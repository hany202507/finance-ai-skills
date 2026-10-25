"""전기 신고서의 일반연구 및 인력개발비 명세서 읽기. 조세특례제한법 시행규칙 별지 제3호서식(1) 앞쪽이 전기.json `rnd` 가 된다
(CONTRACT.md 13절 r8).

당기 공제감면 조서(wp/papers/credits.py)가 증가분 방식의 직전 과세연도 발생액을 사람 손 없이 쓰려고 읽는다. 전기 서식의 ⑫ 해당
과세연도 발생액이 당기 「직전 1년」 이고, 전기 ⑭ · ⑮ · ⑯(직전 1 ~ 3년)이 당기 「직전 2년」 ~ 「직전 4년」 이다(조특법 제10조 제1항
제3호, 시행령 제9조 제9항).

  rnd  신고서에 그 서식이 없으면 키가 없고, 서식은 있는데 값이 하나도 없으면 null.
    form · name · 판(쪽 머리의 개정일 「2025.03.21」) · page(첫 쪽) · fy(과세연도 끝 날의 연도) · fy_start · fy_end
    발생액      ⑫ 해당 과세연도 발생액(비어 있으면 발생명세 ⑪ 총계의 합계 줄)
    명세        발생명세 합계 줄 {인건비, 재료비, 위탁, 기타, 인력개발비, 합계}(찍힌 것만). 줄 이름은 머리글로 가린다
    직전        [{차수 1 ~ 4, year(그 과세연도 끝 날의 연도), period(머리글에 찍힌 기간), amount(빈 란 0)}]
    직전합계 ⑬ · 연평균 ⑱ · 증가발생액 ㉑
    당기분      해당 연도 총발생금액 공제의 공제세액(중소기업 ㉔ · 유예기간 종료 이후 ㉙ · 중견기업 ㉜ · 일반기업 ㊲ 중 찍힌 것)
    당기분구분  위 금액이 찍힌 줄(중소기업 · 유예 · 중견기업 · 일반기업)
    증가분      증가발생금액 공제의 공제세액 ㊵
    공제세액    ㊶ 해당 연도에 공제받을 세액
    cells       서식 란 번호를 키로 둔 값(읽은 것만). 금액은 정수, 공제율은 소수(25% → 0.25)

란 번호(2025. 11. 28. 개정 서식. 인쇄된 신고서와 법제처 서식 PDF 별표 000300 으로 확인)
  발생명세 합계 줄 ⑥ 인건비 및 사회보험료 · ⑦ 재료비 등 · ⑧ 위탁 및 공동 연구개발비 · ⑨ 기타 연구개발비 · ⑩ 인력개발비 · ⑪ 총계,
  ⑫ 해당 과세연도 발생액, ⑬ 직전 4년 발생액 계, ⑭ ~ ⑰ 직전 1 ~ 4년, ⑱ 직전 4년간 연평균 발생액, ⑲ 직전 3년간 · ⑳ 직전 2년간
  연평균 발생액, ㉑ 증가발생액, ㉒ ㉓ ㉔ 중소기업(대상금액 · 공제율 · 공제세액), ㉕ ㉘ ㉙ 유예기간 종료 이후 5년 내 기업,
  ㉚ ㉛ ㉜ 중견기업, ㉝ ㉞ ㉟ ㊱ ㊲ 일반기업(대상금액 · 기본율 · 추가 · 계 · 공제세액), ㊳ ㊴ ㊵ 증가발생금액 공제, ㊶.
  2025. 3. 21. 개정 서식은 ⑧ 이 자체 연구개발비 기타, ⑨ 가 위탁 및 공동 연구개발비다. 발생명세 란 번호는 금액 머리글에 찍힌
  동그라미 번호(⑥ ~ ⑩)를 그대로 읽으므로 cells 의 `8` · `9` 는 그 판의 란이고, 판과 상관없는 이름은 `명세` 에 둔다.

읽는 법은 employ.py 와 같다. 칸 테두리 선으로 만든 격자(grid.Grid)에서 머리글 칸을 글로 찾고(⑯ 보다 큰 동그라미 번호는 글자로
읽히지 않는다) 바로 아래 칸이나 같은 줄 오른쪽 칸의 값을 읽는다. 신청인 란(상호 · 성명 · 생년월일 · 주소)과 뒤쪽은 읽지 않는다.

검산(안 맞으면 문제 글, 1원 차이는 봐준다): ⑪ = ⑥ + ⑦ + ⑧ + ⑨ + ⑩, ⑫ = ⑪, ⑬ = ⑭ + ⑮ + ⑯ + ⑰, ㉑ = ⑫ - ⑭,
공제세액 = 대상금액 × 공제율(당기분 · 증가분), ㊳ = ㉑, ㊶ 이 당기분 · 증가분 공제세액 가운데 하나.
8호 부표3 당기분과 맞추는 일은 read.build 가 한다.
"""
from __future__ import annotations

