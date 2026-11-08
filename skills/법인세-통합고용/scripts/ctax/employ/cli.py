"""`python -m ctax employ <신고 건 폴더>`: 급여대장 · 사원명부로 통합고용세액공제 검증 워크북을 만든다.

읽는 것  00 받은자료/급여/통합고용_입력.xlsx (`--template` 빈 양식, `--sample` 시험용 스무 명, `--input` 다른 파일)
쓰는 것  2 조서/통합고용_검증.xlsx, 2 조서/통합고용_법정서식.pdf(법제처 서식 원본 위에 값), _색인/통합고용.json, 신고건.json 의 「상시근로자」(ctax wp 가 읽는다)
끝 코드  0 검산 모두 통과, 1 확인할 검산이 있음 또는 사원명부 범위 미확인(잠정치), 2 입력 없음
"""
from __future__ import annotations

import argparse
from pathlib import Path

from openpyxl import Workbook, load_workbook

from .. import xlsx as X
from ..case import WP_DIR, Case, MissingInput, won
from . import book, lawform
from .calc import REASONS, compute, hours_for, month_end
from .model import (COMPANY_ROWS, INPUT_DIR, INPUT_NAME, PAY_COLS, PERIODS, STAFF_COLS, InputError, Inputs, load_data,
                    load_rules, read_inputs)

OUT_XLSX = "통합고용_검증.xlsx"
OUT_JSON = "통합고용.json"
INFO_KEY = "상시근로자"
SOURCE = "ctax employ"
RATES = Path(__file__).resolve().parents[1] / "wp" / "rates_2025" / "credits.yaml"


def load_rates() -> dict:
    return load_data(RATES)


def f2(x) -> float:
    return round(float(x), 2)


# ---------------------------------------------------------------- 빈 양식

def write_template(path: Path, case: Case) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "회사"
    row = X.title(ws, "회사", "값 열(노란 칸)만 채웁니다. 비워 두면 설명에 적힌 기본값을 씁니다")
    X.header(ws, row, ["항목", "값", "설명"])
    info = case.info()
    preset = {"fy_start": info.get("fy_start"), "fy_end": info.get("fy_end"), "size": "중소기업", "capital": "Y",
              "consumer": "N", "startup": "N"}
    for i, (label, attr, _, text) in enumerate(COMPANY_ROWS, start=1):
        X.cell(ws, row + i, 1, label)
        X.cell(ws, row + i, 2, preset.get(attr), kind="input")
        X.cell(ws, row + i, 3, text).font = X.NOTE_FONT
    X.widths(ws, [34, 16, 90])
    for name, cols in (("사원명부", STAFF_COLS), ("급여대장", PAY_COLS)):
        ws = wb.create_sheet(name)
        X.header(ws, 1, [c[0] for c in cols])
        for j in range(1, len(cols) + 1):
            X.cell(ws, 2, j, None, kind="input")
        X.widths(ws, [14] * len(cols))
    ws = wb.create_sheet("정의")
    row = X.title(ws, "원천 데이터 정의", "필수 열이 비면 엔진이 멈춥니다. Y · N 열을 비우면 N(내국인은 Y)으로 봅니다")
    X.header(ws, row, ["시트", "열", "필수", "설명"])
    for name, cols in (("사원명부", STAFF_COLS), ("급여대장", PAY_COLS)):
        for label, _, _, need, text in cols:
            row += 1
            for j, v in enumerate((name, label, "필수" if need else "", text), start=1):
                X.cell(ws, row, j, v)
    X.widths(ws, [12, 20, 8, 90])
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


# ---------------------------------------------------------------- 사원명부 범위 확인

DIRECT_STAMP = "잠정 · 사원명부 없이 인원 숫자로 계산"


def direct_pending(inp: Inputs) -> list[str]:
    """사원명부 없이 회사 시트 직접 입력 인원으로 계산했으면 잠정치라고 알린다(rules.yaml count.direct_input)."""
    if inp.staff or not inp.company.direct_given:
        return []
    return ["잠정: 사원명부 없이 인원 숫자로 계산했습니다. 회사 시트 「인원 직접 입력」 인원을 그대로 썼고, 상시근로자 범위 · 청년등 구분 · "
            "근무개월 수는 엔진이 보지 않았습니다. 상시근로자 명세서(별지 제10호의10서식)는 비웠습니다. 세액공제를 신청하려면 명세서를 내야 하므로"
            "(시행령 제26조의8 제11항) 사원명부와 급여대장을 넣어 다시 돌리십시오"]


