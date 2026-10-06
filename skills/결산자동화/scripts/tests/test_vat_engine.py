# -*- coding: utf-8 -*-
"""부가세 판단 엔진 테스트 (계획서 Task 1~7)."""
from vat_engine import (
    Purpose, DenyReason, Routing, JudgmentInput, Judgment,
    ZeroRateType, DeemedSupply, SalesResult,
    SALES_TAXTYPE, PURCH_TAXTYPE,
    route, primary_evidence, taxtype, deny_check, DenyResult,
    split_amount, sales_taxtype, adjust_base, judge, summarize,
    industry_reminders, INDUSTRY_REMINDERS,
)


# --- Task 1: 계약
def test_contracts_exist_and_defaults():
    inp = JudgmentInput(방향="매입", 증빙=frozenset({"세금계산서"}), 총액=1100)
    assert inp.과세구분 == "과세"
    assert inp.카드_가맹점_확인 is False
    assert inp.전기승계_확정 is False
    assert DenyReason.접대비.value == "④접대비"
    assert Routing.매입매출.value == "매입매출"
    assert SALES_TAXTYPE[("수출", "수출")] == 16
    assert SALES_TAXTYPE[("현금영수증", "면세")] == 23
    assert PURCH_TAXTYPE[("세금계산서", "과세")] == 51


# --- Task 2: S1 라우팅
def test_route_taxinvoice_is_purchsale():
    assert route(JudgmentInput(방향="매입", 증빙=frozenset({"세금계산서"}))) is Routing.매입매출

def test_route_card_is_purchsale():
    assert route(JudgmentInput(방향="매입", 증빙=frozenset({"카드"}))) is Routing.매입매출

def test_route_bank_only_is_general():
    assert route(JudgmentInput(방향="매입", 증빙=frozenset({"은행"}))) is Routing.일반

def test_route_import_is_purchsale():
    assert route(JudgmentInput(방향="매입", 증빙=frozenset({"은행"}), 수입=True)) is Routing.매입매출


# --- Task 3: S3 과세유형
def test_primary_evidence_priority():
    assert primary_evidence(JudgmentInput(방향="매입", 증빙=frozenset({"카드", "현금영수증"}))) == "카드"

def test_taxtype_sales_taxinvoice():
    assert taxtype(JudgmentInput(방향="매출", 증빙=frozenset({"세금계산서"}), 과세구분="과세")) == 11

def test_taxtype_sales_export_16():
    assert taxtype(JudgmentInput(방향="매출", 증빙=frozenset(), 과세구분="수출")) == 16

def test_taxtype_sales_cash_exempt_23():
    assert taxtype(JudgmentInput(방향="매출", 증빙=frozenset({"현금영수증"}), 과세구분="면세")) == 23

def test_taxtype_purchase_card_57():
    assert taxtype(JudgmentInput(방향="매입", 증빙=frozenset({"카드"}), 과세구분="과세")) == 57

def test_taxtype_purchase_import_55():
    assert taxtype(JudgmentInput(방향="매입", 증빙=frozenset(), 수입=True, 과세구분="과세")) == 55

def test_taxtype_sales_no_evidence_is_14():
    assert taxtype(JudgmentInput(방향="매출", 증빙=frozenset(), 과세구분="과세")) == 14


# --- Task 4: S4 공제/불공제
def test_deny_sales_never_denied():
    r = deny_check(JudgmentInput(방향="매출", 증빙=frozenset({"세금계산서"})))
    assert r.불공제사유 is None and r.라우팅오버라이드 is None

def test_deny_entertainment_routes_general():
    # G3 확정: 접대비는 54 불공이 아니라 일반전표 전액비용
    r = deny_check(JudgmentInput(방향="매입", 증빙=frozenset({"세금계산서"}), 지출목적=Purpose.접대))
    assert r.라우팅오버라이드 is Routing.일반
    assert r.근거[0][0] == "부가세법 §39①6"
    assert r.hitl is True

