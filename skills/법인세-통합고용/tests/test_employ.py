"""ctax employ: 급여대장 · 사원명부 → 통합고용세액공제 인원 · 공제액 · 검증 워크북. 합성 회사만 쓴다."""
from __future__ import annotations

import json
from datetime import date
from fractions import Fraction
from pathlib import Path

import pytest
from openpyxl import Workbook, load_workbook

from ctax.employ import book, calc, cli
from ctax.employ.model import COMPANY_ROWS, PAY_COLS, STAFF_COLS, InputError, load_rules, read_inputs

D = date
# 사번, 성명, 생년월일, 입사일, 퇴사일, 고용형태, 그 밖의 열
STAFF = [
    ("A01", "김대표", D(1970, 1, 1), D(2019, 1, 1), None, "정규직", {"임원": "Y", "최대주주·친족": "Y"}),
    ("A02", "이정규", D(1985, 3, 10), D(2020, 1, 1), None, "정규직", {}),
    ("A03", "박청년", D(1995, 6, 15), D(2024, 7, 1), None, "정규직", {}),
    ("A04", "최경계", D(1990, 5, 28), D(2025, 4, 1), None, "정규직", {}),
    ("A05", "정기간", D(1998, 1, 1), D(2025, 3, 1), None, "기간제", {"계약 1년 미만": "Y"}),
    ("A06", "한단시", D(1980, 1, 1), D(2023, 1, 1), None, "단시간", {"월 소정근로시간": 80}),
    ("A07", "오퇴사", D(1996, 2, 2), D(2023, 3, 1), D(2025, 8, 15), "정규직", {}),
    ("A08", "윤고령", D(1960, 1, 1), D(2024, 10, 1), None, "정규직", {}),
    ("A09", "강장애", D(1975, 5, 5), D(2025, 7, 1), None, "단시간", {"월 소정근로시간": 100, "0.75 요건": "Y", "장애인 등": "Y"}),
    ("A10", "문병역", D(1989, 9, 1), D(2022, 1, 1), None, "정규직", {"입대일": D(2010, 3, 1), "전역일": D(2012, 2, 29)}),
    ("A11", "서무급", D(1992, 1, 1), D(2025, 1, 1), None, "정규직", {}),
    ("A12", "임외국", D(1990, 1, 1), D(2021, 1, 1), None, "정규직", {"내국인": "N"}),
]
NO_DEDUCTION = {"A11"}


def make_input(path: Path, company: dict | None = None, staff=STAFF, years=(2024, 2025), skip=()) -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = "회사"
    values = {"과세연도 시작일": D(2025, 1, 1), "과세연도 종료일": D(2025, 12, 31), "기업 구분": "중소기업", "증가 지역 수도권": "Y",
              "직전 1차년도 공제액 청년등": 14500000, "직전 1차년도 공제액 청년등 외": 8500000,
              "직전전 1차년도 공제액 청년등 외": 8500000, "전기 신고 직전전 상시근로자 수": 3.0, "전기 신고 직전전 청년등 수": 1.0}
    values.update(company or {})
    ws.append(["항목", "값"])
    for label, *_ in COMPANY_ROWS:
        ws.append([label, values.get(label)])
    ws = wb.create_sheet("사원명부")
    head = [c[0] for c in STAFF_COLS]
    ws.append(head)
    for sid, name, birth, hired, left, kind, more in staff:
        row = {"사번": sid, "성명": name, "생년월일": birth, "입사일": hired, "퇴사일": left, "고용형태": kind, **more}
        ws.append([row.get(h) for h in head])
    ws = wb.create_sheet("급여대장")
    ws.append([c[0] for c in PAY_COLS])
    for sid, name, _, hired, left, *_ in staff:
        for y in years:
            for m in range(1, 13):
                first, last = D(y, m, 1), calc.month_end(D(y, m, 1))
                if hired <= last and (left is None or left >= first) and (sid, y, m) not in skip:
                    ded = (0, 0, 0) if sid in NO_DEDUCTION else (50000, 135000, 106000)
                    ws.append([f"{y}-{m:02d}", sid, name, 3000000, *ded])
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path


