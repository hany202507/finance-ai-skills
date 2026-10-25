"""전기 신고서의 고용 세액공제 계산서 읽기. 조세특례제한법 시행규칙 별지 제10호의8서식(고용 증대 기업에 대한 공제세액계산서)과
별지 제10호의9서식(통합고용세액공제 공제세액계산서)이 전기.json `employment` 가 된다(CONTRACT.md 13절).

당기 공제감면 조서(wp/papers/credits.py)가 2 · 3차 연도 공제액을 사람 손 없이 쓰려고 읽는다. 전기 1차년도 세액공제액 계가 당기
2차 연도 금액이고, 전기 2차년도 세액공제액이 당기 3차 연도 금액이다(조특법 제29조의7 제1항 · 제29조의8 제1항).

  employment  {"10의8": {...}, "10의9": {...}}. 신고서에 그 서식이 없으면 키가 없고, 서식은 있는데 값이 하나도 없으면 null.
    form · name · 판(쪽 머리의 개정일 「2024.03.22」) · page(첫 쪽) · fy(과세연도 끝 날의 연도) · fy_start · fy_end
    cells       서식 란 번호를 키로 둔 값(읽은 것만). 금액은 정수, 인원은 인쇄된 소수 둘째 자리 숫자.
    by_year     [{차수, year, amount, 청년등, 청년등외, first_headcount}] 차수 1 · 2 · 3 차례. year 는 그 몫을 처음 공제받은
                과세연도(fy, fy - 1, fy - 2), first_headcount 는 그 과세연도의 상시근로자 수(다음 해 감소 여부의 기준).
                값 란이 비어 있으면 금액 0, 머리글을 못 찾았으면 null.
    first_year  금액이 있는 차수 가운데 가장 이른 year(없으면 null)
    total       세액공제액(1차 + 2차 + 3차, 10호의9 는 추가공제 포함) 란 값
    headcount   {"prior": {상시, 청년등, 청년등외}, "current": {...}}, 10호의9 는 "prior2"(직전전 과세연도)도.
    extra       10호의9 만. 추가공제 세액공제액 계(정규직 전환 · 육아휴직 복귀)

란 번호(법제처 서식 PDF 로 확인)
  10호의8(2024. 3. 22. 개정)  ⑥ ⑦ ⑧ 상시근로자 수(해당 · 직전 · 증가), ⑨ ⑩ ⑪ 청년등, ⑫ ⑬ ⑭ 청년등 외, ⑮ 1차년도 세액공제액,
      ⑯ ⑰ ⑱ 2차년도 상시근로자 수(해당 · 1차년도 · 증가), ⑲ ⑳ 1차년도 청년등 · 청년등 외 증가 세액공제액, ㉑ 2차년도 세액공제액,
      ㉒ ㉓ ㉔ 3차년도 상시근로자 수, ㉕ ㉖ ㉗ 3차년도 세액공제액, 「세액공제액」 = ⑮ + ㉑ + ㉗.
  10호의9(2026. 3. 20. 개정 서식(1))  ⑥ ⑦ ⑧ 상시근로자 현황(`6_직전전` · `6_직전` · `6_해당` 꼴), ⑨ 정규직 전환 · ⑩ 육아휴직 복귀자 수,
      ⑪ ⑫ ⑬ 상시근로자 수, ⑭ ⑮ ⑯ 청년등, ⑰ ⑱ ⑲ 청년등 외, ⑳ 1차년도 세액공제액, ㉑ ㉒ ㉓ · ㉔ ㉕ ㉖ 2차년도,
      ㉗ ㉘ ㉙ · ㉚ ㉛ ㉜ 3차년도, ㉝ ㉞ ㉟ 추가공제 요건, ㊱ 추가공제 세액공제액, 「세액공제액」 = ⑳ + ㉖ + ㉜ + ㊱.
  1차년도 표는 줄마다 `<란>_<법인 구분>_<지역>_<청년등 · 청년등외>`(금액)와 끝에 `_인원`(증가 인원 수), 계 줄은 `<란>_중소_계` 꼴,
  세 구분의 계를 더한 값이 `<란>_계`. 추가공제 표는 `36_중소_육아휴직복귀자` 꼴.

읽는 법. 신고 프로그램이 ⑯ 보다 큰 동그라미 번호를 모두 같은 글자로 찍어서 란 번호는 글자로 읽지 못한다. 그래서 칸 테두리 선으로 만든
격자(grid.Grid)에서 머리글 칸을 글로 찾고(동그라미 번호 · 기호는 떼고 맞춘다) 바로 아래 칸이나 같은 줄 칸의 값을 읽는다. 10호의9
2025. 6. 30. 개정 서식은 머리글이 2026. 3. 20. 개정 서식(1)과 같아 같은 란 번호로 둔다. 신청인 란(성명 · 생년월일)은 읽지 않는다.

검산(안 맞으면 문제 글): 증가 인원 = 해당 - 직전, 1차년도 표 줄 합 = 계, 2 · 3차년도 세액공제액 = 청년등 + 청년등 외,
세액공제액 = 차수별 금액의 합. 8호 부표3 당기분과 맞추는 일은 read.build 가 한다.
"""
from __future__ import annotations

