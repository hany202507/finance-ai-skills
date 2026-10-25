"""4 업무용승용차: 업무외사용금액(상여), 감가상각비(상당액) 800만원 초과, 이월액 추인, 처분손실 800만원 초과. 29호.

임차(렌트 · 리스) 줄은 차량 단위로 나눈다(`split_lessor`). 적요에 차량번호가 있으면 차량번호가 먼저고, 없으면 한 거래처의
임차료 줄을 금액 흐름(같은 금액이 달마다 한 번씩)으로 나눠 흐름 하나를 차량 하나로 본다. 차량유지비가 아닌 비용 계정의 줄은
적요 · 거래처로 차량 임차료임이 드러날 때만 읽고(`rent_evidence`) 확인 줄을 낸다. 규칙은 wp/NOTES.md 「업무용승용차」 에 있다.

8회차: 세금과공과 · 보험료 같은 다른 비용 계정의 자동차세 · 보험료 · 유류비 등은 적요로 차량 비용임이 드러날 때만 읽는다
(`cost_evidence`). 재고자산 · 건설중인자산 계정에 적힌 임차료는 그 거래처 차량의 금액과 같고 그 차량에 그 달 줄이 없을 때만
읽는다(`asset_rent_lines`). 리스 차량의 감가상각비 상당액은 리스료에서 보험료 · 자동차세 · 수선유지비 노란 칸을 빼고, 수선유지비
7% 는 회계사가 고를 때만 적용한다(법인세법 시행규칙 제27조의2 제6항 제1호).
"""
from __future__ import annotations

import re
from collections import Counter
from fractions import Fraction

from openpyxl.utils import get_column_letter as L

from ... import xlsx as X
from ..books import CAR_PATTERN, NOT_CAR, Books, Line, frac, rate, rd
from ..model import MISSING, Adj, LineRow, Paper, subject_of
from ..sheet import Book, adj_table, calc_row, forms_table, head, ledger, lines_dry, notes, verify, verify_rows
from .loan_interest import norm_related

NAME = "업무용승용차"
FORMS = ["29"]
LEDGER_CHECK = False   # 차량 관련 줄만 고르므로 계정 합계와 다르다

COST_TYPES = ["임차료", "감가상각비", "유류비", "보험료", "수선비", "자동차세", "기타"]
NOT_ASSIGNED = "차량 미지정"
OTHER_VEHICLE = "승합 · 화물 등"
ASSET_RENT = "자산 계정 임차료"   # 자산 계정에 적힌 임차료 가운데 계산에 넣지 않은 줄(대상 부)
REST = -1               # split_lessor 가 어느 차량 것인지 가리지 못한 줄
REST_NAME = "나머지"

# 차량번호: 가운데 한글은 자동차 등록번호판에 쓰는 글자만 본다(「12월 2025」 같은 날짜를 차량번호로 읽지 않게).
PLATE = re.compile(r"(\d{2,3})\s?([가나다라마거너더러머버서어저고노도로모보소오조구누두루무부수우주아바사자배하허호])\s?(\d{4})")
RENT_MEMO = re.compile(r"리스(?!트)|렌트|렌터카|렌탈|대여료|임차료")
CAR_WORD = re.compile(r"차량|자동차|승용차|렌터카|렌트카")
VAT_WORD = re.compile(r"부가세|부가가치세|VAT|세액", re.I)
# 차량유지비가 아닌 계정에서 차량 임차료를 읽을 때 쓰는 말. 좁게 잡는다.
LESSOR = re.compile(r"캐피탈|렌터카|렌트카|오토리스|오토렌탈|오토렌트|자동차대여|자동차리스|파이낸셜서비스")
EQUIPMENT = re.compile(r"복합기|복사기|프린터|정수기|청정기|비데|안마|커피|카메라|장비|기계|기기|지게차|굴삭기|서버|노트북|컴퓨터|PC|모니터|"
                       r"가전|사무실|스튜디오|행사|부스|비품|가구|매트|냉장|냉난방|에어컨|카트|자전거|킥보드|의료|설비|공구|소프트웨어|"
                       r"라이선스|솔루션", re.I)
RENT_ACCOUNT = ("임차료", "리스료", "렌트료", "렌탈료", "렌트비", "렌탈비")
# 차량유지비가 아닌 계정에서 자동차세 · 보험료 · 유류비 등을 읽을 때 쓰는 말(8회차). 좁게 잡는다.
COST_ACCOUNT = ("세금과공과", "보험료", "여비교통비", "수선", "소모품비", "지급수수료", "연구개발비")
EXPLICIT_COST = re.compile(r"자동차세|자동차\s?(종합)?\s?보험|차량\s?(종합)?\s?보험|자동차\s?(정기)?\s?검사")
RUN_COST = re.compile(r"유류|주유|통행료|하이패스|주차|수리|수선|정비|타이어|엔진오일|세차|보험|검사")
NOT_COST = re.compile(r"과태료|범칙금|벌금|벌과금|가산세|가산금|위반|미납|압류|취득세|등록세|명의이전|매각|매도|폐차|상여|처분")
NOT_OURS = re.compile(r"직원\s?차량|임직원\s?차량|개인\s?차량|자가\s?차량|작업\s?차량|공사\s?차량|지원|장비|주차장|주차기|주차설비|"
                      r"주차장치|주차타워")
NONCAR_WORD = re.compile(r"굴삭기|굴착기|포크레인|지게차|덤프|크레인|로더|탱크로리|트레일러|레미콘|건설기계|중장비|이륜|오토바이|스쿠터|"
                         r"바이크|포터|봉고|라보|다마스|스타렉스|버스|탑차|카고|윙바디")
REGION_PLATE = re.compile(r"(서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충북|충남|전북|전남|경북|경남|제주)\s?\d{2}\s?[가-힣]\s?\d{4}")
PLATE_TAIL = re.compile(r"\s?(년|원)|월|일|개|회|건|명|층|동|번지|\d|[.,/-]\d")
INVENTORY = ("원재료", "부재료", "원부재료", "재공품", "반제품", "제품", "상품", "저장품", "미착품")
FINANCE = re.compile(r"캐피탈|파이낸셜|파이낸스|리스")
RENT_WORD = re.compile(r"렌트|렌터카|렌탈")
LEASE_WORD = re.compile(r"리스(?!트)")
RENTAL_LETTERS = ("하", "허", "호")   # 자동차대여사업용 번호판의 용도기호(자동차 등록번호판 등의 기준에 관한 고시, ★★☆ 원문 미확인)


def basis(rates: dict) -> list[tuple]:
    car, low, lease = rates["business_car"], rates["business_car_disposal"], rates["business_car_lease"]
    return [("업무용승용차 감가상각비 한도", car["depreciation_limit"]["value"], car["depreciation_limit"]["basis"], car["depreciation_limit"]["grade"], None),
            ("운행기록 미작성 인정 한도", car["no_log_limit"]["value"], car["no_log_limit"]["basis"], car["no_log_limit"]["grade"], None),
            ("렌트 감가상각비 상당액 비율", car["rent_ratio"]["value"], car["rent_ratio"]["basis"], car["rent_ratio"]["grade"], "0%"),
            ("리스 수선유지비 비율", lease["repair_ratio"]["value"], lease["repair_ratio"]["basis"], lease["repair_ratio"]["grade"], "0%"),
            ("처분손실 한도", car["disposal_limit"]["value"], car["disposal_limit"]["basis"], car["disposal_limit"]["grade"], None),
            ("저가양도 기준금액", low["low_price_amount"]["value"], low["low_price_amount"]["basis"], low["low_price_amount"]["grade"], None),
            ("저가양도 기준비율", low["low_price_ratio"]["value"], low["low_price_ratio"]["basis"], low["low_price_ratio"]["grade"], "0%")]


def _cost_type(text: str) -> str:
    if re.search(r"리스(?!트)|렌트|렌터카|렌탈|대여료|임차", text):
        return "임차료"
    if re.search(r"감가", text):
        return "감가상각비"
    if re.search(r"유류|주유|기름|충전", text):
        return "유류비"
    if re.search(r"보험", text):
        return "보험료"
    if re.search(r"수선|수리|정비|타이어|오일", text):
        return "수선비"
    if re.search(r"자동차세", text):
        return "자동차세"
    return "기타"


def rent_evidence(ln: Line, rent_account: bool) -> str:
    """차량유지비가 아닌 비용 계정의 줄이 차량 임차료로 보이는 정도. "" 은 읽지 않는다.

    「적요」: 적요에 임차를 가리키는 말과 차량을 가리키는 말(차량 · 자동차 · 렌터카 · 차량번호)이 함께 있다. 임차료 · 리스료
    계정은 차량을 가리키는 말만 있어도 읽는다(2회차부터 하던 대로).
    「거래처」: 적요에는 임차를 가리키는 말만 있고 거래처 이름이 차량 임대 회사로 보인다(캐피탈 · 렌터카 · 오토리스 등).
    적요에 장비 이름(복합기 · 정수기 등)이 있으면 읽지 않는다. 승용차 임차료가 아닐 수 있어 확인 줄을 낸다.
    """
    car = bool(PLATE.search(ln.memo) or CAR_WORD.search(ln.memo))
    if rent_account and car:
        return "적요"
    if not RENT_MEMO.search(ln.memo):
        return ""
    if car:
        return "적요"
    if LESSOR.search(ln.partner) and not EQUIPMENT.search(ln.memo):
        return "거래처"
    return ""


def strict_plate(memo: str) -> str:
    """차량유지비가 아닌 계정의 적요에서 읽는 차량번호. 「201호 2025년」 같은 글을 차량번호로 읽지 않게 좁게 본다.

    번호 뒤에 년 · 월 · 원 · 숫자 등이 바로 오면 읽지 않고, 번호 안에 빈칸이 있으면 적요에 차량 · 차량 비용을 가리키는 말이
    함께 있을 때만 읽는다."""
    m = PLATE.search(memo)
    if not m or PLATE_TAIL.match(memo[m.end():]) or (m.start() and memo[m.start() - 1].isdigit()):
        return ""
    if " " in m.group(0) and not (CAR_WORD.search(memo) or RUN_COST.search(memo) or EXPLICIT_COST.search(memo)):
        return ""
    return "".join(m.groups())


def plate_is_passenger(plate: str) -> bool:
    """차량번호 앞자리(차종 분류기호)가 승용인지. 두 자리는 01~69, 세 자리는 100~699 가 승용이고 70~79 · 700~799 는 승합,
    80~97 · 800~979 는 화물, 98~99 · 980~999 는 특수 · 긴급이다(자동차 등록번호판 등의 기준에 관한 고시, ★★☆ 원문 미확인).
    다른 계정에서 새로 읽는 줄의 기본 차량 칸을 정할 때만 쓴다(회계사가 고친다)."""
    head = re.match(r"\d+", plate).group(0)
    return int(head) < (70 if len(head) == 2 else 700)


