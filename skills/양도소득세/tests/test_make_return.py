# -*- coding: utf-8 -*-
"""신고서·전자신고 실행 진입점(scripts/make_return.py)과 MCP 도구 yangdo_forms, yangdo_efile.

종료코드 다섯 가지(0 완료, 1 서식 검산·전자신고 검증 실패, 2 질문·다루지않음, 3 기준정보·규격판 오류, 4 쓰기 실패)와
출력 파일이 언제 생기는지, 이전 결과를 지우는지, 인적사항이 화면·확인 문서·MCP 응답에 실리지 않는지를 본다.
"""
import ast
import copy
import json
import os
import subprocess
import sys

import pytest

import filers
import make_return as MR
import mcp_server
from cases import CASES
from yangdo import efile, forms, forms_pdf, return_values

SKILL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(SKILL, "scripts", "make_return.py")
TODAY = "2026-10-11"
DASH = chr(0x2014)  # 문체 규칙으로 금지한 줄표. 소스에 글자를 직접 적지 않는다
PDFS = {"양도소득세_신고서.pdf", "지방소득세_신고서.pdf"}
GUIDES = {"홈택스_입력안내.md", "부속서류.md"}
CALC = {"result.json", "양도소득세_검토.md", "양도소득세_계산근거.xlsx"}
S1_FILE = "20261215C116300.01"


def s1_filer():
    f = filers.get("S1")
    f["자산"]["S1"]["법정동코드"] = "1120011400"      # 성수동은 법정동코드가 둘이라 직접 적는다
    return f


def g_filer():
    """전액 비과세 사례 G 의 합성 신고인."""
    return filers.filer("예정", "2026-12-20", {"G": filers.lot("77", filers.SELLER)}, [filers.buyer("G")])


def _write(tmp_path, name, filer):
    fp, gp, out = tmp_path / "f.json", tmp_path / "g.json", tmp_path / "out"
    fp.write_text(json.dumps(CASES[name], ensure_ascii=False), encoding="utf-8")
    gp.write_text(json.dumps(filer, ensure_ascii=False), encoding="utf-8")
    return fp, gp, out


def _run(tmp_path, name, filer):
    """별도 프로세스로 돌린다. 자식의 입출력은 UTF-8 로 고정한다(Windows 기본 cp949 로 깨지지 않게)."""
    fp, gp, out = _write(tmp_path, name, filer)
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    p = subprocess.run([sys.executable, SCRIPT, "--사실관계", str(fp), "--신고인", str(gp), "--출력", str(out), "--오늘", TODAY],
                       capture_output=True, text=True, encoding="utf-8", env=env, timeout=300)
    return p, out


def _main(tmp_path, name, filer, extra=()):
    """같은 프로세스에서 main 을 부른다. (종료코드, 출력 폴더)."""
    fp, gp, out = _write(tmp_path, name, filer)
    code = MR.main(["--사실관계", str(fp), "--신고인", str(gp), "--출력", str(out), "--오늘", TODAY] + list(extra))
    return code, out


def _confirm(out):
    with open(os.path.join(str(out), "신고_확인.md"), encoding="utf-8") as fh:
        return fh.read()


def _efiles(out):
    return [n for n in os.listdir(str(out)) if "C116300" in n]


def _personal(filer):
    """화면·확인 문서·MCP 응답에 나오면 안 되는 값."""
    p = filer["신고인"]
    vals = [p["성명"], p["주민등록번호"], p["전화"], filer["신고"]["홈택스ID"]]
    vals += [b[k] for b in filer["양수인"] for k in ("성명", "번호")]
    vals += [lot["취득상대방"] for lot in filer["자산"].values() if lot.get("취득상대방")]
    return vals


# ---------------------------------------------------------------- 지시서 시험

def test_full_pipeline_s1(tmp_path):
    f = s1_filer()
    p, out = _run(tmp_path, "S1", f)
    assert p.returncode == 0, p.stdout + p.stderr
    names = set(os.listdir(out))
    assert {"양도소득세_신고서.pdf", "지방소득세_신고서.pdf", S1_FILE, "신고값.json",
            "홈택스_입력안내.md", "부속서류.md", "신고_확인.md"} <= names
    assert CALC <= names and "질문.md" not in names
    assert not [n for n in names if n.startswith(".efile-") or n.endswith(".tmp")]
    text = _confirm(out)
    for v in _personal(f):
        assert v not in text and v not in p.stdout and v not in p.stderr
    assert S1_FILE in p.stdout and "Traceback" not in p.stderr


