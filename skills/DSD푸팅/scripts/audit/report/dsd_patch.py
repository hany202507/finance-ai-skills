"""DSD 푸팅: 연결.json 의 번호 칸과 표 한 줄을 이름 칸 · 연결로 푼다(2026-10-23, 숫자 쪽 속도).

읽기 자료의 표에는 줄 번호와 열 번호가 붙는다. AI 는 칸을 「표:줄:열」(「주석5-1:2:1」) 로 적고, 줄 하나는 「표:줄」, 같은 표 안의
줄 · 열은 번호(정수)로 적는다. 빼는 칸은 앞에 「-」 를 붙인다(「-재무상태표:8:1」, 합계 구조의 항 -3). 이름으로 적어도 된다.
넣을 때 엔진이 번호를 읽기 자료와 같은 이름 칸(표 · 줄 이름 · 순번 · 열 이름)으로 바꾼다. 연결 정의(dsd_연결정의.json)는 이름으로만
남으므로 다음 판 · --carry · --add 는 예전과 같이 이름으로 푼다. 번호는 읽기 자료를 만든 그 판에서만 뜻이 있다.

표 한 줄(tables, 분석 6.2): 엔진 후보가 없는 표는 연결을 칸마다 적지 않고 표마다 한 줄을 적는다.

    {"table": "주석9-1", "kind": "구성", "total": 7, "item": "재무상태표:15", "basis": "…"}

엔진이 기간 열(당기 · 전기)마다 「합계 줄 = 과목」 연결을 만들고, 그 합계 줄에 합계 구조가 없으면 위 줄의 합을 합계 구조로 더한다.
kind 는 구성 · 변동 · 범주 · 만기 · 일부. 변동은 total 대신 close(기말 줄)와 open(기초 줄)이고 기초는 과목의 전기와 잇는다.
일부는 cmp le(일부 ≤ 과목)로 건다. 줄마다 과목이 다르면 each {줄: 과목} 으로 적는다. 기간 열은 엔진이 열 이름(당기말 · 전기말 ·
당반기 · 제 N 기)으로 정하고, 못 정하면 cols {열: 당기 | 전기} 나, 표 하나가 한 기간이면 period 와 col(합계 열) 로 적는다.
연결 · 합계 구조를 금액으로 고르지 않는다. AI 가 적은 표 종류 · 합계 줄 · 과목이 근거다(금액 대조 연결 반려).
"""
from __future__ import annotations

import re

from .base import norm
from .dsd_grid import Doc, Table
from .dsd_links import DECREASE, PAIR_ID, _isnum, _labels, _ref, detect, is_rate, period_col, term_of, total_kind

STATEMENTS = ("재무상태표", "손익계산서", "현금흐름표")
KINDS = ("구성", "변동", "범주", "만기", "일부")
_CELL = re.compile(r"^\s*(-?)\s*(.+?)\s*:\s*(\d+)\s*:\s*(\d+)\s*$")
_ROW = re.compile(r"^\s*(-?)\s*(.+?)\s*:\s*(\d+)\s*$")


def _fs(tid: str) -> bool:
    """재무제표 본표(열이 당기 · 전기). 자본변동표는 열이 자본 항목이라 본표로 보지 않는다(dsd_ai._ref_of 와 같다). 「짝:」 앞머리는 떼고 본다."""
    tid = tid[len(PAIR_ID):] if tid.startswith(PAIR_ID) else tid
    return not tid.startswith("주석") and not tid.startswith("자본변동표")


def cell_name(t: Table, i: int, j: int, sign: int = 1) -> dict:
    """표의 i 번째 줄(0부터) · j 번째 열을 이름 칸으로. 재무제표 본표의 기간 열은 「당기」 · 「전기」 로 적는다."""
    row, rn = _ref(_labels(t), i)
    if _fs(t.id) and j == period_col(t, "당기"):
        col, cn = "당기", 1
    elif _fs(t.id) and j == period_col(t, "전기"):
        col, cn = "전기", 1
    else:
        col, cn = _ref(t.header, j)
    out = {"table": t.id, "row": row, "col": col}
    if rn != 1:
        out["row_nth"] = rn
    if cn != 1:
        out["col_nth"] = cn
    if sign < 0:
        out["sign"] = -1
    return out


