# -*- coding: utf-8 -*-
"""급여대장 읽기에서 조용히 틀리면 안 되는 것들.

소득세 열 이름이 「갑근세」인 대장이 소득세 0 으로 신고서가 나온 일이 있었다(2026-11-02).
급여대장 스킬 출력은 시트가 넷이라 시트 지정 없이는 멈췄다(같은 날).
"""
import sys
from pathlib import Path

import openpyxl
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "모듈" / "원천징수이행상황신고서" / "scripts"))
import 집계 as A  # noqa: E402



def _대장(경로, 머리, 행들, 시트="12월"):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 시트
    ws["A1"] = "급 여 대 장"
    ws.append([])
    ws.append([])
    ws.append(머리)
    for r in 행들:
        ws.append(r)
    wb.save(경로)
    return 경로


def _스킬출력(경로, 연월="2026-07"):
    """급여대장 스킬이 내는 워크북 모양. 인사카드 · 과세표준 · 급여대장 · 확인사항."""
    wb = openpyxl.Workbook()
    wb.active.title = "인사카드"
    wb.create_sheet("과세표준")
    ws = wb.create_sheet("급여대장")
    wb.create_sheet("확인사항")
    ws["A1"] = f"주식회사 가상 · {연월} 급여대장"
    ws.append([])
    ws.append(["사번", "성명", "구분", "소득코드", "기본급", "총지급액", "소득세", "지방소득세"])
    ws.append(["E001", "김가상", "상용", "A01", 3000000, "=SUM(E4:E4)", 70000, 7000])
    wb.save(경로)
    return 경로


def test_갑근세_열을_소득세로_읽는다(tmp_path):
    경로 = _대장(tmp_path / "대장.xlsx",
                 ["순번", "사번", "성명", "지급총액", "갑근세", "주민세"],
                 [[1, "S01", "김가상", 7000000, 210000, 21000],
                  [2, "S02", "이가상", 3800000, 114000, 11400],
                  ["합계(2명)", None, None, 10800000, 324000, 32400]])
    행 = A.read_ledger(경로)
    assert len(행) == 2
    assert sum(r["소득세"] for r in 행) == 324000
    assert sum(r["지방소득세"] for r in 행) == 32400


def test_소득세_열이_없으면_0으로_두지_않고_멈춘다(tmp_path):
    경로 = _대장(tmp_path / "대장.xlsx",
                 ["사번", "성명", "총지급액", "지방소득세"],
                 [["S01", "김가상", 3000000, 7000]])
    with pytest.raises(A.확인필요, match="소득세"):
        A.read_ledger(경로)


def test_급여대장_스킬_출력은_시트_지정_없이_읽는다(tmp_path):
    경로 = _스킬출력(tmp_path / "급여대장_2026-07.xlsx")
    정보 = {}
    행 = A.read_ledger(경로, 귀속연월="202607", 정보=정보)
    assert 정보["시트"] == "급여대장"
    assert [r["성명"] for r in 행] == ["김가상"]
    assert 행[0]["소득세"] == 70000
    assert 행[0]["소득코드"] == "A01"


def test_급여대장_시트_제목의_달이_귀속과_다르면_멈춘다(tmp_path):
    경로 = _스킬출력(tmp_path / "급여대장_2026-07.xlsx", 연월="2026-07")
    with pytest.raises(A.확인필요, match="2026-07"):
        A.read_ledger(경로, 귀속연월="202606")


def test_달_이름_시트가_있으면_그것이_먼저다(tmp_path):
    경로 = tmp_path / "대장.xlsx"
    wb = openpyxl.Workbook()
    wb.active.title = "급여대장"
    wb["급여대장"].append(["성명", "총지급액", "소득세"])
    wb["급여대장"].append(["틀린사람", 1000000, 1])
    ws = wb.create_sheet("7월")
    ws.append(["성명", "총지급액", "소득세"])
    ws.append(["맞는사람", 2000000, 2])
    wb.save(경로)
    assert [r["성명"] for r in A.read_ledger(경로, 귀속연월="202607")] == ["맞는사람"]


def test_고를_시트가_없으면_여전히_멈춘다(tmp_path):
    경로 = tmp_path / "대장.xlsx"
    wb = openpyxl.Workbook()
    wb.active.title = "인사카드"
    wb.create_sheet("참고")
    wb.save(경로)
    with pytest.raises(A.확인필요, match="시트"):
        A.read_ledger(경로, 귀속연월="202607")


def _회사기초정보(경로):
    """전자파일 스킬의 빈 틀에 가상 값을 채운다."""
    import shutil
    틀 = Path(__file__).resolve().parents[1] / "모듈" / "원천세전자파일" / "assets" / "회사기초정보_템플릿.xlsx"
    shutil.copy(틀, 경로)
    값 = {"사업자번호": "1234512345", "상호": "샘플회사(가상)", "대표자": "가상대표", "사용자ID": "demo",
          "신고구분상세코드": "01", "원천신고구분": "매월", "세무프로그램코드": "9999",
          "세무대리인신고여부": "N", "사업장소재지": "서울특별시 강남구 테헤란로 1",
          "소득처분여부": "N", "일괄납부여부": "N", "사업자단위과세여부": "N"}
    wb = openpyxl.load_workbook(경로)
    for r in wb.active.iter_rows():
        if r[6].value in 값:
            r[2].value = 값[r[6].value]
    wb.save(경로)


def test_받은자료의_추가행_파일을_신고서에_넣는다(tmp_path):
    import json
    import 작성
    받은 = tmp_path / "받은자료"
    받은.mkdir()
    _스킬출력(받은 / "급여대장_2026-07.xlsx")
    _회사기초정보(받은 / "회사기초정보_1234512345.xlsx")
    (받은 / "추가행_2026-07.json").write_text(json.dumps([
        {"성명": "정민호", "소득코드": "A59", "총지급액": 1000000, "소득세": 80000, "농특세": 0,
         "지방소득세": 8000, "출처": "입퇴사처리"},
        {"성명": "김가상", "소득코드": "A02", "대장총지급액": 25200000, "면제비과세": 1400000,
         "총지급액": 23800000, "소득세": -153350, "농특세": 0, "지방소득세": -15280, "출처": "입퇴사처리",
         "비고": "1~7월 중도퇴사 정산"},
    ], ensure_ascii=False), encoding="utf-8")
    r = 작성.실행(받은, tmp_path / "산출", 계산값=False)
    assert r["묶음"]["A59"]["소득세"] == 80000
    assert r["묶음"]["A02"]["총지급액"] == 23800000
    assert r["묶음"]["A99"]["소득세"] == 70000 + 80000 - 153350
