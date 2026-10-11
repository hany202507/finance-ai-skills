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
from yangdo import efile, efile_tmp, forms, forms_pdf, return_values

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


def _section(text, head):
    """확인 문서에서 head 절의 본문. 절이 없으면 빈 글자(IndexError 를 내지 않는다)."""
    parts = text.split(head, 1)
    return parts[1].split("\n## ")[0] if len(parts) == 2 else ""


def _efiles(out):
    return [n for n in os.listdir(str(out)) if "C116300" in n]


def _personal(filer):
    """화면·확인 문서·MCP 응답에 나오면 안 되는 값. 주소는 다른 글에 섞여 나올 수 없는 읍면동과 아파트 이름으로 본다
    (번지·동·호 같은 짧은 숫자는 금액이나 날짜와 겹쳐 견줄 수 없다)."""
    p = filer["신고인"]
    vals = [p["성명"], p["주민등록번호"], p["전화"], filer["신고"]["홈택스ID"]]
    vals += [p["주소"][k] for k in ("읍면동", "아파트명") if p["주소"].get(k)]
    vals += [p["전자메일"]] if p.get("전자메일") else []
    vals += [filer["환급계좌"]["계좌번호"]] if filer.get("환급계좌") else []
    vals += [b[k] for b in filer["양수인"] for k in ("성명", "번호")]
    vals += [lot[k] for lot in filer["자산"].values() for k in ("취득상대방", "아파트명") if lot.get(k)]
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
@pytest.mark.parametrize("name,file_name,today", [
    ("A", "20261220C116300.01", TODAY),
    ("K", "20260820C116300.01", "2026-08-20"),
    ("BF", "20270520C116300.01", TODAY),
])
def test_other_cases_run_to_the_end(tmp_path, capsys, name, file_name, today):
    f = filers.get(name)
    code, out = _main(tmp_path, name, f, today=today)
    shown = capsys.readouterr()
    assert code == 0, shown.out + shown.err + _confirm(out)
    names = set(os.listdir(out))
    assert PDFS | GUIDES | CALC | {file_name, "신고값.json", "신고_확인.md"} <= names
    text = _confirm(out)
    for v in _personal(f):
        assert v not in text and v not in shown.out
    assert "서식 검산" in text and "전자신고 검증" in text and "통과" in text


# 전자신고 파일 바이트(sha256). 예정신고 S1·A·K 의 기대 해시는 통합 브랜치(계획 2b, 공휴일과 확정신고 가산세 병합 뒤)가 만든
# 파일의 값이고, 확정신고 BF 의 기대 해시는 전액 비과세 자산 처리까지 병합한 뒤(가산세 감면 미적용)의 파일 값이다.
# 레코드 레이아웃이나 합성 신고인 값, 사례의 사실관계를 일부러 바꾸면 이 값도 새 파일에서 다시 얻는다.
# K 의 작성일은 2026-08-20 이라 오늘을 그 날로 준다
PINNED = [
    ("S1", S1_FILE, TODAY, "d82dff1e2fb66add08a8699c3c8c43a3cc0308581177786b52600992809f85b2"),
    ("A", "20261220C116300.01", TODAY, "713f3b5d3e115737df257157da810b2034c8cf33acfdd5fd7cfdcd93fdc3de13"),
    ("K", "20260820C116300.01", "2026-08-20", "9e05b7c3e1f3bd3eaeec9399da53b50c310c47b2962dd5a23980d746987f30a7"),
    ("BF", "20270520C116300.01", TODAY, "446e14bcfac6293ade138847fe25446bbc1e1e0d865e2897c31d3f1d0eeece12"),
]


@pytest.mark.parametrize("name,file_name,today,digest", PINNED)
def test_efile_bytes_are_pinned(tmp_path, name, file_name, today, digest):
    """예정신고 S1·A·K 와 확정신고 BF 의 전자신고 파일 바이트를 고정한다. 신고값·서식·검산을 고치는 동안 정상 사례의
    국세 파일이 바뀌지 않았다는 것을 본다. BF 는 가산세(03 레코드 15·16·17·19)가 들어간 확정신고 파일이다."""
    import hashlib
    filer = s1_filer() if name == "S1" else filers.get(name)
    code, out = _main(tmp_path, name, filer, today=today)
    assert code == 0
    with open(out / file_name, "rb") as fh:
        data = fh.read()
    assert hashlib.sha256(data).hexdigest() == digest
    todo = _confirm(out).split("## 사람이 할 일", 1)[1]
    assert "값은 지방소득세_신고서.pdf 에 있다" in todo
    # 예정신고의 납부 안내는 그대로다. 확정신고에는 그 줄이 없다(가산세를 넣은 납부 안내가 따로 나온다)
    assert ("신고기한 안에 국세와 지방소득세를 납부한다" in todo) == (filer["신고"]["구분"] == "예정")


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

def test_only_fully_exempt_assets_stop_before_values(tmp_path):
    """전액 비과세 자산뿐이면 신고서를 만들 과세 자산이 없다. 계산 결과만 내고 종료코드 2 로 끝낸다(신고값과 안내서도 없다).
    과세 자산과 섞인 건, 문장과 MCP 응답은 tests/test_exempt_excluded.py 가 본다."""
    f = g_filer()
    p, out = _run(tmp_path, "G", f)
    assert p.returncode == 2, p.stdout + p.stderr
    names = set(os.listdir(out))
    assert CALC | {"신고_확인.md"} <= names
    assert not (PDFS | GUIDES | {"신고값.json"}) & names and not _efiles(out)
    text = _confirm(out)
    assert "신고서를 만들 과세 자산이 없다" in text and "신고서를 만들 과세 자산이 없다" in p.stdout
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
        raise return_values.Unsupported("확정신고에 같은 해 예정신고분(기신고)을 합산하는 신고는 아직 다루지 않는다", "미정")

    monkeypatch.setattr(MR.return_values, "build", out_of_scope)
    code, out = _main(tmp_path, "S1", s1_filer())
    assert code == 2
    assert "기신고" in _confirm(out) and "다룰 계획이 정해지지 않았다" in _confirm(out)
    assert "계획 미정" not in _confirm(out) and "계획 5" not in _confirm(out)
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
    assert "기신고" in text and "다룰 계획이 정해지지 않았다" in text and "| 신고값 | 다루지않음 |" in text
    assert "계획 5" not in text and "계획 미정" not in text
    assert any(x["계획"] == "미정" and "기신고" in x["내용"] for x in rep["다루지않음"])


