# -*- coding: utf-8 -*-
"""판단에 걸린 금액(stake)의 세액 영향 추정. 세율과 누진세 계산은 엔진(ctax.wp)의 것을 쓴다.

메모 stake: {"amount": 155454545, "side": "가산"} · 금액은 엔진 결과에 있는 값이나 ar.py sum 으로 적은 값.
세액 영향 = 지금 과세표준에 그 금액을 더하거나 뺐을 때 산출세액 차이. 공제 · 감면 · 최저한세 · 이월결손금 공제 한도 변화는 넣지 않는다(추정).
과세표준이 0 이하로 남으면 0 이고, 그때는 결손금이 그만큼 줄거나 는다.
"""
from __future__ import annotations

from ctax.wp.books import load_rates, rate
from ctax.wp.summary import progressive_tax

SIDES = ("가산", "차감")


def problems(st, nums: set[int], label: str) -> list[str]:
    if st is None:
        return []
    if not isinstance(st, dict) or st.get("side") not in SIDES or not isinstance(st.get("amount"), int) or isinstance(st.get("amount"), bool):
        return [f"{label}: stake 는 {{\"amount\": 정수, \"side\": \"가산\" 또는 \"차감\"}} 꼴입니다"]
    if abs(st["amount"]) not in nums:
        return [f"{label}: stake 금액 {st['amount']:,} 은 엔진 결과에 없습니다(여러 줄 합계는 ar.py sum 으로 먼저 적습니다)"]
    return []


def tax_delta(summary: dict, st: dict | None, months: int = 12) -> int | None:
    if not st or summary.get("tax_base") is None:
        return None
    brackets = rate(load_rates(), "corporate_tax", "brackets")
    base = int(summary.get("tax_base") or 0)
    amt = int(st["amount"]) * (1 if st.get("side") == "가산" else -1)
    return progressive_tax(base + amt, brackets, months) - progressive_tax(base, brackets, months)
