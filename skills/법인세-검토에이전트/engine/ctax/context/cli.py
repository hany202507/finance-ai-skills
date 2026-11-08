"""`python -m ctax context <할 일> <신고 건 또는 회사 폴더> ...`: 회사 맥락(해마다 그대로인 회계사 답) 저장 · 조회 · 확인.

  save    <신고 건>                         이 신고 건의 회계사 답을 <회사>/_회사맥락/맥락.json 에 모은다(신고 건을 마칠 때)
  show    <신고 건|회사> [--kind 글] [--find 글] [--json]   맥락 보기(출처 · 이력 포함)
  add     <신고 건|회사> <종류> [대상] <값...> [--fy 연도] [--by 이름] [--note 글]
                                            조서 칸이 없는 것을 손으로 적는다(유가증권 · 주식변동 · 관계기업 · 업종코드 · 특수관계인 · 메모)
  add     <신고 건|회사> --kind 내년메모 --by AI --title <제목> --text <글> [--fy 연도]
                                            다음 해 계획서가 「작년 메모」 로 읽는 글. AI 글은 검사(금액 꼴 · 줄표 · 물음표)를 거쳐 확인 전으로 남는다
                                            (--kind · --text · --title 은 다른 손으로 적는 종류에도 쓸 수 있다)
  check   <신고 건> [--json]                  이 신고 건에 쓸 작년 답과 조서가 채운 칸(확인 전 · 확정 · 회계사가 바꿈)
  confirm <신고 건> <id...> | --all [--by 이름] [--no-wp] [--clear]
                                            작년 답을 회계사가 확인한다. 뒤에 ctax wp 를 다시 돌린다(--no-wp 면 안 돌린다)

작년 답은 노란 칸 기본값으로만 쓴다(「확인 전」). 확정은 회계사가 confirm 하거나 칸을 고칠 때다. 금액을 고치지 않는다.
끝 코드: 0 됨, 1 확인 전 작년 답이 남음(check) · wp 다시 돌리기 실패 · AI 글이 검사에 걸림(add), 2 폴더 · 값을 받지 못함.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .. import runlog
from ..case import Case, MissingInput
from . import apply, catalog, collect, store


def _out(msg: str) -> None:
    try:
        print(msg)
    except UnicodeEncodeError:
        sys.stdout.buffer.write((msg + "\n").encode("utf-8", "replace"))


def _src(f: dict) -> str:
    bits = [f"{f.get('fy')} 사업연도" if f.get("fy") else "", str(f.get("by") or ""), str(f.get("at") or "")[:10],
            str(f.get("from") or ""), "회계사 확인 전" if f.get("confirmed") is False else ""]
    return ", ".join(b for b in bits if b)


def _value(text: list[str]):
    """「취득일=2023-03-02 주식수=1000」 꼴이면 dict, 아니면 글."""
    if text and all("=" in t for t in text):
        return {k.strip(): v.strip() for k, v in (t.split("=", 1) for t in text)}
    return " ".join(text).strip()


def cmd_save(a) -> int:
    got = collect.save(a.folder)
    _out(f"회사 맥락에 모았습니다: {got['rows']}줄(새로 {got['새로']} · 바뀜 {got['바뀜']} · 같음 {got['같음']})\n  {got['path']}")
    return 0


def _facts(a) -> list[dict]:
    data = store.read(a.folder)
    rows = list(data["facts"].values())
    if a.kind:
        rows = [f for f in rows if a.kind in str(f.get("kind"))]
    if a.find:
        rows = [f for f in rows if a.find in json.dumps(f, ensure_ascii=False)]
    return sorted(rows, key=lambda f: (str(f.get("kind")), str(f.get("target"))))


def cmd_show(a) -> int:
    rows = _facts(a)
    if a.json:
        _out(json.dumps({"path": str(store.path(a.folder)), "facts": rows}, ensure_ascii=False, indent=1))
        return 0
    if not store.path(a.folder).exists():
        _out(f"회사 맥락이 없습니다: {store.path(a.folder)}. 신고 건을 마친 뒤 ctax context save 를 돌립니다")
        return 0
    _out(f"회사 맥락 {store.company_dir(a.folder).name}: {len(rows)}줄 ({store.path(a.folder)})")
    for f in rows:
        target = f" {f['target']}" if f.get("target") else ""
        hist = " · ".join(f"{h.get('fy')} {store.show_value(h.get('value'))}" for h in f.get("history") or [])
        _out(f"  [{f['kind']}]{target}: {store.show_value(f.get('value'))}  ({_src(f)})")
        if len(f.get("history") or []) > 1:
            _out(f"      이력: {hist}")
        if f.get("note"):
            _out(f"      메모: {f['note']}")
        _out(f"      id: {f['id']}")
    return 0


def cmd_add(a) -> int:
    kind = a.kind or a.what
    if not kind:
        _out(f"종류를 줍니다(<종류> 또는 --kind). 고를 수 있는 것: {' · '.join(catalog.MANUAL)}")
        return 2
    if kind not in catalog.MANUAL:
        _out(f"손으로 적는 종류가 아닙니다: {kind}. 고를 수 있는 것: {' · '.join(catalog.MANUAL)}")
        return 2
    words = ([a.what] if a.kind and a.what else []) + list(a.rest)
    text = str(a.text or "").strip()
    if kind == "업종코드":
        target, value = "", (text or _value(words))
    elif kind == catalog.NEXT_YEAR:
        value = text or " ".join(words).strip()
        target = str(a.title or "").strip() or str(value)[:30].strip()
    elif a.title:
        target, value = str(a.title).strip(), (text or _value(words))
    else:
        if len(words) < (1 if text else 2):
            _out(f"{kind} 은 대상과 값이 있어야 합니다({catalog.MANUAL[kind]})")
            return 2
        target, value = words[0], (text or _value(words[1:]))
    if not value:
        _out("값이 없습니다")
        return 2
    folder = Path(a.folder)
    fy = a.fy or (Case(folder).fy if folder.is_dir() and (folder / "_색인").is_dir() else "")
    if not fy:
        _out("사업연도를 모릅니다. --fy 2025 처럼 줍니다(신고 건 폴더를 주면 그 사업연도)")
        return 2
    by = a.by or runlog.caller()
    if kind == catalog.NEXT_YEAR:
        from ..memo_check import text_problems

        probs = text_problems("내년메모", str(value), allowed=None) + text_problems("제목", target, allowed=None)
        if probs:
            _out("내년메모를 넣지 않았습니다:\n" + "\n".join(f"  {x}" for x in probs))
            return 1
        fact, how = collect.add_next_year_memo(folder, str(fy), target, str(value), by=by, note=a.note,
                                               case_name=folder.name if (folder / "_색인").is_dir() else "")
        _out(f"적었습니다({how}): [{kind}] {target} = {store.show_value(fact.get('value'))} ({_src(fact)})\n  {store.path(folder)}")
        return 0
    data = store.read(folder)
    key = f"{kind}/{target}" if target else kind
    from datetime import datetime

    entry = {"fy": str(fy), "value": value, "by": by, "at": datetime.now().isoformat(timespec="seconds"),
             "from": "ctax context add", "case": folder.name if (folder / "_색인").is_dir() else "", "note": a.note}
    fact, how = store.put(data, catalog.fact_id(catalog.COMPANY, key), kind=kind, paper=catalog.COMPANY, key=key,
                          target=target, entry=entry)
    p = store.write(folder, data)
    _out(f"적었습니다({how}): [{kind}] {target} = {store.show_value(value)} ({_src(fact)})\n  {p}")
    return 0


def cmd_check(a) -> int:
    case = Case(a.folder)
    cands = apply.candidates(case)
    used = {(u["paper"], u["key"]): u for u in apply.used(case)}
    rows = []
    for c in cands:
        u = used.get((c["paper"], c["key"]))
        state = u["state"] if u else ("확정" if c["confirmed"] else "올해 조서에 없음")
        if u and c["confirmed"] and state == "확인 전":
            state = "확정(조서 다시 돌리기 전)"
        rows.append({**c, "state": state, "sheet": (u or {}).get("sheet", ""), "engine": (u or {}).get("engine", "")})
    if a.json:
        _out(json.dumps({"case": case.root.name, "fy": case.fy, "rows": rows}, ensure_ascii=False, indent=1))
    else:
        if not rows:
            _out(f"이 신고 건({case.fy})에 쓸 작년 답이 없습니다({store.path(case.root)})")
        for r in rows:
            where = f" · 조서 {r['sheet']}" if r["sheet"] else ""
            _out(f"  {r['state']:<6} [{r['kind']}] {r['target']}: 작년 답 {store.show_value(r['value'])} ({_src(r)}){where}\n"
                 f"         id: {r['id']}")
        waiting = [r for r in rows if r["state"] == "확인 전"]
        if waiting:
            _out(f"확인 전 {len(waiting)}칸. 맞으면 python -m ctax context confirm \"{case.root}\" --all, 다르면 조서 노란 칸을 고칩니다")
    return 1 if any(r["state"] == "확인 전" for r in rows) else 0


def cmd_confirm(a) -> int:
    case = Case(a.folder)
    if a.clear:
        n = apply.unconfirm(case, a.ids)
        _out(f"확인을 지웠습니다: {n}칸")
    else:
        ids = [c["id"] for c in apply.candidates(case)] if a.all else a.ids
        if not ids:
            _out("확인할 칸이 없습니다(id 를 주거나 --all)")
            return 2
        try:
            done = apply.confirm(case, ids, a.by or runlog.caller())
        except ValueError as e:
            _out(str(e))
            return 2
        for c in done:
            _out(f"  확정: [{c['kind']}] {c['target']} = {store.show_value(c['value'])} ({c['fy']} 사업연도 답)")
    if a.no_wp or not case.has("장부.json"):
        return 0
    from ..wp import cli as wp_cli

    _out("== ctax wp (조서 메모를 다시 씁니다)")
    return 1 if wp_cli.main([str(case.root)]) == 2 else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ctax context", description="회사 맥락(해마다 그대로인 회계사 답) 저장 · 조회 · 확인")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("save", help="신고 건의 회계사 답을 회사 맥락에 모은다")
    s.add_argument("folder")
    s = sub.add_parser("show", help="회사 맥락 보기")
    s.add_argument("folder")
    s.add_argument("--kind", default="")
    s.add_argument("--find", default="")
    s.add_argument("--json", action="store_true")
    s = sub.add_parser("add", help="손으로 적기(유가증권 · 주식변동 · 관계기업 · 업종코드 · 특수관계인 · 메모 · 내년메모)")
    s.add_argument("folder")
    s.add_argument("what", nargs="?", default="")
    s.add_argument("rest", nargs="*")
    s.add_argument("--kind", default="", help="종류(위치 인자 대신)")
    s.add_argument("--title", default="", help="대상 · 제목(위치 인자 대신)")
    s.add_argument("--text", default="", help="값 · 글(위치 인자 대신)")
    s.add_argument("--fy", default="")
    s.add_argument("--by", default="")
    s.add_argument("--note", default="")
    s = sub.add_parser("check", help="이 신고 건에 쓸 작년 답과 확인 상태")
    s.add_argument("folder")
    s.add_argument("--json", action="store_true")
    s = sub.add_parser("confirm", help="작년 답 확인")
    s.add_argument("folder")
    s.add_argument("ids", nargs="*")
    s.add_argument("--all", action="store_true")
    s.add_argument("--by", default="")
    s.add_argument("--no-wp", action="store_true")
    s.add_argument("--clear", action="store_true")
    a = ap.parse_args(argv)
    if not Path(a.folder).is_dir():
        _out(f"폴더가 없습니다: {a.folder}")
        return 2
    try:
        return {"save": cmd_save, "show": cmd_show, "add": cmd_add, "check": cmd_check, "confirm": cmd_confirm}[a.cmd](a)
    except (MissingInput, ValueError) as e:
        _out(str(e))
        return 2


if __name__ == "__main__":
    sys.exit(main())
