"""푸팅: 합계 재계산과 문서 사이 대사 (R4 report, 2026-10-05).

문서에 지금 적힌 숫자를 다시 읽어 엔진 값과 맞춘다. 문서는 회계사나 회사가 고쳤을 수 있다.
  재무제표 합계   8810 표의 소계 · 합계를 구성 과목으로 다시 더한다. 자산총계 = 부채와자본총계. 자본변동표 가로 · 세로
  재무제표 ↔ 시산표   8810 의 과목 금액 = 수정 후 시산표(엔진)
  전기   엔진이 묶은 전기 금액의 합계 = 전기 재무제표 합계(figures.prior), 8810 전기 열 = 전기 재무제표
  주석   주석 표 세로 합계 · 가로 합계 재계산, 주석 합계 = 8810 = 시산표, 주석 전기 = 전기 재무제표
  주석 문서   8400 엑셀의 표 = 8400 워드의 표
결과는 일치 · 불일치 · 확인. 확인은 숫자 차이가 아니라 회계사가 볼 점(전기 과목 없음 등)이다.
"""
from __future__ import annotations

import re

from pathlib import Path

from .. import wp
from .base import RBook, doc_tables, norm, parse_num, prev_inputs, table_values
from .fs import statement_values


def item(area, where, what, doc, ref, result=None, note=""):
    diff = doc - ref if isinstance(doc, int) and isinstance(ref, int) else None
    if result is None:
        if doc is None and ref is None:
            result = "확인"
        elif doc is None or ref is None:
            result = "불일치"
            note = note or ("문서에 숫자가 없음" if doc is None else "맞출 숫자가 없음")
        else:
            result = "일치" if diff == 0 else "불일치"
    return {"area": area, "where": where, "item": what, "doc": doc, "ref": ref, "diff": diff, "result": result, "note": note}


def fs_doc_values(blocks: list) -> dict:
    tabs = doc_tables(blocks)
    return {"bs": table_values(tabs.get("재무상태표") or [[]]), "is": table_values(tabs.get("손익계산서") or [[]]),
            "sce": tabs.get("자본변동표"), "found": [k for k in ("재무상태표", "손익계산서", "자본변동표") if k in tabs]}


def _get(vals: dict, label: str, col: int):
    v = vals.get(norm(label))
    if v is None and norm(label) == "부채와자본총계":
        v = vals.get("부채및자본총계")              # 전기 재무제표 표시를 따른 이름(R8)
    if v is None and norm(label).endswith("이익"):
        # 이익 계산 줄은 손실이면 '…손실' · '…이익(손실)' 로 보인다(R8)
        k = norm(label)
        v = vals.get(k[:-2] + "손실") or vals.get(k + "(손실)")
    return v[col] if v and col < len(v) else None


def foot_fs(fs: dict, docv: dict, where: str) -> list[dict]:
    out = []
    for k, title in (("재무상태표", "재무상태표"), ("손익계산서", "손익계산서")):
        if k not in docv["found"]:
            out.append(item("재무제표 합계", where, f"{title} 표가 없음", None, 0, "불일치"))
    for key, title in (("bs", "재무상태표"), ("is", "손익계산서")):
        vals = docv[key]
        for r in fs[key]:
            if not r["members"]:
                continue
            for col, cn in ((0, "당기"), (1, "전기")):
                total = _get(vals, r["label"], col)
                parts = [_get(vals, m, col) for m, _ in r["members"]]
                rec = None if any(p is None for p in parts) else sum(s * p for p, (_, s) in zip(parts, r["members"]))
                if total is None and rec is None:
                    continue
                out.append(item("재무제표 합계", f"{where} {title}", f"{r['label']} {cn} = 구성 과목 합", total, rec))
    for col, cn in ((0, "당기"), (1, "전기")):
        a, b = _get(docv["bs"], "자산총계", col), _get(docv["bs"], "부채와자본총계", col)
        if a is not None or b is not None:
            out.append(item("재무제표 합계", f"{where} 재무상태표", f"자산총계 = 부채와자본총계 {cn}", a, b))
    sce = docv.get("sce")
    if sce and len(sce) > 2:
        head = sce[0]
        rows = [[parse_num(c) for c in r[1:]] for r in sce[1:]]
        labels = [norm(r[0]) for r in sce[1:]]
        for lab, r in zip(labels, rows):
            if all(v is not None for v in r):
                out.append(item("재무제표 합계", f"{where} 자본변동표", f"{lab} 가로 합계", r[-1], sum(r[:-1])))
        for j, h in enumerate(head[1:]):
            col = [r[j] for r in rows]
            if all(v is not None for v in col):
                out.append(item("재무제표 합계", f"{where} 자본변동표", f"{h} 기초 + 변동 = 기말", col[-1], sum(col[:-1])))
        end = dict(zip(labels, rows)).get(norm("당기말"))
        tot = _get(docv["bs"], "자본총계", 0)
        if end:
            out.append(item("재무제표 합계", f"{where} 자본변동표", "당기말 합계 = 재무상태표 자본총계", end[-1], tot))
    return out