@pytest.fixture
def case_dir(tmp_path):
    root = tmp_path / "가상회사" / "2025 법인세"
    root.mkdir(parents=True)
    make_input(root / "00 받은자료" / "급여" / "통합고용_입력.xlsx")
    return root


def run(path: Path):
    inp = read_inputs(path, company="가상회사")
    rules, rates = load_rules(), cli.load_rates()
    return inp, calc.compute(inp, rules, rates), rules, rates


def test_headcount_per_worker_and_month_end(case_dir):
    _, res, _, _ = run(case_dir / "00 받은자료" / "급여" / "통합고용_입력.xlsx")
    cur, prev = res["counts"]["해당"], res["counts"]["직전"]
    assert res["method"] == "근로자별"
    assert (cur.total, cur.youth_deem, cur.youth_age) == (Fraction("7.20"), Fraction("5.70"), Fraction("5.03"))
    assert (prev.total, prev.youth_age) == (Fraction("4.25"), Fraction("2.75"))
    assert (cur.me_total, cur.me_youth) == (Fraction("7.20"), Fraction("5.04"))      # 86.5 / 12, 60.5 / 12
    assert (prev.me_total, prev.me_youth) == (Fraction("4.25"), Fraction("2.75"))
    by = {r.person.id: r for r in cur.rows}
    assert by["A07"].n_work == Fraction("0.58") and sum(by["A07"].worked) == 7          # 8월 15일 퇴사: 8월은 월말 재직이 아니다
    assert by["A09"].n_work == Fraction("0.37") and by["A09"].kind == "장애인"           # 0.75 × 6 / 12 = 0.375
    assert by["A06"].weight == Fraction("0.5") and by["A06"].n_youth_deem == 0
    assert by["A04"].n_youth_deem == Fraction("0.75") and by["A04"].n_youth_age == Fraction("0.08")
    reasons = {r.person.id: r.reason for r in cur.rows if not r.regular}
    assert reasons == {"A01": calc.REASONS["c"], "A05": calc.REASONS["a"], "A12": calc.REASONS["f_res"]}      # A11 은 공제액이 없어도 급여가 있어 센다


def test_youth_cutoff_dates():
    rules = load_rules()
    inp_staff = {s[0]: s for s in STAFF}

    def person(sid):
        from ctax.employ.model import Person
        sid, name, birth, hired, left, kind, more = inp_staff[sid]
        return Person(id=sid, name=name, birth=birth, hired=hired, left=left, kind=kind,
                      mil_from=more.get("입대일"), mil_to=more.get("전역일"))
    # 별지 제10호의10서식 작성방법 25: 1990년 5월 28일생은 2025년 5월 28일부터 청년이 아니다
    assert calc.youth_cutoff(person("A04"), "중소기업", rules, deemed=False) == D(2025, 5, 28)
    # 작성방법 18: 2025년 4월 1일 계약이면 3년 또는 2년이 지난 2028-04-01 또는 2027-04-01
    assert calc.youth_cutoff(person("A04"), "중소기업", rules, deemed=True) == D(2028, 4, 1)
    assert calc.youth_cutoff(person("A04"), "일반기업", rules, deemed=True) == D(2027, 4, 1)
    # 병역 731일을 빼면 35세가 되는 날이 2026-09-02 로 늦춰진다
    assert calc.age_limits(person("A10"), rules)[1] == D(2026, 9, 2)
    assert calc.is_senior(person("A08"), rules) and not calc.is_senior(person("A02"), rules)


