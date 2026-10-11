# -*- coding: utf-8 -*-
"""계획 2b G1a: 예정신고를 하지 않은 확정신고의 가산세(예정신고 무신고가산세, 납부지연가산세).

기대값은 국세청 「2023년 유형별 확정신고 사례」(확정신고 작성 사례 09)의 계산 방식과 규칙세트의 율·세율로 손계산했다.
손계산 과정은 references/정답지.md 「가산세 대조」에 있다. penalty 나 엔진의 출력에서 옮긴 값이 아니다.
  원문 재현   원문이 적은 건별 세액과 일수를 넣으면 원문 가산세가 원 단위까지 나온다(사례 2·4·5·8)
  건별 세액   2022년 귀속 세율표를 넣은 규칙세트로 원문의 건별 예정신고 세액이 나온다(사례 2·5·8)
  현행 사례   합성 사례를 엔진에 돌린 결과로 건·열·합계를 단언한다
"""
import copy
import json
import os
import shutil
from datetime import date
from decimal import Decimal

import pytest

from yangdo import RULES_DIR, dates, engine, keys, penalty
from yangdo import ruleset as R
from cases import CASES, asset, facts, 평택

TODAY = "2026-10-11"
KEYS4 = ["가산세.무신고.율", "가산세.무신고.확정신고감면율", "가산세.납부지연.일이자율", "가산세.납부지연.납부일산입"]


@pytest.fixture(scope="module")
def rs():
    return R.load()


def _calc(f):
    r = engine.calculate(copy.deepcopy(f), today=TODAY)
    assert r["상태"] == "완료", r["질문"] or r["다루지않음"] or r["검산"]
    return r


def _lines(out):
    return [(c["자산"], c["예정신고세액"], c["납부기한"], c["일수"], c["무신고"], c["납부지연"]) for c in out["건"]]


# ---------------------------------------------------------------- 규칙

def test_rule_values(rs):
    for on in ("2025-01-01", "2026-06-30", "2026-07-01", "2027-05-31", "2027-12-31"):
        assert rs.value("가산세.무신고.율", on) == Decimal("0.20")
        assert rs.value("가산세.무신고.확정신고감면율", on) == Decimal("0.50")
        assert rs.value("가산세.납부지연.일이자율", on) == Decimal("0.00022")       # 1일 10만분의 22
    assert set(KEYS4) <= set(keys.VALUE_KEYS)


def test_day_count_rule_changes_on_2026_07_01(rs):
    """2026-06-30 납부까지는 납부일까지, 2026-07-01 납부부터는 납부일의 전날까지 센다(기준일은 납부일)."""
    assert rs.value("가산세.납부지연.납부일산입", "2026-06-30") == 1
    assert rs.value("가산세.납부지연.납부일산입", "2026-07-01") == 0
    assert rs.entry("가산세.납부지연.납부일산입", "2027-05-31")["기준일"] == "납부일"
    old = rs.cite("가산세.납부지연.납부일산입", "2026-06-30")
    new = rs.cite("가산세.납부지연.납부일산입", "2026-07-01")
    assert [c["조항"] for c in old] == ["제47조의4①1호"]
    assert "납부일까지의 기간" in old[0]["발췌"][0]
    assert [c["조항"] for c in new] == ["제47조의4①1호", "부칙(제21212호)"]
    assert "전날까지의 기간" in new[0]["발췌"][0] and "2026년 7월 1일부터 시행" in new[1]["발췌"][0]


def test_rule_citations(rs):
    on = "2027-05-31"
    무 = rs.cite("가산세.무신고.율", on)
    assert [(c["법령"], c["조항"]) for c in 무] == [("국세기본법", "제47조의2①2호"), ("국세기본법", "제47조의2⑤")]
    assert "제1호 외의 경우: 100분의 20" in 무[0]["발췌"]
    감 = rs.cite("가산세.무신고.확정신고감면율", on)
    assert [(c["법령"], c["조항"]) for c in 감] == [("국세기본법", "제48조②3호라목")]
    assert any("100분의 50에 상당하는 금액" in x for x in 감[0]["발췌"])
    assert any("제45조의3에 따른 기한 후 신고" in x for x in 감[0]["발췌"])
    assert any("과세표준신고를 한 경우" in x for x in rs.cite("가산세.무신고.확정신고감면율", "2025-12-31")[0]["발췌"])
    이 = rs.cite("가산세.납부지연.일이자율", on)
    assert [c["법령"] for c in 이] == ["국세기본법", "국세기본법", "국세기본법 시행령"]
    assert any("1일 10만분의 22의 율" in x for x in 이[2]["발췌"])
    assert [c["조항"] for c in 이] == ["제47조의4①1호", "제47조의4⑤", "제27조의4①"]      # 조항 글자에 설명을 섞지 않는다
    for k in KEYS4:
        assert all(c["URL"].startswith("https://www.law.go.kr/법령/") and c["시행일"] for c in rs.cite(k, on)), k


# ---------------------------------------------------------------- 원문 재현(확정신고 작성 사례 09)

# 사례: (건별 예정신고 세액, 건별 일수, 무신고 합계, 건별 납부지연). 세액·일수·결과 모두 원문 상세내역에 적힌 값이다.
# 원문의 율(무신고 20% × 50%, 납부지연 1일 2.2/10,000)은 지금 규칙세트 값과 같다
NTS = {
    "09-2": ([12_045_000, 196_272_000], [426, 304], 20_831_700, [1_128_850, 13_126_670]),
    "09-4": ([5_010_000], [304], 501_000, [335_060]),
    "09-5": ([1_590_000, 4_999_500], [426, 304], 658_950, [149_010, 334_360]),
    "09-8": ([7_875_556, 603_136], [182, 151], 847_869, [315_330, 20_030]),
}


@pytest.mark.parametrize("name", sorted(NTS))
def test_amounts_reproduce_nts_cases_to_the_won(rs, name):
    taxes, days, nonfiling, late = NTS[name]
    on = "2027-05-31"
    total, per_case, got_late = penalty.amounts(taxes, days, rs.value("가산세.무신고.율", on),
                                                rs.value("가산세.무신고.확정신고감면율", on),
                                                rs.value("가산세.납부지연.일이자율", on))
    assert total == nonfiling
    assert got_late == late
    assert sum(per_case) == total


def test_amounts_nonfiling_split_matches_nts_form_columns(rs):
    """사례 8 서식 ⑮ 무(과소)신고 줄: 합계 847,869, 열 787,556 · 60,313. 건마다 원 미만을 버리면 787,555 + 60,313 = 847,868 이라
    1원이 모자란다. 합계를 먼저 구하고 모자란 1원은 세액이 큰 건에 둔다."""
    total, per_case, _ = penalty.amounts([7_875_556, 603_136], [182, 151], Decimal("0.20"), Decimal("0.50"), Decimal("0.00022"))
    assert (total, per_case) == (847_869, [787_556, 60_313])


def test_amounts_skip_cases_not_yet_due():
    """일수가 None 인 건은 납부기한이 지나지 않은 건이다. 무신고도 납부지연도 0 이고 합계의 세액에도 들지 않는다."""
    total, per_case, late = penalty.amounts([1_000_005, 2_000_000], [10, None], Decimal("0.20"), Decimal("0.50"), Decimal("0.00022"))
    assert (total, per_case, late) == (100_000, [100_000, 0], [2_200, 0])     # 1,000,005 × 10 × 0.00022 = 2,200.011


class Rules2022:
    """2022년 귀속 세율표(소득세법 제55조① 2022-12-31 개정 전)를 넣은 규칙세트. 원문의 건별 세액을 재현하는 데만 쓴다.
    나머지 값은 지금 규칙세트의 2025-01-01 값이다(단기 50%, 다주택 중과 20%p, 예정신고 기한 2개월은 2022년에도 같았다)."""
    TABLE = [[0, 0, Decimal("0.06")], [12_000_000, 720_000, Decimal("0.15")], [46_000_000, 5_820_000, Decimal("0.24")],
             [88_000_000, 15_900_000, Decimal("0.35")], [150_000_000, 37_600_000, Decimal("0.38")],
             [300_000_000, 94_600_000, Decimal("0.40")], [500_000_000, 174_600_000, Decimal("0.42")],
             [1_000_000_000, 384_600_000, Decimal("0.45")]]

    def __init__(self, real):
        self.real = real

    def value(self, key, on):
        return self.TABLE if key == "기본세율" else self.real.value(key, "2025-01-01")


