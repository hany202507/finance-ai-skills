"""2 미지급비용: 미지급 연차수당 등 미확정비용 손금불산입(유보)과 전기분 추인(손금산입 유보). 15호 줄만.

근거: 법인세법 제40조 제1항(손금은 확정된 날이 속하는 사업연도). 결산에서 미지급으로 잡은 연차수당 중 지급 의무가 아직
확정되지 않은 금액(발생예정분 등)은 손금불산입하고, 다음 해 확정 · 지급되면 추인한다(신고본 네 곳이 같은 꼴).

연차 줄 가리기(장부에서): 부채 계정 줄 중 적요에 연차 · 년차 · 연가 · 휴가가 있는 줄, 또는 계정 이름에 연차가 든 부채
계정의 줄(특허 연차료 · 등록료는 뺌). 대변 쪽 줄은 「설정」(결산 계상, 음수면 감액), 차변 쪽 줄은 「감소」(지급 · 재수정 역분개).
노란 칸 「손금불산입」(O · X)의 기본값:
  - 적요에 발생예정 · 예정이 있는 줄이 있으면 그 줄만 O, 나머지 연차 줄은 X(확정된 연차수당으로 봄)
  - 아니면 전기 50호(을)에 연차 유보(과목 급여 · 직원급여 · 미지급비용(급여) · 연차 등)가 있으면 모두 O(전기 처리를 잇는다)
  - 둘 다 아니면 X(첫 해는 손금으로 두고 확인 필요)
기말 미지급 연차(손금불산입) = MAX(0, 전기 유보 - 감소(O) + 설정(O) - 그대로 둔 전기 유보). 회사가 연초에 역분개하든 기말에
잔액만 조정하든 같다. 전기 유보를 전액 추인하고 기말 금액을 다시 가산하므로 순 유보 증감은 장부 연차 줄(O)에서만 나온다.

전기 유보 처리(노란 칸 「전기 유보 처리/<과목>」, 그대로 · 추인. `prior_compare.carry`)
  추인    전기 유보를 노란 칸 추인액만큼 추인하고 기말 미지급 연차를 다시 가산한다. 기본값이다. 근거 전표는 연차 줄 가운데 노란 칸
          O 인 줄(감소는 같은 전표에 예금 대변이 있으면 지급, 비용 대변이 있으면 역분개)이다. O 줄이 없으면 확인 줄을 낸다.
  그대로  추인하지 않고, 기말 미지급 연차에서 그대로 둔 유보를 뺀 금액만 가산한다. 전기 신고서가 그 유보를 한 해 동안 그대로
          두었을 때(전기 50호(을) 기초 = 기말 · 증감 0, 전기 15호에 연차 줄 없음)만 기본값이고 조서는 「확인 필요」 다.
  손금은 확정된 날이 속하는 사업연도에 귀속한다(법인세법 제40조 제1항). 당기에 지급 의무가 확정됐는지는 엔진이 정하지 않는다.
"""
from __future__ import annotations

import re

from ... import xlsx as X
from ..books import Books
from ..model import Adj, LineRow, Paper
from ..prior_compare import KEEP, carry, carry_head, carry_notes, carry_rows, tri
from ..sheet import Book, Rows, adj_table, forms_table, head, ledger, notes

NAME = "미지급비용"
FORMS = ["15", "50을"]
LEDGER_CHECK = False     # 부채 계정의 연차 줄만 본다
PICK = "손금불산입"
SET, DOWN = "설정", "감소"
LEAVE = re.compile(r"연차|년차|연가|휴가")
NOT_LEAVE = re.compile(r"등록료|연차료|특허|상표|디자인|실용신안")
PLANNED = re.compile(r"발생\s*예정|예정")
WAGE = re.compile(r"급여|임금|상여|미지급비용")
NOT_WAGE = re.compile(r"퇴직|연금|대손")
ADD = "전기분 추인액"
CASH = re.compile(r"현금|예금|당좌|적금|금융상품")
LAW = "손금은 확정된 날이 속하는 사업연도에 귀속합니다(법인세법 제40조 제1항)."


def basis(rates: dict) -> list[tuple]:
    r = rates["accrued_expense"]
    return [("손금 귀속(확정)", r["fixed_rule"]["value"], r["fixed_rule"]["basis"], r["fixed_rule"]["grade"], None),
            ("미지급 연차수당", r["leave_pay"]["value"], r["leave_pay"]["basis"], r["leave_pay"]["grade"], None)]


