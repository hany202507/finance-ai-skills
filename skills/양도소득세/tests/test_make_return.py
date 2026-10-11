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


def _main(tmp_path, name, filer, extra=(), today=TODAY):
    """같은 프로세스에서 main 을 부른다. (종료코드, 출력 폴더). 오늘은 늘 준다(작성일이 오늘보다 앞서면 멈추므로
    시험이 실행하는 날의 달력에 기대지 않게 한다)."""
    fp, gp, out = _write(tmp_path, name, filer)
    code = MR.main(["--사실관계", str(fp), "--신고인", str(gp), "--출력", str(out), "--오늘", today] + list(extra))
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

# 확정신고(BF)는 가산세를 넣어 신고서와 전자신고 파일까지 만든다. 자세한 값은 아래 「확정신고」 시험이 본다
# K 의 작성일은 2026-08-20 이라 오늘을 그 날로 준다(작성일이 오늘보다 앞서면 멈춘다)
@pytest.mark.parametrize("name,file_name,law,today", [
    ("A", "20261220C116300.01", {}, TODAY),
    ("K", "20260820C116300.01", {}, "2026-08-20"),
    ("BF", "20270520C116300.01", {}, TODAY),
])
def test_other_cases_run_to_the_end(tmp_path, capsys, name, file_name, law, today):
    f = filers.get(name)
    for aid, code in law.items():
        f["자산"][aid]["법정동코드"] = code
    code, out = _main(tmp_path, name, f, today=today)
    shown = capsys.readouterr()
    assert code == 0, shown.out + shown.err + _confirm(out)
    names = set(os.listdir(out))
    assert PDFS | GUIDES | CALC | {file_name, "신고값.json", "신고_확인.md"} <= names
    text = _confirm(out)
    for v in _personal(f):
        assert v not in text and v not in shown.out
    assert "서식 검산" in text and "전자신고 검증" in text and "통과" in text


def test_s1_preliminary_efile_bytes_are_pinned(tmp_path):
    """예정신고 S1 의 전자신고 파일 바이트를 고정한다. 확정신고 가산세, 지방소득세, 서식 열 규칙을 고치는 동안 예정신고의
    국세 파일이 바뀌지 않았다는 것을 본다. 기대 해시는 통합 브랜치(계획 2b, 공휴일 병합 뒤)가 만든 파일의 sha256 이다.
    레코드 레이아웃이나 합성 신고인 값, S1 사실관계를 일부러 바꾸면 이 값도 새 파일에서 다시 얻는다."""
    import hashlib
    code, out = _main(tmp_path, "S1", s1_filer())
    assert code == 0
    with open(out / S1_FILE, "rb") as fh:
        data = fh.read()
    assert hashlib.sha256(data).hexdigest() == "d82dff1e2fb66add08a8699c3c8c43a3cc0308581177786b52600992809f85b2"
    todo = _confirm(out).split("## 사람이 할 일", 1)[1]
    assert "신고기한 안에 국세와 지방소득세를 납부한다" in todo        # 예정신고의 납부 안내는 그대로다
    assert "값은 지방소득세_신고서.pdf 에 있다" in todo


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


def _a_with(tmp_path, **annual):
    """사례 A 의 연간 답을 바꿔 돌린다. (보고, 출력 폴더)."""
    facts = copy.deepcopy(CASES["A"])
    facts["연간"].update(annual)
    out = tmp_path / "out"
    return MR.make(facts, filers.get("A"), str(out), today=TODAY), out


def test_preliminary_return_with_prior_return_is_code_2(tmp_path):
    """같은 해 기신고가 있는 예정신고는 정상 신고서로 내지 않는다."""
    rep, out = _a_with(tmp_path, 다른양도=True, 기신고=50000000)
    assert rep["종료코드"] == 2 and rep["상태"] == "다루지않음"
    names = set(os.listdir(out))
    assert CALC | {"신고_확인.md"} <= names
    assert not (PDFS | GUIDES | {"신고값.json"}) & names and _efiles(out) == []
    text = _confirm(out)
    assert "기신고" in text and "계획 5" in text and "| 신고값 | 다루지않음 |" in text
    assert any(x["계획"] == "5" and "기신고" in x["내용"] for x in rep["다루지않음"])


