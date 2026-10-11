# -*- coding: utf-8 -*-
import json
import os

import pytest

from yangdo import RULES_DIR
from yangdo import regions as RG
from yangdo.regions import NeedAnswer

REG = RG.load()
C = "조정대상지역"


def a(시도, 시군구, 읍면동=""):
    return {"시도": 시도, "시군구": 시군구, "읍면동": 읍면동}


def now_list(kind):
    with open(os.path.join(RULES_DIR, "고시", "현황_2026-10-09.json"), encoding="utf-8") as f:
        return sorted(json.load(f)[kind]["지역"])


@pytest.mark.parametrize("bad", ["20261115", "2026-W46-7", "2026/11/15", "2026-11-15T00:00:00", "", None, 20261115])
def test_dates_other_than_iso_text_are_rejected(bad):
    """파이썬 3.11 이상의 date.fromisoformat 은 20261115 도 받는다. 기준일은 YYYY-MM-DD 글자만 받는다."""
    place = a("서울특별시", "마포구", "공덕동")
    with pytest.raises(ValueError):
        REG.status(C, place, bad)
    with pytest.raises(ValueError):
        REG.designated_list(C, bad)
    with pytest.raises(ValueError):
        RG._d(bad)
    if bad is not None:   # metro 의 기준일은 생략할 수 있다(None)
        with pytest.raises(ValueError):
            REG.metro(place, bad)


def test_date_objects_and_iso_text_are_accepted():
    import datetime
    place = a("서울특별시", "마포구", "공덕동")
    want = REG.status(C, place, "2026-10-09")
    assert REG.status(C, place, datetime.date(2026, 10, 9)) == want
    assert REG.status(C, place, datetime.datetime(2026, 10, 9, 12, 0)) == want


def test_replay_matches_2026_status_table():
    assert REG.designated_list(C, "2026-10-09") == now_list(C)
    assert len(now_list(C)) == 40


def test_replay_overheated_matches_status_table():
    assert REG.designated_list("투기과열지구", "2026-10-09") == now_list("투기과열지구")


def test_replay_after_2023_01_05():
    assert REG.designated_list(C, "2023-01-05") == [
        "서울특별시 강남구", "서울특별시 서초구", "서울특별시 송파구", "서울특별시 용산구"]


def test_mapo_history():
    s = REG.status(C, a("서울특별시", "마포구", "공덕동"), "2017-10-15")
    assert s["지정"] and s["효력발생일"] == "2017-08-03" and s["공고일"] == "2017-08-02"
    assert REG.status(C, a("서울", "마포구", "공덕동"), "2019-03-01")["효력발생일"] == "2017-11-10"
    assert REG.status(C, a("서울특별시", "마포구", "공덕동"), "2024-05-01")["지정"] is False
    s = REG.status(C, a("서울특별시", "마포구", "공덕동"), "2026-03-15")
    assert s["지정"] and s["효력발생일"] == "2025-10-16"


def test_other_places():
    assert REG.status(C, a("부산광역시", "해운대구", "우동"), "2026-11-20")["지정"] is False
    assert REG.status(C, a("서울특별시", "송파구", "잠실동"), "2026-07-01")["지정"] is True
    assert REG.status(C, a("강원도", "춘천시", "석사동"), "2026-07-01")["지정"] is False


def test_district_needs_answer_then_resolves():
    addr = a("경기도", "화성시", "반송동")
    with pytest.raises(NeedAnswer) as e:
        REG.status(C, addr, "2018-01-01")
    assert e.value.문항 == "A02" and "동탄2택지개발지구" in e.value.후보
    assert REG.status(C, addr, "2018-01-01", "예")["지정"] is True
    assert REG.status(C, addr, "2018-01-01", "아니오")["지정"] is False
    assert REG.status(C, addr, "2020-07-01")["지정"] is True  # 2020-06-19 화성시 전역 지정이 덮는다


def test_hwaseong_split():
    with pytest.raises(NeedAnswer) as e:
        REG.status(C, a("경기도", "화성시", "반송동"), "2026-08-01")
    assert e.value.문항 == "A01"
    assert REG.status(C, a("경기도", "화성시 동탄구", "반송동"), "2026-08-01")["지정"] is True


