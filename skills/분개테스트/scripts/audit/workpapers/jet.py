"""3600-JET 분개 테스트(R4, 2026-10-05).

분개장 받은자료 전부를 엔진이 판독해 전표 단위로 시험한다. 시험 정의는 definitions/jet.yaml.
완전성: 당기 분개장의 손익계정 순액을 시산표와 맞춘다(재무상태표 계정은 기초 잔액이 분개장에 없어 전기 시산표가 있어야 한다).
결과 목록의 전표마다 검토 결과 기입란을 둔다. 판단(정상 거래인지)은 회계사가 적는다.
2026-10-21 시험 열세 가지(형식 이상 · 전표번호 · 한 번만 나온 거래처 · 이익을 늘린 결산 전표 · 중복 · 특수관계 · 자본 · 적요 낱말 ·
계정별로 평소보다 큰 금액, 작성자 · 승인자 · 입력일시 열이 있을 때 자기 승인 · 드문 작성자 · 결산 후 입력 · 업무 시간 외 입력)와
전표번호 연속성 · 분포 분석(첫 자리 · 월별) 시트를 더했다. 기존 일곱 시험의 판정은 그대로다.

  run(d, mat) -> {"tests": [{id, title, condition, review, hits: [{voucher, why}], note}], "completeness": [...], "seq": {...},
                  "analyses": {...}, "entry_cols": {...}, ...}
"""
from __future__ import annotations

import math
import re
import statistics
from bisect import bisect_right
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from datetime import time as dtime
from pathlib import Path

from .. import wp
from . import common
from .common import ask, won


def _in(x: common.Line, group: dict) -> bool:
    """줄 하나가 계정 묶음에 드는지(2026-10-21). 코드가 있으면 코드 범위로, 코드가 없으면 계정명 낱말로 본다.
    except 낱말이 든 계정명은 낱말 판정에서 뺀다(「매출」 묶음에서 외상매출금 · 매출원가를 뺀다). 다만 unless 낱말이 들면 except 를 넘어 넣는다
    (손익 묶음의 「대손충당금환입」 · 「충당부채전입액」).
    any: true 인 묶음은 코드가 있어도 계정명 낱말로도 찾는다(더존 코드 체계가 아닌 회사)."""
    name = common.reader._norm(x.name or "")
    by_name = any(k in name for k in group.get("names", [])) and (
        not any(e in name for e in group.get("except", [])) or any(u in name for u in group.get("unless", [])))
    if x.code is not None:
        return common.in_ranges(x.code, group.get("ranges", [])) or (bool(group.get("any")) and by_name)
    return by_name


def _grp(v: common.Voucher, side: str, group: dict) -> list:
    return [x for x in v.lines if (x.dr if side == "dr" else x.cr) and _in(x, group)]


def _keys(v: common.Voucher, side: str) -> list[str]:
    """한쪽(차변 · 대변) 계정 목록. 코드가 없는 분개장은 계정명으로 센다(2026-10-21, 코드 없는 분개장에서 드문 조합이 늘 0 이던 것)."""
    return sorted({x.code or common.reader._norm(x.name) for x in v.lines if (x.dr if side == "dr" else x.cr) and (x.code or x.name)})


def _is_pl(x: common.Line, acc: dict, pl_names: dict | None = None) -> bool:
    """줄이 손익계정인지. 코드가 있으면 코드 범위, 없으면 시산표의 같은 이름 계정(코드가 있는 행)의 손익 구분, 그것도 없으면 계정명 낱말."""
    if x.code is None and pl_names:
        n = common.reader._norm(x.name or "")
        if n in pl_names:
            return pl_names[n]
    return _in(x, acc["pnl"])


def _pnl(v: common.Voucher, acc: dict, pl_names: dict | None = None) -> float:
    """전표의 손익 효과. 수익 · 비용 계정의 대변 − 차변이라 + 면 이익이 늘었다."""
    return sum(x.cr - x.dr for x in v.lines if _is_pl(x, acc, pl_names))


def _net(v: common.Voucher) -> dict:
    """(계정, 거래처)별 차변 − 대변. 코드가 없는 분개장은 계정명으로 묶는다(Voucher.net 은 코드로만 묶어 코드 없는 분개장에서 늘 비었다)."""
    out: dict[tuple, float] = {}
    for x in v.lines:
        k = (x.code or common.reader._norm(x.name or ""), x.party)
        out[k] = out.get(k, 0.0) + x.dr - x.cr
    return {k: val for k, val in out.items() if abs(val) > 0.5}


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


# ---------------------------------------------------------------- 2026-10-21 추가 시험의 도구
_NUM = re.compile(r"^(.*?)(\d+)$")


def _lnds(dates: list[int]) -> set[int]:
    """날짜(서수) 목록에서 줄지 않는 가장 긴 부분열에 드는 자리. 그 밖의 자리가 번호 순서와 일자 순서가 어긋난 전표다.
    끼워 넣은 전표 하나는 그 전표만 빠지고, 날짜를 잘못 친 전표 하나도 그 전표만 빠진다(바로 뒤 전표들이 덩달아 걸리지 않는다)."""
    tails: list[int] = []          # 길이 k+1 인 부분열의 마지막 날짜
    tail_at: list[int] = []        # 그 자리
    parent = [-1] * len(dates)
    for i, x in enumerate(dates):
        k = bisect_right(tails, x)
        if k == len(tails):
            tails.append(x)
            tail_at.append(i)
        else:
            tails[k] = x
            tail_at[k] = i
        parent[i] = tail_at[k - 1] if k else -1
    keep, i = set(), tail_at[-1] if tail_at else -1
    while i >= 0:
        keep.add(i)
        i = parent[i]
    return keep