def test_other_sale_answer_is_raised_in_notes_and_todo(tmp_path):
    """다른 양도가 있다고만 답한 건은 신고서를 만들되, 먼저 신고한 건이 있으면 세액이 달라진다고 알림과 사람이 할 일에 올린다."""
    rep, out = _a_with(tmp_path, 다른양도=True)
    assert rep["종료코드"] == 0 and _efiles(out) == ["20261220C116300.01"]
    text = _confirm(out)
    for part in (text.split("## 알림", 1)[1].split("##")[0], _todo_part(text), " ".join(rep["알림"]), " ".join(rep["사람이할일"])):
        assert "같은 해 다른 양도" in part and "기본공제" in part and "먼저 신고" in part
    assert DASH not in text and not [ln for ln in text.splitlines() if ln.rstrip().endswith("?")]
    plain, out2 = _a_with(tmp_path / "plain")
    assert plain["종료코드"] == 0 and plain["알림"] == [] and "같은 해 다른 양도" not in _confirm(out2)


# ---------------------------------------------------------------- 작성일이 오늘보다 앞선 신고인 파일

LATE = "2027-03-10"      # 사례 A 의 작성일 2026-12-20 과 신고기한 2027-02-01 을 모두 지난 날


def _stopped_for_old_date(rep_or_text, out):
    names = set(os.listdir(out))
    assert CALC | {"신고_확인.md"} <= names
    assert not (PDFS | GUIDES | {"신고값.json"}) & names and _efiles(out) == []
    text = _confirm(out)
    notes = text.split("## 알림", 1)[1].split("##")[0]
    assert "작성일" in notes and "2026-12-20" in notes and LATE in notes and "오늘" in notes and "앞선다" in notes
    assert "제출하는 날" in notes and "고쳐 다시 실행한다" in notes
    assert "| 신고값 | 만들지 않음(작성일이 오늘보다 앞섬) |" in text
    assert "입력 파일을 고친 뒤 다시 실행한다" in _todo_part(text)
    assert DASH not in text and not [ln for ln in text.splitlines() if ln.rstrip().endswith("?")]


def test_return_date_before_today_stops_with_code_2(tmp_path, capsys):
    """미리 만들어 둔 신고인 파일을 신고기한 뒤에 돌리면 기한후신고가 정기신고서로 나간다. 작성일이 오늘보다 앞서면 멈춘다."""
    f = filers.get("A")
    code, out = _main(tmp_path, "A", f, today=LATE)
    shown = capsys.readouterr()
    assert code == 2, shown.out + shown.err
    _stopped_for_old_date(None, out)
    assert "작성일" in shown.out
    for v in _personal(f):
        assert v not in shown.out and v not in _confirm(out)


@pytest.mark.parametrize("today,code", [("2026-12-20", 0), ("2026-12-19", 0), ("2026-12-21", 2)])
def test_return_date_on_or_after_today_passes(tmp_path, today, code):
    """작성일이 오늘과 같거나 뒤면 지나간다. 하루라도 앞서면 멈춘다."""
    rep = MR.make(CASES["A"], filers.get("A"), str(tmp_path / "o"), today=today)
    assert rep["종료코드"] == code, rep["알림"]
    assert (rep["상태"] == "입력오류") == (code == 2)


def test_return_date_is_compared_with_the_real_today_when_today_is_not_given(tmp_path, monkeypatch):
    """--오늘 을 주지 않으면 계산이 쓴 한국 시간 오늘과 견준다. 시험은 그 함수를 바꿔 끼워 달력에 기대지 않는다."""
    from yangdo import engine
    monkeypatch.setattr(engine, "today_seoul", lambda: LATE)
    rep = MR.make(CASES["A"], filers.get("A"), str(tmp_path / "late"))
    assert rep["종료코드"] == 2 and rep["상태"] == "입력오류" and rep["기준정보"]["오늘"] == LATE
    _stopped_for_old_date(None, tmp_path / "late")
    monkeypatch.setattr(engine, "today_seoul", lambda: "2026-12-01")
    assert MR.make(CASES["A"], filers.get("A"), str(tmp_path / "early"))["종료코드"] == 0


@pytest.mark.parametrize("tool", ["yangdo_forms", "yangdo_efile"])
@pytest.mark.parametrize("key", ["today", "오늘"])
def test_mcp_return_tools_stop_on_return_date_before_today(tmp_path, tool, key):
    f = filers.get("A")
    out = tmp_path / "o"
    res = mcp_server.call_tool(tool, {"facts": CASES["A"], "filer_path": _filer_file(tmp_path, f), "out_dir": str(out), key: LATE})
    assert res["종료코드"] == 2 and res["상태"] == "입력오류" and res["전자신고"] is None and res["서식검산"] is None
    assert any("작성일" in x and "앞선다" in x for x in res["알림"])
    _stopped_for_old_date(None, out)
    s = json.dumps(res, ensure_ascii=False)
    for v in _personal(f):
        assert v not in s


