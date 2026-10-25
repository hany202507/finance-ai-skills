"""10 대손충당금: 대손충당금 한도초과 손금불산입 · 전기 한도초과 추인(유보), 대손금 부인(노란 칸). 34호.

계산(34호 1. 대손충당금조정과 같은 흐름)
  ① 채권잔액     설정대상 채권(외상매출금 · 받을어음 · 미수금 · 미수수익 · 대여금 등)의 (17) 장부가액 + (18) 대손금 부인누계
                 - (20) 설정제외 채권(노란 칸)
  ② 설정률       max(1%, 대손실적률), 대손실적률 = 당기 대손금(시인) ÷ 직전 사업연도말 채권가액(시행령 제61조 제2 · 3항)
  ③ 한도         ① × ②, 원 미만 버림
  ④ 당기계상액   대손충당금 대변(설정) 합계, ⑤ 보충액 = 기말 잔액 - ④, ⑥ = ④ + ⑤ = 기말 잔액
  ⑦ 한도초과     ⑥ - ③ (손금불산입 · 유보)
  ⑧ ~ ⑮          기초 잔액 - 전기 부인누계 - 대손 상계 - 보충액 = 환입할 금액, 회사 환입액과의 차이(⑮)가 과다환입(△)이면
                 전기 부인누계 추인(손금산입 · 유보)
대손금은 대손충당금 차변 중 같은 전표에서 채권이 대변인 줄(충당금 상계)과 충당금을 거치지 않은 대손상각비 줄(직접 대손)이다.
줄마다 노란 칸 「부인 여부」 기본값은 X(시인)이고 O 면 채권 계정 과목으로 손금불산입 · 유보한다.

대손충당금 차변이라도 같은 전표에 대손상각비 음수 줄 · 환입 수익 대변 줄이 있거나 적요가 「환입」 이면 환입(⑭)이다. 매달
대손상각비를 음수로 적어 충당금을 줄이는 회사가 있다. 이런 줄은 채권 대변이 같은 전표에 섞여 있어도 대손으로 보지 않는다.

전기 유보 처리(노란 칸 「전기 유보 처리」, 그대로 · 추인)
  추인    전기 대손충당금 유보(⑩)를 전액 추인하고 기말 잔액 전체로 한도초과를 다시 계산한다(법인세법 제34조 제3항). 위 ④ ~ ⑮.
  그대로  전기 유보를 추인하지 않는다. ⑤ 보충액 · ⑥ 회사계상액에서 그대로 둔 유보(⑩)를 빼고 남은 충당금만 한도와 비교한다.
          ⑬ = ⑧ - ⑩ - ⑪ - ⑫ 가 회사 환입액과 같아져 ⑮ 가 0 이다.
  기본값은 「추인」 이다. 전기 신고서가 그 유보를 한 해 동안 그대로 두었을 때만(`prior_static`: 전기 50호(을) 대손충당금 줄이
  기초 = 기말 · 감소 0 · 증가 0 이고 전기 15호에 대손충당금 줄이 없음) 기본값이 「그대로」 이고 조서는 「확인 필요」 다.
  10-21: 다만 회사가 보충법(기초 충당금을 환입하지 않고 당기에 차액만 설정)이면 전기가 그대로 두었어도 기본값은 「추인」 이고
  확인 줄을 낸다(values 「보충법」).
  그 유보가 한도초과액인지, 특정 채권의 대손금 부인액인지, 설정 대상이 아닌 채권(법인세법 제34조 제2항)의 충당금인지는
  엔진이 정하지 않는다. 「그대로」 일 때 당기 설정 · 대손 상계 · 환입이 그 유보와 같은 채권의 것인지도 가리지 않고 확인 줄에 금액을 적는다.

특수관계인 대여 계정(가지급금 · 주임종 등)을 현금 없이 매출채권으로 옮긴 전표(예 기말 「반제처리」)는 대체액 중 기말에 남은
금액을 그 매출채권의 설정제외 기본값에 더한다(법인세법 제34조 제2항 · 제19조의2 제2항 제2호). 원래 계정의 설정제외 기본값과
같은 규칙(인정이자 조서 특수관계인 「예」, 이름부터 특수관계인 대여인 계정은 「확인 필요」 도)을 쓴다.
"""
from __future__ import annotations

import re
from datetime import date
from fractions import Fraction

from ... import xlsx as X
from ..books import Books, Line, frac, rate, rd
from ..model import Adj, LineRow, Paper, line_keys
from ..sheet import Book, Rows, adj_table, forms_table, head, notes
from .loan_interest import LOAN, NOT_LOAN, TIED, excluded_for_bad_debt, partner_name, related_of

NAME = "대손충당금"
FORMS = ["34", "15", "50을"]
LEDGER_CHECK = False
PICK = "부인 여부"
MODE = "전기 유보 처리"
KEEP, REVERSE = "그대로", "추인"

RECV = re.compile(r"외상매출금|받을어음|매출채권|공사미수금|분양미수금|미수금|미수수익|대여금|주\.?\s?임\.?\s?종|가지급금|"
                  r"대출채권|양수채권|NPL|할부")
