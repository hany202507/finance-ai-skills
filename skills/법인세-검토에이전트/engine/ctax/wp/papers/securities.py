"""12 유가증권: 단기매매 · 단기투자 평가손익(유보)과 처분 때 추인, 매도가능증권 평가손익(기타포괄손익) 양쪽조정, 지분법손익(유보).

법인세법 제42조 제1항: 자산을 평가해 장부가액을 바꿔도 세법상 장부가액은 평가 전 가액이다. 그래서
- 당기손익으로 잡은 평가이익은 익금불산입(△유보), 평가손실은 손금불산입(유보)
- 그 증권을 팔면 쌓인 유보를 추인한다(전기 △유보는 익금산입, 전기 유보는 손금산입). 적요에 「전기 평가」 가 든 처분손익 줄이
  있으면 그 금액을 쓴다. 10-25: 전기 유보는 기초에 가진 종목의 평가액이라 당기에 산 종목을 판 것으로는 추인하지 않는다. 그래서
  비율은 「기초 보유분 처분 장부가 ÷ 기초 장부가」 다. 종목은 자산 계정 줄 적요의 첫 낱말(「가상화학 5,000주」 → 가상화학)로
  가르고, 종목마다 일자 차례로 「누적 처분 장부가 - 누적 취득가」 가 가장 컸을 때의 금액을 기초 보유분 처분으로 센다(그해에 산 것보다
  더 판 만큼은 기초에 가진 주식이다. 기초 보유 종목을 일부만 팔고 다시 사고판 경우는 이보다 클 수 있어 하한이다). 전기
  50호(을)에 종목별 유보(「단기매매증권(가상전자)」 꼴)가 있으면 그 종목을 판 해에 그 유보를 먼저 추인하고 나머지만 비율로 나눈다.
  적요로 종목을 가르지 못하면 전처럼 총평균법(시행령 제75조 제2항 · 제74조 제4항 준용, 무신고 평가방법) 비율
  「처분 장부가 ÷ (기초 장부가 + 당기 취득)」 을 쓴다. 어느 쪽이든 노란 칸이고 확인 줄을 낸다(종목별 유보 명세로 정한다).
- 기타포괄손익(매도가능증권평가손익)의 증감은 익금산입(기타)과 익금불산입(유보)의 짝, 줄면 반대 짝(신고본 관례)
- 지분법이익은 익금불산입(△유보), 지분법손실은 손금불산입(유보), 지분법 주식에서 받은 배당은 익금산입(유보)
- 매도가능증권 종목 유보(손상 · 처분손실 등)는 그대로 둔다. 10-21: 과목 이름과 같은 자산 계정의 기초 보유분을 모두 처분했으면 전액
  추인이 기본값이고, 일부만 처분했으면 총평균법 비율 추정액을 확인 줄에만 적는다(과목에 「처분」 이 든 유보는 계정을 잇지 않아 전처럼 0)

values: items(과목마다 한 줄) 과 합계. items[i] 의 키는 시트 G 열 `i.<키>` 칸과 같다.
"""
from __future__ import annotations

import re
from fractions import Fraction

from ... import xlsx as X
from ..books import Books, Line, rd
from ..model import Adj, LineRow, Paper
from ..sheet import Book, Rows, adj_table, head, ledger, notes

NAME = "유가증권"
FORMS = ["15", "50을"]
LEDGER_CHECK = False

SEC = re.compile(r"증권|주식|투자자산|투자증권|금융상품|유가|펀드|수익증권")
NOT_SEC = re.compile(r"외화|환산|재고|충당|파생|대손|이연|미수|보증금|퇴직|대여")
OCI = re.compile(r"매도가능|공정가치|금융자산")
EQUITY = "지분법"
SUFFIX = re.compile(r"(평가이익|평가손실|평가손익|평가익|평가손|평가차익|평가차손|처분이익|처분손실|처분익|처분손)$")
PRIOR_VAL = re.compile(r"전기\s*평가|전기분\s*평가|평가(이익|손실|익|손)\s*제거")
DIVIDEND = re.compile(r"배당")
CASH = re.compile(r"현금|예금|당좌|금융상품")
# 적요 첫 낱말(종목 이름). 따옴표 · 대괄호 머리는 건너뛰고, 수량 · 매도 같은 낱말 앞에서 끊는다
STOCK_HEAD = re.compile(r"^[\s\"'\[\]\d\-.]*([^\s\d\",]+)")
STOCK_TAIL = re.compile(r"(주식)?(매도|매수|매입|처분|양도|취득|대금)$")
STOCK_GENERIC = re.compile(r"^(주식|증권|유가증권|단기매매증권|매도가능증권|평가|주식평가|평가이익|평가손실|매도|매수|매입|처분)")
COMPANY_MARK = re.compile(r"\(주\)|㈜|주식회사|\(유\)")
STOCK_RESERVE = re.compile(r"^(.+?)\s*[(\[](.+?)[)\]]$")    # 50호(을) 종목별 유보 과목 「단기매매증권(가상전자)」

KIND_NAME = {"trading": "단기매매 · 단기투자 평가", "oci": "기타포괄손익 양쪽조정", "equity": "지분법", "hold": "매도가능증권 종목 유보"}


def basis(rates: dict) -> list[tuple]:
    r = rates["securities"]
    return [(f"유가증권 {k}", r[key]["value"], r[key]["basis"], r[key]["grade"], None)
            for k, key in (("평가손익 불인정", "valuation_disallowed"), ("평가방법(무신고)", "default_method"),
                           ("기타포괄손익 양쪽조정", "oci_both_sides"), ("지분법손익", "equity_method"))]


