"""임대주택 보드 만들기 (소현리치랩).

data/sh_houses.json(SH 주택정보 수집 결과)에서 단지를 골라 보드 파일 data/boards/<이름>.json 을 만든다.

| 보드 | 만드는 기준 | 이름 |
|---|---|---|
| 공고 보드 | 진행 중인 모집공고마다, 그 공고에 묶인 단지의 주택형 전부 | sh-notice-<공고 번호> |
| 조건 보드 | data/board_specs.json 에 적은 조건(자치구·공급 유형·공가 여부)마다 | 조건에 적은 slug |

- 사람이 직접 만든 보드(파일에 "generated" 가 없는 것, 예: sh-3gu)는 건드리지 않는다.
- 공고가 끝나도 공고 보드는 지우지 않고 "closed": true 만 붙인다(블로그 글 주소가 살아 있도록).
- 공고에 단지 번호가 없거나 단지가 아직 수집되지 않았으면 보드를 만들지 않고 이유를 출력한다.
- 마지막에 보드 목록 data/boards/index.json 을 다시 쓴다.

실행: python scripts/build_boards.py
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "sh_houses.json"
SPECS = ROOT / "data" / "board_specs.json"
BOARDS = ROOT / "data" / "boards"
KST = timezone(timedelta(hours=9))
SOURCE = {"name": "SH 서울주택도시개발공사 서울주택정보", "url": "https://www.i-sh.co.kr/houseinfo/main/mainPage.do"}
NOTE = ("SH 서울주택정보에 공개된 자료를 그대로 모은 것입니다. 보증금·월임대료·공가·예비자 수는 주택형별 기준월 자료이고, "
        "평은 전용면적 ÷ 3.3058로 환산했습니다. 금액 단위는 원이며, 신청 전에는 반드시 SH 공고 원문을 확인하세요.")
IMAGE_EXT = re.compile(r"\.(jpe?g|png|gif|webp|bmp|tiff?)$", re.I)


def gu_of(addr: str) -> str:
    m = re.search(r"(\S+구)(?:\s|$)", addr or "")
    return m.group(1) if m else ""


def items_of(cx: dict) -> list[dict]:
    """단지 한 곳을 주택형별 카드 자료로 바꾼다."""
    out = []
    for t in cx.get("types") or []:
        plans = [p["url"] for p in t.get("floorplans") or [] if p.get("url") and IMAGE_EXT.search(p["url"].split("?")[0])]
        model = next((m.get("url") for m in cx.get("model_houses") or [] if m.get("type") == t.get("type") and m.get("url")), None)
        item = {
            "id": f"{cx['id']}-{t.get('type')}-{t.get('class')}", "complex_id": cx["id"],
            "gu": gu_of(cx.get("addr", "")), "name": cx.get("name"), "addr": (cx.get("addr") or "").strip(),
            "supply": t.get("class") or cx.get("supply"), "type": t.get("type"),
            "area": t.get("exclusive_area"), "rooms": t.get("rooms"), "households": t.get("households"),
            "dep": t.get("deposit"), "rent": t.get("rent"), "vac": t.get("vacant", 0), "wait": t.get("waitlist", 0),
            "as_of": t.get("as_of"), "plan_urls": plans, "model_url": model,
        }
        out.append({k: v for k, v in item.items() if v not in (None, "", [])})
    return out


def tabs_of(items: list[dict]) -> list[dict]:
    """공급 유형이 여럿이면 유형별 탭으로, 하나면 탭 하나로."""
    groups: dict[str, list[dict]] = {}
    for it in items:
        groups.setdefault(it.get("supply") or "임대", []).append(it)
    if len(groups) > 4:
        return [{"id": "all", "label": "전체", "kind": "type", "items": items}]
    return [{"id": f"t{i}", "label": label, "kind": "type", "items": rows} for i, (label, rows) in enumerate(groups.items())]


def write(slug: str, board: dict, today: str) -> bool:
    """내용이 바뀌었을 때만 쓴다(updated 날짜 때문에 매일 바뀌지 않도록)."""
    path = BOARDS / f"{slug}.json"
    old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if {k: v for k, v in old.items() if k != "updated"} == board:
        return False
    path.write_text(json.dumps({**board, "updated": today}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return True


def main() -> int:
    if not SRC.exists():
        print("data/sh_houses.json 이 없어 만들 수 없음", file=sys.stderr)
        return 1
    data = json.loads(SRC.read_text(encoding="utf-8"))
    complexes: dict[str, dict] = data.get("complexes", {})
    today = datetime.now(KST).strftime("%Y-%m-%d")
    BOARDS.mkdir(parents=True, exist_ok=True)
    changed = 0

    # 1) 진행 중인 공고마다
    live = set()
    for n in data.get("notices", []):
        slug = f"sh-notice-{n.get('seq')}"
        ids = n.get("complex_ids") or []
        found = [complexes[b] for b in ids if b in complexes]
        items = [it for cx in found for it in items_of(cx)]
        if not items:
            why = "공고에 단지 번호가 없음" if not ids else "단지가 아직 수집되지 않음"
            print(f"건너뜀: {n.get('title')} ({why})")
            continue
        live.add(slug)
        names = ", ".join(dict.fromkeys(cx.get("name", "") for cx in found))
        board = {"slug": slug, "generated": "notice", "title": n.get("title"),
                 "sub": f"공고일 {n.get('date')} · 대상 단지 {len(found)}곳({names}) · 주택형 {len(items)}개. 평면도를 누르면 크게 볼 수 있습니다.",
                 "note": NOTE, "source": SOURCE, "notice": {"title": n.get("title"), "date": n.get("date"), "url": n.get("url")},
                 "tabs": tabs_of(items)}
        changed += write(slug, board, today)

    # 2) 조건 보드
    specs = json.loads(SPECS.read_text(encoding="utf-8")) if SPECS.exists() else []
    for s in specs:
        slug = s["slug"]
        items = []
        for cx in complexes.values():
            if s.get("gu") and gu_of(cx.get("addr", "")) not in s["gu"]:
                continue
            for it in items_of(cx):
                if s.get("supply") and it.get("supply") not in s["supply"]:
                    continue
                if s.get("vacant_only") and not it.get("vac"):
                    continue
                if s.get("plan_only") and not it.get("plan_urls"):
                    continue
                items.append(it)
        if not items:
            print(f"건너뜀: 조건 보드 {slug} (맞는 주택형 없음)")
            continue
        board = {"slug": slug, "generated": "spec", "title": s["title"],
                 "sub": (s.get("sub") or "") + f" 주택형 {len(items)}개. 평면도를 누르면 크게 볼 수 있습니다.",
                 "note": NOTE, "source": SOURCE, "tabs": tabs_of(items)}
        changed += write(slug, board, today)

    # 3) 끝난 공고 표시와 보드 목록
    index = []
    for f in sorted(BOARDS.glob("*.json")):
        if f.name == "index.json":
            continue
        b = json.loads(f.read_text(encoding="utf-8"))
        if b.get("generated") == "notice":
            closed = b["slug"] not in live
            if bool(b.get("closed")) != closed:
                b["closed"] = closed
                if not closed:
                    b.pop("closed")
                f.write_text(json.dumps(b, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
                changed += 1
        index.append({k: v for k, v in {
            "slug": b.get("slug") or f.stem, "title": b.get("title"), "kind": b.get("generated") or "manual",
            "count": sum(len(t.get("items", [])) for t in b.get("tabs", [])), "updated": b.get("updated"),
            "closed": b.get("closed"), "notice_date": (b.get("notice") or {}).get("date")}.items() if v not in (None, False)})
    index.sort(key=lambda r: (r.get("closed", False), r["kind"] != "notice", r.get("notice_date") or "", r["slug"]))
    idx = BOARDS / "index.json"
    new = json.dumps({"boards": index}, ensure_ascii=False, indent=1) + "\n"
    if not idx.exists() or idx.read_text(encoding="utf-8") != new:
        idx.write_text(new, encoding="utf-8")
    print(f"보드 {len(index)}개, 바뀐 보드 {changed}개")
    return 0


if __name__ == "__main__":
    sys.exit(main())
