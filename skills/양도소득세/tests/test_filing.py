# -*- coding: utf-8 -*-
import copy
import json
import os

import pytest

from yangdo import edition, engine, filing
from cases import CASES
import filers


class FakeBjd:
    def lookup(self, 시도, 시군구, 읍면동, on=None):
        return {"공덕동": "1144010200", "성수동": None}.get(읍면동, "1100000000")

    def candidates(self, *a):
        return ["1120011400", "1120011500"]

    def exists(self, c):
        return True


def _ed(expected):
    """공개본은 F06(홈택스 사용자 ID)을 묻지 않는다(그 값은 전자신고 파일에만 쓴다). 기대 문항에서 F06 을 뺀다."""
    if not edition.PUBLIC:
        return expected
    if isinstance(expected, set):
        return {x for x in expected if x != "F06"}
    return [x for x in expected if x[0] != "F06"]


def test_valid_filer_has_no_questions_after_codes_filled():
    f = filers.get("A")
    f["자산"]["A"]["법정동코드"] = "1171010100"
    assert filing.questions(filing.load(f), CASES["A"], None, bjd=FakeBjd()) == []


def test_ambiguous_dong_asks_f04():
    f = filers.get("S1")
    qs = filing.questions(filing.load(f), CASES["S1"], None, bjd=FakeBjd())
    assert {"문항": "F04", "자산": "S1"} == {k: qs[0][k] for k in ("문항", "자산")}


def test_bad_rrn_is_rejected():
    f = filers.get("A")
    f["신고인"]["주민등록번호"] = "0013011234567"        # 13월. 검증번호만 틀린 번호는 오류가 아니라 경고다
    with pytest.raises(filing.FilingError):
        filing.load(f)


def test_tax_agent_is_out_of_scope():
    f = filers.get("A")
    f["세무대리인"] = {"성명": "합성세무사"}
    with pytest.raises(filing.FilingError, match="세무대리"):
        filing.load(f)


def test_buyer_shares_must_sum_to_one():
    f = filers.get("A")
    f["양수인"][0]["지분"] = {"분자": 1, "분모": 2}
    qs = filing.questions(filing.load(f), CASES["A"], None, bjd=FakeBjd())
    assert any(q["문항"] == "F02" for q in qs)


def test_every_asset_needs_a_buyer_and_lot():
    f = filers.get("BF")
    del f["자산"]["F"]
    qs = filing.questions(filing.load(f), CASES["BF"], None, bjd=FakeBjd())
    assert any(q["문항"] == "F04" and q["자산"] == "F" for q in qs)


# ---- 여기부터 이 태스크가 더한 시험 ----

def biz(first9):
    """사업자등록번호 9자리에 검증번호를 붙인다(가중치 1,3,7,1,3,7,1,3,5, 아홉째 곱의 10의 몫을 더한다)."""
    w = [1, 3, 7, 1, 3, 7, 1, 3, 5]
    s = sum(int(a) * b for a, b in zip(first9, w)) + int(first9[8]) * 5 // 10
    return first9 + str((10 - s % 10) % 10)


def ready(name="A", **codes):
    """법정동코드까지 채운 신고인. 질문이 하나도 안 나오는 기준 상태."""
    f = filers.get(name)
    for k in f["자산"]:
        f["자산"][k]["법정동코드"] = codes.get(k, "1171010100")
    return f


def ask(f, name="A", bjd=None):
    return filing.questions(filing.load(f), CASES[name], None, bjd=bjd or FakeBjd())


def ids(qs):
    return sorted((q["문항"], q["자산"]) for q in qs)


def test_biz_checksum_helper_follows_the_weights():
    # 손계산. 아홉째 자리가 1 이면 합 5, 검증번호 5. 9 이면 9*5=45 에 10의 몫 4 를 더해 합 49, 검증번호 1
    assert biz("000000001") == "0000000015"
    assert biz("000000009") == "0000000091"
    assert filing.biz_ok("0000000091") and not filing.biz_ok("0000000092")


def test_load_accepts_a_path_and_does_not_touch_input(tmp_path):
    f = filers.get("A")
    before = copy.deepcopy(f)
    out = filing.load(f)
    assert f == before and out == dict(before, _경고=[]) and out is not f
    p = tmp_path / "신고인.json"
    p.write_text(json.dumps(f, ensure_ascii=False), encoding="utf-8")
    assert filing.load(str(p)) == out
    assert filing.load(p) == out


def test_load_rejects_unreadable_input(tmp_path):
    p = tmp_path / "x.json"
    p.write_text("{깨진", encoding="utf-8")
    for bad in (str(p), str(tmp_path / "없음.json"), [1, 2], 3):
        with pytest.raises(filing.FilingError):
            filing.load(bad)


def test_business_number_buyer():
    f = ready()
    f["양수인"][0].update(구분="2", 번호=biz("123456789"), 성명="합성주식회사")
    assert filing.load(f)["양수인"][0]["번호"] == biz("123456789")
    assert ask(f) == []
    f["양수인"][0]["번호"] = biz("123456789")[:9] + str((int(biz("123456789")[9]) + 1) % 10)
    with pytest.raises(filing.FilingError, match="사업자"):
        filing.load(f)
    f["양수인"][0]["번호"] = "123"
    with pytest.raises(filing.FilingError, match="사업자"):
        filing.load(f)


def test_buyer_rrn_shape_is_checked_for_everyone():
    f = ready()
    f["양수인"][0]["번호"] = "0013021234567"
    with pytest.raises(filing.FilingError, match="양수인"):
        filing.load(f)
    f["양수인"][0].update(내외국인="9", 번호="5001015234560")     # 외국인등록번호는 검증번호를 보지 않는다
    assert filing.load(f)["_경고"] == []
    f["양수인"][0]["번호"] = "50010152345"
    with pytest.raises(filing.FilingError):
        filing.load(f)
    f["양수인"][0]["번호"] = "5013015234560"                   # 13월
    with pytest.raises(filing.FilingError):
        filing.load(f)


