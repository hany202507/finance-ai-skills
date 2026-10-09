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


@pytest.mark.parametrize("key", ["주소", "도로명주소", "상세주소"])
def test_address_keys_rejected(key):
    f = copy.deepcopy(CASES["A"])
    f["자산"][0][key] = "합성시 합성로 1"
    with pytest.raises(F.FactsError):
        F.check_personal(f)


def test_resident_number_value_rejected():
    f = copy.deepcopy(CASES["A"])
    f["자산"][0]["메모"] = "합성 900101-1234567"
    with pytest.raises(F.FactsError):
        F.check_personal(f)


def test_house_without_acquisition_date_asks():
    f = copy.deepcopy(CASES["BC"])
    f["세대"]["주택목록"][2]["취득일"] = None
    p = F.prepare(f)
    with pytest.raises(F.Missing) as e:
        F.houses_at(f, F.dates.to_date("2026-10-30"), p)
    assert e.value.문항 == "H04"


def test_unknown_kind_asks_and_bad_date_asks():
    p = prep("B", lambda f: f["자산"][0].update(종류="주텍"))
    assert p["질문"][0]["문항"] == "P02"
    p = prep("B", lambda f: f["자산"][0]["양도"].update(잔금일="2026.11.20"))
    assert p["질문"][0]["문항"] == "A11"


def test_new_build_question_text():
    p = prep("B", lambda f: f["자산"][0]["취득"].update(원인="신축", 잔금일=None))
    assert p["질문"][0]["문항"] == "A18" and "사용승인일" in p["질문"][0]["내용"]


@pytest.mark.parametrize("bad", ["공동", {"구분": "공동", "분자": 3, "분모": 2}, {"구분": "공동", "분자": 1, "분모": 0}])
def test_share_validation(bad):
    with pytest.raises(F.FactsError):
        F.share({"지분": bad})


@pytest.mark.parametrize("where", ["asset", "acq", "house"])
def test_address_string_in_location_slot_rejected(where):
    f = copy.deepcopy(CASES["B"])
    s = "부산광역시 해운대구 우동 1-1 합성아파트"
    if where == "asset":
        f["자산"][0]["소재지"] = s
    elif where == "acq":
        f["자산"][0]["취득당시소재지"] = s
    else:
        f["세대"]["주택목록"][1]["소재지"] = s
    with pytest.raises(F.FactsError):
        F.check_personal(f)


def test_long_digit_run_is_not_resident_number():
    f = copy.deepcopy(CASES["A"])
    f["자산"][0]["메모"] = "계약번호 2026111512345678"
    F.check_personal(f)


def test_house_bad_date_asks():
    f = copy.deepcopy(CASES["BC"])
    f["세대"]["주택목록"][2]["취득일"] = "2015.03.01"
    with pytest.raises(F.Missing) as e:
        F.houses_at(f, F.dates.to_date("2026-10-30"), F.prepare(f))
    assert e.value.문항 == "H04"


@pytest.mark.parametrize("bad", [{"분자": 1, "분모": 2}, {"구분": "공동", "분자": 1.5, "분모": 2}])
def test_share_more_validation(bad):
    with pytest.raises(F.FactsError):
        F.share({"지분": bad})


def test_all_cases_pass_personal_check():
    for f in CASES.values():
        F.check_personal(f)