NOT_RECV = re.compile(r"대손충당금|현재가치|선급|국고|부가세|선납")
TRADE = re.compile(r"외상매출금|받을어음|매출채권|공사미수금|분양미수금|미수금")     # 대여금이 옮겨 갈 수 있는 매출채권 · 미수금
CASH = re.compile(r"현금|예금|당좌|적금|금융상품")
REVERSAL_WORD = re.compile(r"환입")
WRITE_OFF = "충당금 상계"
DIRECT = "직접 대손"


def basis(rates: dict) -> list[tuple]:
    bd = rates["bad_debt"]
    return [("대손충당금 최저 설정률", bd["min_rate"]["value"], bd["min_rate"]["basis"], bd["min_rate"]["grade"], "0%")]


def receivable_accounts(b: Books) -> list[dict]:
    return [a for a in b.accounts(cls="자산") if RECV.search(a.get("name", "")) and not NOT_RECV.search(a.get("name", ""))]


def allowance_accounts(b: Books) -> list[dict]:
    return [a for a in b.accounts(cls="자산", any_of=("대손충당금",))]


def _vouchers(b: Books) -> dict[tuple, list[Line]]:
    out: dict[tuple, list[Line]] = {}
    for ln in b.all_lines():
        out.setdefault((ln.date, ln.no), []).append(ln)
    return out


def _norm(s: str) -> str:
    return re.sub(r"\s", "", s or "")


def _prior_reserve(b: Books, pred) -> list[dict]:
    return [r for r in (b.prior or {}).get("reserves", []) or [] if pred(r.get("subject") or "")]


def prior_static(b: Books) -> bool:
    """전기 신고서가 대손충당금 유보를 한 해 동안 그대로 두었는가. 전기 50호(을) 대손충당금 줄(기말 잔액이 있는 줄)이 모두
    기초 = 기말 · 감소 0 · 증가 0 이고 합계가 양수이며, 전기 15호에 대손충당금 가산 · 차감 줄이 없을 때 참이다."""
    rows = [r for r in _prior_reserve(b, lambda s: "대손충당금" in s) if int(r.get("closing") or 0)]
    if not rows or sum(int(r["closing"]) for r in rows) <= 0:
        return False
    for r in rows:
        if r.get("opening") is None or int(r["opening"]) != int(r["closing"]):
            return False
        if int(r.get("decrease") or 0) or int(r.get("increase") or 0):
            return False
    for a in (b.prior or {}).get("adjustments", []) or []:
        if "대손충당금" in _norm(a.get("subject")) or "대손충당금" in _norm(a.get("note")):
            return False
    return True


def _name(b: Books, ln: Line) -> str:
    return b.by_code.get(ln.account, {}).get("name") or ln.account_name


def _is_reversal(b: Books, ln: Line, group: list[Line], exp_codes: set) -> bool:
    """대손충당금 차변 줄이 환입인가. 같은 전표에 대손상각비 음수 줄 · 환입 수익 대변 줄이 있거나 적요 「환입」."""
    if REVERSAL_WORD.search(ln.memo or ""):
        return True
    for x in group:
        if x is ln:
            continue
        if x.account in exp_codes and x.debit - x.credit < 0:
            return True
        a = b.by_code.get(x.account, {})
        if a.get("class") == "수익" and REVERSAL_WORD.search(_name(b, x)) and x.credit - x.debit > 0:
            return True
    return False


def _is_loan(b: Books, code: str) -> bool:
    a = b.by_code.get(code) or {}
    name = a.get("name", "")
    return a.get("class") == "자산" and bool(LOAN.search(name)) and not NOT_LOAN.search(name)


def _fy_end(b: Books) -> date | None:
    try:
        return date.fromisoformat(b.info.get("fy_end") or "")
    except ValueError:
        return None


def loan_transfers(b: Books, vouchers: dict, recv_codes: dict) -> list[dict]:
    """특수관계인 대여 계정 대변 · 매출채권 차변이 현금 없이 함께 있는 전표(대여금을 매출채권으로 옮김).

    줄마다 {date, no, memo, from, from_name, partner, to, to_name, to_partner, amount, later, remaining, related, excluded, days}.
    later 는 대체 뒤 같은 매출채권 · 같은 거래처 대변(회수), remaining 은 기말에 남은 대체액, excluded 는 설정제외 기본값에 넣는지
    (인정이자 조서 특수관계인 「예」, 이름부터 특수관계인 대여인 계정은 「확인 필요」 도). days 는 대체일부터 사업연도 끝까지 일수."""
    end = _fy_end(b)
    out = []
    used: dict[tuple, int] = {}             # (매출채권, 거래처) → 앞선 대체에 이미 쓴 회수액(먼저 옮긴 것부터 회수로 본다)
    for (d, no), group in sorted(vouchers.items()):
        if any(CASH.search(_name(b, x)) for x in group):
            continue
        loans = [x for x in group if x.credit - x.debit > 0 and _is_loan(b, x.account)]
        trades = [x for x in group if x.debit - x.credit > 0 and x.account in recv_codes and not _is_loan(b, x.account)
                  and TRADE.search(_name(b, x))]
        if not loans or not trades:
            continue
        room = [[t, t.debit - t.credit] for t in trades]
        for ln in loans:
            left = ln.credit - ln.debit
            acct = b.by_code.get(ln.account, {})
            pname = partner_name(ln.partner, acct)
            rel = related_of(b, pname)
            for slot in room:
                t, cap = slot
                amt = min(left, cap)
                if amt <= 0:
                    continue
                slot[1] -= amt
                left -= amt
                got = sum(x.credit - x.debit for x in b.lines_of([b.by_code[t.account]])
                          if x.date > t.date and x.partner == t.partner and x.credit - x.debit > 0)
                later = min(amt, max(0, got - used.get((t.account, t.partner), 0)))
                used[(t.account, t.partner)] = used.get((t.account, t.partner), 0) + later
                try:
                    days = (end - date.fromisoformat(d[:10])).days + 1 if end else 0
                except ValueError:
                    days = 0
                out.append({"date": d, "no": no, "memo": ln.memo or t.memo, "from": ln.account, "from_name": acct.get("name", ""),
                            "partner": pname, "to": t.account, "to_name": _name(b, t), "to_partner": t.partner,
                            "amount": amt, "later": later, "remaining": amt - later, "related": rel,
                            "excluded": rel == "예" or (bool(TIED.search(acct.get("name", ""))) and rel == "확인 필요"),
                            "days": max(0, days)})
    return out


