"""13 수입배당금: 내국법인 수입배당금액 익금불산입(법인세법 제18조의2, 16호의2).

익금불산입액 = Σ(배당금액 × 익금불산입률) - Σ(차입금 이자 × 주식 장부가액 적수 ÷ 자산총액 적수 × 익금불산입률), 0 보다 작으면 0.
익금불산입률은 출자비율 50% 이상 100%, 20% 이상 80%, 20% 미만 30%(2025 사업연도 표, 상장 여부는 묻지 않는다).
배당기준일 전 3개월 이내에 취득한 주식의 배당은 빼고, 출자비율은 3개월 이상 계속 보유한 주식으로 센다(시행령 제17조의2 제1항).

장부에는 지분율 · 보유기간이 없다. 그래서 배당 지급법인마다 노란 칸(지분율 · 3개월 이상 보유 · 대상 여부 · 주식 장부가액)을
두고, **기본값으로는 조정을 넣지 않는다**. 지분율을 넣기 전에는 「지분율을 넣으면 X원」 을 보인다.
배당 지급법인 이름은 적요(「보이스아이 배당금」 처럼)에서, 없으면 거래처에서 읽는다. 은행 · 증권 계좌번호나 「만기」 가 든
줄은 펀드 분배금으로 보아 대상 여부를 X 로 둔다(집합투자기구 이익분배금은 피출자법인 배당에 들지 않는다).
"""
from __future__ import annotations

import re

from ... import xlsx as X
from ..books import Books, frac, rate, rd
from ..model import Adj, LineRow, Paper
from ..sheet import Book, Rows, adj_table, forms_table, head, ledger, notes

NAME = "수입배당금"
FORMS = ["16의2", "15"]
LEDGER_CHECK = False

DIV_ACCOUNT = re.compile(r"배당금수익|수입배당|배당수익|배당금")
STRIP = re.compile(r"(현금)?배당(금수익|금|수익|소득)?|수령|입금|분배금|중간|결산|기말")
ACCOUNT_NO = re.compile(r"\d{2,}-\d{2,}-\d{2,}|\d{8,}")
FUND = re.compile(r"만기|펀드|신탁|분배|수익증권|MMF|ETF", re.I)
INTEREST = re.compile(r"이자비용|지급이자|사채이자")


def basis(rates: dict) -> list[tuple]:
    d = rates["dividend"]
    t = d["rate_table"]
    rows = []
    for (low, rt), label in zip(t["value"], ("50% 이상", "20% 이상", "20% 미만")):
        rows.append((f"수입배당금 출자비율 하한({label})", low, t["basis"], t["grade"], "0%"))
        rows.append((f"수입배당금 익금불산입률({label})", rt, t["basis"], t["grade"], "0%"))
    for key, name in (("holding_months", "수입배당금 보유기간(개월)"), ("listed", "수입배당금 상장 여부")):
        rows.append((name, d[key]["value"], d[key]["basis"], d[key]["grade"], None))
    return rows


def payer_of(memo: str, partner: str) -> str:
    """배당 지급법인 이름: 적요에서 배당 · 수령 같은 말을 뺀 것, 계좌번호뿐이면 거래처."""
    name = STRIP.sub("", memo or "").strip(" -_/()'")
    if not name or ACCOUNT_NO.search(name) or len(name) < 2:
        return (partner or memo or "지급법인 미상").strip()
    return name


def bracket(share: float, table) -> float:
    for low, rt in table:
        if share >= low and share > 0:
            return rt
    return 0


