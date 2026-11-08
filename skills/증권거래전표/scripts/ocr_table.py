"""스캔·사진으로 된 거래내역서 표를 OCR 로 읽어 행 목록으로 바꾼다.

순서
1. 쪽 이미지: PDF 는 pdftoppm 300dpi, 이미지 파일(png·jpg·tif·webp)은 그대로.
2. 기울기 보정: 가로 칸 선의 각도 중앙값으로 돌린다.
3. 칸 찾기: 가로·세로 칸 선을 모폴로지로 뽑아 칸 상자를 만든다. 칸 선이 없으면 글자 줄을 묶어 열을 나눈다.
4. 글자 읽기(엔진 선택)
   - rapid: RapidOCR(PaddleOCR PP-OCRv5 한국어 인식 모델, onnxruntime CPU). 쪽 전체를 한 번 읽고 글자 상자를 칸에 담는다.
   - tesseract: Tesseract 5 kor+eng. 칸마다 따로 읽고, 숫자로 보이면 숫자 전용으로 한 번 더 읽는다.
   - auto: rapid 가 있으면 rapid 로 읽고, 숫자 칸에서 확신도가 낮으면 tesseract 숫자 판독과 견줘 더 그럴듯한 쪽을 쓴다.
5. 확신도가 낮은 칸은 의심 칸으로 돌려준다. run.py 가 확인사항에 올리고 잔액 대사가 최종 판정을 한다.

OCR 결과는 언제나 의심값이다. 잔액 칸(현금잔액·외화예수금·잔고수량)이 있는 표만 OCR 로 전표를 만든다.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

IMG_EXT = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp", ".gif"}
NUM_RE = re.compile(r"^[\-\(]?[0-9][0-9,]*(\.[0-9]+)?\)?$")


@dataclass
class OcrCell:
    row: int
    col: int
    text: str
    conf: float
    engine: str


@dataclass
class OcrResult:
    rows: list
    cells: list = field(default_factory=list)
    suspects: list = field(default_factory=list)   # [(쪽, 행, 열, 글, 확신도)]
    pages: int = 0
    engine: str = ""
    angle: list = field(default_factory=list)
    grid: list = field(default_factory=list)       # 쪽마다 '칸선' 또는 '글자줄'
    text_px: list = field(default_factory=list)    # 쪽마다 글자 높이(px)
    quality: list = field(default_factory=list)    # 품질 경고
    src_ppi: dict = field(default_factory=dict)    # PDF 쪽별 내장 이미지 ppi


# ---------------------------------------------------------------- 이미지

def _imread(p: Path):
    import cv2
    data = np.fromfile(str(p), np.uint8)
    im = cv2.imdecode(data, cv2.IMREAD_GRAYSCALE)
    if im is None:   # gif·webp 등
        from PIL import Image
        im = np.array(Image.open(p).convert("L"))
    return im


def pdf_image_ppi(path: Path):
    """쪽마다 큰 내장 이미지의 실제 해상도(ppi). 스캔·캡처를 PDF 로 감싼 경우 300dpi 로 렌더링해도
    원본 해상도는 그대로라, 품질 판정은 이 값으로 한다. {쪽: 최소 ppi}"""
    exe = shutil.which("pdfimages")
    if not exe:
        return {}
    r = subprocess.run([exe, "-list", str(path)], capture_output=True, text=True, errors="replace")
    out = {}
    for line in r.stdout.splitlines()[2:]:
        f = line.split()
        if len(f) < 14 or f[2] != "image":
            continue
        try:
            pg, w, h, xp = int(f[0]), int(f[3]), int(f[4]), int(f[12])
        except ValueError:
            continue
        if w * h < 200 * 150:          # 아이콘·로고는 뺀다
            continue
        out[pg] = min(out.get(pg, 10**6), xp)
    return out


def load_pages(path: Path, dpi: int = 300):
    if path.suffix.lower() in IMG_EXT:
        return [_imread(path)]
    exe = shutil.which("pdftoppm")
    if not exe:
        raise RuntimeError("pdftoppm(poppler)이 없다")
    with tempfile.TemporaryDirectory() as td:
        subprocess.run([exe, "-r", str(dpi), "-png", str(path), str(Path(td) / "p")], check=True)
        return [_imread(p) for p in sorted(Path(td).glob("p-*.png"))]


def upscale_small(gray, min_h=1600, min_w=2400):
    """작은 화면 캡처(650~1,600px)는 글자 높이가 4~10px 이라 인식 모델이 못 읽는다. 폭 2,400px 까지 키운다(최대 4배)."""
    import cv2
    h, w = gray.shape
    f = max(min_h / h, min_w / w, 1.0)
    f = min(f, 4.0)
    if f > 1.01:
        gray = cv2.resize(gray, None, fx=f, fy=f, interpolation=cv2.INTER_CUBIC)
    return gray


def deskew(gray):
    import cv2
    bw = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 31, 15)
    w = gray.shape[1]
    hor = cv2.morphologyEx(bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (max(40, w // 30), 1)))
    lines = cv2.HoughLinesP(hor, 1, np.pi / 1800, threshold=200, minLineLength=w // 8, maxLineGap=20)
    if lines is None:
        # 칸 선이 짧게 끊겨 있으면 더 느슨하게
        lines = cv2.HoughLinesP(bw, 1, np.pi / 1800, threshold=300, minLineLength=w // 5, maxLineGap=10)
    if lines is None:
        return gray, 0.0
    ang = []
    for x1, y1, x2, y2 in np.asarray(lines).reshape(-1, 4):
        a = np.degrees(np.arctan2(y2 - y1, x2 - x1))
        if abs(a) < 10:
            ang.append(a)
    if not ang:
        return gray, 0.0
    a = float(np.median(ang))
    if abs(a) < 0.15:
        return gray, 0.0
    h = gray.shape[0]
    M = cv2.getRotationMatrix2D((w / 2, h / 2), a, 1.0)
    return cv2.warpAffine(gray, M, (w, h), flags=cv2.INTER_CUBIC, borderValue=255), a


def noise_level(gray):
    """잡음 크기: 원본과 3x3 중앙값 필터의 차이를 MAD 로 잰다(밝기 포화에 영향받지 않게)."""
    import cv2
    d = gray.astype(np.int16) - cv2.medianBlur(gray, 3).astype(np.int16)
    return float(np.median(np.abs(d - np.median(d))) * 1.4826)


def text_height(gray):
    """글자 높이(픽셀) 중앙값. 글자를 가로로 이어 붙인 덩어리(낱말)의 높이로 잰다. 14 미만이면 숫자 판독을 믿기 어렵다."""
    import cv2
    bw = cv2.threshold(cv2.medianBlur(gray, 3), 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    w = gray.shape[1]
    hor = cv2.morphologyEx(bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (max(40, w // 25), 1)))
    ver = cv2.morphologyEx(bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(20, gray.shape[0] // 60))))
    bw[(hor > 0) | (ver > 0)] = 0
    words = cv2.dilate(bw, cv2.getStructuringElement(cv2.MORPH_RECT, (9, 3)))
    n, _, st, _ = cv2.connectedComponentsWithStats(words, 8)
    hs = [st[i, 3] - 2 for i in range(1, n) if 5 <= st[i, 3] <= 120 and st[i, 2] >= st[i, 3]]
    return float(np.median(hs)) if hs else 0.0


def denoise(gray):
    import cv2
    n = noise_level(gray)
    if n > 6:
        gray = cv2.fastNlMeansDenoising(gray, None, h=min(30, n * 1.4), templateWindowSize=7, searchWindowSize=21)
    return gray, n


def flatten(gray):
    """밝기 얼룩(휴대폰 촬영) 보정: 배경을 크게 흐려 나눈다."""
    import cv2
    bg = cv2.medianBlur(gray, 51)
    out = cv2.divide(gray, bg, scale=255)
    return out


# ---------------------------------------------------------------- 칸 찾기

def _cluster(pos, gap=6):
    out = []
    for p in pos:
        if out and p - out[-1][-1] <= gap:
            out[-1].append(p)
        else:
            out.append([p])
    return [int(np.mean(c)) for c in out]


def line_masks(gray, text_h=0):
    """칸선 마스크. 글자 획을 선으로 지우지 않게 최소 길이를 글자 높이의 2.5배(세로)·8배(가로) 이상으로 잡는다."""
    import cv2
    bw = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 31, 15)
    h, w = bw.shape
    vk = max(h // 40, int(text_h * 2.5), 20)
    hk = max(w // 25, int(text_h * 8), 40)
    hor = cv2.morphologyEx(bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (hk, 1)))
    ver = cv2.morphologyEx(bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, vk)))
    # 선 두께만큼 넓혀 지운다
    hor = cv2.dilate(hor, np.ones((3, 1), np.uint8))
    ver = cv2.dilate(ver, np.ones((1, 3), np.uint8))
    return hor, ver


def find_grid(gray):
    import cv2
    bw = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 31, 15)
    h, w = bw.shape
    hor = cv2.morphologyEx(bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (max(40, w // 25), 1)))
    ver = cv2.morphologyEx(bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(20, h // 60))))
    rs = hor.sum(axis=1) / 255
    if rs.max() < w * 0.2:
        return None
    ys = _cluster([i for i, v in enumerate(rs) if v > rs.max() * 0.5])
    if len(ys) < 3:
        return None
    # 세로선 검출 길이는 줄 높이의 70%: 한 줄 높이만큼만 있는 칸막이(미래에셋 거래수량|단가)를 놓치지 않으면서
    # 글자 획(줄 높이의 절반 안팎)은 선으로 잡지 않는다
    rh = float(np.median(np.diff(ys))) if len(ys) > 2 else h / 60
    vk = int(max(12, min(h // 60, rh * 0.7)))
    ver = cv2.morphologyEx(bw, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, vk)))
    # 세로선은 행마다 따로 본다. 셀 병합이 많은 양식(미래에셋: 거래종류 칸이 아래 줄에서 원번호·거래수량·단가로
    # 갈린다)은 표 전체 높이를 잇는 세로선이 몇 개뿐이라, 전체 높이 기준으로 보면 열을 놓친다.
    row_xs = {}
    allx = []
    for ri in range(len(ys) - 1):
        y0, y1 = ys[ri] + 2, ys[ri + 1] - 2
        if y1 - y0 < 6:
            continue
        cov = ver[y0:y1].sum(axis=0) / 255
        xr = _cluster([i for i, v in enumerate(cov) if v >= (y1 - y0) * 0.45])
        # 바깥 테두리: 이 행 위아래 가로선의 양 끝(세로 테두리가 얇거나 끊겨 안 잡히는 스캔본이 있다)
        hl = np.where(hor[ys[ri]] > 0)[0] if ys[ri] < hor.shape[0] else np.array([])
        if hl.size:
            for edge in (int(hl.min()), int(hl.max())):
                if not any(abs(edge - x) <= 8 for x in xr):
                    xr = sorted(xr + [edge])
        row_xs[ri] = xr
        allx += xr
    xs = _cluster(sorted(allx), gap=8)
    if len(xs) < 3:
        return None
    find_grid.row_xs = {ri: sorted({min(xs, key=lambda g: abs(g - x)) for x in xr}) for ri, xr in row_xs.items()}
    return ys, xs, bw, hor, ver


# ---------------------------------------------------------------- 엔진

_RAPID = None
_LINE_H = []      # 이번 쪽에서 잘라 낸 글자 줄 높이(품질 판정용)


def rapid_engine():
    global _RAPID
    if _RAPID is None:
        from rapidocr import RapidOCR
        from rapidocr.utils.typings import LangRec, OCRVersion, ModelType
        # 한국어 인식 모델은 PP-OCRv5 mobile 만 있다(server 를 고르면 설정 오류)
        _RAPID = RapidOCR(params={"Rec.lang_type": LangRec.KOREAN, "Rec.ocr_version": OCRVersion.PPOCRV5,
                                  "Rec.model_type": ModelType.MOBILE, "Global.log_level": "critical"})
    return _RAPID


def has_rapid():
    try:
        import rapidocr  # noqa: F401
        return True
    except ImportError:
        return False


def has_tesseract():
    try:
        import pytesseract
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def _rapid_boxes(img):
    eng = rapid_engine()
    r = eng(img, use_det=True, use_cls=False, use_rec=True)
    out = []
    if r is None or r.boxes is None:
        return out
    for box, txt, sc in zip(r.boxes, r.txts, r.scores):
        b = np.array(box)
        out.append((float(b[:, 0].mean()), float(b[:, 1].mean()), float(b[:, 0].min()), float(b[:, 1].min()), txt, float(sc)))
    return out


def _text_lines(crop):
    """칸 안의 글자 줄을 가로 투영으로 나눈다(두 줄 칸: 미국(NASDAQ)/주식매도)."""
    import cv2
    bw = cv2.threshold(crop, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    prof = bw.sum(axis=1) / 255
    on = prof > max(1, bw.shape[1] * 0.01)
    spans, start = [], None
    for i, v in enumerate(on):
        if v and start is None:
            start = i
        elif not v and start is not None:
            if i - start >= 4:
                spans.append((start, i))
            start = None
    if start is not None and len(on) - start >= 4:
        spans.append((start, len(on)))
    # 너무 가까운 줄(받침·쉼표 조각)은 합친다
    merged = []
    for a, b in spans:
        if merged and a - merged[-1][1] < 3:
            merged[-1] = (merged[-1][0], b)
        else:
            merged.append((a, b))
    out = []
    for a, b in merged:
        _LINE_H.append(b - a)
        cols = np.where(bw[a:b].sum(axis=0) > 0)[0]
        if cols.size == 0:
            continue
        x0, x1 = max(0, cols[0] - 4), min(crop.shape[1], cols[-1] + 5)
        out.append(crop[max(0, a - 4):min(crop.shape[0], b + 4), x0:x1])
    return out


def _rapid_rec(line_img):
    import cv2
    eng = rapid_engine()
    h = line_img.shape[0]
    if h < 32:
        f = 48 / h
        line_img = cv2.resize(line_img, None, fx=f, fy=f, interpolation=cv2.INTER_CUBIC)
    hh, ww = line_img.shape
    side = max(12, (hh * 3 - ww) // 2)    # 한 글자 칸은 폭이 좁아 인식 모델이 빈 글을 낸다
    line_img = cv2.copyMakeBorder(line_img, 8, 8, side, side, cv2.BORDER_CONSTANT, value=255)
    r = eng(cv2.cvtColor(line_img, cv2.COLOR_GRAY2BGR), use_det=False, use_cls=False, use_rec=True)  # 인식만
    txts = getattr(r, "txts", None) or ()
    scs = getattr(r, "scores", None) or ()
    if not txts:
        return "", 0.0
    return "".join(txts).strip(), float(min(scs)) if scs else 0.0


def _rapid_cell(crop):
    lines = _text_lines(crop)
    if not lines:
        return "", 0.0
    parts = [_rapid_rec(ln) for ln in lines]
    parts = [p for p in parts if p[0]]
    if not parts:
        return "", 0.0
    txt = "".join(p[0] for p in parts)
    return txt, min(p[1] for p in parts)


def _tess_cell(crop, numeric_hint=False):
    import pytesseract
    import cv2
    h = crop.shape[0]
    if h < 40:
        f = 40 / h
        crop = cv2.resize(crop, None, fx=f, fy=f, interpolation=cv2.INTER_CUBIC)
    crop = cv2.copyMakeBorder(crop, 10, 10, 10, 10, cv2.BORDER_CONSTANT, value=255)
    psm = 7 if crop.shape[0] < 90 else 6
    if crop.shape[1] < crop.shape[0] * 1.2:
        psm = 10       # 한 글자
    cfg = f"--psm {psm}"
    d = pytesseract.image_to_data(crop, lang="kor+eng", config=cfg, output_type=pytesseract.Output.DICT)
    words = [(t, float(c)) for t, c in zip(d["text"], d["conf"]) if t.strip() and float(c) >= 0]
    txt = " ".join(t for t, _ in words)
    conf = min((c for _, c in words), default=0) / 100
    looks_num = numeric_hint or (txt and sum(ch.isdigit() for ch in txt) >= max(1, len(txt.replace(" ", "")) * 0.6))
    if looks_num:
        d2 = pytesseract.image_to_data(crop, lang="eng", config=f"--psm {10 if psm == 10 else 7} -c tessedit_char_whitelist=0123456789,.-()",
                                       output_type=pytesseract.Output.DICT)
        w2 = [(t, float(c)) for t, c in zip(d2["text"], d2["conf"]) if t.strip() and float(c) >= 0]
        t2 = "".join(t for t, _ in w2)
        c2 = min((c for _, c in w2), default=0) / 100
        if t2 and NUM_RE.match(t2) and (c2 >= conf or not NUM_RE.match(txt.replace(" ", ""))):
            return t2, c2
    return txt, conf


def _blank(crop):
    """어두운 점이 거의 없으면 빈칸. 「1」 처럼 잉크가 적은 한 글자를 지우지 않게 고정 문턱으로 센다."""
    return int((crop < 150).sum()) < 12


_DATE_GLUE = re.compile(r"^((?:19|20)\d{2}[./-]\d{1,2}[./-]\d{2})(\d+)$")


def _fix_num(t):
    """숫자 칸의 흔한 오인식(O→0, l·I·|→1)과 공백을 바로잡는다. 글자가 섞이면 손대지 않는다.
    날짜 바로 뒤에 붙은 숫자(2021/03/101 = 날짜 + 거래번호 1)는 띄운다."""
    m = _DATE_GLUE.match((t or "").replace(" ", ""))
    if m:
        return f"{m.group(1)} {m.group(2)}"
    s = t.replace(" ", "")
    trans = s.translate(str.maketrans({"O": "0", "o": "0", "l": "1", "I": "1", "|": "1", "S": "5"}))
    if NUM_RE.match(trans) and sum(ch.isdigit() for ch in s) >= len(s) * 0.6:
        return trans
    return t


# ---------------------------------------------------------------- 표 읽기

def read_page(gray, engine="auto", page_no=1, res: OcrResult | None = None):
    import cv2
    _LINE_H.clear()
    scale = 1.0
    gray, nz = denoise(gray)
    h0, w0 = gray.shape
    gray = upscale_small(gray, min_h=2400)
    scale = gray.shape[0] / h0
    gray, ang = deskew(gray)
    gray = flatten(gray)
    if res is not None:
        res.angle.append(round(ang, 2))
    g = find_grid(gray)
    th0 = 0.0
    if has_rapid() and engine in ("rapid", "auto"):
        d0 = _det_boxes(gray)
        if d0:
            th0 = float(np.median([b[3] - b[1] for b in d0]))
    hmask, vmask = line_masks(gray, th0)
    nolines = gray.copy()
    nolines[(hmask > 0) | (vmask > 0)] = 255
    full_grid = False
    if g is not None:
        ys = g[0]
        rh = np.median(np.diff(ys)) if len(ys) > 2 else 0
        full_grid = len(ys) >= 4 and 0 < rh < gray.shape[0] / 8   # 가로선이 행마다 있는 표
        if full_grid and has_rapid() and engine in ("rapid", "auto"):
            # 글자 줄이 가로선 사이 칸보다 훨씬 많으면 행마다 선이 있는 표가 아니다(HTS 화면)
            dets = _det_boxes(nolines)
            if dets:
                cys = sorted((b[1] + b[3]) / 2 for b in dets)
                hm = float(np.median([b[3] - b[1] for b in dets]))
                nl = 1 + sum(1 for a, b in zip(cys, cys[1:]) if b - a > hm * 0.6)
                if nl > 1.6 * (len(ys) - 1):
                    full_grid = False
    use_rapid = engine in ("rapid", "auto") and has_rapid()
    use_tess = engine == "tesseract" or (engine == "auto" and has_tesseract())
    if engine == "tesseract" and not has_tesseract():
        raise RuntimeError("Tesseract 가 없다")
    if not use_rapid and not use_tess:
        raise RuntimeError("OCR 엔진이 없다(pip install rapidocr 또는 Tesseract 설치)")
    if not full_grid:
        if res is not None:
            res.grid.append("글자상자" + ("+세로선" if g is not None else ""))
        rows = _read_boxes(nolines, _vlines(vmask, max(25, int(th0 * 2.5))), use_rapid, use_tess, res, page_no)
        rows = fix_columns(rows, res, page_no)
        if res is not None and _LINE_H:
            th = float(np.median(_LINE_H)) / scale
            res.text_px.append(round(th, 1))
            if th < 6:
                res.quality.append(f"{page_no}쪽 글자 높이 {th:.0f}px(원본 기준): 해상도가 낮아 숫자 판독을 믿기 어렵다. "
                                   "300dpi 이상으로 다시 스캔하거나 증권사에서 원본(엑셀·PDF)을 받는다")
        return rows
    ys, xs, bw, hor, ver = g
    # 칸 하나에 글자 줄이 셋 이상 몰리면 행마다 가로선이 있는 표가 아니다(HTS 화면) → 글자 상자 방식
    crowded = total = 0
    for ri in range(len(ys) - 1):
        for ci in range(len(xs) - 1):
            cr = gray[ys[ri] + 3:ys[ri + 1] - 3, xs[ci] + 3:xs[ci + 1] - 3]
            if cr.size == 0 or _blank(cr):
                continue
            total += 1
            if len(_text_lines(cr)) >= 3:
                crowded += 1
    _LINE_H.clear()
    if total and crowded / total >= 0.10:
        if res is not None:
            res.grid.append("글자상자+세로선")
        rows = _read_boxes(nolines, _vlines(vmask, max(25, int(th0 * 2.5))), use_rapid, use_tess, res, page_no)
        rows = fix_columns(rows, res, page_no)
        if res is not None and _LINE_H:
            th = float(np.median(_LINE_H)) / scale
            res.text_px.append(round(th, 1))
            if th < 6:
                res.quality.append(f"{page_no}쪽 글자 높이 {th:.0f}px(원본 기준): 해상도가 낮아 숫자 판독을 믿기 어렵다. "
                                   "300dpi 이상으로 다시 스캔하거나 증권사에서 원본(엑셀·PDF)을 받는다")
        return rows
    if res is not None:
        res.grid.append("칸선")
    # 칸 선을 지운 이미지(엔진이 선을 1·l 로 읽지 않게)
    clean = gray.copy()
    clean[(hor > 0) | (ver > 0)] = 255
    rows = []
    row_xs = getattr(find_grid, "row_xs", {})
    for ri in range(len(ys) - 1):
        y0, y1 = ys[ri], ys[ri + 1]
        if y1 - y0 < 8:
            continue
        row = [None] * (len(xs) - 1)
        xr = row_xs.get(ri) or xs
        for k in range(len(xr) - 1):
            x0, x1 = xr[k], xr[k + 1]
            if x1 - x0 < 8:
                continue
            gci = xs.index(x0) if x0 in xs else min(range(len(xs) - 1), key=lambda g: abs(xs[g] - x0))
            pad = 3
            crop = clean[y0 + pad:y1 - pad, x0 + pad:x1 - pad]
            if crop.size == 0 or _blank(crop):
                continue
            txt, conf, eng = "", 0.0, ""
            if use_rapid:
                txt, conf = _rapid_cell(crop)
                eng = "rapid"
            if use_tess and (not txt or (engine == "tesseract") or (conf < 0.85 and _numericish(txt))):
                t2, c2 = _tess_cell(crop, numeric_hint=_numericish(txt))
                if engine == "tesseract" or not txt or (NUM_RE.match(_fix_num(t2)) and not NUM_RE.match(_fix_num(txt))) or c2 > conf + 0.1:
                    txt, conf, eng = t2, c2, "tesseract"
            txt = _fix_num(txt)
            if res is not None:
                res.cells.append(OcrCell(len(rows), gci, txt, conf, eng))
                if conf < 0.80:
                    res.suspects.append((page_no, len(rows) + 1, gci + 1, txt, round(conf, 2)))
            row[gci] = txt or None
        if any(c for c in row):
            rows.append(row)
    rows = fix_columns(rows, res, page_no)
    if res is not None and _LINE_H:
        th = float(np.median(_LINE_H)) / scale       # 원본 해상도 기준 글자 줄 높이
        res.text_px.append(round(th, 1))
        if th < 6:
            res.quality.append(f"{page_no}쪽 글자 높이 {th:.0f}px(원본 기준): 해상도가 낮아 숫자 판독을 믿기 어렵다. "
                               "300dpi 이상으로 다시 스캔하거나 증권사에서 원본(엑셀·PDF)을 받는다")
    return rows


_SEP_RE = re.compile(r"^[\-\(]?[0-9][0-9.,]*[0-9]\)?$")


def fix_number(t):
    """쉼표·마침표 혼동을 바로잡는다. 1,234.56 꼴로 맞출 수 없으면 그대로 둔다."""
    s = re.sub(r"[.,]{2,}", lambda m: m.group(0)[-1], t.replace(" ", ""))
    if not _SEP_RE.match(s):
        return t
    neg = s.startswith("-") or s.startswith("(")
    core = s.strip("-()")
    parts = re.split(r"[.,]", core)
    if len(parts) == 1:
        return t
    head, mids, last = parts[0], parts[1:-1], parts[-1]
    if not (1 <= len(head) <= 3) or any(len(m) != 3 for m in mids):
        return t
    if len(last) == 3 and not (len(parts) == 2 and core[len(head)] == "." and False):
        # 마지막 묶음이 세 자리면 정수(천 단위). 단, 원래 글이 한 묶음 + 마침표면 소수일 수도 있어 원래 꼴을 존중
        if len(parts) == 2 and core[len(head)] == ".":
            return t
        out = ",".join([head] + mids + [last])
    elif len(last) in (1, 2):
        out = ",".join([head] + mids) + "." + last
    else:
        return t
    return ("-" if neg else "") + out


_CONFUSE = {"C": "0", "c": "0", "O": "0", "o": "0", "D": "0", "〇": "0", "ε": "8", "B": "8", "l": "1", "I": "1", "|": "1",
            "S": "5", "s": "5", "Z": "2", "z": "2", "g": "9", "q": "9"}


def _unconfuse(v: str) -> str:
    """숫자 열 칸 안의 숫자 닮은 글자를 숫자로(2026-11-08 미래에셋 스캔본: 환율 1,480 → 1,48C, 1,328 → 1,32ε).
    숫자가 둘 이상 있고, 바꾼 뒤 숫자 꼴이 될 때만 바꾼다."""
    t = v.replace(" ", "")
    if sum(ch.isdigit() for ch in t) < 2 or not any(ch in _CONFUSE for ch in t):
        return v
    u = "".join(_CONFUSE.get(ch, ch) for ch in t)
    return u if NUM_RE.match(u) or _SEP_RE.match(u) else v


def fix_columns(rows, res, page_no):
    """숫자가 대부분인 열은 그 열의 칸을 숫자로 보정한다(o→0, 쉼표·마침표). 바꾼 칸은 의심 칸으로 남긴다."""
    if not rows:
        return rows
    from read_source import load_dict, norm
    _, index = load_dict()
    hits = [sum(1 for c in r if c and norm(c) in index) for r in rows]
    h0 = int(np.argmax(hits)) if max(hits) >= 2 else 0
    body = rows[h0 + 1:]
    width = max(len(r) for r in rows)
    for c in range(width):
        vals = [r[c] for r in body if c < len(r) and r[c]]
        if not vals:
            continue
        numeric = sum(1 for v in vals if NUM_RE.match(v.replace(" ", "")) or v.strip() in ("o", "O", "D", "〇")) / len(vals)
        if numeric < 0.7:
            continue
        # 소수 둘째 자리 값(0.00, 1,296.72)이 하나도 없는 열은 원화 정수 열이다. 거기서 5.200 은 5,200 이다.
        int_col = not any(re.search(r"\.\d{1,2}$", v.replace(" ", "")) for v in vals)
        for ri, r in enumerate(body, h0 + 1):
            if c >= len(r) or not r[c]:
                continue
            v = r[c]
            nv = v
            if v.strip() in ("o", "O", "D", "〇"):
                nv = "0"
            elif not NUM_RE.match(v.replace(" ", "")):
                nv = fix_number(_unconfuse(v))
                if nv == v and re.fullmatch(r"[.,·\-]", v.strip()):
                    nv = "0"
            else:
                nv = fix_number(v)
            if int_col and re.fullmatch(r"-?\d{1,3}(\.\d{3})+", nv.replace(" ", "")):
                nv = nv.replace(".", ",")
            if nv != v:
                r[c] = nv
                if res is not None:
                    res.suspects.append((page_no, ri + 1, c + 1, f"{v}→{nv}", 0.5))
    return rows


def _numericish(t):
    s = (t or "").replace(" ", "")
    return bool(s) and sum(ch.isdigit() for ch in s) >= len(s) * 0.6


def _vlines(vmask, min_h=25):
    """세로선 조각: [(x, y0, y1)]. 표 일부에만 있는 선도 쓴다."""
    import cv2
    n, _, st, _ = cv2.connectedComponentsWithStats((vmask > 0).astype(np.uint8), 8)
    out = []
    for i in range(1, n):
        x, y, w, h, a = st[i]
        if h >= min_h and w <= 12:
            out.append((int(x + w / 2), int(y), int(y + h)))
    return out


def _det_boxes(gray):
    """글자 상자만 찾는다(인식은 상자마다 따로). [(x0,y0,x1,y1)]"""
    import cv2
    eng = rapid_engine()
    r = eng(cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR), use_det=True, use_cls=False, use_rec=False)
    bx = getattr(r, "boxes", None)
    out = []
    if bx is None:
        return out
    for b in bx:
        b = np.array(b)
        out.append((int(b[:, 0].min()), int(b[:, 1].min()), int(b[:, 0].max()), int(b[:, 1].max())))
    return out


def _read_boxes(gray, vlines, use_rapid, use_tess, res, page_no):
    """칸 가로선이 없는 표(HTS 화면, 칸선 없는 PDF): 글자 상자 → 줄 → 열."""
    import cv2
    if not use_rapid:
        return _read_lines(gray, False)
    boxes = _det_boxes(gray)
    if not boxes:
        return []
    segs = vlines or []
    split = []
    for (x0, y0, x1, y1) in boxes:
        cuts = sorted({sx for sx, sy0, sy1 in segs if x0 + 4 < sx < x1 - 4 and sy0 <= (y0 + y1) / 2 <= sy1})
        xs_ = [x0] + cuts + [x1]
        for a, b in zip(xs_, xs_[1:]):
            if b - a >= 6:
                split.append((a, y0, b, y1))
    # 상자 안의 넓은 빈 틈(글자 높이의 0.6배 이상)에서 자른다. 옅은 칸선만 있는 HTS 화면에서
    # 이웃한 두 열 숫자(26,818,000 26,694,000)가 한 상자로 잡히는 것을 막는다.
    gap_split = []
    for (x0, y0, x1, y1) in split:
        crop = gray[y0:y1, x0:x1]
        if crop.size == 0:
            continue
        ink = (crop < 150).sum(axis=0) > 0
        hgt = y1 - y0
        runs, start = [], None
        for i, v in enumerate(ink):
            if not v and start is None:
                start = i
            elif v and start is not None:
                if i - start >= max(4, hgt * 0.6) and start > 0:
                    runs.append((start, i))
                start = None
        cuts = [x0 + (a + b) // 2 for a, b in runs]
        xs_ = [x0] + cuts + [x1]
        for a, b in zip(xs_, xs_[1:]):
            if b - a >= 4:
                gap_split.append((a, y0, b, y1))
    boxes = gap_split
    items = []
    for (x0, y0, x1, y1) in boxes:
        crop = gray[max(0, y0 - 2):y1 + 2, max(0, x0 - 2):x1 + 2]
        if crop.size == 0:
            continue
        rows_ink = np.where((crop < 150).sum(axis=1) > 0)[0]
        if rows_ink.size:
            _LINE_H.append(int(rows_ink[-1] - rows_ink[0] + 1))   # 여백 뺀 실제 글자 높이
        t, c = _rapid_rec(crop)
        cands = [(_fix_num(t), c, "rapid")] if t else []
        # Tesseract 는 RapidOCR 이 숫자로 읽은 상자에만 쓴다. 빈 상자(잡티)를 채우면 가짜 글자가 생겨 열 경계가 흔들린다.
        if use_tess and t and _numericish(t):
            t2, c2 = _tess_cell(crop, numeric_hint=True)
            if t2:
                cands.append((_fix_num(t2), c2, "tesseract"))
        if not cands:
            continue
        t, c = cands[0][0], cands[0][1]
        items.append(dict(x0=x0, y0=y0, x1=x1, y1=y1, cx=(x0 + x1) / 2, cy=(y0 + y1) / 2, t=t, c=c, cands=cands))
    if not items:
        return []
    hmed = float(np.median([i["y1"] - i["y0"] for i in items]))
    items.sort(key=lambda i: i["cy"])
    lines, cur = [], [items[0]]
    for it in items[1:]:
        if abs(it["cy"] - np.mean([c["cy"] for c in cur])) <= hmed * 0.55:
            cur.append(it)
        else:
            lines.append(cur)
            cur = [it]
    lines.append(cur)
    # 열 경계: 세로선이 있으면 그것, 없으면 상자가 가장 많은 줄(머리글 후보)의 상자 사이 중간점
    # 열은 글자 상자 구간으로 나누고, 세로선은 어떤 글자 상자도 가로지르지 않을 때만 경계로 더한다
    # (옅은 칸선은 일부만 잡혀 선만으로 나누면 틀린다)
    bounds = _column_bounds(lines, gray.shape[1])
    long_x = sorted({sx for sx, sy0, sy1 in (vlines or []) if sy1 - sy0 > gray.shape[0] * 0.15})
    allit = [i for ln in lines for i in ln]
    for x in long_x:
        if not any(i["x0"] + 2 < x < i["x1"] - 2 for i in allit) and all(abs(x - bb) > 15 for bb in bounds):
            bounds.append(x)
    bounds = sorted(bounds)
    ncol = len(bounds) - 1
    rows = []
    cmap = {}
    for ln in lines:
        row = [None] * ncol
        cell_items = {}
        for it in sorted(ln, key=lambda i: i["x0"]):
            ci = int(np.searchsorted(bounds, it["cx"]) - 1)
            ci = min(max(ci, 0), ncol - 1)
            cell_items.setdefault(ci, []).append(it)
            row[ci] = (row[ci] + " " + it["t"]) if row[ci] else it["t"]
            if res is not None:
                res.cells.append(OcrCell(len(rows), ci, it["t"], it["c"], "rapid"))
                if it["c"] < 0.80:
                    res.suspects.append((page_no, len(rows) + 1, ci + 1, it["t"], round(it["c"], 2)))
        if any(row):
            for ci, its in cell_items.items():
                if len(its) == 1 and len(its[0].get("cands", [])) > 1:
                    cmap[(len(rows), ci)] = its[0]["cands"]
            rows.append(row)
    return resolve_numeric(rows, cmap, res, page_no)


_NUMPAT = re.compile(r"^-?\(?\d{1,3}(,\d{3})*(\.\d+)?\)?$|^-?\d+(\.\d+)?$")


def _decimals(v):
    m = re.search(r"\.(\d+)\)?$", v.replace(" ", ""))
    return len(m.group(1)) if m else 0


def resolve_numeric(rows, cmap, res, page_no):
    """두 엔진이 다르게 읽은 숫자 칸은 같은 열 다른 칸의 모양(소수 자릿수·쉼표 묶음)에 맞는 쪽을 고른다.
    RapidOCR 은 소수 끝 0을 빠뜨리고(190.0000 → 190.000), Tesseract 는 흐린 숫자에서 자릿수를 잃는다."""
    from collections import Counter
    if not cmap:
        return rows
    for ci in sorted({c for _, c in cmap}):
        decs = Counter()
        for ri, r in enumerate(rows):
            v = r[ci] if ci < len(r) else None
            if not v:
                continue
            cs = cmap.get((ri, ci))
            vals = [x[0] for x in cs] if cs else [v]
            # 두 엔진이 같게 읽었거나 후보가 하나뿐인 값만 기준으로 센다
            if len(set(vals)) == 1 and _NUMPAT.match(vals[0].replace(" ", "")):
                decs[_decimals(vals[0])] += 1
        mode = decs.most_common(1)[0][0] if decs else None
        colvals = [r[ci] for r in rows if ci < len(r) and r[ci]]
        if not colvals or sum(1 for v in colvals if _NUMPAT.match(v.replace(" ", ""))) < len(colvals) * 0.5:
            continue            # 숫자 열이 아니면(날짜·글 열) 고르지 않는다
        for ri, r in enumerate(rows):
            cs = cmap.get((ri, ci))
            if not cs or len({x[0] for x in cs}) == 1:
                continue
            if re.match(r"^(19|20)\d{2}[./-]", (r[ci] or "").replace(" ", "")):
                continue        # 날짜는 RapidOCR 값을 둔다(Tesseract 는 빗금을 7로 읽는다)

            def fits(v):
                v = v.replace(" ", "")
                return bool(_NUMPAT.match(v)) and (mode is None or _decimals(v) == mode)

            def digits(v):
                return re.sub(r"\D", "", v)

            # 기본은 RapidOCR. RapidOCR 값이 열 모양에 안 맞고, Tesseract 값이 맞으면서 숫자 배열이
            # 70% 이상 비슷할 때만 바꾼다(저해상도에서 Tesseract 가 모양만 맞는 엉뚱한 숫자를 내는 것을 막는다).
            from difflib import SequenceMatcher
            prim = next((x for x in cs if x[2] == "rapid"), cs[0])
            best = prim
            if not fits(prim[0]):
                for x in cs:
                    if x is prim or not fits(x[0]):
                        continue
                    if SequenceMatcher(None, digits(prim[0]), digits(x[0])).ratio() >= 0.7:
                        best = x
                        break
            # 부호는 괄호·마이너스를 본 엔진 쪽을 따른다(자릿수는 열 모양에 맞는 쪽, 부호는 따로)
            if not best[0].lstrip().startswith(("-", "(")) and any(x[0].lstrip().startswith(("-", "(")) for x in cs):
                best = ("-" + best[0].strip().strip("()"), best[1], best[2] + "+부호")
            if best[0] != r[ci]:
                if res is not None:
                    res.suspects.append((page_no, ri + 1, ci + 1, f"{r[ci]}→{best[0]}({best[2]})", round(best[1], 2)))
                r[ci] = best[0]
    return rows


def _column_bounds(lines, width):
    """열 경계: x 위치마다 글자가 걸린 줄 수를 세고, 거의 빈 세로 띠(줄의 12% 이하)를 경계로 쓴다.
    머리글은 가운데, 숫자는 오른쪽 정렬이라 머리글 위치로 나누면 틀어지고, 몇 줄의 긴 숫자가
    이웃 열과 닿아도 경계가 사라지지 않게 비율로 본다."""
    # 표 본문만 본다: 숫자·날짜 상자가 둘 이상인 줄과 머리글 후보 줄. 위쪽 안내문·조회 조건 줄은 빼야
    # 왼쪽 글자 열 사이의 빈 띠가 살아남는다.
    from read_source import load_dict, lookup
    _, index = load_dict()

    def body_like(ln):
        nums = sum(1 for i in ln if _numericish(i["t"]) or re.match(r"^(19|20)\d{2}[./-]\d{1,2}", i["t"]))
        heads = sum(1 for i in ln if lookup(index, i["t"]))
        return nums >= 2 or heads >= 2

    many = [ln for ln in lines if len(ln) >= 3 and body_like(ln)] or [ln for ln in lines if len(ln) >= 3]
    if not many:
        return [0, width]
    cov = np.zeros(width + 1, dtype=np.int32)
    for ln in many:
        mark = np.zeros(width + 1, dtype=bool)
        for i in ln:
            if (i["x1"] - i["x0"]) < width * 0.22:
                mark[max(0, i["x0"]):min(width, i["x1"]) + 1] = True
        cov += mark
    thr = max(1, int(len(many) * 0.12))
    busy = cov > thr
    bounds, x = [0], 0
    while x <= width:
        if not busy[x]:
            s0 = x
            while x <= width and not busy[x]:
                x += 1
            if s0 > 0 and x <= width:
                bounds.append((s0 + x) // 2)
        else:
            x += 1
    bounds.append(width)
    return sorted(set(bounds))


def _read_lines(gray, use_rapid):
    """칸 선이 없는 표: 글자 상자를 줄로 묶고, 머리글 줄의 글자 위치로 열을 나눈다."""
    import cv2
    if use_rapid:
        boxes = _rapid_boxes(cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR))
    else:
        import pytesseract
        d = pytesseract.image_to_data(gray, lang="kor+eng", config="--psm 6", output_type=pytesseract.Output.DICT)
        boxes = [(d["left"][i] + d["width"][i] / 2, d["top"][i] + d["height"][i] / 2, d["left"][i], d["top"][i], d["text"][i], float(d["conf"][i]) / 100)
                 for i in range(len(d["text"])) if d["text"][i].strip()]
    if not boxes:
        return []
    hs = np.median([abs(b[1] - b[3]) * 2 for b in boxes]) or 20
    boxes.sort(key=lambda b: b[1])
    lines, cur = [], [boxes[0]]
    for b in boxes[1:]:
        if abs(b[1] - cur[-1][1]) <= hs * 0.6:
            cur.append(b)
        else:
            lines.append(sorted(cur, key=lambda x: x[2]))
            cur = [b]
    lines.append(sorted(cur, key=lambda x: x[2]))
    # 상자가 가장 많은 줄의 왼쪽 끝을 열 경계로 쓴다
    ref = max(lines, key=len)
    starts = [b[2] for b in ref]
    rows = []
    for ln in lines:
        row = [None] * len(starts)
        for b in ln:
            ci = max(0, int(np.searchsorted(starts, b[2] + 5) - 1))
            row[ci] = (row[ci] + " " + b[4]) if row[ci] else b[4]
        rows.append([_fix_num(c) if c else None for c in row])
    return rows


_JUNK = {"o", "O", "○", "●", "◎", "□", "■", "v", "V", "√", "✓", "|", "-", "·", "."}


def drop_junk_rows(rows):
    """라디오 단추(○)·체크 표시만 있는 줄을 버린다. 2행 1건 짝이 깨지지 않게."""
    out = []
    for r in rows:
        vals = [str(c).strip() for c in r if c not in (None, "")]
        if vals and all(v in _JUNK for v in vals):
            continue
        out.append(r)
    return out


def read_table_images(path: Path, engine="auto") -> OcrResult:
    pages = load_pages(path)
    res = OcrResult(rows=[], pages=len(pages), engine=engine)
    if path.suffix.lower() == ".pdf":
        res.src_ppi = pdf_image_ppi(path)
        for pg, ppi in sorted(res.src_ppi.items()):
            if ppi < 150:
                res.quality.append(f"{pg}쪽 원본 이미지 해상도 {ppi}ppi: 150ppi 미만이라 숫자 판독을 믿기 어렵다. "
                                   "증권사에서 원본(엑셀·글자 있는 PDF)을 받거나 300dpi 이상으로 다시 스캔한다")
    for i, pg in enumerate(pages, 1):
        rows = drop_junk_rows(read_page(pg, engine=engine, page_no=i, res=res))
        res.rows.extend(rows)
        res.rows.append([None])
    return res
