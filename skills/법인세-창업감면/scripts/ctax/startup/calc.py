"""창업중소기업 세액감면 계산(결정적). 같은 값을 워크북 수식이 따로 계산하고 「6엔진대조」 시트가 견준다.

순서: 창업 해당 → 감면기간 → 청년 · 지역 · 소규모 · 신성장으로 감면율 → 고용증가 추가감면율 → 감면세액(법인세법 제59조 제2항)
→ 최저한세(111 줄만) → 5억원 한도 → 중복 배제 선택. 근거는 rules.yaml.
"""
from __future__ import annotations

import math
from datetime import date, timedelta
from fractions import Fraction as F

from .model import REGIONS, Inputs, Year

BIG_STAFF = ("광업", "제조업", "건설업", "물류산업")


def edate(d: date, months: int) -> date:
    """엑셀 EDATE: 달을 더하고 그 달에 없는 날은 말일로."""
    y, m = divmod(d.month - 1 + months, 12)
    y, m = d.year + y, m + 1
    last = (date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)).day
    return date(y, m, min(d.day, last))


def months_between(a: date, b: date) -> int:
    """엑셀 DATEDIF(a, b, "m")."""
    n = (b.year - a.year) * 12 + (b.month - a.month)
    if b.day < a.day:
        n -= 1
    return max(n, 0)


def years_between(a: date, b: date) -> int:
    """엑셀 DATEDIF(a, b, "y")."""
    return months_between(a, b) // 12


def _d(rules: dict, *path) -> date:
    v = rules
    for p in path:
        v = v[p]
    return date.fromisoformat(str(v["value"] if isinstance(v, dict) and "value" in v else v))


def region_key(era: str, region: str) -> str:
    if region == REGIONS[0]:
        return "과밀"
    if era == "2025이전":
        return "과밀외"
    return "수도권" if region == REGIONS[1] else "지방"


def year_list(inp: Inputs) -> list[Year]:
    """연도별 시트 + 해당 과세연도(시트에 없으면 회사 시트 값으로 더한다)."""
    v = inp.values
    ys = [y for y in inp.years]
    if not any(y.end == v["과세연도 종료일"] for y in ys):
        ys.append(Year(v["과세연도 시작일"], v["과세연도 종료일"], v["감면소득"], v["수입금액"], v["상시근로자 수(해당)"]))
    ys.sort(key=lambda y: y.end)
    return ys


def first_income_end(inp: Inputs, ys: list[Year], rules: dict) -> tuple[date | None, str]:
    v = inp.values
    if v["최초 소득 발생 과세연도 종료일"]:
        return v["최초 소득 발생 과세연도 종료일"], "회사 시트에 넣은 값"
    found = v["창업일"]
    for y in ys:
        if y.end >= found and y.income > 0:
            return y.end, f"연도별 시트에서 감면사업 소득금액이 처음 0 보다 큰 과세연도({y.start} ~ {y.end})"
    day5 = edate(found, 12 * rules["period"]["no_income_years"]["value"]) - timedelta(days=1)
    for y in ys:
        if y.end >= day5:
            return y.end, f"사업 개시일부터 5년이 되는 날({day5})이 속하는 과세연도(소득이 없어 제6조 제1항 괄호)"
    return None, "감면사업 소득금액이 0 보다 큰 과세연도가 없고 개시일부터 5년도 지나지 않았습니다"


