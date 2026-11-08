"""위하고 전표 줄과 검증 워크북을 엔진 값으로 만든다.

계산은 engine.py 하나뿐이다. 위하고 업로드 파일과 검증 워크북은 둘 다 엔진 값을 그대로 쓴다.
2026-11-08 까지는 원장 · 전표를 엑셀 수식으로 다시 짜고, 엑셀이 재계산한 값으로 업로드 파일을 썼다.
그 구조는 엑셀 판마다 함수가 달라(MAXIFS 는 엑셀 2016 에 없다) 해외 거래 환율이 0 이 된 업로드 파일을 냈고,
엑셀이나 LibreOffice 가 없으면 업로드 파일이 아예 나오지 않았다.

검증 워크북 시트: 요약 · 전표 · 거래원장 · 기초·기말. 수식 없이 값만 쓴다(미리보기 · 휴대폰에서도 같은 값이 보인다).
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

import engine as E
import wehago_upload as WU

INPUT = PatternFill("solid", fgColor="FFF2CC")     # 노란 칸: 회계사가 적는 칸
HEAD = PatternFill("solid", fgColor="D9E1F2")
BAD = PatternFill("solid", fgColor="F8CBAD")
GOOD = PatternFill("solid", fgColor="E2EFDA")
BOLD = Font(bold=True)
NUMF = '#,##0;[Red]-#,##0'
FXF = '#,##0.00#;[Red]-#,##0.00#'
RATEF = '#,##0.00##'
QTYF = "General"           # '#,##0.######' 은 정수 수량에 마침표가 남는다(100.)
DATEF = "yyyy-mm-dd"

NO_BALANCE = ("검토", "정보", "대여")              # 잔액 계산을 하지 않는 행
TRADES = ("해외매수", "해외매도", "국내매수", "국내매도")
FX_PL = ("환전_외화원화", "해외매수", "해외원천세")
PASS_NOTE = "PASS 는 계산과 대사만 본다. 원천 자료가 맞는지, 계정 분류 · 기초 장부금액 · 기말 단가가 맞는지는 보지 않는다."


def _num(v):
    if v is None:
        return None
    if isinstance(v, Decimal):
        return int(v) if v == v.to_integral_value() else float(v)
    return v


def _header(ws, row, names, col=1):
    for j, t in enumerate(names, col):
        c = ws.cell(row, j, t)
        c.fill, c.font = HEAD, BOLD
        c.alignment = Alignment(wrap_text=True, vertical="center", horizontal="center")


def _date(v):
    if v in (None, ""):
        return None
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    from read_source import parse_date
    return parse_date(v)


def party_name(cfg, broker):
    return (cfg.get("거래처") or {}).get("증권사", broker) or ""


def memo(tx, kind, broker, cfg):
    head = E.MEMO.get(kind, tx.raw_type).format(ccy=tx.ccy)
    nm = tx.name or ""
    if kind in TRADES:
        q = tx.qty.normalize() if hasattr(tx.qty, "normalize") else tx.qty
        s = f"{head} {nm} {q:f}주"
    elif kind in ("해외배당", "국내배당"):
        s = f"{head} {nm}"
    elif kind in ("환전_원화외화", "환전_외화원화"):
        s = f"{head} {tx.G:,.2f}"
    else:
        s = head
    s = f"[{broker}] {s}" if broker else s
    tag = f" #{tx.seq}"
    lim = int(cfg.get("적요길이", 40))
    if len(s) + len(tag) > lim:
        s = s[: lim - len(tag)]
    return s + tag


# ---------------------------------------------------------------- 전표 줄
def journal_lines(res, broker=""):
    """엔진 결과 → 위하고 전표 줄(0원 줄 제외). 업로드 파일과 검증 워크북 「전표」 시트가 이 목록을 그대로 쓴다.

    줄: {key, date, gubun(3 차변 · 4 대변), code, name, party, memo, dr, cr}. key 는 거래 순번, 결산 줄은 'Y'.
    """
    cfg = res.cfg
    party = party_name(cfg, broker)
    limit = int(cfg.get("적요길이", 40))
    out = []

    def add(key, date, side, acc, amt, pty, m):
        amt = E.R0(Decimal(amt))
        if amt == 0:
            return
        code, name = acc
        out.append({"key": key, "date": date, "gubun": 3 if side == "dr" else 4, "code": str(code), "name": name,
                    "party": pty, "memo": WU.clean_memo(m, limit),
                    "dr": int(amt) if side == "dr" else 0, "cr": int(amt) if side == "cr" else 0})

    for row in res.rows:
        if row.kind not in E.LINES:
            continue
        tx = row.tx
        m = memo(tx, row.kind, broker, cfg)
        for side, acc, v, key in row.lines:
            pty = party if key in ("원화예수금", "외화예수금") else (tx.counterparty or "") if key == "이체상대" else ""
            add(tx.seq, tx.date, side, acc, v, pty, m)

    end = _date((cfg.get("기말") or {}).get("일자"))
    if end is None:
        return out
    sec = E.acct(cfg, "증권")
    for it in res.year_end:
        pl = it["pl"]
        if not pl:
            continue
        m = f"[결산] 평가 {it['name']}"[:36] + " #Y"
        if pl > 0:
            add("Y", end, "dr", sec, pl, "", m)
            add("Y", end, "cr", E.acct(cfg, "평가이익"), pl, "", m)
        else:
            add("Y", end, "dr", E.acct(cfg, "평가손실"), -pl, "", m)
            add("Y", end, "cr", sec, -pl, "", m)
    for it in res.fx_end:
        pl = it["pl"]
        if not pl:
            continue
        m = f"[결산] 외화환산 {it['ccy']} #Y"
        if pl > 0:
            add("Y", end, "dr", E.acct(cfg, "외화예수금"), pl, party, m)
            add("Y", end, "cr", E.acct(cfg, "환산이익"), pl, "", m)
        else:
            add("Y", end, "dr", E.acct(cfg, "환산손실"), -pl, "", m)
            add("Y", end, "cr", E.acct(cfg, "외화예수금"), -pl, party, m)
    return out


# ---------------------------------------------------------------- 대사 · 검산
def recon(r):
    """한 행의 증권사 잔액 대사. (비교한 항목 수, [다른 항목 설명])."""
    t, n, bad = r.tx, 0, []
    if r.kind in NO_BALANCE:
        return 0, []
    if t.krw_bal is not None and (t.ccy == "KRW" or r.S != 0):
        n += 1
        if r.T != t.krw_bal:
            bad.append(f"원화 증권사 {t.krw_bal:,} 차이 {r.T - t.krw_bal:+,}")
    if t.fx_bal is not None and t.ccy != "KRW":
        n += 1
        if r.P != t.fx_bal:
            bad.append(f"{t.ccy} 증권사 {t.fx_bal:,} 차이 {r.P - t.fx_bal:+,}")
    if t.hold_qty is not None and r.kind in TRADES + ("주식수변동",):
        n += 1
        if r.AG - r.AS != t.hold_qty:
            lent = f"(대여 중 {r.AS} 제외)" if r.AS else ""
            bad.append(f"수량 증권사 {t.hold_qty} 차이 {r.AG - r.AS - t.hold_qty:+}{lent}")
    return n, bad


def checks(res, lines):
    """[(항목, 값, 판정, 설명)]. 판정은 OK · 확인필요 · 중단. 중단이 하나라도 있으면 위하고 업로드 파일을 쓰지 않는다."""
    rows, cfg = res.rows, res.cfg
    by = {}
    for ln in lines:
        by[ln["key"]] = by.get(ln["key"], 0) + ln["dr"] - ln["cr"]
    mis = {"원화": 0, "외화": 0, "수량": 0}
    for r in rows:
        for b in recon(r)[1]:
            mis["수량" if b.startswith("수량") else "원화" if b.startswith("원화") else "외화"] += 1
    no_rate = sum(1 for r in rows if r.kind in E.LINES and r.tx.ccy != "KRW" and not r.kind.startswith("환전") and r.N == 0)
    stops = [i for i in res.issues if i[0] == "중단"]
    b_sec = (cfg.get("기초") or {}).get("종목") or []
    no_book = sum(1 for s in b_sec if Decimal(str(s.get("수량", 0) or 0)) > 0 and Decimal(str(s.get("장부금액", 0) or 0)) == 0)
    no_price = sum(1 for it in res.year_end if it["qty"] != 0 and it["price"] is None)
    no_end = 0 if _date((cfg.get("기말") or {}).get("일자")) else sum(
        1 for it in list(res.year_end) + list(res.fx_end) if it["pl"])
    total = sum(ln["dr"] - ln["cr"] for ln in lines)
    out = [
        ("전표 차변 − 대변", total, "중단", "전체 차대 일치"),
        ("차대가 안 맞는 거래 수", sum(1 for v in by.values() if v), "중단", "거래(순번)마다 차변 합 = 대변 합"),
        ("중단 사유 수", len(stops), "중단", "환율 없음 · 보유보다 많은 매도 · 외화 잔액보다 많은 출금. 확인사항 [중단]"),
        ("환율 없는 외화 거래 수", no_rate, "중단", "환율표에 그 날짜 이전 환율이 없다"),
        ("원화잔액 불일치 수", mis["원화"], "확인필요", "계산 원화예수금 잔액 vs 증권사 현금잔액(거래원장 대사 열)"),
        ("외화잔액 불일치 수", mis["외화"], "확인필요", "계산 외화예수금 잔액 vs 증권사 외화예수금(거래원장 대사 열)"),
        ("보유수량 불일치 수", mis["수량"], "확인필요", "계산 보유수량(대여 중 제외) vs 증권사 잔고수량(거래원장 대사 열)"),
        ("검토대기(전표 없음) 수", sum(1 for r in rows if r.kind == "검토"), "확인필요", "입출고 · 기업행위: 확인사항 [검토대기]"),
        ("가계정 기표 수", sum(1 for r in rows if "가계정" in r.kind), "확인필요", "규칙에 없는 거래: 확인사항 [미분류]"),
        ("장부금액 없는 기초 보유 종목 수", no_book, "확인필요",
         "기초 수량은 있는데 장부금액이 0 이다(역산한 기초). 팔면 원가가 낮게 잡혀 처분이익이 부풀려진다. 설정 「기초」 에 전기말 장부금액을 넣고 다시 돌린다"),
        ("기말 단가 미입력 종목 수", no_price, "확인필요", "설정 「기말」 의 단가 · 환율(기초·기말 시트)"),
        ("기말일이 없어 빠진 결산 전표 수", no_end, "확인필요", "설정 「기말」 의 일자"),
    ]
    return [(n, v, "OK" if not v else bad, d) for n, v, bad, d in out]


def totals(res, lines):
    rs = res.rows
    s = lambda f: sum((getattr(r, f) for r in rs), Decimal(0))
    return [
        ("처분손익", s("AB")), ("외환차손익", s("AC")), ("배당 · 이자수익(세전)", s("AE")), ("원천세 · 현지세", s("AF")),
        ("지급수수료(매수 수수료)", s("AD")),
        ("기말 평가손익", sum((it["pl"] for it in res.year_end if it["pl"] is not None), Decimal(0))),
        ("외화예수금 환산손익", sum((it["pl"] for it in res.fx_end if it["pl"] is not None), Decimal(0))),
        ("기말 보유원가", sum((it["cost"] for it in res.year_end), Decimal(0))),
        ("전표 차변 합계", sum(ln["dr"] for ln in lines)), ("전표 대변 합계", sum(ln["cr"] for ln in lines)),
    ]


# ---------------------------------------------------------------- 검증 워크북
def build(path, res, lines, cks, broker="", status=0, upload_note="", upload_checks=(), diag=None, opening_hint=None):
    cfg = res.cfg
    wb = Workbook()
    ws = wb.active
    ws.title = "요약"
    _summary(ws, res, lines, cks, broker, status, upload_note, upload_checks, diag or [], opening_hint or [])
    _journal(wb.create_sheet("전표"), lines)
    _ledger(wb.create_sheet("거래원장"), res)
    _balances(wb.create_sheet("기초·기말"), res, cfg)
    wb.save(path)
    return path


def _summary(ws, res, lines, cks, broker, status, upload_note, upload_checks, diag, hint):
    cfg = res.cfg
    dates = [r.tx.date for r in res.rows if r.tx.date]
    period = f"{min(dates)} ~ {max(dates)}" if dates else ""
    ws["A1"], ws["A1"].font = "증권 거래 전표 검증", Font(bold=True, size=14)
    ws["A2"] = (f"회사 {cfg.get('회사', '')} · 증권사 {broker or '판별 못함'} · 거래 {period} · 분류 {cfg.get('분류', '단기매매')} · "
                f"만든 때 {dt.datetime.now():%Y-%m-%d %H:%M}")
    verdict = {0: "통과", 2: "확인필요", 3: "중단"}.get(status, str(status))
    ws["A4"], ws["A4"].font = "결론", BOLD
    ws["B4"], ws["B4"].font = verdict, BOLD
    ws["B4"].fill = GOOD if status == 0 else BAD if status == 3 else INPUT
    ws["D4"] = upload_note
    ws["D4"].alignment = Alignment(wrap_text=True, vertical="top")
    ws["A5"] = PASS_NOTE
    r = 7

    def section(title, names, cols):
        nonlocal r
        ws.cell(r, 1, title).font = Font(bold=True, size=12)
        r += 1
        for name, col in zip(names, cols):
            _header(ws, r, [name], col)
        r += 1

    def mark(cell, v):
        cell.fill = GOOD if v == "OK" else BAD if v in ("중단", "반려", "위험") else INPUT if v in ("확인필요", "확인") else PatternFill()

    section("검산", ["항목", "값", "판정", "설명"], [1, 2, 3, 4])
    for name, val, verdict_, desc in cks:
        ws.cell(r, 1, name)
        ws.cell(r, 2, _num(val)).number_format = NUMF
        c = ws.cell(r, 3, verdict_)
        mark(c, verdict_)
        ws.cell(r, 4, desc)
        r += 1
    r += 1
    section("위하고 올리기 전 검사", ["항목", "값", "판정", "예"], [1, 2, 3, 4])
    if not upload_checks:
        ws.cell(r, 1, "업로드 파일을 만들지 않아 검사하지 않았다")
        r += 1
    for name, val, verdict_, ex in upload_checks:
        ws.cell(r, 1, name), ws.cell(r, 2, _num(val))
        mark(ws.cell(r, 3, verdict_), verdict_)
        ws.cell(r, 4, ex)
        r += 1
    r += 1
    section("합계", ["항목", "금액(원)"], [1, 2])
    for name, v in totals(res, lines):
        ws.cell(r, 1, name)
        ws.cell(r, 2, _num(v)).number_format = NUMF
        r += 1
    r += 1
    if diag:
        section("자료 진단", ["항목", "", "판정", "내용", "할 일"], [1, 2, 3, 4, 5])
        for name, verdict_, body, todo in diag:
            ws.cell(r, 1, name)
            mark(ws.cell(r, 3, verdict_), verdict_)
            ws.cell(r, 4, body), ws.cell(r, 5, todo)
            r += 1
        r += 1
    section("확인사항", ["구분", "순번", "일자", "내용", "회계사 결론"], [1, 2, 3, 4, 5])
    for kind, tx, msg in res.issues:
        ws.cell(r, 1, kind)
        if tx is not None:
            ws.cell(r, 2, tx.seq)
            ws.cell(r, 3, tx.date).number_format = DATEF
            msg = f"{tx.raw_type} {tx.name}".strip() + ": " + msg
        ws.cell(r, 4, msg)
        mark(ws.cell(r, 1), "중단" if kind == "중단" else "확인" if kind in ("확인", "대사", "미분류", "검토대기") else "")
        ws.cell(r, 5).fill = INPUT
        r += 1
    for h in hint:
        ws.cell(r, 1, "기초 추정"), ws.cell(r, 4, h)
        ws.cell(r, 5).fill = INPUT
        r += 1
    for row in ws.iter_rows(min_row=4):
        for c in row:
            if c.row != 5 and not (c.fill and c.fill.fgColor.rgb == HEAD.fgColor.rgb):
                c.alignment = Alignment(wrap_text=c.column in (1, 4, 5), vertical="top")
    for col, w in zip("ABCDE", (44, 12, 10, 80, 36)):
        ws.column_dimensions[col].width = w


def _journal(ws, lines):
    ws["A1"], ws["A1"].font = "전표: 위하고 업로드 파일과 같은 줄(0원 줄 제외). 거래번호로 거래원장 순번과 잇는다. Y 는 기말 결산", BOLD
    head = ["거래번호", "일자", "구분", "계정코드", "계정과목명", "거래처명", "적요", "차변", "대변"]
    _header(ws, 2, head)
    r = 3
    for ln in lines:
        vals = [ln["key"], ln["date"], ln["gubun"], ln["code"], ln["name"], ln["party"], ln["memo"], ln["dr"], ln["cr"]]
        for j, v in enumerate(vals, 1):
            ws.cell(r, j, v)
        ws.cell(r, 2).number_format = DATEF
        ws.cell(r, 8).number_format = ws.cell(r, 9).number_format = NUMF
        r += 1
    ws.cell(r, 7, "합계").font = BOLD
    ws.cell(r, 8, sum(ln["dr"] for ln in lines)).number_format = NUMF
    ws.cell(r, 9, sum(ln["cr"] for ln in lines)).number_format = NUMF
    ws.cell(r, 8).font = ws.cell(r, 9).font = BOLD
    ws.freeze_panes = "A3"
    ws.auto_filter.ref = f"A2:I{max(2, r - 1)}"
    for col, w in zip("ABCDEFGHI", (9, 11, 5, 8, 18, 14, 44, 13, 13)):
        ws.column_dimensions[col].width = w


LEDGER = [("순번", 6), ("일자", 11), ("거래", 16), ("처리", 12), ("종목", 22), ("통화", 5), ("수량", 9),
          ("외화금액", 11), ("외화비용", 9), ("원화금액", 13), ("원화비용", 10), ("적용환율", 10),
          ("원가", 13), ("처분손익", 12), ("외환차손익", 11), ("원화잔액", 13), ("외화잔액", 11), ("보유수량", 9),
          ("대사", 22), ("환율 근거", 22)]


def _ledger(ws, res):
    ws["A1"], ws["A1"].font = ("거래원장: 증권사 파일 값(외화 · 원화 금액, 비용)과 엔진 계산(환율 · 원가 · 손익 · 잔액). "
                               "대사 열이 빨간 줄은 계산 잔액이 증권사 잔액과 다르다"), BOLD
    _header(ws, 2, [n for n, _ in LEDGER])
    for i, r in enumerate(res.rows, 3):
        t, k = r.tx, r.kind
        fx = t.ccy != "KRW"
        cost = r.X if k.endswith("매수") else r.Z_ if (k.endswith("매도") or k == "주식수변동") else None
        n, bad = recon(r)
        vals = [t.seq, t.date, t.raw_type, k, t.name, t.ccy, t.qty or None,
                t.G or None, t.H or None, t.I or None, t.J or None, r.N if (fx and r.N) else None,
                cost or None, r.AB if k.endswith("매도") else None, r.AC if k in FX_PL else None,
                None if k in NO_BALANCE else r.T, r.P if (fx and k not in NO_BALANCE) else None,
                r.AG if k in TRADES + ("주식수변동",) else None,
                " · ".join(bad) if bad else ("일치" if n else ""), r.rate_src]
        for j, v in enumerate(vals, 1):
            ws.cell(i, j, _num(v))
        ws.cell(i, 2).number_format = DATEF
        for j in (7, 18):
            ws.cell(i, j).number_format = QTYF
        for j in (8, 9, 17):
            ws.cell(i, j).number_format = FXF
        for j in (10, 11, 13, 14, 15, 16):
            ws.cell(i, j).number_format = NUMF
        ws.cell(i, 12).number_format = RATEF
        if bad:
            ws.cell(i, 19).fill = BAD
    ws.freeze_panes = "C3"
    ws.auto_filter.ref = f"A2:{chr(64 + len(LEDGER))}{max(2, 2 + len(res.rows))}"
    for j, (_, w) in enumerate(LEDGER, 1):
        ws.column_dimensions[chr(64 + j)].width = w


def _balances(ws, res, cfg):
    begin = cfg.get("기초") or {}
    ws["A1"], ws["A1"].font = "기초 · 기말: 기초는 설정 「기초」(비었으면 거래내역에서 추정), 기말 평가는 설정 「기말」 의 단가 · 환율", BOLD
    r = 3
    ws.cell(r, 1, "기초 잔고").font = Font(bold=True, size=12)
    r += 1
    _header(ws, r, ["구분", "이름", "통화", "수량 · 외화잔액", "장부금액(원)", "출처 · 비고"])
    r += 1
    rows = [("원화예수금", "", "KRW", None, Decimal(str(begin.get("원화예수금", 0) or 0)), "")]
    for c, v in sorted((begin.get("외화") or {}).items()):
        rows.append(("외화예수금", c, c, Decimal(str(v.get("잔액", 0) or 0)), Decimal(str(v.get("장부금액", 0) or 0)), v.get("출처", "")))
    for s in begin.get("종목") or []:
        note = s.get("출처", "")
        if Decimal(str(s.get("대여중", 0) or 0)):
            note = f"대여 중 {s['대여중']} · {note}"
        rows.append(("종목", s["종목"], s.get("통화", "KRW"), Decimal(str(s.get("수량", 0) or 0)),
                     Decimal(str(s.get("장부금액", 0) or 0)), note))
    for row in rows:
        for j, v in enumerate(row, 1):
            ws.cell(r, j, _num(v))
        ws.cell(r, 4).number_format, ws.cell(r, 5).number_format = QTYF, NUMF
        if "추정" in str(row[5]):
            ws.cell(r, 6).fill = INPUT
        r += 1
    r += 1
    end = cfg.get("기말") or {}
    krw_end = Decimal(str(begin.get("원화예수금", 0) or 0)) + sum((x.S for x in res.rows), Decimal(0))
    ws.cell(r, 1, "기말").font = Font(bold=True, size=12)
    ws.cell(r, 3, f"기말일 {end.get('일자') or '없음'} · 단가 출처 {end.get('단가출처') or '없음'}")
    r += 1
    ws.cell(r, 1, "원화예수금 기말 잔액(계산)")
    ws.cell(r, 5, _num(krw_end)).number_format = NUMF
    r += 2
    _header(ws, r, ["종목", "통화", "보유수량", "보유원가(원)", "기말단가", "기말환율", "평가액(원)", "평가손익"])
    r += 1
    for it in res.year_end:
        vals = [it["name"], it["ccy"], it["qty"], it["cost"], it["price"], it["rate"], it["fv"], it["pl"]]
        for j, v in enumerate(vals, 1):
            ws.cell(r, j, _num(v))
        ws.cell(r, 3).number_format = QTYF
        for j in (4, 7, 8):
            ws.cell(r, j).number_format = NUMF
        ws.cell(r, 5).number_format = ws.cell(r, 6).number_format = RATEF
        if it["qty"] != 0 and it["price"] is None:
            ws.cell(r, 5).fill = BAD
        r += 1
    r += 1
    _header(ws, r, ["외화예수금", "", "외화잔액", "장부금액(원)", "", "기말환율", "환산액(원)", "환산손익"])
    r += 1
    for it in res.fx_end:
        vals = [it["ccy"], None, it["bal"], it["book"], None, it["rate"], it["krw"], it["pl"]]
        for j, v in enumerate(vals, 1):
            ws.cell(r, j, _num(v))
        ws.cell(r, 3).number_format = FXF
        for j in (4, 7, 8):
            ws.cell(r, j).number_format = NUMF
        ws.cell(r, 6).number_format = RATEF
        if it["rate"] is None:
            ws.cell(r, 6).fill = BAD
        r += 1
    for row in ws.iter_rows(min_row=3):
        for c in row:
            if c.column == 6 and c.value:
                c.alignment = Alignment(wrap_text=True, vertical="top")
    for col, w in zip("ABCDEFGH", (26, 22, 14, 16, 16, 50, 16, 14)):
        ws.column_dimensions[col].width = w
