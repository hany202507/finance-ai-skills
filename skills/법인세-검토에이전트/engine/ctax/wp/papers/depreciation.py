"""5 감가상각: 자산 묶음(유형 · 무형자산 계정)별 회사계상 상각비 · 상각범위액 · 시부인. 20호(1)(2)(4).

- 묶음: 재무상태표 유형 · 무형자산 계정 하나가 한 묶음이고, 바로 뒤의 감가상각누계액 계정이 따라붙는다.
- 회사계상 상각비: 상각비(감가상각비 · 무형자산상각비, 판관비 · 제조원가 모두) 차변이 있는 전표의 누계액 대변
  (누계액이 없는 무형자산은 자산 계정 대변).
- 상각방법 · 내용연수: 노란 칸. 기본값은 무신고 기본(시행령 제26조 제4항 · 제28조 제1항 제2호 단서: 건축물 · 무형자산
  정액, 그 밖의 유형자산 정률, 기준내용연수). 회사 상각비가 어떤 방법 · 연수의 범위액과 단수 차이 안에서 같으면
  그 방법 · 연수를 「추정」 으로 채운다. 업종별 자산(기계장치 등, 별표 6)은 업종을 몰라 내용연수를 비워 둔다.
- 시부인: 노란 칸 「시부인」 이 「적용」 일 때만 상각부인(가산 · 유보) · 시인부족 · 추인(차감 · 유보)을 낸다.
  기본값은 「보류」 다(방법 · 연수가 확인 전이라 한도를 정할 수 없다). 보류면 시부인 0 이고 서식 범위액은 회사계상액이다.
  회계사가 방법 · 연수를 고치면 기본값이 「적용」 이 된다.
"""
from __future__ import annotations

from datetime import date
from fractions import Fraction

from openpyxl.utils import get_column_letter as L

from ... import xlsx as X
from ..books import Books, frac, rd
from ..model import Adj, LineRow, Paper
from ..sheet import Book, adj_table, forms_table, head, ledger, notes

NAME = "감가상각"
FORMS = ["20_1", "20_2", "20_4"]
LEDGER_CHECK = False   # 자산 · 누계액 · 비용 계정이 섞여 계정 합계 검사가 맞지 않는다

FORM_COLS = ["건축물", "기계장치", "기타자산", "무형자산"]
CONTRA = ("누계", "국고보조금", "정부보조금", "손상차손")
NOT_DEPRECIABLE = ("토지", "건설중", "미착", "보증금", "회원권", "선급", "투자부동산", "임차권리금")
INTANGIBLE_WORDS = ("특허권", "상표권", "디자인권", "실용신안권", "영업권", "개발비", "소프트웨어", "무형")
LABELS = ("상각", "취득", "처분", "처분 누계", "누계 기타")
APPLY, HOLD = "적용", "보류"


def basis(rates: dict) -> list[tuple]:
    d = rates["depreciation"]
    return [("감가상각 무신고 상각방법", "건축물 · 무형 정액, 그 밖 정률", d["default_method"]["basis"], d["default_method"]["grade"], None),
            ("업무용승용차 상각방법", "정액 5년", d["business_car"]["basis"], d["business_car"]["grade"], None)]


def basis_table(bk: Book, s, r: int) -> int:
    """기준 시트에 상각률표(별표 4)를 쓰고 범위를 bk.ref["상각률표"] 에 둔다. 다음 행을 돌려준다."""
    rt = bk.b.rates["depreciation"]["rate_table"]
    s.ws.cell(row=r, column=1, value=f"감가상각자산의 상각률표 · {rt['basis']} · {rt['grade']}").font = X.NOTE_FONT
    r += 1
    X.header(s.ws, r, ["내용연수", "정액법", "정률법"])
    r += 1
    first = r
    for life, sl, db in rt["value"]:
        s.put(r, 1, life, fmt="0")
        s.put(r, 2, sl, fmt="0.000")
        s.put(r, 3, db, fmt="0.000")
        r += 1
    bk.ref["상각률표"] = f"'{s.title}'!$A${first}:$C${r - 1}"
    return r


# 묶음 고르기 ------------------------------------------------------------------------------------------

def _kind(name: str, sub: str) -> tuple[str, str]:
    """(종류, 20호(4) 열)."""
    if sub == "무형자산" or any(w in name for w in INTANGIBLE_WORDS):
        return "무형", "무형자산"
    if "건물" in name or "구축물" in name:
        return "건축물", "건축물"
    if "차량" in name:
        return "차량", "기타자산"
    if any(w in name for w in ("비품", "공구", "기구", "금형")):
        return "비품", "기타자산"
    if any(w in name for w in ("기계", "장비", "장치")) and "시설장치" not in name:
        return "기계", "기계장치"
    return "기타", "기타자산"


