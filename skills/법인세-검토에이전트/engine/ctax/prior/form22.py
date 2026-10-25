"""전기 신고서 22호(기부금명세서) 줄과 세금공과금명세서의 비고 줄 읽기(10-20 AR 5차, CONTRACT.md 13절).

  rows["22"]                 [{유형, 코드, 과목, 월, 적요, 기부처, 금액}]
                             유형은 인쇄된 ①유형 글(특례 · 일반 · 기타 · 우리사주), 코드는 ② 코드(10 특례 · 40 일반 · 42 우리사주 ·
                             50 그 밖의 기부금), 월은 ④ 월별 글(「2024.07」), 적요는 ⑤ 첫 줄, 기부처는 금액 앞에 더 찍힌 글(없으면 빈 글).
  rows["세금공과금명세서"]   [{과목, 일자, 적요, 금액, 비고}] 비고 칸(「손금불산입」 · 「손금불산입취소」 등)에 글이 있는 줄만.

둘 다 쪽 글(pymupdf get_text 차례)로 읽는다. 표 칸이 한 줄씩 「유형 → 코드 → 과목 → 월 → 적요 → 금액」, 「과목 → 일자 → 적요 →
금액 → 비고」 차례로 나온다. 기부처 · 지급처 이름은 쪽 끝에 몰려 나와 줄에 붙이지 못한다(22호 기부처는 금액 바로 앞에 찍힌 것만).
읽지 못한 줄은 넣지 않는다. 당기 AR(전기 그 밖의 기부금 · 불공제 매입세액 손금불산입)과 기부금 조서 분류 기본값이 읽는다.
"""
from __future__ import annotations

import re

KINDS_22 = ("특례", "일반", "기타", "우리사주", "그밖", "그 밖")
CODE_22 = re.compile(r"^(10|40|42|50)$")
MONTH = re.compile(r"^\d{4}[.\-/]\s?\d{1,2}$")
AMOUNT = re.compile(r"^(-?\d{1,3}(?:,\d{3})+|-?\d{1,9})(?:\s+(\S.*))?$")
DAY = re.compile(r"^\d{1,2}[/.]\d{1,2}$")
FOOT = re.compile(r"^(계|합계|소계|⑨소계|손금불산입계)$")


def _int(s: str) -> int:
    return int(s.replace(",", ""))


def _lines(text: str) -> list[str]:
    return [ln.strip() for ln in str(text or "").splitlines() if ln.strip()]


def rows_22(text: str) -> list[dict]:
    """22호 쪽 글 하나 → 줄 목록."""
    ls = _lines(text)
    out = []
    i = 0
    while i < len(ls) - 4:
        if ls[i] not in KINDS_22 or not CODE_22.match(ls[i + 1]):
            i += 1
            continue
        kind, code, subject = ls[i], ls[i + 1], ls[i + 2]
        j = i + 3
        month = ""
        if j < len(ls) and MONTH.match(ls[j]):
            month, j = ls[j].replace(" ", ""), j + 1
        texts, amount = [], None
        while j < len(ls) and j <= i + 8:
            m = AMOUNT.match(ls[j])
            if m and ("," in m.group(1) or len(m.group(1).lstrip("-")) >= 4):
                amount = _int(m.group(1))
                break
            if ls[j] in KINDS_22 or FOOT.match(ls[j]):
                break
            texts.append(ls[j])
            j += 1
        if amount is None or not texts:
            i += 1
            continue
        out.append({"유형": kind, "코드": code, "과목": subject, "월": month, "적요": texts[0],
                    "기부처": " ".join(texts[1:]), "금액": amount})
        i = j + 1
    return out


def rows_taxes(text: str) -> list[dict]:
    """세금공과금명세서 쪽 글 하나 → 비고가 있는 줄 목록."""
    ls = _lines(text)
    out = []
    for i in range(1, len(ls) - 1):
        if not DAY.match(ls[i]) or AMOUNT.match(ls[i - 1]) or DAY.match(ls[i - 1]):
            continue
        subject = ls[i - 1]
        j, texts, amount, note = i + 1, [], None, ""
        while j < len(ls) and j <= i + 4:
            m = AMOUNT.match(ls[j])
            if m:
                amount, note = _int(m.group(1)), (m.group(2) or "").strip()
                break
            if DAY.match(ls[j]) or FOOT.match(ls[j]):
                break
            texts.append(ls[j])
            j += 1
        if amount is None:
            continue
        if not note and j + 1 < len(ls) and ls[j + 1].startswith("손금") and not FOOT.match(ls[j + 1]):
            note = ls[j + 1]
        if note:
            out.append({"과목": subject, "일자": ls[i], "적요": " ".join(texts), "금액": amount, "비고": note})
    return out


def read_22(pages: list[dict]) -> list[dict]:
    rows = []
    for p in pages:
        rows += rows_22(p.get("text") or "")
    return rows


def read_taxes(pages: list[dict]) -> list[dict]:
    rows = []
    for p in pages:
        rows += rows_taxes(p.get("text") or "")
    return rows
