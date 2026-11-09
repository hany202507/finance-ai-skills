"""단독 표본 조서: 데이터 파일 하나로 표본 설계 · 추출 · 평가 조서를 만든다(2026-11-09).

감사 폴더(분개장 · 2700A · 영역 대응)가 없어도 된다. 매출 원장 · 세금계산서 목록 · 채권 명세 같은 표 하나와 허용왜곡표시를 받는다.
방법론과 쓰는 법은 이 스킬의 README.md 와 SKILL.md 에 있다.

  scan(data, tm=None, **옵션) -> dict                   뽑기 전에 파일을 읽는다(열 · 기간 · 결산일 어림 · 계층 후보 · 위험 수준별 표본 수). 조서는 만들지 않는다
  make(data, tm, out=None, **옵션) -> 요약 dict         조서를 만들어 저장한다. 같은 파일이 있으면 감사인이 적은 값을 옮긴다
  evaluate(path) -> dict                                 감사인이 적은 왜곡표시로 엔진이 평가한다(엑셀 수식과 같은 값)

방법: mus(금액 단위 표본, 통계) · random(무작위) · systematic(체계적) · specific(특정 항목 선정, 표본감사 아님).
엔진은 선정 · 계산만 한다. 경영진 주장 · 검사 결과 · 왜곡표시 · 평가 · 결론은 감사인 기입란이다.
"""
from __future__ import annotations

import bisect
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.worksheet.datavalidation import DataValidation

from . import dataset, reader, wp
from .workpapers import common, sampling, vouch
from .workpapers import sampling_eval as se
from .workpapers.common import ask

NO = "표본"
WHAT = "모집단"
META = "_표본"
METHODS = ("mus", "random", "systematic", "specific")
ASSERTIONS = ["발생사실", "실재성", "정확성", "기간귀속", "완전성", "권리와 의무", "평가와 배분", "분류"]
KEY_REASON = "고액 기준 이상(전수)"
EXCLUDED_LIST_MAX = 2000
STRATA_MAX = 12                     # scan: 값이 이 수 이하인 글자 열을 계층 후보로 보인다


class SampleError(ValueError):
    pass


# ---------------------------------------------------------------- 표본 단위 · 계층
def _row_unit(r: dict) -> dict:
    return {"key": f"행 {r['row']}", "amount": r["amount"], "date": r["date"], "party": r["party"], "desc": r["desc"],
            "ref": r["ref"], "strata": r["strata"], "src": str(r["row"]), "rows": 1}


def _units(rows: list[dict], group: bool) -> list[dict]:
    """표본 단위. 묶으면 묶을 열 값이 같은 행을 더한다(계층은 그 묶음 첫 행 값, 일자는 마지막 일자)."""
    if not group:
        return [_row_unit(r) for r in rows]
    out: dict[str, dict] = {}
    for r in rows:
        g = r["group"] or "(빈 값)"
        u = out.setdefault(g, {"key": g, "amount": 0.0, "date": None, "party": r["party"], "desc": "", "ref": "",
                               "strata": r["strata"], "src": [], "rows": 0})
        u["amount"] += r["amount"]
        u["rows"] += 1
        u["src"].append(r["row"])
        if r["date"] and (u["date"] is None or r["date"] > u["date"]):
            u["date"] = r["date"]                      # 묶음의 마지막 일자
    for u in out.values():
        src = u["src"]
        u["src"] = f"{src[0]}" if len(src) == 1 else f"{src[0]} 외 {len(src) - 1}행"
    return list(out.values())


def _month_start(d: date, back: int) -> date:
    y, m = d.year, d.month - back
    while m <= 0:
        y, m = y - 1, m + 12
    return date(y, m, 1)


FY_OUT = "사업연도에 들지 않는 일자"


def _net_fy(pop_total: float, excluded: list[dict]) -> float:
    """시산표와 견줄 사업연도 순합계: 모집단 + 금액 0 이하 행(반품 · 에누리). 결산일 뒤 행은 그 사업연도 시산표에 없으므로 뺀다."""
    return pop_total + sum(u["amount"] for u in excluded if u["why"] != FY_OUT)


def _period(fy_end: date | None, tail: int | None):
    """(사업연도 시작, 마지막 기간 시작, 앞 기간 이름, 뒤 기간 이름) 또는 None."""
    if not fy_end:
        return None
    start = date(fy_end.year - 1, fy_end.month, fy_end.day) + timedelta(days=1) if not (fy_end.month == 2 and fy_end.day == 29) \
        else date(fy_end.year - 1, 3, 1)
    if not tail:
        return start, None, None, None
    tail_start = _month_start(fy_end, tail - 1)
    before = tail_start - timedelta(days=1)
    return start, tail_start, f"{start:%Y-%m} ~ {before:%Y-%m}", f"{tail_start:%Y-%m} ~ {fy_end:%Y-%m}"


def _label(u: dict, use_strata: bool, per) -> str:
    parts = []
    if use_strata:
        parts.append((u["strata"] or "(빈 값)").replace("*", "＊").replace("?", "？"))
    if per and per[1]:
        parts.append("(일자 없음)" if not u["date"] else (per[3] if u["date"] >= per[1] else per[2]))
    return " · ".join(parts) or "전체"


