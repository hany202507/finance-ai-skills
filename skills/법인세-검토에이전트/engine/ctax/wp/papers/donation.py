"""8 기부금: 비지정기부금 손금불산입(기타사외유출), 특례 · 일반 한도초과는 15호가 아니라 3호 05. 21호 · 22호.

계산이 두 번이다. `compute` 가 원장 줄을 분류하고, 15호 합계가 나온 뒤 `finish` 가 한도를 잰다(기준소득금액이 차가감소득금액을 쓴다).
엑셀도 한도 부분은 3호 · 결손금 시트가 생긴 뒤 `write_after` 가 쓴다.

한도는 21호(2026.3.20 개정) 산식 그대로다. 전기에서 넘어온 한도초과액(5절)은 노란 줄(사업연도 · 종류 · ㉑ · ㉒)로 받고
④ · ⑭ 한도 안에서 해당 사업연도 지출액보다 먼저, 먼저 생긴 것부터 손금에 넣는다(법인세법 제24조 제5항 · 제6항).
노란 줄의 기본값은 전기 신고서 21호 5절 ㉕ · 6절 ㉘ 차기이월액(전기.json rows["21"], `prior_carry`)이고, 회계사가 노란 칸에
넣은 값이 있으면 그 값이 이긴다.
⑤ = MIN(④, 특례 ㉓ 합계), ⑮ = MIN(⑭, 일반 ㉓ 합계), ⑤ + ⑮ 는 3호 (106) 기본값이다. ⑭ 율은 사회적기업이면 따로다(작성방법 8).

전기 신고서 15호에 기부금 손금불산입 줄(`prior_denied`)이 있으면 확인 줄에 전기 금액 · 처분 · 조정내용과 전기 손익계산서 기부금 ·
당기 기부금 합계를 적는다. 당기 원장 줄 가운데 어느 줄이 비지정기부금(법인세법 제24조 제4항)인지는 엔진이 정하지 않는다(분류 노란 칸).
전기에 비지정기부금이 있었는데 당기 비지정 합계가 0 이면 그 확인 줄을 맨 앞에 둔다.
"""
from __future__ import annotations

import re

from ... import xlsx as X
from ..books import DONATION_NONDESIG, DONATION_SPECIAL, Books, frac, rate, rd
from ..model import Adj, LineRow, Paper, subject_of
from ..sheet import Book, Rows, adj_table, calc_row, forms_table, head, ledger, lines_dry, local, notes, verify, verify_rows

NAME = "기부금"
FORMS = ["21", "22"]
LEDGER_CHECK = True
PICK = "분류"
KINDS = ("특례", "일반", "비지정")
CARRY_ROWS = 6          # 이월 기부금 노란 줄 수(21호 5절, 사업연도 · 종류마다 한 줄)
CARRY_KINDS = ("특례", "일반")
CARRY_YEARS = 10        # 법인세법 제24조 제5항: 다음 사업연도 개시일부터 10년 이내에 끝나는 사업연도


def basis(rates: dict) -> list[tuple]:
    don = rates["donation"]
    return [("특례기부금 한도 비율", don["special_ratio"]["value"], don["special_ratio"]["basis"], don["special_ratio"]["grade"], "0%"),
            ("일반기부금 한도 비율", don["general_ratio"]["value"], don["general_ratio"]["basis"], don["general_ratio"]["grade"], "0%"),
            ("사회적기업 일반기부금 한도 비율", don["social_enterprise_ratio"]["value"], don["social_enterprise_ratio"]["basis"],
             don["social_enterprise_ratio"]["grade"], "0%")]


def _year(v) -> int:
    s = "".join(ch for ch in str(v or "") if ch.isdigit())[:4]
    return int(s) if len(s) == 4 else 0


def _int(v) -> int:
    try:
        return int(round(float(v or 0)))
    except (TypeError, ValueError):
        return 0


