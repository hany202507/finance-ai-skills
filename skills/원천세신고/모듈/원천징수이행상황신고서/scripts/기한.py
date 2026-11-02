# -*- coding: utf-8 -*-
"""귀속연월 → 지급연월·제출연월·작성일자(법정 신고납부기한).

근거
- 소득세법 §128① 매월납부: 원천징수한 소득세를 **징수일이 속하는 달의 다음 달 10일**까지 납부
  https://www.law.go.kr/법령/소득세법/제128조
- 소득세법 §128② 반기납부: **반기의 마지막 달의 다음 달 10일**까지
- 국세기본법 §5① 기한의 특례: 기한이 토요일·일요일·공휴일·대체공휴일·노동절이면 **그 다음 날**
  https://www.law.go.kr/법령/국세기본법/제5조

토·일 이월은 달력만으로 결정되므로 자동으로 한다. 공휴일은 음력 명절이 해마다 옮겨다녀
표 없이는 못 정한다. assets/공휴일.json 에 적어두면 함께 보고, 없으면 기한일이 공휴일인지
사람이 확인하도록 확인사항을 세운다 — 조용히 틀리는 것보다 낫다.
"""
import json
from datetime import date, timedelta
from pathlib import Path

공휴일표 = Path(__file__).resolve().parent.parent / "assets" / "공휴일.json"


def _공휴일(연도):
    """{'YYYY-MM-DD': '이름'} 과 그 해가 표에 있는지."""
    if not 공휴일표.exists():
        return {}, False
    t = json.loads(공휴일표.read_text(encoding="utf-8"))
    해 = t.get(str(연도))
    return (해 or {}), (해 is not None)


def 다음영업일(d):
    """토·일·표에 있는 공휴일이면 다음 날로 민다. 국기법 §5① 은 '그 다음날' 이라
    연휴면 한 번 더 걸리므로 걸리지 않을 때까지 반복한다."""
    휴, _ = _공휴일(d.year)
    while d.weekday() >= 5 or d.isoformat() in 휴:
        d += timedelta(days=1)
        휴, _ = _공휴일(d.year)
    return d


def 산출(귀속연월, 납부주기="매월", 지급연월=None):
    """귀속연월(YYYYMM) → 기간 dict.

    지급연월은 보통 귀속연월과 같지만 다를 수 있다(예: 2021년 12월분 퇴직금을
    2022년 2월에 지급 → 귀속 202112 · 지급 202202 · 제출 202203). 다르면 넘겨라.
    기한은 **지급연월** 기준이다 — 징수는 지급할 때 일어나기 때문이다.
    """
    y, m = int(귀속연월[:4]), int(귀속연월[4:6])
    지급 = 지급연월 or 귀속연월
    gy, gm = int(지급[:4]), int(지급[4:6])

    if 납부주기 == "반기":
        마지막 = 6 if gm <= 6 else 12
        기준y, 기준m = gy, 마지막
    else:
        기준y, 기준m = gy, gm

    ny, nm = (기준y + 1, 1) if 기준m == 12 else (기준y, 기준m + 1)
    법정 = date(ny, nm, 10)
    실제 = 다음영업일(법정)
    _, 표있음 = _공휴일(법정.year)

    return {
        "귀속연월": 귀속연월,
        "지급연월": 지급,
        "제출연월": f"{ny}{nm:02d}",
        "작성일자": 실제.strftime("%Y%m%d"),
        "신고구분": 납부주기,
        "_법정기한": 법정.isoformat(),
        "_실제기한": 실제.isoformat(),
        "_이월사유": ("토·일 이월" if 실제 != 법정 else ""),
        "_공휴일표": 표있음,
    }
