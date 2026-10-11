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
    assert len(qs) == 78
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


def test_form_stage_questions_f01_to_f08():
    out = load_out()
    qs = {q["id"]: q for q in out["문항"]}
    for qid in ("F01", "F02", "F03", "F04", "F05", "F06", "F07", "F08"):
        q = qs[qid]
        assert q["범위"] == "서식단계" and q["키"] == [] and q["선택지"] is None and q["facts키"].startswith("(서식 전용)"), qid
        assert q["보이는조건"] == "항상" and not q["질문"].rstrip().endswith("?"), qid
    assert "관계코드" in qs["F02"]["질문"] and "양수인[].관계코드" in qs["F02"]["facts키"]
    assert "등기원인" in qs["F04"]["질문"] and "자산[].등기원인.취득" in qs["F04"]["facts키"]
    assert "0336" in qs["F04"]["도움말"] and "0021" in qs["F04"]["도움말"]
    assert "신고.홈택스ID" in qs["F06"]["facts키"] and "신고.분납신청" in qs["F03"]["facts키"]
    assert [q["id"] for q in out["문항"]][-8:] == ["F01", "F02", "F03", "F04", "F05", "F06", "F07", "F08"]


def test_form_stage_questions_f07_and_f08():
    out = load_out()
    qs = {q["id"]: q for q in out["문항"]}
    assert "사업자번호" in qs["F07"]["질문"] and "숫자 10자리" in qs["F07"]["질문"]
    assert "1번째 지출(" not in qs["F07"]["질문"] and "1번째 지출(" in qs["F07"]["비고"]      # 시스템 동작 설명은 질문이 아니라 비고에 둔다
    assert "자산[].필요경비.취득부대[].사업자번호" in qs["F07"]["facts키"] and "자산[].필요경비.양도비[].사업자번호" in qs["F07"]["facts키"]
    assert "p60" in json.dumps(qs["F07"]["근거조문"], ensure_ascii=False)
    assert "취득상대방" in qs["F08"]["질문"] and qs["F08"]["facts키"] == "(서식 전용) 자산[].취득상대방"
    assert "p59" in json.dumps(qs["F08"]["근거조문"], ensure_ascii=False) and "60바이트" in qs["F08"]["도움말"]
    assert "㈜" in qs["F08"]["도움말"] and "(주)" in qs["F08"]["도움말"] and "공백" in qs["F08"]["도움말"]
    # 사실관계 지출 목록(M08~M11)의 안내에도 지급처 사업자등록번호가 있다
    for qid in ("M08", "M09", "M10", "M11"):
        text = (qs[qid]["질문"] or "") + (qs[qid]["도움말"] or "")
        assert "사업자등록번호" in text, qid
        assert any("사업자번호" in u for u in qs[qid]["쓰이는판정"]), qid
    assert "사업자번호" in qs["M09"]["facts키"] and qs["M09"]["키"] == ["자산[].필요경비.자본적지출"]
