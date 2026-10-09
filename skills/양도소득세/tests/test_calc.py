# -*- coding: utf-8 -*-
import copy
from decimal import Decimal

import pytest

from cases import CASES, EXPECT, EXPECT_TOTAL
from yangdo import calc as C
from yangdo import codes, ruleset

RS = ruleset.load()
CD = codes.load()


def V(id, 종류, 취득일, 양도일, 보유, 거주=0, **kw):
    v = {"id": id, "종류": 종류, "취득일": 취득일, "양도일": 양도일, "보유년": 보유, "거주년": 거주,
         "거주근사": False, "주택수": None, "주택수_중과": None, "일세대": True, "일세대일주택": False,
         "일시적2주택": False, "처분기한": None, "비과세": False, "고가주택": False, "전액비과세": False,
         "미등기": False, "중과": None, "단기": None, "장특공": "없음", "조정_양도일": {"지정": False},
         "조정_취득일": {"지정": False}, "공고전계약_취득": False, "근거": [], "확인사항": [], "경고": []}
    v.update(kw)
    return v


VERDICTS = {
    "A": V("A", "주택", "2014-11-01", "2026-11-15", 12, 12, 일세대일주택=True, 비과세=True, 고가주택=True, 장특공="표2"),
    "B": V("B", "주택", "2019-11-10", "2026-11-20", 7, 장특공="표1"),
    "C": V("C", "주택", "2026-01-10", "2026-10-30", 0, 단기="1년미만"),
    "D": V("D", "주택", "2021-03-01", "2026-10-15", 5, 중과="중과2"),
    "E": V("E", "토지", "2010-05-01", "2026-11-01", 16, 미등기=True),
    "F": V("F", "토지", "2005-01-01", "2026-11-01", 21, 장특공="표1"),
    "G": V("G", "주택", "2019-03-01", "2026-11-30", 7, 5, 일세대일주택=True, 비과세=True, 전액비과세=True,
           조정_취득일={"지정": True}),
    "G2": V("G2", "주택", "2019-03-01", "2026-06-02", 7, 5, 중과="중과2"),
    "G3": V("G3", "주택", "2019-03-01", "2026-06-01", 7, 5, 일세대일주택=True, 비과세=True, 전액비과세=True,
            조정_취득일={"지정": True}),
    "H": V("H", "주택", "2021-03-01", "2026-03-15", 5, 장특공="표1"),
    "I": V("I", "주택", "2017-10-15", "2026-11-02", 9, 0, 일세대일주택=True, 비과세=True, 전액비과세=True,
           조정_취득일={"지정": True}, 공고전계약_취득=True),
    "I2": V("I2", "주택", "2017-10-15", "2026-11-02", 9, 0, 일세대일주택=True, 장특공="표1", 조정_취득일={"지정": True}),
    "J": V("J", "주택", "2025-08-01", "2026-10-01", 1, 중과="중과2", 단기="2년미만"),
    "K": V("K", "주택", "2021-07-01", "2026-07-01", 5, 중과="중과3"),
    "K2": V("K2", "주택", "2021-07-01", "2026-07-01", 5, 중과="중과2"),
}


def run(name, f=None, verdicts=None):
    return C.annual(f or CASES[name], verdicts or [VERDICTS[name]], RS, CD)


@pytest.mark.parametrize("name", sorted(EXPECT))
def test_case_amounts_and_codes(name):
    r = run(name)
    c = r["자산"][0]["계산"]
    want = EXPECT[name]
    assert (c["과세표준"], c["산출세액"], c["지방소득세"]) == (want["과세표준"], want["산출세액"], want["지방소득세"])
    assert (c["코드"]["세율구분"], c["코드"]["자산종류"]) == (want["세율구분"], want["자산종류"])
    assert r["합계"]["산출세액"] == want["산출세액"]


def test_luxury_split_and_codes():
    c = run("A")["자산"][0]["계산"]
    assert (c["양도차익"], c["비과세양도차익"], c["과세양도차익"]) == (700_000_000, 560_000_000, 140_000_000)
    assert (c["장특공률"], c["장특공"], c["기본공제"]) == ("0.80", 112_000_000, 2_500_000)
    assert c["코드"]["과세구분"] == "ZZ" and c["코드"]["보유기간"] == "10" and c["코드"]["거주기간"] == "Z1"
    assert c["적용세율"] == {"단일": None, "가산": "0", "지방단일": None, "지방가산": "0"}


def test_exempt_codes():
    c = run("G")["자산"][0]["계산"]
    assert c["코드"]["과세구분"] == "01" and c["취득가액"] is None and c["산출세액"] == 0
    assert c["코드"]["보유기간"] == "07" and c["코드"]["거주기간"] == "05"
    assert run("I")["자산"][0]["계산"]["코드"]["거주기간"] == "Z2"


def test_converted_acquisition_price():
    c = run("F")["자산"][0]["계산"]
    assert (c["취득가액"], c["필요경비"], c["양도차익"], c["취득가액방법"]) == (400_000_000, 6_000_000, 594_000_000, "환산가액")
    assert c["코드"]["취득가액종류"] == "04"