def test_other_sale_answer_is_raised_in_notes_and_todo(tmp_path):
    """다른 양도가 있다고만 답한 건은 신고서를 만들되, 먼저 신고한 건이 있으면 세액이 달라진다고 알림과 사람이 할 일에 올린다."""
    rep, out = _a_with(tmp_path, 다른양도=True)
    assert rep["종료코드"] == 0 and _efiles(out) == ["20261220C116300.01"]
    text = _confirm(out)
    for part in (_section(text, "## 알림"), _todo_part(text), " ".join(rep["알림"]), " ".join(rep["사람이할일"])):
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
    notes = _section(text, "## 알림")
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
    # 신고서 PDF 가 제출용 이름으로 남는다. 전자신고 파일이 없다는 것, PDF 는 서식 검산을 통과한 것이라는 것,
    # 그래도 까닭을 확인하기 전에는 쓰지 않는다는 것을 확인 문서와 안내서 머리가 말한다
    notes = _section(text, "## 알림")
    assert "전자신고 파일은 없다" in notes and "서식 검산을 통과" in notes and "양도소득세_신고서.pdf" in notes
    for g in GUIDES:
        head = _first_line(out, g)
        assert "전자신고 파일은 없다" in head and "서식 검산을 통과" in head and "신고하지 않는다" in head


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
    # 전자신고 파일이 없다는 것과 남은 신고서 PDF 가 서식 검산을 통과한 것이라는 말이 확인 문서와 안내서 머리에 있다
    notes = _section(text, "## 알림")
    assert "전자신고 파일은 없다" in notes and "서식 검산을 통과" in notes and "양도소득세_신고서.pdf" in notes
    for g in GUIDES:
        head = _first_line(out, g)
        assert head.startswith("> ") and "전자신고 파일은 없다" in head and "서식 검산을 통과" in head
        assert "신고하지 않는다" not in head                 # 값은 쓸 수 있으니 「신고하지 않는다」 줄은 붙지 않는다


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


def test_report_paths_follow_the_output_folder_as_given(tmp_path, monkeypatch):
    """보고의 파일 경로는 모두 받은 출력 폴더 기준이다. 상대 경로로 받았으면 전자신고 파일도 상대 경로로 적는다."""
    monkeypatch.chdir(tmp_path)
    rep = MR.make(CASES["S1"], s1_filer(), "out", today=TODAY)
    assert rep["종료코드"] == 0
    assert {os.path.basename(p) for p in rep["파일"]} >= PDFS | GUIDES | {S1_FILE, "신고값.json", "신고_확인.md"}
    for p in rep["파일"]:
        assert p == os.path.join("out", os.path.basename(p)) and not os.path.isabs(p), p
    out = str(tmp_path / "o2")
    rep = MR.make(CASES["S1"], s1_filer(), out, today=TODAY)       # 절대 경로로 받으면 모두 절대 경로다
    assert all(p == os.path.join(out, os.path.basename(p)) for p in rep["파일"])


def test_relative_output_folder_runs_to_the_end_on_old_python(tmp_path, monkeypatch, capsys):
    """파이썬 3.10·3.11 의 tempfile.mkdtemp 는 dir 가 상대 경로면 상대 경로를 돌려준다. 그 동작을 흉내 내 돌린다."""
    real = efile_tmp.tempfile.mkdtemp

    def mkdtemp(suffix=None, prefix=None, dir=None):
        made = real(suffix=suffix, prefix=prefix, dir=dir)
        return os.path.join(dir, os.path.basename(made)) if dir else made

    monkeypatch.setattr(efile_tmp.tempfile, "mkdtemp", mkdtemp)
    _relative_run(tmp_path, monkeypatch, capsys)


# ---------------------------------------------------------------- 이전 결과 지우기

def test_rerun_drops_stale_results_and_keeps_other_files(tmp_path):
    code, out = _main(tmp_path, "S1", s1_filer())
    assert code == 0
    keep = {"메모.txt": "내 파일", "20261215A103900.01": "다른 세목 파일", "고객자료.pdf": "pdf"}
    for n, body in keep.items():
        (out / n).write_text(body, encoding="utf-8")
    (out / "20251130C116300.01").write_text("옛 전자신고 파일", encoding="utf-8")
    stale = out / ".efile-old_0001"
    stale.mkdir()
    (stale / "신고값.json").write_text("{}", encoding="utf-8")
    code, out = _main(tmp_path, "S1", filers.get("S1"))     # 이번에는 신고인 질문 F04 로 끝난다
    assert code == 2
    names = set(os.listdir(out))
    assert not (PDFS | GUIDES | {"신고값.json", S1_FILE, "20251130C116300.01", ".efile-old_0001"}) & names
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
    stale = out / ".efile-old_0001"
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
    (out / ".efile-old_0001").mkdir()
    _lock(monkeypatch, "양도소득세_신고서.pdf")                 # PDF 보기 프로그램이 국세 신고서를 열어 둔 채 다시 실행
    code, out = _main(tmp_path, "S1", s1_filer())
    assert code == 4
    names = set(os.listdir(out))
    assert _efiles(out) == []
    assert not (GUIDES | CALC | {"신고값.json", "지방소득세_신고서.pdf", ".efile-old_0001"}) & names   # 막힌 파일 말고는 끝까지 지운다
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