def prior_carry(b: Books) -> list[dict]:
    """전기 신고서 21호(전기.json rows["21"], ctax prior)의 차기이월액 → 당기 5절 이월 줄 기본값 [{사업연도, 종류, 21, 22, from}].
    전기 5절 줄은 ㉕차기이월액이 남은 것(㉑ 그대로, ㉒ = ㉑ - ㉕ 곧 전기까지 공제한 금액), 전기 6절 줄은 ㉘차기 이월액(㉑ = ㉘,
    ㉒ = 0, 사업연도가 비면 전기 사업연도). 특례 · 일반만, 먼저 생긴 것부터. 2026. 3. 20. 개정 서식으로 낸 신고서는 그 사업연도
    한도초과액을 5절과 6절에 함께 적기도 해서, 사업연도 · 종류가 같은 5절 줄이 있으면 6절 줄은 넣지 않는다."""
    prior = b.prior or {}
    out, seen = [], set()
    rows = (prior.get("rows") or {}).get("21") or []
    for r in sorted(rows, key=lambda r: r.get("절") or 0):
        kind = r.get("종류")
        if kind not in CARRY_KINDS:
            continue
        year = str(_year(r.get("사업연도")) or _year(prior.get("fy")) or "")
        if r.get("절") == 5:
            seen.add((year, kind))
        if r.get("절") == 5 and _int(r.get("25")) > 0:
            excess = _int(r.get("21")) or _int(r.get("22")) + _int(r.get("23"))
            out.append({"사업연도": year, "종류": kind, "21": excess, "22": max(excess - _int(r["25"]), 0),
                        "from": "전기 21호 5절 ㉕"})
        elif r.get("절") == 6 and _int(r.get("28")) > 0 and (year, kind) not in seen:
            out.append({"사업연도": year, "종류": kind, "21": _int(r["28"]), "22": 0, "from": "전기 21호 6절 ㉘"})
    return sorted(out, key=lambda r: (_year(r["사업연도"]), CARRY_KINDS.index(r["종류"])))


# 전기 22호 「그 밖의 기부금」(코드 50) 적요와 당기 기부금 줄 잇기(10-20). AR prior_donation_other 도 같은 함수를 쓴다.
OTHER_CODES = ("50",)
OTHER_KINDS = ("기타", "그밖", "그 밖")
GENERIC = {"기부금", "후원금", "성금", "지원금", "찬조금", "협찬금", "발전기금", "회비"}


def memo_core(text: str) -> str:
    """적요의 알맹이. 빈칸 · 괄호(닫히지 않은 것 포함) · 앞의 「7월」 · 「2024년」 · 끝 수량 표기를 지운다."""
    s = re.sub(r"\s+", "", str(text or ""))
    s = re.sub(r"\([^)]*\)?", "", s)
    s = re.sub(r"^(\d{2,4}년)?(\d{1,2}월분?)?", "", s)
    return re.sub(r"[\d,X×\-]+$", "", s)


def prior_other(prior: dict | None) -> list[dict]:
    """전기 22호 줄 가운데 그 밖의 기부금(코드 50 · 유형 「기타」)이고 적요 알맹이가 네 글자 이상이며 흔한 이름이 아닌 줄."""
    out = []
    for r in ((prior or {}).get("rows") or {}).get("22") or []:
        if str(r.get("코드") or "") not in OTHER_CODES and str(r.get("유형") or "") not in OTHER_KINDS:
            continue
        core = memo_core(r.get("적요"))
        if len(core) >= 4 and core not in GENERIC:
            out.append({**r, "core": core})
    return out


def match_prior_other(text: str, rows: list[dict]) -> dict | None:
    """당기 기부금 줄 글(거래처 · 적요)이 전기 그 밖의 기부금 줄의 적요 알맹이를 품으면 그 전기 줄."""
    t = re.sub(r"\s+", "", str(text or ""))
    for r in rows:
        if r["core"] in t:
            return r
    return None