def _row(aid, 양도일, 과세표준, 열, 묶음="기본", 단기=None, 중과=None, 종류="토지"):
    """엔진 결과의 자산 한 줄에서 penalty 가 읽는 것만."""
    return {"id": aid,
            "판정": {"id": aid, "양도일": 양도일, "전액비과세": False, "미등기": False, "단기": 단기, "중과": 중과, "종류": 종류},
            "계산": {"과세표준": 과세표준, "합산묶음": 묶음, "코드": {"국내외분": "1", "세율구분": 열}}}


def _facts_for(rows):
    return {"연간": {"기신고": None}, "자산": [{"id": r["id"], "토지거래허가대상": "아니오"} for r in rows]}


def test_cases_reproduce_nts_case_8_per_case_tax(rs):
    """사례 8: 같은 날 양도한 누진세율 토지 둘은 과세표준을 합산하고(54,564,817 → 7,875,556), 다음 달 양도한 단기 토지는 따로다(603,136)."""
    rows = [_row("A", "2022-09-13", 24_844_375, "10"), _row("B", "2022-09-13", 29_720_442, "10"),
            _row("C", "2022-10-13", 1_206_272, "20", 묶음="일반·일반·1년미만", 단기="1년미만")]
    got, _ = penalty.cases(rows, _facts_for(rows), Rules2022(rs))
    assert [(c["자산"], c["예정신고세액"], c["기한말일"], c["납부기한"]) for c in got] == [
        (["A", "B"], 7_875_556, date(2022, 11, 30), date(2022, 11, 30)),
        (["C"], 603_136, date(2022, 12, 31), date(2023, 1, 2))]             # 2022-12-31 은 토요일
    assert [c["열"] for c in got] == [{"1-10": 7_875_556}, {"1-20": 603_136}]


def test_cases_reproduce_nts_case_5_no_merge_across_months(rs):
    """사례 5: 누진세율 주택을 다른 달에 두 번 양도하고 모두 무신고. 건마다 따로 세율을 적용한다(합산하면 8,779,200).
    기본공제는 먼저 양도한 자산에서만 뺀다: (20,300,000 − 2,500,000) → 1,590,000, 40,530,000 → 4,999,500."""
    rows = [_row("A", "2022-01-15", 17_800_000, "10", 종류="주택"), _row("B", "2022-05-29", 40_530_000, "10", 종류="주택")]
    got, _ = penalty.cases(rows, _facts_for(rows), Rules2022(rs))
    assert [(c["자산"], c["예정신고세액"], c["기한말일"]) for c in got] == [
        (["A"], 1_590_000, date(2022, 3, 31)), (["B"], 4_999_500, date(2022, 7, 31))]


def test_cases_reproduce_nts_case_2_surcharged_and_progressive(rs):
    """사례 2: 1회 조정지역 2주택 중과(누진 + 20%p) 12,045,000, 2회 일반세율 196,272,000. 확정신고 산출세액은 비교과세로
    212,022,000 이지만 가산세는 건별 세액의 합 208,317,000 에 붙는다."""
    rows = [_row("A", "2022-01-15", 37_500_000, "47", 묶음="중과2", 중과="중과2", 종류="주택"),
            _row("B", "2022-05-29", 551_600_000, "10", 종류="주택")]
    got, _ = penalty.cases(rows, _facts_for(rows), Rules2022(rs))
    assert [c["예정신고세액"] for c in got] == [12_045_000, 196_272_000]


def test_days_with_old_and_new_counting(rs):
    """원문(2023-05-31 납부, 납부일까지 세던 때): 2022-11-30 기한 182일, 2022-12-31 기한 151일. 지금은 전날까지라 하루 적다."""
    assert penalty.days(date(2022, 11, 30), date(2023, 5, 31), 1) == 182
    assert penalty.days(date(2022, 12, 31), date(2023, 5, 31), 1) == 151
    assert penalty.days(date(2026, 11, 30), date(2027, 5, 31), 0) == 181
    assert penalty.days(date(2026, 12, 31), date(2027, 5, 31), 0) == 150
    assert penalty.days(date(2027, 2, 1), date(2027, 2, 2), 0) == 0             # 기한 다음 날 납부: 전날까지 0일
    assert penalty.days(date(2027, 2, 1), date(2027, 2, 1), 0) is None          # 기한 안
    assert penalty.days(date(2027, 2, 1), date(2027, 1, 20), 0) is None


# ---------------------------------------------------------------- 현행 사례(엔진 결과 → 가산세)

def test_bf_one_case_for_two_progressive_assets_sold_in_the_same_month():
    """BF: 토지 F(2026-11-01)와 주택 B(2026-11-20)를 같은 달에 양도했다. 예정신고 기한이 같아 한 건이다.
    예정신고세액 = (413,300,000 + 163,400,000) 에 기본세율 = 174,060,000 + 76,700,000 × 42% = 206,274,000
    기한 말일 2027-01-31 은 일요일이라 납부기한 2027-02-01, 일수 = 2027-02-02 ~ 2027-05-19 = 27 + 31 + 30 + 19 = 107
    무신고 = 206,274,000 × 20% = 41,254,800 (지금 문언에서는 감면을 적용하지 않는다)
    납부지연 = 206,274,000 × 107 × 22/100,000 = 4,855,689.96 → 4,855,680"""
    out = penalty.final_return(_calc(CASES["BF"]), CASES["BF"], "2027-05-20")
    assert (out["무신고"], out["납부지연"], out["계"]) == (41_254_800, 4_855_680, 46_110_480)
    assert _lines(out) == [(["F", "B"], 206_274_000, "2027-02-01", 107, 41_254_800, 4_855_680)]
    assert out["건"][0]["기한말일"] == "2027-01-31"
    assert out["열"] == {"1-10": {"무신고": 41_254_800, "납부지연": 4_855_680}}
    assert {"무신고", "납부지연", "계", "건", "열", "확인사항"} <= set(out)


def test_bc_two_cases_in_two_rate_columns():
    """BC: 단기 주택 C(2026-10-30, 70%)와 누진세율 주택 B(2026-11-20). 기본공제는 먼저 양도한 C 에서 뺀다.
    C 건: 47,500,000 × 70% = 33,250,000, 기한 2026-12-31(목), 일수 2027-01-01 ~ 2027-05-19 = 139
    B 건: 163,400,000 → 37,060,000 + 13,400,000 × 38% = 42,152,000, 기한 2027-02-01, 일수 107
    무신고 = 75,402,000 × 20% = 15,080,400 (C 6,650,000, B 8,430,400)
    납부지연 = 33,250,000 × 139 × 22/100,000 = 1,016,785 → 1,016,780, 42,152,000 × 107 × 22/100,000 = 992,258.08 → 992,250"""
    out = penalty.final_return(_calc(CASES["BC"]), CASES["BC"], "2027-05-20")
    assert _lines(out) == [(["C"], 33_250_000, "2026-12-31", 139, 6_650_000, 1_016_780),
                           (["B"], 42_152_000, "2027-02-01", 107, 8_430_400, 992_250)]
    assert out["열"] == {"1-10": {"무신고": 8_430_400, "납부지연": 992_250},
                        "1-46": {"무신고": 6_650_000, "납부지연": 1_016_780}}
    assert (out["무신고"], out["납부지연"], out["계"]) == (15_080_400, 2_009_030, 17_089_430)


def test_every_case_past_due_gets_its_own_line_with_the_values_of_the_guide_table():
    """국세 가산세도 지방소득세처럼 건마다 한 줄이다(예정신고 세액, 납부기한, 일수, 금액). 기한을 옮긴 건의 까닭 문장은 그 건에만 붙는다."""
    out = penalty.final_return(_calc(CASES["BC"]), CASES["BC"], "2027-05-20")
    lines = [x for x in out["확인사항"] if "일(납부기한 다음 날부터 납부일 " in x]
    assert lines == [
        "자산 C: 예정신고 세액 33,250,000원, 납부기한 2026-12-31, 일수 139일(납부기한 다음 날부터 납부일 2027-05-20 전날까지), 무신고가산세 6,650,000원, 납부지연가산세 1,016,780원이다",
        "자산 B: 예정신고 세액 42,152,000원, 납부기한 2027-02-01, 일수 107일(납부기한 다음 날부터 납부일 2027-05-20 전날까지), 무신고가산세 8,430,400원, 납부지연가산세 992,250원이다"]
    for c in out["건"]:
        assert any(("예정신고 세액 %s원" % format(c["예정신고세액"], ",")) in x and ("%d일" % c["일수"]) in x for x in lines)
    moved = [x for x in out["확인사항"] if "건너뛴 날은" in x and "예정신고 기한 말일은" in x]
    assert len(moved) == 1 and moved[0].startswith("자산 B:")          # 기한을 옮긴 B 건에만 붙는다


