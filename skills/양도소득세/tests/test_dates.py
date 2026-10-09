# -*- coding: utf-8 -*-
from datetime import date

import pytest

from yangdo import dates


def test_full_years_anniversary_counts():
    assert dates.full_years("2024-03-01", "2026-03-01") == 2


def test_full_years_one_day_short():
    assert dates.full_years("2024-03-01", "2026-02-28") == 1


def test_full_years_leap_day():
    assert dates.full_years("2024-02-29", "2026-02-28") == 2


def test_full_years_rejects_reverse():
    with pytest.raises(ValueError):
        dates.full_years("2026-01-02", "2026-01-01")


def test_within_years_last_day_included():
    assert dates.within_years("2023-06-01", "2026-06-01", 3) is True
    assert dates.within_years("2023-06-01", "2026-06-02", 3) is False


def test_add_years_leap():
    assert dates.add_years("2024-02-29", 1) == date(2025, 2, 28)


def test_residence_single_period_clipped():
    assert dates.residence_years([["2010-01-01", "2030-01-01"]], "2014-11-01", "2026-11-15") == (12, False)


def test_residence_multiple_periods_approximate():
    y, approx = dates.residence_years([["2015-01-01", "2016-01-01"], ["2018-01-01", "2019-06-01"]],
                                      "2014-01-01", "2026-11-01")
    assert approx is True and y == (365 + 516) // 365


def test_residence_none():
    assert dates.residence_years([], "2014-01-01", "2026-11-01") == (0, False)


def test_transfer_date_balance():
    assert dates.transfer_date({"잔금일": "2026-11-15", "등기접수일": "2026-11-20"})[0] == date(2026, 11, 15)


def test_transfer_date_registration_before_balance():
    d, why = dates.transfer_date({"잔금일": "2026-11-15", "등기접수일": "2026-11-10"})
    assert d == date(2026, 11, 10) and "등기접수일" in why


def test_transfer_date_only_registration():
    assert dates.transfer_date({"잔금일": None, "등기접수일": "2026-11-10"})[0] == date(2026, 11, 10)


def test_transfer_date_none():
    assert dates.transfer_date({})[0] is None


def test_acquisition_new_build():
    d, why = dates.acquisition_date({"원인": "신축", "사용승인일": "2020-05-01", "사실상사용일": "2020-04-20"})
    assert d == date(2020, 4, 20) and "162" in why


def test_acquisition_presale_completion():
    d, _ = dates.acquisition_date({"원인": "분양", "잔금일": "2020-01-10", "사용승인일": "2020-03-01"})
    assert d == date(2020, 3, 1)


def test_acquisition_auction_uses_full_payment():
    assert dates.acquisition_date({"원인": "경매", "대금완납일": "2019-07-01"})[0] == date(2019, 7, 1)


def test_acquisition_plain_purchase():
    assert dates.acquisition_date({"원인": "매매", "잔금일": "2014-11-01"})[0] == date(2014, 11, 1)
