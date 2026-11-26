"""분석 엔진 없이 받은자료에서 8100B 양식 정산표를 만든다(2026-11-26). 설계 문서 3절.

공개 스킬 「표준조서」 가 쓴다. 감사 건의 정산표는 analyze 가 만든 8100B 가 정본이고 이 모듈은 쓰지 않는다.
분석 엔진(analysis.engine · data)을 공개본에 싣지 않으려고 만든 길이라, 계정을 묶는 규칙은 그 코드와 같게 둔다.

  계정 묶기        analysis.data.Data._load_tb 와 같다(defs.code_key · defs.map_account, 시산표 표시과목 열 먼저, 3650A 확정 영역)
  계정 단위 전기    analysis.data.Data._derive_prior 와 같은 함수 prior.account_prior(장부 값은 prior.book)
  비교 줄 · 전기   analysis.engine.Engine.compare_lines 의 이름 짝(label_aliases · 계정 사전 id)만. AI 짝(_색인/전기과목짝.json)은 쓰지 않는다

  accounts(d)                    [{code, name, line, compare_line, area, section, cur, prior, prior_basis}], 재무제표 줄
  build(d, as_of=None) -> Path   8000 감사완결/8100B_정산표.xlsx (계정별 · 재무제표 · 수정 제안). 있던 파일의 수정 제안 줄은 옮긴다

금액은 시산표 부호(차변 +)이고, 「재무제표」 시트만 표시 부호(부채 · 자본 · 수익 양수)다. stdwp.read_tb 가 읽는 꼴이다.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.utils import get_column_letter

from . import figures, prior as prior_mod, style
from .analysis import defs

OUT = Path("8000 감사완결") / "8100B_정산표.xlsx"
SIGN = {"자산": 1, "비용": 1, "부채": -1, "자본": -1, "수익": -1}
BS = ("자산", "부채", "자본")
ADJ_HEAD = ["이슈", "계정코드", "계정명", "적요", "차변", "대변", "반영 여부", "근거"]
ADJ_ROWS = 200                      # 수정 제안 표 자리. 감사인이 줄을 더해도 계정별 수식 범위 안에 든다
WON = "#,##0;[Red]-#,##0;-"
PCT = "0.0%"


def _disp(a: dict, v):
    return None if v is None else v * SIGN.get(a.get("section"), 1)


def _load_tb(d: Path) -> list[dict]:
    """analysis.data.Data._load_tb 와 같은 규칙."""
    rows = figures.current_tb(d)
    areas = figures.confirmations(d)["area"]
    tb: list[dict] = []
    acct: dict[str, dict] = {}
    for r in rows:
        code = defs.code_key(r["code"]) or str(r["code"])
        m = defs.map_account(code, r["name"])
        col = (r.get("line_basis", "표시과목 열") in ("표시과목 열", figures.CONFIRMED, figures.CONTRA_LINE)
               and r["line"] and r["line"] != r["name"])
        if areas.get(str(r["code"])):
            m = {**m, "area": areas[str(r["code"])].upper().removeprefix("4000")}
        line = r["line"] if col else (m["label"] or r["line"] or r["name"])
        if code in acct:
            acct[code]["cur"] += r["amount"]
            continue
        a = {"code": code, "name": r["name"], "line": line, "cur": r["amount"], **m}
        acct[code] = a
        tb.append(a)
    return tb


def _derive_prior(d: Path, tb: list[dict]) -> None:
    """analysis.data.Data._derive_prior 와 같은 함수. 장부 값(원천 4)은 prior.book 이 분개장에서 낸다."""
    ap = prior_mod.account_prior(d, tb)
    for x in ap["extra"]:
        m = defs.map_account(x["code"], x["name"])
        tb.append({"code": x["code"], "name": x["name"], "line": m["label"] or x["name"], "cur": 0, **m})
        ap["accounts"][x["code"]] = {"prior": x["prior"], "basis": x["basis"]}
    for a in tb:
        x = ap["accounts"].get(a["code"]) or {}
        a["prior"] = x.get("prior")
        a["prior_basis"] = x.get("basis")


def _compare_lines(tb: list[dict], prior_fs: dict | None) -> list[dict]:
    """analysis.engine.Engine.compare_lines 의 이름 짝만. 당기 표시과목과 전기 재무제표 과목을 같은 뜻 이름 · 계정 사전 id 로 잇는다."""
    acc = defs.load("accounts")
    syn: dict[str, set] = {}
    for grp in acc["label_aliases"]:
        g = {defs.norm(x) for x in grp}
        for x in g:
            syn.setdefault(x, set()).update(g)
    subtotals = {defs.norm(x) for x in acc["subtotals"]}
    parent: dict = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        parent[find(a)] = find(b)

    is_sec = ("수익", "비용")
    for a in tb:
        find(("cur", "BS" if a["section"] in BS else "IS", a["line"]))
    prior = prior_fs or {"bs": {}, "is": {}}
    prior_vals = {}
    for stmt in ("bs", "is"):
        secs = BS if stmt == "bs" else is_sec
        for label, v in prior.get(stmt, {}).items():
            if defs.norm(label) in subtotals:
                continue
            node = ("prior", stmt.upper(), label)
            find(node)
            prior_vals[node] = v
            hit = False
            for tok in re.split(r"[·,ㆍ・]", label):
                t = defs.norm(tok)
                if not t:
                    continue
                names = syn.get(t, {t})
                for a in tb:
                    if a["section"] in secs and (defs.norm(a["line"]) in names or defs.norm(a["name"]) in names):
                        union(("cur", stmt.upper(), a["line"]), node)
                        hit = True
            if hit:
                continue
            m = defs.map_account(None, label)
            lines = {a["line"] for a in tb if m["id"] and a.get("id") == m["id"] and a["section"] in secs}
            if len(lines) == 1:
                union(("cur", stmt.upper(), next(iter(lines))), node)
    groups: dict = {}
    for a in tb:
        k = find(("cur", "BS" if a["section"] in BS else "IS", a["line"]))
        groups.setdefault(k, {"accounts": [], "prior_labels": []})["accounts"].append(a)
    for node in prior_vals:
        groups.setdefault(find(node), {"accounts": [], "prior_labels": []})["prior_labels"].append(node[2])
    out = []
    for g in groups.values():
        accs = g["accounts"]
        stmt = "BS" if (accs and accs[0]["section"] in BS) or (not accs and any(
            ("prior", "BS", l) in prior_vals for l in g["prior_labels"])) else "IS"
        lines = list(dict.fromkeys(a["line"] for a in accs))
        pf = [prior_vals[("prior", stmt, l)] for l in g["prior_labels"] if ("prior", stmt, l) in prior_vals]
        out.append({"label": " · ".join(lines) if lines else " · ".join(g["prior_labels"]), "stmt": stmt,
                    "codes": [a["code"] for a in accs], "cur": sum(_disp(a, a["cur"]) for a in accs),
                    "prior_fs": sum(pf) if pf else (None if prior_fs is None else 0),
                    "order": min((tb.index(a) for a in accs), default=9999)})
    out.sort(key=lambda x: (x["stmt"] != "BS", x["order"]))
    return out


def accounts(d: Path) -> dict:
    """{"accounts": [...], "lines": [...], "prior_fs": 전기 재무제표 또는 None, "tb_path": 시산표 파일}."""
    d = Path(d)
    tb = _load_tb(d)
    if not tb:
        raise LookupError(f"{figures.tb_absent_reason(d)}. 시산표(또는 계정 단위 재무제표)가 있어야 정산표를 만듭니다")
    _derive_prior(d, tb)
    pf = figures.prior(d)
    lines = _compare_lines(tb, pf)
    line_of = {c: ln["label"] for ln in lines for c in ln["codes"]}
    for a in tb:
        a["compare_line"] = line_of.get(a["code"], a["line"])
    rows = figures.current_tb(d)
    return {"accounts": tb, "lines": lines, "prior_fs": pf, "tb_path": rows[0]["path"] if rows else None}


# ---------------------------------------------------------------- 쓰기
def _old_adjustments(path: Path) -> list[list]:
    """있던 정산표 「수정 제안」 의 감사인 줄(계정코드가 있는 줄). 다시 만들 때 옮긴다."""
    if not path.exists():
        return []
    wb = load_workbook(path)
    try:
        if "수정 제안" not in wb.sheetnames:
            return []
        ws = wb["수정 제안"]
        out, started = [], False
        for r in range(1, ws.max_row + 1):
            vals = [ws.cell(r, c).value for c in range(1, len(ADJ_HEAD) + 1)]
            if vals[1] == "계정코드":
                started = True
                continue
            if started and vals[1] not in (None, ""):
                out.append(vals)
        return out
    finally:
        wb.close()


def _head(ws, title: str, company: str, ye: str, note: str) -> int:
    ws.cell(1, 1, title).font = style.font(size=style.SIZE_TITLE, bold=True, color=style.NAVY)
    ws.cell(2, 1, "회사명").font = style.font(color=style.MUTED)
    ws.cell(2, 2, company).font = style.font(bold=True)
    ws.cell(3, 1, "결산일").font = style.font(color=style.MUTED)
    ws.cell(3, 2, ye).font = style.font(bold=True)
    ws.cell(4, 1, note).font = style.font(size=style.SIZE_NOTE, color=style.MUTED)
    return 6


def _row_head(ws, r: int, names: list[str], widths: list[float]) -> None:
    for i, (n, w) in enumerate(zip(names, widths), 1):
        c = ws.cell(r, i, n)
        c.font = style.font(bold=True, color=style.WHITE)
        c.fill = style.FILL_HEAD
        ws.column_dimensions[get_column_letter(i)].width = w


def build(d: Path, as_of: str | None = None) -> Path:
    """정산표 파일을 (다시) 쓴다. as_of 는 중간감사 기준일(없으면 감사건 결산일)."""
    d = Path(d)
    case = json.loads((d / "_색인" / "감사건.json").read_text(encoding="utf-8"))
    company = (case.get("company") or {}).get("name") or ""
    ye = str(as_of or case.get("fiscal_year_end") or "")[:10]
    got = accounts(d)
    out = d / OUT
    old_adj = _old_adjustments(out)
    wb = Workbook()
    wb.remove(wb.active)

    # 수정 제안: 엔진 후보 없이 빈 표. 감사인이 줄을 적고 반영 여부 「예」 를 쓰면 계정별 수정 열이 SUMIFS 로 가져간다
    wa = wb.create_sheet("수정 제안")
    r = _head(wa, "수정 제안", company, ye, "감사인이 수정분개를 적는 표입니다. 반영 여부를 「예」 로 적은 줄만 「계정별」 시트 수정 열에 들어갑니다")
    _row_head(wa, r, ADJ_HEAD, [8, 10, 18, 40, 16, 16, 10, 40])
    adj_first = r + 1
    for i, vals in enumerate(old_adj):
        for c, v in enumerate(vals, 1):
            wa.cell(adj_first + i, c, v)
    for rr in range(adj_first, adj_first + max(ADJ_ROWS, len(old_adj) + 50)):
        for c in (5, 6):
            wa.cell(rr, c).number_format = WON
        wa.cell(rr, 7).fill = style.FILL_IN
    adj_last = adj_first + max(ADJ_ROWS, len(old_adj) + 50) - 1

    ws = wb.create_sheet("계정별", 0)
    r = _head(ws, "8100B 정산표(분석 없이 받은자료에서 만듦)", company, ye,
              f"시산표: {got['tb_path'] or '-'}. 금액은 시산표 부호(차변 +). 전기는 계정마다 원천 우선순위로 정한 잔액(출처 열)")
    head = ["코드", "계정명", "비교 줄(표시과목)", "영역", "구분", "전기", "당기(회사제시)", "수정 차변", "수정 대변",
            "당기(수정 후 최종)", "증감", "증감률", "관련 조서", "전기 출처"]
    _row_head(ws, r, head, [9, 18, 20, 8, 7, 16, 16, 15, 15, 16, 16, 10, 12, 24])
    first = r + 1
    S = lambda c: f"'수정 제안'!${c}${adj_first}:${c}${adj_last}"
    row = first
    for a in got["accounts"]:
        ws.cell(row, 1, a["code"])
        ws.cell(row, 2, a["name"])
        ws.cell(row, 3, a.get("compare_line") or a["line"])
        ws.cell(row, 4, a.get("area"))
        ws.cell(row, 5, a.get("section"))
        ws.cell(row, 6, a.get("prior")).number_format = WON
        ws.cell(row, 7, a["cur"]).number_format = WON
        ws.cell(row, 8, f'=SUMIFS({S("E")},{S("B")},A{row},{S("G")},"예")').number_format = WON
        ws.cell(row, 9, f'=SUMIFS({S("F")},{S("B")},A{row},{S("G")},"예")').number_format = WON
        ws.cell(row, 10, f"=G{row}+H{row}-I{row}").number_format = WON
        ws.cell(row, 11, f'=IF(F{row}="","",J{row}-F{row})').number_format = WON
        ws.cell(row, 12, f'=IF(OR(F{row}="",F{row}=0),"",K{row}/ABS(F{row}))').number_format = PCT
        ws.cell(row, 13, f"4000{a['area']}" if a.get("area") else "")
        ws.cell(row, 14, a.get("prior_basis"))
        row += 1
    last = row - 1
    ws.cell(row, 2, "합계(당기 · 수정 · 최종은 0)").font = style.font(bold=True)
    for col in (6, 7, 8, 9, 10):
        L = get_column_letter(col)
        ws.cell(row, col, f"=SUM({L}{first}:{L}{last})").number_format = WON
    ws.freeze_panes = f"C{first}"

    wf = wb.create_sheet("재무제표", 1)
    r = _head(wf, "재무제표", company, ye, "「계정별」 시트를 비교 줄로 묶은 표시 금액(부채 · 자본 · 수익 양수). 전기는 받은 전기 재무제표 값. "
              "이름으로 짝을 못 찾은 전기 과목은 전기 금액만 있는 줄로 남습니다")
    _row_head(wf, r, ["과목", "전기(전기 재무제표)", "당기(회사제시)", "당기(최종)", "증감(최종 − 전기)", "구분"], [30, 18, 18, 18, 18, 8])
    rng = lambda c: f"'계정별'!${c}${first}:${c}${last}"
    r += 1
    sec_of = {a["code"]: a["section"] for a in got["accounts"]}
    for ln in got["lines"]:
        sec = next((sec_of[c] for c in ln["codes"] if c in sec_of), None) or ("자산" if ln["stmt"] == "BS" else "비용")
        s = SIGN.get(sec, 1)
        wf.cell(r, 1, ln["label"]).font = style.font(bold=True)
        wf.cell(r, 2, ln["prior_fs"]).number_format = WON
        wf.cell(r, 3, f"={s}*SUMIF({rng('C')},$A{r},{rng('G')})").number_format = WON
        wf.cell(r, 4, f"={s}*SUMIF({rng('C')},$A{r},{rng('J')})").number_format = WON
        wf.cell(r, 5, f'=IF(B{r}="","",D{r}-B{r})').number_format = WON
        wf.cell(r, 6, ln["stmt"])
        r += 1
    # 합계 · 검산 줄(analysis.sheets 「재무제표」 시트와 같은 이름 · 수식). 전기는 전기 재무제표의 같은 이름 과목
    pf = got["prior_fs"] or {"bs": {}, "is": {}}
    pft = {**pf.get("bs", {}), **pf.get("is", {})}
    r += 1
    bold = style.font(bold=True)
    for name, sec in (("자산총계", "자산"), ("부채총계", "부채")):
        wf.cell(r, 1, name).font = bold
        wf.cell(r, 2, pft.get(name)).number_format = WON
        for col, src in ((3, "G"), (4, "J")):
            c = wf.cell(r, col, f'={SIGN[sec]}*SUMIF({rng("E")},"{sec}",{rng(src)})')
            c.number_format, c.font = WON, bold
        r += 1
    wf.cell(r, 1, "자본총계(당기순이익 포함)").font = bold
    wf.cell(r, 2, pft.get("자본총계")).number_format = WON
    for col, src in ((3, "G"), (4, "J")):
        c = wf.cell(r, col, f'=-SUMIF({rng("E")},"자본",{rng(src)})-SUMIF({rng("E")},"수익",{rng(src)})-SUMIF({rng("E")},"비용",{rng(src)})')
        c.number_format, c.font = WON, bold
    r += 1
    wf.cell(r, 1, "검산: 자산 − 부채 − 자본 (0 이어야 함)").font = bold
    for col in (3, 4):
        L = get_column_letter(col)
        c = wf.cell(r, col, f"={L}{r - 3}-{L}{r - 2}-{L}{r - 1}")
        c.number_format, c.font = WON, bold
    r += 1
    wf.cell(r, 1, "당기순이익").font = bold
    wf.cell(r, 2, pft.get("당기순이익")).number_format = WON
    for col, src in ((3, "G"), (4, "J")):
        c = wf.cell(r, col, f'=-SUMIF({rng("E")},"수익",{rng(src)})-SUMIF({rng("E")},"비용",{rng(src)})')
        c.number_format, c.font = WON, bold
    out.parent.mkdir(parents=True, exist_ok=True)
    style.finish(wb)
    wb.save(out)
    return out
