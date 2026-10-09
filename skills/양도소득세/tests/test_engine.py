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
def test_malformed_values_raise_facts_error(path, value):
    f = copy.deepcopy(CASES["A"])
    f["자산"][0][path] = value
    with pytest.raises(F.FactsError):
        engine.calculate(f, today="2026-10-09")


def test_run_malformed_values_exit_2(tmp_path, capsys):
    f = copy.deepcopy(CASES["A"])
    f["자산"][0]["전체양도가액"] = "1억"
    code, out = go(tmp_path, f)
    assert code == 2 and "사실관계의 값을 처리하지 못했다" in capsys.readouterr().out
