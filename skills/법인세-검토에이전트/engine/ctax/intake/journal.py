"""위하고 분개장(11열) 읽기와 마감 · 원가 대체 판정.

열: 전표일자 · 전표번호 · 구분 · Code · 계정과목 · 차변 · 대변 · Code · 거래처 · Code · 적요.
- 같은 머리 글 `Code` 가 셋이다. 차례대로 계정 · 거래처 · 적요 코드다.
- 끝의 `합계 (건수 : N )` 줄은 전표로 세지 않고 합계 대조에만 쓴다.
- 손익대체(마감) 전표 = 손익(400, 세목 회사는 40000) 계정이 든 전표. 구분 결차 · 결대로 판정하지 않는다.
- 원가 대체 줄 = 재고(146~175) · 매출원가(451~470) 계정이 차변에 있는 전표 안에서 500~799 계정의 대변 줄.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field

from .xlsxread import Cells, compact, date_text, text


@dataclass
class Line:
    date: str
    no: str
    kind: str
    account: str
    account_name: str
    debit: int
    credit: int
    partner_code: str
    partner: str
    memo_code: str
    memo: str
    closing: bool = False
    transfer: bool = False
    sub_account: str = ""          # 더존 ERP: 원래 7자 코드(account 는 계정 단위 코드)
    src_file: str = ""             # 원본 파일(신고 건 기준 경로). 읽기가 붙인다(11-01, PBC 대조)
    src_row: int = 0               # 원본 엑셀 행 번호(1부터, 머리줄 위 제목 줄까지 센다)
    src_sheet: str = ""            # 원본 시트 이름. 시트가 여럿인 파일에서만 적는다(11-08)


@dataclass
class Journal:
    lines: list[Line]
    total_row: dict | None = None          # 합계 줄 {"debit":, "credit":, "count":}
    five: bool = False                     # 세목 5자 코드
    pl_code: str = "400"
    vouchers: dict = field(default_factory=dict)
    source: str = "wehago"                 # wehago · douzone_erp


def c3(code: str) -> int:
    """범위 판정용 앞 3자 정수. 숫자가 아니면 -1."""
    s = str(code)[:3]
    return int(s) if s.isdigit() else -1


def _cols(head: list) -> dict:
    h = [compact(x) for x in head]
    idx = {}
    codes = [i for i, x in enumerate(h) if x.lower() == "code"]
    for key in ("전표일자", "전표번호", "구분", "계정과목", "차변", "대변", "거래처", "적요"):
        idx[key] = h.index(key) if key in h else None
    # Code 열: 계정과목 앞, 거래처 앞, 적요 앞
    def code_before(col):
        if col is None:
            return None
        cands = [i for i in codes if i < col]
        return cands[-1] if cands else None
    idx["acc_code"] = code_before(idx["계정과목"])
    idx["partner_code"] = code_before(idx["거래처"])
    idx["memo_code"] = code_before(idx["적요"])
    if idx["memo_code"] == idx["partner_code"]:
        idx["memo_code"] = None
    if idx["partner_code"] == idx["acc_code"]:
        idx["partner_code"] = None
    return idx


def _get(r, i):
    if i is None or i >= len(r):
        return None
    return r[i]


def parse(rows: list[list], ctx: Cells | None = None) -> Journal:
    """rows[0] 이 머리줄. ctx 가 있으면 src_row 를 엑셀 행 번호(건너뛴 제목 줄 포함)로 적고, 금액으로 읽지 못한 칸을 남긴다."""
    ctx = ctx or Cells()
    head, body = rows[0], rows[1:]
    ix = _cols(head)
    lines: list[Line] = []
    total = None
    for row_no, r in enumerate(body, start=2 + ctx.off):
        d = date_text(_get(r, ix["전표일자"]))
        no = text(_get(r, ix["전표번호"]))
        if d is None or not no:
            first = text(_get(r, 0))
            if first.startswith("합계"):
                m = re.search(r"([\d,]+)", first)
                total = {"debit": ctx.n0(_get(r, ix["차변"]), row_no, ix["차변"]),
                         "credit": ctx.n0(_get(r, ix["대변"]), row_no, ix["대변"]),
                         "count": int(m.group(1).replace(",", "")) if m else None}
            continue
        code = text(_get(r, ix["acc_code"]))
        if code.endswith(".0"):
            code = code[:-2]
        pc = text(_get(r, ix["partner_code"]))
        lines.append(Line(date=d, no=no, kind=text(_get(r, ix["구분"])), account=code,
                          account_name=text(_get(r, ix["계정과목"])),
                          debit=ctx.n0(_get(r, ix["차변"]), row_no, ix["차변"]),
                          credit=ctx.n0(_get(r, ix["대변"]), row_no, ix["대변"]),
                          partner_code=pc, partner=text(_get(r, ix["거래처"])),
                          memo_code=text(_get(r, ix["memo_code"])), memo=text(_get(r, ix["적요"])), src_row=row_no))
    lens = [len(x.account) for x in lines if x.account]
    five = bool(lens) and max(set(lens), key=lens.count) == 5
    j = Journal(lines=lines, total_row=total, five=five, pl_code="40000" if five else "400")
    mark(j)
    return j


def mark(j: Journal) -> None:
    """전표 묶기와 마감 · 원가 대체 줄 표시. 여러 파일을 이어 붙인 뒤에도 다시 부른다."""
    vouchers: dict[tuple, list[Line]] = defaultdict(list)
    for ln in j.lines:
        ln.closing = ln.transfer = False
        vouchers[(ln.date, ln.no)].append(ln)
    j.vouchers = vouchers
    for v in vouchers.values():
        if any(c3(ln.account) == 400 for ln in v):
            for ln in v:
                ln.closing = True
            continue
        has_stock_debit = any(ln.debit != 0 and (146 <= c3(ln.account) <= 175 or 451 <= c3(ln.account) <= 470)
                              for ln in v)
        if not has_stock_debit:
            continue
        for ln in v:
            if 500 <= c3(ln.account) <= 799 and ln.credit != 0:
                ln.transfer = True


_mark = mark

PRODUCTION_STOCK = ("재공품", "제품", "미성공사", "미완성")       # forms/fill_more.py 와 같다


def returned_to_stock(lines: list[Line]) -> dict[str, int]:
    """원가 계정(500~799) 대변 가운데 같은 전표 차변이 생산 재고(재공품 · 제품 · 반제품 · 미성공사)도 매출원가(451~470)도 아닌
    재고 계정(146~175, 저장품 · 원재료 등)인 줄의 합 {계정코드: 금액}. 결산 때 남은 소모품 · 원재료를 되돌린 전표다.
    mark 는 이 줄도 원가 대체로 보므로 원가 합계를 낼 때 따로 뺀다(forms/fill_more.cost_returned_to_stock 과 같은 규칙, 11-01)."""
    vouchers: dict[tuple, list[Line]] = defaultdict(list)
    for ln in lines:
        vouchers[(ln.date, ln.no)].append(ln)
    out: dict[str, int] = defaultdict(int)
    for v in vouchers.values():
        stock = [ln for ln in v if ln.debit and 146 <= c3(ln.account) <= 175]
        if not stock or any(ln.debit and 451 <= c3(ln.account) <= 470 for ln in v):
            continue
        if any(any(w in (ln.account_name or "") for w in PRODUCTION_STOCK) for ln in stock):
            continue
        for ln in v:
            if 500 <= c3(ln.account) <= 799 and ln.credit:
                out[ln.account] += ln.credit
    return dict(out)
