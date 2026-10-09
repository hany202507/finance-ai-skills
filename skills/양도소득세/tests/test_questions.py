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


def replay(oracle):
    f = {"자산": [{"id": a["id"]} for a in oracle["자산"]]}
    asked = []
    for _ in range(400):
        nq = Q.next_questions(f)
        if not nq["다음"]:
            return f, asked
        q = nq["다음"][0]
        v = oracle_value(oracle, q)
        f = Q.answer(f, q["id"], Q.MOREUM if v is None else v, 자산=q["자산"], 주택=q["주택"])
        asked.append(q["id"])
    raise AssertionError("문답이 끝나지 않는다: %s" % asked[-10:])


def dialogue(name):
    return replay(CASES[name])


@pytest.mark.parametrize("name", ["A", "B", "D", "E", "F", "G", "G2", "I", "I2", "J", "K2"])
def test_dialogue_reaches_same_result(name):
    f, asked = dialogue(name)
    r = _engine().calculate(f, today="2026-10-09")
    assert r["상태"] == "완료", (asked, r["질문"], r["다루지않음"])
    assert r["계산"]["합계"]["산출세액"] == EXPECT[name]["산출세액"]
    assert len(asked) == len(set(asked)) or name in ("K2", "J")  # 주택마다 묻는 문항은 id 가 겹친다


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


def test_answer_rejects_malformed_answers():
    f = {"자산": [{"id": "A", "종류": "주택"}]}
    bad = [("A11", "2026.11.15", {"자산": "A"}),              # 날짜 형식
           ("A11", "2026-13-40", {"자산": "A"}),
           ("A01", "서울특별시 송파구 잠실동", {"자산": "A"}),   # 주소 문자열
           ("A01", {"시도": "서울특별시"}, {"자산": "A"}),       # 시군구 없음
           ("P04", "공동", {"자산": "A"}),                     # 분자 분모 없음
           ("A11", None, {"자산": "A"}),                      # 빈 답은 모름이 아니다
           ("A17", {"잔금일": None, "등기접수일": None}, {"자산": "A"}),
           ("A17", {"결제일": "2014-11-01"}, {"자산": "A"}),   # 없는 키
           ("A17", "2014-11-01", {"자산": "A"}),               # 키가 둘이면 dict
           ("H07", [["2014-11-01"]], {"자산": "A"}),           # 구간은 둘이다
           ("H07", [["2020-01-01", "2014-11-01"]], {"자산": "A"}),
           ("H04", [{"소재지": {"시도": "서울특별시", "시군구": "마포구"}}], {}),   # id 없음
           ("H04", [{"id": "H1", "자산id": None}], {}),        # 취득일 없는 다른 집
           ("H04", [{"id": "H1", "자산id": "Z", "취득일": "2014-11-01"}], {}),   # 판 집을 잇지 않음
           ("X09", True, {}),                                  # 없는 문항
           ]
    for qid, v, kw in bad:
        with pytest.raises(ValueError):
            Q.answer(f, qid, v, **kw)
    ok = Q.answer(f, "P04", {"구분": "공동", "분자": 1, "분모": 2}, 자산="A")
    assert ok["자산"][0]["지분"]["분모"] == 2


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
