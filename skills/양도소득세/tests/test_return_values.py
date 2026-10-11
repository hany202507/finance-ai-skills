# -*- coding: utf-8 -*-
import copy
import json

import pytest

from yangdo import engine, filing, return_values, ruleset
from cases import CASES
import filers


def _rv(name, **over):
    r = engine.calculate(CASES[name], today="2026-10-11")
    f = filers.get(name)
    for aid in f["자산"]:
        f["자산"][aid]["법정동코드"] = "1120011400"
    f["신고인"]["주소"]["법정동코드"] = "1144010200"
    f["신고"].update(over)
    return r, return_values.build(r, CASES[name], filing.load(f))


def test_s1_form_values():
    r, rv = _rv("S1")
    a = rv["부표1"][0]
    assert (a["양도가액"], a["취득가액"], a["기타필요경비"], a["양도차익"]) == (1800000000, 609800000, 21000000, 1169200000)
    assert (a["과세양도차익"], a["장특공"], a["양도소득금액"]) == (389733333, 233839999, 155893334)
    t = rv["본지"]["열"]["합계"]
    assert (t["양도소득금액"], t["기본공제"], t["과세표준"], t["산출세액"]) == (155893334, 2500000, 153393334, 38349466)


def test_s1_payment_line():
    r, rv = _rv("S1")
    t = rv["본지"]["열"]["합계"]
    # 실행 중 정한 것(T4): 규칙 키는 전자신고세액공제.예정, 기준일은 신고일(= 작성일 2026-12-15)
    credit = ruleset.load().value("전자신고세액공제.예정", "2026-12-15") or 0
    assert t["전자신고공제"] == credit
    assert t["납부할세액"] == 38349466 - credit
    assert t["분납"] == 0


def test_installment_when_requested():
    r, rv = _rv("S1", 분납신청=True)
    t = rv["본지"]["열"]["합계"]
    assert t["분납"] == t["납부할세액"] // 2                 # 2천만원 초과면 50% 이하(원 미만 버림)
    assert t["신고기한내납부"] == t["납부할세액"] - t["분납"]


def test_acquisition_split_keeps_total():
    r, rv = _rv("S1")
    c = r["계산"]["자산"][0]["계산"]
    a = rv["부표1"][0]
    assert a["취득가액"] + a["기타필요경비"] == c["취득가액"] + c["필요경비"]


def test_schedule3_rows_sum():
    r, rv = _rv("S1")
    s = rv["부표3"][0]
    assert sum(x["금액"] for x in s["행"] if x["구분코드"].startswith("1")) == s["취득가액계"] == 609800000
    assert sum(x["금액"] for x in s["행"] if x["구분코드"].startswith("2")) == s["기타필요경비계"] == 21000000


def test_efile_rate_rows_have_total_row():
    r, rv = _rv("BF", 구분="확정", 작성일="2027-05-20")
    rows = rv["전자신고"]["세율별"]
    total = [x for x in rows if (x["국내외분"], x["세율구분"]) == ("Z", "00")]
    assert len(total) == 1
    assert total[0]["과세표준"] == sum(x["과세표준"] for x in rows if x["국내외분"] == "1" and x["세율구분"] != "00")


def test_local_tax_form_uses_engine_local_tax():
    r, rv = _rv("S1")
    assert rv["지방"]["열"]["합계"]["산출세액"] == 3834946


def test_reporting_codes():
    r, rv = _rv("S1")
    assert rv["신고"]["구분코드"] == "03" and rv["신고"]["서식종류"] == "D03" and rv["신고"]["과세기간"] == "202601"
    r, rv = _rv("BF", 구분="확정", 작성일="2027-05-20")
    assert rv["신고"]["구분코드"] == "01" and rv["신고"]["서식종류"] == "D01"


def test_personal_data_only_in_filer_sections():
    r, rv = _rv("S1")
    s = json.dumps({k: v for k, v in rv.items() if k not in ("신고인", "양수인", "신고")}, ensure_ascii=False)
    assert "김합성" not in s and "이합성" not in s


def test_prior_return_merge_is_unsupported():
    r = engine.calculate(CASES["S1"], today="2026-10-11")
    f = filers.get("S1")
    f["신고"]["구분"] = "확정"
    facts = dict(CASES["S1"], 연간=dict(CASES["S1"]["연간"], 기신고=[{"과세표준": 1}]))
    with pytest.raises(return_values.Unsupported):
        return_values.build(r, facts, filing.load(f))


# ---- 브리프에 없는 시험(구현 중 더함) ----

