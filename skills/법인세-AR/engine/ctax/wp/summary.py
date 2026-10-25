"""조서 등록부(`papers`)를 차례로 돌리고 집계 넷(15호 · 3호 · 50호 · 결손금)을 만든다.

집계도 노란 칸이 있다: 15호 「직접 조정」 줄 · 「전기 조정 대조」 표(당기 반영 · 당기 금액, `prior_compare.py`), 3호 공제감면 ·
가산세 · 기납부세액, 결손금 수동 줄. 값은 `Paper.take` 로 읽는다.

조서 모듈이 고를 수 있는 단계: `finish(p, b, flow)` 는 15호 합계 뒤(기부금 한도), `after_tax(p, b, flow)` 는 3호 산출세액 뒤
(공제감면 · 최저한세). after_tax 가 flow 의 credits_min · credits_ex 를 정하면 3호 17 · 19 노란 칸의 기본값이 된다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from fractions import Fraction
from types import ModuleType

from . import papers as registry
from . import prior_compare
from .books import Books, frac, rate, rd
from .model import DISPOSITION_CODE, DISPOSITIONS, Adj, Paper

DIRECT_ROWS = 5          # 15호 「직접 조정」 노란 줄 수
LOSS_MANUAL_ROWS = 3     # 결손금 수동 노란 줄 수
DIRECT_FIELDS = (("구분", "text"), ("과목", "text"), ("소득처분", "text"), ("조정내용", "text"), ("금액", "int"))



def penalty_from_info(b: Books) -> int:
    """신고건.json 「가산세」(사람 입력)로 계산한 9호 (21) 법인세분 가산세 합계. 없으면 0(9호 플러그인과 같은 계산)."""
    if not (b.info or {}).get("가산세"):
        return 0
    from types import SimpleNamespace

    from ctax.forms import registry
    from ctax.forms.plugins import penalty
    inp = SimpleNamespace(info=b.info)
    vals, _ = penalty.given(inp)
    if not vals:
        return 0
    t = penalty.totals(vals, penalty._fy_days(inp), registry.load(penalty.CODE), str(b.info.get("fy_start") or "2025-01-01"))
    return int(t.get("21") or 0)

def progressive_tax(base: int, brackets, months: int = 12) -> int:
    """법인세법 제55조 누진세율. 1년 미만이면 연환산 뒤 월수로 나눈다."""
    if base <= 0:
        return 0
    annual = Fraction(base * 12, months)
    tax, prev = Fraction(0), 0
    for cap, r in brackets:
        top = annual if cap is None else min(annual, cap)
        if top > prev:
            tax += (top - prev) * frac(r)
        if cap is None or annual <= cap:
            break
        prev = cap
    return rd(tax * months / 12)


@dataclass
class Result:
    papers: list[Paper]
    mods: dict[str, ModuleType]
    summary15: Paper
    tax3: Paper
    reserve50: Paper
    loss: Paper
    summary: dict
    reserves: list[dict]
    losses: list[dict]
    direct: list[Adj] = field(default_factory=list)
    checks: list[dict] = field(default_factory=list)
    input_cells: list[dict] = field(default_factory=list)   # 조서.xlsx 노란 칸 표(excel.write 가 채움)

    @property
    def all_papers(self) -> list[Paper]:
        return self.papers + [self.summary15, self.tax3, self.reserve50, self.loss]

    def paper(self, pid: str) -> Paper | None:
        return next((p for p in self.all_papers if p.id == pid), None)

    def adjustments(self) -> list[tuple[Paper, Adj]]:
        return [(p, a) for p in self.papers for a in p.live_adjustments()]

    def json(self) -> dict:
        cells: dict[str, list[dict]] = {}
        for c in self.input_cells:
            cells.setdefault(c["paper"], []).append(c)
        return {"papers": [{**p.json(), "input_cells": cells.get(p.id, [])} for p in self.all_papers],
                "adjustments": [a.json(p.id) for p, a in self.adjustments()],
                "summary": self.summary, "reserves": self.reserves, "losses": self.losses,
                "direct": [a.json("direct") for a in self.direct if a.amount],
                "checks": self.checks}


def loss_rows(b: Books, ls: Paper) -> list[dict]:
    """이월결손금 잔액 줄(오래된 것부터). 전기 50호(갑)에 그해 결손금 줄이 없으면 전기 3호 06 으로 채운다.
    회계사가 「결손금」 시트 수동 줄에 넣은 결손금(연도 · 발생액 · 기공제액)도 더한다."""
    rows = []
    for r in (b.prior or {}).get("losses", []) or []:
        rows.append({"year": str(r.get("year") or ""), "incurred": int(r.get("incurred") or 0),
                     "opening": int(r.get("remaining") if r.get("remaining") is not None else r.get("incurred") or 0),
                     "source": f"전기 {r['derived']}(50호(갑) 결손금 표에 없음)" if r.get("derived") else "전기 50호(갑)"})
    prior_fy = str((b.prior or {}).get("fy") or "")
    prior_income = b.prior_cell("3", "06")
    if prior_income is not None and int(prior_income) < 0 and prior_fy and not any(r["year"] == prior_fy for r in rows):
        rows.append({"year": prior_fy, "incurred": -int(prior_income), "opening": -int(prior_income),
                     "source": "전기 3호 06(50호(갑) 결손금 표에 없음)"})
    limit_year = int(b.fy or 0) - rate(b.rates, "loss", "years") if b.fy else 0
    rows = [r for r in rows if not r["year"][:4].isdigit() or int(r["year"][:4]) >= limit_year]
    manual = []
    for n in range(1, LOSS_MANUAL_ROWS + 1):
        year = ls.take(b, f"결손금 수동 {n}/연도", "", "year")
        incurred = ls.take(b, f"결손금 수동 {n}/발생액", 0, "int")
        used = ls.take(b, f"결손금 수동 {n}/기공제액", 0, "int")
        if year or incurred or used:
            manual.append({"year": year, "incurred": incurred, "opening": incurred - used, "used_before": used,
                           "source": "회계사 입력", "manual": n})
            if year[:4].isdigit() and int(year[:4]) < limit_year:
                ls.confirm.append(f"수동 줄 {n} 의 {year} 결손금은 15년 공제 기간이 지났을 수 있습니다(2008 이전 발생분은 10년)")
    rows += manual
    rows.sort(key=lambda r: r["year"])
    return rows


CARRYBACK = "소급공제 결손금"


def carryback(b: Books, ls: Paper, income: int, brackets) -> dict:
    """중소기업 결손금 소급공제 환급(법인세법 제72조 제1항, 시행령 제110조 제1항, 2025-12-31 시행판 원문 ★★★).

    환급세액 = min(직전 산출세액 - (직전 과세표준 - 소급공제 결손금) × 직전 세율, 직전 산출세액 - 직전 공제 · 감면세액).
    직전 값은 전기 3호 10(과세표준) · 12(산출세액) · 17 + 19(공제감면세액)다. 세율은 직전 사업연도(2024)와 당기 세율표가 같아
    기준 시트 세율을 쓴다(법인세법 제55조 제1항, 2024-12-31 · 2025-12-31 시행판 같은 표). 소급공제는 신청해야 하는 것이라
    노란 칸 「소급공제 결손금」 기본값은 0 이고, 넣으면 그만큼 당기 결손금 이월액이 준다. 신고기한 안에 결손 사업연도와 직전
    사업연도를 모두 신고한 경우에만 된다(제72조 제4항)."""
    zero = {CARRYBACK: 0, "소급공제 환급세액": 0, "소급공제 최대 결손금": 0, "소급공제 최대 환급세액": 0}
    prior_base = int(b.prior_cell("3", "10") or 0)
    prior_tax = int(b.prior_cell("3", "12") or 0)
    if income >= 0 or prior_base <= 0 or prior_tax <= 0:
        return zero
    prior_credit = int(b.prior_cell("3", "17") or 0) + int(b.prior_cell("3", "19") or 0)
    months = 12                          # 직전 사업연도를 12개월로 본다(1년 미만이면 제55조 제2항 환산이 달라 회계사가 고친다)
    cap = max(0, prior_tax - prior_credit)
    most = min(-income, prior_base)

    def refund(loss: int) -> int:
        return max(0, min(prior_tax - progressive_tax(prior_base - loss, brackets, months), cap))

    if not b.sme:
        ls.notes.append(f"결손금 {-income:,}원이 생겼지만 중소기업이 아니라 결손금 소급공제(법인세법 제72조)를 하지 않습니다")
        return zero
    used = ls.take(b, CARRYBACK, 0, "int")
    if used > most:
        ls.confirm.append(f"「{CARRYBACK}」 {used:,}원이 소급공제할 수 있는 결손금 {most:,}원(당기 결손금과 직전 과세표준 중 작은 것)보다 커 "
                          f"{most:,}원으로 계산했습니다")
        used = most
    used = max(0, used)
    out = {CARRYBACK: used, "소급공제 환급세액": refund(used), "소급공제 최대 결손금": most, "소급공제 최대 환급세액": refund(most),
           "직전 과세표준": prior_base, "직전 산출세액": prior_tax, "직전 공제감면세액": prior_credit, "직전 법인세액": cap,
           "직전 사업연도 월수": months}
    if not used and out["소급공제 최대 환급세액"]:
        ls.confirm.append(f"중소기업 결손금 {-income:,}원은 소급공제를 신청하면 직전 사업연도 법인세에서 최대 {out['소급공제 최대 환급세액']:,}원을 "
                          f"돌려받습니다(결손금 {most:,}원 사용, 직전 과세표준 {prior_base:,}원 · 산출세액 {prior_tax:,}원 · 공제감면 "
                          f"{prior_credit:,}원). 신청하면 노란 칸 「{CARRYBACK}」 에 쓸 결손금을 넣고 68호 소급공제법인세액환급신청서를 "
                          "신고기한 안에 냅니다(법인세법 제72조, 시행령 제110조). 넣은 만큼 이월결손금이 줄어듭니다")
    elif used:
        ls.notes.append(f"결손금 {used:,}원을 소급공제해 환급세액 {out['소급공제 환급세액']:,}원을 계산했습니다(68호). 이월결손금은 그만큼 "
                        "줄었습니다. 직전 사업연도 법인세 산출세액에 토지등 양도소득에 대한 법인세가 있으면 빼야 합니다")
    return out


def _direct(b: Books, s15: Paper) -> list[Adj]:
    """15호 「직접 조정」 노란 줄. 구분 · 금액이 있는 줄만 조정이 된다."""
    out = []
    for n in range(1, DIRECT_ROWS + 1):
        got = {name: s15.take(b, f"직접 조정 {n}/{name}", 0 if kind == "int" else "", kind) for name, kind in DIRECT_FIELDS}
        side, disp = got["구분"], got["소득처분"]
        if not side and not got["금액"]:
            continue
        if side not in ("가산", "차감"):
            # 엑셀 합계(SUMIF 「가산」 · 「차감」)도 이 줄을 세지 않는다
            s15.confirm.append(f"직접 조정 {n} 줄의 구분 「{side}」 을 읽지 못해 넣지 않았습니다(가산 · 차감)")
            continue
        if disp not in DISPOSITIONS[side]:
            s15.confirm.append(f"직접 조정 {n} 줄의 소득처분 「{disp}」 을 읽지 못했습니다. 금액은 15호 합계에 넣었고 "
                               f"처분 코드는 비웠습니다({' · '.join(DISPOSITIONS[side])})")
        subj = got["과목"] or "직접 조정"
        a = Adj(side, subj, got["금액"], disp, "직접 조정", got["조정내용"] or f"직접 조정 {n}", f"직접 조정 {n}/금액",
                reserve_subject=subj)
        a.row = n
        out.append(a)
    return out


def run(b: Books) -> Result:
    papers: list[Paper] = []
    mods: dict[str, ModuleType] = {}
    for pid, no, mod in registry.entries():
        p = Paper(pid, no, mod.NAME, forms=list(mod.FORMS))
        mod.compute(p, b)
        p.issues = b.issues_for(pid)
        papers.append(p)
        mods[pid] = mod

    s15 = Paper("summary_15", "15", "소득금액조정", forms=["15", "15부표1", "15부표2"])
    manual = _direct(b, s15)
    adjs = [(p, a) for p in papers for a in p.live_adjustments()]
    # 전기 조정 대조: 전기 15호 줄 가운데 당기에 없는 줄을 회계사가 노란 칸 O 로 넣으면 직접 조정과 같은 흐름을 탄다(기본 X 는 그대로)
    compared = prior_compare.compare(b, s15, adjs, manual)
    direct = manual + compared.applied
    live_manual = [a for a in manual if a.amount]
    live_direct = [a for a in direct if a.amount]
    add = sum(a.amount for _, a in adjs if a.side == "가산") + sum(a.amount for a in live_direct if a.side == "가산")
    ded = sum(a.amount for _, a in adjs if a.side == "차감") + sum(a.amount for a in live_direct if a.side == "차감")
    net_income = int(b.totals.get("net_income") or 0)
    before = net_income + add - ded

    ls = Paper("loss", "결손", "결손금", forms=["50갑"])
    lrows = loss_rows(b, ls)
    balance = sum(r["opening"] for r in lrows)
    flow = {"income_before_donation": before, "loss_balance": balance, "donation_excess": 0}
    for p in papers:
        fin = getattr(mods[p.id], "finish", None)
        if fin:
            fin(p, b, flow)
    excess = flow["donation_excess"]

    t3 = Paper("tax_3", "3", "과세표준 세액", forms=["3"])
    t3.take(b, "중소기업 여부", "여" if b.sme_default else "부")
    # 3호 (106) 기부금한도초과이월액 손금산입. 기본값은 기부금 조서가 이월 기부금 노란 줄로 잰 21호 ⑤ + ⑮
    carry_in = t3.take(b, "54", flow.get("donation_carry_in", 0), "int")
    income = before + excess - carry_in

    ratio = frac(rate(b.rates, "loss", "sme_ratio" if b.sme else "general_ratio"))
    cap = rd(income * ratio) if income > 0 else 0
    left = cap
    for r in lrows:
        r["used"] = max(0, min(r["opening"], left))
        left -= r["used"]
        r["closing"] = r["opening"] - r["used"]
    loss_used = cap - left
    nontax = t3.take(b, "08", 0, "int")
    deduction = t3.take(b, "09", 0, "int")
    base = income - loss_used - nontax - deduction
    brackets = rate(b.rates, "corporate_tax", "brackets")
    computed = progressive_tax(base, brackets, b.months)
    # 공제감면 · 최저한세(CONTRACT.md 15절). 산출세액이 나온 뒤 조서의 after_tax(조서 20 credits)가 3호 17 · 19 기본값을 정한다
    # income(각사업연도소득)은 감면 소득을 이월결손금 등 공제액만큼 비례해 줄일 때 쓴다(법인세법 시행령 제96조 제2호)
    # loss_used · nontax · deduction 은 48호 소득구분계산서 (9) ~ (11) 줄을 감면분 · 기타분으로 나눌 때 쓴다
    flow.update({"tax_base": base, "computed_tax": computed, "credits_min": 0, "credits_ex": 0, "income": income,
                 "loss_used": loss_used, "nontax": nontax, "deduction": deduction})
    for p in papers:
        fn = getattr(mods[p.id], "after_tax", None)
        if fn:
            fn(p, b, flow)
    credits_min = t3.take(b, "17", flow["credits_min"], "int")
    credits_ex = t3.take(b, "19", flow["credits_ex"], "int")
    if (credits_min, credits_ex) != (flow["credits_min"], flow["credits_ex"]):
        t3.confirm.append(f"3호 17 · 19 란 회계사 값({credits_min:,} · {credits_ex:,})이 공제감면 조서 값({flow['credits_min']:,} · "
                          f"{flow['credits_ex']:,})과 다릅니다. 8호(갑) · 4호는 조서 값으로 채웁니다")
    penalty0 = penalty_from_info(b)
    penalty = t3.take(b, "20", penalty0, "int")
    if penalty0:
        t3.confirm.append(f"3호 20 가산세액 기본값 {penalty0:,}원은 신고건.json 「가산세」 로 계산한 9호 (21) 합계입니다")
    # 기납부세액(3호 22 · 24). 법인세비용 조서가 순액 이자의 원천세를 넣기로 한 줄(노란 칸 O)도 더한다
    ct = next((p for p in papers if p.id == "corporate_tax"), None)
    pre = prepaid_rows(b, (ct.extra.get("net_interest_rows") or []) if ct else [])
    interim0, withholding0, local0 = pre["interim"], pre["withholding"], pre["local"]
    interim = t3.take(b, "22", interim0, "int")
    withholding = t3.take(b, "24", withholding0, "int")
    local_wh = t3.take(b, "지방소득세 특별징수", local0, "int")
    prepaid = interim + withholding
    determined = computed - credits_min - credits_ex
    # 3호 (133) 감면분 추가납부세액. 기본값은 공제감면 조서의 추가 납부세액 합계(인원이 줄었을 때, 조특령 제26조의8 제4항 등)
    extra_tax = t3.take(b, "29", flow.get("additional_tax", 0), "int")
    if extra_tax != flow.get("additional_tax", 0):
        t3.confirm.append(f"3호 29 란 회계사 값 {extra_tax:,}원이 공제감면 조서의 추가 납부세액 합계 {flow.get('additional_tax', 0):,}원과 "
                          "다릅니다. 8호(을) · 3호 (133)은 회계사 값으로 채웁니다")
    payable = determined + penalty - prepaid + extra_tax
    summary = {"net_income": net_income, "add": add, "deduct": ded, "income_before_donation": before,
               "donation_excess": excess, "income": income, "loss_used": loss_used, "tax_base": base,
               "computed_tax": computed, "credits": credits_min + credits_ex, "determined_tax": determined,
               "penalty": penalty, "prepaid": prepaid, "payable": payable}

    s15.values = {"익금산입 손금불산입": add, "손금산입 익금불산입": ded, "줄 수": len(adjs) + len(direct)}
    if live_manual:
        s15.notes.append(f"「직접 조정」 줄 {len(live_manual)}개(회계사 입력)를 더했습니다. 조정.json direct 에 있습니다")
    else:
        s15.notes.append("조서에서 넘어온 조정과 「직접 조정」 줄(노란 칸)을 모읍니다. 회사 고유 조정은 직접 조정 줄에 넣고 다시 돌리세요")
    prior_compare.report(b, s15, compared, _reserves(b, adjs, live_direct))

    rate_pct = 0
    for cap_, r in brackets:
        if base > 0 and (cap_ is None or base * 12 / b.months <= cap_):
            rate_pct = round(r * 100)
            break
    t3.values = {"01": net_income, "02": add, "03": ded, "04": before, "05": excess, "54": carry_in,
                 "06": income, "07": loss_used, "08": nontax, "09": deduction, "10": base, "11": rate_pct,
                 "12": computed, "17": credits_min, "18": computed - credits_min, "19": credits_ex, "20": penalty,
                 "21": computed - credits_min - credits_ex + penalty, "22": interim, "24": withholding,
                 "28": prepaid, "29": extra_tax, "30": payable, "지방소득세 특별징수": local_wh, "기납부세액 명세": pre["rows"]}
    prior_credits = (b.prior or {}).get("credits") or []
    if prior_credits:
        names = ", ".join(f"{c.get('name')} {int(c.get('amount') or 0):,}원" for c in prior_credits)
        t3.notes.append(f"전기 공제감면: {names}")
    if credits_min or credits_ex or prior_credits:
        t3.notes.append("17 · 19 란 기본값은 조서 20 공제감면(중소기업특별세액감면 · 이월공제 · 최저한세) 값입니다")
    if income <= 0:
        t3.notes.append("각사업연도소득금액이 0 이하라 산출세액이 없습니다. 결손금은 「결손금」 시트에 당기 발생으로 적었습니다")
    if prepaid or local_wh:
        t3.notes.append("기납부세액은 선납세금 계정 차변입니다. 적요에 「중간예납」 이 있으면 중간예납, 나머지는 원천납부로 나눴습니다. "
                        "적요에 지방소득세 · 특별징수가 있거나 거래처가 지자체인 줄은 지방소득세 특별징수분이라 24 에서 뺐습니다. "
                        "줄마다 나눈 결과는 values 「기납부세액 명세」 이고 10호(갑) · 지방43의5(갑)이 그대로 읽습니다")
    _prepaid_notes(t3, pre, interim == interim0 and withholding == withholding0)
    t3.status = "작성"

    # 결손금
    back = carryback(b, ls, income, brackets)
    losses = [{"year": r["year"], "incurred": r["incurred"], "used": r["used"], "remaining": r["closing"]} for r in lrows]
    if income < 0:
        row = {"year": b.fy, "incurred": -income, "used": 0, "remaining": -income - back["소급공제 결손금"]}
        if back["소급공제 결손금"]:
            row["carryback"] = back["소급공제 결손금"]
        losses.append(row)
    ls.extra["rows"] = lrows
    ls.values = {"이월결손금기초": balance, "공제한도": cap, "당기공제": loss_used, "당기발생": max(0, -income),
                 "이월결손금기말": balance - loss_used + max(0, -income) - back["소급공제 결손금"], **back}
    if any("3호 06" in r["source"] for r in lrows):
        ls.confirm.append("전기 50호(갑) 결손금 표에 전기 결손금 줄이 없어 전기 3호 06 금액으로 넣었습니다. 그 전 해 결손금이 남아 있으면 노란 칸에 넣으세요")
    ls.notes.append("중소기업은 각사업연도소득의 100%, 그 밖의 법인은 80% 까지 공제합니다(법인세법 제13조)")
    ls.status = "확인 필요" if ls.confirm else "작성"
    s15.status = "확인 필요" if s15.confirm else "작성"

    # 50호
    r50 = Paper("reserve_50", "50", "유보 자본금", forms=["50을", "50갑"])
    reserves = _reserves(b, adjs, live_direct)
    r50.extra["rows"] = reserves
    equity = _equity(b)
    res_open = sum(r["opening"] for r in reserves)
    res_close = sum(r["closing"] for r in reserves)
    r50.values = {"유보기초": res_open, "유보기말": res_close, **{f"기말 {k}": v for k, v in equity.items()},
                  "차가감계": equity["계"] + res_close}
    pc = ((b.prior or {}).get("cells") or {}).get("50갑", {})
    r50.extra["prior"] = {"자본금": pc.get("01"), "이익잉여금": pc.get("14"), "계": pc.get("20"), "차가감계": pc.get("31")}
    r50.notes.append("50호(갑) 손익미계상 법인세 등(7) 란은 목업에서 다루지 않습니다")
    r50.status = "작성"

    checks = _checks(b, papers, mods, summary)
    return Result(papers, mods, s15, t3, r50, ls, summary,
                  [{k: r[k] for k in ("subject", "opening", "decrease", "increase", "closing")} for r in reserves],
                  losses, direct, checks)


LOCAL_TAX = re.compile(r"지방소득세|지방세|주민세|특별징수")
LOCAL_GOV = re.compile(r"구청|시청|군청|도청|특별시|광역시|특별자치|^[가-힣]{1,4}[시군구]$|^[가-힣]{1,4}[시군구]청$")
PREPAID_ACCTS = ("선납세금", "선급법인세")
INTEREST_ACCTS = ("이자수익", "이자수입", "배당금수익", "배당금수입", "배당수익")
CASH_WORDS = ("현금", "예금", "당좌")
# 원천징수 줄로 볼 적요(이자 · 배당 · 금융상품). 이 낱말이 있으면 중간예납으로 추정하지 않는다
WITHHOLD_HINT = re.compile(r"이자|배당|원천|예금|적금|만기|해지|금융|증권|채권|펀드")
# 중간예납 납부 달: 개시일부터 6개월이 지난 뒤 2개월 안(법인세법 제63조 제3항), 1천만원 초과분 분납은 1개월(중소기업 2개월)
# 더(제63조 제4항 · 제64조 제2항). 개시 달을 0 으로 센 달 번호 6 ~ 9(12월 결산이면 7 ~ 10월)
INTERIM_MONTHS = range(6, 10)
INTERIM, INTERIM_GUESS, WITHHOLD, LOCAL_ONLY, NET_INTEREST = "중간예납", "중간예납 추정", "원천납부", "지방소득세", "순액 이자 원천세"


def split_withheld(withheld: int, interest: int) -> tuple[int, float | None]:
    """원천징수 줄 금액 → (법인세 몫, 세율). 지방소득세까지 한 줄(이자의 15.4%)이면 법인세 14% 만 뗀다.
    서식 10호(갑) 채우기(forms fill_more.corp_part)와 같은 규칙이다(법인세법 제73조 제1항, 지방세법 제103조의29)."""
    if interest > 0:
        r = Fraction(withheld, interest)
        if Fraction(150, 1000) <= r <= Fraction(158, 1000):
            return interest * 14 // 100 // 10 * 10, 0.14
        if Fraction(135, 1000) <= r <= Fraction(145, 1000):
            return withheld, 0.14
        if Fraction(24, 100) <= r <= Fraction(28, 100):
            return (withheld if r < Fraction(255, 1000) else round(withheld / 1.1)), 0.25
    return withheld, None


def _month_no(start: str, d: str) -> int | None:
    try:
        s, x = date.fromisoformat(str(start)[:10]), date.fromisoformat(str(d)[:10])
    except ValueError:
        return None
    return (x.year - s.year) * 12 + x.month - s.month


def _is_local_of(local: int, corp: int) -> bool:
    """local 이 corp 법인세의 지방소득세(10%, 10원 미만 버림) 금액이다."""
    return corp > 0 and abs(local - corp // 100 * 10) <= 10


def prepaid_rows(b: Books, extra: list[dict] | tuple = ()) -> dict:
    """기납부세액 줄. 선납세금 차변 줄마다 중간예납 · 원천납부(법인세 · 지방소득세) · 지방소득세로 나누고, 같은 전표의 지방소득세 줄은
    그 원천납부 줄에 짝지어 한 줄(10호(갑) · 지방43의5(갑) 한 줄)로 만든다.

      중간예납        적요에 「중간예납」. 선납세금 말고 법인세등 · 미지급세금 차변이어도(같은 전표에 선납세금이 없고 예금이 나갈 때)
      지방소득세      적요에 지방소득세 · 특별징수, 거래처가 지자체, 또는 같은 전표 원천납부 줄 법인세의 10%
      중간예납 추정   같은 전표에 이자 · 배당 수익이 없고 적요에 이자 · 원천 같은 말이 없으며 예금이 나간 줄로, 중간예납 납부 달
                      (12월 결산이면 7 ~ 10월)에 낸 것. 기중 중간예납을 선납세금으로 냈다가 결산 때 미지급세금과 상계한 꼴이다
      원천납부        나머지. 같은 전표 이자 · 배당 수익의 15.4% 한 줄이면 법인세 14% 와 지방소득세로 나눈다
    `extra` 는 법인세비용 조서가 넘긴 순액 이자 원천세 줄(노란 칸 O)이다.
    """
    start = b.info.get("fy_start") or (f"{b.fy}-01-01" if b.fy else "")
    prepaid_codes = {a["code"] for a in b.accounts(cls="자산", any_of=PREPAID_ACCTS)}
    interest_codes = {a["code"] for a in b.accounts(cls="수익", any_of=INTEREST_ACCTS)}
    cash_codes = {a["code"] for a in b.accounts(cls="자산") if any(w in (a.get("name") or "") for w in CASH_WORDS)}
    by_voucher: dict = {}
    for ln in b.lines:
        by_voucher.setdefault((ln.date, ln.no), []).append(ln)

    def name_of(ln):
        return b.by_code.get(ln.account, {}).get("name") or ln.account_name

    def paid_cash(v):
        return sum(x.credit - x.debit for x in v if x.account in cash_codes) > 0

    rows: list[dict] = []
    vouchers: dict = {}
    for ln in b.lines_of([b.by_code[c] for c in sorted(prepaid_codes)]):
        if ln.debit <= 0:
            continue
        v = by_voucher.get((ln.date, ln.no), [])
        interest = max(0, sum(x.credit - x.debit for x in v if x.account in interest_codes))
        r = {"date": ln.date, "no": ln.no, "account": name_of(ln), "partner": ln.partner, "memo": ln.memo,
             "interest": interest, "amount": ln.debit, "법인세": 0, "지방소득세": 0, "rate": None, "kind": WITHHOLD}
        month = _month_no(start, ln.date)
        if "중간예납" in ln.memo:
            r["kind"] = INTERIM
        elif LOCAL_TAX.search(ln.memo) or LOCAL_GOV.search(ln.partner):
            r["kind"] = LOCAL_ONLY
        elif (not interest and not WITHHOLD_HINT.search(ln.memo) and month in INTERIM_MONTHS and paid_cash(v)):
            r["kind"] = INTERIM_GUESS
        rows.append(r)
        if r["kind"] in (WITHHOLD, LOCAL_ONLY):
            vouchers.setdefault((ln.date, ln.no), []).append(r)
    # 전표마다: 표시 없는 지방소득세 줄(다른 원천납부 줄의 10%)을 가리고, 이자는 첫 원천납부 줄에만 둔다
    for v in vouchers.values():
        corp = [r for r in v if r["kind"] == WITHHOLD]
        for r in corp:
            if any(o is not r and _is_local_of(r["amount"], o["amount"]) for o in corp):
                r["kind"] = LOCAL_ONLY
        corp = [r for r in v if r["kind"] == WITHHOLD]
        for i, r in enumerate(corp):
            if i:
                r["interest"] = 0
            if len(corp) == 1:
                r["법인세"], r["rate"] = split_withheld(r["amount"], r["interest"])
            else:
                r["법인세"] = r["amount"]
            r["지방소득세"] = r["amount"] - r["법인세"]
        for r in [r for r in v if r["kind"] == LOCAL_ONLY]:
            r["지방소득세"] = r["amount"]
            mate = next((c for c in corp if _is_local_of(r["amount"], c["법인세"]) and not c.get("짝")), None)
            if mate is None and len(corp) == 1 and not corp[0].get("짝"):
                mate = corp[0]
            if mate is not None:
                mate["지방소득세"] += r["amount"]
                mate["짝"] = True
                r["merged"] = True
    rows = [r for r in rows if not r.pop("merged", False)]
    for r in rows:
        r.pop("짝", None)
        if r["kind"] in (INTERIM, INTERIM_GUESS):
            r["법인세"] = r["amount"]
    # 선납세금을 거치지 않은 중간예납: 법인세등 · 미지급세금 차변 중 적요에 중간예납
    tax_accts = [a for a in b.accounts(cls=("비용", "부채"), any_of=("법인세", "미지급세금")) if a["code"] not in prepaid_codes]
    for ln in b.lines_of(tax_accts):
        v = by_voucher.get((ln.date, ln.no), [])
        if ln.debit <= 0 or "중간예납" not in ln.memo or any(x.account in prepaid_codes for x in v) or not paid_cash(v):
            continue
        rows.append({"date": ln.date, "no": ln.no, "account": name_of(ln), "partner": ln.partner, "memo": ln.memo,
                     "interest": 0, "amount": ln.debit, "법인세": ln.debit, "지방소득세": 0, "rate": None, "kind": INTERIM,
                     "direct": True})
    for x in extra:
        rows.append({**x, "kind": NET_INTEREST})
    rows.sort(key=lambda r: (r["date"], str(r["no"])))
    interim = sum(r["법인세"] for r in rows if r["kind"] in (INTERIM, INTERIM_GUESS))
    withholding = sum(r["법인세"] for r in rows if r["kind"] in (WITHHOLD, NET_INTEREST))
    local = sum(r["지방소득세"] for r in rows)
    return {"interim": interim, "withholding": withholding, "local": local, "rows": rows}


def _prepaid_notes(t3: Paper, pre: dict, engine: bool) -> None:
    """기납부세액 나눔에서 회계사가 볼 것. `engine` 은 3호 22 · 24 가 엔진 값 그대로인지."""
    rows = pre["rows"]
    guess = [r for r in rows if r["kind"] == INTERIM_GUESS]
    if guess and engine:
        t3.confirm.append(f"선납세금 {len(guess)}줄 {sum(r['amount'] for r in guess):,}원은 적요에 중간예납이 없지만 중간예납 납부 달에 "
                          "이자 · 배당 수익 없이 예금에서 낸 줄이라 중간예납(22)으로 보았습니다. 원천징수세액이면 3호 노란 칸 22 · 24 를 "
                          "고치십시오(법인세법 제63조 제3항)")
    direct = [r for r in rows if r.get("direct")]
    if direct:
        t3.notes.append(f"선납세금을 거치지 않고 {direct[0]['account']} 계정 차변으로 낸 중간예납 {len(direct)}줄 "
                        f"{sum(r['amount'] for r in direct):,}원을 22 에 넣었습니다(적요 「중간예납」)")
    split = [r for r in rows if r["kind"] == WITHHOLD and r["rate"] == 0.14 and r["지방소득세"] and r["법인세"] != r["amount"]]
    if split:
        t3.notes.append(f"이자의 15.4% 를 한 줄로 적은 원천징수 {len(split)}줄은 법인세 14% 만 24 에 넣고 "
                        f"나머지 {sum(r['amount'] - r['법인세'] for r in split):,}원은 지방소득세 특별징수로 나눴습니다")
    alone = [r for r in rows if r["kind"] == LOCAL_ONLY]
    if alone:
        t3.notes.append(f"같은 전표에 짝이 되는 법인세 원천납부 줄이 없는 지방소득세 {len(alone)}줄 "
                        f"{sum(r['amount'] for r in alone):,}원은 지방소득세 특별징수에만 넣었습니다(지방43의5(갑)에는 줄이 없음)")


def reserve_move(row: dict, a: Adj) -> tuple[str, int]:
    """유보 조정 한 줄이 50호(을) 어느 열(증가 · 감소)에 어떤 부호로 가는지. 조서가 정한 것이 있으면 그대로,
    없으면(직접 조정) 기초 부호로 정한다: 기초와 반대 방향이면 감소, 같은 방향이거나 기초가 없으면 증가."""
    if a.reserve_col:
        return a.reserve_col, a.reserve_sign * a.amount
    signed = a.amount if a.side == "가산" else -a.amount
    if row["opening"] and (row["opening"] > 0) != (signed > 0):
        return "감소", -signed
    return "증가", signed


def _reserves(b: Books, adjs, direct: list[Adj] = ()) -> list[dict]:
    rows: dict[str, dict] = {}
    for r in (b.prior or {}).get("reserves", []) or []:
        subj = r.get("subject") or ""
        rows[subj] = {"subject": subj, "opening": int(r.get("closing") or 0), "decrease": 0, "increase": 0}
    for a in [a for _, a in adjs] + list(direct):
        if not a.reserve:
            continue
        subj = a.reserve_subject or a.subject
        row = rows.setdefault(subj, {"subject": subj, "opening": 0, "decrease": 0, "increase": 0})
        col, amt = reserve_move(row, a)
        row["decrease" if col == "감소" else "increase"] += amt
    out = []
    for row in rows.values():
        row["closing"] = row["opening"] - row["decrease"] + row["increase"]
        out.append(row)
    return out


def _equity(b: Books) -> dict:
    eq = b.accounts(cls="자본")

    def part(*words):
        return sum(int(a.get("amount") or 0) for a in eq if any(w in (a.get("section") or "") for w in words))
    capital = part("자본금")
    surplus = part("자본잉여금")
    adjust = part("자본조정")
    oci = part("기타포괄")
    total = int(b.totals.get("equity") or 0)
    return {"자본금": capital, "자본잉여금": surplus, "자본조정": adjust, "기타포괄손익누계액": oci,
            "이익잉여금": total - capital - surplus - adjust - oci, "계": total}


def _checks(b: Books, papers: list[Paper], mods: dict, summary: dict) -> list[dict]:
    out = []
    for p in papers:
        if p.accounts and getattr(mods[p.id], "LEDGER_CHECK", True):
            fs = sum(int(a.get("amount") or 0) for a in p.accounts)
            led = sum(r.line.amount for r in p.lines)
            out.append({"id": f"{p.id}_ledger", "ok": fs == led, "title": f"{p.sheet} 재무제표 = 분개장",
                        "left": fs, "right": led})
        out.extend(p.checks)
    s = summary
    out.append({"id": "flow_3", "ok": s["income_before_donation"] == s["net_income"] + s["add"] - s["deduct"]
                and s["tax_base"] == s["income"] - s["loss_used"], "title": "3호 흐름 산식",
                "left": s["tax_base"], "right": s["income"] - s["loss_used"]})
    return out


__all__ = ["Result", "run", "progressive_tax", "loss_rows", "reserve_move", "prepaid_rows", "split_withheld",
           "DISPOSITION_CODE", "DIRECT_ROWS", "LOSS_MANUAL_ROWS"]
