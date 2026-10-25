# -*- coding: utf-8 -*-
"""화면에서 회계사가 한 판단(질문 답 · 세무조정 반영)을 _색인/AR_단계/판단.json 에 남긴다.

화면의 uid(issue:3 · adj:0 · added:a2 · credit:1 · sme)는 엔진을 다시 돌리면 번호가 바뀔 수 있어서
저장은 바뀌지 않는 key 로 한다(이슈 key · 조정 조서와 과목 · 제도 이름).
"""
from __future__ import annotations

from datetime import datetime

from bestar import paths

FILE = "판단.json"


def path(c):
    return paths.steps_dir(c) / FILE


def load(c) -> dict:
    d = paths.read_json(path(c), {}) or {}
    d.setdefault("decisions", {})
    d.setdefault("accepted", {})
    return d


def save(c, d: dict) -> None:
    paths.write_json(path(c), d)


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def stable_keys(ar: dict, adjustments: list[dict], credits: dict) -> dict[str, str]:
    """화면 uid → 저장 key."""
    out = {"sme": "sme"}
    for i in ar.get("issues", []):
        out[f"issue:{i['no']}"] = f"issue|{i.get('key')}|{i.get('rule')}"
    for n, a in enumerate(adjustments):
        out[f"adj:{n}"] = f"adj|{a.get('paper')}|{a.get('side')}|{a.get('subject')}|{a.get('kind')}"
    for n, x in enumerate((credits or {}).get("items") or [], 1):
        out[f"credit:{n}"] = f"credit|{x.get('name')}"
    return out


def decide(c, key: str, value=None, values=None, other=None, by: str = "회계사") -> None:
    d = load(c)
    entry = {"at": now(), "by": by}
    if values is not None:
        entry["values"] = list(values)
    elif value is not None:
        entry["value"] = value
    if other:
        entry["other"] = str(other)
    d["decisions"][key] = entry
    save(c, d)


def accept(c, keys: list[str], by: str = "회계사") -> None:
    d = load(c)
    for k in keys:
        d["accepted"][k] = {"at": now(), "by": by}
    save(c, d)


def undo(c, key: str) -> None:
    d = load(c)
    d["decisions"].pop(key, None)
    d["accepted"].pop(key, None)
    save(c, d)
