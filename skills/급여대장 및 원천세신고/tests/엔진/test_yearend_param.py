# -*- coding: utf-8 -*-
"""연말정산 파라미터·산식 테스트 (2025 귀속, 원문+웹 교차)."""
import db
from yearend_param import seed_2025, 근로소득공제, 산출세액, get_param


def test_근로소득공제_구간():
    # 소득법 §47
    assert 근로소득공제(4_000_000) == 2_800_000            # 400만×70%
    assert 근로소득공제(10_000_000) == 5_500_000           # 350만+500만×40%
    assert 근로소득공제(30_000_000) == 9_750_000           # 750만+1500만×15%
    assert 근로소득공제(48_000_000) == 12_150_000          # 1200만+300만×5%
    assert 근로소득공제(200_000_000) == 16_750_000         # 1475만+1억×2%


def test_근로소득공제_한도_2000만():
    assert 근로소득공제(500_000_000) == 20_000_000


def test_산출세액_누진():
    conn = db.connect(":memory:"); seed_2025(conn)
    assert 산출세액(12_000_000, conn, 2025) == 720_000              # 6%
    assert 산출세액(30_000_000, conn, 2025) == 3_240_000           # 15%−126만
    assert 산출세액(60_000_000, conn, 2025) == 60_000_000*0.24 - 5_760_000
    assert 산출세액(0, conn, 2025) == 0


def test_산출세액_최고구간():
    conn = db.connect(":memory:"); seed_2025(conn)
    # 12억 → 45%−6594만
    assert 산출세액(1_200_000_000, conn, 2025) == int(1_200_000_000*0.45) - 65_940_000


def test_get_param():
    conn = db.connect(":memory:"); seed_2025(conn)
    assert get_param(conn, 2025, "기본공제_1인") == 1_500_000
    assert get_param(conn, 2025, "소득공제_종합한도") == 25_000_000
