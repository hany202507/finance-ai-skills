# -*- coding: utf-8 -*-
"""비거주자 조세조약 제한세율 — 조약 원문 대사 테스트.

한·미 조세협약(조약 제693호) §14: (1) 일반 사용료 15% / (2) 문화적 저작권·영화·방송필름 10%.
"""
from treaty_rates import 사용료_일반, 사용료_문화
from withholding_engine import (judge, PaymentInput, 소득유형,
                                 WithholdingResult, InfoRequest)


def _payee():
    return {"resident_type": "비거주자"}


def _사실(**kw):
    base = {"거주지국": "US", "수익적소유자": True, "거주자증명서": True}
    base.update(kw)
    return base


def test_한미_일반사용료_15퍼센트():
    # 협약 §14(1): 특허·기술 등 일반 사용료 15%
    p = PaymentInput(소득유형.사용료, 1_000_000, "2026-07", _payee(),
                     사실=_사실(사용료구분=사용료_일반))
    r = judge(p, "2026-07-25")
    assert isinstance(r, WithholdingResult)
    assert r.소득세 == 150_000 and r.지방소득세 == 15_000
    assert "조세조약" in r.적용룰


def test_한미_문화적저작권_10퍼센트():
    # 협약 §14(2): 저작권·영화/방송필름 10% — 일반율과 갈린다
    p = PaymentInput(소득유형.사용료, 1_000_000, "2026-07", _payee(),
                     사실=_사실(사용료구분=사용료_문화))
    r = judge(p, "2026-07-25")
    assert r.소득세 == 100_000 and r.지방소득세 == 10_000


def test_사용료종류_모르면_InfoRequest():
    """추정 금지 — 종류로 세율이 갈리면 물어서 확정한다."""
    p = PaymentInput(소득유형.사용료, 1_000_000, "2026-07", _payee(), 사실=_사실())
    r = judge(p, "2026-07-25")
    assert isinstance(r, InfoRequest)
    assert any("사용료 종류" in s for s in r.필요사실)


def test_거주자증명서_없으면_기본율():
    p = PaymentInput(소득유형.사용료, 1_000_000, "2026-07", _payee(),
                     사실=_사실(거주자증명서=False, 사용료구분=사용료_일반))
    r = judge(p, "2026-07-25")
    assert r.소득세 == 200_000                      # 국내세법 기본 20%
    assert "경정청구" in r.근거                      # 회복 경로 안내


def test_수익적소유자_아니면_기본율():
    p = PaymentInput(소득유형.사용료, 1_000_000, "2026-07", _payee(),
                     사실=_사실(수익적소유자=False, 사용료구분=사용료_일반))
    r = judge(p, "2026-07-25")
    assert r.소득세 == 200_000


def test_미대사국은_기본율_과소원천징수_방지():
    """조약 원문 미대사국은 추측 세율 대신 기본율 — 과소원천징수 리스크 차단."""
    p = PaymentInput(소득유형.사용료, 1_000_000, "2026-07", _payee(),
                     사실=_사실(거주지국="BR"))
    r = judge(p, "2026-07-25")
    assert r.소득세 == 200_000


def test_비거주자_기타소득_기본율():
    p = PaymentInput(소득유형.기타, 1_000_000, "2026-07", _payee(), 사실=_사실())
    r = judge(p, "2026-07-25")
    assert r.소득세 == 200_000
