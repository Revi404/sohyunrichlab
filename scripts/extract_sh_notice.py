"""SH 공고문 '미리보기 변환본'에서 글을 읽어 data/notice_text/<공고 id>.json 으로 남긴다 (소현리치랩).

SH 공고 첨부의 preview_url(htmlConverter.do)은 Synap Document Viewer 화면(doc.html?fn=..&rs=..)으로 넘어간다.
화면이 읽는 변환 파일(<rs><fn>.xml 색인과 쪽별 파일)을 받아 글을 뽑는다. 원본 PDF 는 받지 않는다.
색인(<index>)에는 file_type, pdf_cnt(쪽 수)와 쪽마다 path_html(rs 기준 상대 경로)이 들어 있다.
- path_html 이 그림(.png/.jpg/.jpeg/.gif)이면 PDF 를 쪽별 그림으로 바꾼 것이라 글이 없다.
  임시 폴더에 받아 글자 인식(OCR: Pillow 로 확대·회색조 → tesseract)한다. 그림은 끝나면 지우고 저장소에 남기지 않는다.
- path_html 이 글 형식(.htm/.html/.xml/.svg/.txt)이면 받아서 태그를 벗겨 글로 만든다.
- path_html 이 없으면 색인에서 파일 이름을 찾아 여러 주소를 시험한다.

- 대상 지정: python scripts/extract_sh_notice.py --ids sh-313161,sh-312903
- 자동:     python scripts/extract_sh_notice.py --auto [--max 3]
  아직 뽑지 않은 SH 모집공고를 공고일이 최근인 것부터 고른다.
- 진단:     --debug (색인 요약, 쪽별 상태·바이트·글자 수, 앞 4쪽 글 전문, 합계·걸린 시간)
- 글자 인식: --ocr-scale 3 (확대 배율), --psm 6 (tesseract 쪽 분할 방식)
- 시험:     --src 공고 파일, --out 출력 폴더

변환 파일 요청은 리다이렉트를 따라가지 않는다. 없는 파일이 302 로 응답하기 때문이다(없음으로 처리).
요청은 공고 1건당 80회, 요청 사이 1초, 쪽(파일) 5MB·최대 40쪽. 글 형식만 읽을 때는 표준 라이브러리만 쓴다.
글자 인식에는 Pillow 와 tesseract(kor+eng)가 필요하다.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
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
MAX_PAGES = 40             # 한 공고에서 읽을 최대 쪽 수
OCR_SCALE = 3
OCR_PSM = 6
OCR_TIMEOUT = 180          # 쪽당 tesseract 제한 시간(초)
IMG_EXT = (".png", ".jpg", ".jpeg", ".gif")
TEXT_EXT = (".htm", ".html", ".xml", ".svg", ".txt")
OCR_NOTE = "글자 인식 결과라 숫자·표가 틀릴 수 있음. 금액은 원문 확인 필요"
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
        self.total_img = 0
        self.last = 0.0
        self.plain = urllib.request.build_opener(NoRedirect)
        self.follow = urllib.request.build_opener()

    def get(self, url: str, follow: bool = False, read_any: bool = False, track: bool = True) -> Resp:
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
        if track:  # 쪽 그림은 임시 폴더에서 바로 지우므로 합계 상한에 넣지 않는다(쪽당 5MB 만 막는다)
            self.total += len(body)
        else:
            self.total_img += len(body)
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




class OcrError(Exception):
    """글자 인식 도구(Pillow·tesseract)가 없거나 쓸 수 없다."""


def parse_index(index_text: str) -> tuple[str, int, list[str]]:
    """색인에서 file_type, 쪽 수(pdf_cnt), path_html 목록(나온 순서)을 읽는다. 태그 이름이 pdf 가 아니어도 path_html 이면 모은다."""
    ftype, cnt, paths = "", 0, []
    try:
        root = ET.fromstring(index_text.encode("utf-8"))
    except (ET.ParseError, ValueError):
        return ftype, cnt, paths
    for el in root.iter():
        tag = el.tag.split("}")[-1].lower()
        val = (el.text or "").strip()
        if tag == "file_type" and val:
            ftype = val.lower()
        elif tag == "pdf_cnt" and val.isdigit():
            cnt = int(val)
        elif tag == "path_html" and val:
            paths.append(val)
    return ftype, cnt, paths


def ext_of(path: str) -> str:
    return Path(urllib.parse.urlparse(path).path).suffix.lower()


def ocr_image(img_path: Path, scale: int = OCR_SCALE, psm: int = OCR_PSM) -> str:
    """그림 한 장을 글자로 읽는다. Pillow 로 확대(LANCZOS)·회색조 한 뒤 tesseract 를 부른다."""
    try:
        from PIL import Image  # 글 형식만 읽을 때는 필요 없으므로 여기서 불러온다
    except ImportError as e:
        raise OcrError("Pillow 가 없어 글자 인식을 못 함 (pip install pillow)") from e
    exe = shutil.which("tesseract")
    if not exe:
        raise OcrError("tesseract 가 없어 글자 인식을 못 함 (apt-get install tesseract-ocr tesseract-ocr-kor)")
    with Image.open(img_path) as im:
        im = im.convert("L")
        im = im.resize((im.width * scale, im.height * scale), Image.LANCZOS)
        big = img_path.with_name(img_path.stem + "_ocr.png")
        im.save(big)
    try:
        p = subprocess.run([exe, str(big), "stdout", "-l", "kor+eng", "--psm", str(psm)],
                           capture_output=True, timeout=OCR_TIMEOUT)
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"tesseract {OCR_TIMEOUT}초 초과") from e
    if p.returncode != 0:
        err = p.stderr.decode("utf-8", "replace").strip()
        if "language" in err.lower() or "traineddata" in err.lower():
            raise OcrError(f"tesseract 한글 데이터(kor)가 없음: {err[:200]}")
        raise RuntimeError(f"tesseract 오류 {p.returncode}: {err[:200]}")
    return tidy(p.stdout.decode("utf-8", "replace"))


def extract_legacy(f: Fetcher, rs_url: str, fn: str, index_url: str, r2: Resp, index_text: str, dbg: Dbg) -> list[str]:
    """색인에 path_html 이 없을 때: 색인에서 이름을 찾아 여러 주소를 시험한다. 쪽(글) 목록을 돌려준다."""
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
    try:
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
    return [p["text"] for p in parts]


def show_page(dbg: Dbg, i: int, text: str) -> None:
    """--debug: 앞 4쪽은 글 전문(쪽당 2500자까지), 나머지는 앞 300자."""
    if i <= 4:
        dbg(f"    --- {i}쪽 글 ---\n{text[:2500]}" + ("\n    ...(2500자에서 자름)" if len(text) > 2500 else ""))
    else:
        dbg(f"    글 앞 300자: {text[:300]!r}")


def extract_one(n: dict, f_info: dict, dbg: Dbg, scale: int = OCR_SCALE, psm: int = OCR_PSM) -> tuple[dict | None, str]:
    """공고 하나를 읽는다. (결과, 실패 사유)를 돌려준다."""
    t0 = time.monotonic()
    f = Fetcher()
    dbg(f"=== {n['id']} {n['title']}\n파일: {f_info['name']}\npreview_url: {f_info['preview_url']}")
    texts: list[str] = []
    ocr, total_pages = False, 0
    try:
        # (1) 미리보기 주소를 따라가 doc.html 의 최종 주소를 얻는다
        r1 = f.get(f_info["preview_url"], follow=True, read_any=True)
        dbg(f"(1) 최종 주소: {r1.final} [{r1.status}] 형식={r1.ctype} {r1.size}B {r1.error}")
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

        # (3) 색인 읽기: file_type, 쪽 수, path_html 목록
        ftype, cnt, paths = parse_index(index_text)
        total_pages = cnt or len(paths)
        dbg(f"(3) 색인 요약: file_type={ftype or '-'} 쪽 수={total_pages} (pdf_cnt={cnt}, path_html {len(paths)}개) 첫 path_html={paths[0] if paths else '-'}")
        if not paths:
            dbg("    path_html 이 없어 이름 찾기 방식으로 넘어감")
            dbg(f"    색인 앞 4000자:\n{index_text[:4000]}")
            texts = extract_legacy(f, rs_url, fn, index_url, r2, index_text, dbg)
            total_pages = len(texts)
        else:
            if len(paths) > MAX_PAGES:
                dbg(f"    쪽이 {len(paths)}개라 앞 {MAX_PAGES}쪽만 읽음")
            tmp = tempfile.TemporaryDirectory(prefix="shnotice_")  # 끝나면 그림이 함께 지워진다
            with tmp:
                for i, ph in enumerate(paths[:MAX_PAGES], 1):
                    url = urllib.parse.urljoin(rs_url, urllib.parse.quote(ph, safe="/%:@"))
                    ext = ext_of(ph)
                    is_img = ext in IMG_EXT
                    r = f.get(url, read_any=True, track=not is_img)
                    dbg(f"  [{i}쪽] [{r.status}] {url}\n    형식={r.ctype or '-'} 바이트={r.size} {r.error}")
                    txt = ""
                    if r.status == 200 and r.body is not None:
                        if is_img:
                            ocr = True
                            img = Path(tmp.name) / f"p{i}{ext}"
                            img.write_bytes(r.body)
                            try:
                                txt = ocr_image(img, scale, psm)
                            except OcrError:
                                raise
                            except Exception as e:  # noqa: BLE001  한 쪽 실패는 빈 글로 두고 계속
                                dbg(f"    글자 인식 실패: {type(e).__name__} {e}")
                            finally:
                                for x in Path(tmp.name).glob(f"p{i}*"):  # 쪽마다 바로 지운다
                                    x.unlink(missing_ok=True)
                        elif ext in TEXT_EXT or not is_img:
                            txt = text_of(r)
                    dbg(f"    글자 수={len(txt)}")
                    show_page(dbg, i, txt)
                    texts.append(txt)
    except OcrError as e:
        return None, f"글자 인식 도구 오류: {e}"
    except Budget as e:
        dbg(f"!! {e} 에 닿아 중단")
        if not any(texts):
            return None, f"{e}에 닿음, 읽은 글 없음"
    except Exception as e:  # noqa: BLE001
        return None, f"{type(e).__name__} {e}"

    pages = [{"page": i, "text": t} for i, t in enumerate(texts, 1)]
    chars = sum(len(t) for t in texts)
    ok = chars >= MIN_CHARS * min(total_pages or len(texts), 3)
    dbg(f"합계: 요청 {f.count}회, 받은 {f.total + f.total_img:,}바이트, 읽은 쪽 {len(pages)}/{total_pages}, 글자 {chars:,}자, 걸린 시간 {time.monotonic() - t0:.1f}초")
    result = {"id": n["id"], "org": n["org"], "title": n["title"], "notice_date": n.get("notice_date"), "url": n["url"],
              "file": {"name": f_info["name"], "preview_url": f_info["preview_url"]},
              "extracted": datetime.now(KST).strftime("%Y-%m-%d %H:%M"),
              "engine": "synap-preview-ocr" if ocr else "synap-preview", "ocr": ocr,
              "total_pages": total_pages, "text_ok": ok, "pages": pages}
    if ocr:
        result["note"] = OCR_NOTE
    return result, ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", default="", help="공고 id (쉼표 구분)")
    ap.add_argument("--auto", action="store_true")
    ap.add_argument("--max", type=int, default=3, help="--auto 에서 한 번에 뽑을 공고 수")
    ap.add_argument("--force", action="store_true", help="이미 뽑은 공고도 다시 뽑기")
    ap.add_argument("--debug", action="store_true", help="진단 출력(항상 종료 코드 0)")
    ap.add_argument("--ocr-scale", type=int, default=OCR_SCALE, help="글자 인식 전 그림 확대 배율 (기본 3)")
    ap.add_argument("--psm", type=int, default=OCR_PSM, help="tesseract 쪽 분할 방식 (기본 6)")
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
    failed = 0
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
            result, why = extract_one(n, f_info, dbg, args.ocr_scale, args.psm)
        finally:
            dbg.flush()
        if result is None:
            print(f"[{nid}] 실패: {why}", file=sys.stderr)
            failed += 1
            continue
        chars = sum(len(p["text"]) for p in result["pages"])
        if not result["text_ok"]:
            print(f"[{nid}] 글자 {chars}자뿐이라 저장하지 않음(글 뽑기 실패)", file=sys.stderr)
            failed += 1
            continue
        target.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"[{nid}] {len(result['pages'])}쪽, 글자 {chars:,}자 → {target}")
    if args.debug:
        return 0
    return 1 if failed and failed == len(ids) else 0


if __name__ == "__main__":
    sys.exit(main())
