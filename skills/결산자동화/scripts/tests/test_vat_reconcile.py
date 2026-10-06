# -*- coding: utf-8 -*-
"""Layer 1 결정론 대사 테스트."""
from vat_engine import JudgmentInput, Purpose, judge, Judgment, Routing
from vat_return import aggregate
from vat_douzone import Voucher
from vat_reconcile import (
    Finding, reconcile_sales_vs_hometax, reconcile_deposits_vs_sales,
    inventory_rollforward, detect_circular_parties, apportionment_check,
    deemed_rent_check, attachment_vs_return_check, run_reconcile,
)


def _v(과세유형, 공급가, 세액, 구분, 사업자번호="", 고정자산=False):
    j = Judgment(라우팅=Routing.매입매출, 구분=구분, 과세유형=과세유형, 불공제사유=None,
                 공급가=공급가, 세액=세액, 신뢰도="높음", hitl=False, 고정자산=고정자산)
    return Voucher(년=2026, 월=7, 일=1, judgment=j, 사업자번호=사업자번호)


def test_hometax_sales_pass_and_flag():
    f = aggregate([_v(11, 10000, 1000, "매출").judgment], 전자신고공제=False)
    assert reconcile_sales_vs_hometax(f, 10000).상태 == "PASS"
    fl = reconcile_sales_vs_hometax(f, 15000)
    assert fl.상태 == "FLAG" and fl.재무영향 == 500   # 누락 5000의 10%

def test_deposit_flag():
    assert reconcile_deposits_vs_sales(0).상태 == "PASS"
    assert reconcile_deposits_vs_sales(11000).상태 == "FLAG"

def test_inventory_rollforward_shortage_flags():
    # 기초100 + 매입500 − 원가300 = 계산기말 300; 장부 250 → 50 부족
    p = inventory_rollforward(100, 500, 300, 250)
    assert p.상태 == "FLAG" and "자가소비" in p.상세
    ok = inventory_rollforward(100, 500, 300, 300)
    assert ok.상태 == "PASS"

def test_circular_party_detection():
    vs = [_v(11, 1000, 100, "매출", 사업자번호="111"),
          _v(51, 500, 50, "매입", 사업자번호="111"),   # 동일 사업자번호 매출·매입
          _v(51, 200, 20, "매입", 사업자번호="222")]
    flags = detect_circular_parties(vs)
    assert len(flags) == 1 and "111" in flags[0].상세

def test_apportionment_recompute_and_omission():
    # 면세비율 20%, 공통매입세액 100만 → 불공제 20만
    f = apportionment_check(800, 200, 1_000_000, 신고_불공제세액=200_000)
    assert f.상태 == "PASS"
    mism = apportionment_check(800, 200, 1_000_000, 신고_불공제세액=0)
    assert mism.상태 == "FLAG" and mism.재무영향 == 200_000

def test_apportionment_omission_rule():
    # 면세비율 4%(<5%) & 공통매입 400만(<500만) → 생략(불공제 0)
    f = apportionment_check(960, 40, 4_000_000, 신고_불공제세액=0)
    assert f.상태 == "PASS" and "생략 True" in f.상세

def test_deemed_rent_recompute():
    # 보증금 1억, 365일, 3.1% → 3,100,000
    assert deemed_rent_check(100_000_000, 365, 3_100_000).상태 == "PASS"
    assert deemed_rent_check(100_000_000, 365, 3_000_000).상태 == "FLAG"

def test_attachment_vs_return_ties():
    vs = [_v(11, 1000, 100, "매출", 사업자번호="111")]
    f = aggregate([v.judgment for v in vs], 전자신고공제=False)
    findings = attachment_vs_return_check(f, vs)
    assert all(x.상태 == "PASS" for x in findings)

def test_run_reconcile_report():
    vs = [_v(11, 10000, 1000, "매출", 사업자번호="111"),
          _v(51, 4000, 400, "매입", 사업자번호="111")]   # 순환 신호
    f = aggregate([v.judgment for v in vs], 전자신고공제=False)
    rep = run_reconcile(f, vs, 수집_과세매출=10000,
                        재고=dict(기초재고=0, 당기매입=4000, 매출원가=4000, 장부기말=0),
                        간주임대료=dict(보증금=100_000_000, 임대일수=365, 신고_간주임대료=3_100_000))
    assert rep["FLAG"] >= 1        # 순환거래 신호
    assert not rep["완결"]
    assert any(x.체크 == "순환거래신호" for x in rep["findings"])
