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
    assert e.value.계획 == "미정" and "예정신고" in str(e.value)       # 기신고 합산은 어느 계획에도 들어 있지 않다
    assert "계획 5" not in str(e.value) and "아직 다루지 않는다" in str(e.value)
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


def _dated_expenses():
    """S1 에 필수가 아닌 구분의 지출 둘을 지급일과 함께 더한다.
    인지세(기타부대비용 11601): 부표3 서식에서 지급일 칸이 열려 있고 07 레코드는 필수가 아니라 비운다.
    수익자부담금(28101): 부표3 서식에서 지급일 칸이 음영이고 07 레코드도 비운다."""
    facts = copy.deepcopy(CASES["S1"])
    ex = facts["자산"][0]["필요경비"]
    ex["취득부대"].append({"내용": "인지세", "지급일": "2018-03-20", "금액": 150_000, "증빙종류": "계좌이체", "상대방": "합성은행"})
    ex["기타"] = [{"내용": "수익자부담금", "지급일": "2020-01-10", "금액": 1_000_000, "증빙종류": "계좌이체", "상대방": "합성시청"}]
    r = engine.calculate(facts, today="2026-10-11")
    f = filers.get("S1")
    f["자산"]["S1"]["법정동코드"] = "1120011400"
    f["신고인"]["주소"]["법정동코드"] = "1144010200"
    return r, return_values.build(r, facts, filing.load(f))


def test_years_text_cap_and_mountain_code_come_from_tables(tmp_path):
    """⑨·⑩·⑰ 기간 글자의 「10년 이상」 눈금은 forms/서식판.json, 소재지의 「산」 표기는 코드표 특수지에서 읽는다."""
    import os
    import shutil
    from yangdo import SKILL_DIR
    r, rv = _rv("A")
    assert rv["부표1"][0]["보유기간"] == "10년 이상"               # A 는 2014 취득, 2026 양도(보유 12년)
    forms_dir, efile_dir = tmp_path / "forms", tmp_path / "efile"
    shutil.copytree(os.path.join(SKILL_DIR, "forms"), str(forms_dir))
    shutil.copytree(os.path.join(SKILL_DIR, "efile"), str(efile_dir))
    reg = json.loads((forms_dir / "서식판.json").read_text(encoding="utf-8"))
    assert reg["부표1_기간표기"]["끝햇수"] == 10
    reg["부표1_기간표기"].update(끝햇수=8, 끝="8년 이상")
    (forms_dir / "서식판.json").write_text(json.dumps(reg, ensure_ascii=False), encoding="utf-8")
    codes = json.loads((efile_dir / "codes_c116300.json").read_text(encoding="utf-8"))
    codes["특수지"]["1"]["이름"], codes["특수지"]["2"]["이름"] = codes["특수지"]["2"]["이름"], "산"
    (efile_dir / "codes_c116300.json").write_text(json.dumps(codes, ensure_ascii=False), encoding="utf-8")
    f = filers.get("S1")
    f["자산"]["S1"].update(법정동코드="1120011400", 특수지="2", 번지="12", 호="3")
    f["신고인"]["주소"]["법정동코드"] = "1144010200"
    r = engine.calculate(CASES["S1"], today="2026-10-11")
    b = return_values._Builder(r, CASES["S1"], filing.load(f), None, str(forms_dir), str(efile_dir))
    assert (b.years_text(7), b.years_text(8), b.years_text(12)) == ("7년 이상 8년 미만", "8년 이상", "8년 이상")
    assert "산 12-3" in b.place(CASES["S1"]["자산"][0], f["자산"]["S1"], "1120011400")
    f["자산"]["S1"]["특수지"] = "1"                               # 바꾼 표에서는 1 이 산이 아니다
    assert "산 " not in b.place(CASES["S1"]["자산"][0], f["자산"]["S1"], "1120011400")


def test_acquisition_tax_row_note_cites_no_article_outside_the_ruleset():
    """확인사항 문장에 적는 조문은 규칙세트에 근거가 실린 것뿐이다. 취득세 납세지 조문(지방세법 제8조)은 규칙세트에 없다."""
    r, rv = _rv("S1")
    notes = [m for m in rv["확인사항"] if "취득세(11201) 행 상호" in m]
    assert len(notes) == 1 and "부동산 소재지" in notes[0] and "규격서 p60" in notes[0]
    assert "지방세법" not in notes[0] and "제8조" not in notes[0]
    laws = {g["법령"] + " " + ruleset.label(g["조"]) for v in ruleset.load().data["규칙"].values()
            for e in v["이력"] for g in e["근거"] if g["조"] != "부칙"}
    assert "지방세법 제8조" not in laws


