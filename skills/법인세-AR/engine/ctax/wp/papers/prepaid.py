"""14 선급비용: 보험료 등 기간미경과분을 회사가 비용으로 처리했으면 손금불산입(유보), 전기분 추인(손금산입 유보).

근거: 법인세법 제40조 제1항(손금은 확정된 날이 속하는 사업연도). 보험기간이 사업연도를 넘는 보험료의 미경과분은 다음
사업연도 손금이다(신고 실무 「보험료기간미경과액」 유보). 미경과액 = 보험료 × 미경과 일수 ÷ 보험기간 일수(원 미만 버림).

원장 검토(후보 줄): 비용 계정 차변 줄 중
  - 적요에 보험기간(예 25.07.01~26.06.30)이 적혀 있고 끝일이 사업연도 말 뒤인 줄 → 「적요 기간」
  - 적요 기간은 없지만 보험료 · 보증료이고 연 단위로 보이는 줄(보증 · 화재 · 배상 · 자동차 · 차량번호 · 근재 등) → 「기간 추정」
    (보험기간을 지급일부터 1년으로 둔다)
  4대보험 · 산재 · 출장 보험, 선급비용을 함께 대체하는 전표(재수정 역분개 · 결산 미경과 계상)는 뺀다.
노란 칸 「손금불산입」(O · X)의 기본값:
  - 회사가 결산에서 미경과 보험료를 선급비용으로 잡았으면(차변 선급비용 · 대변 비용 전표) 모두 X(이미 이연함)
  - 아니면 「적요 기간」 은 O. 「기간 추정」 은 전기 50호(을)에 미경과 유보가 있으면 O(전기 처리를 잇는다), 없으면 X
노란 칸 「보험기간」 은 「2025-07-01~2026-06-30」 꼴. 고치고 다시 돌리면 일수와 미경과액이 바뀐다.

전기 유보 처리(노란 칸 「전기 유보 처리/<과목>」, 그대로 · 추인. `prior_compare.carry`)
  추인    전기 미경과 유보를 노란 칸 추인액(기본 전액)만큼 추인한다. 기본값이다. 전기 보험기간이 끝난 날은 당기 장부에 없다.
          당기에 낸 보험료 · 보증료 줄(4대보험 · 출장 보험 뺌)이 있으면 갱신 정황으로 메모에 적고, 하나도 없으면 확인 줄을 낸다.
  그대로  추인하지 않는다. 전기 신고서가 그 유보를 한 해 동안 그대로 두었을 때(전기 50호(을) 기초 = 기말 · 증감 0, 전기 15호에
          선급비용 · 미경과 줄 없음)만 기본값이고 조서는 「확인 필요」 다. 보험기간이 여러 해인 보험일 수 있다.
  손금은 확정된 날이 속하는 사업연도에 귀속한다(법인세법 제40조 제1항). 보험기간이 당기에 끝났는지는 엔진이 정하지 않는다.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from fractions import Fraction

from ... import xlsx as X
from ..books import Books, rd
from ..model import Adj, LineRow, Paper
from ..prior_compare import carry, carry_head, carry_notes, carry_rows
from ..sheet import Book, Rows, adj_table, forms_table, head, ledger, notes

NAME = "선급비용"
FORMS = ["15", "50을", "선급비용명세서"]
LEDGER_CHECK = False     # 비용 계정 중 보험 후보 줄만 본다
PICK, PICK2 = "손금불산입", "보험기간"
EXPLICIT, ASSUMED = "적요 기간", "기간 추정"
PREPAID = ("선급비용", "선급보험료")
_D = r"(\d{2,4})\s*[./\-년]\s*(\d{1,2})\s*[./\-월]\s*(\d{1,2})\s*일?"
_SEP = r"\s*(?:[~∼〜\-–]|부터|에서)\s*(?:[~∼〜\-–]\s*)?"
RANGE = re.compile(_D + _SEP + _D + r"(?:\s*까지)?")
# 끝일에 연도가 없는 꼴(25.07.01~06.30): 끝일이 시작일보다 앞서면 다음 해
RANGE_NO_YEAR = re.compile(_D + _SEP + r"(\d{1,2})\s*[./\-월]\s*(\d{1,2})\s*일?(?!\s*[./\-]?\s*\d)(?:\s*까지)?")
# 숫자만 붙여 쓴 꼴(20250701~20260630, 250701-260630)
RANGE_COMPACT = re.compile(r"(?<![\d_])(\d{8}|\d{6})\s*[~∼〜\-–]\s*(\d{8}|\d{6})(?![\d_])")
# 월까지만 쓴 꼴(2025.10~2026.09, 2025년 10월 ~ 2026년 9월): 시작 월 1일 ~ 끝 월 말일
RANGE_MONTH = re.compile(r"(?<![\d.])(\d{4})\s*[./\-년]\s*(\d{1,2})\s*월?" + _SEP +
                         r"(\d{4})\s*[./\-년]\s*(\d{1,2})\s*월?(?!\s*[./\-]?\s*\d)(?:\s*까지)?")
MAX_DAYS = 366 * 5                       # 이보다 긴 기간은 날짜로 보지 않는다(번호를 잘못 읽은 것)
SOCIAL = re.compile(r"4대보험|사회보험|산재|고용보험|국민연금|건강보험|국민건강|장기요양|근로복지공단")
TRAVEL = re.compile(r"출장|여행|항공")
INSURANCE = re.compile(r"보험|보증료|보증서|공제료")
FEE = re.compile(r"수수료|조사료|인지대|인지세")              # 보증서 발급 때 함께 내는 신용조사수수료 등(기간 비용 아님)
INS_MEMO = re.compile(r"보험료|보증료|보증보험|공제료")
ANNUAL = re.compile(r"보증|화재|배상|자동차|차량|근재|재산|책임|갱신|연간|1년|굴삭기|중장비|건설기계|\d{2,3}\s?[가-힣]\s?\d{4}")
RESERVE = re.compile(r"선급비용|선급보험료|미경과")
ADD = "전기분 추인액"
LAW = "손금은 확정된 날이 속하는 사업연도에 귀속하고 보험료는 보험기간이 지난 부분이 그 사업연도 손금입니다(법인세법 제40조 제1항)."


def basis(rates: dict) -> list[tuple]:
    r = rates["prepaid"]
    return [("기간미경과 보험료", r["period_rule"]["value"], r["period_rule"]["basis"], r["period_rule"]["grade"], None),
            ("미경과액 계산", r["day_basis"]["value"], r["day_basis"]["basis"], r["day_basis"]["grade"], None)]


# 기간 ----------------------------------------------------------------------------------------------

def _date(y: str | int, m: str | int, d: str | int) -> date | None:
    year = int(y)
    if year < 100:
        year += 2000
    if not 2000 <= year <= 2100:
        return None
    try:
        return date(year, int(m), int(d))
    except ValueError:
        return None


def _month_end(y: str, m: str) -> date | None:
    first = _date(y, m, 1)
    if not first:
        return None
    nxt = date(first.year + (first.month == 12), first.month % 12 + 1, 1)
    return nxt - timedelta(days=1)


def _compact(s: str) -> date | None:
    return _date(s[:4], s[4:6], s[6:]) if len(s) == 8 else _date(s[:2], s[2:4], s[4:])


def _ok(start: date | None, end: date | None) -> tuple[date, date] | None:
    if not start or not end or end < start or (end - start).days > MAX_DAYS:
        return None
    return start, end


def parse_period(text: str, loose: bool = True) -> tuple[date, date] | None:
    """적요 · 노란 칸 글에서 (시작일, 끝일). 읽는 꼴: 「25.07.01~26.06.30」 · 「2025.07.01-2026.06.30」 · 「2025-07-01~2026-06-30」 ·
    「2025년 7월 1일부터 2026년 6월 30일까지」 · 「25.07.01~06.30」(끝일 연도 없음, 다음 해) · 「20250701~20260630」 ·
    「250701-260630」 · 「2025.07~2026.06」(월까지만, 시작 월 1일 ~ 끝 월 말일). 못 읽으면 None.
    loose 가 거짓이면 연 · 월 · 일이 모두 적힌 첫 꼴만 읽는다(보험 · 보증이 아닌 비용 줄에서 번호를 날짜로 잘못 읽지 않게)."""
    text = text or ""
    for m in RANGE.finditer(text):
        got = _ok(_date(*m.groups()[:3]), _date(*m.groups()[3:]))
        if got:
            return got
    if not loose:
        return None
    for m in RANGE_NO_YEAR.finditer(text):
        start = _date(*m.groups()[:3])
        if not start:
            continue
        end = _date(start.year, *m.groups()[3:])
        if end and end < start:
            end = _date(start.year + 1, *m.groups()[3:])
        got = _ok(start, end)
        if got:
            return got
    for m in RANGE_COMPACT.finditer(text):
        got = _ok(_compact(m.group(1)), _compact(m.group(2)))
        if got:
            return got
    for m in RANGE_MONTH.finditer(text):
        got = _ok(_date(m.group(1), m.group(2), 1), _month_end(m.group(3), m.group(4)))
        if got:
            return got
    return None


def strip_period(text: str) -> str:
    """적요에서 보험기간 글을 걷어 낸다(선급비용명세서 적요란, 기간은 비고란에 따로 적는다)."""
    out = text or ""
    for rx in (RANGE, RANGE_NO_YEAR, RANGE_COMPACT, RANGE_MONTH):
        out = rx.sub("", out)
    out = re.sub(r"\(\s*\)|\[\s*\]", "", out)
    return re.sub(r"\s{2,}", " ", out).strip(" ,·")


def show(period: tuple[date, date]) -> str:
    return f"{period[0].isoformat()}~{period[1].isoformat()}"


def one_year(start: date) -> tuple[date, date]:
    try:
        nxt = start.replace(year=start.year + 1)
    except ValueError:                       # 2월 29일
        nxt = start.replace(year=start.year + 1, day=28)
    return start, nxt - timedelta(days=1)


def days(period: tuple[date, date], fy_end: date) -> tuple[int, int]:
    """(보험기간 일수, 사업연도 말 뒤 미경과 일수). 시작일 · 끝일 모두 넣어 센다."""
    start, end = period
    total = (end - start).days + 1
    left_from = max(start, fy_end + timedelta(days=1))
    left = max(0, (end - left_from).days + 1)
    return total, left


def unexpired(amount: int, total: int, left: int) -> int:
    return rd(Fraction(amount * left, total)) if total > 0 else 0


# 장부 ----------------------------------------------------------------------------------------------

def prior_rows(b: Books) -> list[tuple[str, int]]:
    out = []
    for r in (b.prior or {}).get("reserves", []) or []:
        subj = r.get("subject") or ""
        closing = int(r.get("closing") or 0)
        if closing and RESERVE.search(subj):
            out.append((subj, closing))
    return out


def _fy_end(b: Books) -> date:
    try:
        return date.fromisoformat(b.info.get("fy_end") or "")
    except ValueError:
        return date(int(b.fy or 2025), 12, 31)


def _scan(b: Books, codes: set, fy_end: date):
    """(회사 결산 미경과 계상 줄 [(선급비용 줄, 비용 줄)], 선급비용이 든 전표의 (일자, 번호) 집합)."""
    vouchers: dict = {}
    for ln in b.lines:
        vouchers.setdefault((ln.date, ln.no), []).append(ln)
    deferral, touched = [], set()
    month = fy_end.isoformat()[:7]
    for key, lines in vouchers.items():
        pre = [x for x in lines if x.account in codes]
        if not pre:
            continue
        exp_cr = [x for x in lines if b.by_code.get(x.account, {}).get("class") == "비용" and x.amount < 0]
        exp_dr = [x for x in lines if b.by_code.get(x.account, {}).get("class") == "비용" and x.amount > 0]
        pre_dr = [x for x in pre if x.amount > 0]
        pre_cr = [x for x in pre if x.amount < 0]
        if pre_dr and exp_cr:
            touched.add(key)
            if key[0][:7] == month:
                deferral += [(pre_dr[0], x) for x in exp_cr]
        elif pre_cr and exp_dr:
            touched.add(key)
    return deferral, touched


def reopened(b: Books, codes: set) -> int:
    """전기말 회사가 선급비용으로 잡은 미경과 보험료를 사업연도 첫 달에 보험료 등 비용으로 돌린 금액(선급비용 대변 · 보험 비용
    차변 전표). 회사가 전기에 보험료 기간을 나눠 처리했다는 단서다."""
    try:
        start = date.fromisoformat(b.info.get("fy_start") or "")
    except ValueError:
        return 0
    month = start.isoformat()[:7]
    vouchers: dict = {}
    for ln in b.lines:
        if ln.date[:7] == month:
            vouchers.setdefault((ln.date, ln.no), []).append(ln)
    total = 0
    for lines in vouchers.values():
        if not any(x.account in codes and x.amount < 0 for x in lines):
            continue
        for x in lines:
            a = b.by_code.get(x.account, {})
            text = f"{a.get('name') or x.account_name} {x.memo}"
            if a.get("class") == "비용" and x.amount > 0 and INSURANCE.search(text):
                total += x.amount
    return total


def _related(a: dict) -> bool:
    """전기 15호 줄이 선급비용 · 기간미경과 줄인가(과목 · 조정내용)."""
    return bool(RESERVE.search(f"{a.get('subject') or ''} {a.get('note') or ''}"))


def renewed(b: Books) -> dict:
    """당기에 낸 보험료 · 보증료 줄(4대보험 · 산재 · 출장 보험과 수수료만 낸 줄은 뺌). 전기 보험을 다시 들었다는 정황이다.
    전기 보험기간이 끝난 날은 알려 주지 않는다. {lines, amount}."""
    out = {"lines": 0, "amount": 0}
    for ln in b.lines:
        a = b.by_code.get(ln.account, {})
        name = a.get("name") or ln.account_name
        if a.get("class") != "비용" or ln.amount <= 0:
            continue
        if SOCIAL.search(f"{name} {ln.partner} {ln.memo}") or TRAVEL.search(ln.memo or ""):
            continue
        if not INSURANCE.search(f"{name} {ln.memo}"):
            continue
        if FEE.search(ln.memo or "") and "보험" not in name and not INS_MEMO.search(ln.memo or ""):
            continue
        out["lines"] += 1
        out["amount"] += ln.amount
    return out


def compute(p: Paper, b: Books) -> None:
    accts = b.accounts(cls="자산", any_of=PREPAID)
    p.accounts = accts
    codes = {a["code"] for a in accts}
    with_prepaid = {(x.date, x.no) for x in b.lines if x.account in codes}
    fy_end = _fy_end(b)
    deferral, touched = _scan(b, codes, fy_end)
    prior = prior_rows(b)
    company_defers = bool(deferral)
    back = 0 if company_defers or prior else reopened(b, codes)
    for ln in sorted(b.lines, key=lambda x: (x.date, x.no, x.account)):
        a = b.by_code.get(ln.account, {})
        name = a.get("name") or ln.account_name
        if a.get("class") != "비용" or ln.amount <= 0 or (ln.date, ln.no) in touched:
            continue
        text = f"{name} {ln.partner} {ln.memo}"
        if SOCIAL.search(text) or TRAVEL.search(ln.memo or ""):
            continue
        insurance = bool(INSURANCE.search(f"{name} {ln.memo}"))
        fee_only = bool(FEE.search(ln.memo or "")) and "보험" not in name and not INS_MEMO.search(ln.memo or "")
        period = parse_period(ln.memo, loose=insurance)
        if period:
            label = EXPLICIT
        elif insurance and not fee_only and ANNUAL.search(f"{ln.partner} {ln.memo}"):
            try:
                period, label = one_year(date.fromisoformat(ln.date)), ASSUMED
            except ValueError:
                continue
        else:
            continue
        total, left = days(period, fy_end)
        if left <= 0:
            continue
        if company_defers:
            pick, why = "X", "회사가 결산에서 미경과 보험료를 선급비용으로 잡았습니다. 이 줄이 빠졌으면 O"
        elif label == EXPLICIT:
            pick, why = "O", "적요의 보험기간이 사업연도 말을 넘습니다"
        elif prior:
            pick, why = "O", "보험기간을 지급일부터 1년으로 추정. 전기 미경과 유보가 있어 같은 처리를 이었습니다"
        elif back:
            pick, why = "O", ("보험기간을 지급일부터 1년으로 추정. 전기말 회사가 미경과 보험료를 선급비용으로 잡았다가 첫 달에 비용으로 "
                              "돌려 같은 보험을 갱신한 것으로 보았습니다")
        else:
            pick, why = "X", "보험기간을 지급일부터 1년으로 추정. 보험증권 기간을 넣고 O 로 바꾸세요"
        if (ln.date, ln.no) in with_prepaid:
            why += ". 같은 전표에 선급비용 차변이 있습니다(회사가 일부를 이미 이연했는지 확인)"
        p.lines.append(LineRow(ln, label, pick, show(period), why=why))
    p.take_lines(b, PICK, PICK2)

    rows_days, bad = [], []
    for r in p.lines:
        period = parse_period(r.pick2)
        if not period:
            bad.append(r.pick2 or "(빈 칸)")
            period = parse_period(r.default2)
        total, left = days(period, fy_end)
        rows_days.append((total, left, unexpired(r.line.amount, total, left), period))
    p.extra["days"] = rows_days

    picked = [(r, d) for r, d in zip(p.lines, rows_days) if r.pick == "O"]
    disallow = sum(d[2] for _, d in picked)
    company = sum(-x.amount for _, x in deferral)
    p.values = {"선급비용기초": sum(int(a.get("opening") or 0) for a in accts),
                "선급비용기말": sum(int(a.get("closing") or 0) for a in accts),
                "회사계상미경과": company, "후보미경과": sum(d[2] for d in rows_days), "미경과손금불산입": disallow}
    insurance = any(INSURANCE.search(f"{b.by_code.get(r.line.account, {}).get('name', '')} {r.line.memo}") for r, _ in picked)
    subj_now = prior[0][0] if prior else ("보험료기간미경과액" if insurance or not picked else "선급비용")
    adjs = [Adj("가산", subj_now, disallow, "유보", "당기 기간미경과", "보험료 등 기간미경과분 손금불산입",
                "미경과손금불산입", subj_now, "증가", 1)]
    carries = [carry(p, b, subj, close, f"{ADD}/{subj}", _related) for subj, close in prior]
    for c in carries:
        subj = c.subject
        if c.closing > 0:
            adjs.append(Adj("차감", subj, c.amount, "유보", f"전기분 추인/{subj}", "전기 손금불산입한 기간미경과분 당기 손금산입",
                            c.key_applied, subj, "감소", 1))
        else:
            adjs.append(Adj("가산", subj, c.amount, "유보", f"전기분 추인/{subj}", "전기 유보 당기 추인", c.key_applied, subj, "감소", -1))
    reversal = sum(c.amount for c in carries)
    p.values["전기분추인"] = reversal
    p.adjustments = adjs

    # 전기 유보 대조(전기 유보 기말 · 당기 추인액 · 근거 전표)
    got = renewed(b) if prior else {"lines": 0, "amount": 0}
    found = bool(prior) and got["lines"] > 0
    p.extra["carries"] = carries
    p.values["전기 유보 대조"] = [{**c.json(), "근거": got, "근거 있음": found} for c in carries]
    for c in carries:
        side = "차감" if c.closing > 0 else "가산"
        carry_notes(p, c, law=LAW, if_reverse=f"보험기간이 당기에 끝났으면 추인합니다. 그렇게 하면 {side} {c.asked:,}원입니다.")
    if prior:
        head = carry_head(carries)
        unknown = "전기 보험기간이 끝난 날은 당기 장부로 알 수 없습니다"
        if found:
            p.notes.append(f"{head}. {unknown}. 당기에 낸 보험료 · 보증료 {got['lines']}줄 {got['amount']:,}원(갱신 정황)을 찾았습니다. "
                           f"보험기간이 당기말 뒤까지 남은 전기 보험이 있으면 노란 칸 「{ADD}」 에서 그 미경과액을 빼세요")
        elif reversal:
            p.confirm.append(f"{head}. {unknown}. 당기에 낸 보험료 · 보증료 줄도 없어 추인의 근거 전표를 찾지 못했습니다. 전기 선급비용명세서의 "
                             f"보험기간을 확인하고, 당기말 뒤까지 남은 미경과액은 노란 칸 「{ADD}」 에서 빼세요")
        else:
            p.notes.append(f"{head}. {unknown}")

    # 선급비용명세서 줄(서식 플러그인이 읽는다)
    items = []
    for r, (total, left, amt, period) in picked:
        if amt:
            items.append({"kind": "손금불산입", "구분": _kind(b, r.line), "적요": strip_period(r.line.memo) or r.line.memo,
                          "거래처": r.line.partner, "금액": amt, "기간": f"{period[0]:%Y.%m.%d}~{period[1]:%Y.%m.%d}"})
    for pre, x in deferral:
        period = parse_period(x.memo)
        items.append({"kind": "회사 계상", "구분": _kind(b, x, pre.memo), "적요": strip_period(x.memo) or x.memo,
                      "거래처": x.partner, "금액": -x.amount,
                      "기간": f"{period[0]:%Y.%m.%d}~{period[1]:%Y.%m.%d}" if period else ""})
    p.values["명세"] = items

    # 확인 · 메모
    if bad:
        p.confirm.append(f"보험기간 칸을 읽지 못해 엔진 기간으로 계산한 줄이 {len(bad)}개 있습니다(예 {bad[0]}). 「2025-07-01~2026-06-30」 꼴로 넣으세요")
    guessed = [(r, d) for r, d in zip(p.lines, rows_days) if r.label == ASSUMED and r.pick2 == r.default2]
    assumed_x = [(r, d) for r, d in guessed if r.pick == "X"]
    if assumed_x and not company_defers:
        amt = sum(d[2] for _, d in assumed_x)
        text = (f"적요에 보험기간이 없는 연 단위 보험료 · 보증료 {len(assumed_x)}줄은 손금으로 두었습니다. 보험증권 기간을 「보험기간」 "
                f"칸에 넣고 O 로 바꾸면 미경과액을 손금불산입합니다(지급일부터 1년으로 보면 {amt:,}원)")
        back = reopened(b, codes)
        if back:
            text += (f". 전기말 회사가 미경과 보험료 {back:,}원을 선급비용으로 잡았다가 사업연도 첫 달에 비용으로 돌렸는데 당기말에는 "
                     "잡지 않았습니다. 같은 보험을 갱신했다면 이 줄들에도 미경과분이 있습니다")
        p.confirm.append(text)
    if company_defers:
        p.notes.append(f"회사가 결산에서 미경과 보험료 {company:,}원을 선급비용으로 잡았습니다. 후보 줄 미경과액 합계 "
                       f"{p.values['후보미경과']:,}원과 견주어 빠진 보험이 있으면 그 줄을 O 로 바꾸세요")
    if any(r.pick == "O" for r, _ in guessed):
        p.notes.append("「기간 추정」 줄은 지급일부터 1년을 보험기간으로 두었습니다. 보험증권의 기간으로 고치세요(노란 칸)")
    if back and any(r.pick == "O" for r, _ in guessed):
        p.notes.append(f"전기말 회사가 미경과 보험료 {back:,}원을 선급비용으로 잡았다가 사업연도 첫 달에 비용으로 돌렸습니다. "
                       "같은 보험을 갱신한 것으로 보고 적요에 기간이 없는 연 단위 보험료 줄을 O 로 두었습니다")
    p.notes.append("4대보험 · 산재 · 출장 보험은 후보에서 뺐습니다. 보험 외 기간 비용(임차료 선지급 · 연간 사용료)은 적요에 기간이 "
                   "있을 때만 후보에 듭니다")
    p.settle(bool(accts or p.lines or prior))


def _kind(b: Books, ln, extra: str = "") -> str:
    name = b.by_code.get(ln.account, {}).get("name") or ln.account_name
    return "선급보험료" if INSURANCE.search(f"{name} {ln.memo} {extra}") else "선급비용"


def write(bk: Book, p: Paper) -> None:
    s = head(bk, p)
    row = s.section(5, "1. 회사 계상 선급비용")
    for col, label in ((3, "코드"), (4, "계정"), (5, "기초"), (7, "기말(재무제표)")):
        X.header(s.ws, row, [label], col=col)
    row += 1
    for a in p.accounts:
        s.put(row, 3, a["code"])
        s.put(row, 4, a["name"])
        s.put(row, 5, int(a.get("opening") or 0), money=True)
        s.put(row, 7, int(a.get("closing") or 0), money=True)
        row += 1
    company = [i for i in p.values.get("명세", []) if i["kind"] == "회사 계상"]
    if company:
        row += 1
        X.header(s.ws, row, ["", "", "", "구분", "거래처", "적요(결산 미경과 계상)", "금액"])
        row += 1
        for i in company:
            s.put(row, 4, i["구분"])
            s.put(row, 5, i["거래처"])
            s.put(row, 6, i["적요"])
            s.put(row, 7, i["금액"], money=True)
            row += 1
    row, first, last = ledger(bk, s, row + 1, p, PICK, PICK2,
                              title="2. 원장 검토(보험료 등 후보 줄, 노란 칸 O = 미경과분 손금불산입)")
    hdr = first - 1
    for col, label in ((12, "보험기간 일수"), (13, "미경과 일수"), (14, "미경과액")):
        X.header(s.ws, hdr, [label], col=col)
        s.ws.column_dimensions[chr(64 + col)].width = 14
    for i, (total, left, _, _) in enumerate(p.extra.get("days", [])):
        r = first + i
        s.put(r, 12, total, fmt="0")
        s.put(r, 13, left, fmt="0")
        s.put(r, 14, f"=IF(L{r}>0,ROUNDDOWN(G{r}*M{r}/L{r},0),0)", money=True)
    v = p.values
    row = s.section(row, "3. 손금불산입 · 추인")
    r = Rows(bk, s, p, row)
    g = r.g
    r.put("선급비용기말", "회사 계상 선급비용 기말(재무제표)", v["선급비용기말"])
    r.put("회사계상미경과", "결산 미경과 보험료 계상(회사)", v["회사계상미경과"])
    r.put("후보미경과", "후보 줄 미경과액 합계(참고)", f"=SUM(N{first}:N{last})")
    r.put("미경과손금불산입", "기간미경과분 손금불산입(노란 칸 O 줄, 유보)", f'=SUMIFS(N{first}:N{last},I{first}:I{last},"O")',
          note="보험기간 칸을 고치면 ctax wp 를 다시 돌려 일수를 바꾸세요")
    carries = p.extra.get("carries", [])
    carry_rows(r, p, carries, "손금산입 · 유보", note="기본은 전기 유보 전액. 보험기간이 당기말 뒤까지 남은 금액은 빼세요")
    r.put("전기분추인", "전기분 추인 합계", "=" + "+".join(g(c.key_applied) for c in carries) if carries else 0)
    row = adj_table(bk, s, r.row + 1, p)
    row = forms_table(bk, s, row, p, [("15", "손금불산입 보험료 기간미경과분(유보)", "미경과손금불산입"),
                                      ("15", "손금산입 전기 미경과분 추인(유보)", "전기분추인"),
                                      ("선급비용명세서", "손금불산입계 ④금액", "미경과손금불산입")])
    notes(s, row, p)
