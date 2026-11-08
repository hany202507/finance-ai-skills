"""읽지 않은 금액 열 찾기(2026-10-27). 받은 재무제표 · 분개장에 금액이 들어 있는데 엔진이 읽지 않은 열이 있으면 경고로 남긴다.

재무제표 5열(과목 · 당기 소계 · 당기 합계 · 전기 소계 · 전기 합계) 밖 열에 금액이 있으면 세목 열 · 다른 기간 열을 놓친 것이다.
대차 · 합계는 맞아도 그 열의 과목 금액이 사라진다(개발자 서버 `books/reader/extract.py` 의 같은 검사를 우리 고정 열 꼴에 맞춰 다시 씀).
분개장은 읽는 열(전표일자 · 차변 · 대변 등) 밖에 금액 열(공급가액 · 부가세 등)이 있거나, 더존 ERP 꼴에서 한 행에 차변 · 대변 금액이
모두 있어 한쪽만 읽은 경우다. 경고는 장부.json `warnings` 에 쌓고 대사(checks) 결과와 끝 코드는 바꾸지 않는다.
"""
from __future__ import annotations

from .xlsxread import col_name, compact, date_text, num, text

ID = "unread_columns"
TITLE = "읽지 않은 금액 열"
FS_COLS = 5                        # 재무제표에서 읽는 열 수(fs.py _cells)
EXAMPLES = 3
# 머리 글에 이 낱말이 있으면 금액 열이 아니다(코드 · 번호 · 날짜)
NOT_MONEY = ("코드", "code", "번호", "no", "일자", "날짜", "사원", "부서", "프로젝트", "계정", "과목", "거래처", "적요", "구분")


def _warn(rel: str, found: dict, heads: dict, extra: str = "") -> dict | None:
    if not found and not extra:
        return None
    cols = [{"col": col_name(c), "header": heads.get(c, ""), "cells": len(xs), "examples": xs[:EXAMPLES]}
            for c, xs in sorted(found.items())]
    parts = [f"{x['col']}열{'(' + x['header'] + ')' if x['header'] else ''} 금액 {x['cells']}칸(예: {', '.join(x['examples'])})"
             for x in cols]
    if extra:
        parts.append(extra)
    return {"id": ID, "file": rel, "title": TITLE, "columns": cols,
            "detail": " · ".join(parts) + ". 이 금액은 장부.json 에 들어가지 않았습니다. 받은 파일의 열 꼴을 확인합니다"}


def fs_unread(rel: str, rows: list[list], off: int = 0) -> dict | None:
    """재무제표: 과목이 있는 줄의 6열부터 금액이 있는 칸. off 는 머리줄 위에서 건너뛴 행 수(칸 주소에 더한다)."""
    from .fs import _body
    body = _body(rows)
    start = len(rows) - len(body)
    head = rows[start - 1] if start >= 1 else []
    heads = {c: text(v) for c, v in enumerate(head or []) if c >= FS_COLS and text(v)}
    found: dict = {}
    for n, r in enumerate(body, start + 1 + off):
        r = list(r or [])
        if not r or r[0] is None or compact(r[0]) == "":
            continue
        for c in range(FS_COLS, len(r)):
            a = num(r[c])
            if a:
                found.setdefault(c, []).append(f"{col_name(c)}{n} {text(r[0])} {a:,}")
    return _warn(rel, found, heads)


def _money_head(h: str) -> bool:
    k = compact(h).lower()
    return not any(w in k for w in NOT_MONEY)


def journal_unread(rel: str, rows: list[list], used: set, date_col: int | None, pairs=(), off: int = 0) -> dict | None:
    """분개장: 읽는 열(used) 밖 금액 열. pairs 는 더존 ERP 꼴 (차변 계정 열, 차변 금액 열, 대변 계정 열, 대변 금액 열)로,
    한 행에서 읽지 않은 쪽 금액이 있는 칸을 센다."""
    if not rows:
        return None
    head = [text(x) for x in rows[0]]
    heads = {c: h for c, h in enumerate(head) if h}
    found: dict = {}
    side = []
    for n, r in enumerate(rows[1:], 2 + off):
        r = list(r or [])
        if date_col is None or date_col >= len(r) or date_text(r[date_col]) is None:
            continue
        for c in range(len(r)):
            if c in used or not _money_head(heads.get(c, "")):
                continue
            a = num(r[c])
            if a:
                found.setdefault(c, []).append(f"{col_name(c)}{n} {a:,}")
        if pairs:
            dr_acc, dr_amt, cr_acc, cr_amt = pairs
            get = lambda i: r[i] if i is not None and i < len(r) else None    # noqa: E731
            if text(get(dr_acc)) and num(get(cr_amt)):
                side.append(f"{col_name(cr_amt)}{n} {num(get(cr_amt)):,}")
            elif not text(get(dr_acc)) and text(get(cr_acc)) and num(get(dr_amt)):
                side.append(f"{col_name(dr_amt)}{n} {num(get(dr_amt)):,}")
    extra = (f"한 행에 차변 · 대변 금액이 모두 있어 계정이 적힌 쪽만 읽은 행 {len(side)}개(예: {', '.join(side[:EXAMPLES])})"
             if side else "")
    return _warn(rel, found, heads, extra)