# 공용 도우미(fx 조서도 쓴다) ------------------------------------------------------------------------

def norm(s: str) -> str:
    return re.sub(r"[\s()\[\]·]", "", s or "")


def vouchers(b: Books) -> dict[tuple[str, str], list[Line]]:
    """전표(일자, 번호) → 줄. 손익대체 줄은 빠져 있다(books.read_journal)."""
    out: dict[tuple[str, str], list[Line]] = {}
    for ln in b.lines:
        out.setdefault((ln.date, ln.no), []).append(ln)
    return out


def prior_reserves(b: Books) -> dict[str, int]:
    """전기 50호(을) 과목 → 기말(= 당기 기초). 같은 과목이 둘이면 더한다."""
    out: dict[str, int] = {}
    for r in (b.prior or {}).get("reserves", []) or []:
        subj = r.get("subject") or ""
        out[subj] = out.get(subj, 0) + int(r.get("closing") or 0)
    return out


def match_prior(names: list[str], prior: dict[str, int], used: set[str] | None = None) -> str | None:
    """이름 후보 차례로 전기 유보 과목과 같은 것(띄어쓰기 · 괄호 무시)을 찾는다."""
    by_norm = {norm(k): k for k in prior}
    for n in names:
        k = by_norm.get(norm(n))
        if k is not None and (used is None or k not in used):
            return k
    return None


def stock_name(memo: str) -> str:
    """자산 계정 줄 적요의 종목 이름(「가상화학 5,000주」 → 가상화학, 「가상에너지 6,870주 매도」 → 가상에너지).
    「주식평가이익」 처럼 종목이 아닌 머리말이면 빈 글. 회사 표기((주) · 주식회사)는 뺀다(수입배당금 조서와 이름을 맞춘다)."""
    m = STOCK_HEAD.match(COMPANY_MARK.sub("", memo or ""))
    if not m:
        return ""
    name = STOCK_TAIL.sub("", m.group(1))
    return "" if len(name) < 2 or STOCK_GENERIC.match(name) else name


def stock_flows(b: Books, vs, assets: list[dict], skip_codes: set[str]) -> dict[str, dict]:
    """종목 → {buy, sell, open_sell, mixed}. 일자 · 전표번호 차례로 본다. open_sell 은 「누적 처분 - 누적 취득」 의 가장 큰 값
    (그해에 산 것보다 더 판 만큼, 기초 보유분 처분의 하한), mixed 는 그 종목을 그해에 사기도 했는지다(사고판 종목은 하한이 실제보다
    작을 수 있다). 평가 · 지분법 손익과 같은 전표의 줄은 뺀다(_flows 와 같다). 종목을 읽지 못한 줄은 빈 글 종목에 모은다."""
    out: dict[str, dict] = {}
    for ln in sorted(b.lines_of(assets), key=lambda x: (x.date, x.no)):
        if any(o.account in skip_codes for o in vs.get((ln.date, ln.no), [])):
            continue
        name = stock_name(ln.memo)
        # 같은 종목을 다르게 적은 줄(「가상씨앤에스」 · 「가상씨엔에스」, 「가상」 · 「가상솔루션즈」)은 먼저 나온 이름에 모은다
        name = next((k for k in out if k and name and _alias(k, name)), name)
        st = out.setdefault(name, {"buy": 0, "sell": 0, "open_sell": 0, "mixed": False})
        st["buy"] += ln.debit
        st["sell"] += ln.credit
        st["open_sell"] = max(st["open_sell"], st["sell"] - st["buy"])
        st["mixed"] = st["mixed"] or ln.debit > 0
    return out


def _same_stock(a: str, b: str) -> bool:
    a, b = norm(COMPANY_MARK.sub("", a)), norm(COMPANY_MARK.sub("", b))
    return bool(a and b) and (a == b or (min(len(a), len(b)) >= 2 and (a in b or b in a)))


def _alias(a: str, b: str) -> bool:
    """같은 종목의 다른 표기. 한쪽이 다른 쪽을 품거나, 다섯 글자 이상이고 길이가 같으며 한 글자만 다르다(「가상씨앤에스」 · 「가상씨엔에스」).
    네 글자 이름은 한 글자 차이가 다른 회사일 수 있어(「가상전자」 · 「가상전기」) 잇지 않는다."""
    if _same_stock(a, b):
        return True
    a, b = norm(a), norm(b)
    return len(a) == len(b) >= 5 and sum(x != y for x, y in zip(a, b)) == 1


def gain_of(a: dict) -> int:
    """손익 계정의 이익 쪽 금액(수익 계정은 금액 그대로, 비용 계정은 부호를 바꿈)."""
    amt = int(a.get("amount") or 0)
    return amt if a.get("class") == "수익" else -amt


# 분류 ---------------------------------------------------------------------------------------------

def reserve_kind(subject: str) -> str | None:
    if EQUITY in subject:
        return "equity"
    if OCI.search(subject) and "평가" in subject:
        return "oci"
    if "매도가능" in subject or "처분" in subject or "손상" in subject:
        return "hold"
    if SEC.search(subject) and not NOT_SEC.search(subject):
        return "trading"
    return None


def valuation_accounts(b: Books) -> list[dict]:
    return [a for a in b.accounts(cls=("수익", "비용")) if "평가" in a["name"] and SEC.search(a["name"])
            and not NOT_SEC.search(a["name"]) and EQUITY not in a["name"]]


