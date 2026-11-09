"""4000 계정 조서 골격(2026-10-12): 시트 순서 · 절차 시트 번호 · 주석 검토 · 받은자료 · 줄 많은 표 줄이기.

설계 문서 2~8절이다. 한 파일의 시트 순서는 이렇다.

  표지 → Lead → 절차 시트(.01 <이름>, .02 <이름> …) → .NN 주석 → 요약 시트 → 받은자료

생성기(lead · sales · recalc · vouch)는 시트를 번호 없는 기본 이름으로 만든다. 다 만든 뒤 finish 가 번호를 붙이고
(wp.Book.rename_sheet 가 수식 · 기입란 · 검산 안의 시트 이름을 함께 바꾼다) 순서를 맞춘다.
어느 시트가 절차이고 어느 시트가 요약인지, 시트별 감사절차 한 줄은 definitions/workpapers.yaml 의 sheets 에 있다.
정의에 없는 시트는 절차로 보고 문구 없이 번호만 붙인다.

  plan(b, code, defs)                  지금 책의 시트를 절차 · 요약으로 나누고 번호 붙인 이름을 정한다
  notes_sheet(b, lines, rows, linked)  「주석」 시트(조서 확정 금액 ↔ 회사 제시 주석, 차이는 금액)
  received_sheet(b, d, no, read)       「받은자료」 시트(조서를 만들면서 엔진이 읽은 받은자료와 문서목록의 연결 조서가 이 조서인 받은자료)
  finish(b, code, defs)                절차 시트에 감사절차 한 줄 · 발견사항 · 결론을 붙이고 번호와 순서를 맞춘다
  top_rows(rows, n, amount, keep)      줄이 n 을 넘는 표를 금액 상위 줄과 「기타 (n곳)」 으로 나눈다
"""
from __future__ import annotations

import math
from pathlib import Path

from openpyxl.styles import Alignment
from openpyxl.utils import get_column_letter

from .. import figures, wp
from . import common

COVER, LEAD, NOTES, RECEIVED = "표지", "Lead", "주석", "받은자료"
FIXED = (COVER, LEAD, NOTES, RECEIVED)
PROCEDURE, SUMMARY = "procedure", "summary"
TOP_ROWS = 30
NOTE_UNIT = "주석 단위(원)"
USE_READ, USE_LINKED = "엔진이 읽음", "색인 연결"          # 받은자료 시트의 「쓰임」
LEAD_FIRST = 9          # Lead 리드시트 표의 첫 표시과목 행(머리 6행 + 구역 제목 + 표 머리). 절차 시트가 Lead 를 수식으로 가리킬 때 쓴다


def lead_rows(lines: list[str]) -> dict[str, int]:
    """표시과목 → Lead 리드시트 행. 절차 시트는 Lead 보다 먼저 만들어지므로 이 약속으로 행을 안다(lead._lead_sheet 가 같은 값을 지킨다)."""
    return {line: LEAD_FIRST + i for i, line in enumerate(lines)}


# ---------------------------------------------------------------- 정의
def kind_of(base: str, defs: dict) -> str:
    spec = (defs.get("sheets") or {}).get(base) or {}
    return SUMMARY if spec.get("kind") == SUMMARY else PROCEDURE


def procedure_text(base: str, code: str, defs: dict) -> str:
    """시트의 감사절차 한 줄. 영역마다 다르면 {영역: 문구, default: 문구} 로 적는다. 정의에 없으면 빈 글."""
    t = ((defs.get("sheets") or {}).get(base) or {}).get("procedure")
    if isinstance(t, dict):
        t = t.get(code) or t.get("default")
    return str(t or "").strip()


def top_n(defs: dict) -> int:
    return int((defs.get("summary") or {}).get("top_rows") or TOP_ROWS)


# ---------------------------------------------------------------- 번호
def numbered(n: int, base: str) -> str:
    pre = f".{n:02d} "
    return pre + base[:wp.SHEET_NAME_MAX - len(pre)].rstrip()


def plan(b: wp.Book, code: str, defs: dict) -> dict:
    """지금 책에 있는 시트(표지 · Lead · 주석 · 받은자료 뺌)를 만든 순서대로 절차 · 요약으로 나누고 번호 붙인 이름을 정한다.
    주석은 언제나 마지막 절차다. {"procedures": [(기본 이름, 번호 붙인 이름, 감사절차)], "summaries": [이름], "names": {기본: 실제}}"""
    bases = [s for s in b.wb.sheetnames if s not in FIXED and not s.startswith("_")]
    procs = [s for s in bases if kind_of(s, defs) == PROCEDURE] + [NOTES]
    out = {"procedures": [(s, numbered(n, s), procedure_text(s, code, defs)) for n, s in enumerate(procs, 1)],
           "summaries": [s for s in bases if kind_of(s, defs) == SUMMARY]}
    out["names"] = {COVER: COVER, LEAD: LEAD, RECEIVED: RECEIVED, **{s: s for s in out["summaries"]},
                    **{s: new for s, new, _ in out["procedures"]}}
    return out