def test_missing_filer_info_returns_questions(tmp_path):
    p, out = _run(tmp_path, "S1", filers.get("S1"))       # 성수동은 법정동코드가 둘
    assert p.returncode == 2
    assert "F04" in open(out / "신고_확인.md", encoding="utf-8").read()
    assert not any(n.endswith(".01") for n in os.listdir(out))
    names = set(os.listdir(out))
    assert CALC <= names                                   # 계산은 끝났다
    assert not (PDFS | GUIDES | {"신고값.json"}) & names   # 신고인 정보가 모자라 신고값부터 만들지 않는다


def test_mcp_forms_and_efile_do_not_echo_personal_data(tmp_path):
    f = s1_filer()
    gp = tmp_path / "g.json"
    gp.write_text(json.dumps(f, ensure_ascii=False), encoding="utf-8")
    res = mcp_server.call_tool("yangdo_efile", {"facts": CASES["S1"], "filer_path": str(gp), "out_dir": str(tmp_path / "o"), "오늘": TODAY})
    s = json.dumps(res, ensure_ascii=False)
    assert "김합성" not in s and f["신고인"]["주민등록번호"] not in s
    assert "C116300" in s
    for v in _personal(f):
        assert v not in s
    assert res["종료코드"] == 0 and res["상태"] == "완료"
    assert any(x.endswith(S1_FILE) for x in res["파일"]) and res["전자신고"]["파일명"] == S1_FILE
    assert res["서식검산"] == [] and res["전자신고"]["검증"] == []
    assert any("홈택스" in x for x in res["사람이할일"]) and any("위택스" in x for x in res["사람이할일"])


# ---------------------------------------------------------------- 종료코드 0

# 확정신고(BF)는 가산세를 계산하지 않아 신고서와 전자신고 파일을 만들지 않는다. 아래 「확정신고」 시험이 본다
@pytest.mark.parametrize("name,file_name,law", [
    ("A", "20261220C116300.01", {}),
    ("K", "20260820C116300.01", {}),
])
def test_other_cases_run_to_the_end(tmp_path, capsys, name, file_name, law):
    f = filers.get(name)
    for aid, code in law.items():
        f["자산"][aid]["법정동코드"] = code
    code, out = _main(tmp_path, name, f)
    shown = capsys.readouterr()
    assert code == 0, shown.out + shown.err + _confirm(out)
    names = set(os.listdir(out))
    assert PDFS | GUIDES | CALC | {file_name, "신고값.json", "신고_확인.md"} <= names
    text = _confirm(out)
    for v in _personal(f):
        assert v not in text and v not in shown.out
    assert "서식 검산" in text and "전자신고 검증" in text and "통과" in text


def test_confirm_document_lists_what_people_do(tmp_path):
    code, out = _main(tmp_path, "S1", s1_filer())
    assert code == 0
    text = _confirm(out)
    todo = text.split("## 사람이 할 일", 1)[1]
    for word in ("홈택스", "로그인", "형식검증", "내용검증", "제출", "위택스", "지방소득세"):
        assert word in todo, word
    assert "규격서 미확인 칸" in text and "형식검증" in text.split("## 규격서 미확인 칸", 1)[1]
    assert "## 확인사항" in text and S1_FILE in text
    assert DASH not in text
    assert not [ln for ln in text.splitlines() if ln.rstrip().endswith("?")]


def test_return_values_file_carries_notice_and_render_notes(tmp_path):
    code, out = _main(tmp_path, "S1", s1_filer())
    assert code == 0
    with open(out / "신고값.json", encoding="utf-8") as fh:
        rv = json.load(fh)
    assert list(rv)[0] == "_주의" and "인적사항" in rv["_주의"]
    assert rv["신고인"]["성명"] == "김합성"                       # 신고값 파일에는 인적사항이 있다
    assert any("세무서" in x for x in rv["확인사항"])              # forms.render 가 덧붙인 문장까지 들어 있다
    text = _confirm(out)
    for note in rv["확인사항"]:
        assert note in text


