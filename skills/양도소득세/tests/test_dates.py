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


# ---- 양도소득세 신고기한(소득세법 제105조①, 제110조①, 국세기본법 제5조①). 규칙 값은 규칙세트에서 읽는다 ----

@pytest.fixture(scope="module")
def rs():
    from yangdo import ruleset
    return ruleset.load()


@pytest.mark.parametrize("종류,양도,명목,보정", [
    ("예정", "2026-01-15", "2026-03-31", "2026-03-31"),      # 화요일 말일
    ("예정", "2026-08-20", "2026-10-31", "2026-11-02"),      # 토요일 말일은 월요일로
    ("예정", "2026-11-20", "2027-01-31", "2027-02-01"),      # 일요일 말일은 월요일로
    ("예정", "2026-12-10", "2027-02-28", "2027-03-02"),      # 12월 양도는 2월 말일(일요일), 월요일이 3·1절이라 화요일로
    ("예정", "2027-12-10", "2028-02-29", "2028-02-29"),      # 윤년 2월 말일(화요일)
    ("예정", "2026-12-31", "2027-02-28", "2027-03-02"),      # 양도일이 말일이어도 같은 달 말일 기준
    ("확정", "2026-03-10", "2027-05-31", "2027-05-31"),      # 월요일
    ("확정", "2025-11-10", "2026-05-31", "2026-06-01"),      # 5월 31일이 일요일인 해
    ("확정", "2030-11-10", "2031-05-31", "2031-06-02"),      # 5월 31일이 토요일인 해
])
def test_filing_deadline(rs, 종류, 양도, 명목, 보정):
    assert dates.filing_deadline(종류, 양도, rs) == (date.fromisoformat(명목), date.fromisoformat(보정))


def test_filing_deadline_reads_ruleset_values(rs):
    class Fake:
        def value(self, key, on):
            return {"신고기한.예정.개월": 3, "신고기한.확정.월": 6, "신고기한.확정.일": 30}[key]
    assert dates.filing_deadline("예정", "2026-01-15", Fake())[0] == date(2026, 4, 30)
    assert dates.filing_deadline("확정", "2026-01-15", Fake())[0] == date(2027, 6, 30)


def test_filing_deadline_rejects_unknown_kind(rs):
    with pytest.raises(ValueError):
        dates.filing_deadline("수정", "2026-01-15", rs)


# ---- 공휴일(국세기본법 제5조①). 날짜가 고정된 공휴일과 노동절은 월·일로, 나머지는 rules/공휴일.json 의 연도별 날짜로 본다 ----

def _d(text):
    return date.fromisoformat(text)


def test_deadline_still_unpacks_into_two_dates(rs):
    # 기존 호출부는 둘로 풀어 쓰거나 튜플을 이어 붙인다. 그 모양은 그대로다
    got = dates.filing_deadline("예정", "2026-01-15", rs)
    nominal, adjusted = got
    assert (nominal, adjusted) == (_d("2026-03-31"), _d("2026-03-31")) and len(got) == 2
    assert got + ("A",) == (_d("2026-03-31"), _d("2026-03-31"), "A")
    assert got.공휴일표 is True and got.옮긴이유 == ()


def test_deadline_moves_past_fixed_holiday_after_weekend(rs):
    # 2026-12 양도: 말일 2027-02-28(일) 다음 날이 3·1절(월)이라 2027-03-02(화)까지다
    got = dates.filing_deadline("예정", "2026-12-10", rs)
    assert got == (_d("2027-02-28"), _d("2027-03-02")) and got.공휴일표 is True
    assert got.옮긴이유 == ((_d("2027-02-28"), "일요일"), (_d("2027-03-01"), "3·1절"))


def test_deadline_moves_past_substitute_holiday_in_table(rs):
    # 2025-12 양도: 말일 2026-02-28(토), 3·1절(일), 대체공휴일 2026-03-02(월, 표에 날짜로 있다) 다음인 2026-03-03(화)
    got = dates.filing_deadline("예정", "2025-12-10", rs)
    assert got == (_d("2026-02-28"), _d("2026-03-03")) and got.공휴일표 is True
    assert [why for _, why in got.옮긴이유] == ["토요일", "일요일", "대체공휴일(3·1절)"]


