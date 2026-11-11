"""SH 공고문 '미리보기 변환본'에서 글을 읽어 data/notice_text/<공고 id>.json 으로 남긴다 (소현리치랩).

SH 공고 첨부의 preview_url(htmlConverter.do)은 Synap Document Viewer 화면(doc.html?fn=..&rs=..)으로 넘어간다.
화면이 읽는 변환 파일(<rs><fn>.xml 색인과 쪽별 파일)을 받아 글을 뽑는다. 원본 PDF 는 받지 않는다.
색인(<index>)에는 file_type, pdf_cnt(쪽 수)와 쪽마다 path_html(rs 기준 상대 경로)이 들어 있다.
- path_html 이 그림(.png/.jpg/.jpeg/.gif)이면 PDF 를 쪽별 그림으로 바꾼 것이라 글이 없다.
  임시 폴더에 받아 글자 인식(OCR)한다. 그림은 끝나면 지우고 저장소에 남기지 않는다.
  · 기본 글(pages[].text): 4배 확대·회색조·선명화·자동 대비 후 tesseract psm 6. tessdata_best 가 있으면 그 모델로.
  · 표 쪽(금액 낱말·쉼표 맞는 금액 3개 이상·7자리 이상 쉼표 없는 숫자가 있는 쪽, 공고당 최대 8쪽)은 다시 읽는다.
    paddle(2배 확대)로 읽어 pages[].table_text 와 amounts 를, tesseract psm 11 로도 읽어 두 방식이 일치한
    금액만 pages[].amounts_checked 에 남긴다. paddle 이 없으면 psm 11 결과를 amounts 로 삼아 psm 6 과 맞춰 본다.
- path_html 이 글 형식(.htm/.html/.xml/.svg/.txt)이면 받아서 태그를 벗겨 글로 만든다.
- path_html 이 없으면 색인에서 파일 이름을 찾아 여러 주소를 시험한다.

- 대상 지정: python scripts/extract_sh_notice.py --ids sh-313161,sh-312903
- 자동:     python scripts/extract_sh_notice.py --auto [--max 3]
  아직 뽑지 않은 SH 모집공고를 공고일이 최근인 것부터 고른다.
- 진단:     --debug (색인 요약, 쪽별 상태·바이트·글자 수, 표 쪽의 table_text 전문과 금액, 방식별 시간, 합계)
- 글자 인식: --ocr-scale 4 (확대 배율), --psm 6 (tesseract 쪽 분할 방식), --tessdata-dir DIR (tessdata_best, 없으면
            환경변수 TESSDATA_BEST_DIR), --no-paddle (paddle 건너뛰기), --max-table-pages 8
- 시험:     --src 공고 파일, --out 출력 폴더

변환 파일 요청은 리다이렉트를 따라가지 않는다. 없는 파일이 302 로 응답하기 때문이다(없음으로 처리).
요청은 공고 1건당 80회, 요청 사이 1초, 쪽(파일) 5MB·최대 40쪽. 글 형식만 읽을 때는 표준 라이브러리만 쓴다.
글자 인식에는 Pillow 와 tesseract(kor+eng)가 필요하고, paddlepaddle·paddleocr 는 있으면 쓴다.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "public_housing.json"
OUT = ROOT / "data" / "notice_text"
KST = timezone(timedelta(hours=9))
UA = "sohyunrichlab-notice-collector/1.0 (+https://revi404.github.io/sohyunrichlab/)"
MAX_REQUESTS = 80          # 공고 1건당 요청 상한
DELAY = 1.0                # 요청 사이 쉬는 시간(초)
TIMEOUT = 30
MAX_FILE = 5 * 1024 * 1024
MAX_TOTAL = 20 * 1024 * 1024
MAX_PAGES = 40             # 한 공고에서 읽을 최대 쪽 수
OCR_SCALE = 4
OCR_PSM = 6
OCR_TIMEOUT = 240          # 쪽당 tesseract 제한 시간(초)
IMG_EXT = (".png", ".jpg", ".jpeg", ".gif")
TEXT_EXT = (".htm", ".html", ".xml", ".svg", ".txt")
OCR_NOTE = "글자 인식 결과라 표 안 숫자가 틀릴 수 있음. amounts_checked 는 두 인식 방식이 일치한 금액이며, 그 외 금액은 원문 확인 필요"
MAX_TABLE_PAGES = 8        # 공고 1건당 표 쪽 재인식 상한
PADDLE_SCALE = 2           # paddle 에 넣는 그림 확대 배율
TABLE_WORDS = ("보증금", "임대료", "분양가", "공급금액", "계약금", "중도금", "잔금", "관리비", "전세금", "소득")
TABLE_MIN_AMOUNTS = 3      # 쉼표 맞는 금액 꼴 토큰이 이만큼 이상이면 표 쪽
OK_AMOUNT = re.compile(r"^\d{1,3}(,\d{3})+$")
BIG_NUMBER = re.compile(r"^\d{7,}$")   # 쉼표가 빠진 7자리 이상 숫자(깨진 금액 후보)
DEBUG_LIMIT = 60000
MIN_CHARS = 200
NAME_RE = re.compile(r"[\w\-./%]+\.(?:xml|htm|html|svg|json|txt)\b", re.I)
TEXT_TYPES = ("xml", "html", "svg", "json", "text/")
BAD_FILE = ("양식", "서식", "신청서")


class Budget(Exception):
    """요청·용량 상한에 닿았다."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):  # 따라가지 않고 3xx 를 그대로 돌려받는다
        return None


