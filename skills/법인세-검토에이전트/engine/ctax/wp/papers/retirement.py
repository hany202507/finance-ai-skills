"""11 퇴직급여: 퇴직급여충당금 한도초과 · 추인(32호), 퇴직연금부담금 신고조정(33호). 모두 유보.

운용수익 직접 대체(fx3). 퇴직연금운용자산 차변 중 적요에 운용수익 · 이자가 있고 같은 전표에 수익 계정이 없는 줄. 운용수익을
수익으로 적지 않고 퇴직급여충당부채(또는 다른 계정)에 바로 더한 것이다. 32호 당기 설정액은 계정별 서식(acct 32호 ⑮)과 같이
퇴직급여(비용)가 상대인 충당부채 대변만 넣는다. 상대가 충당부채인 운용수익은 「퇴직연금 운용수익 익금산입」(가산 · 유보)으로
따로 올리고 기말 부인누계에 더한다. 그 밖의 비용 상대가 아닌 대변과 충당부채가 아닌 계정에 더한 운용수익은 확인 줄에 둔다.

퇴직금전환금 차이(10-29 대표 기준). 전기 50호(을) 퇴직급여충당금 유보가 전기 32호로 다시 센 부인누계와 다르면 퇴직금전환금 ·
경정 반영 여부를 장부만으로 가릴 수 없다. 엔진은 어느 쪽 금액도 고르지 않고(기초부인누계는 신고된 50호(을) 그대로) 퇴직금전환금
명세를 요청하는 확인 줄을 낸다.
"""
from __future__ import annotations

import re

from ... import xlsx as X
from ..books import Books, frac, rate, rd
from ..model import Adj, LineRow, Paper, fs_sum, subject_of
from ..sheet import Book, Rows, adj_table, forms_table, head, ledger, notes

NAME = "퇴직급여"
FORMS = ["32", "33"]
LEDGER_CHECK = False   # 충당금 · 운용자산 잔액을 보므로 계정 합계 검사를 하지 않는다


def basis(rates: dict) -> list[tuple]:
    ret = rates["retirement"]
    out = [("퇴직급여충당금 총급여 비율", ret["salary_ratio"]["value"], ret["salary_ratio"]["basis"], ret["salary_ratio"]["grade"], "0%"),
           ("퇴직급여충당금 추계액 비율", ret["estimate_ratio"]["value"], ret["estimate_ratio"]["basis"], ret["estimate_ratio"]["grade"], "0%")]
    pi = (rates.get("pension_income") or {}).get("rule")
    if pi:
        out.append(("퇴직연금 운용수익 직접 대체", pi["value"], pi["basis"], pi["grade"], None))
    return out


PLAN_INCOME = re.compile(r"운용수익|운용이익|이자|수익|배당")


def plan_income_lines(b: Books, plan: list[dict], prov: list[dict]) -> list[dict]:
    """퇴직연금운용자산 차변 중 운용수익으로 보이고 같은 전표에 수익 계정 대변이 없는 줄.
    [{date, no, memo, amount, to}] · to 는 상대가 충당부채 · 비용 · 그 밖 중 무엇인지."""
    plan_codes = {a["code"] for a in plan}
    prov_codes = {a["code"] for a in prov}
    by_voucher: dict = {}
    for ln in b.lines:
        by_voucher.setdefault((ln.date, ln.no), []).append(ln)
    out = []
    for ln in b.lines_of(plan):
        if ln.debit <= 0 or not PLAN_INCOME.search(ln.memo):
            continue
        v = by_voucher.get((ln.date, ln.no), [])
        cls = {x.account: b.by_code.get(x.account, {}).get("class") for x in v}
        if any(cls[x.account] == "수익" and x.credit > 0 for x in v):
            continue
        others = [x for x in v if x.credit > 0 and x.account not in plan_codes]
        if any(re.search(r"현금|예금|당좌", b.by_code.get(x.account, {}).get("name") or x.account_name) for x in others):
            continue                                       # 예금에서 나간 납입이다
        if any(x.account in prov_codes for x in others):
            to = "충당부채"
        elif others and all(cls[x.account] == "비용" for x in others):
            to = "비용"
        else:
            to = "그 밖"
        out.append({"date": ln.date, "no": ln.no, "memo": ln.memo, "amount": ln.debit, "to": to,
                    "counter": " · ".join(sorted({b.by_code.get(x.account, {}).get("name") or x.account_name for x in others}))})
    return out


