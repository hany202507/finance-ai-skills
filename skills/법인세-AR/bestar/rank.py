# -*- coding: utf-8 -*-
"""세 묶음 요약: 가장 중요한 3가지 · 확인사항 · 확인하면 좋은 세부사항 (설계 4절).

v0.3 은 가이드 줄 순서만 보았다. 그래서 기업 구분 · 법인세비용 손금불산입 · 전기 첫 조정이 늘 셋을 차지했다.
여기서는 점수(위험도 상2 · 중1 · 하0 + 판단 조정 필요2 · 판단 필요1) 높은 순, 같으면 조정 필요 먼저, 그다음 크기 · 가이드 순서.
상시 항목은 셋에서 빼고, 같은 사안(same_as)은 셋에 한 번만.
10-19 나참유통 실행: 전기 신고서 결손금 표에 빠진 해가 있어 이월결손금 공제가 달라지는(세액이 0 이 되는) 이슈가 위험 중 · 판단 필요라
확인사항에 머물렀다. 그래서 과세표준 · 세액을 바꾸는 이슈(TAX_RULES 규칙, 또는 메모 tax_effect)에 점수 TAX_POINT 를 더한다.
TAX_RULES 규칙은 당기 각사업연도소득금액(조서)이 0 보다 클 때만 더한다. 당기가 결손이면 이월결손금 이력은 당기 세액을 바꾸지 않는다
(거찬식품: 전기 경정청구 쪽 문제라 확인사항이면 된다).
10-16 두 회사 실행: 판단을 먼저 두면 판단 필요 · 위험 상인 큰 쟁점(사택 임차료)이 밀렸고, 위험도를 먼저 두면 실제로 조정된
기업업무추진비 · 업무용승용차가 AI 의 의심 쟁점에 밀렸다. 점수를 더하는 방식이 두 회사 정답 조정 항목을 가장 많이 셋에 올렸다.
"""
from __future__ import annotations

import re

TOP = 3
TIERS = ("top", "check", "detail")
TIER_NAME = {"top": "가장 중요한 3가지", "check": "확인사항", "detail": "확인하면 좋은 세부사항"}
JUDGE_RANK = {"조정 필요": 0, "판단 필요": 1, None: 2, "조정 없음": 3}
RISK_RANK = {"상": 0, "중": 1, "하": 2, None: 1}
# 해마다 기계적으로 생기거나 서식만 쓰면 되는 규칙. 셋에 넣지 않는다.
ROUTINE = ("corp_tax", "prior:corp_tax", "withholding", "expense_evidence", "cogs")
ACTION_KINDS = ("신고 점검", "조정 후보", "전기 연속", "공제감면")
CERT_RISK = {"확실": "중", "가능": "중", "자료 필요": "하"}
CREDIT_JUDGE = {"적용 가능": "판단 필요", "진행 중": "판단 필요", "적용 불가": "조정 없음"}


RISK_POINT = {"상": 2, "중": 1, "하": 0}
# 과세표준 · 세액을 바로 바꾸는 엔진 규칙(전기 결손금 이력). 메모에 tax_effect: true 를 단 이슈도 같이 본다
TAX_RULES = ("prior_loss_row", "loss_history")
TAX_POINT = 2
# 엔진 규칙이 달라도 같은 사안인 것. 셋에 한 번만 나온다(10-20 블라인드 실행: 소기업 여부와 중소기업 감면이 셋 가운데 둘을 차지해
# 결손금 · 인정이자가 밀렸다). 「sme」 는 2-(2) 기업 구분 줄이다
SAME_GROUPS = {"sme_small": "sme", "sme_size": "sme", "sme_reduction": "sme"}
JUDGE_POINT = {"조정 필요": 2, "판단 필요": 1, None: 1, "조정 없음": 0}


def score(u: dict) -> int:
    """위험도 점수 + 판단 점수(+ 세액 영향). 조정 필요 · 위험 중(3)과 판단 필요 · 위험 상(3)이 같고, 같으면 조정 필요가 먼저다."""
    return RISK_POINT.get(u.get("risk"), 1) + JUDGE_POINT.get(u.get("judgment"), 1) + (TAX_POINT if u.get("tax_effect") else 0)


def same_list(v) -> list:
    """same_as 를 이슈 번호 목록으로(예전 꼴은 숫자 하나)."""
    if v is None:
        return []
    return [x for x in (v if isinstance(v, list) else [v]) if x is not None]


def _rule_base(rule: str) -> str:
    parts = (rule or "").split(":")
    return ":".join(parts[:2]) if parts[0] in ("check", "prior", "credit") and len(parts) > 1 else parts[0]


def routine(issue: dict) -> bool:
    base = _rule_base(issue.get("rule", ""))
    return base in ROUTINE or base.split(":")[0] == "prior" and base.endswith("corp_tax")


