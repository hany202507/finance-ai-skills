"""이슈 대응 절차를 그 회사의 실제 대상으로 구체화한다(2026-10-16, 4000P 다음으로 모든 4000 영역).

이슈 하나는 분석적 검토의 Finding 여럿을 묶은 것이다(_색인/분석.json issues[].findings). 이 모듈은 Finding 마다
「무엇이 얼마나 다른지 · 어느 자료와 맞춘 것인지 · 이 조서의 어느 시트에서 대응하는지」 를 한 줄로 적는다.
숫자는 분석.json 에 있는 엔진 값만 쓴다. 판정 · 결론은 쓰지 않는다(감사인 몫).

  lines(ctx, issue, names)   표지 이슈 대응 줄 아래에 붙일 글 목록

대응 시트는 definitions/workpapers.yaml issue_sheets(규칙 id → 시트 기본 이름 목록)로 고른다. 이 조서에 그 시트가 없으면
「대응 시트 없음」 을 적어 감사인이 절차를 직접 적게 한다.
"""
from __future__ import annotations

import json
from pathlib import Path

MAX_LINES = 6          # 표지 줄 높이 때문에 Finding 줄은 이만큼만. 나머지는 「외 N개」


def _analysis(ctx: dict) -> dict:
    if "_an" not in ctx:
        p = Path(ctx["d"]) / "_색인" / "분석.json"
        ctx["_an"] = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    return ctx["_an"]


def _won(x) -> str:
    return f"{int(round(x)):,}원"


def _src(f: dict) -> str:
    """시산표 · 분개장 참조를 뺀 받은자료 출처. 없으면 빈 글."""
    refs = [r for r in f.get("refs") or [] if not str(r).startswith(("tb:", "gl:"))]
    return f" (출처: {', '.join(refs)})" if refs else ""


def _names(an: dict) -> dict:
    out = {}
    for a in an.get("accounts") or []:
        out.setdefault(a.get("id"), a.get("name"))
    return out


def _side(ids, acc: dict, derived: dict) -> tuple[str, str]:
    """관계 규칙 한쪽의 (이름, 단위). 회사 시산표에 없는 계정 id 는 뺀다. 파생 값(평균 차입금 · 원천세 인원)은 analytics.yaml 제목."""
    names, unit = [], "원"
    for i in ids or []:
        if i in acc:
            names.append(acc[i])
        elif i in derived:
            names.append(derived[i].get("title") or i)
            if "인원" in str(derived[i].get("title") or ""):
                unit = "명"
    return " · ".join(names) or "관련 값", unit


def _rel_names(ctx: dict, rule: str, an: dict) -> tuple[tuple[str, str], tuple[str, str]]:
    """관계 규칙(analytics.yaml relations)의 a · b 쪽 (이름, 단위)."""
    from . import common

    acc = _names(an)
    defs = common.load_def("analytics.yaml") or {}
    derived = {x.get("id"): x for x in defs.get("derived") or []}
    for r in defs.get("relations") or []:
        if r.get("id") == rule:
            return _side(r.get("a"), acc, derived), _side(r.get("b"), acc, derived)
    return ("앞 값", "원"), ("뒤 값", "원")


def _amt(x, unit: str) -> str:
    return _won(x) if unit == "원" else f"{x:,.0f}{unit}"


def _acct(f: dict, an: dict) -> str:
    acc = _names(an)
    return " · ".join(acc.get(i) or i for i in f.get("accounts") or []) or "계정"


def describe(ctx: dict, f: dict, an: dict) -> str | None:
    """Finding 한 개를 실제 대상과 금액으로 적는다. 패턴은 따로 묶으므로 None."""
    m = f.get("metric") or {}
    k = f.get("kind")
    if k == "recon":
        who = f"({m['institution']})" if m.get("institution") else ""
        chk = f" · {m['check']}" if m.get("check") else ""
        return f"{f['title']}{who}: 장부 {_won(m['left'])} · 대사 자료 {_won(m['right'])} · 차이 {_won(m['diff'])}{chk}{_src(f)}"
    if k == "balance":
        top = ", ".join(t["party"] for t in (m.get("top") or [])[:3])
        if "overlap" in m:
            return f"{f['title']}: {m.get('count')}곳 · 겹치는 금액 {_won(m['overlap'])}" + (f"(상위 {top})" if top else "") + _src(f)
        return (f"{f['title']}: {m.get('sheet')} {m.get('side')} 잔액 {m.get('count')}곳 · 합계 {_won(m.get('total') or 0)}"
                + (f"(상위 {top})" if top else "") + _src(f))
    if k == "expectation":
        basis = ""
        if m.get("avg_balance") is not None and m.get("rate") is not None:
            basis = f", 평균 차입금 {_won(m['avg_balance'])} × 금리 {m['rate']:.2%}"
        elif m.get("prior_ratio") is not None:
            basis = f", 전기 비율 {m['prior_ratio']:.2%}"
        return f"{f['title']}: 기대치 {_won(m['expected'])}{basis} · 장부 {_won(m['actual'])} · 차이 {_won(m['diff'])}{_src(f)}"
    if k == "relation":
        (a, ua), (b, ub) = _rel_names(ctx, f.get("rule_id"), an)
        rate = lambda g: f" ({g:+.1%})" if isinstance(g, (int, float)) else ""
        return (f"{f['title']}: {a} 증감 {_amt(m.get('d_a') or 0, ua)}{rate(m.get('g_a'))} · {b} 증감 {_amt(m.get('d_b') or 0, ub)}"
                f"{rate(m.get('g_b'))} · 엔진 차이 금액 {_won(f['amount'])}")
    if k == "variance":
        if m.get("cur") is None:
            return f"{f['title']}: {_won(f['amount'])}"
        return f"{_acct(f, an)} 증감 가운데 독립 자료로 설명되지 않는 금액: 당기 {_won(m['cur'])} · 전기 {_won(m['prior'])} · 설명되지 않는 증감 {_won(m.get('unexplained') or f['amount'])}"
    if k == "monthly":
        return (f"{_acct(f, an)} {f['title']}: {m.get('ye_month')} {_won(m.get('ye_amount') or 0)} · 앞 11개월 평균 {_won(m.get('avg_prev11') or 0)}"
                + (f" ({m['ratio']:.1f}배)" if m.get("ratio") else ""))
    if k == "keytx" and m.get("match") == "minutes":
        cp = f" · 상대방 {m['counterparty']}" if m.get("counterparty") else ""
        return (f"{m.get('meeting')} {m.get('date')} {m.get('agenda')} {_won(m.get('agenda_amount') or f['amount'])}{cp}: "
                f"{f['title']}{_src(f)}")
    if k == "keytx":
        memo = f" 「{m['memo']}」" if m.get("memo") else ""
        party = f" · {m['party']}" if m.get("party") else ""
        if m.get("party") and m["party"] in _related(ctx):
            party += "(영구조서 150 특수관계자 → 3500)"
        return f"전표 {m.get('date')} {m.get('voucher')}{memo}{party} {_won(m.get('area_amount') or f['amount'])}: {f['title']}"
    if k == "pattern":
        return None
    return f"{f['title']}: {_won(f['amount'])}"