def test_return_date_before_today_is_told_together_with_filer_questions(tmp_path):
    """신고인 정보 질문이 있으면 질문으로 끝내되 작성일도 함께 알린다. 신고인 파일을 한 번에 고치게 하려는 것이다."""
    rep = MR.make(CASES["S1"], filers.get("S1"), str(tmp_path / "o"), today=LATE)
    assert rep["종료코드"] == 2 and rep["상태"] == "질문" and [q["문항"] for q in rep["신고인질문"]] == ["F04"]
    assert any("작성일" in x and "앞선다" in x for x in rep["알림"])
    rep = MR.make(CASES["S1"], filers.get("S1"), str(tmp_path / "p"), today=TODAY)
    assert rep["상태"] == "질문" and rep["알림"] == []


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
    monkeypatch.setattr(efile, "_lock_reason", lambda efile_dir=None: "규격판이 잠겨 있다(시험)")     # 규격판.json 의 잠금이 걸린 것처럼
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


# ---------------------------------------------------------------- 상대 경로 출력 폴더

def _relative_run(tmp_path, monkeypatch, capsys):
    fp, gp, _ = _write(tmp_path, "S1", s1_filer())
    monkeypatch.chdir(tmp_path)
    code = MR.main(["--사실관계", str(fp), "--신고인", str(gp), "--출력", "out", "--오늘", TODAY])
    shown = capsys.readouterr()
    assert code == 0, shown.out + shown.err + _confirm(tmp_path / "out")
    assert PDFS | GUIDES | CALC | {S1_FILE, "신고값.json", "신고_확인.md"} <= set(os.listdir(tmp_path / "out"))


def test_relative_output_folder_runs_to_the_end(tmp_path, monkeypatch, capsys):
    _relative_run(tmp_path, monkeypatch, capsys)


def test_relative_output_folder_runs_to_the_end_on_old_python(tmp_path, monkeypatch, capsys):
    """파이썬 3.10·3.11 의 tempfile.mkdtemp 는 dir 가 상대 경로면 상대 경로를 돌려준다. 그 동작을 흉내 내 돌린다."""
    real = efile.tempfile.mkdtemp

    def mkdtemp(suffix=None, prefix=None, dir=None):
        made = real(suffix=suffix, prefix=prefix, dir=dir)
        return os.path.join(dir, os.path.basename(made)) if dir else made

    monkeypatch.setattr(efile.tempfile, "mkdtemp", mkdtemp)
    _relative_run(tmp_path, monkeypatch, capsys)


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


# ---------------------------------------------------------------- 계산만 다시 돌렸을 때(run.py, yangdo_calculate)

RETURN_STAGE = PDFS | GUIDES | {"신고값.json", "신고_확인.md"}
KEEP = {"메모.txt": "내 파일", "20261215A103900.01": "다른 세목 파일", "고객자료.pdf": "pdf"}


def _changed(name):
    """양도가액을 바꾼 사실관계. 세액이 달라져 옛 신고서 단계 파일은 새 계산과 맞지 않는다."""
    f = copy.deepcopy(CASES[name])
    f["자산"][0]["전체양도가액"] += 100_000_000
    return f


def _plant(out):
    for n, body in KEEP.items():
        (out / n).write_text(body, encoding="utf-8")
    (out / "20251130C116300.01").write_text("옛 전자신고 파일", encoding="utf-8")
    (out / "양도소득세_신고서.pdf.tmp").write_text("쓰다 만 PDF", encoding="utf-8")
    stale = out / ".efile-old"
    stale.mkdir()
    (stale / "신고값.json").write_text("{}", encoding="utf-8")


def _only_calculation_left(out):
    names = set(os.listdir(out))
    assert CALC <= names
    assert not RETURN_STAGE & names, sorted(RETURN_STAGE & names)
    assert _efiles(out) == [] and not [n for n in names if n.startswith(".efile-") or n.endswith(".tmp")]
    for n, body in KEEP.items():
        assert (out / n).read_text(encoding="utf-8") == body


def test_mcp_calculate_after_efile_drops_the_old_return_files(tmp_path):
    f = filers.get("A")
    out = tmp_path / "o"
    done = mcp_server.call_tool("yangdo_efile", {"facts": CASES["A"], "filer_path": _filer_file(tmp_path, f),
                                                 "out_dir": str(out), "today": TODAY})
    assert done["종료코드"] == 0 and RETURN_STAGE | {"20261220C116300.01"} <= set(os.listdir(out))
    _plant(out)
    again = mcp_server.call_tool("yangdo_calculate", {"facts": _changed("A"), "out_dir": str(out), "today": TODAY})
    assert again["상태"] == "완료" and again["합계"]["산출세액"] != done["합계"]["산출세액"]
    _only_calculation_left(out)