def test_preliminary_return_spanning_two_deadlines_is_unsupported():
    r = engine.calculate(CASES["BF"], today="2026-10-11")
    r = copy.deepcopy(r)
    r["계산"]["자산"][1]["판정"]["양도일"] = "2026-10-01"
    f = filers.get("BF")
    f["신고"].update(구분="예정", 작성일="2026-12-20")
    for aid in f["자산"]:
        f["자산"][aid]["법정동코드"] = "1120011400"
    with pytest.raises(return_values.Unsupported) as e:
        return_values.build(r, CASES["BF"], filing.load(f))
    assert e.value.계획 == "없음"


def test_s1_schedule1_labels_and_codes():
    r, rv = _rv("S1")
    a = rv["부표1"][0]
    assert a["세율구분표기"] == "1-10" and a["자산종류"] == "2"
    assert a["장특공코드"] == "01"                        # 표2
    assert (a["보유기간"], a["거주기간"], a["장특공거주기간"]) == ("8년 이상 9년 미만", "7년 이상 8년 미만", "7년 이상 8년 미만")
    assert (a["총면적_토지"], a["양도면적_건물"], a["취득면적_토지"]) == (30.0, 84.0, 30.0)
    assert a["취득가액종류"] == "실지거래가액"
    assert a["소재지"].endswith("456 합성아파트 101동 1001호")
    assert all(v == 0 for v in a["기준시가"].values())     # 실지거래가액이면 기준시가를 적지 않는다


def test_s1_rate_text_is_applied_bracket():
    r, rv = _rv("S1")
    assert rv["본지"]["열"]["1-10"]["세율"] == "38%" == rv["본지"]["열"]["합계"]["세율"]
    assert rv["지방"]["열"]["1-10"]["세율"] == "3.8%"
    row = [x for x in rv["전자신고"]["세율별"] if x["세율구분"] == "10"][0]
    assert row["세율"] == "38.00"
    assert all(x["세율"] == "0.00" for x in rv["전자신고"]["세율별"] if x["세율구분"] == "00")


def test_s1_schedule3_and_efile_expense_rows_carry_both_codes():
    r, rv = _rv("S1")
    rows = rv["부표3"][0]["행"]
    assert [(x["구분코드"], x["전자코드"], x["금액"]) for x in rows] == [
        ("111", "11101", 600000000), ("112", "11201", 6600000), ("114", "11401", 800000), ("115", "11501", 2400000),
        ("260", "26001", 12000000), ("290", "29001", 9000000)]
    assert rows[3]["상호"] == "합성공인중개사" and rows[3]["증빙코드"] == "01"
    ex = rv["전자신고"]["필요경비명세"]
    assert [x["전자코드"] for x in ex] == ["11101", "11201", "11401", "11501", "26001", "29001"]
    assert [x["상세일련번호"] for x in ex] == [1, 2, 3, 4, 5, 6] and {x["일련번호"] for x in ex} == {1}
    assert ex[0]["증빙종류코드"] == "ZZ" and ex[0]["지급일자"] == ""          # 필수가 아닌 구분코드(규격서 p60~61)
    assert ex[3]["증빙종류코드"] == "01" and ex[3]["지급일자"] == "20180315"
    calc_row = rv["전자신고"]["계산명세"][0]
    assert calc_row["필요경비신고자료일련번호"] == 1
    assert (calc_row["거래금액_취득가액"], calc_row["기타필요경비"]) == (609800000, 21000000)


def test_expense_business_number_and_counterparty_names():
    r, rv = _rv("S1")
    rows = rv["부표3"][0]["행"]
    ex = rv["전자신고"]["필요경비명세"]
    # 사실관계 필요경비 항목의 사업자번호(계약 보강 2026-10-11). 07 은 필수 구분코드 행에만 쓴다(규격서 p60 7번)
    assert [x["사업자번호"] for x in rows] == ["", "", "2118104565", "1018101238", "3149007897", "1018101238"]
    assert [x["사업자번호"] for x in ex] == ["", "", "2118104565", "1018101238", "3149007897", "1018101238"]
    assert all("사업자등록번호" not in x for x in ex)
    # 07-6 상호(Not Null): 취득세 행은 취득세 납세지(부동산 소재지) 시군구, 매입가액 행은 신고인 JSON 취득상대방
    assert ex[1]["상호"] == rows[1]["상호"] == "서울특별시 성동구"
    assert ex[0]["상호"] == "" and any("11101" in x and "취득상대방" in x for x in rv["확인사항"])
    assert not any("사업자번호가 필수" in x for x in rv["확인사항"])
    r, rv = _rv("S1")
    f = filers.get("S1")
    f["자산"]["S1"].update(법정동코드="1120011400", 취득상대방="합성건설")
    rv = return_values.build(r, CASES["S1"], filing.load(f))
    assert rv["전자신고"]["필요경비명세"][0]["상호"] == rv["부표3"][0]["행"][0]["상호"] == "합성건설"
    assert not any("11101" in x and "취득상대방" in x for x in rv["확인사항"])