def provision_credits(b: Books, prov: list[dict]) -> tuple[int, int]:
    """퇴직급여충당부채 대변을 (퇴직급여(비용)가 상대인 전입액, 그 밖 대변) 으로 가른다. 계정별 서식 32호 ⑮ 와 같은 규칙."""
    by_voucher: dict = {}
    for ln in b.lines:
        by_voucher.setdefault((ln.date, ln.no), []).append(ln)
    accrual = other = 0
    for ln in b.lines_of(prov):
        if ln.credit <= 0:
            continue
        v = [x for x in by_voucher.get((ln.date, ln.no), []) if x is not ln]
        if any(x.debit > 0 and "퇴직급여" in (b.by_code.get(x.account, {}).get("name") or x.account_name)
               and b.by_code.get(x.account, {}).get("class") == "비용" for x in v):
            accrual += ln.credit
        else:
            other += ln.credit
    return accrual, other


def plan_fees(b: Books, plan: list[dict]) -> int:
    """운용수익 전표 안의 운용 수수료. 운용자산 차변에 순액(수익 - 수수료)만 적은 전표는 계정별 서식 33호처럼 수익을 총액으로
    ㉑ 납입에, 수수료를 ⑳ 수령에 넣으므로 운용자산 증가 · 감소에 같은 금액을 더한다(33-Q01 답: 넣는다)."""
    codes = {a["code"] for a in plan}
    by_voucher: dict = {}
    for ln in b.lines:
        by_voucher.setdefault((ln.date, ln.no), []).append(ln)
    cls = lambda x: b.by_code.get(x.account, {}).get("class")
    total = 0
    for v in by_voucher.values():
        if not any(x.account in codes and x.debit > 0 for x in v):
            continue
        rev = sum(x.credit for x in v if x.credit > 0 and cls(x) == "수익")
        if not rev:
            continue
        net = sum(x.debit - x.credit for x in v if x.account in codes)
        fees = sum(x.debit for x in v if x.debit > 0 and cls(x) == "비용")
        if fees and rev - fees == net:
            total += fees
    return total


LEAVE_ACCRUAL = re.compile(r"[연년]차")


def leave_accrual(lines, others) -> int:
    """급여 계정 줄 가운데 연차수당 미지급 계상 · 환입 순액(적요에 연차 · 년차가 있고 같은 전표 상대가 미지급비용인 줄).
    32호 (17) 총급여액은 지급 기준이라 이 금액을 뺀다(10-29 평가세트: 두 회사 신고 총급여가 이 기준과 원 단위로 같다).
    others(ln) 는 같은 전표의 다른 줄. 조서 퇴직급여 「총급여액」 기본값과 계정별 서식 32호 (17) 이 같이 쓴다."""
    return sum(ln.amount for ln in lines if LEAVE_ACCRUAL.search(ln.memo or "")
               and any("미지급비용" in (o.account_name or "") for o in others(ln)))


def _prior_reserve(b: Books, *words) -> int:
    total = 0
    for r in (b.prior or {}).get("reserves", []) or []:
        if any(w in (r.get("subject") or "") for w in words):
            total += int(r.get("closing") or 0)
    return total


def prior_32_gap(b: Books, res_open: int) -> int | None:
    """전기 32호로 다시 센 부인누계(⑦ + min(④ - ⑤ - ⑥ - ⑦ - ⑧, 0) + ⑯) - 전기 50호(을) 유보. 전기 32호가 없으면 None."""
    c32 = ((b.prior or {}).get("cells") or {}).get("32") or {}
    if any(c32.get(k) is None for k in ("4", "7", "8", "15")):
        return None
    v = {k: int(c32.get(k) or 0) for k in ("4", "5", "6", "7", "8", "16")}
    raw9 = v["4"] - v["5"] - v["6"] - v["7"] - v["8"]
    return v["7"] + min(raw9, 0) + v["16"] - res_open


