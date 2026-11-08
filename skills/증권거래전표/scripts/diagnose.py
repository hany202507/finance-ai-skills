"""자료 진단: 전표를 만들기 전에, 받은 자료로 무엇을 검증할 수 있고 무엇이 빠졌는지 판정한다.

증권사마다 양식이 달라도 한 거래에서 뽑을 것(날짜 · 거래 종류 · 종목 · 수량 · 금액 · 비용 · 통화 · 잔액)은 같다.
달라지는 것은 「무엇이 들어 있느냐」와 「어떻게 읽었느냐」다. 그 차이가 전표를 틀리게 만드는 길은 정해져 있어서
(2026-11-08 미래에셋 실물 · 스캔본에서 겪은 것), 실행할 때마다 아래를 먼저 본다.

| 항목 | 왜 보나 |
|---|---|
| 읽은 방법 | 엑셀 · 글자 PDF 는 숫자가 그대로다. OCR 은 자릿수 누락 · 소수점↔쉼표 · 숫자 닮은 글자가 생긴다 |
| 잔액 열 | 원화 · 외화 잔액과 보유수량이 줄마다 있어야 잘못 읽은 숫자를 대사로 잡는다. 없으면 검증 수단이 없다 |
| 일자의 뜻 | 체결일 칸이 있는지. 결제일 자료면 연말 미결제 매매가 다음 해로 밀린다 |
| 기초 | 기간 전에 들고 있던 종목 · 외화의 장부금액. 없으면 처분손익이 부풀려진다 |
| 계좌 주체 | 법인 계좌는 국내 상장주식 배당에 원천세가 없다. 원천세가 찍혀 있으면 개인 계좌 자료일 수 있다 |
| 못 읽은 것 | 못 맞춘 머리글 · 미분류 적요 · 검토대기 |
| 기간 · 통화 | 기말일 · 환율표가 기간을 덮는지 |
"""
from __future__ import annotations

import re
from decimal import Decimal

Z = Decimal(0)
_TRADE_DATE = re.compile(r"체결|매매|약정|trade", re.I)


def _ratio(n, d):
    return f"{n}/{d}" + (f"({n * 100 // d}%)" if d else "")


