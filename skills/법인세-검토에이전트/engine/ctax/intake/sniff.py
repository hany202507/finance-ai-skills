"""받은자료 파일 종류를 머리줄로 가린다. 파일 이름은 믿지 않는다(계정코드 힌트로만 쓴다).

kind: journal · bs · is · partner_ledger · account_detail · trial_balance · prior_pdf · unknown
form(꼴): 분개장 wehago(11열) · douzone_erp(10열), 계정명세서 B(7열) · douzone_blocks(BIFF 블록)

11-08(제품 vfs.sniff · files/sheet.py 비교): 1행이 머리줄이 아니면 앞 15행 안에서 머리줄을 찾아 그 줄부터 읽고(find_form),
시트가 여럿이면 시트마다 가리고(sniff_sheets), 확장자가 아니라 앞 바이트로 xlsx · xls 를 가린다(xlsxread.file_format).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from . import douzone
from .xlsxread import Unreadable, compact, file_format, sheets, strip_no

JOURNAL_KEYS = ("전표일자", "전표번호", "계정과목", "차변", "대변")
A_HEAD = ["code", "거래처", "전기(월)이월", "차변", "대변", "잔액"]
B_HEAD = ["코드", "계정과목명", "적요", "코드", "거래처명", "금액", "비고"]
SUFFIXES = (".xlsx", ".xlsm", ".xls")
HEAD_SCAN = 15                   # 머리줄을 찾는 앞쪽 행 수(제목 · 회사명 · 기간 · 빈 줄 건너뛰기)


def _head(row) -> list[str]:
    cells = [compact(c) for c in (row or [])]
    while cells and cells[-1] == "":
        cells.pop()
    return cells


def form_of_rows(rs: list[list]) -> tuple[str, str]:
    """(kind, form). form 은 분개장 · 계정명세서에서만 뜻이 있다. 머리줄은 rs[0] 이다(앞 제목 줄은 find_form 이 건너뛴다)."""
    if not rs:
        return "unknown", ""
    head = _head(rs[0])
    low = [h.lower() for h in head]
    if all(k in head for k in JOURNAL_KEYS):
        return "journal", "wehago"
    if douzone.is_journal_head(head):
        return "journal", "douzone_erp"
    if low[:6] == A_HEAD:
        return "partner_ledger", "A"
    if head[:7] == B_HEAD or (head[:6] == B_HEAD[:6]):
        return "account_detail", "B"
    if douzone.is_tb_rows(rs):
        return "trial_balance", "douzone_erp"
    if douzone.is_detail_rows(rs):
        return "account_detail", "douzone_blocks"
    if head and head[0] in ("과목", "계정과목") and any("(당)기" in h or "당기" in h for h in head[1:]):
        labels = [compact(r[0]) for r in rs[1:] if r and r[0] is not None]
        names = {strip_no(lb) for lb in labels}
        if names & {"자산총계", "부채및자본총계", "부채총계", "자본총계"} or "자산" in labels:
            return "bs", ""
        if any(re.search(r"(당기순(이익|손실|손익)|매출액|영업외수익)$", n) for n in names):
            return "is", ""
    return "unknown", ""


def _is_head(row) -> bool:
    """머리줄로 보이는 줄: 분개장(위하고 · 더존 ERP), 거래처원장 A 꼴, 계정명세서 B 꼴, 재무제표 「과목」 줄."""
    head = _head(row)
    if not head:
        return False
    if all(k in head for k in JOURNAL_KEYS) or douzone.is_journal_head(head):
        return True
    if [h.lower() for h in head[:6]] == A_HEAD or head[:6] == B_HEAD[:6]:
        return True
    return head[0] in ("과목", "계정과목") and any("(당)기" in h or "당기" in h for h in head[1:])


def find_form(rs: list[list]) -> tuple[str, str, int]:
    """(kind, form, off). 1행으로 못 가리면 앞 15행 안의 머리줄부터 본다. off 는 건너뛴 행 수(rs[off] 가 머리줄)."""
    kind, form = form_of_rows(rs)
    if kind != "unknown":
        return kind, form, 0
    for off in range(1, min(HEAD_SCAN, len(rs))):
        if _is_head(rs[off]):
            k, f = form_of_rows(rs[off:])
            if k != "unknown":
                return k, f, off
    return "unknown", "", 0


def kind_of_rows(rs: list[list]) -> str:
    """앞쪽 몇 행으로 종류를 정한다. 재무제표는 본문까지 봐야 재무상태표 · 손익계산서가 갈린다."""
    return find_form(rs)[0]


@dataclass
class Piece:
    """파일 안 시트 하나를 가린 결과. rows 는 머리줄부터(off 행을 건너뛴 뒤)."""
    sheet: str
    kind: str
    form: str
    rows: list[list] | None
    off: int = 0
    notes: list[str] = field(default_factory=list)
    index: int = 0                 # 통합 문서 안 시트 순서(0 이 첫 시트)


def _empty(rs: list[list]) -> bool:
    return not any(c not in (None, "") for r in rs for c in (r or []))


def format_note(path: Path) -> str:
    """확장자와 속(앞 바이트)이 다르면 한 줄 설명. 같으면 빈 글."""
    real = file_format(path)
    suf = path.suffix.lower()
    if real == "xlsx" and suf == ".xls":
        return "확장자는 .xls 인데 속은 xlsx(zip) 라 xlsx 로 읽었습니다"
    if real == "xls" and suf in (".xlsx", ".xlsm"):
        return f"확장자는 {suf} 인데 속은 xls(BIFF) 라 xls 로 읽었습니다"
    return ""


def sniff_sheets(path: Path) -> list[Piece]:
    """시트마다 가린 조각(빈 시트는 뺀다). 읽지 못하면 [unreadable 한 조각], 엑셀이 아니면 한 조각.
    확장자와 속이 다른 파일은 첫 조각 notes 에 적는다."""
    suf = path.suffix.lower()
    if suf == ".pdf":
        return [Piece("", "prior_pdf", "", None)]
    if suf not in SUFFIXES:
        return [Piece("", "unknown", "", None)]
    try:
        books = sheets(path)
    except Unreadable:
        return [Piece("", "unreadable", "", None)]
    out = []
    for i, (name, rs) in enumerate(books):
        if _empty(rs):
            continue
        kind, form, off = find_form(rs)
        out.append(Piece(name, kind, form, rs[off:] if off else rs, off, index=i))
    if not out:
        out = [Piece(books[0][0] if books else "", "unknown", "", books[0][1] if books else [])]
    note = format_note(path)
    if note:
        out[0].notes.append(note)
    return out


def sniff(path: Path) -> tuple[str, list[list] | None, str]:
    """(kind, 행 목록, form). 분개장은 행 전체를 돌려준다(다시 읽지 않게). 읽지 못하면 ('unreadable', None, '').
    시트가 여럿이면 종류를 가린 첫 시트(없으면 첫 시트). 행은 머리줄부터다."""
    ps = sniff_sheets(path)
    p = next((x for x in ps if x.kind != "unknown"), ps[0])
    return p.kind, p.rows, p.form


def account_hint(name: str) -> str | None:
    """파일 이름의 `_10100_` 같은 5자리(또는 3자리) 계정코드 힌트. 없으면 None."""
    m = re.search(r"(?:^|[_\s-])(\d{5})(?=[_\s.-])", name)
    if m:
        return m.group(1)
    m = re.search(r"(?:^|[_\s-])(\d{3})(?=[_\s.-])", name)
    return m.group(1) if m else None
