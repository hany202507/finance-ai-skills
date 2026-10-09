# -*- coding: utf-8 -*-
"""기간 계산과 양도·취득 시기. 민법 초일 불산입에 따라 시작일 다음 날부터 센다."""
from datetime import date, datetime


def to_date(v):
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v.date()
    return v if isinstance(v, date) else date.fromisoformat(str(v))


def add_years(x, n):
    x = to_date(x)
    try:
        return x.replace(year=x.year + n)
    except ValueError:  # 2월 29일
        return x.replace(year=x.year + n, day=28)


def full_years(start, end):
    """start 부터 end 까지 채운 햇수. add_years(start, N) <= end 인 가장 큰 N."""
    s, e = to_date(start), to_date(end)
    if e < s:
        raise ValueError("끝날이 시작날보다 앞섭니다: %s < %s" % (e, s))
    n = e.year - s.year
    if add_years(s, n) > e:
        n -= 1
    return n


def within_years(start, end, n):
    """end 가 start 로부터 n 년 안(마지막 날 포함)에 드는지."""
    return to_date(end) <= add_years(start, n)


def residence_years(periods, hold_start, hold_end):
    """보유기간 안에 든 거주기간의 햇수와 근사 여부.

    구간이 하나면 full_years 로 세고, 여럿이면 일수 합을 365 로 나눠 버린다(근사).
    """
    hs, he = to_date(hold_start), to_date(hold_end)
    clipped = []
    for s, e in periods or []:
        s, e = max(to_date(s), hs), min(to_date(e), he)
        if e > s:
            clipped.append((s, e))
    if not clipped:
        return 0, False
    if len(clipped) == 1:
        return full_years(*clipped[0]), False
    return sum((e - s).days for s, e in clipped) // 365, True


def _settle(balance, registration):
    """대금 청산일과 등기접수일로 시기를 정한다(소득세법 제98조, 시행령 제162조①1호·2호)."""
    b, r = to_date(balance), to_date(registration)
    if b and r:
        if r < b:
            return r, "등기접수일(대금 청산 전 등기, 시행령 제162조①2호)"
        return b, "잔금일(대금 청산일, 소득세법 제98조)"
    if b:
        return b, "잔금일(대금 청산일, 소득세법 제98조)"
    if r:
        return r, "등기접수일(대금 청산일 불분명, 시행령 제162조①1호)"
    return None, ""


def transfer_date(양도):
    """양도 시기. 경매는 매수인이 매각대금을 다 낸 날(대금완납일, 없으면 잔금일)이 대금 청산일이다."""
    t = 양도 or {}
    balance = (t.get("대금완납일") or t.get("잔금일")) if t.get("원인") == "경매" else t.get("잔금일")
    return _settle(balance, t.get("등기접수일"))


def acquisition_date(취득):
    t = 취득 or {}
    원인 = t.get("원인")
    if 원인 == "신축":
        cands = [to_date(t.get(k)) for k in ("사용승인일", "사실상사용일")]
        cands = [c for c in cands if c]
        if cands:
            return min(cands), "사용승인일과 사실상 사용일 중 빠른 날(시행령 제162조①4호)"
        return None, ""
    balance = (t.get("대금완납일") or t.get("잔금일")) if 원인 == "경매" else t.get("잔금일")
    d, why = _settle(balance, t.get("등기접수일"))
    if 원인 == "분양" and d:
        done = [x for x in (to_date(t.get("사용승인일")), to_date(t.get("사실상사용일"))) if x]
        if done and d < min(done):
            return min(done), "완성일(사용승인일과 사실상 사용일 중 빠른 날, 시행령 제162조①8호 후단·4호)"
    return d, why
