"""평면도 이미지 내려받기 (소현리치랩 임대주택 보드).

보드(data/boards/*.json)에 적힌 평면도와 SH 주택정보 수집 결과(data/sh_houses.json)의 평면도 전부를 받아
화면과 블로그 글에서 바로 보이도록 줄여서 저장한다. 보드에 쓰는 평면도를 먼저 받고, 나머지는 실행마다 조금씩 채운다.

| 결과 | 내용 |
|---|---|
| assets/plans/<주소 해시>.webp | 긴 변 1600px 이하로 줄인 평면도 |
| data/plans.json               | 주소 → 파일·크기·받은 날짜. 화면이 이 표를 읽어 이미지를 붙인다 |

- 이미 받은 주소는 다시 받지 않는다(--refresh 로 전부 다시 받기).
- 이미지 파일이 아닌 주소(블로그·영상)는 건너뛰고, 화면에서는 링크로 남는다.
- 요청 사이에 1.5초를 쉬고, 수집기 이름을 그대로 밝힌 User-Agent 를 쓴다.
- 보드에도 수집 결과에도 없게 된 파일은 지운다.

실행: python scripts/fetch_floorplans.py [--refresh] [--max 300]
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parent.parent
BOARDS = ROOT / "data" / "boards"
PLANS = ROOT / "assets" / "plans"
HOUSES = ROOT / "data" / "sh_houses.json"
MANIFEST = ROOT / "data" / "plans.json"
KST = timezone(timedelta(hours=9))
UA = "sohyunrichlab-notice-collector/1.0 (+https://revi404.github.io/sohyunrichlab/)"
IMAGE_EXT = re.compile(r"\.(jpe?g|png|gif|webp|bmp|tiff?)$", re.I)
MAX_SIDE = 1600
MAX_BYTES = 25 * 1024 * 1024


def is_image_url(url: str) -> bool:
    return bool(IMAGE_EXT.search(urllib.parse.urlsplit(url).path))


def board_urls() -> list[str]:
    """모든 보드에서 평면도 주소를 순서대로, 겹치지 않게 모은다."""
    urls: dict[str, None] = {}
    for f in sorted(BOARDS.glob("*.json")):
        if f.name == "index.json":
            continue
        board = json.loads(f.read_text(encoding="utf-8"))
        for tab in board.get("tabs", []):
            for item in tab.get("items", []):
                for u in [item.get("plan_url"), *(item.get("plan_urls") or [])]:
                    if u and is_image_url(u):
                        urls[u] = None
    return list(urls)


def house_urls() -> list[str]:
    """SH 주택정보 수집 결과에 있는 모든 주택형의 평면도 주소."""
    if not HOUSES.exists():
        return []
    urls: dict[str, None] = {}
    for cx in json.loads(HOUSES.read_text(encoding="utf-8")).get("complexes", {}).values():
        for t in cx.get("types") or []:
            for p in t.get("floorplans") or []:
                if p.get("url") and is_image_url(p["url"]):
                    urls[p["url"]] = None
    return list(urls)


def download(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": "https://www.i-sh.co.kr/houseinfo/main/mainPage.do"})
    with urllib.request.urlopen(req, timeout=40) as r:
        data = r.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("파일이 너무 큼")
    return data


def to_webp(data: bytes) -> tuple[bytes, int, int]:
    im = Image.open(io.BytesIO(data))
    im.seek(0)  # gif·tiff 는 첫 장만
    im = ImageOps.exif_transpose(im)
    if im.mode in ("RGBA", "LA", "P"):
        rgba = im.convert("RGBA")
        bg = Image.new("RGB", rgba.size, "white")  # 투명 배경은 흰색으로
        bg.paste(rgba, mask=rgba.split()[-1])
        im = bg
    else:
        im = im.convert("RGB")
    im.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
    out = io.BytesIO()
    im.save(out, "WEBP", quality=82, method=6)
    return out.getvalue(), im.width, im.height


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="이미 받은 이미지도 다시 받기")
    ap.add_argument("--max", type=int, default=300, help="한 번 실행에서 새로 받을 최대 장수")
    args = ap.parse_args()
    today = datetime.now(KST).strftime("%Y-%m-%d")
    prev = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else {}
    before = prev.get("plans", {})
    plans: dict[str, dict] = dict(before)
    first = board_urls()
    urls = list(dict.fromkeys([*first, *house_urls()]))  # 보드에 쓰는 것 먼저
    PLANS.mkdir(parents=True, exist_ok=True)

    done = failed = 0
    for url in urls:
        have = plans.get(url)
        if have and (ROOT / have["file"]).exists() and not args.refresh:
            continue
        if done >= args.max:
            print(f"한 번에 받을 장수({args.max})에 도달해 나머지는 다음 실행에서 받음")
            break
        if done or failed:
            time.sleep(1.5)
        try:
            webp, w, h = to_webp(download(url))
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"실패: {url} ({type(e).__name__}: {e})", file=sys.stderr)
            if failed >= 30 and not done:
                print("연속 실패가 많아 중단", file=sys.stderr)
                break
            continue
        name = hashlib.sha1(url.encode()).hexdigest()[:16] + ".webp"
        (PLANS / name).write_bytes(webp)
        plans[url] = {"file": f"assets/plans/{name}", "w": w, "h": h, "fetched": today}
        done += 1

    # 어느 보드에서도 쓰지 않는 항목과 파일 정리
    used = set(urls)
    plans = {u: p for u, p in plans.items() if u in used and (ROOT / p["file"]).exists()}
    keep = {Path(p["file"]).name for p in plans.values()}
    removed = 0
    for f in PLANS.glob("*.webp"):
        if f.name not in keep:
            f.unlink()
            removed += 1

    print(f"보드용 {len(first)}개 포함 평면도 주소 {len(urls)}개, 새로 받음 {done}장, 실패 {failed}건, 정리 {removed}장, 보유 {len(plans)}장")
    if plans != before:
        MANIFEST.write_text(json.dumps({"updated": datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "plans": plans},
                                       ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"저장: {MANIFEST.relative_to(ROOT)}")
    # 하나도 받지 못했다면 접속 문제이므로 실패로 알린다
    return 1 if failed and not plans else 0


if __name__ == "__main__":
    sys.exit(main())
