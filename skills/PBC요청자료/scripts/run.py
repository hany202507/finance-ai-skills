# -*- coding: utf-8 -*-
"""PBC요청자료 실행기. 감사 폴더 하나에서 요청자료 목록 · 빠진 자료 · 요청 메일 초안을 만든다.

    python run.py new   <감사 폴더> --company 회사 --fy-end 2025-12-31 [--fy-start 2025-01-01] [--first-year]
    python run.py start <감사 폴더> [--no-ocr]   받은자료를 읽고 요청자료 목록(PBC) · 요청 메일 초안 · 1100 · 1200 · 2100 초안을 만든다
    python run.py text  <PDF>                PDF 쪽마다 글자를 보인다(AI 가 판독 필요 항목을 읽을 때)
    python run.py apply <감사 폴더> <patch.json>   AI · 사람 판독(전기 감사인 · 의견 · 강조사항 · 업종)을 넣는다. 숫자는 넣지 못한다
    python run.py next  <감사 폴더>          빠진 자료와 다음 할 일을 다시 정한다(자료가 더 들어온 뒤)
    python run.py mail  <감사 폴더>          지금 빠진 자료로 요청 메일 초안을 다시 쓴다
    python run.py sent  <감사 폴더> 2026-01-21   메일을 보낸 날을 빠진 자료에 적는다(다음 요청은 「다시 요청」 으로 묶인다)

받은자료는 <감사 폴더>/00 받은자료/ 아래 표준 폴더(전기 · 회사제시 · 분개장 · 명세서 · 세무신고 · 의사록 · 계약서 · 잔액증명 …)에 넣는다.
엔진은 판단하지 않는다. 받음 · 빠짐은 파일과 판독 사실로 정하고, 메일은 회계사가 보낸다.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass


def _new(a) -> int:
    from audit import folder

    d = folder.scaffold(Path(a.dir), a.company, a.fy_end, "초도감사" if a.first_year else "계속감사", fiscal_year_start=a.fy_start)
    print(f"감사 폴더를 만들었습니다: {d}")
    print("받은자료는 00 받은자료 아래 폴더에 넣습니다: 전기 · 회사제시 · 분개장 · 명세서 · 세무신고 · 의사록 · 계약서 · 잔액증명")
    return 0


def _start(a) -> int:
    from audit import index, start

    d = Path(a.dir)
    r0 = index.read_all(d, use_ocr=not a.no_ocr)
    r = start.build(d)
    c = r["company"]
    print(f"회사 {c['name']} · 업종 {c.get('industry') or '판독 필요'}")
    pr = r.get("prior_report")
    if pr:
        print(f"전기 감사보고서 {pr['path']}: 감사인 {pr.get('auditor') or '판독 필요'} · 의견 {pr.get('opinion') or '판독 필요'}")
    print(f"전기 재무제표 출처: {r.get('prior_fs_basis') or '없음'}")
    got = sum(1 for x in r["pbc"] if x["status"] == "받음")
    print(f"요청자료 {got} / {len(r['pbc'])} 받음 · 빠진 자료 {len(r['missing'])}건")
    for m in r["missing"]:
        print(f"  - {m.get('item') if isinstance(m, dict) else m}")
    if r.get("mail"):
        print(f"요청 메일 초안: {r['mail']}")
    print(f"만든 파일 {len(r['wrote'])}개")
    for p in r["wrote"]:
        print(f"  {p}")
    for p in r0.get("need_ai") or []:
        print(f"  AI 판독 필요(스캔본 · 문서): {p}")
    for w in r["warnings"]:
        print(f"  주의: {w}")
    return 0


def _text(a) -> int:
    from audit import index, reader

    pages = reader.pdf_text(Path(a.pdf))
    empty = 0
    for no, text in pages:
        print(f"--- {no}쪽")
        if len("".join(text.split())) < index.NO_TEXT_MIN:
            empty += 1
            print("(이 쪽은 글자 층이 없습니다. 쪽 그림으로 읽어야 합니다)")
        print(text.rstrip())
    if pages and empty == len(pages):
        print(f"주의: 글자 층이 없는 PDF 입니다(스캔본, {len(pages)}쪽). 쪽 그림으로 읽어 주십시오")
    return 0


def _apply(a) -> int:
    from audit import index, start

    patch = json.loads(Path(a.patch).read_text(encoding="utf-8"))
    try:
        r = start.apply(Path(a.dir), patch)
    except index.PatchRejected as e:
        print("patch 를 거부했습니다. 아무것도 바꾸지 않았습니다")
        for p in e.problems:
            print(f"  {p}")
        return 1
    print(f"판독을 넣고 조서를 다시 만들었습니다. 만든 파일 {len(r['wrote'])}개")
    pr = r.get("prior_report") or {}
    if pr:
        print(f"전기 감사보고서: 감사인 {pr.get('auditor') or '판독 필요'} · 의견 {pr.get('opinion') or '판독 필요'}")
    return 0


def _next(a) -> int:
    from audit import director, folder

    d = Path(a.dir)
    folder.scan(d, quiet_log=True)
    r = director.run(d)
    print(f"단계 {r['stage']} · 빠진 자료 {len(r['missing'])}건")
    for m in r["missing"]:
        print(f"  - {director.item_text(m)}")
    for n, x in enumerate(r["next_actions"], 1):
        print(f"{n}. [{x['who']}] {x['title']}")
    return 0


def _mail(a) -> int:
    from audit import start

    p = start.write_mail(Path(a.dir))
    print(f"요청 메일 초안: {p}" if p else "빠진 자료가 없어 메일 초안을 만들지 않았습니다")
    return 0


def _sent(a) -> int:
    from audit import start

    n = start.mark_requested(Path(a.dir), a.date)
    print(f"빠진 자료 {n}건에 요청한 날 {a.date} 을 적었습니다")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="PBC요청자료")
    sub = ap.add_subparsers(dest="cmd", required=True)
    n = sub.add_parser("new", help="감사 폴더를 표준대로 만든다")
    n.add_argument("dir")
    n.add_argument("--company", required=True)
    n.add_argument("--fy-end", required=True)
    n.add_argument("--fy-start", default=None)
    n.add_argument("--first-year", action="store_true", help="초도감사(전기 감사인이 다르거나 처음 감사)")
    n.set_defaults(func=_new)
    s = sub.add_parser("start", help="받은자료를 읽고 요청자료 목록 · 빠진 자료 · 메일 초안을 만든다")
    s.add_argument("dir")
    s.add_argument("--no-ocr", action="store_true", help="스캔 PDF 에 kordoc OCR 을 돌리지 않는다")
    s.set_defaults(func=_start)
    x = sub.add_parser("text", help="PDF 글자 보기")
    x.add_argument("pdf")
    x.set_defaults(func=_text)
    y = sub.add_parser("apply", help="AI · 사람 판독 넣기")
    y.add_argument("dir")
    y.add_argument("patch")
    y.set_defaults(func=_apply)
    for name, fn, h in (("next", _next, "빠진 자료와 다음 할 일"), ("mail", _mail, "요청 메일 초안 다시 쓰기")):
        p = sub.add_parser(name, help=h)
        p.add_argument("dir")
        p.set_defaults(func=fn)
    t = sub.add_parser("sent", help="메일 보낸 날 적기")
    t.add_argument("dir")
    t.add_argument("date")
    t.set_defaults(func=_sent)
    a = ap.parse_args(argv)
    try:
        return a.func(a)
    except Exception as e:  # noqa: BLE001  엔진 오류 문장은 회계사용 안내다
        print(f"멈춤: {type(e).__name__}: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
