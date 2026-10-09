# -*- coding: utf-8 -*-
import copy

import pytest

from cases import CASES, EXPECT, EXPECT_TOTAL
from yangdo import questions as Q


def _engine():
    """문답 재현 시험만 엔진(T12)을 쓴다. 지연 import 라 이 파일은 엔진 없이도 불러진다."""
    from yangdo import engine
    return engine


def oracle_value(oracle, q):
    asset = next(a for a in oracle["자산"] if a["id"] == q["자산"]) if q["자산"] else oracle["자산"][0]
    house = next(h for h in oracle["세대"]["주택목록"] if h["id"] == q["주택"]) if q["주택"] else None
    vals = {k.rsplit(".", 1)[-1]: Q.read(oracle, k, asset, house) for k in q["키"]}
    if len(vals) == 1:
        return next(iter(vals.values()))
    return vals if any(v is not None for v in vals.values()) else None


HOUSE_DETAILS = ("양도당시기준시가", "제12호해당")   # 문항 X01, X03 이 집마다 묻는 값


def bare_house_list(value):
    """H04 의 답에서 집마다 따로 묻는 값(X01, X03)을 뺀다. 집 목록을 소재지·취득일만으로 답한 사용자와 같다."""
    return [{k: v for k, v in h.items() if k not in HOUSE_DETAILS} for h in value]


def replay_units(oracle, bare_houses=False):
    """오라클로 문답을 끝까지 돌린다. (사실관계, [(문항 id, 자산 id, 주택 id)]) 를 돌려준다.

    bare_houses 면 H04 를 집마다 따로 묻는 값 없이 답해, X01, X03 이 나오는 집만 그 값을 오라클에서 받는다.
    """
    f = {"자산": [{"id": a["id"]} for a in oracle["자산"]]}
    asked = []
    for _ in range(400):
        nq = Q.next_questions(f)
        if not nq["다음"]:
            return f, asked
        q = nq["다음"][0]
        v = oracle_value(oracle, q)
        if bare_houses and q["id"] == "H04":
            v = bare_house_list(v)
        f = Q.answer(f, q["id"], Q.MOREUM if v is None else v, 자산=q["자산"], 주택=q["주택"])
        asked.append((q["id"], q["자산"], q["주택"]))
    raise AssertionError("문답이 끝나지 않는다: %s" % asked[-10:])


def replay(oracle):
    f, units = replay_units(oracle)
    return f, [u[0] for u in units]


def dialogue(name):
    return replay(CASES[name])


@pytest.mark.parametrize("name", ["A", "B", "D", "E", "F", "G", "G2", "I", "I2", "J", "K2"])
def test_dialogue_reaches_same_result(name):
    f, asked = dialogue(name)
    r = _engine().calculate(f, today="2026-10-09")
    assert r["상태"] == "완료", (asked, r["질문"], r["다루지않음"])
    assert r["계산"]["합계"]["산출세액"] == EXPECT[name]["산출세액"]
    assert len(asked) == len(set(asked)), asked  # 집마다 묻는 문항은 그 집이 필요할 때만 나와 id 가 겹치지 않는다
    # 오라클이 답하지 못해 「모름」으로 넘긴 문항은 값이 원래 없는 선택 문항(A12 등기접수일, T01 신규 주택 계약일)뿐이다
    assert {m.split(":")[0] for m in f.get("모름") or []} <= {"A12", "T01"}, f["모름"]


def _units(name, qid, bare=True):
    return [u[1:] for u in replay_units(CASES[name], bare_houses=bare)[1] if u[0] == qid]


@pytest.mark.parametrize("name,x01,x03", [
    ("K2", [(None, "H3")], []),    # 서울 집 H1, H2 는 묻지 않는다. 춘천 집 H3 만 묻는다
    ("J", [], [(None, "H1")]),     # 2010년 취득 집 H8 은 묻지 않는다. 2025-08-01 취득 집 H1 만 묻는다
    ("K", [], []), ("D", [], []), ("G", [], []), ("G2", [], []),   # 서울 집뿐이거나 중과 후보가 아니거나 2024-01-10 전에 산 집뿐이다
])
def test_house_questions_are_asked_only_for_the_houses_that_need_them(name, x01, x03):
    """X01(양도 당시 기준시가)은 수도권·광역시 동 지역·세종 동 지역이 아닌 집만, X03(제12호 해당)은 2024-01-10 이후 취득한 집만 묻는다."""
    f, units = replay_units(CASES[name], bare_houses=True)
    assert [u[1:] for u in units if u[0] == "X01"] == x01
    assert [u[1:] for u in units if u[0] == "X03"] == x03
    assert not [m for m in f.get("모름") or [] if m.startswith(("X01", "X03"))]   # 오라클이 답하지 못한 집 문항이 없다


