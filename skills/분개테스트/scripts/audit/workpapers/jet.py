"""3600-JET 분개 테스트(R4, 2026-10-05).

분개장 받은자료 전부를 엔진이 판독해 전표 단위로 시험한다. 시험 정의는 definitions/jet.yaml.
완전성: 당기 분개장의 손익계정 순액을 시산표와 맞춘다(재무상태표 계정은 기초 잔액이 분개장에 없어 전기 시산표가 있어야 한다).
결과 목록의 전표마다 검토 결과 기입란을 둔다. 판단(정상 거래인지)은 회계사가 적는다.

  run(d, mat) -> {"tests": [{id, title, condition, review, hits: [{voucher, why}], note}], "completeness": [...], ...}
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from .. import wp
from . import common
from .common import ask, won


def _grp(v: common.Voucher, side: str, group: dict) -> list:
    out = []
    for x in v.lines:
        if not (x.dr if side == "dr" else x.cr):
            continue
        if x.code is not None and common.in_ranges(x.code, group.get("ranges", [])):
            out.append(x)
        elif x.code is None and any(k in (x.name or "") for k in group.get("names", [])):
            out.append(x)
    return out


def _any(v: common.Voucher, group: dict) -> bool:
    return bool(_grp(v, "dr", group) or _grp(v, "cr", group))


WEEKDAYS = "월화수목금토일"


def _hit(x: common.Line, group: dict) -> bool:
    """줄 하나가 계정 묶음에 드는지: 코드 범위 · 이름 낱말 · 이름 전체 가운데 하나라도 맞으면 든다(R9 결산조정 유형)."""
    if x.code is not None and common.in_ranges(x.code, group.get("ranges", [])):
        return True
    name = common.reader._norm(x.name or "")
    if any(k in name for k in group.get("names", [])):
        return True
    return name in set(group.get("exact", []))


def closing_types(cur: list, spec: dict, end: date) -> dict:
    """당기 전표를 결산조정 유형으로 나눈다(R9 B3). {"types": [{id, title, count, amount, ye_count, ye_amount}], "rows": [(유형, 전표)]}.
    결산월은 결산일이 든 달이다. 분류표이지 시험(걸림)이 아니다."""
    acc = spec.get("closing_accounts") or {}
    types = spec.get("closing_types") or []
    rows = []
    for v in cur:
        for t in types:
            ok = False
            for a, b in t.get("pairs", []):
                dr = [x for x in v.lines if x.dr]
                cr = [x for x in v.lines if x.cr]
                fwd = any(_hit(x, acc[a]) for x in dr) and any(_hit(x, acc[b]) for x in cr)
                rev = t.get("either") and any(_hit(x, acc[b]) for x in dr) and any(_hit(x, acc[a]) for x in cr)
                if fwd or rev:
                    ok = True
                    break
            if not ok and t.get("lines"):
                ok = any(_hit(x, acc[g]) for g in t["lines"] for x in v.lines)
            if ok:
                rows.append((t, v))
                break
    out = []
    for t in types:
        vs = [v for tt, v in rows if tt is t]
        ye = [v for v in vs if (v.date.year, v.date.month) == (end.year, end.month)]
        out.append({"id": t["id"], "title": t["title"], "count": len(vs), "amount": sum(v.amount for v in vs),
                    "ye_count": len(ye), "ye_amount": sum(v.amount for v in ye)})
    return {"types": out, "rows": [(t["title"], v) for t, v in rows]}


def bs_completeness(d: Path, tb: list[dict], lines: list) -> dict:
    """재무상태표 계정: 기말(시산표) − 기초(전기 잔액 원천 1~3) = 차변 발생 − 대변 발생(당기 분개장)(R9 B3).
    전기 잔액은 감사받은 숫자 · 회사제시 전기 시산표(audit.prior 원천 1~3)만 쓴다. 장부 값(시산표 − 분개장)은 이 대사를
    늘 0 으로 만들므로 쓰지 않는다. 원천이 없는 계정은 기초를 비우고 까닭을 적는다."""
    from .. import prior
    from ..analysis import defs as adefs

    accs = prior.current_accounts(d)
    keys = {a["code"] for a in accs}
    ap = prior.account_prior(d, accs, book_values={})
    dr: dict[str, float] = {}
    cr: dict[str, float] = {}
    for x in lines:
        if x.code is None:
            continue
        k = adefs.align_code(adefs.code_key(x.code) or str(x.code), keys)
        dr[k] = dr.get(k, 0.0) + x.dr
        cr[k] = cr.get(k, 0.0) + x.cr
    rows = []
    for a in accs:
        if a["section"] not in prior.BS_SECTIONS:
            continue
        p = ap["accounts"].get(a["code"]) or {}
        rows.append({"code": a["code"], "name": a["name"], "open": p.get("prior"), "basis": p.get("basis"),
                     "dr": common.reader._int(dr.get(a["code"], 0.0)), "cr": common.reader._int(cr.get(a["code"], 0.0)), "close": a["cur"]})
    src = [s["basis"] for s in ap["sources"]]
    return {"rows": rows, "sources": src}


def voucher_sources(cur: list, extra_cols: list, spec: dict) -> dict | None:
    """전표 출처(입력구분 · 전표구분 열) 값마다 전표 수 · 금액과 수기 · 자동 구분(R9 B3). 열이 없으면 None."""
    cols = [c for c in spec.get("source_columns", []) if c in extra_cols]
    if not cols:
        return None
    manual = spec.get("manual_values", [])
    by: dict[str, dict] = {}
    for v in cur:
        val = next((str(x.extra.get(c)).strip() for x in v.lines for c in cols if x.extra.get(c) not in (None, "")), "(빈 칸)")
        e = by.setdefault(val, {"value": val, "count": 0, "amount": 0.0, "kind": "수기" if any(w in val for w in manual) else "자동"})
        e["count"] += 1
        e["amount"] += v.amount
    return {"columns": cols, "rows": sorted(by.values(), key=lambda e: -e["count"])}


def run(d: Path, mat: dict | None = None) -> dict:
    d = Path(d)
    spec = common.load_def("jet.yaml")
    acc = spec["accounts"]
    mat = mat or common.materiality(d)
    pm = mat["performance"]
    end = common.fy_end(d)
    j = common.journals(d)
    cur = common.vouchers(j["cur"])
    post = common.vouchers(j["post"])
    hol = {date.fromisoformat(str(x)) for x in spec.get("holidays", [])}
    tests = {t["id"]: {**t, "hits": [], "note": ""} for t in spec["tests"]}

    def hit(tid: str, v: common.Voucher, why: str):
        tests[tid]["hits"].append({"voucher": v, "why": why})

    # 주말 · 공휴일
    for v in cur + post:
        # 월말 일자 결산 전표(감가상각 · 원가 대체 · 이자 계상)는 날짜를 월말로 다는 것이 정상이라 주말이어도 보지 않는다
        if (v.date + timedelta(days=1)).month != v.date.month:
            continue
        if v.date.weekday() >= 5:
            hit("weekend", v, "토요일" if v.date.weekday() == 5 else "일요일")
        elif v.date in hol:
            hit("weekend", v, "공휴일")

    # 기말 후 취소 · 역분개
    t = tests["post_ye_reversal"]
    lo = end - timedelta(days=t.get("window_before", 45))
    hi = end + timedelta(days=t.get("window_after", 60))
    near = [v for v in cur if v.date >= lo]
    used: set[int] = set()
    for pv in [v for v in post if v.date <= hi]:
        net = pv.net()
        if not net:
            continue
        rev = {k: -x for k, x in net.items()}
        match = next((ov for ov in near if id(ov) not in used and ov.net() == rev), None)
        if match is not None:
            used.add(id(match))
            hit("post_ye_reversal", match, f"기말 후 {pv.date.isoformat()} {pv.no} 로 반대 분개됨")
            hit("post_ye_reversal", pv, f"결산일 전 {match.date.isoformat()} {match.no} 의 반대 분개")
        elif _grp(pv, "dr", acc["revenue"]):
            hit("post_ye_reversal", pv, "기말 후 매출 차변(짝인 결산일 전 전표를 찾지 못함)")
    if not post:
        t["note"] = "결산일 후 분개장이 없어 시험하지 못했습니다. 기말 후 2개월 분개장을 받아 주십시오"

    # 결산일 근처 큰 금액
    t = tests["near_ye_large"]
    if pm:
        cut = pm * t.get("ratio", 0.5)
        start = end - timedelta(days=t.get("days", 15))
        for v in cur:
            if v.date > start and v.amount >= cut:
                hit("near_ye_large", v, f"결산일 전 {(end - v.date).days}일, 금액 {won(v.amount)} ≥ 수행중요성 × {t.get('ratio', 0.5)}")
        t["note"] = f"기준 {won(cut)} ({mat['basis']})"
    else:
        t["note"] = "수행중요성이 없어 시험하지 못했습니다"

    # 드문 계정 조합
    t = tests["rare_pair"]
    sig = {}
    for v in cur:
        k = ("+".join(v.codes("dr")), "+".join(v.codes("cr")))
        sig[k] = sig.get(k, 0) + 1
    for v in cur:
        why = []
        k = ("+".join(v.codes("dr")), "+".join(v.codes("cr")))
        if sig[k] <= t.get("max_count", 1):
            why.append(f"차변 {v.label('dr')} / 대변 {v.label('cr')} 조합이 당기 {sig[k]}번")
        for rule in t.get("rules", []):
            ok = True
            if "credit" in rule and not _grp(v, "cr", acc[rule["credit"]]):
                ok = False
            if ok and "debit" in rule and not _grp(v, "dr", acc[rule["debit"]]):
                ok = False
            if ok and "debit_not" in rule:
                drs = [x for x in v.lines if x.dr]
                others = [x for x in drs if not any(x in _grp(v, "dr", acc[g]) for g in rule["debit_not"])]
                ok = bool(others)
            if ok and "without" in rule and _any(v, acc[rule["without"]]):
                ok = False
            if ok and "any_of" in rule:
                ok = any(_any(v, acc[g]) for g in rule["any_of"]) and any(_any(v, acc[g]) for g in rule.get("with", []))
            if ok and ("credit" in rule or "debit" in rule or "any_of" in rule):
                why.append(rule["title"])
        if why:
            hit("rare_pair", v, " · ".join(why))

    # 끝자리 0 반복
    t = tests["round"]
    unit, low = t.get("unit", 10_000_000), t.get("min_amount", 100_000_000)
    for v in cur:
        a = v.amount
        if a >= low and abs(a - round(a)) < 1e-6 and int(round(a)) % unit == 0:
            hit("round", v, f"{won(unit)} 원 단위로 떨어지는 {won(a)}")

    # 적요 없음
    for v in cur + post:
        n = sum(1 for x in v.lines if not x.memo)
        if n:
            hit("no_memo", v, f"적요 빈 행 {n}개")

    # 수기 조정 전표
    t = tests["manual_adjust"]
    cols = [c for c in t.get("columns", []) if c in j["extra_cols"]]
    if cols:
        vals = t.get("values", [])
        for v in cur + post:
            for x in v.lines:
                tag = next((str(x.extra.get(c)) for c in cols if x.extra.get(c) and any(w in str(x.extra.get(c)) for w in vals)), None)
                if tag:
                    hit("manual_adjust", v, f"입력구분 '{tag}'")
                    break
        t["note"] = f"분개장 '{', '.join(cols)}' 열로 판정"
    else:
        start = end - timedelta(days=t.get("days", 15))
        keys = t.get("keywords", [])
        for v in cur:
            if v.date > start:
                k = next((w for w in keys if w in v.memo), None)
                if k:
                    hit("manual_adjust", v, f"적요 낱말 '{k}'")
        t["note"] = "분개장에 입력구분 열이 없어 결산일 근처 적요 낱말로 대신했습니다. 회사 전산에서 수기 전표 목록을 받아 대조해 주십시오"

    # 완전성: 손익계정
    tb = common.tb_rows(d)
    jnet: dict[str, float] = {}
    for x in j["cur"]:
        if x.code is not None:
            jnet[x.code] = jnet.get(x.code, 0.0) + x.dr - x.cr
    comp = []
    for r in tb:
        if r["pl"]:
            comp.append({"code": r["code"], "name": r["name"], "journal": common.reader._int(jnet.get(str(r["code"]), 0.0)), "tb": r["amount"]})
    tb_codes = {str(r["code"]) for r in tb}
    for c, v in sorted(jnet.items()):
        if common.is_pl(c) and c not in tb_codes and abs(v) > 0.5:
            comp.append({"code": c, "name": "(시산표에 없음)", "journal": common.reader._int(v), "tb": 0})
    closing = closing_types(cur, spec, end)
    bs = bs_completeness(d, tb, j["cur"])
    sources = voucher_sources(cur, j["extra_cols"], spec)
    if not j["cur"] and j["failed"]:
        # 분개장 파일은 있는데 판독하지 못했다. 시험 0건을 「해당 없음」 으로 읽지 않게 시험마다 까닭을 적는다(R8)
        why = "; ".join(f"{x['path']} {x['why']}" for x in j["failed"])
        for t in tests.values():
            t["note"] = f"분개장을 판독하지 못해 시험하지 못했습니다({why})"
    return {"tests": list(tests.values()), "completeness": comp, "bs_completeness": bs, "closing": closing, "sources": sources,
            "files": j["files"], "failed": j["failed"],
            "dr": sum(x.dr for x in j["cur"]), "cr": sum(x.cr for x in j["cur"]), "lines": len(j["cur"]),
            "vouchers": len(cur), "post_vouchers": len(post), "mat": mat}


def make(d: Path, ctx: dict | None = None, force: bool = False) -> dict:
    d = Path(d)
    mat = (ctx or {}).get("mat") or common.materiality(d)
    r = run(d, mat)
    b = wp.Book(d, "3600-JET", standard="감사기준서 240 문단 32 · 한공회 3600 부정의 검토 · 분개장 전수")
    ws, row = b.sheet("요약", widths=[30, 14, 18, 18, 18, 40])
    shown = ", ".join(r["files"]) or ("판독 실패" if r["failed"] else "없음")
    if r["failed"]:
        shown += ". 판독 실패: " + "; ".join(f"{x['path']} {x['why']}" for x in r["failed"])
    ws.cell(6, 1, "분개장: " + shown).font = wp.font(size=9, color=wp.MUTED, bold=bool(r["failed"]))

    row = b.section(ws, row, "완전성 1: 당기 분개장 차변 합계 = 대변 합계")
    row = b.head(ws, row, ["항목", "행 수", "차변 합계", "대변 합계", "차이", ""])
    b.put(ws, row, 1, "당기 분개장")
    b.put(ws, row, 2, r["lines"], fmt="#,##0")
    b.put(ws, row, 3, r["dr"], fmt=wp.WON)
    b.put(ws, row, 4, r["cr"], fmt=wp.WON)
    b.put(ws, row, 5, f"=C{row}-D{row}", fmt=wp.WON, flag=abs(r["dr"] - r["cr"]) > 0.5)
    b.verify("분개장 차변 − 대변", f"='요약'!E{row}", r["dr"] - r["cr"])
    row += 2

    row = b.section(ws, row, "완전성 2: 당기 분개장 손익계정 순액 = 회사제시 시산표 (재무상태표 계정은 기초 잔액이 분개장에 없어 대사하지 않는다)")
    row = b.head(ws, row, ["계정", "", "분개장 순액", "시산표", "차이", ""])
    f0 = row
    for c in r["completeness"]:
        b.put(ws, row, 1, f"{c['code']} {c['name']}")
        b.put(ws, row, 3, c["journal"], fmt=wp.WON)
        b.put(ws, row, 4, c["tb"], fmt=wp.WON)
        b.put(ws, row, 5, f"=C{row}-D{row}", fmt=wp.WON, flag=abs(c["journal"] - c["tb"]) > 0.5)
        row += 1
    if r["completeness"]:
        b.put(ws, row, 1, "합계", bold=True)
        for col, L in ((3, "C"), (4, "D"), (5, "E")):
            b.put(ws, row, col, f"=SUM({L}{f0}:{L}{row - 1})", fmt=wp.WON, bold=True)
        b.verify("손익계정 분개장 − 시산표 차이 합", f"='요약'!E{row}", sum(c["journal"] - c["tb"] for c in r["completeness"]))
        b.verify("손익계정 차이 절대값 합", "=" + "+".join(f"ABS('요약'!E{x})" for x in range(f0, row)),
                 sum(abs(c["journal"] - c["tb"]) for c in r["completeness"]))
        row += 1
    row += 1

    row = b.section(ws, row, "시험 (조건은 definitions/jet.yaml)")
    row = b.head(ws, row, ["시험", "전표 수", "금액", "조건", "", "회계사 확인"])
    for t in r["tests"]:
        b.put(ws, row, 1, t["title"], bold=True)
        b.put(ws, row, 2, f"=COUNTIF('결과 목록'!A:A,A{row})", fmt="#,##0")
        b.put(ws, row, 3, f"=SUMIF('결과 목록'!A:A,A{row},'결과 목록'!J:J)", fmt=wp.WON)
        b.put(ws, row, 4, t["condition"] + (f" · {t['note']}" if t["note"] else ""), wrap=True)
        ws.merge_cells(start_row=row, start_column=4, end_row=row, end_column=5)
        ask(b, ws, row, 6, f"확인: {t['title']}")
        ws.row_dimensions[row].height = 45
        b.verify(f"JET {t['title']} 건수", f"='요약'!B{row}", len(t["hits"]))
        b.verify(f"JET {t['title']} 금액", f"='요약'!C{row}", sum(h["voucher"].amount for h in t["hits"]))
        row += 1
    ws.cell(row, 1, "전표 수는 결과 목록의 줄 수다. 한 전표가 여러 시험에 걸리면 시험마다 한 줄이다").font = wp.font(size=9, color=wp.MUTED)
    row += 1
    b.conclusion(ws, row, 6)

    wl, rl = b.sheet("결과 목록", widths=[20, 12, 6, 16, 6, 26, 26, 16, 34, 16, 34, 30])
    rl = b.head(wl, rl, ["시험", "일자", "요일", "전표번호", "줄 수", "차변 계정", "대변 계정", "거래처", "적요", "금액", "근거", "검토 결과"])
    for t in r["tests"]:
        req = t.get("review") == "required"
        for h in t["hits"]:
            v = h["voucher"]
            b.put(wl, rl, 1, t["title"])
            b.put(wl, rl, 2, v.date.isoformat())
            b.put(wl, rl, 3, WEEKDAYS[v.date.weekday()], flag=v.date.weekday() >= 5)
            b.put(wl, rl, 4, v.no)
            b.put(wl, rl, 5, len(v.lines))
            b.put(wl, rl, 6, v.label("dr"), wrap=True)
            b.put(wl, rl, 7, v.label("cr"), wrap=True)
            b.put(wl, rl, 8, ", ".join(v.parties))
            b.put(wl, rl, 9, common.short(v.memo, 60), wrap=True)
            b.put(wl, rl, 10, v.amount, fmt=wp.WON)
            b.put(wl, rl, 11, h["why"], wrap=True, flag=req)
            ask(b, wl, rl, 12, f"검토 결과: {t['id']} {v.date.isoformat()} {v.no}", rule="required" if req else "optional")
            rl += 1
    _bs_sheet(b, r)
    _closing_sheet(b, r)
    out = common.save(b, force=force)
    out["summary"] = {t["id"]: len(t["hits"]) for t in r["tests"]}
    out["run"] = r
    return out


def _bs_sheet(b: wp.Book, r: dict) -> None:
    """완전성 3: 재무상태표 계정 증감 = 차변 발생 − 대변 발생(R9 B3)."""
    bs = r["bs_completeness"]
    ws, row = b.sheet("재무상태표 대사", widths=[26, 18, 18, 18, 18, 16, 30])
    ws.cell(6, 1, "기말(시산표) − 기초(전기 잔액) = 차변 발생 − 대변 발생(당기 분개장). 전기 잔액은 감사받은 숫자 · 회사제시 전기 시산표만 쓴다"
                  "(장부 값은 늘 0 이 되어 쓰지 않는다). 원천: " + (" · ".join(bs["sources"]) or "없음")).font = wp.font(size=9, color=wp.MUTED)
    row = b.section(ws, row, "완전성 3: 재무상태표 계정 (차변 +, 대변 −)")
    row = b.head(ws, row, ["계정", "기초(전기 잔액)", "차변 발생", "대변 발생", "기말(시산표)", "차이", "기초 출처"])
    first = row
    for x in bs["rows"]:
        b.put(ws, row, 1, f"{x['code']} {x['name']}")
        b.put(ws, row, 2, x["open"], fmt=wp.WON)
        b.put(ws, row, 3, x["dr"], fmt=wp.WON)
        b.put(ws, row, 4, x["cr"], fmt=wp.WON)
        b.put(ws, row, 5, x["close"], fmt=wp.WON)
        if x["open"] is None:
            b.put(ws, row, 6, None)
            b.put(ws, row, 7, "전기 잔액 원천 없음(작년 감사 폴더 8800 · 전기조서 8100B · 전기 시산표). 대사하지 못함", wrap=True, flag=True)
        else:
            diff = x["close"] - x["open"] - x["dr"] + x["cr"]
            b.put(ws, row, 6, f"=E{row}-B{row}-C{row}+D{row}", fmt=wp.WON, flag=abs(diff) > 0.5)
            b.put(ws, row, 7, x["basis"], wrap=True)
            b.verify(f"재무상태표 대사 {x['code']} 차이", f"='재무상태표 대사'!F{row}", diff)
        row += 1
    done = [x for x in bs["rows"] if x["open"] is not None]
    if bs["rows"]:
        b.put(ws, row, 1, "차이 합(대사한 계정)", bold=True)
        b.put(ws, row, 6, f"=SUM(F{first}:F{row - 1})", fmt=wp.WON, bold=True)
        b.verify("재무상태표 대사 차이 합", f"='재무상태표 대사'!F{row}", sum(x["close"] - x["open"] - x["dr"] + x["cr"] for x in done))
        row += 1
    ws.cell(row + 1, 1, f"대사한 계정 {len(done)}개 · 원천이 없어 대사하지 못한 계정 {len(bs['rows']) - len(done)}개").font = wp.font(size=9, color=wp.MUTED)


def _closing_sheet(b: wp.Book, r: dict) -> None:
    """결산조정 전표 유형 표와 목록, 전표 출처(입력구분 열)별 건수(R9 B3)."""
    c = r["closing"]
    ws, row = b.sheet("결산조정 전표", widths=[30, 12, 18, 12, 18, 14, 6, 16, 26, 26, 30])
    ws.cell(6, 1, "계정 조합으로 결산조정 전표를 유형별로 나눈다(definitions/jet.yaml closing_types). 분류표다. 이상 여부는 시험 결과 목록과 "
                  "검토 결과 칸에서 본다").font = wp.font(size=9, color=wp.MUTED)
    row = b.section(ws, row, "유형별 건수 · 금액 (당기 전체 · 결산월)")
    row = b.head(ws, row, ["유형", "전표 수", "금액", "결산월 전표 수", "결산월 금액", "", "", "", "", "", ""])
    first = row
    ls = first + len(c["types"]) + 3               # 아래 목록의 첫 줄
    le = ls + max(len(c["rows"]), 1) - 1
    for t in c["types"]:
        b.put(ws, row, 1, t["title"], bold=True)
        b.put(ws, row, 2, f"=COUNTIF($A${ls}:$A${le},A{row})", fmt="#,##0")
        b.put(ws, row, 3, t["amount"], fmt=wp.WON)
        b.put(ws, row, 4, t["ye_count"], fmt="#,##0")
        b.put(ws, row, 5, t["ye_amount"], fmt=wp.WON)
        b.verify(f"결산조정 {t['title']} 전표 수", f"='결산조정 전표'!B{row}", t["count"])
        row += 1
    row += 1
    row = b.section(ws, row, f"결산조정 전표 목록 {len(c['rows'])}건")
    row = b.head(ws, row, ["유형", "일자", "전표번호", "", "금액", "", "요일", "거래처", "차변 계정", "대변 계정", "적요"])
    assert row == ls
    for title, v in c["rows"]:
        b.put(ws, row, 1, title)
        b.put(ws, row, 2, v.date.isoformat())
        b.put(ws, row, 3, v.no)
        b.put(ws, row, 5, v.amount, fmt=wp.WON)
        b.put(ws, row, 7, WEEKDAYS[v.date.weekday()])
        b.put(ws, row, 8, ", ".join(v.parties))
        b.put(ws, row, 9, v.label("dr"), wrap=True)
        b.put(ws, row, 10, v.label("cr"), wrap=True)
        b.put(ws, row, 11, common.short(v.memo, 60), wrap=True)
        row += 1
    row += 1
    src = r.get("sources")
    row = b.section(ws, row, "전표 출처(분개장 입력구분 열)")
    if not src:
        ws.cell(row, 1, "분개장에 입력구분 · 전표구분 열이 없어 수기 · 자동을 가르지 못했습니다. 수기 조정 전표 시험은 적요 낱말로 대신했습니다"
                ).font = wp.font(size=9, color=wp.MUTED)
        return
    row = b.head(ws, row, ["값(" + ", ".join(src["columns"]) + ")", "전표 수", "금액", "구분", "", "", "", "", "", "", ""])
    for e in src["rows"]:
        b.put(ws, row, 1, e["value"])
        b.put(ws, row, 2, e["count"], fmt="#,##0")
        b.put(ws, row, 3, e["amount"], fmt=wp.WON)
        b.put(ws, row, 4, e["kind"], flag=e["kind"] == "수기")
        row += 1
    ws.cell(row, 1, "구분: 값에 수기 · 수동 · 조정 · 결산 낱말이 있으면 수기(definitions/jet.yaml manual_values)").font = wp.font(size=9, color=wp.MUTED)