def scope_pending(inp: Inputs) -> list[str]:
    """상시근로자 범위를 정하는 열(임원 · 최대주주·친족 · 계약 1년 미만 · 0.75 요건)은 급여대장에서 알 수 없다.
    빈칸은 「아니오」 로 읽히므로, 회사 시트 「사원명부 범위 확인」 이 Y 가 아니면 사람 이름과 함께 잠정치라고 알린다."""
    if inp.company.scope == "Y" or not inp.staff:
        return direct_pending(inp)
    st = inp.staff
    short = [p for p in st if p.kind in ("기간제", "파견") and p.short != "Y"]
    part = [p for p in st if p.kind == "단시간" and (p.hours or 0) >= 60 and p.supported != "Y"]
    names = lambda ps: ", ".join(p.name for p in ps[:8]) + (f" 외 {len(ps) - 8}명" if len(ps) > 8 else "")  # noqa: E731
    out = ["잠정치입니다: 회사 시트 「사원명부 범위 확인」 이 Y 가 아닙니다. 임원 · 최대주주·친족 · 계약 1년 미만 · 0.75 요건은 "
           "급여대장으로 알 수 없고, 사원명부에서 비운 칸은 「아니오」 로 셌습니다. 근로계약서 · 등기부 · 주주명부로 확인해 사원명부에 적고 "
           "「사원명부 범위 확인」 을 Y 로 바꾼 뒤 다시 돌리십시오(옛 양식이라 회사 시트에 그 항목이 없으면 항목 · 값 한 줄을 덧붙입니다)"]
    off, own = sum(p.officer == "Y" for p in st), sum(p.owner == "Y" for p in st)
    out.append(f"임원 {off}명 · 최대주주·친족 {own}명으로 적혀 있습니다(사원명부 {len(st)}명). 이 열이 원본에 없었다면 임원과 최대주주·친족은 "
               "상시근로자에서 빠지므로 인원과 공제액이 줄어듭니다")
    if short:
        out.append(f"기간제 · 파견 {len(short)}명이 계약 1년 미만이 아닌 것으로 되어 있습니다: {names(short)}. 계약기간이 1년 미만이면 상시근로자가 아닙니다")
    if part:
        out.append(f"1개월 소정근로시간 60시간 이상인 단시간근로자 {len(part)}명을 0.5명으로 셌습니다: {names(part)}. 0.75 요건을 채우면 0.75명입니다")
    return out


# ---------------------------------------------------------------- 확인할 것