def test_deemed_only_for_contracts_from_2025(tmp_path):
    """청년 간주는 2025년 1월 1일 이후 체결한 계약만이다(2026-10-12 회계사 확인). 2024년 이전 계약은 현재 연령만 본다."""
    staff = [
        ("B01", "이전계약", D(1990, 9, 15), D(2024, 6, 3), None, "정규직", {}),      # 34세에 계약, 2025-09-15 에 35세
        ("B02", "올해계약", D(1990, 9, 15), D(2025, 6, 2), None, "정규직", {}),      # 34세에 계약, 3년 간주
    ]
    inp, res, rules, _ = run(make_input(tmp_path / "a.xlsx", staff=staff))
    by = {r.person.id: r for r in res["counts"]["해당"].rows}
    assert calc.deemed_until(inp.staff[0], "중소기업", rules) is None
    assert calc.deemed_until(inp.staff[1], "중소기업", rules) == D(2028, 6, 2)
    assert by["B01"].youth_deem == by["B01"].youth_age and sum(by["B01"].youth_deem) == 8      # 1 ~ 8월 말
    assert sum(by["B02"].youth_deem) == 7 and sum(by["B02"].youth_age) == 3                    # 6 ~ 12월 말, 현재 연령은 6 ~ 8월 말


def test_credit_first_second_third(case_dir):
    _, res, _, _ = run(case_dir / "00 받은자료" / "급여" / "통합고용_입력.xlsx")
    assert (res["d_t"], res["d_y"], res["d_o"]) == (Fraction("2.95"), Fraction("2.95"), Fraction(0))
    assert (res["n_y"], res["n_o"]) == (Fraction("2.95"), Fraction(0))
    assert res["first"] == 42_775_000                    # 2.95 × 1,450만원
    assert res["second"] == 23_000_000 and res["second_cut"] == ""
    assert res["third"] == 8_500_000 and res["source"]["직전전"] == "전기 신고서"
    assert res["total"] == 74_275_000


def test_second_year_cut_when_total_falls(tmp_path):
    staff = [s if s[0] != "A02" else (*s[:4], D(2024, 12, 31), *s[5:]) for s in STAFF]       # 2024년 말 퇴사
    staff = [s if s[0] not in ("A03", "A08") else (*s[:4], D(2025, 1, 15), *s[5:]) for s in staff]
    p = make_input(tmp_path / "in.xlsx", staff=staff)
    _, res, _, _ = run(p)
    assert res["legacy"]["해당"][0] < res["legacy"]["직전"][0]
    assert res["second"] == 0 and res["second_cut"] == "전체 감소" and res["first"] == 0


def test_startup_and_missing_prior(tmp_path):
    p = make_input(tmp_path / "a.xlsx", years=(2025,), company={"직전 1차년도 공제액 청년등": None, "직전 1차년도 공제액 청년등 외": None})
    _, res, _, _ = run(p)
    assert res["source"]["직전"] == "없음" and res["first"] == 0
    p = make_input(tmp_path / "b.xlsx", years=(2025,), company={"해당 과세연도 창업": "Y", "직전 1차년도 공제액 청년등": None,
                                                               "직전 1차년도 공제액 청년등 외": None})
    _, res, _, _ = run(p)
    assert res["source"]["직전"] == "창업(0)" and res["n_y"] == Fraction("5.70") and res["n_o"] == Fraction("1.50")


def test_month_end_method_before_2025(tmp_path):
    p = make_input(tmp_path / "in.xlsx", years=(2023, 2024),
                   company={"과세연도 시작일": D(2024, 1, 1), "과세연도 종료일": D(2024, 12, 31)})
    _, res, _, _ = run(p)
    assert res["method"] == "월말합" and not res["periods"]["해당"].deemed
    assert res["used"]["해당"] == (Fraction("4.25"), Fraction("2.75"))


def test_input_errors(tmp_path):
    bad = [("A01", "김대표", D(1970, 1, 1), D(2019, 1, 1), D(2018, 1, 1), "정규직", {})]
    with pytest.raises(InputError, match="퇴사일이 입사일보다"):
        read_inputs(make_input(tmp_path / "a.xlsx", staff=bad))
    bad = [("A01", "김대표", D(1970, 1, 1), D(2019, 1, 1), None, "프리랜서", {})]
    with pytest.raises(InputError, match="고용형태"):
        read_inputs(make_input(tmp_path / "b.xlsx", staff=bad))
    with pytest.raises(InputError, match="입력 파일이 없습니다"):
        read_inputs(tmp_path / "none.xlsx")


