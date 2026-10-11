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


class Holidays:
    """공휴일 표(rules/공휴일.json). 고정 공휴일은 월·일로 세고, 나머지는 연도별 날짜로 본다.

    `고정` 은 날짜가 해마다 같은 공휴일과 노동절이다(시작·끝으로 공휴일이던 기간을 가른다).
    `연도` 는 정부 발표로 확인한 해의 설날·추석 연휴, 부처님 오신 날, 대체공휴일, 선거일, 임시공휴일 날짜다.
    대체공휴일을 규칙으로 계산하지 않는다. 표에 없는 해의 그런 날은 모른다.
    """

    def __init__(self, data):
        self.fixed = [(int(f["월"]), int(f["일"]), f["이름"], to_date(f.get("시작")), to_date(f.get("끝")))
                      for f in data.get("고정", [])]
        self.days, self.years = {}, set()
        for year, y in (data.get("연도") or {}).items():
            # 날짜가 빈 해를 덮는 해로 세면 그 해의 연휴를 아는 것처럼 된다. 확인일과 출처가 없는 해도 받지 않는다
            lacking = [k for k in ("확인일", "출처", "날짜") if not y.get(k)]
            if lacking:
                raise ValueError("공휴일 표의 %s년에 %s 이 없다" % (year, "·".join(lacking)))
            to_date(y["확인일"])
            for x in y["날짜"]:
                d = to_date(x["날짜"])
                if d.year != int(year):
                    raise ValueError("공휴일 표의 %s년에 다른 해의 날짜가 있다: %s" % (year, d))
                if d in self.days:
                    raise ValueError("공휴일 표의 %s년에 같은 날짜가 두 번 있다: %s" % (year, d))
                self.days[d] = x["이름"]
            self.years.add(int(year))

    def covers(self, year):
        """그 해의 설날·추석 연휴, 대체공휴일 등이 표에 있는지."""
        return year in self.years

    def name(self, day):
        """공휴일이면 이름, 아니면 None. 토요일·일요일은 여기서 보지 않는다."""
        for m, d, name, start, end in self.fixed:
            if (day.month, day.day) == (m, d) and (start is None or start <= day) and (end is None or day <= end):
                return name
        return self.days.get(day)


class Deadline(tuple):
    """신고기한 (명목 기한, 옮긴 기한). 예전처럼 두 값으로 풀어 쓴다.

    공휴일표: 명목 기한부터 옮긴 기한까지의 해가 모두 공휴일 표에 있으면 True. False 면 그 해의 설날·추석 연휴,
              대체공휴일, 선거일, 임시공휴일을 모르고 옮긴 기한이라 실제 기한이 더 늦을 수 있다.
    옮긴이유: 기한에서 건너뛴 날과 이유 ((날짜, "일요일"), (날짜, "3·1절"), ...). 옮기지 않았으면 빈 튜플.
    """

    def __new__(cls, nominal, adjusted, covered, moved):
        self = super().__new__(cls, (nominal, adjusted))
        self.공휴일표 = covered
        self.옮긴이유 = tuple(moved)
        return self

    def __getnewargs__(self):
        """copy·deepcopy·pickle 이 네 값으로 다시 만들게 한다(없으면 두 값 튜플 하나만 넘겨 TypeError)."""
        return self[0], self[1], self.공휴일표, self.옮긴이유


def skipped_text(deadline):
    """신고기한에서 건너뛴 날과 이유를 「2027-02-28(일요일), 2027-03-01(3·1절)」 꼴로 적는다. 옮기지 않았으면 빈 글자.
    확인사항과 다루지않음 문장이 기한을 왜 옮겼는지 그대로 적을 때 쓴다."""
    return ", ".join("%s(%s)" % (d.isoformat(), why) for d, why in getattr(deadline, "옮긴이유", ()))


