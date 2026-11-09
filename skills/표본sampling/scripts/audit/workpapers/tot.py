"""감사-TOT 증빙 대조표(2026-10-26). 표본 줄마다 세금계산서 승인번호 · 금액 · 날짜 · 거래처 · 통장(입금 · 지급)을 대조한다.

표본은 새로 뽑지 않는다. 4000P(sales.split_samples) · 4000Q · 4000R · 4000EE(vouch._sample_sheet)의 표본 엔진이 고른 줄을
그대로 받아 vouch.table 의 표본 표에 엔진 대조 칸을 더한다. 대조할 영역과 계정 낱말은 definitions/tot.yaml 이다.

  sources(ctx)          받은자료 판독(한 번만, ctx 에 둔다): 홈택스 전자세금계산서 목록(매출 · 매입) · 통장 거래내역 ·
                        원천세 신고서(PDF, 귀속월 총지급액) · 급여대장(월 합계), 분개장 전표 묶음
  check(ctx, kind, x)   표본 한 줄(분개장 행 x)의 대조 결과 {no, ev_amount, 승인번호 · 금액 · 날짜 · 거래처 · 통장 · 종합, note}
  HEADS · put(...)      표본 표에 넣는 엔진 칸과 값
  summary(results)      종합 칸 건수(일치 · 불일치 · 자료 없음)
  report(d, nos)        이미 만든 조서의 표본 표를 다시 읽어 대조 결과와 검사 결과 빈 칸을 센다(python -m audit wp tot)

값은 일치 · 불일치 · 자료 없음 셋이다(급여 줄의 거래처는 해당 없음). 엔진은 받은자료와 분개장에 있는 값만 맞대고 판정하지 않는다.
회계사 확인 칸(금액 · 일자 · 기간 · 거래처 · 입금 · 지급 · 증빙 종류 · 검사 결과)은 엔진이 채우지 않는다. 검사 결과 칸 이름은
status.samples 가 읽는 꼴(시트 이름에 「표본」, 머리줄 첫 칸 「#」, 「검사 결과」 열) 그대로라 F12 · 보드 카드 표본 수에 잡힌다.
홈택스에 접속하지 않는다. 회사가 내려받아 준 목록 엑셀만 읽는다.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path

from .. import figures, reader, wp
from . import common

OK, BAD, NA, NOT = "일치", "불일치", "자료 없음", "해당 없음"
HEADS = ["승인번호 · 신고", "증빙 금액", "승인번호 대조", "금액 대조", "날짜 대조", "거래처 대조", "통장 대조", "자동 대조", "대조 메모"]
FIELDS = ["evidence", "amount", "date", "party", "bank"]          # 「승인번호 대조」 ~ 「통장 대조」 의 결과 열쇠
WIDTHS = [26, 16, 10, 10, 10, 10, 10, 10, 40]


def settings() -> dict:
    return common.load_def("tot.yaml")


def area_kind(code: str) -> str | None:
    """영역 코드(P · Q · R · EE)의 대조 종류(sales · purchase · payroll). 대조하지 않는 영역이면 None."""
    return (settings().get("areas") or {}).get(code)


# ---------------------------------------------------------------- 이름 · 계정
_CORP = re.compile(r"주식회사|유한회사|\(주\)|㈜|\(유\)")


def pnorm(s) -> str:
    """거래처 상호 맞춤용: 주식회사 · (주) · 공백 · 가운뎃점을 지운다. 다른 괄호 글자((본점) · (지점))는 남긴다."""
    return re.sub(r"[\s·.,]", "", _CORP.sub("", str(s or "")))


def _has(name, words) -> bool:
    n = str(name or "")
    return any(w in n for w in words or [])


def _acc(st: dict, kind: str, x) -> bool:
    a = st["accounts"]
    n = x.name or ""
    if kind == "bank":
        return _has(n, a["bank"]) and not _has(n, a.get("bank_exclude"))
    if kind == "withholding":
        return _has(n, a["withholding"]) and not _has(n, a["vat"])
    return _has(n, a[kind])


# ---------------------------------------------------------------- 받은자료 판독
def _cols(head: list[str], want: dict) -> dict:
    out = {}
    for k, names in want.items():
        idx = [i for i, h in enumerate(head) if h in names]
        if idx:
            out[k] = idx
    return out


def _header(rows: list[tuple], want: dict, need: tuple, scan: int):
    for hi, r in enumerate(rows[:scan]):
        head = [reader._norm(v) for v in r]
        c = _cols(head, want)
        if all(k in c for k in need):
            return hi, c
    return None


def _side_word(path: Path, rows: list[tuple]) -> str | None:
    """파일 이름 · 머리줄 위 글에서 매출 · 매입 낱말."""
    text = path.stem + " " + " ".join(str(v) for r in rows for v in r if v)
    s, p = "매출" in text, "매입" in text
    return "sales" if s and not p else "purchase" if p and not s else None


def _read_book(path: Path) -> list[tuple[str, list[tuple]]]:
    wb = reader._open(path)
    try:
        return [(ws.title, [tuple(r) for r in ws.iter_rows(values_only=True)]) for ws in wb.worksheets]
    finally:
        wb.close()


def _peek(path: Path, scan: int) -> list[tuple[str, list[tuple]]]:
    wb = reader._open(path)
    try:
        return [(ws.title, [tuple(r) for r in ws.iter_rows(values_only=True, max_row=scan)]) for ws in wb.worksheets]
    finally:
        wb.close()


def _invoices(path: Path, rel: str, rows: list[tuple], hi: int, c: dict, company: str) -> list[dict]:
    sup = (c.get("supplier") or [None])[0]
    buy = (c.get("buyer") or [None])[0]
    names = c.get("name") or []
    if sup is None and names:
        sup = names[0]
    if buy is None and len(names) > 1:
        buy = names[1]
    word = _side_word(path, rows[:hi])
    me = pnorm(company)
    out = []
    for r in rows[hi + 1:]:
        if not r or all(v in (None, "") for v in r):
            continue
        g = (lambda k: r[c[k][0]] if k in c and c[k][0] < len(r) else None)
        no, dt, supply = g("approval"), reader._date(g("date")), reader._num(g("supply"))
        if not no or dt is None or supply is None:
            continue
        s_name = str(r[sup]).strip() if sup is not None and sup < len(r) and r[sup] else ""
        b_name = str(r[buy]).strip() if buy is not None and buy < len(r) and r[buy] else ""
        if me and pnorm(s_name) == me:
            side, party = "sales", b_name
        elif me and pnorm(b_name) == me:
            side, party = "purchase", s_name
        elif word:
            side, party = word, (b_name if word == "sales" else s_name)
        else:
            continue
        tax = reader._num(g("tax"))
        total = reader._num(g("total"))
        out.append({"no": str(no).strip(), "date": dt, "party": party, "key": pnorm(party), "supply": reader._int(supply),
                    "tax": reader._int(tax) if tax is not None else None,
                    "total": reader._int(total) if total is not None else (reader._int(supply + (tax or 0))),
                    "side": side, "file": rel})
    return out


def _bank_rows(rel: str, rows: list[tuple], hi: int, c: dict) -> list[dict]:
    out = []
    for r in rows[hi + 1:]:
        if not r:
            continue
        g = (lambda k: r[c[k][0]] if k in c and c[k][0] < len(r) else None)
        dt = reader._date(g("date"))
        if dt is None:
            continue
        dep, wd = reader._num(g("deposit")) or 0, reader._num(g("withdraw")) or 0
        if not dep and not wd:
            continue
        out.append({"date": dt, "in": reader._int(dep), "out": reader._int(wd), "memo": str(g("memo") or "")[:40], "file": rel})
    return out


def _received(d: Path, st: dict) -> list[dict]:
    skip = set(st.get("skip_kinds") or [])
    return [f for f in figures._docs(d)["files"]
            if f.get("role") == "received" and Path(f["path"]).suffix.lower() in reader.READABLE and f.get("kind") not in skip]


def _withholding(d: Path) -> tuple[dict, list[str]]:
    """원천세 신고서 PDF 의 귀속월 총지급액 {YYYY-MM: 금액}. 글자 층이 없어 OCR 로 읽은 값은 확인 전이라 쓰지 않는다."""
    from ..analysis import pdfread

    months, files = {}, []
    for rel in figures.received(d, "원천세 신고서"):
        if Path(rel).suffix.lower() != ".pdf":
            continue
        try:
            r = pdfread.withholding(Path(d) / rel)
        except Exception:  # noqa: BLE001  깨진 PDF 는 건너뛴다(분석 쪽이 까닭을 적는다)
            continue
        if r.get("source") == "ocr" or not r.get("months"):
            continue
        files.append(rel)
        for k, v in r["months"].items():
            months[k] = {"pay": reader._int(v["pay"]), "file": rel}
    return months, files


def _register(d: Path) -> tuple[dict, list[str]]:
    """급여대장의 월 합계 {YYYY-MM: 금액}. 「1월」 처럼 해 없이 적힌 달은 사업연도 시작 해로 본다."""
    months, files = {}, []
    try:
        y0 = common.fy_start(d).year
    except Exception:  # noqa: BLE001
        y0 = None
    for rel in figures.received(d, reader.PAYROLL):
        p = Path(d) / rel
        if p.suffix.lower() not in reader.READABLE:
            continue
        try:
            facts = reader.read(p, reader.PAYROLL)
        except Exception:  # noqa: BLE001
            continue
        got = False
        for f in facts:
            m = re.match(r"^(\d{4})-(\d{2}) 급여 합계", f["text"]) or re.match(r"^(\d{1,2})월 급여 합계", f["text"])
            if not m or f.get("value") is None:
                continue
            k = f"{m.group(1)}-{m.group(2)}" if m.lastindex == 2 else (f"{y0}-{int(m.group(1)):02d}" if y0 else None)
            if k:
                months[k] = {"pay": f["value"], "file": rel}
                got = True
        if got:
            files.append(rel)
    return months, files


def _bind(files: list[dict], rows: list[dict], lines: list, st: dict) -> None:
    """통장 파일마다 어느 계좌(분개장 예금 줄의 거래처 · 계정)인지 정한다. 파일 기간 안 그 계좌 예금 줄 가운데 같은 날 같은 금액 ·
    같은 방향이 통장에 있는 비율이 가장 높은 계좌(bank_bind_ratio 이상). 못 정하면 account 없이 금융기관 이름으로만 본다."""
    acc: dict[str, list] = {}
    for x in lines:
        if _acc(st, "bank", x):
            acc.setdefault(x.party or x.name, []).append(x)
    for f in files:
        have = {(b["date"], b["in"], b["out"]) for b in rows if b["file"] == f["path"]}
        best, best_r = None, 0.0
        for a, xs in acc.items():
            mv = [x for x in xs if f["start"] <= x.date <= f["end"]]
            if not mv:
                continue
            hit = sum(1 for x in mv if (x.date, _amt(x) if x.dr > 0 else 0, _amt(x) if x.cr > 0 else 0) in have)
            r = hit / len(mv)
            if r > best_r:
                best, best_r = a, r
        f["account"] = best if best_r >= float(st.get("bank_bind_ratio", 0.5)) else None
        f["bind_ratio"] = round(best_r, 3)


def sources(ctx: dict) -> dict:
    """받은자료와 분개장 묶음. ctx 안에서 한 번만 읽는다(같은 make 의 여러 조서가 함께 쓴다)."""
    if ctx.get("_tot") is not None:
        return ctx["_tot"]
    from ..analysis import inst
    from .lead import _journals

    d = Path(ctx["d"])
    st = settings()
    scan = int(st.get("header_scan", 15))
    company = (common.case(d).get("company") or {}).get("name") or d.parent.name
    hi_inv, hi_bank = st["heads"]["invoice"], st["heads"]["bank"]
    inv, bank, inv_files, bank_files = [], [], [], []
    for f in _received(d, st):
        rel, p = f["path"], d / f["path"]
        try:
            peek = _peek(p, scan)
        except Exception:  # noqa: BLE001  열리지 않는 엑셀은 다른 판독기가 까닭을 적는다
            continue
        bank_ok = f.get("kind") in (st.get("bank_kinds") or []) or _has(Path(rel).stem, st.get("bank_name_keys"))
        want = [(s, rows) for s, rows in peek if _header(rows, hi_inv, ("date", "approval", "supply"), scan)
                or (bank_ok and _header(rows, hi_bank, ("date", "deposit", "withdraw"), scan))]
        if not want:
            continue
        for sheet, rows in _read_book(p):
            h = _header(rows, hi_inv, ("date", "approval", "supply"), scan)
            if h:
                got = _invoices(p, rel, rows, h[0], h[1], company)
                if got:
                    inv += got
                    inv_files.append({"path": rel, "count": len(got), "sides": sorted({x["side"] for x in got})})
                continue
            h = _header(rows, hi_bank, ("date", "deposit", "withdraw"), scan) if bank_ok else None
            if h:
                got = _bank_rows(rel, rows, h[0], h[1])
                if got:
                    bank += got
                    bank_files.append({"path": rel, "count": len(got), "start": min(x["date"] for x in got),
                                       "end": max(x["date"] for x in got), "inst": inst.name(Path(rel).stem, file=True)})
    wht, wht_files = _withholding(d)
    reg, reg_files = _register(d)
    j = _journals(ctx)
    lines = list(j["cur"]) + list(j["post"])
    by_v: dict[tuple, list] = {}
    for x in lines:
        by_v.setdefault((x.file, x.date, x.voucher), []).append(x)
    by_party: dict[str, list] = {}
    exact: dict[tuple, set] = {}               # (일자, 거래처) → {(금액, 전표)}: 세금계산서가 어느 분개 행 몫인지 가른다
    for x in lines:
        if x.party:
            k = pnorm(x.party)
            by_party.setdefault(k, []).append(x)
            exact.setdefault((x.date, k), set()).add((_amt(x), (x.file, x.date, x.voucher)))
    _bind(bank_files, bank, lines, st)
    out = {"invoices": {"sales": [x for x in inv if x["side"] == "sales"], "purchase": [x for x in inv if x["side"] == "purchase"]},
           "invoice_files": inv_files, "bank": bank, "bank_files": bank_files, "wht": wht, "wht_files": wht_files,
           "register": reg, "register_files": reg_files, "vouchers": by_v, "by_party": by_party, "exact": exact, "settings": st}
    ctx["_tot"] = out
    return out


def used_files(src: dict) -> list[str]:
    return ([f["path"] for f in src["invoice_files"]] + [f["path"] for f in src["bank_files"]] + src["wht_files"] + src["register_files"])


# ---------------------------------------------------------------- 대조
def _voucher(src: dict, x) -> list:
    return src["vouchers"].get((x.file, x.date, x.voucher)) or [x]


def _amt(x) -> int:
    return reader._int(abs(x.cr - x.dr))


def _invoice(src: dict, side: str, x, v: list) -> dict:
    st = src["settings"]
    invs = src["invoices"][side]
    word = "매출" if side == "sales" else "매입"
    if not invs:
        return {"no": None, "ev_amount": None, "evidence": NA, "amount": NA, "date": NA, "party": NA,
                "note": [f"받은자료에 홈택스 {word} 세금계산서 목록이 없습니다"]}
    amt, key, win = _amt(x), pnorm(x.party), int(st.get("invoice_window_days", 15))
    has_vat = any(_acc(st, "vat", y) for y in v)
    me = (x.file, x.date, x.voucher)

    def taken(i) -> bool:
        """다른 분개 행과 일자 · 거래처 · 금액이 꼭 맞는 세금계산서(그 행 몫)."""
        return any(vk != me and a in (i["supply"], i["total"]) for a, vk in src["exact"].get((i["date"], i["key"]), ()))

    near = [i for i in invs if abs((i["date"] - x.date).days) <= win and not taken(i)]

    def rank(i):
        same_p = bool(key) and i["key"] == key
        same_a = amt in (i["supply"], i["total"])
        r = 0 if same_p and same_a else 1 if same_p else 2 if same_a and i["date"] == x.date else 9
        if not has_vat and r:          # 부가세 줄이 없는 전표(선수금 대체 등)는 거래처 · 금액이 꼭 맞을 때만 잇는다
            r = 9
        return (r, abs(i["supply"] - amt), abs((i["date"] - x.date).days))

    best = min(near, key=rank, default=None)
    if best is not None and rank(best)[0] < 9:
        note = []
        a = OK if amt in (best["supply"], best["total"]) else BAD
        if a == BAD:
            note.append(f"공급가액 {best['supply']:,} · 장부 {amt:,} · 차이 {amt - best['supply']:,}")
        dd = (best["date"] - x.date).days
        dt = OK if dd == 0 else BAD
        if dt == BAD:
            note.append(f"작성일자 {best['date'].isoformat()}({dd:+d}일)")
        pt = OK if best["key"] == key else BAD
        if pt == BAD:
            note.append(f"세금계산서 상호 {best['party']}")
        return {"no": best["no"], "ev_amount": best["supply"], "evidence": OK, "amount": a, "date": dt, "party": pt,
                "note": note, "file": best["file"]}
    n_party = sum(1 for i in invs if key and i["key"] == key)
    if n_party and has_vat:
        return {"no": "없음", "ev_amount": None, "evidence": BAD, "amount": NA, "date": NA, "party": NA,
                "note": [f"{word} 목록에 이 거래처 세금계산서 {n_party}건이 있으나 이 줄(일자 ±{win}일)에 맞는 승인번호가 없습니다"]}
    why = (f"{word} 목록에 이 거래처 세금계산서가 없습니다(카드 · 현금영수증 · 수출 · 계산서 등 다른 증빙)" if not n_party else
           "이 전표에 부가세 줄이 없어 세금계산서를 찾지 않았습니다(선수금 대체 · 결산 분개 등)")
    return {"no": None, "ev_amount": None, "evidence": NA, "amount": NA, "date": NA, "party": NA, "note": [why]}


def _payroll(src: dict, x, v: list) -> dict:
    ym = x.date.isoformat()[:7]
    gross = reader._int(sum(y.dr for y in v))
    w, r = src["wht"].get(ym), src["register"].get(ym)
    if not src["wht_files"] and not src["register_files"]:
        return {"no": None, "ev_amount": None, "evidence": NA, "amount": NA, "date": NA, "party": NOT,
                "note": ["받은자료에 원천세 신고서 · 급여대장이 없습니다"]}
    if not w and not r:
        return {"no": None, "ev_amount": None, "evidence": NA, "amount": NA, "date": NA, "party": NOT,
                "note": [f"{ym} 귀속 원천세 신고서 · 급여대장 줄이 받은자료에 없습니다"]}
    note, bad = [], False
    for lab, e in (("원천세 총지급액", w), ("급여대장 월 합계", r)):
        if e and e["pay"] != gross:
            bad = True
            note.append(f"{lab} {e['pay']:,} · 급여 전표 차변 합 {gross:,} · 차이 {gross - e['pay']:,}")
    if not w:
        note.append(f"{ym} 귀속 원천세 신고서 없음(급여대장만 대조)")
    if not r:
        note.append(f"{ym} 급여대장 없음(원천세 신고만 대조)")
    no = " · ".join(t for t, e in ((f"원천세 {ym} 귀속", w), (f"급여대장 {ym}", r)) if e)
    return {"no": no, "ev_amount": (w or r)["pay"], "evidence": OK, "amount": BAD if bad else OK, "date": OK, "party": NOT,
            "note": note, "file": (w or r)["file"]}


def _movement(src: dict, side: str, x, v: list) -> tuple[list[tuple], str | None]:
    """이 줄의 돈이 오간 예금 줄 [(일자, 금액, 입금 여부, 계좌)]과 못 찾은 까닭."""
    st = src["settings"]
    inflow = side == "sales"
    own = [y for y in v if _acc(st, "bank", y) and ((y.dr > 0) if inflow else (y.cr > 0))]
    if own:
        return [(y.date, _amt(y), inflow, y.party or y.name) for y in own], None
    kind = "receivable" if inflow else "payable"
    key = pnorm(x.party)
    open_ = [y for y in v if _acc(st, kind, y) and pnorm(y.party) == key and ((y.dr > 0) if inflow else (y.cr > 0))]
    if not key or not open_:
        return [], "이 전표에 같은 거래처의 " + ("채권" if inflow else "채무") + " 줄이 없어 " + ("회수" if inflow else "지급") + " 전표를 찾지 않았습니다"
    g = _amt(open_[0])
    limit = x.date + timedelta(days=int(st.get("settle_days", 120)))
    for y in sorted(src["by_party"].get(key, []), key=lambda z: (z.date, z.voucher)):
        if y.date < x.date or y.date > limit or (y.file, y.date, y.voucher) == (x.file, x.date, x.voucher):
            continue
        if not _acc(st, kind, y) or _amt(y) != g or not ((y.cr > 0) if inflow else (y.dr > 0)):
            continue
        sv = _voucher(src, y)
        banks = [z for z in sv if _acc(st, "bank", z) and ((z.dr > 0) if inflow else (z.cr > 0))]
        if not banks:
            return [], f"{y.date.isoformat()} " + ("회수" if inflow else "지급") + " 전표에 예금 줄이 없습니다(어음 · 상계 등)"
        return [(z.date, _amt(z), inflow, z.party or z.name) for z in banks], None
    return [], ("회수" if inflow else "지급") + f" 전표를 분개장에서 찾지 못했습니다({g:,}, {int(st.get('settle_days', 120))}일 안)"


def _inst_ok(acct: str | None, f: dict) -> bool:
    from ..analysis import inst

    a = inst.name(acct) if acct else None
    b = f.get("inst")
    if not a or not b:
        return True
    a, b = a.replace("은행", ""), b.replace("은행", "")
    return a in b or b in a


def _bank(src: dict, side: str, x, v: list) -> tuple[str, list[str]]:
    if not src["bank_files"]:
        return NA, ["받은자료에 통장 거래내역이 없습니다"]
    moves, why = _movement(src, side, x, v)
    if not moves:
        return NA, [why] if why else []
    note, res = [], []
    for day, amt, inflow, acct in moves:
        files = [f for f in src["bank_files"] if f["start"] <= day <= f["end"]
                 and (f["account"] == acct if f.get("account") else _inst_ok(acct, f))]
        if not files:
            res.append(NA)
            note.append(f"통장 거래내역 기간 밖({day.isoformat()} {acct})")
            continue
        paths = {f["path"] for f in files}
        hit = [b for b in src["bank"] if b["file"] in paths and b["date"] == day and (b["in"] if inflow else b["out"]) == amt]
        if hit:
            res.append(OK)
            note.append(f"통장 {day.isoformat()} {'입금' if inflow else '출금'} {amt:,}")
        else:
            res.append(BAD)
            note.append(f"통장에 같은 날 같은 금액 {'입금' if inflow else '출금'}이 없습니다({day.isoformat()} {amt:,} {acct})")
    out = BAD if BAD in res else OK if OK in res else NA
    return out, note


def _side(kind: str, x) -> str:
    if kind == "sales":
        return "sales"
    return "purchase"


def is_payroll(src: dict, x, v: list) -> bool:
    st = src["settings"]
    return _acc(st, "payroll", x) and x.dr > 0 and any(_acc(st, "withholding", y) and y.cr > 0 for y in v)


def check(ctx: dict, kind: str, x) -> dict:
    """표본 한 줄의 대조. kind 는 sales · purchase · payroll(definitions/tot.yaml areas)."""
    src = sources(ctx)
    v = _voucher(src, x)
    side = _side(kind, x)
    if kind == "payroll" and is_payroll(src, x, v):
        res = _payroll(src, x, v)
    else:
        res = _invoice(src, side, x, v)
    b, bn = _bank(src, side, x, v)
    res["bank"] = b
    res["note"] = list(res.get("note") or []) + bn
    vals = [res[k] for k in FIELDS]
    if BAD in vals:
        res["overall"] = BAD
    elif res["evidence"] == OK and all(res[k] in (OK, NOT) for k in ("amount", "date", "party")):
        res["overall"] = OK
    else:
        res["overall"] = NA
    return res


def put(b, ws, row: int, col: int, res: dict) -> None:
    """표본 표 한 행에 엔진 대조 칸 아홉을 적는다(col 은 첫 칸). 불일치는 칠한다."""
    b.put(ws, row, col, res.get("no"), wrap=True, flag=res["evidence"] == BAD)
    b.put(ws, row, col + 1, res.get("ev_amount"), fmt=wp.WON)
    for i, k in enumerate(FIELDS + ["overall"]):
        b.put(ws, row, col + 2 + i, res[k], flag=res[k] == BAD, color=wp.MUTED if res[k] in (NA, NOT) else None)
    b.put(ws, row, col + 8, "; ".join(res.get("note") or []) or None, wrap=True)


def summary(results: list[dict]) -> dict:
    out = {OK: 0, BAD: 0, NA: 0}
    for r in results:
        out[r["overall"]] = out.get(r["overall"], 0) + 1
    return out


def footnote(ws, row: int, ctx: dict, kind: str, results: list[dict]) -> int:
    """표본 표 밑 설명 줄(첫 칸이 글이라 status.samples 가 표본으로 세지 않는다)."""
    src = sources(ctx)
    side = "매출" if kind == "sales" else "매입"
    inv = [f for f in src["invoice_files"] if ("sales" if kind == "sales" else "purchase") in f["sides"]]
    parts = [f"홈택스 {side} 세금계산서 목록 " + (", ".join(f"{Path(f['path']).name}({f['count']}건)" for f in inv) if inv else "없음"),
             "통장 거래내역 " + (", ".join(f"{Path(f['path']).name}({f['start']} ~ {f['end']})" for f in src["bank_files"])
                           if src["bank_files"] else "없음")]
    if kind == "payroll":
        for lab, m in (("원천세 신고", src["wht"]), ("급여대장", src["register"])):
            ks = sorted(m)
            parts.append(f"{lab} " + (f"{len(ks)}개월({ks[0]} ~ {ks[-1]})" if ks else "없음"))
    s = summary(results)
    lines = [f"증빙 대조(감사-TOT, 엔진): 자동 대조 일치 {s[OK]} · 불일치 {s[BAD]} · 자료 없음 {s[NA]}. 받은자료: " + " · ".join(parts),
             "자동 대조는 받은자료 목록과 분개장 값을 맞댄 것이다. 일치 · 불일치 · 자료 없음을 보고 감사인이 금액 · 일자 · 거래처 · 입금 · 지급 · "
             "증빙 종류와 검사 결과를 적는다. 엔진은 확인 칸을 채우지 않는다. 승인번호 대조 불일치는 이 거래처 세금계산서가 목록에 있는데 이 줄에 맞는 것이 없다는 뜻이다"]
    for t in lines:
        ws.cell(row, 1, t).font = wp.font(size=9, color=wp.MUTED)
        row += 1
    for rel in used_files(src):
        common.note_read(rel)
    return row


# ---------------------------------------------------------------- 만든 조서 다시 읽기(wp tot)
def report(d: Path, nos: list[str] | None = None) -> list[dict]:
    """조서목록의 4000 조서 가운데 표본 표에 「자동 대조」 열이 있는 것. 조서마다 {no, file, items, checked, counts, bad: [(행 열쇠, 메모)]}"""
    from openpyxl import load_workbook

    d = Path(d)
    wps = (common.idx(d, "조서목록.json", {}) or {}).get("workpapers", [])
    out = []
    for w in wps:
        no = str(w.get("no") or "")
        if not no.startswith("4000") or not w.get("file") or (nos and no not in nos):
            continue
        p = d / w["file"]
        if not p.is_file():
            continue
        wb = load_workbook(p, read_only=True, data_only=True)
        try:
            e = {"no": no, "file": w["file"], "items": 0, "checked": 0, "counts": {OK: 0, BAD: 0, NA: 0}, "bad": []}
            for s in [x for x in wb.sheetnames if "표본" in x]:
                head = None
                for r in wb[s].iter_rows(values_only=True):
                    if head is None:
                        if r and str(r[0] or "").strip() == "#":
                            head = [str(x or "").strip() for x in r]
                            if "자동 대조" not in head:
                                head = None
                        continue
                    if not r or all(x in (None, "") for x in r):
                        head = None
                        continue
                    if not isinstance(r[0], (int, float)):
                        continue
                    get = (lambda h: r[head.index(h)] if h in head and head.index(h) < len(r) else None)
                    e["items"] += 1
                    e["checked"] += get("검사 결과") not in (None, "")
                    o = get("자동 대조") or NA
                    e["counts"][o] = e["counts"].get(o, 0) + 1
                    if o == BAD:
                        e["bad"].append((str(r[1]), str(get("대조 메모") or "")))
        finally:
            wb.close()
        if e["items"]:
            out.append(e)
    return out
