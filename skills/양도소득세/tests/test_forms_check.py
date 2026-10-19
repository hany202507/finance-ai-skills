# -*- coding: utf-8 -*-
import ast
import copy
import os
import subprocess
import sys

import pytest

from yangdo import SKILL_DIR, edition, engine, filing, forms_check, return_values, ruleset
from cases import CASES, F자산
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


_FACTS = {}        # id(엔진 결과) → 사실관계. 확정신고 검산은 사실관계를 받아야 한다(_MEMO 가 결과를 붙들어 id 가 바뀌지 않는다)


def _fc(rv, r, **kw):
    """forms_check.check 를 그 결과를 만든 사실관계와 함께 부른다."""
    kw.setdefault("facts", _FACTS.get(id(r)))
    return forms_check.check(rv, r, **kw)


def _build(name, facts, **over):
    facts = facts or CASES[name]
    r = engine.calculate(facts, today="2026-10-11")
    _FACTS[id(r)] = facts
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
    _FACTS[id(r)] = facts
    rv = return_values.build(r, facts, filing.load(f))
    assert (rv["부표1"][0]["지분분자"], rv["부표1"][0]["지분분모"], rv["부표1"][0]["양도면적_건물"]) == (1, 2, 84.0)
    return r, rv


@_memo
def _mixed():
    # 전액 비과세 주택 G 와 과세 토지 F 를 같은 달에 양도했다. 신고서에는 F 만 들어간다(전액 비과세 자산은 넣지 않는다)
    facts = copy.deepcopy(CASES["G"])
    facts["자산"].append(copy.deepcopy(F자산))
    r = engine.calculate(facts, today="2026-10-11")
    assert [(x["id"], x["판정"]["전액비과세"]) for x in r["계산"]["자산"]] == [("G", True), ("F", False)]
    _FACTS[id(r)] = facts
    f = filers.filer("예정", "2026-12-20", {i: dict(filers.lot("100"), 법정동코드="1120011400") for i in ("G", "F")},
                     [filers.buyer("G"), filers.buyer("F", "박합성", "45678")])
    f["신고인"]["주소"]["법정동코드"] = "1144010200"
    return r, return_values.build(r, facts, filing.load(f))


def _msgs(bad, r):
    return _fc(bad, r)


def _form_only(msgs):
    """서식 값끼리의 검산 문장만. 본지만 바꾼 변조는 신고값 전자신고 절과도 어긋나 그 대조 문장이 함께 나온다."""
    return [m for m in msgs if not m.startswith("전자신고")]


# ---- 브리프 시험 ----

def test_clean_values_pass():
    for name in ("A", "S1", "BF", "K"):
        r, rv = _pair(name)
        assert _fc(rv, r) == [], name


def test_transfer_schedule1_to_main_is_checked():
    r, rv = _pair("S1")
    bad = copy.deepcopy(rv)
    bad["본지"]["열"]["합계"]["양도소득금액"] += 1
    assert any("부표1" in m and "본지" in m for m in _fc(bad, r))


def test_schedule3_to_schedule1_is_checked():
    r, rv = _pair("S1")
    bad = copy.deepcopy(rv)
    bad["부표3"][0]["취득가액계"] -= 1
    assert _fc(bad, r)


def test_payment_formula_is_checked():
    r, rv = _pair("S1")
    bad = copy.deepcopy(rv)
    bad["본지"]["열"]["합계"]["납부할세액"] += 10
    # ⑱ 만 보면 ⑳ 산식 문장(⑱-⑲)과 전자신고 대조 문장으로도 통과한다. ⑱ 산식 문장을 짚는다
    assert any("본지 합계 ⑱ 납부할 세액" in m and "⑩-⑪-⑫-⑬-⑭-⑮+⑯-⑰" in m for m in _fc(bad, r))


def test_local_tax_base_equals_national():
    r, rv = _pair("S1")
    bad = copy.deepcopy(rv)
    bad["지방"]["열"]["합계"]["과세표준"] += 1
    assert _fc(bad, r)


def test_engine_totals_are_reconciled():
    r, rv = _pair("S1")
    bad = copy.deepcopy(rv)
    bad["부표1"][0]["장특공"] -= 1
    bad["부표1"][0]["양도소득금액"] += 1
    assert any("엔진" in m for m in _fc(bad, r))


# ---- 깨끗한 값이 모두 통과해야 하는 변형 ----

def test_clean_variants_pass():
    for label, (r, rv) in {
        "BF 합산 비교세액이 이김": _bf_merged(),
        "BF 두 열, 합산 비교세액이 짐": _bf_two_columns(),
        "S1 분납": _pair("S1", 분납신청=True),
        "BF 예정(두 열, 공제 있음)": _pair("BF", 구분="예정", 작성일="2026-12-20"),
        "전액 비과세 자산과 과세 자산": _mixed(),
        "S1 공동 1/2 지분": _joint_half(),
    }.items():
        assert _fc(rv, r) == [], label


def test_message_shape():
    r, rv = _pair("S1")
    bad = copy.deepcopy(rv)
    bad["본지"]["열"]["합계"]["양도소득금액"] += 1
    assert "부표1 ⑱ 합계 155,893,334 ≠ 본지 ④ 155,893,335" in _fc(bad, r)


# ---- 변조 시험: 칸 하나를 틀리게 하면 그 칸을 짚는다 ----

def _hit(bad, r, *words):
    got = _fc(bad, r)
    assert any(all(w in m for w in words) for m in got), (words, got)
    return got


def test_main_taxable_base_formula():
    r, rv = _pair("S1")
    bad = copy.deepcopy(rv)
    bad["본지"]["열"]["합계"]["기본공제"] += 1
    _hit(bad, r, "본지 합계 ⑧ 과세표준", "④+⑤-⑥-⑦")


def test_payment_net_line():
    r, rv = _pair("S1", 분납신청=True)
    bad = copy.deepcopy(rv)
    t = bad["본지"]["열"]["합계"]
    t["신고기한내납부"] += 1
    _hit(bad, r, "본지 합계 ⑳ 납부세액", "⑱-⑲")            # ⑳ 만 보면 전자신고 대조 문장으로도 통과한다