def compute(inp: Inputs, rules: dict) -> dict:
    v = inp.values
    fs, fe, found = v["과세연도 시작일"], v["과세연도 종료일"], v["창업일"]
    r: dict = {"notes": [], "why": []}
    ys = year_list(inp)
    r["years"] = ys

    # 1. 창업 해당
    deadline = _d(rules, "period", "deadline")
    r["c_deadline"] = found <= deadline
    r["c_sme"] = v["중소기업"] == "Y" and not (v["중소기업 아니게 된 날"] and v["중소기업 아니게 된 날"] <= fe)
    r["c_industry"] = v["업종"] != "그 밖의 업종" and v["업종 단서 제외 업종"] == "N"
    ratio_max = F(str(rules["founding"]["asset_ratio_max"]["value"]))
    succ, asset, spin = v["합병 · 분할 · 현물출자 · 사업양수로 종전 사업 승계"], v["종전 사업 자산 인수 · 매입"], v["사업 분리 임직원 창업"]
    small_asset = asset == "Y" and succ == "N" and F(str(v["인수 자산 비율"])) <= ratio_max
    r["no1"] = (succ == "Y" or asset == "Y") and not (small_asset or spin == "Y")
    r["c_founding"] = not (r["no1"] or v["법인전환"] == "Y" or v["폐업 후 같은 종류 사업 재개"] == "Y" or v["사업 확장 · 업종 추가"] == "Y")
    r["c_started"] = found <= fe

    # 2. 감면기간
    first, why_first = first_income_end(inp, ys, rules)
    r["first_end"], r["first_why"] = first, why_first
    if first:
        r["term_end"] = edate(first + timedelta(days=1), 12 * (rules["period"]["term_years"]["value"] - 1)) - timedelta(days=1)
        r["nth"] = math.floor(F(months_between(first, fe), 12) + F(1, 2)) + 1 if first <= fe else 0   # 엑셀 ROUND(m/12, 0) + 1
        r["c_term"] = first <= fe <= r["term_end"]
    else:
        r["term_end"], r["nth"], r["c_term"] = None, 0, False
    r["eligible"] = all(r[k] for k in ("c_deadline", "c_sme", "c_industry", "c_founding", "c_started", "c_term"))

    # 3. 청년
    yr = rules["youth"]
    birth = v["대표자 생년월일"]
    mil = min(int(v["대표자 병역 개월 수"] or 0), int(yr["military_cap_months"]["value"]))
    if birth:
        r["birth_adj"] = edate(birth, mil)
        r["age"] = years_between(r["birth_adj"], found)
        r["youth"] = yr["age_from"]["value"] <= r["age"] <= yr["age_to"]["value"] and v["대표자 최대주주"] == "Y"
    else:
        r["birth_adj"], r["age"], r["youth"] = None, None, False
    lost = v["청년 요건 상실일"]
    r["youth_lost"] = bool(r["youth"] and lost and lost <= fe)
    r["type"] = "청년상실" if r["youth_lost"] else "청년" if r["youth"] else "일반"

    # 4. 지역 · 시기
    boundary = _d(rules, "rates", "boundary")
    r["era"] = "2025이전" if found <= boundary else "2026이후"
    region = v["창업 지역"]
    moved, moved_on = v["이전 · 지점 지역"], v["이전 · 지점 설치일"]
    r["moved"] = bool(moved and moved_on and moved_on <= fe and region != REGIONS[0])
    r["region"] = moved if r["moved"] else region
    r["key"] = f"{r['era']}|{region_key(r['era'], r['region'])}"
    table = rules["rates"]["value"][r["key"]]

    # 5. 소규모(제6항)
    months = months_between(fs, fe + timedelta(days=1))
    r["fy_months"] = months
    rev = F(v["수입금액"])
    r["revenue_year"] = rev * 12 / months if months < 12 else rev
    small_from = _d(rules, "small", "from")
    r["threshold"] = rules["small"]["threshold_2026" if fs >= small_from else "threshold_2025"]["value"]
    r["small"] = r["type"] == "일반" and r["revenue_year"] <= r["threshold"]

    # 6. 신성장 서비스업(제5항)
    ng_until = date.fromisoformat(rules["new_growth"]["until"])
    r["new_growth"] = (r["type"] == "일반" and not r["small"] and found <= ng_until and r["key"] == "2025이전|과밀외"
                       and v["신성장 서비스업"] == "Y")

    # 7. 감면율
    if r["type"] in ("청년", "청년상실"):
        rate, kind = table[r["type"]], r["type"]
    elif r["small"]:
        rate, kind = table["소규모"], "소규모(제6항)"
    elif r["new_growth"]:
        rate, kind = (0.75 if r["nth"] <= 3 else 0.5), "신성장(제5항)"
    else:
        rate, kind = table["일반"], "일반"
    r["rate_table"] = F(str(rate))
    r["rate"] = r["rate_table"] if r["eligible"] else F(0)
    r["kind"] = kind

    # 8. 고용증가 추가감면(제7항)
    new_from = _d(rules, "employment", "new_from")
    r["emp_new"] = found >= new_from
    r["min_staff"] = rules["industry"]["min_staff"]["value"]["그 밖"] if v["업종"] not in BIG_STAFF else rules["industry"]["min_staff"]["value"][v["업종"]]
    cur, prev = v["상시근로자 수(해당)"], v["상시근로자 수(직전)"]
    if cur is None:
        cur = next((y.staff for y in ys if y.end == fe), None)
    if prev is None:
        prev = next((y.staff for y in ys if y.end == fs - timedelta(days=1)), None)
    # 창업한 과세연도의 직전 과세연도 상시근로자 수는 0(시행령 제5조 제17항 → 제23조 제13항 제1호)
    r["staff_prev_founded"] = prev is None and fs <= found <= fe
    if r["staff_prev_founded"]:
        prev = 0
    r["staff_cur"], r["staff_prev"] = cur, prev
    if r["emp_new"]:
        target = F(0) < r["rate"] < 1
    else:
        target = r["type"] == "일반" and r["key"].endswith("과밀외") and F(0) < r["rate"] < 1
    r["emp_target"] = target
    add = F(0)
    if target and cur is not None and prev is not None:
        base = max(F(str(prev)), F(r["min_staff"]))
        r["staff_base"] = base
        c = F(str(cur))
        if c >= r["min_staff"] and c > base:
            raw = (c - base) / base * (1 if r["emp_new"] else F(1, 2))
            cap = F(1, 4) if r["rate"] == F(3, 4) else F(1, 2)
            add = F(math.floor(min(raw, cap) * 100), 100)
            r["emp_raw"], r["emp_cap"] = raw, cap
    else:
        r["staff_base"] = max(F(str(prev)), F(r["min_staff"])) if prev is not None else None
    r["add_rate"] = add

    # 9. 감면세액
    tax, base_tax, inc = F(v["산출세액"]), F(v["과세표준"]), F(v["감면소득"])
    r["inc_ratio"] = min(F(1), inc / base_tax) if base_tax > 0 and inc > 0 else F(0)
    r["tax_on_income"] = tax * r["inc_ratio"]
    r["base_amt"] = math.floor(r["tax_on_income"] * r["rate"])
    r["add_amt"] = math.floor(r["tax_on_income"] * r["add_rate"])
    full = r["rate"] == 1
    r["o_7"] = (r["base_amt"] if full else 0) + r["add_amt"]          # 11O 최저한세 적용제외
    r["t_7"] = 0 if full else r["base_amt"]                           # 111 최저한세 적용대상

    # 10. 최저한세(111 줄만)
    mt_base = v["최저한세 과세표준"] if v["최저한세 과세표준"] is not None else v["과세표준"]
    r["mt_base"] = mt_base
    r["min_tax"] = math.floor(F(mt_base) * F(str(v["최저한세율"])))
    r["mt_room"] = max(0, v["산출세액"] - r["min_tax"] - v["먼저 적용할 다른 최저한세 대상 감면 · 공제"])
    r["t_8"] = min(r["t_7"], r["mt_room"])
    r["o_8"] = r["o_7"]
    r["mt_cut"] = r["t_7"] - r["t_8"]

    # 11. 5억원 한도(2025년 이후 창업)
    cap = rules["amount"]["cap"]["value"]
    over = max(0, r["o_8"] + r["t_8"] - cap) if r["emp_new"] else 0
    cut_t = min(r["t_8"], over)
    r["t_9"], r["o_9"], r["cap_cut"] = r["t_8"] - cut_t, r["o_8"] - (over - cut_t), over

    # 12. 중복 배제
    r["conflict_employ"] = r["emp_new"] and v["통합고용 · 고용증대 세액공제"] > 0
    r["conflict_127"] = v["제127조 제4항 세액공제"] > 0
    r["conflict_site"] = v["중소기업특별세액감면"] > 0
    r["other_sum"] = ((v["통합고용 · 고용증대 세액공제"] if r["conflict_employ"] else 0) + v["제127조 제4항 세액공제"]
                      + v["중소기업특별세액감면"])
    r["chosen"] = v["적용 선택"] == "창업감면"
    r["o_final"], r["t_final"] = (r["o_9"], r["t_9"]) if r["chosen"] else (0, 0)
    r["total"] = r["o_final"] + r["t_final"]
    r["notes"] = memos(inp, r, rules)
    return r


