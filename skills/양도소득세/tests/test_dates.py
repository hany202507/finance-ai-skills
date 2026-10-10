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


def test_transfer_auction_uses_full_payment_day():
    t = {"원인": "경매", "대금완납일": "2026-11-15", "잔금일": "2026-12-20"}
    assert dates.transfer_date(t)[0] == date(2026, 11, 15)
    assert dates.transfer_date({"원인": "경매", "잔금일": "2026-12-20"})[0] == date(2026, 12, 20)


def test_transfer_auction_registration_before_payment_is_registration_day():
    t = {"원인": "경매", "대금완납일": "2026-11-15", "등기접수일": "2026-11-10"}
    assert dates.transfer_date(t)[0] == date(2026, 11, 10)


def test_transfer_sale_ignores_full_payment_day():
    assert dates.transfer_date({"원인": "매매", "대금완납일": "2026-11-15"})[0] is None
    assert dates.transfer_date({"원인": "매매", "대금완납일": "2026-11-15", "잔금일": "2026-12-20"})[0] == date(2026, 12, 20)


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


def test_acquisition_presale_actual_use_earlier():
    d, why = dates.acquisition_date({"원인": "분양", "잔금일": "2020-01-10", "사용승인일": "2020-03-01", "사실상사용일": "2020-02-15"})
    assert d == date(2020, 2, 15) and "8호" in why


def test_acquisition_new_build_without_dates_is_unknown():
    assert dates.acquisition_date({"원인": "신축", "잔금일": "2020-01-10"}) == (None, "")


def test_acquisition_auction_prefers_full_payment():
    assert dates.acquisition_date({"원인": "경매", "잔금일": "2019-08-01", "대금완납일": "2019-07-01"})[0] == date(2019, 7, 1)


def test_to_date_normalizes_datetime():
    from datetime import datetime
    assert dates.to_date(datetime(2026, 1, 2, 13, 0)) == date(2026, 1, 2)


# ---- 최종 검토 반영 ---------------------------------------------------------------------------
@pytest.mark.parametrize("bad", ["20261115", "2026-W46-7", "2026-11-15T00:00:00", "2026/11/15", " 2026-11-15",
                                 "2026-1-5", "2026-11-15 ", 20261115, "２０２６-11-15"])
def test_to_date_accepts_only_iso_strings(bad):
    """파이썬 3.10 과 3.11 이상이 같은 입력에 같은 결과를 내도록 YYYY-MM-DD 글자만 받는다."""
    with pytest.raises(ValueError):
        dates.to_date(bad)


def test_to_date_iso_string_and_empty():
    assert dates.to_date("2026-11-15") == date(2026, 11, 15)
    assert dates.to_date("") is None and dates.to_date(None) is None
    assert dates.to_date(date(2026, 11, 15)) == date(2026, 11, 15)


def test_transfer_date_rejects_compact_date():
    with pytest.raises(ValueError):
        dates.transfer_date({"잔금일": "20261115"})
    with pytest.raises(ValueError):
        dates.acquisition_date({"원인": "매매", "잔금일": "20141101"})


def test_auction_basis_names_full_payment_of_sale_price():
    """경매의 대금 청산일은 잔금일이 아니라 매각대금 완납일이다(민사집행법 제135조)."""
    for t in ({"원인": "경매", "대금완납일": "2026-11-15"}, {"원인": "경매", "잔금일": "2026-11-15"}):
        d, why = dates.transfer_date(t)
        assert d == date(2026, 11, 15) and "매각대금 완납일" in why and "민사집행법 제135조" in why and "잔금일" not in why
    d, why = dates.acquisition_date({"원인": "경매", "대금완납일": "2019-07-01"})
    assert "매각대금 완납일" in why and "민사집행법 제135조" in why and "잔금일" not in why
    d, why = dates.transfer_date({"원인": "경매", "대금완납일": "2026-11-15", "등기접수일": "2026-11-10"})
    assert d == date(2026, 11, 10) and "등기접수일" in why
    # 매매는 그대로 잔금일
    assert "잔금일" in dates.transfer_date({"원인": "매매", "잔금일": "2026-11-15"})[1]
    assert "잔금일" in dates.acquisition_date({"원인": "매매", "잔금일": "2014-11-01"})[1]


def test_residence_duplicate_period_counts_once():
    p = ["2014-11-01", "2015-11-01"]
    once = dates.residence_years([p], "2014-11-01", "2026-11-15")
    assert dates.residence_years([p, list(p)], "2014-11-01", "2026-11-15") == once == (1, False)


def test_residence_overlapping_periods_use_union():
    """겹친 두 구간(2014-11-01~2016-11-01, 2015-11-01~2017-11-01)의 합집합은 3년이다."""
    got = dates.residence_years([["2014-11-01", "2016-11-01"], ["2015-11-01", "2017-11-01"]], "2014-11-01", "2026-11-15")
    assert got == (3, False)
    # 순서가 뒤바뀌어도 같고, 한 구간이 다른 구간 안에 들어가도 합집합이다
    rev = dates.residence_years([["2015-11-01", "2017-11-01"], ["2014-11-01", "2016-11-01"]], "2014-11-01", "2026-11-15")
    assert rev == got
    inner = dates.residence_years([["2014-11-01", "2020-11-01"], ["2016-01-01", "2017-01-01"]], "2014-11-01", "2026-11-15")
    assert inner == (6, False)


def test_residence_never_exceeds_union_or_holding_period():
    # 겹침 때문에 거주 16년이 보유 12년보다 커지던 입력
    periods = [["2014-11-01", "2026-11-15"]] * 2 + [["2014-11-01", "2018-11-01"], ["2016-01-01", "2026-11-15"]]
    y, approx = dates.residence_years(periods, "2014-11-01", "2026-11-15")
    assert (y, approx) == (12, False)
    # 겹침이 있는 목록과 떨어진 구간이 섞이면 합집합 일수로 근사한다
    y, approx = dates.residence_years([["2015-01-01", "2016-01-01"], ["2015-06-01", "2016-06-01"], ["2020-01-01", "2021-01-01"]],
                                      "2014-01-01", "2026-11-01")
    assert approx is True and y == ((date(2016, 6, 1) - date(2015, 1, 1)).days + (date(2021, 1, 1) - date(2020, 1, 1)).days) // 365


def test_residence_touching_periods_join():
    y, approx = dates.residence_years([["2014-11-01", "2020-01-01"], ["2020-01-01", "2026-11-15"]], "2014-11-01", "2026-11-15")
    assert (y, approx) == (12, False)
