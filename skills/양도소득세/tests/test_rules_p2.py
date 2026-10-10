# -*- coding: utf-8 -*-
"""계획 2 T4 규칙: 분납(소득세법 제112조, 시행령 제175조), 전자신고세액공제(조세특례제한법 제104조의8, 시행령 제104조의5)."""
from decimal import Decimal

import pytest

from yangdo import keys
from yangdo import ruleset


@pytest.fixture(scope="module")
def rs():
    return ruleset.load()


def test_installment_rules(rs):
    for on in ("2025-01-01", "2026-11-20", "2027-12-31"):
        assert rs.value("분납.기준금액", on) == 10000000
        assert rs.value("분납.상한기준", on) == 20000000
        assert rs.value("분납.상한율", on) == Decimal("0.5")
    cites = rs.cite("분납.기준금액", "2026-11-20")
    assert [(c["법령"], c["조항"]) for c in cites] == [("소득세법", "제112조"), ("소득세법 시행령", "제175조1호")]
    assert "납부기한이 지난 후 2개월 이내에 분할납부할 수 있다" in cites[0]["발췌"]


def test_efile_credit_rule_has_citation(rs):
    cites = rs.cite("전자신고세액공제.예정", "2026-11-20")
    assert cites and cites[0]["법령"] == "조세특례제한법"
    assert cites[0]["조항"] == "제104조의8①"
    assert ("조세특례제한법 시행령", "제104조의5①②2호") in [(c["법령"], c["조항"]) for c in cites]
    assert ("조세특례제한법 시행령", "부칙(제36127호)") in [(c["법령"], c["조항"]) for c in cites]


def test_efile_credit_preliminary_is_20000_before_and_after_2026_amendment(rs):
    # 2026-02-27 개정 전에는 제2항 본문의 2만원, 개정 뒤에는 제2항 제2호의 2만원이다
    assert rs.value("전자신고세액공제.예정", "2026-02-26") == 20000
    assert rs.value("전자신고세액공제.예정", "2026-02-27") == 20000
    old = [c["조항"] for c in rs.cite("전자신고세액공제.예정", "2026-02-26")]
    new = [c["조항"] for c in rs.cite("전자신고세액공제.예정", "2026-02-27")]
    assert old == ["제104조의8①", "제104조의5①②"]
    assert new == ["제104조의8①", "제104조의5①②2호", "부칙(제36127호)"]
    assert rs.entry("전자신고세액공제.예정", "2026-12-15")["기준일"] == "신고일"


def test_no_efile_credit_key_for_final_return(rs):
    """시행령 제104조의5①은 양도소득 예정신고(제105조)만 정한다. 확정신고(제110조) 키는 만들지 않는다."""
    assert "전자신고세액공제.확정" not in keys.VALUE_KEYS
    with pytest.raises(ruleset.RuleError):
        rs.value("전자신고세액공제.확정", "2027-05-20")
