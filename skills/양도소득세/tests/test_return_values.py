# -*- coding: utf-8 -*-
import copy
import json
import re

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


def test_prior_return_blocks_preliminary_return_too():
    """같은 해에 먼저 예정신고한 양도가 있으면 기본공제를 다시 쓸 수 없고 누진세율 자산은 기신고 양도소득금액을 합산해야 한다.
    예정신고도 확정신고와 같이 신고값을 만들지 않는다."""
    r = engine.calculate(CASES["A"], today="2026-10-11")
    f = filers.get("A")
    assert f["신고"]["구분"] == "예정"
    facts = dict(CASES["A"], 연간=dict(CASES["A"]["연간"], 다른양도=True, 기신고=50000000))
    with pytest.raises(return_values.Unsupported, match="기신고") as e:
        return_values.build(r, facts, filing.load(f))
    assert e.value.계획 == "5" and "예정신고" in str(e.value)
    assert "제1" not in str(e.value)                      # 조문 번호는 적지 않는다


def test_other_sale_without_prior_return_is_not_blocked():
    """다른 양도가 있다고만 답하고 기신고 금액이 없으면 막지 않는다(문항 P05 는 팔 예정인 건도 받는다)."""
    r = engine.calculate(CASES["A"], today="2026-10-11")
    for prior in (None, 0):
        facts = dict(CASES["A"], 연간=dict(CASES["A"]["연간"], 다른양도=True, 기신고=prior))
        rv = return_values.build(r, facts, filing.load(filers.get("A")))
        assert rv["본지"]["열"]["합계"]["산출세액"] == 2565000


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
    assert [x["사업자번호"] for x in rows] == ["", "", "0000000034", "0000000015", "0000000048", "0000000015"]
    assert [x["사업자번호"] for x in ex] == ["", "", "0000000034", "0000000015", "0000000048", "0000000015"]
    assert all("사업자등록번호" not in x for x in ex)
    # 07-6 상호(Not Null): 취득세 행은 취득세 납세지(부동산 소재지) 시군구, 매입가액 행은 신고인 JSON 취득상대방
    assert ex[1]["상호"] == rows[1]["상호"] == "서울특별시 성동구"
    assert ex[0]["상호"] == rows[0]["상호"] == "최합성"          # 합성 신고인(tests/filers.py)에 취득상대방이 있다
    assert not any("11101" in x and "취득상대방" in x for x in rv["확인사항"])
    assert not any("사업자번호가 필수" in x for x in rv["확인사항"])
    f = filers.get("S1")
    f["자산"]["S1"].update(법정동코드="1120011400", 취득상대방="합성건설")
    rv = return_values.build(r, CASES["S1"], filing.load(f))
    assert rv["전자신고"]["필요경비명세"][0]["상호"] == rv["부표3"][0]["행"][0]["상호"] == "합성건설"
    del f["자산"]["S1"]["취득상대방"]                             # 빠지면 상호를 비우고 확인사항으로 남긴다(질문 F08)
    rv = return_values.build(r, CASES["S1"], filing.load(f))
    assert rv["전자신고"]["필요경비명세"][0]["상호"] == "" and any("11101" in x and "취득상대방" in x for x in rv["확인사항"])


def test_missing_payment_date_is_a_check_item():
    facts = copy.deepcopy(CASES["S1"])
    facts["자산"][0]["필요경비"]["양도비"][0]["지급일"] = None
    r = engine.calculate(facts, today="2026-10-11")
    f = filers.get("S1")
    f["자산"]["S1"]["법정동코드"] = "1120011400"
    rv = return_values.build(r, facts, filing.load(f))
    assert rv["전자신고"]["필요경비명세"][-1]["지급일자"] == ""
    assert any("29001" in x and "지급일자가 필수" in x for x in rv["확인사항"])


def test_filing_codes_come_from_codes_table(tmp_path):
    import json as _json
    import os
    import shutil
    from yangdo import SKILL_DIR
    for name in os.listdir(os.path.join(SKILL_DIR, "efile")):
        shutil.copy(os.path.join(SKILL_DIR, "efile", name), tmp_path / name)
    path = tmp_path / "codes_c116300.json"
    codes = _json.loads(path.read_text(encoding="utf-8"))
    codes["서식종류"]["예정"]["코드"] = "X03"
    codes["세율별특수행"]["합계"]["국내외분"] = "Y"
    path.write_text(_json.dumps(codes, ensure_ascii=False), encoding="utf-8")
    r = engine.calculate(CASES["S1"], today="2026-10-11")
    f = filers.get("S1")
    f["자산"]["S1"]["법정동코드"] = "1120011400"
    rv = return_values.build(r, CASES["S1"], filing.load(f), efile_dir=str(tmp_path))
    assert rv["신고"]["서식종류"] == "X03"
    assert rv["전자신고"]["세율별"][-1]["국내외분"] == "Y"


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
    # 03-31 주민세_세율: 합계 행만 점검값 01000, 나머지 행 0(규격서 p43 31번, 결정 2026-10-11)
    assert (z["주민세_세율"], sub["주민세_세율"], rate["주민세_세율"]) == ("10.00", "0.00", "0.00")
    assert any("03-31" in x and "형식검증" in x for x in rv["확인사항"])