# ---------------------------------------------------------------- 선정
def _select(pop: list[dict], method: str, plan: dict, key: float | None, opt: dict, seed: int, fy_end: date | None) -> dict:
    """선정 결과 {selected, strata, key_threshold, planned, points}. strata 는 계층마다 요약."""
    labels = sorted({u["stratum"] for u in pop})
    J = plan["interval"]
    strata = {lab: {"label": lab, "total": 0.0, "count": 0, "key_count": 0, "key_total": 0.0, "rest": 0.0, "rest_count": 0,
                    "planned": 0, "picked": 0, "points": 0, "seed": seed + i} for i, lab in enumerate(labels)}
    for u in pop:
        s = strata[u["stratum"]]
        s["total"] += u["amount"]
        s["count"] += 1
    selected: list[dict] = []
    if method == "specific":
        crit = []
        if key:
            crit.append(("금액 기준 이상", lambda u: u["amount"] >= key))
        if opt.get("top"):
            top = {id(u) for u in sorted(pop, key=lambda u: -u["amount"])[: int(opt["top"])]}
            crit.append((f"금액 상위 {int(opt['top'])}", lambda u, top=top: id(u) in top))
        if opt.get("window") is not None:
            if not fy_end:
                raise SampleError("결산일 전후 선정(--window)은 --fy-end 가 있어야 합니다")
            w = int(opt["window"])
            crit.append((f"결산일 전후 {w}일", lambda u: bool(u["date"]) and abs((u["date"] - fy_end).days) <= w))
        if not crit:
            raise SampleError("특정 항목 선정은 --key · --top · --window 가운데 하나 이상이 있어야 합니다")
        for u in pop:
            hit = [name for name, f in crit if f(u)]
            if hit:
                selected.append({**u, "reason": " · ".join(hit), "hits": None, "cum": None, "key_item": False})
                strata[u["stratum"]]["picked"] += 1
        return {"selected": selected, "strata": list(strata.values()), "key_threshold": key, "planned": len(selected), "points": None}

    K = min(key, J) if key else J
    keys = [u for u in pop if u["amount"] >= K]
    for u in keys:
        s = strata[u["stratum"]]
        s["key_count"] += 1
        s["key_total"] += u["amount"]
        selected.append({**u, "reason": KEY_REASON, "hits": None, "cum": None, "key_item": True})
    rest = [u for u in pop if u["amount"] < K]
    for u in rest:
        strata[u["stratum"]]["rest"] += u["amount"]
        strata[u["stratum"]]["rest_count"] += 1
    by_key = {}
    points = 0
    if method == "mus":
        for lab in labels:
            s = strata[lab]
            items = [(u["key"], u["amount"]) for u in rest if u["stratum"] == lab]
            if not items:
                continue
            by_key.update({u["key"]: u for u in rest if u["stratum"] == lab})
            m = sampling.mus(items, plan["tolerable"], plan["risk_level"], s["seed"], plan["factor_in"], plan["expected"])
            s["planned"] = m["size"]
            for r in m["selected"]:
                u = by_key[r["key"]]
                selected.append({**u, "reason": "간격 선정", "hits": r["hits"], "cum": r["cum"], "key_item": False})
                s["picked"] += 1
                s["points"] += r["hits"]
                points += r["hits"]
        planned = sum(s["planned"] for s in strata.values())
    else:
        rest_total = sum(u["amount"] for u in rest)
        n = int(opt["size"]) if opt.get("size") else common.ceil(rest_total / J) if rest_total > 0 else 0
        alloc = sampling.allocate(n, [strata[lab]["rest"] for lab in labels])
        for lab, k in zip(labels, alloc):
            s = strata[lab]
            s["planned"] = k
            pool = [u for u in rest if u["stratum"] == lab]
            if not pool or k <= 0:
                continue
            by = {u["key"]: u for u in pool}
            f = sampling.random_sample if method == "random" else sampling.systematic
            m = f([(u["key"], u["amount"]) for u in pool], k, s["seed"])
            for r in m["selected"]:
                selected.append({**by[r["key"]], "reason": "무작위" if method == "random" else "체계적", "hits": None, "cum": None,
                                 "key_item": False})
                s["picked"] += 1
        planned = n
    return {"selected": selected, "strata": list(strata.values()), "key_threshold": K, "planned": planned, "points": points}


# ---------------------------------------------------------------- 앞 판 기입값
def _old(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return {x["label"]: x["value"] for x in wp.readback(path) if not wp._blank(x["value"])}
    except Exception:  # noqa: BLE001  엔진이 만들지 않은 파일
        return {}


def _num(v):
    if v in (None, ""):
        return None
    try:
        return float(str(v).replace(",", ""))
    except ValueError:
        return None


def _resolve(opt: dict, old: dict) -> dict:
    """위험 수준 · 신뢰계수 · 예상 왜곡표시: 명령 옵션 → 조서 기입란 → sampling.yaml 기본값."""
    st = sampling.settings()
    risk, src = opt.get("risk"), "명령 --risk"
    factor = opt.get("factor")
    if factor:
        src = "명령 --factor"
    if not risk and not factor:
        r = str(old.get(f"위험 수준 확인: {WHAT}") or "").strip()
        f = _num(old.get(f"신뢰계수 직접 입력: {WHAT}"))
        if r in st["risk_levels"]:
            risk, src = r, "조서 「위험 수준 확인」"
        if f and f > 0:
            factor, src = f, "조서 「신뢰계수 직접 입력」"
    if not risk and not factor:
        risk, src = st["default_risk"], "초기값(sampling.yaml default_risk). 감사인이 위험 수준을 확인해야 함"
    expected = opt.get("expected")
    if expected is None:
        expected = _num(old.get(f"예상 왜곡표시 직접 입력: {WHAT}")) or 0.0
    return {"risk": risk, "factor": factor, "expected": float(expected or 0), "source": src}


def _fy_guess(dates: list) -> tuple:
    """결산일 어림: 날짜가 가장 많이 드는 12개월의 마지막 달 말일(같으면 12월, 그다음 늦은 달). (결산일, 그 사업연도에 드는 행 수)."""
    if not dates:
        return None, 0
    ds = sorted(dates)
    best = None
    y, m = ds[0].year, ds[0].month
    while (y, m) <= (ds[-1].year, ds[-1].month):
        end = date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1)
        start = _period(end, None)[0]
        n = bisect.bisect_right(ds, end) - bisect.bisect_left(ds, start)
        k = (n, end.month == 12, end)
        if best is None or k > best[0]:
            best = (k, end, n)
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return best[1], best[2]