def test_installment_limit():
    r, rv = _pair("S1", 분납신청=True)
    bad = copy.deepcopy(rv)
    t = bad["본지"]["열"]["합계"]
    t["분납"] = 30000000
    t["신고기한내납부"] = t["납부할세액"] - t["분납"]          # ⑳ 산식은 맞게 두고 한도만 넘긴다
    # 손계산: ⑱ 38,329,466 은 2천만원을 넘어 한도가 50% = 19,164,733. ⑲ 만 보면 전자신고 대조 문장으로도 통과한다
    got = _hit(bad, r, "본지 합계 ⑲ 분납할 세액 30,000,000 이 한도 19,164,733 를 넘는다")
    assert not any("⑳" in m for m in _form_only(got))


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
    # 세율구분 열과 국내소계는 ⑲ 분납·⑳ 납부세액을 비워 두는 것이 정상이다. ⑱ 은 합산 비교세액이 이길 때만 비운다
    r2, rv2 = _bf_two_columns()
    assert rv2["본지"]["열"]["1-10"]["납부할세액"] is not None and rv2["본지"]["열"]["1-10"]["신고기한내납부"] is None
    assert _fc(rv2, r2) == []
    for name, shown in (("1-10", "본지 1-10 열"), ("국내소계", "본지 국내소계")):
        bad = copy.deepcopy(rv2)
        bad["본지"]["열"][name]["납부할세액"] = None
        _hit(bad, r2, shown, "⑱", "비어 있다")
    bad = copy.deepcopy(rv2)
    bad["지방"]["열"]["1-15"]["납부할세액"] = None
    _hit(bad, r2, "지방 1-15 열", "⑮", "비어 있다")
    r3, rv3 = _bf_merged()                                # 합산 비교세액이 이긴 신고서는 열과 소계를 비운다
    assert rv3["본지"]["열"]["1-10"]["납부할세액"] is None and _fc(rv3, r3) == []


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
        assert not any("⑱" in m or "⑳" in m for m in _form_only(got)), got


def test_filing_credit_on_final_return_is_zero_without_rule_lookup(monkeypatch):
    r, rv = _pair("BF")
    assert rv["신고"]["구분"] == "확정" and rv["본지"]["열"]["합계"]["전자신고공제"] == 0

    real = ruleset.Ruleset.value

    def boom(self, key, on):
        if "전자신고세액공제" in key:                      # 국세·지방 모두 확정신고 키가 없다. 가산세 규칙은 읽는다
            raise AssertionError("확정신고는 전자신고세액공제 규칙 키를 부르지 않는다: %s" % key)
        return real(self, key, on)
    monkeypatch.setattr(ruleset.Ruleset, "value", boom)
    assert _fc(rv, r) == []


def test_filing_credit_is_capped_by_tax_after_credits():
    """산출세액이 한도보다 작으면 공제는 산출세액까지다(공제 뒤 세액은 음수가 되지 않는다)."""
    r, rv = _pair("S1")
    bad = copy.deepcopy(rv)
    bad["본지"]["열"]["합계"]["감면세액"] = bad["본지"]["열"]["합계"]["산출세액"] - 5000
    # 기대값은 min(20,000, 5,000) = 5,000. 「본지 합계」와 「⑮」만 보면 ⑱ 산식 문장(⑩-⑪-...-⑮+⑯-⑰)으로도 통과한다
    _hit(bad, r, "본지 합계 ⑮ 전자신고세액공제 20,000 ≠ 5,000")


def test_local_tax_cells_are_checked():
    r, rv = _pair("S1")
    bad = copy.deepcopy(rv)
    bad["지방"]["열"]["1-10"]["산출세액"] += 1
    _hit(bad, r, "지방 국내소계 ⑦ 산출세액", "세율구분 열 합")
    bad = copy.deepcopy(rv)
    bad["지방"]["열"]["합계"]["산출세액"] += 1
    _hit(bad, r, "지방 합계", "⑦", "엔진 지방소득세")


def test_schedule1_row_formulas():
    r, rv = _pair("S1")
    # 란 번호만 보면 합계 행·엔진 대조·전자신고 대조 문장으로도 통과한다. 행 산식 문장(오른쪽의 식)을 짚는다
    for key, word, formula in (("양도차익", "부표1 S1 양도차익", "⑪-⑫-⑬-⑭"),
                               ("과세양도차익", "부표1 S1 ⑮ 과세대상양도차익", "양도차익-비과세양도차익"),
                               ("양도소득금액", "부표1 S1 ⑱ 양도소득금액", "⑮-⑯")):
        bad = copy.deepcopy(rv)
        bad["부표1"][0][key] += 1
        _hit(bad, r, word, "≠ " + formula)


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
    got = _hit(bad, r, "부표3 S1 ⑤ 계", "행 합")
    assert not any("⑬" in m and "행 합" in m for m in got)
    bad = copy.deepcopy(rv)
    bad["부표3"][0]["행"][5]["금액"] += 1               # 양도비 행
    _hit(bad, r, "부표3 S1 ⑬ 기타 필요경비 계", "행 합")
    # 행의 구분을 취득가액 묶음에서 기타필요경비 묶음으로 옮기면 계가 어긋난다
    bad = copy.deepcopy(rv)
    bad["부표3"][0]["행"][2]["구분코드"] = "260"
    bad["부표3"][0]["행"][2]["전자코드"] = "26001"
    _hit(bad, r, "부표3 S1 ⑤ 계", "행 합")
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
    assert _fc(rv, r) == []


def test_column_sum_equals_total_column():
    r, rv = _bf_two_columns()
    for key, word in (("과세표준", "⑧"), ("산출세액", "⑩")):
        bad = copy.deepcopy(rv)
        bad["본지"]["열"]["1-15"][key] += 1
        _hit(bad, r, "본지 국내소계", word, "세율구분 열 합")   # 란 번호만 보면 열의 산식·엔진 대조 문장으로도 통과한다
        _hit(bad, r, "본지 합계", word, "세율구분 열 합")
    bad = copy.deepcopy(rv)
    bad["본지"]["열"]["합계"]["산출세액"] += 1
    bad["본지"]["열"]["합계"]["납부할세액"] += 1
    bad["본지"]["열"]["합계"]["신고기한내납부"] += 1
    _hit(bad, r, "본지 합계", "⑩", "열 합")


def test_local_column_sum_and_engine():
    r, rv = _bf_two_columns()
    bad = copy.deepcopy(rv)
    bad["지방"]["열"]["1-10"]["산출세액"] += 1
    _hit(bad, r, "지방 합계 ⑦ 산출세액", "세율구분 열 합")
    _hit(bad, r, "지방 세율구분 열 ⑦ 합", "엔진 호별합산")
    bad = copy.deepcopy(rv)
    bad["지방"]["열"]["합계"]["산출세액"] += 1
    bad["지방"]["열"]["합계"]["납부할세액"] += 1
    bad["지방"]["열"]["합계"]["신고기한내납부"] += 1
    _hit(bad, r, "지방 합계 ⑦ 산출세액", "엔진 지방소득세")


