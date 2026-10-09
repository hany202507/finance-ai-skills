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


# ---- 금액·자산 id·거주기간·취득일 순서 검사 (T9b) ----
WHOLE_MSG = "금액은 원 단위 정수로 적습니다"
NONNEG_MSG = "금액은 0 이상이어야 합니다"


def _set(path, value):
    """자산 0번 아래 경로에 값을 넣는 변경 함수. 경로 마지막이 정수면 목록 칸이다."""
    def m(f):
        node = f["자산"][0]
        for k in path[:-1]:
            node = node[k]
        node[path[-1]] = value
    return m


def _expense_item(group, amount):
    def m(f):
        f["자산"][0]["필요경비"][group] = [{"내용": "공사", "지급일": "2020-03-02", "금액": amount,
                                          "증빙종류": "세금계산서", "상대방": "합성업체"}]
    return m


def _house_price(value):
    def m(f):
        f["세대"]["주택목록"][1]["양도당시기준시가"] = value
    return m


def _only(p, 문항):
    assert [q["문항"] for q in p["질문"]] == [문항], p["질문"]
    return p["질문"][0]


@pytest.mark.parametrize("mutate,문항,자산", [
    (_set(("전체양도가액",), "1억"), "M01", "B"),
    (_set(("전체양도가액",), "700000000"), "M01", "B"),
    (_set(("전체양도가액",), 700000000.5), "M01", "B"),
    (_set(("전체양도가액",), True), "M01", "B"),
    (_set(("전체취득가액",), "8억"), "M06", "B"),
    (_set(("양도", "매수인부담세액"), "없음"), "A14", "B"),
    (_set(("필요경비", "취득세"), "백만"), "M07", "B"),
    (_expense_item("취득부대", "3백만"), "M08", "B"),
    (_expense_item("자본적지출", 1.5), "M09", "B"),
    (_expense_item("기타", False), "M10", "B"),
    (_expense_item("양도비", "2천만"), "M11", "B"),
    (_set(("감가상각비",), 1.5), "M12", "B"),
    (_set(("매매사례가액",), "5억"), "M21", "B"),
    (_set(("감정가액",), [500000000, "5억"]), "M21", "B"),
    (_set(("기준시가",), {"취득": {"주택": "4억"}, "양도": {"주택": 650000000}}), "M22", "B"),
    (_set(("기준시가",), {"취득": {"주택": 400000000}, "양도": {"주택": 650000000.5}}), "M22", "B"),
    (_house_price("3억"), "X01", "H9"),
])
def test_money_not_whole_number_asks(mutate, 문항, 자산):
    q = _only(prep("B", mutate), 문항)
    assert q["자산"] == 자산 and q["내용"] == WHOLE_MSG


@pytest.mark.parametrize("mutate", [
    _set(("전체양도가액",), 1_500_000_000.0),
    _set(("필요경비", "취득세"), 0),
    _set(("감가상각비",), None),
    _set(("매매사례가액",), None),
    _set(("감정가액",), []),
    _set(("기준시가",), {"취득": {"주택": 400_000_000, "토지": 0}, "양도": {"주택": None}}),
    _house_price(200_000_000),
    _house_price(None),
])
def test_money_whole_or_absent_passes(mutate):
    p = prep("B", mutate)
    assert p["질문"] == [] and p["다루지않음"] == []


@pytest.mark.parametrize("mutate,문항", [
    (_set(("전체양도가액",), -1), "M01"),
    (_set(("전체취득가액",), -500000000), "M06"),
    (_set(("필요경비", "취득세"), -1), "M07"),
    (_expense_item("자본적지출", -10_000_000), "M09"),
    (_set(("감가상각비",), -1), "M12"),
    (_set(("감정가액",), [500000000, -1]), "M21"),
    (_set(("기준시가",), {"취득": {"주택": -400000000}, "양도": {"주택": 650000000}}), "M22"),
    (_house_price(-1), "X01"),
])
def test_negative_money_asks(mutate, 문항):
    q = _only(prep("B", mutate), 문항)
    assert q["내용"] == NONNEG_MSG


def test_duplicate_asset_id_rejected():
    f = copy.deepcopy(CASES["BC"])
    f["자산"][1]["id"] = "B"
    with pytest.raises(F.FactsError) as e:
        F.prepare(f)
    assert str(e.value) == "자산 id 가 겹칩니다: B"


@pytest.mark.parametrize("bad", [None, "", "  "])
def test_missing_or_empty_asset_id_rejected(bad):
    f = copy.deepcopy(CASES["A"])
    if bad is None:
        del f["자산"][0]["id"]
    else:
        f["자산"][0]["id"] = bad
    with pytest.raises(F.FactsError):
        F.prepare(f)


@pytest.mark.parametrize("bad", [
    [["2014-11-01"]],
    [["2014-11-01", "2026-11-15", "2027-01-01"]],
    [["2014-11-01", None]],
    [[None, "2026-11-15"]],
    [["2014.11.01", "2026-11-15"]],
    [["2020-01-01", "2019-01-01"]],
    ["2014-11-01"],
    "2014-11-01",
])
def test_malformed_residence_period_asks(bad):
    q = _only(prep("A", _set(("거주기간",), bad)), "H07")
    assert q["자산"] == "A" and q["내용"]


def test_residence_period_valid_forms_pass():
    for ok in ([], [["2014-11-01", "2026-11-15"]], [["2014-11-01", "2018-01-01"], ["2020-01-01", "2026-11-15"]],
               [("2014-11-01", "2014-11-01")], None):
        p = prep("A", _set(("거주기간",), ok))
        assert p["질문"] == [], ok


def test_acquisition_after_transfer_asks():
    q = _only(prep("A", _set(("취득", "잔금일"), "2027-01-01")), "A17")
    assert q["자산"] == "A" and q["내용"] == "취득일이 양도일보다 늦습니다"


def test_new_build_acquisition_after_transfer_asks_a18():
    def m(f):
        f["자산"][0]["취득"].update(원인="신축", 잔금일=None, 사용승인일="2027-01-01")
    q = _only(prep("B", m), "A18")
    assert q["내용"] == "취득일이 양도일보다 늦습니다"


def test_acquisition_same_day_as_transfer_is_allowed():
    p = prep("A", _set(("취득", "잔금일"), "2026-11-15"))
    assert p["질문"] == [] and p["시기"]["A"]["취득일"] == "2026-11-15"
