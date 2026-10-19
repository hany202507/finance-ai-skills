# -*- coding: utf-8 -*-
import copy
import json
import os

import pytest

import run
from cases import CASES, EXPECT, EXPECT_TOTAL, addr, asset, facts, house
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
    assert r["다루지않음"] == [{"자산": "A", "내용": 문구, "계획": "미정"}]


def test_unsupported_plan_defaults_to_undecided_and_mixed_years_has_none():
    """계획을 주지 않은 Unsupported 는 「미정」이다(어느 계획에 든 항목인지 밝히지 않으면 계획 5 라고 답하지 않는다)."""
    from yangdo import calc, return_values
    assert calc.Unsupported("x").계획 == "미정" and calc.Unsupported("x", 계획="없음").계획 == "없음"
    assert return_values.Unsupported("x").계획 == "미정" and return_values.Unsupported("x", "5").계획 == "5"
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


@pytest.mark.parametrize("today", ["20261115", "2026-W46-7", "2026-11-15T10:00", "2026-1-5", "2026-02-30", "2026-13-01"])
def test_run_today_argument_takes_only_yyyy_mm_dd(tmp_path, today):
    """파이썬 3.11 이상의 date.fromisoformat 은 붙여 쓴 날짜를 받는다. 3.10 과 같은 입력에 같은 결과를 내도록 dates.to_date 로 읽는다."""
    with pytest.raises(SystemExit):
        go(tmp_path, CASES["A"], "--오늘", today)


def test_run_today_argument_is_read_by_the_shared_date_reader():
    assert run._iso_date("2026-11-15") == "2026-11-15"
    assert "fromisoformat" not in open(run.__file__, encoding="utf-8").read()


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


# 출력 쓰기 실패는 종료코드 4. 1 은 검산 실패 전용이다.

def _err_lines(capsys):
    """stderr 의 줄. 검산 재계산 라이브러리(formulas)가 찍는 진행 막대(tqdm)는 이 스크립트의 출력이 아니라서 뺀다."""
    err = capsys.readouterr().err
    assert "Traceback" not in err
    return [ln for ln in err.splitlines() if ln.strip() and "it/s" not in ln and "s/it" not in ln]


def test_exit_codes_documented():
    assert "4 출력 파일 쓰기 실패" in run.__doc__ and "1 검산 실패" in run.__doc__


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


def test_rerun_with_rejected_facts_removes_previous_outputs(tmp_path):
    code, out = go(tmp_path, CASES["A"])
    assert code == 0
    f = copy.deepcopy(CASES["A"])
    f["신고인"]["성명"] = "홍길동"
    code, out = go(tmp_path, f)
    assert code == 2
    assert not any((out / n).exists() for n in
                   ("result.json", "질문.md", "양도소득세_검토.md", "양도소득세_계산근거.xlsx"))


def test_engine_notes_and_warnings_come_from_judge_once():
    """판정의 확인사항·경고를 엔진이 한 번만 받는다(자산 번호가 앞에 붙고 겹치지 않는다)."""
    r = calc("D")
    assert len(set(r["확인사항"])) == len(r["확인사항"]) and len(set(r["경고"])) == len(r["경고"])
    assert any(m.startswith("D: ") and "제167조의10①10호" in m for m in r["확인사항"])
    assert [w for w in r["경고"] if w.startswith("D: ")] and any("계류" in w for w in r["경고"])


# ---- 최종 검토 반영: 모양이 틀린 주택 목록은 역추적 없이 H04 로 되묻고, 종료코드 2 ------------------
BAD_HOUSE_LISTS = [{"H1": 1}, ["H1"], "H1", [1], [[]]]


@pytest.mark.parametrize("bad", BAD_HOUSE_LISTS)
def test_malformed_house_list_asks_h04(bad):
    f = copy.deepcopy(CASES["A"])
    f["세대"]["주택목록"] = bad
    r = engine.calculate(f, today="2026-10-09")
    assert r["상태"] == "질문" and any(q["문항"] == "H04" for q in r["질문"])


def test_engine_wraps_attribute_and_index_errors(monkeypatch):
    """prepare 안에서 AttributeError 나 IndexError 가 나도 FactsError 로 바꾼다."""
    for exc in (AttributeError("'str' object has no attribute 'get'"), IndexError("list index out of range")):
        def boom(f, exc=exc):
            raise exc
        monkeypatch.setattr(F, "prepare", boom)
        with pytest.raises(F.FactsError) as e:
            engine.calculate(copy.deepcopy(CASES["A"]), today="2026-10-09")
        assert type(exc).__name__ in str(e.value)


@pytest.mark.parametrize("bad", ["20261009", "2026-W41-5", "내일", "2026-10-9"])
def test_engine_today_must_be_iso(bad):
    """오늘 날짜도 YYYY-MM-DD 글자만 받는다. 파이썬 3.11 이상에서만 통하던 형식을 막는다."""
    with pytest.raises(F.FactsError):
        engine.calculate(copy.deepcopy(CASES["A"]), today=bad)


@pytest.mark.parametrize("path", ["양도", "취득"])
def test_compact_dates_in_facts_are_asked_not_calculated(path):
    f = copy.deepcopy(CASES["A"])
    f["자산"][0][path]["잔금일"] = "20261115" if path == "양도" else "20141101"
    r = engine.calculate(f, today="2026-10-09")
    assert r["상태"] == "질문" and r["계산"] is None
    assert any("YYYY-MM-DD" in q["내용"] for q in r["질문"])


