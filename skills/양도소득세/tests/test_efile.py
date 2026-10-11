# -*- coding: utf-8 -*-
import ast
import copy
import json
import os
import shutil
import subprocess

import pytest

from yangdo import efile, efile_check, engine, filing, return_values
from cases import CASES
import filers

SKILL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EFILE = os.path.join(SKILL, "efile")
with open(os.path.join(EFILE, "layout_c116300.json"), encoding="utf-8") as _f:
    L = json.load(_f)
ORDER = ["01", "02", "03", "04", "05", "07"]
LENS = {"01": 350, "02": 400, "03": 450, "04": 150, "05": 700, "07": 200}
NAMES = {"A": "20261220C116300.01", "S1": "20261215C116300.01", "BF": "20270520C116300.01", "K": "20260820C116300.01"}
_CACHE = {}


def _rv(name):
    """합성 사례의 신고값. 법정동코드는 법정동코드 표에 있는 값으로 채운다(성수동은 코드가 둘이라 찾지 못한다)."""
    if name not in _CACHE:
        r = engine.calculate(CASES[name], today="2026-10-11")
        f = filers.get(name)
        for aid in f["자산"]:
            f["자산"][aid]["법정동코드"] = "1120011400"
        f["신고인"]["주소"]["법정동코드"] = "1144010200"
        _CACHE[name] = return_values.build(r, CASES[name], filing.load(f))
    return copy.deepcopy(_CACHE[name])


def _cut(rec, name):
    """레코드 바이트에서 레이아웃 이름으로 칸 하나를 잘라 글자로(오른쪽 공백은 뗀다)."""
    kind = rec[:2].decode()
    f = next(x for x in L["레코드"][kind]["필드"] if x["name"] == name)
    return rec[f["start"] - 1:f["end"]].decode("cp949").rstrip(" ")


def _of(recs, kind):
    return [r for r in recs if r[:2] == kind.encode()]


# ---------------------------------------------------------------- 계획서 시험

def test_record_lengths_and_order():
    recs = efile.build_records(_rv("S1"))
    kinds = [r[:2].decode() for r in recs]
    assert kinds[0] == "01" and kinds[1] == "02"
    assert kinds == sorted(kinds, key=ORDER.index)
    for r in recs:
        assert len(r) == LENS[r[:2].decode()]


def test_numeric_and_char_padding():
    recs = efile.build_records(_rv("S1"))
    r05 = next(r for r in recs if r[:2] == b"05")
    # 05-33 양도가액 N13: 0001800000000
    assert b"0001800000000" in r05
    r01 = recs[0]
    assert r01[2:9] == b"C116300"


def test_write_produces_named_file_only_after_check(tmp_path):
    out = efile.write(_rv("S1"), str(tmp_path))
    assert out["검증"] == []
    assert os.path.basename(out["경로"]) == "20261215C116300.01"
    assert out["파일명"] == "20261215C116300.01"
    with open(out["경로"], "rb") as f:
        data = f.read()
    assert data.endswith(b"\r\n") and b"\n" not in data.replace(b"\r\n", b"")
    assert os.listdir(tmp_path) == ["20261215C116300.01"]          # 임시 파일·신고값 임시 JSON 이 남지 않는다


def test_check_failure_leaves_no_file(tmp_path):
    rv = _rv("S1")
    bad = copy.deepcopy(rv)
    bad["전자신고"]["세율별"][0]["과세표준"] += 1        # 국내 소계 행을 세율구분 행 합·합계 행과 어긋나게
    out = efile.write(bad, str(tmp_path))
    assert out["경로"] is None and out["검증"]
    assert any("과세표준" in m for m in out["검증"])
    assert os.listdir(tmp_path) == []


def test_locked_spec_refuses(tmp_path, monkeypatch):
    monkeypatch.setattr(efile, "_spec_locked", lambda d=None: True)
    with pytest.raises(efile.Locked):
        efile.write(_rv("S1"), str(tmp_path))
    assert os.listdir(tmp_path) == []


def test_non_ksx1001_name_is_refused():
    rv = _rv("S1")
    rv["양수인"][0]["성명"] = "김똠"
    with pytest.raises(ValueError, match="완성형") as e:
        efile.build_records(rv)
    assert "김똠" not in str(e.value) and "양수인_성명" in str(e.value)