def test_run_after_make_return_drops_the_old_return_files(tmp_path, capsys):
    import run
    code, out = _main(tmp_path, "S1", s1_filer())
    assert code == 0 and RETURN_STAGE | {S1_FILE} <= set(os.listdir(out))
    _plant(out)
    fp = tmp_path / "f2.json"
    fp.write_text(json.dumps(_changed("S1"), ensure_ascii=False), encoding="utf-8")
    assert run.main(["--사실관계", str(fp), "--출력", str(out), "--오늘", TODAY]) == 0
    _only_calculation_left(out)


def test_run_with_locked_pdf_still_drops_the_other_return_files(tmp_path, monkeypatch, capsys):
    """PDF 보기 프로그램이 옛 신고서를 열어 두었다. 나머지는 끝까지 지우고 종료코드 4 로 멈춘다."""
    import run
    code, out = _main(tmp_path, "S1", s1_filer())
    assert code == 0
    fp, _, _ = _write(tmp_path, "S1", s1_filer())
    capsys.readouterr()
    _lock(monkeypatch, "양도소득세_신고서.pdf")
    assert run.main(["--사실관계", str(fp), "--출력", str(out), "--오늘", TODAY]) == 4
    names = set(os.listdir(out))
    assert "양도소득세_신고서.pdf" in names and _efiles(out) == []
    assert not (GUIDES | CALC | {"신고값.json", "신고_확인.md", "지방소득세_신고서.pdf"}) & names
    assert "양도소득세_신고서.pdf" in capsys.readouterr().err


def test_return_stage_names_live_in_outputs():
    """지울 이름 목록은 yangdo/outputs.py 한 곳에 있다. 서식·전자신고 모듈의 이름과 같아야 한다."""
    from yangdo import outputs
    assert (outputs.FORM_NATIONAL, outputs.FORM_LOCAL) == (forms.OUT_NATIONAL, forms.OUT_LOCAL)
    assert outputs.EFILE_TMP_PREFIX == efile.TMP_PREFIX
    assert set(outputs.RETURN_NAMES) == RETURN_STAGE | {n + ".tmp" for n in PDFS}
    assert MR.OWN_NAMES is outputs.RETURN_NAMES and MR.EFILE_NAME is outputs.EFILE_NAME
    assert (MR.RV_FILE, MR.GUIDE_FILE, MR.ATTACH_FILE, MR.CONFIRM_FILE) == (
        outputs.RETURN_VALUES, outputs.GUIDE, outputs.ATTACHMENTS, outputs.CONFIRM)
    assert outputs.EFILE_NAME.match("20261220C116300.01") and not outputs.EFILE_NAME.match("20261215A103900.01")


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
                                                    "out_dir": str(blocker / "out"), "today": TODAY}}})
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
    secret = "김합성 비밀"                                      # 예외 문장에는 인적사항이 실릴 수 있다

    def boom(rv):
        raise KeyError(secret)

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
    # 표준오류에는 예외 형 이름과 호출 위치만 나온다. 예외 문장은 싣지 않는다
    assert "김합성" not in shown.err and "비밀" not in shown.err
    assert "KeyError" in shown.err and 'File "' in shown.err and "in boom" in shown.err
    assert "Traceback" not in shown.err
    made = text.split("## 만든 파일", 1)[1].split("## 사람이 할 일")[0]
    assert S1_FILE not in made and "신고서.pdf" not in made


def test_unexpected_error_in_render_is_reported_too(tmp_path, monkeypatch, capsys):
    message = "code=2: cannot open document"                   # pymupdf 가 내는 꼴

    def boom(rv, out_dir, **k):
        raise RuntimeError(message)

    monkeypatch.setattr(MR.forms, "render", boom)
    res = MR.make(CASES["S1"], s1_filer(), str(tmp_path / "o"), today=TODAY)
    assert res["종료코드"] == 1 and any("RuntimeError" in x for x in res["알림"])
    assert not any("cannot open" in x for x in res["알림"])
    assert "신고_확인.md" in os.listdir(tmp_path / "o")
    err = capsys.readouterr().err
    assert "RuntimeError" in err and 'File "' in err and "in boom" in err
    assert "cannot open" not in err and "Traceback" not in err


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


# ---------------------------------------------------------------- 확정신고(가산세를 넣어 신고서와 전자신고 파일까지 만든다)
# BF 손계산(references/정답지.md 「가산세 대조」): 무신고 41,254,800(감면 없음), 납부지연 4,855,680, 계 46,110,480,
# 납부할 세액 = 산출세액 206,274,000 + 46,110,480 = 252,384,480

BF_FILE = "20270520C116300.01"


def _bf_merged_facts():
    """같은 달에 양도한 두 자산의 세율이 다르고 합산 비교세액이 이기는 사례. 가산세를 정할 사례가 없다(penalty.Unsupported)."""
    facts = copy.deepcopy(CASES["BF"])
    facts["자산"][1]["취득"]["잔금일"] = "2025-06-01"
    return facts


