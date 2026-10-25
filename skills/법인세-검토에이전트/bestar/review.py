# -*- coding: utf-8 -*-
"""목업 「3. 분석적 검토」 화면의 자료(window.DATA)를 만든다. 꼴은 assets/review.html 의 주석과 docs 설계 5절.

- 근거가 분명한 세무조정: 조서 계산(조정.json adjustments). 「모두 반영」 은 회계사 확인 표시다.
- 사람의 판단이 필요한 것: 판단 필요 이슈 · AI 추가 이슈 · 공제 제안 · 기업 구분(조서에 이미 금액이 잡힌 이슈는 뺀다).
- 확인할 것(질문지): 위 항목 가운데 AI 가 choices 를 붙인 것.
- 한 장 요약: 조정.json summary(3호 흐름)와 세 묶음 요약.
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime

from bestar import decide, finish, link, numbers, paths, rank

SIDE = {"가산": "가산", "차감": "차감"}
JUDGE_BADGE = {"조정 필요": ("확신 높음", "secondary"), "판단 필요": ("확인 필요", "outline"), "조정 없음": ("확인만", "outline")}


def won(n) -> str:
    if not isinstance(n, (int, float)):
        return ""
    n = int(round(n))
    return ("△" if n < 0 else "") + f"₩{abs(n):,}"


def _vouchers(rows: list[dict]) -> dict:
    v = defaultdict(list)
    for r in rows:
        v[(r.get("date"), r.get("no"))].append(r)
    return v


def _num(x) -> int:
    try:
        return int(round(float(x or 0)))
    except ValueError:
        return 0


def entries_for(accounts: list[str], rows: list[dict], vouchers: dict, limit: int = 5) -> list[dict]:
    """계정 코드들의 전표 줄 가운데 금액 큰 순(손익 마감 줄 제외). 차변 / 대변 은 같은 전표의 계정."""
    acc = {str(a) for a in accounts or []}
    hits = [r for r in rows if str(r.get("account")) in acc and str(r.get("closing")) not in ("1", "True", "true")]
    hits.sort(key=lambda r: -max(abs(_num(r.get("debit"))), abs(_num(r.get("credit")))))
    out = []
    for r in hits[:limit]:
        lines = vouchers.get((r.get("date"), r.get("no")), [])
        dr = sorted({x.get("account_name") for x in lines if _num(x.get("debit"))})
        cr = sorted({x.get("account_name") for x in lines if _num(x.get("credit"))})
        out.append({"date": str(r.get("date") or "").replace("-", "."), "memo": r.get("memo") or r.get("partner") or "",
                    "accts": f"{', '.join(dr[:2]) or '-'} / {', '.join(cr[:2]) or '-'}",
                    "amount": won(max(_num(r.get("debit")), _num(r.get("credit")))), "line": r["line"]})
    return out


def answer_text(q: dict | None, ans: dict | None) -> str:
    if not ans:
        return ""
    opts = {o["value"]: o.get("label") for o in (q or {}).get("options") or []}
    if "values" in ans:
        txt = ", ".join(opts.get(v, v) for v in ans["values"]) or "고른 것 없음"
    else:
        txt = opts.get(ans.get("value"), ans.get("value") or "")
    if ans.get("other"):
        txt = (txt + " · " if txt else "") + ans["other"]
    return txt


def _ask_key(q: str) -> str:
    return re.sub(r"[\s.·,()「」]", "", str(q)).replace("보내주십시오", "").replace("알려주십시오", "")


def same_ask(a: str, b: str) -> bool:
    """같은 자료 요청인지. 조사 앞까지 줄인 머리가 다른 쪽의 앞부분이면 같다(「2025년 말 주주명부를」 과 「2025년 말 주주명부와 …」)."""
    if a == b:
        return True
    ha, hb = (re.sub(r"[을를와과이가은는의및]$", "", re.split(r"(?<=[가-힣])(?:을|를|와|과)(?=[0-9가-힣])", x)[0]) for x in (a, b))
    short, long_ = sorted((ha, hb), key=len)
    return len(short) >= 6 and long_.startswith(short)


def company_asks(base: dict, ar: dict, added: list[dict], credits: dict) -> list[dict]:
    """회사에 보낼 자료 요청 모음. 같은 글은 한 번, 회계사 결정(답변 필요)은 빼고, 어디서 나왔는지 함께."""
    out: dict[str, dict] = {}

    def put(q, where):
        q = str(q or "").strip()
        if not q or q.startswith("답변 필요"):
            return
        k = _ask_key(q)
        hit = next((v for kk, v in out.items() if same_ask(k, kk)), None)
        if hit:
            if len(q) > len(hit["ask"]):
                hit["ask"] = q
            if where not in hit["from"]:
                hit["from"].append(where)
            return
        out[k] = {"ask": q, "from": [where]}

    for s in base.get("steps") or []:
        for q in s.get("ask") or []:
            put(q, s.get("step"))
    from bestar.rank import questions_of
    for i in ar.get("issues", []):
        for q in questions_of(i):
            put(q, f"이슈 {i['no']}")
    for a in added:
        for q in a.get("ask") or []:
            put(q, f"AI 추가 {a['id']}")
    for n, x in enumerate((credits or {}).get("items") or [], 1):
        for q in x.get("ask") or []:
            put(q, f"공제 {x.get('name')}")
    # 가장 중요한 3가지의 요청 → 확인사항 → 나머지 순
    summ = base.get("summary") or {}
    rank_of = {}
    for r, tier in enumerate(("top", "check", "detail")):
        for u in summ.get(tier) or []:
            for q in u.get("asks") or []:
                rank_of.setdefault(_ask_key(q), r)
    for v in out.values():
        v["tier"] = min((r for k, r in rank_of.items() if same_ask(k, _ask_key(v["ask"]))), default=3)
    return sorted(out.values(), key=lambda v: v["tier"])


def build(c, mode_gaps: list[str] | None = None) -> dict:
    base = finish.collect(c, mode_gaps)
    ar, credits, added = base["ar"], base["credits"], base["added"]
    adj_doc = paths.read_json(paths.index(c) / "조정.json", {}) or {}
    adjustments = adj_doc.get("adjustments") or []
    papers = {p["id"]: p for p in adj_doc.get("papers") or []}
    keys = decide.stable_keys(ar, adjustments, credits)
    for a in added:
        keys[f"added:{a['id']}"] = f"added|{a['id']}"
    dec = decide.load(c)
    rows = numbers.journal_rows(c)
    vouchers = _vouchers(rows)
    by_no = {i["no"]: i for i in ar.get("issues", [])}
    from bestar import memos
    extras = memos.extras(c)

    # 조서에 금액이 잡힌 이슈(그 조서의 issues)
    covered = set()
    for a in adjustments:
        covered.update((papers.get(a.get("paper")) or {}).get("issues") or [])

    cards, questions, judgments, others = {}, [], [], []

    def decision(uid):
        return dec["decisions"].get(keys.get(uid, uid))

    def accepted(uid):
        return keys.get(uid, uid) in dec["accepted"]

    names = {pid: p.get("name") or pid for pid, p in papers.items()}

    def add_question(uid, ch, kind):
        if not ch:
            return None
        q = {"uid": uid, "title": ch.get("title"), "description": ch.get("description") or "", "kind": kind,
             "multiple": bool(ch.get("multiple")), "allow_other": bool(ch.get("allow_other")),
             "options": [{"value": o["value"], "label": o.get("label"), "effect": o.get("effect") or "",
                          "sets_text": [link.describe(s, names) for s in o.get("sets") or [] if isinstance(s, dict)]}
                         for o in ch.get("options") or []],
             "answer": decision(uid)}
        questions.append(q)
        return q

    # 조서 조정
    adj_rows = []
    for n, a in enumerate(adjustments):
        uid = f"adj:{n}"
        p = papers.get(a.get("paper")) or {}
        acc = sorted({x for no in p.get("issues") or [] for x in (by_no.get(no) or {}).get("accounts") or []})
        vals = [(k, v) for k, v in (p.get("values") or {}).items() if isinstance(v, (int, float)) and v]
        is_acc = accepted(uid)
        cards[uid] = {"badge": "반영됨" if is_acc else "확신 높음", "badge_variant": "default" if is_acc else "secondary",
                      "kind": f"{SIDE.get(a.get('side'), a.get('side'))} · {a.get('disposition')}",
                      "title": a.get("kind") or a.get("subject"),
                      "sub": f"{a.get('subject')} {won(a.get('amount'))} · {a.get('disposition')} · 조서 {p.get('no', '')} {p.get('name', '')}".strip(),
                      "result": "세무조정에 반영했어요" if is_acc else "",
                      "comment": " ".join([str(a.get("note") or "")] + [str(x) for x in (p.get("notes") or [])[:1]]).strip(),
                      "basis": [{"label": k, "value": won(v)} for k, v in vals[:8]],
                      "law": [], "entries": entries_for(acc, rows, vouchers, 3),
                      "foot": "금액은 조서 계산(엔진)입니다. 조서 엑셀 2 조서/조서.xlsx 의 노란 칸을 고치면 ar.py engine 을 다시 돌립니다."}
        adj_rows.append({"uid": uid, "subject": a.get("subject"), "side": a.get("side"), "kind": a.get("kind"),
                         "amount": a.get("amount"), "disposition": a.get("disposition"), "paper_name": p.get("name"), "accepted": is_acc})

    # 이슈
    units = {u["uid"]: u for t in ("top", "check", "detail") for u in base["summary"][t]}
    for i in ar.get("issues", []):
        uid = f"issue:{i['no']}"
        memo = i.get("memo") or {}
        ex = extras.get(i["no"], {})
        judgment = memo.get("judgment")
        ans = decision(uid)
        q = add_question(uid, ex.get("choices"), i["kind"]) if judgment != "조정 없음" else None
        concl = i.get("conclusion")
        result = answer_text(q, ans) or ((concl or {}).get("text") if concl else "")
        badge, var = JUDGE_BADGE.get(judgment, ("엔진 이슈", "outline"))
        if result:
            badge, var = "반영됨", "default"
        a = i.get("amounts") or {}
        basis = []
        for lab, k in (("당기", "current"), ("전기", "prior"), ("증감", "change")):
            if isinstance(a.get(k), (int, float)):
                basis.append({"label": lab, "value": won(a[k])})
        if i.get("prior_treatment"):
            basis.append({"label": "전기 처리", "value": i["prior_treatment"]})
        for n, b in enumerate(i.get("basis") or [], 1):
            basis.append({"label": f"근거 {n}", "value": b})
        for fid in ex.get("facts") or []:
            f = next((x for x in base.get("facts") or [] if x["id"] == fid), None)
            if f:
                basis.append({"label": f"{'엔진 합계' if f['type'] == '합계' else '전기 PDF(확인 전)'} {fid}",
                              "value": f"{f['what']}: {won(f.get('net') if f['type'] == '합계' else f.get('amount'))}"})
        qs = list(memo.get("questions") or i.get("questions") or [])
        cards[uid] = {"badge": badge, "badge_variant": var, "kind": i["kind"], "title": i["title"],
                      "sub": " · ".join(x for x in [", ".join(i.get("accounts") or []) and "계정 " + ", ".join(i.get("accounts")), won(a.get("current")) and "당기 " + won(a.get("current")), f"위험 {ex.get('risk')}" if ex.get("risk") else ""] if x),
                      "result": result, "comment": memo.get("why") or "엔진이 찾은 이슈입니다. AI 메모가 아직 없습니다.",
                      "basis": basis, "law": memo.get("law") or i.get("law") or [], "entries": entries_for(i.get("accounts"), rows, vouchers),
                      "foot": ("회사에 물을 것: " + " / ".join(qs)) if qs else ""}
        u = units.get(uid, {})
        if judgment == "조정 없음" or i["no"] in covered or u.get("routine") or i["kind"] == "서식 필요" and judgment != "판단 필요":
            others.append({"uid": uid, "title": i["title"], "kind": "조서에 반영" if i["no"] in covered else i["kind"], "judgment": judgment or "메모 없음"})
        else:
            judgments.append({"uid": uid, "title": i["title"], "impact": i["kind"], "amount": u.get("size") or None,
                              "state": "반영됨" if result else ("답변 필요" if q else "직접 판단")})

    # AI 추가 이슈
    f1 = {x["id"]: x for x in (next(s for s in base["steps"] if s["id"] == "F1")["carry"].get("accounts") or [])}
    for a in added:
        uid = f"added:{a['id']}"
        q = add_question(uid, a.get("choices") or (f1.get(a["id"]) or {}).get("choices"), "AI 추가")
        result = answer_text(q, decision(uid)) or ((a.get("conclusion") or {}).get("text") or "")
        cards[uid] = {"badge": "반영됨" if result else "확인 필요", "badge_variant": "default" if result else "outline", "kind": "AI 추가 이슈",
                      "title": f"{a.get('account')}", "sub": " · ".join(x for x in [won(a.get("current")) and "당기 " + won(a.get("current")), f"위험 {a.get('risk')}"] if x),
                      "result": result, "comment": a.get("why") or "", "basis": [{"label": "확인한 사실", "value": a.get("finding") or ""}],
                      "law": a.get("law") or [], "entries": [], "foot": ("받을 자료: " + " / ".join(a.get("ask"))) if a.get("ask") else "엔진 규칙에 걸리지 않아 2-(1) 에서 AI 가 고른 계정입니다."}
        judgments.append({"uid": uid, "title": f"{a.get('account')} (AI 추가)", "impact": "AI 추가 이슈", "amount": a.get("current"),
                          "state": "반영됨" if result else ("답변 필요" if q else "직접 판단")})

    # 공제 제안
    lines = {r["line"]: r for r in rows}
    for n, x in enumerate(credits.get("items") or [], 1):
        uid = f"credit:{n}"
        q = add_question(uid, x.get("choices"), "세액공제") if x.get("state") != "적용 불가" else None
        result = answer_text(q, decision(uid))
        ents = []
        for k in x.get("candidates") or []:
            r = lines.get(k.get("line")) or {}
            ents.append({"date": str(r.get("date") or "").replace("-", "."), "memo": k.get("what") or r.get("memo") or "",
                         "accts": r.get("account_name") or "", "amount": won(k.get("amount")), "line": k.get("line")})
        cards[uid] = {"badge": "반영됨" if result else ("직접 판단" if x.get("state") != "적용 불가" else "적용 불가"),
                      "badge_variant": "default" if result else "outline", "kind": f"세액공제 · {x.get('state')}",
                      "title": x.get("name"), "sub": x.get("basis") or "", "result": result, "comment": x.get("purpose") or "",
                      "basis": [{"label": f"판단할 점 {m}", "value": j} for m, j in enumerate(x.get("judge") or [], 1)],
                      "law": [], "entries": ents, "foot": ("받을 자료: " + " / ".join(x.get("ask"))) if x.get("ask") else ""}
        if x.get("state") == "적용 불가":
            others.append({"uid": uid, "title": x.get("name"), "kind": "공제 적용 불가", "judgment": "조정 없음"})
        else:
            judgments.append({"uid": uid, "title": x.get("name"), "impact": f"세액공제 · {x.get('state')}",
                              "amount": max([abs(int(k.get("amount") or 0)) for k in x.get("candidates") or []] or [0]) or None,
                              "state": "반영됨" if result else ("답변 필요" if q else "직접 판단")})

    # 기업 구분
    f2 = next(s for s in base["steps"] if s["id"] == "F2")["carry"]
    cards["sme"] = {"badge": "판정" if f2.get("status") == "확정" else "확인 필요", "badge_variant": "default" if f2.get("status") == "확정" else "outline",
                    "kind": "기업 규모", "title": f"{f2.get('verdict')} 판정", "sub": "조세특례제한법 시행령 제2조 기준",
                    "result": f"{f2.get('premise')} 전제로 검토했어요", "comment": " ".join(x for x in [f2.get("point"), f2.get("effects") if isinstance(f2.get("effects"), str) else " ".join(f2.get("effects") or [])] if x),
                    "basis": [{"label": t.get("name"), "value": " · ".join(x for x in [t.get("result"), t.get("fact"), t.get("basis")] if x)} for t in f2.get("tests") or []],
                    "law": [], "entries": [], "foot": ("받을 자료: " + " / ".join(f2.get("ask"))) if f2.get("ask") else ""}
    linked = [{"text": link.describe(v, names), "source": v.get("source")}
              for v in ((paths.read_json(link.state_path(c), {}) or {}).get("linked") or {}).values()]
    cards["sme"]["basis"] += [{"label": "조서에 넣은 전제", "value": x["text"]} for x in linked if str(x["source"]).startswith(link.PREMISE)]

    from bestar import sheet
    ar_sheet = sheet.build(ar, base["steps"], adjustments, papers, added, credits, questions, won,
                           ledger=paths.read_json(paths.index(c) / "장부.json", {}) or {})

    # 한 장 요약 · 진행 · 자료
    s = adj_doc.get("summary") or {}
    income = {"net_income": s.get("net_income"), "add": s.get("add"), "deduct": s.get("deduct"),
              "add_count": sum(1 for a in adjustments if a.get("side") == "가산"),
              "deduct_count": sum(1 for a in adjustments if a.get("side") == "차감"),
              "income": s.get("income"), "tax_base": s.get("tax_base"), "computed_tax": s.get("computed_tax"),
              "credits": s.get("credits"), "determined_tax": s.get("determined_tax"),
              "donation_excess": s.get("donation_excess"), "loss_used": s.get("loss_used"), "penalty": s.get("penalty"),
              "prepaid": s.get("prepaid"), "payable": s.get("payable")}
    # 회계사 답에 따라 더해질 수 있는 조정(조서가 「확인 필요」 로 두고 금액만 계산해 둔 것: 인정이자 특수관계인일 때 등)
    pending_adj = []
    for p in adj_doc.get("papers") or []:
        vals = p.get("values") or {}
        cand = [v for k, v in vals.items() if isinstance(v, (int, float)) and not isinstance(v, bool) and v
                and ("때 조정액" in k or ("확인 필요" in k and "조정액" in k))]
        if cand and not any(a.get("paper") == p["id"] for a in adjustments):
            from bestar import stake as stake_mod
            pending_adj.append({"paper": p.get("name") or p["id"], "paper_id": p["id"], "amount": max(cand),
                                "tax": stake_mod.tax_delta(adj_doc.get("summary") or {}, {"amount": int(max(cand)), "side": "가산"}),
                                "why": next((n for n in p.get("notes") or [] if "확인 필요" in n or "특수관계인이면" in n), "")})
    top_adj = max(adjustments, key=lambda a: abs(a.get("amount") or 0), default=None)
    directions = []
    if adjustments:
        directions.append(f"세무조정 {len(adjustments)}건은 조서 계산 근거가 분명해요. 가장 큰 건은 {top_adj.get('kind') or top_adj.get('subject')} {won(top_adj.get('amount'))}이에요.")
    directions += [f"{u['title']}: {u['line']}" if u.get("line") else u["title"] for u in base["summary"]["top"]]
    if f2.get("status") != "확정":
        directions.append(f"기업 구분은 {f2.get('premise')} 전제예요. {f2.get('point') or ''}".strip())
    open_q = sum(1 for q in questions if not q["answer"])
    info = c.info()
    ledger = paths.read_json(paths.index(c) / "장부.json", {}) or {}
    checks = ledger.get("checks") or []
    prior = paths.read_json(paths.index(c) / "전기.json", {}) or {}
    period_no = (prior.get("company") or {}).get("period_no")
    received = sorted(p for p in (c.root / "00 받은자료").rglob("*") if p.is_file()) if (c.root / "00 받은자료").exists() else []
    stages = [
        {"label": "자료 입력", "state": "done", "note": f"{len(received)}개 자료"},
        {"label": "표준재무제표", "state": "done" if all(x.get("ok") for x in checks) else "current",
         "note": f"대사 {sum(1 for x in checks if x.get('ok'))} / {len(checks)}"},
        {"label": "분석적 검토", "state": "current", "note": f"{open_q}건 남음" if open_q else "완료"},
        {"label": "서식 총괄표", "state": "todo", "note": ""},
        {"label": "신고", "state": "todo", "note": "준비 중"},
    ]
    materials = {"files": [{"name": p.stem, "file": p.relative_to(c.root / "00 받은자료").as_posix(),
                            "when": datetime.fromtimestamp(p.stat().st_mtime).strftime("%m.%d")} for p in received],
                 "requested": [{"name": q, "from": "분석적 검토"} for q in base["summary"]["first_asks"]]}
    first_open = next((q["uid"] for q in questions if not q["answer"]), None)
    default = first_open or (base["summary"]["top"][0]["uid"] if base["summary"]["top"] else ("adj:0" if adjustments else "sme"))
    if default not in cards:
        default = "sme"
    return {
        "case": f"{c.root.parent.name}/{c.root.name}", "company": base["company"], "fy": base["fy"], "fy_start": base["fy_start"], "fy_end": base["fy_end"],
        "period": f"제{int(period_no) + 1}기 · " if isinstance(period_no, int) else "", "generated_at": base["generated_at"],
        "stages": stages, "materials": materials, "sme": {k: f2.get(k) for k in ("verdict", "status", "premise", "point")},
        "questions": questions, "adjustments": adj_rows,
        "adjust_total": {"add": s.get("add") or 0, "deduct": s.get("deduct") or 0},
        "judgments": judgments, "others": others, "cards": cards, "default_card": default,
        "income": income, "directions": directions, "summary": base["summary"], "gaps": base.get("gaps") or [],
        "progress": base["progress"], "keys": keys, "ar_sheet": ar_sheet, "linked": linked,
        "pending_adjustments": pending_adj, "facts": base.get("facts") or [], "reserves": adj_doc.get("reserves") or [],
        "adjust_without_paper": [i["title"] for i in ar.get("issues", []) if (i.get("memo") or {}).get("judgment") == "조정 필요"
                                 and i["no"] not in covered and not any(a.get("paper") in (i.get("papers") or []) for a in adjustments)
                                 and not ("donation" in (i.get("papers") or []) and (adj_doc.get("summary") or {}).get("donation_excess"))  # 한도초과는 3호 05란
                                 and i["kind"] != "서식 필요" and not rank.routine(i)]
                                + [f"{a.get('account')} (AI 추가)" for a in added if a.get("judgment") == "조정 필요"],
        "prior_tax": ((paths.read_json(paths.index(c) / "전기.json", {}) or {}).get("cells") or {}).get("3", {}).get("12"),
        "company_asks": company_asks(base, ar, added, credits),
        "laws": [{"title": i["title"], "judgment": (i.get("memo") or {}).get("judgment"), "law": (i.get("memo") or {}).get("law") or i.get("law") or []}
                 for i in ar.get("issues", []) if (i.get("memo") or {}).get("judgment") in ("조정 필요", "판단 필요")]
                + [{"title": f"{a.get('account')} (AI 추가)", "judgment": a.get("judgment"), "law": a.get("law") or []} for a in added]
                + [{"title": f"{x.get('name')} (공제 제안)", "judgment": x.get("state"), "law": [{"ref": x.get("basis"), "grade": ""}]}
                   for x in (credits or {}).get("items") or [] if x.get("basis") and x.get("state") != "적용 불가"],
        "others_reviewed": (next(s for s in base["steps"] if s["id"] == "F1")["carry"].get("others_reviewed") or []),
    }
