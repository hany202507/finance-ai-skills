"""`python -m ctax startup <신고 건 폴더>`: 창업중소기업 세액감면(조특법 제6조) 검증 워크북과 세액감면신청서를 만든다.

읽는 것  00 받은자료/창업감면/창업감면_입력.xlsx (`--template` 빈 양식, `--sample` 합성 회사, `--input` 다른 파일)
쓰는 것  2 조서/창업감면_검증.xlsx, 2 조서/창업감면_법정서식.pdf(법제처 별지 제2호서식 위에 값), _색인/창업감면.json,
         신고건.json 의 「창업감면」(ctax wp 조서 20 의 당기분 「창업중소기업 세액감면」 기본값)
끝 코드  0 검산 모두 통과, 1 확인할 검산 · 엔진 대조 불일치가 있음, 2 입력 없음 · 읽지 못함
"""
from __future__ import annotations

import argparse
from pathlib import Path

from openpyxl import load_workbook

from ..case import WP_DIR, Case, MissingInput, won
from ..formkit import recalc
from . import book, lawform, sample
from .calc import compute
from .model import INPUT_DIR, INPUT_NAME, InputError, load_rules, read_inputs

OUT_XLSX = "창업감면_검증.xlsx"
OUT_JSON = "창업감면.json"
INFO_KEY = "창업감면"
SOURCE = "ctax startup"


def _plain(v):
    return v if v is None or isinstance(v, (int, float, str, bool)) else str(v)


