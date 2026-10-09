# -*- coding: utf-8 -*-
import copy

import pytest

from cases import CASES, addr, asset, facts, house, 마포, 성동, 송파, 춘천
from yangdo import facts as F
from yangdo import judge as J
from yangdo import regions, ruleset

RS = ruleset.load()
REG = regions.load()


def run(f):
    return J.judge(f, F.prepare(f), RS, REG)


def one(name, mutate=None):
    f = copy.deepcopy(CASES[name])
    if mutate:
        mutate(f)
    r = run(f)
    assert r["질문"] == [] and r["다루지않음"] == [], r
    return r["자산"][0]


EXPECT = {
    "A": dict(일세대일주택=True, 비과세=True, 고가주택=True, 전액비과세=False, 중과=None, 단기=None, 장특공="표2", 보유년=12, 거주년=12),
    "B": dict(일세대일주택=False, 비과세=False, 중과=None, 단기=None, 장특공="표1", 보유년=7, 주택수=2),
    "C": dict(비과세=False, 중과=None, 단기="1년미만", 장특공="없음"),
    "D": dict(중과="중과2", 단기=None, 장특공="없음", 주택수_중과=2),
    "E": dict(미등기=True, 단기=None, 장특공="없음"),
    "F": dict(미등기=False, 장특공="표1", 보유년=21),
    "G": dict(일시적2주택=True, 처분기한="2027-05-01", 일세대일주택=True, 전액비과세=True),
    "G2": dict(일시적2주택=True, 처분기한="2026-06-01", 일세대일주택=False, 중과="중과2", 장특공="없음"),
    "G3": dict(일세대일주택=True, 전액비과세=True),
    "H": dict(중과=None, 장특공="표1", 보유년=5),
    "I": dict(전액비과세=True, 공고전계약_취득=True),
    "I2": dict(일세대일주택=True, 비과세=False, 중과=None, 장특공="표1", 거주년=0),
    "J": dict(중과="중과2", 단기="2년미만", 장특공="없음"),
    "K": dict(중과="중과3", 주택수_중과=3),
    "K2": dict(중과="중과2", 주택수_중과=2),
}


@pytest.mark.parametrize("name", sorted(EXPECT))
def test_case_verdicts(name):
    v = one(name)
    for k, want in EXPECT[name].items():
        assert v[k] == want, (name, k, v[k])
    assert v["근거"] and all(c["URL"].startswith("https://www.law.go.kr/") for c in v["근거"])


def test_heavy_has_pending_amendment_warning():
    assert any(w.startswith("계류") for w in one("D")["경고"])
    assert one("H")["경고"] == []


def test_temporary_exemption_notes():
    assert any("한시배제" in m for m in one("H")["확인사항"])
    assert any("154조①5호" in m for m in one("I")["확인사항"])


def _pair(신규취득, 양도일, 계약=None):
    a = asset("Z", "주택", 마포, "2019-03-01", 양도일, 1_000_000_000, 600_000_000,
              거주기간=[["2019-03-01", "2024-03-01"]])
    f = facts([a], [house("H1", 마포, "2019-03-01", 자산id="Z"),
                    house("H2", 성동, 신규취득, 계약일=계약, 계약금지급일=계약)])
    return f, f["자산"][0], f["세대"]["주택목록"][1]


@pytest.mark.parametrize("신규,양도,계약,기관,years", [
    ("2026-08-10", "2026-11-01", None, False, 2),
    ("2026-08-10", "2026-11-01", "2026-07-20", False, 3),
    ("2026-08-10", "2026-09-15", None, False, 3),
    ("2024-05-01", "2026-11-01", None, False, 3),
    ("2026-08-10", "2026-11-01", None, True, 5),
])
def test_disposal_years(신규, 양도, 계약, 기관, years):
    f, a, other = _pair(신규, 양도, 계약)
    f["세대"]["기관이전종사자"] = 기관
    y, cites, notes = J.disposal_years(f, a, other, F.dates.to_date(양도), RS, REG)
    assert y == years and cites


def test_missing_residence_asks_h07():
    f = copy.deepcopy(CASES["A"])
    f["자산"][0]["거주기간"] = None
    assert run(f)["질문"][0]["문항"] == "H07"


