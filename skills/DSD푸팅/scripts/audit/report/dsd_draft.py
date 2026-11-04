"""원고 판독기(2026-10-26, DSD 네 기능 설계 2.2 · 3.1). dsd · 공시 xml 을 요소 단위 원고로 읽는다.

검증용 판독(dsd_grid)과 따로 둔다. 검증용 판독은 절 · 문단 · 줄바꿈 · 음수 꼴 · 병합 칸 · 테두리 없는 표 · 과목 번호 · FINANCE 두 칸을
버리거나 바꾸지만, 원고는 dsd 로 되돌려 써야 해서 원문을 그대로 둔다.

  요소 하나 = 원고 줄 하나    P · TITLE 은 문단 줄, TR 은 머리 · 줄. 쪼개지 않는다(제목과 본문이 한 P 인 회사 파일도 한 줄)
  글은 원문 그대로           &cr; 는 칸 안 줄바꿈, 연속 공백도 그대로. SPAN 이 든 P 는 「부분 서식」
  병합 칸                    원본 span 이 덮는 칸은 덮인 칸(회색 · 잠금)으로 둔다. 첫 칸 글자를 아래 줄에 채우지 않는다
  숫자 칸                    숫자로 두고 원문 꼴(괄호 · △ 음수, 「-」 0, 쉼표, 끝 「원」 「주」)을 따로 둔다. 외화 · % 칸은 글자 칸
  FINANCE 두 칸              합치지 않는다. 원문 칸 그대로

    d = read(path)          Draft. d.sheets 는 표지 · 정정신고 · 감사보고서 · 재무제표 표지 · 재무제표 · 주석 머리 · 주석N · 외부감사 실시내용 …
"""
from __future__ import annotations

import hashlib
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from .base import norm
from . import dsd, dsd_grid
from .dsd_source import Node, Source, shown

SECTIONS = ("SECTION-1", "SECTION-2", "SECTION-3")
CELLS = ("TD", "TH", "TE", "TU")
SKIP = {"COMMENT", "LIBRARYLIST", "FILENAME", "PGBRK", "TOC", "WARNING", "COLGROUP", "COL", "DOCUMENT-HEADER", "SUMMARY"}


@dataclass
class Cell:
    loc: int | None                  # 요소 위치 번호. None 이면 새 칸 · 덮인 칸
    text: str = ""                   # 원고 글(원문, &cr; → 줄바꿈)
    num: float | None = None         # 숫자 칸 값
    fmt: dict | None = None          # 숫자 원문 꼴
    covered: bool = False            # 원본 병합(span)이 덮는 칸
    span: tuple = (1, 1)             # (ROWSPAN, COLSPAN)
    tag: str = ""

    @property
    def value(self):
        return self.num if self.num is not None else self.text


@dataclass
class Line:
    kind: str                        # 제목 · 문단 · 표 · 글 표 · 머리 · 줄 · 표끝
    loc: int | None
    cells: list = field(default_factory=list)
    partial: bool = False            # SPAN 이 든 P(부분 서식)
    table: int | None = None         # 시트 안 표 차례(1부터)
    tag: str = ""


@dataclass
class Sheet:
    key: str                         # 시트 이름
    title: str
    kind: str                        # 표지 · 절 · 재무제표 표지 · 재무제표 · 주석 머리 · 주석
    lines: list = field(default_factory=list)
    note: int | None = None


@dataclass
class Draft:
    source: str
    sha256: str
    base: str                        # dsd · xml
    sheets: list
    contents: bytes                  # 원문 contents.xml(xml 이면 lenient 로 고친 글)
    meta: bytes = b""
    info: dict = field(default_factory=dict)
    notes: list = field(default_factory=list)      # 원고 안내에 적을 것(롤포워드 못 한 표 등)
    rolled: bool = False

    def sheet(self, key: str) -> Sheet | None:
        return next((s for s in self.sheets if s.key == key), None)


# ---------------------------------------------------------------- 숫자 꼴
_NUMLIKE = re.compile(r"^(?P<pre>\s*)(?P<neg>\(-\)|\(|△|▲|-|−)?\s*(?P<num>\d{1,3}(?:,\d{3})+|\d+)(?P<dec>\.\d+)?\s*(?P<close>\))?(?P<suf>\s*(?:원|주)?)\s*$")
_ZERO = ("-", "–", "−")


