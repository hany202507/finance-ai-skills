"""4000 조서 절차 시트 둘째 묶음(2026-10-12). 예시 조서를 읽은 결과가 권한 구성 가운데 일곱 가지다.
시트 이름 앞 번호(.01 …)는 lead.make 가 다 만든 뒤 붙인다(skeleton.finish). 여기서는 번호 없는 이름으로 만든다.

  4000P            Cut-off(결산일 앞뒤 기간의 매출 전표, 금액 상위), 진행기준 매출(progress.py, 진행률 명세가 있을 때)
  4000R            월별 변동(세목 × 달, 월평균의 배수와 수행중요성을 함께 넘은 달의 사유). 표본은 vouch.py 가 만든다
  4000CL           기말 후 출금 검토 · 법률 수수료 거래처 대사(subsequent.py 가 그린다. 계산 subsequent() 은 여기 있다)
  4000FF           충당부채 변동(계정별 기초 · 전입 · 사용 · 환입 · 기말, 사용 건 금액 상위)
  4000GG           자본변동표(계정별 기초 · 증자 · 배당 · 당기순이익 · 그 밖의 변동 · 기말)와 등기 대사
  4000G · 4000H    변동내역(계정별 전기말 · 취득 · 처분 · 상각 · 그 밖의 증감 · 당기말)
  4000C            손실충당금 검토(연령 구간별 합계, 완전성, 적립율과 재계산), Roll-Rate(rollrate.py, 기준일 연령표 둘 이상)
                   IPE 대손충당금 연령표(ipe.py, 회사가 만든 대손충당금 연령표가 있을 때, 2026-10-26)
  4000A · C · D · AA · CC · BBDD  외화환산 재계산(분석.json fx 의 그 영역 항목, 2026-10-20). 항목이 없으면 만들지 않는다

숫자는 받은자료(분개장 · 연령분석표 · 고정자산대장 · 계정명세서)와 시산표에서 엔진이 읽은 것만 쓴다. 뽑는 범위와 표시 기준은
definitions/recalc.yaml 에 있다. 귀속 판단 · 적립율 · 기준 금액 · 사유 · 증빙 확인 · 결론은 회계사 기입란이다. 엔진은 판단하지 않는다.
원자료 전체를 싣지 않는다. 요약과 금액 상위 줄만 싣는다. 대사는 차이 금액 수식이고 엔진이 계산한 값은 검산에 넣는다.
자료가 없어 만들 수 없는 시트는 만들지 않고 그 까닭을 돌려준다. lead 가 Lead 의 절차 목록 아래에 적는다.

  add_sheets(b, code, ctx, area) -> [안내 글]   lead.make 가 부른다. area 는 {code, rows, lines, lead_rows}
  cutoff(ctx) · monthly(ctx, code) · subsequent(ctx, threshold) · provisions(ctx) · equity(ctx) · rollforward(ctx, code) · aging(ctx)
                                                시트와 시험이 같이 쓰는 엔진 계산. 만들 수 없으면 None
"""
from __future__ import annotations

import re
from datetime import timedelta
from pathlib import Path

from openpyxl.utils import get_column_letter as L

from .. import figures, folder, reader, wp
from . import common, recalc, sales, skeleton, vouch
from .common import ask, won

CUTOFF, MONTHLY, SUBSEQUENT, PROVISION, EQUITY, ROLL, ALLOWANCE = (
    "Cut-off", "월별 변동", "기말 후 출금 검토", "충당부채 변동", "자본변동표", "변동내역", "손실충당금 검토")
BEFORE, AFTER = "결산일 전", "결산일 후"
THRESHOLD = "기준 금액(기말 후 출금)"
EQUITY_TYPES = ("증자", "배당", "당기순이익", "그 밖의 변동")
MUTED = dict(size=9, color=wp.MUTED)


def _note(ws, row: int, text: str, color: str = wp.MUTED) -> int:
    ws.cell(row, 1, text).font = wp.font(size=9, color=color)
    return row + 1


def _basis(ws, text: str, last_col: int) -> None:
    """6행의 근거 문구. 감사절차 한 줄은 skeleton.finish 가 그 위에 붙인다."""
    ws.cell(6, 1, text).font = wp.font(**MUTED)
    ws.cell(6, 1).alignment = wp.Alignment(wrap_text=True, vertical="top")
    ws.merge_cells(start_row=6, start_column=1, end_row=6, end_column=last_col)


def lead_sum(area: dict, pick=None, col: str = "B") -> tuple[str, int]:
    """Lead 리드시트의 표시과목 줄을 더하는 수식 조각과 그 엔진 값. col B 는 당기(회사제시)다. pick(표시과목) 이 참인 줄만 더한다."""
    ref = wp.sheet_ref(skeleton.LEAD)
    lines = [x for x in area["lines"] if pick is None or pick(x)]
    expr = "+".join(f"{ref}{col}{area['lead_rows'][x]}" for x in lines) or "0"
    return expr, reader._int(sum(r["disp"] for r in area["rows"] if r["line"] in lines))


def _is_pl_line(area: dict):
    pl = {line: all(r["pl"] for r in area["rows"] if r["line"] == line) for line in area["lines"]}
    return lambda line: pl[line]


def _acct_key(code, name) -> str:
    return str(code) if code not in (None, "") else reader._norm(name)


def _vouchers_by_line(lines: list) -> dict:
    """분개 행 → 그 행이 든 전표. 상대계정을 찾는 데 쓴다."""
    out = {}
    for v in common.vouchers(lines):
        for x in v.lines:
            out[id(x)] = v
    return out


def _names(lines) -> str:
    return ", ".join(dict.fromkeys(x.name or str(x.code) for x in lines))


# ---------------------------------------------------------------- 4000P Cut-off
def cutoff(ctx: dict) -> dict | None:
    """결산일을 넣어 앞 days 일과 결산일 다음 날부터 days 일의 매출 전표(매출 계정 대변 − 차변). 구간마다 금액(절대값) 상위 top 건.
    당기 분개장에 매출 계정 행이 없으면 None. 기말 후 분개장이 없으면 after 가 None 이다."""
    d = ctx["d"]
    st = recalc.defs()["cutoff"]
    days, top = int(st["days"]), int(st["top"])
    end = common.fy_end(d)
    j = recalc._journals(ctx)
    g = sales._groups()["revenue"]
    cur = j["cur"]
    if not any(sales._is(x, g) for x in cur):
        return None

    adv = common.load_def("jet.yaml")["accounts"]["advances"]

    def part(lines, lo, hi, year):
        vs, tr_n, tr_sum = [], 0, 0
        for v in common.vouchers([x for x in lines if lo <= x.date <= hi]):
            rev = [x for x in v.lines if sales._is(x, g)]
            amt = reader._int(sum(x.cr - x.dr for x in rev))
            if not rev or not amt:
                continue
            if is_advance_transfer(v, g, adv):
                tr_n, tr_sum = tr_n + 1, tr_sum + amt
                continue
            vs.append({"date": v.date, "voucher": v.no, "memo": " / ".join(dict.fromkeys(x.memo for x in rev if x.memo)),
                       "party": ", ".join(dict.fromkeys(x.party for x in rev if x.party)), "amount": amt, "year": year})
        big = sorted(vs, key=lambda r: (-abs(r["amount"]), r["date"], r["voucher"]))[:top]
        return {"lo": lo, "hi": hi, "count": len(vs), "total": reader._int(sum(r["amount"] for r in vs)),
                "rows": sorted(big, key=lambda r: (r["date"], r["voucher"])),
                "transfers": {"count": tr_n, "total": reader._int(tr_sum)}}

    before = part(cur, end - timedelta(days=days - 1), end, end.year)
    post = j["post"]
    after = part(post, end + timedelta(days=1), end + timedelta(days=days), end.year + 1) if post else None
    return {"days": days, "top": top, "end": end, "before": before, "after": after,
            "reversals": _reversals(cur, post, g, end, adv) if post else None}


def is_advance_transfer(v, g: dict, adv: dict) -> bool:
    """매출 계정과 선수금(선수수익 · 계약부채)만 오가는 전표인가. 월말 미경과매출 역분개 · 이연 · 인식 대체라 결산일 앞뒤 기간귀속 검사와
    기말 후 매출 취소 표의 대상이 아니다(표본 시트의 순액 묶음과 같은 기준, sales.advance_transfers). 2026-11-10 한 감사 건:
    결산일 앞 5일 상위 10건이 모두 이 전표였고 「기말 후 매출 취소」 합계 (금액)원이 1월 역분개였다. 선수금 이연 자체는
    4000CC 선수금 재계산에서 본다."""
    rev = [x for x in v.lines if sales._is(x, g)]
    rest = [x for x in v.lines if not sales._is(x, g)]
    return bool(rev) and bool(rest) and all(sales._is(x, adv) for x in rest)


