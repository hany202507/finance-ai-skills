"""원고 엑셀(2026-10-26, DSD 네 기능 설계 2.3 · 2.4). 쓰기와 읽기.

시트: 원고 안내 · 목차 · 표지 · 감사보고서 · 재무제표 표지 · 재무상태표 … · 주석 머리 · 주석1 … · 외부감사 실시내용 · _위치(숨김) · _원본(숨김).
줄: A 종류(제목 · 문단 · 표 · 글 표 · 머리 · 줄 · 표끝) · B 위치(원본 요소 번호, 숨김 · 잠금) · C 부터 문단 글이나 표 칸.
표 오른쪽 한 열 띄고 「검증」 열에 엔진이 찾은 표 안 합계 수식(TRUE · FALSE)을 둔다. 읽을 때 「검증」 열부터는 읽지 않는다.
_원본 시트에 바탕 contents.xml · meta.xml 을 base64 로 나눠 담아 원고 하나로 dsd 를 다시 만들 수 있다(엑셀이 줄바꿈을 바꾸지 않게 base64).
"""
from __future__ import annotations

import base64
import datetime as _dt
import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill, Protection
from openpyxl.utils import get_column_letter as L

from .. import wp
from .. import style
from .dsd_book import _style_head, print_setup
from .dsd_draft import Cell, Draft, Line, Sheet, excel_format

GUIDE, TOC, POS, ORIG = "원고 안내", "목차", "_위치", "_원본"
FIRST = 4                       # 원고 첫 줄
C0 = 3                          # 첫 칸 열(C)
CHECK = "검증"
FILL_COVER = style.FILL_NONE        # 덮인 칸(2026-11-03 공통 팔레트)
FILL_INFO = style.FILL_SUB
FILL_KEPT = style.FILL_FLAG        # 롤포워드가 옮기지 못해 작년 숫자를 그대로 둔 표의 숫자 칸(2026-11-10)
GRAY = style.MUTED
CHUNK = 30000
LOCKED, UNLOCKED = Protection(locked=True), Protection(locked=False)
TOTAL = re.compile(r"^\s*(합\s*계|계|소\s*계|총\s*계|합계|총계|소계|Total|TOTAL)\s*(\(.*\))?\s*$")
ERRORS = ("#REF!", "#VALUE!", "#DIV/0!", "#NAME?", "#N/A", "#NUM!", "#NULL!", "#SPILL!", "#CALC!")


def _sheet_name(key: str) -> str:
    return "".join("_" if ch in wp.SHEET_NAME_BAD else ch for ch in key)[: wp.SHEET_NAME_MAX]


# ---------------------------------------------------------------- 표 안 합계(원고에서 바로 보이는 검산)
def _label(cells: list[Cell]) -> str:
    for c in cells[:3]:
        if c.text.strip() and c.num is None and not c.covered:
            return c.text
    return ""


def sum_checks(lines: list[Line]) -> list[tuple[int, int, list[int]]]:
    """표 하나의 줄(머리 · 줄)에서 세로 합계를 찾는다. [(합계 줄 차례, 열, [더하는 줄 차례])]. 「합계 · 계 · 소계 · 총계」 이름의 줄이
    바로 위 묶음(앞 합계 줄 뒤부터)의 같은 열 숫자를 더한 것인지 본다. 더하는 칸이 둘 이상인 열만 낸다."""
    out = []
    body = [i for i, ln in enumerate(lines) if ln.kind == "줄"]
    start = 0
    for pos, i in enumerate(body):
        ln = lines[i]
        if not TOTAL.match(_label(ln.cells)):
            continue
        group = body[start:pos]
        start = pos + 1
        for j, c in enumerate(ln.cells):
            if c.num is None or c.covered:
                continue
            terms = [g for g in group if j < len(lines[g].cells) and lines[g].cells[j].num is not None and not lines[g].cells[j].covered]
            if len(terms) >= 2:
                out.append((i, j, terms))
    return out


