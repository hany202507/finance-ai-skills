# -*- coding: utf-8 -*-
import ast
import copy
import os
import subprocess
import sys

import pytest

from yangdo import SKILL_DIR, engine, filing, forms_check, return_values, ruleset
from cases import CASES
import filers

_MEMO = {}


def _memo(fn):
    """같은 인자의 (결과, 신고값)을 한 번만 만든다. 시험은 이 값을 바꾸지 않고 deepcopy 해서 쓴다."""
    def wrapper(*args, **kw):
        key = (fn.__name__, args, tuple(sorted(kw.items())))
        if key not in _MEMO:
            _MEMO[key] = fn(*args, **kw)
        return _MEMO[key]
    wrapper.__name__ = fn.__name__
    return wrapper


@_memo
def _pair_cached(name, **over):
    return _build(name, None, **over)


def _pair(name, facts=None, **over):
    if facts is None:
        return _pair_cached(name, **over)
    return _build(name, facts, **over)


def _build(name, facts, **over):
    facts = facts or CASES[name]
    r = engine.calculate(facts, today="2026-10-11")
    f = filers.get(name)
    for aid in f["자산"]:
        f["자산"][aid]["법정동코드"] = "1120011400"
    f["신고인"]["주소"]["법정동코드"] = "1144010200"
    f["신고"].update(over)
    return r, return_values.build(r, facts, filing.load(f))


@_memo
def _bf_merged():
    # 평택 토지를 2025-06-01 취득으로 바꾸면 40% 단기세율 열(1-15)이 생기고 합산 비교세액이 세율구분 열 합보다 크다
    facts = copy.deepcopy(CASES["BF"])
    facts["자산"][1]["취득"]["잔금일"] = "2025-06-01"
    r, rv = _pair("BF", facts)
    assert r["계산"]["합계"]["산출세액"] == r["계산"]["합계"]["합산비교세액"] > r["계산"]["합계"]["호별합산세액"]
    return r, rv


@_memo
def _bf_two_columns():
    # 같은 단기세율 자산을 줄여 열은 둘(1-10, 1-15)인데 합산 비교세액이 지는 경우. 합계 열이 열 합과 같아야 한다
    facts = copy.deepcopy(CASES["BF"])
    a = facts["자산"][1]
    a["취득"]["잔금일"] = "2025-06-01"
    a["전체양도가액"] = 500000000
    a["기준시가"] = {"양도": {"토지": 250000000}, "취득": {"토지": 100000000}}
    r, rv = _pair("BF", facts)
    t = r["계산"]["합계"]
    assert t["산출세액"] == t["호별합산세액"] > t["합산비교세액"] > 0
    assert [x["표기"] for x in rv["본지"]["세율구분"]] == ["1-10", "1-15"]
    return r, rv


@_memo
def _joint_half():
    # 공동소유 1/2 지분 양도. 신고인 JSON 에 전체 면적을 적는다
    facts = copy.deepcopy(CASES["S1"])
    facts["자산"][0]["지분"] = {"구분": "공동", "분자": 1, "분모": 2}
    r = engine.calculate(facts, today="2026-10-11")
    f = filers.get("S1")
    f["자산"]["S1"]["법정동코드"] = "1120011400"
    f["자산"]["S1"]["총면적"] = {"토지": 60.0, "건물": 168.0}
    f["신고인"]["주소"]["법정동코드"] = "1144010200"
    rv = return_values.build(r, facts, filing.load(f))
    assert (rv["부표1"][0]["지분분자"], rv["부표1"][0]["지분분모"], rv["부표1"][0]["양도면적_건물"]) == (1, 2, 84.0)
    return r, rv