def test_per_case_line_and_guide_table_name_the_day_the_count_really_ends():
    """일수의 끝 날은 규칙 가산세.납부지연.납부일산입 이 정한다. 2026-07-01 부터의 납부는 납부일 전날까지, 그 전은 납부일까지다.
    건별 줄과 안내서 「가산세 계산」 표의 문장이 센 대로 말하고, 지방소득세는 지방 규칙대로 납부일까지다."""
    late = penalty.final_return(_calc(CASES["BF"]), CASES["BF"], "2027-05-20")
    assert late["납부일산입"] is False and late["지방"]["납부일산입"] is True
    line = [x for x in late["확인사항"] if "일(납부기한 다음 날부터 납부일 " in x]
    assert len(line) == 1 and "일수 107일(납부기한 다음 날부터 납부일 2027-05-20 전날까지)" in line[0]
    assert any("납부기한 다음 날부터 납부일 전날까지 일수를 셌다" in x for x in late["확인사항"])
    f = copy.deepcopy(CASES["F"])
    f["자산"][0]["양도"]["잔금일"] = "2025-08-01"
    old = penalty.final_return(_calc(f), f, "2026-05-20")
    assert old["납부일산입"] is True
    line = [x for x in old["확인사항"] if "일(납부기한 다음 날부터 납부일 " in x]
    assert len(line) == 1 and "일수 201일(납부기한 다음 날부터 납부일 2026-05-20까지)" in line[0] and "전날" not in line[0]


def _two_lots():
    """누진세율 토지 둘을 다른 달에 양도(원문 사례 5 와 같은 꼴). L 은 2015-05-01 취득 1억원, 2026-08-10 양도 2억원."""
    lot = asset("L", "토지", 평택, "2015-05-01", "2026-08-10", 200_000_000, 100_000_000, 토지사용현황="사업용")
    return facts([lot, CASES["F"]["자산"][0]])


def test_progressive_assets_sold_in_different_months_are_not_merged():
    """L: 양도차익 1억원, 보유 11년 장기보유특별공제 22%, 양도소득금액 78,000,000, 기본공제 뒤 75,500,000
       → 6,240,000 + 25,500,000 × 24% = 12,360,000. 기한 말일 2026-10-31(토) → 2026-11-02, 일수 2026-11-03 ~ 2027-05-19 = 198
    F: 양도소득금액 415,800,000(기본공제는 L 이 썼다) → 94,060,000 + 115,800,000 × 40% = 140,380,000, 일수 107
    연간 산출세액은 합산한 170,580,000 이지만 가산세는 건별 세액의 합 152,740,000 에 붙는다
    무신고 = 152,740,000 × 20% = 30,548,000 (12,360,000 × 20% = 2,472,000, 140,380,000 × 20% = 28,076,000)
    납부지연 = 12,360,000 × 198 × 22/100,000 = 538,401.6 → 538,400, 140,380,000 × 107 × 22/100,000 = 3,304,545.2 → 3,304,540"""
    f = _two_lots()
    r = _calc(f)
    assert r["계산"]["합계"]["산출세액"] == 170_580_000
    out = penalty.final_return(r, f, "2027-05-20")
    assert _lines(out) == [(["L"], 12_360_000, "2026-11-02", 198, 2_472_000, 538_400),
                           (["F"], 140_380_000, "2027-02-01", 107, 28_076_000, 3_304_540)]
    assert (out["무신고"], out["납부지연"], out["계"]) == (30_548_000, 3_842_940, 34_390_940)
    assert out["열"] == {"1-10": {"무신고": 30_548_000, "납부지연": 3_842_940}}
    assert any("2026-10-31" in m and "토요일" in m and "2026-11-02" in m for m in out["확인사항"])


def test_case_paid_on_or_before_due_date_has_no_penalty():
    """납부일이 납부기한 이전인 건은 예정신고 기한 안이라 가산세가 없다. 기한 다음 날 납부는 무신고만 붙는다(전날까지 0일)."""
    r = _calc(CASES["BF"])
    for paid in ("2027-01-31", "2027-02-01"):                    # 말일(일요일)과 옮긴 기한(월요일)
        out = penalty.final_return(r, CASES["BF"], paid)
        assert (out["무신고"], out["납부지연"], out["계"]) == (0, 0, 0)
        assert _lines(out) == [(["F", "B"], 206_274_000, "2027-02-01", 0, 0, 0)]
        assert out["열"] == {"1-10": {"무신고": 0, "납부지연": 0}}
        assert any("기한 안" in m for m in out["확인사항"])
    out = penalty.final_return(r, CASES["BF"], "2027-02-02")
    assert (out["무신고"], out["납부지연"]) == (41_254_800, 0) and out["건"][0]["일수"] == 0


def test_only_cases_past_due_are_penalized():
    """L 건(기한 2026-11-02)은 지났고 F 건(기한 2027-02-01)은 지나지 않은 납부일: L 건에만 붙는다.
    일수 2026-11-03 ~ 2027-01-14 = 28 + 31 + 14 = 73, 납부지연 12,360,000 × 73 × 22/100,000 = 198,501.6 → 198,500"""
    f = _two_lots()
    out = penalty.final_return(_calc(f), f, "2027-01-15")
    assert _lines(out) == [(["L"], 12_360_000, "2026-11-02", 73, 2_472_000, 198_500),
                           (["F"], 140_380_000, "2027-02-01", 0, 0, 0)]
    assert (out["무신고"], out["납부지연"], out["계"]) == (2_472_000, 198_500, 2_670_500)


def test_fully_exempt_assets_have_no_case():
    out = penalty.final_return(_calc(CASES["G"]), CASES["G"], "2027-05-20")
    assert (out["무신고"], out["납부지연"], out["계"], out["건"]) == (0, 0, 0, [])


def test_no_taxable_asset_returns_zero_without_reading_penalty_rules(monkeypatch):
    """과세 자산이 없으면 건이 없어 가산세도 없다. 율을 읽지 않으므로 납부일이 가산세 규칙의 첫 구간(2025-01-01)보다
    앞서도 오류 없이 0 을 돌려준다."""
    r = _calc(CASES["G"])
    real, seen = R.Ruleset.value, []

    def value(self, key, on):
        seen.append(key)
        return real(self, key, on)
    monkeypatch.setattr(R.Ruleset, "value", value)
    for paid in ("2027-05-20", "2024-12-31"):
        out = penalty.final_return(r, CASES["G"], paid)
        assert (out["무신고"], out["납부지연"], out["계"], out["건"], out["확인사항"]) == (0, 0, 0, [], [])
        assert (out["지방"]["무신고"], out["지방"]["납부지연"], out["지방"]["계"], out["지방"]["건"]) == (0, 0, 0, [])
        assert out["율"] is None and out["감면율"] is None and out["일이자율"] is None and out["지방"]["율"] is None
        assert out["감면적용"] is False and out["양도일별"] is None and out["열"] == {}
    assert not [k for k in seen if "가산세" in k]
    with pytest.raises(R.RuleError):                               # 과세 자산이 있으면 그 날짜의 규칙이 있어야 한다
        penalty.final_return(_calc(CASES["F"]), CASES["F"], "2024-12-31")


def test_same_month_note_lists_the_sale_dates_even_when_the_alternative_is_undetermined(rs):
    """같은 달 양도 건을 양도일마다 따로 볼 때의 세액을 정하지 못해도, 문장은 자산마다 실제 양도일을 적는다.
    A(2주택 중과, 과세표준 37,500,000)와 B(일반, 551,600,000)를 2026-05-15 에, C(2주택 중과, 500,000,000)를 2026-05-20 에 양도.
      건 전체: 중과 묶음 537,500,000 → 174,060,000 + 37,500,000 × 42% + 537,500,000 × 20% = 297,310,000
               일반 551,600,000 → 174,060,000 + 51,600,000 × 42% = 195,732,000, 합 493,042,000
               합산 비교세액 1,089,100,000 → 384,060,000 + 89,100,000 × 45% = 424,155,000 < 493,042,000 이라 건 세액은 정해진다
      2026-05-15 만: 세율별 합 207,597,000 < 합산 비교세액 211,482,000 이라 그 날의 세액은 정하지 못한다"""
    rows = [_row("A", "2026-05-15", 37_500_000, "47", 묶음="중과2", 중과="중과2", 종류="주택"),
            _row("B", "2026-05-15", 551_600_000, "10", 종류="주택"),
            _row("C", "2026-05-20", 500_000_000, "47", 묶음="중과2", 중과="중과2", 종류="주택")]
    got, _ = penalty.cases(rows, _facts_for(rows), rs)
    assert [(c["자산"], c["예정신고세액"], c["양도일별"]) for c in got] == [(["A", "B", "C"], 493_042_000, None)]
    assert got[0]["자산양도일"] == {"A": "2026-05-15", "B": "2026-05-15", "C": "2026-05-20"}
    result = {"상태": "완료", "계산": {"자산": rows, "세율별": [{"국내외분": "1", "세율구분": "10"}, {"국내외분": "1", "세율구분": "47"}]}}
    out = penalty.final_return(result, _facts_for(rows), "2027-05-20")
    hit = [m for m in out["확인사항"] if "같은 달" in m]
    assert len(hit) == 1 and out["양도일별"] is None
    assert hit[0].startswith("자산 A, B, C: 같은 달에 양도해(A 2026-05-15, B 2026-05-15, C 2026-05-20) 예정신고 기한이 같다.")
    assert hit[0].endswith("양도일마다 따로 신고하는 것으로 볼 때의 세액은 정하지 못했다")
    assert "양도일이 둘 이상" not in hit[0] and "493,042,000원" in hit[0]


