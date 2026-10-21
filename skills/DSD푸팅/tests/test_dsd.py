"""모의 dsd(가상 회사 가온정밀(가상), 오류 11개를 심음)로 실행기를 끝까지 돌린다."""
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
EX = HERE / "examples" / "모의자료"
DSD = "회사제시_가온정밀_오류심음.dsd"


def _run(*args, cwd):
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1", "AUDIT_OCR": "off"}
    r = subprocess.run([sys.executable, str(HERE / "scripts" / "run.py"), *args], cwd=cwd, env=env,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.returncode, r.stdout + r.stderr


def test_links_foot_text(tmp_path):
    shutil.copy2(EX / DSD, tmp_path / DSD)
    out = tmp_path / "out"
    out.mkdir()
    shutil.copy2(EX / "기준사실.json", out / "기준사실.json")
    code, log = _run("links", DSD, "--out", "out", cwd=tmp_path)
    assert code == 0, log
    assert (out / "dsd_읽기자료.md").exists() and (out / "dsd_연결요청.json").exists()
    code, log = _run("links", DSD, "--apply", str(EX / "연결.json"), "--out", "out", cwd=tmp_path)
    assert code == 0 and "AI 연결 2건" in log, log
    code, log = _run("foot", DSD, "--out", "out", cwd=tmp_path)
    assert "FALSE 1" in log and "1,212,000,000" in log and "이웃한 두 자리" in log, log
    assert (out / f"DSD푸팅_{Path(DSD).stem}.xlsx").exists()
    assert "오타 3" in log and "사실 불일치 6" in log, log
    code, log = _run("text", DSD, "--out", "out", cwd=tmp_path)
    assert code == 0, log
    for word in ("재무재표", "충당부체", "회사의 회사의"):
        assert word in log, word
    assert "「대표이사 김가온(가상)」 의 직함을 빼거나 바꾼다" in log, log        # S101 주주 명단은 이름이 아니라 직함을 고친다(10-21)
