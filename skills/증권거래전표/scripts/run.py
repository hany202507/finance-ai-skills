"""증권 거래내역 → 전표 한 번에.

python run.py <거래내역 파일 ...> --out <산출 폴더> [--config 설정.json] [--rates 환율표.csv]
              [--broker 삼성증권] [--standard] [--no-recalc]

--standard  입력이 templates/표준거래표_양식.csv 꼴(스캔 PDF 를 AI 가 옮겨 적은 것)일 때.
산출: 증권전표_<회사>.xlsx(수식) · 위하고_일반전표_<회사>.xlsx(업로드용 값) · 표준거래표.csv · 실행보고.md
종료코드: 0 검산 통과, 2 확인필요 남음, 3 중단 사유 있음.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import shutil
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import engine as E                     # noqa: E402
import normalize as NZ                 # noqa: E402
import read_source as RS               # noqa: E402
import build_workbook as BW            # noqa: E402

BROKERS = ["삼성증권", "키움증권", "미래에셋증권", "한국투자증권", "NH투자증권", "KB증권", "신한투자증권", "토스증권",
           "대신증권", "하나증권", "메리츠증권", "카카오페이증권", "한화투자증권", "유안타증권", "교보증권", "IBK투자증권",
           "현대차증권", "DB금융투자", "DB증권", "iM증권", "LS증권", "SK증권", "유진투자증권", "부국증권", "신영증권"]


def guess_broker(paths, tables, extra=""):
    text = " ".join(p.name for p in paths) + " " + " ".join(t.title for t in tables) + " " + (extra or "")[:20000]
    for b in BROKERS:
        short = b.replace("증권", "").replace("투자", "").replace("금융", "")
        if b in text or (len(short) >= 2 and short in text):
            return b
    return ""


def load_rates(path):
    rows = []
    if not path:
        return rows
    text = RS._decode(Path(path).read_bytes())
    for r in csv.DictReader(text.splitlines()):
        d = RS.parse_date(r.get("일자"))
        v = RS.to_num(r.get("환율"))
        if d and v:
            rows.append((d, (r.get("통화") or "USD").strip().upper(), v, (r.get("출처") or "").strip()))
    rows.sort()
    return rows


def fill_opening(cfg, txs, rates_rows):
    """설정에 기초가 없으면 파일에서 추정해 채우고, 추정했다는 사실을 돌려준다."""
    hint = []
    sugg = E.infer_opening(txs)
    begin = cfg.setdefault("기초", {})
    if "원화예수금" not in begin and sugg["원화예수금"] is not None:
        begin["원화예수금"] = str(sugg["원화예수금"])
        hint.append(f"원화예수금 기초 {sugg['원화예수금']:,} 원: 첫 거래 행의 증권사 현금잔액에서 거꾸로 셈(전기말 장부와 맞춘다)")
    fx = begin.setdefault("외화", {})
    first = min((t.date for t in txs), default=None)
    rb = E.RateBook({})
    tab = {}
    for d, c, v, s in rates_rows:
        tab.setdefault(c, []).append((d, v, s))
    rb = E.RateBook(tab)
    for c, bal in sugg["외화"].items():
        if c in fx:
            continue
        got = rb.get(c, first - dt.timedelta(days=1)) if first else None
        book = E.R0(bal * Decimal(str(got[1]))) if got else Decimal(0)
        fx[c] = {"잔액": str(bal), "장부금액": str(book),
                 "출처": f"추정: 잔액은 첫 행에서 거꾸로 셈, 장부금액은 {got[0] if got else '?'} 매매기준율 {got[1] if got else '?'} 환산"}
        hint.append(f"{c} 기초 잔액 {bal} · 장부금액 {book:,} 원(전기말 환산 가정). 전기말 장부 잔액으로 고친다")
    secs = begin.setdefault("종목", [])
    have = {s.get("종목코드") or s["종목"] for s in secs}
    for k, (name, ccy, q) in sugg["종목"].items():
        if k in have:
            continue
        ln = sugg.get("대여중", {}).get(k, 0)
        secs.append({"종목": name, "종목코드": k if k != name else "", "통화": ccy, "수량": str(q), "장부금액": "0",
                     "대여중": str(ln),
                     "출처": "추정 수량(증권사 잔고수량 − 기간 중 매매 + 대여 중). 장부금액 미입력"})
        hint.append(f"{name} 기초 수량 {q} 추정" + (f"(그중 대여 중 {ln})" if ln else "")
                    + ", 장부금액 미입력 → 기초 시트에 전기말 장부금액을 넣어야 처분손익이 맞는다")
    return hint


def _quick_score(ts, cfg, rates_rows):
    """후보 표로 전표를 돌려 본 점수: (중단, 대사+미분류, −거래 수). 작을수록 좋다."""
    import copy
    from collections import Counter
    txs = NZ.to_txns(ts)
    c = copy.deepcopy(cfg)
    fill_opening(c, txs, rates_rows)
    tab = {}
    for d, cc, v, s in rates_rows:
        tab.setdefault(cc, []).append((d, v, s))
    res = E.run(txs, c, E.RateBook(tab))
    k = Counter(x[0] for x in res.issues)
    # 종목명이 빈 매매·배당 수: kordoc 이 3줄 1건 표에서 이름을 놓친다(미래에셋 실물 31건, pdfplumber 0건)
    k["이름빈"] = sum(1 for t in txs if t.event in ("매수", "매도", "배당") and not t.name)
    return (k.get("중단", 0), k.get("대사", 0) + k.get("미분류", 0), k["이름빈"], -len(txs)), k, len(txs)


def pick_pdf_reader(p, password, cfg, rates_rows):
    """PDF 읽기 후보를 차례로 돌려 전표 대사가 가장 좋은 결과를 고른다. 대사·미분류·중단이 0이면 그 자리에서 멈춘다."""
    path = RS.decrypt_pdf(p, password)
    best, tried = None, []
    for name, fn in RS.pdf_candidates(path):
        try:
            sheets, md = fn()
            ocr_res = RS._LAST_OCR if name == "자체 OCR" else None
            ts = RS.tables_from_sheets(p.name, sheets, ocr_res)
        except Exception as e:
            tried.append(f"{name} 실패({str(e)[:40]})")
            continue
        if not ts:
            tried.append(f"{name} 머리글 못 찾음")
            continue
        score, k, n = _quick_score(ts, cfg, rates_rows)
        tried.append(f"{name} 거래 {n} · 대사 {k.get('대사', 0)} · 미분류 {k.get('미분류', 0)} · 중단 {k.get('중단', 0)} · 이름 빈 {k['이름빈']}")
        if best is None or score < best[0]:
            best = (score, name, ts, md)
        if score[0] == 0 and score[1] == 0 and score[2] == 0:
            break
    if best is None:
        raise RS.SourceError(f"{p.name}: 어떤 방법으로도 머리글을 찾지 못했다({'; '.join(tried)}). "
                             "AI 가 쪽 이미지를 읽어 templates/표준거래표_양식.csv 로 옮겨 적는다")
    return best[2], best[3], f"PDF 읽기: {best[1]} 선택 (시도: {' / '.join(tried)})"


def recalc(path: Path):
    ps = HERE / "recalc.ps1"
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps), str(path.resolve())],
                           capture_output=True, text=True, timeout=600)
        if "recalc ok" in r.stdout:
            return "Excel"
    except Exception:
        pass
    soffice = shutil.which("soffice") or shutil.which("soffice.exe")
    if soffice:
        out = path.parent / "_recalc"
        out.mkdir(exist_ok=True)
        subprocess.run([soffice, "--headless", "--calc", "--convert-to", "xlsx", "--outdir", str(out), str(path)],
                       capture_output=True, timeout=600)
        p2 = out / path.name
        if p2.exists():
            shutil.move(str(p2), str(path))
            shutil.rmtree(out, ignore_errors=True)
            return "LibreOffice"
    return ""


def read_back(path: Path):
    import openpyxl
    wb = openpyxl.load_workbook(path, data_only=True)
    errs = []
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for c in row:
                if isinstance(c.value, str) and c.value.startswith("#") and c.value.rstrip("!?0/").upper() in (
                        "#REF", "#DIV", "#VALUE", "#NAME", "#N/A", "#NUM", "#NULL") or (
                        isinstance(c.value, str) and c.value in ("#REF!", "#DIV/0!", "#VALUE!", "#NAME?", "#N/A", "#NUM!")):
                    errs.append(f"{ws.title}!{c.coordinate} {c.value}")
    ck = wb["검산"]
    checks = []
    for r in range(4, ck.max_row + 1):
        name, val, verdict = ck.cell(r, 1).value, ck.cell(r, 2).value, ck.cell(r, 3).value
        if name and r < 4 + 20 and ck.cell(r, 4).value:
            if verdict not in ("OK", "확인필요"):
                verdict = f"계산 안 됨({val})"
            checks.append((name, val, verdict))
    jv = wb["전표"]
    lines = []
    for r in range(4, jv.max_row + 1):
        key = jv.cell(r, 1).value
        if key in (None, ""):
            continue
        lines.append({k: jv.cell(r, j).value for j, k in enumerate(
            ["key", "date", "gubun", "code", "name", "party", "memo", "dr", "cr", "seq"], 1)})
    return checks, lines, errs


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("inputs", nargs="+")
    ap.add_argument("--out", required=True)
    ap.add_argument("--config")
    ap.add_argument("--rates")
    ap.add_argument("--broker", default="")
    ap.add_argument("--standard", action="store_true")
    ap.add_argument("--password", help="암호 걸린 PDF 의 비밀번호(파일·보고서에 남기지 않는다)")
    ap.add_argument("--no-recalc", action="store_true")
    a = ap.parse_args(argv)

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    cfg = json.loads(Path(a.config).read_text(encoding="utf-8")) if a.config else {}
    paths = [Path(p) for p in a.inputs]
    # 새 양식은 코드를 고치지 않고 설정으로 더한다: 「머리글」 {원문: 표준열}, 「적요규칙」 [{pattern, event}]
    RS.EXTRA_ALIASES = dict(cfg.get("머리글") or {})
    NZ.EXTRA_RULES = list(cfg.get("적요규칙") or [])

    tables, notes, ocr_issues, md_texts = [], [], [], []
    source_kinds = set()
    if a.standard:
        source_kinds.add("표준거래표")
        txs = []
        for p in paths:
            txs += NZ.load_standard_csv(p)
    else:
        for p in paths:
            if p.suffix.lower() == ".pdf":
                ts, md, cand_note = pick_pdf_reader(p, a.password, cfg, load_rates(a.rates))
                notes.append(cand_note)
                source_kinds.add("OCR" if "OCR 선택" in cand_note else "글자 PDF")
            else:
                ts, md = RS.read_tables(p, password=a.password)
                source_kinds.add("OCR" if any(t.ocr is not None for t in ts) else "엑셀 · CSV")
            tables += ts
            md_texts.append(md or "")
            if md is not None:
                (out / f"{p.stem}_추출.md").write_text(md, encoding="utf-8")
            for t in ts:
                notes.append(f"{p.name} [{t.sheet}] 머리글 {t.header_row+1}행({t.header_rows}줄, {t.mode}) · 거래 {len(t.records)}행"
                             + (f" · 못 맞춘 머리글: {', '.join(t.unmapped)}" if t.unmapped else ""))
                if t.ocr is not None:
                    o = t.ocr
                    notes.append(f"OCR: 쪽 {o.pages} · 방식 {', '.join(o.grid)} · 글자 높이 {o.text_px}px · 기울기 보정 {o.angle}° · 의심 칸 {len(o.suspects)}")
                    ocr_issues.extend(("OCR", None, q) for q in o.quality)
                    for pg, rr, cc, txt, conf in o.suspects[:40]:
                        ocr_issues.append(("OCR", None, f"{pg}쪽 {rr}행 {cc}열 '{txt}' 확신도 {conf}: 원본 이미지와 대조"))
        txs = NZ.to_txns(tables)
    broker = a.broker or cfg.get("증권사") or guess_broker(paths, tables, " ".join(md_texts))
    rates_rows = load_rates(a.rates)
    hint = fill_opening(cfg, txs, rates_rows)
    tab = {}
    for d, c, v, s in rates_rows:
        tab.setdefault(c, []).append((d, v, s))
    res = E.run(txs, cfg, E.RateBook(tab))
    if ocr_issues:
        res.issues[:0] = ocr_issues
        res.issues.insert(0, ("OCR", None, "OCR 로 읽은 자료다. 잔액 대사([대사])가 0 이어도 의심 칸은 원본과 한 번 대조한다"))

    import diagnose as DG
    diag = DG.diagnose(tables, txs, cfg, res, hint, source_kinds, rates_rows)

    company = cfg.get("회사") or "회사"
    wbp = out / f"증권전표_{company}.xlsx"
    BW.build(res, rates_rows, wbp, broker=broker, opening_hint=hint, diag=diag)

    # 표준거래표(감사 추적용)
    with open(out / "표준거래표.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["순번", "일자", "원문거래종류", "이벤트", "시장", "종목코드", "종목명", "통화", "수량", "단가",
                    "외화총액", "외화비용", "원화금액", "원화비용", "증권사원화잔액", "증권사외화잔액", "증권사잔고수량", "상대방", "원본위치", "메모"])
        for t in txs:
            w.writerow([t.seq, t.date, t.raw_type, t.event, t.market, t.code, t.name, t.ccy, t.qty, t.price, t.G, t.H, t.I, t.J,
                        t.krw_bal, t.fx_bal, t.hold_qty, t.counterparty, t.src, " / ".join(t.notes)])

    report = [f"# 증권 거래 전표 실행 보고 ({dt.datetime.now():%Y-%m-%d %H:%M})", "",
              f"- 회사: {company} · 증권사: {broker or '판별 못함'} · 분류: {cfg.get('분류','단기매매')}",
              f"- 거래 {len(txs)}건 · 전표 대상 {sum(1 for r in res.rows if r.kind != '검토')}건 · 검토대기 {sum(1 for r in res.rows if r.kind == '검토')}건"]
    report += [f"- {n}" for n in notes]
    kinds = {}
    for r in res.rows:
        kinds[r.kind] = kinds.get(r.kind, 0) + 1
    report.append("- 이벤트: " + ", ".join(f"{k} {v}" for k, v in sorted(kinds.items())))
    report += ["", "## 자료 진단", "", "전표를 믿기 전에 볼 것. 위험이 있으면 검산이 OK 여도 결과를 그대로 쓰지 않는다.", ""] + DG.as_markdown(diag)

    status = 2 if any(v == "위험" for _, v, _, _ in diag) else 0
    if not a.no_recalc:
        how = recalc(wbp)
        if not how:
            report.append("- 재계산 도구(Excel·LibreOffice)가 없어 수식 검산을 못 했다")
            status = 2
        else:
            checks, lines, errs = read_back(wbp)
            report.append(f"- 재계산: {how} · 수식 오류 {len(errs)}건" + (f" ({'; '.join(errs[:5])})" if errs else ""))
            report += ["", "## 검산", "", "| 항목 | 값 | 판정 |", "|---|---|---|"]
            for name, val, verdict in checks:
                report.append(f"| {name} | {val} | {verdict} |")
                if verdict != "OK":
                    status = max(status, 2)
            if errs:
                status = 3
            import wehago_upload as WU
            for path_u, n, vchecks in WU.write(lines, out, company, cfg):
                report.append(f"\n### 위하고 업로드 {path_u.name}: {n}줄(0원 줄 제외, 재계산한 수식 값)\n")
                report += ["| 올리기 전 검사 | 값 | 판정 | 예 |", "|---|---|---|---|"]
                for name, val, verdict, ex in vchecks:
                    report.append(f"| {name} | {val} | {verdict} | {ex} |")
                    if verdict == "반려":
                        status = 3
                    elif verdict != "OK":
                        status = max(status, 2)
            report.append("- 다시 올릴 때는 위하고 「자동분개 일괄검색 및 삭제 > 전표엑셀업로드」로 먼저 지운다. "
                          "변환옵션은 기본값(계정코드 · 거래처 기준)으로 둔다")
    stops = [i for i in res.issues if i[0] == "중단"]
    if stops:
        status = 3
    report += ["", "## 확인사항", ""]
    for kind, tx, msg in res.issues:
        where = f"#{tx.seq} {tx.date} {tx.raw_type} {tx.name}".strip() if tx is not None else ""
        report.append(f"- [{kind}] {where} {msg}".replace("  ", " "))
    for h in hint:
        report.append(f"- [기초 추정] {h}")
    report += ["", "PASS 는 계산·대사만 본다. 원천 자료의 정확성, 계정 분류, 기초 장부금액, 기말 단가는 회계사가 확인한다."]
    (out / "실행보고.md").write_text("\n".join(report), encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    print("\n".join(report[:60]))
    return status


if __name__ == "__main__":
    sys.exit(main())
