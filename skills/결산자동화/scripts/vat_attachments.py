# -*- coding: utf-8 -*-
"""부가세 붙임서식(별지) 산출 — Voucher 집합 그루핑 + 특수서식 계산.

A(상시): 매출/매입처별 세계합계표·신용카드수령명세서·발행금액집계표·공제받지못할매입세액명세서
B(조건부): 영세율첨부·건물등취득명세서·계산서합계표·대손세액공제신고서·의제매입세액공제신고서
C(업종): 부동산임대공급가액명세서(간주임대료)·재활용폐자원 등
근거: 신고서 붙임서식 → 본지 란 매핑.
"""
from dataclasses import dataclass
from collections import OrderedDict
from typing import List
from vat_engine import Judgment, Routing, DenyReason
from vat_douzone import Voucher, DENY_CODE

간주임대료율_2026 = 31          # /1000 = 3.1% (시행규칙)

# ---------------------------------------------------------------- 공통 그루핑
def _group_by_party(vouchers, codes, 방향) -> List[dict]:
    """거래처(사업자번호)별 매수·공급가액·세액 집계."""
    agg = OrderedDict()
    for v in vouchers:
        j = v.judgment
        if j.구분 != 방향 or j.과세유형 not in codes:
            continue
        key = v.사업자번호
        a = agg.setdefault(key, [v.거래처명, 0, 0, 0])
        a[1] += 1
        a[2] += j.공급가
        a[3] += j.세액
    return [{"거래처명": n, "사업자번호": k, "매수": c, "공급가액": s, "세액": t}
            for k, (n, c, s, t) in agg.items()]


# ================================================================ A. 상시
def sales_tax_invoice_list(vouchers) -> List[dict]:
    """매출처별 세금계산서합계표 [제38호] → 본지 (1)."""
    return _group_by_party(vouchers, {11}, "매출")


def purchase_tax_invoice_list(vouchers) -> List[dict]:
    """매입처별 세금계산서합계표 [제39호] → 본지 (10)(12). 세계 수취분 전부(불공 포함)."""
    return _group_by_party(vouchers, {51, 52, 54}, "매입")


def card_received_detail(vouchers) -> dict:
    """신용카드매출전표등 수령명세서 [제16호] → (15). 일반(44)/고정자산(45) 분리."""
    일반 = {"매수": 0, "공급가액": 0, "세액": 0}
    고정 = {"매수": 0, "공급가액": 0, "세액": 0}
    for v in vouchers:
        j = v.judgment
        if j.구분 != "매입" or j.과세유형 not in (57, 61):
            continue
        bucket = 고정 if v.judgment.고정자산 else 일반
        bucket["매수"] += 1
        bucket["공급가액"] += j.공급가
        bucket["세액"] += j.세액
    return {"일반매입(44)": 일반, "고정자산매입(45)": 고정}


def card_issued_summary(vouchers) -> dict:
    """신용카드·현금영수증 발행금액집계표 [제23호] → (20). 매출 발행액."""
    신용카드 = 0
    현금영수증 = 0
    for v in vouchers:
        j = v.judgment
        if j.구분 != "매출":
            continue
        if j.과세유형 == 17:
            신용카드 += j.공급가 + j.세액
        elif j.과세유형 == 22:
            현금영수증 += j.공급가 + j.세액
    return {"신용카드": 신용카드, "현금영수증": 현금영수증, "합계": 신용카드 + 현금영수증}


def non_deductible_detail(vouchers) -> List[dict]:
    """공제받지못할 매입세액 명세서 [제22호] → (17). 불공제 사유별 집계(더존 순번)."""
    agg = OrderedDict()
    for v in vouchers:
        j = v.judgment
        if j.과세유형 != 54 or j.불공제사유 is None:
            continue
        r = j.불공제사유
        a = agg.setdefault(r, [0, 0, 0])
        a[0] += 1
        a[1] += j.공급가
        a[2] += j.세액
    rows = [{"사유": r.value, "더존코드": DENY_CODE.get(r, ""),
             "매수": c, "공급가액": s, "세액": t}
            for r, (c, s, t) in agg.items()]
    return sorted(rows, key=lambda x: x["더존코드"])