def test_amounts_in_check_items_use_thousands_separators():
    """신고값 확인사항의 금액은 천 단위 쉼표로 적는다(가산세, 분납, 합산 비교세액, 지방소득세 전자신고세액공제)."""
    import re
    raw = re.compile(r"(?<![\d,])\d{4,}원")
    r, rv = _rv("BF", 구분="확정", 작성일="2027-05-20", 분납신청=True)
    text = "\n".join(rv["확인사항"])
    assert "가산세를 뺀 세액 206,274,000원" in text and "분납할 세액 103,137,000원" in text
    assert raw.findall(text) == []
    r, rv = _rv("S1")                                     # 예정신고: 지방소득세 전자신고세액공제 2,000원
    assert any("지방소득세 전자신고세액공제 2,000원" in m for m in rv["확인사항"])
    assert raw.findall("\n".join(rv["확인사항"])) == []
    r, rv = _bf_merged()                                  # 합산 비교세액이 큰 신고서: 281,118,000 과 열 합 278,752,000
    notes = [m for m in rv["확인사항"] if "합산 비교 세액이 커서" in m]
    assert any("합계 산출세액 281,118,000원이 세율구분 열의 합 278,752,000원과 다르다" in m for m in notes)
    assert raw.findall("\n".join(rv["확인사항"])) == []


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


def test_k_heavy_tax_has_exclusion_code():
    r, rv = _rv("K")
    a = rv["부표1"][0]
    assert a["세율구분표기"] == "1-49" and a["장특공코드"] == "03" and a["보유기간"] == ""
    t = rv["본지"]["열"]["1-49"]
    assert t["산출세액"] == 322310000 and t["세율"] == "70%"            # 40% 구간 + 30%


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
    # 지방소득세 신고서 ⑬: 무신고 20,627,400 × 20% = 4,125,480(국세와 같이 감면 없음),
    # 납부지연 20,627,400 × 50 × 22/100,000 = 226,901.4 → 226,901. ⑮ = 20,627,400 + 4,352,381 = 24,979,781
    for name in ("합계", "국내소계", "1-10"):
        loc = rv["지방"]["열"][name]
        assert (loc["가산세_신고"], loc["가산세_납부"], loc["가산세_기타"], loc["가산세"]) == (4125480, 226901, 0, 4352381), name
        assert (loc["전자신고공제"], loc["납부할세액"]) == (0, 24979781), name
    assert rv["지방"]["열"]["합계"]["신고기한내납부"] == 24979781 and rv["지방"]["열"]["1-10"]["신고기한내납부"] is None


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

    one("본지 ⑯", "41,254,800원", "4,855,680원", "46,110,480원")
    # 세액이 달라질 수 있는 해석 둘은 penalty 의 문장을 그대로 옮긴다
    assert one("감면 없이", "감면이 적용되면", "20,627,400원", "세무 전문가") == p["감면안내"]
    one("양도일마다 따로 신고하는 것으로 보면", "36,306,400원", "4,273,250원")
    one("부정행위", "다루지 않는다")
    one("납부일(2027-05-20) 기준")
    one("지방소득세 신고서 ⑬", "4,125,480원", "226,901원", "4,352,381원")
    assert one("두 가지를 가정", "옮기기 전", "원 미만을 버렸다", "위택스 값을 따른다") == p["지방"]["가정안내"]
    # 지방도 감면을 적용하지 않았다. 감면이 적용될 때의 금액은 대안으로 싣는다
    assert one("지방소득세 무신고가산세는 감면 없이", "감면이 적용되면", "2,062,740원", "위택스 값을 따른다") == p["지방"]["감면안내"]
    assert (p["지방"]["무신고"], p["지방"]["납부지연"], p["지방"]["계"]) == (4125480, 226901, 4352381)
    assert p["지방"]["감면적용"] is False and p["지방"]["무신고_감면적용"] == 2062740
    assert not [m for m in notes if "가산세는 계산하지 않아" in m or "가산세가 빠진" in m]
    assert not [m for m in notes if "가산세를 계산하지 않아 0 으로 두었으므로" in m]
    for m in notes:
        assert "\u2014" not in m and not m.rstrip().endswith("?")


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


# ---- 지방소득세 전자신고세액공제(지방세특례제한법 제167조의3①, 같은 법 시행령 제116조의2: 예정신고 2천원) ----


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