import re
import unicodedata
from fractions import Fraction

from ctax.prior.employ import NEAR, REVISED, label
from ctax.prior.grid import Box, Grid, amount, norm

NAME = "일반연구 및 인력개발비 명세서"
TITLE = "조특 3호(1)"
EDITIONS = {"2025.03.21", "2025.11.28"}
PERIOD = re.compile(r"(\d{4})년(\d{1,2})월(\d{1,2})일\D{0,4}(\d{4})년(\d{1,2})월(\d{1,2})일")
SPAN = re.compile(r"(\d{4})\.(\d{1,2})\.(\d{1,2})\D{0,3}(\d{4})\.(\d{1,2})\.(\d{1,2})")
PERCENT = re.compile(r"^(\d+(?:\.\d+)?)%$")
# 발생명세 묶음 머리글 → 판과 상관없는 이름
DETAIL = (("인건비및사회보험료", "인건비"), ("재료비등", "재료비"), ("위탁및공동연구개발비", "위탁"), ("기타연구개발비", "기타"),
          ("기타", "기타"), ("인력개발비", "인력개발비"))
# 공제세액 표의 줄 머리글 → (이름, 대상금액 · 공제율 · 공제세액 란 번호)
GROUPS = (("중소기업", "중소기업", ("22", "23", "24")), ("중소기업유예기간종료이후5년내기업", "유예", ("25", "28", "29")),
          ("중견기업", "중견기업", ("30", "31", "32")), ("일반기업", "일반기업", ("33", "36", "37")))


def circled(text: str) -> int | None:
    """글에 든 첫 동그라미 번호(① ~ ⑳)의 숫자. 없으면 None."""
    for ch in norm(text):
        if unicodedata.category(ch) == "No":
            try:
                return int(unicodedata.numeric(ch))
            except (TypeError, ValueError):
                return None
    return None


def percent(text: str):
    """「25%」 → 0.25. 아니면 None."""
    m = PERCENT.match(norm(text))
    return float(Fraction(m.group(1)) / 100) if m else None