import re
import unicodedata
from decimal import Decimal

from ctax.prior.grid import Box, Grid, amount, norm

NEAR = 3.0                              # 같은 줄 · 바로 아래 칸으로 보는 거리(pt)
NAMES = {"10의8": "고용 증대 기업에 대한 공제세액계산서", "10의9": "통합고용세액공제 공제세액계산서"}
EDITIONS = {"10의8": {"2024.03.22"}, "10의9": {"2025.06.30", "2026.03.20"}}
REVISED = re.compile(r"개정(\d{4})\.(\d{1,2})\.(\d{1,2})")
PERIOD = re.compile(r"(\d{4})년(\d{1,2})월(\d{1,2})일부터(\d{4})년(\d{1,2})월(\d{1,2})일")
COUNT = re.compile(r"^[△\-]?\d+(\.\d+)?$")
N = r"^\d{0,2}"                          # 한컴 글꼴 서식은 ⑳ 보다 큰 번호를 동그라미와 숫자로 따로 찍는다
H_ALL = N + r"해당과세연도상시근로자수$"
H_YOUTH = N + r"해당과세연도청년등상시근로자수$"
H_OTHER = N + r"해당과세연도청년등상시근로자(외|를제외한)상시근로자수$"
H_Y2 = N + r"2차년도\(해당과세연도\)상시근로자수$"
H_Y3 = N + r"3차년도\(해당과세연도\)상시근로자수$"
CORPS = {"중소기업": "중소", "중견기업": "중견", "일반기업": "일반"}
REGIONS = ("수도권내", "수도권밖")
FIRST_ORDER = ("중소_수도권내_청년등", "중소_수도권내_청년등외", "중소_수도권밖_청년등", "중소_수도권밖_청년등외", "중소_계",
               "중견_청년등", "중견_청년등외", "중견_계", "일반_청년등", "일반_청년등외", "일반_계")


def label(text: str) -> str:
    """머리글 비교용 글. 공백을 지우고 동그라미 번호 · 기호 글자(유니코드 No · So · Co)를 뗀다."""
    return "".join(c for c in norm(text) if unicodedata.category(c) not in ("No", "So", "Co"))


def count(text: str):
    """인원 글 → 소수(float). 아니면 None."""
    t = norm(text).replace(",", "")
    if not COUNT.match(t):
        return None
    v = float(t.lstrip("△-"))
    return -v if t[0] in "△-" else v