def test_foreign_filer_whose_nationality_has_no_korean_name_still_finishes(tmp_path, capsys):
    """국적 CD(코드표에 한글 이름이 없는 하나뿐인 국가)인 외국인 신고인도 신고서와 전자신고 파일까지 만든다. 국적 칸은 영문
    이름이 들어가지 않아 비우고 확인사항으로 알린다. 신고인이 고칠 수 있는 입력이 아니라 멈추지 않는다."""
    f = s1_filer()
    f["신고인"].update(내외국인="9", 국적="CD", 주민등록번호=filers.rrn("0001015", "23456"))
    code, out = _main(tmp_path, "S1", f)
    shown = capsys.readouterr()
    assert code == 0, shown.out + shown.err + _confirm(out)
    names = set(os.listdir(out))
    assert PDFS | {"신고값.json", "신고_확인.md", S1_FILE} <= names
    text = _confirm(out)
    assert "| 신고서 PDF | 만듦 |" in text and "국적" in text and "비워 두었다" in text
    assert "CONGO" not in text and "이름이 비어" not in text
    nat = [ln for ln in text.splitlines() if "국적" in ln]
    assert len(nat) == 1 and nat[0].count("국적") == 1, nat            # 국적 칸의 확인사항은 한 줄이다


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
        assert "감면 없이" in doc and "감면이 적용되면 무신고가산세는 20,627,400원" in doc and "2026-01-01 부터" in doc
        assert "양도일마다 따로 신고하는 것으로 보면" in doc and "36,306,400원" in doc and "4,273,250원" in doc
        assert "부정행위" in doc and "다루지 않는다" in doc
        assert "납부일(2027-05-20) 기준" in doc
        # 지방소득세 가산세: 금액(국세와 같이 감면 없음, 20,627,400 × 20% = 4,125,480), 감면을 적용하지 않은 까닭과 대안 금액, 두 가지 가정
        assert "지방소득세에도 예정신고 무신고가산세 4,125,480원과 납부지연가산세 226,901원" in doc
        assert "지방소득세 무신고가산세는 감면 없이 계산했다" in doc and "과세관청이 달리 본 예가 있어 적용하지 않았다" in doc
        assert "감면이 적용되면 지방소득세 무신고가산세는 2,062,740원" in doc and "경정할 것을 미리 알고 신고한 경우가 아니" in doc
        assert "감면이 적용되지 않으면" not in doc and "감면 50% 를 적용했다" not in doc
        assert "두 가지를 가정" in doc and "위택스 값을 따른다" in doc
        assert "지방소득세 신고서의 가산세는 계산하지 않아" not in doc
    assert not md.startswith(">")                              # 끝까지 간 실행이라 맨 위 경고 줄이 없다
    body = md.split("### 세액계산 결과", 1)[1].split("## 7.", 1)[0]
    assert "가산세는 계산하지 않았다" not in body and "46,110,480원" in body and "따로 계산해 더한다" not in md
    # 감면을 적용하지 않았다는 문장은 확인사항 여러 줄에 묻히지 않게 알림 절에도 올리고, 사람이 할 일에 한 줄을 둔다
    alerts = _section(_confirm(out), "## 알림")
    assert "감면 없이" in alerts and "기한 후 신고로 내면" in alerts and "20,627,400원" in alerts and "세무 전문가" in alerts
    # 지방소득세 무신고가산세를 감면 없이 넣었다는 문장과 감면이 적용될 때의 금액도 알림에 올린다
    local_alert = [ln for ln in alerts.splitlines() if "지방소득세 무신고가산세는 감면 없이" in ln]
    assert len(local_alert) == 1 and "2,062,740원" in local_alert[0] and "위택스 값을 따른다" in local_alert[0]
    todo = _confirm(out).split("## 사람이 할 일", 1)[1]
    late = [ln for ln in todo.splitlines() if "기한 후 신고로 내는 방법" in ln]
    assert len(late) == 1 and "대조한다" in late[0] and "20,627,400원" in late[0]
    assert "그렇게 내서 감면이 적용되면 무신고가산세가 20,627,400원으로 줄어든다" in late[0]      # 「내 감면」으로 읽히지 않게 적는다
    todo = _confirm(out).split("## 사람이 할 일", 1)[1]
    assert "형식검증" in todo and "위택스" in todo
    # 지방소득세 신고서에 가산세가 들어 있다. 두 가지를 가정한 값이라 위택스 화면의 값과 다르면 위택스 값을 따르라고 적는다
    local = [ln for ln in todo.splitlines() if "위택스" in ln and "지방소득세" in ln][0]
    assert "값은 지방소득세_신고서.pdf 에 있다" in local and "가정" in local and "위택스 값을 따른다" in local
    assert "가산세가 빠진 값" not in _confirm(out) and "실제보다 적다" not in _confirm(out)
    with open(out / "신고값.json", encoding="utf-8") as fh:
        loc = json.load(fh)["지방"]["열"]["합계"]
    assert (loc["가산세_신고"], loc["가산세_납부"], loc["가산세"], loc["납부할세액"]) == (4125480, 226901, 4352381, 24979781)
    # 납부지연가산세를 작성일에 내는 것으로 셌다. 「신고기한 안에 납부」가 아니라 작성일에 납부하라고 적는다
    pay = [ln for ln in todo.splitlines() if "납부한다" in ln][0]
    assert "국세와 지방소득세는 작성일 2027-05-20 에 납부한다" in pay and "작성일을 그 날로 바꿔 다시 만든다" in pay
    assert "신고기한 안에 국세와 지방소득세를 납부한다" not in todo
    assert DASH not in _confirm(out) and not [ln for ln in _confirm(out).splitlines() if ln.rstrip().endswith("?")]