def test_workbook_is_formulas(case_dir):
    inp, res, rules, rates = run(case_dir / "00 받은자료" / "급여" / "통합고용_입력.xlsx")
    wb, checks = book.build(inp, res, rules, rates, ["확인"])
    assert wb.sheetnames == [book.S_LIST, book.S_BASE, book.S_STAFF, book.S_PAY, *book.S_JUDGE.values(), book.S_COUNT,
                             book.S_CREDIT, book.S_FORM, book.S_ROSTER, book.S_CHECK]
    # 판정 · 인원 · 공제액 · 서식의 숫자 칸은 값이 아니라 수식이다
    for name in (*book.S_JUDGE.values(), book.S_COUNT, book.S_CREDIT, book.S_FORM):
        ws = wb[name]
        nums = [c for row in ws.iter_rows() for c in row if isinstance(c.value, (int, float)) and not isinstance(c.value, bool)]
        assert not nums, f"{name}: 값으로 박힌 숫자 {[(c.coordinate, c.value) for c in nums[:5]]}"
    form = wb[book.S_FORM]
    text = " ".join(str(c.value) for row in form.iter_rows() for c in row if c.value)
    for word in ("⑥ 상시근로자 수(⑦+⑧)", "⑬ 상시근로자 증가 인원 수(⑪-⑫)", "⑳ 1차년도 세액공제액", "㉖ 2차년도 세액공제액", "㉜ 3차년도 세액공제액",
                 "㊱ 추가공제 세액공제액"):
        assert word in text
    assert len([k for k in checks if not k.startswith("_")]) > 60


def test_cli_writes_outputs_and_info(case_dir, capsys):
    code = cli.main([str(case_dir), "--no-excel"])
    assert code == 0
    data = json.loads((case_dir / "_색인" / "통합고용.json").read_text(encoding="utf-8"))
    assert data["credit"]["합계"] == 74_275_000 and data["headcount"]["해당"] == {"상시": 7.2, "청년등": 5.7, "청년등외": 1.5, "출처": "급여대장"}
    info = json.loads((case_dir / "_색인" / "신고건.json").read_text(encoding="utf-8"))
    block = info["상시근로자"]
    assert block["출처"] == "ctax employ" and block["해당"] == {"청년등": 5.7, "청년등 외": 1.5}
    assert block["직전"] == {"청년등": 2.75, "청년등 외": 1.5} and block["1차년도 공제액"]["직전"]["청년등"] == 14500000
    assert (case_dir / "2 조서" / "통합고용_검증.xlsx").exists()
    # 사람이 넣은 값은 덮어쓰지 않는다
    info["상시근로자"] = {"해당": {"청년등": 1, "청년등 외": 1}}
    (case_dir / "_색인" / "신고건.json").write_text(json.dumps(info, ensure_ascii=False), encoding="utf-8")
    cli.main([str(case_dir), "--no-excel"])
    assert json.loads((case_dir / "_색인" / "신고건.json").read_text(encoding="utf-8"))["상시근로자"]["해당"]["청년등"] == 1
    assert "고치지 않았습니다" in capsys.readouterr().out


def test_excel_formulas_match_engine(case_dir):
    """엑셀이 있는 PC 에서만: 수식을 계산시킨 값이 엔진 값과 모두 같고 검산이 모두 통과한다."""
    pytest.importorskip("win32com.client")
    code = cli.main([str(case_dir)])
    data = json.loads((case_dir / "_색인" / "통합고용.json").read_text(encoding="utf-8"))
    if data["excel"] is None:
        pytest.skip("엑셀이 없습니다")
    assert data["excel"]["bad"] == [] and data["excel"]["errors"] == []
    assert [t for t in data["excel"]["tests"] if t["result"] != "통과"] == []
    assert code == 0
    wb = load_workbook(case_dir / "2 조서" / "통합고용_검증.xlsx", data_only=True)
    form = wb[book.S_FORM]
    values = [c.value for row in form.iter_rows() for c in row if isinstance(c.value, (int, float))]
    assert 74_275_000 in values and 42_775_000 in values


