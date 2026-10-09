# -*- coding: utf-8 -*-
import copy

import pytest

from cases import CASES, asset, facts, house, 마포, 성동, 춘천
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
    assert set(J.EV_KEYS) <= set(empty)


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
