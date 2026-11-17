"""단지 소개 글 만들기 (소현리치랩 공공임대 단지 한 곳 = 글 한 편).

SH 주택정보 수집 결과(data/sh_houses.json)의 단지마다 티스토리 글쓰기 HTML 모드에 그대로 붙여 넣을 글을 만든다.

| 결과 | 내용 |
|---|---|
| posts/complex/<단지 id>.html | 티스토리 글(자세한 표·평면도). 첫 줄 주석에 권장 제목·태그 |
| posts/naver/<단지 id>.html   | 네이버 블로그 요약 글(질문형, 평면도 1장). 티스토리 글과 문장이 겹치지 않게 따로 쓴다 |
| data/complex_posts.json      | 글 목록과 발행 순서(queue: 티스토리, naver_queue: 네이버). 노트북 자동 발행(publisher/)이 위에서부터 꺼내 쓴다 |
| data/published.json          | 이미 발행한 글 기록(발행하는 쪽이 채운다). 여기 있는 단지는 queue 에서 빠진다 |

- 평면도를 모두 받아 둔 단지만 글로 만든다(평면도가 글의 핵심이라서). 나머지는 평면도가 받아지면 자동으로 추가된다.
- 발행 순서: 공가(바로 들어갈 수 있는 빈집)가 있는 단지 → 세대수가 많은 단지. 같은 자치구가 연달아 나오지 않게 섞는다.
- 티스토리 편집기가 지우지 않도록 스크립트·style 태그 없이 태그마다 style 속성으로만 꾸민다.
- 숫자는 SH 화면에 나온 값 그대로 쓰고, 없는 값은 쓰지 않는다(추정하지 않는다).

실행: python scripts/build_complex_posts.py
"""
from __future__ import annotations

import html
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOUSES = ROOT / "data" / "sh_houses.json"
MANIFEST = ROOT / "data" / "plans.json"
OUT = ROOT / "posts" / "complex"
NAVER_OUT = ROOT / "posts" / "naver"
INDEX = ROOT / "data" / "complex_posts.json"
PUBLISHED = ROOT / "data" / "published.json"
SITE = "https://revi404.github.io/sohyunrichlab/"
SH_URL = "https://www.i-sh.co.kr/houseinfo/main/mainPage.do"
NOTICE_URL = "https://www.i-sh.co.kr/main/lay2/program/S1T294C297/www/brd/m_247/list.do"

INK, SOFT, LINE, ACCENT, PAPER = "#121a2b", "#4f5970", "#dfe3ea", "#2457d6", "#f3f5f9"
TH = f"padding:8px 10px;border:1px solid {LINE};background:{PAPER};font-size:13px;white-space:nowrap;text-align:center;color:{INK};"
TD = f"padding:8px 10px;border:1px solid {LINE};font-size:14px;white-space:nowrap;text-align:right;color:{INK};"
TDL = TD.replace("text-align:right", "text-align:left")
H3 = f"margin:36px 0 8px;padding-left:10px;border-left:4px solid {ACCENT};font-size:21px;color:{INK};"
NOTE = f"font-size:14px;color:{SOFT};"

e = html.escape

# 공급 유형 한 줄 설명(SH·국토부 안내에 나오는 일반적인 뜻만 적는다)
SUPPLY_NOTE = {
    "국민임대": "국민임대는 무주택 저소득층이 시세보다 낮은 임대료로 최장 30년까지 살 수 있는 공공임대입니다.",
    "영구임대": "영구임대는 생계·의료급여 수급자 등 소득이 가장 낮은 계층을 위한 공공임대로 임대료가 가장 저렴한 편입니다.",
    "행복주택": "행복주택은 청년·신혼부부·고령자 등을 위한 공공임대로 주변 시세보다 낮은 임대료로 공급됩니다.",
    "장기전세": "장기전세(시프트)는 월 임대료 없이 전세 보증금만 내고 최장 20년까지 살 수 있는 SH 공공임대입니다.",
    "재개발임대": "재개발임대는 재개발 구역 안에 지어진 임대주택으로, 철거 세입자 공급 뒤 남거나 빈 집을 일반에 다시 공급합니다.",
    "청년안심주택": "청년안심주택은 역세권 등 교통이 편한 곳에 청년·신혼부부를 위해 공급하는 서울시 임대주택입니다.",
    "공공임대": "공공임대는 일정 기간 임대로 산 뒤 분양 전환 등이 정해진 공공임대주택입니다.",
}


