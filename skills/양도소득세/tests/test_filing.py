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
    f["신고인"]["주민등록번호"] = "0001011234560"
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


def test_biz_checksum_helper_matches_known_number():
    assert biz("124810099") == "1248100998"      # 알려진 사업자등록번호 모양으로 가중치를 확인한다


def test_load_accepts_a_path_and_does_not_touch_input(tmp_path):
    f = filers.get("A")
    before = copy.deepcopy(f)
    out = filing.load(f)
    assert f == before and out == before and out is not f
    p = tmp_path / "신고인.json"
    p.write_text(json.dumps(f, ensure_ascii=False), encoding="utf-8")
    assert filing.load(str(p)) == before
    assert filing.load(p) == before


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


def test_buyer_rrn_checked_for_citizens_only():
    f = ready()
    f["양수인"][0]["번호"] = "0001021234560"
    with pytest.raises(filing.FilingError, match="양수인"):
        filing.load(f)
    f["양수인"][0].update(내외국인="9", 번호="5001015234560")     # 외국인등록번호는 검증번호를 보지 않는다
    filing.load(f)
    f["양수인"][0]["번호"] = "50010152345"
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
    f = ready()
    try:
        from yangdo import bjd  # noqa: F401
    except ImportError:
        with pytest.raises(ImportError):
            filing.questions(filing.load(f), CASES["A"], None)
        return
    assert isinstance(filing.questions(filing.load(f), CASES["A"], None), list)