@pytest.mark.parametrize("path,value", [
    (("신고", "구분"), "정기"),
    (("신고", "작성일"), "2026/12/20"),
    (("신고", "작성일"), "2026-02-30"),
    (("신고", "작성일"), "20261220"),
    (("신고", "분납신청"), "예"),
    (("신고", "홈택스ID"), "홈택스아이디"),
    (("신고인", "주민등록번호"), "000101-1234567"),
    (("신고인", "주민등록번호"), "000101123456"),
    (("신고인", "전화"), "02-1234-5678"),
    (("신고인", "전화"), "0212345678901"),
    (("신고인", "성명"), "똠"),
    (("신고인", "성명"), "김합성" * 6),
    (("신고인", "내외국인"), "2"),
    (("신고인", "거주구분"), "2"),
    (("신고인", "거주지국"), "kr"),
    (("신고인", "국적"), "US"),
    (("신고인", "전자메일"), "메일"),
    (("신고인", "주소", "특수지"), "10"),
    (("신고인", "주소", "번지"), "12345"),
    (("신고인", "주소", "번지"), "산1"),
    (("신고인", "주소", "법정동코드"), "11440102"),
    (("신고인", "주소", "아파트명"), "똠방아파트"),
    (("양수인", 0, "구분"), "3"),
    (("양수인", 0, "내외국인"), "0"),
    (("양수인", 0, "성명"), "똠"),
    (("양수인", 0, "전화"), "02-1111-2222"),
    (("양수인", 0, "지분"), {"분자": 0, "분모": 1}),
    (("양수인", 0, "지분"), {"분자": 2, "분모": 1}),
    (("양수인", 0, "지분"), {"분자": 1, "분모": 0}),
    (("양수인", 0, "지분"), {"분자": True, "분모": 1}),
    (("양수인", 0, "지분"), 1),
    (("양수인", 0, "자산"), None),
    (("양수인", 0, "관계코드"), "1"),
    (("양수인", 0, "관계코드"), "ZZZ"),
    (("양수인", 0, "관계코드"), "Z-"),
    (("양수인", 0, "관계코드"), 1),
    (("신고", "분납신청"), 1),
    (("자산", "A", "등기원인"), "0336"),
    (("자산", "A", "등기원인"), {"취득": "336"}),
    (("자산", "A", "등기원인"), {"취득": 336}),
    (("자산", "A", "등기원인"), {"기타": "0336"}),
    (("자산", "A", "특수지"), "x"),
    (("자산", "A", "번지"), "1234a"),
    (("자산", "A", "호"), "12345"),
    (("자산", "A", "법정동코드"), "123"),
    (("자산", "A", "총면적"), {"토지": -1, "건물": 84.0}),
    (("자산", "A", "총면적"), {"토지": "30", "건물": 84.0}),
    (("환급계좌",), {"은행코드": "04", "계좌번호": "123"}),
    (("환급계좌",), {"은행코드": "004", "계좌번호": "12-34"}),
])
def test_format_errors_are_rejected(path, value):
    f = ready()
    cur = f
    for k in path[:-1]:
        cur = cur[k]
    cur[path[-1]] = value
    with pytest.raises(filing.FilingError):
        filing.load(f)


@pytest.mark.parametrize("section", ["신고", "신고인", "자산", "양수인"])
def test_wrong_section_type_is_rejected(section):
    f = ready()
    f[section] = "문자"
    with pytest.raises(filing.FilingError):
        filing.load(f)


def test_valid_variants_are_accepted():
    f = ready()
    f["신고인"].update(전자메일="test@example.com", 전화="021234567")
    f["신고인"]["주소"].update(특수지="9", 번지="0", 호="0", 아파트명="아이파크·논현", 아파트동="", 아파트호="")
    f["자산"]["A"]["총면적"] = {"토지": 0, "건물": 84}
    f["환급계좌"] = {"은행코드": "004", "계좌번호": "123456789012"}
    f["신고"]["분납신청"] = True
    filing.load(f)


def test_foreign_filer_skips_checksum_and_needs_foreign_nationality():
    f = ready()
    f["신고인"].update(내외국인="9", 주민등록번호="5001015234560", 국적="US")
    filing.load(f)
    f["신고인"]["국적"] = "KR"
    with pytest.raises(filing.FilingError, match="국적"):
        filing.load(f)


def test_tax_agent_is_rejected_even_when_everything_else_is_wrong():
    f = ready()
    f["신고"]["구분"] = "정기"
    f["세무대리인"] = {"성명": "합성세무사"}
    with pytest.raises(filing.FilingError, match="세무대리"):
        filing.load(f)


def test_missing_values_become_questions_not_errors():
    f = ready()
    f["신고"].update(구분=None, 작성일=None, 홈택스ID=None, 분납신청=None)
    f["신고인"].update(성명=None, 전화=None)
    f["신고인"]["주소"]["번지"] = None
    f["자산"]["A"]["번지"] = None
    qs = ask(f)
    assert ids(qs) == _ed([("F01", None), ("F03", None), ("F04", "A"), ("F05", None), ("F06", None)])


def test_missing_sections_are_questions():
    f = {"세무대리인": None}
    qs = filing.questions(filing.load(f), CASES["A"], None, bjd=FakeBjd())
    assert ids(qs) == _ed([("F01", None), ("F02", "A"), ("F03", None), ("F04", "A"), ("F05", None), ("F06", None)])


def test_f01_unresolved_home_dong():
    f = ready()
    f["신고인"]["주소"]["읍면동"] = "성수동"
    qs = ask(f)
    assert ids(qs) == [("F01", None)]
    f["신고인"]["주소"]["법정동코드"] = "1120011400"
    assert ask(f) == []


def test_codes_found_by_lookup_pass():
    f = filers.get("A")                                        # 법정동코드 null 이지만 FakeBjd 가 찾는다
    assert ask(f) == []


def test_lookup_gets_the_filing_date():
    seen = []

    class Spy(FakeBjd):
        def lookup(self, 시도, 시군구, 읍면동, on=None):
            seen.append((시도, 시군구, 읍면동, on))
            return "1100000000"

    ask(filers.get("S1"), "S1", bjd=Spy())
    assert ("서울특별시", "마포구", "공덕동", "2026-12-15") in seen
    assert ("서울특별시", "성동구", "성수동", "2026-12-15") in seen


def test_given_code_that_does_not_exist_asks_again():
    class NoCode(FakeBjd):
        def exists(self, c):
            return c != "1171010100"

    assert ids(ask(ready(), bjd=NoCode())) == [("F04", "A")]
    f = ready()
    f["신고인"]["주소"]["법정동코드"] = "1171010100"
    assert ids(ask(f, bjd=NoCode())) == [("F01", None), ("F04", "A")]


def test_f04_lists_candidates():
    qs = ask(filers.get("S1"), "S1")
    text = qs[0]["내용"]
    assert "1120011400" in text and "1120011500" in text


def test_f02_cases():
    f = ready("BF")
    assert ask(f, "BF") == []
    f["양수인"] = [b for b in f["양수인"] if b["자산"] != "F"]
    assert ids(ask(f, "BF")) == [("F02", "F")]
    f = ready("BF")
    f["양수인"].append(dict(f["양수인"][0], 자산="ZZ"))
    assert ids(ask(f, "BF")) == [("F02", "ZZ")]
    f = ready("BF")
    f["양수인"][1]["번호"] = None
    f["양수인"][1]["지분"] = None
    assert ids(ask(f, "BF")) == [("F02", "F")]


def test_f02_two_buyers_summing_to_one_pass():
    f = ready()
    f["양수인"][0]["지분"] = {"분자": 1, "분모": 2}
    f["양수인"].append(dict(f["양수인"][0], 성명="박합성", 번호=filers.rrn("0001021", "56789")))
    assert ask(f) == []
    f["양수인"][1]["지분"] = {"분자": 0.5, "분모": 1}
    assert ask(f) == []
    f["양수인"][1]["지분"] = {"분자": 1, "분모": 3}
    assert ids(ask(f)) == [("F02", "A")]
    f["양수인"][1]["지분"] = {"분자": 3, "분모": 4}
    assert ids(ask(f)) == [("F02", "A")]


