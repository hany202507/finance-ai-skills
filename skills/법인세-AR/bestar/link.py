# -*- coding: utf-8 -*-
"""판단을 조서 노란 칸에 잇는다. 조서 금액은 여전히 엔진(조서 계산)이 만들고, 이 모듈은 입력 칸 값만 맞춘다.

조서 칸에 들어갈 값은 두 곳에서 온다.
  1. 2-(2) 기업 구분 전제(AI): premise 의 중소기업 여부 · 소기업 여부, F2 carry.sets(건설용장비 내용연수 같은 전제)
  2. 회계사가 화면(또는 ar.py answer)에서 고른 질문지 답: 보기의 sets
같은 칸이면 회계사 답이 이긴다.

sync 는 이 값과 2 조서/조서.xlsx 의 노란 칸을 맞추고 조서 계산을 다시 돌린다.
- 이 모듈이 넣은 칸은 _색인/AR_단계/조서잇기.json 에 남는다. 답을 지우거나 바꾸면 넣기 전 값으로 되돌린다.
- 회계사가 엑셀에서 직접 고친 칸은 AI 전제로 덮지 않는다. 화면 답은 엑셀에서 고친 때보다 나중에 골랐을 때만 넣는다.

칸은 조서 _입력 시트의 (조서, key) 로 가린다. 목록은 ar.py inputs.
"""
from __future__ import annotations

import contextlib
import io
import re
from datetime import datetime

from ctax.case import WP_DIR
from ctax.wp.inputs import INPUT_JSON
from ctax.wp.model import normalize
from ctax.wp.sheet import INPUT_SHEET

from bestar import decide, paths

FILE = "조서잇기.json"
XLSX = "조서.xlsx"
PREMISE = "2-(2) 전제"
YN = ("여", "부")
# 글 칸 가운데 조서가 정해진 말만 알아듣는 것(key 의 「/」 앞). 다른 말은 조서가 「확인 필요」 등으로 바꿔 버린다.
KNOWN = {"특수관계인": ("예", "아니오", "확인 필요"),
         "소득처분": ("상여", "배당", "기타소득", "기타사외유출", "유보", "기타"),
         "매수인 특수관계인": ("예", "아니오", "확인 필요"),
         "시부인": ("적용", "보류"), "상각방법": ("정액", "정률"), "분류": ("특례", "일반", "비지정"),
         "전기 유보 처리": ("그대로", "추인"), "이자율 선택": ("당좌대출이자율", "가중평균차입이자율"),
         "감면 업종": ("도매업등", "감면업종", "출판업", "비감면")}


def xlsx_path(c):
    return c.root / WP_DIR / XLSX


def state_path(c):
    return paths.steps_dir(c) / FILE


def ck(paper: str, key: str) -> str:
    return f"{paper}|{key}"


# ---------------------------------------------------------------- 조서 칸
def cells(c) -> dict[tuple[str, str], dict]:
    """조서.xlsx _입력 표: (조서, key) → {sheet, cell, default, kind, value}. 조서가 없으면 빈 사전."""
    path = xlsx_path(c)
    if not path.exists():
        return {}
    from openpyxl import load_workbook
    wb = load_workbook(path)
    out = {}
    try:
        if INPUT_SHEET not in wb.sheetnames:
            return {}
        for row in wb[INPUT_SHEET].iter_rows(min_row=2, values_only=True):
            if not row or not row[0] or not row[1]:
                continue
            paper, key, sheet, cell, default, kind = (list(row) + [None] * 6)[:6]
            kind = kind or "text"
            if sheet not in wb.sheetnames:
                continue
            value = wb[sheet][cell].value
            if isinstance(value, str) and value.startswith("="):
                continue
            out[(str(paper), str(key))] = {"sheet": sheet, "cell": cell, "kind": kind,
                                           "default": normalize(default, kind), "value": normalize(value, kind)}
    finally:
        wb.close()
    return out


def paper_names(c) -> dict[str, str]:
    adj = paths.read_json(paths.index(c) / "조정.json", {}) or {}
    return {p["id"]: p.get("name") or p["id"] for p in adj.get("papers") or []}


def describe(s: dict, names: dict[str, str] | None = None) -> str:
    """사람이 읽는 한 줄: 「세금과공과 · 부인 여부(2025-01-06 전표 24) → O」."""
    paper = (names or {}).get(s["paper"], s["paper"])
    key = str(s["key"])
    m = re.match(r"^(.*?)/(\d{4}-\d{2}-\d{2})\|([^|]+)\|", key)
    if m:
        key = f"{m.group(1)}({m.group(2)} 전표 {m.group(3)})"
    return f"{paper} · {key} → {s['value']}"


