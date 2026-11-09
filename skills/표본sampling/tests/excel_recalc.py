"""엑셀로 책을 열어 수식을 다시 계산하고 저장한다(openpyxl 은 수식 값을 계산하지 않는다).

    python tools/excel_recalc.py <책.xlsx>

엑셀이나 pywin32 가 없으면 False 를 돌려준다. 시험이 수식 결과를 엔진 계산과 대조할 때 쓴다.
"""
from __future__ import annotations

import sys
from pathlib import Path


def recalc(path: Path) -> bool:
    try:
        import pythoncom
        import win32com.client as win32
    except ImportError:
        return False
    pythoncom.CoInitialize()
    try:
        xl = win32.DispatchEx("Excel.Application")
    except Exception:  # noqa: BLE001  엑셀이 설치되지 않은 PC
        return False
    wb = None
    try:
        xl.Visible, xl.DisplayAlerts = False, False
        wb = xl.Workbooks.Open(str(Path(path).resolve()))
        xl.CalculateFull()
        wb.Save()
        wb.Close(False)
        return True
    finally:
        wb = None                     # 엑셀을 닫기 전에 참조를 놓는다(닫힌 뒤 놓으면 COM 끊김 오류가 찍힌다)
        xl.Quit()
        del xl
        pythoncom.CoUninitialize()


if __name__ == "__main__":
    ok = recalc(Path(sys.argv[1]))
    print("다시 계산함" if ok else "엑셀이 없어 다시 계산하지 못함")
    sys.exit(0 if ok else 1)
