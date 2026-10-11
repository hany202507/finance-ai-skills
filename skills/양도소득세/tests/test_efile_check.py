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


def test_import_does_not_load_generator_modules():
    # 정적 시험은 「from yangdo import calc」 꼴을 못 잡으므로 실제로 import 한 뒤 불러온 모듈을 본다
    code = ("import sys, yangdo.efile_check; "
            "print(','.join(m for m in ('yangdo.efile', 'yangdo.efile_text', 'yangdo.return_values', 'yangdo.calc') "
            "if m in sys.modules))")
    p = subprocess.run([sys.executable, "-c", code], cwd=SKILL, capture_output=True, timeout=120)
    assert p.returncode == 0, p.stderr.decode("utf-8", "replace")
    assert p.stdout.decode("ascii").strip() == ""


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
TOTAL_LOCAL_RATE = {"주민세_세율": 10}    # 03-31 은 합계 행(Z/00)만 01000, 나머지 행은 0(p43, global.md 03-31 결정)
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
            _rec("03", dict(RATE, 국내외분="Z", 세율구분="00", 자진납부세액=38329466, **TOTAL_LOCAL_RATE)),
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
             _rec("03", dict(rate, 국내외분="Z", 세율구분="00", 자진납부세액=19690000, **TOTAL_LOCAL_RATE)),
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


def _with_extra_rate_rows():
    """픽스처에 국내 소계(1/00)와 지방소득세(Z/98) 행을 더한 줄들. 둘 다 31 = 0 이다."""
    lines = _lines()
    lines.insert(2, _rec("03", dict(RATE, 국내외분="1", 세율구분="00")))
    lines.insert(5, _rec("03", {"국내외분": "Z", "세율구분": "98"}))
    return lines


def test_local_tax_rate_fixture_and_extra_rows_pass(tmp_path):
    f = _field("03", "주민세_세율")
    rates = {x[9:12]: x[f["start"] - 1:f["end"]] for x in _lines() if x[:2] == b"03"}
    assert rates == {b"110": b"00000", b"Z00": b"01000"}
    assert _check(tmp_path, _with_extra_rate_rows()) == []


@pytest.mark.parametrize("row,line,value,ok", [
    (0, 3, 0, True), (0, 3, 10, False),          # 세율구분 행 1/10: 00000 통과, 01000 실패
    (1, 4, 10, True), (1, 4, 0, False),          # 합계 행 Z/00: 01000 통과, 00000 실패
])
def test_local_tax_rate_by_row(tmp_path, row, line, value, ok):
    msgs = _check(tmp_path, _put(_lines(), "03", "주민세_세율", value, nth=row))
    assert (msgs == []) == ok
    if not ok:
        assert _has(msgs, "%d줄(03) 31 주민세_세율" % line, "p43")


@pytest.mark.parametrize("row,line", [(0, 3), (3, 6)])      # 소계 1/00(3줄), Z/98(6줄)
def test_local_tax_rate_subtotal_and_local_rows_must_be_zero(tmp_path, row, line):
    msgs = _check(tmp_path, _put(_with_extra_rate_rows(), "03", "주민세_세율", 10, nth=row))
    assert _has(msgs, "%d줄(03) 31 주민세_세율" % line, "합계 행(Z/00) 이외는 0")


@pytest.mark.parametrize("name", ["주민세_소득세자진납부할세액", "주민세_산출세액", "주민세_자진납부세액"])
def test_local_tax_amounts_are_zero(tmp_path, name):
    msgs = _check(tmp_path, _put(_lines(), "03", name, 1000, nth=1))
    assert _has(msgs, "4줄(03)", name, "0")


def test_credit_caps(tmp_path):
    msgs = _check(tmp_path, _put(_lines(), "03", "전자신고세액공제", 20001, nth=1))
    assert _has(msgs, "4줄(03) 36 전자신고세액공제", "20000")
    msgs = _check(tmp_path, _put(_lines(), "03", "전자신고세액공제", 20001, nth=0))
    assert _has(msgs, "3줄(03) 36 전자신고세액공제", "세율별")
    msgs = _check(tmp_path, _put(_lines(), "03", "연금계좌세액공제", 10000001, nth=1))
    assert _has(msgs, "4줄(03) 37 연금계좌세액공제", "10000000")


