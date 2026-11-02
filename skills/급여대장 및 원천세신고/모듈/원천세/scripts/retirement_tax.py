# -*- coding: utf-8 -*-
"""퇴직소득세(퇴직금관리) 엔진 — 연분연승법. 결정론.

파이프라인(소득세법 §48 퇴직소득공제·§55 세율·§14④ 연분연승):
  퇴직급여 → 근속연수공제 → (퇴직급여−공제)÷근속연수×12 = 환산급여
  → 환산급여공제 → 과세표준 → ×기본세율 = 환산산출세액
  → ÷12×근속연수 = 산출세액 → 지방소득세 = ×10%
근속연수: 1년 미만은 1년으로(§48①). 원문 대사값(2026.7.18).
IRP 과세이연·임원 한도초과는 InfoRequest.
설계: 퇴직소득세 엔진.
"""
import math
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_DOWN

from withholding_engine import InfoRequest
from yearend_param import 산출세액 as 기본세율_산출세액

# §48①1 근속연수공제: (근속연수 상한, 기본액, 초과단가, 기준연수)
근속연수공제표 = [
    (5, 0, 1_000_000, 0),
    (10, 5_000_000, 2_000_000, 5),
    (20, 15_000_000, 2_500_000, 10),
    (999, 40_000_000, 3_000_000, 20),
]
# §48①2 환산급여공제: (환산급여 상한, 기본액, 초과율, 기준액)
환산급여공제표 = [
    (8_000_000, 0, Decimal("1.0"), 0),
    (70_000_000, 8_000_000, Decimal("0.6"), 8_000_000),
    (100_000_000, 45_200_000, Decimal("0.55"), 70_000_000),
    (300_000_000, 61_700_000, Decimal("0.45"), 100_000_000),
    (10**15, 151_700_000, Decimal("0.35"), 300_000_000),
]


@dataclass
class RetirementTax:
    퇴직급여: int
    근속연수: int
    근속연수공제: int
    환산급여: int
    환산급여공제: int
    과세표준: int
    환산산출세액: int
    산출세액: int
    지방소득세: int
    명세: dict = field(default_factory=dict)


def _floor(x):
    return int(Decimal(x).to_integral_value(rounding=ROUND_DOWN))


def 근속연수(입사일, 퇴사일):
    """§48① — 근속연수, 1년 미만은 1년으로 절상. 만N년(응당일)은 잔여 없음."""
    from datetime import date
    d0, d1 = date.fromisoformat(입사일), date.fromisoformat(퇴사일)
    years = d1.year - d0.year
    if (d1.month, d1.day) < (d0.month, d0.day):
        years -= 1                                  # 완전 경과연수
    if not (d1.month == d0.month and d1.day == d0.day):
        years += 1                                  # 1년 미만 잔여 → 절상
    return max(1, years)


def _근속연수공제(n):
    for 상한, 기본, 단가, 기준 in 근속연수공제표:
        if n <= 상한:
            return 기본 + 단가 * (n - 기준)
    raise ValueError


def _환산급여공제(환산급여):
    for 상한, 기본, 율, 기준 in 환산급여공제표:
        if 환산급여 <= 상한:
            return 기본 + _floor(Decimal(환산급여 - 기준) * 율)
    raise ValueError


def settle(conn, 퇴직급여, 입사일, 퇴사일, *, 사실=None, 귀속연도=None):
    """퇴직소득세 산출. IRP 과세이연·임원 한도초과 사실 미비 시 InfoRequest."""
    사실 = 사실 or {}
    귀속연도 = 귀속연도 or int(퇴사일[:4])

    # 과세이연: IRP 등 연금계좌 이체 시 원천징수하지 않음(명세만) — 여부 필요
    if 사실.get("연금계좌이체") is None:
        return InfoRequest(["IRP 등 연금계좌 이체(과세이연) 여부"],
                           "과세이연 시 원천징수 안 함(이연퇴직소득 명세만) — 소득법 §146의2", None)
    if 사실.get("임원") and 사실.get("임원한도초과액") is None:
        return InfoRequest(["임원 퇴직소득 한도초과액(초과분은 근로소득)"],
                           "임원 퇴직금 한도초과분은 근로소득 과세 — 소득법 §22③", None)

    과세대상 = 퇴직급여 - 사실.get("임원한도초과액", 0)   # 초과분은 근로소득으로 분리(별도)
    n = 근속연수(입사일, 퇴사일)
    공제 = min(_근속연수공제(n), 과세대상)                 # §48② 미달 시 전액
    환산급여 = _floor(Decimal(과세대상 - 공제) / n * 12)
    환산공제 = _환산급여공제(환산급여)
    과표 = max(0, 환산급여 - 환산공제)

    if 사실.get("연금계좌이체"):
        # 과세이연: 원천징수 0, 이연퇴직소득 명세만
        return RetirementTax(퇴직급여, n, 공제, 환산급여, 환산공제, 과표, 0, 0, 0,
                             {"과세이연": True, "이연퇴직소득": 과세대상,
                              "비고": "연금계좌 이체 — 원천징수 안 함(수령 시 연금/기타소득 과세)"})

    환산산출 = 기본세율_산출세액(과표, conn, 귀속연도)      # §55 기본세율
    산출 = _floor(Decimal(환산산출) / 12 * n)               # 연분연승
    지방 = 산출 // 10
    return RetirementTax(퇴직급여, n, 공제, 환산급여, 환산공제, 과표, 환산산출, 산출, 지방,
                         {"연분연승": f"{환산산출}÷12×{n}"})
