# -*- coding: utf-8 -*-
import copy
from fractions import Fraction

import pytest

from cases import CASES, addr, asset, facts, house
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
    (("자산", 0, "양도", "원인"), "교환", "5"),
    (("자산", 0, "양도", "원인"), "기타", "5"),
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


@pytest.mark.parametrize("원인,문구", [("교환", "교환으로 양도한 자산"), ("기타", "기타 원인으로 양도한 자산")])
def test_exchange_and_other_transfer_name_the_cause(원인, 문구):
    p = prep("B", lambda f: f["자산"][0]["양도"].update(원인=원인))
    assert p["다루지않음"] == [{"자산": "B", "내용": 문구, "계획": "5"}]
    assert p["시기"] == {}


def test_expropriation_transfer_is_out_of_scope_without_the_old_note():
    p = prep("B", lambda f: f["자산"][0]["양도"].update(원인="수용"))
    assert p["다루지않음"] == [{"자산": "B", "내용": "수용으로 양도한 자산(양도시기 시행령 제162조①7호, 조특법 감면)", "계획": "5"}]
    assert p["시기"] == {} and p["확인사항"] == []


@pytest.mark.parametrize("원인", ["매매", "경매"])
def test_sale_and_auction_are_in_scope(원인):
    p = prep("B", lambda f: f["자산"][0]["양도"].update(원인=원인))
    assert p["다루지않음"] == [] and p["질문"] == []


def test_unknown_transfer_cause_asks_p03():
    p = prep("B", lambda f: f["자산"][0]["양도"].update(원인="증여"))
    assert p["질문"][0]["문항"] == "P03" and "증여" in p["질문"][0]["내용"]


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


def test_other_sales_note():
    p = prep("B", lambda f: f["연간"].update(다른양도=True))
    assert len(p["확인사항"]) == 1 and "제104조⑤" in p["확인사항"][0]


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


EMPTY_MSG = "금액이 비어 있습니다"


def _expense_raw(group, item):
    def m(f):
        f["자산"][0]["필요경비"][group] = [item]
    return m


def _item(**kw):
    base = {"내용": "공사", "지급일": "2020-03-02", "금액": 10_000_000, "증빙종류": "세금계산서", "상대방": "합성업체"}
    base.update(kw)
    return base


def _item_without_amount():
    it = _item()
    del it["금액"]
    return it


@pytest.mark.parametrize("mutate,문항", [
    (_set(("감정가액",), [500000000, None]), "M21"),
    (_set(("감정가액",), [None]), "M21"),
    (_expense_item("취득부대", None), "M08"),
    (_expense_item("자본적지출", None), "M09"),
    (_expense_item("기타", None), "M10"),
    (_expense_item("양도비", None), "M11"),
    (_expense_raw("취득부대", _item_without_amount()), "M08"),
    (_expense_raw("자본적지출", _item_without_amount()), "M09"),
    (_expense_raw("기타", _item_without_amount()), "M10"),
    (_expense_raw("양도비", _item_without_amount()), "M11"),
])
def test_empty_amount_inside_list_asks(mutate, 문항):
    q = _only(prep("B", mutate), 문항)
    assert q["자산"] == "B" and q["내용"] == EMPTY_MSG


def test_zero_amount_inside_list_passes():
    p = prep("B", lambda f: (_expense_item("양도비", 0)(f), _set(("감정가액",), [0, 500000000])(f)))
    assert p["질문"] == [] and p["다루지않음"] == []


@pytest.mark.parametrize("mutate,문항", [
    (_set(("필요경비",), "없음"), "M07"),
    (_set(("필요경비",), []), "M07"),
    (_set(("필요경비", "취득부대"), {"금액": 1}), "M08"),
    (_set(("필요경비", "자본적지출"), "공사"), "M09"),
    (_set(("필요경비", "기타"), 5), "M10"),
    (_set(("필요경비", "양도비"), "중개료"), "M11"),
    (_expense_raw("취득부대", "중개료"), "M08"),
    (_expense_raw("자본적지출", 10_000_000), "M09"),
    (_expense_raw("기타", ["공사"]), "M10"),
    (_expense_raw("양도비", None), "M11"),
    (_set(("감정가액",), "500000000"), "M21"),
    (_set(("감정가액",), {"금액": 500000000}), "M21"),
    (_set(("기준시가",), 400000000), "M22"),
    (_set(("기준시가",), []), "M22"),
    (_set(("기준시가",), {"취득": 400000000, "양도": {"주택": 650000000}}), "M22"),
    (_set(("기준시가",), {"취득": {"주택": 400000000}, "양도": [650000000]}), "M22"),
])
def test_wrong_shape_asks_instead_of_crashing(mutate, 문항):
    q = _only(prep("B", mutate), 문항)
    assert q["자산"] == "B" and q["내용"]


