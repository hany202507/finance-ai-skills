"""0 법인세비용: 손익계산서 법인세등 손금불산입(기타사외유출), 환급받은 세금 익금불산입(기타).

환급 줄 찾기(4회차). 장부에서 세금을 돌려받아 이익으로 적은 줄을 가려 15호 차감(기타)으로 넣는다. 줄마다 노란 「익금불산입」.

  법인세등 계정 환급   법인세등 계정의 대변 줄 중 적요에 환급 · 경정 · 과오납. 15호는 가산(계상액 + 환급) · 차감(환급)
                       두 줄로 나눈다(합은 손익계산서 법인세등과 같다). 법인세법 제18조 제3호                       O
  법인세 환급          수익 계정 줄 중 적요 · 거래처에 법인세 + 환급 · 경정 · 과오납. 과목 「법인세등」. 제18조 제3호    O
  지방소득세 환급      수익 계정 줄 중 지방소득세 + 환급. 과목 「법인세등」. 제18조 제3호(법인지방소득세)               O
  지방세 환급          수익 계정 줄 중 지방세 + 환급(세목이 없음). 법인세 환급 합의 10%(±1%)면 법인지방소득세로      O · X
                       보고 O, 아니면 재산세 등 손금이었던 세금의 환급일 수 있어 X(확인 필요)
  환급가산금           환급 + 가산금 · 가산이자. 과목 「환급가산금」. 제18조 제4호                                      O
                       10-25: 「환급」 없이 세목 + 가산이자 · 환급이자(「지방세 가산이자」 · 「국세 가산이자」)도 같다.
                       수익 계정 대변에 적은 세목의 가산이자는 과오납금 환급금 이자다. 낸 가산금 · 가산세는 비용이라 대상이 아니다
  관세 환급가산금      위에 관세가 붙은 줄. 관세는 국세기본법 국세 목록에 없어 X(확인 필요)                              X
  부가세 환급          수익 계정 줄 중 부가세 · 부가가치세 + 환급 · 경정, 1,000원 이상. 과목은 그 수익 계정 이름.         O
                       낼 때 손금이 아니었던 세액이라 익금이 아니다(제18조 제5호 · 제21조 제1호 적용, ★★☆).
                       불공제 매입세액을 비용으로 처리했다가 돌려받은 것이면 익금이라 회계사 확인 목록에 남긴다

적요에 「단수」 · 「절사」 가 있는 줄, 금액이 0 이하인 줄은 후보가 아니다. 판단은 노란 칸이 정한다.

순액 이자 원천세(fx3). 선납세금 계정 없이 이자 · 배당을 원천세를 뺀 순액으로 적고 적요에 「이자세금:1,540원」 처럼 원천세를 남긴
줄. 원천세만큼 수익이 빠졌고 기납부세액에도 없다. 원천세를 익금산입(기타사외유출)하고 3호 24 원천납부세액으로 뺄지는 회계 판단이라
노란 칸 「원천세 익금산입」 기본 X 와 확인 줄(넣으면 얼마)만 둔다. O 로 고치면 15호 가산 줄이 생기고 3호 24 · 지방소득세
특별징수 기본값에 법인세 · 지방소득세 몫이 더해진다(summary.prepaid_rows).
"""
from __future__ import annotations

import re
from types import SimpleNamespace

from ... import xlsx as X
from ..books import Books
from ..model import Adj, LineRow, Paper, line_keys, subject_of
from ..sheet import Book, Rows, adj_table, forms_table, head, ledger, lines_dry, notes, verify, verify_rows

NAME = "법인세비용"
FORMS = ["15", "3"]
LEDGER_CHECK = False     # 법인세등 계정 금액 = 원장 합계 검사는 compute 가 p.checks 에 넣는다(환급 표 줄은 다른 계정이라)
PICK = "익금불산입"

REFUND = re.compile(r"환급|경정|과오납")
NOT_REFUND = re.compile(r"단수|절사")
INTEREST = re.compile(r"가산금|가산이자|환급이자")
VAT = re.compile(r"부가세|부가가치세")
LOCAL_INCOME = re.compile(r"지방소득세")
LOCAL_TAX = re.compile(r"지방세")
CORP = re.compile(r"법인세")
CUSTOMS = re.compile(r"관세")
# 「환급」 없이 적은 환급금 이자(10-25 「지방세 가산이자」). 세목 바로 뒤 가산이자 · 환급이자만 본다(「가산금」 은 낸 돈일 수 있어 뺀다)
TAX_INTEREST = re.compile(r"(국세|지방세|지방소득세|법인세|부가세|부가가치세|재산세|취득세|관세)\s*(가산이자|환급이자)")
VAT_MIN = 1000           # 이보다 작은 부가세 줄은 단수 차이로 보고 후보에서 뺀다(잡손실 「단수 차이 추정」 과 같은 값)