def parse_num(text: str) -> tuple[float | None, dict | None]:
    """원고 숫자 칸. (값, 꼴). 숫자로 볼 수 없으면 (None, None). % · 외화 · 날짜 꼴(「2025.12.31」)은 글자 칸이다."""
    t = str(text or "")
    s = t.strip()
    if not s:
        return None, None
    if s in _ZERO:
        return 0, {"zero": s, "raw": t}
    m = _NUMLIKE.match(t)
    if not m:
        return None, None
    neg = m.group("neg") or ""
    if neg == "(" and not m.group("close"):
        return None, None
    if m.group("close") and neg != "(":
        return None, None
    num = m.group("num")
    if "," not in num and len(num) >= 5 and num.startswith("0"):
        return None, None                                   # 앞자리 0 이 있는 코드
    v = float(num.replace(",", "") + (m.group("dec") or ""))
    style = {"(": "paren", "(-)": "paren-minus", "△": "tri", "▲": "tri-b", "-": "minus", "−": "minus-u"}.get(neg, "")
    v = -v if style else v
    v = int(v) if v == int(v) and not m.group("dec") else v
    return v, {"neg": style, "comma": "," in num, "dec": len(m.group("dec") or "") - 1 if m.group("dec") else 0,
               "suf": (m.group("suf") or "").strip(), "raw": t}


def format_num(v, fmt: dict | None) -> str:
    """원문 꼴로 숫자를 글로. 꼴이 없으면 쉼표 · 괄호 음수."""
    f = fmt or {"neg": "paren", "comma": True, "dec": 0, "suf": ""}
    if v in (None, ""):
        return ""
    if v == 0 and f.get("zero"):
        return f["zero"]
    if v == 0 and not f.get("neg") and f.get("raw", "").strip() in _ZERO:
        return f["raw"].strip()
    dec = f.get("dec") or 0
    a = abs(float(v))
    body = f"{a:,.{dec}f}" if f.get("comma", True) else f"{a:.{dec}f}"
    if v < 0:
        style = f.get("neg") or "paren"
        body = {"paren": f"({body})", "paren-minus": f"(-){body}", "tri": f"△{body}", "tri-b": f"▲{body}", "minus-u": f"−{body}"}.get(style, f"-{body}")
    return body + (f.get("suf") or "")


def excel_format(fmt: dict | None) -> str:
    """원고 엑셀 숫자 칸 표시 꼴. 원문처럼 보이게(괄호 · △ 음수, 「-」 0, 끝 글자)."""
    f = fmt or {}
    dec = f.get("dec") or 0
    base = ("#,##0" if f.get("comma", True) else "0") + (("." + "0" * dec) if dec else "")
    suf = f'"{f["suf"]}"' if f.get("suf") else ""
    neg = {"paren": f"({base}{suf})", "paren-minus": f'"(-)"{base}{suf}', "tri": f'"△"{base}{suf}', "tri-b": f'"▲"{base}{suf}',
           "minus": f"-{base}{suf}", "minus-u": f'"−"{base}{suf}'}.get(f.get("neg") or "paren", f"({base}{suf})")
    zero = f'"{f["zero"]}"' if f.get("zero") else f"{base}{suf}"
    return f"{base}{suf};{neg};{zero}"


# ---------------------------------------------------------------- 읽기
def _raw(path: Path) -> tuple[bytes, bytes, str]:
    path = Path(path)
    if path.suffix.lower() == ".xml":
        return dsd.lenient_xml(path.read_bytes()), b"", "xml"
    with zipfile.ZipFile(path) as z:
        name = next((n for n in z.namelist() if n.lower().endswith("contents.xml")), None)
        if name is None:
            raise ValueError(f"dsd 안에 contents.xml 이 없습니다: {path}")
        meta = next((n for n in z.namelist() if n.lower().endswith("meta.xml")), None)
        return z.read(name), (z.read(meta) if meta else b""), "dsd"


