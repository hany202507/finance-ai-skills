"""R9 묶음 A: 4000 조서 절차 시트(2026-10-06). 샘플 진단 6.2 에서 실제 회계사 조서에 있는데 우리 조서에 없던 표.
시트 이름 앞 번호(.01 …)는 lead.make 가 다 만든 뒤 붙인다(skeleton.finish). 여기서는 번호 없는 이름으로 만든다.

  4000C · 4000AA · 4000BBDD  거래처별 증감(전기말 · 증가 · 감소 · 당기말 · 조회 회신액 · 차이)
  4000BBDD                   차입금 약정(대주 · 실행일 · 만기 · 약정액 · 이율 · 담보), 이자 재계산(적수)
  4000G · 4000H              감가상각 · 상각 재계산(자산별 취득일 · 내용연수 · 방법 · 재계산 · 장부 · 차이)
  4000AA                     부외부채 검토(결산일 다음 기간의 지급 전표 가운데 비용 · 자산으로 간 것)
  4000E                      재고실사 입회(품목별 장부 수량 · 실사 수량 · 차이 · 타처보관)

숫자는 받은자료(계정명세서 · 고정자산대장 · 연령분석표) · 분개장 · 시산표에서 엔진이 읽은 것만 쓴다.
재계산 규칙과 근거는 definitions/recalc.yaml 에 있다. 이율 · 내용연수 · 방법이 파일에 없으면 기입란이다.
부외부채 여부 · 귀속 기간 · 재고 차이 처리 · 차이 사유는 회계사 기입란이다. 엔진은 판단하지 않는다.

  add_sheets(b, code, ctx)   lead.make 가 부른다. 영역에 맞는 시트를 책에 더한다
  post_window(ctx)           결산일 다음 기간의 전표(4000AA 부외부채 검토 · 4000CL 기말 후 출금 검토가 같이 쓴다)
  party_movement(ctx, area) · loans(d) · interest(ctx) · depreciation(ctx, area) · unrecorded(ctx) · inventory(ctx)
                             시트와 시험 · 끝 기준이 같이 쓰는 엔진 계산
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

from openpyxl.utils import get_column_letter as L

from .. import figures, reader, wp
from . import common, skeleton
from .common import ask, won


@lru_cache(maxsize=1)
def _defs_raw() -> dict:
    return common.yaml.safe_load((common.DEFS / "recalc.yaml").read_text(encoding="utf-8"))


def defs() -> dict:
    """recalc.yaml. 원본은 캐시하고 지금 감사 건의 2700B 값을 부를 때마다 겹친다(2026-10-07)."""
    from .. import params

    return params.overlay("recalc", _defs_raw())


def in_group(code, name, key: str) -> bool:
    g = defs()["accounts"][key]
    if code is not None and common.in_ranges(code, g.get("ranges", [])):
        return True
    n = reader._norm(name)
    return any(k in n for k in g.get("names", []))


def _journals(ctx: dict) -> dict:
    from .lead import _journals as j

    return j(ctx)


def _tb_sum(ctx: dict, key: str) -> int:
    """시산표 계정 묶음 합(표시 부호)."""
    return common.reader._int(sum(r["disp"] for r in ctx["tb"] if in_group(r["code"], r["name"], key)))


# ---------------------------------------------------------------- 표 찾기
def find_tables(path: Path, cols: dict[str, list[str]], need: list[str], sheet_keys: list[str] | None = None) -> list[dict]:
    """시트마다 첫 10행에서 머리줄을 찾는다(정확히 같은 이름 먼저, 다음은 포함). [{sheet, col: {키: 열}, rows, title}]"""
    wb = reader._open(path)
    out = []
    try:
        for ws in wb.worksheets:
            if sheet_keys and not any(k in ws.title for k in sheet_keys):
                continue
            rows = [tuple(r) for r in ws.iter_rows(values_only=True)]
            for hi, row in enumerate(rows[:reader.HEADER_SCAN]):
                hs = [reader._norm(v) for v in row]
                col = {}
                for k, cands in cols.items():
                    i = next((i for c in cands for i, h in enumerate(hs) if h == reader._norm(c)), None)
                    if i is None:
                        i = next((i for c in cands if len(reader._norm(c)) >= 2 for i, h in enumerate(hs)
                                  if reader._norm(c) in h and i not in col.values()), None)
                    if i is not None:
                        col[k] = i
                if all(k in col for k in need):
                    title = " ".join(str(v) for r in rows[:hi] for v in r if v)
                    out.append({"sheet": ws.title, "col": col, "rows": rows[hi + 1:], "title": title})
                    break
    finally:
        wb.close()
    return out


def _excel(d: Path, kind: str) -> list[str]:
    """그 종류의 받은자료 가운데 엔진이 여는 엑셀(.xls 는 xlrd 로 연다, 2026-10-18)."""
    return [p for p in figures.received(d, kind) if Path(p).suffix.lower() in reader.READABLE]


# ---------------------------------------------------------------- A2 거래처별 증감
def _party_ends(d: Path, area: str) -> dict:
    """영역별 거래처 기말 잔액(표시 부호). {"rows": {거래처: 금액}, "source"}"""
    spec = defs()["party_movement"][area]
    if area == "C":
        ar = common.ar_by_party(d)
        return {"rows": {p: a for p, a in ar["rows"]}, "source": ar["source"]}
    if area == "BBDD":
        bl = loans(d)
        out: dict[str, int] = {}
        for x in bl:
            out[x["차입처"]] = out.get(x["차입처"], 0) + abs(x["잔액"])
        return {"rows": out, "source": "계정명세서 차입금 표" if bl else None}
    for rel in _excel(d, "계정명세서"):
        for sheet, c, rows, _, _ in reader._tables(d / rel, [["party"], ["ar_total"]], []):
            if not any(k in sheet for k in spec["sheets"]):
                continue
            out = {}
            for r in rows:
                if reader._is_total_row(r):
                    continue
                p, v = reader._cell(r, c["party"]), reader._num(reader._cell(r, c["ar_total"]))
                if p in (None, "") or v is None:
                    continue
                out[str(p).strip()] = out.get(str(p).strip(), 0) + abs(reader._int(v))
            if out:
                common.note_read(rel)
                return {"rows": out, "source": f"{rel} '{sheet}' 시트"}
    return {"rows": {}, "source": None}


def _replies(d: Path, area: str) -> dict:
    kinds = defs()["party_movement"][area].get("reply_kinds", [])
    out = {}
    for e in (common.idx(d, "조회.json", {}) or {}).get("confirmations", []):
        if e.get("kind") in kinds and e.get("reply_amount") is not None:
            out[e["target"]] = e["reply_amount"]
    return out


NO_PARTY = "(거래처 없음)"


def party_movement(ctx: dict, area: str) -> dict:
    """거래처별 전기말 · 증가 · 감소 · 당기말 · 조회 회신액. 당기말은 명세서, 증가 · 감소는 당기 분개장 거래처 열,
    전기말은 당기말 − 증가 + 감소 로 역산한다(전기 거래처별 잔액 자료가 따로 없을 때의 대사 방법)."""
    d = ctx["d"]
    spec = defs()["party_movement"][area]
    ends = _party_ends(d, area)
    inc: dict[str, float] = {}
    dec: dict[str, float] = {}
    lines = [x for x in _journals(ctx)["cur"] if in_group(x.code, x.name, spec["accounts"])]
    for x in lines:
        p = x.party or NO_PARTY
        up, down = (x.dr, x.cr) if spec["increase"] == "dr" else (x.cr, x.dr)
        inc[p] = inc.get(p, 0) + up
        dec[p] = dec.get(p, 0) + down
    rep = _replies(d, area)
    parties = list(ends["rows"]) + sorted(p for p in set(inc) | set(dec) if p not in ends["rows"])
    rows = []
    for p in parties:
        i, o = reader._int(inc.get(p, 0)), reader._int(dec.get(p, 0))
        end = ends["rows"].get(p)
        known = end is not None
        end = end if known else 0
        r = rep.get(p)
        rows.append({"party": p, "prior": reader._int(end - i + o), "inc": i, "dec": o, "end": end, "in_schedule": known,
                     "reply": r, "diff": None if r is None else reader._int(r - end)})
    tb_end = _tb_sum(ctx, spec["accounts"])
    pv, psrc = common.prior_for(spec["line"], ctx["prior"], ctx["defs"])
    if pv is None:
        for alt in {"BBDD": ["장기차입금", "단기차입금"], "C": ["매출채권"], "AA": ["매입채무"]}.get(area, []):
            v, s = common.prior_for(alt, ctx["prior"], ctx["defs"])
            if v is not None:
                pv, psrc = (pv or 0) + v, s
    return {"rows": rows, "source": ends["source"], "journal_lines": len(lines), "tb_end": tb_end, "prior_fs": pv, "prior_src": psrc,
            "has_journal": bool(_journals(ctx)["cur"])}


def _sheet_party(b, ctx: dict, area: str) -> None:
    m = party_movement(ctx, area)
    ws, row = b.sheet("거래처별 증감", widths=[20, 16, 16, 16, 16, 16, 16, 28])
    ws.cell(6, 1, "당기말은 명세서, 증가 · 감소는 당기 분개장 거래처 열, 전기말은 당기말 − 증가 + 감소(역산). 조회 회신액은 3320 조회 대장").font = wp.font(size=9, color=wp.MUTED)
    if not m["rows"]:
        why = "당기 분개장이 없어" if not m["has_journal"] else "명세서 · 분개장에서 거래처를 찾지 못해"
        b.put(ws, row, 1, f"{why} 거래처별 증감을 만들지 못했습니다. 판독 필요: 거래처별 잔액 명세와 거래처 열이 있는 분개장을 받아 주십시오",
              flag=True, wrap=True)
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=8)
        return
    row = b.section(ws, row, f"거래처별 증감 ({m['source'] or '명세서 없음, 당기말 0 으로 둠'})")
    row = b.head(ws, row, ["거래처", "전기말", "증가", "감소", "당기말", "조회 회신액", "차이(회신 − 당기말)", "비고"])
    first = row
    # 줄이 많으면 금액(당기말 · 증가 · 감소 가운데 큰 값) 상위와 「기타 (n곳)」 한 줄로 줄인다. 조회 회신이 있는 거래처와
    # 거래처 열이 빈 행은 남긴다. 합계 · 검산은 전체 금액이다(설계 7절)
    top = skeleton.top_n(ctx["defs"])
    shown, rest = skeleton.top_rows(m["rows"], top, lambda r: max(abs(r["end"]), abs(r["inc"]), abs(r["dec"])),
                                    keep=lambda r: r["reply"] is not None or r["party"] == NO_PARTY)
    if rest:
        shown = shown + [{"party": skeleton.others_label(rest), "inc": sum(r["inc"] for r in rest), "dec": sum(r["dec"] for r in rest),
                          "end": sum(r["end"] for r in rest), "reply": None, "diff": None, "in_schedule": True, "others": True}]
    for r in shown:
        b.put(ws, row, 1, r["party"], flag=not r["in_schedule"])
        b.put(ws, row, 2, f"=E{row}-C{row}+D{row}", fmt=wp.WON)
        b.put(ws, row, 3, r["inc"], fmt=wp.WON)
        b.put(ws, row, 4, r["dec"], fmt=wp.WON)
        b.put(ws, row, 5, r["end"], fmt=wp.WON)
        b.put(ws, row, 6, r["reply"], fmt=wp.WON)
        b.put(ws, row, 7, f'=IF(F{row}="","",F{row}-E{row})', fmt=wp.WON, flag=bool(r["diff"]))
        note = "" if r["in_schedule"] else "명세서에 없음(당기말 0 으로 둠)"
        if r["party"] == NO_PARTY:
            note = "분개장 거래처 열이 빈 행"
        if r.get("others"):
            note = "금액 상위가 아닌 거래처 합계"
        b.put(ws, row, 8, note, wrap=True)
        row += 1
    last = row - 1
    b.put(ws, row, 1, "합계", bold=True)
    for c in (2, 3, 4, 5):
        b.put(ws, row, c, f"=SUM({L(c)}{first}:{L(c)}{last})", fmt=wp.WON, bold=True)
    tot = row
    row += 1
    end_sum = sum(r["end"] for r in m["rows"])
    prior_sum = sum(r["prior"] for r in m["rows"])
    b.put(ws, row, 1, "시산표 당기말")
    b.put(ws, row, 5, m["tb_end"], fmt=wp.WON)
    b.put(ws, row, 7, f"=E{tot}-E{row}", fmt=wp.WON, flag=end_sum != m["tb_end"])
    row += 1
    b.put(ws, row, 1, "전기 재무제표")
    b.put(ws, row, 2, m["prior_fs"], fmt=wp.WON)
    b.put(ws, row, 7, f'=IF(B{row}="","",B{tot}-B{row})', fmt=wp.WON, flag=m["prior_fs"] is not None and prior_sum != m["prior_fs"])
    b.put(ws, row, 8, m["prior_src"], wrap=True)
    b.verify(f"{b.no} 거래처별 당기말 합계", f"='거래처별 증감'!E{tot}", end_sum)
    b.verify(f"{b.no} 거래처별 전기말 합계(역산)", f"='거래처별 증감'!B{tot}", prior_sum)
    if rest:
        row += 1
        ws.cell(row, 1, "거래처 " + skeleton.top_note(len(m["rows"]), len(shown) - 1, len(rest), top, "조회 회신이 있는 거래처",
                                                   m["source"])).font = wp.font(size=9, color=wp.MUTED)
    row += 2
    ask(b, ws, row, 1, "거래처별 증감 검토 결과", rule="required")
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=8)


# ---------------------------------------------------------------- A3 차입금 약정 · 이자 재계산
def loans(d: Path) -> list[dict]:
    """계정명세서 차입금 표(대주 · 구분 · 실행일 · 만기 · 약정액 · 이율 · 잔액 · 담보)."""
    from ..report.notes import borrowings_source

    rel, ls = borrowings_source(d)
    if ls:
        common.note_read(rel)                                 # 계정명세서 또는 회사 차입금 리스트
    return ls or []


def _loan_facts(d: Path) -> list[str]:
    """차입 · 담보 · 보증 약정 받은자료의 판독 사실(AI 판독은 확인 여부를 붙인다)."""
    p = Path(d) / "_색인" / "문서목록.json"
    if not p.exists():
        return []
    out = []
    for f in json.loads(p.read_text(encoding="utf-8")).get("files", []):
        if f.get("role") != "received" or f.get("kind") != "차입·담보·보증 약정":
            continue
        tag = "엔진 판독" if all(x.get("basis") == "엔진" for x in f.get("facts") or []) else (
            "AI 판독, 회계사 확인 끝" if f.get("confirmed") and f.get("kind_basis") == "사람" else "AI 판독, 확인 전")
        facts = f.get("facts") or []
        if not facts:
            out.append(f"{f['path']}: 판독 사실 없음(감사-맥락색인 으로 판독해 주십시오)")
        for x in facts:
            page = f" {x['source_page']}" if x.get("source_page") else ""
            out.append(f"{x['text']} ({f['path']}{page}, {tag})")
    return out


def _sheet_loans(b, ctx: dict) -> None:
    ls = loans(ctx["d"])
    ws, row = b.sheet("차입금 약정", widths=[16, 12, 14, 14, 16, 10, 16, 36, 22])
    row = b.section(ws, row, "차입금 약정 명세 (계정명세서 차입금 표)")
    row = b.head(ws, row, ["대주", "구분", "실행일", "만기", "약정액", "이율", "기말 잔액", "담보", "확인(약정서 · 조회서)"])
    if not ls:
        b.put(ws, row, 1, "계정명세서에 차입금 표가 없습니다. 판독 필요: 대주 · 실행일 · 만기 · 약정액 · 이율 · 담보가 있는 차입금 명세를 받아 주십시오",
              flag=True, wrap=True)
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=9)
        row += 2
    else:
        first = row
        for k, x in enumerate(ls, 1):
            key = f"{x['차입처']} {x['구분']}".strip()
            b.put(ws, row, 1, x["차입처"])
            b.put(ws, row, 2, str(x["구분"]))
            b.put(ws, row, 3, str(x["실행일"]))
            for col, field, fmt_ in ((4, "만기", None), (5, "약정액", wp.WON), (6, "금리", "0.00%")):
                v = x.get(field)
                if v in (None, ""):
                    ask(b, ws, row, col, f"{field}: {key}", rule="optional", fmt=fmt_)
                else:
                    b.put(ws, row, col, v if not hasattr(v, "isoformat") else v.isoformat()[:10], fmt=fmt_)
            b.put(ws, row, 7, abs(x["잔액"]), fmt=wp.WON)
            b.put(ws, row, 8, x["담보"], wrap=True)
            ask(b, ws, row, 9, f"약정 확인: {key}", rule="optional")
            row += 1
        b.put(ws, row, 1, "합계", bold=True)
        b.put(ws, row, 7, f"=SUM(G{first}:G{row - 1})", fmt=wp.WON, bold=True)
        b.verify("4000BBDD 차입금 약정 잔액 합계", f"='차입금 약정'!G{row}", sum(abs(x["잔액"]) for x in ls))
        row += 1
        b.put(ws, row, 1, "시산표 차입금")
        b.put(ws, row, 7, _tb_sum(ctx, "borrowings"), fmt=wp.WON)
        b.put(ws, row, 8, f"=G{row - 1}-G{row}", fmt=wp.WON, flag=sum(abs(x["잔액"]) for x in ls) != _tb_sum(ctx, "borrowings"))
        row += 2
    row = b.section(ws, row, "약정서 판독 사실 (AI 판독은 회계사 확인 전에는 참고만)")
    facts = _loan_facts(ctx["d"])
    for t in facts or ["받은자료 계약서 폴더에 차입 · 담보 · 보증 약정이 없습니다"]:
        ws.cell(row, 1, t).font = wp.font(size=9, color=wp.RED if "확인 전" in t else wp.MUTED)
        row += 1
    ws.cell(row + 1, 1, "신용공여 조회(한국신용정보원) 결과와 대사는 3320 은행조회 회신으로 합니다").font = wp.font(size=9, color=wp.MUTED)


def interest(ctx: dict) -> dict:
    """차입처별 적수와 이자 재계산. {"lenders": [...], "no_party_book", "tb_interest", "days_in_year"}
    lender: {party, rows: [{date, memo, open, inc, dec, bal, days, acc}], accrual, rate, rate_src, recalc, book, diff, closing_known}"""
    d = ctx["d"]
    start, end = common.fy_start(d), common.fy_end(d)
    j = _journals(ctx)["cur"]
    moves: dict[str, list] = {}
    for x in j:
        if in_group(x.code, x.name, "borrowings"):
            moves.setdefault(x.party or NO_PARTY, []).append(x)
    book: dict[str, float] = {}
    for x in j:
        if in_group(x.code, x.name, "interest_expense"):
            book[x.party or NO_PARTY] = book.get(x.party or NO_PARTY, 0) + x.dr - x.cr
    ls = loans(d)
    closing: dict[str, int] = {}
    rates: dict[str, set] = {}
    for x in ls:
        closing[x["차입처"]] = closing.get(x["차입처"], 0) + abs(x["잔액"])
        if isinstance(x.get("금리"), (int, float)):
            r = float(x["금리"])
            rates.setdefault(x["차입처"], set()).add(r / 100 if r >= 1 else r)
    tb_debt = _tb_sum(ctx, "borrowings")
    parties = list(closing) + sorted(p for p in moves if p not in closing)
    if not ls and len(moves) <= 1:
        parties = list(moves) or ([NO_PARTY] if tb_debt else [])
        if parties:
            closing[parties[0]] = tb_debt
    days_year = defs()["interest"]["days_in_year"]
    out = []
    for p in parties:
        mv = sorted(moves.get(p, []), key=lambda x: x.date)
        net = sum(x.cr - x.dr for x in mv)
        known = p in closing
        bal = (closing.get(p, 0) - net) if known else None
        rows = []
        if bal is not None:
            rows.append({"date": start, "memo": "기초(당기말 − 당기 증감)", "open": reader._int(bal), "inc": 0, "dec": 0})
            for x in mv:
                rows.append({"date": x.date, "memo": x.memo or x.voucher, "open": None, "inc": reader._int(x.cr), "dec": reader._int(x.dr)})
            cur = 0
            for k, r in enumerate(rows):
                cur = (r["open"] or 0) + cur + r["inc"] - r["dec"] if k else r["open"]
                nxt = rows[k + 1]["date"] if k + 1 < len(rows) else end + timedelta(days=1)
                r["bal"], r["days"] = cur, (nxt - r["date"]).days
                r["acc"] = cur * r["days"]
        acc = sum(r["acc"] for r in rows) if rows else None
        rs = rates.get(p, set())
        rate = next(iter(rs)) if len(rs) == 1 else None
        rate_src = "계정명세서 차입금 표 금리" if rate is not None else ("차입처 안에서 이율이 여러 개라 기입란" if len(rs) > 1 else "이율 자료 없음, 기입란")
        recalc = int(round(acc * rate / days_year)) if acc is not None and rate is not None else None
        bk = reader._int(book.pop(p, 0))
        out.append({"party": p, "rows": rows, "accrual": acc, "rate": rate, "rate_src": rate_src, "recalc": recalc, "book": bk,
                    "diff": None if recalc is None else bk - recalc, "closing_known": known})
    tb_int = _tb_sum(ctx, "interest_expense")
    return {"lenders": out, "other_book": {k: reader._int(v) for k, v in book.items() if abs(v) > 0.5}, "tb_interest": tb_int,
            "days_in_year": days_year, "basis": defs()["interest"]["basis"].strip(), "start": start, "end": end}


def _sheet_interest(b, ctx: dict) -> None:
    it = interest(ctx)
    ws, row = b.sheet("이자 재계산", widths=[16, 12, 34, 16, 16, 16, 16, 8, 22])
    ws.cell(6, 1, "재계산 근거: " + it["basis"]).font = wp.font(size=9, color=wp.MUTED)
    ws.cell(6, 1).alignment = wp.Alignment(wrap_text=True, vertical="top")
    ws.merge_cells(start_row=6, start_column=1, end_row=6, end_column=9)
    ws.row_dimensions[6].height = 42
    row += 1
    ws.cell(row, 1, "연 일수").font = wp.font(color=wp.MUTED)
    ask(b, ws, row, 2, "연 일수(비우면 365)", rule="optional", fmt="0")
    days_ref = f"$B${row}"
    ws.cell(row, 3, "비우면 365 일로 계산합니다. 약정서가 360 일 기준이면 적어 주십시오").font = wp.font(size=9, color=wp.MUTED)
    row += 2
    if not it["lenders"]:
        b.put(ws, row, 1, "차입금 계정의 분개 · 잔액이 없어 이자 재계산을 하지 않았습니다", flag=True, wrap=True)
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=9)
        return
    summary = []
    trivial = ctx["mat"].get("trivial")
    for ln in it["lenders"]:
        p = ln["party"]
        row = b.section(ws, row, f"차입처 {p}")
        if not ln["rows"]:
            b.put(ws, row, 1, f"{p} 의 기말 잔액을 명세서에서 찾지 못해 적수를 계산하지 못했습니다. 판독 필요: 차입처별 잔액 명세",
                  flag=True, wrap=True)
            ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=9)
            row += 2
            summary.append((ln, None, None))
            continue
        row = b.head(ws, row, ["일자", "구분", "적요", "기초", "증가", "감소", "잔액", "일수", "적수"])
        first = row
        for k, r in enumerate(ln["rows"]):
            b.put(ws, row, 1, r["date"].isoformat())
            b.put(ws, row, 2, "기초" if k == 0 else ("증가" if r["inc"] else "감소"))
            b.put(ws, row, 3, r["memo"], wrap=True)
            b.put(ws, row, 4, r["open"] if k == 0 else None, fmt=wp.WON)
            b.put(ws, row, 5, r["inc"] or None, fmt=wp.WON)
            b.put(ws, row, 6, r["dec"] or None, fmt=wp.WON)
            b.put(ws, row, 7, f"=D{row}" if k == 0 else f"=G{row - 1}+E{row}-F{row}", fmt=wp.WON)
            b.put(ws, row, 8, r["days"], fmt="#,##0")
            b.put(ws, row, 9, f"=G{row}*H{row}", fmt="#,##0")
            row += 1
        b.put(ws, row, 1, "합계", bold=True)
        b.put(ws, row, 8, f"=SUM(H{first}:H{row - 1})", fmt="#,##0", bold=True)
        b.put(ws, row, 9, f"=SUM(I{first}:I{row - 1})", fmt="#,##0", bold=True)
        b.verify(f"이자 재계산 {p} 적수 합계", f"='이자 재계산'!I{row}", ln["accrual"])
        b.verify(f"이자 재계산 {p} 일수 합계", f"='이자 재계산'!H{row}", (it["end"] - it["start"]).days + 1)
        acc_ref = f"I{row}"
        row += 2
        summary.append((ln, acc_ref, None))
    row = b.section(ws, row, "재계산 이자와 장부 이자 (차이 = 장부 − 재계산)")
    row = b.head(ws, row, ["차입처", "약정 이율", "이율 출처", "적수 합계", "재계산 이자", "장부 이자", "차이", "", "차이 사유"])
    first = row
    for ln, acc_ref, _ in summary:
        p = ln["party"]
        b.put(ws, row, 1, p)
        if ln["rate"] is not None:
            b.put(ws, row, 2, ln["rate"], fmt="0.00%")
        else:
            ask(b, ws, row, 2, f"약정 이율: {p}", rule="number", fmt="0.00%")
        b.put(ws, row, 3, ln["rate_src"], wrap=True, flag=ln["rate"] is None)
        b.put(ws, row, 4, f"={acc_ref}" if acc_ref else None, fmt="#,##0")
        b.put(ws, row, 5, f'=IF(OR(B{row}="",D{row}=""),"",ROUND(D{row}*B{row}/IF({days_ref}="",{it["days_in_year"]},{days_ref}),0))', fmt=wp.WON)
        b.put(ws, row, 6, ln["book"], fmt=wp.WON)
        b.put(ws, row, 7, f'=IF(E{row}="","",F{row}-E{row})', fmt=wp.WON, flag=bool(ln["diff"]))
        big = ln["diff"] is None or (abs(ln["diff"]) > (trivial or 0))
        ask(b, ws, row, 9, f"이자 차이 사유: {p}", rule="required" if big else "optional")
        row += 1
    for p, v in it["other_book"].items():
        b.put(ws, row, 1, p)
        b.put(ws, row, 3, "차입금 거래처가 아닌 이자비용(미지급이자 · 기타)", wrap=True)
        b.put(ws, row, 6, v, fmt=wp.WON)
        row += 1
    b.put(ws, row, 1, "합계", bold=True)
    b.put(ws, row, 6, f"=SUM(F{first}:F{row - 1})", fmt=wp.WON, bold=True)
    tot = row
    row += 1
    b.put(ws, row, 1, "시산표 이자비용")
    b.put(ws, row, 6, it["tb_interest"], fmt=wp.WON)
    book_sum = sum(ln["book"] for ln in it["lenders"]) + sum(it["other_book"].values())
    b.put(ws, row, 7, f"=F{tot}-F{row}", fmt=wp.WON, flag=book_sum != it["tb_interest"])
    b.verify("이자 재계산 장부 이자 합계", f"='이자 재계산'!F{tot}", book_sum)
    row += 2
    ws.cell(row, 1, f"재계산 이자 · 차이는 연 일수 칸이 비었을 때 {it['days_in_year']} 일 기준 엔진 계산과 같다. "
                    "명백히 사소한 금액을 넘는 차이는 사유를 적고 필요하면 8100A 에 올려 주십시오").font = wp.font(size=9, color=wp.MUTED)


# ---------------------------------------------------------------- A4 감가상각 · 상각 재계산
def _method(v) -> str | None:
    s = reader._norm(v)
    if not s:
        return None
    for m, keys in defs()["depreciation"]["methods"].items():
        if any(k in s for k in keys):
            return m
    return None


def _months(acq: date | None, start: date, end: date) -> int | None:
    """당기 사용 월수(취득월 포함 월할). 기초 전 취득이면 사업연도 월수."""
    full = (end.year * 12 + end.month) - (start.year * 12 + start.month) + 1
    if acq is None:
        return None
    if acq > end:
        return 0
    if acq < start:
        return full
    return (end.year * 12 + end.month) - (acq.year * 12 + acq.month) + 1


def assets(ctx: dict) -> dict:
    """고정자산대장 자산별 줄. {"rows": [...], "source", "title"}"""
    d = ctx["d"]
    dc = defs()["depreciation"]["columns"]
    cols = {"asset_no": dc["asset_no"], "name": reader.COLS["asset"], "acct": dc["acct"], "acq_date": reader.COLS["acq_date"],
            "cost": reader.COLS["acq_cost"], "life": dc["life"], "method": dc["method"], "residual": dc["residual"], "rate": dc["rate"],
            "beg_acc": dc["beg_acc"], "add": reader.COLS["acq_cur"], "dep": reader.COLS["dep_cur"]}
    # 변동내역(substantive.rollforward)이 더 읽는 열. 뒤에 붙여서 앞 열의 머리줄 대응이 바뀌지 않게 한다
    cols.update((defs().get("rollforward") or {}).get("columns") or {})
    for rel in _excel(d, reader.FIXED):
        for t in find_tables(d / rel, cols, ["cost"]):
            c = t["col"]
            title = t["title"]
            out = []
            for r in t["rows"]:
                if reader._is_total_row(r):
                    continue
                cost = reader._num(reader._cell(r, c["cost"]))
                if cost is None:
                    continue
                g = lambda k: reader._cell(r, c.get(k))  # noqa: E731
                life = reader._num(g("life"))
                rate = reader._num(g("rate"))
                resid = reader._num(g("residual"))
                acct = str(g("acct") or "").strip()
                a, _ = common.area_of(acct, "", ctx["defs"]) if acct else ("G", "")
                out.append({"no": str(g("asset_no") or "").strip(), "name": str(g("name") or "").strip(), "acct": acct,
                            "area": "H" if a == "H" else "G", "acq": reader._date(g("acq_date")), "cost": reader._int(cost),
                            "life": reader._int(life) if life else None, "method_raw": g("method"), "method": _method(g("method")),
                            "residual": reader._int(resid) if resid is not None else None,
                            "residual_src": "대장 잔존가치 열" if resid is not None else ("대장 제목 '잔존가치 0'" if "잔존가치0" in reader._norm(title) else None),
                            "rate": (rate / 100 if rate and rate >= 1 else rate), "beg_acc": reader._int(abs(reader._num(g("beg_acc")) or 0)),
                            "book": reader._int(abs(reader._num(g("dep")) or 0)),
                            # 변동내역이 쓰는 값. 대장에 그 열이 없으면 None 이다
                            **{k: (reader._int(abs(reader._num(g(k)) or 0)) if k in c else None)
                               for k in ("add", "disposal", "end_acc", "end_book", "beg_book")}})
            if out:
                common.note_read(rel)
                if not any(r["method"] for r in out) and any(k in reader._norm(title) for k in ("정액법",)):
                    for r in out:
                        r["method"], r["method_raw"] = "정액법", "대장 제목 '정액법'"
                return {"rows": out, "source": f"{rel} '{t['sheet']}' 시트", "title": title}
    return {"rows": [], "source": None, "title": ""}


def depreciation(ctx: dict, area: str) -> dict:
    """자산별 당기 상각 재계산. 엔진이 필요한 값(내용연수 · 방법 · 취득일 · 정률법 상각률)이 모두 있으면 recalc, 아니면 None."""
    d = ctx["d"]
    start, end = common.fy_start(d), common.fy_end(d)
    a = assets(ctx)
    rows = []
    for x in a["rows"]:
        if x["area"] != area:
            continue
        m = _months(x["acq"], start, end)
        resid = x["residual"] if x["residual"] is not None else 0
        rc = None
        if m is not None and x["method"] == "정액법" and x["life"]:
            base = x["cost"] - resid
            rc = min(int(round(base / x["life"] * m / 12)), max(base - x["beg_acc"], 0))
        elif m is not None and x["method"] == "정률법" and x["rate"]:
            rc = int(round((x["cost"] - x["beg_acc"]) * x["rate"] * m / 12))
        rows.append({**x, "months": m, "recalc": rc, "diff": None if rc is None else x["book"] - rc})
    key = "amortization" if area == "H" else "depreciation"
    tb = _tb_sum(ctx, key)
    return {"rows": rows, "source": a["source"], "tb_expense": tb, "book_sum": sum(r["book"] for r in rows),
            "recalc_sum": sum(r["recalc"] for r in rows) if rows and all(r["recalc"] is not None for r in rows) else None}


def _sheet_depr(b, ctx: dict, area: str) -> None:
    dep = depreciation(ctx, area)
    dc = defs()["depreciation"]
    name = "상각 재계산" if area == "H" else "감가상각 재계산"
    ws, row = b.sheet(name, widths=[10, 20, 12, 16, 9, 10, 10, 14, 8, 16, 16, 16, 24])
    basis = (dc["basis_intangible"] if area == "H" else dc["basis_straight"] + " " + dc["basis_declining"]).strip()
    ws.cell(6, 1, "재계산 근거: " + basis).font = wp.font(size=9, color=wp.MUTED)
    ws.cell(6, 1).alignment = wp.Alignment(wrap_text=True, vertical="top")
    ws.merge_cells(start_row=6, start_column=1, end_row=6, end_column=13)
    ws.row_dimensions[6].height = 54
    row += 1
    what = "무형자산" if area == "H" else "유형자산"
    if not dep["rows"]:
        msg = (f"고정자산대장에 {what} 줄이 없습니다. " if dep["source"] else "받은자료에 고정자산대장이 없습니다. ") + \
              f"판독 필요: {what} 자산별 취득일 · 취득가액 · 내용연수 · 상각방법이 있는 명세를 받아 주십시오"
        b.put(ws, row, 1, msg, flag=True, wrap=True)
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=13)
        row += 2
        b.put(ws, row, 1, f"시산표 {'무형자산상각비' if area == 'H' else '감가상각비'}")
        b.put(ws, row, 12, dep["tb_expense"], fmt=wp.WON)
        return
    row = b.section(ws, row, f"자산별 당기 상각 재계산 ({dep['source']})")
    row = b.head(ws, row, ["자산번호", "자산명", "취득일", "취득가액", "내용연수", "상각방법", "상각률(정률법)", "기초 상각누계액",
                           "사용 월수", "잔존가치", "재계산 상각비", "장부(대장) 상각비", "차이(장부 − 재계산)"])
    first = row
    for x in dep["rows"]:
        key = x["no"] or x["name"]
        b.put(ws, row, 1, x["no"])
        b.put(ws, row, 2, x["name"], wrap=True)
        if x["acq"]:
            b.put(ws, row, 3, x["acq"].isoformat())
        else:
            ask(b, ws, row, 3, f"취득일: {key}", rule="date")
        b.put(ws, row, 4, x["cost"], fmt=wp.WON)
        if x["life"]:
            b.put(ws, row, 5, x["life"], fmt="0")
        else:
            ask(b, ws, row, 5, f"내용연수: {key}", rule="number", fmt="0")
        if x["method"]:
            b.put(ws, row, 6, x["method"])
        else:
            ask(b, ws, row, 6, f"상각방법: {key}", rule="required")
        if x["rate"]:
            b.put(ws, row, 7, x["rate"], fmt="0.000")
        elif x["method"] != "정액법":
            ask(b, ws, row, 7, f"상각률: {key}", rule="optional", fmt="0.000")
        else:
            b.put(ws, row, 7, None)
        b.put(ws, row, 8, x["beg_acc"], fmt=wp.WON)
        if x["months"] is not None:
            b.put(ws, row, 9, x["months"], fmt="0")
        else:
            ask(b, ws, row, 9, f"사용 월수: {key}", rule="number", fmt="0")
        if x["residual"] is not None:
            b.put(ws, row, 10, x["residual"], fmt=wp.WON)
        else:
            ask(b, ws, row, 10, f"잔존가치(비우면 0): {key}", rule="optional", fmt=wp.WON)
        resid = f'IF(J{row}="",0,J{row})'
        straight = f"MIN(ROUND((D{row}-{resid})/E{row}*I{row}/12,0),MAX(D{row}-{resid}-H{row},0))"
        declining = f"ROUND((D{row}-H{row})*G{row}*I{row}/12,0)"
        b.put(ws, row, 11, f'=IF(OR(E{row}="",I{row}="",F{row}=""),"",IF(F{row}="정액법",{straight},IF(AND(F{row}="정률법",G{row}<>""),{declining},"")))',
              fmt=wp.WON)
        b.put(ws, row, 12, x["book"], fmt=wp.WON)
        b.put(ws, row, 13, f'=IF(K{row}="","",L{row}-K{row})', fmt=wp.WON, flag=bool(x["diff"]))
        row += 1
    last = row - 1
    b.put(ws, row, 1, "합계", bold=True)
    for c in (4, 8, 12):
        b.put(ws, row, c, f"=SUM({L(c)}{first}:{L(c)}{last})", fmt=wp.WON, bold=True)
    b.put(ws, row, 11, f"=SUM(K{first}:K{last})", fmt=wp.WON, bold=True)
    b.put(ws, row, 13, f"=SUM(M{first}:M{last})", fmt=wp.WON, bold=True)
    tot = row
    b.verify(f"{b.no} 대장 상각비 합계", f"='{name}'!L{tot}", dep["book_sum"])
    b.verify(f"{b.no} 대장 취득가액 합계", f"='{name}'!D{tot}", sum(x["cost"] for x in dep["rows"]))
    row += 1
    b.put(ws, row, 1, "시산표 " + ("무형자산상각비" if area == "H" else "감가상각비"), wrap=True)
    b.put(ws, row, 12, dep["tb_expense"], fmt=wp.WON)
    b.put(ws, row, 13, f"=L{tot}-L{row}", fmt=wp.WON, flag=dep["book_sum"] != dep["tb_expense"])
    row += 2
    ask(b, ws, row, 1, f"{what} 상각 재계산 차이 검토 결과", rule="required")
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=13)
    row += 1
    ws.cell(row, 1, "사용 월수는 엔진이 취득일과 사업연도로 계산했다. 처분 · 손상 · 사용 중단 자산은 대장에 처분 열이 없어 반영하지 않았다. "
                    "해당하면 차이 검토 결과에 적어 주십시오").font = wp.font(size=9, color=wp.MUTED)


# ---------------------------------------------------------------- A5 부외부채
def _hint_words(d: Path) -> list[str]:
    e = common.fy_end(d)
    return [h.format(year=e.year, month=e.month, month2=f"{e.month:02d}") for h in defs()["unrecorded"]["period_hints"]]


def _payable_by_party(d: Path) -> dict:
    out: dict[str, int] = {}
    for area in ("AA",):
        for p, v in _party_ends(d, area)["rows"].items():
            out[p] = out.get(p, 0) + v
    for rel in _excel(d, "계정명세서"):
        for sheet, c, rows, _, _ in reader._tables(d / rel, [["party"], ["ar_total"]], []):
            if "미지급" not in sheet:
                continue
            for r in rows:
                p, v = reader._cell(r, c["party"]), reader._num(reader._cell(r, c["ar_total"]))
                if p not in (None, "") and v is not None and not reader._is_total_row(r):
                    out[str(p).strip()] = out.get(str(p).strip(), 0) + abs(reader._int(v))
                    common.note_read(rel)
    return out


def post_window(ctx: dict) -> dict:
    """결산일 다음 기간(unrecorded.window_days 안)의 기말 후 분개장 전표. 4000AA 부외부채 검토와 4000CL 기말 후 출금 검토가 같이 쓴다.
    {"vouchers", "window", "period": (첫날, 끝날), "post_files"}"""
    end = common.fy_end(ctx["d"])
    win = defs()["unrecorded"]["window_days"]
    j = _journals(ctx)
    post = [x for x in j["post"] if x.date <= end + timedelta(days=win)]
    return {"vouchers": common.vouchers(post), "window": win, "period": (end + timedelta(days=1), end + timedelta(days=win)),
            "post_files": sorted({x.file for x in j["post"]})}


def unrecorded(ctx: dict) -> dict:
    """결산일 다음 기간(window_days 안) 지급 전표 가운데 비용 · 자산 계정으로 간 것. 명백히 사소한 금액 이상만."""
    d = ctx["d"]
    trivial = ctx["mat"].get("trivial") or 0
    hints = _hint_words(d)
    pay = _payable_by_party(d)
    pw = post_window(ctx)
    out = []
    for v in pw["vouchers"]:
        paid = sum(x.cr - x.dr for x in v.lines if in_group(x.code, x.name, "cash"))
        if paid <= 0.5:
            continue
        hits = [x for x in v.lines if x.dr and (in_group(x.code, x.name, "expense") or in_group(x.code, x.name, "asset"))
                and not in_group(x.code, x.name, "cash")]
        if not hits:
            continue
        amt = sum(x.dr for x in hits)
        if amt < trivial:
            continue
        memo = v.memo
        hint = next((h for h in hints if h in memo), None)
        party = v.parties[0] if v.parties else None
        out.append({"date": v.date, "voucher": v.no, "party": party, "accounts": ", ".join(dict.fromkeys(x.name or str(x.code) for x in hits)),
                    "amount": reader._int(amt), "paid": reader._int(paid), "memo": memo,
                    "hint": f"적요에 당기 표시('{hint}')" if hint else "", "payable": pay.get(party) if party else None})
    return {"rows": out, "window": pw["window"], "trivial": trivial, "post_files": pw["post_files"], "period": pw["period"]}


def _sheet_unrecorded(b, ctx: dict) -> None:
    u = unrecorded(ctx)
    ws, row = b.sheet("부외부채 검토", widths=[12, 14, 14, 18, 16, 16, 34, 22, 16, 14, 14, 26])
    a, z = u["period"]
    ws.cell(6, 1, f"결산일 다음 기간({a.isoformat()} ~ {z.isoformat()}) 분개장의 지급 전표 가운데 비용 · 자산 계정으로 간 것, "
                  f"금액 {won(u['trivial'])} 이상. 귀속 기간 · 부외부채 여부는 증빙을 보고 회계사가 정합니다").font = wp.font(size=9, color=wp.MUTED)
    if not u["post_files"]:
        b.put(ws, row, 1, "기말 후 분개장이 받은자료에 없어 부외부채 검토 대상을 뽑지 못했습니다. 판독 필요: 결산일 다음 1~2개월 분개장을 받아 주십시오",
              flag=True, wrap=True)
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=12)
        row += 2
        ask(b, ws, row, 1, "부외부채 검토 결과", rule="required")
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=12)
        return
    row = b.section(ws, row, f"부외부채 검토 후보 {len(u['rows'])}건 ({', '.join(u['post_files'])})")
    row = b.head(ws, row, ["지급일", "전표번호", "거래처", "차변 계정", "금액(비용 · 자산)", "지급액", "적요", "엔진 단서",
                           "기말 미지급 잔액(명세서)", "증빙일", "귀속 기간", "부외부채 여부 · 처리"])
    first = row
    for x in u["rows"]:
        key = f"{x['date'].isoformat()} {x['voucher']}"
        b.put(ws, row, 1, x["date"].isoformat())
        b.put(ws, row, 2, x["voucher"])
        b.put(ws, row, 3, x["party"])
        b.put(ws, row, 4, x["accounts"], wrap=True)
        b.put(ws, row, 5, x["amount"], fmt=wp.WON)
        b.put(ws, row, 6, x["paid"], fmt=wp.WON)
        b.put(ws, row, 7, x["memo"], wrap=True)
        b.put(ws, row, 8, x["hint"], wrap=True, flag=bool(x["hint"]))
        b.put(ws, row, 9, x["payable"] if x["payable"] is not None else "명세서에 없음", fmt=wp.WON)
        ask(b, ws, row, 10, f"증빙일: {key}", rule="date")
        ask(b, ws, row, 11, f"귀속 기간: {key}", rule="required")
        ask(b, ws, row, 12, f"부외부채 여부: {key}", rule="required")
        row += 1
    if u["rows"]:
        b.put(ws, row, 1, "합계", bold=True)
        b.put(ws, row, 5, f"=SUM(E{first}:E{row - 1})", fmt=wp.WON, bold=True)
        b.verify("4000AA 부외부채 후보 금액 합계", f"='부외부채 검토'!E{row}", sum(x["amount"] for x in u["rows"]))
    else:
        b.put(ws, row, 1, "조건에 맞는 지급 전표가 없습니다", color=wp.MUTED)
    row += 2
    ws.cell(row, 1, "귀속 기간은 당기 · 차기, 부외부채 여부는 예(8100A 에 올림) · 아니오 · 해당 없음 으로 적어 주십시오. "
                    "엔진 단서는 적요 글자만 본 것이다").font = wp.font(size=9, color=wp.MUTED)
    row += 2
    ask(b, ws, row, 1, "부외부채 검토 결과", rule="required")
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=12)


# ---------------------------------------------------------------- A6 재고실사
def inventory(ctx: dict) -> dict:
    """재고 품목 명세(계정명세서 재고 시트 또는 재고 명세 · 실사표). {"rows", "source", "tb", "total"}"""
    d = ctx["d"]
    ic = defs()["inventory"]
    tb = common.reader._int(sum(r["disp"] for r in ctx["tb"] if r["area"] == "E" and not r["pl"]))
    for kind, keys in (("계정명세서", ic["sheets"]), ("재고 명세·실사표", None)):
        for rel in _excel(d, kind):
            for t in find_tables(d / rel, ic["columns"], ["item", "qty"], keys):
                c = t["col"]
                rows = []
                for r in t["rows"]:
                    if reader._is_total_row(r):
                        continue
                    qty = reader._num(reader._cell(r, c["qty"]))
                    name = reader._cell(r, c["item"])
                    if qty is None or name in (None, ""):
                        continue
                    price = reader._num(reader._cell(r, c.get("price")))
                    amt = reader._num(reader._cell(r, c.get("amount")))
                    loc = str(reader._cell(r, c.get("location")) or "").strip()
                    rows.append({"code": str(reader._cell(r, c.get("item_code")) or "").strip(), "item": str(name).strip(),
                                 "kind": str(reader._cell(r, c.get("kind")) or "").strip(), "location": loc,
                                 "unit": str(reader._cell(r, c.get("unit")) or "").strip(), "qty": reader._int(qty),
                                 "price": reader._int(price) if price is not None else None,
                                 "amount": reader._int(amt) if amt is not None else (reader._int(qty * price) if price is not None else None),
                                 "outside": any(k in loc for k in ic["outside_keys"])})
                if rows:
                    common.note_read(rel)
                    total = sum(r["amount"] or 0 for r in rows)
                    return {"rows": rows, "source": f"{rel} '{t['sheet']}' 시트", "tb": tb, "total": total, "diff": total - tb}
    return {"rows": [], "source": None, "tb": tb, "total": None, "diff": None}


def _sheet_inventory(b, ctx: dict) -> None:
    inv = inventory(ctx)
    ws, row = b.sheet("재고실사", widths=[10, 18, 10, 24, 6, 12, 12, 16, 12, 12, 16, 12, 26])
    ws.cell(6, 1, "장부 수량 · 금액은 재고 명세에서 엔진이 읽었다. 실사 수량 · 입회 사항 · 차이 처리는 회계사 기입란이다").font = wp.font(size=9, color=wp.MUTED)
    row = b.section(ws, row, "재고실사 입회")
    for lab, rule in (("입회일", "date"), ("입회자", "required"), ("실사 기준일과 기말까지 수불 조정", "optional")):
        ws.cell(row, 1, lab).font = wp.font(color=wp.MUTED)
        ask(b, ws, row, 3, lab, rule=rule, fmt="yyyy-mm-dd" if rule == "date" else None)
        ws.merge_cells(start_row=row, start_column=3, end_row=row, end_column=6)
        row += 1
    row += 1
    if not inv["rows"]:
        b.put(ws, row, 1, "재고 품목 명세를 찾지 못했습니다. 판독 필요: 품목 · 보관장소 · 수량 · 단가 · 금액이 있는 기말 재고 명세를 받아 주십시오",
              flag=True, wrap=True)
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=13)
        row += 2
        b.put(ws, row, 1, "시산표 재고자산")
        b.put(ws, row, 8, inv["tb"], fmt=wp.WON)
        return
    row = b.section(ws, row, f"품목별 장부 · 실사 ({inv['source']})")
    row = b.head(ws, row, ["품목코드", "품목명", "구분", "보관장소", "단위", "장부 수량", "단가", "장부 금액", "실사 수량", "차이 수량",
                           "차이 금액", "타처보관", "차이 사유 · 처리"])
    first = row
    for x in inv["rows"]:
        key = x["code"] or x["item"]
        b.put(ws, row, 1, x["code"])
        b.put(ws, row, 2, x["item"], wrap=True)
        b.put(ws, row, 3, x["kind"])
        b.put(ws, row, 4, x["location"], wrap=True, flag=x["outside"])
        b.put(ws, row, 5, x["unit"])
        b.put(ws, row, 6, x["qty"], fmt="#,##0")
        b.put(ws, row, 7, x["price"], fmt=wp.WON)
        b.put(ws, row, 8, x["amount"], fmt=wp.WON)
        ask(b, ws, row, 9, f"실사 수량: {key}", rule="number", fmt="#,##0")
        b.put(ws, row, 10, f'=IF(I{row}="","",I{row}-F{row})', fmt="#,##0")
        b.put(ws, row, 11, f'=IF(OR(J{row}="",G{row}=""),"",J{row}*G{row})', fmt=wp.WON)
        b.put(ws, row, 12, "타처보관" if x["outside"] else "", flag=x["outside"])
        ask(b, ws, row, 13, f"차이 사유: {key}", rule="optional")
        row += 1
    last = row - 1
    b.put(ws, row, 1, "합계", bold=True)
    b.put(ws, row, 8, f"=SUM(H{first}:H{last})", fmt=wp.WON, bold=True)
    b.put(ws, row, 11, f"=SUM(K{first}:K{last})", fmt=wp.WON, bold=True)
    tot = row
    b.verify("4000E 재고 명세 장부 금액 합계", f"='재고실사'!H{tot}", inv["total"])
    row += 1
    b.put(ws, row, 1, "시산표 재고자산")
    b.put(ws, row, 8, inv["tb"], fmt=wp.WON)
    row += 1
    b.put(ws, row, 1, "명세 − 시산표(재고 품목 대사)", wrap=True)
    b.put(ws, row, 8, f"=H{tot}-H{row - 1}", fmt=wp.WON, flag=bool(inv["diff"]))
    b.verify("4000E 재고 명세 − 시산표 재고자산", f"='재고실사'!H{row}", inv["diff"])
    row += 2
    outs = [x for x in inv["rows"] if x["outside"]]
    if outs:
        ws.cell(row, 1, f"타처보관 품목 {len(outs)}개(" + ", ".join(f"{x['item']} · {x['location']}" for x in outs) +
                "). 보관처 조회서(3320) 또는 직접 입회로 확인해 주십시오").font = wp.font(size=9, color=wp.RED)
        row += 1
    ask(b, ws, row, 1, "재고 품목 대사 차이와 실사 차이 처리", rule="required")
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=13)


# ---------------------------------------------------------------- 리드에 붙이기
def add_sheets(b, code: str, ctx: dict) -> None:
    if code in ("C", "AA", "BBDD"):
        _sheet_party(b, ctx, code)
    if code == "BBDD":
        _sheet_loans(b, ctx)
        _sheet_interest(b, ctx)
    if code in ("G", "H"):
        _sheet_depr(b, ctx, code)
    if code == "AA":
        _sheet_unrecorded(b, ctx)
    if code == "E":
        _sheet_inventory(b, ctx)


# ---------------------------------------------------------------- A7 3200 소송 조회 대장
LIT_COLS = ["사건번호", "법원", "상대방", "회사 지위(원고 · 피고)", "소송가액", "진행 상황", "승패전망", "충당부채 · 주석 공시 여부", "근거(조회 회신)"]


def litigation_facts(d: Path) -> dict:
    """변호사 조회 회신 받은자료와 그 판독 사실, 다른 받은자료의 '소송' 판독 사실. 숫자를 만들지 않는다."""
    p = Path(d) / "_색인" / "문서목록.json"
    files = json.loads(p.read_text(encoding="utf-8")).get("files", []) if p.exists() else []
    replies, other = [], []
    for f in files:
        if f.get("role") != "received":
            continue
        tag = "엔진 판독" if f.get("kind_basis") == "엔진" else ("AI 판독, 회계사 확인 끝" if f.get("confirmed") and f.get("kind_basis") == "사람"
                                                             else "AI 판독, 확인 전")
        facts = [f"{x['text']}" + (f" {x['source_page']}" if x.get("source_page") else "") for x in f.get("facts") or []]
        if f.get("kind") == "변호사 조회 회신":
            replies.append({"path": f["path"], "facts": facts, "tag": tag})
        else:
            other += [f"{t} ({f['path']}, {tag})" for t in facts if any(k in t for k in ("소송", "소장", "피소", "계류", "분쟁"))]
    return {"replies": replies, "other": other}


def litigation_sheet(b, d: Path) -> None:
    """3200 부속 「소송 조회 대장」. 사건 줄은 회계사 기입, 회신 판독 사실은 위에 옮긴다(AI 판독은 확인 전 표시)."""
    lf = litigation_facts(d)
    ws, row = b.sheet("소송 조회 대장", widths=[16, 14, 18, 14, 16, 18, 14, 18, 26])
    ws.cell(6, 1, "감사기준서 501 문단 9~12(소송 · 배상청구): 경영진 질문, 의사록, 법률비용 계정 검토, 변호사 조회로 확인한다. "
                  "승패전망 · 충당부채 인식 · 주석 공시 여부는 회계사가 정합니다").font = wp.font(size=9, color=wp.MUTED)
    row = b.section(ws, row, "변호사 조회 회신 (받은자료 조회회신 폴더)")
    if not lf["replies"]:
        ws.cell(row, 1, "받은자료에 변호사 조회 회신이 없습니다. 3320 에서 변호사 조회서를 보내고 회신을 조회회신 폴더에 넣어 주십시오").font = wp.font(size=9, color=wp.RED)
        row += 1
    for x in lf["replies"]:
        ws.cell(row, 1, f"{x['path']} ({x['tag']})").font = wp.font(size=9, bold=True)
        row += 1
        for t in x["facts"] or ["판독 사실 없음(감사-맥락색인 으로 판독해 주십시오)"]:
            ws.cell(row, 2, t).font = wp.font(size=9, color=wp.RED if "확인 전" in x["tag"] else wp.MUTED)
            row += 1
    for t in lf["other"]:
        ws.cell(row, 1, "다른 받은자료: " + t).font = wp.font(size=9, color=wp.MUTED)
        row += 1
    row += 1
    row = b.section(ws, row, "확인")
    ws.cell(row, 1, "확인 방법").font = wp.font(color=wp.MUTED)
    ask(b, ws, row, 2, "소송 확인 방법(경영진 질문 · 의사록 · 법률비용 계정 · 변호사 조회)", rule="required")
    ws.merge_cells(start_row=row, start_column=2, end_row=row, end_column=9)
    row += 1
    ws.cell(row, 1, "계류 · 예상 소송").font = wp.font(color=wp.MUTED)
    ask(b, ws, row, 2, "계류 중이거나 예상되는 소송 · 배상청구가 있음", rule="yesno")
    ws.cell(row, 3, "예 · 아니오 · 해당 없음. 예이면 아래 대장에 사건마다 적어 주십시오").font = wp.font(size=9, color=wp.MUTED)
    row += 2
    row = b.section(ws, row, "소송 조회 대장")
    row = b.head(ws, row, LIT_COLS)
    for i in range(1, max(5, len(lf["replies"]) + 2) + 1):
        for j, c in enumerate(LIT_COLS, 1):
            ask(b, ws, row, j, f"소송 {i} {c}", rule="optional", fmt=wp.WON if c == "소송가액" else None)
        row += 1
    ws.cell(row + 1, 1, "소송가액은 원 단위. 승패전망은 변호사 회신 문구를 그대로 옮기고, 충당부채 인식(일반기업회계기준 제14장) · "
                        "주석 공시 여부는 회계사가 적는다").font = wp.font(size=9, color=wp.MUTED)