ACCT_REFUND = "법인세등 계정 환급"
CORP_REFUND, LOCAL_REFUND, LOCAL_TAX_REFUND = "법인세 환급", "지방소득세 환급", "지방세 환급"
REFUND_INTEREST, CUSTOMS_INTEREST, VAT_REFUND = "환급가산금", "관세 환급가산금", "부가세 환급"
TAX_KINDS = (ACCT_REFUND, CORP_REFUND, LOCAL_REFUND, LOCAL_TAX_REFUND)        # 15호 과목 「법인세등」
INTEREST_SUBJECT = "환급가산금"

NET_PICK = "원천세 익금산입"
NET_LABEL = "순액 이자 원천세"
NET_ACCTS = ("이자수익", "이자수입", "배당금수익", "배당금수입", "배당수익")
# 적요에 남긴 원천세 금액(「이자세금:1,540원」 · 「원천세 1,540」). 숫자는 10원 이상만
NET_TAX = re.compile(r"(?:이자세금|이자소득세|원천징수세액|원천징수|원천세|세금)\s*[:：=]?\s*(\d[\d,]*)\s*원?")


def basis(rates: dict) -> list[tuple]:
    r = rates["corporate_tax"]
    out = [(name, r[k]["value"], r[k]["basis"], r[k]["grade"], None)
           for name, k in (("익금불산입: 법인세 환급", "refund_excluded"), ("익금불산입: 환급가산금", "refund_interest_excluded"),
                           ("익금불산입: 부가세 환급", "vat_refund_excluded"))]
    t = rates.get("prepaid_tax") or {}
    out += [(name, t[k]["value"], t[k]["basis"], t[k]["grade"], None)
            for name, k in (("기납부세액: 중간예납 납부 달", "interim_months"), ("기납부세액: 15.4% 한 줄 나눔", "withholding_split"),
                            ("순액 이자 원천세", "net_interest")) if k in t]
    return out


def classify_refund(text: str, tax_account: bool) -> tuple[str, str, str] | None:
    """환급 후보 줄 하나 → (엔진 분류, 익금불산입 기본값, 근거). 후보가 아니면 None. 지방세 환급의 10% 판정은 compute 가 한다."""
    if NOT_REFUND.search(text) or not (REFUND.search(text) or (not tax_account and TAX_INTEREST.search(text))):
        return None
    if tax_account:
        return ACCT_REFUND, "O", "법인세등 계정 대변의 환급 줄. 손금불산입한 법인세의 환급(법인세법 제18조 제3호)"
    if INTEREST.search(text):
        if CUSTOMS.search(text):
            return (CUSTOMS_INTEREST, "X", "관세 환급가산금. 관세는 국세기본법 제2조 국세 목록에 없어 넣지 않았습니다. "
                    "법인세법 제18조 제4호로 보면 O")
        return REFUND_INTEREST, "O", "국세 · 지방세 과오납금 환급가산금(법인세법 제18조 제4호)"
    if VAT.search(text):
        return (VAT_REFUND, "O", "부가세 환급. 낼 때 손금이 아니었던 세액이라 익금불산입(제18조 제5호 · 제21조 제1호 적용). "
                "비용으로 처리한 세액의 환급이면 X")
    if LOCAL_INCOME.search(text):
        return LOCAL_REFUND, "O", "법인지방소득세 환급(법인세법 제18조 제3호)"
    if CORP.search(text):
        return CORP_REFUND, "O", "법인세 환급(법인세법 제18조 제3호)"
    if LOCAL_TAX.search(text):
        return LOCAL_TAX_REFUND, "X", "세목을 적요로 알 수 없는 지방세 환급"
    return None


