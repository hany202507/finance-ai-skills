# -*- coding: utf-8 -*-
import json
import os

import import_questions as IQ
from yangdo import QUESTIONS_PATH


def test_keys_of():
    assert IQ.keys_of("자산[].소재지{시도,시군구,읍면동}") == ["자산[].소재지"]
    assert IQ.keys_of("자산[].취득.계약일, 자산[].취득.계약금지급일") == ["자산[].취득.계약일", "자산[].취득.계약금지급일"]
    assert IQ.keys_of("자산[].기준시가{취득:{토지,건물,주택},양도:{토지,건물,주택}}") == ["자산[].기준시가"]
    assert IQ.keys_of("세대.주택목록[신규].계약일, 계약금지급일") == ["세대.주택목록[신규].계약일", "세대.주택목록[신규].계약금지급일"]
    assert IQ.keys_of("자산[].거주기간[[전입,전출]]") == ["자산[].거주기간"]
    assert IQ.keys_of("세대.주택목록[]{소유자,소재지}") == ["세대.주택목록"]
    assert IQ.keys_of("세대.주택목록[].양도당시기준시가") == ["세대.주택목록[].양도당시기준시가"]
    assert IQ.keys_of("자산[].필요경비.취득부대[]") == ["자산[].필요경비.취득부대"]
    assert IQ.keys_of("자산[].양도원인") == ["자산[].양도.원인"]
    assert IQ.keys_of("자산[].보유거주예외.일자") == ["자산[].보유거주예외일자"]
    assert IQ.keys_of("(서식 전용) 신고인") == []


MINI = {"이름": "t", "범위": "x", "엔진값": {"엔진.과세": "..."}, "섹션": [], "계획3목록": [], "다루지않음": [], "출처": [],
        "문항": [
            {"id": "P02", "질문": "q", "답형식": "선택", "선택지": IQ.SOURCE_OPTIONS_FOR_TEST["P02"],
             "보이는조건": "항상", "facts키": "자산[].종류", "범위": "계획1", "모를때처리": None},
            {"id": "A07", "질문": "q", "답형식": "예아니오", "선택지": None, "보이는조건": "항상",
             "facts키": "자산[].등기", "범위": "계획1", "모를때처리": None},
            {"id": "A08", "질문": "q", "답형식": "선택", "선택지": IQ.SOURCE_OPTIONS_FOR_TEST["A08"],
             "보이는조건": {"모두": [["A07", "==", "아니오"], ["P02", "in", [IQ.SOURCE_OPTIONS_FOR_TEST["P02"][0]]]]},
             "facts키": "자산[].미등기사유", "범위": "계획3 진입", "모를때처리": "계획 3 으로 넘긴다"}]}


def test_convert_mini():
    out = IQ.convert(MINI)
    q = {x["id"]: x for x in out["문항"]}
    assert q["P02"]["선택지"][0] == {"코드": "주택", "표시": IQ.SOURCE_OPTIONS_FOR_TEST["P02"][0]}
    assert q["A08"]["보이는조건"] == {"모두": [["A07", "==", False], ["P02", "in", ["주택"]]]}
    assert q["A08"]["범위"] == "계획5 진입" and "계획 5" in q["A08"]["모를때처리"]
    assert q["A07"]["키"] == ["자산[].등기"]
    assert "계획5목록" in out and "코드" in out


def load_out():
    with open(QUESTIONS_PATH, encoding="utf-8") as f:
        return json.load(f)


def test_committed_definition_is_consistent():
    out = load_out()
    qs = out["문항"]
    assert len(qs) == 73
    ids = {q["id"] for q in qs}
    roots = ("신고인.", "연간.", "세대.", "자산[].")

    def refs(c):
        if c == "항상":
            return
        for it in c.get("모두", []) + c.get("하나라도", []):
            if isinstance(it, dict):
                yield from refs(it)
            else:
                yield it[0]

    for q in qs:
        if q["선택지"]:
            assert all(set(o) == {"코드", "표시"} for o in q["선택지"]), q["id"]
        if q["범위"] != "서식단계":
            assert q["키"] and all(k.startswith(roots) for k in q["키"]), q["id"]
        for r in refs(q["보이는조건"]):
            assert r in ids or r in out["엔진값"], (q["id"], r)
        assert "계획3" not in q["범위"] and "계획 3" not in q["범위"]


def test_no_local_paths():
    with open(QUESTIONS_PATH, encoding="utf-8") as f:
        text = f.read()
    assert "C:\\" not in text and "Users" not in text and os.sep + "work" + os.sep not in text


def test_no_old_plan_number_left_and_legend_matches():
    out = load_out()
    text = json.dumps(out, ensure_ascii=False)
    assert "계획3" not in text and "계획 3" not in text
    legend = set(out["범위표기"])
    for q in out["문항"]:
        if q["id"] != "X05":  # X05 의 범위는 원본부터 범례에 없는 자유 문구다
            assert q["범위"] in legend, q["id"]
