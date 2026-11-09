"""표본 평가 엔진(2026-11-09): 포아송 상한 계수, 금액 단위 표본 상한 왜곡표시(AICPA 감사 표본 지침 방식), 확장계수,
예상 왜곡표시를 넣은 표본 간격, 체계적 표본, 층 배분, 비통계 비율 투영, 특정 항목 선정."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from audit.workpapers import sampling
from audit.workpapers import sampling_eval as se


@pytest.mark.parametrize("k,want", [(0, 2.9957), (1, 4.7439), (2, 6.2958), (3, 7.7537), (4, 9.1535)])
def test_poisson_upper_95(k, want):
    assert se.upper(k, 0.95) == pytest.approx(want, abs=1e-4)


def test_poisson_upper_other_levels():
    assert se.upper(0, 0.90) == pytest.approx(2.3026, abs=1e-4)
    assert se.upper(1, 0.90) == pytest.approx(3.8897, abs=1e-4)
    assert se.upper(0, se.confidence_of(1.0)) == pytest.approx(1.0)
    t = se.factor_table(0.95, 3)
    assert [x[0] for x in t] == [1, 2, 3]
    assert t[0][2] == pytest.approx(4.7439 - 2.9957, abs=2e-4) and t[1][2] == pytest.approx(6.2958 - 4.7439, abs=2e-4)


def _row(amount, err, key=False, stratum="전체"):
    return {"amount": amount, "err": err, "key": key, "stratum": stratum, "done": True}


def test_mus_upper_limit_by_hand():
    """간격 100,000 · 신뢰계수 3.0(95%). 고액 1건 과대 5,000, 소액 과대 오염률 0.5 · 0.2, 소액 과소 오염률 0.2."""
    rows = [_row(250_000, 5_000), _row(10_000, 2_000), _row(50_000, 25_000), _row(20_000, -4_000), _row(30_000, None)]
    x = se.mus(rows, 100_000, 3.0, 0.95, tolerable=300_000)
    d1, d2 = 1.7481, 1.5519          # ΔF 는 F(k) 를 반올림 전에 빼고 넷째 자리로 반올림한 값(엑셀 계수 표와 같음)
    assert x["basic"] == pytest.approx(300_000)
    assert x["known_over"] == 5_000 and x["projected_over"] == pytest.approx(75_000)
    assert x["increment_over"] == pytest.approx(50_000 * (d1 - 1) + 20_000 * (d2 - 1), rel=1e-4)
    assert x["upper_over"] == pytest.approx(300_000 + 75_000 + 50_000 * (d1 - 1) + 20_000 * (d2 - 1), rel=1e-5)
    assert x["upper_under"] == pytest.approx(300_000 + 20_000 + 20_000 * (d1 - 1), rel=1e-5)
    assert x["estimate"] == pytest.approx(55_000)
    assert x["verdict"] == se.V_UPPER_OVER


def test_mus_verdicts():
    clean = [_row(10_000, None), _row(20_000, 0)]
    assert se.mus(clean, 100_000, 3.0, 0.95, tolerable=300_000)["verdict"] == se.V_NONE
    assert se.mus(clean, 100_000, 3.0, 0.95, tolerable=299_000)["verdict"] == se.V_UPPER_OVER     # 기본 정밀도만으로 넘는다
    # 예상 왜곡을 넣어 간격을 줄이면 작은 왜곡이 있어도 상한이 허용왜곡표시 안에 든다
    p = sampling.plan(10_000_000, 100, 1_000_000, "높음", expected=100_000)
    small = [_row(50_000, 500), _row(80_000, None)]
    x = se.mus(small, p["interval"], p["factor"], p["confidence"], tolerable=1_000_000)
    assert x["verdict"] == se.V_WITHIN
    pending = [dict(_row(10_000, None), done=False)]
    assert se.mus(pending, 100_000, 3.0, 0.95, tolerable=300_000)["verdict"] == se.V_PENDING
    nodiff = [dict(_row(10_000, None), nodiff=True)]
    assert se.mus(nodiff, 100_000, 3.0, 0.95, tolerable=300_000)["verdict"] == se.V_NODIFF
    big = [_row(400_000, 350_000, key=True)]
    assert se.mus(big, 100_000, 3.0, 0.95, tolerable=300_000)["verdict"] == se.V_EST_OVER
    an = se.mus(clean, 100_000, 1.0, None, anomaly=-50_000, tolerable=200_000)
    assert an["upper_under"] == pytest.approx(150_000) and an["estimate"] == pytest.approx(-50_000)


def test_key_threshold_below_interval():
    """고액 기준을 간격보다 낮추면 그 사이 항목은 투영하지 않고 그대로 더한다."""
    rows = [_row(60_000, 6_000)]
    assert se.mus(rows, 100_000, 3.0, 0.95)["projected_over"] == pytest.approx(10_000)
    assert se.mus(rows, 100_000, 3.0, 0.95, key=50_000)["projected_over"] == pytest.approx(6_000)


def test_expansion_factor_and_plan():
    assert sampling.expansion_factor(0.95) == pytest.approx(1.6)
    assert sampling.expansion_factor(0.90) == pytest.approx(1.5)
    assert sampling.expansion_factor(0.925) == pytest.approx(1.55)
    assert sampling.expansion_factor(0.999) == pytest.approx(1.9)
    p = sampling.plan(10_000_000, 100, 1_000_000, "높음", expected=100_000)
    assert p["ef"] == pytest.approx(1.6) and p["interval"] == pytest.approx((1_000_000 - 160_000) / 3.0)
    assert sampling.plan(10_000_000, 100, 1_000_000, "높음")["interval"] == pytest.approx(1_000_000 / 3.0)
    with pytest.raises(ValueError):
        sampling.plan(10_000_000, 100, 1_000_000, "높음", expected=700_000)


def test_systematic_and_allocate():
    items = [(f"k{i}", 1000 + i) for i in range(100)]
    a = sampling.systematic(items, 10, 11)
    b = sampling.systematic(items, 10, 11)
    assert a["selected"] == b["selected"] and a["size"] == 10 and a["step"] == 10
    idx = [int(r["key"][1:]) for r in a["selected"]]
    assert all(y - x == 10 for x, y in zip(idx, idx[1:]))
    assert sampling.allocate(10, [5, 3, 2]) == [5, 3, 2]
    assert sampling.allocate(4, [100, 1, 1]) == [2, 1, 1]
    assert sampling.allocate(2, [0, 0]) == [0, 0]


def test_ratio_and_specific():
    rows = [_row(1_000, 100, stratum="A"), _row(1_000, None, stratum="A"), _row(500, -50, stratum="B"),
            _row(9_000, 900, key=True, stratum="A")]
    x = se.ratio(rows, {"A": 20_000, "B": 5_000}, tolerable=2_000)
    assert x["strata"]["A"]["proj_over"] == pytest.approx(100 / 2_000 * 20_000)
    assert x["projected_over"] == pytest.approx(1_000 + 900)
    assert x["projected_under"] == pytest.approx(50 / 500 * 5_000)
    assert x["verdict"] == se.V_R_WITHIN
    assert se.ratio(rows, {"A": 20_000, "B": 5_000}, tolerable=1_500)["verdict"] == se.V_R_OVER
    s = se.specific(rows, 100_000, tolerable=50_000)
    assert s["rest"] == pytest.approx(100_000 - 11_500) and s["verdict"] == se.V_S_REST
    assert se.specific(rows, 20_000, tolerable=50_000)["verdict"] == se.V_S_OK