# ================================================================ B. 조건부
def zero_rate_attachment(vouchers) -> dict:
    """영세율 첨부 → (5)(6). 수출(16)=수출실적명세서 / 국내영세(12)=내국신용장·구매확인서."""
    수출 = [v for v in vouchers if v.judgment.구분 == "매출" and v.judgment.과세유형 == 16]
    국내 = [v for v in vouchers if v.judgment.구분 == "매출" and v.judgment.과세유형 == 12]
    return {
        "수출실적명세서": [{"거래처명": v.거래처명, "공급가액": v.judgment.공급가, "품명": v.품명} for v in 수출],
        "내국신용장구매확인서전자발급명세서": [{"거래처명": v.거래처명, "공급가액": v.judgment.공급가} for v in 국내],
    }


def fixed_asset_acquisition(vouchers) -> List[dict]:
    """건물등 감가상각자산 취득명세서 [제27호] → (12). 매입 고정자산."""
    rows = []
    for v in vouchers:
        j = v.judgment
        if j.구분 == "매입" and j.고정자산 and j.과세유형 in (51, 54):
            rows.append({"거래처명": v.거래처명, "품명": v.품명,
                         "취득가액": j.공급가, "세액": j.세액})
    return rows


def calculator_invoice_list(vouchers) -> dict:
    """계산서합계표 → 면세. 매출(13)/매입(53) 거래처별."""
    return {"매출(발급)": _group_by_party(vouchers, {13}, "매출"),
            "매입(수취)": _group_by_party(vouchers, {53}, "매입")}


@dataclass
class BadDebt:
    거래처명: str
    사업자번호: str
    대손금: int          # 부가세 포함 채권액


def bad_debt_detail(대손들) -> List[dict]:
    """대손세액 공제(변제)신고서 → (8)/(17). 대손세액 = 대손금 × 10/110."""
    return [{"거래처명": d.거래처명, "사업자번호": d.사업자번호,
             "대손금": d.대손금, "대손세액": d.대손금 * 10 // 110} for d in 대손들]


def total_bad_debt_tax(대손들) -> int:
    return sum(d.대손금 * 10 // 110 for d in 대손들)


@dataclass
class DeemedPurchase:
    거래처명: str
    매입가액: int
    공제율분자: int      # 업종별: 소매·음식 8, 제조 4(중소 6) 등
    공제율분모: int      # 108, 104, 106 …


def deemed_purchase_detail(의제들) -> List[dict]:
    """의제매입세액 공제신고서 [제15호] → (15)→(46)."""
    rows = []
    for d in 의제들:
        공제 = d.매입가액 * d.공제율분자 // d.공제율분모
        rows.append({"거래처명": d.거래처명, "매입가액": d.매입가액,
                     "공제율": f"{d.공제율분자}/{d.공제율분모}", "공제세액": 공제})
    return rows


# ================================================================ C. 업종 특수
@dataclass
class Rental:
    거래처명: str
    보증금: int
    임대일수: int        # 과세대상기간 임대일수


def real_estate_rental(임대들, 이자율=간주임대료율_2026) -> List[dict]:
    """부동산임대공급가액명세서 [제25호]. 간주임대료 = 보증금 × 이자율 × 일수/365, 세액=간주×10%."""
    rows = []
    for r in 임대들:
        간주 = r.보증금 * 이자율 * r.임대일수 // (1000 * 365)
        rows.append({"거래처명": r.거래처명, "보증금": r.보증금, "임대일수": r.임대일수,
                     "간주임대료": 간주, "세액": 간주 // 10})
    return rows


@dataclass
class RecycledWaste:
    거래처명: str
    매입가액: int
    공제율분자: int = 3   # 통상 3/103
    공제율분모: int = 103


def recycled_waste_detail(폐자원들) -> List[dict]:
    """재활용폐자원 등 매입세액 공제신고서 → (15)→(47). 해당 업종만."""
    return [{"거래처명": w.거래처명, "매입가액": w.매입가액,
             "공제세액": w.매입가액 * w.공제율분자 // w.공제율분모} for w in 폐자원들]