def test_final_return_before_the_local_deadline_says_no_local_penalty_in_one_line(tmp_path):
    """BF 를 2027-03-31 에 신고·납부: 국세 예정신고 납부기한 2027-02-01 은 지났고 지방 예정신고기한 2027-03-31 은 지나지 않았다.
    국세 가산세: 무신고 41,254,800, 납부지연 206,274,000 × 57일(02-02 ~ 03-30) × 22/100,000 = 2,586,675.96 → 2,586,670
    지방소득세는 가산세가 없다. 0원을 계산했다거나 감면을 적용했다는 문장, 가정해 계산했다는 문장을 내지 않고 한 줄만 적는다."""
    f = filers.get("BF")
    f["신고"]["작성일"] = "2027-03-31"
    code, out = _main(tmp_path, "BF", f)
    assert code == 0, _confirm(out)
    with open(out / "신고값.json", encoding="utf-8") as fh:
        rv = json.load(fh)
    t, loc = rv["본지"]["열"]["합계"], rv["지방"]["열"]["합계"]
    assert (t["가산세_신고"], t["가산세_납부"]) == (41254800, 2586670)
    assert (loc["가산세_신고"], loc["가산세_납부"], loc["가산세"], loc["납부할세액"]) == (0, 0, 0, 20627400)
    text = _confirm(out)
    line = "지방소득세는 지방 예정신고기한 2027-03-31 이전에 신고·납부하므로 가산세가 없다"
    notes = text.split("## 확인사항", 1)[1].split("##")[0]
    assert [ln for ln in notes.splitlines() if "지방소득세" in ln and "가산세" in ln] == ["- " + line]
    with open(out / "홈택스_입력안내.md", encoding="utf-8") as fh:
        md = fh.read()
    for doc in (text, md):
        assert "0원과 납부지연가산세 0원" not in doc and "적용되지 않으면" not in doc and "두 가지를 가정" not in doc
        assert "지방소득세 무신고가산세는 감면 없이" not in doc
    todo = text.split("## 사람이 할 일", 1)[1]
    local = [ln for ln in todo.splitlines() if "위택스" in ln and "지방소득세" in ln][0]
    assert "값은 지방소득세_신고서.pdf 에 있다" in local and "가정" not in local and "위택스 값을 따른다" not in local
    assert "국세와 지방소득세는 작성일 2027-03-31 에 납부한다" in todo
    alerts = text.split("## 알림", 1)[1].split("##")[0]
    assert "감면 없이" in alerts and "지방소득세 무신고가산세" not in alerts      # 국세 문장만 알림에 오른다


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
    alerts = _section(text, "## 알림")
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
    assert "감면이 적용되면 무신고가산세는 20,627,400원" in notes and "부정행위" in notes
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
    """신고서·파일을 만들지 않는 사유는 한 함수가 모은다. 과세 자산의 예정신고와, 가산세를 계산한 확정신고는 사유가 없다.
    전액 비과세 자산은 사유가 아니다(신고값이 그 자산을 빼고 과세 자산만 싣는다)."""
    def rv(kind, pen=None):
        return {"신고": {"구분": kind}, "가산세": pen}

    def res(*exempt):
        return {"계산": {"자산": [{"id": a, "판정": {"전액비과세": x}} for a, x in exempt]}}

    done = {"계산": True, "무신고": 1, "납부지연": 2, "계": 3}
    failed = {"계산": False, "사유": "자산 B, F: 정하지 않았다", "계획": "없음"}
    assert MR.withheld(rv("예정"), res(("A", False))) == []
    assert MR.withheld(rv("확정", done), res(("A", False))) == []
    assert MR.withheld(rv("예정"), res(("A", False), ("G", True))) == []
    held = MR.withheld(rv("확정", failed), res(("A", False)))
    assert [w["이름"] for w in held] == ["확정신고 가산세"]
    assert "정하지 않았다" in held[0]["알림"] and held[0]["다루지않음"][0]["계획"] == "없음"
    mixed = MR.withheld(rv("확정", failed), res(("A", False), ("G", True)))
    assert [w["이름"] for w in mixed] == ["확정신고 가산세"]
    for w in mixed:
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


def test_withheld_run_confirm_document_has_only_sentences_that_fit(tmp_path):
    reason = "확정신고 가산세"                                # 가산세를 정하지 못하는 확정신고
    code, out = _main_facts(tmp_path, _bf_merged_facts(), filers.get("BF"))
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
        raise return_values.Unsupported("확정신고에 같은 해 예정신고분(기신고)을 합산하는 신고는 아직 다루지 않는다", "미정")

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


# ---------------------------------------------------------------- 계획 2b G7: 미뤄 둔 지적

def test_prior_return_note_says_the_plan_once(tmp_path):
    """어느 계획에서 다루는지는 한 번만 말한다. 기신고 합산은 어느 계획에도 없어 「다룰 계획이 정해지지 않았다」가 한 번 나온다.
    신고값 모듈의 문장이 이미 그 말을 담고 있으면 같은 말을 한 번 더 붙이지 않는다."""
    rep, out = _a_with(tmp_path, 다른양도=True, 기신고=50000000)
    assert rep["종료코드"] == 2
    notes = [x for x in rep["알림"] if "기신고" in x]
    assert notes and all(x.count("다룰 계획이 정해지지 않았다") == 1 for x in notes), notes
    assert _confirm(out).count("다룰 계획이 정해지지 않았다") == 1
    assert "계획 5 에서 다룬다" not in _confirm(out)