def cost_evidence(ln: Line, account_name: str) -> tuple[str, str]:
    """차량유지비가 아닌 비용 계정의 줄이 차량 관련비용(자동차세 · 보험료 · 유류비 등)으로 보이는 근거와 비용 구분.
    ("", "") 은 읽지 않는다. 임차료는 `rent_evidence` 가 먼저 본다.

    「차량번호」: 적요에 차량번호가 있다(`strict_plate`).
    「적요」: 자동차세 · 자동차보험 · 차량보험 · 자동차검사처럼 차량 비용임이 분명한 말이 있거나, 차량을 가리키는 말(차량 ·
    자동차 · 승용차)과 유류 · 통행료 · 주차 · 수리 · 보험 같은 말이 함께 있다. 차량을 가리키는 말이 없는 유류비 · 통행료 ·
    주차비는 업무 출장 교통비와 가릴 수 없어 읽지 않는다.
    「계정」: 세금과공과 계정의 줄이고 적요에 자동차가 있다(자동차세로 본다).
    과태료 · 범칙금 · 취득세 · 명의이전 · 매각처럼 관련비용이 아닌 줄, 직원 차량 지원 · 작업 차량 · 장비 · 주차 시설 줄은 뺀다.
    """
    memo = ln.memo
    if NOT_COST.search(memo):
        return "", ""
    tax_account = "세금과공과" in account_name
    if strict_plate(memo):
        ev = "차량번호"
    elif EXPLICIT_COST.search(memo):
        ev = "적요"
    elif tax_account and "자동차" in memo:
        ev = "계정"
    elif CAR_WORD.search(memo) and RUN_COST.search(memo) and not NOT_OURS.search(memo):
        ev = "적요"
    else:
        return "", ""
    ctype = _cost_type(memo)
    if ctype in ("기타", "임차료"):
        if tax_account and "자동차" in memo and "부담금" not in memo:
            ctype = "자동차세"
        elif "보험료" in account_name:
            ctype = "보험료"
        elif "수선" in account_name:
            ctype = "수선비"
        else:
            ctype = "기타"
    return ev, ctype


def is_inventory(a: dict) -> bool:
    return a.get("subsection") == "재고자산" or a.get("name", "") in INVENTORY


def asset_rent_lines(b: Books, splits: dict) -> list[dict]:
    """자산 계정(재고자산 · 건설중인자산) 차변에 적힌 차량 임차료. 조건을 좁게 잡는다.

    그 거래처가 이미 차량으로 나눈 임차 거래처이고, 금액이 그 거래처 차량 하나의 임차료 금액과 같고, 그 차량에 그 달 임차료
    줄이 없고, 그 달이 그 차량 임차료 흐름과 이어지며(앞뒤 한 달까지), 적요가 임차를 가리키거나 그 차량 줄의 적요와 같을 때만
    읽는다. 같은 계정에서 같은 금액을 뒤에 대변으로 뺀 줄이 있으면(계정 재분류) 읽지 않는다.

    돌려주는 줄: {line, account, partner, car(차량 순번), month, inventory(재고자산 계정인지)}.
    """
    out: list[dict] = []
    taken: set[tuple[str, int, str]] = set()
    assets = [a for a in b.accounts(cls="자산") if is_inventory(a) or "건설중" in a.get("name", "")]
    for a in assets:
        acct_lines = b.lines_of([a])
        for ln in acct_lines:
            sp = splits.get(ln.partner)
            if not sp or ln.amount <= 0 or EQUIPMENT.search(ln.memo) or NOT_CAR.search(ln.memo):
                continue
            if any(x.partner == ln.partner and x.credit - x.debit == ln.amount and x.date >= ln.date for x in acct_lines):
                continue
            month = ln.date[:7]
            for i, c in enumerate(sp["cars"]):
                if not c["lines"] or ln.amount not in c["amounts"] or month in c["lines"] or (ln.partner, i, month) in taken:
                    continue
                lo, hi = _mi(min(c["lines"])), _mi(max(c["lines"]))
                if not lo - 1 <= _mi(month) <= hi + 1:
                    continue
                if not (RENT_MEMO.search(ln.memo) or ln.memo in {x.memo for x in c["lines"].values()}):
                    continue
                taken.add((ln.partner, i, month))
                out.append({"line": ln, "account": a, "partner": ln.partner, "car": i, "month": month,
                            "inventory": is_inventory(a)})
                break
    return out


def _mi(month: str) -> int:
    return int(month[:4]) * 12 + int(month[5:7])


def _vat_pair(a: int, b: int) -> bool:
    """두 금액이 공급가액과 부가세를 더한 금액 사이인지(큰 쪽 = 작은 쪽 × 1.1, 단수 1원)."""
    lo, hi = sorted((a, b))
    return lo > 0 and lo != hi and abs(hi * 10 - lo * 11) <= 10


def split_lessor(lines: list[Line]) -> dict:
    """차량번호 없이 임차료를 받는 한 거래처의 줄을 차량으로 나눈다. 계정은 가리지 않는다(같은 차량의 임차료가 계정 둘에
    나뉘어 있어도 한 흐름이다).

    1. 음수 줄은 같은 금액의 양수 줄과 짝지어 흐름에서 뺀다(취소). 같은 달에 임차료의 10분의 1 인 줄이나 적요에 부가세가
       있는 줄은 그 임차료 줄에 딸린 부가세로 본다.
    2. 금액 흐름: 같은 금액 v 가 한 달에 가장 많이 나온 횟수 n 만큼 흐름을 둔다(같은 금액이 한 달에 두 줄이면 두 대).
    3. 두 달 이상 되풀이되는 흐름을 긴 것부터 차량에 놓는다. 달이 겹치지 않는 차량이 있으면 그 차량에 잇고(부가세만큼
       다른 금액, 바로 이어지는 달이 먼저), 없으면 새 차량이다. 그래서 차량 하나에는 한 달에 임차료 줄이 하나만 있다.
    4. 한 번만 나온 줄은 그 달에 줄이 없는 차량에 잇는다. 그런 차량이 없으면 차량이 하나일 때 그 차량에 붙이고, 둘 이상이면
       어느 차량 것인지 가리지 못한 줄(REST)로 둔다. 되풀이 흐름이 하나도 없으면 한 달 줄 수만큼 차량을 두고 큰 금액부터 놓는다.

    달이 겹치지 않는 흐름을 한 차량으로 이으면 따로 둘 때보다 한도초과가 커지지 않는다(한도가 월수에 비례한다).

    돌려주는 dict: where {id(줄): (차량 순번 또는 REST, 까닭)}, cars [{lines {달: 줄}, amounts, extra}], reasons(확인할 까닭),
    per_month {달: 임차료 줄 수}.
    """
    order = lambda x: (x.date, x.no, x.account, x.amount)   # noqa: E731
    rent = sorted((ln for ln in lines if RENT_MEMO.search(ln.memo)), key=order)
    pos = [ln for ln in rent if ln.amount > 0]
    where: dict[int, tuple[int, str]] = {}

    # 1. 취소 줄 짝
    used: set[int] = set()
    pairs: list[tuple[Line, Line | None]] = []
    for n in (ln for ln in rent if ln.amount < 0):
        same = [x for x in pos if id(x) not in used and x.amount == -n.amount and x.date <= n.date]
        hit = max(same, key=lambda x: (x.date[:7] == n.date[:7], x.date, x.no), default=None)
        if hit is not None:
            used.add(id(hit))
        pairs.append((n, hit))
    live = [x for x in pos if id(x) not in used]

    # 1. 부가세 줄
    addons: list[tuple[Line, Line]] = []
    months: dict[str, list[Line]] = {}
    for ln in live:
        months.setdefault(ln.date[:7], []).append(ln)
    based: set[int] = set()
    addon_ids: set[int] = set()
    for ls in months.values():
        for w in ls:
            open_ = [v for v in ls if v is not w and id(v) not in based and id(v) not in addon_ids]
            base = next((v for v in open_ if abs(v.amount - 10 * w.amount) <= 10), None)
            if base is None and VAT_WORD.search(w.memo):
                base = max((v for v in open_ if v.amount > w.amount and not VAT_WORD.search(v.memo)),
                           key=lambda v: v.amount, default=None)
            if base is not None:
                based.add(id(base))
                addon_ids.add(id(w))
                addons.append((w, base))
    base_lines = [x for x in live if id(x) not in addon_ids]
    per_month = Counter(ln.date[:7] for ln in base_lines)

    # 2. 금액 흐름
    table: dict[int, dict[str, list[Line]]] = {}
    for ln in base_lines:
        table.setdefault(ln.amount, {}).setdefault(ln.date[:7], []).append(ln)
    flows = []
    for v, by_m in table.items():
        for i in range(max(len(x) for x in by_m.values())):
            flows.append({"amount": v, "i": i, "lines": {m: x[i] for m, x in by_m.items() if len(x) > i}})
    cars: list[dict] = []

    def put(car: dict, flow: dict) -> None:
        car["lines"].update(flow["lines"])
        car["amounts"][flow["amount"]] += len(flow["lines"])

    def new_car(flow: dict) -> None:
        cars.append({"lines": {}, "amounts": Counter(), "extra": []})
        put(cars[-1], flow)

    def near(car: dict, flow: dict) -> bool:
        lo, hi = _mi(min(car["lines"])), _mi(max(car["lines"]))
        return any(lo - 1 <= _mi(m) <= hi + 1 for m in flow["lines"])

    def best(free: list[dict], flow: dict) -> dict:
        return min(free, key=lambda c: (not any(_vat_pair(a, flow["amount"]) for a in c["amounts"]), not near(c, flow),
                                        cars.index(c)))

    # 3. 되풀이 흐름
    recurring = sorted((f for f in flows if len(f["lines"]) >= 2),
                       key=lambda f: (-len(f["lines"]), min(f["lines"]), -f["amount"], f["i"]))
    for f in recurring:
        free = [c for c in cars if not set(c["lines"]) & set(f["lines"])]
        if free:
            put(best(free, f), f)
        else:
            new_car(f)
    has_recurring = bool(cars)

    # 4. 한 번만 나온 줄
    rest: list[Line] = []
    once = sorted((f for f in flows if len(f["lines"]) == 1), key=lambda f: (min(f["lines"]), -f["amount"], f["i"]))
    for f in once:
        (m, ln), = f["lines"].items()
        free = [c for c in cars if m not in c["lines"]]
        if free:
            put(best(free, f) if has_recurring else free[0], f)
        elif not has_recurring:
            new_car(f)
        elif len(cars) == 1:
            cars[0]["extra"].append(ln)
        else:
            rest.append(ln)
    if not cars:
        cars.append({"lines": {}, "amounts": Counter(), "extra": []})

    one = len(cars) == 1
    for i, c in enumerate(cars):
        for ln in c["lines"].values():
            where[id(ln)] = (i, "차량번호 없이 리스 · 렌트료를 받는 거래처" if one else "거래처의 임차료 줄을 금액 흐름으로 나눔")
        for ln in c["extra"]:
            where[id(ln)] = (i, "되풀이되지 않는 줄, 그 거래처 차량이 하나라 그 차량에 붙임")
    for ln in rest:
        where[id(ln)] = (REST, "되풀이되지 않는 줄, 어느 차량 것인지 가리지 못함")
    for w, base in addons:
        where[id(w)] = (where[id(base)][0], "부가세 줄, 같은 달 임차료 줄에 붙임")
    for n, hit in pairs:
        amount = -n.amount
        to = next((i for i, c in enumerate(cars) if amount in c["amounts"]), 0 if one else REST)
        for ln in (n, hit):
            if ln is not None:
                where[id(ln)] = (to, "취소 줄과 그 짝")
    for ln in lines:
        if id(ln) not in where:
            where[id(ln)] = (0, "차량번호 없이 리스 · 렌트료를 받는 거래처") if one else \
                (REST, "임차료가 아닌 줄, 어느 차량 것인지 가리지 못함")

    reasons = []
    mixed = [c for c in cars if len(_amount_groups(c["amounts"])) > 1]
    if len(cars) >= 2 and not has_recurring:
        reasons.append(f"되풀이되는 금액이 없어 한 달에 가장 많은 줄 수({len(cars)})만큼 차량을 두고 큰 금액부터 차례로 놓았습니다")
    elif len(cars) >= 2 and mixed:
        reasons.append("금액이 다른 줄을 한 차량으로 이은 곳이 있습니다")
    if any(c["extra"] for c in cars):
        reasons.append("한 달에 임차료 줄이 둘 이상인 달이 있는데 되풀이되지 않는 줄이라 같은 차량에 붙였습니다")
    if any(to == REST for to, _ in where.values()):
        n_rest = sum(1 for to, _ in where.values() if to == REST)
        reasons.append(f"어느 차량 것인지 가리지 못한 줄 {n_rest}개를 「{REST_NAME}」 줄에 따로 두었습니다")
    return {"where": where, "cars": cars, "reasons": reasons, "per_month": dict(sorted(per_month.items()))}


