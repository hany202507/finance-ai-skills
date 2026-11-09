"""DSD 푸팅: 차이 설명 후보(2026-10-18, 11단계).

FALSE · 확인 검증마다 차이를 보고서의 숫자로 설명할 수 있는 후보를 찾는다. 회계사가 차이를 받으면 먼저 하는 일이다.
한 상장사 2026 반기에서 판정 두 건이 틀렸는데, 둘 다 이 후보가 있었으면 지울 수 있었다
(주석 6 전기말 「단기금융상품」 의 차이 15,300,518 = 재무상태표 장기금융상품, 주석 30 전환사채 기타 변동의 차이 1,787,707 = 상환 21,000,000 - 결제 19,212,293).

후보는 판정을 지워 보는 데만 쓰고 연결을 만들지 않는다(금액이 같은 칸을 잇는 방식은 4단계에 반려됐다).
어느 쪽이 맞는지도 정하지 않는다. 판정과 독립 검증이 후보마다 「해당 없음」 이나 「이것으로 설명됨」 을 적는다.

후보 종류
  단위        한쪽이 다른 쪽의 1,000배 · 1,000,000배
  부호        두 금액의 크기가 같고 부호가 반대, 또는 한 항의 부호를 바꾸면 맞음(차이 = 그 항의 두 배)
  부호 표시   부호만 다른 차이에서 그 칸 줄의 부호가 재무제표의 기간마다 다름(금액은 맞고 부호 표시 관례가 다른 것일 수 있다)
  자리        한 칸의 이웃한 두 자리를 바꾸면 맞음(차이가 9 의 배수), 자릿수를 하나 밀면 맞음, 차이가 한 자리만 다른 꼴
  기간 열     한 칸 대신 같은 줄 다른 열의 금액을 넣으면 맞음
  이웃 줄     한 칸 대신 위 · 아래 두 줄 안의 금액을 넣으면 맞음
  같은 칸     차이와 같은 금액의 칸(이 검증의 표, 같은 주석, 재무제표 순), 이 검증의 표와 같은 주석에서 두 칸의 합 · 차
  작년 이름   작년 보고서의 같은 주석에 왼쪽 칸과 같은 금액이 다른 줄 이름으로 있음
"""
from __future__ import annotations

from .base import norm
from .dsd_grid import Doc
from .dsd_links import PAIR_ID, PRIOR_ID, Check, _isnum, _labels

LIMIT = 5            # 검증 하나에 붙이는 후보 수
MIN_DIGITS = 4       # 차이와 같은 칸을 찾는 차이의 최소 자릿수(표시 단위). 작은 차이는 우연히 같은 칸이 많다
MIN_DIGITS_PAIR = 5  # 두 칸의 합 · 차를 찾는 최소 자릿수


def _fmt(v: float) -> str:
    return f"{v:,.0f}" if abs(v - round(v)) < 1e-6 else f"{v:,.2f}"


def _digits(v: float) -> int:
    return len(str(int(abs(round(v))))) if abs(v) >= 1 else 0


def tables(doc: Doc, prior: Doc | None = None, wtb: Doc | None = None, other: Doc | None = None) -> dict:
    """검증의 표 id(작년: · 조서: · 짝: 앞머리 포함) → 표. dsd_links.evaluate 와 같은 짝이다."""
    tabs = {t.id: t for t in doc.tables()}
    if prior is not None:
        tabs.update({PRIOR_ID + t.id: t for t in prior.tables()})
    if wtb is not None:
        tabs.update({"조서:" + t.id: t for t in wtb.tables()})
    if other is not None:
        tabs.update({PAIR_ID + t.id: t for t in other.tables()})
    return tabs


def name(tabs: dict, key: tuple) -> str:
    tid, r, k = key
    t = tabs[tid]
    return f"{tid} {_labels(t)[r]} · {t.header[k]}".strip(" ·")


def _hint(kind: str, text: str, cells=()) -> dict:
    return {"kind": kind, "text": text, "cells": [list(x) for x in cells]}