# ---------------------------------------------------------------- 종료코드 2

def test_fully_exempt_asset_stops_before_forms(tmp_path):
    f = g_filer()
    p, out = _run(tmp_path, "G", f)
    assert p.returncode == 2, p.stdout + p.stderr
    names = set(os.listdir(out))
    assert CALC | GUIDES | {"신고값.json", "신고_확인.md"} <= names
    assert not PDFS & names and not _efiles(out)
    text = _confirm(out)
    assert "전액 비과세" in text and "세무 전문가" in text
    for v in _personal(f):
        assert v not in text and v not in p.stdout


def test_calculation_question_stops_like_run(tmp_path, capsys):
    code, out = _main(tmp_path, "L", filers.get("A"))
    assert code == 2
    names = set(os.listdir(out))
    assert {"result.json", "질문.md", "신고_확인.md"} <= names
    assert not (PDFS | GUIDES | {"신고값.json", "양도소득세_검토.md"}) & names
    assert "질문.md" in _confirm(out)


def test_filer_format_error_is_code_2(tmp_path):
    f = s1_filer()
    f["세무대리인"] = {"성명": "박합성"}
    code, out = _main(tmp_path, "S1", f)
    assert code == 2
    text = _confirm(out)
    assert "세무대리" in text and "박합성" not in text
    assert not (PDFS | {"신고값.json"}) & set(os.listdir(out))


def test_unreadable_inputs_are_code_2(tmp_path):
    fp, gp, out = _write(tmp_path, "S1", s1_filer())
    base = ["--출력", str(out), "--오늘", TODAY]
    assert MR.main(["--사실관계", str(tmp_path / "없음.json"), "--신고인", str(gp)] + base) == 2
    assert "사실관계" in _confirm(out)
    assert MR.main(["--사실관계", str(fp), "--신고인", str(tmp_path / "없음.json")] + base) == 2
    assert "신고인 파일" in _confirm(out)
    personal = tmp_path / "p.json"
    personal.write_text(json.dumps(dict(CASES["S1"], 메모="900101-1234567"), ensure_ascii=False), encoding="utf-8")
    assert MR.main(["--사실관계", str(personal), "--신고인", str(gp)] + base) == 2
    assert "900101-1234567" not in _confirm(out)


def test_unsupported_scope_is_code_2(tmp_path, monkeypatch):
    def out_of_scope(*a, **k):
        raise return_values.Unsupported("확정신고에 같은 해 예정신고분(기신고)을 합산하는 신고는 계획 5 에서 다룬다", "5")

    monkeypatch.setattr(MR.return_values, "build", out_of_scope)
    code, out = _main(tmp_path, "S1", s1_filer())
    assert code == 2
    assert "기신고" in _confirm(out) and "계획 5" in _confirm(out)
    assert not (PDFS | GUIDES | {"신고값.json"}) & set(os.listdir(out))


# ---------------------------------------------------------------- 종료코드 1

def test_forms_check_failure_makes_no_pdf_and_no_file(tmp_path, monkeypatch):
    monkeypatch.setattr(MR.forms_check, "check", lambda *a, **k: ["부표1 ⑱ 합계 155,893,335 ≠ 본지 ④ 155,893,334"])
    code, out = _main(tmp_path, "S1", s1_filer())
    assert code == 1
    names = set(os.listdir(out))
    assert not PDFS & names and not _efiles(out)
    text = _confirm(out)
    assert "부표1 ⑱ 합계 155,893,335 ≠ 본지 ④ 155,893,334" in text
    for g in GUIDES:                                        # 안내서는 나오지만 쓰지 말라는 줄이 맨 위에 붙는다
        with open(out / g, encoding="utf-8") as fh:
            assert "신고_확인.md" in fh.readline()


def test_efile_check_failure_leaves_no_file(tmp_path, monkeypatch):
    def rejected(rv, out_dir, **k):
        return {"경로": None, "검증": ["03 레코드 2번째 줄: 산출세액 합이 합계 행과 다르다"], "파일명": S1_FILE,
                "경고": ["임시 폴더 .efile-x 를 지우지 못했다. 직접 지운다"]}

    monkeypatch.setattr(MR.efile, "write", rejected)
    code, out = _main(tmp_path, "S1", s1_filer())
    assert code == 1
    assert not _efiles(out)
    assert PDFS <= set(os.listdir(out))                     # 서식 검산은 통과했다
    text = _confirm(out)
    assert "03 레코드 2번째 줄: 산출세액 합이 합계 행과 다르다" in text
    assert "임시 폴더 .efile-x 를 지우지 못했다. 직접 지운다" in text


