"""DSD 푸팅: 판 비교와 숫자 레퍼 체크를 브라우저에서 보는 HTML 한 파일(2026-10-26, 설계 docs/specs/2026-10-26-감사-DSD푸팅-HTML보기-design.md).

  build(doc, checks, pdoc, m, old_checks, extra) -> dict      dsd_보기.json 에 쓰는 자료
  render(data, out) -> Path                                   템플릿 dsd_view.html 에 자료를 넣은 한 파일
  write(out_dir, data, mask) -> {json, html, size, warnings}
  read_marks(folder) / merge_marks(...)                       HTML 에서 내려받은 확인_<이름>.json 을 foot 이 엑셀 확인 칸과 함께 읽는다

엑셀 조서가 정본이다. 이 화면은 엔진 결과를 그리기만 한다. 바뀐 칸 · 차이 금액 · 검증 결과는 엔진이 계산해 자료에 싣고,
템플릿은 숫자를 계산하지 않는다(천 단위 쉼표 같은 표시만 한다). 감사의견이나 결론 문구를 만들지 않는다.
HTML 은 바깥 주소를 부르지 않는다(고객 자료가 든 파일을 열 때 밖으로 요청이 나가지 않게).
"""
from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

from . import dsd_compare, dsd_links
from .dsd_grid import Doc, Table

TEMPLATE = Path(__file__).with_name("dsd_view.html")
DATA_FILE = "dsd_보기.json"
LIMIT = 15 * 1024 * 1024                      # ui/export.py 와 같은 한도
MARK_GLOB = "확인_*.json"
GROUPS = ("합계", "레퍼", "전기")
_SLOT = "/*DSD_VIEW_DATA*/{}"


class MaskError(Exception):
    """치환 뒤에도 치환표 check 에 걸리는 글이 남았다(HTML 을 만들지 않는다)."""


def html_name(stem: str) -> str:
    return f"DSD보기_{stem}.html"


def _engine() -> str:
    try:
        r = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=Path(__file__).parent, capture_output=True, text=True, timeout=5)
        return r.stdout.strip() if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def cell_state(c) -> str:
    """검증 하나의 화면 상태. x(뺌) · false · 확인 · 단수 · ok · 없음(계산 못 함)."""
    if c.excluded or c.dropped:
        return "x"
    if dsd_links.failed(c):
        return "false"
    if dsd_links.asks(c):
        return "확인"
    if c.minor:
        return "단수"
    if c.ok is True:
        return "ok"
    return "없음"


_RANK = {"false": 4, "확인": 3, "단수": 2, "ok": 1, "없음": 0, "x": -1}


def _num(v):
    if v is None or isinstance(v, bool):
        return v
    f = float(v)
    return int(f) if f.is_integer() else round(f, 6)


def _table(t: Table) -> dict:
    return {"type": "t", "id": t.id, "caption": t.caption, "unit": t.unit, "kind": t.kind, "header": list(t.header),
            "rows": [list(r) for r in t.rows], "cells": {}, "rowmark": {}}


def _tabs(doc: Doc, others: dict | None) -> dict:
    tabs = {t.id: t for t in doc.tables()}
    for pre, d in (others or {}).items():
        if d is not None:
            tabs.update({pre + t.id: t for t in d.tables()})
    return tabs


def _cell_name(tabs: dict, part_of: dict, tid: str, r: int, c: int) -> str:
    t = tabs.get(tid)
    if t is None:
        return f"{tid} {r}·{c}"
    row = (t.labels or [x[0] for x in t.rows])[r] if 0 <= r < len(t.rows) else ""
    col = t.header[c] if 0 <= c < len(t.header) else ""
    where = part_of.get(tid, tid)
    return f"{where} {row.strip()} · {col.strip()}".strip()