def _defaults(kind: str, name: str, rates: dict) -> tuple[str, int, list[tuple[str, int]], str]:
    """(기본 방법, 기본 연수(0 은 모름), 추정 후보 [(방법, 연수)], 근거)."""
    d = rates["depreciation"]
    if kind == "건축물":
        life = d["life_building_rc"]["value"][0]
        cands = [("정액", n) for n in range(8, 51)]
        return "정액", life, cands, "무신고 기본(정액) · 별표 5 철근콘크리트조 40년(구조 확인)"
    if kind == "무형":
        table = d["life_intangible"]["value"]
        life = next((v for k, v in table.items() if k in name), None)
        if life is None:
            life = d["life_development_default"]["value"] if "개발비" in name else d["life_other_intangible_default"]["value"]
        return "정액", life, [("정액", n) for n in range(2, 21)], "무신고 기본(정액) · 별표 3 또는 5년 균등"
    if kind in ("차량", "비품"):
        life = d["life_vehicle_tools"]["value"][0]
        cands = [(m, n) for m in ("정률", "정액") for n in range(4, 7)]
        return "정률", life, cands, "무신고 기본(정률) · 별표 5 구분 1 기준내용연수 5년"
    return "정률", 0, [(m, n) for m in ("정률", "정액") for n in range(3, 26)], "무신고 기본(정률) · 별표 6 업종별 내용연수 확인 필요"


def _groups(b: Books) -> list[dict]:
    accts = sorted((a for a in b.ledger.get("accounts", []) if a.get("class") == "자산"), key=lambda a: a["code"])
    groups: list[dict] = []
    current = None
    for a in accts:
        name, sub = a.get("name", ""), a.get("subsection") or ""
        code3 = a["code"][:3]
        tangible_range = code3.isdigit() and 195 <= int(code3) <= 250
        in_scope = sub in ("유형자산", "무형자산") or (not sub and tangible_range and a.get("section") == "비유동자산")
        if not in_scope:
            current = None
            continue
        credit_only = int(a.get("opening") or 0) <= 0 and int(a.get("closing") or 0) <= 0 and (a.get("opening") or a.get("closing"))
        if any(w in name for w in CONTRA) or credit_only:
            # 국고보조금 · 일반참여분처럼 대변 잔액뿐인 차감 계정은 앞 묶음에 붙인다(누계액만 상각에 쓴다)
            if current is not None:
                (current["contra"] if "누계" in name else current["subsidy"]).append(a)
            continue
        if any(w in name for w in NOT_DEPRECIABLE):
            current = None
            continue
        kind, col = _kind(name, sub)
        current = {"asset": a, "contra": [], "subsidy": [], "kind": kind, "form_col": col}
        groups.append(current)
    # 같은 이름이 둘이면 코드를 붙인다
    names = [g["asset"]["name"] for g in groups]
    for g in groups:
        n = g["asset"]["name"]
        g["name"] = n if names.count(n) == 1 else f"{n} {g['asset']['code']}"
    return groups


def _dep_vouchers(b: Books) -> set[tuple[str, str]]:
    out = set()
    for ln in b.all_lines():
        a = b.by_code.get(ln.account) or {}
        name = a.get("name") or ln.account_name
        if a.get("class") == "비용" and "상각" in name and "대손" not in name and ln.debit:
            out.add((ln.date, ln.no))
    return out


def _months_used(b: Books, d: str) -> int:
    try:
        e = date.fromisoformat(b.info["fy_end"])
        x = date.fromisoformat(d[:10])
    except (KeyError, ValueError):
        return 12
    return max(1, min(b.months, (e.year - x.year) * 12 + e.month - x.month + 1))


def _disposal_vouchers(b: Books) -> set[tuple[str, str]]:
    """처분이익 · 처분손실 계정이 든 전표. 처분 전표에 처분 전까지의 상각비가 함께 있어도 자산 대변 · 누계액 차변은 처분이다."""
    out = set()
    for ln in b.all_lines():
        a = b.by_code.get(ln.account) or {}
        name = a.get("name") or ln.account_name
        if a.get("class") in ("수익", "비용") and ("처분이익" in name or "처분손실" in name):
            out.add((ln.date, ln.no))
    return out


def _label(ln, is_contra: bool, dep: set, disp: set = frozenset()) -> str:
    in_dep = (ln.date, ln.no) in dep
    in_disp = (ln.date, ln.no) in disp
    if is_contra:
        if in_dep and not (in_disp and ln.amount > 0):
            return "상각"
        return "처분 누계" if ln.amount > 0 else "누계 기타"
    if in_dep and ln.amount < 0 and not in_disp:
        return "상각"
    return "취득" if ln.amount > 0 else "처분"