def _main_facts(tmp_path, facts, filer, today=TODAY):
    fp, gp, out = tmp_path / "f.json", tmp_path / "g.json", tmp_path / "out"
    fp.write_text(json.dumps(facts, ensure_ascii=False), encoding="utf-8")
    gp.write_text(json.dumps(filer, ensure_ascii=False), encoding="utf-8")
    return MR.main(["--사실관계", str(fp), "--신고인", str(gp), "--출력", str(out), "--오늘", today]), out


def test_final_return_makes_forms_and_file_with_penalty(tmp_path, capsys):
    f = filers.get("BF")
    code, out = _main(tmp_path, "BF", f)
    shown = capsys.readouterr()
    assert code == 0, shown.out + shown.err + _confirm(out)
    names = set(os.listdir(out))
    assert CALC | GUIDES | PDFS | {"신고값.json", "신고_확인.md", BF_FILE} <= names
    assert not [n for n in names if n.startswith(".efile-") or n.endswith(".tmp")]
    text = _confirm(out)
    assert "| 서식 검산 | 통과 |" in text and "| 신고서 PDF | 만듦 |" in text and "만듦(%s)" % BF_FILE in text
    assert "만들지 않았다" not in text and "가산세를 계산하지 않" not in text
    with open(out / "신고값.json", encoding="utf-8") as fh:
        rv = json.load(fh)
    t = rv["본지"]["열"]["합계"]
    assert (t["가산세_신고"], t["가산세_납부"], t["가산세"], t["납부할세액"]) == (41254800, 4855680, 46110480, 252384480)
    assert rv["가산세"]["계산"] is True and rv["가산세"]["감면적용"] is False and rv["가산세"]["무신고_감면적용"] == 20627400
    # 전자신고 파일의 03 합계 행: 15 신고불성실, 16 납부불성실, 17 계, 19 자진납부할세액, 21 자진납부세액
    with open(out / BF_FILE, "rb") as fh:
        z = [ln for ln in fh.read().split(b"\r\n") if ln[:2] == b"03" and ln[9:12] == b"Z00"][0]
    assert [int(z[a:b]) for a, b in ((134, 147), (147, 160), (160, 173), (186, 199), (212, 225))] == \
        [41254800, 4855680, 46110480, 252384480, 252384480]
    for v in _personal(f):
        assert v not in text and v not in shown.out


def test_final_return_confirm_document_carries_the_penalty_notes(tmp_path):
    """세액이 달라질 수 있는 해석 둘(감면 전 금액과 문구 개정, 같은 달 양도의 대안 금액)과 다루지 않는 경우가
    신고_확인.md 와 입력 안내서에 그대로 실린다."""
    code, out = _main(tmp_path, "BF", filers.get("BF"))
    assert code == 0
    notes = _confirm(out).split("## 확인사항", 1)[1].split("##")[0]
    with open(out / "홈택스_입력안내.md", encoding="utf-8") as fh:
        md = fh.read()
    for doc in (notes, md.split("## 확인사항", 1)[1]):
        assert "감면 없이" in doc and "감면이 적용되면 무신고가산세는 20627400원" in doc and "2026-01-01 부터" in doc
        assert "양도일마다 따로 신고하는 것으로 보면" in doc and "36306400원" in doc and "4273250원" in doc
        assert "부정행위" in doc and "다루지 않는다" in doc
        assert "납부일(2027-05-20) 기준" in doc
        # 지방소득세 가산세: 금액, 감면을 적용했다는 것과 대안 금액, 두 가지 가정
        assert "지방소득세에도 예정신고 무신고가산세 2062740원과 납부지연가산세 226901원" in doc
        assert "감면이 적용되지 않으면 지방소득세 무신고가산세는 4125480원" in doc
        assert "두 가지를 가정" in doc and "위택스 값을 따른다" in doc
        assert "지방소득세 신고서의 가산세는 계산하지 않아" not in doc
    assert not md.startswith(">")                              # 끝까지 간 실행이라 맨 위 경고 줄이 없다
    body = md.split("### 세액계산 결과", 1)[1].split("## 7.", 1)[0]
    assert "가산세는 계산하지 않았다" not in body and "46,110,480원" in body and "따로 계산해 더한다" not in md
    # 감면을 적용하지 않았다는 문장은 확인사항 여러 줄에 묻히지 않게 알림 절에도 올리고, 사람이 할 일에 한 줄을 둔다
    alerts = _confirm(out).split("## 알림", 1)[1].split("##")[0]
    assert "감면 없이" in alerts and "기한 후 신고로 내면" in alerts and "20627400원" in alerts and "세무 전문가" in alerts
    todo = _confirm(out).split("## 사람이 할 일", 1)[1]
    late = [ln for ln in todo.splitlines() if "기한 후 신고로 내는 방법" in ln]
    assert len(late) == 1 and "견주어 본다" in late[0] and "20627400원" in late[0]
    todo = _confirm(out).split("## 사람이 할 일", 1)[1]
    assert "형식검증" in todo and "위택스" in todo
    # 지방소득세 신고서에 가산세가 들어 있다. 두 가지를 가정한 값이라 위택스 화면의 값과 다르면 위택스 값을 따르라고 적는다
    local = [ln for ln in todo.splitlines() if "위택스" in ln and "지방소득세" in ln][0]
    assert "값은 지방소득세_신고서.pdf 에 있다" in local and "가정" in local and "위택스 값을 따른다" in local
    assert "가산세가 빠진 값" not in _confirm(out) and "실제보다 적다" not in _confirm(out)
    with open(out / "신고값.json", encoding="utf-8") as fh:
        loc = json.load(fh)["지방"]["열"]["합계"]
    assert (loc["가산세_신고"], loc["가산세_납부"], loc["가산세"], loc["납부할세액"]) == (2062740, 226901, 2289641, 22917041)
    # 납부지연가산세를 작성일에 내는 것으로 셌다. 「신고기한 안에 납부」가 아니라 작성일에 납부하라고 적는다
    pay = [ln for ln in todo.splitlines() if "납부한다" in ln][0]
    assert "국세와 지방소득세는 작성일 2027-05-20 에 납부한다" in pay and "작성일을 그 날로 바꿔 다시 만든다" in pay
    assert "신고기한 안에 국세와 지방소득세를 납부한다" not in todo
    assert DASH not in _confirm(out) and not [ln for ln in _confirm(out).splitlines() if ln.rstrip().endswith("?")]


