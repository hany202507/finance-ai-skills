# -*- coding: utf-8 -*-
"""계획 2 T17 규칙: 신고기한(소득세법 제105조①, 제110조①)."""
import pytest

from yangdo import keys
from yangdo import ruleset


@pytest.fixture(scope="module")
def rs():
    return ruleset.load()


def test_deadline_rule_values(rs):
    for on in ("2025-01-01", "2026-11-20", "2027-12-31"):
        assert rs.value("신고기한.예정.개월", on) == 2
        assert rs.value("신고기한.확정.월", on) == 5
        assert rs.value("신고기한.확정.일", on) == 31
    assert {"신고기한.예정.개월", "신고기한.확정.월", "신고기한.확정.일"} <= set(keys.VALUE_KEYS)


def test_deadline_rule_citations(rs):
    예 = rs.cite("신고기한.예정.개월", "2026-11-20")
    assert [(c["법령"], c["조항"]) for c in 예] == [("소득세법", "제105조①1호")]
    assert "그 양도일이 속하는 달의 말일부터 2개월" in 예[0]["발췌"][0]
    확 = rs.cite("신고기한.확정.일", "2026-11-20")
    assert [(c["법령"], c["조항"]) for c in 확] == [("소득세법", "제110조①")]
    assert "5월 1일부터 5월 31일까지" in 확[0]["발췌"][0]
    assert 예[0]["URL"].startswith("https://www.law.go.kr/")
