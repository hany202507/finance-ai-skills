"""ctax ar 6회차 시험. 부동산임대업 주업 등 법인의 수입 요건(법인세법 시행령 제42조 제2항 제2호). 합성 장부만 쓴다."""
from __future__ import annotations

from ctax.ar import engine
from ctax.tests.test_ar import acc, ledger, prior, run
from ctax.tests.test_ar_fx1 import rules, with_accounts


def _builder(led, pr=None):
    return engine.Builder(led, [], pr if pr is not None else prior(), {"company": "가상회사", "fy": "2025"})


def test_rental_test_adds_non_operating_interest_and_dividend_to_revenue():
    # 매출 9억, 영업외 이자 6억 · 배당 4억 → (6 + 4) ÷ (9 + 6 + 4) = 52.6%
    led = with_accounts(acc("901", "이자수익", "수익", 600_000_000, 0), acc("903", "배당금수익", "수익", 400_000_000, 0),
                        drop=("901",))
    r = _builder(led).rental_test()
    assert r["total"] == 1_000_000_000 and r["revenue"] == 900_000_000 and r["added"] == 1_000_000_000
    assert r["base"] == 1_900_000_000 and 0.52 < r["share"] < 0.53
    issue = rules(run(led))["rental_main"]
    assert issue["accounts"] == ["901", "903"]
    assert any("이자수익 600,000,000원 · 배당금수익 400,000,000원, 합계 1,000,000,000원" in b for b in issue["basis"])
    assert any("더한 1,900,000,000원의 53%" in b for b in issue["basis"])
    assert any("상시근로자 수가 5명 미만" in q for q in issue["questions"])


def test_rental_income_inside_revenue_is_not_added_twice():
    # 임대료 수입이 매출 계정(411)이면 분모에 다시 더하지 않는다: 5억 ÷ (9억 + 5억)
    led = with_accounts(acc("411", "임대료수입", "수익", 500_000_000, 0), drop=("901",))
    r = _builder(led).rental_test()
    assert r["added"] == 0 and r["base"] == 1_400_000_000 and r["total"] == 500_000_000
    assert "rental_main" not in rules(run(led))


def test_small_interest_does_not_raise_rental_issue():
    led = with_accounts(acc("901", "이자수익", "수익", 3_000_000, 0), drop=("901",))
    ar = run(led)
    assert "rental_main" not in rules(ar)
    g = next(x for x in ar["guide"] if x["id"] == "1-2")
    assert any("이자수익 3,000,000원" in f for f in g["facts"])


def test_top_holder_fact_reads_prior_54_rows():
    pr = prior()
    pr["rows"] = {"54": [{"번호": 3, "기말_지분율": "60"}, {"번호": 4, "기말_지분율": "40"}, {"번호": 5, "기말_지분율": ""}]}
    led = with_accounts(acc("411", "임대료수입", "수익", 5_000_000_000, 0))
    issue = rules(run(led, None, pr))["rental_main"]
    assert any("지분율은 60%입니다" in b and "50%를 넘게" in b for b in issue["basis"])
    assert _builder(ledger()).top_holder_fact() is None
