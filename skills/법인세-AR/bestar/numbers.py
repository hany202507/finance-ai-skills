# -*- coding: utf-8 -*-
"""모델이 쓴 글 속 금액이 엔진 결과에 있는 값인지 검사한다. 금액 토큰은 엔진 메모 검사(ctax.ar.memo)와 같은 규칙이다."""
from __future__ import annotations

import csv
import re
from pathlib import Path

from ctax.ar import memo as M

from bestar import paths


def journal_rows(c) -> list[dict]:
    """전표.csv 줄. line 은 머리줄 다음부터 1."""
    path = paths.index(c) / "전표.csv"
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as f:
        return [{"line": n, **row} for n, row in enumerate(csv.DictReader(f), 1)]


def known(c) -> set[int]:
    """장부.json · 전기.json · AR.json · 조정.json(조서 계산)의 숫자, 전표 금액, ar.py sum · pdf 로 적은 숫자."""
    out: set[int] = set()
    for name in ("장부.json", "전기.json", "AR.json", "조정.json"):
        M.numbers_of(paths.read_json(paths.index(c) / name, {}), out)
    from bestar import facts
    out |= facts.amounts(c)
    for row in journal_rows(c):
        for k in ("debit", "credit"):
            try:
                out.add(abs(int(float(row.get(k) or 0))))
            except ValueError:
                pass
    return out


# 금액이 아닌 숫자: 전표 줄 · 전표 번호 · 쪽 · 행 · 날짜
REF_RE = re.compile(r"전표\s*(?:번호\s*)?\d+\s*(?:번째\s*)?(?:줄|번|행)?|\d+\s*번째\s*줄|\d+\s*(?:줄|행|쪽)(?![가-힣])|p\.?\s*\d+|\d{4}[-.]\d{1,2}[-.]\d{1,2}")


def amount_tokens(text: str):
    return M.tokens(REF_RE.sub(" ", text))


def texts(obj, where: str = ""):
    """사전 · 목록 안의 글 전부 (어디, 글)."""
    if isinstance(obj, str):
        yield where, obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from texts(v, f"{where}.{k}" if where else k)
    elif isinstance(obj, list):
        for n, v in enumerate(obj):
            yield from texts(v, f"{where}[{n}]")


# 문체검수 스킬 patterns.py 의 「X가 아니라 Y」 규칙과 같은 꼴(10-19: 단계 검사가 이것을 걸러내지 않아 finish 뒤 문체검수에서야 걸렸다)
NOT_BUT = re.compile(r"(이|가)\s?아니라(?!면|서|고)")


def style_problems(obj, label: str) -> list[str]:
    probs = []
    for where, text in texts(obj):
        if "—" in text:
            probs.append(f"{label} {where}: 줄표(—)를 쓰지 않습니다")
        if "?" in text or "？" in text:
            probs.append(f"{label} {where}: 물음표를 쓰지 않습니다")
        m = NOT_BUT.search(text)
        if m:
            probs.append(f"{label} {where}: 「…{m.group(0)}」 처럼 앞을 부정하고 뒤를 말하는 문장 대신 뒤의 말만 씁니다(문체검수와 같은 규칙)")
    return probs


def values(obj, where: str = ""):
    """사전 · 목록 안의 정수 값 전부 (어디, 값). 참거짓은 뺀다."""
    if isinstance(obj, bool):
        return
    if isinstance(obj, (int, float)):
        yield where, obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from values(v, f"{where}.{k}" if where else k)
    elif isinstance(obj, list):
        for n, v in enumerate(obj):
            yield from values(v, f"{where}[{n}]")


def amount_problems(obj, nums: set[int], label: str, skip: tuple[str, ...] = ()) -> list[str]:
    probs = []
    for where, v in values(obj):
        if any(where.split(".")[-1].startswith(s) for s in skip):
            continue
        if abs(v) >= 10000 and abs(int(round(v))) not in nums:
            probs.append(f"{label} {where}: 엔진 결과(장부 · 전기 · AR · 전표)에 없는 금액 {int(v):,}")
    for where, text in texts(obj):
        if any(where.split(".")[-1].startswith(s) for s in skip):
            continue
        for raw, v in amount_tokens(text):
            if v not in nums:
                probs.append(f"{label} {where}: 엔진 결과(장부 · 전기 · AR · 전표)에 없는 금액 {raw}")
    return probs
