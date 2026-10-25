# -*- coding: utf-8 -*-
"""최종 세무조정계산서와 AR 대조. AR 은 어디를 볼지 짚는 단계라 신고서 항목마다 짚었는지를 본다.

  ar.py compare <신고건> [<최종 신고서.pdf>]      PDF 를 주지 않으면 <신고건>/최종 신고본/*.pdf

1. 신고서 항목(15호 줄, 3호 기부금 한도초과 · 이월결손금, 공제감면 적용 · 이월)마다 AR 이 잡았는지
   잡은 곳: 조서 조정(같은 방향 · 금액이나 같은 묶음) → 그 조서의 이슈, 이슈 제목 · 계정의 묶음 · 낱말, AI 추가 이슈, 공제 제안
   결과: 잡음(조정 필요 · 판단 필요) · 조정 없음으로 봄 · 못 잡음. 가장 중요한 3가지에 들었는지도 적는다
2. AR 만 짚은 것: 조정 필요 · 판단 필요인데 신고서 항목과 이어지지 않은 이슈 · AI 추가 이슈 · 공제 제안.
   AR 이 과하게 봤을 수도, 신고본이 놓쳤을 수도 있어 회계사 판단 목록으로 낸다(오답으로 세지 않는다)
3. 조서 금액(참고): 엔진 채점(score/match.py)으로 15호 · 3호 · 50호(을)를 견준다

결과: _색인/AR_대조.json, 1 AR/AR_대조.md. 신고서 읽기는 _색인/최종.json 에 둔다(같은 PDF 면 다시 읽지 않는다).
"""
from __future__ import annotations

import argparse
import hashlib
import re
from datetime import datetime
from pathlib import Path

from ctax.score import match

from bestar import finish, paths

FOLDER = "최종 신고본"
CACHE = "최종.json"
OUT_JSON = "AR_대조.json"
OUT_MD = "1 AR/AR_대조.md"
CAUGHT = ("조정 필요", "판단 필요")
CHECK_STATES = ("같음", "금액 다름", "처분 다름", "방향 반대", "조서 금액 없음")
# 과목 낱말로 잇지 않는 말(어느 이슈에나 들어갈 수 있다)
STOP = {"손금불산입", "손금산입", "익금산입", "익금불산입", "한도초과", "한도초과액", "부인", "기타", "비용", "당기", "전기",
        "금액", "계정", "세무조정", "조정", "처분", "유보", "상여", "사외유출", "기타사외유출"}
CREDIT_STOP = ("최저한세적용제외", "최저한세적용대상", "세액공제", "세액감면", "공제", "감면", "에대한", "일반", "기업", "의")


def _i(v) -> int:
    try:
        return int(round(float(v or 0)))
    except (TypeError, ValueError):
        return 0


# 엔진 묶음(score/match.TOPICS)에 없는 것. 신고서 과목은 붙여 쓴 말이 많다(「보험료기간미경과액」)
MORE_TOPICS = (("선급비용", ("보험료", "선급", "미경과")), ("재고자산", ("재고", "감모", "평가손실")),
               ("인정이자", ("인정이자", "가지급금")), ("외화환산", ("외화", "환산")), ("전기오류", ("전기오류", "오류수정")))


def topic(text: str) -> str:
    t = match.topic(text)
    if t:
        return t
    s = re.sub(r"\s+", "", text or "")
    return next((name for name, keys in MORE_TOPICS if any(k in s for k in keys)), "")


def words(text: str) -> set[str]:
    """세 글자 이상 낱말(괄호 안 · 흔한 세무 말 뺌)."""
    out = set()
    for w in re.findall(r"[가-힣A-Za-z]{3,}", re.sub(r"\(.*?\)", " ", text or "")):
        if w not in STOP:
            out.add(w)
    return out


def related(subject: str, text: str) -> bool:
    """신고서 과목과 AR 글이 낱말을 나눠 갖는지. 붙여 쓴 과목은 AR 낱말이 그 안에 들어 있는지로 본다."""
    a = re.sub(r"\s+", "", re.sub(r"\(.*?\)", "", subject or ""))
    ws = words(text)
    return bool(words(subject) & ws) or any(w in a for w in ws) or any(w in re.sub(r"\s+", "", text) for w in words(subject))