def memos(inp: Inputs, res: dict, rules: dict) -> list[str]:
    co, out = inp.company, list(inp.notes)
    cur, counts = res["periods"]["해당"], res["counts"]
    names = lambda rows, n=8: ", ".join(r.person.name for r in rows[:n]) + (f" 외 {len(rows) - n}명" if len(rows) > n else "")  # noqa: E731
    if co.consumer == "Y":
        out.append("소비성서비스업이라 공제 대상이 아닙니다(조세특례제한법 제29조의8 제1항 괄호). 공제액을 0 으로 두었습니다")
    if res["regime"] == "2026" and not res["unsupported"]:
        out.append("2026년 12월 31일이 속하는 과세연도부터는 공제가 기존공제(2024 · 2025 과세연도 증가분의 2 · 3차 연도, 종전 규정)와 "
                   "신규공제(직전 3개 과세연도 대비 새 산식, 법 제29조의8 제1항)로 나뉩니다. 신규공제는 5공제액 시트 「마」 에서 직전 · 전전 대비를 계산했고 "
                   "전전전 대비는 2027 과세연도까지 해당이 없습니다. 6서식10의9 시트는 별지 제10호의9서식(2) 모양이고 신규공제와 추가공제를 적습니다. 기존공제는 종전 규정으로 신청하므로 종전 서식(1)(6-1 시트)에 적습니다 "
                   "(시행규칙 부칙 제23호 제6조: 개정 서식으로 종전 규정의 공제를 신청할 수 없으면 종전 서식). 합계(8호(갑) 18S)는 둘을 더합니다. 기존공제 2차 연도 인원은 최초 공제연도가 2025 과세연도라 근로자별, 3차 연도는 2024 과세연도라 월말 합 방식입니다(시행령 부칙 제36127호 제11조 제1항)")
    elif res["unsupported"]:
        out.append(res["unsupported"])
    if res["new_scope"] and not res["unsupported"]:
        out.append("2026 과세연도부터 신규공제 · 추가공제 인원은 새 범위(시행령 제26조의8 제2항, 대통령령 제35999호 2026-01-01 시행)로 셉니다. "
                   "근로기간 1년이 된 달부터 근무개월 수에 넣고(월말 현재 근로기간 1년 이상인 달, 입사일로 소급하지 않음), 단시간근로자는 "
                   "해당 과세연도 월 평균 근로시간(총 근로시간 ÷ 근무개월 수) 60시간으로 가립니다. 비교하는 직전 과세연도 인원도 새 범위로 "
                   "다시 셉니다. 기존공제(2024 · 2025 과세연도 증가분의 2 · 3차 연도) 판정은 종전 범위입니다(부칙 <대통령령 제35999호> 제2조). "
                   "근로기간 기준과 비교 연도 재산정은 2026-11-02 대표 결정이고 이정아 회계사 확인 전입니다(rules.yaml scope.service_year · prior_recount). "
                   "두 범위의 인원은 4인원 시트에 함께 있습니다")
        for per in ("해당", "직전"):
            c_new = res["counts_new"][per]
            if per != "해당" and not c_new.period.has_payroll:
                continue
            cut = [r for r in c_new.rows if sum(r.worked) < sum(r.employed) and (r.regular or r.reason == REASONS["a_new"])]
            if cut:
                out.append(f"{per} 과세연도 새 범위에서 근로기간 1년이 되기 전 달을 뺀 사람 {len(cut)}명: {names(cut)}")
            part = [r for r in c_new.rows if r.person.kind == "단시간" and any(r.employed)
                    and hours_for(r.person, per, "새")[1]]
            if part:
                col = "월 평균 근로시간" if per == "해당" else "직전 월 평균 근로시간"
                out.append(f"{per} 과세연도 새 범위 단시간근로자 판정에 월 평균 근로시간이 없어 월 소정근로시간을 대신 쓴 사람: {names(part)}. "
                           f"그해 총 근로시간 ÷ 근무개월 수를 사원명부 「{col}」 에 적으십시오(시행령 제26조의8 제2항 제2호)")
        prev = res["counts"]["직전"].rows + res["counts_new"]["직전"].rows       # 종전 범위(기존공제 판정) · 새 범위
        if res["periods"]["직전"].deemed and res["periods"]["직전"].has_payroll and any(
                r.regular and r.youth_age != r.youth_deem for r in prev):
            out.append("직전 과세연도 인원에도 2025년 중 계약한 사람의 청년 간주(3년, 중소 · 중견 아니면 2년)를 넣었습니다. 명세서 작성방법 25 괄호"
                       "(「간주 개정규정은 미적용」)는 2024년 이전 계약자에 대한 말로 읽었습니다(2026-11-02 대표 결정, 사전-2026-법규법인-0729)")
    if res["sum_floor"]:
        out.append("인원은 사람별 계산한 수를 버리지 않고 더한 뒤 100분의 1 미만을 버렸습니다(시행령 제11조의2 제8항, 대통령령 제36342호 2026. 5. 22. 개정, "
                   "부칙 제2조 제2항: 2026년 1월 1일 이후 개시 과세연도 신고부터). 명세서의 사람별 계산한 수는 버리지 않은 값입니다")
    if res["method"] == "근로자별":
        out.append("1차 연도 인원은 근로자별 방식(사람마다 근무개월 수 ÷ 과세연도 개월 수, "
                   + ("합에서 100분의 1 미만 버림" if res["sum_floor"] else "100분의 1 미만 버림") + ")으로 셌습니다"
                   "(시행령 제26조의8 제6항 · 제11조의2 제8항, 부칙 <대통령령 제36127호> 제11조 제1항). 2024 과세연도 이전 증가분의 2 · 3차 연도 판정은 "
                   "월말 합 방식(종전 규정)입니다. 두 방식의 인원은 4인원 시트에 함께 있습니다")
    for per in ("직전", "직전전"):
        src = res["source"][per]
        if src == "전기 신고서":
            out.append(f"{per} 과세연도 급여대장이 없어 전기 신고서의 인원(0기준 노란 칸)을 썼습니다. 계산 방식 · 청년 범위가 "
                       "당기와 같은지 확인하십시오"
                       + (". 신규공제 비교에도 이 인원(종전 범위)을 썼습니다. 새 범위(근로기간 1년)로 다시 세려면 그 과세연도 급여대장을 "
                          "넣으십시오" if res["new_scope"] and res["periods"][per].start.year >= 2025 else ""))
        elif src == "없음" and (per == "직전" or co.first_prev2_youth or co.first_prev2_other):
            out.append(f"{per} 과세연도 인원이 없습니다(급여대장도 전기 신고 인원도 없음). 그 인원이 필요한 공제는 계산하지 않았습니다")
    for per in PERIODS:
        if res["source"][per] == "직접 입력":
            out.append(f"{per} 과세연도 인원은 회사 시트 「인원 직접 입력」 값(상시 {f2(res['used'][per][0]):.2f} · 청년등 "
                       f"{f2(res['used'][per][1]):.2f})입니다")
    if not res["direct"] and co.direct_given:          # 사원명부가 있으면 직접 입력 인원은 대조만 한다
        mine = res["used_new"] if res["new_scope"] else res["used"]
        given = {"해당": (co.direct_cur_total, co.direct_cur_youth), "직전": (co.direct_prev_total, co.direct_prev_youth),
                 "직전전": (co.direct_prev2_total, co.direct_prev2_youth)}
        for per in PERIODS:
            for i, label in ((0, "상시근로자 수"), (1, "청년등 수")):
                v = given[per][i]
                if v is None or res["source"][per] in ("없음", "직접 입력"):
                    continue
                if abs(f2(v) - f2(mine[per][i])) >= 0.005:
                    out.append(f"직접 입력한 {per} 과세연도 {label} {f2(v):.2f} 이(가) 사원명부로 센 {f2(mine[per][i]):.2f} 와 다릅니다. "
                               "공제액은 사원명부로 센 인원으로 계산했습니다. 어느 쪽이 맞는지 확인하십시오")
    backs = res["returnees"]
    miss = [x["name"] for x in backs if not x["counted"] and "복직일이 없습니다" in x["why"]]
    if miss:
        out.append(f"「육아휴직 복귀자」 Y 인데 복직일이 없어 세지 않은 사람 {len(miss)}명: {', '.join(miss[:8])}. 복직한 날을 사원명부 "
                   "「육아휴직 복직일」 에 적으십시오(제29조의8 제5항: 복직한 날이 속하는 과세연도에 공제)")
    off = [f"{x['name']}({x['why']})" for x in backs if not x["counted"] and x["in_year"]]
    if off:
        out.append(f"해당 과세연도에 복직했지만 육아휴직 복귀자로 세지 않은 사람 {len(off)}명: {', '.join(off[:8])}")
    nolf = [x["name"] for x in backs if x["no_leave_from"]]
    if nolf:
        out.append(f"육아휴직 시작일이 없어 연속 6개월 휴직 · 휴직 전 1년 근무 요건을 보지 못하고 센 사람: {', '.join(nolf[:8])}. "
                   "사원명부 「육아휴직 시작일」 을 적으십시오(제29조의8 제5항 제1호 · 제2호)")
    if res["returned"]:
        out.append("육아휴직 복귀자 추가공제는 자녀 1명당 한 차례입니다(제29조의8 제6항). 같은 자녀로 전에 공제받았는지는 자료로 가리지 못하니 "
                   "확인하십시오. 휴직 전 1년 근무는 근로소득원천징수부로 확인하고(시행령 제26조의8 제10항), 복직일부터 2년 안에 근로관계가 "
                   "끝나면 공제세액을 납부합니다(제7항, 계산하지 않음)")
    if co.returned is not None and int(round(co.returned)) != res["returned_roster"] and inp.staff:
        out.append(f"회사 시트 「육아휴직 복귀자 수」 {f2(co.returned):g} 을(를) 썼습니다. 사원명부로 센 {res['returned_roster']}명과 다릅니다")
    both = [p.name for p in inp.staff if p.mil_from and p.mil_to and p.mil_months]
    if both:
        out.append(f"입대일 · 전역일과 병역 개월 수가 함께 있어 입대일 · 전역일을 쓴 사람: {', '.join(both[:8])}")
    cur_rows = counts["해당"].rows
    deemed = [r for r in cur_rows if r.regular and any(a != b for a, b in zip(r.youth_age, r.youth_deem))]
    if deemed:
        out.append(f"청년 간주(2025년 이후 계약 때 34세 이하였던 사람)로 청년등에 넣은 달이 있는 사람: {names(deemed)}. "
                   "시행령 제26조의8 제4항 제1호 후단 · 부칙 <대통령령 제36127호> 제11조")
        out.append("2024년 이전에 계약한 사람은 간주 대상이 아니라 현재 연령만 봅니다(부칙 <대통령령 제36127호> 제11조, 2026-10-12 회계사 확인)")
    for per in ("해당", "직전"):
        c = counts[per]
        if per != "해당" and not c.period.has_payroll:
            continue
        gone = [r for r in c.rows if any(r.worked) and not r.regular]
        by: dict = {}
        for r in gone:
            by.setdefault(r.reason, []).append(r)
        for reason, rows in by.items():
            out.append(f"{per} 과세연도 상시근로자에서 뺀 사람({reason}) {len(rows)}명: {names(rows)}")
        nopay = [r for r in c.rows if r.no_pay]
        if nopay and c.period.has_payroll:
            out.append(f"{per} 과세연도 월말 재직인데 급여가 없는 달이 있는 사람 {len(nopay)}명: {names(nopay)}. 그 달은 근무개월 수에서 "
                       + ("뺐습니다" if inp.company.unpaid != "Y" else "빼지 않았습니다(급여 없는 달 포함 Y)") +
                       ". 무급휴직처럼 근로관계가 이어진 달이면 회사 시트 「급여 없는 달 포함」 을 Y 로 두고, 급여대장 누락 · 입사일 "
                       "오류인지 확인하십시오")
        odd = [r for r in c.rows if r.odd_pay]
        if odd:
            out.append(f"{per} 과세연도 재직 기간이 아닌데 급여가 있는 사람 {len(odd)}명: {names(odd)}. 입사일 · 퇴사일 또는 퇴직 뒤 정산 "
                       "지급인지 확인하십시오")
    ids = {p.id for p in inp.staff}
    missing = sorted({x.id for x in inp.pays if x.id not in ids})
    if missing:
        out.append(f"급여대장에는 있는데 사원명부에 없는 사번 {len(missing)}개: {', '.join(missing[:10])}. 그 사람은 인원에 들어가지 않았습니다")
    eom = [r for r in cur_rows if r.person.left and cur.start <= r.person.left <= cur.end
           and r.person.left == month_end(r.person.left)]
    if eom:
        out.append(f"퇴사일이 그 달 말일인 사람: {names(eom)}. 퇴사일을 마지막 근무일로 보아 그 달을 근무개월 수에 넣었습니다")
    part = [r for r in cur_rows if r.regular and r.weight < 1]
    if part:
        out.append(f"단시간근로자(1개월 소정근로시간 60시간 이상) {len(part)}명을 0.5명(지원요건을 채우면 0.75명)으로 셌습니다: {names(part)}")
    if res["second_cut"] or res["third_cut"]:
        for name, cut in (("2차", res["second_cut"]), ("3차", res["third_cut"])):
            if cut in ("전체 감소", "청년등 감소"):
                out.append(f"{name} 연도: {cut}(으)로 공제를 줄였습니다. 공제받은 세액의 추가 납부(시행령 제26조의8 제4항)는 계산하지 "
                           "않았으니 따로 계산해 8호(갑) 추가납부세액에 넣으십시오")
            elif cut:
                out.append(f"{name} 연도: {cut}(이)라 계산하지 않았습니다")
    if (co.first_prev_youth or co.first_prev2_youth) and (res["second"] or res["third"]):
        out.append("2 · 3차 연도 청년등 감소 여부는 현재 연령 기준 인원으로 보았습니다. 최초 공제 과세연도에 청년이던 사람을 그 뒤에도 "
                   "청년으로 보는 규정(시행령 제26조의8 제5항, 종전)을 감소 판정에도 쓰는지는 회계사가 확인합니다(☆ 해석례 확인 못 함)")
    out += [
        "상시근로자 범위(임원 · 최대주주와 친족 · 1년 미만 계약 · 단시간)와 청년등 구분(고용형태 · 병역 · 장애 · 경력단절)은 사원명부에 "
        "적힌 값을 그대로 썼습니다. 근로계약서 · 주주명부 · 병적증명서로 확인하는 것은 회계사 몫입니다",
        "납부 확인은 급여대장의 소득세 · 국민연금 · 건강보험 공제액으로 대신했습니다. 근로소득원천징수부와 납부 내역으로 "
        "확인하십시오(시행령 제23조 제10항 제6호)",
        "같은 과세연도에 고용증대 세액공제(제29조의7) 1차 연도 공제와 함께 신청할 수 없습니다(별지 제10호의9서식(1) 작성방법 7). "
        "다른 감면과의 중복 배제는 조서 20 공제감면의 확인 줄을 봅니다",
        "정규직 전환 추가공제(제29조의8 제4항), 합병 · 분할 · 사업 양수와 특수관계인 승계 인원(시행령 제23조 제13항 제3호), "
        "출산전후휴가 대체 인력(제26조의8 제7항), 인원이 줄었을 때의 추가 납부세액은 계산하지 않습니다",
        "최저한세 · 이월공제 · 농어촌특별세는 조서 20 공제감면과 8호 서식에서 계산합니다. 이 워크북의 세액공제액은 당기 발생액입니다",
    ]
    return out