def test_bf_same_month_note_lists_both_sale_dates():
    out = penalty.final_return(_calc(CASES["BF"]), CASES["BF"], "2027-05-20")
    hit = [m for m in out["확인사항"] if "같은 달" in m]
    assert len(hit) == 1 and hit[0].startswith("자산 F, B: 같은 달에 양도해(F 2026-11-01, B 2026-11-20) 예정신고 기한이 같다.")


def test_relief_note_follows_the_wording_of_the_interval(tmp_path):
    """감면 안내 문장은 신고일이 속한 규칙 이력 구간의 문구를 따른다. 2025-12-31 까지는 「확정신고기한까지 과세표준신고를 한
    경우」라 「기한 후 신고로 내면」이라고 적지 않는다. 구간은 발췌 글자가 아니라 이력 구간의 시작 날짜로 가른다."""
    f = copy.deepcopy(CASES["F"])
    f["자산"][0]["양도"]["잔금일"] = "2025-08-01"
    old = penalty.final_return(_calc(f), f, "2025-12-20")["감면안내"]
    assert "확정신고기한까지 신고하면 무신고가산세의 50% 를 감면하는 규정이 있다(국세기본법 제48조)" in old
    assert "기한 후 신고로 내면" not in old and "이 규정의 문구는" not in old
    assert "확정신고서를 만들므로" in old and "적용하지 않았다" in old and "13,938,000원" in old
    new = penalty.final_return(_calc(CASES["BF"]), CASES["BF"], "2027-05-20")["감면안내"]
    assert "확정신고기한까지 예정신고분을 기한 후 신고로 내면 무신고가산세의 50% 를 감면하는 규정이 있다(국세기본법 제48조)" in new
    assert "이 규정의 문구는 2026-01-01 부터 「기한 후 신고를 한 경우」다. " in new

    def refetched(data):                                           # 발췌를 다시 받아 글자가 조금 달라진 규칙세트
        for e in data["규칙"]["가산세.무신고.확정신고감면율"]["이력"]:
            for g in e["근거"]:
                g["발췌"] = [x.replace("기한 후 신고를 한 경우", "기한후신고를 한 경우") for x in g["발췌"]]
    d = _rules_copy(tmp_path, refetched)
    again = penalty.final_return(_calc(CASES["BF"]), CASES["BF"], "2027-05-20", rules_dir=d)["감면안내"]
    assert again == new                                            # 문장이 조용히 빠지지 않는다
    old_again = penalty.final_return(_calc(f), f, "2025-12-20", rules_dir=d)["감면안내"]
    assert old_again == old


def test_relief_wording_constant_matches_the_ruleset_excerpts(rs):
    """문장에 적는 바뀐 문구가 규칙세트 발췌와 어긋나면 알 수 있게 한다. 뒤 구간의 발췌에만 그 문구가 있다."""
    history = rs.data["규칙"]["가산세.무신고.확정신고감면율"]["이력"]
    assert [e["시작"] for e in history] == ["2025-01-01", "2026-01-01"]
    has = [any(penalty.RELIEF_NEW_WORDING in x for g in e["근거"] for x in g["발췌"]) for e in history]
    assert has == [False, True]


def test_amounts_in_notes_use_thousands_separators():
    """확인사항 문장의 금액은 「20,627,400원」처럼 천 단위 쉼표로 적는다. 결과의 숫자 값은 정수 그대로다.
    BF 손계산: 무신고 41,254,800, 납부지연 4,855,680, 세액 206,274,000, 감면이 적용되면 20,627,400. 지방 4,125,480 · 226,901"""
    out = penalty.final_return(_calc(CASES["BF"]), CASES["BF"], "2027-05-20")
    text = "\n".join(out["확인사항"])
    for amount in ("41,254,800원", "4,855,680원", "206,274,000원", "20,627,400원", "181,532,000원", "36,306,400원", "4,273,250원",
                   "4,125,480원", "226,901원", "2,062,740원"):
        assert amount in text, amount
    import re
    assert re.findall(r"(?<![\d,])\d{4,}원", text) == []          # 쉼표 없이 적은 네 자리 이상 금액이 없다
    assert out["무신고"] == 41_254_800 and isinstance(out["무신고"], int) and out["지방"]["납부지연"] == 226_901


def test_undetermined_case_message_uses_thousands_separators(rs):
    """정하지 못한 건의 문장도 금액에 쉼표를 넣는다. 건을 만들 때 지방소득세 세액을 먼저 구하므로 지방 쪽 문장이 나온다.
    지방 합산 비교세액 17,406,000 + 89,100,000 × 4.2% = 21,148,200, 세율별 합 1,186,500 + 19,573,200 = 20,759,700"""
    rows = [_row("A", "2026-05-15", 37_500_000, "47", 묶음="중과2", 중과="중과2", 종류="주택"),
            _row("B", "2026-05-29", 551_600_000, "10", 종류="주택")]
    with pytest.raises(penalty.Unsupported) as e:
        penalty.cases(rows, _facts_for(rows), rs)
    assert "지방소득세 합산 비교세액 21,148,200원이 세율별 세액의 합 20,759,700원보다 크다" in str(e.value)


def test_notes_say_what_was_assumed():
    out = penalty.final_return(_calc(CASES["BF"]), CASES["BF"], "2027-05-20")
    notes = out["확인사항"]
    assert any("부정행위" in m and "다루지 않는다" in m for m in notes)
    assert any("납부일" in m and "2027-05-20" in m for m in notes)
    assert any("같은 달" in m and "F" in m and "B" in m for m in notes)
    # 2027년은 공휴일 표에 있다. 건너뛴 날을 그대로 적고 「토요일·일요일만 옮겼다」는 문장은 내지 않는다
    assert any("건너뛴 날은 2027-01-31(일요일)" in m and "납부기한은 2027-02-01" in m for m in notes)
    assert not any("토요일·일요일만" in m or "다음 월요일" in m for m in notes)
    assert any("10원 미만" in m for m in notes)
    assert all(chr(0x2014) not in m and not m.rstrip().endswith("?") for m in notes)
    assert [(c["법령"], c["조항"]) for c in out["근거"]][:2] == [("국세기본법", "제47조의2①2호"), ("국세기본법", "제47조의2⑤")]


def test_rates_come_from_the_ruleset(tmp_path):
    """율을 코드에 적지 않았다. 규칙세트의 율을 바꾼 사본으로 계산하면 가산세가 따라 바뀐다."""
    d = str(tmp_path / "rules")
    os.makedirs(os.path.join(d, "고시"))
    for name in R.EDITION_FILES:
        shutil.copy(os.path.join(RULES_DIR, name), os.path.join(d, name))
    path = os.path.join(d, "ruleset.json")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    for key, value in (("가산세.무신고.율", "0.40"), ("가산세.무신고.확정신고감면율", "0.25"), ("가산세.납부지연.일이자율", "0.00044")):
        for e in data["규칙"][key]["이력"]:
            e["값"] = value
    for e in data["규칙"]["가산세.납부지연.납부일산입"]["이력"]:
        e["값"] = 1
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    R.write_edition(d, data["확인일"])
    out = penalty.final_return(_calc(CASES["BF"]), CASES["BF"], "2027-05-20", rules_dir=d)
    # 무신고 206,274,000 × 40% = 82,509,600(감면을 적용하면 × 75% = 61,882,200).
    # 납부지연 206,274,000 × 108 × 44/100,000 = 9,802,140.48 → 9,802,140
    assert (out["무신고"], out["무신고_감면적용"], out["납부지연"], out["건"][0]["일수"]) == (82_509_600, 61_882_200, 9_802_140, 108)