class Sheet:
    """앞쪽 한 쪽을 읽는 동안의 상태. cells 는 란 값, why 는 문제 글."""

    def __init__(self, g: Grid):
        self.g = g
        self.cells: dict = {}
        self.why: list[str] = []
        self.missing: list[str] = []

    def find(self, pattern: str) -> list[Box]:
        rx = re.compile(pattern)
        return sorted((b for b, t in self.g.boxes.items() if rx.search(label(t))), key=lambda b: (b.top, b.left))

    def below(self, h: Box) -> Box | None:
        """머리글 칸 바로 아래, 같은 너비의 값 칸."""
        return next((b for b in self.g.boxes if abs(b.left - h.left) <= NEAR and abs(b.right - h.right) <= NEAR
                     and abs(b.top - h.bottom) <= NEAR), None)

    def right(self, h: Box) -> Box | None:
        """머리글 칸과 같은 줄, 바로 오른쪽 칸."""
        return next((b for b in self.g.boxes if abs(b.top - h.top) <= NEAR and abs(b.left - h.right) <= NEAR), None)

    def put(self, code: str, box: Box | None, kind: str = "won"):
        """칸 값을 cells[code] 에. 빈칸이면 넣지 않고 None, 글을 못 읽으면 문제 글."""
        if box is None:
            return None
        raw = self.g.text(box)
        v = amount(raw) if kind == "won" else percent(raw)
        if v is None:
            if norm(raw) not in ("", "-"):
                self.why.append(f"{TITLE} {code} 란 글 「{raw[:20]}」 을 숫자로 읽지 못했습니다({self.g.page_no}쪽)")
            return None
        self.cells[code] = v
        return v

    # 발생명세
    def detail(self) -> dict:
        """발생명세 합계 줄. 금액 머리글마다 위 묶음 머리글로 이름을, 머리글의 동그라미 번호로 란 번호를 정한다."""
        out = {}
        totals = self.find(r"^합계$")
        heads = [b for b in self.find(r"^금액$") if circled(self.g.text(b))]
        if not heads:
            self.missing.append("발생명세 금액 머리글")
        for h in heads:
            up = next((b for b in self.g.boxes if abs(b.bottom - h.top) <= NEAR and b.left - NEAR <= h.left
                       and h.right <= b.right + NEAR), None)
            name = next((n for text, n in DETAIL if up is not None and label(self.g.text(up)) == text), None)
            row = next((b for b in totals if b.top >= h.bottom - NEAR), None)
            if row is None:
                continue
            box = next((b for b in self.g.boxes if abs(b.top - row.top) <= NEAR and h.left - 1 <= b.xc <= h.right + 1
                        and b != row), None)
            v = self.put(str(circled(self.g.text(h))), box)
            if v is not None and name:
                out[name] = out.get(name, 0) + v
        total = next(iter(self.find(r"^총계")), None)
        if total is None:
            self.missing.append("발생명세 ⑪ 총계")
        else:
            row = next((b for b in totals if b.top >= total.bottom - NEAR), None)
            box = next((b for b in self.g.boxes if row is not None and abs(b.top - row.top) <= NEAR
                        and total.left - 1 <= b.xc <= total.right + 1 and b != row), None)
            v = self.put("11", box)
            if v is not None:
                out["합계"] = v
        return out

    # 증가발생액의 계산
    def growth(self, fy: int | None) -> list[dict]:
        for code, rx, where in (("12", r"^해당과세연도발생액$", "below"), ("13", r"^직전4년발생액계", "below"),
                                ("18", r"^직전4년간연평균발생액", "right"), ("19", r"^직전3년간연평균발생액", "right"),
                                ("20", r"^직전2년간연평균발생액", "right"), ("21", r"^증가발생액\(", "right")):
            h = next(iter(self.find(rx)), None)
            if h is None:
                self.missing.append(f"{code} 란 머리글")
                continue
            self.put(code, self.below(h) if where == "below" else self.right(h))
        prev = []
        for n in (1, 2, 3, 4):
            h = next(iter(self.find(rf"\(직전{n}년\)$")), None)
            if h is None:
                self.missing.append(f"직전 {n}년 머리글")
                prev.append({"차수": n, "year": fy - n if fy else None, "period": "", "amount": None})
                continue
            v = self.put(str(13 + n), self.below(h))
            m = SPAN.search(norm(self.g.text(h)))
            period = f"{m.group(1)}.{int(m.group(2)):02d}.{int(m.group(3)):02d}~{m.group(4)}.{int(m.group(5)):02d}.{int(m.group(6)):02d}" \
                if m else ""
            prev.append({"차수": n, "year": int(m.group(4)) if m else (fy - n if fy else None), "period": period,
                         "amount": v or 0})
        return prev

    # 공제세액
    def credit(self) -> tuple[int | None, str]:
        """해당 연도 총발생금액 공제 줄(기업 구분별)과 증가발생금액 공제 줄. (당기분 공제세액, 찍힌 구분)을 돌려준다."""
        current, which = None, ""
        for text, name, (c_base, c_rate, c_tax) in GROUPS:
            grp = next((b for b in self.find(rf"^{text}$")), None)
            if grp is None:
                continue
            inside = [b for b in self.g.boxes if grp.top - NEAR <= b.top < grp.bottom - NEAR and b.left >= grp.right - NEAR]
            head = lambda rx: next((b for b in sorted(inside, key=lambda b: (b.top, b.left))   # noqa: E731
                                    if re.search(rx, label(self.g.text(b)))), None)
            base, tax = head(r"^대상금액"), head(r"^공제세액")
            self.put(c_base, self.below(base) if base else None)
            if name == "일반기업":
                for code, rx in (("34", r"^기본율$"), ("35", r"^추가$"), ("36", r"^계\(")):
                    h = head(rx)
                    self.put(code, self.below(h) if h else None, "rate")
            else:
                h = head(r"^공제율$")
                self.put(c_rate, self.below(h) if h else None, "rate")
            # 공제세액 값 칸은 머리글 아래 줄(일반기업은 공제율 머리글이 두 줄이라 그 아래)
            got = None
            if tax is not None:
                under = sorted((b for b in inside if abs(b.left - tax.left) <= NEAR and b.top >= tax.bottom - NEAR),
                               key=lambda b: b.top)
                got = self.put(c_tax, under[0] if under else None)
            if got:
                if current is not None:
                    self.why.append(f"{TITLE} 해당 연도 총발생금액 공제의 공제세액이 두 줄({which} · {name})에 찍혀 있습니다")
                else:
                    current, which = got, name
        grp = next(iter(self.find(r"^증가발생금액공제")), None)
        if grp is None:
            self.missing.append("증가발생금액 공제 줄")
        else:
            inside = [b for b in self.g.boxes if grp.top - NEAR <= b.top < grp.bottom - NEAR and b.left >= grp.right - NEAR]
            for code, rx, kind in (("38", r"^대상금액", "won"), ("39", r"^공제율$", "rate"), ("40", r"^공제세액", "won")):
                h = next((b for b in sorted(inside, key=lambda b: (b.top, b.left)) if re.search(rx, label(self.g.text(b)))), None)
                self.put(code, self.below(h) if h else None, kind)
        h = next(iter(self.find(r"^해당연도에공제받을세액$")), None)
        if h is None:
            self.missing.append("㊶ 해당 연도에 공제받을 세액")
        else:
            box = next((b for b in sorted(self.g.boxes, key=lambda b: -b.left) if abs(b.top - h.top) <= NEAR
                        and b.left >= h.right - NEAR and amount(self.g.text(b)) is not None), None)
            self.put("41", box)
        return current, which

    def period(self, fallback: str) -> tuple[str, str, str]:
        """과세연도 칸 → (fy, fy_start, fy_end). 못 읽으면 신고서의 사업연도(fallback)."""
        for b in self.find(r"^과세연도$"):
            box = self.right(b)
            m = PERIOD.search(norm(self.g.text(box))) if box is not None else None
            if m:
                a = [int(x) for x in m.groups()]
                return str(a[3]), f"{a[0]}-{a[1]:02d}-{a[2]:02d}", f"{a[3]}-{a[4]:02d}-{a[5]:02d}"
        return fallback, "", ""

    def printed(self) -> int:
        """표 안에 찍힌 금액 칸(천 단위 쉼표) 수. 값을 하나도 못 읽었을 때 빈 서식인지 가린다."""
        return sum(1 for t in self.g.boxes.values() if "," in t and amount(t) is not None)