def oci_accounts(b: Books) -> list[dict]:
    return [a for a in b.accounts(cls="자본") if ("평가" in a["name"] and (OCI.search(a["name"]) or SEC.search(a["name"])))
            or EQUITY in a["name"]]


def counterpart_asset(b: Books, vs: dict, acct: dict) -> dict | None:
    """평가 손익 줄과 같은 전표의 반대쪽 자산 계정 중 금액이 가장 큰 것."""
    weight: dict[str, int] = {}
    for ln in b.lines_of([acct]):
        for other in vs.get((ln.date, ln.no), []):
            a = b.by_code.get(other.account) or {}
            if a.get("class") != "자산" or other.account == ln.account:
                continue
            if (ln.credit > 0 and other.debit > 0) or (ln.debit > 0 and other.credit > 0):
                weight[other.account] = weight.get(other.account, 0) + other.debit + other.credit
    if not weight:
        return None
    return b.by_code[max(weight, key=lambda k: weight[k])]


def assets_named(b: Books, name: str) -> list[dict]:
    target = norm(SUFFIX.sub("", norm(name)))
    return [a for a in b.accounts(cls="자산") if norm(a["name"]) in (norm(name), target)]


# 계산 ---------------------------------------------------------------------------------------------

def compute(p: Paper, b: Books) -> None:
    vs = vouchers(b)
    prior = prior_reserves(b)
    used: set[str] = set()
    items: list[dict] = []
    by_subject: dict[str, dict] = {}

    def item(kind: str, subject: str) -> dict:
        it = by_subject.get(subject)
        if it is None:
            it = {"kind": kind, "subject": subject, "기초유보": prior.get(subject, 0), "assets": [], "valuation": [],
                  "oci": [], "equity": []}
            by_subject[subject] = it
            items.append(it)
            if subject in prior:
                used.add(subject)
        return it

    # 1) 당기손익 평가 계정 → 과목(전기 유보 과목 > 평가 계정 이름 > 자산 계정 이름)
    for a in valuation_accounts(b):
        asset = counterpart_asset(b, vs, a)
        names = [a["name"], SUFFIX.sub("", norm(a["name"]))] + ([asset["name"]] if asset else [])
        subj = match_prior(names, prior) or (asset["name"] if asset else SUFFIX.sub("", norm(a["name"])) or a["name"])
        it = item("trading", subj)
        it["valuation"].append(a)
        if asset and asset["code"] not in {x["code"] for x in it["assets"]}:
            it["assets"].append(asset)
    # 2) 지분법 손익 · 자산
    eq_pl = [a for a in b.accounts(cls=("수익", "비용")) if EQUITY in a["name"]]
    eq_assets = [a for a in b.accounts(cls="자산") if EQUITY in a["name"]]
    eq_prior = [k for k in prior if reserve_kind(k) == "equity" and prior[k]]
    if eq_pl or eq_prior or any(int(a.get("credit") or 0) for a in eq_assets):
        subj = eq_prior[0] if eq_prior else (eq_assets[0]["name"] if eq_assets else "지분법적용투자주식")
        it = item("equity", subj)
        it["equity"] = eq_pl
        it["assets"] = eq_assets
    # 3) 기타포괄손익(자본) 양쪽조정
    for a in oci_accounts(b):
        if int(a.get("opening") or 0) == int(a.get("closing") or 0):
            continue
        subj = match_prior([a["name"]], prior, used) or a["name"]
        it = item("oci", subj)
        it["oci"].append(a)
    # 4) 전기 유보 중 아직 잇지 못한 유가증권 과목
    for subj, amt in prior.items():
        if subj in by_subject or not amt:
            continue
        m = STOCK_RESERVE.match(subj)
        parent = next((it for it in items if it["kind"] == "trading" and m and norm(it["subject"]) == norm(m.group(1))), None)
        if parent is not None:
            # 종목별 유보(10-25). 과목 줄을 따로 만들지 않고 그 과목의 종목 유보로 둔다
            parent.setdefault("종목유보", {})[m.group(2)] = amt
            parent["기초유보"] += amt
            used.add(subj)
            continue
        kind = reserve_kind(subj)
        if kind in ("trading", "hold"):
            it = item(kind, subj)
            if kind == "trading" or "처분" not in subj:
                it["assets"] = assets_named(b, subj)
        elif kind == "oci":
            item("oci", subj)

    adjs: list[Adj] = []
    for i, it in enumerate(items):
        it["i"] = i
        {"trading": _trading, "oci": _oci, "equity": _equity, "hold": _hold}[it["kind"]](p, b, vs, it, adjs)

    p.adjustments = adjs
    accts = {}
    for it in items:
        for a in it["assets"] + it["valuation"] + it["oci"] + it["equity"]:
            accts[a["code"]] = a
    p.accounts = list(accts.values())
    _lines(p, b, vs, items)
    tot = {k: sum(it.get(k, 0) for it in items) for k in ("평가이익", "평가손실", "추인", "기초유보", "기말유보")}
    p.values = {"items": [{k: v for k, v in it.items() if k not in ("assets", "valuation", "oci", "equity")}
                          | {"accounts": [a["code"] for a in it["assets"] + it["valuation"] + it["oci"] + it["equity"]]}
                          for it in items],
                "평가이익 익금불산입": tot["평가이익"], "평가손실 손금불산입": tot["평가손실"], "처분 추인": tot["추인"],
                "기타포괄 증가": sum(it.get("기타포괄증가", 0) for it in items),
                "기타포괄 감소": sum(it.get("기타포괄감소", 0) for it in items),
                "지분법이익": sum(it.get("지분법이익", 0) for it in items),
                "지분법손실": sum(it.get("지분법손실", 0) for it in items),
                "기초유보": tot["기초유보"], "기말유보": tot["기말유보"]}
    p.extra["items"] = items
    if items:
        p.notes.append("유가증권 평가손익은 법인세법 제42조 제1항에 따라 세법상 장부가액에 넣지 않습니다. 당기손익 평가이익은 "
                       "익금불산입(△유보), 평가손실은 손금불산입(유보), 처분하면 쌓인 유보를 추인합니다")
    p.settle(bool(items))


