"""9 인정이자: 특수관계인 가지급금 · 대여금 인정이자 익금산입(부당행위계산 부인). 19호(갑)(을).

계산
  대상 계정   가지급금 · 주임종단기채권 · 단기 · 장기대여금 등(자산, 이름으로 고름)
  거래처 잔액 기말은 거래처 명세(장부.json partners, 없으면 0), 기중 증감은 전표.csv, 기초 = 기말 - 기중 증감.
              기말 0 인 거래처는 명세에 없어서 전표로 기초를 되짚는다. 거래처 기초 합계가 계정 기초와 다르면
              차이를 「(기초 차이)」 줄로 둔다
  적수        잔액이 바뀐 날부터 다음 변동 전날까지(초일 산입 · 말일 불산입), 마지막 구간은 사업연도 끝날까지
  인정이자    차감적수 × 적용이자율 ÷ 연일수(윤년 366), 원 미만 버림
  회사계상액  같은 거래처 이자수익(노란 칸)
  조정액      차액(인정이자 - 회사계상액)이 3억원 이상이거나 인정이자의 5% 이상일 때 차액(시행령 제88조 제3항)

특수관계인 여부는 엔진이 정하지 않는다. 거래처마다 노란 칸 「특수관계인」 기본값이 「확인 필요」 이고 그때는 조정을
넣지 않는다. 「특수관계인일 때 조정액」 은 모든 줄에 보인다. 가지급금 · 가수금 상계와 업무무관 가지급금 지급이자(26호)는
이 조서가 계산하지 않고 메모로만 남긴다.
"""
from __future__ import annotations

import calendar
import re
from datetime import date
from fractions import Fraction

from ... import xlsx as X
from ..books import Books, Line, frac, rate, rd
from ..model import Adj, Paper
from ..sheet import BOLD, Book, Rows, adj_table, forms_table, head, notes

NAME = "인정이자"
FORMS = ["19갑", "19을", "15"]
LEDGER_CHECK = False

LOAN = re.compile(r"가지급금|대여금|주\.?\s?임\.?\s?종|주주.?임원.?(단기)?채권|임원.?(단기)?채권|종업원.?대여")
NOT_LOAN = re.compile(r"대손충당금|현재가치|미수|이자|선급")
TIED = re.compile(r"가지급금|주\.?\s?임\.?\s?종|주주|임원|종업원")      # 이름부터 특수관계인 대여로 보이는 계정
SUSPENSE = re.compile(r"가수금|주주.?임원.?(단기)?채무|주\.?\s?임\.?\s?종.*채무|임원.?(단기)?차입")
NO_PARTNER = ("", "미등록거래처", "(거래처 없음)")
NONE_NAME = "(거래처 없음)"
GAP_NAME = "(기초 차이)"

PICK_RELATED = "특수관계인"
PICK_DISP = "소득처분"
PICK_BOOKED = "회사계상 이자"
RELATED = ("예", "아니오", "확인 필요")
DISPOSITIONS = ("상여", "배당", "기타사외유출", "기타소득")
CHOICE = ("당좌대출이자율", "가중평균차입이자율")
SUBJECT = "가지급금인정이자"


def basis(rates: dict) -> list[tuple]:
    li = rates["loan_interest"]
    return [("당좌대출이자율", li["overdraft_rate"]["value"], li["overdraft_rate"]["basis"], li["overdraft_rate"]["grade"], "0.0%"),
            ("부당행위 시가 차액 기준금액", li["threshold_amount"]["value"], li["threshold_amount"]["basis"],
             li["threshold_amount"]["grade"], None),
            ("부당행위 시가 차액 기준비율", li["threshold_ratio"]["value"], li["threshold_ratio"]["basis"],
             li["threshold_ratio"]["grade"], "0%")]


# 공용(대손충당금 조서도 쓴다) ---------------------------------------------------------------------------

def loan_accounts(b: Books) -> list[dict]:
    return [a for a in b.accounts(cls="자산") if LOAN.search(a.get("name", "")) and not NOT_LOAN.search(a.get("name", ""))]