def test_local_tax_is_reconciled_with_the_engine_column_by_column():
    """지방 세율구분 열의 산출세액은 열마다 다시 계산한 값과 같아야 한다. 두 열 사이에서 옮기면(합은 그대로) 열 합 검사와
    엔진 호별합산 대조를 모두 지나가므로 열마다 본다.
    손계산: 1-10 열 과세표준 163,400,000 → 163,400,000 × 3.8% - 1,994,000 = 4,215,200.
            1-15 열 과세표준 294,500,000 × 4%(2년 미만 보유) = 11,780,000"""
    r, rv = _bf_two_columns()
    cols = rv["지방"]["열"]
    assert (cols["1-10"]["산출세액"], cols["1-15"]["산출세액"]) == (4215200, 11780000)
    bad = copy.deepcopy(rv)
    for name, by in (("1-10", -1000), ("1-15", 1000)):    # 열의 산식(⑮ = ⑦ - ... + ⑬)은 맞게 둔다
        bad["지방"]["열"][name]["산출세액"] += by
        bad["지방"]["열"][name]["납부할세액"] += by
    got = _fc(bad, r)
    assert got == ["지방 1-10 열 ⑦ 산출세액 4,214,200 ≠ 엔진 과세표준에 지방소득세 세율을 적용한 값 4,215,200",
                   "지방 1-15 열 ⑦ 산출세액 11,781,000 ≠ 엔진 과세표준에 지방소득세 세율을 적용한 값 11,780,000"], got
    # 지방소득세 합산 비교세액이 이긴 신고서도 열은 세율구분별 세액이다(합계만 비교세액)
    r3, rv3 = _bf_merged()
    assert (rv3["지방"]["열"]["1-10"]["산출세액"], rv3["지방"]["열"]["1-15"]["산출세액"]) == (4215200, 23660000)
    bad = copy.deepcopy(rv3)
    bad["지방"]["열"]["1-10"]["산출세액"] -= 1000
    bad["지방"]["열"]["1-15"]["산출세액"] += 1000
    _hit(bad, r3, "지방 1-15 열 ⑦ 산출세액 23,661,000", "지방소득세 세율을 적용한 값 23,660,000")


def test_local_payment_formula_and_base_per_column():
    r, rv = _pair("S1")
    bad = copy.deepcopy(rv)
    bad["지방"]["열"]["합계"]["납부할세액"] += 1
    _hit(bad, r, "지방 합계 ⑮ 납부할 총세액", "⑦-⑧-⑨-⑩-⑪-⑫+⑬-⑭")   # ⑮ 만 보면 신고기한내 납부 문장으로도 통과한다
    bad = copy.deepcopy(rv)
    bad["지방"]["열"]["1-10"]["과세표준"] += 1
    _hit(bad, r, "지방", "1-10", "본지")


def test_merged_comparison_total_may_differ_from_column_sum():
    r, rv = _bf_merged()
    cols = rv["본지"]["열"]
    assert cols["합계"]["산출세액"] != cols["1-10"]["산출세액"] + cols["1-15"]["산출세액"]
    assert _fc(rv, r) == []
    # 비교세액은 엔진과 맞아야 한다
    bad = copy.deepcopy(rv)
    bad["본지"]["열"]["합계"]["산출세액"] += 1
    bad["본지"]["열"]["합계"]["납부할세액"] += 1
    bad["본지"]["열"]["합계"]["신고기한내납부"] += 1
    _hit(bad, r, "본지 합계", "⑩", "엔진")
    # 국내소계는 이때도 열 합이다
    bad = copy.deepcopy(rv)
    bad["본지"]["열"]["국내소계"]["산출세액"] += 1
    _hit(bad, r, "본지 국내소계 ⑩ 산출세액", "세율구분 열 합")
    _hit(bad, r, "본지 국내소계 ⑩ 산출세액", "엔진 세율별 합")
    # 지방도 같다
    bad = copy.deepcopy(rv)
    bad["지방"]["열"]["국내소계"]["산출세액"] += 1
    _hit(bad, r, "지방 국내소계 ⑦ 산출세액", "세율구분 열 합")


def test_blank_columns_are_not_summed():
    r, rv = _bf_merged()
    cols = rv["본지"]["열"]
    assert cols["1-10"]["납부할세액"] is None and cols["합계"]["납부할세액"]
    assert _fc(rv, r) == []


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
    """전액 비과세 자산은 부표1 에 없다. 본지 합계는 과세 자산 F 의 값이다(산출세액 139,380,000). 부표1 에 넣으면 걸린다."""
    r, rv = _mixed()
    assert [x["자산"] for x in rv["부표1"]] == ["F"] and rv["본지"]["열"]["합계"]["산출세액"] == 139380000
    assert _fc(rv, r) == []
    bad = copy.deepcopy(rv)
    bad["부표1"].insert(0, dict(copy.deepcopy(rv["부표1"][0]), 자산="G", 과세양도차익=0, 장특공=0, 양도소득금액=0))
    _hit(bad, r, "부표1", "전액 비과세 자산 G")
    _hit(bad, r, "부표1 자산 [G, F]", "엔진 자산 [F]")


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
    assert _fc(bad, r) == []


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
    text = "\n".join(_fc(bad, r))
    assert text
    for s in secrets:
        assert s and s not in text


# ---- 시험이 없던 실패 문장 ----

def test_local_rate_labels_must_match_main():
    r, rv = _bf_two_columns()
    bad = copy.deepcopy(rv)
    bad["지방"]["세율구분"] = bad["지방"]["세율구분"][:1]
    assert "지방 세율구분 열 1-10 이 본지 1-10, 1-15 와 다르다" in _fc(bad, r)
    bad = copy.deepcopy(rv)
    bad["지방"]["세율구분"] = []
    assert "지방 세율구분 열 없음 이 본지 1-10, 1-15 와 다르다" in _fc(bad, r)


def test_unreadable_ruleset_is_reported_once(tmp_path):
    """규칙세트를 읽지 못하면 한도 검사를 건너뛰지 않고 실패로 알린다(빈 폴더에는 기준정보판.json 이 없다)."""
    r, rv = _pair("S1", 분납신청=True)
    got = _fc(rv, r, rules_dir=str(tmp_path))
    assert got == ["규칙세트를 읽지 못해 분납 한도와 전자신고세액공제 한도를 검사하지 못했다"]


def test_missing_rule_value_is_reported(monkeypatch):
    r, rv = _pair("S1", 분납신청=True)
    real = ruleset.Ruleset.value

    def value(self, key, on):
        if key == "분납.상한율":
            raise ruleset.RuleError("없음")
        return real(self, key, on)
    monkeypatch.setattr(ruleset.Ruleset, "value", value)
    assert _fc(rv, r) == ["규칙세트에 분납.상한율 의 2026-11-20 값이 없어 한도를 검사하지 못했다"]


def test_filing_kind_must_be_provisional_or_final():
    r, rv = _pair("S1")
    bad = copy.deepcopy(rv)
    bad["신고"]["구분"] = "기한후"
    _hit(bad, r, "신고 구분 기한후 이 예정이나 확정이 아니다")