def test_final_return_whose_penalty_cannot_be_determined_makes_no_forms(tmp_path, capsys):
    """penalty.Unsupported 면 그 사유로 신고서와 전자신고 파일을 만들지 않고 종료코드 2 로 끝낸다(참고용 값은 낸다)."""
    f = filers.get("BF")
    code, out = _main_facts(tmp_path, _bf_merged_facts(), f)
    shown = capsys.readouterr()
    assert code == 2, shown.out + shown.err
    names = set(os.listdir(out))
    assert CALC | GUIDES | {"신고값.json", "신고_확인.md"} <= names
    assert not PDFS & names and _efiles(out) == []
    assert not [n for n in names if n.startswith(".efile-") or n.endswith(".tmp")]
    text = _confirm(out)
    alerts = text.split("## 알림", 1)[1].split("##")[0]
    for word in ("확정신고", "가산세를 계산하지 못해", "신고서와 전자신고 파일을 만들지 않았다", "합산 비교세액", "실제보다 적게",
                 "세무 전문가", "참고용"):
        assert word in alerts, word
    assert "| 서식 검산 | 통과 |" in text and "만들지 않음(확정신고 가산세)" in text
    assert "전액 비과세" not in text and "가산세" in shown.out
    for v in _personal(f):
        assert v not in text and v not in shown.out
    for g in GUIDES:
        head = _first_line(out, g)
        assert "확정신고" in head and "가산세" in head and "참고용" in head and "전액 비과세" not in head
    with open(out / "홈택스_입력안내.md", encoding="utf-8") as fh:
        md = fh.read()
    body = md.split("### 세액계산 결과", 1)[1].split("## 7.", 1)[0]
    assert "빠져 있다" in md.splitlines()[0] and "가산세는 계산하지 못했다" in body and "이 값으로 입력하지 않는다" in body
    with open(out / "신고값.json", encoding="utf-8") as fh:
        rv = json.load(fh)
    assert rv["신고"]["구분"] == "확정" and rv["가산세"]["계산"] is False


def test_final_return_with_fully_exempt_asset_is_held_for_the_exempt_asset_only(tmp_path):
    """전액 비과세 자산만 있는 확정신고는 가산세가 없다. 전액 비과세 사유 하나로 막힌다."""
    f = g_filer()
    f["신고"].update(구분="확정", 작성일="2027-05-20")
    code, out = _main(tmp_path, "G", f)
    assert code == 2
    names = set(os.listdir(out))
    assert GUIDES | {"신고값.json"} <= names and not PDFS & names and _efiles(out) == []
    text = _confirm(out)
    notes = text.split("## 알림", 1)[1].split("##")[0]
    assert "전액 비과세 자산(G)" in notes and "가산세" not in notes
    assert "전액 비과세" in text.splitlines()[2] and "가산세" not in text.splitlines()[2]
    for g in GUIDES:
        head = _first_line(out, g)
        assert "전액 비과세" in head and "참고용" in head and "가산세" not in head


