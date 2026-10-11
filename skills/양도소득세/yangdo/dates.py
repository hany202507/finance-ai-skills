# -*- coding: utf-8 -*-
"""기간 계산과 양도·취득 시기. 민법 초일 불산입에 따라 시작일 다음 날부터 센다."""
import calendar
import re
from datetime import date, datetime, timedelta

ISO_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


def to_date(v):
    """날짜 값을 date 로. 글자는 YYYY-MM-DD 만 받는다.

    date.fromisoformat 은 파이썬 3.11 부터 20261115 나 2026-W46-7 같은 글자도 받아서, 정규식을 먼저 걸어
    3.10 과 3.11 이상이 같은 입력에 같은 결과를 내게 한다.
    """
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if not isinstance(v, str) or not ISO_DATE.fullmatch(v):
        raise ValueError("날짜는 YYYY-MM-DD 글자로 적어야 합니다: %r" % (v,))
    return date.fromisoformat(v)


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

    보유기간으로 자른 뒤 겹치거나 맞닿은 구간을 하나로 합친다(같은 날을 두 번 세지 않는다).
    합친 구간이 하나면 full_years 로 세고, 여럿이면 일수 합을 365 로 나눠 버린다(근사).
    """
    hs, he = to_date(hold_start), to_date(hold_end)
    clipped = []
    for s, e in periods or []:
        s, e = max(to_date(s), hs), min(to_date(e), he)
        if e > s:
            clipped.append((s, e))
    merged = []
    for s, e in sorted(clipped):
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    if not merged:
        return 0, False
    if len(merged) == 1:
        return full_years(*merged[0]), False
    return sum((e - s).days for s, e in merged) // 365, True


AUCTION_BASIS = "매각대금 완납일(경매의 대금 청산일, 소득세법 제98조, 민사집행법 제135조)"
SALE_BASIS = "잔금일(대금 청산일, 소득세법 제98조)"


def _settle(balance, registration, auction=False):
    """대금 청산일과 등기접수일로 시기를 정한다(소득세법 제98조, 시행령 제162조①1호·2호).
    경매는 대금 청산일이 매수인이 매각대금을 다 낸 날이라 근거 문구를 그렇게 쓴다."""
    b, r = to_date(balance), to_date(registration)
    basis = AUCTION_BASIS if auction else SALE_BASIS
    if b and r:
        if r < b:
            return r, "등기접수일(대금 청산 전 등기, 시행령 제162조①2호)"
        return b, basis
    if b:
        return b, basis
    if r:
        return r, "등기접수일(대금 청산일 불분명, 시행령 제162조①1호)"
    return None, ""


def transfer_date(양도):
    """양도 시기. 경매는 매수인이 매각대금을 다 낸 날(대금완납일, 없으면 잔금일)이 대금 청산일이다."""
    t = 양도 or {}
    경매 = t.get("원인") == "경매"
    balance = (t.get("대금완납일") or t.get("잔금일")) if 경매 else t.get("잔금일")
    return _settle(balance, t.get("등기접수일"), 경매)


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
    d, why = _settle(balance, t.get("등기접수일"), 원인 == "경매")
    if 원인 == "분양" and d:
        done = [x for x in (to_date(t.get("사용승인일")), to_date(t.get("사실상사용일"))) if x]
        if done and d < min(done):
            return min(done), "완성일(사용승인일과 사실상 사용일 중 빠른 날, 시행령 제162조①8호 후단·4호)"
    return d, why


WEEKDAY_KO = "월화수목금토일"


def filing_deadline(kind, base, rs):
    """양도소득세 신고기한 (명목 기한, 토·일을 다음 월요일로 옮긴 기한).

    예정신고는 base(양도일, 허가 전 대금 청산이면 허가일)가 속하는 달의 말일에서 `신고기한.예정.개월` 달 뒤 말일(소득세법 제105조①1호),
    확정신고는 base 가 속하는 과세기간의 다음 연도 `신고기한.확정.월`·`신고기한.확정.일`(소득세법 제110조①)이다.
    기한의 끝이 토요일·일요일이면 그 다음날까지가 기한이다(국세기본법 제5조①). 공휴일·대체공휴일·노동절은 표가 없어 옮기지 못한다.
    """
    b = to_date(base)
    if kind == "예정":
        n = b.year * 12 + (b.month - 1) + rs.value("신고기한.예정.개월", b)
        year, month = n // 12, n % 12 + 1
        nominal = date(year, month, calendar.monthrange(year, month)[1])
    elif kind == "확정":
        nominal = date(b.year + 1, rs.value("신고기한.확정.월", b), rs.value("신고기한.확정.일", b))
    else:
        raise ValueError("신고 구분은 예정 또는 확정이어야 합니다: %r" % (kind,))
    adjusted = nominal
    while adjusted.weekday() >= 5:
        adjusted += timedelta(days=1)
    return nominal, adjusted