def test_deadline_moves_past_labor_day(rs):
    # 2028-02 양도: 말일 2028-04-30(일) 다음 날이 노동절(월)이라 2028-05-02(화)까지다. 노동절은 표가 없는 해에도 월·일로 안다
    got = dates.filing_deadline("예정", "2028-02-10", rs)
    assert got == (_d("2028-04-30"), _d("2028-05-02"))
    assert got.옮긴이유 == ((_d("2028-04-30"), "일요일"), (_d("2028-05-01"), "노동절"))
    assert got.공휴일표 is rs.공휴일.covers(2028)


class _FakeRules:
    """신고기한 값만 주는 규칙세트 대역. 공휴일 표를 시험용으로 바꿔 끼운다."""

    def __init__(self, table=None):
        if table is not None:
            self.공휴일 = dates.Holidays(table)

    def value(self, key, on):
        return {"신고기한.예정.개월": 2, "신고기한.확정.월": 5, "신고기한.확정.일": 31}[key]


SYNTHETIC = {  # 시험용 표다. 1월 말일이 설 연휴 첫날인 해의 모양만 흉내 낸다
    "고정": [{"월": 1, "일": 1, "이름": "1월 1일", "시작": None, "끝": None},
             {"월": 5, "일": 1, "이름": "노동절", "시작": None, "끝": None}],
    "연도": {"2033": {"확인일": "2026-10-11", "출처": [{"이름": "시험용", "URL": "https://example.invalid/"}],
                      "날짜": [{"날짜": "2033-01-31", "이름": "설날(연휴)"}, {"날짜": "2033-02-01", "이름": "설날(연휴)"},
                               {"날짜": "2033-02-02", "이름": "설날(연휴)"}]}}}


def test_january_end_deadline_inside_lunar_new_year_holidays():
    # 11월 양도의 기한 말일 1월 31일(월)이 설 연휴 첫날이면 연휴가 끝난 다음 날까지다
    got = dates.filing_deadline("예정", "2032-11-10", _FakeRules(SYNTHETIC))
    assert got == (_d("2033-01-31"), _d("2033-02-03")) and got.공휴일표 is True
    assert [why for _, why in got.옮긴이유] == ["설날(연휴)"] * 3


def test_year_without_table_moves_weekend_and_fixed_holidays_only():
    # 표에 2034년이 없다. 토·일과 고정 공휴일만 옮기고 표가 덮지 않는다고 표시한다
    got = dates.filing_deadline("예정", "2033-11-10", _FakeRules(SYNTHETIC))     # 2034-01-31 은 화요일
    assert got == (_d("2034-01-31"), _d("2034-01-31")) and got.공휴일표 is False
    got = dates.filing_deadline("예정", "2034-02-10", _FakeRules(SYNTHETIC))     # 2034-04-30(일), 05-01(월) 노동절
    assert got == (_d("2034-04-30"), _d("2034-05-02")) and got.공휴일표 is False


def test_deadline_crossing_into_uncovered_year_is_not_covered():
    # 10월 양도: 2033-12-31(토), 2034-01-01(일), 2034-01-02(월). 넘어간 해(2034)가 표에 없으면 덮지 않는다고 본다
    got = dates.filing_deadline("예정", "2033-10-10", _FakeRules(SYNTHETIC))
    assert got == (_d("2033-12-31"), _d("2034-01-02")) and got.공휴일표 is False


def test_rules_without_holiday_table_keep_weekend_only_behaviour():
    # 공휴일 표가 없는 규칙세트(rules 폴더만 따로 쓰는 경우)는 예전처럼 토·일만 옮긴다
    got = dates.filing_deadline("예정", "2026-12-10", _FakeRules())
    assert got == (_d("2027-02-28"), _d("2027-03-01")) and got.공휴일표 is False
    assert got.옮긴이유 == ((_d("2027-02-28"), "일요일"),)


def test_real_table_far_future_year_is_not_covered(rs):
    got = dates.filing_deadline("확정", "2030-11-10", rs)      # 2031-05-31(토)
    assert got == (_d("2031-05-31"), _d("2031-06-02")) and got.공휴일표 is False


def test_fixed_holidays_follow_their_start_dates(rs):
    h = rs.공휴일
    assert h.name(_d("2025-07-17")) is None            # 제헌절은 2026-05-11 부터 공휴일이다
    assert h.name(_d("2026-07-17")) == "제헌절"
    assert h.name(_d("2025-05-01")) == "노동절" and h.name(_d("2031-05-01")) == "노동절"
    assert h.name(_d("2031-03-01")) == "3·1절" and h.name(_d("2031-03-03")) is None
    assert h.name(_d("2027-05-13")) == "부처님 오신 날" and h.name(_d("2027-05-14")) is None