@_memo
def _exempt():
    # S1 을 12억원 이하로 양도하면 1세대1주택 비과세가 되어 전액비과세 자산이 된다
    facts = copy.deepcopy(CASES["S1"])
    facts["자산"][0]["전체양도가액"] = 1100000000
    facts["자산"][0]["전체취득가액"] = 600000000
    r = engine.calculate(facts, today="2026-10-11")
    assert r["계산"]["자산"][0]["판정"]["전액비과세"]
    f = filers.get("S1")
    f["자산"]["S1"]["법정동코드"] = "1120011400"
    f["신고인"]["주소"]["법정동코드"] = "1144010200"
    return r, return_values.build(r, facts, filing.load(f))


def _msgs(bad, r):
    return forms_check.check(bad, r)


# ---- 브리프 시험 ----

def test_clean_values_pass():
    for name in ("A", "S1", "BF", "K"):
        r, rv = _pair(name)
        assert forms_check.check(rv, r) == [], name


def test_transfer_schedule1_to_main_is_checked():
    r, rv = _pair("S1")
    bad = copy.deepcopy(rv)
    bad["본지"]["열"]["합계"]["양도소득금액"] += 1
    assert any("부표1" in m and "본지" in m for m in forms_check.check(bad, r))


def test_schedule3_to_schedule1_is_checked():
    r, rv = _pair("S1")
    bad = copy.deepcopy(rv)
    bad["부표3"][0]["취득가액계"] -= 1
    assert forms_check.check(bad, r)


def test_payment_formula_is_checked():
    r, rv = _pair("S1")
    bad = copy.deepcopy(rv)
    bad["본지"]["열"]["합계"]["납부할세액"] += 10
    assert any("⑱" in m for m in forms_check.check(bad, r))


def test_local_tax_base_equals_national():
    r, rv = _pair("S1")
    bad = copy.deepcopy(rv)
    bad["지방"]["열"]["합계"]["과세표준"] += 1
    assert forms_check.check(bad, r)


def test_engine_totals_are_reconciled():
    r, rv = _pair("S1")
    bad = copy.deepcopy(rv)
    bad["부표1"][0]["장특공"] -= 1
    bad["부표1"][0]["양도소득금액"] += 1
    assert any("엔진" in m for m in forms_check.check(bad, r))


# ---- 깨끗한 값이 모두 통과해야 하는 변형 ----

def test_clean_variants_pass():
    for label, (r, rv) in {
        "BF 합산 비교세액이 이김": _bf_merged(),
        "BF 두 열, 합산 비교세액이 짐": _bf_two_columns(),
        "S1 분납": _pair("S1", 분납신청=True),
        "BF 예정(두 열, 공제 있음)": _pair("BF", 구분="예정", 작성일="2026-12-20"),
        "전액비과세 한 건": _exempt(),
        "S1 공동 1/2 지분": _joint_half(),
    }.items():
        assert forms_check.check(rv, r) == [], label


def test_message_shape():
    r, rv = _pair("S1")
    bad = copy.deepcopy(rv)
    bad["본지"]["열"]["합계"]["양도소득금액"] += 1
    assert "부표1 ⑱ 합계 155,893,334 ≠ 본지 ④ 155,893,335" in forms_check.check(bad, r)


# ---- 변조 시험: 칸 하나를 틀리게 하면 그 칸을 짚는다 ----

def _hit(bad, r, *words):
    got = forms_check.check(bad, r)
    assert any(all(w in m for w in words) for m in got), (words, got)
    return got


def test_main_taxable_base_formula():
    r, rv = _pair("S1")
    bad = copy.deepcopy(rv)
    bad["본지"]["열"]["합계"]["기본공제"] += 1
    _hit(bad, r, "본지 합계", "⑧")


def test_payment_net_line():
    r, rv = _pair("S1", 분납신청=True)
    bad = copy.deepcopy(rv)
    t = bad["본지"]["열"]["합계"]
    t["신고기한내납부"] += 1
    _hit(bad, r, "⑳")


def test_installment_limit():
    r, rv = _pair("S1", 분납신청=True)
    bad = copy.deepcopy(rv)
    t = bad["본지"]["열"]["합계"]
    t["분납"] = 30000000
    t["신고기한내납부"] = t["납부할세액"] - t["분납"]          # ⑳ 산식은 맞게 두고 한도만 넘긴다
    got = _hit(bad, r, "⑲")
    assert not any("⑳" in m for m in got)


