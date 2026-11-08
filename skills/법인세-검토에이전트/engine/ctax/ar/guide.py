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
def form_catalog() -> dict:
    """서식 총괄표 정본(forms.yaml 통째). names · groups · tiers · unresolved · request_default(11-01, 설계안 7.1절)."""
    return yaml.safe_load((HERE / "forms.yaml").read_text(encoding="utf-8")) or {}


def form_names() -> dict[str, str]:
    return {str(k): str(v) for k, v in (form_catalog().get("names") or {}).items()}


def form_name(code: str) -> str:
    return form_names().get(str(code), str(code))


OTHER_GROUP = "그 밖의 명세서"


@lru_cache(maxsize=1)
def _group_of() -> dict[str, str]:
    return {str(c): str(g.get("name")) for g in (form_catalog().get("groups") or []) for c in (g.get("codes") or [])}


def form_groups() -> list[str]:
    """분류 이름 차례(총괄표 묶음 순서)."""
    return [str(g.get("name")) for g in (form_catalog().get("groups") or [])]


def form_group(code: str) -> str:
    """서식의 분류. 묶음에 없는 코드는 「그 밖의 명세서」."""
    return _group_of().get(str(code), OTHER_GROUP)


def form_tier(code: str) -> tuple[str, bool]:
    """(티어, 회계사 확인 여부). tiers 에 없는 코드는 (「미정」, False)."""
    t = (form_catalog().get("tiers") or {}).get(str(code)) or {}
    return str(t.get("tier") or "미정"), bool(t.get("confirmed", False))


def request_default(code: str) -> bool:
    """서식이 「해당」 이면 결정적으로 요청할 자료가 있는 서식인가(request 단계가 읽는다)."""
    return bool((form_catalog().get("request_default") or {}).get(str(code), False))
