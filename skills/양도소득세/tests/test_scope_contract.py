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


def test_every_plan1_key_is_read_or_declared_collect_only():
    src = _engine_source()
    unread = [(qid, k) for qid, k in _plan1_keys()
              if not _is_read(k, src) and k not in F.COLLECT_ONLY and k not in READ_BY_JUDGE]
    assert not unread, ("질문지가 묻는데 엔진이 읽지 않는 키. 읽어서 계산하거나 다루지않음으로 돌리거나 facts.COLLECT_ONLY 에 이유와 "
                        "함께 적는다: %s" % unread)


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


def test_routed_keys_are_read_by_the_engine_not_collect_only():
    src = _engine_source()
    for qid in ("P07", "A06", "A13", "A14", "M02", "M03", "L01", "H12", "H13", "A02"):
        for q in Q.load()["문항"]:
            if q["id"] == qid:
                assert _is_read(q["키"][0], src) and q["키"][0] not in F.COLLECT_ONLY, qid


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


# ---- 답했는데 반영되지 않던 키를 다루지않음(계획 5)이나 확인사항으로 돌린다 ----
def _mut(name, fn):
    f = copy.deepcopy(CASES[name])
    fn(f)
    return f


def _out(f):
    r = engine.calculate(f, today=TODAY)
    assert r["상태"] == "질문" and r["계산"] is None, r
    return r["다루지않음"]


def test_same_day_houses_are_out_of_scope():
    f = copy.deepcopy(CASES["BC"])
    f["자산"][1]["양도"]["잔금일"] = f["자산"][0]["양도"]["잔금일"]
    p = F.prepare(f)
    assert sorted((x["자산"], x["계획"]) for x in p["다루지않음"]) == [("B", "5"), ("C", "5")]
    assert all(x["내용"] == "같은 날 주택 여러 채 양도(시행령 제154조⑨ 선택 순서)" for x in p["다루지않음"])
    assert len(_out(f)) == 2


def test_houses_sold_on_different_days_or_a_house_and_land_are_not_same_day():
    assert F.prepare(CASES["BC"])["다루지않음"] == []
    f = copy.deepcopy(CASES["BF"])
    f["자산"][1]["양도"]["잔금일"] = f["자산"][0]["양도"]["잔금일"]   # 주택 B 와 토지 F 를 같은 날 판다
    assert F.prepare(f)["다루지않음"] == []


def test_same_day_order_answer_is_out_of_scope_even_for_one_asset_in_the_file():
    """다른 양도를 따로 돌린 사실관계는 같은 날 양도한 다른 집이 없다. P07 에 답이 있으면 그 사실을 알려 주는 것이다."""
    p = F.prepare(_mut("A", lambda f: f["연간"].update(같은날양도순서="A")))
    assert [x["자산"] for x in p["다루지않음"]] == ["A"] and "제154조⑨" in p["다루지않음"][0]["내용"]
    for nobody in (None, "", "없음", "아니오", "해당없음", False):
        assert F.prepare(_mut("A", lambda f: f["연간"].update(같은날양도순서=nobody)))["다루지않음"] == []


def test_same_day_check_ignores_assets_already_out_of_scope():
    f = copy.deepcopy(CASES["BC"])
    f["자산"][1]["양도"]["잔금일"] = f["자산"][0]["양도"]["잔금일"]
    f["자산"][1]["양도"]["매수인부담세액"] = 1
    assert [x["자산"] for x in F.prepare(f)["다루지않음"]] == ["C"]   # B 한 채만 남아 같은 날이 아니다


@pytest.mark.parametrize("answer,out", [("호실별", True), ("일괄", False), (None, False)])
def test_multi_unit_house_sold_by_room_is_out_of_scope(answer, out):
    f = _mut("A", lambda f: f["자산"][0].update(주택유형="다가구주택", 다가구일괄양도=answer))
    if out:
        o = _out(f)
        assert o == [{"자산": "A", "내용": "다가구주택을 호실별로 나눠 양도(시행령 제155조⑮, 호실마다 한 채로 본다)", "계획": "5"}]
    else:
        assert engine.calculate(f, today=TODAY)["계산"]["합계"]["산출세액"] == EXPECT["A"]["산출세액"]


def test_unknown_multi_unit_code_asks_a06():
    f = _mut("A", lambda f: f["자산"][0].update(주택유형="다가구주택", 다가구일괄양도="통째"))
    assert [q["문항"] for q in F.prepare(f)["질문"]] == ["A06"]