def test_single_column_payment_rows():
    r, rv = _rv("S1", 분납신청=True)
    for name in ("1-10", "국내소계"):
        c = rv["본지"]["열"][name]
        assert (c["기신고세액"], c["납부할세액"], c["분납"], c["신고기한내납부"]) == (0, 38329466, None, None), name
    t = rv["본지"]["열"]["합계"]
    assert (t["납부할세액"], t["분납"], t["신고기한내납부"]) == (38329466, 19164733, 19164733)
    # 지방소득세 예정신고 전자신고세액공제 2,000원을 뺀다
    assert rv["지방"]["열"]["1-10"]["납부할세액"] == 3832946 and rv["지방"]["열"]["1-10"]["신고기한내납부"] is None
    assert rv["지방"]["열"]["합계"]["신고기한내납부"] == 3832946


def _bf_merged():
    # BF 의 평택 토지를 2025-06-01 취득으로 바꾸면 1년 이상 2년 미만 단기세율(40%, 1-15)이 이기고,
    # 합산 비교세액(기본세율로 합계 과세표준) 281,118,000원이 세율별 합 278,752,000원보다 크다
    facts = copy.deepcopy(CASES["BF"])
    facts["자산"][1]["취득"]["잔금일"] = "2025-06-01"
    r = engine.calculate(facts, today="2026-10-11")
    assert r["계산"]["합계"]["산출세액"] == r["계산"]["합계"]["합산비교세액"] == 281118000
    f = filers.get("BF")
    for aid in f["자산"]:
        f["자산"][aid]["법정동코드"] = "1120011400"
    return r, return_values.build(r, facts, filing.load(f))


def test_merged_comparison_form_columns_keep_engine_rate_rows():
    """국세청 확정신고 작성 사례 09: 세율구분 열은 열의 세율·세액, 국내분 소계는 열 합, 합계는 비교세액, 합계·소계 ⑨ 공란."""
    r, rv = _bf_merged()
    cols = rv["본지"]["열"]
    assert [x["표기"] for x in rv["본지"]["세율구분"]] == ["1-10", "1-15"]
    assert [(cols[k]["산출세액"], cols[k]["세율"]) for k in ("1-10", "1-15")] == [(42152000, "38%"), (236600000, "40%")]
    assert cols["국내소계"]["산출세액"] == 42152000 + 236600000 and cols["국내소계"]["과세표준"] == 754900000
    assert cols["합계"]["산출세액"] == 281118000 and cols["합계"]["세율"] == cols["국내소계"]["세율"] == ""
    assert all(cols[k][x] is None for k in ("1-10", "1-15", "국내소계") for x in ("기신고세액", "납부할세액", "분납", "신고기한내납부"))
    assert cols["합계"]["납부할세액"] == 281118000
    loc = rv["지방"]["열"]
    assert [(loc[k]["산출세액"], loc[k]["세율"]) for k in ("1-10", "1-15")] == [(4215200, "3.8%"), (23660000, "4%")]
    assert loc["국내소계"]["산출세액"] == 27875200 and loc["합계"]["산출세액"] == 28111800 and loc["합계"]["세율"] == ""
    assert loc["1-10"]["납부할세액"] is None and loc["합계"]["납부할세액"] == 28111800      # 확정신고는 지방 공제도 없다
    assert any("합산 비교 세액이 커서" in x and "제104조⑤" in x for x in rv["확인사항"])


def test_merged_comparison_efile_rows_are_split_by_tax_base():
    r, rv = _bf_merged()
    rows = rv["전자신고"]["세율별"]
    assert [(x["국내외분"], x["세율구분"]) for x in rows] == [("1", "00"), ("1", "10"), ("1", "15"), ("Z", "00")]
    assert rows[1]["산출세액"] == 281118000 * 163400000 // 754900000
    assert (rows[1]["세율"], rows[2]["세율"]) == ("38.00", "40.00")      # 행의 적용 세율(규격서 p37 9번)
    z = rows[-1]
    for k in ("산출세액", "자진납부할세액", "과세표준", "양도소득금액"):
        assert z[k] == rows[0][k] == rows[1][k] + rows[2][k], k
    assert z["산출세액"] == z["자진납부할세액"] == 281118000
    assert any("과세표준 비율로 나눠" in x for x in rv["확인사항"])


def test_bf_final_return_has_no_credit_and_two_assets():
    r, rv = _rv("BF", 구분="확정", 작성일="2027-05-20")
    t = rv["본지"]["열"]["합계"]
    assert t["산출세액"] == 206274000 and t["전자신고공제"] == 0
    assert t["납부할세액"] == 206274000 + t["가산세"]             # 확정신고에는 전자신고세액공제가 없고 가산세가 더해진다
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


def test_a_long_holding_label_and_residence_without_requirement():
    # 거주 코드 Z1(2017-08-02 이전 취득, 거주요건 없음)이어도 거주한 구간이 있으면 ⑩ 을 채운다(국세청 작성 사례 03)
    r, rv = _rv("A")
    a = rv["부표1"][0]
    assert rv["전자신고"]["계산명세"][0]["1세대1주택_비과세_거주기간"] == "Z1"
    assert (a["보유기간"], a["거주기간"], a["장특공거주기간"]) == ("10년 이상", "10년 이상", "10년 이상")
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