@pytest.mark.parametrize("proof,ok", [("05", True), ("10", True), ("06", False)])
def test_contract_proof_code_05_is_accepted(tmp_path, proof, ok):
    # p61 표: 01 현금영수증, 02 신용카드 영수증, 03 세금계산서, 04 계산서, 05 계약서, 10 기타
    msgs = _check(tmp_path, _put(_lines(), "07", "증빙종류코드", proof, nth=2))
    assert (msgs == []) == ok
    if not ok:
        assert _has(msgs, "9줄(07) 10 증빙종류코드")


def test_ksx_empty_cell_is_a_sentence_not_an_exception(tmp_path):
    # 0xA2E8 은 바이트 범위로는 기호 행이지만 표의 빈 자리라 CP949 로 읽히지 않는다
    lines = _lines()
    i = _idx(lines, "04")
    f = _field("04", "양수인_성명")
    x = lines[i]
    lines[i] = x[:f["start"] - 1] + bytes([0xA2, 0xE8]) + x[f["start"] + 1:]
    msgs = _check(tmp_path, lines)
    assert _has(msgs, "5줄(04) 7 양수인_성명", "완성형에 없는 글자")


def test_page_basis_in_row_formula_sentences(tmp_path):
    msgs = _check(tmp_path, _put(_lines(), "05", "거래금액_양도가액", 1800000001))
    assert _has(msgs, "6줄(05) 38", "(브리프)")
    msgs = _check(tmp_path, _put(_lines(), "05", "양도차익_비과세양도차익", 779466668))
    assert _has(msgs, "6줄(05) 40", "p50")


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


def _rv_row(kind, vals, **extra):
    """레이아웃 name 을 키로 하는 신고값 전자신고 행. 자료구분·서식코드와 공란을 뺀 모든 칸을 싣는다(없는 수치 칸은 0, 문자 칸은 빈 글자)."""
    row = {f["name"]: vals.get(f["name"], 0 if f["type"] == "N" else "")
           for f in L["레코드"][kind]["필드"] if f["no"] > 2 and f["class"] != "SPACE"}
    row.update(extra)
    return row


def _rv():
    r10 = _rv_row("03", dict(RATE, 국내외분="1", 세율구분="10"))
    tot = _rv_row("03", dict(RATE, 국내외분="Z", 세율구분="00", 자진납부세액=38329466, 주민세_세율="10.00"))
    calc = _rv_row("05", ASSET, 자산="S1", 일련번호=1)
    # 07 행은 신고값 키가 다르다: 일련번호, 전자코드(5자리), 사업자번호. 구분코드는 서식 부표3 의 3자리다
    exps = [{"일련번호": 1, "전자코드": c, "상세일련번호": i, "상호": who, "사업자번호": biz, "지급일자": day,
             "지급금액": amt, "증빙종류코드": proof, "구분코드": c[:3], "자산": "S1"}
            for i, (c, who, biz, day, amt, proof) in enumerate(EXPENSES, 1)]
    addr = {"시도": "서울특별시", "시군구": "마포구", "읍면동": "공덕동", "특수지": "0", "번지": "1", "호": "0",
            "아파트명": "합성아파트", "아파트동": "101", "아파트호": "1001", "법정동코드": "1144010200"}
    return {"신고": {"구분코드": "03", "상세코드": "01", "유형": "1", "과세기간": "202601", "서식종류": "D03",
                    "작성일": "20261215", "제출년월": "202612", "양도일자": "20261120", "홈택스ID": "testuser01"},
            "신고인": {"성명": "김합성", "주민등록번호": SELLER, "주소": addr, "전화": "0212345678", "전자메일": None,
                     "내외국인": "1", "거주구분": "1", "거주지국": "KR", "국적": "KR"},
            "양수인": [{"자산": "S1", "일련번호": 1, "구분": "1", "내외국인": "1", "번호": BUYER, "성명": "이합성",
                     "전화": None, "지분분자": 1, "지분분모": 1, "관계": "ZA"}],
            "전자신고": {"세율별": [r10, tot], "계산명세": [calc], "필요경비명세": exps}}


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