def test_missing_exclusion_reasons_asks_x04():
    f = copy.deepcopy(CASES["D"])
    f["자산"][0]["중과배제_사유"] = None
    assert run(f)["질문"][0]["문항"] == "X04"


def test_moreum_contract_date_means_no_exception():
    f = copy.deepcopy(CASES["I"])
    f["자산"][0]["취득"]["계약일"] = None
    f["모름"] = ["A16:I"]
    v = run(f)["자산"][0]
    assert v["공고전계약_취득"] is False and v["비과세"] is False


def test_district_question():
    a = asset("Q", "주택", {"시도": "경기도", "시군구": "화성시", "읍면동": "반송동"}, "2018-01-01", "2026-11-01",
              500_000_000, 300_000_000, 거주기간=[["2018-01-01", "2026-11-01"]])
    f = facts([a], [house("H1", a["소재지"], "2018-01-01", 자산id="Q")])
    q = run(f)["질문"][0]
    assert q["문항"] in ("A01", "A02")


def test_unregistered_other_reason_is_not_unregistered():
    v = one("E", lambda f: f["자산"][0].update(미등기사유="장기할부"))
    assert v["미등기"] is False and any("168" in m for m in v["확인사항"])


def test_not_one_household():
    f = copy.deepcopy(CASES["A"])
    f["세대"]["배우자"] = False
    f["세대"]["1세대요건"] = ["해당없음"]
    v = run(f)["자산"][0]
    assert v["일세대"] is False and v["비과세"] is False and v["장특공"] == "표1"


def test_engine_values():
    def ev(name):
        f = CASES[name]
        return J.engine_values(f, f["자산"][0], F.prepare(f), RS, REG)
    d = ev("D")
    assert d["중과후보"] is True and d["세대주택수"] == 2 and d["과세"] is True and d["양도일"] == "2026-10-15"
    g = ev("G")
    assert g["일시적2주택후보"] is True and g["처분기한초과"] is False and g["과세"] is False and g["신규주택id"] == "H2"
    a = ev("A")
    assert a["비과세후보"] is True and a["보유거주미충족"] is False and a["과세"] is True
    i = ev("I")
    assert i["조정_취득일"] is True and i["계약일_공고일이전"] is True
    assert ev("K2")["지방소재주택있음"] is True and ev("J")["2024-01-10이후취득주택있음"] is True
    empty = J.engine_values({"자산": [{"id": "X"}]}, {"id": "X"}, {"시기": {}}, RS, REG)
    assert set(J.EV_KEYS) <= set(empty) and empty["주택별"] == {}


def _ev_houses(f):
    return J.engine_values(f, f["자산"][0], F.prepare(f), RS, REG)["주택별"]


def test_engine_values_per_house():
    """집마다의 값. 질문지가 집 단위 문항(X01, X03)을 그 집이 필요할 때만 묻는 데 쓴다."""
    k2 = _ev_houses(CASES["K2"])
    assert {h: v["지방소재"] for h, v in k2.items()} == {"H1": False, "H2": False, "H3": True}   # H3 만 춘천
    j = _ev_houses(CASES["J"])
    assert j["H1"]["2024-01-10이후취득"] is True and j["H8"]["2024-01-10이후취득"] is False   # 2025-08-01, 2010-01-01
    assert set(j["H1"]) == set(J.HOUSE_EV_KEYS)


def test_engine_values_per_house_boundaries():
    def acquired(day):
        f = copy.deepcopy(CASES["J"])
        f["세대"]["주택목록"][1]["취득일"] = day
        return _ev_houses(f)["H8"]["2024-01-10이후취득"]
    assert acquired("2024-01-09") is False and acquired("2024-01-10") is True
    # 광역시는 군이 아니면 동 지역이다. 군은 지방이다
    f = copy.deepcopy(CASES["K2"])
    f["세대"]["주택목록"][2]["소재지"] = {"시도": "부산광역시", "시군구": "해운대구", "읍면동": "우동"}
    assert _ev_houses(f)["H3"]["지방소재"] is False
    f["세대"]["주택목록"][2]["소재지"] = {"시도": "부산광역시", "시군구": "기장군", "읍면동": "기장읍"}
    assert _ev_houses(f)["H3"]["지방소재"] is True


