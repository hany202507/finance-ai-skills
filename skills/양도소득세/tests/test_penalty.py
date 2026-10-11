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

from yangdo import RULES_DIR, engine, keys, penalty
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
    무신고 = 206,274,000 × 20% × 50% = 20,627,400
    납부지연 = 206,274,000 × 107 × 22/100,000 = 4,855,689.96 → 4,855,680"""
    out = penalty.final_return(_calc(CASES["BF"]), CASES["BF"], "2027-05-20")
    assert (out["무신고"], out["납부지연"], out["계"]) == (20_627_400, 4_855_680, 25_483_080)
    assert _lines(out) == [(["F", "B"], 206_274_000, "2027-02-01", 107, 20_627_400, 4_855_680)]
    assert out["건"][0]["기한말일"] == "2027-01-31"
    assert out["열"] == {"1-10": {"무신고": 20_627_400, "납부지연": 4_855_680}}
    assert {"무신고", "납부지연", "계", "건", "열", "확인사항"} <= set(out)


def test_bc_two_cases_in_two_rate_columns():
    """BC: 단기 주택 C(2026-10-30, 70%)와 누진세율 주택 B(2026-11-20). 기본공제는 먼저 양도한 C 에서 뺀다.
    C 건: 47,500,000 × 70% = 33,250,000, 기한 2026-12-31(목), 일수 2027-01-01 ~ 2027-05-19 = 139
    B 건: 163,400,000 → 37,060,000 + 13,400,000 × 38% = 42,152,000, 기한 2027-02-01, 일수 107
    무신고 = 75,402,000 × 10% = 7,540,200 (C 3,325,000, B 4,215,200)
    납부지연 = 33,250,000 × 139 × 22/100,000 = 1,016,785 → 1,016,780, 42,152,000 × 107 × 22/100,000 = 992,258.08 → 992,250"""
    out = penalty.final_return(_calc(CASES["BC"]), CASES["BC"], "2027-05-20")
    assert _lines(out) == [(["C"], 33_250_000, "2026-12-31", 139, 3_325_000, 1_016_780),
                           (["B"], 42_152_000, "2027-02-01", 107, 4_215_200, 992_250)]
    assert out["열"] == {"1-10": {"무신고": 4_215_200, "납부지연": 992_250},
                        "1-46": {"무신고": 3_325_000, "납부지연": 1_016_780}}
    assert (out["무신고"], out["납부지연"], out["계"]) == (7_540_200, 2_009_030, 9_549_230)


def _two_lots():
    """누진세율 토지 둘을 다른 달에 양도(원문 사례 5 와 같은 꼴). L 은 2015-05-01 취득 1억원, 2026-08-10 양도 2억원."""
    lot = asset("L", "토지", 평택, "2015-05-01", "2026-08-10", 200_000_000, 100_000_000, 토지사용현황="사업용")
    return facts([lot, CASES["F"]["자산"][0]])


def test_progressive_assets_sold_in_different_months_are_not_merged():
    """L: 양도차익 1억원, 보유 11년 장기보유특별공제 22%, 양도소득금액 78,000,000, 기본공제 뒤 75,500,000
       → 6,240,000 + 25,500,000 × 24% = 12,360,000. 기한 말일 2026-10-31(토) → 2026-11-02, 일수 2026-11-03 ~ 2027-05-19 = 198
    F: 양도소득금액 415,800,000(기본공제는 L 이 썼다) → 94,060,000 + 115,800,000 × 40% = 140,380,000, 일수 107
    연간 산출세액은 합산한 170,580,000 이지만 가산세는 건별 세액의 합 152,740,000 에 붙는다
    무신고 = 152,740,000 × 10% = 15,274,000
    납부지연 = 12,360,000 × 198 × 22/100,000 = 538,401.6 → 538,400, 140,380,000 × 107 × 22/100,000 = 3,304,545.2 → 3,304,540"""
    f = _two_lots()
    r = _calc(f)
    assert r["계산"]["합계"]["산출세액"] == 170_580_000
    out = penalty.final_return(r, f, "2027-05-20")
    assert _lines(out) == [(["L"], 12_360_000, "2026-11-02", 198, 1_236_000, 538_400),
                           (["F"], 140_380_000, "2027-02-01", 107, 14_038_000, 3_304_540)]
    assert (out["무신고"], out["납부지연"], out["계"]) == (15_274_000, 3_842_940, 19_116_940)
    assert out["열"] == {"1-10": {"무신고": 15_274_000, "납부지연": 3_842_940}}
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
    assert (out["무신고"], out["납부지연"]) == (20_627_400, 0) and out["건"][0]["일수"] == 0


def test_only_cases_past_due_are_penalized():
    """L 건(기한 2026-11-02)은 지났고 F 건(기한 2027-02-01)은 지나지 않은 납부일: L 건에만 붙는다.
    일수 2026-11-03 ~ 2027-01-14 = 28 + 31 + 14 = 73, 납부지연 12,360,000 × 73 × 22/100,000 = 198,501.6 → 198,500"""
    f = _two_lots()
    out = penalty.final_return(_calc(f), f, "2027-01-15")
    assert _lines(out) == [(["L"], 12_360_000, "2026-11-02", 73, 1_236_000, 198_500),
                           (["F"], 140_380_000, "2027-02-01", 0, 0, 0)]
    assert (out["무신고"], out["납부지연"], out["계"]) == (1_236_000, 198_500, 1_434_500)


def test_fully_exempt_assets_have_no_case():
    out = penalty.final_return(_calc(CASES["G"]), CASES["G"], "2027-05-20")
    assert (out["무신고"], out["납부지연"], out["계"], out["건"]) == (0, 0, 0, [])


def test_notes_say_what_was_assumed():
    out = penalty.final_return(_calc(CASES["BF"]), CASES["BF"], "2027-05-20")
    notes = out["확인사항"]
    assert any("부정행위" in m for m in notes)
    assert any("미리 알고" in m for m in notes)
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
    # 무신고 206,274,000 × 40% × 75% = 61,882,200. 납부지연 206,274,000 × 108 × 44/100,000 = 9,802,140.48 → 9,802,140
    assert (out["무신고"], out["납부지연"], out["건"][0]["일수"]) == (61_882_200, 9_802_140, 108)


# ---------------------------------------------------------------- 감면 전제와 대안 금액(검토 반영)

def test_result_carries_pre_relief_amount_and_rates():
    """감면이 적용되지 않는 쪽으로 해석되면 무신고가산세는 감면 전 금액이다. 결과가 그 금액과 율을 싣는다.
    BF: 206,274,000 × 20% = 41,254,800(감면 뒤 20,627,400)"""
    out = penalty.final_return(_calc(CASES["BF"]), CASES["BF"], "2027-05-20")
    assert (out["무신고_감면전"], out["무신고"]) == (41_254_800, 20_627_400)
    assert (out["율"], out["감면율"], out["일이자율"]) == ("0.20", "0.50", "0.00022")
    assert [c["무신고_감면전"] for c in out["건"]] == [41_254_800]
    json.dumps(out, ensure_ascii=False)                       # 신고값에 그대로 실을 수 있다


def test_pre_relief_amount_splits_like_the_relieved_amount():
    """토지 둘(다른 달): 152,740,000 × 20% = 30,548,000. 건별 12,360,000 × 20% = 2,472,000, 140,380,000 × 20% = 28,076,000.
    기한이 지나지 않은 건은 감면 전 금액도 0 이다."""
    f = _two_lots()
    r = _calc(f)
    out = penalty.final_return(r, f, "2027-05-20")
    assert out["무신고_감면전"] == 30_548_000 and [c["무신고_감면전"] for c in out["건"]] == [2_472_000, 28_076_000]
    out = penalty.final_return(r, f, "2027-01-15")
    assert out["무신고_감면전"] == 2_472_000 and [c["무신고_감면전"] for c in out["건"]] == [2_472_000, 0]


def test_note_states_the_relief_premise_and_the_amount_without_relief():
    out = penalty.final_return(_calc(CASES["BF"]), CASES["BF"], "2027-05-20")
    hit = [m for m in out["확인사항"] if "감면이 적용되지 않으면" in m]
    assert len(hit) == 1
    m = hit[0]
    assert "국세기본법 제48조" in m and "50%" in m
    assert "2026-01-01" in m and "「기한 후 신고를 한 경우」" in m and "확정하지 못했다" in m
    assert "41254800원" in m and "세무 전문가" in m


def test_relief_note_before_the_2026_wording_change():
    """2025년 양도를 2025-12-20 에 신고·납부: 감면 조문은 옛 문구 구간이라 문구 개정 문장이 없다. 일수는 납부일까지 센다.
    F 를 2025-08-01 양도로 옮김: 세액 139,380,000, 기한 2025-10-31(금), 일수 2025-11-01 ~ 2025-12-20 = 30 + 20 = 50
    납부지연 139,380,000 × 50 × 22/100,000 = 1,533,180"""
    f = copy.deepcopy(CASES["F"])
    f["자산"][0]["양도"]["잔금일"] = "2025-08-01"
    out = penalty.final_return(_calc(f), f, "2025-12-20")
    assert _lines(out) == [(["F"], 139_380_000, "2025-10-31", 50, 13_938_000, 1_533_180)]
    hit = [m for m in out["확인사항"] if "감면이 적용되지 않으면" in m]
    assert len(hit) == 1 and "바뀌었" not in hit[0] and "27876000원" in hit[0]


def test_bf_alternative_when_each_sale_date_is_filed_separately():
    """같은 달 다른 날 양도를 양도일마다 따로 신고하는 것으로 보면(BF):
    F(2026-11-01) 413,300,000 → 94,060,000 + 113,300,000 × 40% = 139,380,000
    B(2026-11-20) 163,400,000 → 37,060,000 + 13,400,000 × 38% = 42,152,000, 합 181,532,000
    무신고 = 181,532,000 × 10% = 18,153,200
    납부지연 = 139,380,000 × 107 × 22/100,000 = 3,281,005.2 → 3,281,000, 42,152,000 × 107 × 22/100,000 = 992,258.08 → 992,250, 합 4,273,250"""
    out = penalty.final_return(_calc(CASES["BF"]), CASES["BF"], "2027-05-20")
    alt = out["양도일별"]
    assert (alt["예정신고세액"], alt["무신고"], alt["납부지연"], alt["계"]) == (181_532_000, 18_153_200, 4_273_250, 22_426_450)
    assert alt["무신고_감면전"] == 36_306_400
    assert [(c["자산"], c["양도일"], c["예정신고세액"], c["납부기한"], c["일수"], c["무신고"], c["납부지연"]) for c in alt["건"]] == [
        (["F"], "2026-11-01", 139_380_000, "2027-02-01", 107, 13_938_000, 3_281_000),
        (["B"], "2026-11-20", 42_152_000, "2027-02-01", 107, 4_215_200, 992_250)]
    hit = [m for m in out["확인사항"] if "같은 달" in m]
    assert len(hit) == 1
    assert "양도일마다 따로 신고하는 것으로 보면" in hit[0]
    assert "181532000원" in hit[0] and "18153200원" in hit[0] and "4273250원" in hit[0]
    assert (out["무신고"], out["납부지연"]) == (20_627_400, 4_855_680)           # 계산에 쓴 값은 합산한 쪽이다


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
    with pytest.raises(penalty.Unsupported, match="기신고"):
        penalty.final_return(r, f, "2027-05-20")


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
    세액 139,380,000(기본공제 뒤 413,300,000), 무신고 13,938,000, 납부지연 139,380,000 × 78 × 22/100,000 = 2,391,760.8 → 2,391,760"""
    f = copy.deepcopy(CASES["F"])
    f["자산"][0].update(토지거래허가대상="예", 토지거래허가={"신청일": "2026-10-01", "허가일": "2026-12-10"})
    out = penalty.final_return(_calc(f), f, "2027-05-20")
    assert _lines(out) == [(["F"], 139_380_000, "2027-03-02", 78, 13_938_000, 2_391_760)]
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
    assert len(note) == 1 and "자산 F" in note[0] and "일수가 줄어든다" in note[0]
