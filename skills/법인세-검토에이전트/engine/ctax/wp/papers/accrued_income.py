"""3 미수수익: 기간경과 미수이자 익금불산입(△유보)과 전기분 추인(익금산입 유보). 10호(갑)와의 관계는 메모.

근거: 법인세법 시행령 제70조 제1항 제1호 단서. 결산 때 경과 기간의 이자를 수익으로 계상하면 그 사업연도 익금이지만,
법 제73조 · 제73조의2 로 원천징수되는 이자는 빼고 받는 때(소득세법 시행령 제45조 수입시기)의 익금이다. 그래서 원천징수
대상 이자의 미수 계상액은 익금불산입(△유보)하고, 다음 해 받을 때 전액 추인(익금산입 유보)한다(신고본 네 곳이 같은 꼴).

원장 검토: 미수수익 · 미수이자 계정의 줄. 차변 줄은 같은 전표에 이자 수익 계정이 있으면 「계상」(노란 칸 O), 없으면
「기타 증가」(X). 대변 줄은 「회수」(받음 · 재수정 역분개). 기말 미수이자(익금불산입) = MIN(기말 잔액 - 그대로 둔 전기 유보, O 줄 합계)
(기초 잔액이 먼저 회수된다고 본다). 전기 50호(을) 미수수익 유보는 노란 칸 「전기분 추인액/<과목>」(기본 전액)으로 추인한다.

전기 유보 처리(노란 칸 「전기 유보 처리/<과목>」, 그대로 · 추인. `prior_compare.carry`)
  추인    전기 유보를 노란 칸 추인액만큼 추인한다. 기본값이다. 근거 전표는 당기 미수수익 대변 줄(같은 전표에 예금 차변이 있으면
          입금, 이자 수익 차변이 있으면 역분개)이고, 대변 합계가 추인액보다 적으면 확인 줄, 많거나 같으면 메모에 적는다.
  그대로  추인하지 않는다. 전기 신고서가 그 유보를 한 해 동안 그대로 두었을 때(전기 50호(을) 기초 = 기말 · 증감 0, 전기 15호에
          미수수익 줄 없음)만 기본값이고 조서는 「확인 필요」 다. 만기가 여러 해 뒤인 예금처럼 해마다 받는 이자가 아니라는 신호다.
  원천징수 대상 이자는 실제로 받는 날 · 약정 지급일 같은 수입시기가 속하는 사업연도의 익금이다(법인세법 시행령 제70조 제1항
  제1호, 소득세법 시행령 제45조). 당기에 수입시기가 왔는지는 엔진이 정하지 않는다.
"""
from __future__ import annotations

import re

from ... import xlsx as X
from ..books import Books
from ..model import Adj, LineRow, Paper, subject_of
from ..prior_compare import KEEP, carry, carry_head, carry_notes, carry_rows, tri
from ..sheet import Book, Rows, adj_table, forms_table, head, ledger, notes

NAME = "미수수익"
FORMS = ["15", "50을", "10갑"]
LEDGER_CHECK = False     # 미수수익 줄 합계는 증감이지 재무제표 금액이 아니다
PICK = "익금불산입"
ACCRUE, OTHER, COLLECT = "계상", "기타 증가", "회수"
INTEREST = re.compile(r"이자|할인료")
RESERVE = re.compile(r"미수수익|미수이자")
NOT_RESERVE = re.compile(r"대손|충당")
ADD = "전기분 추인액"
CASH = re.compile(r"현금|예금|당좌|적금|금융상품")
LAW = ("원천징수 대상 이자는 실제로 받는 날이나 약정 지급일 같은 수입시기가 속하는 사업연도의 익금입니다(법인세법 시행령 제70조 "
       "제1항 제1호, 소득세법 시행령 제45조).")


def basis(rates: dict) -> list[tuple]:
    r = rates["accrued_income"]
    return [("미수이자 익금 귀속", r["accrual_rule"]["value"], r["accrual_rule"]["basis"], r["accrual_rule"]["grade"], None),
            ("이자 원천징수세율(법인)", r["withholding_rate"]["value"], r["withholding_rate"]["basis"],
             r["withholding_rate"]["grade"], "0%"),
            ("비영업대금이익 원천징수세율", r["nonbusiness_loan_rate"]["value"], r["nonbusiness_loan_rate"]["basis"],
             r["nonbusiness_loan_rate"]["grade"], "0%")]


