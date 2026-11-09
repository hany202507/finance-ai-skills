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

import functools
import json
import re
from datetime import date, datetime
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from . import folder, style

# 서식은 audit/style.py 한 곳에서 정한다(2026-11-03). 여기 이름은 예전 부르는 곳을 위해 남긴다
NAVY, INK, MUTED, RED, GREEN = style.NAVY, style.INK, style.MUTED, style.RED, style.GREEN
FILL_H, FILL_IN, FILL_SUB, FILL_FLAG, FILL_AI = style.FILL_HEAD, style.FILL_IN, style.FILL_SUB, style.FILL_FLAG, style.FILL_AI
THIN, BOX = style.THIN, style.BOX
FONT = style.FONT
WON, PCT = style.WON, style.PCT
font = style.font
INPUT_SHEET, CHECK_SHEET, META_SHEET = "_기입란", "_검산", "_조서"
# AI 작성 칸(2026-11-03). 확인 전 AI 칸은 연보라로 칠하고, 저장할 때 보이는 「AI 작성」 시트와 숨김 「_AI」 에 모은다
AI_SHEET, AI_META, AI_LABEL = "AI 작성", "_AI", "AI 확인: "
AI_HEAD = ["시트", "칸", "AI 가 쓴 것", "근거", "확인(O · X)"]
# 엔진이 확인 전 AI 판독을 글에 옮길 때 붙이는 표시. 이 표시가 든 글 칸은 Book.text 가 AI 칸으로 칠한다
AI_MARKS = ("(AI, 확인 전)", "(AI 판독, 확인 전)", "AI 짝(확인 전)", "AI 판독, 확인 전")
RULES = ("required", "number", "yesno", "date", "optional")
# 조서 상태 칸(2026-10-26, 감사 프로젝트관리 설계 4절). 첫 머리 시트(4000 은 표지)에 한 번 둔다. 담당 · 인차지가 고치고
# 감시 · 보드가 읽는다. 엔진이 조서를 다시 만들 때 사람이 적은 값을 옮겨 싣는다(Book.save).
DOC_STATUSES = ("초안", "작성중", "제출", "검토완료")
APPLIES_VALUES = ("해당", "해당 없음")
L_STATUS, L_APPLIES, L_REASON = "조서 상태", "조서 해당 여부", "해당 없음 사유"
STATE_LABELS = {L_STATUS: "status", L_APPLIES: "applies", L_REASON: "reason"}
SHEET_NAME_MAX = 31
SHEET_NAME_BAD = "/\\?*[]:"
NUMBERED = re.compile(r"^\.\d{2,} ")          # 번호가 붙은 절차 시트 이름 「.01 거래처별」
# 수식 안의 시트 참조: 문자열 상수 · 따옴표 붙은 이름 · 따옴표 없는 이름. 문자열 상수는 건드리지 않으려고 함께 잡는다
_SHEET_REF = re.compile(r'''"(?:[^"]|"")*"|'((?:[^']|'')+)'!|(?<![\w.'])([A-Za-z_가-힣][\w.]*)!''')


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
        # 소규모 감사 건의 필수 조서면 그 근거(한공회 소규모 일반조서목록, 2026-10-26). 머리에 「필수」 로 보인다
        req, basis = folder.required_of(no, case) if folder.is_small(case) else (False, None)
        self.required = basis if req else None
        self.wb = Workbook()
        self.wb.remove(self.wb.active)
        self.inputs: list[tuple] = []     # (sheet, ref, label, rule)
        self.checks: list[tuple] = []     # (label, formula, expected)
        self.state_placed = False
        self.state_inputs: list[tuple] = []   # 조서 상태 칸(sheet, ref, label, rule). 저장 때 `_기입란` 에 붙는다
        self.state_sheet: str | None = None   # 상태 칸을 둘 시트를 정한 책(4000 은 「표지」). None 이면 첫 머리 시트
        self.ai_cells: list[tuple] = []       # AI 작성 칸 (sheet, ref, what, basis, confirmed). 저장 때 「AI 작성」 · 「_AI」 시트(2026-11-03)
        self.summary_at: tuple | None = None  # 「AI 작성 칸 n개 · 엔진 검산 k줄」 을 적을 (시트, 행). 처음 legend 를 둔 시트
        # 엔진이 제안 값을 미리 넣는 기입란 이름(2026-11-03, 4000 표지 성격 · 시기). 다시 만들 때 감사인이 고친 값이 엔진 값보다 앞선다(common.save)
        self.prefill_labels: set = set()
        # 기입란 AI 초안(2026-11-05, audit/drafts.py). 시트마다 초안을 적을 열. draft_column 으로 정한 시트에서만 ask 가 초안을 옆에 둔다
        self.draft_cols: dict[str, int] = {}
        self._drafts: dict | None = None
        self._draft_at: list[tuple] = []      # (시트, -, 초안 칸, 기입란 이름)

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
        if self.state_sheet is None:
            self.status_block(ws, 3, 7)
        self.legend(ws, 5)
        self.required_mark(ws, 3, 9)
        return ws, 7

    def legend(self, ws, row: int) -> None:
        """row 에 칸의 뜻(범례). 저장할 때 같은 칸 맨 앞에 「AI 작성 칸 n개 · 엔진 검산 k줄」 을 붙인다. 책마다 처음 부른 시트 한 곳이다.
        다음 줄(6행)은 조서마다 안내 문장을 쓰는 자리라 비워 둔다(2026-11-03, 6행에 쓰던 첫 판이 2120A · 3800 안내를 덮었다)."""
        ws.cell(row, 1, style.LEGEND).font = font(size=9, color=MUTED, italic=True)
        if self.summary_at is None:
            self.summary_at = (ws.title, row)

    def text(self, ws, row: int, col: int, value, what: str, basis: str = "", **k):
        """글 칸. 확인 전 AI 판독 표시(AI_MARKS)가 들어 있으면 AI 칸(ai), 아니면 보통 칸(put). 엔진 글과 AI 판독이 한 칸에 섞일 때 쓴다."""
        if isinstance(value, str) and any(m in value for m in AI_MARKS):
            k.pop("flag", None)
            k.pop("color", None)
            k.pop("bold", None)
            return self.ai(ws, row, col, value, what=what, basis=basis, wrap=k.pop("wrap", True), fmt=k.pop("fmt", None))
        return self.put(ws, row, col, value, **k)

    def ai(self, ws, row: int, col: int, value, what: str, basis: str = "", confirmed: bool = False, wrap: bool = True, fmt=None):
        """AI 가 쓴 칸(판독 · 사유 · 제안 · 판정 글). 확인 전이면 연보라 · 왼쪽 보라 선으로 칠하고 「AI 작성」 시트에 모은다.
        확인 끝(confirmed)이면 보통 칸으로 두고 숨김 「_AI」 에만 남긴다. 숫자는 엔진만 만든다(AI 칸은 글이다)."""
        c = self.put(ws, row, col, value, fmt=fmt, wrap=wrap)
        if not confirmed:
            c.fill = FILL_AI
            c.border = style.AI_BOX
            c.font = font(color=style.AI_INK)
        self.ai_cells.append((ws.title, c.coordinate, str(what), str(basis or ""), bool(confirmed)))
        return c

    def status_block(self, ws, row: int, col: int) -> None:
        """조서 상태 · 해당 여부 · 해당 없음 사유 칸(두 줄). 책마다 처음 부를 때 한 번만 둔다.
        row 줄: 상태(초안 · 작성중 · 제출 · 검토완료), row+1 줄: 해당 여부와 해당 없음 사유.
        노란 기입란이지만 조서 기입란 목록(self.inputs)과 따로 둔다(self.state_inputs). 저장할 때 `_기입란` 끝에 붙는다."""
        if self.state_placed:
            return
        from openpyxl.worksheet.datavalidation import DataValidation
        self.state_placed = True

        def cell(r, c, label, value=None):
            x = self.put(ws, r, c, value, wrap=False)
            x.fill = FILL_IN
            self.state_inputs.append((ws.title, x.coordinate, label, "optional"))
            return x

        ws.cell(row, col, L_STATUS).font = font(color=MUTED)
        st = cell(row, col + 1, L_STATUS)          # 비워 둔다. 빈 칸은 초안으로 읽는다(엔진은 기입란을 미리 채우지 않는다)
        ws.cell(row + 1, col, L_APPLIES).font = font(color=MUTED)
        ap = cell(row + 1, col + 1, L_APPLIES)     # 빈 칸은 해당으로 읽는다
        ws.cell(row + 1, col + 2, L_REASON).font = font(color=MUTED)
        cell(row + 1, col + 3, L_REASON)
        for x, vals in ((st, DOC_STATUSES), (ap, APPLIES_VALUES)):
            dv = DataValidation(type="list", formula1='"' + ",".join(vals) + '"', allow_blank=True)
            ws.add_data_validation(dv)
            dv.add(x.coordinate)

    def required_mark(self, ws, row: int, col: int) -> None:
        """소규모 필수 조서 표시: (row, col) 에 「필수」, 오른쪽 칸에 근거(아래 줄은 상태 칸의 해당 없음 사유가 쓴다). 소규모가 아니거나 필수가 아니면 쓰지 않는다."""
        if not self.required:
            return
        c = ws.cell(row, col, "필수")
        c.font = font(bold=True, color=NAVY)
        c.border = BOX
        c.alignment = Alignment(horizontal="center")
        ws.cell(row, col + 1, f"소규모기업 필수 조서({self.required})").font = font(size=9, color=MUTED)

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

    def draft_column(self, ws, col: int, width: int = 44) -> None:
        """이 시트의 기입란 AI 초안을 col 열에 둔다(audit/drafts.py). 초안이 하나라도 있을 때만 열 너비를 잡는다."""
        self.draft_cols[ws.title] = col
        if self.drafts():
            ws.column_dimensions[get_column_letter(col)].width = width

    def drafts(self) -> dict:
        if self._drafts is None:
            from . import drafts

            self._drafts = drafts.for_wp(self.d, self.no)
        return self._drafts

    def _draft_beside(self, ws, row: int, col: int, label: str, value) -> None:
        if ws.title not in self.draft_cols or (value is not None and str(value).strip()):
            return
        x = self.drafts().get(label)
        if not x:
            return
        from . import drafts

        c = self.ai(ws, row, col, x["text"], what=f"기입란 초안: {label[:40]}", basis=drafts.basis_text(x.get("basis")))
        self._draft_at.append((ws.title, "", c.coordinate, label))
        # 초안 글이 다 보이게 줄 높이를 늘린다(열 너비 44 에 한글 약 26자)
        need = 15 * min(12, len(str(x["text"])) // 26 + 1)
        cur = ws.row_dimensions[row].height or 15
        if need > cur:
            ws.row_dimensions[row].height = need

    def _drop_filled_drafts(self) -> None:
        """기입란이 (옮겨 적은 값으로) 채워졌으면 그 옆 초안을 지운다. 점검표는 앞 판 값을 ask 뒤에 옮겨 적기 때문이다."""
        refs = {(s, lab): ref for s, ref, lab, _ in self.inputs}
        for sheet, _, ai_ref, label in self._draft_at:
            in_ref = refs.get((sheet, label))
            if in_ref is None:
                continue
            v = self.wb[sheet][in_ref].value
            if v is not None and str(v).strip():
                cell = self.wb[sheet][ai_ref]
                cell.value = None
                cell.fill, cell.border = PatternFill(fill_type=None), Border()
                self.ai_cells = [x for x in self.ai_cells if not (x[0] == sheet and x[1] == ai_ref)]

    def ask(self, ws, row: int, col: int, label: str, rule: str = "required", value=None, fmt=None, wrap=True):
        """회계사 기입란. 노란 칸으로 칠하고 `_기입란` 에 등록한다. 그 기입란에 AI 초안이 있고 비어 있으면 초안 열에 연보라로 둔다."""
        if rule not in RULES:
            raise ValueError(f"기입란 규칙이 아닙니다: {rule}")
        c = self.put(ws, row, col, value, fmt=fmt, wrap=wrap)
        c.fill = FILL_IN
        self.inputs.append((ws.title, c.coordinate, label, rule))
        if label != getattr(self, "_concluding", None) and ws.title in self.draft_cols:
            self._draft_beside(ws, row, self.draft_cols[ws.title], label, value)
        return c

    def conclusion(self, ws, row: int, ncols: int, label: str = "감사 결론") -> int:
        row = self.section(ws, row + 1, label)
        ws.merge_cells(start_row=row, start_column=1, end_row=row + 2, end_column=ncols)
        self._concluding = label            # 결론 초안은 옆이 아니라 아래 줄에 둔다
        c0 = self.ask(ws, row, 1, label, rule="required")
        self._concluding = None
        for r in range(row, row + 3):
            for c in range(1, ncols + 1):
                ws.cell(r, c).fill = FILL_IN
                ws.cell(r, c).border = BOX
        x = self.drafts().get(label) if ws.title in self.draft_cols and c0.value in (None, "") else None
        if x:                       # 결론 초안은 결론 칸 아래 줄에 둔다(2026-11-05)
            from . import drafts

            ws.merge_cells(start_row=row + 3, start_column=1, end_row=row + 3, end_column=ncols)
            ws.row_dimensions[row + 3].height = 15 * max(2, min(8, len(x["text"]) // 90 + 1))
            c = self.ai(ws, row + 3, 1, f"AI 초안(확인 전): {x['text']}", what=f"기입란 초안: {label}", basis=drafts.basis_text(x.get("basis")))
            self._draft_at.append((ws.title, "", c.coordinate, label))
            return row + 5
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
        self.state_inputs = [(new if sh == old else sh, ref, label, rule) for sh, ref, label, rule in self.state_inputs]
        self.ai_cells = [(new if sh == old else sh, ref, what, basis, ok) for sh, ref, what, basis, ok in self.ai_cells]
        if self.summary_at and self.summary_at[0] == old:
            self.summary_at = (new, self.summary_at[1])
        self.checks = [(label, rename_in_formula(formula, old, new), expected) for label, formula, expected in self.checks]

    def order(self, names: list[str]) -> None:
        """시트 순서를 names 대로 놓는다. names 에 없는 시트는 그 뒤에 지금 순서대로 둔다. 없는 이름은 건너뛴다."""
        want = [n for n in names if n in self.wb.sheetnames]
        rest = [n for n in self.wb.sheetnames if n not in want]
        for i, n in enumerate(want + rest):
            ws = self.wb[n]
            self.wb.move_sheet(ws, offset=i - self.wb.index(ws))

    # ---------------------------------------------------------- 저장
    def carry_state(self, path: Path) -> dict:
        """앞 파일(같은 경로, 없으면 같은 폴더의 같은 조서번호 다른 판 가운데 최근)의 조서 상태 칸 값을 새 책에 옮긴다.
        사람이 「제출」 · 「해당 없음」 으로 고친 것을 엔진이 다시 만들어도 지우지 않는다. 옮긴 값 {label: value}."""
        olds = [path] if path.is_file() else []
        if not olds and path.parent.is_dir():
            olds = sorted((p for p in path.parent.glob(f"{self.no}_*.xlsx") if not p.name.startswith("~$")),
                          key=lambda p: p.stat().st_mtime, reverse=True)[:1]
        if not olds:
            return {}
        try:
            got = doc_state(olds[0]) or {}
        except Exception:      # 열려 있거나 동기화 중인 앞 파일. 새 값(초안)으로 둔다
            return {}
        moved = {}
        for sheet, ref, label, _ in self.state_inputs:
            key = STATE_LABELS.get(label)
            if key and got.get(key) not in (None, ""):
                self.wb[sheet][ref].value = got[key]
                moved[label] = got[key]
        return moved

    def _ai_sheets(self, path: Path) -> int:
        """확인 전 AI 칸을 보이는 「AI 작성」 시트에, 전부를 숨김 「_AI」 에 적는다. 확인(O · X) 칸은 기입란(되읽기만)이고
        앞 파일의 같은 이름 값을 옮긴다. 머리 요약 줄도 여기서 쓴다. 확인 전 AI 칸 수."""
        todo = [x for x in self.ai_cells if not x[4]]
        if todo:
            from openpyxl.worksheet.datavalidation import DataValidation
            ws = self.wb.create_sheet(AI_SHEET)
            for i, w in enumerate([18, 10, 60, 40, 12], 1):
                ws.column_dimensions[get_column_letter(i)].width = w
            ws["A1"] = f"{self.no}  {self.title}: AI 작성 칸"
            ws["A1"].font = font(size=style.SIZE_TITLE, bold=True, color=NAVY)
            ws["A2"] = "AI 가 쓴 글(판독 · 사유 · 제안 · 판정)입니다. 숫자는 엔진이 만들었습니다. 칸을 누르면 그 칸으로 갑니다. 읽고 확인 칸에 O · X 를 적어 주십시오"
            ws["A2"].font = font(size=9, color=MUTED, italic=True)
            row = self.head(ws, 4, AI_HEAD)
            dv = DataValidation(type="list", formula1='"O,X"', allow_blank=True)
            ws.add_data_validation(dv)
            old = {}
            if path.is_file():
                try:
                    old = {x["label"]: x["value"] for x in readback(path)
                           if str(x["label"] or "").startswith(AI_LABEL) and not _blank(x["value"])}
                except Exception:          # 열려 있거나 동기화 중인 앞 파일
                    old = {}
            used: set = set()
            for sheet, ref, what, basis, _ in todo:
                self.put(ws, row, 1, sheet)
                link = self.put(ws, row, 2, ref)
                style.link(link, f"{sheet_ref(sheet)}{ref}")
                self.put(ws, row, 3, what, wrap=True)
                self.put(ws, row, 4, basis or None, wrap=True)
                label, n = f"{AI_LABEL}{sheet} {what}"[:200], 2
                while label in used:
                    label, n = f"{AI_LABEL}{sheet} {what} ({n})"[:200], n + 1
                used.add(label)
                c = self.ask(ws, row, 5, label, rule="optional", value=old.get(label), wrap=False)
                dv.add(c.coordinate)
                row += 1
            ws.freeze_panes = "A5"
        if self.summary_at and self.summary_at[0] in self.wb.sheetnames:
            sh, r = self.summary_at
            text = (f"AI 작성 칸 {len(todo)}개(「{AI_SHEET}」 시트에서 확인) · 엔진 검산 {len(self.checks)}줄" if todo
                    else f"AI 작성 칸 없음 · 엔진 검산 {len(self.checks)}줄")
            c = self.wb[sh].cell(r, 1)
            if c.value not in (None, "") and c.value != style.LEGEND:      # 범례가 아닌 글이 있으면 덮지 않는다
                return len(todo)
            c.value = text + (". " + style.LEGEND if c.value == style.LEGEND else "")
            c.font = font(size=9, bold=True, color=style.AI_INK if todo else MUTED)
            if todo:
                style.link(c, f"{sheet_ref(AI_SHEET)}A1")
                c.font = font(size=9, bold=True, color=style.AI_INK, underline="single")
        return len(todo)

    def save(self, path: Path | None = None) -> Path:
        path = Path(path) if path else path_for(self.d, self.no)
        path.parent.mkdir(parents=True, exist_ok=True)
        if self.state_placed:
            self.carry_state(path)
        self._drop_filled_drafts()
        self._ai_sheets(path)
        ws = self.wb.create_sheet(INPUT_SHEET)
        ws.append(["시트", "셀", "항목", "규칙"])
        for row in self.inputs + [x for x in self.state_inputs if x[0] in self.wb.sheetnames]:
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
        if self.ai_cells:                                   # AI 칸이 있는 책만 숨김 「_AI」(확인 끝 칸 포함 전부)를 맨 뒤에 둔다
            meta = self.wb.create_sheet(AI_META)
            meta.append(["시트", "칸", "AI 가 쓴 것", "근거", "확인"])
            for sheet, ref, what, basis, ok in self.ai_cells:
                meta.append([sheet, ref, what, basis, "확인 끝" if ok else "확인 전"])
            meta.sheet_state = "hidden"
        drop_empty_validations(self.wb)
        style.finish(self.wb)
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


def doc_meta(path: Path) -> dict:
    """조서 엑셀을 한 번 열어 {"made_at", "state"} 를 읽는다. state 는 {"status", "applies", "reason"} 이고
    상태 칸이 없는 예전 조서 · 엔진이 만들지 않은 파일이면 None. 감시가 조서마다 부르므로 읽기 전용으로 연다."""
    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        out: dict = {"made_at": None, "state": None}
        names = wb.sheetnames
        if META_SHEET in names:
            for r in wb[META_SHEET].iter_rows(max_row=20, values_only=True):
                if r and str(r[0] or "").strip() == "만든 시각":
                    out["made_at"] = str(r[1] or "") or None
        if INPUT_SHEET in names:
            where = {}
            for r in wb[INPUT_SHEET].iter_rows(min_row=2, values_only=True):
                if r and len(r) >= 3 and r[2] in STATE_LABELS and r[0] in names:
                    where[STATE_LABELS[r[2]]] = (r[0], r[1])
            if where:
                st = {}
                for key, (sheet, ref) in where.items():
                    v = wb[sheet][ref].value
                    st[key] = v.strip() if isinstance(v, str) else v
                out["state"] = {k: st.get(k) for k in ("status", "applies", "reason")}
        return out
    finally:
        wb.close()


def doc_state(path: Path) -> dict | None:
    """조서 상태 칸 {"status", "applies", "reason"}. 칸이 없으면 None."""
    return doc_meta(path)["state"]


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
