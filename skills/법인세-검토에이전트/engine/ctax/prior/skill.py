"""전기 읽기 스킬 명령: `python -m ctax prev <신고 건 폴더> [--sample] [--fresh]` · `--page N` (2026-10-27).

교육 스킬 「법인세-전기읽기」 가 부르는 명령이다.

  prev <신고 건>            전기 세무조정계산서 PDF 를 읽고(ctax prior, 전기.json 이 있으면 건너뜀) 요약을 찍고,
                            읽은 것을 엑셀 `2 조서/전기신고서_읽기.xlsx` 로 낸다(서식 목록 · 란 값 · 15호 · 50호(을) · 결손금 ·
                            공제감면 · 확인할 것). 엔진이 읽지 못한 서식은 「스킬이 읽을 서식」 으로 따로 찍는다
  prev <신고 건> --page N   N 쪽을 그림(PNG)으로 `_색인/쪽/p<N>.png` 에 쓴다. 스킬이 쪽을 눈으로 볼 때 쓴다
  prev <작업 폴더> --sample 합성 회사 「단순회사(가상)」 의 2025 세무조정계산서(엔진이 만든 PDF, 금액은 지어낸 값)를
                            `단순회사(가상)/2026 법인세/00 받은자료/전기/` 에 두고 돌린다

스킬이 읽은 값은 `ctax prior <신고 건> --template <서식>` 으로 틀을 받고 `--merge-ai <답.json>` 으로 넣는다(prior/ai.py).
숫자는 엔진이 읽고 검사한다. 스킬이 읽은 값은 confirmed false 로 들어가고 확인은 회계사가 한다.

끝 코드: 0 확인할 것 없음, 1 확인할 것이 있음, 2 PDF 가 없거나 읽지 못함.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from collections import Counter
from pathlib import Path

from ctax.case import WP_DIR, Case
from ctax.prior import ai as prior_ai
from ctax.prior import verify

HERE = Path(__file__).resolve().parent
SAMPLE_PDF = HERE / "sample" / "2025_단순회사(가상)_세무조정계산서.pdf"
SAMPLE_COMPANY = "단순회사(가상)"
SAMPLE_YEAR = "2026 법인세"
XLSX = "전기신고서_읽기.xlsx"
KIND_NAMES = {"check_form": "서식 안 검산", "check_cross": "서식 사이 검산", "missing_amount": "쪽에 있는데 안 읽은 금액",
              "not_in_text": "쪽 글자에 없는 금액", "verify_error": "검사 오류", "ai_uncertain": "스킬이 확신 없다고 한 란",
              "ai_unanswered": "스킬이 답하지 않은 란", "ai_bad_value": "스킬 답 값 꼴 오류", "ai_no_pages": "스킬 답에 쪽 없음",
              "ai_scanned": "스캔본 쪽"}


def _won(n) -> str:
    return f"{int(n):,}" if isinstance(n, (int, float)) and not isinstance(n, bool) else str(n if n is not None else "")


def _sample(root: Path) -> Path:
    folder = root / SAMPLE_COMPANY / SAMPLE_YEAR
    prior_dir = folder / "00 받은자료" / "전기"
    prior_dir.mkdir(parents=True, exist_ok=True)
    if not any(prior_dir.glob("*.pdf")):
        shutil.copy(SAMPLE_PDF, prior_dir / SAMPLE_PDF.name)
    return folder


def _label(form: str, code: str) -> str:
    f, _ = verify.defn(form)
    if f is None:
        return ""
    it = next((x for x in f.items if x.code == code), None)
    return " ".join(it.name.split()) if it else ""


def classify(prior: dict) -> tuple[list[dict], list[dict], list[dict]]:
    """(엔진이 읽은 서식, 스킬이 읽을 서식, 정의 없는 서식). 각 줄은 전기.json forms[] 항목에 상태를 더한 것."""
    read = prior_ai.engine_forms(prior)
    ai = set((prior.get("ai") or {}).keys())
    done, todo, nodef = [], [], []
    for f in prior.get("forms") or []:
        code = f.get("code")
        row = dict(f)
        if not row.get("name") or row.get("name") == code:
            d = verify.defn(code)[0]
            row["name"] = getattr(d, "title", "") or code
        if code in read or code in ai:
            row["state"] = "스킬이 읽음(회계사 확인 전)" if code in ai else "엔진이 읽음"
            done.append(row)
        elif f.get("blank"):
            row["state"] = "빈 서식"
            done.append(row)
        elif verify.defn(code)[0] is not None:
            row["state"] = "스킬이 읽을 서식"
            todo.append(row)
        else:
            row["state"] = "정의 없음(읽지 않음)"
            nodef.append(row)
    return done, todo, nodef


def write_xlsx(prior: dict, path: Path) -> Path:
    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    bold = Font(bold=True)

    def sheet(title: str, head: list[str], rows: list[list]):
        ws = wb.create_sheet(title)
        ws.append(head)
        for c in ws[1]:
            c.font = bold
        for r in rows:
            ws.append(r)
        for col, w in zip("ABCDEFGHIJ", (12, 30, 14, 14, 14, 30, 30, 14, 14, 14)):
            ws.column_dimensions[col].width = w
        return ws

    wb.remove(wb.active)
    co = prior.get("company") or {}
    done, todo, nodef = classify(prior)
    probs = Counter()
    for p in prior.get("problems") or []:
        probs[p.get("form") or ""] += 1
    forms = sorted(done + todo + nodef, key=lambda f: int(f.get("page") or 0))
    sheet("서식 목록", ["서식", "이름", "쪽", "쪽 수", "읽은 란", "상태", "확인할 것"],
          [[f.get("code"), f.get("name"), f.get("page"), f.get("pages"),
            len((prior.get("cells") or {}).get(f.get("code"), {})), f["state"], probs.get(f.get("code"), 0) or ""] for f in forms])
    ai = prior.get("ai") or {}
    rows = []
    for form, cells in (prior.get("cells") or {}).items():
        by = "스킬(확인 전)" if form in ai else "엔진"
        for code, v in cells.items():
            rows.append([form, code, _label(form, code), v, by])
    sheet("란 값", ["서식", "란", "이름", "값", "읽은 쪽"], rows)
    sheet("15호 조정", ["구분", "과목", "금액", "처분", "처분 코드", "조정 내용"],
          [[a.get("side"), a.get("subject"), a.get("amount"), a.get("disposition"), a.get("code"), a.get("note")]
           for a in prior.get("adjustments") or []])
    sheet("50호(을) 유보", ["과목", "기초", "감소", "증가", "기말"],
          [[r.get("subject"), r.get("opening"), r.get("decrease"), r.get("increase"), r.get("closing")]
           for r in prior.get("reserves") or []])
    sheet("결손금", ["사업연도", "발생", "공제", "잔액"],
          [[x.get("year"), x.get("incurred"), x.get("used"), x.get("remaining")] for x in prior.get("losses") or []])
    sheet("공제감면", ["이름", "코드", "금액", "이월"],
          [[c.get("name"), c.get("code"), c.get("amount"), c.get("carryforward")] for c in prior.get("credits") or []])
    sheet("확인할 것", ["종류", "서식", "란", "제목", "읽은 값", "기대값", "차이", "까닭"],
          [[KIND_NAMES.get(p.get("kind"), p.get("kind") or ""), p.get("form"), p.get("item"), p.get("title"),
            p.get("read"), p.get("expected"), p.get("diff"), p.get("why")] for p in prior.get("problems") or []])
    ws = wb.create_sheet("회사", 0)
    for k, v in (("법인명", co.get("name")), ("사업연도", f"{prior.get('fy')} (말일 {prior.get('fy_end')})"),
                 ("중소기업", co.get("sme")), ("소기업", co.get("small")), ("업종", co.get("biz_type")),
                 ("PDF", prior.get("pdf")), ("읽은 서식", len(done)), ("스킬이 읽을 서식", len(todo)),
                 ("정의 없는 서식", len(nodef)), ("확인할 것", len(prior.get("problems") or [])),
                 ("안내", "엔진이 읽은 값이다. 스킬이 읽은 서식은 회계사 확인 전이다")):
        ws.append([k, v])
    ws.column_dimensions["A"].width = 16
    ws.column_dimensions["B"].width = 60
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path


def summary(prior: dict) -> int:
    co = prior.get("company") or {}
    done, todo, nodef = classify(prior)
    print(f"\n{co.get('name') or '(법인명 못 읽음)'} {prior.get('fy')} 신고본: 서식 {len(prior.get('forms') or [])}개 · "
          f"읽은 서식 {len(done)} · 스킬이 읽을 서식 {len(todo)} · 정의 없는 서식 {len(nodef)}")
    seen = {k: "못 읽음" if co.get(k) is None else co.get(k) for k in ("sme", "small")}     # None 을 그대로 찍지 않는다
    print(f"  중소기업 {seen['sme']} · 소기업 {seen['small']} · 업종 {co.get('biz_type') or '-'}")
    adj = prior.get("adjustments") or []
    print(f"  15호 조정 {len(adj)}줄")
    for a in adj[:12]:
        print(f"    {a.get('side')} {a.get('subject')} {_won(a.get('amount'))} {a.get('disposition') or ''}")
    if len(adj) > 12:
        print(f"    … {len(adj) - 12}줄 더(엑셀 「15호 조정」)")
    print(f"  50호(을) 유보 {len(prior.get('reserves') or [])}줄 · 결손금 {len(prior.get('losses') or [])}줄 · "
          f"공제감면 {len(prior.get('credits') or [])}건")
    if todo:
        print("\n스킬이 읽을 서식(엔진이 값을 내지 못함, 정의가 있어 틀을 받을 수 있음)")
        for f in todo:
            print(f"  {f.get('code')} {f.get('name')} · {f.get('page')}쪽"
                  f"{'~' + str(int(f['page']) + int(f['pages']) - 1) if int(f.get('pages') or 1) > 1 else ''}")
        print("  읽기: python -m ctax prior \"<신고 건>\" --template <서식> → 쪽 그림(prev --page N)을 보고 답 → --merge-ai <답.json>")
    probs = prior.get("problems") or []
    kinds = Counter(KIND_NAMES.get(p.get("kind"), "읽기 확인") for p in probs)
    print(f"\n확인할 것 {len(probs)}건" + (" (" + ", ".join(f"{k} {n}" for k, n in kinds.items()) + ")" if probs else ""))
    for p in probs[:15]:
        print(f"  [{KIND_NAMES.get(p.get('kind'), '읽기 확인')}] {p.get('title')}")
    if len(probs) > 15:
        print(f"  … {len(probs) - 15}건 더(엑셀 「확인할 것」)")
    return 1 if probs else 0


def page_png(folder: Path, page: int, zoom: float) -> int:
    import pymupdf as fitz
    prior_dir = folder / "00 받은자료" / "전기"
    pdfs = sorted(prior_dir.glob("*.pdf")) if prior_dir.is_dir() else []
    if not pdfs:
        print(f"전기 PDF 가 없습니다: {prior_dir}")
        return 2
    doc = fitz.open(pdfs[0])
    if not 1 <= page <= doc.page_count:
        print(f"쪽 번호가 범위를 넘습니다: {page} (1 ~ {doc.page_count})")
        return 2
    out = folder / "_색인" / "쪽" / f"p{page}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    doc[page - 1].get_pixmap(matrix=fitz.Matrix(zoom, zoom)).save(out)
    print(f"쪽 그림: {out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m ctax prev", description="전기 세무조정계산서를 읽어 요약 · 엑셀로 낸다")
    ap.add_argument("folder", help="신고 건 폴더(<회사>/<연도> 법인세). --sample 이면 합성 회사를 둘 작업 폴더")
    ap.add_argument("--sample", action="store_true", help="합성 회사 「단순회사(가상)」 의 2025 세무조정계산서로 돌린다")
    ap.add_argument("--fresh", action="store_true", help="전기.json 이 있어도 PDF 를 다시 읽는다")
    ap.add_argument("--page", type=int, help="이 쪽을 그림(PNG)으로 쓴다")
    ap.add_argument("--zoom", type=float, default=2.0, help="--page 그림 배율(기본 2)")
    args = ap.parse_args(argv)

    folder = Path(args.folder).resolve()
    if args.sample:
        folder = _sample(folder)
        print(f"합성 회사 전기 신고서: {folder / '00 받은자료' / '전기'}")
    if args.page:
        return page_png(folder, args.page, args.zoom)
    prior_dir = folder / "00 받은자료" / "전기"
    if not (prior_dir.is_dir() and any(prior_dir.glob("*.pdf"))):
        print(f"전기 세무조정계산서 PDF 가 없습니다: {prior_dir}")
        return 2
    idx = folder / "_색인" / "전기.json"
    t0 = time.time()
    if args.fresh or not idx.exists():
        from ctax.prior import cli as prior_cli
        if prior_cli.main([str(folder)]) == 2:
            return 2
    else:
        print("전기.json 이 있어 PDF 를 다시 읽지 않았습니다(--fresh 로 다시 읽기)")
    prior = json.loads(idx.read_text(encoding="utf-8"))
    code = summary(prior)
    out = write_xlsx(prior, folder / WP_DIR / XLSX)
    print(f"\n엑셀: {out}\n전체 {time.time() - t0:.1f}초")
    Case(folder).mark_step("prev", code == 0, f"확인할 것 {len(prior.get('problems') or [])}건", [f"{WP_DIR}/{XLSX}"])
    return code


if __name__ == "__main__":
    sys.exit(main())