def partner_name(name: str | None, acct: dict | None = None) -> str:
    """거래처 이름. 거래처가 없는 줄은 계정마다 따로 「(거래처 없음 · 계정)」 으로 묶는다."""
    s = (name or "").strip()
    if s in NO_PARTNER:
        return f"{NONE_NAME[:-1]} · {acct['name']})" if acct else NONE_NAME
    return s


def norm_related(v) -> str:
    s = str(v or "").strip().upper()
    if s in ("예", "O", "Y", "YES", "여", "해당", "특수관계인"):
        return "예"
    if s in ("아니오", "아니요", "X", "N", "NO", "부", "해당 없음", "비해당"):
        return "아니오"
    return "확인 필요"


def related_of(b: Books, partner: str) -> str:
    """회계사가 인정이자 조서에 넣은 특수관계인 값. 없으면 「확인 필요」."""
    from ..model import MISSING
    got = b.override("loan_interest", f"{PICK_RELATED}/{partner}")
    return "확인 필요" if got is MISSING else norm_related(got)


def _blank() -> dict:
    return {"opening": 0, "closing": 0, "debit": 0, "credit": 0, "lines": []}


def _goes_negative(e: dict) -> bool:
    bal = e["opening"]
    days: dict[str, int] = {}
    for ln in e["lines"]:
        days[ln.date] = days.get(ln.date, 0) + ln.debit - ln.credit
    if bal < 0:
        return True
    for d in sorted(days):
        bal += days[d]
        if bal < 0:
            return True
    return False


def account_partners(b: Books, acct: dict, merge: bool = True) -> dict[str, dict]:
    """한 계정의 거래처별 {opening, closing, debit, credit, lines}. 기초 = 기말 - 기중 증감(전표).

    기말은 거래처 명세(장부.json partners)에서 읽고 명세에 없는 거래처는 0 이다. 계정 줄이 명세에 하나도 없으면
    계정 기말이 0 일 때 모든 거래처 기말을 0 으로 본다. 거래처 기초 합계가 계정 기초와 다르면 차이를 「(기초 차이)」 줄로
    둔다. 전표의 거래처 표시가 일관되지 않아 어느 거래처 잔액이 음수로 내려가면 그 계정은 거래처를 나누지 않고 한 줄로 본다."""
    code = acct["code"]
    lines = b.lines_of([acct])
    rows = [r for r in (b.ledger.get("partners") or []) if str(r.get("account")) == code]
    opening, closing = int(acct.get("opening") or 0), int(acct.get("closing") or 0)
    out: dict[str, dict] = {}
    for ln in lines:
        e = out.setdefault(partner_name(ln.partner, acct), _blank())
        e["debit"] += ln.debit
        e["credit"] += ln.credit
        e["lines"].append(ln)
    if rows:
        for r in rows:
            out.setdefault(partner_name(r.get("partner"), acct), _blank())["closing"] += int(r.get("closing") or 0)
    elif len(out) == 1:
        next(iter(out.values()))["closing"] = closing
    elif closing:
        for e in out.values():
            e["closing"] = e["debit"] - e["credit"]
    for e in out.values():
        e["opening"] = e["closing"] - (e["debit"] - e["credit"])
    gap = opening - sum(e["opening"] for e in out.values())
    if gap:
        e = out.setdefault(GAP_NAME if rows or len(out) == 1 else partner_name("", acct), _blank())
        e["opening"] += gap
        e["closing"] += gap
        e["gap"] = e.get("gap", 0) + gap
    if merge and len(out) > 1 and any(_goes_negative(e) for e in out.values()):
        one = {"opening": opening, "closing": closing, "debit": sum(ln.debit for ln in lines),
               "credit": sum(ln.credit for ln in lines), "lines": list(lines), "merged": True}
        return {f"(거래처 구분 안 됨 · {acct['name']})": one}
    return {k: v for k, v in out.items() if v["lines"] or v["opening"] or v["closing"]}


