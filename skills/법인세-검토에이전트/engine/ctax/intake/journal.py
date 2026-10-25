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

from .xlsxread import compact, date_text, n0, text


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


def parse(rows: list[list]) -> Journal:
    head, body = rows[0], rows[1:]
    ix = _cols(head)
    lines: list[Line] = []
    total = None
    for r in body:
        d = date_text(_get(r, ix["전표일자"]))
        no = text(_get(r, ix["전표번호"]))
        if d is None or not no:
            first = text(_get(r, 0))
            if first.startswith("합계"):
                m = re.search(r"([\d,]+)", first)
                total = {"debit": n0(_get(r, ix["차변"])), "credit": n0(_get(r, ix["대변"])),
                         "count": int(m.group(1).replace(",", "")) if m else None}
            continue
        code = text(_get(r, ix["acc_code"]))
        if code.endswith(".0"):
            code = code[:-2]
        pc = text(_get(r, ix["partner_code"]))
        lines.append(Line(date=d, no=no, kind=text(_get(r, ix["구분"])), account=code,
                          account_name=text(_get(r, ix["계정과목"])),
                          debit=n0(_get(r, ix["차변"])), credit=n0(_get(r, ix["대변"])),
                          partner_code=pc, partner=text(_get(r, ix["거래처"])),
                          memo_code=text(_get(r, ix["memo_code"])), memo=text(_get(r, ix["적요"]))))
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
