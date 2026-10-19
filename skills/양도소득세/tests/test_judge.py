# -*- coding: utf-8 -*-
import copy

import pytest

from cases import CASES, EXPECT as EXPECT_AMOUNTS, addr, asset, facts, house, 마포, 성동, 송파, 춘천
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


@pytest.mark.parametrize("값,기대", [(["해당없음"], False), (["30세이상"], True), (["소득독립", "해당없음"], True), ([], False)])
def test_one_household_reads_the_requirement_list(값, 기대):
    """H02 는 복수선택이라 목록으로 온다. 글자 하나로 온 값은 prepare 가 H02 를 되묻고 여기까지 오지 않는다."""
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
    assert r["다루지않음"] == [{"자산": "W", "내용": "주택으로 용도를 바꾼 건물의 장기보유특별공제(소득세법 제95조⑤)", "계획": "미정"}]


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
    assert r["다루지않음"][0]["계획"] == "미정" and "제95조⑤" in r["다루지않음"][0]["내용"]


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


OPEN_18_NOTE = "시행령 제155조⑱ 본문은 사유가 다른 주택을 취득한 날부터 3년이 되는 날 현재 있어야 한다고 적는다"


def _two_year_deadline_passed(사유):
    """신규 주택 취득 2026-08-10 이라 처분기한이 2년(2028-08-10)이고, 양도는 그 뒤인 2028-09-01 이다."""
    f, _, _ = _pair("2026-08-10", "2028-09-01")
    f["자산"][0]["처분기한연장사유"] = 사유
    return _verdict(f)


@pytest.mark.parametrize("사유", ["자산관리공사", "경매신청", "공매", "현금청산소송"])
def test_extension_on_a_two_year_deadline_notes_the_open_reading(사유):
    """처분기한이 2년인 경우에도 ⑱ 연장을 적용하는지는 확인되지 않았다. 연장을 적용하되 그 사실을 확인사항에 남긴다(m-8)."""
    v = _two_year_deadline_passed(사유)
    assert v["처분기한"] == "2028-08-10" and v["일세대일주택"] is True and v["전액비과세"] is True
    m = [x for x in v["확인사항"] if OPEN_18_NOTE in x]
    assert len(m) == 1 and "처분기한이 2년인 경우에 이 연장을 적용하는지는 확인되지 않았다" in m[0] and "세무 전문가" in m[0]
    assert len([x for x in v["확인사항"] if "제155조⑱" in x and x != m[0]]) == 1   # 연장을 적용했다는 기존 확인사항은 그대로다


def test_extension_note_is_not_added_for_a_three_year_deadline_or_no_reason():
    v = one("G2", lambda f: f["자산"][0].update(처분기한연장사유="경매신청"))   # 처분기한 3년 사례
    assert not any(OPEN_18_NOTE in x for x in v["확인사항"])
    f, a, _ = _pair("2026-08-10", "2028-09-01")   # 2년 기한이 지났지만 연장 사유가 없다. 비과세가 아니라 중과 판정에 필요한 값을 채운다
    a["양도"].update(계약일="2028-06-01", 계약금수령일="2028-06-01")
    a["기준시가"] = {"취득": {"주택": 400_000_000}, "양도": {"주택": 650_000_000}}
    v = _verdict(f)
    assert v["일세대일주택"] is False and not any("제155조⑱" in x for x in v["확인사항"])
    f, _, _ = _pair("2026-08-10", "2028-08-01")   # 2년 기한 안 양도라 연장을 쓰지 않는다
    f["자산"][0]["처분기한연장사유"] = "경매신청"
    assert not any("제155조⑱" in x for x in _verdict(f)["확인사항"])


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
    d2["양도"]["잔금일"] = "2026-10-20"  # 같은 날 여러 채 양도는 다루지않음이라 날을 나눈다
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


def _heavy_sale(양도, 소재지=송파, 취득="2021-03-01", 계약=None):
    """송파 주택 둘 중 하나를 양도일에 판다. 계약은 따로 주지 않으면 양도 30일 전이라 조정대상지역 공고일 뒤다."""
    from datetime import timedelta
    계약 = 계약 or (F.dates.to_date(양도) - timedelta(days=30)).isoformat()
    a = asset("T", "주택", 소재지, 취득, 양도, 900_000_000, 600_000_000, 양도__계약일=계약, 양도__계약금수령일=계약,
              기준시가={"취득": {"주택": 400_000_000}, "양도": {"주택": 650_000_000}})
    return facts([a], [house("H1", 소재지, 취득, 자산id="T"), house("H8", 송파, "2010-01-01")])