def _refund_rows(b: Books, tax_accts: list[dict]) -> list[LineRow]:
    """환급 후보 줄. 법인세등 계정의 대변 줄과 매출이 아닌 수익 계정의 대변 줄을 본다. 금액은 환급액(대변 - 차변, 양수)."""
    tax_codes = {a["code"] for a in tax_accts}
    revenue = [a for a in b.accounts(cls="수익") if "매출" not in (a.get("section") or "")]
    rows = []
    for ln in b.lines_of(tax_accts + revenue):
        if ln.credit - ln.debit <= 0:
            continue
        got = classify_refund(ln.text, ln.account in tax_codes)
        if got and got[0] == VAT_REFUND and ln.credit - ln.debit < VAT_MIN:
            continue
        if got:
            rows.append(LineRow(ln, got[0], got[1], why=got[2]))
    corp = sum(r.line.credit - r.line.debit for r in rows if r.label in (CORP_REFUND, ACCT_REFUND))
    for r in rows:
        if r.label == LOCAL_TAX_REFUND:
            amt = r.line.credit - r.line.debit
            if corp and abs(amt * 10 - corp) <= corp // 100:
                r.pick = "O"
                r.why = f"법인세 환급 합 {corp:,}원의 10%라 법인지방소득세 환급으로 보았습니다(법인세법 제18조 제3호)"
            else:
                r.why += ". 법인지방소득세면 O, 재산세 등 손금이었던 세금의 환급이면 X"
    return rows


def net_interest_rows(b: Books) -> list[LineRow]:
    """이자 · 배당 수익 대변 줄 중 적요에 원천세 금액이 있고 같은 전표에 선납세금이 없는 줄(원천세를 뺀 순액 계상 후보).
    LineRow.why 에 원천세 금액을 글로 두지 않고 extra 로 넘긴다. 금액은 적요의 원천세(LineRow 는 원장 줄 그대로)."""
    from ..summary import PREPAID_ACCTS, split_withheld
    prepaid = {a["code"] for a in b.accounts(cls="자산", any_of=PREPAID_ACCTS)}
    with_prepaid = {(ln.date, ln.no) for ln in b.lines if ln.account in prepaid}
    out = []
    for ln in b.lines_of(b.accounts(cls="수익", any_of=NET_ACCTS)):
        net = ln.credit - ln.debit
        m = NET_TAX.search(ln.memo)
        if net <= 0 or not m or (ln.date, ln.no) in with_prepaid:
            continue
        tax = int(m.group(1).replace(",", ""))
        if tax < 10 or tax >= net:
            continue
        gross = net + tax
        corp, rate_ = split_withheld(tax, gross)
        r = LineRow(ln, NET_LABEL, "X", why=f"적요의 원천세 {tax:,}원. 순액 {net:,}원 + 원천세 = 이자 {gross:,}원")
        r.extra = {"tax": tax, "gross": gross, "corp": corp, "local": tax - corp, "rate": rate_}   # type: ignore[attr-defined]
        out.append(r)
    return out