def test_real_efile_check_failure_is_code_1(tmp_path, monkeypatch):
    """검증기를 돌릴 수 없으면(없는 파이썬) efile.write 가 파일을 남기지 않는다. 그 문장이 확인 문서에 온다."""
    real = efile.write
    monkeypatch.setattr(MR.efile, "write", lambda rv, out_dir: real(rv, out_dir, python=str(tmp_path / "없는파이썬")))
    code, out = _main(tmp_path, "S1", s1_filer())
    assert code == 1 and not _efiles(out)
    assert "검증기" in _confirm(out)
    assert not [n for n in os.listdir(out) if n.startswith(".efile-")]


@pytest.mark.parametrize("exc", [forms_pdf.Overflow("양도자산 소재지 합계 칸에 값이 들어가지 않는다(후보 2개)"),
                                 ValueError("부표1 자산종류 코드 9 의 이름이 매핑 「자산종류」 표에 없다")])
def test_render_error_makes_no_pdf_and_no_file(tmp_path, monkeypatch, exc):
    def broken(rv, out_dir, **k):
        raise exc

    monkeypatch.setattr(MR.forms, "render", broken)
    code, out = _main(tmp_path, "S1", s1_filer())
    assert code == 1
    assert not PDFS & set(os.listdir(out)) and not _efiles(out)
    assert str(exc) in _confirm(out)
    assert "신고값.json" in os.listdir(out)                 # render 전의 신고값으로 쓴다


# ---------------------------------------------------------------- 종료코드 3

def test_locked_spec_is_code_3_and_drops_old_file(tmp_path, monkeypatch):
    code, out = _main(tmp_path, "S1", s1_filer())
    assert code == 0 and _efiles(out) == [S1_FILE]
    monkeypatch.setattr(efile, "_spec_locked", lambda efile_dir=None: True)     # 규격판.json 의 잠금이 걸린 것처럼
    code, out = _main(tmp_path, "S1", s1_filer())
    assert code == 3
    names = set(os.listdir(out))
    assert not _efiles(out)                                 # 옛 파일이 새 결과처럼 남지 않는다
    assert PDFS | GUIDES | {"신고값.json"} <= names         # 서식 검산은 통과했으니 신고서와 안내서는 있다
    text = _confirm(out)
    assert "규격판이 잠겨" in text and "운영자" in text
    with open(out / "홈택스_입력안내.md", encoding="utf-8") as fh:
        assert fh.readline().startswith("# ")               # 값은 쓸 수 있으니 「신고하지 않는다」 줄이 붙지 않는다


def test_unreadable_skill_file_is_code_3(tmp_path, monkeypatch):
    def missing(rv, out_dir, **k):
        raise FileNotFoundError(2, "No such file or directory", os.path.join(SKILL, "forms", "매핑", "본지.json"))

    monkeypatch.setattr(MR.forms, "render", missing)
    code, out = _main(tmp_path, "S1", s1_filer())
    assert code == 3
    assert "본지.json" in _confirm(out) and not PDFS & set(os.listdir(out)) and not _efiles(out)


def test_broken_ruleset_is_code_3(tmp_path):
    rules = tmp_path / "rules"
    rules.mkdir()
    code, out = _main(tmp_path, "S1", s1_filer(), extra=["--rules", str(rules)])
    assert code == 3
    assert "기준정보" in _confirm(out)
    assert not (PDFS | CALC | {"신고값.json"}) & set(os.listdir(out))


# ---------------------------------------------------------------- 종료코드 4

def test_output_folder_that_cannot_be_made_is_code_4(tmp_path, capsys):
    blocker = tmp_path / "file.txt"
    blocker.write_text("x", encoding="utf-8")
    fp, gp, _ = _write(tmp_path, "S1", s1_filer())
    code = MR.main(["--사실관계", str(fp), "--신고인", str(gp), "--출력", str(blocker / "out"), "--오늘", TODAY])
    assert code == 4
    assert "쓰지 못했" in capsys.readouterr().err