@pytest.mark.parametrize("양도,계약,중과,목", [
    ("2026-05-09", "2026-04-09", None, "가목"),
    ("2026-05-10", "2026-05-10", "중과2", None),     # 가목 기한 뒤 양도이고 계약도 2026-05-09 뒤라 다목에도 걸리지 않는다
    ("2026-05-10", "2026-04-10", None, "다목"),      # 2026-05-09 까지 계약하고 4개월 안에 양도
])
def test_temporary_exclusion_ends_after_2026_05_09(양도, 계약, 중과, 목):
    v = _verdict(_heavy_sale(양도, 계약=계약))
    assert v["중과"] == 중과
    for x in ("가목", "다목"):
        assert any("한시배제 %s" % x in m for m in v["확인사항"]) is (x == 목)


@pytest.mark.parametrize("양도,기한", [("2025-02-27", "2025-05-09"), ("2025-02-28", "2026-05-09")])
def test_temporary_exclusion_deadline_follows_edition_in_force(양도, 기한):
    """2025-02-28 판부터 한시배제 양도기한이 2025-05-09 에서 2026-05-09 로 늘었다."""
    assert RS.value("중과.한시배제.가목.양도기한", 양도) == 기한
    v = _verdict(_heavy_sale(양도))
    assert v["중과"] is None and any("%s 까지 양도해" % 기한 in m for m in v["확인사항"])


# ---- 판 집 자신의 중과배제: 사유(X04), 시행령 제167조의10①9호·11호, 판 집 12호·지방 저가 (최종 재검토 m-2) ----
# 사례 D(마포 주택 둘, 중과2 로 152,610,000원)에서 중과만 빠지면 사례 H 와 같은 숫자다(양도가액 9억원, 취득가액 6억원, 보유 5년, 표1)
NO_HEAVY_TAX = EXPECT_AMOUNTS["H"]["산출세액"]


def _d_with(mutate):
    f = copy.deepcopy(CASES["D"])
    mutate(f)
    return f


def _engine_tax(f):
    from yangdo import engine
    r = engine.calculate(f, today="2026-10-09")
    assert r["상태"] == "완료", (r["질문"], r["다루지않음"])
    return r["계산"]["합계"]["산출세액"]


def _note(v, word):
    return [m for m in v["확인사항"] if word in m]


def test_case_d_is_heavy_without_any_exclusion():
    v = one("D")
    assert v["중과"] == "중과2" and _engine_tax(CASES["D"]) == 152_610_000


@pytest.mark.parametrize("사유", [["상속5년"], ["사원용"], ["문화유산"], ["저당권3년"], ["어린이집"], ["부득이3억"], ["소송3년"],
                                 ["조특법감면주택"], ["상속5년", "사원용"]])
def test_valid_exclusion_reason_removes_heavy(사유):
    f = _d_with(lambda f: f["자산"][0].update(중과배제_사유=사유))
    v = run(f)["자산"][0]
    assert v["중과"] is None and v["장특공"] == "표1"
    assert len(_note(v, "중과배제 사유 %s 를 입력대로 인정했다" % ", ".join(사유))) == 1
    assert _engine_tax(f) == NO_HEAVY_TAX


@pytest.mark.parametrize("사유", [[], ["해당없음"]])
def test_no_exclusion_reason_keeps_heavy(사유):
    f = _d_with(lambda f: f["자산"][0].update(중과배제_사유=사유))
    assert run(f)["자산"][0]["중과"] == "중과2"


def test_long_term_rental_registration_is_noted_but_not_judged():
    """등록임대주택(시행령 제167조의3①2호)은 판정하지 않는다. 확인사항만 남기고 중과로 계산한다."""
    f = _d_with(lambda f: f["자산"][0].update(중과배제_사유=["장기임대등록"]))
    v = run(f)["자산"][0]
    assert v["중과"] == "중과2" and len(_note(v, "등록임대주택 중과배제")) == 1 and not _note(v, "입력대로 인정했다")
    assert _engine_tax(f) == 152_610_000
    g = _d_with(lambda f: f["자산"][0].update(중과배제_사유=["장기임대등록", "사원용"]))
    w = run(g)["자산"][0]
    assert w["중과"] is None and _note(w, "중과배제 사유 사원용 를 입력대로 인정했다") and _note(w, "등록임대주택 중과배제")