def test_month_without_pay_is_not_counted(tmp_path):
    """급여대장이 있는 과세연도는 그 달 급여가 있어야 근무개월이다(2026-10-12 결정). 「급여 없는 달 포함」 Y 면 넣는다."""
    skip = {("A03", 2024, 7)}                    # 2024년 7월 1일 입사, 첫 급여는 8월
    _, res, _, _ = run(make_input(tmp_path / "a.xlsx", skip=skip))
    row = {r.person.id: r for r in res["counts"]["직전"].rows}["A03"]
    assert sum(row.worked) == 5 and row.n_work == Fraction("0.41") and row.no_pay == 1
    assert res["counts"]["직전"].total == Fraction("4.16")
    _, res, _, _ = run(make_input(tmp_path / "b.xlsx", skip=skip, company={"급여 없는 달 포함": "Y"}))
    row = {r.person.id: r for r in res["counts"]["직전"].rows}["A03"]
    assert sum(row.worked) == 6 and row.no_pay == 1 and res["counts"]["직전"].total == Fraction("4.25")


def test_sample_twenty(tmp_path):
    """`--sample` 이 만드는 합성 회사 스무 명. 기대값은 손으로 계산했고 README 0절에 같은 숫자가 있다."""
    root = tmp_path / "샘플회사" / "2025 법인세"
    assert cli.main([str(root), "--sample"]) == 0
    src = root / "00 받은자료" / "급여" / "통합고용_입력.xlsx"
    inp, res, _, _ = run(src)
    assert len(inp.staff) == 20
    assert res["used"]["해당"] == (Fraction("13.31"), Fraction("8.73")) and res["used"]["직전"] == (Fraction("11.32"), Fraction("6.99"))
    assert (res["d_t"], res["n_y"], res["n_o"]) == (Fraction("1.99"), Fraction("1.74"), Fraction("0.25"))
    assert res["legacy"]["해당"] == (Fraction("13.33"), Fraction("8.66")) and res["legacy"]["직전"] == (Fraction("11.33"), Fraction("7.00"))
    assert (res["first"], res["second"], res["third"], res["extra"], res["total"]) == (27_355_000, 37_500_000, 14_500_000, 13_000_000,
                                                                                 92_355_000)
    by = {r.person.id: r for r in res["counts"]["해당"].rows}
    assert (by["S07"].n_work, by["S07"].n_youth_deem) == (Fraction(1), Fraction("0.58"))
    assert (by["S09"].n_youth_deem, by["S09"].n_youth_age) == (Fraction("0.91"), Fraction("0.83"))
    assert by["S12"].n_work == Fraction("0.41") and by["S15"].regular and by["S15"].n_youth_deem == 0
    assert {r.person.id for r in res["counts"]["해당"].rows if not r.regular and any(r.paid)} == {"S01", "S02", "S14", "S17"}
    assert cli.main([str(root), "--sample"]) == 0 and cli.main([str(root), "--no-excel"]) == 0      # 있는 입력은 덮어쓰지 않는다


# ---------------------------------------------------------------- 2026 과세연도 신규공제