# ---------------------------------------------------------------- 줄 많은 표 줄이기
def top_rows(rows: list, n: int, amount, keep=None) -> tuple[list, list]:
    """줄이 n 을 넘으면 금액(절대값) 상위 n 줄과 keep(r) 이 참인 줄을 남긴다. (보일 줄, 「기타」 로 합칠 줄). 보일 줄은 원래 순서다.
    n 이하이거나 합칠 줄이 한 줄뿐이면 줄이지 않는다."""
    if n <= 0 or len(rows) <= n:
        return list(rows), []
    order = sorted(range(len(rows)), key=lambda i: (-abs(amount(rows[i]) or 0), i))
    shown = set(order[:n]) | ({i for i, r in enumerate(rows) if keep(r)} if keep else set())
    rest = [r for i, r in enumerate(rows) if i not in shown]
    if len(rest) < 2:
        return list(rows), []
    return [r for i, r in enumerate(rows) if i in shown], rest


def others_label(rest: list) -> str:
    return f"기타 ({len(rest):,}곳)"


def top_note(total: int, shown: int, rest: int, n: int, kept: str = "", source: str | None = None) -> str:
    """줄인 표 아래에 적는 설명. kept 는 금액 상위가 아니어도 남긴 줄의 조건(없으면 빈 글)."""
    also = f", {kept}" if kept else ""
    src = f" 전체 명세는 받은자료({source})에 있습니다." if source else " 전체 명세는 받은자료에 있습니다."
    return (f"{total:,}곳 가운데 {shown:,}곳(금액 상위 {n:,}곳{also})을 보이고 나머지 {rest:,}곳은 「기타」 한 줄로 합쳤습니다. "
            f"합계와 검산은 전체 금액입니다.{src} 줄 수 기준은 definitions/workpapers.yaml 의 summary.top_rows 입니다")


# ---------------------------------------------------------------- 주석 검토
def notes_sheet(b: wp.Book, lines: list[str], lead_rows: dict[str, int], linked, empty: str | None = None) -> None:
    """모든 4000 조서의 마지막 절차 시트(설계 6절). 줄은 Lead 의 표시과목, 조서 금액은 Lead 확정 금액을 주석 단위로 나눈 수식,
    주석 금액은 기입란, 차이는 금액이다. linked(표시과목) 은 이어진 8400 주석 [(번호, 제목)].
    empty 는 금액 리드시트가 없는 영역(4000CL)에서 대사 줄 대신 적는 안내 글이다."""
    ws, row = b.sheet(NOTES, widths=[22, 18, 18, 16, 18, 18, 16, 30, 30])
    ws.cell(row, 1, NOTE_UNIT).font = wp.font(color=wp.MUTED)
    common.ask(b, ws, row, 2, NOTE_UNIT, rule="number", value=1000, fmt="#,##0", wrap=False)
    unit = f"$B${row}"
    ws.cell(row, 3, "회사 제시 주석이 천원 단위이면 1000, 원 단위이면 1 로 바꿉니다. 조서 금액 열은 Lead 확정 금액을 이 칸으로 나눈 값입니다").font = \
        wp.font(size=9, color=wp.MUTED)
    row += 2
    row = b.section(ws, row, "주석 검토 (조서 확정 금액 ↔ 회사 제시 주석)")
    row = b.head(ws, row, ["표시과목", "조서 당기(주석 단위)", "주석 당기", "차이", "조서 전기(주석 단위)", "주석 전기", "차이",
                           "이어진 8400 주석", "비고"])
    if not lines:
        b.put(ws, row, 1, empty or "Lead 에 표시과목이 없어 대사할 줄이 없습니다. 3650A 계정 매핑을 확인해 주십시오", flag=not empty, wrap=True)
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=9)
        ws.row_dimensions[row].height = 32
        return
    ref = wp.sheet_ref(LEAD)
    div = f'IF(OR({unit}="",{unit}=0),1,{unit})'
    for line in lines:
        lr = lead_rows[line]
        b.put(ws, row, 1, line, bold=True)
        b.put(ws, row, 2, f"=ROUND({ref}E{lr}/{div},0)", fmt=wp.WON)
        common.ask(b, ws, row, 3, f"주석 당기: {line}", rule="optional", fmt=wp.WON, wrap=False)
        b.put(ws, row, 4, f'=IF(C{row}="","",B{row}-C{row})', fmt=wp.WON)
        b.put(ws, row, 5, f'=IF({ref}F{lr}="","",ROUND({ref}F{lr}/{div},0))', fmt=wp.WON)
        common.ask(b, ws, row, 6, f"주석 전기: {line}", rule="optional", fmt=wp.WON, wrap=False)
        b.put(ws, row, 7, f'=IF(OR(E{row}="",F{row}=""),"",E{row}-F{row})', fmt=wp.WON)
        ns = linked(line)
        b.put(ws, row, 8, " · ".join(f"주석 {n}. {t}" for n, t in ns) if ns else "이어진 주석 없음", wrap=True,
              color=None if ns else wp.MUTED)
        common.ask(b, ws, row, 9, f"비고: {line}", rule="optional")
        row += 1
    row += 1
    for t in ("주석 금액은 회사가 제시한 주석에서 감사인이 옮겨 적습니다. 차이는 조서 금액 − 주석 금액이고 금액 그대로 보입니다",
              "단수 차이도 차이 열에 그대로 보입니다. 단수 차이이면 비고에 적어 주십시오",
              "조서 금액은 Lead 의 당기(확정) · 전기(확정)입니다. 8100A 에서 처리를 '수정' 으로 정한 분개가 들어 있습니다"):
        ws.cell(row, 1, t).font = wp.font(size=9, color=wp.MUTED)
        row += 1


