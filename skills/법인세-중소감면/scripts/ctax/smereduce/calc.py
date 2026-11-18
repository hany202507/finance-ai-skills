"""중소기업특별세액감면 계산(결정적). 같은 값을 워크북 수식이 따로 계산하고 「4엔진대조」 시트가 견준다.

순서: 감면 대상(중소기업 · 업종 · 일몰) → 소기업(별표 3) · 수도권 → 감면율 → 감면한도(1억원 - 감소 인원 × 5백만원)
→ 감면소득(법인세법 시행령 제96조) → 감면 대상세액(법인세법 제59조 제2항) → 최저한세 → 한도 → 중복 배제 선택
→ 같은 해 통합고용세액공제가 남은 최저한세 여지에서 받는 금액. 근거는 rules.yaml.
"""
from __future__ import annotations

import math
from datetime import date
from fractions import Fraction as F

from .model import NOT_LISTED, Inputs


def _d(x) -> date:
    return date.fromisoformat(str(x))


def F_(x) -> F:
    return F(str(x))


def compute(inp: Inputs, rules: dict) -> dict:
    v = inp.values
    fs, fe = v["과세연도 시작일"], v["과세연도 종료일"]
    r: dict = {}
    ind = rules["industry"]

    # 1. 감면 대상
    r["c_deadline"] = fe <= _d(rules["period"]["deadline"]["value"])
    r["c_sme"] = v["중소기업"] == "Y"
    hydro_ok = not (v["업종"] == ind["hydrogen"]["value"] and fs < _d(ind["hydrogen"]["from"]))
    r["c_industry"] = v["업종"] != NOT_LISTED and v["업종 괄호 제외 업종"] == "N" and hydro_ok
    r["eligible"] = r["c_deadline"] and r["c_sme"] and r["c_industry"]

    # 2. 소기업 · 수도권 · 업종 구분
    table = rules["small"]["table"]["value"]
    row = table[v["별표 3 업종 호"] - 1]
    r["small_name"] = row[1]
    r["table_new"] = fe >= _d(rules["small"]["since"]["value"])           # 과세연도 종료일 현재 시행 표(엔진 규칙)
    r["threshold"] = (v["소기업 규모 기준 직접 입력"] if v["소기업 규모 기준 직접 입력"] is not None
                      else row[3] if r["table_new"] else row[4])
    r["small"] = v["매출액"] <= r["threshold"]
    r["size"] = "소기업" if r["small"] else "중기업"
    r["capital"] = v["본점 수도권"] == "Y" or v["감면 사업장 수도권"] == "Y"
    r["region"] = "수도권" if r["capital"] else "수도권 외"
    publish_from = _d(ind["publish"]["from"])
    if v["업종"] in ind["wholesale"]["value"]:
        r["group"] = "도매업등"
    elif (v["업종"] == "출판업" and v["일반 서적 출판업"] == "Y" and r["size"] == "중기업" and r["capital"]
          and fs >= publish_from):
        r["group"] = "일반 서적 출판업"
    else:
        r["group"] = "그 밖"
    r["key"] = f"{r['size']}|{r['region']}|{r['group']}"

    # 3. 감면율
    base_rate = F_(rules["rates"]["value"][r["key"]])
    r["half"] = v["업종"] == ind["half"]["value"] and r["group"] == "그 밖"
    r["rate_table"] = base_rate * (F(1, 2) if r["half"] else 1)
    r["rate"] = r["rate_table"] if r["eligible"] else F(0)

    # 4. 감면한도
    lim = rules["limit"]
    cur, prev = v["상시근로자 수(해당)"], v["상시근로자 수(직전)"]
    r["staff_cur"], r["staff_prev"] = cur, prev
    if cur is not None and prev is not None:
        r["staff_dec"] = max(F(0), F_(prev) - F_(cur))
    else:
        r["staff_dec"] = F(0)
    r["limit_cut"] = math.floor(r["staff_dec"] * lim["per_worker"]["value"])
    r["limit"] = max(0, lim["base"]["value"] - r["limit_cut"])

    # 5. 감면소득(법인세법 시행령 제96조)
    inc_all = v["각 사업연도 소득금액"]
    r["biz_income"] = max(0, inc_all - v["감면 제외 소득"])
    ded, src = v["이월결손금 · 비과세 · 소득공제"], v["공제액등이 생긴 사업"]
    if src == "감면사업":
        r["ded_share"] = ded
    elif src == "그 밖의 사업" or inc_all <= 0:
        r["ded_share"] = 0
    else:
        r["ded_share"] = math.floor(F(ded) * F(r["biz_income"]) / F(inc_all))
    r["reduced_income"] = max(0, r["biz_income"] - r["ded_share"])

    # 6. 감면 대상세액(법인세법 제59조 제2항)
    tax, base = v["산출세액"], v["과세표준"]
    r["inc_ratio"] = min(F(1), F(r["reduced_income"]) / F(base)) if base > 0 and r["reduced_income"] > 0 else F(0)
    r["tax_on_income"] = F(tax) * r["inc_ratio"]
    r["a7"] = math.floor(r["tax_on_income"] * r["rate"])            # ⑦ 대상세액(최저한세 전)

    # 7. 최저한세(112 줄은 적용대상)
    mt_base = v["최저한세 과세표준"] if v["최저한세 과세표준"] is not None else base
    r["mt_base"] = mt_base
    r["min_tax"] = math.floor(F(mt_base) * F_(v["최저한세율"]))
    r["mt_room"] = max(0, tax - r["min_tax"] - v["먼저 적용할 다른 최저한세 대상 감면 · 공제"])
    r["a8"] = min(r["a7"], r["mt_room"])                            # ⑧ 최저한세 반영
    r["mt_cut"] = r["a7"] - r["a8"]
    r["a9"] = min(r["a8"], r["limit"])                              # ⑨ 한도충족
    r["limit_over"] = r["a8"] - r["a9"]

    # 8. 중복 배제(제127조 제4항 본문 · 제5항)
    r["conflict_127"] = v["제127조 제4항 세액공제"] > 0
    r["conflict_site"] = v["같은 사업장 다른 감면"] > 0
    r["other_sum"] = v["제127조 제4항 세액공제"] + v["같은 사업장 다른 감면"]
    r["chosen"] = v["적용 선택"] == CHOICE_SELF
    r["total"] = r["a9"] if r["chosen"] else 0

    # 9. 같은 해 통합고용세액공제(제127조 제4항이 막지 않음): 감면 뒤 남은 최저한세 여지에서
    emp = v["통합고용 세액공제"]
    r["emp_room"] = max(0, r["mt_room"] - (r["total"] if r["chosen"] else r["other_sum"]))   # 고른 쪽이 여지를 먼저 씀
    r["emp_now"] = min(emp, r["emp_room"])
    r["emp_carry"] = emp - r["emp_now"]
    r["notes"] = memos(inp, r, rules)
    return r


