"""회사 맥락을 다음 해 신고 건에 쓰는 곳.

- `suggestions(case)`: 조서(`ctax wp`)가 읽는 작년 답 {(조서 id, key): {...}}. 이 신고 건 사업연도보다 앞선 해의 가장 늦은 답만 쓴다.
  조서는 그 값을 노란 칸 기본값으로 쓰고 「작년 답, 회계사 확인 전」 을 확인할 것에 올린다(wp.model.Paper.take). 회계사 값이 아니다.
- `_색인/맥락확인.json`: 회계사가 작년 답을 확인한 칸. {"rows": {"<id>": {"value", "fy", "by", "at"}}}. 확인할 때의 값과 사업연도가
  지금 작년 답과 같아야 확인으로 본다(그 뒤 맥락이 바뀌면 확인은 힘을 잃는다).
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from ..case import INDEX, Case
from . import catalog, store

CONFIRM = "맥락확인.json"


def read_confirm(case: Case) -> dict:
    try:
        raw = json.loads((case.root / INDEX / CONFIRM).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    rows = raw.get("rows") if isinstance(raw, dict) else None
    return {str(k): v for k, v in (rows or {}).items() if isinstance(v, dict)}


def write_confirm(case: Case, rows: dict) -> Path:
    p = case.index_path(CONFIRM)
    p.write_text(json.dumps({"rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    return p


def candidates(case: Case) -> list[dict]:
    """이 신고 건에 쓸 작년 답 [{id, kind, paper, key, target, value, fy, by, at, from, confirmed, ...}]. 조서 칸 것만."""
    if not case.fy:
        return []
    data = store.read(case.root)
    done = read_confirm(case)
    out = []
    for fid, fact in sorted(data["facts"].items()):
        paper, key = str(fact.get("paper") or ""), str(fact.get("key") or "")
        if paper == catalog.COMPANY or catalog.engine_kind(paper, key) is None:
            continue
        prev = store.before(fact, case.fy)
        if prev is None or str(prev.get("value") or "").startswith("섞임"):
            continue
        ok = done.get(fid) or {}
        confirmed = ok.get("value") == prev.get("value") and str(ok.get("fy")) == str(prev.get("fy"))
        out.append({"id": fid, "kind": fact.get("kind", ""), "paper": paper, "key": key, "target": fact.get("target", ""),
                    **{k: prev.get(k, "") for k in store.HISTORY_FIELDS if k != "case"}, "case": prev.get("case", ""),
                    "confirmed": confirmed, "confirmed_by": ok.get("by", "") if confirmed else "",
                    "confirmed_at": ok.get("at", "") if confirmed else ""})
    return out


def suggestions(case: Case) -> dict:
    """{(조서 id, key): 작년 답}. 회사 맥락이 없으면 빈 dict."""
    try:
        return {(c["paper"], c["key"]): c for c in candidates(case)}
    except Exception:          # noqa: BLE001  맥락 파일이 깨져도 조서는 엔진 기본값으로 돈다
        return {}


def confirm(case: Case, ids: list[str], by: str) -> list[dict]:
    """작년 답을 확인한다. 확인한 줄 목록. 없는 id 는 ValueError."""
    have = {c["id"]: c for c in candidates(case)}
    bad = [i for i in ids if i not in have]
    if bad:
        raise ValueError("작년 답이 없는 칸입니다: " + ", ".join(bad))
    rows = read_confirm(case)
    now = datetime.now().isoformat(timespec="seconds")
    done = []
    for i in ids:
        c = have[i]
        rows[i] = {"value": c["value"], "fy": c["fy"], "by": by, "at": now}
        done.append(c)
    write_confirm(case, rows)
    return done


def unconfirm(case: Case, ids: list[str]) -> int:
    rows = read_confirm(case)
    n = sum(1 for i in ids if rows.pop(i, None) is not None)
    write_confirm(case, rows)
    return n


def used(case: Case) -> list[dict]:
    """조서가 작년 답으로 채운 칸(조정.json papers[].context). [{paper, sheet, key, value, engine, state, fy, by, at, id}]."""
    try:
        adj = case.read_json("조정.json") if case.has("조정.json") else {}
    except ValueError:
        return []
    out = []
    for p in adj.get("papers") or []:
        for key, c in (p.get("context") or {}).items():
            out.append({"paper": p.get("id", ""), "sheet": p.get("sheet", ""), "key": key, **c})
    return out
