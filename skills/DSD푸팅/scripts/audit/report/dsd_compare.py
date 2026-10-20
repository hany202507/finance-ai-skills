"""DSD 푸팅: 두 보고서의 부분 · 표 · 줄 · 문단 짝 맞추기(2026-10-12).

기존 판 대비 차이(새 판 ↔ 기존 판)와 전기 대사(당기 보고서 ↔ 작년 보고서)가 같은 짝 맞추기를 쓴다.
짝은 이름으로 정한다(주석 제목, 표 머리줄, 행 이름, 열 이름). AI 를 쓰지 않는다.
바뀐 곳 세기(changes)는 엑셀의 차이 수식과 같은 셈이다. 시험이 둘을 대조한다.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from .base import norm
from .dsd_grid import Doc, Part, Table


@dataclass
class Match:
    parts: dict = field(default_factory=dict)        # 새 부분 key → 옛 부분 key
    tables: dict = field(default_factory=dict)       # 새 표 id → (옛 표 id, {새 행: 옛 행}, {새 열: 옛 열})
    paras: dict = field(default_factory=dict)        # (새 부분 key, 항목 번호) → 옛 부분의 항목 번호
    gone: dict = field(default_factory=dict)         # 새 부분 key → 없어진 것 설명(문단 · 표 · 줄)
    gone_parts: list = field(default_factory=list)   # 옛 보고서에만 있는 부분 이름


_FOOT = re.compile(r"\((?:\*|주)\s*\d*\)|\*\d*|\[주\d*\]")      # 「대 체(*)」 「계(주1)」 「비품[주]」 의 각주 표시
_PAREN = re.compile(r"\([^()]*\)")                              # 「영업이익(손실)」 의 괄호 말


def _name(s) -> str:
    return norm(_FOOT.sub("", str(s or "")))


def _ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, _name(a), _name(b)).ratio()


def _keyed(names: list[str]) -> dict:
    seen: dict[str, int] = {}
    out = {}
    for i, x in enumerate(names):
        k = norm(x)
        seen[k] = seen.get(k, 0) + 1
        out[(k, seen[k])] = i
    return out


def _pairs(new: list[str], old: list[str]) -> dict[int, int]:
    """이름으로 짝을 짓는다. 순서가 같은 구간을 먼저 잇고, 남은 것은 같은 이름 가운데 몇 번째인지로 잇는다.
    순서 맞춤을 먼저 하는 것은 같은 이름이 여러 번 나오는 표(당기 · 전기 구간이 있는 자본변동표)에 줄이 끼어들 때
    몇 번째인지만 보면 뒤의 줄이 모두 한 칸씩 어긋나기 때문이다."""
    a, b = [_name(x) for x in new], [_name(x) for x in old]
    out = {}
    for tag, a0, a1, b0, b1 in SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal":
            for k in range(a1 - a0):
                out[a0 + k] = b0 + k
    left_new = [i for i in range(len(a)) if i not in out]
    used = set(out.values())
    left_old = [j for j in range(len(b)) if j not in used]
    o = _keyed([b[j] for j in left_old])
    for k, i in _keyed([a[i] for i in left_new]).items():
        if k in o:
            out[left_new[i]] = left_old[o[k]]
    # 괄호 말이 붙고 떨어진 이름(「영업이익」 ↔ 「영업이익(손실)」). 양쪽에 그 이름이 하나씩일 때만 잇는다
    left_new = [i for i in range(len(a)) if i not in out]
    used = set(out.values())
    left_old = [j for j in range(len(b)) if j not in used]
    loose = lambda s: _PAREN.sub("", s)      # noqa: E731
    la, lb = Counter(loose(a[i]) for i in left_new), Counter(loose(b[j]) for j in left_old)
    for i in left_new:
        k = loose(a[i])
        if k and la[k] == 1 and lb.get(k) == 1:
            out[i] = next(j for j in left_old if loose(b[j]) == k)
    return out


def _nums(row: list) -> Counter:
    return Counter(v for v in row[1:] if isinstance(v, (int, float)) and v != 0)


def _overlap(a: Counter, b: Counter) -> float:
    n = max(sum(a.values()), sum(b.values()))
    return sum((a & b).values()) / n if n else 0.0


def _fuzzy_rows(t: Table, q: Table, rows: dict[int, int]) -> dict[int, int]:
    """이름으로 짝짓지 못한 줄을 비슷한 줄과 잇는다(새 판 ↔ 기존 판에서만 쓴다). 이름이 절반 이상 같고 숫자가 절반 이상 겹치거나,
    숫자가 없는 줄끼리 이름이 거의 같을 때만 잇는다. 줄 이름만 고친 것(전기초 → 당기초, 주식선택권 → 주식매수선택권)을 새 줄로 세지 않으려는 것이다."""
    nk, ok = row_keys(t), row_keys(q)
    used = set(rows.values())
    cand = []
    for i in range(len(t.rows)):
        if i in rows:
            continue
        for j in range(len(q.rows)):
            if j in used:
                continue
            name = SequenceMatcher(None, nk[i], ok[j]).ratio()
            a, b = _nums(t.nums[i]), _nums(q.nums[j])
            num = _overlap(a, b)
            if (name >= 0.5 and num >= 0.5) or (name >= 0.85 and not a and not b):
                cand.append((0.4 * name + 0.6 * num, -abs(i - j), i, j))
    out = {}
    for _, _, i, j in sorted(cand, reverse=True):
        if i not in out and j not in used:
            out[i] = j
            used.add(j)
    return out


def _fuzzy_cols(new: list[str], old: list[str], cols: dict[int, int]) -> dict[int, int]:
    """머리줄 글자가 조금 바뀐 열을 잇는다."""
    used = set(cols.values())
    cand = [(_ratio(new[i], old[j]), -abs(i - j), i, j) for i in range(1, len(new)) if i not in cols
            for j in range(1, len(old)) if j not in used and _ratio(new[i], old[j]) >= 0.6]
    out = {}
    for _, _, i, j in sorted(cand, reverse=True):
        if i not in out and j not in used:
            out[i] = j
            used.add(j)
    return out


def row_keys(t: Table) -> list[str]:
    """줄을 가리는 이름. 숫자 열이 나오기 전에 글자 열이 둘 이상이면(구분 · 회사명) 앞의 두 열을 잇고, 빈 첫 칸은 위 줄 것을 이어받는다.
    첫 칸만 쓰면 첫 칸이 빈 줄(같은 구분 아래 회사 여럿)이 순서로만 짝지어져, 줄이 끼어든 해에 엉뚱한 줄과 맞춰진다
    (2026-10-12 스터디: 종속기업 표의 전기 대사 80건 중 45건이 이 때문에 FALSE)."""
    ncol = len(t.header)
    if getattr(t, "kind", "") == "문장":                # 문장 금액 표는 문장(줄 이름)만으로 가린다. 원문 열(「3,650,000,000원」)을 넣으면
        return [norm(r[0]) for r in t.rows]           # 금액이 바뀐 줄의 짝을 못 지어 바뀐 곳이 「새 줄」 로 나왔다(11단계, 실제 회사 자료 보증 금액)
    rate = getattr(t, "rate", lambda i, j: False)      # % 칸은 숫자 열로 치지 않는다(줄 이름 경계가 판독 규칙을 바꾸기 전과 같게)
    first_num = next((j for j in range(1, ncol) if any(isinstance(r[j], (int, float)) and not rate(i, j) for i, r in enumerate(t.nums))), ncol)
    if first_num < 2 or norm(t.header[1]).startswith("주석"):      # 과목 옆 주석 번호는 해마다 바뀌므로 이름에 넣지 않는다
        return [norm(r[0]) for r in t.rows]
    out, carry = [], ""
    for r in t.rows:
        carry = r[0].strip() or carry
        out.append(norm(carry) + "|" + norm(r[1]))
    return out


def _tables(p: Part) -> list[Table]:
    return [x[1] for x in p.items if x[0] == "t"]


def _match_parts(new: Doc, old: Doc) -> dict[str, str]:
    out, used = {}, set()
    olds = {p.key: p for p in old.parts}
    for p in new.parts:
        if not p.key.startswith("주석") and p.key in olds:
            out[p.key] = p.key
            used.add(p.key)
    notes = [p for p in old.parts if p.key.startswith("주석")]
    for p in new.parts:                                    # 주석은 제목이 같은 것부터
        if p.key.startswith("주석"):
            q = next((q for q in notes if q.key not in used and norm(q.title) == norm(p.title)), None)
            if q:
                out[p.key] = q.key
                used.add(q.key)
    for p in new.parts:                                    # 남은 주석은 번호가 같고 제목이 비슷하면
        if p.key.startswith("주석") and p.key not in out:
            q = olds.get(p.key)
            if q and q.key not in used and _ratio(p.title, q.title) >= 0.6:
                out[p.key] = q.key
                used.add(q.key)
    return out


def _table_score(t: Table, q: Table) -> float:
    """두 표가 같은 표일 정도(0~1). 머리줄, 줄 이름, 숫자가 겹치는 정도를 본다. 머리줄이 다르면 0 이다.
    숫자를 보는 것은 머리줄과 줄 이름이 같은 표가 둘일 때(당기 표와 전기 표) 가르기 위해서다."""
    head = _ratio(" ".join(t.header), " ".join(q.header))
    if head < 0.6:
        return 0.0
    a, b = Counter(row_keys(t)), Counter(row_keys(q))
    rows = sum((a & b).values()) / max(len(t.rows), len(q.rows), 1)
    na, nb = Counter(), Counter()
    for r in t.nums:
        na += _nums(r)
    for r in q.nums:
        nb += _nums(r)
    return 0.4 * head + 0.3 * rows + 0.3 * _overlap(na, nb)


def _match_tables(np: Part, op: Part) -> dict[str, str]:
    """표를 순서를 지키며 짝짓는다. 짝의 점수 합이 가장 큰 맞춤을 고른다(표가 끼어들거나 빠져도 뒤의 표가 어긋나지 않는다).
    순서 맞춤에서 남은 표는 머리줄이 같은 표와 잇는다(주석 안에서 표 순서를 바꾼 경우)."""
    from .dsd_links import period_labels

    nt, ot = _tables(np), _tables(op)
    n, k = len(nt), len(ot)
    ln, lo = period_labels(np), period_labels(op)      # 표 위에 적힌 기간(당반기 · 전반기 · 당기말 …)이 다르면 짝짓지 않는다
    sc = [[0.0 if ln.get(t.id) and lo.get(q.id) and ln[t.id] != lo[q.id] else _table_score(t, q) for q in ot] for t in nt]
    best = [[0.0] * (k + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        for j in range(k - 1, -1, -1):
            best[i][j] = max(best[i + 1][j], best[i][j + 1], (sc[i][j] + best[i + 1][j + 1]) if sc[i][j] > 0 else 0.0)
    out, used = {}, set()
    i = j = 0
    while i < n and j < k:
        if sc[i][j] > 0 and abs(best[i][j] - (sc[i][j] + best[i + 1][j + 1])) < 1e-12:
            out[nt[i].id] = ot[j].id
            used.add(ot[j].id)
            i, j = i + 1, j + 1
        elif best[i + 1][j] >= best[i][j + 1]:
            i += 1
        else:
            j += 1
    sig = lambda t: tuple(_name(h) for h in t.header)     # noqa: E731
    for t in nt:
        if t.id in out:
            continue
        q = max((x for x in ot if x.id not in used and sig(x) == sig(t)), key=lambda x: _table_score(t, x), default=None)
        if q:
            out[t.id] = q.id
            used.add(q.id)
    return out


def _match_paras(np: Part, op: Part) -> dict[int, int]:
    """문단을 순서대로 짝짓는다. 같은 문단을 먼저 잇고, 그 사이에서 바뀐 문단은 글자가 절반 이상 같으면 짝짓는다."""
    ni = [i for i, x in enumerate(np.items) if x[0] == "p"]
    oi = [i for i, x in enumerate(op.items) if x[0] == "p"]
    a, b = [norm(np.items[i][1]) for i in ni], [norm(op.items[i][1]) for i in oi]
    out = {}
    for tag, a0, a1, b0, b1 in SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal":
            for k in range(a1 - a0):
                out[ni[a0 + k]] = oi[b0 + k]
        elif tag == "replace":
            for k in range(min(a1 - a0, b1 - b0)):
                if SequenceMatcher(None, a[a0 + k], b[b0 + k]).ratio() >= 0.5:
                    out[ni[a0 + k]] = oi[b0 + k]
    return out


def match(new: Doc, old: Doc, fuzzy: bool = False) -> Match:
    """fuzzy 는 새 판 ↔ 기존 판에서 쓴다. 이름이 조금 바뀐 줄과 열도 짝짓고, 바뀐 이름을 「없어진 것」 목록에 적는다.
    전기 대사(당기 보고서 ↔ 작년 보고서)는 과목이 재분류되므로 이름이 같은 줄만 짝짓는다."""
    m = Match(parts=_match_parts(new, old))
    olds = {p.key: p for p in old.parts}
    m.gone_parts = [f"{p.key} {p.title}" for p in old.parts if p.key not in m.parts.values()]
    for p in new.parts:
        gone = []
        op = olds.get(m.parts.get(p.key))
        if op is not None:
            pairs = _match_tables(p, op)
            if not p.key.startswith("주석"):         # 재무제표 본표는 머리줄(기수, 기간 이름)이 해마다 달라도 차례대로 같은 표다
                olds_in_order = _tables(op)
                for k, t in enumerate(_tables(p)):
                    if t.id not in pairs and k < len(olds_in_order) and olds_in_order[k].id not in pairs.values():
                        pairs[t.id] = olds_in_order[k].id
            ot = {t.id: t for t in _tables(op)}
            for t in _tables(p):
                if t.id not in pairs:
                    continue
                q = ot[pairs[t.id]]
                rows, cols = _pairs(row_keys(t), row_keys(q)), _pairs(t.header, q.header)
                cols.setdefault(0, 0)
                if fuzzy:
                    more = _fuzzy_cols(t.header, q.header, cols)
                    gone += [f"이름 바뀐 열: {t.id} {q.header[j]} → {t.header[i]}" for i, j in sorted(more.items())]
                    cols.update(more)
                    more = _fuzzy_rows(t, q, rows)
                    gone += [f"이름 바뀐 줄: {t.id} {q.rows[j][0]} → {t.rows[i][0]}" for i, j in sorted(more.items()) if norm(q.rows[j][0]) != norm(t.rows[i][0])]
                    rows.update(more)
                m.tables[t.id] = (q.id, rows, cols)
                gone += [f"없어진 줄: {t.id} {q.rows[i][0]}" for i in range(len(q.rows)) if i not in rows.values() and q.rows[i][0].strip()]
            gone += [f"없어진 표: {q.id} {q.caption[:30]}" for q in _tables(op) if q.id not in pairs.values()]
            pp = _match_paras(p, op)
            for i, j in pp.items():
                m.paras[(p.key, i)] = j
            gone += [f"없어진 문단: {x[1][:60]}" for j, x in enumerate(op.items) if x[0] == "p" and j not in pp.values()]
        m.gone[p.key] = gone
    return m


def cell_text(t: Table, i: int, j: int) -> str:
    """엑셀 칸에 들어가는 값의 글자. 숫자 칸은 숫자, 아니면 원문 글자."""
    v = t.nums[i][j] if j else None
    return str(v) if v is not None else (t.rows[i][j] or "")


def numeric(t: Table, i: int, j: int) -> bool:
    """숫자로 견줄 칸인가. 숫자 칸과 빈칸이다(빈칸은 0 으로 본다. 「-」 를 넣거나 뺀 것은 바뀐 곳이 아니다)."""
    return isinstance(t.nums[i][j], (int, float)) or not (t.rows[i][j] or "").strip()


def changes(new: Doc, old: Doc, m: Match) -> dict[str, int]:
    """부분마다 바뀐 곳 수. 바뀐 칸 · 바뀐 문단 · 새 줄 · 새 문단 · 없어진 것을 센다(엑셀의 「바뀜」 열과 같은 셈)."""
    olds = {p.key: p for p in old.parts}
    out = {}
    for p in new.parts:
        op = olds.get(m.parts.get(p.key))
        ot = {t.id: t for t in _tables(op)} if op is not None else {}
        n = len(m.gone.get(p.key, []))
        for i, x in enumerate(p.items):
            if x[0] == "p":
                j = m.paras.get((p.key, i))
                n += 1 if j is None or op.items[j][1] != x[1] else 0
                continue
            t = x[1]
            mt = m.tables.get(t.id)
            q = ot[mt[0]] if mt else None
            for r in range(len(t.rows)):
                new_row = q is None or r not in mt[1]
                n += 1 if new_row else 0
                for c in range(1, len(t.header)):
                    v = t.nums[r][c]
                    if new_row or c not in mt[2]:
                        n += 1 if isinstance(v, (int, float)) and v != 0 else 0
                        continue
                    w = q.nums[mt[1][r]][mt[2][c]]
                    if numeric(t, r, c) and numeric(q, mt[1][r], mt[2][c]):
                        n += 1 if (v or 0) != (w or 0) else 0
                    else:
                        n += 1 if cell_text(t, r, c) != cell_text(q, mt[1][r], mt[2][c]) else 0
        out[p.key] = n
    return out


def _key(vals) -> tuple:
    """0 이 아닌 숫자의 절댓값 묶음. 사업보고서(XBRL)는 비용 · 차감 항목의 부호를 감사보고서와 다르게 적기도 해 부호는 보지 않는다."""
    return tuple(sorted(round(abs(float(v)), 6) for v in vals if isinstance(v, (int, float)) and v != 0))


def _greedy(score: dict, floor: float) -> dict:
    """{(새, 옛): 점수} 에서 점수가 높은 짝부터 겹치지 않게 고른다."""
    out, used = {}, set()
    for (i, j), s in sorted(score.items(), key=lambda kv: -kv[1]):
        if s >= floor and i not in out and j not in used:
            out[i] = j
            used.add(j)
    return out


def match_numbers(new: Doc, old: Doc) -> dict:
    """숫자로 짝짓기: {새 표 id: (옛 표 id, {새 줄: 옛 줄}, {새 열: 옛 열})}. 같은 기간을 다른 꼴로 낸 두 문서(감사보고서 원문과
    사업보고서 본문)는 숫자가 같고 머리줄 · 줄 이름이 다르다(「계」 와 「유형자산 합계」). 이름 짝이 안 되는 표 · 줄 · 열을 숫자로 잇는다.
    표는 새 표의 0 이 아닌 숫자가 다섯 개 이상이고 그 6할 이상이 옛 표에 있을 때 잇는다. 사업보고서는 감사보고서의 한 표를 당기 표와 전기 표로
    나눠 싣기도 해서 새 표 여럿이 옛 표 하나와 이어질 수 있다. 줄과 열은 숫자 묶음이 같거나 겹침이 6할 이상일 때 잇는다."""
    nt, ot = new.tables(), old.tables()
    bag = lambda t: Counter(abs(v) for r in t.nums for v in r[1:] if isinstance(v, (int, float)) and v != 0)      # noqa: E731
    nb, ob = {t.id: bag(t) for t in nt}, {t.id: bag(t) for t in ot}
    pairs, score = {}, {}
    for t in nt:
        n = sum(nb[t.id].values())
        if n < 5:
            continue
        best = max(((sum((nb[t.id] & ob[q.id]).values()) / n, q.id) for q in ot), default=(0, None))
        if best[0] >= 0.6:
            pairs[t.id] = best[1]
            score[t.id] = best[0]
    olds = {q.id: q for q in ot}
    out = {}
    for t in nt:
        if t.id not in pairs:
            continue
        q = olds[pairs[t.id]]

        def axis(n_items, o_items):
            """새 줄(열)의 숫자가 옛 줄(열)에 들어 있는 정도로 잇는다. 사업보고서가 표를 당기 · 전기로 나누면 새 줄은 옛 줄 숫자의 일부만 담는다.
            새 숫자의 6할 이상이 옛 줄에 있고, 그런 옛 줄이 하나뿐이거나 그 가운데 가장 많이 겹칠 때만 잇는다(같은 숫자가 여러 줄에 있으면 잇지 않는다)."""
            okeys = [Counter(_key(w)) for w in o_items]
            sc = {}
            for i, vals in enumerate(n_items):
                k = Counter(_key(vals))
                n = sum(k.values())
                if not n:
                    continue
                hits = sorted(((sum((k & ok).values()) / n, j) for j, ok in enumerate(okeys) if ok), reverse=True)
                if not hits or hits[0][0] < 0.6:
                    continue
                if len(hits) > 1 and hits[1][0] >= hits[0][0] and n < 3:
                    continue                            # 숫자 한두 개가 여러 줄에 똑같이 있다
                sc[(i, hits[0][1])] = hits[0][0] + (0.001 if sum(okeys[hits[0][1]].values()) == n else 0)
            return _greedy(sc, 0.6)

        rows = axis([r[1:] for r in t.nums], [r[1:] for r in q.nums])
        cols = axis([[r[j] for r in t.nums] for j in range(len(t.header))], [[r[j] for r in q.nums] for j in range(len(q.header))])
        cols[0] = 0
        out[t.id] = (q.id, rows, cols, score[t.id])
    return out
