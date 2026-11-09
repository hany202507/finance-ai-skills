"""표본: 금액 단위 표본(MUS)과 무작위 표본(R4, 2026-10-05).

방법론 값(신뢰계수 · 기본 시드 · 기본 위험 수준)은 definitions/sampling.yaml 에 있다. 같은 시드 · 같은 모집단이면 같은 표본이다.

  plan(population, tolerable, risk=None, expected=0)   표본 크기 계산 근거 {total, count, tolerable, expected, ef, risk, confidence, factor, interval, size}
  mus(items, tolerable, risk=None, seed=None)          금액 단위 표본. 간격마다 한 점, 시작점은 시드 고정 난수
  random_sample(items, n, seed=None)                   무작위 표본(금액 가중 없음)
  systematic(items, n, seed=None)                      체계적 표본(항목 수 간격)
  allocate(n, weights)                                 계층마다 표본 수 배분(금액 비례, 큰 나머지 순)

예상 왜곡표시(2026-11-09): 표본 간격 = (허용왜곡표시 − 예상 왜곡표시 × 확장계수) ÷ 신뢰계수. 확장계수는 sampling.yaml expansion.
평가 계산은 sampling_eval.py 에 있다.

items 는 [(열쇠, 금액)] 이다. 금액이 0 이하인 항목은 모집단에서 빼고 따로 알린다(음수 잔액은 표본이 아니라 따로 본다).
"""
from __future__ import annotations

import random

from .common import ceil, load_def


def settings() -> dict:
    return load_def("sampling.yaml")


def chosen(d, no: str, what: str) -> dict:
    """표본 시트에 감사인이 고른 위험 수준 · 직접 적은 신뢰계수(이미 있는 조서의 기입란). 없으면 {}(2026-10-07).
    다시 만들 때 이 값으로 표본을 뽑는다. 명령의 --risk 가 있으면 그것이 앞선다(호출하는 쪽에서)."""
    from .common import old_inputs

    old = {lab: v for (_, lab), v in old_inputs(d, no).items()}
    out = {}
    r = str(old.get(f"위험 수준 확인: {what}") or "").strip()
    if r in settings()["risk_levels"]:
        out["risk"] = r
    f = old.get(f"신뢰계수 직접 입력: {what}")
    try:
        f = float(str(f).replace(",", "")) if f not in (None, "") else None
    except ValueError:
        f = None
    if f and f > 0:
        out["factor"] = f
    e = old.get(f"예상 왜곡표시 직접 입력: {what}")
    try:
        e = float(str(e).replace(",", "")) if e not in (None, "") else None
    except ValueError:
        e = None
    if e and e > 0:
        out["expected"] = e
    return out


def chosen_for(ctx: dict, no: str, what: str) -> dict:
    """명령 --risk 가 있으면 시트의 위험 수준 · 신뢰계수는 버리고 예상 왜곡표시만 쓴다(2026-11-09)."""
    ch = chosen(ctx["d"], no, what)
    if ctx.get("risk"):
        ch.pop("risk", None)
        ch.pop("factor", None)
    return ch


def expansion_factor(confidence: float | None, factor: float | None = None) -> float:
    """잘못된 수용 위험(1 − 신뢰수준)별 확장계수(sampling.yaml expansion). 표 사이는 직선 보간, 밖은 끝 값."""
    import math

    if not confidence:
        confidence = 1 - math.exp(-(factor or 0))
    pts = sorted((float(k), float(v)) for k, v in settings()["expansion"].items())
    ria = 1 - confidence
    if ria <= pts[0][0]:
        return pts[0][1]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if ria <= x1:
            return round(y0 + (y1 - y0) * (ria - x0) / (x1 - x0), 4)
    return pts[-1][1]


def plan(total: float, count: int, tolerable: float, risk: str | None = None, factor: float | None = None, expected: float = 0) -> dict:
    s = settings()
    risk = risk or s["default_risk"]
    lv = s["risk_levels"].get(risk)
    if factor:                               # 감사인이 신뢰계수를 직접 적었다(위험 수준 표보다 앞선다)
        lv, risk = {"confidence": None, "factor": float(factor)}, f"{risk}(신뢰계수 직접 입력)"
    if lv is None:
        raise ValueError(f"sampling.yaml 에 없는 위험 수준입니다: {risk} (있는 값: {', '.join(s['risk_levels'])})")
    if not tolerable or tolerable <= 0:
        raise ValueError("허용왜곡표시(수행중요성)가 없어 표본 크기를 계산할 수 없습니다")
    expected = float(expected or 0)
    ef = expansion_factor(lv["confidence"], lv["factor"]) if expected else 0.0
    room = tolerable - expected * ef
    if room <= 0:
        raise ValueError(f"예상 왜곡표시({expected:,.0f}원) × 확장계수({ef}) 가 허용왜곡표시({tolerable:,.0f}원) 이상이라 표본으로 결론을 낼 수 없습니다")
    interval = room / lv["factor"]
    size = ceil(total / interval) if total > 0 else 0       # 점 수. 큰 항목에 점이 여럿 떨어지면 고른 항목 수는 이보다 적다
    return {"total": total, "count": count, "tolerable": tolerable, "expected": expected, "ef": ef, "risk": risk,
            "confidence": lv["confidence"], "factor": lv["factor"], "interval": interval, "size": size}