# ---------------------------------------------------------------- 감면과 대안 금액
# 국세기본법 제48조②3호라목은 2026-01-01 부터 「확정신고기한까지 제45조의3에 따른 기한 후 신고를 한 경우」에 감면한다.
# 이 스킬이 만드는 것은 확정신고서라 감면을 적용하지 않고, 감면을 적용한 금액을 대안으로 싣는다.
# 그 전 문언(「과세표준신고를 한 경우」) 구간의 신고도 같다. 감면 판정은 조문 발췌의 글자를 보지 않는다.

def test_no_relief_under_the_current_wording_and_relieved_amount_as_alternative():
    """BF: 206,274,000 × 20% = 41,254,800. 감면이 적용되면 × 50% = 20,627,400."""
    out = penalty.final_return(_calc(CASES["BF"]), CASES["BF"], "2027-05-20")
    assert out["감면적용"] is False
    assert (out["무신고"], out["무신고_감면없음"], out["무신고_감면적용"]) == (41_254_800, 41_254_800, 20_627_400)
    assert (out["율"], out["감면율"], out["일이자율"]) == ("0.20", "0.50", "0.00022")
    assert [(c["무신고"], c["무신고_감면적용"]) for c in out["건"]] == [(41_254_800, 20_627_400)]
    assert "무신고_감면전" not in out and "무신고_감면전" not in out["건"][0]
    json.dumps(out, ensure_ascii=False)                       # 신고값에 그대로 실을 수 있다


def test_relieved_amount_splits_by_case():
    """토지 둘(다른 달): 감면을 적용하면 152,740,000 × 10% = 15,274,000. 건별 1,236,000 과 14,038,000.
    기한이 지나지 않은 건은 어느 쪽 금액도 0 이다."""
    f = _two_lots()
    r = _calc(f)
    out = penalty.final_return(r, f, "2027-05-20")
    assert out["무신고_감면적용"] == 15_274_000 and [c["무신고_감면적용"] for c in out["건"]] == [1_236_000, 14_038_000]
    out = penalty.final_return(r, f, "2027-01-15")
    assert out["무신고_감면적용"] == 1_236_000 and [c["무신고_감면적용"] for c in out["건"]] == [1_236_000, 0]


def test_note_says_relief_was_not_applied_and_gives_the_relieved_amount():
    out = penalty.final_return(_calc(CASES["BF"]), CASES["BF"], "2027-05-20")
    hit = [m for m in out["확인사항"] if "감면이 적용되면" in m and not m.startswith("지방소득세")]
    assert len(hit) == 1
    m = hit[0]
    assert m == out["감면안내"]                               # 신고_확인.md 알림 절에도 올리는 문장
    assert "감면 없이" in m and "20%" in m
    assert "기한 후 신고로 내면" in m and "50%" in m and "국세기본법 제48조" in m
    assert "2026-01-01" in m and "「기한 후 신고를 한 경우」" in m
    assert "기한 후 신고서를 만들지 않고 확정신고서를 만들므로" in m and "적용하지 않았다" in m
    assert "20,627,400원" in m and "세무 전문가" in m
    assert "경정할 것을 미리 알고 신고한 경우가 아니" in m      # 감면 규정의 괄호는 대안 금액 문장의 조건으로 붙인다
    assert "기준-" not in m and "법규" not in m               # 해석례 번호는 적지 않는다(규칙세트에 없다)
    first = out["확인사항"][0]
    assert "× 20%" in first and "(1 − 50%)" not in first      # 계산식에 감면이 없다


def test_no_relief_before_the_2026_wording_change_either():
    """2025년 양도를 2025-12-20 에 신고·납부: 감면 조문이 「과세표준신고를 한 경우」이던 구간이다. 이 스킬은 확정신고서를 만들므로
    이 구간에도 감면을 적용하지 않는다. 일수는 납부일까지 센다.
    F 를 2025-08-01 양도로 옮김: 세액 139,380,000, 기한 2025-10-31(금), 일수 2025-11-01 ~ 2025-12-20 = 30 + 20 = 50
    무신고 139,380,000 × 20% = 27,876,000(감면이 적용되면 13,938,000), 납부지연 139,380,000 × 50 × 22/100,000 = 1,533,180"""
    f = copy.deepcopy(CASES["F"])
    f["자산"][0]["양도"]["잔금일"] = "2025-08-01"
    out = penalty.final_return(_calc(f), f, "2025-12-20")
    assert _lines(out) == [(["F"], 139_380_000, "2025-10-31", 50, 27_876_000, 1_533_180)]
    assert out["감면적용"] is False and (out["무신고_감면없음"], out["무신고_감면적용"]) == (27_876_000, 13_938_000)
    hit = [m for m in out["확인사항"] if "감면이 적용되면" in m and not m.startswith("지방소득세")]
    assert len(hit) == 1 and hit[0] == out["감면안내"]
    assert "감면 없이" in hit[0] and "13,938,000원" in hit[0] and "확정신고서를 만들므로" in hit[0]
    assert "2026-01-01" not in hit[0] and "「기한 후 신고를 한 경우」" not in hit[0]     # 이 구간의 문구가 아니다
    assert "(1 − 50%)" not in out["확인사항"][0] and "× 20%" in out["확인사항"][0]
    assert not any("감면 50% 를 적용했다" in m or "감면하는 규정(국세기본법 제48조)을 적용했다" in m for m in out["확인사항"])


def _rules_copy(tmp_path, change):
    """규칙세트 사본을 만들어 change(data) 로 고친 뒤 판을 다시 쓴다. 폴더 경로를 돌려준다."""
    d = str(tmp_path / "rules")
    os.makedirs(os.path.join(d, "고시"))
    for name in R.EDITION_FILES:
        shutil.copy(os.path.join(RULES_DIR, name), os.path.join(d, name))
    path = os.path.join(d, "ruleset.json")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    change(data)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    R.write_edition(d, data["확인일"])
    return d


def test_relief_decision_does_not_read_the_excerpt_wording(tmp_path):
    """감면을 적용하지 않는 것은 조문 발췌의 글자와 상관없다. 지금 구간의 발췌를 옛 문구로 바꾼 규칙세트로도
    BF 무신고가산세는 206,274,000 × 20% = 41,254,800 이고 지방은 20,627,400 × 20% = 4,125,480 이다."""
    def old_wording(data):
        for key in ("가산세.무신고.확정신고감면율", "지방.가산세.무신고.확정신고감면율"):
            for e in data["규칙"][key]["이력"]:
                for g in e["근거"]:
                    g["발췌"] = [x.replace("제45조의3에 따른 기한 후 신고를 한 경우", "과세표준신고를 한 경우") for x in g["발췌"]]

    d = _rules_copy(tmp_path, old_wording)
    out = penalty.final_return(_calc(CASES["BF"]), CASES["BF"], "2027-05-20", rules_dir=d)
    assert out["감면적용"] is False and out["무신고"] == 41_254_800
    assert out["지방"]["감면적용"] is False and out["지방"]["무신고"] == 4_125_480
    assert not hasattr(penalty, "relief_needs_late_return")


def test_bf_alternative_when_each_sale_date_is_filed_separately():
    """같은 달 다른 날 양도를 양도일마다 따로 신고하는 것으로 보면(BF):
    F(2026-11-01) 413,300,000 → 94,060,000 + 113,300,000 × 40% = 139,380,000
    B(2026-11-20) 163,400,000 → 37,060,000 + 13,400,000 × 38% = 42,152,000, 합 181,532,000
    무신고 = 181,532,000 × 20% = 36,306,400 (F 27,876,000, B 8,430,400). 감면이 적용되면 18,153,200
    납부지연 = 139,380,000 × 107 × 22/100,000 = 3,281,005.2 → 3,281,000, 42,152,000 × 107 × 22/100,000 = 992,258.08 → 992,250, 합 4,273,250"""
    out = penalty.final_return(_calc(CASES["BF"]), CASES["BF"], "2027-05-20")
    alt = out["양도일별"]
    assert (alt["예정신고세액"], alt["무신고"], alt["납부지연"], alt["계"]) == (181_532_000, 36_306_400, 4_273_250, 40_579_650)
    assert alt["무신고_감면적용"] == 18_153_200
    assert [(c["자산"], c["양도일"], c["예정신고세액"], c["납부기한"], c["일수"], c["무신고"], c["납부지연"]) for c in alt["건"]] == [
        (["F"], "2026-11-01", 139_380_000, "2027-02-01", 107, 27_876_000, 3_281_000),
        (["B"], "2026-11-20", 42_152_000, "2027-02-01", 107, 8_430_400, 992_250)]
    hit = [m for m in out["확인사항"] if "같은 달" in m]
    assert len(hit) == 1
    assert "양도일마다 따로 신고하는 것으로 보면" in hit[0]
    assert "181,532,000원" in hit[0] and "36,306,400원" in hit[0] and "4,273,250원" in hit[0]
    assert (out["무신고"], out["납부지연"]) == (41_254_800, 4_855_680)           # 계산에 쓴 값은 합산한 쪽이다


