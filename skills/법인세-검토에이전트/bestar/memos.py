# -*- coding: utf-8 -*-
"""이슈 메모 넣기. 엔진 메모 검사(ctax ar --memo)를 그대로 쓰고, 이 스킬이 더한 두 칸을 따로 둔다.

  answers : 이 이슈에서 결론을 낸 앞 단계 항목(f1 · c1 · a1 …)
  risk    : 상 · 중 · 하 (세 묶음 요약의 순위에 쓴다)
  facts   : ar.py sum · pdf 로 적은 숫자 id(s1 · p1 …). 메모 글에 못 쓰는 숫자를 화면 · 엑셀에 함께 보인다
  same_as : 같은 사안인 다른 이슈 번호(숫자 하나 또는 목록). 요약의 셋에서 겹쳐 나오지 않게 한다
  tax_effect : true 면 과세표준 · 세액을 바로 바꾸는 이슈(결손금 공제 · 감면 대상 여부 등). 요약 순위에 점수를 더한다
  choices : 판단 필요 이슈의 질문지(bestar/choices.py). 화면 왼쪽 「확인할 것」 에 나오고 회계사가 고른다

메모 꼴: {"items": [{"issue": 3, "judgment": "조정 필요", "why": "...", "law": [...], "questions": [...],
                     "answers": ["f1"], "risk": "중"},
                    {"added": "a3", "law": [...], "choices": {...}, "tax_effect": true, "facts": ["s1"], "answers": ["f10"]}]}
「added」 줄은 F1 AI 추가 이슈(엔진 이슈가 없는 a*)에 근거 조문 · 질문지 · 세액 영향 · 숫자 · 받은 앞 단계 항목을 단다.
판단 · 위험도 · 까닭은 F1 에 쓴 것이 그대로다. 「added」 줄은 이슈 전부 규칙에 들지 않는다(넣고 싶은 것만).
두 칸은 _색인/AR_단계/메모_부가.json 에 이슈 key 로 남는다(엔진을 다시 돌려 번호가 바뀌어도 이어진다).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from ctax.ar import cli as ar_cli

from bestar import choices, facts, keep, numbers, paths, steps

EXTRA = "메모_부가.json"
RISK = ("상", "중", "하")


def extra_path(c) -> Path:
    return paths.steps_dir(c) / EXTRA


def issue_key(i: dict) -> str:
    return f"{i.get('key')}|{i.get('rule')}"


def added_extras(c) -> dict[str, dict]:
    """AI 추가 이슈 id(a3) → {law, choices, tax_effect, facts, answers}."""
    saved = paths.read_json(extra_path(c), {}) or {}
    return {k.split("|", 1)[1]: v for k, v in saved.items() if k.startswith("added|")}


def added_problems(c, it: dict, nums: set, cm: dict, known: set, fact_ids: set) -> list[str]:
    w = f"AI 추가 이슈 {it.get('added')}"
    f1 = {a.get("id"): a for a in steps.load_step(c, "F1")["carry"].get("accounts") or []}
    a = f1.get(it.get("added"))
    if not a or a.get("issues"):
        return [f"{w}: F1 accounts 에 엔진 이슈 없이 올린 항목(AI 추가 이슈)이 아닙니다(있는 것: "
                f"{sorted(k for k, v in f1.items() if not v.get('issues'))})"]
    probs = []
    extra = set(it) - {"added", "law", "choices", "tax_effect", "facts", "answers", "stake"}
    if extra:
        probs.append(f"{w}: 받는 칸은 law · choices · tax_effect · facts · answers 입니다(판단 · 위험도 · 까닭은 F1 에 씀). 모르는 칸 {sorted(extra)}")
    for n, x in enumerate(it.get("law") or [], 1):
        if not isinstance(x, dict) or not str(x.get("ref") or "").strip() or x.get("grade") not in ("★★★", "★★☆", "★☆☆", "☆"):
            probs.append(f"{w}: law[{n}] 은 {{ref, grade(★★★ · ★★☆ · ★☆☆ · ☆), url}} 꼴입니다")
    probs += numbers.style_problems({"law": it.get("law") or []}, w)
    probs += numbers.amount_problems({"law": it.get("law") or []}, nums, w)
    probs += choices.problems(it.get("choices"), w, nums, cm)
    if it.get("tax_effect") not in (None, True, False):
        probs.append(f"{w}: tax_effect 는 true 또는 false 입니다")
    from bestar import stake
    probs += stake.problems(it.get("stake"), nums, w)
    bad = [k for k in it.get("facts") or [] if k not in fact_ids]
    if bad:
        probs.append(f"{w}: facts 의 {bad} 는 ar.py sum · pdf 로 적은 것이 아닙니다")
    bad = [k for k in it.get("answers") or [] if k not in known or k == it.get("added")]
    if bad:
        probs.append(f"{w}: answers 의 {bad} 는 앞 단계가 넘긴 항목(f* · c*)이 아닙니다")
    return probs


def extras(c) -> dict[int, dict]:
    """지금 AR.json 이슈 번호 → {answers, risk}."""
    saved = paths.read_json(extra_path(c), {}) or {}
    issues = paths.read_ar(c).get("issues", [])
    no_of = {issue_key(i): i["no"] for i in issues}
    out = {}
    for i in issues:
        if issue_key(i) in saved:
            e = dict(saved[issue_key(i)])
            keys = e.get("same_as")
            keys = keys if isinstance(keys, list) else ([keys] if keys else [])
            e["same_as"] = [no_of[k] for k in keys if k in no_of]          # key 로 남긴 것을 지금 번호로
            out[i["no"]] = e
    return out


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: ar.py memo <신고건> <메모.json>")
        return 2
    folder, memo_path = argv
    c = paths.case(folder)
    if not steps.finished(c):
        print("1-(1) ~ 2-(2) 여섯 단계를 먼저 끝냅니다(ar.py step status).")
        return 2
    try:
        memo = json.loads(Path(memo_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"메모 파일을 읽지 못했습니다: {e}")
        return 2
    if not isinstance(memo, dict) or set(memo) - {"items"}:
        print("메모 파일은 {\"items\": [...]} 하나만 받습니다. AI 추가 이슈 added 줄도 items 안에 넣습니다"
              f"(모르는 칸: {sorted(set(memo) - {'items'}) if isinstance(memo, dict) else type(memo).__name__})")
        return 1
    known = {k for k, *_ in steps.handed(c)}
    fact_ids = {f["id"] for f in facts.load(c)}
    nos = {i["no"] for i in paths.read_ar(c).get("issues", [])}
    probs = []
    nums = numbers.known(c)
    from bestar import link
    cm = link.cells(c) if any(it.get("choices") for it in memo.get("items") or []) else {}
    added_items = [it for it in memo.get("items") or [] if isinstance(it, dict) and "added" in it]
    for it in added_items:
        probs += added_problems(c, it, nums, cm, known, fact_ids)
    memo = {**memo, "items": [it for it in memo.get("items") or [] if not (isinstance(it, dict) and "added" in it)]}
    for it in memo.get("items") or []:
        w = f"이슈 {it.get('issue')}"
        if it.get("risk") not in RISK:
            probs.append(f"{w}: risk 는 상 · 중 · 하 가운데 하나")
        bad = [k for k in it.get("answers") or [] if k not in known]
        if bad:
            probs.append(f"{w}: answers 의 {bad} 는 앞 단계가 넘긴 항목이 아닙니다(있는 것: {sorted(known)})")
        bad = [k for k in it.get("facts") or [] if k not in fact_ids]
        if bad:
            probs.append(f"{w}: facts 의 {bad} 는 ar.py sum · pdf 로 적은 것이 아닙니다(있는 것: {sorted(fact_ids)})")
        probs += choices.problems(it.get("choices"), w, nums, cm)
        probs += [x for x in numbers.style_problems({"why": it.get("why")}, w) if "아니라" in x]
        sa = it.get("same_as")
        sa = sa if isinstance(sa, list) else ([] if sa is None else [sa])
        if any(not isinstance(x, int) or isinstance(x, bool) or x not in nos or x == it.get("issue") for x in sa):
            probs.append(f"{w}: same_as 는 같은 사안인 다른 이슈 번호(숫자 하나 또는 숫자 목록)입니다: {it.get('same_as')}")
        if it.get("tax_effect") not in (None, True, False):
            probs.append(f"{w}: tax_effect 는 true 또는 false 입니다")
        from bestar import stake
        probs += stake.problems(it.get("stake"), nums, w)
    if probs:
        print("메모를 넣지 않았습니다:\n- " + "\n- ".join(probs))
        return 1
    keep.save_added_conclusions(c)
    if memo["items"] or not added_items:                     # added 줄만 넣을 때는 이슈 메모를 건드리지 않는다
        engine_memo = paths.steps_dir(c) / "_메모_엔진.json"  # added 줄을 뺀 이슈 메모만 엔진 검사에 넘긴다
        paths.write_json(engine_memo, memo)
        code = ar_cli.main([folder, "--memo", str(engine_memo)])
        engine_memo.unlink(missing_ok=True)
        if code != 0:
            return code
    by_no = {i["no"]: i for i in paths.read_ar(c).get("issues", [])}
    saved = paths.read_json(extra_path(c), {}) or {}
    for it in memo["items"]:
        sa = it.get("same_as")
        sa = sa if isinstance(sa, list) else ([] if sa is None else [sa])
        saved[issue_key(by_no[it["issue"]])] = {"answers": list(it.get("answers") or []), "risk": it["risk"],
                                                "facts": list(it.get("facts") or []),
                                                "same_as": [issue_key(by_no[x]) for x in sa if x in by_no],
                                                "tax_effect": bool(it.get("tax_effect")), "choices": it.get("choices"),
                                                "stake": it.get("stake")}
    for it in added_items:
        saved[f"added|{it['added']}"] = {k: it[k] for k in ("law", "choices", "tax_effect", "facts", "answers", "stake") if k in it}
    paths.write_json(extra_path(c), saved)
    if added_items:
        print(f"AI 추가 이슈 {len(added_items)}건에 근거 조문 · 질문지 등을 달았습니다.")
    print(f"answers · risk {len(memo['items'])}건을 {paths.STEPS_DIR}/{EXTRA} 에 남겼습니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
