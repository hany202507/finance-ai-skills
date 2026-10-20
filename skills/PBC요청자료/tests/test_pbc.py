"""모의 받은자료(가상 회사 도담소프트(가상) 1차 수령)로 요청자료 목록 · 빠진 자료 · 메일 초안을 만든다."""
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
EX = HERE / "examples" / "모의자료"


def _run(*args):
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1", "AUDIT_OCR": "off"}
    r = subprocess.run([sys.executable, str(HERE / "scripts" / "run.py"), *map(str, args)], env=env,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode, r.stdout + r.stderr


def test_start_apply_mail(tmp_path):
    d = tmp_path / "도담소프트(가상)" / "2025 기말감사"
    code, log = _run("new", d, "--company", "도담소프트(가상)", "--fy-end", "2025-12-31")
    assert code == 0, log
    shutil.copytree(EX / "받은자료", d / "00 받은자료", dirs_exist_ok=True)
    code, log = _run("start", d, "--no-ocr")
    assert code == 0, log
    assert "요청자료 2 / 18 받음 · 빠진 자료 14건" in log, log
    assert "결산일 후분" in log and "원천징수이행상황신고서" in log
    for f in ("1000 감사계약/PBC_요청자료목록.xlsx", "1000 감사계약/1100_계약전위험평가.xlsx", "1000 감사계약/1200_감사업무조건합의.docx",
              "2000 위험평가/2100_기업이해.xlsx"):
        assert (d / f).exists(), f
    assert list((d / "1000 감사계약").glob("PBC_요청자료목록_메일_*.txt"))
    code, log = _run("text", EX / "받은자료" / "전기" / "전기 감사보고서_FY2024.pdf")
    assert code == 0 and "한울감사반(가상)" in log, log
    code, log = _run("apply", d, EX / "판독_patch.json")
    assert code == 0 and "한울감사반(가상)" in log, log
    code, log = _run("sent", d, "2026-01-21")
    assert code == 0 and "2026-01-21" in log, log
    code, log = _run("mail", d)
    assert code == 0, log
    code, log = _run("next", d)
    assert code == 0 and "빠진 자료" in log, log