def prior_denied(b: Books) -> list[dict]:
    """전기 신고서 15호의 기부금 가산 줄(손금불산입) [{amount, disposition, note, kind}]. 과목이나 조정내용에 「기부금」 이 있는 줄.
    kind: 조정내용 · 과목에 「비지정」 이 있으면 비지정, 「한도초과」 가 있으면 한도초과, 둘 다 없고 처분이 유보면 유보, 나머지는
    비지정 추정(기타사외유출 등으로 처분했는데 한도초과라고 적지 않은 줄)."""
    out = []
    for a in (b.prior or {}).get("adjustments", []) or []:
        text = re.sub(r"\s", "", f"{a.get('subject') or ''} {a.get('note') or ''}")
        amount = _int(a.get("amount"))
        if a.get("side") != "가산" or "기부금" not in text or not amount:
            continue
        disp = a.get("disposition") or ""
        if "비지정" in text:
            kind = "비지정"
        elif "한도초과" in text:
            kind = "한도초과"
        elif disp == "유보":
            kind = "유보"
        else:
            kind = "비지정 추정"
        out.append({"amount": amount, "disposition": disp, "note": (a.get("note") or "").strip(), "kind": kind})
    return out


def _prior_text(r: dict) -> str:
    note = f", 조정내용 「{r['note']}」" if r["note"] else ""
    return f"{r['amount']:,}원({r['disposition'] or '처분 미상'}{note})"


def prior_confirm(p: Paper, b: Books, accts: list[dict], total: int, nd: int) -> None:
    """전기 15호 기부금 손금불산입 줄을 확인 줄에 적는다. 전기에 비지정기부금이 있었는데 당기 비지정 합계가 0 이면 맨 앞에 둔다."""
    rows = prior_denied(b)
    known = [a for a in accts if a.get("prior_known") is not False]
    prior_is = sum(_int(a.get("prior_amount")) for a in known)
    p.values["전기 15호 기부금"] = rows
    p.values["전기손익기부금"] = prior_is
    if not rows:
        return
    is_text = f"전기 손익계산서 기부금은 {prior_is:,}원" if known or not accts else "전기 손익계산서 기부금은 장부에서 알 수 없고"
    nondesig = [r for r in rows if r["kind"] in ("비지정", "비지정 추정")]
    label = "비지정기부금 손금불산입" if all(r["kind"] == "비지정" for r in nondesig) else "기부금 손금불산입"
    if nondesig and not total:
        p.notes.append(f"전기 신고서 15호에 {label} " + ", ".join(_prior_text(r) for r in nondesig) +
                       "이 있었습니다. 당기 기부금 계정에는 금액이 없습니다")
    elif nondesig:
        text = (f"전기 신고서 15호에 {label} " + ", ".join(_prior_text(r) for r in nondesig) + f"이 있습니다. {is_text}, "
                f"당기 기부금 합계는 {total:,}원이고 당기 비지정기부금은 {nd:,}원입니다. 당기 원장 줄 가운데 어느 줄이 비지정기부금인지는 "
                f"엔진이 정하지 않았습니다. 해당하는 줄의 노란 칸 「{PICK}」 를 「비지정」 으로 바꾸십시오(법인세법 제24조 제4항)")
        if nd:
            p.confirm.append(text)
        else:
            p.confirm.insert(0, "당기 비지정기부금을 0원으로 두었습니다. " + text)
    for r in rows:
        if r["kind"] == "한도초과":
            p.confirm.append(f"전기 신고서 15호에 기부금 한도초과 손금불산입 {_prior_text(r)}이 있습니다. {is_text}, 당기 기부금 합계는 "
                             f"{total:,}원입니다. 한도초과액은 당기 21호에서 다시 계산해 3호 05 란에 넣습니다. 전기에서 넘어온 금액은 "
                             "3-2 이월 줄과 맞는지 확인하십시오")
        elif r["kind"] == "유보":
            p.confirm.append(f"전기 신고서 15호에 기부금 손금불산입 {_prior_text(r)}이 있습니다. {is_text}, 당기 기부금 합계는 "
                             f"{total:,}원입니다. 당기에 이어지는 조정이 있는지 확인하십시오(엔진은 조정하지 않았습니다)")