def credit_core(name: str) -> str:
    s = re.sub(r"[\s·ㆍ()\[\]0-9]", "", name or "")
    for w in CREDIT_STOP:
        s = s.replace(w, "")
    return s


def same_credit(a: str, b: str) -> bool:
    x, y = credit_core(a), credit_core(b)
    return bool(x and y) and (x[:4] in y or y[:4] in x)


# ---------------------------------------------------------------- 신고서 읽기
def pick_pdf(c, given: str | None) -> Path | None:
    if given:
        p = Path(given)
        return p if p.exists() else None
    d = c.root / FOLDER
    pdfs = sorted(d.glob("*.pdf")) if d.exists() else []
    return pdfs[0] if pdfs else None


def read_answer(c, pdf: Path) -> dict:
    sha = hashlib.sha1(pdf.read_bytes()).hexdigest()
    cache = paths.read_json(paths.index(c) / CACHE)
    if cache and cache.get("sha") == sha:
        return cache["data"]
    from ctax.prior.read import read_prior
    data = read_prior(pdf)
    paths.write_json(paths.index(c) / CACHE, {"pdf": pdf.name, "sha": sha, "at": datetime.now().isoformat(timespec="seconds"),
                                              "data": data})
    return data


def answer_points(ans: dict) -> list[dict]:
    pts = []
    for n, a in enumerate(ans.get("adjustments") or []):
        pts.append({"id": f"15:{n}", "area": "15호", "title": f"{a['side']} {a['subject']}", "side": a["side"],
                    "subject": a["subject"], "amount": _i(a.get("amount")), "disposition": a.get("disposition") or "",
                    "note": a.get("note") or "", "topic": topic(f"{a['subject']} {a.get('note') or ''}")})
    c3 = (ans.get("cells") or {}).get("3") or {}
    if _i(c3.get("05")) > 0:
        pts.append({"id": "3:05", "area": "3호", "title": "기부금 한도초과", "amount": _i(c3["05"]), "topic": "기부금", "subject": "기부금"})
    if _i(c3.get("07")) > 0:
        pts.append({"id": "3:07", "area": "3호", "title": "이월결손금 공제", "amount": _i(c3["07"]), "topic": "결손금", "subject": "결손금"})
    for n, x in enumerate(ans.get("credits") or []):
        if _i(x.get("amount")) > 0:
            pts.append({"id": f"cr:{n}", "area": "공제감면", "title": f"{x.get('name')} 적용", "amount": _i(x["amount"]),
                        "credit": x.get("name"), "subject": x.get("name")})
        if _i(x.get("carryforward")) > 0:
            pts.append({"id": f"cf:{n}", "area": "공제 이월", "title": f"{x.get('name')} 이월", "amount": _i(x["carryforward"]),
                        "credit": x.get("name"), "subject": x.get("name")})
    return pts


# ---------------------------------------------------------------- AR 쪽
def ar_units(c) -> tuple[list[dict], dict]:
    """대조에 쓸 AR 항목 [{uid, title, text, judgment, papers, kind}] 과 세 묶음 요약."""
    base = finish.collect(c)
    ar = base["ar"]
    names = base["account_names"]
    summ = base["summary"]
    tiers = {u["uid"]: u for t in ("top", "check", "detail") for u in summ[t]}
    out = []
    for i in ar.get("issues", []):
        acc = " ".join(str(names.get(a, a)) for a in i.get("accounts") or [])
        out.append({"uid": f"issue:{i['no']}", "no": i["no"], "title": i["title"], "kind": i["kind"], "rule": i.get("rule") or "",
                    "text": f"{i['title']} {acc}", "judgment": (i.get("memo") or {}).get("judgment") or "메모 없음",
                    "papers": list(i.get("papers") or []), "tier": (tiers.get(f"issue:{i['no']}") or {}).get("tier")})
    for a in base["added"]:
        out.append({"uid": f"added:{a['id']}", "title": f"{a.get('account')} (AI 추가)", "kind": "AI 추가 이슈", "rule": "",
                    "text": str(a.get("account") or ""), "judgment": a.get("judgment") or "판단 필요",
                    "papers": [], "tier": (tiers.get(f"added:{a['id']}") or {}).get("tier")})
    for n, x in enumerate(base["credits"].get("items") or [], 1):
        out.append({"uid": f"credit:{n}", "title": f"{x.get('name')} (공제 제안)", "kind": "공제 제안", "rule": "",
                    "text": x.get("name") or "", "credit": x.get("name"),
                    "judgment": "조정 없음" if x.get("state") == "적용 불가" else "판단 필요", "papers": [],
                    "tier": (tiers.get(f"credit:{n}") or {}).get("tier")})
    return out, summ