class Form:
    """서식 하나(쪽 여럿)를 읽는 동안의 상태. cells 는 란 값, why 는 문제 글."""

    def __init__(self, key: str, pages: list[dict]):
        self.key = key
        self.pages = pages
        self.grids = [Grid.from_page(p) for p in pages if p.get("grid")]
        self.cells: dict = {}
        self.why: list[str] = []
        self.missing: list[str] = []

    # 칸 찾기
    def find(self, pattern: str, g: Grid | None = None) -> list[tuple[Grid, Box]]:
        """머리글 글(label)이 pattern 에 맞는 칸(쪽 차례, 위 → 아래, 왼쪽 → 오른쪽)."""
        rx = re.compile(pattern)
        out = []
        for grid in ([g] if g is not None else self.grids):
            hit = [b for b, t in grid.boxes.items() if rx.search(label(t))]
            out += [(grid, b) for b in sorted(hit, key=lambda b: (b.top, b.left))]
        return out

    def head(self, pattern: str, g: Grid | None = None):
        """find 가운데 가장 좁은 칸(머리글은 넓은 설명 칸과 겹쳐 맞을 수 있다). 없으면 (None, None)."""
        found = self.find(pattern, g)
        return min(found, key=lambda gb: gb[1].width) if found else (None, None)

    @staticmethod
    def below(g: Grid, h: Box) -> Box | None:
        """머리글 칸 바로 아래, 같은 너비의 값 칸. 비어 있으면(글자가 없으면) None."""
        return next((b for b in g.boxes if abs(b.left - h.left) <= NEAR and abs(b.right - h.right) <= NEAR
                     and abs(b.top - h.bottom) <= NEAR), None)

    @staticmethod
    def beside(g: Grid, row: Box, col: Box) -> Box | None:
        """row 와 같은 줄이고 가운데가 col 의 가로 범위에 드는 칸."""
        return next((b for b in g.boxes if abs(b.top - row.top) <= NEAR and col.left - 1 <= b.xc <= col.right + 1
                     and b != row), None)

    # 값 넣기
    def put(self, code: str, g: Grid, box: Box | None, kind: str):
        """칸 값을 cells[code] 에. kind 「won」 금액 · 「count」 인원. 빈칸이면 넣지 않고 None, 글을 못 읽으면 문제 글."""
        if box is None:
            return None
        raw = g.text(box)
        v = amount(raw) if kind == "won" else count(raw)
        if v is None:
            if norm(raw) not in ("", "-"):
                self.why.append(f"{self.title} {code} 란 글 「{raw[:20]}」 을 숫자로 읽지 못했습니다({g.page_no}쪽)")
            return None
        self.cells[code] = v
        return v

    @property
    def title(self) -> str:
        return f"조특 {self.key[:2]}호{self.key[2:]}"

    def triple(self, pattern: str, codes: tuple, what: str, nth: int = 0) -> bool:
        """머리글 셋이 한 줄에 나란하고 값이 바로 아래 줄에 있는 표(해당 · 직전 · 증가 인원). 맨 왼쪽 머리글을 pattern 으로 찾아
        같은 줄 칸을 왼쪽부터 codes 에 잇는다. 증가 = 해당 - 직전 을 본다. 머리글이 없으면 False."""
        found = self.find(pattern)
        if len(found) <= nth:
            self.missing.append(what)
            return False
        g, h = found[nth]
        heads = sorted((b for b in g.boxes if abs(b.top - h.top) <= NEAR and b.left >= h.left - NEAR), key=lambda b: b.left)
        vals = [self.put(code, g, self.below(g, b), "count") for code, b in zip(codes, heads)]
        if len(vals) == 3 and all(v is not None for v in vals) and _d(vals[0]) - _d(vals[1]) != _d(vals[2]):
            self.why.append(f"{self.title} {what} 증가 인원 {vals[2]} 이 해당 {vals[0]} - 직전 {vals[1]} 과 다릅니다")
        return True

    def first_table(self, code: str) -> bool:
        """1차년도 세액공제액 계산 표. 줄 이름(청년등 · 청년등외 · 계)을 법인 구분 · 지역 칸의 세로 범위로 묶는다."""
        g, amt = self.head(N + r"1차년도세액공제액$")
        if amt is None:
            self.missing.append("1차년도 세액공제액 계산 표")
            return False
        _, cnt = self.head(r"^직전과세연도대비상시근로자증가인원", g)
        stop = min((b.top for _, b in self.find(r"^나\.2차년도", g) if b.top > amt.bottom), default=1e9)
        body = [b for b in g.boxes if amt.bottom - NEAR <= b.top < stop]
        left = (cnt.left if cnt is not None else amt.left) + 2
        names = sorted((b for b in body if label(g.text(b)) in ("청년등", "청년등외", "계") and b.right <= left),
                       key=lambda b: b.top)
        keys = []
        for b in names:
            corp = next((CORPS[label(g.text(c))] for c in body if label(g.text(c)) in CORPS
                         and c.top - 1 <= b.yc <= c.bottom + 1), None)
            region = next((label(g.text(c)) for c in body if label(g.text(c)) in REGIONS
                           and c.top - 1 <= b.yc <= c.bottom + 1), None)
            name = label(g.text(b))
            keys.append("_".join(k for k in (corp, region if name != "계" else None, name) if k) if corp else None)
        if any(k is None for k in keys) or len(set(keys)) != len(keys):
            if len(names) != len(FIRST_ORDER):
                self.why.append(f"{self.title} 1차년도 세액공제액 계산 표의 줄(법인 구분)을 가리지 못했습니다({g.page_no}쪽)")
                return True
            keys = list(FIRST_ORDER)
        for key, b in zip(keys, names):
            self.put(f"{code}_{key}", g, self.beside(g, b, amt), "won")
            if cnt is not None:
                self.put(f"{code}_{key}_인원", g, self.beside(g, b, cnt), "count")
        totals = []
        for corp in CORPS.values():
            parts = [v for k, v in self.cells.items() if re.fullmatch(rf"{code}_{corp}_(?!계).*(?<!_인원)", k)]
            total = self.cells.get(f"{code}_{corp}_계")
            if parts and total is None:
                self.why.append(f"{self.title} 1차년도 세액공제액 {corp}기업 계 란이 비어 있습니다(줄 합 {sum(parts):,})")
            elif total is not None and parts and sum(parts) != total:
                self.why.append(f"{self.title} 1차년도 세액공제액 {corp}기업 계 {total:,} 이 줄 합 {sum(parts):,} 과 다릅니다")
            if total is not None:
                totals.append(total)
        if totals:
            self.cells[f"{code}_계"] = sum(totals)
        return True

    def later_table(self, year: int, codes: tuple) -> bool:
        """2 · 3차년도 세액공제액 계산 표. codes 는 (청년등 증가 세액공제액, 청년등 외 증가 세액공제액, n차년도 세액공제액).
        값은 머리글 아래 「부」 · 「여」 줄 가운데 찍힌 줄에서 읽는다(표 끝은 왼쪽 열의 「부」 · 「여」 칸이 끝나는 곳)."""
        g, total = self.head(N + rf"{year}차년도세액공제액$")
        if total is None:
            self.missing.append(f"{year}차년도 세액공제액 계산 표")
            return False
        row = [b for b in g.boxes if abs(b.top - total.top) <= NEAR]
        youth = next((b for b in row if re.search(r"청년등상시근로자증가세액공제액$", label(g.text(b)))), None)
        other = next((b for b in row if re.search(r"청년등외상시근로자증가세액공제액$", label(g.text(b)))), None)
        marks = sorted((b for b in g.boxes if b.top >= total.bottom - NEAR and label(g.text(b)) in ("부", "여")
                        and b.right <= (youth.left if youth is not None else total.left) + 2), key=lambda b: b.top)
        end = total.bottom
        for b in marks:
            if b.top > end + NEAR:
                break
            end = max(end, b.bottom)
        if end == total.bottom:
            end = total.bottom + 60
        got = {}
        for code, h in zip(codes, (youth, other, total)):
            if h is None:
                continue
            vals = [b for b in g.boxes if h.left - 1 <= b.xc <= h.right + 1 and total.bottom - NEAR <= b.top < end - 1
                    and amount(g.text(b)) is not None]
            if len(vals) > 1:
                self.why.append(f"{self.title} {year}차년도 세액공제액 계산 표 {code} 란에 값이 두 줄입니다({g.page_no}쪽). 더해서 읽었습니다")
            if vals:
                got[code] = self.cells[code] = sum(amount(g.text(b)) for b in vals)
        y, o, t = (got.get(c) for c in codes)
        if t is not None and (y is not None or o is not None) and (y or 0) + (o or 0) != t:
            self.why.append(f"{self.title} {year}차년도 세액공제액 {t:,} 이 청년등 {y or 0:,} + 청년등 외 {o or 0:,} 과 다릅니다")
        if t is None and (y or o):
            self.why.append(f"{self.title} {year}차년도 세액공제액 란이 비어 있습니다(청년등 {y or 0:,} · 청년등 외 {o or 0:,})")
        return True

    def total(self) -> bool:
        """「세액공제액」 란(1차 + 2차 + 3차). 이름 칸과 같은 줄 오른쪽 칸."""
        found = self.find(r"세액공제액.*1차년도세액공제액.*2차년도세액공제액")
        if not found:
            self.missing.append("세액공제액 란")
            return False
        g, name = found[0]
        box = next((b for b in g.boxes if abs(b.top - name.top) <= NEAR and b.left >= name.right - NEAR), None)
        self.put("세액공제액", g, box, "won")
        return True

    def period(self, fallback: str) -> tuple[str, str, str]:
        """과세연도 칸 → (fy, fy_start, fy_end). 못 읽으면 신고서의 사업연도(fallback)."""
        for g, b in self.find(r"^과세연도$"):
            box = next((x for x in g.boxes if abs(x.top - b.top) <= NEAR and x.left >= b.right - NEAR), None)
            m = PERIOD.search(norm(g.text(box))) if box is not None else None
            if m:
                a = [int(x) for x in m.groups()]
                return str(a[3]), f"{a[0]}-{a[1]:02d}-{a[2]:02d}", f"{a[3]}-{a[4]:02d}-{a[5]:02d}"
        if fallback:
            self.why.append(f"{self.title} 과세연도 란을 읽지 못해 신고서 사업연도 {fallback} 로 두었습니다")
        return fallback, "", ""

    def edition(self) -> str:
        for p in self.pages:
            m = REVISED.search(norm(p.get("text") or ""))
            if m:
                return f"{m.group(1)}.{int(m.group(2)):02d}.{int(m.group(3)):02d}"
        return ""

    def printed(self) -> int:
        """쪽에 찍힌 금액 칸(천 단위 쉼표) 수. 값을 하나도 못 읽었을 때 빈 서식인지 가린다."""
        return sum(1 for g in self.grids for t in g.boxes.values() if "," in t and amount(t) is not None)


