# -*- coding: utf-8 -*-
import ast
import json
import os
import subprocess
import sys
from decimal import Decimal

import pytest

from yangdo import efile_check
import filers

SKILL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
L = json.load(open(os.path.join(SKILL, "efile", "layout_c116300.json"), encoding="utf-8"))


def _blank(kind, **vals):
    """레이아웃으로 레코드 하나를 만든다(검증기 시험 전용 최소 조립기)."""
    r = L["레코드"][kind]
    out = b""
    for f in r["필드"]:
        v = vals.get(f["name"], f["check"] if f["class"] == "FIX" else None)
        if f["type"] == "N":
            out += str(int(v or 0)).rjust(f["len"], "0").encode()
        else:
            b = ("" if v is None else str(v)).encode("cp949")
            out += b + b" " * (f["len"] - len(b))
    return out


def test_does_not_import_generator():
    src = open(os.path.join(SKILL, "yangdo", "efile_check.py"), encoding="utf-8").read()
    names = {n.module for n in ast.walk(ast.parse(src)) if isinstance(n, ast.ImportFrom) and n.module} | \
            {a.name for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Import) for a in n.names}
    assert not names & {"yangdo.efile", "yangdo.return_values", "yangdo.calc", "efile", "return_values", "calc"}
    assert "import efile" not in src and "from . import efile" not in src


def test_detects_bad_line_endings(tmp_path):
    p = tmp_path / "20261215C116300.01"
    p.write_bytes(_blank("01") + b"\n")
    assert any("CRLF" in m for m in efile_check.check_file(str(p)))


def test_detects_wrong_record_length(tmp_path):
    p = tmp_path / "20261215C116300.01"
    p.write_bytes(_blank("01")[:-1] + b"\r\n")
    assert any("길이" in m for m in efile_check.check_file(str(p)))


def test_detects_missing_mandatory_records(tmp_path):
    p = tmp_path / "20261215C116300.01"
    p.write_bytes(_blank("01") + b"\r\n")
    msgs = efile_check.check_file(str(p))
    assert any("02" in m for m in msgs) and any("05" in m for m in msgs)


def test_detects_non_ksx1001_bytes(tmp_path):
    p = tmp_path / "20261215C116300.01"
    p.write_bytes(_blank("01", 성명="김똠") + b"\r\n")
    assert any("완성형" in m for m in efile_check.check_file(str(p)))


def test_file_name_rule(tmp_path):
    p = tmp_path / "wrong.txt"
    p.write_bytes(_blank("01") + b"\r\n")
    assert any("파일명" in m for m in efile_check.check_file(str(p)))


# --- 위는 계획서 시험. 아래는 정상 최소 파일(합성 S1)과 그 파일을 망가뜨린 변형 ---
# 생성기(T10)가 아직 없으므로 레이아웃 칸 위치로 바이트를 직접 조립한다. 신고인·양수인·상대방은 모두 합성값이다

FIXTURE = os.path.join(SKILL, "tests", "fixtures", "efile", "정상_S1.01")
NAME = "20261215C116300.01"
SELLER = filers.rrn("0001011", "23456")
BUYER = filers.rrn("0001021", "34567")


def _biz(nine):
    """앞 9자리에 사업자등록번호 검증번호를 붙인다(합성 번호 전용)."""
    w = [1, 3, 7, 1, 3, 7, 1, 3, 5]
    t = sum(int(a) * b for a, b in zip(nine, w)) + int(nine[8]) * 5 // 10
    return nine + str((10 - t % 10) % 10)


BIZ_LAW, BIZ_AGENT, BIZ_INTERIOR = _biz("000000001"), _biz("000000002"), _biz("000000003")


def _field(kind, name):
    return next(f for f in L["레코드"][kind]["필드"] if f["name"] == name)


def _fmt(f, v):
    if f["type"] == "N":
        q = int(Decimal(str(v or 0)) * (10 ** f["dec"]))
        if q < 0:
            return ("-" + str(-q).rjust(f["len"] - 1, "0")).encode()
        return str(q).rjust(f["len"], "0").encode()
    b = ("" if v is None else str(v)).encode("cp949")
    assert len(b) <= f["len"], (f["name"], v)
    return b + b" " * (f["len"] - len(b))