def tie_fs(fs: dict, docv: dict, where: str) -> list[dict]:
    """문서 재무제표의 과목 금액 = 엔진(수정 후 시산표 · 전기 재무제표)."""
    out = []
    ev = statement_values(fs)
    for key, title in (("bs", "재무상태표"), ("is", "손익계산서")):
        for r in fs[key]:
            if r["kind"] == "header":
                continue
            lab = norm(r["label"])
            cur, pri = ev[key][lab]
            out.append(item("재무제표 ↔ 시산표", f"{where} {title}", f"{r['label']} 당기", _get(docv[key], lab, 0), cur))
            if pri is not None or _get(docv[key], lab, 1) is not None:
                out.append(item("전기", f"{where} {title}", f"{r['label']} 전기", _get(docv[key], lab, 1), pri))
    return out


def prior_totals(fs: dict, prior: dict | None) -> list[dict]:
    """엔진이 과목을 묶어 계산한 전기 합계 = 전기 재무제표에 적힌 합계."""
    out = []
    if not prior:
        return [item("전기", "전기 재무제표", "전기 재무제표가 없어 전기 대사를 하지 못함", None, None, "확인")]
    ev = statement_values(fs)
    # 표시과목 규칙으로 다른 과목에 묶여 들어간 전기 과목(예: 전기 '자본금' → 당기 '보통주자본금')은 합계 줄로 보지 않는다(R8)
    absorbed = {lab for u in fs["units"] for lab in re.findall(r"'([^']+)'", u.prior_basis or "") if norm(lab) != norm(u.name)}
    for key, src in (("bs", prior.get("bs") or {}), ("is", prior.get("is") or {})):
        for lab, v in src.items():
            if lab in absorbed:
                continue
            n = norm(lab)
            if n in ev[key] and any(r["label"] == lab and r["members"] for r in fs[key]):
                out.append(item("전기", f"전기 재무제표({prior.get('path')})", f"{lab} = 엔진이 과목으로 다시 더한 전기 금액", v, ev[key][n][1]))
    for u in fs["units"]:
        if u.prior_basis in ("전기 재무제표에 같은 과목 없음", "당기 잔액 없음"):
            out.append(item("전기", "과목 대응", f"{u.name}: {u.prior_basis}", u.prior, u.prior, "확인"))
    for r in fs.get("unclassified", []):
        out.append(item("재무제표 ↔ 시산표", "수정 후 시산표", f"재무제표 위치를 정하지 못한 계정 {r['code']} {r['name']}", r["amount"], 0, "불일치"))
    return out


def _tb_value(atb: list[dict], codes: list) -> int:
    by = {t["code"]: t["amount"] for t in atb}
    return sum(s * by.get(c, 0) for c, s in codes)


def _rowvals(t: dict, label: str | None) -> list | None:
    if label is None:
        return t.get("total")
    return next((r for r in t["rows"] if norm(r[0]) == norm(label)), None)


def foot_notes(tables: list[dict], docv: dict, atb: list[dict], fs: dict, where: str = "8400 주석") -> list[dict]:
    out = []
    ev = statement_values(fs)
    for t in tables:
        w = f"{where} 표 {t['id']}"
        rows = [[parse_num(v) if i else v for i, v in enumerate(r)] for r in t["rows"]]
        total = [parse_num(v) if i else v for i, v in enumerate(t["total"])] if t.get("total") else None
        for c in t.get("sum_cols", []):
            if total is None:
                continue
            parts = [r[c] for r in rows]
            rec = None if any(p is None for p in parts) else sum(parts)
            out.append(item("주석 합계", w, f"{t['cols'][c]} 세로 합계", total[c], rec))
        for x in t.get("cross", []):
            for r in rows + ([total] if total else []):
                parts = [r[ci] for ci, _ in x["terms"]]
                rec = None if any(p is None for p in parts) else sum(s * p for p, (_, s) in zip(parts, x["terms"]))
                out.append(item("주석 합계", w, f"{r[0]} 가로 합계({t['cols'][x['target']]})", r[x["target"]], rec))
        tt = dict(t, rows=rows, total=total)
        for tie in t.get("ties", []):
            r = _rowvals(tt, tie["row"])
            v = r[tie["col"]] if r else None
            if tie.get("fs"):
                st, labels, fc = tie["fs"]
                parts = [_get(docv[st], lab, fc) for lab in labels]
                ref = None if any(p is None for p in parts) else sum(parts)
                out.append(item("주석 ↔ 재무제표", w, f"{tie['what']} = 8810 {', '.join(labels)}", v, ref))
            if tie.get("tb"):
                out.append(item("주석 ↔ 시산표", w, f"{tie['what']} = 수정 후 시산표 {', '.join(c for c, _ in tie['tb'])}", v,
                                _tb_value(atb, tie["tb"])))
            if tie.get("prior"):
                st, labels = tie["prior"]
                parts = [ev[st].get(norm(lab), (None, None))[1] for lab in labels]
                ref = None if any(p is None for p in parts) else sum(parts)
                if v is None and ref is None:
                    continue
                out.append(item("전기", w, f"{tie['what']} = 전기 재무제표 {', '.join(labels)}", v, ref))
        rc = t.get("recon")
        if rc and rc.get("kind") == "차이":
            out.append(item("주석 ↔ 시산표", w, "명세서 합계와 수정 후 시산표가 다르고 8100A 수정분개로 설명되지 않음", rc["amount"], 0, "불일치"))
        elif rc:
            out.append(item("주석 ↔ 시산표", w, "명세서 합계와 수정 후 시산표 차이를 8100A 수정분개로 설명함", rc["amount"], rc["amount"], "확인"))
    return out