@pytest.mark.parametrize("name", ["K2", "J", "G", "K"])
def test_dialogue_with_bare_house_list_reaches_same_result(name):
    """집 목록을 소재지·취득일만으로 답해도, 필요한 집만 따로 물어 같은 세액에 이른다(K2 는 H3 의 기준시가가 중과 주택 수를 가른다)."""
    f, asked = replay_units(CASES[name], bare_houses=True)
    r = _engine().calculate(f, today="2026-10-09")
    assert r["상태"] == "완료", (asked, r["질문"], r["다루지않음"])
    assert r["계산"]["합계"]["산출세액"] == EXPECT[name]["산출세액"]


def test_house_questions_on_complete_facts_skip_houses_that_do_not_need_them():
    """다 채운 사실관계에서도 서울 집의 X01 은 남은 문항이 아니다(전에는 H1, H2 가 남아 있었다)."""
    assert _pending_house_questions(CASES["K2"]) == [] and _pending_house_questions(CASES["J"]) == []


def _pending_house_questions(f):
    return [(q["id"], q["주택"]) for q in Q.next_questions(f, limit=None)["다음"] if q["주택"]]


def _set_house(f, hid, **kw):
    h = next(x for x in f["세대"]["주택목록"] if x["id"] == hid)
    h.update(kw)
    return h


def test_provincial_house_with_heavy_conditions_still_gets_x01():
    f = copy.deepcopy(CASES["K2"])
    _set_house(f, "H3", 양도당시기준시가=None)
    assert _pending_house_questions(f) == [("X01", "H3")]


def test_house_acquired_from_2024_01_10_still_gets_x03():
    f = copy.deepcopy(CASES["J"])
    _set_house(f, "H8", 취득일="2024-01-10", 제12호해당=None)
    assert _pending_house_questions(f) == [("X03", "H8")]
    _set_house(f, "H8", 취득일="2024-01-09")   # 하루 전이면 묻지 않는다
    assert _pending_house_questions(f) == []


def test_house_with_unknown_location_waits_instead_of_asking():
    """집의 소재지를 모르면 지방인지 모른다. 보이는조건이 모름이라 아직 묻지 않는다."""
    f = copy.deepcopy(CASES["K2"])
    h = _set_house(f, "H3", 양도당시기준시가=None)
    del h["소재지"]
    assert _pending_house_questions(f) == []


def test_house_term_is_three_valued_and_read_per_house():
    ev = {"주택별": {"H1": {"지방소재": True}, "H2": {"지방소재": False}, "H4": {"지방소재": None}}}
    cond = {"모두": [["주택.지방소재", "==", True]]}

    def vis(house):
        return Q._visible(cond, {}, ev, None, house, {}, "Z99")
    assert vis({"id": "H1"}) is True
    assert vis({"id": "H2"}) is False
    assert vis({"id": "H4"}) is None       # 값을 모른다
    assert vis({"id": "H9"}) is None       # 엔진값에 없는 집
    assert vis(None) is None               # 집 단위 문항이 아니다
    assert Q._visible(cond, {}, {}, None, {"id": "H1"}, {}, "Z99") is None   # 주택별 값이 없다


def _condition_terms(c):
    """보이는조건의 항목 왼쪽(문항 id, 엔진.이름, 주택.이름)을 모두 낸다."""
    if c == "항상":
        return
    for it in c.get("모두", []) + c.get("하나라도", []):
        if isinstance(it, dict):
            yield from _condition_terms(it)
        else:
            yield it[0]


def test_house_terms_appear_only_on_house_questions():
    """주택.* 조건은 집마다 묻는 문항에서만 읽을 수 있다. 다른 문항에 쓰면 조용히 영영 안 나온다."""
    for q in Q.load()["문항"]:
        if any(t.startswith("주택.") for t in _condition_terms(q["보이는조건"])):
            assert Q.unit_kind(q) == "주택", q["id"]


