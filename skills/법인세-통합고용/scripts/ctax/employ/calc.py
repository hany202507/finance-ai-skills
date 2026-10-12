"""통합고용세액공제 상시근로자 수와 공제액을 파이썬으로 계산한다(엑셀 수식과 따로 계산해 서로 맞춰 보는 쪽).

기준은 rules.yaml, 1인당 공제금액은 ctax/wp/rates_2025/credits.yaml 의 employment_integrated 다. 인원은 Fraction 으로 센다.
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date, timedelta
from fractions import Fraction

from .model import PERIODS, Company, Inputs, Person, rule

FAR = date(9999, 12, 31)
REASONS = {"a": "ⓐ근로계약기간 1년 미만", "b": "ⓑ단시간 근로자", "c": "ⓒ법인의 임원", "d": "ⓓ최대주주(출자자) 및 그 친족",
           "e": "ⓔ원천징수사실 미확인 근로자 등", "f": "ⓕ기타", "f_res": "ⓕ기타(내국인 아님)", "f_disp": "ⓕ기타(파견근로자)"}
YOUTH_KINDS = ("장애인", "고령자", "경력단절", "북한이탈주민", "청년")


def add_months(d: date, n: int) -> date:
    """엑셀 EDATE 와 같다: 달을 옮기고 날이 없으면 그 달 말일."""
    m = d.month - 1 + n
    y, m = d.year + m // 12, m % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def month_end(d: date) -> date:
    return date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])


def floor2(x: Fraction) -> Fraction:
    """100분의 1 미만은 버린다."""
    return Fraction(int(x * 100), 100) if x > 0 else Fraction(0)


@dataclass
class Period:
    name: str                 # 해당 · 직전 · 직전전
    start: date
    end: date
    ends: list[date]          # 과세연도 안의 월말
    deemed: bool              # 청년 간주(계약 체결일 기준)를 쓰는지
    has_payroll: bool = False

    @property
    def months(self) -> int:
        return len(self.ends)


@dataclass
class Row:
    """한 사람의 한 과세연도 판정."""
    person: Person
    proof: str = ""                         # 납부 확인: Y · N · 자료없음
    regular: bool = False
    reason: str = ""
    weight: Fraction = Fraction(1)
    worked: list[int] = field(default_factory=list)       # 월말 재직(0 · 1)
    youth_age: list[int] = field(default_factory=list)    # 청년등(현재 연령)
    youth_deem: list[int] = field(default_factory=list)   # 청년등(간주 포함)
    paid: list[int] = field(default_factory=list)         # 그 달 지급액
    kind: str = ""                          # 청년등 구분
    m_work: Fraction = Fraction(0)          # ⑳ 상시근로자 근무개월수(단시간 가중)
    n_work: Fraction = Fraction(0)          # ㉑ 계산한 수
    m_youth_age: Fraction = Fraction(0)
    n_youth_age: Fraction = Fraction(0)
    m_youth_deem: Fraction = Fraction(0)
    n_youth_deem: Fraction = Fraction(0)
    no_pay: int = 0                         # 월말 재직인데 급여가 없는 달 수
    odd_pay: int = 0                        # 재직 기간이 아닌데 급여가 있는 달 수


@dataclass
class Count:
    """한 과세연도 인원. 근로자별 방식과 월말 합 방식."""
    period: Period
    rows: list[Row]
    total: Fraction = Fraction(0)           # 근로자별 ② 상시
    youth_age: Fraction = Fraction(0)       # 근로자별 ⑨ 청년등(현재 연령)
    youth_deem: Fraction = Fraction(0)      # 근로자별 ⑨ 청년등(간주 포함)
    me_sum: Fraction = Fraction(0)          # 월말 합(상시)
    me_youth_sum: Fraction = Fraction(0)    # 월말 합(청년등, 현재 연령)
    me_total: Fraction = Fraction(0)        # 월말 합 방식 상시
    me_youth: Fraction = Fraction(0)        # 월말 합 방식 청년등
    monthly: list[Fraction] = field(default_factory=list)        # 달마다 월말 현재 상시근로자 수
    monthly_paid: list[int] = field(default_factory=list)        # 달마다 급여가 있는 사람 수
    monthly_worked: list[int] = field(default_factory=list)      # 달마다 월말 재직 사람 수(상시 여부와 무관)


# ---------------------------------------------------------------- 사람

def adjusted_birth(p: Person, rules: dict) -> date:
    """병역 기간(6년 한도)을 뺀 나이를 재려고 생년월일을 그만큼 늦춘다."""
    if p.mil_from and p.mil_to:
        days = min((p.mil_to - p.mil_from).days + 1, int(rule(rules, "youth", "military_cap_days")))
        return p.birth + timedelta(days=max(0, days))
    return p.birth


def age_limits(p: Person, rules: dict) -> tuple[date, date]:
    """(15세가 되는 날, 병역을 뺀 나이로 35세가 되는 날). 이 사이의 날은 청년 나이다."""
    return (add_months(p.birth, 12 * int(rule(rules, "youth", "age_from"))),
            add_months(adjusted_birth(p, rules), 12 * (int(rule(rules, "youth", "age_to")) + 1)))


def deemed_until(p: Person, size: str, rules: dict) -> date | None:
    """계약 체결일에 청년 나이였던 정규직이 청년으로 간주되는 기간의 끝(그날부터 청년이 아니다). 해당 없으면 None.
    간주는 2025년 1월 1일 이후 체결한 계약에만 있다(2026-10-12 회계사 확인, rules.yaml youth.deemed_from)."""
    lo, hi = age_limits(p, rules)
    if p.kind != "정규직" or not (lo <= p.hired < hi) or p.hired < date.fromisoformat(rule(rules, "youth", "deemed_from")):
        return None
    key = "deemed_years_2025" if p.hired.year == 2025 else "deemed_years_other"
    return add_months(p.hired, 12 * int(rule(rules, "youth", key)[size]))


def youth_cutoff(p: Person, size: str, rules: dict, deemed: bool) -> date:
    """청년 제외시점: 이 날부터 청년(제1호)이 아니다."""
    hi = age_limits(p, rules)[1]
    until = deemed_until(p, size, rules) if deemed else None
    return max(hi, until) if until else hi


def is_senior(p: Person, rules: dict) -> bool:
    return p.hired >= add_months(p.birth, 12 * int(rule(rules, "youth", "senior_age")))


def fixed_youth(p: Person, rules: dict) -> bool:
    """나이와 상관없이 청년등인 사람(장애인 등 · 고령자 · 경력단절 · 북한이탈주민)."""
    return p.disabled == "Y" or is_senior(p, rules) or p.career == "Y" or p.defector == "Y"


def youth_kind(p: Person, rules: dict) -> str:
    if p.disabled == "Y":
        return "장애인"
    if is_senior(p, rules):
        return "고령자"
    if p.career == "Y":
        return "경력단절"
    if p.defector == "Y":
        return "북한이탈주민"
    return "청년"


def common_reason(p: Person, rules: dict) -> str:
    """과세연도와 상관없는 상시근로자 제외 사유(없으면 빈 글)."""
    if p.resident == "N":
        return REASONS["f_res"]
    if p.kind == "파견":
        return REASONS["f_disp"]
    if p.short == "Y":
        return REASONS["a"]
    if p.kind == "단시간" and (p.hours or 0) < float(rule(rules, "scope", "part_time_hours")):
        return REASONS["b"]
    if p.officer == "Y":
        return REASONS["c"]
    if p.owner == "Y":
        return REASONS["d"]
    if p.other == "Y":
        return REASONS["f"]
    return ""


def weight_of(p: Person, rules: dict) -> Fraction:
    if p.kind == "단시간" and (p.hours or 0) >= float(rule(rules, "scope", "part_time_hours")):
        key = "part_time_weight_supported" if p.supported == "Y" else "part_time_weight"
        return Fraction(str(rule(rules, "scope", key)))
    return Fraction(1)


# ---------------------------------------------------------------- 과세연도

def periods(co: Company, rules: dict) -> dict[str, Period]:
    """해당 · 직전 · 직전전 과세연도. 직전 · 직전전은 12개월로 본다."""
    out = {}
    start, end = co.fy_start, co.fy_end
    new_rule = start >= date.fromisoformat(rule(rules, "youth", "deemed_from"))
    for i, name in enumerate(PERIODS):
        s = add_months(co.fy_start, -12 * i)
        e = end if i == 0 else add_months(co.fy_start, -12 * (i - 1)) - timedelta(days=1)
        ends, m = [], s
        while month_end(m) <= e:
            ends.append(month_end(m))
            m = add_months(date(m.year, m.month, 1), 1)
        out[name] = Period(name, s, e, ends, deemed=new_rule and i == 0 and co.deem != "N")
    return out


def count_period(inp: Inputs, per: Period, rules: dict) -> Count:
    co = inp.company
    pays = [x for x in inp.pays if per.start <= x.month <= per.end]
    per.has_payroll = bool(pays)
    by_id: dict[str, list] = {}
    for x in pays:
        by_id.setdefault(x.id, []).append(x)
    rows = []
    for p in inp.staff:
        r = Row(person=p, weight=weight_of(p, rules), kind=youth_kind(p, rules))
        mine = by_id.get(p.id, [])
        if not per.has_payroll:
            r.proof = "자료없음"
        else:
            r.proof = "Y" if sum(x.tax + x.pension + x.health for x in mine) > 0 else "N"
        common = common_reason(p, rules)
        r.regular = not common and r.proof != "N"
        r.reason = common or ("" if r.proof != "N" else REASONS["e"])
        lo, hi = age_limits(p, rules)
        cut = youth_cutoff(p, co.size, rules, per.deemed)
        fixed = fixed_youth(p, rules)
        left = p.left or FAR
        for e in per.ends:
            first = date(e.year, e.month, 1)
            paid = sum(x.pay for x in mine if x.month == first)
            on = p.hired <= e <= left                    # 월말 재직
            # 급여대장이 있는 과세연도는 그 달 급여가 있어야 근무개월로 센다(2026-10-12 회계사 확인, rules.yaml count.unpaid_month)
            w = 1 if on and (paid or not per.has_payroll or co.unpaid == "Y") else 0
            r.worked.append(w)
            r.youth_age.append(1 if w and (fixed or (p.kind == "정규직" and lo <= e < hi)) else 0)
            r.youth_deem.append(1 if w and (fixed or (p.kind == "정규직" and lo <= e < cut)) else 0)
            r.paid.append(paid)
            if on and not paid and per.has_payroll:
                r.no_pay += 1
            if paid and (e < p.hired or first > left):
                r.odd_pay += 1
        if r.regular:
            m = Fraction(per.months)
            r.m_work = r.weight * sum(r.worked)
            r.n_work = floor2(r.m_work / m)
            r.m_youth_age = r.weight * sum(r.youth_age)
            r.n_youth_age = floor2(r.m_youth_age / m)
            r.m_youth_deem = r.weight * sum(r.youth_deem)
            r.n_youth_deem = floor2(r.m_youth_deem / m)
        rows.append(r)
    c = Count(period=per, rows=rows)
    reg = [r for r in rows if r.regular]
    c.total = sum((r.n_work for r in reg), Fraction(0))
    c.youth_age = sum((r.n_youth_age for r in reg), Fraction(0))
    c.youth_deem = sum((r.n_youth_deem for r in reg), Fraction(0))
    for i in range(per.months):
        c.monthly.append(sum((r.weight * r.worked[i] for r in reg), Fraction(0)))
        c.monthly_paid.append(sum(1 for r in rows if r.paid[i] > 0))
        c.monthly_worked.append(sum(r.worked[i] for r in rows))
    c.me_sum = sum(c.monthly, Fraction(0))
    c.me_youth_sum = sum((r.weight * sum(r.youth_age) for r in reg), Fraction(0))
    if per.months:
        c.me_total = floor2(c.me_sum / per.months)
        c.me_youth = floor2(c.me_youth_sum / per.months)
    return c


# ---------------------------------------------------------------- 공제액

def per_head(size: str, capital: str, rates: dict) -> tuple[int, int]:
    """(청년등, 청년등 외) 1인당 공제금액(조세특례제한법 제29조의8 제1항 제1호 · 제2호)."""
    r = lambda k: int(rates["employment_integrated"][k]["value"])   # noqa: E731
    if size == "중소기업":
        tail = "capital" if capital == "Y" else "local"
        return r(f"youth_sme_{tail}"), r(f"other_sme_{tail}")
    if size == "중견기업":
        return r("youth_mid"), r("other_mid")
    return r("youth_general"), r("other_general")


def compute(inp: Inputs, rules: dict, rates: dict) -> dict:
    """인원(세 과세연도)과 1 · 2 · 3차 연도 · 추가공제 금액."""
    co = inp.company
    pers = periods(co, rules)
    counts = {name: count_period(inp, per, rules) for name, per in pers.items()}
    cur = pers["해당"]
    method = "근로자별" if cur.start >= date.fromisoformat(rule(rules, "youth", "deemed_from")) else "월말합"
    in_time = cur.end.year <= int(rates["employment_integrated"]["first_year_until"]["value"])

    def filed(name: str):
        t = co.filed_prev_total if name == "직전" else co.filed_prev2_total
        y = co.filed_prev_youth if name == "직전" else co.filed_prev2_youth
        if t is None:
            return None
        t, y = floor2(Fraction(str(t))), floor2(Fraction(str(y or 0)))
        return t, y

    # 서식에 쓰는 인원(1차 연도 방식)과 2 · 3차 연도 판정에 쓰는 인원(월말 합 방식)
    used, legacy, source = {}, {}, {}
    for name in PERIODS:
        c = counts[name]
        f = filed(name) if name != "해당" else None
        if name == "해당" or c.period.has_payroll:
            if method == "근로자별" and name != "직전전":
                y = c.youth_deem if name == "해당" else c.youth_age
                used[name] = (c.total, y)
            else:
                used[name] = (c.me_total, c.me_youth)
            legacy[name] = (c.me_total, c.me_youth)
            source[name] = "급여대장"
        elif f:
            used[name], legacy[name], source[name] = f, f, "전기 신고서"
        elif name == "직전" and co.startup == "Y":
            used[name] = legacy[name] = (Fraction(0), Fraction(0))
            source[name] = "창업(0)"
        else:
            used[name] = legacy[name] = (Fraction(0), Fraction(0))
            source[name] = "없음"

    (t_c, y_c), (t_p, y_p) = used["해당"], used["직전"]
    o_c, o_p = t_c - y_c, t_p - y_p
    d_t, d_y, d_o = t_c - t_p, y_c - y_p, o_c - o_p
    a_y, a_o = per_head(co.size, co.capital, rates)
    prev_ok = source["직전"] != "없음"
    ok = co.consumer != "Y" and in_time and prev_ok and d_t > 0
    n_y = max(Fraction(0), min(d_y, d_t)) if ok else Fraction(0)
    n_o = max(Fraction(0), min(d_o, d_t)) if ok else Fraction(0)
    first_y, first_o = round(n_y * a_y), round(n_o * a_o)

    (lt_c, ly_c), (lt_p, ly_p), (lt_pp, ly_pp) = legacy["해당"], legacy["직전"], legacy["직전전"]
    second, second_cut = 0, ""
    f1 = (co.first_prev_youth, co.first_prev_other)
    if any(f1) and co.consumer != "Y":
        if source["직전"] in ("없음", "창업(0)"):
            second_cut = "직전 인원 없음"
        elif lt_c < lt_p:
            second_cut = "전체 감소"
        else:
            cut = ly_c < ly_p
            second = (0 if cut else f1[0]) + f1[1]
            second_cut = "청년등 감소" if cut and f1[0] else ""
    third, third_cut = 0, ""
    f2 = (co.first_prev2_youth, co.first_prev2_other)
    if any(f2) and co.consumer != "Y":
        if co.size == "일반기업":
            third_cut = "일반기업"
        elif source["직전전"] == "없음" or source["직전"] in ("없음", "창업(0)"):
            third_cut = "직전전 인원 없음"
        elif lt_p < lt_pp or lt_c < lt_pp:
            third_cut = "전체 감소"
        else:
            cut = ly_p < ly_pp or ly_c < ly_pp
            third = (0 if cut else f2[0]) + f2[1]
            third_cut = "청년등 감소" if cut and f2[0] else ""

    returned = co.returned if co.returned is not None else sum(
        1 for p in inp.staff if p.returned == "Y" and p.hired <= cur.end and (p.left or FAR) >= cur.start)
    amt_sizes = {"중소기업": int(rule(rules, "extra", "return_sme")), "중견기업": int(rule(rules, "extra", "return_mid"))}
    amt = amt_sizes.get(co.size, 0)
    extra = int(round(float(returned) * amt)) if (co.consumer != "Y" and in_time and prev_ok and t_c >= t_p
                                                and co.size in amt_sizes) else 0

    return {"periods": pers, "counts": counts, "method": method, "in_time": in_time, "used": used, "legacy": legacy,
            "source": source, "d_t": d_t, "d_y": d_y, "d_o": d_o, "n_y": n_y, "n_o": n_o, "a_y": a_y, "a_o": a_o,
            "first_y": first_y, "first_o": first_o, "first": first_y + first_o, "second": second, "second_cut": second_cut,
            "third": third, "third_cut": third_cut, "returned": float(returned), "extra": extra,
            "total": first_y + first_o + second + third + extra}
