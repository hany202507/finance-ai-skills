# -*- coding: utf-8 -*-
import copy
from fractions import Fraction

import pytest

from cases import CASES
from yangdo import facts as F


def prep(name, mutate=None):
    f = copy.deepcopy(CASES[name])
    if mutate:
        mutate(f)
    return F.prepare(f)


def test_dates_for_all_cases():
    p = prep("A")
    assert p["시기"]["A"] == {"취득일": "2014-11-01", "취득근거": p["시기"]["A"]["취득근거"],
                             "양도일": "2026-11-15", "양도근거": p["시기"]["A"]["양도근거"]}
    assert p["질문"] == [] and p["다루지않음"] == []
    for name in CASES:
        if name != "L":
            q = prep(name)
            assert q["질문"] == [] and q["다루지않음"] == [], name


def test_before_2025_is_out_of_scope():
    p = prep("L")
    assert p["다루지않음"][0]["자산"] == "L" and "2025-01-01" in p["다루지않음"][0]["내용"]


@pytest.mark.parametrize("path,value,plan", [
    (("자산", 0, "종류"), "분양권", "5"),
    (("자산", 0, "종류"), "기타자산", "없음"),
    (("자산", 0, "양도", "원인"), "부담부증여", "5"),
    (("자산", 0, "취득", "원인"), "상속", "5"),
    (("자산", 0, "계약금액일치"), False, "없음"),
])
def test_scope(path, value, plan):
    def m(f):
        node = f
        for k in path[:-1]:
            node = node[k]
        node[path[-1]] = value
    p = prep("B", m)
    assert p["다루지않음"] and p["다루지않음"][0]["계획"] == plan


def test_household_specials_out_of_scope():
    p = prep("B", lambda f: f["세대"].update(특례주택=["상속주택"]))
    assert p["다루지않음"][0]["계획"] == "5"
    assert prep("B", lambda f: f["세대"].update(특례주택=["없음"]))["다루지않음"] == []


def test_non_resident():
    p = prep("A", lambda f: f["신고인"].update(거주자=False))
    assert p["다루지않음"][0]["계획"] == "없음"


def test_missing_dates_ask():
    p = prep("A", lambda f: f["자산"][0]["양도"].update(잔금일=None))
    assert p["질문"][0]["문항"] == "A11"
    p = prep("A", lambda f: f["자산"][0]["취득"].update(잔금일=None))
    assert p["질문"][0]["문항"] == "A17"


def test_land_use_scope():
    p = prep("F", lambda f: f["자산"][0].update(토지사용현황="나대지"))
    assert p["다루지않음"][0]["계획"] == "5"
    p = prep("F", lambda f: f["자산"][0].update(토지사용현황=None))
    assert p["질문"][0]["문항"] == "A21"


def test_expropriation_note_and_other_sales_note():
    p = prep("B", lambda f: (f["자산"][0]["양도"].update(원인="수용"), f["연간"].update(다른양도=True)))
    assert len(p["확인사항"]) == 2


def test_personal_keys_rejected():
    f = copy.deepcopy(CASES["A"])
    f["자산"][0]["주민등록번호"] = "000000-0000000"
    with pytest.raises(F.FactsError):
        F.check_personal(f)
    F.check_personal(CASES["A"])


def test_houses_at_excludes_sold_earlier():
    f = CASES["BC"]
    p = F.prepare(f)
    assert {h["id"] for h in F.houses_at(f, F.dates.to_date("2026-10-30"), p)} == {"H1", "H2", "H9"}
    assert {h["id"] for h in F.houses_at(f, F.dates.to_date("2026-11-20"), p)} == {"H1", "H9"}


def test_need_and_get():
    a = CASES["A"]["자산"][0]
    assert F.get(a, "양도.잔금일") == "2026-11-15" and F.get(a, "없는.키") is None
    with pytest.raises(F.Missing) as e:
        F.need(a, "없는키", "M99", "A")
    assert e.value.to_dict() == {"문항": "M99", "자산": "A", "내용": "없는키 가 필요합니다"}


def test_share():
    assert F.share({"지분": "단독"}) == 1
    assert F.share({"지분": {"구분": "공동", "분자": 1, "분모": 2}}) == Fraction(1, 2)
    assert F.share({}) == 1