def _d(v) -> Decimal:
    return Decimal(str(v))


def _year(cells: dict, no: int, fy: str, amount_key: str, found: bool, youth, other, headcount) -> dict:
    y = int(fy) - (no - 1) if str(fy).isdigit() else None
    return {"차수": no, "year": y, "amount": (cells.get(amount_key) or 0) if found else None,
            "청년등": youth or 0, "청년등외": other or 0, "first_headcount": headcount}


def _sum(cells: dict, code: str, name: str) -> int:
    return sum(v for k, v in cells.items() if re.fullmatch(rf"{code}_.*_{name}", k))


def _finish(f: Form, out: dict, total_parts: list) -> dict | None:
    if not f.cells:
        f.why.clear()                           # 빈 서식은 과세연도 란도 비어 있다. 그 문제 글은 남기지 않는다
        if f.printed():
            f.why.append(f"{f.title} 쪽에 금액이 있는데 란을 하나도 읽지 못했습니다")
        return None
    if f.missing:
        f.why.append(f"{f.title} 에서 찾지 못한 곳: " + " · ".join(f.missing))
    total = f.cells.get("세액공제액")
    parts = sum(v or 0 for v in total_parts)
    if total is not None and total != parts:
        f.why.append(f"{f.title} 세액공제액 {total:,} 이 차수별 금액의 합 {parts:,} 과 다릅니다")
    if total is None and parts:
        f.why.append(f"{f.title} 세액공제액 란이 비어 있습니다(차수별 금액의 합 {parts:,})")
    ed = f.edition()
    if ed not in EDITIONS[f.key]:
        f.why.append(f"{f.title} 서식 판(개정 {ed or '모름'})은 란 번호를 확인한 판이 아닙니다. 머리글로 읽었고 란 번호는 "
                     f"{' · '.join(sorted(EDITIONS[f.key]))} 판대로 붙였습니다")
    years = [r["year"] for r in out["by_year"] if r["amount"] and r["year"]]
    return {"form": f"조특{f.key}", "name": NAMES[f.key], "판": ed, "page": f.pages[0].get("page_no"), **out,
            "first_year": min(years) if years else None, "total": total, "cells": dict(f.cells)}