def test_installment_must_be_requested():
    r, rv = _pair("S1")
    bad = copy.deepcopy(rv)
    t = bad["본지"]["열"]["합계"]
    t["분납"] = 1000000
    t["신고기한내납부"] = t["납부할세액"] - t["분납"]
    _hit(bad, r, "⑲", "신청")


def test_installment_zero_below_threshold():
    r, rv = _pair("A")                                    # 납부할 세액 2,545,000원
    bad = copy.deepcopy(rv)
    t = bad["본지"]["열"]["합계"]
    t["분납"] = 1
    t["신고기한내납부"] = t["납부할세액"] - 1
    bad["신고"]["분납신청"] = True
    _hit(bad, r, "⑲", "한도")


def test_e_filing_credit_cap_and_final_return():
    r, rv = _pair("S1")
    bad = copy.deepcopy(rv)
    for name in ("합계", "국내소계", "1-10"):
        bad["본지"]["열"][name]["전자신고공제"] = 30000
    _hit(bad, r, "⑮", "한도")
    r, rv = _pair("BF")                                   # 확정신고에는 전자신고세액공제가 없다
    bad = copy.deepcopy(rv)
    bad["본지"]["열"]["합계"]["전자신고공제"] = 20000
    bad["본지"]["열"]["합계"]["납부할세액"] -= 20000
    bad["본지"]["열"]["합계"]["신고기한내납부"] -= 20000
    _hit(bad, r, "⑮", "확정")


def test_total_column_payment_cells_must_not_be_blank():
    """합계 열의 납부 칸(본지 ⑰~⑳, 지방 ⑮ 와 납부세액)이 비면 산식을 건너뛰지 말고 실패해야 한다."""
    r, rv = _pair("S1", 분납신청=True)
    for key, no in (("기신고세액", "⑰"), ("납부할세액", "⑱"), ("분납", "⑲"), ("신고기한내납부", "⑳")):
        bad = copy.deepcopy(rv)
        bad["본지"]["열"]["합계"][key] = None
        _hit(bad, r, "본지 합계", no, "비어 있다")
    for key, no in (("납부할세액", "⑮"), ("신고기한내납부", "납부")):
        bad = copy.deepcopy(rv)
        bad["지방"]["열"]["합계"][key] = None
        _hit(bad, r, "지방 합계", no, "비어 있다")
    # 세율구분 열과 국내소계의 납부 칸은 비워 두는 것이 정상이다
    r2, rv2 = _bf_two_columns()
    assert rv2["본지"]["열"]["1-10"]["납부할세액"] is None
    assert forms_check.check(rv2, r2) == []


def test_filing_credit_must_equal_rule_on_provisional_return():
    """예정신고에서는 합계 열 ⑮ 가 min(규칙세트 금액, 산출세액-⑪~⑭) 와 같아야 한다. 빠져도 잡는다."""
    r, rv = _pair("S1")
    assert rv["신고"]["구분"] == "예정" and rv["본지"]["열"]["합계"]["전자신고공제"] == 20000
    for amount in (0, 10000):                              # 빠뜨려도, 한도보다 적게 넣어도 잡는다
        bad = copy.deepcopy(rv)
        for name in ("합계", "국내소계", "1-10"):          # 열 합은 맞게, 산식도 맞게 두고 ⑮ 만 틀린다
            t = bad["본지"]["열"][name]
            diff = 20000 - amount
            t["전자신고공제"] = amount
            if t.get("납부할세액") is not None:
                t["납부할세액"] += diff
            if t.get("신고기한내납부") is not None:
                t["신고기한내납부"] += diff
        got = _hit(bad, r, "본지 합계", "⑮", "한도")
        assert not any("⑱" in m or "⑳" in m for m in got), got