def prior_rows(b: Books) -> list[tuple[str, int]]:
    """전기 50호(을) 연차수당 유보 줄 (과목, 기말). 과목에 연차 · 년차 · 휴가가 있거나, 급여 · 임금 · 미지급비용 꼴(퇴직 · 연금 뺌)."""
    out = []
    for r in (b.prior or {}).get("reserves", []) or []:
        subj = r.get("subject") or ""
        closing = int(r.get("closing") or 0)
        if not closing:
            continue
        if LEAVE.search(subj) or (WAGE.search(subj) and not NOT_WAGE.search(subj) and "충당" not in subj):
            out.append((subj, closing))
    return out


def _leave_line(b: Books, ln) -> bool:
    a = b.by_code.get(ln.account, {})
    name = a.get("name") or ln.account_name
    if a.get("class") != "부채" or "예수금" in name:
        return False
    if LEAVE.search(name) and not NOT_LEAVE.search(name):
        return True
    return bool(LEAVE.search(ln.memo or "")) and not NOT_LEAVE.search(ln.memo or "")


def _expense_name(b: Books, vouchers: dict, ln) -> str:
    for x in vouchers.get((ln.date, ln.no), []):
        a = b.by_code.get(x.account, {})
        if a.get("class") == "비용":
            return a.get("name") or x.account_name
    return ""


def _related(a: dict) -> bool:
    """전기 15호 줄이 연차수당 줄인가(과목 · 조정내용)."""
    text = f"{a.get('subject') or ''} {a.get('note') or ''}"
    return bool(LEAVE.search(text)) and not NOT_LEAVE.search(text)


def paid(b: Books, rows: list, vouchers: dict) -> dict:
    """연차 줄 가운데 노란 칸 O 인 줄(전기 유보가 줄고 느는 근거 전표). 감소 줄은 같은 전표에 현금 · 예금 대변이 있으면 지급,
    비용 계정 대변(또는 음수 차변)이 있으면 역분개, 둘 다 아니면 나머지다. {lines, 감소, 설정, 지급, 역분개, 나머지}."""
    out = {"lines": 0, "감소": 0, "설정": 0, "지급": 0, "역분개": 0, "나머지": 0}
    for r in rows:
        if r.pick != "O":
            continue
        ln = r.line
        out["lines"] += 1
        if r.label == SET:
            out["설정"] += -ln.amount
            continue
        kind = "나머지"
        for x in vouchers.get((ln.date, ln.no), []):
            if x is ln:
                continue
            a = b.by_code.get(x.account, {})
            name = a.get("name") or x.account_name
            if a.get("class") == "자산" and CASH.search(name) and x.credit - x.debit > 0:
                kind = "지급"
                break
            if a.get("class") == "비용" and x.credit - x.debit > 0:
                kind = "역분개"
        out["감소"] += ln.amount
        out[kind] += ln.amount
    return out