def test_wrong_shape_messages_name_the_expected_form():
    assert "목록" in _only(prep("B", _set(("필요경비", "자본적지출"), "공사")), "M09")["내용"]
    assert "목록" in _only(prep("B", _set(("감정가액",), "5억")), "M21")["내용"]
    assert _only(prep("B", _set(("기준시가",), 4)), "M22")["내용"] == F.SHAPE_PRICE_MSG


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


@pytest.mark.parametrize("bad", [1, 1.5, True, " B", "B ", "B" + chr(10), ["B"], {"id": "B"}])
def test_non_string_or_padded_asset_id_rejected(bad):
    f = copy.deepcopy(CASES["A"])
    f["자산"][0]["id"] = bad
    with pytest.raises(F.FactsError):
        F.prepare(f)


def test_asset_id_string_passes():
    f = copy.deepcopy(CASES["A"])
    f["자산"][0]["id"] = "A-1 아파트"
    assert F.prepare(f)["시기"].keys() == {"A-1 아파트"}


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
    p = prep("A", _set(("취득", "잔금일"), "2027-01-01"))
    q = _only(p, "A17")
    assert q["자산"] == "A" and q["내용"] == "취득일이 양도일보다 늦습니다"
    assert "A" not in p["시기"]


def test_new_build_acquisition_after_transfer_asks_a18():
    def m(f):
        f["자산"][0]["취득"].update(원인="신축", 잔금일=None, 사용승인일="2027-01-01")
    q = _only(prep("B", m), "A18")
    assert q["내용"] == "취득일이 양도일보다 늦습니다"


def test_acquisition_same_day_as_transfer_is_allowed():
    p = prep("A", _set(("취득", "잔금일"), "2026-11-15"))
    assert p["질문"] == [] and p["시기"]["A"]["취득일"] == "2026-11-15"


# ---- 자료형 검사 (C1): 엔진이 읽는 예아니오·선택·복수선택 키 ----
@pytest.mark.parametrize("name,mutate,문항", [
    ("D", lambda f: f["자산"][0].update(중과배제_사유="해당없음"), "X04"),    # 글자 단위로 돌아 중과를 빼던 값
    ("D", lambda f: f["자산"][0].update(중과배제_사유=["없는사유"]), "X04"),
    ("D", lambda f: f["자산"][0].update(중과배제_사유=[["해당없음"]]), "X04"),
    ("E", lambda f: f["자산"][0].update(등기="false"), "A07"),
    ("E", lambda f: f["자산"][0].update(등기=0), "A07"),
    ("D", lambda f: f["신고인"].update(거주자="false"), "P01"),
    ("D", lambda f: f["신고인"].update(거주자="아니오"), "P01"),
    ("D", lambda f: f["자산"][0].update(계약금액일치="false"), "M04"),
    ("D", lambda f: f["세대"].update(배우자="false"), "H01"),
    ("D", lambda f: f["세대"].update(특례주택="없음"), "H05"),               # 다루지않음이 되던 값
    ("D", lambda f: f["세대"].update(특례주택=["상속"]), "H05"),
    ("A", lambda f: f["세대"].update(배우자=False, **{"1세대요건": "30세이상"}), "H02"),
    ("A", lambda f: f["세대"].update(배우자=False, **{"1세대요건": ["그냥"]}), "H02"),
    ("D", lambda f: f["자산"][0].update(보유거주예외=["해당없음"]), "H10"),
    ("D", lambda f: f["자산"][0].update(보유거주예외="모름"), "H10"),
    ("D", lambda f: f["자산"][0].update(처분기한연장사유=True), "T03"),
    ("D", lambda f: f["자산"][0].update(정비구역="네"), "X02"),
    ("D", lambda f: f["자산"][0].update(토지거래허가대상=True), "X05"),
    ("D", lambda f: f["자산"][0].update(취득가액_확인="없음"), "M05"),
    ("D", lambda f: f["자산"][0].update(지구해당=True), "A02"),
    ("D", lambda f: f["자산"][0].update(미등기사유="언젠가"), "A08"),
    ("D", lambda f: f["자산"][0].update(지분=["단독"]), "P04"),
    ("D", lambda f: f["자산"][0]["취득"].update(계약금지급일_무주택="true"), "H09"),
    ("D", lambda f: f["세대"].update(기관이전종사자="false"), "T04"),
    ("D", lambda f: f["연간"].update(다른양도="false"), "P05"),
    ("D", lambda f: f["세대"].update(입주권분양권="없음"), "H06"),
    ("D", lambda f: f["세대"].update(주택목록={"id": "H1"}), "H04"),
    ("D", lambda f: f["세대"].update(주택목록=["H1"]), "H04"),
    ("D", lambda f: f["세대"]["주택목록"][1].update(제12호해당="소형"), "X03"),
    ("D", lambda f: f["자산"][0]["취득"].update(원인="언젠가"), "A15"),
])
def test_wrong_form_asks_that_question(name, mutate, 문항):
    p = prep(name, mutate)
    assert 문항 in [q["문항"] for q in p["질문"]], p
    assert p["다루지않음"] == [], p