def prior_rows(b: Books) -> list[tuple[str, int]]:
    """전기 50호(을) 미수수익 · 미수이자 유보 줄 (과목, 기말). 기말이 0 인 줄은 뺀다."""
    out = []
    for r in (b.prior or {}).get("reserves", []) or []:
        subj = r.get("subject") or ""
        closing = int(r.get("closing") or 0)
        if RESERVE.search(subj) and not NOT_RESERVE.search(subj) and closing:
            out.append((subj, closing))
    return out


def _vouchers(b: Books) -> dict:
    out: dict = {}
    for ln in b.lines:
        out.setdefault((ln.date, ln.no), []).append(ln)
    return out


def _interest_partner(b: Books, ln, voucher: list) -> str:
    """같은 전표 대변의 이자 수익 계정 이름(없으면 빈 글)."""
    for x in voucher:
        if x is ln:
            continue
        a = b.by_code.get(x.account, {})
        name = a.get("name") or x.account_name
        if a.get("class") == "수익" and INTEREST.search(name) and x.credit - x.debit > 0:
            return name
    return ""


def _related(a: dict) -> bool:
    """전기 15호 줄이 미수수익 · 미수이자 줄인가(과목 · 조정내용)."""
    text = f"{a.get('subject') or ''} {a.get('note') or ''}"
    return bool(RESERVE.search(text)) and not NOT_RESERVE.search(a.get("subject") or "")


def collected(b: Books, lines: list, vouchers: dict) -> dict:
    """당기 미수수익 대변 줄(추인의 근거 전표). 같은 전표에 현금 · 예금 차변이 있으면 입금, 이자 수익 계정 차변(또는 음수 대변)이
    있으면 역분개, 둘 다 아니면 나머지다. {lines, amount, 입금, 역분개, 나머지}."""
    out = {"lines": 0, "amount": 0, "입금": 0, "역분개": 0, "나머지": 0}
    for ln in lines:
        net = ln.credit - ln.debit
        if net <= 0:
            continue
        kind = "나머지"
        for x in vouchers.get((ln.date, ln.no), []):
            if x is ln:
                continue
            a = b.by_code.get(x.account, {})
            name = a.get("name") or x.account_name
            if a.get("class") == "자산" and CASH.search(name) and x.debit - x.credit > 0:
                kind = "입금"
                break
            if a.get("class") == "수익" and INTEREST.search(name) and x.debit - x.credit > 0:
                kind = "역분개"
        out["lines"] += 1
        out["amount"] += net
        out[kind] += net
    return out