# 번호를 새로 붙이는 단위. 넓은 것부터 보고, 같은 번호가 다른 날짜에 나오는 전표 비중이 dup_ratio 이하인 첫 단위를 고른다.
# 일자 단위는 그 비중이 늘 0 이라 마지막에 반드시 고른다(2026-10-21 검토: 번호 개수가 아니라 전표 수로 세야 하루 전표가 많은 날에 끌려가지 않는다)
_UNITS = (("앞부분", lambda v: ""), ("달", lambda v: f"{v.date.year}-{v.date.month:02d}"), ("일자", lambda v: v.date.isoformat()))
_UNIT_TEXT = {"앞부분": "앞부분마다 이어 붙이는 번호", "달": "달마다 새로 붙이는 번호", "일자": "일자마다 새로 붙이는 번호"}


def _runs(ns: list[int], band_gap: int) -> list[list[int]]:
    """정렬한 번호를 band_gap 보다 크게 떨어진 곳에서 나눈다(일반전표 00001~ 와 매입매출전표 50001~ 처럼 번호대가 둘인 회사)."""
    out = [[ns[0]]]
    for a, b in zip(ns, ns[1:]):
        if b - a > band_gap:
            out.append([b])
        else:
            out[-1].append(b)
    return out


def _missing(run: list[int], lo: int, limit: int = 20) -> tuple[int, list[int]]:
    """lo ~ run[-1] 사이 빠진 번호 수와 앞 limit 개. 범위를 펼치지 않는다(번호가 10억 단위여도 메모리를 쓰지 않는다)."""
    count = (run[-1] - lo + 1) - len(run)
    sample, want, it = [], lo, iter(run)
    for n in it:
        while want < n and len(sample) < limit:
            sample.append(want)
            want += 1
        if len(sample) >= limit:
            break
        want = n + 1
    return count, sample


def voucher_seq(cur: list, t: dict) -> dict:
    """전표번호 연속성(2026-10-21). 번호 끝 숫자와 앞부분(예: 202512-)으로 나누고, 번호를 새로 붙이는 단위(앞부분 · 달 · 일자)를 고른다.
    고른 단위 안에서 같은 번호가 다른 날짜에 있으면 중복, 번호 순서와 일자 순서가 어긋나면 순서 역전, 번호 사이 빈 곳은 빠진 번호.
    {"scheme", "rows": [{key, first, last, count, missing, sample}], "hits": [(전표, 까닭)], "note", "gaps"}"""
    real = [v for v in cur if v.no != v.date.isoformat()]
    if not real:
        return {"scheme": None, "rows": [], "hits": [], "gaps": 0, "note": "분개장에 전표번호 열이 없어 시험하지 못했습니다"}
    parsed, odd = [], 0
    for v in real:
        m = _NUM.match(str(v.no).strip())
        if m:
            parsed.append((m.group(1), int(m.group(2)), v))
        else:
            odd += 1
    if not parsed:
        return {"scheme": None, "rows": [], "hits": [], "gaps": 0, "note": "전표번호가 숫자로 끝나지 않아 연속성을 보지 못했습니다"}
    for unit, keyf in _UNITS:
        dates_of: dict[tuple, set] = defaultdict(set)
        for p, n, v in parsed:
            dates_of[(keyf(v), p, n)].add(v.date)
        share = sum(1 for p, n, v in parsed if len(dates_of[(keyf(v), p, n)]) > 1) / len(parsed)
        if share <= t.get("dup_ratio", 0.05):
            break
    groups: dict[tuple, list] = defaultdict(list)
    for p, n, v in parsed:
        groups[(keyf(v), p)].append((n, v))
    band = t.get("band_gap", 1000)
    rows, hits, gaps = [], [], 0
    for key in sorted(groups):
        g = groups[key]
        ns = sorted({n for n, _ in g})
        runs = _runs(ns, band)
        missing, sample = 0, []
        for i, run in enumerate(runs):
            lo = 1 if (i == 0 and unit != "앞부분" and run[0] <= band) else run[0]
            c, s = _missing(run, lo, 20 - len(sample))
            missing += c
            sample += s
        gaps += missing
        if unit != "일자" or missing:
            label = " ".join(x for x in key if x) or "(앞부분 없음)"
            rows.append({"key": label, "first": ns[0], "last": ns[-1], "count": len(g), "missing": missing, "sample": sample,
                         "runs": len(runs)})
    widespread = lambda k: k > max(t.get("widespread_min", 5), t.get("widespread", 0.05) * len(cur))  # noqa: E731
    notes = [f"번호 단위: {_UNIT_TEXT[unit]}", f"빠진 번호 {gaps:,}개(전표번호 연속성 시트)"]
    dup = [(v, f"같은 전표번호가 {len(dates_of[(keyf(v), p, n)])}개 날짜(" +
            ", ".join(sorted(x.isoformat() for x in dates_of[(keyf(v), p, n)])[:3]) + ")에 있음")
           for p, n, v in parsed if len(dates_of[(keyf(v), p, n)]) > 1]
    if dup:
        notes.append(f"중복 번호 {len(dup)}건")
        hits += dup
    if unit != "일자":
        out_of_order = []
        min_days = t.get("min_days", 7)
        for g in groups.values():
            g = sorted(g, key=lambda e: (e[0], e[1].date))
            keep = sorted(_lnds([v.date.toordinal() for _, v in g]))
            kept = set(keep)
            for i, (n, v) in enumerate(g):
                if i in kept:
                    continue
                j = bisect_right(keep, i)
                prev = g[keep[j - 1]][1] if j > 0 else None
                nxt = g[keep[j]][1] if j < len(keep) else None
                if prev is not None and v.date < prev.date:
                    gap, ref, word = (prev.date - v.date).days, prev, "앞 번호"
                elif nxt is not None and v.date > nxt.date:
                    gap, ref, word = (v.date - nxt.date).days, nxt, "뒤 번호"
                else:
                    continue
                if gap >= min_days:
                    out_of_order.append((v, f"{word} {ref.no}({ref.date.isoformat()})보다 일자가 {gap}일 " + ("앞섬" if word == "앞 번호" else "늦음")))
        if widespread(len(out_of_order)):
            notes.append(f"순서 역전 {len(out_of_order)}건은 당기 전표의 {t.get('widespread', 0.05):.0%} 를 넘어 번호를 입력 순서로 붙이는 회사로 보고 "
                         "목록에 올리지 않았습니다. 회사 전산의 번호 체계를 확인해 주십시오")
        else:
            hits += out_of_order
            notes.append(f"순서 역전 {len(out_of_order)}건")
    if odd:
        notes.append(f"숫자로 끝나지 않는 번호 {odd}건은 연속성에서 뺐습니다")
    merged: dict[int, list] = {}
    for v, why in hits:
        merged.setdefault(id(v), [v, []])[1].append(why)
    hits = sorted(((v, " · ".join(ws)) for v, ws in merged.values()), key=lambda e: (e[0].date, e[0].no))
    return {"scheme": _UNIT_TEXT[unit], "rows": rows, "hits": hits, "note": " · ".join(notes), "gaps": gaps}


