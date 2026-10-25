"""위하고 재무상태표 · 손익계산서 조회표(5열: 과목 · 당기 소계 · 당기 합계 · 전기 소계 · 전기 합계) 읽기.

함정(입력 분석 1.3 · 3.1):
- 재무상태표 금액은 쉼표 문자열, 음수는 `△`. 손익계산서는 정수.
- 손실 머리 줄(영업손실 · 법인세차감전손실 · 당기순손실)은 손실을 양수로 적는다 → 이익 양수로 뒤집는다.
- 재무상태표 결손금 · 미처리결손금 · 이월결손금도 결손을 양수로 적는다 → 자본 자연 부호(음수)로 뒤집는다.
- 총액 · 차감 짝: 총액은 소계 열(B), 차감 줄(감가상각누계액 등)은 B 가 차감액, C 가 순액.
  차감액이 0 이면 B 가 비고 C 에 순액만 남는다 → 차감액 0 으로 읽는다.
- 매출원가 아래 기초 · 당기 매입 · 기말 재고, 당기 제품 제조원가는 계산 줄이다(계정 아님, kind memo).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .xlsxread import PAREN, ROMAN, compact, norm, num, strip_no

CONTRA_NAMES = ("감가상각누계액", "대손충당금", "국고보조금", "정부보조금", "현재가치할인차금", "손상차손누계액",
                "일반참여분", "사채할인발행차금", "전환권조정", "신주인수권조정", "공사부담금")
# 부채 구역에서 퇴직급여충당부채를 깎는 자산 줄
LIAB_CONTRA_ASSETS = ("퇴직연금운용자산", "퇴직보험예치금", "국민연금전환금")
RE_NAMES = re.compile(r"(미처분이익잉여금|미처리결손금|이월이익잉여금|이월결손금)$")
LOSS_HEAD = re.compile(r"(영업손실|매출총손실|차감전(순)?손실|당기순손실)$")
COST_CALC = re.compile(r"^(기초|기말).*재고|^당기.*(매입|제조원가|공사원가|원가)|^타계정|매입(할인|환출|에누리)")

IS_SECTIONS = {
    "매출액": ("수익", 401, 450), "매출": ("수익", 401, 450), "영업수익": ("수익", 401, 450),
    "매출원가": ("비용", 451, 500), "영업비용": ("비용", 451, 900),
    "판매비와관리비": ("비용", 801, 900), "판매비및일반관리비": ("비용", 801, 900),
    "판매관리비": ("비용", 801, 900), "판매비와일반관리비": ("비용", 801, 900),     # 더존 ERP 표기
    "영업외수익": ("수익", 901, 997), "영업외비용": ("비용", 901, 997),
    "법인세등": ("비용", 998, 999), "법인세비용": ("비용", 998, 999),
}

# 손익계산서 구역 이름 변형 → 장부.json 에 쓰는 이름(하류는 「판매비와관리비」 로 찾는다)
SECTION_ALIAS = {"판매관리비": "판매비와관리비", "판매비및일반관리비": "판매비와관리비", "판매비와일반관리비": "판매비와관리비"}


@dataclass
class FsLine:
    label: str               # 원문(앞뒤 공백만 지움)
    name: str                # 비교용 이름(공백 · 번호 · 꼬리 지움)
    kind: str                # account · subtotal · header · memo
    cur: int | None          # 자연 부호
    prior: int | None
    section: str = ""        # 재무상태표: 유동자산 등 · 손익계산서: 판매비와관리비 등
    sub: str = ""            # 재무상태표 (1) 당좌자산 같은 아래 구역
    side: str = ""           # 재무상태표 A · L · E
    contra: bool = False
    net_cur: int | None = None
    net_prior: int | None = None
    dp_cur: int = 0          # 차변 양수 금액(재무상태표 계정 줄)
    dp_prior: int = 0
    code: str | None = None
    how: str = ""
    extra: dict = field(default_factory=dict)


def _body(rows: list[list]) -> list[list]:
    """머리 두 줄(과목 · 금액)을 건너뛴다."""
    start = 1
    for i, r in enumerate(rows[:4]):
        if any(compact(c) == "금액" for c in (r or [])[1:]):
            start = i + 1
            break
    return rows[start:]


def _cells(r):
    r = list(r) + [None] * 5
    return r[0], num(r[1]), num(r[2]), num(r[3]), num(r[4])


def parse_bs(rows: list[list]) -> list[FsLine]:
    out: list[FsLine] = []
    side, section, sub = "", "", ""
    last_gross = False
    for r in _body(rows):
        label, b, c, d, e = _cells(r)
        if label is None or compact(label) == "":
            continue
        raw = str(label).strip()
        cp = compact(raw)
        nm = strip_no(cp)
        if cp in ("자산", "부채", "자본"):
            side = {"자산": "A", "부채": "L", "자본": "E"}[cp]
            section, sub = "", ""
            out.append(FsLine(raw, nm, "header", None, None, side=side))
            continue
        if cp.startswith("(당기순") or cp.startswith("(전기순") or re.match(r"^(당기|전기):", cp):
            out.append(FsLine(raw, nm, "memo", None, None, side=side))
            continue
        if ROMAN.match(cp) or PAREN.match(cp) or nm.endswith("총계"):
            if ROMAN.match(cp):
                # 결손 회사는 `Ⅴ. 결손금` 으로 나온다. 구역 이름은 이익잉여금으로 맞춘다(줄 이름은 그대로)
                section, sub = ("이익잉여금" if nm == "결손금" else nm), ""
            elif PAREN.match(cp):
                sub = nm
            cur = c if c is not None else b
            pri = e if e is not None else d
            if "결손금" in nm:
                cur = None if cur is None else -cur
                pri = None if pri is None else -pri
            total = cp.endswith("총계")
            out.append(FsLine(raw, nm, "subtotal", cur, pri, section="" if total else section,
                              sub="" if total else sub, side=side))
            last_gross = False
            continue
        # 계정 줄
        # 자본 구역의 국고보조금(자본조정에 둔 회사) 같은 줄은 차감 줄이 아니다
        contra_name = side in ("A", "L") and any(nm.startswith(x) for x in CONTRA_NAMES)
        liab_asset = side == "L" and any(nm.startswith(x) for x in LIAB_CONTRA_ASSETS)
        contra = contra_name or liab_asset or (last_gross and b is not None and c is not None and side == "A")
        if contra:
            cur = b if b is not None else 0
            pri = d if d is not None else 0
        else:
            cur = b if b is not None else c
            pri = d if d is not None else e
        cur = 0 if cur is None else cur
        pri = 0 if pri is None else pri
        ln = FsLine(raw, nm, "account", cur, pri, section=section, sub=sub, side=side, contra=contra)
        if contra:
            ln.net_cur, ln.net_prior = c, e
        # 차변 양수 부호
        if side == "A":
            sign = -1 if contra else 1
        elif side == "L":
            sign = 1 if liab_asset else -1
        else:
            sign = 1 if "결손" in nm else -1
        ln.dp_cur, ln.dp_prior = sign * cur, sign * pri
        if side == "E" and "결손" in nm:      # 자연 부호(자본 = 대변 양수)로
            ln.cur, ln.prior = -cur, -pri
        ln.extra["sign"] = sign
        out.append(ln)
        last_gross = (b is not None and c is None) or (d is not None and e is None)
    return out


def parse_is(rows: list[list]) -> list[FsLine]:
    out: list[FsLine] = []
    section = ""
    for r in _body(rows):
        label, b, c, d, e = _cells(r)
        if label is None or compact(label) == "":
            continue
        raw = str(label).strip()
        cp = compact(raw)
        nm = strip_no(cp)
        if ROMAN.match(cp):
            section = SECTION_ALIAS.get(nm, nm)
            cur = c if c is not None else b
            pri = e if e is not None else d
            if LOSS_HEAD.search(nm):
                cur = None if cur is None else -cur
                pri = None if pri is None else -pri
            out.append(FsLine(raw, nm, "subtotal", cur, pri, section=section))
            continue
        cur = b if b is not None else c
        pri = d if d is not None else e
        if section not in IS_SECTIONS:
            kind = "memo"           # 주당이익 같은 줄
        elif section == "매출원가" and COST_CALC.search(nm):
            kind = "memo"
        else:
            kind = "account"
        ln = FsLine(raw, norm(nm), kind, cur if kind == "memo" else (cur or 0),
                    pri if kind == "memo" else (pri or 0), section=section)
        out.append(ln)
    return out


def find_head(lines: list[FsLine], pattern: str, prior: bool = False) -> int | None:
    """손익계산서 머리 줄 · 재무상태표 합계 줄 값을 이름 정규식으로."""
    rx = re.compile(pattern)
    for ln in lines:
        if ln.kind == "subtotal" and rx.search(ln.name):
            return ln.prior if prior else ln.cur
    return None