def test_expense_lines_decide_which_expenses_become_07_rows():
    """부표3·07 행이 어떤 지출에서 생기는지는 expense_lines 한 곳이 정한다(filing 의 질문 F07·F08 도 이것을 쓴다)."""
    r, rv = _rv("S1")
    a, c = CASES["S1"]["자산"][0], r["계산"]["자산"][0]["계산"]
    lines = return_values.expense_lines(a, c)
    assert [(ln.group, ln.key) for ln in lines] == [
        ("매입가액", "매입가액"), ("취득세", "취득세"), ("취득부대", "취득중개수수료"), ("취득부대", "법무사비용"),
        ("자본적지출", "자본적지출_용도변경개량"), ("양도비", "양도중개수수료등")]
    assert [(ln.no, ln.item) for ln in lines if ln.item] == [
        (1, a["필요경비"]["취득부대"][0]), (2, a["필요경비"]["취득부대"][1]),
        (1, a["필요경비"]["자본적지출"][0]), (1, a["필요경비"]["양도비"][0])]
    assert all(ln.item is None for ln in lines if ln.group in ("매입가액", "취득세", "감가상각비"))
    codes = return_values.load_codes()
    assert sorted(codes["필요경비구분"][ln.key]["전자코드"] for ln in lines) == [x["전자코드"] for x in rv["전자신고"]["필요경비명세"]]
    assert [x["구분"] for x in rv["부표3"][0]["행"]] == [codes["필요경비구분"][ln.key]["이름"] for ln in sorted(
        lines, key=lambda ln: codes["필요경비구분"][ln.key]["전자코드"])]


def test_expense_lines_follow_the_acquisition_method():
    a = copy.deepcopy(CASES["S1"]["자산"][0])
    a["감가상각비"] = 1_000_000
    a["필요경비"]["취득세"] = 0
    a["필요경비"]["양도비"][0]["증빙종류"] = "간이영수증"            # 엔진이 빼는 지출은 줄이 되지 않는다
    real = {"취득가액": 600_000_000, "취득가액방법": "실지거래가액"}
    assert [ln.group for ln in return_values.expense_lines(a, real)] == [
        "매입가액", "취득부대", "취득부대", "감가상각비", "자본적지출"]
    # 환산취득가액이면 줄이 없다. 자본적지출·양도비를 필요경비로 쓰는 경우(취득가액 0)만 그 둘이 줄이 된다(소득세법 제97조②2호 단서)
    assert return_values.expense_lines(a, {"취득가액": 5_000_000, "취득가액방법": "환산가액"}) == []
    assert [ln.group for ln in return_values.expense_lines(a, {"취득가액": 0, "취득가액방법": "환산가액"})] == ["자본적지출"]
    assert return_values.expense_lines(a, {"취득가액": None, "취득가액방법": None}) == []        # 전액 비과세


# ---- 예정신고를 하지 않은 확정신고의 가산세(계획 2b G1b) ----
# 기대값은 손계산이다(references/정답지.md 「가산세 대조」).
# BF(토지 F 2026-11-01, 주택 B 2026-11-20, 납부일 2027-05-20): 한 건, 예정신고 세액 206,274,000, 납부기한 2027-02-01, 107일
#   무신고 = 206,274,000 × 20% = 41,254,800(지금 문언에서는 감면을 적용하지 않는다. 감면이 적용되면 20,627,400)
#   납부지연 = 206,274,000 × 107 × 22/100,000 = 4,855,689.96 → 4,855,680
#   가산세 계 46,110,480, 납부할 세액 = 206,274,000 + 46,110,480 = 252,384,480

BF_PENALTY = (41254800, 4855680, 46110480)


def test_bf_final_return_penalty_in_main_form():
    r, rv = _rv("BF", 구분="확정", 작성일="2027-05-20")
    cols = rv["본지"]["열"]
    for name in ("합계", "국내소계", "1-10"):                  # 열이 하나면 합계·소계·세율구분 열에 같은 값(사례 09 하위 4·5·8)
        c = cols[name]
        assert (c["가산세_신고"], c["가산세_납부"], c["가산세"]) == BF_PENALTY and c["가산세_기장"] == 0, name
    t = cols["합계"]
    assert t["납부할세액"] == 252384480 and (t["분납"], t["신고기한내납부"]) == (0, 252384480)
    assert cols["1-10"]["납부할세액"] == cols["국내소계"]["납부할세액"] == 252384480
    assert cols["1-10"]["분납"] is None and cols["1-10"]["신고기한내납부"] is None
    assert cols["국외소계"]["가산세"] == 0
    loc = rv["지방"]["열"]["합계"]                              # 지방소득세 신고서의 가산세는 계산하지 않는다
    assert (loc["전자신고공제"], loc["가산세"], loc["납부할세액"]) == (0, 0, 20627400)