def _amount_groups(amounts: Counter) -> list[list[int]]:
    """부가세만큼만 다른 금액은 한 묶음으로 본다."""
    groups: list[list[int]] = []
    for a in sorted(amounts):
        for g in groups:
            if any(_vat_pair(a, x) for x in g):
                g.append(a)
                break
        else:
            groups.append([a])
    return groups


def _month_text(per_month: dict) -> str:
    """달별 임차료 줄 수 글. 모든 달이 같으면 「달마다 3줄」."""
    if not per_month:
        return "임차료 줄 없음"
    counts = set(per_month.values())
    if len(counts) == 1:
        return f"달마다 {counts.pop()}줄({len(per_month)}달)"
    return "달별 줄 수 " + " · ".join(f"{int(m[5:7])}월 {n}" for m, n in per_month.items())


def _car_basis(partner: str, car: dict, twin: int, per_month: dict) -> str:
    """차량 줄의 「나눈 근거」: 금액 · 달 수 · 그 거래처의 달별 줄 수."""
    if not car["lines"]:
        return f"{partner} 줄(임차료 흐름 없음)"
    ms = sorted(car["lines"])
    amounts = sorted(car["amounts"].items(), key=lambda x: (-x[1], -x[0]))
    if len(amounts) == 1 and len(ms) > 1:
        text = f"매달 {amounts[0][0]:,}원"
    else:
        text = " · ".join(f"{a:,}원 {n}달" for a, n in amounts)
    text = f"{partner} 임차료 {text}, {len(ms)}달({int(ms[0][5:7])}월~{int(ms[-1][5:7])}월)"
    if twin:
        text += f", 같은 금액 줄이 한 달에 여럿이라 그중 {twin}째"
    if car["extra"]:
        text += f", 되풀이되지 않는 줄 {len(car['extra'])}개 {sum(x.amount for x in car['extra']):,}원을 붙임"
    return f"{text}. 거래처 {_month_text(per_month)}"