def _variants(x: float) -> list[tuple[float, str]]:
    """한 칸을 잘못 적었을 때의 후보 값. 이웃한 두 자리를 바꿈, 자릿수를 하나 밈."""
    if abs(x - round(x)) > 1e-9 or abs(x) < 10:
        return []
    sign = -1 if x < 0 else 1
    s = str(int(abs(round(x))))
    out = []
    for i in range(len(s) - 1):
        if s[i] != s[i + 1]:
            t = s[:i] + s[i + 1] + s[i] + s[i + 2:]
            out.append((sign * int(t), "이웃한 두 자리를 바꿔 적음"))
    out.append((x * 10, "자릿수를 하나 밀어 적음"))
    if s.endswith("0"):
        out.append((x / 10, "자릿수를 하나 밀어 적음"))
    return out


def explain(doc: Doc, checks: list[Check], tabs: dict, priors: list | None = None) -> None:
    """FALSE · 확인 검증(단수 · 뺀 검증 제외)에 c.hints 를 채운다. priors 는 [(작년 문서, 앞머리, dsd_compare.match(doc, 작년))]."""
    part_of = {t.id: doc.part_of(t.id).key for t in doc.tables()}
    statements = [t.id for t in doc.tables() if not part_of[t.id].startswith("주석")]
    for c in checks:
        c.hints = []
        if c.ok is not False or c.minor or c.dropped or c.excluded or c.right is None or c.left is None:
            continue
        try:
            c.hints = _hints(c, doc, tabs, part_of, statements, priors or [])[:LIMIT]
        except (KeyError, IndexError, ValueError, ZeroDivisionError):
            c.hints = []                              # 후보는 참고다. 못 찾아도 검증은 그대로다


