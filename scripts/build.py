"""소현리치랩 링크페이지 데이터 수집기.

- 분석 리포트 탭: 티스토리 블로그의 상위 카테고리(지역 하위 카테고리는 합침)마다
  첫 페이지 최신 글을 모아 data/feed.json 에 저장한다. 카테고리 목록은 블로그 홈에서 읽으므로
  카테고리를 새로 만들면 자동으로 늘어난다. 티스토리 RSS 는 카테고리별 주소가 없고 최근 10편만
  주기 때문에 카테고리 목록 페이지를 읽는다.
- 이번 주 청약단지 탭: 화면이 sohyun-blog-kit 의 calendar.json 을 바로 읽는다. 그 주소가 막힐 때를
  대비해 같은 파일의 사본을 data/calendar.json 으로 둔다.
GitHub Actions 가 30분마다 실행한다. 로컬 실행: python scripts/build.py
"""
from __future__ import annotations

import hashlib
import html
import io
import json
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
DATA = ROOT / "data"
THUMBS = ROOT / "assets" / "thumbs"
FEED_FILE = DATA / "feed.json"
CAL_FILE = DATA / "calendar.json"
KST = timezone(timedelta(hours=9))
UA = "Mozilla/5.0 (compatible; sohyunrichlab-linkpage/1.0; +https://revi404.github.io/sohyunrichlab/)"
BLOG = CONFIG["blog"]["url"].rstrip("/")


def fetch(url: str, retries: int = 2) -> bytes:
    last = None
    for i in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": BLOG + "/"})
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1.5 * (i + 1))
    raise last  # type: ignore[misc]


