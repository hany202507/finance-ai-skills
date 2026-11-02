# -*- coding: utf-8 -*-
"""근로소득 간이세액표 — 소득세법 시행령 별표2 원문(조견표) 대사 테스트.

원문: 국세청 조견표 2026.03.01판 / 2024.03.01판 (tools/parse_gani_xlsx.py 파싱).
핵심: 646구간 세액은 두 판 동일. **자녀공제만 개정으로 갈림** → 효력일자 검증.
"""
import os

import pytest

import db
from simple_tax_table import (lookup, 자녀세액공제, seed_row, load_official,
                              DATA_DIR, 만원)

J2026 = os.path.join(DATA_DIR, "gani_2026-03-01.json")
J2024 = os.path.join(DATA_DIR, "gani_2024-03-01.json")


def _conn(both=False):
    conn = db.connect(":memory:")
    if both:
        load_official(conn, J2024, eff_to="2026-02-28")
        load_official(conn, J2026)
    else:
        load_official(conn, J2026)
    return conn


# ---- 적재 ----

def test_official_load_건수():
    conn = db.connect(":memory:")
    n = load_official(conn, J2026)
    assert n == 646 * 11              # 646구간 × 공제대상가족수 11


# ---- 표 원문값 ----

def test_별표2_원문값_하한():
    conn = _conn()
    assert lookup(conn, 770_000, 1, on_date="2026-07-25") == 0     # '-' → 0


def test_별표2_원문_10000천원_기준액():
    conn = _conn()
    # 조견표 '10,000천원' 행: 가족1 = 1,507,400 / 가족11 = 960,840
    assert lookup(conn, 만원, 1, on_date="2026-07-25") == 1_507_400
    assert lookup(conn, 만원, 11, on_date="2026-07-25") == 960_840


# ---- 자녀공제 효력일자 (이 파일들의 유일한 개정점) ----

def test_자녀공제_2026판():
    conn = _conn()
    assert 자녀세액공제(conn, 1, "2026-07-25") == 20_830
    assert 자녀세액공제(conn, 2, "2026-07-25") == 45_830
    assert 자녀세액공제(conn, 3, "2026-07-25") == 45_830 + 33_330


def test_자녀공제_2024판_소급():
    conn = _conn(both=True)
    # 2026.2월 급여 = 구판(12,500/29,160/+25,000)
    assert 자녀세액공제(conn, 1, "2026-02-25") == 12_500
    assert 자녀세액공제(conn, 3, "2026-02-25") == 29_160 + 25_000
    # 2026.3월부터 신판
    assert 자녀세액공제(conn, 1, "2026-03-25") == 20_830


def test_같은급여_시행일따라_세액다름():
    conn = _conn(both=True)
    구 = lookup(conn, 3_000_000, 3, on_date="2026-02-25", 자녀8_20세수=1)
    신 = lookup(conn, 3_000_000, 3, on_date="2026-03-25", 자녀8_20세수=1)
    assert 구 - 신 == 20_830 - 12_500      # 자녀공제 차이만큼


# ---- 별표2 §6 고액 산식 (구간 이음매 = 자기정합 검증) ----

def test_고액산식_14000천원_이음매():
    conn = _conn()
    base = 1_507_400
    # 14,000천원 = base + 4,000,000×98%×35% + 25,000 = base + 1,397,000
    assert lookup(conn, 14_000_000, 1, on_date="2026-07-25") == base + 1_397_000


def test_고액산식_28000천원_이음매():
    conn = _conn()
    base = 1_507_400
    # base + 1,397,000 + 14,000,000×98%×38% = base + 6,610,600
    assert lookup(conn, 28_000_000, 1, on_date="2026-07-25") == base + 6_610_600


def test_고액산식_45000_87000_이음매():
    conn = _conn()
    base = 1_507_400
    assert lookup(conn, 45_000_000, 1, on_date="2026-07-25") == base + 13_394_600
    assert lookup(conn, 87_000_000, 1, on_date="2026-07-25") == base + 31_034_600


def test_고액산식_최고구간():
    conn = _conn()
    base = 1_507_400
    # 100,000천원 → base + 31,034,600 + 13,000,000×45%
    assert lookup(conn, 100_000_000, 1, on_date="2026-07-25") == base + 31_034_600 + 5_850_000


def test_만원_초과_25000원_점프():
    conn = _conn()
    # 별표2 §6 문언 그대로: 10,000천원 초과 순간 +25,000 상수
    assert lookup(conn, 만원, 1, on_date="2026-07-25") == 1_507_400
    assert lookup(conn, 만원 + 1_000, 1, on_date="2026-07-25") == 1_507_400 + 25_000 + 343


# ---- 규칙 ----

def test_자녀공제_차감_음수는0():
    conn = _conn()
    # 2,500천원 가족3 표세액 < 자녀1명 공제(20,830) → 0
    assert lookup(conn, 2_500_000, 3, on_date="2026-07-25", 자녀8_20세수=1) >= 0
    assert lookup(conn, 800_000, 2, on_date="2026-07-25", 자녀8_20세수=3) == 0


def test_11명초과_별표2_4호():
    conn = db.connect(":memory:")
    seed_row(conn, pay_min=3_000_000, pay_max=3_005_000, dependents=10, tax=5_000)
    seed_row(conn, pay_min=3_000_000, pay_max=3_005_000, dependents=11, tax=3_000)
    conn.execute("INSERT INTO ref_child_credit(one,two,extra,eff_from) "
                 "VALUES(20830,45830,33330,'2024-03-01')")
    conn.commit()
    # 12명 → 3000 − (5000−3000)×1 = 1000
    assert lookup(conn, 3_000_000, 12, on_date="2026-07-25") == 1_000
    # 13명 → 3000 − 2000×2 < 0 → 0
    assert lookup(conn, 3_000_000, 13, on_date="2026-07-25") == 0


def test_ratio_80():
    conn = _conn()
    full = lookup(conn, 3_000_000, 1, on_date="2026-07-25")
    assert lookup(conn, 3_000_000, 1, on_date="2026-07-25", 비율=80) == int(full * 80 / 100)


def test_적재전_조회는_명시적_실패():
    conn = db.connect(":memory:")
    with pytest.raises(LookupError):
        lookup(conn, 3_000_000, 1, on_date="2026-07-25")