def test_plan_sentence_for_each_kind_of_plan_value(tmp_path, monkeypatch):
    """다루지않음을 사람에게 말할 때: 계획 번호면 「계획 n 에서 다룬다」, 「미정」이면 「다룰 계획이 정해지지 않았다」,
    「없음」이면 「이 스킬이 다루지 않는다」. 「계획 미정 에서 다룬다」 같은 문장을 만들지 않는다."""
    from yangdo import outputs
    assert outputs.plan_text("5") == "계획 5 에서 다룬다" and outputs.plan_text("4") == "계획 4 에서 다룬다"
    assert outputs.plan_text("미정") == "다룰 계획이 정해지지 않았다" and outputs.plan_text("없음") == "이 스킬이 다루지 않는다"
    res = {"질문": [], "다루지않음": [{"자산": "B", "내용": "교환으로 양도한 자산", "계획": "미정"},
                                 {"자산": "B", "내용": "분양권 양도", "계획": "5"},
                                 {"자산": None, "내용": "과세연도가 다른 양도", "계획": "없음"}]}
    md = outputs.questions_md(res)
    assert "교환으로 양도한 자산. 다룰 계획이 정해지지 않았다" in md and "분양권 양도. 계획 5 에서 다룬다" in md
    assert "과세연도가 다른 양도. 이 스킬이 다루지 않는다" in md and "계획 미정" not in md

    for plan, want in (("5", "계획 5 에서 다룬다"), ("미정", "다룰 계획이 정해지지 않았다"), ("없음", "이 스킬이 다루지 않는다")):
        def out_of_scope(*a, _plan=plan, **k):
            raise return_values.Unsupported("합성 범위 밖 사유", _plan)
        monkeypatch.setattr(MR.return_values, "build", out_of_scope)
        folder = tmp_path / plan
        folder.mkdir()
        code, out = _main(folder, "S1", s1_filer())
        assert code == 2 and "합성 범위 밖 사유. %s" % want in _confirm(out), plan


def test_scope_stop_without_plan_still_says_who_handles_it(tmp_path, monkeypatch):
    def out_of_scope(*a, **k):
        raise return_values.Unsupported("국외 자산 신고는 다루지 않는다", "없음")

    monkeypatch.setattr(MR.return_values, "build", out_of_scope)
    rep = MR.make(CASES["S1"], s1_filer(), str(tmp_path / "o"), today=TODAY)
    assert any(x == "국외 자산 신고는 다루지 않는다. 이 스킬이 다루지 않는다" for x in rep["알림"])


def test_withheld_todo_does_not_repeat_the_word_reason(tmp_path):
    """사람이 할 일의 보류 문장은 「사유는 …이다. 사유를 …」처럼 같은 말을 잇지 않는다."""
    rep = MR.make(_bf_merged_facts(), filers.get("BF"), str(tmp_path / "o"), today=TODAY)      # 가산세를 계산하지 못하는 확정신고
    assert rep["종료코드"] == 2 and rep["보류사유"] == ["확정신고 가산세"]
    first = rep["사람이할일"][0]
    assert "확정신고 가산세" in first and "세무 전문가" in first and first.count("사유") == 1, first
    monkeypatch_free = MR.make(dict(CASES["A"], 연간=dict(CASES["A"]["연간"], 다른양도=True, 기신고=1)), filers.get("A"),
                               str(tmp_path / "p"), today=TODAY)
    assert monkeypatch_free["사람이할일"][0].count("사유") == 1


def test_question_counts_use_one_wording(tmp_path):
    """계산 질문으로 끝난 실행의 요약, 단계 칸, 확인 문서가 같은 말(계산 질문 n개, 이 도구가 다루지 않는 경우 m개)을 쓴다."""
    from yangdo import outputs
    rep = MR.make(CASES["L"], filers.get("A"), str(tmp_path / "o"), today=TODAY)
    assert rep["종료코드"] == 2
    words = outputs.QUESTION_COUNTS % (len(rep["질문"]), len(rep["다루지않음"]))
    assert rep["요약"].startswith(words) and rep["단계"]["계산"] == words
    assert _confirm(tmp_path / "o").count(words) >= 3              # 요약 줄, 단계 표, 계산 질문 절


def test_return_date_before_sale_date_is_an_input_error(tmp_path):
    """작성일이 양도일보다 앞서면 신고인 파일을 고칠 일이다. 신고값 실패(종료코드 1)가 아니라 입력 오류(종료코드 2)로 끝낸다."""
    f = s1_filer()
    f["신고"]["작성일"] = "2026-11-01"                          # S1 양도일은 2026-11-20
    rep = MR.make(CASES["S1"], f, str(tmp_path / "o"), today=TODAY)
    assert rep["종료코드"] == 2 and rep["상태"] == "입력오류", rep["알림"]
    assert any("2026-11-01" in x and "2026-11-20" in x and "양도일" in x for x in rep["알림"])
    assert rep["단계"]["신고값"].startswith("만들지 않음")
    names = set(os.listdir(tmp_path / "o"))
    assert not (PDFS | GUIDES | {"신고값.json"}) & names
    assert "입력 파일을 고친 뒤 다시 실행한다" in _todo_part(_confirm(tmp_path / "o"))


def test_unexpected_error_after_first_guide_marks_the_guide(tmp_path, monkeypatch):
    """입력 안내서를 쓴 뒤 부속서류에서 예상하지 못한 오류가 나면, 남은 안내서 맨 위에 쓰지 말라는 줄을 붙인다."""
    def boom(rv, facts, res):
        raise RuntimeError("김합성 비밀")

    monkeypatch.setattr(MR.guide, "attachments", boom)
    rep = MR.make(CASES["S1"], s1_filer(), str(tmp_path / "o"), today=TODAY)
    out = tmp_path / "o"
    assert rep["종료코드"] == 1 and rep["상태"] == "오류"
    names = set(os.listdir(out))
    assert "홈택스_입력안내.md" in names and "부속서류.md" not in names and not PDFS & names and not _efiles(out)
    head = _first_line(out, "홈택스_입력안내.md")
    assert head.startswith("> ") and "예상하지 못한 오류" in head and "신고하지 않는다" in head
    assert rep["단계"]["입력 안내서·부속서류"] == "만듦(신고에 쓰지 않는다)"
    assert rep["단계"]["신고서 PDF"].startswith("지움") and rep["단계"]["전자신고 파일"].startswith("지움")
    assert "김합성" not in _confirm(out)


