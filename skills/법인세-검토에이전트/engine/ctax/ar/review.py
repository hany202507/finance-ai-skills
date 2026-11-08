"""분석적 검토 스킬 명령: `python -m ctax review <신고 건 폴더> [--sample] [--no-prior] [--fresh] [--memo <메모.json>]` (2026-10-29).

교육 스킬 「법인세-분석적검토」 가 부르는 한 줄 명령이다. 받은자료 읽기(read) → 전기 신고서 읽기(prior) → 분석적 검토(ar)
→ 요청자료(request)를 차례로 돌리고, 결과를 회계사가 검토하는 순서로 찍는다(10-27 교육 회의: 분석적 검토는 서식 목록과
요청자료가 중심).

  1. 서식 총괄표: 올해 낼 서식과 넣은 까닭(기본 서식 · 이슈), 전기 대비, 채우는 쪽(엔진 · 사람), 그 서식에 필요한 자료와 받은 여부
  2. 요청자료: 아직 받지 못한 자료와 회사에 물을 것, 메일 초안
  3. 이슈: 서식과 요청자료가 나온 까닭. AI 메모(판단 · 까닭 · 근거)가 들어갔는지

결과 파일은 `1 AR/분석적검토.xlsx`(시트 서식 총괄표 · 요청자료 · 이슈 · 메일 초안). 회계사 결론은 이 파일이 아니라
`1 AR/AR_이슈.xlsx` 노란 칸에 적는다(다음 `ctax ar` 가 이어받는다).

`--memo` 는 AI 가 쓴 이슈 메모를 `ctax ar --memo` 로 검사해 넣고, 메모의 회사 질문까지 요청자료에 넣어 다시 찍는다.
받은자료 읽기 · 전기 신고서 읽기는 장부.json · 전기.json 이 있으면 건너뛴다. 다만 그 뒤에 받은자료에 들어온 장부 파일 ·
전기 PDF 가 있으면(`inbox --add` 등, `ctax.intake.stale`) 그 단계만 다시 읽는다(10-31 QA 결함 1). `--fresh` 는 늘 다시 읽는다.
`--sample` 은 받은 폴더 아래에 합성 회사 「단순회사(가상)」 둘째 사업연도를 만든다. 실제 신고에서 나온 누락 유형을 합성 금액으로
심은 장부와 전기 신고서 값이다(`ctax demo --with-errors` 와 같은 자료). 금액은 모두 지어낸 값이다.
전기 세무조정계산서 PDF 가 없는 신고 건(신설 첫 해 · 첫 수임)은 `--no-prior` 로 돌린다.

끝 코드: 0 AI 메모까지 모두 들어감, 1 메모를 아직 넣지 않았거나 메모 · AR 검사에 걸림, 2 입력을 읽지 못함.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import sys
import time
import traceback
from collections import Counter
from pathlib import Path

from ctax import xlsx as X
from ctax.case import AR_DIR, INDEX, PRIOR, RECEIVED, Case, MissingInput

XLSX_NAME = "분석적검토.xlsx"
NO_PRIOR_KEY = "전기 신고서 없음"
STATUS_ORDER = {"해당": 0, "확인": 1, "해당 없음": 2}
GOT, NOT_YET, NA = "받음", "아직", "해당 없음"


def _won(n) -> str:
    return f"{int(n):,}" if isinstance(n, (int, float)) and not isinstance(n, bool) else ""


def _quiet(fn, argv: list[str]) -> tuple[int, str]:
    """단계 명령을 돌리고 (끝 코드, 찍은 글). 단계가 찍는 긴 목록은 요약이 다시 보여 주므로 실패할 때만 내보낸다.
    단계에서 예외가 나면 끝 코드 2 와 예외 글이다(어느 단계에서 멈췄는지 보이게)."""
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            code = fn(argv)
    except Exception:                           # noqa: BLE001
        return 2, buf.getvalue() + traceback.format_exc()
    return int(code or 0), buf.getvalue()


def _step(label: str, fn, argv: list[str], show: bool = False) -> int:
    t = time.time()
    code, out = _quiet(fn, argv)
    if show or code != 0:
        text = out.rstrip()
        if text:
            print(text)
    print(f"  ({label} {time.time() - t:.1f}초, 끝 코드 {code})")
    return code


# ---------------------------------------------------------------- 합성 회사 · 전기 없음
def _sample(root: Path) -> Path:
    """합성 회사(오류 심기) 받은자료와 신고건.json. 이미 있으면 그대로 쓴다."""
    from ctax.demo import cli as demo

    case = demo.case_dir(root)
    if not (case / RECEIVED).is_dir() or not any((case / RECEIVED).glob("*.xlsx")):
        case = demo.prepare(root, with_errors=True)
    return case


def _mark_no_prior(case: Case) -> None:
    info = case.info()
    if info.get(NO_PRIOR_KEY) is not True:
        info[NO_PRIOR_KEY] = True
        case.write_json("신고건.json", info)


# ---------------------------------------------------------------- 총괄표
def overview(ar: dict, req: dict | None, no_prior: bool = False, picks: dict | None = None) -> list[dict]:
    """서식 총괄표 줄. AR.json forms 에 넣은 까닭(기본 서식 · 이슈 제목), 전기 대비, 그 서식에 쓰는 요청자료를 붙인다.
    picks 는 선택.json 의 form 줄(회계사가 `ctax set … form` 으로 고른 낸다 · 안 낸다). 엔진 판정은 바꾸지 않고 옆에 보인다.
    순서는 해당 → 확인 → 해당 없음, 같은 판정 안에서는 AR.json 순서(기본 서식 다음 이슈 서식, 그다음 전기 서식)다."""
    picks = picks or {}
    from ctax.ar.engine import BASIC_FORMS

    basic = set(BASIC_FORMS)
    issues = {i["no"]: i for i in ar.get("issues") or [] if isinstance(i, dict)}
    items = [i for i in (req or {}).get("items") or [] if isinstance(i, dict)]
    rows = []
    for f in ar.get("forms") or []:
        code, status = str(f.get("code")), str(f.get("status") or "")
        nos = [n for n in f.get("why") or [] if isinstance(n, int) and n in issues]
        notes = [str(w) for w in f.get("why") or [] if not isinstance(w, int)]
        reasons = (["기본 서식"] if code in basic else []) + [f"이슈 {n} {issues[n]['title']}" for n in nos] + notes
        if not reasons and f.get("prior_filed"):
            reasons = ["전기에 낸 서식"]
        if no_prior:
            prior = "전기 신고서 없음"
        elif f.get("prior_filed"):
            prior = "전기에도 냄" if status == "해당" else "전기에 냄, 올해 판정 필요"
        else:
            prior = "올해 새로 냄" if status == "해당" else "전기에 없음"
        need = [{"id": i["id"], "name": i["name"], "state": i["state"], "required": bool(i.get("required")),
                 "source": i.get("source"), "by": i.get("by")}
                for i in items if code in (i.get("forms") or []) and i.get("state") != NA]
        pick = picks.get(code) if isinstance(picks.get(code), dict) else {}
        rows.append({"code": code, "name": str(f.get("name") or code), "status": status, "reasons": reasons,
                     "issues": nos, "prior": prior, "by": str(f.get("by") or ""), "need": need,
                     "missing": sum(1 for n in need if n["state"] == NOT_YET), "pick": str(pick.get("value") or "")})
    return sorted(rows, key=lambda r: STATUS_ORDER.get(r["status"], 3))


def _req_order(item: dict) -> tuple:
    state = {NOT_YET: 0, GOT: 1, NA: 2}.get(item.get("state"), 3)
    kind = 0 if item.get("source") == "rule" and item.get("required") else 1 if item.get("source") == "rule" else 2
    return state, kind


# ---------------------------------------------------------------- 엑셀
def write_xlsx(path: Path, ar: dict, req: dict | None, rows: list[dict], head: str) -> Path:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment

    def top(ws, ncol: int, row: int) -> None:
        for col in range(1, ncol + 1):
            ws.cell(row=row, column=col).alignment = Alignment(wrap_text=True, vertical="top")

    wb = Workbook()
    ws = wb.active
    ws.title = "서식 총괄표"
    filed = [r for r in rows if r["status"] == "해당"]
    r0 = X.title(ws, "서식 총괄표",
                 f"{head} · 낼 서식 {len(filed)}종 · 판정이 필요한 서식 {sum(1 for r in rows if r['status'] == '확인')}종. "
                 "기본 서식, 분석적 검토 이슈가 가리킨 서식, 전기에 냈던 서식을 모았습니다. 엔진 판정이라 회계사 확인 전입니다")
    cols = ["번호", "서식", "서식 이름", "당기 판정", "넣은 까닭", "전기 대비", "채움", "필요한 자료(받은 여부)", "아직 못 받은 자료",
            "회계사 선택"]
    X.header(ws, r0, cols)
    for n, r in enumerate(rows, 1):
        row = r0 + n
        need = "\n".join(f"{x['name']} ({x['state']})" for x in r["need"])
        vals = [n, r["code"], r["name"], r["status"], "\n".join(r["reasons"]), r["prior"], r["by"], need, r["missing"] or None,
                r["pick"] or None]
        for col, v in enumerate(vals, 1):
            X.cell(ws, row, col, v, wrap=col in (3, 5, 8))
        top(ws, len(cols), row)
    X.widths(ws, [6, 14, 34, 10, 52, 22, 8, 50, 10, 10])
    ws.freeze_panes = ws.cell(row=r0 + 1, column=4)
    X.note(ws, r0 + len(rows) + 2, "채움이 엔진인 서식은 ctax forms 가 채우고, 사람인 서식은 회계사가 넣습니다. 회계사 선택은 "
                                    "python -m ctax set <신고 건> form <서식> 낸다 또는 안 낸다 로 적은 값입니다(엔진 판정은 그대로 둡니다)")

    ws = wb.create_sheet("요청자료")
    items = sorted((req or {}).get("items") or [], key=_req_order)
    s = (req or {}).get("summary") or {}
    r0 = X.title(ws, "요청자료",
                 f"{head} · 받음 {s.get('received', 0)} · 아직 {s.get('missing_required', 0) + s.get('missing_optional', 0)}"
                 f"(필수 {s.get('missing_required', 0)}) · 해당 없음 {s.get('na', 0)}. 받은 여부는 받은자료 폴더의 파일로 엔진이 판정합니다")
    cols = ["번호", "받은 여부", "자료 · 회사에 물을 것", "필수", "쓰는 서식", "까닭", "누가 넣었나", "받은 파일", "비고"]
    X.header(ws, r0, cols)
    for n, i in enumerate(items, 1):
        row = r0 + n
        why = i.get("basis") or ""
        if i.get("source") == "issue":
            why = str(i.get("why") or why)
        vals = [n, i.get("state"), i.get("name"), "필수" if i.get("required") else "선택", " · ".join(i.get("forms") or []),
                why, i.get("by"), "\n".join(i.get("files") or []), i.get("note")]
        for col, v in enumerate(vals, 1):
            X.cell(ws, row, col, v, wrap=col in (3, 5, 6, 8, 9))
        top(ws, len(cols), row)
    X.widths(ws, [6, 10, 56, 7, 18, 40, 10, 40, 36])
    ws.freeze_panes = ws.cell(row=r0 + 1, column=3)

    ws = wb.create_sheet("이슈")
    issues = ar.get("issues") or []
    memos = sum(1 for i in issues if i.get("memo"))
    r0 = X.title(ws, "분석적 검토 이슈",
                 f"{head} · 이슈 {len(issues)}건 · AI 메모 {memos}건(회계사 확인 전). 회계사 결론은 1 AR/AR_이슈.xlsx 노란 칸에 적습니다")
    cols = ["번호", "종류", "확실도", "제목", "전기", "당기", "서식", "회사에 물을 것", "AI 판단(확인 전)", "AI 까닭", "근거 조문 · 등급",
            "회계사 결론"]
    X.header(ws, r0, cols)
    for n, i in enumerate(issues, 1):
        row = r0 + n
        a = i.get("amounts") or {}
        m = i.get("memo") if isinstance(i.get("memo"), dict) else {}
        law = m.get("law") or i.get("law") or []
        c = i.get("conclusion")
        title = i["title"] + (" (작은 조정 후보)" if i.get("folded") else "")
        vals = [i["no"], i["kind"], i["certainty"], title, a.get("prior"), a.get("current"), " · ".join(i.get("forms") or []),
                "\n".join(list(i.get("questions") or []) + list(m.get("questions") or [])), m.get("judgment"), m.get("why"),
                "\n".join(f"{x.get('ref')} {x.get('grade') or ''}".strip() for x in law if isinstance(x, dict)),
                c.get("text") if isinstance(c, dict) else c]
        for col, v in enumerate(vals, 1):
            X.cell(ws, row, col, v, money=col in (5, 6), wrap=col in (4, 7, 8, 10, 11, 12))
        top(ws, len(cols), row)
    X.widths(ws, [6, 10, 9, 44, 14, 14, 18, 44, 12, 50, 40, 24])
    ws.freeze_panes = ws.cell(row=r0 + 1, column=5)

    ws = wb.create_sheet("메일 초안")
    r0 = X.title(ws, "요청 메일 초안", "보내기는 사람이 합니다. 받는 분 · 보내는 사람 이름을 채우고 AI 질문은 확인한 뒤 보냅니다")
    for n, line in enumerate(str((req or {}).get("mail") or "").splitlines(), 1):
        X.cell(ws, r0 + n, 1, line)
    X.widths(ws, [110])

    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path


# ---------------------------------------------------------------- 찍기
def summary(folder: Path, ar: dict, req: dict | None, rows: list[dict]) -> int:
    issues = ar.get("issues") or []
    by_status = Counter(r["status"] for r in rows)
    by_who = Counter(r["by"] for r in rows if r["status"] == "해당")
    print(f"\n1. 서식 총괄표: 낼 서식 {by_status.get('해당', 0)}종(엔진 {by_who.get('엔진', 0)} · 사람 {by_who.get('사람', 0)})"
          f" · 판정이 필요한 서식 {by_status.get('확인', 0)}종")
    # 이슈도 못 받은 자료도 없는 기본 서식은 한 줄로 모은다. 검토자가 볼 것은 그 밖의 서식이다
    plain = [r for r in rows if r["status"] == "해당" and r["reasons"] == ["기본 서식"] and not r["missing"]]
    if plain:
        print(f"  [해당] 기본 서식 {len(plain)}종(이슈 · 못 받은 자료 없음): " + " · ".join(r["code"] for r in plain))
    for r in rows:
        if r["status"] == "해당 없음" or r in plain:
            continue
        why = " · ".join(f"이슈 {n}" for n in r["issues"]) or (r["reasons"][0] if r["reasons"] else "")
        lack = [x for x in r["need"] if x["state"] == NOT_YET]
        docs = [x["name"] for x in lack if x["source"] == "rule"]
        asks = sum(1 for x in lack if x["source"] != "rule")
        need = " · ".join(docs + ([f"회사에 물을 것 {asks}건"] if asks else []))
        tail = " · ".join(x for x in (r["prior"], f"채움 {r['by']}", why, f"아직: {need}" if need else "",
                                      f"회계사 선택 {r['pick']}" if r["pick"] else "") if x)
        print(f"  [{r['status']}] {r['code']} {r['name']} · {tail}")

    s = (req or {}).get("summary") or {}
    items = sorted((req or {}).get("items") or [], key=_req_order)
    lack = [i for i in items if i.get("state") == NOT_YET]
    print(f"\n2. 요청자료: 받음 {s.get('received', 0)} · 아직 {len(lack)}(필수 {s.get('missing_required', 0)}) · 해당 없음 {s.get('na', 0)}")
    groups = (("꼭 필요한 자료", lambda i: i.get("source") == "rule" and i.get("required")),
              ("있으면 받을 자료", lambda i: i.get("source") == "rule" and not i.get("required")),
              ("회사에 물을 것", lambda i: i.get("source") == "issue"))
    for label, pick in groups:
        part = [i for i in lack if pick(i)]
        if not part:
            continue
        print(f"  {label}")
        for i in part:
            forms = " · ".join(i.get("forms") or [])
            mark = " (AI 질문, 확인 전)" if i.get("by") == "AI" else ""
            nos = " · ".join(str(n) for n in i.get("issues") or [])
            tail = " · ".join(x for x in (f"서식 {forms}" if forms else "", f"이슈 {nos}" if nos else "") if x)
            print(f"    - {i.get('name')}{mark}" + (f" ({tail})" if tail else ""))
    unknown = (req or {}).get("unknown_files") or []
    if unknown:
        print(f"  종류를 알 수 없는 받은 파일 {len(unknown)}개: " + ", ".join(f["path"] for f in unknown))

    kinds = Counter(i["kind"] for i in issues)
    memos = sum(1 for i in issues if i.get("memo"))
    kind_text = " · ".join(f"{k} {v}" for k, v in kinds.items())
    print(f"\n3. 이슈 {len(issues)}건({kind_text}) · AI 메모 {memos}/{len(issues)}건")
    for i in issues:
        m = i.get("memo") if isinstance(i.get("memo"), dict) else {}
        judg = f" · AI 판단 {m['judgment']}(확인 전)" if m.get("judgment") else ""
        concl = " · 회계사 결론 있음" if i.get("conclusion") else ""
        fold = " (작은 조정 후보)" if i.get("folded") else ""
        forms = " · ".join(i.get("forms") or [])
        print(f"  {i['no']:>2}. [{i['kind']} · {i['certainty']}]{fold} {i['title']} → 서식 {forms or '-'}{judg}{concl}")

    print("\n결과 파일")
    for rel in (f"{AR_DIR}/{XLSX_NAME}", f"{AR_DIR}/AR_이슈.xlsx", "0 요청/요청자료_목록.xlsx", "0 요청/요청메일_초안.txt"):
        if (folder / rel).exists():
            print(f"  {folder / rel}")
    if memos < len(issues):
        print(f"\n다음: _색인/AR.json 을 읽고 이슈 {len(issues)}건 메모를 써서 python -m ctax review \"{folder}\" --memo <메모.json>")
        return 1
    return 0


# ---------------------------------------------------------------- 명령
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m ctax review",
                                 description="분석적 검토: read → prior → ar → request, 서식 총괄표 · 요청자료 · 이슈")
    ap.add_argument("folder", help="신고 건 폴더(<회사>/<연도> 법인세). --sample 이면 합성 회사를 만들 작업 폴더")
    ap.add_argument("--sample", action="store_true", help="합성 회사 「단순회사(가상)」 둘째 사업연도(누락 유형을 심은 자료)로 돌린다")
    ap.add_argument("--no-prior", action="store_true", help="전기 세무조정계산서가 없는 신고 건(신설 첫 해 · 첫 수임)")
    ap.add_argument("--fresh", action="store_true", help="장부.json · 전기.json 이 있어도 다시 읽는다")
    ap.add_argument("--memo", help="AI 가 쓴 이슈 메모 JSON. 검사해 넣고 요청자료를 다시 만든다")
    raw = list(sys.argv[1:] if argv is None else argv)
    if "--memo" in raw:
        i = raw.index("--memo")
        val = raw[i + 1] if i + 1 < len(raw) else ""
        if val and Path(val).is_dir():                 # review --memo <폴더> 로 부른 경우
            print(f"--memo 다음에는 메모 JSON 파일을 줍니다. 받은 값은 폴더입니다: {val}\n"
                  f'쓰는 법: python -m ctax review "<신고 건 폴더>" --memo <메모.json>')
            return 2
    args = ap.parse_args(argv)

    folder = Path(args.folder).resolve()
    if args.sample:
        folder.mkdir(parents=True, exist_ok=True)
        folder = _sample(folder)
        print(f"합성 회사 받은자료: {folder / RECEIVED}")
    if not (folder / RECEIVED).is_dir():
        print(f"받은자료 폴더가 없습니다: {folder / RECEIVED}")
        return 2
    case = Case(folder)
    idx = folder / INDEX
    t0 = time.time()

    from ctax.ar import cli as ar_cli
    from ctax.request import cli as request_cli

    if args.memo:
        print("1. AI 메모 검사 · 넣기")
        code = _step("메모", ar_cli.main, [str(folder), "--memo", str(Path(args.memo).resolve())], show=True)
        if code == 1:
            print("메모를 고쳐 다시 넣으십시오. 아무것도 넣지 않았습니다")
        if code != 0:
            return code
    else:
        from ctax.intake import cli as intake_cli
        from ctax.intake import stale
        from ctax.prior import cli as prior_cli

        moved = stale.changed(folder)
        if args.fresh or not (idx / "장부.json").exists() or moved["books"]:
            print("1. 받은자료 읽기" + (f": 받은자료가 바뀌어 다시 읽습니다({' · '.join(Path(x).name for x in moved['books'][:5])})"
                                     if moved["books"] and not args.fresh else ""))
            if _step("받은자료 읽기", intake_cli.main, [str(folder)], show=True) == 2:
                return 2
        else:
            print("1. 받은자료 읽기: 장부.json 이 있어 건너뜀(--fresh 로 다시 읽기)")

        has_pdf = (folder / PRIOR).is_dir() and any((folder / PRIOR).glob("*.pdf"))
        if moved["prior"] and not args.fresh:
            print(f"2. 전기 신고서: 받은자료가 바뀌어 다시 읽습니다({' · '.join(Path(x).name for x in moved['prior'][:3])})")
        if not args.fresh and (idx / "전기.json").exists() and not moved["prior"]:
            print("2. 전기 신고서 읽기: 전기.json 이 있어 건너뜀")
        elif args.sample and not has_pdf:
            from ctax.demo.errors import prior_step
            print("2. 전기 신고서 값(합성 회사)")
            _step("전기 신고서 값", lambda _argv: prior_step(folder), [])
        else:
            if args.no_prior and not has_pdf:
                _mark_no_prior(case)
            if not has_pdf and case.info().get(NO_PRIOR_KEY) is not True:
                print(f"2. 전기 신고서 읽기: {PRIOR} 에 전기 세무조정계산서 PDF 가 없습니다. PDF 를 넣거나, "
                      "신설 첫 해 · 첫 수임이면 --no-prior 로 다시 돌리십시오")
                return 2
            print("2. 전기 신고서 읽기")
            if _step("전기 신고서 읽기", prior_cli.main, [str(folder)]) == 2:
                return 2

        print("3. 분석적 검토")
        code = _step("분석적 검토", ar_cli.main, [str(folder)])
        if code == 2:
            return 2

    print("4. 요청자료")
    _step("요청자료", request_cli.main, [str(folder)])

    ar = case.read_json("AR.json")
    from ctax.request.build import load as load_request
    req = load_request(folder)
    no_prior = bool(case.info().get(NO_PRIOR_KEY) is True or (case.read_json("전기.json") if case.has("전기.json") else {}).get("no_prior"))
    from ctax.choice import store as choice_store
    rows = overview(ar, req, no_prior, choice_store.read(folder).get("form") or {})
    head = f"{case.info().get('company') or case.company} {case.info().get('fy') or case.fy} 사업연도"
    try:
        write_xlsx(case.out_dir(AR_DIR) / XLSX_NAME, ar, req, rows, head)
    except PermissionError:
        print(f"{AR_DIR}/{XLSX_NAME} 이 열려 있어 쓰지 못했습니다. 엑셀을 닫고 다시 돌려 주십시오")
    code = summary(folder, ar, req, rows)
    filed = sum(1 for r in rows if r["status"] == "해당")
    lack = sum(1 for i in (req or {}).get("items") or [] if i.get("state") == NOT_YET)
    memos = sum(1 for i in ar.get("issues") or [] if i.get("memo"))
    print(f"\n전체 {time.time() - t0:.1f}초 · 낼 서식 {filed}종 · 아직 못 받은 자료 {lack}건 · 이슈 {len(ar.get('issues') or [])}건 · AI 메모 {memos}건")
    case.mark_step("review", code == 0, f"낼 서식 {filed}종 · 아직 못 받은 자료 {lack}건 · AI 메모 {memos}건",
                   [f"{AR_DIR}/{XLSX_NAME}"])
    return code


if __name__ == "__main__":
    sys.exit(main())
