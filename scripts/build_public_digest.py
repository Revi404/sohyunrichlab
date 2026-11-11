"""공공주택 공고 요약 파일 생성기 (소현리치랩).

data/public_housing.json 을 읽어 '오늘 뜬 공고·마감 임박·곧 시작' 만 골라 data/public_housing_digest.json 으로 저장한다.
스레드 작성처럼 큰 파일 전체가 필요 없는 곳에서 이 요약만 읽도록 만든 파일이다 (목표 40KB 이하).

- new     공고일이 오늘 포함 최근 3일인 모집공고, 점수 높은 순 (최대 15건)
- closing 접수 마감이 오늘~3일 뒤인 모집공고, 마감 빠른 순 (최대 10건)
- opening 접수 시작이 내일~7일 뒤인 모집공고, 시작 빠른 순 (최대 10건)
- LH·마이홈·GH 는 status 가 공고중·접수중·정정공고중인 것만 본다.
  SH 는 status·접수일이 없으므로 공고일이 최근 3일인 것만 new 에 넣는다.
- 가정어린이집·상가 등 주택이 아닌 공고는 뺀다.
- 값은 data 파일에 있는 것만 쓰고, 없는 값은 항목에 넣지 않는다.

실행: python scripts/build_public_digest.py [--today YYYY-MM-DD]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "public_housing.json"
OUT = ROOT / "data" / "public_housing_digest.json"
TEXT_DIR = ROOT / "data" / "notice_text"
KST = timezone(timedelta(hours=9))

# ── 점수 표 (나중에 고치기 쉽도록 한곳에 둔다) ───────────────────────────────
SCORE_CAPITAL = 3        # 서울·경기·인천
SCORE_UNITS_300 = 3      # 공급 300호 이상
SCORE_UNITS_100 = 2      # 공급 100~299호
SCORE_SALE = 3           # 분양(공공분양·신혼희망타운)
SCORE_SH_GH = 2          # SH 또는 GH
SCORE_FAVORITE = 1       # 관심 유형
SCORE_CORRECTION = -2    # 제목에 '정정공고'
SCORE_EXTRA = -1         # 제목에 '추가'·'예비입주자'·'잔여'
SCORE_FCFS = 1           # 제목에 '선착순'

CAPITAL = ("서울", "경기", "인천")
FAVORITE_TYPES = ("행복주택", "장기전세", "통합공공임대")
EXTRA_WORDS = ("추가", "예비입주자", "잔여")
NOT_HOUSING = ("어린이집", "상가")
ACTIVE = ("공고중", "접수중", "정정공고중")

NEW_DAYS, CLOSING_DAYS, OPENING_DAYS = 3, 3, 7   # 기간(일)
NEW_MAX, CLOSING_MAX, OPENING_MAX = 15, 10, 10   # 최대 건수
HOUSES_MAX, AREAS_MAX = 3, 5
SIZE_GOAL = 40 * 1024


def day(s: str, delta: int = 0) -> str:
    return (datetime.strptime(s, "%Y-%m-%d") + timedelta(days=delta)).strftime("%Y-%m-%d")


def units_of(n: dict) -> int | None:
    """공급 호수. 공고에 없으면 단지별 호수의 합."""
    if n.get("units"):
        return n["units"]
    total = sum(h.get("units") or 0 for h in n.get("houses") or [])
    return total or None


def is_housing(n: dict) -> bool:
    return not any(w in (n.get("type") or "") or w in (n.get("title") or "") for w in NOT_HOUSING)


def score(n: dict) -> tuple[int, list[str]]:
    title, pts, why = n.get("title") or "", 0, []

    def add(p: int, reason: str) -> None:
        nonlocal pts
        pts += p
        why.append(reason)

    if (n.get("region") or "").startswith(CAPITAL):
        add(SCORE_CAPITAL, "수도권")
    u = units_of(n) or 0
    if u >= 300:
        add(SCORE_UNITS_300, "300호 이상")
    elif u >= 100:
        add(SCORE_UNITS_100, "100호 이상")
    if n.get("deal") == "분양":
        add(SCORE_SALE, "분양")
    if n.get("src") in ("sh", "gh"):
        add(SCORE_SH_GH, "SH/GH")
    if any(t in (n.get("type") or "") for t in FAVORITE_TYPES):
        add(SCORE_FAVORITE, "관심 유형")
    if "정정공고" in title:
        add(SCORE_CORRECTION, "정정공고")
    if any(w in title for w in EXTRA_WORDS):
        add(SCORE_EXTRA, "추가·예비 모집")
    if "선착순" in title:
        add(SCORE_FCFS, "선착순")
    return pts, why


def house_item(h: dict) -> dict:
    out = {"name": h.get("name"), "units": h.get("units"), "deposit": h.get("deposit"), "rent": h.get("rent")}
    if not out["deposit"] and not out["rent"]:  # 분양은 계약금·잔금
        out.update(down=h.get("down"), balance=h.get("balance"))
    return {k: v for k, v in out.items() if v}


def item(n: dict, with_houses: bool = True) -> dict:
    d = n.get("detail") or {}
    sc, why = score(n)
    houses = [house_item(h) for h in n.get("houses") or []]
    houses = [h for h in houses if h]
    areas = [{"area": t.get("area"), "units": t.get("units")} for t in d.get("types") or [] if t.get("area")]
    move_in = next((s["move_in"] for s in d.get("sites") or [] if s.get("move_in")), None)
    out = {k: n.get(k) for k in ("id", "org", "deal", "type", "title", "region", "city",
                                 "notice_date", "apply_start", "apply_end", "winner_date")}
    out["units"] = units_of(n)
    if with_houses and houses:
        out["houses"] = houses[:HOUSES_MAX]
    if n.get("houses"):
        out["house_count"] = len(n["houses"])
    if areas:
        out["areas"] = [{k: v for k, v in a.items() if v} for a in areas[:AREAS_MAX]]
    out["move_in"] = move_in
    out["url"] = n.get("url")
    out = {k: v for k, v in out.items() if v not in (None, "", [])}
    out["has_text"] = (TEXT_DIR / f"{n['id']}.json").exists()
    out["score"] = sc
    if why:
        out["reasons"] = why
    return out


def build(src: dict, today: str) -> dict:
    new_from = day(today, -(NEW_DAYS - 1))
    closing_to = day(today, CLOSING_DAYS)
    opening_from, opening_to = day(today, 1), day(today, OPENING_DAYS)

    notices = [n for n in src.get("notices", []) if n.get("kind") == "모집공고" and is_housing(n)]
    new, closing, opening, active = [], [], [], 0
    for n in notices:
        recent = bool(n.get("notice_date")) and new_from <= n["notice_date"] <= today
        if n.get("src") == "sh":  # 상태·접수일이 없어 공고일로만 본다
            if recent:
                active += 1
                new.append(n)
            continue
        if n.get("status") not in ACTIVE:
            continue
        active += 1
        if recent:
            new.append(n)
        if n.get("apply_end") and today <= n["apply_end"] <= closing_to:
            closing.append(n)
        if n.get("apply_start") and opening_from <= n["apply_start"] <= opening_to:
            opening.append(n)

    # 새 공고: 점수 높은 순, 같으면 공고일 최근 순
    new.sort(key=lambda n: (-score(n)[0], -int((n.get("notice_date") or "0").replace("-", "")), n["id"]))
    closing.sort(key=lambda n: (n["apply_end"], -score(n)[0], n["id"]))
    opening.sort(key=lambda n: (n["apply_start"], -score(n)[0], n["id"]))
    return {
        "today": today,
        "source_updated": src.get("updated"),
        "counts": {"active": active, "new_3d": len(new), "closing_3d": len(closing), "opening_7d": len(opening)},
        "new": [item(n) for n in new[:NEW_MAX]],
        "closing": [item(n) for n in closing[:CLOSING_MAX]],
        "opening": [item(n) for n in opening[:OPENING_MAX]],
    }


def dump(d: dict) -> str:
    return json.dumps(d, ensure_ascii=False, separators=(",", ":")) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--today", help="기준 날짜 YYYY-MM-DD (시험용, 기본은 오늘 KST)")
    args = ap.parse_args()
    now = datetime.now(KST)
    if args.today:
        try:
            datetime.strptime(args.today, "%Y-%m-%d")
        except ValueError:
            print("--today 는 YYYY-MM-DD 형식이어야 합니다", file=sys.stderr)
            return 2
    today = args.today or now.strftime("%Y-%m-%d")

    if not SRC.exists():
        print(f"원본 없음: {SRC.relative_to(ROOT)}", file=sys.stderr)
        return 1
    digest = build(json.loads(SRC.read_text(encoding="utf-8")), today)

    # updated 만 다르면 바뀐 내용 없음으로 보고 쓰지 않는다 (today 가 바뀌면 다시 쓴다)
    if OUT.exists():
        try:
            old = json.loads(OUT.read_text(encoding="utf-8"))
            if {k: v for k, v in old.items() if k != "updated"} == digest:
                print("바뀐 내용 없음")
                return 0
        except ValueError:
            pass
    result = {"updated": now.strftime("%Y-%m-%d %H:%M"), **digest}
    text = dump(result)
    OUT.write_text(text, encoding="utf-8")
    size = len(text.encode("utf-8"))
    c = digest["counts"]
    print(f"저장: {OUT.relative_to(ROOT)} ({size:,}바이트) · 진행 {c['active']} · 새 공고 {c['new_3d']} · "
          f"마감 임박 {c['closing_3d']} · 곧 시작 {c['opening_7d']}")
    if size > SIZE_GOAL:
        print(f"경고: 목표 {SIZE_GOAL:,}바이트를 넘었습니다", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