def excluded_for_bad_debt(b: Books, acct: dict) -> tuple[int, int]:
    """대손충당금 설정제외 채권 기본값 (기말, 기초). 인정이자 조서에서 특수관계인 「예」 인 거래처 잔액, 이름부터
    특수관계인 대여인 계정(가지급금 · 주임종)은 「확인 필요」 거래처도 넣는다(법인세법 제34조 제2항)."""
    if not (LOAN.search(acct.get("name", "")) and not NOT_LOAN.search(acct.get("name", ""))):
        return 0, 0
    tied = bool(TIED.search(acct.get("name", "")))
    close = open_ = 0
    for name, e in account_partners(b, acct).items():
        rel = related_of(b, name)
        if rel == "예" or (tied and rel == "확인 필요"):
            close += max(0, e["closing"])
            open_ += max(0, e["opening"])
    return close, open_


# 적수 ---------------------------------------------------------------------------------------------

def _d(s: str, lo: date, hi: date) -> date:
    try:
        d = date.fromisoformat(str(s)[:10])
    except ValueError:
        return lo
    return min(max(d, lo), hi)


def timeline(opening: int, lines: list[Line], start: date, end: date) -> list[dict]:
    """19호(을) 꼴 줄: 기초 줄 + 잔액이 바뀐 날마다 한 줄. 일수는 다음 줄 날짜까지(마지막 줄은 끝날 포함)."""
    days: dict[date, list[Line]] = {}
    for ln in lines:
        days.setdefault(_d(ln.date, start, end), []).append(ln)
    rows = [{"date": start, "memo": "기초 잔액", "debit": max(opening, 0), "credit": max(-opening, 0)}]
    for d in sorted(days):
        ls = days[d]
        memo = ls[0].memo or ls[0].account_name
        if len(ls) > 1:
            memo = f"{memo} 외 {len(ls) - 1}건"
        rows.append({"date": d, "memo": memo, "debit": sum(x.debit for x in ls), "credit": sum(x.credit for x in ls)})
    bal = 0
    for i, r in enumerate(rows):
        bal += r["debit"] - r["credit"]
        nxt = rows[i + 1]["date"] if i + 1 < len(rows) else None
        r["balance"] = bal
        r["days"] = (nxt - r["date"]).days if nxt else (end - r["date"]).days + 1
        r["product"] = max(0, bal) * r["days"]
        r["date"] = r["date"].isoformat()
    return rows


def year_days(start: date, end: date) -> int:
    """사업연도에 2월 29일이 들어 있으면 366."""
    for y in range(start.year, end.year + 1):
        if calendar.isleap(y) and start <= date(y, 2, 29) <= end:
            return 366
    return 365


# 가지급금 · 대여금 계정 밖의 가지급 · 가불(10-20) -----------------------------------------------------------
# AR advance:<계정 코드> 규칙(ar/engine.py rule_hidden_advance)과 같은 낱말 · 조건이다. 전도금 · 선급금 같은 자산 계정에 가지급 · 가불
# 적요가 있으면 그 적요 줄의 거래처를 인정이자 대상 「확인 필요」 로 넣는다. 회계사가 특수관계인 「예」 를 고르면 금액이 나온다.
ADVANCE = re.compile(r"가지급|가불")
CASH = re.compile(r"현금|예금|적금")
# 은행 · 금융기관 계좌가 거래처로 올라온 줄(「기업은행(029)」 처럼 은행명 · 계좌 코드). 특수관계인 기본값을 「아니오」 로 둔다
BANK = re.compile(r"은행|뱅크|금고|농협|수협|신협|증권|저축|\(\d{3}\)$")


def is_bank(name: str) -> bool:
    return bool(BANK.search(str(name or "").strip()))