def our_adjustments(adj: dict) -> list[dict]:
    rows = []
    for a in (adj.get("adjustments") or []) + (adj.get("direct") or []):
        rows.append({**a, "amount": _i(a.get("amount")), "topic": topic(f"{a.get('subject') or ''} {a.get('note') or ''} {a.get('kind') or ''}")})
    return rows


def paper_lines(p: dict, ours: list[dict]) -> tuple[list[dict], str]:
    """15호 항목과 이어지는 조서 조정 줄과 관계(빈 글이면 같은 방향, 「방향 반대」).

    같은 방향 · 같은 금액 한 줄 → 같은 방향 · 같은 묶음 여러 줄(합) → 같은 방향 · 과목 낱말 → 같은 묶음의 반대 방향 줄.
    """
    if p["area"] != "15호":
        return [], ""
    side, tp = p["side"], p.get("topic")
    exact = [o for o in ours if o.get("side") == side and o["amount"] == p["amount"]
             and not (tp and o["topic"] and o["topic"] != tp)]          # 금액이 같아도 묶음이 다르면 다른 줄
    if exact:
        return exact[:1], ""
    same = [o for o in ours if o.get("side") == side and tp and o["topic"] == tp]
    if same:
        return same, ""
    rel = [o for o in ours if o.get("side") == side
           and related(p.get("subject", ""), f"{o.get('subject') or ''} {o.get('kind') or ''}")]
    if rel:
        return rel, ""
    opp = [o for o in ours if o.get("side") != side and tp and o["topic"] == tp]
    return (opp, "방향 반대") if opp else ([], "")


def catchers(p: dict, units: list[dict], ours: list[dict], papers: dict) -> tuple[list[dict], list[dict]]:
    """신고서 항목 하나를 잡은 AR 항목들과 짝지은 조서 조정 줄."""
    hit = []
    via, _rel = paper_lines(p, ours)
    for o in via:
        nos = set((papers.get(o.get("paper")) or {}).get("issues") or [])
        hit += [u for u in units if u.get("no") in nos or o.get("paper") in u["papers"]]
    if p["area"] in ("15호", "3호"):
        tp = p.get("topic")
        for u in units:
            if u in hit or u["kind"] == "공제 제안":
                continue
            if tp and (topic(u["text"]) == tp or tp in u["text"]) or related(p.get("subject", ""), u["text"]):
                hit.append(u)
        if p["id"] == "3:07":
            hit += [u for u in units if u not in hit and ("loss" in u["rule"] or "결손금" in u["title"])]
    if p.get("credit"):
        hit += [u for u in units if same_credit(p["credit"], u.get("credit") or "")
                or u["kind"] in ("공제감면", "전기 연속") and credit_core(p["credit"])[:4] in credit_core(u["title"])]
    seen, out = set(), []
    for u in hit:
        if u["uid"] not in seen:
            seen.add(u["uid"])
            out.append(u)
    if any(u["judgment"] in CAUGHT for u in out):        # 짚은 것이 있으면 「조정 없음」 으로 스친 이슈는 뺀다
        out = [u for u in out if u["judgment"] in CAUGHT]
    return out, via


def verdict(hit: list[dict], via) -> str:
    if via or any(u["judgment"] in CAUGHT for u in hit):
        return "잡음"
    if hit:
        return "조정 없음으로 봄"
    return "못 잡음"


def credit_items(adj: dict) -> list[dict]:
    p = next((p for p in adj.get("papers") or [] if p.get("id") == "credits"), {}) or {}
    return list((p.get("values") or {}).get("items") or [])