STAFF_2026 = [
    ("B01", "이일반", D(1985, 3, 10), D(2020, 1, 1), None, "정규직", {}),
    ("B02", "박청년", D(1995, 6, 15), D(2024, 7, 1), None, "정규직", {}),
    ("B03", "김신규", D(1994, 4, 1), D(2026, 1, 1), None, "정규직", {}),
    ("B04", "최신입", D(1980, 1, 1), D(2026, 1, 1), None, "정규직", {}),
    ("B05", "정반기", D(1970, 1, 1), D(2026, 7, 1), None, "정규직", {}),
    ("B06", "한간주", D(1991, 6, 1), D(2025, 2, 1), None, "정규직", {}),        # 2026-06-01 에 35세. 2025년 계약이라 간주 3년
    ("B07", "오간주", D(1990, 9, 1), D(2025, 3, 1), None, "정규직", {}),        # 2025-09-01 에 35세. 직전 과세연도에도 간주가 필요
]


def staff_2026(extra=0):
    more = [(f"E{i:02d}", f"추가{i}", D(1975, 1, 1), D(2026, 1, 1), None, "정규직", {}) for i in range(extra)]
    return STAFF_2026 + more


def run_2026(tmp_path, size="중소기업", extra=0, **company):
    values = {"과세연도 시작일": D(2026, 1, 1), "과세연도 종료일": D(2026, 12, 31), "기업 구분": size}
    values.update(company)
    p = make_input(tmp_path / "in.xlsx", company=values, staff=staff_2026(extra), years=(2025, 2026))
    return run(p)


def test_new_credit_2026_sme(tmp_path):
    """손으로 센 값: 직전(2025) 상시 1 + 1 + 0.91(11개월) + 0.83(10개월) = 3.74, 청년등(간주) 1 + 0.91 + 0.83 = 2.74.
    해당(2026) 상시 1 × 6 + 0.50(6개월) = 6.50, 청년등(간주) 4.00. 증가 2.76 = 청년등 1.26 + 청년등 외 1.50."""
    _, res, _, _ = run_2026(tmp_path)
    assert res["new26"] and not res["in_time"] and res["method"] == "근로자별"
    assert res["periods"]["직전"].deemed and res["periods"]["해당"].deemed
    assert res["used"]["해당"] == (Fraction("6.50"), Fraction("4.00")) and res["used"]["직전"] == (Fraction("3.74"), Fraction("2.74"))
    assert (res["d_t"], res["d_y"], res["d_o"]) == (Fraction("2.76"), Fraction("1.26"), Fraction("1.50"))
    assert (res["n_y"], res["n_o"]) == (Fraction("1.26"), Fraction("1.50"))
    assert (res["a_y"], res["a_o"]) == (7_000_000, 4_000_000)                         # 중소기업 수도권
    assert (res["first_y"], res["first_o"], res["first"], res["new_min"]) == (8_820_000, 6_000_000, 14_820_000, 0)
    # 2차(2025 증가분): 근로자별 · 간주 없음(청년등 2.41 → 2.41)이라 줄지 않았다. 3차(2024 증가분): 월말 합 방식, 줄지 않았다
    assert (res["second"], res["third"], res["extra"]) == (14_500_000 + 8_500_000, 8_500_000, 0)
    assert res["total"] == 14_820_000 + 23_000_000 + 8_500_000


def test_new_credit_2026_local_and_no_deem(tmp_path):
    _, res, _, _ = run_2026(tmp_path, **{"증가 지역 수도권": "N"})
    assert (res["a_y"], res["a_o"]) == (10_000_000, 7_000_000)                        # 수도권 밖
    assert res["first"] == 12_600_000 + 10_500_000                                    # 청년등 1.26 × 1,000만 + 외 1.50 × 700만
    # 청년 간주를 끄면 해당 · 직전 모두 현재 연령만 본다: 청년등 2.41 → 2.41, 외 2.33 → 4.09
    _, res, _, _ = run_2026(tmp_path / "n", **{"청년 간주 적용": "N"})
    assert not res["periods"]["해당"].deemed and not res["periods"]["직전"].deemed
    assert (res["d_y"], res["d_o"], res["n_y"], res["n_o"]) == (Fraction(0), Fraction("2.76"), Fraction(0), Fraction("2.76"))
    assert res["first"] == 11_040_000