def first_sentence(text: str) -> str:
    text = (text or "").strip()
    m = re.match(r"(.+?[다요음함])\.(\s|$)", text)
    return (m.group(1) + ".") if m else text[:120]


TITLE_MAX = 60


def added_title(a: dict) -> str:
    """AI 추가 이슈 제목. F1 항목의 title 이 있으면 그것, 없으면 why 첫 문장(60자까지)."""
    head = (a.get("title") or "").strip() or first_sentence(a.get("why") or a.get("finding") or "")
    if len(head) > TITLE_MAX:
        head = head[:TITLE_MAX - 1].rstrip() + "…"
    return f"{a.get('account')}: {head}"


def questions_of(issue: dict) -> list[str]:
    """회사에 물을 것. 메모에 questions 칸이 있으면(빈 목록이어도) 그것이 엔진 질문을 대신한다. 조정 없음 이슈는 묻지 않는다."""
    memo = issue.get("memo") or {}
    if memo.get("judgment") == "조정 없음":
        return []
    return list(memo["questions"] if "questions" in memo else issue.get("questions") or [])


def size_of(issue: dict) -> int:
    a = issue.get("amounts") or {}
    vals = [abs(v) for v in (a.get("current"), a.get("prior"), a.get("change")) if isinstance(v, (int, float))]
    return int(max(vals)) if vals else 0


def where_of(answers: list[str], handed: dict[str, tuple[str, str]], fallback: str) -> tuple[str, tuple]:
    """처음 잡힌 자리. 앞 단계 항목을 받았으면 그 단계, 아니면 엔진 가이드 줄."""
    order = {"1-(3)": 2, "1-(4)": 3, "2-(1)": 4}
    hits = sorted((order.get(handed[k][1], 9), k) for k in answers if k in handed)
    if hits:
        k = hits[0][1]
        name, step = handed[k]
        return f"{step} {k} {name}", (hits[0][0], int(re.sub(r"\D", "", k) or 0))
    return fallback, (9, 0)