def _signed_reversal(adjs, it, key, rev, what):
    """전기 유보 추인 줄. 전기 △유보(음수)면 익금산입, 유보(양수)면 손금산입. 50호(을) 감소 열에 기초와 같은 부호로."""
    s, R = it["subject"], it["기초유보"]
    if R < 0:
        adjs.append(Adj("가산", s, rev, "유보", f"{s} 처분 추인", f"전기 익금불산입한 {what} 중 당기 처분분 익금산입", key, s, "감소", -1))
    elif R > 0:
        adjs.append(Adj("차감", s, rev, "유보", f"{s} 처분 추인", f"전기 손금불산입한 {what} 중 당기 처분분 손금산입", key, s, "감소", 1))


def _flows(b: Books, vs, assets: list[dict], skip_codes: set[str]) -> tuple[int, int, int, int]:
    """자산 계정의 (기초, 취득, 처분 장부가, 적요 「전기 평가」 처분손익). 평가 · 지분법 손익과 같은 전표의 줄은 뺀다."""
    opening = sum(int(a.get("opening") or 0) for a in assets)
    buy = sell = memo = 0
    seen = set()
    for ln in b.lines_of(assets):
        others = vs.get((ln.date, ln.no), [])
        if any(o.account in skip_codes for o in others):
            continue
        buy += ln.debit
        sell += ln.credit
        if (ln.date, ln.no) in seen:
            continue
        seen.add((ln.date, ln.no))
        for o in others:
            cls = (b.by_code.get(o.account) or {}).get("class")
            if cls in ("수익", "비용") and PRIOR_VAL.search(o.memo):
                memo += abs(o.debit - o.credit)
    return opening, buy, sell, memo


