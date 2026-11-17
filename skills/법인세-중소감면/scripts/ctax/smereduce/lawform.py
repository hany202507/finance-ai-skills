"""법제처 별지 제2호서식(세액감면(면제)신청서) PDF 원본 위에 중소기업특별세액감면 값만 얹는다. → 2 조서/중소감면_법정서식.pdf

서식 쪽은 법제처 국가법령정보센터 파일을 그대로 쓴다(forms/168822705.pdf, 법령 서식은 저작권 보호 대상이 아니다, 저작권법 제7조).
1쪽(신청인 · 과세연도 · 112 줄)과 3쪽(1A4 합계 줄)만 넣는다. 다른 감면 줄 · 2쪽 · 4 ~ 6쪽은 넣지 않는다.
사업자등록번호 · 대표자 · 생년월일 · 주소 · 날짜 · 서명은 사람이 적는다. 값은 엔진 결과(calc.compute)다.
"""
from __future__ import annotations

import json
from pathlib import Path

import pymupdf as fitz

from ..formkit import put     # 폭을 잰 글꼴로 칸 안에 넣는다(넘치면 가로로 줄인다)

HERE = Path(__file__).resolve().parent
FORMS = HERE / "forms"
OUT_PDF = "중소감면_법정서식.pdf"


def coords() -> dict:
    return json.loads((FORMS / "coords.json").read_text(encoding="utf-8"))


def values(inp, r: dict, company: str) -> dict:
    v = inp.values
    fs, fe = v["과세연도 시작일"], v["과세연도 종료일"]
    out = {"company": company, "fy_s_y": fs.year, "fy_s_m": fs.month, "fy_s_d": fs.day,
           "fy_e_y": fe.year, "fy_e_m": fe.month, "fy_e_d": fe.day}
    if not r["chosen"] or not r["a7"]:
        return out
    out.update({"rate": f"{float(r['rate']) * 100:g}%", "a7": r["a7"], "a8": r["a8"], "a9": r["a9"],
                "sum_7": r["a7"], "sum_8": r["a8"], "sum_9": r["total"]})
    return out


def write(path: Path, inp, r: dict, company: str) -> dict:
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
    doc.save(path)
    return {"written": True, "pages": len(pages), "cells": cells}
