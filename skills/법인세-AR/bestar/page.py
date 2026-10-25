# -*- coding: utf-8 -*-
"""전기 신고서 PDF 한 쪽을 그림(PNG)으로 뜬다. 칸이 많은 서식은 쪽 글을 뽑으면 칸 배치가 깨져 읽기 어렵다(10-19 실행).

  ar.py page <신고건> <쪽> [--zoom 2]   →  _색인/AR_단계/전기_<쪽>쪽.png

그림을 보고 읽은 값은 `ar.py pdf` 로 적어야 글에 쓸 수 있다(확인 전 표시).
"""
from __future__ import annotations

import argparse

from bestar import paths


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="ar.py page")
    ap.add_argument("case")
    ap.add_argument("page", type=int)
    ap.add_argument("--zoom", type=float, default=2.0)
    a = ap.parse_args(argv)
    c = paths.case(a.case)
    pdfs = sorted((c.root / "00 받은자료" / "전기").glob("*.pdf"))
    if not pdfs:
        print("00 받은자료/전기/ 에 전기 신고서 PDF 가 없습니다")
        return 2
    import pymupdf
    doc = pymupdf.open(str(pdfs[0]))
    try:
        if not 1 <= a.page <= len(doc):
            print(f"쪽은 1 ~ {len(doc)} 입니다")
            return 2
        out = paths.steps_dir(c) / f"전기_{a.page}쪽.png"
        out.parent.mkdir(parents=True, exist_ok=True)
        doc[a.page - 1].get_pixmap(matrix=pymupdf.Matrix(a.zoom, a.zoom)).save(str(out))
    finally:
        doc.close()
    print(out)
    return 0
