# -*- coding: utf-8 -*-
"""판단 필요 항목에 AI 가 붙이는 질문지(화면 왼쪽 「확인할 것」). 고르는 것은 회계사다.

{"title": "기계장치를 어떻게 들였나요", "description": "취득 방식에 따라 투자세액공제가 달라져요.",
 "multiple": false, "allow_other": true,
 "options": [{"value": "new", "label": "신품을 구매했어요", "effect": "통합투자세액공제 대상"}]}
"""
from __future__ import annotations

from bestar import numbers


def problems(ch, label: str, nums: set[int], cells: dict | None = None) -> list[str]:
    """cells 는 link.cells(c). 보기에 sets(고르면 바꿀 조서 노란 칸)가 있으면 칸이 조서에 있는지 본다."""
    if ch is None:
        return []
    if not isinstance(ch, dict):
        return [f"{label}: choices 는 사전이어야 합니다"]
    out = []
    if not str(ch.get("title") or "").strip():
        out.append(f"{label}: choices.title 이 비었습니다")
    opts = ch.get("options")
    if not isinstance(opts, list) or not 2 <= len(opts) <= 6:
        out.append(f"{label}: choices.options 는 2 ~ 6개입니다")
        opts = []
    vals = [o.get("value") for o in opts if isinstance(o, dict)]
    if len(vals) != len(opts) or any(not str(v or "").strip() for v in vals) or len(set(vals)) != len(vals):
        out.append(f"{label}: choices.options 의 value 는 비지 않고 겹치지 않아야 합니다")
    if any(not str((o or {}).get("label") or "").strip() for o in opts):
        out.append(f"{label}: choices.options 의 label 이 비었습니다")
    if any(not str((o or {}).get("effect") or "").strip() for o in opts):
        out.append(f"{label}: choices.options 마다 effect(고르면 무엇이 달라지는지)를 씁니다")
    for k in ("multiple", "allow_other"):
        if k in ch and not isinstance(ch[k], bool):
            out.append(f"{label}: choices.{k} 는 true 나 false 입니다")
    plain = {**ch, "options": [{k: v for k, v in o.items() if k != "sets"} if isinstance(o, dict) else o for o in opts]}
    out += numbers.style_problems(plain, f"{label} choices")
    out += numbers.amount_problems(plain, nums, f"{label} choices", skip=("value",))
    from bestar import link
    for o in opts:
        if isinstance(o, dict) and o.get("sets") is not None:
            out += link.problems(o["sets"], cells or {}, f"{label} choices 보기 {o.get('value')}")
    return out
