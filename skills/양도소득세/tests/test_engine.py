# -*- coding: utf-8 -*-
import copy
import json
import os

import pytest

import run
from cases import CASES, EXPECT, EXPECT_TOTAL
from yangdo import engine
from yangdo import facts as F
from yangdo import ruleset


def calc(name, **kw):
    return engine.calculate(copy.deepcopy(CASES[name]), today="2026-10-09", **kw)


@pytest.mark.parametrize("name", sorted(EXPECT))
def test_cases(name):
    r = calc(name)
    assert r["상태"] == "완료" and r["검산"] == [], r.get("검산") or r.get("질문")
    assert r["계산"]["합계"]["산출세액"] == EXPECT[name]["산출세액"]
    assert r["기준정보"]["낡음"] is False and len(r["기준정보"]["판"]) == 16
    json.dumps(r, ensure_ascii=False)


@pytest.mark.parametrize("name", ["BC", "BF"])
def test_totals(name):
    assert calc(name)["계산"]["합계"]["산출세액"] == EXPECT_TOTAL[name]["산출세액"]


def test_heavy_case_warns():
    assert any("계류" in w for w in calc("D")["경고"])


def test_out_of_scope_and_question():
    r = calc("L")
    assert r["상태"] == "질문" and r["다루지않음"]
    f = copy.deepcopy(CASES["A"])
    f["자산"][0]["거주기간"] = None
    r = engine.calculate(f, today="2026-10-09")
    assert r["상태"] == "질문" and r["질문"][0]["문항"] == "H07"


def _auction_a(**양도):
    f = copy.deepcopy(CASES["A"])
    a = f["자산"][0]["양도"]
    a.update(원인="경매", 잔금일=None)
    a.update(양도)
    return f


def test_auction_transfer_calculates_on_full_payment_day():
    r = engine.calculate(_auction_a(대금완납일="2026-11-15"), today="2026-10-09")
    assert r["상태"] == "완료" and r["검산"] == [] and r["다루지않음"] == []
    assert r["계산"]["합계"]["산출세액"] == EXPECT["A"]["산출세액"]
    assert r["계산"]["자산"][0]["판정"]["양도일"] == "2026-11-15"


def test_auction_transfer_full_payment_day_wins_over_balance_day():
    r = engine.calculate(_auction_a(대금완납일="2026-11-15", 잔금일="2026-12-20"), today="2026-10-09")
    assert r["계산"]["자산"][0]["판정"]["양도일"] == "2026-11-15"


def test_auction_transfer_without_any_date_asks_a11():
    r = engine.calculate(_auction_a(), today="2026-10-09")
    assert r["상태"] == "질문" and r["질문"][0]["문항"] == "A11"


@pytest.mark.parametrize("원인,문구", [("교환", "교환으로 양도한 자산"), ("기타", "기타 원인으로 양도한 자산"),
                                     ("수용", "수용으로 양도한 자산(양도시기 시행령 제162조①7호, 조특법 감면)")])
def test_exchange_other_and_expropriation_transfer_not_calculated(원인, 문구):
    f = copy.deepcopy(CASES["A"])
    f["자산"][0]["양도"]["원인"] = 원인
    r = engine.calculate(f, today="2026-10-09")
    assert r["상태"] == "질문" and r["계산"] is None
    assert r["다루지않음"] == [{"자산": "A", "내용": 문구, "계획": "5"}]


def test_unsupported_plan_defaults_to_5_and_mixed_years_has_none():
    from yangdo import calc
    assert calc.Unsupported("x").계획 == "5" and calc.Unsupported("x", 계획="없음").계획 == "없음"
    f = copy.deepcopy(CASES["BC"])
    f["자산"][0]["양도"]["잔금일"] = "2025-12-01"
    r = engine.calculate(f, today="2026-10-09")
    assert r["다루지않음"] == [{"자산": None, "내용": "과세연도가 다른 양도는 연도마다 따로 계산합니다", "계획": "없음"}], r
    f = copy.deepcopy(CASES["B"])
    f["자산"][0]["전체양도가액"] = 400_000_000
    r = engine.calculate(f, today="2026-10-09")
    assert len(r["다루지않음"]) == 1 and r["다루지않음"][0]["계획"] == "5" and "양도차손" in r["다루지않음"][0]["내용"]


def test_personal_data_rejected():
    f = copy.deepcopy(CASES["A"])
    f["신고인"]["성명"] = "홍길동"
    with pytest.raises(F.FactsError):
        engine.calculate(f, today="2026-10-09")