def _engine_value_names():
    """tests/cases.py 의 모든 사례에서 judge.engine_values 가 내놓는 이름. (자산마다의 이름, 집마다의 이름)"""
    from yangdo import facts as F, judge as J, regions, ruleset
    rs, reg = ruleset.load(), regions.load()
    per_asset, per_house = set(), set()
    for f in CASES.values():
        prep = F.prepare(f)
        for a in f["자산"]:
            ev = J.engine_values(f, a, prep, rs, reg)
            per_asset |= set(ev)
            for values in ev["주택별"].values():
                per_house |= set(values)
    return per_asset, per_house


def test_every_engine_term_names_a_value_engine_values_returns():
    """엔진.이름이나 주택.이름을 잘못 적으면 그 값이 늘 모름이라 문항이 조용히 영영 나오지 않는다. 이름이 맞는지 여기서 잡는다."""
    per_asset, per_house = _engine_value_names()
    assert per_house, "사례에서 집마다의 엔진값이 하나도 나오지 않았다"
    used = {t for q in Q.load()["문항"] for t in _condition_terms(q["보이는조건"]) if t.startswith(("엔진.", "주택."))}
    assert used
    wrong = sorted(t for t in used if t[3:] not in (per_asset if t.startswith("엔진.") else per_house))
    assert not wrong, "engine_values 가 내놓지 않는 이름: %s" % wrong


def test_documented_engine_values_exist():
    """문항.json 의 엔진값 설명에 적힌 이름도 engine_values 에 있어야 한다."""
    per_asset, per_house = _engine_value_names()
    docs = Q.load()["엔진값"]
    assert all(k.startswith(("엔진.", "주택.")) for k in docs)
    wrong = sorted(k for k in docs if k[3:] not in (per_asset if k.startswith("엔진.") else per_house))
    assert not wrong, wrong


def test_engine_term_check_catches_a_misspelled_name(monkeypatch):
    broken = copy.deepcopy(Q.load())
    x01 = next(q for q in broken["문항"] if q["id"] == "X01")
    x01["보이는조건"]["모두"].append(["엔진.지방소재주택잇음", "==", True])   # 오타
    monkeypatch.setattr(Q, "load", lambda path=None: broken)
    with pytest.raises(AssertionError, match="지방소재주택잇음"):
        test_every_engine_term_names_a_value_engine_values_returns()


def test_exempt_case_skips_expense_questions():
    _, asked = dialogue("G")
    assert not {"M05", "M06", "M07", "M08", "M09", "M10", "M11", "M12"} & set(asked)
    assert "H07" in asked  # 신규 주택 계약일(T01)은 주택 목록(H04) 답에 이미 들어 있어 묻지 않는다


def test_late_disposal_asks_new_house_contract_and_extension():
    _, asked = dialogue("G2")
    assert {"T01", "T03", "X04"} <= set(asked)


def test_heavy_case_asks_contract_and_exclusions():
    _, asked = dialogue("D")
    assert {"A09", "A10", "X04", "M22", "X05"} <= set(asked)
    assert "H07" not in asked


def test_luxury_one_house_asks_residence_and_expenses():
    _, asked = dialogue("A")
    assert {"H07", "M05", "M06", "M09"} <= set(asked) and "X04" not in asked


def test_answer_validation_and_moreum():
    f = {"자산": [{"id": "A"}]}
    with pytest.raises(ValueError):
        Q.answer(f, "P02", "아파트", 자산="A")
    with pytest.raises(ValueError):
        Q.answer(f, "A07", "예", 자산="A")
    g = Q.answer(f, "A12", Q.MOREUM, 자산="A")
    assert g["모름"] == ["A12:A"] and f == {"자산": [{"id": "A"}]}
    g = Q.answer(f, "A17", {"잔금일": "2014-11-01"}, 자산="A")
    assert g["자산"][0]["취득"]["잔금일"] == "2014-11-01"


def test_first_question_is_residency():
    nq = Q.next_questions({"자산": [{"id": "A"}]})
    assert nq["다음"][0]["id"] == "P01" and nq["남은"] >= 1


def test_form_questions_only_when_asked():
    f, _ = dialogue("B")
    assert Q.next_questions(f)["다음"] == []
    assert Q.next_questions(f, 서식=False)["남은"] == 0


