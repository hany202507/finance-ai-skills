# -*- coding: utf-8 -*-
"""결산 기간에 들지 않는 행 제외 — Gridie 같은 DB 표를 기간으로 거르지 않고 넣어도 그 기간만 결산한다.

2026-10-16 마루키 1·2분기 표를 통째로 넣자 매출이 684,000,000(2분기 354,000,000)으로 잡혔는데,
숫자끼리는 맞아서 verify_close 가 ALL PASS 를 냈다. 엔진이 직접 거르는지 막는다.
"""
import os, sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from close_engine import Engine


def _eng(period, **kw):
    e = Engine.__new__(Engine)
    e.period = period; e.year = int(period[:4]); e.dropped = {}
    e.tax = e.bank = e.card = e.pay = e.chsales = e.setl = []
    e.opening = [("일자", "구분")]
    for k, v in kw.items():
        setattr(e, k, v)
    return e


def test_기간라벨이_덮는_달():
    assert _eng("2026Q2").period_months() == ["04", "05", "06"]
    assert _eng("2026H1").period_months() == ["01", "02", "03", "04", "05", "06"]
    assert _eng("2026-05").period_months() == ["05"]
    assert len(_eng("2026").period_months()) == 12


def test_분기_밖_행을_빼고_건수를_남긴다():
    e = _eng("2026Q2",
             bank=[("2026-03-31", 1), ("2026-04-01", 2), ("2026-06-30 09:00:00", 3), ("2025-05-01", 4)],
             pay=[("2026-03", 1), ("2026-04", 2)],
             opening=[("일자", "구분"),
                      ("2025-12-31", "전기이월"), ("2026-03-31", "전기이월"), (None, None), ("2026-03-31", "전기이월")])
    e._clip_period()
    assert [r[1] for r in e.bank] == [2, 3]
    assert [r[1] for r in e.pay] == [2]
    # 이월은 기간 첫날 전의 가장 늦은 날짜(2026-03-31)만 남는다
    assert [r[0] for r in e.opening[1:] if r[0]] == ["2026-03-31", "2026-03-31"]
    assert e.dropped == {"은행거래내역": 2, "급여대장": 1, "전기이월분개장": 1}


def test_기간_안이면_아무것도_안_뺀다():
    e = _eng("2026Q2", bank=[("2026-04-03", 1)], opening=[("일자", "구분"), ("2026-03-31", "전기이월")])
    e._clip_period()
    assert e.dropped == {} and len(e.bank) == 1 and len(e.opening) == 2
