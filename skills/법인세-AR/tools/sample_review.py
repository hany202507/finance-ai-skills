# -*- coding: utf-8 -*-
"""분석적 검토 화면(assets/review.html) 시험용 html 을 만든다.

usage: python tools/sample_review.py [내보낼 html] [--live]
  기본 출력은 C:\\Users\\ptsjm\\bestar-view\\review_sample.html.
  자료는 tools/sample_review.json(가상 회사 (주)예시상사). 고객 자료는 쓰지 않는다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bestar import review_view  # noqa: E402

SAMPLE = ROOT / "tools" / "sample_review.json"
DEFAULT_OUT = Path(__file__).resolve().parents[1].parent / "bestar-view" / "review_sample.html"  # 저장소 밖


def main(argv: list[str]) -> int:
    live = "--live" in argv
    rest = [a for a in argv if a != "--live"]
    if len(rest) > 1:
        print(__doc__)
        return 2
    out = Path(rest[0]) if rest else DEFAULT_OUT
    data = json.loads(SAMPLE.read_text(encoding="utf-8"))
    review_view.write(data, out, mode="live" if live else "static")
    print(f"썼습니다: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