def _small_price(가격, 정비=None, 모름=False):
    def m(f):
        f["자산"][0]["기준시가"] = {"취득": {"주택": 40_000_000}, "양도": {"주택": 가격}}
        f["자산"][0]["정비구역"] = 정비
        if 모름:
            f["모름"] = ["X02:D"]
    return _d_with(m)


@pytest.mark.parametrize("가격", [90_000_000, 100_000_000])
def test_item_9_small_house_outside_redevelopment_zone_removes_heavy(가격):
    f = _small_price(가격, 정비="아니오")
    v = run(f)["자산"][0]
    assert v["중과"] is None and len(_note(v, "시행령 제167조의10①9호")) == 1
    assert _engine_tax(f) == NO_HEAVY_TAX


@pytest.mark.parametrize("가격,정비", [(100_000_001, "아니오"), (90_000_000, "예")])
def test_item_9_needs_price_at_most_100_million_and_no_redevelopment_zone(가격, 정비):
    f = _small_price(가격, 정비=정비)
    v = run(f)["자산"][0]
    assert v["중과"] == "중과2" and not _note(v, "제167조의10①9호")


def test_item_9_with_unknown_redevelopment_zone_keeps_heavy_with_a_note():
    v = run(_small_price(90_000_000, 정비=None, 모름=True))["자산"][0]
    assert v["중과"] == "중과2" and len(_note(v, "정비구역 여부가 정해지지 않아 중과로 계산했다")) == 1
    r = run(_small_price(90_000_000, 정비=None))   # 답이 없으면 X02 를 묻는다
    assert [q["문항"] for q in r["질문"]] == ["X02"]


def _contract(계약, 계약금):
    return _d_with(lambda f: f["자산"][0]["양도"].update(계약일=계약, 계약금수령일=계약금))


def test_item_11_contract_on_or_before_announcement_removes_heavy():
    공고일 = REG.status("조정대상지역", 마포, "2026-10-15")["공고일"]    # 2025-10-16 국토교통부공고
    f = _contract(공고일, 공고일)
    v = run(f)["자산"][0]
    assert v["중과"] is None and len(_note(v, "공고일(%s) 이전에 양도 매매계약·계약금 수령을 해 중과하지 않았다" % 공고일)) == 1
    assert _engine_tax(f) == NO_HEAVY_TAX


@pytest.mark.parametrize("계약,계약금", [("2025-10-16", "2025-10-17"), ("2025-10-17", "2025-10-16"), ("2025-10-17", "2025-10-17")])
def test_item_11_needs_both_contract_and_deposit_on_or_before_announcement(계약, 계약금):
    v = run(_contract(계약, 계약금))["자산"][0]
    assert v["중과"] == "중과2" and not _note(v, "공고일(2025-10-16) 이전에 양도")


def test_sold_house_of_item_12_removes_heavy():
    """판 집이 시행령 제167조의3①12호 주택(제12호해당)이면 중과하지 않는다."""
    f = _d_with(lambda f: f["세대"]["주택목록"][0].update(제12호해당="소형신축"))
    v = run(f)["자산"][0]
    assert v["중과"] is None and len(_note(v, "제167조의3①12호 주택이라 중과하지 않았다")) == 1
    assert _engine_tax(f) == NO_HEAVY_TAX


class _RegionWithLocalDesignation:
    """판 집이 광역시도 수도권도 아닌 지방인데 조정대상지역인 가상의 이력. 지방 저가주택 판정을 시험한다(실제 고시에는 없는 조합이다)."""

    def status(self, regime, addr, on, 지구해당=None):
        return {"지정": True, "공고": "가짜", "공고일": "2020-01-01", "효력발생일": "2020-01-01", "주석": []}

    def metro(self, addr, on=None):
        return False

    def metro_caveat(self, addr, on):
        return None


def _local_house(기준시가):
    return _d_with(lambda f: f["자산"][0].update(기준시가={"취득": {"주택": 100_000_000}, "양도": {"주택": 기준시가}}))


@pytest.mark.parametrize("가격,중과", [(300_000_000, None), (300_000_001, "중과2")])
def test_sold_local_cheap_house_removes_heavy(가격, 중과):
    f = _local_house(가격)
    r = J.judge(f, F.prepare(f), RS, _RegionWithLocalDesignation())
    assert r["질문"] == [] and r["다루지않음"] == [], r
    v = r["자산"][0]
    assert v["중과"] == 중과 and bool(_note(v, "판 집이 지방 저가주택이거나")) is (중과 is None)