# ---------------------------------------------------------------- 합성 사례 네 건

@pytest.mark.parametrize("name", ["A", "S1", "BF", "K"])
def test_write_passes_check_for_synthetic_cases(tmp_path, name):
    rv = _rv(name)
    out = efile.write(rv, str(tmp_path))
    assert out["검증"] == [], out["검증"]
    assert out["파일명"] == NAMES[name] and os.path.basename(out["경로"]) == NAMES[name]
    assert os.listdir(tmp_path) == [NAMES[name]]
    # 별도 프로세스 검증과 따로, 같은 파일을 이 프로세스에서도 신고값과 대사한다
    assert efile_check.check_file(out["경로"], rv=rv) == []
    with open(out["경로"], "rb") as f:
        lines = f.read()[:-2].split(b"\r\n")
    assert lines == efile.build_records(rv)
    kinds = [x[:2].decode() for x in lines]
    assert kinds.count("03") == len(rv["전자신고"]["세율별"])
    assert kinds.count("04") == len(rv["양수인"])
    assert kinds.count("05") == len(rv["전자신고"]["계산명세"])
    assert kinds.count("07") == len(rv["전자신고"]["필요경비명세"])


# ---------------------------------------------------------------- 레코드 값

def test_header_fields():
    rv = _rv("S1")
    h = efile.build_records(rv)[0]
    want = {"자료구분": "01", "서식코드": "C116300", "납세자ID": rv["신고인"]["주민등록번호"], "납세자구분": "01",
            "세목코드": "22", "신고구분코드": "03", "신고유형": "1", "과세기간_년월": "202601", "신고구분상세코드": "01",
            "신고서종류코드": "D03", "민원종류코드": "FD001", "사용자ID": "testuser01", "제출년월": "202612",
            "성명": "김합성", "세무프로그램코드": "9000", "작성일자": "20261215", "양도일자": "20261120"}
    for name, v in want.items():
        assert _cut(h, name) == v, name
    blank = ("은행코드(국세환급금)", "계좌번호(국세환급금)", "예금종류", "세무대리대표자주민등록번호", "세무대리대표자성명",
             "세무대리인전화번호", "세무대리사업자등록번호", "세무대리인관리번호", "세무대리인성명", "세무대리인생년월일", "공란")
    for name in blank:
        assert _cut(h, name) == "", name


def test_basic_fields():
    b = efile.build_records(_rv("S1"))[1]
    want = {"주소_법정동코드": "1144010200", "주소_특수지코드": "0", "주소_번지": "1", "주소_호": "0",
            "주소_아파트명": "합성아파트", "주소_아파트동": "101", "주소_아파트호": "1001", "전화번호": "0212345678",
            "전자메일주소": "", "내외국인여부": "Y", "거주구분": "N", "거주지국코드": "KR", "거주지국명": "한국",
            "국적코드": "KR", "도로명_건물번호(본번)": "00000", "도로명_건물번호(부번)": "00000"}
    for name, v in want.items():
        assert _cut(b, name) == v, name
    assert b[2 + 7 + 10 + 1:2 + 7 + 10 + 1 + 4] == b"1   "          # 02-5 번지는 문자 칸이라 왼쪽부터, 남는 자리는 공백


def test_rate_rows():
    rows = _of(efile.build_records(_rv("S1")), "03")
    assert [(_cut(r, "국내외분"), _cut(r, "세율구분")) for r in rows] == [("1", "00"), ("1", "10"), ("Z", "00")]
    assert [_cut(r, "세율") for r in rows] == ["00000", "03800", "00000"]
    assert [_cut(r, "주민세_세율") for r in rows] == ["00000", "00000", "01000"]      # 합계 행만 01000
    assert [_cut(r, "산출세액") for r in rows] == ["0000038349466"] * 3
    assert [_cut(r, "자진납부세액") for r in rows] == ["0000000000000", "0000000000000", "0000038329466"]