def test_f03_only_when_value_missing():
    f = ready()
    f["신고"]["분납신청"] = False
    assert ask(f) == []
    f["신고"]["분납신청"] = True
    assert ask(f) == []
    del f["신고"]["분납신청"]
    assert ids(ask(f)) == [("F03", None)]


def test_questions_do_not_echo_personal_values():
    f = ready()
    f["신고인"]["주소"]["읍면동"] = "성수동"
    f["양수인"][0]["지분"] = {"분자": 1, "분모": 2}
    f["신고"]["홈택스ID"] = None
    secret = [f["신고인"]["성명"], f["신고인"]["주민등록번호"], f["양수인"][0]["성명"], f["양수인"][0]["번호"],
              f["신고인"]["주소"]["아파트명"], f["신고인"]["전화"], "성수동", "공덕동"]
    qs = ask(f)
    assert ids(qs) == _ed([("F01", None), ("F02", "A"), ("F06", None)])
    text = json.dumps(qs, ensure_ascii=False)
    for s in secret:
        assert s not in text


def test_question_text_style():
    f = filers.get("S1")
    f["신고"].update(구분=None, 홈택스ID=None, 분납신청=None)
    f["양수인"] = []
    f["신고인"]["성명"] = None
    qs = filing.questions(filing.load(f), CASES["S1"], None, bjd=FakeBjd())
    assert {q["문항"] for q in qs} == _ed({"F01", "F02", "F03", "F04", "F05", "F06"})
    for q in qs:
        assert set(q) == {"문항", "자산", "내용"}
        assert q["내용"] and chr(0x2014) not in q["내용"] and not q["내용"].rstrip().endswith("?")


def test_default_bjd_is_loaded_late():
    f = ready()                    # 법정동코드가 모두 적혀 있어도 존재 검사 때문에 bjd 를 읽는다
    try:
        from yangdo import bjd  # noqa: F401
    except ImportError:
        with pytest.raises(ImportError):
            filing.questions(filing.load(f), CASES["A"], None)
        return
    assert isinstance(filing.questions(filing.load(f), CASES["A"], None), list)


# ---- 컨트롤러가 묶음 1 검토 뒤에 정한 계약(2026-10-11) ----

def fw(text):
    """ASCII 숫자를 전각 숫자로 바꾼다. CP949 2바이트라 고정길이 칸을 깨뜨린다."""
    return "".join(chr(ord(c) + 0xFEE0) if c.isdigit() else c for c in text)


def facts_with(**changes):
    """사례 A 의 사실관계에서 자산 A 의 값을 바꾼다. 두 단계 키는 취득__원인 처럼 준다."""
    facts = copy.deepcopy(CASES["A"])
    for k, v in changes.items():
        if "__" in k:
            p, c = k.split("__")
            facts["자산"][0][p][c] = v
        else:
            facts["자산"][0][k] = v
    return facts


def ask_facts(f, facts, bjd=None):
    return filing.questions(filing.load(f), facts, None, bjd=bjd or FakeBjd())


def wrong_check_digit(num):
    return num[:12] + str((int(num[12]) + 1) % 10)


@pytest.mark.parametrize("num", [
    "0013011234567",     # 13월
    "0001321234567",     # 32일
    "0002301234567",     # 1900-02-30
    "0002291234567",     # 1900년은 윤년이 아니다
    "0002303234567",     # 2000-02-30
    "0001019234567",     # 성별 자리 9
    "0001010234567",     # 성별 자리 0
])
def test_rrn_birth_date_and_gender_digit_are_errors(num):
    f = ready()
    f["신고인"]["주민등록번호"] = num
    with pytest.raises(filing.FilingError, match="생년월일"):
        filing.load(f)
    f = ready()
    f["양수인"][0]["번호"] = num
    with pytest.raises(filing.FilingError, match="생년월일"):
        filing.load(f)


def test_rrn_shape_accepts_leap_day_and_foreign_numbers():
    assert filing.rrn_shape_ok("0002293234567")          # 2000-02-29
    assert filing.rrn_shape_ok("5001015234560") and filing.rrn_shape_ok("0501017234567")
    assert not filing.rrn_shape_ok("000101123456") and not filing.rrn_shape_ok(fw("0001011234567"))
    good = filers.rrn("0001011", "23456")
    assert filing.rrn_ok(good) and not filing.rrn_ok(fw(good)) and not filing.rrn_ok(wrong_check_digit(good))


def test_rrn_check_digit_mismatch_is_a_warning_without_the_number():
    f = ready()
    mine = wrong_check_digit(f["신고인"]["주민등록번호"])
    theirs = wrong_check_digit(f["양수인"][0]["번호"])
    f["신고인"]["주민등록번호"], f["양수인"][0]["번호"] = mine, theirs
    out = filing.load(f)
    assert out["_경고"] == [
        "신고인 주민등록번호의 검증번호가 옛 규칙과 다르다. 2020-10 이후 발급·변경된 번호가 아니면 다시 확인하라",
        "양수인[0] 번호의 검증번호가 옛 규칙과 다르다. 2020-10 이후 발급·변경된 번호가 아니면 다시 확인하라"]
    assert mine not in json.dumps(out["_경고"], ensure_ascii=False) and theirs not in json.dumps(out["_경고"])
    assert ask(f) == []                                  # 경고는 질문을 만들지 않는다


def test_warning_list_is_always_there_and_recomputed():
    f = ready()
    assert filing.load(f)["_경고"] == []
    f["_경고"] = ["지난번 경고"]
    assert filing.load(f)["_경고"] == []
    f["신고인"].update(내외국인="9", 국적="US", 주민등록번호="5001015234560")     # 외국인은 검증번호를 보지 않는다
    assert filing.load(f)["_경고"] == []


def test_business_number_check_digit_is_still_an_error():
    f = ready()
    f["양수인"][0].update(구분="2", 번호="0000000092")
    with pytest.raises(filing.FilingError, match="사업자"):
        filing.load(f)
    f["양수인"][0]["번호"] = "0000000091"
    assert filing.load(f)["_경고"] == []