def scan(data: Path, tm: float | None = None, **opt) -> dict:
    """뽑기 전에 데이터 파일을 읽는다(2026-11-09). 조서는 만들지 않는다.
    AI 가 감사인에게 무엇을 물을지 정하는 데 쓰는 사실만 낸다: 읽은 열과 다른 숫자 열, 금액 0 이하 행, 일자 범위와 결산일 어림,
    계층 후보(값이 2 ~ STRATA_MAX 개인 글자 열), 거래처 수, 금액 상위 비중, 허용왜곡표시를 주면 위험 수준별 간격 · 점 수.
    결산일 · 계층 · 묶기 전 어림이고, 고르는 일(허용왜곡표시 · 위험 수준 · 계층 · 방법)은 감사인이 한다."""
    data = Path(data)
    cols = {k: opt.get(k) for k in dataset.ROLES}
    try:
        ds = dataset.read(data, opt.get("sheet"), cols, raw=True)
    except dataset.DataError as e:
        raise SampleError(str(e)) from None
    rows, raws, idx, heads = ds["rows"], ds["raw"], ds["idx"], ds["headers"]
    pos = [r for r in rows if r["amount"] > 0]
    nonpos = [r for r in rows if r["amount"] <= 0]
    pos_total = sum(r["amount"] for r in pos)
    dates = [r["date"] for r in rows if r["date"]]
    fy, fy_in = _fy_guess(dates)
    fy_start = _period(fy, None)[0] if fy else None
    net_fy = sum(r["amount"] for r in rows if not fy or not r["date"] or fy_start <= r["date"] <= fy)   # 시산표와 견줄 금액(어림 결산일 기준)
    skip = {idx[k] for k in ("amount", "date", "ref", "party") if k in idx}
    numeric, strata = [], []
    for i, h in enumerate(heads):
        if i in skip or not h:
            continue
        vals = [x[i] if i < len(x) else None for x in raws]
        filled = [v for v in vals if v not in (None, "")]
        if not filled or any(isinstance(v, (date, datetime)) for v in filled[:50]):
            continue
        if sum(1 for v in filled if reader._num(v) is not None) >= 0.8 * len(filled):
            numeric.append(h)                     # 세액 · 합계금액 같은 다른 금액 열. 금액 열을 맞게 잡았는지 감사인이 본다
            continue
        if len(filled) < 0.9 * len(vals):
            continue
        groups: dict = {}
        for v, r in zip(vals, rows):
            t = dataset._text(v)
            if t:
                g = groups.setdefault(t, [0, 0.0])
                g[0] += 1
                g[1] += r["amount"] if r["amount"] > 0 else 0
        if 2 <= len(groups) <= STRATA_MAX:
            strata.append({"col": h, "values": [{"value": k, "count": c, "total": t}
                                                for k, (c, t) in sorted(groups.items(), key=lambda kv: -kv[1][1])]})
    party = None
    if "party" in idx:
        names = Counter(r["party"] for r in pos if r["party"])
        party = {"col": ds["cols"]["party"], "distinct": len(names), "repeat": sum(1 for c in names.values() if c > 1)}
    big = sorted(pos, key=lambda r: -r["amount"])
    s = sampling.settings()
    sizes = []
    if tm:
        for lv in sorted(s["risk_levels"], key=lambda k: -float(s["risk_levels"][k]["factor"])):   # 높음부터
            try:
                p = sampling.plan(pos_total, len(pos), tm, lv)
            except ValueError as e:
                raise SampleError(str(e)) from None
            sizes.append({"risk": lv, "confidence": p["confidence"], "factor": p["factor"], "interval": p["interval"],
                          "points": p["size"], "key_items": sum(1 for r in pos if r["amount"] >= p["interval"])})
    return {"path": str(data), "file": data.name, "sheet": ds["sheet"], "header_row": ds["header_row"],
            "headers": [h for h in heads if h], "cols": ds["cols"], "rows": len(rows), "skipped": ds["skipped"],
            "positive": {"count": len(pos), "total": pos_total},
            "nonpositive": {"count": len(nonpos), "total": sum(r["amount"] for r in nonpos)},
            "dates": {"min": min(dates) if dates else None, "max": max(dates) if dates else None, "missing": len(rows) - len(dates)},
            "fy_end_guess": fy, "outside_guess": len(dates) - fy_in, "net_fy_guess": net_fy,
            "other_numeric": numeric, "strata_candidates": strata,
            "party": party, "top": [{"row": r["row"], "party": r["party"], "amount": r["amount"]} for r in big[:5]],
            "top10_share": (sum(r["amount"] for r in big[:10]) / pos_total) if pos_total else 0.0,
            "default_risk": s["default_risk"], "risk_levels": list(s["risk_levels"]), "assertions": ASSERTIONS,
            "tm": tm, "sizes": sizes, "sha": ds["sha"]}


# ---------------------------------------------------------------- 만들기
def make(data: Path, tm: float, out: Path | None = None, **opt) -> dict:
    data = Path(data)
    method = opt.get("method") or "mus"
    if method not in METHODS:
        raise SampleError(f"방법은 {', '.join(METHODS)} 가운데 하나입니다: {method}")
    if not tm or tm <= 0:
        raise SampleError("허용왜곡표시(--tm)가 0 보다 커야 합니다")
    cols = {k: opt.get(k) for k in dataset.ROLES}
    try:
        ds = dataset.read(data, opt.get("sheet"), cols)
    except dataset.DataError as e:
        raise SampleError(str(e)) from None
    if opt.get("strata") and "strata" not in ds["cols"]:
        raise SampleError(f"계층 열 「{opt['strata']}」 을 찾지 못했습니다")
    out = Path(out) if out else data.parent / f"표본_{data.stem}.xlsx"
    old = _old(out)
    rv = _resolve(opt, old)
    fy_end = opt.get("fy_end")
    if isinstance(fy_end, str) and fy_end:
        fy_end = date.fromisoformat(fy_end)
    tail = opt.get("tail_months")
    if tail and not fy_end:
        raise SampleError("기간 계층(--tail-months)은 --fy-end 가 있어야 합니다")
    per = _period(fy_end, tail)
    seed = int(opt["seed"]) if opt.get("seed") is not None else int(sampling.settings()["seed"])

    # 사업연도에 들지 않는 일자는 행마다 먼저 뺀다(묶기 전에. 거래처 하나에 결산일 뒤 거래가 섞여도 그 거래처 전체가 빠지지 않게)
    rows_in, excluded = [], []
    for r in ds["rows"]:
        if per and r["date"] and not (per[0] <= r["date"] <= fy_end):
            excluded.append({**_row_unit(r), "why": FY_OUT})
        else:
            rows_in.append(r)
    units = _units(rows_in, bool(opt.get("group")))
    pop = []
    for u in units:
        if u["amount"] <= 0:
            excluded.append({**u, "why": "금액 0 이하(반품 · 에누리 · 역분개)" if u["rows"] == 1 else "묶은 순액 0 이하"})
        else:
            pop.append(u)
    if not pop:
        raise SampleError("금액이 0 보다 큰 항목이 없어 표본을 뽑을 수 없습니다")
    for u in pop:
        u["stratum"] = _label(u, bool(opt.get("strata")), per)
    pop_total = sum(u["amount"] for u in pop)
    try:
        p = sampling.plan(pop_total, len(pop), tm, rv["risk"], rv["factor"], rv["expected"])
    except ValueError as e:
        raise SampleError(str(e)) from None
    p["risk_level"], p["factor_in"] = rv["risk"], rv["factor"]
    p["confidence_used"] = p["confidence"] or se.confidence_of(p["factor"])
    key = _num(opt.get("key"))
    sel = _select(pop, method, p, key, opt, seed, fy_end)
    if not sel["selected"]:
        raise SampleError("고른 항목이 없습니다. 선정 기준이나 표본 수를 확인해 주십시오")

    b = wp.Book(out.parent, NO, title=opt.get("title") or "표본 조서", standard="감사기준서 530 표본감사 · 500 문단 A64 ~ A66")
    b.company = opt.get("company") or ""
    b.fy_end = fy_end.isoformat() if fy_end else ""
    ctx = {"ds": ds, "method": method, "plan": p, "sel": sel, "pop": pop, "pop_total": pop_total, "excluded": excluded, "rv": rv,
           "seed": seed, "per": per, "opt": opt, "tm": float(tm)}
    _design_sheet(b, ctx)
    _sample_sheet(b, ctx)
    _excluded_sheet(b, ctx)
    if opt.get("full"):
        _population_sheet(b, ctx)
    _meta(b, ctx)
    res = common.save(b, force=bool(opt.get("force")), path=out)
    key_items = [r for r in sel["selected"] if r["key_item"]]
    by_why: dict = {}
    for u in excluded:                                   # 까닭별 건수 · 금액(음수 행과 결산일 뒤 행을 한 금액으로 더하면 읽기 어렵다)
        w = by_why.setdefault(u["why"], {"count": 0, "total": 0.0})
        w["count"] += 1
        w["total"] += u["amount"]
    return {"path": res["path"], "method": method, "file": ds["path"].name, "sheet": ds["sheet"], "cols": ds["cols"],
            "rows": len(ds["rows"]), "skipped": ds["skipped"], "units": len(units), "pop_count": len(pop), "pop_total": pop_total,
            "excluded": len(excluded), "excluded_total": sum(u["amount"] for u in excluded), "excluded_by": by_why,
            "net_fy": _net_fy(pop_total, excluded), "control": _num(opt.get("control")),
            "control_diff": (_net_fy(pop_total, excluded) - _num(opt.get("control"))) if _num(opt.get("control")) is not None else None,
            "interval": p["interval"],
            "factor": p["factor"], "confidence": p["confidence_used"], "risk": p["risk"], "risk_source": rv["source"],
            "expected": p["expected"], "ef": p["ef"], "key_threshold": sel["key_threshold"], "key_items": len(key_items),
            "selected": len(sel["selected"]), "planned": sel["planned"], "points": sel["points"], "seed": seed,
            "strata": [{k: s[k] for k in ("label", "total", "count", "key_count", "planned", "picked")} for s in sel["strata"]],
            "carried": res["carried"], "moved": res["moved"], "lost": res["lost"]}