def test_permit_zone_without_permit_date_passes_only_inside_the_sale_based_deadline():
    """허가일이 없으면 허가구역 단서(허가일 기준 기한)에 해당하는지 알 수 없다. 허가일 기준 기한은 양도일 기준 기한보다
    이르지 않으므로, 작성일이 양도일 기준 기한 안이면 어느 쪽이든 기한 안이다. 그 기한을 지났으면 판정할 수 없어 신고값을
    만들지 않고 허가일을 받는다. S1 양도 2026-11-20: 양도일 기준 기한 말일 2027-01-31(일요일) → 2027-02-01(월요일)."""
    rv = _late("S1", "2027-02-01", _permit(None))
    assert rv["신고"]["상세코드"] == "01"
    notes = [m for m in rv["확인사항"] if "허가일 값이 없어" in m]
    assert len(notes) == 1 and "양도일 기준 신고기한 2027-02-01" in notes[0] and "어느 쪽이든 신고기한 안" in notes[0]
    with pytest.raises(return_values.Unsupported) as e:
        _late("S1", "2027-02-02", _permit(None))
    msg = str(e.value)
    assert "자산 S1" in msg and "허가일 값이 없어" in msg and "양도일 기준 신고기한 2027-02-01" in msg
    assert "토지거래허가의 허가일" in msg and "YYYY-MM-DD" in msg and e.value.계획 == "없음"
    with pytest.raises(return_values.Unsupported, match="허가일 값이 없어"):       # 기한을 한참 넘긴 작성일도 통과시키지 않는다
        _late("S1", "2030-01-01", _permit(None))


def test_permit_zone_without_permit_date_is_judged_asset_by_asset():
    """허가일이 있는 자산이 기한 안이어도 허가일이 없는 자산은 따로 본다. BF 확정신고: B 는 허가일 2026-12-10(허가 전 대금
    청산, 양도일과 같은 해)이라 허가일 기준이고, F 는 허가 대상인데 허가일이 없어 양도일 기준 기한 2027-05-31 까지만 판정할 수 있다."""
    def mutate(f):
        f["자산"][0].update(토지거래허가대상="예", 토지거래허가={"신청일": "2026-10-01", "허가일": "2026-12-10"})
        f["자산"][1].update(토지거래허가대상="예", 토지거래허가=None)
    assert [a["id"] for a in CASES["BF"]["자산"]] == ["B", "F"]
    assert _late("BF", "2027-05-31", mutate, 구분="확정")["신고"]["구분"] == "확정"
    with pytest.raises(return_values.Unsupported) as e:
        _late("BF", "2027-06-15", mutate, 구분="확정")
    assert "자산 F" in str(e.value) and "허가일 값이 없어" in str(e.value) and "2027-05-31" in str(e.value)


def test_unknown_permit_zone_answer_gets_the_proviso_in_the_deadline_message():
    """토지거래허가대상이 「모름」이면 양도일 기준으로 기한을 본다. 기한을 넘겨 멈출 때 허가구역 단서로 기한이 달라질 수 있다고 알린다."""
    def unknown(f):
        f["자산"][0]["토지거래허가대상"] = "모름"
    assert _late("S1", "2027-02-01", unknown)["신고"]["상세코드"] == "01"
    with pytest.raises(return_values.Unsupported) as e:
        _late("S1", "2027-02-02", unknown)
    msg = str(e.value)
    assert "2027-02-01" in msg and "토지거래허가대상이 「모름」" in msg and "허가일 기준" in msg
    with pytest.raises(return_values.Unsupported) as e:        # 「아니오」인 자산에는 붙이지 않는다
        _late("S1", "2027-02-02")
    assert "모름" not in str(e.value)


def test_non_permit_asset_has_no_skip_note():
    rv = _late("S1", "2027-01-31")
    assert not any("허가구역 단서" in m for m in rv["확인사항"])


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


def test_final_deadline_with_permit_date_in_the_same_year_counts_from_the_permit_date():
    # 양도 2026-11-20, 허가일 2026-12-10(허가 전 대금 청산, 같은 해): 확정신고 기간은 양도일 기준과 같은 2027-05-01~05-31 이다
    rv = _late("S1", "2027-05-31", _permit("2026-12-10"), 구분="확정")
    assert any("허가일(2026-12-10)" in m for m in rv["확인사항"])
    with pytest.raises(return_values.Unsupported, match="2027-05-31"):
        _late("S1", "2027-06-01", _permit("2026-12-10"), 구분="확정")
    with pytest.raises(return_values.Unsupported, match="2027-05-31"):          # 허가 단서가 없어도 같다
        _late("S1", "2027-06-15", None, 구분="확정")