def test_converted_falls_back_to_actual_costs():
    f = copy.deepcopy(CASES["F"])
    f["자산"][0]["필요경비"]["자본적지출"] = [{"내용": "기타가치증가", "지급일": "2010-01-01", "금액": 500_000_000,
                                         "증빙종류": "세금계산서", "상대방": "합성"}]
    c = run("F", f)["자산"][0]["계산"]
    assert (c["취득가액"], c["필요경비"]) == (0, 500_000_000)


def test_comparable_sale_price_first():
    f = copy.deepcopy(CASES["F"])
    f["자산"][0]["매매사례가액"] = 450_000_000
    c = run("F", f)["자산"][0]["계산"]
    assert (c["취득가액"], c["필요경비"], c["취득가액방법"]) == (450_000_000, 6_000_000, "매매사례가액")


def test_expense_evidence_and_repairs_dropped():
    f = copy.deepcopy(CASES["B"])
    f["자산"][0]["필요경비"]["자본적지출"] += [
        {"내용": "샷시", "지급일": "2021-01-01", "금액": 3_000_000, "증빙종류": "간이영수증", "상대방": "합성"},
        {"내용": "일반수선", "지급일": "2021-01-01", "금액": 1_000_000, "증빙종류": "카드영수증", "상대방": "합성"}]
    c = run("B", f)["자산"][0]["계산"]
    assert c["필요경비"] == 10_000_000 and len(c["필요경비_제외"]) == 2


def test_joint_ownership():
    f = copy.deepcopy(CASES["B"])
    f["자산"][0]["지분"] = {"구분": "공동", "분자": 1, "분모": 2}
    c = run("B", f)["자산"][0]["계산"]
    assert (c["양도가액"], c["취득가액"], c["양도차익"]) == (350_000_000, 250_000_000, 90_000_000)


def test_loss_and_mixed_years_unsupported():
    f = copy.deepcopy(CASES["B"])
    f["자산"][0]["전체양도가액"] = 400_000_000
    with pytest.raises(C.Unsupported):
        run("B", f)
    with pytest.raises(C.Unsupported):
        C.annual(CASES["BC"], [VERDICTS["B"], dict(VERDICTS["C"], 양도일="2025-12-01")], RS, CD)


@pytest.mark.parametrize("pair,names", [("BC", ("B", "C")), ("BF", ("B", "F"))])
def test_two_assets_same_year(pair, names):
    r = C.annual(CASES[pair], [VERDICTS[n] for n in names], RS, CD)
    want = EXPECT_TOTAL[pair]
    got = r["합계"]
    assert (got["자산별세액"], got["합산비교세액"], got["산출세액"], got["지방소득세"]) == (
        want["자산별세액"], want["합산비교세액"], want["산출세액"], want["지방소득세"])
    first = sorted(names, key=lambda n: VERDICTS[n]["양도일"])[0]
    by = {row["id"]: row["계산"] for row in r["자산"]}
    assert by[first]["기본공제"] == 2_500_000 and sum(c["기본공제"] for c in by.values()) == 2_500_000
    assert any(x["key"] == "판정.합산비교" for x in r["근거"])


def test_rate_table_by_code():
    r = C.annual(CASES["BC"], [VERDICTS["B"], VERDICTS["C"]], RS, CD)
    assert sorted((x["세율구분"], x["산출세액"]) for x in r["세율별"]) == [("10", 42_152_000), ("46", 33_250_000)]


def test_progressive_boundaries():
    t = RS.value("기본세율", "2026-10-09")
    assert C.floor(C.progressive(14_000_000, t)) == 840_000
    assert C.floor(C.progressive(14_000_001, t)) == 840_000
    assert C.floor(C.progressive(0, t)) == 0


def test_short_term_winner():
    c = run("J")["자산"][0]["계산"]
    assert (c["세율그룹"], c["세율종류"]) == ("중과2", "2년미만")
    assert c["적용세율"] == {"단일": "0.60", "가산": "0.20", "지방단일": "0.060", "지방가산": "0.020"}
    v = dict(VERDICTS["J"], 단기="2년미만")
    big = C.rate_tax(v, 1_400_000_000, RS, C.to_date("2026-10-01"))
    assert big[1] == "누진"  # 과표 13.08억 초과면 누진+20% 가 크다(규격서 p34)


def test_ltd_table2_min_row():
    v = dict(VERDICTS["A"], 보유년=3, 거주년=2)
    assert C.ltd_rate(v, RS, C.to_date("2026-10-09")) == Decimal("0.20")


def test_new_build_surcharge_note():
    f = copy.deepcopy(CASES["F"])
    f["자산"][0]["신축증축"] = {"사용승인일": "2023-01-01", "증축면적": 0}
    assert any("114조의2" in m for m in run("F", f)["확인사항"])


def test_local_is_tenth():
    for name in EXPECT:
        c = run(name)["자산"][0]["계산"]
        assert abs(c["지방소득세"] * 10 - c["산출세액"]) <= 10, name
