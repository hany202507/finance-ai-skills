# -*- coding: utf-8 -*-
"""계산근거 워크북. 입력을 바꾸면 세액이 따라 바뀌도록 수식으로 쓴다.
recalc 는 formulas 로 워크북을 독립 재계산해 셀 값을 돌려준다(엔진과 대조용)."""
import os

import openpyxl
from openpyxl.styles import Font

COL = {"id": "A", "종류": "B", "세율": "C", "단일세율": "D", "가산세율": "E", "양도가액": "F", "취득가액": "G",
       "필요경비": "H", "양도차익": "I", "고가주택": "J", "고가주택기준": "K", "과세양도차익": "L", "장특공률": "M",
       "장특공": "N", "양도소득금액": "O", "기본공제": "P", "과세표준": "Q", "산출세액": "R", "지방소득세": "S",
       "전액비과세": "T", "지방단일세율": "U", "지방가산세율": "V", "전체양도가액": "W"}
ROW_CHECK = ("양도차익", "과세양도차익", "장특공", "양도소득금액", "과세표준", "산출세액", "지방소득세")


def summary_cells(n):
    a, b, c = n + 3, n + 4, n + 5
    return {"자산별세액": "R%d" % a, "합산비교세액": "R%d" % b, "산출세액": "R%d" % c,
            "지방_자산별": "S%d" % a, "지방_합산비교": "S%d" % b, "지방소득세": "S%d" % c}


def _num(v):
    return float(v) if v is not None else None


def _p(x, sheet):
    rng = "%s!$A$2:$C$9" % sheet
    return "VLOOKUP({x},{r},2,TRUE)+({x}-VLOOKUP({x},{r},1,TRUE))*VLOOKUP({x},{r},3,TRUE)".format(x=x, r=rng)


def _tax(r, d, e, sheet):
    q = "Q%d" % r
    inner = "IF(ISNUMBER({e}{r}),MAX({p}+{q}*{e}{r},IF(ISNUMBER({d}{r}),{q}*{d}{r},0)),{q}*{d}{r})".format(
        e=e, r=r, d=d, q=q, p=_p(q, sheet))
    return "=IF(T{r}=1,0,ROUNDDOWN(ROUND({i},6),0))".format(r=r, i=inner)


def _table(ws, rows):
    ws.append(["하한", "기준액", "세율"])
    for a, b, c in rows:
        ws.append([int(a), int(b), float(c)])


def write(result, path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "계산"
    _table(wb.create_sheet("세율표"), result["세율표"]["국세"])
    _table(wb.create_sheet("지방세율표"), result["세율표"]["지방"])
    ws.append(list(COL))
    for cell in ws[1]:
        cell.font = Font(bold=True)
    rows = result["자산"]
    for r, row in enumerate(rows, start=2):
        v, c = row["판정"], row["계산"]
        rate = c["적용세율"]
        values = {
            "id": row["id"], "종류": v["종류"], "세율": "%s·%s" % (c.get("세율그룹"), c.get("세율종류")),
            "단일세율": _num(rate["단일"]), "가산세율": _num(rate["가산"]),
            "양도가액": c["양도가액"], "취득가액": c["취득가액"] or 0, "필요경비": c["필요경비"] or 0,
            "양도차익": "=F{r}-G{r}-H{r}".format(r=r), "고가주택": 1 if v["고가주택"] else 0,
            "고가주택기준": c.get("고가주택기준") or 0,
            "과세양도차익": "=IF(T{r}=1,0,IF(J{r}=1,ROUNDDOWN(ROUND(I{r}*(W{r}-K{r})/W{r},6),0),I{r}))".format(r=r),
            "장특공률": float(c["장특공률"]), "장특공": "=ROUNDDOWN(ROUND(L{r}*M{r},6),0)".format(r=r),
            "양도소득금액": "=L{r}-N{r}".format(r=r), "기본공제": c["기본공제"],
            "과세표준": "=O{r}-P{r}".format(r=r),
            "산출세액": _tax(r, "D", "E", "세율표"), "지방소득세": _tax(r, "U", "V", "지방세율표"),
            "전액비과세": 1 if v["전액비과세"] else 0,
            "지방단일세율": _num(rate["지방단일"]), "지방가산세율": _num(rate["지방가산"]),
            "전체양도가액": c["전체양도가액"],
        }
        for name, letter in COL.items():
            ws["%s%d" % (letter, r)] = values[name]
    n = len(rows)
    last = n + 1
    ws["A%d" % (n + 3)] = "자산별 합"
    ws["A%d" % (n + 4)] = "합산 비교(소득세법 제104조⑤)"
    ws["A%d" % (n + 5)] = "산출세액"
    ws["Q%d" % (n + 4)] = "=SUMIF(T2:T{l},0,Q2:Q{l})".format(l=last)
    for col, sheet in (("R", "세율표"), ("S", "지방세율표")):
        ws["%s%d" % (col, n + 3)] = "=SUM({c}2:{c}{l})".format(c=col, l=last)
        ws["%s%d" % (col, n + 4)] = "=IF(COUNTIF(T2:T{l},0)>=2,ROUNDDOWN(ROUND({p},6),0),0)".format(
            l=last, p=_p("Q%d" % (n + 4), sheet))
        ws["%s%d" % (col, n + 5)] = "=MAX({c}{a},{c}{b})".format(c=col, a=n + 3, b=n + 4)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    wb.save(path)
    return path


def recalc(path):
    import formulas
    base = os.path.basename(path).upper()
    sol = formulas.ExcelModel().loads(path).finish().calculate()
    out = {}
    for k, v in sol.items():
        ku = k.upper()
        if not ku.startswith("'[%s]" % base) or "!" not in ku:
            continue
        sheet = ku.split("]", 1)[1].split("'!", 1)[0]
        addr = ku.split("!", 1)[1]
        try:
            val = v.value[0, 0]
        except Exception:
            val = v.value
        out[(sheet, addr)] = val
    return out


def _eq(got, want):
    try:
        return int(round(float(got))) == int(want or 0)
    except (TypeError, ValueError):
        return False


def compare(path, result):
    cells = recalc(path)
    fails = []
    for i, row in enumerate(result["자산"], start=2):
        c = row["계산"]
        for name in ROW_CHECK:
            if c[name] is None:  # 전액비과세 자산의 양도차익처럼 계산하지 않은 값
                continue
            got = cells.get(("계산", "%s%d" % (COL[name], i)))
            if not _eq(got, c[name]):
                fails.append("W %s %s: 워크북 %s, 엔진 %s" % (row["id"], name, got, c[name]))
    for name, addr in summary_cells(len(result["자산"])).items():
        got = cells.get(("계산", addr))
        if not _eq(got, result["합계"][name]):
            fails.append("W 합계 %s: 워크북 %s, 엔진 %s" % (name, got, result["합계"][name]))
    return fails
