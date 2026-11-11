"""SH 공고문 '미리보기 변환본'에서 글을 읽어 data/notice_text/<공고 id>.json 으로 남긴다 (소현리치랩).

SH 공고 첨부의 preview_url(htmlConverter.do)은 Synap Document Viewer 화면(doc.html?fn=..&rs=..)으로 넘어간다.
화면이 읽는 변환 파일(<rs><fn>.xml 색인과 쪽별 파일)을 받아 글만 뽑는다. 원본 PDF 는 받지 않는다.
쪽별 파일의 이름·형식은 아직 확정되지 않아 색인에서 이름을 찾아 여러 주소를 시험한다. --debug 로 진단을 본다.

- 대상 지정: python scripts/extract_sh_notice.py --ids sh-313161,sh-312903
- 자동:     python scripts/extract_sh_notice.py --auto [--max 3]
  아직 뽑지 않은 SH 모집공고를 공고일이 최근인 것부터 고른다.
- 진단:     --debug (주소·상태·형식·글 앞부분 출력), --debug-js (뷰어 스크립트에서 주소 조립 부분 출력)
- 시험:     --src 공고 파일, --out 출력 폴더

변환 파일 요청은 리다이렉트를 따라가지 않는다. 없는 파일이 302 로 응답하기 때문이다(없음으로 처리).
요청은 공고 1건당 80회, 요청 사이 1초, 파일 5MB·합계 20MB 이내. 표준 라이브러리만 쓴다.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "public_housing.json"
OUT = ROOT / "data" / "notice_text"
KST = timezone(timedelta(hours=9))
UA = "sohyunrichlab-notice-collector/1.0 (+https://revi404.github.io/sohyunrichlab/)"
MAX_REQUESTS = 80          # 공고 1건당 요청 상한
DELAY = 1.0                # 요청 사이 쉬는 시간(초)
TIMEOUT = 30
MAX_FILE = 5 * 1024 * 1024
MAX_TOTAL = 20 * 1024 * 1024
DEBUG_LIMIT = 60000
MIN_CHARS = 200
NAME_RE = re.compile(r"[\w\-./%]+\.(?:xml|htm|html|svg|json|txt)\b", re.I)
TEXT_TYPES = ("xml", "html", "svg", "json", "text/")
BAD_FILE = ("양식", "서식", "신청서")


class Budget(Exception):
    """요청·용량 상한에 닿았다."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):  # 따라가지 않고 3xx 를 그대로 돌려받는다
        return None


class Resp:
    def __init__(self, status: int, ctype: str = "", body: bytes | None = None, size: int = 0, final: str = "", error: str = ""):
        self.status, self.ctype, self.body, self.size, self.final, self.error = status, ctype, body, size, final, error


class Fetcher:
    """요청 횟수·간격·용량을 관리하며 받는다."""

    def __init__(self) -> None:
        self.count = 0
        self.total = 0
        self.last = 0.0
        self.plain = urllib.request.build_opener(NoRedirect)
        self.follow = urllib.request.build_opener()

    def get(self, url: str, follow: bool = False, read_any: bool = False) -> Resp:
        if self.count >= MAX_REQUESTS:
            raise Budget("요청 상한")
        if self.total >= MAX_TOTAL:
            raise Budget("용량 상한")
        wait = DELAY - (time.monotonic() - self.last)
        if self.count and wait > 0:
            time.sleep(wait)
        self.count += 1
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
        try:
            r = (self.follow if follow else self.plain).open(req, timeout=TIMEOUT)
        except urllib.error.HTTPError as e:  # 3xx(따라가지 않을 때)·4xx·5xx
            self.last = time.monotonic()
            return Resp(e.code, e.headers.get("Content-Type", "") or "", None, 0, url)
        except Exception as e:  # noqa: BLE001
            self.last = time.monotonic()
            return Resp(0, "", None, 0, url, f"{type(e).__name__} {e}")
        with r:
            ctype = (r.headers.get("Content-Type") or "").lower()
            final = r.geturl()
            textual = read_any or any(t in ctype for t in TEXT_TYPES) or ctype.split(";")[0].strip() in ("", "application/octet-stream")
            if not textual:  # 그림 등은 받지 않는다
                self.last = time.monotonic()
                return Resp(r.status, ctype, None, int(r.headers.get("Content-Length") or 0), final)
            body = r.read(MAX_FILE + 1)
        self.last = time.monotonic()
        if len(body) > MAX_FILE:
            return Resp(r.status, ctype, None, len(body), final, "5MB 초과")
        self.total += len(body)
        return Resp(r.status, ctype, body, len(body), final)