def _reversals(cur, post, g, end, adv: dict | None = None) -> list[dict]:
    """기말 후 분개장 전체의 매출 취소 전표(매출 계정 차변 − 대변 > 0)와, 같은 거래처 · 같은 금액의 당기 매출 전표(가장 늦은 것)를 잇는다(2026-10-16).
    결산일 앞 days 일 구간 밖의 원 매출도 이 표로 보인다. 같은 거래처 · 같은 금액이 아니면 원 전표는 비운다.
    매출 ↔ 선수금 대체 전표(is_advance_transfer)는 취소가 아니라 뺀다(2026-11-10)."""
    adv = adv or common.load_def("jet.yaml")["accounts"]["advances"]

    def sales_vouchers(lines):
        out = []
        for v in common.vouchers(lines):
            if is_advance_transfer(v, g, adv):
                continue
            rev = [x for x in v.lines if sales._is(x, g)]
            amt = reader._int(sum(x.cr - x.dr for x in rev))
            if rev and amt:
                out.append({"date": v.date, "voucher": v.no, "party": ", ".join(dict.fromkeys(x.party for x in rev if x.party)),
                            "memo": " / ".join(dict.fromkeys(x.memo for x in rev if x.memo)), "amount": amt})
        return out

    origs = sorted((r for r in sales_vouchers([x for x in cur if x.date <= end]) if r["amount"] > 0), key=lambda r: (r["date"], r["voucher"]))
    used, rows = set(), []
    for c in sorted((r for r in sales_vouchers([x for x in post if x.date > end]) if r["amount"] < 0), key=lambda r: (r["date"], r["voucher"])):
        o = next((r for r in reversed(origs) if c["party"] and r["party"] == c["party"] and r["amount"] == -c["amount"]
                  and (r["date"], r["voucher"]) not in used), None)
        if o:
            used.add((o["date"], o["voucher"]))
        rows.append({"cancel": c, "orig": o})
    return rows


def _sheet_cutoff(b, ctx: dict, area: dict) -> str | None:
    c = cutoff(ctx)
    if c is None:
        return f"「{CUTOFF}」: 매출 계정 행이 있는 당기 분개장을 받으면 만듭니다"
    ws, row = b.sheet(CUTOFF, widths=[12, 14, 18, 30, 18, 18, 12, 12, 30, 10])
    _basis(ws, "매출 계정의 대변 − 차변을 전표 단위로 모았다. 회사 귀속 연도는 전표 일자가 든 사업연도다. "
               "감사인 귀속 연도와 증빙, 인도일은 감사인이 적는다", 10)
    row = b.section(ws, row, "기준")
    row = b.head(ws, row, ["구분", "모집단 전표 수", "모집단 금액", "기간", "조서에 실은 전표 수"])
    parts = [(BEFORE, c["before"]), (AFTER, c["after"])]
    for kind, p in parts:
        b.put(ws, row, 1, kind, bold=True)
        if p is None:
            b.put(ws, row, 2, None)
            b.put(ws, row, 3, None)
            b.put(ws, row, 4, "기말 후 분개장 없음", color=wp.MUTED)
            b.put(ws, row, 5, None)
        else:
            b.put(ws, row, 2, p["count"], fmt="#,##0")
            b.put(ws, row, 3, p["total"], fmt=wp.WON)
            b.put(ws, row, 4, f"{p['lo'].isoformat()} ~ {p['hi'].isoformat()}")
            b.put(ws, row, 5, len(p["rows"]), fmt="#,##0")
        row += 1
    for kind, p in parts:
        t = (p or {}).get("transfers") or {}
        if t.get("count"):
            b.put(ws, row, 1, f"{kind} 선수금 대체(뺌)", color=wp.MUTED)
            b.put(ws, row, 2, t["count"], fmt="#,##0")
            b.put(ws, row, 3, t["total"], fmt=wp.WON)
            b.put(ws, row, 4, "매출 ↔ 선수금만 오가는 전표(미경과매출 역분개 · 이연 · 인식). 기간귀속 표본이 아니라 4000CC 선수금 재계산과 .02 표본의 순액 묶음에서 본다",
                  color=wp.MUTED, wrap=True)
            ws.merge_cells(start_row=row, start_column=4, end_row=row, end_column=5)
            row += 1
    row = _note(ws, row, f"결산일 {c['end'].isoformat()}. 결산일을 넣어 앞 {c['days']}일과 결산일 다음 날부터 {c['days']}일을 본다. "
                         f"구간마다 금액(절대값) 상위 {c['top']}건을 싣는다. 값은 definitions/recalc.yaml 의 cutoff 에 있다")
    row += 1
    row = b.section(ws, row, "결산일 앞뒤 매출 전표")
    row = b.head(ws, row, ["구분", "일자", "전표번호", "적요", "거래처", "금액", "회사 귀속 연도", "감사인 귀속 연도", "증빙과 인도일", "판정"])
    first = row
    for kind, p in parts:
        for r in (p or {}).get("rows", []):
            key = f"{r['date'].isoformat()} {r['voucher']}"
            b.put(ws, row, 1, kind)
            b.put(ws, row, 2, r["date"].isoformat())
            b.put(ws, row, 3, r["voucher"])
            b.put(ws, row, 4, common.short(r["memo"], 60), wrap=True)
            b.put(ws, row, 5, r["party"], wrap=True)
            b.put(ws, row, 6, r["amount"], fmt=wp.WON, flag=r["amount"] < 0)
            b.put(ws, row, 7, r["year"], fmt="0")
            ask(b, ws, row, 8, f"감사인 귀속 연도: {key}", rule="number", fmt="0", wrap=False)
            ask(b, ws, row, 9, f"증빙과 인도일: {key}", rule="required")
            b.put(ws, row, 10, f'=IF(H{row}="","",IF(H{row}=G{row},"일치","불일치"))')
            row += 1
    last = row - 1
    if last < first:
        b.put(ws, row, 1, "기준 기간에 매출 전표가 없습니다", color=wp.MUTED)
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=10)
        row += 1
    else:
        ref = wp.sheet_ref(CUTOFF)
        for kind, p in parts:
            if p is None:
                continue
            b.put(ws, row, 1, f"{kind} 합계", bold=True)
            b.put(ws, row, 6, f'=SUMIF(A{first}:A{last},"{kind}",F{first}:F{last})', fmt=wp.WON, bold=True)
            b.verify(f"4000P Cut-off {kind} 실은 전표 금액 합", f"={ref}F{row}", sum(r["amount"] for r in p["rows"]))
            row += 1
    row += 1
    row = _cutoff_reversals(b, ws, row, c)
    for t in ("판정은 회사 귀속 연도와 감사인 귀속 연도가 같으면 「일치」, 다르면 「불일치」 로 보입니다. 감사인 귀속 연도를 적기 전에는 빈칸입니다",
              "금액이 음수인 전표(매출 취소 · 환입)는 붉게 보입니다. 불일치이면 금액과 처리를 결론에 적고 8100A 에 올려 주십시오"):
        row = _note(ws, row, t)
    return None


def _cutoff_reversals(b, ws, row: int, c: dict) -> int:
    """기말 후 매출 취소와 원 매출 전표 표(2026-10-16 시연: 12-18 · 12-22 허위 매출이 결산일 앞 5일 구간 밖이라 Cut-off 표에 없었다)."""
    rv = c.get("reversals")
    if rv is None:
        return row
    row = b.section(ws, row, "기말 후 매출 취소와 원 매출 전표")
    if not rv:
        b.put(ws, row, 1, "기말 후 분개장에 매출 취소 전표가 없습니다", color=wp.MUTED)
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=10)
        return row + 2
    row = b.head(ws, row, ["취소 일자", "취소 전표", "거래처", "취소 금액", "원 매출 일자", "원 전표번호", "원 매출 금액", "Cut-off 표에 있음", "취소 사유와 증빙", "판정"])
    lo = c["before"]["lo"]
    first = row
    for r in rv:
        x, o = r["cancel"], r["orig"]
        key = f"{x['date'].isoformat()} {x['voucher']}"
        b.put(ws, row, 1, x["date"].isoformat())
        b.put(ws, row, 2, x["voucher"])
        b.put(ws, row, 3, x["party"], wrap=True)
        b.put(ws, row, 4, x["amount"], fmt=wp.WON, flag=True)
        if o:
            b.put(ws, row, 5, o["date"].isoformat())
            b.put(ws, row, 6, o["voucher"])
            b.put(ws, row, 7, o["amount"], fmt=wp.WON)
            b.put(ws, row, 8, "예" if o["date"] >= lo else "아니오", flag=o["date"] < lo)
        else:
            b.put(ws, row, 5, "같은 거래처 · 같은 금액의 당기 매출 없음", color=wp.MUTED)
            ws.merge_cells(start_row=row, start_column=5, end_row=row, end_column=8)
        ask(b, ws, row, 9, f"취소 사유와 증빙: {key}", rule="required")
        ask(b, ws, row, 10, f"취소 판정: {key}", rule="required", wrap=False)
        row += 1
    b.put(ws, row, 1, "취소 금액 합계", bold=True)
    b.put(ws, row, 4, f"=SUM(D{first}:D{row - 1})", fmt=wp.WON, bold=True)
    b.verify("4000P Cut-off 기말 후 매출 취소 합", f"={wp.sheet_ref(CUTOFF)}D{row}", sum(r["cancel"]["amount"] for r in rv))
    row += 1
    return _note(ws, row, "기말 후 분개장 전체에서 매출 계정 차변이 대변보다 큰 전표를 모아, 같은 거래처 · 같은 금액의 당기 매출 전표(가장 늦은 것)와 이었다. "
                          "원 매출이 당기 수익 인식 요건을 채웠는지(인도 · 검수 · 대금 회수)와 취소 사유를 보고 판정에 적어 주십시오. 「Cut-off 표에 있음」 이 아니오이면 결산일 앞 구간 밖의 매출이다") + 1