def test_return_values_buyer_asset_missing(tmp_path):
    rv = _rv()
    del rv["양수인"][0]["자산"]
    msgs = efile_check.check_file(_write(tmp_path, _join(_lines())), rv=rv)
    assert "신고값에 양수인[0].자산 없음" in msgs


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


# ---- 03 가산세 칸(15 신고불성실, 16 납부불성실, 17 계, 35 기장불성실등, 규격서 p41·p43) ----
# 예정신고를 하지 않은 확정신고 파일은 이 칸에 예정신고 무신고가산세와 납부지연가산세를 적는다(계획 2b G1b).
# 검증기는 가산세가 0 이어야 한다고 보지 않는다. 행 안의 산식, 합계 행 = 세율구분 행 합, 신고값 대사로 본다.

def _with_penalty(nonfiling=20000, delay=5000):
    """S1 정상 파일의 03 두 행에 가산세를 산식에 맞게 넣는다. 납부할 세액 38,329,466 에 가산세가 더해진다."""
    lines = _lines()
    for nth in (0, 1):
        lines = _put(lines, "03", "가산세-신고불성실", nonfiling, nth=nth)
        lines = _put(lines, "03", "가산세-납부불성실", delay, nth=nth)
        lines = _put(lines, "03", "가산세-계", nonfiling + delay, nth=nth)
        lines = _put(lines, "03", "자진납부할세액", 38329466 + nonfiling + delay, nth=nth)
    return _put(lines, "03", "자진납부세액", 38329466 + nonfiling + delay, nth=1)


def test_penalty_cells_consistent_file_passes(tmp_path):
    assert _check(tmp_path, _with_penalty()) == []


@pytest.mark.parametrize("name,no", [("가산세-신고불성실", "15"), ("가산세-납부불성실", "16")])
def test_penalty_cell_changed_in_one_row_is_caught(tmp_path, name, no):
    """세율구분 행의 가산세 한 칸만 바꾸면 그 행의 계(17)와, 합계 행 = 세율구분 행 합(p41 15~17번)에서 걸린다."""
    lines = _put(_with_penalty(), "03", name, 12345, nth=0)
    msgs = _check(tmp_path, lines)
    assert _has(msgs, "3줄(03)", "17 가산세-계", "가산세 합")
    assert _has(msgs, "4줄(03)", "%s %s" % (no, name), "세율구분 행 합")


def test_penalty_total_must_be_in_tax_due(tmp_path):
    """17 가산세-계가 19 자진납부할세액에 들어가지 않으면 걸린다(서식 ⑱ = ⑩-⑪-⑫-⑬-⑭-⑮+⑯-⑰)."""
    lines = _with_penalty()
    for nth in (0, 1):
        lines = _put(lines, "03", "자진납부할세액", 38329466, nth=nth)
    lines = _put(lines, "03", "자진납부세액", 38329466, nth=1)
    msgs = _check(tmp_path, lines)
    assert _has(msgs, "3줄(03)", "19", "가산세") and _has(msgs, "4줄(03)", "19", "가산세")


def test_bookkeeping_penalty_cell_is_part_of_the_total(tmp_path):
    lines = _put(_with_penalty(), "03", "가산세-기장불성실등", 700, nth=0)
    assert _has(_check(tmp_path, lines), "3줄(03)", "17 가산세-계")


def test_penalty_cells_are_reconciled_with_return_values(tmp_path):
    """파일 안에서는 서로 맞게 바꿔도 신고값 전자신고.세율별 의 가산세 칸과 다르면 걸린다."""
    rv = _rv()
    for x in rv["전자신고"]["세율별"]:
        last = x["국내외분"] == "Z"
        x.update({"가산세-신고불성실": 20000, "가산세-납부불성실": 5000, "가산세-계": 25000, "자진납부할세액": 38354466,
                  "자진납부세액": 38354466 if last else 0})
    assert _check(tmp_path, _with_penalty(), rv=rv) == []
    msgs = _check(tmp_path, _with_penalty(nonfiling=10000), rv=rv)        # 파일은 무신고 10,000, 신고값은 20,000
    assert _has(msgs, "3줄(03)", "15 가산세-신고불성실", "신고값 20000") and _has(msgs, "4줄(03)", "17 가산세-계", "신고값 25000")