def test_bf_final_return_penalty_in_efile_rows():
    r, rv = _rv("BF", 구분="확정", 작성일="2027-05-20")
    rows = {(x["국내외분"], x["세율구분"]): x for x in rv["전자신고"]["세율별"]}
    assert list(rows) == [("1", "00"), ("1", "10"), ("Z", "00")]
    for k, x in rows.items():
        assert (x["가산세-신고불성실"], x["가산세-납부불성실"], x["가산세-계"]) == BF_PENALTY, k
        assert x["가산세-기장불성실등"] == 0 and x["자진납부할세액"] == 252384480, k
    z = rows[("Z", "00")]
    assert (z["분납할세액"], z["자진납부세액"]) == (0, 252384480)
    assert rows[("1", "10")]["자진납부세액"] == rows[("1", "00")]["자진납부세액"] == 0


def test_installment_limit_excludes_penalty():
    """분납 한도는 가산세를 뺀 세액 206,274,000 의 100분의 50 = 103,137,000. 가산세는 신고기한 안에 내는 세액에 들어간다
    (252,384,480 − 103,137,000 = 149,247,480)."""
    r, rv = _rv("BF", 구분="확정", 작성일="2027-05-20", 분납신청=True)
    t = rv["본지"]["열"]["합계"]
    assert (t["납부할세액"], t["분납"], t["신고기한내납부"]) == (252384480, 103137000, 149247480)
    z = [x for x in rv["전자신고"]["세율별"] if x["국내외분"] == "Z"][0]
    assert (z["자진납부할세액"], z["분납할세액"], z["자진납부세액"]) == (252384480, 103137000, 149247480)
    note = [m for m in rv["확인사항"] if "분납할 세액의 한도" in m]
    assert len(note) == 1 and "가산세를 뺀 세액 206274000원" in note[0]
    assert "소득세법 제112조·제106조①·제111조①" in note[0]     # 규칙세트(판정.분납대상세액)에 실린 조문만 적는다


def test_final_return_penalty_section_and_notes():
    r, rv = _rv("BF", 구분="확정", 작성일="2027-05-20")
    p = rv["가산세"]
    assert p["계산"] is True and p["납부일"] == "2027-05-20"
    assert (p["무신고"], p["납부지연"], p["계"]) == BF_PENALTY
    assert p["감면적용"] is False and (p["무신고_감면적용"], p["무신고_감면없음"]) == (20627400, 41254800)
    assert [(c["자산"], c["예정신고세액"], c["납부기한"], c["일수"]) for c in p["건"]] == [(["F", "B"], 206274000, "2027-02-01", 107)]
    assert p["열"] == {"1-10": {"무신고": 41254800, "납부지연": 4855680}}
    # 양도일마다 따로 신고하는 것으로 보면 181,532,000 × 20% = 36,306,400(감면이 적용되면 18,153,200), 납부지연 4,273,250
    assert (p["양도일별"]["무신고"], p["양도일별"]["무신고_감면적용"], p["양도일별"]["납부지연"]) == (36306400, 18153200, 4273250)
    json.dumps(p, ensure_ascii=False)                        # 신고값.json 에 그대로 실린다
    notes = rv["확인사항"]

    def one(*parts):
        hit = [m for m in notes if all(x in m for x in parts)]
        assert len(hit) == 1, parts
        return hit[0]

    one("본지 ⑯", "41254800원", "4855680원", "46110480원")
    # 세액이 달라질 수 있는 해석 둘은 penalty 의 문장을 그대로 옮긴다
    assert one("감면 없이", "감면이 적용되면", "20627400원", "세무 전문가") == p["감면안내"]
    one("양도일마다 따로 신고하는 것으로 보면", "36306400원", "4273250원")
    one("부정행위", "다루지 않는다")
    one("납부일(2027-05-20) 기준")
    one("지방소득세 신고서의 가산세는 계산하지 않아", "위택스")
    assert not [m for m in notes if "가산세를 계산하지 않아 0 으로 두었으므로" in m]
    for m in notes:
        assert "\u2014" not in m and not m.rstrip().endswith("?")


def test_preliminary_return_has_no_penalty():
    r, rv = _rv("S1")
    assert rv["가산세"] is None
    assert all(c["가산세"] == 0 for c in rv["본지"]["열"].values())
    assert not [m for m in rv["확인사항"] if "무신고가산세" in m]
    assert all(x["가산세-계"] == 0 and x["가산세-신고불성실"] == 0 for x in rv["전자신고"]["세율별"])


def test_penalty_that_cannot_be_determined_is_flagged():
    """같은 달에 양도한 두 자산의 세율이 다르고 합산 비교세액이 이기면 예정신고 세액을 정할 사례가 없다(penalty.Unsupported).
    신고값은 가산세를 0 으로 두고 「가산세」 절에 사유를 실어, 진입점이 신고서와 전자신고 파일을 만들지 않게 한다."""
    r, rv = _bf_merged()
    p = rv["가산세"]
    assert p["계산"] is False and p["계획"] == "없음" and "합산 비교세액" in p["사유"]
    assert rv["본지"]["열"]["합계"]["가산세"] == 0 and rv["본지"]["열"]["합계"]["납부할세액"] == 281118000
    note = [m for m in rv["확인사항"] if "가산세를 계산하지 못해" in m]
    assert len(note) == 1 and "이 값으로 신고하지 않는다" in note[0] and p["사유"] in note[0]


