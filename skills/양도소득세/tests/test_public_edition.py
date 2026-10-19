# -*- coding: utf-8 -*-
"""출력 계약(yangdo/edition.py 의 PUBLIC 이 참). 시험은 PUBLIC 을 참으로 두고 돈다(public 고정물, 명령줄은 _cli).

  계산(run.py, yangdo_calculate)은 출력 폴더에 양도소득세_계산근거.xlsx 만 남긴다.
  신고서(make_return.py, yangdo_forms)는 양도소득세_신고서.pdf, 지방소득세_신고서.pdf, 양도소득세_계산근거.xlsx 만 남긴다.
  실패해도 그 밖의 파일(결과 JSON, 질문·검토·확인 문서, 신고값 JSON, 전자신고 파일, 안내서, 임시 폴더)이 남지 않는다.
  상태·합계·확인사항·경고·질문·다루지않음·사람이 할 일은 화면 출력과 MCP 응답으로 나가고 인적사항은 싣지 않는다.
  사람이 할 일에 전자신고 파일·입력 안내서·부속서류 이야기가 없다. 전자신고 도구와 전자신고·안내서 모듈이 없다.
"""
import json
import os
import subprocess
import sys

import pytest

import filers
import make_return as MR
import mcp_server
import run
from cases import CASES
from yangdo import edition, filing, forms, forms_check, outputs, return_values

SKILL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(os.path.dirname(SKILL))
PUBLIC_TREE = edition.PUBLIC            # 읽을 때부터 PUBLIC 이 참인 트리에서 도는지
TODAY = "2026-10-11"
CALC_ONLY = set(edition.PUBLIC_CALC_OUTPUTS)
RETURN_FILES = set(edition.PUBLIC_RETURN_OUTPUTS)
WORKBOOK = edition.WORKBOOK
# 출력(화면, 응답, 사람이 할 일)에 나오면 안 되는 말. 전자신고 파일과, 쓰지 않는 파일·도구의 이름이다.
# 모듈·도구 이름은 조각을 이어 만든다. 소스 검사가 이 목록 자체를 그 이름으로 읽지 않게 하려는 것이다
_E = "e" "file"
EFILE_TOOL = "yangdo_" + _E
BANNED = ("전자신고 파일", "변환파일", "C116300", "홈택스_입력안내", "입력 안내서", "부속서류", "신고_확인.md", "신고값.json",
          "result.json", "질문.md", "양도소득세_검토.md", EFILE_TOOL, "형식검증")
# 이 도구가 예전에 같은 폴더에 남겼을 수 있는 파일 이름. 다시 돌 때 지운다
LEGACY = ("result.json", "질문.md", "양도소득세_검토.md", "신고값.json", "신고_확인.md", "홈택스_입력안내.md", "부속서류.md",
          "20261220C116300.01")
# 읽혀서는 안 되는 전자신고·안내서 모듈
_UNUSED = (_E, _E + "_check", _E + "_tmp", "gui" "de")
UNUSED_MODULES = tuple("yangdo." + n for n in _UNUSED)
REMOVED_PATHS = tuple("yangdo/%s.py" % n for n in _UNUSED) + (
    "efile/layout_" "c116300.json", "efile/규격판" ".json", "references/전자신고" ".md", "references/기준정보_" "초판절차.md")
CASE_TODAY = {"A": TODAY, "K": "2026-08-20", "BF": TODAY, "S1": TODAY}
MARK = "@@불러온모듈@@"


@pytest.fixture
def public(monkeypatch):
    """PUBLIC 을 참으로 두고 돈다."""
    monkeypatch.setattr(edition, "PUBLIC", True)


def _filer(name):
    f = filers.get(name)
    if name == "S1":
        f["자산"]["S1"]["법정동코드"] = "1120011400"      # 성수동은 법정동코드가 둘이라 직접 적는다
    return f


