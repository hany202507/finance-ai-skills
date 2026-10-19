# -*- coding: utf-8 -*-
"""더존 SmartA 업로드 파일 산출 — Judgment + 전표 컨텍스트 → 매입매출전표(18컬럼)/일반전표.

양식 스펙: references/더존업로드양식.md. 계정매핑(기본/상대계정)은 호출측(회사 프로파일)이 제공.
불공제 사유코드는 라이브 더존 명세서 순번(2026-07-15 검증) 기준 단일 매핑.
"""
from dataclasses import dataclass, field
from typing import Optional, List
from vat_engine import Judgment, Routing, DenyReason

# 불공제 사유 → 더존 코드 (라이브 더존 「공제받지못할매입세액명세서」 순번, 2026-07-15)
# G3 확정(2026-07-15): 접대비는 실무상 54 불공이 아니라 일반전표 전액비용으로 처리
#   → 엔진 default가 접대를 일반전표 라우팅. 아래 접대비 코드는 54를 쓰는 회사용 잔존 매핑.
DENY_CODE = {
    DenyReason.필요적기재누락: "1",
    DenyReason.사업무관: "2",
    DenyReason.비영업용승용차: "3",
    DenyReason.면세관련: "4",
    DenyReason.토지관련: "5",
    DenyReason.등록전: "6",
    DenyReason.금스크랩계좌: "7",
    DenyReason.접대비: "2",   # 접대비를 54로 처리하는 회사용(엔진 default는 일반전표)
}

PURCHSALE_HEADER = ["년도", "월", "일", "매입매출구분", "과세유형", "불공제사유",
                    "신용카드거래처코드", "신용카드사명", "신용카드가맹점번호",
                    "거래처명", "사업자등록번호", "공급가액", "부가세", "품명",
                    "전자세금", "기본계정", "상대계정", "현금영수증승인번호"]
GENERAL_HEADER = ["월", "일", "구분", "계정과목코드", "계정과목명",
                  "거래처코드", "거래처", "적요", "차변", "대변"]


@dataclass
class Voucher:
    """경제적 사건 + 판단 + 더존 입력 컨텍스트."""
    년: int
    월: int
    일: int
    judgment: Judgment
    거래처명: str = ""
    사업자번호: str = ""            # 하이픈 없이(숫자형 대상)
    품명: str = ""
    적요: str = ""
    전자: bool = False
    기본계정: int = 0              # 손익/자산 계정코드(프로파일 제공)
    상대계정: int = 0              # 결제/채권채무
    기본계정명: str = ""
    상대계정명: str = ""
    거래처코드: str = ""           # 앞자리0 텍스트
    카드거래처코드: str = ""
    카드사명: str = ""
    카드가맹점번호: str = ""
    현금영수증승인번호: str = ""


def _bizno_int(s: str):
    """사업자번호는 숫자형(하이픈 제거). 빈값이면 ''."""
    d = str(s).replace("-", "").strip()
    return int(d) if d.isdigit() else ""


def douzone_purchsale_rows(vouchers) -> List[list]:
    """매입매출전표(18컬럼) 행. 라우팅=매입매출인 전표만."""
    rows = []
    for v in vouchers:
        j = v.judgment
        if j.라우팅 is not Routing.매입매출:
            continue
        구분 = 1 if j.구분 == "매출" else 2
        사유 = DENY_CODE.get(j.불공제사유, "") if j.불공제사유 else ""
        rows.append([
            v.년, v.월, v.일, 구분, j.과세유형, 사유,
            v.카드거래처코드, v.카드사명, v.카드가맹점번호,
            v.거래처명, _bizno_int(v.사업자번호), j.공급가, j.세액, v.품명,
            1 if v.전자 else "", v.기본계정, v.상대계정, v.현금영수증승인번호,
        ])
    return rows


def douzone_general_rows(vouchers) -> List[list]:
    """일반전표 행. 라우팅=일반인 전표를 차변/대변 2행 분개로."""
    rows = []
    for v in vouchers:
        j = v.judgment
        if j.라우팅 is not Routing.일반:
            continue
        금액 = j.공급가 + j.세액          # 전액비용/비과세 총액(세액 0)
        적요 = v.적요 or v.품명
        # 구분 3=차변, 4=대변
        rows.append([v.월, v.일, 3, v.기본계정, v.기본계정명, v.거래처코드, v.거래처명, 적요, 금액, 0])
        rows.append([v.월, v.일, 4, v.상대계정, v.상대계정명, v.거래처코드, v.거래처명, 적요, 0, 금액])
    return rows


def build_douzone_xlsx(vouchers, purchsale_path: str, general_path: str):
    """매입매출전표·일반전표 업로드 엑셀 2종 산출. 사업자번호=숫자형, 거래처코드=텍스트."""
    import openpyxl
    # 매입매출전표
    wb1 = openpyxl.Workbook()
    ws1 = wb1.active
    ws1.title = "매출자료 & 매입자료"
    ws1.append(PURCHSALE_HEADER)
    for r in douzone_purchsale_rows(vouchers):
        ws1.append(r)
    wb1.save(purchsale_path)
    # 일반전표
    wb2 = openpyxl.Workbook()
    ws2 = wb2.active
    ws2.title = "일반전표"
    ws2.append(GENERAL_HEADER)
    for r in douzone_general_rows(vouchers):
        # 거래처코드 앞자리0 보존 위해 문자열로
        r = list(r)
        r[5] = str(r[5]) if r[5] != "" else ""
        ws2.append(r)
    wb2.save(general_path)
    return purchsale_path, general_path