def problems(sets, cm: dict, label: str) -> list[str]:
    """sets([{paper, key, value}]) 검사. cm 은 cells(c)."""
    if sets is None:
        return []
    if not isinstance(sets, list):
        return [f"{label}: sets 는 [{{paper, key, value}}] 목록입니다"]
    if not sets:                              # 조서를 그대로 두는 보기(빈 목록이나 sets 를 뺀 것이나 같다)
        return []
    if not cm:
        return [f"{label}: 2 조서/조서.xlsx 가 없어 sets 를 확인하지 못했습니다(ar.py engine 을 먼저 돌립니다)"]
    out = []
    for n, s in enumerate(sets, 1):
        if not isinstance(s, dict) or not s.get("paper") or not s.get("key") or "value" not in s:
            out.append(f"{label}: sets[{n}] 에 paper · key · value 가 있어야 합니다")
            continue
        cell = cm.get((str(s["paper"]), str(s["key"])))
        if not cell:
            near = [k for p, k in cm if p == s["paper"]][:5]
            out.append(f"{label}: sets[{n}] 조서 칸 ({s['paper']}, {s['key']}) 이 없습니다"
                       + (f"(이 조서의 칸 예: {near}, 목록은 ar.py inputs)" if near else "(ar.py inputs 로 칸 목록을 봅니다)"))
            continue
        v, kind = s["value"], cell["kind"]
        if kind == "pick" and normalize(v, kind) not in ("O", "X"):
            out.append(f"{label}: sets[{n}] {s['key']} 는 O 또는 X 입니다")
        elif kind in ("int", "ratio") and (not isinstance(v, (int, float)) or isinstance(v, bool)):
            out.append(f"{label}: sets[{n}] {s['key']} 는 숫자 칸입니다")
        elif cell["default"] in YN and str(v) not in YN:
            out.append(f"{label}: sets[{n}] {s['key']} 는 여 또는 부 입니다")
        else:
            allowed = KNOWN.get(str(s["key"]).split("/")[0])
            if allowed and str(v) not in allowed:
                out.append(f"{label}: sets[{n}] {s['key']} 는 {' · '.join(allowed)} 가운데 하나입니다")
    return out


# ---------------------------------------------------------------- 넣을 값
def premise_sets(f2: dict) -> list[dict]:
    """2-(2) 결론에서 조서 칸 값. 미확인이면 넣지 않는다."""
    out = []
    prem = str(f2.get("premise") or f2.get("verdict") or "")
    if f2.get("status") == "판단 불가" or not prem or "미확인" in prem:
        sme = None
    elif "중소기업" in prem:
        sme = "여"
    elif any(w in prem for w in ("중견", "일반", "그 외", "상호출자")):
        sme = "부"
    else:
        sme = None
    if sme:
        out.append({"paper": "tax_3", "key": "중소기업 여부", "value": sme, "why": f"2-(2) {prem}"})
    if sme == "여":
        small = None
        if "소기업" in prem.replace("중소기업", ""):
            small = "여"
        elif "중기업" in prem:
            small = "부"
        else:
            t = next((t for t in f2.get("tests") or [] if t.get("name") == "소기업"), {})
            small = {"충족": "여", "미충족": "부"}.get(t.get("result"))
        if small:
            out.append({"paper": "credits", "key": "소기업 여부", "value": small, "why": f"2-(2) {prem}"})
    for s in f2.get("sets") or []:
        out.append({**s, "why": s.get("why") or "2-(2) 전제"})
    return out


def question_sets(c) -> dict[str, dict]:
    """판단 저장 key → {title, options: {value: sets}}."""
    from bestar import memos, steps
    out = {}
    ar = paths.read_ar(c)
    ex = memos.extras(c)
    for i in ar.get("issues", []):
        ch = (ex.get(i["no"]) or {}).get("choices")
        if ch:
            out[f"issue|{i.get('key')}|{i.get('rule')}"] = ch
    ax = memos.added_extras(c)
    for a in steps.load_step(c, "F1")["carry"].get("accounts") or []:
        ch = (ax.get(a["id"]) or {}).get("choices") or a.get("choices")
        if ch and not a.get("issues"):
            out[f"added|{a['id']}"] = ch
    for x in (paths.read_json(paths.index(c) / paths.CREDITS, {}) or {}).get("items") or []:
        if x.get("choices"):
            out[f"credit|{x.get('name')}"] = x["choices"]
    return out