def _cell(src: Source, n: Node) -> Cell:
    text = shown(src.text(n))
    num, fmt = parse_num(text)
    if num is not None and n.kids:
        num, fmt = None, None                      # 칸 안에 요소가 든 칸은 글자로 둔다
    rs, cs = int(n.get("ROWSPAN") or 1), int(n.get("COLSPAN") or 1)
    return Cell(n.k, text, num, fmt, span=(max(rs, 1), max(cs, 1)), tag=n.tag)


def _table_lines(src: Source, t: Node, no: int) -> list[Line]:
    """표 하나: 「표」 줄, 머리 · 줄, 「표끝」 줄. 병합 칸은 덮인 칸으로 펼친다."""
    trs = []
    for sec in t.kids:
        if sec.tag in ("THEAD", "TBODY"):
            trs += [("머리" if sec.tag == "THEAD" else "줄", tr) for tr in sec.findall("TR")]
    grid: list[list] = []
    taken: dict = {}
    for r, (_, tr) in enumerate(trs):
        row: list = []
        c = 0
        for n in tr.kids:
            if n.tag not in CELLS:
                continue
            while (r, c) in taken:
                row.append(Cell(None, covered=True))
                c += 1
            cell = _cell(src, n)
            row.append(cell)
            rs, cs = cell.span
            for dr in range(rs):
                for dc in range(cs):
                    if dr or dc:
                        taken[(r + dr, c + dc)] = True
            for _ in range(cs - 1):
                c += 1
                row.append(Cell(None, covered=True))
            c += 1
        while (r, c) in taken:
            row.append(Cell(None, covered=True))
            c += 1
        grid.append(row)
    width = max((len(r) for r in grid), default=0)
    border = (t.get("BORDER") or "1").strip()
    kind = "글 표" if border == "0" else "표"
    head = [Cell(None, f"[표 {no}] {t.get('ACLASS') or 'NORMAL'} · 테두리 {'없음' if border == '0' else '있음'}")]
    out = [Line(kind, t.k, head, table=no, tag="TABLE")]
    for (k, tr), row in zip(trs, grid):
        row = row + [Cell(None, covered=True) for _ in range(width - len(row))]
        out.append(Line(k, tr.k, row, table=no, tag="TR"))
    out.append(Line("표끝", None, [], table=no))
    return out


def _p_line(src: Source, n: Node, kind: str = "문단") -> Line:
    text = shown(src.text(n))
    partial = any(c.tag == "SPAN" for c in n.kids)
    if kind == "문단" and dsd._bold_level(n.get("USERMARK")) and not partial:
        kind = "제목"
    return Line(kind, n.k, [Cell(n.k, text, tag=n.tag)], partial=partial, tag=n.tag)


class _Walker:
    def __init__(self, src: Source):
        self.src = src
        self.lines: list[Line] = []
        self.ntab = 0

    def walk(self, e: Node, stop_sections: bool = False):
        for c in e.kids:
            if c.tag in SKIP:
                continue
            if c.tag in SECTIONS:
                if stop_sections:
                    continue
                t = c.find("TITLE")
                if t is not None:
                    self.lines.append(_p_line(self.src, t, "제목"))
                self.walk(c)
            elif c.tag in ("TITLE", "COVER-TITLE"):
                self.lines.append(_p_line(self.src, c, "제목"))
            elif c.tag == "P":
                self.lines.append(_p_line(self.src, c))
            elif c.tag == "SPAN":
                self.lines.append(_p_line(self.src, c))
            elif c.tag == "TABLE":
                self.ntab += 1
                self.lines.extend(_table_lines(self.src, c, self.ntab))
            elif c.tag in ("INSERTION", "LIBRARY", "PART", "TABLE-GROUP", "COVER", "CORRECTION"):
                self.walk(c, stop_sections)


def _lines_of(src: Source, e: Node, stop_sections: bool = False) -> list[Line]:
    w = _Walker(src)
    w.walk(e, stop_sections)
    return w.lines


