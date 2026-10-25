"""17 업무무관 지급이자: 업무무관자산 · 특수관계인 업무무관 가지급금에 대한 지급이자 손금불산입(기타사외유출). 26호(갑)(을).

계산(법인세법 제28조 제1항 제4호, 시행령 제53조 제2항 · 제3항, 2025-12-31 시행판 원문 ★★★)
  지급이자       이자비용 · 지급이자 계정 합계(노란 칸). 먼저 부인한 이자(채권자불분명 사채이자 · 비실명 채권이자 · 건설자금이자,
                 시행령 제55조 적용순위)는 노란 칸 「먼저 부인한 이자」 로 빼고 남은 이자에 산식을 건다
  가지급금 적수  9 인정이자 조서와 같은 거래처별 적수(초일 산입 · 말일 불산입, 마지막 구간은 사업연도 끝날까지). 그 조서에서 특수관계인
                 「예」 로 고른 거래처만 더한다. 같은 사람의 가수금 상계(시행령 제53조 제3항)는 노란 칸 「가수금 상계 적수」 로 뺀다
  업무무관자산   부동산 · 동산 취득가액 적수(시행령 제49조 제1항)는 장부로 가리지 못해 노란 칸이다
  총차입금 적수  차입금 · 사채 계정의 일별 잔액 적수(노란 칸). 26호(을)처럼 이자율별 「이자 ÷ 이자율 × 연일수」 로 계산한 값을 넣어도 된다
  손금불산입     (지급이자 - 먼저 부인한 이자) × min(업무무관 적수 합계, 총차입금 적수) ÷ 총차입금 적수, 원 미만 버림

특수관계인 여부는 엔진이 정하지 않는다(9 인정이자 조서의 노란 칸). 「확인 필요」 거래처는 조정에 넣지 않고 넣으면 얼마인지 확인 줄에 적는다.
"""
from __future__ import annotations

import re
from datetime import date
from fractions import Fraction

from ... import xlsx as X
from ..books import Books, rd
from ..model import Adj, Paper
from ..sheet import Book, Rows, adj_table, forms_table, head, notes
from . import loan_interest as li

NAME = "업무무관 지급이자"
FORMS = ["26갑", "26을", "15"]
LEDGER_CHECK = False
SUBJECT = "업무무관자산등관련이자"

INTEREST = re.compile(r"이자비용|지급이자")
NOT_INTEREST = re.compile(r"수익|미지급|선급|할인차금|현재가치")
BORROW = re.compile(r"차입금|사채|유동성장기부채")
NOT_BORROW = re.compile(r"할인|할증|전환권|신주인수권|가수|미지급|이자")


def basis(rates: dict) -> list[tuple]:
    r = rates["interest_denial"]
    return [("업무무관 지급이자 산식", r["formula"]["value"], r["formula"]["basis"], r["formula"]["grade"], None),
            ("지급이자 손금불산입 순서", r["order"]["value"], r["order"]["basis"], r["order"]["grade"], None)]


def interest_accounts(b: Books) -> list[dict]:
    return [a for a in b.accounts(cls="비용") if INTEREST.search(a.get("name", "")) and not NOT_INTEREST.search(a.get("name", ""))]


def borrowing_accounts(b: Books) -> list[dict]:
    return [a for a in b.accounts(cls="부채") if BORROW.search(a.get("name", "")) and not NOT_BORROW.search(a.get("name", ""))]


def _period(b: Books) -> tuple[date, date]:
    try:
        return date.fromisoformat(b.info["fy_start"]), date.fromisoformat(b.info["fy_end"])
    except (KeyError, ValueError):
        y = int(b.fy or 2025)
        return date(y, 1, 1), date(y, 12, 31)


def borrowing_product(b: Books, accts: list[dict], start: date, end: date) -> tuple[int, list[dict]]:
    """차입금 계정마다 일별 잔액(대변 - 차변) 적수. (합계, [{code, name, opening, closing, 적수}])."""
    rows = []
    for a in accts:
        days: dict[date, int] = {}
        for ln in b.lines_of([a]):
            d = li._d(ln.date, start, end)
            days[d] = days.get(d, 0) + ln.credit - ln.debit
        bal = -int(a.get("opening") or 0)          # 부채는 장부.json 에서 음수(CONTRACT.md 3절)
        at, product = start, 0
        for d in sorted(days):
            product += max(0, bal) * (d - at).days
            bal += days[d]
            at = d
        product += max(0, bal) * ((end - at).days + 1)
        rows.append({"code": a["code"], "name": a.get("name", ""), "opening": -int(a.get("opening") or 0),
                     "closing": bal, "적수": product})
    return sum(r["적수"] for r in rows), rows