def test_blank_address_buyer_mismatch_and_duplicate_schedule3():
    r, rv = _pair("BF")
    bad = copy.deepcopy(rv)
    for k in ("시도", "시군구", "읍면동"):
        bad["신고인"]["주소"][k] = " "
    assert _fc(bad, r) == ["본지 ① 신고인 주소가 비어 있다"]
    bad = copy.deepcopy(rv)
    bad["신고인"]["주소"] = None
    assert _fc(bad, r) == ["본지 ① 신고인 주소가 비어 있다"]
    bad = copy.deepcopy(rv)
    bad["양수인"][1]["자산"] = "X"                          # F 를 산 양수인이 없는 자산 X 를 가리킨다
    assert _fc(bad, r) == ["본지 ② 양수인의 자산 X 가 부표1 에 없다", "본지 ② 양수인이 없다(자산 F)"]
    bad = copy.deepcopy(rv)
    bad["부표3"].append(copy.deepcopy(bad["부표3"][0]))
    assert _fc(bad, r) == ["부표3 이 자산 B 에 둘 이상 있다"]
    bad = copy.deepcopy(rv)
    bad["부표3"][0]["자산"] = "X"
    got = _fc(bad, r)
    assert "부표3 의 자산 X 가 부표1 에 없다" in got and "부표1 B ⑫ 취득가액이 실지거래가액인데 부표3 이 없다" in got


def test_no_taxable_asset_sentence_names_the_assets():
    r = engine.calculate(CASES["G"], today="2026-10-11")
    made = "신고서를" if edition.PUBLIC else "신고서와 전자신고 파일을"     # 공개본에는 전자신고 파일이 없다
    assert forms_check.check({}, r, facts=CASES["G"]) == [
        "과세 자산이 없다. 전액 비과세 자산(G)뿐인 건은 %s 만들지 않는다" % made]


def test_schedule3_row_with_an_unknown_group_is_reported(tmp_path):
    """코드표의 묶음 이름이 취득가액·기타필요경비로 시작하지 않는 구분은 어느 계에 넣을지 몰라 실패로 알린다."""
    import json
    import shutil
    r, rv = _pair("S1")
    efile_dir = tmp_path / "efile"
    shutil.copytree(os.path.join(SKILL_DIR, "efile"), str(efile_dir))
    path = efile_dir / "codes_c116300.json"
    codes = json.loads(path.read_text(encoding="utf-8"))
    codes["필요경비구분"]["취득세"]["묶음"] = "모르는 묶음"
    path.write_text(json.dumps(codes, ensure_ascii=False), encoding="utf-8")
    assert "부표3 S1 전자코드 11201 의 묶음을 알 수 없다" in _fc(rv, r, efile_dir=str(efile_dir))


def test_step_that_cannot_run_names_the_exception_type():
    """검사 단계가 신고값의 모양 때문에 돌지 못하면 단계 이름과 예외 형 이름을 적는다. 값은 싣지 않는다."""
    r, rv = _pair("S1")
    bad = copy.deepcopy(rv)
    del bad["부표1합계"]
    assert "부표1 검사를 하지 못했다. 신고값에 필요한 칸이 없거나 모양이 다르다(KeyError 부표1합계)" in _fc(bad, r)
    bad = copy.deepcopy(rv)
    bad["본지"]["열"]["합계"]["산출세액"] = "삼천만원"
    got = [m for m in _fc(bad, r) if "검사를 하지 못했다" in m]
    assert got and all("ValueError)" in m and "삼천만원" not in m for m in got), got
    # 신고값의 모양과 상관없는 예외(프로그램 오류)는 삼키지 않는다
    chk = forms_check._Check(copy.deepcopy(rv), r, None, None, None)
    chk.schedule1 = lambda: 1 // 0
    with pytest.raises(ZeroDivisionError):
        chk.run()


# ---- 규칙세트를 읽는 날짜와 판 ----

def test_reference_dates_are_reconciled_with_the_engine():
    """분납 한도는 신고 절 양도일자로 규칙을 읽는다. 그 날짜가 엔진 결과의 마지막 양도일과 다르면 알린다."""
    r, rv = _pair("BF")                                   # 양도일 F 2026-11-01, B 2026-11-20
    bad = copy.deepcopy(rv)
    bad["신고"]["양도일자"] = "20261101"
    assert _fc(bad, r) == ["신고 절 양도일자 2026-11-01 ≠ 엔진 과세 자산의 마지막 양도일 2026-11-20"]
    r, rv = _pair("S1")
    bad = copy.deepcopy(rv)
    bad["신고"]["작성일"] = "20261119"
    _hit(bad, r, "신고 절 작성일 2026-11-19 이 엔진 과세 자산의 마지막 양도일 2026-11-20 보다 앞선다")
    bad = copy.deepcopy(rv)
    bad["판"]["기준정보"] = "0" * 16
    assert _fc(bad, r) == ["신고값 판의 기준정보 0000000000000000 ≠ 엔진 결과의 기준정보 판 %s" % r["기준정보"]["판"]]
    r, rv = _mixed()                                      # 전액 비과세 G 의 양도일은 기준일이 아니다
    assert _fc(rv, r) == []


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
    assert _fc(rv, r) == []
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
            if not _fc(bad, r):
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
    _FACTS[id(r)] = facts
    if r["상태"] != "완료":
        return r, None
    try:
        return r, return_values.build(r, facts, filing.load(f))
    except return_values.NoTaxableAsset:               # 전액 비과세 자산뿐인 사례는 신고값을 만들지 않는다
        return r, None


def test_every_finished_case_passes():
    done, no_taxable = 0, []
    for name in CASES:
        r, rv = _synthetic(name)
        if rv is None:
            if r["상태"] == "완료":
                no_taxable.append(name)
                assert any("과세 자산이 없다" in m for m in forms_check.check({}, r, facts=CASES[name])), name
            continue
        assert _fc(rv, r) == [], name
        done += 1
    assert no_taxable == ["G", "G3", "I"]                # 전액 비과세 자산뿐인 사례
    assert done >= 15                                    # 단기·중과·미등기·두 열 사례를 포함한다


# ---- 문장 모양 ----

def test_messages_follow_the_writing_rules():
    r, rv = _bf_two_columns()
    bad = copy.deepcopy(rv)
    bad["본지"]["열"]["합계"]["양도소득금액"] += 1
    bad["본지"]["열"]["1-15"]["납부할세액"] = 5
    bad["부표3"][0]["취득가액계"] -= 1
    bad["지방"]["열"]["합계"]["산출세액"] += 1
    bad["신고인"]["성명"] = ""
    msgs = _fc(bad, r)
    assert len(msgs) >= 5
    for m in msgs:
        assert chr(0x2014) not in m and not m.rstrip().endswith("?"), m
        assert m == m.strip() and chr(10) not in m, m


# ---- 구조와 독립성 ----

def test_unfinished_result_is_reported():
    r, rv = _pair("S1")
    got = _fc(rv, dict(r, 상태="질문", 계산=None))
    assert got and any("엔진" in m for m in got)


def test_missing_section_is_reported_not_raised():
    r, rv = _pair("S1")
    bad = copy.deepcopy(rv)
    del bad["본지"]["열"]["합계"]
    assert _fc(bad, r)
    bad = copy.deepcopy(rv)
    del bad["지방"]
    assert _fc(bad, r)
    bad = copy.deepcopy(rv)
    del bad["부표3"]
    assert _fc(bad, r)


def test_does_not_import_generator_or_renderer():
    src = open(os.path.join(SKILL_DIR, "yangdo", "forms_check.py"), encoding="utf-8").read()
    tree = ast.parse(src)
    names = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module} | \
            {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names}
    banned = {"return_values", "forms", "forms_pdf", "penalty"}
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