# --- 신고값 대사 범위: 05 의 날짜·면적·법정동코드·지번·코드와 07 전체 ---
# 파일의 그 칸만 형식에 맞는 다른 값으로 바꾼다. 신고값 없이 검사하면 통과하는 칸(형식만 맞으면 되는 칸)도 신고값과 대사하면 걸린다.

# (칸 이름, 바꿔 넣을 값, 신고값 없이도 다른 검사에 걸리는지)
TAMPER_05 = [
    ("거래일자_취득일자", "20180316", False),
    ("거래일자_양도일자", "20261119", True),            # HEADER 양도일자와 달라진다
    ("거래자산면적_총면적_토지_면적", 31, False),
    ("거래자산면적_총면적_토지_지분(분자)", 2, False),
    ("거래자산면적_총면적_건물_지분(분모)", 2, False),
    ("거래자산면적_양도면적_건물_면적", "84.5", False),
    ("거래자산면적_취득면적_토지_면적", "30.001", False),
    ("소재지_법정동코드", "1144010200", False),
    ("소재지_특수지코드", "1", False),
    ("소재지_번지", "457", False),
    ("소재지_호", "1", False),
    ("소재지_아파트명", "다른아파트", False),
    ("소재지_아파트동", "102", False),
    ("소재지_아파트호", "1002", False),
    ("거래일자_양도등기원인", "0028", False),           # 교환(p109). 등기목적 A1ZZCZ 의 코드다
    ("거래일자_취득등기원인", "0028", False),
    ("거래일자_취득등기목적", "A1ZZAZ", True),          # 소유권보존이면 등기원인을 적지 않는다
    ("자산의종류", "03", False),
    ("과세구분", "01", False),
    ("세율구분", "15", True),                           # 03 에 세율구분 15 행이 없다
    ("취득가액종류", "02", False),
    ("주택거주기간년수", 8, False),
    ("1세대1주택비과세_보유기간", "09", False),
    ("1세대1주택_비과세_거주기간", "06", False),
    ("장기보유특별공제적용구분코드", "Z1", False),
]


@pytest.mark.parametrize("name,value,caught_anyway", TAMPER_05, ids=[t[0] for t in TAMPER_05])
def test_asset_record_cell_is_reconciled_with_return_values(tmp_path, name, value, caught_anyway):
    lines = _put(_lines(), "05", name, value)
    no = _field("05", name)["no"]
    msgs = _check(tmp_path, lines, rv=_rv())
    assert _has(msgs, "6줄(05) %d %s" % (no, name), "신고값 전자신고.계산명세[1].%s 와 다름" % name), msgs
    if not caught_anyway:
        assert _check(tmp_path, lines) == []        # 신고값이 없으면 형식만 보므로 통과한다


# 07 은 줄을 (일련번호, 구분코드, 상세일련번호)로 신고값 행과 잇는다. 넷째 줄(11501, 중개수수료)의 칸을 바꾼다
TAMPER_07 = [
    ("상호", "다른공인중개사", "상호", False),
    ("사업자등록번호", BIZ_LAW, "사업자번호", False),
    ("지급일자", "20180316", "지급일자", False),
    ("증빙종류코드", "02", "증빙종류코드", False),
    ("지급금액", 2400001, "지급금액", True),            # 05-34 취득가액과 07 합이 달라진다
]


@pytest.mark.parametrize("name,value,key,caught_anyway", TAMPER_07, ids=[t[0] for t in TAMPER_07])
def test_expense_record_cell_is_reconciled_with_return_values(tmp_path, name, value, key, caught_anyway):
    lines = _put(_lines(), "07", name, value, nth=3)
    no = _field("07", name)["no"]
    msgs = _check(tmp_path, lines, rv=_rv())
    assert _has(msgs, "10줄(07) %d %s" % (no, name), "신고값"), msgs
    if name != "지급금액":
        assert _has(msgs, "신고값 전자신고.필요경비명세[1/11501/4].%s 와 다름" % key), msgs
    if not caught_anyway:
        assert _check(tmp_path, lines) == []