def test_holiday_table_file_has_source_and_check_date_for_every_year(rs):
    import json
    import os
    from yangdo import RULES_DIR
    with open(os.path.join(RULES_DIR, "공휴일.json"), encoding="utf-8") as f:
        data = json.load(f)
    assert data["연도"], "연도 표가 비었다"
    for year, y in data["연도"].items():
        assert dates.ISO_DATE.fullmatch(y["확인일"]), year
        assert y["출처"] and all(s["이름"] and s["URL"].startswith("https://") for s in y["출처"]), year
        days = [x["날짜"] for x in y["날짜"]]
        assert days == sorted(set(days)) and all(d.startswith(year + "-") and x["이름"] for d, x in zip(days, y["날짜"])), year
        assert rs.공휴일.covers(int(year))
    for f in data["고정"]:
        assert date(2028, f["월"], f["일"]) and f["이름"] and "근거" in f      # 2028 은 윤년이라 어느 월·일이든 만들어진다


def test_holiday_table_rejects_date_in_wrong_year():
    src = [{"이름": "시험용", "URL": "https://example.invalid/"}]
    bad = {"고정": [], "연도": {"2033": {"확인일": "2026-10-11", "출처": src, "날짜": [{"날짜": "2034-01-01", "이름": "x"}]}}}
    with pytest.raises(ValueError, match="2033년에 다른 해"):
        dates.Holidays(bad)
    twice = {"고정": [], "연도": {"2033": {"확인일": "2026-10-11", "출처": src,
                                         "날짜": [{"날짜": "2033-01-31", "이름": "x"}, {"날짜": "2033-01-31", "이름": "y"}]}}}
    with pytest.raises(ValueError, match="두 번"):
        dates.Holidays(twice)


@pytest.mark.parametrize("year,lacking", [
    ({}, "확인일·출처·날짜"),                                                              # 빈 해를 덮는 해로 세지 않는다
    ({"확인일": "2026-10-11", "출처": [{"이름": "시험용", "URL": "https://example.invalid/"}], "날짜": []}, "날짜"),
    ({"확인일": "2026-10-11", "날짜": [{"날짜": "2030-02-04", "이름": "x"}]}, "출처"),
    ({"출처": [{"이름": "시험용", "URL": "https://example.invalid/"}], "날짜": [{"날짜": "2030-02-04", "이름": "x"}]}, "확인일"),
])
def test_holiday_table_rejects_year_without_dates_source_or_check_date(year, lacking):
    with pytest.raises(ValueError, match="2030년에 %s 이 없다" % lacking):
        dates.Holidays({"고정": [], "연도": {"2030": year}})


def test_deadline_survives_copy_and_pickle(rs):
    import copy
    import pickle
    got = dates.filing_deadline("예정", "2026-12-10", rs)
    for clone in (copy.copy(got), copy.deepcopy(got), pickle.loads(pickle.dumps(got)), copy.deepcopy({"기한": got})["기한"]):
        assert type(clone) is dates.Deadline and clone == got
        assert clone.공휴일표 is True and clone.옮긴이유 == got.옮긴이유


def _real_table():
    import json
    import os
    from yangdo import RULES_DIR
    with open(os.path.join(RULES_DIR, "공휴일.json"), encoding="utf-8") as f:
        return json.load(f)


def test_real_table_substitute_holidays_are_weekdays():
    # 대체공휴일은 공휴일 다음의 첫 번째 비공휴일이라 토요일·일요일일 수 없다. 고정 공휴일과 겹쳐도 안 된다
    h = dates.Holidays(_real_table())
    found = 0
    for year, y in _real_table()["연도"].items():
        for x in y["날짜"]:
            if x["이름"].startswith("대체공휴일"):
                d = _d(x["날짜"])
                found += 1
                assert d.weekday() < 5, x
                assert not any((d.month, d.day) == (m, dd) for m, dd, *_ in h.fixed), x
    assert found >= 10


def test_real_table_lunar_holidays_are_three_consecutive_days():
    from datetime import timedelta
    for year, y in _real_table()["연도"].items():
        for name in ("설날(연휴)", "추석(연휴)"):
            days = [_d(x["날짜"]) for x in y["날짜"] if x["이름"] == name]
            assert len(days) == 3 and days[1] - days[0] == days[2] - days[1] == timedelta(days=1), (year, name, days)