def _bf_merged_two_months():
    """_bf_merged 의 토지 F 를 2026-10-01 에 양도한 것으로 바꾼다. 건이 둘(10월 F, 11월 B)이라 가산세를 계산할 수 있고,
    연간 산출세액은 여전히 합산 비교세액 281,118,000 이다.
      F 건: 591,500,000 × 40% = 236,600,000, 기한 2026-12-31(목), 2027-01-01 ~ 2027-05-19 = 31 + 28 + 31 + 30 + 19 = 139일
      B 건: 37,060,000 + 13,400,000 × 38% = 42,152,000, 기한 2027-02-01(말일 01-31 일요일), 107일
      무신고 = 278,752,000 × 20% = 55,750,400 (47,320,000 + 8,430,400)
      납부지연 = 236,600,000 × 139 × 22/100,000 = 7,235,228 → 7,235,220, 42,152,000 × 107 × 22/100,000 = 992,258.08 → 992,250
      가산세 계 = 55,750,400 + 8,227,470 = 63,977,870, 납부할 세액 = 281,118,000 + 63,977,870 = 345,095,870"""
    facts = copy.deepcopy(CASES["BF"])
    facts["자산"][1]["취득"]["잔금일"] = "2025-06-01"
    facts["자산"][1]["양도"]["잔금일"] = "2026-10-01"
    r = engine.calculate(facts, today="2026-10-11")
    assert r["계산"]["합계"]["산출세액"] == r["계산"]["합계"]["합산비교세액"] == 281118000
    f = filers.get("BF")
    for aid in f["자산"]:
        f["자산"][aid]["법정동코드"] = "1120011400"
    return r, return_values.build(r, facts, filing.load(f))


def test_merged_comparison_penalty_goes_to_total_column_only():
    """국세청 확정신고 작성 사례 09 하위 2: 합산 비교세액이 이긴 신고서는 가산세와 납부할 세액을 합계 열에만 적었다."""
    r, rv = _bf_merged_two_months()
    cols = rv["본지"]["열"]
    t = cols["합계"]
    assert (t["가산세_신고"], t["가산세_납부"], t["가산세"]) == (55750400, 8227470, 63977870)
    assert t["납부할세액"] == 345095870
    for name in ("국내소계", "1-10", "1-15"):
        assert all(cols[name][k] is None for k in ("가산세", "가산세_신고", "가산세_납부", "가산세_기장", "기신고세액", "납부할세액",
                                                   "분납", "신고기한내납부")), name
    rows = {(x["국내외분"], x["세율구분"]): x for x in rv["전자신고"]["세율별"]}
    # 03 레코드는 합계 행이 세율구분 행의 합이어야 해서 행마다 적는다(규격서 p41 15~17번)
    assert (rows[("1", "10")]["가산세-신고불성실"], rows[("1", "10")]["가산세-납부불성실"]) == (8430400, 992250)
    assert (rows[("1", "15")]["가산세-신고불성실"], rows[("1", "15")]["가산세-납부불성실"]) == (47320000, 7235220)
    for k in ("가산세-신고불성실", "가산세-납부불성실", "가산세-계", "자진납부할세액", "산출세액"):
        assert rows[("Z", "00")][k] == rows[("1", "00")][k] == rows[("1", "10")][k] + rows[("1", "15")][k], k
    assert rows[("Z", "00")]["자진납부할세액"] == 345095870
    assert any("합계 열에만 적었다" in m for m in rv["확인사항"])


# ---- 지방소득세 전자신고세액공제(지방세특례제한법 제167조의3①, 같은 법 시행령 제116조의2: 예정신고 2천원) ----

def test_local_efile_credit_on_preliminary_return():
    r, rv = _rv("S1")
    loc = rv["지방"]["열"]
    for name in ("합계", "국내소계", "1-10"):
        assert loc[name]["전자신고공제"] == 2000, name
    assert loc["합계"]["산출세액"] == 3834946 and loc["합계"]["납부할세액"] == 3834946 - 2000
    note = [m for m in rv["확인사항"] if "지방소득세 전자신고세액공제" in m]
    assert len(note) == 1 and "2000원" in note[0] and "지방세특례제한법 제167조의3①" in note[0]
    assert "규칙세트에 값이 없어" not in " ".join(rv["확인사항"])
    assert all(x[k] == 0 for x in rv["전자신고"]["세율별"]            # 국세 파일의 주민세 칸은 그대로 0 이다
               for k in ("주민세_소득세자진납부할세액", "주민세_산출세액", "주민세_자진납부세액"))


def test_local_efile_credit_is_capped_by_local_tax():
    """공제가 지방소득세 산출세액보다 크면 산출세액까지만 뺀다(납부할 세액이 음수이면 없는 것으로 한다)."""
    r = engine.calculate(CASES["S1"], today="2026-10-11")
    r = copy.deepcopy(r)
    r["계산"]["합계"]["지방소득세"] = r["계산"]["합계"]["지방_호별합산"] = 1500
    f = filers.get("S1")
    f["자산"]["S1"]["법정동코드"] = "1120011400"
    b = return_values._Builder(r, CASES["S1"], filing.load(f), None, None, None)
    b.filing_section()
    b.local_by_column = lambda taxed: {("1", "10"): 1500}
    local = b.main_forms()[1]
    assert (local["열"]["합계"]["전자신고공제"], local["열"]["합계"]["납부할세액"]) == (1500, 0)


