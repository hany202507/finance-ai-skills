"""이익잉여금처분계산서(결손금처리계산서) 규칙(12단계, 2026-10-19).

처분계산서는 본표 절에 따로 두는 회사도 있지만, 공개 원문 309건과 정정공시 짝에서는 이익잉여금 주석 안의 표로 둔 보고서가
훨씬 많았다(처분계산서 표 290개 가운데 주석 안 249). 그래서 본표 절에 없으면 주석 안 표를 줄 이름으로 찾는다.
처분계산서 표는 「미처분이익잉여금 · 미처리결손금」 으로 시작하는 줄과 「차기이월」 줄이 함께 있는 표다(이익잉여금 구성 표에는
차기이월 줄이 없다).

거는 검증(당기 · 전기 열마다):
- 당기순이익 = 손익계산서 당기순이익(일반기업회계기준 2.88 이익잉여금처분계산서, 손실만 적는 줄의 양수는 손실 금액)
- 미처분이익잉여금(미처리결손금) = 재무상태표 같은 줄(재무상태표가 이익잉여금을 나눠 적었을 때)
- 당기 열 전기이월 = 전기 열 차기이월(같은 표 안)
- 처분액 ≤ 처분 전 이익잉여금(미처분이익잉여금 + 임의적립금 등의 이입액). 처분 뒤 차기이월이 음수가 되면 안 된다
- 이익준비금 적립 ≥ MIN(금전배당 × 10%, MAX(0, 자본금 × 1/2 - 이익준비금 잔액))(상법 제458조)

정정공시 짝 셋(01661932 · 00411288 · 00117692)에서 정정 전 판이 틀렸던 곳이다. 01661932 · 00411288 은 배당을 하면서
이익준비금 적립을 빠뜨렸고, 00117692 는 시설투자적립금을 미처분이익잉여금보다 많이 적립해 차기이월이 음수였다.
"""
from __future__ import annotations

import re

from .base import norm
from .dsd_grid import Doc, Table

_PRE = re.compile(r"^(?:[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+|[IVX]+(?=[.\s])|\d+|[가-하](?=[.)])|\(\d+\)|\([가-하]\)|[①-⑳]|-)\s*[.)]?\s*")
_NOTE_MARK = re.compile(r"\((?:\*|주\s*\d*|주석\s*[\d,\s]+)\)|\(\*\d*\)")


def key(label) -> str:
    """줄 이름에서 번호(Ⅰ. 1. 가. (1) -)와 공백, 각주 표시를 뗀다."""
    s = _NOTE_MARK.sub("", norm(label))
    for _ in range(3):
        t = _PRE.sub("", s)
        if t == s:
            break
        s = t
    return s


_HEAD = ("미처분이익잉여금", "미처리결손금", "미처리이익잉여금")
_NI = re.compile(r"^당기순(이익|손실|손익|이손실)")


def _labels(t: Table) -> list[str]:
    return t.labels or [r[0] for r in t.rows]


def is_appropriation(t: Table) -> bool:
    ks = [key(x) for x in _labels(t)]
    return any(k.startswith(_HEAD) for k in ks) and any(k.startswith("차기이월") for k in ks)


def find(doc: Doc) -> Table | None:
    """처분계산서 표. 본표 절의 처분계산서가 먼저고, 없으면 주석 안 표."""
    for p in doc.parts:
        if p.key == "이익잉여금처분계산서":
            for x in p.items:
                if x[0] == "t" and is_appropriation(x[1]):
                    return x[1]
    for p in doc.parts:
        if not p.key.startswith("주석"):
            continue
        for x in p.items:
            if x[0] == "t" and x[1].kind != "문장" and is_appropriation(x[1]):
                return x[1]
    return None