def _table(doc: Doc, tid: str, where: str, problems: list[str]) -> Table | None:
    if tid.startswith(PAIR_ID):                       # 함께 낸 보고서의 칸: foot --links … --pair 로 넣으면 그 보고서의 번호로 푼다(2026-10-23)
        other = getattr(doc, "_pair", None)
        q = other.table(tid[len(PAIR_ID):]) if other is not None else None
        if other is None:
            problems.append(f"{where}: 함께 낸 보고서(짝:)의 칸을 번호로 적으려면 foot --links 에 --pair 를 함께 주거나 이름으로 적어 주십시오")
            return None
        if q is None:
            problems.append(f"{where}: 함께 낸 보고서에 「{tid[len(PAIR_ID):]}」 표가 없습니다")
            return None
        import copy

        q = copy.copy(q)
        q.id = PAIR_ID + q.id
        return q
    t = doc.table(tid)
    if t is None:
        problems.append(f"{where}: 「{tid}」 표가 없습니다")
    return t


def _row_index(t: Table, r: int, where: str, problems: list[str]) -> int | None:
    if not 1 <= r <= len(t.rows):
        problems.append(f"{where}: 「{t.id}」 에 {r}번째 줄이 없습니다(줄 번호는 1~{len(t.rows)})")
        return None
    return r - 1


def _col_index(t: Table, c: int, where: str, problems: list[str]) -> int | None:
    if not 1 <= c < len(t.header):
        problems.append(f"{where}: 「{t.id}」 에 {c}번째 열이 없습니다(열 번호는 1~{len(t.header) - 1})")
        return None
    return c


def cell(doc: Doc, x, where: str, problems: list[str]):
    """칸 하나. 「표:줄:열」 글이나 {table, row: 정수, col: 정수} 를 이름 칸으로 바꾼다. 이름 칸은 그대로 둔다."""
    if isinstance(x, str):
        m = _CELL.match(x)
        if not m:
            problems.append(f"{where}: 칸 「{x}」 은 「표:줄:열」(예: 주석5-1:2:1) 로 적어 주십시오")
            return None
        sign, tid, r, c = m.group(1), m.group(2), int(m.group(3)), int(m.group(4))
        t = _table(doc, tid, where, problems)
        if t is None:
            return None
        i, j = _row_index(t, r, where, problems), _col_index(t, c, where, problems)
        return None if i is None or j is None else cell_name(t, i, j, -1 if sign else 1)
    if isinstance(x, dict) and (_int(x.get("row")) or _int(x.get("col"))):
        t = _table(doc, str(x.get("table", "")), where, problems)
        if t is None:
            return None
        out = {k: v for k, v in x.items() if k not in ("row", "col", "row_nth", "col_nth")}
        if _int(x.get("row")):
            i = _row_index(t, x["row"], where, problems)
            if i is None:
                return None
            out["row"], rn = _ref(_labels(t), i)
            if rn != 1:
                out["row_nth"] = rn
        else:
            out["row"] = x.get("row")
            if x.get("row_nth"):
                out["row_nth"] = x["row_nth"]
        if _int(x.get("col")):
            j = _col_index(t, x["col"], where, problems)
            if j is None:
                return None
            named = cell_name(t, 0, j) if t.rows else {"col": _ref(t.header, j)[0]}
            out["col"] = named["col"]
            if named.get("col_nth"):
                out["col_nth"] = named["col_nth"]
        else:
            out["col"] = x.get("col")
            if x.get("col_nth"):
                out["col_nth"] = x["col_nth"]
        return out
    return x


def _int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _cells(doc: Doc, xs, where: str, problems: list[str]) -> list:
    xs = xs if isinstance(xs, list) else [xs]
    return [cell(doc, x, f"{where} {k + 1}번째 칸", problems) for k, x in enumerate(xs)]


def _line(t: Table, v, axis: str, where: str, problems: list[str]):
    """합계 구조의 줄(axis v) · 열(axis h) 하나. 정수면 번호(음수면 빼는 항), {"row": 번호, "sign": -1} 도 받는다(10-23 한 상장사 재기에서
    이 꼴을 풀지 못해 한 번 다시 넣었다). 그 밖은 그대로 둔다. (이름, 순번, 부호) 또는 원래 값."""
    key = "row" if axis == "v" else "col"
    if isinstance(v, dict) and _int(v.get(key)):
        got = _line(t, v[key], axis, where, problems)
        if got is not None and (v.get("sign", 1) < 0 or v[key] < 0):
            got["sign"] = -1
        return got
    if not _int(v):
        return v
    names = _labels(t) if axis == "v" else t.header
    k = abs(v)
    if axis == "v":
        i = _row_index(t, k, where, problems)
    else:
        i = _col_index(t, k, where, problems)
    if i is None:
        return None
    name, nth = _ref(names, i)
    key = "row" if axis == "v" else "col"
    return {key: name, "nth": nth, **({"sign": -1} if v < 0 else {})}


