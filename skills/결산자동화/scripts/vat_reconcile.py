# -*- coding: utf-8 -*-
"""부가세 완결성 — Layer 1 결정론 대사·재계산.

"국세청이 이미 아는 것"과의 대사 + 임계값 재계산으로 누락·오류를 결정론적으로 스크리닝.
비결정론 이상탐지(순환그래프·셀프결제 스코어링)·맥락질문은 상위 AI 레이어(제품). 여기는 결정적 룰만.
신고 완결성 Layer 1 결정론 대사. 판례·조문 근거는 각 체크 함수 주석에 병기
"""
from dataclasses import dataclass, field
from collections import OrderedDict
from typing import List, Optional
from vat_return import ReturnForm
from vat_douzone import Voucher
from vat_attachments import sales_tax_invoice_list, non_deductible_detail, 간주임대료율_2026

# 임계값 (연도태그 설정 대상 — 예규검증)
안분생략_면세비율 = 0.05          # 5% 미만
안분생략_공통매입 = 5_000_000     # 500만원 미만
재계산_변동 = 0.05               # 면세비율 5%p 이상 증감


@dataclass
class Finding:
    체크: str
    상태: str                     # 'PASS' | 'FLAG'
    심각도: str = "-"             # '높음'|'중간'|'낮음'
    근거: str = ""                # 법령·판례
    상세: str = ""
    재무영향: int = 0             # 예상 세액 영향(원)