def _row(b, ws, row: int, label: str, value, fmt=None, flag=False, note: str | None = None) -> int:
    ws.cell(row, 1, label).font = wp.font(color=wp.MUTED)
    b.put(ws, row, 2, value, fmt=fmt, wrap=fmt is None, flag=flag)
    if note:
        ws.cell(row, 3, note).font = wp.font(size=9, color=wp.MUTED)
    return row + 1


def _design_sheet(b, ctx: dict) -> None:
    from .workpapers.lead import risk_inputs, sampling_guide

    ds, p, sel, opt = ctx["ds"], ctx["plan"], ctx["sel"], ctx["opt"]
    method = ctx["method"]
    mdef = sampling.settings()["methods"][method]
    ws, row = b.sheet("설계", [44, 26, 80, 14, 14, 16, 14, 14, 10])
    ws.cell(6, 1, "데이터 파일 하나로 만든 표본 조서(python -m audit sample make). 표본 설계 → 추출 → 검사 → 평가 순서다(감사기준서 530 문단 6 ~ 15). "
                  "흰 칸은 엔진 값, 노란 칸은 감사인 기입란이다").font = wp.font(size=9, color=wp.MUTED)

    row = b.section(ws, row, "1. 목적과 모집단 (감사기준서 530 문단 6 · 8, A4 ~ A9)")
    ws.cell(row, 1, "테스트 목적 · 경영진 주장").font = wp.font(color=wp.MUTED)
    c = ask(b, ws, row, 2, "테스트 목적 · 경영진 주장", value=opt.get("assertion"))
    dv = DataValidation(type="list", formula1='"' + ",".join(ASSERTIONS) + '"', allow_blank=True, showErrorMessage=False)
    ws.add_data_validation(dv)
    dv.add(c.coordinate)
    ws.cell(row, 3, "목록에서 고르거나 직접 적는다. 완전성은 장부가 아닌 자료(출고 · 수주 · 계약)에서 모집단을 뽑아야 한다(500 문단 A31)").font = \
        wp.font(size=9, color=wp.MUTED)
    row += 1
    row = _row(b, ws, row, "데이터 파일", ds["path"].name, note=str(ds["path"]))
    row = _row(b, ws, row, "시트 · 머리줄", f"{ds['sheet']} · {ds['header_row']}행")
    roles = " · ".join(f"{dataset.ROLE_NAMES[k]} 「{v}」" for k, v in ds["cols"].items())
    row = _row(b, ws, row, "읽은 열", roles, note="열 이름을 자동으로 찾았다. 다르면 --amount · --date · --party 로 열 이름을 준다")
    row = _row(b, ws, row, "파일 해시(SHA-256 앞 12자리)", ds["sha"], note="같은 파일 · 같은 시드면 같은 표본이 나온다. 회사가 파일을 바꾸면 이 값이 달라진다")
    unit = f"「{ds['cols']['group']}」 이 같은 행을 더한 합계(묶음 하나가 표본 단위)" if opt.get("group") else "행(거래 한 줄)"
    row = _row(b, ws, row, "표본 단위(문단 5(f), A2)", unit)
    row = _row(b, ws, row, "읽은 데이터 행 수", len(ds["rows"]), "#,##0")
    sk = ds["skipped"]
    row = _row(b, ws, row, "뺀 행: 합계 · 소계 행 / 금액이 숫자가 아닌 행", f"{sk['합계 행']:,} / {sk['금액 없음']:,}")
    out_fy = [u for u in ctx["excluded"] if u["why"] == FY_OUT]
    neg = [u for u in ctx["excluded"] if u["why"] != FY_OUT]
    row = _row(b, ws, row, "모집단에서 뺀 항목: 금액 0 이하(건수 · 금액)", f"{len(neg):,}건 · {sum(u['amount'] for u in neg):,.0f}원", flag=bool(neg),
               note="반품 · 에누리 · 역분개. 따로 검토한다(「모집단에서 뺀 항목」 시트)" if neg else None)
    if ctx["per"]:
        row = _row(b, ws, row, "모집단에서 뺀 항목: 사업연도에 들지 않는 일자(건수 · 금액)", f"{len(out_fy):,}건 · {sum(u['amount'] for u in out_fy):,.0f}원",
                   flag=bool(out_fy), note="결산일 뒤 거래는 기간귀속(Cut-off) 절차에서 본다" if out_fy else None)
    row = _row(b, ws, row, "모집단 항목 수", len(ctx["pop"]), "#,##0")
    pop_row = row
    row = _row(b, ws, row, "모집단 금액", ctx["pop_total"], wp.WON)
    net_row = row
    row = _row(b, ws, row, "사업연도 순합계(반품 · 0 이하 포함, 결산일 뒤 제외)", _net_fy(ctx["pop_total"], ctx["excluded"]), wp.WON)
    ws.cell(row, 1, "시산표 · 원장 금액(대사, 문단 A5 · 500 문단 9)").font = wp.font(color=wp.MUTED)
    ctl = f"B{row}"
    ask(b, ws, row, 2, "시산표 · 원장 금액", rule="optional", value=opt.get("control"), fmt=wp.WON)
    ws.cell(row, 3, "모집단이 완전한지 시산표 · 계정별원장 금액과 맞춘다. 대사가 맞아야 표본 결과를 그 계정에 대한 근거로 쓸 수 있다").font = \
        wp.font(size=9, color=wp.MUTED)
    row += 1
    ws.cell(row, 1, "대사 차이 = 사업연도 순합계 − 시산표 · 원장 금액").font = wp.font(color=wp.MUTED)
    b.put(ws, row, 2, f'=IF(ISNUMBER({ctl}),B{net_row}-{ctl},"금액을 적으면 계산")', fmt=wp.WON)
    row += 1
    ws.cell(row, 1, "대사 차이 설명").font = wp.font(color=wp.MUTED)
    ask(b, ws, row, 2, "대사 차이 설명", rule="optional")
    row += 2
    b.verify("표본 모집단 금액", f"='설계'!B{pop_row}", ctx["pop_total"])

    row = b.section(ws, row, "2. 표본 크기와 추출 방법 (문단 7 · 8, A10 ~ A13, 보론 2 · 4)")
    row = _row(b, ws, row, "추출 방법", f"{mdef['name']} · {mdef['kind']}")
    row = _row(b, ws, row, "허용왜곡표시(수행중요성)", ctx["tm"], wp.WON)
    ws.cell(row, 1, "허용왜곡표시 근거").font = wp.font(color=wp.MUTED)
    ask(b, ws, row, 2, "허용왜곡표시 근거", rule="optional")
    ws.cell(row, 3, "2700A 수행중요성, 또는 이 계정에 따로 정한 허용왜곡표시").font = wp.font(size=9, color=wp.MUTED)
    row += 1
    default = ctx["rv"]["source"].startswith("초기값")
    row = _row(b, ws, row, "적용 위험 수준", f"{p['risk']} ({ctx['rv']['source']})", flag=default,
               note="매출은 수익인식 부정위험 추정(감사기준서 240 문단 27)으로 유의적 위험이라 「높음」 을 권한다" if default else None)
    row = _row(b, ws, row, "신뢰수준", p["confidence_used"], wp.PCT)
    row = _row(b, ws, row, "신뢰계수 = −ln(1 − 신뢰수준)", p["factor"], "0.00")
    row = _row(b, ws, row, "예상 왜곡표시", p["expected"], wp.WON)
    row = _row(b, ws, row, "확장계수(잘못된 수용 위험별 표)", p["ef"] or None, "0.00")
    row = _row(b, ws, row, "표본 간격 = (허용왜곡표시 − 예상 왜곡표시 × 확장계수) ÷ 신뢰계수", p["interval"], wp.WON,
               note=None if method == "mus" else "비통계 표본도 같은 식으로 표본 수를 정했다(문단 A11: 같은 상황이면 통계 · 비통계 표본 규모가 비슷하다)")
    K = sel["key_threshold"]
    keys = [r for r in sel["selected"] if r["key_item"]]
    if method == "specific":
        row = _row(b, ws, row, "선정 기준", " · ".join(sorted({r["reason"] for r in sel["selected"]})) or "-")
        row = _row(b, ws, row, "고른 항목 수 · 금액", f"{len(sel['selected']):,}건 · {sum(r['amount'] for r in sel['selected']):,.0f}원")
    else:
        row = _row(b, ws, row, "고액 기준(전수 검사, 투영 안 함)", K, wp.WON,
                   note="감사인이 --key 로 낮출 수 있다(표본 간격보다 크게는 못 잡는다)" if not ctx["opt"].get("key") else "감사인이 정한 기준(표본 간격 이하)")
        row = _row(b, ws, row, "고액 항목 수 · 금액", f"{len(keys):,}건 · {sum(r['amount'] for r in keys):,.0f}원")
        rest = sum(s["rest"] for s in sel["strata"])
        row = _row(b, ws, row, "표본 대상 금액(고액 뺌) · 항목 수", f"{rest:,.0f}원 · {sum(s['rest_count'] for s in sel['strata']):,}건")
        if method == "mus":
            row = _row(b, ws, row, "계획 표본 수 = 계층마다 올림(표본 대상 금액 ÷ 표본 간격)의 합", sel["planned"], "#,##0")
            row = _row(b, ws, row, "실제로 찍힌 점 수 · 고른 항목 수(고액 제외)",
                       f"{sel['points']:,} · {sum(1 for r in sel['selected'] if not r['key_item']):,}",
                       note="점은 시작점부터 간격마다 찍혀 계층 끝을 넘으면 멈춘다. 그래서 계획 수보다 적을 수 있다")
        else:
            row = _row(b, ws, row, "표본 수" + (" (감사인이 정함)" if ctx["opt"].get("size") else " = 올림(표본 대상 금액 ÷ 표본 간격)"),
                       sel["planned"], "#,##0", note="계층마다 표본 대상 금액에 비례해 나눴다(금액이 있는 계층은 적어도 1개)")
    row = _row(b, ws, row, "시드(계층마다 시드 + 순번)", ctx["seed"], "0", note="같은 시드면 같은 표본이다. 원하는 표본이 나올 때까지 시드를 바꾸지 않는다")
    row = risk_inputs(b, ws, row, WHAT, cmd=f"python -m audit sample make {ds['path'].name} --tm …")
    ws.cell(row, 3, "명령 옵션(--risk · --factor · --expected)이 위 기입란보다 앞선다").font = \
        wp.font(size=9, color=wp.MUTED)
    row += 2

    row = b.section(ws, row, "3. 계층 (문단 A8, 보론 1)")
    ws.cell(row, 1, "계층마다 같은 표본 간격으로 뽑아 표본 수가 계층 금액에 비례한다. 평가는 계층을 합쳐 한 번 한다" if method != "specific"
            else "특정 항목 선정은 계층을 나누지 않는다. 참고로 계층별 금액을 보인다").font = wp.font(size=9, color=wp.MUTED)
    row = b.head(ws, row + 1, ["계층", "모집단 금액", "항목 수", "고액 항목 수", "고액 금액", "표본 대상 금액", "표본 수(계획)", "고른 항목 수", "시드"])
    for s in sel["strata"]:
        for i, (v, f) in enumerate([(s["label"], None), (s["total"], wp.WON), (s["count"], "#,##0"), (s["key_count"], "#,##0"),
                                    (s["key_total"], wp.WON), (s["rest"], wp.WON), (s["planned"], "#,##0"), (s["picked"], "#,##0"),
                                    (s["seed"], "0")], 1):
            b.put(ws, row, i, v, fmt=f, wrap=f is None)
        row += 1
    row += 1

    row = b.section(ws, row, "4. 표본 수 근거")
    ws.merge_cells(start_row=row, start_column=2, end_row=row, end_column=6)
    ws.cell(row, 1, "엔진이 쓴 근거").font = wp.font(color=wp.MUTED)
    b.put(ws, row, 2, _basis_sentence(ctx), wrap=True)
    ws.row_dimensions[row].height = 75
    row += 1
    ws.cell(row, 1, "감사인 추가 근거").font = wp.font(color=wp.MUTED)
    ask(b, ws, row, 2, "표본 수 추가 근거", rule="optional")
    ws.cell(row, 3, "위험 수준 · 예상 왜곡표시를 고른 까닭, 다른 절차(분석적 검토 · 통제테스트)에서 얻은 확신").font = wp.font(size=9, color=wp.MUTED)
    row += 2
    sampling_guide(b, ws, row)