def filing_deadline(kind, base, rs):
    """양도소득세 신고기한 (명목 기한, 토·일·공휴일·노동절이 아닌 첫 날로 옮긴 기한). Deadline 을 돌려준다.

    예정신고는 base(양도일, 허가 전 대금 청산이면 허가일)가 속하는 달의 말일에서 `신고기한.예정.개월` 달 뒤 말일(소득세법 제105조①1호),
    확정신고는 base 가 속하는 과세기간의 다음 연도 `신고기한.확정.월`·`신고기한.확정.일`(소득세법 제110조①)이다.
    기한이 토요일·일요일, 공휴일·대체공휴일, 노동절이면 그 다음날까지가 기한이다(국세기본법 제5조①).
    공휴일은 규칙세트가 읽은 공휴일 표(rs.공휴일)로 본다. 표가 덮지 않는 해는 토·일과 날짜가 고정된 공휴일·노동절만 옮기고,
    표가 아예 없는 규칙세트는 토·일만 옮긴다. 두 경우 모두 결과의 `공휴일표` 가 False 다.
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
    return _moved(nominal, rs)


def _moved(nominal, rs):
    """명목 기한을 토요일·일요일·공휴일·대체공휴일·노동절이 아닌 첫 날로 옮겨 Deadline 으로 돌려준다."""
    table = getattr(rs, "공휴일", None)
    adjusted, moved = nominal, []
    while True:
        if adjusted.weekday() >= 5:
            why = WEEKDAY_KO[adjusted.weekday()] + "요일"
        else:
            why = table.name(adjusted) if table is not None else None
        if why is None:
            break
        moved.append((adjusted, why))
        adjusted += timedelta(days=1)
    covered = table is not None and all(table.covers(y) for y in range(nominal.year, adjusted.year + 1))
    return Deadline(nominal, adjusted, covered, moved)


def add_months(day, months):
    """기한에 개월 수를 더한 날. 민법의 기간 계산을 따른다: 기한 다음 날이 기산일이고, 마지막 달에서 기산일에 해당하는 날의
    전날에 끝난다. 그 달에 해당하는 날이 없으면 그 달의 말일에 끝난다. 말일인 기한에 더하면 다시 말일이 된다."""
    start = to_date(day) + timedelta(days=1)
    n = start.year * 12 + (start.month - 1) + int(months)
    year, month = n // 12, n % 12 + 1
    last = calendar.monthrange(year, month)[1]
    if start.day > last:
        return date(year, month, last)
    return date(year, month, start.day) - timedelta(days=1)


# 분납 기한: 소득세법 제112조 「납부기한이 지난 후 2개월 이내」. 개월 수는 조문에 적힌 값이라 규칙세트에 두지 않는다
INSTALLMENT_MONTHS = 2


def installment_deadline(filing, rs):
    """분납할 세액의 납부 기한 Deadline. filing 은 신고·납부 기한(filing_deadline 의 결과, 옮긴 기한을 쓴다).

    옮긴 기한에서 2개월 뒤 같은 날(add_months)이고, 그날이 토요일·일요일·공휴일·대체공휴일·노동절이면 다음 평일이다.
    조문은 「납부기한이 지난 후 2개월 이내」만 적고 기한을 세는 법은 적지 않아서, 어느 날에서 세는지와 쉬는 날을 옮기는 것은
    이 스킬의 가정이다. 실제 기한은 홈택스 분납 납부서에 적힌 날짜를 따른다."""
    return _moved(add_months(filing[1], INSTALLMENT_MONTHS), rs)


def local_filing_deadline(kind, base, rs):
    """양도소득에 대한 개인지방소득세의 신고기한(명목 기한, 옮긴 기한). Deadline 을 돌려준다.

    소득세법이 정한 신고기한(filing_deadline 의 명목 기한, 토·일·공휴일이라 옮기기 전)에 `지방.신고기한.가산개월` 을 더한 날이다
    (지방세법 제103조의5①, 제103조의7①). 달 계산은 add_months(지방세기본법 제23조가 민법을 따르게 한다).
    더한 날이 토요일·일요일·공휴일·대체공휴일·노동절이면 그 다음 날이 기한이다(지방세기본법 제24조①). 국세와 같은 공휴일 표를 쓴다.
    국세 기한이 쉬는 날이라 옮겨진 경우 어느 날에 더하는지는 조문에 없다. 옮기기 전의 기한에 더하는 것으로 정했다(확인사항으로 알린다).
    """
    national = filing_deadline(kind, base, rs)[0]
    return _moved(add_months(national, rs.value("지방.신고기한.가산개월", to_date(base))), rs)