def compute(p: Paper, b: Books) -> None:
    accts = b.accounts(cls="비용", any_of=("법인세",))
    p.accounts = accts
    p.lines = [LineRow(ln, "법인세등", "") for ln in b.lines_of(accts)]
    fs_tax = int(b.totals.get("corporate_tax") or 0)
    ledger_sum = sum(r.line.amount for r in p.lines)
    if accts:
        fs = sum(int(a.get("amount") or 0) for a in accts)
        p.checks.append({"id": f"{p.id}_ledger", "ok": fs == ledger_sum, "title": f"{p.sheet} 재무제표 = 분개장",
                         "left": fs, "right": ledger_sum})

    refunds = _refund_rows(b, accts)
    line_keys_for(refunds)
    for r in refunds:
        r.default = r.pick
        r.pick = p.take(b, f"{PICK}/{r.key}", r.pick, "pick")
        p.inputs.pop(f"{PICK}/{r.key}", None)           # 줄 칸 기본값은 inputs 에 두지 않는다(take_lines 와 같게)
        p.defaults.pop(f"{PICK}/{r.key}", None)
    p.extra["refunds"] = refunds

    nets = net_interest_rows(b)
    line_keys_for(nets)
    for r in nets:
        r.default = r.pick
        r.pick = p.take(b, f"{NET_PICK}/{r.key}", r.pick, "pick")
        p.inputs.pop(f"{NET_PICK}/{r.key}", None)
        p.defaults.pop(f"{NET_PICK}/{r.key}", None)
    p.extra["nets"] = nets
    net_o = [r for r in nets if r.pick == "O"]
    # 3호 24 · 지방소득세 특별징수 기본값에 더할 줄(summary.prepaid_rows 의 extra)
    p.extra["net_interest_rows"] = [
        {"date": r.line.date, "no": r.line.no, "account": b.by_code.get(r.line.account, {}).get("name") or r.line.account_name,
         "partner": r.line.partner, "memo": r.line.memo, "interest": r.extra["gross"], "amount": r.extra["tax"],
         "법인세": r.extra["corp"], "지방소득세": r.extra["local"], "rate": r.extra["rate"]} for r in net_o]

    def amt(r):
        return r.line.credit - r.line.debit

    def picked(*labels):
        return sum(amt(r) for r in refunds if r.pick == "O" and r.label in labels)

    acct_refund = picked(ACCT_REFUND)
    corp_refund = picked(CORP_REFUND, LOCAL_REFUND, LOCAL_TAX_REFUND)
    interest = picked(REFUND_INTEREST, CUSTOMS_INTEREST)
    vat = picked(VAT_REFUND)
    gross = fs_tax + acct_refund
    add = max(gross, 0)
    ded = acct_refund + corp_refund + max(-gross, 0)
    p.values = {"법인세등": fs_tax, "분개장 합계": ledger_sum, "법인세등 계정 환급": acct_refund, "손금불산입": add,
                "수익 계정 법인세 환급": corp_refund, "익금불산입": ded, "환급가산금 익금불산입": interest,
                "부가세 환급 익금불산입": vat, "환급 후보": sum(amt(r) for r in refunds),
                "순액 이자 원천세 후보": sum(r.extra["tax"] for r in nets),
                "순액 이자 원천세 익금산입": sum(r.extra["tax"] for r in net_o)}
    subj = subject_of(accts, "법인세등")
    net_subj = (b.by_code.get(net_o[0].line.account, {}).get("name") or net_o[0].line.account_name) if net_o else "이자수익"
    vat_rows = [r for r in refunds if r.label == VAT_REFUND and r.pick == "O"]
    vat_subj = (b.by_code.get(vat_rows[0].line.account, {}).get("name") or vat_rows[0].line.account_name) if vat_rows else "잡이익"
    p.adjustments = [
        Adj("가산", subj, add, "기타사외유출", "법인세비용 손금불산입", "당기 법인세등 계상액 손금불산입", "손금불산입"),
        Adj("차감", subj, ded, "기타", "법인세 환급액 익금불산입", "법인세 · 법인지방소득세 환급액 익금불산입", "익금불산입"),
        Adj("차감", INTEREST_SUBJECT, interest, "기타", "환급가산금 익금불산입", "국세 · 지방세 환급가산금 익금불산입",
            "환급가산금 익금불산입"),
        Adj("차감", vat_subj, vat, "기타", "부가세 환급 익금불산입", "수익으로 적은 부가세 환급액 익금불산입", "부가세 환급 익금불산입"),
        Adj("가산", net_subj, p.values["순액 이자 원천세 익금산입"], "기타사외유출", "순액 이자 원천세 익금산입",
            "원천세를 뺀 순액으로 적은 이자 · 배당의 원천징수세액 익금산입", "순액 이자 원천세 익금산입"),
    ]
    ibt = int(b.totals.get("income_before_tax") or 0)
    if fs_tax == 0 and ibt > 0:
        p.confirm.append(f"법인세차감전이익 {ibt:,}원인데 법인세등이 0원입니다. 미계상이면 결산 수정 여부를 확인하세요")
    _confirm(p, refunds)
    _confirm_nets(p, nets)
    p.notes.append("금액은 손익계산서 법인세등(법인세비용)을 그대로 씁니다. 법인지방소득세를 세금과공과로 처리했다면 그 금액도 더해야 합니다")
    if refunds:
        p.notes.append(f"수익 · 법인세등 계정에서 세금 환급으로 보이는 줄 {len(refunds)}줄 {p.values['환급 후보']:,}원을 찾았습니다. "
                       "노란 칸 O 줄만 익금불산입(기타)합니다")
    p.settle(bool(fs_tax or p.lines or refunds or nets))


def _confirm_nets(p: Paper, nets: list[LineRow]) -> None:
    left = [r for r in nets if r.pick == "X" and f"{NET_PICK}/{r.key}" not in p.overridden]
    if not left:
        return
    tax = sum(r.extra["tax"] for r in left)
    corp = sum(r.extra["corp"] for r in left)
    p.confirm.append(f"이자 · 배당 수익을 원천세를 뺀 순액으로 적은 것으로 보이는 줄 {len(left)}줄(적요의 원천세 {tax:,}원)이 있습니다. "
                     "선납세금 계정이 없어 기납부세액에도 없습니다. 원천세를 익금산입하고 기납부세액으로 뺄지는 회계 판단이라 넣지 "
                     f"않았습니다. 넣으면 15호 가산 {tax:,}원(기타사외유출), 3호 24 원천납부세액 +{corp:,}원, 지방소득세 특별징수 "
                     f"+{tax - corp:,}원입니다(표 2-3 노란 칸 O, 법인세법 제15조 제1항 · 제64조 제1항 제4호)")


