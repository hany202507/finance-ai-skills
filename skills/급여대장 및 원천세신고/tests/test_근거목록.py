# -*- coding: utf-8 -*-
"""근거목록(references/근거목록.json)의 값과 엔진 코드의 값이 같은지 본다.

값을 바꿀 때는 엔진 코드와 근거목록을 함께 고친다. 한쪽만 고치면 이 시험이 멈춘다.
"""
import csv
import datetime
import json
import os
import sys
from pathlib import Path

import pytest

스킬 = Path(__file__).resolve().parents[1]
for 하위 in ("원천세", "입퇴사처리", "원천징수이행상황신고서"):
    sys.path.insert(0, str(스킬 / "모듈" / 하위 / "scripts"))

from datetime import date  # noqa: E402

import db                  # noqa: E402
import event_obligations   # noqa: E402
import insurance_engine    # noqa: E402
import retirement_tax      # noqa: E402
import simple_tax_table    # noqa: E402
import tax_credit          # noqa: E402
import withholding_engine  # noqa: E402
import yearend_param       # noqa: E402
import 기한                # noqa: E402
import 입퇴사              # noqa: E402
import 집계                # noqa: E402

목록 = json.loads((스킬 / "references" / "근거목록.json").read_text(encoding="utf-8"))
등급들 = {"★★★", "★★☆", "☆"}


def 요율(날짜):
    return insurance_engine._rates_for(날짜)


def 규칙(항목, 제도):
    with open(스킬 / "examples/샘플회사/받은자료/pay_item_rule.csv", encoding="utf-8-sig", newline="") as f:
        r = next(x for x in csv.DictReader(f) if x["항목코드"] == 항목 and x["제도"] == 제도)
    return {"구분": r["구분"], "한도금액": int(r["한도금액"]) if r["한도금액"] else None, "한도단위": r["한도단위"]}


def _간이conn():
    c = db.connect(":memory:")
    simple_tax_table.load_official(c, os.path.join(simple_tax_table.DATA_DIR, "gani_2026-03-01.json"))
    return c


def 간이(월급여, 가족):
    return simple_tax_table.lookup(_간이conn(), 월급여, 가족, on_date="2026-07-31")


def 간이자녀(n):
    return simple_tax_table.자녀세액공제(_간이conn(), n, "2026-07-31")


def 간이판():
    return json.loads(Path(simple_tax_table.DATA_DIR, "gani_2026-03-01.json").read_text(encoding="utf-8"))["eff_from"]


def param(키):
    return dict((k, v) for k, v, _ in yearend_param.PARAM_2025)[키]


def 소스(상대경로):
    return (스킬 / 상대경로).read_text(encoding="utf-8")


def 레이아웃():
    return json.loads(소스("모듈/원천세전자파일/references/layout_c103900.json"))


@pytest.mark.parametrize("값", 목록["값"], ids=[v["id"] for v in 목록["값"]])
def test_근거목록_값과_코드가_같다(값):
    assert eval(값["코드"]) == 값["값"], f"{값['id']}: 근거목록 {값['값']} · 코드 {eval(값['코드'])}"


def test_값마다_근거_등급_쓰는곳이_있다():
    아이디 = [v["id"] for v in 목록["값"]]
    assert len(아이디) == len(set(아이디))
    for v in 목록["값"]:
        assert v["근거"] and all(k in 목록["근거"] for k in v["근거"]), v["id"]
        assert v["등급"] in 등급들, v["id"]
        assert (스킬 / v["쓰는곳"].split(" ")[0]).exists(), v["쓰는곳"]


def test_근거마다_판_기록이_있다():
    for 키, g in 목록["근거"].items():
        assert g["출처"] in ("TaxDoctor", "korean-law", "사람 확인"), 키
        datetime.date.fromisoformat(g["확인일"])
        if g["출처"] == "사람 확인":
            assert g["메모"], 키
            continue
        assert g["스냅샷"] and g["시행일"], 키
        datetime.date.fromisoformat(g["시행일"])
        if g["출처"] == "TaxDoctor" and g["도구"] in ("get_article", "get_reference_article"):
            assert g["스냅샷"].startswith(("moleg-eflaw:", "ref-eflaw:")), 키


def test_쓰지_않는_근거가_없다():
    쓰는 = {k for v in 목록["값"] for k in v["근거"]}
    assert set(목록["근거"]) == 쓰는