def test_partial_release_and_exclusions():
    assert REG.status(C, a("경기도", "남양주시", "다산동"), "2020-01-01")["지정"] is True
    assert REG.status(C, a("경기도", "남양주시", "화도읍"), "2020-01-01")["지정"] is False
    with pytest.raises(NeedAnswer) as e:
        REG.status(C, a("경기도", "안성시", "죽산면"), "2020-07-01")
    assert e.value.문항 == "A01"
    assert REG.status(C, a("경기도", "안성시", "죽산면 죽산리"), "2020-07-01")["지정"] is False
    assert REG.status(C, a("경기도", "안성시", "죽산면 칠장리"), "2020-07-01")["지정"] is True


def test_incheon_reorganization():
    with pytest.raises(NeedAnswer) as e:
        REG.status(C, a("인천광역시", "검단구", "불로동"), "2020-01-01")
    assert e.value.문항 == "A03"
    with pytest.raises(NeedAnswer) as e:
        REG.status(C, a("인천광역시", "중구", "운서동"), "2026-08-01")
    assert e.value.문항 == "A01"


def test_speculation_zone():
    assert REG.status("투기지역", a("서울특별시", "강남구", "대치동"), "2026-10-09")["지정"] is True
    assert REG.status("투기지역", a("서울특별시", "마포구", "공덕동"), "2026-10-09")["지정"] is False


def test_metro():
    assert REG.metro(a("부산광역시", "기장군", "기장읍"), "2026-10-09") is False
    assert REG.metro(a("대구광역시", "수성구", "범어동"), "2026-10-09") is True
    assert REG.metro(a("세종특별자치시", "", "조치원읍"), "2026-10-09") is False
    assert REG.metro(a("세종특별자치시", "", "보람동"), "2026-10-09") is True
    assert REG.metro(a("인천광역시", "강화군", "강화읍"), "2026-10-09") is True
    assert REG.metro(a("경기도", "평택시", "고덕동"), "2026-10-09") is True
    assert REG.metro(a("강원특별자치도", "춘천시", "석사동"), "2026-10-09") is False
    assert REG.metro(a("광주광역시", "서구", "치평동"), "2026-10-09") is True
    assert REG.capital(a("경기", "평택시")) is True and REG.capital(a("부산", "해운대구")) is False


def test_renamed_with_low_grade_is_noted():
    """등급이 ★★★ 이 아닌 이름변경으로 바꿔 판정하면 주석을 단다. 지금 표의 이름변경은 모두 ★★★ 이라 등급만 낮춘 표로 본다."""
    with open(os.path.join(RULES_DIR, "행정구역_대응.json"), encoding="utf-8") as f:
        admin = json.load(f)
    assert {r["등급"] for r in admin["이름변경"]} == {"★★★"}
    place = a("강원도", "춘천시", "석사동")
    assert REG.status(C, place, "2026-07-01")["주석"] == []
    for r in admin["이름변경"]:
        if r["옛"] == "강원도":
            r["등급"] = "★★☆"
    low = RG.Regions({name: {"이벤트": []} for name in RG.REGIMES}, admin)
    notes = low.status(C, place, "2026-07-01")["주석"]
    assert len(notes) == 1 and "강원특별자치도" in notes[0] and "★★☆" in notes[0]


def test_city_without_district_must_name_district():
    with pytest.raises(NeedAnswer) as e:
        REG.status(C, a("경기도", "성남시", "정자동"), "2024-01-01")
    assert e.value.문항 == "A01"
    assert REG.status(C, a("경기도", "성남시 분당구", "정자동"), "2024-01-01")["지정"] is False


# --- 전남광주통합특별시(2026-07-01 광주광역시와 전라남도를 폐지하고 설치) ---