def test_wrong_form_message_names_the_key_and_the_accepted_codes():
    q = _only(prep("D", lambda f: f["자산"][0].update(중과배제_사유="해당없음")), "X04")
    assert q["자산"] == "D" and q["내용"].startswith("중과배제_사유 의 값 형식이 맞지 않습니다")
    assert "목록" in q["내용"] and "장기임대등록" in q["내용"] and "소송3년" in q["내용"]
    q = _only(prep("E", lambda f: f["자산"][0].update(등기="false")), "A07")
    assert q["내용"].endswith("true 또는 false")
    q = _only(prep("D", lambda f: f["세대"].update(배우자="false")), "H01")
    assert q["자산"] is None


@pytest.mark.parametrize("name,mutate", [
    ("D", lambda f: f["자산"][0].update(중과배제_사유=[])),
    ("D", lambda f: f["자산"][0].update(중과배제_사유=["해당없음"])),
    ("D", lambda f: f["자산"][0].update(중과배제_사유=["사원용", "소송3년"])),
    ("D", lambda f: f["자산"][0].update(중과배제_사유=None)),
    ("D", lambda f: f["세대"].update(특례주택=["없음"])),
    ("D", lambda f: f["세대"].update(특례주택=None)),
    ("A", lambda f: f["세대"].update(배우자=False, **{"1세대요건": ["30세이상", "소득독립"]})),
    ("D", lambda f: f["자산"][0].update(지구해당="아니오")),
    ("D", lambda f: f["자산"][0].update(지분={"구분": "공동", "분자": 1, "분모": 2})),
    ("D", lambda f: f["자산"][0].update(지분="단독")),
    ("E", lambda f: f["자산"][0].update(등기=False)),
])
def test_right_form_passes(name, mutate):
    p = prep(name, mutate)
    assert p["질문"] == [] and p["다루지않음"] == [], p


def test_form_check_skips_keys_that_do_not_matter():
    """토지만 파는 사실관계에서 세대 키는 엔진이 읽지 않아 자료형을 따지지 않는다. 단 신고인·연간 키는 따진다."""
    p = prep("F", lambda f: f["세대"].update(배우자="false"))
    assert p["질문"] == []
    p = prep("F", lambda f: f["연간"].update(다른양도="false"))
    assert [q["문항"] for q in p["질문"]] == ["P05"]


def test_non_resident_string_is_a_question_not_a_resident():
    p = prep("D", lambda f: f["신고인"].update(거주자="false"))
    assert [q["문항"] for q in p["질문"]] == ["P01"] and p["다루지않음"] == []


def test_form_table_comes_from_question_definitions():
    """자료형 표는 문항.json 의 답형식 하나다. 엔진이 읽지 않는 키(COLLECT_ONLY)와 신규 주택 키는 들지 않는다."""
    rules = F.form_rules()
    paths = {path for _, _, path in rules}
    assert {"신고인.거주자", "세대.특례주택", "세대.1세대요건", "중과배제_사유", "등기", "계약금액일치", "보유거주예외"} <= paths
    assert not any("[신규]" in q["키"][0] for q, _, _ in rules)
    collect = {k.split(".")[-1] for k in F.COLLECT_ONLY}
    assert not collect & {p.split(".")[-1] for p in paths}
    assert F.form_rules() is rules   # 한 번만 만든다


