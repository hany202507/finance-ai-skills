# -*- coding: utf-8 -*-
"""연말정산 세액공제 — 근로·자녀·연금계좌·보장성·의료비·교육비·기부금·월세·표준. 결정론.

근거: 소득세법 §59·§59의2~4, 조특법 §95의2(월세). 앵커 2025 귀속(자녀공제 상향 반영).
부족 사실은 InfoRequest(중복배제·실손수령 등).
"""
from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN

from withholding_engine import InfoRequest
from yearend_param import get_param


@dataclass
class 세액공제결과:
    근로: int
    자녀: int
    연금계좌: int
    보장성: int
    의료비: int
    교육비: int
    기부금: int
    월세: int
    표준: int
    공제계: int


def _floor(x):
    return int(Decimal(x).to_integral_value(rounding=ROUND_DOWN))


def 근로소득세액공제(총급여, 산출세액):
    """소득법 §59: 130만 이하 55%, 초과 71.5만+초과분 30%. 총급여별 한도."""
    if 산출세액 <= 1_300_000:
        공제 = _floor(Decimal(산출세액) * Decimal("0.55"))
    else:
        공제 = 715_000 + _floor(Decimal(산출세액 - 1_300_000) * Decimal("0.30"))
    # 총급여별 한도
    if 총급여 <= 33_000_000:
        한도 = 740_000
    elif 총급여 <= 70_000_000:
        한도 = max(660_000, 740_000 - _floor(Decimal(총급여 - 33_000_000) * Decimal("0.008")))
    elif 총급여 <= 120_000_000:
        한도 = max(500_000, 660_000 - _floor(Decimal(총급여 - 70_000_000) * Decimal("0.5")))
    else:
        한도 = max(200_000, 500_000 - _floor(Decimal(총급여 - 120_000_000) * Decimal("0.5")))
    return min(공제, 한도)


def _자녀(conn, 귀속연도, n):
    if n <= 0:
        return 0
    if n == 1:
        return get_param(conn, 귀속연도, "자녀공제_1명")
    if n == 2:
        return get_param(conn, 귀속연도, "자녀공제_2명")
    return get_param(conn, 귀속연도, "자녀공제_2명") + (n - 2) * get_param(conn, 귀속연도, "자녀공제_추가")


def _연금계좌(conn, 귀속연도, 총급여, 자료):
    저축 = min(자료.get("연금저축", 0), get_param(conn, 귀속연도, "연금저축_한도"))
    합 = min(저축 + 자료.get("IRP", 0), get_param(conn, 귀속연도, "연금계좌_한도"))
    율 = Decimal("0.15") if 총급여 <= 55_000_000 else Decimal("0.12")
    return _floor(Decimal(합) * 율)


def _의료비(conn, 귀속연도, 총급여, 자료):
    """총급여 3% 초과분 15%, 난임 30%, 미숙아·선천성 20%. 실손수령분 차감."""
    med = 자료.get("의료비", {})
    문턱 = _floor(Decimal(총급여) * get_param(conn, 귀속연도, "의료비_문턱율") / 100)
    본인등 = med.get("본인65세장애6세이하", 0)
    난임 = med.get("난임", 0)
    미숙아 = med.get("미숙아선천성", 0)
    일반 = med.get("일반", 0)
    실손 = med.get("실손수령", 0)
    지출 = 본인등 + 난임 + 미숙아 + 일반 - 실손
    if 지출 <= 문턱:
        return 0
    # 문턱은 공제율 낮은 일반분부터 소진(납세자 유리)
    한도 = get_param(conn, 귀속연도, "의료비_기타한도")
    일반순 = max(0, min(일반, 일반 - 실손))
    쓸일반 = max(0, 일반순 - 문턱)                       # 일반분(한도 700만)
    쓸일반 = min(쓸일반, 한도)
    남은문턱 = max(0, 문턱 - 일반순)
    공제 = _floor(Decimal(쓸일반) * Decimal("0.15"))
    공제 += _floor(Decimal(max(0, 본인등 - 남은문턱)) * Decimal("0.15"))
    공제 += _floor(Decimal(미숙아) * Decimal("0.20"))
    공제 += _floor(Decimal(난임) * Decimal("0.30"))
    return 공제


def compute(conn, 귀속연도, 자료, 총급여, 산출세액):
    근로 = 근로소득세액공제(총급여, 산출세액)
    자녀 = _자녀(conn, 귀속연도, 자료.get("자녀세액공제대상", 0))
    연금계좌 = _연금계좌(conn, 귀속연도, 총급여, 자료)
    보장성 = min(_floor(Decimal(자료.get("보장성보험료", 0)) * Decimal("0.12")),
               _floor(Decimal(get_param(conn, 귀속연도, "보장성_한도")) * Decimal("0.12")))
    의료비 = _의료비(conn, 귀속연도, 총급여, 자료)
    교육비 = _floor(Decimal(자료.get("교육비", 0)) * Decimal("0.15"))
    기부 = 자료.get("기부금", 0)
    기부금 = (_floor(Decimal(기부) * Decimal("0.15")) if 기부 <= 10_000_000
             else _floor(Decimal(10_000_000) * Decimal("0.15"))
                  + _floor(Decimal(기부 - 10_000_000) * Decimal("0.30")))
    # 월세: 총급여 8,000만 이하 무주택 세대주 요건(2025 귀속 기준 상향 7천→8천). 대상한도 1,000만(750만→상향).
    if 총급여 <= 80_000_000 and 자료.get("월세액"):
        월세대상 = min(자료["월세액"], get_param(conn, 귀속연도, "월세_대상한도"))
        월세율 = Decimal("0.17") if 총급여 <= 55_000_000 else Decimal("0.15")
        월세 = _floor(Decimal(월세대상) * 월세율)
    else:
        월세 = 0

    특별세액 = 보장성 + 의료비 + 교육비 + 기부금 + 월세
    표준 = 0
    if 특별세액 == 0 and 자료.get("주택자금", 0) == 0:
        표준 = get_param(conn, 귀속연도, "표준세액공제")

    공제계 = 근로 + 자녀 + 연금계좌 + 특별세액 + 표준
    return 세액공제결과(근로, 자녀, 연금계좌, 보장성, 의료비, 교육비,
                     기부금, 월세, 표준, 공제계)
