"""티스토리 글 만들기 (소현리치랩 임대주택 보드).

보드 파일 data/boards/<이름>.json 마다 티스토리 글쓰기의 HTML 모드에 그대로 붙여 넣을 글 posts/<이름>.html 을 만든다.

- 글 하나로 다 볼 수 있게 요약 표와 주택별 조건, 평면도 이미지를 모두 넣는다. 보드 링크는 맨 아래 한 번만 단다.
- 티스토리 편집기가 지우지 않도록 스크립트·style 태그 없이 태그마다 style 속성으로만 꾸민다.
- 평면도는 이 저장소가 받아 둔 사본(assets/plans, data/plans.json)의 공개 주소를 쓴다. 아직 받지 못한 평면도는 글에 넣지 않는다.
- 첫 줄 주석에 권장 제목과 태그를 적는다. 복사 화면(board/post.html)이 이를 읽어 보여 준다.

실행: python scripts/build_posts.py
"""
from __future__ import annotations

import html
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BOARDS = ROOT / "data" / "boards"
MANIFEST = ROOT / "data" / "plans.json"
POSTS = ROOT / "posts"
SITE = "https://revi404.github.io/sohyunrichlab/"
MAX_ITEMS = 60  # 글 하나에 싣는 주택 수 상한(넘으면 나머지는 보드로 안내)

INK, SOFT, LINE, ACCENT, PAPER = "#121a2b", "#4f5970", "#dfe3ea", "#2457d6", "#f3f5f9"
TH = f"padding:8px 10px;border:1px solid {LINE};background:{PAPER};font-size:13px;white-space:nowrap;text-align:center;color:{INK};"
TD = f"padding:8px 10px;border:1px solid {LINE};font-size:14px;white-space:nowrap;text-align:right;color:{INK};"
TDL = TD.replace("text-align:right", "text-align:left")

e = html.escape


def won(n) -> str:
    return "-" if n in (None, 0, "") else f"{round(n):,}"


def man(n) -> str:
    if n in (None, 0, ""):
        return "-"
    m = round(n / 10000)
    if m < 10000:
        return f"{m:,}만"
    return f"{m // 10000}억 {m % 10000:,}만".replace(" 0만", "")


def py(a) -> str:
    return f"{a / 3.3058:.1f}" if a else "-"


def label(d: dict) -> str:
    return f"{d['name']} {d['type']}형" if d.get("type") else str(d.get("name"))


def table(kind: str, items: list[dict]) -> str:
    if kind == "unit":
        head = ["주택", "자치구", "전용면적", "호수", "승강기", "임대보증금", "월 임대료", "실질임대료"]
        rows = [[label(d), d.get("gu"), f"{d.get('area')}㎡ ({py(d.get('area'))}평)", f"{d.get('ho')}호", d.get("elev"),
                 won(d.get("dep")), won(d.get("rent")), won(d.get("real"))] for d in items]
    elif kind == "complex":
        head = ["단지", "자치구", "주거전용", "모집", "공가", "예비", "임대보증금", "월 임대료"]
        rows = [[label(d), d.get("gu"), f"{d.get('area')}㎡ ({py(d.get('area'))}평)", f"{d.get('total')}세대", d.get("vac"), d.get("wait"),
                 won(d.get("dep")), won(d.get("rent"))] for d in items]
    else:
        head = ["단지·주택형", "자치구", "전용면적", "방", "공가", "예비", "임대보증금", "월 임대료"]
        rows = [[label(d), d.get("gu"), f"{d.get('area')}㎡ ({py(d.get('area'))}평)", d.get("rooms", "-"), d.get("vac", 0), d.get("wait", 0),
                 won(d.get("dep")), won(d.get("rent"))] for d in items]
    out = [f'<div style="overflow-x:auto;margin:12px 0 24px;"><table style="border-collapse:collapse;width:100%;min-width:640px;"><thead><tr>']
    out += [f'<th style="{TH}">{e(h)}</th>' for h in head]
    out.append("</tr></thead><tbody>")
    for r in rows:
        out.append("<tr>" + "".join(f'<td style="{TDL if i < 2 else TD}">{e(str(v if v is not None else "-"))}</td>' for i, v in enumerate(r)) + "</tr>")
    out.append("</tbody></table></div>")
    return "".join(out)