# ---------------------------------------------------------------- 엑셀 재계산과 대조

def recalc(path: Path) -> bool:
    """엑셀로 한 번 계산해 수식 결과를 파일에 심는다. 엑셀이 없으면 False."""
    try:
        import pythoncom
        import win32com.client
    except ImportError:
        return False
    pythoncom.CoInitialize()
    try:
        xl = win32com.client.DispatchEx("Excel.Application")
    except Exception:                                        # noqa: BLE001  엑셀이 깔리지 않은 PC
        return False
    try:
        xl.Visible, xl.DisplayAlerts = False, False
        wb = xl.Workbooks.Open(str(path), UpdateLinks=0)
        xl.CalculateFull()
        wb.Save()
        wb.Close(False)
    finally:
        xl.Quit()
        pythoncom.CoUninitialize()
    return True


def read_back(path: Path, checks: dict) -> dict:
    """재계산한 파일에서 엔진 대조와 검산 결과를 읽는다."""
    wb = load_workbook(path, data_only=True)
    ws = wb[book.S_CHECK]
    bad, n = [], 0
    for label, pair in checks.items():
        if label.startswith("_"):
            continue
        engine, addr = pair
        v = ws[addr].value
        n += 1
        if v is None or isinstance(v, str) or abs(float(v) - float(engine)) >= 0.005:
            bad.append({"item": label, "engine": engine, "excel": v})
    ws = wb[book.S_LIST]
    tests, on = [], False
    for row in ws.iter_rows(min_col=1, max_col=4, values_only=True):
        if row[0] == "검산" and row[1] == "결과":
            on = True
            continue
        if on:
            if row[1] not in ("통과", "확인"):
                break
            tests.append({"check": row[0], "result": row[1], "left": row[2], "right": row[3]})
    form = wb[book.S_FORM]
    errors = [f"{s.title}!{c.coordinate}" for s in wb.worksheets for r in s.iter_rows() for c in r
              if isinstance(c.value, str) and c.value.startswith("#")]
    return {"matched": n - len(bad), "total": n, "bad": bad, "tests": tests, "errors": errors[:20], "form_rows": form.max_row}


