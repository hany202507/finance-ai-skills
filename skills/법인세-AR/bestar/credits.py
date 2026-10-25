# -*- coding: utf-8 -*-
"""공제 · 감면 제안 검사 · 넣기. 적용 여부는 정하지 않는다(회계사 몫).

꼴(references/credits.md):
{"point": "두 문장 안",
 "items": [{"name": "통합고용세액공제", "basis": "조세특례제한법 제29조의8", "state": "적용 가능",
            "purpose": "입법 취지 한 문장", "candidates": [{"what": "...", "line": 1234, "amount": 3500000}],
            "judge": ["회계사가 판단할 점"], "ask": ["...주십시오"], "issues": [7], "answers": ["c1"]}]}

검사: state 값, purpose, 후보의 line 이 전표.csv 에 있고 amount 가 그 줄의 차변이나 대변과 같은지,
issues 가 AR.json 에 있는지, answers 가 앞 단계 항목인지, 글 속 금액, 줄표 · 물음표.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from bestar import choices, numbers, paths, steps

STATES = ("적용 가능", "진행 중", "적용 불가")


def problems(c, data: dict) -> list[str]:
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        return ['제안은 {"point": "...", "items": [...]} 꼴이어야 합니다']
    probs = []
    if not str(data.get("point") or "").strip():
        probs.append("point 가 비었습니다")
    lines = {r["line"]: r for r in numbers.journal_rows(c)}
    nums = numbers.known(c)
    nos = {i["no"] for i in paths.read_ar(c).get("issues", [])}
    known = {k for k, *_ in steps.handed(c)}
    from bestar import link
    cm = link.cells(c) if any((it or {}).get("choices") for it in data["items"] if isinstance(it, dict)) else {}
    for n, it in enumerate(data["items"], 1):
        w = f"items[{n}] {it.get('name')}"
        if it.get("state") not in STATES:
            probs.append(f"{w}: state 는 {' · '.join(STATES)} 가운데 하나")
        for key in ("name", "basis", "purpose"):
            if not str(it.get(key) or "").strip():
                probs.append(f"{w}: {key} 가 비었습니다(취지를 못 찾았으면 「취지 미확인」)")
        for m, cand in enumerate(it.get("candidates") or [], 1):
            row = lines.get(cand.get("line"))
            if row is None:
                probs.append(f"{w} 후보 {m}: 전표.csv 에 {cand.get('line')} 번째 줄이 없습니다")
                continue
            amt = cand.get("amount")
            vals = {abs(int(float(row.get(k) or 0))) for k in ("debit", "credit")}
            if not isinstance(amt, (int, float)) or abs(int(amt)) not in vals:
                probs.append(f"{w} 후보 {m}: 금액 {amt} 이 전표 {cand.get('line')} 번째 줄({row.get('date')} {row.get('account_name')} "
                             f"차변 {row.get('debit')} · 대변 {row.get('credit')})과 다릅니다")
        bad = [x for x in it.get("issues") or [] if x not in nos]
        if bad:
            probs.append(f"{w}: AR.json 에 없는 이슈 {bad}")
        bad = [k for k in it.get("answers") or [] if k not in known]
        if bad:
            probs.append(f"{w}: answers 의 {bad} 는 앞 단계가 넘긴 항목이 아닙니다")
        probs += choices.problems(it.get("choices"), w, nums, cm)
        for q in it.get("ask") or []:
            if not str(q).rstrip(" .").endswith("주십시오"):
                probs.append(f"{w}: 받을 자료 「{q}」 는 「…주십시오」 로 끝냅니다")
    probs += numbers.style_problems(data, "제안")
    probs += numbers.amount_problems(data, nums, "제안", skip=("line", "issues", "value"))
    return probs


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: ar.py credits <신고건> <제안.json>")
        return 2
    c = paths.case(argv[0])
    if not steps.finished(c):
        print("1-(1) ~ 2-(2) 여섯 단계를 먼저 끝냅니다(ar.py step status).")
        return 2
    try:
        data = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"제안 파일을 읽지 못했습니다: {e}")
        return 2
    probs = problems(c, data)
    if probs:
        print("제안을 넣지 않았습니다:\n- " + "\n- ".join(probs))
        return 1
    paths.write_json(paths.index(c) / paths.CREDITS, data)
    print(f"공제 · 감면 제안 {len(data['items'])}건을 _색인/{paths.CREDITS} 에 넣었습니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