def compute(p: Paper, b: Books) -> None:
    car_accts = b.accounts(cls="비용", any_of=("차량",), none_of=("감가상각", "처분"))
    car_codes = {a["code"] for a in car_accts}
    lines = b.lines_of(car_accts)
    # 차량유지비가 아닌 비용 계정(판매비와관리비 · 제조원가 등)에서 차량 임차료로 드러나는 줄
    others = [a for a in b.accounts(cls="비용", none_of=("감가상각", "처분", "이자", "법인세"))
              if a["code"] not in car_codes and not re.search(r"영업외|법인세", a.get("section") or "")]
    evidence: dict[int, tuple[str, dict, bool]] = {}      # id(줄) → (근거, 계정, 임차료 · 리스료 계정인지)
    cost_ev: dict[int, tuple[str, dict, str]] = {}        # id(줄) → (근거, 계정, 비용 구분): 자동차세 · 보험료 등(8회차)
    for a in others:
        rent_account = any(k in a.get("name", "") for k in RENT_ACCOUNT)
        cost_account = any(k in a.get("name", "") for k in COST_ACCOUNT)
        for ln in b.lines_of([a]):
            ev = rent_evidence(ln, rent_account)
            if ev:
                evidence[id(ln)] = (ev, a, rent_account)
                lines.append(ln)
                continue
            ev, ctype = cost_evidence(ln, a.get("name", "")) if cost_account else ("", "")
            if ev:
                cost_ev[id(ln)] = (ev, a, ctype)
                lines.append(ln)
    lines.sort(key=lambda x: (x.date, x.no, x.account))

    def plate_of(ln: Line) -> str:
        m = PLATE.search(ln.memo)
        return "".join(m.groups()) if m else ""

    lessors = {ln.partner for ln in lines if ln.partner and RENT_MEMO.search(ln.memo) and not plate_of(ln)
               and not CAR_PATTERN.search(ln.memo) and not NOT_CAR.search(ln.memo) and id(ln) not in cost_ev}
    by_lessor: dict[str, list[Line]] = {}
    for ln in lines:
        if id(ln) in cost_ev:
            continue                      # 다른 계정의 자동차세 · 보험료 등은 임차료 흐름에 넣지 않는다
        if ln.partner in lessors and not (CAR_PATTERN.search(ln.memo) or NOT_CAR.search(ln.memo) or plate_of(ln)):
            by_lessor.setdefault(ln.partner, []).append(ln)
    splits = {partner: split_lessor(ls) for partner, ls in by_lessor.items()}

    # 자산 계정에 적힌 임차료(8회차). 재고자산 계정 줄은 그 차량 임차료에 넣고, 그 밖의 자산 계정 줄은 넣지 않고 확인 줄만 낸다.
    asset_ev: dict[int, dict] = {id(x["line"]): x for x in asset_rent_lines(b, splits)}
    lines += [x["line"] for x in asset_ev.values()]
    lines.sort(key=lambda x: (x.date, x.no, x.account))
    read_codes = {ln.account for ln in lines}
    asset_accts = sorted({x["account"]["code"]: x["account"] for x in asset_ev.values()}.values(), key=lambda a: a["code"])
    p.accounts = car_accts + [a for a in others if a["code"] in read_codes] + asset_accts

    def lessor_key(partner: str, to: int) -> str:
        if to == REST:
            return f"임차 {partner} {REST_NAME}"
        return f"임차 {partner}" if len(splits[partner]["cars"]) == 1 else f"임차 {partner} {to + 1}"

    basis_of: dict[str, str] = {}
    split_info = []
    for partner, sp in sorted(splits.items()):
        seen: Counter = Counter()
        twins = Counter(tuple(sorted(c["amounts"])) for c in sp["cars"])
        for i, c in enumerate(sp["cars"]):
            sig = tuple(sorted(c["amounts"]))
            seen[sig] += 1
            basis_of[lessor_key(partner, i)] = _car_basis(partner, c, seen[sig] if twins[sig] > 1 else 0, sp["per_month"])
        if any(to == REST for to, _ in sp["where"].values()):
            basis_of[lessor_key(partner, REST)] = f"{partner} 줄 가운데 어느 차량 것인지 가리지 못한 줄"
        split_info.append({"partner": partner, "cars": len(sp["cars"]), "sure": not sp["reasons"],
                           "reasons": list(sp["reasons"]), "months": sp["per_month"]})
    for x in asset_ev.values():
        x["car_key"] = lessor_key(x["partner"], x["car"])
        if x["inventory"]:
            basis_of[x["car_key"]] += f", {x['account'].get('name', '')} 계정(자산) {int(x['month'][5:7])}월 {x['line'].amount:,}원을 더함"

    models: dict[str, str] = {}
    for ln in lines:
        m = CAR_PATTERN.search(ln.memo)
        if id(ln) in asset_ev:
            x = asset_ev[id(ln)]
            key, ctype = (x["car_key"] if x["inventory"] else ASSET_RENT), "임차료"
            why = f"「{x['car_key']}」 임차료와 같은 금액, 그 차량에 그 달 줄 없음"
        elif m:
            plate = m.group("plate").replace(" ", "")
            key, ctype, why = plate, _cost_type(m.group("type")), "적요의 [차량코드] 차량번호 차종 (비용구분)"
            models.setdefault(plate, m.group("model").strip())
        elif NOT_CAR.search(ln.memo):
            key, ctype, why = OTHER_VEHICLE, _cost_type(ln.memo), "적요에 9인승 · 화물 등 표시"
        elif id(ln) in cost_ev:
            _, a, ctype = cost_ev[id(ln)]
            plate = strict_plate(ln.memo)
            if NOT_CAR.search(ln.memo) or NONCAR_WORD.search(ln.memo) or REGION_PLATE.search(ln.memo):
                key, why = OTHER_VEHICLE, "적요에 화물 · 승합 · 건설기계 등 표시"
            elif plate and not plate_is_passenger(plate):
                key, why = OTHER_VEHICLE, f"차량번호 {plate} 앞자리가 승합 · 화물 분류"
            elif plate:
                key, why = plate, "적요의 차량번호"
                basis_of.setdefault(key, "적요의 차량번호")
            elif ln.partner in splits and len(splits[ln.partner]["cars"]) == 1:
                key, why = lessor_key(ln.partner, 0), "임차 거래처에 낸 비용, 그 거래처 차량이 하나"
            else:
                key, why = NOT_ASSIGNED, "차량번호가 적요에 없습니다"
        elif plate_of(ln):
            key = plate_of(ln)
            ctype, why = _cost_type(ln.memo), "적요의 차량번호"
            basis_of.setdefault(key, "적요의 차량번호")
        elif ln.partner in splits:
            to, why = splits[ln.partner]["where"][id(ln)]
            key = lessor_key(ln.partner, to)
            ctype = "임차료" if (RENT_MEMO.search(ln.memo) or _cost_type(ln.memo) == "기타") else _cost_type(ln.memo)
        else:
            key, ctype, why = NOT_ASSIGNED, _cost_type(ln.memo), "차량을 가리킬 말이 적요에 없습니다"
        row = LineRow(ln, why, key, ctype)
        if id(ln) in evidence:
            ev, a, rent_account = evidence[id(ln)]
            tags = [] if rent_account else [f"차량유지비가 아닌 계정({a.get('name', '')})"]
            if ev == "거래처":
                tags.append("적요에 차량을 가리키는 말이 없어 거래처 이름으로 봄")
            row.why = " · ".join(tags)
        elif id(ln) in cost_ev:
            ev, a, _ = cost_ev[id(ln)]
            row.why = f"차량유지비가 아닌 계정({a.get('name', '')})" + (" · 세금과공과 계정의 자동차" if ev == "계정" else "")
        elif id(ln) in asset_ev:
            x = asset_ev[id(ln)]
            row.why = f"자산 계정({x['account'].get('name', '')})" + ("" if x["inventory"] else " · 계산에 넣지 않음")
        p.lines.append(row)

    # 차량이 하나뿐이면 차량을 가리지 못한 비용(유류비 · 주차비 등)도 그 차량 것으로 본다(29호 ⑮ 관련비용).
    # 다른 계정에서 새로 읽은 줄의 차량번호는 차량 수에 넣지 않는다(임차 차량과 같은 차량일 수 있고, 넣으면 전에 그 차량에
    # 붙던 비용이 「차량 미지정」 으로 빠진다).
    real = {r.pick for r in p.lines if id(r.line) not in cost_ev} - {NOT_ASSIGNED, OTHER_VEHICLE, ASSET_RENT}
    if len(real) == 1:
        only = next(iter(real))
        for r in p.lines:
            if r.pick == NOT_ASSIGNED:
                r.pick, r.label = only, "차량이 하나라 그 차량 비용으로 봄"
    p.take_lines(b, "차량", "비용 구분", kind="text")
    for r in p.lines:
        if r.pick2 not in COST_TYPES:
            r.pick2 = "기타"

    # 차량별 집계
    cars: dict[str, dict] = {}
    for r in p.lines:
        c = cars.setdefault(r.pick, {"key": r.pick, "costs": {t: 0 for t in COST_TYPES}, "rent_months": set(),
                                     "months_all": set(), "lease": False, "rent": False, "rent_word": False,
                                     "partners": set()})
        c["costs"][r.pick2] = c["costs"].get(r.pick2, 0) + r.line.amount
        c["months_all"].add(r.line.date[:7])
        if r.pick2 == "임차료" and r.line.amount > 0:
            c["rent_months"].add(r.line.date[:7])
            c["rent"] = True
            c["partners"].add(r.line.partner)
            if LEASE_WORD.search(r.line.memo):
                c["lease"] = True
            if RENT_WORD.search(r.line.memo):
                c["rent_word"] = True
    lim_dep = rate(b.rates, "business_car", "depreciation_limit")
    lim_log = rate(b.rates, "business_car", "no_log_limit")
    rent_ratio = frac(rate(b.rates, "business_car", "rent_ratio"))
    repair_ratio = frac(rate(b.rates, "business_car_lease", "repair_ratio"))
    args = (lim_dep, lim_log, rent_ratio, b.months, repair_ratio)
    rows = []
    migrated = []
    # 10-19: 그 차량번호가 포터 · 봉고 같은 화물 · 승합 적요와 함께 나온 차량은 대상 기본값을 「부」 로 둔다.
    # 10-21: 차량번호 앞자리가 승합 · 화물 · 특수 분류(두 자리 70~99, 세 자리 700~999)인 차량도 「부」 로 두고 확인 줄을 낸다.
    # 업무용승용차는 개별소비세 과세 승용자동차라(법인세법 제27조의2 제1항) 화물 번호판 차량은 대상이 아니다(분류기호 고시 ★★☆)
    truck_plates = {plate_of(ln) for ln in lines if (NOT_CAR.search(ln.memo) or NONCAR_WORD.search(ln.memo)) and plate_of(ln)}
    own_default = _own_dep_defaults(p, b, cars, truck_plates)
    carry_of, prior_only = _prior_carry(p, b, cars, models, own_default)
    order = sorted(cars, key=lambda k: (k == NOT_ASSIGNED, k == OTHER_VEHICLE, k == ASSET_RENT, k))
    not_target = {k for k in cars if k in truck_plates}
    by_number = {k for k in cars if PLATE.fullmatch(k) and not plate_is_passenger(k) and k not in not_target and k not in prior_only}
    if not_target:
        p.notes.append(f"차량 {', '.join(sorted(not_target))} 은 적요에 화물 · 승합 차종(포터 · 봉고 등)이 함께 적혀 대상을 「부」 로 "
                       "두었습니다. 개별소비세 과세 승용차이면 「여」 로 고치세요")
    if by_number:
        p.confirm.append(f"차량 {', '.join(sorted(by_number))} 은 차량번호 앞자리가 승합 · 화물 · 특수 분류라 대상을 「부」 로 두었습니다"
                         "(자동차 등록번호판 분류기호, 원문 미확인). 승용자동차이면 「여」 로 고치십시오")
        not_target |= by_number
    for k in order:
        c = cars[k]
        target = "부" if k in (NOT_ASSIGNED, OTHER_VEHICLE, ASSET_RENT) or k in not_target else "여"
        if k in prior_only:
            target = prior_only[k]["target"]
        kind = "리스" if c["lease"] else ("렌트" if c["rent"] or (k in prior_only and prior_only[k]["end"]) else "자가")
        months = len(c["rent_months"]) if c["rent"] else b.months
        months = max(1, min(12, months))
        # 7회차까지의 노란 칸 「리스 제외액」(보험료 · 자동차세 · 수선비 합계) 값은 「리스 보험료」 칸으로 옮긴다.
        old = b.override(p.id, f"리스 제외액/{k}")
        if old not in (MISSING, 0, "", None) and all(b.override(p.id, f"{name}/{k}") is MISSING for name in LEASE_KEYS):
            b.overrides[(p.id, f"리스 보험료/{k}")] = old
            migrated.append(k)
        row = {"key": k, "model": models.get(k, ""),
               "target": p.take(b, f"대상/{k}", target),
               "kind": p.take(b, f"임차 구분/{k}", kind),
               "log": p.take(b, f"운행기록/{k}", "여"),
               "ratio_in": p.take(b, f"업무사용비율/{k}", 1, "ratio"),
               "months": p.take(b, f"월수/{k}", months, "int"),
               "costs": dict(c["costs"]),
               "own_dep": p.take(b, f"자가 감가상각비/{k}", own_default.get(k, 0), "int"),
               "lease_ins": p.take(b, f"리스 보험료/{k}", 0, "int"),
               "lease_tax": p.take(b, f"리스 자동차세/{k}", 0, "int"),
               "lease_repair": p.take(b, f"리스 수선유지비/{k}", 0, "int"),
               "lease_7": p.take(b, f"수선유지비 7% 적용/{k}", "부"),
               "carry": p.take(b, f"전기 이월액/{k}", carry_of.get(k, 0), "int"),
               "basis": basis_of.get(k, ""),
               "unclear": _unclear_lessor(c) and f"임차 구분/{k}" not in p.overridden}
        row["ratio_in"] = row["ratio_in"] if row["ratio_in"] != 1.0 else 1
        row["costs"]["감가상각비"] += row["own_dep"]
        rows.append(car_calc(row, *args))
    p.extra["cars"] = rows

    disposal = disposals(p, b)
    p.extra["disposal"] = disposal

    on = [r for r in rows if r["target"] == "여"]
    total_cost = sum(r["total"] for r in on)
    personal = sum(r["personal"] for r in on)
    excess_rent = sum(r["excess"] for r in on if r["kind"] != "자가")
    excess_own = sum(r["excess"] for r in on if r["kind"] == "자가")
    reversal = sum(r["reversal"] for r in on)
    disp_excess = sum(d["excess"] for d in disposal if d["apply"] == "여")
    p.values = {"관련비용": total_cost, "감가상각비상당액": sum(r["dep_eq"] for r in on), "업무외사용금액": personal,
                "한도초과(임차)": excess_rent, "한도초과(자가)": excess_own, "이월액손금추인": reversal,
                "처분손실한도초과": disp_excess, "처분손실한도초과후보": sum(d["excess"] for d in disposal),
                "저가양도차액": sum(d["low_price"] for d in disposal),
                "차량수": len(on), "미지정비용": sum(r["total"] for r in rows if r["key"] == NOT_ASSIGNED),
                "다른계정임차료": sum(r.line.amount for r in p.lines if id(r.line) in evidence),
                "다른계정관련비용": sum(r.line.amount for r in p.lines if id(r.line) in cost_ev),
                "자산계정임차료": [{"account": x["account"]["code"], "name": x["account"].get("name", ""),
                                    "partner": x["partner"], "month": x["month"], "amount": x["line"].amount,
                                    "car": x["car_key"], "included": r.pick not in (ASSET_RENT, NOT_ASSIGNED, OTHER_VEHICLE)}
                                   for r in p.lines for x in [asset_ev.get(id(r.line))] if x],
                "임차나누기": split_info,
                "cars": [_car_json(r) for r in rows],
                "처분": [{k: d[k] for k in ("date", "no", "memo", "book", "price", "loss", "limit", "apply", "related",
                                            "market", "low_price", "excess", "key")} for d in disposal]}
    subj = subject_of(car_accts, "차량유지비")
    p.adjustments = [
        Adj("가산", subj, personal, "상여", "업무용승용차 업무외사용금액", "업무용승용차 업무외사용금액 손금불산입", "업무외사용금액"),
        Adj("가산", subj, excess_rent, "기타사외유출", "업무용승용차 감가상각비상당액 한도초과",
            "업무용승용차 감가상각비상당액 800만원 초과 손금불산입", "한도초과(임차)"),
        Adj("가산", subj, excess_own, "유보", "업무용승용차 감가상각비 한도초과",
            "업무용승용차 감가상각비 800만원 초과 손금불산입", "한도초과(자가)", "업무용승용차 감가상각비", "증가", 1),
        Adj("차감", subj, reversal, "기타", "업무용승용차 한도초과 이월액 손금추인",
            "전기 감가상각비상당액 한도초과 이월액 손금산입", "이월액손금추인"),
        Adj("가산", subj, disp_excess, "기타사외유출", "업무용승용차 처분손실 한도초과",
            "업무용승용차 처분손실 800만원 초과 손금불산입", "처분손실한도초과"),
    ]
    _split_messages(p, splits)
    _evidence_messages(p, evidence)
    _cost_messages(p, cost_ev, real)
    _asset_messages(p, asset_ev, rows, args)
    _lease_messages(p, rows, args)
    for k in migrated:
        p.notes.append(f"「{k}」 의 옛 노란 칸 「리스 제외액」 값을 「리스료 중 보험료」 칸으로 옮겼습니다. 보험료 · 자동차세 · 수선유지비로 나눠 고치세요")
    p.notes.append("운행기록 작성 여부는 「여」, 업무사용비율은 100% 로 두었습니다. 운행기록이 없으면 「부」 로 바꾸세요(1천5백만원 기준)")
    p.notes.append("리스 차량의 감가상각비 상당액은 리스료에서 보험료 · 자동차세 · 수선유지비를 뺀 금액입니다. 리스료에 들어 있으면 노란 칸에 넣으세요")
    if not own_default:
        p.notes.append("자가 차량의 감가상각비는 감가상각 조서의 차량운반구 회사계상액 중 그 차량 몫을 「자가 감가상각비」 노란 칸에 넣습니다")
    prior_car = [a for a in (b.prior or {}).get("adjustments", [])
                 if ("차량" in a.get("subject", "") or "승용차" in a.get("subject", "")) and a.get("side") == "가산"]
    _carry_messages(p, rows, carry_of, prior_only)
    if prior_car and not _prior_29(b):
        amt = sum(int(a.get("amount") or 0) for a in prior_car)
        p.confirm.append(f"전기 15호에 차량 관련 손금불산입 {amt:,}원이 있습니다. 감가상각비상당액 한도초과 이월액이면 차량별 「전기 이월액」 란에 넣으세요")
    if any(r["key"] == NOT_ASSIGNED and r["total"] for r in rows):
        p.notes.append("차량을 가리지 못한 비용(유류비 · 주차비 등)은 「차량 미지정」 줄에 모았고 계산에서 뺐습니다. 운행기록을 쓰지 않은 차량이 있으면 차량별로 나눠야 합니다")
    for d in disposal:
        open_ = d["related"] == "확인 필요" or (d["apply"] != "여" and d["excess"]) or d["low_price"]
        (p.confirm if open_ else p.notes).append(_disposal_message(d))
    if disposal:
        p.notes.append("처분손실은 회사 장부의 장부가액으로 셉니다. 그 차량에 감가상각비 한도초과 이월액(유보)이 있으면 세무상 장부가액이 "
                       "그만큼 커져 처분손실도 커집니다(29호 세무상 장부가액)")
    p.settle(bool(total_cost or rows or disposal))


def _prior_29(b: Books) -> list[dict]:
    """전기 29호 3절 차량별 이월 줄 가운데 차기이월액이 있는 것(전기.json rows["29"])."""
    return [r for r in ((b.prior or {}).get("rows") or {}).get("29") or [] if int(r.get("closing") or 0) > 0]


def _ymd(s: str) -> str:
    return str(s or "").replace(".", "-")[:10]


