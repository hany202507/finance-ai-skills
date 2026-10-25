"""16 전기오류수정손익: 영업외 전기오류수정손익 · 이익잉여금에 바로 반영한 전기오류수정손익의 세무조정.

원장 줄마다 상대 계정을 보아 나눈다.
  잉여금 손실 · 이익   자본(이익잉여금) 계정의 전기오류수정손실 · 이익. 손익계산서를 거치지 않는다
  영업외 손실 · 이익   손익 계정(영업외비용 · 영업외수익)의 전기오류수정손실 · 이익
  잉여금 대체          상대 계정이 모두 이익잉여금(미처분 · 이월)인 줄. 결산 대체라 금액에 넣지 않는다(포함 여부 X)

엔진이 넣는 기본 조정(판단은 노란 칸)
  잉여금 손실: 손금산입(기타)과 손금불산입(유보)의 짝. 기본 금액은 전기 50호(을) 음수 유보 가운데 상대 계정 · 적요와 맞는 몫이다.
               맞는 유보가 없으면 0(전기 귀속 손실이면 전기 경정청구 대상이고 당기 조정은 없다).
  잉여금 이익: 익금산입(기타)과 익금불산입(유보)의 짝. 기본 금액은 양수 유보와 맞는 몫.
  영업외 손실: 전액 손금불산입(유보). 영업외 이익: 전액 익금불산입(유보). 귀속 연도가 당기가 아니라는 전제다.
"""
from __future__ import annotations

import re

from ..books import Books
from ..model import DISPOSITIONS, Adj, LineRow, Paper, subject_of
from ..sheet import Book, Rows, adj_table, forms_table, head, ledger, notes

NAME = "전기오류수정손익"
FORMS = ["15", "50을"]
LEDGER_CHECK = False      # 자본 계정 amount 는 대변 양수라 원장(차변 - 대변) 합계와 부호가 다르다. 원장 줄은 아래 표에 다 있다
PICK = "포함 여부"
WORDS = ("전기오류수정", "전기손익수정", "과년도손익수정", "전기수정손")
SURPLUS = re.compile(r"이익잉여금|미처분|이월이익|미처리결손|이월결손|처분전")
RECEIVABLE = ("외상매출금", "매출채권", "받을어음", "미수금")
KINDS = ("잉여금 손실", "잉여금 이익", "영업외 손실", "영업외 이익")


def _accounts(b: Books) -> list[dict]:
    return [a for a in b.accounts(cls=("자본", "수익", "비용")) if any(w in (a.get("name") or "") for w in WORDS)]


def _vouchers(b: Books, keys: set) -> dict:
    out: dict = {}
    for ln in b.all_lines():
        k = (ln.date, ln.no)
        if k in keys:
            out.setdefault(k, []).append(ln)
    return out


def _kind(acct: dict) -> str:
    gain = "이익" in (acct.get("name") or "") and "손실" not in (acct.get("name") or "")
    if acct.get("class") == "자본":
        return "잉여금 이익" if gain else "잉여금 손실"
    if acct.get("class") == "수익" or gain:
        return "영업외 이익"
    return "영업외 손실"


def _match(reserves: list[dict], texts: str, sign: int) -> dict | None:
    """전기 50호(을) 유보 가운데 부호가 sign 이고 과목이 상대 계정 · 적요에 걸리는 줄."""
    for r in reserves:
        closing = int(r.get("closing") or 0)
        subj = str(r.get("subject") or "")
        if not subj or closing == 0 or (closing > 0) != (sign > 0):
            continue
        if subj in texts or (subj in RECEIVABLE and re.search(r"채권|매출", texts)):
            return r
    return None