def won(n) -> str:
    return "-" if n in (None, 0, "") else f"{round(n):,}원"


def man(n) -> str:
    if n in (None, 0, ""):
        return "-"
    m = round(n / 10000)
    if m < 10000:
        return f"{m:,}만원"
    return (f"{m // 10000}억 {m % 10000:,}만원").replace(" 0만원", "원")


def py(a) -> str:
    return f"{a / 3.3058:.1f}평" if a else "-"


def josa(word: str, pair: str) -> str:
    """받침에 맞춰 '은/는'·'이/가' 를 붙인다. 한글로 끝나지 않으면 첫 번째(받침 있음)를 쓴다."""
    ch = re.sub(r"[\s)\]]+$", "", word)[-1:] or "가"
    has = (ord(ch) - 0xAC00) % 28 != 0 if "가" <= ch <= "힣" else True
    return word + (pair[0] if has else pair[1])


def gu_of(addr: str) -> str:
    parts = (addr or "").split()
    return parts[1] if len(parts) > 1 else ""


def dong_of(addr: str) -> str:
    m = re.search(r"\(([^)]*동)[,)]", addr or "")
    return m.group(1) if m else ""


def clean_name(name: str) -> str:
    return re.sub(r"\s+", " ", name or "").strip()


def surroundings(text: str) -> list[tuple[str, str]]:
    """SH 주변환경 글을 '1. 자연환경 / - 내용' 묶음으로 나눈다."""
    if not text:
        return []
    blocks: list[tuple[str, list[str]]] = []
    for raw in text.replace("\r", "").split("\n"):
        line = raw.strip()
        if not line:
            continue
        m = re.match(r"^\d+\s*[.)]\s*(.+)$", line)
        if m:
            blocks.append((m.group(1).strip(), []))
            continue
        line = re.sub(r"^[-·•*]\s*", "", line).strip()
        if not line:
            continue
        if not blocks:
            blocks.append(("", []))
        blocks[-1][1].append(line)
    return [(h, " ".join(b)) for h, b in blocks if b]


def plan_files(c: dict, plans: dict) -> list[tuple[str, list[tuple[str, dict]]]]:
    out = []
    for t in c.get("types", []):
        fs = [(f.get("name") or "", plans[f["url"]]) for f in t.get("floorplans", []) if f.get("url") in plans]
        if fs:
            out.append((t["type"], fs))
    return out


def all_plans_ready(c: dict, plans: dict) -> bool:
    urls = [f["url"] for t in c.get("types", []) for f in t.get("floorplans", []) if f.get("url")]
    return bool(urls) and all(u in plans for u in urls)


def meta_for(c: dict) -> dict:
    name = clean_name(c["name"])
    gu = gu_of(c.get("addr", ""))
    supply = (c.get("supply") or "").replace(",", "·")
    title = f"{name} {supply} 임대 조건 | {gu} 보증금·월임대료·평면도 정리"
    tags = [name.split(" (")[0], f"{gu}임대주택", "SH임대주택", "서울공공임대", "임대주택평면도"]
    tags += [f"{s}" for s in (c.get("supply") or "").split(",") if s]
    return {"title": title, "tags": list(dict.fromkeys(t for t in tags if t)), "slug": f"complex/{c['id']}", "id": c["id"], "gu": gu, "name": name}