@pytest.mark.parametrize("amount,out", [(30_000_000, True), (1, True), (0, False), (None, False)])
def test_buyer_paid_tax_is_out_of_scope(amount, out):
    f = _mut("B", lambda f: f["자산"][0]["양도"].update(매수인부담세액=amount))
    if out:
        assert _out(f) == [{"자산": "B", "내용": "매수인이 부담한 양도소득세가 있는 양도", "계획": "5"}]
    else:
        assert engine.calculate(f, today=TODAY)["계산"]["합계"]["산출세액"] == EXPECT["B"]["산출세액"]


def test_buyer_paid_tax_must_be_a_whole_amount():
    p = F.prepare(_mut("B", lambda f: f["자산"][0]["양도"].update(매수인부담세액="삼천만")))
    assert [q["문항"] for q in p["질문"]] == ["A14"] and p["다루지않음"] == []


def _related(관계, 시가):
    return _mut("B", lambda f: f["자산"][0].update(매수인관계=관계, 시가참고=시가))


RELATED_NOTE = "B: 특수관계인 거래는 시가와 비교해 부당행위계산 부인 대상인지 확인한다(소득세법 제101조)"


@pytest.mark.parametrize("관계", ["배우자", "직계", "친족", "법인", "기타특수관계"])
def test_related_party_sold_below_market_is_out_of_scope(관계):
    f = _related(관계, 900_000_000)   # 양도가액 7억원이 시가 9억원보다 낮다
    assert _out(f) == [{"자산": "B", "내용": "특수관계인에게 시가보다 낮게 양도(부당행위계산 부인 검토 대상)", "계획": "5"}]


@pytest.mark.parametrize("시가", [None, 700_000_000, 600_000_000])
def test_related_party_not_below_market_gets_a_note(시가):
    r = engine.calculate(_related("배우자", 시가), today=TODAY)
    assert r["상태"] == "완료" and r["계산"]["합계"]["산출세액"] == EXPECT["B"]["산출세액"]
    assert RELATED_NOTE in r["확인사항"]


def test_unrelated_buyer_gets_no_note_and_market_price_is_checked_as_money():
    r = engine.calculate(_related("타인", 900_000_000), today=TODAY)
    assert r["상태"] == "완료" and RELATED_NOTE not in r["확인사항"]
    p = F.prepare(_related("배우자", "구억"))
    assert [q["문항"] for q in p["질문"]] == ["M03"] and p["질문"][0]["내용"] == F.WHOLE_MSG


def _land(대지, 정착, 용도, 소재지=None):
    def m(f):
        f["자산"][0].update(주택유형="단독주택", 부수토지={"대지면적": 대지, "정착면적": 정착, "용도지역": 용도})
        if 소재지:
            f["자산"][0]["소재지"] = copy.deepcopy(소재지)
    return _mut("A", m)


@pytest.mark.parametrize("대지,용도,배율", [(301, "제2종일반주거지역", 3), (301, "준주거지역", 3), (301, "중심상업지역", 3),
                                          (301, "일반공업지역", 3), (501, "자연녹지지역", 5), (1001, "계획관리지역", 10),
                                          (1001, "농림지역", 10)])
def test_house_land_over_the_ratio_in_the_capital_area_is_out_of_scope(대지, 용도, 배율):
    o = _out(_land(대지, 100, 용도))[0]
    assert o["계획"] == "5" and "제154조⑦" in o["내용"] and "%d배" % 배율 in o["내용"]


@pytest.mark.parametrize("대지,용도", [(300, "제2종일반주거지역"), (500, "자연녹지지역"), (1000, "계획관리지역"), (1, "보전관리지역")])
def test_house_land_within_the_ratio_is_calculated(대지, 용도):
    r = engine.calculate(_land(대지, 100, 용도), today=TODAY)
    assert r["상태"] == "완료" and r["계산"]["합계"]["산출세액"] == EXPECT["A"]["산출세액"]


def test_land_ratio_outside_the_capital_area_is_five_for_urban_zones():
    for 대지, out in ((500, False), (501, True)):
        p = F.prepare(_land(대지, 100, "제1종일반주거지역", 소재지=addr("강원특별자치도", "춘천시", "석사동")))
        assert bool(p["다루지않음"]) is out and p["질문"] == []


@pytest.mark.parametrize("land", [300, "300", [300, 100], {"대지면적": 300}, {"대지면적": 300, "정착면적": 0, "용도지역": "자연녹지지역"},
                                  {"대지면적": 300, "정착면적": 100, "용도지역": "몰라"},
                                  {"대지면적": 300, "정착면적": 100, "용도지역": ""},
                                  {"대지면적": "300", "정착면적": 100, "용도지역": "자연녹지지역"},
                                  {"대지면적": 300, "정착면적": 100, "용도지역": "자연녹지지역", "비고": "x"}])