def test_form_problem_by_answer_form():
    qs = {q["id"]: q for q in F.load_questions()["문항"]}
    assert F.form_problem(qs["A07"], True) is None and F.form_problem(qs["A07"], "true")
    assert F.form_problem(qs["A07"], 1)
    assert F.form_problem(qs["A06"], "일괄") is None and F.form_problem(qs["A06"], "통째")
    assert F.form_problem(qs["A06"], ["일괄"]) and F.form_problem(qs["A06"], {"구분": "일괄"})
    assert F.form_problem(qs["X04"], ["사원용"]) is None and F.form_problem(qs["X04"], []) is None
    assert F.form_problem(qs["X04"], "사원용") and F.form_problem(qs["X04"], ["사원용", 3])
    assert F.form_problem(qs["P04"], {"구분": "공동", "분자": 1, "분모": 2}) is None   # 지분만 묶음으로도 답한다
    assert F.form_problem(qs["P04"], {"구분": "그냥"})
    assert F.form_problem(qs["H06"], []) is None and F.form_problem(qs["H06"], "없음")
    assert F.form_problem(qs["A11"], "2026.11.15") is None     # 날짜·금액은 이 함수가 보지 않는다
    assert F.form_problem(qs["P07"], "H1") is None            # 선택지가 없는 선택 문항은 받는 대로 둔다


# ---- 지구 안인지 모르는 답(A02 모름) ----
def _gwanggyo():
    a = asset("G1", "주택", addr("경기도", "수원시 영통구", "이의동"), "2019-03-01", "2026-11-15", 1_500_000_000, 800_000_000,
              거주기간=[["2019-03-01", "2026-11-15"]])
    return facts([a], [house("H1", a["소재지"], "2019-03-01", 자산id="G1")])


def test_district_unknown_answer_is_out_of_scope_not_a_loop():
    f = _gwanggyo()
    f["자산"][0]["지구해당"] = "모름"
    p = F.prepare(f)
    assert p["질문"] == [] and len(p["다루지않음"]) == 1
    o = p["다루지않음"][0]
    assert o["자산"] == "G1" and "지구 안인지 확인되지 않음" in o["내용"] and o["계획"] == "없음"
    assert F.prepare(_gwanggyo())["다루지않음"] == []   # 모르는 답이 없으면 그대로 판정으로 가 A02 를 묻는다


def test_district_unknown_marker_in_list_is_the_same():
    f = _gwanggyo()
    f["모름"] = ["A02:G1"]
    assert "지구 안인지 확인되지 않음" in F.prepare(f)["다루지않음"][0]["내용"]


def test_district_unknown_does_not_block_land_or_unregistered_house():
    f = copy.deepcopy(CASES["F"])
    f["자산"][0]["지구해당"] = "모름"
    assert F.prepare(f)["다루지않음"] == []
    f = copy.deepcopy(CASES["E"])
    f["자산"][0]["지구해당"] = "모름"
    assert F.prepare(f)["다루지않음"] == []


# ---- 취득원인·미등기 토지 ----
def test_other_acquisition_cause_is_out_of_scope():
    p = prep("B", lambda f: f["자산"][0]["취득"].update(원인="기타"))
    assert p["다루지않음"] == [{"자산": "B", "내용": "기타 원인으로 취득한 자산(점유취득·환지 등 취득시기 규칙이 다름)", "계획": "5"}]
    assert p["시기"] == {}


@pytest.mark.parametrize("원인,문구", [("상속", "상속으로 취득한 자산"), ("증여", "증여로 취득한 자산"),
                                      ("부담부증여", "부담부증여로 취득한 자산"), ("조합원", "조합원으로 취득한 자산")])
def test_acquisition_cause_particle(원인, 문구):
    p = prep("B", lambda f: f["자산"][0]["취득"].update(원인=원인))
    assert p["다루지않음"] == [{"자산": "B", "내용": 문구, "계획": "5"}]


@pytest.mark.parametrize("word,want", [("교환", "교환으로"), ("기타", "기타로"), ("증여", "증여로"), ("부담부증여", "부담부증여로"),
                                       ("상속", "상속으로"), ("조합원", "조합원으로"), ("수용", "수용으로"), ("경매", "경매로"),
                                       ("물", "물로"), ("분양", "분양으로"), ("A", "A로")])
def test_with_ro_picks_ro_after_vowel_or_rieul(word, want):
    assert F.with_ro(word) == want


def test_unregistered_land_still_needs_land_use():
    """등기하지 않은 토지도 제외 사유(장기할부 등)가 있으면 비사업용 토지 판정이 필요하다. 사용 현황을 건너뛰지 않는다."""
    def m(use):
        return lambda f: f["자산"][0].update(미등기사유="장기할부", 토지사용현황=use)
    assert [q["문항"] for q in prep("E", m(None))["질문"]] == ["A21"]
    assert prep("E", m("나대지"))["다루지않음"][0]["계획"] == "5"
    assert prep("E", m("사업용"))["다루지않음"] == []
