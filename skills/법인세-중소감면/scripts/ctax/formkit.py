"""검증 워크북 · 법정서식 PDF 를 만드는 스킬(통합고용 · 창업감면 · 중소감면)이 함께 쓰는 두 가지.

- put: 법제처 서식 PDF 의 칸(box) 안에 글자를 넣는다
- recalc: 엑셀로 워크북을 한 번 계산해 수식 결과를 파일에 심는다(엑셀이 없으면 False)

스킬 꾸러미(pack.py)가 이 파일을 함께 담는다. 다른 ctax 모듈을 읽지 않는다.
"""
from __future__ import annotations

from pathlib import Path

import pymupdf as fitz

FONT = "korea"            # PyMuPDF 내장 CJK 글꼴(Droid Sans Fallback)
SIZE = 9.0

_FONT = None


def _font():
    global _FONT
    if _FONT is None:
        _FONT = fitz.Font(FONT)
    return _FONT


def put(page, box, text: str, align: str = "r", size: float = SIZE, pad: float = 1.6, min_sx: float = 0.55) -> None:
    """칸(box) 안에 글자를 넣는다. 넘치면 가로로 0.55 배까지 줄이고, 그래도 넘치면 글자 크기를 줄인다.
    폭을 잰 글꼴로 그대로 그린다(TextWriter). insert_text 의 내장 CJK 이름 글꼴은 숫자를 전각 폭으로 그려 칸을 넘친다."""
    if text in (None, ""):
        return
    font = _font()
    x0, y0, x1, y1 = box
    room = max(1.0, (x1 - x0) - 2 * pad)
    size = min(size, (y1 - y0) * 0.8)
    w = font.text_length(text, fontsize=size)
    sx = 1.0
    if w > room:
        sx = max(min_sx, room / w)
        if w * sx > room:
            size = size * room / (w * sx)
            w = font.text_length(text, fontsize=size)
    width = w * sx
    if align == "l":
        x = x0 + pad
    elif align == "c":
        x = (x0 + x1 - width) / 2
    else:
        x = x1 - pad - width
    y = (y0 + y1) / 2 + size * 0.36
    pt = fitz.Point(x, y)
    tw = fitz.TextWriter(page.rect)
    tw.append(pt, text, font=font, fontsize=size)
    tw.write_text(page, color=(0, 0, 0), morph=(pt, fitz.Matrix(sx, 1)) if sx < 1 else None)


def recalc(path: Path) -> bool:
    """엑셀로 한 번 계산해 수식 결과를 파일에 심는다. 엑셀이 없으면 False."""
    try:
        import pythoncom
        import win32com.client
    except ImportError:
        return False
    pythoncom.CoInitialize()
    try:
        xl = win32com.client.DispatchEx("Excel.Application")
    except Exception:                                        # noqa: BLE001  엑셀이 깔리지 않은 PC
        return False
    try:
        xl.Visible, xl.DisplayAlerts = False, False
        wb = xl.Workbooks.Open(str(path), UpdateLinks=0)
        xl.CalculateFull()
        wb.Save()
        wb.Close(False)
    finally:
        xl.Quit()
        pythoncom.CoUninitialize()
    return True
