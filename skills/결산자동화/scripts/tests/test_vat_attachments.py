# -*- coding: utf-8 -*-
"""부가세 붙임서식 테스트."""
from vat_engine import JudgmentInput, Purpose, judge, ZeroRateType
from vat_douzone import Voucher
from vat_attachments import (
    sales_tax_invoice_list, purchase_tax_invoice_list, card_received_detail,
    card_issued_summary, non_deductible_detail,
    zero_rate_attachment, fixed_asset_acquisition, calculator_invoice_list,
    BadDebt, bad_debt_detail, total_bad_debt_tax,
    DeemedPurchase, deemed_purchase_detail,
    Rental, real_estate_rental, RecycledWaste, recycled_waste_detail,
)


def _v(inp, **ctx):
    return Voucher(년=2026, 월=7, 일=15, judgment=judge(inp), **ctx)

def _sale(과세구분="과세", 공급가=1000, 세액=100, **k):
    return JudgmentInput(방향="매출", 증빙=frozenset({"세금계산서"}), 과세구분=과세구분,
                         공급가=공급가, 세액=세액, **k)

def _buy(공급가=1000, 세액=100, 지출목적=Purpose.일반경비, **k):
    return JudgmentInput(방향="매입", 증빙=frozenset({"세금계산서"}), 과세구분="과세",
                         공급가=공급가, 세액=세액, 지출목적=지출목적, **k)


# --- A 상시
def test_sales_tax_invoice_grouped_by_party():
    vs = [_v(_sale(), 거래처명="A", 사업자번호="111"),
          _v(_sale(공급가=2000, 세액=200), 거래처명="A", 사업자번호="111"),
          _v(_sale(), 거래처명="B", 사업자번호="222")]
    rows = sales_tax_invoice_list(vs)
    a = [r for r in rows if r["사업자번호"] == "111"][0]
    assert a["매수"] == 2 and a["공급가액"] == 3000 and a["세액"] == 300
    assert len(rows) == 2

def test_purchase_list_includes_ungong():
    vs = [_v(_buy()), _v(_buy(지출목적=Purpose.사업무관), 거래처명="C", 사업자번호="333")]
    rows = purchase_tax_invoice_list(vs)          # 51 + 54(사업무관 불공) 포함
    assert len(rows) == 2

def test_card_received_split_general_fixed():
    vs = [_v(JudgmentInput(방향="매입", 증빙=frozenset({"카드"}), 카드_가맹점_확인=True,
                           과세구분="과세", 총액=1100, 지출목적=Purpose.복리후생)),
          _v(JudgmentInput(방향="매입", 증빙=frozenset({"카드"}), 카드_가맹점_확인=True,
                           과세구분="과세", 총액=2200, 지출목적=Purpose.자산취득, 자본적지출=True))]
    d = card_received_detail(vs)
    assert d["일반매입(44)"]["세액"] == 100
    assert d["고정자산매입(45)"]["세액"] == 200

def test_card_issued_summary():
    vs = [_v(JudgmentInput(방향="매출", 증빙=frozenset({"카드"}), 과세구분="과세", 총액=1100)),
          _v(JudgmentInput(방향="매출", 증빙=frozenset({"현금영수증"}), 과세구분="과세", 총액=550))]
    s = card_issued_summary(vs)
    assert s["신용카드"] == 1100 and s["현금영수증"] == 550 and s["합계"] == 1650

def test_non_deductible_detail_grouped_by_reason():
    vs = [_v(_buy(지출목적=Purpose.사업무관)),
          _v(_buy(지출목적=Purpose.사업무관, 공급가=500, 세액=50)),
          _v(_buy(지출목적=Purpose.토지_자본적지출, 자본적지출=True))]
    rows = non_deductible_detail(vs)
    사업무관 = [r for r in rows if "사업무관" in r["사유"]][0]
    assert 사업무관["매수"] == 2 and 사업무관["세액"] == 150
    토지 = [r for r in rows if "토지" in r["사유"]][0]
    assert 토지["더존코드"] == "5"


# --- B 조건부
def test_zero_rate_attachment_split():
    vs = [_v(JudgmentInput(방향="매출", 증빙=frozenset(), 과세구분="수출",
                           영세율유형=ZeroRateType.직수출, 공급가=5000, 세액=0), 거래처명="EX"),
          _v(JudgmentInput(방향="매출", 증빙=frozenset({"세금계산서"}), 과세구분="영세_국내",
                           영세율유형=ZeroRateType.내국신용장_구매확인서, 공급가=3000, 세액=0), 거래처명="LC")]
    z = zero_rate_attachment(vs)
    assert len(z["수출실적명세서"]) == 1 and z["수출실적명세서"][0]["공급가액"] == 5000
    assert len(z["내국신용장구매확인서전자발급명세서"]) == 1

def test_fixed_asset_acquisition():
    vs = [_v(_buy(지출목적=Purpose.자산취득, 자본적지출=True, 공급가=8000, 세액=800),
             거래처명="설비사", 품명="기계")]
    rows = fixed_asset_acquisition(vs)
    assert rows[0]["취득가액"] == 8000 and rows[0]["품명"] == "기계"

def test_calculator_invoice_exempt():
    vs = [_v(JudgmentInput(방향="매출", 증빙=frozenset({"계산서"}), 면세대상=True,
                           공급가=3000, 세액=0), 거래처명="면세처", 사업자번호="999")]
    d = calculator_invoice_list(vs)
    assert d["매출(발급)"][0]["공급가액"] == 3000

def test_bad_debt():
    ds = [BadDebt("부실거래처", "444", 11000)]
    assert bad_debt_detail(ds)[0]["대손세액"] == 1000
    assert total_bad_debt_tax(ds) == 1000

def test_deemed_purchase():
    ds = [DeemedPurchase("농산물상", 10800, 8, 108)]   # 8/108
    assert deemed_purchase_detail(ds)[0]["공제세액"] == 800


# --- C 업종
def test_real_estate_deemed_rent():
    # 보증금 1억, 365일 → 간주임대료 = 1억 × 3.1% = 3,100,000, 세액 310,000
    rows = real_estate_rental([Rental("임차인", 100_000_000, 365)])
    assert rows[0]["간주임대료"] == 3_100_000
    assert rows[0]["세액"] == 310_000

def test_real_estate_partial_period():
    # 보증금 1억, 반년(182일) ≈ 1억×3.1%×182/365
    rows = real_estate_rental([Rental("임차인", 100_000_000, 182)])
    assert rows[0]["간주임대료"] == 100_000_000 * 31 * 182 // (1000 * 365)

def test_recycled_waste():
    ws = [RecycledWaste("고물상", 10300)]              # 3/103
    assert recycled_waste_detail(ws)[0]["공제세액"] == 300