def test_deny_entertainment_carried_forward_autoconfirm():
    r = deny_check(JudgmentInput(방향="매입", 증빙=frozenset({"세금계산서"}),
                                 지출목적=Purpose.접대, 전기승계_확정=True))
    assert r.hitl is False

def test_deny_land_capex():
    r = deny_check(JudgmentInput(방향="매입", 증빙=frozenset({"세금계산서"}),
                                 지출목적=Purpose.토지_자본적지출, 자본적지출=True))
    assert r.불공제사유 is DenyReason.토지관련

def test_deny_passenger_service_routes_to_general():
    r = deny_check(JudgmentInput(방향="매입", 증빙=frozenset({"카드"}),
                                 지출목적=Purpose.여객운송_개인서비스))
    assert r.라우팅오버라이드 is Routing.일반
    assert r.근거[0][0] == "부가세법 시행령 §88⑤"

def test_deny_simplified_under_4800_routes_general():
    r = deny_check(JudgmentInput(방향="매입", 증빙=frozenset({"현금영수증"}),
                                 거래처_과세유형="간이", 거래처_공급대가_4800이상=False))
    assert r.라우팅오버라이드 is Routing.일반

def test_simplified_over_4800_with_taxinvoice_deductible():
    r = deny_check(JudgmentInput(방향="매입", 증빙=frozenset({"세금계산서"}),
                                 거래처_과세유형="간이", 거래처_공급대가_4800이상=True))
    assert r.불공제사유 is None and r.라우팅오버라이드 is None

def test_deny_card_merchant_unverified_routes_general():
    r = deny_check(JudgmentInput(방향="매입", 증빙=frozenset({"카드"}), 카드_가맹점_확인=False))
    assert r.라우팅오버라이드 is Routing.일반

def test_deny_defective_taxinvoice():
    r = deny_check(JudgmentInput(방향="매입", 증빙=frozenset({"세금계산서"}), 증빙흠결=True))
    assert r.불공제사유 is DenyReason.필요적기재누락

def test_small_car_business_use_exception_deductible():
    r = deny_check(JudgmentInput(방향="매입", 증빙=frozenset({"세금계산서"}),
                                 지출목적=Purpose.차량_소형승용, 소형승용_영업용=True))
    assert r.불공제사유 is None


# --- Task 5: S6 금액분해
def test_split_taxinvoice_uses_given():
    assert split_amount(JudgmentInput(방향="매입", 증빙=frozenset({"세금계산서"}), 공급가=1000, 세액=100)) == (1000, 100)

def test_split_card_gross_10_11():
    assert split_amount(JudgmentInput(방향="매입", 증빙=frozenset({"카드"}), 총액=1100)) == (1000, 100)

def test_split_card_gross_rounding_floor():
    공급가, 세액 = split_amount(JudgmentInput(방향="매입", 증빙=frozenset({"카드"}), 총액=10000))
    assert 공급가 == 9090 and 세액 == 910
    assert 공급가 + 세액 == 10000

def test_split_exempt_zero_vat():
    assert split_amount(JudgmentInput(방향="매입", 증빙=frozenset({"계산서"}), 과세구분="면세", 총액=1000)) == (1000, 0)


# --- Task 6: judge 오케스트레이터
def test_judge_normal_deductible_purchase():
    j = judge(JudgmentInput(방향="매입", 증빙=frozenset({"세금계산서"}), 전자세계=True,
                            과세구분="과세", 공급가=1000, 세액=100, 지출목적=Purpose.일반경비))
    assert j.라우팅 is Routing.매입매출
    assert j.과세유형 == 51
    assert j.불공제사유 is None
    assert (j.공급가, j.세액) == (1000, 100)
    assert j.hitl is False

