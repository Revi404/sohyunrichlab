#!/usr/bin/env python3
"""SH 공고문 쪽 그림의 금액 표 숫자 인식률 비교 시험 도구 (임시, 확인 후 삭제).

  python scripts/ocr_compare.py --tessdata-best DIR            # sh-313161 의 8,9,10쪽을 받아 모든 방식으로 인식
  python scripts/ocr_compare.py --local-image x.png --tessdata-best DIR   # 사이트 요청 없이 그림 한 장만

- 사이트 요청은 scripts/extract_sh_notice.py 의 Fetcher(UA·1초 간격·상한)를 그대로 쓴다. 쪽당 1회 + 앞단 2회.
- 그림은 임시 폴더에 받고 끝나면 지운다. 방식마다 try/except 로 감싸 실패해도 다음으로 넘어간다.
- 방식: A tess-fast-s3-psm6(현재 방식) / B tess-best-s3-psm6 / C tess-best-s4-psm6(선명화+자동 대비)
        D tess-best-s4-psm4 / E tess-best-s4-psm11 / F tess-cells(표 칸 단위) / G paddle
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
from pathlib import Path

sys.dont_write_bytecode = True  # scripts/__pycache__ 를 만들지 않는다
sys.path.insert(0, str(Path(__file__).resolve().parent))
import extract_sh_notice as esn  # noqa: E402  (함수만 재사용, 수정하지 않음)

ALL_VARIANTS = ["tess-fast-s3-psm6", "tess-best-s3-psm6", "tess-best-s4-psm6", "tess-best-s4-psm4",
                "tess-best-s4-psm11", "tess-cells", "paddle"]
SHORT = dict(zip("ABCDEFG", ALL_VARIANTS))
TEXT_LIMIT = 3000
TESS_TIMEOUT = 240
MAX_CELLS = 400
FALLBACK_FRAC = 0.12

OK_AMOUNT = re.compile(r"^\d{1,3}(,\d{3})+$")
NUMERIC = re.compile(r"^[\d,]*\d[\d,]*$")


class ToolMissing(Exception):
    """tesseract·모델 등이 없다."""


# ---------------------------------------------------------------- tesseract
def tess_run(img_path: Path, psm: int, tessdir: str | None, lang: str = "kor+eng") -> str:
    exe = shutil.which("tesseract")
    if not exe:
        raise ToolMissing("tesseract 없음 (apt-get install tesseract-ocr tesseract-ocr-kor)")
    cmd = [exe, str(img_path), "stdout", "-l", lang, "--psm", str(psm)]
    if tessdir:
        cmd[1:1] = ["--tessdata-dir", tessdir]
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=TESS_TIMEOUT)
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"tesseract {TESS_TIMEOUT}초 초과") from e
    if p.returncode != 0:
        raise RuntimeError(f"tesseract 오류 {p.returncode}: {p.stderr.decode('utf-8', 'replace').strip()[:200]}")
    return esn.tidy(p.stdout.decode("utf-8", "replace"))


def need_best(tessdir: str | None) -> str:
    if not tessdir or not Path(tessdir).is_dir():
        raise ToolMissing(f"tessdata_best 폴더 없음: {tessdir!r} (--tessdata-best)")
    for m in ("kor", "eng"):
        if not (Path(tessdir) / f"{m}.traineddata").exists():
            raise ToolMissing(f"{tessdir}/{m}.traineddata 없음")
    return tessdir


def gray_scaled(src: Path, scale: int):
    from PIL import Image
    with Image.open(src) as im:
        im = im.convert("L")
        return im.resize((im.width * scale, im.height * scale), Image.LANCZOS)


def enhance(im):
    from PIL import ImageFilter, ImageOps
    return ImageOps.autocontrast(im.filter(ImageFilter.SHARPEN))


def run_tess_variant(src: Path, work: Path, scale: int, psm: int, tessdir: str | None, sharpen: bool) -> str:
    if tessdir is not None:
        need_best(tessdir)
    im = gray_scaled(src, scale)
    if sharpen:
        im = enhance(im)
    big = work / f"{src.stem}_s{scale}{'e' if sharpen else ''}.png"
    im.save(big)
    return tess_run(big, psm, tessdir)


# ------------------------------------------------------------ 표 칸 인식 (F)
def _runs_to_lines(flags: list[bool]) -> list[tuple[int, int]]:
    """True 가 이어진 구간 (시작, 끝) 목록."""
    out, start = [], None
    for i, v in enumerate(flags + [False]):
        if v and start is None:
            start = i
        elif not v and start is not None:
            out.append((start, i - 1))
            start = None
    return out


def find_lines(bw, min_frac: float = 0.25, block: int = 8) -> tuple[list[int], list[int]]:
    """이진 그림(글자=255)에서 가로선 y 목록, 세로선 x 목록을 찾는다. numpy 없이 Pillow 만 쓴다.

    가로 방향을 block 화소씩 묶어(BOX 평균) 70% 이상 어두우면 '선 조각'으로 보고,
    한 줄에서 선 조각이 이어진 길이가 폭의 min_frac 이상이면 가로선 줄로 본다. 세로선은 전치해서 같은 방식.
    """
    from PIL import Image

    def scan(img, length_total: int) -> list[int]:
        w, h = img.size
        red = img.resize((max(1, w // block), h), Image.BOX).point(lambda v: 255 if v >= 178 else 0)
        rw = red.size[0]
        data = red.tobytes()
        need = min_frac * length_total / block
        flags = []
        for y in range(h):
            row = data[y * rw:(y + 1) * rw]
            longest = max((len(s) for s in row.split(b"\x00")), default=0)
            flags.append(longest >= need)
        return [(a + b) // 2 for a, b in _runs_to_lines(flags)]

    def scan2(img, length_total: int, frac: float) -> list[int]:
        nonlocal min_frac
        old, min_frac = min_frac, frac
        try:
            return scan(img, length_total)
        finally:
            min_frac = old

    w, h = bw.size
    ys = scan(bw, w)
    tr = bw.transpose(Image.TRANSPOSE)
    xs = scan(tr, h)
    if len(xs) < 2 or len(ys) < 2:  # 표가 짧아 25% 기준에 못 미치면 12% 로 한 번 더 (정해진 규칙에 덧붙인 보완)
        fb = FALLBACK_FRAC
        ys2, xs2 = (ys if len(ys) >= 2 else scan2(bw, w, fb)), (xs if len(xs) >= 2 else scan2(tr, h, fb))
        return ys2, xs2
    return ys, xs


def build_cells(ys: list[int], xs: list[int], min_size: int = 12) -> list[list[tuple[int, int, int, int]]]:
    """괘선 좌표로 칸 사각형을 행 단위로 만든다. 간격이 min_size 미만인 이웃 선(겹선)은 건너뛴다."""
    def thin(v: list[int]) -> list[int]:
        out: list[int] = []
        for p in v:
            if not out or p - out[-1] >= min_size:
                out.append(p)
        return out
    ys, xs = thin(ys), thin(xs)
    rows = []
    for i in range(len(ys) - 1):
        rows.append([(xs[j], ys[i], xs[j + 1], ys[i + 1]) for j in range(len(xs) - 1)])
    return rows


def ink_bands(cell_bw) -> int:
    """칸 안에서 글자 줄이 몇 덩어리인지(행 방향으로 어두운 줄이 이어진 구간, 높이 6 이상)."""
    from PIL import Image
    w, h = cell_bw.size
    col = cell_bw.resize((1, h), Image.BOX)
    flags = [v > 0 for v in col.tobytes()]
    return sum(1 for a, b in _runs_to_lines(flags) if b - a + 1 >= 6)


def ocr_cell(img_path: Path, psm: int, tessdir: str) -> str:  # 시험에서 가짜로 바꿀 수 있게 따로 둠
    return tess_run(img_path, psm, tessdir)


def run_cells(src: Path, work: Path, tessdir: str | None) -> str:
    from PIL import Image, ImageOps
    need_best(tessdir)
    gray = gray_scaled(src, 4)
    bw = gray.point(lambda v: 255 if v < 140 else 0)  # 어두운 화소 = 255
    ys, xs = find_lines(bw)
    notes = [f"가로선 {len(ys)}개 {ys[:12]}  세로선 {len(xs)}개 {xs[:12]}"]
    rows = build_cells(ys, xs)
    ncell = sum(len(r) for r in rows)
    if len(ys) < 2 or len(xs) < 2 or ncell == 0:
        return "괘선 없음\n" + notes[0]
    if ncell > MAX_CELLS:
        notes.append(f"칸 {ncell}개 중 앞 {MAX_CELLS}개만 인식")
    out_rows, done = [], 0
    pad = 8  # 지정은 4px 이지만 4배 확대에서 괘선 굵기(약 8px)의 절반이 칸 안으로 들어와 8 로 함
    for r in rows:
        cells = []
        for (x0, y0, x1, y1) in r:
            if done >= MAX_CELLS:
                cells.append("")
                continue
            done += 1
            box = (x0 + pad, y0 + pad, x1 - pad, y1 - pad)
            if box[2] - box[0] < 8 or box[3] - box[1] < 8:
                cells.append("")
                continue
            ink = bw.crop(box)
            if ink.getbbox() is None:  # 빈 칸
                cells.append("")
                continue
            bands = ink_bands(ink)
            psm = 6 if bands >= 2 else 7
            crop = ImageOps.expand(gray.crop(box), border=12, fill=255)
            p = work / "cell.png"
            crop.save(p)
            try:
                cells.append(" ".join(ocr_cell(p, psm, tessdir).split()))
            except ToolMissing:
                raise
            except Exception as e:  # noqa: BLE001  칸 하나 실패는 표시하고 계속
                cells.append(f"<오류 {type(e).__name__}>")
        out_rows.append(" | ".join(cells))
    return "\n".join(["(" + "; ".join(notes) + f"; 칸 {ncell}개)"] + out_rows)


# ------------------------------------------------------------------ PaddleOCR
def _to_list(v):
    if v is None:
        return None
    if hasattr(v, "tolist"):
        return v.tolist()
    return list(v)


def _poly_bbox(poly) -> tuple[float, float, float, float]:
    """네 점 [[x,y],...] 또는 [x0,y0,x1,y1] 을 (x0,y0,x1,y1) 로."""
    p = _to_list(poly)
    if p and isinstance(p[0], (list, tuple)):
        xs = [float(q[0]) for q in p]
        ys = [float(q[1]) for q in p]
        return min(xs), min(ys), max(xs), max(ys)
    return float(p[0]), float(p[1]), float(p[2]), float(p[3])


def paddle_items(res) -> list[tuple[str, float, tuple[float, float, float, float]]]:
    """PaddleOCR 결과(2.x/3.x)에서 (글, 점수, 상자) 목록을 뽑는다. 못 읽으면 빈 목록."""
    items = []
    seq = res if isinstance(res, (list, tuple)) else [res]
    for page in seq:
        if page is None:
            continue
        # 3.x: dict 꼴 결과 (rec_texts, rec_scores, rec_polys / rec_boxes)
        d = None
        if isinstance(page, dict):
            d = page
        else:
            for attr in ("json", "res"):
                v = getattr(page, attr, None)
                if callable(v):
                    continue
                if isinstance(v, dict):
                    d = v.get("res", v) if isinstance(v.get("res", None), dict) else v
                    break
            if d is None:
                try:
                    d = dict(page)
                except Exception:  # noqa: BLE001
                    d = None
        if d and "res" in d and isinstance(d["res"], dict):
            d = d["res"]
        if d and d.get("rec_texts") is not None:
            texts = _to_list(d["rec_texts"]) or []
            scores = _to_list(d.get("rec_scores")) or [0.0] * len(texts)
            boxes = d.get("rec_polys")
            if boxes is None:
                boxes = d.get("rec_boxes")
            if boxes is None:
                boxes = d.get("dt_polys")
            boxes = _to_list(boxes) or []
            for t, s, b in zip(texts, scores, boxes):
                items.append((str(t), float(s), _poly_bbox(b)))
            continue
        # 2.x: [[box, (text, score)], ...] (쪽마다 한 겹 더 감싸이기도 함)
        if isinstance(page, (list, tuple)):
            for it in page:
                try:
                    box, (t, s) = it[0], it[1]
                    items.append((str(t), float(s), _poly_bbox(box)))
                except Exception:  # noqa: BLE001
                    continue
    return items


def group_lines(items) -> list[list[tuple[str, tuple[float, float, float, float]]]]:
    """상자를 y 중심으로 줄 묶음: 줄 높이의 0.6 이내면 같은 줄. 줄은 위→아래, 안은 x 순."""
    its = sorted(items, key=lambda it: (it[2][1] + it[2][3]) / 2)
    lines: list[list] = []
    for t, s, b in its:
        cy, hh = (b[1] + b[3]) / 2, max(1.0, b[3] - b[1])
        for ln in lines:
            ref_cy = sum((x[2][1] + x[2][3]) / 2 for x in ln) / len(ln)
            ref_h = sum(max(1.0, x[2][3] - x[2][1]) for x in ln) / len(ln)
            if abs(cy - ref_cy) <= 0.6 * max(ref_h, hh):
                ln.append((t, s, b))
                break
        else:
            lines.append([(t, s, b)])
    return [[(t, b) for t, s, b in sorted(ln, key=lambda x: x[2][0])] for ln in lines]


_PADDLE = {}


def paddle_engine():
    if "ocr" in _PADDLE:
        return _PADDLE["ocr"], _PADDLE["ver"]
    try:
        import paddleocr
    except ImportError as e:
        raise ToolMissing("paddleocr 없음 (pip install paddlepaddle paddleocr)") from e
    ver = getattr(paddleocr, "__version__", "?")
    major = int(re.match(r"\d+", ver).group()) if re.match(r"\d+", ver) else 3
    if major >= 3:
        base = dict(lang="korean", use_doc_orientation_classify=False,
                    use_doc_unwarping=False, use_textline_orientation=False)
        # 실측(paddle 3.3.1 / paddleocr 3.7.0, CPU): enable_mkldnn 기본값에서는 oneDNN 오류(NotImplementedError),
        # 2배 확대 그림에 검출 한계를 두지 않으면 메모리 14GB 이상을 써 강제 종료됨 → 아래 두 설정을 먼저 시도
        try:
            ocr = paddleocr.PaddleOCR(**base, enable_mkldnn=False, text_det_limit_type="max", text_det_limit_side_len=1280)
        except TypeError:
            ocr = paddleocr.PaddleOCR(**base)
    else:
        ocr = paddleocr.PaddleOCR(lang="korean", use_angle_cls=False)
    _PADDLE.update(ocr=ocr, ver=ver)
    return ocr, ver


def run_paddle(src: Path, work: Path) -> str:
    from PIL import Image
    ocr, ver = paddle_engine()
    with Image.open(src) as im:
        im = im.convert("RGB")
        big = im.resize((im.width * 2, im.height * 2), Image.LANCZOS)
        p = work / f"{src.stem}_paddle.png"
        big.save(p)
    major = int(re.match(r"\d+", ver).group()) if re.match(r"\d+", ver) else 3
    res = ocr.predict(str(p)) if major >= 3 else ocr.ocr(str(p))
    items = paddle_items(res)
    if not items:
        return f"(paddleocr {ver} 결과 구조를 못 읽음)\ntype={type(res)}\n{repr(res)[:1500]}"
    lines = group_lines(items)
    return "\n".join(" | ".join(t for t, _ in ln) for ln in lines)


# ------------------------------------------------------------------- 요약
def tokens_of(text: str) -> list[str]:
    toks = []
    for raw in re.split(r"[\s|]+", text):
        t = raw.strip("()[]{}<>.,:;'\"원~")
        if t:
            toks.append(t)
    return toks


def stats(text: str) -> dict:
    toks = tokens_of(text)
    nums = [t for t in toks if NUMERIC.match(t)]
    good = [t for t in nums if OK_AMOUNT.match(t)]
    broken = [t for t in nums if "," not in t and len(t) >= 7]
    return {"chars": len(text), "nums": len(nums), "good": good, "broken": broken}


def run_variant(name: str, src: Path, work: Path, tessdir: str | None) -> str:
    if name == "tess-fast-s3-psm6":
        return run_tess_variant(src, work, 3, 6, None, False)
    if name == "tess-best-s3-psm6":
        return run_tess_variant(src, work, 3, 6, tessdir or "", False)
    if name == "tess-best-s4-psm6":
        return run_tess_variant(src, work, 4, 6, tessdir or "", True)
    if name == "tess-best-s4-psm4":
        return run_tess_variant(src, work, 4, 4, tessdir or "", True)
    if name == "tess-best-s4-psm11":
        return run_tess_variant(src, work, 4, 11, tessdir or "", True)
    if name == "tess-cells":
        return run_cells(src, work, tessdir)
    if name == "paddle":
        return run_paddle(src, work)
    raise ValueError(f"모르는 방식: {name}")


def compare_image(label: str, src: Path, variants: list[str], tessdir: str | None, work: Path, summary: list) -> None:
    for v in variants:
        t0 = time.monotonic()
        text, err = "", ""
        try:
            text = run_variant(v, src, work, tessdir)
        except Exception as e:  # noqa: BLE001
            err = f"{type(e).__name__}: {e}"[:300]
        dt = time.monotonic() - t0
        print(f"\n===== [{label}] {v}  ({dt:.1f}초) =====")
        if err:
            print(f"!! 오류 {err}")
        else:
            print(text[:TEXT_LIMIT] + (f"\n...(앞 {TEXT_LIMIT}자만, 전체 {len(text)}자)" if len(text) > TEXT_LIMIT else ""))
        summary.append((label, v, dt, err, stats(text) if not err else None))
        sys.stdout.flush()


def print_summary(summary: list) -> None:
    print("\n" + "=" * 20 + " 요약 " + "=" * 20)
    print(f"{'쪽':<6}{'방식':<20}{'초':>6}{'글자':>7}{'숫자':>6}{'쉼표맞음':>8}{'깨짐후보':>8}")
    for label, v, dt, err, st in summary:
        if err:
            print(f"{label:<6}{v:<20}{dt:>6.1f}  오류: {err[:80]}")
        else:
            print(f"{label:<6}{v:<20}{dt:>6.1f}{st['chars']:>7}{st['nums']:>6}{len(st['good']):>8}{len(st['broken']):>8}")
    print("\n--- 쉼표가 맞는 금액 꼴 토큰 (최대 30개) / 7자리 이상 쉼표 없는 숫자(깨진 금액 후보) ---")
    for label, v, dt, err, st in summary:
        if err or st is None:
            continue
        print(f"[{label}] {v}\n   맞음({len(st['good'])}): {st['good'][:30]}\n   깨짐({len(st['broken'])}): {st['broken'][:30]}")


# --------------------------------------------------------------------- 받기
def fetch_pages(nid: str, pages: list[int], work: Path) -> list[tuple[str, Path]]:
    """공고 색인에서 지정 쪽 그림만 받는다. (표시 이름, 파일) 목록."""
    notices = {n["id"]: n for n in json.loads(Path(esn.SRC).read_text(encoding="utf-8"))["notices"]}
    n = notices.get(nid)
    if n is None:
        raise SystemExit(f"공고 파일에 없는 id: {nid}")
    fi = esn.pick_file(n)
    if fi is None:
        raise SystemExit("미리보기 주소가 있는 첨부 없음")
    f = esn.Fetcher()
    r1 = f.get(fi["preview_url"], follow=True, read_any=True)
    q = urllib.parse.parse_qs(urllib.parse.urlparse(r1.final).query)
    fn, rs = (q.get("fn") or [""])[0], (q.get("rs") or [""])[0]
    if not fn or not rs:
        raise SystemExit("최종 주소에서 fn, rs 를 찾지 못함")
    rs_url = urllib.parse.urljoin(r1.final, rs if rs.endswith("/") else rs + "/")
    r2 = f.get(rs_url + fn + ".xml")
    if r2.status != 200 or r2.body is None:
        raise SystemExit(f"색인을 받지 못함(상태 {r2.status})")
    _, cnt, paths = esn.parse_index(esn.decode(r2))
    print(f"색인: 쪽 수 {cnt or len(paths)}, path_html {len(paths)}개")
    out = []
    for pg in pages:
        if not 1 <= pg <= len(paths):
            print(f"[{pg}쪽] 범위 밖 (1~{len(paths)})")
            continue
        ph = paths[pg - 1]
        ext = esn.ext_of(ph)
        if ext not in esn.IMG_EXT:
            print(f"[{pg}쪽] 그림이 아님: {ph}")
            continue
        url = urllib.parse.urljoin(rs_url, urllib.parse.quote(ph, safe="/%:@"))
        r = f.get(url, read_any=True, track=False)
        if r.status != 200 or r.body is None:
            print(f"[{pg}쪽] 받기 실패 상태={r.status} {r.error}")
            continue
        p = work / f"p{pg}{ext}"
        p.write_bytes(r.body)
        out.append((f"{pg}쪽", p))
    print(f"요청 {f.count}회")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", default="sh-313161")
    ap.add_argument("--pages", default="8,9,10")
    ap.add_argument("--variants", default=",".join(ALL_VARIANTS), help="쉼표 목록 (이름 또는 A~G)")
    ap.add_argument("--tessdata-dir", "--tessdata-best", dest="tessdata", default=None, help="tessdata_best 폴더 (kor, eng)")
    ap.add_argument("--local-image", default=None, help="사이트 요청 없이 이 그림만 모든 방식에 넣는다")
    args = ap.parse_args()

    variants = []
    for v in (x.strip() for x in args.variants.split(",") if x.strip()):
        v = SHORT.get(v.upper(), v) if len(v) == 1 else v
        if v not in ALL_VARIANTS:
            raise SystemExit(f"모르는 방식 {v!r}; 가능: {ALL_VARIANTS}")
        variants.append(v)

    summary: list = []
    with tempfile.TemporaryDirectory(prefix="ocrcmp_") as td:  # 끝나면 그림이 함께 지워진다
        work = Path(td)
        if args.local_image:
            imgs = [("local", Path(args.local_image))]
        else:
            pages = [int(x) for x in args.pages.split(",") if x.strip()]
            imgs = fetch_pages(args.id, pages, work)
        for label, p in imgs:
            compare_image(label, p, variants, args.tessdata, work, summary)
    print_summary(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