def _renumber_tables(lines: list[Line]) -> list[Line]:
    """시트 안 표 차례를 다시 매긴다(시트를 나눈 뒤)."""
    k, cur = 0, None
    for ln in lines:
        if ln.kind in ("표", "글 표"):
            k += 1
            cur = k
            ln.cells[0].text = re.sub(r"^\[표 \d+\]", f"[표 {k}]", ln.cells[0].text)
        if ln.table is not None:
            ln.table = cur
    return lines


def _statement_of(ln: Line) -> str | None:
    """재무제표 제목 줄이면 그 이름(짧은 제목 · 표 첫 칸)."""
    if ln.kind in ("제목", "문단"):
        text = ln.cells[0].text
    elif ln.kind == "줄" and ln.cells:
        text = next((c.text for c in ln.cells if c.text.strip()), "")
    else:
        return None
    t = norm(text)
    if len(t) > 40:
        return None
    for key, names in dsd_grid.STATEMENTS:
        if any(n in t for n in names) and not ("주석" in t or "일부입니다" in t or "작성한것" in t):
            return key
    return None


def _split_fs(lines: list[Line]) -> list[Sheet]:
    out: list[Sheet] = [Sheet("재무제표 표지", "재무제표 표지", "재무제표 표지")]
    i = 0
    while i < len(lines):
        ln = lines[i]
        st = _statement_of(ln)
        if st:
            start = i
            if ln.kind == "줄":                                # 표 첫 칸 제목: 그 표의 「표」 줄부터 새 시트
                while start > 0 and lines[start].kind not in ("표", "글 표"):
                    start -= 1
            moved = lines[start:i]
            del out[-1].lines[len(out[-1].lines) - len(moved):]
            prev = next((s for s in out if s.key == st), None)
            cur = prev or Sheet(st, st, "재무제표")
            if prev is None:
                out.append(cur)
            elif out[-1] is not prev:
                out.remove(prev)
                out.append(prev)
            cur.lines.extend(moved)
            cur.lines.append(ln)
            i += 1
            continue
        out[-1].lines.append(ln)
        i += 1
    return [s for s in out if s.lines]


def _split_notes(lines: list[Line]) -> list[Sheet]:
    """주석 절: 주석 머리와 주석N. 주석 제목은 검증용 판독과 같은 규칙(dsd_grid._note_starts)으로 고른다."""
    blocks: list = [("h", 1, dsd_grid.NOTES)]
    at: list[int] = []
    for i, ln in enumerate(lines):
        if ln.kind in ("제목", "문단"):
            t = re.sub(r"\s+", " ", ln.cells[0].text.replace("\n", " ")).strip()
            blocks.append(("h", 3, t) if ln.kind == "제목" else ("p", t))
            at.append(i)
    starts = dsd_grid._note_starts(blocks)
    begin = {at[b - 1]: v for b, v in starts.items()}
    out = [Sheet("주석 머리", "주석 첫머리", "주석 머리")]
    for i, ln in enumerate(lines):
        if i in begin:
            n, title, _ = begin[i]
            out.append(Sheet(f"주석{n}", title, "주석", note=n))
        out[-1].lines.append(ln)
    return [s for s in out if s.lines]


def _fs_title(title: str) -> bool:
    return dsd.part_of(title) in ("(첨부) 재무제표", "주석") or dsd_grid.section_of(title) in (dsd_grid.FS, dsd_grid.NOTES)


def _is_notes(title: str) -> bool:
    return dsd.part_of(title) == "주석" or dsd_grid.section_of(title) == dsd_grid.NOTES