def test_judge_entertainment_routes_general_no_vat():
    j = judge(JudgmentInput(방향="매입", 증빙=frozenset({"세금계산서"}),
                            과세구분="과세", 공급가=1000, 세액=100, 지출목적=Purpose.접대))
    assert j.라우팅 is Routing.일반
    assert j.과세유형 is None
    assert j.세액 == 0
    assert j.hitl is True

def test_judge_land_capex_is_deny_54():
    j = judge(JudgmentInput(방향="매입", 증빙=frozenset({"세금계산서"}), 과세구분="과세",
                            공급가=1000, 세액=100, 지출목적=Purpose.토지_자본적지출, 자본적지출=True))
    assert j.과세유형 == 54 and j.불공제사유 is DenyReason.토지관련

def test_judge_passenger_service_routes_general_no_vat():
    j = judge(JudgmentInput(방향="매입", 증빙=frozenset({"카드"}), 총액=11000,
                            지출목적=Purpose.여객운송_개인서비스))
    assert j.라우팅 is Routing.일반
    assert j.과세유형 is None
    assert j.세액 == 0
    assert j.공급가 == 11000

def test_judge_card_deductible_57():
    j = judge(JudgmentInput(방향="매입", 증빙=frozenset({"카드"}), 총액=1100,
                            카드_가맹점_확인=True, 과세구분="과세", 지출목적=Purpose.복리후생))
    assert j.과세유형 == 57
    assert (j.공급가, j.세액) == (1000, 100)

def test_judge_missing_purpose_lowers_confidence():
    j = judge(JudgmentInput(방향="매입", 증빙=frozenset({"세금계산서"}),
                            과세구분="과세", 공급가=1000, 세액=100))
    assert j.신뢰도 == "낮음" and j.hitl is True


# --- Task 7: 배치 요약
# --- 매출 판단축 (2026-07-15)
def test_sales_exempt_calseo_13():
    sr = sales_taxtype(JudgmentInput(방향="매출", 증빙=frozenset({"계산서"}), 면세대상=True))
    assert sr.과세유형 == 13

def test_sales_exempt_cash_23():
    sr = sales_taxtype(JudgmentInput(방향="매출", 증빙=frozenset({"현금영수증"}), 면세대상=True))
    assert sr.과세유형 == 23

def test_sales_export_16_with_attachment():
    sr = sales_taxtype(JudgmentInput(방향="매출", 증빙=frozenset(),
                                     영세율유형=ZeroRateType.직수출))
    assert sr.과세유형 == 16
    assert sr.첨부 == "수출실적명세서"
    assert sr.hitl is True

def test_sales_local_lc_12():
    sr = sales_taxtype(JudgmentInput(방향="매출", 증빙=frozenset({"세금계산서"}),
                                     영세율유형=ZeroRateType.내국신용장_구매확인서))
    assert sr.과세유형 == 12
    assert "구매확인서" in sr.첨부

def test_sales_deemed_gift_14():
    sr = sales_taxtype(JudgmentInput(방향="매출", 증빙=frozenset(),
                                     간주공급유형=DeemedSupply.사업상증여, 매입세액공제이력=True))
    assert sr.과세유형 == 14
    assert sr.hitl is True

def test_sales_deemed_direct_branch_11():
    sr = sales_taxtype(JudgmentInput(방향="매출", 증빙=frozenset(),
                                     간주공급유형=DeemedSupply.직매장반출, 매입세액공제이력=True))
    assert sr.과세유형 == 11

def test_sales_deemed_no_prior_credit_not_taxable():
    sr = sales_taxtype(JudgmentInput(방향="매출", 증빙=frozenset(),
                                     간주공급유형=DeemedSupply.사업상증여, 매입세액공제이력=False))
    assert sr.과세유형 is None and sr.hitl is True

def test_sales_general_taxinvoice_11():
    sr = sales_taxtype(JudgmentInput(방향="매출", 증빙=frozenset({"세금계산서"}), 과세구분="과세"))
    assert sr.과세유형 == 11