# ---- 전자신고 절(03·05 레코드 값)과 본지·부표1 대조 ----
# 신고값의 「전자신고」 절은 생성기가 본지와 다른 경로로 만든다. 서식 값만 검산하면 이 절의 세액이 틀려도 지나간다.

def _rate_rows(rv):
    return {(x["국내외분"], x["세율구분"]): x for x in rv["전자신고"]["세율별"]}


def test_efile_section_check_does_not_import_the_file_generator():
    """서식 검산은 신고값 생성기, 가산세 계산, 서식 렌더러를 부르지 않는다(같은 코드를 쓰면 같이 틀린다)."""
    src = open(os.path.join(SKILL_DIR, "yangdo", "forms_check.py"), encoding="utf-8").read()
    tree = ast.parse(src)
    names = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module} | \
            {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names}
    banned = {"return_values", "forms", "forms_pdf", "penalty"}
    modules = ("yangdo.return_values", "yangdo.penalty")
    assert not {x.split(".")[-1] for x in names} & banned and not imported & banned
    code = ("import sys, yangdo.forms_check; "
            "print(','.join(m for m in %r if m in sys.modules))" % (modules,))
    p = subprocess.run([sys.executable, "-c", code], cwd=SKILL_DIR, capture_output=True, timeout=120)
    assert p.returncode == 0 and p.stdout.decode("ascii").strip() == ""


# ---- ⑯ 가산세: 규칙세트 값과 엔진 결과·사실관계로 다시 계산해 대조한다(계획 2b G1b) ----
# 신고값의 가산세는 yangdo.penalty 가 계산한다. 서식 검산은 그 모듈을 부르지 않고 같은 값을 따로 계산한다.
# BF 손계산: 예정신고 세액 206,274,000, 107일, 무신고 206,274,000 × 20% = 41,254,800(감면 없음), 납부지연 4,855,680, 계 46,110,480

def _bump_penalty(rv, col, key, by):
    """본지 한 열의 가산세 한 줄을 바꾸고 그 열의 계와 납부 칸을 산식에 맞게 함께 바꾼다(다른 열은 그대로)."""
    bad = copy.deepcopy(rv)
    c = bad["본지"]["열"][col]
    c[key] += by
    c["가산세"] += by
    for k in ("납부할세액", "신고기한내납부"):
        if c.get(k) is not None:
            c[k] += by
    return bad


def test_penalty_cells_are_recalculated():
    r, rv = _pair("BF")
    assert rv["본지"]["열"]["합계"]["가산세"] == 46110480
    assert _fc(rv, r, facts=CASES["BF"]) == []
    for col, shown in (("합계", "본지 합계"), ("국내소계", "본지 국내소계"), ("1-10", "본지 1-10 열")):
        for key, name, want in (("가산세_신고", "무(과소)신고", "41,254,800"), ("가산세_납부", "납부지연", "4,855,680")):
            msgs = _fc(_bump_penalty(rv, col, key, 10), r, facts=CASES["BF"])
            hit = [m for m in msgs if shown in m and "⑯" in m and name in m and "다시 계산" in m and want in m]
            assert hit, (col, key, msgs)
    bad = _bump_penalty(rv, "합계", "가산세_기장", 1000)
    _hit(bad, r, "본지 합계", "⑯", "기장불성실")


def test_penalty_recalculation_works_without_the_penalty_module(monkeypatch):
    from yangdo import penalty
    r, rv = _pair("BF")

    def boom(*a, **k):
        raise AssertionError("서식 검산은 penalty 를 부르지 않는다")
    for name in ("final_return", "cases", "amounts", "days"):
        monkeypatch.setattr(penalty, name, boom)
    assert _fc(rv, r, facts=CASES["BF"]) == []
    assert _fc(_bump_penalty(rv, "합계", "가산세_납부", 10), r, facts=CASES["BF"])


def test_penalty_two_cases_two_columns_from_answer_key():
    """정답지 09-8: 건 둘(A·B 2026-09-13, C 2026-10-13), 열 둘. 무신고는 감면 없이 7,335,556 × 20% = 1,467,111 과
    603,136 × 20% = 120,627. 1-10 열 1,467,111 · 292,100, 1-20 열 120,627 · 19,900."""
    from answer_keys import KEYS
    k = KEYS["09-8"]
    r = engine.calculate(copy.deepcopy(k["facts"]), today="2026-10-11")
    _FACTS[id(r)] = k["facts"]
    rv = return_values.build(r, k["facts"], filing.load(copy.deepcopy(k["filer"])))
    assert _fc(rv, r, facts=k["facts"]) == []
    for col, key, name, want in (("1-10", "가산세_신고", "무(과소)신고", "1,467,111"), ("1-10", "가산세_납부", "납부지연", "292,100"),
                                 ("1-20", "가산세_신고", "무(과소)신고", "120,627"), ("1-20", "가산세_납부", "납부지연", "19,900"),
                                 ("합계", "가산세_신고", "무(과소)신고", "1,587,738"), ("합계", "가산세_납부", "납부지연", "312,000")):
        msgs = _fc(_bump_penalty(rv, col, key, 1), r, facts=k["facts"])
        shown = "본지 %s" % (col if col == "합계" else col + " 열")
        assert any(shown in m and "⑯" in m and name in m and want in m for m in msgs), (col, key, msgs)
    # 열의 가산세를 비워 두면 합 검사가 건너뛰므로 따로 잡는다
    bad = copy.deepcopy(rv)
    for key in ("가산세", "가산세_신고", "가산세_납부"):
        bad["본지"]["열"]["1-20"][key] = None
    _hit(bad, r, "본지 1-20 열", "⑯", "비어 있다")


def test_penalty_that_cannot_be_determined_must_be_zero_and_flagged():
    """한 건 안에서 세율이 다른 자산의 합산 비교세액이 이기면 다시 계산할 수 없다. 가산세 칸은 0 이어야 하고,
    신고값이 「가산세」 절에 계산하지 못했다고 적어야 한다(진입점이 그 표시로 신고서를 만들지 않는다)."""
    r, rv = _bf_merged()
    assert rv["가산세"]["계산"] is False and _fc(rv, r) == []
    bad = _bump_penalty(rv, "합계", "가산세_신고", 1000)
    _hit(bad, r, "본지 합계", "⑯", "정할 수 없")
    bad = copy.deepcopy(rv)
    bad["가산세"] = {"계산": True, "무신고": 0, "납부지연": 0, "계": 0}
    _hit(bad, r, "가산세 절", "정할 수 없")


def test_penalty_flag_must_not_hide_a_computable_penalty():
    """신고값이 계산하지 못했다고 적었는데 다시 계산하면 금액이 나오는 경우."""
    r, rv = _pair("BF")
    bad = copy.deepcopy(rv)
    bad["가산세"] = {"계산": False, "사유": "시험", "계획": "없음"}
    _hit(bad, r, "가산세 절", "46,110,480")