def test_no_local_efile_credit_on_final_return():
    r, rv = _rv("BF", 구분="확정", 작성일="2027-05-20")
    assert all(c["전자신고공제"] == 0 for c in rv["지방"]["열"].values())
    assert not [m for m in rv["확인사항"] if "지방소득세 전자신고세액공제" in m]


# ---- 신고기한이 지난 작성일(기한후신고)은 신고 범위가 아니다. 기한은 규칙세트와 dates.filing_deadline 에서 온다 ----

def _late(name, made, mutate=None, **over):
    """facts 를 고쳐 엔진을 다시 돌리고 작성일을 바꿔 신고값을 만든다."""
    f = copy.deepcopy(CASES[name])
    if mutate:
        mutate(f)
    r = engine.calculate(f, today="2026-10-11")
    filer = filers.get(name)
    for aid in filer["자산"]:
        filer["자산"][aid]["법정동코드"] = "1120011400"
    filer["신고인"]["주소"]["법정동코드"] = "1144010200"
    filer["신고"].update(작성일=made, **over)
    return return_values.build(r, f, filing.load(filer))


def _weekend_notes(rv):
    """신고기한이 토·일·공휴일이라 옮긴 기한 안의 작성일을 정기신고로 만들었다는 문장."""
    return [m for m in rv["확인사항"] if "정기신고로 만들었다" in m]


def test_preliminary_deadline_on_weekday_is_inclusive():
    # K: 2026-07-01 양도, 예정신고 기한 2026-09-30(수요일)
    rv = _late("K", "2026-09-30")
    assert rv["신고"]["상세코드"] == "01" and _weekend_notes(rv) == []
    with pytest.raises(return_values.Unsupported) as e:
        _late("K", "2026-10-01")
    assert "2026-09-30" in str(e.value) and "기한후신고" in str(e.value) and e.value.계획 == "없음"


def test_preliminary_deadline_on_sunday_moves_to_monday():
    # S1: 2026-11-20 양도, 기한 말일 2027-01-31(일요일) 이라 2027-02-01(월요일)까지
    assert _weekend_notes(_late("S1", "2027-01-31")) == []            # 명목 기한 이내는 안내가 필요 없다
    rv = _late("S1", "2027-02-01")
    notes = _weekend_notes(rv)
    assert len(notes) == 1 and "2027-01-31(일요일)" in notes[0] and "2027-02-01" in notes[0]
    assert "다음 월요일" not in notes[0] and "공휴일이어도" not in notes[0]      # 건너뛴 날을 그대로 적는다
    assert rv["본지"]["열"]["합계"]["전자신고공제"] == 20000          # 기한 안이라 정기신고다
    with pytest.raises(return_values.Unsupported) as e:
        _late("S1", "2027-02-02")
    msg = str(e.value)
    assert "2027-02-01" in msg and "2027-01-31(일요일)" in msg
    assert "알지 못" not in msg and "다음 월요일" not in msg         # 2027년은 공휴일 표에 있다


def test_final_deadline_is_may_31_of_next_year():
    # BF: 2026 양도, 확정신고 기한 2027-05-31(월요일)
    rv = _late("BF", "2027-05-31", 구분="확정")
    assert rv["신고"]["구분"] == "확정" and _weekend_notes(rv) == []
    with pytest.raises(return_values.Unsupported) as e:
        _late("BF", "2027-06-01", 구분="확정")
    assert "2027-05-31" in str(e.value)


def test_sale_date_after_made_date_is_still_a_value_error():
    with pytest.raises(ValueError, match="앞선다"):
        _late("S1", "2026-11-01")


def _permit(permit_date):
    def mutate(f):
        a = f["자산"][0]
        a["토지거래허가대상"] = "예"
        if permit_date:
            a["토지거래허가"] = {"신청일": "2026-10-01", "허가일": permit_date}
    return mutate


def test_permit_zone_uses_permit_date_when_paid_before_permit():
    # S1 양도 2026-11-20, 허가일 2026-12-10(대금 청산이 허가보다 먼저): 기한은 12월 말일부터 2개월 = 2027-02-28(일요일).
    # 다음 날 2027-03-01(월)이 3·1절이라 2027-03-02(화)까지다(공휴일 표)
    rv = _late("S1", "2027-03-01", _permit("2026-12-10"))
    assert any("허가일" in m and "2026-12-10" in m for m in rv["확인사항"]) and len(_weekend_notes(rv)) == 1
    assert "2027-02-28(일요일), 2027-03-01(3·1절)" in _weekend_notes(rv)[0] and "2027-03-02" in _weekend_notes(rv)[0]
    assert _late("S1", "2027-03-02", _permit("2026-12-10"))["신고"]["상세코드"] == "01"      # 3·1절 다음 날은 기한 안이다
    with pytest.raises(return_values.Unsupported) as e:
        _late("S1", "2027-03-03", _permit("2026-12-10"))
    assert "2027-03-02" in str(e.value)