def land_first(name):
    oracle = copy.deepcopy(CASES[name])
    oracle["자산"].sort(key=lambda a: a["종류"] != "토지")
    assert oracle["자산"][0]["종류"] == "토지"
    return oracle


def test_land_first_still_asks_household_questions():
    """토지를 먼저 적어도 주택 자산이 있으면 세대 문항이 나온다(첫 자산만 보면 문답이 중간에 멈춘다)."""
    _, asked = replay(land_first("BF"))
    assert {"H01", "H03", "H04", "H05", "H06"} <= set(asked)


def test_land_first_dialogue_reaches_same_total():
    f, asked = replay(land_first("BF"))
    r = _engine().calculate(f, today="2026-10-09")
    assert r["상태"] == "완료", (asked, r["질문"], r["다루지않음"])
    assert r["계산"]["합계"]["산출세액"] == EXPECT_TOTAL["BF"]["산출세액"]


@pytest.mark.parametrize("name", ["BC", "BF"])
def test_two_asset_dialogue_reaches_same_total(name):
    f, asked = dialogue(name)
    r = _engine().calculate(f, today="2026-10-09")
    assert r["상태"] == "완료", (asked, r["질문"], r["다루지않음"])
    assert r["계산"]["합계"]["산출세액"] == EXPECT_TOTAL[name]["산출세액"]
    assert asked.count("A01") == 2  # 자산마다 묻는다


def test_new_house_unit_and_moreum_marker():
    base = {"자산": [{"id": "A", "종류": "주택"}],
            "세대": {"주택목록": [{"id": "H1", "자산id": "A"},
                                {"id": "H2", "자산id": None, "취득일": "2024-05-01"}]}}
    g = Q.answer(base, "T01", Q.MOREUM, 자산="A", 주택="H2")
    assert g["모름"] == ["T01:H2"]
    g = Q.answer(g, "T01", {"계약일": "2024-03-01"}, 자산="A", 주택="H2")
    assert g["세대"]["주택목록"][1]["계약일"] == "2024-03-01" and g["모름"] == []  # 값을 알게 되면 모름 표시를 지운다
    with pytest.raises(ValueError):
        Q.answer(base, "T01", {"계약일": "2024-03-01"}, 자산="A")  # 주택 id 가 필요하다


def test_moreum_is_a_value_when_choice_has_it():
    g = Q.answer({"자산": [{"id": "A"}]}, "M20", Q.MOREUM, 자산="A")
    assert g["자산"][0]["취득"]["상대방유형"] == "모름" and not g.get("모름")


def _house_asset_facts():
    return {"자산": [{"id": "A", "종류": "주택"}]}


@pytest.mark.parametrize("qid,value,kw", [
    pytest.param("A11", "2026.11.15", {"자산": "A"}, id="date-format"),
    pytest.param("A11", "2026-13-40", {"자산": "A"}, id="date-no-such-day"),
    pytest.param("A11", {"잔금일": "2026-11-15"}, {"자산": "A"}, id="date-dict-for-plain-date"),
    pytest.param("A01", "서울특별시 송파구 잠실동", {"자산": "A"}, id="address-string"),
    pytest.param("A01", {"시도": "서울특별시"}, {"자산": "A"}, id="address-no-sigungu"),
    pytest.param("P04", "공동", {"자산": "A"}, id="share-no-numerator-denominator"),
    pytest.param("A11", None, {"자산": "A"}, id="empty-is-not-moreum"),
    pytest.param("A17", {"잔금일": None, "등기접수일": None}, {"자산": "A"}, id="two-keys-all-empty"),
    pytest.param("A17", {"결제일": "2014-11-01"}, {"자산": "A"}, id="two-keys-unknown-name"),
    pytest.param("A17", "2014-11-01", {"자산": "A"}, id="two-keys-needs-dict"),
    pytest.param("H07", [["2014-11-01"]], {"자산": "A"}, id="period-has-two-ends"),
    pytest.param("H07", [["2020-01-01", "2014-11-01"]], {"자산": "A"}, id="period-reversed"),
    pytest.param("H04", [{"소재지": {"시도": "서울특별시", "시군구": "마포구"}}], {}, id="houses-no-id"),
    pytest.param("H04", [{"id": "H1", "자산id": None}], {}, id="houses-other-house-no-date"),
    pytest.param("H04", [{"id": "H1", "자산id": "Z", "취득일": "2014-11-01"}], {}, id="houses-sold-house-not-linked"),
    pytest.param("X09", True, {}, id="no-such-question"),
])
def test_answer_rejects_malformed_answers(qid, value, kw):
    with pytest.raises(ValueError):
        Q.answer(_house_asset_facts(), qid, value, **kw)