def test_missing_business_number_is_a_check_item():
    facts = copy.deepcopy(CASES["S1"])
    del facts["자산"][0]["필요경비"]["양도비"][0]["사업자번호"]
    r = engine.calculate(facts, today="2026-10-11")
    f = filers.get("S1")
    f["자산"]["S1"]["법정동코드"] = "1120011400"
    rv = return_values.build(r, facts, filing.load(f))
    assert rv["전자신고"]["필요경비명세"][-1]["사업자번호"] == ""
    assert any("29001" in x and "사업자번호가 필수" in x for x in rv["확인사항"])


def test_efile_rows_carry_every_layout_field():
    import os
    from yangdo import SKILL_DIR
    with open(os.path.join(SKILL_DIR, "efile", "layout_c116300.json"), encoding="utf-8") as fh:
        layout = json.load(fh)["레코드"]
    r, rv = _rv("BF", 구분="확정", 작성일="2027-05-20")
    for no, key in (("03", "세율별"), ("05", "계산명세")):
        names = [x["name"] for x in layout[no]["필드"] if x["name"] not in ("자료구분", "서식코드", "공란")]
        for row in rv["전자신고"][key]:
            assert [k for k in row if k != "자산"] == names
            assert all(isinstance(row[x["name"]], int) for x in layout[no]["필드"] if x["type"] == "N" and x["class"] != "RATE"
                       and x["name"] in names and "면적" not in x["name"] and "지분" not in x["name"])


def test_s1_payment_rows_in_efile():
    r, rv = _rv("S1", 분납신청=True)
    rows = {(x["국내외분"], x["세율구분"]): x for x in rv["전자신고"]["세율별"]}
    assert list(rows) == [("1", "00"), ("1", "10"), ("Z", "00")]
    t = rv["본지"]["열"]["합계"]
    z, sub, rate = rows[("Z", "00")], rows[("1", "00")], rows[("1", "10")]
    assert (z["분납할세액"], z["자진납부세액"]) == (t["분납"], t["신고기한내납부"])
    assert sub["분납할세액"] == rate["분납할세액"] == 0 and sub["자진납부세액"] == rate["자진납부세액"] == 0
    assert z["전자신고세액공제"] == rate["전자신고세액공제"] == 20000
    assert all(x[k] == 0 for x in rows.values() for k in ("주민세_소득세자진납부할세액", "주민세_산출세액", "주민세_자진납부세액"))
    assert all(x["주민세_세율"] == "10.00" for x in rows.values())        # 레이아웃 점검값 01000(결정 2026-10-11)


def test_merged_comparison_tax_is_split_by_tax_base():
    # BF 의 평택 토지를 2025-06-01 취득으로 바꾸면 1년 이상 2년 미만 단기세율(40%, 1-15)이 이기고,
    # 합산 비교세액(기본세율로 합계 과세표준) 281,118,000원이 세율별 합 278,752,000원보다 크다
    facts = copy.deepcopy(CASES["BF"])
    facts["자산"][1]["취득"]["잔금일"] = "2025-06-01"
    r = engine.calculate(facts, today="2026-10-11")
    assert r["계산"]["합계"]["산출세액"] == r["계산"]["합계"]["합산비교세액"] == 281118000
    f = filers.get("BF")
    for aid in f["자산"]:
        f["자산"][aid]["법정동코드"] = "1120011400"
    rv = return_values.build(r, facts, filing.load(f))
    cols = rv["본지"]["열"]
    assert [x["표기"] for x in rv["본지"]["세율구분"]] == ["1-10", "1-15"]
    assert cols["1-10"]["산출세액"] + cols["1-15"]["산출세액"] == cols["합계"]["산출세액"] == 281118000
    assert cols["1-10"]["산출세액"] == 281118000 * 163400000 // 754900000
    assert cols["1-10"]["세율"] == cols["1-15"]["세율"] == cols["합계"]["세율"] == "42%"
    loc = rv["지방"]["열"]
    assert loc["1-10"]["산출세액"] + loc["1-15"]["산출세액"] == loc["합계"]["산출세액"] == 28111800
    rows = rv["전자신고"]["세율별"]
    assert [(x["국내외분"], x["세율구분"]) for x in rows] == [("1", "00"), ("1", "10"), ("1", "15"), ("Z", "00")]
    z = rows[-1]
    for k in ("산출세액", "자진납부할세액", "과세표준", "양도소득금액"):
        assert z[k] == rows[0][k] == rows[1][k] + rows[2][k], k
    assert any("과세표준 비율로 나눠" in x for x in rv["확인사항"])