def test_permit_zone_ignores_permit_date_when_permit_came_first():
    # 허가가 대금 청산보다 앞서면 단서가 아니다. 허가일 2026-10-15 는 앞선 달이라 허가일 기준이면 기한이 2026-12-31 이 되어 달라진다.
    # 양도일(2026-11-20) 기준 기한은 2027-02-01 이므로 2027-02-01 은 통과하고 2027-02-02 는 Unsupported 다
    rv = _late("S1", "2027-02-01", _permit("2026-10-15"))
    assert not any("허가일" in m and "기준으로" in m for m in rv["확인사항"])
    with pytest.raises(return_values.Unsupported, match="2027-02-01"):
        _late("S1", "2027-02-02", _permit("2026-10-15"))


def test_permit_zone_without_permit_date_skips_deadline_check():
    rv = _late("S1", "2030-01-01", _permit(None))
    assert any("허가구역 단서에 해당할 수 있어 신고기한을 판정하지 않았다" in m for m in rv["확인사항"])
    assert rv["신고"]["상세코드"] == "01"


def test_non_permit_asset_has_no_skip_note():
    rv = _late("S1", "2027-01-31")
    assert not any("신고기한을 판정하지 않았다" in m for m in rv["확인사항"])


def _sold_on(date_text):
    def mutate(f):
        f["자산"][0]["양도"]["잔금일"] = date_text
    return mutate


def test_preliminary_deadline_on_saturday_moves_to_monday_through_build():
    # 2026-08-20 양도: 기한 말일 2026-10-31(토요일) -> 2026-11-02(월요일)
    m = _sold_on("2026-08-20")
    assert _weekend_notes(_late("S1", "2026-10-31", m)) == []
    for made in ("2026-11-01", "2026-11-02"):
        notes = _weekend_notes(_late("S1", made, m))
        assert len(notes) == 1 and "토요일" in notes[0] and "2026-11-02" in notes[0]
    with pytest.raises(return_values.Unsupported, match="2026-11-02"):
        _late("S1", "2026-11-03", m)


def test_final_deadline_on_sunday_may_31_moves_to_monday_through_build():
    # 2025-11-20 양도의 확정신고: 2026-05-31(일요일) -> 2026-06-01(월요일)
    m = _sold_on("2025-11-20")
    assert _weekend_notes(_late("S1", "2026-05-31", m, 구분="확정")) == []
    notes = _weekend_notes(_late("S1", "2026-06-01", m, 구분="확정"))
    assert len(notes) == 1 and "일요일" in notes[0]
    with pytest.raises(return_values.Unsupported, match="2026-06-01"):
        _late("S1", "2026-06-02", m, 구분="확정")


def test_final_deadline_with_permit_date_in_next_year_counts_from_permit_year():
    # 양도 2026-11-20, 허가일 2027-01-10(허가 전 대금 청산): 확정신고 기한은 허가일이 속한 과세기간의 다음 연도 5월 31일 = 2028-05-31
    rv = _late("S1", "2027-06-15", _permit("2027-01-10"), 구분="확정")
    assert any("허가일(2027-01-10)" in m for m in rv["확인사항"])
    with pytest.raises(return_values.Unsupported, match="2028-05-31"):
        _late("S1", "2028-06-01", _permit("2027-01-10"), 구분="확정")
    with pytest.raises(return_values.Unsupported, match="2027-05-31"):          # 허가 단서가 없으면 양도 연도 기준
        _late("S1", "2027-06-15", None, 구분="확정")


def test_unreadable_permit_date_is_reported_as_unreadable_not_missing():
    def mutate(f):
        a = f["자산"][0]
        a["토지거래허가대상"] = "예"
        a["토지거래허가"] = {"신청일": "2026-10-01", "허가일": "미정"}
    rv = _late("S1", "2030-01-01", mutate)
    notes = [m for m in rv["확인사항"] if "신고기한을 판정하지 않았다" in m]
    assert len(notes) == 1 and "읽지 못해" in notes[0] and "값이 없어" not in notes[0]
    rv = _late("S1", "2030-01-01", _permit(None))
    notes = [m for m in rv["확인사항"] if "신고기한을 판정하지 않았다" in m]
    assert len(notes) == 1 and "값이 없어" in notes[0] and "읽지 못해" not in notes[0]


def test_unsupported_names_the_asset_whose_deadline_was_missed():
    with pytest.raises(return_values.Unsupported, match=r"자산 S1\b"):
        _late("S1", "2027-02-02")
    with pytest.raises(return_values.Unsupported) as e:
        _late("BF", "2027-06-01", 구분="확정")
    assert "자산 B" in str(e.value) or "자산 F" in str(e.value)


# ---- 서식 열 납부 행(계획 2b fix round 1 에서 바꾼 계약) ----
# 열과 소계의 ⑯·⑰·⑱ 은 합산 비교세액이 이길 때만 비운다. 그 밖에는 열과 소계에도 적는다. ⑲·⑳ 은 합계 열에만 적는다.
# 국세청 확정신고 작성 사례 09: 하위 8(열 둘, 이기지 않음)은 ⑰ 납부할 세액을 합계·소계·열에 모두 적었고(1859~1866행),
# 하위 1·2·7(이김)은 합계 열에만, 하위 4·5(열 하나)는 합계와 소계에 적었다.