def compute(p: Paper, b: Books) -> None:
    vouchers: dict = {}
    for ln in b.lines:
        vouchers.setdefault((ln.date, ln.no), []).append(ln)
    picked = sorted((ln for ln in b.lines if _leave_line(b, ln)), key=lambda x: (x.date, x.no, x.account))
    codes = list(dict.fromkeys(ln.account for ln in picked))
    p.accounts = [b.by_code[c] for c in codes if c in b.by_code]
    prior = prior_rows(b)
    planned = any(PLANNED.search(ln.memo or "") for ln in picked)
    default = "O" if prior else "X"
    for ln in picked:
        side = SET if ln.credit else DOWN
        if planned:
            pick = "O" if PLANNED.search(ln.memo or "") else "X"
            why = ("적요에 발생예정. 지급 의무가 아직 확정되지 않았습니다" if pick == "O"
                   else "발생예정분이 따로 있어 이 줄은 확정된 연차수당으로 보았습니다")
        else:
            pick = default
            why = "전기 연차 유보가 있어 같은 처리를 이었습니다" if prior else "전기 연차 유보가 없어 손금으로 두었습니다"
        p.lines.append(LineRow(ln, side, pick, why=why))
    p.take_lines(b, PICK)

    set_o = -sum(r.line.amount for r in p.lines if r.label == SET and r.pick == "O")
    down_o = sum(r.line.amount for r in p.lines if r.label == DOWN and r.pick == "O")
    set_all = -sum(r.line.amount for r in p.lines if r.label == SET)
    down_all = sum(r.line.amount for r in p.lines if r.label == DOWN)
    base = sum(c for _, c in prior)
    raw = base - down_o + set_o
    expense = next((n for n in (_expense_name(b, vouchers, ln) for ln in picked if ln.credit) if n), "")
    subj_now = prior[0][0] if prior else (expense or "미지급비용")
    p.values = {"설정합계": set_all, "감소합계": down_all, "기초유보": base, "감소O": down_o, "설정O": set_o}
    carries = [carry(p, b, subj, close, f"{ADD}/{subj}", _related) for subj, close in prior]
    # 그대로 둔 유보는 추인하지 않으니 기말 미지급 연차에서 그만큼을 빼고 남은 금액만 새로 가산한다
    kept = sum(c.closing for c in carries if c.keep and c.closing > 0)
    year_end = max(0, raw - kept)
    p.values.update({"유보유지": kept, "기말미지급연차": year_end})
    adjs = [Adj("가산", subj_now, year_end, "유보", "당기 미지급 연차수당", "미지급 연차수당(지급 의무 미확정) 손금불산입",
                "기말미지급연차", subj_now, "증가", 1)]
    for c in carries:
        subj = c.subject
        if c.closing > 0:
            adjs.append(Adj("차감", subj, c.amount, "유보", f"전기분 추인/{subj}", "전기 손금불산입한 미지급 연차수당 당기 손금산입",
                            c.key_applied, subj, "감소", 1))
        else:
            adjs.append(Adj("가산", subj, c.amount, "유보", f"전기분 추인/{subj}", "전기 유보 당기 추인", c.key_applied, subj, "감소", -1))
            p.confirm.append(f"전기 50호(을) {subj} 유보가 △ {abs(c.closing):,}원입니다. 연차수당 유보는 보통 + 입니다. 추인 방향을 확인하세요")
    reversal = sum(c.amount for c in carries)
    p.values["전기분추인"] = reversal
    p.adjustments = adjs

    # 확인 · 메모: 전기 유보 대조(전기 유보 기말 · 당기 추인액 · 근거 전표)
    got = paid(b, p.lines, vouchers)
    found = bool(prior) and got["lines"] > 0
    p.extra["carries"] = carries
    p.values["전기 유보 대조"] = [{**c.json(), "근거": got, "근거 있음": found} for c in carries]
    for c in carries:
        side = "차감" if c.closing > 0 else "가산"
        carry_notes(p, c, law=LAW, if_reverse=f"당기에 지급했거나 지급 의무가 확정됐으면 추인합니다. 그렇게 하면 {side} {c.asked:,}원이고 "
                                              f"기말 미지급 연차 {max(0, raw):,}원을 다시 가산합니다.")
    if prior:
        head = carry_head(carries)
        if found:
            parts = " · ".join(f"{k} {got[k]:,}원" for k in ("지급", "역분개", "나머지") if got[k])
            down = f"감소 {got['감소']:,}원" + (f"({parts})" if parts else "")
            p.notes.append(f"{head}. 근거 전표: 연차 줄 가운데 노란 칸 O {got['lines']}줄({down} · 설정 {tri(got['설정'])}원). 추인액과 당기분 "
                           f"가산 {year_end:,}원의 차이(순 유보 증감)는 이 줄에서만 나옵니다")
        elif reversal:
            p.confirm.append(f"{head}. 장부에서 연차 지급 · 역분개 · 설정 줄(노란 칸 O)을 찾지 못해 추인의 근거 전표가 없습니다. 추인한 금액을 "
                             f"당기분 {year_end:,}원으로 다시 가산해 순 유보 증감은 {year_end - reversal:,}원입니다. 당기 지급 · 기말 미지급 "
                             "연차를 확인하세요")
        else:
            p.notes.append(f"{head}. 장부에 연차 줄(노란 칸 O)이 없습니다")
    if kept and raw < kept:
        p.confirm.append(f"연차 줄로 셈한 기말 미지급 연차 {raw:,}원이 그대로 둔 전기 유보 {kept:,}원보다 작습니다. 모자라는 {kept - raw:,}원은 "
                         "당기에 지급 · 확정됐을 수 있으니 추인할지 확인하십시오(엔진은 조정하지 않았습니다)")

    if picked and not prior and not planned:
        p.confirm.append(f"장부에 연차 미지급 줄 {len(picked)}개(설정 {set_all:,}원)가 있습니다. 전기 연차 유보가 없어 손금으로 두었습니다. "
                         "지급 의무가 확정되지 않은 연차(발생예정분 등)면 노란 칸을 O 로 바꾸세요")
    if raw < 0:
        p.confirm.append(f"전기 유보 - 감소 + 설정이 {raw:,}원으로 음수라 기말 미지급 연차를 0 으로 두었습니다. 연차 명세와 맞추세요")
    if picked:
        p.notes.append("기말 미지급 연차수당은 장부 연차 줄로 셈했습니다(전기 유보 - 감소 O + 설정 O - 그대로 둔 전기 유보). "
                       "연차 명세(미사용 일수 · 통상임금)와 맞추세요")
    p.notes.append("연차 줄은 부채 계정 줄 중 적요에 연차 · 년차 · 연가 · 휴가가 있는 줄입니다. 다른 미확정비용(미지급 성과급 등)은 "
                   "15호 「직접 조정」 줄에 넣으세요")
    p.settle(bool(picked or prior))