def test_stale_edition_warns():
    r = engine.calculate(copy.deepcopy(CASES["A"]), today="2026-10-30")
    assert r["기준정보"]["낡음"] is True and any("7일" in w for w in r["경고"])


@pytest.mark.parametrize("name", ["A", "D", "J", "BF"])
def test_workbook_matches_engine(name, tmp_path):
    r = calc(name, workbook_path=str(tmp_path / "w.xlsx"))
    assert r["검산"] == []


def go(tmp_path, f, *extra):
    p = tmp_path / "facts.json"
    p.write_text(json.dumps(f, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "out"
    return run.main(["--사실관계", str(p), "--출력", str(out), "--오늘", "2026-10-09"] + list(extra)), out


def test_run_end_to_end(tmp_path):
    code, out = go(tmp_path, CASES["A"])
    assert code == 0
    for name in ("양도소득세_검토.md", "양도소득세_계산근거.xlsx", "result.json"):
        assert (out / name).exists(), name
    md = (out / "양도소득세_검토.md").read_text(encoding="utf-8")
    assert "2,565,000" in md and "제159조의4" in md and "검토용" in md
    res = json.loads((out / "result.json").read_text(encoding="utf-8"))
    assert res["계산"]["자산"][0]["계산"]["코드"]["세율구분"] == "10"


def test_run_question_exit_2(tmp_path):
    code, out = go(tmp_path, CASES["L"])
    assert code == 2 and "2025-01-01" in (out / "질문.md").read_text(encoding="utf-8")
    assert not (out / "양도소득세_계산근거.xlsx").exists()


def test_run_broken_rules_exit_3(tmp_path):
    bad = tmp_path / "rules"
    bad.mkdir()
    code, _ = go(tmp_path, CASES["A"], "--rules", str(bad))
    assert code == 3


# 아래는 묶음 4 착수 전 변경과 실행 스크립트의 종료코드·문서 내용을 확인하는 추가 시험

def test_no_assets_asks_for_asset():
    f = copy.deepcopy(CASES["A"])
    f["자산"] = []
    r = engine.calculate(f, today="2026-10-09")
    assert r["상태"] == "질문" and r["질문"][0]["문항"] == "P02" and r["계산"] is None


def test_broken_rules_raise_rule_error(tmp_path, monkeypatch):
    with pytest.raises(ruleset.RuleError):
        engine.calculate(copy.deepcopy(CASES["A"]), rules_dir=str(tmp_path), today="2026-10-09")

    def boom(rules_dir=None):
        raise FileNotFoundError("코드표.json")
    monkeypatch.setattr(engine.codes, "load", boom)
    with pytest.raises(ruleset.RuleError):
        engine.calculate(copy.deepcopy(CASES["A"]), today="2026-10-09")


def test_workbook_not_written_when_question(tmp_path):
    p = tmp_path / "w.xlsx"
    r = calc("L", workbook_path=str(p))
    assert r["상태"] == "질문" and not p.exists()


def test_report_has_group_row_and_note(tmp_path):
    code, out = go(tmp_path, CASES["BF"])
    assert code == 0
    md = (out / "양도소득세_검토.md").read_text(encoding="utf-8")
    row = "| 같은 세율 자산 합산 세액(소득세법 제104조⑤2호) | 206,274,000 |"
    assert row in md
    assert md.index("| 자산별 산출세액 합 |") < md.index(row) < md.index("| 합산 비교 세액(소득세법 제104조⑤) |")
    assert "참고값" in md


def test_report_shows_exempt_asset_as_not_applicable(tmp_path):
    code, out = go(tmp_path, CASES["G"])
    md = (out / "양도소득세_검토.md").read_text(encoding="utf-8")
    assert code == 0 and "| 취득가액 | 해당 없음 |" in md and "| 산출세액 | 0 |" in md


def test_report_lists_excluded_expenses(tmp_path):
    f = copy.deepcopy(CASES["B"])
    f["자산"][0]["필요경비"]["자본적지출"].append(
        {"내용": "샷시", "지급일": "2021-05-01", "금액": 3_000_000, "증빙종류": "간이영수증", "상대방": "합성업체"})
    code, out = go(tmp_path, f)
    md = (out / "양도소득세_검토.md").read_text(encoding="utf-8")
    assert code == 0 and "필요경비에서 뺀 항목" in md and "간이영수증" in md


def test_run_verify_failure_exit_1(tmp_path, monkeypatch):
    monkeypatch.setattr(engine.verify, "check", lambda res, f, rs: ["V6 A: 시험용 실패"])
    code, out = go(tmp_path, CASES["A"])
    assert code == 1
    md = (out / "양도소득세_검토.md").read_text(encoding="utf-8")
    assert "V6 A: 시험용 실패" in md and "통과" not in md.split("## 검산")[1]
    assert json.loads((out / "result.json").read_text(encoding="utf-8"))["상태"] == "검산실패"


def test_run_unreadable_facts_exit_2(tmp_path):
    bad = tmp_path / "facts.json"
    bad.write_text("{ 깨진 json", encoding="utf-8")
    assert run.main(["--사실관계", str(bad), "--출력", str(tmp_path / "o")]) == 2
    assert run.main(["--사실관계", str(tmp_path / "없음.json"), "--출력", str(tmp_path / "o")]) == 2


def test_run_personal_data_exit_2(tmp_path):
    f = copy.deepcopy(CASES["A"])
    f["신고인"]["성명"] = "홍길동"
    code, out = go(tmp_path, f)
    assert code == 2 and not (out / "result.json").exists()


def test_run_bad_date_argument(tmp_path):
    with pytest.raises(SystemExit):
        go(tmp_path, CASES["A"], "--오늘", "내일")


def test_question_file_uses_question_bank(tmp_path):
    f = copy.deepcopy(CASES["A"])
    f["자산"][0]["거주기간"] = None
    code, out = go(tmp_path, f)
    md = (out / "질문.md").read_text(encoding="utf-8")
    assert code == 2 and "[H07] 자산 A:" in md and "모를 때 확인하는 곳" in md


def test_generated_text_style(tmp_path):
    """생성한 문서에 줄표(U+2014)가 없고 물음표로 끝나는 줄이 없다."""
    _, out = go(tmp_path, CASES["BF"])
    md = (out / "양도소득세_검토.md").read_text(encoding="utf-8")
    assert "\u2014" not in md
    assert all(not ln.rstrip().endswith("?") for ln in md.splitlines())


@pytest.mark.parametrize("path,value", [
    ("전체양도가액", "1억"),
    ("전체취득가액", "8억"),
    ("거주기간", [["2014-11-01"]]),
    ("거주기간", "12년"),
])
def test_malformed_values_are_facts_error_or_question(path, value):
    """형식이 틀린 값은 FactsError 이거나 질문 상태다. 다른 예외는 어느 쪽으로도 새면 안 된다."""
    f = copy.deepcopy(CASES["A"])
    f["자산"][0][path] = value
    try:
        r = engine.calculate(f, today="2026-10-09")
    except F.FactsError:
        return
    assert r["상태"] == "질문"


def test_run_malformed_values_exit_2(tmp_path, capsys):
    f = copy.deepcopy(CASES["A"])
    f["자산"][0]["전체양도가액"] = "1억"
    code, out = go(tmp_path, f)
    assert code == 2 and "질문 1개" in capsys.readouterr().out
    assert "[M01]" in (out / "질문.md").read_text(encoding="utf-8")


# 출력 쓰기 실패는 종료코드 4. 1 은 검산 실패 전용이다.

def _err_lines(capsys):
    """stderr 의 줄. 검산 재계산 라이브러리(formulas)가 찍는 진행 막대(tqdm)는 이 스크립트의 출력이 아니라서 뺀다."""
    err = capsys.readouterr().err
    assert "Traceback" not in err
    return [ln for ln in err.splitlines() if ln.strip() and "it/s" not in ln and "s/it" not in ln]


def test_exit_codes_documented():
    assert "4 출력 파일 쓰기 실패" in run.__doc__ and "1 검산 실패" in run.__doc__


@pytest.mark.parametrize("case,name", [
    ("A", "result.json"),
    ("A", "양도소득세_검토.md"),
    ("A", "양도소득세_계산근거.xlsx"),
    ("L", "질문.md"),
])
def test_run_output_blocked_exit_4(tmp_path, capsys, case, name):
    """쓸 파일 자리에 폴더가 있으면 쓰지 못한다. 역추적 없이 종료코드 4 와 한 줄 안내만 낸다."""
    out = tmp_path / "out"
    (out / name).mkdir(parents=True)
    code, _ = go(tmp_path, CASES[case])
    lines = _err_lines(capsys)
    assert code == 4
    assert len(lines) == 1 and lines[0].startswith("출력 파일을 쓰지 못했습니다: ")
    assert name in lines[0] and "다시 실행" in lines[0]


def test_run_workbook_locked_exit_4(tmp_path, capsys, monkeypatch):
    """엑셀이 이전 통합 문서를 열어 두면 저장이 PermissionError 로 막힌다."""
    target = str(tmp_path / "out" / "양도소득세_계산근거.xlsx")

    def locked(res, path):
        raise PermissionError(13, "Permission denied", path)
    monkeypatch.setattr(engine.workbook, "write", locked)
    code, _ = go(tmp_path, CASES["A"])
    lines = _err_lines(capsys)
    assert code == 4 and len(lines) == 1
    assert target in lines[0] and "Permission denied" in lines[0]


def _snapshot(folder):
    return {p.name: p.read_bytes() for p in folder.iterdir()}


def test_run_cannot_remove_previous_workbook_exit_4(tmp_path, capsys, monkeypatch):
    """엑셀이 이전 통합 문서를 잡고 있으면 지우기가 막힌다. 통합 문서를 먼저 지우려 해서, 막히면 다른 파일도 그대로 남는다."""
    out = tmp_path / "out"
    code, _ = go(tmp_path, CASES["A"])
    assert code == 0
    (out / "내메모.txt").write_text("남겨야 함", encoding="utf-8")
    before = _snapshot(out)
    assert {"result.json", "양도소득세_검토.md", "양도소득세_계산근거.xlsx", "내메모.txt"} == set(before)
    old = str(out / "양도소득세_계산근거.xlsx")
    real_remove = os.remove

    def remove(path):
        if os.path.abspath(path) == os.path.abspath(old):
            raise PermissionError(13, "Permission denied", path)
        real_remove(path)
    monkeypatch.setattr(run.os, "remove", remove)
    code, _ = go(tmp_path, CASES["A"])
    lines = _err_lines(capsys)
    assert code == 4 and len(lines) == 1 and old in lines[0]
    assert _snapshot(out) == before   # 이전 결과 파일이 하나도 지워지지 않았고 새로 쓴 것도 없다


def test_run_output_dir_is_a_file_exit_4(tmp_path, capsys):
    (tmp_path / "out").write_text("파일", encoding="utf-8")
    code, _ = go(tmp_path, CASES["A"])
    lines = _err_lines(capsys)
    assert code == 4 and len(lines) == 1 and str(tmp_path / "out") in lines[0]


def test_run_exit_1_still_means_verify_failure(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(engine.verify, "check", lambda res, f, rs: ["V6 A: 시험용 실패"])
    code, _ = go(tmp_path, CASES["A"])
    assert code == 1 and "출력 파일을 쓰지 못했습니다" not in capsys.readouterr().err


# 같은 출력 폴더에 다시 실행하면 이전 실행의 산출물이 남지 않는다.

def test_rerun_with_question_removes_previous_outputs(tmp_path):
    code, out = go(tmp_path, CASES["A"])
    assert code == 0
    (out / "내메모.txt").write_text("남겨야 함", encoding="utf-8")
    (out / "다른.xlsx").write_text("남겨야 함", encoding="utf-8")
    code, out = go(tmp_path, CASES["L"])
    assert code == 2
    assert (out / "질문.md").exists() and (out / "result.json").exists()
    assert json.loads((out / "result.json").read_text(encoding="utf-8"))["상태"] == "질문"
    assert not (out / "양도소득세_검토.md").exists()
    assert not (out / "양도소득세_계산근거.xlsx").exists()
    assert (out / "내메모.txt").read_text(encoding="utf-8") == "남겨야 함"
    assert (out / "다른.xlsx").exists()


def test_rerun_with_completion_removes_previous_question_file(tmp_path):
    code, out = go(tmp_path, CASES["L"])
    assert code == 2 and (out / "질문.md").exists()
    code, out = go(tmp_path, CASES["A"])
    assert code == 0 and not (out / "질문.md").exists()


def test_rerun_with_rejected_facts_removes_previous_outputs(tmp_path):
    code, out = go(tmp_path, CASES["A"])
    assert code == 0
    f = copy.deepcopy(CASES["A"])
    f["신고인"]["성명"] = "홍길동"
    code, out = go(tmp_path, f)
    assert code == 2
    assert not any((out / n).exists() for n in
                   ("result.json", "질문.md", "양도소득세_검토.md", "양도소득세_계산근거.xlsx"))


def test_unreadable_facts_keeps_previous_outputs(tmp_path):
    """사실관계 파일 경로를 잘못 적은 것만으로 이전 결과를 지우지 않는다."""
    code, out = go(tmp_path, CASES["A"])
    assert code == 0
    assert run.main(["--사실관계", str(tmp_path / "없음.json"), "--출력", str(out)]) == 2
    assert (out / "result.json").exists() and (out / "양도소득세_계산근거.xlsx").exists()