# ---- 한시배제 나목·다목(시행령 제167조의10①12의2, 제167조의3①12의2, 2026-04-23 신설) ----
# 송파구는 나목4) 표에 없는 지역(4개월), 마포구는 표 안(6개월)이다. 보유 2년 미만은 가·나·다목 모두 해당하지 않는다(12호의2 본문, 정답지 사례 08)

def _late_sale(양도, 취득, 계약, 곳=송파, 허가대상="아니오", 허가=None, 계약금=None):
    """같은 곳 주택 둘 중 하나를 판다. 양도는 한시배제 가목 양도기한(2026-05-09) 뒤라 가목에는 걸리지 않는다."""
    kw = dict(양도__계약일=계약, 양도__계약금수령일=계약금 or 계약,
              기준시가={"취득": {"주택": 400_000_000}, "양도": {"주택": 650_000_000}}, 토지거래허가대상=허가대상)
    if 허가 is not None:
        kw["토지거래허가"] = 허가
    a = asset("T", "주택", 곳, 취득, 양도, 900_000_000, 600_000_000, **kw)
    return facts([a], [house("H1", 곳, 취득, 자산id="T"), house("H8", 곳, "2010-01-01")])


def _late_note(v, 목):
    return [m for m in v["확인사항"] if "한시배제 %s" % 목 in m]


@pytest.mark.parametrize("곳,양도,중과", [
    (송파, "2026-09-06", None), (송파, "2026-09-07", "중과2"),        # 표에 없는 지역: 계약일 2026-05-06 부터 4개월
    (마포, "2026-11-06", None), (마포, "2026-11-07", "중과2"),        # 표 안: 6개월
])
def test_temporary_exclusion_da_months_by_region(곳, 양도, 중과):
    v = _verdict(_late_sale(양도, "2021-03-01", "2026-05-06", 곳=곳))
    assert v["중과"] == 중과
    assert bool(_late_note(v, "다목")) is (중과 is None)
    assert (v["장특공"] == "표1") is (중과 is None)
    if 중과 is None:
        # 결과 md 와 신고_확인.md 에 그대로 찍히는 문구다. 「표 밖」 같은 공간 비유를 쓰지 않는다
        note = _late_note(v, "다목")[0]
        assert ("나목4) 표의 지역" if 곳 == 마포 else "나목4) 표에 없는 지역") in note and "밖" not in note


@pytest.mark.parametrize("계약,계약금", [("2026-05-10", None), ("2026-05-09", "2026-05-10")])
def test_temporary_exclusion_da_needs_contract_and_deposit_by_deadline(계약, 계약금):
    v = _verdict(_late_sale("2026-06-05", "2021-03-01", 계약, 계약금=계약금))
    assert v["중과"] == "중과2" and not _late_note(v, "다목")


def test_temporary_exclusion_da_only_when_held_two_years():
    v = _verdict(_late_sale("2026-06-05", "2025-05-01", "2026-05-06"))
    assert v["보유년"] < 2 and v["중과"] == "중과2" and v["단기"] is not None
    assert not any("한시배제" in m for m in v["확인사항"])


def test_temporary_exclusion_holding_boundary_is_two_years_exactly():
    """가목과 같은 값(보유년)과 같은 기준(중과.한시배제.보유)을 쓴다. 만 2년이 되는 날은 배제된다."""
    v = _verdict(_late_sale("2026-06-05", "2024-06-05", "2026-05-06"))
    assert v["보유년"] == 2 and v["중과"] is None and _late_note(v, "다목")
    v = _verdict(_late_sale("2026-06-05", "2024-06-06", "2026-05-06"))
    assert v["보유년"] == 1 and v["중과"] == "중과2"


