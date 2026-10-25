# -*- coding: utf-8 -*-
"""가이드 1-(1)부터 2-(2)까지를 한 단계씩 쓰게 하는 문지기(v0.3 step.py 를 엔진 결과와 대조하도록 고침).

  ar.py step next   <신고건>          지금 할 단계, 가이드 원문, 엔진이 찾은 사실, 앞 단계가 넘긴 결론
  ar.py step done   <신고건> <ID>     _색인/AR_단계/<ID>.json 을 검사하고 끝난 단계로 적는다
  ar.py step done   <신고건> <ID> --redo   끝난 단계를 고쳐 다시 적는다(뒤 단계는 모두 다시)
  ar.py step status <신고건>
  ar.py step outside <신고건>        엔진 규칙에 안 걸린 계정 목록(F1 others_reviewed 로 훑을 것)

순서: P1 → P2 → P3 → P4 → F1 → F2. 여섯 단계가 끝나면 _색인/AR_단계/전제.json 이 생긴다.
단계 파일 형식은 references/sequence.md.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import json
from datetime import datetime

from bestar import choices, numbers, paths

SEQUENCE = [("P1", "1-(1)"), ("P2", "1-(2)"), ("P3", "1-(3)"), ("P4", "1-(4)"), ("F1", "2-(1)"), ("F2", "2-(2)")]
ORDER = [i for i, _ in SEQUENCE]
LABEL = dict(SEQUENCE)
GUIDE = {"P1": "1-1", "P2": "1-2", "P3": "1-3", "P4": "1-4", "F1": "2-1", "F2": "2-2"}
TITLE = {"P1": "회사 종류 구분", "P2": "주식변동 · 부동산임대업 주업", "P3": "전기 조정 · 유보로 당기 조정 예측",
         "P4": "전기 공제 · 감면으로 당기 예측", "F1": "재무제표로 볼 계정 고르기", "F2": "당기 중소기업 여부"}

CARRY = {
    "P1": {"keys": ["class", "small", "industry", "grace", "effects"],
           "values": {"class": ("중소기업", "중견기업", "상호출자제한기업", "그 외", "미확인"),
                      "small": ("소기업", "중기업", "해당 없음", "미확인")}},
    "P2": {"keys": ["stock_change", "stock_form", "rental_main", "effects"],
           "values": {"stock_change": ("있음", "없음", "미확인"), "stock_form": ("제출 예상", "제출 대상 아님", "미확인"),
                      "rental_main": ("해당", "해당 아님", "미확인")}},
    "P3": {"keys": ["forecast"], "values": {}},
    "P4": {"keys": ["forecast"], "values": {}},
    "F1": {"keys": ["accounts", "forecast_check"], "values": {}},
    "F2": {"keys": ["verdict", "status", "premise", "compare_p1", "point", "tests", "effects"],
           "values": {"status": ("확정", "확인 필요", "판단 불가"), "compare_p1": ("같음", "달라짐", "미확인")}},
}
P3_VALUES = {"outlook": ("다시 생길 듯", "추인될 듯", "안 생길 듯", "미확인"), "kind": ("반복", "유보 추인", "일회성")}
P4_VALUES = {"outlook": ("계속", "사후관리", "종료", "미확인")}
F1_CHECK = ("계정 있음", "크게 변함", "계정 없음")
RISK = ("상", "중", "하")
SME_TESTS = ("업종", "규모", "자산총액", "독립성", "유예기간", "소기업")
TEST_RESULT = ("충족", "미충족", "미확인", "해당 없음")
# 금액이 아닌 정수 칸(이슈 번호 등)
NOT_MONEY = ("issues", "no", "page")


# ---------------------------------------------------------------- 엔진 결과
def engine_facts(c) -> dict:
    ar = paths.read_ar(c)
    prior = paths.read_json(paths.index(c) / "전기.json", {}) or {}
    return {"ar": ar, "prior": prior, "issue_nos": {i["no"] for i in ar.get("issues", [])}}


def prior_sources(prior: dict) -> dict[str, list[str]]:
    """전기.json 줄마다 붙일 src id."""
    return {"P3": [f"adj:{n}" for n, _ in enumerate(prior.get("adjustments") or [])]
                  + [f"res:{n}" for n, _ in enumerate(prior.get("reserves") or [])],
            "P4": [f"credit:{n}" for n, _ in enumerate(prior.get("credits") or [])]}


def step_view(step_id: str, f: dict) -> dict:
    """next 가 보여 주는 엔진 사실. 이 단계의 자료를 대신하지 않는다(필요하면 원문을 연다)."""
    ar, prior = f["ar"], f["prior"]
    guide = {g["id"]: g for g in ar.get("guide", [])}
    g = guide.get(GUIDE[step_id], {})
    out = {"guide": g.get("text"), "engine_status": g.get("status"), "engine_facts": g.get("facts", []),
           "engine_issues": [_brief(i) for i in ar.get("issues", []) if i["no"] in (g.get("issues") or [])]}
    if step_id == "P1":
        out["prior_company"] = prior.get("company")
    elif step_id == "P2":
        out["prior_54"] = (prior.get("rows") or {}).get("54", [])
    elif step_id == "P3":
        src = prior_sources(prior)["P3"]
        rows = (prior.get("adjustments") or []) + (prior.get("reserves") or [])
        out["prior_lines"] = [{"src": s, **r} for s, r in zip(src, rows)]
        out["issues_with_prior"] = [_brief(i) for i in ar.get("issues", []) if i.get("prior_treatment") or i["kind"] == "전기 연속"]
        out["all_issues"] = [_brief(i) for i in ar.get("issues", [])]
    elif step_id == "P4":
        src = prior_sources(prior)["P4"]
        out["prior_lines"] = [{"src": s, **r} for s, r in zip(src, prior.get("credits") or [])]
        out["credit_years"] = prior.get("credit_years") or []
        out["credit_issues"] = [_brief(i) for i in ar.get("issues", []) if i["kind"] == "공제감면"]
    elif step_id == "F1":
        out["all_issues"] = [_brief(i) for i in ar.get("issues", [])]
        out["outside_accounts"] = [{k: r[k] for k in ("code", "name", "class", "amount")}
                                   for r in outside_accounts(f.get("ledger") or {}, ar, {})]
    elif step_id == "F2":
        out["prior_company"] = prior.get("company")
    return out


def _brief(i: dict) -> dict:
    return {"no": i["no"], "kind": i["kind"], "certainty": i["certainty"], "title": i["title"],
            "amounts": i.get("amounts"), "prior_treatment": i.get("prior_treatment")}


# ---------------------------------------------------------------- 엔진 규칙에 안 걸린 계정
def outside_accounts(ledger: dict, ar: dict, f1_carry: dict) -> list[dict]:
    """금액이 있는데 엔진 계정 묶음 · 엔진 이슈 · F1 accounts 어디에도 안 걸린 계정."""
    from bestar import sheet
    steps = [{"id": "F1", "carry": {"accounts": f1_carry.get("accounts") or []}}]
    return sheet.account_coverage(ledger, ar, steps)["outside"]


def outside_unreviewed(ledger: dict, ar: dict, f1_carry: dict) -> list[str]:
    reviewed = " ".join(str(n) for x in f1_carry.get("others_reviewed") or [] for n in (x.get("accounts") or []))
    out = []
    for r in outside_accounts(ledger, ar, f1_carry):
        clean = re.sub(r"\((판|제|도)\)$", "", str(r["name"])).strip()
        if clean not in reviewed and str(r["name"]) not in reviewed:
            out.append(clean)
    return out


# ---------------------------------------------------------------- 검사
def carry_problems(step_id: str, carry: dict, f: dict) -> list[str]:
    spec, probs = CARRY[step_id], []
    nos = f["issue_nos"]
    for key in spec["keys"]:
        if key not in carry:
            probs.append(f"carry.{key} 없음")
    for key, allowed in spec["values"].items():
        if key in carry and carry[key] not in allowed:
            probs.append(f"carry.{key} 값 오류({carry[key]}): {' / '.join(allowed)} 중 하나")

    def bad_issues(entry, label):
        bad = [n for n in entry.get("issues") or [] if n not in nos]
        if bad:
            probs.append(f"{label}: AR.json 에 없는 이슈 번호 {bad}")

    if step_id == "P1":
        comp = f["prior"].get("company") or {}
        if comp:
            eng_class = "중소기업" if comp.get("sme") else None
            eng_small = "소기업" if comp.get("small") else ("중기업" if comp.get("sme") else None)
            if ((eng_class and carry.get("class") != eng_class) or (eng_small and carry.get("small") != eng_small)) \
                    and not str(carry.get("differs_reason") or "").strip():
                probs.append(f"carry: 전기.json 은 {eng_class or '-'} · {eng_small or '-'} 입니다. 다르게 적었으면 differs_reason 에 까닭을 씁니다")
    if step_id in ("P3", "P4"):
        prefix, allowed = ("f", P3_VALUES) if step_id == "P3" else ("c", P4_VALUES)
        want = prior_sources(f["prior"])[step_id]
        seen_id, seen_src = set(), []
        for n, x in enumerate(carry.get("forecast") or [], 1):
            label = f"carry.forecast[{n}]"
            if not str(x.get("id", "")).startswith(prefix) or x.get("id") in seen_id:
                probs.append(f"{label}: id 는 {prefix}1, {prefix}2 … 처럼 겹치지 않게")
            seen_id.add(x.get("id"))
            seen_src.append(x.get("src"))
            for key, values in allowed.items():
                if x.get(key) not in values:
                    probs.append(f"{label}.{key} 값 오류({x.get(key)}): {' / '.join(values)} 중 하나")
            bad_issues(x, label)
            closed = x.get("outlook") in ("안 생길 듯", "종료")
            if not x.get("issues") and not closed and step_id == "P3":
                probs.append(f"{label}: 확인할 이슈 번호(issues)가 없습니다. 당기에 안 생길 것이면 outlook 을 「안 생길 듯」 으로 하고 why 에 까닭을 씁니다")
            if not str(x.get("why") or "").strip():
                probs.append(f"{label}: why 가 비었습니다")
        missing = [s for s in want if s not in seen_src]
        extra = [s for s in seen_src if s not in want]
        dup = sorted({s for s in seen_src if seen_src.count(s) > 1})
        if missing or extra or dup:
            probs.append(f"carry.forecast 는 전기.json 줄마다 하나씩입니다(src). 빠짐 {missing}, 없는 줄 {extra}, 겹침 {dup}")
    if step_id == "F1":
        for n, a in enumerate(carry.get("accounts") or [], 1):
            label = f"carry.accounts[{n}]"
            if not str(a.get("id", "")).startswith("a"):
                probs.append(f"{label}: id 는 a1, a2 …")
            bad_issues(a, label)
            if not a.get("issues") and not str(a.get("finding") or "").strip():
                probs.append(f"{label}: 엔진 이슈가 없는 계정은 finding(확인한 사실)을 써야 AI 추가 이슈가 됩니다")
            if a.get("choices") is not None:
                probs += choices.problems(a.get("choices"), label, f.get("nums") or set(), f.get("cells"))
            if not a.get("issues") and a.get("risk") not in RISK:
                probs.append(f"{label}: AI 추가 이슈는 risk(상 · 중 · 하)를 고릅니다")
        missing = outside_unreviewed(f.get("ledger") or {}, f["ar"], carry)
        if missing:
            probs.append("carry.others_reviewed: 엔진 규칙 · 엔진 이슈 · accounts 어디에도 안 걸린 계정을 모두 훑어 한 줄씩 적습니다. "
                         f"빠진 계정 {len(missing)}개: " + ", ".join(missing) + " (목록과 금액: ar.py step outside <신고건>)")
        p3 = {x.get("id") for x in (f.get("p3") or {}).get("forecast", [])}
        for n, x in enumerate(carry.get("forecast_check") or [], 1):
            if x.get("status") not in F1_CHECK:
                probs.append(f"carry.forecast_check[{n}].status 값 오류({x.get('status')})")
            if p3 and x.get("forecast") not in p3:
                probs.append(f"carry.forecast_check[{n}]: 1-(3) 에 없는 예측 {x.get('forecast')}")
    if step_id == "F2":
        names = [t.get("name") for t in carry.get("tests") or []]
        missing = [n for n in SME_TESTS if n not in names]
        if missing:
            probs.append(f"carry.tests 에 빠진 요건: {missing}")
        for t in carry.get("tests") or []:
            if t.get("result") not in TEST_RESULT:
                probs.append(f"carry.tests {t.get('name')}: 결과 값 오류({t.get('result')})")
        if carry.get("sets") is not None:
            from bestar import link
            probs += link.problems(carry["sets"], f.get("cells") or {}, "carry.sets")
            probs += [f"carry.sets[{n}]: why(어느 전제인지)를 씁니다" for n, s in enumerate(carry["sets"] or [], 1)
                      if isinstance(s, dict) and not str(s.get("why") or "").strip()]
    return probs


def check_step(c, step_id: str) -> list[str]:
    path = paths.steps_dir(c) / f"{step_id}.json"
    if not path.exists():
        return [f"{path} 가 없습니다"]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return [f"{path.name}: JSON 오류 {e}"]
    f = engine_facts(c)
    if not f["ar"]:
        return ["AR.json 이 없습니다. 먼저 ar.py engine 을 돌리세요"]
    if step_id == "F1":
        f["ledger"] = paths.read_json(paths.index(c) / "장부.json", {}) or {}
        f["p3"] = load_step(c, "P3")["carry"]
        f["nums"] = numbers.known(c)
    if step_id in ("F1", "F2"):
        from bestar import link
        f["cells"] = link.cells(c)
    probs = []
    if data.get("id") != step_id or data.get("step") != LABEL[step_id]:
        probs.append(f'id/step 은 "{step_id}" / "{LABEL[step_id]}"')
    for key in ("finding", "note"):
        if not str(data.get(key) or "").strip():
            probs.append(f"{key} 가 비었습니다")
    probs += carry_problems(step_id, data.get("carry") or {}, f)
    plain = _without_sets(data)          # 조서 칸 key · 값은 글 · 금액 검사에서 뺀다(link.problems 가 따로 본다)
    probs += numbers.style_problems(plain, step_id)
    probs += numbers.amount_problems(plain, numbers.known(c), step_id, skip=NOT_MONEY)
    return probs


def _without_sets(obj):
    if isinstance(obj, dict):
        return {k: _without_sets(v) for k, v in obj.items() if k != "sets"}
    if isinstance(obj, list):
        return [_without_sets(v) for v in obj]
    return obj


# ---------------------------------------------------------------- 진행 기록
def digest(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def read_log(c) -> list[dict]:
    return paths.read_json(paths.steps_dir(c) / "순서.json", []) or []


def write_log(c, log: list[dict]) -> None:
    paths.write_json(paths.steps_dir(c) / "순서.json", log)


def stale(c, log: list[dict]) -> str | None:
    """끝났다고 적은 뒤 파일이 바뀐 첫 단계."""
    for entry in log:
        path = paths.steps_dir(c) / f"{entry['id']}.json"
        if not path.exists() or digest(path) != entry["sha"]:
            return entry["id"]
    return None


def load_step(c, step_id: str) -> dict:
    return json.loads((paths.steps_dir(c) / f"{step_id}.json").read_text(encoding="utf-8"))


def premise(c, upto: str | None) -> list[dict]:
    out = []
    for step_id in (ORDER[:ORDER.index(upto)] if upto in ORDER else ORDER):
        d = load_step(c, step_id)
        out.append({"id": step_id, "step": LABEL[step_id], "title": TITLE[step_id], "finding": d.get("finding", ""),
                    "note": d.get("note", ""), "carry": d["carry"], "ask": d.get("ask", [])})
    return out


def finished(c) -> bool:
    log = read_log(c)
    return [e["id"] for e in log] == ORDER and not stale(c, log)


def handed(c) -> list[tuple[str, str, str, dict]]:
    """앞 단계가 넘긴 항목 (id, 이름, 단계, 항목)."""
    out = []
    p3, p4, f1 = (load_step(c, s)["carry"] for s in ("P3", "P4", "F1"))
    out += [(x["id"], x.get("item") or "", "1-(3)", x) for x in p3.get("forecast") or []]
    out += [(x["id"], x.get("name") or "", "1-(4)", x) for x in p4.get("forecast") or []]
    out += [(x["id"], x.get("account") or "", "2-(1)", x) for x in f1.get("accounts") or []]
    return out


# ---------------------------------------------------------------- 명령
def cmd_status(c) -> int:
    log = read_log(c)
    done = [e["id"] for e in log]
    bad = stale(c, log)
    for step_id in ORDER:
        mark = "끝" if step_id in done else "  "
        if bad and step_id in done and done.index(step_id) >= done.index(bad):
            mark = "다시"
        print(f"[{mark:>2}] {LABEL[step_id]} {step_id} {TITLE[step_id]}")
    print(f"이슈 메모 · 공제 제안: {'시작 가능' if finished(c) else '여섯 단계 뒤'}")
    return 0


def cmd_next(c) -> int:
    log = read_log(c)
    bad = stale(c, log)
    if bad:
        print(f"{LABEL[bad]} {bad} 파일이 끝난 뒤 바뀌었습니다. `ar.py step done <신고건> {bad} --redo` 로 다시 적고 그 뒤 단계를 다시 하세요.")
        return 1
    done = [e["id"] for e in log]
    if len(done) == len(ORDER):
        print(json.dumps({"next": "이슈 메모", "message": "여섯 단계가 끝났습니다. _색인/AR_단계/전제.json 을 읽고 이슈 메모(ar.py memo)와 공제 · 감면 제안(ar.py credits)을 씁니다."},
                         ensure_ascii=False, indent=1))
        return 0
    f = engine_facts(c)
    if not f["ar"]:
        print("AR.json 이 없습니다. 먼저 ar.py engine 을 돌리세요")
        return 2
    step_id = ORDER[len(done)]
    f["ledger"] = paths.read_json(paths.index(c) / "장부.json", {}) or {}
    print(json.dumps({"next": LABEL[step_id], "id": step_id, "title": TITLE[step_id],
                      "write": f"_색인/{paths.STEPS_DIR}/{step_id}.json", "how": "references/sequence.md 의 해당 단계",
                      "engine": step_view(step_id, f), "premise": premise(c, step_id)}, ensure_ascii=False, indent=1))
    return 0


def cmd_done(c, step_id: str, redo: bool) -> int:
    if step_id not in ORDER:
        print(f"{step_id} 는 순서 단계가 아닙니다({', '.join(ORDER)}).")
        return 2
    log = read_log(c)
    done = [e["id"] for e in log]
    if step_id in done and not redo:
        print(f"{LABEL[step_id]} {step_id} 는 이미 끝났습니다. 고쳤다면 --redo 를 붙이세요(뒤 단계를 다시 해야 합니다).")
        return 1
    if step_id in done:
        dropped = done[done.index(step_id):]
        log = log[:done.index(step_id)]
        if len(dropped) > 1:
            print(f"뒤 단계 {', '.join(LABEL[d] for d in dropped[1:])} 를 다시 해야 합니다.")
    else:
        bad = stale(c, log)
        if bad:
            print(f"{LABEL[bad]} {bad} 파일이 끝난 뒤 바뀌었습니다. 먼저 `ar.py step done <신고건> {bad} --redo`.")
            return 1
        expected = ORDER[len(log)]
        if step_id != expected:
            print(f"순서가 아닙니다. 지금은 {LABEL[expected]} {expected} 차례입니다.")
            return 1
    probs = check_step(c, step_id)
    if probs:
        print(f"{LABEL[step_id]} {step_id} 를 끝낼 수 없습니다:\n- " + "\n- ".join(probs))
        return 1
    path = paths.steps_dir(c) / f"{step_id}.json"
    log.append({"id": step_id, "step": LABEL[step_id], "sha": digest(path), "at": datetime.now().isoformat(timespec="seconds")})
    write_log(c, log)
    target = paths.steps_dir(c) / "전제.json"
    if len(log) == len(ORDER):
        paths.write_json(target, premise(c, None))
        print(f"{LABEL[step_id]} {step_id} 끝. 여섯 단계가 끝나 {paths.STEPS_DIR}/전제.json 을 만들었습니다. 다음은 이슈 메모입니다.")
        from bestar import link
        if link.xlsx_path(c).exists():
            r = link.sync(c)
            names = link.paper_names(c)
            for w in r["writes"]:
                print(f"  조서 칸: {link.describe(w, names)} (전 {w['current']}) · {w['source']}")
            for w in r["kept"]:
                print(f"  조서 칸 둠: {link.describe(w, names)} (지금 {w['current']}) · {w['why']}")
            msg = link.notice(r, names)
            print(f"  {msg}" if msg else "  조서 칸: 2-(2) 전제와 조서 노란 칸이 이미 같아 바꾼 것이 없습니다.")
    else:
        if target.exists():
            target.unlink()
        print(f"{LABEL[step_id]} {step_id} 끝. 다음은 {LABEL[ORDER[len(log)]]} {ORDER[len(log)]}.")
    return 0


def cmd_outside(c) -> int:
    """엔진 규칙에 안 걸린 계정 목록(F1 others_reviewed 로 훑을 것). 아직 안 훑은 것에 「아직」."""
    ledger = paths.read_json(paths.index(c) / "장부.json", {}) or {}
    ar = paths.read_ar(c)
    f1 = load_step(c, "F1")["carry"] if (paths.steps_dir(c) / "F1.json").exists() else {}
    left = set(outside_unreviewed(ledger, ar, f1))
    rows = outside_accounts(ledger, ar, f1)
    for r in rows:
        clean = re.sub(r"\((판|제|도)\)$", "", str(r["name"])).strip()
        print(f"{'아직' if clean in left else '훑음'}  {r['code']:>8}  {r['name']}  {r['class']}  {int(r['amount'] or 0):,}")
    print(f"모두 {len(rows)}개, 아직 {len(left)}개")
    return 0


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="ar.py step")
    p.add_argument("command", choices=["next", "done", "status", "outside"])
    p.add_argument("folder")
    p.add_argument("step", nargs="?")
    p.add_argument("--redo", action="store_true")
    a = p.parse_args(argv)
    c = paths.case(a.folder)
    if a.command == "next":
        return cmd_next(c)
    if a.command == "status":
        return cmd_status(c)
    if a.command == "outside":
        return cmd_outside(c)
    if not a.step:
        print("done 에는 단계 ID 가 필요합니다(P1 …)")
        return 2
    return cmd_done(c, a.step, a.redo)