def _sum(doc: Doc, x: dict, where: str, problems: list[str], kind: str) -> dict | None:
    if not isinstance(x, dict):
        return x
    t = doc.table(str(x.get("table", "")))
    if t is None:
        return x                                       # 표가 없다는 문제는 dsd_ai._sums_of 가 적는다
    axis = "h" if "total_col" in x else "v"
    tk = "total_col" if axis == "h" else "total"
    y = dict(x)
    if _int(x.get(tk)):
        got = _line(t, x[tk], axis, f"{where} 합계 {'열' if axis == 'h' else '줄'}", problems)
        if got is None:
            return None
        y[tk], y["total_nth"] = got["row" if axis == "v" else "col"], got["nth"]
    ik = "cols" if axis == "h" else "rows"
    if isinstance(x.get(ik), list):
        items = [_line(t, v, axis, f"{where} 항", problems) for v in x[ik]]
        if any(v is None for v in items):
            return None
        y[ik] = items
    for k in ("from", "to"):
        if _int(x.get(k)):
            got = _line(t, abs(x[k]), axis, f"{where} {k}", problems)
            if got is None:
                return None
            got.pop("sign", None)
            y[k] = got
    other = "h" if axis == "v" else "v"                # skip · only 는 합계 줄이면 열 이름, 합계 열이면 줄 이름이다
    for k in ("skip", "only"):
        if isinstance(x.get(k), list) and any(_int(v) for v in x[k]):
            names = []
            for v in x[k]:
                got = _line(t, abs(v), other, f"{where} {k}", problems) if _int(v) else v
                if got is None:
                    return None
                names.append(got["row" if other == "v" else "col"] if isinstance(got, dict) else got)
            y[k] = names
    return y


def column_periods(doc: Doc, t: Table) -> dict[int, str]:
    """주석 표의 열마다 기간(당기 · 전기). 열 이름의 「당기 · 당반기 · 당분기 · 전기 · 전반기 · 전분기」, 없으면 기수(재무상태표 당기 기수와
    같으면 당기, 하나 작으면 전기)로 정한다. 숫자가 있는 열만 본다. 못 정한 열은 넣지 않는다."""
    cur = None
    for name in STATEMENTS:
        s = doc.table(name)
        j = period_col(s, "당기") if s is not None else None
        if j is not None and term_of(s.header[j]) is not None:
            cur = term_of(s.header[j])
            break
    out = {}
    for j in range(1, len(t.header)):
        if not any(_isnum(r[j]) for r in t.nums) or is_rate(t.header[j]):
            continue
        h = norm(t.header[j])
        if re.search(r"당(기|반기|분기)", h):
            out[j] = "당기"
        elif re.search(r"전(기|반기|분기)", h) and "전기이월" not in h:
            out[j] = "전기"
        elif cur is not None and term_of(t.header[j]) in (cur, cur - 1):
            out[j] = "당기" if term_of(t.header[j]) == cur else "전기"
    return out


def _item_rows(doc: Doc, v, where: str, problems: list[str]) -> list[tuple[Table, int, int]] | None:
    """설명하는 과목: 재무제표 본표의 줄 「재무상태표:12」(빼는 과목은 「-재무상태표:13」) 하나나 목록. (표, 줄, 부호)."""
    out = []
    for k, x in enumerate(v if isinstance(v, list) else [v]):
        m = _ROW.match(str(x)) if isinstance(x, str) else None
        if not m:
            problems.append(f"{where} item {k + 1}번째: 과목은 「재무상태표:12」 처럼 재무제표 표와 줄 번호로 적어 주십시오")
            return None
        t = _table(doc, m.group(2), where, problems)
        if t is None:
            return None
        if not _fs(t.id):
            problems.append(f"{where} item: 「{t.id}」 는 재무제표 본표가 아닙니다. 주석끼리는 links 로 적어 주십시오")
            return None
        i = _row_index(t, int(m.group(3)), where, problems)
        if i is None:
            return None
        out.append((t, i, -1 if m.group(1) else 1))
    return out