def _own_dep_defaults(p: Paper, b: Books, cars: dict, truck_plates: set) -> dict[str, int]:
    """자가 차량 「자가 감가상각비」 기본값(10-25). 감가상각 조서의 차량운반구 회사 상각비(depreciation.company_dep_of)를 자가 차량에
    나눈다. 차량유지비 계정에는 감가상각비 줄이 없어 기본값 0 이면 자가 차량 800만원 초과 유보(법인세법 제27조의2 제3항)가 빠졌다.

    자가 차량: 승용 번호판 차량번호 줄이고 임차료 줄이 없으며 렌트 번호판(하 · 허 · 호)이 아닌 차량. 한 대면 상각비 전부를 둔다.
    여러 대면 전기 29호 3절 차량별 줄에서 전기 사업연도 내내 가진 차량의 전기 상각비(한도초과 + 한도 800만원, 정액 상각이면 해마다
    같다)를 그 차량 몫으로 어림하고, 어림이 없는 차량이 한 대만 남으면 나머지를 둔다. 그래도 나누지 못하면 0 과 확인 줄이다.
    회계사가 노란 칸에 넣은 차량은 그 값을 쓰고 남은 금액만 나눈다. 여러 대로 나눈 값은 확인 줄에 남긴다."""
    from .depreciation import company_dep_of
    cands = sorted(k for k, c in cars.items()
                   if PLATE.fullmatch(k) and plate_is_passenger(k) and k not in truck_plates and not c["rent"] and not c["lease"]
                   and PLATE.fullmatch(k).group(2) not in RENTAL_LETTERS)
    if not cands:
        return {}
    total = company_dep_of(b, "차량")
    pool = total - sum(cars[k]["costs"].get("감가상각비", 0) for k in cands)
    by_hand = {k: b.override(p.id, f"자가 감가상각비/{k}") for k in cands}
    by_hand = {k: int(v) for k, v in by_hand.items() if v not in (MISSING, "", None)}
    pool -= sum(by_hand.values())
    left = [k for k in cands if k not in by_hand and not cars[k]["costs"].get("감가상각비")]
    if pool <= 0 or not left:
        return {}
    if len(left) == 1:
        p.notes.append(f"감가상각 조서의 차량운반구 회사 상각비 {total:,}원 가운데 {pool:,}원을 자가 차량 {left[0]} 의 「자가 감가상각비」 "
                       "기본값으로 넣었습니다(장부의 자가 승용차 한 대). 차량운반구에 업무용승용차가 아닌 차량이 있으면 그 몫을 빼십시오")
        return {left[0]: pool}
    lim = int(rate(b.rates, "business_car", "depreciation_limit"))
    fy_start = str(b.info.get("fy_start") or f"{b.fy or 2025}-01-01")
    prior_start = f"{int(fy_start[:4]) - 1}{fy_start[4:]}"
    est = {}
    for r in ((b.prior or {}).get("rows") or {}).get("29") or []:
        k = re.sub(r"\s", "", str(r.get("car") or ""))
        start = _ymd(r.get("start"))
        if k in left and not r.get("end") and start and start <= prior_start and int(r.get("excess") or 0) > 0:
            est[k] = int(r["excess"]) + lim
    rest = [k for k in left if k not in est]
    if not est or sum(est.values()) > pool or len(rest) > 1 or (not rest and sum(est.values()) != pool):
        p.confirm.append(f"자가 차량 {', '.join(left)} 의 「자가 감가상각비」 를 넣지 못했습니다. 감가상각 조서의 차량운반구 회사 상각비 "
                         f"{total:,}원 가운데 차량마다 몫을 노란 칸에 넣으십시오(비어 있으면 800만원 초과 유보가 빠집니다)")
        return {}
    out = dict(est)
    if rest:
        out[rest[0]] = pool - sum(est.values())
    text = ", ".join(f"{k} {v:,}원" for k, v in out.items())
    p.confirm.append(f"감가상각 조서의 차량운반구 회사 상각비 {total:,}원을 자가 차량에 나눠 「자가 감가상각비」 기본값으로 넣었습니다: {text}. "
                     "전기 29호 3절 한도초과가 있는 차량은 전기 상각비(한도초과 + 800만원)와 같다고 어림했고"
                     + (f", {rest[0]} 에는 나머지를 두었습니다" if rest else "")
                     + ". 고정자산 대장의 차량별 상각비로 확인하십시오")
    return out


def _prior_disposed(p: Paper, b: Books, rows: list[dict]) -> set[str]:
    """전기에 처분해 이월액을 이미 손금추인한 차량(10-25). 전기 15호 차감 줄 가운데 업무용승용차 · 차량 과목이고 조정내용에
    양도 · 처분 · 매각이 든 감가상각비 한도초과 추인 줄을, 조정내용의 차량번호나 금액(29호 3절 그 차량의 차기이월액과 같음)으로
    차량에 잇는다. 그 차량은 이월액을 0 으로 본다(처분한 차량의 차기이월액을 3절에 그대로 찍는 신고본이 있다). 잇지 못한 줄은 확인 줄이다."""
    out = set()
    by_plate = {re.sub(r"\s", "", str(r.get("car") or "")): int(r.get("closing") or 0) for r in rows}
    for a in (b.prior or {}).get("adjustments", []) or []:
        subj, note = str(a.get("subject") or ""), str(a.get("note") or "")
        if a.get("side") != "차감" or not re.search(r"승용차|차량", subj + note) or not re.search(r"양도|처분|매각", note):
            continue
        if not re.search(r"감가상각|한도초과|이월", subj + note) or re.search(r"처분손실", subj + note):
            continue
        amt = int(a.get("amount") or 0)
        m = PLATE.search(note)
        plate = "".join(m.groups()) if m else ""
        hit = [plate] if plate in by_plate else [k for k, v in by_plate.items() if v and v == amt]
        if len(hit) == 1:
            out.add(hit[0])
            p.notes.append(f"전기 15호에 차량 {hit[0]} 의 처분 손금추인 {amt:,}원이 있어 그 차량의 전기 이월액을 0 으로 보았습니다"
                           "(처분한 사업연도에 이월액을 손금산입, 법인세법 시행령 제50조의2 제11항)")
        else:
            p.confirm.append(f"전기 15호에 업무용승용차 처분 손금추인 {amt:,}원이 있는데 29호 3절의 어느 차량 것인지 잇지 못했습니다. "
                             "그 차량이면 「전기 이월액」 을 0 으로 고치십시오")
    return out


def _prior_carry(p: Paper, b: Books, cars: dict, models: dict, own_default: dict | None = None) -> tuple[dict, dict]:
    """전기 29호 3절 차기이월액 → 차량별 「전기 이월액」 기본값(10-21). (차량 이름 → 이월액, 당기 장부에 없어 새로 둔 차량 → 정보).

    차량번호가 당기 차량 이름과 같으면 그 차량에 둔다. 당기 장부에 없는 차량은 줄을 하나 만든다(관련비용 0). 이월액은 다음 사업연도부터
    그 차량의 감가상각비(상당액) 업무사용분이 800만원에 못 미치는 만큼 손금에 넣는다(법인세법 제27조의2 제3항, 시행령 제50조의2 제11항).
    새로 둔 차량의 대상 기본값: 임차가 당기 시작 전에 끝났거나 자가 차량을 산 지 5년(정액법 내용연수, 같은 조 제3항)이 지나 당기
    감가상각비가 없으면 「여」(한도 전부를 추인), 아니면 「부」 와 확인 줄(당기 장부의 다른 이름 차량과 같은 차량일 수 있다)."""
    rows = _prior_29(b)
    if not rows:
        return {}, {}
    own_default = own_default or {}
    disposed = _prior_disposed(p, b, rows)
    fy_start = str(b.info.get("fy_start") or f"{b.fy or 2025}-01-01")
    by_norm = {re.sub(r"\s", "", k): k for k in cars}
    carry_of, prior_only, held = {}, {}, {}
    for r in rows:
        plate = re.sub(r"\s", "", str(r.get("car") or ""))
        amt = int(r.get("closing") or 0)
        if not plate or plate in disposed:
            continue
        end, start = _ymd(r.get("end")), _ymd(r.get("start"))
        own_done = not end and bool(start) and f"{int(start[:4]) + 5}{start[4:]}" <= fy_start
        if plate in by_norm:
            k = by_norm[plate]
            lease_on = bool(end) and end >= fy_start and not cars[k]["rent"]
            own_dep = b.override(p.id, f"자가 감가상각비/{k}")
            own_dep = own_default.get(k, 0) if own_dep is MISSING else own_dep
            own_on = (not end and not own_done and not cars[k]["costs"].get("감가상각비")
                      and own_dep in (MISSING, 0, "", None))
            if lease_on or own_on:
                # 이 줄에 감가상각비(상당액)가 없다. 임차료가 다른 이름(임차 거래처) 줄로 잡혔거나 자가 차량 감가상각비가 감가상각 조서에만
                # 있어(노란 칸 「자가 감가상각비」) 이월액을 넣으면 상당액 0 으로 보고 800만원까지 잘못 추인한다
                held[k] = (amt, "임차료" if lease_on else "감가상각비")
                continue
            carry_of[k] = carry_of.get(k, 0) + amt
            continue
        ended = bool(end) and end < fy_start
        cars[plate] = {"key": plate, "costs": {t: 0 for t in COST_TYPES}, "rent_months": set(), "months_all": set(),
                       "lease": False, "rent": False, "rent_word": False, "partners": set()}
        models.setdefault(plate, str(r.get("model") or ""))
        carry_of[plate] = amt
        prior_only[plate] = {"target": "여" if (ended or own_done) else "부", "end": end, "start": start, "amount": amt,
                             "why": ("임차 끝남" if ended else "취득 5년 지남") if (ended or own_done) else ""}
    for k, (amt, what) in held.items():
        if what == "임차료":
            p.confirm.append(f"전기 이월 차량 {k}(이월액 {amt:,}원)은 임차가 당기에도 이어지는데 그 차량번호 줄에 임차료가 없어 「전기 이월액」 을 "
                             "넣지 않았습니다. 임차료가 다른 차량 이름(임차 거래처) 줄에 있으면 그 줄의 차량 칸을 차량번호로 고치고 이월액을 넣으십시오")
        else:
            p.confirm.append(f"전기 이월 차량 {k}(이월액 {amt:,}원)은 산 지 5년이 지나지 않은 자가 차량인데 「자가 감가상각비」 가 비어 「전기 이월액」 을 "
                             "넣지 않았습니다. 감가상각 조서의 그 차량 상각비를 「자가 감가상각비」 에 넣고 이월액을 넣으십시오")
    return carry_of, prior_only