@pytest.mark.parametrize("path,make", [
    (("신고인", "주민등록번호"), lambda f: fw(f["신고인"]["주민등록번호"])),
    (("신고인", "전화"), lambda f: fw(f["신고인"]["전화"])),
    (("신고인", "주소", "번지"), lambda f: fw("12")),
    (("신고인", "주소", "호"), lambda f: fw("3")),
    (("신고인", "주소", "특수지"), lambda f: fw("0")),
    (("신고인", "주소", "법정동코드"), lambda f: fw("1171010100")),
    (("양수인", 0, "번호"), lambda f: fw(f["양수인"][0]["번호"])),
    (("양수인", 0, "전화"), lambda f: fw("0212345678")),
    (("양수인", 0, "관계코드"), lambda f: fw("01")),
    (("자산", "A", "번지"), lambda f: fw("123")),
    (("자산", "A", "호"), lambda f: fw("0")),
    (("자산", "A", "법정동코드"), lambda f: fw("1171010100")),
    (("자산", "A", "등기원인"), lambda f: {"취득": fw("0336")}),
    (("환급계좌",), lambda f: {"은행코드": fw("004"), "계좌번호": "123"}),
    (("환급계좌",), lambda f: {"은행코드": "004", "계좌번호": fw("123")}),
    (("신고인", "전화"), lambda f: "\u0661\u0662\u0663"),          # 아랍-인도 숫자
])
def test_digit_fields_take_ascii_digits_only(path, make):
    f = ready()
    cur = f
    for k in path[:-1]:
        cur = cur[k]
    cur[path[-1]] = make(f)
    with pytest.raises(filing.FilingError):
        filing.load(f)


def test_fullwidth_business_number_is_rejected():
    f = ready()
    f["양수인"][0].update(구분="2", 번호=fw("0000000091"))
    with pytest.raises(filing.FilingError, match="사업자"):
        filing.load(f)


def test_empty_special_code_becomes_zero():
    f = ready()
    f["신고인"]["주소"]["특수지"] = None
    f["자산"]["A"]["특수지"] = ""
    out = filing.load(f)
    assert out["신고인"]["주소"]["특수지"] == "0" and out["자산"]["A"]["특수지"] == "0"
    del f["자산"]["A"]["특수지"]
    assert filing.load(f)["자산"]["A"]["특수지"] == "0"
    f["자산"]["A"]["특수지"] = "9"
    assert filing.load(f)["자산"]["A"]["특수지"] == "9"


def test_lot_zero_is_allowed_only_for_special_9():
    f = ready()
    f["자산"]["A"]["번지"] = "0"
    qs = ask(f)
    assert ids(qs) == [("F04", "A")] and "번지가 0" in qs[0]["내용"]
    f["자산"]["A"]["특수지"] = ""                         # 비면 0 으로 채우므로 여전히 안 된다
    assert ids(ask(f)) == [("F04", "A")]
    f["자산"]["A"]["특수지"] = "9"
    assert ask(f) == []
    f = ready()
    f["신고인"]["주소"]["번지"] = "0"
    qs = ask(f)
    assert ids(qs) == [("F01", None)] and "번지가 0" in qs[0]["내용"]
    f["신고인"]["주소"]["특수지"] = "9"
    assert ask(f) == []


def test_related_buyer_needs_a_relation_code():
    f = ready()
    facts = facts_with(매수인관계="배우자")
    qs = ask_facts(f, facts)
    assert ids(qs) == [("F02", "A")]
    assert "규격서 p107~109 관계코드" in qs[0]["내용"] and "관계코드" in qs[0]["내용"]
    f["양수인"][0]["관계코드"] = "02"
    assert ask_facts(f, facts) == []
    f["양수인"][0]["관계코드"] = ""
    assert ids(ask_facts(f, facts)) == [("F02", "A")]
    f["양수인"][0]["관계코드"] = "ZB"
    assert ask_facts(f, facts) == []


def test_relation_code_is_not_asked_for_strangers_or_unknown():
    f = ready()
    for rel in ("타인", None):
        assert ask_facts(f, facts_with(매수인관계=rel)) == []
    f["양수인"][0]["관계코드"] = "ZA"                      # 타인이어도 적어 두면 형식만 본다
    assert ask_facts(f, facts_with(매수인관계="타인")) == []


def test_relation_code_question_names_only_the_buyers_missing_it():
    f = ready("BF")
    facts = copy.deepcopy(CASES["BF"])
    for a in facts["자산"]:
        a["매수인관계"] = "직계" if a["id"] == "F" else "타인"
    qs = ask_facts(f, facts)
    assert ids(qs) == [("F02", "F")]
    f["양수인"][1]["관계코드"] = "05"
    assert ask_facts(f, facts) == []


@pytest.mark.parametrize("side", ["취득", "양도"])
def test_auction_needs_a_registry_cause(side):
    f = ready()
    facts = facts_with(**{side + "__원인": "경매"})
    qs = ask_facts(f, facts)
    assert ids(qs) == [("F04", "A")]
    for code in ("0336", "0337", "0302", "0303", "0015", "0021"):
        assert code in qs[0]["내용"]
    assert "임의경매로 인한 매각" in qs[0]["내용"] and side in qs[0]["내용"]
    f["자산"]["A"]["등기원인"] = {"양도" if side == "취득" else "취득": "0336"}      # 반대쪽 키로는 안 된다
    assert ids(ask_facts(f, facts)) == [("F04", "A")]
    f["자산"]["A"]["등기원인"] = {side: "0336"}
    assert ask_facts(f, facts) == []


def test_auction_on_both_sides_needs_both_causes():
    f = ready()
    facts = facts_with(취득__원인="경매", 양도__원인="경매")
    f["자산"]["A"]["등기원인"] = {"취득": "0336"}
    qs = ask_facts(f, facts)
    assert ids(qs) == [("F04", "A")] and "경매로 양도한" in qs[0]["내용"] and "경매로 취득한" not in qs[0]["내용"]
    f["자산"]["A"]["등기원인"] = {"취득": "0336", "양도": "0337"}
    assert ask_facts(f, facts) == []


def test_no_cause_question_for_ordinary_assets():
    f = ready()
    assert ask_facts(f, facts_with(취득__원인="매매", 양도__원인="매매")) == []


def test_empty_strings_are_missing_not_errors():
    f = ready()
    f["신고"].update(구분="", 작성일="", 홈택스ID="", 분납신청="")
    f["신고인"].update(성명="", 주민등록번호="", 전화="", 전자메일="", 내외국인="", 거주구분="", 거주지국="", 국적="")
    f["양수인"][0].update(구분="", 내외국인="", 번호="", 성명="", 전화="", 지분="", 관계코드="")
    f["자산"]["A"].update(번지="", 호="", 법정동코드="", 총면적="", 등기원인="", 특수지="")
    f["환급계좌"] = ""
    qs = ask_facts(f, facts_with(매수인관계="배우자"))
    assert ids(qs) == _ed([("F01", None), ("F02", "A"), ("F03", None), ("F04", "A"), ("F05", None), ("F06", None)])
    f["신고"]["구분"] = "정기"
    with pytest.raises(filing.FilingError):
        filing.load(f)


def test_empty_string_sections_are_filled():
    f = {"신고": "", "신고인": " ", "양수인": "", "자산": "", "세무대리인": None}
    out = filing.load(f)
    assert (out["신고"], out["신고인"], out["양수인"], out["자산"]) == ({}, {}, [], {})


