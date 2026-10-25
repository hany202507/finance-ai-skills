"""`python -m ctax wp <신고 건 폴더>`: 조서 등록부(`papers`)와 집계 넷을 계산해 `_색인/조정.json` 과 `2 조서/조서.xlsx` 를 쓴다.

조서.xlsx 가 이미 있으면 노란 칸(회계사 입력)을 먼저 읽어 `_색인/조서입력.json` 에 모으고 그 값으로 계산한다(inputs.py).
"""
from __future__ import annotations

import argparse
import sys

from ..case import WP_DIR, Case, MissingInput, won
from . import excel, inputs
from .books import Books, load_rates, read_journal
from .summary import Result, run

OUT_XLSX = "조서.xlsx"


def build(case: Case, overrides: dict | None = None) -> tuple[Books, Result]:
    ledger = case.need("read")
    prior = case.need("prior")
    journal = case.root / (ledger.get("journal_csv") or "_색인/전표.csv")
    if not journal.exists():
        raise MissingInput(f"{journal.name} 이 없습니다. 먼저 ctax read 를 돌리세요")
    ar = case.read_json("AR.json") if case.has("AR.json") else None
    books = Books(ledger=ledger, lines=read_journal(journal), prior=prior, ar=ar, info=case.info(), rates=load_rates(),
                  overrides=overrides or {})
    return books, run(books)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ctax wp", description="조서와 조정.json 을 만든다")
    ap.add_argument("folder", help="신고 건 폴더(<회사>/<연도> 법인세)")
    ap.add_argument("--fresh", action="store_true", help="조서.xlsx 의 노란 칸을 읽지 않고 엔진 값으로 새로 쓴다")
    args = ap.parse_args(argv)
    try:
        case = Case(args.folder)
        xlsx_path = case.out_dir(WP_DIR) / OUT_XLSX
        overrides, problems = ({}, []) if args.fresh else inputs.collect(case, xlsx_path)
        books, result = build(case, overrides)
    except MissingInput as e:
        print(f"입력이 없습니다: {e}")
        return 2
    try:
        excel.write(result, books, xlsx_path)
    except PermissionError:
        print(f"{xlsx_path} 가 열려 있어 쓰지 못했습니다. 엑셀을 닫고 다시 돌리세요")
        return 1
    data = result.json()
    case.write_json("조정.json", data)
    s = result.summary
    failed = [c for c in result.checks if not c["ok"]]
    adjs = data["adjustments"]
    used = sum(len(p.overridden) for p in result.all_papers)
    note = (f"조서 {len(result.papers)} · 조정 {len(adjs)}줄(가산 {won(s['add'])} · 차감 {won(s['deduct'])}) · "
            f"기부금 한도초과 {won(s['donation_excess'])} · 과세표준 {won(s['tax_base'])} · 산출세액 {won(s['computed_tax'])}")
    if data["direct"]:
        note += f" · 직접 조정 {len(data['direct'])}줄"
    if used:
        note += f" · 회계사 값 {used}칸"
    if failed:
        note += " · 검사 실패 " + ", ".join(c["title"] for c in failed)
    case.mark_step("wp", not failed, note, ["_색인/조정.json", f"{WP_DIR}/{OUT_XLSX}"])
    print(note)
    for msg in problems:
        print(f"  알림: {msg}")
    for p in result.papers:
        live = p.live_adjustments()
        detail = "; ".join(f"{a.side} {a.kind} {won(a.amount)}" for a in live) or "조정 없음"
        print(f"  {p.sheet:<14} {p.status:<6} {detail}")
    print(f"  3호 01 {won(s['net_income'])} · 02 {won(s['add'])} · 03 {won(s['deduct'])} · 05 {won(s['donation_excess'])}"
          f" · 06 {won(s['income'])} · 07 {won(s['loss_used'])} · 10 {won(s['tax_base'])} · 12 {won(s['computed_tax'])}"
          f" · 30 {won(s['payable'])}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
