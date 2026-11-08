"""유형자산 계정별 당기 취득 전표 합계(통합투자세액공제 판단 근거, 10-29 대표 · RN 기준).

AR 이슈(investment_credit)와 조서 공제감면(wp/papers/credits.py)이 같은 값을 쓴다. 숫자만 만든다. 공제 대상 자산인지는
회계사가 정한다(조세특례제한법 시행규칙 제12조 제1항, 토지 · 건축물 등은 대상이 아니다).

계정 하나마다 기초(전기 말) · 기말 · 증감과 당기 차변을 넷으로 나눈다.
- 취득: 아래 셋이 아닌 차변 줄
- 투자: 한 번만 센 당기 투자 금액. 건설중인자산은 기말 증가분, 그 밖 계정은 취득 + 건설중인자산에서 넘어온 대체. 통합투자세액공제
  판단 근거로 보는 금액이다(RN 투자자산명세서와 같은 셈)
- 대체: 같은 전표에 다른 유형자산 · 무형자산 계정 대변이 있는 차변 줄(건설중인자산 → 기계장치 같은 계정 사이 옮김)
- 처분: 같은 전표에 감가상각누계액 · 처분손익 계정이 있거나 적요에 처분 · 매각 · 폐기가 있는 차변 줄
- 이월: 적요나 전표 종류에 전기이월 · 기초 표기가 있는 차변 줄
감가상각은 대변(누계액) 쪽이라 차변 합계에 들지 않는다. 같은 전표에 감가상각비가 있는 차변 줄은 처분과 같이 뺀다.
"""
from __future__ import annotations

import re

from .topics import TOPICS, clean

RX_TANGIBLE = re.compile(TOPICS["tangible"][1])
RX_CANDIDATE = re.compile(TOPICS["capex"][1])
RX_NOT_ASSET = re.compile(r"누계|상각|보조금|손상|충당")
RX_INTANGIBLE = re.compile(TOPICS["intangible"][1])
RX_CIP = re.compile(r"건설중인자산")
RX_DISPOSAL_ACCT = re.compile(r"감가상각누계액|상각누계액|처분(이익|손실)|감가상각비|손상차손")
RX_DISPOSAL_MEMO = re.compile(r"처분|매각|폐기|양도|제각")
RX_OPENING = re.compile(r"전기이월|기초잔액|기초금액|이월잔액")


def _int(v) -> int:
    if v in (None, ""):
        return 0
    try:
        return int(round(float(str(v).replace(",", ""))))
    except ValueError:
        return 0


def is_tangible(acct: dict) -> bool:
    """유형자산 본 계정인가(감가상각누계액 · 국고보조금 · 손상차손누계액은 뺀다)."""
    name = clean(acct.get("name"))
    return acct.get("class") == "자산" and bool(RX_TANGIBLE.search(name)) and not RX_NOT_ASSET.search(name)


def is_candidate(acct: dict) -> bool:
    """통합투자세액공제 판단을 띄우는 계정(topics capex: 기계장치 · 시설장치 · 건설중인자산 · 건물 · 건설기계)."""
    return is_tangible(acct) and bool(RX_CANDIDATE.search(clean(acct.get("name"))))


def _get(r, key):
    return r.get(key) if isinstance(r, dict) else getattr(r, key, None)