def _key(name):
    from answer_keys import KEYS
    k = KEYS[name]
    r = engine.calculate(copy.deepcopy(k["facts"]), today="2026-10-11")
    return r, return_values.build(r, k["facts"], filing.load(copy.deepcopy(k["filer"])))


def test_columns_carry_tax_due_when_merged_comparison_does_not_win():
    """09-8 현행 손계산(무신고가산세는 감면 없이 1,467,111 + 120,627 = 1,587,738, 납부지연 292,100 + 19,900):
    1-10 열 7,335,556 + 1,759,211 = 9,094,767, 1-20 열 603,136 + 140,527 = 743,663, 소계 9,838,430."""
    r, rv = _key("09-8")
    cols = rv["본지"]["열"]
    assert (cols["1-10"]["납부할세액"], cols["1-20"]["납부할세액"], cols["국내소계"]["납부할세액"]) == (9094767, 743663, 9838430)
    assert cols["합계"]["납부할세액"] == 9838430
    for name in ("1-10", "1-20", "국내소계"):
        assert cols[name]["기신고세액"] == 0 and cols[name]["분납"] is None and cols[name]["신고기한내납부"] is None, name
    rows = {"%s-%s" % (x["국내외분"], x["세율구분"]): x for x in rv["전자신고"]["세율별"]}
    for label in ("1-10", "1-20"):                         # 열의 ⑱ 은 03 행의 자진납부할세액과 같다
        assert cols[label]["납부할세액"] == rows[label]["자진납부할세액"], label
    loc = rv["지방"]["열"]                                    # 지방 서식 열도 같은 규칙. 733,555 + 60,313 = 793,868
    assert (loc["1-10"]["납부할세액"], loc["1-20"]["납부할세액"], loc["국내소계"]["납부할세액"]) == (733555, 60313, 793868)
    assert loc["1-10"]["신고기한내납부"] is None and loc["합계"]["신고기한내납부"] == 793868


def test_single_column_with_merged_comparison_win_blanks_penalty_and_tax_due_together():
    """세율구분 열이 하나인데 합산 비교세액이 큰 신고서에 가산세가 있으면 열과 소계의 ⑯ 과 ⑱ 을 함께 비운다
    (⑯ 만 비우고 ⑱ 에 가산세가 든 값이 남으면 검산의 ⑱ 산식이 어긋난다). 엔진 결과의 합계만 고친 시험용 값이다."""
    r = engine.calculate(CASES["BF"], today="2026-10-11")
    r = copy.deepcopy(r)
    t = r["계산"]["합계"]
    t["합산비교세액"] = t["산출세액"] = t["호별합산세액"] + 1_000_000
    f = filers.get("BF")
    for aid in f["자산"]:
        f["자산"][aid]["법정동코드"] = "1120011400"
    rv = return_values.build(r, CASES["BF"], filing.load(f))
    cols = rv["본지"]["열"]
    assert [x["표기"] for x in rv["본지"]["세율구분"]] == ["1-10"]
    for name in ("1-10", "국내소계"):
        assert cols[name]["가산세"] is None and cols[name]["납부할세액"] is None and cols[name]["기신고세액"] is None, name
    assert cols["합계"]["가산세"] == 46110480 and cols["합계"]["납부할세액"] == 207274000 + 46110480
    from yangdo import forms_check
    assert forms_check.check(rv, r, facts=CASES["BF"]) == []


# ---- 분납을 신청한 확정신고: 납부지연가산세는 전액을 작성일에 낸 것으로 셌다는 것을 알린다 ----

def test_installment_on_final_return_notes_delay_penalty_on_the_deferred_part():
    r, rv = _rv("BF", 구분="확정", 작성일="2027-05-20", 분납신청=True)
    note = [m for m in rv["확인사항"] if "분납할 세액 103137000원" in m and "납부지연가산세" in m]
    assert len(note) == 1
    assert "작성일 2027-05-20" in note[0] and "더 붙을 수 있다" in note[0] and "세무 전문가" in note[0]
    assert rv["본지"]["열"]["합계"]["분납"] == 103137000 and rv["본지"]["열"]["합계"]["가산세_납부"] == 4855680   # 금액은 그대로
    r, rv = _rv("BF", 구분="확정", 작성일="2027-05-20")
    assert not [m for m in rv["확인사항"] if "더 붙을 수 있다" in m]       # 분납하지 않으면 붙이지 않는다
    r, rv = _rv("S1", 분납신청=True)
    assert not [m for m in rv["확인사항"] if "더 붙을 수 있다" in m]       # 예정신고에는 가산세가 없다


# ---- 공휴일 표를 반영한 기한 문장 ----

def test_deadline_message_in_a_year_the_holiday_table_does_not_cover():
    """공휴일 표에 없는 해(2028년)에 끝나는 기한을 지난 작성일. 그 해의 연휴와 대체공휴일을 모른다고 적는다.
    S1 을 2027-11-20 양도로 옮기면 예정신고 기한은 2028-01-31(월요일)이다."""
    with pytest.raises(return_values.Unsupported) as e:
        _late("S1", "2028-02-01", _sold_on("2027-11-20"))
    msg = str(e.value)
    assert "2028-01-31" in msg and "공휴일 표에 없" in msg and "알지 못" in msg and "달력으로 확인" in msg