def test_final_return_of_a_permit_asset_whose_permit_year_differs_is_out_of_scope():
    """제110조① 괄호: 허가일이 속하는 과세기간의 다음 연도 5월이 그 자산의 확정신고 기간이다. 허가일과 양도일의 해가 다르면 신고서를 만들지 않는다.
    예정신고는 건드리지 않는다(허가일 기준 예정신고기한은 그대로 세어 만든다)."""
    for made in ("2027-05-20", "2028-05-20"):
        with pytest.raises(return_values.Unsupported) as e:
            _late("S1", made, _permit("2027-01-15"), 구분="확정")
        msg = str(e.value)
        assert e.value.계획 == "미정" and "2028-05-01부터 2028-05-31까지" in msg and "허가일 2027-01-15" in msg
        assert "이 스킬은 이 자산의 확정신고서를 만들지 않는다" in msg and msg.count("해가") == 0 and "2028-05-01부터 2028-05-31까지" in msg and "2026-11-20" in msg
        # 계획 문장은 할 일 앞에 한 번만 온다(make_return 이 끝에 덧붙이지 않게 문장에 넣었다)
        assert msg.count("다룰 계획이 정해지지 않았다") == 1 and msg.index("다룰 계획이 정해지지 않았다") < msg.index("세무 전문가와 확인한다")
    assert _late("S1", "2027-03-01", _permit("2026-12-10"))["신고"]["구분"] == "예정"
    assert _late("S1", "2027-03-01", _permit("2027-01-15"))["신고"]["구분"] == "예정"


def test_final_return_before_the_final_return_period_is_out_of_scope():
    """제110조①: 확정신고는 다음 연도 5월 1일부터 5월 31일까지다. 작성일이 기간 시작보다 앞서면 가산세를 작성일까지의 일수로 세는
    신고서가 틀리므로 만들지 않는다. 2026년 양도, 경계 2027-04-30(막힘), 2027-05-01(통과), 2027-05-31(통과), 2027-06-01(막힘)."""
    for made in ("2026-12-31", "2027-04-30"):
        with pytest.raises(return_values.Unsupported) as e:
            _late("BF", made, None, 구분="확정")
        msg = str(e.value)
        assert e.value.계획 == "없음" and made in msg and "2027-05-01부터 2027-05-31까지" in msg
        assert "신고.작성일을 그 기간 안의 신고·납부 예정일로 고쳐 다시 실행한다" in msg and "납부지연가산세" in msg
    for made in ("2027-05-01", "2027-05-31"):
        assert _late("BF", made, None, 구분="확정")["신고"]["구분"] == "확정"
    with pytest.raises(return_values.Unsupported, match="기한후신고"):
        _late("BF", "2027-06-01", None, 구분="확정")
    assert _late("BF", "2026-12-31", None, 구분="예정")["신고"]["구분"] == "예정"      # 예정신고는 기존대로


def test_unreadable_permit_date_is_reported_as_unreadable_not_missing():
    def mutate(f):
        a = f["자산"][0]
        a["토지거래허가대상"] = "예"
        a["토지거래허가"] = {"신청일": "2026-10-01", "허가일": "미정"}
    rv = _late("S1", "2027-02-01", mutate)                       # 양도일 기준 기한 안이라 통과하고 확인사항으로 남는다
    notes = [m for m in rv["확인사항"] if "허가구역 단서에 해당하는지 알 수 없다" in m]
    assert len(notes) == 1 and "읽지 못해" in notes[0] and "값이 없어" not in notes[0]
    rv = _late("S1", "2027-02-01", _permit(None))
    notes = [m for m in rv["확인사항"] if "허가구역 단서에 해당하는지 알 수 없다" in m]
    assert len(notes) == 1 and "값이 없어" in notes[0] and "읽지 못해" not in notes[0]
    with pytest.raises(return_values.Unsupported) as e:          # 기한을 지났으면 멈추는 문장도 읽지 못한 것과 없는 것을 가른다
        _late("S1", "2027-02-02", mutate)
    assert "읽지 못해" in str(e.value) and "값이 없어" not in str(e.value) and "미정" not in str(e.value)


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
    note = [m for m in rv["확인사항"] if "분납할 세액 103,137,000원" in m and "납부지연가산세" in m]
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