def test_buyer_and_asset_and_expense_fields():
    rv = _rv("S1")
    recs = efile.build_records(rv)
    y = _of(recs, "04")[0]
    assert _cut(y, "일련번호") == "000001" and _cut(y, "양수인_양도자와의관계") == "ZA"
    assert _cut(y, "양수인_주민등록번호") == rv["양수인"][0]["번호"]
    assert _cut(y, "양수인_지분(분자)") == "00000001000" and _cut(y, "양수인_지분(분모)") == "00000001000"
    a = _of(recs, "05")[0]
    want = {"서식코드": "C116400", "일련번호": "000001", "과세구분": "ZZ", "세율구분": "10", "자산의종류": "02",
            "소재지_번지": "456", "소재지_호": "0", "거래일자_양도등기목적": "A1ZZCZ", "거래일자_양도등기원인": "0055",
            "거래자산면적_총면적_건물_면적": "00000084000", "거래자산면적_총면적_토지_지분(분자)": "00000001000",
            "취득가액종류": "01", "감면종류": "ZZZ", "감면율": "00000", "자동계산불러오기구분값": "1", "소재지국": "KR",
            "소재지국명": "한국", "소재지": "", "필요경비신고자료일련번호": "000001", "주택거주기간년수": "0007",
            "1세대1주택비과세_보유기간": "08", "1세대1주택_비과세_거주기간": "07"}
    for name, v in want.items():
        assert _cut(a, name) == v, name
    x = _of(recs, "07")
    assert [_cut(r, "구분코드") for r in x] == ["11101", "11201", "11401", "11501", "26001", "29001"]
    assert [_cut(r, "상세일련번호") for r in x] == ["%06d" % i for i in range(1, 7)]
    assert {_cut(r, "필요경비신고자료일련번호") for r in x} == {"000001"} and {_cut(r, "서식코드") for r in x} == {"C116600"}
    assert (_cut(x[0], "사업자등록번호"), _cut(x[0], "지급일자"), _cut(x[0], "증빙종류코드")) == ("", "", "ZZ")
    assert (_cut(x[2], "지급일자"), _cut(x[2], "증빙종류코드"), _cut(x[2], "지급금액")) == ("20180315", "03", "0000000800000")


def test_refund_account_only_when_refund():
    rv = _rv("S1")
    rv["환급계좌"] = {"은행코드": "004", "계좌번호": "1234567890"}
    recs, notes = efile.build(rv)
    h = recs[0]
    assert _cut(h, "은행코드(국세환급금)") == "" and _cut(h, "계좌번호(국세환급금)") == ""      # 납부할 세액이 있으면 적지 않는다
    assert notes == []                                    # 환급이 없으면 환급계좌를 읽지 않는다(C7)
    for row in rv["전자신고"]["세율별"]:
        row["자진납부할세액"] = -1000
    h = efile.build_records(rv)[0]
    assert _cut(h, "은행코드(국세환급금)") == "004" and _cut(h, "계좌번호(국세환급금)") == "1234567890"
    for row in rv["전자신고"]["세율별"]:
        row["자진납부할세액"] = -5000000                    # 환급세액 500만원 이상은 계좌를 적지 않는다(규격서 p26)
    assert _cut(efile.build_records(rv)[0], "은행코드(국세환급금)") == ""
    for row in rv["전자신고"]["세율별"]:
        row["자진납부할세액"] = -4999999
    assert _cut(efile.build_records(rv)[0], "은행코드(국세환급금)") == "004"
    rv["환급계좌"] = ""                                   # 신고인 JSON 의 빈 글자
    h = efile.build_records(rv)[0]
    assert _cut(h, "은행코드(국세환급금)") == ""
    rv["환급계좌"] = {"은행코드": "999", "계좌번호": "1234567890"}
    with pytest.raises(ValueError, match="은행코드"):
        efile.build_records(rv)


# ---------------------------------------------------------------- 칸 채우기