def paper_check(p: dict, ours: list[dict], adj: dict) -> dict:
    """조서 계산이 신고서 항목을 어떻게 냈나: {state, side, amount, diff, disposition, lines}.

    state: 같음 · 금액 다름 · 처분 다름 · 방향 반대 · 조서 금액 없음
    """
    s = adj.get("summary") or {}
    if p["area"] == "15호":
        lines, rel = paper_lines(p, ours)
        if not lines:
            return {"state": "조서 금액 없음"}
        amt = sum(o["amount"] for o in lines)
        disp = sorted({o.get("disposition") or "" for o in lines})
        out = {"side": lines[0].get("side"), "amount": amt, "diff": amt - p["amount"], "disposition": " · ".join(disp),
               "lines": [f"{o.get('side')} {o.get('subject')} {o['amount']:,} {o.get('disposition') or ''}".strip() for o in lines]}
        if rel:
            out["state"] = "방향 반대"
        elif amt != p["amount"]:
            out["state"] = "금액 다름"
        elif disp != [p.get("disposition") or ""]:
            out["state"] = "처분 다름"
        else:
            out["state"] = "같음"
        return out
    if p["id"] in ("3:05", "3:07"):
        amt = _i(s.get("donation_excess" if p["id"] == "3:05" else "loss_used"))
        if not amt:
            return {"state": "조서 금액 없음", "amount": 0, "diff": -p["amount"]}
        return {"state": "같음" if amt == p["amount"] else "금액 다름", "amount": amt, "diff": amt - p["amount"]}
    if p.get("credit"):
        key = "used" if p["area"] == "공제감면" else "carry_out"
        its = [x for x in credit_items(adj) if same_credit(p["credit"], x.get("name") or "") and _i(x.get(key))]
        if not its:
            return {"state": "조서 금액 없음", "amount": 0, "diff": -p["amount"]}
        amt = sum(_i(x.get(key)) for x in its)
        return {"state": "같음" if amt == p["amount"] else "금액 다름", "amount": amt, "diff": amt - p["amount"],
                "lines": [f"{x.get('name')} {x.get('year')} {_i(x.get(key)):,}" for x in its]}
    return {"state": "조서 금액 없음"}


# ---------------------------------------------------------------- 만들기
def build(c, pdf: Path, ans: dict | None = None) -> dict:
    """ans 를 주면 PDF 를 읽지 않는다(시험용)."""
    ans = ans if ans is not None else read_answer(c, pdf)
    adj = paths.read_json(paths.index(c) / "조정.json", {}) or {}
    papers = {p["id"]: p for p in adj.get("papers") or []}
    units, summ = ar_units(c)
    ours = our_adjustments(adj)
    top = {u["uid"] for u in summ["top"]} | {f"issue:{n}" for u in summ["top"] for n in u.get("same_as") or []}

    items, used = [], set()
    for p in answer_points(ans):
        hit, via = catchers(p, units, ours, papers)
        used.update(u["uid"] for u in hit)
        v = verdict(hit, via)
        judg = [u["judgment"] for u in hit]
        items.append({**{k: p.get(k) for k in ("id", "area", "title", "amount", "disposition")}, "side": p.get("side"),
                      "result": v, "top": any(u["uid"] in top for u in hit),
                      "ar_judgment": next((j for j in ("조정 필요", "판단 필요", "조정 없음") if j in judg), ""),
                      "caught_by": [{"uid": u["uid"], "title": u["title"], "judgment": u["judgment"]} for u in hit],
                      "check": paper_check(p, ours, adj)})

    only = [{"uid": u["uid"], "title": u["title"], "judgment": u["judgment"], "kind": u["kind"], "tier": u["tier"]}
            for u in units if u["uid"] not in used and u["judgment"] in CAUGHT]
    routine = {u["uid"] for t in ("check", "detail") for u in summ[t] if u.get("routine")}
    only = sorted((x for x in only if x["uid"] not in routine), key=lambda x: (x["judgment"] != "조정 필요", x["tier"] != "top"))

    rows15, s15 = match.score_adjustments(ans.get("adjustments") or [], (adj.get("adjustments") or []) + (adj.get("direct") or []))
    ours3, src3 = match.ours_items_3(None, adj)
    rows3, s3 = match.score_items_3((ans.get("cells") or {}).get("3") or {}, ours3)
    rowsR, sR = match.score_reserves(ans.get("reserves") or [], adj.get("reserves") or [])

    n = len(items)
    count = {k: sum(1 for x in items if x["result"] == k) for k in ("잡음", "조정 없음으로 봄", "못 잡음")}
    checks = {k: sum(1 for x in items if x["check"]["state"] == k) for k in CHECK_STATES}
    return {
        "pdf": pdf.name, "generated_at": datetime.now().isoformat(timespec="seconds"),
        "answer_company": (ans.get("company") or {}).get("name"), "answer_fy": ans.get("fy"),
        "summary": {"points": n, **count, "top": sum(1 for x in items if x["top"] and x["result"] == "잡음"),
                    "recall": round(count["잡음"] / n, 3) if n else None, "ar_only": len(only),
                    "ar_only_adjust": sum(1 for x in only if x["judgment"] == "조정 필요"), "checks": checks,
                    "paper_15": s15, "paper_3": s3, "paper_50": sR},
        "items": items, "ar_only": only,
        "paper": {"15호": rows15, "3호": rows3, "50호(을)": rowsR, "source_3": src3},
        "problems": [p.get("title") if isinstance(p, dict) else str(p) for p in ans.get("problems") or []],
    }