def test_no_alternative_when_no_case_has_two_sale_dates():
    for name in ("BC",):
        assert penalty.final_return(_calc(CASES[name]), CASES[name], "2027-05-20")["양도일별"] is None
    f = _two_lots()
    assert penalty.final_return(_calc(f), f, "2027-05-20")["양도일별"] is None


def test_alternative_is_zero_for_a_case_not_yet_due():
    out = penalty.final_return(_calc(CASES["BF"]), CASES["BF"], "2027-02-01")
    alt = out["양도일별"]
    assert (alt["예정신고세액"], alt["무신고"], alt["납부지연"], alt["계"]) == (181_532_000, 0, 0, 0)


def test_penalty_uses_public_ruleset_names_only():
    import inspect
    assert R.label("47의2", "①2호") == "제47조의2①2호" and R.label("부칙", 공포번호="21212") == "부칙(제21212호)"
    assert "ruleset._" not in inspect.getsource(penalty)


# ---------------------------------------------------------------- 다루지 않는 경우

def test_unfinished_result_is_a_value_error():
    with pytest.raises(ValueError):
        penalty.final_return({"상태": "질문", "계산": None}, CASES["BF"], "2027-05-20")
    with pytest.raises(ValueError):
        penalty.final_return(_calc(CASES["BF"]), CASES["BF"], None)


def test_partly_filed_year_is_unsupported():
    f = copy.deepcopy(CASES["BF"])
    r = _calc(f)
    f["연간"]["기신고"] = [{"양도소득금액": 40_000_000, "결정세액": 4_545_000}]
    with pytest.raises(penalty.Unsupported, match="기신고") as e:
        penalty.final_return(r, f, "2027-05-20")
    assert e.value.계획 == "미정"                          # 기신고 합산은 어느 계획에도 들어 있지 않다


def test_after_final_return_deadline_is_unsupported():
    """확정신고 기한(2027-05-31)을 지나면 기한후신고라 감면율이 다르다."""
    r = _calc(CASES["BF"])
    assert penalty.final_return(r, CASES["BF"], "2027-05-31")["건"][0]["일수"] == 118       # 107 + 11
    with pytest.raises(penalty.Unsupported, match="2027-05-31"):
        penalty.final_return(r, CASES["BF"], "2027-06-01")


def test_permit_zone_asset_without_permit_date_is_unsupported():
    f = copy.deepcopy(CASES["F"])
    f["자산"][0]["토지거래허가대상"] = "예"
    r = _calc(f)
    with pytest.raises(penalty.Unsupported, match="허가일"):
        penalty.final_return(r, f, "2027-05-20")
    f["자산"][0]["토지거래허가"] = {"신청일": "2026-10-01", "허가일": "미정"}
    with pytest.raises(penalty.Unsupported, match="허가일"):
        penalty.final_return(r, f, "2027-05-20")


def test_permit_zone_asset_counts_from_permit_month():
    """허가 전에 대금을 청산한 허가구역 토지는 허가일이 속하는 달의 말일부터 2개월이 기한이다.
    F 양도 2026-11-01, 허가 2026-12-10: 기한 말일 2027-02-28(일), 다음 날 2027-03-01(월)이 3·1절이라 납부기한은 2027-03-02(화).
    일수 2027-03-03 ~ 2027-05-19 = 29 + 30 + 19 = 78
    세액 139,380,000(기본공제 뒤 413,300,000), 무신고 139,380,000 × 20% = 27,876,000, 납부지연 139,380,000 × 78 × 22/100,000 = 2,391,760.8 → 2,391,760"""
    f = copy.deepcopy(CASES["F"])
    f["자산"][0].update(토지거래허가대상="예", 토지거래허가={"신청일": "2026-10-01", "허가일": "2026-12-10"})
    out = penalty.final_return(_calc(f), f, "2027-05-20")
    assert _lines(out) == [(["F"], 139_380_000, "2027-03-02", 78, 27_876_000, 2_391_760)]
    assert any("허가일" in m and "2026-12-10" in m for m in out["확인사항"])
    f["자산"][0]["토지거래허가"]["허가일"] = "2026-10-15"            # 허가가 대금 청산보다 앞서면 양도일 기준
    assert penalty.final_return(_calc(f), f, "2027-05-20")["건"][0]["납부기한"] == "2027-02-01"


def test_case_whose_merged_comparison_tax_wins_is_unsupported(rs):
    """한 예정신고 건 안에 세율이 다른 자산이 있고 합산 비교세액(소득세법 제104조⑤)이 세율별 세액의 합보다 크면
    원문 사례에 계산 방식이 없어 정하지 않는다. 2주택 중과 과세표준 37,500,000 과 일반세율 551,600,000 을 같은 달에 양도:
    세율별 합 = (840,000 + 23,500,000 × 15% + 37,500,000 × 20%) + (174,060,000 + 51,600,000 × 42%)
    = 11,865,000 + 195,732,000 = 207,597,000 < 합산 174,060,000 + 89,100,000 × 42% = 211,482,000"""
    rows = [_row("A", "2026-05-15", 37_500_000, "47", 묶음="중과2", 중과="중과2", 종류="주택"),
            _row("B", "2026-05-29", 551_600_000, "10", 종류="주택")]
    with pytest.raises(penalty.Unsupported, match="합산"):
        penalty.cases(rows, _facts_for(rows), rs)
    rows[1] = _row("B", "2026-06-02", 551_600_000, "10", 종류="주택")          # 다른 달이면 건마다 따로라 정해진다
    got, _ = penalty.cases(rows, _facts_for(rows), rs)
    assert [c["예정신고세액"] for c in got] == [11_865_000, 195_732_000]


# ---- 공휴일 표를 반영한 납부기한 문장(계획 2b fix round 1) ----

def test_due_date_note_names_the_holiday_that_was_skipped():
    """F 를 2026-12-10 에 양도하면 예정신고 기한 말일은 2027-02-28(일요일)이고 다음 날이 3·1절이라 납부기한은 2027-03-02 다.
    일수는 2027-03-03 ~ 2027-05-19 = 29 + 30 + 19 = 78."""
    f = copy.deepcopy(CASES["F"])
    f["자산"][0]["양도"]["잔금일"] = "2026-12-10"
    out = penalty.final_return(_calc(f), f, "2027-05-20")
    assert (out["건"][0]["기한말일"], out["건"][0]["납부기한"], out["건"][0]["일수"]) == ("2027-02-28", "2027-03-02", 78)
    note = [m for m in out["확인사항"] if "납부기한은 2027-03-02" in m]
    assert len(note) == 1 and "2027-02-28(일요일), 2027-03-01(3·1절)" in note[0]
    assert not any("토요일·일요일만" in m or "다음 월요일" in m for m in out["확인사항"])


def test_due_date_in_a_year_without_holiday_table_is_flagged():
    """공휴일 표에 없는 해(2028년)에 끝나는 납부기한. 그 해의 연휴와 대체공휴일을 건너뛰지 못했다고 알린다.
    F 를 2027-11-01 에 양도하면 기한은 2028-01-31(월요일)이다."""
    f = copy.deepcopy(CASES["F"])
    f["자산"][0]["양도"]["잔금일"] = "2027-11-01"
    out = penalty.final_return(_calc(f), f, "2028-05-20")
    assert out["건"][0]["납부기한"] == "2028-01-31"
    note = [m for m in out["확인사항"] if "공휴일 표에 없" in m]
    assert len(note) == 2 and all("자산 F" in m and "일수가 줄어든다" in m for m in note)      # 국세 납부기한과 지방소득세 납부기한
    assert "예정신고 납부기한" in note[0] and "지방소득세 납부기한" in note[1]


# ---------------------------------------------------------------- 지방소득세 가산세(계획 2b fix round 2)
# 양도소득에 대한 개인지방소득세도 예정신고를 하지 않으면 무신고가산세와 납부지연가산세가 붙는다.
#   기한   소득세법이 정한 예정신고기한(옮기기 전 말일)에 2개월을 더한 날(지방세법 제103조의5①). 달 계산은 민법 방식이라
#          말일에 2개월을 더하면 다시 말일이다. 그 날이 토·일·공휴일·노동절이면 다음 날(지방세기본법 제24조①)
#   무신고 지방 예정신고 세액 × 20% × (1 − 50%). 지방세기본법 제57조②4호가목의 문언은 「확정신고기한까지 과세표준 신고를 한 경우」다
#   납부지연 지방 예정신고 세액 × 일수 × 1일 10만분의 22. 일수는 납부기한 다음 날부터 납부일까지(납부일을 넣는다)
#   끝수   건마다 원 미만을 버린다
# 지방소득세 예정신고기한과 끝수는 조문으로 정해지지 않아 정한 가정이다. 확인사항에 적는다.