def entry_cols(extra_cols: list, spec: dict) -> dict:
    """작성자 · 승인자 · 입력일시 열 이름. 분개장에 없으면 None."""
    return {k: next((c for c in names if c in extra_cols), None) for k, names in (spec.get("entry_columns") or {}).items()}


_DATE_TIME = re.compile(r"(\d{4})\s*[-./년]\s*(\d{1,2})\s*[-./월]\s*(\d{1,2})\s*일?"
                        r"(?:[ T]+(오전|오후|AM|PM|am|pm)?\s*(\d{1,2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?\s*(AM|PM|am|pm)?)?")
_COMPACT = re.compile(r"(\d{4})(\d{2})(\d{2})(?:[ T]?(\d{2}):?(\d{2})(?::?(\d{2}))?)?")
_TIME = re.compile(r"(오전|오후|AM|PM|am|pm)?\s*(\d{1,2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?\s*(AM|PM|am|pm)?")


def _hm(h: int, mi: int, sec: int = 0, ampm: str | None = None) -> tuple[int | None, int | None]:
    """시 · 분. 오후 · PM 이면 12 를 더한다. 0시 0분 0초는 날짜만 적은 칸으로 보고 시각 없음(None)으로 둔다(모든 꼴에 같게)."""
    a = (ampm or "").upper()
    if a in ("오후", "PM") and h < 12:
        h += 12
    elif a in ("오전", "AM") and h == 12:
        h = 0
    return (None, None) if (h, mi, sec) == (0, 0, 0) else (h, mi)


