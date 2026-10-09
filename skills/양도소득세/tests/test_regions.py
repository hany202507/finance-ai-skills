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
    assert REG.metro(a("광주광역시", "서구", "치평동"), "2026-10-09") is None
    assert REG.capital(a("경기", "평택시")) is True and REG.capital(a("부산", "해운대구")) is False


def test_renamed_with_low_grade_is_noted():
    s = REG.status(C, a("광주광역시", "서구", "치평동"), "2021-06-01")
    assert s["지정"] is True and s["주석"]


def test_city_without_district_must_name_district():
    with pytest.raises(NeedAnswer) as e:
        REG.status(C, a("경기도", "성남시", "정자동"), "2024-01-01")
    assert e.value.문항 == "A01"
    assert REG.status(C, a("경기도", "성남시 분당구", "정자동"), "2024-01-01")["지정"] is False


def test_metro_uses_date_for_merger():
    assert REG.metro(a("광주광역시", "서구", "치평동"), "2025-06-01") is True
    assert REG.metro(a("광주광역시", "광산구", "수완동"), "2025-06-01") is True
    assert REG.metro(a("전라남도", "순천시", "조례동"), "2025-06-01") is False
    assert REG.metro(a("광주광역시", "서구", "치평동"), "2026-10-09") is None


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