@pytest.mark.parametrize("how", ["소재지없음", "소재지가문자열", "모르는시도", "취득일없음", "취득일형식틀림"])
def test_engine_values_per_house_unknown_is_none(how):
    f = copy.deepcopy(CASES["K2"])
    h = f["세대"]["주택목록"][2]
    if how == "소재지없음":
        del h["소재지"]
    elif how == "소재지가문자열":
        h["소재지"] = "춘천시 석사동"
    elif how == "모르는시도":
        h["소재지"] = {"시도": "서울특별", "시군구": "마포구", "읍면동": "공덕동"}
    elif how == "취득일없음":
        h["취득일"] = None
    else:
        h["취득일"] = "2012.01.01"
    ev = J.engine_values(f, f["자산"][0], F.prepare(f), RS, REG)   # 예외 없이 돌아온다
    if how.startswith("취득일"):
        assert ev["주택별"] == {}   # 주택 목록을 날짜로 거르지 못하면 집마다의 값을 내지 않는다
    else:
        assert ev["주택별"]["H3"]["지방소재"] is None and ev["주택별"]["H1"]["지방소재"] is False


def _ev_first(f):
    return J.engine_values(f, f["자산"][0], F.prepare(f), RS, REG)


def _sale(소재지, 취득="2018-01-01", **kw):
    """양도 2026-03-15 인 주택 하나. 성남시는 2022-11-14 부터 구마다 지정이 갈려 구 이름이 없으면 되묻는다."""
    a = asset("S", "주택", 소재지, 취득, "2026-03-15", 900_000_000, 500_000_000, **kw)
    return facts([a], [house("H1", 소재지, 취득, 자산id="S")])


def test_engine_values_flags_address_that_needs_more_detail():
    """고시가 구마다 지정을 가르는 시(성남)를 구 이름 없이 적으면 소재지확인필요(문항 A01 NeedAnswer)와 안내 문장이 나온다."""
    성남 = addr("경기도", "성남시", "정자동")
    ev = _ev_first(_sale(성남))
    assert ev["소재지확인필요"] is True and "구 이름" in ev["소재지안내"]
    assert ev["취득당시소재지확인필요"] is False and ev["취득당시소재지안내"] is None
    ok = _ev_first(_sale(addr("경기도", "성남시 분당구", "정자동")))
    assert ok["소재지확인필요"] is False and ok["소재지안내"] is None
    typo = _ev_first(_sale(addr("서울특별", "마포구", "공덕동")))
    assert typo["소재지확인필요"] is True and "시도 이름" in typo["소재지안내"]
    # 나중 날짜를 모르는 동안은 판정하지 못해 플래그가 서지 않는다
    f = _sale(성남)
    del f["자산"][0]["양도"]["잔금일"]
    assert _ev_first(f)["소재지확인필요"] is False


def test_engine_values_flags_acquisition_address_separately():
    성남 = addr("경기도", "성남시", "정자동")
    ev = _ev_first(_sale(마포, "2023-03-01", 취득당시소재지=성남))
    assert ev["취득당시소재지확인필요"] is True and "구 이름" in ev["취득당시소재지안내"]
    assert ev["소재지확인필요"] is False and ev["소재지안내"] is None
    # 취득당시소재지를 따로 적지 않으면 취득일에도 소재지를 본다. 그 모자람은 소재지 쪽에 선다
    same = _ev_first(_sale(성남, "2023-03-01"))
    assert same["소재지확인필요"] is True and same["취득당시소재지확인필요"] is False
    # 취득일이 2022-11-14 전이면 성남시 전체가 같은 지정이라 구 이름이 없어도 된다
    assert _ev_first(_sale(마포, "2018-01-01", 취득당시소재지=성남))["취득당시소재지확인필요"] is False


# ---- 검토 반영 1차 ----------------------------------------------------------------------------
@pytest.mark.parametrize("name,idx,끝비움", [("D", 0, False), ("D", 1, False), ("G", 0, False), ("G", 1, False),
                                        ("D", None, True), ("G", 1, True)])
