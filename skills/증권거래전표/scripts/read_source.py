"""증권사 거래내역 파일을 읽어 머리글이 붙은 행 목록으로 바꾼다.

받는 형식: .xlsx .xlsm .xls(진짜 xls 와 HTML 로 된 xls 둘 다) .csv .txt .html .pdf
PDF 는 kordoc 으로 표를 뽑고, 글자층이 없으면 --ocr 로 다시 읽는다.
표를 끝내 못 뽑으면 SourceError 를 내고, AI 가 templates/표준거래표_양식.csv 에 옮겨 적는 길로 간다.

이 모듈은 값을 해석하지 않는다. 머리글을 표준 열 이름에 맞추고 행을 넘길 뿐이다.
"""
from __future__ import annotations

import csv
import datetime as dt
import html.parser
import json
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
REF = HERE.parent / "references"


class SourceError(Exception):
    pass


@dataclass
class Table:
    source: str
    sheet: str
    header_row: int                      # 0-based 첫 머리글 행
    header_rows: int                     # 머리글 행 수
    mode: str                            # single | combined | multiline
    columns: list                        # [(열번호, 줄번호, 표준열, 원문머리글)]
    records: list = field(default_factory=list)   # [{"_row": n, 표준열: 값, ...}]
    unmapped: list = field(default_factory=list)  # 맞추지 못한 머리글
    title: str = ""                       # 표 위쪽 글(조회기간 등)
    ocr: object = None                    # OCR 로 읽었으면 OcrResult(의심 칸·품질)


# ---------------------------------------------------------------- 사전

EXTRA_ALIASES = {}      # 설정 「머리글」: {원문 머리글: 표준열}. 사전보다 먼저 쓴다(run.py 가 채운다)


def load_dict():
    d = json.loads((REF / "머리글사전.json").read_text(encoding="utf-8"))
    index = {}
    for fld, aliases in d["fields"].items():
        for a in aliases:
            index.setdefault(norm(a), fld)
    for raw, fld in EXTRA_ALIASES.items():
        if fld not in d["fields"]:
            raise SourceError(f"설정 머리글 '{raw}' 의 표준열 '{fld}' 이 머리글사전에 없다. 쓸 수 있는 열: {', '.join(d['fields'])}")
        index[norm(raw)] = fld
    return d, index


def norm(s) -> str:
    if s is None:
        return ""
    s = str(s)
    s = s.replace("　", " ").replace("\n", "").replace("\r", "")
    for u in ["(원)", "(주)", "(₩)", "₩", "﻿", "'"]:
        s = s.replace(u, "")
    s = re.sub(r"[\s\.·:]", "", s)
    s = s.replace("（", "(").replace("）", ")")
    s = re.sub(r"[()\[\]]", "", s)
    return s.strip()


# ---------------------------------------------------------------- 셀 읽기

def _read_xlsx(path: Path):
    import openpyxl
    wb = openpyxl.load_workbook(path, data_only=True, read_only=False)
    out = []
    for ws in wb.worksheets:
        rows = []
        for r in ws.iter_rows(values_only=True):
            rows.append(list(r))
        # 병합 셀은 왼쪽 위 값만 있다. 머리글 짝짓기를 위해 가로 병합을 채운다.
        for mr in ws.merged_cells.ranges:
            v = ws.cell(mr.min_row, mr.min_col).value
            for rr in range(mr.min_row, mr.max_row + 1):
                for cc in range(mr.min_col, mr.max_col + 1):
                    if rr - 1 < len(rows) and cc - 1 < len(rows[rr - 1]) and rows[rr - 1][cc - 1] is None:
                        if rr == mr.min_row:      # 가로 병합만 채운다(세로 병합은 다단 머리글 판정을 흐린다)
                            rows[rr - 1][cc - 1] = v
        out.append((ws.title, rows))
    return out


def _read_xls(path: Path):
    import xlrd
    book = xlrd.open_workbook(str(path))
    out = []
    for sh in book.sheets():
        rows = []
        for r in range(sh.nrows):
            row = []
            for c in range(sh.ncols):
                cell = sh.cell(r, c)
                if cell.ctype == xlrd.XL_CELL_DATE:
                    row.append(xlrd.xldate.xldate_as_datetime(cell.value, book.datemode))
                else:
                    row.append(cell.value if cell.value != "" else None)
            rows.append(row)
        out.append((sh.name, rows))
    return out