def compute(p: Paper, b: Books) -> None:
    accts = _accounts(b)
    p.accounts = accts
    by_code = {a["code"]: a for a in accts}
    lines = b.lines_of(accts)
    vouchers = _vouchers(b, {(ln.date, ln.no) for ln in lines})
    counters: dict[str, list[str]] = {}
    for ln in lines:
        others = [o for o in vouchers.get((ln.date, ln.no), []) if o.account != ln.account]
        names = [b.by_code.get(o.account, {}).get("name") or o.account_name for o in others]
        kind = _kind(by_code[ln.account])
        if names and all(SURPLUS.search(n or "") for n in names):
            p.lines.append(LineRow(ln, "잉여금 대체", "X", why="상대 계정이 이익잉여금뿐이라 결산 대체로 보았습니다"))
        else:
            p.lines.append(LineRow(ln, kind, "O", why="상대 계정 " + (" · ".join(dict.fromkeys(names)) or "없음")))
            counters.setdefault(kind, []).extend(n for n in names if n and not SURPLUS.search(n))
    p.take_lines(b, PICK)
    sums = {k: sum(r.line.amount for r in p.lines if r.label == k and r.pick == "O") for k in KINDS}
    amounts = {"잉여금 손실": sums["잉여금 손실"], "잉여금 이익": -sums["잉여금 이익"],
               "영업외 손실": sums["영업외 손실"], "영업외 이익": -sums["영업외 이익"]}
    texts = {k: " ".join(counters.get(k, []) + [r.line.memo for r in p.lines if r.label == k]) for k in KINDS}
    reserves = (b.prior or {}).get("reserves") or []

    matched: dict[str, dict | None] = {}
    for k, sign in (("잉여금 손실", -1), ("영업외 손실", -1), ("잉여금 이익", 1), ("영업외 이익", 1)):
        matched[k] = _match(reserves, texts[k], sign) if amounts[k] > 0 else None

    def subj50(k):
        m = matched[k]
        if m:
            return str(m["subject"])
        names = list(dict.fromkeys(counters.get(k, [])))
        return names[0] if names else subject_of([a for a in accts if _kind(a) == k], k)

    def cap(k):
        m = matched[k]
        return min(amounts[k], abs(int(m.get("closing") or 0))) if m else 0

    p.values = {**amounts}
    pair_loss = p.take(b, "잉여금 손실/짝 금액", cap("잉여금 손실"), "int")
    pair_loss_subj = p.take(b, "잉여금 손실/50을 과목", subj50("잉여금 손실"))
    pl_loss = p.take(b, "영업외 손실/손금불산입", amounts["영업외 손실"], "int")
    pl_loss_disp = p.take(b, "영업외 손실/처분", "유보")
    pl_loss_subj = p.take(b, "영업외 손실/50을 과목", subj50("영업외 손실"))
    pl_gain = p.take(b, "영업외 이익/익금불산입", amounts["영업외 이익"], "int")
    pl_gain_disp = p.take(b, "영업외 이익/처분", "유보")
    pl_gain_subj = p.take(b, "영업외 이익/50을 과목", subj50("영업외 이익"))
    pair_gain = p.take(b, "잉여금 이익/짝 금액", cap("잉여금 이익"), "int")
    pair_gain_subj = p.take(b, "잉여금 이익/50을 과목", subj50("잉여금 이익"))
    for key, disp, side in (("영업외 손실/처분", pl_loss_disp, "가산"), ("영업외 이익/처분", pl_gain_disp, "차감")):
        if disp not in DISPOSITIONS[side]:
            p.confirm.append(f"「{key}」 칸 「{disp}」 을 읽지 못해 유보로 두었습니다({' · '.join(DISPOSITIONS[side])})")
    if pl_loss_disp not in DISPOSITIONS["가산"]:
        pl_loss_disp = "유보"
    if pl_gain_disp not in DISPOSITIONS["차감"]:
        pl_gain_disp = "유보"
    p.values.update({"잉여금 손실/짝 금액": pair_loss, "영업외 손실/손금불산입": pl_loss,
                     "영업외 이익/익금불산입": pl_gain, "잉여금 이익/짝 금액": pair_gain,
                     "전기 유보 맞춤": {k: (matched[k] or {}).get("subject") for k in KINDS}})

    def col(k, sign):
        return {"reserve_col": "증가", "reserve_sign": sign} if matched[k] else {}

    name = {k: subject_of([a for a in accts if _kind(a) == k], "전기오류수정" + k[-2:]) for k in KINDS}
    p.adjustments = [
        Adj("가산", name["잉여금 손실"], pair_loss, "유보", "잉여금 손실 손금불산입",
            f"이익잉여금에 반영한 전기오류수정손실 손금불산입하고 유보로 처분함({pair_loss_subj})", "잉여금 손실/짝 금액",
            reserve_subject=pair_loss_subj, **col("잉여금 손실", 1)),
        Adj("차감", name["잉여금 손실"], pair_loss, "기타", "잉여금 손실 손금산입",
            "이익잉여금에 반영한 전기오류수정손실 손금산입하고 기타로 처분함", "잉여금 손실/짝 금액"),
        Adj("가산", name["영업외 손실"], pl_loss, pl_loss_disp, "영업외 손실 손금불산입",
            f"전기 귀속 전기오류수정손실 손금불산입하고 {pl_loss_disp}로 처분함", "영업외 손실/손금불산입",
            reserve_subject=pl_loss_subj, **col("영업외 손실", 1)),
        Adj("차감", name["영업외 이익"], pl_gain, pl_gain_disp, "영업외 이익 익금불산입",
            f"전기 귀속 전기오류수정이익 익금불산입하고 {pl_gain_disp}로 처분함", "영업외 이익/익금불산입",
            reserve_subject=pl_gain_subj, **col("영업외 이익", -1)),
        Adj("차감", name["잉여금 이익"], pair_gain, "유보", "잉여금 이익 익금불산입",
            f"이익잉여금에 반영한 전기오류수정이익 익금불산입하고 유보로 처분함({pair_gain_subj})", "잉여금 이익/짝 금액",
            reserve_subject=pair_gain_subj, **col("잉여금 이익", -1)),
        Adj("가산", name["잉여금 이익"], pair_gain, "기타", "잉여금 이익 익금산입",
            "이익잉여금에 반영한 전기오류수정이익 익금산입하고 기타로 처분함", "잉여금 이익/짝 금액"),
    ]

    # 알릴 것
    debit = sum(r.line.debit for r in p.lines if r.pick == "O")
    credit = sum(r.line.credit for r in p.lines if r.pick == "O")
    if p.lines and not any(amounts.values()) and debit:
        p.notes.append(f"전기오류수정 계정 차변 {debit:,}원 · 대변 {credit:,}원이 서로 지워져 남는 금액이 없습니다(잘못 넣고 되돌린 전표로 보입니다)")
    if amounts["잉여금 손실"]:
        m = matched["잉여금 손실"]
        rest = amounts["잉여금 손실"] - cap("잉여금 손실")
        msg = (f"이익잉여금에 바로 반영한 전기오류수정손실 {amounts['잉여금 손실']:,}원 가운데 "
               + (f"전기 유보 「{m['subject']}」 {int(m['closing']):,}원과 맞는 {cap('잉여금 손실'):,}원을 손금산입(기타) · 손금불산입(유보) 짝으로 넣었습니다. "
                  if m else "전기 유보와 맞는 몫이 없어 짝 조정을 0 으로 두었습니다. ")
               + (f"나머지 {rest:,}원은 전기 귀속이면 전기 경정청구 대상이고 당기 조정이 없습니다. 세무상 자산 · 부채 차이가 남으면 짝 금액에 더하십시오"
                  if rest else ""))
        p.confirm.append(msg.strip())
    if amounts["잉여금 이익"]:
        p.confirm.append(f"이익잉여금에 바로 반영한 전기오류수정이익 {amounts['잉여금 이익']:,}원: 전기 유보와 맞는 몫만 짝 조정(익금산입 기타 · "
                         "익금불산입 유보)으로 넣었습니다. 전기 귀속 익금이면 전기 수정신고 대상입니다")
    if amounts["영업외 손실"] or amounts["영업외 이익"]:
        p.confirm.append("영업외 전기오류수정손익은 귀속 연도가 지난 해라고 보고 전액 손금불산입 · 익금불산입(유보)으로 두었습니다. 당기 손금 · 익금"
                         "이면 노란 칸을 0 으로, 기타사외유출 · 기타면 처분 칸을 고치십시오")
    p.notes.append("적요 · 상대 계정은 원장 표에 있습니다. 「포함 여부」 X 줄은 금액에 넣지 않습니다")
    p.settle(any(amounts.values()) or any(a.amount for a in p.adjustments))
    if p.lines and p.status == "해당 없음":
        p.status = "작성"