def facts(kind: str, d: dict) -> list[tuple[str, str]]:
    area = f"{d.get('area')}㎡ ({py(d.get('area'))}평)"
    if kind == "unit":
        return [("전용면적", area), ("구조", str(d.get("room"))), ("호수", f"{d.get('ho')}호"), ("승강기", str(d.get("elev"))),
                ("임대보증금", won(d.get("dep")) + "원"), ("월 임대료", won(d.get("rent")) + "원"),
                ("전세 전환 시", f"보증금 {won(d.get('jdep'))}원 · 월 {won(d.get('jrent'))}원"), ("주소", str(d.get("addr")))]
    if kind == "complex":
        return [("주거전용", area), ("구조", str(d.get("room"))), ("모집", f"{d.get('total')}세대 (공가 {d.get('vac')} · 예비 {d.get('wait')})"),
                ("임대보증금", won(d.get("dep")) + "원"), ("월 임대료", won(d.get("rent")) + "원"),
                ("보증금 올릴 때", f"보증금 {won(d.get('dep2'))}원 · 월 {won(d.get('rent2'))}원")]
    return [("공급 유형", str(d.get("supply"))), ("전용면적", area), ("방", str(d.get("rooms", "-"))), ("세대수", f"{d.get('households', '-')}세대"),
            ("공가 · 예비", f"{d.get('vac', 0)} · {d.get('wait', 0)} ({d.get('as_of', '-')} 기준)"),
            ("임대보증금", won(d.get("dep")) + ("원" if d.get("dep") else "")), ("월 임대료", won(d.get("rent")) + ("원" if d.get("rent") else "")),
            ("주소", str(d.get("addr")))]


def section(kind: str, d: dict, plans: dict) -> str:
    urls = [u for u in [d.get("plan_url"), *(d.get("plan_urls") or [])] if u]
    imgs = [plans[u] for u in urls if u in plans]
    out = [f'<h4 style="margin:28px 0 8px;font-size:18px;color:{INK};">{e(label(d))} <span style="font-size:13px;font-weight:400;color:{SOFT};">{e(str(d.get("gu") or ""))}</span></h4>']
    out.append(f'<ul style="margin:0 0 10px;padding-left:18px;color:{INK};font-size:15px;line-height:1.7;">')
    out += [f'<li><b>{e(k)}</b> {e(v)}</li>' for k, v in facts(kind, d) if v and v not in ("None", "-")]
    out.append("</ul>")
    for p in imgs:
        out.append(f'<p style="margin:0 0 10px;text-align:center;"><img src="{e(SITE + p["file"])}" width="{p["w"]}" height="{p["h"]}" alt="{e(label(d))} 평면도" loading="lazy" '
                   f'style="max-width:100%;max-height:760px;width:auto;height:auto;border:1px solid {LINE};border-radius:8px;"></p>')
    if not imgs:
        link = next((u for u in urls if u.startswith("http")), None)
        out.append(f'<p style="margin:0 0 10px;font-size:13px;color:{SOFT};">평면도 이미지가 공개되어 있지 않습니다.'
                   + (f' <a href="{e(link)}" target="_blank" rel="noopener">관련 자료 보기</a>' if link else "") + "</p>")
    return "".join(out)


