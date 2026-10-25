"""6 기업업무추진비: 신용카드 등 미사용액 · 한도초과 손금불산입(기타사외유출). 23호(갑)(을)."""
from __future__ import annotations

from fractions import Fraction

from ..books import EVIDENCE, GIFT, Books, frac, rate, rd
from ..model import Adj, LineRow, Paper, subject_of
from ..sheet import Book, Rows, adj_table, forms_table, head, ledger, lines_dry, notes, verify, verify_rows

NAME = "기업업무추진비"
FORMS = ["23갑", "23을"]
LEDGER_CHECK = True
PICK = "부인 여부"
# 23호(갑) ⑨ 문화 · ⑪ 전통시장 · ⑫ 지역사랑상품권 · ⑬ 온누리상품권 기업업무추진비 지출액(노란 칸 key = values key)
SPENT = ("문화 지출액", "전통시장 지출액", "지역사랑상품권 지출액", "온누리상품권 지출액")


def basis(rates: dict) -> list[tuple]:
    ent = rates["entertainment"]
    rows = [("기업업무추진비 기본한도(중소기업)", ent["base_sme"]["value"], ent["base_sme"]["basis"], ent["base_sme"]["grade"], None),
            ("기업업무추진비 기본한도(일반)", ent["base_general"]["value"], ent["base_general"]["basis"], ent["base_general"]["grade"], None)]
    for i, (cap, rt) in enumerate(ent["revenue_tiers"]["value"], start=1):
        if cap is not None:
            rows.append((f"수입금액 구간{i} 상한", cap, ent["revenue_tiers"]["basis"], ent["revenue_tiers"]["grade"], None))
        rows.append((f"수입금액 구간{i} 비율", rt, ent["revenue_tiers"]["basis"], ent["revenue_tiers"]["grade"], "0.00%"))
    rows.append(("특수관계인 수입금액 비율", ent["related_party_ratio"]["value"], ent["related_party_ratio"]["basis"],
                 ent["related_party_ratio"]["grade"], "0%"))
    for name, key, fmt in (("문화 기업업무추진비 한도율", "culture_ratio", "0%"),
                           ("전통시장 등 기업업무추진비 한도율", "market_ratio", "0%"),
                           ("온누리상품권 한도 적용(1 · 0)", "onnuri_applies", "0")):
        rows.append((name, ent[key]["value"], ent[key]["basis"], ent[key]["grade"], fmt))
    return rows


def tier_limit(revenue: int, tiers) -> int:
    """수입금액 기준 한도(법인세법 제25조 제4항 제2호 표)."""
    (c1, r1), (c2, r2), (_, r3) = tiers
    x = max(revenue, 0)
    if x <= c1:
        v = x * frac(r1)
    elif x <= c2:
        v = c1 * frac(r1) + (x - c1) * frac(r2)
    else:
        v = c1 * frac(r1) + (c2 - c1) * frac(r2) + (x - c2) * frac(r3)
    return rd(v)


