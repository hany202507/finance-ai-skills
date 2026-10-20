"""조서 엑셀 공통: 모양 · 기입란 등록 · 되읽기 · 검사 · 저장 위치 (R3~R5 공통, 2026-10-05).

조서마다 생성기는 단계 모듈(analysis · workpapers · report · close)에 두고, 이 모듈만으로 책을 만든다.
엔진이 채운 칸과 회계사 기입란(노란 칸)을 나누고, 기입란은 숨김 시트 `_기입란` 에 적어 둔다.
회계사가 채워 다시 저장한 파일을 되읽을 때는 이 목록에 있는 셀만 읽는다(다른 셀은 보지 않는다).

  b = Book(d, "2120A", standard="감사기준서 520")      감사 폴더 d 의 감사건 · 회사제시 판에서 머리를 채운다
  ws, row = b.sheet("분석", widths=[...])
  b.put(ws, row, 1, 1234, fmt=WON)
  b.ask(ws, row, 5, "차이 설명", rule="required")         기입란 등록
  row = b.conclusion(ws, row, 6)                           결론 칸(기입란, required)
  path = b.save()                                          표준 폴더에 <번호>_<이름>[_v판].xlsx 로 저장
  readback(path) -> [{sheet, ref, label, rule, value}]
  check(path) -> list[str]                                 비어 있는 required, 규칙 위반, 엔진 검산(`_검산` 시트) 실패
  mark_checked(d, no, problems)                            조서목록 상태를 검사 통과 · 작성중 으로 바꾼다

규칙: required(비우면 안 됨) · number(숫자) · yesno(예/아니오) · date(날짜) · optional(되읽기만)
검산: b.verify(label, formula_or_value, expected) 는 `_검산` 시트에 엔진 기대값과 셀 수식을 함께 둔다.
엑셀이 계산하지 않은 파일(openpyxl 저장 직후)은 수식 값을 모르므로, 엔진이 쓴 기대값과 비교한다.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from . import folder

NAVY, INK, MUTED = "1B2A4A", "1A1C19", "6B7167"
FILL_H = PatternFill("solid", fgColor=NAVY)
FILL_IN = PatternFill("solid", fgColor="FFF2CC")
FILL_SUB = PatternFill("solid", fgColor="F1F6EF")
FILL_FLAG = PatternFill("solid", fgColor="F8E1E5")
THIN = Side(style="thin", color="DFE5DB")
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
FONT = "맑은 고딕"
WON = '#,##0;[Red]-#,##0;"-"'
PCT = '0.0%;[Red]-0.0%;"-"'
INPUT_SHEET, CHECK_SHEET, META_SHEET = "_기입란", "_검산", "_조서"
RULES = ("required", "number", "yesno", "date", "optional")
SHEET_NAME_MAX = 31
SHEET_NAME_BAD = "/\\?*[]:"
NUMBERED = re.compile(r"^\.\d{2,} ")          # 번호가 붙은 절차 시트 이름 「.01 거래처별」
# 수식 안의 시트 참조: 문자열 상수 · 따옴표 붙은 이름 · 따옴표 없는 이름. 문자열 상수는 건드리지 않으려고 함께 잡는다
_SHEET_REF = re.compile(r'''"(?:[^"]|"")*"|'((?:[^']|'')+)'!|(?<![\w.'])([A-Za-z_가-힣][\w.]*)!''')


def font(**k):
    return Font(name=FONT, size=k.pop("size", 10), **k)


def base_name(sheet: str) -> str:
    """번호를 뗀 시트 이름. 「.01 거래처별」 → 「거래처별」. 번호가 없으면 그대로."""
    return NUMBERED.sub("", str(sheet))


def find_sheet(names, base: str) -> str | None:
    """시트 이름 목록(또는 워크북)에서 기본 이름이 base 인 시트의 실제 이름. 번호가 붙었든 아니든 찾는다."""
    names = getattr(names, "sheetnames", names)
    return next((n for n in names if n == base or base_name(n) == base), None)


def sheet_ref(name: str) -> str:
    """수식에 쓰는 시트 참조. 언제나 따옴표를 붙인다. 「'.01 거래처별'!」"""
    return "'" + name.replace("'", "''") + "'!"


def rename_in_formula(formula, old: str, new: str):
    """수식 안의 시트 참조 「'옛이름'!」 · 「옛이름!」 을 새 이름으로 바꾼다. 수식이 아니면(= 로 시작하지 않으면) 그대로."""
    if not isinstance(formula, str) or not formula.startswith("="):
        return formula

    def repl(m):
        quoted, bare = m.group(1), m.group(2)
        if (quoted is not None and quoted.replace("''", "'") == old) or (bare is not None and bare == old):
            return sheet_ref(new)
        return m.group(0)

    return _SHEET_REF.sub(repl, formula)


def _case(d: Path) -> dict:
    p = Path(d) / "_색인" / "감사건.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def path_for(d: Path, no: str, ext: str = ".xlsx", version: str | None = None) -> Path:
    """표준 폴더와 이름 규칙대로 조서 경로를 정한다. 판은 회사제시 숫자가 들어가는 조서에만 붙인다."""
    std = folder.load_standard()
    sub = folder._wp_folder_map(std).get(no) or ("4000 계정별" if folder._is_area(no) else None)
    if sub is None:
        raise ValueError(f"표준에 없는 조서번호입니다: {no}")
    name = (std.get("workpaper_names") or {}).get(no, "")
    stem = f"{no}_{name}" if name else no
    uses = {str(x) for x in std.get("uses_company_figures", [])}
    if no in uses or (folder._is_area(no) and "4000" in uses):
        ver = version or _case(d).get("company_version")
        if ver:
            stem += f"_{ver if ver.startswith('v') else 'v' + ver}"
    return Path(d) / sub / f"{stem}{ext}"


class Book:
    def __init__(self, d: Path, no: str, title: str | None = None, standard: str = "", preparer: str | None = None):
        self.d, self.no = Path(d), no
        std = folder.load_standard()
        self.title = title or (std.get("workpaper_names") or {}).get(no, no)
        self.standard = standard
        case = _case(d)
        comp = case.get("company") or {}
        self.company = comp.get("name") if isinstance(comp, dict) else str(comp or "")
        self.fy_end = case.get("fiscal_year_end") or ""
        self.version = case.get("company_version")
        self.preparer = preparer or f"엔진 초안 {date.today().isoformat()}"
        self.wb = Workbook()
        self.wb.remove(self.wb.active)
        self.inputs: list[tuple] = []     # (sheet, ref, label, rule)
        self.checks: list[tuple] = []     # (label, formula, expected)

    # ---------------------------------------------------------- 모양
    def sheet(self, name: str, widths: list[int], head: bool = True):
        """시트를 만들고 머리(조서번호 · 회사명 · 결산일 · 작성자 · 검토자)를 적는다. (시트, 다음 행).
        head=False 이면 열 너비만 잡고 1행부터 비워 둔다(4000 표지처럼 머리 배치가 다른 시트)."""
        ws = self.wb.create_sheet(name[:SHEET_NAME_MAX])
        for i, w in enumerate(widths, 1):
            ws.column_dimensions[get_column_letter(i)].width = w
        if not head:
            return ws, 1
        ws["A1"] = f"{self.no}  {self.title}"
        ws["A1"].font = font(size=14, bold=True, color=NAVY)
        ws["A2"] = " · ".join(x for x in (self.standard, f"회사제시 {self.version}" if self.version else "") if x)
        ws["A2"].font = font(size=9, color=MUTED)
        for r, (a, b, c) in enumerate([("회사명", self.company, "작성자"), ("결산일", self.fy_end, "검토자")], 3):
            ws.cell(r, 1, a).font = font(color=MUTED)
            ws.cell(r, 2, b).font = font(bold=True)
            ws.cell(r, 4, c).font = font(color=MUTED)
            if c == "작성자":
                ws.cell(r, 5, self.preparer).font = font()
            else:
                self.ask(ws, r, 5, "검토자", rule="optional")
        ws.cell(5, 1, "노란 칸은 감사인 기입란. 나머지는 엔진이 채운 값과 수식").font = font(size=9, color=MUTED, italic=True)
        return ws, 7

    def section(self, ws, row: int, text: str) -> int:
        ws.cell(row, 1, text).font = font(size=11, bold=True, color=NAVY)
        return row + 1

    def head(self, ws, row: int, heads: list[str], col: int = 1) -> int:
        for i, h in enumerate(heads):
            c = ws.cell(row, col + i, h)
            c.font = font(bold=True, color="FFFFFF")
            c.fill = FILL_H
            c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            c.border = BOX
        ws.row_dimensions[row].height = 30
        return row + 1

    def put(self, ws, row: int, col: int, value, fmt=None, bold=False, wrap=False, flag=False, color=None):
        c = ws.cell(row, col, value)
        c.font = font(bold=bold, color=color or INK)
        c.border = BOX
        if fmt:
            c.number_format = fmt
        if flag:
            c.fill = FILL_FLAG
        c.alignment = Alignment(vertical="top", wrap_text=wrap, horizontal="right" if fmt and not wrap else None)
        return c

    def ask(self, ws, row: int, col: int, label: str, rule: str = "required", value=None, fmt=None, wrap=True):
        """회계사 기입란. 노란 칸으로 칠하고 `_기입란` 에 등록한다."""
        if rule not in RULES:
            raise ValueError(f"기입란 규칙이 아닙니다: {rule}")
        c = self.put(ws, row, col, value, fmt=fmt, wrap=wrap)
        c.fill = FILL_IN
        self.inputs.append((ws.title, c.coordinate, label, rule))
        return c

    def conclusion(self, ws, row: int, ncols: int, label: str = "감사 결론") -> int:
        row = self.section(ws, row + 1, label)
        ws.merge_cells(start_row=row, start_column=1, end_row=row + 2, end_column=ncols)
        self.ask(ws, row, 1, label, rule="required")
        for r in range(row, row + 3):
            for c in range(1, ncols + 1):
                ws.cell(r, c).fill = FILL_IN
                ws.cell(r, c).border = BOX
        return row + 4

    def verify(self, label: str, formula: str, expected) -> None:
        """엔진 검산 한 줄. formula 는 엑셀 수식(예: "=SUM('Lead'!C8:C20)"), expected 는 엔진이 계산한 값."""
        self.checks.append((label, formula, expected))

    # ---------------------------------------------------------- 시트 이름 · 순서
    def rename_sheet(self, old: str, new: str) -> None:
        """시트 이름을 바꾸고, 수식(= 로 시작하는 문자열 칸) 안의 「'옛이름'!」 · 「옛이름!」, 기입란 목록, 검산 수식의 시트 이름을 함께 바꾼다.
        4000 조서가 절차 시트에 번호를 붙일 때 쓴다(생성기는 번호 없는 이름으로 수식을 쓴다)."""
        if old not in self.wb.sheetnames:
            raise KeyError(f"없는 시트입니다: {old}")
        if old == new:
            return
        bad = [ch for ch in SHEET_NAME_BAD if ch in new]
        if not new or len(new) > SHEET_NAME_MAX or bad or new.startswith("'") or new.endswith("'"):
            raise ValueError(f"시트 이름으로 쓸 수 없습니다(31자 이하, {' '.join(SHEET_NAME_BAD)} 금지): {new}")
        if new in self.wb.sheetnames:
            raise ValueError(f"같은 이름의 시트가 이미 있습니다: {new}")
        self.wb[old].title = new
        for ws in self.wb.worksheets:
            for row in ws.iter_rows():
                for c in row:
                    if isinstance(c.value, str) and c.value.startswith("="):
                        c.value = rename_in_formula(c.value, old, new)
        self.inputs = [(new if sh == old else sh, ref, label, rule) for sh, ref, label, rule in self.inputs]
        self.checks = [(label, rename_in_formula(formula, old, new), expected) for label, formula, expected in self.checks]

    def order(self, names: list[str]) -> None:
        """시트 순서를 names 대로 놓는다. names 에 없는 시트는 그 뒤에 지금 순서대로 둔다. 없는 이름은 건너뛴다."""
        want = [n for n in names if n in self.wb.sheetnames]
        rest = [n for n in self.wb.sheetnames if n not in want]
        for i, n in enumerate(want + rest):
            ws = self.wb[n]
            self.wb.move_sheet(ws, offset=i - self.wb.index(ws))

    # ---------------------------------------------------------- 저장
    def save(self, path: Path | None = None) -> Path:
        path = Path(path) if path else path_for(self.d, self.no)
        path.parent.mkdir(parents=True, exist_ok=True)
        ws = self.wb.create_sheet(INPUT_SHEET)
        ws.append(["시트", "셀", "항목", "규칙"])
        for row in self.inputs:
            ws.append(list(row))
        ws.sheet_state = "hidden"
        ws = self.wb.create_sheet(CHECK_SHEET)
        ws.append(["검산", "수식", "엔진 기대값"])
        for label, formula, expected in self.checks:
            ws.append([label, formula, expected])
        ws.sheet_state = "hidden"
        ws = self.wb.create_sheet(META_SHEET)
        for k, v in (("조서번호", self.no), ("이름", self.title), ("회사제시 판", self.version or ""),
                     ("만든 시각", datetime.now().strftime("%Y-%m-%d %H:%M")), ("만든 것", "audit 엔진")):
            ws.append([k, v])
        ws.sheet_state = "hidden"
        drop_empty_validations(self.wb)
        self.wb.save(path)
        return path


def drop_empty_validations(wb) -> int:
    """칸이 하나도 없는 데이터 검증을 시트에서 뺀다. 빈 dataValidations 요소가 있으면 엑셀이 책을 열지 못한다."""
    n = 0
    for ws in wb.worksheets:
        dvs = ws.data_validations
        keep = [dv for dv in dvs.dataValidation if dv.sqref and str(dv.sqref).strip()]
        n += len(dvs.dataValidation) - len(keep)
        dvs.dataValidation = keep
    return n


# ---------------------------------------------------------------- 되읽기 · 검사
def readback(path: Path) -> list[dict]:
    wb = load_workbook(path, data_only=True)
    if INPUT_SHEET not in wb.sheetnames:
        return []
    out = []
    for sheet, ref, label, rule in wb[INPUT_SHEET].iter_rows(min_row=2, values_only=True):
        if not sheet:
            continue
        v = wb[sheet][ref].value if sheet in wb.sheetnames else None
        out.append({"sheet": sheet, "ref": ref, "label": label, "rule": rule, "value": v})
    return out


def _blank(v) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


def check(path: Path) -> list[str]:
    """기입란 규칙과 엔진 검산을 본다. 문제가 없으면 빈 목록."""
    probs = []
    for x in readback(path):
        v, rule, where = x["value"], x["rule"], f"{x['sheet']}!{x['ref']} {x['label']}"
        if rule == "optional":
            continue
        if _blank(v):
            probs.append(f"비어 있음: {where}")
        elif rule == "number" and not isinstance(v, (int, float)):
            probs.append(f"숫자가 아님: {where} = {v}")
        elif rule == "yesno" and str(v).strip() not in ("예", "아니오", "해당 없음"):
            probs.append(f"예 · 아니오 · 해당 없음 중 하나여야 함: {where} = {v}")
        elif rule == "date" and not isinstance(v, (date, datetime)):
            probs.append(f"날짜가 아님: {where} = {v}")
    wb = load_workbook(path, data_only=True)
    if CHECK_SHEET in wb.sheetnames:
        wbf = load_workbook(path, data_only=False)
        for i, (label, formula, expected) in enumerate(wb[CHECK_SHEET].iter_rows(min_row=2, values_only=True), 2):
            if not label:
                continue
            got = wb[CHECK_SHEET].cell(i, 2).value
            if isinstance(wbf[CHECK_SHEET].cell(i, 2).value, str) and got is None:
                continue        # 엑셀이 아직 계산하지 않은 수식. 엔진 기대값은 생성 때 맞춰 두었다
            if isinstance(expected, (int, float)) and isinstance(got, (int, float)) and abs(got - expected) > 0.5:
                probs.append(f"검산 불일치: {label} 엑셀 {got:,.0f} · 엔진 {expected:,.0f}")
    return probs


DOC_MARKS = ("【기입", "[기입란")       # 워드 · HTML 초안의 기입란 표시(보고 단계 · 시작 자료 두 꼴)


def doc_marks(path: Path) -> int:
    """워드(.docx) · HTML 초안에 남은 기입란 수."""
    path = Path(path)
    if path.suffix.lower() == ".docx":
        from docx import Document

        doc = Document(str(path))
        texts = [p.text for p in doc.paragraphs]
        texts += [c.text for tb in doc.tables for row in tb.rows for c in row.cells]
    else:
        texts = [path.read_text(encoding="utf-8")]
    return sum(s.count(m) for s in texts for m in DOC_MARKS)


def check_doc(path: Path) -> list[str]:
    n = doc_marks(path)
    return [f"기입란 {n}칸 남음: {Path(path).name}"] if n else []


def mark_checked(d: Path, no: str, problems: list[str], now: str | None = None) -> str:
    """검사 결과로 조서목록 상태를 바꾼다. 문제가 없으면 검사 통과, 있으면 작성중."""
    d = Path(d)
    p = d / "_색인" / "조서목록.json"
    wps = json.loads(p.read_text(encoding="utf-8"))
    w = next((x for x in wps.get("workpapers", []) if x.get("no") == no), None)
    if w is None:
        raise KeyError(f"조서목록에 없는 조서입니다: {no}")
    if problems:
        w["status"] = "작성중"
        w["status_basis"] = f"검사 {len(problems)}건 남음: " + "; ".join(problems[:3])
    elif w.get("status") != "검토 끝":       # 검토가 끝난 조서는 다시 검사해도 내리지 않는다
        w["status"] = "검사 통과"
        w["status_basis"] = "검사 통과(기입란 · 검산)"
    if not problems:
        w["needs_recheck"] = False
    # 검사한 그 파일의 해시를 적는다. 그래야 다음 scan 이 '검사 뒤 바뀐 파일'로 보지 않는다
    if w.get("file") and (d / w["file"]).exists():
        w["sha256"] = folder._sha(d / w["file"])
    folder._write(p, wps)
    folder.validate_index(d)
    return w["status"]
