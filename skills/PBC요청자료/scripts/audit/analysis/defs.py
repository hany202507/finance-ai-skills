"""정의 YAML 읽기와 계정 매핑(R3, 2026-10-05).

  load(name)                    definitions/<name>.yaml (한 번 읽으면 캐시)
  map_account(code, name)       accounts.yaml 순서대로 id · 영역 · 구분 · 표시과목 기본값 · 근거
  resolve(spec, inputs)         {input: 키, ratio: r, else: ...} 꼴 값을 입력값으로 푼다. 없으면 MissingInput
  ref(path)                     analytics/relations/R-sales-ar/threshold 꼴 참조를 푼다
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import yaml

from ..errors import DefinitionError, MissingInput

DEFS = Path(__file__).resolve().parents[2] / "definitions"
ASSERTIONS = ("E/O", "C", "A/V", "CO", "RO", "P/CL")


@lru_cache(maxsize=None)
def _load_raw(name: str) -> dict:
    p = DEFS / f"{name}.yaml"
    if not p.exists():
        raise DefinitionError(f"정의 파일이 없습니다: {p}")
    return yaml.safe_load(p.read_text(encoding="utf-8"))


def load(name: str) -> dict:
    """정의 파일. 원본은 캐시하고, 지금 감사 건의 2700B 값은 부를 때마다 겹친다(2026-10-07, audit.params)."""
    from .. import params

    return params.overlay(name, _load_raw(name))


def norm(s) -> str:
    if s is None:
        return ""
    s = re.sub(r"\(.*?\)|\[.*?\]", "", str(s))
    return re.sub(r"\s+", "", s)


def code3(v) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    if isinstance(v, float):
        s = str(int(v))
    m = re.match(r"(\d{3,7})", s)
    return m.group(1)[:3] if m else None


def code_key(v) -> str | None:
    """분석 계정 열쇠: 계정코드 숫자 그대로(3~7자리). 보조계정(7자리 · 5자리)을 앞 3자리로 합치지 않는다(R8, 진단 #12)."""
    if v is None:
        return None
    s = str(int(v)) if isinstance(v, float) else str(v).strip()
    m = re.match(r"(\d{3,7})(?!\d)", s)
    return m.group(1) if m else None


def align_code(code: str | None, keys) -> str | None:
    """다른 자료의 계정코드를 시산표 열쇠에 맞춘다. 같으면 그대로, 앞 3자리가 같은 시산표 계정이 하나뿐이면 그 계정,
    아니면 그대로 둔다(3자리 코드 자료와 5 · 7자리 코드 자료가 섞일 때)."""
    if code is None or code in keys:
        return code
    c3 = code[:3]
    same = [k for k in keys if k[:3] == c3]
    return same[0] if len(same) == 1 else code


def section_of_code(code: str | None) -> str | None:
    if not code:
        return None
    k = int(str(code)[:3])
    for r in load("accounts")["code_sections"]:
        if r["from"] <= k <= r["to"]:
            return r["section"]
    return None


def map_account(code: str | None, name: str) -> dict:
    """계정 하나를 매핑한다. 이름이 먼저, 둘 이상이면 코드로 가르고, 이름이 안 맞으면 코드로 본다."""
    accs = load("accounts")["accounts"]
    n = norm(name)
    hits = [a for a in accs if any(re.search(p, n) for p in a.get("names", []))]
    basis = "계정명"
    code = str(code)[:3] if code else code
    if len(hits) > 1 and code:
        by_code = [a for a in hits if code in a.get("codes", [])]
        hits = by_code or hits[:1]
    if not hits and code:
        hits = [a for a in accs if code in a.get("codes", [])]
        basis = "계정코드"
    if not hits and code and str(code).isdigit():
        # 회사가 지은 이름이라 이름 · 코드 목록에 없으면 코드 범위로 잇는다(R8, accounts.yaml code_ranges)
        k = int(str(code)[:3])
        for r in load("accounts").get("code_ranges", []):
            if r["from"] <= k <= r["to"] and not any(x in n for x in r.get("not_names", [])):
                hits = [a for a in accs if a["id"] == r["id"]]
                basis = "계정코드 범위"
                break
    if not hits:
        return {"id": None, "area": None, "section": section_of_code(code), "label": None, "contra": False,
                "basis": "매핑 안 됨", "confidence": "low"}
    a = hits[0]
    return {"id": a["id"], "area": a.get("area"), "section": a["section"], "label": a.get("label"), "contra": bool(a.get("contra")),
            "basis": basis, "confidence": "high"}


def display_line(name: str, names: set[str] | None = None) -> tuple[str | None, str | None]:
    """표시과목 열이 없는 시산표 계정의 재무제표 표시과목(accounts.yaml display_lines). (표시과목, 근거) 없으면 (None, None).
    names: 같은 시산표의 계정명들(only_with · 보조계정 판정용)."""
    names = names or set()
    n = norm(name)
    if "_" in n:                     # 보조계정 '부모_꼬리': 부모 계정이 시산표에 있으면 부모로 본다
        parent = n.split("_")[0]
        if parent and parent in names:
            got = display_line(parent, names)
            return (got[0] or parent), "보조계정(부모 계정 " + parent + ")"
    for r in load("accounts").get("display_lines", []):
        if r.get("only_with") and norm(r["only_with"]) not in names:
            continue
        if any(re.search(p, n) for p in r["names"]):
            return r["line"], "accounts.yaml display_lines"
    return None, None


def area_name(area: str | None) -> str:
    return load("accounts")["areas"].get(area, area or "미매핑")


def resolve(spec, inputs: dict, key_hint: str = ""):
    """정의 값 하나를 숫자로 푼다. dict 가 아니면 그대로. 입력값이 없으면 MissingInput."""
    if not isinstance(spec, dict):
        return spec
    if "ref" in spec:
        return resolve(ref(spec["ref"]), inputs, key_hint)
    if "input" in spec:
        k = spec["input"]
        if k not in inputs or inputs[k] is None:
            if "else" in spec:
                return {"else": spec["else"]}
            raise MissingInput(k)
        v = inputs[k]
        r = spec.get("ratio", 1)
        if r is None:
            raise MissingInput(f"{key_hint} ratio")
        return v * r
    return spec


def ref(path: str):
    parts = path.split("/")
    doc = load(parts[0])
    cur = doc[parts[1]]
    if isinstance(cur, list):
        cur = next(x for x in cur if x.get("id") == parts[2])
        rest = parts[3:]
    elif isinstance(cur, dict) and "rules" in cur and len(parts) > 3:
        cur = next(x for x in cur["rules"] if x.get("id") == parts[2])
        rest = parts[3:]
    else:
        rest = parts[2:]
    for p in rest:
        cur = cur[p]
    return cur