# ---------------------------------------------------------------- 4000R 월별 변동
def monthly(ctx: dict, code: str = "R") -> dict | None:
    """영역의 손익 세목 × 달 금액(표시 부호: 비용은 차변 − 대변). 달 금액이 그 세목 월평균의 multiple 배를 넘고 수행중요성도 넘으면 flags 에 든다.
    영역에 손익 계정이 없거나 당기 분개장이 없으면 None."""
    d = ctx["d"]
    accts = [r for r in ctx["tb"] if r["area"] == code and r["pl"]]
    if not accts:
        return None
    lines = vouch.area_lines(ctx, code)
    if not recalc._journals(ctx)["cur"]:
        return None
    per = folder.periods(common.case(d))
    months = sales._months(per["cur_start"], per["cur_end"])
    multiple = float(recalc.defs()["monthly"]["multiple"])
    pm = ctx["mat"]["performance"]
    by = {_acct_key(r["code"], r["name"]): r for r in accts}
    flows = {k: {m: 0.0 for m in months} for k in by}
    for x in lines:
        k = _acct_key(x.code, x.name)
        m = x.date.isoformat()[:7]
        if k in flows and m in flows[k]:
            flows[k][m] += by[k]["sign"] * (x.dr - x.cr)
    rows = []
    for k, r in by.items():
        vals = [reader._int(flows[k][m]) for m in months]
        total = reader._int(sum(vals))
        avg = total / len(months)
        flags = [i for i, v in enumerate(vals) if pm and avg and abs(v) > multiple * abs(avg) and abs(v) > pm]
        rows.append({"code": r["code"], "name": r["name"], "months": vals, "total": total, "avg": avg, "flags": flags, "tb": r["disp"]})
    return {"months": months, "rows": rows, "multiple": multiple, "pm": pm, "total": reader._int(sum(r["total"] for r in rows)),
            "tb": reader._int(sum(r["tb"] for r in rows))}


def _sheet_monthly(b, ctx: dict, area: dict) -> str | None:
    m = monthly(ctx, area["code"])
    if m is None:
        return f"「{MONTHLY}」: 이 영역의 손익 계정이 시산표에 있고 당기 분개장을 받으면 만듭니다"
    n = len(m["months"])
    c_tot = 3 + n                                   # 합계 열
    ws, row = b.sheet(MONTHLY, widths=[10, 22] + [14] * n + [16])
    _basis(ws, "당기 분개장에서 이 영역 손익 계정의 차변 − 대변을 세목과 달로 모았다. 급여 · 감가상각비처럼 다른 영역이 맡는 계정은 그 조서에서 본다. "
               f"달 금액이 그 세목 월평균의 {m['multiple']:g}배를 넘고 수행중요성({won(m['pm'])})도 넘으면 붉게 보인다", c_tot)
    ws.row_dimensions[6].height = 28
    row = b.section(ws, row, f"세목별 월별 금액 ({len(m['rows'])}개 세목)")
    row = b.head(ws, row, ["계정코드", "계정명"] + m["months"] + ["합계"])
    first = row
    top = skeleton.top_n(ctx["defs"])
    shown, rest = skeleton.top_rows(m["rows"], top, lambda r: r["total"], keep=lambda r: bool(r["flags"]))
    if rest:
        shown = shown + [{"code": "", "name": f"그 밖의 세목 ({len(rest)}개)", "months": [sum(r["months"][i] for r in rest) for i in range(n)],
                          "flags": []}]
    for r in shown:
        b.put(ws, row, 1, r["code"])
        b.put(ws, row, 2, r["name"])
        for i, v in enumerate(r["months"]):
            b.put(ws, row, 3 + i, v, fmt=wp.WON, flag=i in r["flags"])
        b.put(ws, row, c_tot, f"=SUM(C{row}:{L(c_tot - 1)}{row})", fmt=wp.WON)
        row += 1
    last = row - 1
    b.put(ws, row, 1, "합계", bold=True)
    b.put(ws, row, 2, "")
    for c in range(3, c_tot + 1):
        b.put(ws, row, c, f"=SUM({L(c)}{first}:{L(c)}{last})", fmt=wp.WON, bold=True)
    tot = row
    ref = wp.sheet_ref(MONTHLY)
    expr, lead_v = lead_sum(area, _is_pl_line(area))
    row += 1
    b.put(ws, row, 1, "Lead 당기(회사제시)")
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=2)
    b.put(ws, row, c_tot, f"={expr}", fmt=wp.WON)
    row += 1
    b.put(ws, row, 1, "차이(월별 합계 − Lead)")
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=2)
    b.put(ws, row, c_tot, f"={L(c_tot)}{tot}-{L(c_tot)}{row - 1}", fmt=wp.WON, flag=m["total"] != lead_v)
    b.verify(f"{b.no} 월별 변동 합계", f"={ref}{L(c_tot)}{tot}", m["total"])
    b.verify(f"{b.no} 월별 변동 합계 − Lead", f"={ref}{L(c_tot)}{row}", m["total"] - lead_v)
    row += 1
    if rest:
        row = _note(ws, row, f"세목 {len(m['rows'])}개 가운데 {len(shown) - 1}개(연 금액 상위 {top}개와 붉게 보인 달이 있는 세목)를 보이고 나머지 "
                             f"{len(rest)}개는 한 줄로 합쳤습니다. 합계와 검산은 전체 금액입니다")
    row += 1
    hits = [(r, i) for r in m["rows"] for i in r["flags"]]
    row = b.section(ws, row, f"월평균의 {m['multiple']:g}배와 수행중요성을 함께 넘은 달 ({len(hits)}건)")
    if not hits:
        row = _note(ws, row, "해당하는 달이 없습니다" if m["pm"] else "수행중요성이 없어 표시하지 못했습니다(2700A)")
    else:
        row = b.head(ws, row, ["계정코드", "계정명", "달", "금액", "세목 월평균", "사유"])
        for r, i in hits:
            b.put(ws, row, 1, r["code"])
            b.put(ws, row, 2, r["name"])
            b.put(ws, row, 3, m["months"][i])
            b.put(ws, row, 4, r["months"][i], fmt=wp.WON, flag=True)
            b.put(ws, row, 5, reader._int(round(r["avg"])), fmt=wp.WON)
            ask(b, ws, row, 6, f"사유: {r['name']} {m['months'][i]}", rule="required")
            ws.merge_cells(start_row=row, start_column=6, end_row=row, end_column=min(c_tot, 10))
            row += 1
    _note(ws, row + 1, "배수는 definitions/recalc.yaml 의 monthly.multiple 입니다. 사유는 전표와 증빙을 보고 감사인이 적습니다")
    return None


# ---------------------------------------------------------------- 4000CL 기말 후 출금 검토
def old_threshold(d: Path, no: str) -> float | None:
    """이미 있는 조서에 감사인이 적은 기준 금액. 다시 만들 때 이 값으로 목록을 뽑는다."""
    for (_, lab), v in common.old_inputs(d, no).items():
        if lab == THRESHOLD and isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0:
            return v
    return None


def default_threshold(ctx: dict) -> float | None:
    """기말 후 출금 검토의 기준 금액 기본값: definitions/recalc.yaml subsequent.threshold(2700B 로 감사 건마다 바꿈). 0 · 빈 값이면 수행중요성."""
    v = recalc.defs()["subsequent"].get("threshold")
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0 else ctx["mat"]["performance"]


def _sig(v) -> tuple:
    """전표 내용 열쇠(일자 · 줄마다 계정 · 차변 · 대변). 판 비교에 쓴다. 전표번호가 바뀌어도 같은 전표로 본다."""
    return (v.date, tuple(sorted((str(x.code or reader._norm(x.name)), reader._int(x.dr), reader._int(x.cr)) for x in v.lines)))