def _carry_text(r: dict) -> str:
    return f"{r['사업연도']} {r['종류']} {r['21'] - r['22']:,}원"


def carry_inputs(p: Paper, b: Books) -> list[dict]:
    """이월 기부금 노란 줄. 기본값은 전기 21호 5절 ㉕ · 6절 ㉘ 차기이월액(prior_carry)을 사업연도 · 종류마다 넣은 것이고,
    회계사가 노란 칸에 넣은 값이 있으면 그 값을 쓴다."""
    prior = prior_carry(b)
    p.extra["prior_carry"] = prior
    rows = []
    for n in range(1, CARRY_ROWS + 1):
        d = prior[n - 1] if n <= len(prior) else {}
        year = p.take(b, f"이월 {n}/사업연도", d.get("사업연도", ""), "year")
        kind = p.take(b, f"이월 {n}/종류", d.get("종류", ""))
        excess = p.take(b, f"이월 {n}/한도초과 손금불산입액", d.get("21", 0), "int")
        used = p.take(b, f"이월 {n}/기공제액", d.get("22", 0), "int")
        rows.append({"n": n, "사업연도": year, "종류": kind, "21": excess, "22": used, "23": excess - used, "24": 0,
                     "25": excess - used})
    if len(prior) > CARRY_ROWS:
        rest = prior[CARRY_ROWS:]
        p.confirm.append(f"전기 21호 이월 기부금 줄이 {len(prior)}개라 노란 줄 {CARRY_ROWS}개에 다 넣지 못했습니다. 넣지 못한 "
                         f"{len(rest)}줄({', '.join(_carry_text(r) for r in rest)})은 "
                         "직접 조정 등으로 반영하십시오")
    return rows


def allocate(rows: list[dict], kind: str, amount: int) -> None:
    """손금산입액을 먼저 생긴 이월액부터 나눈다(법인세법 제24조 제6항). 같은 사업연도면 줄 차례."""
    left = amount
    for r in sorted((r for r in rows if r["종류"] == kind), key=lambda r: (_year(r["사업연도"]), r["n"])):
        r["24"] = max(0, min(r["23"], left))
        left -= r["24"]
        r["25"] = r["23"] - r["24"]


