"""DSD 푸팅: 표 사이 숫자 연결(레퍼)을 금액 근거로 찾는다(2026-10-12).

재무제표 과목과 주석 표, 주석 표와 주석 표 사이의 「같아야 하는 숫자」를 이름으로 짐작하지 않고 금액으로 찾는다.

  둘 다 같음   한 줄의 (당기, 전기) 두 금액이 다른 표의 한 줄과 둘 다 같으면 건다. 숫자 두 개가 나란히 같은 것은 우연이기 어렵다.
               이렇게 건 연결은 처음에는 전부 TRUE 이고, 연결 정의에 남아 다음 판에서 한쪽 숫자가 달라지면 FALSE 가 된다.
  참조 주석    재무제표 과목 옆 「(주석 5)」 가 가리키는 주석에서 한 기간 금액만 같고 다른 기간이 10% 안에서 다른 줄이 하나뿐이면 건다.
               다른 기간이 FALSE 로 뜬다. 처음 받은 판에서 틀린 숫자를 잡는 길이다.
  여러 줄 합   가리키는 주석의 한 표에서 두세 줄을 더하면 과목의 당기 · 전기와 둘 다 같은 조합이 하나뿐이면 건다(유동 + 비유동).
  한 금액      위 셋으로 주석과 이어지지 않은 과목은, 가리키는 주석 안에서 그 과목 금액과 같은 칸(여섯 자리 이상)을 건다.
               전기 금액이 없는 과목과 날짜별 변동표처럼 (당기, 전기) 짝을 읽을 수 없는 표가 여기서 걸린다.

(당기, 전기) 짝을 읽는 곳:
  재무제표 본표의 당기 열과 전기 열. 자본변동표는 기간 열이 없어 보지 않는다.
  주석 표의 「당기…」 열과 「전기…」 열(당기말 ↔ 전기말), 「당기말」 줄과 「전기말」 줄.
  변동표의 기말과 기초(열이든 줄이든). 기말이 당기말, 기초가 전기말이다.
  머리줄이 같은 이웃한 두 표(당기 표와 전기 표를 따로 둔 주석). 표 제목에 「전기」 가 있는 쪽이 전기, 없으면 앞 표가 당기다.

기준이 되는 칸은 재무제표 과목이다. 같은 금액 짝이 재무제표 여러 줄에 있으면 그 주석을 가리키는 과목, 아래 단계 과목 순으로 고른다.
재무제표에 없고 주석 여러 곳에만 있으면 먼저 나온 주석 줄이 기준이다. 한 표 안에서 되풀이되는 금액은 걸지 않는다.
"""
from __future__ import annotations

from itertools import combinations

from .base import norm
from .dsd_grid import Doc, Table
from .dsd_links import _isnum, _labels, _ref, period_col, total_kind

MIN_DIGITS = 4          # 금액이 이 자릿수보다 짧으면 우연히 같기 쉬워 근거로 쓰지 않는다
NEAR = 0.1              # 참조 주석에서 한 기간만 같을 때, 다른 기간이 이 비율 안에서 다르면 같은 항목으로 본다
SINGLE_DIGITS = 6       # 금액 하나만으로 걸 때(과목이 그 주석을 가리킬 때만)의 자릿수
BOTH = "당기 · 전기 금액이 둘 다 같음"


def _digits(v) -> int:
    return len(str(abs(int(v))))


def _row_map(a: Table, b: Table) -> dict[int, int]:
    seen: dict[str, list] = {}
    for j, x in enumerate(_labels(b)):
        seen.setdefault(norm(x), []).append(j)
    out, count = {}, {}
    for i, x in enumerate(_labels(a)):
        k = norm(x)
        n = count.get(k, 0)
        count[k] = n + 1
        if n < len(seen.get(k, [])):
            out[i] = seen[k][n]
    return out