LOCAL_KEYS = ["지방.가산세.무신고.율", "지방.가산세.무신고.확정신고감면율", "지방.가산세.납부지연.일이자율",
              "지방.가산세.납부지연.납부일산입", "지방.신고기한.가산개월"]


def test_local_rule_values_and_citations(rs):
    assert set(LOCAL_KEYS) <= set(keys.VALUE_KEYS)
    for on in ("2025-01-01", "2026-12-15", "2027-05-20"):
        assert rs.value("지방.가산세.무신고.율", on) == Decimal("0.20")
        assert rs.value("지방.가산세.무신고.확정신고감면율", on) == Decimal("0.50")
        assert rs.value("지방.가산세.납부지연.일이자율", on) == Decimal("0.00022")
        assert rs.value("지방.가산세.납부지연.납부일산입", on) == 1
        assert rs.value("지방.신고기한.가산개월", on) == 2

    def cited(key):
        return [(c["법령"], c["조항"]) for c in rs.cite(key, "2027-05-20")]
    assert cited("지방.가산세.무신고.율") == [("지방세기본법", "제53조①")]
    assert cited("지방.가산세.무신고.확정신고감면율") == [("지방세기본법", "제57조②4호가목")]
    # 제55조① 은 한도(내지 않은 세액의 100분의 75)의 근거다. 지원하는 일수로는 한도에 이르지 않아 한도를 계산에 넣지 않았다고 문서에 적는다
    assert cited("지방.가산세.납부지연.일이자율") == [("지방세기본법", "제55조①1호"), ("지방세기본법", "제55조①"),
                                            ("지방세기본법 시행령", "제34조①")]
    cap = [c for c in rs.cite("지방.가산세.납부지연.일이자율", "2027-05-20") if c["조항"] == "제55조①"][0]["발췌"]
    assert any("100분의 75" in x for x in cap)
    # 한도에 닿는 일수는 0.75 ÷ 0.00022 = 3,409.09 일이다. 예정신고기한부터 확정신고기한까지는 1년 반이 안 된다
    assert Decimal("0.75") / rs.value("지방.가산세.납부지연.일이자율", "2027-05-20") > 3409
    assert cited("지방.신고기한.가산개월") == [("지방세법", "제103조의5①"), ("지방세법", "제103조의7①"),
                                       ("지방세기본법", "제23조"), ("지방세기본법", "제24조①")]
    relief = rs.cite("지방.가산세.무신고.확정신고감면율", "2027-05-20")[0]["발췌"]
    assert any("확정신고기한까지 과세표준 신고를 한 경우" in x for x in relief)
    assert not any("기한 후 신고" in x for x in relief)          # 국세와 달리 기한 후 신고를 요구하지 않는다


def test_add_months_follows_civil_code_counting():
    """기한 다음 날이 기산일이다. 말일에 더하면 말일이고, 달 중간이면 같은 날이다(해당일이 없으면 그 달 말일)."""
    assert dates.add_months(date(2026, 11, 30), 2) == date(2027, 1, 31)
    assert dates.add_months(date(2026, 12, 31), 2) == date(2027, 2, 28)
    assert dates.add_months(date(2027, 2, 28), 2) == date(2027, 4, 30)
    assert dates.add_months(date(2027, 1, 31), 2) == date(2027, 3, 31)
    assert dates.add_months(date(2027, 2, 1), 2) == date(2027, 4, 1)
    assert dates.add_months(date(2027, 12, 30), 2) == date(2028, 2, 29)      # 기산일 12-31, 2월 31일이 없어 말일
    assert dates.add_months(date(2027, 5, 31), 2) == date(2027, 7, 31)


def test_local_filing_deadline(rs):
    """지방 기한 = 소득세법 기한(옮기기 전) + 2개월, 그 날이 쉬는 날이면 다음 날."""
    d = dates.local_filing_deadline("예정", "2026-11-20", rs)        # 국세 말일 2027-01-31(일) → 지방 2027-03-31(수)
    assert tuple(d) == (date(2027, 3, 31), date(2027, 3, 31)) and d.옮긴이유 == () and d.공휴일표
    d = dates.local_filing_deadline("예정", "2026-09-13", rs)        # 국세 2026-11-30 → 지방 2027-01-31(일) → 02-01
    assert tuple(d) == (date(2027, 1, 31), date(2027, 2, 1)) and dates.skipped_text(d) == "2027-01-31(일요일)"
    d = dates.local_filing_deadline("예정", "2026-10-13", rs)        # 국세 2026-12-31 → 지방 2027-02-28(일) → 3·1절 → 03-02
    assert tuple(d) == (date(2027, 2, 28), date(2027, 3, 2))
    assert dates.skipped_text(d) == "2027-02-28(일요일), 2027-03-01(3·1절)"
    d = dates.local_filing_deadline("확정", "2026-11-20", rs)        # 국세 2027-05-31 → 지방 2027-07-31(토) → 08-02
    assert tuple(d) == (date(2027, 7, 31), date(2027, 8, 2))
    assert tuple(dates.filing_deadline("예정", "2026-11-20", rs)) == (date(2027, 1, 31), date(2027, 2, 1))   # 국세 기한은 그대로다


def test_bf_local_penalty_matches_hand_calculation():
    """BF: 지방 예정신고 세액 = 576,700,000 에 지방 누진세율 = 17,406,000 + 76,700,000 × 4.2% = 20,627,400
    국세 기한 말일 2027-01-31 에 2개월을 더한 2027-03-31(수요일)이 지방 납부기한. 일수 2027-04-01 ~ 2027-05-20 = 30 + 20 = 50
    무신고 = 20,627,400 × 20% = 4,125,480(감면이 적용되면 × 50% = 2,062,740). 국세와 같이 감면을 적용하지 않는다
    납부지연 = 20,627,400 × 50 × 22/100,000 = 226,901.4 → 226,901(원 미만 버림), 계 4,352,381"""
    out = penalty.final_return(_calc(CASES["BF"]), CASES["BF"], "2027-05-20")
    loc = out["지방"]
    assert (loc["무신고"], loc["납부지연"], loc["계"]) == (4_125_480, 226_901, 4_352_381)
    assert loc["감면적용"] is False and (loc["무신고_감면적용"], loc["무신고_감면없음"]) == (2_062_740, 4_125_480)
    assert (loc["율"], loc["감면율"], loc["일이자율"]) == ("0.20", "0.50", "0.00022")
    assert [(c["자산"], c["예정신고세액"], c["기한말일"], c["납부기한"], c["일수"], c["무신고"], c["납부지연"]) for c in loc["건"]] == [
        (["F", "B"], 20_627_400, "2027-03-31", "2027-03-31", 50, 4_125_480, 226_901)]
    assert loc["건"][0]["무신고_감면적용"] == 2_062_740
    assert loc["열"] == {"1-10": {"무신고": 4_125_480, "납부지연": 226_901}}
    assert [(c["법령"], c["조항"]) for c in loc["근거"]][:2] == [("지방세기본법", "제53조①"), ("지방세기본법", "제57조②4호가목")]
    json.dumps(out, ensure_ascii=False)
    assert (out["무신고"], out["납부지연"]) == (41_254_800, 4_855_680)       # 국세 금액은 그대로다


