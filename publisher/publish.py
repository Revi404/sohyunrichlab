"""소현리치랩 단지 소개 글 자동 발행 (집 노트북에서 실행).

GitHub Pages 에 올라간 글 목록(data/complex_posts.json)에서 아직 안 올린 단지를 순서대로 꺼내
티스토리(자세한 글)와 네이버 블로그(요약 글)에 브라우저로 직접 올린다.
로그인은 처음 한 번 `login` 으로 이 프로그램 전용 브라우저에서 직접 하고, 그 뒤로는 저장된 로그인으로 돌아간다.

  python publish.py login                 # 처음 한 번: 티스토리·네이버 로그인
  python publish.py tistory --dry-run     # 올리기 직전까지만 하고 화면을 찍어 둔다(첫 시험용)
  python publish.py all                   # 설정한 개수만큼 두 블로그에 발행 (예약 실행이 부르는 명령)
  python publish.py status                # 발행 기록·남은 개수 보기

설정: config.json (없으면 config.example.json 을 복사해 만든다)
기록: state.json (발행한 단지와 주소). 지우면 처음부터 다시 올리게 되니 지우지 말 것.
화면 기록: shots/ (발행 직전 화면, 오류 화면)
"""
from __future__ import annotations

import argparse
import json
import platform
import random
import re
import shutil
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONFIG = HERE / "config.json"
STATE = HERE / "state.json"
PROFILE = HERE / ".profile"
SHOTS = HERE / "shots"
LOG = HERE / "publish.log"
PASTE_KEY = "Meta+V" if platform.system() == "Darwin" else "Control+V"
UA = "sohyunrichlab-publisher/1.0"


# ── 공통 ────────────────────────────────────────────────────────────────

def log(msg: str) -> None:
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line, flush=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def load_json(p: Path, default):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def save_json(p: Path, data) -> None:
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    tmp.replace(p)


def config() -> dict:
    if not CONFIG.exists():
        shutil.copy(HERE / "config.example.json", CONFIG)
        log("config.json 을 새로 만들었습니다. 블로그 주소·발행 개수를 확인하세요.")
    return load_json(CONFIG, {})