def test_formatters():
    assert efile._n(5230, 10) == b"0000005230"                      # 규격서 p23 수치
    assert efile._n(-100, 13) == b"-000000000100"                   # 음수는 맨 앞 부호
    assert efile._n("53.05", 5, 2) == b"05305"                      # 규격서 p19 비율
    assert efile._n("53.05", 6, 3) == b"053050" and efile._n("53.05", 7, 3) == b"0053050"
    assert efile._n(84.0, 11, 3) == b"00000084000" and efile._n(None, 4) == b"0000"
    assert efile._c("홍길동", 8) == "홍길동".encode("cp949") + b"  "
    assert efile._c(None, 3) == b"   " and efile._c("KR", 3) == b"KR "
    for bad in (lambda: efile._n(10 ** 13, 13), lambda: efile._n(-10 ** 12, 13), lambda: efile._n("abc", 5),
                lambda: efile._n(True, 5), lambda: efile._c("가나다", 5), lambda: efile._c("金합성", 10),
                lambda: efile._c("가\t나", 10), lambda: efile._c({"a": 1}, 10)):
        with pytest.raises(ValueError):
            bad()


def test_error_messages_carry_no_personal_values():
    rv = _rv("S1")
    rv["신고인"]["성명"] = "가" * 16                       # 01-14 성명은 30바이트
    with pytest.raises(ValueError, match="성명") as e:
        efile.build_records(rv)
    assert "가가" not in str(e.value)
    rv = _rv("S1")
    rv["신고인"]["주민등록번호"] = "00010112345641"         # 14자리
    with pytest.raises(ValueError, match="납세자ID") as e:
        efile.build_records(rv)
    assert "0001011" not in str(e.value)


def test_null_code_is_refused():
    rv = _rv("S1")
    rv["양수인"][0]["관계"] = None                         # 코드표 양수인관계 의 코드 null(배우자·직계)에서 온 값
    with pytest.raises(ValueError, match="규격서에 없는 코드"):
        efile.build_records(rv)
    rv = _rv("S1")
    rv["전자신고"]["계산명세"][0]["거래일자_취득등기원인"] = None    # 경매 등기원인을 받지 못한 경우
    with pytest.raises(ValueError, match="규격서에 없는 코드"):
        efile.build_records(rv)
    rv = _rv("S1")
    rv["전자신고"]["계산명세"][0]["거래일자_취득등기원인"] = ""      # 소유권보존이면 공란이 맞다
    assert _cut(_of(efile.build_records(rv), "05")[0], "거래일자_취득등기원인") == ""
    rv = _rv("S1")
    rv["양수인"][0]["내외국인"] = "7"                      # 코드표에 없는 값
    with pytest.raises(ValueError, match="규격서에 없는 코드"):
        efile.build_records(rv)


def test_missing_not_null_value_is_refused():
    rv = _rv("S1")
    rv["전자신고"]["계산명세"][0]["소재지_법정동코드"] = None
    with pytest.raises(ValueError, match="소재지_법정동코드"):
        efile.build_records(rv)


def test_filer_lot_number_is_required():
    for key, name in (("번지", "주소_번지"), ("호", "주소_호")):     # 레이아웃은 Null 허용, 항목 설명은 필수입력(규격서 p30)
        rv = _rv("S1")
        rv["신고인"]["주소"][key] = None
        with pytest.raises(ValueError, match=name):
            efile.build_records(rv)


def test_keys_not_in_layout_are_refused():
    rv = _rv("S1")
    rv["전자신고"]["세율별"][0]["없는칸"] = 1
    with pytest.raises(KeyError):
        efile.build_records(rv)
    rv = _rv("S1")
    del rv["전자신고"]["계산명세"][0]["거래금액_양도가액"]
    with pytest.raises(KeyError):
        efile.build_records(rv)


def test_other_spec_edition_is_refused():
    rv = _rv("S1")
    rv["판"]["규격"] = "V5.18"
    with pytest.raises(ValueError, match="규격"):
        efile.build_records(rv)


# ---------------------------------------------------------------- write

def test_write_removes_stale_file_and_reports_build_error(tmp_path):
    stale = tmp_path / "20261215C116300.01"
    stale.write_bytes(b"old")
    rv = _rv("S1")
    rv["양수인"][0]["성명"] = "김똠"
    out = efile.write(rv, str(tmp_path))
    assert out["경로"] is None and out["파일명"] == "20261215C116300.01"
    assert any("완성형" in m for m in out["검증"]) and not any("김똠" in m for m in out["검증"])
    assert os.listdir(tmp_path) == []                      # 옛 파일도 남기지 않는다