def _check_json(c, tabs: dict, part_of: dict, before: dict) -> dict:
    terms = []
    for t, r, k, sg in c.terms:
        tab = tabs.get(t)
        v = tab.nums[r][k] if tab is not None and 0 <= r < len(tab.nums) and 0 <= k < len(tab.header) else None
        terms.append({"name": _cell_name(tabs, part_of, t, r, k), "v": _num(v), "sign": _num(sg),
                      "loc": [t, r, k] if t in part_of and r >= 0 else None})
    diff = None if c.left is None or c.right is None else _num(c.left - c.right)
    return {"g": c.group, "k": c.kind, "label": c.label, "t": c.table, "r": c.r, "c": c.c, "part": part_of.get(c.table, ""),
            "name": _cell_name(tabs, part_of, c.table, c.r, c.c), "left": _num(c.left), "right": _num(c.right), "diff": diff,
            "st": cell_state(c), "terms": terms, "expr": c.expr, "when": c.when, "cmp": c.cmp, "finding": c.finding, "usual": c.usual,
            "unit": _num(c.unit), "before": before.get(c.id, ""), "mark": "X" if c.excluded else ("O" if c.confirmed else ""),
            "dropped": c.dropped, "fix": c.fix_note, "verified": c.verified, "hints": [h.get("text", "") for h in (c.hints or [])][:3],
            "source": c.source, "basis": c.basis,
            # 판정이 고치라고 한 칸과 맞는 숫자(그 칸의 표시 단위). 화면의 「수정」 단추가 이 칸을 고친다(2026-11-04)
            "fixcell": list(c.fix_cell) if c.fix_cell is not None and c.fix_cell[0] in part_of and c.correct is not None else None,
            "correct": _num(c.correct) if c.correct is not None else None}


def _align(n_items: list, o_items: list, pair_of: dict) -> list[tuple]:
    """새 항목과 옛 항목을 한 줄씩 나란히 놓는다. pair_of 는 새 항목 번호 → 옛 항목 번호. 짝 없는 옛 항목은 그 앞 짝 뒤에 끼운다."""
    used = set(pair_of.values())
    out, j = [], 0
    for i in range(len(n_items)):
        k = pair_of.get(i)
        if k is not None:
            while j < k:
                if j not in used:
                    out.append((None, j))
                j += 1
            j = max(j, k + 1)
        out.append((i, k))
    for jj in range(len(o_items)):
        if jj not in used and jj >= j:
            out.append((None, jj))
    return out


