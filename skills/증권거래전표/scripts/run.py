"""증권 거래내역 → 전표 한 번에.

python run.py <거래내역 파일 ...> --out <산출 폴더> [--config 설정.json] [--rates 환율표.csv]
              [--broker 삼성증권] [--standard] [--opening-from 증권전표_검증_<회사>.xlsx]

--standard  입력이 templates/표준거래표_양식.csv 꼴(스캔 PDF 를 AI 가 옮겨 적은 것)일 때.
--opening-from  앞서 만든 검증 파일의 「기초·기말」 시트에서 고친 기초 잔고(수량 · 장부금액)를 읽어 설정 「기초」 대신 쓴다.
산출(--out 폴더): 위하고_일반전표_<회사>.xlsx(업로드) · 증권전표_검증_<회사>.xlsx(요약 · 전표 · 거래원장 · 기초·기말).
작업 파일(_작업 폴더): 실행보고.md · 표준거래표.csv · PDF 추출 마크다운.
업로드 파일은 엔진 값만, 검증 파일은 수식으로 쓰고 만들 때 수식을 다시 계산해 엔진 값과 대조한다. 엑셀 · LibreOffice 가 없어도 된다.
종료코드: 0 검산 통과, 2 확인필요 남음, 3 중단(이때는 위하고 업로드 파일을 만들지 않는다).
표준출력 맨 앞과 맨 끝에 「[증권거래전표] 실행보고: <절대경로>」 줄을, 맨 끝 바로 위에 결론 줄을 찍는다.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import sys
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import engine as E                     # noqa: E402
import normalize as NZ                 # noqa: E402
import read_source as RS               # noqa: E402
import build_workbook as BW            # noqa: E402

REPORT_MARK = "[증권거래전표] 실행보고: "   # 출력 앞 · 끝에서 실행보고 위치를 찾는 줄. 세법 훅도 이 줄을 본다

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
                    + ", 장부금액 미입력 → 설정 「기초」 에 전기말 장부금액을 넣어야 처분손익이 맞는다")
    return hint


def _dec(v):
    """엑셀 칸 값 → Decimal. 빈칸은 0, 쉼표가 든 글자도 받는다."""
    if v in (None, ""):
        return Decimal(0)
    if isinstance(v, float):
        return Decimal(repr(v))
    return Decimal(str(v).replace(",", "").strip())


def read_opening_from(path, cfg, txs, rates_rows):
    """검증 파일 「기초·기말」 시트의 기초 잔고 표를 읽어 cfg["기초"] 에 넣는다.

    이번 실행이 설정과 거래내역만으로 쓸 기초(추정 포함)와 다른 줄만 넣는다. 추정 그대로 둔 줄은 넣지 않아
    fill_opening 이 다시 추정하고 「기초 추정」 확인사항도 그대로 남는다. 돌려주는 값: 바꾼 내용 설명 목록.
    """
    import copy
    import openpyxl
    path = Path(path)
    base = copy.deepcopy(cfg)
    fill_opening(base, txs, rates_rows)
    b0 = base.get("기초") or {}
    wv = openpyxl.load_workbook(path, data_only=True, read_only=True)
    wf = openpyxl.load_workbook(path, read_only=True)
    if BW.SHEET_B not in wv.sheetnames:
        raise SystemExit(f"{path.name} 에 「{BW.SHEET_B}」 시트가 없다. 이 스킬이 만든 검증 파일을 준다")
    vals = list(wv[BW.SHEET_B].iter_rows(max_col=8, values_only=True))
    fmls = list(wf[BW.SHEET_B].iter_rows(max_col=8, values_only=True))
    wv.close()
    wf.close()
    head =next((i for i, r in enumerate(vals) if r and r[0] == "구분" and str(r[4] or "").startswith("장부금액")), None)
    if head is None:
        raise SystemExit(f"{path.name} 「{BW.SHEET_B}」 시트에서 기초 잔고 표 머리글(구분 · 장부금액)을 못 찾았다")
    names = {}
    for s in b0.get("종목") or []:
        names.setdefault(s["종목"], set()).add(s.get("종목코드") or s["종목"])
    for t in txs:
        if t.key and t.name:
            names.setdefault(t.name, set()).add(t.key)
    begin = cfg.setdefault("기초", {})
    note0 = f"검증 파일 「{BW.SHEET_B}」 시트에서 읽음({path.name})"
    changes = []

    def note_of(sheet_note, base_note):
        sheet_note = str(sheet_note or "").strip()
        if sheet_note and sheet_note != (base_note or "") and not sheet_note.startswith("추정"):
            return sheet_note
        return note0

    for i in range(head + 1, len(vals)):
        r, f = vals[i], fmls[i]
        if not r or r[0] not in ("원화예수금", "외화예수금", "종목"):
            break
        r = tuple(r) + (None,) * (8 - len(r))
        f = tuple(f) + (None,) * (8 - len(f))
        for j in (3, 4, 5):
            if isinstance(f[j], str) and f[j].startswith("=") and r[j] is None:
                raise SystemExit(f"{path.name} 「{BW.SHEET_B}」 {i + 1}행에 계산값 없이 저장된 수식이 있다. 엑셀에서 열어 저장한 뒤 다시 돌린다")
        kind, name, ccy = r[0], str(r[1] or "").strip(), str(r[2] or "KRW").strip()
        qty, book, lent, note = _dec(r[3]), E.R0(_dec(r[4])), _dec(r[5]), r[6]
        where = f"{i + 1}행"
        if kind == "원화예수금":
            old = Decimal(str(b0.get("원화예수금", 0) or 0))
            if book != old:
                begin["원화예수금"] = str(book)
                changes.append(f"원화예수금 {old:,} → {book:,} 원({where})")
            continue
        if kind == "외화예수금":
            c = name or ccy
            ob = (b0.get("외화") or {}).get(c) or {}
            obal, obook = Decimal(str(ob.get("잔액", 0) or 0)), Decimal(str(ob.get("장부금액", 0) or 0))
            if (qty, book) != (obal, obook):
                begin.setdefault("외화", {})[c] = {"잔액": str(qty), "장부금액": str(book), "출처": note_of(note, ob.get("출처"))}
                changes.append(f"{c} 외화예수금 잔액 {obal} → {qty} · 장부금액 {obook:,} → {book:,} 원({where})")
            continue
        code = str(r[7] or "").strip()
        if not code:
            keys = names.get(name, set())
            if len(keys) > 1:
                raise SystemExit(f"{path.name} 「{BW.SHEET_B}」 {where} 종목 '{name}' 이 종목코드 여럿({', '.join(sorted(keys))})과 "
                                 "맞는다. H열에 종목코드를 적고 다시 돌린다")
            code = next(iter(keys)) if keys else name
        ob = next((s for s in b0.get("종목") or [] if (s.get("종목코드") or s["종목"]) == code), {})
        old = tuple(Decimal(str(ob.get(k, 0) or 0)) for k in ("수량", "장부금액", "대여중"))
        if ob and (qty, book, lent) == old:
            continue
        secs = begin.setdefault("종목", [])
        secs[:] = [s for s in secs if (s.get("종목코드") or s["종목"]) != code]
        nm = name or ob.get("종목") or code
        secs.append({"종목": nm, "종목코드": code if code != nm else "", "통화": ccy or ob.get("통화", "KRW"),
                     "수량": str(qty), "장부금액": str(book), "대여중": str(lent), "출처": note_of(note, ob.get("출처"))})
        what = [f"{lab} {o:,} → {n:,}" for lab, o, n in zip(("수량", "장부금액", "대여 중 수량"), old, (qty, book, lent)) if o != n]
        changes.append(f"{nm} " + (" · ".join(what) if ob else f"새 줄 수량 {qty:,} · 장부금액 {book:,}") + f"({where})")
    return changes


def _locked(p):
    """엑셀이 열어 둔 파일은 덮어쓸 수 없다."""
    if not p.is_file():
        return False
    try:
        with open(p, "r+b"):
            return False
    except PermissionError:
        return True


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


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("inputs", nargs="+")
    ap.add_argument("--out", required=True)
    ap.add_argument("--config")
    ap.add_argument("--rates")
    ap.add_argument("--broker", default="")
    ap.add_argument("--standard", action="store_true")
    ap.add_argument("--password", help="암호 걸린 PDF 의 비밀번호(파일·보고서에 남기지 않는다)")
    ap.add_argument("--no-recalc", action="store_true", help="옛 옵션. 지금은 엑셀 재계산을 하지 않아 아무 일도 하지 않는다")
    ap.add_argument("--opening-from", help="검증 파일(증권전표_검증_<회사>.xlsx) 「기초·기말」 시트에서 고친 기초 잔고를 읽어 쓴다")
    a = ap.parse_args(argv)

    out = Path(a.out)
    work = out / "_작업"
    work.mkdir(parents=True, exist_ok=True)
    cfg = json.loads(Path(a.config).read_text(encoding="utf-8")) if a.config else {}
    company = cfg.get("회사") or "회사"
    busy = [p.name for p in (out / f"증권전표_검증_{company}.xlsx", out / f"위하고_일반전표_{company}.xlsx") if _locked(p)]
    if busy:
        sys.stdout.reconfigure(encoding="utf-8")
        print(f"엑셀에서 열려 있어 덮어쓸 수 없다: {', '.join(busy)}. 엑셀에서 닫고 다시 돌린다")
        return 3
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
                (work / f"{p.stem}_추출.md").write_text(md, encoding="utf-8")
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
    opened = read_opening_from(a.opening_from, cfg, txs, rates_rows) if a.opening_from else []
    hint = fill_opening(cfg, txs, rates_rows)
    if a.opening_from:
        (work / "설정_기초.json").write_text(json.dumps({"기초": cfg["기초"]}, ensure_ascii=False, indent=1), encoding="utf-8")
    tab = {}
    for d, c, v, s in rates_rows:
        tab.setdefault(c, []).append((d, v, s))
    res = E.run(txs, cfg, E.RateBook(tab))
    if a.opening_from:
        src = Path(a.opening_from).name
        res.issues[:0] = [("정보", None, f"기초 입력({src}): {m}") for m in opened] or [
            ("정보", None, f"기초 입력({src}): 이번 실행의 기초와 다른 줄이 없어 그대로 썼다")]
    if ocr_issues:
        res.issues[:0] = ocr_issues
        res.issues.insert(0, ("OCR", None, "OCR 로 읽은 자료다. 잔액 대사([대사])가 0 이어도 의심 칸은 원본과 한 번 대조한다"))

    import diagnose as DG
    diag = DG.diagnose(tables, txs, cfg, res, hint, source_kinds, rates_rows)

    import wehago_upload as WU
    # 앞선 실행이 남긴 파일을 지운다. 이번에 업로드를 막았는데 옛 업로드 파일이 남아 있으면 그것을 올리게 된다
    for old in [*out.glob(f"위하고_일반전표_{company}.xlsx"), *out.glob(f"위하고_일반전표_{company}_*.xlsx"),
                out / f"증권전표_{company}.xlsx", out / "표준거래표.csv", out / "실행보고.md"]:
        if old.is_file():
            old.unlink()

    # 표준거래표(감사 추적용)
    with open(work / "표준거래표.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["순번", "일자", "원문거래종류", "이벤트", "시장", "종목코드", "종목명", "통화", "수량", "단가",
                    "외화총액", "외화비용", "원화금액", "원화비용", "증권사원화잔액", "증권사외화잔액", "증권사잔고수량", "상대방", "원본위치", "메모"])
        for t in txs:
            w.writerow([t.seq, t.date, t.raw_type, t.event, t.market, t.code, t.name, t.ccy, t.qty, t.price, t.G, t.H, t.I, t.J,
                        t.krw_bal, t.fx_bal, t.hold_qty, t.counterparty, t.src, " / ".join(t.notes)])

    lines = BW.journal_lines(res, broker)
    cks = BW.checks(res, lines)
    stop = [f"{n} {v:,}" for n, v, verdict, _ in cks if verdict == "중단"]
    status = 2 if any(v == "위험" for _, v, _, _ in diag) else 0
    if any(verdict != "OK" for _, _, verdict, _ in cks):
        status = 2
    uploads = []
    if stop:
        status = 3
        upload_note = ("위하고 업로드 파일을 만들지 않았다: " + "; ".join(stop)
                       + ". 확인사항의 [중단] 을 고치고(환율표 · 기초 잔고) 다시 돌린다")
    else:
        uploads = WU.write(lines, out, company, cfg)
        upload_note = " · ".join(f"{p.name} {n}줄" for p, n, _ in uploads) + (
            ". 다시 올릴 때는 위하고 「자동분개 일괄검색 및 삭제 > 전표엑셀업로드」로 먼저 지운다. 변환옵션은 기본값(계정코드 · 거래처 기준)")
    vchecks = [c for _, _, vc in uploads for c in vc]
    for _, _, verdict, _ in vchecks:
        if verdict == "반려":
            status = 3
        elif verdict != "OK":
            status = max(status, 2)
    if any(verdict == "반려" for _, _, verdict, _ in vchecks):
        upload_note = "업로드 파일에 반려 사유가 있다(위하고 올리기 전 검사). 고치기 전에는 올리지 않는다. " + upload_note
    wbp = out / f"증권전표_검증_{company}.xlsx"
    status, fcheck, fbad = BW.build(wbp, res, lines, cks, broker=broker, status=status, upload_note=upload_note,
                                    upload_checks=vchecks, diag=diag, opening_hint=hint)
    cks = cks + [fcheck]
    for s, coord, f, got, exp in fbad[:20]:
        res.issues.append(("확인", None, f"검증 파일 {s}!{coord} 수식 {f} 를 다시 계산하면 {got}, 엔진 값은 {exp} (스킬 결함)"))

    report = [f"# 증권 거래 전표 실행 보고 ({dt.datetime.now():%Y-%m-%d %H:%M})", "",
              f"- 회사: {company} · 증권사: {broker or '판별 못함'} · 분류: {cfg.get('분류','단기매매')} · 원가 평가방법: {E.cost_method(cfg)}",
              f"- 거래 {len(txs)}건 · 전표 대상 {sum(1 for r in res.rows if r.kind in E.LINES)}건 · 검토대기 {sum(1 for r in res.rows if r.kind == '검토')}건"]
    report += [f"- {n}" for n in notes]
    kinds = {}
    for r in res.rows:
        kinds[r.kind] = kinds.get(r.kind, 0) + 1
    report.append("- 이벤트: " + ", ".join(f"{k} {v}" for k, v in sorted(kinds.items())))
    report += ["", f"## 결론: {({0: '통과', 2: '확인필요', 3: '중단'})[status]}", "",
               f"- 산출: {' · '.join(p.name for p, _, _ in uploads) or '업로드 파일 없음'} · {wbp.name}",
               f"- {upload_note}"]
    report += ["", "## 자료 진단", "", "전표를 믿기 전에 볼 것. 위험이 있으면 검산이 OK 여도 결과를 그대로 쓰지 않는다.", ""] + DG.as_markdown(diag)
    report += ["", "## 검산", "", "| 항목 | 값 | 판정 |", "|---|---|---|"]
    report += [f"| {n} | {v} | {verdict} |" for n, v, verdict, _ in cks]
    for p, n, vc in uploads:
        report += ["", f"## 위하고 업로드 {p.name}: {n}줄(0원 줄 제외, 엔진 값)", "",
                   "| 올리기 전 검사 | 값 | 판정 | 예 |", "|---|---|---|---|"]
        report += [f"| {name} | {val} | {verdict} | {ex} |" for name, val, verdict, ex in vc]
    report += ["", "## 확인사항", ""]
    for kind, tx, msg in res.issues:
        where = f"#{tx.seq} {tx.date} {tx.raw_type} {tx.name}".strip() if tx is not None else ""
        report.append(f"- [{kind}] {where} {msg}".replace("  ", " "))
    for h in hint:
        report.append(f"- [기초 추정] {h}")
    if a.opening_from:
        report.append("- [기초 입력] 이번에 쓴 기초 전체는 _작업/설정_기초.json 에 있다. 설정 파일 「기초」 에 옮겨 두면 다음 실행에도 그대로 쓴다")
    report += ["", BW.PASS_NOTE]
    rp = (work / "실행보고.md").resolve()
    rp.write_text("\n".join(report), encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    print(f"{REPORT_MARK}{rp}")
    print("\n".join(report[:70]))
    if len(report) > 70:
        print(f"… 아래 {len(report) - 70}줄은 실행보고에 있다")
    # 출력 끝만 보는 경우(tail)에도 결론이 보이게 한다. 실행보고 끝줄은 결론과 상관없이 PASS 주의문이다
    print(f"결론: {({0: '통과', 2: '확인필요', 3: '중단'})[status]} (종료코드 {status})")
    print(f"{REPORT_MARK}{rp}")
    return status


if __name__ == "__main__":
    sys.exit(main())