def _near(a, b) -> bool:
    return a is not None and b is not None and abs(int(a) - int(b)) <= 1


def _checks(c: dict, why: list[str]) -> None:
    """서식 안 검산. 값이 있는 란끼리만 본다."""
    parts = [c.get(k) for k in ("6", "7", "8", "9", "10")]
    if c.get("11") is not None and any(v is not None for v in parts) and sum(v or 0 for v in parts) != c["11"]:
        why.append(f"{TITLE} ⑪ 총계 {c['11']:,} 이 ⑥ ~ ⑩ 합계 {sum(v or 0 for v in parts):,} 과 다릅니다")
    if c.get("11") is not None and c.get("12") is not None and c["11"] != c["12"]:
        why.append(f"{TITLE} ⑫ 해당 과세연도 발생액 {c['12']:,} 이 ⑪ 총계 {c['11']:,} 과 다릅니다")
    prev = [c.get(k) for k in ("14", "15", "16", "17")]
    if c.get("13") is not None and sum(v or 0 for v in prev) != c["13"]:
        why.append(f"{TITLE} ⑬ 직전 4년 발생액 계 {c['13']:,} 이 ⑭ ~ ⑰ 합계 {sum(v or 0 for v in prev):,} 과 다릅니다")
    if c.get("21") is not None and c.get("12") is not None and c["21"] != max(0, c["12"] - (c.get("14") or 0)):
        why.append(f"{TITLE} ㉑ 증가발생액 {c['21']:,} 이 ⑫ - ⑭ {max(0, c['12'] - (c.get('14') or 0)):,} 과 다릅니다")
    for name, base, rate, tax in (("중소기업", "22", "23", "24"), ("유예기간 종료 이후 5년 내 기업", "25", "28", "29"),
                                  ("중견기업", "30", "31", "32"), ("일반기업", "33", "36", "37"),
                                  ("증가발생금액 공제", "38", "39", "40")):
        if c.get(tax) is None or c.get(base) is None or c.get(rate) is None:
            continue
        want = Fraction(c[base]) * Fraction(str(c[rate]))
        if not _near(c[tax], int(want)) and not _near(c[tax], round(want)):
            why.append(f"{TITLE} {name} 공제세액 {c[tax]:,} 이 대상금액 {c[base]:,} × 공제율 {c[rate] * 100:g}% 와 다릅니다")
    if c.get("38") is not None and c.get("21") is not None and c["38"] != c["21"]:
        why.append(f"{TITLE} ㊳ 대상금액 {c['38']:,} 이 ㉑ 증가발생액 {c['21']:,} 과 다릅니다")
    picks = [c[k] for k in ("24", "29", "32", "37", "40") if c.get(k)]
    if c.get("41") is not None and picks and c["41"] not in picks:
        why.append(f"{TITLE} ㊶ 해당 연도에 공제받을 세액 {c['41']:,} 이 당기분 · 증가분 공제세액"
                   f"({' · '.join(f'{v:,}' for v in picks)}) 가운데 어느 것과도 다릅니다")
    if c.get("41") is None and picks:
        why.append(f"{TITLE} ㊶ 해당 연도에 공제받을 세액 란이 비어 있습니다(공제세액 {' · '.join(f'{v:,}' for v in picks)})")