def test_malformed_house_land_asks_l01(land):
    f = _mut("A", lambda f: f["자산"][0].update(주택유형="단독주택", 부수토지=land))
    p = F.prepare(f)
    assert [q["문항"] for q in p["질문"]] == ["L01"] and p["다루지않음"] == []


def test_house_land_answer_check_is_shared_with_the_questionnaire():
    f = {"자산": [{"id": "A", "종류": "주택"}]}
    ok = {"대지면적": 300, "정착면적": 100, "용도지역": "제2종일반주거지역"}
    assert Q.answer(f, "L01", ok, 자산="A")["자산"][0]["부수토지"] == ok
    for bad in (300, {"대지면적": 300}, {"대지면적": 300, "정착면적": 100, "용도지역": "몰라"}):
        assert F.land_problem(bad)
        with pytest.raises(ValueError, match="L01"):
            Q.answer(f, "L01", bad, 자산="A")
    assert F.land_problem(ok) is None


@pytest.mark.parametrize("key,reason", [("비거주자전환", "시행령 제154조⑧2호"), ("재건축통산", "시행령 제154조⑧1호")])
def test_carryover_answers_are_out_of_scope(key, reason):
    o = _out(_mut("A", lambda f: f["자산"][0].update({key: True})))
    assert o[0]["계획"] == "5" and reason in o[0]["내용"]
    assert engine.calculate(_mut("A", lambda f: f["자산"][0].update({key: False})), today=TODAY)["상태"] == "완료"


def test_change_of_use_clause_is_out_of_scope():
    o = _out(_mut("A", lambda f: f["자산"][0]["양도"].update(용도변경특약=True)))
    assert o[0]["계획"] == "5" and "제154조① 괄호" in o[0]["내용"]
    assert engine.calculate(_mut("A", lambda f: f["자산"][0]["양도"].update(용도변경특약=False)), today=TODAY)["상태"] == "완료"


def test_house_routes_do_not_apply_to_land():
    f = _mut("F", lambda f: f["자산"][0].update(비거주자전환=True, 재건축통산=True, 다가구일괄양도="호실별"))
    assert F.prepare(f)["다루지않음"] == []


@pytest.mark.parametrize("name", sorted(EXPECT))
def test_expected_amounts_are_unchanged_by_the_routing(name):
    r = engine.calculate(CASES[name], today=TODAY)
    if name == "L":   # 2024-12-31 양도는 첫 양도일 전이라 다루지않음
        assert r["상태"] == "질문"
        return
    assert r["상태"] == "완료", (name, r["질문"], r["다루지않음"])
    assert r["계산"]["합계"]["산출세액"] == EXPECT[name]["산출세액"]


@pytest.mark.parametrize("name", sorted(EXPECT_TOTAL))
def test_expected_totals_are_unchanged_by_the_routing(name):
    r = engine.calculate(CASES[name], today=TODAY)
    assert r["상태"] == "완료" and r["계산"]["합계"]["산출세액"] == EXPECT_TOTAL[name]["산출세액"]


# ---- 광교 이의동(지구 단위 지정)에서 A02 모름 ----
def test_unknown_district_ends_with_out_of_scope_not_a_repeated_question():
    a = asset("G1", "주택", addr("경기도", "수원시 영통구", "이의동"), "2019-03-01", "2026-11-15", 1_500_000_000, 800_000_000,
              거주기간=[["2019-03-01", "2026-11-15"]])
    f = facts([a], [house("H1", a["소재지"], "2019-03-01", 자산id="G1")])
    first = engine.calculate(f, today=TODAY)
    assert [q["문항"] for q in first["질문"]] == ["A02"]
    g = Q.answer(f, "A02", Q.MOREUM, 자산="G1")
    r = engine.calculate(g, today=TODAY)
    assert r["질문"] == [] and r["계산"] is None
    assert len(r["다루지않음"]) == 1 and "지구 안인지 확인되지 않음" in r["다루지않음"][0]["내용"]
    assert "A02" not in [q["id"] for q in Q.next_questions(g, limit=None)["다음"]]
    h = Q.answer(g, "A02", "예", 자산="G1")   # 확인한 뒤 답을 바꾸면 계산한다
    assert engine.calculate(h, today=TODAY)["상태"] == "완료"