def compute(p: Paper, b: Books) -> None:
    accts = [a for a in b.accounts(cls="수익") if DIV_ACCOUNT.search(a["name"]) and "지분법" not in a["name"]]
    p.accounts = accts
    table = rate(b.rates, "dividend", "rate_table")
    payers: dict[str, dict] = {}
    for ln in b.lines_of(accts):
        amt = ln.credit - ln.debit
        name = payer_of(ln.memo, ln.partner)
        fund = bool(ACCOUNT_NO.search(ln.memo) or FUND.search(ln.memo))
        p.lines.append(LineRow(ln, name, "", why="펀드 분배금으로 보임(계좌번호 · 만기)" if fund else ""))
        e = payers.setdefault(name, {"payer": name, "배당금액": 0, "fund": False, "lines": 0, "partner": ln.partner})
        e["배당금액"] += amt
        e["fund"] = e["fund"] or fund
        e["lines"] += 1
    interest_default = sum(int(a.get("amount") or 0) for a in b.accounts(cls="비용") if INTEREST.search(a["name"]))
    interest = p.take(b, "차입금 이자", interest_default, "int")
    assets = p.take(b, "자산총액", int(b.totals.get("assets") or 0), "int")
    rows = []
    for i, e in enumerate(sorted(payers.values(), key=lambda x: -x["배당금액"])):
        n = e["payer"]
        share = p.take(b, f"지분율/{n}", 0.0, "ratio")
        hold = p.take(b, f"3개월 이상 보유/{n}", "O", "pick")
        target = p.take(b, f"대상 여부/{n}", "X" if e["fund"] else "O", "pick")
        listed = p.take(b, f"상장 여부/{n}", "", "text")
        book = p.take(b, f"주식 장부가액/{n}", 0, "int")
        D = e["배당금액"]
        r = bracket(share, table) if hold == "O" and target == "O" else 0
        base = rd(D * frac(r))
        excl = rd(interest * frac(r) * book / assets) if assets > 0 and r else 0
        rows.append({"i": i, "payer": n, "partner": e["partner"], "배당금액": D, "지분율": share, "보유": hold,
                     "대상": target, "상장": listed, "장부가액": book, "익금불산입률": float(r), "대상금액": base,
                     "배제금액": excl, "익금불산입액": base - excl, "fund": e["fund"],
                     "가정30": rd(D * frac(table[2][1])), "가정80": rd(D * frac(table[1][1])), "가정100": rd(D * frac(table[0][1]))})
    total = max(0, sum(r_["익금불산입액"] for r_ in rows))
    p.values = {"rows": rows, "배당금수익": sum(r_["배당금액"] for r_ in rows), "차입금 이자": interest, "자산총액": assets,
                "대상금액": sum(r_["대상금액"] for r_ in rows), "배제금액": sum(r_["배제금액"] for r_ in rows),
                "익금불산입": total}
    p.extra["rows"] = rows
    p.adjustments = [Adj("차감", "수입배당금", total, "기타", "수입배당금 익금불산입",
                         "내국법인 수입배당금액 익금불산입(법인세법 제18조의2)", "익금불산입")]
    claimed = [r_ for r_ in rows if r_["익금불산입률"]]
    for r_ in rows:
        n = r_["payer"]
        if r_["fund"] and f"대상 여부/{n}" not in p.overridden:
            p.notes.append(f"{n} {r_['배당금액']:,}원: 적요에 계좌번호 · 만기가 있어 펀드 분배금으로 보고 대상에서 뺐습니다(대상 여부 X)")
        elif not r_["지분율"]:
            p.confirm.append(f"{n} 배당 {r_['배당금액']:,}원: 지분율을 넣으면 20% 미만 {r_['가정30']:,}원 · 20% 이상 "
                             f"{r_['가정80']:,}원 · 50% 이상 {r_['가정100']:,}원 익금불산입(지급이자 차감 전)입니다. "
                             "지분율 · 3개월 이상 보유 여부를 노란 칸에 넣으세요")
    if claimed and interest and not any(r_["장부가액"] for r_ in claimed):
        p.confirm.append(f"차입금 이자 {interest:,}원이 있어 지급이자 관련 배제금액을 빼야 합니다. 지급법인 주식의 장부가액(일별 잔액 평균)을 "
                         "노란 칸에 넣으세요(시행령 제17조의2 제3항)")
    if rows:
        p.notes.append("익금불산입률은 출자비율로만 정합니다(50% 이상 100%, 20% 이상 80%, 20% 미만 30%). 상장 여부 칸은 기록용입니다")
    p.settle(bool(rows))


def _rate_formula(R: dict, share: str, hold: str, target: str) -> str:
    lo1, lo2 = R["수입배당금 출자비율 하한(50% 이상)"], R["수입배당금 출자비율 하한(20% 이상)"]
    r1, r2, r3 = (R[f"수입배당금 익금불산입률({k})"] for k in ("50% 이상", "20% 이상", "20% 미만"))
    return (f'=IF(OR({hold}<>"O",{target}<>"O",{share}<=0),0,'
            f'IF({share}>={lo1},{r1},IF({share}>={lo2},{r2},{r3})))')