class Resp:
    def __init__(self, status: int, ctype: str = "", body: bytes | None = None, size: int = 0, final: str = "", error: str = ""):
        self.status, self.ctype, self.body, self.size, self.final, self.error = status, ctype, body, size, final, error


class Fetcher:
    """요청 횟수·간격·용량을 관리하며 받는다."""

    def __init__(self) -> None:
        self.count = 0
        self.total = 0
        self.total_img = 0
        self.last = 0.0
        self.plain = urllib.request.build_opener(NoRedirect)
        self.follow = urllib.request.build_opener()

    def get(self, url: str, follow: bool = False, read_any: bool = False, track: bool = True) -> Resp:
        if self.count >= MAX_REQUESTS:
            raise Budget("요청 상한")
        if self.total >= MAX_TOTAL:
            raise Budget("용량 상한")
        wait = DELAY - (time.monotonic() - self.last)
        if self.count and wait > 0:
            time.sleep(wait)
        self.count += 1
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
        try:
            r = (self.follow if follow else self.plain).open(req, timeout=TIMEOUT)
        except urllib.error.HTTPError as e:  # 3xx(따라가지 않을 때)·4xx·5xx
            self.last = time.monotonic()
            return Resp(e.code, e.headers.get("Content-Type", "") or "", None, 0, url)
        except Exception as e:  # noqa: BLE001
            self.last = time.monotonic()
            return Resp(0, "", None, 0, url, f"{type(e).__name__} {e}")
        with r:
            ctype = (r.headers.get("Content-Type") or "").lower()
            final = r.geturl()
            textual = read_any or any(t in ctype for t in TEXT_TYPES) or ctype.split(";")[0].strip() in ("", "application/octet-stream")
            if not textual:  # 그림 등은 받지 않는다
                self.last = time.monotonic()
                return Resp(r.status, ctype, None, int(r.headers.get("Content-Length") or 0), final)
            body = r.read(MAX_FILE + 1)
        self.last = time.monotonic()
        if len(body) > MAX_FILE:
            return Resp(r.status, ctype, None, len(body), final, "5MB 초과")
        if track:  # 쪽 그림은 임시 폴더에서 바로 지우므로 합계 상한에 넣지 않는다(쪽당 5MB 만 막는다)
            self.total += len(body)
        else:
            self.total_img += len(body)
        return Resp(r.status, ctype, body, len(body), final)


class Dbg:
    """--debug 진단을 모아 두었다가 60,000자 이내로 출력한다."""

    def __init__(self, on: bool) -> None:
        self.on, self.lines = on, []

    def __call__(self, s: str = "") -> None:
        if self.on:
            self.lines.append(s)

    def flush(self) -> None:
        if self.on:
            out = "\n".join(self.lines)
            print(out[:DEBUG_LIMIT] + ("\n...(60,000자에서 자름)" if len(out) > DEBUG_LIMIT else ""))
            self.lines = []