def compute(p: Paper, b: Books) -> None:
    """기부금 분류와 비지정 기부금 조정. 한도는 15호 합계가 나온 뒤 `finish` 가 채운다."""
    accts = b.accounts(cls="비용", any_of=("기부금",))
    p.accounts = accts
    others = prior_other(b.prior)
    for ln in b.lines_of(accts):
        text = ln.text
        hit = match_prior_other(text, others) if ln.amount > 0 else None
        if hit:
            p.lines.append(LineRow(ln, "비지정 추정(전기 22호)", "비지정",
                                   why=f"전기 22호 그 밖의 기부금 「{hit['적요']}」 과 같은 적요"))
        elif DONATION_NONDESIG.search(text):
            p.lines.append(LineRow(ln, "비지정 추정", "비지정", why=f"「{DONATION_NONDESIG.search(text).group(0)}」"))
        elif DONATION_SPECIAL.search(text):
            p.lines.append(LineRow(ln, "특례 추정", "특례", why=f"「{DONATION_SPECIAL.search(text).group(0)}」"))
        else:
            p.lines.append(LineRow(ln, "일반 추정", "일반", why="받는 곳 이름으로 가리지 못해 일반기부금으로 두었습니다"))
    p.take_lines(b, PICK, kind="text")
    sp = sum(r.line.amount for r in p.lines if r.pick == "특례")
    gen = sum(r.line.amount for r in p.lines if r.pick == "일반")
    nd = sum(r.line.amount for r in p.lines if r.pick == "비지정")
    social = p.take(b, "사회적기업 여부", "부")
    carry = carry_inputs(p, b)
    p.extra["carry"] = carry
    p.values = {"기부금합계": sp + gen + nd, "특례기부금": sp, "일반기부금": gen, "비지정기부금": nd,
                "사회적기업": 1 if social == "여" else 0}
    p.adjustments = [Adj("가산", subject_of(accts, "기부금"), nd, "기타사외유출", "비지정기부금 손금불산입",
                         "비지정기부금 손금불산입", "비지정기부금")]
    odd = [r for r in p.lines if r.pick not in KINDS]
    if odd:
        p.confirm.append(f"분류 칸이 특례 · 일반 · 비지정이 아닌 줄 {len(odd)}개는 어느 합계에도 넣지 않았습니다")
    unconfirmed = [r for r in p.lines if f"{PICK}/{r.key}" not in p.overridden]
    if unconfirmed:
        p.confirm.append("기부금 분류(특례 · 일반 · 비지정)는 받는 곳 이름으로 추정했습니다. 영수증의 단체 종류로 확인하세요")
    if social not in ("여", "부"):
        p.confirm.append(f"노란 칸 「사회적기업 여부」 값 「{social}」 을 읽지 못해 사회적기업이 아닌 것으로 보았습니다(여 · 부)")
    prior_confirm(p, b, accts, sp + gen + nd, nd)
    carried = [r for r in p.lines if r.label == "비지정 추정(전기 22호)"]
    if carried:
        p.confirm.append(f"전기 22호에서 그 밖의 기부금(코드 50)으로 적은 적요와 같은 당기 줄 {len(carried)}개 "
                         f"{sum(r.line.amount for r in carried):,}원을 분류 기본값 「비지정」 으로 두었습니다. 기부처가 일반기부금 단체로 "
                         "바뀌었으면 분류 칸을 고치십시오(법인세법 제24조 제4항)")
    live = [r for r in carry if r["21"] or r["22"]]
    fy = _year(b.fy)
    for r in live:
        if r["종류"] not in CARRY_KINDS:
            p.confirm.append(f"이월 {r['n']} 줄 종류 「{r['종류']}」 가 특례 · 일반이 아니라 이월 손금산입에서 뺐습니다")
        if not r["사업연도"]:
            p.confirm.append(f"이월 {r['n']} 줄 사업연도가 비어 있어 가장 먼저 생긴 이월액으로 보았습니다")
        elif fy and fy - _year(r["사업연도"]) > CARRY_YEARS:
            p.confirm.append(f"이월 {r['n']} 줄({r['사업연도']} 사업연도)은 10년이 지났을 수 있습니다(법인세법 제24조 제5항). "
                             "공제 기간이 끝났으면 줄을 지우세요")
        if r["22"] > r["21"]:
            p.confirm.append(f"이월 {r['n']} 줄 기공제액이 한도초과 손금불산입액보다 큽니다")
    prior = p.extra.get("prior_carry") or []
    if live:
        p.notes.append(f"이월 기부금 {len(live)}줄(노란 칸)을 ④ · ⑭ 한도 안에서 먼저 생긴 것부터 손금에 넣었습니다(법인세법 제24조 제6항)")
    if prior:
        p.notes.append(f"이월 기부금 노란 줄 기본값은 전기 신고서 21호 차기이월액 {len(prior)}줄입니다(" +
                       ", ".join(_carry_text(r) for r in prior) +
                       "). 다르면 노란 칸을 고치십시오")
    elif "21" in ((b.prior or {}).get("rows") or {}):
        p.notes.append("전기 신고서 21호에 차기이월 기부금이 없습니다(5절 ㉕ · 6절 ㉘)")
    elif not live and (sp + gen + nd):
        p.notes.append("전기 이월 기부금은 노란 칸 이월 줄에 넣으면 21호 5절과 3호 (106) 에 반영됩니다(넣지 않으면 0)")