def build(c: dict, plans: dict) -> str:
    meta = meta_for(c)
    name, gu = meta["name"], meta["gu"]
    types = c.get("types", [])
    supplies = [s for s in (c.get("supply") or "").split(",") if s]
    vac = sum(t.get("vacant") or 0 for t in types)
    wait = sum(t.get("waitlist") or 0 for t in types)
    deps = [t["deposit"] for t in types if t.get("deposit")]
    rents = [t["rent"] for t in types if t.get("rent")]
    areas = [t["exclusive_area"] for t in types if t.get("exclusive_area")]
    as_of = next((t.get("as_of") for t in types if t.get("as_of")), "")

    out = [f"<!-- sohyunrichlab-post {json.dumps(meta, ensure_ascii=False)} -->"]
    out.append(f'<div style="font-size:16px;line-height:1.7;color:{INK};word-break:keep-all;">')

    # 도입: 단지마다 숫자가 달라 글마다 문장이 달라진다
    loc = f"서울 {gu}{(' ' + dong_of(c.get('addr', ''))) if dong_of(c.get('addr', '')) else ''}"
    intro = f"{loc}에 있는 SH 공공임대 {name}의 임대 조건을 정리했습니다."
    bits = []
    if c.get("units"):
        bits.append(f"총 {c['units']:,}세대")
    if areas:
        bits.append(f"전용 {min(areas)}㎡" + (f"~{max(areas)}㎡" if max(areas) != min(areas) else "") + f" {len(types)}개 주택형")
    if deps:
        bits.append(f"임대보증금 {man(min(deps))}" + (f"~{man(max(deps))}" if max(deps) != min(deps) else ""))
    if rents:
        bits.append(f"월 임대료 {won(min(rents))}" + (f"~{won(max(rents))}" if max(rents) != min(rents) else ""))
    elif deps and "장기전세" in supplies:
        bits.append("월 임대료 없음(장기전세)")
    out.append(f"<p>{e(intro)} {e(', '.join(bits))}입니다." + "</p>" if bits else f"<p>{e(intro)}</p>")
    if vac or wait:
        out.append(f'<p style="{NOTE}">{e(as_of)} 기준 공가 {vac}호, 예비입주자 {wait}명입니다. 공가는 지금 비어 있는 집이라 다음 모집공고에 나올 가능성이 있습니다.</p>')

    # 기본 정보
    out.append(f'<h3 style="{H3}">{e(name)} 기본 정보</h3>')
    rows = [("주소", (c.get("addr") or "").strip()), ("공급 유형", ", ".join(supplies)),
            ("세대수", f"{c['units']:,}세대" if c.get("units") else ""), ("준공", str(c.get("built") or "")),
            ("난방", c.get("heating") or ""), ("구조", c.get("corridor") or ""),
            ("시공사", c.get("builder") or ""), ("관리 센터", c.get("center") or "")]
    out.append(f'<div style="overflow-x:auto;margin:12px 0 24px;"><table style="border-collapse:collapse;width:100%;"><tbody>')
    for k, v in rows:
        if v and v not in ("-", "None"):
            out.append(f'<tr><th style="{TH}width:110px;">{e(k)}</th><td style="{TDL}white-space:normal;">{e(v)}</td></tr>')
    out.append("</tbody></table></div>")

    # 주택형별 조건
    out.append(f'<h3 style="{H3}">주택형별 보증금·월 임대료</h3>')
    head = ["주택형", "구분", "전용면적", "방", "세대수", "임대보증금", "월 임대료", "공가", "예비"]
    out.append(f'<div style="overflow-x:auto;margin:12px 0 8px;"><table style="border-collapse:collapse;width:100%;min-width:680px;"><thead><tr>')
    out += [f'<th style="{TH}">{h}</th>' for h in head]
    out.append("</tr></thead><tbody>")
    for t in types:
        a = t.get("exclusive_area")
        r = [f"{t['type']}형", t.get("class") or "", f"{a}㎡ ({py(a)})" if a else "-", f"{t['rooms']}개" if t.get("rooms") else "-",
             f"{t.get('households'):,}" if t.get("households") else "-", man(t.get("deposit")), won(t.get("rent")),
             str(t.get("vacant") or 0), str(t.get("waitlist") or 0)]
        out.append("<tr>" + "".join(f'<td style="{TDL if i < 2 else TD}">{e(v)}</td>' for i, v in enumerate(r)) + "</tr>")
    out.append("</tbody></table></div>")
    out.append(f'<p style="{NOTE}">{e(as_of)} SH 주택정보 기준 표준 임대조건입니다. 보증금과 월 임대료는 서로 바꿀 수 있고(전환), 실제 금액은 모집공고에서 확인해야 합니다.</p>')
    cheap = min((t for t in types if t.get("deposit")), key=lambda t: t["deposit"], default=None)
    if cheap and len(types) > 1:
        out.append(f"<p>보증금이 가장 낮은 주택형은 {e(cheap['type'])}형(전용 {cheap.get('exclusive_area')}㎡)으로 {man(cheap['deposit'])}"
                   + (f", 월 {won(cheap.get('rent'))}" if cheap.get("rent") else "") + "입니다.</p>")

    # 평면도
    pf = plan_files(c, plans)
    if pf:
        out.append(f'<h3 style="{H3}">주택형별 평면도</h3>')
        for typ, fs in pf:
            t = next((x for x in types if x["type"] == typ), {})
            out.append(f'<h4 style="margin:24px 0 6px;font-size:18px;color:{INK};">{e(typ)}형 <span style="font-size:13px;font-weight:400;color:{SOFT};">'
                       f'전용 {t.get("exclusive_area", "-")}㎡ · {py(t.get("exclusive_area"))}</span></h4>')
            for label, p in fs:
                if label:
                    out.append(f'<p style="margin:10px 0 4px;font-size:13px;color:{SOFT};text-align:center;">{e(label)}</p>')
                out.append(f'<p style="margin:0 0 10px;text-align:center;"><img src="{e(SITE + p["file"])}" width="{p["w"]}" height="{p["h"]}" '
                           f'alt="{e(name)} {e(typ)}형 평면도" loading="lazy" style="max-width:100%;max-height:760px;width:auto;height:auto;border:1px solid {LINE};border-radius:8px;"></p>')

    mh = c.get("model_houses") or []
    if mh:
        out.append(f'<p style="{NOTE}">사이버 모델하우스(집 안을 360도로 둘러보기): '
                   + " · ".join(f'<a href="{e(m["url"])}" target="_blank" rel="noopener">{e(m["type"])}형</a>' for m in mh if m.get("url")) + "</p>")

    # 주변 환경
    sur = surroundings(c.get("surroundings") or "")
    if sur:
        out.append(f'<h3 style="{H3}">주변 환경</h3>')
        out.append(f'<ul style="margin:0 0 10px;padding-left:18px;font-size:15px;line-height:1.8;">')
        out += [f"<li>{('<b>' + e(h) + '</b> ') if h else ''}{e(b)}</li>" for h, b in sur]
        out.append("</ul>")
        out.append(f'<p style="{NOTE}">SH가 단지 소개에 적은 내용을 옮겼습니다.</p>')

    # 신청 방법
    out.append(f'<h3 style="{H3}">입주 신청은 어떻게 하나요</h3>')
    out.append(f"<p>{e(josa(name, '은는'))} 상시 모집이 아니라 SH 모집공고가 날 때 신청합니다. 공가가 생기면 유형별 모집공고(재공급 포함)에 함께 나옵니다.</p>")
    for s in supplies:
        if s in SUPPLY_NOTE:
            out.append(f"<p>{e(SUPPLY_NOTE[s])}</p>")
    out.append(f'<p style="{NOTE}"><a href="{NOTICE_URL}" target="_blank" rel="noopener">SH 모집공고 보기</a> · 문의: {e(c.get("center") or "SH 콜센터 1600-3456")}</p>')

    out.append(f'<hr style="border:0;border-top:1px solid {LINE};margin:32px 0 16px;">')
    out.append(f'<p style="font-size:13px;color:{SOFT};">자료·평면도 출처: <a href="{SH_URL}" target="_blank" rel="noopener">SH 서울주택도시개발공사 주택정보</a>'
               f' ({e(c.get("fetched") or "")} 확인) · 공익 목적의 정보 공유이며 저작권은 원 출처에 있습니다.</p>')
    out.append(f'<p style="font-size:14px;"><a href="{SITE}" target="_blank" rel="noopener">이번 주 청약·임대 공고 한눈에 보기 (소현리치랩)</a></p>')
    out.append("</div>")
    return "\n".join(out) + "\n"


