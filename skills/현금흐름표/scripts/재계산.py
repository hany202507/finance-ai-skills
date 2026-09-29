# -*- coding: utf-8 -*-
"""엑셀을 한 번 계산시켜 수식의 결과값을 파일에 심는다.

openpyxl 은 수식을 써 넣기만 하고 계산하지 않는다. 그 파일을 엑셀로 열면 자동으로 계산돼
정상으로 보이지만, 구글시트·뷰어·pandas·검토용 대사 스크립트로 읽으면 **인원 0 · 총지급액 0
· 소득세 0** 이 나온다. 값이 비었다고 알려주지도 않는다. 검토자가 「0원 신고」로 읽는 사고가
여기서 난다.

그래서 저장 직후 한 번 계산시킨다. 엑셀 → 리브레오피스 순으로 시도하고, 둘 다 없으면
막지 않되 분명히 알린다 · 조용히 넘어가면 없는 문제로 보인다.
"""
import shutil
import subprocess
import sys
from pathlib import Path


def _엑셀(경로):
    import win32com.client as win32
    app = win32.DispatchEx("Excel.Application")
    app.Visible = False
    app.DisplayAlerts = False
    try:
        wb = app.Workbooks.Open(str(Path(경로).resolve()))
        app.CalculateFullRebuild()
        wb.Save()
        wb.Close(SaveChanges=False)
    finally:
        app.Quit()
    return "Excel"


def _리브레(경로):
    p = Path(경로).resolve()
    후보 = [shutil.which("soffice"), shutil.which("libreoffice"),
            r"C:\Program Files\LibreOffice\program\soffice.exe",
            "/Applications/LibreOffice.app/Contents/MacOS/soffice", "/usr/bin/soffice"]
    exe = next((c for c in 후보 if c and Path(c).exists()), None)
    if not exe:
        raise FileNotFoundError("LibreOffice 없음")
    tmp = p.parent / "_재계산"
    tmp.mkdir(exist_ok=True)
    subprocess.run([exe, "--headless", "--norestore", "--convert-to", "xlsx",
                    "--outdir", str(tmp), str(p)], check=True,
                   capture_output=True, timeout=180)
    나온것 = tmp / p.name
    if not 나온것.exists():
        raise RuntimeError("LibreOffice 변환 결과가 없습니다")
    shutil.move(str(나온것), str(p))
    shutil.rmtree(tmp, ignore_errors=True)
    return "LibreOffice"


def 심기(경로, 조용히=False):
    """계산값을 심고 쓴 도구 이름을 돌려준다. 못 하면 None."""
    for 이름, 함수 in (("Excel", _엑셀), ("LibreOffice", _리브레)):
        try:
            쓴것 = 함수(경로)
            if not 조용히:
                print(f"  계산값 심음 ({쓴것})")
            return 쓴것
        except Exception as e:
            마지막 = f"{이름}: {type(e).__name__} {e}"
    if not 조용히:
        print(f"  ⚠ 계산값을 심지 못했습니다 ({마지막}).\n"
              f"    엑셀에서 한 번 열었다 저장하면 채워집니다. 그 전에는 엑셀 밖에서 읽으면\n"
              f"    숫자가 전부 빈칸으로 보입니다 · 검토자에게 그대로 넘기지 마세요.", file=sys.stderr)
    return None


def 확인(경로):
    """수식 셀 중 계산값이 비어 있는 것의 개수. 0 이면 어디서 열어도 숫자가 보인다."""
    import openpyxl
    수 = openpyxl.load_workbook(경로)
    값 = openpyxl.load_workbook(경로, data_only=True)
    전체 = 빈칸 = 0
    for 이름 in 수.sheetnames:
        a, b = 수[이름], 값[이름]
        for r in range(1, a.max_row + 1):
            for c in range(1, a.max_column + 1):
                v = a.cell(r, c).value
                if isinstance(v, str) and v.startswith("="):
                    전체 += 1
                    if b.cell(r, c).value is None:
                        빈칸 += 1
    return 전체, 빈칸
