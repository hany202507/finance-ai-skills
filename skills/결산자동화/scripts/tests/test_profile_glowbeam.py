# -*- coding: utf-8 -*-
import os, sys, json, io
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))


def test_profile_covers_bank_labels_and_card_pool():
    import profile_glowbeam as P, glowbeam_raw as G
    engine_known = {"매출채권회수", "급여", "신용카드대금", "4대보험", "보험료", "이자비용",
                    "세금과공과", "이자수익", "부가세납부"}
    for _, lab, _ in G.BANK_LABEL:
        assert lab in engine_known or lab in P.은행라벨_규칙, lab
    assert len(P.카드가맹점_계정) == 23
    assert all(v[2] in ("공제", "불공제") for v in P.카드가맹점_계정.values())


def test_engine_by_period():
    from close_engine import Engine

    class Dummy:
        pass
    e = Dummy(); e.period = "2026-06"
    assert Engine._by_period(e, {"2026-05": 1, "2026-06": 2}) == 2
    assert Engine._by_period(e, 7) == 7
