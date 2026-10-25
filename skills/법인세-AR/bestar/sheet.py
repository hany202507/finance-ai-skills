# -*- coding: utf-8 -*-
"""AR 한 장: 전사 기준 · 재무제표 계정별 · 세액공제 세 묶음으로, 항목마다 관련 · 추정 판단 · 추가 요청을 한 줄에.

가이드(이정아 회계사 AR 가이드) 줄과의 대응
  전사 기준   1-(1) 회사 종류 · 1-(2) 주식변동 · 임대업 · 1-(3) 전기 조정 · 유보 · 2-(1) 재무제표 훑기 · 2-(2) 당기 중소기업
  계정별      2-(3) 계정 22묶음 가운데 공제 계정을 뺀 18묶음, 조서 조정, AI 추가 이슈
  세액공제    1-(4) 전기 공제 · 감면, 공제 계정(6 기계장치 · 13 인건비 · 14 연구개발비 · 17 운반비), 공제감면 이슈, 공제 제안
"""
from __future__ import annotations

import re

CREDIT_ACCOUNTS = {6, 13, 14, 17}
COMPANY_GUIDES = {"P1": "1-1", "P2": "1-2", "P3": "1-3", "F1": "2-1", "F2": "2-2"}
# 조서 → 가이드 계정 묶음 번호(조서에 이슈가 안 붙은 조정을 계정에 놓을 때)
PAPER_GROUP = {"accrued_expense": 9, "accrued_income": 4, "bad_debt": 2, "business_car": 21, "corporate_tax": 15,
               "depreciation": 5, "dividend": 1, "donation": 22, "entertainment": 16, "loan_interest": 3, "interest_denial": 3,
               "prior_error": 18, "retirement": 9, "securities": 1, "taxes_dues": 15}
# 공제 계정 → 같은 제도의 공제 제안 이름
CREDIT_NAME = {6: r"투자", 13: r"고용|사회보험료", 14: r"연구", 17: r"투자"}
SEVERITY = {"조정 필요": 5, "판단 필요": 4, "자료 필요": 3, "확인": 2, "조정 없음": 1, "해당 없음": 0}
STATUS_JUDGE = {"이슈": "판단 필요", "해당 없음": "해당 없음", "자료 필요": "자료 필요"}


def _group_no(guide_id: str) -> int | None:
    m = re.match(r"2-3-(\d+)-", guide_id or "")
    return int(m.group(1)) if m else None


def _first(text: str, n: int = 110) -> str:
    text = (text or "").strip()
    m = re.match(r"(.+?[다요음함])\.(\s|$)", text)
    s = (m.group(1) + ".") if m else text
    return s if len(s) <= n else s[:n - 1] + "…"


def _worst(*js) -> str:
    js = [j for j in js if j]
    return max(js, key=lambda j: SEVERITY.get(j, 0)) if js else "해당 없음"


def _won(n) -> str:
    if not isinstance(n, (int, float)):
        return ""
    n = int(round(n))
    return ("△" if n < 0 else "") + f"₩{abs(n):,}"


def _dedupe(xs, limit=3):
    out = []
    for x in xs:
        if x and x not in out:
            out.append(x)
    return out[:limit]


def account_coverage(ledger: dict, ar: dict, steps: list[dict]) -> dict:
    """시산표의 모든 계정(금액이 있는 것)이 어디서 다뤄졌는지. 엔진 계정 묶음(topic) · 엔진 이슈 · 2-(1) AI 가 고른 계정 · 그 밖."""
    from ctax.ar.topics import TOPICS, topics_of
    f1 = next((s for s in steps if s["id"] == "F1"), {}).get("carry") or {}
    named = " ".join(str(a.get("account") or "") for a in f1.get("accounts") or [])
    issue_acc = {str(x) for i in ar.get("issues", []) for x in i.get("accounts") or []}
    rows = []
    for a in ledger.get("accounts") or []:
        amt = a.get("amount") if a.get("amount") not in (None, 0) else a.get("closing")
        if not amt or a.get("class") == "손익대체":
            continue
        tps = topics_of(a)
        name = str(a.get("name") or "")
        clean = re.sub(r"\((판|제|도)\)$", "", name).strip()
        if str(a.get("code")) in issue_acc:
            how = "엔진 이슈"
        elif clean and clean in named:
            how = "AI 가 2-(1) 에서 봄"
        elif tps:
            how = "엔진 규칙(" + ", ".join(TOPICS[t][0] for t in tps[:2]) + ")"
        else:
            how = ""
        rows.append({"code": a.get("code"), "name": name, "class": a.get("class"), "amount": amt, "how": how})
    rows.sort(key=lambda r: -abs(r["amount"] or 0))
    outside = [r for r in rows if not r["how"]]
    return {"total": len(rows), "covered": len(rows) - len(outside), "outside": outside, "rows": rows}