# ---------------------------------------------------------------- A. 매출 누락 대사
def reconcile_sales_vs_hometax(f: ReturnForm, 수집_과세매출_공급가: int) -> Finding:
    """홈택스 수집자료(전자세계·카드·현금영수증) ↔ 신고 과세매출. 신고 < 수집 = 누락."""
    신고 = f.공급.get(1, 0) + f.공급.get(3, 0) + f.공급.get(4, 0)
    if 신고 >= 수집_과세매출_공급가:
        return Finding("홈택스매출대사", "PASS", 근거="NTIS 양측대사",
                       상세=f"신고 {신고:,} ≥ 수집 {수집_과세매출_공급가:,}")
    diff = 수집_과세매출_공급가 - 신고
    return Finding("홈택스매출대사", "FLAG", "높음", "국세청 수집자료(경정리스크)",
                   f"신고 {신고:,} < 수집 {수집_과세매출_공급가:,} — 매출누락 의심 {diff:,}",
                   재무영향=diff // 10)


def reconcile_deposits_vs_sales(입금_미대응: int) -> Finding:
    """은행 입금 중 매출 미대응분 = 현금매출 누락 신호."""
    if 입금_미대응 <= 0:
        return Finding("입금-매출대사", "PASS")
    return Finding("입금-매출대사", "FLAG", "중간", "현금매출 누락",
                   f"매출 미대응 입금 {입금_미대응:,} — 현금매출 확인", 재무영향=입금_미대응 // 11)


def inventory_rollforward(기초재고: int, 당기매입: int, 매출원가: int, 장부기말: int) -> Finding:
    """재고 롤포워드. 계산기말 = 기초+매입−매출원가. 장부기말 < 계산 → 자가소비/증여/매출누락."""
    계산기말 = 기초재고 + 당기매입 - 매출원가
    if 장부기말 >= 계산기말:
        return Finding("재고롤포워드", "PASS", 근거="조심2018서1207",
                       상세=f"장부기말 {장부기말:,} ≥ 계산 {계산기말:,}")
    diff = 계산기말 - 장부기말
    return Finding("재고롤포워드", "FLAG", "중간", "조심2019서2074·2018서1207",
                   f"재고 {diff:,} 부족 — 자가소비/증여/매출누락 검토(시가 과세)", 재무영향=diff // 10)


# ---------------------------------------------------------------- B. 순환거래(결정론 신호)
def detect_circular_parties(vouchers) -> List[Finding]:
    """동일 사업자번호가 매출·매입에 동시 등장 = 순환거래 결정론 신호(그래프 cycle은 AI Layer2)."""
    매출 = {v.사업자번호 for v in vouchers if v.judgment.구분 == "매출" and v.사업자번호}
    매입 = {v.사업자번호 for v in vouchers if v.judgment.구분 == "매입" and v.사업자번호}
    dup = sorted(매출 & 매입)
    return [Finding("순환거래신호", "FLAG", "높음", "대법 2014두9912·조심2019서2571",
                    f"사업자번호 {b} 매출·매입 동시 등장 — 순환/자전거래 확인") for b in dup]


# ---------------------------------------------------------------- C. 겸영 안분 재계산
def apportionment_check(과세공급가액: int, 면세공급가액: int, 공통매입세액: int,
                        신고_불공제세액: Optional[int] = None) -> Finding:
    """공통매입세액 안분 재계산 + 안분생략 요건(5% & 500만) 판정."""
    총 = 과세공급가액 + 면세공급가액
    면세비율 = (면세공급가액 / 총) if 총 else 0.0
    생략 = 면세비율 < 안분생략_면세비율 and 공통매입세액 < 안분생략_공통매입
    재계산_불공제 = 0 if 생략 else round(공통매입세액 * 면세비율)
    if 신고_불공제세액 is None or 신고_불공제세액 == 재계산_불공제:
        return Finding("공통매입안분", "PASS", 근거="령§81",
                       상세=f"면세비율 {면세비율:.1%}, 생략 {생략}, 불공제 {재계산_불공제:,}")
    return Finding("공통매입안분", "FLAG", "중간", "부가세법 §40·령§81",
                   f"신고 불공제 {신고_불공제세액:,} ≠ 재계산 {재계산_불공제:,}(면세비율 {면세비율:.1%})",
                   재무영향=abs(신고_불공제세액 - 재계산_불공제))


# ---------------------------------------------------------------- D. 간주임대료 재계산
def deemed_rent_check(보증금: int, 임대일수: int, 신고_간주임대료: int,
                      이자율=간주임대료율_2026) -> Finding:
    """부동산임대 간주임대료 재계산 ↔ 신고."""
    재계산 = 보증금 * 이자율 * 임대일수 // (1000 * 365)
    if 신고_간주임대료 == 재계산:
        return Finding("간주임대료", "PASS", 근거="령§65", 상세=f"{재계산:,}")
    return Finding("간주임대료", "FLAG", "중간", "부가세법 §29⑩·령§65",
                   f"신고 {신고_간주임대료:,} ≠ 재계산 {재계산:,}(이자율 {이자율/10:.1f}%)",
                   재무영향=abs(신고_간주임대료 - 재계산) // 10)


# ---------------------------------------------------------------- E. 붙임서식 ↔ 본지 대사
def attachment_vs_return_check(f: ReturnForm, vouchers) -> List[Finding]:
    """세계합계표 합 ↔ (1), 공제받지못할명세 세액 ↔ (17)."""
    out = []
    매출세계 = sum(r["공급가액"] for r in sales_tax_invoice_list(vouchers))
    if 매출세계 == f.공급.get(1, 0):
        out.append(Finding("매출세계합계표↔(1)", "PASS"))
    else:
        out.append(Finding("매출세계합계표↔(1)", "FLAG", "높음", "붙임↔본지",
                           f"합계표 {매출세계:,} ≠ 본지(1) {f.공급.get(1,0):,}"))
    불공제세액 = sum(r["세액"] for r in non_deductible_detail(vouchers))
    if 불공제세액 == f.세액.get(17, 0):
        out.append(Finding("공제못할명세↔(17)", "PASS"))
    else:
        out.append(Finding("공제못할명세↔(17)", "FLAG", "높음", "붙임↔본지",
                           f"명세 {불공제세액:,} ≠ 본지(17) {f.세액.get(17,0):,}"))
    return out


# ---------------------------------------------------------------- 종합 러너
def run_reconcile(f: ReturnForm, vouchers, *, 수집_과세매출=None, 입금_미대응=0,
                  재고=None, 안분=None, 간주임대료=None) -> dict:
    """Layer 1 결정론 대사 전수 실행 → 완결성 리포트(PASS/FLAG)."""
    findings: List[Finding] = []
    findings += attachment_vs_return_check(f, vouchers)
    findings += detect_circular_parties(vouchers)
    if 수집_과세매출 is not None:
        findings.append(reconcile_sales_vs_hometax(f, 수집_과세매출))
    if 입금_미대응:
        findings.append(reconcile_deposits_vs_sales(입금_미대응))
    if 재고:
        findings.append(inventory_rollforward(**재고))
    if 안분:
        findings.append(apportionment_check(**안분))
    if 간주임대료:
        findings.append(deemed_rent_check(**간주임대료))
    flags = [x for x in findings if x.상태 == "FLAG"]
    return {"findings": findings, "PASS": len(findings) - len(flags),
            "FLAG": len(flags), "완결": len(flags) == 0,
            "총재무영향": sum(x.재무영향 for x in flags)}