class TextOf(HTMLParser):
    """태그를 벗기고 글만 모은다. script/style 안은 뺀다."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.skip:
            self.skip -= 1
        if tag in ("p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "table"):
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def decode(r: Resp) -> str:
    m = re.search(r"charset=([\w\-]+)", r.ctype)
    for enc in ([m.group(1)] if m else []) + ["utf-8", "cp949"]:
        try:
            return (r.body or b"").decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return (r.body or b"").decode("utf-8", "replace")


def tidy(s: str) -> str:
    s = s.replace("\xa0", " ")
    lines = [re.sub(r"[ \t\r\f\v]+", " ", ln).strip() for ln in s.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def text_of(r: Resp) -> str:
    """응답 본문에서 글만 뽑는다. 글 형식이 아니면 빈 문자열."""
    if r.body is None:
        return ""
    raw = decode(r)
    ctype = r.ctype
    if "json" in ctype or raw.lstrip()[:1] in "{[":
        try:
            strs: list[str] = []

            def walk(v):
                if isinstance(v, str):
                    strs.append(v)
                elif isinstance(v, dict):
                    for x in v.values():
                        walk(x)
                elif isinstance(v, list):
                    for x in v:
                        walk(x)

            walk(json.loads(raw))
            return tidy("\n".join(strs))
        except ValueError:
            pass
    if "html" in ctype or "xml" in ctype or "svg" in ctype or raw.lstrip()[:1] == "<":
        p = TextOf()
        try:
            p.feed(raw)
            p.close()
        except Exception:  # noqa: BLE001
            pass
        return tidy("".join(p.parts))
    return tidy(raw)


def pick_file(n: dict) -> dict | None:
    """preview_url 이 있는 첨부 가운데 공고문 하나를 고른다. pdf > hwp/hwpx > 그 외, 없으면 첫 파일."""
    files = [f for f in (n.get("detail") or {}).get("files", []) if f.get("preview_url")]
    if not files:
        return None

    def rank(f: dict) -> tuple[int, int]:
        name = (f.get("name") or "").lower()
        is_notice = "공고" in name and not any(w in name for w in BAD_FILE)
        ext = 0 if name.endswith(".pdf") else 1 if name.endswith((".hwp", ".hwpx")) else 2
        return (0 if is_notice else 1, ext)

    return min(files, key=rank)  # min 은 동순위에서 앞선 것을 쓴다


def collect_names(index_text: str) -> tuple[list[str], list[int]]:
    """색인에서 파일 이름처럼 보이는 문자열과 쪽 수로 보이는 숫자를 찾는다."""
    found: list[str] = []
    values = [index_text]
    counts: list[int] = []
    try:
        root = ET.fromstring(index_text.encode("utf-8") if not index_text.lstrip().startswith("<?xml") else index_text.encode("utf-8"))
        for el in root.iter():
            tag = el.tag.split("}")[-1]
            if el.text and el.text.strip():
                values.append(el.text)
                if re.search(r"page|count|total", tag, re.I) and el.text.strip().isdigit():
                    counts.append(int(el.text.strip()))
            for k, v in el.attrib.items():
                values.append(v)
                if re.search(r"page|count|total", k, re.I) and v.strip().isdigit():
                    counts.append(int(v.strip()))
    except (ET.ParseError, ValueError):
        pass
    for v in values:
        for m in NAME_RE.finditer(v):
            found.append(m.group(0))
    return list(dict.fromkeys(found)), [c for c in counts if 0 < c <= 2000]


def read_part(name: str, url: str, r: Resp, dbg: Dbg) -> tuple[dict | None, str]:
    txt = text_of(r)
    raw = decode(r) if r.body is not None else ""
    dbg(f"  [{r.status}] {url}\n    형식={r.ctype or '-'} 바이트={r.size} 글자={len(txt)}")
    if r.body is not None:
        dbg(f"    글 앞 300자: {txt[:300]!r}\n    원문 앞 300자: {raw[:300]!r}")
    return ({"name": name, "chars": len(txt), "text": txt} if txt else None), txt




class OcrError(Exception):
    """글자 인식 도구(Pillow·tesseract)가 없거나 쓸 수 없다."""


def parse_index(index_text: str) -> tuple[str, int, list[str]]:
    """색인에서 file_type, 쪽 수(pdf_cnt), path_html 목록(나온 순서)을 읽는다. 태그 이름이 pdf 가 아니어도 path_html 이면 모은다."""
    ftype, cnt, paths = "", 0, []
    try:
        root = ET.fromstring(index_text.encode("utf-8"))
    except (ET.ParseError, ValueError):
        return ftype, cnt, paths
    for el in root.iter():
        tag = el.tag.split("}")[-1].lower()
        val = (el.text or "").strip()
        if tag == "file_type" and val:
            ftype = val.lower()
        elif tag == "pdf_cnt" and val.isdigit():
            cnt = int(val)
        elif tag == "path_html" and val:
            paths.append(val)
    return ftype, cnt, paths


def ext_of(path: str) -> str:
    return Path(urllib.parse.urlparse(path).path).suffix.lower()


class OcrConf:
    """글자 인식 설정. tessdata_best 가 있으면 그 모델을 쓰고, 없으면 apt 기본 모델."""

    def __init__(self, tessdir: str | None = None, scale: int = OCR_SCALE, psm: int = OCR_PSM,
                 paddle: bool = True, max_table: int = MAX_TABLE_PAGES) -> None:
        d = tessdir or os.environ.get("TESSDATA_BEST_DIR") or ""
        self.tessdir = d if d and (Path(d) / "kor.traineddata").is_file() else None
        self.tessdir_bad = d if d and not self.tessdir else ""   # 지정했는데 kor 가 없는 폴더
        self.lang = "kor+eng" if not self.tessdir or (Path(self.tessdir) / "eng.traineddata").is_file() else "kor"
        self.scale, self.psm, self.paddle, self.max_table = scale, psm, paddle, max_table

    @property
    def text_label(self) -> str:
        return f"tess-{'best' if self.tessdir else 'fast'}-s{self.scale}-psm{self.psm}"


def prep_image(img_path: Path, scale: int) -> Path:
    """확대(LANCZOS)·회색조 → 선명화 1회 → 자동 대비. 확대한 그림 파일을 돌려준다(부른 쪽에서 지운다)."""
    try:
        from PIL import Image, ImageFilter, ImageOps  # 글 형식만 읽을 때는 필요 없으므로 여기서 불러온다
    except ImportError as e:
        raise OcrError("Pillow 가 없어 글자 인식을 못 함 (pip install pillow)") from e
    with Image.open(img_path) as im:
        im = im.convert("L")
        im = im.resize((im.width * scale, im.height * scale), Image.LANCZOS)
        im = ImageOps.autocontrast(im.filter(ImageFilter.SHARPEN))
        big = img_path.with_name(img_path.stem + f"_ocr{scale}.png")
        im.save(big)
    return big


def ocr_image(img_path: Path, conf: OcrConf, psm: int | None = None) -> str:
    """그림 한 장을 tesseract 로 읽는다(선명화·자동 대비 전처리 포함). 확대한 임시 파일은 바로 지운다."""
    psm = conf.psm if psm is None else psm
    exe = shutil.which("tesseract")
    if not exe:
        raise OcrError("tesseract 가 없어 글자 인식을 못 함 (apt-get install tesseract-ocr tesseract-ocr-kor)")
    big = prep_image(img_path, conf.scale)
    cmd = [exe, str(big), "stdout", "-l", conf.lang, "--psm", str(psm)]
    if conf.tessdir:
        cmd[1:1] = ["--tessdata-dir", conf.tessdir]
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=OCR_TIMEOUT)
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"tesseract {OCR_TIMEOUT}초 초과") from e
    finally:
        big.unlink(missing_ok=True)
    if p.returncode != 0:
        err = p.stderr.decode("utf-8", "replace").strip()
        if "language" in err.lower() or "traineddata" in err.lower():
            raise OcrError(f"tesseract 한글 데이터(kor)가 없음: {err[:200]}")
        raise RuntimeError(f"tesseract 오류 {p.returncode}: {err[:200]}")
    return tidy(p.stdout.decode("utf-8", "replace"))


# ------------------------------------------------------------ 금액 토큰·표 쪽 판정
def tokens_of(text: str) -> list[str]:
    toks = []
    for raw in re.split(r"[\s|]+", text):
        t = raw.strip("()[]{}<>.,:;'\"원~")
        if t:
            toks.append(t)
    return toks


def amount_tokens(text: str) -> list[str]:
    """쉼표가 맞는 금액 꼴 토큰(예: 190,000,000)을 나온 순서대로, 중복도 그대로."""
    return [t for t in tokens_of(text) if OK_AMOUNT.match(t)]


def is_table_page(text: str) -> bool:
    """금액 낱말이 있거나, 쉼표 맞는 금액 꼴이 3개 이상이거나, 7자리 이상 쉼표 없는 숫자가 있으면 표 쪽."""
    if has_amount_word(text):
        return True
    toks = tokens_of(text)
    return sum(1 for t in toks if OK_AMOUNT.match(t)) >= TABLE_MIN_AMOUNTS or any(BIG_NUMBER.match(t) for t in toks)


def has_amount_word(text: str) -> bool:
    flat = re.sub(r"\s+", "", text)  # 글자 인식이 낱말 안에 띄어쓰기를 넣어도 찾는다
    return any(w in flat for w in TABLE_WORDS)


def checked_amounts(amounts: list[str], others: list[list[str]]) -> list[str]:
    """amounts 중 다른 방식 결과(others 중 하나라도)에도 있는 것. 순서 유지, 중복은 양쪽 개수의 최솟값만큼."""
    other: Counter = Counter()
    for toks in others:
        other |= Counter(toks)   # 토큰별 최대 개수
    used: Counter = Counter()
    out = []
    for t in amounts:
        if used[t] < other[t]:
            used[t] += 1
            out.append(t)
    return out


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


_PADDLE: dict = {}


def paddle_engine():
    """paddle 객체를 한 번만 만들어 재사용한다. 못 만들면 사유를 기억해 두고 다시 시도하지 않는다."""
    if "err" in _PADDLE:
        raise OcrError(_PADDLE["err"])
    if "ocr" in _PADDLE:
        return _PADDLE["ocr"], _PADDLE["ver"]
    try:
        import paddleocr
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
    except Exception as e:  # noqa: BLE001  import 실패·모델 준비 실패 모두
        _PADDLE["err"] = f"paddle 을 쓸 수 없음: {type(e).__name__} {e}"[:300]
        raise OcrError(_PADDLE["err"]) from e
    _PADDLE.update(ocr=ocr, ver=ver)
    return ocr, ver


def ocr_paddle(img_path: Path) -> str:
    """그림을 2배 확대해 paddle 로 읽고, 줄 묶음 결과를 줄마다 ' | ' 로 칸을 이어 돌려준다."""
    from PIL import Image
    ocr, ver = paddle_engine()
    with Image.open(img_path) as im:
        im = im.convert("RGB")
        big = im.resize((im.width * PADDLE_SCALE, im.height * PADDLE_SCALE), Image.LANCZOS)
        p = img_path.with_name(img_path.stem + "_paddle.png")
        big.save(p)
    try:
        major = int(re.match(r"\d+", ver).group()) if re.match(r"\d+", ver) else 3
        res = ocr.predict(str(p)) if major >= 3 else ocr.ocr(str(p))
    finally:
        p.unlink(missing_ok=True)
    items = paddle_items(res)
    if not items:
        raise RuntimeError(f"paddleocr {ver} 결과가 비었거나 구조를 못 읽음 ({type(res).__name__})")
    return "\n".join(" | ".join(t for t, _ in ln) for ln in group_lines(items))


def reread_table(rec: dict, conf: OcrConf, dbg: Dbg) -> None:
    """표 쪽 하나를 다시 읽어 rec 에 table_text·amounts·amounts_checked·amounts_method 를 채운다."""
    src, base = rec["img"], rec["text"]
    rec["times"] = {"psm%d" % conf.psm: rec.get("t_base", 0.0)}
    t11 = None
    t0 = time.monotonic()
    try:
        t11 = ocr_image(src, conf, 11)
    except Exception as e:  # noqa: BLE001
        dbg(f"    tess psm11 실패: {type(e).__name__} {e}")
    rec["times"]["psm11"] = time.monotonic() - t0
    rec["psm11_text"] = t11
    pad = None
    if conf.paddle:
        t0 = time.monotonic()
        try:
            pad = ocr_paddle(src)
        except Exception as e:  # noqa: BLE001  paddle 이 없거나 실패하면 table_text 없이 계속
            dbg(f"    paddle 실패: {type(e).__name__} {e}")
        rec["times"]["paddle"] = time.monotonic() - t0
    psm_n = f"psm{conf.psm}"
    if pad is not None:
        rec["table_text"] = pad
        amounts = amount_tokens(pad)
        others = ([amount_tokens(t11)] if t11 is not None else []) + [amount_tokens(base)]
        method = "paddle+tess-psm11/" + psm_n if t11 is not None else "paddle+tess-" + psm_n
    elif t11 is not None:
        amounts = amount_tokens(t11)
        others = [amount_tokens(base)]
        method = f"tess-psm11+tess-{psm_n}"
    else:
        return
    rec["amounts"] = amounts
    rec["amounts_checked"] = checked_amounts(amounts, others)
    rec["amounts_method"] = method


def extract_legacy(f: Fetcher, rs_url: str, fn: str, index_url: str, r2: Resp, index_text: str, dbg: Dbg) -> list[str]:
    """색인에 path_html 이 없을 때: 색인에서 이름을 찾아 여러 주소를 시험한다. 쪽(글) 목록을 돌려준다."""
    names, counts = collect_names(index_text)
    names = [x for x in names if x != fn + ".xml"]
    dbg(f"(3) 찾은 이름 {len(names)}개: {names}\n    쪽 수 후보: {counts}")
    parts: list[dict] = []
    idx_txt = text_of(r2)
    if idx_txt:
        parts.append({"name": fn + ".xml", "chars": len(idx_txt), "text": idx_txt})
    done = {index_url}

    def bases() -> list[str]:
        return [rs_url, rs_url + fn + "/", rs_url + fn + ".files/", rs_url + fn + "_files/"]

    pref: int | None = None  # 성공한 기준 위치를 먼저 시험해 요청을 아낀다
    try:
        for name in names:
            order = list(range(4))
            if pref is not None:
                order.remove(pref)
                order.insert(0, pref)
            for i in order:
                url = urllib.parse.urljoin(bases()[i], name)
                if url in done:
                    continue
                done.add(url)
                r = f.get(url)
                part, _ = read_part(name, url, r, dbg)
                if r.status == 200:
                    if part:
                        parts.append(part)
                    pref = i
                    break

        # 쪽 수가 보이면 흔한 쪽 파일 이름 규칙을 1쪽만 시험하고, 되는 규칙으로 전 쪽을 읽는다
        if counts:
            total = max(counts)
            rules = [fn + ".files/{}.xml", fn + ".files/page{}.xml", fn + "_{}.xml", fn + ".files/{}.htm", fn + ".files/{}.svg"]
            dbg(f"쪽 규칙 시험(쪽 수 {total})")
            for rule in rules:
                url = urllib.parse.urljoin(rs_url, rule.format(1))
                if url in done:
                    continue
                done.add(url)
                r = f.get(url)
                part, _ = read_part(rule.format(1), url, r, dbg)
                if r.status != 200:
                    continue
                if part:
                    parts.append(part)
                dbg(f"  → 규칙 채택: {rule}")
                for p in range(2, total + 1):
                    url = urllib.parse.urljoin(rs_url, rule.format(p))
                    if url in done:
                        continue
                    done.add(url)
                    r = f.get(url)
                    part, _ = read_part(rule.format(p), url, r, dbg)
                    if r.status != 200:
                        break
                    if part:
                        parts.append(part)
                break
    except Budget as e:
        dbg(f"!! {e} 에 닿아 중단")
    return [p["text"] for p in parts]


def show_page(dbg: Dbg, rec: dict) -> None:
    """--debug: 표 쪽이면 table_text(없으면 psm11 글) 전문 2500자까지와 금액, 방식별 시간. 아니면 글 앞 300자."""
    i, text = rec["i"], rec["text"]
    if not rec.get("table"):
        dbg(f"    표 쪽: 아님\n    글 앞 300자: {text[:300]!r}")
        return
    if "amounts" not in rec:
        why = "상한 초과로 재인식 안 함" if not rec.get("reread") else "재인식 결과 없음"
        dbg(f"    표 쪽: 예 ({why})\n    글 앞 300자: {text[:300]!r}")
        return
    body, label = (rec["table_text"], "table_text(paddle)") if "table_text" in rec else (rec.get("psm11_text") or "", "psm11 글(table_text 없음)")
    times = " ".join(f"{k}={v:.1f}초" for k, v in rec["times"].items())
    dbg(f"    표 쪽: 예  방식별 시간: {times}\n    --- {i}쪽 {label} ---\n{body[:2500]}"
        + ("\n    ...(2500자에서 자름)" if len(body) > 2500 else ""))
    dbg(f"    amounts({len(rec['amounts'])}): {rec['amounts']}\n    amounts_checked({len(rec['amounts_checked'])}): {rec['amounts_checked']}\n"
        f"    amounts_method: {rec['amounts_method']}")


def extract_one(n: dict, f_info: dict, dbg: Dbg, conf: OcrConf | None = None) -> tuple[dict | None, str]:
    """공고 하나를 읽는다. (결과, 실패 사유)를 돌려준다."""
    conf = conf or OcrConf()
    t0 = time.monotonic()
    f = Fetcher()
    dbg(f"=== {n['id']} {n['title']}\n파일: {f_info['name']}\npreview_url: {f_info['preview_url']}")
    dbg(f"글자 인식: {conf.text_label} (tessdata_best={conf.tessdir or '없음, 기본 모델'}) paddle={'사용' if conf.paddle else '끔'} 표 쪽 상한={conf.max_table}")
    texts: list[str] = []
    recs: list[dict] = []      # 쪽 그림 글자 인식 기록 (표 쪽 재인식 결과를 함께 담는다)
    ocr, total_pages = False, 0
    try:
        # (1) 미리보기 주소를 따라가 doc.html 의 최종 주소를 얻는다
        r1 = f.get(f_info["preview_url"], follow=True, read_any=True)
        dbg(f"(1) 최종 주소: {r1.final} [{r1.status}] 형식={r1.ctype} {r1.size}B {r1.error}")
        q = urllib.parse.parse_qs(urllib.parse.urlparse(r1.final).query)
        fn, rs = (q.get("fn") or [""])[0], (q.get("rs") or [""])[0]
        dbg(f"fn={fn!r}\nrs={rs!r}")
        if not fn or not rs:
            return None, "최종 주소에서 fn, rs 를 찾지 못함"
        rs_url = urllib.parse.urljoin(r1.final, rs if rs.endswith("/") else rs + "/")

        # (2) 색인
        index_url = rs_url + fn + ".xml"
        r2 = f.get(index_url)
        dbg(f"(2) 색인: {index_url}\n    상태={r2.status} 형식={r2.ctype or '-'} 바이트={r2.size} {r2.error}")
        if r2.status != 200 or r2.body is None:
            return None, f"색인을 받지 못함(상태 {r2.status})"
        index_text = decode(r2)

        # (3) 색인 읽기: file_type, 쪽 수, path_html 목록
        ftype, cnt, paths = parse_index(index_text)
        total_pages = cnt or len(paths)
        dbg(f"(3) 색인 요약: file_type={ftype or '-'} 쪽 수={total_pages} (pdf_cnt={cnt}, path_html {len(paths)}개) 첫 path_html={paths[0] if paths else '-'}")
        if not paths:
            dbg("    path_html 이 없어 이름 찾기 방식으로 넘어감")
            dbg(f"    색인 앞 4000자:\n{index_text[:4000]}")
            texts = extract_legacy(f, rs_url, fn, index_url, r2, index_text, dbg)
            total_pages = len(texts)
            for i, t in enumerate(texts, 1):
                recs.append({"i": i, "text": t})
                dbg(f"  [{i}쪽] 글자 수={len(t)}\n    글 앞 300자: {t[:300]!r}")
        else:
            if len(paths) > MAX_PAGES:
                dbg(f"    쪽이 {len(paths)}개라 앞 {MAX_PAGES}쪽만 읽음")
            tmp = tempfile.TemporaryDirectory(prefix="shnotice_")  # 끝나면 그림이 함께 지워진다
            with tmp:
                # (4) 쪽마다 받아 기본 글을 읽는다. 표 쪽 재인식을 위해 원본 그림은 이 블록이 끝날 때까지 둔다
                budget_hit = ""
                try:
                    for i, ph in enumerate(paths[:MAX_PAGES], 1):
                        url = urllib.parse.urljoin(rs_url, urllib.parse.quote(ph, safe="/%:@"))
                        ext = ext_of(ph)
                        is_img = ext in IMG_EXT
                        r = f.get(url, read_any=True, track=not is_img)
                        dbg(f"  [{i}쪽] [{r.status}] {url}\n    형식={r.ctype or '-'} 바이트={r.size} {r.error}")
                        txt = ""
                        rec: dict = {"i": i}
                        if r.status == 200 and r.body is not None:
                            if is_img:
                                ocr = True
                                img = Path(tmp.name) / f"p{i}{ext}"
                                img.write_bytes(r.body)
                                rec["img"] = img
                                t1 = time.monotonic()
                                try:
                                    txt = ocr_image(img, conf)
                                except OcrError:
                                    raise
                                except Exception as e:  # noqa: BLE001  한 쪽 실패는 빈 글로 두고 계속
                                    dbg(f"    글자 인식 실패: {type(e).__name__} {e}")
                                rec["t_base"] = time.monotonic() - t1
                                rec["table"] = is_table_page(txt)
                                if not rec["table"]:  # 표 쪽이 아니면 그림을 바로 지운다
                                    img.unlink(missing_ok=True)
                            elif ext in TEXT_EXT or not is_img:
                                txt = text_of(r)
                        rec["text"] = txt
                        dbg(f"    글자 수={len(txt)}")
                        texts.append(txt)
                        recs.append(rec)
                except Budget as e:
                    budget_hit = str(e)
                    dbg(f"!! {e} 에 닿아 중단")

                # (5) 표 쪽 재인식: 공고당 상한, 넘으면 금액 낱말이 있는 쪽 먼저
                cands = [r_ for r_ in recs if r_.get("table")]
                if len(cands) > conf.max_table:
                    cands.sort(key=lambda r_: (0 if has_amount_word(r_["text"]) else 1, r_["i"]))
                    dbg(f"표 쪽 {len(cands)}개 > 상한 {conf.max_table}: 금액 낱말이 있는 쪽 먼저 {conf.max_table}쪽만 재인식")
                    cands = cands[:conf.max_table]
                for r_ in sorted(cands, key=lambda r_: r_["i"]):
                    r_["reread"] = True
                    dbg(f"  [{r_['i']}쪽] 표 쪽 재인식")
                    reread_table(r_, conf, dbg)
                    for x in Path(tmp.name).glob(f"p{r_['i']}*"):
                        x.unlink(missing_ok=True)
                if budget_hit and not any(texts):
                    return None, f"{budget_hit}에 닿음, 읽은 글 없음"
            for rec in recs:
                dbg(f"  [{rec['i']}쪽 결과] 글자 수={len(rec['text'])}")
                show_page(dbg, rec)
    except OcrError as e:
        return None, f"글자 인식 도구 오류: {e}"
    except Budget as e:
        dbg(f"!! {e} 에 닿아 중단")
        if not any(texts):
            return None, f"{e}에 닿음, 읽은 글 없음"
    except Exception as e:  # noqa: BLE001
        return None, f"{type(e).__name__} {e}"

    pages = []
    for rec in recs:
        pg = {"page": rec["i"], "text": rec["text"]}
        if "amounts" in rec:
            if "table_text" in rec:
                pg["table_text"] = rec["table_text"]
            pg["amounts"] = rec["amounts"]
            pg["amounts_checked"] = rec["amounts_checked"]
            pg["amounts_method"] = rec["amounts_method"]
        pages.append(pg)
    chars = sum(len(t) for t in texts)
    ok = chars >= MIN_CHARS * min(total_pages or len(texts), 3)
    n_table = sum(1 for r_ in recs if r_.get("table"))
    n_reread = sum(1 for r_ in recs if "amounts" in r_)
    dbg(f"합계: 요청 {f.count}회, 받은 {f.total + f.total_img:,}바이트, 읽은 쪽 {len(pages)}/{total_pages}, 글자 {chars:,}자, "
        f"표 쪽 {n_table}개(재인식 {n_reread}개), 총 걸린 시간 {time.monotonic() - t0:.1f}초")
    result = {"id": n["id"], "org": n["org"], "title": n["title"], "notice_date": n.get("notice_date"), "url": n["url"],
              "file": {"name": f_info["name"], "preview_url": f_info["preview_url"]},
              "extracted": datetime.now(KST).strftime("%Y-%m-%d %H:%M"),
              "engine": "synap-preview-ocr" if ocr else "synap-preview", "ocr": ocr}
    if ocr:
        tables = ("paddle" if any("table_text" in r_ for r_ in recs)
                  else "tess-psm11" if n_reread else None)
        result["ocr_detail"] = {"text": conf.text_label, "tables": tables}
    result.update({"total_pages": total_pages, "text_ok": ok, "pages": pages})
    if ocr:
        result["note"] = OCR_NOTE
    return result, ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", default="", help="공고 id (쉼표 구분)")
    ap.add_argument("--auto", action="store_true")
    ap.add_argument("--max", type=int, default=3, help="--auto 에서 한 번에 뽑을 공고 수")
    ap.add_argument("--force", action="store_true", help="이미 뽑은 공고도 다시 뽑기")
    ap.add_argument("--debug", action="store_true", help="진단 출력(항상 종료 코드 0)")
    ap.add_argument("--ocr-scale", type=int, default=OCR_SCALE, help="글자 인식 전 그림 확대 배율 (기본 4)")
    ap.add_argument("--psm", type=int, default=OCR_PSM, help="tesseract 쪽 분할 방식 (기본 6)")
    ap.add_argument("--tessdata-dir", default="", help="tessdata_best 폴더(kor.traineddata). 없으면 환경변수 TESSDATA_BEST_DIR, 그것도 없으면 기본 모델")
    ap.add_argument("--no-paddle", action="store_true", help="paddle 을 쓰지 않고 tesseract 로만 읽기")
    ap.add_argument("--max-table-pages", type=int, default=MAX_TABLE_PAGES, help="공고 1건당 표 쪽 재인식 상한 (기본 8)")
    ap.add_argument("--src", default=str(SRC), help="공고 파일 (기본 data/public_housing.json)")
    ap.add_argument("--out", default=str(OUT), help="출력 폴더 (기본 data/notice_text)")
    args = ap.parse_args()
    out = Path(args.out)
    conf = OcrConf(args.tessdata_dir, args.ocr_scale, args.psm, not args.no_paddle, args.max_table_pages)
    if conf.tessdir_bad:
        print(f"tessdata_best 폴더에 kor.traineddata 가 없어 기본 모델을 씀: {conf.tessdir_bad}", file=sys.stderr)
    notices = {n["id"]: n for n in json.loads(Path(args.src).read_text(encoding="utf-8"))["notices"]}

    ids = [i.strip() for i in args.ids.split(",") if i.strip()]
    if args.auto:
        auto = [n for n in notices.values()
                if n.get("src") == "sh" and n.get("kind") == "모집공고" and pick_file(n)
                and not (out / f"{n['id']}.json").exists()]
        auto.sort(key=lambda n: n.get("notice_date") or "", reverse=True)
        ids += [n["id"] for n in auto[: args.max]]
    if not ids:
        print("뽑을 공고 없음")
        return 0

    out.mkdir(parents=True, exist_ok=True)
    ids = list(dict.fromkeys(ids))
    failed = 0
    for nid in ids:
        n = notices.get(nid)
        target = out / f"{nid}.json"
        if n is None:
            print(f"[{nid}] 공고 파일에 없는 id", file=sys.stderr)
            failed += 1
            continue
        if target.exists() and not args.force:
            print(f"[{nid}] 이미 있음")
            continue
        f_info = pick_file(n)
        if f_info is None:
            print(f"[{nid}] 미리보기 주소가 있는 첨부 없음", file=sys.stderr)
            failed += 1
            continue
        dbg = Dbg(args.debug)
        try:
            result, why = extract_one(n, f_info, dbg, conf)
        finally:
            dbg.flush()
        if result is None:
            print(f"[{nid}] 실패: {why}", file=sys.stderr)
            failed += 1
            continue
        chars = sum(len(p["text"]) for p in result["pages"])
        if not result["text_ok"]:
            print(f"[{nid}] 글자 {chars}자뿐이라 저장하지 않음(글 뽑기 실패)", file=sys.stderr)
            failed += 1
            continue
        target.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"[{nid}] {len(result['pages'])}쪽, 글자 {chars:,}자 → {target}")
    if args.debug:
        return 0
    return 1 if failed and failed == len(ids) else 0


if __name__ == "__main__":
    sys.exit(main())