def _when(v) -> tuple[date | None, int | None, int | None]:
    """입력일시 칸 → (입력일, 시, 분). 시각만 적은 칸은 (None, 시, 분). 시각이 없거나 0시 0분 0초면 시 · 분은 None.
    읽는 꼴: datetime · date · time · 엑셀 일련번호(소수는 시각) · 「2026-01-20 23:10」 · 「2026-01-20T23:10:05.123Z」 ·
    「2026-01-20 오후 11:10:05」 · 「2026년 1월 20일 23:10」 · 「20260120 2310」 · 「20260120231000」 · 「23:10」 · 「오후 11:10」."""
    if v in (None, ""):
        return None, None, None
    if isinstance(v, datetime):
        return (v.date(), *_hm(v.hour, v.minute, v.second))
    if isinstance(v, date):
        return v, None, None
    if isinstance(v, dtime):
        return (None, *_hm(v.hour, v.minute, v.second))
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        whole, frac = int(v), float(v) - int(v)
        mins = round(frac * 24 * 60)
        if 20000 <= v <= 80000:
            d = date(1899, 12, 30) + timedelta(days=whole + mins // 1440)
            return (d, *_hm((mins % 1440) // 60, mins % 60))
        if 0 <= v < 1:                                # 시각만 적은 일련번호
            return (None, *_hm((mins % 1440) // 60, mins % 60))
    s = re.sub(r"(Z|[+-]\d{2}:?\d{2})$", "", str(v).strip())
    try:
        if m := _DATE_TIME.fullmatch(s):
            d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            if m.group(5) is None:
                return d, None, None
            return (d, *_hm(int(m.group(5)), int(m.group(6)), int(m.group(7) or 0), m.group(4) or m.group(8)))
        if m := _COMPACT.fullmatch(s):
            d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            if m.group(4) is None:
                return d, None, None
            return (d, *_hm(int(m.group(4)), int(m.group(5)), int(m.group(6) or 0)))
        if m := _TIME.fullmatch(s):
            return (None, *_hm(int(m.group(2)), int(m.group(3)), int(m.group(4) or 0), m.group(1) or m.group(5)))
    except ValueError:
        return None, None, None
    return common.reader._date(s), None, None


def entry_of(v: common.Voucher, cols: dict) -> dict:
    """전표의 작성자 · 승인자 · 입력일시(첫 줄부터 처음 값이 있는 줄). 입력일자와 입력시각이 다른 열이면 합친다."""
    def first(c):
        if not c:
            return None
        return next((x.extra.get(c) for x in v.lines if x.extra.get(c) not in (None, "")), None)

    u, a = first(cols.get("user")), first(cols.get("approver"))
    d, h, mi = _when(first(cols.get("entered")))
    if h is None and cols.get("entered_time"):
        d2, h, mi = _when(first(cols["entered_time"]))
        d = d or d2
    return {"user": None if u is None else str(u).strip(), "approver": None if a is None else str(a).strip(),
            "entered": d, "hour": h, "minute": mi}


def _entry_text(e: dict) -> str:
    parts = []
    if e.get("user"):
        parts.append(f"작성 {e['user']}")
    if e.get("approver"):
        parts.append(f"승인 {e['approver']}")
    if e.get("entered"):
        parts.append("입력 " + e["entered"].isoformat() + (f" {e['hour']:02d}:{e['minute']:02d}" if e.get("hour") is not None else ""))
    return " · ".join(parts)


def benford(lines: list, spec: dict) -> dict:
    """줄 금액 첫 자리 분포(2026-10-21). {"counts": {1..9: n}, "n", "mad", "verdict"}. MAD 는 실제 비율과 기대 비율 차이 절대값의 평균이다."""
    low = max(spec.get("min_amount", 10), 1)          # 1 미만은 첫 자리를 정수로 읽지 못한다
    counts = {d: 0 for d in range(1, 10)}
    for x in lines:
        a = abs(x.dr) if x.dr else abs(x.cr)
        if a >= low:
            counts[int(str(int(a))[0])] += 1
    n = sum(counts.values())
    mad = sum(abs(counts[d] / n - math.log10(1 + 1 / d)) for d in counts) / 9 if n else None
    if not n or n < spec.get("min_lines", 300):
        verdict = f"줄이 {n:,}개라 판정하지 않음(기준 {spec.get('min_lines', 300):,}개)"
    else:
        verdict = next((w for lim, w in spec.get("mad", []) if mad <= lim), spec.get("over", "부적합"))
    return {"counts": counts, "n": n, "mad": mad, "verdict": verdict}


def monthly(cur: list, start: date, end: date, acc: dict, spec: dict) -> dict:
    """사업연도 달마다 전표 수 · 금액 · 매출 순액(매출 계정 대변 − 차변). 결산월 매출이 사업연도 월평균의 ratio 배 이상이면 표시."""
    months, y, m = [], start.year, start.month
    while (y, m) <= (end.year, end.month):
        months.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    rows = {k: {"ym": f"{k[0]}-{k[1]:02d}", "count": 0, "amount": 0.0, "revenue": 0.0} for k in months}
    for v in cur:
        r = rows.get((v.date.year, v.date.month))
        if r is None:
            continue
        r["count"] += 1
        r["amount"] += v.amount
        r["revenue"] += sum(x.cr - x.dr for x in v.lines if _in(x, acc["revenue"]))
    out = list(rows.values())
    ye = rows.get((end.year, end.month))
    avg = sum(r["revenue"] for r in out) / len(out) if out else 0.0
    ratio = (ye["revenue"] / avg) if ye and avg else None
    flag = ratio is not None and ratio >= spec.get("ratio", 1.5)
    return {"rows": out, "ye_ratio": ratio, "flag": flag}


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
    tb = common.tb_rows(d)
    # 코드 없는 분개장의 손익 판정에 쓴다: 시산표에서 코드가 있는 행의 계정명 → 손익 여부
    pl_names = {common.reader._norm(r["name"]): bool(r["pl"]) for r in tb if r.get("code") is not None and r.get("name")}

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
        net = _net(pv)
        if not net:
            continue
        rev = {k: -x for k, x in net.items()}
        match = next((ov for ov in near if id(ov) not in used and _net(ov) == rev), None)
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
        k = ("+".join(_keys(v, "dr")), "+".join(_keys(v, "cr")))
        sig[k] = sig.get(k, 0) + 1
    for v in cur:
        why = []
        k = ("+".join(_keys(v, "dr")), "+".join(_keys(v, "cr")))
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

    # ---- 2026-10-21 추가 시험
    # 많이 걸리면 목록 대신 메모로 남기는 기준(번호 순서 역전 · 음수 금액 · 중복 의심 · 승인 없음): 당기 전표의 widespread 비율과 widespread_min 건 가운데 큰 쪽
    def widespread(t: dict, k: int) -> bool:
        return k > max(t.get("widespread_min", 5), t.get("widespread", 0.05) * max(len(cur), 1))

    # 전표 형식 이상: 전표별 차대 · 계정이 빈 줄 · 음수 금액
    t = tests["integrity"]
    neg = []
    for v in cur + post:
        why = []
        dr, cr = sum(x.dr for x in v.lines), sum(x.cr for x in v.lines)
        if abs(dr - cr) > 0.5:
            why.append(f"차변 {won(dr)} · 대변 {won(cr)} · 차이 {won(dr - cr)}")
        n = sum(1 for x in v.lines if x.code is None and not (x.name or "").strip())
        if n:
            why.append(f"계정이 빈 줄 {n}개")
        if why:
            hit("integrity", v, " · ".join(why))
        n = sum(1 for x in v.lines if x.dr < 0 or x.cr < 0)
        if n:
            neg.append((v, f"음수 금액 줄 {n}개"))
    if widespread(t, len(neg)):
        # 수정세금계산서처럼 마이너스 전표를 늘 쓰는 회사(2026-10-21 검토)
        t["note"] = f"음수 금액 줄이 있는 전표 {len(neg)}건은 마이너스 전표를 늘 쓰는 회사로 보고 목록에 올리지 않았습니다"
    else:
        done = {id(h["voucher"]): h for h in t["hits"]}
        for v, why in neg:
            if id(v) in done:
                done[id(v)]["why"] += f" · {why}"
            else:
                hit("integrity", v, why)

    # 전표번호 중복 · 순서 역전 · 빠진 번호
    t = tests["voucher_seq"]
    seq = voucher_seq(cur, t)
    for v, why in seq["hits"]:
        hit("voucher_seq", v, why)
    t["note"] = seq["note"]

    # 한 번만 나온 거래처의 큰 금액
    t = tests["one_time_party"]
    if pm:
        cut = pm * t.get("ratio", 0.5)
        seen = common.prior_parties(j)
        cnt = Counter(p for v in cur for p in v.parties)
        after = Counter(p for v in post for p in v.parties)
        for v in cur:
            ones = [p for p in v.parties if cnt[p] == 1 and (seen is None or p not in seen)]
            if ones and v.amount >= cut:
                extra = "".join(f" · 기말 후 분개장에도 {p} {after[p]}건" for p in ones if after[p])
                hit("one_time_party", v, f"당기 전표 1건뿐인 거래처: {', '.join(ones)}" + ("" if seen is None else " · 전기 분개장에도 없음") +
                    f", 금액 {won(v.amount)} ≥ 수행중요성 × {t.get('ratio', 0.5)}" + extra)
        t["note"] = f"기준 {won(cut)}" + (" · 전기 분개장이 없어 전기 거래 여부는 보지 않았습니다" if seen is None else "")
    else:
        t["note"] = "수행중요성이 없어 시험하지 못했습니다"

    # 결산일 근처 이익을 늘린 전표
    t = tests["profit_up"]
    if pm:
        cut = pm * t.get("ratio", 0.5)
        start = end - timedelta(days=t.get("days", 15))
        for v in cur:
            if v.date > start:
                e = _pnl(v, acc, pl_names)
                if e >= cut:
                    hit("profit_up", v, f"결산일 전 {(end - v.date).days}일, 이익 +{won(e)} ≥ 수행중요성 × {t.get('ratio', 0.5)}")
        t["note"] = f"기준 {won(cut)} · 손익계정은 매출 · 매출원가 · 판관비 · 영업외 · 법인세(제조원가 빼고)"
    else:
        t["note"] = "수행중요성이 없어 시험하지 못했습니다"

    # 중복 의심 전표
    t = tests["duplicate"]
    same: dict[tuple, list] = defaultdict(list)
    for v in cur:
        if v.amount > 0:
            same[(tuple(_keys(v, "dr")), tuple(_keys(v, "cr")), tuple(v.parties), round(v.amount, 2))].append(v)
    # 사슬로 잇지 않고 바로 이웃한 두 전표만 본다. 매주 같은 금액을 주는 거래가 한 해 내내 한 묶음이 되지 않게(2026-10-21 검토)
    pairs: dict[int, list] = {}
    for vs in same.values():
        vs.sort(key=lambda v: (v.date, v.no))
        for a, b in zip(vs, vs[1:]):
            if (b.date - a.date).days <= t.get("days", 3):
                pairs.setdefault(id(a), [a, []])[1].append(b)
                pairs.setdefault(id(b), [b, []])[1].append(a)
    if widespread(t, len(pairs)):
        t["note"] = f"중복 의심 {len(pairs)}건은 같은 금액 거래가 잦은 회사로 보고 목록에 올리지 않았습니다. 거래처별로 따로 보십시오"
    else:
        for v, others in sorted(pairs.values(), key=lambda e: (e[0].date, e[0].no)):
            hit("duplicate", v, "계정 · 거래처 · 금액이 같은 전표 " + ", ".join(f"{o.date.isoformat()} {o.no}" for o in others))

    # 대표 · 주주 · 임원 관련 계정, 자본 계정
    words = spec.get("related_parties", [])
    for v in cur + post:
        accs = sorted({x.name or str(x.code) for x in v.lines if _in(x, acc["related"])})
        ps = [p for p in v.parties if any(w in p for w in words)]
        if accs or ps:
            hit("related_party", v, " · ".join(([f"계정 {', '.join(accs)}"] if accs else []) + ([f"거래처 {', '.join(ps)}"] if ps else [])))
        eq = sorted({x.name or str(x.code) for x in v.lines if _in(x, acc["equity"])})
        if eq:
            hit("equity", v, f"계정 {', '.join(eq)}")

    # 적요 주의 낱말
    t = tests["memo_keyword"]
    for v in cur + post:
        k = [w for w in t.get("keywords", []) if w in v.memo]
        if k:
            hit("memo_keyword", v, "적요 낱말 " + ", ".join(f"'{w}'" for w in k[:3]))

    # 계정 평소보다 큰 금액
    t = tests["outlier"]
    by: dict[tuple, list] = defaultdict(list)
    for v in cur:
        for x in v.lines:
            key = x.code or common.reader._norm(x.name)
            for side, amt in (("차변", x.dr), ("대변", x.cr)):
                if key and amt > 0:
                    by[(key, side)].append((amt, v, x))
    floor = pm * t.get("ratio", 0.5) if pm else t.get("min_amount", 10_000_000)
    found: dict[int, list] = {}
    for (key, side), xs in by.items():
        if len(xs) < max(t.get("min_lines", 12), 1):
            continue
        med = statistics.median(a for a, _, _ in xs)
        cut = max(med * t.get("multiple", 10), floor)
        for a, v, x in xs:
            if med > 0 and a >= cut:
                found.setdefault(id(v), [v]).append(f"{x.name or key} {side} {won(a)} = 중앙값 {won(med)} 의 {a / med:,.0f}배")
    for v, *why in sorted(found.values(), key=lambda e: (e[0].date, e[0].no)):
        hit("outlier", v, " · ".join(why))
    t["note"] = f"금액 하한 {won(floor)}" + (" (수행중요성 × " + str(t.get("ratio", 0.5)) + ")" if pm else " (수행중요성이 없어 min_amount)")

    # 작성자 · 승인자 · 입력일시 열이 있을 때만 도는 시험
    cols = entry_cols(j["extra_cols"], spec)
    meta = {id(v): entry_of(v, cols) for v in cur + post}
    t = tests["self_approval"]
    if cols.get("approver"):
        allv = cur + post
        filled = sum(1 for v in allv if meta[id(v)]["approver"])
        none_hits, same_hits = [], []
        for v in allv:
            e = meta[id(v)]
            if not e["approver"]:
                none_hits.append((v, f"승인자 없음(작성 {e['user'] or '빈 칸'})"))
            elif e["user"] and e["user"] == e["approver"]:
                same_hits.append((v, f"작성자와 승인자가 같음({e['user']})"))
        notes = [f"분개장 '{cols.get('user') or '작성자 열 없음'}' · '{cols['approver']}' 열로 판정"]
        if filled < t.get("min_filled", 0.5) * max(len(allv), 1):
            # 승인자 칸이 대부분 빈 회사(자동 전표에 승인자를 남기지 않는 전산). 승인 없음을 전표마다 올리면 목록이 분개장 전체가 된다(2026-10-21 검토)
            notes.append(f"승인자 칸이 채워진 전표가 {filled:,}건({filled / max(len(allv), 1):.0%})뿐이라 승인 없음 {len(none_hits):,}건은 목록에 올리지 않았습니다. "
                         "회사 전산의 승인 절차를 확인해 주십시오")
            none_hits = []
        for v, why in sorted(none_hits + same_hits, key=lambda e: (e[0].date, e[0].no)):
            hit("self_approval", v, why)
        t["note"] = ". ".join(notes)
    else:
        t["note"] = "분개장에 승인자 열이 없어 시험하지 못했습니다. 회사 전산에서 작성자 · 승인자가 든 분개장을 받아 주십시오"
    t = tests["rare_user"]
    if cols.get("user"):
        made = Counter(meta[id(v)]["user"] for v in cur + post if meta[id(v)]["user"])
        if len(made) >= 2:
            for v in cur + post:
                u = meta[id(v)]["user"]
                if u and made[u] <= t.get("max_count", 5):
                    hit("rare_user", v, f"작성자 {u}: 작성한 전표 {made[u]}건(작성자 {len(made)}명)")
            t["note"] = f"분개장 '{cols['user']}' 열로 판정"
        elif made:
            t["note"] = "작성자가 한 명뿐이라 시험하지 않았습니다"
        else:
            t["note"] = f"분개장 '{cols['user']}' 열이 모두 비어 시험하지 못했습니다"
    else:
        t["note"] = "분개장에 작성자 열이 없어 시험하지 못했습니다"
    if cols.get("entered") or cols.get("entered_time"):
        t, o = tests["late_entry"], tests["off_hours"]
        unread = 0
        for v in cur + post:
            e = meta[id(v)]
            ed = e["entered"]
            if ed is None:
                unread += 1
                continue
            why = []
            if v.date <= end < ed:
                why.append(f"결산일 후 {ed.isoformat()} 입력")
            if (ed - v.date).days >= t.get("days", 30):
                why.append(f"전표 일자보다 {(ed - v.date).days}일 늦게 입력")
            if why:
                hit("late_entry", v, " · ".join(why))
            why = []
            h = e["hour"]
            if h is not None and (h >= o.get("night_from", 22) or h < o.get("night_to", 6)):
                why.append(f"입력 시각 {h:02d}:{e['minute']:02d}")
            if ed.weekday() >= 5:
                why.append("입력일 " + ("토요일" if ed.weekday() == 5 else "일요일"))
            elif ed in hol:
                why.append("입력일 공휴일")
            if why:
                hit("off_hours", v, " · ".join(why))
        used = " · ".join(f"'{c}'" for c in (cols.get("entered"), cols.get("entered_time")) if c)
        t["note"] = o["note"] = f"분개장 {used} 열로 판정"
        if unread:
            miss = f". 입력일을 읽지 못한 전표 {unread:,}건은 빠졌습니다"
            t["note"] += miss
            o["note"] += miss
        if not any(meta[id(v)]["hour"] is not None for v in cur + post):
            o["note"] += ". 입력일시에 시각이 없어 입력일의 요일 · 공휴일만 봤습니다"
    else:
        for k in ("late_entry", "off_hours"):
            tests[k]["note"] = "분개장에 입력일시 열이 없어 시험하지 못했습니다. 회사 전산에서 입력일시가 든 분개장을 받아 주십시오"

    # 모집단 분석: 첫 자리 분포 · 월별
    an = spec.get("analyses") or {}
    analyses = {"benford": {**benford(j["cur"], an.get("benford") or {}), "title": (an.get("benford") or {}).get("title", "첫 자리 분포")},
                "monthly": {**monthly(cur, common.fy_start(d), end, acc, an.get("monthly") or {}),
                            "title": (an.get("monthly") or {}).get("title", "월별 전표 · 매출"), "ratio": (an.get("monthly") or {}).get("ratio", 1.5)}}

    # 완전성: 손익계정
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
            "vouchers": len(cur), "post_vouchers": len(post), "mat": mat,
            "seq": seq, "analyses": analyses, "entry_cols": cols, "meta": meta, "pnl": {id(v): _pnl(v, acc, pl_names) for v in cur + post}}


def make(d: Path, ctx: dict | None = None, force: bool = False) -> dict:
    d = Path(d)
    mat = (ctx or {}).get("mat") or common.materiality(d)
    r = run(d, mat)
    b = wp.Book(d, "3600-JET", standard="감사기준서 240 문단 33(a) · 한공회 3600 부정의 검토 · 분개장 전수")
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
    row += 2

    # 모집단 분석(2026-10-21): 분개장 전체의 분포를 본다. 자세한 표는 「분포 분석」 · 「전표번호 연속성」 시트
    an = r["analyses"]
    row = b.section(ws, row, "모집단 분석 (분포 분석 · 전표번호 연속성 시트)")
    row = b.head(ws, row, ["분석", "", "", "결과", "", "회계사 확인"])
    bf, mo = an["benford"], an["monthly"]
    b.put(ws, row, 1, bf["title"], bold=True)
    b.put(ws, row, 4, f"줄 {bf['n']:,}개 · MAD " + ("-" if bf["mad"] is None else f"{bf['mad']:.4f}") + f" · {bf['verdict']}", wrap=True,
          flag=bf["verdict"] in ("경계", "부적합"))
    ws.merge_cells(start_row=row, start_column=4, end_row=row, end_column=5)
    ask(b, ws, row, 6, f"확인: {bf['title']}")
    row += 1
    b.put(ws, row, 1, mo["title"], bold=True)
    txt = "결산월 매출 " + ("-" if mo["ye_ratio"] is None else f"= 월평균의 {mo['ye_ratio']:.2f}배") + \
          (f" (기준 {mo['ratio']}배 이상)" if mo["flag"] else "")
    b.put(ws, row, 4, txt, wrap=True, flag=mo["flag"])
    ws.merge_cells(start_row=row, start_column=4, end_row=row, end_column=5)
    ask(b, ws, row, 6, f"확인: {mo['title']}")
    row += 1
    sq = r["seq"]
    b.put(ws, row, 1, "전표번호 연속성", bold=True)
    b.put(ws, row, 4, sq["note"], wrap=True, flag=bool(sq.get("gaps")))
    ws.merge_cells(start_row=row, start_column=4, end_row=row, end_column=5)
    ask(b, ws, row, 6, "확인: 전표번호 연속성")
    ws.row_dimensions[row].height = 30
    row += 2
    b.conclusion(ws, row, 6)

    has_entry = any(r["entry_cols"].get(k) for k in ("user", "approver", "entered"))
    wl, rl = b.sheet("결과 목록", widths=[20, 12, 6, 16, 6, 26, 26, 16, 34, 16, 34, 30, 16] + ([30] if has_entry else []))
    rl = b.head(wl, rl, ["시험", "일자", "요일", "전표번호", "줄 수", "차변 계정", "대변 계정", "거래처", "적요", "금액", "근거", "검토 결과", "이익 효과"] +
                (["작성 · 승인 · 입력"] if has_entry else []))
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
            pnl = r["pnl"].get(id(v), 0.0)
            b.put(wl, rl, 13, common.reader._int(pnl) if abs(pnl) > 0.5 else None, fmt=wp.WON)
            if has_entry:
                b.put(wl, rl, 14, _entry_text(r["meta"].get(id(v), {})), wrap=True)
            rl += 1
    wl.cell(rl + 1, 1, "이익 효과: 그 전표가 손익계정(매출 · 매출원가 · 판관비 · 영업외 · 법인세)에 준 순효과. + 면 이익이 늘었다").font = \
        wp.font(size=9, color=wp.MUTED)
    _multi_sheet(b, r)
    _bs_sheet(b, r)
    _closing_sheet(b, r)
    _seq_sheet(b, r)
    _dist_sheet(b, r)
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


def multi_hits(r: dict) -> list[dict]:
    """시험 둘 이상에 걸린 전표(2026-10-21). 걸린 시험 수가 많은 순, 같으면 금액 큰 순."""
    by: dict[int, dict] = {}
    for t in r["tests"]:
        for h in t["hits"]:
            v = h["voucher"]
            e = by.setdefault(id(v), {"voucher": v, "titles": []})
            if t["title"] not in e["titles"]:
                e["titles"].append(t["title"])
    out = [e for e in by.values() if len(e["titles"]) >= 2]
    return sorted(out, key=lambda e: (-len(e["titles"]), -e["voucher"].amount, e["voucher"].date, e["voucher"].no))


def _multi_sheet(b: wp.Book, r: dict) -> None:
    """여러 시험에 걸린 전표(2026-10-21). 결과 목록은 시험마다 한 줄이라 한 전표가 흩어져 보인다. 전표마다 모아 먼저 볼 순서로 늘어놓는다."""
    rows = multi_hits(r)
    ws, row = b.sheet("여러 시험에 걸린 전표", widths=[16, 12, 16, 30, 16, 16, 10, 70])
    ws.cell(6, 1, "시험 둘 이상에 걸린 전표를 걸린 시험 수가 많은 순으로 모았다. 검토 결과는 결과 목록에 적는다").font = wp.font(size=9, color=wp.MUTED)
    row = b.section(ws, row, f"여러 시험에 걸린 전표 {len(rows)}건")
    if not rows:
        return
    row = b.head(ws, row, ["전표번호", "일자", "거래처", "적요", "금액", "이익 효과", "시험 수", "걸린 시험"])
    for e in rows:
        v = e["voucher"]
        pnl = r["pnl"].get(id(v), 0.0)
        b.put(ws, row, 1, v.no)
        b.put(ws, row, 2, v.date.isoformat())
        b.put(ws, row, 3, ", ".join(v.parties))
        b.put(ws, row, 4, common.short(v.memo, 60), wrap=True)
        b.put(ws, row, 5, v.amount, fmt=wp.WON)
        b.put(ws, row, 6, common.reader._int(pnl) if abs(pnl) > 0.5 else None, fmt=wp.WON)
        b.put(ws, row, 7, len(e["titles"]), fmt="#,##0", flag=len(e["titles"]) >= 4)
        b.put(ws, row, 8, " · ".join(e["titles"]), wrap=True)
        row += 1


def _seq_sheet(b: wp.Book, r: dict) -> None:
    """전표번호 연속성(2026-10-21). 번호 앞부분(일자별 체계면 일자)마다 첫 · 끝 번호와 빠진 번호."""
    sq = r["seq"]
    ws, row = b.sheet("전표번호 연속성", widths=[24, 12, 12, 12, 14, 60])
    ws.cell(6, 1, "전표번호 끝 숫자를 앞부분(예: 202512-)마다 이어 본다. 빠진 번호는 지운 전표 · 취소한 전표일 수 있다. 회사 전산의 삭제 · 취소 전표 목록과 "
                  "대조한다. " + sq["note"]).font = wp.font(size=9, color=wp.MUTED)
    row = b.section(ws, row, "번호 체계: " + (sq["scheme"] or "판정 못함"))
    if not sq["rows"]:
        ws.cell(row, 1, "빠진 번호가 없거나 전표번호가 없어 표를 만들지 않았습니다").font = wp.font(size=9, color=wp.MUTED)
        return
    row = b.head(ws, row, ["번호 단위 · 앞부분", "첫 번호", "끝 번호", "전표 수", "빠진 번호 수", "빠진 번호(앞 20개)"])
    first = row
    for x in sq["rows"]:
        b.put(ws, row, 1, x["key"])
        b.put(ws, row, 2, x["first"], fmt="#,##0")
        b.put(ws, row, 3, x["last"], fmt="#,##0")
        b.put(ws, row, 4, x["count"], fmt="#,##0")
        b.put(ws, row, 5, x["missing"], fmt="#,##0", flag=bool(x["missing"]))
        txt = ", ".join(map(str, x["sample"])) + (f" 외 {x['missing'] - len(x['sample']):,}개" if x["missing"] > len(x["sample"]) else "")
        if x.get("runs", 1) > 1:
            txt += f" (번호대 {x['runs']}개로 나눠 셈)"
        b.put(ws, row, 6, txt, wrap=True)
        row += 1
    b.put(ws, row, 1, "합계", bold=True)
    b.put(ws, row, 4, f"=SUM(D{first}:D{row - 1})", fmt="#,##0", bold=True)
    b.put(ws, row, 5, f"=SUM(E{first}:E{row - 1})", fmt="#,##0", bold=True)
    b.verify("전표번호 빠진 번호 수", f"='전표번호 연속성'!E{row}", sq.get("gaps", 0))


def _dist_sheet(b: wp.Book, r: dict) -> None:
    """분포 분석(2026-10-21): 줄 금액 첫 자리(벤포드)와 월별 전표 · 매출."""
    bf, mo = r["analyses"]["benford"], r["analyses"]["monthly"]
    ws, row = b.sheet("분포 분석", widths=[16, 14, 14, 14, 14, 16])
    ws.cell(6, 1, "분개장 전체의 분포다. 첫 자리 분포는 자연스럽게 생긴 금액이 벤포드 법칙(첫 자리 1 이 약 30%)을 따른다는 데 기댄다. "
                  "정가 · 고정 금액이 많은 회사나 줄이 적은 분개장은 맞지 않는 것이 정상일 수 있다").font = wp.font(size=9, color=wp.MUTED)
    row = b.section(ws, row, f"{bf['title']}: 줄 {bf['n']:,}개 · {bf['verdict']}")
    row = b.head(ws, row, ["첫 자리", "줄 수", "실제 비율", "기대 비율", "차이(절대값)", ""])
    first = row
    for dgt in range(1, 10):
        b.put(ws, row, 1, dgt)
        b.put(ws, row, 2, bf["counts"][dgt], fmt="#,##0")
        b.put(ws, row, 3, f"=IF(SUM($B${first}:$B${first + 8})=0,0,B{row}/SUM($B${first}:$B${first + 8}))", fmt="0.0%")
        b.put(ws, row, 4, math.log10(1 + 1 / dgt), fmt="0.0%")
        b.put(ws, row, 5, f"=ABS(C{row}-D{row})", fmt="0.0000")
        row += 1
    b.put(ws, row, 1, "MAD", bold=True)
    b.put(ws, row, 2, f"=SUM(B{first}:B{row - 1})", fmt="#,##0", bold=True)
    b.put(ws, row, 5, f"=SUM(E{first}:E{row - 1})/9", fmt="0.0000", bold=True, flag=bf["verdict"] in ("경계", "부적합"))
    if bf["mad"] is not None:
        # 검산 허용 오차가 0.5 라 MAD 는 100만 배로 맞춘다
        b.verify("첫 자리 분포 MAD × 1,000,000", f"='분포 분석'!E{row}*1000000", round(bf["mad"] * 1_000_000, 4))
    b.verify("첫 자리 분포 줄 수", f"='분포 분석'!B{row}", bf["n"])
    ws.cell(row + 1, 1, "기대 비율 = LOG10(1 + 1/첫 자리). MAD = 차이 아홉 개의 평균. 판정 경계(Nigrini): 0.006 이하 적합 · 0.012 이하 대체로 적합 · "
                        "0.015 이하 경계 · 그 위 부적합 (definitions/jet.yaml analyses)").font = wp.font(size=9, color=wp.MUTED)
    row += 3

    row = b.section(ws, row, mo["title"] + ("" if mo["ye_ratio"] is None else f": 결산월 매출 = 월평균의 {mo['ye_ratio']:.2f}배"))
    row = b.head(ws, row, ["월", "전표 수", "금액", "매출 순액", "월평균 대비", ""])
    first = row
    for x in mo["rows"]:
        b.put(ws, row, 1, x["ym"])
        b.put(ws, row, 2, x["count"], fmt="#,##0")
        b.put(ws, row, 3, x["amount"], fmt=wp.WON)
        b.put(ws, row, 4, common.reader._int(x["revenue"]), fmt=wp.WON)
        row += 1
    last = row - 1
    for k in range(first, last + 1):
        b.put(ws, k, 5, f"=IF(SUM($D${first}:$D${last})=0,0,D{k}/(SUM($D${first}:$D${last})/{last - first + 1}))", fmt="0.00",
              flag=k == last and mo["flag"])
    b.put(ws, row, 1, "합계", bold=True)
    for col, L in ((2, "B"), (3, "C"), (4, "D")):
        b.put(ws, row, col, f"=SUM({L}{first}:{L}{last})", fmt="#,##0" if col == 2 else wp.WON, bold=True)
    b.verify("월별 전표 수 합", f"='분포 분석'!B{row}", sum(x["count"] for x in mo["rows"]))
    b.verify("월별 매출 순액 합", f"='분포 분석'!D{row}", common.reader._int(sum(x["revenue"] for x in mo["rows"])))
    ws.cell(row + 1, 1, "매출 순액: 매출 계정 대변 − 차변. 월평균 대비는 사업연도 달 전체의 평균과 견준 배수다").font = wp.font(size=9, color=wp.MUTED)