def _opening_reversal(it: dict, R: int, o: int, stocks: dict) -> tuple[int, Fraction, str, list]:
    """기초 보유분으로 나눈 추인액(10-25). (추인액, 비율, 방법, 기초 보유 종목 [(종목, 처분 장부가)]). 방법이 빈 글이면 적요로
    종목을 가르지 못해 쓰지 않는다. 종목별 유보는 그 종목을 판 해에 먼저 추인하고, 나머지 유보만 기초 보유분 처분 비율로 나눈다."""
    named_sell = sum(st["sell"] for k, st in stocks.items() if k)
    total_sell = sum(st["sell"] for st in stocks.values())
    sold = [(k, st["open_sell"]) for k, st in stocks.items() if k and st["open_sell"]]
    per = it.get("종목유보") or {}
    if not total_sell or named_sell < total_sell or o <= 0:
        return 0, Fraction(0), "", sold
    if sum(v for _, v in sold) > o + max(1000, o // 100):
        return 0, Fraction(0), "초과", sold        # 기초 장부가보다 많이 팔았다: 같은 종목을 다른 이름으로 적어 가르기가 틀렸다
    signed = 0
    rest_r = R - sum(per.values())
    for name, amt in per.items():
        if any(_same_stock(name, k) and st["open_sell"] for k, st in stocks.items() if k):
            signed += amt
    rest_open = sum(v for k, v in sold if not any(_same_stock(n, k) for n in per))
    ratio = Fraction(min(rest_open, o), o)
    signed += rd(abs(rest_r) * ratio) * (1 if rest_r >= 0 else -1)
    if signed and (signed > 0) != (R > 0):
        return 0, ratio, "부호", sold
    return min(abs(signed), abs(R)), ratio, "종목별" if per else "기초 보유분", sold


def _trading(p: Paper, b: Books, vs, it: dict, adjs: list) -> None:
    i, s, R = it["i"], it["subject"], it["기초유보"]
    skip = {a["code"] for a in valuation_accounts(b)}
    o, buy, sell, memo = _flows(b, vs, it["assets"], skip)
    stocks = stock_flows(b, vs, it["assets"], skip)
    base = o + buy
    ratio = Fraction(min(sell, base), base) if base > 0 else Fraction(0)
    by_open, open_ratio, how, sold = _opening_reversal(it, R, o, stocks)
    if R == 0:
        calc = 0
    elif memo:
        calc = min(abs(R), memo)
    elif how in ("종목별", "기초 보유분"):
        calc, ratio = by_open, open_ratio
    else:
        calc = rd(abs(R) * ratio)
    key = f"전기 유보 추인/{s}"
    rev = p.take(b, key, calc, "int") if R else 0
    gain = sum(max(0, gain_of(a)) for a in it["valuation"])
    loss = sum(max(0, -gain_of(a)) for a in it["valuation"])
    closing = (R + rev if R < 0 else R - rev) - gain + loss
    open_sell = sum(v for _, v in sold)
    it.update({"기초장부가": o, "취득": buy, "처분": sell, "기초보유처분": open_sell, "비율": float(ratio), "추인방법": how or "총평균",
               "적요추인": memo, "추정추인": calc, "추인": rev, "평가이익": gain, "평가손실": loss, "기말유보": closing})
    if R:
        _signed_reversal(adjs, it, key, rev, "평가이익" if R < 0 else "평가손실")
    adjs.append(Adj("차감", s, gain, "유보", f"{s} 평가이익", "당기 평가이익 익금불산입", f"{i}.평가이익", s, "증가", -1))
    adjs.append(Adj("가산", s, loss, "유보", f"{s} 평가손실", "당기 평가손실 손금불산입", f"{i}.평가손실", s, "증가", 1))
    if R and key not in p.overridden:
        mixed = [k for k, st in stocks.items() if k and st["open_sell"] and st["mixed"]]
        if memo:
            p.notes.append(f"{s}: 적요에 「전기 평가」 가 든 처분손익 {memo:,}원으로 전기 유보 {R:,}원 중 {calc:,}원을 추인했습니다")
        elif how in ("종목별", "기초 보유분"):
            names = ", ".join(f"{k} {v:,}원" for k, v in sold) or "없음"
            text = (f"{s}: 전기 유보 {R:,}원은 기초에 가진 종목의 평가액이라 기초 보유분 처분 비율(처분 장부가 {open_sell:,} ÷ 기초 "
                    f"장부가 {o:,} = {float(ratio):.2%})로 {calc:,}원 추인했습니다(법인세법 제42조 제1항). 종목마다 그해에 산 것보다 더 판 "
                    f"금액을 기초 보유분 처분으로 보았습니다: {names}")
            if how == "종목별":
                text += f". 전기 50호(을) 종목별 유보({', '.join(it['종목유보'])})는 그 종목을 판 것으로 보아 먼저 추인했습니다"
            if mixed:
                text += (f". {', '.join(mixed)} 은 그해에 사기도 해서 기초 보유분 처분이 이보다 클 수 있습니다(산 것보다 더 판 금액만 넣음)")
            p.confirm.append(text + ". 종목별 유보 명세로 확인하고 노란 칸을 고치세요")
        elif how == "초과":
            p.confirm.append(f"{s}: 적요 종목으로 센 기초 보유분 처분 {open_sell:,}원이 기초 장부가 {o:,}원보다 커서(같은 종목을 다른 이름으로 "
                             f"적은 줄이 있는 듯합니다) 총평균법 비율(처분 장부가 {sell:,} ÷ (기초 {o:,} + 취득 {buy:,}) = {float(ratio):.2%})로 "
                             f"{calc:,}원 추인했습니다. 당기 매수분이 섞인 어림이라 종목별 유보 명세로 노란 칸을 고치세요")
        elif how == "부호":
            p.confirm.append(f"{s}: 종목별 유보로 나눈 추인액의 부호가 전기 유보 {R:,}원과 달라 총평균법 비율 {calc:,}원을 넣었습니다. "
                             "종목별 유보 명세로 노란 칸을 고치세요")
        elif calc and calc != abs(R):
            p.confirm.append(f"{s}: 전기 유보 {R:,}원 중 처분분을 총평균법 비율(처분 장부가 {sell:,} ÷ (기초 {o:,} + 취득 {buy:,}) "
                             f"= {float(ratio):.2%})로 {calc:,}원 추인했습니다. 종목별 유보 명세로 확인하고 노란 칸을 고치세요")
        elif calc:
            p.notes.append(f"{s}: 기초 보유분을 모두 처분해 전기 유보 {R:,}원을 전액 추인했습니다")
        elif not it["assets"]:
            p.confirm.append(f"{s}: 전기 유보 {R:,}원에 맞는 장부 계정을 찾지 못해 추인하지 않았습니다. 처분했으면 노란 칸에 넣으세요")


def _oci(p: Paper, b: Books, vs, it: dict, adjs: list) -> None:
    i, s, R = it["i"], it["subject"], it["기초유보"]
    accts = it["oci"]
    opening = sum(int(a.get("opening") or 0) for a in accts)
    closing_book = sum(int(a.get("closing") or 0) for a in accts)
    credit = opening - closing_book            # 대변(자본 증가) 쪽 증감
    up, down = max(0, credit), max(0, -credit)
    name = accts[0]["name"] if accts else s
    it.update({"기초잔액": opening, "기말잔액": closing_book, "증감": credit, "기타포괄증가": up, "기타포괄감소": down,
               "기말유보": R - credit, "추인": 0, "평가이익": 0, "평가손실": 0})
    adjs.append(Adj("가산", name, up, "기타", f"{name} 증가 기타", "기타포괄손익 증가분 익금산입(자본 직접 계상)", f"{i}.기타포괄증가"))
    adjs.append(Adj("차감", s, up, "유보", f"{name} 증가 유보", "평가로 늘어난 장부가액 익금불산입", f"{i}.기타포괄증가", s))
    adjs.append(Adj("차감", name, down, "기타", f"{name} 감소 기타", "기타포괄손익 감소분 익금불산입(자본 직접 계상)", f"{i}.기타포괄감소"))
    adjs.append(Adj("가산", s, down, "유보", f"{name} 감소 유보", "평가로 줄어든 장부가액 익금산입", f"{i}.기타포괄감소", s))
    if not accts and R:
        p.notes.append(f"{s}: 기타포괄손익 계정이 장부에 없거나 변동이 없어 전기 유보 {R:,}원을 그대로 둡니다")
    elif accts:
        p.notes.append(f"{name}: 기타포괄손익 증감 {credit:,}원을 익금산입(기타) · 익금불산입(유보) 짝으로 넣었습니다. "
                       "법인세 효과를 뺀 금액으로 적었으면 자산 쪽 평가액과 다를 수 있습니다")


def _equity(p: Paper, b: Books, vs, it: dict, adjs: list) -> None:
    i, s, R = it["i"], it["subject"], it["기초유보"]
    gain = sum(max(0, gain_of(a)) for a in it["equity"])
    loss = sum(max(0, -gain_of(a)) for a in it["equity"])
    eq_codes = {a["code"] for a in it["equity"]}
    dividend = other = 0
    for ln in b.lines_of(it["assets"]):
        others = vs.get((ln.date, ln.no), [])
        if any(o.account in eq_codes for o in others) or ln.credit <= 0:
            continue
        if any(DIVIDEND.search(o.memo) for o in others):
            dividend += ln.credit
        else:
            other += ln.credit
    key = f"전기 유보 추인/{s}"
    rev = p.take(b, key, 0, "int") if R else 0
    closing = (R + rev if R < 0 else R - rev) - gain + loss + dividend
    it.update({"지분법이익": gain, "지분법손실": loss, "배당": dividend, "기타감소": other, "추인": rev,
               "평가이익": 0, "평가손실": 0, "기말유보": closing})
    if R:
        _signed_reversal(adjs, it, key, rev, "지분법손익")
    adjs.append(Adj("차감", s, gain, "유보", f"{s} 지분법이익", "지분법이익 익금불산입", f"{i}.지분법이익", s, "증가", -1))
    adjs.append(Adj("가산", s, loss, "유보", f"{s} 지분법손실", "지분법손실 손금불산입", f"{i}.지분법손실", s, "증가", 1))
    adjs.append(Adj("가산", s, dividend, "유보", f"{s} 배당 익금산입", "지분법 주식 배당금(장부가액 차감) 익금산입",
                    f"{i}.배당", s, "증가", 1))
    if dividend:
        p.notes.append(f"{s}: 지분법 주식 배당금 {dividend:,}원을 익금산입(유보)했습니다. 수입배당금 익금불산입(13 수입배당금, "
                       "법인세법 제18조의2) 대상인지 함께 보세요")
    if other:
        p.confirm.append(f"{s}: 지분법손익 · 배당 말고 대변 {other:,}원이 있습니다. 처분이면 전기 유보 추인액을 노란 칸에 넣으세요")


def _hold_flows(b: Books, vs, assets: list[dict]) -> tuple[int, int, int]:
    """매도가능증권 계정의 (기초, 취득, 처분 장부가). 평가(기타포괄손익 · 평가손익 계정)만 있는 전표는 취득 · 처분으로 세지 않는다.
    처분은 같은 전표에 처분손익 계정이나 현금 · 예금 계정이 있는 대변 줄이다(기타포괄손익을 함께 지우는 처분 전표도 센다)."""
    marks = {a["code"] for a in oci_accounts(b) + valuation_accounts(b)}
    opening = sum(int(a.get("opening") or 0) for a in assets)
    buy = sell = 0
    for ln in b.lines_of(assets):
        others = [o for o in vs.get((ln.date, ln.no), []) if o is not ln]
        valued = any(o.account in marks for o in others)
        sold = any("처분" in ((b.by_code.get(o.account) or {}).get("name") or "") or CASH.search(
            (b.by_code.get(o.account) or {}).get("name") or "") for o in others)
        if ln.credit and (sold or not valued):
            sell += ln.credit
        if ln.debit and not valued:
            buy += ln.debit
    return opening, buy, sell


def _hold(p: Paper, b: Books, vs, it: dict, adjs: list) -> None:
    """매도가능증권 종목 유보(손상 · 평가 전 장부가 차이 등). 10-21: 당기에 그 계정 증권을 처분했으면 총평균법 처분 비율
    「처분 장부가 ÷ (기초 장부가 + 당기 취득)」 을 계산한다(_trading 과 같은 비율, 시행령 제75조 제2항 · 제74조 제4항 준용).
    비율이 1(모두 처분)일 때만 전액 추인이 기본값이고, 그 밖에는 추정액을 확인 줄에 적고 기본값 0 이다. 단기 상품이 계속 도는
    계정에서 비율로 나누면 특정 종목 유보를 크게 잘못 추인한다(평가 회사 한 곳)."""
    s, R = it["subject"], it["기초유보"]
    key = f"전기 유보 추인/{s}"
    o = buy = sell = 0
    if it["assets"]:
        o, buy, sell = _hold_flows(b, vs, it["assets"])
    base = o + buy
    ratio = Fraction(min(sell, base), base) if base > 0 and sell > 0 else Fraction(0)
    calc = rd(abs(R) * ratio) if R else 0
    # 종목 유보는 특정 종목(손상 등)의 것이라 비율 추정은 기본값으로 넣지 않는다. 기초 보유분을 모두 처분했을 때만 전액 추인한다
    default = calc if ratio == 1 else 0
    rev = p.take(b, key, default, "int")
    it.update({"기초장부가": o, "취득": buy, "처분": sell, "비율": float(ratio), "추정추인": calc,
               "추인": rev, "평가이익": 0, "평가손실": 0, "기말유보": R + rev if R < 0 else R - rev})
    _signed_reversal(adjs, it, key, rev, "금액")
    if key in p.overridden:
        return
    if calc and not default:
        p.confirm.append(f"{s}: 당기 처분이 있습니다(처분 장부가 {sell:,} ÷ (기초 {o:,} + 취득 {buy:,}) = {float(ratio):.2%}). 전기 유보 "
                         f"{R:,}원을 이 비율로 나누면 {calc:,}원이지만 종목 유보는 특정 종목의 것이라 추인하지 않았습니다. 유보가 처분한 종목의 "
                         "것이면 종목별 유보 명세로 그 금액을 노란 칸에 넣으십시오")
    elif calc:
        p.notes.append(f"{s}: 기초 보유분을 모두 처분해 전기 유보 {R:,}원을 전액 추인했습니다")
    else:
        p.notes.append(f"{s}: 전기 유보 {R:,}원은 종목을 처분할 때 추인합니다. 당기에 처분했으면 노란 칸에 추인액을 넣으세요")


def _lines(p: Paper, b: Books, vs, items: list[dict]) -> None:
    """원장 검토 줄: 평가 · 지분법 · 기타포괄손익 계정 줄과 유가증권 처분손익 줄."""
    codes = {a["code"] for it in items for a in it["valuation"] + it["oci"] + it["equity"]}
    disp = [a for a in b.accounts(cls=("수익", "비용")) if "처분" in a["name"] and SEC.search(a["name"])
            and not NOT_SEC.search(a["name"])]
    label = {}
    for it in items:
        for a in it["valuation"]:
            label[a["code"]] = f"평가({it['subject']})"
        for a in it["oci"]:
            label[a["code"]] = "기타포괄손익"
        for a in it["equity"]:
            label[a["code"]] = "지분법"
    for a in disp:
        label.setdefault(a["code"], "처분손익")
        codes.add(a["code"])
    for ln in b.lines_of([b.by_code[c] for c in codes if c in b.by_code]):
        why = "적요에 전기 평가분 제거" if PRIOR_VAL.search(ln.memo) else ""
        p.lines.append(LineRow(ln, label.get(ln.account, ""), "", why=why))


# 시트 ---------------------------------------------------------------------------------------------

def write(bk: Book, p: Paper) -> None:
    s = head(bk, p)
    row = 5
    row = s.section(row, "1. 계정")
    X.header(s.ws, row, ["코드", "계정", "구분", "기초", "차변", "대변", "기말(재무제표)"], col=1)
    row += 1
    for a in p.accounts:
        s.put(row, 1, a["code"])
        s.put(row, 2, a["name"])
        s.put(row, 3, a.get("class"))
        for col, k in ((4, "opening"), (5, "debit"), (6, "credit")):
            s.put(row, col, int(a.get(k) or 0), money=True)
        s.put(row, 7, int(a.get("amount") or 0), money=True)
        row += 1
    if not p.accounts:
        s.put(row, 2, "유가증권 평가 · 지분법 · 기타포괄손익 계정이 없습니다")
        row += 1
    row += 1
    row, _, _ = ledger(bk, s, row, p, "", title="2. 원장 검토(평가 · 처분 · 지분법 · 기타포괄손익 줄)")
    row = s.section(row, "3. 과목별 유보 계산")
    X.note(s.ws, row, "노란 칸: 전기 유보 추인액(엔진 기본값은 적요 「전기 평가」 처분손익, 기초 보유분 처분 비율 또는 총평균법 처분 비율)")
    row += 1
    r = Rows(bk, s, p, row)
    g = r.g
    for it in p.extra["items"]:
        i, subj, kind = it["i"], it["subject"], it["kind"]
        r.row = s.section(r.row, f"3-{i + 1}. {subj} ({KIND_NAME[kind]})")
        key = f"전기 유보 추인/{subj}"
        if kind == "trading":
            r.put(f"{i}.기초유보", "기초 유보(전기 50호(을) 기말)", it["기초유보"])
            r.put(f"{i}.기초장부가", "기초 장부가액", it["기초장부가"])
            r.put(f"{i}.취득", "당기 취득(평가 전표 뺀 차변)", it["취득"])
            r.put(f"{i}.처분", "당기 처분 장부가(평가 전표 뺀 대변)", it["처분"])
            how = it.get("추인방법")
            if how in ("기초 보유분", "종목별"):
                r.put(f"{i}.기초보유처분", "기초 보유분 처분 장부가(종목마다 그해에 산 것보다 더 판 금액)", it["기초보유처분"])
                r.put(f"{i}.비율", "처분 비율 = 기초 보유분 처분 ÷ 기초 장부가",
                      f"=IF({g(f'{i}.기초장부가')}>0,MIN(1,{g(f'{i}.기초보유처분')}/{g(f'{i}.기초장부가')}),0)", fmt="0.00%")
            else:
                r.put(f"{i}.비율", "처분 비율(총평균법) = 처분 ÷ (기초 + 취득)",
                      f"=IF({g(f'{i}.기초장부가')}+{g(f'{i}.취득')}>0,MIN(1,{g(f'{i}.처분')}/({g(f'{i}.기초장부가')}+{g(f'{i}.취득')})),0)",
                      fmt="0.00%")
            r.put(f"{i}.적요추인", "적요 「전기 평가」 처분손익", it["적요추인"])
            if how == "종목별" and not it["적요추인"]:
                r.put(f"{i}.추정추인", "추인액 계산(종목별 유보를 먼저 추인하고 나머지 유보 × 비율, 확인 줄 참고)", it["추정추인"])
            else:
                r.put(f"{i}.추정추인", "추인액 계산(적요 금액이 있으면 그 금액, 없으면 |기초 유보| × 비율)",
                      f"=IF({g(f'{i}.기초유보')}=0,0,IF({g(f'{i}.적요추인')}>0,MIN(ABS({g(f'{i}.기초유보')}),{g(f'{i}.적요추인')}),"
                      f"ROUNDDOWN(ABS({g(f'{i}.기초유보')})*{g(f'{i}.비율')},0)))")
            if it["기초유보"]:
                r.put(key, "전기 유보 추인액(노란 칸)", p.inputs[key], kind="input", input_kind="int")
                rev = g(key)
            else:
                r.put(f"{i}.추인", "전기 유보 추인액(기초 유보 없음)", 0)
                rev = g(f"{i}.추인")
            r.put(f"{i}.평가이익", "당기 평가이익(익금불산입 · △유보)", it["평가이익"])
            r.put(f"{i}.평가손실", "당기 평가손실(손금불산입 · 유보)", it["평가손실"])
            b0 = g(f"{i}.기초유보")
            r.put(f"{i}.기말유보", "기말 유보", f"=IF({b0}<0,{b0}+{rev},{b0}-{rev})-{g(f'{i}.평가이익')}+{g(f'{i}.평가손실')}")
        elif kind == "oci":
            r.put(f"{i}.기초유보", "기초 유보(전기 50호(을) 기말)", it["기초유보"])
            r.put(f"{i}.기초잔액", "기타포괄손익 기초 잔액(차변 양수)", it["기초잔액"])
            r.put(f"{i}.기말잔액", "기타포괄손익 기말 잔액(차변 양수)", it["기말잔액"])
            r.put(f"{i}.증감", "자본 증가 쪽 증감(기초 - 기말)", f"={g(f'{i}.기초잔액')}-{g(f'{i}.기말잔액')}")
            r.put(f"{i}.기타포괄증가", "증가: 익금산입(기타) · 익금불산입(△유보)", f"=MAX(0,{g(f'{i}.증감')})")
            r.put(f"{i}.기타포괄감소", "감소: 익금불산입(기타) · 익금산입(유보)", f"=MAX(0,-{g(f'{i}.증감')})")
            r.put(f"{i}.기말유보", "기말 유보", f"={g(f'{i}.기초유보')}-{g(f'{i}.증감')}")
        elif kind == "equity":
            r.put(f"{i}.기초유보", "기초 유보(전기 50호(을) 기말)", it["기초유보"])
            r.put(f"{i}.지분법이익", "지분법이익(익금불산입 · △유보)", it["지분법이익"])
            r.put(f"{i}.지분법손실", "지분법손실(손금불산입 · 유보)", it["지분법손실"])
            r.put(f"{i}.배당", "지분법 주식 배당 수령(익금산입 · 유보)", it["배당"])
            if it["기초유보"]:
                r.put(key, "전기 유보 추인액(처분했을 때, 노란 칸)", p.inputs[key], kind="input", input_kind="int")
                rev = g(key)
            else:
                r.put(f"{i}.추인", "전기 유보 추인액(기초 유보 없음)", 0)
                rev = g(f"{i}.추인")
            b0 = g(f"{i}.기초유보")
            r.put(f"{i}.기말유보", "기말 유보",
                  f"=IF({b0}<0,{b0}+{rev},{b0}-{rev})-{g(f'{i}.지분법이익')}+{g(f'{i}.지분법손실')}+{g(f'{i}.배당')}")
        else:
            r.put(f"{i}.기초유보", "기초 유보(전기 50호(을) 기말)", it["기초유보"])
            r.put(f"{i}.기초장부가", "기초 장부가액(같은 이름 자산 계정)", it["기초장부가"])
            r.put(f"{i}.취득", "당기 취득(평가 전표 뺀 차변)", it["취득"])
            r.put(f"{i}.처분", "당기 처분 장부가(처분손익 · 예금이 있는 전표의 대변)", it["처분"])
            r.put(f"{i}.비율", "처분 비율(총평균법) = 처분 ÷ (기초 + 취득)",
                  f"=IF(AND({g(f'{i}.처분')}>0,{g(f'{i}.기초장부가')}+{g(f'{i}.취득')}>0),MIN(1,{g(f'{i}.처분')}/"
                  f"MAX(1,{g(f'{i}.기초장부가')}+{g(f'{i}.취득')})),0)", fmt="0.00%")
            r.put(f"{i}.추정추인", "추인액 계산(|기초 유보| × 비율)", f"=ROUNDDOWN(ABS({g(f'{i}.기초유보')})*{g(f'{i}.비율')},0)")
            r.put(key, "전기 유보 추인액(처분했을 때, 노란 칸)", p.inputs[key], kind="input", input_kind="int")
            b0 = g(f"{i}.기초유보")
            r.put(f"{i}.기말유보", "기말 유보", f"=IF({b0}<0,{b0}+{g(key)},{b0}-{g(key)})")
        r.row += 1
    if not p.extra["items"]:
        s.put(r.row, 1, "유가증권 평가 · 지분법 · 기타포괄손익 조정이 없습니다")
        r.row += 1
    items = p.extra["items"]
    if items:
        r.row = s.section(r.row, f"3-{len(items) + 1}. 합계")
        r.put("기초유보", "기초 유보 합계", "=" + "+".join(g(f"{it['i']}.기초유보") for it in items))
        r.put("기말유보", "기말 유보 합계", "=" + "+".join(g(f"{it['i']}.기말유보") for it in items))
    row = adj_table(bk, s, r.row + 1, p, title="4. 세무조정 · 소득처분")
    notes(s, row, p)