def write(bk: Book, p: Paper) -> None:
    s = head(bk, p)
    row = s.section(5, "1. 연차 줄이 있는 부채 계정")
    for col, label in ((3, "코드"), (4, "계정"), (5, "기초"), (7, "기말(재무제표)")):
        X.header(s.ws, row, [label], col=col)
    row += 1
    for a in p.accounts:
        s.put(row, 3, a["code"])
        s.put(row, 4, a["name"])
        s.put(row, 5, -int(a.get("opening") or 0), money=True)
        s.put(row, 7, int(a.get("amount") or 0), money=True)
        row += 1
    if not p.accounts:
        s.put(row, 4, "장부에서 연차 줄을 찾지 못했습니다")
        row += 1
    row, first, last = ledger(bk, s, row + 1, p, PICK,
                              title="2. 원장 검토(연차 줄, 금액은 차변 - 대변. 노란 칸 O = 지급 의무 미확정)")
    v = p.values
    row = s.section(row, "3. 손금불산입 · 추인")
    r = Rows(bk, s, p, row)
    g = r.g
    r.put("설정합계", "연차 설정(대변 줄) 합계", f'=-SUMIFS(G{first}:G{last},H{first}:H{last},"{SET}")')
    r.put("감소합계", "연차 감소(지급 · 역분개) 합계", f'=SUMIFS(G{first}:G{last},H{first}:H{last},"{DOWN}")')
    r.put("기초유보", "기초 미지급 연차 유보(전기 50호(을))", v["기초유보"])
    r.put("감소O", "감소 중 노란 칸 O", f'=SUMIFS(G{first}:G{last},H{first}:H{last},"{DOWN}",I{first}:I{last},"O")')
    r.put("설정O", "설정 중 노란 칸 O", f'=-SUMIFS(G{first}:G{last},H{first}:H{last},"{SET}",I{first}:I{last},"O")')
    carries = p.extra.get("carries", [])
    carry_rows(r, p, carries, "손금산입 · 유보", note="기본은 전기 유보 전액. 아직 확정 · 지급되지 않은 금액은 빼세요")
    held = [f'IF({g(c.key_mode)}="{KEEP}",{c.closing},0)' for c in carries if c.closing > 0]
    r.put("유보유지", "그대로 둔 전기 유보(추인하지 않는 금액)", "=" + "+".join(held) if held else 0)
    r.put("기말미지급연차", "기말 미지급 연차수당(손금불산입 · 유보)",
          f"=MAX(0,{g('기초유보')}-{g('감소O')}+{g('설정O')}-{g('유보유지')})")
    r.put("전기분추인", "전기분 추인 합계", "=" + "+".join(g(c.key_applied) for c in carries) if carries else 0)
    row = adj_table(bk, s, r.row + 1, p)
    row = forms_table(bk, s, row, p, [("15", "손금불산입 미지급 연차수당(유보)", "기말미지급연차"),
                                      ("15", "손금산입 전기 연차수당 추인(유보)", "전기분추인")])
    notes(s, row, p)