def subsequent(ctx: dict, threshold: float | None = None) -> dict | None:
    """결산일 다음 기간의 출금 전표(현금 · 예금 계정 대변)를 상대계정으로 구분한다. 기말 후 분개장이 없으면 None.
    구분: 상대계정이 없으면(현금 · 예금 줄뿐이면) 계좌 사이 대체, 차변 상대가 비용 · 자산이면 기말 후 발생 또는 계상하지 않은 부채 후보,
    부채이면 기말 부채 결제, 그 밖은 확인 필요. rows 는 계좌 사이 대체를 뺀 전표 가운데 기준 금액 이상(금액 상위 subsequent.max_rows 건까지)이다.
    기준 금액을 주지 않으면 default_threshold(정의 파일 · 2700B, 2026-10-26). 거래처는 현금 · 예금이 아닌 줄의 거래처(차변 먼저)다."""
    d = ctx["d"]
    pw = recalc.post_window(ctx)
    if not pw["post_files"]:
        return None
    sd = recalc.defs()["subsequent"]
    kinds = sd["kinds"]
    threshold = threshold if threshold is not None else default_threshold(ctx)
    pay = recalc._payable_by_party(d)
    cash = lambda x: recalc.in_group(x.code, x.name, "cash")  # noqa: E731
    out = []
    for v in pw["vouchers"]:
        if sum(x.cr for x in v.lines if cash(x)) <= 0.5:
            continue
        non = [x for x in v.lines if not cash(x)]
        dr = [x for x in non if x.dr]
        if not non:
            kind, amount = "transfer", sum(x.cr for x in v.lines)
        else:
            amount = sum(x.cr - x.dr for x in v.lines if cash(x))
            if amount <= 0.5:
                continue
            if any(recalc.in_group(x.code, x.name, "expense") or recalc.in_group(x.code, x.name, "asset") for x in dr):
                kind = "accrue"
            elif any(recalc.in_group(x.code, x.name, "liability") for x in dr):
                kind = "settle"
            else:
                kind = "other"
        party = next((x.party for x in dr + non if x.party), None) or (v.parties[0] if v.parties else None)
        out.append({"date": v.date, "voucher": v.no, "party": party, "amount": reader._int(amount), "memo": v.memo,
                    "counter": _names(dr), "kind": kind, "label": kinds[kind], "file": v.file, "sig": _sig(v),
                    "payable": pay.get(party) if kind == "settle" and party else None})
    paid = [r for r in out if r["kind"] != "transfer"]
    over = [r for r in paid if threshold is None or r["amount"] >= threshold]
    top = int(sd.get("max_rows") or skeleton.top_n(ctx["defs"]))
    rows = sorted(sorted(over, key=lambda r: (-r["amount"], r["date"], r["voucher"]))[:top], key=lambda r: (r["date"], r["voucher"]))
    by_kind = [{"kind": k, "label": kinds[k], "count": sum(1 for r in out if r["kind"] == k),
                "amount": reader._int(sum(r["amount"] for r in out if r["kind"] == k)),
                "over": sum(1 for r in over if r["kind"] == k)} for k in ("transfer", "settle", "accrue", "other")]
    return {"period": pw["period"], "window": pw["window"], "post_files": pw["post_files"], "threshold": threshold, "all": out, "rows": rows,
            "by_kind": by_kind, "paid_count": len(paid), "paid_amount": reader._int(sum(r["amount"] for r in paid)),
            "over_count": len(over), "over_amount": reader._int(sum(r["amount"] for r in over)),
            "transfer_count": len(out) - len(paid), "top": top, "vouchers": pw["vouchers"]}


def _sheet_subsequent(b, ctx: dict, area: dict) -> str | None:
    """4000CL 「기말 후 출금 검토」 는 기간 후 사건 모듈(audit/workpapers/subsequent.py, 2026-10-26)이 그린다."""
    from . import subsequent as sub

    return sub.sheet_payments(b, ctx, area)


def _sheet_legal(b, ctx: dict, area: dict) -> str | None:
    from . import subsequent as sub

    return sub.sheet_legal(b, ctx, area)


# ---------------------------------------------------------------- 4000FF 충당부채 변동 · 4000GG 자본변동표 공통
def _openings(ctx: dict, accts: list[dict]) -> dict:
    """계정별 기초 잔액(표시 부호)과 출처. 계정명세서 기초 열 → 전기 재무제표(그 표시과목에 이 영역 계정이 하나뿐일 때) 순. 없으면 None(기입란)."""
    d = ctx["d"]
    sched = common.schedule_openings(d)
    out = {}
    for r in accts:
        k = str(r["code"])
        v = sched["balances"].get(k)
        if v is not None:
            out[k] = (r["sign"] * v, f"계정명세서 기초 열({sched['source']})")
            continue
        alone = sum(1 for x in ctx["tb"] if x["line"] == r["line"]) == 1
        pv, src = common.prior_for(r["line"], ctx["prior"], ctx["defs"]) if alone else (None, "")
        out[k] = (pv, src) if pv is not None else (None, "기초 자료 없음, 기입란")
    return out


def _area_bs(ctx: dict, code: str) -> list[dict]:
    return [r for r in ctx["tb"] if r["area"] == code and not r["pl"]]


def _acct_lines(ctx: dict, accts: list[dict]) -> list:
    keys = {_acct_key(r["code"], r["name"]) for r in accts}
    return [x for x in recalc._journals(ctx)["cur"] if _acct_key(x.code, x.name) in keys]


def _movement_table(b, ws, row: int, sheet: str, accts: list[dict], opens: dict, moves: list[tuple], area: dict, label_end: str = "기말") -> tuple[int, dict]:
    """구분(행) × 계정(열) 변동표. moves 는 [(이름, 부호, {계정코드: 금액})]. 기초는 엔진 값이나 기입란, 기말은 수식이다.
    아래에 시산표 잔액과 차이, Lead 당기(회사제시)와 차이를 둔다. (다음 행, {"end": 기말 행, "sum": 합계 열, "first": 기초 행})"""
    n = len(accts)
    c_sum = 2 + n
    row = b.head(ws, row, ["구분"] + [f"{r['code']} {r['name']}" for r in accts] + ["합계"])
    r_open = row
    b.put(ws, row, 1, "기초", bold=True)
    for i, r in enumerate(accts):
        v, _ = opens[str(r["code"])]
        if v is None:
            ask(b, ws, row, 2 + i, f"기초: {r['name']}", rule="number", fmt=wp.WON, wrap=False)
        else:
            b.put(ws, row, 2 + i, v, fmt=wp.WON)
    row += 1
    for name, _, vals in moves:
        b.put(ws, row, 1, name)
        for i, r in enumerate(accts):
            b.put(ws, row, 2 + i, reader._int(vals.get(_acct_key(r["code"], r["name"]), 0)), fmt=wp.WON)
        row += 1
    r_end = row
    b.put(ws, row, 1, label_end, bold=True)
    for i in range(n):
        c = L(2 + i)
        terms = "".join(f"{'+' if sg > 0 else '-'}{c}{r_open + 1 + k}" for k, (_, sg, _) in enumerate(moves))
        b.put(ws, row, 2 + i, f'=IF({c}{r_open}="",0,{c}{r_open}){terms}', fmt=wp.WON, bold=True)
    row += 1
    r_tb = row
    b.put(ws, row, 1, "시산표(회사제시)")
    for i, r in enumerate(accts):
        b.put(ws, row, 2 + i, r["disp"], fmt=wp.WON)
    row += 1
    r_diff = row
    b.put(ws, row, 1, f"차이({label_end} − 시산표)")
    for i, r in enumerate(accts):
        v, _ = opens[str(r["code"])]
        calc = None if v is None else v + sum(sg * vals.get(_acct_key(r["code"], r["name"]), 0) for _, sg, vals in moves)
        b.put(ws, row, 2 + i, f"={L(2 + i)}{r_end}-{L(2 + i)}{r_tb}", fmt=wp.WON, flag=calc is not None and abs(calc - r["disp"]) > 0.5)
    for rr in range(r_open, r_diff + 1):
        b.put(ws, rr, c_sum, f"=SUM(B{rr}:{L(c_sum - 1)}{rr})", fmt=wp.WON, bold=rr in (r_open, r_end))
    row += 1
    expr, lead_v = lead_sum(area, lambda line: not _is_pl_line(area)(line))
    b.put(ws, row, 1, "Lead 당기(회사제시)")
    b.put(ws, row, c_sum, f"={expr}", fmt=wp.WON)
    row += 1
    b.put(ws, row, 1, f"차이({label_end} 합계 − Lead)")
    known = all(opens[str(r["code"])][0] is not None for r in accts)
    end_v = sum((opens[str(r["code"])][0] or 0) + sum(sg * vals.get(_acct_key(r["code"], r["name"]), 0) for _, sg, vals in moves) for r in accts)
    b.put(ws, row, c_sum, f"={L(c_sum)}{r_end}-{L(c_sum)}{row - 1}", fmt=wp.WON, flag=known and abs(end_v - lead_v) > 0.5)
    ref = wp.sheet_ref(sheet)
    for k, (name, _, vals) in enumerate(moves):
        b.verify(f"{b.no} {sheet} {name} 합계", f"={ref}{L(c_sum)}{r_open + 1 + k}", reader._int(sum(vals.values())))
    if known:
        b.verify(f"{b.no} {sheet} {label_end} 합계", f"={ref}{L(c_sum)}{r_end}", reader._int(end_v))
        b.verify(f"{b.no} {sheet} {label_end} 합계 − Lead", f"={ref}{L(c_sum)}{row}", reader._int(end_v - lead_v))
    return row + 1, {"open": r_open, "end": r_end, "sum": c_sum, "known": known}