def _basis_sentence(ctx: dict) -> str:
    p, sel, method = ctx["plan"], ctx["sel"], ctx["method"]
    head = (f"모집단 {len(ctx['pop']):,}건 {ctx['pop_total']:,.0f}원. 허용왜곡표시 {ctx['tm']:,.0f}원, 예상 왜곡표시 {p['expected']:,.0f}원, "
            f"위험 {p['risk']}(신뢰수준 {p['confidence_used']:.1%}, 신뢰계수 {p['factor']:.2f}"
            + (f", 확장계수 {p['ef']:.2f}" if p["ef"] else "") + f"). 표본 간격 {p['interval']:,.0f}원. ")
    keys = [r for r in sel["selected"] if r["key_item"]]
    if method == "specific":
        return (f"특정 항목 선정(표본감사 아님, 감사기준서 500 문단 A65): {', '.join(sorted({r['reason'] for r in sel['selected']}))} 기준으로 "
                f"{len(sel['selected']):,}건 {sum(r['amount'] for r in sel['selected']):,.0f}원을 골랐다. 결과는 투영하지 않고, "
                f"선정하지 않은 나머지 {ctx['pop_total'] - sum(r['amount'] for r in sel['selected']):,.0f}원은 다른 절차로 본다(문단 A66).")
    tail = (f"고액 기준 {sel['key_threshold']:,.0f}원 이상 {len(keys):,}건은 전수 검사하고, 나머지에서 ")
    if method == "mus":
        tail += f"금액 단위로 {sel['points']:,}점을 찍어 {sum(1 for r in sel['selected'] if not r['key_item']):,}건을 골랐다."
    else:
        tail += f"{'무작위로' if method == 'random' else '체계적으로'} {sum(1 for r in sel['selected'] if not r['key_item']):,}건을 골랐다(계층마다 금액 비례)."
    return head + tail