def test_penalty_permit_date_comes_from_facts():
    """허가 전에 대금을 청산한 허가구역 토지는 허가일이 속한 달부터 기한을 센다. 사실관계를 주어야 같은 값이 나온다.
    F 양도 2026-11-01, 허가 2026-12-10: 건이 둘이 된다(B 11월, F 12월 기준)."""
    facts = copy.deepcopy(CASES["BF"])
    facts["자산"][1].update(토지거래허가대상="예", 토지거래허가={"신청일": "2026-10-01", "허가일": "2026-12-10"})
    r, rv = _pair("BF", facts)
    assert len(rv["가산세"]["건"]) == 2
    assert _fc(rv, r, facts=facts) == []
    without = dict(facts, 자산=[dict(a, 토지거래허가대상="아니오") for a in facts["자산"]])
    assert any("⑯" in m for m in _fc(rv, r, facts=without))            # 허가일을 보지 않으면 양도일 기준이라 값이 다르다


def test_final_return_check_needs_facts():
    """확정신고 검산을 사실관계 없이 부르면 한 문장으로 실패한다(가산세를 다시 계산할 때 허가구역 토지의 허가일을 읽는다)."""
    r, rv = _pair("BF")
    msgs = forms_check.check(rv, r)
    assert len(msgs) == 1 and "확정신고" in msgs[0] and "사실관계" in msgs[0]
    r, rv = _pair("S1")                                              # 예정신고는 사실관계 없이도 검산한다
    assert forms_check.check(rv, r) == []


def test_penalty_follows_ruleset_values(tmp_path):
    """율은 규칙세트에서 읽는다. 율을 바꾼 규칙세트 사본으로 검산하면 지금 값이 틀린 값이 된다.
    무신고 206,274,000 × 40% = 82,509,600(감면율은 지금 문언에서 쓰지 않는다)."""
    import json
    import shutil
    d = str(tmp_path / "rules")
    os.makedirs(os.path.join(d, "고시"))
    for name in ruleset.EDITION_FILES:
        shutil.copy(os.path.join(SKILL_DIR, "rules", name), os.path.join(d, name))
    path = os.path.join(d, "ruleset.json")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    for key, value in (("가산세.무신고.율", "0.40"), ("가산세.무신고.확정신고감면율", "0.25")):
        for e in data["규칙"][key]["이력"]:
            e["값"] = value
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    ruleset.write_edition(d, data["확인일"])
    r, rv = _pair("BF")
    msgs = _fc(rv, r, rules_dir=d, facts=CASES["BF"])
    assert any("본지 합계" in m and "무(과소)신고" in m and "82,509,600" in m for m in msgs), msgs


# ---- 지방소득세 ⑫ 전자신고세액공제: 예정신고는 규칙세트 금액, 확정신고는 0 ----

def test_local_filing_credit_must_equal_rule_on_provisional_return():
    r, rv = _pair("S1")
    assert rv["지방"]["열"]["합계"]["전자신고공제"] == 2000
    for amount in (0, 1000, 20000):
        bad = copy.deepcopy(rv)
        for name in ("합계", "국내소계", "1-10"):
            t = bad["지방"]["열"][name]
            diff = 2000 - amount
            t["전자신고공제"] = amount
            for k in ("납부할세액", "신고기한내납부"):
                if t.get(k) is not None:
                    t[k] += diff
        _hit(bad, r, "지방 합계", "⑫", "2,000")


def test_local_filing_credit_on_final_return_is_zero():
    r, rv = _pair("BF")
    bad = copy.deepcopy(rv)
    for name in ("합계", "국내소계", "1-10"):
        t = bad["지방"]["열"][name]
        t["전자신고공제"] = 2000
        for k in ("납부할세액", "신고기한내납부"):
            if t.get(k) is not None:
                t[k] -= 2000
    _hit(bad, r, "지방 합계", "⑫", "확정")


# ---- 지방소득세 ⑬ 가산세: 본지와 같이 따로 다시 계산해 대조한다(계획 2b fix round 2) ----
# BF 손계산: 지방 예정신고 세액 20,627,400, 납부기한 2027-03-31, 50일. 무신고 2,062,740, 납부지연 226,901, 계 2,289,641

def _bump_local(rv, col, key, by):
    bad = copy.deepcopy(rv)
    c = bad["지방"]["열"][col]
    c[key] += by
    c["가산세"] += by
    for k in ("납부할세액", "신고기한내납부"):
        if c.get(k) is not None:
            c[k] += by
    return bad


def test_local_penalty_cells_are_recalculated():
    r, rv = _pair("BF")
    # BF 지방: 무신고 20,627,400 × 20% = 4,125,480(감면 없음), 납부지연 226,901, 계 4,352,381
    assert rv["지방"]["열"]["합계"]["가산세"] == 4352381 and _fc(rv, r) == []
    for col, shown in (("합계", "지방 합계"), ("국내소계", "지방 국내소계"), ("1-10", "지방 1-10 열")):
        for key, name, want in (("가산세_신고", "무(과소)신고", "4,125,480"), ("가산세_납부", "납부지연", "226,901")):
            msgs = _fc(_bump_local(rv, col, key, 1), r)
            assert any(shown in m and "⑬" in m and name in m and "다시 계산" in m and want in m for m in msgs), (col, key, msgs)
    _hit(_bump_local(rv, "합계", "가산세_기타", 500), r, "지방 합계", "⑬", "기타")
    bad = copy.deepcopy(rv)
    bad["가산세"]["지방"].update(납부지연=226900, 계=4352380)
    _hit(bad, r, "가산세 절", "지방", "226,901")


def test_local_penalty_with_relief_is_caught():
    """지방 무신고가산세에 감면 50% 를 넣은 값(2,062,740)은 다시 계산한 값 4,125,480 과 달라 걸린다. 국세와 같이 감면을 넣지 않는다."""
    r, rv = _pair("BF")
    bad = copy.deepcopy(rv)
    for col in ("합계", "국내소계", "1-10"):
        c = bad["지방"]["열"][col]
        c.update(가산세_신고=2062740, 가산세=2289641)
        for k in ("납부할세액", "신고기한내납부"):
            if c.get(k) is not None:
                c[k] = 22917041
    bad["가산세"]["지방"].update(무신고=2062740, 계=2289641)
    msgs = _fc(bad, r)
    assert any("지방 합계" in m and "⑬" in m and "무(과소)신고" in m and "2,062,740 ≠ 다시 계산한 값 4,125,480" in m for m in msgs), msgs
    assert any("가산세 절 지방" in m and "4,125,480" in m for m in msgs), msgs