def compute(p: Paper, b: Books) -> None:
    allow = allowance_accounts(b)
    recv = receivable_accounts(b)
    expense = b.accounts(cls="비용", any_of=("대손상각",))
    allow_codes = {a["code"] for a in allow}
    recv_codes = {a["code"]: a for a in recv}
    exp_codes = {a["code"] for a in expense}
    vouchers = _vouchers(b)

    # 충당금 계정별 움직임 · 대손금 줄
    moves = []
    other_up = 0
    odd_direct = 0
    neg_reversal, neg_count = 0, 0          # 대손상각비 음수 · 환입 수익으로 줄인 충당금(대손 아님)
    for a in allow:
        m = {"code": a["code"], "name": a["name"], "opening": -int(a.get("opening") or 0), "set": 0, "write_off": 0,
             "reversal": 0, "closing": -int(a.get("closing") or 0)}
        for ln in b.lines_of([a]):
            net = ln.debit - ln.credit
            group = vouchers.get((ln.date, ln.no), [])
            if net < 0:
                m["set"] += -net
                if not any(x.account in exp_codes for x in group):
                    other_up += -net
            elif net > 0:
                if _is_reversal(b, ln, group, exp_codes):
                    m["reversal"] += net
                    neg_reversal += net
                    neg_count += 1
                    continue
                hit = next((x for x in group if x.account in recv_codes and x.credit - x.debit > 0), None)
                if hit:
                    m["write_off"] += net
                    p.lines.append(LineRow(ln, WRITE_OFF, "X", pick2=hit.account,
                                           why=f"같은 전표에서 {recv_codes[hit.account]['name']} 대변"))
                else:
                    m["reversal"] += net
        moves.append(m)
    for ln in b.lines_of(expense):
        if ln.debit - ln.credit <= 0:
            continue
        group = vouchers.get((ln.date, ln.no), [])
        if any(x.account in allow_codes and x.credit - x.debit > 0 for x in group):
            continue                                       # 충당금 설정
        hit = next((x for x in group if x.account in recv_codes and x.credit - x.debit > 0), None)
        if hit:
            p.lines.append(LineRow(ln, DIRECT, "X", pick2=hit.account, why=f"같은 전표에서 {recv_codes[hit.account]['name']} 대변"))
        else:
            other = ", ".join(sorted({x.account_name for x in group if x is not ln})) or "없음"
            p.lines.append(LineRow(ln, DIRECT, "X", pick2="", why=f"대손상각비(상대 계정 {other}, 채권 아님)"))
            odd_direct += ln.debit - ln.credit
    p.lines.sort(key=lambda r: (r.line.date, r.line.no, r.line.account))
    line_keys(p)
    for r in p.lines:
        r.default = r.pick
        r.pick = "O" if p.take(b, f"{PICK}/{r.key}", r.pick, "pick") == "O" else "X"
        p.inputs.pop(f"{PICK}/{r.key}", None)
        p.defaults.pop(f"{PICK}/{r.key}", None)
    denied = {}
    for r in p.lines:
        if r.pick == "O":
            denied[r.pick2] = denied.get(r.pick2, 0) + r.line.amount
    total_bd = sum(r.line.amount for r in p.lines)
    denied_total = sum(denied.values())
    allowed_bd = total_bd - denied_total

    # 특수관계인 대여금을 매출채권으로 옮긴 전표: 기말에 남은 대체액을 그 매출채권 설정제외 기본값에 더한다
    moved_rows = loan_transfers(b, vouchers, recv_codes)
    moved: dict[str, int] = {}
    for m in moved_rows:
        if m["excluded"]:
            moved[m["to"]] = moved.get(m["to"], 0) + m["remaining"]

    # 채권 표(34호 (16) ~ (21))
    table = []
    for a in recv:
        code, name = a["code"], a["name"]
        prior = sum(int(r.get("closing") or 0) for r in _prior_reserve(b, lambda s, n=name: _norm(s) == _norm(n))
                    if int(r.get("closing") or 0) > 0)
        book = int(a.get("closing") or 0)
        opening = int(a.get("opening") or 0)
        if not (book or opening or prior or denied.get(code)):
            continue
        ex_close, ex_open = excluded_for_bad_debt(b, a)
        ex_moved = min(moved.get(code, 0), max(0, book - ex_close))
        ex_close += ex_moved
        prior = p.take(b, f"전기 부인누계/{code}", prior, "int")
        reversal = p.take(b, f"대손금 부인 추인/{code}", 0, "int") if prior else 0
        exclude = p.take(b, f"설정제외/{code}", ex_close, "int")
        cur = denied.get(code, 0)
        acc = prior + cur - reversal
        table.append({"code": code, "name": name, "17": book, "전기부인누계": prior, "당기부인": cur, "추인": reversal,
                      "18": acc, "19": book + acc, "20": exclude, "21": book + acc - exclude, "기초": opening,
                      "기초제외": ex_open})
        if ex_close and not p.overridden.get(f"설정제외/{code}"):
            if ex_moved:
                part = f"{ex_close:,}원은" if ex_moved == ex_close else f"{ex_close:,}원 중 {ex_moved:,}원은"
                p.notes.append(f"{name} 설정제외 채권 기본값 {part} 특수관계인 대여 계정에서 현금 없이 옮겨 온 금액 중 기말에 남은 "
                               "것입니다(아래 확인 줄). 실제 매출채권이면 설정제외 칸을 고치세요")
            if ex_close - ex_moved:
                p.notes.append(f"{name} 설정제외 채권 기본값 {ex_close - ex_moved:,}원은 특수관계인 대여로 본 잔액입니다(인정이자 조서 "
                               "특수관계인 칸, 가지급금 · 주임종 계정은 「확인 필요」 도 넣음). 업무와 관련된 대여면 0 으로 고치세요")
    unknown_denied = denied.get("", 0)
    receivable = sum(t["21"] for t in table)
    prev = p.take(b, "직전채권잔액", sum(t["기초"] + t["전기부인누계"] - t["기초제외"] for t in table), "int")
    loss_ratio = Fraction(allowed_bd, prev) if prev > 0 else Fraction(0)
    min_rate = frac(rate(b.rates, "bad_debt", "min_rate"))
    set_rate = max(min_rate, loss_ratio)
    limit = rd(receivable * set_rate)

    opening = sum(m["opening"] for m in moves)
    closing = sum(m["closing"] for m in moves)
    set_ = sum(m["set"] for m in moves)
    write_off = sum(m["write_off"] for m in moves)
    reversal_co = sum(m["reversal"] for m in moves)
    prior_rows = _prior_reserve(b, lambda s: "대손충당금" in s)
    prior_allow = sum(int(r.get("closing") or 0) for r in prior_rows)
    subj = prior_rows[0]["subject"] if prior_rows else (allow[0]["name"] if allow else "대손충당금")
    denied_prior = p.take(b, "전기부인누계", max(0, min(prior_allow, opening)), "int")
    # 전기 유보 처리. 전기 신고서가 유보를 그대로 두었으면 기본값이 「그대로」, 아니면 「추인」
    static = prior_static(b)
    # 10-21 보충법: 기초 충당금을 환입하지 않고 두고(회사 환입 < 기초 - 대손 상계) 당기에 차액만 설정했으면, 전기 신고서가 유보를
    # 그대로 두었어도 기본값은 「추인」 이다. 남은 충당금은 다음 사업연도에 익금이라(법인세법 제34조 제3항) 그 안의 전기 부인액은
    # 손금산입하고 기말 잔액 전체로 한도초과를 다시 계산한다(34호 보충법 ⑤ · ⑫)
    supplemental = static and set_ > 0 and reversal_co < max(0, opening - write_off)
    mode = p.take(b, MODE, KEEP if static and not supplemental else REVERSE)
    keep = mode == KEEP
    kept = denied_prior if keep else 0             # 그대로 둔 전기 유보
    booked = closing - kept                        # ⑥ 회사계상액 계
    supplement = booked - set_
    excess = max(0, booked - limit)
    to_return = opening - 0 - denied_prior - write_off - supplement
    over_under = to_return - reversal_co
    reversal = 0 if keep else min(denied_prior, max(0, -over_under))
    # 다른 처리를 골랐을 때의 금액(확인 줄 · 메모에 적는다)
    other_excess = max(0, (closing if keep else closing - denied_prior) - limit)
    other_reversal = (min(denied_prior, max(0, -(opening - denied_prior - write_off - (closing - set_) - reversal_co)))
                      if keep else 0)

    p.accounts = allow + recv
    p.values = {"채권잔액": receivable, "대손금": total_bd, "대손금시인": allowed_bd, "대손금부인": denied_total,
                "직전채권잔액": prev, "대손실적률": float(loss_ratio), "최저설정률": float(min_rate), "설정률": float(set_rate),
                "한도": limit, "당기계상": set_, "보충액": supplement, "충당금기말": closing, "유보유지": kept,
                "회사계상계": booked, "한도초과": excess,
                "충당금기초": opening, "기중환입": 0, "전기부인누계": denied_prior, "대손상계": write_off,
                "당기설정보충액": supplement, "환입할금액": to_return, "회사환입": reversal_co, "과소과다환입": over_under,
                "추인": reversal, "충당금": moves, "채권": table,
                "대손금내역": [{"date": r.line.date, "no": r.line.no, "account": r.line.account, "partner": r.line.partner,
                             "memo": r.line.memo, "amount": r.line.amount, "kind": r.label, "receivable": r.pick2,
                             "denied": r.pick == "O"} for r in p.lines],
                "환입전표": neg_reversal, "대여금대체": moved_rows,
                MODE: mode, "전기유보증감없음": static, "보충법": supplemental,
                "다른처리": {"처리": REVERSE if keep else KEEP, "한도초과": other_excess, "추인": other_reversal}}
    p.extra["table"] = table
    p.adjustments = [
        Adj("가산", subj, excess, "유보", "대손충당금 한도초과", "대손충당금 한도초과액 손금불산입", "한도초과", subj, "증가", 1),
        Adj("차감", subj, reversal, "유보", "대손충당금 한도초과 추인", "전기 대손충당금 한도초과액 손금산입", "추인", subj, "감소", 1),
    ]
    with_lines = {r.pick2 for r in p.lines}
    for t in table:
        if t["code"] in with_lines:
            p.adjustments.append(Adj("가산", t["name"], t["당기부인"], "유보", f"대손금 부인 {t['name']}",
                                     "대손 요건을 갖추지 못한 대손금 손금불산입", f"{t['code']}.당기부인", t["name"], "증가", 1))
        if t["전기부인누계"]:
            p.adjustments.append(Adj("차감", t["name"], t["추인"], "유보", f"대손금 부인 추인 {t['name']}",
                                     "전기 대손금 부인액 중 당기 대손 요건 충족분 손금산입", f"{t['code']}.추인", t["name"], "감소", 1))
    if "" in with_lines:
        p.adjustments.append(Adj("가산", "대손금", unknown_denied, "유보", "대손금 부인(채권 미상)",
                                 "대손 요건을 갖추지 못한 대손금 손금불산입", "대손금부인 채권 미상", "대손금", "증가", 1))
        p.values["대손금부인 채권 미상"] = unknown_denied

    has = bool(allow and (opening or closing or set_ or write_off or reversal_co)) or bool(p.lines)
    if p.lines:
        p.confirm.append(f"대손금 {len(p.lines)}건 {total_bd:,}원은 대손 요건(파산 · 소멸시효 · 회수불능 등, 시행령 제19조의2)을 "
                         "확인하지 않고 시인으로 두었습니다. 요건이 안 되면 「부인 여부」 를 O 로 바꾸세요")
    if odd_direct:
        p.confirm.append(f"상대 계정이 채권이 아닌 대손상각비 {odd_direct:,}원이 있습니다. 대손금이 맞는지 확인하세요")
    if other_up:
        p.confirm.append(f"대손충당금 증가 중 대손상각비가 상대 계정이 아닌 금액 {other_up:,}원이 있습니다(상각채권 회수 등). "
                         "회수한 대손금이면 익금 여부를 확인하세요")
    if mode not in (KEEP, REVERSE):
        p.confirm.append(f"노란 칸 「{MODE}」 값 「{mode}」 을 읽지 못해 「{REVERSE}」 으로 계산했습니다({KEEP} · {REVERSE})")
    picked = MODE in p.overridden                  # 회계사가 기본값과 다르게 고름
    if static and denied_prior and keep:
        p.confirm.append(
            f"전기 신고서는 대손충당금 유보 {prior_allow:,}원을 한 해 동안 그대로 두었습니다(전기 50호(을) 기초 = 기말, 전기 15호에 "
            f"대손충당금 줄 없음). 그래서 당기에도 {denied_prior:,}원을 추인하지 않고 유보로 두었습니다. 이 유보가 한도초과액이면 전액 "
            f"추인하고 당기 한도초과를 다시 계산합니다(법인세법 제34조 제3항). 그렇게 하면 차감 {other_reversal:,}원 · 가산 "
            f"{other_excess:,}원입니다. 특정 채권의 대손금 부인액이거나 설정 대상이 아닌 채권(법인세법 제34조 제2항)의 충당금이면 "
            f"그대로 둡니다. 노란 칸 「{MODE}」 에서 고르십시오({KEEP} · {REVERSE})")
    elif supplemental and denied_prior and mode == REVERSE and not picked:
        p.confirm.append(
            f"전기 신고서는 대손충당금 유보 {prior_allow:,}원을 한 해 동안 그대로 두었지만, 회사는 보충법(기초 충당금 {opening:,}원을 두고 "
            f"당기 {set_:,}원만 설정)입니다. 보충법이어도 남은 충당금은 다음 사업연도 익금이라(법인세법 제34조 제3항) 전기 부인누계 "
            f"{denied_prior:,}원을 추인하고 기말 잔액 {closing:,}원 전체로 한도초과를 다시 계산했습니다(차감 {reversal:,}원 · 가산 "
            f"{excess:,}원). 그 유보가 특정 채권의 대손금 부인액이거나 설정 대상이 아닌 채권(법인세법 제34조 제2항)의 충당금이면 노란 칸 "
            f"「{MODE}」 를 「{KEEP}」 로 바꾸십시오(차감 {other_reversal:,}원 · 가산 {other_excess:,}원)")
    elif static and denied_prior and mode == REVERSE:
        p.notes.append(f"전기 신고서는 대손충당금 유보 {prior_allow:,}원을 한 해 동안 그대로 두었습니다. 노란 칸 「{MODE}」 가 "
                       f"「{REVERSE}」 이라 전액 추인하고 당기 한도초과를 다시 계산했습니다(「{KEEP}」 로 두면 차감 "
                       f"{other_reversal:,}원 · 가산 {other_excess:,}원)")
    elif keep and denied_prior and picked:
        p.notes.append(f"노란 칸 「{MODE}」 가 「{KEEP}」 라 전기 대손충당금 유보 {denied_prior:,}원을 추인하지 않았습니다"
                       f"(「{REVERSE}」 으로 두면 차감 {other_reversal:,}원 · 가산 {other_excess:,}원)")
    if kept and (set_ or write_off or reversal_co):
        moved_text = " · ".join(f"{label} {amt:,}원" for label, amt in (("설정", set_), ("대손 상계", write_off),
                                                                        ("환입", reversal_co)) if amt)
        p.confirm.append(
            f"당기 대손충당금 증감은 {moved_text}입니다. 그대로 둔 유보 {kept:,}원을 뺀 회사 충당금 {booked:,}원만 한도 {limit:,}원과 "
            f"비교했습니다(한도초과 {excess:,}원, 법인세법 제34조 제1항). 이 증감이 그대로 둔 유보와 같은 채권의 것인지는 엔진이 "
            "가리지 않았고 따로 조정하지 않았습니다. 같은 채권의 것이면 당기 설정액의 손금불산입 · 상계하거나 환입한 금액의 유보 추인을 "
            "확인하십시오")
    if kept and booked < 0:
        p.confirm.append(f"기말 대손충당금 {closing:,}원이 그대로 둔 유보 {kept:,}원보다 작습니다. 모자라는 {-booked:,}원에 해당하는 "
                         "유보를 추인할지 확인하십시오(엔진은 조정하지 않았습니다)")
    if prior_allow > opening and allow:
        over = prior_allow - min(prior_allow, opening)
        tail = (f"넘는 {over:,}원도 유보로 남겼습니다" if keep else
                f"넘는 {over:,}원은 충당금 한도초과일 수 없어 추인하지 않고 유보로 남겼습니다")
        p.confirm.append(f"전기 50호(을) 대손충당금 유보 {prior_allow:,}원이 기초 대손충당금 {opening:,}원보다 큽니다. {tail}"
                         "(대손금 부인 등 다른 유보가 섞였는지 확인)")
    if neg_reversal:
        p.notes.append(f"대손충당금 차변 {neg_reversal:,}원({neg_count}건)은 대손상각비 음수 · 환입 수익 · 적요 「환입」 전표라 환입(⑭ 회사 "
                       "환입액)으로 넣었습니다. 대손 처리한 채권이 아닙니다")
    for m in moved_rows:
        text = (f"{m['date']} 전표 {m['no']}: {m['from_name']}({m['partner']}) {m['amount']:,}원을 현금 없이 {m['to_name']} "
                f"계정으로 옮겼습니다(적요 「{m['memo']}」)")
        if m["later"]:
            text += f". 그 뒤 같은 거래처 {m['to_name']} 회수 {m['later']:,}원"
        if m["excluded"] and m["remaining"]:
            text += (f". 특수관계인 대여금이 매출채권으로 옮겨진 것으로 보고 기말에 남은 {m['remaining']:,}원을 {m['to_name']} 설정제외 "
                     "기본값에 넣었습니다. 실제 매출 대금이면 설정제외 칸을 고치세요")
        elif m["remaining"]:
            text += (f". 인정이자 조서 특수관계인 칸이 「{m['related']}」 라 설정제외에 넣지 않았습니다. 특수관계인 대여금이면 "
                     f"{m['to_name']} 설정제외 칸에 {m['remaining']:,}원을 더하세요")
        if m["days"]:
            text += (f". 인정이자 조서는 대체 뒤 잔액으로 적수를 세므로 대체일부터 사업연도 끝까지 {m['days']}일분 적수 "
                     f"{m['amount'] * m['days']:,}(대체액 × 일수)이 빠져 있습니다. 대여금이 맞으면 인정이자 조서에서 확인하세요")
        p.confirm.append(text)
    if supplement < 0 and kept:
        p.notes.append("그대로 둔 유보(⑩)를 뺀 충당금보다 당기 설정액이 커서 ⑤ 보충액이 음수입니다")
    elif supplement < 0:
        p.notes.append("당기 설정액이 기말 잔액보다 커서 ⑤ 보충액이 음수입니다(기중에 당기 설정분과 대손을 상계함)")
    if has:
        p.notes.append("한도 = 채권잔액 × max(1%, 대손실적률)(시행령 제61조 제2항). 채권잔액에는 대손충당금을 쌓지 않은 채권도 "
                       "들어갑니다. 설정대상이 아닌 채권은 (20) 설정제외 칸에 넣으세요")
        if kept:
            p.notes.append(f"전기 대손충당금 유보를 그대로 두는 처리입니다(노란 칸 「{MODE}」). ⑤ 보충액 · ⑥ 회사계상액에서 그대로 둔 "
                           "유보(⑩)를 빼고 한도와 비교하므로 ⑮ 가 0 이고 추인이 없습니다. 유보는 50호(을)에 그대로 남습니다")
        else:
            p.notes.append("전기 한도초과액(50호(을) 대손충당금 유보)은 당기에 손금산입(추인)하고, 당기 기말 잔액으로 한도를 다시 계산합니다"
                           "(법인세법 제34조 제3항)")
        p.notes.append("금융회사 등의 대손충당금적립기준(② (ㄷ))은 넣지 않았습니다. 대부업자는 그 대상이 아닙니다(시행령 제61조 제2항)")
    else:
        p.notes.append("대손충당금 · 대손금이 없습니다")
    p.settle(has)