def period_cells(doc: Doc, t: Table) -> list[tuple]:
    """한 표 안의 (당기 칸, 전기 칸) 짝들. 칸은 (표, 행, 열)."""
    key = doc.part_of(t.id).key
    rows = range(len(t.rows))
    if not key.startswith("주석"):
        if key == "자본변동표":
            return []
        a, b = period_col(t, "당기"), period_col(t, "전기")
        return [((t, i, a), (t, i, b)) for i in rows] if a and b and a != b else []
    out = []
    names = [norm(h) for h in t.header]
    for j, h in enumerate(names):
        if not j:
            continue
        other = h.replace("당기", "전기") if "당기" in h else (h.replace("(당)", "(전)") if "(당)" in h else None)
        if other and other != h and names.count(other) == 1:
            k = names.index(other)
            out += [((t, i, j), (t, i, k)) for i in rows]
    cur = [j for j, h in enumerate(names) if j and "당기" in h and "전기" not in h]
    pri = [j for j, h in enumerate(names) if j and "전기" in h and "당기" not in h]
    if not out and len(cur) == 1 and len(pri) == 1:      # 「당기 처리예정일 …」 「전기 처리확정일 …」 처럼 이름이 달라도 기간 열이 하나씩이면
        out += [((t, i, cur[0]), (t, i, pri[0])) for i in rows]
    a = [j for j, h in enumerate(names) if j and h.startswith("기초")]
    b = [j for j, h in enumerate(names) if j and h.startswith("기말")]
    if len(a) == 1 and len(b) == 1:
        out += [((t, i, b[0]), (t, i, a[0])) for i in rows]
    labels = [norm(x) for x in _labels(t)]
    for cur, pri in (("당기말", "전기말"), ("기말", "기초")):
        r1 = [i for i, x in enumerate(labels) if x.startswith(cur)]
        r0 = [i for i, x in enumerate(labels) if x.startswith(pri)]
        if len(r1) == 1 and len(r0) == 1:
            out += [((t, r1[0], c), (t, r0[0], c)) for c in range(1, len(t.header))]
    return out


def twin_cells(doc: Doc) -> list[tuple]:
    """머리줄이 같은 이웃한 두 표에서 같은 줄 · 같은 열의 (당기 칸, 전기 칸) 짝들."""
    out = []
    for p in doc.parts:
        if not p.key.startswith("주석"):
            continue
        tabs = [x[1] for x in p.items if x[0] == "t"]
        k = 0
        while k + 1 < len(tabs):
            a, b = tabs[k], tabs[k + 1]
            if len(a.header) > 1 and [norm(h) for h in a.header] == [norm(h) for h in b.header]:
                ca, cb = norm(a.caption), norm(b.caption)
                if "전기" in ca and "당기" not in ca and "전기" not in cb:      # 앞 표의 제목이 전기만 말할 때만 순서를 바꾼다
                    a, b = b, a
                for i, j in _row_map(a, b).items():
                    out += [((a, i, c), (b, j, c)) for c in range(1, len(a.header))]
                k += 2
            else:
                k += 1
    return out


def _occurrences(doc: Doc) -> list[dict]:
    big = max((t.unit for t in doc.tables()), default=1)
    order = {t.id: n for n, t in enumerate(doc.tables())}
    pairs = [c for t in doc.tables() for c in period_cells(doc, t)] + twin_cells(doc)
    out = []
    for cur, pri in pairs:
        (t1, r1, c1), (t0, r0, c0) = cur, pri
        v, w = t1.nums[r1][c1], t0.nums[r0][c0]
        if not (_isnum(v) and _isnum(w)) or not v or not w:
            continue
        out.append({"cur": cur, "pri": pri, "fs": not doc.part_of(t1.id).key.startswith("주석"), "order": order[t1.id],
                    "tables": {t1.id, t0.id}, "key": (round(v * t1.unit / big), round(w * t0.unit / big)),
                    "won": (v * t1.unit, w * t0.unit), "unit": max(t1.unit, t0.unit),
                    "strong": _digits(v) >= MIN_DIGITS and _digits(w) >= MIN_DIGITS})
    return out


def same(x: dict, y: dict, k: int) -> bool:
    """두 곳의 k 번째(0 당기, 1 전기) 금액이 부호를 떼고 같은지. 단위가 같으면 그대로, 다르면 큰 단위로 반올림해 견준다."""
    a, b, u = abs(x["won"][k]), abs(y["won"][k]), max(x["unit"], y["unit"])
    if x["unit"] == y["unit"]:                    # 천원 · 백만원 단위 표끼리는 따로 반올림한 숫자라 1 까지 다를 수 있다
        return abs(a - b) <= (u if u > 1 else 0) + 1e-6
    return abs(round(a / u) - round(b / u)) <= 1          # 단위가 다른 표 사이는 검증도 큰 단위에서 차이 1 을 허용한다


def _note_no(doc: Doc, t: Table) -> int | None:
    key = doc.part_of(t.id).key
    return int(key[2:]) if key.startswith("주석") and key[2:].isdigit() else None


def _cell_ref(cell: tuple, sign: int = 1) -> dict:
    t, r, c = cell
    lab, head = _ref(_labels(t), r), _ref(t.header, c)
    d = {"table": t.id, "row": lab[0], "row_nth": lab[1], "col": head[0], "col_nth": head[1], "exact": True}
    if sign != 1:
        d["sign"] = sign
    return d


