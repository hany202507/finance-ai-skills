"""중소기업특별세액감면 계산(결정적). 같은 값을 워크북 수식이 따로 계산하고 「4엔진대조」 시트가 견준다.

순서: 감면 대상(중소기업 · 업종 · 일몰) → 소기업(별표 3, 창업 · 분할 · 합병 과세연도는 연 환산) · 수도권 → 감면율
→ 감면한도(1억원 - 감소 인원 × 5백만원) → 감면소득(법인세법 시행령 제96조) → 감면 대상세액(법인세법 제59조 제2항)
→ 최저한세 → 한도 → 중복 배제 선택
→ 같은 해 통합고용세액공제가 남은 최저한세 여지에서 받는 금액. 근거는 rules.yaml.
"""
from __future__ import annotations

import math
from datetime import date
from fractions import Fraction as F

from .model import EXCLUDED, NOT_LISTED, STARTUP_YEAR, Inputs, months


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
    en = ind["energy"]
    r["energy_old_out"] = v["업종"] == en["old"] and fs >= _d(en["from"])      # 2026-09-18 판부터 누목이 재생에너지로 바뀜
    r["c_industry"] = v["업종"] != NOT_LISTED and v[EXCLUDED] == "N" and not r["energy_old_out"]
    r["eligible"] = r["c_deadline"] and r["c_sme"] and r["c_industry"]

    # 2. 소기업 · 수도권 · 업종 구분
    table = rules["small"]["table"]["value"]
    row = table[v["별표 3 업종 호"] - 1]
    r["small_name"] = row[1]
    r["table_new"] = fe >= _d(rules["small"]["since"]["value"])           # 과세연도 종료일 현재 시행 표(엔진 규칙)
    r["threshold"] = (v["소기업 규모 기준 직접 입력"] if v["소기업 규모 기준 직접 입력"] is not None
                      else row[3] if r["table_new"] else row[4])
    r["months"] = months(fs, fe)
    r["annualize"] = v[STARTUP_YEAR] == "Y" and r["months"] < 12             # 시행규칙 제5조 · 제2조 제4항 단서
    r["sales_used"] = F(v["매출액"]) * 12 / r["months"] if r["annualize"] else F(v["매출액"])
    r["small"] = r["sales_used"] <= r["threshold"]
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
        r["ded_share"] = min(ded, math.floor(F(ded) * F(r["biz_income"]) / F(inc_all)))   # 공제액등을 넘지 않는다
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
    r["a8"] = min(r["a7"], r["mt_room"])                            # ⑧ 서식: ⑦ - 최저한세 배제세액(⑨ = min(⑧, 한도)가 맞게)
    r["a9"] = min(r["a8"], r["limit"])                              # ⑨ 한도충족
    r["a7_lim"] = min(r["a7"], r["limit"])                          # ⑦ 중 감면한도까지
    r["limit_over"] = r["a7"] - r["a7_lim"]                         # 한도로 감면하지 않은 금액
    r["mt_cut"] = r["a7_lim"] - r["a9"]                             # 최저한세로 감면하지 않은 금액(한도까지의 금액 기준)

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
    en = rules["industry"]["energy"]
    en_from = _d(en["from"])
    if not r["c_industry"]:
        if r["energy_old_out"]:
            out.append(f"감면하지 않음: {en['from']} 이후 개시 과세연도에는 누목이 「재생에너지 발전사업」 으로 바뀌어 「{en['old']}」 은 감면 업종이"
                       f" 아닙니다. 재생에너지 발전이면 「{en['renew']}」, 수소발전이면 「{en['hydrogen']}」 을 고르십시오. 석탄 액화 · 가스화 같은"
                       " 그 밖의 신에너지 발전은 목록에서 빠졌습니다(제7조 제1항 제1호 누목 · 두목, 부칙 <법률 제21467호> 제8조)")
        else:
            out.append("감면하지 않음: 감면 업종이 아니거나 각 목 괄호의 제외 업종 · 한정 요건 미충족입니다(제7조 제1항 제1호)")
    if v["업종"] in (en["old"], en["renew"], en["hydrogen"]):
        if fs < en_from <= fe:
            out.append(f"과세연도 중({en['from']}) 누목이 신 · 재생에너지 발전사업에서 재생에너지 발전사업으로 바뀌고 두목 수소발전사업이"
                       " 들어왔습니다. 부칙 <법률 제21467호> 에 조특법 적용례가 없어 과세연도 시작일 현재 업종 목록으로 가렸습니다"
                       "(엔진 규칙, 회계사 확인 전). 종료일 현재 목록을 쓰면 수소 · 재생에너지가 아닌 신에너지 발전은 감면 업종이 아닙니다")
        elif fs < en_from and v["업종"] != en["old"]:
            out.append(f"과세연도 시작일이 {en['from']} 앞이라 이 업종은 그때 누목 「신 · 재생에너지 발전사업」(신에너지 및 재생에너지 개발 · 이용 · 보급"
                       " 촉진법, 신에너지에 수소에너지 · 연료전지 포함)으로 감면합니다. 신청서 근거는 그 판의 누목입니다")
    if v["업종"] == "의료기관 운영(의료업)":
        out.append("의료업 중 의원 · 치과의원 · 한의원은 요양급여비용 비율 100분의 80 이상 등 한정 요건이 있습니다(제7조 제1항 제1호 허목)."
                   f" 요건을 채우지 못하면 「{EXCLUDED}」 를 Y 로 두십시오")
    since = rules["small"]["since"]["value"]
    table = "2025-09-01 개정 표" if r["table_new"] else "옛 표(2025-08-31 까지 시행)"
    sales = f"연 환산 매출액 {math.floor(r['sales_used']):,}원" if r["annualize"] else f"매출액 {v['매출액']:,}원"
    out.append(f"소기업 판정: {sales} · 별표 3 제{v['별표 3 업종 호']}호({r['small_name']}) 기준 {r['threshold']:,}원({table}) → {r['size']}"
               "(업종 번호는 한국표준산업분류로 회계사가 고른 값입니다)")
    row = rules["small"]["table"]["value"][v["별표 3 업종 호"] - 1]
    if fs < _d(since) <= fe and row[3] != row[4] and v["소기업 규모 기준 직접 입력"] is None:
        out.append(f"별표 3 이 과세연도 중({since}) 바뀌었습니다. 과세연도 종료일 현재 시행 표를 썼고, 옛 표 기준은 {row[4]:,}원입니다"
                   "(시행령 제6조 제4항, 엔진 규칙, 회계사 확인 전)")
    if r["annualize"]:
        out.append(f"창업 · 분할 · 합병 과세연도가 {r['months']}개월이라 매출액을 연으로 환산했습니다: {v['매출액']:,} × 12 ÷ {r['months']}"
                   f" = {math.floor(r['sales_used']):,}원(시행규칙 제5조 · 제2조 제4항 단서). 개월 수는 1개월 미만을 1개월로 센 엔진 규칙입니다")
    elif r["months"] < 12:
        out.append(f"과세연도가 {r['months']}개월인데 「{STARTUP_YEAR}」 가 N 이라 매출액을 연으로 환산하지 않았습니다. 시행규칙 제2조 제4항 단서는"
                   " 창업 · 분할 · 합병 과세연도만 환산합니다. 사업연도 변경 · 법인 전환 첫 과세연도를 환산한 해석(법인세과-641, 서면법규과-568)이"
                   f" 있으니 해당하면 「{STARTUP_YEAR}」 를 Y 로 두고 회계사가 확인하십시오")
    if v["본점 수도권"] == "Y" and v["감면 사업장 수도권"] == "N":
        out.append("본점이 수도권이라 감면 사업장이 수도권 외 지역이어도 수도권 감면율을 썼습니다(제7조 제1항 단서)")
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
        out.append(f"상시근로자가 {float(r['staff_dec']):g}명 줄어 한도에서 {r['limit_cut']:,}원을 뺐습니다(제7조 제1항 제3호 가목, 서식 4쪽 ❺"
                   " 「1억원 - 500만원 × 상시근로자 수 감소인원」, 소수 인원을 그대로 곱함은 엔진 규칙). 신청서 4쪽 ❺ 감면한도계산은 이 스킬이"
                   " 채우지 않으니 사람이 적습니다")
    if v["이월결손금 · 비과세 · 소득공제"] and v["공제액등이 생긴 사업"] == "불분명":
        out.append(f"공제액등 {v['이월결손금 · 비과세 · 소득공제']:,}원을 소득금액 비례로 안분해 감면소득에서 {r['ded_share']:,}원을 뺐습니다"
                   "(법인세법 시행령 제96조 제2호). 감면사업에서 생긴 결손금이면 「공제액등이 생긴 사업」 을 감면사업으로 고치십시오")
    if v["감면 제외 소득"] < 0:
        out.append(f"감면 제외 소득이 음수({v['감면 제외 소득']:,}원)라 감면사업 소득 {r['biz_income']:,}원이 각 사업연도 소득금액보다 큽니다."
                   " 공제액등 안분액은 공제액등 전액을 넘지 않게 잘랐습니다(법인세법 시행령 제96조 제2호). 감면 업종이 아닌 사업의 결손을"
                   " 감면소득 계산에 어떻게 반영할지는 회계사 확인 전입니다")
    exp_base = max(0, v["각 사업연도 소득금액"] - v["이월결손금 · 비과세 · 소득공제"])
    if v["과세표준"] != exp_base:
        out.append(f"과세표준 {v['과세표준']:,}원이 각 사업연도 소득금액 - 이월결손금 · 비과세 · 소득공제 {exp_base:,}원과 다릅니다."
                   " 3호 서식 값을 다시 보십시오(감면소득 비율의 분모가 과세표준입니다)")
    if v["감면 제외 소득"] == 0 and r["eligible"]:
        out.append("감면 제외 소득이 0 입니다. 영업외 이자 · 배당 · 임대료 · 처분손익이나 감면 업종이 아닌 사업 소득이 있으면 넣으십시오")
    if r["mt_cut"]:
        out.append(f"최저한세로 {r['mt_cut']:,}원을 감면하지 않았습니다(제132조 제1항 제4호, 감면한도까지의 금액 기준). 감면은 이월되지 않습니다")
    if r["limit_over"]:
        out.append(f"감면한도를 넘어 {r['limit_over']:,}원을 감면하지 않았습니다(제7조 제1항 제3호)")
    if r["a7"] > r["limit"] and r["a7"] > r["mt_room"]:
        out.append(f"⑦ {r['a7']:,}원이 감면한도 {r['limit']:,}원과 최저한세 여지 {r['mt_room']:,}원을 함께 넘습니다. 서식 ⑧ 에는 ⑨ = min(⑧, 한도)가"
                   f" 실제 감면세액과 같도록 ⑦ 과 최저한세 여지 중 적은 {r['a8']:,}원을 넣었습니다. 작성방법 4 는 배제세액을 한도 적용 전후 어느"
                   " 금액으로 셀지 정하지 않아 ⑧ 값은 회계사 확인 전입니다")
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
               " 합산, 한 사업장에서 감면율이 다른 업종을 함께 경영할 때의 소득 구분, 업종 · 별표 3 호 판정(한국표준산업분류)과 상시근로자 수"
               " 계산, 감면 제외 소득의 구분, 제128조 제2항 ~ 제4항의 감면 배제(결정 · 기한 후 신고, 경정을 미리 알고 낸 수정신고의 과소신고금액,"
               " 현금영수증가맹점 미가입 · 신용카드 · 현금영수증 발급 거부나 사실과 다른 발급)는 엔진이 보지 않습니다")
    return out