def _detail(label: str) -> bool:
    s = str(label).strip()
    return s.startswith(("-", "－")) or s.startswith(("(차감", "차감", "(가산", "가산"))


def _block_sum(doc: Doc, t: Table, total: int, start: int | None, kind: str, basis: str) -> dict | None:
    """표 한 줄의 합계 줄(변동이면 기말 줄)에 엔진 · AI 구조가 없을 때 더할 합계 구조. 구성 · 범주 · 만기 · 일부는 바로 앞 합계 줄 뒤부터
    합계 줄 앞까지, 변동은 기초 줄부터 기말 줄 앞까지 더한다. 그 사이에 소계 · 합계 줄이나 「- 」 · 「차감」 으로 시작하는 줄이 있으면 만들지 않는다
    (어느 줄을 더하는지 표만으로 정할 수 없어 AI 가 sums 로 적는다). 감소 · 처분 같은 이름의 줄은 양수로 적혀 있으면 뺀다(괄호로 적은 줄은 그대로 더한다)."""
    labels = _labels(t)
    if kind == "변동":
        if start is None or start >= total:
            return None
        items = list(range(start, total))
    else:
        prev = max((k for k in range(total) if total_kind(labels[k])), default=-1)
        items = list(range(prev + 1, total))
    items = [k for k in items if any(_isnum(v) for v in t.nums[k][1:]) and not is_rate(labels[k])]
    if not items or any(total_kind(labels[k]) or _detail(labels[k]) for k in items):
        return None
    signs = []
    for k in items:
        vals = [v for v in t.nums[k][1:] if _isnum(v) and v]
        down = kind == "변동" and k != start and any(w in norm(labels[k]) for w in DECREASE)
        signs.append(-1 if down and vals and sum(1 for v in vals if v > 0) > len(vals) / 2 else 1)
    tn, tnth = _ref(labels, total)
    return {"table": t.id, "total": tn, "total_nth": tnth,
            "rows": [{"row": _ref(labels, k)[0], "nth": _ref(labels, k)[1], **({"sign": -1} if g < 0 else {})} for k, g in zip(items, signs)],
            "basis": f"{basis} (표 한 줄 「{kind}」: {'기말 = 기초 + 변동' if kind == '변동' else '합계 = 위 줄의 합'})"}


