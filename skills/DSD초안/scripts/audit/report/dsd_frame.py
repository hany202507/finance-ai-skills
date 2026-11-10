"""틀로 쓰기(2026-10-26, DSD 네 기능 설계 3.2 의 A). 바탕이 공시 원문 xml 인 원고를 엔진 틀(dsd.write_dsd)로 dsd 를 만든다.

공시 xml 에는 편집기 요소(INSERTION · COMMENT · LIBRARYLIST · FILENAME)가 없어 바탕 고치기를 하지 않는다(편집기가 기본 틀을 띄웠다, 규격 6절).
원고의 글과 숫자를 블록으로 바꿔 틀(별도 감사보고서, 서식 00760)에 넣는다. 원문 서식은 남지 않는다.

  감사보고서 · 검토보고서 시트   → 「감사보고서」 블록(수신인 · 본문 · 서명 · 보고서일은 dsd.report_pieces 가 가른다)
  재무제표 시트                  → 재무제표 이름 제목과 표 [과목, 당기, 전기]. 주석 열은 빼고, 기간마다 내역 · 합계 두 칸은 값이 있는 칸 하나로
  주석 시트                      → 「N. 제목」 굵은 제목과 문단 · 표(제목과 본문이 한 문단이면 제목 뒤를 본문 문단으로)
  외부감사 실시내용              → 그대로 블록으로(틀의 기입 표는 엔진 기입란 꼴만 읽는다)
요약 코드는 채우지 않는다(작년 공시 값을 옮기지 않는다. 감사의견 구분은 8600 에서).
"""
from __future__ import annotations

import hashlib
import json
import re
import zipfile
from pathlib import Path

from .base import norm
from . import dsd, dsd_draft, dsd_draft_book as RB
from .dsd_draft import Cell, Line, Sheet
from .dsd_draft_book import issue, value_text


def apply_values(r: RB.Read) -> tuple[list[Sheet], list[dict]]:
    """원고 엑셀 값을 바탕 원고 줄에 얹은 시트 목록. 위치 번호가 없는 줄은 새 줄로, 엑셀에서 지운 줄은 뺀다."""
    orig = dsd_draft.from_raw(r.contents, r.meta, r.base)
    names = {RB._sheet_name(s.key): s for s in orig.sheets}
    excel = dict(r.sheets)
    toc = {t[0] for t in r.toc}
    issues = []
    out = []
    for name, s in names.items():
        if r.toc and name not in toc and s.kind == "주석":
            continue
        rl = excel.get(name)
        if rl is None:
            out.append(s)
            continue
        by = {}
        for ln in s.lines:
            if ln.loc is not None:
                by.setdefault(ln.loc, ln)
        lines = []
        for x in rl:
            ol = by.get(x.loc) if x.loc is not None else None
            if x.kind in ("표", "글 표"):
                lines.append(Line(x.kind, x.loc, [Cell(None, ol.cells[0].text if ol else "[표]")], tag="TABLE"))
                continue
            if x.kind == "표끝":
                lines.append(Line("표끝", None, []))
                continue
            cells = []
            for j, v in enumerate(x.values):
                text, num, note = value_text(v, x.cached[j] if j < len(x.cached) else None)
                oc = ol.cells[j] if ol is not None and j < len(ol.cells) else None
                if oc is not None and oc.covered:
                    cells.append(Cell(None, covered=True))
                    continue
                if note:
                    issues.append(issue("엑셀 손상", name, f"{RB.L(RB.C0 + j)}{x.row}", note))
                if num is not None:
                    cells.append(Cell(None, dsd_draft.format_num(num, oc.fmt if oc else None), num, oc.fmt if oc else None))
                else:
                    cells.append(Cell(None, text))
            lines.append(Line(x.kind, x.loc, cells))
        out.append(Sheet(s.key, s.title, s.kind, lines, s.note))
    return out, issues


def _tables(lines: list[Line]) -> list[tuple[int, int]]:
    out, i = [], 0
    while i < len(lines):
        if lines[i].kind in ("표", "글 표"):
            j = i + 1
            while j < len(lines) and lines[j].kind != "표끝":
                j += 1
            out.append((i, j))
            i = j
        i += 1
    return out


def _rows(lines: list[Line], a: int, b: int) -> list[list[str]]:
    return [[("" if c.covered else c.text) for c in ln.cells] for ln in lines[a + 1:b] if ln.kind in ("머리", "줄")]


def _flat(t: str) -> str:
    return re.sub(r"\s+", " ", str(t or "")).strip()


def fs_table(rows: list[list[str]]) -> list[list[str]]:
    """회사 재무제표 표 → 틀의 [과목, 당기, 전기]. 주석 열을 빼고, 머리줄 이름이 같은 열(기간마다 내역 · 합계)은 값이 있는 칸 하나로."""
    if not rows:
        return rows
    body_at = next((i for i, r in enumerate(rows) if any(dsd_draft.parse_num(x)[0] is not None for x in r[1:])), 1)
    head = rows[:max(body_at, 1)]
    width = max(len(r) for r in rows)
    names = []
    for j in range(width):
        parts = []
        for r in head:
            x = r[j] if j < len(r) else ""
            if not x and j > 0 and parts == [] and r[j - 1:j]:
                x = ""
            parts.append(x)
        names.append(" ".join(p for p in parts if p))
    # 병합된 머리 칸: 빈 이름은 왼쪽 이름을 따른다(COLSPAN 으로 덮인 칸)
    for j in range(1, width):
        if not names[j].strip():
            names[j] = names[j - 1]
    note_cols = {j for j in range(1, width) if "주석" in norm(names[j])}
    groups: list[list[int]] = []
    for j in range(1, width):
        if j in note_cols:
            continue
        if groups and norm(names[groups[-1][0]]) == norm(names[j]):
            groups[-1].append(j)
        else:
            groups.append([j])
    out = [[names[0] or "과 목"] + [names[g[0]] for g in groups]]
    for r in rows[len(head):]:
        r = list(r) + [""] * (width - len(r))
        vals = []
        for g in groups:
            xs = [r[j] for j in g if r[j].strip()]
            vals.append(xs[-1] if xs else "")
        out.append([dsd._label(_flat(r[0]))] + vals)
    return out