def rows(accounts: list[dict], lines: list) -> list[dict]:
    """유형자산 계정마다 {code, name, candidate, opening, closing, change, acquired, moved, disposed, carried, debit, credit,
    vouchers(취득 전표 수)}. lines 는 전표.csv 줄(dict 이거나 wp.books.Line, 손익대체 줄은 뺀 것). 계정 순서는 장부 순서."""
    accts = [a for a in accounts if a.get("code") and is_tangible(a)]
    codes = {str(a["code"]) for a in accts}
    names = {str(a.get("code")): clean(a.get("name")) for a in accounts if a.get("code")}
    other_assets = {c for c, n in names.items() if c not in codes and RX_INTANGIBLE.search(n)} | codes
    cip = {c for c in codes if RX_CIP.search(names.get(c, ""))}
    by_voucher: dict[tuple, list] = {}
    for r in lines:
        by_voucher.setdefault((str(_get(r, "date") or ""), str(_get(r, "no") or "")), []).append(r)
    out = []
    for a in accts:
        code = str(a["code"])
        acc = {"acquired": 0, "moved": 0, "from_cip": 0, "disposed": 0, "carried": 0, "debit": 0, "credit": 0}
        seen: set = set()
        for key, vl in by_voucher.items():
            for r in vl:
                if str(_get(r, "account")) != code:
                    continue
                dr, cr = _int(_get(r, "debit")), _int(_get(r, "credit"))
                acc["credit"] += cr
                if dr <= 0:
                    continue
                acc["debit"] += dr
                others = [o for o in vl if o is not r]
                if RX_OPENING.search(str(_get(r, "memo") or "")) or "이월" in str(_get(r, "kind") or ""):
                    acc["carried"] += dr
                elif any(str(_get(o, "account")) in other_assets and str(_get(o, "account")) != code
                         and _int(_get(o, "credit")) > 0 for o in others):
                    acc["moved"] += dr
                    if code not in cip and any(str(_get(o, "account")) in cip and _int(_get(o, "credit")) > 0 for o in others):
                        acc["from_cip"] += dr
                elif RX_DISPOSAL_MEMO.search(str(_get(r, "memo") or "")) or any(
                        RX_DISPOSAL_ACCT.search(names.get(str(_get(o, "account")), "") or str(_get(o, "account_name") or ""))
                        for o in others):
                    acc["disposed"] += dr
                else:
                    acc["acquired"] += dr
                    seen.add(key)
        opening, closing = _int(a.get("prior_amount")), _int(a.get("amount"))
        # 당기 투자 금액(한 번만 센다): 건설중인자산은 기말 증가분(준공해 본계정으로 넘긴 금액은 그 계정에서 센다),
        # 그 밖 계정은 직접 취득 + 건설중인자산에서 넘어온 금액. 계정 사이 단순 대체 · 처분 · 이월은 넣지 않는다
        invest = max(0, closing - opening) if code in cip else acc["acquired"] + acc["from_cip"]
        out.append({"code": code, "name": clean(a.get("name")), "candidate": is_candidate(a), "cip": code in cip,
                    "opening": opening, "closing": closing, "change": closing - opening, "vouchers": len(seen),
                    "invest": invest, **acc})
    return out


def won(n: int) -> str:
    return f"△{abs(n):,}" if n < 0 else f"{n:,}"


def line(r: dict, with_prior: bool = True) -> str:
    """계정 한 줄 글: 「기계장치: 기초 0원 → 기말 50,000,000원(증감 50,000,000원), 당기 취득 전표 2장 50,000,000원」.
    with_prior 가 거짓(첫 사업연도)이면 기초 · 증감을 빼고 기말만 적는다."""
    head = (f"기초 {won(r['opening'])}원 → 기말 {won(r['closing'])}원(증감 {won(r['change'])}원)" if with_prior
            else f"기말 {won(r['closing'])}원")
    s = f"{r['name']}: {head}, 당기 취득 전표 {r['vouchers']}장 {won(r['acquired'])}원"
    if r.get("cip"):
        s += f", 당기 투자 {won(r['invest'])}원(기말 증가분, 본계정으로 넘긴 금액은 그 계정에서 셉니다)"
    elif r.get("from_cip"):
        s += f", 당기 투자 {won(r['invest'])}원(직접 취득 + 건설중인자산에서 넘어온 {won(r['from_cip'])}원)"
    moved = r["moved"] - r.get("from_cip", 0)
    left = [f"{n} {won(v)}원" for n, v in (("계정 대체", moved), ("처분", r["disposed"]), ("이월", r["carried"])) if v]
    return s + (f"(취득에서 뺀 차변: {' · '.join(left)})" if left else "")


def total(rows_: list[dict]) -> int:
    """판단 계정의 당기 투자 금액 합계."""
    return sum(r["invest"] for r in rows_ if r["candidate"])