def _rec(kind, vals):
    names = [f["name"] for f in L["레코드"][kind]["필드"]]
    assert set(vals) <= set(names), set(vals) - set(names)
    out = b"".join(_fmt(f, vals.get(f["name"], f["check"] if f["class"] == "FIX" else None))
                   for f in L["레코드"][kind]["필드"])
    assert len(out) == L["레코드"][kind]["길이"]
    return out


HEADER = {"납세자ID": SELLER, "납세자구분": "01", "신고구분코드": "03", "신고유형": "1", "과세기간_년월": "202601",
          "신고구분상세코드": "01", "신고서종류코드": "D03", "민원종류코드": "FD001", "사용자ID": "testuser01",
          "제출년월": "202612", "성명": "김합성", "세무프로그램코드": "9000", "작성일자": "20261215", "양도일자": "20261120"}
BASIC = {"주소_법정동코드": "1144010200", "주소_특수지코드": "0", "주소_번지": "1", "주소_호": "0",
         "주소_아파트명": "합성아파트", "주소_아파트동": "101", "주소_아파트호": "1001", "전화번호": "0212345678",
         "내외국인여부": "Y", "거주구분": "N", "거주지국코드": "KR", "거주지국명": "한국", "국적코드": "KR"}
RATE = {"양도소득금액": 155893334, "양도소득기본공제": 2500000, "과세표준": 153393334, "산출세액": 38349466,
        "전자신고세액공제": 20000, "자진납부할세액": 38329466}
BUYER_REC = {"일련번호": "000001", "양수인_주민사업자구분": "1", "양수인_내외국인_구분코드": "1",
             "양수인_주민등록번호": BUYER, "양수인_성명": "이합성", "양수인_지분(분자)": 1, "양수인_지분(분모)": 1,
             "양수인_양도자와의관계": "ZA"}
ASSET = {"일련번호": "000001", "과세구분": "ZZ", "국내외분(소재지)": "1", "세율구분": "10", "자산의종류": "02",
         "소재지_법정동코드": "1120011400", "소재지_특수지코드": "0", "소재지_번지": "456", "소재지_호": "0",
         "소재지_아파트명": "합성아파트", "소재지_아파트동": "101", "소재지_아파트호": "1001",
         "거래일자_양도일자": "20261120", "거래일자_양도등기목적": "A1ZZCZ", "거래일자_양도등기원인": "0055",
         "거래일자_취득일자": "20180315", "거래일자_취득등기목적": "A1ZZCZ", "거래일자_취득등기원인": "0055",
         "거래자산면적_총면적_토지_면적": 30, "거래자산면적_총면적_토지_지분(분자)": 1,
         "거래자산면적_총면적_토지_지분(분모)": 1, "거래자산면적_총면적_건물_면적": 84,
         "거래자산면적_총면적_건물_지분(분자)": 1, "거래자산면적_총면적_건물_지분(분모)": 1,
         "거래자산면적_양도면적_토지_면적": 30, "거래자산면적_양도면적_건물_면적": 84,
         "거래자산면적_취득면적_토지_면적": 30, "거래자산면적_취득면적_건물_면적": 84,
         "거래금액_양도가액": 1800000000, "거래금액_취득가액": 609800000, "취득가액종류": "01",
         "기타필요경비": 21000000, "양도차익_전체양도차익": 1169200000, "양도차익_비과세양도차익": 779466667,
         "양도차익_과세대상양도차익": 389733333, "장기보유특별공제": 233839999, "양도소득금액": 155893334,
         "감면종류": "ZZZ", "자동계산불러오기구분값": "1", "소재지국": "KR", "소재지국명": "한국",
         "필요경비신고자료일련번호": 1, "장기보유특별공제적용구분코드": "ZZ", "주택거주기간년수": 7,
         "1세대1주택비과세_보유기간": "08", "1세대1주택_비과세_거주기간": "07"}
EXPENSES = [("11101", "합성매도인", "", "", 600000000, "ZZ"),
            ("11201", "합성구청", "", "", 6600000, "ZZ"),
            ("11401", "합성법무사", BIZ_LAW, "20180315", 800000, "03"),
            ("11501", "합성공인중개사", BIZ_AGENT, "20180315", 2400000, "01"),
            ("26001", "합성인테리어", BIZ_INTERIOR, "20180410", 12000000, "03"),
            ("29001", "합성공인중개사", BIZ_AGENT, "20261120", 9000000, "01")]