def compute(p: Paper, b: Books) -> None:
    accts = interest_accounts(b)
    p.accounts = accts
    start, end = _period(b)
    # 9 인정이자 조서와 같은 거래처 · 적수(조서를 한 번 더 계산한다. 노란 칸은 같은 조서입력.json 을 읽는다)
    tmp = Paper("loan_interest", "9", li.NAME)
    li.compute(tmp, b)
    loans = tmp.extra.get("rows") or []
    related = [r for r in loans if r["특수관계인"] == "예" and r["적수"]]
    unknown = [r for r in loans if r["특수관계인"] == "확인 필요" and r["적수"]]
    book_interest = sum(int(a.get("amount") or 0) for a in accts)
    borrow = borrowing_accounts(b)
    borrow_default, borrow_rows = borrowing_product(b, borrow, start, end)

    interest = p.take(b, "지급이자", book_interest, "int")
    first = p.take(b, "먼저 부인한 이자", 0, "int")
    advance = sum(r["적수"] for r in related)
    offset = p.take(b, "가수금 상계 적수", 0, "int")
    land = p.take(b, "업무무관 부동산 적수", 0, "int")
    movable = p.take(b, "업무무관 동산 적수", 0, "int")
    total_borrow = p.take(b, "총차입금 적수", borrow_default, "int")
    base = max(0, interest - first)
    assets = max(0, advance - offset) + land + movable

    def denied(numer: int) -> int:
        if total_borrow <= 0 or base <= 0:
            return 0
        return rd(Fraction(base) * min(numer, total_borrow) / total_borrow)

    amount = denied(assets)
    if_unknown = denied(assets + sum(r["적수"] for r in unknown)) - amount
    p.values = {"지급이자": interest, "먼저 부인한 이자": first, "대상 지급이자": base, "가지급금 적수": advance,
                "가수금 상계 적수": offset, "업무무관 부동산 적수": land, "업무무관 동산 적수": movable,
                "업무무관 적수": assets, "총차입금 적수": total_borrow, "한도 적수": min(assets, total_borrow) if total_borrow > 0 else 0,
                "손금불산입": amount, "확인 필요 손금불산입": if_unknown, "확인 필요 거래처": len(unknown),
                "장부 이자비용": book_interest, "장부 차입금 적수": borrow_default,
                "거래처": [{"partner": r["partner"], "특수관계인": r["특수관계인"], "적수": r["적수"]} for r in loans if r["적수"]],
                "차입금": borrow_rows}
    p.extra["loans"] = [r for r in loans if r["적수"]]
    p.extra["borrow"] = borrow_rows
    p.adjustments = [Adj("가산", SUBJECT, amount, "기타사외유출", "업무무관 지급이자",
                         "업무무관자산 · 가지급금 관련 지급이자 손금불산입", "손금불산입")]

    has = bool(base and (related or unknown or land or movable))
    if not has:
        if base and loans:
            p.notes.append("가지급금 · 대여금 거래처가 있지만 9 인정이자 조서에서 특수관계인 「예」 · 「확인 필요」 로 남은 적수가 없어 계산하지 않았습니다")
        p.settle(False)
        return
    if unknown:
        p.confirm.append(f"9 인정이자 조서에서 특수관계인 여부를 정하지 않은 거래처 {len(unknown)}곳의 적수는 넣지 않았습니다. 업무무관 "
                         f"가지급금이면 지급이자 손금불산입이 {if_unknown:,}원 늘어납니다(그 조서 노란 칸을 「예」 로)")
    if total_borrow <= 0:
        p.confirm.append(f"차입금 · 사채 계정의 적수가 0 인데 지급이자가 {base:,}원입니다. 26호(을)처럼 이자율별 "
                         "「이자 ÷ 이자율 × 연일수」 로 차입금 적수를 계산해 노란 칸 「총차입금 적수」 에 넣으십시오")
    elif total_borrow == borrow_default:
        p.notes.append(f"총차입금 적수는 차입금 · 사채 계정 {len(borrow_rows)}개의 일별 잔액 적수 {borrow_default:,}입니다. 26호(을)은 "
                       "이자율별 「지급이자 ÷ 이자율 × 연일수」 로 적으니 차입금별 이자율을 알면 그 합계를 노란 칸에 넣으십시오")
    if assets > total_borrow > 0:
        p.notes.append("업무무관 적수가 총차입금 적수보다 커서 총차입금 적수를 한도로 썼습니다(시행령 제53조 제2항)")
    p.notes.append("가지급금 적수는 9 인정이자 조서와 같은 적수입니다. 같은 사람의 가수금이 있으면 상계한 적수를 「가수금 상계 적수」 에 "
                   "넣습니다(시행령 제53조 제3항, 상계 약정이 없어도 상계). 업무무관 부동산 · 동산은 취득가액 적수입니다")
    p.notes.append("채권자불분명 사채이자 · 비실명 채권이자 · 건설자금이자를 먼저 손금불산입했으면 「먼저 부인한 이자」 에 넣습니다"
                   "(시행령 제55조 적용순위). 이 조서는 그 셋을 계산하지 않습니다")
    p.settle(True)