# ---------------------------------------------------------------- 받은자료
def received_files(d: Path, no: str, read=()) -> list[dict]:
    """이 조서의 받은자료. 조서를 만들면서 엔진이 읽은 파일(read, common.reading 이 모은 상대경로)과 문서목록에서
    연결 조서(linked_workpapers)에 이 조서번호가 있는 파일이다. 파일마다 use(쓰임)를 붙이고 엔진이 읽은 파일을 먼저 놓는다.
    read 에 있어도 문서목록의 받은자료가 아니면(작년 감사 폴더의 8810 같은 것) 넣지 않는다."""
    read = set(read or ())
    out = []
    for f in figures._docs(d)["files"]:
        if f.get("role") != "received":
            continue
        use = [USE_READ] * (f["path"] in read) + [USE_LINKED] * (no in (f.get("linked_workpapers") or []))
        if use:
            out.append({**f, "use": " · ".join(use)})
    return sorted(out, key=lambda f: (USE_READ not in f["use"], str(f.get("kind") or ""), f["path"]))


def _read_basis(f: dict) -> str:
    facts = f.get("facts") or []
    out = [f"종류 판정 {f.get('kind_basis') or '없음'}"]
    if facts:
        by = sorted({str(x.get("basis") or "") for x in facts} - {""})
        out.append(f"판독 사실 {len(facts)}건({' · '.join(by)})" if by else f"판독 사실 {len(facts)}건")
    if f.get("read_error"):
        out.append("판독 못 함: " + str(f["read_error"]))
    return ", ".join(out)


