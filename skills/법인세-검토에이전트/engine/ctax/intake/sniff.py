"""받은자료 파일 종류를 머리줄로 가린다. 파일 이름은 믿지 않는다(계정코드 힌트로만 쓴다).

kind: journal · bs · is · partner_ledger · account_detail · trial_balance · prior_pdf · unknown
form(꼴): 분개장 wehago(11열) · douzone_erp(10열), 계정명세서 B(7열) · douzone_blocks(BIFF 블록)
"""
from __future__ import annotations

import re
from pathlib import Path

from . import douzone
from .xlsxread import Unreadable, compact, rows, strip_no

JOURNAL_KEYS = ("전표일자", "전표번호", "계정과목", "차변", "대변")
A_HEAD = ["code", "거래처", "전기(월)이월", "차변", "대변", "잔액"]
B_HEAD = ["코드", "계정과목명", "적요", "코드", "거래처명", "금액", "비고"]
SUFFIXES = (".xlsx", ".xlsm", ".xls")


def _head(row) -> list[str]:
    cells = [compact(c) for c in (row or [])]
    while cells and cells[-1] == "":
        cells.pop()
    return cells


def form_of_rows(rs: list[list]) -> tuple[str, str]:
    """(kind, form). form 은 분개장 · 계정명세서에서만 뜻이 있다."""
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


def kind_of_rows(rs: list[list]) -> str:
    """앞쪽 몇 행으로 종류를 정한다. 재무제표는 본문까지 봐야 재무상태표 · 손익계산서가 갈린다."""
    return form_of_rows(rs)[0]


def sniff(path: Path) -> tuple[str, list[list] | None, str]:
    """(kind, 행 목록, form). 분개장은 행 전체를 돌려준다(다시 읽지 않게). 읽지 못하면 ('unreadable', None, '')."""
    if path.suffix.lower() == ".pdf":
        return "prior_pdf", None, ""
    if path.suffix.lower() not in SUFFIXES:
        return "unknown", None, ""
    try:
        rs = rows(path)
    except Unreadable:
        return "unreadable", None, ""
    kind, form = form_of_rows(rs)
    return kind, rs, form


def account_hint(name: str) -> str | None:
    """파일 이름의 `_10100_` 같은 5자리(또는 3자리) 계정코드 힌트. 없으면 None."""
    m = re.search(r"(?:^|[_\s-])(\d{5})(?=[_\s.-])", name)
    if m:
        return m.group(1)
    m = re.search(r"(?:^|[_\s-])(\d{3})(?=[_\s.-])", name)
    return m.group(1) if m else None