def test_penalty_recalculation_does_not_read_the_relief_wording(tmp_path):
    """검산의 가산세 다시 계산도 감면 조문 발췌의 글자를 보지 않는다. 발췌를 옛 문구로 바꾼 규칙세트로도 BF 신고값(무신고 41,254,800,
    지방 4,125,480)이 통과하고, 감면을 넣은 국세 값 20,627,400 은 걸린다."""
    import json
    import shutil
    from yangdo import RULES_DIR
    d = str(tmp_path / "rules")
    os.makedirs(os.path.join(d, "고시"))
    for name in ruleset.EDITION_FILES:
        shutil.copy(os.path.join(RULES_DIR, name), os.path.join(d, name))
    path = os.path.join(d, "ruleset.json")
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    for key in ("가산세.무신고.확정신고감면율", "지방.가산세.무신고.확정신고감면율"):
        for e in data["규칙"][key]["이력"]:
            for g in e["근거"]:
                g["발췌"] = [x.replace("제45조의3에 따른 기한 후 신고를 한 경우", "과세표준신고를 한 경우") for x in g["발췌"]]
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False)
    ruleset.write_edition(d, data["확인일"])
    r = engine.calculate(CASES["BF"], today="2026-10-11", rules_dir=d)
    f = filers.get("BF")
    for aid in f["자산"]:
        f["자산"][aid]["법정동코드"] = "1120011400"
    rv = return_values.build(r, CASES["BF"], filing.load(f), rules_dir=d)
    t = rv["본지"]["열"]["합계"]
    assert (t["가산세_신고"], rv["지방"]["열"]["합계"]["가산세_신고"]) == (41254800, 4125480)
    assert forms_check.check(rv, r, rules_dir=d, facts=CASES["BF"]) == []
    bad = copy.deepcopy(rv)
    for col in ("합계", "국내소계", "1-10"):
        c = bad["본지"]["열"][col]
        c.update(가산세_신고=20627400, 가산세=20627400 + c["가산세_납부"])
    msgs = forms_check.check(bad, r, rules_dir=d, facts=CASES["BF"])
    assert any("본지 합계" in m and "⑯" in m and "20,627,400 ≠ 다시 계산한 값 41,254,800" in m for m in msgs), msgs
    assert not hasattr(forms_check, "PENALTY_LATE_RETURN_WORDING")


def test_local_penalty_left_at_zero_is_caught():
    """지방 가산세를 모두 0 으로 두고 납부할 총세액도 그에 맞춘 신고값(가산세를 계산하지 않던 때의 값)."""
    r, rv = _pair("BF")
    bad = copy.deepcopy(rv)
    for col in ("합계", "국내소계", "1-10"):
        c = bad["지방"]["열"][col]
        c.update(가산세_신고=0, 가산세_납부=0, 가산세=0)
        for k in ("납부할세액", "신고기한내납부"):
            if c.get(k) is not None:
                c[k] = 20627400
    bad["가산세"]["지방"].update(무신고=0, 납부지연=0, 계=0)
    msgs = _fc(bad, r)
    assert any("지방 합계" in m and "⑬" in m and "무(과소)신고" in m and "0 ≠ 다시 계산한 값 4,125,480" in m for m in msgs), msgs


def test_local_penalty_two_columns_from_answer_key():
    """09-8: 1-10 열 146,711 · 19,204, 1-20 열 12,062 · 1,194(tests/answer_keys.py 현행지방가산세)."""
    from answer_keys import KEYS
    k = KEYS["09-8"]
    r = engine.calculate(copy.deepcopy(k["facts"]), today="2026-10-11")
    _FACTS[id(r)] = k["facts"]
    rv = return_values.build(r, k["facts"], filing.load(copy.deepcopy(k["filer"])))
    assert _fc(rv, r) == []
    for col, key, name, want in (("1-10", "가산세_신고", "무(과소)신고", "146,711"), ("1-10", "가산세_납부", "납부지연", "19,204"),
                                 ("1-20", "가산세_신고", "무(과소)신고", "12,062"), ("1-20", "가산세_납부", "납부지연", "1,194"),
                                 ("합계", "가산세_납부", "납부지연", "20,398")):
        msgs = _fc(_bump_local(rv, col, key, 1), r)
        shown = "지방 %s" % (col if col == "합계" else col + " 열")
        assert any(shown in m and "⑬" in m and name in m and want in m for m in msgs), (col, key, msgs)


def test_local_penalty_on_preliminary_return_must_be_zero():
    r, rv = _pair("S1")
    _hit(_bump_local(rv, "합계", "가산세_납부", 100), r, "지방 합계", "⑬", "예정신고")


# ---- 본지와 지방 서식의 합산 비교세액 판정이 엇갈리는 경우 ----
# 지방소득세 세율은 국세의 10분의 1 이지만 세액을 따로 원 미만 버림하므로, 합산 비교세액과 세율별 세액의 합이 몇 원 차이일 때
# 본지는 합산 비교세액이 크고 지방은 크지 않을 수(또는 그 반대일 수) 있다. 본지 열은 본지 판정으로, 지방 열은 지방 판정으로 비운다.
# 두 사례 모두 토지 F(2026-10-01 양도, 보유 2년 미만 40%)와 주택 B(2026-11-20 양도, 누진세율)이고 납부일은 2027-05-20 이다.
# 국세 납부기한과 일수: F 건 2026-12-31, 139일. B 건 2027-02-01, 107일.
# 지방 납부기한과 일수: F 건 2027-02-28(일) → 03-01(3·1절) → 03-02, 79일. B 건 2027-03-31, 50일.

_KEEP = []        # 시험이 끝날 때까지 결과를 붙들어 _FACTS 의 id 가 다시 쓰이지 않게 한다


def _two_months(price_f, price_b):
    facts = copy.deepcopy(CASES["BF"])
    assert [x["id"] for x in facts["자산"]] == ["B", "F"]
    facts["자산"][0]["전체양도가액"] = price_b
    facts["자산"][1]["취득"]["잔금일"] = "2025-06-01"
    facts["자산"][1]["양도"]["잔금일"] = "2026-10-01"
    facts["자산"][1]["전체양도가액"] = price_f
    r = engine.calculate(facts, today="2026-10-11")
    _FACTS[id(r)] = facts
    _KEEP.append(r)
    f = filers.get("BF")
    for aid in f["자산"]:
        f["자산"][aid]["법정동코드"] = "1120011400"
    return r, return_values.build(r, facts, filing.load(f))