def test_unexpected_error_does_not_say_removed_when_a_pdf_is_stuck(tmp_path, monkeypatch):
    """예상하지 못한 오류 뒤에 신고서 PDF 를 지우지 못했으면 단계 표와 알림이 지웠다고 적지 않는다."""
    def boom(rv):
        raise RuntimeError("터짐")

    monkeypatch.setattr(MR.guide, "hometax_input", boom)
    fp, gp, out = _write(tmp_path, "S1", s1_filer())
    real = os.remove

    def remove(path, *a, **k):
        # 이전 결과를 지우는 처음에는 없던 파일이다. 이번 실행이 만든 국세 신고서만 지워지지 않게 한다
        if os.path.basename(os.fspath(path)) == "양도소득세_신고서.pdf":
            raise PermissionError(13, "Permission denied", os.fspath(path))
        return real(path, *a, **k)

    monkeypatch.setattr(os, "remove", remove)
    rep = MR.make(str(fp), str(gp), str(out), today=TODAY)
    monkeypatch.undo()
    assert rep["종료코드"] == 1 and rep["상태"] == "오류"
    assert "양도소득세_신고서.pdf" in os.listdir(out) and _efiles(out) == []
    assert rep["단계"]["신고서 PDF"].startswith("지우지 못함") and rep["단계"]["전자신고 파일"].startswith("지움")
    text = _confirm(out)
    assert "지우지 못한 파일: 양도소득세_신고서.pdf" in text
    assert not any("전자신고 파일은 지웠다" in x and "신고서 PDF 와" in x for x in rep["알림"])
    assert any("일부가 남았다" in x for x in rep["알림"])


