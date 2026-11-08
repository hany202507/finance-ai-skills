"""Claude 앱에 올리는 「법인세-분석적검토」 스킬 꾸러미를 만든다. `python -m ctax.ar.pack_review <내보낼 폴더>`.

담는 것: 받은자료 읽기 intake · 전기 신고서 읽기 prior · 분석적 검토 ar · 요청자료 request · 선택 choice ·
분석적 검토가 부르는 조서 wp(기납부세액 · 감가상각 등 규칙)와 wp 가 쓰는 score.match · 서식 forms(서식 이름 · 엔진이 채우는
서식) · 합성 회사 demo.
만드는 방법은 `ctax/skillpack.py`. 결과는 `<폴더>/corporate-tax-review/` 와 `.zip`.
"""
from __future__ import annotations

import sys
from pathlib import Path

from ctax import skillpack

NAME = "법인세-분석적검토"
APP_NAME = "corporate-tax-review"
PACKAGES = ("intake", "prior", "ar", "request", "choice", "wp", "score", "forms", "demo")
# `set`(ctax.choice.cli)은 점검 status · 화면 ui 패키지를 불러 꾸러미에 넣지 않는다. choice 는 store(선택.json 읽기)만 쓴다
COMMANDS = {"review": "ctax.ar.review", "read": "ctax.intake.cli", "prior": "ctax.prior.cli", "ar": "ctax.ar.cli",
            "request": "ctax.request.cli"}


def build(out: Path) -> Path:
    return skillpack.build(out, name=NAME, app_name=APP_NAME, packages=PACKAGES, commands=COMMANDS, default="review",
                           requirements="openpyxl>=3.1\npymupdf>=1.24\npyyaml>=6\n",
                           doc="분석적 검토 스킬 꾸러미에 담은 ctax 일부.")


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print("사용법: python -m ctax.ar.pack_review <내보낼 폴더>")
        return 2
    z = build(Path(argv[0]).resolve())
    print(f"꾸러미: {z} ({z.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
