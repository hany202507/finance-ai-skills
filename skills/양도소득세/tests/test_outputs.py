# -*- coding: utf-8 -*-
"""출력 함수(outputs), 호별 합산 독립 검산, 판정표의 조정대상지역 줄."""
import copy
import json
import os

import pytest

import mcp_server
import run
from cases import CASES
from yangdo import calc, engine, outputs, ruleset, verify

TODAY = "2026-10-11"
RS = ruleset.load()
ROW = "| 조정대상지역(취득일 · 양도일) |"


def calc_result(name):
    return engine.calculate(copy.deepcopy(CASES[name]), today=TODAY)


def test_review_shows_regulated_area_row():
    r = engine.calculate(CASES["S1"], today="2026-10-11")
    md = outputs.review_md(r)
    assert "| 조정대상지역(취득일 · 양도일) | 예 · 예 |" in md


def test_verify_recomputes_group_tax_independently():
    r = engine.calculate(CASES["BC"], today="2026-10-11")
    res = r["계산"]
    res["합계"]["호별합산세액"] += 1
    assert any("호별" in m for m in verify.check(res, CASES["BC"], ruleset.load()))


def test_run_and_mcp_share_outputs(tmp_path):
    assert run.write_outputs is outputs.write_outputs and run.review_md is outputs.review_md
    mcp_server.call_tool("yangdo_calculate", {"facts": CASES["A"], "out_dir": str(tmp_path / "m"), "오늘": "2026-10-09"})
    assert set(os.listdir(tmp_path / "m")) == {outputs.RESULT, outputs.REVIEW, outputs.WORKBOOK}


def test_run_reexports_every_moved_name():
    for name in ("won", "cell", "questions_md", "review_md", "clear_previous", "write_outputs",
                 "RESULT", "QUESTIONS", "REVIEW", "WORKBOOK", "OUTPUT_NAMES", "TAIL"):
        assert getattr(run, name) is getattr(outputs, name), name
    assert outputs.OUTPUT_NAMES == (outputs.RESULT, outputs.QUESTIONS, outputs.REVIEW, outputs.WORKBOOK)


def test_mcp_server_uses_outputs_not_run_copies():
    src = open(mcp_server.__file__, encoding="utf-8").read()
    assert "import run" not in src and "RUN." not in src
    assert mcp_server.outputs is outputs


def test_write_outputs_question_and_done(tmp_path):
    q = engine.calculate({"자산": []}, today=TODAY)
    paths = outputs.write_outputs(q, str(tmp_path / "q"))
    assert [os.path.basename(p) for p in paths] == [outputs.RESULT, outputs.QUESTIONS]
    done = calc_result("A")
    paths = outputs.write_outputs(done, str(tmp_path / "d"))
    assert [os.path.basename(p) for p in paths] == [outputs.RESULT, outputs.REVIEW]   # 워크북은 engine 이 쓴다
    with open(paths[0], encoding="utf-8") as f:
        assert json.load(f)["상태"] == "완료"


def test_clear_previous_removes_only_own_files(tmp_path):
    for n in outputs.OUTPUT_NAMES + ("내메모.txt",):
        (tmp_path / n).write_text("x", encoding="utf-8")
    outputs.clear_previous(str(tmp_path))
    assert os.listdir(tmp_path) == ["내메모.txt"]


def test_regulated_area_row_only_for_houses():
    r = calc_result("BF")   # 주택 B + 토지 F
    kinds = {a["id"]: a["판정"]["종류"] for a in r["계산"]["자산"]}
    assert kinds == {"B": "주택", "F": "토지"}
    md = outputs.review_md(r)
    assert md.count(ROW) == 1
    house, land = md.split("## 자산 F")[0], "## 자산 F" + md.split("## 자산 F")[1]
    assert ROW in house and ROW not in land