def test_adjust_base_erunuri_negative():
    assert adjust_base(JudgmentInput(방향="매출", 증빙=frozenset(), 조정사유="에누리", 조정금액=500)) == -500

def test_adjust_base_jangnyeogeum_zero():
    assert adjust_base(JudgmentInput(방향="매출", 증빙=frozenset(), 조정사유="장려금", 조정금액=500)) == 0

def test_judge_sales_exempt_routes_purchsale_13():
    j = judge(JudgmentInput(방향="매출", 증빙=frozenset({"계산서"}), 면세대상=True,
                            공급가=1000, 세액=0))
    assert j.라우팅 is Routing.매입매출
    assert j.과세유형 == 13
    assert j.구분 == "매출"

def test_judge_sales_discount_reduces_base():
    j = judge(JudgmentInput(방향="매출", 증빙=frozenset({"세금계산서"}), 과세구분="과세",
                            공급가=10000, 세액=1000, 조정사유="매출할인", 조정금액=1000))
    assert j.공급가 == 9000
    assert j.과세유형 == 11


# --- S4 완성: 등록전·금스크랩
def test_deny_pre_registration():
    r = deny_check(JudgmentInput(방향="매입", 증빙=frozenset({"세금계산서"}), 등록전_매입=True))
    assert r.불공제사유 is DenyReason.등록전
    assert r.근거[0][0] == "부가세법 §39①8"

def test_deny_gold_scrap_account():
    r = deny_check(JudgmentInput(방향="매입", 증빙=frozenset({"세금계산서"}), 금거래계좌_미사용=True))
    assert r.불공제사유 is DenyReason.금스크랩계좌

def test_judge_pre_registration_54():
    j = judge(JudgmentInput(방향="매입", 증빙=frozenset({"세금계산서"}), 과세구분="과세",
                            공급가=1000, 세액=100, 등록전_매입=True))
    assert j.과세유형 == 54 and j.불공제사유 is DenyReason.등록전


# --- 업종 프로파일 게이팅
def test_industry_reminder_realestate():
    r = industry_reminders(JudgmentInput(방향="매출", 증빙=frozenset(), 업종="부동산임대"))
    assert len(r) == 1 and "간주임대료" in r[0][1]

def test_industry_reminder_none_when_unset():
    assert industry_reminders(JudgmentInput(방향="매출", 증빙=frozenset())) == []

def test_industry_reminder_unknown_industry_empty():
    assert industry_reminders(JudgmentInput(방향="매출", 증빙=frozenset(), 업종="없는업종")) == []

def test_judge_appends_industry_reminder():
    j = judge(JudgmentInput(방향="매출", 증빙=frozenset({"세금계산서"}), 과세구분="과세",
                            공급가=1000, 세액=100, 업종="전자상거래"))
    assert any("판매대행" in why for _, why in j.근거)

def test_all_industries_have_reminder():
    for 업종 in INDUSTRY_REMINDERS:
        assert len(industry_reminders(JudgmentInput(방향="매출", 증빙=frozenset(), 업종=업종))) == 1


def test_summarize_counts():
    cases = [
        JudgmentInput(방향="매입", 증빙=frozenset({"세금계산서"}), 과세구분="과세",
                      공급가=1000, 세액=100, 지출목적=Purpose.일반경비),
        JudgmentInput(방향="매입", 증빙=frozenset({"세금계산서"}), 과세구분="과세",
                      공급가=1000, 세액=100, 지출목적=Purpose.토지_자본적지출, 자본적지출=True),
        JudgmentInput(방향="매입", 증빙=frozenset({"카드"}),
                      지출목적=Purpose.여객운송_개인서비스, 총액=11000),
    ]
    s = summarize(cases)
    assert s["총건"] == 3
    assert s["매입매출"] == 2       # 일반경비(51) + 토지(54)
    assert s["일반"] == 1           # 여객운송
    assert s["불공제"] == 1         # 토지
    assert s["HITL"] >= 2
    assert s["사유별"]["⑥토지관련"] == 1