def build(ar: dict, extras: dict[int, dict], steps: dict[str, dict], added: list[dict], credits: dict,
          guide_order: list[str], taxable: bool | None = None, tax_summary: dict | None = None) -> dict:
    """steps: {P1..F2: 단계 파일}. added: AI 추가 이슈. 결과는 화면 · 엑셀이 같이 쓴다."""
    handed = {}
    for x in steps["P3"]["carry"].get("forecast") or []:
        handed[x["id"]] = (x.get("item") or "", "1-(3)")
    for x in steps["P4"]["carry"].get("forecast") or []:
        handed[x["id"]] = (x.get("name") or "", "1-(4)")
    for x in steps["F1"]["carry"].get("accounts") or []:
        handed[x["id"]] = (x.get("account") or "", "2-(1)")
    gpos = {g: n for n, g in enumerate(guide_order)}
    units = []
    for i in ar.get("issues", []):
        ex = extras.get(i["no"], {})
        memo = i.get("memo") or {}
        judgment = memo.get("judgment")
        risk = ex.get("risk") or CERT_RISK.get(i.get("certainty"))
        guide_first = min((gpos.get(g, 999) for g in i.get("guide") or []), default=999)
        where, wkey = where_of(ex.get("answers") or [], handed, f"엔진 · 가이드 {', '.join(i.get('guide') or []) or '-'}")
        is_routine = routine(i)
        tax_rule = _rule_base(i.get("rule", "")) in TAX_RULES and taxable is not False
        tax_effect = bool(ex.get("tax_effect")) or tax_rule
        if tax_rule and taxable:
            risk = "상"          # 당기 소득이 있으면 결손금 공제액이 그대로 과세표준을 바꾼다(위험 중으로 매기면 셋에서 밀렸다)
        if judgment == "조정 없음" or i.get("folded"):
            tier = "detail"
        elif (i["kind"] in ACTION_KINDS or tax_effect) and not is_routine:
            tier = "candidate"
        else:
            tier = "check"
        units.append({"uid": f"issue:{i['no']}", "type": "issue", "ref": i["no"], "title": i["title"], "kind": i["kind"],
                      "certainty": i.get("certainty"), "judgment": judgment, "risk": risk, "size": size_of(i),
                      "where": where, "line": first_sentence(memo.get("why") or ""), "asks": questions_of(i),
                      "routine": is_routine, "tier": tier, "same_as": same_list(ex.get("same_as")), "tax_effect": tax_effect, "facts": ex.get("facts") or [],
                      "group": SAME_GROUPS.get(_rule_base(i.get("rule", ""))), "accounts": [str(a) for a in i.get("accounts") or []],
                      "stake": ex.get("stake"), "papers": list(i.get("papers") or []),
                      "_order": (wkey, guide_first, i["no"])})
    for a in added:
        units.append({"uid": f"added:{a['id']}", "type": "added", "ref": a["id"], "title": added_title(a),
                      "kind": "AI 추가", "certainty": None, "judgment": a.get("judgment") or "판단 필요", "risk": a.get("risk"),
                      "size": int(a.get("current") or 0), "where": f"2-(1) {a['id']} {a.get('account')}", "line": first_sentence(a.get("finding") or ""),
                      "asks": list(a.get("ask") or []), "routine": False, "tax_effect": bool(a.get("tax_effect")), "facts": a.get("facts") or [],
                      "stake": a.get("stake"),
                      "same_as": [],
                      "tier": "detail" if a.get("judgment") == "조정 없음" else "candidate", "_order": ((4, 0), 999, 0)})
    for n, c in enumerate((credits or {}).get("items") or []):
        judgment = CREDIT_JUDGE.get(c.get("state"), "판단 필요")
        where, wkey = where_of(c.get("answers") or [], handed, "공제 · 감면 제안")
        size = max([abs(int(x.get("amount") or 0)) for x in c.get("candidates") or []] or [0])
        units.append({"uid": f"credit:{n + 1}", "type": "credit", "ref": n + 1, "title": f"{c.get('name')} ({c.get('state')})", "kind": "공제감면",
                      "certainty": None, "judgment": judgment, "risk": "중" if c.get("state") == "적용 가능" else "하", "size": size,
                      "where": where, "line": first_sentence(c.get("purpose") or ""), "asks": list(c.get("ask") or []),
                      "routine": False, "tier": "detail" if c.get("state") == "적용 불가" else ("candidate" if c.get("state") == "적용 가능" else "check"),
                      "_order": (wkey, 998, n)})
    f2 = steps["F2"]["carry"]
    if f2.get("status") != "확정" or f2.get("compare_p1") != "같음":
        left = [t for t in f2.get("tests") or [] if t.get("result") in ("미확인", "미충족")]
        only_indep = bool(left) and all(t.get("name") == "독립성" and t.get("result") == "미확인" for t in left) \
            and f2.get("compare_p1") != "달라짐"
        units.append({"uid": "sme", "type": "sme", "ref": "F2", "title": f"기업 구분: {f2.get('verdict')}", "kind": "기업 구분",
                      "certainty": None, "judgment": "판단 필요", "risk": "하" if only_indep else "상", "size": 0,
                      "where": "2-(2) 당기 중소기업 여부", "line": f2.get("point") or "", "asks": list(f2.get("ask") or []),
                      "routine": False, "tier": "check" if only_indep else "candidate", "group": "sme", "_order": ((0, 0), 0, 0)})

    from bestar import stake as stake_mod
    for u in units:
        st = u.get("stake")
        u["stake_amount"] = abs(int(st["amount"])) if st else 0
        u["tax_delta"] = stake_mod.tax_delta(tax_summary or {}, st) if st else None
    cands = [u for u in units if u["tier"] == "candidate"]
    # 같은 점수면 판단에 걸린 금액(stake)이 큰 것 → 조정 필요 → 크기 순(10-20 회계사 검토: 7백만원 조정이 1.5억원 쟁점 위에 있었다)
    cands.sort(key=lambda u: (-score(u), -u.get("stake_amount", 0), JUDGE_RANK.get(u["judgment"], 2), -u["size"], u["_order"]))
    top = []
    for u in cands:
        # 같은 사안: 메모 same_as, 규칙 묶음(SAME_GROUPS), 같은 계정을 보는 이슈(10-20 회계사 검토: 가지급금 한 묶음이 셋을 나눠 가짐)
        dup = any(t["type"] == "issue" and u["type"] == "issue" and (t["ref"] in (u.get("same_as") or []) or u["ref"] in (t.get("same_as") or []))
                  or u.get("group") and u.get("group") == t.get("group")
                  or set(u.get("accounts") or []) & set(t.get("accounts") or []) for t in top)
        if len(top) < TOP and not dup:
            u["tier"] = "top"
            top.append(u)
        else:
            u["tier"] = "check"
    rest = [u for u in units if u["tier"] == "check" and u not in top]
    rest.sort(key=lambda u: (u["routine"], JUDGE_RANK.get(u["judgment"], 2), RISK_RANK.get(u["risk"], 1), u["_order"], -u["size"]))
    detail = sorted([u for u in units if u["tier"] == "detail"], key=lambda u: u["_order"])
    first_asks = []
    for u in top:
        for q in u["asks"]:
            if q not in first_asks and len(first_asks) < 5:
                first_asks.append(q)
    for u in units:
        u.pop("_order", None)
    return {"top": top, "check": rest, "detail": detail, "first_asks": first_asks}
