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


def _stage_files(folder):
    names = outputs.OUTPUT_NAMES + outputs.RETURN_NAMES + ("20261220C116300.01", "내메모.txt", "20261215A103900.01")
    for n in names:
        (folder / n).write_text("x", encoding="utf-8")
    (folder / ".efile-old").mkdir()
    (folder / ".efile-old" / "신고값.json").write_text("{}", encoding="utf-8")
    (folder / "보관").mkdir()
    return names


def test_clear_previous_removes_return_stage_files_too(tmp_path):
    """계산만 다시 돌려도 신고서 단계 파일(신고값, 신고서 PDF, 안내서, 확인 문서, 전자신고 파일, 임시 폴더)을 지운다."""
    _stage_files(tmp_path)
    assert outputs.clear_previous(str(tmp_path)) == []
    assert sorted(os.listdir(tmp_path)) == ["20261215A103900.01", "내메모.txt", "보관"]


def test_clear_previous_order_and_first_error(tmp_path, monkeypatch):
    """제출용 전자신고 파일, 임시 폴더, 신고서 PDF 를 먼저 지우고 통합 문서와 계산 결과는 마지막이다.
    하나가 막혀도 끝까지 지우고 처음 난 OSError 를 다시 낸다."""
    _stage_files(tmp_path)
    seen, real = [], os.remove

    def remove(path):
        name = os.path.basename(os.fspath(path))
        seen.append(name)
        if name in ("20261220C116300.01", outputs.GUIDE):
            raise PermissionError(13, "Permission denied", os.fspath(path))
        real(path)

    monkeypatch.setattr(os, "remove", remove)
    with pytest.raises(PermissionError) as e:
        outputs.clear_previous(str(tmp_path))
    monkeypatch.undo()
    assert os.path.basename(e.value.filename) == "20261220C116300.01"        # 처음 난 오류
    assert seen[0] == "20261220C116300.01"
    pdfs = [i for i, n in enumerate(seen) if n.startswith((outputs.FORM_NATIONAL, outputs.FORM_LOCAL))]
    rest = [i for i, n in enumerate(seen) if n in (outputs.RETURN_VALUES, outputs.GUIDE, outputs.ATTACHMENTS, outputs.CONFIRM)]
    calc_files = [i for i, n in enumerate(seen) if n in outputs.OUTPUT_NAMES]
    assert len(pdfs) == 4 and max(pdfs) < min(rest) and max(rest) < min(calc_files)
    assert seen[min(calc_files)] == outputs.WORKBOOK                         # 계산 결과 가운데서는 통합 문서부터
    assert sorted(os.listdir(tmp_path)) == sorted(["20261220C116300.01", outputs.GUIDE, "20261215A103900.01", "내메모.txt", "보관"])


def test_clear_previous_stops_calculation_files_when_workbook_is_locked(tmp_path, monkeypatch):
    """엑셀이 통합 문서를 열어 두었으면 신고서 단계 파일은 지우고 계산 결과 파일은 그대로 둔다."""
    _stage_files(tmp_path)
    real = os.remove

    def remove(path):
        if os.path.basename(os.fspath(path)) == outputs.WORKBOOK:
            raise PermissionError(13, "Permission denied", os.fspath(path))
        real(path)

    monkeypatch.setattr(os, "remove", remove)
    with pytest.raises(PermissionError):
        outputs.clear_previous(str(tmp_path))
    monkeypatch.undo()
    assert sorted(os.listdir(tmp_path)) == sorted(outputs.OUTPUT_NAMES + ("20261215A103900.01", "내메모.txt", "보관"))


def test_clear_previous_reports_temp_folder_it_could_not_remove(tmp_path, monkeypatch):
    (tmp_path / ".efile-stuck").mkdir()
    monkeypatch.setattr(outputs.shutil, "rmtree", lambda *a, **k: None)
    assert outputs.clear_previous(str(tmp_path)) == [".efile-stuck"]


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
        assert chr(0x2014) not in md
        assert all(not ln.rstrip().endswith("?") for ln in md.splitlines())


# ---- 호별 합산 독립 재계산 (V11) ----
# V10 도 합계의 「호별」 문장을 낸다. 아래 시험은 V10 이 비는 변조만 쓰고 검산 번호 집합이 정확히 {"V11"} 인지 본다.
# 그래야 group_totals 가 비어도 통과하는 시험이 생기지 않는다.