def test_new_credit_2026_mid_minimum_increase(tmp_path):
    # 증가 2.76명은 최소고용증가인원수 5명 이하라 공제하지 않는다
    _, res, _, _ = run_2026(tmp_path / "a", size="중견기업")
    assert res["first"] == 0 and res["new_min_n"] == 5 and "최소고용증가인원수(5명)" in res["new_cut"]
    # 외 3명 더: 증가 5.76 > 5, 외 증가 4.50 < 5 → 제3호 = 4.5 × 300만 + 0.5 × 500만
    _, res, _, _ = run_2026(tmp_path / "b", size="중견기업", extra=3)
    assert (res["a_y"], res["a_o"]) == (5_000_000, 3_000_000) and res["n_o"] == Fraction("4.50")
    assert res["new_min"] == 16_000_000 and res["first"] == 6_300_000 + 13_500_000 - 16_000_000
    # 외 4명 더: 외 증가 5.50 ≥ 5 → 제3호 = 5 × 300만
    _, res, _, _ = run_2026(tmp_path / "c", size="중견기업", extra=4)
    assert res["n_o"] == Fraction("5.50") and res["new_min"] == 15_000_000 and res["first"] == 6_300_000 + 16_500_000 - 15_000_000


def test_new_credit_2026_general(tmp_path):
    _, res, _, _ = run_2026(tmp_path / "a", size="일반기업")
    assert res["first"] == 0 and res["new_min_n"] == 10
    # 외 8명 더: 증가 10.76 > 10, 외 증가 9.50 < 10 → 제3호 = 0.5 × 300만. 일반기업은 청년등 외 몫이 없고 청년등 300만원
    _, res, _, _ = run_2026(tmp_path / "b", size="일반기업", extra=8)
    assert (res["a_y"], res["a_o"]) == (3_000_000, 0) and res["new_min"] == 1_500_000 and res["first"] == 3_780_000 - 1_500_000
    # 외 9명 더: 외 증가 10.50 ≥ 10 → 제3호 0
    _, res, _, _ = run_2026(tmp_path / "c", size="일반기업", extra=9)
    assert res["new_min"] == 0 and res["first"] == 3_780_000


def test_cli_2026_engine_only(tmp_path):
    root = tmp_path / "가상회사" / "2026 법인세"
    root.mkdir(parents=True)
    make_input(root / "00 받은자료" / "급여" / "통합고용_입력.xlsx", staff=staff_2026(),
               company={"과세연도 시작일": D(2026, 1, 1), "과세연도 종료일": D(2026, 12, 31)}, years=(2025, 2026))
    assert cli.main([str(root), "--no-excel"]) == 0
    assert not list(root.rglob("통합고용_검증.xlsx"))                                # 2026 은 워크북을 만들지 않는다
    data = json.loads(next(root.rglob("통합고용*.json")).read_text(encoding="utf-8"))
    assert data["new26"] and data["workbook"] is None


def test_payroll_proof_rule(tmp_path):
    """납부 확인(시행령 제26조의8 제2항 제6호, 2026-10-14 결정): 단시간근로자가 아니면 급여가 지급된 사람은 공제액이 0 이어도 센다.
    급여가 한 번도 없으면 뺀다. 단시간근로자는 공제액이 모두 0 이면 뺀다."""
    staff = [
        ("Q01", "일반", D(1985, 3, 10), D(2020, 1, 1), None, "정규직", {}),
        ("Q02", "단시간", D(1985, 3, 10), D(2020, 1, 1), None, "단시간", {"월 소정근로시간": 80}),
        ("Q03", "무급여", D(1985, 3, 10), D(2020, 1, 1), None, "정규직", {}),
        ("Q04", "무공제", D(1985, 3, 10), D(2020, 1, 1), None, "정규직", {}),
    ]
    NO_DEDUCTION.update({"Q02", "Q04"})
    try:
        skip = {("Q03", 2025, m) for m in range(1, 13)}
        _, res, _, _ = run(make_input(tmp_path / "in.xlsx", staff=staff, skip=skip))
    finally:
        NO_DEDUCTION.difference_update({"Q02", "Q04"})
    rows = {r.person.id: r for r in res["counts"]["해당"].rows}
    assert (rows["Q01"].proof, rows["Q04"].proof) == ("Y", "Y") and rows["Q04"].regular and rows["Q04"].reason == ""
    assert rows["Q02"].proof == "N" and not rows["Q02"].regular and rows["Q02"].reason == calc.REASONS["e"]
    assert rows["Q03"].proof == "N" and not rows["Q03"].regular and rows["Q03"].reason == calc.REASONS["e"]
    assert res["counts"]["해당"].total == Fraction("2.00")