# ---------------------------------------------------------------- 쓰기
def _info_rows(d: Draft, command: str) -> list[tuple[str, str]]:
    i = d.info
    return [("바탕 파일", d.source), ("바탕 sha256", d.sha256[:16]), ("바탕 종류", "DART 편집기 파일(dsd)" if d.base == "dsd" else "공시 원문(xml)"),
            ("회사명", i.get("name") or ""), ("문서", i.get("document") or ""), ("기수", str(i.get("term") or "")),
            ("결산일", i.get("period_end") or ""), ("단위", i.get("unit") or ""), ("만든 명령", command),
            ("롤포워드", "했음(당기 칸을 전기로 옮기고 비웠다)" if d.rolled else "안 했음")]


USAGE = ("쓰는 법",
         "1. 각 시트의 C 열부터 고친다. A 열(종류)과 숨긴 B 열(위치)은 그대로 둔다. 회색 칸은 위 칸과 병합된 칸이라 쓰지 않는다.",
         "2. 줄을 더하려면 같은 표 안에 줄을 끼워 넣고 B 열은 비운다. 줄을 지우면 그 줄이 dsd 에서 빠진다(편집기가 지울 수 있게 한 줄만).",
         "3. 주석을 빼려면 목차 시트에서 그 줄을 지운다. 목차의 주석 번호를 고치면 번호를 다시 매긴다.",
         "4. 고친 뒤 python -m audit dsd foot <이 엑셀> 로 검증하고, python -m audit dsd build <이 엑셀> 로 dsd 를 만든다.",
         "5. 표 오른쪽 「검증」 열의 FALSE 는 합계가 맞지 않는 곳이다. 이 열은 dsd 에 들어가지 않는다.")