def advance_accounts(b: Books) -> list[tuple[dict, set]]:
    """[(계정, 가지급 · 가불 적요 줄의 거래처 이름 모음)]. 가지급금 · 대여금 · 현금 · 예금 계정은 빼고, 같은 전표에 가지급금 ·
    대여금 계정 줄이 있는 줄(그 계정 거래의 상대 줄)도 뺀다. 기말 잔액이 있거나 적요 줄이 둘 이상인 계정만."""
    loans = {a["code"] for a in loan_accounts(b)}
    skip = loans | {a["code"] for a in b.accounts(cls="자산") if CASH.search(a.get("name", ""))}
    vouchers: dict[tuple, set] = {}
    for ln in b.all_lines():
        vouchers.setdefault((ln.date, ln.no), set()).add(ln.account)
    out = []
    for a in b.accounts(cls="자산"):
        if a["code"] in skip:
            continue
        hits = [ln for ln in b.lines_of([a]) if ADVANCE.search(ln.memo or "")
                and not (vouchers.get((ln.date, ln.no), set()) & loans)]
        if not hits or (int(a.get("closing") or 0) <= 0 and len(hits) < 2):
            continue
        out.append((a, {partner_name(ln.partner, a) for ln in hits}))
    return out


# 계산 ---------------------------------------------------------------------------------------------

COMPANY = re.compile(r"주식회사|\(주\)|㈜|유한회사|합자회사|법인|은행|조합")
OWNER = re.compile(r"대표|사장|임원|주주")


def _guess_disp(name: str, accts: list[dict], lines: list[Line]) -> str:
    """소득처분 노란 칸 기본값. 주임종 · 가지급금 계정이나 적요에 대표 · 임원이 있으면 상여, 아니면 기타사외유출."""
    if any(TIED.search(a.get("name", "")) for a in accts):
        return "상여"
    if not COMPANY.search(name) and any(OWNER.search(ln.memo or "") for ln in lines):
        return "상여"
    return "기타사외유출"


def _interest_by_partner(b: Books) -> dict[str, int]:
    accts = [a for a in b.accounts(cls="수익") if "이자" in a.get("name", "")]
    out: dict[str, int] = {}
    for ln in b.lines_of(accts):
        name = partner_name(ln.partner)
        if name == NONE_NAME:
            continue
        out[name] = out.get(name, 0) + ln.credit - ln.debit
    return out


