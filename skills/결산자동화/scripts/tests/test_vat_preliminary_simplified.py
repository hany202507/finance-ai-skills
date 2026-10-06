# -*- coding: utf-8 -*-
"""예정신고 변형 + 간이과세자 테스트."""
from vat_engine import JudgmentInput, Purpose, judge, Judgment, Routing
from vat_return import aggregate
from vat_simplified import (
    aggregate_simplified, 간이_부가가치율, SimplifiedReturn, 납부의무면제_공급대가,
)


def _j(과세유형, 공급가, 세액, 구분):
    return Judgment(라우팅=Routing.매입매출, 구분=구분, 과세유형=과세유형,
                    불공제사유=None, 공급가=공급가, 세액=세액, 신뢰도="높음", hitl=False)


# --- 예정신고 변형
def test_preliminary_excludes_electronic_credit_and_baddebt():
    js = [_j(11, 10000, 1000, "매출"), _j(51, 4000, 400, "매입")]
    확정 = aggregate(js, 신고구분="확정", 전자신고공제=True, 대손세액가감=-500, 예정고지=100)
    예정 = aggregate(js, 신고구분="예정", 전자신고공제=True, 대손세액가감=-500, 예정고지=100)
    # 확정: 전자신고공제 1만·대손 −500·예정고지 100 반영
    assert 확정.전자신고공제 == 10000
    assert 확정.매출세액 == 1000 - 500          # 대손가감
    # 예정: 전자신고공제 0, 대손 0, 예정고지 0
    assert 예정.전자신고공제 == 0
    assert 예정.매출세액 == 1000                # 대손 미반영
    assert 예정.차감납부 == 예정.납부세액        # 예정고지 차감 없음

def test_preliminary_payable_matches_core():
    js = [_j(11, 10000, 1000, "매출"), _j(51, 4000, 400, "매입")]
    예정 = aggregate(js, 신고구분="예정")
    assert 예정.납부세액 == 600


# --- 간이과세자
def test_simplified_retail_rate_15():
    # 소매업 공급대가 11,000,000 × 15% × 10% = 165,000
    js = [_j(11, 10_000_000, 1_000_000, "매출")]
    r = aggregate_simplified(js, "소매", 전자신고공제=False)
    assert r.부가가치율 == 15
    assert r.과세공급대가 == 11_000_000
    assert r.매출세액 == 11_000_000 * 15 // 100 * 10 // 100   # 165,000

def test_simplified_input_credit_half_percent():
    js = [_j(11, 100_000_000, 10_000_000, "매출"),
          _j(51, 20_000_000, 2_000_000, "매입")]
    r = aggregate_simplified(js, "숙박", 전자신고공제=False)   # 25%
    assert r.수취세액공제 == 22_000_000 * 5 // 1000           # 공급대가×0.5%

def test_simplified_payment_exemption_under_4800():
    # 공급대가 4,400만 < 4,800만 → 납부의무 면제
    js = [_j(11, 40_000_000, 4_000_000, "매출")]
    r = aggregate_simplified(js, "소매", 전자신고공제=False)
    assert r.납부의무면제 is True
    assert r.차감납부 == 0

def test_simplified_over_threshold_pays():
    js = [_j(11, 90_000_000, 9_000_000, "매출")]   # 공급대가 9,900만 ≥ 4,800만
    r = aggregate_simplified(js, "소매", 전자신고공제=True)
    assert r.납부의무면제 is False
    expected = 99_000_000 * 15 // 100 * 10 // 100 - 0 - 0 - 10000
    assert r.차감납부 == expected

def test_simplified_credit_capped_at_output_tax():
    # 매출세액 750,000인데 매입 수취공제가 훨씬 큼 → 공제합계 매출세액 한도 → 차감납부 0
    js = [_j(11, 45_000_000, 5_000_000, "매출"), _j(51, 900_000_000, 90_000_000, "매입")]
    r = aggregate_simplified(js, "소매", 전자신고공제=False)
    assert r.매출세액 == 750_000
    assert r.공제합계 == 750_000        # min(수취공제 4,950,000, 매출세액 750,000)
    assert r.차감납부 == 0

def test_simplified_prepaid_yields_refund():
    js = [_j(11, 90_000_000, 9_000_000, "매출")]   # 매출세액 1,485,000
    r = aggregate_simplified(js, "소매", 전자신고공제=False, 예정부과세액=2_000_000)
    assert r.차감납부 == 1_485_000 - 2_000_000      # (−)515,000 환급

def test_simplified_penalty_added():
    js = [_j(11, 90_000_000, 9_000_000, "매출")]
    r = aggregate_simplified(js, "소매", 전자신고공제=False, 가산세=50_000)
    assert r.차감납부 == 1_485_000 + 50_000

def test_simplified_unknown_industry_raises():
    import pytest
    with pytest.raises(ValueError):
        aggregate_simplified([], "없는업종")

def test_all_industries_have_rate():
    for 업종 in 간이_부가가치율:
        r = aggregate_simplified([], 업종)
        assert r.부가가치율 == 간이_부가가치율[업종]