def chosen_sets(choice: dict, entry: dict) -> list[dict]:
    picked = entry.get("values") if "values" in entry else [entry.get("value")]
    opts = {str(o.get("value")): o for o in choice.get("options") or []}
    out = []
    for v in picked or []:
        out += list((opts.get(str(v)) or {}).get("sets") or [])
    return out


def desired(c) -> dict[str, dict]:
    """"조서|key" → {paper, key, value, source, at, by}."""
    from bestar import steps
    out = {}
    f2 = steps.load_step(c, "F2")
    log = {e["id"]: e for e in steps.read_log(c)}
    f2_at = (log.get("F2") or {}).get("at") or ""
    for s in premise_sets(f2.get("carry") or {}):
        out[ck(s["paper"], s["key"])] = {"paper": s["paper"], "key": s["key"], "value": s["value"],
                                         "source": f"{PREMISE}: {s['why']}", "at": f2_at, "by": "AI"}
    qs = question_sets(c)
    dec = decide.load(c)["decisions"]
    for k, entry in sorted(dec.items(), key=lambda kv: kv[1].get("at") or ""):
        ch = qs.get(k)
        if not ch:
            continue
        for s in chosen_sets(ch, entry):
            out[ck(s["paper"], s["key"])] = {"paper": s["paper"], "key": s["key"], "value": s["value"],
                                             "source": f"답: {ch.get('title')}", "at": entry.get("at") or "", "by": entry.get("by") or "회계사"}
    return out


# ---------------------------------------------------------------- 맞추기
def _manual_at(c) -> dict[str, str]:
    d = paths.read_json(paths.index(c) / INPUT_JSON, {}) or {}
    return {ck(x["paper"], x["key"]): x.get("at") or "" for x in d.get("cells") or [] if x.get("paper") and x.get("key")}


def plan(c) -> dict:
    """{writes: [{paper, key, value, prev, source}], kept: [...], unknown: [...], state: {...}}."""
    cm = cells(c)
    want = desired(c)
    st = paths.read_json(state_path(c), {}) or {}
    linked = dict(st.get("linked") or {})
    manual = _manual_at(c)
    now = datetime.now().isoformat()          # 마이크로초까지: 같은 초에 고른 답보다 뒤로 정렬된다
    writes, kept, unknown = [], [], []
    for k, d in want.items():
        cell = cm.get((d["paper"], d["key"]))
        if not cell:
            unknown.append({**d, "why": "조서에 이 칸이 없습니다(조서를 다시 계산해 줄이 사라졌을 수 있습니다)"})
            continue
        val, cur = normalize(d["value"], cell["kind"]), cell["value"]
        own = linked.get(k)
        if cur == val:
            if own:
                linked[k] = {**own, "value": val, "source": d["source"]}
            continue
        # 엑셀에서 고친 칸: 이 모듈이 넣은 뒤 바뀌었거나, 넣은 적 없는데 기본값이 아니다
        touched = (own is not None and cur != normalize(own.get("value"), cell["kind"])) or (own is None and cur != cell["default"])
        # 엑셀에서 고친 때: 넣은 칸이면 넣은 때보다 뒤(넣은 때로 본다), 아니면 조서입력.json 에 남은 때
        edited_at = (own.get("at") or "") if own is not None else (manual.get(k) or "")
        if touched and (d["by"] == "AI" or edited_at >= (d["at"] or "")):
            kept.append({**d, "current": cur, "why": "회계사가 엑셀에서 고친 값이라 두었습니다"})
            continue
        prev = own["prev"] if own and not touched else cur
        writes.append({**d, "value": val, "prev": prev, "current": cur, "kind": cell["kind"]})
        linked[k] = {"paper": d["paper"], "key": d["key"], "value": val, "prev": prev, "source": d["source"], "at": now}
    for k, own in list(linked.items()):
        if k in want:
            continue
        cell = cm.get((own["paper"], own["key"]))
        linked.pop(k)
        if cell and cell["value"] == normalize(own.get("value"), cell["kind"]) and cell["value"] != normalize(own.get("prev"), cell["kind"]):
            writes.append({"paper": own["paper"], "key": own["key"], "value": normalize(own.get("prev"), cell["kind"]),
                           "prev": cell["value"], "current": cell["value"], "kind": cell["kind"],
                           "source": "되돌림(답을 지웠거나 바꿈)"})
    return {"writes": writes, "kept": kept, "unknown": unknown, "linked": linked, "cells": cm}


