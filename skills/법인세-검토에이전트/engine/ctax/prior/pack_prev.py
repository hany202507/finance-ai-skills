"""Claude 앱에 올리는 「법인세-전기읽기」 스킬 꾸러미를 만든다. `python -m ctax.prior.pack_prev <내보낼 폴더>`.

담는 것: 전기 신고서 읽기 prior(합성 예시 PDF 포함) · 서식 정의와 계산기 forms(검산에 쓴다).
만드는 방법은 `ctax/skillpack.py`. 결과는 `<폴더>/corporate-tax-prior-return/` 와 `.zip`.
"""
from __future__ import annotations

import sys
from pathlib import Path

from ctax import skillpack

NAME = "법인세-전기읽기"
APP_NAME = "corporate-tax-prior-return"
PACKAGES = ("prior", "forms")
COMMANDS = {"prev": "ctax.prior.skill", "prior": "ctax.prior.cli"}


def build(out: Path) -> Path:
    return skillpack.build(out, name=NAME, app_name=APP_NAME, packages=PACKAGES, commands=COMMANDS, default="prev",
                           requirements="openpyxl>=3.1\npymupdf>=1.24\npyyaml>=6\n",
                           doc="전기 읽기 스킬 꾸러미에 담은 ctax 일부.")


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print("사용법: python -m ctax.prior.pack_prev <내보낼 폴더>")
        return 2
    z = build(Path(argv[0]).resolve())
    print(f"꾸러미: {z} ({z.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