def build(board: dict, plans: dict) -> str:
    slug = board["slug"]
    total = sum(len(t.get("items", [])) for t in board.get("tabs", []))
    tags = ["SH임대주택", "임대주택평면도", "서울임대주택"] + [t["label"] for t in board.get("tabs", []) if t.get("label") not in ("전체", "임대")]
    gus = list(dict.fromkeys(d.get("gu") for t in board.get("tabs", []) for d in t.get("items", []) if d.get("gu")))
    tags += gus[:5]
    meta = {"title": f"{board['title']} 평면도·보증금·월임대료 한눈에 비교", "tags": list(dict.fromkeys(tags)), "slug": slug, "count": total}
    out = [f"<!-- sohyunrichlab-post {json.dumps(meta, ensure_ascii=False)} -->"]
    out.append(f'<div style="font-size:16px;line-height:1.7;color:{INK};word-break:keep-all;">')
    intro = f"{board['title']}에 나온 주택 {total}건의 면적, 임대보증금, 월 임대료와 평면도를 한 번에 볼 수 있게 정리했습니다."
    out.append(f"<p>{e(intro)}</p>")
    if board.get("notice", {}).get("url"):
        n = board["notice"]
        out.append(f'<p style="font-size:14px;color:{SOFT};">공고일 {e(str(n.get("date")))} · <a href="{e(n["url"])}" target="_blank" rel="noopener">SH 공고 원문</a></p>')
    left = MAX_ITEMS
    for t in board.get("tabs", []):
        items = t.get("items", [])
        if not items:
            continue
        kind = t.get("kind", "type")
        out.append(f'<h3 style="margin:36px 0 4px;padding-left:10px;border-left:4px solid {ACCENT};font-size:21px;color:{INK};">{e(t.get("label") or "목록")} {len(items)}건</h3>')
        cheap = min((d for d in items if d.get("dep")), key=lambda d: d["dep"], default=None)
        if cheap:
            out.append(f'<p style="font-size:14px;color:{SOFT};">보증금이 가장 낮은 곳은 {e(label(cheap))}로 {man(cheap["dep"])}원입니다.</p>')
        out.append(table(kind, items))
        show = items[:max(left, 0)]
        left -= len(show)
        out += [section(kind, d, plans) for d in show]
        if len(show) < len(items):
            out.append(f'<p style="font-size:14px;color:{SOFT};">나머지 {len(items) - len(show)}건의 평면도는 아래 전체 보드에서 볼 수 있습니다.</p>')
    out.append(f'<hr style="border:0;border-top:1px solid {LINE};margin:32px 0 16px;">')
    if board.get("note"):
        out.append(f'<p style="font-size:13px;color:{SOFT};">{e(board["note"])}</p>')
    src = board.get("source") or {}
    out.append(f'<p style="font-size:13px;color:{SOFT};">자료·평면도 출처: <a href="{e(src.get("url", ""))}" target="_blank" rel="noopener">{e(src.get("name", "SH"))}</a>'
               f' · 공익 목적의 정보 공유이며 저작권은 원 출처에 있습니다.</p>')
    out.append(f'<p style="font-size:14px;"><a href="{e(SITE)}board/?b={e(slug)}" target="_blank" rel="noopener">자치구·보증금 순으로 골라 보기 (전체 보드)</a></p>')
    out.append("</div>")
    return "\n".join(out) + "\n"


def main() -> int:
    plans = (json.loads(MANIFEST.read_text(encoding="utf-8")).get("plans", {}) if MANIFEST.exists() else {})
    POSTS.mkdir(exist_ok=True)
    made = changed = 0
    keep = set()
    for f in sorted(BOARDS.glob("*.json")):
        if f.name == "index.json":
            continue
        board = json.loads(f.read_text(encoding="utf-8"))
        board.setdefault("slug", f.stem)
        text = build(board, plans)
        out = POSTS / f"{board['slug']}.html"
        keep.add(out.name)
        made += 1
        if not out.exists() or out.read_text(encoding="utf-8") != text:
            out.write_text(text, encoding="utf-8")
            changed += 1
    for f in POSTS.glob("*.html"):
        if f.name not in keep:
            f.unlink()
    print(f"글 {made}개, 바뀐 글 {changed}개")
    return 0


if __name__ == "__main__":
    sys.exit(main())
