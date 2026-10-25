"""15호 조서의 「전기 조정 대조」 표.

전기.json adjustments(전기 15호 줄)마다 당기 엔진 조정(조서가 낸 조정과 회계사 직접 조정 줄)에 같은 과목 줄이 있는지 가린다.
없는 줄에는 당기 전표에서 찾은 단서와 노란 칸 둘(당기 반영 · 당기 금액)을 붙인다. 회계사가 「당기 반영」 을 O 로 바꾸면 그 줄을
전기와 같은 구분 · 소득처분으로 당기 15호에 넣는다(직접 조정 줄과 같은 흐름: 조정.json direct → 15호 · 3호 02 · 03 · 50호(을)).
엔진이 기본값을 O 로 두는 것은 유보 짝 조정 하나뿐이다(`pair_defaults`, 10-21). 나머지 줄은 기본 X 라 조정 금액이 바뀌지 않는다.

과목 대응은 채점기(`ctax.score.match`)의 과목 묶음 `topic` 과 이름 정규화 `norm_subject` 를 그대로 쓴다. 전기 줄 하나에 당기 줄
하나를 짝짓고(쓴 줄은 다시 쓰지 않음) 다섯 차례로 본다: 구분 · 과목 이름 · 처분이 같음 → 구분 · 과목 이름이 같음 → 구분 · 묶음 · 처분 ·
금액이 같음 → 구분 · 묶음 · 처분이 같음 → 구분 · 묶음이 같고 둘 다 유보이거나 둘 다 유보가 아님.

다섯 차례에서 짝을 찾지 못한 전기 유보 줄은 구분(가산 · 차감)이 반대인 당기 유보 줄을 한 번 더 찾는다(`flip`). 평가이익이 평가손실로
바뀐 해처럼 조정 방향이 뒤집힌 과목이다. 같은 유보 과목이고 유보를 움직이는 쪽(증가 · 감소)이 같을 때만 잇는다. 결과는
「당기 있음(구분 반대)」 이고 확인 줄에는 넣지 않는다. 기타사외유출 같은 유보가 아닌 줄에는 쓰지 않는다.

조서가 함께 쓰는 전기 유보 판별도 여기에 있다(`reserve_still` · `reserve_piling` · `carry`). 전기 중 증감이 없던 유보는 자동으로
추인하지 않게 노란 칸 「전기 유보 처리」(그대로 · 추인)의 기본값을 「그대로」 로 둔다. 대손충당금 조서(10)와 같은 이름 · 값이다.

당기 장부 단서는 전기 과목 · 조정내용에서 뽑은 낱말(`words`)이 적요에 있는 당기 전표다. 낱말 뽑기는 정규식과 상투어 목록(`STOP`)으로만
한다. 사업연도 종료일 전표는 따로 적는다(기말 설정 전표). 「당기 금액」 기본값은 과목에서 뽑은 낱말로 찾은 기말 전표가 한 건일 때 그 금액,
전기 유보가 한 해에 모두 바뀐 과목의 추인 줄이면 전기 유보 기말이고, 아니면 빈 칸이다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .. import xlsx as X
from ..score.match import TOPICS, norm_subject, topic
from .books import Books
from .model import DISPOSITIONS, Adj, Paper

PID = "summary_15"
YES, NO = "당기 있음", "당기 없음"
FLIP = "당기 있음(구분 반대)"   # 같은 유보의 같은 쪽(증가 · 감소) 당기 줄이 있는데 가산 · 차감이 전기와 반대
UP, DOWN = "증가", "감소"       # 유보를 움직이는 쪽(Adj.reserve_col 과 같은 말)
MODE, KEEP, REVERSE = "전기 유보 처리", "그대로", "추인"   # 노란 칸 이름 · 값(대손충당금 조서와 같다)
KIND = "전기 조정 대조"
ROW_BASE = 100            # 대조 표에서 넣은 조정의 Adj.row(직접 조정 줄 1 ~ 5 와 겹치지 않게)
CONFIRM_MIN = 1_000_000   # 이 금액 이상인 줄만 확인 줄을 따로 낸다. 그보다 작은 줄은 한 줄로 묶는다
CONFIRM_MAX = 10          # 따로 내는 확인 줄 수. 넘는 줄도 묶음 줄에 들어간다
APPLY, AMOUNT = "당기 반영", "당기 금액"
NO_CLUE = "당기 장부에서 같은 적요를 찾지 못함"
PICKS = ("O", "X", "N")   # O 넣음 · X 넣지 않음(기본) · N 검토했고 당기에는 없는 조정
WORD_MIN, NOTE_WORD_MIN, WORD_MAX = 3, 4, 6
YEAR_END_MAX = 5

PAREN = re.compile(r"[(（]([^()（）]*)[)）]")
# 조정내용(15호 부표) 상투어. 이 말들로 글을 끊고 남은 토막을 낱말로 쓴다. 긴 말부터 견준다.
# 「처분」 · 「기타」 처럼 과목 이름 안에도 나오는 두 글자 말은 넣지 않는다(토막이 네 글자 미만이면 버리므로 따로 끊지 않아도 된다)
STOP = ("기타사외유출", "손금불산입한", "익금불산입한", "손금불산입", "익금불산입", "손금산입한", "익금산입한", "손금산입", "익금산입",
        "로소득처분함", "소득처분함", "로처분함", "처분분함", "처분함", "처리함", "추인함", "세무조정함", "세무조정",
        "한도초과액", "한도초과", "범위초과액", "사외유출", "에대하여", "에대해서", "에대해", "에대한", "대하여", "대해서", "대한",
        "으로써", "계상액", "계상분", "계상한", "상당액", "초과액", "증감액", "하였음", "하였다", "발생한", "설정한",
        "당해연도", "당기", "전기", "당해", "하고", "하여", "으로", "에서", "부터", "까지")
STOP_RX = re.compile("|".join(sorted(STOP, key=len, reverse=True)))
SUBJECT_TAIL = re.compile(r"(한도초과액|한도초과|범위초과액|초과액|손금불산입|익금불산입|손금산입|익금산입)$")
PARTICLE = re.compile(r"(금액|에|을|를|은|는|의|로|중|등|및)+$")


@dataclass
class Row:
    idx: int                       # 전기.json adjustments 안 차례(1 부터)
    side: str
    subject: str
    amount: int
    disposition: str
    note: str
    topic: str
    no: int = 0                    # 표에 보이는 번호
    pair: int | None = None        # 같은 과목 가산 · 차감 유보 짝 번호
    role: str = ""                 # 설정 · 추인(전기 유보가 한 해에 모두 바뀐 과목)
    move: str = ""                 # 증가 · 감소(이 줄이 전기 유보를 움직인 쪽, 가리지 못하면 빈 글)
    result: str = NO
    how: str = ""
    current: tuple | None = None   # (조서 Paper 또는 None, Adj)
    reserve: dict | None = None    # 이어지는 전기 50호(을) 줄
    clue: dict | None = None
    key: str = ""
    apply: str = "X"
    apply_amount: int = 0
    default_amount: int = 0
    adj: Adj | None = None         # 회계사가 O 로 넣은 조정
    main_row: int = 0              # 15호 본표에 쓴 행(엑셀)

    @property
    def state(self) -> str:
        if self.adj is not None:
            return "회계사 반영"
        return "검토 끝" if self.result == NO and self.apply == "N" else ""

    @property
    def open(self) -> bool:
        """당기에 없고 회계사가 아직 정하지 않은 줄."""
        return self.result == NO and self.apply == "X"

    def json(self) -> dict:
        cur = None
        if self.current:
            paper, a = self.current
            cur = {"paper": paper.id if paper is not None else "direct", "side": a.side, "subject": a.subject,
                   "amount": a.amount, "disposition": a.disposition, "kind": a.kind}
        return {"no": self.no, "side": self.side, "subject": self.subject, "amount": self.amount,
                "disposition": self.disposition, "note": self.note, "topic": self.topic, "pair": self.pair, "role": self.role,
                "move": self.move, "result": self.result, "how": self.how, "state": self.state, "current": cur,
                "reserve": self.reserve, "clue": self.clue, "apply": self.apply if self.result == NO else "",
                "apply_amount": self.apply_amount, "default_amount": self.default_amount, "applied": self.adj is not None,
                "keys": {"apply": f"{self.key}/{APPLY}", "amount": f"{self.key}/{AMOUNT}"} if self.result == NO else {}}


@dataclass
class Compare:
    rows: list[Row] = field(default_factory=list)       # 표에 보이는 차례
    applied: list[Adj] = field(default_factory=list)    # 회계사가 O 로 넣은 조정(직접 조정과 같은 흐름)
    reserves: list[dict] = field(default_factory=list)  # 전기 유보 대조 줄
    auto: list[int] = field(default_factory=list)       # 「당기 반영」 기본값이 O 인 전기 줄 idx(유보 짝 조정, pair_defaults)


def _i(v) -> int:
    try:
        return int(round(float(v or 0)))
    except (TypeError, ValueError):
        return 0


def won(n: int) -> str:
    return f"{int(n):,}"


# ---------------------------------------------------------------- 과목 대응

def match(rows: list[Row], current: list[tuple]) -> list[dict]:
    """전기 줄마다 당기 줄 하나를 짝짓는다. `current` 는 (조서 또는 None, Adj) 목록. 당기 줄 묶음(쓴 줄 표시 포함)을 돌려준다."""
    cur = [{"item": c, "adj": c[1], "names": {norm_subject(c[1].subject), norm_subject(c[1].reserve_subject or "")} - {""},
            "topic": topic(f"{c[1].subject} {c[1].note}"), "used": False} for c in current if c[1].amount]

    passes = (
        (lambda r, c: norm_subject(r.subject) in c["names"] and c["adj"].disposition == r.disposition, "과목 같음"),
        (lambda r, c: norm_subject(r.subject) in c["names"], "과목 같음(처분 다름)"),
        (lambda r, c: bool(r.topic) and r.topic == c["topic"] and c["adj"].disposition == r.disposition
         and c["adj"].amount == r.amount, "묶음 같음"),
        (lambda r, c: bool(r.topic) and r.topic == c["topic"] and c["adj"].disposition == r.disposition, "묶음 같음"),
        (lambda r, c: bool(r.topic) and r.topic == c["topic"]
         and (c["adj"].disposition == "유보") == (r.disposition == "유보"), "묶음 같음(처분 다름)"),
    )
    for cond, how in passes:
        for r in rows:
            if r.current is not None:
                continue
            hit = next((c for c in cur if not c["used"] and c["adj"].side == r.side and cond(r, c)), None)
            if hit is not None:
                hit["used"] = True
                r.current, r.result, r.how = hit["item"], YES, how
    return cur


def _sign(n: int) -> int:
    return (n > 0) - (n < 0)


def move_of(r: Row) -> str:
    """전기 유보 줄이 이어진 50호(을) 줄을 움직인 쪽(증가 · 감소). 가산은 유보를 +, 차감은 - 쪽으로 움직인다.
    기초와 기말 부호가 같으면(한쪽이 0 이어도) 그 부호 쪽으로 움직인 줄이 증가, 반대쪽이 감소다. 한 해에 부호가 바뀐 유보는
    기말 부호 쪽 줄 가운데 금액이 기초 전액과 같으면 감소(기초 추인), 기말과 같으면 증가(새 설정)이고 나머지는 가리지 않는다."""
    x = r.reserve
    if not x or r.side not in ("가산", "차감"):
        return ""
    eff = 1 if r.side == "가산" else -1
    so, sc = _sign(x["opening"]), _sign(x["closing"])
    if so and sc and so != sc:
        if eff != sc:
            return ""
        if r.amount == abs(x["opening"]):
            return DOWN
        return UP if r.amount == abs(x["closing"]) else ""
    base = so or sc
    if not base:
        return ""
    return UP if eff == base else DOWN


def flip(rows: list[Row], cur: list[dict]) -> None:
    """짝을 찾지 못한 전기 유보 줄을 구분이 반대인 당기 유보 줄에 잇는다(`link_reserves` · `pair_up` 뒤에 부른다).

    잇는 조건: 둘 다 유보, 구분이 반대, 당기 줄의 50호(을) 과목이 전기 줄의 과목이나 이어진 전기 50호(을) 과목과 같음, 유보를
    움직이는 쪽(증가 · 감소)이 같음. 전기 추인 줄을 당기 설정 줄에 잇지 않으려는 조건이다. 쪽을 가리지 못한 줄은 잇지 않는다.
    당기 줄 하나에 맞는 전기 줄이 여럿이면 금액이 가장 가까운 줄, 같으면 앞선 줄을 잇는다.
    쓰지 않은 당기 줄이 없으면 같은 과목 짝(가산 · 차감)의 다른 줄이 이미 짝지은 당기 줄을 본다. 전기에는 추인 줄과 설정 줄을
    따로 적었는데 당기 조서는 한 줄로 낸 경우다. 이때도 당기 줄이 움직이는 쪽은 이 전기 줄과 같아야 한다."""
    for r in rows:
        r.move = move_of(r) if r.disposition == "유보" else ""

    def fits(r: Row, c: dict) -> bool:
        a = c["adj"]
        names = {norm_subject(r.subject), norm_subject((r.reserve or {}).get("subject") or "")} - {""}
        return (a.disposition == "유보" and a.side in ("가산", "차감") and a.side != r.side and a.reserve_col == r.move
                and norm_subject(a.reserve_subject or a.subject) in names)

    def waiting() -> list[Row]:
        return [r for r in rows if r.current is None and r.move]

    pairs = [(abs(c["adj"].amount - r.amount), r.idx, n, r, c) for r in waiting() for n, c in enumerate(cur)
             if not c["used"] and fits(r, c)]
    for _, _, _, r, c in sorted(pairs, key=lambda x: x[:3]):
        if r.current is None and not c["used"]:
            c["used"] = True
            r.current, r.result, r.how = c["item"], FLIP, "구분 반대"
    mates: dict[int, list[Row]] = {}
    for r in rows:
        if r.pair:
            mates.setdefault(r.pair, []).append(r)
    for r in waiting():
        for m in mates.get(r.pair or 0, []):
            if m is r or m.current is None or m.result != YES:
                continue
            hit = next((c for c in cur if c["item"] is m.current and fits(r, c)), None)
            if hit is not None:
                r.current, r.result, r.how = hit["item"], FLIP, "구분 반대(짝 줄과 같은 당기 줄)"
                break


def link_reserves(rows: list[Row], reserves: list[dict]) -> None:
    """유보 줄을 전기 50호(을) 줄에 잇는다: 과목 이름이 같음 → 금액이 그 줄의 증가나 감소와 같음(한 줄뿐일 때) → 괄호를 뺀 이름이 같음.
    전기 유보가 한 해에 모두 바뀐 과목(감소 = 기초, 증가 = 기말)이면 설정 · 추인을 가린다."""
    res = [{"subject": str(r.get("subject") or ""), **{k: _i(r.get(k)) for k in ("opening", "decrease", "increase", "closing")}}
           for r in reserves]
    for r in rows:
        if r.disposition != "유보":
            continue
        name = norm_subject(r.subject)
        base = norm_subject(PAREN.sub("", r.subject))
        got = [x for x in res if norm_subject(x["subject"]) == name]
        if not got:
            same = [x for x in res if r.amount and r.amount in (abs(x["increase"]), abs(x["decrease"]))]
            got = same if len(same) == 1 else []
        if not got:
            same = [x for x in res if base and norm_subject(x["subject"]) == base]
            got = same if len(same) == 1 else []
        if not got:
            continue
        x = r.reserve = dict(got[0])
        if x["closing"] and x["decrease"] == x["opening"] and x["increase"] == x["closing"]:
            setting = "가산" if x["closing"] > 0 else "차감"
            r.role = "설정" if r.side == setting else "추인"


def pair_up(rows: list[Row]) -> None:
    """같은 과목의 가산 유보 줄과 차감 유보 줄을 차례대로 짝짓는다(당기분 설정과 전기분 추인)."""
    groups: dict[str, dict[str, list[Row]]] = {}
    for r in rows:
        if r.disposition == "유보" and r.side in ("가산", "차감"):
            groups.setdefault(norm_subject(r.subject), {"가산": [], "차감": []})[r.side].append(r)
    n = 0
    for g in groups.values():
        for a, d in zip(g["가산"], g["차감"]):
            n += 1
            a.pair = d.pair = n


# ---------------------------------------------------------------- 당기 장부 단서

def _add(out: list[str], w: str, least: int) -> None:
    w = re.sub(r"[\s·ㆍ.,]", "", w or "")
    if len(w) >= least and w not in out:
        out.append(w)


def subject_words(subject: str) -> list[str]:
    """과목에서 뽑은 낱말: 괄호 안 낱말 → 괄호를 뺀 과목(끝의 한도초과 같은 말은 뗌). 세 글자 이상."""
    out: list[str] = []
    for m in PAREN.finditer(subject or ""):
        _add(out, m.group(1), WORD_MIN)
    _add(out, SUBJECT_TAIL.sub("", re.sub(r"\s", "", PAREN.sub("", subject or ""))), WORD_MIN)
    return out


def words(subject: str, note: str) -> list[str]:
    """전기 과목 · 조정내용에서 적요를 찾을 낱말을 뽑는다. 과목 낱말 다음에 조정내용을 상투어로 끊은 토막(네 글자 이상)을 둔다."""
    out = subject_words(subject)
    text = re.sub(r"[\s·ㆍ.,()（）]", "", note or "")
    for piece in STOP_RX.split(text):
        _add(out, PARTICLE.sub("", piece), NOTE_WORD_MIN)
    return out[:WORD_MAX]


class Journal:
    """당기 전표를 적요(빈칸 뺌)로 찾는다."""

    def __init__(self, b: Books):
        self.b = b
        self.fy_end = str(b.info.get("fy_end") or (f"{b.fy}-12-31" if b.fy else ""))
        self.memos = [(re.sub(r"\s", "", ln.memo or ""), ln) for ln in b.lines]
        self.vouchers: dict | None = None

    def name(self, ln) -> str:
        return self.b.by_code.get(ln.account, {}).get("name") or ln.account_name

    def voucher(self, key) -> list:
        if self.vouchers is None:
            self.vouchers = {}
            for ln in self.b.lines:
                self.vouchers.setdefault((ln.date, ln.no), []).append(ln)
        return self.vouchers.get(key, [])

    def clue(self, row: Row) -> dict:
        ws = words(row.subject, row.note)
        strong = subject_words(row.subject)
        out = {"words": ws, "word": "", "lines": 0, "debit": 0, "credit": 0, "year_end": [], "year_end_count": 0, "accounts": [],
               "amount": None}
        for w in ws:
            hits = [ln for memo, ln in self.memos if w in memo]
            if not hits:
                continue
            out.update(word=w, lines=len(hits), debit=sum(ln.debit for ln in hits), credit=sum(ln.credit for ln in hits))
            by_no: dict = {}
            for ln in hits:
                if ln.date == self.fy_end:
                    by_no.setdefault((ln.date, ln.no), []).append(ln)
            for key, got in by_no.items():
                out["year_end"].append(self._voucher(key, got))
            # 금액이 하나로 정해지는 때: 과목에서 뽑은 낱말로 찾은 기말 전표가 한 건
            if len(out["year_end"]) == 1 and w in strong:
                out["amount"] = out["year_end"][0]["amount"]
            out["year_end_count"] = len(out["year_end"])
            out["year_end"] = out["year_end"][:YEAR_END_MAX]      # 흔한 낱말이면 기말 전표가 많다. 조정.json 에는 앞의 몇 건만 둔다
            break
        out["accounts"] = self._accounts(ws, row.topic)
        out["text"] = self._text(out)
        return out

    def _voucher(self, key, hits: list) -> dict:
        debit = [ln for ln in hits if ln.debit]
        credit = [ln for ln in hits if ln.credit]
        whole = self.voucher(key)
        if not debit and len(whole) <= 6:
            debit = [ln for ln in whole if ln.debit]
        if not credit and len(whole) <= 6:
            credit = [ln for ln in whole if ln.credit]
        hit_debit = sum(ln.debit for ln in hits)
        return {"date": key[0], "no": key[1], "amount": hit_debit or sum(ln.credit for ln in hits),
                "debit": sorted({self.name(ln) for ln in debit}), "credit": sorted({self.name(ln) for ln in credit})}

    def _accounts(self, ws: list[str], tp: str) -> list[dict]:
        """이름에 낱말이 든 당기 계정(없으면 같은 묶음의 낱말로). 금액이 큰 차례로 셋까지."""
        accts = [a for a in self.b.ledger.get("accounts", []) if _i(a.get("amount"))]

        def named(keys) -> list[dict]:
            return [a for a in accts if any(k in re.sub(r"\s", "", a.get("name") or "") for k in keys)]

        got = named(ws) or named(next((keys for name, keys in TOPICS if name == tp), ()))
        got.sort(key=lambda a: (-abs(_i(a.get("amount"))), str(a.get("code"))))
        return [{"code": str(a.get("code")), "name": str(a.get("name") or ""), "amount": _i(a.get("amount"))} for a in got[:3]]

    @staticmethod
    def _text(c: dict) -> str:
        parts = []
        if c["year_end_count"] > 2:
            parts.append(f"기말 전표 {c['year_end_count']}건(금액이 하나로 정해지지 않음)")
        else:
            for v in c["year_end"]:
                side = f"차변 {' · '.join(v['debit'])} " if v["debit"] else ""
                other = f", 대변 {' · '.join(v['credit'])}" if v["credit"] else ""
                parts.append(f"기말 {v['date']} 전표 {v['no']}: {side}{won(v['amount'])}원{other}")
        if c["lines"]:
            parts.append(f"적요 「{c['word']}」 당기 전표 {c['lines']}줄(차변 합계 {won(c['debit'])}원 · 대변 합계 {won(c['credit'])}원)")
        else:
            parts.append(NO_CLUE)
        if c["accounts"]:
            parts.append("당기 계정 " + " · ".join(f"{a['name']}({a['code']}) {won(a['amount'])}원" for a in c["accounts"]))
        return ". ".join(parts)


# ---------------------------------------------------------------- 계산

def _key(r: Row, seen: dict) -> str:
    base = f"전기 대조/{r.side}|{r.subject}|{r.amount}"
    n = seen[base] = seen.get(base, 0) + 1
    return base if n == 1 else f"{base}#{n}"


def compare(b: Books, s15: Paper, adjs: list[tuple], manual: list[Adj]) -> Compare:
    """대조 줄을 만들고 노란 칸을 읽는다. `adjs` 는 조서가 낸 (Paper, Adj), `manual` 은 15호 직접 조정 줄."""
    prior = b.prior or {}
    rows = []
    for i, a in enumerate(prior.get("adjustments") or [], start=1):
        subject, amount = str(a.get("subject") or "").strip(), _i(a.get("amount"))
        if not subject and not amount:
            continue
        note = str(a.get("note") or "").strip()
        rows.append(Row(i, str(a.get("side") or ""), subject, amount, str(a.get("disposition") or ""), note,
                        topic(f"{subject} {note}")))
    pc = Compare()
    if not rows:
        return pc
    pool = match(rows, [(p, a) for p, a in adjs] + [(None, a) for a in manual if a.amount])
    link_reserves(rows, prior.get("reserves") or [])
    pair_up(rows)
    flip(rows, pool)

    journal = Journal(b)
    seen: dict = {}
    for r in rows:
        r.key = _key(r, seen)
        if r.result != NO:
            continue
        r.clue = journal.clue(r)
        if r.role == "추인":
            r.default_amount = abs(r.reserve["closing"])
        elif r.clue["amount"]:
            r.default_amount = int(r.clue["amount"])
    auto = pair_defaults(rows)
    for r in rows:
        if r.result != NO:
            continue
        pick = s15.take(b, f"{r.key}/{APPLY}", "O" if r.idx in auto else "X", "pick")
        r.apply_amount = s15.take(b, f"{r.key}/{AMOUNT}", r.default_amount, "int")
        if pick not in PICKS:
            s15.confirm.append(f"전기 조정 대조 {r.side} {r.subject} 줄의 「{APPLY}」 값 「{pick}」 을 읽지 못해 넣지 않았습니다"
                               f"({' · '.join(PICKS)})")
            pick = "X"
        r.apply = pick
        if pick != "O" or r.side not in DISPOSITIONS:
            continue
        if r.apply_amount <= 0:
            s15.confirm.append(f"전기 조정 대조 {r.side} {r.subject} 줄은 「{APPLY}」 이 O 인데 「{AMOUNT}」 이 비어 있어 넣지 않았습니다")
            continue
        if r.disposition not in DISPOSITIONS[r.side]:
            s15.confirm.append(f"전기 조정 대조 {r.side} {r.subject} 줄의 전기 소득처분 「{r.disposition}」 을 읽지 못했습니다. 금액은 15호 "
                               f"합계에 넣었고 처분 코드는 비웠습니다({' · '.join(DISPOSITIONS[r.side])})")
        a = Adj(r.side, r.subject, r.apply_amount, r.disposition, KIND, r.note or f"전기와 같은 조정({r.subject})",
                f"{r.key}/{AMOUNT}", reserve_subject=(r.reserve or {}).get("subject") or r.subject)
        a.row = ROW_BASE + r.idx
        r.adj = a
        pc.applied.append(a)
    pc.rows = _ordered(rows)
    for n, r in enumerate(pc.rows, start=1):
        r.no = n
    pc.auto = sorted(auto)
    for unit in _units([r for r in pc.rows if r.idx in auto]):
        if all(r.adj is not None for r in unit):
            s15.confirm.append("전기 15호의 유보 짝 조정 " + " · ".join(f"{r.side} {r.subject} {r.apply_amount:,}원({r.role})" for r in unit)
                               + "을 당기에도 넣었습니다(전기 조정 대조 기본값 O). 설정 금액은 당기 기말 전표, 추인 금액은 전기 50호(을) 기말 "
                               "유보입니다. 당기 계상분이 당기에 확정됐으면 「당기 반영」 을 X 로 바꾸십시오")
    return pc


def pair_defaults(rows: list[Row]) -> set[int]:
    """「당기 반영」 기본값이 O 인 전기 줄(idx). 같은 과목의 유보 가산 · 차감 짝(당기분 설정 · 전기분 추인, 폐기물처분부담금처럼 매년
    미지급으로 계상하고 이듬해 지급할 때 추인하는 꼴)이 둘 다 당기에 없고, 전기 50호(을)에서 그 유보가 한 해에 모두 바뀌었고(설정 · 추인을
    가림), 설정 줄은 당기 기말 전표 한 건 금액을, 추인 줄은 전기 유보 기말을 기본 금액으로 찾았을 때만이다(10-21).
    손금은 확정된 사업연도의 것이라(법인세법 제40조 제1항) 기말 미지급 계상분은 가산하고 전기분은 지급한 해에 추인한다."""
    groups: dict[int, list[Row]] = {}
    for r in rows:
        if r.pair:
            groups.setdefault(r.pair, []).append(r)
    out = set()
    for unit in groups.values():
        if (len(unit) == 2 and all(r.result == NO and r.default_amount > 0 for r in unit)
                and {r.role for r in unit} == {"설정", "추인"}):
            out.update(r.idx for r in unit)
    return out


def _units(rows: list[Row]) -> list[list[Row]]:
    """짝은 두 줄을 한 묶음으로, 나머지는 한 줄씩. 전기 15호 차례를 지킨다."""
    out, done = [], set()
    for r in rows:
        if r.idx in done:
            continue
        unit = [x for x in rows if x.pair == r.pair] if r.pair else [r]
        done.update(x.idx for x in unit)
        out.append(unit)
    return out


def _ordered(rows: list[Row]) -> list[Row]:
    """당기에 없는 줄이 든 묶음을 금액 큰 차례로 앞에, 구분이 반대인 당기 줄과 이은 묶음을 그다음에, 나머지는 전기 15호 차례로."""
    units = _units(rows)
    missing = [u for u in units if any(r.result == NO for r in u)]
    others = [u for u in units if not any(r.result == NO for r in u)]
    flipped = [u for u in others if any(r.result == FLIP for r in u)]
    rest = [u for u in others if not any(r.result == FLIP for r in u)]
    missing.sort(key=lambda u: (-max(r.amount for r in u if r.result == NO), u[0].idx))
    return [r for u in missing + flipped + rest for r in u]


def reserve_rows(b: Books, now: list[dict]) -> list[dict]:
    """전기 기말 잔액이 있는 유보 과목마다 전기 증감과 당기 증감을 견준다."""
    cur = {str(r.get("subject") or ""): r for r in now}
    out = []
    for r in (b.prior or {}).get("reserves") or []:
        subject = str(r.get("subject") or "")
        p = {k: _i(r.get(k)) for k in ("opening", "decrease", "increase", "closing")}
        if not p["closing"]:
            continue
        c = cur.get(subject) or {}
        c = {k: _i(c.get(k)) for k in ("decrease", "increase", "closing")}
        prior_still = p["opening"] == p["closing"] and not p["decrease"] and not p["increase"]
        now_still = not c["decrease"] and not c["increase"]
        flag = ("전기와 당기 모두 증감 없음" if prior_still and now_still else
                "당기 증감 없음" if now_still else
                "전기 증감 없음(당기 증감 있음)" if prior_still else "")
        out.append({"subject": subject, "prior": p, "current": c, "flag": flag})
    return out


def report(b: Books, s15: Paper, pc: Compare, reserves_now: list[dict]) -> None:
    """values 에 대조 줄을 남기고 확인 줄 · 메모를 쓴다. `reserves_now` 는 당기 50호(을) 줄."""
    pc.reserves = reserve_rows(b, reserves_now)
    s15.values["prior_compare"] = [r.json() for r in pc.rows]
    s15.values["prior_reserves"] = pc.reserves
    s15.extra["prior_compare"] = pc
    if not pc.rows and not pc.reserves:
        return
    still = {x["subject"]: x for x in pc.reserves if x["flag"].startswith("당기 증감 없음")}
    units = [u for u in _units(pc.rows) if any(r.open for r in u)]
    units.sort(key=lambda u: (-max(r.amount for r in u if r.open), u[0].no))
    loud = [u for u in units if max(r.amount for r in u if r.open) >= CONFIRM_MIN][:CONFIRM_MAX]
    quiet = units[len(loud):]
    for u in loud:
        opened = [r for r in u if r.open]
        first = opened[0]
        if len(opened) == 2:
            head = (f"전기 15호 {first.subject} {' · '.join(f'{r.side} {won(r.amount)}원' for r in opened)}({first.disposition}) "
                    "짝이 당기 조정에 없습니다")
        else:
            head = f"전기 15호 {first.side} {first.subject} {won(first.amount)}원({first.disposition}) 줄이 당기 조정에 없습니다"
            mate = next((r for r in u if r is not first and r.current), None)
            if mate is not None:
                head += f"(짝인 {mate.side} 줄은 당기 {won(mate.current[1].amount)}원)"
        text = first.clue["text"]
        parts = [head, text if text.startswith(NO_CLUE) else f"당기 장부 {text}"]
        res = still.get((first.reserve or {}).get("subject"))
        if res:
            parts.append(f"전기 유보 {res['subject']} {won(res['prior']['closing'])}원은 당기 50호(을)에 증감 없이 남습니다")
        nos = " · ".join(str(r.no) for r in opened)
        parts.append(f"반영하려면 「전기 조정 대조」 표 {nos}번 줄 노란 칸 「{APPLY}」 을 O 로 바꾸고 「{AMOUNT}」 을 확인합니다")
        s15.confirm.append(". ".join(parts))
    if quiet:
        lines = [r for u in quiet for r in u if r.open]
        small = all(r.amount < CONFIRM_MIN for r in lines)
        why = f"줄마다 {won(CONFIRM_MIN)}원 미만" if small else f"{won(CONFIRM_MIN)}원 미만이거나 금액 차례가 {CONFIRM_MAX}줄 다음"
        s15.confirm.append(f"{'나머지 ' if loud else ''}전기 15호 {len(lines)}줄(합계 {won(sum(r.amount for r in lines))}원, {why})이 "
                           "당기 조정에 없습니다. 「전기 조정 대조」 표에서 확인하십시오")
    missing = [r for r in pc.rows if r.result == NO]
    flipped = [r for r in pc.rows if r.result == FLIP]
    if pc.rows:
        mid = f"{FLIP} {len(flipped)}줄 · " if flipped else ""
        s15.notes.append(f"전기 조정 대조: 전기 15호 {len(pc.rows)}줄 가운데 당기 있음 {len(pc.rows) - len(missing) - len(flipped)}줄 · "
                         f"{mid}당기 없음 {len(missing)}줄(회계사 반영 {len(pc.applied)}줄 · 검토 끝 "
                         f"{sum(1 for r in missing if r.state == '검토 끝')}줄). 과목은 채점과 같은 묶음 · 이름 정규화로 견줍니다")
    if flipped:
        names = " · ".join(f"{r.side} {r.subject} {won(r.amount)}원(당기 {r.current[1].side} {won(r.current[1].amount)}원)"
                           for r in flipped[:5])
        more = f" 외 {len(flipped) - 5}줄" if len(flipped) > 5 else ""
        s15.notes.append(f"전기 15호 {len(flipped)}줄은 같은 유보의 당기 줄이 있는데 가산 · 차감이 전기와 반대입니다(평가이익이 평가손실로 바뀐 해 "
                         f"등): {names}{more}. 확인 줄에는 넣지 않았습니다. 「전기 조정 대조」 표에 「{FLIP}」 로 보입니다")
    if pc.applied:
        add = sum(a.amount for a in pc.applied if a.side == "가산")
        ded = sum(a.amount for a in pc.applied if a.side == "차감")
        s15.notes.append(f"「전기 조정 대조」 에서 회계사가 넣은 조정 {len(pc.applied)}줄(가산 {won(add)}원 · 차감 {won(ded)}원)을 더했습니다. "
                         f"조정.json direct 에 kind 「{KIND}」 로 있습니다")
    for flag, text in (("당기 증감 없음", "전기에는 증감이 있었는데 당기 50호(을)에서 증감이 없는 유보"),
                       ("전기 증감 없음(당기 증감 있음)", "전기 중 증감이 없었는데 당기 조정이 움직인 유보"),
                       ("전기와 당기 모두 증감 없음", "전기 중에도 당기에도 증감이 없는 유보")):
        got = [x for x in pc.reserves if x["flag"] == flag]
        if got:
            names = " · ".join(f"{x['subject']} {won(x['prior']['closing'])}원" for x in got[:5])
            more = f" 외 {len(got) - 5}과목" if len(got) > 5 else ""
            s15.notes.append(f"{text} {len(got)}과목: {names}{more}")


# ---------------------------------------------------------------- 전기 유보 처리(조서가 함께 쓰는 판별)

def tri(n: int) -> str:
    """유보 금액 글. 음수는 △ 로 적는다."""
    return f"△ {abs(int(n)):,}" if n < 0 else f"{int(n):,}"


def _prior_rows(b: Books, subject: str) -> list[dict]:
    return [r for r in (b.prior or {}).get("reserves") or [] if str(r.get("subject") or "") == subject]


def prior_reserve(b: Books, subject: str) -> dict | None:
    """전기 50호(을) 그 과목 줄 {subject, opening, decrease, increase, closing, known}. 같은 과목이 여럿이면 더한다.
    `known` 은 기초를 모두 읽었는지다."""
    rows = _prior_rows(b, subject)
    if not rows:
        return None
    out = {"subject": subject, "known": all(r.get("opening") is not None for r in rows)}
    for k in ("opening", "decrease", "increase", "closing"):
        out[k] = sum(_i(r.get(k)) for r in rows)
    return out


def prior_text(x: dict | None) -> str:
    if not x:
        return "전기 50호(을)에 줄 없음"
    return (f"전기 50호(을) 기초 {tri(x['opening'])}원 · 감소 {tri(x['decrease'])}원 · 증가 {tri(x['increase'])}원 · "
            f"기말 {tri(x['closing'])}원")


def reserve_still(b: Books, subject: str, related=None) -> bool:
    """전기 신고서가 그 유보를 한 해 동안 그대로 두었는가. 전기 50호(을) 그 과목 줄(기말 잔액이 있는 줄)이 모두 기초 = 기말 ·
    감소 0 · 증가 0 이고, 전기 15호에 그 과목 줄이 없을 때 참이다. 전기 15호 줄은 유보 처분이고 과목 이름(괄호를 뺀 이름 포함)이
    같은 줄, 그리고 `related(줄)` 이 참인 줄을 그 과목 줄로 본다(조서마다 미수이자 · 연차 같은 낱말로 가린다).
    매년 추인하고 다시 설정하는 유보가 아니라는 신호다. 대손충당금 조서의 `prior_static` 과 같은 판별이다."""
    rows = [r for r in _prior_rows(b, subject) if _i(r.get("closing"))]
    if not rows:
        return False
    for r in rows:
        if r.get("opening") is None or _i(r.get("opening")) != _i(r.get("closing")):
            return False
        if _i(r.get("decrease")) or _i(r.get("increase")):
            return False
    names = {norm_subject(subject), norm_subject(PAREN.sub("", subject))} - {""}
    for a in (b.prior or {}).get("adjustments") or []:
        subj = str(a.get("subject") or "")
        if str(a.get("disposition") or "") == "유보" and {norm_subject(subj), norm_subject(PAREN.sub("", subj))} & names:
            return False
        if related is not None and related(a):
            return False
    return True


def reserve_piling(b: Books, subject: str) -> bool:
    """전기 신고서가 그 유보를 추인하지 않고 늘리기만 했는가(기초 잔액이 있고 감소 0 · 증가 있음)."""
    x = prior_reserve(b, subject)
    return bool(x and x["known"] and x["opening"] and not x["decrease"] and x["increase"])


@dataclass
class Carry:
    """전기 유보 한 과목을 당기에 어떻게 넘기는지(조서 2 · 3 · 14 · 15 가 함께 쓴다)."""
    subject: str
    closing: int                   # 전기 기말(= 당기 기초)
    prior: dict | None             # 전기 50호(을) 줄
    still: bool                    # 전기 중 증감 없음
    piling: bool                   # 전기에 추인 없이 늘리기만 함
    shown: str                     # 노란 칸 「전기 유보 처리」 에 적힌 글
    mode: str                      # 계산에 쓴 처리(그대로 · 추인)
    asked: int                     # 노란 칸 추인액
    amount: int                    # 반영한 추인액(처리가 그대로면 0)
    picked: bool                   # 회계사가 처리 칸을 기본값과 다르게 고름
    key_mode: str
    key_amount: str
    key_applied: str

    @property
    def keep(self) -> bool:
        return self.mode == KEEP

    def json(self) -> dict:
        return {"subject": self.subject, "기초유보": self.closing, "전기": self.prior, "전기유보증감없음": self.still,
                "전기추인없이증가": self.piling, "처리": self.mode, "추인액": self.asked, "반영": self.amount,
                "keys": {"mode": self.key_mode, "amount": self.key_amount}}


def carry(p: Paper, b: Books, subject: str, closing: int, amount_key: str, related=None) -> Carry:
    """노란 칸 둘을 읽는다: 「전기 유보 처리/<과목>」(그대로 · 추인)와 추인액(`amount_key`, 기본 전기 유보 전액).
    처리 기본값은 「추인」 이고 전기 중 증감이 없던 유보만 「그대로」 다. 읽지 못한 값은 「추인」 으로 계산하고 확인 줄을 낸다.
    values 에 처리 글 · 추인액 · 반영액(`추인 반영/<과목>`)을 넣는다."""
    still = reserve_still(b, subject, related)
    key_mode, key_applied = f"{MODE}/{subject}", f"추인 반영/{subject}"
    shown = p.take(b, key_mode, KEEP if still else REVERSE)
    mode = shown
    if shown not in (KEEP, REVERSE):
        p.confirm.append(f"노란 칸 「{key_mode}」 값 「{shown}」 을 읽지 못해 「{REVERSE}」 으로 계산했습니다({KEEP} · {REVERSE})")
        mode = REVERSE
    asked = p.take(b, amount_key, abs(closing), "int")
    amount = 0 if mode == KEEP else asked
    p.values[key_mode], p.values[amount_key], p.values[key_applied] = shown, asked, amount
    return Carry(subject, closing, prior_reserve(b, subject), still, reserve_piling(b, subject), shown, mode, asked, amount,
                 key_mode in p.overridden, key_mode, amount_key, key_applied)


def carry_notes(p: Paper, c: Carry, *, law: str, if_reverse: str) -> None:
    """처리에 따른 확인 줄 · 메모. `law` 는 추인 시기의 근거 글, `if_reverse` 는 추인을 골랐을 때의 조정 글이다."""
    held = (f"전기 신고서는 {c.subject} 유보 {tri(c.closing)}원을 한 해 동안 그대로 두었습니다(전기 50호(을) 기초 = 기말 · 감소 0 · "
            "증가 0, 전기 15호에 그 과목 줄 없음)")
    if c.still and c.keep:
        p.confirm.append(f"{held}. 매년 추인하고 다시 설정하는 유보가 아니어서 당기에도 추인하지 않고 유보로 두었습니다. {law} "
                         f"{if_reverse} 노란 칸 「{c.key_mode}」 에서 고르십시오({KEEP} · {REVERSE})")
    elif c.still:
        p.notes.append(f"{held}. 노란 칸 「{c.key_mode}」 가 「{REVERSE}」 이라 {won(c.amount)}원을 추인했습니다")
    elif c.keep:
        p.notes.append(f"노란 칸 「{c.key_mode}」 가 「{KEEP}」 라 전기 {c.subject} 유보 {tri(c.closing)}원을 추인하지 않았습니다"
                       f"(「{REVERSE}」 으로 두면 {won(c.asked)}원 추인)")
    if c.piling and not c.keep and c.key_amount not in p.overridden:
        p.confirm.append(f"전기 신고서는 {c.subject} 유보를 추인하지 않고 늘리기만 했습니다({prior_text(c.prior)}). 매년 추인하고 다시 "
                         f"설정하는 유보가 아닐 수 있습니다. 엔진은 앞선 기본값대로 {won(c.amount)}원을 추인했습니다. {law} "
                         f"노란 칸 「{c.key_mode}」 를 확인하십시오({KEEP} · {REVERSE})")
    if not c.keep and c.amount != abs(c.closing):
        p.notes.append(f"{c.subject} 전기 유보 {won(abs(c.closing))}원 중 {won(c.amount)}원만 추인합니다(회계사 값). 나머지는 50호(을)에 남습니다")


def carry_head(cs: list[Carry]) -> str:
    """조서 확인 줄 「전기 유보 대조」 의 앞머리: 과목마다 전기 유보 기말과 당기 추인액."""
    return "전기 유보 대조: " + " · ".join(f"{c.subject} 전기 기말 {tri(c.closing)}원 · 당기 추인 {won(c.amount)}원" for c in cs)


def carry_rows(r, p: Paper, cs: list[Carry], what: str, note: str = "") -> None:
    """조서 시트 계산 줄(`sheet.Rows`)에 과목마다 줄 셋을 쓴다: 노란 칸 「전기 유보 처리」, 노란 칸 추인액, 반영액 수식."""
    for c in cs:
        r.put(c.key_mode, f"전기 50호(을) {c.subject} 유보 처리({KEEP} · {REVERSE})", p.inputs[c.key_mode], kind="input",
              note="전기 중 증감이 없던 유보는 기본값이 「그대로」 입니다")
        r.put(c.key_amount, f"전기 50호(을) {c.subject} 유보 추인액({what})", p.inputs[c.key_amount], kind="input", input_kind="int",
              note=note)
        r.put(c.key_applied, f"{c.subject} 당기 추인 반영액(처리가 「{KEEP}」 면 0)",
              f'=IF({r.g(c.key_mode)}="{KEEP}",0,{r.g(c.key_amount)})')


# ---------------------------------------------------------------- 엑셀

COLS =["번호", "구분", "짝", "과목(전기)", "소득처분", "조정내용(전기)", "전기 금액", "당기 대응", "당기 조정 금액", "당기 줄",
        "당기 장부 단서", APPLY, AMOUNT, "반영 금액"]
EXTRA_WIDTHS = {"I": 16, "J": 30, "K": 70, "L": 10, "M": 16, "N": 16}


def write_applied(bk, s, row: int, res) -> int:
    """15호 본표에 대조 표에서 넣은 조정 줄을 쓴다. 금액 칸은 `write` 가 대조 표의 「반영 금액」 을 부르는 수식으로 채운다."""
    pc: Compare | None = res.summary15.extra.get("prior_compare")
    for r in pc.rows if pc else []:
        if r.adj is None:
            continue
        a = r.adj
        s.put(row, 1, a.side)
        s.put(row, 2, a.code)
        s.put(row, 4, a.subject)
        s.put(row, 5, a.disposition)
        s.put(row, 6, a.note)
        s.put(row, 7, a.amount, kind="link", money=True)
        s.put(row, 8, f"{KIND} {r.no}")
        bk.reg(PID, f"direct:{a.row}", s.addr(row, 7))
        r.main_row = row
        row += 1
    return row


def write(bk, s, row: int, res) -> int:
    """15호 시트 아래에 「전기 조정 대조」 표와 「전기 유보 대조」 표를 쓴다. 다음 행을 돌려준다."""
    p: Paper = res.summary15
    pc: Compare | None = p.extra.get("prior_compare")
    if pc is None or (not pc.rows and not pc.reserves):
        return row
    for letter, w in EXTRA_WIDTHS.items():
        s.ws.column_dimensions[letter].width = w
    if pc.rows:
        row = s.section(row, "전기 조정 대조")
        X.note(s.ws, row, f"전기 15호 줄마다 당기 조정에 같은 과목 줄이 있는지 견줍니다. 노란 칸 「{APPLY}」: O 는 전기와 같은 구분 · "
                          f"소득처분으로 당기 15호에 넣음, X 는 넣지 않음(기본), N 은 검토했고 당기에는 없는 조정. 「{AMOUNT}」 을 넣고 "
                          "ctax wp 를 다시 돌리면 15호 · 3호 · 50호(을)에 반영됩니다")
        row += 1
        if any(r.result == FLIP for r in pc.rows):
            X.note(s.ws, row, f"「{FLIP}」 는 같은 유보를 같은 쪽(증가 · 감소)으로 움직이는 당기 줄이 있는데 가산 · 차감이 전기와 반대인 "
                              "줄입니다(평가이익이 평가손실로 바뀐 해 등). 노란 칸이 없고 확인 줄에도 넣지 않습니다")
            row += 1
        X.header(s.ws, row, COLS)
        row += 1
        for r in pc.rows:
            s.put(row, 1, r.no)
            s.put(row, 2, r.side)
            s.put(row, 3, r.pair)
            s.put(row, 4, r.subject)
            s.put(row, 5, r.disposition)
            s.put(row, 6, r.note)
            s.put(row, 7, r.amount, money=True)
            s.put(row, 8, r.result + (f"({r.state})" if r.state else "") + (f" · {r.role}" if r.role and r.result == NO else ""))
            if r.current:
                paper, a = r.current
                src = (bk.cells.get(paper.id, {}).get(f"adj:{a.kind}") if paper is not None
                       else bk.cells.get(PID, {}).get(f"direct:{getattr(a, 'row', 0)}"))
                s.put(row, 9, f"={src}" if src else a.amount, kind="link" if src else "body", money=True)
                side = f"당기 {a.side} " if r.result == FLIP else ""
                s.put(row, 10, f"{paper.sheet if paper is not None else '직접 조정'} · {side}{a.subject} · {a.disposition} · {r.how}")
            else:
                s.put(row, 11, r.clue["text"])
                s.inp(row, 12, r.apply, pid=PID, key=f"{r.key}/{APPLY}", default=p.defaults.get(f"{r.key}/{APPLY}", "X"), kind="pick")
                s.inp(row, 13, r.apply_amount or None, pid=PID, key=f"{r.key}/{AMOUNT}",
                      default=p.defaults.get(f"{r.key}/{AMOUNT}") or None, kind="int", money=True)
                s.put(row, 14, f'=IF(L{row}="O",M{row},0)', money=True)
                if r.main_row:
                    s.put(r.main_row, 7, f"=N{row}", kind="link", money=True)
            row += 1
        row += 1
    if pc.reserves:
        row = s.section(row, "전기 유보 대조")
        X.note(s.ws, row, "전기 50호(을) 기말 잔액이 있는 과목입니다. 당기 증감은 조서의 유보 조정과 위 표에서 넣은 조정입니다")
        row += 1
        for col, label in ((1, "번호"), (4, "과목"), (5, "전기 기초"), (6, "표시"), (7, "전기 감소"), (8, "전기 증가"), (9, "전기 기말"),
                           (10, "당기 증감"), (13, "당기 기말")):
            X.header(s.ws, row, [label], col=col)
        row += 1
        for n, x in enumerate(pc.reserves, start=1):
            s.put(row, 1, n)
            s.put(row, 4, x["subject"])
            s.put(row, 5, x["prior"]["opening"], money=True)
            s.put(row, 6, x["flag"])
            s.put(row, 7, x["prior"]["decrease"], money=True)
            s.put(row, 8, x["prior"]["increase"], money=True)
            s.put(row, 9, x["prior"]["closing"], money=True)
            s.put(row, 10, f"감소 {won(x['current']['decrease'])} · 증가 {won(x['current']['increase'])}")
            s.put(row, 13, x["current"]["closing"], money=True)
            row += 1
        row += 1
    return row


__all__ = ["Compare", "Row", "compare", "report", "words", "write", "write_applied", "KIND", "YES", "NO", "FLIP", "ROW_BASE",
           "CONFIRM_MIN", "CONFIRM_MAX", "APPLY", "AMOUNT", "UP", "DOWN", "move_of", "flip",
           "MODE", "KEEP", "REVERSE", "Carry", "carry", "carry_notes", "carry_head", "carry_rows", "reserve_still",
           "reserve_piling", "prior_reserve", "prior_text", "tri"]
