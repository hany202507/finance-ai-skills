# -*- coding: utf-8 -*-
import copy
import json

import pytest

from yangdo import filing
from cases import CASES
import filers


class FakeBjd:
    def lookup(self, 시도, 시군구, 읍면동, on=None):
        return {"공덕동": "1144010200", "성수동": None}.get(읍면동, "1100000000")

    def candidates(self, *a):
        return ["1120011400", "1120011500"]

    def exists(self, c):
        return True


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
    assert ids(qs) == [("F01", None), ("F03", None), ("F04", "A"), ("F05", None), ("F06", None)]


def test_missing_sections_are_questions():
    f = {"세무대리인": None}
    qs = filing.questions(filing.load(f), CASES["A"], None, bjd=FakeBjd())
    assert ids(qs) == [("F01", None), ("F02", "A"), ("F03", None), ("F04", "A"), ("F05", None), ("F06", None)]


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
    assert ids(qs) == [("F01", None), ("F02", "A"), ("F06", None)]
    text = json.dumps(qs, ensure_ascii=False)
    for s in secret:
        assert s not in text


def test_question_text_style():
    f = filers.get("S1")
    f["신고"].update(구분=None, 홈택스ID=None, 분납신청=None)
    f["양수인"] = []
    f["신고인"]["성명"] = None
    qs = filing.questions(filing.load(f), CASES["S1"], None, bjd=FakeBjd())
    assert {q["문항"] for q in qs} == {"F01", "F02", "F03", "F04", "F05", "F06"}
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
    assert ids(qs) == [("F01", None), ("F02", "A"), ("F03", None), ("F04", "A"), ("F05", None), ("F06", None)]
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


def test_bjd_is_not_read_when_nothing_needs_a_code_check():
    qs = filing.questions(filing.load({"세무대리인": None}), {"자산": []}, None)       # bjd 모듈이 없어도 돈다
    assert ids(qs) == [("F01", None), ("F03", None), ("F05", None), ("F06", None)]
