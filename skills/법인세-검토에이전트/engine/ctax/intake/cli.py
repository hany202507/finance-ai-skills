"""`python -m ctax read <신고 건 폴더>`: 받은자료 xlsx · xls 를 머리줄로 가려 읽고 _색인/장부.json · 전표.csv 를 쓴다.

읽는 꼴: 위하고(분개장 11열 · 재무제표 5열 · 거래처원장 A 꼴 · 계정명세서 B 꼴), 더존 ERP(분개장 10열 7자 코드 ·
재무제표 5열 · 계정명세서 BIFF 블록 · 합계잔액시산표).

끝 코드: 0 대사 통과, 1 대사 실패가 있음, 2 신고 건 폴더 · 분개장 · 재무상태표 · 손익계산서가 없거나 읽지 못함.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import sys
from collections import Counter
from pathlib import Path

from ..case import Case, MissingInput
from . import douzone
from . import fs as fsmod
from . import journal as jmod
from . import stale as stale_mod
from . import unread
from .build import build
from .partners import parse_a, parse_b
from .sniff import account_hint, sniff_sheets
from .xlsxread import SHOW_BAD, Cells

CSV_HEAD = ["date", "no", "kind", "account", "account_name", "debit", "credit", "partner_code", "partner",
            "memo_code", "memo", "closing", "sub_account", "src_file", "src_row"]      # src_*: 원본 파일 · 행(11-01)
# 시트는 열로 더하지 않는다(test_intake_douzone 이 끝 세 열을 고정). 시트가 여럿인 파일은 장부.json files[].sheet 에 있다(11-08)


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


def _pick_fs(cands: list[dict]) -> dict | None:
    """같은 종류 재무제표가 여럿이면 금액 줄이 가장 많은 것(계정별판)을 쓴다. 나머지는 같은 내용이면 duplicate_of,
    다르면 ignored 로 남긴다. cands 의 줄은 {rel, rows, entry, ctx}."""
    if not cands:
        return None
    best = max(cands, key=lambda c: _account_rows(c["rows"]))
    for c in cands:
        if c is best:
            continue
        e = c["entry"]
        if c["rows"] == best["rows"]:
            e["duplicate_of"] = best["key"]
        else:
            e["ignored"] = best["key"]
            e["note"] = "금액 줄이 더 많은 같은 종류 파일을 썼습니다(표시과목판 · 빈 파일로 봅니다)"
    return best


SHOW_NAMES = 10
OVERLAP = 0.5                    # 두 분개장 줄이 서로 이 비율을 넘게 겹치면 알린다(C3, 11-08)


def _names(xs: list[str]) -> str:
    return ", ".join(xs[:SHOW_NAMES]) + (f" 외 {len(xs) - SHOW_NAMES}개" if len(xs) > SHOW_NAMES else "")


def _content_sha256(rows: list[list]) -> str:
    """분개장 시트 내용(머리줄부터의 칸 값) sha256. 같은 분개장을 두 번 받으면 이름 · 저장 시각이 달라도 같다(제품 vfs.build_tree)."""
    h = hashlib.sha256()
    for r in rows:
        h.update(repr(tuple(r)).encode("utf-8"))
    return h.hexdigest()


def _line_keys(lines) -> Counter:
    return Counter((x.date, x.no, x.debit, x.credit) for x in lines)


def _note(entry: dict, msg: str) -> None:
    entry.setdefault("notes", []).append(msg)


def read_case(case: Case) -> tuple[dict, list]:
    """받은자료를 읽어 (장부 dict, 분개장 줄 목록). 필수 입력이 없으면 MissingInput.

    파일마다 시트를 모두 보고(sniff_sheets) 종류를 가린 시트마다 files 줄을 하나씩 만든다. 시트가 여럿인 파일(또는 첫 시트가 아닌
    시트를 읽은 파일)의 줄에만 `sheet` 를 적는다. 같은 분개장 내용이 두 번 오면 뒤의 것은 duplicate_of 로 두고 읽지 않는다(11-08)."""
    recv = case.received
    if not recv.is_dir():
        raise MissingInput(f"받은자료 폴더가 없습니다: {recv}")
    paths = sorted(p for p in recv.rglob("*") if p.is_file() and not p.name.startswith("~$"))
    files: list[dict] = []
    journals: list[dict] = []
    bs_c: list[dict] = []
    is_c: list[dict] = []
    pfs = []                     # (PartnerFile, entry)
    ctxs: list[tuple[dict, Cells]] = []
    tb = None
    unreadable, unknown = [], []
    seen_journal: dict[str, str] = {}
    for p in paths:
        rel = case.rel(p)
        try:
            sha = stale_mod.sha1(p)          # 같은 이름으로 바꿔 넣은 파일을 찾는다(intake/stale.py, 10-31)
        except OSError:
            sha = None
        pieces = sniff_sheets(p)
        known = [x for x in pieces if x.kind != "unknown"]
        if not known:
            known = pieces[:1]
        skipped = [x.sheet for x in pieces if x.kind == "unknown" and x not in known]
        for n, pc in enumerate(known):
            kind, rs, form = pc.kind, pc.rows, pc.form
            entry = {"path": rel, "kind": kind if kind != "unreadable" else "unknown", "rows": 0}
            if sha is not None:
                entry["sha1"] = sha
            if form and kind in ("journal", "account_detail", "partner_ledger", "trial_balance"):
                entry["form"] = form
            on_sheet = kind not in ("unknown", "unreadable", "prior_pdf") and (len(pieces) > 1 or pc.index > 0)
            if on_sheet:
                entry["sheet"] = pc.sheet
            key = f"{rel}#{pc.sheet}" if on_sheet else rel
            for msg in pc.notes:
                _note(entry, msg)
            if n == 0 and skipped:
                _note(entry, f"종류를 알 수 없는 시트 {len(skipped)}개는 읽지 않았습니다: {_names(skipped)}")
            files.append(entry)
            ctx = Cells(sheet=pc.sheet, off=pc.off)
            if kind == "unreadable":
                unreadable.append(rel)
                entry["note"] = "읽지 못함"
            elif kind == "unknown":
                if pc.kind != "prior_pdf":
                    unknown.append(rel)
            elif kind == "journal":
                digest = _content_sha256(rs)
                entry["content_sha256"] = digest
                if digest in seen_journal:
                    entry["duplicate_of"] = seen_journal[digest]
                    continue
                seen_journal[digest] = key
                journals.append({"rel": rel, "key": key, "form": form, "rows": rs, "entry": entry, "ctx": ctx})
            elif kind == "bs":
                bs_c.append({"rel": rel, "key": key, "rows": rs, "entry": entry, "ctx": ctx})
                entry["rows"] = sum(1 for r in rs[2:] if r and r[0] is not None)
            elif kind == "is":
                is_c.append({"rel": rel, "key": key, "rows": rs, "entry": entry, "ctx": ctx})
                entry["rows"] = sum(1 for r in rs[2:] if r and r[0] is not None)
            elif kind == "partner_ledger":
                pf = parse_a(rel, rs, account_hint(p.name), ctx)
                pfs.append((pf, entry))
                ctxs.append((entry, ctx))
                entry["rows"] = len(pf.rows)
            elif kind == "account_detail":
                if form == "douzone_blocks":
                    parts = douzone.blocks_to_files(rel, douzone.parse_blocks(rs))
                else:
                    parts = parse_b(rel, rs, ctx)
                    ctxs.append((entry, ctx))
                for pf in parts:
                    pfs.append((pf, entry))
                entry["rows"] = sum(len(pf.rows) for pf in parts)
            elif kind == "trial_balance":
                if tb is None:
                    tb = douzone.parse_tb(rs)
                    entry["rows"] = len(tb)
                else:
                    entry["ignored"] = next(f["path"] for f in files if f["kind"] == "trial_balance")
    bs_pick = _pick_fs(bs_c)
    is_pick = _pick_fs(is_c)
    missing = [nm for nm, ok in (("분개장", journals), ("재무상태표", bs_pick), ("손익계산서", is_pick)) if not ok]
    if missing:
        bits = []
        if unreadable:
            bits.append(f"읽지 못한 파일: {_names(unreadable)}")
        if unknown:                            # 종류를 가리지 못한 파일도 이름을 보인다(11-08)
            bits.append(f"종류를 알 수 없는 파일: {_names(unknown)}")
        extra = f" ({' · '.join(bits)})" if bits else ""
        last = missing[-1][-1]                 # 받침이 있으면 「을」, 없으면 「를」(10-31 QA 결함 5)
        josa = "을" if "가" <= last <= "힣" and (ord(last) - 0xAC00) % 28 else "를"
        raise MissingInput(f"받은자료에서 {' · '.join(missing)}{josa} 찾지 못했습니다{extra}")
    forms = {j["form"] for j in journals}
    if len(forms) > 1:
        raise MissingInput(f"분개장 꼴이 섞여 있습니다({' · '.join(sorted(forms))}). 한 프로그램에서 내려받은 분개장만 두세요")

    # 분개장 여러 개(분기별 등)는 이어 붙인다. 파일마다 합계 줄과 대조하고, 모든 파일에 합계 줄이 있으면 합을 남긴다
    jr = None
    totals = []
    warns: list[dict] = []
    keyed: list[tuple[dict, dict, Counter]] = []
    for jd in journals:
        rel, form, rs, e, ctx = jd["rel"], jd["form"], jd["rows"], jd["entry"], jd["ctx"]
        j = douzone.parse_journal(rs, ctx) if form == "douzone_erp" else jmod.parse(rs, ctx)
        ctxs.append((e, ctx))
        for x in j.lines:
            x.src_file = rel
            x.src_sheet = e.get("sheet", "")
        w = _journal_unread(rel, form, rs, ctx.off)
        if w:
            warns.append(w)
        e["rows"] = len(j.lines)
        if j.total_row:
            dr = sum(x.debit for x in j.lines)
            cr = sum(x.credit for x in j.lines)
            if (dr, cr) != (j.total_row["debit"], j.total_row["credit"]):
                e["note"] = f"파일 합계 줄(차변 {j.total_row['debit']:,} · 대변 {j.total_row['credit']:,})과 줄 합계가 다릅니다"
        totals.append(j.total_row)
        keyed.append((jd, e, _line_keys(j.lines)))
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
    warns += _overlaps(keyed)

    fs_files = {}
    picked = {}
    for key, pick, parse in (("bs", bs_pick, fsmod.parse_bs), ("is", is_pick, fsmod.parse_is)):
        fs_files[f"{key}_file"] = pick["rel"]
        if pick["entry"].get("sheet"):
            fs_files[f"{key}_sheet"] = pick["entry"]["sheet"]
        w = unread.fs_unread(pick["rel"], pick["rows"], pick["ctx"].off)
        if w:
            warns.append(w)
        picked[key] = parse(pick["rows"], pick["ctx"])
        ctxs.append((pick["entry"], pick["ctx"]))
    bs, is_ = picked["bs"], picked["is"]
    ledger = build(journal=jr, bs=bs, is_=is_, pfs=[pf for pf, _ in pfs], files=files, tb=tb)
    ledger["fs"].update(fs_files)                     # 재무제표 줄 src_row 가 가리키는 파일(11-01)
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
                entry["notes"] = list(pf.notes) + entry.get("notes", [])
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
    # 금액으로 읽지 못한 칸(C2): 칸을 0(빈 값)으로 두고 파일 notes 와 경고에 주소 · 원래 글을 남긴다
    for entry, ctx in ctxs:
        msg = ctx.note()
        if msg:
            _note(entry, msg)
            warns.append({"id": BAD_ID, "file": entry["path"] + (f"#{entry['sheet']}" if entry.get("sheet") else ""),
                          "title": BAD_TITLE, "cells": [{"cell": a, "text": t} for a, t in ctx.bad[:SHOW_BAD]],
                          "count": len(ctx.bad), "detail": msg})
    ledger["warnings"] = warns
    return ledger, jr.lines


BAD_ID, BAD_TITLE = "bad_cells", "금액으로 읽지 못한 칸"
OVERLAP_ID, OVERLAP_TITLE = "journal_overlap", "겹치는 분개장"


def _overlaps(keyed: list[tuple[dict, dict, Counter]]) -> list[dict]:
    """두 분개장의 (일자, 전표번호, 차변, 대변) 줄이 서로 절반 넘게 겹치면 두 파일 notes 와 경고에 남긴다. 읽기는 그대로 한다.
    분기 파일은 일자가 달라 겹치지 않는다. 같은 분개장을 다시 받았거나 기간이 겹치는 파일을 함께 받은 경우다."""
    out = []
    for i in range(len(keyed)):
        for k in range(i + 1, len(keyed)):
            (a, ea, ca), (b, eb, cb) = keyed[i], keyed[k]
            na, nb = sum(ca.values()), sum(cb.values())
            inter = sum((ca & cb).values())
            if not inter or inter <= na * OVERLAP or inter <= nb * OVERLAP:
                continue
            pa, pb = round(inter * 100 / na), round(inter * 100 / nb)
            detail = (f"{a['key']} 와 {b['key']} 의 (일자, 전표번호, 금액) 줄 {inter:,}개가 겹칩니다(앞 파일 줄의 {pa}% · 뒤 파일 줄의 "
                      f"{pb}%). 두 파일 모두 읽었습니다. 같은 분개장을 두 번 받았는지 확인합니다")
            _note(ea, f"{b['key']} 와 줄 {inter:,}개가 겹칩니다(이 파일 줄의 {pa}%). 같은 분개장인지 확인합니다")
            _note(eb, f"{a['key']} 와 줄 {inter:,}개가 겹칩니다(이 파일 줄의 {pb}%). 같은 분개장인지 확인합니다")
            out.append({"id": OVERLAP_ID, "file": b["key"], "title": OVERLAP_TITLE, "other": a["key"], "lines": inter,
                        "detail": detail})
    return out


def _journal_unread(rel: str, form: str, rs: list, off: int = 0) -> dict | None:
    """분개장에서 읽지 않은 금액 열(unread.journal_unread). 읽는 열은 꼴마다 머리 글로 정한다. off 는 건너뛴 제목 줄 수."""
    from .xlsxread import compact
    head = [compact(x) for x in (rs[0] if rs else [])]
    if form == "douzone_erp":
        names = ("승인일", "승인번호", "차변금액", "차변계정과목", "대변계정과목", "대변금액", "적요", "거래처코드", "거래처명", "작성일")
        ix = {k: head.index(k) for k in names if k in head}
        return unread.journal_unread(rel, rs, set(ix.values()), ix.get("승인일"),
                                     (ix.get("차변계정과목"), ix.get("차변금액"), ix.get("대변계정과목"), ix.get("대변금액")), off=off)
    ix = jmod._cols(rs[0] if rs else [])
    return unread.journal_unread(rel, rs, {v for v in ix.values() if v is not None}, ix.get("전표일자"), off=off)


def write_csv(path: Path, lines) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(CSV_HEAD)
        for x in lines:
            wr.writerow([x.date, x.no, x.kind, x.account, x.account_name, x.debit, x.credit, x.partner_code,
                         x.partner, x.memo_code, x.memo, 1 if x.closing else 0, x.sub_account, x.src_file, x.src_row or ""])


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
    soft = [c["id"] for c in checks if c["ok"] and c.get("warn")]
    if soft:
        note += " · 경고: " + ", ".join(soft)
    warns = ledger.get("warnings") or []
    if warns:
        kinds = Counter(w["title"] for w in warns)
        what = next(iter(kinds)) if len(kinds) == 1 else " · ".join(f"{t} {n}" for t, n in kinds.items())
        note += f" · 경고 {len(warns)}개({what})"
    case.mark_step("read", ok, note, ["_색인/장부.json", "_색인/전표.csv"])
    _out(f"{case.company} {case.fy}: {note}")
    for c in checks:
        _out(f"  [{('경고' if c.get('warn') else '통과') if c['ok'] else '실패'}] {c['id']}: {c['detail']}")
    for w in warns:
        _out(f"  [경고] {w['title']} {w['file']}: {w['detail']}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
