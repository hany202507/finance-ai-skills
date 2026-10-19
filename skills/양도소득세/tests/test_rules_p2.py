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


# ---- 계획 2b G1b: 개인지방소득세 전자신고세액공제, 분납 대상 세액 ----

def test_local_efile_credit_preliminary_is_2000(rs):
    """양도소득에 대한 개인지방소득세 예정신고를 직접 전자신고하면 2천원을 뺀다(지방세특례제한법 제167조의3①, 시행령 제116조의2)."""
    for on in ("2025-01-01", "2026-12-15", "2027-05-20"):
        assert rs.value("지방.전자신고세액공제.예정", on) == 2000
    assert rs.entry("지방.전자신고세액공제.예정", "2026-12-15")["기준일"] == "신고일"
    cites = rs.cite("지방.전자신고세액공제.예정", "2026-12-15")
    assert [(c["법령"], c["조항"]) for c in cites] == [("지방세특례제한법", "제167조의3①"), ("지방세특례제한법 시행령", "제116조의2①②")]
    assert any("예정신고하는 양도소득에 대한 개인지방소득세" in x for x in cites[1]["발췌"])
    assert "지방.전자신고세액공제.예정" in keys.VALUE_KEYS


def test_no_local_efile_credit_key_for_final_return(rs):
    """시행령 제116조의2①은 양도소득은 예정신고만 정한다. 확정신고 키는 만들지 않는다."""
    assert "지방.전자신고세액공제.확정" not in keys.VALUE_KEYS
    with pytest.raises(ruleset.RuleError):
        rs.value("지방.전자신고세액공제.확정", "2027-05-20")


def test_installment_base_citation_excludes_penalty(rs):
    """분납할 수 있는 세액은 예정신고납부·확정신고납부로 납부할 세액이다. 두 조는 산출세액에서 감면세액과 세액공제액을 뺀 세액을
    납부하도록 정하고 가산세를 넣지 않는다. 신고값과 서식 검산이 분납 한도를 가산세를 뺀 세액으로 세는 근거다."""
    assert "판정.분납대상세액" in keys.CITE_KEYS
    cites = rs.cite("판정.분납대상세액", "2026-11-20")
    assert [(c["법령"], c["조항"]) for c in cites] == [("소득세법", "제112조"), ("소득세법", "제106조①"), ("소득세법", "제111조①")]
    assert "제106조 또는 제111조에 따라 납부할 세액이 각각 1천만원을 초과하는 자" in cites[0]["발췌"]
    assert "양도소득 산출세액에서 감면세액과 세액공제액을 공제한 금액" in cites[2]["발췌"]