def _sections(src: Source) -> list[Sheet]:
    out: list[Sheet] = []
    used: dict = {}

    def add(sheet: Sheet):
        base = sheet.key
        n = used.get(base, 0) + 1
        used[base] = n
        if n > 1:
            sheet.key = f"{base}({n})"
        out.append(sheet)

    def title_of(e: Node) -> str:
        t = e.find("TITLE")
        return re.sub(r"\s+", " ", src.text(t)).strip() if t is not None else ""

    def fs(e: Node):
        """재무제표 절: 표지 · 재무제표 넷(다섯) 시트, 안의 주석 절은 주석 시트로."""
        lines = _lines_of(src, e, stop_sections=True)
        for sh in _split_fs(lines):
            add(sh)
        for sub in e.iter():
            if sub is not e and sub.tag in SECTIONS and _is_notes(title_of(sub)):
                notes(sub)
                break

    def notes(e: Node):
        t = e.find("TITLE")
        skip = t.k if t is not None else -1                 # 「주석」 절 제목 줄은 원고에 두지 않는다(시트 이름이 대신한다)
        lines = [ln for ln in _lines_of(src, e) if ln.loc != skip]
        for sh in _split_notes(lines):
            add(sh)

    def walk(e: Node):
        for c in e.kids:
            if c.tag == "COVER":
                add(Sheet("표지", "표지", "표지", _lines_of(src, c)))
            elif c.tag == "CORRECTION":
                add(Sheet("정정신고", title_of(c) or "정정신고", "절", _lines_of(src, c)))
            elif c.tag in SECTIONS:
                title = title_of(c)
                if _fs_title(title):
                    if _is_notes(title):
                        notes(c)
                    else:
                        fs(c)
                    continue
                p = dsd.part_of(title)
                key = p if p in ("감사보고서", "외부감사 실시내용") else (title or "제목 없는 절")
                if "검토보고서" in norm(title):
                    key = "검토보고서"
                add(Sheet(key[:28], title, "절", _lines_of(src, c)))
            elif c.tag in ("INSERTION", "LIBRARY", "PART"):
                walk(c)

    body = src.root.find("BODY") if src.root is not None else None
    if body is not None:
        walk(body)
    for s in out:
        _renumber_tables(s.lines)
    return out


def _info(src: Source, sheets: list[Sheet]) -> dict:
    root = src.root
    name = ""
    for tag in ("COMPANY-NAME",):
        for n in root.iter():
            if n.tag == tag:
                name = src.text(n).strip()
                break
    doc = next((src.text(n).strip() for n in root.iter() if n.tag == "DOCUMENT-NAME"), "")
    cover = next((s for s in sheets if s.key == "표지"), None)
    term = None
    unit = ""
    if cover:
        for ln in cover.lines:
            for c in ln.cells:
                m = re.search(r"제\s*(\d+)\s*기", c.text)
                if m and term is None:
                    term = int(m.group(1))
    for s in sheets:
        for ln in s.lines:
            for c in ln.cells:
                m = dsd_grid._UNIT.search(c.text)
                if m and not unit:
                    unit = m.group(1)
    dates = [n.get("AUNITVALUE") for n in root.iter() if n.tag == "TU" and n.get("AUNIT", "").startswith("PERIODTO")]
    summary = {n.get("ACODE"): src.text(n).strip() for n in root.iter() if n.tag == "EXTRACTION" and n.parent is not None and n.parent.tag == "SUMMARY"}
    return {"name": name, "document": doc, "term": term, "period_end": dates[0] if dates else "", "unit": unit, "summary": summary}


def from_raw(raw: bytes, meta: bytes = b"", base: str = "dsd", name: str = "", sha256: str = "") -> Draft:
    src = Source(raw)
    sheets = _sections(src)
    return Draft(name, sha256 or hashlib.sha256(raw).hexdigest(), base, sheets, raw, meta, _info(src, sheets))


def read(path: Path) -> Draft:
    raw, meta, base = _raw(path)
    return from_raw(raw, meta, base, Path(path).name, hashlib.sha256(Path(path).read_bytes()).hexdigest())


def cell_index(d: Draft) -> dict:
    """위치 번호 → (시트 key, 줄 차례, 칸 차례, Cell). 문단은 칸 0."""
    out = {}
    for s in d.sheets:
        for i, ln in enumerate(s.lines):
            for j, c in enumerate(ln.cells):
                if c.loc is not None:
                    out[c.loc] = (s.key, i, j, c)
    return out


# ---------------------------------------------------------------- 롤포워드(--roll, 설계 3.1)
_TERM = re.compile(r"(제\s*)(\d+)(\s*(?:\(\s*[당전]\s*\))?\s*기)")
_YEAR = re.compile(r"(?<!\d)((?:19|20)\d{2})(?=\s*(?:년|[.\-/]\s*\d{1,2}))")
_CUR = re.compile(r"당\s*(?:기말|기|반기말|반기|분기말|분기)|\(\s*당\s*\)")
_PRI = re.compile(r"전\s*(?:기말|기|반기말|반기|분기말|분기)|\(\s*전\s*\)")