def _open_sources(ws, row: int, accts: list[dict], opens: dict) -> int:
    srcs = list(dict.fromkeys(opens[str(r["code"])][1] for r in accts))
    return _note(ws, row, "기초 출처: " + " · ".join(srcs) + ". 기초 자료가 없는 계정은 노란 칸에 전기 감사받은 금액을 적어 주십시오"
                 if any(opens[str(r["code"])][0] is None for r in accts) else "기초 출처: " + " · ".join(srcs))


# ---------------------------------------------------------------- 4000FF 충당부채 변동
def provisions(ctx: dict, code: str = "FF") -> dict | None:
    """충당부채 계정별 전입 · 사용 · 환입. 계정의 대변은 전입, 차변은 상대계정이 수익이거나 비용(비용 차감)이면 환입, 그 밖은 사용이다.
    시산표에 이 영역 부채 계정이 없거나 당기 분개장이 없으면 None."""
    accts = _area_bs(ctx, code)
    if not accts or not recalc._journals(ctx)["cur"]:
        return None
    lines = _acct_lines(ctx, accts)
    vmap = _vouchers_by_line(recalc._journals(ctx)["cur"]) if lines else {}
    mine = {_acct_key(r["code"], r["name"]) for r in accts}
    add: dict[str, float] = {}
    use: dict[str, float] = {}
    rev: dict[str, float] = {}
    odd: dict[str, float] = {}
    uses = []
    for x in lines:
        k = _acct_key(x.code, x.name)
        others = [y for y in vmap[id(x)].lines if _acct_key(y.code, y.name) not in mine]
        if x.cr:
            add[k] = add.get(k, 0) + x.cr
            if not any(y.dr and recalc.in_group(y.code, y.name, "expense") for y in others):
                odd[k] = odd.get(k, 0) + x.cr
        if x.dr:
            cr = [y for y in others if y.cr]
            if any(recalc.in_group(y.code, y.name, "income") or recalc.in_group(y.code, y.name, "expense") for y in cr):
                rev[k] = rev.get(k, 0) + x.dr
            else:
                use[k] = use.get(k, 0) + x.dr
                uses.append({"date": x.date, "voucher": x.voucher, "row": x.row, "account": x.name, "counter": _names(cr),
                             "amount": reader._int(x.dr), "memo": x.memo})
    top = int(recalc.defs()["provision"]["use_top"])
    shown = sorted(sorted(uses, key=lambda r: (-r["amount"], r["date"], r["voucher"]))[:top], key=lambda r: (r["date"], r["voucher"]))
    return {"accts": accts, "opens": _openings(ctx, accts), "add": add, "use": use, "rev": rev, "odd": odd, "uses": uses, "shown": shown, "top": top}


def _sheet_provisions(b, ctx: dict, area: dict) -> str | None:
    accts = _area_bs(ctx, area["code"])
    if not accts:
        return None                                    # 충당부채 계정이 없다. Lead 가 영역 대응이 없다고 알린다
    p = provisions(ctx, area["code"])
    if p is None:
        return f"「{PROVISION}」: 당기 분개장을 받으면 만듭니다"
    n = len(accts)
    ws, row = b.sheet(PROVISION, widths=[30] + [20] * n + [20] + [18] * max(0, 8 - (n + 2)))
    last_col = max(n + 2, 8)
    _basis(ws, "당기 분개장에서 충당부채 계정의 대변과 차변을 상대계정으로 나눴다. 대변은 전입, 차변은 상대계정이 수익이거나 비용 차감이면 환입, "
               "그 밖은 사용이다. 증빙 확인과 판정, 환입 사유는 감사인이 적는다", last_col)
    ws.row_dimensions[6].height = 28
    row = b.section(ws, row, "충당부채 변동 (표시 금액: 부채는 양수)")
    row, at = _movement_table(b, ws, row, PROVISION, accts, p["opens"],
                              [("전입", 1, p["add"]), ("사용", -1, p["use"]), ("환입", -1, p["rev"])], area)
    row = _open_sources(ws, row, accts, p["opens"])
    if any(p["odd"].values()):
        b.put(ws, row, 1, "전입 가운데 상대계정이 비용이 아닌 금액", wrap=True, flag=True)
        for i, r in enumerate(accts):
            b.put(ws, row, 2 + i, reader._int(p["odd"].get(_acct_key(r["code"], r["name"]), 0)), fmt=wp.WON, flag=True)
        row += 1
        row = _note(ws, row, "상대계정이 비용이 아닌 전입은 계정 대체나 사업결합일 수 있습니다. 전표를 확인해 주십시오", color=wp.RED)
    row += 1
    row = b.section(ws, row, f"사용 건 {len(p['shown'])}건 (전체 {len(p['uses'])}건 가운데 금액 상위 {p['top']}건까지)")
    if not p["shown"]:
        row = _note(ws, row, "당기 분개장에 충당부채 사용 건이 없습니다")
    else:
        row = b.head(ws, row, ["일자", "전표번호", "계정", "상대계정", "금액", "적요", "증빙", "판정"])
        first = row
        for r in p["shown"]:
            key = f"{r['date'].isoformat()} {r['voucher']}-{r['row'] or ''}"
            b.put(ws, row, 1, r["date"].isoformat())
            b.put(ws, row, 2, r["voucher"])
            b.put(ws, row, 3, r["account"])
            b.put(ws, row, 4, r["counter"], wrap=True)
            b.put(ws, row, 5, r["amount"], fmt=wp.WON)
            b.put(ws, row, 6, common.short(r["memo"], 40), wrap=True)
            ask(b, ws, row, 7, f"증빙: {key}", rule="required")
            ask(b, ws, row, 8, f"판정: {key}", rule="required")
            row += 1
        b.put(ws, row, 1, "합계", bold=True)
        b.put(ws, row, 5, f"=SUM(E{first}:E{row - 1})", fmt=wp.WON, bold=True)
        b.verify(f"{b.no} 충당부채 사용 건 금액 합", f"={wp.sheet_ref(PROVISION)}E{row}", sum(r["amount"] for r in p["shown"]))
        row += 1
    row += 1
    if any(p["rev"].values()):
        ws.cell(row, 1, "환입 사유").font = wp.font(color=wp.MUTED)
        ask(b, ws, row, 2, "환입 사유", rule="required")
        ws.merge_cells(start_row=row, start_column=2, end_row=row, end_column=last_col)
        row += 1
    _note(ws, row, "사용 건은 의무 이행과 대응하는지 증빙으로 확인합니다. 줄 수는 definitions/recalc.yaml 의 provision.use_top 입니다. "
                   "설정 근거(경험률 · 적용 율)의 검토는 Lead 의 감사절차 및 결과에 적어 주십시오")
    return None


# ---------------------------------------------------------------- 4000GG 자본변동표 · 등기 대사
def equity(ctx: dict, code: str = "GG") -> dict | None:
    """자본 계정 전표를 변동 유형으로 모은다(대변 − 차변, 자본 증가가 양수). 유형을 정하지 못한 전표는 그 밖의 변동이다.
    시산표에 자본 계정이 없거나 당기 분개장이 없으면 None."""
    accts = _area_bs(ctx, code)
    if not accts or not recalc._journals(ctx)["cur"]:
        return None
    st = recalc.defs()["equity"]
    lines = _acct_lines(ctx, accts)
    vmap = _vouchers_by_line(recalc._journals(ctx)["cur"]) if lines else {}
    mine = {_acct_key(r["code"], r["name"]) for r in accts}
    moves = {t: {} for t in EQUITY_TYPES}
    unknown = set()
    for x in lines:
        v = vmap[id(x)]
        others = [y for y in v.lines if _acct_key(y.code, y.name) not in mine]
        text = reader._norm(v.memo) + " " + " ".join(reader._norm(y.name) for y in others)
        if any(k in text for k in st["dividend_keys"]):
            t = "배당"
        elif x.cr and any(k in reader._norm(x.name) for k in st["issue_accounts"]) and (
                any(k in reader._norm(v.memo) for k in st["issue_keys"]) or any(y.dr and recalc.in_group(y.code, y.name, "cash") for y in others)):
            t = "증자"
        elif any(common.is_pl(y.code) or any(k in reader._norm(y.name) for k in st["income_keys"]) for y in others):
            t = "당기순이익"
        else:
            t = "그 밖의 변동"
            unknown.add((v.file, v.date, v.no))
        k = _acct_key(x.code, x.name)
        moves[t][k] = moves[t].get(k, 0) + x.cr - x.dr
    capital = [r for r in accts if reader._norm(r["line"]) in {reader._norm(x) for x in st["capital_lines"]}]
    return {"accts": accts, "opens": _openings(ctx, accts), "moves": moves, "unknown": len(unknown), "lines": len(lines),
            "capital": reader._int(sum(r["disp"] for r in capital)) if capital else None,
            "capital_lines": list(dict.fromkeys(r["line"] for r in capital))}


