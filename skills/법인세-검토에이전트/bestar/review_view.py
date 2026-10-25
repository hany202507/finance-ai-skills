# -*- coding: utf-8 -*-
"""분석적 검토 화면(한 파일). assets/review.html 템플릿에 화면 자료(DATA)와 MODE 를 넣는다.

화면은 외부 파일 없이 열린다(구글 글꼴만 받아지면 쓰고, 없으면 시스템 글꼴).
MODE "static" 은 화면 안에서만 바뀌는 읽기 전용, "live" 는 답 · 반영을 같은 폴더의
api/decide · api/accept · api/undo 로 보내고 응답(새 DATA 전체)으로 다시 그린다.
자료 꼴은 tools/sample_review.json 을 본다.
"""
from __future__ import annotations

import json
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parents[1] / "assets" / "review.html"
DATA_SLOT = "/*DATA*/null"
MODE_SLOT = '/*MODE*/"static"'
MODES = ("static", "live")


def _json(value) -> str:
    # 글 안의 </script> · <!-- 가 스크립트를 끊지 않게 < 를 모두 \u003c 로 쓴다. JSON 과 JS 둘 다 같은 글로 읽는다.
    text = json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
    return text.replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def render(data: dict, mode: str = "static") -> str:
    if mode not in MODES:
        raise ValueError(f"mode 는 {' · '.join(MODES)} 가운데 하나여야 합니다: {mode!r}")
    html = TEMPLATE.read_text(encoding="utf-8")
    for slot in (DATA_SLOT, MODE_SLOT):
        if html.count(slot) != 1:
            raise ValueError(f"{TEMPLATE} 에 자리 {slot} 가 한 번 있어야 합니다")
    # 자료를 먼저 넣으면 자료 글 안의 MODE 자리 글자가 바뀔 수 있으니 MODE 를 먼저 넣는다.
    html = html.replace(MODE_SLOT, _json(mode))
    return html.replace(DATA_SLOT, _json(data), 1)


def write(data: dict, path, mode: str = "static") -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(data, mode), encoding="utf-8")
    return path
