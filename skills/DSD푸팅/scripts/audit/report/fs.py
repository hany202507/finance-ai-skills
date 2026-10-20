"""수정 후 시산표와 재무제표 구조 (R4 report, 2026-10-05).

  adjusted_tb(tb, adjustments)   회사제시 시산표에 8100A 에서 '수정' 으로 표시한 분개를 더한다
  build(tb, prior)               표시 단위(과목) · 재무상태표 · 손익계산서 · 자본변동표 행을 만든다

표시 단위: 당기 표시과목이 기본이다. 전기 재무제표가 과목을 '·' 로 묶어 표시했으면(예: 예수금·부가세예수금·미지급법인세)
당기도 같은 묶음으로 보인다. 전기 숫자를 계정 단위로 받지 못해 비교 표시를 맞추려면 이 방법뿐이다.
묶음에 들지 않은 계정은 원래 표시과목으로 남는다. 전기에 없는 과목은 전기 0 으로 두고 '확인' 으로 남긴다.
숫자는 모두 엔진 계산이다. 이 모듈은 판단(표시 방법 변경 · 재분류)을 하지 않는다.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .base import defs, norm


def group_of(code) -> dict | None:
    try:
        c = int(str(code)[:3])
    except ValueError:
        return None
    return next((g for g in defs()["groups"] if g["from"] <= c <= g["to"]), None)


def category_of(code) -> str | None:
    try:
        c = int(str(code)[:3])
    except ValueError:
        return None
    return next((g["key"] for g in defs()["categories"] if g["from"] <= c <= g["to"]), None)


def is_re(code) -> bool:
    r = defs()["retained_earnings"]
    try:
        return r["from"] <= int(str(code)[:3]) <= r["to"]
    except ValueError:
        return False


def adjusted_tb(tb: list[dict], adjustments: list[dict]) -> list[dict]:
    """adjustments: [{issue, code, name, line, dr, cr}]. 시산표에 없는 계정은 새 행으로 더한다."""
    rows = [dict(r, adj_dr=0, adj_cr=0, company=r["amount"], issues=[]) for r in tb]
    by = {r["code"]: r for r in rows}
    for a in adjustments:
        r = by.get(a["code"])
        if r is None:
            r = {"code": a["code"], "name": a.get("name") or "", "line": a.get("line") or a.get("name") or "", "amount": 0,
                 "company": 0, "adj_dr": 0, "adj_cr": 0, "issues": [], "version": None, "path": None, "new": True}
            rows.append(r)
            by[a["code"]] = r
        r["adj_dr"] += a["dr"]
        r["adj_cr"] += a["cr"]
        r["amount"] += a["dr"] - a["cr"]
        if a.get("issue") is not None and a["issue"] not in r["issues"]:
            r["issues"].append(a["issue"])
    rows.sort(key=lambda r: (int(r["code"][:3]) if r["code"][:3].isdigit() else 9999, r["code"]))
    return rows


@dataclass
class Unit:
    name: str
    group: str
    accounts: list = field(default_factory=list)
    cur: int = 0
    prior: int | None = None
    prior_basis: str = ""
    min_code: int = 9999
    subgroup: str | None = None          # 시산표 중분류 줄(< 당좌자산 > 등)에서 읽은 재무상태표 중분류(R8)

    @property
    def codes(self) -> list[str]:
        return [a["code"] for a in self.accounts]


def _prior_items(prior: dict | None) -> list[tuple[str, str, int, str]]:
    """(재무제표, 과목, 금액, 쪽). 합계 이름은 뺀다. 쪽은 재무상태표의 자산 · 부채 · 자본 순서에서 정한다."""
    if not prior:
        return []
    totals = {norm(x) for x in defs()["prior_totals"]}
    out = []
    side = "자산"
    for lab, v in (prior.get("bs") or {}).items():
        n = norm(lab)
        if n == "자산총계":
            side = "부채"
        elif n == "부채총계":
            side = "자본"
        if n in totals:
            continue
        out.append(("bs", lab, v, side))
    for lab, v in (prior.get("is") or {}).items():
        if norm(lab) not in totals:
            out.append(("is", lab, v, "손익"))
    return out


def build(tb: list[dict], prior: dict | None) -> dict:
    D = defs()
    gorder = [g["key"] for g in D["groups"]]
    gby = {g["key"]: g for g in D["groups"]}
    notes, unclassified = [], []
    accs = []
    for r in tb:
        g = group_of(r["code"])
        if g is None:
            unclassified.append(r)
            k = int(str(r["code"])[:3]) if str(r["code"])[:3].isdigit() else 0
            why = ("원가 계정(501~799)이라 원가명세서를 거친 매출원가 · 재고 위치를 회계사가 정해 주십시오. 판독 필요"
                   if 501 <= k <= 799 else "report_fs.yaml 범위 밖")
            notes.append(f"재무제표 위치를 정하지 못한 계정 {r['code']} {r['name']} {r['amount']:,}원({why})")
            continue
        accs.append(dict(r, group=g["key"], side=g["side"], sign=g["sign"]))
    ni = -sum(a["amount"] for a in accs if a["side"] == "손익")

    pitems = _prior_items(prior)
    combined = [(st, lab, v, side) for st, lab, v, side in pitems if "·" in lab]
    assign = {}
    for st, lab, v, side in combined:
        parts = {norm(p) for p in lab.split("·")}
        for a in accs:
            if a["code"] not in assign and (norm(a["name"]) in parts or norm(a["line"]) in parts):
                assign[a["code"]] = lab

    units: dict[str, Unit] = {}
    for a in accs:
        uname = assign.get(a["code"]) or a["line"] or a["name"]
        u = units.get(uname)
        if u is None:
            u = units[uname] = Unit(uname, a["group"])
        u.accounts.append(a)
        if u.subgroup is None and a.get("subgroup") and a["group"] in BS_GROUPS:
            u.subgroup = a["subgroup"]
        c = int(a["code"][:3])
        if c < u.min_code:
            u.min_code, u.group = c, a["group"]
    for u in units.values():
        u.cur = sum(gby[a["group"]]["sign"] * a["amount"] for a in u.accounts)
        if any(is_re(a["code"]) for a in u.accounts):
            u.cur += ni

    used = set()
    pmap = {norm(lab): (lab, v) for _, lab, v, _ in pitems}
    for u in units.values():
        if prior is None:
            u.prior, u.prior_basis = None, "전기 재무제표 없음"
            continue
        names = [u.name] + D.get("aliases", {}).get(u.name, [])
        hit = next((pmap[norm(n)] for n in names if norm(n) in pmap and norm(pmap[norm(n)][0]) not in used), None)
        if hit:
            u.prior, u.prior_basis = hit[1], f"전기 재무제표 '{hit[0]}'"
            used.add(norm(hit[0]))
    # 이름이 바로 맞지 않으면 전기 과목을 당기와 같은 표시과목 규칙(accounts.yaml display_lines)으로 묶어 맞춘다(R8).
    # 예: 전기 재무제표 '직원급여' · '상여금' → 당기 '급여', '제예금' → '현금및현금성자산'
    from ..analysis import defs as adefs

    pnames = {adefs.norm(lab) for _, lab, _, _ in pitems}
    for u in units.values():
        if prior is None or u.prior_basis:
            continue
        got = [(lab, v) for _, lab, v, _ in pitems if norm(lab) not in used and adefs.display_line(lab, pnames)[0] == u.name]
        if got:
            u.prior = sum(v for _, v in got)
            u.prior_basis = "전기 재무제표 " + " · ".join(f"'{lab}'" for lab, _ in got) + "(표시과목 규칙으로 묶음)"
            used |= {norm(lab) for lab, _ in got}
        else:
            u.prior, u.prior_basis = 0, "전기 재무제표에 같은 과목 없음"
            notes.append(f"전기 재무제표에 '{u.name}' 과목이 없어 전기 0 으로 두었습니다")
    for st, lab, v, side in pitems:
        if norm(lab) in used:
            continue
        g = (prior.get("positions") or {}).get(lab) or {"자산": "유동자산", "부채": "유동부채", "자본": "자본"}.get(side)
        if g is None:                     # 손익: 계정 사전의 코드로 손익 묶음을 정한다. 못 정하면 영업외비용
            m = adefs.map_account(None, lab)
            spec = next((a for a in adefs.load("accounts")["accounts"] if a["id"] == m["id"]), None) if m["id"] else None
            grp = group_of(spec["codes"][0]) if spec and spec.get("codes") else None
            g = grp["key"] if grp and grp["side"] == "손익" else "영업외비용"
        u = units[lab] = Unit(lab, g, [], 0, v, "당기 잔액 없음", 9999)
        notes.append(f"전기 재무제표 '{lab}' 에 맞는 당기 계정이 없어 당기 0 으로 두었습니다(위치 {g} 는 엔진 추정)")

    ul = sorted(units.values(), key=lambda u: (gorder.index(u.group), u.min_code, u.name))
    fs = {"units": ul, "ni": ni, "notes": notes, "unclassified": unclassified, "has_prior": prior is not None,
          "prior_as_of": (prior or {}).get("as_of")}
    fs["bs"] = _bs(ul, "부채및자본총계" if prior and "부채및자본총계" in {norm(k) for k in prior.get("bs") or {}} else "부채와자본총계")
    fs["is_form"] = "영업수익" if service_form(prior) else "매출액"
    fs["is"], fs["is_labels"] = _is(ul, fs["is_form"] == "영업수익")
    fs["sce"] = _sce(ul, ni) if prior is not None else None
    return fs


def _sum(vals):
    if any(v is None for v in vals):
        return None
    return sum(vals)


def _row(label, kind, cur, prior, members=None, unit=None):
    return {"label": label, "kind": kind, "cur": cur, "prior": prior, "members": members or [], "unit": unit}


BS_GROUPS = ("유동자산", "비유동자산", "유동부채", "비유동부채", "자본")


def _sub_label(sub: str, us: list[Unit]) -> str:
    """중분류 이름. 이익잉여금 중분류의 합이 음수면 결손금이다(일반기업회계기준 2.33 이익잉여금(또는 결손금))."""
    if sub == "이익잉여금" and sum(u.cur for u in us) < 0:
        return "결손금"
    return sub


def _with_subgroups(us: list[Unit]) -> tuple[list[dict], list[tuple[str, int]]]:
    """한 묶음의 행과 그 묶음 합계의 구성원. 중분류가 있으면 중분류 행(구성원은 과목)을 과목 앞에 둔다."""
    rows, members, seen = [], [], []
    for u in us:
        if u.subgroup not in seen:
            seen.append(u.subgroup)
    for sub in seen:
        sus = [u for u in us if u.subgroup == sub]
        lab = _sub_label(sub, sus) if sub else None
        if lab and not (len(sus) == 1 and sus[0].name == lab) and lab not in {u.name for u in us}:
            rows.append(_row(lab, "group", sum(u.cur for u in sus), _sum([u.prior for u in sus]), [(u.name, 1) for u in sus]))
            members.append((lab, 1))
        else:
            members += [(u.name, 1) for u in sus]
        rows += [_row(u.name, "unit", u.cur, u.prior, unit=u) for u in sus]
    return rows, members


def _bs(units: list[Unit], both_total: str = "부채와자본총계") -> list[dict]:
    rows = []
    for side, groups, total in (("자산", ["유동자산", "비유동자산"], "자산총계"),
                                ("부채", ["유동부채", "비유동부채"], "부채총계"),
                                ("자본", ["자본"], "자본총계")):
        rows.append(_row(side, "header", None, None))
        tmembers = []
        for g in groups:
            us = [u for u in units if u.group == g]
            if not us:
                continue
            sub_rows, members = _with_subgroups(us)
            if side != "자본":
                rows.append(_row(g, "group", sum(u.cur for u in us), _sum([u.prior for u in us]), members))
                tmembers.append((g, 1))
            else:
                tmembers += members
            rows += sub_rows
        vals = {r["label"]: r for r in rows}
        rows.append(_row(total, "total", sum(vals[m]["cur"] for m, _ in tmembers),
                         _sum([vals[m]["prior"] for m, _ in tmembers]), tmembers))
    vals = {r["label"]: r for r in rows}
    rows.append(_row(both_total, "total", vals["부채총계"]["cur"] + vals["자본총계"]["cur"],
                     _sum([vals["부채총계"]["prior"], vals["자본총계"]["prior"]]), [("부채총계", 1), ("자본총계", 1)]))
    return rows


def service_form(prior: dict | None) -> bool:
    """전기 재무제표가 영업수익 · 영업비용 꼴(서비스업 꼴)이면 당기도 그 꼴로 보인다. 근거: 일반기업회계기준 2.13
    (재무제표 항목의 표시와 분류는 매기 동일). 전기 재무제표가 없으면 매출액 · 매출원가 꼴이다(R8, 진단 #20)."""
    if not prior:
        return False
    labs = {norm(k) for k in (prior.get("is") or {})} | {norm(k) for k in ((prior.get("groups") or {}).get("is") or [])}
    return "영업수익" in labs or "영업비용" in labs


def profit_label(key: str, cur, prior) -> str:
    """이익 계산 줄의 표시 이름. 당기 · 전기가 모두 손실이면 '…손실', 한쪽만 손실이면 '…이익(손실)'(R8, 진단 #20)."""
    if not key.endswith("이익"):
        return key
    neg = [v is not None and v < 0 for v in (cur, prior)]
    if neg[0] and (prior is None or neg[1]):
        return key[:-2] + "손실"
    if any(neg):
        return key + "(손실)"
    return key


def _is(units: list[Unit], service: bool = False) -> tuple[list[dict], dict]:
    """손익계산서 행. service 면 영업수익(매출액 계정) · 영업비용(매출원가 + 판매비와관리비 계정) 꼴이다.
    glabel: 계산에 쓰는 이름(매출액 · 매출원가 · 판매비와관리비 · 매출총이익 · 영업이익 …) → 표에 보이는 이름."""
    rows, glabel = [], {}

    def add_group(g, keys=None, label=None):
        keys = keys or [g]
        us = [u for u in units if u.group in keys]
        if not us:
            return
        label = label or g
        if len(us) == 1 and us[0].name == label:
            rows.append(_row(label, "unit", us[0].cur, us[0].prior, unit=us[0]))
        else:
            lab = f"{label} 합계" if any(u.name == label for u in us) else label
            rows.append(_row(lab, "group", sum(u.cur for u in us), _sum([u.prior for u in us]), [(u.name, 1) for u in us]))
            rows.extend(_row(u.name, "unit", u.cur, u.prior, unit=u) for u in us)
            label = lab
        for k in keys:
            glabel[k] = label

    def calc(key, terms):
        members = [(glabel[t], s) if t in glabel else (t, s) for t, s in terms]
        members = [(m, s) for m, s in members if m in {r["label"] for r in rows}]
        by = {r["label"]: r for r in rows}
        cur = sum(s * by[m]["cur"] for m, s in members)
        prior = _sum([by[m]["prior"] for m, _ in members])
        if prior is not None:
            prior = sum(s * by[m]["prior"] for m, s in members)
        label = profit_label(key, cur, prior)
        row = _row(label, "calc", cur, prior, members)
        row["key"] = key
        rows.append(row)
        glabel[key] = label

    if service:
        add_group("매출액", label="영업수익")
        add_group("영업비용", keys=["매출원가", "판매비와관리비"])
        calc("영업이익", [("매출액", 1), ("매출원가", -1)])
    else:
        add_group("매출액")
        add_group("매출원가")
        calc("매출총이익", [("매출액", 1), ("매출원가", -1)])
        add_group("판매비와관리비")
        calc("영업이익", [("매출총이익", 1), ("판매비와관리비", -1)])
    add_group("영업외수익")
    add_group("영업외비용")
    calc("법인세비용차감전순이익", [("영업이익", 1), ("영업외수익", 1), ("영업외비용", -1)])
    add_group("법인세비용")
    calc("당기순이익", [("법인세비용차감전순이익", 1), ("법인세비용", -1)])
    return rows, glabel


def _sce(units: list[Unit], ni: int) -> dict:
    eq = [u for u in units if u.group == "자본"]
    cols = [u.name for u in eq]
    begin = [u.prior if u.prior is not None else 0 for u in eq]
    nis = [ni if any(is_re(c) for c in u.codes) else 0 for u in eq]
    end = [u.cur for u in eq]
    other = [e - b - n for e, b, n in zip(end, begin, nis)]
    rows = [("전기말(당기초)", begin), ("당기순이익", nis)]
    if any(other):
        rows.append(("그 밖의 변동", other))
    rows.append(("당기말", end))
    return {"cols": cols, "rows": [(lab, vals + [sum(vals)]) for lab, vals in rows], "other": any(other)}


def statement_values(fs: dict) -> dict:
    """{'bs': {과목: (당기, 전기)}, 'is': {...}} 엔진 값. 이익 계산 줄은 보이는 이름(…손실)과 계산 이름(…이익) 둘 다로 찾는다."""
    out = {k: {norm(r["label"]): (r["cur"], r["prior"]) for r in fs[k] if r["kind"] != "header"} for k in ("bs", "is")}
    for r in fs["is"]:
        if r.get("key"):
            out["is"].setdefault(norm(r["key"]), (r["cur"], r["prior"]))
    return out


def key_figures(fs: dict) -> dict:
    v = statement_values(fs)
    out = {}
    for k, lab in (("bs", "자산총계"), ("bs", "부채총계"), ("bs", "자본총계"), ("is", "당기순이익"), ("is", "법인세비용차감전순이익")):
        if lab in v[k]:
            out[lab] = v[k][lab][0]
    rev = fs["is_labels"].get("매출액")
    if rev and norm(rev) in v["is"]:
        out["매출액"] = v["is"][norm(rev)][0]
    return out