def _related(ctx: dict) -> set[str]:
    if "_rp" not in ctx:
        from .. import relparty

        try:
            got = relparty.parties(Path(ctx["d"]))
        except Exception:          # 시험용 ctx(감사 폴더 없음)
            got = None
        ctx["_rp"] = {p["name"] for p in got["rows"]} if got else set()
    return ctx["_rp"]


def _sheet(ctx: dict, f: dict, names: dict) -> str:
    rules = (ctx["defs"].get("issue_sheets") or {})
    k = f.get("kind")
    want = rules.get(f.get("rule_id")) or rules.get(f"kind:{k}" + (":minutes" if (f.get("metric") or {}).get("match") == "minutes" else "")) or []
    for s in want:
        if s in names:
            return names[s]
    return ""


def ar_lines(ctx: dict, names: dict) -> list[str]:
    """4000C: 거래처별 잔액에서 실재성 대상(당기 신규 거래처, 기말 후 입금 없음, 기말 후 취소)을 적는다."""
    from . import lead

    try:
        pop = lead.ar_population(ctx)
    except Exception:          # 거래처원장 · 분개장이 없으면 거래처 단위 대상을 적지 않는다
        return []
    rows = pop["rows"]
    sheet = names.get("거래처별", "거래처별")
    out = []
    new = [r for r in rows if r["new"] and r["amount"]]
    if new:
        out.append(f"당기 신규 거래처 잔액 {len(new)}곳 {_won(sum(r['amount'] for r in new))}("
                   + ", ".join(r["party"] for r in new[:4]) + (f" 외 {len(new) - 4}곳" if len(new) > 4 else "")
                   + f") → {sheet} · 3320 조회와 실재성 확인(사업자 조회 · 계약서 · 출고 증빙)")
    if pop["post_files"]:
        none = [r for r in rows if r["amount"] and not r["collected"]]
        if none:
            out.append(f"기말 후 입금이 없는 거래처 {len(none)}곳 {_won(sum(r['amount'] for r in none))} → {sheet} 「기말 후 입금」 · 대체적 절차")
        canc = [r for r in rows if r["cancelled"]]
        if canc:
            out.append(f"기말 후 매출 취소로 줄어든 거래처 {len(canc)}곳 {_won(sum(r['cancelled'] for r in canc))}("
                       + ", ".join(r["party"] for r in canc[:4]) + ") → 4000P Cut-off 「기말 후 매출 취소와 원 매출 전표」")
    return out


def lines(ctx: dict, issue: dict, names: dict) -> list[str]:
    """표지 이슈 대응 줄에 붙일 글. 분석.json 이 없거나 이슈를 찾지 못하면 빈 목록."""
    an = _analysis(ctx)
    g = next((x for x in an.get("issues") or [] if x.get("issue") == issue.get("no")), None)
    if not g:
        return []
    by = {f["id"]: f for f in an.get("findings") or []}
    fs = [by[i] for i in g.get("findings") or [] if i in by]
    out = ar_lines(ctx, names) if issue.get("area") == "C" else []
    plain = [f for f in fs if f.get("kind") != "pattern"]
    for f in plain[:MAX_LINES]:
        t = describe(ctx, f, an)
        if not t:
            continue
        s = _sheet(ctx, f, names)
        out.append(t + (f" → {s}" if s else " → 대응 시트 없음. 수행 결과에 절차와 증빙을 적는다"))
    if len(plain) > MAX_LINES:
        out.append(f"그 밖의 근거 {len(plain) - MAX_LINES}개는 2120A 이슈 {issue['no']} 에 있다")
    pats = sorted((f for f in fs if f.get("kind") == "pattern"), key=lambda f: -(f.get("amount") or 0))
    if pats:
        out.append("부정 패턴 후보(엔진, 확인 전): " + ", ".join(p["title"] for p in pats[:2])
                   + (f" 외 {len(pats) - 2}개" if len(pats) > 2 else "") + ". 위 절차의 결과로 해당 여부를 적는다")
    return out