def test_write_failure_in_the_middle_is_code_4(tmp_path, monkeypatch, capsys):
    fp, gp, out = _write(tmp_path, "S1", s1_filer())

    def locked(rv, out_dir, **k):
        raise PermissionError(13, "Permission denied", os.path.join(out_dir, forms.OUT_NATIONAL))

    monkeypatch.setattr(MR.forms, "render", locked)
    code = MR.main(["--사실관계", str(fp), "--신고인", str(gp), "--출력", str(out), "--오늘", TODAY])
    assert code == 4
    assert forms.OUT_NATIONAL in capsys.readouterr().err
    assert "쓰지 못했다" in _confirm(out)


# ---------------------------------------------------------------- 이전 결과 지우기

def test_rerun_drops_stale_results_and_keeps_other_files(tmp_path):
    code, out = _main(tmp_path, "S1", s1_filer())
    assert code == 0
    keep = {"메모.txt": "내 파일", "20261215A103900.01": "다른 세목 파일", "고객자료.pdf": "pdf"}
    for n, body in keep.items():
        (out / n).write_text(body, encoding="utf-8")
    (out / "20251130C116300.01").write_text("옛 전자신고 파일", encoding="utf-8")
    stale = out / ".efile-old"
    stale.mkdir()
    (stale / "신고값.json").write_text("{}", encoding="utf-8")
    code, out = _main(tmp_path, "S1", filers.get("S1"))     # 이번에는 신고인 질문 F04 로 끝난다
    assert code == 2
    names = set(os.listdir(out))
    assert not (PDFS | GUIDES | {"신고값.json", S1_FILE, "20251130C116300.01", ".efile-old"}) & names
    for n, body in keep.items():
        assert (out / n).read_text(encoding="utf-8") == body
    assert "F04" in _confirm(out)


# ---------------------------------------------------------------- MCP

def _filer_file(tmp_path, filer):
    gp = tmp_path / "g.json"
    gp.write_text(json.dumps(filer, ensure_ascii=False), encoding="utf-8")
    return str(gp)


def test_mcp_forms_stops_at_pdf(tmp_path):
    f = s1_filer()
    out = tmp_path / "o"
    res = mcp_server.call_tool("yangdo_forms", {"facts": CASES["S1"], "filer_path": _filer_file(tmp_path, f),
                                                "out_dir": str(out), "today": TODAY})
    assert res["종료코드"] == 0 and res["상태"] == "완료" and res["전자신고"] is None
    names = set(os.listdir(out))
    assert PDFS | GUIDES | {"신고값.json", "신고_확인.md"} <= names and not _efiles(out)
    s = json.dumps(res, ensure_ascii=False)
    for v in _personal(f):
        assert v not in s
    assert "성수동" not in s                                # 부표1 소재지도 응답에 옮기지 않는다


def test_mcp_efile_reports_questions_without_values(tmp_path):
    f = filers.get("S1")
    res = mcp_server.call_tool("yangdo_efile", {"facts": CASES["S1"], "filer_path": _filer_file(tmp_path, f),
                                                "out_dir": str(tmp_path / "o"), "today": TODAY})
    assert res["종료코드"] == 2 and res["상태"] == "질문"
    assert [q["문항"] for q in res["신고인질문"]] == ["F04"]
    s = json.dumps(res, ensure_ascii=False)
    for v in _personal(f):
        assert v not in s


def test_mcp_return_tools_check_arguments(tmp_path):
    gp = _filer_file(tmp_path, s1_filer())
    base = {"facts": CASES["S1"], "filer_path": gp, "out_dir": str(tmp_path / "o"), "today": TODAY}
    for name in ("yangdo_forms", "yangdo_efile"):
        for missing in ("filer_path", "out_dir"):
            args = {k: v for k, v in base.items() if k != missing}
            with pytest.raises(mcp_server.ToolError, match=missing):
                mcp_server.call_tool(name, args)
        with pytest.raises(mcp_server.ToolError, match="today"):
            mcp_server.call_tool(name, dict(base, today="20261011"))
        with pytest.raises(mcp_server.ToolError, match="facts"):
            mcp_server.call_tool(name, {k: v for k, v in base.items() if k != "facts"})
    assert not os.path.exists(tmp_path / "o")               # 인자가 틀리면 출력 폴더를 건드리지 않는다
    with_person = dict(base, facts=dict(copy.deepcopy(CASES["S1"]), 메모="900101-1234567"))
    r = mcp_server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                           "params": {"name": "yangdo_efile", "arguments": with_person}})
    assert r["result"].get("isError") is True and "900101-1234567" not in r["result"]["content"][0]["text"]


