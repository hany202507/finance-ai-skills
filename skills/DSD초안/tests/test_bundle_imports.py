"""이 스킬 폴더만 따로 떼어도 묶은 엔진 모듈이 모두 불러와진다(2026-11-27).

스킬마다 감사 엔진(audit 패키지)의 일부만 묶어 싣는다. 묶음에 빠진 모듈을 맨 위에서 부르는 파일이 있으면 그 파일을 쓰는 명령이
수강생 PC 에서 ModuleNotFoundError 로 멈춘다(11-27 PBC요청자료 · 표준조서). 스킬 폴더를 임시 폴더에 복사하고
`python -I`(PYTHONPATH · 다른 스킬 · 감사 엔진 전체를 보지 않음)로 모듈을 하나씩 불러 본다. 함수 안에서 부르는 모듈은 명령 시험이 본다.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
CODE = """import importlib, sys
from pathlib import Path
scripts = Path(sys.argv[1]); sys.path.insert(0, str(scripts)); bad = []
for f in sorted((scripts / "audit").rglob("*.py")):
    parts = list(f.relative_to(scripts).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    try:
        importlib.import_module(".".join(parts))
    except Exception as e:
        bad.append(f"{'.'.join(parts)}: {type(e).__name__}: {e}")
print("\\n".join(bad)); sys.exit(1 if bad else 0)
"""


def test_every_bundled_module_imports_alone(tmp_path):
    skill = tmp_path / SKILL.name
    shutil.copytree(SKILL / "scripts", skill / "scripts", ignore=shutil.ignore_patterns("__pycache__"))
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
    env["PYTHONIOENCODING"] = "utf-8"
    p = subprocess.run([sys.executable, "-I", "-c", CODE, str(skill / "scripts")], cwd=skill, env=env,
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
    assert p.returncode == 0, p.stdout + p.stderr