def test_compact_residence_dates_are_asked_not_calculated():
    f = copy.deepcopy(CASES["A"])
    f["자산"][0]["거주기간"] = [["20141101", "20261115"]]
    r = engine.calculate(f, today="2026-10-09")
    assert r["상태"] == "질문" and [q["문항"] for q in r["질문"]] == ["H07"]


def test_run_stderr_has_no_progress_bar(tmp_path, capsys):
    """검산용 재계산 라이브러리(formulas)의 진행 막대가 표준오류에 찍히지 않는다."""
    code, _ = go(tmp_path, CASES["A"])
    err = capsys.readouterr().err
    assert code == 0
    assert "it/s" not in err and "%|" not in err and "\r" not in err and err.strip() == ""


def _case_a_with_residence(periods):
    f = copy.deepcopy(CASES["A"])
    f["자산"][0]["거주기간"] = periods
    return engine.calculate(f, today="2026-10-09")


def test_duplicate_residence_period_gives_same_result_as_one():
    """같은 거주 구간을 두 번 적어도 거주 햇수는 늘지 않는다(이전에는 1년이 2년이 되어 표2 를 받았다)."""
    one_year = ["2014-11-01", "2015-11-01"]
    once = _case_a_with_residence([one_year])
    twice = _case_a_with_residence([one_year, list(one_year)])
    for r in (once, twice):
        assert r["상태"] == "완료" and r["검산"] == []
        v = r["계산"]["자산"][0]["판정"]
        assert (v["거주년"], v["장특공"]) == (1, "표1")
    assert twice["계산"]["합계"] == once["계산"]["합계"]
    assert twice["계산"]["자산"][0]["계산"] == once["계산"]["자산"][0]["계산"]


def test_overlapping_residence_periods_use_the_union():
    full = _case_a_with_residence([["2014-11-01", "2026-11-15"]])
    overlapped = _case_a_with_residence([["2014-11-01", "2026-11-15"], ["2016-01-01", "2020-01-01"], ["2014-11-01", "2026-11-15"]])
    assert overlapped["계산"]["합계"] == full["계산"]["합계"]
    assert overlapped["계산"]["자산"][0]["판정"]["거주년"] == 12 == full["계산"]["자산"][0]["판정"]["거주년"]


SECRET = "ZZ비밀값ZZ"


@pytest.mark.parametrize("name", ["K", "S1", "BF", "G"])
@pytest.mark.parametrize("path,qid", [(("주거사용개시일",), "A05"), (("양도", "계약일"), "A09"), (("양도", "계약금수령일"), "A10")])
def test_optional_date_keys_with_a_bad_format_are_asked_again_and_the_value_stays_out_of_the_text(name, path, qid):
    """주거사용개시일, 양도.계약일, 양도.계약금수령일 의 형식이 틀리면 예외 문장 대신 그 문항 질문으로 돌린다. 값은 어디에도 싣지 않는다."""
    f = copy.deepcopy(CASES[name])
    d = f["자산"][0]
    for k in path[:-1]:
        d = d.setdefault(k, {})
    d[path[-1]] = SECRET
    r = engine.calculate(f, today="2026-10-09")
    assert r["상태"] == "질문" and [q["문항"] for q in r["질문"]] == [qid] and SECRET not in json.dumps(r, ensure_ascii=False)


def test_malformed_facts_message_names_only_the_exception_type():
    """엔진이 형식 오류를 알리는 문장에 예외 문장(사실관계 값이 들어 있을 수 있다)을 싣지 않는다."""
    e = engine._malformed(ValueError("날짜는 YYYY-MM-DD 글자로 적어야 합니다: '%s'" % SECRET))
    assert isinstance(e, F.FactsError) and SECRET not in str(e) and "ValueError" in str(e)


def test_value_error_raised_while_judging_does_not_reach_the_message(monkeypatch):
    from yangdo import judge

    def boom(*a, **k):
        raise ValueError("값 %s" % SECRET)
    monkeypatch.setattr(judge, "judge", boom)
    with pytest.raises(F.FactsError) as e:
        engine.calculate(copy.deepcopy(CASES["S1"]), today="2026-10-09")
    assert SECRET not in str(e.value) and "ValueError" in str(e.value)


def test_sold_house_linked_by_asset_id_only():
    """판 집을 주택 목록에 id 와 자산id 로만 적어도 계산한다. 시연 사례에서 「사실관계의 값을 처리하지 못했다(KeyError)」로 멈췄다."""
    아현 = addr("서울특별시", "마포구", "아현동")

    def case(sold_house):
        a = asset("A", "주택", 아현, "2019-04-10", "2026-09-25", 1_100_000_000, 700_000_000,
                  양도__계약일="2026-06-20", 양도__계약금수령일="2026-06-20",
                  기준시가={"취득": {"주택": 500_000_000}, "양도": {"주택": 800_000_000}})
        return facts([a], [sold_house, house("H2", addr("경기도", "고양시 일산동구", "장항동"), "2015-06-01")])
    bare = engine.calculate(case({"id": "H1", "자산id": "A"}), today="2026-10-09")
    full = engine.calculate(case(house("H1", 아현, "2019-04-10", 자산id="A")), today="2026-10-09")
    assert bare["상태"] == "완료" and bare["검산"] == [], bare.get("질문")
    assert bare["계산"]["합계"]["산출세액"] == full["계산"]["합계"]["산출세액"] > 0
