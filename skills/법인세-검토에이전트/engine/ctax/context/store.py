"""`<회사>/_회사맥락/맥락.json` 읽기 · 쓰기.

    {"format_version": 1, "company": "<회사 폴더 이름>", "updated_at": "...",
     "facts": {"<id>": {"id", "kind", "paper", "key", "target", "value", "fy", "by", "at", "from", "case", "note",
                        "history": [{"fy", "value", "by", "at", "from", "case", "note"}]}}}

- id 는 `<조서 id>|<key>`(조서 칸) 또는 `회사|<종류>/<대상>`(손으로 적은 것 · 신고 건에서 저절로 모은 것).
- history 는 사업연도마다 한 줄이다. 같은 사업연도를 다시 모으면 그 줄을 바꾼다. 맨 위 value · fy · by · at 은 가장 늦은 사업연도 줄이다.
- 값은 글 또는 dict(유가증권 취득일 · 주식수 · 취득가액 같은 것). 금액을 새로 계산하지 않는다. 회계사가 적은 그대로다.
- 내년메모처럼 AI 가 쓴 줄에만 선택 키 `confirmed`(참거짓)가 있다(10-30). 다른 줄의 꼴은 그대로다.
- 신고 건 폴더 밖에 두고 저장소에 넣지 않는다(고객 자료).
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

FORMAT_VERSION = 1
DIR = "_회사맥락"
FILE = "맥락.json"
HISTORY_FIELDS = ("fy", "value", "by", "at", "from", "case", "note")


def company_dir(folder: str | Path) -> Path:
    """신고 건 폴더(`<회사>/<연도> 법인세`)나 회사 폴더를 받아 회사 폴더."""
    p = Path(folder).resolve()
    if re.match(r"\d{4}\s*법인세", p.name):
        return p.parent
    return p


def path(folder: str | Path) -> Path:
    return company_dir(folder) / DIR / FILE


def empty(company: str = "") -> dict:
    return {"format_version": FORMAT_VERSION, "company": company, "updated_at": "", "facts": {}}


def read(folder: str | Path) -> dict:
    """맥락.json. 없거나 깨졌으면 빈 것."""
    p = path(folder)
    out = empty(company_dir(folder).name)
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return out
    if isinstance(raw, dict) and isinstance(raw.get("facts"), dict):
        out["facts"] = {str(k): v for k, v in raw["facts"].items() if isinstance(v, dict)}
        out["updated_at"] = str(raw.get("updated_at") or "")
        out["company"] = str(raw.get("company") or out["company"])
    return out


def write(folder: str | Path, data: dict) -> Path:
    p = path(folder)
    p.parent.mkdir(parents=True, exist_ok=True)
    data["updated_at"] = datetime.now().isoformat(timespec="seconds")
    p.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return p


def fy_key(fy) -> int:
    try:
        return int(str(fy)[:4])
    except ValueError:
        return 0


def put(data: dict, fid: str, *, kind: str, paper: str, key: str, target: str, entry: dict) -> tuple[dict, str]:
    """사실 하나에 사업연도 한 줄을 넣는다(같은 사업연도 줄은 바꾼다). (사실, 「새로」 · 「바뀜」 · 「같음」)."""
    row = {f: entry.get(f, "") for f in HISTORY_FIELDS}
    if "confirmed" in entry:
        row["confirmed"] = bool(entry["confirmed"])
    fact = data["facts"].get(fid)
    if fact is None:
        fact = {"id": fid, "kind": kind, "paper": paper, "key": key, "target": target, "history": []}
        data["facts"][fid] = fact
        how = "새로"
    else:
        old = next((h for h in fact["history"] if str(h.get("fy")) == str(row["fy"])), None)
        how = "같음" if old and old.get("value") == row["value"] else "바뀜"
        if how == "같음":
            return fact, how
    fact["history"] = sorted([h for h in fact["history"] if str(h.get("fy")) != str(row["fy"])] + [row],
                             key=lambda h: fy_key(h.get("fy")))
    fact.update({k: v for k, v in fact["history"][-1].items()})
    fact["kind"], fact["target"] = kind, target
    return fact, how


def before(fact: dict, fy) -> dict | None:
    """사업연도 fy 보다 앞선 해의 가장 늦은 줄. 없으면 None."""
    n = fy_key(fy)
    rows = [h for h in fact.get("history") or [] if fy_key(h.get("fy")) and fy_key(h.get("fy")) < n]
    return rows[-1] if rows else None


def show_value(v) -> str:
    if isinstance(v, dict):
        return " · ".join(f"{k} {x}" for k, x in v.items())
    return str(v)