def diagnose(tables, txs, cfg, res, hint, source_kinds, rates_rows):
    """[(항목, 판정, 내용, 할 일)] 판정: OK · 정보 · 확인 · 위험."""
    out = []
    ocr = "OCR" in source_kinds

    # 1) 읽은 방법
    fixes = sum(1 for t in txs for n in t.notes if n.startswith("OCR"))
    if ocr:
        out.append(("읽은 방법", "확인", f"{' · '.join(sorted(source_kinds))}. OCR 교정 {fixes}건(거래 메모 「OCR …」)",
                    "OCR 은 자릿수가 빠지거나(1,000,000 → 1,00,000) 소수점을 쉼표로 읽는다(1,234.567 → 1,234,567). "
                    "잔액 · 같은 행 계산으로 고친 것과 실행보고의 의심 칸은 원본과 한 번 대조한다"))
    else:
        out.append(("읽은 방법", "OK", " · ".join(sorted(source_kinds)) or "표준거래표", ""))

    # 2) 잔액 열: 대사로 검증할 수 있는가. 잔액은 누적이라 잔액이 찍힌 행 사이의 오독도 다음 잔액에서 드러난다.
    #    그래서 행마다가 아니라 「돈 · 수량이 움직인 날마다 잔액이 한 번은 있는지」를 본다(미래에셋은 묶음 끝 행에만 잔액)
    def day_cov(rows, has):
        days = {}
        for t in rows:
            days.setdefault((t.date, getattr(t, "_ck", "")), False)
            if has(t):
                days[(t.date, getattr(t, "_ck", ""))] = True
        return sum(days.values()), len(days)

    krw_rows = [t for t in txs if t.ccy == "KRW" and (t.I or t.J)]
    fx_rows = [t for t in txs if t.ccy != "KRW" and (t.G or t.H)]
    trade_rows = [t for t in txs if t.event in ("매수", "매도")]
    kd = day_cov(krw_rows, lambda t: t.krw_bal is not None)
    fd = day_cov(fx_rows, lambda t: t.fx_bal is not None)
    hd = day_cov(trade_rows, lambda t: t.hold_qty is not None)
    present = [x for x in (kd, fd, hd) if x[1]]
    none_at_all = present and all(x[0] == 0 for x in present)
    full = all(x[0] >= x[1] * 0.9 for x in present)
    verdict = "위험" if none_at_all else ("OK" if full else "확인")
    out.append(("잔액 열(대사 수단)", verdict,
                f"잔액이 찍힌 날: 원화 {_ratio(*kd)} · 외화 {_ratio(*fd)} · 보유수량 {_ratio(*hd)}",
                "" if verdict == "OK" else (
                    "잔액 열이 없어 잘못 읽은 숫자 · 빠진 행을 잡을 방법이 없다. 잔액이 찍힌 거래내역(증명서 · 종합거래내역)을 다시 받는다"
                    + (". OCR 자료는 잔액 열 없이 전표를 확정하지 않는다" if ocr else "") if none_at_all else
                    "잔액이 없는 날이 있다. 그날 금액은 다음 잔액에서야 드러나니 원본과 대조한다")))

    # 3) 일자의 뜻
    trade_col = None
    for tb in tables:
        for ci, j, f, orig in tb.columns:
            if f == "일자":
                trade_col = orig
    if not tables:
        out.append(("일자의 뜻", "정보", "표준거래표 일자 열(체결일로 적는다)", ""))
    elif trade_col and _TRADE_DATE.search(str(trade_col)):
        out.append(("일자의 뜻", "OK", f"체결일 칸 「{trade_col}」 을 일자로 썼다", ""))
    elif trade_rows:
        out.append(("일자의 뜻", "확인", f"「{trade_col}」 칸이 체결일인지 결제일인지 자료로 알 수 없다",
                    "일반기업회계기준 6.4의2 · 법인세법 시행령 제68조①5호는 체결일 기준이다. 결제일 자료면 기말 직전 2영업일 "
                    "체결분을 미수금 · 미지급금으로 따로 잡는다"))

    # 4) 기초
    begin = cfg.get("기초") or {}
    zero_book = [s for s in begin.get("종목") or [] if Decimal(str(s.get("수량", 0) or 0)) > 0
                 and Decimal(str(s.get("장부금액", 0) or 0)) == 0]
    if zero_book:
        names = ", ".join(str(s.get("종목")) for s in zero_book[:5])
        out.append(("기초 장부금액", "위험", f"기초 수량만 있고 장부금액이 0 인 종목 {len(zero_book)}개({names})",
                    "이 종목을 팔면 원가가 낮게 잡혀 처분이익이 부풀려진다. 전기말 계정명세서의 장부금액을 설정 「기초」 에 넣는다"))
    elif hint:
        out.append(("기초 장부금액", "확인", f"기초를 거래내역에서 역산했다({len(hint)}건)", "전기말 장부와 맞춘다"))
    else:
        out.append(("기초 장부금액", "OK", "설정에 기초 잔고가 있다" if begin else "기간 전 잔고 없음", ""))

    # 5) 계좌 주체
    who = cfg.get("계좌주체", "법인")
    taxed = [r for r in res.rows if r.kind == "국내배당" and r.AF > 0
             and not re.search(r"ETF|KODEX|TIGER|ACE|RISE|SOL|PLUS|KBSTAR|HANARO|ARIRANG|투자신탁", r.tx.name or "", re.I)]
    if taxed and who == "법인":
        out.append(("계좌 주체", "확인", f"국내 상장주식 배당 {len(taxed)}건에 원천세가 찍혀 있다(예: {taxed[0].tx.name})",
                    "법인이 받는 상장주식 배당은 원천징수 대상이 아니다(법인세법 제73조①). 개인 계좌 자료인지, 증권사가 잘못 뗀 것인지 본다"))
    else:
        out.append(("계좌 주체", "OK" if who == "법인" else "정보", f"{who} 계좌로 처리", ""))

    # 6) 못 읽은 것
    unmapped = sorted({u for tb in tables for u in tb.unmapped})
    kinds = {}
    for k, _, _ in res.issues:
        kinds[k] = kinds.get(k, 0) + 1
    bad = kinds.get("미분류", 0) + kinds.get("검토대기", 0)
    out.append(("못 읽은 것", "OK" if not bad else "확인",
                f"미분류 {kinds.get('미분류', 0)} · 검토대기 {kinds.get('검토대기', 0)} · 못 맞춘 머리글 {len(unmapped)}"
                + (f"({', '.join(unmapped[:8])}{' …' if len(unmapped) > 8 else ''})" if unmapped else ""),
                "" if not bad else "금액 열인데 못 맞춘 머리글은 설정 「머리글」 에, 미분류 적요는 설정 「적요규칙」 에 더하고 다시 돌린다"))

    # 7) 기간 · 통화 · 환율
    ds = [t.date for t in txs if t.date]
    end = (cfg.get("기말") or {}).get("일자")
    ccys = sorted({t.ccy for t in txs if t.ccy != "KRW"})
    rate_days = {}
    for d, c, v, s in rates_rows or []:
        rate_days.setdefault(c, []).append(d)
    miss = [c for c in ccys if not rate_days.get(c)]
    span = f"{min(ds)} ~ {max(ds)}" if ds else "거래 없음"
    out.append(("기간 · 통화", "위험" if miss else ("확인" if not end else "OK"),
                f"{span} · 기말 {end or '없음'} · 외화 {', '.join(ccys) or '없음'}"
                + (f" · 환율표 없음: {', '.join(miss)}" if miss else ""),
                "환율표를 받는다(fetch_rates.py)" if miss else ("기말 평가를 하려면 설정 「기말」 에 일자 · 환율 · 단가를 넣는다" if not end else "")))
    return out


def as_markdown(rows):
    lines = ["| 항목 | 판정 | 내용 | 할 일 |", "|---|---|---|---|"]
    for a, b, c, d in rows:
        lines.append(f"| {a} | {b} | {c} | {d} |")
    return lines