@pytest.mark.parametrize("tool", ["yangdo_forms", "yangdo_efile"])
def test_mcp_final_return_gives_the_same_result(tmp_path, tool):
    f = filers.get("BF")
    out = tmp_path / "o"
    res = mcp_server.call_tool(tool, {"facts": CASES["BF"], "filer_path": _filer_file(tmp_path, f), "out_dir": str(out),
                                      "today": TODAY})
    assert res["종료코드"] == 0 and res["상태"] == "완료" and res["서식검산"] == [] and res["다루지않음"] == []
    made = {os.path.basename(x) for x in res["파일"]}
    assert GUIDES | PDFS | {"신고값.json", "신고_확인.md"} <= made
    if tool == "yangdo_efile":
        assert res["전자신고"]["파일명"] == BF_FILE and res["전자신고"]["검증"] == [] and BF_FILE in made
    else:
        assert res["전자신고"] is None and not [n for n in made if "C116300" in n]
    notes = " ".join(res["확인사항"])
    assert "감면이 적용되면 무신고가산세는 20627400원" in notes and "부정행위" in notes
    assert any("감면 없이" in x for x in res["알림"]) and any("기한 후 신고로 내는 방법" in x for x in res["사람이할일"])
    s = json.dumps(res, ensure_ascii=False)
    for v in _personal(f):
        assert v not in s


def test_mcp_final_return_without_determinable_penalty_is_held(tmp_path):
    f = filers.get("BF")
    out = tmp_path / "o"
    res = mcp_server.call_tool("yangdo_efile", {"facts": _bf_merged_facts(), "filer_path": _filer_file(tmp_path, f),
                                                "out_dir": str(out), "today": TODAY})
    assert res["종료코드"] == 2 and res["상태"] == "다루지않음" and res["전자신고"] is None
    assert "확정신고 가산세" in " ".join(res["사람이할일"]) and res["서식검산"] == []
    assert "가산세" in res["요약"] and any("가산세" in x["내용"] and "합산 비교세액" in x["내용"] for x in res["다루지않음"])
    names = set(os.listdir(out))
    assert not PDFS & names and _efiles(out) == []
    s = json.dumps(res, ensure_ascii=False)
    for v in _personal(f):
        assert v not in s


def test_withheld_reasons_are_collected_in_one_place():
    """신고서·파일을 만들지 않는 사유는 한 함수가 모은다. 과세 자산의 예정신고와, 가산세를 계산한 확정신고는 사유가 없다."""
    def rv(kind, pen=None):
        return {"신고": {"구분": kind}, "가산세": pen}

    def res(*exempt):
        return {"계산": {"자산": [{"id": a, "판정": {"전액비과세": x}} for a, x in exempt]}}

    done = {"계산": True, "무신고": 1, "납부지연": 2, "계": 3}
    failed = {"계산": False, "사유": "자산 B, F: 정하지 않았다", "계획": "없음"}
    assert MR.withheld(rv("예정"), res(("A", False))) == []
    assert MR.withheld(rv("확정", done), res(("A", False))) == []
    assert [w["이름"] for w in MR.withheld(rv("예정"), res(("A", False), ("G", True)))] == ["전액 비과세 자산"]
    held = MR.withheld(rv("확정", failed), res(("A", False)))
    assert [w["이름"] for w in held] == ["확정신고 가산세"]
    assert "정하지 않았다" in held[0]["알림"] and held[0]["다루지않음"][0]["계획"] == "없음"
    both = MR.withheld(rv("확정", failed), res(("G", True)))
    assert [w["이름"] for w in both] == ["전액 비과세 자산", "확정신고 가산세"]
    for w in both:
        assert set(w) == {"이름", "까닭", "알림", "안내", "다루지않음"}


# ---------------------------------------------------------------- T18: 신고서와 전자신고 파일을 만들지 않은 실행의 확인 문서

def _prose(text):
    """표의 줄을 뺀 글. 표의 상태 칸에는 다루지않음 같은 상태 값이 그대로 나올 수 있다."""
    return "\n".join(ln for ln in text.splitlines() if not ln.startswith("|"))


def _todo_part(text):
    return text.split("## 사람이 할 일", 1)[1]


def _made_part(text):
    return text.split("## 만든 파일", 1)[1].split("## 사람이 할 일", 1)[0]


FILE_FREE_WORDS = ("형식검증", "내용검증", "로그인", "제출", "위택스", "만들어진 뒤")