def _sheet_equity(b, ctx: dict, area: dict) -> str | None:
    accts = _area_bs(ctx, area["code"])
    if not accts:
        return None
    e = equity(ctx, area["code"])
    if e is None:
        return f"「{EQUITY}」: 당기 분개장을 받으면 만듭니다"
    n = len(accts)
    ws, row = b.sheet(EQUITY, widths=[30] + [20] * n + [20] + [18] * max(0, 6 - (n + 2)))
    last_col = max(n + 2, 6)
    _basis(ws, "당기 분개장에서 자본 계정의 대변 − 차변을 전표의 적요와 상대계정으로 나눴다. 유형을 정하지 못한 전표는 「그 밖의 변동」 에 넣었다. "
               "1주의 금액과 발행주식의 총수는 등기사항전부증명서를 보고 감사인이 적는다", last_col)
    ws.row_dimensions[6].height = 28
    row = b.section(ws, row, "자본변동표 (표시 금액: 자본은 양수)")
    row, at = _movement_table(b, ws, row, EQUITY, accts, e["opens"], [(t, 1, e["moves"][t]) for t in EQUITY_TYPES], area)
    row = _open_sources(ws, row, accts, e["opens"])
    unknown = f"유형을 엔진이 정하지 못한 전표 {e['unknown']}건은 「그 밖의 변동」 에 넣었습니다" if e["unknown"] else "유형을 정하지 못한 전표는 없습니다"
    row = _note(ws, row, f"당기 분개장의 자본 계정 분개 행 {e['lines']}개. {unknown}. 전표별 내역은 「자본 변동」 시트에 있습니다",
                color=wp.RED if e["unknown"] else wp.MUTED)
    row = _note(ws, row, "결산 전 시산표이면 당기순이익이 이익잉여금에 들어가기 전이라 당기순이익 줄이 0 입니다")
    row += 1
    row = b.section(ws, row, "등기 대사 (등기사항전부증명서)")
    row = b.head(ws, row, ["구분", "값", "비고"])
    r0 = row
    b.put(ws, row, 1, "1주의 금액")
    ask(b, ws, row, 2, "1주의 금액", rule="number", fmt=wp.WON, wrap=False)
    b.put(ws, row, 3, "등기사항전부증명서", color=wp.MUTED)
    row += 1
    b.put(ws, row, 1, "발행주식의 총수")
    ask(b, ws, row, 2, "발행주식의 총수", rule="number", fmt="#,##0", wrap=False)
    b.put(ws, row, 3, "등기사항전부증명서", color=wp.MUTED)
    row += 1
    b.put(ws, row, 1, "계산한 자본금")
    b.put(ws, row, 2, f'=IF(OR(B{r0}="",B{r0 + 1}=""),"",B{r0}*B{r0 + 1})', fmt=wp.WON)
    b.put(ws, row, 3, "1주의 금액 × 발행주식의 총수", color=wp.MUTED)
    row += 1
    b.put(ws, row, 1, "장부 자본금")
    if e["capital"] is None:
        ask(b, ws, row, 2, "장부 자본금", rule="number", fmt=wp.WON, wrap=False)
        b.put(ws, row, 3, "시산표에 표시과목이 자본금인 계정이 없습니다. 적어 주십시오", wrap=True, flag=True)
    else:
        expr, cap_v = lead_sum(area, lambda line: line in e["capital_lines"])
        b.put(ws, row, 2, f"={expr}", fmt=wp.WON)
        b.put(ws, row, 3, "Lead 당기(회사제시) " + " · ".join(e["capital_lines"]), color=wp.MUTED)
        b.verify(f"{b.no} 등기 대사 장부 자본금", f"={wp.sheet_ref(EQUITY)}B{row}", cap_v)
    row += 1
    b.put(ws, row, 1, "차이(계산한 자본금 − 장부 자본금)", wrap=True)
    b.put(ws, row, 2, f'=IF(OR(B{row - 2}="",B{row - 1}=""),"",B{row - 2}-B{row - 1})', fmt=wp.WON)
    row += 2
    _note(ws, row, "무액면주식이거나 우선주가 있으면 1주의 금액과 주식 수가 종류마다 다릅니다. 차이가 나면 종류별 계산을 결론에 적어 주십시오")
    return None


# ---------------------------------------------------------------- 4000G · 4000H 변동내역
def rollforward(ctx: dict, code: str) -> dict | None:
    """고정자산대장을 계정별로 모은 장부금액 변동. 전기말은 기초 장부가액 열, 없으면 취득가액 − 당기 취득 − 기초 누계액이다.
    당기말은 기말 장부가액 열, 없으면 취득가액 − 기말 누계액, 그것도 없으면 전기말 + 취득 − 처분 − 상각이다.
    대장이 없으면 None, 대장에 이 영역 자산 줄이 없으면 rows 가 빈 목록이다."""
    d = ctx["d"]
    start, end = common.fy_start(d), common.fy_end(d)
    a = recalc.assets(ctx)
    if not a["source"]:
        return None
    mine = [x for x in a["rows"] if x["area"] == code]
    by: dict[str, dict] = {}
    notes = set()
    for x in mine:
        acct = x["acct"] or ("무형자산" if code == "H" else "유형자산")
        e = by.setdefault(acct, {"acct": acct, "count": 0, "beg": 0, "add": 0, "disposal": 0, "dep": 0, "end": 0})
        add = x["add"]
        if add is None:
            add = x["cost"] if x["acq"] and start <= x["acq"] <= end else 0
            notes.add("당기 취득 열이 없어 취득일이 당기인 자산의 취득가액을 취득으로 보았다")
        disposal = x["disposal"]
        if disposal is None:
            disposal = 0
            notes.add("처분 열이 없어 처분을 0 으로 두었다")
        beg = x["beg_book"] if x["beg_book"] is not None else x["cost"] - add - x["beg_acc"]
        if x["end_book"] is not None:
            fin = x["end_book"]
        elif x["end_acc"] is not None:
            fin = x["cost"] - x["end_acc"]
            notes.add("기말 장부가액 열이 없어 취득가액 − 기말 누계액으로 계산했다")
        else:
            fin = beg + add - disposal - x["book"]
            notes.add("기말 장부가액 · 기말 누계액 열이 없어 당기말을 전기말 + 취득 − 처분 − 상각으로 계산했다")
        e["count"] += 1
        for k, v in (("beg", beg), ("add", add), ("disposal", disposal), ("dep", x["book"]), ("end", fin)):
            e[k] += v
    rows = list(by.values())
    for e in rows:
        e["other"] = e["end"] - (e["beg"] + e["add"] - e["disposal"] - e["dep"])
    return {"rows": rows, "source": a["source"], "notes": sorted(notes)}