def test_unconfirmed_cells_come_from_the_layout_file(tmp_path, monkeypatch):
    """확인 문서의 「규격서 미확인 칸」 문장은 코드 상수가 아니라 레이아웃 파일의 FIXUPS 에서 읽는다."""
    assert not hasattr(MR, "UNCONFIRMED")
    with open(os.path.join(efile.EFILE_DIR, efile.LAYOUT_FILE), encoding="utf-8") as fh:
        layout = json.load(fh)
    marked = [x for x in layout["FIXUPS"] if "형식검증" in x.get("확인", "")]
    lines = MR._unconfirmed()
    assert len(lines) == len(marked) >= 5
    for word in ("01-23 세무프로그램코드", "01-18~22·26·27 세무대리인 칸", "03-31 주민세_세율", "01 레코드", "05 레코드 과세구분"):
        assert any(x.startswith(word) for x in lines), word
    # 레이아웃 파일의 문장을 바꾸면 확인 문서의 문장이 따라 바뀐다
    for x in layout["FIXUPS"]:
        if x.get("칸이름") == "01-23 세무프로그램코드":
            x["내용"] = "시험용으로 바꾼 문장"
    d = tmp_path / "efile"
    d.mkdir()
    (d / efile.LAYOUT_FILE).write_text(json.dumps(layout, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(efile, "EFILE_DIR", str(d))
    assert "01-23 세무프로그램코드: 시험용으로 바꾼 문장" in MR._unconfirmed()


def test_make_return_does_not_import_the_run_script():
    """실행 진입점끼리 가져다 쓰지 않는다. 함께 쓰는 도우미는 yangdo/outputs.py 에 있다."""
    import run
    from yangdo import outputs
    code = ("import sys; sys.path[:0] = [%r, %r]; import make_return; print('run' in sys.modules)"
            % (SKILL, os.path.join(SKILL, "scripts")))
    p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120)
    assert p.returncode == 0 and p.stdout.strip() == "False", p.stdout + p.stderr
    assert run.iso_date is outputs.iso_date and run.read_facts is outputs.read_facts and run._iso_date is outputs.iso_date


# ---------------------------------------------------------------- CI 의 합성 실행 단계

WORKFLOW = os.path.join(os.path.dirname(os.path.dirname(SKILL)), ".github", "workflows", "test.yml")


def _ci_commands():
    """CI 작업 파일에서 양도소득세 단계의 명령 줄(run: python ...)을 차례로 뽑는다."""
    with open(WORKFLOW, encoding="utf-8") as fh:
        lines = fh.read().splitlines()
    out = []
    for i, ln in enumerate(lines):
        if ln.strip() == "if: matrix.skill == '양도소득세'" and i + 1 < len(lines) and lines[i + 1].strip().startswith("run: "):
            out.append(lines[i + 1].strip()[len("run: "):])
    return out


@pytest.mark.skipif(not os.path.exists(WORKFLOW), reason="플러그인 저장소 없이 스킬 폴더만 있다")
def test_ci_runs_make_return_on_the_synthetic_case(tmp_path):
    """CI 작업 파일에 적힌 양도소득세 명령을 그대로 돌린다. 합성 입력 만들기, 신고서와 전자신고 파일 만들기, 파일 검증이 모두 0 으로 끝난다."""
    cmds = _ci_commands()
    assert len(cmds) == 3
    assert "tests/sample_inputs.py" in cmds[0] and "scripts/make_return.py" in cmds[1] and "yangdo.efile_check" in cmds[2]
    # CI 작업과 같은 환경으로 돌린다. PYTHONPATH 는 주지 않는다(작업 폴더가 스킬 폴더인 것만으로 돌아야 한다)
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    env.pop("PYTHONPATH", None)
    for cmd in cmds:
        words = cmd.split()
        assert words[0] == "python"
        # 작업 폴더는 CI 처럼 스킬 폴더로 두고, 쓰는 폴더(ci_sample, ci_out)만 임시 폴더 아래로 돌린다
        args = [str(tmp_path / w) if w.startswith(("ci_sample", "ci_out")) else w for w in words[1:]]
        p = subprocess.run([sys.executable] + args, cwd=SKILL, capture_output=True, text=True, encoding="utf-8", env=env, timeout=300)
        assert p.returncode == 0, cmd + chr(10) + p.stdout + p.stderr
    names = set(os.listdir(tmp_path / "ci_out"))
    assert PDFS | {"20261220C116300.01", "신고값.json", "신고_확인.md"} <= names


def test_sample_inputs_script_writes_both_files(tmp_path, capsys):
    import sample_inputs
    assert sample_inputs.main(["A", str(tmp_path / "s")]) == 0
    facts_path, filer_path, made = capsys.readouterr().out.split()
    with open(facts_path, encoding="utf-8") as fh:
        assert json.load(fh) == CASES["A"]
    with open(filer_path, encoding="utf-8") as fh:
        assert json.load(fh) == filers.get("A")
    assert made == "2026-12-20" and os.path.basename(filer_path) == "a_신고인.json"
    assert sample_inputs.main(["A"]) == 2
    with pytest.raises(SystemExit):
        sample_inputs.main(["없는사례", str(tmp_path / "t")])


def test_missing_section_is_an_empty_string_not_an_error():
    assert _section("# 제목\n\n## 단계\n\n표\n\n## 사람이 할 일\n\n1. 일\n", "## 알림") == ""
    assert _section("## 알림\n\n- 하나\n\n## 확인사항\n\n- 둘\n", "## 알림").strip() == "- 하나"


def test_personal_values_with_email_and_refund_account_stay_out(tmp_path, capsys):
    """전자메일과 환급계좌를 적은 신고인 파일로 끝까지 돌린다. 주소·전자메일·계좌번호도 화면, 확인 문서, 보고에 실리지 않는다."""
    f = s1_filer()
    f["신고인"]["전자메일"] = "hapseong.kim@example.com"
    f["환급계좌"] = {"은행코드": "004", "계좌번호": "98765432101234"}
    vals = _personal(f)
    assert {"hapseong.kim@example.com", "98765432101234", "공덕동", "합성아파트"} <= set(vals)
    fp, gp, out = _write(tmp_path, "S1", f)
    rep = MR.make(str(fp), str(gp), str(out), today=TODAY)
    code = MR.main(["--사실관계", str(fp), "--신고인", str(gp), "--출력", str(out), "--오늘", TODAY])
    shown = capsys.readouterr()
    assert rep["종료코드"] == 0 and code == 0
    text = _confirm(out)
    res = mcp_server.call_tool("yangdo_efile", {"facts": CASES["S1"], "filer_path": str(gp), "out_dir": str(tmp_path / "m"), "today": TODAY})
    for v in vals:
        for where, body in (("확인 문서", text), ("화면", shown.out + shown.err), ("보고", json.dumps(rep, ensure_ascii=False)),
                            ("MCP 응답", json.dumps(res, ensure_ascii=False))):
            assert v not in body, (where, v)
    with open(out / "신고값.json", encoding="utf-8") as fh:      # 신고값 파일에는 있다
        assert "hapseong.kim@example.com" in fh.read()


def test_final_return_after_preliminary_in_the_same_folder(tmp_path):
    """예정신고를 만든 폴더에 확정신고를 다시 돌린다. 예정신고의 전자신고 파일과 문서가 확정신고 결과 옆에 남지 않는다."""
    out = tmp_path / "out"
    first = MR.make(CASES["S1"], s1_filer(), str(out), today=TODAY)
    assert first["종료코드"] == 0 and _efiles(out) == [S1_FILE]
    before = {n: (out / n).read_bytes() for n in PDFS | GUIDES | {"신고값.json", "신고_확인.md"}}
    second = MR.make(CASES["BF"], filers.get("BF"), str(out), today=TODAY)
    assert second["종료코드"] == 0, second["알림"]
    assert _efiles(out) == ["20270520C116300.01"]              # 예정신고 파일(.01, 작성일 2026-12-15)은 지워졌다
    for n, old in before.items():
        assert (out / n).read_bytes() != old, n               # 모두 확정신고의 것으로 바뀌었다
    text = _confirm(out)
    assert S1_FILE not in text and "20270520C116300.01" in text
    with open(out / "신고값.json", encoding="utf-8") as fh:
        rv = json.load(fh)
    assert rv["신고"]["구분"] == "확정" and {x["자산"] for x in rv["부표1"]} == {"B", "F"}
    assert {os.path.basename(p) for p in second["파일"]} == set(os.listdir(out))


# ---------------------------------------------------------------- 검토 반영 1차(G7)

def _plant_mixed(out):
    """강제로 끝난 실행이 남긴 임시 폴더에 다른 파일이나 폴더가 끼어 있다. 이 도구의 폴더로 가리지 못해 지우지 않는다."""
    a = out / ".efile-killed02"
    a.mkdir(parents=True)
    (a / "20261215C116300.01").write_bytes(b"unchecked")
    (a / "신고값.json").write_text("{}", encoding="utf-8")
    (a / ".DS_Store").write_bytes(b"x")
    b = out / ".efile-killed03"
    (b / "sub").mkdir(parents=True)
    (b / "신고값.json").write_text("{}", encoding="utf-8")
    c = out / ".efile-abcd1234"                               # 이 도구의 파일이 하나도 없다. 사용자의 폴더라 알리지 않는다
    c.mkdir()
    (c / "내파일.txt").write_text("x", encoding="utf-8")
    return [".efile-killed02", ".efile-killed03"]


def _mixed_told(notes, names):
    for n in names:
        assert any(n in x and "다른 파일이 함께 있어 지우지 않았다" in x and "직접 확인해 지운다" in x for x in notes), (n, notes)
    assert not any(".efile-abcd1234" in x for x in notes)


def test_make_return_tells_about_mixed_temp_folders_it_did_not_remove(tmp_path):
    out = tmp_path / "out"
    names = _plant_mixed(out)
    rep = MR.make(CASES["S1"], s1_filer(), str(out), today=TODAY)
    assert rep["종료코드"] == 0
    left = set(os.listdir(out))
    assert set(names) | {".efile-abcd1234"} <= left          # 지우지 않았다
    assert (out / ".efile-killed02" / "신고값.json").exists()
    _mixed_told(rep["알림"], names)
    _mixed_told(_section(_confirm(out), "## 알림").splitlines(), names)
    _mixed_told(rep["전자신고"]["경고"], names)               # efile.write 의 경고에도 실린다
    for n in names:                                         # 확인 문서에는 알림에만 한 번 적는다
        assert sum(n in ln for ln in _confirm(out).splitlines()) == 1, n
    res = mcp_server.call_tool("yangdo_efile", {"facts": CASES["S1"], "filer_path": _filer_file(tmp_path, s1_filer()),
                                                "out_dir": str(out), "today": TODAY})
    _mixed_told(res["알림"], names)


def test_make_return_tells_about_mixed_temp_folders_even_when_it_stops_early(tmp_path):
    """신고인 질문으로 끝나 전자신고 단계까지 가지 않은 실행도 알린다."""
    out = tmp_path / "out"
    names = _plant_mixed(out)
    rep = MR.make(CASES["S1"], filers.get("S1"), str(out), today=TODAY)
    assert rep["종료코드"] == 2 and rep["전자신고"] is None
    _mixed_told(rep["알림"], names)


def test_run_and_mcp_calculate_tell_about_mixed_temp_folders(tmp_path, capsys):
    import run
    out = tmp_path / "out"
    names = _plant_mixed(out)
    fp, _, _ = _write(tmp_path, "A", filers.get("A"))
    capsys.readouterr()
    assert run.main(["--사실관계", str(fp), "--출력", str(out), "--오늘", TODAY]) == 0
    _mixed_told(capsys.readouterr().err.splitlines(), names)
    res = mcp_server.call_tool("yangdo_calculate", {"facts": CASES["A"], "out_dir": str(out), "today": TODAY})
    _mixed_told(res["알림"], names)
    assert set(names) <= set(os.listdir(out))


def test_efile_write_warns_about_mixed_temp_folders(tmp_path):
    names = _plant_mixed(tmp_path)
    rep = MR.make(CASES["S1"], s1_filer(), str(tmp_path / "o"), today=TODAY)
    with open(tmp_path / "o" / "신고값.json", encoding="utf-8") as fh:
        rv = json.load(fh)
    rv.pop("_주의")
    w = efile.write(rv, str(tmp_path))
    assert rep["종료코드"] == 0 and w["검증"] == [] and os.path.isfile(w["경로"])
    _mixed_told(w["경고"], names)
    assert efile_tmp.mixed(str(tmp_path)) == names and efile_tmp.left(str(tmp_path)) == []


def test_mcp_calculate_write_failure_still_tells_about_temp_folders(tmp_path, monkeypatch):
    """계산 도구가 쓰기 실패로 끝나도 지우지 못한 임시 폴더와 다른 파일이 섞인 임시 폴더를 알린다(run.py 와 같다)."""
    out = tmp_path / "out"
    names = _plant_mixed(out)
    stuck = out / ".efile-stuck001"
    stuck.mkdir()
    (stuck / "신고값.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(efile_tmp.shutil, "rmtree", lambda *a, **k: None)
    (out / "양도소득세_계산근거.xlsx").write_text("x", encoding="utf-8")
    _lock(monkeypatch, "양도소득세_계산근거.xlsx")
    r = mcp_server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                           "params": {"name": "yangdo_calculate", "arguments": {"facts": CASES["A"], "out_dir": str(out), "today": TODAY}}})
    monkeypatch.undo()
    text = r["result"]["content"][0]["text"]
    assert r["result"].get("isError") is True and "쓰지 못했다" in text
    assert ".efile-stuck001" in text and "직접 지운다" in text
    for n in names:
        assert n in text