def line_keys_for(rows: list[LineRow]) -> None:
    """원장 줄 열쇠(일자|전표|계정|금액). model.line_keys 는 Paper.lines 를 보므로 같은 규칙을 이 목록에 건다."""
    line_keys(SimpleNamespace(lines=rows))


def _confirm(p: Paper, refunds: list[LineRow]) -> None:
    def mine(r):
        return f"{PICK}/{r.key}" not in p.overridden

    vat = [r for r in refunds if r.label == VAT_REFUND and r.pick == "O" and mine(r)]
    if vat:
        p.confirm.append(f"부가세 환급 {len(vat)}줄 {sum(r.line.credit - r.line.debit for r in vat):,}원을 익금불산입했습니다. "
                         "불공제 매입세액처럼 비용으로 처리한 세액을 돌려받은 것이면 익금이니 노란 칸을 X 로 고치세요")
    open_ = [r for r in refunds if r.label in (LOCAL_TAX_REFUND, CUSTOMS_INTEREST) and r.pick == "X" and mine(r)]
    if open_:
        p.confirm.append(f"세목을 알 수 없는 지방세 환급 · 관세 환급가산금 {len(open_)}줄 "
                         f"{sum(r.line.credit - r.line.debit for r in open_):,}원은 익금불산입하지 않았습니다. "
                         "법인지방소득세 환급 · 과오납 환급가산금이면 노란 칸을 O 로 고치세요")


def write(bk: Book, p: Paper) -> None:
    s = head(bk, p)
    row = 5
    _, first, last = lines_dry(p, row + verify_rows(p))
    row = verify(bk, s, row, p, first, last)
    row, first, last = ledger(bk, s, row, p, "")
    row, rf, rl = _refund_table(bk, s, row, p)
    row, nf, nl = _net_table(bk, s, row, p)
    row = s.section(row, "3. 세무조정 계산")
    r = Rows(bk, s, p, row)

    def sumifs(*labels):
        if not labels:
            return "0"
        return "+".join(f'SUMIFS(G{rf}:G{rl},H{rf}:H{rl},"{lb}",I{rf}:I{rl},"O")' for lb in labels)

    r.put("법인세등", "손익계산서 법인세등", p.values["법인세등"], note="장부.json totals.corporate_tax")
    r.put("분개장 합계", "분개장 법인세등 계정 합계", f"=SUM(G{first}:G{last})")
    r.put("법인세등 계정 환급", "법인세등 계정 대변 환급(노란 칸 O)", f"={sumifs(ACCT_REFUND)}")
    r.put("손금불산입", "손금불산입(가산 · 기타사외유출)", f"=MAX({r.g('법인세등')}+{r.g('법인세등 계정 환급')},0)",
          note="환급을 법인세등 계정에서 뺐으면 빼기 전 계상액")
    r.put("수익 계정 법인세 환급", "수익 계정의 법인세 · 지방소득세 환급(노란 칸 O)",
          f"={sumifs(CORP_REFUND, LOCAL_REFUND, LOCAL_TAX_REFUND)}")
    r.put("익금불산입", "법인세 환급액 익금불산입(차감 · 기타)",
          f"={r.g('법인세등 계정 환급')}+{r.g('수익 계정 법인세 환급')}+MAX(-({r.g('법인세등')}+{r.g('법인세등 계정 환급')}),0)",
          note="법인세법 제18조 제3호")
    r.put("환급가산금 익금불산입", "환급가산금 익금불산입(차감 · 기타)", f"={sumifs(REFUND_INTEREST, CUSTOMS_INTEREST)}",
          note="법인세법 제18조 제4호")
    r.put("부가세 환급 익금불산입", "부가세 환급 익금불산입(차감 · 기타)", f"={sumifs(VAT_REFUND)}",
          note="제18조 제5호 · 제21조 제1호 적용(★★☆)")
    r.put("환급 후보", "환급 후보 줄 합계", f"=SUM(G{rf}:G{rl})")
    r.put("순액 이자 원천세 후보", "순액 이자 원천세 후보 줄 합계", f"=SUM(G{nf}:G{nl})")
    r.put("순액 이자 원천세 익금산입", "순액 이자 원천세 익금산입(가산 · 기타사외유출, 노란 칸 O)",
          f'=SUMIFS(G{nf}:G{nl},I{nf}:I{nl},"O")', note="법인세법 제15조 제1항 · 제64조 제1항 제4호(회계 판단)")
    row = adj_table(bk, s, r.row + 1, p)
    row = forms_table(bk, s, row, p, [("15", "익금산입 · 손금불산입 법인세등", "손금불산입"),
                                      ("15", "손금산입 · 익금불산입 법인세등", "익금불산입"),
                                      ("15", "손금산입 · 익금불산입 환급가산금", "환급가산금 익금불산입"),
                                      ("15", "손금산입 · 익금불산입 부가세 환급", "부가세 환급 익금불산입"),
                                      ("15", "익금산입 · 손금불산입 순액 이자 원천세", "순액 이자 원천세 익금산입")])
    notes(s, row, p)