def additions_without_dep(b: Books) -> list[dict]:
    """당기 취득(I)이 있는데 회사 상각비(N)가 0 인 자산 묶음(10-20, AR dep_missing 이 읽는다).
    [{group, asset_code, additions, first, months, accum_codes}]. 묶음 · 취득 · 상각 가르기는 compute 와 같다(_groups · _label)."""
    dep_v, disp_v = _dep_vouchers(b), _disposal_vouchers(b)
    out = []
    for g in _groups(b):
        a = g["asset"]
        contra_codes = {c["code"] for c in g["contra"]}
        lines = b.lines_of([a] + g["contra"])
        labels = [(ln, _label(ln, ln.account in contra_codes, dep_v, disp_v)) for ln in lines]
        adds = [ln for ln, lab in labels if lab == "취득"]
        dep = -sum(ln.amount for ln, lab in labels if lab == "상각")
        total = sum(ln.amount for ln in adds)
        if total <= 0 or dep:
            continue
        first = min(ln.date for ln in adds)
        out.append({"group": g["name"], "asset_code": a["code"], "additions": total, "first": first,
                    "months": _months_used(b, first), "accum_codes": sorted(contra_codes)})
    return out


def limit_of(method: str, rate: float, acq_base: int, g: dict) -> int:
    """상각범위액(계산). 정액은 취득가액 기준, 정률은 세무상 미상각잔액 기준(월할 취득 반영), 세무상 미상각잔액을 넘지 않는다."""
    if not rate:
        return 0
    base = acq_base if method == "정액" else g["H"] - g["L"] + g["P"] - (g["J"] - g["M"]) + g["Q"]
    return min(g["S"], rd(base * frac(rate)))


# 계산 ----------------------------------------------------------------------------------------------