def _carry_messages(p: Paper, rows: list[dict], carry_of: dict, prior_only: dict) -> None:
    if not carry_of:
        return
    got = [r for r in rows if r["key"] in carry_of]
    text = ", ".join(f"{r['key']} {carry_of[r['key']]:,}원" for r in got)
    p.notes.append(f"전기 29호 3절 차기이월액을 차량별 「전기 이월액」 기본값으로 넣었습니다: {text}. 이월액은 그 차량의 감가상각비(상당액) "
                   "업무사용분이 800만원에 못 미치는 만큼 손금추인합니다(법인세법 시행령 제50조의2 제11항)")
    for k, x in prior_only.items():
        r = next((r for r in rows if r["key"] == k), None)
        if r is None:
            continue
        period = f"{x['start']} ~ {x['end']}" if x["end"] else f"{x['start']} 취득"
        if x["target"] == "여":
            # 임차가 끝난 차량의 이월액 추인은 시행령 제50조의2 제11항 제2호 문언(다음 사업연도부터 그 차량의 상당액 업무사용분이
            # 800만원에 못 미치는 만큼)을 따른 것이다. 임차 종료 뒤를 직접 다룬 해석은 찾지 못했고(★★☆), 추인하지 않는 신고본도 있어 확인 줄이다
            p.confirm.append(f"전기 이월 차량 {k}({period})은 당기 장부에 비용 줄이 없고 {x['why']}이라 대상 「여」 로 두어 "
                             f"{r['reversal']:,}원을 손금추인했습니다(법인세법 시행령 제50조의2 제11항, 이월액 {x['amount']:,}원). 당기에 "
                             "처분했으면 처분손실 표에서 이월액을 세무상 장부가액에 더하고, 추인하지 않으려면 이 줄 대상을 「부」 로 바꾸십시오")
        else:
            p.confirm.append(f"전기 이월 차량 {k}({period}, 이월액 {x['amount']:,}원)이 당기 장부의 차량번호와 이어지지 않아 대상 「부」 로 "
                             "두었습니다. 당기 장부의 다른 이름 차량(임차 거래처 이름 등)과 같은 차량이면 그 차량의 「전기 이월액」 칸에 넣고, "
                             "당기에 쓰지 않은 차량이면 이 줄 대상을 「여」 로 바꾸십시오(자가 차량은 「자가 감가상각비」 도 넣음)")


def _split_messages(p: Paper, splits: dict) -> None:
    """임차 거래처를 차량 둘 이상으로 나눴거나 나누기에 확신이 없는 곳의 메모 · 확인 줄."""
    for partner, sp in sorted(splits.items()):
        n = len(sp["cars"])
        months = _month_text(sp["per_month"])
        if sp["reasons"]:
            p.confirm.append(f"{partner} 임차료 줄을 차량 {n}대로 보았지만 확인이 필요합니다. {' '.join(x + '.' for x in sp['reasons'])} "
                             f"{months}. 원장 표에서 줄마다 차량 칸을 고치면 차량 수와 차량별 금액이 바뀝니다(새 이름을 쓰면 차량 줄이 "
                             "하나 더 생깁니다)")
        elif n >= 2:
            p.notes.append(f"{partner} 임차료 줄을 차량 {n}대로 나눠 차량마다 한도를 따로 적용했습니다({months}, 금액 흐름마다 차량 하나). "
                           "나눈 근거는 차량 표 끝 열에 있고, 원장 표에서 줄마다 차량 칸을 고칠 수 있습니다")


def _evidence_messages(p: Paper, evidence: dict) -> None:
    """차량유지비가 아닌 계정에서 읽어 온 임차료 줄의 확인 줄. 계정 · 거래처마다 한 줄."""
    groups: dict[tuple, dict] = {}
    for r in p.lines:
        got = evidence.get(id(r.line))
        if not got:
            continue
        ev, a, rent_account = got
        if rent_account and ev == "적요":
            continue                      # 임차료 · 리스료 계정에서 적요로 차량이 드러난 줄은 2회차부터 읽던 줄이다
        g = groups.setdefault((a.get("name", ""), r.line.partner, rent_account), {"n": 0, "amount": 0, "weak": False})
        g["n"] += 1
        g["amount"] += r.line.amount
        g["weak"] = g["weak"] or ev == "거래처"
    for (account, partner, rent_account), g in sorted(groups.items()):
        text = f"{account} 계정의 {partner or '거래처 없는'} 임차료 {g['n']}줄 {g['amount']:,}원을 차량 임차료로 읽었습니다"
        if not rent_account:
            text += "(차량유지비가 아닌 계정)"
        if g["weak"]:
            text += ". 적요에 차량을 가리키는 말이 없어 거래처 이름으로 보았습니다. 장비 리스 · 렌탈일 수 있습니다"
        text += f". 승용차 임차료가 아니면 원장 표에서 그 줄의 차량 칸을 「{OTHER_VEHICLE}」 으로 바꾸세요"
        p.confirm.append(text)


def _cost_messages(p: Paper, cost_ev: dict, known: set) -> None:
    """차량유지비가 아닌 계정에서 읽어 온 자동차세 · 보험료 · 유류비 등의 확인 줄. 계정마다 한 줄."""
    groups: dict[str, dict] = {}
    for r in p.lines:
        got = cost_ev.get(id(r.line))
        if not got:
            continue
        g = groups.setdefault(got[1].get("name", ""), {"n": 0, "amount": 0, "types": Counter(), "other": [0, 0],
                                                         "loose": [0, 0], "new": set(), "listed": set()})
        g["n"] += 1
        g["amount"] += r.line.amount
        g["types"][r.pick2] += r.line.amount
        if r.pick == OTHER_VEHICLE:
            g["other"] = [g["other"][0] + 1, g["other"][1] + r.line.amount]
            plate = strict_plate(r.line.memo)
            if plate in known and p.inputs.get(f"대상/{plate}") == "여":
                g["listed"].add(plate)
        elif r.pick == NOT_ASSIGNED:
            g["loose"] = [g["loose"][0] + 1, g["loose"][1] + r.line.amount]
        elif r.pick not in known and r.pick != ASSET_RENT:
            g["new"].add(r.pick)
    for account, g in sorted(groups.items()):
        types = " · ".join(f"{t} {g['types'][t]:,}원" for t in COST_TYPES if g["types"][t])
        text = f"{account} 계정에서 차량 비용 {g['n']}줄 {g['amount']:,}원을 읽었습니다(차량유지비가 아닌 계정, {types})"
        if g["other"][0]:
            text += (f". {g['other'][0]}줄 {g['other'][1]:,}원은 차량번호 앞자리나 적요로 보아 「{OTHER_VEHICLE}」 에 두었습니다"
                     "(대상 부). 승용차이면 그 줄의 차량 칸을 차량번호로 바꾸세요")
        if g["listed"]:
            text += (f". 차량번호 {' · '.join(sorted(g['listed']))} 은 차량유지비 줄이 있어 차량 표에 대상 「여」 로 있습니다. 승용차가 "
                     "아니면 차량 표의 대상을 「부」 로 바꾸세요")
        if g["loose"][0]:
            text += f". 차량번호가 없는 {g['loose'][0]}줄 {g['loose'][1]:,}원은 「{NOT_ASSIGNED}」 에 두었습니다"
        if g["new"]:
            text += (f". 차량 표에 없던 차량번호 {' · '.join(sorted(g['new']))} 은 새 차량 줄로 두었습니다. 이미 있는 임차 차량과 "
                     "같은 차량이면 원장 표에서 그 줄의 차량 칸을 그 차량 이름으로 바꾸세요")
        if g["other"][0] < g["n"]:
            text += f". 차량 비용이 아니거나 승용차가 아닌 줄은 차량 칸을 「{OTHER_VEHICLE}」 으로 바꾸세요"
        p.confirm.append(text)
    if groups:
        p.notes.append("차량유지비가 아닌 계정에서 읽은 자동차세 · 보험료 등은 29호 관련비용에 들어갑니다. 운행기록 「여」 · 업무사용비율 "
                       "100% 인 차량은 조정 금액이 그대로이고, 운행기록 「부」 인 차량은 관련비용이 늘어 업무외사용금액이 달라집니다")


def _what_if(row: dict, args: tuple, rent: int = 0, months: int = 0, **change) -> dict:
    """차량 줄 하나를 값만 바꿔 다시 계산한다(확인 줄에 두 금액을 함께 적을 때 쓴다). 원래 줄은 바꾸지 않는다."""
    alt = {**row, "costs": dict(row["costs"]), **change}
    alt["costs"]["임차료"] = alt["costs"].get("임차료", 0) + rent
    alt["months"] = max(1, alt["months"] + months)
    return car_calc(alt, *args)


def _asset_messages(p: Paper, asset_ev: dict, rows: list[dict], args: tuple) -> None:
    """자산 계정에 적힌 임차료의 확인 줄. 줄마다 한 줄이고, 넣었을 때와 뺐을 때의 월수 · 한도초과를 함께 적는다."""
    by_key = {r["key"]: r for r in rows}
    for r in p.lines:
        x = asset_ev.get(id(r.line))
        if not x:
            continue
        key, amount, m = x["car_key"], r.line.amount, int(x["month"][5:7])
        text = (f"{x['account'].get('name', '')} 계정(자산)의 {x['partner']} {m}월 {amount:,}원은 「{key}」 임차료와 금액이 같고 "
                f"그 차량에 {m}월 임차료 줄이 없습니다")
        car = by_key.get(key)
        if r.pick != r.default or car is None:
            p.notes.append(f"{text}. 회계사 값에 따라 「{r.pick}」 에 두었습니다")
            continue
        step = 0 if f"월수/{key}" in p.overridden else 1
        if r.pick == key:
            alt = _what_if(car, args, rent=-amount, months=-step)
            p.confirm.append(f"{text}. 그 차량의 {m}월 임차료로 읽어 임차료와 월수에 넣었습니다(월수 {car['months']} · 한도초과 "
                             f"{car['excess']:,}원). 자산으로 처리한 임차료는 원가에 들어가 손금이 되는 때가 다를 수 있습니다. 당기 "
                             f"손금이 아니면 원장 표에서 그 줄의 차량 칸을 「{ASSET_RENT}」 로 바꾸세요(빼면 월수 {alt['months']} · "
                             f"한도초과 {alt['excess']:,}원)")
        else:
            alt = _what_if(car, args, rent=amount, months=step)
            p.confirm.append(f"{text}. 재고자산이 아닌 자산 계정이라 계산에 넣지 않았습니다(「{ASSET_RENT}」 줄, 대상 부). 그 차량의 "
                             f"{m}월 임차료이고 당기 손금이면 원장 표에서 그 줄의 차량 칸을 「{key}」 로 바꾸세요(넣으면 월수 "
                             f"{alt['months']} · 한도초과 {alt['excess']:,}원, 지금 월수 {car['months']} · 한도초과 {car['excess']:,}원)")


def _unclear_lessor(c: dict) -> bool:
    """거래처 이름이 캐피탈 · 리스 회사인데 임차료 줄 적요에 리스도 렌트도 없는 차량(리스인지 렌트인지 적요로 가릴 수 없다)."""
    return bool(c["rent"] and not c["lease"] and not c["rent_word"] and any(FINANCE.search(x) for x in c["partners"]))