def _personal(filer):
    """화면·응답에 나오면 안 되는 값. 주소는 다른 글에 섞여 나올 수 없는 읍면동과 아파트 이름으로 본다."""
    p = filer["신고인"]
    vals = [p["성명"], p["주민등록번호"], p["전화"], filer["신고"]["홈택스ID"]]
    vals += [p["주소"][k] for k in ("읍면동", "아파트명") if p["주소"].get(k)]
    vals += [b[k] for b in filer["양수인"] for k in ("성명", "번호")]
    vals += [lot[k] for lot in filer["자산"].values() for k in ("취득상대방", "아파트명") if lot.get(k)]
    return [v for v in vals if v]


def _inputs(tmp_path, name, filer=None, facts=None):
    fp, gp = tmp_path / "f.json", tmp_path / "g.json"
    fp.write_text(json.dumps(CASES[name] if facts is None else facts, ensure_ascii=False), encoding="utf-8")
    gp.write_text(json.dumps(_filer(name) if filer is None else filer, ensure_ascii=False), encoding="utf-8")
    return fp, gp


def _cli(script, args, cwd=SKILL):
    """scripts/<script> 를 PUBLIC 을 참으로 두고 별도 프로세스에서 돌린다. (종료코드, 표준출력, 표준오류, 읽힌 전자신고·안내서 모듈).

    edition.PUBLIC 을 참으로 바꾼 뒤 스크립트를 읽으므로 전자신고·안내서 모듈을 읽으면 안 된다."""
    path = script if os.path.isabs(script) else os.path.join(SKILL, script)
    code = ("import sys, runpy\n"
            "sys.path.insert(0, %r)\n"
            "from yangdo import edition\n"
            "edition.PUBLIC = True\n"
            "sys.argv = [%r] + sys.argv[1:]\n"
            "try:\n"
            "    runpy.run_path(%r, run_name='__main__')\n"
            "finally:\n"
            "    print(%r + ','.join(m for m in %r if m in sys.modules), file=sys.stderr)\n"
            % (SKILL, path, path, MARK, UNUSED_MODULES))
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    env.pop("PYTHONPATH", None)
    p = subprocess.run([sys.executable, "-c", code] + [str(a) for a in args], cwd=cwd, capture_output=True, text=True,
                       encoding="utf-8", env=env, timeout=300)
    err, _, loaded = p.stderr.rpartition(MARK)
    return p.returncode, p.stdout, err, [m for m in loaded.strip().split(",") if m]


def _no_banned(text, where):
    for w in BANNED:
        assert w not in text, (where, w)


# ---------------------------------------------------------------- 계산

def test_run_leaves_only_the_workbook_and_prints_the_result(tmp_path):
    fp, _ = _inputs(tmp_path, "A")
    out = tmp_path / "out"
    code, so, se, loaded = _cli("scripts/run.py", ["--사실관계", fp, "--출력", out, "--오늘", TODAY])
    assert code == 0, so + se
    assert set(os.listdir(out)) == CALC_ONLY
    assert "산출세액 2,565,000원, 지방소득세 256,500원, 검산 통과" in so and "자산 A(주택" in so and WORKBOOK in so
    assert outputs.TAIL in so and loaded == []
    _no_banned(so, "run.py 화면")


def test_run_question_writes_no_file_and_prints_the_questions(tmp_path, public, capsys):
    facts = json.loads(json.dumps(CASES["A"]))
    facts["자산"][0].pop("양도")
    fp, _ = _inputs(tmp_path, "A", facts=facts)
    out = tmp_path / "out"
    assert run.main(["--사실관계", str(fp), "--출력", str(out), "--오늘", TODAY]) == 2
    shown = capsys.readouterr().out
    assert os.listdir(out) == []
    assert "계산 질문 1개, 이 스킬이 다루지 않는 경우 0개" in shown and "- [P03] 자산 A:" in shown
    _no_banned(shown, "질문 화면")