def write(path: Path, d: Draft, command: str = "") -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = GUIDE
    ws.cell(1, 1, "원고 안내").font = Font(name=wp.FONT, size=14, bold=True)
    for r, (k, v) in enumerate(_info_rows(d, command), 3):
        ws.cell(r, 1, k).font = wp.font(bold=True)
        ws.cell(r, 2, v)
    r = 3 + len(_info_rows(d, command)) + 1
    for line in USAGE:
        ws.cell(r, 1, line).font = wp.font(bold=line == USAGE[0])
        r += 1
    kept = d.info.get("kept_tables") or []
    if kept:
        r += 1
        ws.cell(r, 1, f"작년 숫자를 그대로 둔 표 {len(kept)}개(분홍 칸). 당기 · 전기를 가르지 못해 옮기지 않았다. 회사 자료로 고친다").font = wp.font(bold=True)
        for x in kept:
            r += 1
            ws.cell(r, 1, f"{_sheet_name(x['sheet'])} 표 {x['table']}")
            ws.cell(r, 2, x.get("why") or "")
            ws.cell(r, 1).fill = FILL_KEPT
    stale = set(d.info.get("stale_cells") or [])
    if stale:
        r += 1
        ws.cell(r, 1, f"옮긴 표 안에서 작년 값을 그대로 둔 숫자 칸 {len(stale)}개(분홍 칸). 당기 · 전기 열이 아닌 열(이자율 · 지분율 · 주식수 등)이다. "
                      "올해 값으로 고친다. 표마다 아래 「롤포워드 · 읽기에서 남은 것」 에 있다").font = wp.font(bold=True)
        ws.cell(r, 1).fill = FILL_KEPT
    if d.notes:
        r += 1
        ws.cell(r, 1, "롤포워드 · 읽기에서 남은 것").font = wp.font(bold=True)
        for x in d.notes:
            r += 1
            ws.cell(r, 1, x)
    ws.column_dimensions["A"].width = 18
    ws.column_dimensions["B"].width = 80
    print_setup(ws, 1)
    toc = wb.create_sheet(TOC)
    for j, h in enumerate(("차례", "시트", "주석 번호", "제목"), 1):
        _style_head(toc.cell(3, j, h))
    toc.cell(1, 1, "목차").font = Font(name=wp.FONT, size=14, bold=True)
    toc.cell(2, 1, "줄을 지우면 그 주석을 뺀다. 주석 번호를 고치면 번호를 다시 매긴다(본문의 「주석 N」 도 같이).").font = wp.font(size=9, color=wp.MUTED)
    names = {}
    for k, s in enumerate(d.sheets, 1):
        names[s.key] = _sheet_name(s.key)
        toc.cell(3 + k, 1, k)
        toc.cell(3 + k, 2, names[s.key])
        toc.cell(3 + k, 3, s.note)
        toc.cell(3 + k, 4, s.title[:200])
    for col, w in zip("ABCD", (6, 18, 10, 60)):
        toc.column_dimensions[col].width = w
    pos_rows = []
    kept_at = {(x["sheet"], x["table"]) for x in kept}
    for s in d.sheets:
        pos_rows += _sheet(wb, names[s.key], s, {t for k, t in kept_at if k == s.key}, stale)
    pw = wb.create_sheet(POS)
    for j, h in enumerate(("위치", "요소", "시트", "줄", "칸", "원문 글", "원문 꼴", "판독용 값", "부분 서식"), 1):
        pw.cell(1, j, h)
    for r, row in enumerate(pos_rows, 2):
        for j, v in enumerate(row, 1):
            pw.cell(r, j, v)
    pw.sheet_state = "hidden"
    pw.protection.sheet = True
    ow = wb.create_sheet(ORIG)
    ow.cell(1, 1, "바탕 원문(base64). 고치지 않는다")
    ow.cell(2, 1, "sha256")
    ow.cell(2, 2, hashlib.sha256(d.contents).hexdigest())
    ow.cell(3, 1, "종류")
    ow.cell(3, 2, d.base)
    ow.cell(4, 1, "info")
    ow.cell(4, 2, json.dumps(dict(d.info, notes=d.notes, rolled=d.rolled, source=d.source, source_sha256=d.sha256), ensure_ascii=False))
    for col, blob in ((1, d.contents), (2, d.meta)):
        b64 = base64.b64encode(blob).decode("ascii")
        for k in range(0, len(b64), CHUNK):
            ow.cell(6 + k // CHUNK, col, b64[k:k + CHUNK])
    ow.sheet_state = "hidden"
    ow.protection.sheet = True
    path.parent.mkdir(parents=True, exist_ok=True)
    style.finish(wb)
    wb.save(path)
    # 같은 dsd 면 바이트까지 같은 원고(2026-11-10): 문서 속성의 만든 · 고친 시각과 압축 안 파일 시각을 고정한다.
    # 초안 dsd 의 주석이 이 엑셀의 해시를 적어서, 엑셀이 달라지면 초안 dsd 도 매번 달라졌다
    from .dsd_build import steady_zip

    steady_zip(path, lambda name, data: re.sub(rb"(<dcterms:(?:created|modified)[^>]*>)[^<]*", rb"\g<1>1980-01-01T00:00:00Z", data)
               if name == "docProps/core.xml" else data)
    return path


def _sheet(wb, name: str, s: Sheet, kept: set = frozenset(), stale: set = frozenset()) -> list[tuple]:
    ws = wb.create_sheet(name)
    ws.cell(1, 1, f"{s.key} {s.title[:80]}".strip()).font = Font(name=wp.FONT, size=13, bold=True)
    ws.cell(2, 1, "C 열부터 고친다. 회색 칸은 병합된 칸이다. 표 오른쪽 「검증」 열은 엔진이 넣은 합계 수식이다(dsd 에 들어가지 않는다).").font = wp.font(size=9, color=wp.MUTED)
    for j, h in enumerate(("종류", "위치", "내용"), 1):
        _style_head(ws.cell(3, j, h))
    pos = []
    width = max([len(ln.cells) for ln in s.lines if ln.kind in ("머리", "줄")] + [1])
    r = FIRST
    i = 0
    lines = s.lines
    while i < len(lines):
        ln = lines[i]
        if ln.kind in ("표", "글 표"):
            j = i + 1
            while j < len(lines) and lines[j].kind != "표끝":
                j += 1
            block = lines[i:j + 1]
            r = _table(ws, name, block, r, pos, ln.table in kept, stale)
            i = j + 1
            continue
        ws.cell(r, 1, ln.kind).font = wp.font(size=9, bold=ln.kind == "제목")
        ws.cell(r, 2, ln.loc)
        c = ln.cells[0] if ln.cells else Cell(None)
        x = ws.cell(r, C0, c.text)
        x.alignment = Alignment(wrap_text=True, vertical="top")
        x.font = wp.font(bold=ln.kind == "제목")
        x.data_type = "s"
        n = len(c.text)
        ws.row_dimensions[r].height = min(15 * (c.text.count("\n") + n // 90 + 1), 400)
        if ln.loc is not None:
            pos.append((ln.loc, ln.tag, name, r, L(C0), c.text, "", " ".join(c.text.split()), "Y" if ln.partial else ""))
        r += 1
        i += 1
    ws.column_dimensions["A"].width = 6
    ws.column_dimensions["B"].width = 7
    ws.column_dimensions["B"].hidden = True
    ws.column_dimensions[L(C0)].width = 60 if width <= 2 else 30
    for j in range(C0 + 1, C0 + width + 12):
        ws.column_dimensions[L(j)].width = 15
    ws.freeze_panes = "C4"
    _protect(ws, width + 14)
    print_setup(ws, 3)
    return pos


def _protect(ws, width: int) -> None:
    """B 열(위치)과 병합으로 덮인 칸만 잠근다. 줄 넣기 · 지우기 · 서식은 열어 둔다(설계 8절 9번)."""
    for row in ws.iter_rows(min_row=1, max_row=ws.max_row, max_col=C0 + width):
        for c in row:
            if c.column != 2 and c.protection is not LOCKED and not (c.fill is not None and c.fill.fgColor is not None and c.fill.fgColor.rgb == FILL_COVER.fgColor.rgb):
                c.protection = UNLOCKED
    for j in [1] + list(range(C0, C0 + width + 1)):
        ws.column_dimensions[L(j)].protection = UNLOCKED
    ws.protection.sheet = True
    for a in ("insertRows", "deleteRows", "formatCells", "formatColumns", "formatRows", "sort", "autoFilter", "insertColumns", "deleteColumns"):
        setattr(ws.protection, a, False)


def _table(ws, name: str, block: list[Line], r: int, pos: list, kept: bool = False, stale: set = frozenset()) -> int:
    head = block[0]
    rows = [ln for ln in block if ln.kind in ("머리", "줄")]
    width = max([len(ln.cells) for ln in rows] + [1])
    check0 = C0 + width + 1
    ws.cell(r, 1, head.kind).font = wp.font(size=9, bold=True)
    ws.cell(r, 2, head.loc)
    x = ws.cell(r, C0, head.cells[0].text if head.cells else "")
    x.font = wp.font(size=9, color=GRAY)
    x.fill = FILL_INFO
    ws.cell(r, check0, CHECK).font = wp.font(size=9, bold=True, color=GRAY)
    r += 1
    first = r
    row_at = {}
    for k, ln in enumerate(block[1:-1], 1):
        row_at[k] = r
        ws.cell(r, 1, ln.kind).font = wp.font(size=9)
        ws.cell(r, 2, ln.loc)
        for j, c in enumerate(ln.cells):
            x = ws.cell(r, C0 + j)
            if c.covered:
                x.fill = FILL_COVER
                x.protection = LOCKED
                continue
            if c.num is not None:
                x.value = c.num
                x.number_format = excel_format(c.fmt)
                if kept and ln.kind == "줄" or c.loc in stale:
                    x.fill = FILL_KEPT
            elif not c.text and c.fmt:                          # 롤포워드로 비운 당기 칸: 숫자를 넣으면 원문 꼴로 보이게
                x.number_format = excel_format(c.fmt)
            else:
                x.value = c.text
                x.data_type = "s"
                if "\n" in c.text:
                    x.alignment = Alignment(wrap_text=True, vertical="top")
            if ln.kind == "머리":
                x.font = wp.font(bold=True)
            if c.loc is not None:
                pos.append((c.loc, c.tag, name, r, L(C0 + j), c.text, json.dumps(c.fmt, ensure_ascii=False) if c.fmt else "",
                            c.num if c.num is not None else " ".join(c.text.split()), ""))
        if ln.loc is not None:
            pos.append((ln.loc, "TR", name, r, "", "", "", "", ""))
        r += 1
    for i, j, terms in sum_checks(block[1:-1]):
        tr = row_at[i + 1]
        col = L(C0 + j)
        refs = ",".join(f"{col}{row_at[t + 1]}" for t in terms)
        cell = ws.cell(tr, check0 + j, f"=ROUND(SUM({refs})-{col}{tr},6)=0")
        cell.font = wp.font(size=9, bold=True)
    ws.cell(r, 1, "표끝").font = wp.font(size=9, color=GRAY)
    if head.loc is not None:
        pos.append((head.loc, "TABLE", name, first - 1, "", head.cells[0].text if head.cells else "", "", width, ""))
    return r + 1


# ---------------------------------------------------------------- 읽기
@dataclass
class Read:
    """엑셀에서 읽은 원고. sheets 는 엑셀의 차례(목차 차례), 줄은 엑셀 값. issues 는 원고 검사 줄."""
    contents: bytes
    meta: bytes
    base: str
    info: dict
    sheets: list
    toc: list                                   # [(시트 key, 주석 번호 | None, 제목)] 목차에 남은 줄
    issues: list = field(default_factory=list)
    sha256: str = ""


@dataclass
class RLine:
    kind: str
    loc: int | None
    values: list                                # 엑셀 값(칸마다)
    row: int
    cached: list = field(default_factory=list)  # 수식 칸의 계산값
    gray: list = field(default_factory=list)    # 덮인 칸 색(FILL_COVER)인 칸. 새 줄이 위 줄의 세로 병합에 이어지는지 dsd build 가 본다(2026-11-10)


def issue(kind: str, sheet: str, where: str, what: str, level: str = "확인") -> dict:
    return {"분류": kind, "시트": sheet, "칸": where, "내용": what, "수준": level}


def read(path: Path) -> Read:
    path = Path(path)
    wb = load_workbook(path)
    wbv = load_workbook(path, data_only=True)
    if ORIG not in wb.sheetnames:
        raise ValueError(f"원고 엑셀이 아닙니다(_원본 시트가 없다): {path.name}")
    ow = wb[ORIG]
    sha = str(ow.cell(2, 2).value or "")
    base = str(ow.cell(3, 2).value or "dsd")
    info = json.loads(ow.cell(4, 2).value or "{}")

    def blob(col):
        parts = []
        r = 6
        while ow.cell(r, col).value:
            parts.append(str(ow.cell(r, col).value))
            r += 1
        return base64.b64decode("".join(parts)) if parts else b""

    contents, meta = blob(1), blob(2)
    issues = []
    if hashlib.sha256(contents).hexdigest() != sha:
        raise ValueError("원고 엑셀의 _원본 시트가 상했습니다(해시가 다르다). 원고를 다시 만든다")
    toc = []
    tw = wb[TOC] if TOC in wb.sheetnames else None
    if tw is not None:
        for r in range(4, tw.max_row + 1):
            name = tw.cell(r, 2).value
            if not name:
                continue
            n = tw.cell(r, 3).value
            try:
                n = int(n) if n not in (None, "") else None
            except (TypeError, ValueError):
                issues.append(issue("목차", TOC, f"C{r}", f"주석 번호가 숫자가 아님: {n}", "막음"))
                n = None
            toc.append((str(name), n, str(tw.cell(r, 4).value or "")))
    sheets = []
    skip = {GUIDE, TOC, POS, ORIG}
    for name in wb.sheetnames:
        if name in skip:
            continue
        ws, wv = wb[name], wbv[name]
        lines = []
        width = None
        for r in range(FIRST, ws.max_row + 1):
            kind = ws.cell(r, 1).value
            if kind is None and all(ws.cell(r, c).value in (None, "") for c in range(2, C0 + 3)):
                continue
            kind = str(kind or ("줄" if width is not None else "문단")).strip()
            loc = ws.cell(r, 2).value
            try:
                loc = int(loc) if loc not in (None, "") else None
            except (TypeError, ValueError):
                issues.append(issue("엑셀 손상", name, f"B{r}", f"위치 번호가 숫자가 아님: {loc}", "막음"))
                loc = None
            if kind in ("표", "글 표"):
                width = None
                for c in range(C0 + 1, ws.max_column + 1):
                    if ws.cell(r, c).value == CHECK:
                        width = c - C0 - 1
                        break
                if width is None:
                    width = 0
                    issues.append(issue("엑셀 손상", name, f"A{r}", "표의 「검증」 머리 칸이 없어졌다. 표 넓이를 오른쪽 끝 칸까지로 본다"))
                lines.append(RLine(kind, loc, [], r))
                continue
            if kind == "표끝":
                lines.append(RLine(kind, None, [], r))
                width = None
                continue
            if kind in ("머리", "줄"):
                if width is None:
                    issues.append(issue("엑셀 손상", name, f"A{r}", "「표」 줄 없이 표 줄이 있다. 이 줄은 읽지 않는다", "막음"))
                    continue
                w = width or max(c for c in range(C0, ws.max_column + 1) if ws.cell(r, c).value not in (None, "")) - C0 + 1
                vals = [ws.cell(r, C0 + j).value for j in range(w)]
                cached = [wv.cell(r, C0 + j).value for j in range(w)]
                gray = [_is_cover(ws.cell(r, C0 + j)) for j in range(w)]
                lines.append(RLine(kind, loc, vals, r, cached, gray))
                continue
            vals = [ws.cell(r, C0).value]
            cached = [wv.cell(r, C0).value]
            lines.append(RLine(kind, loc, vals, r, cached))
        if width is not None:
            issues.append(issue("엑셀 손상", name, "", "마지막 표의 「표끝」 줄이 없어졌다. 시트 끝까지를 그 표로 본다"))
        sheets.append((name, lines))
    return Read(contents, meta, base, info, sheets, toc, issues, sha)


def _is_cover(c) -> bool:
    f = c.fill
    rgb = f.fgColor.rgb if f is not None and f.fgColor is not None else None
    return isinstance(rgb, str) and rgb[-6:].upper() == str(FILL_COVER.fgColor.rgb)[-6:].upper()   # 엑셀이 다시 저장하면 앞 두 자리가 00 → FF


def value_text(v, cached=None) -> tuple[str, float | None, str]:
    """엑셀 값 → (글, 숫자, 손상 설명). 숫자는 숫자, 날짜는 손상(엑셀이 글을 날짜로 바꾼 것), 수식은 계산값."""
    if isinstance(v, str) and v.startswith("="):
        if cached is None:
            return "", None, "계산되지 않은 수식(엑셀에서 열어 저장하면 값이 생긴다)"
        v = cached
        note = "수식 칸(dsd 에는 값만 간다)"
    else:
        note = ""
    if v is None:
        return "", None, note
    if isinstance(v, bool):
        return str(v).upper(), None, note
    if isinstance(v, (_dt.datetime, _dt.date)):
        return v.strftime("%Y.%m.%d") if isinstance(v, _dt.date) else str(v), None, "날짜로 바뀐 칸(엑셀이 글을 날짜로 바꿨다)"
    if isinstance(v, (int, float)):
        x = int(v) if float(v).is_integer() else v
        return str(x), x, note
    s = str(v)
    if s.strip() in ERRORS:
        return s, None, f"수식 오류 값 {s.strip()}"
    return s, None, note


def write_issues(wb, issues: list[dict]) -> None:
    ws = wb.create_sheet("원고 검사", 0)
    ws.cell(1, 1, "원고 검사").font = Font(name=wp.FONT, size=14, bold=True)
    ws.cell(2, 1, f"엑셀에서 생긴 손상, dsd 로 옮길 수 있는지, 롤포워드에서 남은 곳 {len(issues)}건. 「막음」 은 dsd 를 만들 때 반영하지 않은 것이다."
            ).font = wp.font(size=9, color=wp.MUTED)
    head = ("수준", "분류", "시트", "칸", "내용")
    for j, h in enumerate(head, 1):
        _style_head(ws.cell(3, j, h))
    for r, x in enumerate(issues, 4):
        for j, h in enumerate(head, 1):
            c = ws.cell(r, j, x.get(h, ""))
            if h == "수준" and x.get(h) == "막음":
                c.font = wp.font(bold=True, color=wp.RED)
            c.alignment = Alignment(wrap_text=h == "내용", vertical="top")
    for col, w in zip("ABCDE", (7, 14, 16, 8, 90)):
        ws.column_dimensions[col].width = w


__all__ = ["write", "read", "Read", "RLine", "issue", "value_text", "write_issues", "sum_checks"]