def _sheet_roll(b, ctx: dict, area: dict) -> str | None:
    code = area["code"]
    what = "무형자산" if code == "H" else "유형자산"
    rf = rollforward(ctx, code)
    if rf is None:
        return f"「{ROLL}」: 고정자산대장을 받으면 만듭니다"
    if not rf["rows"]:
        return f"「{ROLL}」: {what} 줄이 있는 고정자산대장을 받으면 만듭니다"
    ws, row = b.sheet(ROLL, widths=[22, 18, 18, 18, 18, 18, 18, 10, 34])
    _basis(ws, f"고정자산대장을 계정별로 모은 장부금액 변동이다({rf['source']}). 대장으로 설명되지 않는 금액은 「그 밖의 증감」 에 수식으로 남는다. "
               "그 밖의 증감의 설명은 감사인이 적는다", 9)
    ws.row_dimensions[6].height = 28
    row = b.section(ws, row, f"{what} 변동내역 (장부금액)")
    row = b.head(ws, row, ["계정", "전기말", "취득", "처분", "상각", "그 밖의 증감", "당기말", "자산 수", "그 밖의 증감 설명"])
    first = row
    for e in rf["rows"]:
        b.put(ws, row, 1, e["acct"], bold=True)
        b.put(ws, row, 2, e["beg"], fmt=wp.WON)
        b.put(ws, row, 3, e["add"], fmt=wp.WON)
        b.put(ws, row, 4, e["disposal"], fmt=wp.WON)
        b.put(ws, row, 5, e["dep"], fmt=wp.WON)
        b.put(ws, row, 6, f"=G{row}-(B{row}+C{row}-D{row}-E{row})", fmt=wp.WON, flag=bool(e["other"]))
        b.put(ws, row, 7, e["end"], fmt=wp.WON)
        b.put(ws, row, 8, e["count"], fmt="#,##0")
        ask(b, ws, row, 9, f"그 밖의 증감 설명: {e['acct']}", rule="required" if e["other"] else "optional")
        row += 1
    last = row - 1
    b.put(ws, row, 1, "합계", bold=True)
    for c in range(2, 9):
        b.put(ws, row, c, f"=SUM({L(c)}{first}:{L(c)}{last})", fmt=wp.WON if c != 8 else "#,##0", bold=True)
    tot = row
    ref = wp.sheet_ref(ROLL)
    expr, lead_v = lead_sum(area, lambda line: not _is_pl_line(area)(line))
    end_v = sum(e["end"] for e in rf["rows"])
    row += 1
    b.put(ws, row, 1, "Lead 당기(회사제시)")
    b.put(ws, row, 7, f"={expr}", fmt=wp.WON)
    b.put(ws, row, 9, "Lead 의 재무상태표 표시과목 합", color=wp.MUTED)
    row += 1
    b.put(ws, row, 1, "차이(당기말 − Lead)")
    b.put(ws, row, 7, f"=G{tot}-G{row - 1}", fmt=wp.WON, flag=end_v != lead_v)
    for lab, col, key in (("전기말", "B", "beg"), ("취득", "C", "add"), ("처분", "D", "disposal"), ("상각", "E", "dep"), ("당기말", "G", "end")):
        b.verify(f"{b.no} 변동내역 {lab} 합계", f"={ref}{col}{tot}", sum(e[key] for e in rf["rows"]))
    b.verify(f"{b.no} 변동내역 그 밖의 증감 합계", f"={ref}F{tot}", sum(e["other"] for e in rf["rows"]))
    b.verify(f"{b.no} 변동내역 당기말 − Lead", f"={ref}G{row}", end_v - lead_v)
    row += 2
    for t in rf["notes"]:
        row = _note(ws, row, "대장 판독: " + t)
    _note(ws, row, "대장에 없는 자산(토지 · 건설중인자산)이 Lead 에 있으면 차이로 보입니다. 차이의 까닭은 결론에 적어 주십시오")
    return None


# ---------------------------------------------------------------- 4000C 손실충당금 검토
def _bucket_head(h: str, st: dict) -> bool:
    return (bool(re.search(r"\d", h)) and any(u in h for u in st["bucket_units"])) or any(w in h for w in st["bucket_words"])


def aging(ctx: dict) -> dict | None:
    """연령분석표의 연령 구간별 합계. {"buckets": [(구간, 금액)], "total"(합계 열), "source", "allowance"(회사 계상 충당금, 양수),
    "allowance_names", "receivable"(시산표 채권 잔액, 충당금 차감 전)}. 연령 구간 열이 없으면 None."""
    d = ctx["d"]
    st = recalc.defs()["loss_allowance"]
    for rel in figures.received(d, reader.AGING):
        if Path(rel).suffix.lower() not in reader.READABLE:
            continue
        tabs = reader.asof_tabs(reader._tables(d / rel, [["party"], ["ar_total"]], []), common.case(d).get("fiscal_year_end"))
        for sheet, c, rows, _, hdr in tabs:
            cols = [i for i, h in enumerate(hdr) if i not in c.values() and _bucket_head(h, st)]
            if not cols:
                continue
            sums = {i: 0.0 for i in cols}
            seen = set()
            total = 0.0
            for r in rows:
                if reader._is_total_row(r) or reader._cell(r, c["party"]) in (None, ""):
                    continue
                v = reader._num(reader._cell(r, c["ar_total"]))
                if v is None:
                    continue
                total += v
                for i in cols:
                    x = reader._num(reader._cell(r, i))
                    if x is not None:
                        sums[i] += x
                        seen.add(i)
            cols = [i for i in cols if i in seen]            # 숫자가 한 칸도 없는 열(날짜 · 메모)은 연령 구간이 아니다
            if not cols:
                continue
            common.note_read(rel)
            heads = _raw_heads(d / rel, sheet, hdr)
            allow = [r for r in ctx["tb"] if r["area"] == "C" and not r["pl"] and any(k in reader._norm(r["name"]) for k in st["allowance_names"])]
            recv = [r for r in ctx["tb"] if recalc.in_group(r["code"], r["name"], "receivable") and r not in allow and not r["pl"]]
            return {"buckets": [(heads.get(i, hdr[i]), reader._int(sums[i])) for i in cols], "total": reader._int(total),
                    "source": f"{rel} '{sheet}' 시트", "allowance": reader._int(-sum(r["disp"] for r in allow)),
                    "allowance_names": list(dict.fromkeys(r["name"] for r in allow)),
                    "receivable": reader._int(sum(r["disp"] for r in recv))}
    return None


def _raw_heads(path: Path, sheet: str, hdr: list[str]) -> dict:
    """머리줄의 원래 글자(띄어쓰기를 살린 것). {열 번호: 글자}. 못 찾으면 빈 dict."""
    wb = reader._open(path)
    try:
        for row in wb[sheet].iter_rows(values_only=True, max_row=reader.HEADER_SCAN):
            if [reader._norm(v) for v in row][:len(hdr)] == hdr[:len(row)]:
                return {i: str(v).strip() for i, v in enumerate(row) if v not in (None, "")}
    finally:
        wb.close()
    return {}


def _sheet_allowance(b, ctx: dict, area: dict) -> str | None:
    ag = aging(ctx)
    if ag is None:
        return f"「{ALLOWANCE}」: 연령 구간 열이 있는 연령분석표를 받으면 만듭니다"
    ws, row = b.sheet(ALLOWANCE, widths=[34, 20, 14, 20, 40])
    _basis(ws, f"연령분석표의 연령 구간 열을 엔진이 더했다({ag['source']}). 적립율과 개별평가 충당금은 감사인이 적고 재계산 충당금은 수식이다. "
               "회사 계상 충당금은 시산표의 충당금 계정이다", 5)
    ws.row_dimensions[6].height = 28
    ref = wp.sheet_ref(ALLOWANCE)
    row = b.section(ws, row, "연령 구간별 채권과 충당금 재계산")
    row = b.head(ws, row, ["연령 구간", "채권 금액", "적립율", "재계산 충당금", "비고"])
    first = row
    for name, amt in ag["buckets"]:
        b.put(ws, row, 1, name)
        b.put(ws, row, 2, amt, fmt=wp.WON)
        ask(b, ws, row, 3, f"적립율: {name}", rule="number", fmt="0.00%", wrap=False)
        b.put(ws, row, 4, f'=IF(C{row}="","",ROUND(B{row}*C{row},0))', fmt=wp.WON)
        ask(b, ws, row, 5, f"비고: {name}", rule="optional")
        row += 1
    last = row - 1
    r_ind = row
    b.put(ws, row, 1, "개별평가 충당금")
    b.put(ws, row, 2, None)
    b.put(ws, row, 3, None)
    ask(b, ws, row, 4, "개별평가 충당금", rule="optional", fmt=wp.WON, wrap=False)
    b.put(ws, row, 5, "개별평가한 채권이 있으면 그 충당금을 적습니다. 구간 금액에서 빼지 않았습니다", wrap=True, color=wp.MUTED)
    row += 1
    tot = row
    b.put(ws, row, 1, "합계", bold=True)
    b.put(ws, row, 2, f"=SUM(B{first}:B{last})", fmt=wp.WON, bold=True)
    b.put(ws, row, 3, None)
    b.put(ws, row, 4, f"=SUM(D{first}:D{r_ind})", fmt=wp.WON, bold=True)
    b.put(ws, row, 5, None)
    row += 1
    b.put(ws, row, 1, "회사 계상 충당금")
    b.put(ws, row, 4, ag["allowance"], fmt=wp.WON)
    b.put(ws, row, 5, "시산표 " + (" · ".join(ag["allowance_names"]) if ag["allowance_names"] else "충당금 계정 없음(0)"), wrap=True, color=wp.MUTED)
    row += 1
    b.put(ws, row, 1, "차이(회사 계상 − 재계산)")
    b.put(ws, row, 4, f"=D{row - 1}-D{tot}", fmt=wp.WON)
    row += 2
    bucket_sum = sum(a for _, a in ag["buckets"])
    row = b.section(ws, row, "완전성 (연령 구간 합 ↔ 채권 잔액)")
    row = b.head(ws, row, ["구분", "금액", "", "차이(구간 합 − 금액)", "비고"])
    for lab, val, note in (("연령분석표 합계 열", ag["total"], "연령분석표 안의 가로 합"),
                           ("시산표 채권 잔액(충당금 차감 전)", ag["receivable"], "외상매출금 · 받을어음 계정의 시산표 잔액")):
        b.put(ws, row, 1, lab)
        b.put(ws, row, 2, val, fmt=wp.WON)
        b.put(ws, row, 3, None)
        b.put(ws, row, 4, f"=B{tot}-B{row}", fmt=wp.WON, flag=bucket_sum != val)
        b.put(ws, row, 5, note, color=wp.MUTED)
        b.verify(f"4000C 손실충당금 검토 구간 합 − {lab}", f"={ref}D{row}", bucket_sum - val)
        row += 1
    b.verify("4000C 손실충당금 검토 연령 구간 합", f"={ref}B{tot}", bucket_sum)
    row += 1
    for t in ("적립율은 회사의 충당금 설정 정책과 과거 대손 경험을 보고 감사인이 적습니다. 엔진은 율을 정하지 않습니다",
              "거래처별 연령 명세는 싣지 않았습니다. 받은자료 연령분석표에 있습니다. 차이가 명백히 사소한 금액을 넘으면 사유를 결론에 적고 8100A 에 올려 주십시오"):
        row = _note(ws, row, t)
    return None


