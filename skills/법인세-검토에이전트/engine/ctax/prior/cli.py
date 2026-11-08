"""`python -m ctax prior <신고 건 폴더>`: 00 받은자료/전기/*.pdf → _색인/전기.json (CONTRACT.md 6절).

  --template <서식코드> [--out <파일>]  파서가 없는 서식을 스킬이 읽을 틀(란 코드 · 이름 · 답 틀)을 쓴다(ai.py)
  --merge-ai <답.json>                 스킬이 읽은 값을 검사에 통과시켜 전기.json 에 confirmed false 로 넣는다(ai.py)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

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
    ap.add_argument("--template", metavar="서식코드", help="스킬이 읽을 서식 틀을 _색인/전기_틀_<서식코드>.json 에 쓴다")
    ap.add_argument("--out", help="--template 결과 파일(기본 _색인/전기_틀_<서식코드>.json)")
    ap.add_argument("--merge-ai", metavar="답.json", help="스킬이 읽은 서식 값을 검사해 전기.json 에 넣는다(confirmed false)")
    args = ap.parse_args(argv)
    try:
        case = Case(args.folder)
    except MissingInput as e:
        print(e)
        return 2
    if args.template:
        return write_template(case, args.template, args.out)
    if args.merge_ai:
        return merge_ai(case, args.merge_ai)
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
    from ctax.case import file_sha1

    data = {"pdf": case.rel(pdf), **body}
    data["pdf_sha1"] = file_sha1(pdf)                       # 같은 이름으로 바꿔 넣은 전기 PDF 를 찾는다(intake/stale.py, 10-31)
    kept = keep_ai(case, data)
    case.write_json("전기.json", data)
    n_pages = sum(f["pages"] for f in data["forms"])
    note = (f"{data['fy']} 신고본 {n_pages}쪽 · 서식 {sum(1 for f in data['forms'] if f['known'])}개 · "
            f"조정 {len(data['adjustments'])}줄 · 유보 {len(data['reserves'])}줄 · 결손금 {len(data['losses'])}줄 · "
            f"공제감면 {len(data['credits'])}건 · 확인 {len(data['problems'])}건")
    if kept:
        note += f" · 스킬이 읽은 서식 {', '.join(kept)} 유지"
    ok = not fails
    info = case.info()
    if info.get(NO_PRIOR_KEY) is True:               # 신설로 돌렸다가 전기 PDF 가 들어와 읽었다(10-31 변경 검토)
        info.pop(NO_PRIOR_KEY)
        case.write_json("신고건.json", info)
        note += f" · 「{NO_PRIOR_KEY}」 표시를 지움(전기 PDF 를 읽음)"
    case.mark_step("prior", ok, note, ["_색인/전기.json"])
    print(f"{note} ({time.time() - t:.1f}초)")
    for q in data["problems"]:
        print(f"  확인: {q['title']} ({q['why']})")
    return 0 if ok else 1


def keep_ai(case: Case, data: dict) -> list[str]:
    """PDF 를 다시 읽을 때 앞서 --merge-ai 로 넣은 서식(엔진이 이번에도 읽지 못한 것)의 값 · 출처 · 확인사항을 옮겨 둔다."""
    if not case.has("전기.json"):
        return []
    from ctax.prior import ai
    try:
        old = case.read_json("전기.json")
    except ValueError:
        return []
    engine = ai.engine_forms(data)
    kept = []
    for code, meta in (old.get("ai") or {}).items():
        if code in engine:
            continue
        data.setdefault("cells", {})[code] = (old.get("cells") or {}).get(code) or {}
        if (old.get("rows") or {}).get(code):
            data.setdefault("rows", {})[code] = old["rows"][code]
        data.setdefault("ai", {})[code] = meta
        data["problems"] += [p for p in old.get("problems") or [] if p.get("by") == "ai" and p.get("form") == code]
        kept.append(code)
    return kept


def write_template(case: Case, code: str, out: str | None) -> int:
    """스킬이 읽을 서식 틀. 전기.json 이 있으면 그 서식 쪽 번호를 채운다."""
    from ctax.prior import ai
    prior = case.read_json("전기.json") if case.has("전기.json") else None
    try:
        data = ai.template(code, prior)
    except KeyError:
        print(f"{code} 서식 정의가 없습니다(ctax/prior/defs · ctax/forms/defs)")
        return 2
    path = Path(out) if out else case.index_path(f"전기_틀_{code}.json")
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{code} 틀: 란 {len(data['items'])}개 · 쪽 {', '.join(map(str, data['pages'])) or '모름'} → {path}")
    if data["engine_read"]:
        print(f"  {code} 는 엔진이 이미 읽은 서식입니다. --merge-ai 는 이 서식을 받지 않습니다")
    return 0


def merge_ai(case: Case, answer: str) -> int:
    """스킬 답(한 서식 또는 여럿) → 전기.json. 끝 코드 0 넣음, 1 넣었으나 검사 불일치 · 받지 않은 서식, 2 입력 없음."""
    from ctax.prior import ai
    try:
        prior = case.read_json("전기.json", "prior")
    except MissingInput as e:
        print(e)
        return 2
    try:
        answers = ai.load_answers(Path(answer))
    except (OSError, ValueError) as e:
        print(f"스킬 답을 읽지 못했습니다: {answer} ({e})")
        return 2
    pdf = (case.root / prior["pdf"]) if prior.get("pdf") else None
    bad, notes = 0, []
    for ans in answers:
        try:
            prior, new, note = ai.merge(prior, ans, pdf)
        except KeyError as e:
            notes.append(f"{e.args[0]} 서식 정의가 없어 넣지 않았습니다")
            bad += 1
            continue
        except ValueError as e:
            notes.append(str(e))
            bad += 1
            continue
        notes.append(note)
        bad += sum(1 for p in new if p["kind"] in ("check_form", "check_cross", "missing_amount", "not_in_text"))
        for p in new:
            print(f"  확인: {p['title']} ({p['why']})")
    case.write_json("전기.json", prior)
    case.mark_step("prior_ai", not bad, " / ".join(notes), ["_색인/전기.json"])
    for n in notes:
        print(n)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
