"""표준조서: 자료 폴더 하나로 정산표와 계정별 표준조서를 만든다.
자료는 examples/모의자료 의 가상 회사 가온정밀(가상) 파일이다(실제 자료 아님). 엑셀 없이 엔진의 수식 계산기(xlcalc)로 검산한다."""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

import pytest
from openpyxl import load_workbook

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
EXAMPLE = HERE.parent / "examples" / "모의자료"
sys.path.insert(0, str(SCRIPTS))

import run  # noqa: E402  (공개판 갈림 stdmode.STANDALONE 을 켠다)
from audit import stdmode, stdwp  # noqa: E402
from audit.workpapers.xlcalc import Calc  # noqa: E402

CO, FY = "가온정밀(가상)", "2025-12-31"


def _copy(tmp: Path, name: str) -> Path:
    dst = tmp / name
    shutil.copytree(EXAMPLE, dst)
    return dst


def _folder(src: Path) -> Path:
    return run._find(src)


@pytest.fixture(scope="module")
def made(tmp_path_factory):
    src = _copy(tmp_path_factory.mktemp("std"), "자료")
    assert run.main(["make", str(src), "--company", CO, "--fy-end", FY, "--pm", "60000000", "--risk", "보통"]) == 0
    return src


@pytest.fixture
def src(made, tmp_path):
    dst = tmp_path / "자료"
    shutil.copytree(made, dst)
    return dst


def _text(path: Path, skip=("정산표", "_표준")) -> str:
    wb = load_workbook(path)
    try:
        return "\n".join(str(v) for ws in wb.worksheets if ws.title not in skip
                         for row in ws.iter_rows(values_only=True) for v in row if isinstance(v, str))
    finally:
        wb.close()


def test_standalone_flag_is_on():
    assert stdmode.STANDALONE is True


def test_make_writes_wtb_and_workpapers(made):
    d = _folder(made)
    assert d.name == f"표준조서_{FY} 기말감사"
    assert (d / "8000 감사완결" / "8100B_정산표.xlsx").is_file()
    files = sorted(p.name for p in (d / "4000 계정별" / "표준조서").glob("*_표준.xlsx"))
    assert "4000C_매출채권_표준.xlsx" in files and len(files) >= 10
    case = json.loads((d / "_색인" / "감사건.json").read_text(encoding="utf-8"))
    assert case["std"] == {"performance": 60000000, "risk": "보통"}


def test_wtb_checks_are_zero(made):
    p = _folder(made) / "8000 감사완결" / "8100B_정산표.xlsx"
    wb = load_workbook(p)
    ws = wb["재무제표"]
    row = next(r for r in range(1, ws.max_row + 1) if str(ws.cell(r, 1).value or "").startswith("검산: 자산 − 부채 − 자본"))
    wa = wb["계정별"]
    tot = next(r for r in range(1, wa.max_row + 1) if str(wa.cell(r, 2).value or "").startswith("합계"))
    wb.close()
    c = Calc(p)
    assert c.cell("재무제표", f"C{row}") == 0 and c.cell("재무제표", f"D{row}") == 0
    assert c.cell("계정별", f"G{tot}") == 0


def test_lead_ties_and_4000c_feeds(made):
    res = {x["code"]: x for x in stdwp.check(_folder(made))}
    assert all(not x["diff"] for x in res.values()), [x["diff"] for x in res.values() if x["diff"]]
    assert not res["4000C"].get("feed_errors")


def test_4000c_sample_uses_pm_and_risk(made):
    p = stdwp.file_for(_folder(made), "4000C")
    wb = load_workbook(p)
    sp = stdwp._meta(wb)["feeds"]["02"]
    ws = wb[sp["sheet"]]
    params = {lab: ws.cell(r, 4).value for lab, r in sp["prow"].items()}
    wb.close()
    assert params["수행중요성(허용왜곡표시)"] == 60000000
    assert params["위험 수준"] == "보통" and params["신뢰계수"] == 2.31
    assert params["표본 점 수"] >= 1


def test_public_texts_have_no_kicpa_or_internal_refs(made):
    d = _folder(made)
    c = _text(stdwp.file_for(d, "4000C"))
    assert "총괄표: 당기말 잔액을" in c
    assert "python scripts/run.py fill <자료 폴더>" in c
    assert "한공회 감사조서서식 4000A Part 1 2번 절차" in _text(stdwp.file_for(d, "4000A"))
    for p in (d / "4000 계정별" / "표준조서").glob("*_표준.xlsx"):
        t = _text(p)
        for bad in ("3320", "2700B", "wp make", "python -m audit"):
            assert bad not in t, (p.name, bad)


def test_refresh_keeps_ai_text_and_rejects_amounts(src, tmp_path):
    patch = tmp_path / "p.json"
    patch.write_text(json.dumps({"slots": [{"slot": "memo.main", "text": "외상매출금과 손실충당금으로 이루어진다", "basis": "정산표"}]},
                                ensure_ascii=False), encoding="utf-8")
    assert run.main(["fill", str(src), "--area", "4000C", "--patch", str(patch)]) == 0
    assert run.main(["refresh", str(src), "--area", "4000C"]) == 0
    assert "외상매출금과 손실충당금으로 이루어진다" in _text(stdwp.file_for(_folder(src), "4000C"))
    bad = tmp_path / "b.json"
    bad.write_text(json.dumps({"slots": [{"slot": "memo.main", "text": "잔액 1,234,567원", "basis": "정산표"}]}, ensure_ascii=False),
                   encoding="utf-8")
    assert run.main(["fill", str(src), "--area", "4000C", "--patch", str(bad)]) == 1