def read_rnd(pages: list[dict], fy: str = "") -> tuple[dict | None, list[str]]:
    """조특 3호(1) 쪽들 → (rnd, 문제 글). 앞쪽(발생명세 머리글이 있는 쪽)만 읽는다."""
    grids = [Grid.from_page(p) for p in pages if p.get("grid")]
    if not grids:
        return None, [f"{TITLE} 쪽의 선 · 글자 자료가 없어 읽지 못했습니다"]
    front = next((g for g in grids if any(label(t) == "해당과세연도발생액" for t in g.boxes.values())), None)
    if front is None:
        return None, [f"{TITLE} 앞쪽(증가발생액의 계산 표)을 찾지 못했습니다"]
    s = Sheet(front)
    year, start, end = s.period(fy)
    fy_no = int(year) if str(year).isdigit() else None
    detail = s.detail()
    prev = s.growth(fy_no)
    current, which = s.credit()
    c = s.cells
    if not c:
        return None, ([f"{TITLE} 쪽에 금액이 있는데 란을 하나도 읽지 못했습니다"] if s.printed() else [])
    if not start and fy:
        s.why.append(f"{TITLE} 과세연도 란을 읽지 못해 신고서 사업연도 {fy} 로 두었습니다")
    if s.missing:
        s.why.append(f"{TITLE} 에서 찾지 못한 곳: " + " · ".join(s.missing))
    _checks(c, s.why)
    ed = ""
    for p in pages:
        m = REVISED.search(norm(p.get("text") or ""))
        if m:
            ed = f"{m.group(1)}.{int(m.group(2)):02d}.{int(m.group(3)):02d}"
            break
    if ed not in EDITIONS:
        s.why.append(f"{TITLE} 서식 판(개정 {ed or '모름'})은 란 번호를 확인한 판이 아닙니다. 머리글로 읽었고 란 번호는 "
                     f"{' · '.join(sorted(EDITIONS))} 판대로 붙였습니다")
    spent = c.get("12", c.get("11"))
    out = {"form": "조특3_1", "name": NAME, "판": ed, "page": front.page_no, "fy": fy_no, "fy_start": start, "fy_end": end,
           "발생액": spent, "명세": detail, "직전": prev, "직전합계": c.get("13"), "연평균": c.get("18"),
           "증가발생액": c.get("21"), "당기분": current, "당기분구분": which, "증가분": c.get("40"), "공제세액": c.get("41"),
           "cells": dict(c)}
    return out, s.why