def test_write_replaces_existing_file(tmp_path):
    stale = tmp_path / "20261215C116300.01"
    stale.write_bytes(b"old")
    out = efile.write(_rv("S1"), str(tmp_path))
    assert out["검증"] == [] and stale.read_bytes().startswith(b"01C116300")


def test_write_passes_rrn_warning(tmp_path):
    rv = _rv("S1")
    n = rv["신고인"]["주민등록번호"]
    rv["신고인"]["주민등록번호"] = n[:12] + str((int(n[12]) + 1) % 10)      # 검증번호만 옛 규칙과 다르게
    out = efile.write(rv, str(tmp_path))
    assert out["검증"] == [] and out["경로"]
    assert len(out["경고"]) == 1 and "검증번호" in out["경고"][0] and rv["신고인"]["주민등록번호"] not in out["경고"][0]
    assert efile.write(_rv("S1"), str(tmp_path))["경고"] == []


def test_write_reports_checker_that_cannot_run(tmp_path, monkeypatch):
    out = efile.write(_rv("S1"), str(tmp_path), python=os.path.join(str(tmp_path), "없는파이썬"))
    assert out["경로"] is None and os.listdir(tmp_path) == []
    assert len(out["검증"]) == 1 and "FileNotFoundError" in out["검증"][0]      # 원인이 문장에 드러난다

    def slow(*a, **k):
        raise subprocess.TimeoutExpired(cmd="python", timeout=1)
    monkeypatch.setattr(efile.subprocess, "run", slow)
    out = efile.write(_rv("S1"), str(tmp_path))
    assert out["경로"] is None and "TimeoutExpired" in out["검증"][0] and os.listdir(tmp_path) == []


def test_lock_file(tmp_path, monkeypatch):
    assert efile._spec_locked() is False
    d = tmp_path / "efile"
    d.mkdir()
    for n in ("layout_c116300.json", "codes_c116300.json", "규격판.json"):
        shutil.copy(os.path.join(EFILE, n), str(d / n))
    assert efile._spec_locked(str(d)) is False
    with open(os.path.join(EFILE, "규격판.json"), encoding="utf-8") as f:
        spec = json.load(f)
    (d / "규격판.json").write_text(json.dumps(dict(spec, 잠금=True), ensure_ascii=False), encoding="utf-8")
    assert efile._spec_locked(str(d)) is True
    out = tmp_path / "out"
    monkeypatch.setattr(efile, "EFILE_DIR", str(d))
    with pytest.raises(efile.Locked, match="잠"):
        efile.write(_rv("S1"), str(out))
    assert not out.exists()                                # 잠금이면 출력 폴더를 건드리지 않는다
    (d / "규격판.json").write_text(json.dumps(dict(spec, 판="V5.18"), ensure_ascii=False), encoding="utf-8")
    assert efile._spec_locked(str(d)) is True              # 규격판과 레이아웃의 판이 다르면 만들지 않는다
    os.remove(str(d / "규격판.json"))
    assert efile._spec_locked(str(d)) is True              # 규격판을 읽지 못해도 만들지 않는다


def test_does_not_import_checker():
    with open(os.path.join(SKILL, "yangdo", "efile.py"), encoding="utf-8") as f:
        tree = ast.parse(f.read())
    names = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module} | \
            {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names} | \
            {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names}
    assert not any("efile_check" in n for n in names)


# ---------------------------------------------------------------- 검토 1차 반영

def _walk(root):
    return [os.path.join(d, n) for d, _, names in os.walk(str(root)) for n in names]


def _submission_named(paths):
    return [p for p in paths if efile_check.FILE_NAME.match(os.path.basename(str(p)))]


def _bad_rv():
    rv = _rv("S1")
    rv["전자신고"]["세율별"][0]["과세표준"] += 1
    return rv


def _refuse(*a, **k):
    raise PermissionError("흉내 낸 삭제 실패")