def test_filing_credit_on_final_return_is_zero_without_rule_lookup(monkeypatch):
    r, rv = _pair("BF")
    assert rv["신고"]["구분"] == "확정" and rv["본지"]["열"]["합계"]["전자신고공제"] == 0

    def boom(self, key, on):
        raise AssertionError("확정신고는 전자신고세액공제 규칙 키를 부르지 않는다: %s" % key)
    monkeypatch.setattr(ruleset.Ruleset, "value", boom)
    assert forms_check.check(rv, r) == []


def test_filing_credit_is_capped_by_tax_after_credits():
    """산출세액이 한도보다 작으면 공제는 산출세액까지다(공제 뒤 세액은 음수가 되지 않는다)."""
    r, rv = _pair("S1")
    bad = copy.deepcopy(rv)
    bad["본지"]["열"]["합계"]["감면세액"] = bad["본지"]["열"]["합계"]["산출세액"] - 5000
    _hit(bad, r, "본지 합계", "⑮")                         # 기대값은 min(20,000, 5,000) = 5,000


def test_local_tax_cells_are_checked():
    r, rv = _pair("S1")
    bad = copy.deepcopy(rv)
    bad["지방"]["열"]["1-10"]["산출세액"] += 1
    _hit(bad, r, "지방", "⑦")
    bad = copy.deepcopy(rv)
    bad["지방"]["열"]["합계"]["산출세액"] += 1
    _hit(bad, r, "지방 합계", "⑦", "엔진 지방소득세")


def test_schedule1_row_formulas():
    r, rv = _pair("S1")
    for key, word in (("양도차익", "양도차익"), ("과세양도차익", "⑮"), ("양도소득금액", "⑱")):
        bad = copy.deepcopy(rv)
        bad["부표1"][0][key] += 1
        _hit(bad, r, "부표1", word)


def test_schedule1_total_row():
    r, rv = _pair("BF")
    bad = copy.deepcopy(rv)
    bad["부표1합계"]["양도가액"] += 1
    _hit(bad, r, "부표1 합계")
    bad = copy.deepcopy(rv)
    bad["부표1합계"]["기준시가"]["양도_토지"] += 1
    _hit(bad, r, "부표1 합계", "기준시가")


def test_schedule3_rows_sum_uses_group_not_code_prefix():
    r, rv = _pair("S1")
    rows = rv["부표3"][0]["행"]
    bad = copy.deepcopy(rv)
    bad["부표3"][0]["행"][1]["금액"] += 1               # 취득세 행
    got = _hit(bad, r, "부표3", "⑤")
    assert not any("⑬" in m and "행 합" in m for m in got)
    bad = copy.deepcopy(rv)
    bad["부표3"][0]["행"][5]["금액"] += 1               # 양도비 행
    _hit(bad, r, "부표3", "⑬")
    # 행의 구분을 취득가액 묶음에서 기타필요경비 묶음으로 옮기면 계가 어긋난다
    bad = copy.deepcopy(rv)
    bad["부표3"][0]["행"][2]["구분코드"] = "260"
    bad["부표3"][0]["행"][2]["전자코드"] = "26001"
    _hit(bad, r, "부표3", "⑤")
    assert len(rows) == 6


def test_schedule3_unknown_code():
    r, rv = _pair("S1")
    bad = copy.deepcopy(rv)
    bad["부표3"][0]["행"][0]["전자코드"] = "99999"
    _hit(bad, r, "부표3", "99999")
    bad = copy.deepcopy(rv)
    bad["부표3"][0]["행"][0]["구분코드"] = "112"
    _hit(bad, r, "부표3", "11101")


def test_schedule3_to_schedule1_both_totals():
    r, rv = _pair("S1")
    bad = copy.deepcopy(rv)
    bad["부표1"][0]["취득가액"] += 1
    bad["부표1"][0]["양도차익"] -= 1
    bad["부표1"][0]["과세양도차익"] -= 1
    bad["부표1"][0]["양도소득금액"] -= 1
    _hit(bad, r, "부표3", "⑫")
    bad = copy.deepcopy(rv)
    bad["부표1"][0]["기타필요경비"] += 1
    bad["부표1"][0]["양도차익"] -= 1
    bad["부표1"][0]["과세양도차익"] -= 1
    bad["부표1"][0]["양도소득금액"] -= 1
    _hit(bad, r, "부표3", "⑭")