def _lease_messages(p: Paper, rows: list[dict], args: tuple) -> None:
    """리스 차량의 보험료 · 자동차세 · 수선유지비 확인 줄, 리스인지 렌트인지 가리지 못한 차량의 확인 줄."""
    pct = f"{int(args[2] * 100)}%"
    on = [r for r in rows if r["target"] == "여" and r["costs"].get("임차료", 0) > 0]
    lease = [r for r in on if r["kind"] == "리스"]
    todo = [r for r in lease if not (r["lease_ins"] or r["lease_tax"] or r["lease_repair"]) and r["lease_7"] != "여"]
    if todo:
        parts = []
        for r in todo:
            alt = _what_if(r, args, lease_7="여")
            parts.append(f"「{r['key']}」 감가상각비 상당액 {alt['dep_eq']:,}원 · 한도초과 {alt['excess']:,}원"
                         f"(지금 {r['dep_eq']:,}원 · {r['excess']:,}원)")
        p.confirm.append(f"리스 차량 {len(todo)}대의 리스료에 든 보험료 · 자동차세를 리스 계약서로 확인해 넣으십시오. 수선유지비를 따로 "
                         "가리기 어려우면 (임차료 − 보험료 − 자동차세) × 7% 를 수선유지비로 할 수 있습니다(법인세법 시행규칙 "
                         "제27조의2 제6항 제1호). 지금은 리스료에서 아무것도 빼지 않았습니다. 「수선유지비 7% 적용」 을 「여」 로 "
                         f"바꾸면 {', '.join(parts)} 이 됩니다")
    for r in lease:
        if any(r is t for t in todo):
            continue
        if r["lease_7"] == "여" and r["lease_repair"]:
            p.notes.append(f"「{r['key']}」 은 수선유지비 칸에 값이 있어 7% 를 적용하지 않았습니다")
        elif r["lease_7"] == "여":
            p.notes.append(f"「{r['key']}」 의 수선유지비를 (임차료 − 보험료 − 자동차세) × 7% = {r['lease_repair_applied']:,}원으로 "
                           f"계산했습니다(감가상각비 상당액 {r['dep_eq']:,}원 · 한도초과 {r['excess']:,}원)")
        elif not r["lease_repair"]:
            alt = _what_if(r, args, lease_7="여")
            p.notes.append(f"「{r['key']}」 은 수선유지비 칸이 비어 있습니다. 「수선유지비 7% 적용」 을 「여」 로 바꾸면 수선유지비 "
                           f"{alt['lease_repair_applied']:,}원을 더 빼 한도초과가 {alt['excess']:,}원이 됩니다(지금 {r['excess']:,}원)")
    for r in on:
        if not r.get("unclear"):
            continue
        rent, lease_, seven = (_what_if(r, args, kind="렌트"), _what_if(r, args, kind="리스"),
                               _what_if(r, args, kind="리스", lease_7="여"))
        hint = ""
        if PLATE.fullmatch(r["key"]) and PLATE.fullmatch(r["key"]).group(2) not in RENTAL_LETTERS:
            hint = (f"차량번호의 한글이 {' · '.join(RENTAL_LETTERS)} 가 아니어서 자동차대여사업용 번호판은 아닌 것으로 보입니다"
                    "(리스일 수 있습니다). ")
        p.confirm.append(f"「{r['key']}」 은 거래처 이름이 캐피탈 · 리스 회사인데 적요에 리스도 렌트도 없어 {r['kind']}로 계산했습니다. {hint}"
                         f"렌트(자동차대여사업자)이면 감가상각비 상당액이 임차료의 {pct} 인 {rent['dep_eq']:,}원 · 한도초과 "
                         f"{rent['excess']:,}원이고, 리스(시설대여업자)이면 임차료에서 보험료 · 자동차세 · 수선유지비를 뺀 "
                         f"{lease_['dep_eq']:,}원 · 한도초과 {lease_['excess']:,}원입니다(수선유지비 7% 를 적용하면 "
                         f"{seven['dep_eq']:,}원 · {seven['excess']:,}원). 계약서로 확인해 「임차 구분」 을 고치세요")


def disposals(p: Paper, b: Books) -> list[dict]:
    """차량 처분 전표(차량 자산 대변과 처분손실 차변이 같은 전표). 장부가액 = 차량 대변 - 누계액 차변,
    양도가액 = 장부가액 - 처분손실 + 처분이익. 노란 칸: 처분손실 적용(업무용승용차 여부) · 매수인 특수관계인 · 시가.

    처분손실 한도는 차량마다 800만원(사업연도가 1년 미만이면 월할, 법인세법 제27조의2 제4항). 저가양도 차액은 매수인이
    특수관계인이고 시가와 양도가액 차이가 3억원 이상이거나 시가의 100분의 5 이상일 때 시가 - 양도가액(시행령 제88조 제1항
    제3호 · 제3항)이고, 그만큼은 처분손실 한도 계산에서 뺀다(세법상 양도가액은 시가)."""
    vouchers: dict = {}
    for ln in b.all_lines():
        vouchers.setdefault((ln.date, ln.no), []).append(ln)

    def acct(ln):
        return b.by_code.get(ln.account, {})

    def name(ln):
        return acct(ln).get("name") or ln.account_name

    base = rate(b.rates, "business_car", "disposal_limit")
    lim = rd(Fraction(base * b.months, 12)) if b.months < 12 else base
    low_amt = rate(b.rates, "business_car_disposal", "low_price_amount")
    low_ratio = frac(rate(b.rates, "business_car_disposal", "low_price_ratio"))
    out = []
    for (d, no), group in sorted(vouchers.items()):
        cars = [x for x in group if acct(x).get("class") == "자산" and "차량" in name(x) and "누계" not in name(x)
                and x.credit - x.debit > 0]
        losses = [x for x in group if acct(x).get("class") == "비용" and "처분손실" in name(x) and x.amount > 0]
        if not cars or not losses:
            continue
        accum = sum(x.debit - x.credit for x in group if acct(x).get("class") == "자산" and "누계" in name(x)
                    and x.debit - x.credit > 0)
        gain = sum(x.credit - x.debit for x in group if acct(x).get("class") == "수익" and "처분이익" in name(x))
        cost = sum(x.credit - x.debit for x in cars)
        book = cost - accum
        for ln in losses:
            loss = ln.amount
            price = max(0, book - sum(x.amount for x in losses) + gain)
            dkey = f"{ln.date}|{ln.no}|{ln.account}|{ln.amount}"
            apply = p.take(b, f"처분손실 적용/{dkey}", "부")
            related = norm_related(p.take(b, f"매수인 특수관계인/{dkey}", "확인 필요"))
            market = p.take(b, f"시가/{dkey}", 0, "int")
            gap = market - price
            low = gap if (related == "예" and gap > 0 and (gap >= low_amt or gap >= rd(market * low_ratio))) else 0
            ref = book - price
            ref = ref if ref > 0 and (ref >= low_amt or ref >= rd(book * low_ratio)) else 0
            out.append({"line": ln, "date": ln.date, "no": ln.no, "memo": ln.memo, "cost": cost, "accum": accum,
                        "book": book, "price": price, "loss": loss, "limit": lim, "apply": apply, "related": related,
                        "market": market, "low_price": low, "ref_low_price": ref,
                        "excess": max(0, loss - min(low, loss) - lim), "key": dkey})
    return out


def _disposal_message(d: dict) -> str:
    text = (f"{d['date']} 차량 처분(적요 「{d['memo']}」): 장부가액 {d['book']:,}원 · 양도가액 {d['price']:,}원 · 처분손실 "
            f"{d['loss']:,}원")
    if d["excess"] and d["apply"] == "여":
        text += (f". 업무용승용차로 보고 한도 {d['limit']:,}원 초과분 {d['excess']:,}원을 손금불산입(기타사외유출)했습니다. 다음 "
                 "사업연도부터 800만원씩 손금산입합니다")
    elif d["excess"]:
        text += (f". 업무용승용차(개별소비세 과세 승용차)이면 「적용」 을 여로 바꾸세요. 넣으면 한도 {d['limit']:,}원 초과분 "
                 f"{d['excess']:,}원을 손금불산입(기타사외유출)하고 다음 사업연도부터 800만원씩 손금산입합니다")
    else:
        text += f". 처분손실이 한도 {d['limit']:,}원 안이라 업무용승용차여도 한도초과 조정은 없습니다"
    if d["low_price"]:
        text += (f". 매수인이 특수관계인이고 시가 {d['market']:,}원보다 낮게 넘겨 저가양도 차액 {d['low_price']:,}원이 나옵니다. 이 조서는 "
                 "조정하지 않으니 15호 직접 조정 줄에 가산으로 넣고 귀속자에 따라 처분하세요(임원 · 직원 상여, 주주 배당, 법인 "
                 "기타사외유출). 처분손실 한도 계산에서는 이 금액을 뺐습니다")
    elif d["related"] != "아니오":
        text += (". 매수인이 특수관계인이고 시가보다 낮게 넘겼으면 시가 - 양도가액을 익금산입합니다(차액이 3억원 이상이거나 시가의 "
                 "5% 이상일 때). 「매수인 특수관계인」 · 「시가」 칸을 넣으면 계산합니다")
        if d["ref_low_price"]:
            text += f"(시가를 장부가액으로 보면 {d['ref_low_price']:,}원)"
    return text


def _car_json(r: dict) -> dict:
    """29호 차량별 줄(서식이 읽는다). 대상 「부」 줄(차량 미지정 · 승합 · 화물)도 target 으로 가려 넣는다."""
    return {"car": r["key"], "model": r["model"], "target": r["target"] == "여",
            "type": "취득" if r["kind"] == "자가" else r["kind"], "kind": r["kind"], "log": r["log"],
            "ratio": round(float(r["ratio"]), 6), "months": r["months"], "costs": dict(r["costs"]),
            "total": r["total"], "dep_eq": r["dep_eq"], "dep_biz": r["dep_biz"], "limit": r["limit"],
            "personal": r["personal"], "excess": r["excess"], "carry": r["carry"], "reversal": r["reversal"],
            "disallowed": r["personal"] + r["excess"], "basis": r.get("basis", ""),
            "lease": {"insurance": r.get("lease_ins", 0), "tax": r.get("lease_tax", 0), "repair": r.get("lease_repair", 0),
                      "seven": r.get("lease_7", "부"), "repair_applied": r.get("lease_repair_applied", 0)}}


def car_calc(row: dict, lim_dep: int, lim_log: int, rent_ratio: Fraction, fy_months: int,
             repair_ratio: Fraction = Fraction(7, 100)) -> dict:
    costs = row["costs"]
    total = sum(costs.values())
    rent = costs.get("임차료", 0)
    repair = 0
    if row["kind"] == "리스":
        # 법인세법 시행규칙 제27조의2 제6항 제1호: 임차료 - 그 임차료에 든 보험료 · 자동차세 · 수선유지비. 수선유지비를 따로
        # 가리기 어려우면 (임차료 - 보험료 - 자동차세) × 7% 로 할 수 있다(회계사가 「수선유지비 7% 적용」 을 「여」 로 둘 때만).
        net = rent - row.get("lease_ins", 0) - row.get("lease_tax", 0)
        repair = row.get("lease_repair", 0)
        if row.get("lease_7") == "여" and not repair:
            repair = rd(net * repair_ratio)
        dep_eq = net - repair
    elif row["kind"] == "렌트":
        dep_eq = rd(rent * rent_ratio)
    else:
        dep_eq = costs.get("감가상각비", 0)
    row["lease_repair_applied"] = repair
    # 한도 월할(법인세법 제27조의2 제3항 · 시행령 제50조의2 제7항 · 제10항): 사업연도가 1년 미만이면 한도 × 사업연도 월수 / 12,
    # 사업연도 중 일부 기간만 보유 · 임차했으면 한도 × 그 월수 / 사업연도 월수. 둘을 이어 한도 × 월수 / 12 로 계산한다
    # (월수는 사업연도 월수까지).
    months = max(0, min(row["months"], fy_months))
    if row["log"] == "여":
        ratio = Fraction(str(row["ratio_in"]))
    elif total <= 0:
        ratio = Fraction(1)
    else:
        ratio = min(Fraction(1), Fraction(lim_log * months, 12) / total)
    personal = rd(total * (1 - ratio))
    dep_biz = rd(dep_eq * ratio)
    limit = rd(Fraction(lim_dep * months, 12))
    excess = max(0, dep_biz - limit)
    reversal = min(row["carry"], max(0, limit - dep_biz))
    row.update({"total": total, "dep_eq": dep_eq, "ratio": ratio, "personal": personal, "dep_biz": dep_biz,
                "limit": limit, "excess": excess, "reversal": reversal})
    if row["target"] != "여":
        row.update({"personal": 0, "dep_biz": 0, "excess": 0, "reversal": 0})
    return row