def write(bk: Book, p: Paper) -> None:
    s = head(bk, p)
    row, first, last = ledger(bk, s, 5, p, PICK, title="1. 원장 검토(상대 계정 · 적요, 포함 여부 노란 칸)")
    row = s.section(row, "2. 금액")
    r = Rows(bk, s, p, row)

    def sumifs(kind):
        return f'SUMIFS(G{first}:G{last},H{first}:H{last},"{kind}",I{first}:I{last},"O")'
    r.put("잉여금 손실", "이익잉여금에 반영한 전기오류수정손실", f"={sumifs('잉여금 손실')}")
    r.put("잉여금 이익", "이익잉여금에 반영한 전기오류수정이익", f"=-{sumifs('잉여금 이익')}")
    r.put("영업외 손실", "영업외비용 전기오류수정손실", f"={sumifs('영업외 손실')}")
    r.put("영업외 이익", "영업외수익 전기오류수정이익", f"=-{sumifs('영업외 이익')}")
    row = s.section(r.row + 1, "3. 세무조정 판단(노란 칸)")
    r = Rows(bk, s, p, row)
    matched = p.values["전기 유보 맞춤"]
    for key, label, kind, note in (
            ("잉여금 손실/짝 금액", "잉여금 손실: 손금산입(기타) · 손금불산입(유보) 짝 금액", "int",
             f"전기 유보 {matched['잉여금 손실']}" if matched["잉여금 손실"] else "전기 유보와 맞는 몫 없음"),
            ("잉여금 손실/50을 과목", "잉여금 손실: 50호(을) 과목", "text", ""),
            ("영업외 손실/손금불산입", "영업외 손실: 손금불산입 금액", "int", ""),
            ("영업외 손실/처분", "영업외 손실: 소득처분", "text", "유보 · 기타사외유출 · 기타"),
            ("영업외 손실/50을 과목", "영업외 손실: 50호(을) 과목", "text", ""),
            ("영업외 이익/익금불산입", "영업외 이익: 익금불산입 금액", "int", ""),
            ("영업외 이익/처분", "영업외 이익: 소득처분", "text", "유보 · 기타"),
            ("영업외 이익/50을 과목", "영업외 이익: 50호(을) 과목", "text", ""),
            ("잉여금 이익/짝 금액", "잉여금 이익: 익금산입(기타) · 익금불산입(유보) 짝 금액", "int", ""),
            ("잉여금 이익/50을 과목", "잉여금 이익: 50호(을) 과목", "text", "")):
        r.put(key, label, p.inputs[key], kind="input", input_kind=kind, note=note)
    row = adj_table(bk, s, r.row + 1, p, "3-1. 세무조정 · 소득처분")
    row = forms_table(bk, s, row, p, [("15", "잉여금 손실 짝 금액(가산 유보 · 차감 기타)", "잉여금 손실/짝 금액"),
                                      ("15", "영업외 손실 손금불산입", "영업외 손실/손금불산입"),
                                      ("15", "영업외 이익 익금불산입", "영업외 이익/익금불산입")])
    notes(s, row, p)