def _hints(c: Check, doc: Doc, tabs: dict, part_of: dict, statements: list, priors: list) -> list[dict]:
    out: list[dict] = []
    u = c.unit or 1
    L, R = float(c.left), float(c.right)
    d = L - R
    tol = max(float(c.tol or 0), 0.5)
    if c.cmp:                                         # 부분 대사는 넘친 금액만 본다
        return out
    # 단위
    if L and R:
        for f in (1000, 1_000_000):
            for a, b in ((L, R), (R, L)):
                if abs(a / b - f) <= f * 0.002:
                    out.append(_hint("단위", f"한쪽이 다른 쪽의 {f:,}배다. 한 칸의 단위를 잘못 적었을 수 있다"))
    # 부호(전체)
    if L and abs(L + R) <= tol:
        out.append(_hint("부호", f"두 금액의 크기({_fmt(abs(L))})가 같고 부호가 반대다"))
    left_key = (c.table, c.r, c.c)
    cells: list[tuple[tuple, int]] = [] if (c.expr or c.plain) else [(left_key, 0)] + [((tid, r, k), s) for tid, r, k, s in c.terms]

    def value(key):
        t = tabs[key[0]]
        v = t.nums[key[1]][key[2]]
        return (v, t.unit_at(key[1], key[2]) / u) if _isnum(v) else (None, None)

    def after(key, sign, x, x2, f):
        """칸 key 의 값 x 를 x2 로 바꿨을 때의 차이(표시 단위)."""
        if sign == 0:
            return (x2 * f) - R
        return L - (R - sign * x * f + sign * x2 * f)

    # 부호(한 항)
    for key, sign in cells[1:]:
        x, f = value(key)
        if x and abs(d + 2 * sign * x * f) <= tol:
            out.append(_hint("부호", f"「{name(tabs, key)}」 {_fmt(x)} 의 부호를 바꾸면 맞는다(차이가 그 금액의 두 배)", [key]))
    # 부호 표시: 부호만 다른 차이에서 그 칸 줄의 부호가 기간마다 다르면 표시 관례 차이일 수 있다
    # (실제 회사 자료 재무상태표 결손금: 당기 양수 · 전기 음수. 판정과 독립 검증이 당기를 음수로 고치라 했는데 최종판은 전기를 양수로 고쳤다)
    flipped = [k for k, _ in cells] if (L and abs(L + R) <= tol) else [tuple(h["cells"][0]) for h in out if h["kind"] == "부호" and h["cells"]]
    for key in flipped:
        tid, r, k = key
        x = tabs[tid].nums[r][k] if tid in statements else None
        if not (_isnum(x) and x):
            continue
        t = tabs[tid]
        j = next((j for j in range(1, len(t.header)) if j != k and _isnum(t.nums[r][j]) and t.nums[r][j] and (t.nums[r][j] > 0) != (x > 0)), None)
        if j is None:
            continue
        last = _prior_value(tid, r, priors)
        tail = f" 작년 보고서 {last[0]}{last[1]} 의 같은 줄 당기는 {_fmt(last[2])} 다." if last else " 작년 보고서가 없으면 어느 쪽을 고칠지 정하지 않는다."
        out.append(_hint("부호 표시", f"「{_labels(t)[r]}」 줄은 「{t.header[k]}」 {_fmt(x)} · 「{t.header[j]}」 {_fmt(t.nums[r][j])} 로 기간마다 부호가 다르다. "
                                     f"금액이 맞으면 부호 표시 차이(표시 오류)다. 작년 보고서의 같은 줄 부호로 어느 기간이 다른지 정한다.{tail}", [key, (tid, r, j)]))
    # 자리
    n_digit = 0
    for key, sign in cells:
        x, f = value(key)
        if x is None:
            continue
        for x2, how in _variants(x):
            if abs(after(key, sign, x, x2, f)) <= tol and n_digit < 2:
                out.append(_hint("자리", f"「{name(tabs, key)}」 의 {_fmt(x)} 을 {_fmt(x2)} 로 고치면 맞는다({how})", [key]))
                n_digit += 1
    a = abs(round(d))
    if not c.expr and a >= 10 and abs(d - round(d)) < 1e-6 and str(a).rstrip("0") in "123456789" and len(str(a).rstrip("0")) == 1 and not n_digit:
        out.append(_hint("자리", f"차이 {_fmt(a)} 은 한 자리만 다를 때 나는 꼴이다. 한 칸의 한 자리를 잘못 적었을 수 있다"))
    # 기간 열 · 이웃 줄
    n_col = n_row = 0
    for key, sign in cells:
        x, f = value(key)
        if x is None:
            continue
        tid, r, k = key
        t = tabs[tid]
        for j in range(1, len(t.header)):
            y = t.nums[r][j]
            if j != k and _isnum(y) and y and y != x and abs(after(key, sign, x, y, f)) <= tol and n_col < 2:
                out.append(_hint("기간 열", f"「{name(tabs, key)}」 대신 같은 줄 「{t.header[j]}」 의 {_fmt(y)} 를 넣으면 맞는다", [key, (tid, r, j)]))
                n_col += 1
        for i in (r - 1, r + 1, r - 2, r + 2):
            if 0 <= i < len(t.rows):
                y = t.nums[i][k]
                if _isnum(y) and y and y != x and abs(after(key, sign, x, y, f)) <= tol and n_row < 2:
                    out.append(_hint("이웃 줄", f"「{name(tabs, key)}」 대신 이웃 줄 「{_labels(t)[i]}」 의 {_fmt(y)} 를 넣으면 맞는다", [key, (tid, i, k)]))
                    n_row += 1
    # 같은 칸(한 칸, 두 칸의 합 · 차)
    own = {left_key} | {(tid, r, k) for tid, r, k, _ in c.terms}
    if c.span:
        tid, r0, c0, r1, c1 = c.span
        own |= {(tid, r, k) for r in range(r0, r1 + 1) for k in range(c0, c1 + 1)}
    if not c.expr and _digits(d) >= MIN_DIGITS:
        involved = list(dict.fromkeys([c.table] + [tid for tid, *_ in c.terms]))
        parts = {part_of[t] for t in involved if t in part_of}
        near = [t.id for t in doc.tables() if part_of[t.id] in parts and t.id not in involved]
        scopes = [("이 검증의 표", involved), ("같은 주석", near), ("재무제표", [s for s in statements if s not in involved])]
        target = abs(d)
        found = 0
        for label, ids in scopes:
            for key, v in _cells(tabs, ids, u):
                if key in own or not v:
                    continue
                if abs(abs(v) - target) <= tol and found < 2:
                    side = "왼쪽 칸에 이 금액이 더 들어 있거나 대사 대상에서 빠졌다" if d > 0 else "대사 대상에 이 금액이 더 들어 있거나 왼쪽 칸에서 빠졌다"
                    out.append(_hint("같은 칸", f"차이 {_fmt(target)} 와 같은 금액: 「{name(tabs, key)}」({label}). {side}", [key]))
                    found += 1
            if found:
                break
        if not found and _digits(d) >= MIN_DIGITS_PAIR:
            pool = [(key, v) for key, v in _cells(tabs, [i for _, ids in scopes[:2] for i in ids], u) if key not in own and v and abs(v) < target * 50]
            index: dict = {}
            for key, v in pool:
                index.setdefault(round(v), []).append(key)
            seen = set()
            for key, v in pool:
                for want, op in ((target - v, "+"), (v - target, "-")):
                    for w in (round(want) - 1, round(want), round(want) + 1):
                        for other in index.get(w, []):
                            if other == key or (other, key) in seen or (key, other) in seen:
                                continue
                            ov = tabs[other[0]].nums[other[1]][other[2]] * tabs[other[0]].unit_at(other[1], other[2]) / u
                            got = v + ov if op == "+" else v - ov
                            if abs(abs(got) - target) <= tol * 2 and len(seen) < 2:
                                seen.add((key, other))
                                out.append(_hint("같은 칸", f"차이 {_fmt(target)} = 「{name(tabs, key)}」 {_fmt(v)} {op} 「{name(tabs, other)}」 {_fmt(ov)}",
                                                 [key, other]))
    # 작년 이름
    if _digits(L) >= MIN_DIGITS and part_of.get(c.table):
        lw = L * u
        mine = norm(_labels(tabs[c.table])[c.r]) if c.table in tabs else ""
        for pdoc, tag, m in priors:
            if m is None:
                continue
            pk = m.parts.get(part_of[c.table])
            part = next((p for p in pdoc.parts if p.key == pk), None)
            if part is None:
                continue
            for x in part.items:
                if x[0] != "t":
                    continue
                q = x[1]
                for i in range(len(q.rows)):
                    for j in range(1, len(q.header)):
                        v = q.nums[i][j]
                        if _isnum(v) and abs(v * q.unit_at(i, j) - lw) <= 0.5 * max(u, q.unit_at(i, j)) and norm(_labels(q)[i]) != mine:
                            out.append(_hint("작년 이름", f"작년 보고서 {tag}{q.id} 는 같은 금액 {_fmt(L)} 을 「{_labels(q)[i]}」 줄 · 「{q.header[j]}」 열에 적었다"
                                                         f"(올해 줄 이름 「{_labels(tabs[c.table])[c.r]}」)"))
                            return out
    return out


def _prior_value(tid: str, r: int, priors: list):
    """작년 보고서에서 같은 표 · 같은 줄의 당기 금액. (앞머리, 작년 표 id, 값) 또는 None."""
    from .dsd_links import period_col

    for pdoc, tag, m in priors:
        mt = m.tables.get(tid) if m is not None else None
        if not mt:
            continue
        q = pdoc.table(mt[0])
        j = dict(mt[1]).get(r)
        b = period_col(q, "당기") if q is not None else None
        if q is not None and j is not None and b is not None and _isnum(q.nums[j][b]):
            return tag, q.id, q.nums[j][b]
    return None


def _cells(tabs: dict, ids: list, u: float):
    """표들의 숫자 칸 ((표 id, 줄, 열), 검증의 표시 단위로 바꾼 값)."""
    for tid in ids:
        t = tabs.get(tid)
        if t is None:
            continue
        for r in range(len(t.rows)):
            for k in range(1, len(t.header)):
                v = t.nums[r][k]
                if _isnum(v) and not t.rate(r, k):
                    yield (tid, r, k), v * t.unit_at(r, k) / u
