"""표준조서: 이 스킬 폴더만 따로 떼어도 엔진이 끝까지 돈다(2026-11-27).

스킬마다 감사 엔진의 일부만 묶어 싣는다. 11-27 수강생 시연에서 전기조서(WTB)가 든 자료로 make 를 돌리자
definitions/prior_wp.yaml 과 audit/report/dsd_wtb.py(+ dsd · dsd_grid · dsd_links)가 묶음에 없어 전기WTB 판독에서 멈췄다.
예시 자료에는 전기조서가 없어 다른 시험이 이 길을 지나지 않았다.

- 스킬 폴더를 임시 폴더에 복사하고 `python -I` 로 돌린다(다른 스킬 · 감사 엔진 전체 · PYTHONPATH 를 보지 않는다).
- 예시 자료에 감사 법인 양식 전기조서(표지 · BS · IS · AJE 시트, 가상 숫자)를 더해 전기조서 판독 길을 지난다.
- 묶음 안 모듈을 하나씩 불러 본다(맨 위 import 가 묶음 밖 모듈을 부르면 여기서 걸린다).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from openpyxl import Workbook

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent
EXAMPLE = SKILL / "examples" / "모의자료"
STOPS = ("ModuleNotFoundError", "ImportError", "정의 파일이 없습니다", "DefinitionError", "Traceback")
CO, FY = "가온정밀(가상)", "2025-12-31"


def _env() -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


def _run(skill: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-I", str(skill / "scripts" / "run.py"), *args], cwd=skill, env=_env(),
                          capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900)


def _prior_wtb(path: Path) -> None:
    """감사 법인 양식 전기조서: BS · IS(과목 | 당기 | 전기) · AJE(No. | 내역 | 차변 | 대변). 숫자는 가상이다."""
    wb = Workbook()
    ws = wb.active
    ws.title = "표지"
    ws["B2"] = "가온정밀(가상) 전기조서 · 정산표(WTB)"
    ws["B3"] = "2024-01-01 ~ 2024-12-31 · 가상 자료"
    bs = wb.create_sheet("BS")
    bs.append(["과목", "당기", None, "전기", None])
    for row in (["자산", None, None, None, None], ["현금및현금성자산", 120000000, None, 90000000, None],
                ["매출채권", 80000000, None, 70000000, None], ["자산총계", None, 200000000, None, 160000000]):
        bs.append(row)
    is_ = wb.create_sheet("IS")
    is_.append(["과목", "당기", None, "전기", None])
    for row in (["매출액", 500000000, None, 450000000, None], ["당기순이익", 30000000, None, 25000000, None]):
        is_.append(row)
    aje = wb.create_sheet("AJE")
    aje.append([None, "No.", "내역", "차변", None, "대변", None])
    aje.append([None, None, None, "계정과목", "금액", "계정과목", "금액"])
    aje.append([None, 1, "기말 미지급비용 계상", "지급수수료", 3000000, None, None])
    aje.append([None, None, None, None, None, "미지급비용", 3000000])
    wb.save(path)


@pytest.fixture(scope="module")
def alone(tmp_path_factory):
    root = tmp_path_factory.mktemp("alone")
    skill = root / "표준조서"
    shutil.copytree(SKILL, skill, ignore=shutil.ignore_patterns("tests", "__pycache__", ".pytest_cache", "표준조서_*"))
    data = root / "자료"
    shutil.copytree(EXAMPLE, data, ignore=shutil.ignore_patterns("표준조서_*"))
    (data / "전기").mkdir(exist_ok=True)
    _prior_wtb(data / "전기" / "전기조서_WTB_2024.xlsx")
    return skill, data


def _ok(p: subprocess.CompletedProcess) -> None:
    out = p.stdout + p.stderr
    hit = [s for s in STOPS if s in out]
    assert not hit, f"엔진이 멈췄다({hit}):\n{out[-3000:]}"
    assert p.returncode in (0, 2), out[-3000:]


def test_make_refresh_check_alone(alone):
    skill, data = alone
    _ok(_run(skill, "make", str(data), "--company", CO, "--fy-end", FY, "--pm", "60000000", "--risk", "보통"))
    _ok(_run(skill, "refresh", str(data), "--pm", "60000000"))
    _ok(_run(skill, "check", str(data)))
    _ok(_run(skill, "check", str(data), "--slots"))
    _ok(_run(skill, "list"))


def test_every_bundled_module_imports_alone(alone):
    skill, _ = alone
    scripts = skill / "scripts"
    mods = []
    for f in sorted((scripts / "audit").rglob("*.py")):
        parts = list(f.relative_to(scripts).with_suffix("").parts)
        if parts[-1] == "__init__":
            parts = parts[:-1]
        mods.append(".".join(parts))
    code = ("import importlib, sys\nsys.path.insert(0, sys.argv[1])\nbad = []\n"
            "for m in sys.argv[2:]:\n    try:\n        importlib.import_module(m)\n"
            "    except Exception as e:\n        bad.append(f'{m}: {type(e).__name__}: {e}')\n"
            "print('\\n'.join(bad))\nsys.exit(1 if bad else 0)\n")
    p = subprocess.run([sys.executable, "-I", "-c", code, str(scripts), *mods], cwd=skill, env=_env(),
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
    assert p.returncode == 0, p.stdout + p.stderr