def _s1_lines():
    exp = [_rec("07", {"필요경비신고자료일련번호": "000001", "구분코드": c, "상세일련번호": "%06d" % i, "상호": who,
                       "사업자등록번호": biz, "지급일자": day, "지급금액": amt, "증빙종류코드": proof})
           for i, (c, who, biz, day, amt, proof) in enumerate(EXPENSES, 1)]
    return [_rec("01", HEADER), _rec("02", BASIC),
            _rec("03", dict(RATE, 국내외분="1", 세율구분="10")),
            _rec("03", dict(RATE, 국내외분="Z", 세율구분="00", 자진납부세액=38329466)),
            _rec("04", BUYER_REC), _rec("05", ASSET)] + exp


def _join(lines):
    return b"".join(x + b"\r\n" for x in lines)


def _write(tmp_path, data, name=NAME):
    p = tmp_path / name
    p.write_bytes(data)
    return str(p)


def _lines():
    with open(FIXTURE, "rb") as f:
        data = f.read()
    assert data.endswith(b"\r\n")
    return data[:-2].split(b"\r\n")


def _idx(lines, kind, nth=0):
    return [i for i, x in enumerate(lines) if x[:2] == kind.encode()][nth]


def _put(lines, kind, name, value, nth=0):
    i = _idx(lines, kind, nth)
    f = _field(kind, name)
    x = lines[i]
    lines[i] = x[:f["start"] - 1] + _fmt(f, value) + x[f["end"]:]
    return lines


def _check(tmp_path, lines, **kw):
    return efile_check.check_file(_write(tmp_path, _join(lines)), **kw)


def test_fixture_matches_builder():
    with open(FIXTURE, "rb") as f:
        assert f.read() == _join(_s1_lines())


def test_minimal_valid_file_passes(tmp_path):
    fails, warns = efile_check.check_file_ex(_write(tmp_path, _join(_lines())))
    assert fails == [] and warns == []


def test_file_without_expense_detail_passes(tmp_path):
    # 07 이 없는 파일: 필요경비가 없으면 05-61 은 0 이고 기타필요경비도 0 이다
    asset = dict(ASSET, 거래금액_양도가액=300000000, 거래금액_취득가액=200000000, 기타필요경비=0,
                 양도차익_전체양도차익=100000000, 양도차익_비과세양도차익=0, 양도차익_과세대상양도차익=100000000,
                 장기보유특별공제=0, 양도소득금액=100000000, 필요경비신고자료일련번호=0, 과세구분="ZZ", 자산의종류="03",
                 **{"1세대1주택비과세_보유기간": "ZZ", "1세대1주택_비과세_거주기간": "ZZ"})
    rate = {"양도소득금액": 100000000, "양도소득기본공제": 2500000, "과세표준": 97500000, "산출세액": 19710000,
            "전자신고세액공제": 20000, "자진납부할세액": 19690000}
    lines = [_rec("01", HEADER), _rec("02", BASIC), _rec("03", dict(rate, 국내외분="1", 세율구분="10")),
             _rec("03", dict(rate, 국내외분="Z", 세율구분="00", 자진납부세액=19690000)),
             _rec("04", BUYER_REC), _rec("05", asset)]
    assert _check(tmp_path, lines) == []


def _has(msgs, *parts):
    return any(all(p in m for p in parts) for m in msgs)


def test_non_digit_in_number_field(tmp_path):
    lines = _lines()
    i = _idx(lines, "05")
    f = _field("05", "거래금액_양도가액")
    x = lines[i]
    lines[i] = x[:f["start"] - 1] + b"A" + x[f["start"]:]
    msgs = _check(tmp_path, lines)
    assert "6줄(05) 33 거래금액_양도가액: 숫자가 아님" in msgs


def test_changed_number_breaks_row_formula(tmp_path):
    msgs = _check(tmp_path, _put(_lines(), "05", "거래금액_양도가액", 1800000001))
    assert _has(msgs, "6줄(05)", "38")


def test_total_row_must_equal_rate_rows(tmp_path):
    lines = _put(_lines(), "03", "과세표준", 153393335, nth=1)
    msgs = _check(tmp_path, lines)
    assert _has(msgs, "4줄(03)", "8 과세표준", "합")


def test_tax_base_formula(tmp_path):
    lines = _put(_lines(), "03", "과세표준", 153393335, nth=0)
    lines = _put(lines, "03", "과세표준", 153393335, nth=1)
    msgs = _check(tmp_path, lines)
    assert _has(msgs, "3줄(03)", "과세표준", "양도소득금액")