def compute(p: Paper, b: Books) -> None:
    accts = b.accounts(cls="비용", any_of=("접대비", "기업업무추진비"))
    p.accounts = accts
    g_lim = rate(b.rates, "entertainment", "card_threshold_general")
    gift_lim = rate(b.rates, "entertainment", "card_threshold_gift")
    for ln in b.lines_of(accts):
        amt, text = ln.amount, ln.text
        if amt <= 0:
            p.lines.append(LineRow(ln, "취소 · 음수 줄", "X"))
        elif GIFT.search(text):
            if amt > gift_lim:
                p.lines.append(LineRow(ln, "경조금 20만원 초과", "O", why="경조금은 20만원 초과분이 적격증빙 없으면 손금불산입(시행령 제41조)"))
            else:
                p.lines.append(LineRow(ln, "경조금 20만원 이하", "X"))
        elif amt > g_lim and not EVIDENCE.search(text) and ln.kind == "출금":
            p.lines.append(LineRow(ln, "3만원 초과 현금 지출", "O", why="적요에 카드 · 계산서 표시가 없고 현금 출금 전표입니다"))
        elif amt > g_lim and not EVIDENCE.search(text):
            p.lines.append(LineRow(ln, "증빙 표시 없음", "X", why="적요에 카드 · 계산서 표시가 없습니다. 증빙을 확인하세요"))
        else:
            p.lines.append(LineRow(ln, "신용카드 등", "X"))
    p.take_lines(b, PICK)
    total = sum(r.line.amount for r in p.lines)
    no_card = sum(r.line.amount for r in p.lines if r.pick == "O")
    sme = b.sme
    months = b.months
    base_amt = rate(b.rates, "entertainment", "base_sme" if sme else "base_general")
    base = rd(Fraction(base_amt * months, 12))
    revenue = p.take(b, "수입금액", int(b.totals.get("revenue") or 0), "int")
    related = p.take(b, "특수관계인 수입금액", 0, "int")
    # 23호(갑) ⑨ · ⑪ · ⑫ · ⑬ 지출액은 장부 계정으로 가릴 수 없어 노란 칸(기본 0)
    spent = {k: p.take(b, k, 0, "int") for k in SPENT}
    tiers = rate(b.rates, "entertainment", "revenue_tiers")
    lim_total = tier_limit(revenue, tiers)
    lim_general = tier_limit(revenue - related, tiers)
    rev_limit = lim_general + rd((lim_total - lim_general) * frac(rate(b.rates, "entertainment", "related_party_ratio")))
    general = base + rev_limit                                                       # ⑧
    culture = min(spent["문화 지출액"], rd(general * frac(rate(b.rates, "entertainment", "culture_ratio"))))   # ⑩
    onnuri_in = spent["온누리상품권 지출액"] * int(rate(b.rates, "entertainment", "onnuri_applies"))
    market = min(spent["전통시장 지출액"] + spent["지역사랑상품권 지출액"] + onnuri_in,
                 rd(general * frac(rate(b.rates, "entertainment", "market_ratio"))))   # ⑭
    limit = general + culture + market                                              # ⑮
    net = total - no_card
    excess = max(0, net - limit)
    p.values = {"해당금액": total, "신용카드미사용": no_card, "차감해당금액": net, "기본한도": base,
                "수입금액": revenue, "수입금액기준한도": rev_limit, "일반한도": general, **spent,
                "문화한도": culture, "전통시장등한도": market, "한도": limit, "한도초과": excess,
                "손금산입한도내": min(net, limit)}
    subj = subject_of(accts, "기업업무추진비")
    p.adjustments = [
        Adj("가산", subj, no_card, "기타사외유출", "기업업무추진비 신용카드 미사용",
            "기업업무추진비 신용카드 등 미사용액 손금불산입", "신용카드미사용"),
        Adj("가산", subj, excess, "기타사외유출", "기업업무추진비 한도초과", "기업업무추진비 한도초과액 손금불산입", "한도초과"),
    ]
    p.notes.append("한도 계산의 수입금액은 손익계산서 매출액을 썼습니다(특수관계인 매출 구분 확인 필요)")
    if not any(spent.values()):
        p.notes.append("문화 · 전통시장 · 지역사랑상품권 · 온누리상품권 기업업무추진비 지출액은 장부로 가릴 수 없어 0 으로 두었습니다"
                       "(조특법 제136조 제3항 · 제6항, 해당하면 노란 칸에 지출액을 넣으세요)")
    if spent["온누리상품권 지출액"] and not onnuri_in:
        p.confirm.append("온누리상품권 기업업무추진비는 2026.5.12 이 속하는 과세연도 지출분부터 한도에 더합니다(법률 제21612호 부칙 제4조)."
                         " 이 사업연도 한도 계산에서는 뺐습니다(23호(갑) ⑬ 에는 적음)")
    if sum(spent.values()) > net:
        p.confirm.append(f"문화 · 전통시장 등 지출액 합계 {sum(spent.values()):,}원이 ③ 차감 해당금액 {net:,}원보다 큽니다"
                         "(23호(갑) 작성방법 4 · 5: ③ 가운데 지출액)")
    if not b.sme_known:
        p.confirm.append("전기 신고서에서 중소기업 여부를 읽지 못해 중소기업으로 보았습니다")
    p.settle(bool(total or accts))


def _tier(x: str, c1: str, r1: str, c2: str, r2: str, r3: str) -> str:
    return (f"ROUNDDOWN(IF({x}<={c1},{x}*{r1},IF({x}<={c2},{c1}*{r1}+({x}-{c1})*{r2},"
            f"{c1}*{r1}+({c2}-{c1})*{r2}+({x}-{c2})*{r3})),0)")


