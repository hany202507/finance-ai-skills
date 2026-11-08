"""JSON 수식이 부르는 계산 도우미. corptax-impl `engine/forms/fx.py` 에서 서식 목업에 필요한 것만 옮겼다(39호 재고자산
평가 판정은 뺐다).

  rounddown(x, digits=0)       엑셀 ROUNDDOWN. 0 쪽으로 자른다
  xround(x, digits=0)          엑셀 ROUND. .5 는 0 에서 먼 쪽으로 올린다(파이썬 round 는 짝수 쪽이라 다르다)
  band(base, brackets, k)      구간표의 k 번째(0부터) 구간에 들어가는 금액 x 율, 원 미만 버림(23호(갑) ⑤ · ⑥ 줄)
  progressive(base, brackets)  구간표로 누진 계산한 세액, 원 미만 버림, 0 이하면 0(3호 12)
  bracket_rate(base, brackets) base 가 들어가는 구간의 율. 0 이하면 첫 구간 율(3호 11)
  min_tax_brackets(brackets, grace, year)  4호 ③ 최저한세율 구간표. 중소기업 졸업 유예 연차가 있으면 그 율 하나

brackets 는 params 의 구간표 모양 [(상한, 율), ...] 이고 마지막 상한 None 이 초과분이다. 금액 계산은 Decimal 로 해서
3,298,066,287 x 0.002 같은 곱이 부동소수 오차로 1원 어긋나지 않게 한다.
"""
from __future__ import annotations

from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal


def _dec(x) -> Decimal:
    return Decimal(str(x if x is not None else 0))


def _quantize(v: Decimal, digits: int, rounding):
    q = Decimal(1).scaleb(-int(digits))
    out = v.quantize(q, rounding=rounding)
    return int(out) if int(digits) <= 0 else float(out)


def rounddown(x, digits=0):
    """엑셀 ROUNDDOWN(x, digits)."""
    return _quantize(_dec(x), digits, ROUND_DOWN)


def xround(x, digits=0):
    """엑셀 ROUND(x, digits)."""
    return _quantize(_dec(x), digits, ROUND_HALF_UP)


def _band_exact(base, brackets, k: int) -> Decimal:
    lower = Decimal(0) if k == 0 else _dec(brackets[k - 1][0])
    upper, rate = brackets[k]
    top = _dec(base) if upper is None else min(_dec(base), _dec(upper))
    return max(top - lower, Decimal(0)) * _dec(rate)


def band(base, brackets, k):
    """k 번째 구간 금액 x 율(원 미만 버림)."""
    return rounddown(_band_exact(base, brackets, int(k)))


def progressive(base, brackets):
    """구간 누진 세액(구간마다 더한 뒤 원 미만 버림). base 가 0 이하면 0."""
    return rounddown(sum((_band_exact(base, brackets, k) for k in range(len(brackets))), Decimal(0)))


def bracket_rate(base, brackets):
    """base 가 들어가는 구간의 율."""
    for upper, rate in brackets:
        if upper is None or _dec(base) <= _dec(upper):
            return rate
    return brackets[-1][1]


def min_tax_brackets(brackets, grace, year):
    """4호 ③최저한세 열이 쓰는 최저한세율 구간표(corptax-impl fx 에서 옮김). brackets 는 params 최저한세율, grace 는
    params 최저한세율.졸업유예 [(유예기간 종료후 연차 상한, 율), ...], year 는 4호 (127) 유예기간 종료후 연차다. 연차가 grace
    의 어느 상한 안이면 그 율 하나짜리 구간표, 아니면 brackets 그대로다."""
    n = int(_dec(year)) if year not in (None, "") else 0
    if n >= 1:
        for upper, rate in grace:
            if n <= upper:
                return [(None, rate)]
    return brackets
