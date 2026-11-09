"""3650A 감사전재무제표확인: 회사제시 재무제표 ↔ 시산표 대사(R4, 2026-10-05).

회사제시 폴더의 지금 판 파일에서 재무상태표 · 손익계산서 시트(과목 · 금액 머리줄)를 찾아 시산표 표시과목 합과 맞춘다.
재무제표 시트가 없으면 표시과목별 노란 칸에 받은 재무제표 금액을 적게 하고 차이를 수식으로 보인다.
계정 매핑(계정 → 표시과목 → 4000 영역)은 엔진 제안이고 감사인이 확정 칸에 적는다.
"""
from __future__ import annotations

from pathlib import Path

from .. import figures, reader, wp
from . import common
from .common import ask


def company_fs(d: Path) -> dict:
    """지금 판 회사제시 파일의 재무제표 시트. {"lines": {과목: 금액}, "source"} 없으면 lines 가 빈 dict."""
    from openpyxl import load_workbook

    d = Path(d)
    ver = common.case(d).get("company_version")
    out, src = {}, []
    for rel in figures.received(d, reader.TB):
        if Path(rel).suffix.lower() not in reader.EXCEL:
            continue
        if ver and f"_{ver}" not in Path(rel).stem:
            continue
        wb = load_workbook(d / rel, data_only=True, read_only=True)
        try:
            for ws in wb.worksheets:
                if not any(k in ws.title for k in ("재무상태표", "손익계산서", "대차대조표", "포괄손익")):
                    continue
                vals, _ = figures._prior_sheet(ws)
                if vals:
                    out.update(vals)
                    src.append(f"{rel} '{ws.title}'")
        finally:
            wb.close()
    return {"lines": out, "source": " · ".join(src) or None}


def _layout_recon(b, ws, row: int, d: Path) -> int:
    """회사제시 재무제표(공시 꼴 양식 파일)의 과목마다 당기 금액 ↔ 그 과목에 묶인 시산표 계정 합(2026-11-06).
    분석적 검토가 세운 공시 양식 배치(_색인/분석.json disclosure, 분석 대사 X-fs-tb)를 그대로 옮긴다. 이름이 달라도
    (제예금 · 외상매출금 ↔ 표시과목 현금및현금성자산 · 매출채권) 계정 단위로 이어져 있어 맞출 수 있다."""
    from .. import folder as _folder

    a = _folder._read(Path(d) / "_색인" / "분석.json", None) or {}
    dis = a.get("disclosure") or {}
    rows = [x for x in dis.get("rows") or [] if x.get("kind") == "acct" and x.get("cur_disclosed") is not None]
    if not rows or "회사제시" not in (dis.get("basis") or ""):
        return row
    rec = {r["label"]: r for r in a.get("recons") or [] if r.get("id") == "X-fs-tb"}
    row = b.section(ws, row, f"회사제시 재무제표 과목 ↔ 시산표 계정 ({dis.get('source_path')}, 금액은 시산표 부호 쪽: 차감 줄은 음수)")
    row = b.head(ws, row, ["재무제표 과목", "묶인 시산표 계정", "시산표 계정 합", "회사제시 재무제표", "차이(재무제표 − 시산표)", "결과"])
    first, n_diff = row, 0
    for x in rows:
        r = rec.get(x["key"])
        b.put(ws, row, 1, x["key"])
        b.put(ws, row, 2, ", ".join(x["codes"]) or "붙은 계정 없음", wrap=True, flag=not x["codes"])
        tb_v = r["right"] if r else x.get("cur")
        if tb_v is not None:
            b.put(ws, row, 3, tb_v, fmt=wp.WON)
        b.put(ws, row, 4, x["cur_disclosed"], fmt=wp.WON)
        if tb_v is not None:
            b.put(ws, row, 5, f"=D{row}-C{row}", fmt=wp.WON, flag=abs(x["cur_disclosed"] - tb_v) >= 1)
            b.put(ws, row, 6, f'=IF(ABS(E{row})<1,"일치","차이")')
            n_diff += abs(x["cur_disclosed"] - tb_v) >= 1
        else:
            b.put(ws, row, 6, "시산표 계정 없음")
            n_diff += 1
        if r and r.get("note"):
            ws.cell(row, 7, r["note"]).font = wp.font(size=9, color=wp.MUTED)
        row += 1
    b.verify("회사제시 재무제표 과목 금액의 합", f"=SUM('대사'!D{first}:D{row - 1})", sum(x["cur_disclosed"] for x in rows))
    ws.cell(row, 1, f"과목 {len(rows)}개 가운데 차이 · 계정 없음 {n_diff}개. 회사가 낸 재무제표와 시산표가 다르면 어느 판이 감사 대상인지 "
                    "회사에 확인한다(시산표만 수정분개를 반영한 판 등)").font = wp.font(size=9, color=wp.MUTED)
    return row + 2