def test_rate_row_income_must_match_assets(tmp_path):
    lines = _put(_lines(), "05", "양도소득금액", 155893333)
    lines = _put(lines, "05", "장기보유특별공제", 233840000)
    msgs = _check(tmp_path, lines)
    assert _has(msgs, "3줄(03)", "5 양도소득금액", "05")


def test_record_order(tmp_path):
    lines = _lines()
    a, b = _idx(lines, "04"), _idx(lines, "05")
    lines[a], lines[b] = lines[b], lines[a]
    assert _has(_check(tmp_path, lines), "순서")


@pytest.mark.parametrize("how", ["delete", "insert"])
def test_one_byte_shift(tmp_path, how):
    lines = _lines()
    x = lines[1]
    lines[1] = x[:30] + x[31:] if how == "delete" else x[:30] + b"0" + x[30:]
    assert _has(_check(tmp_path, lines), "2줄(02)", "길이")


def test_lone_lf_inside_file(tmp_path):
    data = _join(_lines())
    data = data.replace(b"\r\n", b"\n", 1)
    msgs = efile_check.check_file(_write(tmp_path, data))
    assert _has(msgs, "CRLF")


def test_missing_final_crlf(tmp_path):
    data = _join(_lines())[:-2]
    assert _has(efile_check.check_file(_write(tmp_path, data)), "CRLF")


def test_non_ksx1001_name_in_fixture(tmp_path):
    msgs = _check(tmp_path, _put(_lines(), "04", "양수인_성명", "이똠"))
    assert _has(msgs, "5줄(04)", "7 양수인_성명", "완성형")


@pytest.mark.parametrize("code,word", [("00", "무효"), ("QQ", "코드표에 없음")])
def test_buyer_relation_code(tmp_path, code, word):
    msgs = _check(tmp_path, _put(_lines(), "04", "양수인_양도자와의관계", code))
    assert _has(msgs, "5줄(04)", "11 양수인_양도자와의관계", word)


@pytest.mark.parametrize("kind,name,code,word", [
    ("02", "주소_법정동코드", "1144000000", "읍면동"),       # 마포구(시군구 단계)
    ("02", "주소_법정동코드", "1100000000", "읍면동"),       # 서울특별시(시도 단계)
    ("05", "소재지_법정동코드", "1120000000", "읍면동"),     # 성동구
    ("05", "소재지_법정동코드", "1120099900", "표에 없음"),
    ("02", "주소_법정동코드", "11440102", "10자리"),
])
def test_bjd_must_be_dong_level_and_exist(tmp_path, kind, name, code, word):
    msgs = _check(tmp_path, _put(_lines(), kind, name, code))
    assert _has(msgs, "(%s)" % kind, name, word)


def test_rrn_shape_is_error(tmp_path):
    bad = "0013011234567"                     # 13월
    msgs = _check(tmp_path, _put(_lines(), "01", "납세자ID", bad))
    assert _has(msgs, "1줄(01) 3 납세자ID", "생년월일")
    assert not _has(msgs, bad)


def test_rrn_check_digit_is_warning_only(tmp_path):
    other = SELLER[:12] + str((int(SELLER[12]) + 1) % 10)
    path = _write(tmp_path, _join(_put(_lines(), "01", "납세자ID", other)))
    fails, warns = efile_check.check_file_ex(path)
    assert fails == [] and _has(warns, "납세자ID", "검증번호")
    assert efile_check.check_file(path) == []
    assert not _has(warns, other)


def test_business_number_check_digit_for_corporate_buyer(tmp_path):
    lines = _put(_lines(), "04", "양수인_주민사업자구분", "2")
    ok = _check(tmp_path, _put(list(lines), "04", "양수인_주민등록번호", BIZ_LAW))
    bad = _check(tmp_path, _put(list(lines), "04", "양수인_주민등록번호", BIZ_LAW[:9] + str((int(BIZ_LAW[9]) + 1) % 10)))
    assert ok == [] and _has(bad, "5줄(04) 6", "검증번호")


def test_buyer_shares_must_sum_to_one(tmp_path):
    assert _has(_check(tmp_path, _put(_lines(), "04", "양수인_지분(분자)", 2)), "지분")


