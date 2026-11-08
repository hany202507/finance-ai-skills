"""머리글이 맞춰진 행을 표준 거래(Txn)로 바꾸고 이벤트를 붙인다.

표준 거래의 금액 칸(원장 시트 열과 같다):
  G 외화총액  H 외화비용  I 원화금액  J 원화비용  (모두 0 이상, 방향은 이벤트가 정한다)
  매수 G·I 는 체결금액(수수료 전), 매도 G·I 도 체결금액, H·J 는 수수료·세금.
  배당·이자 G·I 는 세전 총액, H·J 는 원천세(해외는 현지세).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict
from decimal import Decimal
from pathlib import Path

from read_source import parse_date, to_num, norm, REF

Z = Decimal(0)


@dataclass
class Txn:
    _fx_net: object = None
    _fx_gross: object = None
    _krw_net: object = None
    _fx_cost_given: bool = False
    _sign: int = 1
    _rec: object = None
    seq: int = 0
    date: object = None
    settle: object = None
    raw_type: str = ""
    event: str = ""
    market: str = ""            # 국내 | 해외 | ""
    key: str = ""               # 종목 키(코드 또는 이름)
    code: str = ""
    name: str = ""
    ccy: str = "KRW"
    qty: Decimal = Z
    price: Decimal = Z
    G: Decimal = Z
    H: Decimal = Z
    I: Decimal = Z
    J: Decimal = Z
    krw_bal: object = None      # 증권사 원화 잔액(대사용)
    fx_bal: object = None       # 증권사 외화 잔액(대사용)
    hold_qty: object = None     # 증권사 잔고수량(대사용)
    broker_rate: object = None
    counterparty: str = ""
    src: str = ""
    notes: list = field(default_factory=list)

    def d(self):
        x = {k: v for k, v in asdict(self).items() if not k.startswith("_")}
        x["date"] = str(self.date)
        x["settle"] = str(self.settle) if self.settle else ""
        for k in ("qty", "price", "G", "H", "I", "J"):
            x[k] = str(x[k])
        for k in ("krw_bal", "fx_bal", "hold_qty", "broker_rate"):
            x[k] = None if x[k] is None else str(x[k])
        return x


def load_rules():
    d = json.loads((REF / "적요사전.json").read_text(encoding="utf-8"))
    return [(re.compile(r["pattern"]), r) for r in d["rules"]]


def classify(raw_type: str, ccy: str, rules):
    s = re.sub(r"\s", "", raw_type or "")
    for rx, r in rules:
        if not rx.search(s):
            continue
        cond = r.get("통화")
        if cond == "외화" and ccy == "KRW":
            continue
        if cond == "KRW" and ccy != "KRW":
            continue
        return r["event"], r.get("시장", "")
    return "미분류", ""


def _n(rec, *keys):
    for k in keys:
        v = to_num(rec.get(k))
        if v is not None:
            return v
    return None


def _clean_name(name: str, ccy: str) -> str:
    s = (str(name or "")).replace("　", " ").strip()
    # 칸 안 줄바꿈(pdfplumber): 한글 낱말 중간에서 끊긴 것은 붙이고, 그 밖은 띄운다
    s = re.sub(r"(?<=[가-힣])\s*\n\s*(?=[가-힣])", "", s)
    s = " ".join(s.split())
    if ccy != "KRW" and s.upper().startswith(ccy):     # 'USD 애플', OCR 은 'USD애플'
        s = s[len(ccy):].strip()
    # kordoc 이 3줄 1건 표(미래에셋)에서 환율·단가 칸을 종목명 앞에 붙인다: '1,434.9 ○○ ETF'
    s = re.sub(r"^-?\d{1,3}(?:,\d{3})*\.\d+\s+|^-?\d{1,3}(?:,\d{3})+\s+", "", s)
    return s


def _jamo(s: str) -> str:
    out = []
    for ch in s:
        c = ord(ch)
        if 0xAC00 <= c <= 0xD7A3:
            c -= 0xAC00
            out += [chr(0x1100 + c // 588), chr(0x1161 + (c % 588) // 28)]
            if c % 28:
                out.append(chr(0x11A7 + c % 28))
        else:
            out.append(ch)
    return "".join(out)


def _sim(a: str, b: str) -> float:
    from difflib import SequenceMatcher
    return SequenceMatcher(None, _jamo(a), _jamo(b)).ratio()


def ocr_correct(txs, vocab):
    """OCR 표: 분류 안 된 적요를 비슷한 표준 적요로, 거의 같은 종목명을 많이 나온 이름으로 맞춘다."""
    rules = load_rules()
    for t in txs:
        if t.event in ("미분류",) and t.raw_type:
            best = max(vocab, key=lambda v: _sim(re.sub(r"\s", "", t.raw_type), v))
            if _sim(re.sub(r"\s", "", t.raw_type), best) >= 0.8:
                ev, mkt = classify(best, t.ccy, rules)
                if ev != "미분류":
                    t.notes.append(f"OCR 교정: 거래종류 '{t.raw_type}' → '{best}'")
                    t.raw_type, t.event = best, ev
                    if t._rec is not None:      # 이벤트가 바뀌면 금액 해석도 바뀐다
                        t.G = t.H = t.I = t.J = Z
                        t.qty = abs(_n(t._rec, "수량") or Z)
                        _amounts(t, t._rec, mkt)
    from collections import Counter
    cnt = Counter(t.name for t in txs if t.name)
    names = [n for n, _ in cnt.most_common()]
    codes = {}
    for t in txs:
        if t.name and t.code:
            codes.setdefault(t.name, set()).add(t.code)
    digits = lambda s: re.findall(r"\d+", s)   # noqa: E731
    for t in txs:
        if not t.name:
            continue
        for n in names:
            if n == t.name:
                break
            # 다른 종목을 한 이름으로 합치지 않는다(2026-11-08 미래에셋 스캔본: 레버리지 3X ETF 를 같은 운용사 2X ETF 로,
            # 이름 앞부분이 같은 ETF 둘을 한 이름으로). 종목코드가 다르거나 숫자가 다르면 건너뛴다
            if t.code and codes.get(n) and t.code not in codes[n]:
                continue
            if digits(n) != digits(t.name):
                continue
            if cnt[n] >= cnt[t.name] and _sim(n, t.name) >= 0.75:
                t.notes.append(f"OCR 교정: 종목명 '{t.name}' → '{n}'")
                t.name = n
                break


_AMT_KEYS = ("거래금액", "정산금액", "입금액", "출금액", "외화거래금액", "외화정산금액")
_COST_KEYS = ("수수료", "제세금", "거래세", "농특세", "소득세", "지방세", "원화기타비용",
              "외화수수료", "외화제세금", "외화기타비용")


def _fmt(d: Decimal) -> str:
    s = format(d.normalize(), "f")
    return s


def repair_by_balance(recs):
    """OCR 로 읽은 행의 금액을 증권사 잔액 변동으로 바로잡는다(2026-11-08 미래에셋 스캔본 127쪽).
    OCR 은 '1,000,000' 을 '1,00,000' 으로, 외화 '1,234.567' 을 '1,234,567' 로, '4.567' 을 '4.56' 으로 읽었다.
    잔액 변동 = 금액(± 비용) 이 되도록
      ① 금액 칸이 10·100·1000 배 어긋나면 잔액 변동에 맞는 값으로,
      ② 외화 비용이 끝자리를 잃었으면(잔액이 가리키는 값이 읽은 값으로 시작하면) 그 값으로 고친다.
    앞 잔액·이 행 잔액이 둘 다 읽혀야 하고, 10의 거듭제곱 배가 잔액 변동과 1원(0.001) 단위까지 같아야 고친다.
    recs 는 시간 순이어야 한다. 고친 내용은 그 행 '_notes' 에 남아 거래 메모로 간다."""
    prev = {}
    for r in recs:
        ccy = (str(r.get("통화") or "").strip().upper() or "KRW")
        for bal_key, cur in (("현금잔액", "KRW"), ("외화예수금잔액", ccy if ccy not in ("원", "KRW") else None)):
            if cur is None:
                continue
            b = to_num(r.get(bal_key))
            if b is None:
                continue
            p = prev.get((bal_key, cur))
            prev[(bal_key, cur)] = b
            if p is None:
                continue
            delta = abs(b - p)
            if delta == 0:
                continue
            amts = {k: abs(to_num(r.get(k))) for k in _AMT_KEYS if to_num(r.get(k))}
            costs = {k: abs(to_num(r.get(k))) for k in _COST_KEYS if to_num(r.get(k))}
            csum = sum(costs.values(), Z)
            fits = lambda v: v in (delta, delta - csum, delta + csum)   # noqa: E731
            if any(fits(v) for v in amts.values()):
                continue

            def fee_fix(g):
                # 외화 비용 하나가 끝자리를 잃은 경우: 잔액이 가리키는 비용이 읽은 비용으로 시작하면 그 값
                if cur == "KRW" or len(costs) != 1:
                    return None
                (ck, fv), = costs.items()
                for res in (delta - g, g - delta):
                    if res > 0 and 0 < abs(res - fv) < Decimal("0.01") and _fmt(res).startswith(_fmt(fv)):
                        return ck, fv, res
                return None

            # 후보: (금액 칸, 읽은 값, 고친 값). 읽은 그대로 → 10·100·1000 배 순
            cands = [(k, v, v) for k, v in amts.items()]
            cands += [(k, v, c) for k, v in amts.items() for f in (10, 100, 1000) for c in (v * f, v / f)]
            for k, v, c in cands:
                fee = None
                if not fits(c):
                    fee = fee_fix(c)
                    if fee is None:
                        continue
                notes = r.setdefault("_notes", [])
                if c != v:
                    # 거래금액·입출금액처럼 같은 값을 적은 칸은 함께 고친다
                    for k2 in [k2 for k2, v2 in amts.items() if v2 == v]:
                        notes.append(f"OCR 잔액 교정: {k2} {_fmt(v)} → {_fmt(c)}")
                        r[k2] = _fmt(c)
                if fee:
                    notes.append(f"OCR 잔액 교정: {fee[0]} {_fmt(fee[1])} → {_fmt(fee[2])}")
                    r[fee[0]] = _fmt(fee[2])
                break


def repair_in_row(recs):
    """OCR 이 소수점을 쉼표로 읽은 외화 금액·단가를 같은 행의 다른 칸으로 바로잡는다(2026-11-08 미래에셋 스캔본).
    '1,234.567' → '1,234,567', 단가 '12.345' → '12,345' 가 나왔다. 외화 칸은 잔액이 같은 행에 없어 잔액 교정이 안 된다.
      ① 수량 × 단가 ≈ 외화거래금액 이 되도록 금액이나 단가를 1/10·1/100·1/1000 로
      ② 외화거래금액 ± 외화 비용 ≈ 외화정산금액(센트로 끊겨 0.011 까지 허용) 이 되도록 금액을 1/10·1/100·1/1000 로."""
    tol = Decimal("0.011")
    for r in recs:
        ccy = (str(r.get("통화") or "").strip().upper() or "KRW")
        if ccy in ("KRW", "원"):
            continue
        g, q, pr, net = (to_num(r.get(k)) for k in ("외화거래금액", "수량", "단가", "외화정산금액"))
        cost = sum((abs(to_num(r.get(k)) or Z) for k in _COST_KEYS), Z)
        notes = r.setdefault("_notes", [])
        near = lambda a, b: abs(a - b) <= max(tol, abs(b) * Decimal("0.0005"))   # noqa: E731
        if g and q and pr:
            g, q, pr = abs(g), abs(q), abs(pr)
            if not near(q * pr, g):
                for f in (10, 100, 1000):
                    if near(q * pr, g / f):
                        notes.append(f"OCR 행 교정: 외화거래금액 {_fmt(g)} → {_fmt(g / f)}")
                        g = g / f
                        r["외화거래금액"] = _fmt(g)
                        break
                    if near(q * pr / f, g):
                        notes.append(f"OCR 행 교정: 단가 {_fmt(pr)} → {_fmt(pr / f)}")
                        r["단가"] = _fmt(pr / f)
                        break
        elif g and net:
            g, net = abs(g), abs(net)
            if not any(abs(x - net) <= tol for x in (g + cost, g - cost, g)):
                for f in (10, 100, 1000):
                    if any(abs(x - net) <= tol for x in (g / f + cost, g / f - cost)):
                        notes.append(f"OCR 행 교정: 외화거래금액 {_fmt(g)} → {_fmt(g / f)}")
                        r["외화거래금액"] = _fmt(g / f)
                        break
        if not notes:
            r.pop("_notes")


def to_txns(tables, broker: str = ""):
    rules = load_rules()
    out = []
    for t in tables:
        recs = t.records
        # 최신 거래가 위에 오는 파일(삼성 종합거래내역 등)은 뒤집는다. 같은 날 순서도 함께 뒤집힌다.
        ds = [parse_date(r.get("일자")) for r in recs]
        if len(ds) >= 2 and ds[0] and ds[-1] and ds[0] > ds[-1]:
            recs = list(reversed(recs))
        if t.ocr is not None or str(t.sheet).startswith("ocr"):
            repair_in_row(recs)
            repair_by_balance(recs)
        for r in recs:
            ccy = (str(r.get("통화") or "").strip().upper() or "KRW")
            if ccy in ("원", "KRW", "WON", "₩"):
                ccy = "KRW"
            raw = " ".join(x for x in (str(r.get("거래종류") or "").strip(), str(r.get("세부적요") or "").strip()) if x)
            ev, mkt = classify(raw, ccy, rules)
            tx = Txn(date=parse_date(r.get("일자")), settle=parse_date(r.get("결제일")),
                     raw_type=raw, event=ev, ccy=ccy,
                     src=f"{t.source}:{t.sheet}:{r['_row']}")
            tx.code = str(r.get("종목코드") or "").strip()
            tx.name = _clean_name(r.get("종목명"), ccy)
            m = re.match(r"^(.*?)\s*\(([A-Z]{0,2}[0-9A-Z]{6,12})\)$", tx.name)
            if m:   # 토스: 종목명(종목코드)
                tx.name, tx.code = m.group(1).strip(), tx.code or m.group(2)
            if tx.code.upper() in ("USD", "KRW", "JPY", "HKD", "CNY", "EUR"):   # 신한: 종목번호 칸의 통화 표시
                if ccy == "KRW" and tx.code.upper() != "KRW":
                    tx.ccy = ccy = tx.code.upper()
                    tx.event, mkt = classify(raw, ccy, rules)
                tx.code = ""
            tx.qty = abs(_n(r, "수량") or Z)
            tx.price = abs(_n(r, "단가") or Z)
            tx.krw_bal = _n(r, "현금잔액")
            tx.fx_bal = _n(r, "외화예수금잔액") if ccy != "KRW" else None
            tx.hold_qty = _n(r, "잔고수량")
            tx.broker_rate = _n(r, "환율")
            tx.counterparty = " ".join(" ".join(str(r.get(k) or "").replace("　", " ").split())
                                       for k in ("상대기관", "상대계좌명")).strip()
            tx._rec = r
            tx.notes += r.get("_notes", [])
            _amounts(tx, r, mkt)
            out.append(tx)
    if any(getattr(t, "ocr", None) is not None for t in tables):
        vocab = json.loads((REF / "적요사전.json").read_text(encoding="utf-8")).get("ocr_vocab", [])
        ocr_correct(out, vocab)
    out = _merge_pairs(out)
    out.sort(key=lambda x: x.date)   # 안정 정렬: 같은 날은 파일 순서
    out = reorder_auto_fx(out)
    last_fx = "USD"
    for x in out:
        if x.ccy != "KRW":
            last_fx = x.ccy
        elif x.event == "환전정산":
            x.ccy = last_fx
    for i, x in enumerate(out, 1):
        x.seq = i
        x.key = x.code or x.name
    return out


def _amounts(tx: Txn, r, mkt):
    ev, ccy = tx.event, tx.ccy
    # 미래에셋: 외화 거래도 수수료·제세금을 거래 통화로 같은 칸(수수료·제세금합)에 적는다.
    # 원화 금액·원화 잔액이 비어 있는 외화 행이면 그 칸을 외화 비용으로 본다.
    # (삼성은 외화 배당 행에 원화 세금을 적고 현금잔액이 함께 줄어 이 조건에 걸리지 않는다)
    if ccy != "KRW" and not any(_n(r, k) for k in ("외화수수료", "외화제세금", "외화기타비용")) \
            and not (_n(r, "거래금액") or _n(r, "정산금액")) and _n(r, "현금잔액") is None \
            and any(_n(r, k) for k in ("수수료", "제세금")):
        r = dict(r)
        if _n(r, "수수료"):
            r["외화수수료"] = r.pop("수수료")
        if _n(r, "제세금"):
            r["외화제세금"] = r.pop("제세금")
    tx._fx_net = _n(r, "외화정산금액")
    tx._fx_gross = _n(r, "외화거래금액")
    tx._krw_net = _n(r, "정산금액")
    tx._fx_cost_given = any(_n(r, k) for k in ("외화수수료", "외화제세금", "외화기타비용"))
    fx = ccy != "KRW"
    fx_gross = _n(r, "외화거래금액")
    fx_net = _n(r, "외화정산금액")
    fx_cost = sum((abs(_n(r, k) or Z) for k in ("외화수수료", "외화제세금", "외화기타비용")), Z)
    krw_gross = _n(r, "거래금액")
    krw_net = _n(r, "정산금액")
    krw_inout = _n(r, "입금액") or _n(r, "출금액")
    krw_cost = sum((abs(_n(r, k) or Z) for k in ("수수료", "제세금", "거래세", "농특세", "소득세", "지방세", "원화기타비용")), Z)

    if ev in ("매수", "매도"):
        tx.market = "해외" if (mkt == "해외" or fx) else "국내"
        if tx.market == "해외":
            g = abs(fx_gross) if fx_gross is not None else (tx.qty * tx.price).quantize(Decimal("0.01"))
            n = abs(fx_net) if fx_net is not None else None
            if fx_cost:
                h = fx_cost
            elif n is not None:
                h = abs(n - g)
            else:
                h = Z
            tx.G, tx.H = g, h
            if n is not None:
                exp = g + h if ev == "매수" else g - h
                if abs(exp - n) > Decimal("0.011"):
                    tx.notes.append(f"외화 정산금액 {n} 이 체결금액±비용 {exp} 과 다르다")
        else:
            g = abs(krw_gross) if krw_gross is not None else None
            n = abs(krw_net) if krw_net is not None else (abs(krw_inout) if krw_inout is not None else None)
            if g is None and n is not None:
                g = n - krw_cost if ev == "매수" else n + krw_cost
            if g is None:
                g = (tx.qty * tx.price).quantize(Decimal("1"))
            tx.I, tx.J = g, krw_cost
            if n is not None:
                exp = g + krw_cost if ev == "매수" else g - krw_cost
                if abs(exp - n) > 1:
                    tx.notes.append(f"정산금액 {n} 이 거래금액±수수료·세금 {exp} 과 다르다")
        return

    if ev in ("환전정산", "원화세금"):
        k = krw_net if krw_net is not None else (krw_inout if krw_inout is not None else krw_gross)
        tx.I = abs(k or Z)
        tx._sign = -1 if (k is not None and k < 0) or "출금" in tx.raw_type else 1
        tx.qty = Z
        return

    if ev == "해외세금환급":
        tx.market = "해외"
        v = fx_net if fx_net is not None else (fx_gross if fx_gross is not None else tx.qty)
        tx.G = abs(v or Z)
        tx.qty = Z
        return

    if ev in ("환전_원화외화", "환전_외화원화"):
        tx.market = "해외"
        g = fx_net if fx_net is not None else fx_gross
        if g is None and ccy != "KRW":
            g = tx.qty          # 삼성: 거래수량 칸에 외화금액
        tx.G = abs(g or Z)
        k = krw_net if krw_net is not None else (krw_gross if krw_gross is not None else krw_inout)
        tx.I = abs(k or Z)
        if not tx.name or tx.name.upper() == ccy:
            tx.name = ""
        tx.qty = Z
        if ccy == "KRW" and tx.G == 0 and tx.I == 0 and tx.qty:
            tx.I = tx.qty
        return

    if ev in ("배당", "이자"):
        if fx:
            tx.market = "해외"
            tax = abs(_n(r, "외화제세금") or Z)
            if fx_gross is not None and fx_gross != 0:
                g = abs(fx_gross)
            elif fx_net is not None:
                g = abs(fx_net) + tax if tax else abs(fx_net)
            else:
                g = tx.qty
            tx.G, tx.H = g, tax
        else:
            tx.market = "국내"
            tax = sum((abs(_n(r, k) or Z) for k in ("제세금", "소득세", "지방세")), Z)
            if krw_gross is not None and krw_gross != 0:
                g = abs(krw_gross)
            elif krw_net is not None:
                g = abs(krw_net) + tax
            elif krw_inout is not None:
                g = abs(krw_inout) + tax
            else:
                g = Z
            tx.I, tx.J = g, tax
        tx.qty = Z
        if not fx and tx.name.upper() in ("", "KRW"):
            tx.name = ""
        if tx.name.upper() == ccy:
            tx.name = ""
        return

    if ev == "해외원천세":
        tx.market = "해외"
        v = fx_net if fx_net is not None else (fx_gross if fx_gross is not None else tx.qty)
        tx.H = abs(v or Z)
        tx.qty = Z
        return

    # 입금 · 출금 · 검토 · 미분류
    if fx:
        v = fx_net if fx_net is not None else fx_gross
        if v is None and ev in ("입금", "출금"):
            v = tx.qty
        tx.G = abs(v or Z)
    else:
        v = krw_net if krw_net is not None else (krw_inout if krw_inout is not None else krw_gross)
        tx.I = abs(v or Z)
        tx.J = krw_cost
    if ev in ("입금", "출금"):
        tx.qty = Z
        if not tx.name or tx.name.upper() == ccy:
            tx.name = ""


_CCY_NAMES = {"미국달러", "홍콩달러", "일본엔", "중국위안", "유로", "USD", "HKD", "JPY", "CNY", "EUR", "달러"}


def reorder_auto_fx(txs):
    """원화주문 자동환전(미래에셋 '외화매수원화출금(미수)'): 같은 날 해외 매수가 먼저 찍히고 환전이 뒤에 온다.
    그대로 두면 외화 잔액이 중간에 음수가 되어 장부환율을 잡을 수 없다. 같은 날 같은 통화의 환전(원화→외화)을
    그날 첫 해외 매수 앞으로 옮기고, 환전 행에 있던 증권사 외화 잔액은 원래 환전 바로 앞의 외화 거래에 붙인다."""
    out = list(txs)
    i = 0
    while i < len(out):
        t = out[i]
        if t.event == "환전_원화외화" and t.ccy != "KRW":
            first = None
            for j in range(i - 1, -1, -1):
                u = out[j]
                if u.date != t.date:
                    break
                if u.ccy == t.ccy and u.event == "매수" and u.market == "해외":
                    first = j
            if first is not None:
                prev = i - 1
                while prev >= first and out[prev].ccy != t.ccy:
                    prev -= 1
                if t.fx_bal is not None and prev >= first:
                    out[prev].fx_bal, t.fx_bal = t.fx_bal, None
                out.pop(i)
                out.insert(first, t)
                t.notes.append("자동환전: 같은 날 해외 매수 앞으로 옮김")
        i += 1
    return out


def _merge_pairs(txs):
    """해외 배당 + 세금출금(해외), 매매 수량행 + 대금행, 환전 원화 행·외화 행 짝, 분할체결을 한 거래로 합친다."""
    used = set()
    # 0) 환전 원화 행·외화 행(미래에셋 외화매수원화출금 + 외화매수외화입금, 토스 환전원화출금 + 환전외화입금)
    for i, t in enumerate(txs):
        if i in used or t.event not in ("환전_원화외화", "환전_외화원화") or (t.I == 0) == (t.G == 0):
            continue
        need_fx = t.G == 0
        cand = [j for j, u in enumerate(txs) if j not in used and j != i and u.event == t.event and u.date == t.date
                and ((u.G > 0 and u.I == 0) if need_fx else (u.I > 0 and u.G == 0))]
        if cand:
            j = min(cand, key=lambda x: abs(x - i))
            u = txs[j]
            fxleg, krleg = (u, t) if need_fx else (t, u)
            keep, drop = (i, j) if i < j else (j, i)
            k = txs[keep]
            k.G, k.I, k.ccy = fxleg.G, krleg.I, fxleg.ccy
            k.fx_bal = fxleg.fx_bal
            k.krw_bal = krleg.krw_bal
            k.notes.append(f"환전 짝 행({txs[drop].src})를 합침")
            used.add(drop)
    for i, t in enumerate(txs):
        if i not in used and t.event in ("환전_원화외화", "환전_외화원화") and (t.G == 0 or t.I == 0):
            t.notes.append("환전 금액(외화 또는 원화)이 비어 있다. 짝 행이 없다")
    # 0-2) 분할체결: 앞 행은 정산금액이 비고 마지막 행에 묶음 정산금액이 실린 경우(키움)
    for i, t in enumerate(txs):
        if i in used or t.event not in ("매수", "매도"):
            continue
        fx = t.ccy != "KRW"
        net_missing = (t._fx_net is None) if fx else (t._krw_net is None)
        if not net_missing:
            continue
        j = i + 1
        group = [i]
        while j < len(txs) and txs[j].event == t.event and txs[j].date == t.date and txs[j].name == t.name and txs[j].ccy == t.ccy:
            group.append(j)
            if ((txs[j]._fx_net is not None) if fx else (txs[j]._krw_net is not None)):
                break
            j += 1
        last = txs[group[-1]]
        if len(group) > 1 and ((last._fx_net is not None) if fx else (last._krw_net is not None)):
            if fx:
                gsum = sum((txs[k].G for k in group), Z)
                net = abs(last._fx_net)
                last.H = sum((txs[k].H for k in group), Z) if last._fx_cost_given else abs(net - gsum)
                last.G = gsum
            else:
                gsum = sum((txs[k].I for k in group), Z)
                last.J = sum((txs[k].J for k in group), Z)
                last.I = gsum
            last.qty = sum((txs[k].qty for k in group), Z)
            last.notes = [n for n in last.notes if "다르다" not in n]
            last.notes.append(f"분할체결 {len(group)}행을 합침")
            for k in group[:-1]:
                used.add(k)
    # 1) 배당·이자 + 현지세
    for i, t in enumerate(txs):
        if t.event != "해외원천세":
            continue
        cand = [j for j, u in enumerate(txs)
                if j not in used and u.event in ("배당", "이자") and u.ccy == t.ccy
                and u.date == t.date and (u.name == t.name or not t.name) and u.H == 0]
        # 사이에 같은 통화를 움직인 다른 행이 있으면 합치지 않는다(중간 잔액 대사가 깨진다).
        # 그때는 현지세를 따로 전표로 낸다(해외원천세 이벤트).
        cand = [j for j in cand if not any(
            txs[m].ccy == t.ccy and m not in used and txs[m].event not in ("검토_입출고", "검토_기업행위")
            for m in range(min(i, j) + 1, max(i, j)))]
        if cand:
            j = cand[0]
            txs[j].H = t.H
            if i > j:   # 뒤에 온 행의 잔액이 두 행을 다 반영한 잔액이다
                txs[j].fx_bal = t.fx_bal if t.fx_bal is not None else txs[j].fx_bal
                txs[j].krw_bal = t.krw_bal if t.krw_bal is not None else txs[j].krw_bal
            txs[j].notes.append(f"현지세 행({t.src})을 합침")
            used.add(i)
    # 2-0) 묶음 대금행(미래에셋): 같은 날·같은 방향·같은 통화 수량행마다 거래금액·수수료·세금이 다 있고,
    #      대금행은 그날 합계 한 행이다. 수량행 합계 = 대금행 합계이면 수량행을 그대로 거래로 쓰고
    #      대금행은 확인용으로 지운다. 대금행의 잔액은 묶음 마지막 거래에 붙인다.
    groups = {}
    move_to = {}          # 대금행 마지막 위치 → 그 자리로 옮길 수량행들(증권사 원장에서 현금은 대금행 위치에서 움직인다)
    moved = set()
    for i, t in enumerate(txs):
        if i in used or t.event not in ("매매_수량행", "매매_대금행"):
            continue
        side = "매도" if ("매도" in t.raw_type or "판매" in t.raw_type) else "매수"
        groups.setdefault((t.date, side, t.ccy), {"Q": [], "P": []})["Q" if t.event == "매매_수량행" else "P"].append(i)
    for (d, side, ccy), g in groups.items():
        Q, P = g["Q"], g["P"]
        if not Q or not P:
            continue
        fx = ccy != "KRW"

        def gross(t):
            if t._rec is None:
                return Z
            return abs(_n(t._rec, "외화거래금액") or Z) if fx else abs(_n(t._rec, "거래금액") or Z)

        if not all(gross(txs[i]) for i in Q):
            continue
        qsum = sum((gross(txs[i]) for i in Q), Z)
        psum = sum((gross(txs[j]) for j in P), Z)
        if abs(qsum - psum) > (Decimal("0.011") if fx else 1):
            continue
        for i in Q:
            t = txs[i]
            t.event = side
            t.G = t.H = t.I = t.J = Z
            _amounts(t, t._rec, "해외" if fx else "")
            t.notes.append(f"묶음 대금행 {len(P)}행과 합계 대조({qsum})")
        last = max(Q)
        # 대금행의 실제 입출금액(증권사가 센트·원으로 끊은 값)과 수량행 합계의 끝수 차이를 묶음 마지막 거래 비용에 넣는다
        if fx:
            pnet = [abs(txs[j]._fx_net) for j in P if txs[j]._fx_net is not None]
            if len(pnet) == len(P):
                calc = sum(((txs[i].G + txs[i].H) if side == "매수" else (txs[i].G - txs[i].H)) for i in Q)
                diff = sum(pnet, Z) - calc
                if diff and abs(diff) < Decimal("0.05") * len(Q):
                    txs[last].H += diff if side == "매수" else -diff
                    txs[last].notes.append(f"외화 끝수 {diff} 를 수수료에 반영(대금행 출입금액 기준)")
        else:
            pnet = [abs(txs[j]._krw_net) for j in P if txs[j]._krw_net is not None]
            if len(pnet) == len(P):
                calc = sum(((txs[i].I + txs[i].J) if side == "매수" else (txs[i].I - txs[i].J)) for i in Q)
                diff = sum(pnet, Z) - calc
                if diff and abs(diff) <= 10 * len(Q):
                    txs[last].J += diff if side == "매수" else -diff
                    txs[last].notes.append(f"원화 끝수 {diff} 를 비용에 반영(대금행 출입금액 기준)")
        for j in P:
            u = txs[j]
            if u.krw_bal is not None:
                txs[last].krw_bal = u.krw_bal
            if u.fx_bal is not None:
                txs[last].fx_bal = u.fx_bal
            used.add(j)
        if max(P) > last:
            move_to[max(P)] = list(Q)
            moved.update(Q)
    # 2) 수량행 + 대금행(1:1)
    for i, t in enumerate(txs):
        if t.event != "매매_수량행" or i in used:
            continue
        side = "매도" if "매도" in t.raw_type else "매수"
        # 대금행(매수출금·매도입금)에는 종목명이 없는 양식이 있다(미래에셋). 이름이 같거나 비어 있으면 후보로
        # 보고, 같은 이름 → 가까운 행 순으로 고른다.
        cand = [j for j, u in enumerate(txs) if j not in used and j != i and u.event == "매매_대금행"
                and u.date == t.date and (u.name == t.name or not u.name or u.name in _CCY_NAMES)
                and side in u.raw_type and u.ccy == t.ccy]
        cand.sort(key=lambda j: (txs[j].name != t.name, abs(j - i)))
        t.event = side
        t.market = "해외" if t.ccy != "KRW" else "국내"
        if cand:
            u = txs[cand[0]]
            if t.ccy == "KRW":
                net = u.I
                t.J = u.J
                t.I = net + t.J if side == "매도" else net - t.J
            else:
                g = abs(u._fx_gross) if u._fx_gross else (t.qty * t.price).quantize(Decimal("0.01"))
                n = abs(u._fx_net) if u._fx_net is not None else None
                t.G = g
                t.H = abs(n - g) if n is not None else Z
                t.fx_bal = u.fx_bal if u.fx_bal is not None else t.fx_bal
            t.krw_bal = u.krw_bal if u.krw_bal is not None else t.krw_bal
            t.notes.append(f"대금행({u.src})을 합침")
            used.add(cand[0])
        else:
            t.notes.append("짝이 되는 대금행이 없다")
            t.event = "검토_입출고"
    for i, t in enumerate(txs):
        if t.event == "매매_대금행" and i not in used:
            t.event = "미분류"
            t.notes.append("짝이 되는 수량행이 없는 매매 대금행")
    out = []
    for i, t in enumerate(txs):
        if i in move_to:
            out.extend(txs[q] for q in move_to[i])
        if i in used or i in moved:
            continue
        out.append(t)
    return out


def load_standard_csv(path: Path):
    """AI·OCR 경로: templates/표준거래표_양식.csv 를 그대로 Txn 으로 읽는다."""
    import csv
    from read_source import _decode
    text = _decode(path.read_bytes())
    rows = list(csv.DictReader(text.splitlines()))
    rules = load_rules()
    out = []
    for i, r in enumerate(rows, 2):
        ccy = (r.get("통화") or "KRW").strip().upper() or "KRW"
        ev = (r.get("이벤트") or "").strip()
        raw = (r.get("원문거래종류") or "").strip()
        mkt = ""
        if not ev:
            ev, mkt = classify(raw, ccy, rules)
        tx = Txn(date=parse_date(r.get("일자")), settle=parse_date(r.get("결제일")), raw_type=raw, event=ev,
                 ccy=ccy, code=(r.get("종목코드") or "").strip(), name=(r.get("종목명") or "").strip(),
                 src=f"{path.name}:{i}")
        for k in ("qty", "price", "G", "H", "I", "J"):
            col = {"qty": "수량", "price": "단가", "G": "외화총액", "H": "외화비용", "I": "원화금액", "J": "원화비용"}[k]
            setattr(tx, k, abs(to_num(r.get(col)) or Z))
        # 금액이 하나뿐인 이벤트는 어느 칸에 적었든 읽는다. 현지세 · 환급을 외화비용 칸에 적거나,
        # 입출금 · 이자를 외화총액이 아닌 칸에 적는 일이 있다(2026-11-08 독립 정답 대조 사례 09)
        if ev == "해외세금환급" and not tx.G and tx.H:
            tx.G, tx.H = tx.H, Z
        elif ev == "해외원천세" and not tx.H and tx.G:
            tx.H, tx.G = tx.G, Z
        tx.krw_bal = to_num(r.get("증권사원화잔액"))
        tx.fx_bal = to_num(r.get("증권사외화잔액"))
        tx.hold_qty = to_num(r.get("증권사잔고수량"))
        tx.counterparty = (r.get("상대방") or "").strip()
        # 시장 칸은 사람이 옮겨 적어 「미국」「US」「해외주식」 처럼 들어온다(2026-11-08 독립 정답 대조에서 드러남).
        # 외화 거래이거나 국내가 아닌 시장 이름이면 해외로 본다
        m_raw = (r.get("시장") or mkt or "").strip()
        if ccy != "KRW" or (m_raw and not re.match(r"^(국내|KRX|코스피|코스닥|KOSPI|KOSDAQ|코넥스|K-?OTC|장내|장외)", m_raw, re.I)):
            tx.market = "해외" if (ccy != "KRW" or m_raw) else "국내"
        else:
            tx.market = "국내"
        if tx.date is None:
            raise ValueError(f"{path.name} {i}행: 일자를 읽지 못했다")
        out.append(tx)
    out = _merge_pairs(out)
    out.sort(key=lambda x: x.date)
    for i, x in enumerate(out, 1):
        x.seq = i
        x.key = x.code or x.name
    return out
