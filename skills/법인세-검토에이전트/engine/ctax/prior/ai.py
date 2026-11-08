"""파서가 없는 서식(또는 스캔본)을 스킬(Claude)이 쪽 그림을 보고 읽을 때 쓰는 틀과 받은 값 넣기.

  python -m ctax prior <신고 건> --template <서식코드> [--out <파일>]
      그 서식 정의의 란 코드 · 이름 목록과 답 틀을 `_색인/전기_틀_<서식코드>.json` 에 쓴다.
  python -m ctax prior <신고 건> --merge-ai <답.json>
      답을 검사(verify.def_checks · text_checks)에 통과시켜 전기.json 에 넣는다. 값은 cells[서식] · rows[서식],
      출처는 ai[서식] = {by: "ai", confirmed: false, ...}, 검사 결과는 problems(by "ai"). 엔진이 읽은 서식은 받지 않는다.

답 꼴(한 서식 또는 {"forms": [...]})
  {"form": "9", "pages": [31, 32],
   "values": {"01": 1200000, "02": null, "03": "absent", ...},     모든 란에 답한다. 칸은 있는데 비면 null, 칸 자체가 없으면 "absent"
   "records": [{"1": "과목", "2": 300000}],                          명세(여러 줄) 란은 줄마다 한 dict
   "uncertain": ["02"]}                                               확신이 없는 란 코드

숫자는 엔진만 만든다는 원칙(CLAUDE.md)에 따라 여기 들어오는 값은 문서 판독이고 confirmed false 다. 확인은 회계사가 한다.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from ctax.prior import verify

ABSENT = "absent"
HOW = [
    "서식 쪽 그림을 보고 values 의 모든 란에 답한다. 란 코드는 items 의 code 다(서식에 인쇄된 번호와 다를 수 있으니 name 으로 맞춘다).",
    "칸은 있는데 비어 있으면 null, 그 판 서식에 칸 자체가 없으면 \"absent\" 로 적는다. 0 이 찍혀 있으면 0 이다.",
    "금액은 원 단위 정수로 적는다. 음수(△ · 괄호 · -)는 - 를 붙인다. 쉼표는 있어도 된다.",
    "rate 란은 인쇄된 대로(19% 면 \"19%\" 또는 0.19) 적는다. text 란은 인쇄된 글 그대로 적는다.",
    "여러 줄 명세(rows 가 true 인 란)는 records 에 줄마다 {란 코드: 값} 하나씩 적는다. 소계 · 합계 줄은 values 의 합계 란에 적는다.",
    "읽기 어렵거나 확신이 없는 란은 값을 적고 그 코드를 uncertain 에 넣는다. 지어내지 않는다.",
    "values 의 숫자는 쪽 글자 대조(쪽에 없는 1,000원 이상 금액)와 정의 계산식 검산을 거쳐 confirmed false 로 들어간다.",
]


# ---------------------------------------------------------------- 틀

def template(code: str, prior: dict | None) -> dict:
    """서식 코드 → 틀(dict). 정의가 없으면 KeyError."""
    f, where = verify.defn(code)
    if f is None:
        raise KeyError(code)
    pages = _pages_of(prior or {}, code)
    singles = [it for it in f.items if not it.rows]
    rows = [it for it in f.items if it.rows]
    items = [{"code": it.code, "name": re.sub(r"\s+", " ", it.name).strip(), "dtype": it.dtype, "rows": it.rows,
              **({"formula": it.formula} if it.formula else {})} for it in f.items]
    out = {"form": code, "title": f.title, "def": where, "pdf": (prior or {}).get("pdf"), "pages": pages,
           "engine_read": code in engine_forms(prior or {}), "how": HOW, "items": items,
           "answer": {"form": code, "pages": pages, "values": {it.code: None for it in singles},
                      "records": [{it.code: None for it in rows}] if rows else [], "uncertain": []}}
    return out


def _pages_of(prior: dict, code: str) -> list[int]:
    for f in prior.get("forms") or []:
        if f.get("code") == code:
            return list(range(int(f["page"]), int(f["page"]) + int(f.get("pages") or 1)))
    return []


# ---------------------------------------------------------------- 엔진이 읽은 서식

def engine_forms(prior: dict) -> set[str]:
    """엔진이 값을 낸 서식(스킬 답이 덮지 않는다)."""
    ai = set((prior.get("ai") or {}).keys())
    out = {k for k, x in (prior.get("cells") or {}).items() if x} | {k for k, x in (prior.get("rows") or {}).items() if x}
    for key, form in (("adjustments", "15"), ("reserves", "50을"), ("losses", "50갑"), ("credit_years", "8부표3"),
                      ("rnd", "조특3_1")):
        if prior.get(key):
            out.add(form)
    emp = prior.get("employment") or {}
    if emp.get("10의8"):
        out.add("조특10의8")
    if emp.get("10의9"):
        out |= {"조특10의9", "조특10의9_1"}
    return out - ai


# ---------------------------------------------------------------- 값 읽기

NUM = re.compile(r"^[△▲\-－(（]?\s*[0-9][0-9,]*(?:\.[0-9]+)?\s*[)）]?$")


def parse_value(raw, dtype: str):
    """답 값 → (값, 읽혔나). None 은 빈칸. 금액 글은 쉼표 · 음수 표기를 푼다."""
    if raw is None:
        return None, True
    if dtype in ("text", "date"):
        return str(raw).strip(), True
    if isinstance(raw, bool):
        return None, False
    if isinstance(raw, (int, float)):
        v = float(raw)
    else:
        t = str(raw).strip().replace(" ", "")
        if t == "":
            return None, True
        pct = t.endswith("%")
        t = t.rstrip("%")
        if not NUM.match(t):
            return None, False
        neg = t[0] in "△▲-－(（"
        v = float(re.sub(r"[^0-9.]", "", t))
        v = -v if neg else v
        if pct:
            v = v / 100
    if dtype == "rate":
        return (v / 100 if abs(v) > 1 else v), True
    return int(round(v)), True


def read_answer(ans: dict) -> tuple[str, dict, list[dict], dict]:
    """답 하나 → (서식, cells 값, rows 줄, 메타 {pages, blank, absent, uncertain, unanswered, bad, unknown})."""
    code = str(ans.get("form") or "").strip()
    f, _ = verify.defn(code)
    if f is None:
        raise KeyError(code)
    raw = ans.get("values") or {}
    cells, blank, absent, bad, unknown = {}, [], [], [], []
    for key, val in raw.items():
        it = f.find(str(key))
        if it is None:
            unknown.append(str(key))
            continue
        if isinstance(val, str) and val.strip().lower() == ABSENT:
            absent.append(it.code)
            continue
        v, ok = parse_value(val, it.dtype)
        if not ok:
            bad.append(f"{it.code}={val!r}")
        elif v is None:
            blank.append(it.code)
        else:
            cells[it.code] = v
    records = []
    for r in ans.get("records") or []:
        row = {}
        for key, val in (r or {}).items():
            it = f.find(str(key))
            if it is None:
                unknown.append(str(key))
                continue
            if isinstance(val, str) and val.strip().lower() == ABSENT:
                continue
            v, ok = parse_value(val, it.dtype)
            if not ok:
                bad.append(f"{it.code}={val!r}")
            elif v is not None:
                row[it.code] = v
        if row:
            records.append(row)
    answered = {f.find(str(k)).code for k in raw if f.find(str(k)) is not None}
    unanswered = [it.code for it in f.items if not it.rows and it.code not in answered]
    meta = {"pages": [int(p) for p in ans.get("pages") or []], "blank": blank, "absent": absent,
            "uncertain": [str(x) for x in ans.get("uncertain") or []], "unanswered": unanswered,
            "bad": bad, "unknown": sorted(set(unknown))}
    return code, cells, records, meta


# ---------------------------------------------------------------- 넣기

def _page_words(pdf: Path, pages: list[int]) -> list[dict]:
    import pymupdf
    out = []
    doc = pymupdf.open(str(pdf))
    try:
        for no in pages:
            if 1 <= no <= len(doc):
                out.append({"page_no": no, "words": doc[no - 1].get_text("words")})
    finally:
        doc.close()
    return out


def _engine_values(prior: dict, skip: str) -> verify.Values:
    """전기.json cells(한 줄 란)를 서식 사이 검산 입력으로. 엔진이 다 읽는 서식(prior/defs 정의가 있고 PARTIAL 이 아님)은 full."""
    v = verify.Values()
    for form, items in (prior.get("cells") or {}).items():
        if form == skip or not items:
            continue
        for item, val in items.items():
            if form == "3" and str(item) in ("11", "14", "35", "60") and isinstance(val, (int, float)):
                val = val / 100                                    # 3호 세율은 인쇄된 % 정수로 둔다(read.cells_from)
            v.put(form, item, 0, val)
        if (verify.PRIOR_DEFS / f"{form}.json").exists() and form not in verify.PARTIAL and form not in (prior.get("ai") or {}):
            v.full.add(form)
    return v


def merge(prior: dict, ans: dict, pdf: Path | None) -> tuple[dict, list[dict], str]:
    """답 하나를 전기.json(dict)에 넣는다. → (prior, 새 problems, 한 줄 결과). 엔진이 읽은 서식이면 ValueError."""
    code, cells, records, meta = read_answer(ans)
    if code in engine_forms(prior):
        raise ValueError(f"{code} 는 엔진이 읽은 서식이라 스킬 답으로 덮지 않습니다")
    pages = meta["pages"] or _pages_of(prior, code)
    f, _ = verify.defn(code)
    v = _engine_values(prior, code)
    v.full.add(code)
    for item, val in cells.items():
        v.put(code, item, 0, val)
    for n, row in enumerate(records, start=1):
        for item, val in row.items():
            v.put(code, item, n, val)
    v.blank |= {(code, c, 0) for c in meta["blank"]}
    v.absent |= {(code, c) for c in meta["absent"]}
    v.unread |= {(code, c) for c in meta["unanswered"]}
    words = _page_words(pdf, pages) if pdf is not None and pages else []
    v.pages[code] = verify.page_numbers(words)
    fy = prior.get("fy") or ""
    sme = (prior.get("company") or {}).get("sme")
    checks, summary = verify.def_checks(v, fy_start=f"{fy}-01-01" if fy else "", sme=True if sme is None else bool(sme))
    checks = [p for p in checks if p["form"] == code or code in p.get("with", [])]
    got = verify.amounts_of([x for k, x in cells.items() if f.find(k).dtype in verify.NUM_DTYPES])
    got |= verify.amounts_of([{k: x for k, x in r.items() if f.find(k).dtype in verify.NUM_DTYPES} for r in records])
    texts = verify.text_checks(code, got, v.pages[code])
    new = checks + texts
    if meta["uncertain"]:
        new.append({"title": f"{code} 스킬이 확신하지 못한 란 {len(meta['uncertain'])}개",
                    "why": ", ".join(meta["uncertain"][:20]), "kind": "ai_uncertain", "form": code,
                    "items": meta["uncertain"]})
    if meta["unanswered"]:
        new.append({"title": f"{code} 스킬 답에 없는 란 {len(meta['unanswered'])}개(읽지 않은 란으로 둡니다)",
                    "why": ", ".join(meta["unanswered"][:20]), "kind": "ai_unanswered", "form": code,
                    "items": meta["unanswered"]})
    if meta["bad"] or meta["unknown"]:
        new.append({"title": f"{code} 스킬 답에서 넣지 못한 값 {len(meta['bad']) + len(meta['unknown'])}개",
                    "why": "; ".join(meta["bad"][:10] + [f"정의에 없는 란 {c}" for c in meta["unknown"][:10]]),
                    "kind": "ai_bad_value", "form": code, "items": meta["bad"] + meta["unknown"]})
    if not pages:
        new.append({"title": f"{code} 서식 쪽을 몰라 쪽 글자 대조를 하지 않았다",
                    "why": "답에 pages 를 적거나 전기.json forms 에 그 서식이 있어야 한다", "kind": "ai_no_pages", "form": code})
    elif not any(p.present for p in v.pages[code]):
        new.append({"title": f"{code} 서식 쪽에 글자가 없어(스캔본) 쪽 글자 대조를 하지 않았다",
                    "why": f"{', '.join(map(str, pages))}쪽", "kind": "ai_scanned", "form": code})
    for p in new:
        p["by"] = "ai"
        p.pop("ref", None)
    prior.setdefault("cells", {})[code] = cells
    if records:
        prior.setdefault("rows", {})[code] = records
    elif code in (prior.get("rows") or {}):
        prior["rows"].pop(code)
    prior.setdefault("ai", {})[code] = {"by": "ai", "confirmed": False, "pages": pages, "blank": meta["blank"],
                                        "absent": meta["absent"], "uncertain": meta["uncertain"],
                                        "unanswered": meta["unanswered"], "at": datetime.now().isoformat(timespec="seconds")}
    prior["problems"] = [p for p in prior.get("problems") or []
                         if not (p.get("by") == "ai" and p.get("form") == code)] + new
    fails = sum(1 for p in new if p["kind"] in ("check_form", "check_cross", "missing_amount", "not_in_text"))
    note = (f"{code} 란 {len(cells)}개 · 줄 {len(records)}개 넣음(confirmed false) · 검산 {summary['form']['ok'] + summary['cross']['ok']}개 맞음"
            f" · 확인 {len(new)}건" + (f"(검사 불일치 {fails})" if fails else ""))
    return prior, new, note


def load_answers(path: Path) -> list[dict]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("forms"), list):
        return data["forms"]
    if isinstance(data, dict) and isinstance(data.get("answer"), dict):
        return [data["answer"]]                                  # 틀 파일을 통째로 채워 넘긴 경우
    return [data]