def test_engine_values_never_raises_on_half_filled_facts(name, idx, 끝비움):
    f = copy.deepcopy(CASES[name])
    if idx is not None:
        del f["세대"]["주택목록"][idx]["소재지"]       # 주택 목록 한 채에 소재지가 없다
    if 끝비움:
        f["자산"][0]["거주기간"] = [["2019-03-01", None]]   # 거주 구간의 끝이 비어 있다
    ev = J.engine_values(f, f["자산"][0], F.prepare(f), RS, REG)
    assert isinstance(ev, dict) and set(J.EV_KEYS) <= set(ev)
    assert (ev["거주년"] is None) == 끝비움


def test_judge_skips_asset_prepare_sent_back_as_out_of_scope():
    f = copy.deepcopy(CASES["A"])
    f["세대"]["특례주택"] = ["상속주택"]
    prep = F.prepare(f)
    assert [x["자산"] for x in prep["다루지않음"]] == ["A"] and "A" in prep["시기"]
    r = J.judge(f, prep, RS, REG)
    assert r["자산"] == [] and r["질문"] == []


@pytest.mark.parametrize("how", ["삭제", "빈값"])
def test_judge_skips_asset_without_location(how):
    f = copy.deepcopy(CASES["A"])
    if how == "삭제":
        del f["자산"][0]["소재지"]
    else:
        f["자산"][0]["소재지"] = None
    prep = F.prepare(f)
    assert [(q["문항"], q["자산"]) for q in prep["질문"]] == [("A01", "A")]
    r = J.judge(f, prep, RS, REG)
    assert r["자산"] == [] and r["질문"] == []


def test_judge_skips_only_the_sent_back_asset():
    f = copy.deepcopy(CASES["BF"])
    f["자산"][1]["소재지"] = None
    r = J.judge(f, F.prepare(f), RS, REG)
    assert [v["id"] for v in r["자산"]] == ["B"] and r["질문"] == []


def _officetel(주거사용개시일):
    a = asset("O", "주택", 춘천, "2018-03-01", "2026-11-01", 500_000_000, 300_000_000, 주택유형="오피스텔",
              주거사용개시일=주거사용개시일, 보유거주예외=None, 거주기간=[["2025-06-01", "2026-11-01"]])
    return facts([a], [house("H1", 춘천, "2018-03-01", 자산id="O")])


def test_engine_values_counts_holding_from_residential_use_start():
    f = _officetel("2025-06-01")
    ev = J.engine_values(f, f["자산"][0], F.prepare(f), RS, REG)
    assert ev["보유거주미충족"] is True and ev["보유년"] == 8   # 보유년 자체는 취득일 기준 그대로
    assert run(f)["질문"][0]["문항"] == "H10"
    g = _officetel(None)
    assert J.engine_values(g, g["자산"][0], F.prepare(g), RS, REG)["보유거주미충족"] is False


def _gap_case(사유):
    old = asset("Z", "주택", 춘천, "2026-01-10", "2026-11-01", 500_000_000, 300_000_000,
                거주기간=[["2026-01-10", "2026-11-01"]], 보유거주예외=사유)
    return facts([old], [house("H1", 춘천, "2026-01-10", 자산id="Z"), house("H2", 춘천, "2026-07-10")])


@pytest.mark.parametrize("사유", ["수용", "공공임대5년", "부득이1년"])
def test_temporary_gap_not_required_for_154_exemptions(사유):
    r = run(_gap_case(사유))
    assert r["질문"] == [] and r["다루지않음"] == []
    v = r["자산"][0]
    assert v["일시적2주택"] is True and v["일세대일주택"] is True and v["전액비과세"] is True
    assert any("155조①" in m and "1년" in m for m in v["확인사항"])


@pytest.mark.parametrize("사유", ["해외이주", "해외취학근무", "해당없음"])
def test_temporary_gap_still_required_for_other_reasons(사유):
    v = run(_gap_case(사유))["자산"][0]
    assert v["일시적2주택"] is True and v["일세대일주택"] is False
    assert any("1년 안에 취득" in m for m in v["확인사항"])