def test_run_clears_this_tools_old_files_and_keeps_other_files(tmp_path, public, capsys):
    fp, _ = _inputs(tmp_path, "A")
    out = tmp_path / "out"
    out.mkdir()
    for n in LEGACY + ("메모.txt",):
        (out / n).write_text("옛 파일", encoding="utf-8")
    assert run.main(["--사실관계", str(fp), "--출력", str(out), "--오늘", TODAY]) == 0
    assert set(os.listdir(out)) == CALC_ONLY | {"메모.txt"}


def test_calculate_to_writes_only_the_workbook(tmp_path, public):
    res, files = outputs.calculate_to(CASES["A"], str(tmp_path / "o"), today=TODAY)
    assert res["상태"] == "완료" and [os.path.basename(p) for p in files] == [WORKBOOK]
    assert set(os.listdir(tmp_path / "o")) == CALC_ONLY
    text = outputs.report_text(res)
    assert "기준정보 판" in text and "산출세액 2,565,000원" in text


# ---------------------------------------------------------------- 신고서

def test_make_return_leaves_exactly_three_files(tmp_path):
    fp, gp = _inputs(tmp_path, "A")
    out = tmp_path / "out"
    code, so, se, loaded = _cli("scripts/make_return.py", ["--사실관계", fp, "--신고인", gp, "--출력", out, "--오늘", "2026-12-20"])
    assert code == 0, so + se
    assert set(os.listdir(out)) == RETURN_FILES
    assert loaded == [], "전자신고·안내서 모듈을 읽었다: %s" % loaded
    assert so.startswith("# 양도소득세 신고 확인") and "신고서 PDF 두 벌" in so and "(종료코드 0)" in so
    for head in ("## 단계", "## 서식 검산", "## 만든 파일", "## 사람이 할 일"):
        assert head in so, head
    assert "산출세액 2,565,000원, 지방소득세 256,500원" in so and "신고서 PDF 에는 인적사항이 들어 있다" in so
    _no_banned(so, "make_return 화면")
    for v in _personal(_filer("A")):
        assert v not in so and v not in se, v


@pytest.mark.parametrize("name", ["A", "K", "BF", "S1"])
def test_every_synthetic_case_leaves_three_files_and_a_todo_without_efile_steps(tmp_path, public, name):
    fp, gp = _inputs(tmp_path, name)
    out = tmp_path / "out"
    rep = MR.make(str(fp), str(gp), str(out), today=CASE_TODAY[name])
    assert rep["종료코드"] == 0, (rep["요약"], rep["알림"], rep["서식검산"], rep["신고인질문"])
    assert set(os.listdir(out)) == RETURN_FILES
    assert tuple(rep["단계"]) == MR.PUBLIC_STEPS and rep["전자신고"] is None and rep["범위"] == MR.FORMS
    assert {os.path.basename(p) for p in rep["파일"]} == RETURN_FILES
    todo = " ".join(rep["사람이할일"])
    _no_banned(todo, "사람이 할 일")
    assert MR.PUBLIC_FILE in rep["사람이할일"] and "위택스에서 지방소득세" in todo
    if name == "BF":        # 가산세가 있는 확정신고
        assert "기한 후 신고로 내는 방법과 비교한다" in todo and "작성일 2027-05-20 에 납부한다" in todo
    assert not [x for x in rep["확인사항"] if return_values.is_file_only_note(x)]
    text = MR.confirm_md(rep)
    _no_banned(text, "화면 글")
    for v in _personal(_filer(name)):
        assert v not in text and v not in json.dumps(rep, ensure_ascii=False), v


def test_mixed_return_leaves_out_the_exempt_asset_and_says_what_to_keep(tmp_path, public):
    from test_exempt_excluded import gf_facts, mixed_filer
    fp, gp = _inputs(tmp_path, "A", filer=mixed_filer(), facts=gf_facts())
    out = tmp_path / "out"
    rep = MR.make(str(fp), str(gp), str(out), today=TODAY)
    assert rep["종료코드"] == 0, (rep["요약"], rep["알림"], rep["신고인질문"])
    assert set(os.listdir(out)) == RETURN_FILES and rep["제외자산"] == ["G"]
    assert any("전액 비과세로 판정한 자산(G)" in x for x in rep["알림"])
    keep = [x for x in rep["사람이할일"] if "넣지 않은 자산(G)" in x]
    assert len(keep) == 1 and "비과세 요건" in keep[0] and "증빙" in keep[0]
    _no_banned(" ".join(rep["사람이할일"]), "사람이 할 일")