통합 = "전남광주통합특별시"
자치구 = ("동구", "서구", "남구", "북구", "광산구")                      # 통합 전 광주광역시의 자치구
시군 = ("목포시", "여수시", "순천시", "나주시", "광양시", "담양군", "곡성군", "구례군", "고흥군", "보성군", "화순군",
      "장흥군", "강진군", "해남군", "영암군", "무안군", "함평군", "영광군", "장성군", "완도군", "진도군", "신안군")   # 통합 전 전라남도의 시·군
통합_전후 = ("2021-06-01", "2026-06-30", "2026-07-01", "2026-10-09")


@pytest.mark.parametrize("on", 통합_전후)
def test_merged_city_districts_follow_metropolitan_rule(on):
    """통합특별시의 자치구 관할구역에는 광역시 규정을 적용한다. 주소를 옛 이름으로 적든 새 이름으로 적든, 통합 전이든 뒤든 같다."""
    for gu in 자치구:
        assert REG.metro(a(통합, gu, ""), on) is True, gu
        assert REG.metro(a("광주광역시", gu, ""), on) is True, gu
    assert REG.metro(a("광주", "서구", "치평동"), on) is True
    assert REG.metro(a("광주특별시", "광산구", "수완동"), on) is True       # 법률이 정한 약칭


@pytest.mark.parametrize("on", 통합_전후)
def test_merged_city_cities_and_counties_follow_province_rule(on):
    """통합특별시의 시·군 관할구역에는 도 규정을 적용한다(지방 저가주택 판정에서 광역시가 아닌 지역)."""
    for name in 시군:
        assert REG.metro(a(통합, name, ""), on) is False, name
        assert REG.metro(a("전라남도", name, ""), on) is False, name
    assert REG.metro(a("전남", "순천시", "조례동"), on) is False
    assert REG.metro(a(통합, "강진군", "강진읍"), on) is False


def test_merged_city_unknown_or_mismatched_district_is_none():
    """시군구를 모르면 자치구인지 시·군인지 정하지 못한다. 옛 시도 이름과 시군구가 맞지 않아도 정하지 않는다."""
    on = "2026-10-09"
    assert REG.metro(a(통합, "", "치평동"), on) is None
    assert REG.metro(a(통합, "중구", ""), on) is None
    assert REG.metro(a("전라남도", "서구", "치평동"), on) is None
    assert REG.metro(a("광주광역시", "순천시", "조례동"), on) is None
    assert REG.capital(a(통합, "서구")) is False and REG.capital(a("전라남도", "순천시")) is False


def test_old_sido_name_without_district_keeps_its_rule_across_the_merger():
    """옛 시도 이름만 적고 시군구를 비운 주소는 그 시도의 적용(광역시, 도)을 통합 뒤에도 그대로 쓴다."""
    for on in 통합_전후:
        assert REG.metro(a("광주광역시", "", ""), on) is True, on
        assert REG.metro(a("광주", "", "치평동"), on) is True, on
        assert REG.metro(a("전라남도", "", ""), on) is False, on
        assert REG.metro(a("전남", "", "조례동"), on) is False, on


def test_old_sido_name_with_foreign_district_before_the_merger_is_unchanged():
    """옛 시도 이름과 시군구가 맞지 않는 주소는 통합 뒤 기준일에는 정하지 않는다. 통합 전 기준일에는 시군구 이름을
    대조하지 않던 종전 동작(시도 이름만으로 판정) 그대로다. 종전 결과를 바꾸지 않으려고 그대로 두었다."""
    for on in ("2021-06-01", "2026-06-30"):
        assert REG.metro(a("광주광역시", "순천시", "조례동"), on) is True, on
        assert REG.metro(a("전라남도", "서구", "치평동"), on) is False, on
        assert REG.metro(a("광주광역시", "중구", ""), on) is True, on
    for on in ("2026-07-01", "2026-10-09"):
        assert REG.metro(a("광주광역시", "순천시", "조례동"), on) is None, on
        assert REG.metro(a("전라남도", "서구", "치평동"), on) is None, on
        assert REG.metro(a("광주광역시", "중구", ""), on) is None, on


통합시 = ("목포시", "여수시", "순천시", "나주시", "광양시")