class _FakeReg:
    """공고일을 마음대로 정하는 가짜 지역 이력. 어디든 조정대상지역이다."""

    def __init__(self, 공고일):
        self.공고일 = 공고일

    def status(self, regime, addr, on, 지구해당=None):
        return {"지정": True, "공고": "가짜", "공고일": self.공고일, "효력발생일": self.공고일, "주석": []}


@pytest.mark.parametrize("계약,계약금,years", [
    ("2026-08-10", "2026-08-12", 3),
    ("2026-08-25", "2026-08-15", 2),
    ("2026-08-15", "2026-08-25", 2),
    (None, None, 2),
])
def test_disposal_years_announcement_exception_needs_both_dates(계약, 계약금, years):
    f, a, other = _pair("2026-09-01", "2026-11-01")
    other["계약일"], other["계약금지급일"] = 계약, 계약금
    y, cites, notes = J.disposal_years(f, a, other, F.dates.to_date("2026-11-01"), RS, _FakeReg("2026-08-20"))
    assert y == years, notes


@pytest.mark.parametrize("값,기대", [("해당없음", False), ("30세이상", True), (["해당없음"], False),
                                    (["소득독립", "해당없음"], True), ([], False), ("", False)])
def test_one_household_accepts_a_plain_string(값, 기대):
    assert J.one_household({"세대": {"배우자": False, "1세대요건": 값}}) is 기대


def test_new_house_acquisition_date_follows_linked_asset_timing():
    z = asset("Z", "주택", 마포, "2019-03-01", "2026-11-01", 1_000_000_000, 600_000_000,
              거주기간=[["2019-03-01", "2024-03-01"]])
    y = asset("Y", "주택", 성동, "2026-08-10", "2027-05-01", 900_000_000, 800_000_000)
    f = facts([z, y], [house("H1", 마포, "2019-03-01", 자산id="Z"),
                       house("H2", 성동, "2026-01-05", 자산id="Y")])   # 목록의 취득일은 자산 쪽과 다르다
    prep = F.prepare(f)
    v = J.judge_asset(f, f["자산"][0], prep, RS, REG)
    assert v["처분기한"] == "2028-08-10"     # 신규 취득 2026-08-10 + 2년(조정대상지역 간 이동)
    ev = J.engine_values(f, f["자산"][0], prep, RS, REG)
    assert ev["신규주택id"] == "H2" and ev["처분기한초과"] is False


# ---- 최종 검토 반영: 해외 출국 예외(H11) -------------------------------------------------------
def _departure(사유, 출국, 취득="2025-05-01", 양도="2026-11-15", 가액=1_000_000_000):
    """보유 2년을 못 채운 송파 아파트 한 채에 해외이주·해외취학근무 예외를 건다."""
    a = asset("Y", "주택", 송파, 취득, 양도, 가액, 800_000_000, 거주기간=[], 보유거주예외=사유, 보유거주예외일자=출국,
              취득__계약일=취득, 취득__계약금지급일=취득)   # 조정대상지역 취득이라 계약일을 묻는다(공고일 뒤라 거주 면제는 없다)
    return facts([a], [house("H1", 송파, 취득, 자산id="Y")])


def _verdict(f):
    r = run(f)
    assert r["질문"] == [] and r["다루지않음"] == [], r
    return r["자산"][0]


@pytest.mark.parametrize("사유", ["해외이주", "해외취학근무"])
def test_departure_exemption_applies_when_owned_on_departure_and_sold_within_two_years(사유):
    v = _verdict(_departure(사유, "2025-09-01"))
    assert v["비과세"] is True and v["전액비과세"] is True
    assert any("출국일(2025-09-01)" in m and "154조①2호" in m for m in v["확인사항"])


@pytest.mark.parametrize("사유", ["해외이주", "해외취학근무"])
def test_departure_before_acquisition_is_not_exempt(사유):
    """출국 2023-01-01, 취득 2025-06-01, 양도 2026-11-15. 출국일에 그 집이 없었으므로 예외가 아니다."""
    v = _verdict(_departure(사유, "2023-01-01", 취득="2025-06-01"))
    assert v["비과세"] is False and v["전액비과세"] is False
    assert any("출국일(2023-01-01) 현재 이 주택을 보유하지 않았" in m for m in v["확인사항"])
    assert not any("예외(%s" % 사유 in m for m in v["확인사항"])