def _pre_cols(ctx: dict) -> list[tuple]:
    pre = [("계층", lambda r: (r["stratum"], False)),
           ("일자", lambda r: (r["date"].isoformat() if r["date"] else "", False)),
           ("거래처", lambda r: (r["party"], False)),
           ("적요", lambda r: (r["desc"], False)),
           ("원본 행", lambda r: (r["src"], False))]
    if ctx["opt"].get("group"):
        pre.append(("묶은 행 수", lambda r: (r["rows"], False)))
    return pre


def _sample_sheet(b, ctx: dict) -> None:
    sel, p, method = ctx["sel"], ctx["plan"], ctx["method"]
    pre = _pre_cols(ctx)
    ws, row = b.sheet("표본", vouch.widths(16, pre=len(pre)))
    ws.cell(6, 1, "검사 항목: √ 일치 · ✗ 다름 · 해당 없음 가운데 고른다. 다름이 있으면 검사 결과에 차이와 처리를 적고, 왜곡표시 금액(장부 − 확인 금액, 과대계상 양수)을 숫자로 적는다").font = \
        wp.font(size=9, color=wp.MUTED)
    rows = sorted(sel["selected"], key=lambda r: (not r["key_item"], r["stratum"], r.get("cum") or 0))
    row = b.section(ws, row, f"선정 항목 {len(rows):,}개 ({sampling.settings()['methods'][method]['name']})")
    row, first = vouch.table(b, ws, row, rows, "항목", [], lambda r: [], pre=pre, reason=lambda r: r["reason"])
    last = row - 1
    b.verify("표본 금액 합", f"=SUM('표본'!C{first}:C{last})", sum(r["amount"] for r in rows))
    row += 1
    if method == "mus":
        s = {"interval": p["interval"], "key_threshold": sel["key_threshold"], "factor": p["factor"], "confidence": p["confidence_used"],
             "tolerable": ctx["tm"], "selected": True, "method": "금액 단위 표본(MUS)"}
        row, refs = vouch.eval_numbers(b, ws, row, s, first, last, "표본 결과 수치 (감사기준서 530 문단 14)")
        row = vouch.eval_conclude(b, ws, row, [refs], ctx["tm"], WHAT)
    elif method in ("random", "systematic"):
        row = _eval_ratio(b, ws, row, ctx, first, last)
    else:
        row = _eval_specific(b, ws, row, ctx, first, last)
    b.conclusion(ws, row, 8)


def _counts(b, ws, row: int, first: int, last: int) -> tuple[int, dict]:
    from openpyxl.utils import get_column_letter as L

    c = b.sample_cols
    E, R, K = L(c["err"]), L(c["result"]), L(c["check"])
    err = f"{E}{first}:{E}{last}"
    refs = {"err": E}
    for key, lab, val, fmt in [("pending", "검사 결과가 빈 항목", f"=COUNTBLANK({R}{first}:{R}{last})", "#,##0"),
                               ("nodiff", "금액 대사가 「✗ 다름」 인데 왜곡표시 금액이 빈 항목", f'=COUNTIFS({K}{first}:{K}{last},"{vouch.CHOICES[1]}",{err},"")', "#,##0"),
                               ("found", "표본에서 찾은 왜곡표시(순액)", f"=SUM({err})", wp.WON)]:
        ws.cell(row, 1, lab).font = wp.font(color=wp.MUTED)
        b.put(ws, row, 2, val, fmt=fmt)
        refs[key] = f"B{row}"
        row += 1
    return row, refs


def _verdict_tail(b, ws, row: int, formula: str) -> int:
    ws.cell(row, 1, "허용왜곡표시와 견줌").font = wp.font(color=wp.MUTED)
    b.put(ws, row, 2, formula, wrap=True)
    ws.merge_cells(start_row=row, start_column=2, end_row=row, end_column=6)
    ws.row_dimensions[row].height = 45
    row += 1
    ws.cell(row, 1, "평가(왜곡표시의 성격 · 원인, 다른 분야 영향, 모집단 결론)").font = wp.font(color=wp.MUTED)
    ask(b, ws, row, 2, f"표본 결과 평가: {WHAT}")
    ws.row_dimensions[row].height = 45
    return row + 1


