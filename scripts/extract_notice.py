"""공고문 PDF 를 받아 글과 표만 뽑아 data/notice_text/<공고 id>.json 으로 남긴다 (소현리치랩).

PDF 원본은 저장하지 않는다. 받은 파일은 임시 폴더에서 읽고 바로 지운다.

- 대상 지정: python scripts/extract_notice.py --ids lh-0000061207,gh-843
- 자동:     python scripts/extract_notice.py --auto [--max 5]
  아직 뽑지 않은 진행 중 모집공고 가운데 GH 전체와 LH 분양(신혼희망타운 포함)을 공고일이 최근인 것부터 고른다.
  LH 임대는 건수가 많아 필요할 때 --ids 로 지정한다.
- SH 는 첨부 내려받기 주소가 공개돼 있지 않아 대상에서 뺀다.

필요 라이브러리: pdfplumber (pypdfium2 포함)
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pdfplumber

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "public_housing.json"
OUT = ROOT / "data" / "notice_text"
KST = timezone(timedelta(hours=9))
UA = "sohyunrichlab-notice-collector/1.0 (+https://revi404.github.io/sohyunrichlab/)"
ACTIVE = ("공고중", "접수중", "정정공고중")
MAX_BYTES = 40 * 1024 * 1024
MAX_PAGES = 150


def pick_pdf(n: dict) -> dict | None:
    """공고문 PDF 하나를 고른다. 정정공고문이 있으면 그것을, 없으면 공고문을 쓴다."""
    files = [f for f in (n.get("detail") or {}).get("files", []) if f.get("url") and f.get("name", "").lower().endswith(".pdf")]
    if not files:
        return None

    def rank(f: dict) -> int:
        kind, name = f.get("kind") or "", f.get("name") or ""
        if "정정공고문" in kind:
            return 0
        if "공고문" in kind:
            return 1
        if "공고" in name and not any(w in name for w in ("팸플릿", "카탈로그", "양식", "서식")):
            return 2
        return 9

    best = min(files, key=rank)
    return best if rank(best) < 9 else None


def download(url: str, dest: Path) -> int:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    size = 0
    with urllib.request.urlopen(req, timeout=60) as r, dest.open("wb") as f:
        while chunk := r.read(1 << 16):
            size += len(chunk)
            if size > MAX_BYTES:
                raise RuntimeError("파일이 너무 큼")
            f.write(chunk)
    return size


def tidy(table: list[list]) -> list[list[str]]:
    """빈 칸만 있는 열과 줄을 뺀다."""
    rows = [[(c or "").strip() for c in row] for row in table]
    width = max((len(r) for r in rows), default=0)
    rows = [r + [""] * (width - len(r)) for r in rows]
    keep = [i for i in range(width) if any(r[i] for r in rows)]
    return [[r[i] for i in keep] for r in rows if any(r)]


def extract(path: Path) -> tuple[list[dict], int, str]:
    """쪽마다 pdfplumber 로 글과 표를 뽑고, 그 쪽을 읽지 못하면 pypdfium2 로 글만 뽑는다."""
    import pypdfium2

    spare = pypdfium2.PdfDocument(str(path))
    total = len(spare)
    pages, fallback = [], 0
    try:
        plumb = pdfplumber.open(path)
    except Exception:  # noqa: BLE001
        plumb = None
    for i in range(min(total, MAX_PAGES)):
        entry = {"page": i + 1}
        try:
            page = plumb.pages[i].dedupe_chars(tolerance=1)  # 굵은 글씨를 겹쳐 찍은 글자 정리
            tables = [t for t in (tidy(t) for t in page.extract_tables() or []) if len(t) > 1 and len(t[0]) > 1]
            entry["text"] = (page.extract_text() or "").strip()
            if tables:
                entry["tables"] = tables
        except Exception:  # noqa: BLE001
            fallback += 1
            entry["text"] = spare[i].get_textpage().get_text_range().replace("\r\n", "\n").strip()
            entry["tables_missing"] = True
        pages.append(entry)
    if plumb:
        plumb.close()
    spare.close()
    return pages, total, f"pdfplumber, {fallback}쪽은 글만" if fallback else "pdfplumber"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", default="", help="공고 id (쉼표 구분)")
    ap.add_argument("--auto", action="store_true")
    ap.add_argument("--max", type=int, default=5, help="--auto 에서 한 번에 뽑을 공고 수")
    ap.add_argument("--force", action="store_true", help="이미 뽑은 공고도 다시 뽑기")
    args = ap.parse_args()
    notices = {n["id"]: n for n in json.loads(SRC.read_text(encoding="utf-8"))["notices"]}
    OUT.mkdir(parents=True, exist_ok=True)

    ids = [i.strip() for i in args.ids.split(",") if i.strip()]
    if args.auto:
        auto = [n for n in notices.values()
                if n["kind"] == "모집공고" and n.get("status") in ACTIVE and pick_pdf(n)
                and (n["src"] == "gh" or (n["src"] == "lh" and n["deal"] == "분양"))
                and not (OUT / f"{n['id']}.json").exists()]
        auto.sort(key=lambda n: n.get("notice_date") or "", reverse=True)
        ids += [n["id"] for n in auto[: args.max]]
    if not ids:
        print("뽑을 공고 없음")
        return 0

    failed = 0
    for nid in dict.fromkeys(ids):
        n = notices.get(nid)
        target = OUT / f"{nid}.json"
        if n is None:
            print(f"[{nid}] 공고 파일에 없는 id", file=sys.stderr)
            failed += 1
            continue
        if target.exists() and not args.force:
            print(f"[{nid}] 이미 있음")
            continue
        pdf = pick_pdf(n)
        if pdf is None:
            print(f"[{nid}] 받을 수 있는 공고문 PDF 없음", file=sys.stderr)
            failed += 1
            continue
        try:
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "notice.pdf"
                size = download(pdf["url"], path)
                pages, total, engine = extract(path)
        except Exception as e:  # noqa: BLE001
            print(f"[{nid}] 실패: {type(e).__name__} {e}", file=sys.stderr)
            failed += 1
            continue
        chars = sum(len(p["text"]) for p in pages)
        result = {"id": nid, "org": n["org"], "title": n["title"], "notice_date": n.get("notice_date"), "url": n["url"],
                  "file": {"name": pdf["name"], "kind": pdf.get("kind"), "url": pdf["url"], "bytes": size},
                  "extracted": datetime.now(KST).strftime("%Y-%m-%d %H:%M"), "engine": engine, "total_pages": total,
                  # 글자가 거의 없으면 그림으로 된 PDF 라 글을 뽑지 못한 것이다
                  "text_ok": chars >= 200 * max(1, min(len(pages), 3)), "pages": pages}
        target.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        tables = sum(len(p.get("tables", [])) for p in pages)
        print(f"[{nid}] {total}쪽, 글자 {chars:,}자, 표 {tables}개 → {target.relative_to(ROOT)}")
        time.sleep(2)
    return 1 if failed and failed == len(set(ids)) else 0


if __name__ == "__main__":
    sys.exit(main())