def _part_time_staff(q3_left=None):
    return [
        ("Q01", "일반1", D(1985, 3, 10), D(2020, 1, 1), None, "정규직", {}),
        ("Q02", "일반2", D(1985, 3, 10), D(2020, 1, 1), None, "정규직", {}),
        ("Q03", "일반3", D(1985, 3, 10), D(2020, 1, 1), q3_left, "정규직", {}),
        ("P01", "단시간", D(1985, 3, 10), D(2020, 1, 1), None, "단시간", {"월 소정근로시간": 80, "0.75 요건": "Y"}),
    ]


def test_part_time_075_needs_no_decrease(tmp_path):
    """시행령 제11조의2 제8항 제2호 가목: 단시간근로자를 뺀 상시근로자 수가 직전 과세연도보다 줄면 0.75명이 아니라 0.5명이다."""
    # 줄지 않음: 단시간 0.75 → 해당 3.75
    _, res, _, _ = run(make_input(tmp_path / "a.xlsx", staff=_part_time_staff()))
    assert res["half"] == {} and res["counts"]["해당"].total == Fraction("3.75") and res["counts"]["해당"].core == Fraction(3)
    # 일반3 이 2025년 6월 30일 퇴사: 해당 core 2.50 < 직전 3.00 → 해당은 0.5명(1 + 1 + 0.50 + 0.50 = 3.00), 직전은 직전전 급여대장이 없어 0.75명
    _, res, _, _ = run(make_input(tmp_path / "b.xlsx", staff=_part_time_staff(D(2025, 6, 30))))
    assert res["half"] == {"해당": (Fraction("2.50"), Fraction("3.00"))}
    assert res["counts"]["해당"].total == Fraction("3.00") and res["counts"]["직전"].total == Fraction("3.75")
    assert {r.person.id: r.weight for r in res["counts"]["해당"].rows}["P01"] == Fraction("0.5")
    assert any("0.75명이 아니라 0.5명" in t for t in cli.memos(read_inputs(tmp_path / "b.xlsx", company="가상회사"), res, load_rules()))
    # 직전 급여대장이 없으면 확인할 수 없어 입력값(Y)을 그대로 쓴다
    _, res, _, _ = run(make_input(tmp_path / "c.xlsx", staff=_part_time_staff(D(2025, 6, 30)), years=(2025,)))
    assert res["half"] == {} and res["counts"]["해당"].total == Fraction("3.25")      # 1 + 1 + 0.50 + 0.75


def test_part_time_075_excel_matches_engine(tmp_path):
    pytest.importorskip("win32com.client")
    root = tmp_path / "가상회사" / "2025 법인세"
    make_input(root / "00 받은자료" / "급여" / "통합고용_입력.xlsx", staff=_part_time_staff(D(2025, 6, 30)))
    code = cli.main([str(root)])
    data = json.loads((root / "_색인" / "통합고용.json").read_text(encoding="utf-8"))
    if data["excel"] is None:
        pytest.skip("엑셀이 없습니다")
    assert data["excel"]["bad"] == [] and data["excel"]["errors"] == [] and code == 0
    assert data["headcount"]["해당"]["상시"] == 3.0 and data["headcount"]["직전"]["상시"] == 3.75
