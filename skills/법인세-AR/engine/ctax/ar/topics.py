"""AR 이 보는 계정 묶음(topic). 계정명과 계정 class 로 잇는다.

corptax-impl `definitions/accounts.yaml`(계정 성격 162개)에서 AR 가이드 · 트리거에 필요한 것만 골라 정규식으로 줄였다.
계정명이 먼저다(더존 코드는 회사가 편집한다). 대조 전에 공백과 끝의 구분 꼬리 `(판)` · `(제)` · `(도)` 를 지운다.
목업이라 성격 사전 전체를 옮기지 않았다. 빠진 것은 NOTES.md.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# id: (이름, 정규식, 허용 class). class 는 장부.json accounts.class(자산 · 부채 · 자본 · 수익 · 비용 · 손익대체).
TOPICS: dict[str, tuple[str, str, frozenset]] = {
    "securities": ("유가증권", r"단기매매증권|단기투자증권|단기투자자산|매도가능증권|만기보유증권|지분법적용투자주식|장기투자증권|투자주식|유가증권|출자금",
                   frozenset({"자산"})),
    "securities_pl": ("유가증권 평가 · 처분손익", r"증권평가(이익|손실|손익)|증권처분(이익|손실)|증권손상차손|지분법(이익|손실)|투자자산처분|투자주식처분|투자자산평가|금융상품평가",
                      frozenset({"수익", "비용", "자본"})),
    "dividend": ("배당금수익", r"배당금수익", frozenset({"수익"})),
    "allowance": ("대손충당금", r"대손충당금$", frozenset({"자산"})),
    "bad_debt": ("대손상각비", r"대손상각비|대손충당금환입", frozenset({"비용", "수익"})),
    "receivable": ("매출채권 · 미수금", r"외상매출금|받을어음|공사미수금|^미수금$|분양미수금", frozenset({"자산"})),
    "loan": ("대여금 · 가지급금", r"대여금|주\.?임\.?종|가지급금", frozenset({"자산"})),
    "borrowing": ("차입금", r"차입금|^사채$", frozenset({"부채"})),
    "interest_expense": ("이자비용", r"이자비용", frozenset({"비용"})),
    "accrued_income": ("미수수익", r"미수수익|미수이자", frozenset({"자산"})),
    "interest_income": ("이자수익", r"이자수익", frozenset({"수익"})),
    "prepaid_tax": ("선납세금", r"선납세금|선급법인세", frozenset({"자산"})),
    "prepaid": ("선급비용", r"선급비용", frozenset({"자산"})),
    "inventory": ("재고자산", r"^상품$|^제품$|원재료|재공품|반제품|저장품|미완성공사|미착품", frozenset({"자산"})),
    "tangible": ("유형자산", r"^토지$|^건물$|구축물|기계장치|차량운반구|공구|기구|비품|시설장치|건설중인자산|건설용장비|중장비|선박|기타유형자산|집기",
                 frozenset({"자산"})),
    "accum_dep": ("감가상각누계액", r"감가상각누계액|상각누계액", frozenset({"자산"})),
    "depreciation": ("감가상각비", r"^감가상각비", frozenset({"비용"})),
    "impairment": ("손상차손", r"손상차손", frozenset({"비용"})),
    # 통합투자세액공제 판정 계정(가이드 2-3-6-1). 건설기계(굴삭기 등)는 기계장치와 같은 사업용 유형자산이라 넣는다
    # (조특령 제21조 제2항 · 조특칙 제12조 제1항 · 제3항 제3호). 차량운반구 · 공구 · 비품은 넣지 않는다.
    "capex": ("기계장치 · 시설장치 · 건설중인자산 · 건물 · 건설기계", r"기계장치|시설장치|건설중인자산|^건물$|건설용장비|중장비|건설기계",
              frozenset({"자산"})),
    "grant": ("국고보조금", r"국고보조금|정부보조금", frozenset({"자산", "부채", "자본", "수익"})),
    "intangible": ("무형자산", r"영업권|특허권|상표권|실용신안권|의장권|디자인권|소프트웨어|^개발비|산업재산권|라이선스|라이센스|회원권|기타무형자산|광업권|어업권",
                   frozenset({"자산"})),
    "amortization": ("무형자산상각비", r"무형(고정)?자산상각", frozenset({"비용"})),
    "accrued_expense": ("미지급비용", r"미지급비용", frozenset({"부채"})),
    "provision": ("충당부채(퇴직급여 외)", r"^(?!퇴직).*충당부채", frozenset({"부채"})),
    "retirement_allowance": ("퇴직급여충당부채", r"퇴직급여충당", frozenset({"부채", "자산"})),
    "retirement_plan": ("퇴직연금운용자산", r"퇴직연금운용자산|퇴직보험예치금", frozenset({"자산", "부채"})),
    "retirement_expense": ("퇴직급여", r"^퇴직급여$|퇴직연금|퇴직금", frozenset({"비용"})),
    "convertible": ("전환사채 · 신주인수권부사채", r"전환사채|신주인수권부사채|전환권|신주인수권|상환할증금", frozenset({"부채", "자본"})),
    "capital": ("자본금", r"자본금$", frozenset({"자본"})),
    "share_premium": ("주식발행초과금", r"주식발행초과금", frozenset({"자본"})),
    "equity_other": ("자본 항목", r"자기주식|감자차|주식할인발행차금|기타포괄|자본조정|기타자본잉여금|재평가잉여금|증권평가손익|해외사업환산|신주청약증거금|주식선택권",
                     frozenset({"자본"})),
    "payroll": ("급여 · 상여", r"(?<!퇴직)급여$|임금|상여|잡급|제수당|급료", frozenset({"비용"})),
    "welfare": ("복리후생비", r"복리후생비", frozenset({"비용"})),
    "rnd": ("경상연구개발비 · 개발비", r"연구개발비|연구비|^개발비|경상개발비", frozenset({"비용", "자산"})),
    "taxes": ("세금과공과", r"세금과공과", frozenset({"비용"})),
    "entertainment": ("기업업무추진비", r"접대비|기업업무추진비", frozenset({"비용"})),
    "freight": ("운반비", r"운반비", frozenset({"비용"})),
    "prior_error": ("전기오류수정손익", r"전기오류수정", frozenset({"자본", "수익", "비용"})),
    "donation_gain": ("자산수증이익 · 채무면제이익", r"자산수증이익|채무면제이익", frozenset({"수익"})),
    "inventory_loss": ("재고자산감모손실", r"감모손실", frozenset({"비용"})),
    "vehicles": ("차량운반구", r"차량운반구|^차량$", frozenset({"자산"})),
    "vehicle_cost": ("차량유지비", r"차량유지비|차량리스료|차량렌트|차량임차료|차량비", frozenset({"비용"})),
    "insurance": ("보험료", r"보험료", frozenset({"비용"})),
    "rent_expense": ("지급임차료", r"임차료|리스료|렌탈료", frozenset({"비용"})),
    "donation": ("기부금", r"기부금", frozenset({"비용"})),
    "misc_loss": ("잡손실", r"잡손실", frozenset({"비용"})),
    "misc_expense": ("잡비", r"잡비", frozenset({"비용"})),      # 원가 · 판관비 잡비(과태료를 적은 회사가 있다, 10-19)
    "misc_income": ("잡이익", r"잡이익", frozenset({"수익"})),
    # 10-20 AR 5차: 수선비(자본적 지출 확인) · 지급수수료(소송 · 변호사 비용) · 임원 보수(상여 지급기준) · 계약자산(작업진행률)
    "repair": ("수선비", r"수선비|수선유지비|수리비", frozenset({"비용"})),
    "fees": ("지급수수료", r"지급수수료|수수료비용|소송비|법률비용|자문료", frozenset({"비용"})),
    "officer_pay": ("임원급여", r"임원.*(급여|보수|상여|급료)", frozenset({"비용"})),
    "contract_asset": ("미완성공사 · 계약자산", r"미완성공사|계약자산|미청구공사", frozenset({"자산"})),
    "corp_tax": ("법인세등", r"법인세", frozenset({"비용"})),
    "fx": ("외화환산손익", r"외화환산(이익|손실)", frozenset({"수익", "비용"})),
    "rent_income": ("임대료수입", r"임대료|임대수입|임대매출", frozenset({"수익"})),
    "revenue": ("매출액", r".", frozenset({"수익"})),
}

_TAIL = re.compile(r"\((판|제|도|분|임|공|운|보|건|용|관)\)$")
_COMPILED = {k: re.compile(v[1]) for k, v in TOPICS.items()}


def clean(name: str | None) -> str:
    s = re.sub(r"\s+", "", str(name or ""))
    while True:
        t = _TAIL.sub("", s)
        if t == s:
            return s
        s = t


def code3(code: str) -> int:
    try:
        return int(str(code)[:3])
    except ValueError:
        return -1


def topics_of(acc: dict) -> list[str]:
    """계정 하나가 드는 topic 들. class 는 장부.json 값을 그대로 쓴다. revenue 는 401~450 매출(코드 없는 손익계산서 줄은 매출액 구역)."""
    name = clean(acc.get("name"))
    cls = acc.get("class") or ""
    out = []
    for k, (_label, _rx, classes) in TOPICS.items():
        if cls not in classes:
            continue
        if k == "revenue":
            if 401 <= code3(acc.get("code", "")) <= 450 or (acc.get("fs_only") and acc.get("section") == "매출액"):
                out.append(k)
            continue
        if _COMPILED[k].search(name):
            out.append(k)
    return out


@dataclass
class Topic:
    """topic 하나의 당기 · 전기 합(자연 부호)과 계정 목록."""
    id: str
    label: str
    accounts: list = field(default_factory=list)

    @property
    def current(self) -> int:
        return sum(int(a.get("amount") or 0) for a in self.accounts)

    @property
    def prior(self) -> int:
        return sum(int(a.get("prior_amount") or 0) for a in self.accounts)

    @property
    def known(self) -> list:
        """전기 금액을 아는 계정. 원가(500~700번대) 계정은 prior_known false 다(전기 손익계산서에 원가 명세가 없음)."""
        return [a for a in self.accounts if a.get("prior_known", True) is not False]

    @property
    def unknown_prior(self) -> bool:
        return any(a.get("prior_known") is False and int(a.get("amount") or 0) for a in self.accounts)

    @property
    def change(self) -> int:
        """증감은 전기 금액을 아는 계정만 센다."""
        return sum(int(a.get("amount") or 0) - int(a.get("prior_amount") or 0) for a in self.known)

    @property
    def lines(self) -> int:
        return sum(int(a.get("lines") or 0) for a in self.accounts)

    @property
    def debit(self) -> int:
        return sum(int(a.get("debit") or 0) for a in self.accounts)

    @property
    def credit(self) -> int:
        return sum(int(a.get("credit") or 0) for a in self.accounts)

    @property
    def codes(self) -> list[str]:
        """분개장 계정코드. 코드 없는 손익계산서 줄(전기에만 있는 줄)은 뺀다."""
        return [str(a.get("code")) for a in self.accounts if a.get("code")]

    @property
    def names(self) -> list[str]:
        return [clean(a.get("name")) for a in self.accounts]

    @property
    def has_current(self) -> bool:
        return any(int(a.get("amount") or 0) != 0 for a in self.accounts)

    @property
    def has_prior(self) -> bool:
        return any(int(a.get("prior_amount") or 0) != 0 for a in self.accounts)

    @property
    def touched(self) -> bool:
        """당기 잔액이 0 이어도 기중 거래가 있었는지."""
        return any(int(a.get("lines") or 0) > 0 or int(a.get("debit") or 0) or int(a.get("credit") or 0)
                   for a in self.accounts)

    @property
    def exists(self) -> bool:
        return self.has_current or self.has_prior or self.touched

    def status(self, rate: float = 0.30, amount: int = 10_000_000) -> str:
        """신규 · 소멸 · 크게 변동 · 유지 · 없음. 문턱은 corptax-impl ar.yaml 과 같다(증감률 30% 와 1천만 원 둘 다)."""
        if not self.exists:
            return "없음"
        if not self.known:
            return "전기 모름"
        cur = sum(int(a.get("amount") or 0) for a in self.known)
        pri = sum(int(a.get("prior_amount") or 0) for a in self.known)
        if pri == 0 and cur != 0:
            return "신규"
        if pri != 0 and cur == 0:
            return "소멸"
        if pri != 0 and abs(cur - pri) >= amount and abs(cur - pri) / abs(pri) >= rate:
            return "크게 변동"
        return "유지"


def build_topics(accounts: list[dict]) -> dict[str, Topic]:
    out = {k: Topic(k, v[0]) for k, v in TOPICS.items()}
    for acc in accounts:
        for k in topics_of(acc):
            out[k].accounts.append(acc)
    return out


def won(n) -> str:
    if n is None:
        return ""
    n = int(round(n))
    return f"△{abs(n):,}" if n < 0 else f"{n:,}"


def describe(t: Topic, with_prior: bool = True) -> str:
    """「접대비 56,357,530원(전기 48,000,000원)」 꼴. 계정이 여럿이면 계정명을 「 · 」 로 잇는다."""
    names = " · ".join(dict.fromkeys(t.names)) or t.label
    s = f"{names} {won(t.current)}원"
    if with_prior:
        s += f"(전기 {won(t.prior)}원" + (", 원가 계정은 전기 금액 모름)" if t.unknown_prior else ")")
    return s