def test_mcp_write_failure_is_a_tool_error(tmp_path):
    blocker = tmp_path / "file.txt"
    blocker.write_text("x", encoding="utf-8")
    r = mcp_server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                           "params": {"name": "yangdo_efile",
                                      "arguments": {"facts": CASES["S1"], "filer_path": _filer_file(tmp_path, s1_filer()),
                                                    "out_dir": str(blocker / "out")}}})
    assert r["result"].get("isError") is True and "쓰지 못했다" in r["result"]["content"][0]["text"]


# ---------------------------------------------------------------- 문체

def test_source_style_rules():
    with open(SCRIPT, encoding="utf-8") as fh:
        src = fh.read()
    assert src.startswith("# -*- coding: utf-8 -*-") and DASH not in src
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert "?" not in node.value, node.value


# ---------------------------------------------------------------- 검토 반영 1차

def _lock(monkeypatch, *names):
    """이름이 names 인 파일은 지워지지 않게 한다(다른 프로그램이 열어 둔 것처럼)."""
    real = os.remove

    def remove(path, *a, **k):
        if os.path.basename(os.fspath(path)) in names:
            raise PermissionError(13, "Permission denied", os.fspath(path))
        return real(path, *a, **k)

    monkeypatch.setattr(os, "remove", remove)


def test_rerun_with_locked_workbook_leaves_no_submittable_file(tmp_path, monkeypatch, capsys):
    code, out = _main(tmp_path, "S1", s1_filer())
    assert code == 0 and _efiles(out) == [S1_FILE]
    _lock(monkeypatch, "양도소득세_계산근거.xlsx")             # 엑셀이 계산근거를 열어 둔 채 다시 실행
    code, out = _main(tmp_path, "S1", s1_filer())
    assert code == 4
    names = set(os.listdir(out))
    assert _efiles(out) == []                                  # 옛 전자신고 파일이 제출용 이름으로 남지 않는다
    assert not (PDFS | GUIDES | {"신고값.json"}) & names
    assert "양도소득세_계산근거.xlsx" in names
    text = _confirm(out)
    assert "양도소득세_계산근거.xlsx" in text and "이전 실행" in text
    assert "양도소득세_계산근거.xlsx" in capsys.readouterr().err


def test_rerun_with_locked_pdf_leaves_no_submittable_file(tmp_path, monkeypatch):
    code, out = _main(tmp_path, "S1", s1_filer())
    assert code == 0
    (out / ".efile-old").mkdir()
    _lock(monkeypatch, "양도소득세_신고서.pdf")                 # PDF 보기 프로그램이 국세 신고서를 열어 둔 채 다시 실행
    code, out = _main(tmp_path, "S1", s1_filer())
    assert code == 4
    names = set(os.listdir(out))
    assert _efiles(out) == []
    assert not (GUIDES | CALC | {"신고값.json", "지방소득세_신고서.pdf", ".efile-old"}) & names   # 막힌 파일 말고는 끝까지 지운다
    assert "양도소득세_신고서.pdf" in names
    text = _confirm(out)
    assert "양도소득세_신고서.pdf" in text and "이전 실행" in text


def test_unexpected_error_still_writes_confirm_and_drops_submittable_files(tmp_path, monkeypatch, capsys):
    def boom(rv):
        raise KeyError("김합성 비밀")                           # 예외 문장에는 인적사항이 실릴 수 있다

    monkeypatch.setattr(MR.guide, "hometax_input", boom)
    code, out = _main(tmp_path, "S1", s1_filer())
    shown = capsys.readouterr()
    assert code == 1
    names = set(os.listdir(out))
    assert "신고_확인.md" in names
    assert _efiles(out) == [] and not PDFS & names             # 확인 문서 없이 제출용 파일만 남지 않게 지운다
    assert not [n for n in names if n.startswith(".efile-")]
    text = _confirm(out)
    assert "KeyError" in text and "예상하지 못한" in text
    assert "김합성" not in text and "김합성" not in shown.out
    assert "Traceback" in shown.err
    made = text.split("## 만든 파일", 1)[1].split("## 사람이 할 일")[0]
    assert S1_FILE not in made and "신고서.pdf" not in made