def test_expense_serial_must_have_detail_rows(tmp_path):
    assert _has(_check(tmp_path, _put(_lines(), "05", "필요경비신고자료일련번호", 2)), "6줄(05) 61")


def test_expense_detail_must_match_asset_amounts(tmp_path):
    msgs = _check(tmp_path, _put(_lines(), "07", "지급금액", 600000001))
    assert _has(msgs, "07", "34 거래금액_취득가액")


def test_required_expense_code_needs_business_number(tmp_path):
    msgs = _check(tmp_path, _put(_lines(), "07", "사업자등록번호", "", nth=2))
    assert _has(msgs, "9줄(07) 7 사업자등록번호")


def test_expense_detail_serial_sequence(tmp_path):
    msgs = _check(tmp_path, _put(_lines(), "07", "상세일련번호", "000003", nth=1))
    assert _has(msgs, "8줄(07) 5 상세일련번호")


def test_expense_subtotal_code_refused(tmp_path):
    msgs = _check(tmp_path, _put(_lines(), "07", "구분코드", "11990", nth=1))
    assert _has(msgs, "8줄(07) 4 구분코드")


def test_missing_total_row(tmp_path):
    lines = _lines()
    del lines[_idx(lines, "03", 1)]
    assert _has(_check(tmp_path, lines), "합계 행")


def test_own_code_tables():
    # 규격서 p27~28 세무프로그램코드 41개(기타 9000), p32~37 세율구분. 05 에는 주식 세율구분을 받지 않는다
    assert len(efile_check.PROGRAM_CODES) == 41 and "9000" in efile_check.PROGRAM_CODES
    assert {"10", "39", "46", "47", "49", "82", "84", "86", "88", "30"} <= efile_check.RATES_05
    assert not {"61", "62", "70", "63"} & efile_check.RATES_05


def test_program_code(tmp_path):
    assert _has(_check(tmp_path, _put(_lines(), "01", "세무프로그램코드", "1234")), "1줄(01) 23")


def test_return_kind_and_form_kind_pair(tmp_path):
    assert _has(_check(tmp_path, _put(_lines(), "01", "신고서종류코드", "D01")), "1줄(01) 10")


def test_transfer_date_is_latest_asset_date(tmp_path):
    assert _has(_check(tmp_path, _put(_lines(), "01", "양도일자", "20261119")), "1줄(01) 25")


@pytest.mark.parametrize("name", ["20261332C116300.01", "20261215C116300.03", "20261214C116300.01"])
def test_file_name_must_match_header(tmp_path, name):
    msgs = efile_check.check_file(_write(tmp_path, _join(_lines()), name=name))
    assert _has(msgs, "파일명")


@pytest.mark.parametrize("kind,word", [("99", "자료구분"), ("08", "다루지 않")])
def test_unknown_or_unhandled_record(tmp_path, kind, word):
    lines = _lines() + [kind.encode() + b"C116300" + b" " * 91]
    assert _has(_check(tmp_path, lines), word)


def test_duplicate_basic_record(tmp_path):
    lines = _lines()
    lines.insert(2, lines[1])
    assert _has(_check(tmp_path, lines), "02", "한 줄")


def test_local_tax_fields_are_zero(tmp_path):
    msgs = _check(tmp_path, _put(_lines(), "03", "주민세_세율", 10, nth=1))
    assert _has(msgs, "4줄(03) 31 주민세_세율")


def test_messages_do_not_carry_personal_values(tmp_path):
    lines = _put(_lines(), "01", "성명", "")
    lines = _put(lines, "02", "주소_법정동코드", "1144000000")
    lines = _put(lines, "04", "양수인_양도자와의관계", "00")
    msgs = _check(tmp_path, lines)
    text = "\n".join(msgs)
    assert msgs and SELLER not in text and BUYER not in text and "이합성" not in text and "합성아파트" not in text


def test_layout_length_must_match_own_table(tmp_path, monkeypatch):
    monkeypatch.setitem(efile_check.LENGTHS, "01", 300)
    msgs = efile_check.check_file(_write(tmp_path, _join(_lines())))
    assert len(msgs) == 1 and "레이아웃" in msgs[0]


# --- 신고값 대사 ---

MONEY03 = [f["name"] for f in L["레코드"]["03"]["필드"] if f["type"] == "N" and f["len"] == 13 and f["dec"] == 0]
MONEY05 = [f["name"] for f in L["레코드"]["05"]["필드"] if f["type"] == "N" and f["len"] == 13 and f["dec"] == 0]