def _isnum(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def period_cols(t: Table, period: str) -> list[int]:
    """그 기간의 열. 기간마다 내역 · 합계 두 열을 둔 본표는 두 열이 다 그 기간이다."""
    from .dsd_links import period_col, term_of

    key_ = "당" if period == "당기" else "전"
    hits = [j for j, h in enumerate(t.header) if j and key_ in h]
    if hits and len(hits) < len(t.header) - 1:
        other = [j for j, h in enumerate(t.header) if j and ("전" if period == "당기" else "당") in h]
        return [j for j in hits if j not in other] or hits[:1]
    terms = {j: term_of(h) for j, h in enumerate(t.header) if j and term_of(h) is not None}
    kinds = sorted(set(terms.values()), reverse=True)
    if len(kinds) >= 2:
        want = kinds[0] if period == "당기" else kinds[1]
        return [j for j, k in terms.items() if k == want]
    j = period_col(t, period)
    return [j] if j is not None else []


def _cell(t: Table, r: int, cols: list[int]) -> int | None:
    """그 줄에서 숫자가 있는 그 기간의 열. 내역 · 합계 두 열이면 0 이 아닌 쪽, 둘 다면 뒤쪽 합계(DART 01591509 는 내역 열에
    당기순손실, 합계 열에 「-」 를 적었다)."""
    got = [j for j in cols if _isnum(t.nums[r][j])]
    live = [j for j in got if t.nums[r][j]]
    return (live or got)[-1] if got else None


class Rows:
    """처분계산서 줄의 역할."""

    def __init__(self, t: Table):
        ks = [key(x) for x in _labels(t)]
        self.keys = ks
        first = lambda pred, start=0, end=None: next((i for i in range(start, len(ks) if end is None else end) if pred(ks[i])), None)  # noqa: E731
        self.head = first(lambda k: k.startswith(_HEAD))
        self.carry_in = first(lambda k: k.startswith("전기이월"))
        self.ni = first(lambda k: bool(_NI.match(k)))
        self.transfer = first(lambda k: bool(re.match(r"^(임의적립금등의|적립금등의|임의적립금|법정적립금|이익잉여금)이입액", k)))
        self.dispose = first(lambda k: bool(re.match(r"^(이익잉여금처분액|잉여금처분액|처분액|결손금처리액|이월결손금처리액)", k)))
        self.carry_out = first(lambda k: k.startswith("차기이월"))
        end = self.dispose if self.dispose is not None else self.carry_out
        self.interim = first(lambda k: "중간배당" in k, 0, end)
        lo = self.dispose if self.dispose is not None else len(ks)
        hi = self.carry_out if self.carry_out is not None and self.carry_out > lo else len(ks)
        self.reserve = first(lambda k: k.startswith("이익준비금"), lo, hi)
        self.stock_div = [i for i in range(lo, hi) if "주식배당" in ks[i]]
        div = [i for i in range(lo, hi) if re.match(r"^(배당금|현금배당|연차배당|보통주현금배당|우선주현금배당|보통주배당|우선주배당)", ks[i])]
        if div and ks[div[0]].startswith(("보통주", "우선주")):     # 종류마다 따로 적은 배당은 더한다
            self.dividends = [i for i in div if ks[i].startswith(("보통주", "우선주"))]
        else:
            self.dividends = div[:1]                    # 「배당금」 아래 「가. 현금배당」 처럼 같은 금액을 두 단계로 적은 표는 첫 줄만
        self.deficit = self.head is not None and "결손금" in ks[self.head]      # 「미처리결손금」 「미처분이익잉여금(미처리결손금)」


def _bs_row(t: Table, names: tuple) -> int | None:
    ks = [key(x) for x in _labels(t)]
    return next((i for i, k in enumerate(ks) if re.sub(r"\(.*\)$", "", k) in names), None)


def _same_sign(a, b) -> int:
    """두 금액의 크기만 견주는 배수. 결손금처리계산서는 회사마다 방향이 섞여 있다. 첫 줄은 결손을 양수로 적고 아래 줄은 이익 방향으로
    적은 표(DART 00960021 · 01910607), 줄마다 결손 방향으로 적은 표(공개 원문 006 · 126), 이름은 「미처리결손금」 인데 금액은 잉여인
    기간(공개 원문 053 전기)이 다 있었다. 그래서 줄 이름이나 첫 줄 부호로 방향을 정하지 않고 크기만 견준다. 이 표의 합은 엔진 합계 구조가 본다."""
    return -1 if _isnum(a) and _isnum(b) and (a < 0) != (b < 0) and a and b else 1


def checks(doc: Doc) -> list:
    from .dsd_links import Check, _kind, find_row, income_sign, period_col

    t = find(doc)
    if t is None:
        return []
    rows = Rows(t)
    labels = _labels(t)
    out = []
    from .dsd_kicpa import consolidated

    group = consolidated(doc)                       # 연결 보고서 주석의 처분계산서는 지배기업 것이라 연결 재무제표와 견주지 않는다(같은 표 안의 이월 · 처분 한도만)
    pl = None if group else doc.table("손익계산서")
    bs = None if group else doc.table("재무상태표")
    name = f"{t.id} 처분계산서" if t.id.startswith("주석") else t.id
    cols = {p: period_cols(t, p) for p in ("당기", "전기")}
    if not cols["당기"] or not cols["전기"] or set(cols["당기"]) & set(cols["전기"]):
        cols = {p: v for p, v in cols.items() if v and not (set(cols["당기"]) & set(cols["전기"]))}
    for period, pc in cols.items():
        # 1. 당기순이익 = 손익계산서 당기순이익
        if rows.ni is not None and pl is not None:
            c = _cell(t, rows.ni, pc)
            j = period_col(pl, period)
            i = next((x for x in (find_row(pl, n) for n in NI_NAMES) if x is not None), None)
            if c is not None and j is not None and i is not None and _isnum(pl.nums[i][j]):
                if rows.deficit:                         # 결손금처리계산서는 크기만 견준다(_same_sign)
                    s = _same_sign(t.nums[rows.ni][c], pl.nums[i][j])
                else:
                    s = income_sign(labels[rows.ni], t.nums[rows.ni][c]) * income_sign(_labels(pl)[i], pl.nums[i][j])
                out.append(Check(f"처분계산서-당기순이익|{period}", _kind(doc, t.id, [pl.id]), "레퍼", t.id, rows.ni, c, [(pl.id, i, j, s)], None,
                                 f"손익계산서 {_labels(pl)[i]}", "규칙",
                                 "처분계산서 당기순이익 = 손익계산서 당기순이익(일반기업회계기준 2.88). 「당기순손실」 처럼 손실만 적는 줄의 양수는 손실 금액으로 읽는다. "
                                 "결손금처리계산서는 회사마다 적는 방향이 달라 크기만 견준다"))
        # 2. 미처분이익잉여금(미처리결손금) = 재무상태표 같은 줄
        if rows.head is not None and bs is not None:
            c = _cell(t, rows.head, pc)
            j = period_col(bs, period)
            i = _bs_row(bs, ("미처분이익잉여금", "미처리결손금", "미처분이익잉여금(미처리결손금)", "미처리결손금(미처분이익잉여금)"))
            if c is not None and j is not None and i is not None and _isnum(bs.nums[i][j]):
                if rows.deficit or "결손금" in key(_labels(bs)[i]):
                    s = _same_sign(t.nums[rows.head][c], bs.nums[i][j])
                else:
                    s = 1
                out.append(Check(f"처분계산서-미처분이익잉여금|{period}", _kind(doc, t.id, [bs.id]), "레퍼", t.id, rows.head, c, [(bs.id, i, j, s)], None,
                                 f"재무상태표 {_labels(bs)[i]}", "규칙",
                                 "처분계산서 미처분이익잉여금(미처리결손금) = 재무상태표 같은 과목(처분 전 금액). 결손금은 크기만 견준다"))
        # 4. 처분액 ≤ 처분 전 이익잉여금
        if rows.dispose is not None and rows.head is not None and not rows.deficit:
            c = _cell(t, rows.dispose, pc)
            h = _cell(t, rows.head, pc)
            if c is not None and h is not None and t.nums[rows.dispose][c] > 0:
                terms = [(t.id, rows.head, h, 1)]
                if rows.transfer is not None and rows.transfer < rows.dispose:
                    k = _cell(t, rows.transfer, pc)
                    if k is not None:
                        terms.append((t.id, rows.transfer, k, 1))
                out.append(Check(f"처분계산서-처분한도|{period}", "주석 간" if t.id.startswith("주석") else "재무제표 간", "레퍼", t.id, rows.dispose, c, terms, None,
                                 " + ".join(labels[x[1]] for x in terms), "규칙",
                                 "이익잉여금 처분액은 처분 전 이익잉여금(미처분이익잉여금 + 임의적립금 등의 이입액)을 넘을 수 없다. 넘으면 차기이월미처분이익잉여금이 음수가 된다",
                                 cmp="le"))
        # 5. 이익준비금 적립(상법 제458조)
        got = _reserve_check(doc, t, rows, period, pc, bs, name)
        if got is not None:
            out.append(got)
    # 3. 당기 열 전기이월 = 전기 열 차기이월
    if rows.carry_in is not None and rows.carry_out is not None and "당기" in cols and "전기" in cols:
        a, b = _cell(t, rows.carry_in, cols["당기"]), _cell(t, rows.carry_out, cols["전기"])
        if a is not None and b is not None:
            g = _same_sign(t.nums[rows.carry_in][a], t.nums[rows.carry_out][b]) if rows.deficit else 1
            out.append(Check("처분계산서-이월", "주석 간" if t.id.startswith("주석") else "재무제표 간", "레퍼", t.id, rows.carry_in, a, [(t.id, rows.carry_out, b, g)], None,
                             f"{t.id} 전기 {labels[rows.carry_out]}", "규칙", "당기 처분계산서의 전기이월 = 전기 처분계산서의 차기이월. 결손금처리계산서는 크기만 견준다"))
    return out


NI_NAMES = ("당기순이익", "당기순이익(손실)", "당기순손실", "당기순손익", "당기순손실(이익)", "연결당기순이익")


def _reserve_balance(doc: Doc, bs: Table | None, period: str, t: Table, rows: Rows, pc: list[int]):
    """이익준비금 잔액: (표 id, 줄, 열) 이거나 0(재무상태표가 이익잉여금을 미처분이익잉여금 하나로만 적음). 모르면 None."""
    from .dsd_links import period_col

    if bs is None:
        return None
    j = period_col(bs, period)
    if j is None:
        return None
    i = _bs_row(bs, ("이익준비금",)) or _bs_row(bs, ("법정적립금",))
    if i is not None and _isnum(bs.nums[i][j]):
        return (bs.id, i, j)
    tot, und = _bs_row(bs, ("이익잉여금", "이익잉여금(결손금)", "이익잉여금(미처리결손금)")), _bs_row(bs, ("미처분이익잉여금",))
    if tot is not None and und is not None and und == tot + 1 and _isnum(bs.nums[tot][j]) and bs.nums[tot][j] == bs.nums[und][j]:
        nxt = und + 1 < len(bs.rows) and key(_labels(bs)[und + 1]).startswith(("이익준비금", "법정적립금", "임의적립금"))
        if not nxt:
            return 0                                     # 이익잉여금 = 미처분이익잉여금 한 줄. 이익준비금이 없다
    # 이익잉여금 주석의 구성 표(이익준비금 줄과 미처분이익잉여금 줄이 함께 있고 미처분이익잉여금이 처분계산서와 같은 표)
    h = _cell(t, rows.head, pc) if rows.head is not None else None
    if h is None:
        return None
    for q in doc.tables():
        if q is t or q.kind == "문장" or is_appropriation(q):
            continue
        ks = [key(x) for x in _labels(q)]
        ri = next((x for x, k in enumerate(ks) if k == "이익준비금"), None)
        ui = next((x for x, k in enumerate(ks) if k == "미처분이익잉여금"), None)
        if ri is None or ui is None:
            continue
        qj = period_col(q, period)
        if qj is None or not _isnum(q.nums[ri][qj]) or not _isnum(q.nums[ui][qj]):
            continue
        if abs(q.nums[ui][qj] * q.unit - t.nums[rows.head][h] * t.unit) <= max(q.unit, t.unit):
            return (q.id, ri, qj)
    return None


def _reserve_check(doc: Doc, t: Table, rows: Rows, period: str, pc: list[int], bs: Table | None, name: str):
    from .dsd_links import Check, period_col

    if rows.deficit or rows.stock_div and any(_isnum(t.nums[i][j]) and t.nums[i][j] for i in rows.stock_div for j in pc):
        return None
    divs = [(i, _cell(t, i, pc)) for i in rows.dividends]
    divs = [(i, j) for i, j in divs if j is not None]
    terms, parts = [], []
    for i, j in divs:
        terms.append((t.id, i, j, 1))
        parts.append(f"ABS({{{len(terms) - 1}}})")
    if rows.interim is not None and (j := _cell(t, rows.interim, pc)) is not None:
        terms.append((t.id, rows.interim, j, 1))
        parts.append(f"ABS({{{len(terms) - 1}}})")
    paid = sum(abs(t.nums[x[1]][x[2]]) for x in terms)
    if not terms or paid <= 0 or bs is None:
        return None
    cj = period_col(bs, period)
    ci = _bs_row(bs, ("자본금",))
    if cj is None or ci is None or not _isnum(bs.nums[ci][cj]) or bs.nums[ci][cj] <= 0:
        return None
    bal = _reserve_balance(doc, bs, period, t, rows, pc)
    if bal is None:
        return None
    terms.append((bs.id, ci, cj, 1))
    cap = f"{{{len(terms) - 1}}}"
    if bal == 0:
        res = "0"
    else:
        terms.append((*bal, 1))
        res = f"{{{len(terms) - 1}}}"
    expr = f"MIN(0.1*({'+'.join(parts)}),MAX(0,{cap}/2-{res}))"
    zero = rows.reserve is None or _cell(t, rows.reserve, pc) is None
    if zero:
        anchor = rows.dispose if rows.dispose is not None else rows.carry_out
        if anchor is None:
            return None
        c = _cell(t, anchor, pc) or (pc[-1] if pc else None)
        r = anchor
    else:
        r, c = rows.reserve, _cell(t, rows.reserve, pc)
    if c is None:
        return None
    labels = _labels(t)
    left = "이익준비금 적립(처분계산서에 없음)" if zero else labels[r]
    label = (f"{left} ≥ MIN(금전배당 {' + '.join(labels[x[1]] for x in terms if x[0] == t.id)} × 10%, "
             f"자본금 × 1/2 - {'이익준비금 0(재무상태표에 이익준비금 없음)' if bal == 0 else ('이익준비금 ' + doc_label(doc, bal))})")
    lu = t.unit_at(r, c)                            # 천원 재무상태표의 자본금 · 이익준비금은 반올림된 금액이라 그 폭을 받는다(한 상장사 2025: 적립 246,676,023원 · 최소 246,676,500원)
    spread = sum(0.5 * doc.table(x[0]).unit_at(x[1], x[2]) for x in terms if doc.table(x[0]).unit_at(x[1], x[2]) > lu) / lu
    return Check(f"처분계산서-이익준비금|{period}", "계산", "레퍼", t.id, r, c, terms, None, label, "규칙",
                 "상법 제458조: 자본금의 1/2 이 될 때까지 매 결산기 이익배당액(금전배당, 중간배당 포함)의 1/10 이상을 이익준비금으로 적립한다. "
                 "적립할 금액은 MIN(금전배당 × 10%, 자본금 × 1/2 - 기말 이익준비금)이다",
                 tol=max(1, spread), expr=expr, cmp="ge", zero_left=zero)


def doc_label(doc: Doc, cell) -> str:
    tid, i, _ = cell
    q = doc.table(tid)
    return f"{tid} {_labels(q)[i]}" if q is not None else tid