def compute(p: Paper, b: Books) -> None:
    accts = loan_accounts(b)
    p.accounts = accts
    try:
        start = date.fromisoformat(b.info["fy_start"])
        end = date.fromisoformat(b.info["fy_end"])
    except (KeyError, ValueError):
        y = int(b.fy or 2025)
        start, end = date(y, 1, 1), date(y, 12, 31)
    ndays = year_days(start, end)
    overdraft = rate(b.rates, "loan_interest", "overdraft_rate")
    choice = p.take(b, "이자율 선택", CHOICE[0], "text")
    weighted = p.take(b, "가중평균차입이자율", 0.0, "ratio")
    if choice == CHOICE[1] and weighted > 0:
        used = weighted
    else:
        used = overdraft
        if choice == CHOICE[1]:
            p.confirm.append("이자율 선택이 가중평균차입이자율인데 비율 칸이 비어 있어 당좌대출이자율을 썼습니다")
        elif choice != CHOICE[0]:
            p.confirm.append(f"이자율 선택 「{choice}」 을 읽지 못해 당좌대출이자율을 썼습니다(고를 수 있는 값: 당좌대출이자율 · 가중평균차입이자율)")
    cap = rate(b.rates, "loan_interest", "threshold_amount")
    ratio_cap = frac(rate(b.rates, "loan_interest", "threshold_ratio"))

    merged: dict[str, dict] = {}
    gaps, merged_notes = [], []
    for a in accts:
        for name, e in account_partners(b, a).items():
            m = merged.setdefault(name, {"accounts": [], "opening": 0, "closing": 0, "debit": 0, "credit": 0, "lines": []})
            m["accounts"].append(a)
            for k in ("opening", "closing", "debit", "credit"):
                m[k] += e[k]
            m["lines"] += e["lines"]
            if e.get("gap"):
                gaps.append(f"{a['name']}({a['code']}) {e['gap']:,}원")
            if e.get("merged"):
                merged_notes.append(a["name"])
    advance_notes = []
    for a, names in advance_accounts(b):
        # 거래처를 하나로 합치지 않는다(전도금처럼 거래처 표시가 들쭉날쭉한 계정도 가지급 적요 거래처만 따로 본다)
        got = {k: v for k, v in account_partners(b, a, merge=False).items() if k in names}
        for name, e in got.items():
            m = merged.setdefault(name, {"accounts": [], "opening": 0, "closing": 0, "debit": 0, "credit": 0, "lines": []})
            m["accounts"].append(a)
            m["advance"] = True
            for k in ("opening", "closing", "debit", "credit"):
                m[k] += e[k]
            m["lines"] += e["lines"]
        if got:
            advance_notes.append(f"{a['name']}({a['code']}) {', '.join(sorted(got))}")
    booked_default = _interest_by_partner(b)
    rows = []
    for name in sorted(merged, key=lambda n: (n.startswith("("), n)):
        m = merged[name]
        lines = sorted(m["lines"], key=lambda x: (x.date, x.no))
        periods = timeline(m["opening"], lines, start, end)
        product = sum(r["product"] for r in periods)
        if not product and not m["closing"] and not lines:
            continue
        related = norm_related(p.take(b, f"{PICK_RELATED}/{name}", "아니오" if is_bank(name) else "확인 필요", "text"))
        disp = p.take(b, f"{PICK_DISP}/{name}", _guess_disp(name, m["accounts"], lines), "text")
        if disp not in DISPOSITIONS:
            p.confirm.append(f"{name} 소득처분 「{disp}」 을 읽지 못해 상여로 두었습니다(고를 수 있는 값: {' · '.join(DISPOSITIONS)})")
            disp = "상여"
        booked = p.take(b, f"{PICK_BOOKED}/{name}", booked_default.get(name, 0), "int")
        interest = rd(Fraction(product) * frac(used) / ndays)
        diff = interest - booked
        over = diff > 0 and (diff >= cap or diff >= interest * ratio_cap)
        if_related = diff if over else 0
        rows.append({"partner": name, "accounts": [a["code"] for a in m["accounts"]],
                     "account_names": [a["name"] for a in m["accounts"]], "opening": m["opening"], "debit": m["debit"],
                     "credit": m["credit"], "closing": m["closing"], "적수": product, "가수금적수": 0, "차감적수": product,
                     "인정이자": interest, "회사계상": booked, "차액": diff,
                     "비율": (diff / interest * 100) if interest else 0.0, "시가기준": over,
                     "특수관계인일 때 조정액": if_related, "특수관계인": related, "소득처분": disp,
                     "조정액": if_related if related == "예" else 0, "periods": periods,
                     "출처": "가지급 적요" if m.get("advance") else ("은행 계좌" if is_bank(name) else "계정")})
    for i, r in enumerate(rows, start=1):
        r["i"] = i
    unknown = [r for r in rows if r["특수관계인"] == "확인 필요" and r["적수"]]
    p.values = {"이자율선택": choice if choice in CHOICE else CHOICE[0], "가중평균차입이자율": weighted, "적용이자율": used,
                "연일수": ndays, "가지급금적수": sum(r["적수"] for r in rows),
                "인정이자": sum(r["인정이자"] for r in rows), "회사계상": sum(r["회사계상"] for r in rows),
                "특수관계인일 때 조정액": sum(r["특수관계인일 때 조정액"] for r in rows),
                "확인 필요 인정이자": sum(r["인정이자"] for r in unknown),
                "확인 필요 조정액": sum(r["특수관계인일 때 조정액"] for r in unknown),
                "조정액": sum(r["조정액"] for r in rows), "확인 필요 거래처": len(unknown), "거래처": rows}
    p.extra["rows"] = rows
    p.adjustments = [Adj("가산", SUBJECT, r["조정액"], r["소득처분"], f"인정이자 {r['partner']}",
                         f"{r['partner']} 가지급금 인정이자 익금산입", f"p{r['i']}.조정액") for r in rows if r["특수관계인"] == "예"]

    v = p.values
    live = [r for r in rows if r["적수"]]
    if unknown:
        p.confirm.append(f"특수관계인 여부를 정하지 않은 거래처 {len(unknown)}곳은 조정을 넣지 않았습니다(노란 칸 「확인 필요」). "
                         f"특수관계인이면 인정이자 {v['확인 필요 인정이자']:,}원, 조정액(차액 3억원 이상 또는 5% 이상) {v['확인 필요 조정액']:,}원입니다")
    if advance_notes:
        p.confirm.append("가지급금 · 대여금 계정이 아닌 계정에 가지급 · 가불 적요가 있어 그 거래처를 「확인 필요」 로 넣었습니다: "
                         + "; ".join(advance_notes) + ". 특수관계인 대여가 맞으면 「예」, 업무용 전도금 · 선급금이면 「아니오」 로 고르십시오")
    banks = [r["partner"] for r in rows if r["출처"] == "은행 계좌"]
    if banks:
        p.notes.append(f"은행 · 금융기관 계좌로 보이는 거래처 {', '.join(banks)} 는 특수관계인 기본값을 「아니오」 로 두었습니다")
    if gaps:
        p.confirm.append("거래처 기초 합계가 계정 기초와 달라 차이를 따로 한 줄로 두었습니다: " + ", ".join(gaps))
    if merged_notes:
        p.notes.append(f"{', '.join(merged_notes)} 은 전표의 거래처 표시로 잔액을 나누면 음수가 되는 거래처가 있어 계정 전체를 한 줄로 "
                       "계산했습니다. 거래처별로 나누려면 원장을 보고 특수관계인 대여분만 따로 계산하세요")
    for r in rows:
        if any(x["balance"] < 0 for x in r["periods"]):
            p.notes.append(f"{r['partner']} 잔액이 음수인 기간이 있어 그 기간 적수는 0 으로 보았습니다")
    if live:
        p.notes.append(f"적용이자율 {used * 100:g}%({'가중평균차입이자율' if used != overdraft else '당좌대출이자율'}). "
                       "원칙은 가중평균차입이자율입니다(시행령 제89조 제3항). 차입금 자료로 비율을 계산해 노란 칸에 넣고 선택을 바꾸면 그 율로 다시 계산합니다. "
                       "당좌대출이자율을 고르면 그 사업연도와 이후 2개 사업연도에 계속 적용합니다")
        p.notes.append("적수는 잔액이 바뀐 날부터 다음 변동 전날까지(초일 산입), 마지막 구간은 사업연도 끝날까지 셉니다. "
                       f"인정이자 = 차감적수 × 이자율 ÷ {ndays}, 원 미만 버림")
        p.notes.append("직원 경조사비 · 학자금 대여, 중소기업 직원 주택자금 대여 등은 인정이자 대상이 아닙니다(시행규칙 제44조). "
                       "해당 거래처는 특수관계인 칸을 「아니오」 로 두세요")
        p.notes.append("특수관계인 「예」 로 정한 거래처 잔액은 대손충당금 설정 대상 채권에서 뺍니다(10 대손충당금 조서가 읽음)")
    susp = [a for a in b.accounts(cls="부채") if SUSPENSE.search(a.get("name", ""))]
    if live and susp:
        names = ", ".join(f"{a['name']} 기말 {int(a.get('amount') or 0):,}원" for a in susp)
        p.notes.append(f"가수금 · 주주임원 채무 계정이 있습니다({names}). 같은 사람의 가지급금과 상계할지는 이 조서가 계산하지 않습니다"
                       "(상계 약정이 있으면 차감적수가 줄어듭니다)")
    if any(r["특수관계인"] == "예" for r in rows):
        interest_exp = [a for a in b.accounts(cls="비용") if "이자비용" in a.get("name", "") or "지급이자" in a.get("name", "")]
        if interest_exp:
            p.notes.append("특수관계인 가지급금이 있고 이자비용이 있습니다. 업무무관 가지급금 지급이자 손금불산입(26호)은 이 조서가 계산하지 않습니다")
    p.settle(bool(live))


