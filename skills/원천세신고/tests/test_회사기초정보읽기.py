# -*- coding: utf-8 -*-
"""회사기초정보 엑셀 읽기. 신고서 단계(회사정보.py)가 읽는 꼴은 전자파일 단계도 읽어야 한다.

틀 양식(시트 「회사기초정보」, 4행 머리, 「키」 열)만 읽던 때는 「항목」 · 「값」 만 있는 엑셀이 신고서 단계를 지나
전자파일 단계에서 KeyError 로 멈췄다(2026-11-02).
"""
import sys
from pathlib import Path

import openpyxl
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "모듈" / "원천세전자파일" / "scripts"))
import make_company_info_xlsx as M  # noqa: E402

값 = {"사업자번호": "1234512345", "상호": "샘플회사(가상)", "대표자": "가상대표", "사용자ID": "demo",
      "신고구분상세코드": "01", "원천신고구분": "매월", "세무프로그램코드": "9000", "세무대리인신고여부": "N"}


def test_틀_양식을_읽는다(tmp_path):
    p = tmp_path / "회사기초정보_1234512345.xlsx"
    M.build(p, 값)
    r = M.read(p)
    assert {k: r[k] for k in 값} == 값


def test_항목_값_열만_있어도_틀의_항목_이름으로_읽는다(tmp_path):
    p = tmp_path / "회사기초정보.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "기초정보"
    ws.append(["우리 회사 기초정보"])
    ws.append(["항목", "값"])
    라벨 = {키: 항목 for _, 항목, 키, *_ in M.ROWS}
    for k, v in 값.items():
        ws.append([라벨[k], v])
    ws.append(["신고 종류", "정기"])            # 글자로 적어도 코드로 바꾼다(앞 줄 01 을 덮는다)
    wb.save(p)
    r = M.read(p)
    assert r["사업자번호"] == "1234512345" and r["사용자ID"] == "demo" and r["신고구분상세코드"] == "01"


def test_1행_머리에_키_열이_있어도_읽는다(tmp_path):
    p = tmp_path / "회사기초정보.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["항목", "값", "키"])
    for k, v in 값.items():
        ws.append(["", v, k])
    wb.save(p)
    assert M.read(p)["상호"] == "샘플회사(가상)"


def test_머리행이_없으면_알아듣는_문장으로_멈춘다(tmp_path):
    p = tmp_path / "회사기초정보.xlsx"
    wb = openpyxl.Workbook()
    wb.active.append(["이름", "금액"])
    wb.save(p)
    with pytest.raises(ValueError, match="머리행"):
        M.read(p)
