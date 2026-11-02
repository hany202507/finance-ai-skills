# -*- coding: utf-8 -*-
"""소득유형별 원천징수 판정 코어 — 결정론. 사실 미비 시 InfoRequest(회계사에 안 미룸).

PaymentInput(정규화 지급건) → WithholdingResult(세액 확정) | InfoRequest(필요사실 질의).
지방소득세 특별징수 = 소득세 × 10%(원 미만 절사). 세액 계산 Decimal 정밀.
근거: 소득세법 §127~129·§156, 시행령 §87·§189, 지방세법 §103의13.
"""
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_DOWN
from enum import Enum

import simple_tax_table


class 소득유형(Enum):
    근로 = "근로"
    상여 = "상여"
    일용 = "일용"
    사업 = "사업"
    기타 = "기타"
    사용료 = "사용료"


# 기타소득 종류별 법정 필요경비율 (소득령 §87). 실제경비만 인정하는 종류는 None → 사실요청.
기타경비율 = {
    "강연료": Decimal("0.6"), "원고료": Decimal("0.6"), "인적용역": Decimal("0.6"),
    "사례금": Decimal("0.6"), "자문료": Decimal("0.6"),
    "공익상금": Decimal("0.8"), "다수기획상금": Decimal("0.8"),
    "위약금": None, "배상금": None, "부동산권리금": None,  # 실제경비만
}
기타_과세최저 = 50_000        # 건별 기타소득금액 5만원 이하 과세제외 (소득법 §84)
일용_공제 = 150_000          # 일 15만원 근로소득공제 (소득법 §47)
일용_세율 = Decimal("0.06")
일용_세액공제율 = Decimal("0.55")   # 근로소득세액공제 55%
일용_소액부징수 = 1_000
사업_세율 = Decimal("0.03")
기타_세율 = Decimal("0.2")


@dataclass
class PaymentInput:
    소득유형: "소득유형"
    지급총액: int
    귀속연월: str                       # 'YYYY-MM'
    payee: dict                          # resident_type, 공제대상가족수, 자녀8_20세수, 비율…
    비과세: int = 0
    필요경비: int = None                 # 기타소득 실제경비(있으면 우선)
    기타소득종류: str = None
    사실: dict = field(default_factory=dict)


@dataclass
class WithholdingResult:
    소득세: int
    지방소득세: int
    적용룰: str
    근거: str
    지급총액: int
    소득유형: "소득유형"


@dataclass
class InfoRequest:
    필요사실: list
    사유: str
    소득유형: "소득유형"


def _지방세(소득세):
    """개인지방소득세 특별징수 = 소득세 × 10%, **10원 미만 버림**.

    국고금관리법 §47(단수 버림). 예: 소득세 307,420 → 지방세 30,740(30,742 아님).
    """
    return 소득세 // 10 // 10 * 10


def _floor(dec):
    return int(dec.to_integral_value(rounding=ROUND_DOWN))


def judge(p, on_date, conn=None):
    """지급건을 판정해 WithholdingResult 또는 InfoRequest를 반환.

    on_date: 지급일 'YYYY-MM-DD'. 세액표·요율·조약의 효력일자 판정 기준.
    """
    t = p.소득유형
    비거주자 = p.payee.get("resident_type") == "비거주자"

    if 비거주자:
        return _judge_비거주자(p, on_date)

    if t in (소득유형.근로, 소득유형.상여):
        return _judge_근로(p, on_date, conn)
    if t == 소득유형.일용:
        return _judge_일용(p)
    if t == 소득유형.사업:
        return _judge_사업(p)
    if t == 소득유형.기타:
        return _judge_기타(p)
    if t == 소득유형.사용료:
        return _judge_사용료_거주자(p)
    raise ValueError(f"미지원 소득유형: {t}")


