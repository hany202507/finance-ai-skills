# -*- coding: utf-8 -*-
"""질문지가 묻는 사실을 엔진이 반영하는지 보는 계약 시험(최종 검토 I1, C1).

질문지가 사용자에게 묻는 사실(범위가 계획1인 문항의 키)은 세 가지 중 하나여야 한다.
  1. yangdo 가 읽어 계산하거나, 계산하지 않고 다루지않음(계획 5)이나 확인사항으로 돌린다.
  2. facts.COLLECT_ONLY 에 읽지 않는 이유와 함께 적혀 있다.
답했는데 결과에 아무 흔적이 없는 키가 다시 생기지 않게 한다.
"""
import copy
import glob
import os
import re

import pytest

from cases import CASES, EXPECT, EXPECT_TOTAL, addr, asset, facts, house
from yangdo import SKILL_DIR, engine
from yangdo import facts as F
from yangdo import questions as Q

TODAY = "2026-10-09"
# 다른 수정 묶음이 judge.py 에서 읽기로 한 키. 그 묶음이 합쳐지면 이 허용은 필요 없지만 남겨 두어도 시험은 깨지지 않는다
READ_BY_JUDGE = {"자산[].보유거주예외일자"}   # H11 출국일(시행령 제154조①2호 나목·다목 단서)


def _engine_source():
    """questions.py 를 뺀 yangdo/*.py 소스. questions.py 는 키를 묻고 검사할 뿐 엔진이 읽는 곳이 아니다.
    COLLECT_ONLY 표 자체도 읽는 곳이 아니라 뺀다."""
    text = ""
    for path in sorted(glob.glob(os.path.join(SKILL_DIR, "yangdo", "*.py"))):
        if os.path.basename(path) == "questions.py":
            continue
        with open(path, encoding="utf-8") as fh:
            text += re.sub(r"COLLECT_ONLY = \{.*?\n\}\n", "", fh.read(), flags=re.S)
    return text


def _is_read(key, source):
    """문항 키의 마지막 이름이 따옴표 글자 안에서 이름 끝이나 점 뒤 이름으로 나오는지. get(a, "양도.용도변경특약")
    과 a.get("용도변경특약") 를 모두 잡는다."""
    return re.search(r'(?<=["\.])%s"' % re.escape(key.split(".")[-1]), source) is not None


def _plan1_keys():
    return [(q["id"], k) for q in Q.load()["문항"] if q["범위"].startswith("계획1") for k in q["키"]]


def test_is_read_matches_both_reading_styles():
    assert _is_read("자산[].양도.용도변경특약", 'if get(a, "양도.용도변경특약") is True:')
    assert _is_read("자산[].양도.용도변경특약", 'a.get("양도").get("용도변경특약")')
    assert _is_read("자산[].등기", 'a["등기"]')
    assert not _is_read("자산[].양도.용도변경특약", 'x = "용도변경특약가"')
    assert not _is_read("자산[].면적", '"정착면적"')
    assert not _is_read("자산[].면적", "")


def test_collect_only_entries_are_real_explained_and_really_unread():
    keys = {k for _, k in _plan1_keys()}
    src = _engine_source()
    assert set(F.COLLECT_ONLY) <= keys, sorted(set(F.COLLECT_ONLY) - keys)
    for key, why in F.COLLECT_ONLY.items():
        assert isinstance(why, str) and len(why.strip()) >= 10, key
        assert "?" not in why and chr(0x2014) not in why, key
        assert not _is_read(key, src), "%s 를 엔진이 읽는다. COLLECT_ONLY 에서 뺀다" % key


def test_collect_only_names_the_keys_review_listed():
    by_id = {q["id"]: q for q in Q.load()["문항"]}
    for qid in ("T02", "M20", "P06", "H03", "H08", "M24", "A04", "A20", "X06"):
        assert by_id[qid]["키"][0] in F.COLLECT_ONLY, qid


# ---- 자료형 계약: 문항.json 의 답형식 표로 엔진이 읽는 모든 키를 검사한다 ----
def _put(node, path, value):
    parts = path.split(".")
    for p in parts[:-1]:
        if not isinstance(node.get(p), dict):
            node[p] = {}
        node = node[p]
    node[parts[-1]] = value


def _wrong(kind):
    return {"예아니오": "false", "선택": ["없는코드"], "복수선택": "해당없음", "목록": "없음"}[kind]


def _rule_id(rule):
    q, where, path = rule
    return "%s-%s" % (q["id"], path)


@pytest.mark.parametrize("rule", [r for r in F.form_rules() if r[0].get("선택지") or r[0]["답형식"] in ("예아니오", "목록")],
                         ids=_rule_id)
def test_every_form_key_the_engine_reads_asks_its_question_on_wrong_type(rule):
    q, where, path = rule
    f = copy.deepcopy(CASES["D"])
    target = {"자산": f["자산"][0], "주택": f["세대"]["주택목록"][1], "전역": f}[where]
    _put(target, path, _wrong(q["답형식"]))
    p = F.prepare(f)
    assert q["id"] in [x["문항"] for x in p["질문"]], (q["id"], path, p["질문"])


def test_wrong_type_never_lowers_the_tax_through_the_engine():
    """검토가 재현한 사례: 중과배제 사유를 글자로 주면 중과가 빠져 81,710,000원으로 완료·검산 통과로 나왔다."""
    f = copy.deepcopy(CASES["D"])
    f["자산"][0]["중과배제_사유"] = "해당없음"
    r = engine.calculate(f, today=TODAY)
    assert r["상태"] == "질문" and r["계산"] is None
    assert [x["문항"] for x in r["질문"]] == ["X04"]
    f["자산"][0]["중과배제_사유"] = ["해당없음"]
    r = engine.calculate(f, today=TODAY)
    assert r["상태"] == "완료" and r["계산"]["합계"]["산출세액"] == EXPECT["D"]["산출세액"]


@pytest.mark.parametrize("name,mutate,문항", [
    ("E", lambda f: f["자산"][0].update(등기="false"), "A07"),
    ("D", lambda f: f["신고인"].update(거주자="false"), "P01"),
    ("D", lambda f: f["자산"][0].update(계약금액일치="false"), "M04"),
    ("D", lambda f: f["세대"].update(배우자="false"), "H01"),
    ("D", lambda f: f["세대"].update(특례주택="없음"), "H05"),
])
def test_engine_asks_instead_of_calculating_on_wrong_type(name, mutate, 문항):
    f = copy.deepcopy(CASES[name])
    mutate(f)
    r = engine.calculate(f, today=TODAY)
    assert r["상태"] == "질문" and r["계산"] is None and r["다루지않음"] == []
    assert 문항 in [x["문항"] for x in r["질문"]]