def test_dong_code():
    b = FakeBjd()
    assert filing.dong_code({"법정동코드": "1171010100"}, b) == "1171010100"
    assert filing.dong_code({"시도": "서울특별시", "시군구": "마포구", "읍면동": "공덕동"}, b) == "1144010200"
    assert filing.dong_code({"시도": "서울특별시", "시군구": "성동구", "읍면동": "성수동"}, b) is None      # 후보가 여럿
    assert filing.dong_code({"시도": "서울특별시", "시군구": "마포구", "읍면동": ""}, b) is None
    assert filing.dong_code({"시도": "서울특별시", "시군구": "마포구"}, b) is None
    assert filing.dong_code(None, b) is None

    class NoCode(FakeBjd):
        def exists(self, c):
            return False

    assert filing.dong_code({"법정동코드": "1171010100"}, NoCode()) is None
    seen = []

    class Spy(FakeBjd):
        def lookup(self, 시도, 시군구, 읍면동, on=None):
            seen.append(on)
            return "1100000000"

    assert filing.dong_code({"시도": "서울특별시", "시군구": "마포구", "읍면동": "공덕동"}, Spy(), on="2026-12-20") == "1100000000"
    assert seen == ["2026-12-20"]


def test_dong_code_of_old_gwangju_jeonnam_names_with_real_table():
    """광주광역시·전라남도로 적은 주소도 작성일이 통합(2026-07-01) 이후면 전남광주통합특별시의 코드를 찾는다. 질문 F04 로 넘어가지 않는다."""
    for sido in ("광주광역시", "전남광주통합특별시"):
        assert filing.dong_code({"시도": sido, "시군구": "서구", "읍면동": "치평동"}, on="2026-10-11") == "1224012000"
    for sido in ("전라남도", "전남광주통합특별시"):
        assert filing.dong_code({"시도": sido, "시군구": "강진군", "읍면동": "강진읍"}, on="2026-10-11") == "1278025000"
    assert filing.dong_code({"시도": "전라남도", "시군구": "서구", "읍면동": "치평동"}, on="2026-10-11") is None


def test_bjd_is_not_read_when_nothing_needs_a_code_check():
    qs = filing.questions(filing.load({"세무대리인": None}), {"자산": []}, None)       # bjd 모듈이 없어도 돈다
    assert ids(qs) == _ed([("F01", None), ("F03", None), ("F05", None), ("F06", None)])


# ---- 서식 단계 F07(지급처 사업자번호)·F08(취득 상대방) ----

TODAY = "2026-10-11"


def done(name="S1", facts=None):
    """계산이 끝난 엔진 결과. F07·F08 은 이 결과의 취득가액 방법을 보고 07 행이 생기는 지출을 정한다."""
    facts = facts if facts is not None else CASES[name]
    res = engine.calculate(facts, today=TODAY)
    assert res["상태"] == "완료"
    return res


def ask_done(f, name="S1", facts=None):
    facts = facts if facts is not None else CASES[name]
    return filing.questions(filing.load(f), facts, done(name, facts), bjd=FakeBjd())


def s1_facts(**gone):
    """사례 S1 의 사실관계. gone 은 {묶음: [사업자번호를 지울 항목 순서(0부터)]}."""
    facts = copy.deepcopy(CASES["S1"])
    for group, idxs in gone.items():
        for i in idxs:
            del facts["자산"][0]["필요경비"][group][i]["사업자번호"]
    return facts


@pytest.mark.parametrize("name", ["A", "S1", "BF", "K"])
def test_synthetic_filers_have_no_questions_once_codes_are_filled(name):
    f = ready(name)
    assert ask_done(f, name) == []
    assert ask(f, name) == []


def test_f07_asks_for_a_missing_business_number_of_a_required_code():
    facts = s1_facts(취득부대=[0])                      # 중개수수료(11501)는 지급처 사업자번호가 필수 구분코드다
    qs = ask_done(ready("S1"), facts=facts)
    assert ids(qs) == [("F07", "S1")]
    text = qs[0]["내용"]
    assert "취득부대의 1번째 지출(중개수수료, 2018-03-15)" in text
    assert "2번째 지출" not in text and "자본적지출" not in text and "양도비" not in text      # 번호가 있는 다른 지출은 묻지 않는다
    assert "규격서 p60" in text and "사업자번호" in text


def test_f07_is_silent_when_every_required_expense_has_a_valid_number():
    assert ask_done(ready("S1"), facts=s1_facts()) == []


@pytest.mark.parametrize("bad", ["", None, "   ", "000-00-00015", "000000001", "00000000150", "0000000016", fw("0000000015"),
                                 15])
def test_f07_asks_when_the_number_is_blank_or_wrong(bad):
    facts = s1_facts()
    facts["자산"][0]["필요경비"]["양도비"][0]["사업자번호"] = bad
    qs = ask_done(ready("S1"), facts=facts)
    assert ids(qs) == [("F07", "S1")]
    assert "양도비의 1번째 지출(중개수수료, 2026-11-20)" in qs[0]["내용"]
    if isinstance(bad, str) and bad.strip():
        assert bad not in qs[0]["내용"]                  # 적은 번호는 되풀이하지 않는다


def test_f07_names_blank_and_wrong_numbers_separately_and_lists_every_expense():
    facts = s1_facts(취득부대=[1])                       # 법무사비용: 빠짐
    facts["자산"][0]["필요경비"]["자본적지출"][0]["사업자번호"] = "0000000040"    # 발코니확장: 검증번호가 틀림(0000000048 에서 끝자리만 바꿨다)
    qs = ask_done(ready("S1"), facts=facts)
    assert ids(qs) == [("F07", "S1")]                    # 자산마다 질문 하나
    text = qs[0]["내용"]
    assert "취득부대의 2번째 지출(법무사비용, 2018-03-15)" in text
    assert "자본적지출의 1번째 지출(발코니확장, 2018-04-10)" in text
    assert text.index("비어 있는") < text.index("법무사비용") < text.index("틀린") < text.index("발코니확장")


def test_f07_does_not_ask_about_codes_that_do_not_need_a_number():
    facts = s1_facts()
    ex = facts["자산"][0]["필요경비"]
    ex["취득부대"].append({"내용": "인지세", "지급일": "2018-03-15", "금액": 150_000, "증빙종류": "계좌이체", "상대방": "합성은행"})
    ex["기타"] = [{"내용": "개발부담금", "지급일": "2020-01-10", "금액": 1_000_000, "증빙종류": "계좌이체", "상대방": "합성시청"}]
    assert ask_done(ready("S1"), facts=facts) == []      # 기타부대비용(11601)·개발부담금(26101)은 필수 구분코드가 아니다
    ex["기타"][0]["내용"] = "토지 철거비"                   # 토지장애철거비(28001)는 필수다
    qs = ask_done(ready("S1"), facts=facts)
    assert ids(qs) == [("F07", "S1")] and "기타의 1번째 지출(토지 철거비, 2020-01-10)" in qs[0]["내용"]
    assert "인지세" not in qs[0]["내용"]