def finish(p: Paper, b: Books, flow: dict) -> None:
    """21호 ① ~ ⑳ 과 5절 ㉔. 기준소득금액 = 차가감소득금액 + 특례 + 일반. 결손이면 한도 0, 한도초과는 3호 05 로 간다."""
    income_before, loss_balance = flow["income_before_donation"], flow["loss_balance"]
    sp, gen = p.values["특례기부금"], p.values["일반기부금"]
    carry = p.extra["carry"]
    basis_income = income_before + sp + gen                                                  # ①
    ratio = frac(rate(b.rates, "loss", "sme_ratio" if b.sme else "general_ratio"))
    loss = min(loss_balance, rd(basis_income * ratio)) if basis_income > 0 else 0              # ②
    sp_lim = max(0, rd((basis_income - loss) * frac(rate(b.rates, "donation", "special_ratio"))))   # ④
    sp_left = sum(r["23"] for r in carry if r["종류"] == "특례")                               # 5절 특례 ㉓ 합계
    sp_carry = min(sp_lim, sp_left)                                                          # ⑤
    sp_in = min(max(sp_lim - sp_carry, 0), sp)                                               # ⑥
    rest = max(basis_income - loss - sp_carry - sp_in, 0)                                    # ⑧(⑪ 우리사주 0)
    gen_ratio = rate(b.rates, "donation", "social_enterprise_ratio" if p.values["사회적기업"] else "general_ratio")
    gen_lim = max(0, rd(rest * frac(gen_ratio)))                                             # ⑭
    gen_left = sum(r["23"] for r in carry if r["종류"] == "일반")                              # 5절 일반 ㉓ 합계
    gen_carry = min(gen_lim, gen_left)                                                       # ⑮
    gen_in = min(max(gen_lim - gen_carry, 0), gen)                                           # ⑯
    allocate(carry, "특례", sp_carry)
    allocate(carry, "일반", gen_carry)
    p.values.update({"차가감소득금액": income_before, "기준소득금액": basis_income, "이월결손금": loss,
                     "특례한도": sp_lim, "특례이월잔액": sp_left, "특례이월손금산입": sp_carry,
                     "특례손금산입": sp_in, "특례한도초과": sp - sp_in, "소득금액차감잔액": rest, "일반한도율": gen_ratio,
                     "일반한도": gen_lim, "일반이월잔액": gen_left, "일반이월손금산입": gen_carry,
                     "일반손금산입": gen_in, "일반한도초과": gen - gen_in,
                     "한도초과": (sp - sp_in) + (gen - gen_in), "이월손금산입": sp_carry + gen_carry,
                     "이월": [{k: r[k] for k in ("사업연도", "종류", "21", "22", "23", "24", "25")}
                              for r in carry if (r["21"] or r["22"]) and r["종류"] in CARRY_KINDS],
                     **{f"이월 {r['n']}/손금추인액": r["24"] for r in carry if r["21"] or r["22"]}})
    if basis_income <= 0 and (sp or gen):
        p.notes.append("기준소득금액이 0 이하라 한도가 0 이고, 특례 · 일반 기부금 전액이 한도초과로 3호 05 란에 갑니다(10년 이월)")
    if p.values["사회적기업"]:
        p.notes.append(f"사회적기업이라 ⑭ 일반기부금 한도율을 {gen_ratio:.0%} 로 했습니다(21호 작성방법 8, 법인세법 제24조 제3항 제2호)")
    p.settle(bool(p.values["기부금합계"] or sp_left or gen_left))
    flow["donation_excess"] = p.values["한도초과"]
    flow["donation_carry_in"] = sp_carry + gen_carry


def write(bk: Book, p: Paper) -> None:
    s = head(bk, p)
    row = 5
    _, first, last = lines_dry(p, row + verify_rows(p))
    row = verify(bk, s, row, p, first, last)
    row, first, last = ledger(bk, s, row, p, PICK, kind="text")
    row = s.section(row, "3. 분류 집계")
    row = calc_row(bk, s, row, p, "기부금합계", "기부금 합계", f"=SUM(G{first}:G{last})")
    for key in ("특례기부금", "일반기부금", "비지정기부금"):
        row = calc_row(bk, s, row, p, key, key, f'=SUMIF(I{first}:I{last},"{key[:-3]}",G{first}:G{last})')
    row += 1
    row = adj_table(bk, s, row, p, "3-1. 세무조정 · 소득처분(비지정기부금)")
    row = _carry_table(bk, s, row, p)
    p.extra["limit_row"] = row
    p.extra["sheet"] = s