def test_actual_cost_asset_needs_schedule3():
    r, rv = _pair("S1")
    bad = copy.deepcopy(rv)
    bad["부표3"] = []
    _hit(bad, r, "실지거래가액", "부표3")


def test_converted_cost_asset_has_no_schedule3_and_passes():
    r, rv = _pair("BF")
    assert [x["자산"] for x in rv["부표3"]] == ["B"]
    assert forms_check.check(rv, r) == []


def test_column_sum_equals_total_column():
    r, rv = _bf_two_columns()
    for key, word in (("과세표준", "⑧"), ("산출세액", "⑩")):
        bad = copy.deepcopy(rv)
        bad["본지"]["열"]["1-15"][key] += 1
        _hit(bad, r, "본지", word)
    bad = copy.deepcopy(rv)
    bad["본지"]["열"]["합계"]["산출세액"] += 1
    bad["본지"]["열"]["합계"]["납부할세액"] += 1
    bad["본지"]["열"]["합계"]["신고기한내납부"] += 1
    _hit(bad, r, "본지 합계", "⑩", "열 합")


def test_local_column_sum_and_engine():
    r, rv = _bf_two_columns()
    bad = copy.deepcopy(rv)
    bad["지방"]["열"]["1-10"]["산출세액"] += 1
    _hit(bad, r, "지방", "⑦")
    bad = copy.deepcopy(rv)
    bad["지방"]["열"]["합계"]["산출세액"] += 1
    bad["지방"]["열"]["합계"]["납부할세액"] += 1
    bad["지방"]["열"]["합계"]["신고기한내납부"] += 1
    _hit(bad, r, "지방", "엔진")


def test_local_payment_formula_and_base_per_column():
    r, rv = _pair("S1")
    bad = copy.deepcopy(rv)
    bad["지방"]["열"]["합계"]["납부할세액"] += 1
    _hit(bad, r, "지방", "⑮")
    bad = copy.deepcopy(rv)
    bad["지방"]["열"]["1-10"]["과세표준"] += 1
    _hit(bad, r, "지방", "1-10", "본지")


def test_merged_comparison_total_may_differ_from_column_sum():
    r, rv = _bf_merged()
    cols = rv["본지"]["열"]
    assert cols["합계"]["산출세액"] != cols["1-10"]["산출세액"] + cols["1-15"]["산출세액"]
    assert forms_check.check(rv, r) == []
    # 비교세액은 엔진과 맞아야 한다
    bad = copy.deepcopy(rv)
    bad["본지"]["열"]["합계"]["산출세액"] += 1
    bad["본지"]["열"]["합계"]["납부할세액"] += 1
    bad["본지"]["열"]["합계"]["신고기한내납부"] += 1
    _hit(bad, r, "본지 합계", "⑩", "엔진")
    # 국내소계는 이때도 열 합이다
    bad = copy.deepcopy(rv)
    bad["본지"]["열"]["국내소계"]["산출세액"] += 1
    _hit(bad, r, "국내소계", "⑩")
    # 지방도 같다
    bad = copy.deepcopy(rv)
    bad["지방"]["열"]["국내소계"]["산출세액"] += 1
    _hit(bad, r, "지방", "국내소계", "⑦")


def test_blank_columns_are_not_summed():
    r, rv = _bf_merged()
    cols = rv["본지"]["열"]
    assert cols["1-10"]["납부할세액"] is None and cols["합계"]["납부할세액"]
    assert forms_check.check(rv, r) == []


def test_column_label_mismatch():
    r, rv = _bf_two_columns()
    bad = copy.deepcopy(rv)
    bad["부표1"][0]["세율구분표기"] = "1-99"
    _hit(bad, r, "부표1", "1-99")
    bad = copy.deepcopy(rv)
    del bad["본지"]["열"]["1-15"]
    _hit(bad, r, "본지", "1-15")