def test_f07_ignores_zero_amount_and_expenses_the_engine_drops():
    facts = s1_facts(취득부대=[0], 양도비=[0])
    facts["자산"][0]["필요경비"]["취득부대"][0]["금액"] = 0               # 지급금액이 없으면 필수가 아니다(규격서 p60)
    facts["자산"][0]["필요경비"]["양도비"][0]["증빙종류"] = "간이영수증"      # 엔진이 필요경비에서 빼서 07 에 오지 않는다
    assert ask_done(ready("S1"), facts=facts) == []


def test_f07_numbers_stay_with_the_item_position_in_the_facts_list():
    """n번째는 사실관계 목록의 순서다. 앞 항목을 엔진이 빼도 번호가 당겨지지 않는다."""
    facts = s1_facts(취득부대=[1])
    facts["자산"][0]["필요경비"]["취득부대"][0]["증빙종류"] = "간이영수증"
    qs = ask_done(ready("S1"), facts=facts)
    assert "취득부대의 2번째 지출(법무사비용, 2018-03-15)" in qs[0]["내용"]


def test_f07_item_without_content_or_date_is_still_pointed_at():
    facts = s1_facts(양도비=[0])
    facts["자산"][0]["필요경비"]["양도비"][0].update(내용=None, 지급일=None)
    qs = ask_done(ready("S1"), facts=facts)
    assert "양도비의 1번째 지출(내용 없음, 지급일 없음)" in qs[0]["내용"]


def test_f07_and_f08_do_not_echo_values():
    facts = s1_facts(취득부대=[0, 1])
    facts["자산"][0]["필요경비"]["양도비"][0]["사업자번호"] = "0000000016"
    f = ready("S1")
    del f["자산"]["S1"]["취득상대방"]
    qs = ask_done(f, facts=facts)
    assert ids(qs) == [("F07", "S1"), ("F08", "S1")]
    text = json.dumps(qs, ensure_ascii=False)
    for s in ("2400000", "2,400,000", "800000", "9000000", "합성공인중개사", "합성법무사", "합성인테리어", "합성성동", "최합성",
              "0000000015", "0000000034", "0000000048", "0000000016"):
        assert s not in text
    for q in qs:
        assert set(q) == {"문항", "자산", "내용"}
        assert q["내용"] and chr(0x2014) not in q["내용"] and not q["내용"].rstrip().endswith("?")
        assert "밖" not in q["내용"]


def test_f08_asks_for_the_seller_of_the_purchase_row():
    f = ready("S1")
    assert ask_done(f) == []
    del f["자산"]["S1"]["취득상대방"]
    qs = ask_done(f)
    assert ids(qs) == [("F08", "S1")]
    # 공개본은 전자신고 파일이 없어 규격서 대신 부표3 매입가액 행을 말한다
    assert "취득상대방" in qs[0]["내용"] and "매입가액" in qs[0]["내용"]
    assert ("부표3" if edition.PUBLIC else "규격서 p59") in qs[0]["내용"]
    for blank in (None, "", "   "):
        f["자산"]["S1"]["취득상대방"] = blank
        assert ids(ask_done(f)) == [("F08", "S1")]
    f["자산"]["S1"]["취득상대방"] = "최합성"
    assert ask_done(f) == []


def test_f08_asks_when_the_asset_has_no_lot_entry():
    f = ready("BF")
    del f["자산"]["B"]
    qs = ask_done(f, "BF")
    assert [("F04", "B"), ("F08", "B")] == [x for x in ids(qs) if x[1] == "B"]


def test_f08_is_asked_only_for_assets_that_get_a_purchase_row():
    f = ready("BF")
    assert "취득상대방" not in f["자산"]["F"]          # 토지 F 는 환산취득가액이라 매입가액 행이 없다
    assert ask_done(f, "BF") == []
    del f["자산"]["B"]["취득상대방"]
    assert ids(ask_done(f, "BF")) == [("F08", "B")]


def test_f07_and_f08_are_silent_for_a_fully_exempt_asset():
    f = filers.filer("예정", "2026-12-20", {"G3": filers.lot()}, [filers.buyer("G3")])
    f["자산"]["G3"]["법정동코드"] = "1171010100"
    assert done("G3")["계산"]["자산"][0]["계산"]["취득가액"] is None          # 전액 비과세라 부표3 이 없다
    assert ask_done(f, "G3") == []


def test_f07_and_f08_need_a_finished_result():
    f = ready("S1")
    del f["자산"]["S1"]["취득상대방"]
    facts = s1_facts(취득부대=[0])
    loaded = filing.load(f)
    assert filing.questions(loaded, facts, None, bjd=FakeBjd()) == []
    assert filing.questions(loaded, facts, {"상태": "질문", "계산": None}, bjd=FakeBjd()) == []
    broken = dict(done("S1", facts), 상태="검산실패")
    assert filing.questions(loaded, facts, broken, bjd=FakeBjd()) == []


def test_f07_and_f08_follow_the_rule_in_return_values(monkeypatch):
    """어느 지출이 07 행이 되는지는 return_values.expense_lines 가 정한다. filing 은 같은 규칙을 다시 쓰지 않는다."""
    from yangdo import return_values
    seen = []

    def fake(a, c):
        seen.append((a["id"], c["취득가액방법"]))
        return []

    monkeypatch.setattr(return_values, "expense_lines", fake)
    f = ready("S1")
    del f["자산"]["S1"]["취득상대방"]
    assert ask_done(f, facts=s1_facts(취득부대=[0])) == []
    assert seen == [("S1", "실지거래가액")]


def test_seller_name_is_checked_when_loading():
    f = ready("S1")
    f["자산"]["S1"]["취득상대방"] = "최" + "합" * 29                # 60바이트
    assert filing.load(f)["자산"]["S1"]["취득상대방"].startswith("최합")
    for bad in ("최합" * 16, "똠방각하", "합성" + chr(0xB7) + "건설", "최합성" + chr(0xFF3A), "최합성" + chr(0x2014), 123, ["최합성"]):
        f["자산"]["S1"]["취득상대방"] = bad
        with pytest.raises(filing.FilingError, match="취득상대방"):
            filing.load(f)
    f["자산"]["S1"]["취득상대방"] = "(주)합성건설 최합성"          # ASCII 괄호와 공백은 된다. 기호 행(가운뎃점)은 신고값 생성과 같게 받지 않는다
    assert filing.load(f)["자산"]["S1"]["취득상대방"]


def test_wrong_seller_name_is_asked_again_when_questions_get_an_unloaded_filer():
    f = filing.load(ready("S1"))
    f["자산"]["S1"]["취득상대방"] = "똠방각하"
    qs = filing.questions(f, CASES["S1"], done("S1"), bjd=FakeBjd())
    assert ids(qs) == [("F08", "S1")] and "쓸 수 없는 글자" in qs[0]["내용"] and "똠방각하" not in qs[0]["내용"]