def failures(name, mutate):
    r = calc_result(name)
    mutate(r["계산"])
    return verify.check(r["계산"], CASES[name], RS)


def codes(msgs):
    return {m.split(":")[0].split(" ")[0] for m in msgs}


def only_v11(msgs):
    assert codes(msgs) == {"V11"}, msgs
    assert all("호별" in m for m in msgs), msgs


def test_clean_cases_have_no_group_failure():
    for name in ("A", "BC", "BF", "C", "D", "E", "J", "K", "S1"):
        r = calc_result(name)
        assert not any(m.startswith("V11") for m in r["검산"]), (name, r["검산"])


def test_group_check_alone_catches_national_total():
    """BF 는 호별 합산 세액과 합산 비교 세액이 같아서, 호별 쪽을 1원 낮춰도 산출세액 = max(...) 이 맞아 V10 이 비어 있다."""
    r = calc_result("BF")
    t = r["계산"]["합계"]
    assert t["호별합산세액"] == t["합산비교세액"]
    t["호별합산세액"] -= 1
    only_v11(verify.check(r["계산"], CASES["BF"], RS))


def test_group_check_alone_catches_local_total():
    r = calc_result("BF")
    t = r["계산"]["합계"]
    assert t["지방_호별합산"] == t["지방_합산비교"]
    t["지방_호별합산"] -= 1
    msgs = verify.check(r["계산"], CASES["BF"], RS)
    only_v11(msgs)
    assert any("지방" in m for m in msgs)


def test_group_check_detects_wrong_rate_table():
    def bad_table(c):
        for row in c["세율표"]["국세"]:
            row[2] = "0.99"
    only_v11(failures("BC", bad_table))


def test_group_check_detects_wrong_local_rate_table():
    def bad_table(c):
        for row in c["세율표"]["지방"]:
            row[2] = "0.099"
    msgs = failures("BC", bad_table)
    only_v11(msgs)
    assert all("지방" in m for m in msgs)


def test_group_check_detects_wrong_anchor_rate():
    """묶음 세율은 결과의 적용세율에서 읽는다. 단기 단일세율을 바꾸면 묶음 세액이 달라져 V11 만 걸린다."""
    def bad_rate(c):
        c["자산"][0]["계산"]["적용세율"]["단일"] = "0.50"
    only_v11(failures("C", bad_rate))


def test_group_check_detects_wrong_group_base():
    """두 구성원의 과세표준 합이 묶음 과세표준이다. 한 구성원의 과세표준과 합계 과세표준만 같이 고치면 V11 만 걸린다."""
    def bad_base(c):
        c["자산"][1]["계산"]["과세표준"] += 1_000_000
        c["합계"]["과세표준"] += 1_000_000
        c["자산"][1]["계산"]["양도소득금액"] += 1_000_000   # V4 가 비게 한다
    msgs = failures("BF", bad_base)
    assert "V11" in codes(msgs), msgs


SINGLE_AND_HEAVY = ("C", "E", "J", "D", "K")   # 단기 단일, 미등기 단일, 단기+중과, 중과2, 중과3


@pytest.mark.parametrize("name", SINGLE_AND_HEAVY)
def test_group_check_alone_catches_single_rate_and_heavy_groups(name):
    """합산 비교 세액이 0 인 단일 자산은 산출세액을 같이 올려 V10 을 비우고 호별 합산 세액만 어긋나게 한다."""
    def bump(c):
        c["합계"]["호별합산세액"] += 1
        c["합계"]["산출세액"] += 1
    only_v11(failures(name, bump))


@pytest.mark.parametrize("name", SINGLE_AND_HEAVY)
def test_group_check_alone_catches_local_single_rate_and_heavy_groups(name):
    def bump(c):
        c["합계"]["지방_호별합산"] += 1
        c["합계"]["지방소득세"] += 1
    msgs = failures(name, bump)
    only_v11(msgs)
    assert any("지방" in m for m in msgs)


def test_group_check_runs_on_a_two_member_group():
    r = calc_result("BF")   # B, F 가 기본세율 한 묶음
    assert {a["계산"]["합산묶음"] for a in r["계산"]["자산"]} == {"기본"}
    assert len(r["계산"]["자산"]) == 2
    r["계산"]["합계"]["호별합산세액"] -= 1
    only_v11(verify.check(r["계산"], CASES["BF"], RS))


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