def memos(inp: Inputs, r: dict, rules: dict) -> list[str]:
    """회계사에게 전할 확인 줄. 판정을 바꾸지 않고 알리기만 한다."""
    v, out = inp.values, []
    reasons = [(r["c_deadline"], "창업일이 2027년 12월 31일 뒤입니다(제6조 제1항)"),
               (r["c_sme"], "중소기업이 아니거나 중소기업이 아니게 된 날이 이 과세연도 안입니다(제6조 제1항 · 제11항)"),
               (r["c_industry"], "감면 업종이 아니거나 각 호 단서의 제외 업종입니다(제6조 제3항)"),
               (r["c_founding"], "창업으로 보지 않는 경우입니다(제6조 제10항): 사업 승계 · 자산 인수(30% 넘음) · 법인전환 · 재개업 · 확장 중 하나"),
               (r["c_started"], "창업일이 과세연도 종료일 뒤입니다"),
               (r["c_term"], f"감면기간이 아닙니다(최초 소득 과세연도 종료일 {r['first_end'] or '없음'}, 감면 끝 {r['term_end'] or '-'})")]
    for ok, text in reasons:
        if not ok:
            out.append(f"감면하지 않음: {text}")
    if r["first_end"]:
        out.append(f"최초 소득 과세연도: {r['first_why']}. 감면 {r['nth']}차 연도, 감면 끝 {r['term_end']}")
    else:
        out.append(f"최초 소득 과세연도를 정하지 못했습니다: {r['first_why']}")
    if not v["대표자 생년월일"]:
        out.append("대표자 생년월일이 없어 청년창업중소기업이 아닌 것으로 계산했습니다. 청년이면 생년월일 · 병역 개월 수 · 최대주주를 넣으십시오")
    elif r["age"] is not None and r["age"] <= 34 and v["대표자 최대주주"] != "Y":
        out.append(f"대표자 창업 당시 나이 {r['age']}세로 연령은 맞지만 최대주주가 아니라고 되어 있어 청년창업으로 보지 않았습니다(시행령 제5조 제1항 제2호)")
    if r["youth_lost"]:
        out.append("청년 요건 상실일이 이 과세연도 안이라 청년상실 감면율을 썼습니다(시행령 제5조 제2항, 상실 기업을 제6항 소규모에서 뺀 것은 엔진 해석)")
    if r["moved"]:
        out.append(f"사업장 이전 · 지점 설치로 「{r['region']}」 에서 창업한 것으로 보았습니다(시행령 제5조 제25항)")
    if r["small"]:
        out.append(f"수입금액(연 환산) {int(r['revenue_year']):,}원이 {r['threshold']:,}원 이하라 제6항 감면율을 썼습니다")
    if r["new_growth"]:
        out.append("신성장 서비스업(제5항): 최초 소득 과세연도를 최초 감면 과세연도로 보고 1 ~ 3차 75%, 4 ~ 5차 50% 로 계산했습니다(회계사 확인 전)")
    if r["eligible"] and r["rate"] == 0:
        out.append(f"감면 요건은 맞지만 이 구분({r['key']} · {r['kind']})의 감면율이 0 입니다")
    if r["emp_target"] and (r["staff_cur"] is None or r["staff_prev"] is None):
        out.append("상시근로자 수(해당 · 직전)가 없어 고용증가 추가감면(제7항)을 계산하지 않았습니다. ctax employ 종전 범위 인원을 넣으십시오")
    if r["add_rate"]:
        out.append(f"고용증가 추가감면율 {float(r['add_rate']) * 100:.0f}%: 상시근로자 해당 {r['staff_cur']} · 기준 {float(r['staff_base']):g}"
                   f"(직전 {r['staff_prev']} 와 업종별최소고용인원 {r['min_staff']} 중 큰 값)" + ("" if r["emp_new"] else ", 종전 규정 × 50/100"))
    if r["emp_target"] and r["staff_prev_founded"]:
        out.append(f"창업한 과세연도라 직전 과세연도 상시근로자 수를 0 으로 보고 업종별최소고용인원 {r['min_staff']}명을 기준으로 썼습니다"
                   "(시행령 제5조 제17항 → 제23조 제13항 제1호). 법인전환 · 사업 승계로 시작했으면 「상시근로자 수(직전)」 에 종전 사업 인원을 넣으십시오")
    if r["eligible"] and r["rate"] == 1 and r["staff_cur"] is not None:
        out.append("100% 감면 과세연도라 고용증가 추가감면(제7항)은 적용하지 않습니다")
    if r["mt_cut"]:
        out.append(f"최저한세로 111 줄 {r['mt_cut']:,}원을 감면하지 않았습니다. 최저한세 여지는 산출세액에서 최저한세와"
                   f" 먼저 적용할 다른 감면 · 공제 {v['먼저 적용할 다른 최저한세 대상 감면 · 공제']:,}원을 뺀 금액입니다. 순서는 납세자가 고릅니다")
    if r["cap_cut"]:
        out.append(f"감면세액이 5억원을 넘어 {r['cap_cut']:,}원을 감면하지 않았습니다(제6조 제13항)")
    if r["conflict_employ"]:
        out.append(f"2025년 이후 창업이라 창업감면을 받으면 통합고용 · 고용증대 세액공제({v['통합고용 · 고용증대 세액공제']:,}원)를 함께 받지 못합니다"
                   "(제127조 제4항 단서). 공제는 이월되고 감면은 이월되지 않으니 회사 사정에 맞게 고르십시오")
    elif v["통합고용 · 고용증대 세액공제"] > 0:
        out.append("2024년 이전 창업이라 통합고용 · 고용증대 세액공제와 창업감면을 함께 받을 수 있습니다(제127조 제4항 단서는 2025년 이후 창업부터)")
    if r["conflict_127"]:
        out.append(f"제127조 제4항 본문 세액공제 {v['제127조 제4항 세액공제']:,}원과 창업감면은 하나만 받습니다")
    if r["conflict_site"]:
        out.append(f"같은 사업장의 중소기업특별세액감면 {v['중소기업특별세액감면']:,}원과 창업감면은 하나만 받습니다(제127조 제5항)")
    if r["other_sum"] and r["chosen"] and r["other_sum"] > r["o_9"] + r["t_9"]:
        out.append(f"중복 배제로 고른 창업감면 {r['o_9'] + r['t_9']:,}원이 함께 받지 못하는 공제감면 {r['other_sum']:,}원보다 작습니다")
    if not r["chosen"]:
        out.append("적용 선택이 「다른 공제감면」 이라 창업감면 신청 금액을 0 으로 두었습니다")
    if v["법인전환"] == "Y" or v["합병 · 분할 · 현물출자 · 사업양수로 종전 사업 승계"] == "Y":
        out.append("법인전환 · 사업 승계로 세운 법인은 새로 창업감면을 받지 못합니다. 개인사업자(또는 중소기업 간 통합으로 소멸한 중소기업)가"
                   " 받던 창업감면의 감면기간이 남았으면, 승계받은 사업에서 생긴 소득에 남은 감면기간 안에 끝나는 과세연도까지 감면받을 수 있습니다"
                   "(제32조 제4항 → 제31조 제4항, 시행령 제28조 제4항). 법인전환은 현물출자 또는 사업 양도양수(시행령 제29조 제2항)로"
                   " 순자산가액 이상 자본금을 갖춰야 합니다(제32조 제1항 · 제2항). 이 스킬은 승계 감면을 계산하지 않습니다")
    if v["사업 분리 임직원 창업"] == "Y" and v["창업일"] >= SPIN_REL_START:
        out.append("2026-02-27 이후 사업을 시작했고 사업 분리 임직원 창업이 Y 입니다. 회사와 그 임직원이 친족관계 · 경영지배관계가"
                   " 아닌지 확인하십시오(시행령 제5조 제21항 제3호). 해당하면 창업으로 보지 않습니다")
    if found_before_2020(v):
        out.append("2019년까지(2020-01-01 전) 창업했습니다. 현행 규정으로 계산했으니 업종 범위 · 제7항이 그때 규정과 다른지 종전 조문을 확인하십시오")
    out.append("이 계산은 창업중소기업(제1항 제1호 · 제5항 ~ 제7항)만 봅니다. 창업보육센터사업자 · 창업벤처 · 에너지신기술중소기업과"
               " 업종 판정(한국표준산업분류), 상시근로자 수, 감면소득 구분경리는 보지 않습니다")
    return out


# 시행령 제5조 제21항 제3호(친족관계 · 경영지배관계 아닐 것)는 2026-02-27 이후 사업 개시분부터(부칙 <제36127호> 제2조)
SPIN_REL_START = date(2026, 2, 27)


def found_before_2020(v: dict) -> bool:
    return v["창업일"] < date(2020, 1, 1)