@pytest.mark.parametrize("kind,made", [("예정", "2026-12-20"), ("확정", "2027-05-20")])
def test_only_exempt_assets_leave_only_the_workbook(tmp_path, public, kind, made):
    from test_exempt_excluded import g_only_filer
    fp, gp = _inputs(tmp_path, "G", filer=g_only_filer(kind, made), facts=CASES["G"])
    out = tmp_path / "out"
    rep = MR.make(str(fp), str(gp), str(out), today=TODAY)
    assert rep["종료코드"] == 2 and rep["과세자산없음"] is True
    assert set(os.listdir(out)) == CALC_ONLY
    assert rep["요약"] == return_values.NO_TAXABLE and "만들지 않음(과세 자산 없음)" in rep["단계"]["신고값"]
    todo = " ".join(rep["사람이할일"])
    assert "과세 자산이 없어 신고서를 만들지 않았다" in todo
    _no_banned(todo + " ".join(rep["알림"]), "과세 자산 없음")


def test_make_return_rerun_clears_old_files_of_this_tool(tmp_path, public):
    fp, gp = _inputs(tmp_path, "A")
    out = tmp_path / "out"
    out.mkdir()
    for n in LEGACY + ("메모.txt",):
        (out / n).write_text("옛 파일", encoding="utf-8")
    rep = MR.make(str(fp), str(gp), str(out), today="2026-12-20")
    assert rep["종료코드"] == 0
    assert set(os.listdir(out)) == RETURN_FILES | {"메모.txt"}


def test_calculation_question_is_printed_inline_and_leaves_no_file(tmp_path, public, capsys):
    facts = json.loads(json.dumps(CASES["A"]))
    facts["자산"][0].pop("양도")
    fp, gp = _inputs(tmp_path, "A", facts=facts)
    out = tmp_path / "out"
    assert MR.main(["--사실관계", str(fp), "--신고인", str(gp), "--출력", str(out), "--오늘", "2026-12-20"]) == 2
    shown = capsys.readouterr().out
    assert os.listdir(out) == []
    assert "## 계산 질문" in shown and "- [P03] 자산 A:" in shown and "다시 실행한다" in shown
    _no_banned(shown, "계산 질문 화면")


def test_filer_questions_are_in_the_output_and_the_hometax_id_is_not_asked(tmp_path, public, capsys):
    f = _filer("A")
    f["신고인"]["성명"] = ""
    f["신고"]["홈택스ID"] = ""
    fp, gp = _inputs(tmp_path, "A", filer=f)
    out = tmp_path / "out"
    assert MR.main(["--사실관계", str(fp), "--신고인", str(gp), "--출력", str(out), "--오늘", "2026-12-20"]) == 2
    shown = capsys.readouterr().out
    assert set(os.listdir(out)) == CALC_ONLY          # 계산은 끝났고 신고서는 만들지 않았다
    assert "## 신고인 정보 질문" in shown and "- [F01]" in shown and "[F06]" not in shown
    loaded = filing.load(f)
    assert "F06" not in {q["문항"] for q in filing.questions(loaded, CASES["A"])}


def test_forms_check_failure_leaves_only_the_workbook(tmp_path, public, monkeypatch):
    monkeypatch.setattr(MR.forms_check, "check", lambda *a, **k: ["시험이 만든 실패"])
    fp, gp = _inputs(tmp_path, "A")
    out = tmp_path / "out"
    rep = MR.make(str(fp), str(gp), str(out), today="2026-12-20")
    assert rep["종료코드"] == 1 and rep["서식검산"] == ["시험이 만든 실패"]
    assert set(os.listdir(out)) == CALC_ONLY
    assert rep["요약"] == "서식 검산 실패 1건. 신고서를 만들지 않았다"
    _no_banned(" ".join(rep["사람이할일"]), "사람이 할 일")