def fetch(cfg: dict, path: str) -> str:
    """글 목록·본문 읽기. source 가 폴더면 그 폴더에서(시험용), 아니면 GitHub Pages 에서."""
    src = cfg.get("source", "https://revi404.github.io/sohyunrichlab/")
    if not src.startswith("http"):
        return (Path(src) / path).read_text(encoding="utf-8")
    req = urllib.request.Request(src.rstrip("/") + "/" + path + f"?t={int(time.time())}", headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8")


def split_meta(text: str) -> tuple[dict, str]:
    m = re.match(r"<!-- sohyunrichlab-post (.*?) -->\n?", text)
    return (json.loads(m.group(1)), text[m.end():]) if m else ({}, text)


def next_posts(cfg: dict, site: str, n: int) -> list[dict]:
    idx = json.loads(fetch(cfg, "data/complex_posts.json"))
    state = load_json(STATE, {})
    done = set(state.get(site, {}))
    queue = idx.get("queue" if site == "tistory" else "naver_queue") or [p["id"] for p in idx.get("posts", [])]
    posts = {p["id"]: p for p in idx.get("posts", [])}
    out = []
    for pid in queue:
        if pid in done or pid not in posts:
            continue
        file = posts[pid]["file" if site == "tistory" else "naver_file"]
        meta, body = split_meta(fetch(cfg, file))
        out.append({"id": pid, "title": meta.get("title") or posts[pid].get("title"), "tags": meta.get("tags", []), "html": body})
        if len(out) >= n:
            break
    return out


def record(site: str, pid: str, url: str, title: str) -> None:
    state = load_json(STATE, {})
    state.setdefault(site, {})[pid] = {"url": url, "title": title, "at": datetime.now().strftime("%Y-%m-%d %H:%M")}
    save_json(STATE, state)


def shot(page, name: str) -> None:
    SHOTS.mkdir(exist_ok=True)
    f = SHOTS / f"{datetime.now():%m%d_%H%M%S}_{name}.png"
    try:
        page.screenshot(path=str(f), full_page=False)
        log(f"화면 저장: {f.name}")
    except Exception as ex:  # noqa: BLE001
        log(f"화면 저장 실패: {ex}")


def pause(a: float = 0.6, b: float = 1.4) -> None:
    time.sleep(random.uniform(a, b))


def browser(pw, cfg: dict):
    """이 프로그램 전용 로그인 프로필로 크롬(없으면 내장 크로미움)을 화면에 띄운다."""
    args = dict(user_data_dir=str(PROFILE), headless=False, viewport={"width": 1400, "height": 900}, locale="ko-KR",
                permissions=["clipboard-read", "clipboard-write"], args=["--disable-blink-features=AutomationControlled"])
    try:
        return pw.chromium.launch_persistent_context(channel=cfg.get("browser_channel", "chrome"), **args)
    except Exception:  # noqa: BLE001
        return pw.chromium.launch_persistent_context(**args)


class NeedLogin(Exception):
    pass


# ── 티스토리 ────────────────────────────────────────────────────────────

def tistory_post(page, cfg: dict, post: dict, dry: bool) -> str | None:
    blog = cfg["tistory_blog"]
    page.once("dialog", lambda d: d.dismiss())  # '저장된 글을 이어서 쓸까요?' → 아니요
    page.goto(f"https://{blog}.tistory.com/manage/newpost/?type=post&returnURL=ENTRY", wait_until="domcontentloaded")
    pause(2, 3)
    if "auth/login" in page.url or "kakao.com" in page.url:
        raise NeedLogin("티스토리")
    page.wait_for_selector("#post-title-inp", timeout=30000)
    page.wait_for_function("window.tinymce && tinymce.activeEditor && tinymce.activeEditor.initialized", timeout=30000)

    if cfg.get("tistory_category"):
        try:
            page.click("#category-btn", timeout=5000)
            pause()
            page.locator("#category-list [role=option], #category-list .mce-menu-item").filter(has_text=cfg["tistory_category"]).first.click(timeout=5000)
        except Exception:  # noqa: BLE001
            log(f"카테고리 '{cfg['tistory_category']}' 를 찾지 못해 기본 카테고리로 둡니다.")
        pause()

    page.fill("#post-title-inp", post["title"])
    pause()
    page.evaluate("html => { tinymce.activeEditor.setContent(html); tinymce.activeEditor.fire('change'); }", post["html"])
    pause()
    for tag in post["tags"][:10]:
        page.fill("#tagText", tag)
        page.press("#tagText", "Enter")
        pause(0.3, 0.6)
    shot(page, f"tistory_{post['id']}_ready")
    if dry:
        log("시험 모드라 '완료'를 누르지 않았습니다. 화면을 확인하세요.")
        return None

    page.click("#publish-layer-btn")
    page.wait_for_selector("#open20", state="attached", timeout=15000)
    page.locator("label[for=open20], #open20").first.click()  # 공개
    pause()
    page.click("#publish-btn")
    page.wait_for_url(re.compile(r"/manage/posts|/entry/|/\d+$"), timeout=30000)
    pause(2, 3)
    return tistory_url(blog, post["title"]) or f"https://{blog}.tistory.com/manage/posts"


def tistory_url(blog: str, title: str) -> str | None:
    """방금 올린 글 주소를 블로그 RSS 에서 제목으로 찾는다."""
    try:
        req = urllib.request.Request(f"https://{blog}.tistory.com/rss", headers={"User-Agent": UA})
        xml = urllib.request.urlopen(req, timeout=20).read().decode("utf-8")
        for item in re.findall(r"<item>(.*?)</item>", xml, re.S):
            t = re.search(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", item, re.S)
            link = re.search(r"<link>(.*?)</link>", item)
            if t and link and t.group(1).strip() == title:
                return link.group(1).strip()
    except Exception:  # noqa: BLE001
        pass
    return None


# ── 네이버 블로그 ───────────────────────────────────────────────────────

def editor_frame(page):
    for _ in range(30):
        f = page.frame(name="mainFrame")
        for cand in ([f] if f else []) + [page.main_frame]:
            try:
                if cand.locator(".se-documentTitle, .se-title-text").count():
                    return cand
            except Exception:  # noqa: BLE001
                pass
        time.sleep(1)
    raise RuntimeError("네이버 글쓰기 화면을 찾지 못했습니다.")


def click_if(frame, sel: str) -> None:
    try:
        loc = frame.locator(sel).first
        if loc.is_visible(timeout=1500):
            loc.click()
            pause(0.4, 0.8)
    except Exception:  # noqa: BLE001
        pass


def naver_post(page, cfg: dict, post: dict, dry: bool) -> str | None:
    nid = cfg["naver_blog_id"]
    page.goto(f"https://blog.naver.com/{nid}?Redirect=Write&", wait_until="domcontentloaded")
    pause(3, 4)
    if "nid.naver.com" in page.url:
        raise NeedLogin("네이버")
    fr = editor_frame(page)
    click_if(fr, ".se-popup-button-cancel")       # '작성 중인 글이 있습니다' → 취소
    click_if(fr, ".se-help-panel-close-button")   # 도움말 닫기

    fr.locator(".se-documentTitle .se-text-paragraph, .se-title-text").first.click()
    page.keyboard.type(post["title"], delay=40)
    pause()
    fr.locator(".se-component.se-text .se-text-paragraph").first.click()
    pause()
    plain = re.sub(r"<[^>]+>", "", post["html"])
    ok = fr.evaluate("""async ([html, plain]) => {
        try {
          await navigator.clipboard.write([new ClipboardItem({
            'text/html': new Blob([html], {type: 'text/html'}),
            'text/plain': new Blob([plain], {type: 'text/plain'})})]);
          return true;
        } catch (e) { return false; }
    }""", [post["html"], plain])
    if ok:
        page.keyboard.press(PASTE_KEY)
    else:  # 클립보드를 못 쓰면 붙여넣기 이벤트를 직접 보낸다
        fr.evaluate("""([html, plain]) => {
            const dt = new DataTransfer();
            dt.setData('text/html', html); dt.setData('text/plain', plain);
            document.activeElement.dispatchEvent(new ClipboardEvent('paste', {clipboardData: dt, bubbles: true, cancelable: true}));
        }""", [post["html"], plain])
    time.sleep(cfg.get("naver_image_wait_sec", 8))  # 평면도 이미지가 네이버로 올라갈 시간
    shot(page, f"naver_{post['id']}_ready")
    if dry:
        log("시험 모드라 '발행'을 누르지 않았습니다. 화면을 확인하세요.")
        return None

    fr.locator("button:has-text('발행')").first.click()
    pause(1.5, 2.5)
    try:
        tag_box = fr.locator("#tag-input, input[placeholder*='태그']").first
        for tag in post["tags"][:10]:
            tag_box.fill(tag)
            tag_box.press("Enter")
            pause(0.3, 0.6)
    except Exception:  # noqa: BLE001
        log("태그 입력 칸을 찾지 못해 태그 없이 발행합니다.")
    if cfg.get("naver_category"):
        try:
            fr.locator("[class*='selectbox'] button, [class*='category'] button").first.click(timeout=4000)
            fr.locator("[class*='option'], li").filter(has_text=cfg["naver_category"]).first.click(timeout=4000)
        except Exception:  # noqa: BLE001
            log(f"카테고리 '{cfg['naver_category']}' 를 찾지 못해 기본 카테고리로 둡니다.")
    shot(page, f"naver_{post['id']}_layer")
    fr.locator("button:has-text('발행')").last.click()
    page.wait_for_url(re.compile(r"PostView|logNo=|/\d{9,}"), timeout=40000)
    pause(2, 3)
    return page.url


# ── 실행 ────────────────────────────────────────────────────────────────

SITES = {"tistory": tistory_post, "naver": naver_post}
NAMES = {"tistory": "티스토리", "naver": "네이버"}


def run(sites: list[str], dry: bool, count: int | None) -> int:
    from playwright.sync_api import sync_playwright

    cfg = config()
    fails = 0
    with sync_playwright() as pw:
        ctx = browser(pw, cfg)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        for site in sites:
            n = 1 if dry else (count or int(cfg.get(f"{site}_per_run", 1)))
            if n <= 0:
                continue
            try:
                posts = next_posts(cfg, site, n)
            except Exception as ex:  # noqa: BLE001
                log(f"{NAMES[site]}: 글 목록을 읽지 못했습니다 ({ex})")
                fails += 1
                continue
            if not posts:
                log(f"{NAMES[site]}: 남은 글이 없습니다.")
            for post in posts:
                log(f"{NAMES[site]}: {post['title']} ({post['id']}) 올리는 중")
                try:
                    url = SITES[site](page, cfg, post, dry)
                    if url:
                        record(site, post["id"], url, post["title"])
                        log(f"{NAMES[site]}: 발행 완료 {url}")
                except NeedLogin as ex:
                    log(f"{ex} 로그인이 풀렸습니다. 'python publish.py login' 으로 다시 로그인하세요.")
                    fails += 1
                    break
                except Exception as ex:  # noqa: BLE001
                    shot(page, f"{site}_{post['id']}_error")
                    log(f"{NAMES[site]}: 실패 ({type(ex).__name__}: {str(ex)[:200]}) 다음 실행 때 다시 시도합니다.")
                    fails += 1
                    break
                if post is not posts[-1]:
                    time.sleep(random.uniform(*cfg.get("gap_minutes", [3, 6])) * 60)
        ctx.close()
    return 1 if fails else 0


def login() -> int:
    from playwright.sync_api import sync_playwright

    cfg = config()
    with sync_playwright() as pw:
        ctx = browser(pw, cfg)
        p1 = ctx.pages[0] if ctx.pages else ctx.new_page()
        p1.goto("https://www.tistory.com/auth/login")
        p2 = ctx.new_page()
        p2.goto("https://nid.naver.com/nidlogin.login")
        print("\n열린 브라우저에서 티스토리(카카오)와 네이버에 로그인하세요.")
        print("둘 다 '로그인 상태 유지'를 켜 두면 오래 유지됩니다. 다 했으면 여기서 Enter 를 누르세요.")
        input()
        ctx.close()
    log("로그인 정보를 저장했습니다.")
    return 0


def status() -> int:
    cfg = config()
    state = load_json(STATE, {})
    idx = json.loads(fetch(cfg, "data/complex_posts.json"))
    for site in SITES:
        done = state.get(site, {})
        q = idx.get("queue" if site == "tistory" else "naver_queue", [])
        left = [x for x in q if x not in done]
        last = max(done.values(), key=lambda v: v["at"], default=None)
        print(f"{NAMES[site]}: 발행 {len(done)}편 · 남은 글 {len(left)}편" + (f" · 마지막 {last['at']} {last['title']}" if last else ""))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="소현리치랩 단지 소개 글 자동 발행")
    ap.add_argument("what", choices=["login", "tistory", "naver", "all", "status"])
    ap.add_argument("--dry-run", action="store_true", help="발행 버튼 직전까지만 하고 화면을 저장")
    ap.add_argument("--count", type=int, help="이번에 올릴 글 수 (기본: config.json 의 *_per_run)")
    a = ap.parse_args()
    if a.what == "login":
        return login()
    if a.what == "status":
        return status()
    cfg = config()
    if a.what == "all" and not a.dry_run:
        delay = cfg.get("start_delay_minutes", [0, 20])
        time.sleep(random.uniform(*delay) * 60)  # 매일 같은 시각에 올라가지 않게 조금씩 늦춘다
    sites = ["tistory", "naver"] if a.what == "all" else [a.what]
    sites = [s for s in sites if cfg.get(f"{s}_enabled", True)]
    return run(sites, a.dry_run, a.count)


if __name__ == "__main__":
    sys.exit(main())
