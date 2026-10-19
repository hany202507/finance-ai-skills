# -*- coding: utf-8 -*-
"""부가세 신고서 집계 테스트 (일반과세 확정신고)."""
import os, tempfile
from vat_engine import JudgmentInput, Purpose, judge
from vat_return import aggregate, ReturnForm, build_return_xlsx


def _mae_chul(과세유형, 공급가, 세액, 구분="매출", 고정자산=False):
    """테스트용 Judgment 헬퍼(엔진 우회, 직접 구성)."""
    from vat_engine import Judgment, Routing
    return Judgment(라우팅=Routing.매입매출, 구분=구분, 과세유형=과세유형,
                    불공제사유=None, 공급가=공급가, 세액=세액,
                    신뢰도="높음", hitl=False, 고정자산=고정자산)


def test_sales_taxinvoice_to_line1():
    f = aggregate([_mae_chul(11, 1000, 100)], 전자신고공제=False)
    assert f.공급[1] == 1000 and f.세액[1] == 100
    assert f.매출세액 == 100

def test_sales_card_to_line3_and_issue_base():
    f = aggregate([_mae_chul(17, 1000, 100), _mae_chul(22, 500, 50)], 전자신고공제=False)
    assert f.공급[3] == 1500 and f.세액[3] == 150
    assert f.카드발행액 == 1650

def test_sales_export_line6_zero_vat():
    f = aggregate([_mae_chul(16, 2000, 0)], 전자신고공제=False)
    assert f.공급[6] == 2000 and f.세액[6] == 0
    assert f.매출세액 == 0

def test_exempt_sales_to_exempt_income():
    f = aggregate([_mae_chul(13, 3000, 0)], 전자신고공제=False)
    assert f.면세수입금액 == 3000
    assert f.매출세액 == 0

def test_purchase_general_line10():
    f = aggregate([_mae_chul(51, 1000, 100, 구분="매입")], 전자신고공제=False)
    assert f.세액[10] == 100
    assert f.매입세액18 == 100

def test_purchase_fixed_asset_line12():
    f = aggregate([_mae_chul(51, 1000, 100, 구분="매입", 고정자산=True)], 전자신고공제=False)
    assert f.세액[12] == 100 and f.세액[10] == 0

def test_purchase_card_line15():
    f = aggregate([_mae_chul(57, 1000, 100, 구분="매입")], 전자신고공제=False)
    assert f.세액[15] == 100

def test_ungong_to_line17_netted_out():
    # 51 일반 세액100(공제) + 54 불공 세액50 → (10)=150, (17)=50, (18)=150-50=100
    js = [_mae_chul(51, 1000, 100, 구분="매입"), _mae_chul(54, 500, 50, 구분="매입")]
    f = aggregate(js, 전자신고공제=False)
    assert f.세액[10] == 150
    assert f.세액[17] == 50
    assert f.매입세액합계16 == 150
    assert f.매입세액18 == 100

def test_payable_sales_minus_purchase():
    js = [_mae_chul(11, 10000, 1000), _mae_chul(51, 4000, 400, 구분="매입")]
    f = aggregate(js, 전자신고공제=False)
    assert f.매출세액 == 1000
    assert f.매입세액18 == 400
    assert f.납부세액 == 600

def test_issue_credit_gated_and_capped():
    # 카드매출 발행액 1억1천만 → 1.3% = 143만, 한도 1000만 내
    f = aggregate([_mae_chul(17, 100_000_000, 10_000_000)],
                  발행공제자격=True, 전자신고공제=False)
    assert f.발행공제 == 110_000_000 * 13 // 1000

def test_issue_credit_zero_when_not_qualified():
    f = aggregate([_mae_chul(17, 1000, 100)], 발행공제자격=False, 전자신고공제=False)
    assert f.발행공제 == 0

def test_electronic_filing_credit_and_prepaid():
    js = [_mae_chul(11, 10000, 1000)]
    f = aggregate(js, 전자신고공제=True, 예정고지=200)
    assert f.전자신고공제 == 10000
    assert f.차감납부 == f.납부세액 - 10000 - 200

def test_validate_holds_endtoend_via_judge():
    inps = [
        JudgmentInput(방향="매출", 증빙=frozenset({"세금계산서"}), 과세구분="과세",
                      공급가=50000, 세액=5000),
        JudgmentInput(방향="매입", 증빙=frozenset({"세금계산서"}), 과세구분="과세",
                      공급가=20000, 세액=2000, 지출목적=Purpose.일반경비),
        JudgmentInput(방향="매입", 증빙=frozenset({"세금계산서"}), 과세구분="과세",
                      공급가=10000, 세액=1000, 지출목적=Purpose.사업무관),  # 불공→(10)+(17)
    ]
    js = [judge(i) for i in inps]
    f = aggregate(js, 전자신고공제=True)
    assert f.세액[1] == 5000
    assert f.세액[10] == 3000        # 일반경비 2000 + 사업무관(불공) 1000 (세계 수취분 포함)
    assert f.세액[17] == 1000       # 사업무관 불공
    assert f.매출세액 == 5000
    assert f.매입세액18 == 2000      # (16)3000 − (17)1000
    assert f.납부세액 == 3000

def test_build_xlsx_smoke():
    f = aggregate([_mae_chul(11, 1000, 100)], 전자신고공제=False)
    path = os.path.join(tempfile.mkdtemp(), "ret.xlsx")
    build_return_xlsx(f, path)
    assert os.path.exists(path)
    import openpyxl
    wb = openpyxl.load_workbook(path)
    ws = wb.active
    assert ws["A1"].value.startswith("부가가치세 신고서")