def test_failed_check_leaves_no_submission_named_file_when_folder_cannot_be_removed(tmp_path, monkeypatch):
    # 임시 폴더 삭제가 막혀도(백신·색인기가 잡은 경우) 검증에 실패한 파일이 제출용 이름으로 남으면 안 된다
    monkeypatch.setattr(efile.shutil, "rmtree", _refuse)
    out = efile.write(_bad_rv(), str(tmp_path))
    monkeypatch.undo()
    assert out["경로"] is None
    assert _submission_named(_walk(tmp_path)) == []
    left = [n for n in os.listdir(tmp_path) if n.startswith(".efile-")]
    assert len(left) == 1                                  # 폴더는 남았고
    assert any("임시 폴더" in m and left[0] in m for m in out["검증"])      # 남았다는 것을 알린다
    out = efile.write(_rv("S1"), str(tmp_path))            # 다음 실행이 남은 폴더를 쓸어 낸다
    assert out["검증"] == [] and out["경고"] == [] and os.listdir(tmp_path) == ["20261215C116300.01"]


def test_blocked_temp_file_is_renamed_away_from_submission_name(tmp_path, monkeypatch):
    real_remove = os.remove

    def remove(path, *a, **k):
        if ".efile-" in str(path) and _submission_named([path]):
            raise PermissionError("흉내 낸 삭제 실패")
        return real_remove(path, *a, **k)
    monkeypatch.setattr(efile.os, "remove", remove)
    monkeypatch.setattr(efile.shutil, "rmtree", _refuse)
    out = efile.write(_bad_rv(), str(tmp_path))
    monkeypatch.undo()
    assert out["경로"] is None
    files = _walk(tmp_path)
    assert files and _submission_named(files) == []        # 지우지 못한 파일은 제출용이 아닌 이름으로 바뀌었다
    assert any("임시 폴더" in m for m in out["검증"])


def test_stuck_submission_named_file_is_reported(tmp_path, monkeypatch):
    real_remove, real_replace = os.remove, os.replace

    def stuck(path):
        return ".efile-" in str(path) and _submission_named([path])

    def remove(path, *a, **k):
        if stuck(path):
            raise PermissionError("흉내 낸 삭제 실패")
        return real_remove(path, *a, **k)

    def replace(src, dst, *a, **k):
        if stuck(src):
            raise PermissionError("흉내 낸 이름 바꾸기 실패")
        return real_replace(src, dst, *a, **k)
    monkeypatch.setattr(efile.os, "remove", remove)
    monkeypatch.setattr(efile.os, "replace", replace)
    monkeypatch.setattr(efile.shutil, "rmtree", _refuse)
    out = efile.write(_bad_rv(), str(tmp_path))
    monkeypatch.undo()
    assert out["경로"] is None
    assert any("제출하지" in m and "20261215C116300.01" in m for m in out["검증"])


def test_leftover_folder_after_success_is_warned(tmp_path, monkeypatch):
    monkeypatch.setattr(efile.shutil, "rmtree", _refuse)
    out = efile.write(_rv("S1"), str(tmp_path))
    monkeypatch.undo()
    assert out["검증"] == [] and os.path.isfile(out["경로"])
    assert any("임시 폴더" in m for m in out["경고"])       # 신고값 임시 JSON 이 남았을 수 있다
    assert _submission_named(_walk(tmp_path)) == [out["경로"]]


def test_write_sweeps_folders_left_by_killed_run(tmp_path):
    old = tmp_path / ".efile-killed"
    old.mkdir()
    (old / "20261215C116300.01").write_bytes(b"unchecked")
    (old / "신고값.json").write_text("{}", encoding="utf-8")
    keep = tmp_path / "다른파일.txt"
    keep.write_text("x", encoding="utf-8")
    out = efile.write(_bad_rv(), str(tmp_path))            # 실패하는 실행이어도 쓸어 낸다
    assert out["경로"] is None and os.listdir(tmp_path) == ["다른파일.txt"]


