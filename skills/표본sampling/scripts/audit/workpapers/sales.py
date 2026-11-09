"""4000P 매출: 매출 요약 · 매출 분석 · 기간 분할 금액 단위 표본(R9 묶음 B4, 2026-10-06. 요약은 2026-10-12).

샘플 진단 §6.2(샘플 F): 사람 조서는 월별 · 거래처별 연도별 매출, 매출총이익률, 환입 · 에누리, 결산일 전후 일평균 매출, 부가세 대사를 보고
표본을 기간으로 나눠 뽑는다(1~9월 · 10~12월). 숫자는 분개장(당기 · 전기 · 기말 후)과 시산표 · 분석 결과에서만 온다.

  population(ctx)            당기 매출 분개 행 [(열쇠, 금액)] (대변 − 차변 > 0 인 행이 표본 모집단이다)
  analysis(ctx)              매출 분석 숫자 {months, parties, returns, window, vat}
  split_samples(ctx)         기간 분할 표본 [{label, months, s}] (sampling.yaml period_split · 기간마다 시드 seed + 순번)
  summary(ctx)               매출 요약 숫자 {total, count, months, parties, files, tb}. 모집단과 같은 행을 모은 것이다
  add_sheets(b, ctx)         「매출 분석」 · 「표본」 절차 시트와 「매출 요약」 요약 시트
                             매출 분개 행 전부(옛 「매출 모집단」 시트)는 조서에 싣지 않는다. 원자료는 받은자료에 둔다
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

from .. import folder, wp
from . import common, sampling, skeleton
from .common import ask

SALES_WHAT = "당기 매출 분개 행"



def _journals(ctx: dict) -> dict:
    if ctx.get("_j") is None:
        ctx["_j"] = common.journals(ctx["d"])
    return ctx["_j"]


def _is(x, group: dict) -> bool:
    if x.code is not None and common.in_ranges(x.code, group.get("ranges", [])):
        return True
    return x.code is None and any(k in (x.name or "") for k in group.get("names", []))


def _groups() -> dict:
    acc = common.load_def("jet.yaml")["accounts"]
    return {"revenue": acc["revenue"], "cogs": {"ranges": [[451, 470]], "names": ["매출원가"]}}


def _key(x) -> str:
    return f"{x.date.isoformat()} {x.voucher}-{x.row or ''} {x.party or ''}".strip()


def lines_of(ctx: dict) -> dict:
    """표본 열쇠 → 당기 매출 분개 행(감사-TOT 대조가 전표를 찾는 데 쓴다, 2026-10-26). 열쇠가 겹치면 앞 행."""
    g = _groups()["revenue"]
    out: dict = {}
    for x in _journals(ctx)["cur"]:
        if _is(x, g) and (x.cr - x.dr):
            out.setdefault(_key(x), x)
    return out


def population(ctx: dict, lines: list | None = None) -> list[tuple]:
    """당기 매출 분개 행(대변 − 차변). 열쇠는 '일자 전표번호-행 거래처'."""
    g = _groups()["revenue"]
    out = []
    for x in (_journals(ctx)["cur"] if lines is None else lines):
        if _is(x, g):
            amt = x.cr - x.dr
            if amt:
                out.append((_key(x), common.reader._int(amt)))
    return out


def _months(start: date, end: date) -> list[str]:
    out, y, m = [], start.year, start.month
    while (y, m) <= (end.year, end.month):
        out.append(f"{y}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def analysis(ctx: dict) -> dict:
    d = Path(ctx["d"])
    per = folder.periods(common.case(d))
    j = _journals(ctx)
    g = _groups()
    cur_m, pri_m = _months(per["cur_start"], per["cur_end"]), _months(per["prior_start"], per["prior_end"])

    def flows(lines, months, grp):
        out = {m: 0 for m in months}
        for x in lines:
            k = x.date.isoformat()[:7]
            if k in out and _is(x, g[grp]):
                out[k] += (x.cr - x.dr) if grp == "revenue" else (x.dr - x.cr)
        return {k: common.reader._int(v) for k, v in out.items()}

    rev, rev_p = flows(j["cur"], cur_m, "revenue"), flows(j["prior"], pri_m, "revenue")
    cogs, cogs_p = flows(j["cur"], cur_m, "cogs"), flows(j["prior"], pri_m, "cogs")
    has_prior = bool([x for x in j["prior"] if _is(x, g["revenue"])])
    months = []
    for i, m in enumerate(cur_m):
        pm = pri_m[i] if i < len(pri_m) else None
        months.append({"month": m, "prior_month": pm, "rev": rev[m], "rev_prior": rev_p.get(pm) if has_prior and pm else None,
                       "cogs": cogs[m], "cogs_prior": cogs_p.get(pm) if has_prior and pm else None})
    parties: dict[str, dict] = {}
    for fy, lines in (("cur", j["cur"]), ("prior", j["prior"])):
        for x in lines:
            if _is(x, g["revenue"]):
                e = parties.setdefault(x.party or "(거래처 없음)", {"party": x.party or "(거래처 없음)", "cur": 0, "prior": 0})
                e[fy] += x.cr - x.dr
    plist = sorted(({**e, "cur": common.reader._int(e["cur"]), "prior": common.reader._int(e["prior"])} for e in parties.values()),
                   key=lambda e: -e["cur"])
    # 환입 · 에누리: 매출 계정을 줄이는 행(차변, 또는 대변 음수로 적은 차감 · 취소 전표). 매출 ↔ 선수금 이연 대체는 뺀다.
    # 차변만 보아 대변 음수로 취소를 적는 회사에서 「없음」 으로 나왔다(2026-11-06 실제 회사 시험)
    def reducing(lines):
        skip = _advance_ids(lines)
        return [x for x in lines if _is(x, g["revenue"]) and (x.dr - x.cr) > 0 and id(x) not in skip]

    ret, ret_post = reducing(j["cur"]), reducing(j["post"])
    days = common.load_def("sampling.yaml").get("sales_window_days", 15)
    end = per["cur_end"]
    lo, hi = end - timedelta(days=days), end + timedelta(days=days)
    before = sum(x.cr - x.dr for x in j["cur"] if _is(x, g["revenue"]) and x.date > lo)
    after = sum(x.cr - x.dr for x in j["post"] if _is(x, g["revenue"]) and x.date <= hi)
    total = sum(rev.values())
    ndays = (per["cur_end"] - per["cur_start"]).days + 1
    window = {"days": days, "before": common.reader._int(before), "after": common.reader._int(after) if j["post"] else None,
              "year_daily": total / ndays if ndays else None, "before_daily": before / days, "after_daily": (after / days) if j["post"] else None,
              "post_files": sorted({x.file for x in j["post"]})}
    vat, vat_periods = None, []
    p = d / "_색인" / "분석.json"
    if p.exists():
        an = json.loads(p.read_text(encoding="utf-8"))
        vat = [r for r in an.get("recons", []) if r["id"] == "X-sales-vat"]
        vat_periods = an.get("vat_periods", [])
    return {"vat_periods": vat_periods, "months": months, "has_prior": has_prior, "parties": plist,
            "returns": [{"date": x.date.isoformat(), "voucher": x.voucher, "party": x.party, "memo": x.memo, "amount": common.reader._int(x.dr - x.cr)}
                        for x in ret],
            "returns_post": [{"date": x.date.isoformat(), "voucher": x.voucher, "party": x.party, "memo": x.memo, "amount": common.reader._int(x.dr - x.cr)}
                             for x in ret_post],
            "window": window, "vat": vat, "total": total}


def _advance_ids(lines: list) -> set:
    """매출 ↔ 선수금(선수수익 · 계약부채)만 오가는 전표의 매출 행 id. 이연 · 인식 대체라 환입 · 에누리가 아니다."""
    acc = common.load_def("jet.yaml")["accounts"]
    rev, adv = acc["revenue"], acc["advances"]
    out = set()
    for v in common.vouchers(lines):
        r = [x for x in v.lines if _is(x, rev)]
        rest = [x for x in v.lines if not _is(x, rev)]
        if r and rest and all(_is(x, adv) for x in rest):
            out.update(id(x) for x in r)
    return out


def advance_transfers(lines: list) -> tuple[set, list[dict]]:
    """같은 달 · 같은 거래처에서 매출 ↔ 선수금(선수수익 · 계약부채)만 오가는 전표가 양쪽 부호로 함께 있으면 순액 하나로 합친다.
    (합쳐서 모집단에서 뺄 행 id 집합, 묶음 [{month, party, key, amount, gross, vouchers}]).

    월말 「전월 미경과매출 환입(+) · 당월 미경과매출 이연(−)」 을 총액으로 두면 매달 큰 금액이 양쪽으로 잡혀 모집단이 실제 매출의
    몇 배가 되고 표본이 부푼다(2026-11-06 실제 회사: 모집단이 매출의 약 5배). 한쪽 부호만 있는 선수금 → 매출 대체(구독 매출을 매달
    인식하는 정상 수익 인식, jet.yaml advances)는 그대로 둔다. 빼면 인식된 매출을 시험하지 않게 된다."""
    acc = common.load_def("jet.yaml")["accounts"]
    rev, adv = acc["revenue"], acc["advances"]
    groups: dict = {}
    for v in common.vouchers(lines):
        r = [x for x in v.lines if _is(x, rev)]
        rest = [x for x in v.lines if not _is(x, rev)]
        if r and rest and all(_is(x, adv) for x in rest):
            for x in r:
                groups.setdefault((x.date.isoformat()[:7], x.party or ""), []).append((v.no, x))
    ids, out = set(), []
    for (month, party), xs in sorted(groups.items()):
        amts = [x.cr - x.dr for _, x in xs]
        if not (any(a > 0 for a in amts) and any(a < 0 for a in amts)):
            continue
        ids.update(id(x) for _, x in xs)
        top = max(xs, key=lambda t: t[1].cr - t[1].dr)[1]
        out.append({"month": month, "party": party, "key": f"{_key(top)} 선수금 대체 순액", "amount": common.reader._int(sum(amts)),
                    "gross": common.reader._int(sum(abs(a) for a in amts)), "vouchers": sorted({no for no, _ in xs})})
    return ids, out


def split_samples(ctx: dict) -> list[dict]:
    """사업연도 마지막 tail_months 달과 그 앞으로 나눠 기간마다 금액 단위 표본을 뽑는다. 위험 수준은 lead.sample_risk(영역 위험).
    같은 달 · 같은 거래처의 매출 ↔ 선수금 환입 · 이연은 순액 하나로 합친다(advance_transfers)."""
    from . import lead

    d = Path(ctx["d"])
    per = folder.periods(common.case(d))
    st = sampling.settings()
    tail = int((st.get("period_split") or {}).get("tail_months", 3))
    months = _months(per["cur_start"], per["cur_end"])
    if len(months) <= tail:
        groups = [months]
    else:
        groups = [months[:-tail], months[-tail:]]
    base = st["seed"] if ctx.get("seed") is None else ctx["seed"]
    pm = ctx["mat"]["performance"]
    ch = sampling.chosen_for(ctx, "4000P", SALES_WHAT)      # 명령 --risk 가 앞선다(예상 왜곡표시는 시트 값, 2026-11-09)
    out = []
    lines = _journals(ctx)["cur"]
    moved, netted = advance_transfers(lines)
    for k, ms in enumerate(groups):
        sub = [x for x in lines if x.date.isoformat()[:7] in ms and id(x) not in moved]
        tr = [t for t in netted if t["month"] in ms]
        pop = population(ctx, sub) + [(t["key"], t["amount"]) for t in tr if t["amount"]]
        label = f"{ms[0]} ~ {ms[-1]}"
        s = sampling.mus(pop, pm, lead.sample_risk(ctx, "P", ch), base + k, ch.get("factor"), ch.get("expected", 0)) if pop and pm else None
        out.append({"label": label, "months": ms, "s": s, "seed": base + k, "count": len(pop),
                    "transfers": len(tr), "transfer_gross": sum(t["gross"] for t in tr), "transfer_amount": sum(t["amount"] for t in tr)})
    return out


def issue_detail(ctx: dict, issue: dict) -> list[str]:
    """이슈 대응 절차를 그 회사의 실제 대상으로 구체화한다(2026-10-16). 숫자는 엔진 값만 쓴다.
    부가세 차이가 난 신고 기간, 기말 후 취소 전표, 당기 신규 거래처, 결산일 전 매출 집중을 적고 대응 시트를 가리킨다."""
    a = analysis(ctx)
    out = []
    for r in a["vat_periods"]:
        if r["diff"]:
            out.append(f"부가세 신고 기간 {r['start']} ~ {r['end']}: 장부 매출 − 과세표준 {r['diff']:,}원 → .01 매출 분석 「부가세 대사 차이 내역」 을 채운다")
    if a["returns_post"]:
        out.append(f"기말 후 매출 취소 {len(a['returns_post'])}건 {sum(x['amount'] for x in a['returns_post']):,}원("
                   + ", ".join(f"{x['date']} {x['party']}" for x in a["returns_post"][:4]) + ") → .03 Cut-off 에서 원 매출 전표 · 인도 증빙과 대사")
    new = [e for e in a["parties"] if a["has_prior"] and not e["prior"] and e["cur"]]
    if new:
        out.append(f"당기 신규 거래처 {len(new)}곳(" + ", ".join(e["party"] for e in new[:4]) + ") → 3320 조회와 실재성 확인(사업자 조회 · 계약서 · 출고 증빙)")
    w = a["window"]
    if w["year_daily"] and w["before_daily"] > 2 * w["year_daily"]:
        out.append(f"결산일 전 {w['days']}일 일평균 매출이 연 일평균의 {w['before_daily'] / w['year_daily']:.1f}배 → .02 표본의 마지막 기간 결과를 따로 본다")
    return out


# ---------------------------------------------------------------- 시트
def _put_rows(b, ws, row: int, items: list[tuple]) -> int:
    for lab, val, fmt in items:
        ws.cell(row, 1, lab).font = wp.font(color=wp.MUTED)
        b.put(ws, row, 2, val, fmt=fmt, wrap=fmt is None)
        row += 1
    return row


SUMMARY_SHEET = "매출 요약"


def summary(ctx: dict) -> dict:
    """매출 요약 숫자(설계 7절). 표본 모집단과 같은 당기 매출 분개 행을 월 · 거래처 · 받은자료 파일로 모은다.
    {"total", "count", "months": [(월, 금액, 행 수)], "parties": [{party, amount, count}], "files": [(파일, 금액, 매출 행 수, 전체 행 수)], "tb"}"""
    g = _groups()["revenue"]
    cur = _journals(ctx)["cur"]
    per = folder.periods(common.case(Path(ctx["d"])))
    months = {m: [0, 0] for m in _months(per["cur_start"], per["cur_end"])}
    parties: dict[str, list] = {}
    files: dict[str, list] = {}
    rows_in_file: dict[str, int] = {}
    for x in cur:
        rows_in_file[x.file] = rows_in_file.get(x.file, 0) + 1
        amt = (x.cr - x.dr) if _is(x, g) else 0
        if not amt:
            continue
        for by, k in ((months, x.date.isoformat()[:7]), (parties, x.party or "(거래처 없음)"), (files, x.file)):
            e = by.setdefault(k, [0, 0])
            e[0] += amt
            e[1] += 1
    i = common.reader._int
    tb = sum(r["disp"] for r in ctx["tb"] if r["area"] == "P" and r["line"] == "매출액") or sum(r["disp"] for r in ctx["tb"] if r["area"] == "P")
    return {"total": i(sum(v[0] for v in months.values())), "count": sum(v[1] for v in months.values()),
            "months": [(m, i(v[0]), v[1]) for m, v in sorted(months.items())],
            "parties": sorted(({"party": p, "amount": i(v[0]), "count": v[1]} for p, v in parties.items()), key=lambda e: -e["amount"]),
            "files": [(f, i(v[0]), v[1], rows_in_file.get(f, 0)) for f, v in sorted(files.items())], "tb": tb}


def _summary_sheet(b, ctx: dict) -> int:
    """「매출 요약」(요약 시트, 번호 없음): 월별 합계, 거래처 금액 상위와 「기타 (n곳)」, 합계 ↔ 시산표 매출액 대사, 받은자료 파일 이름과 행 수.
    매출 분개 행 전부(모집단)는 조서에 옮기지 않는다. 원자료는 받은자료 분개장에 있다(2026-10-12 결정)."""
    sm = summary(ctx)
    total, ref = sm["total"], wp.sheet_ref(SUMMARY_SHEET)
    ws, row = b.sheet(SUMMARY_SHEET, widths=[44, 18, 12, 12, 30])
    ws.cell(6, 1, "당기 매출 분개 행(대변 − 차변)을 월 · 거래처로 모았다. 금액 단위 표본의 모집단과 같은 행이다. "
                  "분개 행 전체는 받은자료 분개장에 있다").font = wp.font(size=9, color=wp.MUTED)
    # 1 월별 합계 · 시산표 대사
    row = b.section(ws, row, "월별 합계")
    row = b.head(ws, row, ["월", "금액", "행 수"])
    first = row
    for m, amt, n in sm["months"]:
        b.put(ws, row, 1, m)
        b.put(ws, row, 2, amt, fmt=wp.WON)
        b.put(ws, row, 3, n, fmt="#,##0")
        row += 1
    b.put(ws, row, 1, "합계", bold=True)
    b.put(ws, row, 2, f"=SUM(B{first}:B{max(row - 1, first)})", fmt=wp.WON, bold=True)
    b.put(ws, row, 3, f"=SUM(C{first}:C{max(row - 1, first)})", fmt="#,##0", bold=True)
    tot = row
    row += 1
    b.put(ws, row, 1, "시산표 매출액")
    b.put(ws, row, 2, sm["tb"], fmt=wp.WON)
    row += 1
    b.put(ws, row, 1, "합계 − 시산표 매출액")
    b.put(ws, row, 2, f"=B{tot}-B{row - 1}", fmt=wp.WON, flag=total != sm["tb"])
    b.verify("4000P 매출 요약 합계", f"={ref}B{tot}", total)
    b.verify("4000P 매출 요약 − 시산표 매출액", f"={ref}B{row}", total - sm["tb"])
    b.verify("4000P 매출 요약 행 수 = 표본 모집단 행 수", f"={ref}C{tot}", len(population(ctx)))
    row += 2

    # 2 거래처 금액 상위와 기타
    top = skeleton.top_n(ctx["defs"])
    shown, rest = skeleton.top_rows(sm["parties"], top, lambda e: e["amount"])
    row = b.section(ws, row, f"거래처별 금액 ({len(sm['parties']):,}곳)")
    row = b.head(ws, row, ["거래처", "금액", "행 수", "구성비"])
    pf = row
    ptot = pf + len(shown) + (1 if rest else 0)
    for e in shown + ([{"party": skeleton.others_label(rest), "amount": sum(x["amount"] for x in rest),
                       "count": sum(x["count"] for x in rest)}] if rest else []):
        b.put(ws, row, 1, e["party"])
        b.put(ws, row, 2, e["amount"], fmt=wp.WON)
        b.put(ws, row, 3, e["count"], fmt="#,##0")
        b.put(ws, row, 4, f'=IF($B${ptot}=0,"",B{row}/$B${ptot})', fmt=wp.PCT)
        row += 1
    b.put(ws, row, 1, "합계", bold=True)
    b.put(ws, row, 2, f"=SUM(B{pf}:B{max(row - 1, pf)})", fmt=wp.WON, bold=True)
    b.put(ws, row, 3, f"=SUM(C{pf}:C{max(row - 1, pf)})", fmt="#,##0", bold=True)
    b.verify("4000P 매출 요약 거래처별 합계 = 월별 합계", f"={ref}B{row}", total)
    row += 1
    if rest:
        ws.cell(row, 1, "거래처 " + skeleton.top_note(len(sm["parties"]), len(shown), len(rest), top)).font = wp.font(size=9, color=wp.MUTED)
        row += 1
    row += 1

    # 3 받은자료 파일 이름과 행 수
    row = b.section(ws, row, "받은자료 (모집단을 읽은 당기 분개장)")
    row = b.head(ws, row, ["파일", "매출 분개 행 금액", "매출 분개 행 수", "당기 분개 행 수"])
    ff = row
    for f, amt, n, rows_ in sm["files"]:
        b.put(ws, row, 1, f, wrap=True)
        b.put(ws, row, 2, amt, fmt=wp.WON)
        b.put(ws, row, 3, n, fmt="#,##0")
        b.put(ws, row, 4, rows_, fmt="#,##0")
        row += 1
    if not sm["files"]:
        b.put(ws, row, 1, "당기 분개장에 매출 계정 행이 없습니다", flag=True, wrap=True)
        row += 1
    else:
        b.put(ws, row, 1, "합계", bold=True)
        b.put(ws, row, 2, f"=SUM(B{ff}:B{row - 1})", fmt=wp.WON, bold=True)
        b.put(ws, row, 3, f"=SUM(C{ff}:C{row - 1})", fmt="#,##0", bold=True)
        b.verify("4000P 매출 요약 파일별 합계 = 월별 합계", f"={ref}B{row}", total)
    return total


def _analysis_sheet(b, ctx: dict) -> None:
    a = analysis(ctx)
    ws, row = b.sheet("매출 분석", widths=[16, 18, 18, 18, 12, 18, 12, 18, 12])
    ws.cell(6, 1, "분개장(당기 · 전기 · 기말 후)에서 엔진이 계산했다. 설명 칸은 감사인이 적는다. 매출은 매출 계정 대변 − 차변, "
                  "매출원가는 451~470 계정 차변 − 대변").font = wp.font(size=9, color=wp.MUTED)
    # 1 월별
    row = b.section(ws, row, "월별 매출 · 매출총이익률" + ("" if a["has_prior"] else " (전기 분개장이 없어 전기 열은 비움)"))
    row = b.head(ws, row, ["월", "당기 매출", "전기 같은 달", "증감", "증감률", "당기 매출원가", "당기 매출총이익률", "전기 매출원가", "전기 매출총이익률"])
    first = row
    for m in a["months"]:
        b.put(ws, row, 1, m["month"])
        b.put(ws, row, 2, m["rev"], wp.WON)
        b.put(ws, row, 3, m["rev_prior"], wp.WON)
        b.put(ws, row, 4, f'=IF(C{row}="","",B{row}-C{row})', wp.WON)
        b.put(ws, row, 5, f'=IF(OR(C{row}="",C{row}=0),"",D{row}/ABS(C{row}))', wp.PCT)
        b.put(ws, row, 6, m["cogs"], wp.WON)
        b.put(ws, row, 7, f'=IF(B{row}=0,"",(B{row}-F{row})/B{row})', wp.PCT)
        b.put(ws, row, 8, m["cogs_prior"], wp.WON)
        b.put(ws, row, 9, f'=IF(OR(H{row}="",C{row}="",C{row}=0),"",(C{row}-H{row})/C{row})', wp.PCT)
        row += 1
    b.put(ws, row, 1, "합계", bold=True)
    for col in (2, 3, 6, 8):
        L = "ABCDEFGHI"[col - 1]
        if col in (3, 8) and not a["has_prior"]:
            continue
        b.put(ws, row, col, f"=SUM({L}{first}:{L}{row - 1})", wp.WON, bold=True)
    b.put(ws, row, 7, f'=IF(B{row}=0,"",(B{row}-F{row})/B{row})', wp.PCT, bold=True)
    b.verify("4000P 월별 매출 합 = 분개장 매출", f"='매출 분석'!B{row}", a["total"])
    row += 1
    ask(b, ws, row, 2, "월별 추이 설명", rule="required")
    ws.cell(row, 1, "월별 추이 설명").font = wp.font(color=wp.MUTED)
    ws.merge_cells(start_row=row, start_column=2, end_row=row, end_column=9)
    row += 2

    # 2 거래처별 연도별
    row = b.section(ws, row, f"거래처별 매출 (당기 · 전기, {len(a['parties'])}곳)")
    row = b.head(ws, row, ["거래처", "당기", "전기", "증감", "증감률", "당기 구성비", "신규", "", ""])
    pf = row
    # 줄이 많으면 당기 금액 상위와 「기타 (n곳)」 한 줄로 줄인다. 신규 거래처는 남긴다(설계 7절)
    top = skeleton.top_n(ctx["defs"])
    shown, rest = skeleton.top_rows(a["parties"], top, lambda e: e["cur"],
                                    keep=lambda e: bool(a["has_prior"] and not e["prior"] and e["cur"]))
    if rest:
        shown = shown + [{"party": skeleton.others_label(rest), "cur": sum(e["cur"] for e in rest), "prior": sum(e["prior"] for e in rest),
                          "others": True}]
    tot_row = pf + len(shown)
    for e in shown:
        b.put(ws, row, 1, e["party"])
        b.put(ws, row, 2, e["cur"], wp.WON)
        b.put(ws, row, 3, e["prior"] if a["has_prior"] else None, wp.WON)
        b.put(ws, row, 4, f'=IF(C{row}="","",B{row}-C{row})', wp.WON)
        b.put(ws, row, 5, f'=IF(OR(C{row}="",C{row}=0),"",D{row}/ABS(C{row}))', wp.PCT)
        b.put(ws, row, 6, f'=IF($B${tot_row}=0,"",B{row}/$B${tot_row})', wp.PCT)
        new = a["has_prior"] and not e["prior"] and e["cur"] and not e.get("others")
        b.put(ws, row, 7, "신규" if new else "", flag=bool(new))
        row += 1
    b.put(ws, row, 1, "합계", bold=True)
    b.put(ws, row, 2, f"=SUM(B{pf}:B{max(row - 1, pf)})", wp.WON, bold=True)
    if a["has_prior"]:
        b.put(ws, row, 3, f"=SUM(C{pf}:C{max(row - 1, pf)})", wp.WON, bold=True)
    b.verify("4000P 거래처별 매출 합", f"='매출 분석'!B{row}", sum(e["cur"] for e in a["parties"]))
    if rest:
        row += 1
        ws.cell(row, 1, "거래처 " + skeleton.top_note(len(a["parties"]), len(shown) - 1, len(rest), top, "신규 거래처")).font = \
            wp.font(size=9, color=wp.MUTED)
    row += 2

    # 3 환입 · 에누리
    row = b.section(ws, row, "환입 · 에누리 (매출을 줄인 행: 차변 또는 대변 음수, 매출 ↔ 선수금 이연 대체 제외. 금액 큰 순서 30건씩)")
    row = b.head(ws, row, ["구분", "일자", "전표번호", "거래처", "금액", "적요", "", "", ""])
    for kind, rows_ in (("당기", a["returns"]), ("기말 후", a["returns_post"])):
        top = sorted(rows_, key=lambda x: -x["amount"])[:30]
        for x in top:
            b.put(ws, row, 1, kind)
            b.put(ws, row, 2, x["date"])
            b.put(ws, row, 3, x["voucher"])
            b.put(ws, row, 4, x["party"])
            b.put(ws, row, 5, x["amount"], wp.WON, flag=kind == "기말 후")
            b.put(ws, row, 6, common.short(x["memo"], 40))
            row += 1
        if len(rows_) > len(top):
            shown = {id(x) for x in top}
            rest = [x for x in rows_ if id(x) not in shown]
            b.put(ws, row, 1, kind)
            b.put(ws, row, 2, f"그 밖 {len(rest):,}행", color=wp.MUTED)
            b.put(ws, row, 5, sum(x["amount"] for x in rest), wp.WON, color=wp.MUTED)
            row += 1
        if not rows_:
            b.put(ws, row, 1, kind)
            b.put(ws, row, 2, "없음", color=wp.MUTED)
            row += 1
    b.put(ws, row, 1, "합계(당기)", bold=True)
    b.put(ws, row, 5, sum(x["amount"] for x in a["returns"]), wp.WON, bold=True)
    row += 1
    b.put(ws, row, 1, "합계(기말 후)", bold=True)
    b.put(ws, row, 5, sum(x["amount"] for x in a["returns_post"]), wp.WON, bold=True, flag=bool(a["returns_post"]))
    row += 2

    # 4 결산일 전후 일평균
    w = a["window"]
    row = b.section(ws, row, f"결산일 전후 일평균 매출 (결산일 전 {w['days']}일 · 결산일 후 {w['days']}일)")
    row = b.head(ws, row, ["구간", "매출", "일평균", "연 일평균 대비", "", "", "", "", ""])
    yr = row
    b.put(ws, row, 1, "사업연도 전체")
    b.put(ws, row, 2, a["total"], wp.WON)
    b.put(ws, row, 3, w["year_daily"], wp.WON)
    row += 1
    b.put(ws, row, 1, f"결산일 전 {w['days']}일")
    b.put(ws, row, 2, w["before"], wp.WON)
    b.put(ws, row, 3, w["before_daily"], wp.WON)
    b.put(ws, row, 4, f'=IF(C{yr}=0,"",C{row}/C{yr})', "0.00")
    row += 1
    b.put(ws, row, 1, f"결산일 후 {w['days']}일")
    if w["after"] is None:
        b.put(ws, row, 2, "기말 후 분개장 없음", color=wp.MUTED)
    else:
        b.put(ws, row, 2, w["after"], wp.WON)
        b.put(ws, row, 3, w["after_daily"], wp.WON)
        b.put(ws, row, 4, f'=IF(C{yr}=0,"",C{row}/C{yr})', "0.00")
    row += 1
    ws.cell(row, 1, "결산일 전 일평균이 크게 높고 결산일 후가 낮거나 음수(취소)이면 기간 귀속 · 허위 매출을 의심한다").font = wp.font(size=9, color=wp.MUTED)
    row += 1
    ask(b, ws, row, 2, "결산일 전후 매출 설명", rule="required")
    ws.cell(row, 1, "설명").font = wp.font(color=wp.MUTED)
    ws.merge_cells(start_row=row, start_column=2, end_row=row, end_column=9)
    row += 2

    # 5 부가세 과세표준 대사
    row = b.section(ws, row, "부가세 과세표준 대사 (분석적 검토 X-sales-vat, 2120A 대사 시트)")
    row = b.head(ws, row, ["기간", "장부 매출", "신고 과세표준", "차이", "근거", "", "", "", ""])
    if a["vat"] is None:
        b.put(ws, row, 1, "분석 결과(_색인/분석.json)가 없습니다", color=wp.MUTED)
    elif not a["vat"]:
        b.put(ws, row, 1, "부가세 신고서가 없어 대사하지 못했습니다(2120A 대사 시트)", color=wp.MUTED)
    for r in a["vat"] or []:
        b.put(ws, row, 1, "당기" if r["period"] == "cur" else "전기")
        b.put(ws, row, 2, r["left"], wp.WON)
        b.put(ws, row, 3, r["right"], wp.WON)
        b.put(ws, row, 4, f"=B{row}-C{row}", wp.WON, flag=bool(r["diff"]))
        b.put(ws, row, 5, "; ".join(x for x in r["refs"] if x), wrap=True, color=wp.MUTED)
        b.verify(f"4000P 부가세 대사 {r['period']} 차이", f"='매출 분석'!D{row}", r["diff"])
        row += 1
    if a["vat_periods"]:
        row = _vat_breakdown(b, ws, row + 1, a, ctx)


# 부가세 대사 차이 내역(샘플 조서의 「부가세과표와 매출액대사표」 방식, 2026-10-16). 감사인이 금액을 적는 줄이다.
# 부호: 장부 매출 − 신고 과세표준을 설명하는 금액. 장부에만 있는 매출은 +, 신고에만 있는 공급은 −
VAT_ITEMS = ["세금계산서 없이 장부에만 있는 매출(기말 후 취소 · 허위 의심 포함)", "선수금 세금계산서 · 공급시기 차이", "고정자산 매각 · 간주공급(신고에만 있음)",
             "면세 · 과세 제외 매출", "기타"]


def _vat_breakdown(b, ws, row: int, a: dict, ctx: dict) -> int:
    """신고 기간(열)마다 장부 매출 · 신고 과세표준 · 차이와 차이 내역(감사인 기입), 설명 후 남은 차이. 엔진 후보는 옆에 참고로 적는다."""
    from openpyxl.utils import get_column_letter as L

    ps = a["vat_periods"]
    n = len(ps)
    ws.cell(row, 1, "부가세 대사 차이 내역 (신고 기간별. 차이를 원인별로 풀어 설명 후 남은 차이를 본다)").font = wp.font(bold=True)
    row = b.head(ws, row + 1, ["내용"] + [f"{p['start'][5:]} ~ {p['end'][5:]}" for p in ps] + ["계", "엔진 후보(참고)"])
    tot = n + 2
    first = row

    def sum_cell(r):
        b.put(ws, r, tot, f"=SUM(B{r}:{L(n + 1)}{r})", wp.WON, bold=True)

    b.put(ws, row, 1, "장부 매출(분개장)")
    for j, p in enumerate(ps, 2):
        b.put(ws, row, j, p["left"], wp.WON)
    sum_cell(row)
    rb = row
    row += 1
    b.put(ws, row, 1, "신고 과세표준(과세 + 영세율)")
    for j, p in enumerate(ps, 2):
        b.put(ws, row, j, p["right"], wp.WON)
    sum_cell(row)
    rv = row
    row += 1
    b.put(ws, row, 1, "차이(장부 − 신고)", bold=True)
    for j, p in enumerate(ps, 2):
        b.put(ws, row, j, f"={L(j)}{rb}-{L(j)}{rv}", wp.WON, bold=True, flag=bool(p["diff"]))
        b.verify(f"4000P 부가세 기간별 대사 {p['start']} 차이", f"='매출 분석'!{L(j)}{row}", p["diff"])
    sum_cell(row)
    rd = row
    row += 1
    post = sum(x["amount"] for x in a["returns_post"])
    hint = {VAT_ITEMS[0]: f"기말 후 매출 취소 {len(a['returns_post'])}건 {post:,}원(.03 Cut-off). 세금계산서 발급 여부를 확인해 적는다" if post else None}
    ri = row
    for item in VAT_ITEMS:
        b.put(ws, row, 1, f"  {item}")
        for j, p in enumerate(ps, 2):
            ask(b, ws, row, j, f"부가세 차이 내역: {common.short(item, 20)} {p['start']}", rule="optional", fmt=wp.WON)
        sum_cell(row)
        if hint.get(item):
            b.put(ws, row, tot + 1, hint[item], wrap=True, color=wp.MUTED)
        row += 1
    b.put(ws, row, 1, "설명 후 남은 차이", bold=True)
    for j in range(2, n + 2):
        b.put(ws, row, j, f"={L(j)}{rd}-SUM({L(j)}{ri}:{L(j)}{row - 1})", wp.WON, bold=True)
    sum_cell(row)
    triv = ctx["mat"].get("trivial")
    b.put(ws, row, tot + 1, f"명백히 사소한 금액({triv:,}원)을 넘으면 원인을 더 찾거나 8100A 왜곡표시로 올린다" if triv else
          "남은 차이가 있으면 원인을 더 찾거나 8100A 왜곡표시로 올린다", wrap=True, color=wp.MUTED)
    ws.cell(row + 1, 1, "출처: 신고서 " + ", ".join(p["ref"] for p in ps) + ". 장부 매출은 신고 기간 안 매출 계정 대변 − 차변").font = \
        wp.font(size=9, color=wp.MUTED)
    assert first == rb
    return row + 2


def _sample_sheet(b, ctx: dict) -> None:
    from .vouch import widths as vw

    from . import tot as tot_mod

    kind = tot_mod.area_kind("P")                 # 감사-TOT 증빙 대조(definitions/tot.yaml areas, 2026-10-26)
    ws, row = b.sheet("표본", widths=vw(40, tot=bool(kind)))
    parts = split_samples(ctx)
    line_of = lines_of(ctx) if kind else {}
    results: list[dict] = []
    m = ctx["mat"]
    if not m["performance"] or not any(p["s"] for p in parts):
        b.put(ws, row, 1, "당기 분개장의 매출 행이나 수행중요성이 없어 표본을 뽑지 못했습니다", flag=True, wrap=True)
        return
    tail = (sampling.settings().get("period_split") or {}).get("tail_months", 3)
    ws.cell(6, 1, f"표본을 기간으로 나눠 뽑는다(사업연도 마지막 {tail}개월과 그 앞, definitions/sampling.yaml period_split). "
                  "기간마다 같은 허용왜곡표시 · 신뢰계수라 표본 수는 기간 매출에 비례한다. 시드는 기간마다 시드 + 순번").font = wp.font(size=9, color=wp.MUTED)
    row = b.section(ws, row, "기간별 표본 요약")
    row = b.head(ws, row, ["기간", "모집단 금액", "항목 수", "표본 간격", "계획 표본 수", "선정 항목 수", "시드", ""])
    for p in parts:
        s = p["s"]
        b.put(ws, row, 1, p["label"], bold=True)
        b.put(ws, row, 2, s["total"] if s else 0, wp.WON)
        b.put(ws, row, 3, p["count"], "#,##0")
        b.put(ws, row, 4, s["interval"] if s else None, wp.WON)
        b.put(ws, row, 5, s["size"] if s else 0, "#,##0")
        b.put(ws, row, 6, len(s["selected"]) if s else 0, "#,##0")
        b.put(ws, row, 7, p["seed"], "0")
        row += 1
    n_tr = sum(p.get("transfers", 0) for p in parts)
    if n_tr:
        amt = sum(p.get("transfer_amount", 0) for p in parts)
        gross = sum(p.get("transfer_gross", 0) for p in parts)
        ws.cell(row, 1, f"같은 달 · 같은 거래처의 매출 ↔ 선수금 환입 · 이연 {n_tr}묶음(총액 {gross:,}원)은 순액 {amt:,}원으로 합쳐 모집단에 두었다"
                        "(순액이 0 이하인 묶음은 빠진다). 이연 계산 자체는 선수금(계약부채) 재계산으로 본다(4000CC · 이 조서 Cut-off)").font = wp.font(size=9, color=wp.RED)
        row += 1
    row += 1
    from .lead import evidence_note, risk_inputs

    ev = common.evidence_files(ctx["d"])
    row = risk_inputs(b, ws, row, SALES_WHAT) + 1
    ev_refs: list[dict] = []
    ev_tol = None
    for p in parts:
        s = p["s"]
        if not s:
            continue
        row = b.section(ws, row, f"{p['label']} 표본 ({s['method']}, 시드 {p['seed']})")
        for lab, val, fmt in [("모집단 금액", s["total"], wp.WON), ("허용왜곡표시(수행중요성)", s["tolerable"], wp.WON),
                              ("수행중요성 근거", m["basis"], None), ("적용 위험 수준", s["risk"], None),
                              ("신뢰계수", s["factor"], "0.00"), ("예상 왜곡표시", s.get("expected", 0), wp.WON),
                              ("표본 간격", s["interval"], wp.WON), ("시작점", s["start"], wp.WON)]:
            ws.cell(row, 1, lab).font = wp.font(color=wp.MUTED)
            b.put(ws, row, 2, val, fmt=fmt, wrap=fmt is None, flag=(lab == "수행중요성 근거" and m["candidate"]))
            row += 1
        from .lead import sample_count_note
        from . import vouch

        row = sample_count_note(b, ws, row, s)

        def match(r):
            day, voucher, party = _key_parts(r["key"])
            return common.match_evidence(ev, party=party, voucher=voucher, day=day)

        def tot(r):
            x = line_of.get(r["key"])
            return tot_mod.check(ctx, kind, x) if x is not None else None

        row, first = vouch.table(b, ws, row, s["selected"], "일자 전표-행 거래처", ev, match, tot=tot if kind else None)
        results += [r["tot"] for r in s["selected"] if r.get("tot")]
        if s["selected"]:
            b.verify(f"4000P 표본 금액 합 {p['label']}", f"=SUM('표본'!C{first}:C{row - 1})", sum(r["amount"] for r in s["selected"]))
        if vouch._is_mus(s):
            row, r_ev = vouch.eval_numbers(b, ws, row + 1, s, first, row - 1, f"표본 결과 수치 (감사기준서 530 문단 14): {p['label']}")
            ev_refs.append(r_ev)
            ev_tol = s["tolerable"]
        else:
            row += 1
    if ev_refs:                                   # 기간마다 같은 허용왜곡표시라 기간을 합쳐 한 번만 견준다(2026-11-02)
        row = vouch.eval_conclude(b, ws, row, ev_refs, ev_tol, SALES_WHAT)
    ws.cell(row, 1, "출처: definitions/sampling.yaml (신뢰계수 = −ln(1 − 신뢰수준), 확장계수 표, 감사-표본sampling 방법론 docs/표본-방법론.md)").font = wp.font(size=9, color=wp.MUTED)
    row += 1
    ws.cell(row, 1, evidence_note(ev) + ". 매출 분개 행은 전표번호, 또는 거래처와 일자(20250115 꼴)가 함께 있는 파일만 잇습니다").font = wp.font(size=9, color=wp.MUTED)
    row += 1
    ws.cell(row, 1, "검사 항목: √ 일치 · ✗ 다름 · 해당 없음 가운데 고른다. 다름이 있으면 검사 결과에 차이와 처리를 적는다(8100A 왜곡표시 후보)").font = wp.font(size=9, color=wp.MUTED)
    if kind:
        row = tot_mod.footnote(ws, row + 1, ctx, kind, results) - 1
    from .lead import sampling_guide

    sampling_guide(b, ws, row + 2)          # 표본 수를 고르는 방법(2026-10-08 감사 전문가 회의)


def _key_parts(key: str) -> tuple[str | None, str | None, str | None]:
    """매출 표본 열쇠 「2025-01-15 202501-0009-2 대영정밀」 → (일자, 전표번호, 거래처). 행 번호(-2)는 뗀다."""
    parts = str(key).split(" ", 2)
    if len(parts) < 3:
        return None, None, str(key)
    day, vr, party = parts
    voucher = vr.rsplit("-", 1)[0] if vr.count("-") >= 2 else vr
    return day, voucher, party


def add_sheets(b, ctx: dict) -> None:
    _analysis_sheet(b, ctx)
    _sample_sheet(b, ctx)
    _summary_sheet(b, ctx)