def write(bk: Book, p: Paper) -> None:
    s = head(bk, p)
    row = 5
    _, first, last = lines_dry(p, row + verify_rows(p))
    row = verify(bk, s, row, p, first, last)
    row, first, last = ledger(bk, s, row, p, PICK)
    R = bk.ref
    row = s.section(row, "3. 한도 시부인")
    r = Rows(bk, s, p, row)
    g = r.g
    r.put("해당금액", "① 기업업무추진비 해당금액", f"=SUM(G{first}:G{last})")
    r.put("신용카드미사용", "② 신용카드 등 미사용액(부인 여부 O)", f'=SUMIFS(G{first}:G{last},I{first}:I{last},"O")')
    r.put("차감해당금액", "③ 차감 해당금액(① - ②)", f"={g('해당금액')}-{g('신용카드미사용')}")
    r.put("월수", "사업연도 월수", f"={R['사업연도 월수']}", fmt="0")
    r.put("기본한도", "④ 기본한도(중소기업 3,600만원 · 일반 1,200만원 × 월수/12)",
          f'=ROUNDDOWN(IF({R["중소기업 여부"]}="여",{R["기업업무추진비 기본한도(중소기업)"]},{R["기업업무추진비 기본한도(일반)"]})*{g("월수")}/12,0)')
    r.put("수입금액", "수입금액(손익계산서 매출액)", p.inputs["수입금액"], kind="input", input_kind="int")
    r.put("특수관계인 수입금액", "특수관계인 수입금액", p.inputs["특수관계인 수입금액"], kind="input", input_kind="int")
    r.put("일반수입금액", "일반 수입금액", f"={g('수입금액')}-{g('특수관계인 수입금액')}")
    t = (R["수입금액 구간1 상한"], R["수입금액 구간1 비율"], R["수입금액 구간2 상한"], R["수입금액 구간2 비율"], R["수입금액 구간3 비율"])
    r.put("총수입금액기준", "⑤ 총수입금액 기준", "=" + _tier(g("수입금액"), *t))
    r.put("일반수입금액기준", "⑥ 일반수입금액 기준", "=" + _tier(g("일반수입금액"), *t))
    r.put("수입금액기준한도", "수입금액 기준 한도(⑥ + (⑤ - ⑥) × 10%)",
          f"={g('일반수입금액기준')}+ROUNDDOWN(({g('총수입금액기준')}-{g('일반수입금액기준')})*{R['특수관계인 수입금액 비율']},0)")
    r.put("일반한도", "⑧ 일반 기업업무추진비 한도액(④ + ⑥ + ⑦)", f"={g('기본한도')}+{g('수입금액기준한도')}")
    labels = {"문화 지출액": "⑨ 문화 기업업무추진비 지출액", "전통시장 지출액": "⑪ 전통시장 기업업무추진비 지출액",
              "지역사랑상품권 지출액": "⑫ 지역사랑상품권 기업업무추진비 지출액",
              "온누리상품권 지출액": "⑬ 온누리상품권 기업업무추진비 지출액(2026.5.12 이 속하는 과세연도 지출분부터 한도에 더함)"}
    r.put("문화 지출액", labels["문화 지출액"], p.inputs["문화 지출액"], kind="input", input_kind="int")
    r.put("문화한도", "⑩ 문화 기업업무추진비 한도액(⑨ 와 ⑧ × 20% 중 적은 금액)",
          f"=MIN({g('문화 지출액')},ROUNDDOWN({g('일반한도')}*{R['문화 기업업무추진비 한도율']},0))")
    for key in SPENT[1:]:
        r.put(key, labels[key], p.inputs[key], kind="input", input_kind="int")
    r.put("전통시장등한도", "⑭ 전통시장 · 지역사랑상품권 · 온누리상품권 한도액(⑪ + ⑫ + ⑬ 과 ⑧ × 20% 중 적은 금액)",
          f"=MIN({g('전통시장 지출액')}+{g('지역사랑상품권 지출액')}+{g('온누리상품권 지출액')}*{R['온누리상품권 한도 적용(1 · 0)']},"
          f"ROUNDDOWN({g('일반한도')}*{R['전통시장 등 기업업무추진비 한도율']},0))")
    r.put("한도", "⑮ 기업업무추진비 한도액 합계(⑧ + ⑩ + ⑭)", f"={g('일반한도')}+{g('문화한도')}+{g('전통시장등한도')}")
    r.put("한도초과", "⑯ 한도초과액", f"=MAX(0,{g('차감해당금액')}-{g('한도')})")
    r.put("손금산입한도내", "⑰ 손금산입 한도 내 지출액", f"=MIN({g('차감해당금액')},{g('한도')})")
    row = adj_table(bk, s, r.row + 1, p)
    row = forms_table(bk, s, row, p, [("23갑", "① 기업업무추진비 해당금액", "해당금액"),
                                      ("23갑", "② 신용카드 등 미사용 손금불산입액", "신용카드미사용"),
                                      ("23갑", "⑧ 일반 기업업무추진비 한도액", "일반한도"),
                                      ("23갑", "⑮ 한도액 합계", "한도"), ("23갑", "⑯ 한도초과액", "한도초과"),
                                      ("23을", "신용카드 등 미사용액", "신용카드미사용")])
    notes(s, row, p)