def bump(text: str, years: int = 1) -> str:
    """기수 +1(「제 5 (당) 기」 → 「제 6 (당) 기」), 날짜의 해 +1(「2025년 12월 31일」 · 「2025.12.31」)."""
    t = _TERM.sub(lambda m: f"{m.group(1)}{int(m.group(2)) + years}{m.group(3)}", str(text))
    return _YEAR.sub(lambda m: str(int(m.group(1)) + years), t)


def _blocks(lines: list[Line]) -> list[tuple[int, int]]:
    out, i = [], 0
    while i < len(lines):
        if lines[i].kind in ("표", "글 표"):
            j = i + 1
            while j < len(lines) and lines[j].kind != "표끝":
                j += 1
            out.append((i, j))
            i = j
        i += 1
    return out


def _head_rows(rows: list[Line]) -> int:
    """표 머리 줄 수: 「머리」 줄, 없으면 숫자가 처음 나오는 줄 앞까지."""
    k = sum(1 for ln in rows if ln.kind == "머리")
    if k:
        return k
    for i, ln in enumerate(rows):
        if any(c.num is not None for c in ln.cells[1:]):
            return i
    return 0


def period_columns(rows: list[Line], head: int, term: int | None, fy: int | None) -> tuple[list[int], list[int]]:
    """머리 줄 글로 당기 · 전기 열. 병합으로 덮인 머리 칸은 왼쪽 칸 글을 따른다."""
    width = max((len(ln.cells) for ln in rows), default=0)
    names = [""] * width
    for ln in rows[:head]:
        last = ""
        for j in range(width):
            c = ln.cells[j] if j < len(ln.cells) else Cell(None, covered=True)
            t = c.text if not c.covered else last
            last = t if not c.covered else last
            names[j] = (names[j] + " " + t).strip()
    cur, pri = [], []
    for j in range(1, width):
        h = names[j]
        terms = [int(x) for x in re.findall(r"제\s*(\d+)\s*(?:\(\s*[당전]\s*\))?\s*기", h)]
        years = [int(x) for x in re.findall(r"(?<!\d)((?:19|20)\d{2})(?!\d)", h)]
        if _CUR.search(h) or (term and term in terms) or (fy and fy in years and not _PRI.search(h)):
            cur.append(j)
        elif _PRI.search(h) or (term and term - 1 in terms) or (fy and fy - 1 in years):
            pri.append(j)
    return cur, pri


_LABEL_PERIOD = re.compile(r"(?:^|[\s(<\[〈①-⑳\d)])(당|전)\s*(반기|분기|기)(말)?(?![가-힣])")


def _row_key(ln: Line, skip: int = 0) -> str:
    return norm(next((c.text for c in ln.cells[skip:] if not c.covered and c.num is None and c.text.strip()), ""))


def _copy_rows(cur: list[Line], pri: list[Line], skip: int = 0) -> tuple[int, list[str]]:
    """당기 줄의 숫자 칸을 이름이 같은 전기 줄로 옮기고 당기 숫자 칸을 비운다. (옮긴 줄 수, 전기에 없는 당기 줄 이름)."""
    by = {}
    for ln in pri:
        by.setdefault(_row_key(ln, skip), ln)
    moved, missing = 0, []
    for ln in cur:
        k = _row_key(ln, skip)
        dst = by.get(k)
        nums = [j for j, c in enumerate(ln.cells) if c.num is not None or (not c.text.strip() and not c.covered and j >= skip + 1)]
        if dst is None:
            if any(ln.cells[j].num is not None for j in nums):
                missing.append(k)
            for j in nums:
                ln.cells[j].text, ln.cells[j].num = "", None
            continue
        for j in nums:
            if j >= len(dst.cells) or dst.cells[j].covered:
                continue
            c, t = ln.cells[j], dst.cells[j]
            if c.num is None and t.num is None and not c.text.strip():
                continue
            t.text, t.num, t.fmt = c.text, c.num, c.fmt or t.fmt
            c.text, c.num = "", None
        moved += 1
    return moved, missing