@pytest.mark.parametrize("출국,적용", [("2024-11-15", True), ("2024-11-14", False)])
def test_departure_two_year_limit_includes_last_day(출국, 적용):
    """양도 2026-11-15 는 출국 2024-11-15 로부터 2년째 날이라 안에 든다. 하루 앞선 출국은 2년을 넘긴다."""
    v = _verdict(_departure("해외이주", 출국, 취득="2024-05-01"))
    assert v["비과세"] is 적용
    if not 적용:
        assert any("2년 안에 양도하지 않" in m for m in v["확인사항"])


@pytest.mark.parametrize("취득,적용", [("2025-09-01", True), ("2025-09-02", False)])
def test_departure_acquired_on_departure_day_counts_as_owned(취득, 적용):
    assert _verdict(_departure("해외취학근무", "2025-09-01", 취득=취득))["비과세"] is 적용


@pytest.mark.parametrize("사유", ["해외이주", "해외취학근무"])
def test_departure_date_missing_asks_h11(사유):
    f = _departure(사유, None)
    q = run(f)["질문"]
    assert [(x["문항"], x["자산"]) for x in q] == [("H11", "Y")]


def test_departure_date_unknown_does_not_exempt():
    f = _departure("해외이주", None)
    f["모름"] = ["H11:Y"]
    v = _verdict(f)
    assert v["비과세"] is False and any("출국일을 알 수 없" in m for m in v["확인사항"])


@pytest.mark.parametrize("사유", ["수용", "공공임대5년", "부득이1년"])
def test_other_exemptions_do_not_need_departure_date(사유):
    v = _verdict(_departure(사유, None))
    assert v["비과세"] is True and v["전액비과세"] is True


# ---- 최종 검토 반영: 주택으로 용도를 바꾼 건물의 장기보유특별공제(소득세법 제95조⑤) -------------
def _converted(가액=2_000_000_000, 거주=(("2023-06-01", "2026-11-15"),), 전환="2023-06-01"):
    a = asset("W", "주택", 송파, "2010-03-01", "2026-11-15", 가액, 800_000_000, 주택유형="주거용근생",
              주거사용개시일=전환, 거주기간=[list(x) for x in 거주])
    return facts([a], [house("H1", 송파, "2010-03-01", 자산id="W")])


def test_converted_building_with_table2_is_out_of_scope():
    """근생 건물을 2023-06-01 에 주거로 바꾸고 20억에 팔면 표2 가 걸린다. 건물 기간은 표1 이라 표2 를 전 기간에 줄 수 없다."""
    r = run(_converted())
    assert r["자산"] == [] and r["질문"] == []
    assert r["다루지않음"] == [{"자산": "W", "내용": "주택으로 용도를 바꾼 건물의 장기보유특별공제(소득세법 제95조⑤)", "계획": "5"}]


def test_converted_building_fully_exempt_is_unaffected():
    v = run(_converted(가액=1_000_000_000))["자산"][0]
    assert v["전액비과세"] is True and v["장특공"] == "없음"


def test_converted_building_without_table2_is_unaffected():
    """거주 2년 미만이면 표1 이라 제95조⑤ 의 표2 합산이 걸리지 않는다."""
    r = run(_converted(거주=(("2025-12-01", "2026-11-15"),)))
    assert r["다루지않음"] == [] and r["자산"][0]["장특공"] == "표1"


def test_house_never_converted_still_gets_table2():
    f = _converted(전환=None)
    assert run(f)["자산"][0]["장특공"] == "표2"
    f["자산"][0]["주거사용개시일"] = "2010-03-01"   # 취득일과 같으면 바꾼 것이 아니다
    assert run(f)["자산"][0]["장특공"] == "표2"


def test_converted_building_reaches_engine_as_out_of_scope():
    from yangdo import engine
    r = engine.calculate(_converted(), today="2026-10-09")
    assert r["상태"] == "질문" and r["계산"] is None
    assert r["다루지않음"][0]["계획"] == "5" and "제95조⑤" in r["다루지않음"][0]["내용"]