# ---------------------------------------------------------------- 명령

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ctax employ", description="급여대장 · 사원명부로 통합고용세액공제 검증 워크북을 만든다")
    ap.add_argument("folder", help="신고 건 폴더(<회사>/<연도> 법인세)")
    ap.add_argument("--input", help=f"입력 파일(없으면 {INPUT_DIR}/{INPUT_NAME})")
    ap.add_argument("--template", action="store_true", help="빈 입력 양식을 만들고 끝낸다")
    ap.add_argument("--sample", action="store_true", help="시험용 합성 회사(스무 명) 입력을 만들고 끝낸다")
    ap.add_argument("--sample-year", type=int, choices=(2025, 2026, 2027), default=2025, help="--sample 의 해당 과세연도(기본 2025)")
    ap.add_argument("--no-excel", action="store_true", help="엑셀 재계산과 수식 값 대조를 하지 않는다")
    ap.add_argument("--keep", action="store_true", help="신고건.json 의 「상시근로자」 를 고치지 않는다")
    args = ap.parse_args(argv)
    if args.sample or args.template or args.input:
        Path(args.folder).mkdir(parents=True, exist_ok=True)      # 신고 건 폴더가 없으면 만든다
    try:
        case = Case(args.folder)
    except MissingInput as e:
        print(f"입력이 없습니다: {e}")
        return 2
    src = Path(args.input) if args.input else case.root / INPUT_DIR / INPUT_NAME
    if args.sample:
        if src.exists():
            print(f"{src} 가 이미 있어 그대로 두었습니다")
            return 0
        from . import sample
        sample.write(src, args.sample_year)
        print(f"시험용 입력(합성 회사 {len(sample.STAFF)}명)을 만들었습니다: {src}")
        print(f'이어서 python -m ctax employ "{args.folder}" 를 돌리십시오')
        return 0
    if args.template:
        if src.exists():
            print(f"{src} 가 이미 있어 그대로 두었습니다")
            return 0
        write_template(src, case)
        print(f"빈 양식을 만들었습니다: {src}")
        return 0
    info = case.info()
    try:
        inp = read_inputs(src, info.get("fy_start", ""), info.get("fy_end", ""), case.company)
    except InputError as e:
        print(f"입력을 읽지 못했습니다: {e}")
        return 2
    rules, rates = load_rules(), load_rates()
    res = compute(inp, rules, rates)
    pending = scope_pending(inp)
    direct = bool(direct_pending(inp))
    notes = pending + memos(inp, res, rules)
    wb, checks = book.build(inp, res, rules, rates, notes)
    out = case.out_dir(WP_DIR) / OUT_XLSX
    try:
        wb.save(out)
    except PermissionError:
        print(f"{out} 가 열려 있어 쓰지 못했습니다. 엑셀을 닫고 다시 돌리세요")
        return 1
    excel = False if args.no_excel else recalc(out)
    back = read_back(out, checks) if excel else None
    pdf_out = case.out_dir(WP_DIR) / lawform.OUT_PDF
    try:
        legal = lawform.write(pdf_out, inp, res, rules, case.company,
                              DIRECT_STAMP if direct else "잠정 · 사원명부 범위(임원 · 최대주주·친족 · 계약기간) 확인 전" if pending else "")
    except PermissionError:
        legal = {"written": False, "why": f"{pdf_out} 가 열려 있어 쓰지 못했습니다. PDF 를 닫고 다시 돌리세요"}

    used, src_of = res["used"], res["source"]
    head = {per: {"상시": f2(used[per][0]), "청년등": f2(used[per][1]), "청년등외": f2(used[per][0] - used[per][1]),
                  "출처": src_of[per]} for per in PERIODS}
    data = {"company": case.company, "fy_start": str(inp.company.fy_start), "fy_end": str(inp.company.fy_end),
            "method": res["method"], "size": inp.company.size, "capital": inp.company.capital, "headcount": head,
            "legacy": {per: {"상시": f2(res["legacy"][per][0]), "청년등": f2(res["legacy"][per][1])} for per in PERIODS},
            # 2026 과세연도부터 신규공제 · 추가공제 인원(새 범위). headcount 는 종전 범위(조서 credits 가 2 · 3차 연도 판정에 쓴다)
            "headcount_new": ({per: {"상시": f2(res["used_new"][per][0]), "청년등": f2(res["used_new"][per][1]),
                                     "청년등외": f2(res["used_new"][per][0] - res["used_new"][per][1]), "출처": src_of[per]}
                               for per in PERIODS} if res["new_scope"] else None),
            "rounding": "합계에서 버림" if res["sum_floor"] else "사람별 버림",
            "increase": {"상시": f2(res["d_t"]), "청년등": f2(res["d_y"]), "청년등외": f2(res["d_o"])},
            "credit": {"청년등 공제 인원": f2(res["n_y"]), "청년등 외 공제 인원": f2(res["n_o"]), "청년등 1인당": res["a_y"],
                       "청년등 외 1인당": res["a_o"], "1차 청년등": res["first_y"], "1차 청년등 외": res["first_o"],
                       "1차": res["first"], "2차": res["second"], "3차": res["third"], "추가공제": res["extra"],
                       "합계": res["total"], "2차 끊김": res["second_cut"], "3차 끊김": res["third_cut"]},
            "people": {per: {"사원명부": len(inp.staff), "재직": sum(1 for r in res["counts"][per].rows if any(r.worked)),
                             "상시근로자": sum(1 for r in res["counts"][per].rows if r.regular and any(r.worked))}
                       for per in PERIODS},
            "excel": back, "confirm": notes, "provisional": bool(pending), "direct": direct, "workbook": case.rel(out), "input": str(src),
            "law_pdf": case.rel(pdf_out) if legal.get("written") else None}
    case.write_json(OUT_JSON, data)

    wrote = False
    if not args.keep:
        info = case.info()
        old = info.get(INFO_KEY)
        if old is None or (isinstance(old, dict) and old.get("출처") == SOURCE):
            block = {"출처": SOURCE, "기업 구분": inp.company.size, "증가 지역 수도권": "여" if inp.company.capital == "Y" else "부"}
            for per in PERIODS:
                if src_of[per] != "없음":
                    block[per] = {"청년등": head[per]["청년등"], "청년등 외": head[per]["청년등외"]}
            first = {}
            if inp.company.first_prev_youth or inp.company.first_prev_other:
                first["직전"] = {"청년등": inp.company.first_prev_youth, "청년등 외": inp.company.first_prev_other}
            if inp.company.first_prev2_youth or inp.company.first_prev2_other:
                first["직전전"] = {"청년등": inp.company.first_prev2_youth, "청년등 외": inp.company.first_prev2_other}
            if first:
                block["1차년도 공제액"] = first
            if res["returned"]:      # 추가공제(육아휴직 복귀)는 ctax wp 가 이 인원으로 다시 계산한다(8호(갑) 1B5 줄)
                block["육아휴직 복귀 인원"] = res["returned"]
            info[INFO_KEY] = block
            case.write_json("신고건.json", info)
            wrote = True

    h = head["해당"]
    if direct:
        print("【잠정치】 사원명부 없이 인원 숫자로 계산했습니다. 상시근로자 명세서를 낼 수 없으니 확정으로 쓰지 마십시오")
    elif pending:
        print("【잠정치】 사원명부 범위(임원 · 최대주주·친족 · 계약 1년 미만 · 0.75 요건)를 확인하기 전 값입니다. 확정으로 쓰지 마십시오")
    print(f"통합고용세액공제 {won(res['total'])}원 = 1차 {won(res['first'])} + 2차 {won(res['second'])} + 3차 {won(res['third'])} "
          + (f"+ 신규 {won(res['new_total'])} " if res["regime"] == "2026" else "") + f"+ 추가 {won(res['extra'])}")
    print(f"상시근로자 수: 해당 {h['상시']:.2f}(청년등 {h['청년등']:.2f}) · 직전 {head['직전']['상시']:.2f}"
          f"(청년등 {head['직전']['청년등']:.2f}, {src_of['직전']}) · 증가 {f2(res['d_t']):.2f} · 방식 {res['method']}"
          + (" · 기존공제 판정용 종전 범위" if res["new_scope"] else ""))
    if res["new_scope"]:
        hn = data["headcount_new"]
        print(f"새 범위 상시근로자 수(신규공제 · 추가공제): 해당 {hn['해당']['상시']:.2f}(청년등 {hn['해당']['청년등']:.2f}) · "
              f"직전 {hn['직전']['상시']:.2f}(청년등 {hn['직전']['청년등']:.2f}) · 증가 {hn['해당']['상시'] - hn['직전']['상시']:.2f}")
    code = 1 if pending else 0
    if back:
        failed = [t for t in back["tests"] if t["result"] == "확인"]
        print(f"엔진 대조 {back['total']}개 중 {back['matched']}개 일치 · 검산 {len(back['tests'])}개 중 {len(back['tests']) - len(failed)}개 통과")
        for b in back["bad"][:10]:
            print(f"어긋남 엔진대조: {b['item']} 엔진 {b['engine']} · 엑셀 {b['excel']}")
        for t in failed:
            print(f"확인 검산: {t['check']} (왼쪽 {t['left']} · 오른쪽 {t['right']})")
        if back["errors"]:
            print(f"수식 오류 칸: {', '.join(back['errors'])}")
        if back["bad"] or failed or back["errors"]:
            code = 1
    else:
        print("엑셀 재계산을 하지 않았습니다. 워크북을 엑셀로 열면 수식이 계산됩니다(엔진 대조 · 검산은 「목록」 시트)")
    if legal.get("written"):
        print(f"법정서식 PDF {legal['pages']}쪽(법제처 서식 원본 위에 값 {legal['cells']}칸): {case.rel(pdf_out)}")
    else:
        print(f"법정서식 PDF 를 만들지 않았습니다: {legal.get('why', '')}")
    for text in notes[:40]:
        print(f"확인: {text}")
    if not args.keep and not wrote:
        print(f"신고건.json 의 「{INFO_KEY}」 는 사람이 넣은 값이라 고치지 않았습니다. 워크북 인원과 다르면 맞추십시오")
    case.mark_step("employ", code == 0, f"통합고용세액공제 {won(res['total'])}원 · 상시 {h['상시']:.2f}명 · 증가 {f2(res['d_t']):.2f}명",
                   [case.rel(out), f"_색인/{OUT_JSON}"] + ([case.rel(pdf_out)] if legal.get("written") else []))
    return code