def build(doc: Doc, checks: list, pdoc: Doc | None = None, m=None, old_checks: list | None = None, extra: dict | None = None) -> dict:
    """HTML 보기 자료. extra: {others: {앞머리: 문서}(작년 · 정산표 · 짝 보고서), text: 문장 검토 결과, prior, wtb, pair: 파일 이름,
    diff: dsd_versions_view.build 의 parts · changes · summary(2026-11-04. 있으면 판 비교 화면을 이것으로 그린다),
    workpapers: 연결 정의의 조서와 맞출 숫자(2026-11-04. 숫자 검증 화면의 하늘색 칸 · 검증 범위 수)}"""
    extra = extra or {}
    tabs = _tabs(doc, extra.get("others"))
    part_of = {t.id: p.key for p in doc.parts for x in p.items if x[0] == "t" for t in [x[1]]}
    before = {}
    if pdoc is not None and old_checks is not None:
        from .dsd_book import check_changes

        before = {c.id: what for c, what, _, _ in check_changes(checks, old_checks, m)}
    cj = {c.id: _check_json(c, tabs, part_of, before) for c in checks}
    # 검증 범위(2026-11-04): 엑셀 「검증 범위」 시트와 같은 셈. 숫자 칸(0 이 아닌 금액, % 칸 제외) 가운데 어느 검증에도 들어가지 않은 칸은
    # 조서와 맞출 칸(wp, 하늘색)과 검증 없는 칸(none, 회색)으로 나눈다. 검증 없는 칸이 빠진 합계 · 레퍼를 찾는 곳이다
    from .dsd_book import _money_cells, wp_cells

    cover = dsd_links.covered(checks)
    wpc = wp_cells(doc, extra.get("workpapers") or [])
    gap = {}
    for p in doc.parts:
        for k in _money_cells(p):
            if k not in cover:
                gap[k] = "wp" if k in wpc else "none"

    rows = dsd_compare.diff_rows(doc, pdoc, m) if pdoc is not None and m is not None else []
    changed_cells = {(x["table"], x["r"], x["c"]): x for x in rows if "table" in x and x["kind"] not in ("새 표", "새 줄")}
    new_rows = {(x["table"], x["r"]) for x in rows if x["kind"] in ("새 표", "새 줄")}
    old_changed = {(x["old_table"], x["old_r"], x["old_c"]): ("num" if x["kind"] == "숫자 바뀜" else "text") for x in rows if "old_table" in x}
    changed_paras = {(x["part"], x["item"]): x for x in rows if "item" in x}
    by_part: dict = {}
    for x in rows:
        by_part[x["part"]] = by_part.get(x["part"], 0) + x["n"]

    # 칸마다 걸린 검증
    on_cell: dict = {}
    for c in checks:
        cells = [(c.table, c.r, c.c)] + [(t, r, k) for t, r, k, _ in c.terms]
        for key in cells:
            if key[0] in part_of and key[1] >= 0:
                on_cell.setdefault(key, []).append(c.id)
        if any(k in changed_cells or (k[0], k[1]) in new_rows for k in cells):
            cj[c.id]["on_changed"] = True

    olds = {p.key: p for p in pdoc.parts} if pdoc is not None else {}
    parts = []
    for p in doc.parts:
        op = olds.get(m.parts.get(p.key)) if m is not None else None
        n_items = p.items
        o_items = op.items if op is not None else []
        pair_of = {}
        if op is not None:
            oidx = {x[1].id: j for j, x in enumerate(o_items) if x[0] == "t"}
            for i, x in enumerate(n_items):
                if x[0] == "p":
                    j = m.paras.get((p.key, i))
                elif m.tables.get(x[1].id):
                    j = oidx.get(m.tables[x[1].id][0])
                else:
                    j = None
                if j is not None:
                    pair_of[i] = j
        lines = []
        n_false = n_ask = 0
        for i, j in _align(n_items, o_items, pair_of):
            nx = n_items[i] if i is not None else None
            ox = o_items[j] if j is not None else None
            line = {"new": None, "old": None, "chg": ""}
            if nx is not None and nx[0] == "p":
                line["new"] = {"type": "p", "text": nx[1]}
                if op is not None:
                    cp = changed_paras.get((p.key, i))
                    if cp is not None and cp["kind"] == "새 문단":
                        line["chg"] = "new"
                    elif cp is not None:
                        line["chg"] = "text"
                        a, b = ox[1], nx[1]
                        line["ops"] = [list(o) for o in SequenceMatcher(None, a, b, autojunk=False).get_opcodes()]
            elif nx is not None:
                t = nx[1]
                tj = _table(t)
                mt = m.tables.get(t.id) if m is not None else None
                for r in range(len(t.rows)):
                    if op is not None and (t.id, r) in new_rows:
                        tj["rowmark"][r] = "new"
                        line["chg"] = line["chg"] or "cells"
                    for c in range(len(t.header)):
                        info = {}
                        x = changed_cells.get((t.id, r, c))
                        if x is not None:
                            info["chg"] = {"숫자 바뀜": "num", "새 열": "new"}.get(x["kind"], "text")
                            info["old"] = x["old"]
                            if x.get("diff") is not None:
                                info["diff"] = _num(x["diff"])
                            line["chg"] = line["chg"] or "cells"
                        g = gap.get((t.id, r, c))
                        if g:
                            info["gap"] = g
                        ids = on_cell.get((t.id, r, c))
                        if ids:
                            st = max((cj[k]["st"] for k in ids), key=lambda s: _RANK[s])
                            info["ck"] = ids
                            info["st"] = st
                            tot = [cj[k]["st"] for k in ids if cj[k]["g"] == "합계" and cj[k]["t"] == t.id and cj[k]["r"] == r and cj[k]["c"] == c]
                            if tot:
                                info["tot"] = max(tot, key=lambda s: _RANK[s])
                        if info:
                            tj["cells"][f"{r},{c}"] = info
                            if info.get("st") == "false" and "ck" in info:
                                n_false += 1
                            elif info.get("st") == "확인":
                                n_ask += 1
                line["new"] = tj
                if op is not None and mt is None:
                    line["chg"] = "new"
            if ox is not None:
                if ox[0] == "p":
                    line["old"] = {"type": "p", "text": ox[1]}
                else:
                    q = ox[1]
                    qj = _table(q)
                    mt = next((v for v in m.tables.values() if v[0] == q.id), None) if nx is not None and nx[0] == "t" else None
                    if mt is not None:
                        back_r = set(mt[1].values())
                        for r in range(len(q.rows)):
                            if r not in back_r:
                                qj["rowmark"][r] = "gone"
                        for (tid, orow, ocol), kind in old_changed.items():
                            if tid == q.id:
                                qj["cells"][f"{orow},{ocol}"] = {"chg": kind}
                    line["old"] = qj
                if nx is None:
                    line["chg"] = "gone"
            lines.append(line)
        parts.append({"key": p.key, "title": p.title, "old_key": op.key if op is not None else None, "old_title": op.title if op is not None else None,
                      "changes": by_part.get(p.key, 0), "false": n_false, "ask": n_ask, "lines": lines,
                      "gray": sum(1 for k, v in gap.items() if v == "none" and part_of.get(k[0]) == p.key),
                      "gone": list(m.gone.get(p.key, [])) if m is not None else []})

    live = [c for c in checks if not c.excluded and not c.dropped]
    summary = {}
    for g in GROUPS:
        cs = [c for c in live if c.group == g]
        summary[g] = {"n": len(cs), "false": sum(1 for c in cs if dsd_links.failed(c)), "확인": sum(1 for c in cs if dsd_links.asks(c)),
                      "단수": sum(1 for c in cs if c.minor)}
    money = sum(len(_money_cells(p)) for p in doc.parts)
    summary["검증 범위"] = {"숫자 칸": money, "검증된 칸": money - len(gap), "조서와 맞출 칸": sum(1 for v in gap.values() if v == "wp"),
                         "검증 없는 칸": sum(1 for v in gap.values() if v == "none")}
    if pdoc is not None:
        kinds: dict = {}
        for x in rows:
            k = "없어진 것" if x.get("gone") else x["kind"]
            kinds[k] = kinds.get(k, 0) + x["n"]
        summary["버전"] = {"바뀐 곳": sum(x["n"] for x in rows), **kinds}
        ch: dict = {}
        for w in before.values():
            ch[w] = ch.get(w, 0) + 1
        summary["검증 변화"] = ch
    text = extra.get("text")
    findings = []
    if text:
        from . import dsd_fix, dsd_text

        summary["문장"] = dsd_text.summary(text)
        # AI 가 엔진 지적과 같은 곳에 다른 안을 적은 S번호(11-04 한 회사 S209: 엔진 「옛 대표이사 이름 → 새 대표이사 이름」, AI 「주주 이름이라 고치지 않는다」).
        # 두 안이 엇갈리면 엔진 줄에는 단추를 내지 않는다. 회계사가 둘을 견줘 보고 정한다
        disputed = {x.get("seg") for x in text.get("ai", []) if x.get("rule") == "AI(엔진과 같은 곳)"}
        for x in text.get("engine", []) + [x for x in text.get("ai", []) if not x.get("same_as_engine")]:
            f = {k: x.get(k, "") for k in ("seg", "where", "kind", "quote", "fix", "basis", "by")}
            pair = dsd_fix.text_pair(x)                 # 「수정」 단추로 바로 고칠 수 있는 지적(찾을 글 → 바꿀 글). 할 일 · 메모를 적은 지적은 없다
            if pair and not (x.get("by") == "엔진" and x.get("seg") in disputed):
                f["old"], f["new"] = pair
            findings.append(f)
        for d in text.get("disclosures", []):
            if d.get("status") == "공시 안 됨":
                findings.append({"where": d.get("where", ""), "kind": "공시 안 됨", "quote": d.get("item", ""), "fix": "",
                                 "basis": d.get("basis", ""), "by": "AI"})
    changes = [{k: _num(v) if k in ("old", "new", "diff") and isinstance(v, (int, float)) else v for k, v in x.items()} for x in rows]
    more = {"diff": extra["diff"]} if extra.get("diff") else {}
    from . import dsd_fix

    stamp = dsd_fix.stamp_of(Path(extra["src"])) if extra.get("src") and Path(extra["src"]).suffix.lower() == ".dsd" else {}
    return {**more, "format": 1,
            "meta": {"new": doc.source and Path(doc.source).name, "old": Path(pdoc.source).name if pdoc is not None else "",
                     "sha256": {"new": doc.sha256, "old": pdoc.sha256 if pdoc is not None else ""},
                     # 수정판이면 원본 sha256 과 고침 수. 화면의 확인(O · X)을 원본 기준으로 이어 쓴다(2026-11-04)
                     "base": stamp.get("바탕", ""), "fixes": stamp.get(dsd_fix.STAMP, 0),
                     "made": datetime.now().strftime("%Y-%m-%d %H:%M"), "engine": _engine(), "masked": False,
                     "prior": extra.get("prior", ""), "wtb": extra.get("wtb", ""), "pair": extra.get("pair", "")},
            "summary": summary, "parts": parts, "gone_parts": list(m.gone_parts) if m is not None else [],
            "checks": cj, "changes": changes, "text": findings}