def _judge_근로(p, on_date, conn):
    if conn is None:
        raise ValueError("근로소득 판정은 간이세액표 DB 연결(conn) 필요")
    과세 = p.지급총액 - p.비과세
    가족수 = p.payee.get("공제대상가족수", 1)
    자녀 = p.payee.get("자녀8_20세수", 0)
    비율 = p.payee.get("비율", 100)
    소득세 = simple_tax_table.lookup(conn, 과세, 가족수, on_date=on_date,
                                    자녀8_20세수=자녀, 비율=비율)
    # 지급총액 = 과세지급액(비과세 제외) — 이행상황신고서 ⑤총지급액 기준(실제 신고서 확증:
    # 2026-06 신고 6,910,000 = 과세합. 비과세 포함 gross 아님)
    return WithholdingResult(소득세, _지방세(소득세), "근로-간이세액표",
                             "소득령 §189 별표2", 과세, p.소득유형)


def _judge_일용(p):
    """일용근로: (일급−15만)×6%×(1−55%). 일 산출세액 1,000원 미만 소액부징수."""
    일급 = p.사실.get("일급", p.지급총액)
    일수 = p.사실.get("일수", 1)
    과세일급 = max(0, 일급 - 일용_공제)
    일세액 = _floor(Decimal(과세일급) * 일용_세율 * (1 - 일용_세액공제율))
    if 일세액 < 일용_소액부징수:
        일세액 = 0
    소득세 = 일세액 * 일수
    return WithholdingResult(소득세, _지방세(소득세), "일용-6%×45%",
                             "소득법 §47·§129①4", p.지급총액, p.소득유형)


def _judge_사업(p):
    소득세 = _floor(Decimal(p.지급총액) * 사업_세율)
    return WithholdingResult(소득세, _지방세(소득세), "사업-3%",
                             "소득법 §129①3", p.지급총액, p.소득유형)


def _judge_기타(p):
    종류 = p.기타소득종류
    if p.필요경비 is not None:
        경비 = p.필요경비
    else:
        if 종류 not in 기타경비율:
            return InfoRequest(["기타소득 종류(경비율 확정)", "실제 필요경비"],
                               f"기타소득 종류 '{종류}' 경비율 미확정 — 종류 또는 실제경비 필요",
                               p.소득유형)
        율 = 기타경비율[종류]
        if 율 is None:
            return InfoRequest(["실제 필요경비"],
                               f"'{종류}'는 법정경비율 없음 — 실제경비 입력 필요", p.소득유형)
        경비 = _floor(Decimal(p.지급총액) * 율)
    소득금액 = p.지급총액 - 경비
    if 소득금액 <= 기타_과세최저:
        return WithholdingResult(0, 0, "기타-과세최저",
                                 "소득법 §84 과세최저한", p.지급총액, p.소득유형)
    소득세 = _floor(Decimal(소득금액) * 기타_세율)
    return WithholdingResult(소득세, _지방세(소득세), "기타-20%",
                             "소득법 §21·129①6, 령§87", p.지급총액, p.소득유형)


def _judge_사용료_거주자(p):
    """거주자 사용료: 계속·반복성 사실로 사업/기타 구분."""
    구분 = p.사실.get("구분")           # '사업' | '기타'
    if 구분 is None:
        return InfoRequest(["계속·반복성 여부(사업소득)", "일시·우발 여부(기타소득)"],
                           "사용료의 사업/기타 구분 사실 필요", p.소득유형)
    if 구분 == "사업":
        return _judge_사업(p)
    p.기타소득종류 = p.기타소득종류 or "인적용역"
    return _judge_기타(p)


def _judge_비거주자(p, on_date):
    필수 = ["거주지국", "수익적소유자 여부", "거주자증명서 유무"]
    없는것 = [k for k in ("거주지국", "수익적소유자", "거주자증명서") if k not in p.사실]
    if 없는것:
        return InfoRequest(필수,
                           "비거주자 원천징수 — 조세조약 제한세율 판정에 필요사실 미비",
                           p.소득유형)
    import treaty_rates
    return treaty_rates.apply_비거주자(p, on_date)