def test_answer_accepts_share_dict():
    ok = Q.answer(_house_asset_facts(), "P04", {"구분": "공동", "분자": 1, "분모": 2}, 자산="A")
    assert ok["자산"][0]["지분"]["분모"] == 2


def test_structured_date_answers_are_accepted():
    """M23, X06 은 날짜 하나가 아니라 이름 붙인 묶음으로 답한다. 엔진은 .get 으로 읽는다."""
    f = _house_asset_facts()
    g = Q.answer(f, "M23", {"사용승인일": "2020-05-01", "증축면적": 90}, 자산="A")
    assert g["자산"][0]["신축증축"] == {"사용승인일": "2020-05-01", "증축면적": 90}
    assert (g["자산"][0].get("신축증축") or {}).get("사용승인일") == "2020-05-01"
    h = Q.answer(f, "X06", {"신청일": "2026-04-01", "허가일": "2026-05-01"}, 자산="A")
    assert h["자산"][0]["토지거래허가"] == {"신청일": "2026-04-01", "허가일": "2026-05-01"}
    part = Q.answer(f, "X06", {"신청일": "2026-04-01"}, 자산="A")  # 허가는 아직 안 난 경우
    assert part["자산"][0]["토지거래허가"] == {"신청일": "2026-04-01"}
    only_area = Q.answer(f, "M23", {"증축면적": 90}, 자산="A")
    assert only_area["자산"][0]["신축증축"] == {"증축면적": 90}
    assert f == _house_asset_facts()


@pytest.mark.parametrize("qid,value", [
    pytest.param("M23", "2020-05-01", id="m23-plain-date-string"),   # 엔진이 .get 을 부르므로 문자열이 들어가면 안 된다
    pytest.param("M23", {"사용승인일": "2020.05.01"}, id="m23-date-format"),
    pytest.param("M23", {"사용승인일": "2020-02-31"}, id="m23-no-such-day"),
    pytest.param("M23", {"사용승인일": 20200501}, id="m23-date-not-string"),
    pytest.param("M23", {"준공일": "2020-05-01"}, id="m23-unknown-name"),
    pytest.param("M23", {"사용승인일": None, "증축면적": None}, id="m23-all-empty"),
    pytest.param("M23", {}, id="m23-empty-dict"),
    pytest.param("X06", "2026-05-01", id="x06-plain-date-string"),
    pytest.param("X06", {"신청일": "2026/04/01"}, id="x06-date-format"),
    pytest.param("X06", {"신청일": "2026-04-01", "허가일": "곧"}, id="x06-second-date-bad"),
    pytest.param("X06", {"접수일": "2026-04-01"}, id="x06-unknown-name"),
    pytest.param("X06", {"신청일": None, "허가일": None}, id="x06-all-empty"),
])
def test_structured_date_answers_reject_wrong_shapes(qid, value):
    with pytest.raises(ValueError):
        Q.answer(_house_asset_facts(), qid, value, 자산="A")


def test_generic_date_check_is_skipped_only_for_keys_with_an_answer_check(monkeypatch):
    """KEY_RULES 에 든 키라고 일반 날짜 검사를 건너뛰지 않는다. 그 키의 규칙에 「답」 검사가 있을 때만 건너뛴다."""
    q = next(x for x in Q.load()["문항"] if x["id"] == "A11")
    assert q["답형식"] == "날짜" and len(q["키"]) == 1
    key = q["키"][0]
    f = _house_asset_facts()
    monkeypatch.setitem(Q.KEY_RULES, key, {"주소확인": "소재지"})    # 답 검사가 없는 규칙
    with pytest.raises(ValueError):
        Q.answer(f, "A11", "2026.11.15", 자산="A")
    assert Q.answer(f, "A11", "2026-11-15", 자산="A")["자산"][0]["양도"]["잔금일"] == "2026-11-15"
    monkeypatch.setitem(Q.KEY_RULES, key, {"답": lambda qid, value, facts: None})   # 답 검사가 맡는다
    assert Q.answer(f, "A11", "2026.11.15", 자산="A")["자산"][0]["양도"]["잔금일"] == "2026.11.15"