# ---- 전자신고 검증에서만 걸리던 입력을 질문 단계에서 잡는다(계획 2b G6) ----
# 번지 00, 시도·시군구 단계의 법정동코드, 필수 구분 지출의 지급일 없음은 신고서 PDF 를 만든 뒤 파일 검증에서야 걸렸다.

@pytest.mark.parametrize("lot", ["00", "000", "0000"])
def test_lot_made_of_zeros_is_treated_as_zero(lot):
    f = ready()
    f["자산"]["A"]["번지"] = lot
    qs = ask(f)
    assert ids(qs) == [("F04", "A")] and "번지가 0 이면 특수지가 9(무번지)여야 합니다" in qs[0]["내용"]
    f["자산"]["A"]["특수지"] = "9"                         # 무번지도 0 한 글자로 적는다
    qs = ask(f)
    assert ids(qs) == [("F04", "A")] and "0 한 글자" in qs[0]["내용"]
    f = ready()
    f["신고인"]["주소"]["번지"] = lot
    qs = ask(f)
    assert ids(qs) == [("F01", None)] and "번지가 0 이면 특수지가 9(무번지)여야 합니다" in qs[0]["내용"]
    f["신고인"]["주소"]["특수지"] = "9"
    qs = ask(f)
    assert ids(qs) == [("F01", None)] and "0 한 글자" in qs[0]["내용"]


def test_lot_with_leading_zero_is_asked_again():
    f = ready()
    f["자산"]["A"]["번지"] = "0123"
    qs = ask(f)
    assert ids(qs) == [("F04", "A")] and "앞에 0 을 붙이지 않고" in qs[0]["내용"] and "0123" not in qs[0]["내용"]
    f["자산"]["A"]["번지"] = "1230"                        # 끝의 0 은 번지의 일부다
    assert ask(f) == []
    f["신고인"]["주소"]["번지"] = "01"
    qs = ask(f)
    assert ids(qs) == [("F01", None)] and "앞에 0 을 붙이지 않고" in qs[0]["내용"]


@pytest.mark.parametrize("code,stage", [("1100000000", "시도"), ("1171000000", "시군구"), ("4111000000", "시군구"),
                                        ("3611000000", "시도")])
def test_given_code_above_dong_level_is_asked_again(code, stage):
    """법정동코드는 시도 2 + 시군구 3 + 읍면동 3 + 리 2 자리다. 읍면동 자리가 000 이면 시도나 시군구 행이라 05-8·02-3 에 쓸 수 없다."""
    f = ready(A=code)
    qs = ask(f)
    assert ids(qs) == [("F04", "A")]
    assert "시도나 시군구 단계" in qs[0]["내용"] and "읍면동" in qs[0]["내용"] and code not in qs[0]["내용"]
    f = ready()
    f["신고인"]["주소"]["법정동코드"] = code
    qs = ask(f)
    assert ids(qs) == [("F01", None)] and "시도나 시군구 단계" in qs[0]["내용"]
    assert filing.dong_code({"법정동코드": code}, FakeBjd()) is None


def test_given_code_at_dong_or_ri_level_passes_with_real_table():
    """진짜 법정동코드 표로: 읍면동 단계(공덕동)와 리 단계(강진읍 아래 리)는 받고, 시군구 단계(마포구)는 되묻는다."""
    from yangdo import bjd
    table = bjd.load()
    ri = next(c for c in sorted(table._names) if c.startswith("12780250") and c[8:] != "00")
    for code in ("1144010200", ri):
        assert filing.dong_code({"법정동코드": code}, table) == code
    assert table.exists("1144000000") and filing.dong_code({"법정동코드": "1144000000"}, table) is None
    f = ready(A="1144000000")
    assert ids(filing.questions(filing.load(f), CASES["A"], None, bjd=table)) == [("F04", "A")]


def test_f07_asks_for_a_missing_payment_date_of_a_required_code():
    facts = s1_facts()
    facts["자산"][0]["필요경비"]["취득부대"][1]["지급일"] = None          # 법무사비용(11401)은 필수 구분코드다
    qs = ask_done(ready("S1"), facts=facts)
    assert ids(qs) == [("F07", "S1")]
    text = qs[0]["내용"]
    assert "지급일이 없거나 읽을 수 없는 지출: 취득부대의 2번째 지출(법무사비용, 지급일 없음)." in text
    assert "지급일에 YYYY-MM-DD 로 적어 주세요" in text and "규격서 p60" in text
    assert "사업자번호가 비어 있는 지출" not in text and "숫자 10자리" not in text      # 사업자번호는 다 맞다


@pytest.mark.parametrize("bad", ["", "   ", "2018.03.15", "20180315", "2018-02-30", 20180315])
def test_f07_asks_when_the_payment_date_is_blank_or_unreadable(bad):
    facts = s1_facts()
    facts["자산"][0]["필요경비"]["양도비"][0]["지급일"] = bad
    qs = ask_done(ready("S1"), facts=facts)
    assert ids(qs) == [("F07", "S1")] and "지급일이 없거나 읽을 수 없는 지출: 양도비의 1번째 지출(중개수수료" in qs[0]["내용"]


def test_f07_lists_numbers_and_dates_separately():
    facts = s1_facts(취득부대=[0])                       # 중개수수료: 사업자번호 빠짐
    facts["자산"][0]["필요경비"]["자본적지출"][0]["지급일"] = ""     # 발코니확장: 지급일 빠짐
    qs = ask_done(ready("S1"), facts=facts)
    assert ids(qs) == [("F07", "S1")]
    text = qs[0]["내용"]
    assert "사업자번호가 비어 있는 지출: 취득부대의 1번째 지출(중개수수료, 2018-03-15)." in text
    assert "지급일이 없거나 읽을 수 없는 지출: 자본적지출의 1번째 지출(발코니확장, 지급일 없음)." in text
    assert text.index("사업자번호가 비어 있는") < text.index("지급일이 없거나") < text.index("숫자 10자리") < text.index("YYYY-MM-DD")


def test_f07_does_not_ask_for_the_date_of_codes_that_do_not_need_it():
    """필수가 아닌 구분(기타부대비용 11601, 개발부담금 26101)과 지급금액이 없는 지출, 엔진이 뺀 지출은 지급일을 묻지 않는다."""
    facts = s1_facts()
    ex = facts["자산"][0]["필요경비"]
    ex["취득부대"].append({"내용": "인지세", "지급일": None, "금액": 150_000, "증빙종류": "계좌이체", "상대방": "합성은행"})
    ex["기타"] = [{"내용": "개발부담금", "지급일": "", "금액": 1_000_000, "증빙종류": "계좌이체", "상대방": "합성시청"}]
    assert ask_done(ready("S1"), facts=facts) == []
    facts = s1_facts()
    facts["자산"][0]["필요경비"]["취득부대"][0].update(금액=0, 지급일=None)
    facts["자산"][0]["필요경비"]["양도비"][0].update(증빙종류="간이영수증", 지급일=None)
    assert ask_done(ready("S1"), facts=facts) == []


