"""법제처 별지 제2호서식(세액감면(면제)신청서) PDF 원본 위에 창업감면 값만 얹는다. → 2 조서/창업감면_법정서식.pdf

서식 쪽은 법제처 국가법령정보센터 파일을 그대로 쓴다(forms/168822705.pdf, 법령 서식은 저작권 보호 대상이 아니다, 저작권법 제7조).
1쪽(신청인 · 과세연도 · 11O · 111 줄)과 3쪽(1A4 합계 줄)만 넣는다. 다른 감면 줄 · 2쪽 · 4 ~ 6쪽은 넣지 않는다.
사업자등록번호 · 대표자 · 생년월일 · 주소 · 날짜 · 서명은 사람이 적는다. 값은 엔진 결과(calc.compute)다.
"""
from __future__ import annotations

import json
from pathlib import Path

import pymupdf as fitz

from ..formkit import put     # 폭을 잰 글꼴로 칸 안에 넣는다(넘치면 가로로 줄인다)

HERE = Path(__file__).resolve().parent
FORMS = HERE / "forms"
OUT_PDF = "창업감면_법정서식.pdf"


def coords() -> dict:
    return json.loads((FORMS / "coords.json").read_text(encoding="utf-8"))


def _pct(x) -> str:
    return f"{float(x) * 100:g}%"


def values(inp, r: dict, company: str) -> dict:
    v = inp.values
    fs, fe = v["과세연도 시작일"], v["과세연도 종료일"]
    out = {"company": company, "fy_s_y": fs.year, "fy_s_m": fs.month, "fy_s_d": fs.day,
           "fy_e_y": fe.year, "fy_e_m": fe.month, "fy_e_d": fe.day}
    if not r["chosen"]:
        return out
    if r["o_7"]:
        out.update({"o_rate": _pct(r["rate"] + r["add_rate"] if r["rate"] == 1 else r["add_rate"]),
                    "o_7": r["o_7"], "o_8": r["o_8"], "o_9": r["o_9"]})
    if r["t_7"]:
        out.update({"t_rate": _pct(r["rate"]), "t_7": r["t_7"], "t_8": r["t_8"], "t_9": r["t_9"]})
    out.update({"sum_7": r["o_7"] + r["t_7"], "sum_8": r["o_8"] + r["t_8"], "sum_9": r["o_final"] + r["t_final"]})
    return out


def write(path: Path, inp, r: dict, company: str, stamp: str = "") -> dict:
    spec = coords()
    src = FORMS / spec["pdf"]["file"]
    if not src.exists():
        return {"written": False, "why": f"법제처 서식 PDF 가 없습니다: {src}"}
    vals = values(inp, r, company)
    base = fitz.open(src)
    doc = fitz.open()
    pages = spec["pages"]
    for n in pages:
        doc.insert_pdf(base, from_page=n - 1, to_page=n - 1)
    cells = 0
    for name, f in spec["fields"].items():
        if name not in vals or vals[name] in (None, ""):
            continue
        val = vals[name]
        text = f"{val:,}" if isinstance(val, int) and name not in ("fy_s_y", "fy_e_y") and val >= 1000 else str(val)
        page = doc[pages.index(f["page"])]
        put(page, f["box"], text, {"left": "l", "center": "c"}.get(f["align"], "r"))
        cells += 1
    if stamp:
        for page in doc:
            put(page, (60, 30, 400, 46), stamp, "l", size=11)
    doc.save(path)
    return {"written": True, "pages": len(pages), "cells": cells}
