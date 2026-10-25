"""`python -m ctax prior <신고 건 폴더>`: 00 받은자료/전기/*.pdf → _색인/전기.json (CONTRACT.md 6절)."""
from __future__ import annotations

import argparse
import re
import sys
import time

from ctax.case import Case, MissingInput

# 이 확인사항이 있으면 끝 코드 1(실행은 됐으나 검사 실패). 그 밖의 확인사항은 사람이 볼 것이라 끝 코드 0 이다
FAIL_REFS = re.compile(r"^(check\.|3$|15$|50갑$)")

# 전기 신고서가 없는 신고 건(신설 첫 해 · 첫 수임). 신고건.json 에 이 키가 참이면 PDF 없이 빈 전기.json 을 쓴다
NO_PRIOR_KEY = "전기 신고서 없음"
NO_PRIOR_TITLE = "전기 신고서가 없습니다(신설 첫 해 또는 첫 수임)"
# 그때 회사 정보를 받는 신고건.json 선택 키와 옮기는 자리. (적는 이름, 전기.json company 키) · (적는 이름, 1호 란 code)
COMPANY_KEY = "회사정보"
COMPANY_FIELDS = [("법인명", "name"), ("중소기업", "sme"), ("소기업", "small"), ("종류별구분", "kind_code"),
                  ("주업종코드", "industry_code"), ("업태", "biz_type"), ("종목", "item"), ("기수", "period_no"),
                  ("사업자등록번호", "biz_no")]
COMPANY_CELLS_1 = [("사업자등록번호", "1"), ("법인등록번호", "2"), ("전화번호", "4"), ("대표자성명", "5"),
                   ("전자우편주소", "6"), ("소재지", "7"), ("법인구분", "13"), ("조정구분", "14")]


def pick_pdf(case: Case):
    """전기 PDF. 여럿이면 파일 이름이 전기 연도로 시작하는 것, 없으면 이름 순 마지막."""
    pdfs = sorted(p for p in case.prior_dir.glob("*.pdf") if not p.name.startswith("~$")) if case.prior_dir.is_dir() else []
    if not pdfs:
        return None, []
    prev = str(int(case.fy) - 1) if case.fy.isdigit() else ""
    hit = [p for p in pdfs if prev and p.name.startswith(prev)]
    chosen = hit[0] if hit else pdfs[-1]
    return chosen, [p for p in pdfs if p != chosen]


def no_prior(case: Case) -> int:
    """전기 신고서가 없는 신고 건(신설 첫 해 · 첫 수임). 빈 전기.json 을 쓰고 끝 코드 0 이다.

    회사 정보는 전기 신고서 1호에서 오던 값이라 여기서는 신고건.json 선택 키 「회사정보」 에 사람이 적은 값을 옮긴다
    (company 와 cells 1 의 같은 자리). 그 키도 없으면 빈 값이고 서식 머리 란은 회계사가 채운다."""
    given = case.info().get(COMPANY_KEY) or {}
    company = {key: given[label] for label, key in COMPANY_FIELDS if given.get(label) not in (None, "")}
    one = {code: str(given[label]) for label, code in COMPANY_CELLS_1 if str(given.get(label) or "").strip()}
    data = {"pdf": None, "no_prior": True, "fy": "", "fy_end": "", "forms": [], "company": company,
            "cells": {"1": one} if one else {}, "rows": {}, "adjustments": [], "reserves": [], "losses": [],
            "credits": [], "credit_years": [], "employment": {},
            "problems": [{"title": NO_PRIOR_TITLE,
                          "why": f"신고건.json 「{NO_PRIOR_KEY}」 이 참입니다. 전기와 견주는 항목은 전기 신고서가 없어 견주지 못했습니다"}]}
    case.write_json("전기.json", data)
    note = f"{NO_PRIOR_TITLE} · 빈 전기.json" + (f" · 회사정보 {len(company) + len(one)}칸" if company or one else "")
    case.mark_step("prior", True, note, ["_색인/전기.json"])
    print(note)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ctax prior", description="전기 세무조정계산서 PDF 를 읽어 _색인/전기.json")
    ap.add_argument("folder", help="신고 건 폴더(<회사>/<연도> 법인세)")
    args = ap.parse_args(argv)
    try:
        case = Case(args.folder)
    except MissingInput as e:
        print(e)
        return 2
    pdf, others = pick_pdf(case)
    if pdf is None and case.info().get(NO_PRIOR_KEY) is True:
        return no_prior(case)
    if pdf is None:
        msg = "00 받은자료/전기 에 전기 세무조정계산서 PDF 가 없습니다"
        print(msg)
        case.mark_step("prior", False, msg, [])
        return 2
    from ctax.prior.read import read_prior
    t = time.time()
    try:
        body = read_prior(pdf)
    except Exception as e:                      # 열리지 않는 PDF
        msg = f"전기 PDF 를 읽지 못했습니다: {pdf.name} ({e!r})"
        print(msg)
        case.mark_step("prior", False, msg, [])
        return 2
    fails = [q for q in body["problems"] if FAIL_REFS.match(q.get("ref", ""))]
    for p in others:
        body["problems"].append({"title": "전기 폴더에 PDF 가 여럿이다", "why": f"{case.rel(pdf)} 를 읽고 {p.name} 는 읽지 않았다"})
    for q in body["problems"]:
        q.pop("ref", None)
    data = {"pdf": case.rel(pdf), **body}
    case.write_json("전기.json", data)
    n_pages = sum(f["pages"] for f in data["forms"])
    note = (f"{data['fy']} 신고본 {n_pages}쪽 · 서식 {sum(1 for f in data['forms'] if f['known'])}개 · "
            f"조정 {len(data['adjustments'])}줄 · 유보 {len(data['reserves'])}줄 · 결손금 {len(data['losses'])}줄 · "
            f"공제감면 {len(data['credits'])}건 · 확인 {len(data['problems'])}건")
    ok = not fails
    case.mark_step("prior", ok, note, ["_색인/전기.json"])
    print(f"{note} ({time.time() - t:.1f}초)")
    for q in data["problems"]:
        print(f"  확인: {q['title']} ({q['why']})")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
