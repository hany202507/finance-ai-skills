"""4000 표지 절차의 「해당 여부」 AI 제안(2026-10-12).

묶음 에이전트가 회사 자료를 보고 낸 제안을 `_색인/절차제안.json` 에 쌓고, `wp make` 가 표지의 「AI 제안(확인 전)」 열에 적는다.
제안은 기입란에 넣지 않는다. 해당 여부는 감사인이 노란 칸에 적고, 그 값이 제안과 달라도 엔진은 아무것도 하지 않는다.
넣는 길은 apply 하나다. 하나라도 어긋나면 아무것도 쓰지 않는다(index.apply_patch 와 같은 태도).

  steps(no)             그 조서 표지의 절차 [{part, no, key, step, assertions}]. Part 1 은 「감사결론」 줄을 뺀다(표지에 없다)
  apply(d, patch)       {"suggestions": [{workpaper, part, step, suggest, reason, sources}]} 를 검증해 넣는다
  for_wp(d, no)         {(part, 절차 이름): 제안}. 표지와 `wp steps` 가 쓴다
  cell_text(s)          표지 칸에 적는 글 「해당 없음: <근거> (자료: …)」

patch 의 step 에 적는 절차 이름은 표지 기입란 이름에 쓰는 것과 같다(절차 글 첫 줄의 앞 30자, common.short). 절차 번호(3 · "3" · "3.")로도 가리킬 수 있다.
근거 문장에 금액으로 보이는 숫자가 있으면 거부한다. 숫자는 엔진이 조서에 넣은 것만 쓴다.
"""
from __future__ import annotations

import re
from pathlib import Path

from .. import figures, folder
from ..errors import IntakeError
from . import common

FILE = "절차제안.json"
CHOICES = ("해당", "해당 없음", "판단 자료 없음")
NEEDS_SOURCE = "해당 없음"                 # 자료 없이 절차를 빼지 못하게 한다
ITEM_KEYS = {"workpaper", "part", "step", "suggest", "reason", "sources"}
STEP_NO = re.compile(r"^\s*(\d+)\s*[.)]")

# 금액으로 보는 숫자: 쉼표 낀 숫자, 바로 뒤에 원 · 천원 · 백만원 · 억원이 붙은 숫자, 억 · 천만 · 백만 단위 숫자, 7자리 이상 숫자.
# 날짜(2025-12-31 · 2025년 12월 31일) · 조서번호(4000C · 3320) · 계정코드(108 · 10800) · 쪽 번호(12쪽)는 걸리지 않는다.
# 「108 원장」 처럼 띄어 쓴 「원」 은 단위로 보지 않는다(원장 · 원천세 · 원가)
AMOUNT_RES = (re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?"),
              re.compile(r"(?<!제)(?<![\d.])\d[\d.]*\s*(?:조|억|천만|백만|십만|만|천|백)\s*원"),
              re.compile(r"\d[\d.]*원"),
              re.compile(r"(?<!제)(?<![\d.])\d[\d.]*\s*(?:억|천만|백만)"),
              re.compile(r"\d{7,}"))


class Rejected(IntakeError):
    """제안 patch 를 받아들이지 않았다. problems 에 까닭이 한국어 문장으로 있다. 아무것도 쓰지 않았다."""

    def __init__(self, problems: list[str]):
        super().__init__("\n".join(problems))
        self.problems = problems


def amount_in_text(text: str) -> str | None:
    """근거 문장에 금액으로 보이는 숫자가 있으면 그 부분을 돌려준다."""
    for rx in AMOUNT_RES:
        m = rx.search(text)
        if m:
            return m.group(0).strip()
    return None


# ---------------------------------------------------------------- 절차 이름
def steps(no: str) -> list[dict]:
    """그 조서 표지에 실리는 절차. 한공회 4000 Part 1(「감사결론」 줄 뺌) · Part 2 순서다. 영역에 절차가 없으면 빈 목록."""
    from . import lead

    code = no[4:]
    out = []
    for part, items in ((1, (lead.procedures().get(code) or {}).get("items", [])),
                        (2, (lead.procedures2().get(code) or {}).get("items", []))):
        for it in items:
            if part == 1 and "감사결론" in it["step"]:
                continue
            m = STEP_NO.match(it["step"])
            out.append({"part": part, "no": int(m.group(1)) if m else None, "key": common.short(it["step"], 30),
                        "step": it["step"], "assertions": list(it.get("assertions") or [])})
    return out