def test_moreum_still_works_for_structured_date_questions():
    g = Q.answer(_house_asset_facts(), "M23", Q.MOREUM, 자산="A")
    assert g["모름"] == ["M23:A"] and "신축증축" not in g["자산"][0]


def test_answer_rejects_personal_data():
    from yangdo import facts as F
    with pytest.raises(F.FactsError):
        Q.answer({"자산": [{"id": "A"}]}, "H03", [{"성명": "합성", "관계": "배우자"}])
    with pytest.raises(F.FactsError):
        Q.answer({"자산": [{"id": "A"}]}, "H03", [{"관계": "900101-1234567"}])


def test_description_is_a_copy():
    f = {"자산": [{"id": "A"}]}
    nq = Q.next_questions(f, limit=None)
    assert nq["남은"] == len(nq["다음"]) > 1
    nq["다음"][0]["키"].append("깨짐")
    nq["다음"][0]["근거조문"].clear()
    again = Q.next_questions(f)["다음"][0]
    assert again["키"] == ["신고인.거주자"] and again["근거조문"]


def test_empty_facts_start_with_global_questions():
    assert Q.next_questions({})["다음"][0]["id"] == "P01"


def _house_sale_facts(addr):
    """주소 문항(A01) 앞의 문항을 답한 사실관계. 양도 2026-03-15, 취득 2018-01-01."""
    f = {"자산": [{"id": "A"}]}
    for qid, v in (("P02", "주택"), ("P03", "매매"), ("A15", "매매"), ("A11", "2026-03-15"),
                   ("A17", {"잔금일": "2018-01-01"}), ("A01", addr)):
        f = Q.answer(f, qid, v, 자산="A")
    return f


def _ids(f):
    return [q["id"] for q in Q.next_questions(f, limit=None)["다음"]]


@pytest.mark.parametrize("addr,hint", [
    ({"시도": "경기도", "시군구": "성남시", "읍면동": "정자동"}, "구 이름"),   # 고시가 구마다 지정을 가른다
    ({"시도": "서울특별", "시군구": "마포구", "읍면동": "공덕동"}, "시도 이름"),   # 모르는 시도
])
def test_unresolved_address_is_asked_again_with_hint(addr, hint):
    f = _house_sale_facts(addr)
    nq = [q for q in Q.next_questions(f, limit=None)["다음"] if q["id"] == "A01"]
    assert len(nq) == 1 and hint in nq[0]["안내"] and nq[0]["자산"] == "A"


def test_address_hint_comes_from_engine_values_not_from_regions(monkeypatch):
    """되묻기는 judge.engine_values 의 소재지확인필요, 소재지안내 를 읽는다. 문항 쪽에서 regions 를 다시 부르지 않는다."""
    from yangdo import judge
    f = _house_sale_facts({"시도": "서울특별시", "시군구": "마포구", "읍면동": "공덕동"})   # 고시 이력이 정하는 주소
    assert "A01" not in _ids(f)
    real = judge.engine_values

    def flagged(*args):
        return dict(real(*args), 소재지확인필요=True, 소재지안내="엔진값이 준 안내")
    monkeypatch.setattr(judge, "engine_values", flagged)
    again = [q for q in Q.next_questions(f, limit=None)["다음"] if q["id"] == "A01"]
    assert len(again) == 1 and again[0]["안내"] == "엔진값이 준 안내"
    assert Q._address_note({"답형식": "주소", "키": ["자산[].소재지"]}, {"소재지확인필요": False, "소재지안내": "x"}) is None
    assert Q._address_note({"답형식": "주소", "키": ["자산[].취득당시소재지"]},
                           {"취득당시소재지확인필요": True, "취득당시소재지안내": "y"}) == "y"
    assert Q._address_note({"답형식": "날짜", "키": ["자산[].양도.잔금일"]}, {"소재지확인필요": True}) is None