def test_schedule1_assets_match_engine():
    r, rv = _pair("BF")
    bad = copy.deepcopy(rv)
    bad["부표1"].pop()
    _hit(bad, r, "엔진", "자산")
    bad = copy.deepcopy(rv)
    bad["부표1"][0]["양도일"] = "2026-11-21"
    _hit(bad, r, "부표1", "양도일", "엔진")
    bad = copy.deepcopy(rv)
    bad["부표1"][0]["양도가액"] += 1
    _hit(bad, r, "엔진", "양도가액")


def test_engine_acquisition_plus_expense():
    r, rv = _pair("S1")
    bad = copy.deepcopy(rv)
    a = bad["부표1"][0]
    a["취득가액"] += 1
    a["기타필요경비"] -= 1                                 # 합은 같고 가름만 어긋난다
    got = _hit(bad, r, "부표3")
    assert not any("엔진" in m and "취득가액" in m for m in got)
    bad = copy.deepcopy(rv)
    bad["부표3"][0]["행"][0]["금액"] += 5                 # 부표3 과 부표1 을 함께 5원 올렸다 → 엔진 합과 어긋난다
    bad["부표3"][0]["취득가액계"] += 5
    bad["부표1"][0]["취득가액"] += 5
    bad["부표1"][0]["양도차익"] -= 5
    bad["부표1"][0]["과세양도차익"] -= 5
    bad["부표1"][0]["비과세양도차익"] -= 0
    bad["부표1"][0]["양도소득금액"] -= 5
    _hit(bad, r, "엔진", "취득가액")


def test_engine_column_and_total_amounts():
    r, rv = _bf_two_columns()
    bad = copy.deepcopy(rv)
    bad["본지"]["열"]["합계"]["과세표준"] += 1
    _hit(bad, r, "엔진", "과세표준")
    bad = copy.deepcopy(rv)
    bad["지방"]["열"]["합계"]["산출세액"] += 1
    bad["지방"]["열"]["합계"]["납부할세액"] += 1
    bad["지방"]["열"]["합계"]["신고기한내납부"] += 1
    _hit(bad, r, "엔진", "지방")
    bad = copy.deepcopy(rv)
    bad["본지"]["열"]["1-15"]["기본공제"] += 1
    _hit(bad, r, "엔진", "기본공제")


def test_exempt_asset_rows():
    r, rv = _exempt()
    assert rv["부표1"][0]["양도차익"] is None and rv["본지"]["열"]["합계"]["산출세액"] == 0
    assert forms_check.check(rv, r) == []
    bad = copy.deepcopy(rv)
    bad["부표1"][0]["양도소득금액"] = 1
    assert forms_check.check(bad, r)


def test_form_codes_match_engine():
    r, rv = _pair("S1")
    for key, value, word in (("자산종류", "3", "③"), ("장특공코드", "02", "⑯"), ("취득가액종류", "환산취득가액", "취득가액종류")):
        bad = copy.deepcopy(rv)
        bad["부표1"][0][key] = value
        _hit(bad, r, "부표1", word, "엔진")


def test_share_and_area_follow_the_engine():
    r, rv = _joint_half()
    bad = copy.deepcopy(rv)
    bad["부표1"][0]["지분분모"] = 3                       # 양도가액은 엔진 값 그대로인데 지분이 다르다
    _hit(bad, r, "부표1", "지분", "엔진 양도가액")
    bad = copy.deepcopy(rv)
    bad["부표1"][0]["양도면적_토지"] = 60.0                # 총면적 60 × 지분 1/2 = 30
    _hit(bad, r, "부표1", "⑦ 양도면적", "토지")
    bad = copy.deepcopy(rv)
    bad["부표1"][0]["총면적_건물"] = 84.0
    _hit(bad, r, "부표1", "⑦ 양도면적", "건물")
    bad = copy.deepcopy(rv)
    bad["부표1"][0]["양도면적_토지"] = 30.0004             # 소수 셋째 자리 아래 차이는 같게 본다
    assert forms_check.check(bad, r) == []