def _rv():
    zero03 = {k: 0 for k in MONEY03}
    r10 = dict(zero03, 국내외분="1", 세율구분="10", **RATE)
    tot = dict(r10, 국내외분="Z", 세율구분="00", 자진납부세액=38329466)
    calc = dict({k: ASSET.get(k, 0) for k in MONEY05}, 자산="S1", 일련번호=1)
    addr = {"시도": "서울특별시", "시군구": "마포구", "읍면동": "공덕동", "특수지": "0", "번지": "1", "호": "0",
            "아파트명": "합성아파트", "아파트동": "101", "아파트호": "1001", "법정동코드": "1144010200"}
    return {"신고": {"구분코드": "03", "상세코드": "01", "유형": "1", "과세기간": "202601", "서식종류": "D03",
                    "작성일": "20261215", "제출년월": "202612", "양도일자": "20261120", "홈택스ID": "testuser01"},
            "신고인": {"성명": "김합성", "주민등록번호": SELLER, "주소": addr, "전화": "0212345678", "전자메일": None,
                     "내외국인": "1", "거주구분": "1", "거주지국": "KR", "국적": "KR"},
            "양수인": [{"자산": "S1", "일련번호": 1, "구분": "1", "내외국인": "1", "번호": BUYER, "성명": "이합성",
                     "전화": None, "지분분자": 1, "지분분모": 1, "관계": "ZA"}],
            "전자신고": {"세율별": [r10, tot], "계산명세": [calc], "필요경비명세": []}}


def test_return_values_reconcile(tmp_path):
    assert efile_check.check_file(_write(tmp_path, _join(_lines())), rv=_rv()) == []


def test_return_values_tax_base_mismatch(tmp_path):
    rv = _rv()
    rv["전자신고"]["세율별"][1]["과세표준"] += 1
    msgs = efile_check.check_file(_write(tmp_path, _join(_lines())), rv=rv)
    assert _has(msgs, "4줄(03) 8 과세표준", "신고값")


def test_return_values_missing_key_is_a_sentence(tmp_path):
    rv = _rv()
    del rv["전자신고"]["계산명세"][0]["기타필요경비"]
    del rv["신고인"]["성명"]
    msgs = efile_check.check_file(_write(tmp_path, _join(_lines())), rv=rv)
    assert _has(msgs, "신고값에", "기타필요경비", "없음") and _has(msgs, "신고값에", "신고인.성명", "없음")


def test_return_values_personal_mismatch_hides_value(tmp_path):
    rv = _rv()
    rv["신고인"]["성명"] = "박합성"
    msgs = efile_check.check_file(_write(tmp_path, _join(_lines())), rv=rv)
    assert _has(msgs, "1줄(01) 14 성명", "신고값") and not _has(msgs, "김합성") and not _has(msgs, "박합성")


# --- 명령줄 ---

def _cli(*args):
    p = subprocess.run([sys.executable, "-m", "yangdo.efile_check"] + list(args), cwd=SKILL,
                       capture_output=True, timeout=120)
    return p.returncode, p.stdout.decode("utf-8"), p.stderr.decode("utf-8")


def test_cli_pass_and_fail(tmp_path):
    ok = _write(tmp_path, _join(_lines()))
    code, out, _ = _cli(ok)
    assert code == 0 and out.strip() == "검증 통과 (12줄)"
    rv = tmp_path / "신고값.json"
    rv.write_text(json.dumps(_rv(), ensure_ascii=False), encoding="utf-8")
    assert _cli(ok, "--신고값", str(rv))[0] == 0
    bad_dir = tmp_path / "bad"
    bad_dir.mkdir()
    bad = _write(bad_dir, _join(_put(_lines(), "05", "거래금액_양도가액", 1800000001)))
    code, out, _ = _cli(bad)
    assert code == 1 and "6줄(05)" in out and "검증 통과" not in out


def test_cli_prints_warning_and_keeps_exit_zero(tmp_path):
    other = SELLER[:12] + str((int(SELLER[12]) + 1) % 10)
    code, out, err = _cli(_write(tmp_path, _join(_put(_lines(), "01", "납세자ID", other))))
    assert code == 0 and out.strip() == "검증 통과 (12줄)" and "경고" in err and other not in err
