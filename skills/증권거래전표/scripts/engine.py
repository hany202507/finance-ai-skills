"""표준 거래 → 원장 계산 → 전표.

계산은 워크북 원장 시트의 수식과 같은 식을 Decimal 로 따로 한다. 워크북 수식 값과 이 값이
1원도 다르지 않아야 넘긴다(verify.py).

원가: 종목별 이동평균. 외화예수금: 통화별 이동평균 장부금액.
반올림: 원 단위 ROUND(엑셀과 같은 0.5 올림).
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP

Z = Decimal(0)


def R0(x: Decimal) -> Decimal:
    """엑셀 ROUND(x,0): 0.5 는 0에서 먼 쪽으로."""
    q = abs(x).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    return q if x >= 0 else -q


def R3(x: Decimal) -> Decimal:
    """외화 잔액: 소수 셋째 자리(미래에셋 외화예수금은 12.345 처럼 셋째 자리까지 적는다)."""
    q = abs(x).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    return q if x >= 0 else -q


def R2(x: Decimal) -> Decimal:
    q = abs(x).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return q if x >= 0 else -q


# 계정 키 → 기본 코드·이름(설정에서 바꾼다). 더존 3자리 기본 계정표 기준 초안.
# 이름은 위하고 기본 계정과목(references/위하고_계정과목.csv, 매입매출 업로드 양식 계정과목 시트)과 맞춘다.
# 104 는 위하고 기본 이름이 「기타제예금」이지만 법인 장부는 「외화예금」으로 바꿔 쓴다(고객 장부 실측). 998 은 시트에 없다
DEFAULT_ACCOUNTS = {
    "원화예수금": ("103", "보통예금"),
    "외화예수금": ("104", "외화예금"),
    "이체상대": ("103", "보통예금"),
    "단기매매증권": ("107", "단기매매증권"),
    "매도가능증권": ("178", "매도가능증권"),
    "지급수수료": ("831", "지급수수료"),
    "처분이익": ("906", "단기투자자산처분익"),
    "처분손실": ("938", "단기투자자산처분손"),
    "매도가능처분이익": ("915", "투자자산처분이익"),
    "매도가능처분손실": ("951", "투자자산처분손실"),
    "외환차익": ("907", "외환차익"),
    "외환차손": ("932", "외환차손"),
    "배당금수익": ("903", "배당금수익"),
    "이자수익": ("901", "이자수익"),
    "선납세금": ("136", "선납세금"),
    "해외원천세": ("998", "법인세등"),
    "평가이익": ("905", "단기투자자산평가익"),
    "평가손실": ("937", "단기투자자산평가손"),
    "매도가능평가이익": ("981", "매도가능증권평가이익"),
    "매도가능평가손실": ("982", "매도가능증권평가손실"),
    "환산이익": ("910", "외화환산이익"),
    "환산손실": ("935", "외화환산손실"),
    "가수금": ("257", "가수금"),
    "가지급금": ("134", "가지급금"),
    "대여수수료수익": ("930", "잡이익"),
}

# 이벤트별 분개. (구분, 계정키, 값) 구분: dr 차변 / cr 대변 / pl 양수면 대변(이익계정), 음수면 차변(손실계정)
# 값 앞의 '-' 는 부호를 바꾼다. 값 이름은 Row 필드(원장 열)와 같다.
LINES = {
    "입금":          [("dr", "원화예수금", "S"), ("cr", "이체상대", "S")],
    "출금":          [("dr", "이체상대", "-S"), ("cr", "원화예수금", "-S")],
    "환전_원화외화": [("dr", "외화예수금", "Q"), ("cr", "원화예수금", "-S")],
    "환전_외화원화": [("dr", "원화예수금", "S"), ("cr", "외화예수금", "-Q"), ("pl", "외환", "AC")],
    "해외매수":      [("dr", "증권", "X"), ("dr", "지급수수료", "AD"), ("cr", "외화예수금", "-Q"), ("pl", "외환", "AC")],
    "해외매도":      [("dr", "외화예수금", "Q"), ("cr", "증권", "Z"), ("pl", "처분", "AB")],
    "해외배당":      [("dr", "외화예수금", "Q"), ("dr", "해외원천세", "AF"), ("cr", "배당금수익", "AE")],
    "해외이자":      [("dr", "외화예수금", "Q"), ("dr", "선납세금", "AF"), ("cr", "이자수익", "AE")],
    "해외원천세":    [("dr", "해외원천세", "AF"), ("cr", "외화예수금", "-Q"), ("pl", "외환", "AC")],
    "외화입금":      [("dr", "외화예수금", "Q"), ("cr", "가수금", "Q")],
    "환전정산입금":  [("dr", "원화예수금", "S"), ("cr", "외화예수금", "-Q")],
    "환전정산출금":  [("dr", "외화예수금", "Q"), ("cr", "원화예수금", "-S")],
    "해외세금환급":  [("dr", "외화예수금", "Q"), ("cr", "해외원천세", "Q")],
    "원화세금":      [("dr", "선납세금", "-S"), ("cr", "원화예수금", "-S")],
    "외화출금":      [("dr", "가지급금", "-Q"), ("cr", "외화예수금", "-Q")],
    "국내매수":      [("dr", "증권", "X"), ("dr", "지급수수료", "AD"), ("cr", "원화예수금", "-S")],
    "국내매도":      [("dr", "원화예수금", "S"), ("cr", "증권", "Z"), ("pl", "처분", "AB")],
    "국내배당":      [("dr", "원화예수금", "S"), ("dr", "선납세금", "AF"), ("cr", "배당금수익", "AE")],
    "원화이자":      [("dr", "원화예수금", "S"), ("dr", "선납세금", "AF"), ("cr", "이자수익", "AE")],
    "대여수수료":    [("dr", "원화예수금", "S"), ("dr", "선납세금", "AF"), ("cr", "대여수수료수익", "AE")],
    "원화가계정입":  [("dr", "원화예수금", "S"), ("cr", "가수금", "S")],
    "원화가계정출":  [("dr", "가지급금", "-S"), ("cr", "원화예수금", "-S")],
    "외화가계정입":  [("dr", "외화예수금", "Q"), ("cr", "가수금", "Q")],
    "외화가계정출":  [("dr", "가지급금", "-Q"), ("cr", "외화예수금", "-Q")],
}

PL_PAIR = {"외환": ("외환차익", "외환차손"), "처분": ("처분이익", "처분손실"),
           "평가": ("평가이익", "평가손실"), "환산": ("환산이익", "환산손실")}

# 적요 머리말
MEMO = {
    "입금": "증권계좌 입금", "출금": "증권계좌 출금", "환전_원화외화": "환전 원화→{ccy}", "환전_외화원화": "환전 {ccy}→원화",
    "해외매수": "매수", "해외매도": "매도", "해외배당": "배당", "해외이자": "예탁금이용료", "해외원천세": "현지세",
    "외화입금": "외화입금(확인)", "환전정산입금": "환전정산 {ccy}", "환전정산출금": "환전정산 {ccy}",
    "해외세금환급": "현지세 환급", "원화세금": "세금출금(확인)", "외화출금": "외화출금(확인)", "국내매수": "매수", "국내매도": "매도",
    "국내배당": "배당", "원화이자": "예탁금이용료", "대여수수료": "주식대여 수수료", "원화가계정입": "미분류 입금", "원화가계정출": "미분류 출금",
    "외화가계정입": "미분류 외화입금", "외화가계정출": "미분류 외화출금",
}


@dataclass
class Row:
    tx: object
    kind: str                 # LINES 키 또는 '검토'
    N: Decimal = Z            # 적용 환율
    O: Decimal = Z            # 외화 흐름(+입 −출)
    P: Decimal = Z            # 외화 잔액(후)
    Q: Decimal = Z            # 외화 장부금액 변동(원)
    R: Decimal = Z            # 외화 장부금액(후)
    S: Decimal = Z            # 원화 흐름
    T: Decimal = Z            # 원화 잔액(후)
    U: Decimal = Z            # 수량 변동
    V: Decimal = Z            # 직전 보유수량
    W: Decimal = Z            # 직전 보유원가
    X: Decimal = Z            # 취득원가
    Y: Decimal = Z            # 원가 변동
    Z_: Decimal = Z           # 매도원가
    AA: Decimal = Z           # 처분대가
    AB: Decimal = Z           # 처분손익
    AC: Decimal = Z           # 외환차손익
    AD: Decimal = Z           # 지급수수료(비용)
    AE: Decimal = Z           # 배당·이자 수익(세전)
    AF: Decimal = Z           # 원천세·현지세
    AG: Decimal = Z           # 보유수량(후)
    AH: Decimal = Z           # 보유원가(후)
    AS: Decimal = Z           # 대여 중 수량(후)
    AT: Decimal = Z           # 대여 중 수량 변동(대여출고 +, 대여회수입고 −)
    rate_src: str = ""
    lines: list = field(default_factory=list)

    def get(self, name):
        if name == "Z":
            return self.Z_
        return getattr(self, name)


@dataclass
class Result:
    rows: list
    issues: list
    year_end: list
    fx_end: list
    cfg: dict


def kind_of(tx):
    e, fx = tx.event, tx.ccy != "KRW"
    if e == "매수":
        return "해외매수" if tx.market == "해외" else "국내매수"
    if e == "매도":
        return "해외매도" if tx.market == "해외" else "국내매도"
    if e == "배당":
        return "해외배당" if fx else "국내배당"
    if e == "이자":
        return "해외이자" if fx else "원화이자"
    if e in ("환전_원화외화", "환전_외화원화", "해외원천세", "해외세금환급", "원화세금"):
        return e
    if e == "환전정산":
        return "환전정산출금" if tx._sign < 0 else "환전정산입금"
    if e == "대여수수료":
        return "대여수수료"
    if e == "대여입출고":
        return "대여"
    if e == "주식수변동":
        return "주식수변동"
    if e == "입금":
        return "외화입금" if fx else "입금"
    if e == "출금":
        return "외화출금" if fx else "출금"
    return "검토"


class RateBook:
    def __init__(self, table):
        # table: {통화: [(date, rate, 출처)] 정렬}
        self.t = {c: sorted(v) for c, v in table.items()}

    def get(self, ccy, d):
        best = None
        for (dd, r, s) in self.t.get(ccy, []):
            if dd <= d:
                best = (dd, r, s)
            else:
                break
        return best


def run(txs, cfg, rates: RateBook):
    classification = cfg.get("분류", "단기매매")
    # 2026-11-08: 단기매매(K-IFRS FVPL)만 처리한다. 매도가능(FVOCI)은 처분 시 평가손익 누계 정리와
    # 기초 누계 입력이 없어 막는다. 필요해지면 업데이트한다. 아래 afs 분기는 그때 쓰려고 남긴다
    if classification not in ("단기매매", "FVPL", "당기손익"):
        raise ValueError(f"분류 '{classification}' 는 아직 지원하지 않는다. 단기매매(K-IFRS 당기손익-공정가치측정)만 처리한다. "
                         "매도가능증권 · 기타포괄손익-공정가치측정 지분은 다음 업데이트에서 다룬다")
    afs = False
    issues = []
    begin = cfg.get("기초", {})
    b_krw = Decimal(str(begin.get("원화예수금", 0) or 0))
    b_fx = {c: (Decimal(str(v.get("잔액", 0) or 0)), Decimal(str(v.get("장부금액", 0) or 0)))
            for c, v in (begin.get("외화") or {}).items()}
    b_sec = {}
    for s in begin.get("종목") or []:
        k = s.get("종목코드") or s["종목"]
        b_sec[k] = (Decimal(str(s.get("수량", 0) or 0)), Decimal(str(s.get("장부금액", 0) or 0)), s.get("통화", "KRW"))
    b_lent = {(s.get("종목코드") or s["종목"]): Decimal(str(s.get("대여중", 0) or 0)) for s in (begin.get("종목") or [])}

    fx_bal = {c: v[0] for c, v in b_fx.items()}
    fx_book = {c: v[1] for c, v in b_fx.items()}
    krw = b_krw
    hold = {k: [v[0], v[1]] for k, v in b_sec.items()}
    lent = dict(b_lent)
    pending = {}            # 주식수변동: 날짜별로 출고 행에서 떼어 놓은 장부금액(입고 행이 가져간다)
    rows = []

    for tx in txs:
        k = kind_of(tx)
        if k not in ("대여",) and not (tx.qty or tx.G or tx.H or tx.I or tx.J):
            issues.append(("정보", tx, f"'{tx.raw_type}' 는 금액·수량이 없는 안내 행이라 전표를 내지 않았다"))
            rows.append(Row(tx, "정보"))
            continue
        if k == "대여":
            # 주식 대여·회수: 소유는 그대로다. 전표 없이 대여 중 수량만 센다.
            r = Row(tx, "대여")
            r.AT = tx.qty if "출고" in tx.raw_type else -tx.qty
            lent[tx.key] = lent.get(tx.key, Z) + r.AT
            r.AS = lent[tx.key]
            rows.append(r)
            continue
        if k == "주식수변동" and ((tx.ccy == "KRW" and tx.I) or (tx.ccy != "KRW" and tx.G)):
            k = "검토"      # 단주대금 · 교부금처럼 돈이 움직인 기업행위 행은 가계정으로
        if k == "주식수변동":
            # 분할 · 병합 · 무상증자 · 주식배당 · 감자 · 합병 · 교환: 전표 없이 수량만 바꾼다. 장부금액은 그대로 두고,
            # 종목코드가 바뀌는 경우(출고 → 입고)는 같은 날 출고 행의 장부금액을 입고 행이 가져간다
            r = Row(tx, k)
            h = hold.setdefault(tx.key, [Z, Z])
            r.V, r.W = h[0], h[1]
            out = is_out(tx.raw_type)
            if out:
                if tx.qty > r.V:
                    issues.append(("중단", tx, f"{tx.name} 기업행위 출고 {tx.qty} 가 보유 {r.V} 보다 많다. 기초 잔고를 넣는다"))
                r.U = -tx.qty
                r.Z_ = Z if r.V <= 0 else (r.W if tx.qty >= r.V else R0(r.W * tx.qty / r.V))
                r.Y = -r.Z_
            else:
                r.U = tx.qty
                r.Y = -pending.get(tx.date, Z)
            pending[tx.date] = pending.get(tx.date, Z) + r.Y
            h[0] += r.U
            h[1] += r.Y
            r.AG, r.AH = h[0], h[1]
            r.AS = lent.get(tx.key, Z)
            r.T = krw
            if not out and r.Y == 0:
                issues.append(("확인", tx, f"{tx.name} '{tx.raw_type}' {tx.qty}주를 장부금액 없이 수량만 늘렸다(평균 단가가 내려간다). "
                                           "무상주 · 주식배당이면 세무상 의제배당 여부를 확인한다"))
            elif not out:
                issues.append(("확인", tx, f"{tx.name} '{tx.raw_type}' 에 같은 날 출고 행의 장부금액 {r.Y:,} 원을 옮겼다. "
                                           "분할 · 합병 비율대로인지 확인한다"))
            rows.append(r)
            continue
        if k == "검토":
            moves_cash = (tx.ccy == "KRW" and tx.I) or (tx.ccy != "KRW" and tx.G)
            if moves_cash and tx.event in ("미분류", "검토_자동환전", "검토_기업행위", "검토_입출고", "주식수변동"):
                # 돈이 움직였는데 규칙이 없다 → 가계정. 방향은 증권사 잔액 변화로 정한다.
                k = _guess_direction(tx, krw, fx_bal)
                issues.append(("미분류", tx, f"'{tx.raw_type}' 를 규칙으로 분류하지 못해 가계정으로 기표했다. 적요사전에 넣거나 계정을 정한다"))
            elif not tx.qty:
                # 금액·수량이 모두 없는 안내 행(미래에셋 '세금환급' 행 등). 실제 금액은 앞뒤 행에 있다
                issues.append(("정보", tx, f"'{tx.raw_type}' 는 금액·수량이 없는 안내 행이라 전표를 내지 않았다"))
                rows.append(Row(tx, "정보"))
                continue
            else:
                issues.append(("검토대기", tx, f"'{tx.raw_type}' 수량 {tx.qty} 은 전표를 내지 않았다. 입출고·기업행위는 회계사가 원가를 정한다"))
                rows.append(Row(tx, "검토"))
                continue
        r = Row(tx, k)
        fx = tx.ccy != "KRW"
        if fx and k in ("환전정산입금", "환전정산출금"):
            r.rate_src = "환전정산(원화만)"
        elif fx:
            if k == "환전_원화외화":
                r.N = (tx.I / tx.G) if tx.G else Z
                r.rate_src = "환전 실제환율"
            elif k == "환전_외화원화":
                r.N = (tx.I / tx.G) if tx.G else Z
                r.rate_src = "환전 실제환율"
            else:
                got = rates.get(tx.ccy, tx.date)
                if not got:
                    issues.append(("중단", tx, f"{tx.ccy} {tx.date} 이전 환율이 환율표에 없다"))
                    r.N = Z
                else:
                    r.N = Decimal(str(got[1]))
                    r.rate_src = f"{got[2]} {got[0]}"
                    if got[0] != tx.date:
                        r.rate_src += "(직전일)"
        pb = fx_bal.get(tx.ccy, Z)
        pk = fx_book.get(tx.ccy, Z)

        def out_book(amount):
            if pb <= 0:
                issues.append(("중단", tx, f"{tx.ccy} 외화예수금 잔액이 {pb} 인데 {amount} 를 내보낸다. 기초 잔액을 확인한다"))
                return Z
            if amount == pb:
                return -pk
            return -R0(pk * amount / pb)

        if k == "입금":
            r.S = tx.I
        elif k == "출금":
            r.S = -tx.I
        elif k == "환전_원화외화":
            r.O, r.S = tx.G, -tx.I
            r.Q = tx.I
        elif k == "환전_외화원화":
            r.O, r.S = -tx.G, tx.I
            r.Q = out_book(tx.G)
            r.AC = tx.I + r.Q
        elif k == "해외매수":
            r.O = -(tx.G + tx.H)
            gk, hk = R0(tx.G * r.N), R0(tx.H * r.N)
            r.X = gk + (hk if afs else Z)
            r.AD = Z if afs else hk
            r.Q = out_book(tx.G + tx.H)
            r.AC = gk + hk + r.Q
            r.U, r.Y = tx.qty, r.X
        elif k == "해외매도":
            r.O = tx.G - tx.H
            r.AA = R0((tx.G - tx.H) * r.N)
            r.Q = r.AA
            r.U = -tx.qty
        elif k in ("해외배당", "해외이자"):
            r.O = tx.G - tx.H
            r.AE, r.AF = R0(tx.G * r.N), R0(tx.H * r.N)
            r.Q = r.AE - r.AF
        elif k == "해외원천세":
            r.O = -tx.H
            r.AF = R0(tx.H * r.N)
            r.Q = out_book(tx.H)
            r.AC = r.AF + r.Q
        elif k == "환전정산입금":
            r.S, r.Q = tx.I, -tx.I
        elif k == "환전정산출금":
            r.S, r.Q = -tx.I, tx.I
        elif k == "해외세금환급":
            r.O = tx.G
            r.Q = R0(tx.G * r.N)
        elif k == "원화세금":
            r.S = -tx.I
        elif k in ("외화입금", "외화가계정입"):
            r.O = tx.G
            r.Q = R0(tx.G * r.N)
        elif k in ("외화출금", "외화가계정출"):
            r.O = -tx.G
            r.Q = out_book(tx.G)
        elif k == "국내매수":
            r.S = -(tx.I + tx.J)
            r.X = tx.I + (tx.J if afs else Z)
            r.AD = Z if afs else tx.J
            r.U, r.Y = tx.qty, r.X
        elif k == "국내매도":
            r.S = tx.I - tx.J
            r.AA = r.S
            r.U = -tx.qty
        elif k in ("국내배당", "원화이자", "대여수수료"):
            r.S = tx.I - tx.J
            r.AE, r.AF = tx.I, tx.J
        elif k == "원화가계정입":
            r.S = tx.I
        elif k == "원화가계정출":
            r.S = -tx.I

        # 보유 원장
        if k in ("해외매수", "해외매도", "국내매수", "국내매도"):
            h = hold.setdefault(tx.key, [Z, Z])
            r.V, r.W = h[0], h[1]
            if k.endswith("매도"):
                if r.V <= 0 or tx.qty > r.V:
                    issues.append(("중단", tx, f"{tx.name} 매도 수량 {tx.qty} 가 보유 {r.V} 보다 많다. 기초 잔고를 넣는다"))
                    r.Z_ = Z if r.V <= 0 else r.W
                else:
                    r.Z_ = r.W if tx.qty == r.V else R0(r.W * tx.qty / r.V)
                r.Y = -r.Z_
                r.AB = r.AA - r.Z_
            h[0] += r.U
            h[1] += r.Y
            r.AG, r.AH = h[0], h[1]
            r.AS = lent.get(tx.key, Z)

        if fx:
            fx_bal[tx.ccy] = R3(pb + r.O)
            fx_book[tx.ccy] = pk + r.Q
            r.P, r.R = fx_bal[tx.ccy], fx_book[tx.ccy]
        krw = krw + r.S
        r.T = krw
        r.lines = make_lines(r, cfg)
        rows.append(r)

    # 기초 수량은 있는데 장부금액이 0 인 종목(역산한 기초)을 팔면 원가가 낮게 잡혀 처분이익이 부풀려진다
    for key, (q0, w0, _) in b_sec.items():
        if q0 > 0 and w0 == 0:
            sold = [r for r in rows if r.kind in ("국내매도", "해외매도") and r.tx.key == key]
            if sold:
                nm = sold[0].tx.name
                ab = sum((r.AB for r in sold), Z)
                issues.append(("확인", None, f"{nm} 기초 {q0}주의 장부금액이 0 이라 매도 {len(sold)}건의 원가가 낮게 잡혔다(처분손익 합계 {ab:,} 원). "
                                             "전기말 장부금액을 설정 기초 · 워크북 기초 시트에 넣고 다시 돌린다"))
    year_end, fx_end = closing(cfg, hold, fx_bal, fx_book, b_sec, txs, issues)
    _checks(rows, issues, cfg)
    _period_end_notes(rows, issues, cfg, year_end, fx_end)
    return Result(rows, issues, year_end, fx_end, cfg)


def _period_end_notes(rows, issues, cfg, year_end, fx_end):
    """기간 전체에 걸린 확인사항. 근거는 2026-11-08 분개규칙 원문 검토(references/분개규칙.md 「검토 근거」)."""
    trades = [r for r in rows if r.kind in ("국내매수", "국내매도", "해외매수", "해외매도")]
    if trades:
        issues.append(("확인", None, "전표 일자는 증권사 파일의 일자 열이다(체결일 · 매매일 칸이 있으면 그 칸). 일반기업회계기준 6.4의2 와 "
                                     "법인세법 시행령 제68조①5호(국내 상장주식)는 체결일 기준이다. 일자가 결제일이면 기말 직전 2영업일에 "
                                     "체결하고 다음 해에 결제한 매매를 미수금 · 미지급금으로 따로 잡는다"))
        if any(r.AD for r in trades):
            issues.append(("확인", None, "매수 수수료를 지급수수료(기본 831, 판관비)로 잡았다. 처분 · 평가손익은 영업외 항목이라(일반기업회계기준 "
                                         "실2.48 · 실2.49) 매수 수수료도 영업외로 두려면 회사설정 영업외비용 코드를 등록해 설정 `계정` 의 "
                                         "지급수수료를 바꾼다"))
        issues.append(("정보", None, "원가는 종목별 이동평균법이다. 매기 같은 방법을 쓰고 주석에 적는다(일반기업회계기준 6.A7의5 · 6.A24). "
                                     "세무상 평가방법을 신고하지 않았으면 총평균법이라(법인세법 시행령 제75조) 차이를 세무조정한다"))
    if (cfg.get("기말") or {}).get("일자"):
        issues.append(("확인", None, "기말에 받을 권리가 확정됐는데 아직 안 들어온 배당 · ETF 분배금은 이 스킬이 잡지 않는다(입금 행으로만 "
                                     "전표를 낸다). 미수배당금 · 미수수익으로 따로 잡는다(일반기업회계기준 16.16⑵ · 실6.64⑴). 세법 귀속은 "
                                     "잉여금 처분결의일이다(법인세법 시행령 제70조②)"))
    if year_end:
        issues.append(("정보", None, "기말 평가손익은 세무상 인정되지 않는다(법인세법 제42조①). 세무조정 대상이다"))
    if fx_end:
        issues.append(("정보", None, "외화예수금 환산손익은 그 사업연도 법인세 신고 때 외화 평가방법을 신고한 경우에만 세무상 인정된다"
                                     "(법인세법 시행령 제76조)"))
    if stock_div_count(rows):
        issues.append(("확인", None, "국내 상장주식 배당은 수입배당금 익금불산입 대상이다(법인세법 제18조의2, 지분 20% 미만 30%). "
                                     "배당기준일 전 3개월 안에 산 주식의 배당과 차입금 이자 상당액은 뺀다. ETF 분배금과 미국 주식 배당은 대상이 아니다"))


def stock_div_count(rows):
    return sum(1 for r in rows if r.kind == "국내배당" and not _ETF.search(r.tx.name or ""))


def is_out(raw_type: str) -> bool:
    """기업행위 행이 주식을 내보내는지(출고 · 감자) 들여오는지."""
    s = raw_type or ""
    if "출고" in s:
        return True
    if "입고" in s:
        return False
    return "감자" in s


def _guess_direction(tx, krw, fx_bal):
    if tx.ccy == "KRW":
        if tx.krw_bal is not None:
            return "원화가계정입" if tx.krw_bal >= krw else "원화가계정출"
        return "원화가계정입" if "입" in tx.raw_type else "원화가계정출"
    if tx.fx_bal is not None:
        return "외화가계정입" if tx.fx_bal >= fx_bal.get(tx.ccy, Z) else "외화가계정출"
    return "외화가계정입" if "입" in tx.raw_type else "외화가계정출"


def acct(cfg, key):
    m = dict(DEFAULT_ACCOUNTS)
    m.update({k: tuple(v) for k, v in (cfg.get("계정") or {}).items()})
    afs = cfg.get("분류", "단기매매") == "매도가능"
    if key == "증권":
        key = "매도가능증권" if afs else "단기매매증권"
    if afs and key in ("처분이익", "처분손실", "평가이익", "평가손실"):
        key = "매도가능" + key
    return m[key]


def make_lines(r: Row, cfg):
    out = []
    for side, key, val in LINES.get(r.kind, []):
        neg = val.startswith("-")
        v = r.get(val.lstrip("-"))
        v = -v if neg else v
        if side == "pl":
            gain, loss = PL_PAIR[key]
            if v > 0:
                out.append(("cr", acct(cfg, gain), v, key))
            elif v < 0:
                out.append(("dr", acct(cfg, loss), -v, key))
            else:
                out.append(("cr", acct(cfg, gain), Z, key))
        else:
            out.append((side, acct(cfg, key), v, key))
    return out


def closing(cfg, hold, fx_bal, fx_book, b_sec, txs, issues):
    end = cfg.get("기말") or {}
    prices = end.get("단가") or {}
    rates = {c: Decimal(str(v)) for c, v in (end.get("환율") or {}).items() if v not in (None, "")}
    names = {}
    for k, v in b_sec.items():
        names[k] = (k, v[2])
    for t in txs:
        if t.key and t.event in ("매수", "매도"):
            names.setdefault(t.key, (t.name, t.ccy))
    ye = []
    for k, (q, cost) in hold.items():
        nm, ccy = names.get(k, (k, "KRW"))
        if q == 0 and cost == 0:
            continue
        p = prices.get(k, prices.get(nm))
        rate = Decimal(1) if ccy == "KRW" else rates.get(ccy)
        item = {"key": k, "name": nm, "ccy": ccy, "qty": q, "cost": cost, "price": None, "rate": rate, "fv": None, "pl": None}
        if q == 0 and cost != 0:
            issues.append(("확인", None, f"{nm} 수량 0 인데 원가 {cost} 가 남았다(반올림 잔액이 아니면 원장 확인)"))
        if p not in (None, "") and rate is not None:
            item["price"] = Decimal(str(p))
            item["fv"] = R0(q * item["price"] * rate)
            item["pl"] = item["fv"] - cost
        elif end:
            issues.append(("확인", None, f"{nm} 기말 단가(또는 {ccy} 기말환율)가 없어 평가 전표를 내지 않았다"))
        ye.append(item)
    fe = []
    for c in sorted(fx_bal):
        rate = rates.get(c)
        it = {"ccy": c, "bal": fx_bal[c], "book": fx_book[c], "rate": rate, "krw": None, "pl": None}
        if rate is not None:
            it["krw"] = R0(fx_bal[c] * rate)
            it["pl"] = it["krw"] - fx_book[c]
        elif end:
            issues.append(("확인", None, f"{c} 기말환율이 없어 외화예수금 환산 전표를 내지 않았다"))
        fe.append(it)
    return ye, fe


_PROCESS_NOTES = ("합침", "묶음 대금행", "자동환전", "끝수")


_ETF = __import__("re").compile(r"ETF|KODEX|TIGER|ACE|KBSTAR|RISE|SOL|HANARO|ARIRANG|KOSEF|PLUS|TIMEFOLIO|KIWOOM|마이티|히어로즈|1Q|BNK|"
                                 r"상장지수|증권투자신탁|투자신탁", __import__("re").I)


def _checks(rows, issues, cfg):
    fxadj = [r for r in rows if r.kind.startswith("환전정산")]
    if fxadj:
        tot = sum((r.S for r in fxadj), Z)
        issues.append(("확인", None, f"환전정산(선환전차액 등) {len(fxadj)}건, 원화 합계 {tot:,} 원을 외화예수금 장부금액에서 "
                                     "조정했다(가환율 환전의 차액). 건별 내역은 거래원장"))
    proc = {}
    for r in rows:
        for n in r.tx.notes:
            for key in _PROCESS_NOTES:
                if key in n:
                    proc[key] = proc.get(key, 0) + 1
    if proc:
        issues.append(("정보", None, "처리 기록: " + ", ".join(f"{k} {v}건" for k, v in proc.items())
                       + ". 건별 내역은 표준거래표.csv 메모 열"))
    for r in rows:
        t = r.tx
        if r.kind == "원화이자" and r.AF == 0 and r.AE * Decimal("0.14") >= 1000:
            # 법인세법 제73조①: 14% 원천징수, 1천원 미만이면 징수하지 않는다(소액부징수)
            issues.append(("확인", t, f"원화 이자 {r.AE} 에 원천세가 없다. 법인 이자소득은 14% 원천징수 대상이다(법인세법 제73조①, 세액 1천원 미만은 징수 안 함). 원천징수영수증으로 맞춘다"))
        if r.kind == "해외배당" and r.AE:
            rate = (t.H / t.G) if t.G else Z
            if t.H == 0:
                issues.append(("확인", t, f"{t.name} 배당에 현지세가 없다(미국 15% 가 보통). 세금 행이 따로 있는지 본다"))
            elif abs(t.H - t.G * Decimal("0.30")) <= Decimal("0.011"):
                issues.append(("확인", t, f"{t.name} 배당 현지세율이 30% 다. 한미 조세조약 세율(15%)을 받는 서류(W-8BEN-E)가 증권사에 "
                                          "없을 때 나온다. 증권사에 제출하고, 더 뗀 15% 는 미국 환급 절차로 돌려받는다"))
            elif abs(t.H - t.G * Decimal("0.15")) > Decimal("0.011"):
                issues.append(("확인", t, f"{t.name} 배당 현지세율 {rate*100:.2f}% (15% 가 아니다)"))
        if r.kind == "해외이자" and r.AF == 0 and r.AE * Decimal("0.14") >= 1000:
            issues.append(("확인", t, f"외화 예탁금이용료 {r.AE:,} 원(환산)에 원천세가 없다. 국내 증권사가 주는 이자는 원화 이자와 같이 "
                                      "14% 원천징수 대상이다(법인세법 제73조①1호). 원천징수영수증으로 맞춘다"))
        if r.kind == "국내배당":
            if _ETF.search(t.name or "") and r.AF == 0 and r.AE * Decimal("0.154") >= 1000:
                issues.append(("확인", t, f"{t.name} 분배금 {r.AE:,} 원에 원천세가 없다. ETF(투자신탁) 분배금은 법인도 14% 원천징수 "
                                          "대상이다(법인세법 제73조①2호, 법인지방소득세 1.4% 별도). 국내 주식형 ETF 는 분배 재원이 주식 매매차익이면 과세 대상이 없어 0 일 수 있다. 증권사 분배금 내역(과세표준)으로 맞춘다"))
        if r.kind == "대여수수료" and r.AF > 0:
            issues.append(("확인", t, f"주식 대여 수수료에서 세금 {r.AF:,} 원이 빠졌다. 법인이 받는 대여 수수료는 법인세법 제73조① 원천징수 "
                                      "대상(이자 · 투자신탁이익)이 아니다. 증권사에 근거를 묻고, 잘못 뗀 것이면 환급을 요청한다"))
        if r.kind == "주식수변동" and "합병" in (t.raw_type or ""):
            issues.append(("확인", t, f"{t.name} 합병 교부주식은 장부금액을 그대로 옮겼다. 일반기업회계기준 질의회신 GKQA03-062 는 교부받은 "
                                      "주식을 교부일 공정가치로 새로 잡고 옛 장부금액과의 차액을 손익으로 둔다. 공정가치로 조정 전표를 친다"))
        if r.kind == "원화세금":
            issues.append(("확인", t, f"원화 세금 출금 {t.I} 을 선납세금으로 잡았다. 무슨 소득의 세금인지 원천징수영수증으로 맞춘다"))
        for n in t.notes:
            if not any(key in n for key in _PROCESS_NOTES):
                issues.append(("확인", t, n))
        # 증권사 잔액 대사
        if t.krw_bal is not None and r.kind not in ("검토", "대여", "정보") and (t.ccy == "KRW" or r.S != 0) and r.T != t.krw_bal:
            issues.append(("대사", t, f"원화 잔액 계산 {r.T} ≠ 증권사 {t.krw_bal}"))
        if t.fx_bal is not None and t.ccy != "KRW" and r.kind not in ("검토", "대여", "정보") and r.P != t.fx_bal:
            issues.append(("대사", t, f"{t.ccy} 잔액 계산 {r.P} ≠ 증권사 {t.fx_bal}"))
        if t.hold_qty is not None and r.kind in ("해외매수", "해외매도", "국내매수", "국내매도", "주식수변동") and r.AG - r.AS != t.hold_qty:
            issues.append(("대사", t, f"{t.name} 보유수량 계산 {r.AG}(대여 중 {r.AS} 제외 {r.AG - r.AS}) ≠ 증권사 {t.hold_qty}"))
        if r.kind not in ("검토", "대여", "정보"):
            dr = sum(v for s, _, v, _ in r.lines if s == "dr")
            cr = sum(v for s, _, v, _ in r.lines if s == "cr")
            if dr != cr:
                issues.append(("중단", t, f"전표 차대 불일치 {dr} / {cr}"))


def infer_opening(txs):
    """파일에서 기초 잔고를 거꾸로 추정한다(입력 제안용, 확정값 아님)."""
    sugg = {"원화예수금": None, "외화": {}, "종목": {}}
    fx_seen, krw_seen = {}, False
    flow_k = Z
    flows = {}
    qty = {}
    # 기간 전에 빌려준 수량: 대여 변동 누계의 최솟값이 음수면 그만큼이 기초에 대여 중이었다
    cum, mn = {}, {}
    for t in txs:
        if kind_of(t) == "대여":
            d = t.qty if "출고" in t.raw_type else -t.qty
            cum[t.key] = cum.get(t.key, Z) + d
            mn[t.key] = min(mn.get(t.key, Z), cum[t.key])
    open_lent = {k: -v for k, v in mn.items() if v < 0}
    sugg["대여중"] = open_lent
    lend_now = dict(open_lent)
    for t in txs:
        k = kind_of(t)
        if k == "대여":
            lend_now[t.key] = lend_now.get(t.key, Z) + (t.qty if "출고" in t.raw_type else -t.qty)
            continue
        # 원화
        s = Z
        if k == "입금": s = t.I
        elif k == "출금": s = -t.I
        elif k == "환전_원화외화": s = -t.I
        elif k == "환전_외화원화": s = t.I
        elif k == "국내매수": s = -(t.I + t.J)
        elif k == "국내매도" or k in ("국내배당", "원화이자", "대여수수료"): s = t.I - t.J
        elif k == "환전정산입금": s = t.I
        elif k in ("환전정산출금", "원화세금"): s = -t.I
        flow_k += s
        if t.krw_bal is not None and not krw_seen and (t.ccy == "KRW" or s):
            sugg["원화예수금"] = t.krw_bal - flow_k
            krw_seen = True
        if t.ccy != "KRW":
            o = Z
            if k == "환전_원화외화": o = t.G
            elif k == "환전_외화원화": o = -t.G
            elif k == "해외매수": o = -(t.G + t.H)
            elif k in ("해외매도", "해외배당", "해외이자"): o = t.G - t.H
            elif k == "해외원천세": o = -t.H
            elif k in ("외화입금", "해외세금환급"): o = t.G
            elif k == "외화출금": o = -t.G
            flows[t.ccy] = flows.get(t.ccy, Z) + o
            if t.fx_bal is not None and t.ccy not in fx_seen:
                fx_seen[t.ccy] = R3(t.fx_bal - flows[t.ccy])
        if k in ("해외매수", "해외매도", "국내매수", "국내매도", "주식수변동"):
            if k == "주식수변동":
                u = -t.qty if is_out(t.raw_type) else t.qty
            else:
                u = t.qty if k.endswith("매수") else -t.qty
            qty[t.key] = qty.get(t.key, Z) + u
            if t.hold_qty is not None and t.key not in sugg["종목"]:
                # 증권사 잔고 = 소유 − 대여 중 → 기초 소유 = 잔고 − 기간 중 매매 + 그 시점 대여 중
                b = t.hold_qty - qty[t.key] + lend_now.get(t.key, Z)
                sugg["종목"][t.key] = (t.name, t.ccy, b)
    for key, q in open_lent.items():          # 매매 없이 대여 회수만 있는 종목
        if key not in sugg["종목"]:
            nm = next((t.name for t in txs if t.key == key), key)
            sugg["종목"][key] = (nm, "KRW", q)
    sugg["외화"] = fx_seen
    sugg["종목"] = {k: v for k, v in sugg["종목"].items() if v[2] != 0}
    return sugg