def rent_kr(n) -> str:
    """월 임대료를 '52만 5천원' 처럼 말하듯 적는다(네이버 요약 글용)."""
    if not n:
        return "-"
    m, r = divmod(round(n), 10000)
    c = round(r / 1000)
    if c == 10:
        m, c = m + 1, 0
    return (f"{m:,}만" if m else "") + (f" {c}천" if c else "") + "원"


def first_sentence(text: str, limit: int = 90) -> str:
    t = re.split(r"(?<=[다요])\.\s|(?<=[다요])\.$", text.strip())[0].strip()
    if not t.endswith("."):
        t += "."
    return t if len(t) <= limit else t[:limit].rsplit(" ", 1)[0] + "…"


def naver_meta(c: dict) -> dict:
    name = clean_name(c["name"])
    gu = gu_of(c.get("addr", ""))
    supply = (c.get("supply") or "").split(",")[0]
    short = name.split(" (")[0]
    return {"title": f"{short} {supply} 보증금 얼마? {gu} SH 임대 요약", "tags": [short, f"{gu}임대", "SH임대", supply, "공공임대"],
            "slug": f"naver/{c['id']}", "id": c["id"], "gu": gu, "name": name}


def build_naver(c: dict, plans: dict) -> str:
    """네이버 블로그용 요약 글. 티스토리 글과 문장·구성이 겹치지 않게 짧은 질문형으로 쓴다.
    네이버 편집기에 붙여 넣으므로 꾸밈은 최소로 하고(굵게·목록·이미지), 표는 쓰지 않는다."""
    meta = naver_meta(c)
    name, gu = meta["name"], meta["gu"]
    types = c.get("types", [])
    supplies = [s for s in (c.get("supply") or "").split(",") if s]
    vac = sum(t.get("vacant") or 0 for t in types)
    as_of = next((t.get("as_of") for t in types if t.get("as_of")), "")
    cheap = min((t for t in types if t.get("deposit")), key=lambda t: t["deposit"], default=None)
    dong = dong_of(c.get("addr", ""))
    out = [f"<!-- sohyunrichlab-post {json.dumps(meta, ensure_ascii=False)} -->"]
    out.append(f"<p>{e(gu)}{(' ' + e(dong)) if dong else ''} SH {e('·'.join(supplies))} <b>{e(name)}</b>, 보증금과 월세가 얼마인지 핵심만 짧게 정리해 봤어요.</p>")
    out.append("<p><b>한눈에 보기</b></p><ul>")
    if c.get("units"):
        out.append(f"<li>규모: {c['units']:,}세대{(' · ' + e(str(c['built'])) + ' 준공') if c.get('built') and c['built'] not in ('-', 'None') else ''}</li>")
    if cheap:
        out.append(f"<li>가장 저렴한 집: {e(cheap['type'])}형(약 {py(cheap.get('exclusive_area'))}) 보증금 {man(cheap['deposit'])}"
                   + (f", 월 {rent_kr(cheap.get('rent'))}" if cheap.get("rent") else ", 월세 없음") + "</li>")
    out.append(f"<li>빈집(공가): {vac}호" + (f" ({e(as_of)} 기준)" if as_of else "") + "</li></ul>")

    out.append("<p><b>Q. 어떤 평형이 있나요?</b></p><ul>")
    for t in types:
        a = t.get("exclusive_area")
        bits = [f"전용 {a}㎡(약 {py(a)})" if a else "", f"방 {t['rooms']}개" if t.get("rooms") else ""]
        money = f"보증금 {man(t.get('deposit'))}" + (f" / 월 {rent_kr(t.get('rent'))}" if t.get("rent") else "")
        out.append(f"<li>{e(t['type'])}형: {e(', '.join(b for b in bits if b))} → {e(money)}</li>")
    out.append("</ul>")

    pf = plan_files(c, plans)
    if pf:
        typ, fs = pf[0]
        label, p = fs[0]
        out.append(f"<p><b>Q. 집 구조는요?</b> {e(typ)}형 평면도예요.</p>")
        out.append(f'<p><img src="{e(SITE + p["file"])}" alt="{e(name)} {e(typ)}형 평면도"></p>')

    sur = surroundings(c.get("surroundings") or "")
    if sur:
        out.append("<p><b>Q. 주변은 어떤가요?</b></p><ul>")
        out += [f"<li>{(e(h) + ': ') if h else ''}{e(first_sentence(b))}</li>" for h, b in sur[:3]]
        out.append("</ul>")

    out.append("<p><b>Q. 어떻게 들어가나요?</b></p>")
    out.append(f"<p>수시 접수가 아니라 SH 모집공고가 뜰 때 신청해요. 빈집이 생기면 재공급 공고에 나오니 공고 알림을 켜 두는 게 좋아요. 문의는 {e(c.get('center') or 'SH 콜센터 1600-3456')}.</p>")
    out.append(f'<p>출처: SH 서울주택도시개발공사 주택정보({e(c.get("fetched") or "")} 확인). 실제 조건은 모집공고 기준이에요.</p>')
    out.append(f'<p>소현리치랩 임대·청약 공고 모아보기: <a href="{SITE}">{SITE}</a></p>')
    return "\n".join(out) + "\n"