def form_coverage(ar: dict) -> dict:
    fs = ar.get("forms") or []
    return {"total": len(fs), "yes": sum(1 for f in fs if f.get("status") == "해당"),
            "check": [{"code": f.get("code"), "name": f.get("name"), "by": f.get("by"), "prior": f.get("prior_filed")}
                      for f in fs if f.get("status") == "확인"],
            "no": sum(1 for f in fs if f.get("status") == "해당 없음")}


def build(ar: dict, steps: list[dict], adjustments: list[dict], papers: dict, added: list[dict], credits: dict,
          questions: list[dict], won_of=_won, ledger: dict | None = None) -> dict:
    """review.build 가 부른다. steps 는 finish.collect 의 steps(P1~F2), questions 는 화면 질문지(답 포함)."""
    st = {s["id"]: s for s in steps}
    guide = {g["id"]: g for g in ar.get("guide", [])}
    issues = ar.get("issues", [])
    pending = {q["uid"] for q in questions if not q.get("answer")}
    qtitle = {q["uid"]: q["title"] for q in questions}

    def memo_j(i):
        return (i.get("memo") or {}).get("judgment") or ("판단 필요" if i["kind"] != "서식 필요" else "확인")

    def issue_asks(i):
        uid = "issue:%s" % i["no"]
        out = ["답변 필요: " + qtitle[uid]] if uid in pending else []
        from bestar.rank import questions_of
        return out + questions_of(i)

    def is_credit_issue(i):
        return i["kind"] == "공제감면" or any(_group_no(g) in CREDIT_ACCOUNTS for g in i.get("guide") or [])

    def row(key, title, relation, judgment, text, asks, uids, amount=None, guide_ids=(), state=None):
        uids = [u for u in dict.fromkeys(uids) if u]
        return {"key": key, "title": title, "relation": relation, "judgment": judgment, "judgment_text": text,
                "amount": amount, "asks": _dedupe(asks), "uids": uids, "guide": list(guide_ids),
                "pending": sum(1 for u in uids if u in pending), "state": state}

    used_issue = set()

    # ---------------- 전사 기준
    company = []
    for sid, gid in COMPANY_GUIDES.items():
        s = st.get(sid) or {}
        carry = s.get("carry") or {}
        # 서식 필요 이슈(결손금 소급공제 · 주식 양도 등)는 따로 한 줄씩 둔다. 단계 줄에 섞으면 엉뚱한 요청이 붙는다(10-20)
        linked = [i for i in issues if gid in (i.get("guide") or []) and not is_credit_issue(i) and i["kind"] != "서식 필요"
                  and not any(_group_no(g) for g in i.get("guide") or [])]
        used_issue.update(i["no"] for i in linked)
        if sid == "P1":
            j, text = "확인", f"{carry.get('class')} · {carry.get('small')} · {carry.get('industry')}"
            uids = ["sme"]
        elif sid == "P2":
            j = "판단 필요" if "미확인" in (carry.get("stock_change"), carry.get("rental_main")) or carry.get("stock_change") == "있음" else "확인"
            text = f"주식변동 {carry.get('stock_change')} · 54호 {carry.get('stock_form')} · 임대업 주업 {carry.get('rental_main')}"
            uids = []
        elif sid == "P3":
            fc = carry.get("forecast") or []
            counts = {}
            for f in fc:
                counts[f.get("outlook")] = counts.get(f.get("outlook"), 0) + 1
            j = "판단 필요" if any(f.get("outlook") in ("다시 생길 듯", "추인될 듯", "미확인") for f in fc) else ("확인" if fc else "해당 없음")
            text = " · ".join(f"{k} {v}건" for k, v in counts.items()) or "전기 조정 · 유보 없음"
            uids = [f"issue:{n}" for f in fc for n in f.get("issues") or []]
        elif sid == "F1":
            acc = carry.get("accounts") or []
            j = "판단 필요" if acc else "확인"
            text = f"볼 계정 {len(acc)}개(엔진 이슈 {sum(1 for a in acc if a.get('issues'))} · AI 추가 {sum(1 for a in acc if not a.get('issues'))})"
            uids = []
        else:
            j = "확인" if carry.get("status") == "확정" and carry.get("compare_p1") == "같음" else "판단 필요"
            text = f"{carry.get('verdict')} · {carry.get('status')} · 전기와 {carry.get('compare_p1')}"
            uids = ["sme"]
        j = _worst(j, *[memo_j(i) for i in linked])
        asks = list(s.get("ask") or []) + [a for i in linked for a in issue_asks(i)]
        title = re.sub(r"^\(\d\)\s*", "", (guide.get(gid) or {}).get("title") or s.get("title") or sid)
        company.append(row(sid, f"{s.get('step')} {s.get('title')}", _first(s.get("finding") or ""), j, text, asks,
                           uids + [f"issue:{i['no']}" for i in linked], guide_ids=[gid], state=title))
    # 전사 성격 이슈(가이드 1-x · 2-1 · 2-2 에만 걸리고 위에서 안 받은 것)
    for i in issues:
        gs = i.get("guide") or []
        if i["no"] in used_issue or is_credit_issue(i) or any(_group_no(g) for g in gs):
            continue
        used_issue.add(i["no"])
        a = i.get("amounts") or {}
        company.append(row(f"issue:{i['no']}", i["title"], _first((i.get("basis") or [""])[0]), memo_j(i),
                           _first((i.get("memo") or {}).get("why") or ""), issue_asks(i), [f"issue:{i['no']}"],
                           amount=a.get("current"), guide_ids=gs))

    # ---------------- 계정별
    by_group: dict[int | str, dict] = {}
    for n, adj in enumerate(adjustments):
        p = papers.get(adj.get("paper")) or {}
        if adj.get("paper") == "credits":
            continue
        grp = None
        for no in p.get("issues") or []:
            i = next((x for x in issues if x["no"] == no), None)
            grp = next((_group_no(g) for g in (i or {}).get("guide") or [] if _group_no(g)), None)
            if grp:
                break
        grp = grp or PAPER_GROUP.get(adj.get("paper"), "기타")
        by_group.setdefault(grp, {"adj": [], "issues": []})["adj"].append((n, adj))
    for i in issues:
        if i["no"] in used_issue or is_credit_issue(i):
            continue
        grp = next((_group_no(g) for g in i.get("guide") or [] if _group_no(g)), None) or "기타"
        by_group.setdefault(grp, {"adj": [], "issues": []})["issues"].append(i)
        used_issue.add(i["no"])
    accounts = []
    titles = {}
    for gid, g in guide.items():
        n = _group_no(gid)
        if n:
            titles.setdefault(n, []).append(g)
    for n in sorted(titles):
        if n in CREDIT_ACCOUNTS:
            continue
        lines = titles[n]
        b = by_group.get(n, {"adj": [], "issues": []})
        statuses = [g.get("status") for g in lines]
        facts = [f for g in lines for f in g.get("facts") or []]
        adj_amt = sum(int(a.get("amount") or 0) * (1 if a.get("side") == "가산" else -1) for _, a in b["adj"])
        if b["adj"]:
            j = "조정 필요"
            text = " · ".join(f"{a.get('kind') or a.get('subject')} {won_of(a.get('amount'))} {a.get('side')} · {a.get('disposition')}" for _, a in b["adj"])
        elif b["issues"]:
            j = _worst(*[memo_j(i) for i in b["issues"]])
            text = _first((b["issues"][0].get("memo") or {}).get("why") or b["issues"][0]["title"])
        else:
            j = _worst(*[STATUS_JUDGE.get(s) for s in statuses])
            if j == "판단 필요":
                j = "확인"
            text = _first(facts[0]) if facts else ""
        if b["issues"]:
            a = b["issues"][0].get("amounts") or {}
            rel = f"당기 {won_of(a.get('current'))}" + (f" · 전기 {won_of(a.get('prior'))}" if isinstance(a.get("prior"), (int, float)) else "") if isinstance(a.get("current"), (int, float)) else _first((b["issues"][0].get("basis") or [""])[0])
        else:
            rel = _first(facts[0]) if facts else "관련 계정 없음"
        state = "해당" if (b["adj"] or b["issues"] or "이슈" in statuses) else ("자료 필요" if "자료 필요" in statuses else "해당 없음")
        asks = [x for i in b["issues"] for x in issue_asks(i)]
        # 가산과 차감이 함께 있으면(퇴직급여충당금 가산 · 퇴직연금 차감 등) 순액 한 숫자는 오해를 부른다(10-19). 줄마다 판단 글에 있다
        one_side = len({a.get("side") for _, a in b["adj"]}) == 1
        accounts.append(row(f"acct:{n}", lines[0]["title"], rel, j, text, asks,
                            [f"adj:{k}" for k, _ in b["adj"]] + [f"issue:{i['no']}" for i in b["issues"]],
                            amount=adj_amt if b["adj"] and one_side else None, guide_ids=[g["id"] for g in lines], state=state))
    if "기타" in by_group:
        b = by_group["기타"]
        accounts.append(row("acct:other", "그 밖의 계정", "가이드 계정 묶음에 없는 조서 · 이슈",
                            _worst("조정 필요" if b["adj"] else None, *[memo_j(i) for i in b["issues"]]),
                            " · ".join(f"{a.get('kind') or a.get('subject')} {won_of(a.get('amount'))}" for _, a in b["adj"]) or _first(b["issues"][0]["title"] if b["issues"] else ""),
                            [x for i in b["issues"] for x in issue_asks(i)],
                            [f"adj:{k}" for k, _ in b["adj"]] + [f"issue:{i['no']}" for i in b["issues"]], state="해당"))
    for a in added:
        uid = f"added:{a['id']}"
        accounts.append(row(uid, f"AI 추가 · {a.get('account')}", _first(a.get("finding") or ""), a.get("judgment") or "판단 필요",
                            _first(a.get("why") or ""), ([f"답변 필요: {qtitle[uid]}"] if uid in pending else []) + list(a.get("ask") or []),
                            [uid], amount=None, state="해당"))

    # ---------------- 세액공제
    credit_rows = []
    s = st.get("P4") or {}
    fc = (s.get("carry") or {}).get("forecast") or []
    counts = {}
    for f in fc:
        counts[f.get("outlook")] = counts.get(f.get("outlook"), 0) + 1
    p4_issues = [i for i in issues if "1-4" in (i.get("guide") or [])]
    credit_rows.append(row("P4", f"{s.get('step')} {s.get('title')}", _first(s.get("finding") or ""),
                           _worst("판단 필요" if any(f.get("outlook") in ("계속", "사후관리", "미확인") for f in fc) else ("확인" if fc else "해당 없음"),
                                  *[memo_j(i) for i in p4_issues]),
                           " · ".join(f"{k} {v}건" for k, v in counts.items()) or "전기 공제 · 감면 없음",
                           list(s.get("ask") or []), [f"issue:{n}" for f in fc for n in f.get("issues") or []] + [f"issue:{i['no']}" for i in p4_issues],
                           guide_ids=["1-4"]))
    credit_issue_nos = set()
    for k, x in enumerate((credits or {}).get("items") or [], 1):
        uid = f"credit:{k}"
        credit_issue_nos.update(x.get("issues") or [])
        j = {"적용 가능": "판단 필요", "진행 중": "판단 필요", "적용 불가": "해당 없음"}.get(x.get("state"), "판단 필요")
        cands = x.get("candidates") or []
        # 후보 전표 금액은 공제 · 감면액이 아니다. 판단 칸 금액으로 두지 않고 글로만 적는다(10-19). 회계사가 판단할 점(judge)은
        # 회사에 받을 자료가 아니라 추가 요청 칸에 넣지 않는다
        total = sum(abs(int(c.get("amount") or 0)) for c in cands)
        text = f"{x.get('state')}" + (f" · 취지에 맞는 후보 전표 {len(cands)}건(전표 금액 합계 {won_of(total)}, 공제 · 감면액이 아님)" if cands else "")
        if x.get("judge"):
            text += ". 판단할 점: " + " / ".join(x.get("judge"))
        credit_rows.append(row(uid, x.get("name"), _first(x.get("purpose") or ""), j, text,
                               ([f"답변 필요: {qtitle[uid]}"] if uid in pending else []) + list(x.get("ask") or []),
                               [uid] + [f"issue:{n}" for n in x.get("issues") or []], amount=None, state="해당" if j != "해당 없음" else "해당 없음"))
    for i in issues:
        if not is_credit_issue(i) or i["no"] in credit_issue_nos:
            continue
        a = i.get("amounts") or {}
        credit_rows.append(row(f"issue:{i['no']}", i["title"], _first((i.get("basis") or [""])[0]), memo_j(i),
                               _first((i.get("memo") or {}).get("why") or ""), issue_asks(i), [f"issue:{i['no']}"],
                               amount=a.get("current"), guide_ids=i.get("guide") or [], state="해당"))
    linked_groups = {_group_no(g) for i in issues if is_credit_issue(i) for g in i.get("guide") or []}
    items = list(enumerate((credits or {}).get("items") or [], 1))
    for n in sorted(CREDIT_ACCOUNTS):
        if n not in titles:
            continue
        lines = titles[n]
        same = [(k, x) for k, x in items if re.search(CREDIT_NAME[n], str(x.get("name") or ""))]
        if n in linked_groups or same:
            facts = [f for g in lines for f in g.get("facts") or []]
            where = f"공제 제안 「{same[0][1].get('name')}」" if same else "공제감면 이슈"
            credit_rows.append(row(f"acct:{n}", lines[0]["title"], _first(facts[0]) if facts else "관련 계정 있음", "확인",
                                   f"{where}에서 봅니다", [], [f"credit:{k}" for k, _ in same], guide_ids=[g["id"] for g in lines], state="해당"))
            continue
        facts = [f for g in lines for f in g.get("facts") or []]
        st_ = [g.get("status") for g in lines]
        j = "판단 필요" if "이슈" in st_ else ("자료 필요" if "자료 필요" in st_ else "해당 없음")
        text = {"판단 필요": "엔진 단서가 있습니다. 공제 대상 투자 · 인원 증가인지 확인합니다",
                "자료 필요": "장부만으로 알 수 없어 자료를 받아야 합니다", "해당 없음": "엔진이 공제 단서를 찾지 못했습니다"}[j]
        credit_rows.append(row(f"acct:{n}", lines[0]["title"], _first(facts[0]) if facts else "관련 계정 없음", j, text, [], [],
                               guide_ids=[g["id"] for g in lines], state={"판단 필요": "해당"}.get(j, j)))

    ISSUE = ("조정 필요", "판단 필요", "자료 필요")
    for rows_ in (company, accounts, credit_rows):
        for r in rows_:
            r["issue"] = r["judgment"] in ISSUE
    groups = []
    for key, label, rows_, desc in (("company", "전사 기준", company, "회사 종류 · 주식 변동 · 전기 조정 예측 · 재무제표 훑기 · 당기 중소기업"),
                                    ("accounts", "재무제표 계정별", accounts, "가이드 계정 묶음마다 관련 계정 · 조서 조정 · AI 추가 이슈"),
                                    ("credits", "세액공제", credit_rows, "전기 공제 · 감면, 공제 계정, 공제 제안")):
        attention = sum(1 for r in rows_ if r["judgment"] in ("조정 필요", "판단 필요"))
        groups.append({"key": key, "label": label, "desc": desc, "rows": rows_, "total": len(rows_),
                       "adjust": sum(1 for r in rows_ if r["judgment"] == "조정 필요"),
                       "attention": attention, "pending": sum(r["pending"] for r in rows_),
                       "asks": sum(len(r["asks"]) for r in rows_),
                       "na": sum(1 for r in rows_ if r["judgment"] in ("해당 없음", "조정 없음")),
                       "issues": sum(1 for r in rows_ if r["issue"])})
    gl = ar.get("guide", [])
    coverage = {"guide_lines": len(gl), "issue": sum(1 for g in gl if g.get("status") == "이슈"),
                "na": sum(1 for g in gl if g.get("status") == "해당 없음"), "need": sum(1 for g in gl if g.get("status") == "자료 필요"),
                "account_groups": len(titles), "issues": len(issues), "added": len(added),
                "credits": len((credits or {}).get("items") or []), "adjustments": len(adjustments)}
    if ledger is not None:
        coverage["accounts"] = account_coverage(ledger, ar, steps)
    coverage["forms"] = form_coverage(ar)
    return {"groups": groups, "coverage": coverage}