def test_unexpected_error_in_render_is_reported_too(tmp_path, monkeypatch, capsys):
    def boom(rv, out_dir, **k):
        raise RuntimeError("code=2: cannot open document")     # pymupdf 가 내는 꼴

    monkeypatch.setattr(MR.forms, "render", boom)
    res = MR.make(CASES["S1"], s1_filer(), str(tmp_path / "o"), today=TODAY)
    assert res["종료코드"] == 1 and any("RuntimeError" in x for x in res["알림"])
    assert not any("cannot open" in x for x in res["알림"])
    assert "신고_확인.md" in os.listdir(tmp_path / "o")
    assert "Traceback" in capsys.readouterr().err


def _first_line(out, name):
    with open(os.path.join(str(out), name), encoding="utf-8") as fh:
        return fh.readline()


def test_guide_head_says_what_really_happened(tmp_path, monkeypatch):
    def rejected(rv, out_dir, **k):
        return {"경로": None, "검증": ["03 레코드: 합계가 다르다"], "파일명": S1_FILE, "경고": []}

    monkeypatch.setattr(MR.efile, "write", rejected)
    code, out = _main(tmp_path, "S1", s1_filer())
    assert code == 1 and PDFS <= set(os.listdir(out))
    for g in GUIDES:
        head = _first_line(out, g)
        assert "전자신고 검증" in head and "신고_확인.md" in head and "신고하지 않는다" in head
        assert "신고서를 만들지 못" not in head                 # 신고서 PDF 는 만들었다


def test_guide_head_for_fully_exempt_asset(tmp_path):
    code, out = _main(tmp_path, "G", g_filer())
    assert code == 2
    for g in GUIDES:
        head = _first_line(out, g)
        assert "전액 비과세" in head and "참고용" in head


@pytest.mark.parametrize("exc,want", [
    (efile.BuildError("신고.작성일(YYYYMMDD)과 신고.상세코드(2자리)로 파일명을 만들 수 없다"), "파일명을 만들 수 없다"),
    (KeyError("신고값 전자신고 05 행에 없는 키: 과세구분"), "신고값 전자신고 05 행에 없는 키: 과세구분"),
])
def test_efile_build_errors_are_code_1(tmp_path, monkeypatch, exc, want):
    def broken(rv, out_dir, **k):
        raise exc

    monkeypatch.setattr(MR.efile, "write", broken)
    code, out = _main(tmp_path, "S1", s1_filer())
    assert code == 1 and _efiles(out) == []
    assert PDFS <= set(os.listdir(out))
    text = _confirm(out)
    section = text.split("## 전자신고 검증", 1)[1].split("##")[0]
    assert "전자신고 레코드를 만들지 못했다. " in section and want in section
    assert "통과" not in section and "'" not in section


def test_no_path_and_no_sentence_is_not_a_pass(tmp_path, monkeypatch):
    monkeypatch.setattr(MR.efile, "write", lambda rv, out_dir, **k: {"경로": None, "검증": [], "파일명": S1_FILE, "경고": []})
    code, out = _main(tmp_path, "S1", s1_filer())
    assert code == 1 and _efiles(out) == []
    text = _confirm(out)
    section = text.split("## 전자신고 검증", 1)[1].split("##")[0]
    assert "통과" not in section and "파일을 만들지 못했다" in section
    assert "규격서 미확인 칸" not in text


# ---------------------------------------------------------------- 확정신고(가산세를 계산하지 않아 신고서·파일을 만들지 않는다)

PENALTY_WORDS = ("확정신고", "무신고가산세", "납부지연가산세", "가산세를 계산하지 않", "실제보다 적게")