def test_codes_are_read_from_code_table(tmp_path):
    with open(os.path.join(EFILE, "codes_c116300.json"), encoding="utf-8") as f:
        codes = json.load(f)
    assert codes["납세자구분"]["1"]["코드"] == "01" and codes["납세자구분"]["9"]["코드"] == "09"
    assert codes["세무프로그램코드"]["기타"]["코드"] == "9000"
    for table in ("납세자구분", "세무프로그램코드"):
        assert table in codes["메타"]["필드"]
        assert all(isinstance(v["쪽"], int) and v["이름"] for v in codes[table].values())
    assert "형식검증" in codes["납세자구분"]["9"]["메모"]
    assert not hasattr(efile, "TAXPAYER_KIND") and not hasattr(efile, "PROGRAM_CODE")
    d = tmp_path / "efile"
    d.mkdir()
    shutil.copy(os.path.join(EFILE, "layout_c116300.json"), str(d / "layout_c116300.json"))
    codes["세무프로그램코드"]["기타"]["코드"] = "1001"
    codes["납세자구분"]["1"]["코드"] = "07"
    (d / "codes_c116300.json").write_text(json.dumps(codes, ensure_ascii=False), encoding="utf-8")
    h = efile.build_records(_rv("S1"), efile_dir=str(d))[0]
    assert _cut(h, "세무프로그램코드") == "1001" and _cut(h, "납세자구분") == "07"
    codes["납세자구분"]["1"]["코드"] = None
    (d / "codes_c116300.json").write_text(json.dumps(codes, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="규격서에 없는 코드"):
        efile.build_records(_rv("S1"), efile_dir=str(d))


def _foreign_rv():
    rv = _rv("S1")
    rv["신고인"].update({"내외국인": "9", "국적": "US"})
    rv["신고인"]["코드"].update({"내외국인여부": "N", "국적": "US"})
    return rv


def test_foreign_filer_code_is_warned(tmp_path):
    rv = _foreign_rv()
    recs, notes = efile.build(rv)
    assert _cut(recs[0], "납세자구분") == "09"
    assert len(notes) == 1 and "01-4 납세자구분" in notes[0] and "형식검증" in notes[0]
    assert rv["신고인"]["주민등록번호"] not in notes[0] and rv["신고인"]["성명"] not in notes[0]
    out = efile.write(rv, str(tmp_path))
    assert out["검증"] == [] and out["경고"] == notes
    assert efile.build(_rv("S1"))[1] == []


def test_write_refuses_other_efile_dir(tmp_path):
    d = tmp_path / "efile"
    shutil.copytree(EFILE, str(d), ignore=shutil.ignore_patterns("법정동코드.json"))
    out = tmp_path / "out"
    with pytest.raises(ValueError, match="efile_dir"):
        efile.write(_rv("S1"), str(out), efile_dir=str(d))
    assert not out.exists()
    assert efile.write(_rv("S1"), str(out), efile_dir=EFILE)["검증"] == []        # 기본 폴더를 적어 주는 것은 된다
    assert len(efile.build_records(_rv("S1"), efile_dir=str(d))) == 13              # build_records 의 인자는 그대로


def test_dropped_refund_account_is_warned():
    def notes(acct, due):
        rv = _rv("S1")
        rv["환급계좌"] = acct
        for row in rv["전자신고"]["세율별"]:
            row["자진납부할세액"] = due
        recs, out = efile.build(rv)
        assert _cut(recs[0], "은행코드(국세환급금)") == "" and _cut(recs[0], "계좌번호(국세환급금)") == ""
        return out
    assert notes({"은행코드": "004", "계좌번호": "1234567890"}, 1000) == []
    assert notes(None, -1000) == [] and notes("", -1000) == []
    for acct, due in (({"은행코드": "004", "계좌번호": ""}, -1000), ({"은행코드": None, "계좌번호": "1234567890"}, -1000),
                      ({"은행코드": "004", "계좌번호": "1234567890"}, -5000000), ("004-1234567890", -1000)):
        out = notes(acct, due)
        assert len(out) == 1 and "환급계좌" in out[0] and "1234567890" not in out[0], (acct, due)


def test_missing_numeric_value_is_refused():
    for key, name in (("지분분자", "양수인_지분.분자"), ("지분분모", "양수인_지분.분모")):
        rv = _rv("S1")
        rv["양수인"][0][key] = None
        with pytest.raises(ValueError, match=name):
            efile.build_records(rv)
    rv = _rv("S1")
    rv["전자신고"]["계산명세"][0]["거래금액_양도가액"] = None
    with pytest.raises(ValueError, match="거래금액_양도가액"):
        efile.build_records(rv)
