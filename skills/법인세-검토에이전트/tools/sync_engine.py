# -*- coding: utf-8 -*-
"""academy-product 의 ctax 에서 AR 에 필요한 부분만 engine/ctax 로 옮긴다.

usage: python tools/sync_engine.py <academy-product 의 법인세 폴더>

옮기는 것: case.py, xlsx.py, intake/, prior/, ar/, wp/ (파일 내용은 고치지 않는다), AR 시험(tests/test_ar*.py).
조서(wp)도 그대로 옮긴다(세무조정 금액 · 소득금액 계산). 서식(forms) 패키지는 AR 이 서식 목록만 읽으므로 껍데기를 만든다.
  - forms/engine_forms.yaml (원본 그대로), forms/plugins/__init__.py : engine_forms()
  (조서의 9호 가산세 계산은 신고건.json 「가산세」 입력이 있을 때만 forms 를 부르고, 이 스킬은 그 입력을 쓰지 않는다)
옮긴 원본의 커밋은 engine/VENDORED.json 에 남긴다.
"""
import json
import shutil
import subprocess
import sys
from importlib import import_module
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "engine" / "ctax"
COPY_DIRS = ["intake", "prior", "ar", "wp"]
COPY_FILES = ["case.py", "xlsx.py"]
SKIP = shutil.ignore_patterns("tests", "__pycache__", "*.pyc")


def main(src_root: str) -> int:
    src = Path(src_root).resolve() / "ctax"
    if not (src / "ar" / "engine.py").exists():
        sys.exit(f"ctax 를 찾지 못했습니다: {src}")
    if DEST.exists():
        shutil.rmtree(DEST)
    DEST.mkdir(parents=True)
    (DEST / "__init__.py").write_text('"""academy-product ctax 에서 옮긴 AR 엔진(tools/sync_engine.py). 직접 고치지 않는다."""\n', encoding="utf-8")
    for name in COPY_FILES:
        shutil.copy2(src / name, DEST / name)
    for name in COPY_DIRS:
        shutil.copytree(src / name, DEST / name, ignore=SKIP)
    (DEST / "score").mkdir()                     # 조서의 전기 조정 대조가 과목 맞춤(score/match.py)만 쓴다
    (DEST / "score" / "__init__.py").write_text("", encoding="utf-8")
    shutil.copy2(src / "score" / "match.py", DEST / "score" / "match.py")

    sys.path.insert(0, str(src.parent))
    plugins = import_module("ctax.forms.plugins")
    forms = DEST / "forms"
    (forms / "plugins").mkdir(parents=True)
    (forms / "__init__.py").write_text("", encoding="utf-8")
    shutil.copy2(src / "forms" / "engine_forms.yaml", forms / "engine_forms.yaml")
    listed = [{"code": f["code"]} for f in plugins.engine_forms()]
    (forms / "plugins" / "__init__.py").write_text(
        '"""서식 플러그인 이름표(tools/sync_engine.py 가 만듦)."""\n'
        f"_FORMS = {listed!r}\n\n\ndef engine_forms():\n    return [dict(x) for x in _FORMS]\n", encoding="utf-8")

    tests = DEST / "tests"           # 시험끼리 ctax.tests.test_ar 를 불러서 패키지 안에 둔다
    tests.mkdir(parents=True)
    (tests / "__init__.py").write_text("", encoding="utf-8")
    shutil.copy2(src / "tests" / "conftest.py", tests / "conftest.py")
    for f in sorted((src / "tests").glob("test_ar*.py")):
        shutil.copy2(f, tests / f.name)

    repo = src.parent.parent
    commit = subprocess.run(["git", "-C", str(repo), "log", "-1", "--format=%h %ad %s", "--date=short", "--", "법인세/ctax"],
                            capture_output=True, text=True, encoding="utf-8").stdout.strip()
    (ROOT / "engine" / "VENDORED.json").write_text(json.dumps(
        {"source": "kernelspaces/academy-product 법인세/ctax", "commit": commit,
         "copied": COPY_FILES + [d + "/" for d in COPY_DIRS] + ["score/match.py"], "stubs": ["forms/plugins", "forms/engine_forms.yaml"]},
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"engine/ctax 를 만들었습니다({commit})")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1]))
