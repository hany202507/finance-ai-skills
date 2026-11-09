"""표본 결과 평가 계산(2026-11-09). 엑셀 수식과 같은 값을 엔진이 낸다.

근거: 감사기준서 530 문단 14 · 15 · A19 · A22 · A23, 500 문단 A66. 계수는 포아송 상한(AICPA Audit Guide 「Audit Sampling」 MUS 표와 같은 값).

  upper(k, c)                    오류 k 건일 때 신뢰수준 c 의 포아송 상한 F(k)
  factor_table(c, n)             [(k, F(k), ΔF(k))] k = 1..n, 소수 넷째 자리로 반올림(엑셀 표와 엔진이 같은 값을 쓴다)
  mus(rows, interval, factor, confidence, key=None, anomaly=0, tolerable=None)   금액 단위 표본 상한 평가
  ratio(rows, strata_base, anomaly=0, tolerable=None)                            비통계 표본 비율 투영
  specific(rows, population, anomaly=0, tolerable=None)                          특정 항목 선정(투영 없음)

rows 는 [{"amount": 장부 금액, "err": 왜곡표시 금액(과대계상 양수, 없으면 None), "key": 고액(전수) 여부, "stratum": 층,
"done": 검사 결과를 적었는지, "nodiff": 금액 대사가 「✗ 다름」 인데 왜곡표시 금액이 빈지}] 이다.
"""
from __future__ import annotations

import math

DIGITS = 4          # 계수 표 반올림 자리

# 판정 문구. 엑셀 수식(vouch.eval_conclude · sample_wp)과 엔진이 같은 글을 쓴다. 큰따옴표를 넣지 않는다(수식 안 문자열)
V_PENDING = "검사 결과가 빈 항목이 있어 아직 평가할 수 없음"
V_NODIFF = "「✗ 다름」 항목에 왜곡표시 금액이 없음"
V_NONE = "왜곡표시 없음. 상한(기본 정밀도)이 허용왜곡표시 이내"
V_WITHIN = "상한 왜곡표시가 허용왜곡표시 이내. 찾은 왜곡표시의 성격 · 원인을 평가에 적음"
V_EST_OVER = "모집단 왜곡표시 추정치가 허용왜곡표시 초과: 이 표본으로 모집단 결론을 낼 수 없음(문단 A22 · A23)"
V_UPPER_OVER = ("상한 왜곡표시가 허용왜곡표시 초과: 표본위험을 수용할 수 없음. 회사 조사 · 수정 요구, 표본 확대나 추가 절차(문단 A22 · A23)")
V_R_NONE = "왜곡표시 없음"
V_R_OVER = "투영 왜곡표시가 허용왜곡표시 초과: 이 표본으로 모집단 결론을 낼 수 없음(문단 A22 · A23)"
V_R_WITHIN = ("투영 왜곡표시가 허용왜곡표시 이내. 비통계 표본이라 표본위험 허용액은 계산하지 않음. "
              "허용왜곡표시에 가까울수록 표본위험이 크므로 평가에 판단을 적음(문단 A22)")
V_S_REST = "선정하지 않은 나머지가 허용왜곡표시보다 큼: 이 절차만으로 모집단 결론을 낼 수 없음. 나머지에 할 절차를 적음(500 문단 A66)"
V_S_OK = "선정하지 않은 나머지가 허용왜곡표시 이하. 찾은 왜곡표시는 투영하지 않고 그대로 집계함"


def _cdf(k: int, lam: float) -> float:
    """포아송 누적확률 P(X ≤ k; λ). 로그로 더해 λ 가 커도 넘치지 않는다."""
    if lam <= 0:
        return 1.0
    total, log_lam = 0.0, math.log(lam)
    for i in range(k + 1):
        total += math.exp(-lam + i * log_lam - math.lgamma(i + 1))
    return min(total, 1.0)


def upper(k: int, confidence: float) -> float:
    """P(X ≤ k; λ) = 1 − 신뢰수준 인 λ(이분법). k = 0 이면 −ln(1 − c)."""
    if not 0 < confidence < 1:
        raise ValueError(f"신뢰수준은 0 과 1 사이여야 합니다: {confidence}")
    target = 1 - confidence
    if k == 0:
        return -math.log(target)
    lo, hi = 0.0, k + 10 + 10 * math.sqrt(k + 1) - 3 * math.log(target)
    for _ in range(200):
        mid = (lo + hi) / 2
        if _cdf(k, mid) > target:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-12:
            break
    return (lo + hi) / 2


def confidence_of(factor: float) -> float:
    """감사인이 신뢰계수만 적었을 때의 신뢰수준(오류 0건 포아송): 1 − e^(−RF)."""
    return 1 - math.exp(-factor)


def factor_table(confidence: float, n: int) -> list[tuple[int, float, float]]:
    """[(k, F(k), ΔF(k))]. ΔF(k) = F(k) − F(k − 1). 반올림한 값을 엑셀 표와 엔진이 함께 쓴다."""
    out, prev = [], upper(0, confidence)
    for k in range(1, max(n, 0) + 1):
        f = upper(k, confidence)
        out.append((k, round(f, DIGITS), round(f - prev, DIGITS)))
        prev = f
    return out


def _err(r) -> float | None:
    v = r.get("err")
    if v in (None, ""):
        return None
    return float(v)