CHOICE_SELF = "중소기업특별세액감면"


def memos(inp: Inputs, r: dict, rules: dict) -> list[str]:
    """회계사에게 전할 확인 줄. 판정을 바꾸지 않고 알리기만 한다."""
    v, out = inp.values, []
    fs, fe = v["과세연도 시작일"], v["과세연도 종료일"]
    if not r["c_deadline"]:
        out.append(f"감면하지 않음: 과세연도 종료일 {fe} 가 일몰({rules['period']['deadline']['value']}) 뒤입니다(제7조 제1항)")
    if not r["c_sme"]:
        out.append("감면하지 않음: 중소기업이 아닙니다(제7조 제1항)")
    if not r["c_industry"]:
        if v["업종"] == rules["industry"]["hydrogen"]["value"] and fs < _d(rules["industry"]["hydrogen"]["from"]):
            out.append("감면하지 않음: 수소발전사업은 2025년 12월 개정으로 들어온 업종이라 2026년 이후 개시 과세연도로 보았습니다(부칙 확인 전)")
        else:
            out.append("감면하지 않음: 감면 업종이 아니거나 각 목 괄호의 제외 업종입니다(제7조 제1항 제1호)")
    since = rules["small"]["since"]["value"]
    table = "2025-09-01 개정 표" if r["table_new"] else "옛 표(2025-08-31 까지 시행)"
    out.append(f"소기업 판정: 매출액 {v['매출액']:,}원 · 별표 3 제{v['별표 3 업종 호']}호({r['small_name']}) 기준 {r['threshold']:,}원({table}) → {r['size']}"
               "(업종 번호는 한국표준산업분류로 회계사가 고른 값입니다)")
    row = rules["small"]["table"]["value"][v["별표 3 업종 호"] - 1]
    if fs < _d(since) <= fe and row[3] != row[4] and v["소기업 규모 기준 직접 입력"] is None:
        out.append(f"별표 3 이 과세연도 중({since}) 바뀌었습니다. 과세연도 종료일 현재 시행 표를 썼고, 옛 표 기준은 {row[4]:,}원입니다"
                   "(시행령 제6조 제4항, 엔진 규칙, 회계사 확인 전)")
    months = (fe.year - fs.year) * 12 + fe.month - fs.month + 1
    if months < 12:
        out.append(f"과세연도가 {months}개월입니다. 소기업 판정 매출액을 연으로 환산하지 않았습니다(시행령 제6조 제4항에 환산 규정 없음, 회계사 확인 전)")
    if v["본점 수도권"] == "Y" and v["감면 사업장 수도권"] == "N":
        out.append("본점이 수도권이라 감면 사업장이 수도권 밖이어도 수도권 감면율을 썼습니다(제7조 제1항 단서)")
    if r["eligible"] and r["rate"] == 0:
        out.append(f"감면 요건은 맞지만 이 구분({r['key']})의 감면율이 0 입니다. 중기업이 수도권에서 경영하는 사업장은 2025년 이후 개시 과세연도부터 "
                   "일반 서적 출판업만 감면하고, 2023 ~ 2024년 개시 과세연도에는 감면하지 않습니다(제7조 제1항 제2호 마목, 부칙 <제20778호> 제2조)")
    if v["업종"] == "출판업" and v["일반 서적 출판업"] == "Y" and r["group"] != "일반 서적 출판업" and r["size"] == "중기업" and r["capital"]:
        out.append("일반 서적 출판업 10%(마목)는 2025년 1월 1일 이후 개시 과세연도부터라 이 과세연도에는 쓰지 않았습니다(부칙 <제20778호> 제2조)")
    if r["half"]:
        out.append("통관 대리 및 관련 서비스업이라 감면 비율에 100분의 50을 곱했습니다(제7조 제1항 제2호 단서)")
    if r["staff_cur"] is None or r["staff_prev"] is None:
        out.append("상시근로자 수(해당 · 직전)가 없어 감면한도를 1억원으로 두었습니다. 인원이 줄었으면 한도가 줄어드니 ctax employ 종전 범위 인원을 넣으십시오")
    else:
        out.append(f"상시근로자 수 해당 {r['staff_cur']:g} · 직전 {r['staff_prev']:g}({inp.staff_from}), 감면한도 {r['limit']:,}원")
    if r["staff_dec"]:
        out.append(f"상시근로자가 {float(r['staff_dec']):g}명 줄어 한도에서 {r['limit_cut']:,}원을 뺐습니다(제7조 제1항 제3호 가목, 소수 인원을 그대로 곱함은 엔진 규칙)")
    if v["이월결손금 · 비과세 · 소득공제"] and v["공제액등이 생긴 사업"] == "불분명":
        out.append(f"공제액등 {v['이월결손금 · 비과세 · 소득공제']:,}원을 소득금액 비례로 안분해 감면소득에서 {r['ded_share']:,}원을 뺐습니다"
                   "(법인세법 시행령 제96조 제2호). 감면사업에서 생긴 결손금이면 「공제액등이 생긴 사업」 을 감면사업으로 고치십시오")
    if v["감면 제외 소득"] == 0 and r["eligible"]:
        out.append("감면 제외 소득이 0 입니다. 영업외 이자 · 배당 · 임대료 · 처분손익이나 감면 업종이 아닌 사업 소득이 있으면 넣으십시오")
    if r["mt_cut"]:
        out.append(f"최저한세로 {r['mt_cut']:,}원을 감면하지 않았습니다(제132조 제1항 제4호). 감면은 이월되지 않습니다")
    if float(v["최저한세율"]) > 0.0700001:
        out.append(f"최저한세율을 {float(v['최저한세율']) * 100:g}% 로 넣었습니다. 중소기업은 유예기간 중에도 7% 입니다(시행령 제2조 제2항)."
                   " 8 · 9%(제132조 제1항 괄호)는 유예기간이 지나 중소기업이 아니게 된 뒤의 율이라 이 감면과 함께 쓰지 않습니다")
    if r["limit_over"]:
        out.append(f"감면한도를 넘어 {r['limit_over']:,}원을 감면하지 않았습니다(제7조 제1항 제3호)")
    if v["통합고용 세액공제"]:
        out.append(f"통합고용 세액공제 {v['통합고용 세액공제']:,}원은 함께 받습니다(제127조 제4항이 막지 않음). 감면 뒤 남은 최저한세 여지에서"
                   f" {r['emp_now']:,}원을 공제하고 {r['emp_carry']:,}원은 이월합니다(제144조, 공제 순서는 납세자가 고름)")
        if not r["chosen"] and r["other_sum"]:
            out.append(f"고른 다른 공제감면 {r['other_sum']:,}원이 최저한세 여지를 먼저 쓴다고 보고 통합고용 공제를 계산했습니다. 그 공제감면이"
                       " 최저한세 적용제외이거나 순서를 달리 고르면 「먼저 적용할 다른 최저한세 대상 감면 · 공제」 로 맞추십시오")
    if r["conflict_127"]:
        out.append(f"제127조 제4항 본문 세액공제(통합투자 등) {v['제127조 제4항 세액공제']:,}원과 중소기업특별세액감면은 하나만 받습니다."
                   " 구분경리하고 그 공제가 감면 사업이 아닌 사업에 걸리면 중복이 아닙니다(제127조 제10항)")
    if r["conflict_site"]:
        out.append(f"같은 사업장의 다른 감면(창업중소기업 감면 등) {v['같은 사업장 다른 감면']:,}원과 중소기업특별세액감면은 하나만 받습니다"
                   "(제127조 제5항). 창업감면 기간(5개 과세연도)이 끝난 뒤에는 중소기업특별세액감면을 받을 수 있습니다")
    if r["other_sum"] and r["chosen"] and r["other_sum"] > r["a9"]:
        out.append(f"고른 중소기업특별세액감면 {r['a9']:,}원이 함께 받지 못하는 공제감면 {r['other_sum']:,}원보다 작습니다."
                   " 세액공제는 이월되고 감면은 이월되지 않으니 회사 사정에 맞게 고르십시오")
    if not r["chosen"]:
        out.append("적용 선택이 「다른 공제감면」 이라 중소기업특별세액감면 신청 금액을 0 으로 두었습니다")
    out.append("이 계산은 법인의 제7조 제1항만 봅니다. 제2항(110%, 개인사업자 요건) · 제3항(알뜰주유소), 사업장이 여러 곳이고 감면율이 다른 경우의"
               " 합산, 업종 · 별표 3 호 판정(한국표준산업분류)과 상시근로자 수 계산, 감면 제외 소득의 구분은 엔진이 보지 않습니다")
    return out
