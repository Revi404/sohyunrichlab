"""SH 매입임대(빌라) 수집기 (소현리치랩).

SH 서울주택정보(https://www.i-sh.co.kr/houseinfo/main/mainPage.do)의 매입다가구·매입원룸 건물을 읽어
data/sh_purchased.json 에 저장한다. 아파트형 단지는 collect_sh_houses.py 가 맡는다.

| 묶음 | 내용 |
|---|---|
| buildings{건물 번호} | 주소, 구분(매입다가구/매입원룸), 승강기, 층수, 준공일, 공가·예비자 수, 좌표 |
| buildings{}.units[]  | 호별 [동, 호, 전용면적(㎡), 보증금(원), 월임대료(원)] |
| buildings{}.plans[]  | 건축 도면(층별 평면) 이미지 주소. SH가 '기타' 사진으로 올린 것 중 파일 이름에 건축·도면·평면이 들어간 것 |
| buildings{}.photos[] | 전경·정문·주차장·실내 등 사진 주소 |

- 건물이 약 3,350곳이라 한 번에 다 읽지 않는다. 실행마다 요청 수 상한(기본 1,500회, 약 450곳)까지만 읽고
  다음 실행이 이어서 읽는다. 먼저 읽을 자치구(PRIORITY)를 앞에 두고, 그다음 서울 전체를 목록 순서대로 돈다.
- 이번 달에 이미 읽은 건물은 다시 읽지 않는다(자료 기준이 월 단위).
- 요청 사이에 1.5초를 쉬고, 수집기 이름을 그대로 밝힌 User-Agent 를 쓴다. 이미지는 내려받지 않고 주소만 남긴다.

실행: python scripts/collect_sh_purchased.py [--max-requests 1500]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "sh_purchased.json"
KST = timezone(timedelta(hours=9))
UA = "sohyunrichlab-notice-collector/1.0 (+https://revi404.github.io/sohyunrichlab/)"
SITE = "https://www.i-sh.co.kr"
API = SITE + "/houseinfo/map/"
PAGE_SIZE = 5
CATEGORY = {"20": "매입다가구", "30": "매입원룸"}
PRIORITY = ["11740", "11710", "11200"]  # 먼저 읽을 자치구: 강동·송파·성동 (법정 시군구 코드)
PLAN_NAME = re.compile(r"건축|도면|평면")


class Budget(Exception):
    pass


class Client:
    def __init__(self, limit: int):
        self.left = limit
        self.used = 0

    def call(self, ep: str, params: dict | None = None):
        if self.left <= 0:
            raise Budget()
        self.left -= 1
        self.used += 1
        time.sleep(1.5)
        data = urllib.parse.urlencode(params or {}).encode()
        req = urllib.request.Request(API + ep, data=data, headers={"User-Agent": UA, "X-Requested-With": "XMLHttpRequest"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8", "replace"))


def clean(d: dict) -> dict:
    return {k: v for k, v in d.items() if v not in (None, "", "-", [], {})}


def num(v):
    try:
        f = float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return None
    return int(f) if f == int(f) else f


def img_url(i: dict) -> str | None:
    if not i.get("imgNewFileNm"):
        return None
    path = "/" + "/".join(p for p in (i.get("imgPath") or "").split("/") if p)
    return f"{SITE}/houseinfo{path}/{urllib.parse.quote(i['imgNewFileNm'])}"


def building(c: Client, row: dict, ty: str, today: str) -> dict | None:
    """건물 한 곳: 개요 1회 + 호 목록 1회 + 사진 목록 1회."""
    b = str(row.get("biznsCd"))
    base = c.call("selectHouseBscDetail.do", {"ctgrCd": ty, "biznsCd": b}).get("result") or {}
    r = c.call("selectMltOrmHsTyDetailInfo.do", {"biznsCd": b, "ctgrCd": ty})
    m = r.get("resultMap") or {}
    units = [[u.get("dong"), u.get("ho"), num(u.get("privuseAr")), num(u.get("stdsGrtm")), num(u.get("stdsRent"))]
             for u in r.get("resultList") or []]
    as_of = next((u.get("stdsYm") for u in r.get("resultList") or [] if u.get("stdsYm")), None)
    plans, photos = [], []
    for i in c.call("selectImgList.do", {"biznsCd": b, "imgTy": ""}).get("result") or []:
        url = img_url(i)
        if not url:
            continue
        if i.get("imgTyNm") == "기타" and PLAN_NAME.search(i.get("imgOriFileNm") or ""):
            plans.append(clean({"name": i.get("imgNm"), "url": url}))
        else:
            photos.append(clean({"kind": i.get("imgTyNm"), "url": url}))
    if not base and not units:
        return None
    return clean({
        "id": b, "category": CATEGORY.get(ty, ty), "group": row.get("bizns1Nm"), "name": base.get("biznsViewNm") or row.get("biznsViewNm"),
        "addr": (base.get("addr") or row.get("addr") or "").strip(), "elevator": base.get("elevInstlAt"), "floors": num(base.get("floorNum")),
        "built": base.get("cocwDt") or row.get("cocwDt"), "heating": base.get("hetTyNm"), "center": base.get("chrgCntrNm"),
        "surroundings": base.get("lfCondDesc"), "lat": num(row.get("posX")), "lng": num(row.get("posY")),
        "vacant": num(m.get("empthSplyPsblCnt")), "waitlist": num(m.get("rsrvCount")), "moved_out_1y": num(m.get("oneyrLaveCnt")),
        "as_of": as_of, "units": units, "plans": plans, "photos": photos, "fetched": today,
    }) | {"vacant": num(m.get("empthSplyPsblCnt")) or 0}


def dump(result: dict) -> str:
    """건물 하나를 한 줄에 써서 파일 크기와 변경 내역을 줄인다."""
    head = {k: v for k, v in result.items() if k != "buildings"}
    lines = [json.dumps(head, ensure_ascii=False)[:-1] + ', "buildings": {']
    items = list(result["buildings"].items())
    for n, (k, v) in enumerate(items):
        lines.append(f' {json.dumps(k)}: {json.dumps(v, ensure_ascii=False, separators=(",", ":"))}' + ("," if n < len(items) - 1 else ""))
    lines.append("}}")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-requests", type=int, default=1500, help="한 번 실행에서 보낼 요청 수 상한")
    args = ap.parse_args()
    now = datetime.now(KST)
    today, month = now.strftime("%Y-%m-%d"), now.strftime("%Y-%m")
    prev = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    buildings: dict[str, dict] = dict(prev.get("buildings", {}))
    state: dict = dict(prev.get("progress", {}))
    cursor: dict = dict(state.get("cursor", {}))   # "구분:자치구" → 다음에 읽을 쪽
    totals: dict = dict(state.get("totals", {}))
    c = Client(args.max_requests)
    fresh = lambda b: (buildings.get(b) or {}).get("fetched", "")[:7] == month  # noqa: E731
    done = failed = 0

    # 먼저 읽을 자치구 → 서울 전체. 한 묶음을 끝까지 돌면 다음 묶음으로 넘어가고, 모두 돌면 다음 달에 다시 시작한다.
    lanes = [(ty, sig) for sig in [*PRIORITY, ""] for ty in CATEGORY]
    try:
        for ty, sig in lanes:
            key = f"{ty}:{sig or 'all'}"
            if cursor.get(key) == f"done:{month}":
                continue
            page = cursor.get(key) if isinstance(cursor.get(key), int) else 1
            while True:
                r = c.call("selectHouseRentWithFilter.do", {"pageNum": page, "sigCd": sig, "emdCd": "", "chkRentTy": ty, "sortGubun": "hoCntSort"})
                rows = r.get("result") or []
                total = num(r.get("totalCnt"))
                if total is not None:
                    totals[key] = total
                for row in rows:
                    b = str(row.get("biznsCd"))
                    if fresh(b):
                        continue
                    try:
                        d = building(c, row, ty, today)
                    except Budget:
                        raise
                    except Exception as e:  # noqa: BLE001
                        failed += 1
                        print(f"건물 {b} 실패: {type(e).__name__}", file=sys.stderr)
                        if failed >= 20 and not done:
                            raise RuntimeError("연속 실패가 많아 중단") from e
                        continue
                    if d:
                        buildings[b] = d
                        done += 1
                if not rows or (total and page * PAGE_SIZE >= total):
                    cursor[key] = f"done:{month}"
                    break
                page += 1
                cursor[key] = page
    except Budget:
        print("요청 상한에 도달해 여기까지만 저장")
    except Exception as e:  # noqa: BLE001
        print(f"중단: {type(e).__name__}: {e}", file=sys.stderr)
        if not done:
            return 1

    all_total = (totals.get("20:all") or 0) + (totals.get("30:all") or 0) or None
    result = {"updated": now.strftime("%Y-%m-%d %H:%M"), "source_note": "SH 서울주택정보(i-sh.co.kr/houseinfo) 화면 데이터, 매입다가구·매입원룸",
              "unit_fields": ["동", "호", "전용면적(㎡)", "보증금(원)", "월임대료(원)"],
              "progress": clean({"total": all_total, "collected": len(buildings), "cursor": cursor, "totals": totals}),
              "buildings": buildings}
    with_plans = sum(1 for b in buildings.values() if b.get("plans"))
    print(f"요청 {c.used}회, 새로 읽은 건물 {done}곳, 실패 {failed}건, 누적 {len(buildings)}/{all_total or '?'}곳, 도면 있는 건물 {with_plans}곳")
    if prev.get("buildings") == buildings and prev.get("progress") == result["progress"]:
        print("바뀐 내용 없음")
        return 0
    OUT.write_text(dump(result), encoding="utf-8")
    print(f"저장: {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