def text(fragment: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", fragment))).strip()


def save_thumb(url: str) -> str:
    """티스토리 썸네일 주소는 서명이 만료되므로 assets/thumbs 에 저장해 둔다. 이름은 원본 이미지 경로 기준."""
    if not url:
        return ""
    if url.startswith("//"):
        url = "https:" + url
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    origin = (q.get("fname") or [url])[0].split("?")[0]
    name = hashlib.sha1(origin.encode()).hexdigest()[:16] + ".jpg"
    dest = THUMBS / name
    if not dest.exists():
        try:
            raw = fetch(url)
            try:
                from PIL import Image  # 있으면 400px 로 줄여 용량 절감

                im = Image.open(io.BytesIO(raw)).convert("RGB")
                im.thumbnail((400, 400))
                buf = io.BytesIO()
                im.save(buf, "JPEG", quality=82, optimize=True)
                raw = buf.getvalue()
            except Exception:  # noqa: BLE001
                pass
            THUMBS.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(raw)
        except Exception as e:  # noqa: BLE001
            print(f"  ! 썸네일 실패 {url[:80]}: {e}", file=sys.stderr)
            return ""
    return f"assets/thumbs/{name}"


# ---------- 카테고리 ----------
def top_categories() -> list[str]:
    """블로그 홈 사이드 메뉴의 상위 카테고리 이름(티스토리 기본 class link_item)."""
    page = fetch(BLOG + "/").decode("utf-8", "replace")
    names = []
    for href in re.findall(r'href="/category/([^"/?]+)"\s+class="link_item"', page):
        name = urllib.parse.unquote(href)
        if name not in names:
            names.append(name)
    order = CONFIG["blog"].get("order", [])
    hidden = set(CONFIG["blog"].get("hidden", []))
    names = [n for n in names if n not in hidden]
    return sorted(names, key=lambda n: (order.index(n) if n in order else len(order), names.index(n)))


def category_posts(name: str, limit: int) -> list[dict]:
    """카테고리 목록 1쪽의 글(스킨의 article.rl-tile)."""
    page = fetch(f"{BLOG}/category/{urllib.parse.quote(name)}").decode("utf-8", "replace")
    out, seen = [], set()
    for block in re.split(r'<article class="rl-tile"', page)[1:]:
        block = block.split("</article>")[0]
        href = re.search(r'<a\s+href="([^"]+)"', block)
        title = re.search(r'class="rl-tile-title"[^>]*>(.*?)</strong>', block, re.S)
        if not href or not title:
            continue
        url = urllib.parse.urljoin(BLOG + "/", html.unescape(href.group(1)))
        if url in seen:
            continue
        seen.add(url)
        img = re.search(r'<img\s+src="([^"]+)"', block)
        date = re.search(r'class="rl-date"[^>]*>(.*?)</time>', block, re.S)
        summ = re.search(r'class="rl-summary"[^>]*>(.*?)</span>', block, re.S)
        ymd = re.findall(r"\d+", text(date.group(1))) if date else []
        d = "{}-{:0>2}-{:0>2}".format(*ymd[:3]) if len(ymd) >= 3 else ""
        out.append({
            "title": text(title.group(1)),
            "url": url,
            "date": d,
            "summary": text(summ.group(1))[:90] if summ else "",
            "category": name,
            "thumbSrc": html.unescape(img.group(1)) if img else "",
        })
        if len(out) >= limit:
            break
    return out


def rss_times() -> dict[str, float]:
    """RSS 의 발행 시각(같은 날 글 순서용). 최근 글만 있다."""
    try:
        root = ET.fromstring(fetch(BLOG + "/rss"))
    except Exception as e:  # noqa: BLE001
        print(f"  ! RSS 실패: {e}", file=sys.stderr)
        return {}
    times = {}
    for it in root.iter("item"):
        link = urllib.parse.unquote((it.findtext("link") or "").strip())
        try:
            times[link] = parsedate_to_datetime(it.findtext("pubDate")).timestamp()
        except Exception:  # noqa: BLE001
            pass
    return times


def calendar_copy() -> None:
    url = CONFIG["week"]["dataUrl"]
    try:
        raw = fetch(url)
        json.loads(raw)
        CAL_FILE.write_bytes(raw)
    except Exception as e:  # noqa: BLE001
        print(f"  ! 청약 일정 사본 실패(이전 사본 유지): {e}", file=sys.stderr)


def main() -> None:
    DATA.mkdir(exist_ok=True)
    calendar_copy()

    per = CONFIG["blog"]["perCategory"]
    prev = json.loads(FEED_FILE.read_text(encoding="utf-8")) if FEED_FILE.exists() else {"posts": {}}
    try:
        cats = top_categories()
    except Exception as e:  # noqa: BLE001
        print(f"  ! 블로그 홈 실패, 이전 카테고리 유지: {e}", file=sys.stderr)
        cats = list(prev.get("categories") or prev["posts"].keys())

    by_cat: dict[str, list[dict]] = {}
    for name in cats:
        try:
            posts = category_posts(name, per)
        except Exception as e:  # noqa: BLE001
            print(f"  ! {name} 실패, 이전 글 유지: {e}", file=sys.stderr)
            by_cat[name] = prev["posts"].get(name, [])
            continue
        for p in posts:
            p["thumb"] = save_thumb(p.pop("thumbSrc"))
        by_cat[name] = posts
        print(f"  {name}: {len(posts)}편")

    # 전체 = 카테고리 글을 날짜순으로(같은 날은 RSS 발행 시각, 없으면 카테고리 목록 순서)
    times = rss_times()
    seen, merged = set(), []
    for name in cats:
        for k, p in enumerate(by_cat.get(name, [])):
            if p["url"] in seen:
                continue
            seen.add(p["url"])
            merged.append((p["date"], times.get(urllib.parse.unquote(p["url"]), 0), -k, p["url"]))
    merged.sort(reverse=True)
    all_urls = [m[3] for m in merged[: CONFIG["blog"]["allCount"]]]

    feed = {
        "updated": datetime.now(KST).strftime("%Y-%m-%d %H:%M"),
        "categories": cats,
        "all": all_urls,
        "posts": by_cat,
    }
    FEED_FILE.write_text(json.dumps(feed, ensure_ascii=False, indent=1), encoding="utf-8")

    # 더 이상 쓰지 않는 썸네일 정리
    used = {p["thumb"].rsplit("/", 1)[-1] for ps in by_cat.values() for p in ps if p.get("thumb")}
    for f in THUMBS.glob("*.jpg") if THUMBS.exists() else []:
        if f.name not in used:
            f.unlink()
    print(f"완료: 카테고리 {len(cats)}개, 글 {sum(len(v) for v in by_cat.values())}편")


if __name__ == "__main__":
    main()