def test_final_return_makes_no_forms_and_no_file(tmp_path, capsys):
    f = filers.get("BF")
    code, out = _main(tmp_path, "BF", f)
    shown = capsys.readouterr()
    assert code == 2, shown.out + shown.err
    names = set(os.listdir(out))
    assert CALC | GUIDES | {"신고값.json", "신고_확인.md"} <= names
    assert not PDFS & names and _efiles(out) == []
    assert not [n for n in names if n.startswith(".efile-") or n.endswith(".tmp")]
    text = _confirm(out)
    for word in PENALTY_WORDS:
        assert word in text, word
    assert "신고서와 전자신고 파일을 만들지 않았다" in text
    assert "제1" not in text.split("## 알림", 1)[1].split("##")[0]       # 조문 번호는 적지 않는다
    assert "| 서식 검산 | 통과 |" in text and "만들지 않음(확정신고 가산세)" in text
    assert "전액 비과세" not in text
    assert "가산세" in shown.out
    for v in _personal(f):
        assert v not in text and v not in shown.out
    for g in GUIDES:
        head = _first_line(out, g)
        assert "확정신고" in head and "가산세" in head and "참고용" in head and "전액 비과세" not in head
    with open(out / "신고값.json", encoding="utf-8") as fh:
        assert json.load(fh)["신고"]["구분"] == "확정"


def test_final_return_with_fully_exempt_asset_gives_both_reasons(tmp_path):
    f = g_filer()
    f["신고"].update(구분="확정", 작성일="2027-05-20")
    code, out = _main(tmp_path, "G", f)
    assert code == 2
    names = set(os.listdir(out))
    assert GUIDES | {"신고값.json"} <= names and not PDFS & names and _efiles(out) == []
    text = _confirm(out)
    notes = text.split("## 알림", 1)[1].split("##")[0]
    assert "전액 비과세 자산(G)" in notes and "무신고가산세" in notes and "납부지연가산세" in notes
    assert "전액 비과세" in text.splitlines()[2] and "확정신고" in text.splitlines()[2]      # 요약 줄에도 두 사유
    for g in GUIDES:
        head = _first_line(out, g)
        assert "전액 비과세" in head and "확정신고" in head and "가산세" in head and "참고용" in head


@pytest.mark.parametrize("tool", ["yangdo_forms", "yangdo_efile"])
def test_mcp_final_return_gives_the_same_result(tmp_path, tool):
    f = filers.get("BF")
    out = tmp_path / "o"
    res = mcp_server.call_tool(tool, {"facts": CASES["BF"], "filer_path": _filer_file(tmp_path, f), "out_dir": str(out),
                                      "today": TODAY})
    assert res["종료코드"] == 2 and res["상태"] == "다루지않음" and res["전자신고"] is None
    notes = " ".join(res["알림"])
    for word in PENALTY_WORDS:
        assert word in notes, word
    assert "가산세" in res["요약"] and res["서식검산"] == []
    assert any("가산세" in x["내용"] for x in res["다루지않음"])
    made = {os.path.basename(x) for x in res["파일"]}
    assert GUIDES | {"신고값.json", "신고_확인.md"} <= made and not PDFS & made and not [n for n in made if "C116300" in n]
    names = set(os.listdir(out))
    assert not PDFS & names and _efiles(out) == []
    s = json.dumps(res, ensure_ascii=False)
    for v in _personal(f):
        assert v not in s


def test_withheld_reasons_are_collected_in_one_place():
    """신고서·파일을 만들지 않는 사유는 한 함수가 모은다. 예정신고의 과세 자산은 사유가 없다."""
    def rv(kind):
        return {"신고": {"구분": kind}}

    def res(*exempt):
        return {"계산": {"자산": [{"id": a, "판정": {"전액비과세": x}} for a, x in exempt]}}

    assert MR.withheld(rv("예정"), res(("A", False))) == []
    assert [w["이름"] for w in MR.withheld(rv("예정"), res(("A", False), ("G", True)))] == ["전액 비과세 자산"]
    assert [w["이름"] for w in MR.withheld(rv("확정"), res(("A", False)))] == ["확정신고 가산세"]
    both = MR.withheld(rv("확정"), res(("G", True)))
    assert [w["이름"] for w in both] == ["전액 비과세 자산", "확정신고 가산세"]
    for w in both:
        assert set(w) == {"이름", "까닭", "알림", "안내", "다루지않음"}