def _link(cell: tuple, anchor: tuple, sign: int, basis: str) -> dict:
    t, r, c = cell
    lab, head = _ref(_labels(t), r), _ref(t.header, c)
    d = {"id": f"레퍼|{t.id}|{lab[0]}#{lab[1]}|{head[0]}#{head[1]}", "left": _cell_ref(cell), "right": [_cell_ref(anchor, sign)],
         "source": "규칙", "basis": basis}
    if t.unit > 1 and anchor[0].unit > 1:
        d["tol"] = 1
    return d


def detect(doc: Doc, taken: set) -> list[dict]:
    """금액 근거로 찾은 연결들(연결 정의의 links 꼴). taken 은 이미 연결이 걸린 왼쪽 칸 (표 id, 행, 열)."""
    occ = _occurrences(doc)
    links, used = [], set(taken)
    big = max((t.unit for t in doc.tables()), default=1)

    def add(x, y, sign, basis):
        for k in ("cur", "pri"):
            t, r, c = x[k]
            if (t.id, r, c) in used:
                continue
            used.add((t.id, r, c))
            links.append(_link(x[k], y[k], sign, basis))

    def fs_row(y):
        t, r, _ = y["cur"]
        return t, r

    strong = [x for x in occ if x["strong"] and x["key"][0] and x["key"][1]]
    index: dict[tuple, list] = {}
    for n, x in enumerate(strong):
        k = x["key"]
        index.setdefault((abs(k[0]), abs(k[1]), (k[0] > 0) == (k[1] > 0)), []).append(n)
    parent = list(range(len(strong)))

    def find(n):
        while parent[n] != n:
            parent[n] = parent[parent[n]]
            n = parent[n]
        return n

    for (k0, k1, flag), members in index.items():       # 열쇠는 큰 단위로 뭉뚱그린 것이라 이웃 열쇠까지 보고 실제 금액으로 확인한다
        for d0 in (0, 1):
            for d1 in (-1, 0, 1):
                if (d0, d1) < (0, 0) or (d0 == 0 and d1 < 0):
                    continue
                for m in members:
                    for n in index.get((k0 + d0, k1 + d1, flag), []):
                        if m != n and same(strong[m], strong[n], 0) and same(strong[m], strong[n], 1):
                            parent[find(m)] = find(n)
    comp: dict[int, list] = {}
    for n, x in enumerate(strong):
        comp.setdefault(find(n), []).append((x, 1 if x["key"][0] > 0 else -1))
    anchored = set()                                       # 주석과 이어진 재무제표 줄 (표 id, 행)
    exact = list(comp.values())
    for xs in exact:
        if len(set().union(*(x["tables"] for x, _ in xs))) < 2:
            continue
        fs = [(x, s) for x, s in xs if x["fs"]]
        for x, s in xs:
            cands = [(y, sy) for y, sy in (fs or xs[:1]) if not (y["tables"] & x["tables"])]
            if not cands or (not fs and x is xs[0][0]):
                continue
            no = _note_no(doc, x["cur"][0])

            def rank(c):
                t, r = fs_row(c[0])
                refs = (t.refs or [[]] * len(t.rows))[r]
                level = (t.levels or [0] * len(t.rows))[r] or 0
                return (0 if no is not None and no in refs else 1, -level, c[0]["order"], r)

            y, sy = min(cands, key=rank)
            if x["fs"] and y["order"] > x["order"]:        # 재무제표끼리는 앞 재무제표가 기준이다
                continue
            add(x, y, s * sy, BOTH)
            if y["fs"] and not x["fs"]:
                t, r = fs_row(y)
                anchored.add((t.id, r))
    by_note: dict[int, list] = {}
    for x in occ:
        no = _note_no(doc, x["cur"][0])
        if no is not None:
            by_note.setdefault(no, []).append(x)
    for y in occ:                                          # 참조 주석: 과목이 가리키는 주석에서 한 기간만 같은 줄
        if not y["fs"] or not y["strong"]:
            continue
        t, r = fs_row(y)
        refs = (t.refs or [[]] * len(t.rows))[r]
        if not refs or (t.id, r) in anchored:
            continue
        half = []
        for no in refs:
            for x in by_note.get(no, []):
                eq = (same(x, y, 0), same(x, y, 1))
                if eq[0] != eq[1]:
                    k = 1 if eq[0] else 0                  # 안 맞는 기간: 부호가 같고 10% 안에서 다를 때만 같은 항목으로 본다
                    a, b = x["won"][k], y["won"][k]
                    flip = -1 if (x["won"][1 - k] > 0) != (y["won"][1 - k] > 0) else 1
                    if a * flip * b > 0 and abs(abs(a) - abs(b)) <= NEAR * abs(b):
                        half.append((x, 0 if eq[0] else 1))
        if len(half) != 1:
            continue
        x, which = half[0]
        sign = 1 if (x["key"][which] > 0) == (y["key"][which] > 0) else -1
        add(x, y, sign, f"재무제표가 주석 {_note_no(doc, x['cur'][0])} 을 참조하고 {'당기' if which == 0 else '전기'} 금액이 같음")
    # 참조 주석의 여러 줄 합: 과목이 가리키는 주석의 한 표에서 두세 줄을 더하면 당기 · 전기가 둘 다 같은 조합이 하나뿐일 때
    for y in occ:
        if not y["fs"] or not y["strong"]:
            continue
        t, r = fs_row(y)
        refs = (t.refs or [[]] * len(t.rows))[r]
        if not refs or (t.id, r) in anchored or any((t.id, r, y[k][2]) in used for k in ("cur", "pri")):
            continue
        found = []
        for no in refs:
            part = next((p for p in doc.parts if p.key == f"주석{no}"), None)
            for q in ([x[1] for x in part.items if x[0] == "t"] if part else []):
                cols: dict[tuple, list] = {}
                for (qa, i, a), (qb, j, b) in period_cells(doc, q):
                    if i == j and not total_kind(q.rows[i][0]) and _isnum(q.nums[i][a]) and _isnum(q.nums[i][b]):
                        cols.setdefault((a, b), []).append(i)
                for (a, b), rows in cols.items():
                    if len(rows) > 25:
                        continue
                    for n in (2, 3):
                        for combo in combinations(rows, n):
                            z = {"won": (sum(q.nums[i][a] for i in combo) * q.unit, sum(q.nums[i][b] for i in combo) * q.unit), "unit": q.unit}
                            if z["won"][0] and z["won"][1] and same(z, y, 0) and same(z, y, 1) and (z["won"][0] > 0) == (y["won"][0] > 0):
                                found.append((q, combo, a, b))
        if len(found) != 1:
            continue
        q, combo, a, b = found[0]
        for k, col in (("cur", a), ("pri", b)):
            ft, fr, fc = y[k]
            lab, head = _ref(_labels(ft), fr), _ref(ft.header, fc)
            d = {"id": f"레퍼|{ft.id}|{lab[0]}#{lab[1]}|{head[0]}#{head[1]}", "left": _cell_ref(y[k]),
                 "right": [_cell_ref((q, i, col)) for i in combo], "source": "규칙",
                 "basis": f"주석 {_note_no(doc, q)} 의 {len(combo)}줄을 더하면 당기 · 전기 금액이 둘 다 같음"}
            if q.unit > 1 or ft.unit > 1:
                d["tol"] = 1
            used.add((ft.id, fr, fc))
            links.append(d)
        anchored.add((t.id, r))
    # 참조 주석의 한 금액: 한 기간 금액이 없어 짝을 못 쓰는 과목(새 과목, 전기 0)과 날짜별 변동표처럼 기간 짝이 없는 표
    for t in doc.tables():
        if not t.refs or doc.part_of(t.id).key == "자본변동표":
            continue
        cols = [c for c in (period_col(t, "당기"), period_col(t, "전기")) if c]
        for r in range(len(t.rows)):
            if not t.refs[r] or (t.id, r) in anchored:
                continue
            for c in cols:
                v = t.nums[r][c]
                if not _isnum(v) or _digits(v) < SINGLE_DIGITS:
                    continue
                for no in t.refs[r]:
                    p = next((p for p in doc.parts if p.key == f"주석{no}"), None)
                    for q in ([x[1] for x in p.items if x[0] == "t"] if p else []):
                        for i in range(len(q.rows)):
                            for j in range(1, len(q.header)):
                                w = q.nums[i][j]
                                u = max(q.unit, t.unit)
                                hit = _isnum(w) and (abs(abs(w) - abs(v)) <= (1 if u > 1 else 0) + 1e-6 if q.unit == t.unit
                                                     else abs(round(abs(w) * q.unit / u) - round(abs(v) * t.unit / u)) <= 1)
                                if hit and (q.id, i, j) not in used:
                                    used.add((q.id, i, j))
                                    links.append(_link((q, i, j), (t, r, c), 1 if (w > 0) == (v > 0) else -1,
                                                       f"재무제표가 주석 {no} 을 참조하고 금액이 같음"))
    return links
