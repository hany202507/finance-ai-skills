# -*- coding: utf-8 -*-
import copy

import pytest

from cases import CASES
from yangdo import engine, ruleset, verify

RS = ruleset.load()


def done(name):
    r = engine.calculate(copy.deepcopy(CASES[name]), today="2026-10-09")
    assert r["상태"] == "완료", r
    return r


def test_clean_cases_pass():
    for name in ("A", "B", "C", "D", "E", "F", "G", "H", "J", "K", "BC", "BF"):
        assert done(name)["검산"] == [], name


def test_detects_wrong_ltd_rate():
    r = done("B")
    r["계산"]["자산"][0]["계산"]["장특공률"] = "0.16"
    assert any(m.startswith("V2") for m in verify.check(r["계산"], CASES["B"], RS))


def test_detects_ltd_on_heavy():
    r = done("D")
    r["계산"]["자산"][0]["계산"]["장특공"] = 1
    assert any(m.startswith("V3") for m in verify.check(r["계산"], CASES["D"], RS))


def test_detects_exempt_over_threshold():
    f = copy.deepcopy(CASES["G"])
    r = done("G")
    f["자산"][0]["전체양도가액"] = 1_300_000_000
    assert any(m.startswith("V1") for m in verify.check(r["계산"], f, RS))


def test_detects_local_tax_and_total():
    r = done("B")
    r["계산"]["자산"][0]["계산"]["지방소득세"] += 100
    r["계산"]["합계"]["산출세액"] += 1
    msgs = verify.check(r["계산"], CASES["B"], RS)
    assert any(m.startswith("V6") for m in msgs) and any(m.startswith("V10") for m in msgs)


def test_closed_ltd():
    from decimal import Decimal
    assert verify.closed_ltd({"장특공": "표2", "보유년": 12, "거주년": 12}) == Decimal("0.80")
    assert verify.closed_ltd({"장특공": "표1", "보유년": 21, "거주년": 0}) == Decimal("0.30")


# 아래는 묶음 4 착수 전 변경(같은 세율 자산 합산, 제104조⑤2호)에 맞춘 추가 시험

def test_v10_total_is_max_of_group_sum_and_comparison():
    """산출세액은 max(호별합산세액, 합산비교세액)다. BF 는 두 자산이 한 묶음이라 호별 합산이 자산별 합보다 크다."""
    for name in ("BC", "BF"):
        t = done(name)["계산"]["합계"]
        assert t["산출세액"] == max(t["호별합산세액"], t["합산비교세액"])
        assert t["지방소득세"] == max(t["지방_호별합산"], t["지방_합산비교"])
    t = done("BF")["계산"]["합계"]
    assert t["호별합산세액"] > t["자산별세액"]


def test_v10_detects_group_total_mismatch():
    r = done("BC")
    r["계산"]["합계"]["호별합산세액"] += 1
    assert any(m.startswith("V10") for m in verify.check(r["계산"], CASES["BC"], RS))
    r = done("BC")
    r["계산"]["합계"]["지방소득세"] += 1
    assert any(m.startswith("V10") for m in verify.check(r["계산"], CASES["BC"], RS))


def test_v10_detects_per_asset_sum_drift():
    """자산별세액이 자산 행의 합과 다르면 계산 중간값이 깨진 것이다."""
    r = done("BC")
    r["계산"]["합계"]["자산별세액"] += 1
    assert any(m.startswith("V10") for m in verify.check(r["계산"], CASES["BC"], RS))


def _tamper(name, fn):
    r = done(name)
    fn(r["계산"]["자산"][0])
    return [m.split(":")[0].split(" ")[0] for m in verify.check(r["계산"], CASES[name], RS)]


def test_detects_taxable_base_mismatch():
    assert "V4" in _tamper("A", lambda row: row["계산"].__setitem__("과세표준", row["계산"]["과세표준"] + 1))


def test_detects_taxable_gain_above_gain():
    assert "V7" in _tamper("B", lambda row: row["계산"].__setitem__("과세양도차익", row["계산"]["양도차익"] + 1))


def test_detects_holding_years_mismatch():
    assert "V8" in _tamper("A", lambda row: row["판정"].__setitem__("보유년", row["판정"]["보유년"] + 1))


def test_detects_high_price_apportion_mismatch():
    assert "V9" in _tamper("A", lambda row: row["계산"].__setitem__("과세양도차익", row["계산"]["과세양도차익"] + 5))


def test_detects_basic_deduction_over_limit():
    r = done("BC")
    r["계산"]["자산"][0]["계산"]["기본공제"] = 2_500_000
    r["계산"]["자산"][1]["계산"]["기본공제"] = 2_500_000
    assert any(m.startswith("V4: 기본공제 합") for m in verify.check(r["계산"], CASES["BC"], RS))


def test_v5_detects_wrong_marginal_slope(monkeypatch):
    """누진세율 계산이 한계세율과 다른 기울기를 내면 V5 가 알린다."""
    from decimal import Decimal
    from yangdo import calc
    r = done("B")
    monkeypatch.setattr(calc, "progressive", lambda base, table: Decimal(base) * Decimal("0.5"))
    assert any(m.startswith("V5") for m in verify.check(r["계산"], CASES["B"], RS))


def test_check_does_not_mutate_result():
    r = done("BC")
    before = copy.deepcopy(r["계산"])
    verify.check(r["계산"], CASES["BC"], RS)
    assert r["계산"] == before


def test_workbook_check_detects_engine_mismatch(tmp_path):
    p = str(tmp_path / "w.xlsx")
    r = engine.calculate(copy.deepcopy(CASES["B"]), today="2026-10-09", workbook_path=p)
    assert r["검산"] == []
    r["계산"]["자산"][0]["계산"]["산출세액"] += 1000
    r["계산"]["합계"]["산출세액"] += 1000
    msgs = verify.check_workbook(p, r["계산"])
    assert any(m.startswith("W B 산출세액") for m in msgs) and any("합계 산출세액" in m for m in msgs)


def test_verify_reads_dates_strictly():
    """검산도 YYYY-MM-DD 글자만 받는다(파이썬 3.10 과 3.11 이상의 결과가 같다)."""
    assert verify._years("2014-11-01", "2026-11-15") == 12
    with pytest.raises(ValueError):
        verify._years("20141101", "2026-11-15")