def _eval_ratio(b, ws, row: int, ctx: dict, first: int, last: int) -> int:
    """비통계 표본(무작위 · 체계적): 계층마다 (표본 왜곡 합 ÷ 표본 장부 합) × 표본 대상 금액. 고액 왜곡은 그대로. 엔진 계산은 sampling_eval.ratio."""
    row = b.section(ws, row, "표본 결과 수치 (감사기준서 530 문단 14, 비율 투영)")
    row, refs = _counts(b, ws, row, first, last)
    E = refs["err"]
    A, F, G = f"$C${first}:$C${last}", f"$F${first}:$F${last}", f"$G${first}:$G${last}"     # 금액 · 선정 이유 · 계층
    err = f"${E}${first}:${E}${last}"
    row = b.head(ws, row + 1, ["계층", "표본 대상 금액(고액 뺌)", "표본 장부 금액", "표본 왜곡: 과대", "표본 왜곡: 과소", "투영: 과대", "투영: 과소"])
    top = row
    for s in ctx["sel"]["strata"]:
        b.put(ws, row, 1, s["label"], wrap=True)
        b.put(ws, row, 2, s["rest"], fmt=wp.WON)
        b.put(ws, row, 3, f'=SUMIFS({A},{G},A{row},{F},"<>{KEY_REASON}")', fmt=wp.WON)
        b.put(ws, row, 4, f'=SUMIFS({err},{G},A{row},{F},"<>{KEY_REASON}",{err},">0")', fmt=wp.WON)
        b.put(ws, row, 5, f'=-SUMIFS({err},{G},A{row},{F},"<>{KEY_REASON}",{err},"<0")', fmt=wp.WON)
        b.put(ws, row, 6, f"=IF(C{row}>0,D{row}/C{row}*B{row},0)", fmt=wp.WON)
        b.put(ws, row, 7, f"=IF(C{row}>0,E{row}/C{row}*B{row},0)", fmt=wp.WON)
        row += 1
    bot = row - 1
    row += 1
    ws.cell(row, 1, "변이로 본 왜곡표시 금액(왜곡표시 금액 칸에서 빼고 여기 적음, 과대계상 양수)").font = wp.font(color=wp.MUTED)
    an = f"B{row}"
    ask(b, ws, row, 2, f"변이 왜곡표시: {WHAT}", rule="optional", fmt=wp.WON)
    row += 1
    cells = {}
    for key, lab, f in [("ko", "고액 항목 왜곡표시: 과대(그대로)", f'=SUMIFS({err},{F},"{KEY_REASON}",{err},">0")'),
                        ("ku", "고액 항목 왜곡표시: 과소(그대로, 양수로)", f'=-SUMIFS({err},{F},"{KEY_REASON}",{err},"<0")'),
                        ("po", "투영한 왜곡표시: 과대계상 합", None), ("pu", "투영한 왜곡표시: 과소계상 합(양수로)", None),
                        ("est", "모집단 왜곡표시 추정치 = 투영(과대 − 과소) + 변이 (문단 A22)", None)]:
        ws.cell(row, 1, lab).font = wp.font(color=wp.MUTED)
        cells[key] = f"B{row}"
        if f:
            b.put(ws, row, 2, f, fmt=wp.WON)
        row += 1
    b.put(ws, int(cells["po"][1:]), 2, f"=SUM(F{top}:F{bot})+{cells['ko']}", fmt=wp.WON, bold=True)
    b.put(ws, int(cells["pu"][1:]), 2, f"=SUM(G{top}:G{bot})+{cells['ku']}", fmt=wp.WON, bold=True)
    b.put(ws, int(cells["est"][1:]), 2, f"={cells['po']}-{cells['pu']}+N({an})", fmt=wp.WON)
    ws.cell(row, 1, "허용왜곡표시").font = wp.font(color=wp.MUTED)
    tol = f"B{row}"
    b.put(ws, row, 2, ctx["tm"], fmt=wp.WON)
    row += 1
    hi = f"MAX({cells['po']}+MAX(N({an}),0),{cells['pu']}+MAX(-N({an}),0))"
    f = (f'=IF({refs["pending"]}>0,"{se.V_PENDING}",IF({refs["nodiff"]}>0,"{se.V_NODIFF}",'
         f'IF({hi}=0,"{se.V_R_NONE}",IF({hi}>{tol},"{se.V_R_OVER}","{se.V_R_WITHIN}"))))')
    row = _verdict_tail(b, ws, row, f)
    ws.cell(row, 1, "비통계 표본은 표본위험 허용액을 계산하지 않는다. 계층 표의 투영은 계층마다 (표본 왜곡 ÷ 표본 장부 금액) × 표본 대상 금액이다"
                    "(문단 14, A18)").font = wp.font(size=9, color=wp.MUTED)
    return row + 2


def _eval_specific(b, ws, row: int, ctx: dict, first: int, last: int) -> int:
    """특정 항목 선정(500 문단 A65 · A66): 투영하지 않는다. 선정하지 않은 나머지 금액을 허용왜곡표시와 견준다. 엔진 계산은 sampling_eval.specific."""
    row = b.section(ws, row, "결과 (특정 항목 선정: 표본감사에 해당하지 않아 투영하지 않음, 감사기준서 500 문단 A66)")
    row, refs = _counts(b, ws, row, first, last)
    E = refs["err"]
    err = f"{E}{first}:{E}{last}"
    selected = sum(r["amount"] for r in ctx["sel"]["selected"])
    rest = ctx["pop_total"] - selected
    for lab, f in [("찾은 왜곡표시: 과대", f'=SUMIF({err},">0")'), ("찾은 왜곡표시: 과소(양수로)", f'=-SUMIF({err},"<0")'),
                   ("선정한 금액", f"=SUM(C{first}:C{last})")]:
        ws.cell(row, 1, lab).font = wp.font(color=wp.MUTED)
        b.put(ws, row, 2, f, fmt=wp.WON)
        row += 1
    ws.cell(row, 1, "선정하지 않은 나머지 금액").font = wp.font(color=wp.MUTED)
    b.put(ws, row, 2, rest, fmt=wp.WON, flag=rest > ctx["tm"])
    rest_cell = f"B{row}"
    row += 1
    ws.cell(row, 1, "허용왜곡표시").font = wp.font(color=wp.MUTED)
    tol = f"B{row}"
    b.put(ws, row, 2, ctx["tm"], fmt=wp.WON)
    row += 1
    f = (f'=IF({refs["pending"]}>0,"{se.V_PENDING}",IF({refs["nodiff"]}>0,"{se.V_NODIFF}",'
         f'IF({rest_cell}>{tol},"{se.V_S_REST}","{se.V_S_OK}")))')
    row = _verdict_tail(b, ws, row, f)
    ws.cell(row, 1, "선정하지 않은 나머지에 한 절차").font = wp.font(color=wp.MUTED)
    ask(b, ws, row, 2, "선정하지 않은 나머지에 한 절차", rule="required" if rest > ctx["tm"] else "optional")
    ws.cell(row, 3, "분석적 절차 · 추가 표본 · 다른 증거. 나머지가 허용왜곡표시보다 크면 반드시 적는다").font = wp.font(size=9, color=wp.MUTED)
    return row + 2