@pytest.mark.parametrize("on", ["2026-07-01", "2026-10-09"])
def test_metro_caveat_marks_merged_city_urban_areas_after_the_merger(on):
    """통합 뒤 기준일에 시의 동 지역을 광역시가 아닌 지역으로 보는 것은 시·군 관할구역 특례를 적용한 결과다.
    그 주소를 알려 주어 판정이 확인사항을 달게 한다."""
    for name in 통합시:
        for sido in (통합, "전라남도", "전남"):
            assert REG.metro(a(sido, name, "중앙동"), on) is False
            assert REG.metro_caveat(a(sido, name, "중앙동"), on) == 통합, (sido, name)
        assert REG.metro_caveat(a(통합, name, ""), on) == 통합, name
    assert REG.metro_caveat(a("전라남도", "", "조례동"), on) == 통합       # 시군구를 몰라 시의 동 지역일 수 있다


def test_metro_caveat_is_none_where_readings_agree():
    for name in 통합시:                                                     # 통합 전 기준일
        for on in ("2021-06-01", "2026-06-30"):
            assert REG.metro_caveat(a(통합, name, "중앙동"), on) is None
            assert REG.metro_caveat(a("전라남도", name, "중앙동"), on) is None
    for on in ("2026-07-01", "2026-10-09"):
        for gu in 자치구:                                                   # 자치구는 광역시로 본다
            assert REG.metro_caveat(a(통합, gu, ""), on) is None
            assert REG.metro_caveat(a("광주광역시", gu, ""), on) is None
        for name in 시군:
            if name.endswith("군"):                                         # 군은 광역시에 소속된 군으로 읽어도 같다
                assert REG.metro_caveat(a(통합, name, ""), on) is None
                assert REG.metro_caveat(a("전라남도", name, ""), on) is None
        assert REG.metro_caveat(a(통합, "순천시", "승주읍"), on) is None        # 시의 읍·면도 같다
        assert REG.metro_caveat(a(통합, "나주시", "남평읍 남평리"), on) is None
        assert REG.metro_caveat(a(통합, "순천시", "황전면"), on) is None
        assert REG.metro_caveat(a(통합, "", "조례동"), on) is None             # 정하지 못한 주소(metro None)
        assert REG.metro_caveat(a("전라남도", "서구", "치평동"), on) is None
        for other in (a("강원특별자치도", "춘천시", "석사동"), a("서울특별시", "마포구", "공덕동"),
                      a("부산광역시", "해운대구", "우동"), a("세종특별자치시", "", "조치원읍"), a("서울특별", "마포구", "")):
            assert REG.metro_caveat(other, on) is None


@pytest.mark.parametrize("sido,gu,dong", [("전라남도", "서구", "치평동"), ("전남", "광산구", "수완동"),
                                         ("광주광역시", "순천시", "조례동"), ("광주", "여수시", "학동")])
def test_notice_history_does_not_follow_an_old_name_with_a_foreign_district(sido, gu, dong):
    """옛 시도 이름은 제 시군구일 때만 새 이름으로 바꾼다. 전라남도에 서구는 없었으므로 광주 서구의 지정 이력을 잇지 않는다."""
    for on in ("2021-06-01", "2026-10-09"):
        s = REG.status(C, a(sido, gu, dong), on)
        assert s["지정"] is False and s["주석"] == [], on


def test_merged_city_table_matches_bjd_table():
    """행정구역_대응.json 의 통합 표가 법정동코드표의 통합특별시 시군구와 같다. 구는 광역시 규정, 시·군은 도 규정이다."""
    with open(os.path.join(RULES_DIR, "행정구역_대응.json"), encoding="utf-8") as f:
        admin = json.load(f)
    (m,) = admin["통합"]
    assert m["시도"] == 통합 and m["시작"] == "2026-07-01"
    groups = {g["시도"]: g for g in m["옛"]}
    assert set(groups) == {"광주광역시", "전라남도"}
    assert groups["광주광역시"]["적용"] == "광역시" and tuple(groups["광주광역시"]["시군구"]) == 자치구
    assert groups["전라남도"]["적용"] == "도" and tuple(groups["전라남도"]["시군구"]) == 시군
    renamed = {r["옛"]: r for r in admin["이름변경"]}
    for old in groups:
        assert renamed[old]["새"] == 통합 and renamed[old]["시작"] == m["시작"] and renamed[old]["등급"] == "★★★"
    from yangdo import bjd
    b = bjd.load()
    rows = {b.split(c)[1] for c in b._names if c.startswith("12") and c[5:] == "00000" and c != "1200000000"}
    assert rows == set(자치구) | set(시군)
    assert {n for n in rows if n.endswith("구")} == set(자치구)


