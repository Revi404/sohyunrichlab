"""임시 시험: SH 주택정보 화면 데이터의 매입임대 응답 형태 확인. 머지 전에 지운다."""
import json, time, urllib.parse, urllib.request
UA = "sohyunrichlab-notice-collector/1.0 (+https://revi404.github.io/sohyunrichlab/)"
API = "https://www.i-sh.co.kr/houseinfo/map/"
def call(ep, params=None):
    time.sleep(1.5)
    req = urllib.request.Request(API + ep, data=urllib.parse.urlencode(params or {}).encode(), headers={"User-Agent": UA, "X-Requested-With": "XMLHttpRequest"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except Exception as e:
        return {"__error": f"{type(e).__name__}: {e}"}
def show(title, obj, n=2500):
    print("=====", title); print(json.dumps(obj, ensure_ascii=False)[:n])
for ty in ("20", "30"):
    r = call("selectHouseRentWithFilter.do", {"pageNum": 1, "sigCd": "", "emdCd": "", "chkRentTy": ty, "sortGubun": "hoCntSort"})
    show(f"list chkRentTy={ty} keys={list(r)} total={r.get('totalCnt')}", (r.get("result") or [])[:2])
    rows = r.get("result") or []
    for row in rows[:2]:
        b = str(row.get("biznsCd"))
        show(f"bsc {b} ctgr10", call("selectHouseBscDetail.do", {"ctgrCd": "10", "biznsCd": b}), 1500)
        show(f"bsc {b} ctgr{ty}", call("selectHouseBscDetail.do", {"ctgrCd": ty, "biznsCd": b}), 1500)
        show(f"mlt {b}", call("selectMltOrmHsTyDetailInfo.do", {"biznsCd": b, "ctgrCd": ty}), 2500)
        show(f"sply {b}", call("selectSplyTyInfo.do", {"biznsCd": b}), 800)
        for it in ("01", "02", "03", "04", ""):
            show(f"img {b} imgTy={it!r}", call("selectImgList.do", {"biznsCd": b, "imgTy": it}), 1200)
        show(f"splyimg {b}", call("selectSplyTyImgInfo.do", {"biznsCd": b, "splyTy": ""}), 800)
n = call("selectNoticeInProgressList.do")
show("notices", n, 3000)