WIDTHS = [36, 14, 14, 14, 14, 14, 18, 40]


def write(bk: Book, p: Paper) -> None:
    s = head(bk, p)
    X.widths(s.ws, WIDTHS)
    v = p.values
    row = s.section(5, "1. 업무무관 가지급금 적수(9 인정이자 조서의 거래처)")
    X.header(s.ws, row, ["거래처", "특수관계인", "", "", "", "", "적수"])
    row += 1
    first = row
    for r in p.extra.get("loans", []):
        s.put(row, 1, r["partner"])
        s.put(row, 2, r["특수관계인"])
        s.put(row, 7, r["적수"], money=True)
        row += 1
    if not p.extra.get("loans"):
        s.put(row, 1, "가지급금 · 대여금 거래처가 없습니다")
        row += 1
    last = row - 1
    row = s.section(row + 1, "2. 차입금 적수(일별 잔액)")
    X.header(s.ws, row, ["계정", "코드", "기초", "기말", "", "", "적수"])
    row += 1
    b_first = row
    for r in p.extra.get("borrow", []):
        s.put(row, 1, r["name"])
        s.put(row, 2, r["code"])
        s.put(row, 3, r["opening"], money=True)
        s.put(row, 4, r["closing"], money=True)
        s.put(row, 7, r["적수"], money=True)
        row += 1
    if not p.extra.get("borrow"):
        s.put(row, 1, "차입금 · 사채 계정이 없습니다")
        row += 1
    b_last = row - 1
    row = s.section(row + 1, "3. 지급이자 손금불산입(26호(갑))")
    r = Rows(bk, s, p, row)
    g = r.g
    r.put("지급이자", "① 지급이자(이자비용 · 지급이자 계정)", p.inputs["지급이자"], kind="input", input_kind="int")
    r.put("먼저 부인한 이자", "먼저 부인한 이자(채권자불분명 · 비실명 · 건설자금)", p.inputs["먼저 부인한 이자"], kind="input", input_kind="int")
    r.put("대상 지급이자", "산식에 거는 지급이자", f"=MAX(0,{g('지급이자')}-{g('먼저 부인한 이자')})")
    r.put("가지급금 적수", "④ 가지급금 등 적수(특수관계인 「예」)", f'=SUMIF(B{first}:B{last},"예",G{first}:G{last})')
    r.put("가수금 상계 적수", "같은 사람 가수금 상계 적수", p.inputs["가수금 상계 적수"], kind="input", input_kind="int")
    r.put("업무무관 부동산 적수", "② 업무무관 부동산 적수", p.inputs["업무무관 부동산 적수"], kind="input", input_kind="int")
    r.put("업무무관 동산 적수", "③ 업무무관 동산 적수", p.inputs["업무무관 동산 적수"], kind="input", input_kind="int")
    r.put("업무무관 적수", "⑤ 계",
          f"=MAX(0,{g('가지급금 적수')}-{g('가수금 상계 적수')})+{g('업무무관 부동산 적수')}+{g('업무무관 동산 적수')}")
    r.put("장부 차입금 적수", "차입금 · 사채 계정 적수(참고)", f"=SUM(G{b_first}:G{b_last})")
    r.put("총차입금 적수", "⑥ 총차입금 적수", p.inputs["총차입금 적수"], kind="input", input_kind="int")
    r.put("한도 적수", "⑦ ⑤ 와 ⑥ 중 작은 것", f"=IF({g('총차입금 적수')}>0,MIN({g('업무무관 적수')},{g('총차입금 적수')}),0)")
    r.put("손금불산입", "⑧ 손금불산입 지급이자(가산 · 기타사외유출)",
          f"=IF({g('총차입금 적수')}>0,ROUNDDOWN({g('대상 지급이자')}*{g('한도 적수')}/MAX(1,{g('총차입금 적수')}),0),0)")
    X.note(s.ws, r.row, "특수관계인 여부는 9 인정이자 조서의 노란 칸으로 고릅니다. 고친 뒤 다시 돌리면 1 번 표가 바뀝니다")
    row = adj_table(bk, s, r.row + 2, p)
    row = forms_table(bk, s, row, p, [("26갑", "① 지급이자", "대상 지급이자"), ("26갑", "④ 가지급금 등 적수", "가지급금 적수"),
                                      ("26갑", "⑥ 차입금 적수", "총차입금 적수"), ("26갑", "⑧ 손금불산입 지급이자", "손금불산입")])
    notes(s, row, p)