def test_unexpected_error_after_the_pdfs_removes_them(tmp_path, public, monkeypatch, capsys):
    real = MR.forms.render

    def render_then_fail(rv, out_dir, *a, **k):
        real(rv, out_dir, *a, **k)
        raise RuntimeError("시험이 만든 오류")

    monkeypatch.setattr(MR.forms, "render", render_then_fail)
    fp, gp = _inputs(tmp_path, "A")
    out = tmp_path / "out"
    rep = MR.make(str(fp), str(gp), str(out), today="2026-12-20")
    capsys.readouterr()
    assert rep["종료코드"] == 1 and rep["상태"] == "오류"
    assert set(os.listdir(out)) == CALC_ONLY
    assert any("신고서 PDF 는 지웠다" in x for x in rep["알림"])
    assert rep["단계"]["신고서 PDF"] != "만듦"


def test_efile_scope_is_refused(tmp_path, public):
    with pytest.raises(ValueError):
        MR.make(CASES["A"], _filer("A"), str(tmp_path / "o"), upto=MR.EFILE)
    assert not os.path.exists(tmp_path / "o")


def test_return_values_have_no_efile_section_and_pass_the_forms_check(public):
    from yangdo import engine
    res = engine.calculate(CASES["A"], today=TODAY)
    rv = return_values.build(res, CASES["A"], filing.load(_filer("A")))
    assert "전자신고" not in rv and "규격" not in rv["판"]
    assert forms_check.check(rv, res, facts=CASES["A"]) == []


def test_shortened_cell_note_points_to_the_input_files(public):
    note = forms.shortened_note({"이름": "별지84 본지 ② 양도자산 소재지", "형식": "주소"})
    assert "사실관계와 신고인 파일에 있다" in note and "전자신고" not in note and "신고값" not in note
    assert "사실관계와 신고인 파일에 있다" in forms.shortened_note({"이름": "X", "형식": "글"})


# ---------------------------------------------------------------- MCP

def _rpc(method, params=None, rid=1):
    return mcp_server.handle({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}})


def test_mcp_lists_no_efile_tool_and_says_nothing_about_it(public):
    ins = _rpc("initialize")["result"]["instructions"]
    assert "yangdo_forms" in ins and EFILE_TOOL not in ins and "신고_확인" not in ins
    names = {t["name"] for t in _rpc("tools/list")["result"]["tools"]}
    assert EFILE_TOOL not in names and {"yangdo_calculate", "yangdo_forms"} <= names
    for t in _rpc("tools/list")["result"]["tools"]:
        _no_banned(t["description"], t["name"])
    err = _rpc("tools/call", {"name": EFILE_TOOL, "arguments": {}})
    assert err["error"]["code"] == -32602
    with pytest.raises(mcp_server.ToolError):
        mcp_server.call_tool(EFILE_TOOL, {})


def test_mcp_forms_response_carries_the_report_and_the_folder_has_three_files(tmp_path, public):
    _, gp = _inputs(tmp_path, "A")
    out = tmp_path / "o"
    res = mcp_server.call_tool("yangdo_forms", {"facts": CASES["A"], "filer_path": str(gp), "out_dir": str(out),
                                                "today": "2026-12-20"})
    assert tuple(res) == mcp_server.PUBLIC_RETURN_KEYS and "전자신고" not in res
    assert res["상태"] == "완료" and res["종료코드"] == 0 and res["사람이할일"]
    for key in ("확인사항", "경고", "질문", "다루지않음", "알림", "합계", "단계"):
        assert key in res, key
    assert set(os.listdir(out)) == RETURN_FILES
    s = json.dumps(res, ensure_ascii=False)
    for v in _personal(_filer("A")):
        assert v not in s, v
    _no_banned(" ".join(res["사람이할일"]), "MCP 사람이할일")