def test_real_table_has_no_duplicate_dates_and_one_spelling_per_holiday():
    data = _real_table()
    days = [x["날짜"] for y in data["연도"].values() for x in y["날짜"]]
    assert len(days) == len(set(days))
    names = {x["이름"] for y in data["연도"].values() for x in y["날짜"]} | {f["이름"] for f in data["고정"]}
    assert len({n.replace(" ", "") for n in names}) == len(names), sorted(names)      # 띄어쓰기만 다른 이름이 없다
    for year, y in data["연도"].items():
        assert sum(1 for x in y["날짜"] if x["이름"] == "부처님 오신 날") == 1, year


def test_holiday_table_is_part_of_the_edition(rs, tmp_path):
    import os
    import shutil
    from yangdo import RULES_DIR, ruleset
    assert "공휴일.json" in rs.edition["파일"]
    # 표를 고치면 판이 달라졌다고 알린다
    d = str(tmp_path / "rules")
    shutil.copytree(RULES_DIR, d)
    p = tmp_path / "rules" / "공휴일.json"
    p.write_text(p.read_text(encoding="utf-8").replace("2027-05-13", "2027-05-14"), encoding="utf-8")
    with pytest.raises(ruleset.RuleError, match="공휴일.json"):
        ruleset.load(d)
    # 표 파일이 없는 rules 폴더는 읽히고, 공휴일을 모르는 규칙세트가 된다
    p.unlink()
    assert ruleset.load(d).공휴일 is None
    # 표가 생기기 전에 만든 판(파일 목록에 표가 없다)에 표 파일만 놓으면 대조하지 않은 표라 읽지 않는다
    ruleset.write_edition(d, rs.확인일)
    shutil.copy(os.path.join(RULES_DIR, "공휴일.json"), str(p))
    with pytest.raises(ruleset.RuleError, match="공휴일.json"):
        ruleset.load(d)
    ruleset.write_edition(d, rs.확인일)
    assert ruleset.load(d).공휴일.covers(2027)


# ---- 분납 기한(소득세법 제112조 「납부기한이 지난 후 2개월 이내」). 날짜 계산은 이 스킬의 가정이다 ----

@pytest.mark.parametrize("종류,양도,신고기한,분납기한,요일", [
    ("확정", "2026-11-20", "2027-05-31", "2027-08-02", 0),     # 2027-07-31 토요일, 08-01 일요일을 건너뛴다
    ("예정", "2026-10-20", "2026-12-31", "2027-03-02", 1),     # 2027-02-28 일요일, 03-01 삼일절을 건너뛴다
    ("예정", "2026-06-10", "2026-08-31", "2026-11-02", 0),     # 2026-10-31 토요일, 11-01 일요일
    ("예정", "2026-01-15", "2026-03-31", "2026-06-01", 0),     # 말일 3월 31일의 2개월 뒤는 5월 31일(일요일)이라 월요일로
])
def test_installment_deadline_adds_two_months_to_the_adjusted_deadline(rs, 종류, 양도, 신고기한, 분납기한, 요일):
    filing = dates.filing_deadline(종류, 양도, rs)
    assert filing[1] == date.fromisoformat(신고기한)
    due = dates.installment_deadline(filing, rs)
    assert due[1] == date.fromisoformat(분납기한) and due[1].weekday() == 요일 and due[1].weekday() < 5
    assert due.공휴일표 is True


def test_installment_deadline_starts_from_the_moved_deadline_and_tells_what_it_skipped(rs):
    filing = dates.filing_deadline("예정", "2026-12-10", rs)           # 말일 2027-02-28(일) 이 3·1절 다음 화요일 03-02 로 옮겨진 기한
    assert filing[0] == date(2027, 2, 28) and filing[1] == date(2027, 3, 2)
    due = dates.installment_deadline(filing, rs)
    assert due[0] == date(2027, 5, 2) and due[1] == date(2027, 5, 4)   # 05-02 일요일, 05-03 노동절 대체휴일
    assert dates.skipped_text(due).startswith("2027-05-02(일요일), 2027-05-03(")


def test_installment_deadline_marks_a_year_missing_from_the_holiday_table(rs):
    filing = dates.filing_deadline("확정", "2038-11-20", rs)
    assert dates.installment_deadline(filing, rs).공휴일표 is False