def mus(rows: list[dict], interval: float, factor: float, confidence: float | None, key: float | None = None,
        anomaly: float = 0.0, tolerable: float | None = None) -> dict:
    """금액 단위 표본 상한 평가. key(고액 기준) 이상 항목은 왜곡표시 그대로, 미만은 오염률 × 표본 간격으로 투영하고
    큰 순서로 증분 허용을 더한다. 과대 · 과소를 따로 낸다. 기본 정밀도 = 신뢰계수 × 표본 간격."""
    c = confidence if confidence else confidence_of(factor)
    k_limit = interval if key is None else min(key, interval)
    known = {"over": 0.0, "under": 0.0}
    pm = {"over": [], "under": []}
    for r in rows:
        e = _err(r)
        if not e:
            continue
        side = "over" if e > 0 else "under"
        if r["amount"] >= k_limit or r.get("key"):
            known[side] += abs(e)
        else:
            pm[side].append(abs(e) / r["amount"] * interval)
    table = factor_table(c, max(len(pm["over"]), len(pm["under"])))
    bp = factor * interval
    out = {"interval": interval, "factor": factor, "confidence": c, "key": k_limit, "basic": bp,
           "anomaly": anomaly or 0.0, "tolerable": tolerable}
    for side in ("over", "under"):
        ranked = sorted(pm[side], reverse=True)
        inc = sum(p * (table[i][2] - 1) for i, p in enumerate(ranked))
        an = max(anomaly or 0, 0) if side == "over" else max(-(anomaly or 0), 0)
        out[f"known_{side}"] = known[side]
        out[f"projected_{side}"] = known[side] + sum(ranked)       # 엑셀 「투영한 왜곡표시」 줄과 같은 정의(고액 포함)
        out[f"increment_{side}"] = inc
        out[f"upper_{side}"] = bp + known[side] + sum(ranked) + inc + an
        out[f"count_{side}"] = len(ranked)
    out["estimate"] = out["projected_over"] - out["projected_under"] + (anomaly or 0)
    out["verdict"] = verdict_mus(out, rows)
    return out


def verdict_mus(x: dict, rows: list[dict]) -> str:
    """엑셀 「허용왜곡표시와 견줌」 수식과 같은 순서로 판정한다."""
    if any(not r.get("done") for r in rows):
        return V_PENDING
    if any(r.get("nodiff") for r in rows):
        return V_NODIFF
    tol = x.get("tolerable")
    if tol is None:
        return ""
    hi = max(x["upper_over"], x["upper_under"])
    if _xround(hi) <= _xround(tol):
        none = x["projected_over"] == 0 and x["projected_under"] == 0 and not x["anomaly"]
        return V_NONE if none else V_WITHIN
    return V_EST_OVER if abs(x["estimate"]) > tol else V_UPPER_OVER


def _xround(v: float) -> int:
    """엑셀 ROUND(v, 0): 반은 0 에서 멀어지는 쪽으로."""
    return int(math.floor(abs(v) + 0.5)) * (1 if v >= 0 else -1)


def ratio(rows: list[dict], strata_base: dict, anomaly: float = 0.0, tolerable: float | None = None) -> dict:
    """비통계 표본(무작위 · 체계적) 비율 투영. strata_base 는 {층: 표본 대상 모집단 금액(고액 뺌)}.
    층마다 (표본 왜곡 합 ÷ 표본 장부 합) × 표본 대상 금액, 과대 · 과소 따로. 고액 왜곡은 그대로 더한다."""
    out = {"strata": {}, "known_over": 0.0, "known_under": 0.0, "projected_over": 0.0, "projected_under": 0.0,
           "anomaly": anomaly or 0.0, "tolerable": tolerable}
    for r in rows:
        e = _err(r)
        if e and r.get("key"):
            out["known_over" if e > 0 else "known_under"] += abs(e)
    for st, base in strata_base.items():
        sub = [r for r in rows if r.get("stratum") == st and not r.get("key")]
        book = sum(r["amount"] for r in sub)
        over = sum(_err(r) for r in sub if (_err(r) or 0) > 0)
        under = -sum(_err(r) for r in sub if (_err(r) or 0) < 0)
        po = over / book * base if book else 0.0
        pu = under / book * base if book else 0.0
        out["strata"][st] = {"base": base, "book": book, "over": over, "under": under, "proj_over": po, "proj_under": pu}
        out["projected_over"] += po
        out["projected_under"] += pu
    out["projected_over"] += out["known_over"]
    out["projected_under"] += out["known_under"]
    out["estimate"] = out["projected_over"] - out["projected_under"] + (anomaly or 0)
    out["verdict"] = verdict_ratio(out, rows)
    return out


def verdict_ratio(x: dict, rows: list[dict]) -> str:
    if any(not r.get("done") for r in rows):
        return V_PENDING
    if any(r.get("nodiff") for r in rows):
        return V_NODIFF
    tol = x.get("tolerable")
    if tol is None:
        return ""
    hi = max(x["projected_over"] + max(x["anomaly"], 0), x["projected_under"] + max(-x["anomaly"], 0))
    if hi == 0:
        return V_R_NONE
    return V_R_OVER if hi > tol else V_R_WITHIN


def specific(rows: list[dict], population: float, anomaly: float = 0.0, tolerable: float | None = None) -> dict:
    """특정 항목 선정(감사기준서 500 문단 A65 · A66). 투영하지 않는다. 선정하지 않은 나머지 금액을 허용왜곡표시와 견준다."""
    over = sum(_err(r) for r in rows if (_err(r) or 0) > 0)
    under = -sum(_err(r) for r in rows if (_err(r) or 0) < 0)
    chosen = sum(r["amount"] for r in rows)
    rest = population - chosen
    out = {"found_over": over, "found_under": under, "selected": chosen, "rest": rest, "anomaly": anomaly or 0.0, "tolerable": tolerable}
    if any(not r.get("done") for r in rows):
        out["verdict"] = V_PENDING
    elif any(r.get("nodiff") for r in rows):
        out["verdict"] = V_NODIFF
    elif tolerable is not None and rest > tolerable:
        out["verdict"] = V_S_REST
    else:
        out["verdict"] = V_S_OK
    return out