def _period_of_text(text: str) -> str | None:
    m = _LABEL_PERIOD.search(text[:40])
    return None if not m else ("cur" if m.group(1) == "당" else "pri")


def roll(d: Draft) -> Draft:
    """작년 판 원고를 당기 초안으로: 당기 숫자를 전기 칸으로 옮기고 당기 칸을 비운다. 머리줄 기수 · 해 +1, 표지 · 재무제표 머리 표 · TU 날짜 +1.
    당기 · 전기를 두는 꼴 셋을 옮긴다: 열(「당기말 · 전기말」 열), 한 표 안 줄 묶음(첫 열 「당기 · 전기」 병합 칸), 따로 둔 두 표(표 위 문단 「당기 · 전기」).
    문단 속 날짜는 바꾸지 않는다(문장 검토가 작년 날짜를 잡는다). 정하지 못한 표는 손대지 않고 notes 에 적는다.
    1차에서 뺀다: 자본변동표(두 해를 위아래 줄 묶음으로 둔다), 반기 · 분기 보고서(재무상태표 비교가 직전 사업연도 말이다)."""
    doc = norm(d.info.get("document") or "")
    if "반기" in doc or "분기" in doc:
        d.notes.append("반기 · 분기 보고서는 1차에서 롤포워드하지 않는다(재무상태표 비교 기간이 직전 사업연도 말이라 +1년 규칙이 맞지 않는다)")
        return d
    term = d.info.get("term")
    end = str(d.info.get("period_end") or "")
    fy = int(end[:4]) if re.fullmatch(r"\d{8}", end) else None
    rolled = []
    for s in d.sheets:
        blocks = _blocks(s.lines)
        done: set = set()
        if s.kind in ("재무제표", "주석"):
            # 따로 둔 두 표: 표 위 세 줄 안의 문단이 「당기 · 전기」
            tagged = []
            start_of = {b: a for a, b in blocks}

            def unit_only(a, b):
                rows = [ln for ln in s.lines[a + 1:b] if ln.kind in ("머리", "줄")]
                texts = [c.text for ln in rows for c in ln.cells if c.text.strip()]
                return len(texts) == 1 and bool(dsd_grid._UNIT.search(texts[0])) and len(norm(texts[0])) <= 14

            for a, b in blocks:
                per = None
                if not any(c.num is not None for ln in s.lines[a + 1:b] for c in ln.cells):
                    tagged.append((a, b, None))
                    continue
                k = a - 1
                seen = 0
                while k >= 0 and seen < 4:
                    ln = s.lines[k]
                    if ln.kind == "표끝" and k in start_of and unit_only(start_of[k], k):
                        k = start_of[k] - 1                            # 「(단위 : 원)」 한 칸 표는 건너뛴다
                        continue
                    if ln.kind in ("표끝", "표", "글 표", "머리", "줄"):
                        break
                    seen += 1
                    if ln.kind in ("문단", "제목") and ln.cells and ln.cells[0].text.strip():
                        t = re.sub(r"\s+", " ", ln.cells[0].text).strip()
                        if not (dsd_grid._UNIT.search(t) and len(norm(t)) <= 14):
                            per = _period_of_text(t)
                            break
                    k -= 1
                tagged.append((a, b, per))
            for i, (a, b, per) in enumerate(tagged):
                if per != "cur" or (a, b) in done:
                    continue
                mate = next(((x, y) for x, y, q in tagged[i + 1:] if q == "pri" and (x, y) not in done), None)
                if mate is None:
                    continue
                rows_c = [ln for ln in s.lines[a + 1:b] if ln.kind in ("머리", "줄")]
                rows_p = [ln for ln in s.lines[mate[0] + 1:mate[1]] if ln.kind in ("머리", "줄")]
                hc, hp = _head_rows(rows_c), _head_rows(rows_p)
                if [_row_key(x) for x in rows_c[:hc]] != [_row_key(x) for x in rows_p[:hp]]:
                    continue
                moved, missing = _copy_rows(rows_c[hc:], rows_p[hp:])
                done |= {(a, b), mate}
                name = f"{s.key} 표 {s.lines[a].table} → 표 {s.lines[mate[0]].table}"
                if missing:
                    d.notes.append(f"{name}: 전기 표에 없는 당기 줄은 옮기지 못하고 비웠다({', '.join(missing[:5])})")
                rolled.append({"sheet": s.key, "table": s.lines[a].table, "loc": s.lines[a].loc, "mode": "표",
                               "cells": [c.loc for ln in rows_c[hc:] for c in ln.cells if c.loc is not None and c.fmt is not None]})
        for a, b in blocks:
            if (a, b) in done:
                continue
            rows = [ln for ln in s.lines[a + 1:b] if ln.kind in ("머리", "줄")]
            head_kind = s.lines[a].kind
            name = f"{s.key} 표 {s.lines[a].table}"
            if s.kind in ("표지", "재무제표 표지", "주석 머리") or (s.kind == "재무제표" and head_kind == "글 표"):
                for ln in rows:
                    for c in ln.cells:
                        if not c.covered and c.num is None:
                            c.text = bump(c.text)
                continue
            if s.kind not in ("재무제표", "주석"):
                continue
            has_num = any(c.num is not None for ln in rows for c in ln.cells)
            if not has_num:
                continue
            if s.key == "자본변동표":
                d.notes.append(f"{name}: 자본변동표는 1차에서 옮기지 않는다(두 해를 위아래 줄 묶음으로 둔다)")
                continue
            head = _head_rows(rows)
            body = rows[head:]
            # 한 표 안 줄 묶음: 첫 열 병합 칸이 「당기」 · 「전기」
            groups, cur_g = {}, None
            for ln in body:
                c0 = ln.cells[0] if ln.cells else None
                if c0 is not None and not c0.covered and c0.text.strip():
                    cur_g = _period_of_text(c0.text) if len(norm(c0.text)) <= 6 else None
                    if cur_g is None:
                        groups = {}
                        break
                if cur_g:
                    groups.setdefault(cur_g, []).append(ln)
            if set(groups) == {"cur", "pri"}:
                moved, missing = _copy_rows(groups["cur"], groups["pri"], skip=1)
                if missing:
                    d.notes.append(f"{name}: 전기 묶음에 없는 당기 줄은 옮기지 못하고 비웠다({', '.join(missing[:5])})")
                for ln in rows[:head]:
                    for c in ln.cells:
                        if not c.covered:
                            c.text = bump(c.text)
                rolled.append({"sheet": s.key, "table": s.lines[a].table, "loc": s.lines[a].loc, "mode": "줄 묶음",
                               "cells": [c.loc for ln in groups["cur"] for c in ln.cells if c.loc is not None and c.fmt is not None]})
                continue
            cur, pri = period_columns(rows, head, term, fy)
            if not cur or len(cur) != len(pri):
                d.notes.append(f"{name}: 당기 · 전기 칸을 찾지 못해 옮기지 않았다(당기 {len(cur)}열 · 전기 {len(pri)}열)")
                continue
            for ln in rows[:head]:
                for c in ln.cells:
                    if not c.covered:
                        c.text = bump(c.text)
            cells = []
            for ln in body:
                for cj, pj in zip(cur, pri):
                    if cj >= len(ln.cells) or pj >= len(ln.cells):
                        continue
                    c, p = ln.cells[cj], ln.cells[pj]
                    if c.covered or p.covered:
                        continue
                    p.text, p.num, p.fmt = c.text, c.num, c.fmt if c.fmt else p.fmt
                    c.text, c.num = "", None
                    if c.loc is not None and c.fmt is not None:
                        cells.append(c.loc)
            rolled.append({"sheet": s.key, "table": s.lines[a].table, "loc": s.lines[a].loc, "mode": "열", "cells": cells})
    d.rolled = True
    d.info["rolled_tables"] = rolled
    if term:
        d.info["term"] = term + 1
    if fy:
        d.info["period_end"] = f"{fy + 1}{end[4:]}"
    return d