def received_sheet(b: wp.Book, d: Path, no: str, read=()) -> list[dict]:
    """이 조서가 쓴 받은자료 목록(설계 7절). 원자료는 조서에 옮기지 않고 파일 이름만 적는다.
    「쓰임」 열은 엔진이 읽음(이 조서의 숫자를 가져온 파일) · 색인 연결(문서목록의 연결 조서) 가운데 맞는 것을 적는다."""
    files = received_files(d, no, read)
    ws, row = b.sheet(RECEIVED, widths=[26, 56, 16, 34, 12, 24])
    ws.cell(6, 1, "이 조서를 만들면서 엔진이 읽은 받은자료와, 문서목록(_색인/문서목록.json)에서 연결 조서가 이 조서인 받은자료. "
                  "원자료는 받은자료 폴더에 두고 조서에는 요약과 표본만 싣습니다").font = wp.font(size=9, color=wp.MUTED)
    if not files:
        b.put(ws, row, 1, "엔진이 읽은 받은자료와 색인에서 이 조서와 이어진 받은자료가 없습니다", wrap=True)
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=6)
        return files
    n_read = sum(1 for f in files if USE_READ in f["use"])
    n_link = sum(1 for f in files if USE_LINKED in f["use"])
    row = b.section(ws, row, f"받은자료 {len(files)}개 ({USE_READ} {n_read}개 · {USE_LINKED} {n_link}개)")
    row = b.head(ws, row, ["종류", "파일", "기간", "판독 근거", "확인 여부", "쓰임"])
    for f in files:
        ok = bool(f.get("confirmed"))
        b.put(ws, row, 1, f.get("kind"), wrap=True)
        b.put(ws, row, 2, f["path"], wrap=True)
        b.put(ws, row, 3, f.get("period") or "")
        b.put(ws, row, 4, _read_basis(f), wrap=True)
        b.put(ws, row, 5, "확인" if ok else "확인 전", flag=not ok)
        b.put(ws, row, 6, f["use"], wrap=True)
        row += 1
    for t in (f"쓰임의 「{USE_READ}」 은 이 조서를 만들면서 엔진이 숫자를 가져온 파일입니다(시산표 · 분개장 · 명세서 · 대장 · 잔액증명). "
              "열어 보았으나 쓸 표가 없던 파일과 이름으로만 이은 표본 증빙은 적지 않습니다",
              f"쓰임의 「{USE_LINKED}」 은 문서목록에서 연결 조서가 이 조서인 파일입니다. 연결 조서는 definitions/received_links.yaml 과 판독 결과로 정합니다",
              "확인 전인 자료는 종류 · 판독 사실을 회계사가 확인하기 전입니다(감사-맥락색인)"):
        row += 1
        ws.cell(row, 1, t).font = wp.font(size=9, color=wp.MUTED)
    return files


# ---------------------------------------------------------------- 마무리
def _width(ws, last_col: int) -> float:
    return sum((ws.column_dimensions[get_column_letter(c)].width or 9) for c in range(1, last_col + 1))


def _procedure_line(ws, text: str) -> None:
    """6행에 감사절차 한 줄을 적는다. 생성기가 6행에 이미 근거 문구를 적었으면 그 위 줄에 붙인다."""
    if not text:
        return
    c = ws.cell(6, 1)
    line = "감사절차: " + text
    if c.value in (None, ""):
        c.value = line
        c.font = wp.font(size=9, bold=True, color=wp.NAVY)
        return
    old = str(c.value)
    c.value = line + "\n" + old
    span = next((r for r in ws.merged_cells.ranges if r.min_row <= 6 <= r.max_row and r.min_col == 1), None)
    last = span.max_col if span else min(max(ws.max_column, 2), 9)
    if span is None:
        ws.merge_cells(start_row=6, start_column=1, end_row=6, end_column=last)
    c.alignment = Alignment(wrap_text=True, vertical="top")
    per_line = max(_width(ws, last) / 1.7, 20)                       # 한글 한 글자를 열 너비 1.7 로 본다
    lines = sum(max(1, math.ceil(len(t) / per_line)) for t in (line, old))
    ws.row_dimensions[6].height = max(ws.row_dimensions[6].height or 0, 14 * lines)


def _findings(b: wp.Book, ws, base: str) -> None:
    """절차 시트 맨 아래 「발견사항」 · 「결론」 선택 기입란. 이름은 번호 없는 시트 이름으로 붙인다."""
    ncols = min(max(ws.max_column, 4), 8)
    row = ws.max_row + 2
    for lab in ("발견사항", "결론"):
        row = b.section(ws, row, lab)
        common.ask(b, ws, row, 1, f"{lab}: {base}", rule="optional")
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=ncols)
        for c in range(1, ncols + 1):
            ws.cell(row, c).fill = wp.FILL_IN
            ws.cell(row, c).border = wp.BOX
        ws.row_dimensions[row].height = 32
        row += 2


def finish(b: wp.Book, code: str, defs: dict) -> dict:
    """조서를 다 만든 뒤 한 번 부른다. 절차 시트마다 감사절차 한 줄 · 발견사항 · 결론을 붙이고, 번호를 붙여 이름을 바꾸고,
    표지 → Lead → 절차 → 주석 → 요약 → 받은자료 순서로 놓는다. plan 과 같은 결과를 돌려준다."""
    p = plan(b, code, defs)
    for base, _, text in p["procedures"]:
        if base in b.wb.sheetnames:
            _procedure_line(b.wb[base], text)
            _findings(b, b.wb[base], base)
    for base, new, _ in p["procedures"]:
        if base in b.wb.sheetnames:
            b.rename_sheet(base, new)
    b.order([COVER, LEAD] + [new for _, new, _ in p["procedures"]] + p["summaries"] + [RECEIVED])
    return p