def tables(doc: Doc, patch: dict, problems: list[str]) -> tuple[list[dict], list[dict], list[str]]:
    """표 한 줄(tables)을 연결과 합계 구조로 푼다. (연결, 합계 구조, 알림)."""
    links, sums, notes = [], [], []
    have = {(x.get("table"), str(x.get("total", x.get("total_col", "")))) for x in patch.get("sums") or [] if isinstance(x, dict)}
    for n, x in enumerate(patch.get("tables") or [], 1):
        where = f"tables {n}번째"
        if not isinstance(x, dict):
            problems.append(f"{where}: {{table, kind, total, item, basis}} 꼴로 적어 주십시오")
            continue
        t = _table(doc, str(x.get("table", "")), where, problems)
        if t is None:
            continue
        kind, basis = str(x.get("kind") or "").strip(), str(x.get("basis") or "").strip()
        if kind not in KINDS:
            problems.append(f"{where}: kind 는 {' · '.join(KINDS)} 가운데 하나로 적어 주십시오")
            continue
        if not basis:
            problems.append(f"{where}: 근거(basis)를 한 줄 적어 주십시오")
            continue
        if kind == "변동":
            close, start = x.get("close"), x.get("open")
            if not _int(close) or (start is not None and not _int(start)):
                problems.append(f"{where}: 변동표는 close(기말 줄 번호)와 open(기초 줄 번호)을 적어 주십시오")
                continue
            ci = _row_index(t, close, where, problems)
            oi = _row_index(t, start, where, problems) if start is not None else None
            if ci is None or (start is not None and oi is None):
                continue
            main = ci
        else:
            total = x.get("total")
            if total is not None and not _int(total):
                problems.append(f"{where}: total 은 합계 줄 번호로 적어 주십시오")
                continue
            main = _row_index(t, total, where, problems) if total is not None else None
            oi = None
            if total is not None and main is None:
                continue
            if main is None and not x.get("each"):
                problems.append(f"{where}: total(합계 줄 번호)이나 each({{줄: 과목}})를 적어 주십시오")
                continue
        targets = []                                   # (왼쪽 줄, 과목 줄들, 기간을 바꿔 잇는지)
        if main is not None and x.get("item") is not None:
            items = _item_rows(doc, x["item"], where, problems)
            if items is None:
                continue
            targets.append((main, items, False))
            if kind == "변동" and oi is not None:
                targets.append((oi, items, True))
        for r, v in (x.get("each") or {}).items():
            if not str(r).strip().isdigit():
                problems.append(f"{where}: each 의 열쇠는 줄 번호로 적어 주십시오")
                targets = None
                break
            i = _row_index(t, int(r), where, problems)
            items = _item_rows(doc, v, where, problems)
            if i is None or items is None:
                targets = None
                break
            targets.append((i, items, False))
        if targets is None:
            continue
        cols = {}
        if targets:                                    # 기간 열은 연결을 만들 때만 정한다(합계 구조만 원하는 줄은 없어도 된다)
            if x.get("cols"):
                raw = x["cols"].items() if isinstance(x["cols"], dict) else [tuple(v) for v in x["cols"]]
                cols = {}
                for c, p in raw:
                    j = _col_index(t, int(c), where, problems) if str(c).strip().lstrip("-").isdigit() else None
                    if j is None or p not in ("당기", "전기"):
                        problems.append(f"{where}: cols 는 {{열 번호: \"당기\" | \"전기\"}} 로 적어 주십시오")
                        cols = None
                        break
                    cols[j] = p
                if cols is None:
                    continue
            elif x.get("period"):
                if x["period"] not in ("당기", "전기") or not _int(x.get("col")):
                    problems.append(f"{where}: period(당기 · 전기)를 적으면 col(그 기간의 합계 열 번호)도 적어 주십시오")
                    continue
                j = _col_index(t, x["col"], where, problems)
                if j is None:
                    continue
                cols = {j: x["period"]}
            else:
                cols = column_periods(doc, t)
                if not cols:
                    problems.append(f"{where}: 「{t.id}」 의 열 이름으로 기간을 정하지 못했습니다. cols({{열: 당기 | 전기}})나 period · col 을 적어 주십시오")
                    continue
        extra = {k: x[k] for k in ("grade", "when", "usual") if str(x.get(k) or "").strip()}
        if kind == "일부":
            extra["cmp"] = "le"
        made = 0
        for j, p in sorted(cols.items()):
            for i, items, opening in targets:
                if opening and p != "당기":             # 전기 표의 기초는 전전기라 보고서에 맞춰 볼 곳이 없다
                    continue
                period = "전기" if opening else p
                if not _isnum(t.nums[i][j]):
                    continue
                right = []
                for q, k, g in items:
                    jj = period_col(q, period)
                    if jj is None:
                        break
                    right.append(cell_name(q, k, jj, g))
                if len(right) != len(items):
                    continue
                links.append({"left": cell_name(t, i, j), "right": right, "basis": f"{basis} (표 한 줄 「{kind}」)", **extra})
                made += 1
        if x.get("sums", True) is not False and main is not None:
            tn = _ref(_labels(t), main)[0]
            engine = {tuple(v["total"]) for v in detect(t)["vsum"]}
            if (t.id, tn) not in have and (t.id, str(main + 1)) not in have and tuple(_ref(_labels(t), main)) not in engine:
                s = _block_sum(doc, t, main, oi, kind, basis)
                if s is not None:
                    sums.append(s)
                    have.add((t.id, tn))
                else:
                    notes.append(f"{where} {t.id} 「{tn}」: 표 안에 소계 · 「- 」 · 「차감」 줄이 있어 합계 구조를 만들지 않았습니다. 필요하면 sums 로 적어 주십시오")
        if not made and (x.get("item") is not None or x.get("each")):
            notes.append(f"{where} {t.id}: 기간 열에 숫자가 있는 칸이 없어 연결을 만들지 않았습니다")
    return links, sums, notes


def normalize(doc: Doc, patch: dict, other: Doc | None = None) -> tuple[dict, list[str], list[str]]:
    """연결.json 의 번호 칸을 이름 칸으로 바꾸고 표 한 줄을 연결 · 합계 구조로 푼다. (새 patch, 문제, 알림). 이름으로 적은 것은 그대로 둔다.
    other 는 함께 낸 보고서(--pair)다. 주면 「짝:주석18-1:3:1」 처럼 그 보고서의 번호로 적은 칸도 푼다."""
    doc._pair = other
    try:
        return _normalize(doc, patch)
    finally:
        doc._pair = None