def test_resolved_address_is_not_asked_again():
    f = _house_sale_facts({"시도": "경기도", "시군구": "성남시 분당구", "읍면동": "정자동"})
    assert "A01" not in _ids(f)
    g = _house_sale_facts({"시도": "경기도", "시군구": "성남시", "읍면동": "정자동"})
    g = Q.answer(g, "A01", {"시도": "경기도", "시군구": "성남시 분당구", "읍면동": "정자동"}, 자산="A")
    assert "A01" not in _ids(g)
    assert all(q["안내"] is None for q in Q.next_questions(g, limit=None)["다음"])


def test_address_not_asked_again_after_moreum_or_before_dates():
    addr = {"시도": "경기도", "시군구": "성남시", "읍면동": "정자동"}
    early = Q.answer({"자산": [{"id": "A"}]}, "A01", addr, 자산="A")  # 날짜를 아직 모르면 판정하지 못해 기다린다
    assert "A01" not in _ids(early)
    f = Q.answer(_house_sale_facts(addr), "A01", Q.MOREUM, 자산="A")
    assert "A01" not in _ids(f)


def test_next_questions_is_json_serializable():
    import json
    nq = Q.next_questions(_house_sale_facts({"시도": "경기도", "시군구": "성남시", "읍면동": "정자동"}), limit=None)
    json.dumps(nq, ensure_ascii=False)


