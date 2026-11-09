"""표시 오류 규칙(2026-11-08, DSD 시험 3단계): 숫자는 맞는데 놓인 자리가 틀린 꼴을 엔진이 판마다 찾는다.

  합계 줄 비어 있음   「합계」 · 「계」 · 「총계」 줄의 금액이 모두 0 이나 「-」 이고, 바로 아래 이름 없는 줄이 위 줄들의 합과 같다.
                     금액을 한 줄 아래에 적은 표시 오류다(공개 연결 보고서 주석31 전기초 만기분석: 「합 계 | - | - …」 아래 줄에 234,318,205).
                     AI 가 합계 구조를 이름 없는 줄에 걸면 맞음으로 지나가 세 실행 가운데 하나가 놓쳤다. 열마다 「합계 줄 = 위 줄들의 합」
                     을 왼쪽 칸 0 으로 견주는 검증을 낸다(FALSE). 판정은 표시 오류(고칠 칸: 합계 줄, 맞는 숫자: 아래 줄 금액)다.

    checks(doc) -> [Check]
"""
from __future__ import annotations

from .base import norm
from .dsd_grid import Doc
from .dsd_links import Check, _isnum, _labels, total_kind


def _nz(v) -> bool:
    return _isnum(v) and v != 0


def checks(doc: Doc) -> list:
    out = []
    for t in doc.tables():
        if t.kind or t.finance or not t.nums:
            continue
        labels = _labels(t)
        n = len(t.nums)
        for i in range(n - 1):
            if total_kind(labels[i]) != "합계" or any(_nz(v) for v in t.nums[i][1:]):
                continue
            if norm(labels[i + 1]) or not any(_nz(v) for v in t.nums[i + 1][1:]):
                continue
            start = max([k + 1 for k in range(i) if total_kind(labels[k])] + [0])
            rows = [k for k in range(start, i) if any(_nz(v) for v in t.nums[k][1:])]
            if len(rows) < 2:
                continue
            hits = []
            for c in range(1, len(t.header)):
                vals = [t.nums[k][c] for k in rows if _isnum(t.nums[k][c])]
                below = t.nums[i + 1][c]
                if not vals or not _isnum(below):
                    continue
                total = sum(vals)
                if total and abs(total - below) <= max(1, len(vals) // 2):
                    hits.append(c)
            if not hits:
                continue
            for c in hits:
                terms = [(t.id, k, c, 1) for k in rows if _isnum(t.nums[k][c])]
                expr = " + ".join(f"{{{x}}}" for x in range(len(terms)))
                out.append(Check(f"표시-합계줄|{t.id}|{labels[i]}#{i}|{t.header[c]}#{c}", "계산", "합계", t.id, i, c, terms, None,
                                 f"「{labels[i]}」 줄 = 위 {len(terms)}줄 합(합계 줄에 금액이 없고 아래 이름 없는 줄에 {t.nums[i + 1][c]:,} 가 있다)",
                                 "규칙", "합계 줄에 금액이 없고 바로 아래 이름 없는 줄이 위 줄들의 합과 같다. 금액을 한 줄 아래에 적은 표시 오류로 보인다",
                                 tol=max(1, len(terms) // 2), expr=expr, zero_left=True))
    return out