def _prior_estimate(b: Books) -> int:
    """전기 신고서 퇴직급여 추계액. 32호 (22) 세법상 추계액, 없으면 (20), 그것도 없으면 33호 ① 퇴직급여추계액."""
    cells = (b.prior or {}).get("cells") or {}
    c32, c33 = cells.get("32") or {}, cells.get("33") or {}
    for v in (c32.get("22"), c32.get("20"), c33.get("1")):
        if v not in (None, "") and int(v or 0):
            return int(v)
    return 0


def estimate_default(b: Books, pv_open: int, pv_close: int, pl_open: int, pl_close: int) -> tuple[int, str, int, str]:
    """퇴직급여추계액 기본값(회사 자료가 없을 때)과 그 근거, 대안값과 그 근거(10-20 회계사 검토).

    전기 32호 · 33호 추계액이 전기 퇴직급여충당부채 잔액(= 당기 기초)과 같으면 회사가 충당부채를 추계액만큼 쌓아 온 것으로 보고
    당기도 재무상태표 퇴직급여충당부채 잔액, 전기 퇴직연금운용자산 잔액과 같으면 당기 운용자산 잔액을 쓴다. 전기 추계액을 모르거나
    어느 쪽과도 다르면 앞과 같이 두 잔액 중 큰 쪽이고, 다른 쪽 값과 그때의 금액은 확인 줄에 적는다. 운용자산 잔액을 추계액으로 두면 운용자산이 충당부채보다 많은 회사에서 33호 손금산입이
    추계액을 넘게 커진다(10-20 평가에서 드러남)."""
    prior = _prior_estimate(b)
    tol = max(1000, prior // 10_000)
    if prior and pv_open and abs(prior - pv_open) <= tol:
        how = f"전기 32호 · 33호 추계액 {prior:,}원이 전기 퇴직급여충당부채 잔액 {pv_open:,}원과 같아 당기 재무상태표 퇴직급여충당부채 잔액"
        return pv_close, how, pl_close, "퇴직연금운용자산 기말 잔액"
    if prior and pl_open and abs(prior - pl_open) <= tol:
        how = f"전기 32호 · 33호 추계액 {prior:,}원이 전기 퇴직연금운용자산 잔액 {pl_open:,}원과 같아 당기 퇴직연금운용자산 기말 잔액"
        return pl_close, how, pv_close, "퇴직급여충당부채 기말 잔액"
    lead = f"전기 추계액 {prior:,}원이 전기 충당부채 · 운용자산 잔액과 달라 " if prior else "전기 추계액을 읽지 못해 "
    if pv_close >= pl_close:
        return pv_close, lead + "퇴직급여충당부채 · 퇴직연금운용자산 기말 잔액 중 큰 쪽(충당부채)", pl_close, "퇴직연금운용자산 기말 잔액"
    return pl_close, lead + "퇴직급여충당부채 · 퇴직연금운용자산 기말 잔액 중 큰 쪽(운용자산)", pv_close, "퇴직급여충당부채 기말 잔액"


def _limits(b: Books, estimate: int, conversion: int, salary: int, pv_inc: int, pv_close: int, res_open: int,
            before: int, reversal: int, pl_close: int, pen_left: int, income: int = 0) -> dict:
    """추계액 하나로 32호 한도 · 33호 손금산입을 잰다(대안 추계액의 금액도 같은 식으로 보이려고 따로 둔다)."""
    lim_salary = rd(salary * frac(rate(b.rates, "retirement", "salary_ratio")))
    lim_est = max(0, rd(estimate * frac(rate(b.rates, "retirement", "estimate_ratio"))) + conversion - before)
    limit = min(lim_salary, lim_est)
    over = max(0, pv_inc - limit)
    res_close = res_open - reversal + over + income
    tax_close = pv_close - res_close
    pen_limit = max(0, estimate - tax_close)
    pen_target = min(pen_limit, pl_close)
    pen_now = pen_target - pen_left
    return {"lim_salary": lim_salary, "lim_est": lim_est, "limit": limit, "over": over, "res_close": res_close,
            "tax_close": tax_close, "pen_limit": pen_limit, "pen_target": pen_target, "pen_ded": max(0, pen_now),
            "pen_over": max(0, -pen_now)}


def compute(p: Paper, b: Books) -> None:
    exp = b.accounts(cls="비용", any_of=("퇴직급여", "퇴직금"), none_of=("충당",))
    prov = b.accounts(cls="부채", any_of=("퇴직급여충당", "퇴직급여 충당", "퇴직충당"))
    plan = b.accounts(cls="자산", any_of=("퇴직연금", "퇴직보험"), none_of=("전환금",))
    conv = b.accounts(any_of=("퇴직금전환금",))
    pay = b.accounts(cls="비용", any_of=("급여", "임금", "상여"), none_of=("퇴직",))
    p.accounts = exp + prov + plan
    p.lines = [LineRow(ln, b.by_code.get(ln.account, {}).get("name", ""), "") for ln in b.lines_of(prov + plan)]

    pv_open = -sum(int(a.get("opening") or 0) for a in prov)
    pv_dec = sum(int(a.get("debit") or 0) for a in prov)
    pv_inc, pv_other = provision_credits(b, prov)
    income = sum(r["amount"] for r in plan_income_lines(b, plan, prov) if r["to"] == "충당부채") if prov else 0
    income = min(income, pv_other)
    pv_close = -sum(int(a.get("closing") or 0) for a in prov)
    pl_open = sum(int(a.get("opening") or 0) for a in plan)
    fees = plan_fees(b, plan) if plan else 0
    pl_inc = sum(int(a.get("debit") or 0) for a in plan) + fees
    pl_dec = sum(int(a.get("credit") or 0) for a in plan) + fees
    pl_close = sum(int(a.get("closing") or 0) for a in plan)
    res_open = p.take(b, "기초부인누계", _prior_reserve(b, "퇴직급여충당", "퇴직충당"), "int")
    # 전기 50호(을)을 모르면(11-08, 제품 papers/retirement.py:148-150) 직전까지 손금산입한 퇴직연금부담금 누계를 0 으로 보지 않는다.
    # 0 으로 보면 기초 운용자산까지 당기 손금산입이 된다. 노란 칸을 빈 칸(글 칸)으로 두고, 회계사가 값(0 포함)을 넣어야 계산한다
    unknown = b.reserves_unknown
    pen_blank = bool(unknown and plan and pl_open > 0)
    if pen_blank:
        raw = p.take(b, "기손금산입누계", "", "text")
        try:
            pen_open = int(round(float(raw.replace(",", "")))) if raw else None
        except ValueError:
            pen_open = None
            p.confirm.append(f"노란 칸 「기손금산입누계」 값 「{raw}」 을 숫자로 읽지 못했습니다")
    else:
        pen_open = p.take(b, "기손금산입누계", -_prior_reserve(b, "퇴직연금", "퇴직보험"), "int")
    pen_known = pen_open is not None
    pen_open = pen_open or 0
    est0, est_how, alt, alt_how = estimate_default(b, pv_open, pv_close, pl_open, pl_close)
    estimate = p.take(b, "퇴직급여추계액", est0, "int")
    conversion = p.take(b, "퇴직금전환금", sum(int(a.get("closing") or 0) for a in conv), "int")
    vouchers: dict[tuple, list] = {}
    for x in b.all_lines():
        vouchers.setdefault((x.date, x.no), []).append(x)
    leave = leave_accrual(b.lines_of(pay), lambda ln: [o for o in vouchers.get((ln.date, ln.no), []) if o is not ln])
    salary = p.take(b, "총급여액", fs_sum(pay) - leave, "int")
    if leave and "총급여액" not in p.overridden:
        p.notes.append(f"총급여액 기본값은 급여 계정 합계에서 연차수당 미지급 계상 · 환입 순액 {leave:,}원을 뺀 지급 기준입니다"
                       "(근로소득 지급명세와 대조)")

    tax_open = pv_open - res_open
    reversal = min(res_open, max(0, pv_dec - tax_open)) if res_open > 0 else 0
    before = max(0, pv_open - res_open - pv_dec + reversal)
    pen_rev = min(pen_open, pl_dec) if pen_open > 0 else 0
    pen_left = pen_open - pen_rev
    args = (conversion, salary, pv_inc, pv_close, res_open, before, reversal, pl_close, pen_left, income)
    got = _limits(b, estimate, *args)
    lim_salary, lim_est, limit, over = got["lim_salary"], got["lim_est"], got["limit"], got["over"]
    res_close, tax_close, pen_limit, pen_target = got["res_close"], got["tax_close"], got["pen_limit"], got["pen_target"]
    pen_ded, pen_over = got["pen_ded"], got["pen_over"]
    if not pen_known:                   # 33호 손금산입 · 지급분 추인 · 누계 한도초과를 내지 않는다(엑셀도 빈 칸이면 0)
        what_if = pen_ded
        pen_rev = pen_ded = pen_over = 0
    p.values = {"충당금기초": pv_open, "충당금감소": pv_dec, "충당금설정": pv_inc, "충당금기말": pv_close,
                "기초부인누계": res_open, "부인액추인": reversal, "설정전세무상잔액": before,
                "충당금그밖증가": pv_other, "운용수익익금산입": income,
                "급여액기준한도": lim_salary, "추계액기준한도": lim_est, "한도": limit, "한도초과": over,
                "기말부인누계": res_close, "세무상충당금기말": tax_close,
                "운용자산기초": pl_open, "운용자산납입": pl_inc, "운용자산감소": pl_dec, "운용자산기말": pl_close,
                "기손금산입누계": pen_open if pen_known else None, "연금지급추인": pen_rev, "연금손금산입한도": pen_limit,
                "연금손금산입대상": pen_target, "연금손금산입": pen_ded, "연금한도초과": pen_over,
                "퇴직급여(비용)": fs_sum(exp)}
    _plan_income(p, b, plan, prov)
    if pv_other - income:
        p.confirm.append(f"퇴직급여충당부채 대변 중 퇴직급여(비용)가 상대가 아닌 금액 {pv_other - income:,}원이 있습니다(32호 당기 설정액에 넣지 않음)."
                         " 계열사 전입 · 운용수익 등이면 성격에 맞게 15호에서 따로 조정하십시오")
    ps, ls = subject_of(prov, "퇴직급여충당금"), subject_of(plan, "퇴직연금운용자산")
    p.adjustments = [
        Adj("가산", ps, over, "유보", "퇴직급여충당금 한도초과", "퇴직급여충당금 한도초과액 손금불산입", "한도초과", ps, "증가", 1),
        Adj("가산", ps, income, "유보", "퇴직연금 운용수익 익금산입", "퇴직연금 운용수익을 수익 없이 퇴직급여충당부채에 더한 금액 익금산입",
            "운용수익익금산입", ps, "증가", 1),
        Adj("차감", ps, reversal, "유보", "퇴직급여충당금 부인액 추인", "전기 부인액 중 당기 지급분 손금산입", "부인액추인", ps, "감소", 1),
        Adj("차감", ls, pen_ded, "유보", "퇴직연금부담금 손금산입", "퇴직연금운용자산 신고조정 손금산입", "연금손금산입", ls, "증가", -1),
        Adj("가산", ls, pen_rev, "유보", "퇴직연금 지급분 추인", "전기 손금산입 퇴직연금 중 당기 지급분 손금불산입", "연금지급추인", ls, "감소", -1),
        Adj("가산", ls, pen_over, "유보", "퇴직연금부담금 한도초과", "퇴직연금 손금산입 누계 한도초과 손금불산입", "연금한도초과", ls, "증가", 1),
    ]
    if (prov or plan) and "퇴직급여추계액" not in p.overridden:
        p.confirm.append(f"퇴직급여추계액을 회사 자료 없이 장부 잔액 {estimate:,}원으로 넣었습니다. 계리 · 근퇴법 추계액으로 바꾸세요")
        p.notes.append(f"퇴직급여추계액 기본값 {estimate:,}원은 {est_how}입니다")
        if alt != estimate:
            o = _limits(b, alt, *args)
            p.confirm.append(f"추계액을 {alt_how} {alt:,}원으로 두면 퇴직급여충당금 한도초과 {o['over']:,}원 · 퇴직연금부담금 손금산입 "
                             f"{o['pen_ded']:,}원 · 퇴직연금 한도초과 {o['pen_over']:,}원입니다(지금 값: 한도초과 {over:,}원 · 손금산입 "
                             f"{pen_ded:,}원 · 한도초과 {pen_over:,}원)")
    if not pen_known:
        p.confirm.append(f"{unknown}. 전기 50호(을)을 몰라 직전 사업연도까지 손금산입한 퇴직연금부담금 누계(33호 ⑭)를 알 수 없어 "
                         f"퇴직연금부담금 손금산입 조정을 내지 않았습니다. 전기말 퇴직연금운용자산 △유보 잔액을 노란 칸 「기손금산입누계」 "
                         f"에 넣으면(없으면 0) 33호가 계산됩니다(운용자산 기초 {pl_open:,}원, 0 을 넣으면 손금산입 {what_if:,}원)")
    if unknown and prov and pv_open > 0 and "기초부인누계" not in p.overridden:
        p.confirm.append(b.reserves_unknown_text("퇴직급여충당금 기초 부인누계(32호 ⑦)", "기초부인누계"))
    gap = prior_32_gap(b, res_open) if prov and "기초부인누계" not in p.overridden else None
    p.values["전기32부인누계차이"] = gap or 0
    if gap:
        p.confirm.append(f"추가 자료 필요(퇴직금전환금 명세). 전기 50호(을) 퇴직급여충당금 유보 {res_open:,}원이 전기 32호로 다시 센 부인누계 "
                         f"{res_open + gap:,}원과 {abs(gap):,}원 다릅니다. 퇴직금전환금 · 경정 반영 여부를 장부만으로 가릴 수 없어 엔진이 금액을 "
                         "정하지 않고 신고된 50호(을) 값을 기초부인누계로 두었습니다(확인 전). 퇴직금전환금 명세와 전기 경정 내역으로 확인하고 "
                         "다르면 기초부인누계 노란 칸을 고치세요")
    if exp and not (prov or plan):
        p.notes.append("퇴직급여충당금 · 퇴직연금운용자산 계정이 없습니다. 지급 시 비용 처리했거나 확정기여형이면 조정이 없습니다")
    p.notes.append("설정 한도는 추계액 기준(추계액 × 0% + 퇴직금전환금 - 설정 전 세무상 잔액)과 총급여액 5% 중 작은 금액입니다")
    p.settle(bool(prov or plan))


def _plan_income(p: Paper, b: Books, plan: list[dict], prov: list[dict]) -> None:
    """운용수익 직접 대체 감지. values 에 금액, 충당부채로 간 몫은 compute 가 익금산입으로 올린다."""
    rows = plan_income_lines(b, plan, prov)
    to_prov = sum(r["amount"] for r in rows if r["to"] == "충당부채")
    other = sum(r["amount"] for r in rows if r["to"] == "그 밖")
    p.extra["plan_income"] = rows
    p.values.update({"운용수익 충당부채 대체": to_prov, "운용수익 그 밖 대체": other})
    if to_prov:
        p.confirm.append(f"퇴직연금 운용수익 {to_prov:,}원을 수익이 아니라 퇴직급여충당부채에 더한 전표가 있습니다(같은 전표에 수익 계정 없음). "
                         "32호 당기 설정액에는 넣지 않고 15호 가산 「퇴직연금 운용수익 익금산입」(퇴직급여충당부채 유보)으로 올렸습니다"
                         "(법인세법 제15조 제1항)")
    if other:
        names = " · ".join(sorted({r["counter"] for r in rows if r["to"] == "그 밖"}))
        p.confirm.append(f"퇴직연금 운용수익 {other:,}원을 수익 계정 없이 {names or '다른 계정'}에 바로 적은 전표가 있습니다. 운용수익은 "
                         f"익금이라 넣으면 15호 가산 {other:,}원입니다(법인세법 제15조 제1항, 회계 판단이라 조정하지 않음)")


def write(bk: Book, p: Paper) -> None:
    s = head(bk, p)
    row = 5
    row = s.section(row, "1. 금액 검증")
    for col, label in ((3, "코드"), (4, "계정"), (7, "기말(재무제표)")):
        X.header(s.ws, row, [label], col=col)
    row += 1
    for a in p.accounts:
        s.put(row, 3, a["code"])
        s.put(row, 4, a["name"])
        s.put(row, 7, int(a.get("amount") or 0), money=True)
        row += 1
    if not p.accounts:
        s.put(row, 4, "퇴직급여 관련 계정이 없습니다")
        row += 1
    row += 1
    row, first, last = ledger(bk, s, row, p, "", title="2. 원장 검토(퇴직급여충당금 · 퇴직연금운용자산)")
    v, R, I = p.values, bk.ref, p.inputs
    row = s.section(row, "3. 퇴직급여충당금 한도(32호)")
    r = Rows(bk, s, p, row)
    g = r.g
    r.put("충당금기초", "장부상 기초 충당금", v["충당금기초"])
    r.put("충당금감소", "당기 감소(지급)", v["충당금감소"])
    r.put("충당금설정", "당기 설정(퇴직급여 비용이 상대인 증가, 32호 ⑮)", v["충당금설정"])
    r.put("충당금그밖증가", "그 밖 증가(비용 상대가 아닌 대변, 설정액에서 뺌)", v["충당금그밖증가"])
    r.put("충당금기말", "장부상 기말 충당금", v["충당금기말"])
    r.put("기초부인누계", "기초 부인누계(전기 50호(을))", I["기초부인누계"], kind="input", input_kind="int")
    r.put("부인액추인", "부인액 추인(지급액이 세무상 기초 잔액을 넘은 만큼)",
          f"=IF({g('기초부인누계')}>0,MIN({g('기초부인누계')},MAX(0,{g('충당금감소')}-({g('충당금기초')}-{g('기초부인누계')}))),0)")
    r.put("설정전세무상잔액", "설정 전 세무상 잔액",
          f"=MAX(0,{g('충당금기초')}-{g('기초부인누계')}-{g('충당금감소')}+{g('부인액추인')})")
    r.put("총급여액", "총급여액(퇴직급여 지급 대상)", I["총급여액"], kind="input", input_kind="int")
    r.put("퇴직급여추계액", "퇴직급여 추계액", I["퇴직급여추계액"], kind="input", input_kind="int")
    r.put("퇴직금전환금", "퇴직금전환금", I["퇴직금전환금"], kind="input", input_kind="int")
    r.put("급여액기준한도", "① 총급여액 기준(5%)", f"=ROUNDDOWN({g('총급여액')}*{R['퇴직급여충당금 총급여 비율']},0)")
    r.put("추계액기준한도", "② 추계액 기준(추계액 × 0% + 전환금 - 설정 전 잔액)",
          f"=MAX(0,ROUNDDOWN({g('퇴직급여추계액')}*{R['퇴직급여충당금 추계액 비율']},0)+{g('퇴직금전환금')}-{g('설정전세무상잔액')})")
    r.put("한도", "③ 한도(① · ② 중 작은 금액)", f"=MIN({g('급여액기준한도')},{g('추계액기준한도')})")
    r.put("한도초과", "한도초과(가산 · 유보)", f"=MAX(0,{g('충당금설정')}-{g('한도')})")
    r.put("운용수익익금산입", "퇴직연금 운용수익 익금산입(충당부채에 더한 운용수익, 가산 · 유보)", v["운용수익익금산입"])
    r.put("기말부인누계", "기말 부인누계", f"={g('기초부인누계')}-{g('부인액추인')}+{g('한도초과')}+{g('운용수익익금산입')}")
    r.put("세무상충당금기말", "세무상 기말 충당금", f"={g('충당금기말')}-{g('기말부인누계')}")
    r.row = s.section(r.row + 1, "3-1. 퇴직연금부담금(33호)")
    r.put("운용자산기초", "퇴직연금운용자산 기초", v["운용자산기초"])
    r.put("운용자산납입", "당기 납입", v["운용자산납입"])
    r.put("운용자산감소", "당기 감소(지급 · 해지)", v["운용자산감소"])
    r.put("운용자산기말", "퇴직연금운용자산 기말", v["운용자산기말"])
    blank = isinstance(I["기손금산입누계"], str)        # 전기 50호(을)을 몰라 빈 칸(글 칸)으로 둔 경우
    pen_in = I["기손금산입누계"]
    if blank:
        try:
            pen_in = int(round(float(pen_in.replace(",", "")))) if pen_in else None
        except ValueError:
            pen_in = pen_in or None
    r.put("기손금산입누계", "직전까지 손금산입한 부담금(전기 50호(을) △" + (", 모르면 빈 칸: 넣어야 33호 계산)" if blank else ")"),
          pen_in, kind="input", input_kind="text" if blank else "int")
    k = g("기손금산입누계")
    r.put("연금지급추인", "지급분 추인(가산 · 유보)", f'=IF({k}&""="",0,IF({k}>0,MIN({k},{g("운용자산감소")}),0))')
    r.put("연금손금산입한도", "손금산입 한도(추계액 - 세무상 기말 충당금)", f"=MAX(0,{g('퇴직급여추계액')}-{g('세무상충당금기말')})")
    r.put("연금손금산입대상", "손금산입 대상(한도 · 기말 운용자산 중 작은 금액)", f"=MIN({g('연금손금산입한도')},{g('운용자산기말')})")
    r.put("연금손금산입", "당기 손금산입(차감 · 유보, 누계 칸이 비면 0)",
          f'=IF({k}&""="",0,MAX(0,{g("연금손금산입대상")}-({k}-{g("연금지급추인")})))')
    r.put("연금한도초과", "손금산입 누계 한도초과(가산 · 유보, 누계 칸이 비면 0)",
          f'=IF({k}&""="",0,MAX(0,({k}-{g("연금지급추인")})-{g("연금손금산입대상")}))')
    r.put("퇴직급여(비용)", "손익계산서 퇴직급여", v["퇴직급여(비용)"])
    r.row = s.section(r.row + 1, "3-2. 운용수익을 수익 없이 적은 전표")
    for it in p.extra.get("plan_income") or []:
        s.put(r.row, 1, it["date"])
        s.put(r.row, 2, it["no"])
        s.put(r.row, 4, f"상대 {it['counter'] or '없음'}")
        s.put(r.row, 6, it["memo"])
        s.put(r.row, 7, it["amount"], money=True)
        s.put(r.row, 8, f"{it['to']}에 더함")
        r.row += 1
    r.put("운용수익 충당부채 대체", "운용수익을 퇴직급여충당부채에 더한 금액(익금산입으로 올림)", v["운용수익 충당부채 대체"])
    r.put("운용수익 그 밖 대체", "운용수익을 충당부채 · 비용 · 수익이 아닌 계정에 더한 금액(익금 누락 의심)", v["운용수익 그 밖 대체"])
    row = adj_table(bk, s, r.row + 1, p)
    row = forms_table(bk, s, row, p, [("32", "당기 설정액", "충당금설정"), ("32", "손금산입 한도액", "한도"),
                                      ("32", "한도초과액", "한도초과"), ("33", "손금산입액", "연금손금산입")])
    notes(s, row, p)
