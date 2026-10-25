# -*- coding: utf-8 -*-
"""엔진 결과에 없는 숫자를 쓰고 싶을 때의 두 통로. 숫자는 여기서 만들고 글에는 그 값이나 id 를 쓴다.

  ar.py sum <신고건> --what "법인세 환급 줄" (--lines 12,15,40-42 | --account 901 [--memo 정규식] [--partner 정규식])
      전표.csv 줄의 차변 · 대변 · 순액 합계를 엔진이 계산한다(id s1, s2 …).
  ar.py pdf <신고건> --page 37 --form 29 --what "업무외사용금액" --amount 5930000
      엔진이 못 읽은 전기 신고서 PDF 값을 사람이 읽은 대로 적는다(id p1 …, 확인 전 표시). 쪽 · 서식이 필수다.
  ar.py facts <신고건>        적어 둔 것 보기

적은 숫자는 단계 파일 · 공제 제안 글에 써도 검사에 걸리지 않는다. 이슈 메모 글은 엔진 검사가 AR.json 숫자만 받으므로
메모의 "facts": ["s1"] 로 가리키면 화면 · 엑셀에 그 숫자가 함께 나온다.
"""
from __future__ import annotations

import argparse
import re
from datetime import datetime

from bestar import numbers, paths

FILE = "사실.json"


def path(c):
    return paths.steps_dir(c) / FILE


def load(c) -> list[dict]:
    return paths.read_json(path(c), []) or []


def amounts(c) -> set[int]:
    out = set()
    for f in load(c):
        for k in ("debit", "credit", "net", "amount"):
            v = f.get(k)
            if isinstance(v, (int, float)):
                out.add(abs(int(v)))
    return out


def _lines(spec: str) -> list[int]:
    out = []
    for part in spec.split(","):
        part = part.strip()
        if re.fullmatch(r"\d+-\d+", part):
            a, b = map(int, part.split("-"))
            out += list(range(a, b + 1))
        elif part.isdigit():
            out.append(int(part))
        elif part:
            raise ValueError(f"줄 번호를 읽지 못했습니다: {part}")
    return out


def _num(v) -> int:
    try:
        return int(round(float(v or 0)))
    except ValueError:
        return 0


def add(c, entry: dict, prefix: str) -> dict:
    data = load(c)
    n = 1 + max([int(f["id"][1:]) for f in data if f.get("id", "").startswith(prefix)] or [0])
    entry = {"id": f"{prefix}{n}", **entry, "at": datetime.now().isoformat(timespec="seconds")}
    data.append(entry)
    paths.write_json(path(c), data)
    return entry


def cmd_sum(c, a) -> int:
    rows = numbers.journal_rows(c)
    if not rows:
        print("전표.csv 가 없습니다. 먼저 ar.py engine 을 돌리세요")
        return 2
    if a.lines:
        try:
            want = set(_lines(a.lines))
        except ValueError as e:
            print(e)
            return 2
        picked = [r for r in rows if r["line"] in want]
        missing = sorted(want - {r["line"] for r in picked})
        if missing:
            print(f"전표.csv 에 없는 줄: {missing[:10]}")
            return 1
        rule = f"줄 {a.lines}"
    elif a.account:
        acc = [x.strip() for x in a.account.split(",")]
        memo = re.compile(a.memo) if a.memo else None
        partner = re.compile(a.partner) if a.partner else None
        picked = [r for r in rows if str(r.get("account")) in acc and str(r.get("closing")) not in ("1", "True", "true")
                  and (not memo or memo.search(r.get("memo") or "")) and (not partner or partner.search(r.get("partner") or ""))]
        rule = f"계정 {a.account}" + (f" 적요 /{a.memo}/" if a.memo else "") + (f" 거래처 /{a.partner}/" if a.partner else "") + " (손익 마감 줄 제외)"
    else:
        print("--lines 나 --account 가 필요합니다")
        return 2
    if not picked:
        print("고른 줄이 없습니다")
        return 1
    dr, cr = sum(_num(r["debit"]) for r in picked), sum(_num(r["credit"]) for r in picked)
    e = add(c, {"type": "합계", "what": a.what, "rule": rule, "count": len(picked), "debit": dr, "credit": cr, "net": dr - cr,
                "lines": [r["line"] for r in picked][:200], "by": "엔진"}, "s")
    print(f"{e['id']} {a.what}: {len(picked)}줄 · 차변 {dr:,} · 대변 {cr:,} · 순액 {dr - cr:,}")
    return 0


def cmd_pdf(c, a) -> int:
    pdfs = list((c.root / "00 받은자료" / "전기").glob("*.pdf"))
    if not pdfs:
        print("00 받은자료/전기/ 에 전기 신고서 PDF 가 없습니다")
        return 2
    e = add(c, {"type": "전기 PDF", "what": a.what, "form": a.form, "page": a.page, "amount": a.amount,
                "pdf": pdfs[0].name, "by": "AI 판독", "confirmed": False}, "p")
    print(f"{e['id']} 전기 {a.form}호 {a.page}쪽 {a.what}: {a.amount:,}원 (AI 판독, 확인 전)")
    return 0


def cmd_list(c) -> int:
    for f in load(c):
        if f["type"] == "합계":
            print(f"{f['id']} [합계] {f['what']}: {f['rule']} {f['count']}줄 차변 {f['debit']:,} 대변 {f['credit']:,} 순액 {f['net']:,}")
        else:
            print(f"{f['id']} [전기 PDF] {f['form']}호 {f['page']}쪽 {f['what']}: {f['amount']:,}")
    return 0


def main(cmd: str, argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog=f"ar.py {cmd}")
    p.add_argument("folder")
    if cmd == "sum":
        p.add_argument("--what", required=True)
        p.add_argument("--lines")
        p.add_argument("--account")
        p.add_argument("--memo")
        p.add_argument("--partner")
    elif cmd == "pdf":
        p.add_argument("--page", type=int, required=True)
        p.add_argument("--form", required=True)
        p.add_argument("--what", required=True)
        p.add_argument("--amount", type=int, required=True)
    a = p.parse_args(argv)
    c = paths.case(a.folder)
    return {"sum": lambda: cmd_sum(c, a), "pdf": lambda: cmd_pdf(c, a), "facts": lambda: cmd_list(c)}[cmd]()