@pytest.mark.parametrize("곳,계약,양도,중과", [
    (송파, "2026-05-06", "2026-09-06", None),          # 신청기한 안 계약: 계약일부터 4개월
    (송파, "2026-05-25", "2026-09-09", None),          # 2026-05-10 이후 계약: 4개월(9-25)보다 이른 2026-09-09 까지
    (송파, "2026-05-25", "2026-09-10", "중과2"),
    (마포, "2026-06-01", "2026-11-09", None),          # 표 안 늦은 계약: 6개월(12-01)보다 이른 2026-11-09 까지
    (마포, "2026-06-01", "2026-11-10", "중과2"),
])
def test_temporary_exclusion_na(곳, 계약, 양도, 중과):
    f = _late_sale(양도, "2021-03-01", 계약, 곳=곳, 허가대상="예", 허가={"신청일": "2026-05-01", "허가일": "2026-05-20"})
    v = _verdict(f)
    assert v["중과"] == 중과 and bool(_late_note(v, "나목")) is (중과 is None)


def test_temporary_exclusion_na_needs_application_by_deadline():
    f = _late_sale("2026-08-01", "2021-03-01", "2026-06-01", 허가대상="예", 허가={"신청일": "2026-05-10", "허가일": "2026-05-30"})
    assert _verdict(f)["중과"] == "중과2"


def test_temporary_exclusion_na_asks_permit_dates():
    r = run(_late_sale("2026-08-01", "2021-03-01", "2026-06-01", 허가대상="예"))
    assert [q["문항"] for q in r["질문"]] == ["X06"]


def test_temporary_exclusion_unknown_permit_status_keeps_heavy_with_note():
    v = _verdict(_late_sale("2026-06-05", "2021-03-01", "2026-05-06", 허가대상="모름"))
    assert v["중과"] == "중과2" and any("토지거래허가 대상인지 몰라" in m for m in v["확인사항"])


def test_temporary_exclusion_not_after_latest_deadline():
    """2026-11-09 뒤 양도는 나·다목 어느 쪽으로도 배제되지 않고 토지거래허가 질문도 하지 않는다."""
    f = _late_sale("2026-11-10", "2021-03-01", "2026-05-09", 곳=마포)
    del f["자산"][0]["토지거래허가대상"]
    v = _verdict(f)
    assert v["중과"] == "중과2"


def test_case_g2_with_contract_before_deadline_is_not_heavy():
    """이슈 #2 의 재현. 사례 G2 의 계약일만 2026-05-01 로 당기면 다목으로 중과가 빠지고 장특공 표1(7년)이 붙는다."""
    def early(f):
        f["자산"][0]["양도"]["계약일"] = f["자산"][0]["양도"]["계약금수령일"] = "2026-05-01"
    v = one("G2", early)
    assert v["중과"] is None and v["장특공"] == "표1" and v["보유년"] == 7


# --- 전남광주통합특별시 주소의 지방 저가주택 판정 ---

def _k2_with_third(시도, 시군구, 읍면동, 양도일=None):
    """사례 K2(송파 집 양도, 강남 집, 셋째 집 기준시가 2억원)의 셋째 집 소재지만 바꾼다."""
    f = copy.deepcopy(CASES["K2"])
    for h in f["세대"]["주택목록"]:
        if h["id"] == "H3":
            h["소재지"] = addr(시도, 시군구, 읍면동)
    if 양도일:
        f["자산"][0]["양도"]["잔금일"] = 양도일
    return f


특례_확인 = "시·군 관할구역 특례"


@pytest.mark.parametrize("시도", ["전라남도", "전남", "전남광주통합특별시"])
@pytest.mark.parametrize("양도일", [None, "2026-06-30"])            # K2 의 양도일은 통합 시행일인 2026-07-01 이다
def test_merged_city_county_house_is_a_local_low_price_house(시도, 양도일):
    """통합특별시의 시·군(옛 전라남도) 집은 도 지역이라 기준시가 3억원 이하면 중과 주택 수에서 뺀다. 춘천 집(K2)과 같은 결과다.
    통합 뒤 양도일에 시의 동 지역 집을 빼면 특례를 적용했다는 확인사항을 한 줄 단다. 통합 전 양도일에는 달지 않는다."""
    f = _k2_with_third(시도, "순천시", "조례동", 양도일)
    v = run(f)["자산"][0]
    assert v["중과"] == "중과2" and v["주택수_중과"] == 2 and not _note(v, "정하지 못해")
    assert J.engine_values(f, f["자산"][0], F.prepare(f), RS, REG)["주택별"]["H3"]["지방소재"] is True
    notes = _note(v, 특례_확인)
    if 양도일 is None:
        assert _engine_tax(f) == EXPECT_AMOUNTS["K2"]["산출세액"] == 272_560_000
        assert len(notes) == 1 and notes[0].startswith("H3: ") and "세무 전문가" in notes[0], notes
        # 「통합특별시 시 지역의 집」으로 읽히지 않게 소재지를 주어로 쓰고, 시군구를 적지 않은 주소도 여기 든다고 밝힌다
        assert notes[0].startswith("H3: 소재지가 전남광주통합특별시의 시 지역이다(시군구를 적지 않은 주소도 시 지역으로 보았다). ")
        assert "통합특별시 시 지역의 집" not in notes[0]
        assert "제11조" not in notes[0] and "조제" not in notes[0]       # 규칙세트에 없는 조문 번호는 적지 않는다
    else:
        assert notes == []


