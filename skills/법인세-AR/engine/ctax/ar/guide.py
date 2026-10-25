"""AR 가이드 원문(guide.yaml)과 서식 이름표(forms.yaml) 읽기."""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent


@lru_cache(maxsize=1)
def load_guide() -> list[dict]:
    """가이드 줄 [{id, cell, section, title, text, raw}]. 순서는 엑셀 순서.

    title: 계정별 줄은 묶음 이름(「16) 기업업무추진비」), 1절 · 2절 머리 줄은 「:」 앞 글(없으면 줄 전체).
    text: 계정별 줄은 원문 앞의 「: 」 와 끝 빈칸을 뗀 글, 1절 · 2절 머리 줄은 원문 그대로. raw 는 엑셀 칸 그대로.
    """
    data = yaml.safe_load((HERE / "guide.yaml").read_text(encoding="utf-8"))
    sections = [s["raw"] for s in data["sections"]]
    out = []
    for ln in data["lines"]:
        gid = str(ln["id"])
        raw = ln["raw"]
        section = sections[0] if gid.startswith("1-") else sections[1]
        if ln.get("group"):
            title = ln["group"]
            text = re.sub(r"^\s*:\s*", "", raw).rstrip()
        else:
            head = raw.split(":", 1)[0].strip() if ":" in raw else raw.strip()
            title, text = head, raw
        out.append({"id": gid, "cell": ln["cell"], "section": section, "title": title, "text": text, "raw": raw})
    return out


@lru_cache(maxsize=1)
def form_names() -> dict[str, str]:
    data = yaml.safe_load((HERE / "forms.yaml").read_text(encoding="utf-8"))
    return {str(k): str(v) for k, v in (data.get("names") or {}).items()}


def form_name(code: str) -> str:
    return form_names().get(str(code), str(code))