# ---------------------------------------------------------------- 이름 치환(--mask)
def _walk(x, f):
    if isinstance(x, str):
        return f(x)
    if isinstance(x, list):
        return [_walk(v, f) for v in x]
    if isinstance(x, dict):
        return {(f(k) if isinstance(k, str) else k): _walk(v, f) for k, v in x.items()}
    return x


def apply_mask(data: dict, rules: dict) -> dict:
    """치환표 {"subs": [[바꿀 말, 바꾼 말], …] 또는 {바꿀 말: 바꾼 말}, "check": [정규식, …]} 로 모든 글을 바꾼다.
    긴 말부터 바꾼다. 치환 뒤 check 에 걸리는 글이 하나라도 있으면 MaskError(audit-external-review 의 tools/sync_dsd.py 와 같은 방식).
    금액은 바꾸지 않는다. 치환한 판도 실제 회사 자료로 다룬다(설계 4.2)."""
    subs = rules.get("subs") or []
    pairs = list(subs.items()) if isinstance(subs, dict) else [tuple(x) for x in subs]
    pairs.sort(key=lambda kv: -len(kv[0]))

    def f(s: str) -> str:
        for a, b in pairs:
            if a:
                s = s.replace(a, b)
        return s

    out = _walk(data, f)
    pats = [re.compile(p) for p in rules.get("check") or []]
    left = []

    def scan(s: str) -> str:
        for p in pats:
            mm = p.search(s)
            if mm:
                left.append(mm.group(0))
        return s

    _walk(out, scan)
    if left:
        raise MaskError(f"치환 뒤에도 남은 이름 {len(left)}곳: {', '.join(sorted(set(left))[:5])}")
    out["meta"]["masked"] = True
    return out