def compute(p: Paper, b: Books) -> None:
    accts = b.accounts(cls="자산", any_of=("미수수익", "미수이자"), none_of=("대손", "충당"))
    p.accounts = accts
    vouchers = _vouchers(b)
    for ln in b.lines_of(accts):
        if ln.debit:
            inc = _interest_partner(b, ln, vouchers.get((ln.date, ln.no), []))
            if inc:
                p.lines.append(LineRow(ln, ACCRUE, "O", why=f"같은 전표 대변 {inc}. 원천징수 대상이 아니면(금융회사 등 · 국외 이자) X"))
            else:
                p.lines.append(LineRow(ln, OTHER, "X", why="같은 전표에 이자 수익 계정이 없습니다(이자 아닌 미수수익)"))
        else:
            p.lines.append(LineRow(ln, COLLECT, "", why="받음 · 재수정 역분개. 익금불산입 판단 대상이 아닙니다"))
    p.take_lines(b, PICK)

    opening = sum(int(a.get("opening") or 0) for a in accts)
    debit = sum(int(a.get("debit") or 0) for a in accts)
    credit = sum(int(a.get("credit") or 0) for a in accts)
    closing = sum(int(a.get("closing") or 0) for a in accts)
    accrued = sum(r.line.amount for r in p.lines if r.pick == "O")

    prior = prior_rows(b)
    subj_now = prior[0][0] if prior else subject_of(accts, "미수수익")
    p.values = {"기초잔액": opening, "당기증가": debit, "당기감소": credit, "기말잔액": closing, "미수이자계상": accrued}
    carries = [carry(p, b, subj, close, f"{ADD}/{subj}", _related) for subj, close in prior]
    # 그대로 둔 △ 유보는 아직 받지 않은 전기 이전 미수이자다. 기말 잔액에서 먼저 빼고 당기 계상분과 견준다
    kept = sum(-c.closing for c in carries if c.keep and c.closing < 0)
    year_end = max(0, min(closing - kept, accrued))
    p.values.update({"유보유지": kept, "기말미수이자": year_end})
    adjs = [Adj("차감", subj_now, year_end, "유보", "당기 미수이자", "기간경과 미수이자(원천징수 대상) 익금불산입",
                "기말미수이자", subj_now, "증가", -1)]
    for c in carries:
        subj = c.subject
        if c.closing < 0:
            adjs.append(Adj("가산", subj, c.amount, "유보", f"전기분 추인/{subj}", "전기 익금불산입한 미수이자 당기 수령분 익금산입",
                            c.key_applied, subj, "감소", -1))
        else:
            adjs.append(Adj("차감", subj, c.amount, "유보", f"전기분 추인/{subj}", "전기 유보 미수수익 당기 추인",
                            c.key_applied, subj, "감소", 1))
            p.confirm.append(f"전기 50호(을) {subj} 유보가 + {c.closing:,}원입니다. 미수이자 유보는 보통 △ 입니다. 추인 방향을 확인하세요")
    reversal = sum(c.amount for c in carries)
    p.values["전기분추인"] = reversal
    p.adjustments = adjs

    # 확인 · 메모: 전기 유보 대조(전기 유보 기말 · 당기 추인액 · 근거 전표)
    got = collected(b, [r.line for r in p.lines if r.label == COLLECT], vouchers)
    found = bool(prior) and got["lines"] > 0 and got["amount"] >= sum(c.asked for c in carries)
    p.extra["carries"] = carries
    p.values["전기 유보 대조"] = [{**c.json(), "근거": got, "근거 있음": found} for c in carries]
    for c in carries:
        side = "가산" if c.closing < 0 else "차감"
        carry_notes(p, c, law=LAW, if_reverse=f"당기에 받았거나 수입시기가 왔으면 추인합니다. 그렇게 하면 {side} {c.asked:,}원입니다"
                                              f"(당기 미수수익 대변 {got['lines']}줄 {got['amount']:,}원).")
    if prior:
        parts = " · ".join(f"{k} {got[k]:,}원" for k in ("입금", "역분개", "나머지") if got[k])
        head = carry_head(carries)
        if not accts:
            p.confirm.append(f"{head}. 장부에 미수수익 계정이 없어 근거 전표를 찾지 못했습니다. 받은 때 계정을 확인하세요")
        elif not reversal:
            p.notes.append(f"{head}. 당기 미수수익 대변(받음 · 역분개) {got['lines']}줄 {got['amount']:,}원" + (f"({parts})" if parts else ""))
        elif got["lines"] and got["amount"] >= reversal:
            tail = ". 역분개 줄은 받은 전표가 아니니 기말에 다시 계상한 금액과 함께 보세요" if got["역분개"] else ""
            p.notes.append(f"{head}. 근거 전표: 당기 미수수익 대변 {got['lines']}줄 {got['amount']:,}원({parts}). 추인액 이상입니다{tail}")
        elif got["lines"]:
            p.confirm.append(f"{head}. 근거 전표: 당기 미수수익 대변 {got['lines']}줄 {got['amount']:,}원({parts})으로 추인액보다 "
                             f"{reversal - got['amount']:,}원 적습니다. 받지 못한 이자는 추인하지 않습니다(노란 칸 「{ADD}」)")
        else:
            p.confirm.append(f"{head}. 당기 미수수익 대변(받음 · 역분개) 줄이 없어 근거 전표를 찾지 못했습니다. 받지 못한 이자는 "
                             f"추인하지 않습니다(노란 칸 「{ADD}」)")
    if kept and closing < kept:
        p.confirm.append(f"미수수익 기말 잔액 {closing:,}원이 그대로 둔 전기 유보 {tri(-kept)}원보다 작습니다. 모자라는 {kept - closing:,}원은 "
                         "당기에 받았을 수 있으니 추인할지 확인하십시오(엔진은 조정하지 않았습니다)")
    if closing - kept > accrued > 0:
        p.notes.append(f"미수수익 기말 {closing:,}원 중 당기 이자 계상분 {accrued:,}원만 익금불산입했습니다. "
                       "나머지는 이자 외 미수수익이거나 전기 이전 잔액입니다")
    if accts or prior:
        p.notes.append("원천징수 대상 이자(예금 · 채권 이자 등)는 받을 때 익금입니다(법인세법 시행령 제70조 제1항 제1호 단서). "
                       "금융회사 등이 받는 이자, 원천징수가 없는 국외 이자는 기간경과분 계상이 그해 익금이라 노란 칸을 X 로 두세요")
        p.notes.append(f"10호(갑): 당기 익금불산입한 미수이자 {year_end:,}원은 다음 사업연도에 받을 때 원천징수되므로 그 세액은 다음 "
                       f"사업연도 10호(갑) 원천납부세액입니다. 전기분 {reversal:,}원을 당기에 받으며 뗀 원천징수세액은 당기 "
                       "10호(갑) · 3호 24 에 들어갑니다(선납세금)")
    else:
        p.notes.append("미수수익 · 미수이자 계정과 전기 미수이자 유보가 없습니다")
    p.settle(bool(accts or prior))