class _HTMLTables(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables, self._t, self._r, self._c, self._span = [], None, None, None, 1

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._t = []
        elif tag == "tr" and self._t is not None:
            self._r = []
        elif tag in ("td", "th") and self._r is not None:
            self._c = []
            self._span = int(dict(attrs).get("colspan", "1") or 1)
        elif tag == "br" and self._c is not None:
            self._c.append(" ")

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._c is not None:
            v = "".join(self._c).strip() or None
            self._r.append(v)
            for _ in range(self._span - 1):
                self._r.append(v)
            self._c = None
        elif tag == "tr" and self._r is not None:
            self._t.append(self._r)
            self._r = None
        elif tag == "table" and self._t is not None:
            self.tables.append(self._t)
            self._t = None

    def handle_data(self, data):
        if self._c is not None:
            self._c.append(data)


def _decode(raw: bytes) -> str:
    for enc in ("utf-8-sig", "cp949", "euc-kr", "utf-16"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _read_html_text(text: str):
    p = _HTMLTables()
    p.feed(text)
    return [(f"표{i+1}", t) for i, t in enumerate(p.tables)]


def _read_csv(path: Path):
    text = _decode(path.read_bytes())
    sample = text[:4000]
    delim = "\t" if sample.count("\t") > sample.count(",") else ","
    rows = [r for r in csv.reader(text.splitlines(), delimiter=delim)]
    return [("csv", [[c if c != "" else None for c in r] for r in rows])]


def _md_tables(md: str):
    """kordoc 마크다운에서 GFM 표와 HTML 표를 뽑는다."""
    tables = []
    tables += [t for _, t in _read_html_text(md)]
    cur = []
    for line in md.splitlines():
        s = line.strip()
        if s.startswith("|") and s.endswith("|"):
            cells = [c.strip() for c in s.strip("|").split("|")]
            if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
                continue
            cur.append([c or None for c in cells])
        else:
            if cur:
                tables.append(cur)
                cur = []
    if cur:
        tables.append(cur)
    return tables


def _kordoc(path: Path, ocr: bool) -> str:
    npx = shutil.which("npx") or shutil.which("npx.cmd")
    if not npx:
        raise SourceError("npx 가 없다. Node.js 18 이상을 설치하거나 PDF 를 AI 경로(양식 CSV)로 옮겨 적는다")
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "out.md"
        cmd = [npx, "-y", "kordoc@^4", str(path), "-o", str(out)]
        if ocr:
            cmd.append("--ocr")
        # 시간 제한은 쪽수에 맞춘다. OCR 은 쪽당 13초쯤 걸려(2026-11-07 실측) 900초 고정이면 128쪽에서 끊겼다
        try:
            import pdfplumber
            with pdfplumber.open(str(path)) as pdf:
                pages = len(pdf.pages)
        except Exception:
            pages = 50
        limit = max(900, pages * (30 if ocr else 5))
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=limit)
        except subprocess.TimeoutExpired:
            raise SourceError(f"kordoc 시간 초과({limit}초, {pages}쪽)")
        if not out.exists():
            raise SourceError(f"kordoc 실패: {r.stderr[-500:]}")
        return out.read_text(encoding="utf-8", errors="replace")


def _plumber_tables(path: Path):
    """칸 선이 있는 PDF(증권사 발급 거래내역서 대부분)는 pdfplumber 로 표를 그대로 뽑는다."""
    try:
        import pdfplumber
    except ImportError:
        return [], 0
    tables, nchars = [], 0
    with pdfplumber.open(str(path)) as pdf:
        for pg in pdf.pages:
            nchars += len(pg.chars)
            for t in pg.extract_tables():
                tables.append([[c if c not in ("",) else None for c in row] for row in t])
    return tables, nchars


_LAST_OCR = None


def _ocr(path: Path):
    """스캔 PDF·이미지: ocr_table(RapidOCR PP-OCRv5 한국어, 없으면 Tesseract)."""
    global _LAST_OCR
    try:
        import ocr_table
    except ImportError as e:
        raise SourceError(f"스캔본 · 이미지는 OCR 패키지가 있어야 읽는다({e.name} 없음). "
                          "스킬 폴더에서 pip install -r requirements-ocr.txt 를 실행한다")
    res = ocr_table.read_table_images(path, engine="auto")
    _LAST_OCR = res
    return res


def _read_pdf(path: Path):
    """PDF: ① pdfplumber 표(칸 선, 글자층 있음) ② kordoc 글자층 ③ 칸·글자상자 OCR(스캔본) ④ kordoc OCR.
    모두 머리글을 못 찾으면 AI 가 쪽 이미지를 읽는다."""
    tables, nchars = _plumber_tables(path)
    md = f"<!-- pdfplumber 표 {len(tables)}개, 글자 {nchars}자 -->\n"
    if not _has_header(tables) and nchars:
        md = _kordoc(path, ocr=False)
        tables = _md_tables(md)
    if not _has_header(tables):
        try:
            res = _ocr(path)
            if _has_header([res.rows]):
                return [("ocr", res.rows)], f"<!-- OCR {res.engine} 쪽 {res.pages} 방식 {res.grid} -->\n"
        except Exception as e:      # 엔진이 없으면 kordoc OCR 로 넘어간다
            md += f"<!-- OCR 실패: {e} -->\n"
    if not _has_header(tables):
        md = _kordoc(path, ocr=True)
        tables = _md_tables(md)
    # 쪽마다 머리글이 반복되면 같은 표로 잇는다. 머리글 판정은 locate_header 가 한다.
    merged = []
    for t in tables:
        merged.extend(t)
        merged.append([None])
    return [("pdf", merged)], md


def _merge(tables):
    merged = []
    for t in tables:
        merged.extend(t)
        merged.append([None])
    return merged


def pdf_candidates(path: Path):
    """PDF 를 읽는 방법 후보를 순서대로 돌려준다. [(이름, 함수)] 함수는 (시트목록, 추출 마크다운) 을 낸다.
    run.py 가 후보마다 전표를 돌려 대사·미분류·중단이 가장 적은 결과를 고른다(0이면 거기서 멈춘다).
    글자 있는 PDF: kordoc → pdfplumber. 스캔 PDF: 순서는 SCAN_ORDER."""
    tables, nchars = _plumber_tables(path)

    def k_text():
        md = _kordoc(path, ocr=False)
        return [("pdf", _merge(_md_tables(md)))], md

    def plumber():
        return [("pdf", _merge(tables))], f"<!-- pdfplumber 표 {len(tables)}개, 글자 {nchars}자 -->\n"

    def own_ocr():
        res = _ocr(path)
        return [("ocr", res.rows)], f"<!-- OCR {res.engine} 쪽 {res.pages} 방식 {res.grid} -->\n"

    def k_ocr():
        md = _kordoc(path, ocr=True)
        return [("ocr_kordoc", _merge(_md_tables(md)))], md

    text = [("kordoc", k_text), ("pdfplumber", plumber)]
    scan = [("자체 OCR", own_ocr), ("kordoc OCR", k_ocr)]
    if SCAN_ORDER == "kordoc":
        scan.reverse()
    return (text + scan) if nchars > 200 else scan


SCAN_ORDER = "own"      # 스캔본 첫 후보(own: 자체 OCR, kordoc: kordoc OCR). 2026-11-07 비교로 정한다


def _has_header(tables) -> bool:
    _, index = load_dict()
    for t in tables:
        for row in t[:30]:
            if sum(1 for c in row if lookup(index, c)) >= 3:
                return True
    return False


def read_cells(path: Path):
    """[(시트이름, 행목록)] 과 PDF 이면 추출 마크다운을 돌려준다."""
    suf = path.suffix.lower()
    head = path.read_bytes()[:2048]
    if suf == ".pdf":
        return _read_pdf(path)
    if suf in (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp", ".gif"):
        res = _ocr(path)
        return [("ocr", res.rows)], f"<!-- OCR {res.engine} 쪽 {res.pages} 방식 {res.grid} -->\n"
    looks_html = b"<table" in head.lower() or b"<html" in head.lower() or head.lstrip().startswith(b"<")
    if suf in (".html", ".htm") or (suf == ".xls" and looks_html):
        return _read_html_text(_decode(path.read_bytes())), None
    if suf in (".xlsx", ".xlsm"):
        return _read_xlsx(path), None
    if suf == ".xls":
        return _read_xls(path), None
    if suf in (".csv", ".txt", ".tsv"):
        return _read_csv(path), None
    raise SourceError(f"읽지 못하는 형식: {path.name}")


# ---------------------------------------------------------------- 머리글 찾기

_FUZZY = False      # OCR 표를 읽는 동안만 켠다(머리글 오타: 환을→환율, 증목명→종목명)


def _jamo(s):
    out = []
    for ch in s:
        c = ord(ch)
        if 0xAC00 <= c <= 0xD7A3:
            c -= 0xAC00
            out += [chr(0x1100 + c // 588), chr(0x1161 + (c % 588) // 28)]
            if c % 28:
                out.append(chr(0x11A7 + c % 28))
        else:
            out.append(ch)
    return "".join(out)


def lookup(index, cell):
    n = norm(cell)
    if not n:
        return None
    f = index.get(n)
    if f or not _FUZZY or len(n) < 2:
        return f
    from difflib import SequenceMatcher
    jn = _jamo(n)
    best, bf = 0.0, None
    for alias, fld in index.items():
        if abs(len(alias) - len(n)) > 2:
            continue
        r = SequenceMatcher(None, jn, _jamo(alias)).ratio()
        if r > best:
            best, bf = r, fld
    return bf if best >= 0.8 else None


def _score(row, index):
    return sum(1 for c in row if lookup(index, c))


def _is_date_like(v) -> bool:
    return parse_date(v) is not None


def locate_header(rows, index):
    best, bi = 0, None
    for i, r in enumerate(rows[:60]):
        s = _score(r, index)
        if s > best:
            best, bi = s, i
    if bi is None or best < 3:
        return None
    k = 1
    # 사전 단어가 가장 많은 줄이 머리글 둘째 줄일 수 있다(미래에셋: 거래일자 줄보다 거래번호 줄이 더 많이 맞는다)
    while bi > 0 and k < 3:
        prv = rows[bi - 1]
        if _score(prv, index) >= 2 and not any(_is_date_like(c) for c in prv):
            bi -= 1
            k += 1
        else:
            break
    while k < 3 and bi + k < len(rows):
        nxt = rows[bi + k]
        if _score(nxt, index) >= 2 and not any(_is_date_like(c) for c in nxt):
            k += 1
        elif _textual_header(nxt) and bi + k + 1 < len(rows) and not _textual_header(rows[bi + k + 1]):
            # 사전 단어가 적어도 숫자·날짜 없는 글자 칸이 셋 넘는 줄은 머리글 마지막 줄이다
            # (미래에셋 3줄 머리글의 셋째 줄: 상대금융기관 · 환율 · 처리점 · 처리시각)
            k += 1
            break
        else:
            break
    return bi, k


def _textual_header(row) -> bool:
    vals = [str(c).strip() for c in row if c not in (None, "") and str(c).strip()]
    if len(vals) < 3:
        return False
    return not any(_is_date_like(v) or to_num(v) is not None for v in vals)


_TRADE_DATE = re.compile(r"체결|매매|약정|trade", re.I)


def _map_row(cells, index, used):
    """머리글 줄 하나를 표준 열로 맞춘다. 같은 표준 열에 두 칸이 맞으면 왼쪽 칸을 쓴다.
    예외: 일자 열은 체결일 · 매매일 · 약정일 칸을 거래일자 · 처리일자보다 먼저 쓴다. 일반기업회계기준 6.4의2 와
    법인세법 시행령 제68조①5호(국내 상장주식 양도 귀속)가 모두 체결일 기준이라서다(2026-11-08)."""
    m = {}
    for ci, c in enumerate(cells):
        f = lookup(index, c)
        if not f:
            continue
        if f not in used:
            m[ci] = (f, c)
            used.add(f)
        elif f == "일자" and _TRADE_DATE.search(str(c)):
            old = next(k for k, (g, _) in m.items() if g == "일자")
            if not _TRADE_DATE.search(str(m[old][1])):
                del m[old]
                m[ci] = (f, c)
    return m


def build_table(source, sheet, rows, index):
    loc = locate_header(rows, index)
    if not loc:
        return None
    hi, k = loc
    title = " ".join(str(c) for r in rows[:hi] for c in r if c not in (None, ""))[:300]
    hdr = [rows[hi + j] for j in range(k)]
    # 머리글 줄 사이에 한 칸짜리 줄(한국투자 웹 화면의 '선택' 칸)이 끼면 건너뛰고 다음 머리글 줄을 찾는다
    if k == 1 and hi + 2 < len(rows):
        mid, nxt = rows[hi + 1], rows[hi + 2]
        if sum(1 for c in mid if c not in (None, "")) <= 1 and _score(nxt, index) >= 2 and not any(_is_date_like(c) for c in nxt):
            rows = rows[:hi + 1] + rows[hi + 2:]
            k = 2
            hdr = [rows[hi], rows[hi + 1]]
    width = max(len(r) for r in hdr)
    hdr = [list(r) + [None] * (width - len(r)) for r in hdr]
    data = rows[hi + k:]

    mode = "single"
    if k > 1:
        # 다행 레코드인지(줄마다 머리글 한 줄씩) 묶음 머리글인지 가른다.
        used = set()
        m1 = _map_row(hdr[0], index, used)
        date_col = next((ci for ci, (f, _) in m1.items() if f == "일자"), None)
        nonblank = [r for r in data if any(c not in (None, "") for c in r)]
        if date_col is not None and nonblank:
            # 한 거래가 몇 줄인지: 날짜 줄 사이 간격의 최빈값(빈 줄·쪽 머리 반복 줄은 빼고 센다)
            from collections import Counter
            hdr_norm = [[norm(c) for c in h] for h in hdr]
            body = [r for r in data if any(c not in (None, "") for c in r)
                    and [norm(c) for c in (list(r) + [None] * (width - len(r)))[:width]] not in hdr_norm]
            pos = [i for i, r in enumerate(body) if date_col < len(r) and _is_date_like(r[date_col])]
            gaps = Counter(b - a for a, b in zip(pos, pos[1:]))
            if gaps and gaps.most_common(1)[0][0] == k:
                mode = "multiline"
            else:
                empty = sum(1 for r in nonblank if date_col >= len(r) or not _is_date_like(r[date_col]))
                ratio = empty / len(nonblank)
                if abs(ratio - (k - 1) / k) < 0.2:
                    mode = "multiline"
        if mode != "multiline":
            mode = "combined"

    columns, unmapped = [], []
    if mode in ("single", "multiline"):
        used = set()
        for j in range(k):
            for ci, (f, orig) in _map_row(hdr[j], index, used).items():
                columns.append((ci, j, f, orig))
            for ci, c in enumerate(hdr[j]):
                if c not in (None, "") and not any(cc == ci and jj == j for cc, jj, _, _ in columns):
                    unmapped.append(str(c))
    else:
        used = set()
        for ci in range(width):
            parts = [hdr[j][ci] for j in range(k) if hdr[j][ci] not in (None, "")]
            cands = []
            if parts:
                cands.append("".join(str(p) for p in parts))           # 부모+자식
                cands.append("".join(str(p) for p in reversed(parts)))  # 자식+부모
                cands.append(str(parts[-1]))                          # 자식
                cands.append(str(parts[0]))                           # 부모
            hit = None
            for cnd in cands:
                f = lookup(index, cnd)
                if f and f not in used:
                    hit = (f, cnd)
                    break
            if hit:
                used.add(hit[0])
                columns.append((ci, 0, hit[0], hit[1]))
            elif parts:
                unmapped.append("/".join(str(p) for p in parts))

    t = Table(source, sheet, hi, k, mode, columns, title=title, unmapped=unmapped)
    hdr_norm = [[norm(c) for c in h] for h in hdr]

    def is_header_repeat(r):
        return any([norm(c) for c in (list(r) + [None] * (width - len(r)))[:width]] == h for h in hdr_norm)

    def is_total(r):
        txt = [norm(c) for c in r if c not in (None, "")]
        return bool(txt) and txt[0] in ("합계", "소계", "총계", "누계", "계", "Total")

    i = 0
    step = k if mode == "multiline" else 1
    line_cols = {}
    for ci, j, f, _ in columns:
        line_cols.setdefault(j if mode == "multiline" else 0, []).append((ci, f))
    while i < len(data):
        r = data[i]
        if not any(c not in (None, "") for c in r) or is_header_repeat(r) or is_total(r):
            i += 1
            continue
        rec = {"_row": hi + k + i + 1, "_sheet": sheet}
        lines = [data[i + j] if i + j < len(data) else [] for j in range(step)]
        for j, line in enumerate(lines):
            for ci, f in line_cols.get(j, []):
                if ci < len(line) and line[ci] not in (None, ""):
                    rec[f] = line[ci]
        if parse_date(rec.get("일자")) is None:
            i += 1
            continue
        t.records.append(rec)
        i += step
    return t


def _needs_password(path: Path) -> bool:
    """pikepdf 가 없을 때 pdfplumber 와 함께 깔리는 pdfminer 로 열기 암호가 있는지만 본다."""
    try:
        from pdfminer.pdfdocument import PDFDocument, PDFPasswordIncorrect
        from pdfminer.pdfparser import PDFParser
    except ImportError:
        return False
    with open(path, "rb") as f:
        try:
            PDFDocument(PDFParser(f))
        except PDFPasswordIncorrect:
            return True
        except Exception:
            return False
    return False


def decrypt_pdf(path: Path, password: str | None) -> Path:
    """암호 걸린 PDF(키움: 사업자번호, 미래에셋 거래내역증명서: 생년월일 등)를 임시 사본으로 푼다.
    비밀번호는 파일·로그에 남기지 않는다. 암호가 없으면 원본 경로를 그대로 돌려준다."""
    if path.suffix.lower() != ".pdf":
        return path
    try:
        import pikepdf
    except ImportError:
        # pikepdf 없이 암호 PDF 를 넘기면 pdfplumber 가 원인을 알 수 없는 오류로 멈춘다(2026-11-09 실물)
        if password or _needs_password(path):
            raise SourceError(f"{path.name}: 비밀번호가 걸린 PDF 를 열려면 pikepdf 가 필요하다. "
                              "스킬 폴더에서 pip install pikepdf 로 설치한 뒤, 다시 실행할 때 --password 로 비밀번호를 넘긴다")
        return path
    try:
        with pikepdf.open(str(path)) as pdf:
            if not pdf.is_encrypted:
                return path
    except pikepdf.PasswordError:
        if not password:
            raise SourceError(f"{path.name}: 비밀번호가 걸린 PDF 다. --password 로 비밀번호를 넘긴다")
    tmp = Path(tempfile.mkdtemp(prefix="sec_pdf_")) / path.name
    try:
        with pikepdf.open(str(path), password=password or "") as pdf:
            pdf.save(str(tmp))
    except pikepdf.PasswordError:
        raise SourceError(f"{path.name}: 비밀번호가 맞지 않는다")
    return tmp


def tables_from_sheets(src_name, sheets, ocr_res=None):
    global _FUZZY
    _, index = load_dict()
    out = []
    for name, rows in sheets:
        _FUZZY = name.startswith("ocr")
        try:
            t = build_table(src_name, name, rows, index)
        finally:
            _FUZZY = False
        if t and t.records:
            if name == "ocr":
                t.ocr = ocr_res
            out.append(t)
    return out


def read_tables(path: Path, password: str | None = None):
    global _LAST_OCR
    _LAST_OCR = None
    _, index = load_dict()
    src_name = path.name
    path = decrypt_pdf(path, password)
    sheets, md = read_cells(path)
    tables = []
    global _FUZZY
    for name, rows in sheets:
        _FUZZY = name == "ocr"
        try:
            t = build_table(path.name, name, rows, index)
        finally:
            _FUZZY = False
        if t and t.records:
            if name == "ocr":
                t.ocr = _LAST_OCR
            tables.append(t)
    if not tables:
        raise SourceError(
            f"{path.name}: 머리글(거래일자·거래종류·금액 중 3개 이상)을 찾지 못했다. "
            "열 이름을 references/머리글사전.json 에 넣거나, AI 가 templates/표준거래표_양식.csv 로 옮겨 적는다")
    return tables, md


# ---------------------------------------------------------------- 값 해석 도우미

_DATE_RES = [
    (re.compile(r"^(\d{4})[-./년 ]\s*(\d{1,2})[-./월 ]\s*(\d{1,2})"), "ymd"),
    (re.compile(r"^(\d{4})(\d{2})(\d{2})$"), "ymd"),
    (re.compile(r"^(\d{2})[-./](\d{1,2})[-./](\d{1,2})$"), "yymd"),
    (re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4})"), "mdy"),
]


def parse_date(v):
    if v is None:
        return None
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    s = str(v).strip()
    for rx, kind in _DATE_RES:
        m = rx.match(s)
        if m:
            a, b, c = (int(x) for x in m.groups())
            try:
                if kind == "ymd":
                    return dt.date(a, b, c)
                if kind == "yymd":
                    return dt.date(2000 + a, b, c)
                if kind == "mdy":
                    return dt.date(c, a, b)
            except ValueError:
                return None
    return None


def to_num(v):
    """'1,234.5' '(1,234)' '△12' '-' 를 Decimal 로. 숫자가 아니면 None."""
    from decimal import Decimal, InvalidOperation
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return Decimal(str(v))
    s = str(v).strip().replace(",", "").replace(" ", "")
    for u in ("원", "주", "₩", "$", "USD", "좌"):
        s = s.replace(u, "")
    if s in ("", "-", "--"):
        return None
    neg = False
    if s.startswith("(") and s.endswith(")"):
        neg, s = True, s[1:-1]
    if s.startswith("△") or s.startswith("▲"):
        neg, s = True, s[1:]
    try:
        d = Decimal(s)
    except InvalidOperation:
        return None
    return -d if neg else d
