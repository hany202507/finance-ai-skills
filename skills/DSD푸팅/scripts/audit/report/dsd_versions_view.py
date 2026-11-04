"""DSD 판 비교 HTML(2026-11-03). `python -m audit dsd diff <옛 판> <새 판> --html`.

dsd diff 의 판 비교 결과(dsd_versions.Result)를 푸팅 HTML 보기(dsd_view.html)와 같은 화면에 그린다. 푸팅은 돌리지 않는다.
엑셀(판비교_<옛>_<새>.xlsx)과 같은 셈이다. 바뀐 곳 목록은 엑셀 「바뀐 곳」 시트와 한 줄씩 같고, 위 띠의 수는 dsd_versions.totals 다.

  build(res) -> dict                                  dsd_view 와 같은 꼴의 자료(meta.mode 「diff」)
  write(out_dir, data, stem, mask) -> {html, size, warnings}

화면 표시
  추가(새 판에 더한 것)   연두. 새 줄 · 새 열 · 새 문단 · 새 표 · 새 부분
  삭제(새 판에서 뺀 것)   분홍. 기존 판 쪽 원래 있던 곳에 취소선
  변경(고친 것)           하늘색. 칸에 마우스를 올리면 기존 값 · 새 값 · 차이. 문단은 지운 글자 분홍 · 더한 글자 연두
  옮김 · 나뉨 · 합침     주황
바뀐 곳마다 go = [부분 차례, 줄 차례, 쪽(n 새 판 · o 기존 판), 표, 줄, 열] 을 붙여 목록에서 누르면 그 칸으로 간다.

화면은 엔진이 낸 바뀐 곳을 그리기만 한다. 차이 금액은 엔진 값이고, 판단 문구를 만들지 않는다. 바깥 주소를 부르지 않는다.
실제 회사 dsd 로 만든 HTML 은 결과 폴더에만 둔다(아티팩트 · 저장소에 올리지 않는다).
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

from . import dsd_versions as V
from . import dsd_view
from .dsd_versions import Change, PartDiff, Result

KEYS = ("추가", "삭제", "변경", "번호 바뀜", "옮김", "나뉨", "합침")
_LINE_RANK = {"new": 5, "gone": 5, "split": 4, "moved": 3, "text": 2, "cells": 1, "": 0}


def key_of(c: Change) -> str:
    """거르기 열쇠. 주석 번호만 바뀐 것은 엑셀 요약처럼 「번호 바뀜」 으로 따로 센다."""
    return "번호 바뀜" if c.unit == "번호" else c.kind


def _num(v):
    return dsd_view._num(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else v


def _item(x) -> dict:
    if x[0] == "p":
        return {"type": "p", "text": x[1]}
    t = dsd_view._table(x[1])
    t["headmark"], t["headold"] = {}, {}
    return t


def _set_chg(line: dict, chg: str) -> None:
    if _LINE_RANK[chg] > _LINE_RANK[line["chg"]]:
        line["chg"] = chg


def _cell(tab: dict, r: int, c: int, **info) -> None:
    tab["cells"].setdefault(f"{r},{c}", {}).update(info)


def _part(pi: int, pd: PartDiff, out_changes: list, lines_of: dict | None = None) -> dict:
    p = pd.new or pd.old
    whole = pd.new is None or pd.old is None
    lines: list[dict] = []
    n_line: dict[int, int] = {}
    o_line: dict[int, int] = {}
    if whole:                                         # 새 부분 · 없어진 부분은 한쪽에만 그린다
        q = V._clean(p)
        side = "new" if pd.old is None else "old"
        for k, x in enumerate(q.items):
            (n_line if side == "new" else o_line)[k] = len(lines)
            line = {"new": None, "old": None, "chg": "new" if side == "new" else "gone", "kinds": ["추가" if side == "new" else "삭제"]}
            line[side] = _item(x)
            lines.append(line)
    else:
        a, b = pd.new, pd.old                         # _part_diff 가 「문장」 표를 뺀 부분이다
        pair_of = dict(pd.paras)
        used_old = set(pair_of.values())
        for k in sorted(pd.tables):                   # 나뉨: 새 표 여럿이 옛 표 하나를 가리킨다. 옛 표는 첫 조각 옆에만 둔다
            j = pd.tables[k][0]
            if j not in used_old:
                pair_of[k] = j
                used_old.add(j)
        for i, j in dsd_view._align(a.items, b.items, pair_of):
            line = {"new": None, "old": None, "chg": "", "kinds": []}
            if i is not None:
                line["new"] = _item(a.items[i])
                n_line[i] = len(lines)
            if j is not None:
                line["old"] = _item(b.items[j])
                o_line[j] = len(lines)
            if i is not None and j is not None and a.items[i][0] == "p" and V._ws(a.items[i][1]) != V._ws(b.items[j][1]):
                line["ops"] = [list(o) for o in SequenceMatcher(None, b.items[j][1], a.items[i][1], autojunk=False).get_opcodes()]
            lines.append(line)

    def tab(li: int | None, side: str) -> dict | None:
        if li is None:
            return None
        it = lines[li]["new" if side == "n" else "old"]
        return it if it and it.get("type") == "t" else None

    notes, kinds = [], Counter()
    for c in pd.changes:
        k = key_of(c)
        kinds[k] += 1
        go = [pi, None, "n" if pd.new is not None else "o", None, None, None]
        _, item, r, col = c.anchor or (None, None, None, None)
        li = None
        if item is None:                              # 부분 전체(추가 · 삭제 · 옮김 · 번호 · 제목)
            if c.unit == "번호":
                notes.append({"k": k, "text": f"번호 바뀜: {c.old} → {c.new}"})
            elif c.unit == "제목":
                notes.append({"k": k, "text": f"제목 바뀜: 「{_short(c.old)}」 → 「{_short(c.new)}」" + (f" ({c.memo})" if c.memo else "")})
            elif c.kind == "옮김":
                notes.append({"k": k, "text": f"차례 옮김: {c.old} → {c.new}"})
            elif lines:                               # 새 부분 · 없어진 부분은 첫 줄로 간다(제목에 본문이 붙어 줄이 없으면 부분 머리로)
                go[1] = 0
        else:
            side, idx = item
            li = (n_line if side == "n" else o_line).get(idx)
            go[1], go[2] = li, side
        ln = lines[li] if li is not None else None
        if ln is not None and k not in ln["kinds"]:
            ln["kinds"].append(k)
        if ln is not None and item is not None:
            _mark(c, ln, go, pd, item, r, col, lines, n_line, o_line, tab)
        out_changes.append({"k": k, "kind": c.kind, "unit": c.unit, "part": c.part, "where": c.where, "old": _num(c.old), "new": _num(c.new),
                            "diff": _num(c.diff), "memo": c.memo, "go": go})
    if lines_of is not None:
        lines_of[pi] = (n_line, lines)
    return {"key": p.key, "title": p.title, "old_key": pd.old.key if pd.old is not None else None,
            "old_title": pd.old.title if pd.old is not None else None, "changes": len(pd.changes), "kinds": dict(kinds),
            "false": 0, "ask": 0, "lines": lines, "gone": [], "notes": notes,
            "state": "new" if pd.old is None else ("gone" if pd.new is None else "")}


def _short(v, n: int = 60) -> str:
    s = str(v if v is not None else "")
    return s if len(s) <= n else s[:n] + "…"


def _mark(c: Change, ln: dict, go: list, pd: PartDiff, item: tuple, r, col, lines: list, n_line: dict, o_line: dict, tab) -> None:
    """바뀐 곳 하나를 화면 자료에 표시하고 go 의 표 · 줄 · 열을 채운다."""
    side, idx = item
    li = go[1]
    if c.unit == "문단":
        _set_chg(ln, {"추가": "new", "삭제": "gone", "옮김": "moved"}.get(c.kind, "text"))
        return
    if c.unit == "표":
        if c.kind in ("나뉨", "합침"):
            _set_chg(ln, "split")
            for tid in [s.strip() for s in str(c.new).split(",")] + [s.strip() for s in str(c.old).split(",")]:
                for other in lines:
                    for sd in ("new", "old"):
                        it = other[sd]
                        if it and it.get("type") == "t" and it["id"] == tid:
                            _set_chg(other, "split")
                            if c.kind not in other["kinds"]:
                                other["kinds"].append(c.kind)
        else:
            _set_chg(ln, {"추가": "new", "삭제": "gone", "옮김": "moved"}[c.kind])
        t = tab(li, side)
        if t is not None:
            go[3:6] = [t["id"], -1, 0]
        return
    t = tab(li, side)
    if t is None:
        return
    pair = pd.tables.get(idx) if side == "n" else None
    o_li = o_line.get(pair[0]) if pair else None
    ot = tab(o_li, "o") if o_li is not None else None
    rows, cols = (pair[1], pair[2]) if pair else ({}, {})
    if c.unit == "칸":
        chg = "num" if c.diff is not None else "text"
        _cell(t, r, col, chg=chg, old=_num(c.old), **({"diff": _num(c.diff)} if c.diff is not None else {}))
        if ot is not None and r in rows and col in cols:
            _cell(ot, rows[r], cols[col], chg=chg)
        _set_chg(ln, "cells")
        go[3:6] = [t["id"], r, col]
    elif c.unit == "줄":
        if isinstance(r, tuple):                      # 없어진 줄: 기존 판 표의 그 줄
            if ot is not None:
                ot["rowmark"][r[1]] = "gone"
                if o_li is not None and "삭제" not in lines[o_li]["kinds"]:
                    lines[o_li]["kinds"].append("삭제")
                _set_chg(lines[o_li], "cells")
                go[1:6] = [o_li, "o", ot["id"], r[1], 0]
            else:
                go[3:6] = [t["id"], -1, 0]
            return
        if r is None or r < 0:                        # 나뉜 표 어디에도 없는 줄(줄 번호가 없다)
            go[3:6] = [t["id"], -1, 0]
            return
        if c.kind == "추가":
            t["rowmark"][r] = "new"
        elif c.kind == "옮김":
            t["rowmark"].setdefault(r, "moved")
        else:                                         # 줄 이름 바뀜
            _cell(t, r, 0, chg="text", old=_num(c.old))
            if ot is not None and r in rows:
                _cell(ot, rows[r], 0, chg="text")
        _set_chg(ln, "cells")
        go[3:6] = [t["id"], r, 0]
    elif c.unit == "열":
        if c.kind == "추가":
            t["headmark"][col] = "new"
            for i in range(len(t["rows"])):
                _cell(t, i, col, chg="new")
            go[3:6] = [t["id"], -1, col]
        elif ot is not None:                          # 없어진 열: 기존 판 표에서 짝 없는 열 가운데 이름이 맞는 것
            q = ot
            gone = [j for j in range(1, len(q["header"])) if j not in cols.values()]
            hit = next((j for j in gone if c.where == f"{q['id']} {q['header'][j] or f'{j + 1}번째 열'}"), gone[0] if gone else None)
            if hit is not None:
                q["headmark"][hit] = "gone"
                for i in range(len(q["rows"])):
                    _cell(q, i, hit, chg="gone")
                go[1:6] = [o_li, "o", q["id"], -1, hit]
        _set_chg(ln, "cells")
    elif c.unit == "머리줄":
        t["headmark"][col] = "chg"
        t["headold"][col] = _num(c.old)
        if ot is not None and col in cols:
            ot["headmark"][cols[col]] = "chg"
        _set_chg(ln, "cells")
        go[3:6] = [t["id"], -1, col]


def _leftovers(res: Result, lines_of: dict) -> list[dict]:
    """같이 고칠 곳 후보(2026-11-04)를 화면 자료로. go 는 바뀐 곳과 같은 꼴이고, 남은 칸에 left 표시를 단다."""
    at = {(pd.new or pd.old).key: pi for pi, pd in enumerate(res.parts) if pd.new is not None}
    out = []
    for x in res.leftovers:
        pi = at.get(x.part)
        go = [pi, None, "n", None, None, None]
        if pi is not None and x.anchor:
            n_line, lines = lines_of.get(pi, ({}, []))
            li = n_line.get(x.anchor[1][1])
            go[1] = li
            if li is not None and x.unit == "칸":
                t = lines[li]["new"]
                if t and t.get("type") == "t":
                    r, c = x.anchor[2], x.anchor[3]
                    go[3:6] = [t["id"], r, c]
                    info = t["cells"].setdefault(f"{r},{c}", {})
                    to = f" → {_num(x.new_value):,}" if x.new_value is not None else ""
                    info["left"] = f"같이 고칠 곳 후보: {x.changed} 의 {_num(x.value):,}{to} 를 고쳤는데 이 칸은 그대로다"
            elif li is not None:
                lines[li]["left"] = f"같이 고칠 곳 후보: {x.changed} 의 {_num(x.value):,} 를 고쳤는데 이 문단에는 그대로다"
        out.append({"part": x.part, "unit": x.unit, "where": x.where, "value": _num(x.value), "changed": x.changed,
                    "new_value": _num(x.new_value), "text": x.text, "go": go})
    return out


def build(res: Result) -> dict:
    changes: list = []
    lines_of: dict = {}
    parts = [_part(pi, pd, changes, lines_of) for pi, pd in enumerate(res.parts)]
    left = _leftovers(res, lines_of)
    tot = V.totals(res)
    rows = []
    for pi, (pd, row) in enumerate(zip(res.parts, V.summary_rows(res))):
        if pd.changes:
            rows.append({"p": pi, **{k: _num(v) for k, v in row.items()}})
    return {"format": 1,
            "meta": {"mode": "diff", "new": Path(res.new.source).name, "old": Path(res.old.source).name,
                     "sha256": {"new": res.new.sha256, "old": res.old.sha256},
                     "made": datetime.now().strftime("%Y-%m-%d %H:%M"), "engine": dsd_view._engine(), "masked": False},
            "summary": {"판 비교": {k: _num(v) for k, v in tot.items()}, "부분": rows, "keys": list(KEYS)},
            "parts": parts, "gone_parts": [], "checks": {}, "changes": changes, "leftovers": left, "text": []}


def write(out_dir: Path, data: dict, stem: str, mask: dict | None = None) -> dict:
    """<stem>.html 을 쓴다(stem 은 엑셀과 같은 판비교_<옛>_<새>). mask 를 주면 이름을 바꾼 <stem>_치환.html. 15MB 를 넘으면
    바뀌지 않은 부분의 기존 판 원문을 뺀다(dsd_view.write 와 같다)."""
    out_dir = Path(out_dir)
    warnings = []
    suffix = ""
    if mask is not None:
        data = dsd_view.apply_mask(data, mask)
        suffix = "_치환"
    html = out_dir / f"{stem}{suffix}.html"
    dsd_view.render(data, html)
    if html.stat().st_size > dsd_view.LIMIT:
        data = dsd_view._shrink(data)
        dsd_view.render(data, html)
        warnings.append("파일이 커서 바뀌지 않은 부분의 기존 판 원문을 뺐습니다")
        if html.stat().st_size > dsd_view.LIMIT:
            warnings.append(f"기존 판 원문을 빼도 {dsd_view.LIMIT // 1_048_576}MB 를 넘습니다")
    return {"html": html, "size": html.stat().st_size, "warnings": warnings}