def read_10_8(pages: list[dict], fy: str = "") -> tuple[dict | None, list[str]]:
    """10호의8 쪽들 → (employment["10의8"], 문제 글)."""
    f = Form("10의8", pages)
    if not f.grids:
        return None, [f"{f.title} 쪽의 선 · 글자 자료가 없어 읽지 못했습니다"]
    f.triple(H_ALL, ("6", "7", "8"), "상시근로자")
    f.triple(H_YOUTH, ("9", "10", "11"), "청년등 상시근로자")
    f.triple(H_OTHER, ("12", "13", "14"), "청년등 외 상시근로자")
    t1 = f.first_table("15")
    f.triple(H_Y2, ("16", "17", "18"), "2차년도 상시근로자")
    t2 = f.later_table(2, ("19", "20", "21"))
    f.triple(H_Y3, ("22", "23", "24"), "3차년도 상시근로자")
    t3 = f.later_table(3, ("25", "26", "27"))
    f.total()
    c = f.cells
    year, start, end = f.period(fy)
    cur = c.get("6", c.get("16", c.get("22")))
    out = {"fy": int(year) if str(year).isdigit() else None, "fy_start": start, "fy_end": end,
           "by_year": [_year(c, 1, year, "15_계", t1, _sum(c, "15", "청년등"), _sum(c, "15", "청년등외"), cur),
                       _year(c, 2, year, "21", t2, c.get("19"), c.get("20"), c.get("17", c.get("7"))),
                       _year(c, 3, year, "27", t3, c.get("25"), c.get("26"), c.get("23"))],
           "headcount": {"prior": {"상시": c.get("7", c.get("17")), "청년등": c.get("10"), "청년등외": c.get("13")},
                         "current": {"상시": cur, "청년등": c.get("9"), "청년등외": c.get("12")}}}
    return _finish(f, out, [c.get("15_계"), c.get("21"), c.get("27")]), f.why