def read_back(path: Path) -> dict:
    wb = load_workbook(path, data_only=True)
    ws = wb[book.S_CHECK]
    bad, n = [], 0
    for row in ws.iter_rows(min_row=4, max_col=4, values_only=True):
        if row[0] in (None, "") or row[0] == "항목" or row[1] == "엔진 값":
            continue
        n += 1
        if row[3] != "일치":
            bad.append({"item": row[0], "engine": _plain(row[1]), "excel": _plain(row[2])})
    tests, on = [], False
    for row in wb[book.S_LIST].iter_rows(min_col=1, max_col=4, values_only=True):
        if row[0] == "검산" and row[1] == "결과":
            on = True
            continue
        if on:
            if row[1] not in ("통과", "확인"):
                break
            tests.append({"check": row[0], "result": row[1], "left": row[2], "right": row[3]})
    errors = [f"{s.title}!{c.coordinate}" for s in wb.worksheets for r in s.iter_rows() for c in r
              if isinstance(c.value, str) and c.value.startswith("#")]
    return {"matched": n - len(bad), "total": n, "bad": bad, "tests": tests, "errors": errors[:20]}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ctax startup", description="창업중소기업 세액감면(조특법 제6조) 검증 워크북과 세액감면신청서")
    ap.add_argument("folder", help="신고 건 폴더(<회사>/<연도> 법인세)")
    ap.add_argument("--input", help=f"입력 파일(없으면 {INPUT_DIR}/{INPUT_NAME})")
    ap.add_argument("--template", action="store_true", help="빈 입력 양식을 만들고 끝낸다")
    ap.add_argument("--sample", action="store_true", help="시험용 합성 회사 입력을 만들고 끝낸다")
    ap.add_argument("--no-excel", action="store_true", help="엑셀 재계산과 수식 값 대조를 하지 않는다")
    ap.add_argument("--keep", action="store_true", help="신고건.json 의 「창업감면」 을 고치지 않는다")
    args = ap.parse_args(argv)
    if args.sample or args.template or args.input:
        Path(args.folder).mkdir(parents=True, exist_ok=True)
    try:
        case = Case(args.folder)
    except MissingInput as e:
        print(f"입력이 없습니다: {e}")
        return 2
    src = Path(args.input) if args.input else case.root / INPUT_DIR / INPUT_NAME
    if args.sample or args.template:
        if src.exists():
            print(f"{src} 가 이미 있어 그대로 두었습니다")
            return 0
        sample.write(src, blank=args.template)
        print(f"{'빈 양식' if args.template else '시험용 입력(합성 회사)'}을 만들었습니다: {src}")
        if args.sample:
            print(f'이어서 python -m ctax startup "{args.folder}" 를 돌리십시오')
        return 0
    rules = load_rules()
    info = case.info()
    try:
        inp = read_inputs(src, rules, info.get("fy_start", ""), info.get("fy_end", ""))
    except InputError as e:
        print(f"입력을 읽지 못했습니다: {e}")
        return 2
    r = compute(inp, rules)
    wb, engine = book.build(inp, r, rules, r["notes"])
    out = case.out_dir(WP_DIR) / OUT_XLSX
    try:
        wb.save(out)
    except PermissionError:
        print(f"{out} 가 열려 있어 쓰지 못했습니다. 엑셀을 닫고 다시 돌리세요")
        return 1
    excel = False if args.no_excel else recalc(out)
    back = read_back(out) if excel else None
    pdf_out = case.out_dir(WP_DIR) / lawform.OUT_PDF
    try:
        legal = lawform.write(pdf_out, inp, r, case.company)
    except PermissionError:
        legal = {"written": False, "why": f"{pdf_out} 가 열려 있어 쓰지 못했습니다. PDF 를 닫고 다시 돌리세요"}

    f = float
    data = {"company": case.company, "fy_start": str(inp["과세연도 시작일"]), "fy_end": str(inp["과세연도 종료일"]),
            "eligible": r["eligible"], "type": r["type"], "kind": r["kind"], "key": r["key"], "nth": r["nth"],
            "first_income_end": str(r["first_end"] or ""), "term_end": str(r["term_end"] or ""),
            "rate": f(r["rate"]), "add_rate": f(r["add_rate"]),
            "rows": {"11O": {"7": r["o_7"], "8": r["o_8"], "9": r["o_9"]}, "111": {"7": r["t_7"], "8": r["t_8"], "9": r["t_9"]}},
            "min_tax": r["min_tax"], "min_tax_cut": r["mt_cut"], "cap_cut": r["cap_cut"], "chosen": r["chosen"],
            "total": r["total"], "excel": back, "confirm": r["notes"], "workbook": case.rel(out), "input": str(src),
            "law_pdf": case.rel(pdf_out) if legal.get("written") else None}
    case.write_json(OUT_JSON, data)

    wrote = False
    if not args.keep:
        info = case.info()
        old = info.get(INFO_KEY)
        if old is None or (isinstance(old, dict) and old.get("출처") == SOURCE):
            info[INFO_KEY] = {"출처": SOURCE, "감면세액": r["total"], "최저한세 적용대상(111) 대상세액": r["t_7"] if r["chosen"] else 0,
                              "최저한세 적용대상(111)": r["t_final"], "최저한세 적용제외(11O)": r["o_final"],
                              "감면율": f(r["rate"]), "추가감면율": f(r["add_rate"])}
            case.write_json("신고건.json", info)
            wrote = True

    print(f"창업중소기업 세액감면 {won(r['total'])}원 = 11O(최저한세 적용제외) {won(r['o_final'])} + 111(최저한세 적용대상) {won(r['t_final'])}")
    print(f"판정: {'감면 대상' if r['eligible'] else '감면 대상 아님'} · {r['key']} · {r['kind']} · 감면율 {f(r['rate']) * 100:g}%"
          f" · 추가감면율 {f(r['add_rate']) * 100:g}% · {r['nth']}차 연도(감면 끝 {r['term_end'] or '-'})")
    code = 0
    if back:
        failed = [t for t in back["tests"] if t["result"] == "확인"]
        print(f"엔진 대조 {back['total']}개 중 {back['matched']}개 일치 · 검산 {len(back['tests'])}개 중 {len(back['tests']) - len(failed)}개 통과")
        for b in back["bad"][:10]:
            print(f"어긋남 엔진대조: {b['item']} 엔진 {b['engine']} · 엑셀 {b['excel']}")
        for t in failed:
            print(f"확인 검산: {t['check']} (왼쪽 {t['left']} · 오른쪽 {t['right']})")
        if back["errors"]:
            print(f"수식 오류 칸: {', '.join(back['errors'])}")
        if back["bad"] or failed or back["errors"]:
            code = 1
    else:
        print("엑셀 재계산을 하지 않았습니다. 워크북을 엑셀로 열면 수식이 계산됩니다(엔진 대조 · 검산은 「목록」 시트)")
    if legal.get("written"):
        print(f"법정서식 PDF {legal['pages']}쪽(법제처 별지 제2호서식 위에 값 {legal['cells']}칸): {case.rel(pdf_out)}")
    else:
        print(f"법정서식 PDF 를 만들지 않았습니다: {legal.get('why', '')}")
    for text in r["notes"]:
        print(f"확인: {text}")
    if not args.keep and not wrote:
        print(f"신고건.json 의 「{INFO_KEY}」 는 사람이 넣은 값이라 고치지 않았습니다. 워크북 값과 다르면 맞추십시오")
    case.mark_step("startup", code == 0, f"창업감면 {won(r['total'])}원 · {r['kind']} {f(r['rate']) * 100:g}%",
                   [case.rel(out), f"_색인/{OUT_JSON}"] + ([case.rel(pdf_out)] if legal.get("written") else []))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