def _carry_table(bk: Book, s, row: int, p: Paper) -> int:
    """3-2. 이월 기부금 노란 줄(21호 5절). ㉔ 손금추인액 수식은 한도 계산 뒤 `write_after` 가 건다."""
    row = s.section(row, "3-2. 전기 이월 기부금(21호 5절, 기본값은 전기 신고서 21호 5절 ㉕ · 6절 ㉘ 차기이월액, 다르면 노란 칸을 고침)")
    X.header(s.ws, row, ["줄", "사업연도", "종류(특례 · 일반)", "㉑한도초과 손금불산입액", "㉒기공제액",
                           "㉓공제가능 잔액(㉑-㉒)", "㉔해당사업연도 손금추인액", "㉕차기이월액(㉓-㉔)", "차례"])
    row += 1
    first = row
    for r in p.extra["carry"]:
        n = r["n"]
        s.put(row, 1, f"이월 {n}")
        year = r["사업연도"]
        s.inp(row, 2, int(year) if str(year).isdigit() else (year or None), pid=p.id, key=f"이월 {n}/사업연도",
              default=p.defaults.get(f"이월 {n}/사업연도") or None, kind="year", fmt="0")
        s.inp(row, 3, r["종류"] or None, pid=p.id, key=f"이월 {n}/종류", default=p.defaults.get(f"이월 {n}/종류") or None)
        s.inp(row, 4, r["21"], pid=p.id, key=f"이월 {n}/한도초과 손금불산입액",
              default=p.defaults.get(f"이월 {n}/한도초과 손금불산입액", 0), kind="int", money=True)
        s.inp(row, 5, r["22"], pid=p.id, key=f"이월 {n}/기공제액", default=p.defaults.get(f"이월 {n}/기공제액", 0),
              kind="int", money=True)
        s.put(row, 6, f"=D{row}-E{row}", money=True)
        s.put(row, 9, f'=IF(B{row}="",0,B{row})*100+{n}', fmt="0")      # 먼저 생긴 것부터 나누는 차례(사업연도 · 줄)
        bk.reg(p.id, f"이월 {n}/손금추인액", s.addr(row, 7))
        row += 1
    p.extra["carry_rows"] = (first, row - 1)
    return row + 1