def order(items: list[dict]) -> list[dict]:
    """공가 있는 단지 → 세대수 큰 단지. 같은 자치구가 연달아 나오지 않게 섞는다."""
    items = sorted(items, key=lambda x: (-(x["vac"] > 0), -x["units"], x["id"]))
    out, rest = [], items[:]
    while rest:
        last = out[-1]["gu"] if out else None
        i = next((k for k, x in enumerate(rest) if x["gu"] != last), 0)
        out.append(rest.pop(i))
    return out


def main() -> int:
    data = json.loads(HOUSES.read_text(encoding="utf-8"))
    plans = json.loads(MANIFEST.read_text(encoding="utf-8")).get("plans", {}) if MANIFEST.exists() else {}
    published = json.loads(PUBLISHED.read_text(encoding="utf-8")) if PUBLISHED.exists() else {"posts": []}
    done = {p["id"] for p in published.get("posts", []) if p.get("tistory")}
    done_naver = {p["id"] for p in published.get("posts", []) if p.get("naver")}
    OUT.mkdir(parents=True, exist_ok=True)
    NAVER_OUT.mkdir(parents=True, exist_ok=True)
    items, keep, changed = [], set(), 0
    for c in data.get("complexes", {}).values():
        if not c.get("types") or not any(t.get("deposit") for t in c["types"]) or not all_plans_ready(c, plans):
            continue
        if gu_of(c.get("addr", "")).endswith("시"):  # 서울 밖(의정부 등)은 제외
            continue
        for folder, text in ((OUT, build(c, plans)), (NAVER_OUT, build_naver(c, plans))):
            f = folder / f"{c['id']}.html"
            if not f.exists() or f.read_text(encoding="utf-8") != text:
                f.write_text(text, encoding="utf-8")
                changed += 1
        keep.add(f"{c['id']}.html")
        m = meta_for(c)
        items.append({"id": c["id"], "name": m["name"], "gu": m["gu"], "title": m["title"], "file": f"posts/complex/{c['id']}.html",
                      "naver_title": naver_meta(c)["title"], "naver_file": f"posts/naver/{c['id']}.html",
                      "units": c.get("units") or 0, "vac": sum(t.get("vacant") or 0 for t in c["types"])})
    for f in [*OUT.glob("*.html"), *NAVER_OUT.glob("*.html")]:
        if f.name not in keep:
            f.unlink()
    items = order(items)
    queue = [x["id"] for x in items if x["id"] not in done]
    INDEX.write_text(json.dumps({"updated": data.get("updated"), "count": len(items), "queue": queue,
                                "naver_queue": [x["id"] for x in items if x["id"] not in done_naver], "posts": items},
                                ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    if not PUBLISHED.exists():
        PUBLISHED.write_text(json.dumps({"_설명": "발행한 단지 글 기록. id 와 tistory·naver 주소, 발행 날짜", "posts": []}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"단지 글 {len(items)}개, 바뀐 글 {changed}개, 발행 대기 {len(queue)}개")
    return 0


if __name__ == "__main__":
    sys.exit(main())