def _status(f: Form) -> None:
    """10호의9 상시근로자 현황 표(⑥ ~ ⑩, 직전전 · 직전 · 해당 과세연도 열)."""
    hit = f.find(r"^직전전과세연도$")
    if not hit:
        f.missing.append("상시근로자 현황 표")
        return
    g, h = hit[0]
    cols = {"직전전": h}
    for name in ("직전", "해당"):
        cols[name] = next((b for b in g.boxes if abs(b.top - h.top) <= NEAR and label(g.text(b)) == f"{name}과세연도"), None)
    rows = (("6", N + r"상시근로자수(\(\+\))?$"), ("7", N + r"청년등상시근로자수$"), ("8", N + r"청년등상시근로자를제외한상시근로자수$"),
            ("9", N + r"정규직전환근로자수$"), ("10", N + r"육아휴직복귀자수$"))
    for code, rx in rows:
        row = next((b for _, b in f.find(rx, g) if b.top >= h.bottom - NEAR and b.right <= h.left + 2), None)
        if row is None:
            continue
        for name, col in cols.items():
            if col is not None and (code in ("6", "7", "8") or name == "해당"):
                f.put(f"{code}_{name}", g, f.beside(g, row, col), "count")


def _extra(f: Form) -> None:
    """10호의9 추가공제 세액공제액 계산 표(㊱)."""
    g, amt = f.head(N + r"추가공제세액공제액$")
    if amt is None:
        return                                  # 추가공제 표가 없는 옛 판은 조용히 넘긴다
    _, cnt = f.head(r"^인원수$", g)
    body = [b for b in g.boxes if amt.bottom - NEAR <= b.top]
    for b in sorted((b for b in body if label(g.text(b)) in ("정규직전환자", "육아휴직복귀자", "계") and b.right <= amt.left),
                    key=lambda b: b.top):
        corp = next((CORPS[label(g.text(c))] for c in body if label(g.text(c)) in CORPS and c.top - 1 <= b.yc <= c.bottom + 1),
                    None)
        if corp is None:
            continue
        key = f"36_{corp}_{label(g.text(b))}"
        f.put(key, g, f.beside(g, b, amt), "won")
        if cnt is not None:
            f.put(key + "_인원", g, f.beside(g, b, cnt), "count")
    totals = [v for k, v in f.cells.items() if re.fullmatch(r"36_.*_계", k)]
    if totals:
        f.cells["36_계"] = sum(totals)