def test_schedule3_row_name_and_label_notation():
    r, rv = _pair("S1")
    bad = copy.deepcopy(rv)
    bad["부표3"][0]["행"][0]["구분"] = "취득세"
    _hit(bad, r, "부표3", "구분 이름")
    bad = copy.deepcopy(rv)
    bad["본지"]["세율구분"][0]["표기"] = "1-11"
    _hit(bad, r, "본지", "세율구분 표기")


# ---- 필수 칸과 인적사항 ----

def test_required_blanks_are_reported_without_values():
    r, rv = _pair("S1")
    for path, word in ((("신고인", "성명"), "성명"), (("신고인", "주민등록번호"), "주민등록번호")):
        bad = copy.deepcopy(rv)
        bad[path[0]][path[1]] = ""
        _hit(bad, r, word, "비어")
    bad = copy.deepcopy(rv)
    bad["부표1"][0]["소재지"] = ""
    _hit(bad, r, "소재지", "비어")
    bad = copy.deepcopy(rv)
    bad["양수인"] = []
    _hit(bad, r, "양수인")
    bad = copy.deepcopy(rv)
    bad["양수인"][0]["성명"] = ""
    _hit(bad, r, "양수인", "성명")
    bad = copy.deepcopy(rv)
    bad["양수인"][0]["지분분자"] = 1
    bad["양수인"][0]["지분분모"] = 2
    _hit(bad, r, "양수인", "지분")


def test_messages_never_carry_personal_values():
    r, rv = _pair("S1")
    secrets = [rv["신고인"]["성명"], rv["신고인"]["주민등록번호"], rv["양수인"][0]["성명"], rv["양수인"][0]["번호"],
               rv["부표1"][0]["소재지"], rv["부표3"][0]["행"][3]["상호"]]
    bad = copy.deepcopy(rv)
    bad["신고인"]["성명"] = ""
    bad["신고인"]["주민등록번호"] = ""
    bad["양수인"][0]["성명"] = ""
    bad["양수인"][0]["번호"] = ""
    bad["부표1"][0]["소재지"] = ""
    bad["본지"]["열"]["합계"]["양도소득금액"] += 1
    bad["부표3"][0]["취득가액계"] -= 1
    bad["부표1"][0]["취득일"] = "2018-03-16"
    text = "\n".join(forms_check.check(bad, r))
    assert text
    for s in secrets:
        assert s and s not in text


# ---- 금액 칸 전부가 어딘가에서 검산된다 ----

def _int_cells(o, path=()):
    if isinstance(o, dict):
        for k, v in o.items():
            yield from _int_cells(v, path + (k,))
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from _int_cells(v, path + (i,))
    elif isinstance(o, int) and not isinstance(o, bool):
        yield path


# 감면은 이번 신고 범위가 아니라 항상 0 이고, 서식에 그대로 적을 뿐 다른 칸과 관계가 없다
UNCHECKED_CELLS = {"감면율"}


@pytest.mark.parametrize("label,make", [
    ("S1 분납", lambda: _pair("S1", 분납신청=True)),
    ("BF 두 열", _bf_two_columns),
    ("BF 합산 비교세액이 이김", _bf_merged),
    ("S1 공동 1/2", _joint_half),
])
def test_every_integer_cell_is_checked(label, make, monkeypatch):
    """숫자 칸을 하나씩 1 올리면 검산이 실패해야 한다. 어느 칸도 검산에서 빠지지 않게 하려는 시험이다."""
    real, loaded = ruleset.load, {}

    def load_once(rules_dir=None):                       # 검산 천 번에 규칙세트를 천 번 읽지 않게 한다
        if rules_dir not in loaded:
            loaded[rules_dir] = real(rules_dir)
        return loaded[rules_dir]
    monkeypatch.setattr(ruleset, "load", load_once)
    r, rv = make()
    assert forms_check.check(rv, r) == []
    missed = []
    for sec in ("본지", "부표1", "부표1합계", "부표3", "지방"):
        for path in _int_cells(rv[sec]):
            if path[-1] in UNCHECKED_CELLS:
                continue
            bad = copy.deepcopy(rv)
            node = bad[sec]
            for k in path[:-1]:
                node = node[k]
            node[path[-1]] += 1
            if not forms_check.check(bad, r):
                missed.append((sec,) + path)
    assert missed == [], label