def _sheet_progress(b, ctx: dict, area: dict) -> str | None:
    from . import progress

    return progress.add_sheet(b, ctx, area)


def _sheet_rollrate(b, ctx: dict, area: dict) -> str | None:
    from . import rollrate

    return rollrate.add_sheet(b, ctx, area)


def _sheet_ipe(b, ctx: dict, area: dict) -> str | None:
    from . import ipe

    return ipe.add_sheet(b, ctx, area)


# ---------------------------------------------------------------- 외화환산 재계산(4000A · C · D · AA · CC · BBDD, 2026-10-20)
FX_SHEET = "외화환산 재계산"


def fx_items(ctx: dict, code: str) -> dict | None:
    """분석.json fx 가운데 그 영역 항목. {items, non_monetary, rates, source, units} 또는 None(항목 없음)."""
    from ..analysis import fx as fxmod

    a = common.idx(ctx["d"], "분석.json", {}) or {}
    t = a.get("fx") or {}
    its = [x for x in t.get("items") or [] if x.get("area") == code]
    if not its:
        return None
    units = (fxmod.spec().get("currencies") or {})
    return {"items": its, "rates": t.get("rates") or {}, "source": t.get("source"), "units": units}


def _sheet_fx(b, ctx: dict, area: dict) -> str | None:
    f = fx_items(ctx, area["code"])
    if f is None:
        return None
    ws, row = b.sheet(FX_SHEET, widths=[16, 26, 7, 16, 11, 16, 11, 22, 16, 15, 10, 30])
    _basis(ws, "화폐성 외화항목은 결산일 환율(마감환율)로 환산한다(K-IFRS 1021 문단 23 · 28, 일반기업회계기준 23.9 · 23.10). 비화폐성 항목(선급금 · "
               "선수금 · 재고 · 유형 · 무형자산)은 거래일 환율로 두므로 다시 환산하지 않는다. 외화 금액은 " + str(f["source"]) + ", 장부 원화는 그 자료와 "
               "계정명세서, 결산일 환율은 2120A 기입란 또는 결산일 잔액증명 은행 환산이다. 화폐성 판단과 확인은 감사인이 적는다", 12)
    ws.row_dimensions[6].height = 42
    row = b.section(ws, row, "항목별 재계산")
    row = b.head(ws, row, ["계정", "거래처 · 계좌", "통화", "외화 금액", "회사 적용환율", "장부 원화", "결산일 환율", "환율 근거",
                           "재계산 원화", "차이(장부 − 재계산)", "구분", "감사인 확인"])
    first = row
    ref = wp.sheet_ref(FX_SHEET)
    for x in f["items"]:
        unit = int(f["units"].get(x["currency"], 1))
        b.put(ws, row, 1, x.get("acct_name") or x.get("account"))
        b.put(ws, row, 2, x.get("party"), wrap=True)
        b.put(ws, row, 3, x["currency"])
        b.put(ws, row, 4, x["fc"], fmt="#,##0.00")
        b.put(ws, row, 5, x.get("rate_book"), fmt="#,##0.00##")
        b.put(ws, row, 6, x["book"], fmt=wp.WON)
        mon = x.get("kind") != "비화폐성"
        if mon and x.get("rate") is not None:
            b.put(ws, row, 7, x["rate"], fmt="#,##0.00##")
            b.put(ws, row, 8, x.get("rate_basis"), wrap=True, color=wp.MUTED)
            if x["source"] == "잔액증명" and x.get("rate_basis") != "회계사 입력":
                b.put(ws, row, 9, x["expected"], fmt=wp.WON)       # 은행 원화 환산액 그대로
            else:
                b.put(ws, row, 9, f"=ROUND(D{row}*G{row}/{unit},0)", fmt=wp.WON)
            b.put(ws, row, 10, f"=F{row}-I{row}", fmt=wp.WON, flag=bool(x.get("diff")))
        elif mon:
            b.put(ws, row, 8, "결산일 환율 없음(2120A 기입란)", color=wp.RED)
        else:
            b.put(ws, row, 8, "비화폐성: 다시 환산하지 않음", color=wp.MUTED)
        b.put(ws, row, 11, x.get("kind"), flag=x.get("kind") == "판단 필요")
        ask(b, ws, row, 12, f"감사인 확인: {x.get('acct_name')} {x.get('party')} {x['currency']}",
            rule="required" if x.get("kind") == "판단 필요" else "optional")
        row += 1
    b.put(ws, row, 1, "합계", bold=True)
    for c in (6, 9, 10):
        b.put(ws, row, c, f"=SUM({L(c)}{first}:{L(c)}{row - 1})", fmt=wp.WON, bold=True)
    done = [x for x in f["items"] if x.get("kind") != "비화폐성" and "diff" in x]
    b.verify(f"{b.no} 외화환산 장부 원화 합", f"={ref}F{row}", sum(x["book"] for x in f["items"]))
    if done and len(done) == len([x for x in f["items"] if x.get("kind") != "비화폐성"]):
        b.verify(f"{b.no} 외화환산 차이 합(장부 − 재계산)", f"={ref}J{row}", sum(x["diff"] for x in done))
    row += 2
    for t in ("차이가 있으면 8100A 에 올린다. 분석적 검토(8100B 수정 제안)에 엔진 후보 「외화 화폐성 항목을 결산일 환율로 환산」 이 있다(상대 계정 외화환산이익 · 손실)",
              "구분 「판단 필요」 는 화폐성 여부를 감사인이 정한다(채무증권 · 보증금은 화폐성, 지분증권은 비화폐성). 엔진은 이 줄을 수정 후보에 넣지 않았다",
              "결산일 환율은 서울외국환중개 매매기준율 등 회사가 쓴 고시 환율과 같은지 확인한다"):
        row = _note(ws, row, t)
    return None


# ---------------------------------------------------------------- 조서에 붙이기
SHEETS = {"P": [_sheet_cutoff, _sheet_progress], "R": [_sheet_monthly], "CL": [_sheet_subsequent, _sheet_legal], "FF": [_sheet_provisions], "GG": [_sheet_equity],
          "G": [_sheet_roll], "H": [_sheet_roll], "C": [_sheet_allowance, _sheet_rollrate, _sheet_ipe, _sheet_fx],
          "A": [_sheet_fx], "D": [_sheet_fx], "AA": [_sheet_fx], "CC": [_sheet_fx], "BBDD": [_sheet_fx]}


# Q-11 분석 열두 가지(2026-11-11). 모듈이 이 파일의 도움 함수(_basis · _note · lead_sum)를 쓰므로 부를 때 불러온다(순환 import 방지).
# 값은 「모듈.함수」. 함수는 _sheet_* 와 같은 꼴(b, ctx, area) -> 안내 글 | None 이다
EXTRA = {"A": ["funds.sheet_interest_income", "funds.sheet_fx_summary"], "CC": ["funds.sheet_payable_trend"],
         "EE": ["payroll.sheet_monthly", "payroll.sheet_estimate", "payroll.sheet_annual_leave", "payroll.sheet_dc"],
         "E": ["stock.sheet_flow", "stock.sheet_nrv"], "Q": ["stock.sheet_mfg"],
         "CL": ["contracts.sheet_seal"], "DL": ["contracts.sheet_lease"]}


def _extra(code: str) -> list:
    import importlib

    out = []
    for ref in EXTRA.get(code, []):
        mod, fn = ref.split(".")
        out.append(getattr(importlib.import_module(f"{__package__}.{mod}"), fn))
    return out


def add_sheets(b, code: str, ctx: dict, area: dict) -> list[str]:
    """영역에 맞는 절차 시트를 책에 더한다. 자료가 없어 만들지 않은 시트의 안내 글을 돌려준다(Lead 절차 목록 아래에 적는다)."""
    out = []
    for fn in SHEETS.get(code, []) + _extra(code):
        msg = fn(b, ctx, area)
        if msg:
            out.append(msg)
    return out