# ---- 최종 검토 반영: 일반주택 10호 확인사항 ----------------------------------------------------
def test_heavy_two_houses_notes_item_10_of_article_167_10():
    notes = one("D")["확인사항"]
    m = [x for x in notes if "제167조의10①10호" in x]
    assert len(m) == 1
    assert "제167조의10①1호부터 7호까지" in m[0] and "다른 주택의 배제 사유를 확인하라" in m[0] and "중과하지 않는다" in m[0]


def test_heavy_three_houses_notes_item_10_of_article_167_3():
    notes = one("K")["확인사항"]
    m = [x for x in notes if "제167조의3①10호" in x]
    assert len(m) == 1
    assert "제167조의3①1호부터 8호까지 및 8호의2" in m[0] and "일반주택" in m[0] and "다른 주택의 배제 사유를 확인하라" in m[0]
    assert not any("제167조의10①10호" in x for x in notes)


def test_item_10_note_absent_when_not_heavy():
    for name in ("A", "B", "H", "I"):
        assert not any("10호" in x and "배제 사유를 확인" in x for x in one(name)["확인사항"]), name


# ---- 최종 검토 반영: 처분기한 연장 사유(시행령 제155조⑱) ---------------------------------------
@pytest.mark.parametrize("사유,호", [("자산관리공사", "1호"), ("경매신청", "2호"), ("공매", "3호"), ("현금청산소송", "4호 또는 5호")])
def test_extension_reason_names_the_item_of_155_18(사유, 호):
    """G2 는 신규 주택 취득 3년이 하루 지난 뒤 양도한다. 연장 사유가 있으면 기한 안 양도로 본다. 현금청산소송 코드는 4호와 5호(수용재결·매도청구)를 함께 맡는다."""
    v = one("G2", lambda f: f["자산"][0].update(처분기한연장사유=사유))
    assert v["일세대일주택"] is True and v["전액비과세"] is True
    m = [x for x in v["확인사항"] if "제155조⑱" in x]
    assert len(m) == 1 and ("제155조⑱%s" % 호) in m[0] and 사유 in m[0]


def test_no_extension_reason_keeps_deadline_passed():
    v = one("G2")
    assert v["일세대일주택"] is False and not any("제155조⑱" in x for x in v["확인사항"])


def test_extension_option_codes_match_question_bank():
    """T03 선택지의 연장 사유 코드는 모두 판정이 읽는 코드다. 4호와 5호는 같은 코드(현금청산소송) 하나가 맡는다."""
    import json
    from yangdo import QUESTIONS_PATH
    with open(QUESTIONS_PATH, encoding="utf-8") as fh:
        q = {x["id"]: x for x in json.load(fh)["문항"]}["T03"]
    codes = {c["코드"] for c in q["선택지"]} - {"해당없음"}
    assert codes == J.EXTEND_REASONS
    assert "수용재결" in next(c["표시"] for c in q["선택지"] if c["코드"] == "현금청산소송")


# ---- 최종 검토 반영: judge() 최상위 확인사항·경고 -----------------------------------------------
def _two_heavy_assets():
    """중과로 계산되는 주택 둘(D, E2). 집은 판 집 둘과 송파집, 모두 셋이다."""
    from cases import D자산
    d2 = copy.deepcopy(D자산)
    d2["id"] = "E2"
    return facts([D자산, d2], [house("H1", 마포, "2021-03-01", 자산id="D"), house("H2", 마포, "2021-03-01", 자산id="E2"),
                              house("H8", addr("서울특별시", "송파구", "잠실동"), "2010-01-01")])


def test_judge_top_level_lists_aggregate_per_asset_notes():
    r = run(_two_heavy_assets())
    assert [v["id"] for v in r["자산"]] == ["D", "E2"]
    want_notes = ["%s: %s" % (v["id"], m) for v in r["자산"] for m in v["확인사항"]]
    want_warns = ["%s: %s" % (v["id"], w) for v in r["자산"] for w in v["경고"]]
    assert r["확인사항"] == want_notes and r["경고"] == want_warns
    assert {x.split(": ")[0] for x in r["확인사항"]} == {"D", "E2"}
    assert {w.split(": ")[0] for w in r["경고"]} == {"D", "E2"}