@pytest.mark.parametrize("시군구", ["목포시", "여수시", "순천시", "나주시", "광양시"])
def test_merged_city_urban_house_note_only_after_the_merger(시군구):
    """다섯 시의 동 지역 집: 통합 뒤 양도일에는 확인사항이 있고 통합 전 양도일에는 없다. 판정과 주택 수는 같다."""
    for 시도 in ("전남광주통합특별시", "전라남도"):
        after = run(_k2_with_third(시도, 시군구, "중앙동"))["자산"][0]
        before = run(_k2_with_third(시도, 시군구, "중앙동", "2026-06-30"))["자산"][0]
        assert after["주택수_중과"] == before["주택수_중과"] == 2 and after["중과"] == before["중과"] == "중과2"
        assert len(_note(after, 특례_확인)) == 1 and _note(before, 특례_확인) == []


@pytest.mark.parametrize("시군구,읍면동", [("강진군", "강진읍"), ("담양군", "담양읍"), ("순천시", "승주읍"), ("나주시", "남평읍")])
def test_merged_city_county_or_town_house_has_no_note(시군구, 읍면동):
    """군과 시의 읍·면 집은 어느 쪽으로 읽어도 광역시가 아닌 지역이라 확인사항을 달지 않는다."""
    v = run(_k2_with_third("전남광주통합특별시", 시군구, 읍면동))["자산"][0]
    assert v["주택수_중과"] == 2 and _note(v, 특례_확인) == []


def test_merged_city_urban_house_over_the_price_limit_has_no_note():
    """기준시가가 3억원을 넘어 주택 수에서 빼지 않은 집에는 달지 않는다(특례에 기대지 않은 결과다)."""
    f = _k2_with_third("전남광주통합특별시", "순천시", "조례동")
    for h in f["세대"]["주택목록"]:
        if h["id"] == "H3":
            h["양도당시기준시가"] = 300_000_001
    v = run(f)["자산"][0]
    assert v["주택수_중과"] == 3 and _note(v, 특례_확인) == []


def test_other_local_low_price_house_has_no_merged_city_note():
    assert _note(one("K2"), 특례_확인) == []                              # 춘천 집


@pytest.mark.parametrize("시도", ["광주광역시", "광주", "전남광주통합특별시", "광주특별시"])
@pytest.mark.parametrize("양도일", [None, "2026-06-30"])
def test_merged_city_district_house_counts_like_a_metropolitan_house(시도, 양도일):
    """통합특별시의 자치구(옛 광주광역시) 집은 광역시 지역이라 기준시가가 낮아도 주택 수에 넣는다. 서초 집(K)과 같은 결과다."""
    f = _k2_with_third(시도, "서구", "치평동", 양도일)
    v = run(f)["자산"][0]
    assert v["중과"] == "중과3" and v["주택수_중과"] == 3 and not _note(v, "정하지 못해") and _note(v, 특례_확인) == []
    assert J.engine_values(f, f["자산"][0], F.prepare(f), RS, REG)["주택별"]["H3"]["지방소재"] is False
    if 양도일 is None:
        assert _engine_tax(f) == EXPECT_AMOUNTS["K"]["산출세액"] == 322_310_000