# 엑셀 ---------------------------------------------------------------------------------------------

WIDTHS = [22, 16, 12, 12, 18, 12, 18, 14, 14, 14, 10, 16, 14]


def write(bk: Book, p: Paper) -> None:
    s = head(bk, p)
    X.widths(s.ws, WIDTHS)
    v, R = p.values, bk.ref
    rows = p.extra.get("rows", [])
    row = s.section(5, "1. 적용이자율")
    r = Rows(bk, s, p, row)
    g = r.g
    r.put("이자율 선택", "이자율 선택(당좌대출이자율 · 가중평균차입이자율)", p.inputs["이자율 선택"], kind="input", input_kind="text")
    r.put("당좌대출이자율", "당좌대출이자율(기준 2025)", f"={R['당좌대출이자율']}", fmt="0.00%")
    r.put("가중평균차입이자율", "가중평균차입이자율(차입금 자료로 계산해 넣음)", p.inputs["가중평균차입이자율"], kind="input",
          input_kind="ratio", fmt="0.00%")
    r.put("적용이자율", "적용이자율",
          f'=IF({g("이자율 선택")}="가중평균차입이자율",IF({g("가중평균차입이자율")}>0,{g("가중평균차입이자율")},{g("당좌대출이자율")}),'
          f'{g("당좌대출이자율")})', fmt="0.00%")
    r.put("연일수", "연일수(윤년 366)", v["연일수"], fmt="0")
    rate_ref, days_ref = f"${g('적용이자율')[0]}${g('적용이자율')[1:]}", f"${g('연일수')[0]}${g('연일수')[1:]}"

    # 2. 거래처별 인정이자(19호(갑)). 적수는 아래 3 의 거래처 묶음 합계를 부른다(행 번호를 먼저 정한다)
    row = s.section(r.row + 1, "2. 거래처별 인정이자(19호(갑))")
    X.header(s.ws, row, ["거래처", "계정", "특수관계인", "소득처분", "가지급금적수", "가수금적수", "차감적수", "인정이자",
                         "회사계상액", "차액", "비율(%)", "특수관계인일 때 조정액", "조정액"])
    row += 1
    first = row
    blocks_at = first + max(1, len(rows)) + 3
    sub_rows = {}
    at = blocks_at + 1
    for rr in rows:
        at += 2                                  # 묶음 제목 · 머리 줄
        sub_rows[rr["i"]] = at + len(rr["periods"])
        at += len(rr["periods"]) + 2
    for rr in rows:
        i = rr["i"]
        s.put(row, 1, rr["partner"])
        s.put(row, 2, " · ".join(rr["account_names"]))
        s.inp(row, 3, rr["특수관계인"], pid=p.id,
              key=f"{PICK_RELATED}/{rr['partner']}", default=p.defaults.get(f"{PICK_RELATED}/{rr['partner']}", "확인 필요"))
        s.inp(row, 4, rr["소득처분"], pid=p.id, key=f"{PICK_DISP}/{rr['partner']}",
              default=p.defaults.get(f"{PICK_DISP}/{rr['partner']}", rr["소득처분"]))
        s.put(row, 5, f"=G{sub_rows[i]}", money=True)
        s.put(row, 6, 0, money=True)
        s.put(row, 7, f"=E{row}-F{row}", money=True)
        s.put(row, 8, f"=ROUNDDOWN(G{row}*{rate_ref}/{days_ref},0)", money=True)
        s.inp(row, 9, rr["회사계상"], pid=p.id, key=f"{PICK_BOOKED}/{rr['partner']}",
              default=p.defaults.get(f"{PICK_BOOKED}/{rr['partner']}", rr["회사계상"]), kind="int", money=True)
        s.put(row, 10, f"=H{row}-I{row}", money=True)
        s.put(row, 11, f"=IF(H{row}>0,J{row}/MAX(1,H{row})*100,0)", fmt="0.00")
        s.put(row, 12, f"=IF(AND(J{row}>0,OR(J{row}>={R['부당행위 시가 차액 기준금액']},"
                       f"J{row}>=H{row}*{R['부당행위 시가 차액 기준비율']})),J{row},0)", money=True)
        s.put(row, 13, f'=IF(C{row}="예",L{row},0)', money=True)
        for col, field in ((5, "적수"), (7, "차감적수"), (8, "인정이자"), (9, "회사계상"), (10, "차액"), (11, "비율"),
                           (12, "특수관계인일 때 조정액"), (13, "조정액")):
            bk.reg(p.id, f"p{i}.{field}", s.addr(row, col))
        row += 1
    if not rows:
        s.put(row, 1, "가지급금 · 대여금 거래처가 없습니다")
        row += 1
    last = row - 1
    s.put(row, 1, "계")
    for col, key in ((5, "가지급금적수"), (8, "인정이자"), (9, "회사계상"), (12, "특수관계인일 때 조정액"), (13, "조정액")):
        X.cell(s.ws, row, col, f"=SUM({chr(64 + col)}{first}:{chr(64 + col)}{last})", money=True, kind="total")
        bk.reg(p.id, key, s.addr(row, col))
    row += 1
    s.put(row, 1, "확인 필요 거래처")
    s.put(row, 8, f'=SUMIF(C{first}:C{last},"확인 필요",H{first}:H{last})', money=True)
    s.put(row, 12, f'=SUMIF(C{first}:C{last},"확인 필요",L{first}:L{last})', money=True)
    bk.reg(p.id, "확인 필요 인정이자", s.addr(row, 8))
    bk.reg(p.id, "확인 필요 조정액", s.addr(row, 12))
    row += 1

    # 3. 거래처별 적수(19호(을))
    row = s.section(blocks_at, "3. 거래처별 가지급금 적수(19호(을))")
    for rr in rows:
        s.put(row, 1, f"{rr['partner']} ({' · '.join(rr['account_names'])})").font = BOLD
        row += 1
        X.header(s.ws, row, ["일자", "적요", "차변", "대변", "잔액", "일수", "적수"])
        row += 1
        b0 = row
        for k, x in enumerate(rr["periods"]):
            s.put(row, 1, x["date"])
            s.put(row, 2, x["memo"])
            s.put(row, 3, x["debit"], money=True)
            s.put(row, 4, x["credit"], money=True)
            s.put(row, 5, f"=C{row}-D{row}" if k == 0 else f"=E{row - 1}+C{row}-D{row}", money=True)
            s.put(row, 6, x["days"], fmt="0")
            s.put(row, 7, f"=MAX(0,E{row})*F{row}", money=True)
            row += 1
        assert row == sub_rows[rr["i"]], (row, sub_rows[rr["i"]])
        s.put(row, 1, "적수 계")
        X.cell(s.ws, row, 7, f"=SUM(G{b0}:G{row - 1})", money=True, kind="total")
        row += 2
    row = adj_table(bk, s, row + 1, p)
    row = forms_table(bk, s, row, p, [("19갑", "② 가지급금적수 계", "가지급금적수"), ("19갑", "⑤ 인정이자 계", "인정이자"),
                                      ("19갑", "⑥ 회사계상액 계", "회사계상"), ("19갑", "⑨ 조정액 계", "조정액")])
    notes(s, row, p)


__all__ = ["NAME", "FORMS", "compute", "write", "basis", "loan_accounts", "account_partners", "excluded_for_bad_debt",
           "related_of", "norm_related", "timeline", "year_days", "partner_name"]