def test_bf_final_return_has_no_credit_and_two_assets():
    r, rv = _rv("BF", 구분="확정", 작성일="2027-05-20")
    t = rv["본지"]["열"]["합계"]
    assert t["산출세액"] == 206274000 and t["전자신고공제"] == 0 and t["납부할세액"] == 206274000
    assert rv["신고"]["유형"] == "5" and rv["신고"]["양도일자"] == "20261120"
    assert [x["자산"] for x in rv["부표1"]] == ["B", "F"]
    assert rv["부표1합계"]["양도소득금액"] == 163400000 + 415800000
    assert rv["지방"]["열"]["합계"]["산출세액"] == 20627400
    f = rv["부표1"][1]
    assert f["취득가액종류"] == "환산취득가액" and (f["취득가액"], f["기타필요경비"]) == (400000000, 6000000)
    assert f["기준시가"]["양도_토지"] == 500000000 and f["기준시가"]["취득_합계"] == 200000000
    assert [x["자산"] for x in rv["부표3"]] == ["B"]                     # 환산취득가액 자산은 부표3 을 쓰지 않는다
    c = rv["전자신고"]["계산명세"][1]
    assert c["취득가액종류"] == "04" and c["양도시기준시가_토지"] == 500000000 and c["필요경비신고자료일련번호"] == 0


def test_k_heavy_tax_has_exclusion_code():
    r, rv = _rv("K")
    a = rv["부표1"][0]
    assert a["세율구분표기"] == "1-49" and a["장특공코드"] == "03" and a["보유기간"] == ""
    t = rv["본지"]["열"]["1-49"]
    assert t["산출세액"] == 322310000 and t["세율"] == "70%"            # 40% 구간 + 30%


def test_a_long_holding_label_and_blank_residence_code():
    r, rv = _rv("A")
    a = rv["부표1"][0]
    assert (a["보유기간"], a["거주기간"], a["장특공거주기간"]) == ("10년 이상", "", "12년 이상 13년 미만")
    assert rv["본지"]["열"]["합계"]["산출세액"] == 2565000 and rv["지방"]["열"]["합계"]["산출세액"] == 256500


def test_filer_warnings_move_to_check_items():
    r = engine.calculate(CASES["S1"], today="2026-10-11")
    f = filers.get("S1")
    f["자산"]["S1"]["법정동코드"] = "1120011400"
    n = f["양수인"][0]["번호"]
    f["양수인"][0]["번호"] = n[:12] + str((int(n[12]) + 1) % 10)
    loaded = filing.load(f)
    assert loaded["_경고"]
    rv = return_values.build(r, CASES["S1"], loaded)
    assert all(w in rv["확인사항"] for w in loaded["_경고"])
    assert "_경고" not in rv["신고인"]


def test_registry_purpose_override_and_default_check():
    facts = copy.deepcopy(CASES["S1"])
    facts["자산"][0]["취득"]["원인"] = "분양"
    r = engine.calculate(facts, today="2026-10-11")
    f = filers.get("S1")
    f["자산"]["S1"]["법정동코드"] = "1120011400"
    rv = return_values.build(r, facts, filing.load(f))
    c = rv["전자신고"]["계산명세"][0]
    assert (c["거래일자_취득등기목적"], c["거래일자_취득등기원인"]) == ("A1ZZCZ", "0055")
    assert any("분양" in x and "등기목적" in x for x in rv["확인사항"])
    f["자산"]["S1"]["등기목적"] = {"취득": "A1ZZAZ"}
    rv = return_values.build(r, facts, filing.load(f))
    c = rv["전자신고"]["계산명세"][0]
    assert (c["거래일자_취득등기목적"], c["거래일자_취득등기원인"]) == ("A1ZZAZ", "")
    f["자산"]["S1"]["등기목적"] = {"취득": "XYZ"}
    with pytest.raises(filing.FilingError):
        return_values.build(r, facts, filing.load(f))


def test_unfinished_result_is_rejected():
    r = engine.calculate(CASES["S1"], today="2026-10-11")
    r = dict(r, 상태="질문", 계산=None)
    with pytest.raises(ValueError):
        return_values.build(r, CASES["S1"], filing.load(filers.get("S1")))


def test_dropped_expense_is_listed_not_written():
    facts = copy.deepcopy(CASES["S1"])
    facts["자산"][0]["필요경비"]["자본적지출"].append(
        {"내용": "일반수선", "지급일": "2019-01-01", "금액": 1000000, "증빙종류": "카드영수증", "상대방": "합성수리"})
    r = engine.calculate(facts, today="2026-10-11")
    f = filers.get("S1")
    f["자산"]["S1"]["법정동코드"] = "1120011400"
    rv = return_values.build(r, facts, filing.load(f))
    assert all(x["금액"] != 1000000 for x in rv["부표3"][0]["행"])
    assert any("일반 수선" in x for x in rv["확인사항"])
