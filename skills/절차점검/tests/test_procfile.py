"""절차점검. 조서 파일 하나로 절차 줄 · 판정 검사 · 점검표 · 고른 줄 옮기기."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import make_procfile_sample as sample  # noqa: E402
from audit import procfile as pf  # noqa: E402
from audit import procrules as R  # noqa: E402

WP = sample.WP


@pytest.fixture
def clean(tmp_path):
    return sample.build(tmp_path / "clean")


@pytest.fixture
def defect(tmp_path):
    return sample.build(tmp_path / "defect", defect=True)


def _ok(n: int, cite: str) -> dict:
    return {"key": n, "verdict": "수행됨", "cites": [cite]}


def _defect_patch() -> dict:
    """결함 넷을 짚은 판정. 절차 줄은 8개(특수관계자 줄이 없다)."""
    return {"workpaper": WP, "verdicts": [
        _ok(1, "C10 총괄!A2:G3"), _ok(2, "C20 명세!A2:F17"),
        {"key": 3, "verdict": "수행 부족", "missing": "증거: 조회 3곳이 회신 없이 대체 절차도 없음", "cites": ["C30 조회!D11:H13"]},
        _ok(4, "C20 명세!B2:E16"),
        {"key": 5, "verdict": "일부 빠짐", "missing": "1년 초과 구간의 설정률과 결론 칸이 빈칸", "cites": ["C50 충당금!C5", "C50 충당금!B9"]},
        _ok(6, "C60 기간귀속!A2:F11"),
        {"key": 7, "verdict": "사유 어긋남", "missing": "명세에 USD 거래처가 있음", "cites": ["C20 명세!B3"]},
        _ok(8, "C90 주석!A2:D4"),
        {"part": "영역", "key": "C-8 특수관계자 채권", "verdict": "수행 기록 없음", "missing": "감사프로그램에 특수관계자 채권 절차 줄이 없음",
         "cites": ["C20 명세!D8"]}],
        "coverage": {"C-1": [1], "C-2": [2], "C-3": [3], "C-4": [4], "C-5": [5], "C-6": [6], "C-7": [7], "C-8": [], "C-9": [8]}}


def _reject(path, layout, patch, **k) -> str:
    with pytest.raises(R.Rejected) as e:
        pf.accept(path, layout, patch, **k)
    return "\n".join(e.value.problems)


def test_scan_guesses_table_and_rows_read_states(defect):
    sc = pf.scan(defect)
    cand = next(c for c in sc["candidates"] if c["sheet"] == "감사프로그램")
    assert (cand["first_row"], cand["last_row"], cand["step"], cand["applies"], cand["result"]) == (5, 12, "B", "C", "F")
    assert "4000C" in sc["defined_areas"]
    v = pf.view(defect, sample.layout(True))
    assert [r["n"] for r in v["rows"]] == list(range(1, 9)) and not v["range_problems"]
    assert v["rows"][0]["state"] == R.DONE and v["rows"][6]["state"] == R.NA
    assert any("사유가" in f for f in v["rows"][6]["flags"])                 # 「외화 채권 없음」 은 15자 미만
    assert v["defined"] and [p["id"] for p in v["area_points"]][0] == "C-1"
    assert v["status"]["check"] == R.NEVER


def test_accept_writes_next_to_workpaper_and_leaves_it_alone(defect):
    before = R.sha(defect)
    rec = pf.accept(defect, sample.layout(True), _defect_patch(), now="2026-01-30 10:00")
    assert R.sha(defect) == before
    assert rec["counts"] == {"rows": 8, "todo": 4, "ok": 5, "skipped": 0, "fixed": 0, "unknown": 0, "area": 1}
    sheet = defect.with_name("절차점검_매출채권_조서.xlsx")
    ws = load_workbook(sheet)[R.SHEET]
    assert ws.cell(R.HEAD_ROW + 1, 2).value == "C-8 특수관계자 채권" and ws.cell(R.HEAD_ROW + 2, 3).value == "수행 부족"
    text = "\n".join(str(c.value) for row in ws.iter_rows() for c in row if c.value)
    assert "범위는 AI 가 정했습니다" in text and "C-8 특수관계자 채권: 조서에 절차 줄 없음" in text
    assert "00 받은자료" not in rec["deps"] and rec["coverage"]["C-9"] == ["감사프로그램!12"]
    assert pf.status(defect)["check"] == R.FRESH


def test_reject_missing_verdict_unknown_key_and_cover_only_cite(defect):
    p = _defect_patch()
    p["verdicts"] = p["verdicts"][1:]
    assert "판정이 없는 절차 줄 1개" in _reject(defect, sample.layout(True), p)
    p = _defect_patch()
    p["verdicts"][0] = {"key": "없는 줄", "verdict": "수행됨", "cites": ["C10 총괄!A2"]}
    assert "절차 표에 없는 절차" in _reject(defect, sample.layout(True), p)
    p = _defect_patch()
    p["verdicts"][0] = _ok(1, "감사프로그램!F5")                            # 절차 표 안의 「수행 결과」 글만 근거로 든다
    assert "절차 표 범위 밖의 수행 칸" in _reject(defect, sample.layout(True), p)
    p["verdicts"][0] = _ok(1, "감사프로그램!F5:F15")                         # 표 안의 글에 바깥 빈칸을 붙여도 절차 표로 본다
    assert "절차 표 범위 밖의 수행 칸" in _reject(defect, sample.layout(True), p)
    p["verdicts"][0] = _ok(1, "감사프로그램!B15")                           # 같은 시트라도 절차 표와 겹치지 않으면 받는다
    pf.accept(defect, sample.layout(True), p)


def test_range_next_to_table_must_be_included_or_excluded(defect):
    lay = sample.layout(True)
    lay["tables"][0]["last_row"] = 11                                       # 마지막 절차 줄을 범위에서 뺐다
    p = _defect_patch()
    p["verdicts"] = [x for x in p["verdicts"] if x.get("key") != 8]
    p["coverage"]["C-9"] = [7]
    assert "가까이의 행 12" in _reject(defect, lay, p)
    lay["tables"][0]["excluded"] = {"12": "x"}
    assert "뺀 까닭(2자 이상)" in _reject(defect, lay, p)
    lay = sample.layout(True)
    del lay["tables"][0]["head_row"]                                        # 머리글 행도 적지 않으면 가까운 행으로 잡힌다
    del lay["tables"][0]["excluded"]                                        # 빈 행 둘을 건너 있는 결론 줄
    msg = _reject(defect, lay, _defect_patch())
    assert "가까이의 행 4, 15" in msg


def test_coverage_rules(defect):
    lay = sample.layout(True)
    p = _defect_patch()
    del p["coverage"]
    assert "coverage(절차 번호" in _reject(defect, lay, p)
    p = _defect_patch()
    del p["coverage"]["C-4"]
    p["coverage"]["C-99"] = [1]
    msg = _reject(defect, lay, p)
    assert "coverage 에 C-4 가 없습니다" in msg and "정의에 없는 절차 번호가 있습니다: C-99" in msg
    p = _defect_patch()
    p["verdicts"] = p["verdicts"][:-1]                                      # 빈 대응인데 영역 줄이 없다
    assert "coverage C-8 가 빈 목록입니다" in _reject(defect, lay, p)
    p = _defect_patch()
    p["verdicts"][-1]["key"] = "C-80 특수관계자"                            # 번호 앞머리만 같은 이름은 받지 않는다
    assert "coverage C-8 가 빈 목록입니다" in _reject(defect, lay, p)
    p = _defect_patch()
    p["verdicts"][-1].update(verdict="판단 못 함", cites=[])                # 조서에 없는 절차는 「수행 기록 없음」 으로만 남긴다
    assert "coverage C-8 가 빈 목록입니다" in _reject(defect, lay, p)
    p = _defect_patch()
    p["coverage"].update({"C-2": [1], "C-4": [1], "C-6": [1]})              # 줄 하나를 네 절차에 댄다
    assert "절차 번호 4개" in _reject(defect, lay, p)
    p = _defect_patch()
    p["coverage"]["C-1"] = [99]
    assert "절차 표에 없는 줄입니다: 99" in _reject(defect, lay, p)


def test_applies_words_are_read_only_when_exact():
    s = pf._state
    assert s("해당 없음", True, "")[0] == R.NA and s("N/A", True, "")[0] == R.NA and s("해당없음(외화 없음)", True, "")[0] == R.NA
    assert s("해당", True, "")[0] == R.DONE and s(" y ", True, "")[0] == R.DONE and s("해당: 조회", True, "")[0] == R.DONE
    for v in ("Not applicable", "X-ray", "해당 사항 검토 중", "Original", "N.A"):
        state, flag = s(v, True, "")
        assert state == R.OPEN and "읽지 못함" in flag, v
    assert s(True, True, "")[0] == R.OPEN and "참 · 거짓" in s(True, True, "")[1]
    assert s(None, True, "글") == (R.OPEN, None)
    assert s(None, False, "수행함")[0] == R.DONE and s(None, False, "")[0] == R.OPEN


def test_continuation_rows_formula_without_value_and_excluded(clean):
    wb = load_workbook(clean)
    ws = wb["감사프로그램"]
    ws.insert_rows(8)                                                       # 3번 절차 아래에 수행 결과가 한 줄 더 있다
    ws["F8"] = "미회신 없음"
    ws["C5"] = "=IF(1=1,\"Y\",\"N\")"                                       # 계산값이 저장되지 않은 수식
    ws.insert_rows(11)
    ws["B11"] = "(소계)"
    wb.save(clean)
    lay = {"area": "4000C", "tables": [{"sheet": "감사프로그램", "head_row": 4, "first_row": 5, "last_row": 15, "step": "B", "applies": "C",
                                        "result": "F", "excluded": {"11": "소계 줄", "18": "결론 줄"}}]}
    v = pf.view(clean, lay)
    assert len(v["rows"]) == 9 and "8행: 절차 열은 비었는데" in v["range_problems"][0]      # 이어진 행이라고 적지 않으면 잇지 않는다
    lay["tables"][0]["continued"] = [8]
    v = pf.view(clean, lay)
    assert len(v["rows"]) == 9 and not v["range_problems"]
    r3 = v["rows"][2]
    assert r3["cont_rows"] == [8] and r3["result"].endswith("미회신 없음") and any("이었음" in f for f in r3["flags"])
    assert v["rows"][0]["state"] == R.OPEN and any("계산값이 없음" in f for f in v["rows"][0]["flags"])
    with pytest.raises(R.Rejected) as e:
        pf.view(clean, {"area": "4000C", "tables": [{"sheet": "없는 시트", "first_row": 1, "last_row": 2, "step": "B"}]})
    assert "조서에 없는 시트" in e.value.problems[0]


def test_cites_to_other_workpaper_and_received_files(defect, tmp_path):
    lay = sample.layout(True)
    other = sample.build(tmp_path / "other")
    p = _defect_patch()
    p["verdicts"][0]["cites"] = ["총괄=bad:C10 총괄!A2"]
    assert "근거의 시트가" in _reject(defect, lay, p, also=[f"매출={other}"])
    p["verdicts"][0]["cites"] = ["매출:C10 총괄!A2"]
    p["verdicts"][6]["cites"] = ["받은자료:거래처별_채권명세.xlsx#채권명세", "C20 명세!B3"]
    rec = pf.accept(defect, lay, p, also=[f"매출={other}"])
    assert other.resolve().as_posix() in rec["deps"] and "00 받은자료/거래처별_채권명세.xlsx" in rec["deps"]
    p["verdicts"][6]["cites"] = ["받은자료:../매출채권_조서.xlsx"]
    assert "아래에 없습니다" in _reject(defect, lay, p, also=[f"매출={other}"])
    assert "이름을 근거에 쓸 수 없습니다" in _reject(defect, lay, _defect_patch(), also=[f"a:b={other}"])
    (defect.parent / "00 받은자료" / "거래처별_채권명세.xlsx").write_bytes(b"changed")
    assert pf.status(defect)["check"] == R.STALE


def test_apply_moves_only_picked_rows_and_refuses_stale(defect):
    lay = sample.layout(True)
    pf.accept(defect, lay, _defect_patch(), now="2026-01-30 10:00")
    sheet = defect.with_name("절차점검_매출채권_조서.xlsx")
    with pytest.raises(R.Rejected):
        pf.apply(defect, "AI")
    assert pf.apply(defect, "박검토")["moved"] == []
    wb = load_workbook(sheet)
    wb[R.SHEET].cell(R.HEAD_ROW + 2, 6, "예")
    wb.save(sheet)
    out = pf.apply(defect, "박검토", now="2026-01-30 11:00")
    assert out["moved"] == [2] and out["left"] == [1, 3, 4]
    review = defect.with_name("검토의견_매출채권_조서.xlsx")
    ws = load_workbook(review).worksheets[0]
    assert ws.cell(4, 5).value == "열림" and "수행 부족" in ws.cell(4, 2).value and ws.cell(4, 3).value.startswith("증거:")
    wb = load_workbook(sheet)                                               # 앞 실행이 기록만 쓰고 끊겨 점검표의 반영 결과가 비었다
    wb[R.SHEET].cell(R.HEAD_ROW + 2, 7, None)
    wb.save(sheet)
    assert pf.apply(defect, "박검토", picks=[2, 3])["moved"] == [3]         # 이미 옮긴 줄은 두 번 쓰지 않는다
    assert "반영함" in load_workbook(sheet)[R.SHEET].cell(R.HEAD_ROW + 2, 7).value
    assert load_workbook(review).worksheets[0].max_row == 5
    rec = json.loads(defect.with_name("절차점검_매출채권_조서.json").read_text(encoding="utf-8"))
    assert [x["n"] for x in rec["items"] if x["applied"]] == [2, 3]
    rec2 = pf.accept(defect, lay, _defect_patch())                          # 같은 판정으로 다시 점검하면 반영 기록이 이어진다
    assert [x["n"] for x in rec2["items"] if x["applied"]] == [2, 3]
    wb = load_workbook(defect)
    wb["C30 조회"]["H11"] = "대체 절차 수행"
    wb.save(defect)
    assert pf.status(defect)["check"] == R.STALE
    with pytest.raises(R.Rejected) as e:
        pf.apply(defect, "박검토", picks=[1])
    assert "점검을 다시 돌린 뒤" in e.value.problems[0]


def test_area_without_definition_checks_only_listed_rows(clean):
    lay = sample.layout(False)
    lay["area"] = "4000P"
    cites = ["C10 총괄!A2:G3", "C20 명세!A2:F17", "C30 조회!A2:H13", "C20 명세!B2:E16", "C50 충당금!A2:F9", "C60 기간귀속!A2:F11",
             None, "C20 명세!A19:B20", "C90 주석!A2:D4"]
    vs = [{"key": n, "verdict": "사유 맞음", "cites": ["C20 명세!B2:B16"]} if c is None else _ok(n, c) for n, c in enumerate(cites, 1)]
    assert "coverage 를 받지 않습니다" in _reject(clean, lay, {"workpaper": WP, "verdicts": vs, "coverage": {"C-1": [1]}})
    rec = pf.accept(clean, lay, {"workpaper": WP, "verdicts": vs})
    assert rec["counts"]["todo"] == 0 and not rec["defined"]
    ws = load_workbook(clean.with_name(rec["file"]))[R.SHEET]
    text = "\n".join(str(c.value) for row in ws.iter_rows() for c in row if c.value)
    assert "볼 것 없음" in text and "확인 항목 정의가 없습니다" in text


def test_cli(defect, tmp_path, capsys):
    from run import main

    lay, ver = tmp_path / "layout.json", tmp_path / "verdicts.json"
    lay.write_text(json.dumps(sample.layout(True), ensure_ascii=False), encoding="utf-8")
    ver.write_text(json.dumps(_defect_patch(), ensure_ascii=False), encoding="utf-8")
    assert main(["procfile", "scan", str(defect)]) == 0 and "절차 표 후보" in capsys.readouterr().out
    assert main(["procfile", "rows", str(defect), "--layout", str(lay), "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert len(out["rows"]) == 8 and out["verdicts"] == list(R.VERDICTS) and "path" not in out
    assert main(["procfile", "check", str(defect), "--layout", str(lay), "--verdicts", str(ver)]) == 0
    assert "볼 것 3줄" in capsys.readouterr().out
    bad = _defect_patch()
    bad["verdicts"][2]["missing"] = "증거: 3곳 412,500,000원 미회신"
    ver.write_text(json.dumps(bad, ensure_ascii=False), encoding="utf-8")
    assert main(["procfile", "check", str(defect), "--layout", str(lay), "--verdicts", str(ver)]) == 1
    assert "금액으로 보이는 숫자" in capsys.readouterr().out
    assert main(["procfile", "apply", str(defect), "--who", "박검토", "--pick", "1"]) == 0
    assert main(["procfile", "status", str(defect)]) == 0 and "최신" in capsys.readouterr().out
    assert main(["procfile", "scan", str(tmp_path / "없음.xlsx")]) == 1