def _excluded_sheet(b, ctx: dict) -> None:
    ex = ctx["excluded"]
    if not ex:
        return
    ws, row = b.sheet("모집단에서 뺀 항목", [16, 12, 28, 40, 18, 30, 14])
    ws.cell(6, 1, "표본 모집단에 넣지 않은 항목이다. 금액 0 이하는 반품 · 에누리 · 역분개라 따로 검토하고, 사업연도에 들지 않는 일자는 기간귀속 절차에서 본다").font = \
        wp.font(size=9, color=wp.MUTED)
    row = b.head(ws, row, ["항목", "일자", "거래처", "적요", "금액", "뺀 까닭", "원본 행"])
    for u in sorted(ex, key=lambda u: u["amount"])[:EXCLUDED_LIST_MAX]:
        for i, (v, f) in enumerate([(u["key"], None), (u["date"].isoformat() if u["date"] else "", None), (u["party"], None),
                                    (u["desc"], None), (u["amount"], wp.WON), (u["why"], None), (u["src"], None)], 1):
            b.put(ws, row, i, v, fmt=f)
        row += 1
    if len(ex) > EXCLUDED_LIST_MAX:
        ws.cell(row, 1, f"금액 순으로 {EXCLUDED_LIST_MAX:,}건까지 적었다. 전체 {len(ex):,}건").font = wp.font(size=9, color=wp.RED)


def _population_sheet(b, ctx: dict) -> None:
    picked = {r["key"]: r for r in ctx["sel"]["selected"]}
    ws, row = b.sheet("모집단", [8, 16, 22, 12, 28, 40, 18, 18, 22])
    ws.cell(6, 1, "모집단 전 항목(--full). 누적 금액은 계층 안에서 파일 순서로 더한 값이다").font = wp.font(size=9, color=wp.MUTED)
    row = b.head(ws, row, ["#", "항목", "계층", "일자", "거래처", "적요", "금액", "계층 안 누적 금액", "선정"])
    cum: dict[str, float] = {}
    for i, u in enumerate(ctx["pop"], 1):
        cum[u["stratum"]] = cum.get(u["stratum"], 0.0) + u["amount"]
        r = picked.get(u["key"])
        for j, (v, f) in enumerate([(i, "0"), (u["key"], None), (u["stratum"], None), (u["date"].isoformat() if u["date"] else "", None),
                                    (u["party"], None), (u["desc"], None), (u["amount"], wp.WON), (cum[u["stratum"]], wp.WON),
                                    (r["reason"] if r else "", None)], 1):
            c = ws.cell(row, j, v)
            if f:
                c.number_format = f
        row += 1


def _meta(b, ctx: dict) -> None:
    """엔진이 다시 읽는 숨김 시트(sample eval). 값만 둔다."""
    p, sel = ctx["plan"], ctx["sel"]
    ws = b.wb.create_sheet(META)
    for k, v in [("method", ctx["method"]), ("interval", p["interval"]), ("key_threshold", sel["key_threshold"]), ("factor", p["factor"]),
                 ("confidence", p["confidence_used"]), ("tolerable", ctx["tm"]), ("pop_total", ctx["pop_total"])]:
        ws.append([k, v])
    ws.append(["stratum_base"] + [x for s in sel["strata"] for x in (s["label"], s["rest"])])
    ws.append(["rows"])
    for r in sel["selected"]:
        ws.append([r["key"], r["amount"], bool(r["key_item"]), r["stratum"]])
    ws.sheet_state = "hidden"


# ---------------------------------------------------------------- 평가(엔진)
def evaluate(path: Path) -> dict:
    """감사인이 적은 검사 결과 · 왜곡표시 금액 · 변이로 엔진이 평가한다. 엑셀 「허용왜곡표시와 견줌」 과 같은 판정이 나온다."""
    path = Path(path)
    wb = load_workbook(path, read_only=True, data_only=False)
    try:
        if META not in wb.sheetnames:
            raise SampleError(f"{path.name}: sample make 가 만든 조서가 아닙니다(숨김 시트 {META} 없음)")
        vals = [tuple(r) for r in wb[META].iter_rows(values_only=True)]
    finally:
        wb.close()
    meta, rows, i = {}, [], 0
    while i < len(vals) and vals[i][0] != "rows":
        meta[vals[i][0]] = vals[i][1:] if vals[i][0] == "stratum_base" else vals[i][1]
        i += 1
    inputs = {x["label"]: x["value"] for x in wp.readback(path)}
    for v in vals[i + 1:]:
        key = v[0]
        err = inputs.get(f"왜곡표시 금액: {key}")
        err = _num(err)
        # sampling_eval 은 key 를 고액 여부(참 · 거짓)로 읽는다. 항목 이름은 name 에 둔다
        rows.append({"name": key, "amount": float(v[1]), "key": bool(v[2]), "stratum": v[3],
                     "err": err, "done": not wp._blank(inputs.get(f"검사 결과: {key}")),
                     "nodiff": inputs.get(f"금액 대사: {key}") == vouch.CHOICES[1] and err is None})
    anomaly = _num(inputs.get(f"변이 왜곡표시: {WHAT}")) or 0.0
    method, tol = meta["method"], float(meta["tolerable"])
    if method == "mus":
        out = se.mus(rows, float(meta["interval"]), float(meta["factor"]), float(meta["confidence"]),
                     key=float(meta["key_threshold"]), anomaly=anomaly, tolerable=tol)
    elif method in ("random", "systematic"):
        sb = meta.get("stratum_base") or ()
        base = {sb[j]: float(sb[j + 1]) for j in range(0, len(sb) - 1, 2) if sb[j] is not None}
        out = se.ratio(rows, base, anomaly=anomaly, tolerable=tol)
    else:
        out = se.specific(rows, float(meta["pop_total"]), anomaly=anomaly, tolerable=tol)
    out["method"] = method
    out["items"] = len(rows)
    out["pending"] = sum(1 for r in rows if not r["done"])
    out["with_error"] = sum(1 for r in rows if r["err"])
    return out
