"""11 퇴직급여: 퇴직급여충당금 한도초과 · 추인(32호), 퇴직연금부담금 신고조정(33호). 모두 유보.

운용수익 직접 대체(fx3). 퇴직연금운용자산 차변 중 적요에 운용수익 · 이자가 있고 같은 전표에 수익 계정이 없는 줄. 운용수익을
수익으로 적지 않고 퇴직급여충당부채(또는 다른 계정)에 바로 더한 것이다. 상대가 충당부채면 그 금액이 32호 당기 설정액에 들어
한도초과로 더해지고 33호 손금산입(기말 운용자산 기준)에도 들어가, 한도초과가 그 금액 이상이면 소득금액 합계는 수익으로 적은
경우와 같다. 한도 안에 든 몫, 상대가 충당부채 · 비용이 아닌 몫은 익금이 빠진다. 조정은 기본 없음, 확인 줄에 「넣으면 얼마」 를 둔다.
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


def _prior_reserve(b: Books, *words) -> int:
    total = 0
    for r in (b.prior or {}).get("reserves", []) or []:
        if any(w in (r.get("subject") or "") for w in words):
            total += int(r.get("closing") or 0)
    return total


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
            before: int, reversal: int, pl_close: int, pen_left: int) -> dict:
    """추계액 하나로 32호 한도 · 33호 손금산입을 잰다(대안 추계액의 금액도 같은 식으로 보이려고 따로 둔다)."""
    lim_salary = rd(salary * frac(rate(b.rates, "retirement", "salary_ratio")))
    lim_est = max(0, rd(estimate * frac(rate(b.rates, "retirement", "estimate_ratio"))) + conversion - before)
    limit = min(lim_salary, lim_est)
    over = max(0, pv_inc - limit)
    res_close = res_open - reversal + over
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
    pv_inc = sum(int(a.get("credit") or 0) for a in prov)
    pv_close = -sum(int(a.get("closing") or 0) for a in prov)
    pl_open = sum(int(a.get("opening") or 0) for a in plan)
    pl_inc = sum(int(a.get("debit") or 0) for a in plan)
    pl_dec = sum(int(a.get("credit") or 0) for a in plan)
    pl_close = sum(int(a.get("closing") or 0) for a in plan)
    res_open = p.take(b, "기초부인누계", _prior_reserve(b, "퇴직급여충당", "퇴직충당"), "int")
    pen_open = p.take(b, "기손금산입누계", -_prior_reserve(b, "퇴직연금", "퇴직보험"), "int")
    est0, est_how, alt, alt_how = estimate_default(b, pv_open, pv_close, pl_open, pl_close)
    estimate = p.take(b, "퇴직급여추계액", est0, "int")
    conversion = p.take(b, "퇴직금전환금", sum(int(a.get("closing") or 0) for a in conv), "int")
    salary = p.take(b, "총급여액", fs_sum(pay), "int")

    tax_open = pv_open - res_open
    reversal = min(res_open, max(0, pv_dec - tax_open)) if res_open > 0 else 0
    before = max(0, pv_open - res_open - pv_dec + reversal)
    pen_rev = min(pen_open, pl_dec) if pen_open > 0 else 0
    pen_left = pen_open - pen_rev
    args = (conversion, salary, pv_inc, pv_close, res_open, before, reversal, pl_close, pen_left)
    got = _limits(b, estimate, *args)
    lim_salary, lim_est, limit, over = got["lim_salary"], got["lim_est"], got["limit"], got["over"]
    res_close, tax_close, pen_limit, pen_target = got["res_close"], got["tax_close"], got["pen_limit"], got["pen_target"]
    pen_ded, pen_over = got["pen_ded"], got["pen_over"]
    p.values = {"충당금기초": pv_open, "충당금감소": pv_dec, "충당금설정": pv_inc, "충당금기말": pv_close,
                "기초부인누계": res_open, "부인액추인": reversal, "설정전세무상잔액": before,
                "급여액기준한도": lim_salary, "추계액기준한도": lim_est, "한도": limit, "한도초과": over,
                "기말부인누계": res_close, "세무상충당금기말": tax_close,
                "운용자산기초": pl_open, "운용자산납입": pl_inc, "운용자산감소": pl_dec, "운용자산기말": pl_close,
                "기손금산입누계": pen_open, "연금지급추인": pen_rev, "연금손금산입한도": pen_limit,
                "연금손금산입대상": pen_target, "연금손금산입": pen_ded, "연금한도초과": pen_over,
                "퇴직급여(비용)": fs_sum(exp)}
    _plan_income(p, b, plan, prov, over)
    ps, ls = subject_of(prov, "퇴직급여충당금"), subject_of(plan, "퇴직연금운용자산")
    p.adjustments = [
        Adj("가산", ps, over, "유보", "퇴직급여충당금 한도초과", "퇴직급여충당금 한도초과액 손금불산입", "한도초과", ps, "증가", 1),
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
    if exp and not (prov or plan):
        p.notes.append("퇴직급여충당금 · 퇴직연금운용자산 계정이 없습니다. 지급 시 비용 처리했거나 확정기여형이면 조정이 없습니다")
    p.notes.append("설정 한도는 추계액 기준(추계액 × 0% + 퇴직금전환금 - 설정 전 세무상 잔액)과 총급여액 5% 중 작은 금액입니다")
    p.settle(bool(prov or plan))


def _plan_income(p: Paper, b: Books, plan: list[dict], prov: list[dict], over: int) -> None:
    """운용수익 직접 대체 감지(조정 없음). values 에 금액, 확인 줄에 넣으면 얼마."""
    rows = plan_income_lines(b, plan, prov)
    to_prov = sum(r["amount"] for r in rows if r["to"] == "충당부채")
    other = sum(r["amount"] for r in rows if r["to"] == "그 밖")
    p.extra["plan_income"] = rows
    p.values.update({"운용수익 충당부채 대체": to_prov, "운용수익 그 밖 대체": other})
    if to_prov:
        inside = min(to_prov, over)
        msg = (f"퇴직연금 운용수익 {to_prov:,}원을 수익이 아니라 퇴직급여충당부채에 더한 전표가 있습니다(같은 전표에 수익 계정 없음). "
               "이 조서는 그 금액을 32호 당기 설정액에 넣어 한도초과로 더하고 33호 손금산입(기말 운용자산)에도 넣습니다")
        if inside == to_prov:
            msg += (". 그래서 소득금액 합계는 수익으로 적은 경우와 같습니다. 15호에 운용수익 익금산입으로 따로 보이려면 32호 설정액에서 "
                    f"{to_prov:,}원을 빼야 두 번 더해지지 않습니다")
        else:
            msg += (f". 한도 안에 든 {to_prov - inside:,}원은 익금이 빠진 것이라 넣으면 15호 가산 {to_prov - inside:,}원"
                    "(퇴직급여충당부채 유보)입니다")
        p.confirm.append(msg + "(법인세법 제15조 제1항)")
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
    r.put("충당금설정", "당기 설정(증가)", v["충당금설정"])
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
    r.put("기말부인누계", "기말 부인누계", f"={g('기초부인누계')}-{g('부인액추인')}+{g('한도초과')}")
    r.put("세무상충당금기말", "세무상 기말 충당금", f"={g('충당금기말')}-{g('기말부인누계')}")
    r.row = s.section(r.row + 1, "3-1. 퇴직연금부담금(33호)")
    r.put("운용자산기초", "퇴직연금운용자산 기초", v["운용자산기초"])
    r.put("운용자산납입", "당기 납입", v["운용자산납입"])
    r.put("운용자산감소", "당기 감소(지급 · 해지)", v["운용자산감소"])
    r.put("운용자산기말", "퇴직연금운용자산 기말", v["운용자산기말"])
    r.put("기손금산입누계", "직전까지 손금산입한 부담금(전기 50호(을) △)", I["기손금산입누계"], kind="input", input_kind="int")
    r.put("연금지급추인", "지급분 추인(가산 · 유보)", f"=IF({g('기손금산입누계')}>0,MIN({g('기손금산입누계')},{g('운용자산감소')}),0)")
    r.put("연금손금산입한도", "손금산입 한도(추계액 - 세무상 기말 충당금)", f"=MAX(0,{g('퇴직급여추계액')}-{g('세무상충당금기말')})")
    r.put("연금손금산입대상", "손금산입 대상(한도 · 기말 운용자산 중 작은 금액)", f"=MIN({g('연금손금산입한도')},{g('운용자산기말')})")
    r.put("연금손금산입", "당기 손금산입(차감 · 유보)", f"=MAX(0,{g('연금손금산입대상')}-({g('기손금산입누계')}-{g('연금지급추인')}))")
    r.put("연금한도초과", "손금산입 누계 한도초과(가산 · 유보)", f"=MAX(0,({g('기손금산입누계')}-{g('연금지급추인')})-{g('연금손금산입대상')})")
    r.put("퇴직급여(비용)", "손익계산서 퇴직급여", v["퇴직급여(비용)"])
    r.row = s.section(r.row + 1, "3-2. 운용수익을 수익 없이 적은 전표(조정 없음, 확인 줄)")
    for it in p.extra.get("plan_income") or []:
        s.put(r.row, 1, it["date"])
        s.put(r.row, 2, it["no"])
        s.put(r.row, 4, f"상대 {it['counter'] or '없음'}")
        s.put(r.row, 6, it["memo"])
        s.put(r.row, 7, it["amount"], money=True)
        s.put(r.row, 8, f"{it['to']}에 더함")
        r.row += 1
    r.put("운용수익 충당부채 대체", "운용수익을 퇴직급여충당부채에 더한 금액(32호 설정액에 들어 있음)", v["운용수익 충당부채 대체"])
    r.put("운용수익 그 밖 대체", "운용수익을 충당부채 · 비용 · 수익이 아닌 계정에 더한 금액(익금 누락 의심)", v["운용수익 그 밖 대체"])
    row = adj_table(bk, s, r.row + 1, p)
    row = forms_table(bk, s, row, p, [("32", "당기 설정액", "충당금설정"), ("32", "손금산입 한도액", "한도"),
                                      ("32", "한도초과액", "한도초과"), ("33", "손금산입액", "연금손금산입")])
    notes(s, row, p)
