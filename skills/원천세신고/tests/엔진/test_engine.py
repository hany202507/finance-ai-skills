# -*- coding: utf-8 -*-
"""판정 코어 테스트 — 소득유형별 결정론 + InfoRequest."""
import db
from simple_tax_table import load_official
from withholding_engine import (judge, PaymentInput, 소득유형,
                                 WithholdingResult, InfoRequest)

거주자 = {"resident_type": "거주자"}


def test_사업소득_3_3():
    p = PaymentInput(소득유형.사업, 1_000_000, "2026-07", 거주자)
    r = judge(p, "2026-07-25")
    assert isinstance(r, WithholdingResult)
    assert r.소득세 == 30_000 and r.지방소득세 == 3_000


def test_일용_소액부징수():
    p = PaymentInput(소득유형.일용, 150_000, "2026-07", 거주자, 사실={"일급": 150_000})
    r = judge(p, "2026-07-25")
    assert r.소득세 == 0


def test_일용_과세():
    # 일급 200,000, 3일: (200000-150000)*2.7%=1350 ≥1000, ×3 = 4050
    p = PaymentInput(소득유형.일용, 600_000, "2026-07", 거주자,
                     사실={"일급": 200_000, "일수": 3})
    r = judge(p, "2026-07-25")
    assert r.소득세 == 4_050 and r.지방소득세 == 400   # 지방세 10원 미만 버림


def test_기타소득_경비율_60():
    p = PaymentInput(소득유형.기타, 1_000_000, "2026-07", 거주자, 기타소득종류="강연료")
    r = judge(p, "2026-07-25")
    assert r.소득세 == 80_000 and r.지방소득세 == 8_000


def test_기타소득_과세최저():
    # 60만 강연료 → 경비 36만 → 소득금액 24만? >5만 과세. 6.25만 → 경비 3.75만 → 소득 2.5만 ≤5만 → 0
    p = PaymentInput(소득유형.기타, 62_500, "2026-07", 거주자, 기타소득종류="강연료")
    r = judge(p, "2026-07-25")
    assert r.소득세 == 0 and r.지방소득세 == 0


def test_기타소득_실제경비만_InfoRequest():
    p = PaymentInput(소득유형.기타, 1_000_000, "2026-07", 거주자, 기타소득종류="위약금")
    r = judge(p, "2026-07-25")
    assert isinstance(r, InfoRequest)


def test_근로소득_간이세액표():
    # 별표2 원문: 2,980~2,990천원 가족3 = 31,120. 자녀1명 공제 20,830 → 10,290
    conn = db.connect(":memory:")
    load_official(conn)
    p = PaymentInput(소득유형.근로, 2_980_000, "2026-07",
                     {"resident_type": "거주자", "공제대상가족수": 3, "자녀8_20세수": 1})
    r = judge(p, "2026-07-25", conn)
    assert r.소득세 == 10_290 and r.지방소득세 == 1_020  # 10원 버림


def test_근로소득_비과세_제외후_조회():
    # 지급 3,180,000 중 비과세 200,000 → 과세 2,980,000 → 가족1 72,210
    conn = db.connect(":memory:")
    load_official(conn)
    p = PaymentInput(소득유형.근로, 3_180_000, "2026-07",
                     {"resident_type": "거주자", "공제대상가족수": 1}, 비과세=200_000)
    r = judge(p, "2026-07-25", conn)
    assert r.소득세 == 72_210


def test_비거주자_사실없으면_InfoRequest():
    p = PaymentInput(소득유형.사용료, 1_000_000, "2026-07", {"resident_type": "비거주자"})
    r = judge(p, "2026-07-25")
    assert isinstance(r, InfoRequest)
    assert any("거주지국" in s for s in r.필요사실)


def test_사용료_거주자_구분없으면_InfoRequest():
    p = PaymentInput(소득유형.사용료, 1_000_000, "2026-07", 거주자)
    r = judge(p, "2026-07-25")
    assert isinstance(r, InfoRequest)