@pytest.mark.parametrize("name,reason", [("BF", "확정신고 가산세"), ("G", "전액 비과세 자산")])
def test_withheld_run_confirm_document_has_only_sentences_that_fit(tmp_path, name, reason):
    if name == "BF":                                        # 가산세를 정하지 못하는 확정신고
        code, out = _main_facts(tmp_path, _bf_merged_facts(), filers.get("BF"))
    else:
        code, out = _main(tmp_path, name, g_filer())
    assert code == 2
    text = _confirm(out)
    todo = _todo_part(text)
    assert "신고서와 전자신고 파일이 없다" in todo and reason in todo and "세무 전문가" in todo
    for word in FILE_FREE_WORDS:                            # 만들지 않은 파일의 형식검증·제출 안내는 나오지 않는다
        assert word not in todo, word
    assert "03 레코드" not in text and "형식검증" not in text   # 만들지 않은 전자신고 파일의 칸 문장도 싣지 않는다
    notes = text.split("## 확인사항", 1)[1].split("##")[0] if "## 확인사항" in text else ""
    assert not [ln for ln in notes.splitlines() if MR.guide.FILE_ONLY.search(ln) and "필요경비에서 뺀" not in ln]
    made = _made_part(text)                                # 없는 파일을 인적사항 경고에 올리지 않는다
    assert "인적사항이 들어 있다" in made and "신고서 PDF" not in made and "전자신고 파일" not in made
    assert "다루지않음" not in _prose(text)
    assert DASH not in text and not [ln for ln in text.splitlines() if ln.rstrip().endswith("?")]


def test_withheld_run_mcp_response_matches_the_confirm_document(tmp_path):
    f = filers.get("BF")
    res = mcp_server.call_tool("yangdo_efile", {"facts": _bf_merged_facts(), "filer_path": _filer_file(tmp_path, f),
                                                "out_dir": str(tmp_path / "o"), "today": TODAY})
    assert res["종료코드"] == 2
    todo = " ".join(res["사람이할일"])
    assert "신고서와 전자신고 파일이 없다" in todo and "확정신고 가산세" in todo
    for word in FILE_FREE_WORDS:
        assert word not in todo, word
    assert not [x for x in res["확인사항"] if MR.guide.FILE_ONLY.search(x) and "필요경비에서 뺀" not in x]
    assert "다루지않음" not in " ".join(res["알림"] + res["사람이할일"] + [res["요약"]])


def test_full_run_confirm_document_keeps_its_file_sentences(tmp_path):
    code, out = _main(tmp_path, "S1", s1_filer())
    assert code == 0
    text = _confirm(out)
    assert "신고서 PDF, 전자신고 파일" in _made_part(text)
    todo = _todo_part(text)
    assert "형식검증" in todo and "제출" in todo and "신고서와 전자신고 파일이 없다" not in todo


def test_unsupported_run_has_no_reference_values_sentence(tmp_path, monkeypatch):
    def out_of_scope(*a, **k):
        raise return_values.Unsupported("확정신고에 같은 해 예정신고분(기신고)을 합산하는 신고는 계획 5 에서 다룬다", "5")

    monkeypatch.setattr(MR.return_values, "build", out_of_scope)
    code, out = _main(tmp_path, "S1", s1_filer())
    assert code == 2
    text = _confirm(out)
    todo = _todo_part(text)
    assert "참고용" not in text                              # 신고값을 만들지 못했으니 참고용으로 낸 값이 없다
    assert "신고서와 전자신고 파일이 없다" in todo and "세무 전문가" in todo
    for word in FILE_FREE_WORDS:
        assert word not in todo, word
    assert "다루지않음" not in _prose(text)


def test_calculation_stage_scope_stop_has_no_reference_values_sentence(tmp_path):
    from answer_keys import OUT
    fp, gp, out = tmp_path / "f.json", tmp_path / "g.json", tmp_path / "out"
    fp.write_text(json.dumps(OUT["02"]["facts"], ensure_ascii=False), encoding="utf-8")
    gp.write_text(json.dumps(s1_filer(), ensure_ascii=False), encoding="utf-8")
    res = MR.make(str(fp), str(gp), str(out), today=TODAY)
    assert res["종료코드"] == 2 and res["상태"] == "다루지않음" and not res["질문"]
    text = _confirm(out)
    assert "참고용" not in text
    assert "신고서와 전자신고 파일이 없다" in _todo_part(text)
    for word in FILE_FREE_WORDS:
        assert word not in _todo_part(text), word
    assert "다루지않음" not in _prose(text) and "다루지않음" not in res["요약"]
    assert "다루지 않는 경우" in res["요약"] and "다루지 않는 경우" in text


def test_question_run_keeps_its_instruction_and_has_no_reference_values_sentence(tmp_path):
    p, out = _run(tmp_path, "S1", filers.get("S1"))          # 성수동 법정동코드 질문(F04)
    assert p.returncode == 2
    text = _confirm(out)
    assert "참고용" not in text
    assert "위 질문에 답을 채운 뒤 다시 실행한다" in _todo_part(text)