def test_regulated_area_row_shows_each_date_separately():
    r = calc_result("S1")
    v = r["계산"]["자산"][0]["판정"]
    v["조정_취득일"]["지정"] = False
    assert "%s 아니오 · 예 |" % ROW in outputs.review_md(r)
    v["조정_양도일"]["지정"] = False
    assert "%s 아니오 · 아니오 |" % ROW in outputs.review_md(r)


def test_regulated_area_row_says_not_applicable_when_missing():
    r = calc_result("S1")
    v = r["계산"]["자산"][0]["판정"]
    v["조정_취득일"], v["조정_양도일"] = {"지정": None}, None   # 지정 값이 없거나 판정이 비어 있는 경우(미등기 주택 등)
    assert "%s 해당 없음 · 해당 없음 |" % ROW in outputs.review_md(r)


def test_review_has_no_forbidden_style():
    for name in ("A", "S1", "BC", "BF"):
        md = outputs.review_md(calc_result(name))
        assert "—" not in md
        assert all(not ln.rstrip().endswith("?") for ln in md.splitlines())


# ---- 호별 합산 독립 재계산 ----

def failures(name, mutate):
    r = calc_result(name)
    mutate(r["계산"])
    return verify.check(r["계산"], CASES[name], RS)


def test_clean_cases_have_no_group_failure():
    for name in ("A", "BC", "BF", "C", "D", "E", "J", "K", "S1"):
        r = calc_result(name)
        assert not any("호별" in m for m in r["검산"]), (name, r["검산"])


def test_group_check_detects_local_group_total():
    msgs = failures("BC", lambda c: c["합계"].__setitem__("지방_호별합산", c["합계"]["지방_호별합산"] + 10))
    assert any("호별" in m and "지방" in m for m in msgs)


def test_group_check_detects_wrong_rate_table():
    def bad_table(c):
        for row in c["세율표"]["국세"]:
            row[2] = "0.99"
    assert any("호별" in m for m in failures("BC", bad_table))


def test_group_check_runs_on_a_two_member_group():
    r = calc_result("BF")   # B, F 가 기본세율 한 묶음
    assert {a["계산"]["합산묶음"] for a in r["계산"]["자산"]} == {"기본"}
    r["계산"]["합계"]["호별합산세액"] -= 1
    assert any("호별" in m for m in verify.check(r["계산"], CASES["BF"], RS))


def test_group_check_covers_single_rate_and_heavy_groups():
    for name in ("C", "E", "J", "D", "K"):   # 단기 단일, 미등기 단일, 단기+중과, 중과2, 중과3
        r = calc_result(name)
        r["계산"]["합계"]["호별합산세액"] += 1
        assert any("호별" in m for m in verify.check(r["계산"], CASES[name], RS)), name


def test_group_check_ignores_fully_exempt_assets():
    r = calc_result("G")   # 전액비과세라 합산묶음이 None
    assert r["계산"]["자산"][0]["계산"]["합산묶음"] is None
    assert r["검산"] == []


def test_group_check_does_not_call_calc(monkeypatch):
    r = calc_result("BC")["계산"]

    def boom(*a, **k):
        raise AssertionError("calc 를 부르면 안 된다")
    for fn in ("progressive", "rate_tax", "rates", "merge_key", "group_anchor", "floor"):
        monkeypatch.setattr(calc, fn, boom)
    assert verify.group_totals(r) == []


def test_group_check_uses_earliest_member_rate_basis():
    """묶음 세율의 기준은 가장 이른 양도일 구성원이다(입력 순서와 상관없다)."""
    r = calc_result("BC")["계산"]
    r["자산"].reverse()
    assert verify.group_totals(r) == []


def test_group_check_does_not_mutate_result():
    r = calc_result("BC")["계산"]
    before = copy.deepcopy(r)
    verify.group_totals(r)
    assert r == before


@pytest.mark.parametrize("name", ["A", "BC", "BF", "K", "S1"])
def test_group_totals_matches_engine(name):
    r = calc_result(name)["계산"]
    assert verify.group_totals(r) == []