def test_local_penalty_two_cases_from_answer_key():
    """09-8: A·B 건 지방 세액 624,000 + 4,564,817 × 2.4% = 733,555, C 건 1,206,272 × 5% = 60,313
    A·B: 국세 기한 2026-11-30 + 2개월 = 2027-01-31(일) → 2027-02-01. 일수 02-02 ~ 05-31 = 27 + 31 + 30 + 31 = 119
    C: 국세 기한 2026-12-31 + 2개월 = 2027-02-28(일) → 03-01(3·1절) → 2027-03-02. 일수 03-03 ~ 05-31 = 29 + 30 + 31 = 90
    무신고 = 793,868 × 20% = 158,773.6 → 158,773 (건별 733,555 × 20% = 146,711, 60,313 × 20% = 12,062.6 → 12,062, 합 158,773)
    감면이 적용되면 793,868 × 10% = 79,386.8 → 79,386
    납부지연 = 733,555 × 119 × 22/100,000 = 19,204.47 → 19,204, 60,313 × 90 × 22/100,000 = 1,194.20 → 1,194"""
    from answer_keys import KEYS
    k = KEYS["09-8"]
    out = penalty.final_return(_calc(k["facts"]), k["facts"], "2027-05-31")
    loc = out["지방"]
    assert [(c["자산"], c["예정신고세액"], c["기한말일"], c["납부기한"], c["일수"], c["무신고"], c["납부지연"]) for c in loc["건"]] == [
        (["A", "B"], 733_555, "2027-01-31", "2027-02-01", 119, 146_711, 19_204),
        (["C"], 60_313, "2027-02-28", "2027-03-02", 90, 12_062, 1_194)]
    assert (loc["무신고"], loc["납부지연"], loc["계"]) == (158_773, 20_398, 179_171)
    assert (loc["감면적용"], loc["무신고_감면없음"], loc["무신고_감면적용"]) == (False, 158_773, 79_386)
    assert loc["열"] == {"1-10": {"무신고": 146_711, "납부지연": 19_204}, "1-20": {"무신고": 12_062, "납부지연": 1_194}}
    want = {x: v for x, v in k["현행지방가산세"].items() if x != "납부할세액"}      # 납부할세액은 지방 서식 ⑮ 기대값이다
    assert {x: loc[x] for x in want} == want


def test_local_penalty_is_zero_until_the_local_deadline():
    """지방 납부기한(2027-03-31)까지는 지방 가산세가 없다. 국세 예정신고 기한(2027-02-01)은 지났으므로 국세 가산세는 붙는다.
    다음 날 2027-04-01 은 무신고 20,627,400 × 20% = 4,125,480, 납부지연 20,627,400 × 1 × 22/100,000 = 4,538.028 → 4,538(납부일을 넣어 1일)."""
    r = _calc(CASES["BF"])
    out = penalty.final_return(r, CASES["BF"], "2027-03-31")
    assert out["무신고"] == 41_254_800 and (out["지방"]["무신고"], out["지방"]["납부지연"], out["지방"]["계"]) == (0, 0, 0)
    assert out["지방"]["건"][0]["기한경과"] is False
    out = penalty.final_return(r, CASES["BF"], "2027-04-01")
    assert (out["지방"]["무신고"], out["지방"]["납부지연"], out["지방"]["건"][0]["일수"]) == (4_125_480, 4_538, 1)


def test_local_penalty_before_the_local_deadline_is_one_plain_sentence():
    """작성일이 지방 예정신고기한 이전이면 지방 가산세가 없다. 0원을 계산했다거나 감면을 적용했다는 문장, 가정을 적은 문장 대신
    한 줄만 낸다. 국세 가산세 문장은 그대로다."""
    out = penalty.final_return(_calc(CASES["BF"]), CASES["BF"], "2027-03-31")
    local = [m for m in out["확인사항"] if "지방소득세" in m]
    assert local == ["지방소득세는 지방 예정신고기한 2027-03-31 이전에 신고·납부하므로 가산세가 없다"]
    assert out["지방"]["가정안내"] is None and out["지방"]["감면안내"] is None
    assert out["감면안내"] and "감면 없이" in out["감면안내"]
    # 건이 둘이고 둘 다 지방 기한 이전이면 가장 이른 지방 기한을 적는다(09-8 을 2027-01-20 에 신고: 지방 기한 2027-02-01, 2027-03-02)
    from answer_keys import KEYS
    k = KEYS["09-8"]
    out = penalty.final_return(_calc(k["facts"]), k["facts"], "2027-01-20")
    assert out["무신고"] > 0 and out["지방"]["계"] == 0
    assert [m for m in out["확인사항"] if "지방소득세" in m] == ["지방소득세는 지방 예정신고기한 2027-02-01 이전에 신고·납부하므로 가산세가 없다"]


def test_local_penalty_with_one_case_due_keeps_the_case_sentences():
    """건 둘 가운데 하나만 지방 기한이 지났으면 가산세 문장과 건별 문장을 그대로 낸다(09-8 을 2027-02-20 에 신고:
    A·B 건은 지방 기한 2027-02-01 이 지났고 C 건은 2027-03-02 전이다). 무신고 733,555 × 20% = 146,711"""
    from answer_keys import KEYS
    k = KEYS["09-8"]
    out = penalty.final_return(_calc(k["facts"]), k["facts"], "2027-02-20")
    assert out["지방"]["무신고"] == 146_711 and [c["기한경과"] for c in out["지방"]["건"]] == [True, False]
    notes = out["확인사항"]
    assert any(m.startswith("지방소득세에도") and "146,711원" in m for m in notes)
    assert any("자산 C" in m and "지방소득세 가산세를 계산하지 않았다" in m for m in notes)
    assert not any("가산세가 없다" in m for m in notes)


def test_local_penalty_notes_state_the_two_assumptions():
    out = penalty.final_return(_calc(CASES["BF"]), CASES["BF"], "2027-05-20")
    notes = out["확인사항"]
    first = [m for m in notes if m.startswith("지방소득세에도")]
    assert len(first) == 1 and "4,125,480원" in first[0] and "226,901원" in first[0] and "납부일(2027-05-20)까지" in first[0]
    assert "지방세기본법 제53조·제55조" in first[0] and "지방세기본법 시행령 제34조" in first[0]      # 계산식에 감면 조문이 없다
    relief = [m for m in notes if "지방소득세 무신고가산세" in m and "감면 없이" in m]
    assert len(relief) == 1 and relief[0] == out["지방"]["감면안내"]
    m = relief[0]
    assert "지방세기본법 제57조" in m and "확정신고기한까지 신고한 경우" in m and "과세관청이 달리 본 예" in m
    assert "적용하지 않았다" in m and "감면이 적용되면 지방소득세 무신고가산세는 2,062,740원" in m
    assert "경정할 것을 미리 알고 신고한 경우가 아니" in m
    assert "위택스 화면의 가산세와 다르면 위택스 값을 따른다" in m and "세무 전문가와 확인한다" in m
    assert "기준-" not in m and "법규" not in m and "적용되지 않으면" not in m
    assert "(1 − 50%)" not in first[0] and "× 20%" in first[0]
    assume = [m for m in notes if "두 가지를 가정" in m]
    assert len(assume) == 1 and assume[0] == out["지방"]["가정안내"]
    assert "옮기기 전" in assume[0] and "2개월을 더한 날" in assume[0] and "지방세법 제103조의5" in assume[0]
    assert "위택스 화면이 계산한 가산세와 다르면 위택스 값을 따른다" in assume[0]
    # 끝수 설명은 실제 계산과 같다: 무신고는 합계에서 버린 뒤 건에 나누고, 납부지연은 건마다 버린다
    assert "무신고가산세는 세액 합계에 율을 곱해 원 미만을 버린 뒤 건에 나눴고" in assume[0]
    assert "납부지연가산세는 건마다 원 미만을 버렸다" in assume[0]
    assert "가산세 금액은 건마다 원 미만을 버렸다" not in assume[0]
    assert any("자산 F, B" in m and "지방소득세" in m and "납부기한은 2027-03-31" in m for m in notes)
    assert all(chr(0x2014) not in m and not m.rstrip().endswith("?") for m in notes)


def test_local_rates_come_from_the_ruleset(tmp_path):
    d = str(tmp_path / "rules")
    os.makedirs(os.path.join(d, "고시"))
    for name in R.EDITION_FILES:
        shutil.copy(os.path.join(RULES_DIR, name), os.path.join(d, name))
    path = os.path.join(d, "ruleset.json")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    for key, value in (("지방.가산세.무신고.율", "0.40"), ("지방.가산세.무신고.확정신고감면율", "0.25"),
                       ("지방.가산세.납부지연.일이자율", "0.00044"), ("지방.신고기한.가산개월", 3)):
        for e in data["규칙"][key]["이력"]:
            e["값"] = value
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    R.write_edition(d, data["확인일"])
    out = penalty.final_return(_calc(CASES["BF"]), CASES["BF"], "2027-05-20", rules_dir=d)
    # 기한 2027-01-31 + 3개월 = 2027-04-30(금), 일수 20. 무신고 20,627,400 × 40% = 8,250,960(감면이 적용되면 × 75% = 6,188,220)
    # 납부지연 20,627,400 × 20 × 44/100,000 = 181,521.12 → 181,521
    loc = out["지방"]
    assert (loc["건"][0]["납부기한"], loc["건"][0]["일수"], loc["무신고"], loc["납부지연"]) == ("2027-04-30", 20, 8_250_960, 181_521)
    assert loc["무신고_감면적용"] == 6_188_220