def make(d: Path, ctx: dict | None = None, force: bool = False) -> dict:
    d = Path(d)
    defs = common.load_def("workpapers.yaml")
    tb = common.tb_rows(d, defs)
    fs = company_fs(d)
    b = wp.Book(d, "3650A", standard="실무지침 2018-3 감사 전 재무제표 확인 · 감사기준서 210 · 회사제시 재무제표와 시산표를 맞춘다")
    ws, row = b.sheet("대사", widths=[26, 20, 20, 18, 30, 12])
    src = tb[0]["path"] if tb else "없음"
    ws.cell(6, 1, f"시산표: {src} · 재무제표: {fs['source'] or '회사제시 폴더에 재무제표 시트 없음'}").font = wp.font(size=9, color=wp.MUTED)

    row = b.section(ws, row, "시산표 검산")
    row = b.head(ws, row, ["항목", "금액", "", "", "근거", ""])
    total = sum(r["amount"] for r in tb)
    b.put(ws, row, 1, "시산표 합계(차변 + · 대변 −)")
    b.put(ws, row, 2, total, fmt=wp.WON, flag=abs(total) > 0.5)
    b.put(ws, row, 5, "0 이어야 한다(차대 일치)")
    b.verify("시산표 합계", f"='대사'!B{row}", total)
    row += 1
    ni = -sum(r["amount"] for r in tb if r["pl"])
    assets = sum(r["amount"] for r in tb if (common.code3(r["code"]) or 0) <= 250)
    liab = -sum(r["amount"] for r in tb if 251 <= (common.code3(r["code"]) or 0) <= 330)
    eq = -sum(r["amount"] for r in tb if 331 <= (common.code3(r["code"]) or 0) <= 400)
    for lab, v in (("자산총계", assets), ("부채총계", liab), ("자본(마감 전)", eq), ("당기순이익(손익계정 합)", ni)):
        b.put(ws, row, 1, lab)
        b.put(ws, row, 2, v, fmt=wp.WON)
        row += 1
    b.put(ws, row, 1, "자산 − 부채 − 자본 − 당기순이익", bold=True)
    b.put(ws, row, 2, f"=B{row - 4}-B{row - 3}-B{row - 2}-B{row - 1}", fmt=wp.WON, flag=abs(assets - liab - eq - ni) > 0.5)
    b.verify("자산 − 부채 − 자본 − 당기순이익", f"='대사'!B{row}", assets - liab - eq - ni)
    row += 2

    row = _layout_recon(b, ws, row, d)
    row = b.section(ws, row, "표시과목별 대사 (표시 금액: 부채 · 자본 · 수익은 양수)")
    row = b.head(ws, row, ["표시과목", "시산표 합", "회사제시 재무제표", "차이", "근거", "결과"])
    lines: dict[str, int] = {}
    for r in tb:
        lines[r["line"]] = lines.get(r["line"], 0) + r["disp"]
    fsn = {reader._norm(k): v for k, v in fs["lines"].items()}
    first = row
    missing = 0
    for line, v in lines.items():
        b.put(ws, row, 1, line)
        b.put(ws, row, 2, v, fmt=wp.WON)
        fv = fsn.get(reader._norm(line))
        if fv is not None:
            b.put(ws, row, 3, fv, fmt=wp.WON)
            b.put(ws, row, 5, "회사제시 재무제표 시트(엔진)")
        else:
            ask(b, ws, row, 3, f"회사제시 재무제표 금액: {line}", rule="optional", fmt=wp.WON)
            b.put(ws, row, 5, "재무제표 시트에서 찾지 못함. 받은 재무제표 금액을 적는다" if fs["lines"] else "재무제표 시트 없음. 받은 재무제표 금액을 적는다", wrap=True)
            missing += 1
        b.put(ws, row, 4, f'=IF(C{row}="","",C{row}-B{row})', fmt=wp.WON)
        b.put(ws, row, 6, f'=IF(C{row}="","확인 전",IF(ABS(D{row})<1,"일치","차이"))')
        row += 1
    b.verify("표시과목별 시산표 합의 합", f"=SUM('대사'!B{first}:B{row - 1})", sum(lines.values()))
    ws.cell(row, 1, f"엔진이 재무제표에서 읽은 과목 {len(lines) - missing}개 · 노란 칸 {missing}개").font = wp.font(size=9, color=wp.MUTED)
    row += 1
    extra = [k for k in fs["lines"] if reader._norm(k) not in {reader._norm(x) for x in lines}]
    if extra:
        ws.cell(row, 1, "재무제표에만 있는 과목(합계 줄 포함): " + ", ".join(extra[:15])).font = wp.font(size=9, color=wp.MUTED)
        row += 1
    row += 1
    row = b.section(ws, row, "확인")
    ws.cell(row, 1, "대사 결과(차이가 있으면 원인과 처리)").font = wp.font(color=wp.MUTED)
    ask(b, ws, row, 2, "대사 결과 확인")
    ws.merge_cells(start_row=row, start_column=2, end_row=row, end_column=6)
    row += 1
    b.conclusion(ws, row, 6)

    wm, rm = b.sheet("계정 매핑", widths=[10, 18, 18, 10, 30, 18, 12])
    rm = b.section(wm, rm, "계정 → 표시과목 → 4000 영역 (엔진 제안. 다르면 확정 칸에 적는다. 다음 analyze · wp make · report 부터 WTB · 재무제표 · 4000 조서 Lead 가 따른다)")
    rm = b.head(wm, rm, ["계정코드", "계정명", "표시과목", "4000 영역", "근거", "표시과목 확정", "영역 확정"])
    for r in tb:
        b.put(wm, rm, 1, r["code"])
        b.put(wm, rm, 2, r["name"])
        b.put(wm, rm, 3, r["line"], flag=r.get("line_basis") == figures.CONFIRMED)
        b.put(wm, rm, 4, r["area"] or "", flag=r["area"] is None)
        b.put(wm, rm, 5, " · ".join(x for x in (r.get("line_basis"), r["area_basis"]) if x), wrap=True)
        ask(b, wm, rm, 6, f"표시과목 확정: {r['code']} {r['name']}", rule="optional")
        ask(b, wm, rm, 7, f"영역 확정: {r['code']} {r['name']}", rule="optional")
        rm += 1
    from ..analysis import fsmap          # 계정 → 공시 과목 당기 · 전기 나란히(R9 B6)

    fsmap.add_sheet(b, fsmap.rows(d, tb), "당기는 회사제시 시산표 표시과목(감사전), 전기는 분석적 검토가 이은 전기 재무제표 과목(_색인/분석.json)")
    out = common.save(b, force=force)
    out["fs_found"] = bool(fs["lines"])
    out["lines"] = len(lines)
    return out
