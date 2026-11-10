"""SH 주택정보(서울주택정보) 수집기 (소현리치랩).

https://www.i-sh.co.kr/houseinfo/main/mainPage.do 화면이 쓰는 데이터를 읽어 data/sh_houses.json 에 저장한다.

| 묶음 | 내용 |
|---|---|
| notices      | 진행 중인 모집공고와 해당 단지 번호 |
| model_houses | 사이버 모델하우스 주소(단지·주택형별) |
| complexes    | 단지 개요, 주택형별 면적·세대수·보증금·월임대료·공가·예비자 수, 평면도·전경 이미지 주소 |

- 단지는 813곳(아파트 등)이라 한 번에 다 읽지 않는다. 실행마다 진행 중 공고 단지와 사이버 모델하우스 단지를 먼저 읽고,
  나머지는 목록 순서대로 조금씩(기본 40곳) 읽어 몇 주에 걸쳐 한 바퀴를 돈다. 자료 기준월이 월 단위라 이 속도로 충분하다.
- 요청 사이에 1.5초를 쉬고, 수집기 이름을 그대로 밝힌 User-Agent 를 쓴다.
- 이미지는 내려받지 않고 주소만 남긴다.

실행: python scripts/collect_sh_houses.py [--batch 40] [--max-requests 700]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "sh_houses.json"
KST = timezone(timedelta(hours=9))
UA = "sohyunrichlab-notice-collector/1.0 (+https://revi404.github.io/sohyunrichlab/)"
SITE = "https://www.i-sh.co.kr"
API = SITE + "/houseinfo/map/"
NOTICE_VIEW = SITE + "/main/lay2/program/S1T294C297/www/brd/m_247/view.do?seq="
PAGE_SIZE = 5  # 단지 목록 한 쪽에 오는 개수
CATEGORY = {"10": "아파트 등", "20": "매입다가구", "30": "매입원룸"}


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
    return {k: v for k, v in d.items() if v not in (None, "", [], {})}


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


def model_house(m: dict) -> dict:
    return clean({"type": m.get("splyTy"), "url": m.get("cyberModelhouseUrl"), "as_of": m.get("stdsYm")})


def unit_type(d: dict) -> dict:
    return clean({
        "type": d.get("splyTy"), "class": d.get("hsClNm"), "households": num(d.get("hshdCnt")),
        "exclusive_area": num(d.get("privuseAr")), "contract_area": num(d.get("cntrcAr")), "rooms": num(d.get("roomNo")),
        "deposit": num(d.get("infoLeasGrtm")), "rent": num(d.get("infoLeasRent")),
        "vacant": num(d.get("empthSplyPsblCnt")), "waitlist": num(d.get("rsrvCount")),
        "moved_out_1y": num(d.get("oneyrLaveCnt")), "as_of": d.get("stdsYm")})


def complex_detail(c: Client, bizns: str, today: str) -> dict | None:
    """단지 한 곳. 주택 구분(아파트 등/매입다가구/매입원룸)을 모르면 아파트 등으로 먼저 물어본다."""
    r = c.call("selectHouseBscDetail.do", {"ctgrCd": "10", "biznsCd": bizns})
    base = r.get("result") or {}
    if not base:
        return None
    se = str(base.get("hsSe") or "10")
    out = clean({
        "id": bizns, "name": base.get("biznsViewNm"), "addr": base.get("addr"), "category": CATEGORY.get(se, se),
        "supply": base.get("subSplyTyNm"), "units": num(base.get("totHoCnt") or base.get("hoCnt")),
        "type_list": base.get("hsTyLst"), "heating": base.get("hetTyNm"), "corridor": base.get("psgeTyNm"),
        "builder": base.get("cnstrtCorp"), "center": base.get("chrgCntrNm"), "surroundings": base.get("lfCondDesc"),
        "model_houses": [model_house(m) for m in r.get("resultD") or []],
    })
    types = []
    if se == "10":
        for s in c.call("selectSplyTyInfo.do", {"biznsCd": bizns}).get("result") or []:
            ty = s.get("splyTy")
            plans = [clean({"name": i.get("imgNm"), "url": img_url(i)})
                     for i in c.call("selectSplyTyImgInfo.do", {"biznsCd": bizns, "splyTy": ty}).get("result") or []]
            tags = c.call("selectHouseHsTyTagInfo.do", {"biznsCd": bizns, "splyTy": ty}).get("result") or []
            for t in tags:
                d = c.call("selectHouseHsTyDetailInfo.do", {"biznsCd": bizns, "hsCl": t.get("hsCl"), "splyTy": ty}).get("result") or {}
                if d:
                    types.append(clean({**unit_type(d), "floorplans": plans}))
    else:
        r2 = c.call("selectMltOrmHsTyDetailInfo.do", {"biznsCd": bizns, "ctgrCd": se})
        m = r2.get("resultMap") or {}
        out.update(clean({"vacant": num(m.get("empthSplyPsblCnt")), "waitlist": num(m.get("rsrvCount")),
                          "moved_out_1y": num(m.get("oneyrLaveCnt"))}))
        types = [unit_type(d) for d in r2.get("resultList") or []]
    out["types"] = types
    out["images"] = [clean({"kind": i.get("imgTyNm"), "name": i.get("imgNm"), "url": img_url(i), "taken": i.get("picDe")})
                     for i in c.call("selectImgList.do", {"biznsCd": bizns, "imgTy": "01"}).get("result") or []]
    out["fetched"] = today
    return clean(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", type=int, default=40, help="목록 순서대로 새로 읽을 단지 수")
    ap.add_argument("--max-requests", type=int, default=700, help="한 번 실행에서 보낼 요청 수 상한")
    args = ap.parse_args()
    now = datetime.now(KST)
    today, month = now.strftime("%Y-%m-%d"), now.strftime("%Y-%m")
    prev = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    complexes: dict[str, dict] = prev.get("complexes", {})
    state = prev.get("progress", {})
    c = Client(args.max_requests)
    fresh = lambda b: (complexes.get(b) or {}).get("fetched", "")[:7] == month  # noqa: E731  이번 달에 이미 읽은 단지

    try:
        notices = [clean({"seq": n.get("seq"), "title": n.get("recrnotiNm"), "code": n.get("recrnotiCd"),
                          "date": n.get("regDate"), "complex_ids": [b for b in (n.get("biznsCd") or "").split(",") if b],
                          "url": NOTICE_VIEW + str(n.get("seq"))})
                   for n in c.call("selectNoticeInProgressList.do").get("result") or []]
        groups = c.call("selectModelHouseList.do").get("result") or []
        models = [clean({"complex_id": m.get("biznsCd"), "name": m.get("biznsViewNm"), **model_house(m)}) for g in groups for m in g]
    except Exception as e:  # noqa: BLE001
        print(f"SH 주택정보 접속 실패: {type(e).__name__}", file=sys.stderr)
        return 1

    # 1) 진행 중 공고 단지 → 2) 사이버 모델하우스 단지 → 3) 목록 순서대로
    first = [b for n in notices for b in n.get("complex_ids", [])] + [m["complex_id"] for m in models if m.get("complex_id")]
    queue = [b for b in dict.fromkeys(first) if not fresh(b)]
    page, total = int(state.get("next_page", 1)), state.get("total")
    done_new, failed = 0, 0
    try:
        for b in queue:
            d = complex_detail(c, b, today)
            if d:
                complexes[b] = d
                done_new += 1
        picked = 0
        while picked < args.batch:
            r = c.call("selectHouseRentWithFilter.do", {"pageNum": page, "sigCd": "", "emdCd": "", "chkRentTy": "10", "sortGubun": "hoCntSort"})
            total = num(r.get("totalCnt")) or total
            rows = r.get("result") or []
            for row in rows:
                b = str(row.get("biznsCd"))
                if fresh(b):
                    continue
                try:
                    d = complex_detail(c, b, today)
                except Budget:
                    raise
                except Exception as e:  # noqa: BLE001
                    failed += 1
                    print(f"단지 {b} 실패: {type(e).__name__}", file=sys.stderr)
                    continue
                if d:
                    d.update(clean({"lat": num(row.get("posX")), "lng": num(row.get("posY")), "built": row.get("cocwDt")}))
                    complexes[b] = d
                    done_new += 1
                    picked += 1
            page = 1 if not rows or (total and page * PAGE_SIZE >= total) else page + 1
            if page == 1:
                break
    except Budget:
        print("요청 상한에 도달해 여기까지만 저장")
    except Exception as e:  # noqa: BLE001
        failed += 1
        print(f"중단: {type(e).__name__}", file=sys.stderr)

    result = {"updated": now.strftime("%Y-%m-%d %H:%M"), "source_note": "SH 서울주택정보(i-sh.co.kr/houseinfo) 화면 데이터",
              "progress": clean({"total": total, "collected": len(complexes), "next_page": page}),
              "notices": notices, "model_houses": models, "complexes": complexes}
    same = all(prev.get(k) == result[k] for k in ("notices", "model_houses", "complexes", "progress"))
    print(f"요청 {c.used}회, 새로 읽은 단지 {done_new}곳, 실패 {failed}건, 누적 {len(complexes)}/{total}")
    if same:
        print("바뀐 내용 없음")
        return 0
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"저장: {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