def write(bk: Book, p: Paper) -> None:
    s = head(bk, p)
    row = 5
    row = s.section(row, "1. 계정")
    X.header(s.ws, row, ["코드", "계정", "", "", "", "", "금액"], col=1)
    row += 1
    for a in p.accounts:
        s.put(row, 1, a["code"])
        s.put(row, 2, a["name"])
        s.put(row, 7, int(a.get("amount") or 0), money=True)
        row += 1
    if not p.accounts:
        s.put(row, 2, "배당금수익 계정이 없습니다")
        row += 1
    row += 1
    row, _, _ = ledger(bk, s, row, p, "", title="2. 원장 검토(엔진 분류 = 배당 지급법인)")
    R = bk.ref
    row = s.section(row, "3. 지급법인별 익금불산입")
    X.note(s.ws, row, "노란 칸: 지분율(예 0.1105) · 3개월 이상 보유(O · X) · 대상 여부(O · X) · 상장 여부(기록용) · 주식 장부가액")
    row += 1
    r = Rows(bk, s, p, row)
    g = r.g
    r.put("차입금 이자", "차입금 이자(손익계산서 이자비용)", p.inputs["차입금 이자"], kind="input", input_kind="int")
    r.put("자산총액", "자산총액(사업연도 종료일 재무상태표)", p.inputs["자산총액"], kind="input", input_kind="int")
    for e in p.extra["rows"]:
        i, n = e["i"], e["payer"]
        r.row = s.section(r.row + 1, f"3-{i + 1}. {n}")
        r.put(f"{i}.배당금액", "배당금액", e["배당금액"])
        r.put(f"지분율/{n}", "지분율(노란 칸, 모르면 0)", p.inputs[f"지분율/{n}"], kind="input", input_kind="ratio", fmt="0.00%")
        r.put(f"3개월 이상 보유/{n}", "배당기준일 현재 3개월 이상 보유(O · X)", p.inputs[f"3개월 이상 보유/{n}"], kind="input",
              input_kind="pick", fmt="@")
        r.put(f"대상 여부/{n}", "익금불산입 대상(O · X, 펀드 분배금 등은 X)", p.inputs[f"대상 여부/{n}"], kind="input",
              input_kind="pick", fmt="@")
        r.put(f"상장 여부/{n}", "피출자법인 상장 여부(기록용)", p.inputs[f"상장 여부/{n}"] or None, kind="input", input_kind="text",
              fmt="@")
        r.put(f"주식 장부가액/{n}", "주식 장부가액(적수 ÷ 일수)", p.inputs[f"주식 장부가액/{n}"], kind="input", input_kind="int")
        r.put(f"{i}.익금불산입률", "익금불산입률",
              _rate_formula(R, g(f"지분율/{n}"), g(f"3개월 이상 보유/{n}"), g(f"대상 여부/{n}")), fmt="0%")
        r.put(f"{i}.대상금액", "익금불산입 대상금액(배당 × 율)", f"=ROUNDDOWN({g(f'{i}.배당금액')}*{g(f'{i}.익금불산입률')},0)")
        r.put(f"{i}.배제금액", "지급이자 관련 배제금액(이자 × 율 × 장부가액 ÷ 자산총액)",
              f"=IF(OR({g('자산총액')}<=0,{g(f'{i}.익금불산입률')}=0),0,ROUNDDOWN({g('차입금 이자')}*{g(f'{i}.익금불산입률')}"
              f"*{g(f'주식 장부가액/{n}')}/{g('자산총액')},0))")
        r.put(f"{i}.익금불산입액", "익금불산입액(대상 - 배제)", f"={g(f'{i}.대상금액')}-{g(f'{i}.배제금액')}")
        r.put(f"{i}.가정30", "지분율 20% 미만이면(30%)", f"=ROUNDDOWN({g(f'{i}.배당금액')}*{R['수입배당금 익금불산입률(20% 미만)']},0)")
        r.put(f"{i}.가정80", "지분율 20% 이상이면(80%)", f"=ROUNDDOWN({g(f'{i}.배당금액')}*{R['수입배당금 익금불산입률(20% 이상)']},0)")
        r.put(f"{i}.가정100", "지분율 50% 이상이면(100%)", f"=ROUNDDOWN({g(f'{i}.배당금액')}*{R['수입배당금 익금불산입률(50% 이상)']},0)")
    rows = p.extra["rows"]
    r.row = s.section(r.row + 1, f"3-{len(rows) + 1}. 합계")
    r.put("배당금수익", "배당금액 합계", "=" + ("+".join(g(f"{e['i']}.배당금액") for e in rows) or "0"))
    r.put("대상금액", "익금불산입 대상금액 합계", "=" + ("+".join(g(f"{e['i']}.대상금액") for e in rows) or "0"))
    r.put("배제금액", "지급이자 관련 배제금액 합계", "=" + ("+".join(g(f"{e['i']}.배제금액") for e in rows) or "0"))
    r.put("익금불산입", "익금불산입액(0 보다 작으면 0, 차감 · 기타)", f"=MAX(0,{g('대상금액')}-{g('배제금액')})")
    row = adj_table(bk, s, r.row + 1, p, title=f"3-{len(rows) + 2}. 세무조정 · 소득처분")
    row = forms_table(bk, s, row, p, [("16의2", "⑬ 배당금액 계", "배당금수익"), ("16의2", "⑮ 익금불산입 대상금액 계", "대상금액"),
                                      ("16의2", "⑯ 지급이자 관련 배제금액 계", "배제금액"), ("16의2", "⑰ 익금불산입액 계", "익금불산입")])
    notes(s, row, p)
