"""`python -m ctax read <신고 건 폴더>`: 받은자료 xlsx · xls 를 머리줄로 가려 읽고 _색인/장부.json · 전표.csv 를 쓴다.

읽는 꼴: 위하고(분개장 11열 · 재무제표 5열 · 거래처원장 A 꼴 · 계정명세서 B 꼴), 더존 ERP(분개장 10열 7자 코드 ·
재무제표 5열 · 계정명세서 BIFF 블록 · 합계잔액시산표).

끝 코드: 0 대사 통과, 1 대사 실패가 있음, 2 신고 건 폴더 · 분개장 · 재무상태표 · 손익계산서가 없거나 읽지 못함.
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from ..case import Case, MissingInput
from . import douzone
from . import fs as fsmod
from . import journal as jmod
from .build import build
from .partners import parse_a, parse_b
from .sniff import account_hint, sniff

CSV_HEAD = ["date", "no", "kind", "account", "account_name", "debit", "credit", "partner_code", "partner",
            "memo_code", "memo", "closing", "sub_account"]


def _out(msg: str) -> None:
    try:
        print(msg)
    except UnicodeEncodeError:
        sys.stdout.buffer.write((msg + "\n").encode("utf-8", "replace"))


def _account_rows(rs: list[list]) -> int:
    """재무제표 파일에서 금액이 있는 줄 수(계정별판 · 표시과목판 · 빈 파일을 가르는 데 쓴다)."""
    n = 0
    for r in rs[2:]:
        if r and r[0] is not None and any(c not in (None, "") for c in list(r)[1:5]):
            n += 1
    return n


def _pick_fs(cands: list[tuple[str, list]], files: list[dict]) -> list | None:
    """같은 종류 재무제표가 여럿이면 금액 줄이 가장 많은 것(계정별판)을 쓴다. 나머지는 같은 내용이면 duplicate_of,
    다르면 ignored 로 남긴다."""
    if not cands:
        return None
    best_rel, best = max(cands, key=lambda c: _account_rows(c[1]))
    for rel, rs in cands:
        if rel == best_rel:
            continue
        e = next(x for x in files if x["path"] == rel)
        if rs == best:
            e["duplicate_of"] = best_rel
        else:
            e["ignored"] = best_rel
            e["note"] = "금액 줄이 더 많은 같은 종류 파일을 썼습니다(표시과목판 · 빈 파일로 봅니다)"
    return best


def read_case(case: Case) -> tuple[dict, list]:
    """받은자료를 읽어 (장부 dict, 분개장 줄 목록). 필수 입력이 없으면 MissingInput."""
    recv = case.received
    if not recv.is_dir():
        raise MissingInput(f"받은자료 폴더가 없습니다: {recv}")
    paths = sorted(p for p in recv.rglob("*") if p.is_file() and not p.name.startswith("~$"))
    files: list[dict] = []
    journals: list[tuple[str, str, list]] = []
    bs_c: list[tuple[str, list]] = []
    is_c: list[tuple[str, list]] = []
    pfs = []                     # (PartnerFile, entry)
    tb = None
    unreadable = []
    for p in paths:
        kind, rs, form = sniff(p)
        rel = case.rel(p)
        entry = {"path": rel, "kind": kind if kind != "unreadable" else "unknown", "rows": 0}
        if form and kind in ("journal", "account_detail", "partner_ledger", "trial_balance"):
            entry["form"] = form
        files.append(entry)
        if kind == "unreadable":
            unreadable.append(rel)
            entry["note"] = "읽지 못함"
        elif kind == "journal":
            journals.append((rel, form, rs))
        elif kind == "bs":
            bs_c.append((rel, rs))
            entry["rows"] = sum(1 for r in rs[2:] if r and r[0] is not None)
        elif kind == "is":
            is_c.append((rel, rs))
            entry["rows"] = sum(1 for r in rs[2:] if r and r[0] is not None)
        elif kind == "partner_ledger":
            pf = parse_a(rel, rs, account_hint(p.name))
            pfs.append((pf, entry))
            entry["rows"] = len(pf.rows)
        elif kind == "account_detail":
            parts = douzone.blocks_to_files(rel, douzone.parse_blocks(rs)) if form == "douzone_blocks" else parse_b(rel, rs)
            for pf in parts:
                pfs.append((pf, entry))
            entry["rows"] = sum(len(pf.rows) for pf in parts)
        elif kind == "trial_balance":
            if tb is None:
                tb = douzone.parse_tb(rs)
                entry["rows"] = len(tb)
            else:
                entry["ignored"] = next(f["path"] for f in files if f["kind"] == "trial_balance")
    bs_rows = _pick_fs(bs_c, files)
    is_rows = _pick_fs(is_c, files)
    missing = [nm for nm, ok in (("분개장", journals), ("재무상태표", bs_rows), ("손익계산서", is_rows)) if not ok]
    if missing:
        extra = f" (읽지 못한 파일: {', '.join(unreadable)})" if unreadable else ""
        raise MissingInput(f"받은자료에서 {' · '.join(missing)} 을 찾지 못했습니다{extra}")
    forms = {f for _, f, _ in journals}
    if len(forms) > 1:
        raise MissingInput(f"분개장 꼴이 섞여 있습니다({' · '.join(sorted(forms))}). 한 프로그램에서 내려받은 분개장만 두세요")

    # 분개장 여러 개(분기별 등)는 이어 붙인다. 파일마다 합계 줄과 대조하고, 모든 파일에 합계 줄이 있으면 합을 남긴다
    jr = None
    totals = []
    for rel, form, rs in journals:
        j = douzone.parse_journal(rs) if form == "douzone_erp" else jmod.parse(rs)
        e = next(x for x in files if x["path"] == rel)
        e["rows"] = len(j.lines)
        if j.total_row:
            dr = sum(x.debit for x in j.lines)
            cr = sum(x.credit for x in j.lines)
            if (dr, cr) != (j.total_row["debit"], j.total_row["credit"]):
                e["note"] = f"파일 합계 줄(차변 {j.total_row['debit']:,} · 대변 {j.total_row['credit']:,})과 줄 합계가 다릅니다"
        totals.append(j.total_row)
        if jr is None:
            jr = j
        else:
            jr.lines.extend(j.lines)
    if len(journals) > 1:
        jr.total_row = None
        if all(totals):
            jr.total_row = {"debit": sum(t["debit"] for t in totals), "credit": sum(t["credit"] for t in totals),
                            "count": None}
        jmod.mark(jr)

    bs = fsmod.parse_bs(bs_rows)
    is_ = fsmod.parse_is(is_rows)
    ledger = build(journal=jr, bs=bs, is_=is_, pfs=[pf for pf, _ in pfs], files=files, tb=tb)
    by_entry: dict[int, list] = {}
    for pf, entry in pfs:
        by_entry.setdefault(id(entry), []).append(pf)
    for pf_list in by_entry.values():
        entry = next(e for pf, e in pfs if pf is pf_list[0])
        if len(pf_list) == 1 and not pf_list[0].part:
            pf = pf_list[0]
            entry["account"] = pf.account
            entry["account_how"] = pf.how
            if pf.duplicate_of:
                entry["duplicate_of"] = pf.duplicate_of
            if pf.notes:
                entry["notes"] = pf.notes
            continue
        # 한 파일에 계정이 여럿(B 꼴 여러 계정 · 더존 계정명세서 블록)
        entry["account"] = next((pf.account for pf in pf_list if pf.account), None)
        entry["accounts"] = [pf.account for pf in pf_list if pf.account]
        entry["parts"] = []
        for pf in pf_list:
            part = {"part": pf.part, "account": pf.account, "account_how": pf.how, "rows": len(pf.rows)}
            if pf.duplicate_of:
                part["duplicate_of"] = pf.duplicate_of
            if pf.notes:
                part["notes"] = pf.notes
            entry["parts"].append(part)
    return ledger, jr.lines


def write_csv(path: Path, lines) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(CSV_HEAD)
        for x in lines:
            wr.writerow([x.date, x.no, x.kind, x.account, x.account_name, x.debit, x.credit, x.partner_code,
                         x.partner, x.memo_code, x.memo, 1 if x.closing else 0, x.sub_account])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ctax read", description="받은자료를 읽어 _색인/장부.json · 전표.csv 를 쓴다")
    ap.add_argument("folder", help="신고 건 폴더(<회사>/<연도> 법인세)")
    args = ap.parse_args(argv)
    try:
        case = Case(args.folder)
        ledger, lines = read_case(case)
    except MissingInput as e:
        _out(str(e))
        try:
            Case(args.folder).mark_step("read", False, str(e), [])
        except MissingInput:
            pass
        return 2
    case.write_json("장부.json", ledger)
    write_csv(case.index_path("전표.csv"), lines)
    checks = ledger["checks"]
    passed = sum(1 for c in checks if c["ok"])
    ok = passed == len(checks)
    note = f"분개장 {len(lines):,}줄 · 대사 {len(checks)}개 중 {passed}개 통과"
    if not ok:
        note += " · 실패: " + ", ".join(c["id"] for c in checks if not c["ok"])
    case.mark_step("read", ok, note, ["_색인/장부.json", "_색인/전표.csv"])
    _out(f"{case.company} {case.fy}: {note}")
    for c in checks:
        _out(f"  [{'통과' if c['ok'] else '실패'}] {c['id']}: {c['detail']}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