class Dbg:
    """--debug 진단을 모아 두었다가 60,000자 이내로 출력한다."""

    def __init__(self, on: bool) -> None:
        self.on, self.lines = on, []

    def __call__(self, s: str = "") -> None:
        if self.on:
            self.lines.append(s)

    def flush(self) -> None:
        if self.on:
            out = "\n".join(self.lines)
            print(out[:DEBUG_LIMIT] + ("\n...(60,000자에서 자름)" if len(out) > DEBUG_LIMIT else ""))
            self.lines = []


class TextOf(HTMLParser):
    """태그를 벗기고 글만 모은다. script/style 안은 뺀다."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.skip:
            self.skip -= 1
        if tag in ("p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "table"):
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def decode(r: Resp) -> str:
    m = re.search(r"charset=([\w\-]+)", r.ctype)
    for enc in ([m.group(1)] if m else []) + ["utf-8", "cp949"]:
        try:
            return (r.body or b"").decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return (r.body or b"").decode("utf-8", "replace")


def tidy(s: str) -> str:
    s = s.replace("\xa0", " ")
    lines = [re.sub(r"[ \t\r\f\v]+", " ", ln).strip() for ln in s.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def text_of(r: Resp) -> str:
    """응답 본문에서 글만 뽑는다. 글 형식이 아니면 빈 문자열."""
    if r.body is None:
        return ""
    raw = decode(r)
    ctype = r.ctype
    if "json" in ctype or raw.lstrip()[:1] in "{[":
        try:
            strs: list[str] = []

            def walk(v):
                if isinstance(v, str):
                    strs.append(v)
                elif isinstance(v, dict):
                    for x in v.values():
                        walk(x)
                elif isinstance(v, list):
                    for x in v:
                        walk(x)

            walk(json.loads(raw))
            return tidy("\n".join(strs))
        except ValueError:
            pass
    if "html" in ctype or "xml" in ctype or "svg" in ctype or raw.lstrip()[:1] == "<":
        p = TextOf()
        try:
            p.feed(raw)
            p.close()
        except Exception:  # noqa: BLE001
            pass
        return tidy("".join(p.parts))
    return tidy(raw)


def pick_file(n: dict) -> dict | None:
    """preview_url 이 있는 첨부 가운데 공고문 하나를 고른다. pdf > hwp/hwpx > 그 외, 없으면 첫 파일."""
    files = [f for f in (n.get("detail") or {}).get("files", []) if f.get("preview_url")]
    if not files:
        return None

    def rank(f: dict) -> tuple[int, int]:
        name = (f.get("name") or "").lower()
        is_notice = "공고" in name and not any(w in name for w in BAD_FILE)
        ext = 0 if name.endswith(".pdf") else 1 if name.endswith((".hwp", ".hwpx")) else 2
        return (0 if is_notice else 1, ext)

    return min(files, key=rank)  # min 은 동순위에서 앞선 것을 쓴다


def collect_names(index_text: str) -> tuple[list[str], list[int]]:
    """색인에서 파일 이름처럼 보이는 문자열과 쪽 수로 보이는 숫자를 찾는다."""
    found: list[str] = []
    values = [index_text]
    counts: list[int] = []
    try:
        root = ET.fromstring(index_text.encode("utf-8") if not index_text.lstrip().startswith("<?xml") else index_text.encode("utf-8"))
        for el in root.iter():
            tag = el.tag.split("}")[-1]
            if el.text and el.text.strip():
                values.append(el.text)
                if re.search(r"page|count|total", tag, re.I) and el.text.strip().isdigit():
                    counts.append(int(el.text.strip()))
            for k, v in el.attrib.items():
                values.append(v)
                if re.search(r"page|count|total", k, re.I) and v.strip().isdigit():
                    counts.append(int(v.strip()))
    except (ET.ParseError, ValueError):
        pass
    for v in values:
        for m in NAME_RE.finditer(v):
            found.append(m.group(0))
    return list(dict.fromkeys(found)), [c for c in counts if 0 < c <= 2000]


def read_part(name: str, url: str, r: Resp, dbg: Dbg) -> tuple[dict | None, str]:
    txt = text_of(r)
    raw = decode(r) if r.body is not None else ""
    dbg(f"  [{r.status}] {url}\n    형식={r.ctype or '-'} 바이트={r.size} 글자={len(txt)}")
    if r.body is not None:
        dbg(f"    글 앞 300자: {txt[:300]!r}\n    원문 앞 300자: {raw[:300]!r}")
    return ({"name": name, "chars": len(txt), "text": txt} if txt else None), txt


def run_debug_js(f: Fetcher, doc_url: str, doc_html: str) -> None:
    """뷰어 스크립트에서 .xml/.files/rs/fn 이 함께 쓰이는 곳을 찾아 앞뒤 120자씩 출력한다."""
    print("== debug-js ==")
    srcs = re.findall(r"<script[^>]+src=[\"']([^\"']+)[\"']", doc_html, re.I)
    print("script src:", srcs)
    targets = [s for s in srcs if re.search(r"newviewer|config\.js", s)]
    snippets: list[str] = []
    for s in targets:
        url = urllib.parse.urljoin(doc_url, s)
        try:
            r = f.get(url, follow=False, read_any=True)
        except Budget:
            break
        print(f"-- {url} [{r.status}] {r.ctype} {r.size}B")
        if r.body is None:
            continue
        js = decode(r)
        if "config.js" in s:
            print(js[:4000])
        tiers = [lambda w: ".xml" in w and ".files" in w and re.search(r"\brs\b", w) and re.search(r"\bfn\b", w),
                 lambda w: ".files" in w and (re.search(r"\brs\b", w) or re.search(r"\bfn\b", w)),
                 lambda w: ".xml" in w and re.search(r"\brs\b", w) and re.search(r"\bfn\b", w)]
        seen_pos: list[int] = []
        for ok in tiers:
            for m in re.finditer(r"\.xml|\.files", js):
                if len(snippets) >= 40:
                    break
                if any(abs(m.start() - p) < 120 for p in seen_pos):
                    continue
                w = js[max(0, m.start() - 120): m.end() + 120]
                if ok(w):
                    seen_pos.append(m.start())
                    snippets.append(f"[{Path(s).name} @{m.start()}] {w!r}")
    print(f"조각 {len(snippets)}개")
    for sn in snippets[:40]:
        print(sn)


def extract_one(n: dict, f_info: dict, dbg: Dbg, want_js: bool) -> tuple[dict | None, str]:
    """공고 하나를 읽는다. (결과, 실패 사유)를 돌려준다."""
    f = Fetcher()
    dbg(f"=== {n['id']} {n['title']}\n파일: {f_info['name']}\npreview_url: {f_info['preview_url']}")
    try:
        # (1) 미리보기 주소를 따라가 doc.html 의 최종 주소를 얻는다
        r1 = f.get(f_info["preview_url"], follow=True, read_any=True)
        dbg(f"(1) 최종 주소: {r1.final} [{r1.status}] 형식={r1.ctype} {r1.size}B {r1.error}")
        if want_js and r1.body is not None:
            run_debug_js(f, r1.final, decode(r1))
        q = urllib.parse.parse_qs(urllib.parse.urlparse(r1.final).query)
        fn, rs = (q.get("fn") or [""])[0], (q.get("rs") or [""])[0]
        dbg(f"fn={fn!r}\nrs={rs!r}")
        if not fn or not rs:
            return None, "최종 주소에서 fn, rs 를 찾지 못함"
        rs_url = urllib.parse.urljoin(r1.final, rs if rs.endswith("/") else rs + "/")

        # (2) 색인
        index_url = rs_url + fn + ".xml"
        r2 = f.get(index_url)
        dbg(f"(2) 색인: {index_url}\n    상태={r2.status} 형식={r2.ctype or '-'} 바이트={r2.size} {r2.error}")
        if r2.status != 200 or r2.body is None:
            return None, f"색인을 받지 못함(상태 {r2.status})"
        index_text = decode(r2)
        dbg(f"    색인 앞 4000자:\n{index_text[:4000]}")

        # (3) 색인에서 이름·쪽 수 찾기
        names, counts = collect_names(index_text)
        names = [x for x in names if x != fn + ".xml"]
        dbg(f"(3) 찾은 이름 {len(names)}개: {names}\n    쪽 수 후보: {counts}")
        parts: list[dict] = []
        idx_txt = text_of(r2)
        if idx_txt:
            parts.append({"name": fn + ".xml", "chars": len(idx_txt), "text": idx_txt})
        done = {index_url}

        def bases() -> list[str]:
            return [rs_url, rs_url + fn + "/", rs_url + fn + ".files/", rs_url + fn + "_files/"]

        pref: int | None = None  # 성공한 기준 위치를 먼저 시험해 요청을 아낀다
        for name in names:
            order = list(range(4))
            if pref is not None:
                order.remove(pref)
                order.insert(0, pref)
            for i in order:
                url = urllib.parse.urljoin(bases()[i], name)
                if url in done:
                    continue
                done.add(url)
                r = f.get(url)
                part, _ = read_part(name, url, r, dbg)
                if r.status == 200:
                    if part:
                        parts.append(part)
                    pref = i
                    break

        # 쪽 수가 보이면 흔한 쪽 파일 이름 규칙을 1쪽만 시험하고, 되는 규칙으로 전 쪽을 읽는다
        if counts:
            total = max(counts)
            rules = [fn + ".files/{}.xml", fn + ".files/page{}.xml", fn + "_{}.xml", fn + ".files/{}.htm", fn + ".files/{}.svg"]
            dbg(f"쪽 규칙 시험(쪽 수 {total})")
            for rule in rules:
                url = urllib.parse.urljoin(rs_url, rule.format(1))
                if url in done:
                    continue
                done.add(url)
                r = f.get(url)
                part, _ = read_part(rule.format(1), url, r, dbg)
                if r.status != 200:
                    continue
                if part:
                    parts.append(part)
                dbg(f"  → 규칙 채택: {rule}")
                for p in range(2, total + 1):
                    url = urllib.parse.urljoin(rs_url, rule.format(p))
                    if url in done:
                        continue
                    done.add(url)
                    r = f.get(url)
                    part, _ = read_part(rule.format(p), url, r, dbg)
                    if r.status != 200:
                        break
                    if part:
                        parts.append(part)
                break
    except Budget as e:
        dbg(f"!! {e} 에 닿아 중단")
        parts = locals().get("parts", [])
        if not parts:
            return None, f"{e}에 닿음, 읽은 글 없음"
    except Exception as e:  # noqa: BLE001
        return None, f"{type(e).__name__} {e}"

    chars = sum(p["chars"] for p in parts)
    dbg(f"합계: 요청 {f.count}회, 받은 {f.total:,}바이트, part {len(parts)}개, 글자 {chars:,}자")
    result = {"id": n["id"], "org": n["org"], "title": n["title"], "notice_date": n.get("notice_date"), "url": n["url"],
              "file": {"name": f_info["name"], "preview_url": f_info["preview_url"]},
              "extracted": datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "engine": "synap-preview",
              "total_parts": len(parts), "text_ok": chars >= MIN_CHARS, "parts": parts}
    return result, ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", default="", help="공고 id (쉼표 구분)")
    ap.add_argument("--auto", action="store_true")
    ap.add_argument("--max", type=int, default=3, help="--auto 에서 한 번에 뽑을 공고 수")
    ap.add_argument("--force", action="store_true", help="이미 뽑은 공고도 다시 뽑기")
    ap.add_argument("--debug", action="store_true", help="진단 출력(항상 종료 코드 0)")
    ap.add_argument("--debug-js", action="store_true", help="뷰어 스크립트의 주소 조립 부분 출력")
    ap.add_argument("--src", default=str(SRC), help="공고 파일 (기본 data/public_housing.json)")
    ap.add_argument("--out", default=str(OUT), help="출력 폴더 (기본 data/notice_text)")
    args = ap.parse_args()
    out = Path(args.out)
    notices = {n["id"]: n for n in json.loads(Path(args.src).read_text(encoding="utf-8"))["notices"]}

    ids = [i.strip() for i in args.ids.split(",") if i.strip()]
    if args.auto:
        auto = [n for n in notices.values()
                if n.get("src") == "sh" and n.get("kind") == "모집공고" and pick_file(n)
                and not (out / f"{n['id']}.json").exists()]
        auto.sort(key=lambda n: n.get("notice_date") or "", reverse=True)
        ids += [n["id"] for n in auto[: args.max]]
    if not ids:
        print("뽑을 공고 없음")
        return 0

    out.mkdir(parents=True, exist_ok=True)
    ids = list(dict.fromkeys(ids))
    failed, first = 0, True
    for nid in ids:
        n = notices.get(nid)
        target = out / f"{nid}.json"
        if n is None:
            print(f"[{nid}] 공고 파일에 없는 id", file=sys.stderr)
            failed += 1
            continue
        if target.exists() and not args.force:
            print(f"[{nid}] 이미 있음")
            continue
        f_info = pick_file(n)
        if f_info is None:
            print(f"[{nid}] 미리보기 주소가 있는 첨부 없음", file=sys.stderr)
            failed += 1
            continue
        dbg = Dbg(args.debug)
        try:
            result, why = extract_one(n, f_info, dbg, args.debug_js and first)
        finally:
            dbg.flush()
        first = False
        if result is None:
            print(f"[{nid}] 실패: {why}", file=sys.stderr)
            failed += 1
            continue
        chars = sum(p["chars"] for p in result["parts"])
        if not result["text_ok"]:
            print(f"[{nid}] 글자 {chars}자뿐이라 저장하지 않음(글 뽑기 실패)", file=sys.stderr)
            failed += 1
            continue
        target.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"[{nid}] part {result['total_parts']}개, 글자 {chars:,}자 → {target}")
    if args.debug:
        return 0
    return 1 if failed and failed == len(ids) else 0


if __name__ == "__main__":
    sys.exit(main())
