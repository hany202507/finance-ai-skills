"""`python -m ctax employ <신고 건 폴더>`: 급여대장 · 사원명부로 통합고용세액공제 검증 워크북을 만든다.

읽는 것  00 받은자료/급여/통합고용_입력.xlsx (`--template` 빈 양식, `--sample` 시험용 스무 명, `--input` 다른 파일)
쓰는 것  2 조서/통합고용_검증.xlsx, _색인/통합고용.json, 신고건.json 의 「상시근로자」(ctax wp 가 읽는다)
끝 코드  0 검산 모두 통과, 1 확인할 검산이 있음, 2 입력 없음
"""
from __future__ import annotations

import argparse
from pathlib import Path

from openpyxl import Workbook, load_workbook

from .. import xlsx as X
from ..case import WP_DIR, Case, MissingInput, won
from . import book
from .calc import compute, month_end
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


# ---------------------------------------------------------------- 확인할 것

def memos(inp: Inputs, res: dict, rules: dict) -> list[str]:
    co, out = inp.company, list(inp.notes)
    cur, counts = res["periods"]["해당"], res["counts"]
    names = lambda rows, n=8: ", ".join(r.person.name for r in rows[:n]) + (f" 외 {len(rows) - n}명" if len(rows) > n else "")  # noqa: E731
    if co.consumer == "Y":
        out.append("소비성서비스업이라 공제 대상이 아닙니다(조세특례제한법 제29조의8 제1항 괄호). 공제액을 0 으로 두었습니다")
    if not res["in_time"]:
        out.append("2026년 12월 31일이 속하는 과세연도부터는 별지 제10호의9서식(2)와 새 산식을 씁니다. 공제가 기존공제와 신규공제로 나뉩니다. "
                   "기존공제는 2024 · 2025 과세연도 증가분의 2 · 3차 연도로 종전 규정을 따르고(부칙 <법률 제21223호> 제34조), "
                   "신규공제는 2026 과세연도 이후 증가분으로 직전 3개 과세연도 대비 새 산식(법 제29조의8 제1항)입니다. "
                   "이 워크북은 서식(1)까지만 다루어 둘 다 계산하지 않았습니다")
    if res["method"] == "근로자별":
        out.append("1차 연도 인원은 근로자별 방식(사람마다 근무개월 수 ÷ 과세연도 개월 수, 100분의 1 미만 버림)으로 셌습니다"
                   "(시행령 제26조의8 제6항 · 제11조의2 제8항, 부칙 <대통령령 제36127호> 제11조 제1항). 2 · 3차 연도 판정은 "
                   "월말 합 방식(종전 규정)입니다. 두 방식의 인원은 4인원 시트에 함께 있습니다")
    for per in ("직전", "직전전"):
        src = res["source"][per]
        if src == "전기 신고서":
            out.append(f"{per} 과세연도 급여대장이 없어 전기 신고서의 인원(0기준 노란 칸)을 썼습니다. 계산 방식 · 청년 범위가 "
                       "당기와 같은지 확인하십시오")
        elif src == "없음" and (per == "직전" or co.first_prev2_youth or co.first_prev2_other):
            out.append(f"{per} 과세연도 인원이 없습니다(급여대장도 전기 신고 인원도 없음). 그 인원이 필요한 공제는 계산하지 않았습니다")
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
        sample.write(src)
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
    notes = memos(inp, res, rules)
    wb, checks = book.build(inp, res, rules, rates, notes)
    out = case.out_dir(WP_DIR) / OUT_XLSX
    try:
        wb.save(out)
    except PermissionError:
        print(f"{out} 가 열려 있어 쓰지 못했습니다. 엑셀을 닫고 다시 돌리세요")
        return 1
    excel = False if args.no_excel else recalc(out)
    back = read_back(out, checks) if excel else None

    used, src_of = res["used"], res["source"]
    head = {per: {"상시": f2(used[per][0]), "청년등": f2(used[per][1]), "청년등외": f2(used[per][0] - used[per][1]),
                  "출처": src_of[per]} for per in PERIODS}
    data = {"company": case.company, "fy_start": str(inp.company.fy_start), "fy_end": str(inp.company.fy_end),
            "method": res["method"], "size": inp.company.size, "capital": inp.company.capital, "headcount": head,
            "legacy": {per: {"상시": f2(res["legacy"][per][0]), "청년등": f2(res["legacy"][per][1])} for per in PERIODS},
            "increase": {"상시": f2(res["d_t"]), "청년등": f2(res["d_y"]), "청년등외": f2(res["d_o"])},
            "credit": {"청년등 공제 인원": f2(res["n_y"]), "청년등 외 공제 인원": f2(res["n_o"]), "청년등 1인당": res["a_y"],
                       "청년등 외 1인당": res["a_o"], "1차 청년등": res["first_y"], "1차 청년등 외": res["first_o"],
                       "1차": res["first"], "2차": res["second"], "3차": res["third"], "추가공제": res["extra"],
                       "합계": res["total"], "2차 끊김": res["second_cut"], "3차 끊김": res["third_cut"]},
            "people": {per: {"사원명부": len(inp.staff), "재직": sum(1 for r in res["counts"][per].rows if any(r.worked)),
                             "상시근로자": sum(1 for r in res["counts"][per].rows if r.regular and any(r.worked))}
                       for per in PERIODS},
            "excel": back, "confirm": notes, "workbook": case.rel(out), "input": str(src)}
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
            info[INFO_KEY] = block
            case.write_json("신고건.json", info)
            wrote = True

    h = head["해당"]
    print(f"통합고용세액공제 {won(res['total'])}원 = 1차 {won(res['first'])} + 2차 {won(res['second'])} + 3차 {won(res['third'])} "
          f"+ 추가 {won(res['extra'])}")
    print(f"상시근로자 수: 해당 {h['상시']:.2f}(청년등 {h['청년등']:.2f}) · 직전 {head['직전']['상시']:.2f}"
          f"(청년등 {head['직전']['청년등']:.2f}, {src_of['직전']}) · 증가 {f2(res['d_t']):.2f} · 방식 {res['method']}")
    code = 0
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
    for text in notes[:40]:
        print(f"확인: {text}")
    if not args.keep and not wrote:
        print(f"신고건.json 의 「{INFO_KEY}」 는 사람이 넣은 값이라 고치지 않았습니다. 워크북 인원과 다르면 맞추십시오")
    case.mark_step("employ", code == 0, f"통합고용세액공제 {won(res['total'])}원 · 상시 {h['상시']:.2f}명 · 증가 {f2(res['d_t']):.2f}명",
                   [case.rel(out), f"_색인/{OUT_JSON}"])
    return code