def mus(items: list[tuple], tolerable: float, risk: str | None = None, seed: int | None = None, factor: float | None = None,
        expected: float = 0) -> dict:
    """금액 단위 표본. 누적 금액 위에 시작점 + 간격 × k 인 점을 찍고, 점이 떨어진 항목을 고른다.
    간격 이상인 항목은 반드시 한 번 이상 걸린다(고액 항목). 돌려주는 것에 항목마다 걸린 점 수가 있다."""
    seed = settings()["seed"] if seed is None else seed
    pop = [(k, a) for k, a in items if a and a > 0]
    excluded = [(k, a) for k, a in items if not a or a <= 0]
    total = sum(a for _, a in pop)
    p = plan(total, len(pop), tolerable, risk, factor, expected)
    rng = random.Random(seed)
    start = rng.uniform(0, p["interval"]) if total > 0 else 0.0
    picks: dict = {}
    cum = 0.0
    point = start
    rows = []
    for k, a in pop:
        cum += a
        hits = 0
        while point < cum and point < total:
            hits += 1
            point += p["interval"]
        if hits:
            picks[k] = hits
        rows.append({"key": k, "amount": a, "cum": cum, "hits": hits, "key_item": a >= p["interval"]})
    return {**p, "seed": seed, "start": start, "rows": rows, "selected": [r for r in rows if r["hits"]],
            "excluded": excluded, "method": "금액 단위 표본(MUS)"}


def random_sample(items: list[tuple], n: int, seed: int | None = None) -> dict:
    seed = settings()["seed"] if seed is None else seed
    pop = [(k, a) for k, a in items if a and a > 0]
    rng = random.Random(seed)
    idx = sorted(rng.sample(range(len(pop)), min(n, len(pop))))
    return {"seed": seed, "size": len(idx), "selected": [{"key": pop[i][0], "amount": pop[i][1]} for i in idx],
            "method": "무작위 표본"}


def systematic(items: list[tuple], n: int, seed: int | None = None) -> dict:
    """체계적 표본: 항목 수 간격 k = N ÷ n, 시작점은 [0, k) 의 시드 고정 난수. 순서는 받은 순서(파일 행 순서) 그대로다."""
    seed = settings()["seed"] if seed is None else seed
    pop = [(k, a) for k, a in items if a and a > 0]
    n = min(n, len(pop))
    if n <= 0:
        return {"seed": seed, "size": 0, "step": None, "start": None, "selected": [], "method": "체계적 표본"}
    step = len(pop) / n
    start = random.Random(seed).uniform(0, step)
    idx = sorted({min(int(start + i * step), len(pop) - 1) for i in range(n)})
    return {"seed": seed, "size": len(idx), "step": step, "start": start,
            "selected": [{"key": pop[i][0], "amount": pop[i][1]} for i in idx], "method": "체계적 표본"}


def allocate(n: int, weights: list[float]) -> list[int]:
    """n 을 weights 에 비례해 나눈다(큰 나머지 순). 금액이 있는 계층은 적어도 1 개."""
    tot = sum(w for w in weights if w > 0)
    if n <= 0 or tot <= 0:
        return [0] * len(weights)
    raw = [n * w / tot if w > 0 else 0 for w in weights]
    out = [int(x) for x in raw]
    for i in sorted(range(len(raw)), key=lambda i: raw[i] - out[i], reverse=True)[: n - sum(out)]:
        out[i] += 1
    for i, w in enumerate(weights):
        if w > 0 and out[i] == 0:
            out[i] = 1
    # 1 개씩 채운 만큼 큰 계층에서 덜어 합을 n 에 맞춘다. 금액 있는 계층 수가 n 보다 많으면 계층마다 1 개라 n 을 넘는다
    while sum(out) > n and max(out) > 1:
        out[max(range(len(out)), key=lambda i: (out[i], raw[i]))] -= 1
    return out