def _net_table(bk: Book, s, row: int, p: Paper) -> tuple[int, int, int]:
    """2-3 순액 이자 원천세 후보 표. 금액(G)은 적요의 원천세, 노란 칸(I)은 원천세 익금산입 O · X, J · K 는 법인세 · 지방소득세 몫."""
    row = s.section(row, f"2-3. 원천세를 뺀 순액 이자 후보(노란 칸 O = {NET_PICK}, 회계 판단)")
    X.header(s.ws, row, ["일자", "전표", "코드", "계정", "거래처", "적요", "원천세", "엔진 분류", NET_PICK, "법인세 몫",
                         "지방소득세 몫", "근거"])
    row += 1
    first = row
    for r in p.extra.get("nets") or []:
        ln = r.line
        s.put(row, 1, ln.date)
        s.put(row, 2, ln.no)
        s.put(row, 3, ln.account)
        s.put(row, 4, bk.b.by_code.get(ln.account, {}).get("name") or ln.account_name)
        s.put(row, 5, ln.partner)
        s.put(row, 6, ln.memo)
        s.put(row, 7, r.extra["tax"], money=True)
        s.put(row, 8, r.label)
        s.inp(row, 9, r.pick, pid=p.id, key=f"{NET_PICK}/{r.key}", default=r.default, kind="pick")
        s.put(row, 10, r.extra["corp"], money=True)
        s.put(row, 11, r.extra["local"], money=True)
        s.put(row, 12, r.why)
        row += 1
    if not p.extra.get("nets"):
        s.put(row, 6, "순액 이자 후보 줄 없음")
        row += 1
    return row + 1, first, row - 1


def _refund_table(bk: Book, s, row: int, p: Paper) -> tuple[int, int, int]:
    """2-2 환급 후보 표. 금액(G)은 환급액(양수), 노란 칸(I)은 익금불산입 O · X, J 는 15호 과목."""
    row = s.section(row, f"2-2. 세금 환급 후보(노란 칸 O = {PICK})")
    X.header(s.ws, row, ["일자", "전표", "코드", "계정", "거래처", "적요", "환급액", "엔진 분류", PICK, "15호 과목", "근거"])
    row += 1
    first = row
    for r in p.extra.get("refunds") or []:
        ln = r.line
        s.put(row, 1, ln.date)
        s.put(row, 2, ln.no)
        s.put(row, 3, ln.account)
        s.put(row, 4, bk.b.by_code.get(ln.account, {}).get("name") or ln.account_name)
        s.put(row, 5, ln.partner)
        s.put(row, 6, ln.memo)
        s.put(row, 7, ln.credit - ln.debit, money=True)
        s.put(row, 8, r.label)
        s.inp(row, 9, r.pick, pid=p.id, key=f"{PICK}/{r.key}", default=r.default, kind="pick")
        if r.label in TAX_KINDS:
            subj = next((a.subject for a in p.adjustments if a.key == "익금불산입"), "법인세등")
        elif r.label in (REFUND_INTEREST, CUSTOMS_INTEREST):
            subj = INTEREST_SUBJECT
        else:
            subj = next((a.subject for a in p.adjustments if a.key == "부가세 환급 익금불산입"), "")
        s.put(row, 10, subj)
        s.put(row, 11, r.why)
        row += 1
    if not p.extra.get("refunds"):
        s.put(row, 6, "환급 후보 줄 없음")
        row += 1
    return row + 1, first, row - 1