def _find(no: str, part, step) -> dict | None:
    """patch 의 step(절차 이름 또는 절차 번호)이 가리키는 절차. 없으면 None."""
    cands = [s for s in steps(no) if s["part"] == part]
    if isinstance(step, bool):
        return None
    if isinstance(step, int):
        return next((s for s in cands if s["no"] == step), None)
    if not isinstance(step, str) or not step.strip():
        return None
    t = step.strip()
    hit = next((s for s in cands if t in (s["key"], s["step"])), None)
    if hit is None and re.fullmatch(r"\d+\s*[.)]?", t):
        hit = next((s for s in cands if s["no"] == int(re.match(r"\d+", t).group(0))), None)
    return hit


# ---------------------------------------------------------------- 읽기
def load(d: Path) -> dict:
    return common.idx(d, FILE) or {"format_version": 1, "updated_at": None, "suggestions": []}


def for_wp(d: Path, no: str) -> dict:
    """{(part, 절차 이름): 제안}. 지금 절차표에 없는 절차 이름의 제안(절차표가 바뀌기 전 것)도 그대로 돌려준다. 표지는 맞는 것만 쓴다."""
    return {(s["part"], s["step"]): s for s in load(d)["suggestions"] if s["workpaper"] == no}


def cell_text(s: dict | None) -> str | None:
    """표지 「AI 제안(확인 전)」 칸의 글. 제안이 없으면 None(빈칸)."""
    if not s:
        return None
    src = f" (자료: {', '.join(s['sources'])})" if s.get("sources") else " (자료: 없음)"
    return f"{s['suggest']}: {s['reason']}{src}"


# ---------------------------------------------------------------- 넣기
def _check(item, i: int, received: set[str], seen: set) -> tuple[list[str], dict | None]:
    where = f"{i + 1}번째 제안"
    if not isinstance(item, dict):
        return [f"{where}: 객체여야 합니다"], None
    probs = []
    extra = sorted(set(item) - ITEM_KEYS)
    if extra:
        probs.append(f"{where}: 쓸 수 없는 항목입니다: {', '.join(extra)} (쓸 수 있는 것: {', '.join(sorted(ITEM_KEYS))})")
    no, part, step = item.get("workpaper"), item.get("part"), item.get("step")
    hit = None
    if not isinstance(no, str) or not folder._is_area(no):
        probs.append(f"{where}: workpaper 는 4000 영역 조서번호여야 합니다(4000C · 4000P 등): {no}")
    elif not steps(no):
        probs.append(f"{where}: 한공회 4000 절차에 없는 영역입니다: {no}")
    elif isinstance(part, bool) or part not in (1, 2):
        probs.append(f"{where}({no}): part 는 1(절차 예시) 또는 2(추가 고려 절차)입니다: {part}")
    else:
        where = f"{where}({no} Part {part})"
        hit = _find(no, part, step)
        if hit is None:
            probs.append(f"{where}: 이 영역 절차에 없는 step 입니다: {step}. step 에 적을 값은 `python -m audit wp steps <감사 폴더> {no}` 로 확인해 주십시오")
        elif (no, part, hit["key"]) in seen:
            probs.append(f"{where}: 같은 절차의 제안이 patch 에 두 번 있습니다: {hit['key']}")
        else:
            seen.add((no, part, hit["key"]))
    sug = item.get("suggest")
    if sug not in CHOICES:
        probs.append(f"{where}: suggest 는 {' · '.join(CHOICES)} 가운데 하나입니다: {sug}")
    reason = item.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        probs.append(f"{where}: reason(근거 문장)이 비어 있습니다")
    else:
        amt = amount_in_text(reason)
        if amt:
            probs.append(f"{where}: reason 에 금액으로 보이는 숫자 '{amt}' 가 있습니다. 숫자는 엔진이 조서에 넣은 것만 씁니다: {reason.strip()}")
    sources = item.get("sources", [])
    if not isinstance(sources, list) or not all(isinstance(x, str) and x.strip() for x in sources):
        probs.append(f"{where}: sources 는 받은자료 경로 목록입니다")
        sources = []
    bad = [x for x in sources if x not in received]
    if bad:
        probs.append(f"{where}: 색인(문서목록.json)에 없는 받은자료입니다: {', '.join(bad)}")
    if sug == NEEDS_SOURCE and not sources:
        probs.append(f"{where}: 「{NEEDS_SOURCE}」 은 근거 자료(sources)가 하나 이상 있어야 합니다. 자료가 없으면 「판단 자료 없음」 으로 적어 주십시오")
    if probs or hit is None:
        return probs, None
    return [], {"workpaper": no, "part": part, "step": hit["key"], "step_no": hit["no"], "suggest": sug, "reason": reason.strip(),
                "sources": list(dict.fromkeys(sources))}