def test_unexpected_error_marks_a_guide_that_already_has_another_head(tmp_path, monkeypatch):
    """참고용 머리 줄이 붙은 안내서(가산세를 계산하지 못한 확정신고)도 오류로 끝나면 그 사실이 맨 위에 온다."""
    def boom(rv, facts, res):
        raise RuntimeError("터짐")

    monkeypatch.setattr(MR.guide, "attachments", boom)
    out = tmp_path / "o"
    rep = MR.make(_bf_merged_facts(), filers.get("BF"), str(out), today=TODAY)
    assert rep["종료코드"] == 1 and rep["상태"] == "오류"
    with open(out / "홈택스_입력안내.md", encoding="utf-8") as fh:
        lines = fh.read().splitlines()
    assert lines[0].startswith("> ") and "예상하지 못한 오류" in lines[0] and "신고하지 않는다" in lines[0]
    assert lines[1] == "" and lines[2].startswith("> ") and "참고용" in lines[2]      # 먼저 붙은 머리 줄은 그 아래에 남는다
    assert sum(1 for ln in lines if "예상하지 못한 오류" in ln) == 1


def test_return_date_check_ignores_fully_exempt_assets(tmp_path):
    """작성일과 양도일을 견줄 때 신고서에 넣지 않는 전액 비과세 자산의 양도일은 보지 않는다(신고값 단계와 같다)."""
    res = {"계산": {"자산": [{"id": "A", "판정": {"양도일": "2026-11-20", "전액비과세": False}},
                           {"id": "G", "판정": {"양도일": "2026-12-28", "전액비과세": True}}]}}
    assert MR._return_before_sale({"신고": {"작성일": "2026-12-15"}}, res) is None
    assert "2026-11-20" in MR._return_before_sale({"신고": {"작성일": "2026-11-01"}}, res)
    assert MR._return_before_sale({"신고": {"작성일": None}}, res) is None