# ---------------------------------------------------------------- 쓰기
def render(data: dict, out: Path) -> Path:
    tpl = TEMPLATE.read_text(encoding="utf-8")
    blob = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/").replace("<!--", "<\\u0021--")
    if _SLOT not in tpl:
        raise ValueError("템플릿에 자료 자리가 없습니다")
    html = tpl.replace(_SLOT, blob, 1)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return out


def _shrink(data: dict) -> dict:
    """바뀌지 않은 부분의 기존 판 원문을 뺀다(크기가 LIMIT 을 넘을 때). 판 비교 자료(diff)도 같다."""
    for p in data["parts"] + list((data.get("diff") or {}).get("parts") or []):
        if not p["changes"]:
            for line in p["lines"]:
                line["old"] = None
            p["old_omitted"] = True
    return data


def write(out_dir: Path, data: dict, stem: str, mask: dict | None = None) -> dict:
    """dsd_보기.json 과 DSD보기_<stem>.html 을 쓴다. mask 를 주면 치환한 자료로 둘 다 쓴다(이름 뒤에 _치환)."""
    out_dir = Path(out_dir)
    warnings = []
    suffix = ""
    if mask is not None:
        data = apply_mask(data, mask)
        suffix = "_치환"
    html = out_dir / html_name(stem + suffix)
    render(data, html)
    if html.stat().st_size > LIMIT:
        data = _shrink(data)
        render(data, html)
        warnings.append("파일이 커서 바뀌지 않은 부분의 기존 판 원문을 뺐습니다")
        if html.stat().st_size > LIMIT:
            warnings.append(f"기존 판 원문을 빼도 {LIMIT // 1_048_576}MB 를 넘습니다")
    js = out_dir / (DATA_FILE if not suffix else DATA_FILE.replace(".json", f"{suffix}.json"))
    js.write_text(json.dumps(data, ensure_ascii=False, indent=0), encoding="utf-8")
    return {"json": js, "html": html, "size": html.stat().st_size, "warnings": warnings}


# ---------------------------------------------------------------- 확인 왕복
def read_marks(path: Path) -> dict:
    """HTML 에서 내려받은 확인 json → {검증 id: {"excluded": True} | {"confirmed": True}}. 빈 표시는 넘기지 않는다."""
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    out = {}
    for cid, v in (d.get("marks") or {}).items():
        mk = str((v or {}).get("mark", "")).strip().upper()
        if mk == "X":
            out[cid] = {"excluded": True}
        elif mk == "O":
            out[cid] = {"confirmed": True}
    return out


def merge_marks(base: dict, folder: Path, xlsx_marks: list[tuple[Path, dict]]) -> tuple[dict, list[str]]:
    """엑셀 확인 칸과 HTML 확인을 파일 수정 시각 차례로 겹친다(나중 것이 이긴다). 엑셀과 HTML 이 다르게 적은 검증은 notes 에 한 줄씩."""
    srcs = [(p.stat().st_mtime, "엑셀", p, mk) for p, mk in xlsx_marks]
    for p in Path(folder).glob(MARK_GLOB):
        try:
            srcs.append((p.stat().st_mtime, "HTML", p, read_marks(p)))
        except (OSError, ValueError):
            continue
    srcs.sort(key=lambda x: x[0])
    out = dict(base)
    seen: dict = {}
    notes = []
    for _, kind, p, mk in srcs:
        for cid, v in mk.items():
            if cid in seen and seen[cid][0] != kind and seen[cid][1] != v:
                notes.append(f"{cid}: {seen[cid][0]} 확인과 {kind} 확인({p.name})이 달라 나중 것({kind})을 썼다")
            seen[cid] = (kind, v)
            out[cid] = v
    return out, notes