def won(n) -> str:
    return "" if n is None else f"{int(n):,}"


def signed(n) -> str:
    if n is None:
        return ""
    return ("+" if n > 0 else "△" if n < 0 else "") + f"{abs(int(n)):,}"


def check_text(k: dict) -> str:
    if k["state"] == "조서 금액 없음":
        return "금액 없음"
    head = " ".join(x for x in (k.get("side") or "", won(k.get("amount")), k.get("disposition") or "") if x)
    return f"{k['state']} · {head}"


def markdown(d: dict) -> str:
    s = d["summary"]
    L = [f"# AR 대조 · 최종 세무조정계산서", "",
         f"신고서 `{d['pdf']}` 와 이 신고 건의 AR 을 견줬습니다({d['generated_at'][:16].replace('T', ' ')}). "
         "AR 은 볼 곳을 짚는 단계라 신고서 항목마다 AR 이 짚었는지를 봅니다(금액 비교는 3절 참고).", "",
         f"- 신고서 항목 {s['points']}개 가운데 AR 이 잡은 것 {s['잡음']}개"
         + (f"(가장 중요한 3가지에 든 것 {s['top']}개)" if s["top"] else "")
         + f", 조정 없음으로 본 것 {s['조정 없음으로 봄']}개, 못 잡은 것 {s['못 잡음']}개",
         f"- 신고서에 없는데 AR 이 짚은 것 {s['ar_only']}개(조정 필요 {s['ar_only_adjust']} · 판단 필요 {s['ar_only'] - s['ar_only_adjust']}, 회계사 판단)",
         f"- 조서 금액(참고): 15호 일치 {s['paper_15'].get('match', 0)} · 금액 다름 {s['paper_15'].get('amount_diff', 0)}"
         f" · 처분 다름 {s['paper_15'].get('disposition_diff', 0)} · 빠짐 {s['paper_15'].get('missing', 0)}"
         f" · 조서에만 있음 {s['paper_15'].get('extra', 0)}, 3호 {s['paper_3'].get('match', 0)}/{s['paper_3'].get('match', 0) + s['paper_3'].get('diff', 0)} 란 일치", ""]
    L += ["## 1. 신고서 항목을 AR 이 잡았는지", "",
          "「AR 판단」 은 잡은 이슈의 메모 판단, 「조서 계산」 은 엔진 조서가 같은 항목을 낸 방향 · 금액 · 처분, 「차이」 는 조서에서 신고서를 뺀 값입니다.", "",
          "| 신고서 항목 | 신고서 금액 | 결과 | AR 판단 · 잡은 이슈 | 조서 계산 | 차이 | 가장 중요한 3가지 |",
          "|---|---:|---|---|---|---:|---|"]
    for x in d["items"]:
        by = "<br>".join(f"{k['uid']} {k['title']}" for k in x["caught_by"][:3])
        judg = f"{x['ar_judgment']}<br>{by}" if x["ar_judgment"] else (by or "없음")
        title = x["title"] + (f" · {x['disposition']}" if x.get("disposition") else "")
        diff = signed(x["check"].get("diff")) if x["check"]["state"] in ("금액 다름", "방향 반대", "조서 금액 없음") else ""
        L.append(f"| {title} | {won(x['amount'])} | {x['result']} | {judg} | {check_text(x['check'])} | {diff} | {'예' if x['top'] else ''} |")
    k = s["checks"]
    L += ["", f"조서 계산: 같음 {k['같음']} · 금액 다름 {k['금액 다름']} · 처분 다름 {k['처분 다름']} · 방향 반대 {k['방향 반대']}"
              f" · 조서 금액 없음 {k['조서 금액 없음']}."]
    miss = [x for x in d["items"] if x["result"] != "잡음"]
    if miss:
        L += ["", "못 잡았거나 조정 없음으로 본 항목은 엔진 규칙이나 스킬 절차를 고칠 단서입니다:", ""]
        L += [f"- {x['title']} {won(x['amount'])}: {x['result']}" for x in miss]
    off = [x for x in d["items"] if x["result"] == "잡음" and x["check"]["state"] != "같음"]
    if off:
        L += ["", "잡았지만 조서 계산이 신고서와 다른 항목입니다. 노란 칸 입력이 빠졌는지, 엔진 규칙이 다른지 봅니다:", ""]
        L += [f"- {x['title']}: 신고서 {won(x['amount'])}, 조서 {check_text(x['check'])}"
              + (f" (차이 {signed(x['check']['diff'])})" if x["check"].get("diff") else "") for x in off]
    L += ["", "## 2. AR 만 짚은 것", "",
          "신고서에는 조정이 없는데 AR 이 조정 필요 · 판단 필요로 본 항목입니다. AR 이 과하게 봤을 수도, 신고본이 놓쳤을 수도 있어 회계사가 판단합니다.", ""]
    if d["ar_only"]:
        L += ["| AR 항목 | 종류 | AR 판단 | 묶음 |", "|---|---|---|---|"]
        tier = {"top": "가장 중요한 3가지", "check": "확인사항", "detail": "세부사항"}
        L += [f"| {x['title']} | {x['kind']} | {x['judgment']} | {tier.get(x['tier'], '')} |" for x in d["ar_only"]]
    else:
        L.append("없음")
    L += ["", "## 3. 조서 금액 (참고)", "", "엔진 조서 계산과 신고서 숫자를 견줍니다. 조서를 고칠 때 씁니다.", "",
          "| 서식 | 항목 | 신고서 | 조서 | 결과 | 비고 |", "|---|---|---:|---:|---|---|"]
    for area in ("15호", "3호", "50호(을)"):
        for r in d["paper"][area]:
            L.append(f"| {r['area']} | {r['key']} | {won(r['answer'])} | {won(r['ours'])} | {r['result']} | {r.get('note') or ''} |")
    if d["problems"]:
        L += ["", "## 신고서를 읽다 걸린 곳", ""] + [f"- {p}" for p in d["problems"][:20]]
    return "\n".join(L) + "\n"


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="ar.py compare")
    p.add_argument("folder")
    p.add_argument("pdf", nargs="?", help=f"최종 세무조정계산서 PDF (없으면 <신고건>/{FOLDER}/*.pdf)")
    a = p.parse_args(argv)
    c = paths.case(a.folder)
    from bestar import steps
    if not steps.finished(c) or not (paths.index(c) / "조정.json").exists():
        print("ar.py engine 과 1-(1) ~ 2-(2) 단계를 먼저 끝냅니다.")
        return 2
    pdf = pick_pdf(c, a.pdf)
    if pdf is None:
        print(f"최종 세무조정계산서 PDF 가 없습니다. 경로를 주거나 <신고건>/{FOLDER}/ 에 넣습니다.")
        return 2
    d = build(c, pdf)
    paths.write_json(paths.index(c) / OUT_JSON, d)
    out = c.root / OUT_MD
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(markdown(d), encoding="utf-8")
    s = d["summary"]
    print(f"신고서 항목 {s['points']} · 잡음 {s['잡음']}(가장 중요한 3가지 {s['top']}) · 조정 없음으로 봄 {s['조정 없음으로 봄']} · "
          f"못 잡음 {s['못 잡음']} · AR 만 짚은 것 {s['ar_only']}(조정 필요 {s['ar_only_adjust']})")
    for x in d["items"]:
        mark = {"잡음": "잡음", "조정 없음으로 봄": "없음", "못 잡음": "놓침"}[x["result"]]
        by = ", ".join(k["uid"] for k in x["caught_by"][:4])
        diff = f" 차이 {signed(x['check'].get('diff'))}" if x["check"]["state"] in ("금액 다름", "방향 반대") else ""
        print(f"  [{mark}] {x['title']} {won(x['amount'])}{' · 셋' if x['top'] else ''}  {x['ar_judgment']} {by}"
              f"  | 조서 {check_text(x['check'])}{diff}")
    print(f"보고서: 1 AR/AR_대조.md · _색인/{OUT_JSON}")
    return 0