def write_after(bk: Book, p: Paper) -> None:
    """한도 계산은 3호 · 결손금 시트가 생긴 뒤에 건다."""
    s = p.extra.pop("sheet")
    R, cells = bk.ref, bk.cells
    row = s.section(p.extra.pop("limit_row"), "3-3. 한도 계산(21호, 한도초과는 15호가 아니라 3호 05)")
    r = Rows(bk, s, p, row)
    g = r.g
    c1, c2 = p.extra["carry_rows"]
    kinds, left = f"C{c1}:C{c2}", f"F{c1}:F{c2}"
    sp, gen = local(cells[p.id]["특례기부금"]), local(cells[p.id]["일반기부금"])
    r.put("차가감소득금액", "차가감소득금액(3호 04)", f"={cells['tax_3']['04']}")
    r.put("기준소득금액", "① 기준소득금액(차가감소득 + 특례 + 일반)", f"={g('차가감소득금액')}+{sp}+{gen}")
    r.put("이월결손금잔액", "이월결손금 잔액(결손금 시트)", f"={cells['loss']['이월결손금기초']}")
    r.put("이월결손금", "② 한도 계산에서 빼는 이월결손금",
          f"=IF({g('기준소득금액')}>0,MIN({g('이월결손금잔액')},ROUNDDOWN({g('기준소득금액')}*{cells['loss']['공제율']},0)),0)")
    r.put("특례한도", "④ 특례기부금 한도(× 50%)", f"=MAX(0,ROUNDDOWN(({g('기준소득금액')}-{g('이월결손금')})*{R['특례기부금 한도 비율']},0))")
    r.put("특례이월잔액", "특례기부금 이월 잔액(5절 특례 ㉓ 합계)", f'=SUMIF({kinds},"특례",{left})')
    r.put("특례이월손금산입", "⑤ 이월잔액 중 손금산입액 MIN(④, ㉓)", f"=MIN({g('특례한도')},{g('특례이월잔액')})")
    r.put("특례손금산입", "⑥ 해당연도 특례기부금 손금산입", f"=MIN(MAX({g('특례한도')}-{g('특례이월손금산입')},0),{sp})")
    r.put("특례한도초과", "⑦ 특례기부금 한도초과", f"={sp}-{g('특례손금산입')}")
    r.put("소득금액차감잔액", "⑧ 소득금액 차감잔액(① - ② - ⑤ - ⑥)",
          f"=MAX({g('기준소득금액')}-{g('이월결손금')}-{g('특례이월손금산입')}-{g('특례손금산입')},0)")
    r.put("사회적기업 여부", "사업연도 종료일 현재 사회적기업(여 · 부)", p.inputs["사회적기업 여부"], kind="input")
    r.put("일반한도율", "⑭ 한도율(사회적기업이면 따로, 작성방법 8)",
          f'=IF({g("사회적기업 여부")}="여",{R["사회적기업 일반기부금 한도 비율"]},{R["일반기부금 한도 비율"]})', fmt="0%")
    r.put("일반한도", "⑭ 일반기부금 한도(⑧ × 율)", f"=MAX(0,ROUNDDOWN({g('소득금액차감잔액')}*{g('일반한도율')},0))")
    r.put("일반이월잔액", "일반기부금 이월 잔액(5절 일반 ㉓ 합계)", f'=SUMIF({kinds},"일반",{left})')
    r.put("일반이월손금산입", "⑮ 이월잔액 중 손금산입액 MIN(⑭, ㉓)", f"=MIN({g('일반한도')},{g('일반이월잔액')})")
    r.put("일반손금산입", "⑯ 해당연도 일반기부금 손금산입", f"=MIN(MAX({g('일반한도')}-{g('일반이월손금산입')},0),{gen})")
    r.put("일반한도초과", "⑰ 일반기부금 한도초과", f"={gen}-{g('일반손금산입')}")
    r.put("한도초과", "⑳ 기부금 한도초과액(3호 05 로 감)", f"={g('특례한도초과')}+{g('일반한도초과')}")
    r.put("이월손금산입", "⑤ + ⑮ 이월 기부금 손금산입(3호 (106) 기본값)",
          f"={g('특례이월손금산입')}+{g('일반이월손금산입')}")
    # 5절 ㉔: 종류별 손금산입액(⑤ · ⑮)을 차례(I 열)가 앞선 줄부터 나눈다
    for i in range(c1, c2 + 1):
        amt = f'IF(C{i}="특례",{g("특례이월손금산입")},IF(C{i}="일반",{g("일반이월손금산입")},0))'
        s.put(i, 7, f'=MAX(0,MIN(F{i},{amt}-SUMIFS(F{c1}:F{c2},C{c1}:C{c2},C{i},I{c1}:I{c2},"<"&I{i})))', money=True)
        s.put(i, 8, f"=F{i}-G{i}", money=True)
    row = forms_table(bk, s, r.row + 1, p, [("21", "③ 특례기부금 해당 금액", "특례기부금"), ("21", "⑤ 이월잔액 중 손금산입액", "특례이월손금산입"),
                                            ("21", "⑬ 일반기부금 해당 금액", "일반기부금"), ("21", "⑮ 이월잔액 중 손금산입액", "일반이월손금산입"),
                                            ("21", "⑳ 한도초과액 합계", "한도초과"), ("3", "05 기부금한도초과액", "한도초과"),
                                            ("3", "(106) 기부금한도초과이월액 손금산입", "이월손금산입")])
    notes(s, row, p)