@pytest.mark.parametrize("sido,gu,dong", [("광주광역시", "서구", "치평동"), (통합, "서구", "치평동"), ("광주특별시", "서구", "치평동"),
                                         ("전라남도", "순천시", "조례동"), (통합, "순천시", "조례동")])
def test_merged_city_notice_history_under_old_and_new_names(sido, gu, dong):
    """조정대상지역 고시 이력은 옛 이름으로 지정됐다. 주소를 어느 이름으로 적어도 같은 이력으로 판정하고 주석을 달지 않는다."""
    s = REG.status(C, a(sido, gu, dong), "2021-06-01")
    assert s["지정"] is True and s["효력발생일"] == "2020-12-18" and s["주석"] == []
    for on in ("2020-12-17", "2026-06-30", "2026-07-01", "2026-10-09"):
        s = REG.status(C, a(sido, gu, dong), on)
        assert s["지정"] is False and s["주석"] == [], on


def test_merged_city_is_not_in_current_designations():
    for regime in RG.REGIMES:
        assert not [n for n in REG.designated_list(regime, "2026-10-09") if n.startswith(통합)]
    assert "전남광주통합특별시 서구" in REG.designated_list(C, "2021-06-01")


def test_city_form_alias_and_unknown_sido():
    assert REG.status(C, a("서울시", "마포구", "공덕동"), "2026-03-15")["지정"] is True
    with pytest.raises(NeedAnswer) as e:
        REG.status(C, a("서울특별", "마포구", "공덕동"), "2026-03-15")
    assert e.value.문항 == "A01"


def test_load_requires_notice_files(tmp_path):
    import shutil
    shutil.copy(os.path.join(RULES_DIR, "행정구역_대응.json"), tmp_path / "행정구역_대응.json")
    with pytest.raises(FileNotFoundError):
        RG.load(str(tmp_path))


def test_empty_district_asks():
    with pytest.raises(NeedAnswer) as e:
        REG.status(C, a("서울특별시", "", ""), "2026-03-15")
    assert e.value.문항 == "A01"
    assert REG.status(C, a("세종특별자치시", "", "보람동"), "2026-03-15", "아니오")["지정"] is False


def test_metro_unknown_sido_is_none():
    assert REG.metro(a("서울특별", "마포구", "공덕동"), "2026-10-09") is None


def test_income_tax_decree_does_not_yet_name_the_merged_city():
    """통합특별시의 자치구에 광역시 규정을, 시·군에 도 규정을 적용하는 것은 개별 법령이 개정될 때까지다.

    받은 소득세법 시행령 판(시행예정 포함)의 지방 저가주택 조문에 통합특별시 문구가 들어오면 이 시험이 실패한다.
    그때는 새 문구대로 행정구역_대응.json 의 통합 표와 regions.metro 를 다시 맞춘다.
    """
    base = os.path.join(RULES_DIR, "조문")
    with open(os.path.join(base, "판목록.json"), encoding="utf-8") as f:
        pans = json.load(f)["법령"]["소득세법 시행령"]
    assert any(p["시행일"] >= "2026-07-01" for p in pans)
    for p in pans:
        with open(os.path.join(base, *p["파일"].split("/")), encoding="utf-8") as f:
            arts = json.load(f)["조문"]
        for jo in ("167의3", "167의10"):
            text = "".join(arts[jo]["text"].split())
            assert "수도권및광역시ㆍ특별자치시(광역시에소속된군" in text, (p["파일"], jo)
            assert "통합특별시" not in text, (p["파일"], jo)

