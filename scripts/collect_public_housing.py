"""공공임대·공공분양 모집공고 수집기 (소현리치랩).

LH·GH·SH 와 지방 개발공사의 공고를 한 형식으로 모아 data/public_housing.json 에 저장한다.

| 출처 | 방식 | 내용 |
|---|---|---|
| lh     | 공공데이터포털 LH 분양임대공고 조회 API | LH 임대·분양·주거복지 공고 전체(상태·마감일·원문 링크) |
| myhome | 공공데이터포털 마이홈 공공주택 모집공고 API | 단지 주소·공급 호수·보증금·월임대료 (LH 공고에 붙이고, 지방공사 공고는 따로 추가) |
| gh     | GH 주택청약·임대센터 청약공고 목록 화면 | GH 임대주택·매입임대 공고 (robots.txt 전체 허용) |
| sh     | SH 공고 및 공지 게시판 목록 화면 | SH 주택임대·주택분양 게시글 (robots.txt 일반 수집 허용 경로) |

- API 키는 환경 변수 DATA_GO_KR_KEY 로만 받는다. 코드·로그·결과 파일에 남기지 않는다.
- 사이트 화면은 수집기 이름을 그대로 밝힌 User-Agent 로 하루 몇 번, 목록 첫 쪽만 읽는다.
- 상세(첨부파일·일정·단지)는 진행 중 공고만, 공고당 한 번 읽고 이후에는 저장된 값을 다시 쓴다.
  LH 는 공식 상세 API, GH 는 모든 공고, SH 는 모집공고 글만 읽는다. 파일 자체는 내려받지 않고 이름·주소만 남긴다.
- 한 출처가 실패해도 나머지는 저장하고, 실패한 출처는 직전 수집분을 그대로 둔다.

실행: python scripts/collect_public_housing.py [--only lh,myhome,gh,sh] [--days 90]
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "public_housing.json"
KST = timezone(timedelta(hours=9))
UA = "sohyunrichlab-notice-collector/1.0 (+https://revi404.github.io/sohyunrichlab/)"
SOURCES = ("lh", "myhome", "gh", "sh")

LH_LIST = "https://apis.data.go.kr/B552555/lhLeaseNoticeInfo1/lhLeaseNoticeInfo1"
LH_DETAIL = "https://apis.data.go.kr/B552555/lhLeaseNoticeDtlInfo1/getLeaseNoticeDtlInfo1"
LH_KINDS = {"06": "임대", "13": "임대", "05": "분양", "39": "분양"}  # 06 임대주택, 13 주거복지(매입·전세임대), 05 분양주택, 39 신혼희망타운
MYHOME = "https://apis.data.go.kr/1613000/HWSPR02/"
MYHOME_EPS = {"rsdtRcritNtcList": "임대", "ltRsdtRcritNtcList": "분양"}
GH_BASE = "https://apply.gh.or.kr"
# 임대주택 목록과 매입임대 목록. GH 청약센터에는 분양 공고 목록이 따로 없다(분양은 청약홈에서 진행).
GH_LISTS = {"/sb/sr/sr7150/selectPbancRentHouseList.do": "임대", "/sb/sr/sr7155/selectPbancRentHouseList.do": "임대"}
SH_LIST = "https://www.i-sh.co.kr/main/lay2/program/S1T294C297/www/brd/m_247/list.do"
SH_CATS = {"2": "임대", "1": "분양"}  # 공지분류: 1 주택분양, 2 주택임대
# 모집공고가 아닌 게시글(당첨자 발표·접수 결과·안내 등)을 가르는 낱말
FOLLOWUP = re.compile(r"발표|결과|안내|게시|연장|재계약|채용|입찰|이전등기|출시|중단|공개|대상자|변경")


def fetch(url: str, params: dict | None = None, retries: int = 2, timeout: int = 30) -> bytes:
    if params:
        url += "?" + urllib.parse.urlencode(params)
    last: Exception | None = None
    for i in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            # 예외 문구에 주소(키 포함)가 섞이지 않도록 종류만 남긴다
            last = RuntimeError(f"{type(e).__name__} {getattr(e, 'code', '')}".strip())
            time.sleep(2 * (i + 1))
    raise last  # type: ignore[misc]


def text(fragment: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def ymd(value) -> str | None:
    """20261110 · 2026.11.10 · 2026-11-10 → 2026-11-10. 날짜가 아니면 None."""
    m = re.search(r"(20\d{2})[.\-/]?(\d{2})[.\-/]?(\d{2})", str(value or ""))
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else None


def num(value) -> int | None:
    try:
        n = int(float(str(value).replace(",", "")))
    except (TypeError, ValueError):
        return None
    return n


def status_of(start: str | None, end: str | None, today: str) -> str | None:
    if not end:
        return None
    if end < today:
        return "접수마감"
    if start and start > today:
        return "공고중"
    return "접수중" if start else "공고중"


def notice(**kw) -> dict:
    base = dict(id="", org="", deal="", type=None, kind="모집공고", title="", region=None, city=None,
                notice_date=None, apply_start=None, apply_end=None, winner_date=None, status=None,
                units=None, houses=[], url="", src="")
    base.update(kw)
    return base


# ── LH ────────────────────────────────────────────────────────────────────────
def collect_lh(key: str, since: datetime, today: datetime) -> list[dict]:
    out = []
    for code, deal in LH_KINDS.items():
        page = 1
        while page <= 20:
            raw = fetch(LH_LIST, {"serviceKey": key, "PG_SZ": 500, "PAGE": page, "UPP_AIS_TP_CD": code,
                                  "PAN_ST_DT": since.strftime("%Y%m%d"), "PAN_ED_DT": today.strftime("%Y%m%d")})
            data = json.loads(raw)
            rows = next((b["dsList"] for b in data if isinstance(b, dict) and "dsList" in b), [])
            for r in rows:
                out.append(notice(
                    id=f"lh-{r.get('PAN_ID')}", org="LH", deal=deal, type=r.get("AIS_TP_CD_NM"),
                    title=(r.get("PAN_NM") or "").strip(), region=r.get("CNP_CD_NM"),
                    notice_date=ymd(r.get("PAN_NT_ST_DT")) or ymd(r.get("PAN_DT")),
                    apply_end=ymd(r.get("CLSG_DT")), status=r.get("PAN_SS"),
                    url=r.get("DTL_URL") or "", src="lh",
                    _lh={"PAN_ID": r.get("PAN_ID"), "CCR_CNNT_SYS_DS_CD": r.get("CCR_CNNT_SYS_DS_CD"),
                         "SPL_INF_TP_CD": r.get("SPL_INF_TP_CD"), "UPP_AIS_TP_CD": code, "AIS_TP_CD": r.get("AIS_TP_CD")}))
            total = num(rows[0].get("ALL_CNT")) if rows else 0
            if not rows or page * 500 >= (total or 0):
                break
            page += 1
    return out


# ── 마이홈 ────────────────────────────────────────────────────────────────────
def collect_myhome(key: str, since: datetime, today: datetime) -> list[dict]:
    """공고(pblancId) 단위로 묶고, 단지별 조건은 houses 에 담는다."""
    floor = since.strftime("%Y-%m-%d")
    now = today.strftime("%Y-%m-%d")
    out = []
    for ep, deal in MYHOME_EPS.items():
        items, page = [], 1
        while page <= 20:
            body = json.loads(fetch(MYHOME + ep, {"serviceKey": key, "pageNo": page, "numOfRows": 1000}))["response"]["body"]
            got = body.get("item") or []
            items += got
            if not got or len(items) >= (num(body.get("totalCount")) or 0):
                break
            page += 1
        groups: dict[str, dict] = {}
        for it in items:
            pid = str(it.get("pblancId"))
            g = groups.get(pid)
            if g is None:
                start, end = ymd(it.get("beginDe")), ymd(it.get("endDe"))
                org = (it.get("suplyInsttNm") or "").strip()
                g = groups[pid] = notice(
                    id=f"myhome-{'r' if deal == '임대' else 's'}{pid}", org=org, deal=deal, type=it.get("suplyTyNm"),
                    title=(it.get("pblancNm") or "").strip(), region=it.get("brtcNm"), city=it.get("signguNm"),
                    notice_date=ymd(it.get("rcritPblancDe")), apply_start=start, apply_end=end,
                    winner_date=ymd(it.get("przwnerPresnatnDe")), status=status_of(start, end, now),
                    url=it.get("url") or it.get("pcUrl") or "", src="myhome")
                g["_myhome_url"] = it.get("pcUrl")
            house = {"name": it.get("hsmpNm"), "addr": (it.get("fullAdres") or "").strip() or None,
                     "city": it.get("signguNm"), "total_units": num(it.get("totHshldCo")),
                     "units": num(it.get("sumSuplyCo")),
                     "apply_start": ymd(it.get("beginDe")), "apply_end": ymd(it.get("endDe")),
                     # 임대: 보증금·월임대료 / 분양: 계약금·중도금·잔금 (원 단위, 대표 주택형 기준으로 마이홈이 주는 값)
                     "deposit": num(it.get("rentGtn")), "rent": num(it.get("mtRntchrg")),
                     "down": num(it.get("enty")), "middle": num(it.get("prtpay")), "balance": num(it.get("surlus"))}
            # 값이 없어서 0 으로 오는 항목은 뺀다 (중도금 0 은 실제 조건이라 남긴다)
            g["houses"].append({k: v for k, v in house.items() if v not in (None, "") and (v != 0 or k == "middle")})
        for g in groups.values():
            if (g["notice_date"] or "") < floor and (g["apply_end"] or "") < now:
                continue
            units = [h["units"] for h in g["houses"] if h.get("units")]
            g["units"] = sum(units) if units else None
            out.append(g)
    return out


def merge_lh_myhome(lh: list[dict], myhome: list[dict]) -> list[dict]:
    """마이홈 LH 공고는 원문 주소의 panId 로 LH 공고에 붙인다. 못 붙인 것과 다른 기관 공고는 따로 남긴다."""
    by_pan = {n["id"][3:]: n for n in lh}
    rest = []
    for m in myhome:
        pan = re.search(r"panId=(\w+)", m["url"] or "")
        target = by_pan.get(pan.group(1)) if pan else None
        if target is None:
            m.pop("_myhome_url", None)
            rest.append(m)
            continue
        target["houses"] = m["houses"]
        target["units"] = m["units"]
        for k in ("city", "winner_date"):
            target[k] = target[k] or m[k]
        # 접수 시작일은 LH 마감일과 앞뒤가 맞을 때만 쓴다 (단지마다 접수 기간이 다른 공고는 houses 를 볼 것)
        if m["apply_start"] and target["apply_end"] and m["apply_start"] <= target["apply_end"]:
            target["apply_start"] = m["apply_start"]
        target["myhome_url"] = m.get("_myhome_url")
    return lh + rest


# ── GH ────────────────────────────────────────────────────────────────────────
def collect_gh(since: datetime, today: datetime) -> list[dict]:
    floor = since.strftime("%Y-%m-%d")
    now = today.strftime("%Y-%m-%d")
    out = []
    for path, deal in GH_LISTS.items():
        page = fetch(GH_BASE + path).decode("utf-8", "replace")
        body = re.search(r"<tbody.*?</tbody>", page, re.S)
        for row in re.findall(r"<tr.*?</tr>", body.group(0), re.S) if body else []:
            no = re.search(r'data-pbancNo="(\d+)"', row)
            if not no:
                continue
            link = re.search(r"<a\b.*?</a>", row, re.S)
            dates = re.findall(r"\d{4}-\d{2}-\d{2}", text(row))
            cells = [text(c) for c in re.split(r"<td[^>]*>", row)[1:]]
            n = notice(id=f"gh-{no.group(1)}", org="GH", deal=deal,
                       type=(re.search(r'data-bizTyNm="([^"]*)"', row) or [None, None])[1] or (cells[1] if len(cells) > 1 else None),
                       title=text(link.group(0)) if link else "", region="경기도",
                       city=cells[3] if len(cells) > 3 and not re.search(r"\d{4}-", cells[3]) else None,
                       notice_date=dates[0] if dates else None, apply_end=dates[1] if len(dates) > 1 else None,
                       status=next((s for s in ("접수중", "공고중", "접수마감", "공고마감") if s in cells), None),
                       url=GH_BASE + path, src="gh",
                       _gh=GH_BASE + path.replace("selectPbancRentHouseList", "selectPbancDetailView") + "?" + urllib.parse.urlencode(
                           {"pbancNo": no.group(1), "pbancKndCd": (re.search(r'data-pbancKndCd="(\w*)"', row) or [0, "01"])[1], "previewYn": "N"}))
            if (n["notice_date"] or "9") < floor and (n["apply_end"] or "") < now:
                continue
            out.append(n)
        time.sleep(2)
    return out


# ── SH ────────────────────────────────────────────────────────────────────────
def collect_sh(since: datetime, today: datetime) -> list[dict]:
    floor = since.strftime("%Y-%m-%d")
    out, seen = [], set()
    for cat, deal in SH_CATS.items():
        page = fetch(SH_LIST, {"multi_itm_seq": cat}).decode("utf-8", "replace")
        if "getDetailView" not in page:
            raise RuntimeError("SH 목록 화면이 예상과 다름")
        for row in re.findall(r"<tr>.*?</tr>", page, re.S):
            seq = re.search(r"getDetailView\('(\d+)'\)", row)
            if not seq or seq.group(1) in seen:
                continue
            link = re.search(r"<a\b.*?</a>", row, re.S)
            title = re.sub(r"^NEW\s*", "", text(link.group(0))) if link else ""
            date = re.search(r"\d{4}-\d{2}-\d{2}", text(row.split("</a>")[-1]))
            if not title or (date and date.group(0) < floor):
                continue
            seen.add(seq.group(1))
            recruiting = bool(re.search(r"모집", title)) and not FOLLOWUP.search(title)
            out.append(notice(id=f"sh-{seq.group(1)}", org="SH", deal=deal,
                              kind="모집공고" if recruiting else "후속·안내", title=title, region="서울특별시",
                              notice_date=date.group(0) if date else None,
                              url=f"{SH_LIST.replace('list.do', 'view.do')}?seq={seq.group(1)}&multi_itm_seq={cat}", src="sh"))
        time.sleep(2)
    return out


# ── 상세 (첨부파일·일정·단지) ─────────────────────────────────────────────────
ACTIVE = ("공고중", "접수중", "정정공고중")


def clean(d: dict) -> dict:
    return {k: v for k, v in d.items() if v not in (None, "", [], {})}


def lh_detail(key: str, n: dict) -> dict:
    data = json.loads(fetch(LH_DETAIL, {"serviceKey": key, **n["_lh"]}))
    block = {k: v for b in data if isinstance(b, dict) for k, v in b.items() if isinstance(v, list)}
    return clean({
        "files": [clean({"name": f.get("CMN_AHFL_NM"), "kind": f.get("SL_PAN_AHFL_DS_CD_NM"), "url": f.get("AHFL_URL")})
                  for f in block.get("dsAhflInfo", [])],
        # 단지별 위치도·평면도·조감도 등 이미지
        "images": [clean({"site": f.get("LCC_NT_NM"), "name": f.get("CMN_AHFL_NM"), "kind": f.get("LS_SPL_INF_UPL_FL_DS_CD_NM"),
                          "url": f.get("AHFL_URL")}) for f in block.get("dsSbdAhfl", [])],
        "schedule": [clean({"site": r.get("SBD_LGO_NM"), "apply_start": ymd(r.get("SBSC_ACP_ST_DT")),
                            "apply_end": ymd(r.get("SBSC_ACP_CLSG_DT")), "docs_start": ymd(r.get("PPR_ACP_ST_DT")),
                            "docs_end": ymd(r.get("PPR_ACP_CLSG_DT")), "winner_date": ymd(r.get("PZWR_ANC_DT")),
                            "contract_start": ymd(r.get("CTRT_ST_DT")), "contract_end": ymd(r.get("CTRT_ED_DT"))})
                     for r in block.get("dsSplScdl", [])],
        "sites": [clean({"name": r.get("LCC_NT_NM"), "addr": " ".join(x for x in (r.get("LGDN_ADR"), r.get("LGDN_DTL_ADR")) if x),
                         "total_units": num(r.get("HSH_CNT")), "area": r.get("DDO_AR"), "heating": r.get("HTN_FMLA_DESC"),
                         "move_in": r.get("MVIN_XPC_YM")}) for r in block.get("dsSbd", [])],
    })


def gh_detail(n: dict) -> dict:
    page = fetch(n["_gh"]).decode("utf-8", "replace")
    start = page.find("sub_content")
    body = page[start:] if start > 0 else page
    if "상세정보" not in body:
        raise RuntimeError("GH 상세 화면이 예상과 다름")
    files = []
    for href, inner in re.findall(r'<a\s+href="([^"]*selectFileDown\.do[^"]*)"[^>]*>(.*?)</a>', body, re.S):
        name = re.sub(r"\s*\(\d+ Byte\)\s*$", "", text(inner))
        files.append({"name": name, "url": html.unescape(href)})
    plain = text(re.sub(r"<script.*?</script>|<style.*?</style>", " ", body, flags=re.S))

    def span(label: str) -> tuple[str | None, str | None]:
        m = re.search(label + r"\s*:\s*(\d{4}\.\d{2}\.\d{2})[\d: ]*(?:~\s*(\d{4}\.\d{2}\.\d{2}))?", plain)
        return (ymd(m.group(1)), ymd(m.group(2))) if m else (None, None)

    types = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", body, re.S):
        cells = [text(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
        if len(cells) >= 5 and re.fullmatch(r"[\d.]+", cells[1] or "") and re.fullmatch(r"[\d,]+", cells[2] or ""):
            types.append(clean({"type": cells[0], "area": float(cells[1]), "units": num(cells[2]),
                                "deposit": num(cells[3]), "rent": num(cells[4])}))
    addr = re.search(r"소재지\s+(.+?)\s+전용면적", plain)
    units = re.search(r"모집호수\s+([\d,]+)", plain)
    move = re.search(r"입주예정월\s+(\d{4}\.\d{2})", plain)
    online, offline, docs = span("온라인접수기간"), span("현장접수기간"), span("서류제출기간")
    return clean({
        "files": files, "types": types,
        "schedule": [clean({"apply_start": online[0] or offline[0], "apply_end": online[1] or offline[1],
                            "docs_start": docs[0], "docs_end": docs[1], "winner_date": span("당첨자발표일")[0]})],
        "sites": [clean({"addr": addr.group(1) if addr else None, "units": num(units.group(1)) if units else None,
                         "move_in": move.group(1) if move else None})],
    })


def sh_detail(n: dict) -> dict:
    page = fetch(n["url"]).decode("utf-8", "replace")
    files = []
    # 첨부 한 줄 = 파일 이름(existFile 링크) + 미리보기 주소. 화면 위쪽의 확장자 아이콘 설명은 건너뛴다.
    for row in re.findall(r"<tr[^>]*>.*?</tr>", page, re.S):
        name = re.search(r"onclick=\"existFile\([^)]*\)[^>]*>(.*?)</a>", row, re.S)
        if not name:
            continue
        view = re.search(r'href="(/main/com/util/htmlConverter\.do[^"]*)"', row)
        files.append(clean({"name": text(name.group(1)),
                            "preview_url": "https://www.i-sh.co.kr" + html.unescape(view.group(1)) if view else None}))
    return clean({"files": files})


def enrich(notices: list[dict], prev: dict[str, dict], key: str, today: str, limit: int = 200) -> dict:
    """진행 중 공고에 상세(detail)를 붙인다. 제목·마감일이 그대로면 직전 수집분을 다시 쓴다(사이트 재방문 없음)."""
    stat = {"new": 0, "reused": 0, "failed": 0}
    for n in notices:
        old = prev.get(n["id"]) or {}
        if old.get("detail") and old.get("title") == n["title"] and old.get("apply_end") == n["apply_end"]:
            n["detail"] = old["detail"]
            stat["reused"] += 1
            continue
        want = (n["src"] == "lh" and n.get("_lh") and key and n["status"] in ACTIVE) \
            or (n["src"] == "gh" and n.get("_gh")) \
            or (n["src"] == "sh" and n["kind"] == "모집공고")
        if not want or stat["new"] >= limit:
            continue
        try:
            n["detail"] = lh_detail(key, n) if n["src"] == "lh" else gh_detail(n) if n["src"] == "gh" else sh_detail(n)
            n["detail"]["at"] = today
            stat["new"] += 1
        except Exception as e:  # noqa: BLE001
            stat["failed"] += 1
            print(f"[상세] {n['id']} 실패: {e}", file=sys.stderr)
        time.sleep(0.3 if n["src"] == "lh" else 2)
    for n in notices:
        d = n.get("detail") or {}
        sched = (d.get("schedule") or [{}])[0]
        if n["src"] == "gh":  # 목록에 없는 접수 시작일·발표일·호수를 상세에서 채운다
            n["apply_start"] = n["apply_start"] or sched.get("apply_start")
            n["winner_date"] = n["winner_date"] or sched.get("winner_date")
            n["units"] = n["units"] or ((d.get("sites") or [{}])[0]).get("units")
        if n["src"] == "lh" and len(d.get("schedule") or []) == 1:
            start = sched.get("apply_start")
            if start and n["apply_end"] and start <= n["apply_end"]:
                n["apply_start"] = n["apply_start"] or start
            n["winner_date"] = n["winner_date"] or sched.get("winner_date")
    return stat


# ── 실행 ──────────────────────────────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default=",".join(SOURCES), help="수집할 출처 (쉼표 구분)")
    ap.add_argument("--days", type=int, default=90, help="공고일 기준 며칠 전까지 담을지")
    args = ap.parse_args()
    only = [s for s in args.only.split(",") if s in SOURCES]
    today = datetime.now(KST)
    since = today - timedelta(days=args.days)
    key = os.environ.get("DATA_GO_KR_KEY", "").strip()

    prev = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {"sources": {}, "notices": []}
    kept = {s: [n for n in prev.get("notices", []) if n.get("src") == s] for s in SOURCES}
    meta = dict(prev.get("sources", {}))
    fresh: dict[str, list[dict]] = {}

    jobs = {"lh": lambda: collect_lh(key, since, today), "myhome": lambda: collect_myhome(key, since, today),
            "gh": lambda: collect_gh(since, today), "sh": lambda: collect_sh(since, today)}
    for s in only:
        stamp = today.strftime("%Y-%m-%d %H:%M")
        try:
            if s in ("lh", "myhome") and not key:
                raise RuntimeError("DATA_GO_KR_KEY 없음")
            fresh[s] = jobs[s]()
            meta[s] = {"ok": True, "at": stamp, "count": len(fresh[s])}
            print(f"[{s}] {len(fresh[s])}건")
        except Exception as e:  # noqa: BLE001
            meta[s] = {"ok": False, "at": stamp, "error": str(e)[:120],
                       "last_ok": (prev.get("sources", {}).get(s) or {}).get("at") if (prev.get("sources", {}).get(s) or {}).get("ok") else (prev.get("sources", {}).get(s) or {}).get("last_ok")}
            print(f"[{s}] 실패: {e}", file=sys.stderr)

    lh = fresh.get("lh")
    myhome = fresh.get("myhome")
    if lh is not None and myhome is not None:
        api = merge_lh_myhome(lh, myhome)
    else:  # 한쪽만 새로 받았으면 다른 쪽은 직전 수집분을 쓴다
        api = (lh if lh is not None else kept["lh"]) + (myhome if myhome is not None else kept["myhome"])
    notices = api + fresh.get("gh", kept["gh"]) + fresh.get("sh", kept["sh"])
    stat = enrich(notices, {n["id"]: n for n in prev.get("notices", [])}, key, today.strftime("%Y-%m-%d"))
    print(f"[상세] 새로 {stat['new']}건, 재사용 {stat['reused']}건, 실패 {stat['failed']}건")
    for n in notices:
        for k in [k for k in n if k.startswith("_")]:
            del n[k]
    notices.sort(key=lambda n: (n.get("notice_date") or "", n["id"]), reverse=True)

    body = {"sources": meta, "notices": notices}
    old_body = {"sources": {k: {x: y for x, y in v.items() if x != "at"} for k, v in prev.get("sources", {}).items()},
                "notices": prev.get("notices", [])}
    new_body = {"sources": {k: {x: y for x, y in v.items() if x != "at"} for k, v in meta.items()}, "notices": notices}
    if old_body == new_body and all(m.get("ok") for m in meta.values()):
        print("바뀐 내용 없음")
        return 0
    result = {"updated": today.strftime("%Y-%m-%d %H:%M"),
              "source_note": "LH·마이홈: 공공데이터포털 API / GH: 주택청약·임대센터 청약공고 / SH: 공고 및 공지 게시판",
              **body}
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"저장: {OUT.relative_to(ROOT)} ({len(notices)}건)")
    return 0 if any(m.get("ok") for m in meta.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