def compute(p: Paper, b: Books) -> None:
    rates = b.rates
    table = {life: (sl, db) for life, sl, db in rates["depreciation"]["rate_table"]["value"]}
    dep_v = _dep_vouchers(b)
    disp_v = _disposal_vouchers(b)
    groups = _groups(b)
    exp_accts = [a for a in b.accounts(cls="비용") if "상각" in a.get("name", "") and "대손" not in a.get("name", "")]
    p.accounts = exp_accts
    prior_res = (b.prior or {}).get("reserves", []) or []
    rows = []
    for i, g in enumerate(groups, start=1):
        a, gname = g["asset"], g["name"]
        contra_codes = {c["code"] for c in g["contra"]}
        lines = b.lines_of([a] + g["contra"])
        lrows = [LineRow(ln, _label(ln, ln.account in contra_codes, dep_v, disp_v), "") for ln in lines]
        p.lines.extend(lrows)
        by = {lab: [r.line for r in lrows if r.label == lab] for lab in LABELS}
        H = int(a.get("opening") or 0)
        I = sum(ln.amount for ln in by["취득"])
        J = -sum(ln.amount for ln in by["처분"])
        K = int(a.get("closing") or 0)
        L_ = -sum(int(c.get("opening") or 0) for c in g["contra"])
        M = sum(ln.amount for ln in by["처분 누계"])
        N = -sum(ln.amount for ln in by["상각"])
        O = -sum(int(c.get("closing") or 0) for c in g["contra"])
        Q = rd(sum((Fraction(ln.amount * _months_used(b, ln.date), 12) for ln in by["취득"]), Fraction(0)))
        # 전기 50호(을) 유보 중 이 묶음 것
        hit = [r for r in prior_res if gname.split(" ")[0] in (r.get("subject") or "") and "승용차" not in (r.get("subject") or "")]
        P0 = sum(int(r.get("closing") or 0) for r in hit)
        P = p.take(b, f"기초 부인누계/{gname}", P0, "int")
        S = max(0, H - L_ + P - (J - M) + I)
        vals = {"H": H, "I": I, "J": J, "K": K, "L": L_, "M": M, "N": N, "O": O, "P": P, "Q": Q, "S": S}
        method0, life0, cands, why0 = _defaults(g["kind"], a.get("name", ""), rates)
        acq0 = H - J + Q
        basis_kind = "기본값"
        # 회사 상각비와 맞는 방법 · 연수 찾기(추정)
        if N > 0:
            tol = max(1000, N // 200)
            best = None
            for m, n in cands:
                rt = table.get(n, (0, 0))[0 if m == "정액" else 1]
                diff = abs(limit_of(m, rt, acq0, vals) - N)
                if diff <= tol:
                    key = (diff, m != method0, abs(n - (life0 or n)))
                    if best is None or key < best[0]:
                        best = (key, m, n)
            if best:
                method0, life0, basis_kind = best[1], best[2], "추정"
                why0 = f"회사 상각비가 {best[1]} {best[2]}년 범위액과 {best[0][0]:,}원 차이 안에서 같습니다(추정)"
        method = p.take(b, f"상각방법/{gname}", method0)
        life = p.take(b, f"내용연수/{gname}", life0, "int")
        acq_base = p.take(b, f"정액 기준 취득가액/{gname}", acq0, "int")
        changed = any(k in p.overridden for k in (f"상각방법/{gname}", f"내용연수/{gname}", f"정액 기준 취득가액/{gname}"))
        if changed:
            basis_kind, why0 = "회계사", "회계사가 넣은 상각방법 · 내용연수"
        apply = p.take(b, f"시부인/{gname}", APPLY if changed else HOLD)
        rate = table.get(life, (0, 0))[0 if method == "정액" else 1] if life else 0
        T = limit_of(method, rate, acq_base, vals)
        on = apply == APPLY
        W = max(0, N - T) if on else 0
        Xs = max(0, T - N) if on else 0
        Y = min(Xs, max(P, 0))
        Z = P + W - Y
        subj = next((r.get("subject") for r in hit), None) or f"감가상각누계액({gname})"
        status = ("시부인" if on else ("상각 없음" if N == 0 else ("내용연수 필요" if not rate else
                  ("회사 상각과 일치" if abs(N - T) <= max(1000, N // 200) else "확인 필요"))))
        rows.append({"i": i, "group": gname, "kind": g["kind"], "accounts": [a["code"]] + sorted(contra_codes),
                     "asset_code": a["code"], "contra_codes": sorted(contra_codes),
                     "form_col": g["form_col"], "method": method, "life": life, "rate": rate, "basis": why0,
                     "basis_kind": basis_kind, "acquisition": K, "acquisition_begin": H, "additions": I,
                     "additions_monthly": Q, "disposals": J, "accum_begin": L_, "accum_disposed": M, "accum_end": O,
                     "dep_company": N, "acq_base": acq_base, "cap": S, "limit_calc": T,
                     "limit": T if on else N, "apply": on, "excess": W, "shortfall": Xs, "reversal": Y,
                     "reserve_begin": P, "reserve_end": Z, "status": status, "reserve_subject": subj,
                     "subsidy": [s_["code"] for s_ in g["subsidy"]]})
        p.adjustments.append(Adj("가산", f"감가상각비({gname})", W, "유보", f"{gname} 상각부인",
                                 f"{gname} 감가상각비 상각부인액 손금불산입", f"g{i}.excess", subj, "증가", 1))
        p.adjustments.append(Adj("차감", f"감가상각비({gname})", Y, "유보", f"{gname} 상각부인 추인",
                                 f"{gname} 전기 상각부인액 중 시인부족액만큼 손금산입", f"g{i}.reversal", subj, "감소", 1))
    p.extra["rows"] = rows
    _values(p, rows)
    grants = grant_reversals(p, b, groups, disp_v)
    _messages(p, b, rows, exp_accts)
    p.settle(bool(rows and (any(r["dep_company"] or r["acquisition"] for r in rows))) or any(g["추인"] for g in grants))


GRANT = "보조금"
DISPOSE_WORD = ("처분", "매각", "폐기", "폐차", "양도", "제각")


def grant_reversals(p: Paper, b: Books, groups: list[dict], disp_v: set) -> list[dict]:
    """전기 50호(을) 보조금 유보(국고보조금 · 일반보조금 등)의 처분 추인(10-21).

    보조금으로 산 자산을 처분하면 그 자산 몫의 보조금 유보도 없어진다. 일시상각충당금은 감가상각비와 상계하고 남은 잔액을 처분한 사업연도에
    전액 익금산입하고 압축기장충당금도 처분한 사업연도에 전액 익금산입하며, 일부 처분은 자산가액 중 충당금 비율로 안분한다(법인세법 시행령
    제64조 제4항 · 제5항, 2025-12-31 시행판 원문 ★★☆: korean-law 만 읽음). 장부로는 어느 자산 몫인지 알 수 없어 처분 전표가 지운
    보조금 차감 계정 금액의 비율 「처분 전표의 보조금 계정 차변 ÷ (기초 보조금 잔액 + 당기 수령)」 로 추인 기본값을 낸다. 처분 전표는 처분이익 · 처분손실
    계정이 있거나 자산 대변 줄 적요에 처분 · 매각 · 폐기 · 폐차가 든 전표다. 감가상각비와 상계한 줄(상각 전표)은 세지 않는다.
    노란 칸 「전기 유보 추인/<과목>」, 확인 줄을 늘 낸다."""
    rows = [r for r in (b.prior or {}).get("reserves", []) or [] if GRANT in str(r.get("subject") or "") and int(r.get("closing") or 0)]
    if not rows:
        return []
    subsidy = {a["code"]: a for g in groups for a in g["subsidy"]}
    for a in b.accounts(cls="자산"):
        if GRANT in a.get("name", ""):
            subsidy.setdefault(a["code"], a)
    assets = {g["asset"]["code"] for g in groups}
    vouchers: dict[tuple, list] = {}
    for ln in b.all_lines():
        vouchers.setdefault((ln.date, ln.no), []).append(ln)
    removed = received = 0
    hits = []
    dep_v = _dep_vouchers(b)
    for key, lines in vouchers.items():
        sold = key in disp_v or any(ln.account in assets and ln.credit and any(w in (ln.memo or "") for w in DISPOSE_WORD)
                                    for ln in lines)
        for ln in lines:
            if ln.account not in subsidy:
                continue
            received += ln.credit
            if sold and ln.debit and not (key in dep_v and key not in disp_v):
                removed += ln.debit
                hits.append(ln)
    pool = -sum(int(a.get("opening") or 0) for a in subsidy.values()) + received
    ratio = Fraction(min(removed, pool), pool) if pool > 0 and removed > 0 else Fraction(0)
    out = []
    for r in rows:
        subj, R = str(r["subject"]), int(r["closing"])
        key = f"전기 유보 추인/{subj}"
        calc = rd(abs(R) * ratio)
        rev = p.take(b, key, calc, "int")
        g = {"subject": subj, "기초유보": R, "처분 보조금": removed, "보조금 기초 + 수령": pool, "비율": float(ratio),
             "추정추인": calc, "추인": rev, "key": key}
        out.append(g)
        if R < 0:
            p.adjustments.append(Adj("가산", subj, rev, "유보", f"{subj} 처분 추인", f"보조금 자산 처분분 {subj} 유보 익금산입", key, subj,
                                     "감소", -1))
        else:
            p.adjustments.append(Adj("차감", subj, rev, "유보", f"{subj} 처분 추인", f"보조금 자산 처분분 {subj} 유보 손금산입", key, subj,
                                     "감소", 1))
        if key in p.overridden:
            continue
        if calc:
            p.confirm.append(f"{subj}: 처분 전표가 보조금 차감 계정 {removed:,}원을 지웠습니다(기초 잔액 + 당기 수령 {pool:,}원의 "
                             f"{float(ratio):.2%}). 전기 유보 {R:,}원 중 {calc:,}원을 추인 기본값으로 두었습니다. 처분한 자산이 그 보조금으로 산 "
                             "자산인지, 유보가 그 자산 몫인지 확인하고 노란 칸을 고치십시오")
        else:
            p.notes.append(f"{subj}: 전기 유보 {R:,}원은 보조금으로 산 자산을 처분할 때 추인합니다. 당기 처분 전표에 보조금 계정이 없어 "
                           "추인하지 않았습니다. 처분했으면 노란 칸에 넣으십시오")
    p.values["보조금 유보"] = [{k: v for k, v in g.items() if k != "key"} for g in out]
    p.extra["grants"] = out
    return out


def _values(p: Paper, rows: list[dict]) -> None:
    keys = ("group", "accounts", "form_col", "method", "life", "rate", "basis", "acquisition", "acquisition_begin",
            "additions", "disposals", "accum_begin", "accum_end", "dep_company", "limit", "limit_calc", "apply",
            "excess", "shortfall", "reversal", "reserve_begin", "reserve_end", "status")
    groups = [{k: r[k] for k in keys} for r in rows]
    tot = {k: sum(r[k] for r in rows) for k in ("dep_company", "limit", "excess", "shortfall", "reversal",
                                                 "reserve_begin", "reserve_end")}
    by_form = {}
    for col in FORM_COLS:
        rs = [r for r in rows if r["form_col"] == col]
        if not rs:
            continue
        by_form[col] = {"acquisition": sum(r["acquisition"] for r in rs), "accum_end": sum(r["accum_end"] for r in rs),
                        "unamortized": sum(r["acquisition"] - r["accum_end"] for r in rs),
                        "limit": sum(r["limit"] for r in rs), "dep_company": sum(r["dep_company"] for r in rs),
                        "excess": sum(r["excess"] for r in rs), "shortfall": sum(r["shortfall"] for r in rs),
                        "reversal": sum(r["reversal"] for r in rs)}
    p.values = {"groups": groups, "totals": tot, "by_form": by_form}


def _messages(p: Paper, b: Books, rows: list[dict], exp_accts: list[dict]) -> None:
    exp_total = sum(int(a.get("amount") or 0) for a in exp_accts)
    dep_total = sum(r["dep_company"] for r in rows)
    if any("감가상각비" not in a.get("name", "") for a in exp_accts):
        listed = " · ".join(f"{a['name']}({a['code']}) {int(a.get('amount') or 0):,}원" for a in exp_accts)
        p.notes.append(f"회사계상 상각비에 넣은 비용 계정: {listed}. 무형자산 상각비(영업권 · 상표권 등)도 20호(4) 무형자산 열에 듭니다")
    if exp_total != dep_total:
        p.confirm.append(f"상각비 계정 합계 {exp_total:,}원과 묶음별 회사계상 상각비 합계 {dep_total:,}원이 {exp_total - dep_total:,}원 다릅니다"
                         "(국고보조금 상계 · 누계액 없는 상각 · 다른 계정 상대 전표를 확인하세요)")
    for r in rows:
        g = r["group"]
        if r["status"] == "확인 필요":
            p.confirm.append(f"{g}: {r['method']} {r['life']}년 범위액 {r['limit_calc']:,}원과 회사계상 {r['dep_company']:,}원이 다릅니다. "
                             "감가상각방법 · 내용연수 신고서를 확인하고 상각방법 · 내용연수 칸을 고치거나 시부인 칸을 「적용」 으로 바꾸세요")
        elif r["status"] == "내용연수 필요":
            p.confirm.append(f"{g}: 업종별 자산(별표 6)이라 내용연수를 넣어야 범위액을 잽니다. 그 전에는 시부인 0 입니다")
        if r["reserve_begin"] and not r["apply"]:
            p.confirm.append(f"{g}: 전기 상각부인누계 {r['reserve_begin']:,}원이 있습니다. 시부인을 「적용」 해야 시인부족액만큼 추인합니다")
        if r["subsidy"]:
            p.notes.append(f"{g}: 국고보조금 계정({', '.join(r['subsidy'])})이 있습니다. 일시상각충당금 신고조정은 이 조서에 없습니다")
        if r["kind"] == "차량" and r["dep_company"]:
            p.notes.append(f"{g}: 업무용승용차는 정액법 5년이 강제됩니다(시행령 제50조의2 제3항). 승용차 몫은 업무용승용차 조서 「자가 감가상각비」 칸에도 넣으세요")
        if r["disposals"] and r["reserve_begin"]:
            p.confirm.append(f"{g}: 처분이 있습니다. 처분 자산의 상각부인누계는 처분한 해에 손금산입합니다(직접 조정 줄)")
    if any(r["basis_kind"] == "추정" for r in rows):
        p.notes.append("「추정」 은 회사 상각비와 맞는 상각방법 · 내용연수를 엔진이 고른 것입니다. 감가상각방법 · 내용연수 신고서로 확인하세요")
    p.notes.append("시부인 칸이 「보류」 이면 시부인 0 이고 20호 상각범위액은 회사계상액으로 둡니다. 상각방법 · 내용연수를 확인한 뒤 「적용」 으로 바꾸세요")
    p.notes.append("당기 취득은 취득 전표 월부터 사업연도 끝까지 월할(시행령 제26조 제9항), 정률법 잔존가액 5% · 비망가액 1천원은 묶음 단위라 반영하지 않았습니다")
    pc = ((b.prior or {}).get("cells") or {}).get("20_4") or {}
    for col, suf in zip(FORM_COLS, ("_3", "_4", "_5", "_6")):
        lim, dep = pc.get("04" + suf), pc.get("05" + suf)
        if lim is not None and dep is not None:
            p.notes.append(f"전기 20호(4) {col}: 상각범위액 {int(lim):,}원 · 회사계상 {int(dep):,}원")


# 엑셀 ----------------------------------------------------------------------------------------------

COLS = ["자산 묶음", "계정", "20호(4) 열", "상각방법", "내용연수", "상각률", "근거",
        "기초 취득가액", "당기 취득", "당기 처분", "기말 취득가액", "기초 누계액", "처분 누계", "회사계상 상각비", "기말 누계액",
        "기초 부인누계", "월할 취득액", "정액 기준 취득가액", "상각 기초가액", "세무상 미상각잔액", "상각범위액(계산)",
        "시부인", "상각범위액(서식)", "상각부인액", "시인부족액", "기왕부인액 추인", "기말 부인누계", "차이(회사계상 - 계산)"]
JSON_KEY = {"기말 취득가액": "acquisition", "기초 누계액": "accum_begin", "회사계상 상각비": "dep_company",
            "기말 누계액": "accum_end", "기초 부인누계": "reserve_begin", "상각률": "rate", "상각범위액(계산)": "limit_calc",
            "상각범위액(서식)": "limit", "상각부인액": "excess", "시인부족액": "shortfall", "기왕부인액 추인": "reversal",
            "기말 부인누계": "reserve_end", "당기 취득": "additions", "당기 처분": "disposals", "기초 취득가액": "acquisition_begin"}


def write(bk: Book, p: Paper) -> None:
    s = head(bk, p)
    R = bk.ref
    rows = p.extra["rows"]
    row = 5
    # 1. 금액 검증 위치를 잡으려면 원장 범위가 먼저 필요하다: 금액 검증은 집계 표 뒤에 둔다.
    row, first, last = ledger(bk, s, row, p, "", title="1. 원장(상각 · 취득 · 처분 줄, 엔진 분류 = 아래 표의 SUMIFS 조건)")
    row = s.section(row, "2. 자산 묶음별 상각범위액과 시부인")
    X.note(s.ws, row, "노란 칸: 상각방법(정액 · 정률) · 내용연수 · 기초 부인누계 · 정액 기준 취득가액 · 시부인(적용 · 보류)")
    row += 1
    X.header(s.ws, row, COLS)
    row += 1
    col = {name: i + 1 for i, name in enumerate(COLS)}
    c = {name: L(i) for name, i in col.items()}
    g_first = row
    d = p.defaults

    def sumifs(code, label, sign=1):
        f = f'SUMIFS($G${first}:$G${last},$C${first}:$C${last},"{code}",$H${first}:$H${last},"{label}")'
        return f if sign > 0 else f"-{f}"

    for gr in rows:
        r, g, i = row, gr["group"], gr["i"]

        def inp(name, key, value, kind="text", **kw):
            s.inp(r, col[name], value, pid=p.id, key=f"{key}/{g}", default=d.get(f"{key}/{g}", value), kind=kind, **kw)

        def cell(name):
            return f"{c[name]}{r}"

        s.put(r, col["자산 묶음"], g)
        s.put(r, col["계정"], ", ".join(gr["accounts"]))
        s.put(r, col["20호(4) 열"], gr["form_col"])
        inp("상각방법", "상각방법", gr["method"])
        inp("내용연수", "내용연수", gr["life"] or None, "int", fmt="0")
        s.put(r, col["상각률"], f'=IF(OR({cell("내용연수")}="",{cell("내용연수")}=0),0,'
                               f'VLOOKUP({cell("내용연수")},{R["상각률표"]},IF({cell("상각방법")}="정액",2,3),FALSE))', fmt="0.000")
        s.put(r, col["근거"], gr["basis"])
        s.put(r, col["기초 취득가액"], gr["acquisition_begin"], money=True)
        codes = [gr["asset_code"]]
        s.put(r, col["당기 취득"], "=" + sumifs(gr["asset_code"], "취득"), money=True)
        s.put(r, col["당기 처분"], "=" + sumifs(gr["asset_code"], "처분", -1), money=True)
        s.put(r, col["기말 취득가액"], gr["acquisition"], money=True)
        s.put(r, col["기초 누계액"], gr["accum_begin"], money=True)
        contra = gr["contra_codes"]
        s.put(r, col["처분 누계"], "=" + ("+".join(sumifs(k, "처분 누계") for k in contra) if contra else "0"), money=True)
        s.put(r, col["회사계상 상각비"], "=" + "".join(sumifs(k, "상각", -1) for k in codes + contra), money=True)
        s.put(r, col["기말 누계액"], gr["accum_end"], money=True)
        inp("기초 부인누계", "기초 부인누계", gr["reserve_begin"], "int", money=True)
        s.put(r, col["월할 취득액"], gr["additions_monthly"], money=True)
        inp("정액 기준 취득가액", "정액 기준 취득가액", gr["acq_base"], "int", money=True)
        unamort = (f'{cell("기초 취득가액")}-{cell("기초 누계액")}+{cell("기초 부인누계")}'
                   f'-({cell("당기 처분")}-{cell("처분 누계")})')
        s.put(r, col["상각 기초가액"], f'=IF({cell("상각방법")}="정액",{cell("정액 기준 취득가액")},{unamort}+{cell("월할 취득액")})', money=True)
        s.put(r, col["세무상 미상각잔액"], f'=MAX(0,{unamort}+{cell("당기 취득")})', money=True)
        s.put(r, col["상각범위액(계산)"], f'=IF({cell("상각률")}=0,0,MIN({cell("세무상 미상각잔액")},'
                                       f'ROUNDDOWN({cell("상각 기초가액")}*{cell("상각률")},0)))', money=True)
        inp("시부인", "시부인", APPLY if gr["apply"] else HOLD)
        on = f'{cell("시부인")}="{APPLY}"'
        s.put(r, col["상각범위액(서식)"], f'=IF({on},{cell("상각범위액(계산)")},{cell("회사계상 상각비")})', money=True)
        s.put(r, col["상각부인액"], f'=IF({on},MAX(0,{cell("회사계상 상각비")}-{cell("상각범위액(계산)")}),0)', money=True)
        s.put(r, col["시인부족액"], f'=IF({on},MAX(0,{cell("상각범위액(계산)")}-{cell("회사계상 상각비")}),0)', money=True)
        s.put(r, col["기왕부인액 추인"], f'=MIN({cell("시인부족액")},MAX(0,{cell("기초 부인누계")}))', money=True)
        s.put(r, col["기말 부인누계"], f'={cell("기초 부인누계")}+{cell("상각부인액")}-{cell("기왕부인액 추인")}', money=True)
        s.put(r, col["차이(회사계상 - 계산)"], f'={cell("회사계상 상각비")}-{cell("상각범위액(계산)")}', money=True)
        for name, key in JSON_KEY.items():
            bk.reg(p.id, f"g{i}.{key}", s.addr(r, col[name]))
        row += 1
    if not rows:
        s.put(row, 1, "유형 · 무형자산 계정이 없습니다")
        row += 1
    g_last = row - 1
    row += 1
    row = s.section(row, "3. 합계와 금액 검증")
    tot_rows = [("dep_company", "회사계상 상각비 합계", "회사계상 상각비"), ("limit", "상각범위액(서식) 합계", "상각범위액(서식)"),
                ("excess", "상각부인액 합계(가산 · 유보)", "상각부인액"), ("shortfall", "시인부족액 합계", "시인부족액"),
                ("reversal", "기왕부인액 추인 합계(차감 · 유보)", "기왕부인액 추인"),
                ("reserve_begin", "기초 부인누계 합계", "기초 부인누계"), ("reserve_end", "기말 부인누계 합계", "기말 부인누계")]
    for key, label, name in tot_rows:
        s.put(row, 1, label)
        s.put(row, 7, f"=SUM({c[name]}{g_first}:{c[name]}{max(g_first, g_last)})", money=True)
        bk.reg(p.id, f"totals.{key}", s.addr(row, 7))
        if key == "dep_company":
            dep_at = row
        row += 1
    exp_first = row
    for a in p.accounts:
        s.put(row, 1, f"재무제표 {a['name']}({a['code']})")
        s.put(row, 7, int(a.get("amount") or 0), money=True)
        row += 1
    s.put(row, 1, "상각비 계정 합계 - 회사계상 상각비 합계")
    s.put(row, 7, f"=SUM(G{exp_first}:G{max(exp_first, row - 1)})-G{dep_at}" if p.accounts else f"=-G{dep_at}", money=True)
    row += 2
    grants = p.extra.get("grants") or []
    if grants:
        row = s.section(row, "3-1. 보조금 유보 처분 추인")
        X.note(s.ws, row, "처분 전표가 지운 보조금 차감 계정 금액의 비율로 전기 유보를 추인합니다. 노란 칸이 추인액입니다")
        row += 1
        for gr in grants:
            for label, v in ((f"{gr['subject']} 기초 유보(전기 50호(을))", gr["기초유보"]), ("처분 전표의 보조금 계정 차변", gr["처분 보조금"]),
                             ("보조금 기초 잔액 + 당기 수령", gr["보조금 기초 + 수령"])):
                s.put(row, 1, label)
                s.put(row, 7, v, money=True)
                row += 1
            s.put(row, 1, "처분 비율")
            s.put(row, 7, f"=IF(AND(G{row - 1}>0,G{row - 2}>0),MIN(1,G{row - 2}/MAX(1,G{row - 1})),0)", fmt="0.00%")
            row += 1
            s.put(row, 1, "추인액 계산(|기초 유보| × 비율)")
            s.put(row, 7, f"=ROUNDDOWN(ABS(G{row - 4})*G{row - 1},0)", money=True)
            row += 1
            s.put(row, 1, "전기 유보 추인액(노란 칸)")
            s.inp(row, 7, p.inputs[gr["key"]], pid=p.id, key=gr["key"], default=p.defaults.get(gr["key"], 0), kind="int", money=True)
            bk.reg(p.id, gr["key"], s.addr(row, 7))
            row += 2
    row = adj_table(bk, s, row, p, "4. 세무조정 · 소득처분")
    items = []
    for gr in rows:
        form = "20_1" if gr["method"] == "정액" else "20_2"
        items += [(form, f"{gr['group']} 상각범위액", f"g{gr['i']}.limit"), (form, f"{gr['group']} 회사계상액", f"g{gr['i']}.dep_company")]
    items += [("20_4", "(105) 회사손비계상액 합계", "totals.dep_company"), ("20_4", "(106) 상각부인액 합계", "totals.excess"),
              ("20_4", "(108) 기왕부인액 중 당기손금추인액 합계", "totals.reversal")]
    row = forms_table(bk, s, row, p, items)
    notes(s, row, p)