def test_mcp_calculate_with_out_dir_writes_only_the_workbook(tmp_path, public):
    out = tmp_path / "o"
    res = mcp_server.call_tool("yangdo_calculate", {"facts": CASES["A"], "out_dir": str(out), "today": TODAY})
    assert [os.path.basename(p) for p in res["파일"]] == [WORKBOOK]
    assert set(os.listdir(out)) == CALC_ONLY
    assert res["상태"] == "완료" and "확인사항" in res and "경고" in res and "알림" not in res


# ---------------------------------------------------------------- 저장소와 CI

def _replaced(rel, text):
    """저장소 파일 rel 의 글. PUBLIC 이 참인 트리에서는 그대로 돌려준다."""
    return text


def _public_workflow():
    """CI 작업 파일의 글. 파일이 없으면 None(스킬 폴더만 있는 경우)."""
    wf = os.path.join(REPO, ".github", "workflows", "test.yml")
    if not os.path.exists(wf):
        return None
    with open(wf, encoding="utf-8") as fh:
        return _replaced(".github/workflows/test.yml", fh.read().replace("\r\n", "\n"))


def _skill_commands(text):
    lines = text.splitlines()
    return [lines[i + 1].strip()[len("run: "):] for i, ln in enumerate(lines)
            if ln.strip() == "if: matrix.skill == '양도소득세'" and i + 1 < len(lines) and lines[i + 1].strip().startswith("run: ")]


def test_public_ci_makes_the_return_and_checks_three_files(tmp_path):
    text = _public_workflow()
    if text is None:
        pytest.skip("저장소의 CI 작업 파일이 없다")
    cmds = _skill_commands(text)
    assert len(cmds) == 3, cmds
    assert "tests/sample_inputs.py A" in cmds[0] and "scripts/make_return.py" in cmds[1] and "tests/check_outputs.py" in cmds[2]
    assert "efile" not in text and "C116300" not in text
    for cmd in cmds:
        words = cmd.split()
        assert words[0] == "python"
        args = [str(tmp_path / w) if w.startswith(("ci_sample", "ci_out")) else w for w in words[2:]]
        code, so, se, loaded = _cli(words[1], args)
        assert code == 0 and loaded == [], cmd + "\n" + so + se
    assert set(os.listdir(tmp_path / "ci_out")) == RETURN_FILES


def test_check_outputs_script_wants_exactly_the_three_files(tmp_path):
    import check_outputs
    d = tmp_path / "o"
    d.mkdir()
    for n in RETURN_FILES:
        (d / n).write_bytes(b"x")
    assert check_outputs.main([str(d), "신고서"]) == 0
    (d / "신고값.json").write_text("{}", encoding="utf-8")
    assert check_outputs.main([str(d), "신고서"]) == 1
    assert check_outputs.main([str(d), "없는종류"]) == 2


def test_removed_files_are_absent_in_the_public_tree_or_listed_for_removal():
    left = [p for p in REMOVED_PATHS if os.path.exists(os.path.join(SKILL, p))]
    assert left == [], left


def test_public_skill_and_readme_describe_three_outputs_without_efile_steps():
    """SKILL.md 와 저장소 README 양도소득세 절이 출력 파일 셋을 말하고 전자신고 절차를 말하지 않는다."""
    skill_path = os.path.join(SKILL, "SKILL.md")
    with open(skill_path, encoding="utf-8") as fh:
        skill = fh.read()
    for n in RETURN_FILES:
        assert n in skill, n
    for w in BANNED:
        assert w not in skill, w
    readme = os.path.join(REPO, "README.md")
    if not os.path.exists(readme):
        return
    with open(readme, encoding="utf-8") as fh:
        text = _replaced("README.md", fh.read().replace("\r\n", "\n"))
    if text is None:
        return
    section = text.split("## 양도소득세", 1)[1].split("\n## ", 1)[0]
    for w in ("전자신고 파일", "변환파일", "홈택스_입력안내", "부속서류", "신고_확인.md", "references/전자신고" ".md"):
        assert w not in section, w
    assert all(n in section for n in RETURN_FILES)