def read_10_9(pages: list[dict], fy: str = "") -> tuple[dict | None, list[str]]:
    """10호의9 쪽들 → (employment["10의9"], 문제 글)."""
    f = Form("10의9", pages)
    if not f.grids:
        return None, [f"{f.title} 쪽의 선 · 글자 자료가 없어 읽지 못했습니다"]
    _status(f)
    f.triple(H_ALL, ("11", "12", "13"), "상시근로자")
    f.triple(H_YOUTH, ("14", "15", "16"), "청년등 상시근로자")
    f.triple(H_OTHER, ("17", "18", "19"), "청년등 외 상시근로자")
    t1 = f.first_table("20")
    f.triple(H_Y2, ("21", "22", "23"), "2차년도 상시근로자")
    t2 = f.later_table(2, ("24", "25", "26"))
    f.triple(H_Y3, ("27", "28", "29"), "3차년도 상시근로자")
    t3 = f.later_table(3, ("30", "31", "32"))
    if len(f.find(H_ALL)) > 1:
        f.triple(H_ALL, ("33", "34", "35"), "추가공제 상시근로자", nth=1)
    _extra(f)
    f.total()
    c = f.cells
    year, start, end = f.period(fy)
    cur = c.get("6_해당", c.get("11", c.get("21", c.get("27"))))
    prior = c.get("6_직전", c.get("12", c.get("22")))
    out = {"fy": int(year) if str(year).isdigit() else None, "fy_start": start, "fy_end": end,
           "by_year": [_year(c, 1, year, "20_계", t1, _sum(c, "20", "청년등"), _sum(c, "20", "청년등외"), cur),
                       _year(c, 2, year, "26", t2, c.get("24"), c.get("25"), prior),
                       _year(c, 3, year, "32", t3, c.get("30"), c.get("31"), c.get("6_직전전", c.get("28")))],
           "extra": c.get("36_계") or 0,
           "headcount": {"prior2": {"상시": c.get("6_직전전", c.get("28")), "청년등": c.get("7_직전전"), "청년등외": c.get("8_직전전")},
                         "prior": {"상시": prior, "청년등": c.get("7_직전", c.get("15")), "청년등외": c.get("8_직전", c.get("18"))},
                         "current": {"상시": cur, "청년등": c.get("7_해당", c.get("14")),
                                     "청년등외": c.get("8_해당", c.get("17"))}}}
    return _finish(f, out, [c.get("20_계"), c.get("26"), c.get("32"), c.get("36_계")]), f.why


def read_employment(pages8: list[dict], pages9: list[dict], fy: str = "") -> tuple[dict, list[str]]:
    """10호의8 · 10호의9 쪽들 → (employment, 문제 글). 그 서식 쪽이 없으면 키를 두지 않는다."""
    out, why = {}, []
    for key, pages, reader in (("10의8", pages8, read_10_8), ("10의9", pages9, read_10_9)):
        if pages:
            out[key], w = reader(pages, fy)
            why += w
    return out, why