def _normalize(doc: Doc, patch: dict) -> tuple[dict, list[str], list[str]]:
    problems: list[str] = []
    out = dict(patch)
    links = []
    for n, x in enumerate(patch.get("links") or [], 1):
        if not isinstance(x, dict):
            links.append(x)
            continue
        y = dict(x)
        if "left" in x:
            y["left"] = cell(doc, x["left"], f"{n}번째 연결 left", problems)
        if "right" in x:
            y["right"] = _cells(doc, x["right"], f"{n}번째 연결 right", problems)
        links.append(y)
    calcs = []
    for n, x in enumerate(patch.get("calcs") or [], 1):
        if not isinstance(x, dict):
            calcs.append(x)
            continue
        y = dict(x)
        if "left" in x:
            y["left"] = cell(doc, x["left"], f"calcs {n}번째 left", problems)
        if isinstance(x.get("vars"), dict):
            y["vars"] = {k: cell(doc, v, f"calcs {n}번째 vars {k}", problems) for k, v in x["vars"].items()}
        calcs.append(y)
    props = patch.get("proposals")
    if isinstance(props, dict):
        props = dict(props)
        edits = []
        for n, e in enumerate(props.get("고침") or props.get("edit") or [], 1):
            if isinstance(e, dict):
                e = dict(e)
                if "left" in e:
                    e["left"] = cell(doc, e["left"], f"proposals 고침 {n}번째 left", problems)
                if "right" in e:
                    e["right"] = _cells(doc, e["right"], f"proposals 고침 {n}번째 right", problems)
            edits.append(e)
        if edits:
            props["고침"] = edits
            props.pop("edit", None)
        out["proposals"] = props
    finds = []
    for n, x in enumerate(patch.get("findings") or [], 1):
        if isinstance(x, dict):
            x = dict(x)
            if x.get("fix") is not None:
                x["fix"] = cell(doc, x["fix"], f"findings {n}번째 fix", problems)
            if isinstance(x.get("evidence"), list):
                x["evidence"] = [e if isinstance(e, dict) and str(e.get("table", "")).startswith(("작년:", "조서:", PAIR_ID))
                                 else cell(doc, e, f"findings {n}번째 evidence", problems) for e in x["evidence"]]
        finds.append(x)
    for key in ("sums", "no_sums"):
        got = []
        for n, x in enumerate(patch.get(key) or [], 1):
            got.append(_sum(doc, x, f"{key} {n}번째", problems, key))
        if patch.get(key) is not None:
            out[key] = [x for x in got if x is not None]
    wps = []
    for n, x in enumerate(patch.get("workpapers") or [], 1):
        if isinstance(x, dict) and isinstance(x.get("rows"), list) and any(_int(r) for r in x["rows"]):
            t = doc.table(str(x.get("table", "")))
            if t is not None:
                rows = []
                for r in x["rows"]:
                    if _int(r):
                        i = _row_index(t, r, f"workpapers {n}번째", problems)
                        if i is None:
                            continue
                        name, nth = _ref(_labels(t), i)
                        rows.append(name if nth == 1 else {"row": name, "row_nth": nth})
                    else:
                        rows.append(r)
                x = dict(x, rows=rows)
        wps.append(x)
    pairs = []
    for n, x in enumerate(patch.get("prior_pairs") or [], 1):
        if isinstance(x, dict) and _int(x.get("row")):
            t = doc.table(str(x.get("table", "")))
            i = _row_index(t, x["row"], f"prior_pairs {n}번째", problems) if t is not None else None
            if i is not None:
                name, nth = _ref(_labels(t), i)
                x = dict(x, row=name, **({"row_nth": nth} if nth != 1 else {}))
        pairs.append(x)
    for key, got in (("links", links), ("calcs", calcs), ("findings", finds), ("workpapers", wps), ("prior_pairs", pairs)):
        if patch.get(key) is not None:
            out[key] = got
    notes: list[str] = []
    if patch.get("tables"):
        more, sums, notes = tables(doc, dict(out), problems)
        out["links"] = list(out.get("links") or []) + more
        out["sums"] = list(out.get("sums") or []) + sums
        notes.insert(0, f"표 한 줄 {len(patch['tables'])}개 → 연결 {len(more)} · 합계 구조 {len(sums)}")
    out.pop("tables", None)
    return out, problems, notes
