# -*- coding: utf-8 -*-
"""퇴직소득세 엔진 테스트 — 연분연승법 (소득법 §48·§55).

골든: 퇴직급여 50,000,000·근속 10년 → 산출세액 680,000 (원문 표 손검산).
"""
import db
from yearend_param import seed_2025
from retirement_tax import settle, 근속연수, RetirementTax, _근속연수공제, _환산급여공제
from withholding_engine import InfoRequest


def _conn():
    conn = db.connect(":memory:"); seed_2025(conn); return conn


# ---- 근속연수 ----

def test_근속연수_1년미만_절상():
    assert 근속연수("2024-03-15", "2024-09-01") == 1


def test_근속연수_만10년():
    assert 근속연수("2015-01-01", "2025-01-01") == 10       # 응당일 = 정확히 10년


def test_근속연수_10년_하루전_절상():
    assert 근속연수("2015-01-01", "2024-12-31") == 10       # 9년364일 → 절상 10


def test_근속연수_3년364일_절상():
    assert 근속연수("2020-03-15", "2024-03-14") == 4


# ---- 공제표(원문 §48) ----

def test_근속연수공제_원문():
    assert _근속연수공제(5) == 5_000_000                    # 100만×5
    assert _근속연수공제(10) == 15_000_000                  # 500만+200만×5
    assert _근속연수공제(20) == 40_000_000                  # 1500만+250만×10
    assert _근속연수공제(25) == 55_000_000                  # 4000만+300만×5


def test_환산급여공제_원문():
    assert _환산급여공제(8_000_000) == 8_000_000            # 전액
    assert _환산급여공제(42_000_000) == 28_400_000          # 800만+3400만×60%


# ---- 골든 케이스 ----

def test_골든_50M_10년():
    conn = _conn()
    # 2015-07-01~2025-06-30 = 9년364일 → 근속 10년, 귀속 2025
    r = settle(conn, 50_000_000, "2015-07-01", "2025-06-30", 사실={"연금계좌이체": False})
    assert isinstance(r, RetirementTax)
    assert r.근속연수 == 10
    assert r.근속연수공제 == 15_000_000
    assert r.환산급여 == 42_000_000
    assert r.환산급여공제 == 28_400_000
    assert r.과세표준 == 13_600_000
    assert r.환산산출세액 == 816_000                        # 13.6M×6%
    assert r.산출세액 == 680_000                            # 816,000÷12×10
    assert r.지방소득세 == 68_000


# ---- 과세이연·임원 ----

def test_과세이연_여부_InfoRequest():
    conn = _conn()
    r = settle(conn, 50_000_000, "2015-01-01", "2024-12-31")   # 사실 없음
    assert isinstance(r, InfoRequest)
    assert "연금계좌" in r.필요사실[0]


def test_과세이연시_원천징수0():
    conn = _conn()
    r = settle(conn, 50_000_000, "2015-01-01", "2024-12-31", 사실={"연금계좌이체": True})
    assert r.산출세액 == 0 and r.지방소득세 == 0
    assert r.명세["과세이연"] is True


def test_임원_한도초과_InfoRequest():
    conn = _conn()
    r = settle(conn, 200_000_000, "2015-01-01", "2024-12-31",
               사실={"연금계좌이체": False, "임원": True})
    assert isinstance(r, InfoRequest)
    assert "한도초과" in r.필요사실[0]


def test_퇴직급여_공제미달_전액공제():
    conn = _conn()
    # 근속 10년 공제 1,500만 > 퇴직급여 1,000만 → §48② 전액공제, 과표 0
    r = settle(conn, 10_000_000, "2015-01-01", "2024-12-31", 사실={"연금계좌이체": False})
    assert r.과세표준 == 0 and r.산출세액 == 0