def write_cells(c, writes: list[dict], cm: dict) -> str:
    """노란 칸에 값을 쓴다. 문제가 있으면 까닭을 돌려준다."""
    from openpyxl import load_workbook
    path = xlsx_path(c)
    wb = load_workbook(path)
    for w in writes:
        cell = cm[(w["paper"], w["key"])]
        wb[cell["sheet"]][cell["cell"]].value = w["value"]
    try:
        wb.save(path)
    except PermissionError:
        return f"{WP_DIR}/{XLSX} 가 열려 있어 조서 칸을 쓰지 못했습니다. 엑셀을 닫고 ar.py apply 를 돌립니다"
    finally:
        wb.close()
    return ""


def summary_of(c) -> dict:
    return (paths.read_json(paths.index(c) / "조정.json", {}) or {}).get("summary") or {}


def sync(c, rerun: bool = True) -> dict:
    """판단과 조서 칸을 맞춘다. rerun 이면 바뀐 칸이 있을 때 조서 계산을 다시 돌린다.

    돌려주는 것: {writes, kept, unknown, problem, before, after}
    """
    if not xlsx_path(c).exists():
        return {"writes": [], "kept": [], "unknown": [], "problem": f"{WP_DIR}/{XLSX} 가 없습니다(ar.py engine 을 먼저 돌립니다)"}
    p = plan(c)
    out = {"writes": p["writes"], "kept": p["kept"], "unknown": p["unknown"], "problem": "", "before": summary_of(c)}
    if p["writes"]:
        out["problem"] = write_cells(c, p["writes"], p["cells"])
        if out["problem"]:
            out["writes"] = []
            return out
    paths.write_json(state_path(c), {"linked": p["linked"]})
    if p["writes"] and rerun:
        from ctax.wp import cli as wp_cli
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = wp_cli.main([str(c.root)])
        if code == 2:
            out["problem"] = "조서 계산을 다시 돌리지 못했습니다: " + buf.getvalue().strip()[-300:]
    out["after"] = summary_of(c)
    return out


def notice(r: dict, names: dict[str, str] | None = None) -> str:
    """화면 · 명령 출력용 짧은 글."""
    parts = []
    if r.get("problem"):
        parts.append(r["problem"])
    if r.get("writes"):
        b, a = r.get("before") or {}, r.get("after") or {}
        moved = [f"{lab} {b.get(k) or 0:,} → {a.get(k) or 0:,}" for k, lab in
                 (("add", "가산"), ("deduct", "차감"), ("tax_base", "과세표준"), ("determined_tax", "결정세액")) if (b.get(k) or 0) != (a.get(k) or 0)]
        parts.append(f"조서 칸 {len(r['writes'])}개를 바꾸고 다시 계산했어요" + (f" ({', '.join(moved)})" if moved else " (금액 변동 없음)"))
    if r.get("kept"):
        parts.append(f"엑셀에서 직접 고친 칸 {len(r['kept'])}개는 두었어요")
    if r.get("unknown"):
        parts.append(f"조서에 없는 칸 {len(r['unknown'])}개는 넣지 못했어요")
    return ". ".join(parts)


# ---------------------------------------------------------------- 명령
def main_apply(argv: list[str]) -> int:
    import argparse
    p = argparse.ArgumentParser(prog="ar.py apply")
    p.add_argument("folder")
    p.add_argument("--dry", action="store_true", help="바꿀 칸만 보이고 쓰지 않는다")
    a = p.parse_args(argv)
    c = paths.case(a.folder)
    names = paper_names(c)
    if a.dry:
        pl = plan(c)
        for w in pl["writes"]:
            print(f"바꿈  {describe(w, names)} (지금 {w['current']}) · {w['source']}")
        for w in pl["kept"]:
            print(f"둠    {describe(w, names)} (지금 {w['current']}) · {w['why']}")
        for w in pl["unknown"]:
            print(f"없음  {describe(w, names)} · {w['why']}")
        if not (pl["writes"] or pl["kept"] or pl["unknown"]):
            print("조서 칸과 판단이 이미 맞습니다.")
        return 0
    r = sync(c)
    for w in r["writes"]:
        print(f"바꿈  {describe(w, names)} (전 {w['current']}) · {w['source']}")
    for w in r["kept"]:
        print(f"둠    {describe(w, names)} (지금 {w['current']}) · {w['why']}")
    for w in r["unknown"]:
        print(f"없음  {describe(w, names)} · {w['why']}")
    print(notice(r, names) or "조서 칸과 판단이 이미 맞습니다.")
    return 1 if r.get("problem") else 0