def write(bk: Book, p: Paper) -> None:
    s = head(bk, p)
    row = s.section(5, "1. 미수수익 잔액")
    for col, label in ((3, "코드"), (4, "계정"), (5, "기초"), (7, "기말(재무제표)"), (8, "증가(차변)"), (9, "감소(대변)")):
        X.header(s.ws, row, [label], col=col)
    row += 1
    for a in p.accounts:
        s.put(row, 3, a["code"])
        s.put(row, 4, a["name"])
        s.put(row, 5, int(a.get("opening") or 0), money=True)
        s.put(row, 7, int(a.get("closing") or 0), money=True)
        s.put(row, 8, int(a.get("debit") or 0), money=True)
        s.put(row, 9, int(a.get("credit") or 0), money=True)
        row += 1
    if not p.accounts:
        s.put(row, 4, "미수수익 계정이 없습니다")
        row += 1
    row, first, last = ledger(bk, s, row + 1, p, PICK, title="2. 원장 검토(미수수익, 노란 칸 O = 원천징수 대상 미수이자)")
    v = p.values
    row = s.section(row, "3. 익금불산입 · 추인")
    r = Rows(bk, s, p, row)
    g = r.g
    r.put("기초잔액", "미수수익 기초 잔액", v["기초잔액"])
    r.put("당기증가", "당기 증가(차변)", f'=SUMIFS(G{first}:G{last},H{first}:H{last},"<>{COLLECT}")')
    r.put("당기감소", "당기 감소(받음 · 역분개)", f'=-SUMIFS(G{first}:G{last},H{first}:H{last},"{COLLECT}")')
    r.put("기말잔액", "미수수익 기말 잔액(재무제표)", f"={g('기초잔액')}+{g('당기증가')}-{g('당기감소')}")
    r.put("미수이자계상", "당기 미수이자 계상(노란 칸 O 줄 합계)", f'=SUMIFS(G{first}:G{last},I{first}:I{last},"O")')
    carries = p.extra.get("carries", [])
    carry_rows(r, p, carries, "익금산입 · 유보", note="기본은 전기 유보 전액. 받지 못한 금액은 빼세요")
    held = [f'IF({g(c.key_mode)}="{KEEP}",{-c.closing},0)' for c in carries if c.closing < 0]
    r.put("유보유지", "그대로 둔 전기 유보(아직 받지 않은 전기 이전 미수이자)", "=" + "+".join(held) if held else 0)
    r.put("기말미수이자", "기말 미수이자(익금불산입 · △유보)",
          f"=MAX(0,MIN({g('기말잔액')}-{g('유보유지')},{g('미수이자계상')}))",
          note="기초 잔액이 먼저 회수된다고 보고 당기 계상분 중 기말에 남은 금액")
    r.put("전기분추인", "전기분 추인 합계", "=" + "+".join(g(c.key_applied) for c in carries) if carries else 0)
    row = adj_table(bk, s, r.row + 1, p)
    row = forms_table(bk, s, row, p, [("15", "익금불산입 미수수익(△유보)", "기말미수이자"),
                                      ("15", "익금산입 전기 미수수익 추인(유보)", "전기분추인"),
                                      ("50을", "미수수익 증가(△)", "기말미수이자"),
                                      ("50을", "미수수익 감소(△)", "전기분추인")])
    notes(s, row, p)
