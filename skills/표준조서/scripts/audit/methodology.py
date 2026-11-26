"""방법론 값의 기본값(2026-10-07). 정의는 definitions/methodology.yaml.

감사인이 2700A · 2120A 노란 칸에 적은 값이 늘 앞선다. 비운 칸만 기본값으로 채우고 「기본값」 이라고 표시한다.
엔진이 중요성을 「정하는」 것이 아니라, 감사인이 고르기 전에도 분석 · 표본이 돌도록 일반적인 수준의 값을 넣어 두는 것이다.
기본값으로 돈 결과는 분석.json 의 inputs(default: true) · default_inputs 와 지휘의 할 일에 남아 감사인 확인을 받는다.

  bases_of(E)                          분석 엔진에서 벤치마크 금액 {이름: (당기, 전기)}
  materiality(bases, first_year, choice)  전체 · 수행 · 사소 금액과 고른 기준 · 백분율 · 비율, 그 근거
  fill(inputs_raw, bases, first_year)  분석 입력값의 빈 칸을 기본값으로 채운다. 채운 키 목록
  applied(d)                           _색인/분석.json 에 남은 적용값(감사인 값 또는 기본값). 실행 · 보고 단계가 읽는다
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import yaml

DEFS = Path(__file__).resolve().parents[1] / "definitions" / "methodology.yaml"
_CACHE: dict | None = None

# 2700A · 2120A 기입란 키
MAT_KEYS = ("materiality.overall", "materiality.performance", "materiality.trivial")
SIG_KEYS = ("analytics.sig_amount", "analytics.sig_ratio", "analytics.tolerable_diff")
CHOICE_KEYS = ("materiality.benchmark", "materiality.pct", "materiality.perf_ratio", "materiality.trivial_ratio")


def load() -> dict:
    global _CACHE
    if _CACHE is None:
        _CACHE = yaml.safe_load(DEFS.read_text(encoding="utf-8"))
    return _CACHE


def benchmarks() -> list[dict]:
    return load()["materiality"]["benchmarks"]


def _pct(x: float) -> str:
    s = f"{x * 100:.2f}".rstrip("0").rstrip(".")
    return f"{s}%"


def _floor(v: float) -> int:
    unit = int(load()["materiality"].get("round_to") or 1)
    return int(math.floor(v / unit) * unit)


def bases_of(E) -> dict:
    """{벤치마크 이름: (당기, 전기)}. 분석 엔진 E.q 로 읽는다. 값이 없으면 넣지 않는다."""
    out = {}
    for b in benchmarks():
        cur = E.q(b["key"], "cur")
        if cur is not None:
            out[b["name"]] = (cur, E.q(b["key"], "prior"))
    return out


def default_benchmark(bases: dict) -> tuple[str | None, str]:
    """(기준 이름, 고른 까닭). 기준서 320 A4 의 벤치마크 변동성을 단순한 규칙으로 옮긴 것이다(methodology.yaml default_rule)."""
    rule = load()["materiality"]["default_rule"]
    pbt, rev = bases.get("법인세비용차감전순이익"), bases.get("매출액")
    if pbt and pbt[0] and pbt[0] > 0 and (pbt[1] is None or pbt[1] > 0):
        if not rev or not rev[0] or pbt[0] >= rev[0] * rule["margin_min"]:
            return "법인세비용차감전순이익", "세전이익이 당기 · 전기 모두 양수"
        why = f"세전이익이 매출액의 {_pct(rule['margin_min'])} 미만(손익분기점 근처)"
    elif pbt and pbt[0] is not None:
        why = "세전이익이 손실이거나 전기 손실(변동성이 커서 쓰지 않음)"
    else:
        why = "세전이익을 계산할 수 없음"
    if rev and rev[0] and rev[0] > 0:
        return "매출액", why + ", 매출액을 씀"
    if bases.get("자산총계") and bases["자산총계"][0]:
        return "자산총계", why + ", 매출이 없어 자산총계를 씀"
    return None, "벤치마크 금액이 없음"


def materiality(bases: dict, first_year: bool = False, choice: dict | None = None, overall: float | None = None) -> dict:
    """전체 · 수행 · 사소 금액. choice 는 감사인이 고른 {benchmark, pct, perf_ratio, trivial_ratio}(없는 키는 기본값).
    overall 을 주면(감사인이 금액을 적었으면) 수행 · 사소 기본값을 그 금액에서 계산한다."""
    M = load()["materiality"]
    choice = {k: v for k, v in (choice or {}).items() if v not in (None, "")}
    by = {b["name"]: b for b in M["benchmarks"]}
    out: dict = {}
    if overall is None:
        name, why = (choice["benchmark"], "감사인이 고름") if choice.get("benchmark") in by else default_benchmark(bases)
        if name is None:
            return {"overall": None, "performance": None, "trivial": None, "why": why}
        b = by[name]
        pct = float(choice.get("pct") or b["pct"])
        base = bases.get(name, (None, None))[0]
        if base is None or base <= 0:
            return {"overall": None, "performance": None, "trivial": None, "why": f"{name} 금액이 없거나 0 이하"}
        overall = _floor(base * pct)
        out.update(benchmark=name, base=base, pct=pct,
                   overall_why=f"{name} {base:,.0f} × {_pct(pct)}. 기준: {why}" + ("" if choice.get("pct") else f". 백분율 근거: {b['basis']}"))
    else:
        out["overall_why"] = "감사인 기입"
    pr_default = M["performance"]["first_year"] if first_year else M["performance"]["default"]
    pr = float(choice.get("perf_ratio") or pr_default)
    tr = float(choice.get("trivial_ratio") or M["trivial"]["default"])
    out.update(overall=int(overall), perf_ratio=pr, trivial_ratio=tr,
               performance=_floor(overall * pr), trivial=_floor(overall * tr),
               performance_why=f"전체 중요성 × {_pct(pr)}" + ("" if choice.get("perf_ratio") else
                                                          f". 근거: {M['performance']['basis']}" + (". 이 건은 초도감사" if first_year else "")),
               trivial_why=f"전체 중요성 × {_pct(tr)}" + ("" if choice.get("trivial_ratio") else f". 근거: {M['trivial']['basis']}"))
    return out


def fill(inputs_raw: dict, bases: dict, first_year: bool = False) -> list[str]:
    """inputs_raw({키: {value, from}})의 빈 중요성 · 유의성 칸을 기본값으로 채운다. 채운 키 목록.
    감사인 값이 있는 칸은 건드리지 않는다. 채운 칸은 {"value", "from": "기본값: …", "default": True}."""
    val = lambda k: (inputs_raw.get(k) or {}).get("value")  # noqa: E731
    choice = {"benchmark": val("materiality.benchmark"), "pct": val("materiality.pct"),
              "perf_ratio": val("materiality.perf_ratio"), "trivial_ratio": val("materiality.trivial_ratio")}
    m = materiality(bases, first_year, choice, overall=val("materiality.overall"))
    filled = []

    def put(key, v, why, default=True):
        """default 가 거짓이면 감사인이 고른 값(기준 · 백분율 · 비율)으로 계산한 금액이다. 기본값 목록에 넣지 않는다."""
        if key in inputs_raw or v is None:
            return
        inputs_raw[key] = {"value": v, "from": f"{'기본값' if default else '2700A 선택으로 계산'}: {why}", "default": default}
        if default:
            filled.append(key)

    o_default = not (choice.get("benchmark") and choice.get("pct")) and val("materiality.overall") is None
    put("materiality.overall", m.get("overall"), m.get("overall_why") or m.get("why"), o_default)
    put("materiality.performance", m.get("performance"), m.get("performance_why"), o_default or not choice.get("perf_ratio"))
    put("materiality.trivial", m.get("trivial"), m.get("trivial_why"), o_default or not choice.get("trivial_ratio"))
    A = load()["analytics"]
    perf, triv = val("materiality.performance"), val("materiality.trivial")
    put("analytics.sig_amount", perf, f"수행중요성 {perf:,.0f}. 근거: {A['sig_amount']['basis']}" if perf is not None else "")
    put("analytics.sig_ratio", A["sig_ratio"]["value"], f"{_pct(A['sig_ratio']['value'])}. 근거: {A['sig_ratio']['basis']}")
    put("analytics.tolerable_diff", triv, f"명백히 사소한 금액 {triv:,.0f}. 근거: {A['tolerable_diff']['basis']}" if triv is not None else "")
    return filled


def first_year(d: Path) -> bool:
    p = Path(d) / "_색인" / "감사건.json"
    try:
        return json.loads(p.read_text(encoding="utf-8")).get("engagement_kind") == "초도감사"
    except (OSError, ValueError):
        return False


def applied(d: Path) -> dict:
    """_색인/분석.json 의 적용값 {키: {value, from, default}}. 분석 전이면 {}."""
    p = Path(d) / "_색인" / "분석.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8")).get("inputs") or {}
    except ValueError:
        return {}