def apply(d: Path, patch: dict, now: str | None = None, source: str | None = None) -> dict:
    """제안 patch 를 `_색인/절차제안.json` 에 넣는다. 하나라도 어긋나면 Rejected 를 올리고 아무것도 쓰지 않는다.
    같은 조서 · 같은 절차의 제안은 새 것으로 바꾼다. 넣은 제안은 basis AI · confirmed false 다. 조서는 다시 만들지 않는다."""
    d = Path(d)
    at = now or folder._now()
    if not isinstance(patch, dict) or not isinstance(patch.get("suggestions"), list) or not patch["suggestions"]:
        raise Rejected(['patch 는 {"suggestions": [...]} 꼴이고 제안이 하나 이상 있어야 합니다'])
    extra = sorted(set(patch) - {"suggestions"})
    probs = [f"patch 맨 위에 쓸 수 없는 항목입니다: {', '.join(extra)}"] if extra else []
    received = {f["path"] for f in figures._docs(d)["files"] if f.get("role") == "received"}
    seen: set = set()
    new = []
    for i, item in enumerate(patch["suggestions"]):
        p, rec = _check(item, i, received, seen)
        probs += p
        if rec:
            new.append({**rec, "basis": "AI", "confirmed": False, "at": at})
    if probs:
        raise Rejected(probs)

    data = load(d)
    keys = {(x["workpaper"], x["part"], x["step"]) for x in new}
    replaced = sum(1 for x in data["suggestions"] if (x["workpaper"], x["part"], x["step"]) in keys)
    data["suggestions"] = [x for x in data["suggestions"] if (x["workpaper"], x["part"], x["step"]) not in keys] + new
    data["suggestions"].sort(key=lambda x: (x["workpaper"], x["part"], x.get("step_no") or 0, x["step"]))
    data.update(format_version=1, updated_at=at)
    import jsonschema

    try:                                                 # 앞서 쌓인 파일이 형식에 안 맞으면 쓰지 않는다
        jsonschema.validate(data, folder._schema()[FILE])
    except jsonschema.ValidationError as e:
        path = "/".join(str(x) for x in e.absolute_path)
        raise Rejected([f"적용하면 _색인/{FILE} 형식이 깨집니다({path}): {e.message}"]) from None
    common.put_idx(d, FILE, data)
    nos = sorted({x["workpaper"] for x in new})
    case = common.case(d)
    if case:
        what = f"AI 절차 제안 {len(new)}건을 넣었습니다(확인 전): " + ", ".join(f"{no} {sum(1 for x in new if x['workpaper'] == no)}건" for no in nos)
        case.setdefault("log", []).insert(0, {"at": at, "who": "조서", "what": what, "read": [source] if source else [],
                                          "wrote": [f"_색인/{FILE}"]})
        common.put_idx(d, "감사건.json", case)
    folder.validate_index(d)
    return {"applied": len(new), "replaced": replaced, "workpapers": nos,
            "counts": {c: sum(1 for x in new if x["suggest"] == c) for c in CHOICES}}