def test_sold_house_in_a_merged_city_urban_area_gets_the_note():
    """판 집이 통합특별시 시의 동 지역 지방 저가주택이라 중과하지 않은 경우에도 같은 확인사항을 단다(실제 고시에는 없는 조합이라 가짜 이력을 쓴다)."""
    class Designated(regions.Regions):
        def status(self, regime, addr, on, 지구해당=None):
            return {"지정": True, "공고": "가짜", "공고일": "2020-01-01", "효력발생일": "2020-01-01", "주석": []}

    reg = Designated({name: {"이벤트": []} for name in regions.REGIMES}, REG.admin)

    def sold(양도일):
        f = _d_with(lambda f: f["자산"][0].update(기준시가={"취득": {"주택": 100_000_000}, "양도": {"주택": 300_000_000}}))
        place = addr("전남광주통합특별시", "여수시", "학동")
        f["자산"][0]["소재지"] = place
        f["자산"][0]["양도"]["잔금일"] = 양도일
        f["자산"][0]["양도"]["계약일"] = f["자산"][0]["양도"]["계약금수령일"] = "2026-05-20"
        for h in f["세대"]["주택목록"]:
            if h.get("자산id") == f["자산"][0]["id"]:
                h["소재지"] = place
        return J.judge(f, F.prepare(f), RS, reg)["자산"][0]

    after, before = sold("2026-10-15"), sold("2026-06-30")
    for v in (after, before):
        assert v["중과"] is None and len(_note(v, "판 집이 지방 저가주택이거나")) == 1
    assert len(_note(after, 특례_확인)) == 1 and _note(before, 특례_확인) == []


def test_merged_city_house_without_district_is_counted_with_a_note():
    f = _k2_with_third("전남광주통합특별시", "", "조례동")
    v = run(f)["자산"][0]
    assert v["주택수_중과"] == 3 and len(_note(v, "H3: 광역시 해당 여부를 정하지 못해 주택 수에 넣었다")) == 1



# ---- 판 집을 자산id 로만 이은 주택 목록 ----
# 이은 집은 취득일·양도일처럼 소재지도 자산에서 읽는다(facts.houses_at). 시연 사례(마포구 아현동 양도, 고양시 일산동구 집 한 채 더)에서
# 판 집 소재지를 비우면 중과 주택 수를 셀 때 KeyError 가 났다. 이어지지 않은 집은 읽을 곳이 없어 H04 를 되묻는다

아현 = addr("서울특별시", "마포구", "아현동")
일산 = addr("경기도", "고양시 일산동구", "장항동")


def _linked_only(sold_house, 양도기준시가=800_000_000):
    a = asset("A", "주택", 아현, "2019-04-10", "2026-09-25", 1_100_000_000, 700_000_000,
              양도__계약일="2026-06-20", 양도__계약금수령일="2026-06-20",
              기준시가={"취득": {"주택": 500_000_000}, "양도": {"주택": 양도기준시가}})
    return facts([a], [sold_house, house("H2", 일산, "2015-06-01")])


def test_linked_house_without_address_reads_the_asset():
    bare = run(_linked_only({"id": "H1", "자산id": "A"}))
    assert bare["질문"] == [] and bare["다루지않음"] == [], bare
    assert bare == run(_linked_only(house("H1", 아현, "2019-04-10", 자산id="A")))
    v = bare["자산"][0]
    assert v["조정_양도일"]["지정"] and v["주택수_중과"] == 2 and v["중과"] == "중과2"


def test_linked_house_address_follows_the_asset():
    """이은 집에 다른 주소를 적어도 자산 소재지로 판정한다. 조정대상지역(자산 소재지)과 지방 저가 제외가 같은 주소를 본다.
    춘천으로 읽으면 판 집이 지방 저가주택(양도 기준시가 3억 이하)이 돼 중과가 빠진다."""
    stale = run(_linked_only(house("H1", 춘천, "2019-04-10", 자산id="A"), 양도기준시가=200_000_000))
    assert stale == run(_linked_only(house("H1", 아현, "2019-04-10", 자산id="A"), 양도기준시가=200_000_000))
    assert stale["자산"][0]["중과"] == "중과2"


def test_other_house_without_address_asks_h04():
    f = _linked_only({"id": "H1", "자산id": "A"})
    del f["세대"]["주택목록"][1]["소재지"]
    r = run(f)
    assert r["질문"] == [{"문항": "H04", "자산": "A", "내용": "주택 목록 H2 의 소재지가 필요합니다"}] and r["자산"] == []


def test_new_house_without_address_asks_h04():
    """일시적 2주택 처분기한(조정대상지역 2년)을 가를 때 신규 주택 소재지를 읽는다(G2 는 2년 기한이 걸리는 사례)."""
    f = copy.deepcopy(CASES["G2"])
    del f["세대"]["주택목록"][1]["소재지"]
    assert [(q["문항"], q["내용"]) for q in run(f)["질문"]] == [("H04", "주택 목록 H2 의 소재지가 필요합니다")]