# 엑셀 ---------------------------------------------------------------------------------------------

WIDTHS = [12, 9, 10, 20, 18, 30, 16, 14, 14, 14, 16, 30]


def write(bk: Book, p: Paper) -> None:
    s = head(bk, p)
    X.widths(s.ws, WIDTHS)
    v, R = p.values, bk.ref
    moves, table = v["충당금"], p.extra.get("table", [])

    # 1. 대손충당금 계정
    row = s.section(5, "1. 대손충당금 계정(장부)")
    X.header(s.ws, row, ["코드", "", "", "계정", "기초", "설정(대변)", "대손 상계", "환입", "기말"])
    row += 1
    m0 = row
    for m in moves:
        s.put(row, 1, m["code"])
        s.put(row, 4, m["name"])
        for col, k in ((5, "opening"), (6, "set"), (7, "write_off"), (8, "reversal")):
            s.put(row, col, m[k], money=True)
        s.put(row, 9, f"=E{row}+F{row}-G{row}-H{row}", money=True)
        row += 1
    if not moves:
        s.put(row, 4, "대손충당금 계정이 없습니다")
        row += 1
    m1 = row - 1
    s.put(row, 4, "계")
    tot = {}
    for col, key in ((5, "충당금기초"), (6, "당기계상"), (7, "대손상계"), (8, "회사환입"), (9, "회사계상계")):
        letter = "EFGHI"[col - 5]
        X.cell(s.ws, row, col, f"=SUM({letter}{m0}:{letter}{m1})", money=True, kind="total")
        tot[key] = f"{letter}{row}"
    row += 2

    # 2. 대손금(34호 2. 대손금조정)
    row = s.section(row, "2. 대손금(부인 여부 노란 칸, O 면 손금불산입 · 유보)")
    X.header(s.ws, row, ["일자", "전표", "코드", "계정", "거래처", "적요", "금액", "구분", PICK, "채권 코드", "채권 계정", "근거"])
    row += 1
    l0 = row
    for lr in p.lines:
        ln = lr.line
        s.put(row, 1, ln.date)
        s.put(row, 2, ln.no)
        s.put(row, 3, ln.account)
        s.put(row, 4, bk.b.by_code.get(ln.account, {}).get("name") or ln.account_name)
        s.put(row, 5, ln.partner)
        s.put(row, 6, ln.memo)
        s.put(row, 7, ln.amount, money=True)
        s.put(row, 8, lr.label)
        s.inp(row, 9, lr.pick, pid=p.id, key=f"{PICK}/{lr.key}", default=lr.default, kind="pick")
        s.put(row, 10, lr.pick2)
        s.put(row, 11, bk.b.by_code.get(lr.pick2, {}).get("name", ""))
        s.put(row, 12, lr.why)
        row += 1
    if not p.lines:
        s.put(row, 6, "대손금 줄 없음")
        row += 1
    l1 = row - 1
    rng = lambda c: f"{c}{l0}:{c}{l1}"  # noqa: E731
    row += 1

    # 3. 채권잔액(34호 (16) ~ (21))
    row = s.section(row, "3. 설정대상 채권잔액(34호 (16) ~ (21))")
    X.header(s.ws, row, ["코드", "계정", "(17) 장부가액", "전기 부인누계", "당기 부인", "부인 추인", "(18) 부인누계",
                         "(19) 합계", "(20) 설정제외", "(21) 채권잔액", "기초 장부가액", "기초 설정제외"])
    row += 1
    t0 = row
    for t in table:
        c = t["code"]
        s.put(row, 1, c)
        s.put(row, 2, t["name"])
        s.put(row, 3, t["17"], money=True)
        s.inp(row, 4, t["전기부인누계"], pid=p.id, key=f"전기 부인누계/{c}",
              default=p.defaults.get(f"전기 부인누계/{c}", t["전기부인누계"]), kind="int", money=True)
        s.put(row, 5, f'=SUMIFS({rng("G")},{rng("I")},"O",{rng("J")},"{c}")', money=True)
        if f"대손금 부인 추인/{c}" in p.inputs:
            s.inp(row, 6, t["추인"], pid=p.id, key=f"대손금 부인 추인/{c}", default=0, kind="int", money=True)
        else:
            s.put(row, 6, 0, money=True)
        s.put(row, 7, f"=D{row}+E{row}-F{row}", money=True)
        s.put(row, 8, f"=C{row}+G{row}", money=True)
        s.inp(row, 9, t["20"], pid=p.id, key=f"설정제외/{c}", default=p.defaults.get(f"설정제외/{c}", t["20"]),
              kind="int", money=True)
        s.put(row, 10, f"=H{row}-I{row}", money=True)
        s.put(row, 11, t["기초"], money=True)
        s.put(row, 12, t["기초제외"], money=True)
        for col, key in ((5, "당기부인"), (6, "추인"), (7, "18"), (8, "19"), (10, "21")):
            bk.reg(p.id, f"{c}.{key}", s.addr(row, col))
        row += 1
    if not table:
        s.put(row, 2, "설정대상 채권이 없습니다")
        row += 1
    t1 = row - 1
    s.put(row, 2, "계")
    for col in (3, 7, 8, 9, 10):
        letter = "ABCDEFGHIJ"[col - 1]
        X.cell(s.ws, row, col, f"=SUM({letter}{t0}:{letter}{t1})", money=True, kind="total")
    recv_total = f"J{row}"
    row += 2

    # 4. 한도 시부인
    row = s.section(row, "4. 대손충당금 한도(34호 1. 대손충당금조정)")
    r = Rows(bk, s, p, row)
    g = r.g
    r.put("채권잔액", "① 채권잔액((21) 계)", f"={recv_total}")
    r.put("대손금", "당기 대손금(2 의 계)", f"=SUM({rng('G')})")
    r.put("대손금부인", "대손금 부인(부인 여부 O)", f'=SUMIF({rng("I")},"O",{rng("G")})')
    r.put("대손금시인", "대손금 시인", f"={g('대손금')}-{g('대손금부인')}")
    r.put("직전채권잔액", "직전 사업연도말 채권가액", p.inputs["직전채권잔액"], kind="input", input_kind="int")
    r.put("대손실적률", "(ㄴ) 대손실적률(시인 대손금 ÷ 직전 채권가액)",
          f"=IF({g('직전채권잔액')}>0,{g('대손금시인')}/MAX(1,{g('직전채권잔액')}),0)", fmt="0.0000%")
    r.put("최저설정률", "(ㄱ) 최저 설정률(기준 2025)", f"={R['대손충당금 최저 설정률']}", fmt="0%")
    r.put("설정률", "② 설정률(큰 율)", f"=MAX({g('최저설정률')},{g('대손실적률')})", fmt="0.0000%")
    r.put("한도", "③ 한도액(① × ②)", f"=ROUNDDOWN({g('채권잔액')}*{g('설정률')},0)")
    r.put(MODE, f"전기 유보 처리({KEEP} · {REVERSE}, ⑩ 을 당기에 추인할지)", p.inputs[MODE], kind="input")
    r.put("당기계상", "④ 당기계상액(설정)", f"={tot['당기계상']}")
    r.put("충당금기말", "장부상 충당금 기말잔액", f"={tot['회사계상계']}")
    r.put("회사계상계", "⑥ 계(기말잔액 - 그대로 둔 유보)", 0)          # 수식은 ⑩ 줄을 쓴 뒤에 건다
    r.put("보충액", "⑤ 보충액(⑥ - ④)", f"={g('회사계상계')}-{g('당기계상')}")
    r.put("한도초과", "⑦ 한도초과액(⑥ - ③, 손금불산입 · 유보)", f"=MAX(0,{g('회사계상계')}-{g('한도')})")
    r.put("충당금기초", "⑧ 장부상 충당금 기초잔액", f"={tot['충당금기초']}")
    r.put("기중환입", "⑨ 기중 충당금 환입액", 0)
    r.put("전기부인누계", "⑩ 충당금 부인누계액(전기 50호(을))", p.inputs["전기부인누계"], kind="input", input_kind="int")
    r.put("유보유지", f"그대로 둔 전기 유보(처리가 「{KEEP}」 면 ⑩, 아니면 0)", f'=IF({g(MODE)}="{KEEP}",{g("전기부인누계")},0)')
    s.ws.cell(row=r.at["회사계상계"], column=7).value = f"={g('충당금기말')}-{g('유보유지')}"
    r.put("대손상계", "⑪ 당기 대손금 상계액", f"={tot['대손상계']}")
    r.put("당기설정보충액", "⑫ 당기설정 충당금 보충액(⑤)", f"={g('보충액')}")
    r.put("환입할금액", "⑬ 환입할 금액(⑧ - ⑨ - ⑩ - ⑪ - ⑫)",
          f"={g('충당금기초')}-{g('기중환입')}-{g('전기부인누계')}-{g('대손상계')}-{g('당기설정보충액')}")
    r.put("회사환입", "⑭ 회사 환입액", f"={tot['회사환입']}")
    r.put("과소과다환입", "⑮ 과소환입 · 과다환입(△)(⑬ - ⑭)", f"={g('환입할금액')}-{g('회사환입')}")
    r.put("추인", "전기 한도초과 추인(손금산입 · 유보, ⑩ 안에서 과다환입)",
          f'=IF({g(MODE)}="{KEEP}",0,MIN({g("전기부인누계")},MAX(0,-{g("과소과다환입")})))')
    row = adj_table(bk, s, r.row + 1, p)
    row = forms_table(bk, s, row, p, [("34", "① 채권잔액", "채권잔액"), ("34", "③ 한도액", "한도"),
                                      ("34", "⑥ 회사계상액 계", "회사계상계"), ("34", "⑦ 한도초과액", "한도초과"),
                                      ("34", "⑩ 충당금 부인누계액", "전기부인누계"), ("34", "⑮ 과소 · 과다환입", "과소과다환입"),
                                      ("34", "(29) · (32) 대손금 부인액 계", "대손금부인")])
    notes(s, row, p)


__all__ = ["NAME", "FORMS", "compute", "write", "basis", "receivable_accounts", "allowance_accounts", "loan_transfers",
           "prior_static", "MODE", "KEEP", "REVERSE"]