def test_rules_are_reloaded_when_edition_file_changes(tmp_path):
    import os
    import shutil
    from yangdo import RULES_DIR
    d = str(tmp_path / "rules")
    shutil.copytree(RULES_DIR, d)
    first = Q._rules(d)
    assert Q._rules(d) is first
    ed = os.path.join(d, "기준정보판.json")
    st = os.stat(ed)
    os.utime(ed, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
    assert Q._rules(d) is not first
    assert len([k for k in Q._RULES if k[0] == d]) == 1  # 옛 판은 버린다
    assert Q.next_questions({"자산": [{"id": "A"}]}, rules_dir=d)["다음"][0]["id"] == "P01"


# 키 이름으로 거는 검사는 Q.KEY_RULES 한 표에 모았다. 문항의 키가 바뀌면 여기서 깨진다.
def _all_question_keys():
    return {k for q in Q.load()["문항"] for k in q["키"]}


def test_every_key_rule_names_a_real_question_key():
    assert Q.KEY_RULES
    missing = set(Q.KEY_RULES) - _all_question_keys()
    assert not missing, "문항.json 에 없는 키: %s" % sorted(missing)


def test_key_rules_hooks_are_known_and_callable():
    from yangdo import judge as J
    for key, hooks in Q.KEY_RULES.items():
        assert hooks and set(hooks) <= {"답", "주소확인"}, key
        if "답" in hooks:
            assert callable(hooks["답"]), key
        if "주소확인" in hooks:   # 엔진값 <이름>확인필요, <이름>안내 가 engine_values 에 있어야 한다
            name = hooks["주소확인"]
            assert name + "확인필요" in J.EV_KEYS and name + "안내" in J.EV_KEYS, key


def test_answer_rules_sit_on_single_key_questions():
    """답 검사는 키 하나짜리 문항의 답 전체를 받는다. 키가 둘이면 답이 dict 라 같은 검사를 쓸 수 없다."""
    by_key = {}
    for q in Q.load()["문항"]:
        for k in q["키"]:
            by_key.setdefault(k, []).append(q)
    for key, hooks in Q.KEY_RULES.items():
        if "답" in hooks:
            assert all(len(q["키"]) == 1 for q in by_key[key]), key


def test_every_condition_in_definition_has_a_known_shape():
    qs = Q.load()["문항"]
    qmap = {q["id"]: q for q in qs}
    for q in qs:
        # 빈 사실관계로 평가한다. 모양이 틀린 조건이면 ValueError 가 난다(값을 몰라 None 이어도 모양은 끝까지 본다)
        Q._visible(q["보이는조건"], {}, {}, None, None, qmap, q["id"])


@pytest.mark.parametrize("cond", [
    pytest.param({"또는": [["P01", "==", True]]}, id="unknown-group-name"),
    pytest.param({}, id="empty-dict"),
    pytest.param({"모두": [], "하나라도": []}, id="both-groups"),
    pytest.param({"모두": "P01"}, id="group-not-list"),
    pytest.param([["P01", "==", True]], id="bare-list"),
    pytest.param("가끔", id="unknown-string"),
    pytest.param({"모두": [["P01", "=~", True]]}, id="unknown-operator"),
    pytest.param({"모두": [["P01", "=="]]}, id="item-too-short"),
    pytest.param({"모두": ["P01"]}, id="item-not-list"),
    pytest.param({"모두": [{"또는": []}]}, id="nested-unknown-group"),
])
def test_unknown_condition_shape_names_the_question(cond):
    with pytest.raises(ValueError, match="Z99"):
        Q._visible(cond, {}, {}, None, None, {}, "Z99")


def test_next_questions_reports_bad_condition_with_question_id(monkeypatch):
    broken = copy.deepcopy(Q.load())
    broken["문항"][0]["보이는조건"] = {"또는": []}
    monkeypatch.setattr(Q, "load", lambda path=None: broken)
    with pytest.raises(ValueError, match=broken["문항"][0]["id"]):
        Q.next_questions({"자산": [{"id": "A"}]})


# ---- 자료형 검사는 사실관계 검사와 같은 표(facts.form_problem)를 쓴다 (C1) ----
def _q(qid):
    return next(q for q in Q.load()["문항"] if q["id"] == qid)


def test_question_definitions_are_loaded_once_for_both_checks():
    from yangdo import facts as F
    assert Q.load() is F.load_questions()


@pytest.mark.parametrize("qid,value,unit", [
    ("A07", "false", "자산"), ("A07", 0, "자산"), ("A07", "예", "자산"),
    ("X04", "해당없음", "자산"), ("X04", ["없는사유"], "자산"), ("X04", [["사원용"]], "자산"),
    ("A06", ["일괄"], "자산"), ("A06", "통째", "자산"), ("A06", {"구분": "일괄"}, "자산"),
    ("A02", True, "자산"), ("A02", {"구분": "예"}, "자산"),
    ("H10", ["해당없음"], "자산"),
    ("P01", "아니오", "전역"), ("H01", "true", "전역"),
    ("H02", "30세이상", "전역"), ("H02", ["그냥"], "전역"),
    ("H05", "없음", "전역"), ("H06", "없음", "전역"),
])
def test_answer_and_prepare_reject_the_same_wrong_forms(qid, value, unit):
    from yangdo import facts as F
    q = _q(qid)
    assert F.form_problem(q, value)
    f = {"자산": [{"id": "A"}]}
    with pytest.raises(ValueError, match="받는 형식"):
        Q.answer(f, qid, value, 자산="A" if unit == "자산" else None)


@pytest.mark.parametrize("qid,value", [
    ("A07", True), ("A07", False), ("X04", []), ("X04", ["사원용", "소송3년"]), ("X04", ["해당없음"]),
    ("A06", "일괄"), ("A02", "모름"), ("P01", False), ("H01", True), ("H02", ["30세이상"]), ("H05", ["없음"]),
    ("H06", []), ("P04", "단독"), ("P04", {"구분": "공동", "분자": 1, "분모": 2}),
])
def test_answer_accepts_the_forms_prepare_accepts(qid, value):
    from yangdo import facts as F
    assert F.form_problem(_q(qid), value) is None
    f = {"자산": [{"id": "A"}]}
    unit = Q.unit_kind(_q(qid))
    Q.answer(f, qid, value, 자산="A" if unit == "자산" else None)


def test_wrongly_typed_value_is_asked_again_instead_of_counted_as_answered():
    f = copy.deepcopy(CASES["D"])
    f["자산"][0]["중과배제_사유"] = "해당없음"
    assert "X04" in [q["id"] for q in Q.next_questions(f, limit=None)["다음"]]
    g = Q.answer(f, "X04", ["해당없음"], 자산="D")
    assert "X04" not in [q["id"] for q in Q.next_questions(g, limit=None)["다음"]]
    assert g["자산"][0]["중과배제_사유"] == ["해당없음"]


def test_moreum_and_right_forms_still_count_as_answered():
    f = copy.deepcopy(CASES["D"])
    assert "X04" not in [q["id"] for q in Q.next_questions(f, limit=None)["다음"]]
    f["자산"][0]["중과배제_사유"] = None
    g = Q.answer(f, "X04", Q.MOREUM, 자산="D")
    assert "X04" not in [q["id"] for q in Q.next_questions(g, limit=None)["다음"]]
