"""모의 분개장(가상 회사 가온정밀(가상))으로 분개 테스트 조서를 만든다."""
import os
import subprocess
import sys
from pathlib import Path

from openpyxl import load_workbook

HERE = Path(__file__).resolve().parents[1]
EX = HERE / "examples" / "모의자료"


def test_jet_example(tmp_path):
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1", "AUDIT_OCR": "off"}
    r = subprocess.run([sys.executable, str(HERE / "scripts" / "run.py"), str(EX / "분개장_2025.xlsx"),
                        "--after", str(EX / "분개장_2026_기말후.xlsx"), "--tb", str(EX / "재무제표_시산표.xlsx"),
                        "--fy-end", "2025-12-31", "--pm", "60000000", "--company", "가온정밀(가상)", "--out", str(tmp_path / "out")],
                       env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
    log = r.stdout + r.stderr
    assert r.returncode == 0, log
    assert "분개장 1,751행" in log, log
    for line in ("주말 · 공휴일 전표: 1건", "기말 후 취소 · 역분개: 6건", "결산일 근처 큰 금액: 32건", "드문 계정 조합: 10건",
                 "끝자리 0 반복: 16건", "적요 없음: 0건", "수기 조정 전표: 4건"):
        assert line in log, line
    p = tmp_path / "out" / "3600-JET_분개테스트.xlsx"
    wb = load_workbook(p, read_only=True)
    assert "요약" in wb.sheetnames