def test_refresh_reads_new_file_and_drops_removed(src):
    (src / "계정명세서_2025.xlsx").unlink()
    assert run.main(["refresh", str(src), "--area", "4000C"]) == 0
    rec = _folder(src) / "00 받은자료"
    assert not (rec / "계정명세서_2025.xlsx").exists() and (rec / "매출채권 연령분석표_2025.xlsx").exists()


def test_without_pm_the_sample_table_says_why(tmp_path):
    s = _copy(tmp_path, "자료")
    assert run.main(["make", str(s), "--company", CO, "--fy-end", FY, "--area", "4000C"]) == 0
    x = next(x for x in stdwp.check(_folder(s)) if x["code"] == "4000C")
    assert "수행중요성(--pm)" in x["feed_errors"]["02"]


def test_interim_folder_and_head(tmp_path, capsys):
    s = _copy(tmp_path, "자료")
    assert run.main(["make", str(s), "--company", CO, "--fy-end", FY, "--as-of", "2025-09-30", "--area", "4000A"]) == 0
    out = capsys.readouterr().out
    d = _folder(s)
    assert d.name == "표준조서_2025-09-30 중간감사"
    assert "중간감사" in _text(stdwp.file_for(d, "4000A"))
    assert "확인: 정산표에 쓴 시산표" in out and "기준일 2025-09-30" in out      # 연도만 적힌 시산표로 중간감사를 만들면 알린다


def test_year_end_tb_needs_no_note(made):
    assert run._tb_note(_folder(made)) is None


def _fake(src: Path, name: str) -> Path:
    d = src / name / "_색인"
    d.mkdir(parents=True)
    (d / "감사건.json").write_text("{}", encoding="utf-8")
    return d.parent


def test_find_picks_folder_by_name_not_time(tmp_path):
    s = tmp_path / "자료"
    s.mkdir()
    a = _fake(s, "표준조서_2025-06-30 중간감사")
    assert run._find(s) == a                                         # 하나뿐이면 그것
    b = _fake(s, "표준조서_2025-09-30 중간감사")
    with pytest.raises(run.Stop):
        run._find(s)                                                 # 중간감사만 여럿이면 고르지 않는다
    assert run._find(s, "2025-06-30") == a and run._find(s, "2025-09-30") == b
    y = _fake(s, "표준조서_2025-12-31 기말감사")
    os.utime(a, (1, 1))
    os.utime(y, (2, 2))                                              # 기말감사 폴더가 가장 오래돼도
    assert run._find(s) == y
    with pytest.raises(run.Stop):
        run._find(s, "2025-03-31")


def test_sync_compares_content_and_keeps_auditor_files(src):
    d = _folder(src)
    rec = d / "00 받은자료"
    (src / "추가.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    assert run._sync(src, d)["added"] == ["추가.csv"]
    (src / "추가.csv").write_text("a,b\n1,3\n", encoding="utf-8")          # 크기 같고
    st = (rec / "추가.csv").stat()
    os.utime(src / "추가.csv", (st.st_atime, st.st_mtime))                   # 시각도 같아도
    assert run._sync(src, d)["changed"] == ["추가.csv"]
    assert (rec / "추가.csv").read_text(encoding="utf-8") == "a,b\n1,3\n"
    (rec / "감사인_추가자료.xlsx").write_bytes(b"x")                          # 감사인이 받은자료에 직접 넣은 파일
    (src / "추가.csv").unlink()
    assert run._sync(src, d)["removed"] == ["추가.csv"]
    assert (rec / "감사인_추가자료.xlsx").exists() and not (rec / "추가.csv").exists()


def test_unknown_area_stops_before_writing(tmp_path):
    s = _copy(tmp_path, "자료")
    assert run.main(["make", str(s), "--company", CO, "--fy-end", FY, "--area", "4000Z"]) == 1
    assert not [p for p in s.iterdir() if p.is_dir() and p.name.startswith("표준조서_")]


def test_bad_input_returns_1(tmp_path):
    assert run.main(["make", str(tmp_path / "없음"), "--company", CO, "--fy-end", FY]) == 1
    empty = tmp_path / "빈 폴더"
    empty.mkdir()
    assert run.main(["make", str(empty), "--company", CO, "--fy-end", FY]) == 1
    assert not any(empty.iterdir()), "자료가 없으면 감사 폴더도 세우지 않는다"
    assert run.main(["check", str(empty)]) == 1
    s = _copy(tmp_path, "자료")
    assert run.main(["make", str(s), "--company", CO, "--fy-end", FY, "--pm", "0"]) == 1
    assert not [p for p in s.iterdir() if p.is_dir()], "잘못된 --pm 이면 감사 폴더도 세우지 않는다"
    assert run.main(["make", str(empty), "--company", CO, "--fy-end", "2025/12/31"]) == 1
    assert run.main(["make", str(s), "--company", CO, "--fy-end", FY, "--fy-start", "2026-01-01"]) == 1
    assert not [p for p in s.iterdir() if p.is_dir() and p.name.startswith("표준조서_")]


def test_roll_interim_to_year_end_in_same_folder(tmp_path):
    s = _copy(tmp_path, "자료")
    assert run.main(["make", str(s), "--company", CO, "--fy-end", FY, "--as-of", "2025-09-30", "--area", "4000A"]) == 0
    assert run.main(["make", str(s), "--company", CO, "--fy-end", FY, "--area", "4000A"]) == 0
    assert run.main(["roll", str(s), str(s), "--as-of", "2025-09-30"]) == 1          # 같은 감사 폴더끼리는 멈춘다
    assert run.main(["roll", str(s), str(s)]) == 1
    assert run.main(["roll", str(s), str(s), "--prev-as-of", "2025-09-30"]) == 0
    year_end = next(p for p in run._folders(s) if p.name.endswith("기말감사"))
    assert "중간감사" not in _text(stdwp.file_for(year_end, "4000A"))