def test_judge_top_level_warnings_carry_asset_id():
    r = run(copy.deepcopy(CASES["D"]))
    assert r["경고"] and all(w.startswith("D: ") for w in r["경고"]) and any("계류" in w for w in r["경고"])
    assert run(copy.deepcopy(CASES["H"]))["경고"] == []


def test_judge_top_level_lists_have_no_duplicates():
    r = run(_two_heavy_assets())
    assert len(set(r["확인사항"])) == len(r["확인사항"]) and len(set(r["경고"])) == len(r["경고"])


# ---- 최종 검토 반영: 경계일 회귀 시험(최종 검토에서 손으로 확인한 날짜) --------------------------
@pytest.mark.parametrize("신규,양도,계약,years", [
    ("2026-08-03", "2026-11-01", None, 3),           # 부칙 제36737호: 신규 취득이 2026-08-03 이전이면 종전 규정
    ("2026-08-04", "2026-11-01", None, 2),           # 2026-08-04 이후 취득이면 2년
    ("2026-08-10", "2026-11-01", "2026-08-03", 3),   # 계약과 계약금 지급이 2026-08-03 이전이면 3년
    ("2026-08-10", "2026-11-01", "2026-08-04", 2),
    ("2026-08-10", "2026-09-30", None, 3),           # 종전 주택 양도가 2026-10-01 전이면 3년
    ("2026-08-10", "2026-10-01", None, 2),
])
def test_disposal_years_supplementary_rule_boundaries(신규, 양도, 계약, years):
    f, a, other = _pair(신규, 양도, 계약)
    y, cites, notes = J.disposal_years(f, a, other, F.dates.to_date(양도), RS, REG)
    assert y == years, notes


def test_supplementary_contract_exception_needs_deposit_on_or_before_cutoff_too():
    f, a, other = _pair("2026-08-10", "2026-11-01", "2026-08-03")
    other["계약금지급일"] = "2026-08-04"
    y, _, _ = J.disposal_years(f, a, other, F.dates.to_date("2026-11-01"), RS, REG)
    assert y == 2


@pytest.mark.parametrize("양도,기한", [("2026-09-30", "2029-08-10"), ("2026-10-01", "2028-08-10")])
def test_temporary_deadline_switches_on_2026_10_01(양도, 기한):
    f, _, _ = _pair("2026-08-10", 양도)
    assert _verdict(f)["처분기한"] == 기한


def _heavy_sale(양도, 소재지=송파, 취득="2021-03-01"):
    """송파 주택 둘 중 하나를 양도일에 판다. 계약은 양도 30일 전이라 조정대상지역 공고일 뒤다."""
    from datetime import timedelta
    계약 = (F.dates.to_date(양도) - timedelta(days=30)).isoformat()
    a = asset("T", "주택", 소재지, 취득, 양도, 900_000_000, 600_000_000, 양도__계약일=계약, 양도__계약금수령일=계약,
              기준시가={"취득": {"주택": 400_000_000}, "양도": {"주택": 650_000_000}})
    return facts([a], [house("H1", 소재지, 취득, 자산id="T"), house("H8", 송파, "2010-01-01")])


@pytest.mark.parametrize("양도,중과", [("2026-05-09", None), ("2026-05-10", "중과2")])
def test_temporary_exclusion_ends_after_2026_05_09(양도, 중과):
    v = _verdict(_heavy_sale(양도))
    assert v["중과"] == 중과
    assert any("한시배제 가목" in m for m in v["확인사항"]) is (중과 is None)


@pytest.mark.parametrize("양도,기한", [("2025-02-27", "2025-05-09"), ("2025-02-28", "2026-05-09")])
def test_temporary_exclusion_deadline_follows_edition_in_force(양도, 기한):
    """2025-02-28 판부터 한시배제 양도기한이 2025-05-09 에서 2026-05-09 로 늘었다."""
    assert RS.value("중과.한시배제.가목.양도기한", 양도) == 기한
    v = _verdict(_heavy_sale(양도))
    assert v["중과"] is None and any("%s 까지 양도해" % 기한 in m for m in v["확인사항"])