def test_auction_cause_candidates_all_carry_their_names():
    """F04 가 보여 주는 경매 등기원인 후보는 코드마다 코드표(규격서 p109~110)의 이름을 함께 적는다."""
    import os
    from yangdo import SKILL_DIR
    with open(os.path.join(SKILL_DIR, "efile", "codes_c116300.json"), encoding="utf-8") as fh:
        names = json.load(fh)["등기원인목록"]["A1ZZCZ"]
    listed = dict(x.strip().split(" ", 1) for x in filing.경매원인후보.split(","))
    assert sorted(listed) == ["0015", "0021", "0302", "0303", "0336", "0337"]
    for code, name in listed.items():
        assert name == names[code]["이름"].replace(chr(0xA0), " "), code
    facts = facts_with(취득__원인="경매")
    qs = ask_facts(ready(), facts)
    assert "0302 임의경매로 인한 낙찰" in qs[0]["내용"] and "0303 강제경매로 인한 낙찰" in qs[0]["내용"]


def test_questions_read_the_code_table_of_the_given_efile_dir(tmp_path):
    """F07 이 보는 필수 구분코드 표는 신고값을 만들 때와 같은 efile 폴더의 것이어야 한다."""
    import os
    import shutil
    from yangdo import SKILL_DIR
    efile_dir = tmp_path / "efile"
    shutil.copytree(os.path.join(SKILL_DIR, "efile"), str(efile_dir))
    path = efile_dir / "codes_c116300.json"
    codes = json.loads(path.read_text(encoding="utf-8"))
    codes["필요경비구분"]["취득중개수수료"]["필수"] = False
    path.write_text(json.dumps(codes, ensure_ascii=False), encoding="utf-8")
    facts = s1_facts(취득부대=[0])
    loaded, res = filing.load(ready("S1")), done("S1", facts)
    assert ids(filing.questions(loaded, facts, res, bjd=FakeBjd())) == [("F07", "S1")]
    assert filing.questions(loaded, facts, res, bjd=FakeBjd(), efile_dir=str(efile_dir)) == []


# ---- 신고인_양식.json: 사용자가 복사해 채우는 파일이라 코드가 읽는 모양과 어긋나면 안 된다 ----
FORM_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "신고인_양식.json")


def _form():
    with open(FORM_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def test_filer_form_loads_and_its_blanks_become_questions():
    """빈 양식은 오류로 멈추지 않고 읽힌다. 빈 값은 질문이 된다(신고인 F01, 양수인 F02, 분납 F03 과 주소·서류 문항)."""
    f = filing.load(FORM_PATH)
    assert f["_경고"] == [] and f["세무대리인"] is None and f["환급계좌"] is None
    assert f["신고인"]["주소"]["특수지"] == "0" and f["자산"]["A"]["특수지"] == "0"
    qs = filing.questions(f, {"자산": [{"id": "A"}]}, None, bjd=FakeBjd())
    assert {"F01", "F02", "F03"} <= {q["문항"] for q in qs}
    for name in filing.FIELD_NAMES:
        assert name in qs[0]["내용"]


def test_filer_form_has_the_same_keys_as_a_valid_filer():
    """양식의 구역과 칸 이름은 시험이 쓰는 합성 신고인(코드가 받아들이는 모양)과 같다. 합성 신고인에 없는 칸은 선택 칸이다."""
    form, ok = _form(), filers.get("S1")
    assert set(form) - {"_설명"} == set(ok)
    for sec in ("신고", "신고인"):
        assert set(form[sec]) == set(ok[sec]), sec
    assert set(form["신고인"]) - {"주소", "전자메일"} == set(filing.FIELD_NAMES)      # 전자메일은 선택 칸이라 필수 목록에 없다
    assert set(form["신고인"]["주소"]) == set(ok["신고인"]["주소"])
    assert set(form["양수인"][0]) - set(ok["양수인"][0]) == {"관계코드"} and set(ok["양수인"][0]) <= set(form["양수인"][0])
    lot, mine = next(iter(ok["자산"].values())), form["자산"]["A"]
    assert set(lot) <= set(mine) and set(mine) - set(lot) <= {"등기원인", "등기목적"}


def test_filer_form_filled_with_valid_values_loads_without_questions():
    """양식의 칸에 합성 값을 채우면 읽히고 질문이 없다(양식이 코드가 요구하는 칸을 빠뜨리지 않았다)."""
    ok, form = filers.get("A"), _form()
    ok["자산"]["A"]["법정동코드"] = "1171010100"
    for sec in ("신고", "신고인"):
        for k in form[sec]:
            form[sec][k] = ok[sec][k]
    form["양수인"] = ok["양수인"]
    form["자산"] = {"A": {**form["자산"]["A"], **ok["자산"]["A"]}}
    f = filing.load(form)
    assert filing.questions(f, CASES["A"], None, bjd=FakeBjd()) == []


def test_unknown_keys_are_warned_by_name_only_and_underscore_keys_are_not():
    f = filers.get("BF")
    f["신고"]["분납 신청"] = "ZZ비밀값ZZ"
    f["자산"]["B"]["취득 상대방"] = "ZZ비밀값ZZ"
    f["신고인"]["주소"]["동네"] = "ZZ비밀값ZZ"
    f["양수인"][0]["지분율"] = 1
    f["최상위"] = {"x": 1}
    f["자산"]["B"]["시도"] = "ZZ비밀값ZZ"
    f["_설명"] = {"쓰는법": "설명용 키는 경고하지 않는다"}
    f["신고"]["_메모"] = "ZZ비밀값ZZ"
    warns = filing.load(f)["_경고"]
    w = [x for x in warns if x.startswith(filing.UNKNOWN_KEYS_HEAD)]
    assert len(w) == 1 and "ZZ비밀값ZZ" not in w[0]
    for name in ("신고.분납 신청", "자산.B.취득 상대방", "신고인.주소.동네", "양수인[1].지분율", "최상위", "자산.B.시도"):
        assert name in w[0], name
    assert "_설명" not in w[0] and "_메모" not in w[0]


@pytest.mark.parametrize("name", ["A", "S1", "BF", "K"])
def test_known_filers_have_no_unknown_key_warning(name):
    assert filing.load(filers.get(name))["_경고"] == []


def test_filer_form_describes_every_section():
    """_설명에 구역마다 풀이가 있다. 줄표와 물음표로 끝나는 문장은 없다."""
    form = _form()
    text = form["_설명"]
    for sec in ("신고", "신고인"):
        for k in form[sec]:
            assert "%s.%s" % (sec, k) in text, (sec, k)
    for sec in ("양수인", "자산", "환급계좌", "세무대리인"):
        assert sec in text
    assert chr(0x2014) not in json.dumps(form, ensure_ascii=False)