CAR_COLS = ["차량", "차종", "대상", "임차 구분", "운행기록", "업무사용비율", "월수"] + COST_TYPES + [
    "자가 감가상각비", "관련비용", "리스료 중 보험료", "리스료 중 자동차세", "리스료 중 수선유지비", "수선유지비 7% 적용",
    "수선유지비 적용액", "감가상각비 상당액", "적용 비율", "업무외사용금액", "상당액 업무사용분", "한도", "한도초과", "전기 이월액",
    "손금추인", "나눈 근거"]
LEASE_KEYS = ("리스 보험료", "리스 자동차세", "리스 수선유지비", "수선유지비 7% 적용")


def write(bk: Book, p: Paper) -> None:
    s = head(bk, p)
    row = 5
    _, first, last = lines_dry(p, row + verify_rows(p))
    row = verify(bk, s, row, p, first, last)
    row, first, last = ledger(bk, s, row, p, "차량", "비용 구분", kind="text")
    R = bk.ref
    row = s.section(row, "3. 차량별 관련비용과 한도")
    X.note(s.ws, row, "노란 칸: 대상(여 · 부) · 임차 구분(리스 · 렌트 · 자가) · 운행기록(여 · 부) · 업무사용비율 · 월수 · "
                      "자가 감가상각비 · 리스료 중 보험료 · 자동차세 · 수선유지비 · 수선유지비 7% 적용(여 · 부) · 전기 이월액")
    row += 1
    X.note(s.ws, row, "리스 차량의 감가상각비 상당액 = 임차료 - 리스료 중 보험료 - 자동차세 - 수선유지비. 수선유지비 칸이 0 이고 "
                      "「수선유지비 7% 적용」 이 「여」 이면 (임차료 - 보험료 - 자동차세) × 7% 를 수선유지비로 봅니다"
                      "(법인세법 시행규칙 제27조의2 제6항 제1호)")
    row += 1
    X.note(s.ws, row, "차량 수와 차량별 금액은 위 원장 표의 차량 칸(노란 칸)으로 고칩니다. 줄의 차량 칸에 새 이름을 쓰면 다음 실행에서 "
                      "차량 줄이 하나 더 생깁니다. 한도는 800만원 × 월수 / 12 입니다(월수는 사업연도 월수까지)")
    row += 1
    X.header(s.ws, row, CAR_COLS)
    row += 1
    col = {name: i + 1 for i, name in enumerate(CAR_COLS)}
    c = {name: L(i) for name, i in col.items()}
    car_first = row
    fy_m = R["사업연도 월수"]
    d = p.defaults
    for car in p.extra["cars"]:
        r, k = row, car["key"]
        m_cap = f"MAX(0,MIN({c['월수']}{r},{fy_m}))"

        def inp(name, key, value, kind="text", **kw):
            s.inp(r, col[name], value, pid=p.id, key=f"{key}/{k}", default=d.get(f"{key}/{k}", value), kind=kind, **kw)

        s.put(r, col["차량"], k)
        s.put(r, col["차종"], car["model"])
        inp("대상", "대상", car["target"])
        inp("임차 구분", "임차 구분", car["kind"])
        inp("운행기록", "운행기록", car["log"])
        inp("업무사용비율", "업무사용비율", car["ratio_in"], "ratio", fmt="0.00%")
        inp("월수", "월수", car["months"], "int", fmt="0")
        inp("자가 감가상각비", "자가 감가상각비", car["own_dep"], "int", money=True)
        for t in COST_TYPES:
            f = f'=SUMIFS($G${first}:$G${last},$I${first}:$I${last},$A{r},$J${first}:$J${last},"{t}")'
            if t == "감가상각비":
                f += f"+{c['자가 감가상각비']}{r}"
            s.put(r, col[t], f, money=True)
        s.put(r, col["관련비용"], f"=SUM({c[COST_TYPES[0]]}{r}:{c[COST_TYPES[-1]]}{r})", money=True)
        inp("리스료 중 보험료", "리스 보험료", car["lease_ins"], "int", money=True)
        inp("리스료 중 자동차세", "리스 자동차세", car["lease_tax"], "int", money=True)
        inp("리스료 중 수선유지비", "리스 수선유지비", car["lease_repair"], "int", money=True)
        inp("수선유지비 7% 적용", "수선유지비 7% 적용", car["lease_7"])
        net = f'({c["임차료"]}{r}-{c["리스료 중 보험료"]}{r}-{c["리스료 중 자동차세"]}{r})'
        s.put(r, col["수선유지비 적용액"],
              f'=IF({c["임차 구분"]}{r}="리스",IF(AND({c["수선유지비 7% 적용"]}{r}="여",{c["리스료 중 수선유지비"]}{r}=0),'
              f'ROUNDDOWN({net}*{R["리스 수선유지비 비율"]},0),{c["리스료 중 수선유지비"]}{r}),0)', money=True)
        s.put(r, col["감가상각비 상당액"],
              f'=IF({c["임차 구분"]}{r}="리스",{net}-{c["수선유지비 적용액"]}{r},'
              f'IF({c["임차 구분"]}{r}="렌트",ROUNDDOWN({c["임차료"]}{r}*{R["렌트 감가상각비 상당액 비율"]},0),{c["감가상각비"]}{r}))', money=True)
        s.put(r, col["적용 비율"],
              f'=IF({c["운행기록"]}{r}="여",{c["업무사용비율"]}{r},IF({c["관련비용"]}{r}<=0,1,'
              f'MIN(1,{R["운행기록 미작성 인정 한도"]}*{m_cap}/12/MAX(1,{c["관련비용"]}{r}))))', fmt="0.00%")
        on = f'{c["대상"]}{r}="여"'
        s.put(r, col["업무외사용금액"], f"=IF({on},ROUNDDOWN({c['관련비용']}{r}*(1-{c['적용 비율']}{r}),0),0)", money=True)
        s.put(r, col["상당액 업무사용분"], f"=IF({on},ROUNDDOWN({c['감가상각비 상당액']}{r}*{c['적용 비율']}{r},0),0)", money=True)
        s.put(r, col["한도"], f"=ROUNDDOWN({R['업무용승용차 감가상각비 한도']}*{m_cap}/12,0)", money=True)
        s.put(r, col["한도초과"], f"=IF({on},MAX(0,{c['상당액 업무사용분']}{r}-{c['한도']}{r}),0)", money=True)
        inp("전기 이월액", "전기 이월액", car["carry"], "int", money=True)
        s.put(r, col["손금추인"], f"=IF({on},MIN({c['전기 이월액']}{r},MAX(0,{c['한도']}{r}-{c['상당액 업무사용분']}{r})),0)", money=True)
        s.put(r, col["나눈 근거"], car.get("basis", ""))
        row += 1
    if not p.extra["cars"]:
        s.put(row, 1, "차량 없음")
        row += 1
    car_last = row - 1

    def rng(name):
        return f"${c[name]}${car_first}:${c[name]}${car_last}"

    row += 1
    put_rows = [
        ("관련비용", "대상 차량 관련비용 합계", f'=SUMIF({rng("대상")},"여",{rng("관련비용")})'),
        ("감가상각비상당액", "대상 차량 감가상각비(상당액) 합계", f'=SUMIF({rng("대상")},"여",{rng("감가상각비 상당액")})'),
        ("업무외사용금액", "업무외사용금액(가산 · 상여)", f"=SUM({rng('업무외사용금액')})"),
        ("한도초과(임차)", "임차 차량 감가상각비 상당액 한도초과(가산 · 기타사외유출)", f'=SUMIFS({rng("한도초과")},{rng("임차 구분")},"<>자가")'),
        ("한도초과(자가)", "자가 차량 감가상각비 한도초과(가산 · 유보)", f'=SUMIF({rng("임차 구분")},"자가",{rng("한도초과")})'),
        ("이월액손금추인", "전기 이월액 손금추인(차감 · 기타)", f"=SUM({rng('손금추인')})"),
        ("차량수", "대상 차량 수", f'=COUNTIF({rng("대상")},"여")'),
        ("미지정비용", "차량 미지정 비용(계산에서 뺌)", f'=SUMIF({rng("차량")},"{NOT_ASSIGNED}",{rng("관련비용")})'),
    ]
    for key, label, f in put_rows:
        row = calc_row(bk, s, row, p, key, label, f, fmt="0" if key == "차량수" else None)
    row += 1
    row = s.section(row, "3-1. 업무용승용차 처분손실 · 저가양도")
    X.note(s.ws, row, "노란 칸: 적용(업무용승용차 여 · 부) · 매수인 특수관계인(예 · 아니오 · 확인 필요) · 시가(모르면 0). "
                      "저가양도 차액은 이 조서가 조정하지 않습니다(15호 직접 조정 줄에 넣음)")
    row += 1
    X.header(s.ws, row, ["일자", "전표", "장부가액", "양도가액", "매수인 특수관계인", "적요", "처분손실", "한도", "적용", "시가",
                         "한도초과", "저가양도 차액"])
    row += 1
    d_first = row
    for dsp in p.extra["disposal"]:
        ln = dsp["line"]
        s.put(row, 1, ln.date)
        s.put(row, 2, ln.no)
        s.put(row, 3, dsp["book"], money=True)
        s.put(row, 4, dsp["price"], money=True)
        key = f"매수인 특수관계인/{dsp['key']}"
        s.inp(row, 5, dsp["related"], pid=p.id, key=key, default=d.get(key, dsp["related"]))
        s.put(row, 6, ln.memo)
        s.put(row, 7, dsp["loss"], money=True)
        s.put(row, 8, f"=IF({R['사업연도 월수']}<12,ROUNDDOWN({R['처분손실 한도']}*{R['사업연도 월수']}/12,0),{R['처분손실 한도']})",
              money=True)
        key = f"처분손실 적용/{dsp['key']}"
        s.inp(row, 9, dsp["apply"], pid=p.id, key=key, default=d.get(key, dsp["apply"]))
        key = f"시가/{dsp['key']}"
        s.inp(row, 10, dsp["market"], pid=p.id, key=key, default=d.get(key, dsp["market"]), kind="int", money=True)
        s.put(row, 12, f'=IF(AND(E{row}="예",J{row}>D{row},OR(J{row}-D{row}>={R["저가양도 기준금액"]},'
                       f'J{row}-D{row}>=ROUNDDOWN(J{row}*{R["저가양도 기준비율"]},0))),J{row}-D{row},0)', money=True)
        s.put(row, 11, f"=MAX(0,G{row}-MIN(G{row},L{row})-H{row})", money=True)
        row += 1
    if not p.extra["disposal"]:
        s.put(row, 6, "차량 처분손실 없음")
        row += 1
    d_last = row - 1
    row += 1
    row = calc_row(bk, s, row, p, "처분손실한도초과후보", "처분손실 한도초과(후보)", f"=SUM(K{d_first}:K{d_last})")
    row = calc_row(bk, s, row, p, "처분손실한도초과", "처분손실 한도초과(적용 「여」 만, 가산 · 기타사외유출)",
                   f'=SUMIF(I{d_first}:I{d_last},"여",K{d_first}:K{d_last})')
    row = calc_row(bk, s, row, p, "저가양도차액", "저가양도 차액(참고, 15호 직접 조정 줄에 넣음)", f"=SUM(L{d_first}:L{d_last})")
    row += 1
    row = adj_table(bk, s, row, p)
    row = forms_table(bk, s, row, p, [("29", "⑮ 업무용승용차 관련비용 합계", "관련비용"),
                                      ("29", "업무외사용금액", "업무외사용금액"),
                                      ("29", "감가상각비(상당액) 한도초과금액", "한도초과(임차)")])
    notes(s, row, p)