def test_expense_record_code_changed_is_a_missing_row(tmp_path):
    """구분코드를 같은 묶음의 다른 코드로 바꾸면(26001 → 26002) 파일 안의 합은 그대로라 신고값 없이는 통과한다."""
    lines = _put(_lines(), "07", "구분코드", "26002", nth=4)
    assert _check(tmp_path, lines) == []
    msgs = _check(tmp_path, lines, rv=_rv())
    assert _has(msgs, "11줄(07)", "신고값 전자신고.필요경비명세 에 1/26002/5 행이 없음")
    assert _has(msgs, "신고값 전자신고.필요경비명세 의 1/26001/5 행이 파일에 없음")


def test_expense_rows_must_exist_on_both_sides(tmp_path):
    rv = _rv()
    dropped = rv["전자신고"]["필요경비명세"].pop()
    msgs = _check(tmp_path, _lines(), rv=rv)
    assert _has(msgs, "12줄(07)", "필요경비명세 에 1/%s/6 행이 없음" % dropped["전자코드"])
    rv = _rv()
    del rv["전자신고"]["필요경비명세"]
    assert _has(_check(tmp_path, _lines(), rv=rv), "신고값에 전자신고.필요경비명세 없음")


def test_rate_cells_of_rate_record_are_reconciled(tmp_path):
    """03 의 세율 칸(5자리 고정 소수)도 신고값과 대사한다."""
    rv = _rv()
    rv["전자신고"]["세율별"][0]["세율"] = "38.00"
    msgs = _check(tmp_path, _lines(), rv=rv)
    assert _has(msgs, "3줄(03) 9 세율", "신고값 전자신고.세율별[1/10].세율 와 다름")


def test_reconcile_sentences_carry_names_not_values(tmp_path):
    """지번과 07 상호는 인적 성격의 값이다. 다르다는 문장에 파일 값도 신고값도 싣지 않는다."""
    lines = _put(_lines(), "07", "상호", "다른매도인", nth=0)
    lines = _put(lines, "05", "소재지_번지", "457")
    lines = _put(lines, "05", "소재지_아파트명", "다른아파트")
    rv = _rv()
    rv["전자신고"]["계산명세"][0]["소재지_아파트동"] = "909"
    text = "\n".join(_check(tmp_path, lines, rv=rv))
    assert "소재지_번지" in text and "상호" in text and "소재지_아파트동" in text
    for v in ("다른매도인", "합성매도인", "457", "456", "다른아파트", "합성아파트", "909", SELLER, BUYER):
        assert v not in text, v


@pytest.mark.parametrize("key,value,word", [
    ("거래자산면적_총면적_토지_면적", "서른", "수가 아님"),
    ("주택거주기간년수", 7.5, "정수가 아님"),
    ("소재지_번지", ["456"], "글자가 아님"),
    ("일련번호", "첫째", None),
])
def test_unreadable_return_value_is_a_sentence(tmp_path, key, value, word):
    rv = _rv()
    rv["전자신고"]["계산명세"][0][key] = value
    msgs = _check(tmp_path, _lines(), rv=rv)        # 예외 없이 문장으로 알린다
    assert msgs and (word is None or _has(msgs, "신고값 전자신고.계산명세[1].%s" % key, word)), msgs


def test_long_term_deduction_allowed_for_rate_code_11(tmp_path):
    """05-41 장기보유특별공제는 세율구분 10 과 11(2년 이상 보유한 비사업용 토지)에서 받는다(p33, p50, p51)."""
    lines = _put(_put(_lines(), "05", "세율구분", "11"), "03", "세율구분", "11")
    assert not _has(_check(tmp_path, lines), "41 장기보유특별공제")
    lines = _put(_put(_lines(), "05", "세율구분", "15"), "03", "세율구분", "15")
    assert _has(_check(tmp_path, lines), "6줄(05) 41 장기보유특별공제", "세율구분 10·11")