# ---- 합성 사례 전부에서 깨끗한 값은 통과한다 ----

def _synthetic(name, kind="확정"):
    facts = CASES[name]
    ids = [a["id"] for a in facts["자산"]]
    f = filers.filer(kind, "2027-05-20", {i: dict(filers.lot("100"), 법정동코드="1120011400") for i in ids},
                     [filers.buyer(i, serial=str(34567 + k)) for k, i in enumerate(ids)])
    f["신고인"]["주소"]["법정동코드"] = "1144010200"
    r = engine.calculate(facts, today="2026-10-11")
    if r["상태"] != "완료":
        return r, None
    return r, return_values.build(r, facts, filing.load(f))


def test_every_finished_case_passes():
    done = 0
    for name in CASES:
        r, rv = _synthetic(name)
        if rv is None:
            continue
        assert forms_check.check(rv, r) == [], name
        done += 1
    assert done >= 15                                    # 전액비과세·단기·중과·미등기·두 열 사례를 포함한다


# ---- 문장 모양 ----

def test_messages_follow_the_writing_rules():
    r, rv = _bf_two_columns()
    bad = copy.deepcopy(rv)
    bad["본지"]["열"]["합계"]["양도소득금액"] += 1
    bad["본지"]["열"]["1-15"]["납부할세액"] = 5
    bad["부표3"][0]["취득가액계"] -= 1
    bad["지방"]["열"]["합계"]["산출세액"] += 1
    bad["신고인"]["성명"] = ""
    msgs = forms_check.check(bad, r)
    assert len(msgs) >= 5
    for m in msgs:
        assert chr(0x2014) not in m and not m.rstrip().endswith("?"), m
        assert m == m.strip() and chr(10) not in m, m


# ---- 구조와 독립성 ----

def test_unfinished_result_is_reported():
    r, rv = _pair("S1")
    got = forms_check.check(rv, dict(r, 상태="질문", 계산=None))
    assert got and any("엔진" in m for m in got)


def test_missing_section_is_reported_not_raised():
    r, rv = _pair("S1")
    bad = copy.deepcopy(rv)
    del bad["본지"]["열"]["합계"]
    assert forms_check.check(bad, r)
    bad = copy.deepcopy(rv)
    del bad["지방"]
    assert forms_check.check(bad, r)
    bad = copy.deepcopy(rv)
    del bad["부표3"]
    assert forms_check.check(bad, r)


def test_does_not_import_generator_or_renderer():
    src = open(os.path.join(SKILL_DIR, "yangdo", "forms_check.py"), encoding="utf-8").read()
    tree = ast.parse(src)
    names = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module} | \
            {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names}
    banned = {"return_values", "forms", "forms_pdf"}
    assert not {x.split(".")[-1] for x in names} & banned
    assert not imported & banned
    for bad in ("import return_values", "import forms_pdf", "from . import forms", "importlib"):
        assert bad not in src


def test_import_does_not_load_generator_modules():
    code = ("import sys, yangdo.forms_check; "
            "print(','.join(m for m in ('yangdo.return_values', 'yangdo.forms', 'yangdo.forms_pdf') if m in sys.modules))")
    p = subprocess.run([sys.executable, "-c", code], cwd=SKILL_DIR, capture_output=True, timeout=120)
    assert p.returncode == 0, p.stderr.decode("utf-8", "replace")
    assert p.stdout.decode("ascii").strip() == ""
