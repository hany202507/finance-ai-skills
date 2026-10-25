"""`python -m ctax ar <신고 건 폴더> [--memo <메모.json>]` (CONTRACT.md 7 · 14.1절).

ar: 장부.json · 전표.csv · 전기.json → _색인/AR.json, 1 AR/AR_이슈.xlsx. 앞 AR_이슈.xlsx 의 회계사 결론과 앞 AR.json 의
AI 메모를 이어받는다.
ar --memo: 지금 AR.json 에 AI 메모를 검사해 넣는다. 검사에 걸리면 끝 코드 1 과 문제 목록, 아무것도 넣지 않는다.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from ctax.ar import engine, excel, memo
from ctax.case import AR_DIR, INDEX, Case, MissingInput

XLSX_NAME = "AR_이슈.xlsx"


def _old_ar(case: Case) -> dict | None:
    try:
        return case.read_json("AR.json") if case.has("AR.json") else None
    except (ValueError, OSError):
        return None


def _write_xlsx(case: Case, ar: dict, ledger: dict | None, problems: list[str]) -> list[str]:
    xlsx_path = case.out_dir(AR_DIR) / XLSX_NAME
    try:
        excel.write(ar, xlsx_path, ledger, case.info())
        return [case.rel(xlsx_path)]
    except PermissionError:
        problems.append(f"{AR_DIR}/{XLSX_NAME} 을 쓸 수 없습니다(엑셀에서 열려 있으면 닫고 다시 돌리세요)")
        return []


def _allowed(case: Case) -> set | None:
    """메모 글에 써도 되는 AR.json 밖 금액: 조서 계산(조정.json)의 숫자. `--memo` 검사와 이어받기가 같은 집합을 쓴다(10-20)."""
    try:
        adjust = case.read_json("조정.json") if case.has("조정.json") else None
    except (ValueError, OSError):
        return None
    return memo.numbers_of(adjust) if adjust else None


def build(case: Case) -> int:
    try:
        ledger = case.need("read")
        prior = case.need("prior")
        jpath = case.root / (ledger.get("journal_csv") or f"{INDEX}/전표.csv")
        if not jpath.exists():
            raise MissingInput(f"{case.rel(jpath) if jpath.is_relative_to(case.root) else jpath} 이 없습니다. 먼저 ctax read 를 돌리세요")
        journal = engine.read_journal(jpath)
    except MissingInput as e:
        print(e)
        return 2

    info = case.info()
    ar = engine.build(ledger, journal, prior, info)
    rows = excel.read_conclusions(case.root / AR_DIR / XLSX_NAME)
    carried = memo.carry(ar, _old_ar(case), rows, allowed=_allowed(case))
    problems = engine.validate(ar)
    case.write_json("AR.json", ar)
    outputs = [f"{INDEX}/AR.json"] + _write_xlsx(case, ar, ledger, problems)

    kinds = Counter(i["kind"] for i in ar["issues"])
    status = Counter(g["status"] for g in ar["guide"])
    kind_text = " · ".join(f"{k} {kinds[k]}" for k in engine.KINDS if kinds.get(k))
    folded = sum(1 for i in ar["issues"] if i.get("folded"))
    note = (f"이슈 {len(ar['issues'])}건({kind_text})" + (f" · 작은 조정 후보 {folded}건 접음" if folded else "")
            + f" · 가이드 {len(ar['guide'])}줄 판정"
            f"(이슈 {status.get('이슈', 0)} · 해당 없음 {status.get('해당 없음', 0)} · 자료 필요 {status.get('자료 필요', 0)})")
    memos = sum(1 for i in ar["issues"] if i.get("memo"))
    concl = sum(1 for i in ar["issues"] if i.get("conclusion"))
    if memos or concl:
        note += f" · AI 메모 {memos}건 · 회계사 결론 {concl}건"
    if problems:
        note += " · 검사 실패: " + "; ".join(problems[:3])
    case.mark_step("ar", not problems, note, outputs)
    print(note)
    for iss in ar["issues"]:
        mark = " (접음)" if iss.get("folded") else ""
        print(f"  {iss['no']:>2}. [{iss['kind']} · {iss['certainty']}]{mark} {iss['title']}")
    for msg in carried:
        print(f"  {msg}")
    for msg in problems:
        print(f"  검사 실패: {msg}")
    return 1 if problems else 0


def put_memo(case: Case, memo_path: str) -> int:
    try:
        ar = case.need("ar")
    except MissingInput as e:
        print(e)
        return 2
    p = Path(memo_path)
    if not p.exists():
        print(f"메모 파일이 없습니다: {p}")
        return 2
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, UnicodeDecodeError) as e:
        print(f"메모 파일을 JSON 으로 읽지 못했습니다: {e}")
        return 2
    # 조서 계산 금액(조정.json)도 메모에 쓸 수 있다(10-19: 조서가 계산한 조정 금액을 메모 글에 못 쓰던 것)
    allowed = _allowed(case)
    problems = memo.validate(data, ar, allowed)
    if problems:
        print(f"메모 검사 실패 {len(problems)}건. 아무것도 넣지 않았습니다")
        for msg in problems:
            print(f"  {msg}")
        return 1
    # 엑셀을 다시 쓰기 전에 회계사가 적은 결론부터 읽어 둔다
    rows = excel.read_conclusions(case.root / AR_DIR / XLSX_NAME)
    carried = memo.carry(ar, json.loads(json.dumps(ar, ensure_ascii=False)), rows, allowed=allowed) if rows is not None else []
    carried = [c for c in carried if "결론" in c]
    n = memo.apply(data, ar)
    case.write_json("AR.json", ar)
    ledger = case.read_json("장부.json") if case.has("장부.json") else None
    problems = []
    outputs = [f"{INDEX}/AR.json"] + _write_xlsx(case, ar, ledger, problems)
    judg = Counter(i["memo"]["judgment"] for i in ar["issues"] if i.get("memo"))
    text = " · ".join(f"{k} {judg[k]}" for k in memo.JUDGMENTS if judg.get(k))
    prev = (case.info().get("steps") or {}).get("ar") or {}
    base = str(prev.get("note") or "").split(" · AI 메모")[0]
    note = f"{base} · AI 메모 {n}건 넣음({text})"
    case.mark_step("ar", bool(prev.get("ok", True)) and not problems, note, sorted(set((prev.get("outputs") or []) + outputs)))
    print(f"AI 메모 {n}건을 넣었습니다({text})")
    for msg in carried + problems:
        print(f"  {msg}")
    return 1 if problems else 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m ctax ar", description="분석적 검토(AR) 이슈 목록을 만듭니다")
    p.add_argument("folder", help="신고 건 폴더(<회사>/<연도> 법인세)")
    p.add_argument("--memo", help="AI 가 쓴 이슈 메모 JSON(법인세-AR 스킬). 지금 AR.json 에 검사해 넣습니다")
    args = p.parse_args(argv)
    try:
        case = Case(args.folder)
    except MissingInput as e:
        print(e)
        return 2
    if args.memo:
        return put_memo(case, args.memo)
    return build(case)


if __name__ == "__main__":
    raise SystemExit(main())