def main_inputs(argv: list[str]) -> int:
    import argparse
    p = argparse.ArgumentParser(prog="ar.py inputs")
    p.add_argument("folder")
    p.add_argument("--paper", help="조서 id(taxes_dues · business_car …)")
    p.add_argument("--grep", help="key 에서 찾을 정규식")
    p.add_argument("--changed", action="store_true", help="기본값과 다른 칸만")
    p.add_argument("--no-lines", action="store_true", help="전표 줄마다 있는 칸(key 에 「|」)을 빼고 조서 · 거래처 · 자산 단위 칸만")
    a = p.parse_args(argv)
    c = paths.case(a.folder)
    cm = cells(c)
    if not cm:
        print(f"{WP_DIR}/{XLSX} 가 없습니다. ar.py engine 을 먼저 돌립니다.")
        return 2
    names = paper_names(c)
    linked = (paths.read_json(state_path(c), {}) or {}).get("linked") or {}
    rx = re.compile(a.grep) if a.grep else None
    n = 0
    try:
        for (paper, key), cell in cm.items():
            if a.paper and paper != a.paper or rx and not rx.search(key) or a.changed and cell["value"] == cell["default"] \
                    or a.no_lines and "|" in key:
                continue
            mark = " ← " + linked[ck(paper, key)]["source"] if ck(paper, key) in linked else ""
            print(f"{paper}\t{names.get(paper, paper)}\t{key}\t지금 {cell['value']!r}\t기본 {cell['default']!r}\t{cell['kind']}"
                  f"\t받는 값 {allowed_of(key, cell)}{mark}")
            n += 1
        print(f"({n}칸) sets 에는 첫 열(조서 id)과 셋째 열(key)을 그대로 씁니다.")
    except BrokenPipeError:                    # | head 로 자른 경우
        pass
    return 0


def allowed_of(key: str, cell: dict) -> str:
    """칸이 받는 값 안내. 정해진 말을 모르면 기본값 꼴로 적는다."""
    if cell["kind"] == "pick":
        return "O · X"
    if cell["default"] in YN:
        return "여 · 부"
    known = KNOWN.get(str(key).split("/")[0])
    if known:
        return " · ".join(known)
    return {"int": "정수(금액은 회계사가 넣음)", "ratio": "비율(0.05 꼴)", "year": "연도 4자리"}.get(cell["kind"], f"글(기본 {cell['default']!r} 꼴)")


def main_answer(argv: list[str]) -> int:
    """화면 없이 질문지에 답한다(회계사가 대화로 답을 준 경우)."""
    import argparse
    p = argparse.ArgumentParser(prog="ar.py answer")
    p.add_argument("folder")
    p.add_argument("uid", nargs="?", help="issue:3 · added:a2 · credit:1 (목록은 uid 없이)")
    p.add_argument("--value")
    p.add_argument("--values", help="쉼표로 여러 개")
    p.add_argument("--other")
    p.add_argument("--undo", action="store_true")
    p.add_argument("--by", default="회계사")
    a = p.parse_args(argv)
    c = paths.case(a.folder)
    from bestar import review
    data = review.build(c)
    qs = {q["uid"]: q for q in data["questions"]}
    if not a.uid:
        for q in data["questions"]:
            ans = review.answer_text(q, q.get("answer"))
            print(f"{q['uid']}\t{q['title']}\t{'답: ' + ans if ans else '답 없음'}")
            for o in q["options"]:
                print(f"    {o['value']}\t{o['label']}" + (f"\t조서: {'; '.join(o['sets_text'])}" if o.get("sets_text") else ""))
        return 0
    if a.uid not in qs:
        print(f"질문이 없습니다: {a.uid} (uid 없이 돌리면 목록)")
        return 2
    key = data["keys"].get(a.uid, a.uid)
    q = qs[a.uid]
    vals = {str(o["value"]) for o in q["options"]}
    if a.undo:
        decide.undo(c, key)
    else:
        picked = [x.strip() for x in a.values.split(",")] if a.values else ([a.value] if a.value else [])
        bad = [v for v in picked if v not in vals]
        if bad or not picked and not a.other:
            print(f"보기 value 가 아닙니다: {bad or '(없음)'} (있는 것: {sorted(vals)})")
            return 2
        if a.values:
            decide.decide(c, key, values=picked, other=a.other, by=a.by)
        else:
            decide.decide(c, key, value=picked[0] if picked else None, other=a.other, by=a.by)
    r = sync(c)
    print(notice(r, paper_names(c)) or "저장했습니다(조서 칸은 바뀌지 않음).")
    return 1 if r.get("problem") else 0
