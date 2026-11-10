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
    unit: str = ""                   # TU 칸의 AUNIT(PERIODFROM · SUB_PERIODTO 등)

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
    # 세 자리 이하 원문은 쉼표 꼴을 알 수 없다. 쉼표로 둔다(「(120)」 칸에 4,321 을 쓰면 「(3157)」 이 됐다, 2026-11-06 D8)
    return v, {"neg": style, "comma": "," in num or len(num) <= 3, "dec": len(m.group("dec") or "") - 1 if m.group("dec") else 0,
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
    raw = f.get("raw") or ""
    m = _NUMLIKE.match(raw) if "\n" in raw else None
    if m:                                  # 「12,345⏎주⏎」 처럼 칸 안 줄바꿈이 든 원문은 숫자만 바꾸고 줄바꿈 · 끝 글자를 둔다(2026-11-06 D3)
        a = m.start("neg") if m.group("neg") else m.start("num")
        b = max(m.end(g) for g in ("num", "dec", "close") if m.group(g))
        return raw[:a] + body + raw[b:]
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
    if num is not None and n.kids and not all(k.tag == "SPAN" and not k.kids for k in n.kids):
        num, fmt = None, None                      # 칸 안에 요소가 든 칸은 글자로 둔다. 「12,345<SPAN>주</SPAN>」 처럼 SPAN 만 든 칸은 숫자다(2026-11-06 D3)
    rs, cs = int(n.get("ROWSPAN") or 1), int(n.get("COLSPAN") or 1)
    return Cell(n.k, text, num, fmt, span=(max(rs, 1), max(cs, 1)), tag=n.tag, unit=n.get("AUNIT") or "")


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
                self.walk(c)                                 # 절 제목(TITLE)은 절 안을 돌 때 한 번 들어간다. 따로 넣으면 원고에 두 줄이 되어 dsd 에 제목이 두 번 쓰였다(2026-11-06)
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
# 「당기손익-공정가치 측정」 「당기순이익」 의 당기는 기간이 아니다. 금융상품 범주 열을 당기 열로 세어 열이 엇갈려 옮겨졌다(2026-11-07 한 회사 주석5)
_CUR = re.compile(r"당\s*(?:기말|기(?!\s*(?:손익|순이익|순손익|순손실|법인세|손실|이익))|반기말|반기|분기말|분기)|\(\s*당\s*\)")
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


_RATE = re.compile(r"율|률|%")


def head_names(rows: list[Line], head: int, sep: str = " ") -> list[str]:
    """열마다 머리 줄 글. 가로 병합(COLSPAN)으로 덮인 칸은 왼쪽 칸 글을 따르고, 세로 병합(ROWSPAN)으로 위에서 덮인 칸은 보태지 않는다.
    둘을 가리지 않아 「당기말(두 줄) | 전기말(두 줄)」 아래 줄의 「이자율(%)」 이 두 열 이름에 붙어 율 열로 빠졌다(2026-11-09 차입금 표).
    sep 은 머리 줄 사이 글. 기간을 읽을 때는 「 | 」 로 이어 아래 줄 글이 윗줄 기간 말에 붙지 않게 한다."""
    width = max((len(ln.cells) for ln in rows), default=0)
    names = [""] * width
    for ln in rows[:head]:
        owner: dict = {}
        for j, c in enumerate(ln.cells[:width]):
            if not c.covered:
                for k in range(j, j + max(c.span[1] if c.span else 1, 1)):
                    owner[k] = c.text
        for j in range(width):
            c = ln.cells[j] if j < len(ln.cells) else Cell(None, covered=True)
            if c.covered and j not in owner:
                continue
            t = owner[j] if c.covered else c.text
            names[j] = (names[j] + sep + t).strip() if names[j] else t.strip()
    return names


def period_columns(rows: list[Line], head: int, term: int | None, fy: int | None) -> tuple[list[int], list[int]]:
    """머리 줄 글로 당기 · 전기 열. 「당기말이자율(%)」 처럼 율 · % 열은 금액 열이 아니라 세지 않는다(2026-11-06 D6)."""
    names = head_names(rows, head)
    split = head_names(rows, head, sep=" | ")      # 「당기 | 법인세효과」: 아래 줄 「법인세효과」 가 「당기」 에 붙으면 당기법인세로 읽어 열을 뺐다(2026-11-09)
    cols = []
    for j in range(1, len(names)):
        h, hs = names[j], split[j]
        if _RATE.search(h) and not re.fullmatch(r"[당전]기(?:말|초)?\(%\)", norm(h)):
            continue                      # 「당기말(%)」 처럼 율만 적은 기간 열은 센다(2026-11-07 한 회사 주석18 할인율 표)
        # 「제 6전) 기」 처럼 여는 괄호가 빠진 원문도 기수로 읽는다(2026-11-10 처음 보는 회사 세트 현금흐름표: 전기 열을 못 찾아 표를 그대로 두었다)
        cols.append((j, h, hs, [int(x) for x in re.findall(r"제\s*(\d+)\s*(?:\(?\s*[당전]\s*\)?)?\s*기", h)]))
    # 원문 오타가 두 가지다. 기수는 맞고 글자가 틀린 원문(전기 열 「제 06(당) 기」 · 「제7(당)기」)과, 글자는 맞고 기수가 작년 것인 원문(현금흐름표만
    # 「제 11(당) 기 | 제 10(전) 기」, 표지는 제 12 기)이 있었다(2026-11-10 처음 보는 회사 세트). 글자로 먼저 읽고, 당기 · 전기 짝이 서지 않을 때만
    # 기수로 다시 읽는다. 표지에서 기수를 읽지 못했으면 머리의 기수가 둘이고 1 차이일 때 큰 쪽이 당기다
    def by_word():
        c, p = [], []
        for j, h, hs, terms in cols:
            years = [int(x) for x in re.findall(r"(?<!\d)((?:19|20)\d{2})(?!\d)", h)]
            if _CUR.search(hs) or (term and term in terms) or (fy and fy in years and not _PRI.search(hs)):
                c.append(j)
            elif _PRI.search(hs) or (term and term - 1 in terms) or (fy and fy - 1 in years):
                p.append(j)
        return c, p

    cur, pri = by_word()
    if cur and pri and len(cur) == len(pri):
        return cur, pri
    t = term
    if not t:
        seen = sorted({x for *_, ts in cols for x in ts})
        t = seen[1] if len(seen) == 2 and seen[1] - seen[0] == 1 else None
    c2 = [j for j, *_, ts in cols if t and t in ts and t - 1 not in ts]
    p2 = [j for j, *_, ts in cols if t and t - 1 in ts and t not in ts]
    if c2 and p2 and len(c2) == len(p2):
        return c2, p2
    return cur, pri


_UNIT_CELL = re.compile(r"^\s*\(?\s*단\s*위\s*[:：]")
_UNIT_TEXT = re.compile(r"[(（]?\s*단\s*위\s*[:：][^)）]*[)）]?")


def _unit_like(t: str) -> bool:
    """「(단위: 원)」 · 「(단위: USD, JPY ,원)」 · 「(단위: 주, 원)」 처럼 단위만 적은 칸. dsd_grid._UNIT 은 원 · 천원 · 백만원만 본다(2026-11-06 D5)."""
    return bool(dsd_grid._UNIT.search(t) or _UNIT_CELL.match(t or "")) and len(norm(t)) <= 24


_LABEL_PERIOD = re.compile(r"(?:^|[\s(<\[〈①-⑳\d)])(당|전)\s*(반기|분기|기)(말)?(?![가-힣])")


def _row_key(ln: Line, skip: int = 0) -> str:
    return norm(next((c.text for c in ln.cells[skip:] if not c.covered and c.num is None and c.text.strip()), ""))


def _label_texts(lines: list[Line], skip: int = 0) -> list[list[str]]:
    """줄마다 이름 칸 글(숫자가 아닌 글 칸, 열 차례). 위 줄의 세로 병합 칸에 덮인 칸은 그 병합 칸 글로 채운다.
    「외화예금(세로 병합) | USD」 묶음의 둘째 줄도 「외화예금 | JPY」 가 된다. 묶음 이름만 보면 당기 「외화예금 | USD」 줄이
    전기 「외화예금 | CNY」 줄로 옮겨졌다(2026-11-10 초안 검산 시험)."""
    out, active = [], {}                      # active: 열 → [아래로 남은 줄 수, 글]
    for ln in lines:
        texts, used, started = [], set(), {}
        for j, c in enumerate(ln.cells):
            if c.covered:
                a = active.get(j)
                if a is not None and j >= skip and id(a) not in used:
                    used.add(id(a))
                    if a[1]:
                        texts.append(a[1])
                continue
            t = norm(c.text) if c.num is None else ""
            if t and j >= skip:
                texts.append(t)
            if c.span[0] > 1:
                a = [c.span[0] - 1, t]
                for dc in range(max(1, c.span[1])):
                    started[j + dc] = a
        for a in {id(a): a for a in active.values()}.values():     # 여러 열을 덮는 병합 칸도 줄마다 한 번만 줄인다
            a[0] -= 1
        active = {j: a for j, a in active.items() if a[0] > 0}
        active.update(started)
        out.append(texts)
    return out


def _row_keys(cur: list[Line], pri: list[Line], skip: int = 0) -> tuple[list[str], list[str]]:
    """두 묶음의 줄 이름. 첫 글자 칸이 같은 줄이 있으면(「보통예금 | USD」 · 「보통예금 | JPY」) 앞 두 글자 칸으로 가르고,
    그래도 같으면 차례 번호를 붙인다. 첫 칸만 보면 둘째 줄이 첫째 줄 자리로 옮겨졌다(2026-11-06 실제 회사 시험 D5).
    세로 병합으로 묶은 줄은 묶음 이름부터 센다(_label_texts, 2026-11-10)."""
    tc, tp = _label_texts(cur, skip), _label_texts(pri, skip)
    base_c, base_p = [x[0] if x else "" for x in tc], [x[0] if x else "" for x in tp]
    dup = {k for ks in (base_c, base_p) for k in ks if k and ks.count(k) > 1}
    texts_of = {id(ln): x for ln, x in [*zip(cur, tc), *zip(pri, tp)]}

    def keys(lines, base):
        out, seen = [], {}
        for ln, k in zip(lines, base):
            if k in dup:
                k = "|".join(texts_of[id(ln)][:2])
            n = seen.get(k, 0)
            seen[k] = n + 1
            out.append(k if n == 0 or not k else f"{k}#{n}")
        return out

    kc, kp = keys(cur, base_c), keys(pri, base_p)
    # 합계 줄 이름이 두 표에서 다르면(당기 표 「계」 · 전기 표 「합 계」) 같은 줄로 본다. 전기 표 합계가 비었다(2026-11-09 전수 대조)
    tc, tp = [k for k in kc if k in _TOTAL_NAMES], [k for k in kp if k in _TOTAL_NAMES]
    if len(tc) == 1 and len(tp) == 1 and tc[0] != tp[0]:
        kc = [tp[0] if k == tc[0] else k for k in kc]
    return kc, kp


_TOTAL_NAMES = {"계", "합계", "총계"}


def _new_row(src: Line, table: int | None) -> Line:
    """당기 줄을 본뜬 새 전기 줄(위치 번호 없음. 원고 → dsd 에서 위 줄 TR 을 복사해 넣는다)."""
    cells = [Cell(None, c.text, c.num, dict(c.fmt) if c.fmt else None, c.covered, c.span, c.tag, c.unit) for c in src.cells]
    return Line("줄", None, cells, table=table, tag="TR")


def _copy_rows(cur: list[Line], pri: list[Line], skip: int = 0, cols: dict | None = None,
               add: list | None = None, start: Line | None = None, keep_one: bool = True) -> tuple[int, list[str]]:
    """당기 줄의 숫자 칸을 이름이 같은 전기 줄로 옮기고 당기 숫자 칸을 비운다. (옮긴 줄 수, 전기에 없는 당기 줄 이름).
    cols 는 당기 열 → 전기 열(두 표 머리가 다를 때 머리 이름으로 맞춘 것, 없으면 같은 열). 대응이 없는 전기 열과
    당기에 없는 전기 줄의 숫자 칸은 비운다(작년의 전기 숫자가 남지 않게, 2026-11-05).
    add 를 주면(두 표 머리가 같을 때) 전기 표에 없는 당기 줄을 바로 위 당기 줄이 옮겨 간 전기 줄 아래에 새 줄로 더한다.
    (뒤 줄, 새 줄)을 add 에 모으고 시트에 넣는 일은 부른 쪽이 한다(2026-11-06 D5: 외화 표의 미지급금 줄을 버렸다).
    start 는 첫 당기 줄이 전기에 없을 때 새 줄을 넣을 자리(그 줄 아래), keep_one 은 전기 줄이 모두 지울 줄이어도 한 줄은 남길지다
    (표 전체일 때만 켠다. 자본변동표의 전기 변동 줄은 표 일부라 모두 지워도 된다, 2026-11-09)."""
    kc, kp = _row_keys(cur, pri, skip)
    by = {}
    for ln, k in zip(pri, kp):
        by.setdefault(k, ln)
    moved, missing, hit = 0, [], set()
    after = start
    same = cols is None or all(j == jp for j, jp in cols.items())          # 열이 자리마다 같으면(이름만 다름) 줄을 더해도 칸이 맞는다
    for ln, k in zip(cur, kc):
        dst = by.get(k)
        nums = [j for j, c in enumerate(ln.cells) if c.num is not None or (not c.text.strip() and not c.covered and j >= skip + 1)]
        if dst is None:
            has = any(ln.cells[j].num is not None for j in nums)
            if has and add is not None and after is not None and same and (after.kind == "표" or len(after.cells) == len(ln.cells)):
                new = _new_row(ln, after.table)
                for j in range(min(skip, len(new.cells))):     # 줄 묶음 표: 첫 열(「전기」 병합 칸)은 덮인 칸으로 둔다
                    new.cells[j].text, new.cells[j].num, new.cells[j].covered, new.cells[j].span = "", None, True, (1, 1)
                add.append((after, new))
                after = new
            elif has:
                missing.append(k)
            for j in nums:
                ln.cells[j].text, ln.cells[j].num = "", None
            continue
        after = dst
        hit.add(id(dst))
        for j in nums:
            jp = cols.get(j) if cols is not None else j
            c = ln.cells[j]
            if jp is None or jp >= len(dst.cells) or dst.cells[jp].covered:
                c.text, c.num = ("", None) if c.num is not None else (c.text, c.num)
                continue
            t = dst.cells[jp]
            if c.num is None and t.num is None and not c.text.strip():
                continue
            t.text, t.num, t.fmt = c.text, c.num, c.fmt or t.fmt
            c.text, c.num = "", None
        if cols is not None:
            mapped = set(cols.values())
            for jp, t in enumerate(dst.cells):
                if jp > skip and jp not in mapped and t.num is not None:
                    t.text, t.num = "", None
        moved += 1
    gone = [ln for ln, k in zip(pri, kp) if id(ln) not in hit and k and add is not None
            and any(t.num is not None for t in ln.cells[skip + 1:])]
    if gone and len(gone) == len(pri) and keep_one:
        gone = gone[1:]                      # 표의 줄을 모두 지우면 편집기가 열지 못한다(빈 TBODY, 2026-11-07). 한 줄은 숫자만 비운다
    for ln, k in zip(pri, kp):
        if id(ln) not in hit and k:
            if any(ln is g for g in gone):
                add.append((ln, None))         # 머리가 같은 두 표: 작년 당기에 없던 재작년 줄은 지운다(전기 표 = 작년 당기 표)
                continue
            for t in ln.cells[skip + 1:]:
                if t.num is not None:
                    t.text, t.num = "", None
    return moved, missing


def _head_word(text: str) -> str:
    """머리 칸 이름을 견줄 꼴. 각주 표시를 떼고, 「당기초 · 전기말」 → 「기초 · 기말」, 「기초잔액 · 기말장부금액」 → 「기초 · 기말」,
    「감가상각비」 → 「감가상각」. 당기 표와 전기 표가 이름만 조금 다르게 적은 열을 맞추려는 것이다(2026-11-09 전수 대조)."""
    t = re.sub(r"\(\s*\*[^)]*\)|\*\d*", "", norm(text))
    t = re.sub(r"^[당전]기(?=[초말])", "기", t)
    t = re.sub(r"^(기초|기말)(?:잔액|금액|장부금액|장부가액|가액)$", r"\1", t)
    return re.sub(r"^((?:감가)?상각)비$", r"\1", t)


def _head_sig(head: list[Line]) -> list[list[str]]:
    """두 표 머리를 견줄 글. 왼쪽 위 칸이 「당기」 · 「전기」 같은 기간 표시뿐이면 빼고 본다(그 칸이 두 표를 가르는 표시다, 2026-11-09)."""
    out = []
    for i, ln in enumerate(head):
        row = []
        for j, c in enumerate(ln.cells):
            t = _head_word(c.text)
            if i == 0 and j == 0 and len(norm(c.text)) <= 4 and _period_of_text(c.text):
                t = ""
            row.append("~" if c.covered else t)
        out.append(row)
    return out


def _same_shape(a: list[Line], b: list[Line]) -> bool:
    return len(a) == len(b) and all(len(x.cells) == len(y.cells) and [c.covered for c in x.cells] == [c.covered for c in y.cells]
                                    for x, y in zip(a, b))


def _alike_heads(cur_head: list[Line], pri_head: list[Line]) -> bool:
    """열을 맞추지 못한 두 표 머리가 같은 표의 당기 · 전기인가. 단위 · 기간 글을 뺀 머리 이름이 둘 이상 겹치고, 적은 쪽 이름의 절반 이상이
    겹치면 같다(2026-11-10). 「(단위: 천원)」 줄을 머리에 둔 「기초 · 상각 · 기말」 · 「기초 · 취득 · 상각 · 기말」 두 표를 버렸다.
    「(1) 당기말 현재」 잔액 표(취득금액 · 상각누계액 · 장부금액)와 전기 변동표(기초 · 취득 · 상각 · 기말)는 「구분」 하나만 겹쳐 짝이 아니다."""
    def names(head):
        out = set()
        for ln in head:
            for c in ln.cells:
                t = _head_word(c.text)
                if c.covered or not t or "단위" in t or _period_of_text(c.text) is not None and len(t) <= 4:
                    continue
                out.add(t)
        return out
    a, b = names(cur_head), names(pri_head)
    both = a & b
    return len(both) >= 2 and len(both) * 2 >= min(len(a), len(b))


def col_map(cur_head: list[Line], pri_head: list[Line]) -> dict | None:
    """두 표 머리가 다를 때 당기 열 → 전기 열을 머리 이름으로 맞춘다. 머리가 한 줄이고 첫 열이 같을 때만(병합 머리는 맞추지 않는다)."""
    if len(cur_head) != 1 or len(pri_head) != 1:
        return None
    # 각주 표시는 이름에서 뗀다. 「대 체(*)」 와 「대 체(*1, *2)」 를 다른 열로 보면 대체 값을 버린다(2026-11-06 실제 회사 시험 D4).
    # 「기초잔액 · 감가상각비」 와 「기초 · 감가상각」 도 같은 열이다(2026-11-09 전수 대조, _head_word)
    mark = _head_word
    hc = [mark(c.text) for c in cur_head[0].cells]
    hp = [mark(c.text) for c in pri_head[0].cells]
    if hc and hp and _period_of_text(cur_head[0].cells[0].text) == "cur" and _period_of_text(pri_head[0].cells[0].text) == "pri":
        hp[0] = hc[0]                       # 왼쪽 위 칸 「당 기」 · 「전 기」 는 같은 열이다(2026-11-06 E2)
    if not hc or not hp or hc[0] != hp[0] or len(set(hp)) != len(hp):
        return None
    out = {j: hp.index(t) for j, t in enumerate(hc) if j > 0 and t and t in hp}
    if len(hc) == len(hp):                  # 열 수가 같으면 이름이 맞지 않는 열은 같은 자리 열로(「1년 미만」 · 「3개월 미만」, 2026-11-06 N10)
        used = set(out.values())
        for j in range(1, len(hc)):
            if j not in out and j not in used and hc[j] and hp[j]:
                out[j] = j
    return out if len(out) >= max(1, (len(hc) - 1) // 2) else None


_OPEN = re.compile(r"^기초(금액|잔액|장부금액)?$")
_CLOSE = re.compile(r"^기말(금액|잔액|장부금액)?$")


def _put(dst: Cell, src: Cell) -> None:
    dst.text, dst.num, dst.fmt = src.text, src.num, src.fmt or dst.fmt


def fill_opening(cur: list[Line], pri: list[Line], hc: int, hp: int, skip: int = 0) -> int:
    """변동표에서 새 당기 기초를 옮긴 전기(작년 당기) 기말로 채운다(2026-11-05 DSD변환). 채운 칸 수.
    열 꼴: 머리 칸 「기초」 · 「기말」 열이 있으면 줄 이름이 같은 전기 줄의 기말 칸을 당기 줄 기초 칸에 넣는다.
    줄 꼴: 본문 첫 칸이 「기초」 인 당기 줄에 전기 「기말」 줄의 숫자 칸을 넣는다. _copy_rows 뒤에 부른다."""
    n = 0

    def find(head, rx):        # 「당기초 · 당기말」 「기초잔액」 도 기초 · 기말 열이다(_head_word)
        return sorted({j for ln in head for j, c in enumerate(ln.cells) if not c.covered and rx.match(_head_word(c.text))})

    # 기초 열마다 그 오른쪽(다음 기초 열 앞)의 기말 열과 짝짓는다. 「일시적차이 기초 · 증감 · 기말 | 이연법인세 기초 · 기말」 처럼
    # 짝이 둘인 표에서 첫 짝만 채웠다(2026-11-09 법인세 주석)
    opens, closes = find(cur[:hc], _OPEN), find(pri[:hp], _CLOSE)
    pairs = []
    for i, j0 in enumerate(opens):
        stop = opens[i + 1] if i + 1 < len(opens) else 10 ** 9
        j1 = next((j for j in closes if j0 < j < stop), None)
        if j1 is not None:
            pairs.append((j0, j1))
    if pairs:
        by = {}
        kc, kp = _row_keys(cur[hc:], pri[hp:], skip)
        for ln, k in zip(pri[hp:], kp):
            by.setdefault(k, ln)
        for ln, k in zip(cur[hc:], kc):
            p = by.get(k)
            for j0, j1 in pairs:
                if p is None or j0 >= len(ln.cells) or j1 >= len(p.cells):
                    continue
                if p.cells[j1].num is not None and not ln.cells[j0].covered:
                    _put(ln.cells[j0], p.cells[j1])
                    n += 1
        return n
    o = next((ln for ln in cur[hc:] if _OPEN.match(_row_key(ln, skip))), None)
    c = next((ln for ln in pri[hp:] if _CLOSE.match(_row_key(ln, skip))), None)
    if o is not None and c is not None:
        for j in range(skip + 1, min(len(o.cells), len(c.cells))):
            if c.cells[j].num is not None and not o.cells[j].covered:
                _put(o.cells[j], c.cells[j])
                n += 1
    return n


# 문단 끝에 붙은 기간 머리: 「… 다음과 같습니다.5.2.1 당기말」 「… 같습니다.17.2.1 당기」(줄바꿈이 빠진 공시 원문, 2026-11-06 다른 회사 시험 E2).
# 「전기초」 는 셋째 기간이라 보지 않는다. 「… 같습니다(단위:천원).<당기말>」 처럼 괄호 · 꺾쇠로 감싼 끝 기간도 읽는다(2026-11-09 전수 대조)
_TAIL_PERIOD = re.compile(r"(?:^|[\s.)\d<\[〈(])[<\[〈(]?\s*(당|전)\s*기(?:말)?\s*[>\]〉)]?\s*$")


def _period_of_text(text: str) -> str | None:
    m = _TAIL_PERIOD.search(text[-12:])                                          # 끝에 붙은 기간이 앞 문장의 「당기와 전기 중」 보다 앞선다
    if not m:
        if {"당", "전"} <= set(re.findall(r"(당|전)\s*(?:반기|분기|기)", text[:40])):
            return None                     # 「당기와 전기 중 …」 은 두 기간을 함께 말한다. 「전기」 만 읽어 전기 표로 보았다(2026-11-07 주석28.3)
        m = _LABEL_PERIOD.search(text[:40])
    return None if not m else ("cur" if m.group(1) == "당" else "pri")


_FS_KINDS = ("표지", "재무제표 표지", "재무제표", "주석 머리", "주석")
# 괄호 · 따옴표로 감싼 꼴만: 「(감사받지 아니한 재무제표)」 「"감사받지 않은 재무제표"」(2026-11-06 다른 회사 시험 N8 · E3)
_UNAUDITED = re.compile(r"\s*(?:\(\s*감사\s*받지\s*(?:않은|아니한)\s*재무제표\s*\)|[\"“]\s*감사\s*받지\s*(?:않은|아니한)\s*재무제표\s*[\"”])")


def _drop_unaudited(d: Draft) -> None:
    """작년 전기가 감사받지 않은 숫자였으면(초도 감사) 「(감사받지 않은 재무제표)」 표시는 재작년 칸을 가리킨다. 새 전기는 작년에 감사받은
    당기라 표지 · 재무제표 · 주석의 이 표시를 지운다. 감사보고서 기타사항 같은 문장은 고치지 않고 알린다(2026-11-06 다른 회사 시험 N8)."""
    n = 0
    for s in d.sheets:
        for ln in s.lines:
            for c in ln.cells:
                if c.covered or not c.text:
                    continue
                if s.kind in _FS_KINDS:
                    t = _UNAUDITED.sub("", c.text)
                    if t != c.text:
                        c.text, n = t, n + 1
    if n:
        d.notes.append(f"「(감사받지 않은 재무제표)」 표시 {n}곳을 지웠다. 작년 전기(재작년)를 가리키던 표시이고 새 전기는 작년에 감사받은 당기다")
    said = [s.key for s in d.sheets if s.kind not in _FS_KINDS
            and any(re.search(r"감사\s*받지\s*(?:않|아니)", c.text or "") for ln in s.lines for c in ln.cells)]
    if said:
        d.notes.append(f"{', '.join(dict.fromkeys(said))}: 전기 재무제표를 감사받지 않았다는 작년 문장이 남았다. 새 전기는 감사받은 해라 그 문단(기타사항 등)을 고치거나 지운다")


_SOCE_DATE = re.compile(r"(?<!\d)((?:19|20)\d{2})\s*[.\-/년]\s*(\d{1,2})\s*[.\-/월]\s*(\d{1,2})")
_SOCE_WORD = re.compile(r"([전당])\s*기\s*([초말])")
_SOCE_EDGE = re.compile(r"기\s*[초말]|[초말]\s*자\s*본|[초말]\s*잔\s*액")


def _soce_edge(ln: Line, end: str | None) -> tuple[str, str] | None:
    """자본변동표 줄이 기간 경계 줄(전기초 · 전기말 · 당기초 · 당기말)이면 (기간, 초 · 말). 숫자가 없는 줄은 아니다.
    날짜(「2024.1.1(당기초)」 · 「2024.12.31(기말자본)」)가 있으면 날짜로, 없으면 「전기초」 같은 말로 가른다."""
    t = _row_key(ln)
    if not t or not any(c.num is not None for c in ln.cells[1:]):
        return None
    m = _SOCE_DATE.search(t)
    if m and end and re.fullmatch(r"\d{8}", end):
        import datetime as dt

        def years_back(x: "dt.date", k: int) -> "dt.date":
            try:
                return x.replace(year=x.year - k)
            except ValueError:                 # 2월 29일
                return x.replace(year=x.year - k, day=28)
        try:
            day = dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            e = dt.date(int(end[:4]), int(end[4:6]), int(end[6:]))
        except ValueError:
            day = None
        if day is not None:
            pe, ppe, one = years_back(e, 1), years_back(e, 2), dt.timedelta(days=1)
            if day == e:
                return "cur", "말"
            if day == pe:
                return "pri", "말"
            if day == pe + one:
                return "cur", "초"
            if day in (ppe + one, ppe):
                return "pri", "초"
            # 기간 첫날 · 끝날이 아닌 날짜는 변동 줄의 거래일이다(「2024.8.10 | 전환우선주 발행」). 당기초로 읽어 새 전기초 줄을 잃었다(2026-11-10)
    w = _SOCE_WORD.search(t)
    if w and _SOCE_EDGE.search(t):
        return ("cur" if w.group(1) == "당" else "pri"), w.group(2)
    return None


def _roll_soce(s: Sheet, a: int, b: int, d: Draft, grow: list, rolled: list) -> bool:
    """자본변동표(두 해를 위아래로 둔 한 표)를 옮긴다(2026-11-09 전수 대조). 작년 당기 묶음(당기초 ~ 당기말)을 전기 묶음 자리로 옮기고
    「당기」 를 「전기」 로 바꾼다. 새 당기 묶음은 작년 당기 줄 이름을 그대로 두고 날짜만 +1, 당기초 줄에 작년 당기말 숫자를 넣고
    변동 줄 · 당기말 줄 숫자는 비운다. 전기 변동 줄은 작년 당기 변동 줄 이름으로 맞춘다(없는 줄은 더하고, 재작년에만 있던 줄은 지운다).
    당기초 줄 없이 「전기초 · 변동 · 전기말 · (당기 변동) · 당기말」 로 쌓은 주석 표도 받는다. 작년 당기초는 작년 전기말과 같아 새 전기초에
    작년 전기말을 넣는다(2026-11-09 자본금 주석). 경계 줄을 찾지 못하면 손대지 않고 False."""
    rows = [ln for ln in s.lines[a + 1:b] if ln.kind in ("머리", "줄")]
    head = _head_rows(rows)
    body = rows[head:]
    end = str(d.info.get("period_end") or "")
    tags = [_soce_edge(ln, end) for ln in body]
    first = lambda want: next((i for i, t in enumerate(tags) if t == want), None)  # noqa: E731
    last = lambda want: next((i for i in range(len(tags) - 1, -1, -1) if tags[i] == want), None)  # noqa: E731
    i1, i2, i3, i4 = first(("pri", "초")), last(("pri", "말")), first(("cur", "초")), last(("cur", "말"))
    if None in (i1, i2, i4) or not (i1 < i2 < i4) or (i3 is not None and not i2 < i3 < i4):
        return False
    if i3 is not None and any(c.num is not None for ln in body[i2 + 1:i3] for c in ln.cells):
        return False                       # 전기말과 당기초 사이에 숫자 줄(회계정책 변경 효과 등)이 있으면 옮기지 않는다
    b1, b2, b4 = body[i1], body[i2], body[i4]
    b3 = body[i3] if i3 is not None else None
    edges = [x for x in (b1, b2, b3, b4) if x is not None]
    if len({len(x.cells) for x in edges}) != 1:
        return False
    names = head_names(rows, head)
    notes = {j for j, n in enumerate(names) if re.fullmatch(r"주석(번호)?", norm(n))}
    lab = lambda ln: next((j for j, c in enumerate(ln.cells) if not c.covered and c.num is None and c.text.strip()), 0)  # noqa: E731
    to_pri = lambda t: re.sub(r"당(\s*)기", r"전\1기", t)  # noqa: E731
    snap = [Cell(None, text=c.text, num=c.num, fmt=c.fmt) for c in b4.cells]
    # 전기 경계 줄 = 작년 당기 경계 줄(이름의 「당기」 → 「전기」, 날짜는 그대로). 당기초 줄이 없으면 새 전기초 = 작년 전기말
    for dst, src in ((b1, b3 if b3 is not None else b2), (b2, b4)):
        jd, js = lab(dst), lab(src)
        dst.cells[jd].text = to_pri(src.cells[js].text) if src is not b2 else bump(dst.cells[jd].text)
        for j in range(1, len(dst.cells)):
            if j != jd and not dst.cells[j].covered and not src.cells[j].covered:
                _put(dst.cells[j], src.cells[j])
    # 전기 변동 줄 = 작년 당기 변동 줄. 주석 번호 열은 새 당기 줄에도 남긴다
    mid_c, mid_p = body[(i3 if i3 is not None else i2) + 1:i4], body[i1 + 1:i2]
    keep = [[(j, ln.cells[j].text, ln.cells[j].num) for j in notes if j < len(ln.cells) and not ln.cells[j].covered] for ln in mid_c]
    added: list = []
    moved, missing = _copy_rows(mid_c, mid_p, add=added, start=b1, keep_one=False)
    for ln, kept in zip(mid_c, keep):
        for j, text, num in kept:
            ln.cells[j].text, ln.cells[j].num = text, num
    grow += added
    # 새 당기 경계 줄: 날짜 +1, 당기초 = 작년 당기말, 당기말은 비운다
    cleared = []
    for ln in (b3, b4):
        if ln is None:
            continue
        j0 = lab(ln)
        ln.cells[j0].text = bump(ln.cells[j0].text)
    opened = 0
    for j in range(1, len(b3.cells) if b3 is not None else 0):
        c = b3.cells[j]
        if j in notes or c.covered or j == lab(b3):
            continue
        _put(c, snap[j])
        opened += c.num is not None
    for ln in mid_c + [b4]:
        for j, c in enumerate(ln.cells):
            if j in notes or c.covered or j == lab(ln):
                continue
            if c.num is not None:
                c.text, c.num = "", None
            if c.loc is not None and c.fmt is not None and not c.text.strip():
                cleared.append(c.loc)
    for ln in rows[:head]:
        for c in ln.cells:
            if not c.covered:
                c.text = bump(c.text)
    plus, minus = [n for _, n in added if n], [o for o, n in added if n is None]
    name = f"{s.key} 표 {s.lines[a].table}"
    d.notes.append(f"{name}: 작년 당기 줄(당기초 ~ 당기말 {i4 - i3 + 1}줄)을 전기 줄로 옮기고 새 당기초에 작년 당기말을 넣었다. "
                   if b3 is not None else
                   f"{name}: 당기초 줄이 없는 표다. 새 전기초에 작년 전기말, 새 전기말에 작년 당기말을 넣고 작년 당기 변동 줄 {i4 - i2 - 1}개를 전기 변동 줄로 옮겼다. "
                   "새 당기 변동 줄은 작년 줄 이름만 두고 숫자를 비웠다(올해 변동에 맞게 줄을 더하고 지운다)"
                   + (f". 전기 변동 줄을 맞추며 더한 줄 {len(plus)} · 지운 재작년 줄 {len(minus)}" if plus or minus else ""))
    if missing:
        d.notes.append(f"{name}: 전기 묶음에 넣지 못한 작년 당기 변동 줄({', '.join(missing[:5])})")
    rolled.append({"sheet": s.key, "table": s.lines[a].table, "loc": s.lines[a].loc, "opening": opened, "cells": cleared,
                   "mode": "자본변동표" if s.key == "자본변동표" else "위아래 묶음"})
    return True


_REL = re.compile(r"(?<![가-힣])(당|전)(\s*)기(?=\s*(?:말|초|$|[^가-힣]))")


def _back_one(text: str) -> str:
    """당기 표 머리 글을 한 해 뒤 표 머리 글로: 「당기 · 당기말 · 당 기」 → 「전기 …」, 「전기초」 → 「전전기초」, 「(당)」 → 「(전)」.
    「당기손익」 · 「전기설비」 처럼 뒤에 다른 글자가 붙은 말은 기간이 아니라 두지 않는다."""
    t = _REL.sub(lambda m: ("전" if m.group(1) == "당" else "전전") + m.group(2) + "기", text)
    return re.sub(r"\(\s*당\s*\)", "(전)", t)


def _copy_tables(raw: bytes, copies: list) -> bytes:
    """전기 표(TABLE 요소)를 작년 당기 표 요소 사본으로 바꾼다. 사본 머리 칸 글은 copies 의 head(칸 위치, 새 글)로."""
    from .dsd_build import text_edit

    src = Source(raw)
    edits = []
    for c in copies:
        tc, tp = src.nodes[c["cur"]], src.nodes[c["pri"]]
        inner = []
        for loc, text in c["head"]:
            es, _ = text_edit(src, src.nodes[loc], text)
            inner += [(a - tc.s, b - tc.s, new) for a, b, new in es]
        piece, out, at = raw[tc.s:tc.e], [], 0
        for a, b, new in sorted(inner):
            out += [piece[at:a], new]
            at = b
        out.append(piece[at:])
        edits.append((tp.s, tp.e, b"".join(out)))
    return src.apply(edits)


def roll(d: Draft) -> Draft:
    """_roll 을 하고, 따로 둔 당기 · 전기 두 표가 있으면 전기 표를 작년 당기 표 사본으로 바꾼 바탕에서 다시 한다. 새 전기 표는 작년
    당기 표와 같아야 한다. 그 전에는 숫자 칸만 줄 이름 · 열 머리로 옮겨, 당기 표에만 있는 열(「사업결합」 · 「재평가」)과 줄은 비우고
    율 · 평가기법 같은 글 칸은 재작년 것이 남았다(2026-11-10 요청 「오류가 있을 수 없는 스킬」). 원고 엑셀은 바꾼 바탕을 담는다."""
    before = list(d.notes)
    _roll(d)
    seen, copies = set(), []
    for c in d.info.get("copy_tables") or []:
        if not {c["cur"], c["pri"]} & seen:      # 한 표가 두 짝에 걸리면 앞 짝만(고침 구간이 겹치지 않게)
            copies.append(c)
            seen |= {c["cur"], c["pri"]}
    if not copies:
        return d
    new = from_raw(_copy_tables(d.contents, copies), d.meta, d.base, d.source, d.sha256)
    _roll(new)
    d.sheets, d.contents, d.info, d.rolled = new.sheets, new.contents, new.info, new.rolled
    where = ", ".join(f"{c['sheet']} 표 {c['tables'][1]}" for c in copies)
    d.notes = before + [f"따로 둔 당기 · 전기 두 표 {len(copies)}쌍: 전기 표를 작년 당기 표 사본(열 · 줄 · 숫자 · 글)으로 바꿨다. "
                        f"머리의 기간 글(당기 → 전기)만 한 해 뒤로 고쳤다({where})"] + new.notes
    d.info["copied_tables"] = [{"sheet": c["sheet"], "from": c["tables"][0], "to": c["tables"][1]} for c in copies]
    return d


def _roll(d: Draft) -> Draft:
    """작년 판 원고를 당기 초안으로: 당기 숫자를 전기 칸으로 옮기고 당기 칸을 비운다. 머리줄 기수 · 해 +1, 표지 · 재무제표 머리 표 · TU 날짜 +1,
    외부감사 실시내용 「감사대상 사업연도」(TU SUB_PERIODFROM · SUB_PERIODTO) +1.
    당기 · 전기를 두는 꼴 셋을 옮긴다: 열(「당기말 · 전기말」 열), 한 표 안 줄 묶음(첫 열 「당기 · 전기」 병합 칸), 따로 둔 두 표(표 위 문단 「당기 · 전기」
    또는 「① 당기말 | (단위: 원)」 한 줄 표). 변동표는 새 당기 기초를 작년 당기 기말로 채운다(fill_opening).
    자본변동표(두 해를 위아래로 둔 한 표)는 경계 줄 넷으로 묶음을 갈라 옮긴다(_roll_soce, 2026-11-09).
    문단 속 날짜는 바꾸지 않는다(문장 검토가 작년 날짜를 잡는다). 정하지 못한 표는 손대지 않고 notes 에 적는다.
    1차에서 뺀다: 반기 · 분기 보고서(재무상태표 비교가 직전 사업연도 말이다)."""
    doc = norm(d.info.get("document") or "")
    if "반기" in doc or "분기" in doc:
        d.notes.append("반기 · 분기 보고서는 1차에서 롤포워드하지 않는다(재무상태표 비교 기간이 직전 사업연도 말이라 +1년 규칙이 맞지 않는다)")
        return d
    term = d.info.get("term")
    end = str(d.info.get("period_end") or "")
    fy = int(end[:4]) if re.fullmatch(r"\d{8}", end) else None
    rolled = []
    copies = []                                # 전기 표를 작년 당기 표 사본으로 바꿀 짝(roll 이 바탕을 바꿔 다시 한다)
    stale = []                                 # 옮긴 표 안에서 작년 값이 남은 숫자 칸(당기 · 전기 열이 아닌 열)의 위치. 원고에서 분홍으로 칠한다
    kept = []                                  # 옮기지 못해 작년 숫자를 그대로 둔 표. 원고 엑셀에서 색칠하고 안내에 모은다(2026-11-10 결정)
    for s in d.sheets:
        for ln in s.lines:                     # 외부감사 실시내용 「감사대상 사업연도」 는 표지 기간과 같아야 편집기 검사를 넘는다(2026-11-06)
            for c in ln.cells:
                if c.unit in ("SUB_PERIODFROM", "SUB_PERIODTO") and not c.covered:
                    c.text = bump(c.text)
        blocks = _blocks(s.lines)
        done: set = set()
        grow: list = []                         # (뒤 줄, 새 줄). 표 위치가 바뀌지 않게 시트를 다 본 뒤 넣는다
        if s.kind in ("재무제표", "주석"):
            # 따로 둔 두 표: 표 위 세 줄 안의 문단이 「당기 · 전기」
            tagged = []
            head_tagged: set = set()               # 머리 기간 열로만 기간을 정한 표. 바로 다음 숫자 표하고만 짝짓는다
            start_of = {b: a for a, b in blocks}

            def unit_only(a, b):
                rows = [ln for ln in s.lines[a + 1:b] if ln.kind in ("머리", "줄")]
                texts = [c.text for ln in rows for c in ln.cells if c.text.strip()]
                return len(texts) == 1 and _unit_like(texts[0])

            def label_table(a, b):
                rows = [ln for ln in s.lines[a + 1:b] if ln.kind in ("머리", "줄")]
                if len(rows) != 1 or any(c.num is not None for c in rows[0].cells):
                    return None
                texts = [re.sub(r"\s+", " ", c.text).strip() for c in rows[0].cells if c.text.strip()]
                texts = [t for t in texts if not _unit_like(t)]
                return _period_of_text(texts[0]) if len(texts) == 1 and len(norm(texts[0])) <= 12 else None

            for a, b in blocks:
                per = None
                if not any(c.num is not None for ln in s.lines[a + 1:b] for c in ln.cells):
                    tagged.append((a, b, None))
                    continue
                k = a - 1
                seen = 0
                while k >= 0 and seen < 4:
                    ln = s.lines[k]
                    if ln.kind == "표끝" and k in start_of and label_table(start_of[k], k):
                        per = label_table(start_of[k], k)               # 「① 당기말 | (단위: 원)」 한 줄 표(2026-11-05)
                        break
                    if ln.kind == "표끝" and k in start_of and unit_only(start_of[k], k):
                        k = start_of[k] - 1                            # 「(단위 : 원)」 한 칸 표는 건너뛴다
                        continue
                    if ln.kind in ("표끝", "표", "글 표", "머리", "줄"):
                        break
                    seen += 1
                    if ln.kind in ("문단", "제목") and ln.cells and ln.cells[0].text.strip():
                        t = re.sub(r"\s+", " ", ln.cells[0].text).strip()
                        if re.match(r"\(?\s*\*", t):
                            break                          # 「(*) 전기는 …」 은 앞 표의 각주다. 다음 표의 기간 표시로 읽지 않는다(2026-11-07)
                        # 「〈당 기〉 (단위:원)」 처럼 기간과 단위가 한 문단이면 단위를 떼고 읽는다. 단위 줄로 보고 건너뛰어 짝을 잃었다(2026-11-09 전수 대조)
                        bare = _UNIT_TEXT.sub("", t).strip()
                        if bare:
                            per = _period_of_text(bare)
                            break
                    k -= 1
                if per is None:                        # 표 왼쪽 위 칸이 「당 기」 · 「전 기」 뿐인 표(2026-11-06 다른 회사 시험 E2)
                    top = next((ln for ln in s.lines[a + 1:b] if ln.kind in ("머리", "줄")), None)
                    if top is not None and top.cells and len(norm(top.cells[0].text)) <= 4:
                        per = _period_of_text(top.cells[0].text)
                head = next((ln for ln in s.lines[a + 1:b] if ln.kind == "머리"), None)
                if per is not None and head is not None and {"cur", "pri"} <= {_period_of_text(c.text) for c in head.cells[1:]}:
                    per = None                         # 머리에 당기 · 전기 열이 다 있는 표는 열 꼴이다. 다른 표와 짝짓지 않는다(2026-11-07)
                if per is None:                        # 머리 기간 열이 한쪽뿐인 표: 「구분 | 당기초 | 당기말」 · 「구분 | 전기초 | 전기말」(2026-11-09)
                    rows_t = [ln for ln in s.lines[a + 1:b] if ln.kind in ("머리", "줄")]
                    pc, pp = period_columns(rows_t, _head_rows(rows_t), None, None)
                    if bool(pc) != bool(pp):
                        per = "cur" if pc else "pri"
                        head_tagged.add((a, b))
                tagged.append((a, b, per))
            numeric = [i for i, (a, b, _) in enumerate(tagged) if any(c.num is not None for ln in s.lines[a + 1:b] for c in ln.cells)]
            for x, y in zip(numeric, numeric[1:]):  # 「(전기말)」 표시만 있고 바로 앞 표에 「당기」 표시가 없으면 그 표를 당기 표로 본다(2026-11-06 N10)
                (a, b, per), (a2, b2, per2) = tagged[x], tagged[y]
                if per is None and per2 == "pri":
                    # 머리를 TH 가 아닌 보통 칸으로 적은 표는 숫자가 처음 나오는 줄 앞까지가 머리다(2026-11-09 전수 대조 보험회사 「<전기>」 표)
                    rx_ = [ln for ln in s.lines[a + 1:b] if ln.kind in ("머리", "줄")]
                    ry_ = [ln for ln in s.lines[a2 + 1:b2] if ln.kind in ("머리", "줄")]
                    hc_, hp_ = rx_[:_head_rows(rx_)], ry_[:_head_rows(ry_)]
                    # 열 수가 달라도(당기 표에만 「2년 초과」 열) 머리 이름이 맞으면 짝이다(2026-11-09 전수 대조 만기분석 표)
                    if hc_ and hp_ and norm(hc_[0].cells[0].text) == norm(hp_[0].cells[0].text) and (
                            len(hc_[-1].cells) == len(hp_[-1].cells) or col_map(hc_, hp_) is not None):
                        tagged[x] = (a, b, "cur")
                        d.notes.append(f"{s.key} 표 {s.lines[a].table}: 「당기」 표시가 없어 바로 뒤 전기 표(표 {s.lines[a2].table})의 당기 표로 보았다")
            for i, (a, b, per) in enumerate(tagged):
                if per != "cur" or (a, b) in done:
                    continue
                mate = next(((x, y) for x, y, q in tagged[i + 1:] if q == "pri" and (x, y) not in done), None)
                if mate is not None and ((a, b) in head_tagged or mate in head_tagged):
                    # 이미 짝지은 표는 건너뛴다: [당기] 표 4 · 표 5(당기초 | 당기말), [전기] 표 6 · 표 7(전기초 | 전기말)에서 표 4 가 표 6 을 먼저 가져간다
                    nxt = next(((x, y) for x, y, _ in tagged[i + 1:] if (x, y) not in done
                                and any(c.num is not None for ln in s.lines[x + 1:y] for c in ln.cells)), None)
                    if nxt != mate:
                        mate = None
                if mate is None:
                    continue
                rows_c = [ln for ln in s.lines[a + 1:b] if ln.kind in ("머리", "줄")]
                rows_p = [ln for ln in s.lines[mate[0] + 1:mate[1]] if ln.kind in ("머리", "줄")]
                hc, hp = _head_rows(rows_c), _head_rows(rows_p)
                cols = None
                renamed = []
                if _head_sig(rows_c[:hc]) != _head_sig(rows_p[:hp]):
                    cols = col_map(rows_c[:hc], rows_p[:hp])
                    if cols is None and hc > 1 and _same_shape(rows_c[:hc], rows_p[:hp]):
                        # 여러 줄 머리가 모양(줄 수 · 열 수 · 병합)이 같으면 자리대로 옮긴다. 「증가」 → 「증감」 처럼 회사가 이름만 바꾼 열이다
                        # (2026-11-09 법인세 주석 일시적차이 표 「당기 | 차감할 일시적차이 | 이연법인세자산」 두 줄 머리)
                        renamed = [f"「{y.text.strip()}」 → 「{x.text.strip()}」" for xr, yr in zip(rows_c[:hc], rows_p[:hp])
                                   for j, (x, y) in enumerate(zip(xr.cells, yr.cells))
                                   if j and not x.covered and norm(x.text) != norm(y.text)]
                    elif cols is None:
                        if not _alike_heads(rows_c[:hc], rows_p[:hp]):
                            continue
                        # 열을 맞추지 못해도(두 줄 머리 · 당기 표에만 있는 열) 머리 이름이 거의 같으면 짝이다. 전기 표는 작년 당기 표 사본이 되므로
                        # 열을 맞출 일이 없다. 칸은 옮기지 않고 사본만 적는다. roll 이 사본 바탕에서 다시 할 때 옮긴다(2026-11-10)
                        copies.append({"sheet": s.key, "cur": s.lines[a].loc, "pri": s.lines[mate[0]].loc,
                                       "head": [(c.loc, _back_one(c.text)) for ln in rows_c[:hc] for c in ln.cells
                                                if not c.covered and c.loc is not None and _back_one(c.text) != c.text],
                                       "tables": [s.lines[a].table, s.lines[mate[0]].table]})
                        done |= {(a, b), mate}
                        continue
                # 새 전기 표 = 작년 당기 표. 칸을 줄마다 옮기면 숫자만 옮겨져 율 · 평가기법 같은 글 칸과 재작년에만 있던 줄의 병합 칸이 남았다.
                # roll 이 전기 표를 작년 당기 표 사본으로 바꾼 바탕에서 다시 한다(2026-11-10). 머리 칸의 기간 글만 한 해 뒤로 고친다.
                # 짝으로 받아들인 뒤에만 적는다. 열이 맞지 않아 버린 짝(「당기말 현재」 잔액 표 ↔ 전기 변동표)까지 적어 엉뚱한 표가 복사됐다
                copies.append({"sheet": s.key, "cur": s.lines[a].loc, "pri": s.lines[mate[0]].loc,
                               "head": [(c.loc, _back_one(c.text)) for ln in rows_c[:hc] for c in ln.cells
                                        if not c.covered and c.loc is not None and _back_one(c.text) != c.text],
                               "tables": [s.lines[a].table, s.lines[mate[0]].table]})
                added: list = []
                lost = []                          # 당기 표에만 있는 열(「처 분」): 전기 표에 열이 없어 옮기지 못한 값을 안내에 남긴다(2026-11-06 D4)
                if cols is not None:
                    for j, c in enumerate(rows_c[hc - 1].cells if hc else []):
                        if j > 0 and j not in cols and not c.covered and c.text.strip():
                            vals = [f"{_row_key(ln)} {ln.cells[j].text.strip()}" for ln in rows_c[hc:]
                                    if j < len(ln.cells) and ln.cells[j].num not in (None, 0)]
                            lost.append(f"「{c.text.strip()}」({', '.join(vals[:6]) or '값 없음'})")
                # 줄 꼴 변동표의 새 당기 기초 = 작년 당기 기말. 같은 표의 기말 줄을 옮기기 전에 잡아 둔다. 옮긴 전기 표에서 가져오면
                # 두 표의 열이 다를 때(당기에만 「기계장치」 열) 한 칸씩 밀려 들어갔다(2026-11-07 한 회사 주석9)
                o_row = next((ln for ln in rows_c[hc:] if _OPEN.match(_row_key(ln))), None)
                c_row = next((ln for ln in rows_c[hc:] if _CLOSE.match(_row_key(ln))), None)
                snap = ([Cell(None, text=c.text, num=c.num, fmt=c.fmt) for c in c_row.cells]
                        if o_row is not None and c_row is not None and o_row is not c_row else None)
                # 첫 당기 줄이 전기 표에 없으면 전기 표 머리 아래(머리가 없으면 표 첫머리)에 더한다. 넣을 자리가 없어 그 줄을 비웠다(2026-11-10 초안 검산 시험)
                moved, missing = _copy_rows(rows_c[hc:], rows_p[hp:], cols=cols, add=added, start=rows_p[hp - 1] if hp else s.lines[mate[0]])
                if snap is not None:
                    opened = 0
                    for j in range(1, min(len(o_row.cells), len(snap))):
                        if snap[j].num is not None and not o_row.cells[j].covered:
                            _put(o_row.cells[j], snap[j])
                            opened += 1
                else:
                    opened = fill_opening(rows_c, [x for x in rows_p if all(x is not o for o, n in added if n is None)] + [n for _, n in added if n], hc, hp)
                grow += added
                plus, minus = [n for _, n in added if n], [o for o, n in added if n is None]
                if plus or minus:
                    d.notes.append(f"{s.key} 표 {s.lines[a].table} → 표 {s.lines[mate[0]].table}: 전기 표를 작년 당기 표의 줄로 맞췄다"
                                   f"(더한 줄 {len(plus)}{': ' + ', '.join(_row_key(n, 0) for n in plus[:4]) if plus else ''}"
                                   f" · 지운 재작년 줄 {len(minus)}{': ' + ', '.join(_row_key(o, 0) for o in minus[:4]) if minus else ''})")
                done |= {(a, b), mate}
                name = f"{s.key} 표 {s.lines[a].table} → 표 {s.lines[mate[0]].table}"
                if renamed:
                    d.notes.append(f"{name}: 머리 모양이 같아 자리대로 옮겼다. 이름이 다른 머리 칸({', '.join(renamed[:4])})은 회사가 바꿨는지 확인한다")
                if cols is not None:
                    d.notes.append(f"{name}: 두 표의 열이 달라 머리 이름으로 맞춰 옮겼다. 전기 표에만 있는 열은 비웠다(열 더하기 · 빼기는 편집기에서)")
                    hn_c, hn_p = rows_c[hc - 1].cells, rows_p[hp - 1].cells
                    pos = [f"「{hn_c[j].text.strip()}」 → 「{hn_p[k].text.strip()}」" for j, k in sorted(cols.items())
                           if j == k and j < len(hn_c) and k < len(hn_p) and norm(hn_c[j].text) != norm(hn_p[k].text)]
                    if pos:
                        d.notes.append(f"{name}: 이름이 다른 열을 같은 자리 열로 옮겼다({', '.join(pos)}). 회사가 머리 이름을 바꿨는지 확인한다")
                if lost:
                    d.notes.append(f"{name}: 당기 표에만 있던 열 {', '.join(lost)} 은 전기 표에 열이 없어 옮기지 못했다. "
                                   "편집기에서 전기 표에 열을 더하고 이 값을 넣어야 줄마다 기초 + 변동 = 기말이 맞는다")
                if missing:
                    d.notes.append(f"{name}: 전기 표에 없는 당기 줄은 옮기지 못하고 비웠다({', '.join(missing[:5])})")
                rolled.append({"sheet": s.key, "table": s.lines[a].table, "loc": s.lines[a].loc, "mode": "표", "opening": opened,
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
            has_num = any(c.num is not None or re.fullmatch(r"\(?-?[\d,]*\.?\d+\s*%\)?", c.text.strip())
                          for ln in rows for c in ln.cells)          # 「4.66%」 율만 있는 표도 옮긴다(2026-11-07 주석18 할인율 표)
            if not has_num:
                continue
            if s.key == "자본변동표":
                if not _roll_soce(s, a, b, d, grow, rolled):
                    d.notes.append(f"{name}: 자본변동표의 기간 경계 줄(전기초 · 전기말 · 당기초 · 당기말)을 찾지 못해 옮기지 않았다")
                    kept.append({"sheet": s.key, "table": s.lines[a].table, "loc": s.lines[a].loc, "why": "기간 경계 줄을 찾지 못함"})
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
                added = []                          # 전기 묶음에 없는 당기 줄은 전기 묶음 안에 새 줄로(첫 열은 「전기」 병합에 잇는다, 2026-11-10)
                moved, missing = _copy_rows(groups["cur"], groups["pri"], skip=1, add=added)
                opened = fill_opening(groups["cur"], [x for x in groups["pri"] if all(x is not o for o, n in added if n is None)]
                                      + [n for _, n in added if n], 0, 0, skip=1)
                grow += added
                if missing:
                    d.notes.append(f"{name}: 전기 묶음에 없는 당기 줄은 옮기지 못하고 비웠다({', '.join(missing[:5])})")
                for ln in rows[:head]:
                    for c in ln.cells:
                        if not c.covered:
                            c.text = bump(c.text)
                rolled.append({"sheet": s.key, "table": s.lines[a].table, "loc": s.lines[a].loc, "mode": "줄 묶음", "opening": opened,
                               "cells": [c.loc for ln in groups["cur"] for c in ln.cells if c.loc is not None and c.fmt is not None]})
                continue
            # 소제목 줄 꼴: 「당기말:」 처럼 기간만 적은 줄(나머지 칸은 병합 · 빈 칸)이 묶음을 연다(2026-11-09 채권 연령분석 표)
            groups, cur_g, bad = {}, None, False
            for ln in body:
                filled = [c for c in ln.cells if not c.covered and c.text.strip()]
                if len(filled) == 1 and filled[0] is ln.cells[0] and len(norm(ln.cells[0].text)) <= 6:
                    g = _period_of_text(ln.cells[0].text.strip().rstrip(":："))
                    if g:
                        cur_g = g
                        groups.setdefault(g, [])
                        continue
                if cur_g is None:
                    if any(c.num is not None for c in ln.cells):
                        bad = True
                        break
                    continue
                groups[cur_g].append(ln)
            if not bad and set(groups) == {"cur", "pri"} and groups["cur"] and groups["pri"]:
                added: list = []
                moved, missing = _copy_rows(groups["cur"], groups["pri"], add=added)
                opened = fill_opening(rows[:head] + groups["cur"], rows[:head] + groups["pri"], head, head)
                grow += added
                if missing:
                    d.notes.append(f"{name}: 전기 묶음에 넣지 못한 당기 줄은 옮기지 못하고 비웠다({', '.join(missing[:5])})")
                rolled.append({"sheet": s.key, "table": s.lines[a].table, "loc": s.lines[a].loc, "mode": "소제목 묶음", "opening": opened,
                               "cells": [c.loc for ln in groups["cur"] for c in ln.cells if c.loc is not None and c.fmt is not None]})
                continue
            cur, pri = period_columns(rows, head, term, fy)
            names = head_names(rows, head)
            first = [j for j in pri if re.search(r"기초|전환일", norm(names[j]))]
            rest = [j for j in pri if j not in first]
            pairs, extra, only_cur = None, [], []
            bare = lambda t: norm(re.sub(r"[당전]\s*기\s*[말초]?|기\s*초|전환일", "", t))  # noqa: E731
            if cur and pri and not first and len(cur) > len(pri):
                # 당기만 세부 열로 나눈 표(당기 「제조원가 · 판매비와관리비 · 합계」 · 전기 「합계」, 2026-11-09 전수 대조 주석12): 기간을 뗀
                # 열 이름으로 전기 열마다 당기 열을 고른다. 짝이 없는 당기 열은 작년 값이라 비운다
                m = [(next((cj for cj in cur if bare(names[cj]) == bare(names[pj])), None), pj) for pj in pri]
                if all(c is not None for c, _ in m) and len({c for c, _ in m}) == len(m):
                    only_cur = [cj for cj in cur if cj not in {c for c, _ in m}]
                    cur, pri = [c for c, _ in m], [p for _, p in m]
            if cur and first and len(rest) == len(cur):
                pairs = list(zip(cur, rest))
            elif cur and first:
                # 기간마다 범주 열이 다른 표(당기말 2열 · 전기말 3열 · 전기초 3열): 기간 말을 뗀 열 이름으로 맞춘다(2026-11-07 한 회사 주석5)
                by: dict = {}
                for j in rest:
                    by.setdefault(bare(names[j]), []).append(j)
                m = [(cj, (by.get(bare(names[cj])) or [None])[0]) for cj in cur]
                if all(p is not None for _, p in m) and len({p for _, p in m}) == len(m):
                    pairs = m
                    extra = [j for j in rest if j not in {p for _, p in m}]
            if pairs is not None:
                # 당기말 · 전기말 · 전기초 세 기간 표(K-IFRS 최초 채택 · 재작성 해, 2026-11-06 다른 회사 시험 E1): 당기말은 전기말 열로,
                # 전기초 열은 다음 해에 둘 까닭이 없어 값을 비우고 열을 지우라고 알린다(열 빼기는 편집기에서).
                # 「151.48%」 처럼 숫자로 읽지 않은 율 칸도 비운다(2026-11-07). 당기에 없던 범주의 전기말 열도 재작년 값이라 비운다
                for ln in rows[head:]:
                    for j in first + extra:
                        if j < len(ln.cells) and not ln.cells[j].covered and (ln.cells[j].num is not None or re.search(r"\d", ln.cells[j].text)):
                            ln.cells[j].text, ln.cells[j].num = "", None
                d.notes.append(f"{s.key} 표 {s.lines[a].table}: 세 기간 표다. 당기말을 전기말 열로 옮기고 「{names[first[0]].strip()}」 열은 비웠다. "
                               "편집기에서 그 열을 지운다(재작성이 없으면 전기초 재무상태표는 두지 않는다)"
                               + (f". 당기 열이 없는 「{', '.join(names[j].strip() for j in extra)}」 열은 재작년 값이라 비웠다" if extra else ""))
                cur, pri = [c for c, _ in pairs], [p for _, p in pairs]
            rate = [j for j in range(1, len(names)) if j not in cur and _RATE.search(names[j]) and _CUR.search(names[j]) and not _PRI.search(names[j])]
            if not cur or len(cur) != len(pri):
                # 자본변동표처럼 전기초 ~ 전기말 · 당기초 ~ 당기말 줄을 위아래로 둔 주석 표(자본금 · 기타포괄손익 변동, 2026-11-09)
                if s.kind == "주석" and _roll_soce(s, a, b, d, grow, rolled):
                    continue
                d.notes.append(f"{name}: 당기 · 전기 칸을 찾지 못해 옮기지 않았다(당기 {len(cur)}열 · 전기 {len(pri)}열)")
                kept.append({"sheet": s.key, "table": s.lines[a].table, "loc": s.lines[a].loc, "why": "당기 · 전기 칸을 찾지 못함"})
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
                for j in only_cur:
                    c = ln.cells[j] if j < len(ln.cells) else None
                    if c is not None and not c.covered and c.num is not None:
                        c.text, c.num = "", None
                        if c.loc is not None and c.fmt is not None:
                            cells.append(c.loc)
            if only_cur:
                d.notes.append(f"{name}: 당기에만 있는 열({', '.join(names[j].strip() for j in only_cur)})은 전기 열이 없어 옮기지 않고 비웠다")
            opened = 0                            # 줄 꼴 변동표(「기초금액 · 기말금액」 줄): 새 당기 기초 = 새 전기 기말(2026-11-06 N11)
            row_open = next((ln for ln in body if ln.cells and _OPEN.match(norm(ln.cells[0].text))), None)
            row_close = next((ln for ln in body if ln.cells and _CLOSE.match(norm(ln.cells[0].text))), None)
            if row_open is not None and row_close is not None and row_open is not row_close:
                for cj, pj in zip(cur, pri):
                    if (max(cj, pj) < min(len(row_open.cells), len(row_close.cells)) and not row_open.cells[cj].covered
                            and row_close.cells[pj].num is not None):
                        _put(row_open.cells[cj], row_close.cells[pj])
                        opened += 1
            for ln in body:                       # 당기에만 있는 율 열(「당기말이자율(%)」)은 작년 값이라 비운다
                for j in rate:
                    if j < len(ln.cells) and not ln.cells[j].covered:
                        ln.cells[j].text, ln.cells[j].num = "", None
            if rate:
                d.notes.append(f"{name}: 당기에만 있는 열({', '.join(names[j] for j in rate)})은 작년 값이라 비웠다. 만기일 같은 글 칸은 작년 글이 남았다")
            # 당기 · 전기 열이 아닌 숫자 열(「이자율(%)」 · 「지분율」 · 「주식수」)은 기간을 몰라 작년 값이 그대로 남는다. 원고에서 분홍으로 칠하고
            # 안내에 모은다(2026-11-10 결정 「작년 숫자를 그대로 둔다」. 말없이 남기면 회계사가 옮긴 값으로 안다)
            per_cols = set(cur) | set(pri)
            old_cols = sorted({j for ln in body for j, c in enumerate(ln.cells)
                               if j and j not in per_cols and not c.covered and c.num is not None and c.loc is not None})
            if old_cols:
                stale += [c.loc for ln in body for j, c in enumerate(ln.cells) if j in old_cols and not c.covered and c.num is not None and c.loc is not None]
                d.notes.append(f"{name}: 당기 · 전기 열이 아닌 숫자 열({', '.join(names[j].strip() for j in old_cols if j < len(names))})은 "
                               "작년 값 그대로다(원고 분홍 칸). 올해 값으로 고친다")
            rolled.append({"sheet": s.key, "table": s.lines[a].table, "loc": s.lines[a].loc, "mode": "열", "cells": cells, "opening": opened})
        for prev, new in grow:                    # 전기 표에 더할 당기 줄은 뒤 줄 바로 아래(새 줄끼리는 차례대로), 지울 재작년 줄은 뺀다
            at = next(i for i, ln in enumerate(s.lines) if ln is prev)
            if new is None:
                del s.lines[at]
            else:
                s.lines.insert(at + 1, new)
    _drop_unaudited(d)
    d.rolled = True
    d.info["rolled_tables"] = rolled
    d.info["kept_tables"] = kept
    d.info["stale_cells"] = stale
    d.info["copy_tables"] = copies
    if term:
        d.info["term"] = term + 1
    if fy:
        d.info["period_end"] = f"{fy + 1}{end[4:]}"
    return d


def _sig(ln: Line) -> tuple:
    """줄의 (열, 값) 중 값이 있는 칸. 빈 칸과 병합으로 덮인 칸은 같게 본다(새 줄이 위 줄 병합에 잇지 못하고 빈 칸을 가져도 값은 같다)."""
    def val(c):
        n = c.num if c.num is not None else parse_num(c.text)[0]     # 「<P>13,879,180,000</P>」 칸은 원문이 글, 옮긴 칸은 숫자로 읽힌다
        return round(n, 4) if n is not None else norm(c.text)
    return tuple((j, val(c)) for j, c in enumerate(ln.cells) if not c.covered and (c.num is not None or norm(c.text)))


def _label(ln: Line) -> str:
    return next((norm(c.text) for c in ln.cells if not c.covered and c.num is None and norm(c.text)), "(이름 없음)")[:30]


def check_built(d: Draft, built: Draft) -> list[dict]:
    """롤포워드 원고(d)와 그 원고로 만든 dsd 를 다시 읽은 것(built)을 줄 · 칸마다 견준다(2026-11-10 요청 「오류가 있을 수 없는 스킬」).
    표는 줄 수와 칸 값(숫자는 값, 글은 norm 한 글)이, 표 밖 줄은 글이 같아야 한다. 다른 곳은 시트 · 표마다 「막음」 한 줄."""
    import difflib

    def issue(sheet, where, what):
        return {"분류": "초안 검산", "시트": sheet, "칸": where, "내용": what, "수준": "막음"}

    out = []
    got = {s.key: s for s in built.sheets}
    for s in d.sheets:
        b = got.pop(s.key, None)
        if b is None:
            out.append(issue(s.key, "", "원고의 시트가 dsd 에 없다"))
            continue
        ta = [(s.lines[x].table, [ln for ln in s.lines[x + 1:y] if ln.kind in ("머리", "줄")]) for x, y in _blocks(s.lines)]
        tb = [(b.lines[x].table, [ln for ln in b.lines[x + 1:y] if ln.kind in ("머리", "줄")]) for x, y in _blocks(b.lines)]
        if len(ta) != len(tb):
            out.append(issue(s.key, "", f"표 수가 다르다(원고 {len(ta)} · dsd {len(tb)})"))
        for (no, ra), (_, rb) in zip(ta, tb):
            sa, sb = [_sig(ln) for ln in ra], [_sig(ln) for ln in rb]
            if sa == sb:
                continue
            only_a = only_b = changed = 0
            first = None
            for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, sa, sb, autojunk=False).get_opcodes():
                if op == "equal":
                    continue
                if op == "replace" and i2 - i1 == j2 - j1:
                    changed += i2 - i1
                else:
                    only_a, only_b = only_a + i2 - i1, only_b + j2 - j1
                if first is None:
                    first = f"「{_label(ra[i1])}」" if i1 < i2 else f"「{_label(rb[j1])}」"
            what = [f"원고와 다른 줄 {changed}개"] if changed else []
            what += [f"원고에만 있는 줄 {only_a}개"] if only_a else []
            what += [f"dsd 에만 있는 줄 {only_b}개"] if only_b else []
            out.append(issue(s.key, f"표 {no}", " · ".join(what) + f". 처음 다른 줄 {first}"))
        pa = [norm(" ".join(c.text for c in ln.cells)) for ln in s.lines if ln.kind in ("제목", "문단")]
        pb = [norm(" ".join(c.text for c in ln.cells)) for ln in b.lines if ln.kind in ("제목", "문단")]
        if pa != pb:
            n = sum(max(i2 - i1, j2 - j1) for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, pa, pb, autojunk=False).get_opcodes() if op != "equal")
            out.append(issue(s.key, "", f"표 밖 글이 다른 줄 {n}개"))
    for k in got:
        out.append(issue(k, "", "원고에 없는 시트가 dsd 에 있다"))
    return out
