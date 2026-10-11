# -*- coding: utf-8 -*-
import hashlib
import json
import os

import filers
from cases import CASES
from yangdo import engine

SKILL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _sha(p):
    with open(p, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def test_form_originals_match_registry():
    with open(os.path.join(SKILL, "forms", "서식판.json"), encoding="utf-8") as f:
        reg = json.load(f)
    for v in reg["서식"].values():
        assert _sha(os.path.join(SKILL, "forms", v["파일"])) == v["sha256"]


def test_case_s1_matches_hand_calculation():
    r = engine.calculate(CASES["S1"], today="2026-10-11")
    assert r["상태"] == "완료", r["질문"] or r["다루지않음"]
    c = r["계산"]["자산"][0]["계산"]
    assert (c["양도차익"], c["과세양도차익"], c["장특공"], c["과세표준"], c["산출세액"], c["지방소득세"]) == \
        (1169200000, 389733333, 233839999, 153393334, 38349466, 3834946)


def test_filer_rrn_checksums_are_valid():
    w = [2, 3, 4, 5, 6, 7, 8, 9, 2, 3, 4, 5]
    for f in filers.FILERS.values():
        for n in [f["신고인"]["주민등록번호"]] + [b["번호"] for b in f["양수인"]]:
            assert (11 - sum(int(a) * b for a, b in zip(n[:12], w)) % 11) % 10 == int(n[12])