def positional(rows: list[list]) -> list[list]:
    return [[norm(r[0])] + [parse_num(c) for c in r[1:]] for r in rows]


def compare_tables(a: dict, b: dict, area: str, wa: str, wb_: str) -> list[dict]:
    """두 문서의 같은 이름 표를 칸마다 맞춘다. a, b: {표 이름: 행 목록(머리줄 포함)}"""
    out = []
    for k, ra in a.items():
        rb = b.get(k)
        if rb is None:
            out.append(item(area, f"{wb_}", f"표 {k} 가 없음", None, 0, "불일치"))
            continue
        pa, pb = positional(ra), positional(rb)
        if len(pa) != len(pb):
            out.append(item(area, f"{wa} ↔ {wb_} 표 {k}", "행 수가 다름", len(pb), len(pa), "불일치"))
            continue
        bad = 0
        for x, y in zip(pa[1:], pb[1:]):
            if x[0] != y[0]:
                out.append(item(area, f"{wa} ↔ {wb_} 표 {k}", f"행 이름이 다름: {x[0]} · {y[0]}", None, None, "불일치"))
                bad += 1
                continue
            for j, (u, v) in enumerate(zip(x[1:], y[1:]), 1):
                if u != v:
                    out.append(item(area, f"{wa} ↔ {wb_} 표 {k}", f"{x[0]} {ra[0][j] if j < len(ra[0]) else j}열", v, u))
                    bad += 1
        if not bad:
            out.append(item(area, f"{wa} ↔ {wb_} 표 {k}", "모든 칸이 같음", 0, 0, "일치"))
    return out


def counts(items: list[dict]) -> dict:
    return {r: sum(1 for x in items if x["result"] == r) for r in ("일치", "불일치", "확인")}


def write(d: Path, path: Path, items: list[dict], title: str = "푸팅", no: str = "8400") -> Path:
    b = RBook(d, no, title=title, standard="합계 재계산 · 재무제표 · 주석 · 시산표 · 전기 재무제표 대사", keep=prev_inputs(path))
    ws, row = b.sheet(title, [16, 34, 46, 18, 18, 16, 10, 26])
    c = counts(items)
    b.put(ws, row, 1, f"불일치 {c['불일치']}건 · 일치 {c['일치']}건 · 확인 {c['확인']}건", bold=True,
          color="B3261E" if c["불일치"] else None)
    row += 2
    row = b.head(ws, row, ["구분", "위치", "검사", "문서 금액", "다시 계산 · 대사 금액", "차이", "결과", "비고"])
    for x in sorted(items, key=lambda x: {"불일치": 0, "확인": 1, "일치": 2}[x["result"]]):
        b.put(ws, row, 1, x["area"])
        b.put(ws, row, 2, x["where"], wrap=True)
        b.put(ws, row, 3, x["item"], wrap=True)
        b.put(ws, row, 4, x["doc"], fmt=wp.WON)
        b.put(ws, row, 5, x["ref"], fmt=wp.WON)
        b.put(ws, row, 6, x["diff"], fmt=wp.WON)
        b.put(ws, row, 7, x["result"], flag=x["result"] == "불일치", bold=x["result"] != "일치")
        b.put(ws, row, 8, x["note"], wrap=True)
        row += 1
    if c["불일치"]:
        row = b.section(ws, row + 1, "불일치 처리 (감사인)")
        b.ask(ws, row, 1, "불일치 처리", rule="required")
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=8)
        row += 1
    b.conclusion(ws, row, 8)
    return b.save(path)