def blocks(sheets: list[Sheet]) -> list[tuple[str, list]]:
    parts: dict[str, list] = {"감사보고서": [], "(첨부) 재무제표": [], "주석": [], "외부감사 실시내용": []}
    for s in sheets:
        lines = s.lines
        tabs = _tables(lines)
        in_tab = {k for a, b in tabs for k in range(a, b + 1)}
        if s.kind == "재무제표":
            bl = parts["(첨부) 재무제표"]
            bl.append(("h", 2, s.key))
            main = max(tabs, key=lambda ab: sum(1 for ln in lines[ab[0] + 1:ab[1]] for c in ln.cells if c.num is not None), default=None)
            for k, ln in enumerate(lines):
                if k in in_tab:
                    if main and k == main[0]:
                        rows = _rows(lines, *main)
                        bl.append(("table", fs_table(rows) if s.key != "자본변동표" else _sce(rows)))
                    continue
                t = _flat(ln.cells[0].text) if ln.cells else ""
                if t and norm(t) != norm(s.key):
                    bl.append(("p", t))
            continue
        if s.kind in ("주석", "주석 머리"):
            bl = parts["주석"]
            for k, ln in enumerate(lines):
                if k in in_tab:
                    for a, b in tabs:
                        if k == a:
                            bl.append(("table", _rows(lines, a, b)))
                    continue
                t = _flat(ln.cells[0].text) if ln.cells else ""
                if not t:
                    continue
                if s.kind == "주석" and k == 0:
                    head = f"{s.note}. {s.title}"
                    bl.append(("h", 2, head))
                    m = re.match(rf"^\s*{s.note}\s*\.\s*", t)
                    rest = t[m.end():] if m else t
                    rest = rest[len(s.title):].strip() if rest.startswith(s.title) else rest
                    if rest:
                        bl.append(("p", rest))
                    continue
                bl.append(("p", t))
            continue
        key = "감사보고서" if s.key in ("감사보고서", "검토보고서") else ("외부감사 실시내용" if s.key.startswith("외부감사") else None)
        if key is None:
            continue
        bl = parts[key]
        for k, ln in enumerate(lines):
            if k in in_tab:
                for a, b in tabs:
                    if k == a:
                        rows = _rows(lines, a, b)
                        if lines[a].kind == "글 표" and key == "감사보고서":
                            bl += [("p", _flat(" ".join(x for x in r if x))) for r in rows if any(x.strip() for x in r)]
                        else:
                            bl.append(("table", rows))
                continue
            t = _flat(ln.cells[0].text) if ln.cells else ""
            if t:
                bl.append(("h", 2, t) if ln.kind == "제목" else ("p", t))
    return [(k, v) for k, v in parts.items()]


def _sce(rows: list[list[str]]) -> list[list[str]]:
    width = max(len(r) for r in rows)
    keep = [j for j in range(width) if not (j and "주석" in norm(rows[0][j] if j < len(rows[0]) else ""))]
    return [[(r[j] if j < len(r) else "") for j in keep] for r in rows]


def build(r: RB.Read, out: Path) -> dict:
    sheets, issues = apply_values(r)
    parts = blocks(sheets)
    info = r.info or {}
    end = str(info.get("period_end") or "")
    fye = f"{end[:4]}-{end[4:6]}-{end[6:8]}" if re.fullmatch(r"\d{8}", end) else ""
    meta = {"name": info.get("name") or "", "corp_code": "", "fiscal_year_end": fye, "fiscal_year_start": "", "term": info.get("term"),
            "ceo": None, "address": None, "phone": None, "auditor": None, "levels": {}, "summary": {}}
    tmp = Path(out).with_suffix(".tmp.dsd")
    dsd.write_dsd(tmp, parts, meta)
    with zipfile.ZipFile(tmp) as z:
        c, m = z.read("contents.xml"), z.read("meta.xml")
    tmp.unlink(missing_ok=True)
    from .dsd_build import STAMP, zip_dsd

    path = zip_dsd(Path(out), c, m, json.dumps({STAMP: hashlib.sha256(c).hexdigest(), "틀로 쓰기": True, "바탕": r.sha256}, ensure_ascii=False).encode("utf-8"))
    issues.append(issue("틀로 쓰기", "", "", "바탕이 공시 원문이라 엔진 틀(별도 감사보고서)에 원고를 넣었다. 원문 서식 · 계정코드는 남지 않고 요약 코드는 비어 있다. "
                        "편집기로 열어 확인한 뒤(편집기 확인 F7) 쓴다"))
    if "연결" in norm(info.get("document") or "") or any("연결" in norm(s.key) for s in sheets if s.kind == "재무제표"):
        issues.append(issue("틀로 쓰기", "", "", "연결 보고서는 틀이 없어 별도 감사보고서 틀에 넣었다(연결 틀은 빈 연결 dsd 를 받아 만든다)", "막음"))
    return {"path": path, "issues": issues, "changed": 0, "added": 0, "removed": 0, "same_bytes": False}