def test_national_merged_comparison_wins_but_local_does_not():
    """국세는 합산 비교세액이 5원 크고 지방소득세는 같다. 본지는 가산세와 납부할 세액을 합계 열에만, 지방 서식은 열과 소계에도 적는다.
      F 과세표준 = 802,833,750 - 환산취득가액 321,133,500(× 200/500) - 개산공제 6,000,000(200,000,000 × 3%) - 기본공제 2,500,000
                 = 473,200,250. 세액 189,280,100, 지방 18,928,010
      B 과세표준 163,400,000. 세액 37,060,000 + 13,400,000 × 38% = 42,152,000, 지방 4,215,200
      국세: 세율별 합 231,432,100 < 합산 비교 174,060,000 + 136,600,250 × 42% = 231,432,105
      지방: 세율별 합 23,143,210 = 합산 비교 17,406,000 + 136,600,250 × 4.2% = 23,143,210.5 → 23,143,210
      국세 가산세: 무신고 231,432,100 × 20% = 46,286,420. 납부지연 189,280,100 × 139 × 22/100,000 = 5,788,185.458 → 5,788,180,
        42,152,000 × 107 × 22/100,000 = 992,258.08 → 992,250. 계 53,066,850. ⑱ = 231,432,105 + 53,066,850 = 284,498,955
      지방 가산세: 무신고 23,143,210 × 20% = 4,628,642 (F 18,928,010 × 20% = 3,785,602, B 4,215,200 × 20% = 843,040). 감면 없음
        납부지연 18,928,010 × 79 × 22/100,000 = 328,968.81 → 328,968, 4,215,200 × 50 × 22/100,000 = 46,367.2 → 46,367
        1-15 열 ⑬ 3,785,602 + 328,968 = 4,114,570 · ⑮ 18,928,010 + 4,114,570 = 23,042,580,
        1-10 열 ⑬ 843,040 + 46,367 = 889,407 · ⑮ 4,215,200 + 889,407 = 5,104,607,
        합계 ⑬ 4,628,642 + 375,335 = 5,003,977 · ⑮ 23,143,210 + 5,003,977 = 28,147,187"""
    r, rv = _two_months(802833750, 700000000)
    t = r["계산"]["합계"]
    assert (t["합산비교세액"], t["호별합산세액"]) == (231432105, 231432100)
    assert (t["지방_합산비교"], t["지방_호별합산"]) == (23143210, 23143210)
    nat, loc = rv["본지"]["열"], rv["지방"]["열"]
    assert (nat["합계"]["가산세_신고"], nat["합계"]["가산세_납부"], nat["합계"]["가산세"]) == (46286420, 6780430, 53066850)
    assert nat["합계"]["납부할세액"] == 284498955
    for name in ("국내소계", "1-10", "1-15"):
        assert nat[name]["가산세"] is None and nat[name]["납부할세액"] is None, name
    assert (loc["1-15"]["가산세_신고"], loc["1-15"]["가산세_납부"], loc["1-15"]["납부할세액"]) == (3785602, 328968, 23042580)
    assert (loc["1-10"]["가산세_신고"], loc["1-10"]["가산세_납부"], loc["1-10"]["납부할세액"]) == (843040, 46367, 5104607)
    for name in ("합계", "국내소계"):
        assert (loc[name]["가산세_신고"], loc[name]["가산세_납부"], loc[name]["가산세"]) == (4628642, 375335, 5003977), name
        assert loc[name]["납부할세액"] == 28147187, name
    assert _fc(rv, r) == []
    # 지방 열의 가산세와 납부할 총세액을 비워 두면(본지 판정을 지방 서식에 그대로 쓴 값) 검산이 알린다
    bad = copy.deepcopy(rv)
    for name in ("국내소계", "1-10", "1-15"):
        for k in ("가산세", "가산세_신고", "가산세_납부", "가산세_기타", "납부할세액"):
            bad["지방"]["열"][name][k] = None
    msgs = _fc(bad, r)
    assert any("지방 1-15 열" in m and "⑬" in m and "비어 있다" in m for m in msgs), msgs
    assert any("지방" in m and "⑮" in m and "비어 있다" in m for m in msgs), msgs


def test_local_merged_comparison_wins_but_national_does_not():
    """지방소득세만 합산 비교세액이 1원 크다. 지방 서식은 가산세와 납부할 총세액을 합계 열에만, 본지는 열과 소계에도 적는다.
      F 과세표준 = 802,833,330 - 321,133,332 - 6,000,000 - 2,500,000 = 473,199,998. 세액 189,279,999.2 → 189,279,999,
        지방 18,927,999.92 → 18,927,999
      B 과세표준 = (700,000,003 - 500,000,000 - 10,000,000) - 장기보유특별공제 26,600,000 = 163,400,003.
        세액 37,060,000 + 13,400,003 × 38% = 42,152,001.14 → 42,152,001, 지방 3,706,000 + 13,400,003 × 3.8% = 4,215,200.11 → 4,215,200
      국세: 세율별 합 231,432,000 = 합산 비교 174,060,000 + 136,600,001 × 42% = 231,432,000.42 → 231,432,000
      지방: 세율별 합 23,143,199 < 합산 비교 17,406,000 + 136,600,001 × 4.2% = 23,143,200.04 → 23,143,200
      국세 가산세: 무신고 231,432,000 × 20% = 46,286,400. 건별 37,855,999.8 → 37,855,999 와 8,430,400.2 → 8,430,400 이고
        모자라는 1원을 F 건에 두어 37,856,000. 납부지연 189,279,999 × 139 × 22/100,000 = 5,788,182.37 → 5,788,180,
        42,152,001 × 107 × 22/100,000 = 992,258.10 → 992,250. 계 53,066,830
        1-15 열 ⑱ 189,279,999 + 43,644,180 = 232,924,179, 1-10 열 ⑱ 42,152,001 + 9,422,650 = 51,574,651, 합계 284,498,830
      지방 가산세: 무신고 23,143,199 × 20% = 4,628,639.8 → 4,628,639 (F 18,927,999 × 20% = 3,785,599.8 → 3,785,599, B 843,040). 감면 없음
        납부지연 18,927,999 × 79 × 22/100,000 = 328,968.62 → 328,968, 46,367. 계 5,003,974. ⑮ = 23,143,200 + 5,003,974 = 28,147,174"""
    r, rv = _two_months(802833330, 700000003)
    t = r["계산"]["합계"]
    assert (t["합산비교세액"], t["호별합산세액"]) == (231432000, 231432000)
    assert (t["지방_합산비교"], t["지방_호별합산"]) == (23143200, 23143199)
    nat, loc = rv["본지"]["열"], rv["지방"]["열"]
    assert (nat["1-15"]["가산세_신고"], nat["1-15"]["가산세_납부"], nat["1-15"]["납부할세액"]) == (37856000, 5788180, 232924179)
    assert (nat["1-10"]["가산세_신고"], nat["1-10"]["가산세_납부"], nat["1-10"]["납부할세액"]) == (8430400, 992250, 51574651)
    assert (nat["합계"]["가산세"], nat["합계"]["납부할세액"], nat["국내소계"]["납부할세액"]) == (53066830, 284498830, 284498830)
    for name in ("국내소계", "1-10", "1-15"):
        assert loc[name]["가산세"] is None and loc[name]["가산세_신고"] is None and loc[name]["납부할세액"] is None, name
    assert (loc["합계"]["가산세_신고"], loc["합계"]["가산세_납부"], loc["합계"]["가산세"]) == (4628639, 375335, 5003974)
    assert loc["합계"]["납부할세액"] == loc["합계"]["신고기한내납부"] == 28147174
    assert any("지방소득세 합산 비교 세액이 큰 신고서라" in m and "합계 열에만 적었다" in m for m in rv["확인사항"])
    assert _fc(rv, r) == []
    _hit(_bump_local(rv, "합계", "가산세_신고", 1), r, "지방 합계", "⑬", "4,628,639")
