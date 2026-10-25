"""AR(분석적 검토) 엔진. 장부.json · 전표.csv · 전기.json → AR.json(CONTRACT.md 7절).

엔진은 숫자를 장부 · 전기 신고서에서만 가져온다. 판단이 필요한 곳은 확실도 「가능」 · 「자료 필요」 와 회사 질문으로 남긴다.
목업 규칙이라 단순하다: 계정 유무(계정명 · class), 증감(신규 · 소멸 · 크게 변동), 전기 15호 · 50호(을) 줄, 전기 서식 목록,
적요 낱말. 얕게 둔 곳은 NOTES.md.
"""
from __future__ import annotations

import csv
import json
import re
from functools import lru_cache
from pathlib import Path

import yaml

from ctax.ar.guide import form_name, load_guide
from ctax.ar.topics import Topic, build_topics, clean, code3, describe, won

KINDS = ("신고 점검", "전기 연속", "조정 후보", "공제감면", "서식 필요")
CERTAINTIES = ("확실", "가능", "자료 필요")
STATUSES = ("이슈", "해당 없음", "자료 필요")
FORM_STATUSES = ("해당", "해당 없음", "확인")
GRADES = ("★★★", "★★☆", "★☆☆", "☆")

# 기본 서식(설계 9-22 회의 · 대표 지시). 총괄표 맨 앞에 이 순서로 둔다.
BASIC_FORMS = ["1", "3", "std_bs", "std_is", "std_re", "15", "15부표1", "15부표2", "16", "17", "47갑", "47을",
               "50갑", "50을", "50병", "51", "54", "지방43", "지방43의2", "세금공과금명세서", "23갑", "23을"]

# 목업에서 ctax 가 채우는 서식(CONTRACT.md 8 · 9절). ctax/forms/defs 가 있으면 그 목록을 쓴다(engine_forms).
ENGINE_FORMS_FALLBACK = {"1", "3", "std_bs", "std_is", "15", "15부표1", "15부표2", "50갑", "50을", "50병",
                         "23갑", "23을", "세금공과금명세서", "29", "32", "33", "21"}

# 문턱
BIG_CHANGE_RATE, BIG_CHANGE_AMOUNT = 0.30, 10_000_000      # corptax-impl ar.yaml 과 같다
SME_ASSET_LIMIT = 500_000_000_000                            # 조특령 2조 1항 단서(자산 5천억)
EXPENSE_EVIDENCE_REVENUE = 3_000_000_000                     # 법인령 158조 6항(직전 수입금액 30억)
# 작은 조정 후보 묶음(folded). 「조정 후보 · 가능」 이고 전기 처리가 없고 당기 · 전기 · 증감이 모두 이 금액 미만이면 접는다.
# 세율 9% 로 세액 27만 원 남짓이다. 회계사와 맞춰 볼 값이다(NOTES.md).
FOLD_LIMIT = 3_000_000
# 전기 신고서가 없는 신고 건(전기.json no_prior)의 가이드 1절 사실 글
NO_PRIOR_FACT = "전기 신고서가 없어 견주지 못했습니다(신설 첫 해 또는 첫 수임)"
# 전기 신고서가 없으면 회사 종류(중소기업 여부 · 업종)는 신고건.json 「회사정보」 에서 온 값이다(prior/cli.py no_prior)
INFO_SME = "신고건.json 회사정보"
# 첫 사업연도(전기 신고서가 없고 재무제표 전기 금액이 모두 0)의 이슈 제목 머리와, 근거 · 가이드 사실 글에서 빼는 전기 대비 글
FIRST_YEAR = "첫 사업연도라 전기와 견줄 수 없습니다. "
RX_FIRST_YEAR = re.compile(r"\(전기 0원\)| · 증감 △?[\d,]+원| · 신규$")
# 결손금 이력 이슈의 다음 할 일(회계사). 전기 신고서에 결손금 줄이 빠진 회사(평가세트의 한 회사)는 조서 결손금 시트 수동 줄로 바로잡는다
LOSS_TODO = ("받은 신고서로 결손금이 난 사업연도 · 발생액 · 기공제액을 확인해 조서 「결손 결손금」 시트 노란 줄(결손금 수동)에 넣고 "
             "ctax wp 를 다시 돌립니다")

# 적요 낱말(목업). 찾은 금액은 사실로만 쓰고 조정 금액은 조서가 정한다.
RX_PENALTY = re.compile(r"가산세|과태료|벌과금|벌금|범칙금|체납|연체료|연체이자|납부지연|불성실|미납|통행료|교통위반|주정차|경찰|위반"
                        r"|초과배출부과금|초과부과금")       # 제재 공과금(법인세법 제21조 제5호, 조서 taxes_dues SANCTION 과 같은 낱말)
# 가산세 낱말보다 먼저 빼는 줄(4회차): 수수료 · 용역 대가(「법인세 경정청구 수수료」 는 세금이 아니라 대가)와 단수 차이
RX_NOT_PENALTY = re.compile(r"수수료|용역|대행|자문|컨설팅|단수|절사")
RX_NONDEDUCT_VAT = re.compile(r"불공제")
RX_TAX_IN_LOSS = re.compile(r"국세|부가세|부가가치세|지방세|원천세|법인세|소득세|세무서")
RX_LOCAL_GOV = re.compile(r"^[가-힣]{1,4}(시|군|구|시청|군청|구청)$")
RX_CAR = re.compile(r"렌트|렌터카|렌탈카|리스료|대여료|자동차보험|자동차세|\d{2,3}\s?[가-힣]\s?\d{4}")
RX_PLATE = re.compile(r"(\d{2,3})\s?([가-힣])\s?(\d{4})")
RX_TRUCK = re.compile(r"포터|봉고|화물|트럭|덤프|굴삭기|굴착기|지게차|크레인|레미콘|건설기계|중장비")
RX_ENT_EVENT = re.compile(r"경조사|축의|부의|조의|화환|근조")
RX_ENT_CARD = re.compile(r"신용카드|법인카드|카드")
RX_FORGIVE = re.compile(r"면제|포기|탕감")
# 현금 · 예금 계정(이름). 대여금 「면제」 적요 줄도 상대가 예금 입금이면 회수다(5회차)
RX_CASH_NAME = re.compile(r"현금|예금|적금")
# 배당금수익 줄의 펀드 · 금융상품 분배금 표기. 투자신탁이익은 원천징수 대상이고(법인세법 제73조 제1항 제2호) 내국법인 배당이 아니다
RX_FUND = re.compile(r"펀드|MMF|신탁|분배금|재투자|만기|환매|해지|ETF|수익증권|리츠|REITs|채권형|주식형|혼합형")
RX_FIN_PRODUCT = re.compile(r"금융상품|신탁|수익증권|펀드")
# 이자수익 적요의 세금 표기(「이자세금:11,000원」 꼴). 선납세금 없이 받은 돈만 이자로 적은 신호
RX_INT_TAX = re.compile(r"세금|원천|법인세|소득세|세액")
RX_WON = re.compile(r"(\d{1,3}(?:,\d{3})+|\d+)\s*원")
# 퇴직연금운용자산 차변 · 퇴직급여충당부채 대변 전표의 운용수익 표기
RX_PLAN_INCOME = re.compile(r"운용|수익|이자")
# 대여금 · 가지급금 적요의 대표자 · 임원 표기
RX_INSIDER = re.compile(r"대표|사장|회장|임원|이사|주주")
# 가지급금 · 대여금 계정이 아닌 자산 계정(전도금 · 선급금 등)의 가지급 · 가불 적요(10-19). 인정이자 대상인지 회계사가 본다
RX_ADVANCE = re.compile(r"가지급|가불")
# 10-20 AR 5차 규칙의 문턱 · 낱말(CONTRACT.md 13절 10-20 줄)
# 수선비 한 줄이 이 금액 이상이면 자본적 지출 · 즉시상각의제를 본다(법인세법 시행령 제31조 제3항 제1호, 개별자산별 600만원 미만은 손금)
REPAIR_LIMIT = 6_000_000
RX_CAPEX_WORD = re.compile(r"공사|교체|설치|개조|증설|신설|이설|개량|확장")
RX_MODEL = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]{1,5}-?\d{3,}[A-Za-z0-9\-]*")
# 지급수수료 적요 · 거래처의 소송 · 변호사 표기. 합계가 이 금액 이상이면 업무관련성을 본다
RX_LEGAL = re.compile(r"변호사|법무법인|법률사무소|소송|형사|고소|고발|공탁|합의금")
LEGAL_LIMIT = 10_000_000
# 거래처 이름은 법률 사무소 이름만 본다(거래처에 「…전자소송」 이 붙고 적요는 다른 거래인 장부가 있다, 10-20 평가)
RX_LEGAL_FIRM = re.compile(r"변호사|법무법인|법률사무소")
# 영업외 손익 계정 적요의 전기오류 · 전기분 수정 표기(전기오류수정 37xx · 전기오류수정손익 계정은 rule_misc_accounts 가 본다)
RX_PRIOR_FIX = re.compile(r"전기\s*오류|오류\s*수정|전기분\s*(수정|정정|조정|오류|과소|과대)|과년도\s*(수정|오류|손익)")
PRIOR_FIX_MIN = 100_000
# 임원급여 월별 금액이 평월(중앙값)의 이 배수를 넘는 달
OFFICER_RATIO = 2
# 건설업 판정(전기 51호 업태 · 업종코드)과 공사매출 계정 이름
RX_CONSTRUCTION = re.compile(r"건설")
RX_CONSTRUCTION_REV = re.compile(r"공사|도급")
# 전기 15호 유보 가산 · 차감 짝을 보지 않는 과목(전기 유보 추인과 당기분을 조서가 따로 계산한다)
PAIR_SKIP = {"accrued_expense", "accrued_income", "prepaid", "fx", "bad_debt", "securities", "depreciation",
             "retirement_allowance", "retirement_plan", "car"}

# 업무용승용차 처분손실 한도(법인세법 제27조의2 제4항, 사업연도 1년 미만이면 월할)
CAR_DISPOSAL_LIMIT = 8_000_000
# 전기오류수정 전표 글 → 전기 50호(을) 유보 과목 열쇠(subject_key). 같은 자산 · 부채를 고친 전표인지 잇는다
LINK_WORDS = {"receivable": r"채권|외상|매출", "inventory": r"재고|상품|제품|원재료", "accrued_expense": r"미지급|연차",
              "accrued_income": r"미수", "prepaid": r"선급", "depreciation": r"감가|상각누계|유형자산",
              "securities": r"증권|주식|투자자산", "retirement_allowance": r"퇴직"}

# 전기 15호 · 50호(을) 과목(조정내용 포함) → 이슈 열쇠. 위에서부터 첫 일치(corptax-impl ar.yaml subject_natures 를 줄였다).
SUBJECT_KEYS = [
    ("퇴직급여충당", "retirement_allowance"), ("퇴직연금", "retirement_plan"), ("퇴직급여", "retirement_allowance"), ("대손충당금", "bad_debt"), ("대손금", "bad_debt"),
    ("일시상각충당", "grant"), ("보조금", "grant"), ("환급", "tax_refund"),
    ("미경과", "prepaid"), ("선급비용", "prepaid"), ("연차", "accrued_expense"), ("미지급비용", "accrued_expense"),
    ("미수이자", "accrued_income"), ("미수수익", "accrued_income"), ("업무용승용차", "car"), ("업무용차량", "car"),
    ("차량", "car"), ("감가상각", "depreciation"), ("상각부인", "depreciation"), ("무형자산상각", "depreciation"),
    ("기업업무추진비", "entertainment"),
    ("접대비", "entertainment"), ("기부금", "donation"), ("법인지방소득세", "corp_tax"), ("법인세", "corp_tax"),
    ("가산세", "penalty"), ("벌과금", "penalty"), ("과태료", "penalty"), ("잡손실", "penalty"), ("세금과공과", "penalty"),
    ("인정이자", "loan"), ("가지급금", "loan"), ("지급이자", "loan_interest"), ("외화환산", "fx"), ("재고자산", "inventory"),
    ("수입배당금", "dividend"), ("배당", "dividend"), ("지분법", "securities"), ("증권", "securities"), ("전기오류", "prior_error"),
    ("투자자산", "securities"), ("금융상품평가", "securities"), ("보험료", "prepaid"), ("외상매출금", "receivable"),
    ("매출채권", "receivable"), ("급여", "accrued_expense"),
]
# 이슈 열쇠 → 당기에 계정이 있는지 볼 topic
KEY_TOPICS = {
    "corp_tax": ["corp_tax"], "entertainment": ["entertainment"], "car": ["vehicles", "vehicle_cost"],
    "penalty": ["taxes", "misc_loss"], "retirement_allowance": ["retirement_allowance"], "retirement_plan": ["retirement_plan"],
    "donation": ["donation"], "bad_debt": ["allowance", "bad_debt"], "accrued_income": ["accrued_income"],
    "accrued_expense": ["accrued_expense"], "prepaid": ["prepaid"], "depreciation": ["depreciation", "amortization"],
    "securities": ["securities", "securities_pl"], "dividend": ["dividend"], "fx": ["fx"], "loan": ["loan"],
    "loan_interest": ["interest_expense"], "prior_error": ["prior_error"], "grant": ["grant"], "inventory": ["inventory"],
    "tax_refund": ["misc_income"], "receivable": ["receivable"],
}
# 이슈 규칙 id(전기 연속 줄은 과목으로 정한 id) → 조서 id. 조서 id 가 실제로 있는지는 조서 등록부(ctax.wp.papers ORDER · AGGREGATES)로
# 가린다(paper_ids). 등록부에 없는 id 는 이슈에 붙이지 않는다. 3회차(CONTRACT.md 15절)에 새 조서 열 개를 이었다.
KEY_PAPERS = {"corp_tax": ["corporate_tax"], "entertainment": ["entertainment"], "car": ["business_car"],
              "penalty": ["taxes_dues"], "retirement_allowance": ["retirement"], "retirement_plan": ["retirement"],
              "donation": ["donation"], "tax_refund": ["corporate_tax"], "depreciation": ["depreciation"],
              "accrued_expense": ["accrued_expense"], "accrued_income": ["accrued_income"], "prepaid": ["prepaid"],
              "loan": ["loan_interest"], "loan_interest": ["interest_denial"], "bad_debt": ["bad_debt"], "securities": ["securities"], "dividend": ["dividend"],
              "fx": ["fx"], "prior_error": ["prior_error"],
              "sme_reduction": ["credits"], "employment_credit": ["credits"], "investment_credit": ["credits"],
              "rnd_credit": ["credits"], "retirement_income": ["retirement"], "interest_net": ["summary_15", "tax_3"]}
# 규칙 id 머리 → 조서 id(전기 공제감면 줄 「credit:<이름>」 처럼 이름이 붙는 id)
PREFIX_PAPERS = {"credit:": ["credits"]}


@lru_cache(maxsize=1)
def paper_ids() -> frozenset[str] | None:
    """조서 등록부의 조서 id 와 집계 id. 등록부를 읽지 못하면 None(그때는 거르지 않는다)."""
    try:
        from ctax.wp import papers as registry
    except Exception:                                    # noqa: BLE001 (조서 패키지가 깨져도 AR 은 돈다)
        return None
    return frozenset([pid for pid, _no in registry.ORDER] + list(registry.AGGREGATES))


def papers_for(key: str, given=()) -> list[str]:
    """이슈 규칙 id 의 조서 id 목록. 규칙이 준 id(given)에 KEY_PAPERS · PREFIX_PAPERS 대응을 더하고 등록부에 있는 것만 남긴다."""
    found = list(given or []) + KEY_PAPERS.get(key, [])
    for head, ids in PREFIX_PAPERS.items():
        if key.startswith(head):
            found += ids
    known = paper_ids()
    return [p for p in dict.fromkeys(found) if known is None or p in known]


def state(t: Topic) -> str:
    """계정 상태 한 줄. 기말 · 전기 잔액이 0 이고 기중 거래만 있으면 차변 · 대변 합을 보인다."""
    if not t.has_current and not t.has_prior and t.touched:
        return f"기중 거래만 있음({t.lines}줄, 차변 {won(t.debit)}원 · 대변 {won(t.credit)}원, 기말 잔액 0원)"
    return f"계정 상태 {t.status()}"


def subject_key(*texts: str) -> str | None:
    t = re.sub(r"\s+", "", " ".join(str(x or "") for x in texts))
    for word, key in SUBJECT_KEYS:
        if word in t:
            return key
    return None


@lru_cache(maxsize=1)
def load_laws() -> dict[str, list[dict]]:
    data = yaml.safe_load((Path(__file__).resolve().parent / "laws.yaml").read_text(encoding="utf-8"))
    return {str(k): list(v or []) for k, v in (data.get("laws") or {}).items()}


def law_for(rule: str, title: str = "") -> list[dict]:
    """이슈 규칙 열쇠 → 근거 조문 [{ref, grade, url?}] (laws.yaml). 전기 연속 · 공제감면 줄은 과목 · 공제 이름으로 고른다."""
    laws = load_laws()
    base = rule
    if rule.startswith("check:"):
        base = "ledger_check"
    elif rule.startswith("prior_pair:"):
        base = "prior_pair"
    elif rule.startswith("prior:"):
        base = rule.split(":")[1]
    elif rule == "prior_donation_overlap":
        base = "donation"
    elif rule == "loan_moved":
        base = "loan"
    elif rule.startswith(("advance:", "car_disposal:")):
        base = {"advance": "loan", "car_disposal": "car_disposal"}[rule.split(":")[0]]
    elif rule.startswith("reserve:"):
        base = subject_key(rule.split(":", 1)[1]) or ""
    elif rule.startswith("credit:"):
        name = rule.split(":", 1)[1]
        picks = ["credit_carryforward"] if "이월세액공제" in title else []
        for rx, k in ((r"창업", "credit_startup"), (r"중소기업.*감면|특별세액감면", "sme_reduction"),
                      (r"연구|인력개발", "rnd_credit"), (r"사회보험", "credit_social_insurance"),
                      (r"고용", "credit_employment_followup"), (r"투자", "investment_credit")):
            if re.search(rx, name):
                picks.append(k)
                break
        return [dict(x) for k in picks for x in laws.get(k, [])] or [dict(x) for x in laws.get("no_rule", [])]
    # 근거 조문이 빈 이슈를 두지 않는다(5회차). 규칙에 조문이 없으면 그 사실을 ☆ 줄로 적는다
    return [dict(x) for x in laws.get(base, [])] or [dict(x) for x in laws.get("no_rule", [])]


def engine_forms() -> set[str]:
    """ctax forms 가 채우는 서식 code. 서식 에이전트의 `ctax/forms/engine_forms.yaml`(2회차)이 정본이고, 없으면 defs 와 목업 목록."""
    listed = Path(__file__).resolve().parents[1] / "forms" / "engine_forms.yaml"
    if listed.exists():
        try:
            data = yaml.safe_load(listed.read_text(encoding="utf-8")) or {}
            codes = {str(f.get("code")) for f in data.get("forms") or [] if isinstance(f, dict) and f.get("code")}
            try:  # 3회차 조서별 서식 플러그인(CONTRACT.md 15절)
                from ctax.forms import plugins
                codes |= {f["code"] for f in plugins.engine_forms()}
            except ImportError:
                pass
            if codes:
                return codes
        except (yaml.YAMLError, OSError):
            pass
    defs = Path(__file__).resolve().parents[1] / "forms" / "defs"
    found = {p.stem for p in defs.glob("*.json")} if defs.is_dir() else set()
    return found | ENGINE_FORMS_FALLBACK if found else set(ENGINE_FORMS_FALLBACK)


def read_journal(path: str | Path) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            r["debit"] = _int(r.get("debit"))
            r["credit"] = _int(r.get("credit"))
            r["closing"] = str(r.get("closing") or "").strip() in ("1", "True", "true")
            r["account"] = str(r.get("account") or "").strip()
            rows.append(r)
    return rows


def _int(v) -> int:
    if v is None or v == "":
        return 0
    try:
        return int(round(float(str(v).replace(",", ""))))
    except ValueError:
        return 0


class Hits:
    def __init__(self):
        self.n, self.amount, self.words = 0, 0, []

    def add(self, row: dict, words: list[str]) -> None:
        self.n += 1
        self.amount += row["debit"] - row["credit"]
        for w in words:
            if w not in self.words:
                self.words.append(w)

    def __bool__(self) -> bool:
        return self.n > 0

    def text(self, what: str) -> str:
        return f"적요에 {what} 표기 {self.n}줄 {won(self.amount)}원({' · '.join(self.words[:6])})"


class Builder:
    def __init__(self, ledger: dict, journal: list[dict], prior: dict | None, info: dict | None = None):
        self.L = ledger or {}
        self.J = [r for r in (journal or []) if not r.get("closing")]
        self.P = prior or {}
        self.has_prior = prior is not None
        self.info = info or {}
        self.accounts = list(self.L.get("accounts") or []) + self._fs_only()
        # 첫 사업연도: 전기 신고서가 없고(전기.json no_prior) 재무제표 전기 금액이 모두 0. 첫 수임(전기 금액이 있음)은 아니다
        self.first_year = bool(self.P.get("no_prior")) and not any(_int(a.get("prior_amount")) for a in self.accounts)
        self.by_code = {str(a.get("code")): a for a in self.accounts if a.get("code")}
        self.T = build_topics(self.accounts)
        self.tot = self.L.get("totals") or {}
        self.issues: dict[str, dict] = {}
        self.judg: dict[str, dict] = {}
        # 전기
        self.prior_forms = {str(f.get("code")): f for f in (self.P.get("forms") or []) if f.get("known", True) is not False}
        # 전기 총괄표에 첨부 O 가 찍혔는데 받은 PDF 에 쪽이 없는 서식(10-21). 낸 서식으로 본다(「내지 않았습니다」 로 단정하지 않는다)
        self.prior_listed = {str(x.get("code")) for x in (self.P.get("listed") or []) if x.get("attached")} - set(self.prior_forms)
        self.prior_adj = self._dedupe(self.P.get("adjustments") or [])
        self.prior_res = [r for r in (self.P.get("reserves") or []) if _int(r.get("closing")) != 0]
        self.prior_losses = list(self.P.get("losses") or [])
        self.prior_credits = list(self.P.get("credits") or [])
        self.company = self.P.get("company") or {}
        self.cells3 = (self.P.get("cells") or {}).get("3") or {}
        self.prior_fy = str(self.P.get("fy") or "")
        self.adj_fate: list[tuple[dict, str, str | None]] = []   # (전기 조정, 운명, 이슈 열쇠)
        self.fund_note: str | None = None        # 배당금수익이 모두 펀드 · 신탁 분배금으로 보일 때 원천납부 이슈 · 가이드에 붙일 글
        self.fix_texts: list[str] = []           # 전기오류수정 전표 글(적요 · 상대 계정). 전기 유보 과목과 잇는 데 쓴다
        self.pair_adj: dict[int, str] = {}       # 전기 15호 짝 조정 줄(id) → 전기 연속 이슈 열쇠(rule_prior_pairs)
        self.pair_res: dict[str, str] = {}       # 전기 50호(을) 과목(빈칸 없앰) → 짝 조정 이슈 열쇠
        self.prior_vat = 0                       # 전기 세금공과금명세서 · 15호에서 손금불산입한 불공제 매입세액

    # ------------------------------------------------------------ 도우미

    IS_SECTION_CLASS = {"매출액": "수익", "매출원가": "비용", "판매비와관리비": "비용", "영업외수익": "수익", "영업외비용": "비용",
                        "법인세등": "비용"}

    def _fs_only(self) -> list[dict]:
        """당기 0 이고 분개장 코드가 없는 손익계산서 줄(전기에만 있는 줄)을 계정처럼 더한다. 코드는 빈 글, fs_only 표시."""
        out = []
        for ln in ((self.L.get("fs") or {}).get("is") or []):
            if ln.get("kind") != "account" or ln.get("code") or not _int(ln.get("prior")) or _int(ln.get("cur")):
                continue
            out.append({"code": "", "name": ln.get("label"), "class": self.IS_SECTION_CLASS.get(ln.get("section"), "비용"),
                        "section": ln.get("section"), "opening": 0, "debit": 0, "credit": 0, "closing": 0, "amount": 0,
                        "prior_amount": _int(ln.get("prior")), "fs_label": ln.get("label"), "lines": 0, "fs_only": True})
        return out

    @property
    def prior_totals(self) -> dict:
        return self.tot.get("prior") or {}

    @staticmethod
    def _dedupe(adjs: list[dict]) -> list[dict]:
        seen, out = set(), []
        for a in adjs:
            k = (a.get("side"), a.get("subject"), _int(a.get("amount")), a.get("disposition"))
            if k in seen:
                continue
            seen.add(k)
            out.append(a)
        return out

    def agg(self, *tids: str) -> Topic:
        seen: dict[str, dict] = {}
        for t in tids:
            for a in self.T[t].accounts:
                seen.setdefault(str(a.get("code")), a)
        return Topic("+".join(tids), " · ".join(self.T[t].label for t in tids), list(seen.values()))

    def prior_filed(self, code: str, nonblank: bool = False) -> bool:
        """전기에 그 서식을 냈는가. PDF 에 쪽이 없어도 총괄표에 첨부 O 면 낸 것으로 본다(금액은 모른다)."""
        f = self.prior_forms.get(code)
        if f is None:
            return code in self.prior_listed
        return not nonblank or not f.get("blank")

    def listed_only(self, *codes: str) -> list[str]:
        """총괄표에만 있고 받은 PDF 에 쪽이 없는 서식."""
        return [c for c in codes if c in self.prior_listed]

    def scan(self, codes, rx: re.Pattern, extra: re.Pattern | None = None, fields=("memo",),
             exclude: re.Pattern | None = None, min_amount: int = 0) -> Hits:
        """min_amount: 이 금액(원) 미만 줄은 뺀다(1원 · 몇 원짜리 단수 차이 줄)."""
        codes = set(map(str, codes))
        h = Hits()
        for r in self.J:
            if r["account"] not in codes:
                continue
            if min_amount and abs(_int(r.get("debit")) - _int(r.get("credit"))) < min_amount:
                continue
            text = " ".join(str(r.get(f) or "") for f in fields).strip()
            if exclude is not None and exclude.search(text):
                continue
            words = ["차량번호" if RX_PLATE.fullmatch(m.group(0)) else m.group(0) for m in rx.finditer(text)]
            if extra is not None:
                memo = str(r.get("memo") or "").strip()
                if extra.search(memo):
                    words.append("지자체 납부")
            if words:
                h.add(r, words)
        return h

    def codes_by_class(self, *classes: str) -> list[str]:
        return [str(a.get("code")) for a in self.accounts if a.get("class") in classes]

    def rental_test(self) -> dict:
        """법인세법 시행령 제42조 제2항 제2호의 수입 요건. 임대 · 이자 · 배당 수입 합계를 매출액으로 나눈다.

        매출액에 들어 있지 않은 임대 · 이자 · 배당 수입(영업외수익 계정)은 매출액에 더해 계산한다(같은 호 괄호).
        간주임대료 익금가산액(조세특례제한법 제138조 제1항)은 장부에 없어 넣지 않는다. 이자수익 · 배당금수익 계정을
        소득세법 제16조 · 제17조의 이자소득 · 배당소득으로 본다(계정 이름 기준이라 회계사가 확인한다).
        """
        rev = self.T["revenue"]
        in_rev = {id(a) for a in rev.accounts}
        parts, total, added = [], 0, 0
        for tid, label in (("rent_income", "임대료 수입"), ("interest_income", "이자수익"), ("dividend", "배당금수익")):
            t = self.T[tid]
            amount = t.current
            outside = sum(_int(a.get("amount")) for a in t.accounts if id(a) not in in_rev)
            parts.append({"topic": tid, "label": label, "amount": amount, "outside": outside})
            total += amount
            added += outside
        base = rev.current + added
        return {"parts": parts, "total": total, "revenue": rev.current, "added": added, "base": base,
                "share": (total / base) if base > 0 and total > 0 else 0.0}

    def rent_share(self) -> float:
        """임대 · 이자 · 배당 수입 합계 ÷ 매출액(시행령 제42조 제2항 제2호)."""
        return self.rental_test()["share"]

    def rental_facts(self) -> list[str]:
        r = self.rental_test()
        shown = [f"{x['label']} {won(x['amount'])}원" for x in r["parts"] if x["amount"]]
        if not shown:
            return ["임대료 수입 · 이자수익 · 배당금수익 계정이 없습니다"]
        base = f"매출액 {won(r['revenue'])}원"
        if r["added"]:
            base += f"에 매출액에 들어 있지 않은 임대 · 이자 · 배당 수입 {won(r['added'])}원을 더한 {won(r['base'])}원"
        return [f"{' · '.join(shown)}, 합계 {won(r['total'])}원", f"{base}의 {r['share']:.0%}"]

    def top_holder_fact(self) -> str | None:
        """전기 54호 3절 주주 줄에서 기말 지분율이 가장 큰 주주의 지분율. 지배주주등 합계(시행령 제43조 제7항)는 특수관계를
        알아야 해서 계산하지 않는다."""
        best = 0.0
        for row in ((self.P.get("rows") or {}).get("54") or []):
            try:
                best = max(best, float(str(row.get("기말_지분율") or "").replace(",", "")))
            except ValueError:
                continue
        if not best:
            return None
        text = f"전기 말 지분율이 가장 큰 주주의 지분율은 {best:g}%입니다(전기 54호)"
        return text + (". 한 주주가 50%를 넘게 갖고 있었습니다" if best > 50 else "")

    @property
    def ibt(self) -> int:
        return _int(self.tot.get("income_before_tax"))

    @property
    def corp_tax_amount(self) -> int:
        return max(_int(self.tot.get("corporate_tax")), self.T["corp_tax"].current)

    @property
    def sme(self):
        return self.company.get("sme")

    def amounts_of(self, t: Topic) -> dict:
        """이슈 금액. 전기 · 당기 · 증감이 늘 「당기 − 전기 = 증감」 으로 맞게 둔다(5회차).

        원가 계정(전기 금액 모름)의 당기 금액이 있으면 계정 전체의 전기 금액을 모르므로 전기 · 증감은 비우고(None)
        당기는 계정 전체 금액이다. 전기 금액을 아는 계정끼리 비교한 값은 근거 글(cost_note)에 둔다.
        """
        if t.unknown_prior:
            return {"prior": None, "current": t.current, "change": None}
        return {"prior": t.prior, "current": t.current, "change": t.change}

    @staticmethod
    def cost_note(t: Topic) -> str:
        known_cur = sum(_int(a.get("amount")) for a in t.known)
        known_pri = sum(_int(a.get("prior_amount")) for a in t.known)
        return (f"원가 계정(전기 금액 모름) 당기 {won(t.current - known_cur)}원이 있어 이슈의 전기 · 증감 칸은 비웠습니다. "
                f"전기 금액을 아는 계정만 보면 전기 {won(known_pri)}원, 당기 {won(known_cur)}원, 증감 {won(known_cur - known_pri)}원입니다")

    @staticmethod
    def gross(t: Topic) -> int:
        """기중 금액. 손익 계정은 금액(손익대체 뺀 값) 절대값, 재무상태표 계정은 차변 · 대변 합 가운데 큰 쪽."""
        out = 0
        for a in t.accounts:
            if a.get("class") in ("수익", "비용"):
                out += abs(_int(a.get("amount")))
            else:
                out += max(_int(a.get("debit")), _int(a.get("credit")))
        return out

    def period_amounts(self, t: Topic):
        """계정 묶음의 기말 · 전기 금액이 모두 0 인데 기중 거래가 있으면(자본에 바로 반영한 전기오류수정손익 · 기중에 받아 다 쓴
        보조금 등) 0 대신 기중 금액을 이슈 금액으로 쓴다(기말 0 이라 작은 후보로 접히던 것, 5회차). 아니면 topic 그대로."""
        if t.has_current or t.has_prior or not t.touched:
            return t
        return {"prior": None, "current": self.gross(t), "change": None}

    # ------------------------------------------------------------ 전표 묶음

    @property
    def vouchers(self) -> dict:
        """(일자, 전표번호) → 줄 목록(손익대체 전표 뺌)."""
        if not hasattr(self, "_vouchers"):
            v: dict[tuple, list] = {}
            for r in self.J:
                v.setdefault((str(r.get("date") or ""), str(r.get("no") or "")), []).append(r)
            self._vouchers = v
        return self._vouchers

    def voucher_of(self, r: dict) -> list[dict]:
        return self.vouchers.get((str(r.get("date") or ""), str(r.get("no") or "")), [r])

    def name_of(self, r: dict) -> str:
        return clean(self.by_code.get(r["account"], {}).get("name") or r.get("account_name"))

    def insurance_lines(self) -> dict:
        """비용 쪽 보험료 계정 줄: 줄 수, 적요에 보험기간(「2025.03.01~2026.02.28」 꼴)이 적힌 줄 수, 보증보험 줄 수."""
        codes = {str(a.get("code")) for a in self.accounts if re.search(r"보험료", str(a.get("name") or ""))
                 and not re.search(r"선급|미경과", str(a.get("name") or ""))}
        lines = [r for r in self.J if r["account"] in codes and _int(r.get("debit")) > 0]
        rx_period = re.compile(r"\d{2,4}[.\-/년]\s*\d{1,2}.{0,12}[~∼-].{0,4}\d{1,4}[.\-/년]\s*\d{1,2}")
        period = sum(1 for r in lines if rx_period.search(str(r.get("memo") or "")))
        surety = sum(1 for r in lines if re.search(r"보증보험|이행보증|보증증권", str(r.get("memo") or "")))
        return {"lines": len(lines), "period": period, "surety": surety}

    def lines_of(self, codes) -> list[dict]:
        codes = set(map(str, codes))
        return [r for r in self.J if r["account"] in codes]

    def add(self, key: str, kind: str, certainty: str, title: str, *, guide=(), topics=(), accounts=(), amounts=None,
            basis=(), papers=None, forms=(), questions=(), prior_treatment=None, todo=()) -> dict:
        """amounts 는 dict 이거나 Topic(그 topic 의 amounts_of). 없으면 topics 를 합친 topic."""
        t = self.agg(*topics) if topics else None
        codes = list(dict.fromkeys([*(t.codes if t else []), *(str(a) for a in accounts if a)]))
        amt_topic = amounts if isinstance(amounts, Topic) else (t if amounts is None else None)
        if amt_topic is not None:
            amounts = self.amounts_of(amt_topic)
            if amt_topic.unknown_prior:
                basis = [*basis, self.cost_note(amt_topic)]
        if key in self.issues:
            iss = self.issues[key]
            for f, vals in (("guide", guide), ("accounts", codes), ("basis", basis), ("forms", forms), ("questions", questions),
                            ("papers", papers_for(key, papers)), ("todo", todo)):
                iss[f] += [v for v in vals if v not in iss[f]]
            return iss
        iss = {"key": key, "kind": kind, "certainty": certainty, "guide": list(dict.fromkeys(guide)), "accounts": codes,
               "title": title, "amounts": amounts if amounts is not None else (self.amounts_of(t) if t else {}),
               "basis": [b for b in basis if b], "prior_treatment": prior_treatment,
               "papers": papers_for(key, papers),
               "forms": list(dict.fromkeys(forms)), "questions": list(questions), "todo": list(todo), "memo": None,
               "conclusion": None}
        self.issues[key] = iss
        return iss

    def judge(self, gid: str, status: str, facts=(), keys=()) -> None:
        rank = {None: 0, "해당 없음": 1, "자료 필요": 2, "이슈": 3}
        j = self.judg.setdefault(gid, {"status": None, "facts": [], "keys": []})
        if rank[status] > rank[j["status"]]:
            j["status"] = status
        j["facts"] += [f for f in facts if f and f not in j["facts"]]
        j["keys"] += [k for k in keys if k not in j["keys"]]

    # ------------------------------------------------------------ 신고 점검

    CHECK_TITLES = {
        "balanced": "분개장 차변 합계와 대변 합계가 다릅니다",
        "bs_rollforward": "전기 재무상태표에 분개장 증감을 더한 값이 당기 재무상태표와 다릅니다",
        "pl_match": "분개장 손익 집계가 손익계산서와 다릅니다",
        "closing_residual": "손익(400) 계정에 잔액이 남았습니다(마감 누락)",
        "partner_match": "거래처원장 합계가 재무상태표와 다릅니다",
    }

    def check_ledger(self) -> None:
        checks = self.L.get("checks") or []
        has_closing = False
        for c in checks:
            cid = str(c.get("id"))
            amts = {k: _int(v) for k, v in (c.get("amounts") or {}).items() if isinstance(v, (int, float))}
            if cid == "closing_residual":
                has_closing = True
                residual = amts.get("손익 400 잔액", 0)
                left = {k: v for k, v in amts.items() if k != "손익 400 잔액" and v}
                if c.get("ok") is False or residual:
                    self._closing_issue(residual, left, c.get("detail"), "확실")
                elif left:
                    self._closing_issue(0, left, c.get("detail"), "가능", offset=True)
                continue
            if c.get("ok") is not False:
                continue
            diff = amts.get("diff")
            if diff is None:
                nonzero = [v for k, v in amts.items() if v and k not in ("debit", "credit")]
                diff = max(nonzero, key=abs) if nonzero else 0
            basis = [str(c.get("detail") or "")[:400]]
            basis += [f"{k} {won(v)}원" for k, v in list(amts.items())[:6] if v and k not in ("debit", "credit", "diff")]
            self.add(f"check:{cid}", "신고 점검", "확실", self.CHECK_TITLES.get(cid, f"{c.get('title') or cid} 검사가 맞지 않습니다"),
                     guide=["2-1"], amounts={"change": diff} if diff else {}, basis=basis, papers=[],
                     questions=["장부를 고친 뒤 다시 보낸 분개장 · 재무제표가 있으면 보내 주십시오"])
        if not has_closing:
            acc = self.by_code.get("400")
            residual = _int(acc.get("closing")) if acc else 0
            if residual:
                self._closing_issue(residual, {}, f"손익(400) 기말 잔액 {won(residual)}원", "확실")

    def _closing_issue(self, residual: int, left: dict, detail, certainty: str, offset: bool = False) -> None:
        if offset:
            title = "마감 뒤에도 잔액이 남은 손익 계정이 있습니다(계정별 손익대체 금액 확인)"
            amount = max(left.values(), key=abs)
        else:
            title = self.CHECK_TITLES["closing_residual"]
            amount = residual
        head = ("손익(400) 잔액은 0원이지만 마감 뒤 잔액이 남은 손익 계정끼리 서로 상쇄됩니다" if offset
                else f"손익(400) 기말 잔액 {won(residual)}원")
        basis = [head] + [f"{k} {won(v)}원" for k, v in list(left.items())[:6]]
        codes = ["400"] + [k.split()[0] for k in left if k.split() and k.split()[0].isdigit()]
        self.add("check:closing_residual", "신고 점검", certainty, title, guide=["2-1"], accounts=codes,
                 amounts={"current": amount}, basis=basis, papers=[],
                 questions=["결산 마감(손익대체) 뒤에 고친 전표가 있으면 고친 내용을 알려 주십시오"])

    def check_prior_forms(self) -> None:
        """전기 신고서 서식끼리 맞지 않는 곳(신고본 품질 신호). 원천납부세액이 있는데 법인지방소득세 특별징수세액명세서가 빔."""
        if self.prior_filed("10갑", True) and not self.prior_filed("지방43의5갑", True):
            how = "빈 서식입니다" if self.prior_filed("지방43의5갑") else "없습니다"
            self.add("local_withholding", "신고 점검", "가능", "전기 원천납부세액이 있는데 법인지방소득세 특별징수세액명세서가 비었습니다",
                     guide=["2-3-4-1"], amounts={}, papers=[], forms=["지방43의5갑", "지방43의2"],
                     basis=[f"전기 10호(갑) 원천납부세액명세서를 냈고 지방 43호의5(갑) 특별징수세액명세서는 {how}",
                            "전기 법인지방소득세 신고에서 특별징수세액 공제가 빠졌을 수 있습니다. 당기에는 10호(갑)과 같이 채웁니다"],
                     questions=["전기 법인지방소득세 신고 때 이자소득 특별징수세액을 공제했는지 알려 주십시오"])

    def check_prior_car(self) -> None:
        """전기 29호 2절 손금불산입 합계(32, 업무외사용금액 30 + 감가상각비 한도초과 31)가 전기 15호 업무용승용차 가산 줄 합계보다
        크면 전기 조정 누락.

        15호 줄은 과목 · 조정내용이 업무용승용차 · 차량(subject_key car)이거나 「업무외」 가 든 가산 줄을 센다. 업무외사용금액과
        같은 금액 줄이 있고 남은 합계도 맞으면 넣은 것으로 본다. 10-19: 업무외사용금액이 0 이고 한도초과만 있는 회사에서
        렌트 한 대분 한도초과가 15호에 빠진 것을 못 잡아 32 와 견주도록 넓혔다."""
        c29 = (self.P.get("cells") or {}).get("29") or {}
        personal, excess = _int(c29.get("30")), _int(c29.get("31"))
        disallowed = _int(c29.get("32")) or personal + excess
        if disallowed <= 0:
            return
        lines = [a for a in self.prior_adj if a.get("side") == "가산"
                 and (subject_key(a.get("subject"), a.get("note")) == "car" or "업무외" in str(a.get("note") or a.get("subject") or ""))]
        added = sum(_int(a.get("amount")) for a in lines)
        if added >= disallowed:
            return
        gap = disallowed - added
        basis = [f"전기 29호 2절 손금불산입 합계 {won(disallowed)}원(업무외사용금액 {won(personal)}원 · 감가상각비(상당액) 한도초과 "
                 f"{won(excess)}원)"]
        basis.append(f"전기 15호 업무용승용차 · 차량 가산 줄 {len(lines)}줄 {won(added)}원, 차이 {won(gap)}원" if lines
                     else "전기 15호에 업무용승용차 · 차량 가산 줄이 없습니다")
        if personal > 0:
            basis.append("업무외사용금액은 손금불산입 대상입니다(법인세법 제27조의2 제2항)")
        if excess > 0:
            basis.append("감가상각비(상당액) 한도초과액은 손금불산입하고 다음 사업연도로 넘깁니다(법인세법 제27조의2 제3항)")
        basis.append("29호에 계산해 두고 15호에 옮기지 않았으면 전기 소득금액이 그만큼 적게 신고됐습니다. 차량별 줄을 맞춰 어느 차량이 빠졌는지 봅니다")
        title = ("전기 29호 업무외사용금액이 전기 15호에 없습니다(전기 조정 누락)" if personal > 0 and not lines
                 else "전기 29호 손금불산입 합계가 전기 15호 업무용승용차 가산 줄보다 큽니다(전기 조정 누락)")
        self.add("prior_car_missing", "신고 점검", "확실" if not lines else "가능", title, guide=["1-3", "2-3-21-1"],
                 amounts={"prior": gap}, basis=basis, papers=["business_car"], forms=["29", "15"],
                 questions=["전기 업무용승용차 손금불산입액 가운데 15호에 넣지 않은 차량과 까닭, 전기 신고를 고칠지(수정신고) 알려 주십시오",
                            "당기 업무용승용차의 운행기록부 작성 여부와 업무사용비율을 알려 주십시오"],
                 todo=["전기 신고서 29호 2절 차량별 줄과 15호를 맞춰 보고, 누락이 맞으면 전기 수정신고 여부를 회사와 정합니다"])
    def sme_scale(self, revenue: int) -> list[str]:
        """전기 51호 규모 기준 칸(억원, cells["51"])과 당기 손익계산서 매출액을 견준 사실. 당기 매출액이 소기업 기준(15) ·
        중소기업 기준(11)을 넘으면 이슈(sme_small · sme_size)를 더한다. 51호는 업종별 사업수입금액이고 여기서는 손익계산서
        매출액으로 견주므로 근거에 그 차이를 적는다."""
        c51 = (self.P.get("cells") or {}).get("51") or {}
        if not c51 or self.P.get("no_prior"):
            return ["전기 51호 규모 기준을 읽지 못했습니다"] if self.has_prior and not self.P.get("no_prior") else []
        eok = revenue / 100_000_000
        facts = []
        small_lim, sme_lim = c51.get("15"), c51.get("11")
        if small_lim:
            facts.append(f"전기 51호 소기업 규모기준(15) {small_lim:,g}억 원 · 전기 매출액(14) {c51.get('14', 0):,g}억 원, 당기 매출액 {eok:,.1f}억 원")
        if sme_lim:
            facts.append(f"전기 51호 중소기업 규모기준(11) {sme_lim:,g}억 원")
        how = "51호는 업종별 사업수입금액으로 견주고 여기서는 손익계산서 매출액으로 견주었습니다"
        q = ["당기 업종별 매출액(사업수입금액)과 주된 업종을 알려 주십시오"]
        if self.sme is True and sme_lim and eok > sme_lim:
            self.add("sme_size", "신고 점검", "가능", "당기 매출액이 전기 51호 중소기업 규모기준을 넘습니다. 유예기간 적용 여부를 확인합니다",
                     guide=["2-2"], amounts={"current": revenue}, papers=[], forms=["51"],
                     basis=[f"당기 매출액 {won(revenue)}원({eok:,.1f}억 원) · 전기 51호 중소기업 규모기준(11) {sme_lim:,g}억 원", how],
                     questions=q + ["중소기업 규모기준을 처음 넘은 사업연도(유예기간 시작)가 언제인지 알려 주십시오"])
        elif (self.sme is True and self.company.get("small") is False and small_lim
              and (eok <= small_lim or (c51.get("14") or small_lim + 1) <= small_lim)):
            prior_in = (c51.get("14") or small_lim + 1) <= small_lim
            self.add("sme_small", "신고 점검", "가능", "전기 51호는 소기업 「부」 인데 매출액이 소기업 규모기준 안입니다. 소기업 여부를 확인합니다",
                     guide=["2-2"], amounts={"current": revenue}, papers=["credits"], forms=["51"],
                     basis=[f"전기 51호 (27) 소기업 적정 여부 「부」, 소기업 규모기준(15) {small_lim:,g}억 원",
                            f"전기 매출액(14) {c51.get('14', 0):,g}억 원" + (" 로 이미 기준 안이었습니다(51호 안에서 어긋남)" if prior_in else ""),
                            f"당기 매출액 {won(revenue)}원({eok:,.1f}억 원)", how,
                            "소기업 · 중기업은 중소기업 특별세액감면 감면비율이 다릅니다(조세특례제한법 제7조 제1항 제2호)"],
                     questions=q)
        elif self.sme is True and self.company.get("small") and small_lim and eok > small_lim:
            self.add("sme_small", "신고 점검", "가능", "당기 매출액이 전기 51호 소기업 규모기준을 넘습니다. 소기업에서 중기업으로 바뀌는지 확인합니다",
                     guide=["2-2"], amounts={"current": revenue}, papers=["credits"], forms=["51"],
                     basis=[f"당기 매출액 {won(revenue)}원({eok:,.1f}억 원) · 전기 51호 소기업 규모기준(15) {small_lim:,g}억 원 · 전기 소기업", how,
                            "소기업 · 중기업은 중소기업 특별세액감면 감면비율이 다릅니다(조세특례제한법 제7조 제1항 제2호)"],
                     questions=q)
        return facts

    def check_tax_zero(self) -> None:
        if self.ibt <= 0 or self.corp_tax_amount != 0:
            return
        basis = [f"손익계산서 법인세차감전이익 {won(self.ibt)}원 · 법인세등 0원"]
        remaining = sum(_int(x.get("remaining")) for x in self.prior_losses if not x.get("derived"))
        prior06 = _int(self.cells3.get("06")) if self.cells3.get("06") not in (None, "") else None
        certainty = "확실"
        if remaining > 0:
            basis.append(f"전기 50호(갑) 이월결손금 잔액 {won(remaining)}원(공제하면 세액이 없을 수 있습니다)")
            certainty = "가능"
        if prior06 is not None and prior06 < 0:
            basis.append(f"전기 3호 06 각사업연도소득 {won(prior06)}원(결손금 공제로 세액이 없을 수 있습니다)")
            certainty = "가능"
        self.add("tax_zero", "신고 점검", certainty, "법인세차감전이익이 있는데 법인세등이 0원입니다", guide=["2-1"],
                 topics=["corp_tax"], amounts={"current": self.ibt}, basis=basis, papers=["corporate_tax"], forms=["3"],
                 questions=["결산에 법인세 추산액을 계상하지 않은 까닭을 알려 주십시오"])

    def prior_deficit(self) -> int:
        """전기 재무상태표 이익잉여금(결손금) 합계. 음수면 미처리결손금. 이익잉여금 소계 줄을 먼저 보고, 없으면 계정을 더한다."""
        for ln in ((self.L.get("fs") or {}).get("bs") or []):
            label = re.sub(r"\s+", "", str(ln.get("label") or ""))
            if ln.get("kind") == "subtotal" and re.search(r"이익잉여금|결손금", label) and ln.get("prior") is not None:
                return _int(ln.get("prior"))
        accs = [a for a in self.accounts if a.get("class") == "자본" and re.search(r"이익잉여금|결손금|이익준비금|적립금", clean(a.get("name")))]
        return sum(_int(a.get("prior_amount")) for a in accs)

    def check_prior_loss(self) -> None:
        """결손금 이력 점검. 전기 결손이 50호(갑) 결손금 표에 없거나 표의 잔액이 의심스러우면 결손이 난 해의 신고서로 이력을 확인하게 한다.

        신호: ① 전기 3호 06 이 음수인데 그 해 줄이 표에 없음(prior_loss_row, 확실) ② 전기 3호 07 이월결손금 공제가 있는데 표가 빔
        ③ 표 줄의 잔액이 음수이거나 발생액보다 큼 ④ 전기 재무상태표 미처리결손금이 표 잔액보다 큼.
        ① 이 서면 ②~④ 는 그 이슈 근거에 붙고, ① 없이 ②~④ 만 서면 loss_history(가능).
        """
        fy = self.prior_fy
        filed = [x for x in self.prior_losses if not x.get("derived")]   # derived: 전기 읽기가 3호 06 으로 채운 줄(신고서에는 없음)
        v06 = None if self.cells3.get("06") in (None, "") else _int(self.cells3.get("06"))
        missing_row = (v06 is not None and v06 < 0
                       and not any(str(x.get("year") or "") == fy or _int(x.get("incurred")) == -v06 for x in filed))
        signals = []
        v07 = _int(self.cells3.get("07"))
        if v07 > 0 and not filed:
            signals.append(f"전기 3호 07 이월결손금 공제 {won(v07)}원이 있는데 50호(갑) 결손금 표가 비었습니다")
        for x in filed:
            inc, used, rem = _int(x.get("incurred")), _int(x.get("used")), _int(x.get("remaining"))
            if rem < 0 or (inc and rem > inc) or (inc and used and rem != inc - used):
                signals.append(f"전기 50호(갑) {x.get('year')} 사업연도 줄의 발생 {won(inc)}원 · 공제 {won(used)}원 · 잔액 {won(rem)}원이 서로 맞지 않습니다")
        remaining = sum(_int(x.get("remaining")) for x in filed) + (-v06 if missing_row else 0)
        deficit = self.prior_deficit() if self.has_prior else 0
        if deficit < 0 and -deficit > remaining:
            signals.append(f"전기 재무상태표 이익잉여금 {won(deficit)}원(미처리결손금)이 50호(갑) 결손금 잔액 {won(remaining)}원보다 큽니다. "
                           "세무조정으로 차이가 날 수 있으나 신고서에 빠진 결손금이 있을 수 있습니다")
        ask = ["결손금이 처음 난 사업연도부터 전기까지의 세무조정계산서(3호 · 50호(갑))를 보내 주십시오"]
        why = "다음 해 이월결손금 공제에 바로 영향을 줍니다"
        todo = [LOSS_TODO]
        if missing_row:
            self.add("prior_loss_row", "신고 점검", "확실", "전기 결손금이 50호(갑) 이월결손금 줄에 없습니다", guide=["1-3"],
                     amounts={"prior": v06}, papers=["loss"], forms=["50갑"],
                     basis=[f"전기 3호 06 각사업연도소득 {won(v06)}원", f"전기 50호(갑) 결손금 줄 {len(filed)}개, {fy} 사업연도 줄 없음",
                            "결손금 표에 빠진 해가 있으면 그 전 사업연도 결손금도 빠졌을 수 있어 전전기 이전 신고서로 결손금 이력을 확인해야 합니다",
                            *signals, why],
                     questions=ask, todo=todo)
        elif signals:
            self.add("loss_history", "신고 점검", "가능", "50호(갑) 이월결손금 잔액을 결손금이 난 해의 신고서로 확인해야 합니다",
                     guide=["1-3"], amounts={"prior": remaining} if remaining else {}, papers=["loss"], forms=["50갑"],
                     basis=[f"전기 50호(갑) 결손금 줄 {len(filed)}개 · 잔액 {won(remaining)}원", *signals, why], questions=ask,
                     todo=todo)

    # ------------------------------------------------------------ 대여금 · 인정이자

    def fy_dates(self):
        from datetime import date
        fy = str(self.info.get("fy") or "")
        try:
            start = date.fromisoformat(str(self.info.get("fy_start") or f"{fy}-01-01"))
            end = date.fromisoformat(str(self.info.get("fy_end") or f"{fy}-12-31"))
        except ValueError:
            return None
        return (start, end) if start <= end else None

    def balance_path(self, codes) -> dict | None:
        """계정들의 기중 일별 잔액(차변 양수). 기초 + 날짜별 증감으로 걸어 최대 잔액과 적수(일별 잔액 합)를 낸다.
        변동이 있는 날은 그날부터 새 잔액으로 센다. 사업연도 날짜를 모르거나 전표 날짜를 읽지 못하면 None."""
        from datetime import date
        span = self.fy_dates()
        if span is None:
            return None
        start, end = span
        codes = set(map(str, codes))
        bal = sum(_int(self.by_code[c].get("opening")) for c in codes if c in self.by_code)
        deltas: dict = {}
        for r in self.J:
            if r["account"] not in codes:
                continue
            try:
                d = date.fromisoformat(str(r.get("date") or "")[:10])
            except ValueError:
                return None
            deltas[d] = deltas.get(d, 0) + r["debit"] - r["credit"]
        opening, prev, product = bal, start, 0
        peak, peak_date = bal, start
        for d in sorted(deltas):
            if d < start:
                bal += deltas[d]
                continue
            if d > end:
                break
            product += bal * (d - prev).days
            bal += deltas[d]
            prev = d
            if bal > peak:
                peak, peak_date = bal, d
        product += bal * ((end - prev).days + 1)
        days = (end - start).days + 1
        return {"opening": opening, "closing": bal, "peak": peak, "peak_date": peak_date.isoformat(), "days": days,
                "product": product, "average": int(round(product / days))}

    def forgiven(self, codes) -> tuple[Hits, Hits]:
        """대여금 대변 줄 가운데 적요에 면제 · 포기가 있는 줄. 같은 전표 차변에 현금 · 예금이 있으면 회수(돌려받은 돈)로 따로 센다."""
        real, repaid = Hits(), Hits()
        for r in self.lines_of(codes):
            memo = str(r.get("memo") or "")
            words = [m.group(0) for m in RX_FORGIVE.finditer(memo)]
            if not words or not r["credit"]:
                continue
            cash_in = any(o is not r and o["debit"] > 0 and RX_CASH_NAME.search(self.name_of(o)) for o in self.voucher_of(r))
            (repaid if cash_in else real).add(r, words)
        return real, repaid

    def rule_loans(self) -> None:
        loan = self.T["loan"]
        path = self.balance_path(loan.codes) if loan.touched else None
        during = bool(path and path["peak"] > 0)
        if not (loan.has_current or loan.has_prior or during):
            return
        partners = [p for p in (self.L.get("partners") or []) if str(p.get("account")) in set(loan.codes) and _int(p.get("closing"))]
        basis = [describe(loan)]
        if path and path["peak"] > 0:
            line = (f"기중 잔액: 최대 {won(path['peak'])}원({path['peak_date']}), 일별 잔액 평균 {won(path['average'])}원"
                    f"(적수 {won(path['product'])}원 ÷ {path['days']}일)")
            if path["average"] > max(loan.current, 0) or path["peak"] > max(loan.current, 0):
                line += f". 기말 잔액 {won(loan.current)}원보다 커서 인정이자 · 지급이자는 기말 잔액이 아니라 적수로 봅니다"
            basis.append(line)
        insider = Hits()
        for r in self.lines_of(loan.codes):
            words = [m.group(0) for m in RX_INSIDER.finditer(str(r.get("memo") or ""))]
            if words and r["debit"] > 0:
                insider.add(r, words)
        if insider:
            basis.append(insider.text("대표 · 임원(지급)"))
        if partners:
            basis.append(f"거래처원장 기말 잔액이 있는 상대 {len(partners)}곳")
        ii = self.T["interest_income"]
        basis.append(f"이자수익 {won(ii.current)}원")
        forgive, repaid = self.forgiven(loan.codes)
        if forgive:
            basis.append(forgive.text("면제 · 포기"))
        if repaid:
            basis.append(f"적요에 면제 · 포기 표기가 있으나 같은 전표 차변이 현금 · 예금인 줄 {repaid.n}줄 {won(-repaid.amount)}원은 "
                         "돌려받은 돈으로 보고 면제에서 뺐습니다")
        prior_hit = any(subject_key(a.get("subject"), a.get("note")) == "loan" for a in self.prior_adj)
        prior19 = self.prior_filed("19갑", True) or self.prior_filed("19을", True)
        q = ["대여 상대방이 주주 · 임원 · 직원 등 특수관계인인지와 약정 이자율 · 받은 이자를 알려 주십시오"]
        if forgive:
            q.append("대여금을 면제하거나 포기한 거래가 있으면 상대방과 까닭을 알려 주십시오")
        has = "대여금 · 주임종채권이 있는데" if (loan.has_current or loan.has_prior) else "기중에 대여금 · 가지급금이 있었는데"
        listed19 = self.listed_only("19갑", "19을")
        if listed19:
            basis.append(f"전기 총괄표에 {' · '.join(form_name(c) for c in listed19)} 첨부 O 표시가 있습니다. 받은 PDF 에는 그 쪽이 없어 "
                         "전기 인정이자 금액은 보지 못했습니다")
            q.append("전기 세무조정계산서의 가지급금등의인정이자조정명세서(19호 갑 · 을) 쪽을 보내 주십시오")
        if prior_hit or prior19:
            self.add("loan", "조정 후보", "확실", "가지급금 · 대여금 인정이자 계산이 필요합니다", guide=["2-3-3-1", "2-3-3-2"],
                     topics=["loan"], basis=basis + ["전기에 인정이자 조정 또는 19호가 있습니다"], papers=[],
                     forms=["19갑", "19을"], questions=q)
        else:
            self.add("loan", "신고 점검", "가능", f"{has} 전기에 인정이자 조정과 19호가 없습니다",
                     guide=["2-3-3-1", "2-3-3-2"], topics=["loan"], papers=[], forms=["19갑", "19을"],
                     basis=basis + ["전기 15호에 인정이자 줄이 없고 19호(갑)(을)을 내지 않았습니다"], questions=q)
        ie = self.T["interest_expense"]
        if (loan.has_current or during) and ie.current > 0:
            lb = [describe(ie), f"대여금 · 가지급금 기말 {won(loan.current)}원"]
            if path and path["peak"] > 0:
                lb.append(f"대여금 · 가지급금 일별 잔액 평균 {won(path['average'])}원(적수 {won(path['product'])}원)")
            self.add("loan_interest", "조정 후보", "가능", "업무무관 가지급금 관련 지급이자 손금불산입을 확인합니다",
                     guide=["2-3-3-3"], topics=["interest_expense"], papers=[], forms=["26갑", "26을"],
                     basis=lb + [describe(self.T["borrowing"])],
                     questions=["차입금별 이자율과 대여금이 업무와 관련된 것인지 알려 주십시오"])

    # ------------------------------------------------------------ 조정 후보

    def rule_corp_tax(self) -> None:
        amt = self.corp_tax_amount
        if amt > 0:
            pri = max(self.T["corp_tax"].prior, _int(self.prior_totals.get("corporate_tax")))
            self.add("corp_tax", "조정 후보", "확실", "법인세등을 손금불산입합니다", guide=["2-1"], topics=["corp_tax"],
                     amounts={"prior": pri, "current": amt, "change": amt - pri},
                     basis=[f"손익계산서 법인세등 {won(amt)}원"], forms=["15"], questions=[])
        self.rule_tax_refund()

    def refund_lines(self) -> dict[str, tuple[Hits, list[str]]]:
        """매출이 아닌 수익 계정 대변 줄 가운데 세금 환급 줄을 조서(wp corporate_tax.classify_refund)와 같은 낱말로 나눈다.
        {"corp": 법인세 · 지방소득세, "vat": 부가세, "local": 세목 모를 지방세, "interest": 환급가산금} → (Hits, 계정 코드).
        세목 모를 지방세 줄이 법인세 환급 합의 10%(±1%)면 조서처럼 법인지방소득세로 보고 corp 에 넣는다."""
        from ctax.wp.papers import corporate_tax as CT
        groups = {"corp": (CT.CORP_REFUND, CT.LOCAL_REFUND), "vat": (CT.VAT_REFUND,),
                  "local": (CT.LOCAL_TAX_REFUND,), "interest": (CT.REFUND_INTEREST, CT.CUSTOMS_INTEREST)}
        codes = {str(a.get("code")) for a in self.accounts if a.get("class") == "수익" and "매출" not in str(a.get("section") or "")}
        out = {g: (Hits(), []) for g in groups}
        local = []
        for r in self.J:
            net = r["credit"] - r["debit"]
            if r["account"] not in codes or net <= 0:
                continue
            got = CT.classify_refund(f"{str(r.get('partner') or '').strip()} {str(r.get('memo') or '').strip()}".strip(), False)
            if not got or (got[0] == CT.VAT_REFUND and net < CT.VAT_MIN):
                continue
            g = next(k for k, labels in groups.items() if got[0] in labels)
            if g == "local":
                local.append(r)
                continue
            words = [m.group(0) for m in re.finditer(r"법인세|지방소득세|지방세|부가세|부가가치세|경정청구|경정|과오납|환급가산금|가산금|환급",
                                                     str(r.get("memo") or ""))]
            if g == "vat":                      # 「법인세등_부가세_…」 꼴 적요 머리말의 법인세는 낱말에서 뺀다
                words = [w for w in words if w not in ("법인세", "지방소득세")]
            out[g][0].add(r, list(dict.fromkeys(words)))
            if r["account"] not in out[g][1]:
                out[g][1].append(r["account"])
        corp = -out["corp"][0].amount
        for r in local:
            net = r["credit"] - r["debit"]
            g = "corp" if corp and abs(net * 10 - corp) <= corp // 100 else "local"
            out[g][0].add(r, ["지방세"] + (["법인세 환급의 10%"] if g == "corp" else []))
            if r["account"] not in out[g][1]:
                out[g][1].append(r["account"])
        return {g: v for g, v in out.items() if v[0]}

    def rule_tax_refund(self) -> None:
        """수익에 든 세금 환급. 법인세 · 지방소득세 환급과 부가세 환급(경정청구 등)을 적요로 나눠 금액을 따로 적는다.
        법인세 환급은 익금불산입(법인세법 제18조 제3호)이고, 부가세 환급의 익금 여부는 회계사가 정한다."""
        found = self.refund_lines()
        if not found:
            return
        names = {"corp": "법인세 · 지방소득세 환급", "vat": "부가세 환급", "local": "세목을 모르는 지방세 환급", "interest": "환급가산금"}
        basis = [h.text(names[g]) for g, (h, _c) in found.items()]
        if "vat" in found:
            basis.append("부가세 환급은 익금 여부를 회계사가 정합니다. 낼 때 손금이 아니었던 매출세액 · 공제 매입세액을 돌려받은 것이면 "
                         "익금불산입, 불공제 매입세액처럼 비용으로 처리한 세액의 환급이면 익금입니다(조서 0 법인세비용 노란 칸)")
        heads = [w for g, w in (("corp", "법인세"), ("vat", "부가세"), ("local", "지방세")) if g in found]
        what = [f"{' · '.join(heads)} 환급액"] if heads else []
        what += ["환급가산금"] if "interest" in found else []
        title = f"{' · '.join(what)}이 수익에 있습니다. 익금불산입을 확인합니다"
        q = []
        if "corp" in found:
            q.append("환급받은 법인세 · 지방소득세가 몇 사업연도 분인지 알려 주십시오")
        if "vat" in found:
            q.append("부가세 환급(경정청구)이 어느 과세기간 분이고 무엇을 고쳐 돌려받은 것인지(매출세액 · 공제 매입세액 · 불공제 매입세액) 알려 주십시오")
        if "local" in found:
            q.append("지방세 환급이 어느 세목(법인지방소득세 · 재산세 등)인지 알려 주십시오")
        total = sum(-h.amount for h, _c in found.values())
        accounts = sorted({c for _h, codes in found.values() for c in codes})
        self.add("tax_refund", "조정 후보", "가능", title, guide=["2-1"], accounts=accounts, amounts={"current": total},
                 basis=basis, papers=["corporate_tax"], forms=["15"], questions=q)

    def rule_entertainment(self) -> None:
        t = self.T["entertainment"]
        if not (t.has_current or t.touched):
            return
        basis = [describe(t), f"전표 {t.lines}줄"]
        ev = self.scan(t.codes, RX_ENT_EVENT)
        card = self.scan(t.codes, RX_ENT_CARD)
        if ev:
            basis.append(ev.text("경조사"))
        if card:
            basis.append(card.text("카드"))
        if self.rent_share() >= 0.5:
            basis.append(f"임대 · 이자 · 배당 수입이 매출액의 {self.rent_share():.0%}입니다. 지배주주등 지분 50% 초과 · 상시근로자 5명 미만이면 "
                         "한도가 일반 법인의 50%입니다(법인세법 제25조 제5항)")
        self.add("entertainment", "조정 후보", "확실", "기업업무추진비 한도 계산이 필요합니다", guide=["2-3-16-1"],
                 topics=["entertainment"], basis=basis, forms=["23갑", "23을"],
                 questions=["경조사비 중 한 번에 20만원을 넘는 지출이 있으면 명세를 보내 주십시오",
                            "3만원을 넘는 기업업무추진비 중 법인카드 · 세금계산서 같은 적격증빙이 없는 지출이 있으면 알려 주십시오"])

    def rule_car(self) -> None:
        veh, vc = self.T["vehicles"], self.T["vehicle_cost"]
        exp_codes = self.agg("vehicle_cost", "rent_expense", "insurance", "taxes").codes
        car = self.scan(exp_codes, RX_CAR)
        truck = self.scan(exp_codes + veh.codes, RX_TRUCK)
        prior29 = self.prior_filed("29", True)
        prior_adj = any(subject_key(a.get("subject"), a.get("note")) == "car" for a in self.prior_adj)
        if not (veh.has_current or vc.has_current or car):
            return
        trucks, passenger = self.car_kinds(exp_codes + veh.codes)
        if trucks and not passenger and not (prior29 or prior_adj):
            # 10-21: 차량 줄이 모두 화물차 · 건설기계면 업무용승용차(개별소비세 과세 승용자동차, 법인세법 제27조의2 제1항)가 없다
            self.judge("2-3-21-1", "해당 없음",
                       [f"차량 관련 적요 · 차량번호가 모두 화물차 · 건설기계입니다({' · '.join(sorted(trucks)[:5])})",
                        "전기에 29호와 업무용승용차 조정이 없습니다. 승용차를 따로 쓰면 29호 대상입니다"])
            return
        basis = []
        if veh.exists:
            basis.append(describe(veh))
        if vc.exists:
            basis.append(describe(vc))
        if car:
            basis.append(car.text("렌트 · 리스 · 차량번호"))
        if truck:
            basis.append(truck.text("화물차 · 건설기계") + ". 화물차는 29호 대상이 아닙니다")
        if prior29:
            basis.append("전기에 29호를 냈습니다")
        certainty = "확실" if (prior29 or prior_adj) else "가능"
        amounts = vc if vc.exists else {"current": car.amount}
        accounts = sorted({r["account"] for r in self.J if r["account"] in set(exp_codes) and RX_CAR.search(str(r.get("memo") or ""))})
        self.add("car", "조정 후보", certainty, "업무용승용차 관련비용 명세(29호)와 한도 계산이 필요합니다", guide=["2-3-21-1"],
                 topics=["vehicles", "vehicle_cost"], accounts=accounts, amounts=amounts, basis=basis, forms=["29"],
                 questions=["업무용승용차(개별소비세 과세 승용차) 목록과 차량별 취득 · 렌트 · 리스 구분, 운행기록부 작성 여부를 알려 주십시오"])

    def car_kinds(self, codes) -> tuple[set, list]:
        """(화물차 · 건설기계로 보이는 표시, 승용차일 수 있는 줄). 차량번호 앞자리가 승합 · 화물 · 특수(두 자리 70~99, 세 자리 700~999)이거나
        적요에 포터 · 봉고 · 굴삭기 같은 말이 함께 있으면 화물차다. 그 번호가 다른 줄에 홀로 나와도 화물차로 본다. 승용차일 수 있는 줄은
        렌트 · 리스료 · 자동차보험 · 자동차세 · 차량번호 줄(RX_CAR) 가운데 화물차 표시가 없는 줄이다."""
        lines = self.lines_of(codes)
        trucks, plates = set(), {}
        for r in lines:
            memo = str(r.get("memo") or "")
            got = ["".join(m.groups()) for m in RX_PLATE.finditer(memo)]
            word = RX_TRUCK.search(memo)
            for pl in got:
                head = re.match(r"\d+", pl).group(0)
                if word or int(head) >= (70 if len(head) == 2 else 700):
                    plates[pl] = True
            if word and not got:
                trucks.add(word.group(0))
        trucks |= set(plates)
        passenger = []
        for r in lines:
            memo = str(r.get("memo") or "")
            if not RX_CAR.search(memo) or RX_TRUCK.search(memo):
                continue
            got = ["".join(m.groups()) for m in RX_PLATE.finditer(memo)]
            if got and all(pl in plates for pl in got):
                continue
            passenger.append(r)
        return trucks, passenger

    def rule_penalty(self) -> None:
        tx, ml, mx = self.T["taxes"], self.T["misc_loss"], self.T["misc_expense"]
        h3 = self.scan(mx.codes, RX_PENALTY, exclude=RX_NOT_PENALTY, min_amount=10) if mx.exists else Hits()
        if not (tx.exists or ml.exists or h3):
            return
        h1 = self.scan(tx.codes, RX_PENALTY, exclude=RX_NOT_PENALTY, min_amount=10)
        h2 = self.scan(ml.codes, re.compile(RX_PENALTY.pattern + "|" + RX_TAX_IN_LOSS.pattern), extra=RX_LOCAL_GOV,
                       exclude=RX_NOT_PENALTY, min_amount=10)       # 10원 미만은 단수 차이
        basis = [describe(tx)] if tx.exists else []
        if ml.exists:
            basis.append(describe(ml))
        if h1:
            basis.append("세금과공과 " + h1.text("가산세 · 과태료"))
        if h2:
            basis.append("잡손실 " + h2.text("세금 · 과태료"))
        if h3:
            basis.append("잡비 " + h3.text("과태료 · 벌과금"))
        certainty = "확실" if (h1 or h2 or h3) else "가능"
        where = "세금과공과 · 잡손실 · 잡비" if h3 else "세금과공과 · 잡손실"
        title = (f"{where}에 가산세 · 과태료로 보이는 지출이 있습니다" if (h1 or h2 or h3)
                 else "세금과공과 · 잡손실에서 손금불산입 항목을 가려냅니다")
        accts = sorted({r["account"] for r in self.J if r["account"] in set(mx.codes) and RX_PENALTY.search(str(r.get("memo") or ""))})
        self.add("penalty", "조정 후보", certainty, title, guide=["2-3-15-1"], topics=["taxes", "misc_loss"], accounts=accts,
                 basis=basis,
                 forms=["세금공과금명세서"],
                 questions=["세금과공과 · 잡손실 중 가산세 · 과태료 · 벌과금 · 연체료가 있으면 고지서를 보내 주십시오"])
        self.rule_nondeductible_vat()

    def prior_nondeductible(self) -> tuple[int, int, list[str]]:
        """전기에 손금불산입한 불공제 매입세액. 전기 세금공과금명세서 줄(rows, 적요 「불공제」 · 비고 「손금불산입」) 합계, 없으면 전기 15호
        가산 줄 가운데 과목 · 조정내용에 「불공제」 가 든 줄. (줄 수, 금액, 근거 글)."""
        rows = [r for r in ((self.P.get("rows") or {}).get("세금공과금명세서") or [])
                if RX_NONDEDUCT_VAT.search(str(r.get("적요") or "")) and str(r.get("비고") or "").startswith("손금불산입")
                and "취소" not in str(r.get("비고") or "")]
        if rows:
            amt = sum(_int(r.get("금액")) for r in rows)
            return len(rows), amt, [f"전기 세금공과금명세서 「{rows[0].get('적요')}」 {len(rows)}줄 {won(amt)}원 비고 손금불산입"]
        adds = [a for a in self.prior_adj if a.get("side") == "가산"
                and RX_NONDEDUCT_VAT.search(f"{a.get('subject') or ''} {a.get('note') or ''}")]
        amt = sum(_int(a.get("amount")) for a in adds)
        return len(adds), amt, ([f"전기 15호 가산 {a.get('subject')} {won(_int(a.get('amount')))}원 {a.get('disposition') or ''}".strip()
                                 for a in adds])

    def rule_nondeductible_vat(self) -> None:
        """불공제 매입세액을 비용으로 대체한 줄. 전기에 같은 적요를 손금불산입했으면(10-20) 비용 계정 전부를 보고 확실로 올린다."""
        tx = self.T["taxes"]
        n_prior, prior_amt, prior_basis = self.prior_nondeductible()
        self.prior_vat = prior_amt
        codes = self.codes_by_class("비용") if prior_amt else tx.codes
        nv = self.scan(codes, RX_NONDEDUCT_VAT, min_amount=10)
        if not nv:
            return
        accts = sorted({r["account"] for r in self.J if r["account"] in set(codes)
                        and RX_NONDEDUCT_VAT.search(str(r.get("memo") or ""))}) if prior_amt else sorted({*tx.codes})
        where = " · ".join(dict.fromkeys(self.name_of({"account": c}) for c in accts)) if prior_amt else "세금과공과"
        basis = [f"{where} " + nv.text("불공제 매입세액"),
                 "부가가치세 매입세액은 손금불산입이고, 면세사업 관련 등 부가가치세법 제39조 제1항 제5호 · 제6호 매입세액은 손금입니다"]
        if prior_amt:
            basis += prior_basis + ["전기에 같은 적요의 불공제 매입세액을 손금불산입했습니다. 당기에도 같은 사유면 같은 조정이 따릅니다"]
        self.add("nondeductible_vat", "조정 후보", "확실" if prior_amt else "가능",
                 ("전기에 손금불산입한 불공제 매입세액이 당기에도 있습니다. 불공제 사유별로 손금 여부를 가립니다" if prior_amt
                  else "세금과공과에 불공제 매입세액이 있습니다. 불공제 사유별로 손금 여부를 가립니다"), guide=["2-3-15-1"],
                 topics=[] if prior_amt else ["taxes"], accounts=accts,
                 amounts={"prior": prior_amt, "current": nv.amount, "change": nv.amount - prior_amt} if prior_amt else {"current": nv.amount},
                 basis=basis, papers=["taxes_dues"], forms=["15", "세금공과금명세서"],
                 prior_treatment=f"전기 불공제 매입세액 {won(prior_amt)}원 손금불산입" if prior_amt else None,
                 questions=["불공제 매입세액의 불공제 사유별 금액(면세사업 · 비영업용 승용차 · 기업업무추진비 · 세금계산서 미수취 등)을 "
                            "보내 주십시오"])

    def rule_retirement(self) -> None:
        ra, rp, rx = self.T["retirement_allowance"], self.T["retirement_plan"], self.T["retirement_expense"]
        if ra.exists:
            basis = [describe(ra), f"계정 상태 {ra.status()}"]
            if rx.exists:
                basis.append(describe(rx))
            self.add("retirement_allowance", "조정 후보", "확실", "퇴직급여충당금 한도 계산(32호)이 필요합니다", guide=["2-3-9-1"],
                     topics=["retirement_allowance"], basis=basis, forms=["32"],
                     questions=["기말 현재 전 직원이 퇴직할 때 줄 퇴직급여 추계액(일시퇴직 기준)과 퇴직급여 지급 명세를 보내 주십시오"])
        if rp.exists:
            self.add("retirement_plan", "조정 후보", "확실", "퇴직연금부담금 손금산입(33호)이 필요합니다", guide=["2-3-9-1"],
                     topics=["retirement_plan"], basis=[describe(rp), f"계정 상태 {rp.status()}"], forms=["33"],
                     questions=["퇴직연금 유형(확정급여형 · 확정기여형)과 기말 적립금 잔액 확인서를 보내 주십시오"])
        self.rule_plan_income(ra, rp)

    def rule_plan_income(self, ra: Topic, rp: Topic) -> None:
        """퇴직연금 운용수익을 수익으로 적지 않고 퇴직급여충당부채에 바로 더한 전표(5회차).

        전표 꼴: 차변 퇴직연금운용자산 · 대변 퇴직급여충당부채, 같은 전표에 수익 계정 · 현금 · 예금이 없음.
        운용수익은 순자산을 늘리는 수익이라 익금이다(법인세법 제15조 제1항). 적요에 운용 · 수익 · 이자가 있으면 확실, 없으면 가능.
        """
        if not (ra.codes and rp.codes):
            return
        ra_codes, rp_codes = set(ra.codes), set(rp.codes)
        income = set(self.codes_by_class("수익"))
        found, sure = Hits(), True
        for key, rows in self.vouchers.items():
            plan_dr = [r for r in rows if r["account"] in rp_codes and r["debit"] > 0]
            prov_cr = [r for r in rows if r["account"] in ra_codes and r["credit"] > 0]
            if not (plan_dr and prov_cr):
                continue
            if any(r["account"] in income or RX_CASH_NAME.search(self.name_of(r)) for r in rows):
                continue
            amount = min(sum(r["debit"] for r in plan_dr), sum(r["credit"] for r in prov_cr))
            memo = " ".join(str(r.get("memo") or "") for r in plan_dr + prov_cr)
            words = [m.group(0) for m in RX_PLAN_INCOME.finditer(memo)]
            sure = sure and bool(words)
            found.add({"debit": amount, "credit": 0}, words or ["표기 없음"])
        if not found:
            return
        self.add("retirement_income", "조정 후보", "확실" if sure else "가능",
                 "퇴직연금 운용수익을 수익으로 적지 않고 퇴직급여충당부채에 바로 더한 전표가 있습니다", guide=["2-3-9-1"],
                 accounts=[*rp.codes, *ra.codes], amounts={"current": found.amount}, forms=["15", "50을", "32", "33"],
                 basis=[f"차변 퇴직연금운용자산 · 대변 퇴직급여충당부채이고 같은 전표에 수익 · 예금 계정이 없는 전표 {found.n}건 "
                        f"{won(found.amount)}원(적요 {' · '.join(found.words[:4])})",
                        "운용수익이 손익계산서를 거치지 않았고, 같은 금액이 퇴직급여충당부채 대변(설정)에 퇴직급여(비용) 없이 들어 있습니다"],
                 questions=["퇴직연금 운용사의 운용수익 명세(기간 · 금액)를 보내 주십시오"])

    def rule_donation(self) -> None:
        t = self.T["donation"]
        if not (t.has_current or t.touched):
            return
        self.add("donation", "조정 후보", "확실", "기부금 한도 계산(21호)이 필요합니다", guide=["2-3-22-1"], topics=["donation"],
                 basis=[describe(t), f"전표 {t.lines}줄"], forms=["21", "22"],
                 questions=["기부금 영수증(기부처 · 금액 · 특례 · 일반 구분)을 보내 주십시오"])

    def check_prior_donation(self) -> None:
        """전기 15호 기부금 가산 줄의 금액이 전기 21호 6절(해당 사업연도 기부금 지출액)에도 손금산입으로 들어 있으면 전기 신고서
        안에서 같은 기부금을 두 번 다룬 것이다(10-19 평가세트 한 곳). 전기 기부금 계정 금액과 21호 지출액 합이 같을 때만 본다."""
        fy = self.prior_fy
        rows = [r for r in ((self.P.get("rows") or {}).get("21") or []) if r.get("절") == 6 and str(r.get("사업연도")) == fy]
        adds = [a for a in self.prior_adj if a.get("side") == "가산" and subject_key(a.get("subject"), a.get("note")) == "donation"]
        if not rows or not adds:
            return
        spent = sum(_int(r.get("26")) for r in rows)
        deducted = sum(_int(r.get("27")) for r in rows)
        book = self.T["donation"].prior
        disallowed = sum(_int(a.get("amount")) for a in adds)
        if not book or spent != book or deducted + disallowed <= book:
            return
        self.add("prior_donation_overlap", "신고 점검", "가능", "전기 15호 기부금 손금불산입액이 전기 21호에서도 손금산입돼 있습니다",
                 guide=["1-3", "2-3-22-1"], amounts={"prior": disallowed}, papers=["donation"], forms=["21", "15"],
                 basis=[f"전기 기부금 계정 {won(book)}원 = 전기 21호 6절 지출액 합 {won(spent)}원, 그 가운데 손금산입 {won(deducted)}원",
                        f"전기 15호 기부금 가산 {len(adds)}줄 {won(disallowed)}원({adds[0].get('note') or ''})",
                        "같은 기부금이 21호 손금산입과 15호 손금불산입에 함께 들어 있어 둘 가운데 하나는 틀렸습니다. "
                        "15호 줄이 비지정기부금이면 21호 지출액에서 빠져야 하고, 한도초과액이면 3호 (105) 에 적고 15호에는 적지 않습니다",
                        "당기 21호의 전기 이월액(5절)과 당기 한도 계산이 이 판단에 따라 달라집니다"],
                 questions=["전기 15호 기부금 손금불산입 줄이 어떤 기부금(기부처 · 종류)인지 알려 주십시오"])

    def allowance_split(self) -> dict:
        """대손충당금 차변 줄을 같은 전표 상대 계정으로 나눈다: 채권 대변이면 대손(상계), 대손상각비 · 환입 계정이면 환입,
        나머지는 그 밖. 대손상각비 차변이 채권 대변과 같은 전표면 직접 대손(5회차, 환입 전표를 대손으로 읽던 것)."""
        al, bd = self.T["allowance"], self.T["bad_debt"]
        claims = set(self.T["receivable"].codes) | set(self.T["loan"].codes)
        bd_codes = set(bd.codes)
        out = {"written_off": 0, "reversed": 0, "other": 0, "direct": 0}
        for r in self.lines_of(al.codes):
            if r["debit"] <= 0:
                continue
            others = [o for o in self.voucher_of(r) if o is not r]
            if any(o["account"] in claims and o["credit"] > 0 for o in others):
                out["written_off"] += r["debit"]
            elif any(o["account"] in bd_codes for o in others):
                out["reversed"] += r["debit"]
            else:
                out["other"] += r["debit"]
        for r in self.lines_of(bd_codes):
            if r["debit"] > 0 and any(o["account"] in claims and o["credit"] > 0 for o in self.voucher_of(r) if o is not r):
                out["direct"] += r["debit"]
        return out

    def rule_bad_debt(self) -> None:
        al, bd = self.T["allowance"], self.T["bad_debt"]
        if not (al.exists or bd.exists):
            return
        basis = [describe(al)] if al.exists else []
        if bd.exists:
            basis.append(describe(bd))
        split = self.allowance_split()
        if al.exists and al.debit > 0:
            parts = [f"{name} {won(split[k])}원" for k, name in (("written_off", "채권 상계(대손)"), ("reversed", "환입"),
                                                                ("other", "그 밖")) if split[k]]
            basis.append(f"대손충당금 차변 {won(al.debit)}원: {' · '.join(parts)}"
                         + (". 대손 처리한 채권이 있습니다" if split["written_off"] else ". 채권을 대손으로 지운 전표는 없습니다"))
        if split["direct"]:
            basis.append(f"대손상각비로 채권을 바로 지운 전표 {won(split['direct'])}원(직접 대손)")
        certainty = "가능"
        limit = self.allowance_limit(al, split)
        if limit:
            basis += limit["basis"]
            if limit["over"]:
                certainty = "확실"
        if self.has_prior and al.has_prior and not self.prior_filed("34"):
            basis.append("전기에 대손충당금이 있었는데 34호를 내지 않았습니다. 한도 안이어도 34호는 붙입니다")
        guide = ["2-3-2-1"] + (["2-3-2-2"] if (split["written_off"] or split["direct"] or bd.has_current) else [])
        iss = self.add("bad_debt", "조정 후보", certainty, "대손충당금 한도와 대손 요건(34호)을 확인합니다", guide=guide,
                       topics=["allowance", "bad_debt"], amounts=al if al.exists else bd, basis=basis, papers=[], forms=["34"],
                       questions=["대손 처리한 채권이 있으면 대손 사유(파산 · 소멸시효 등) 증빙을 보내 주십시오"])
        if limit and limit["over"]:
            iss.setdefault("law_extra", []).append("bad_debt_limit")
        if limit and limit.get("excluded"):
            iss.setdefault("law_extra", []).append("bad_debt_excluded")

    def allowance_limit(self, al: Topic, split: dict) -> dict | None:
        """대손충당금 기말 잔액과 세법 한도(채권잔액 × 1% 와 대손실적률 중 큰 비율, 법인세법 시행령 제61조 제2항)를 견준다.

        채권잔액은 매출채권 · 미수금에 그 밖 설정 대상 채권을 더하되, 대여금 · 가지급금 · 주임종 계정(loan 묶음)은 특수관계인 대여로
        보아 설정 대상에서 뺀다(법인세법 제34조 제2항 · 제19조의2 제2항 제2호. 조서 10 대손충당금의 설정제외 기본값과 같다, 10-25 대표
        지시. 전에는 빼지 않은 채권잔액의 1% 를 적어 조서와 어긋났다). 뺀 채권까지 넣어 계산한 한도도 넘으면 확실, 뺀 한도만 넘으면
        가능이다(업무와 관련된 대여면 설정 대상이라 한도초과가 없을 수 있다). 대손실적률은 대손(상계) + 직접 대손을 전기 매출채권 ·
        미수금(좁은 쪽)으로 나눈다. 전기 채권이 0 인데 대손이 있으면 비율을 정하지 못해 보지 않는다.
        """
        if not al.exists or al.current >= 0:
            return None
        rc = self.T["receivable"]
        narrow = max(rc.current, 0)
        others = self.other_claims(al, set(rc.codes))
        loan_codes = set(self.T["loan"].codes)
        related = [a for a in others if str(a.get("code")) in loan_codes]
        plain = [a for a in others if str(a.get("code")) not in loan_codes]
        related_total = sum(_int(a.get("amount")) for a in related)
        plain_total = sum(_int(a.get("amount")) for a in plain)
        base = narrow + plain_total
        wide = base + related_total
        if wide <= 0:
            return None
        bad = split["written_off"] + split["direct"] + split["other"]     # 그 밖 차변도 대손일 수 있어 넣는다(한도를 넓게)
        prior_base = max(rc.prior, 0)
        if bad and prior_base <= 0:
            return None
        rate = max(0.01, bad / prior_base if prior_base else 0.0)
        balance = -al.current
        lim_base, lim_wide = int(base * rate), int(wide * rate)
        how = "1%" if rate == 0.01 else f"대손실적률 {rate:.2%}"
        plain_names = " · ".join(dict.fromkeys(clean(a.get("name")) for a in plain[:4])) or "그 밖 채권"
        related_names = " · ".join(dict.fromkeys(clean(a.get("name")) for a in related[:4])) or "대여금 · 가지급금"
        base_text = f"매출채권 · 미수금 {won(narrow)}원"
        if plain_total:
            base_text = f"채권잔액({base_text} + {plain_names} {won(plain_total)}원) {won(base)}원"
        excl = (f"{related_names} {won(related_total)}원은 특수관계인 대여로 보아 설정 대상에서 뺐습니다(법인세법 제34조 제2항, 조서 "
                "설정제외 기본값과 같음. 업무와 관련된 대여면 설정 대상입니다)") if related_total else ""
        if balance > lim_wide:
            line = f"대손충당금 기말 {won(balance)}원이 {base_text}의 {how} {won(lim_base)}원보다 커 한도초과가 생깁니다"
            if related_total:
                line += f". {excl}. 넣어 계산한 한도 {won(lim_wide)}원보다 커 한도초과입니다"
        elif base > 0 and balance > lim_base:
            line = f"대손충당금 기말 {won(balance)}원이 {base_text}의 {how} {won(lim_base)}원보다 큽니다"
            if related_total:
                line += f". {excl}. 설정 대상에 넣으면 한도 {won(lim_wide)}원이라 한도초과가 없습니다"
        else:
            return None
        return {"over": balance > lim_wide, "basis": [line], "excluded": related_total > 0}

    def other_claims(self, al: Topic, skip: set) -> list[dict]:
        """매출채권 · 미수금 밖의 설정 대상일 수 있는 채권(잔액이 양수인 자산 계정). 이름에 채권 · 미수 · 어음 · 대여 · 대출 ·
        선급금이 있는 계정, 대여금 · 가지급금, 대손충당금 계정 바로 앞 자산 계정(충당금이 붙은 채권). 한도를 넓게 잡으려고 넓게 모은다."""
        allowance = set(al.codes)
        accounts = [a for a in self.L.get("accounts") or [] if a.get("code")]
        picked: dict[str, dict] = {}
        for i, a in enumerate(accounts):
            code = str(a.get("code"))
            if code in allowance:
                prev = next((b for b in reversed(accounts[:i]) if b.get("class") == "자산" and str(b.get("code")) not in allowance), None)
                if prev is not None:
                    picked.setdefault(str(prev.get("code")), prev)
            elif a.get("class") == "자산" and (code in set(self.T["loan"].codes)
                                              or re.search(r"채권|미수|어음|대여|대출|선급금", clean(a.get("name")))):
                picked.setdefault(code, a)
        return [a for c, a in picked.items() if c not in skip and c not in allowance and _int(a.get("amount")) > 0]

    def rule_accrued(self) -> None:
        ai, ae, pv = self.T["accrued_income"], self.T["accrued_expense"], self.T["provision"]
        if ai.exists:
            self.add("accrued_income", "조정 후보", "가능", "미수이자 익금불산입(유보)을 확인합니다", guide=["2-3-4-2"],
                     topics=["accrued_income"], basis=[describe(ai), f"계정 상태 {ai.status()}"], papers=[], forms=["15", "50을"],
                     questions=["미수수익 중 예금 · 대여금 이자처럼 원천징수 대상 이자의 기간경과분이 있으면 명세를 보내 주십시오"])
        if ae.exists:
            self.add("accrued_expense", "조정 후보", "가능", "미지급비용 중 미확정 비용(연차수당 등)을 확인합니다", guide=["2-3-9-1"],
                     topics=["accrued_expense"], basis=[describe(ae), f"계정 상태 {ae.status()}"], papers=[], forms=["15", "50을"],
                     questions=["미지급비용 명세(연차수당 · 성과급 · 이자 구분)를 보내 주십시오"])
        if pv.exists:
            self.add("provision", "조정 후보", "가능", "충당부채 전입액 손금불산입(유보)을 확인합니다", guide=["2-3-9-1"],
                     topics=["provision"], basis=[describe(pv)], papers=[], forms=["15", "50을"], questions=[])
        pp = self.T["prepaid"]
        ins = self.insurance_lines()
        if pp.current > 0 or ins["period"] or ins["surety"]:   # 선급비용 잔액, 또는 보험료 적요에 보험기간 · 보증보험
            basis = [describe(pp), f"계정 상태 {pp.status()}"] if pp.exists else ["선급비용 계정이 없습니다"]
            if ins["lines"]:
                basis.append(f"보험료 줄 {ins['lines']}줄 가운데 적요에 보험기간이 적힌 줄 {ins['period']}줄, 보증보험 줄 "
                             f"{ins['surety']}줄. 기간이 없는 보증보험 줄은 증권의 보험기간으로 미경과액을 셉니다")
            self.add("prepaid", "조정 후보", "가능", "선급비용이 있습니다. 기간 미경과액(선급비용명세서)을 확인합니다", guide=["2-1"],
                     topics=["prepaid"], basis=basis, forms=["선급비용명세서"],
                     questions=["선급비용 명세(보험료 · 임차료 등 지급일 · 대상 기간 · 금액)를 보내 주십시오"])

    @staticmethod
    def pl_lines(pl: Topic) -> list[str]:
        """유가증권 손익 계정을 성격별로 나눈 근거 줄(5회차). 이익과 손실을 한 금액으로 더하지 않는다.
        평가 · 지분법 · 손상(세법이 인정하지 않는 평가손익)과 처분손익(세법도 손익), 자본의 평가손익(기타포괄)을 따로 적는다."""
        groups: dict[str, list] = {}
        for a in pl.accounts:
            name = clean(a.get("name"))
            if a.get("class") == "자본":
                g = "기타포괄손익(자본)의 평가손익"
            elif re.search(r"처분", name):
                g = "처분이익" if a.get("class") == "수익" else "처분손실"
            elif a.get("class") == "수익":
                g = "평가 · 지분법 이익(익금불산입 후보)"
            else:
                g = "평가 · 지분법 · 손상 손실(손금불산입 후보)"
            groups.setdefault(g, []).append(a)
        order = ["평가 · 지분법 이익(익금불산입 후보)", "평가 · 지분법 · 손상 손실(손금불산입 후보)", "처분이익", "처분손실",
                 "기타포괄손익(자본)의 평가손익"]
        out = []
        for g in order:
            if g in groups:
                out.append(f"{g}: " + describe(Topic(g, g, groups[g])))
        if any(g.startswith("처분") for g in groups):
            out.append("처분손익은 세법도 손익으로 봅니다. 처분한 종목의 전기 유보가 있으면 추인합니다")
        return out

    def rule_securities(self) -> None:
        s, pl, dv = self.T["securities"], self.T["securities_pl"], self.T["dividend"]
        if pl.exists:
            self.add("securities", "조정 후보", "확실", "유가증권 평가손익을 되돌립니다(유보)", guide=["2-3-1-1", "2-3-1-2"],
                     topics=["securities", "securities_pl"], amounts=s if s.exists else pl,
                     basis=[describe(s), *self.pl_lines(pl)], papers=[], forms=["15", "50을"],
                     questions=["유가증권 명세(종목 · 취득가액 · 기말 평가액 · 지분율)를 보내 주십시오"])
        elif s.exists:
            self.add("securities", "조정 후보", "자료 필요", "유가증권 증감과 평가 여부를 확인합니다", guide=["2-3-1-1"],
                     topics=["securities"], basis=[describe(s), f"계정 상태 {s.status()}"], papers=[], forms=["15", "50을"],
                     questions=["유가증권 명세(종목 · 취득가액 · 기말 평가액 · 지분율)를 보내 주십시오"])
        foreign = [a for a in s.accounts if re.search(r"해외|국외|외국", clean(a.get("name")))]
        if foreign and "securities" in self.issues:
            iss = self.issues["securities"]
            iss["basis"].append(f"해외 투자 계정 {' · '.join(clean(a.get('name')) for a in foreign)}. 해외현지법인명세서 · 50호(병) 대상인지 확인합니다")
            iss["guide"] += [g for g in ("2-3-1-4",) if g not in iss["guide"]]
            iss["forms"] += [f for f in ("해외현지법인명세서", "50병") if f not in iss["forms"]]
            iss["questions"].append("해외 투자처의 국가 · 지분율과 해외직접투자 신고 여부를 알려 주십시오")
            iss.setdefault("law_extra", []).append("foreign_investment")
        if dv.exists:
            fund, total = self.fund_dividends(dv)
            fund_line = (f"배당금수익 {fund.n}줄 {won(fund.amount)}원은 같은 전표에 원천징수(선납세금) · 금융상품 만기 원금 · "
                         f"재투자가 있거나 적요에 펀드 · 분배 · 만기 표기가 있어({' · '.join(fund.words[:5])}) 펀드 · 신탁 분배금으로 "
                         "보고 수입배당금 익금불산입 후보에서 뺐습니다")
            if fund and fund.amount >= total:
                self.fund_note = fund_line + ". 원천납부세액명세서(10호 갑)에는 들어갑니다"
                return
            basis = [describe(dv)]
            if fund:
                basis.append(f"{fund_line}. 남은 후보 {won(total - fund.amount)}원")
            iss = self.add("dividend", "조정 후보", "가능", "수입배당금 익금불산입(16호의2)을 확인합니다", guide=["2-3-1-3"],
                           topics=["dividend"], basis=basis, papers=[], forms=["16의2"],
                           questions=["배당을 준 회사와 출자 지분율, 조합 출자금 배당인지 알려 주십시오"])
            if fund:
                iss.setdefault("law_extra", []).append("dividend_fund")

    def fund_dividends(self, dv: Topic) -> tuple[Hits, int]:
        """배당금수익 대변 줄 가운데 펀드 · 신탁 분배금으로 보이는 줄과 대변 합계(5회차, 은행 · 증권 계좌 분배금 오탐).

        신호(하나면 충분): ① 같은 전표 차변에 선납세금이 있고 이자수익 줄은 없음(내국법인이 법인에 주는 배당은 원천징수 대상이
        아니고 투자신탁이익은 대상이다, 법인세법 제73조 제1항) ② 같은 전표에 유가증권 · 금융상품 계정 대변(만기 · 환매 원금)
        ③ 배당 줄 적요에 펀드 · 분배 · 만기 표기, 또는 같은 전표 줄 적요에 재투자. 같은 전표의 금융상품 차변(매수)만으로는 세지 않는다.
        """
        tax = set(self.T["prepaid_tax"].codes)
        interest = set(self.T["interest_income"].codes)
        sec = set(self.T["securities"].codes)
        fund, total = Hits(), 0
        for r in self.lines_of(dv.codes):
            if r["credit"] <= 0:
                continue
            total += r["credit"]
            others = [o for o in self.voucher_of(r) if o is not r]
            words = []
            if any(o["account"] in tax and o["debit"] > 0 for o in others) and not any(o["account"] in interest for o in others):
                words.append("원천징수")
            if any(o["credit"] > 0 and (o["account"] in sec or RX_FIN_PRODUCT.search(self.name_of(o))) for o in others):
                words.append("금융상품 원금 회수")
            words += [m.group(0) for m in RX_FUND.finditer(str(r.get("memo") or ""))]
            if any("재투자" in str(o.get("memo") or "") for o in others):
                words.append("재투자")
            if words:
                fund.add({"debit": r["credit"], "credit": 0}, words)
        return fund, total

    def fx_translation(self) -> tuple[Hits, Hits, list[str], int]:
        """외환차익 · 외환차손 계정 줄 가운데 기말 환산 줄(조서 15 외화환산 is_translation 과 같은 판별).
        (환산 줄, 기중 「환산」 표기 줄 중 환산분으로 안 본 줄, 계정 코드, 순액(이익 - 손실))."""
        from ctax.wp.papers import fx as FX
        fy_end = str(self.info.get("fy_end") or (f"{self.info.get('fy')}-12-31" if self.info.get("fy") else ""))
        codes = {str(a.get("code")): a for a in self.accounts if a.get("class") in ("수익", "비용")
                 and FX.SETTLE.search(clean(a.get("name"))) and not FX.FX_PL.search(clean(a.get("name")))}
        hit, mid, used, net = Hits(), Hits(), [], 0
        for r in self.J:
            a = codes.get(r["account"])
            if a is None:
                continue
            memo = str(r.get("memo") or "")
            words = [m.group(0) for m in re.finditer(r"기말|환산|평가|결산|기준\s*환율|환율\s*적용", memo)]
            if FX.is_translation(memo, r.get("date"), fy_end):
                hit.add(r, words)
                net += (r["credit"] - r["debit"]) if a.get("class") == "수익" else -(r["debit"] - r["credit"])
                if r["account"] not in used:
                    used.append(r["account"])
            elif "환산" in memo:
                mid.add(r, ["환산"])
        return hit, mid, used, net

    def rule_fx(self) -> None:
        t = self.T["fx"]
        hit, mid, used, net = self.fx_translation()
        if not (t.exists or hit):
            return
        basis = [describe(t)] if t.exists else []
        if hit:
            basis.append("외환차익 · 외환차손 계정 " + hit.text("기말 환산(날짜 · 적요)")
                         + f". 기말 외화 환산손익으로 보고 조서 15 외화환산에 넣었습니다(순액 {won(net)}원)")
        if mid:
            basis.append(f"기중 날짜의 외환차손익 줄 가운데 적요에 환산 표기가 있는 {mid.n}줄 {won(mid.amount)}원은 거래일 차손익으로 보고 넣지 않았습니다")
        title = ("외화환산손익을 신고한 평가방법에 맞춥니다(40호)" if t.exists
                 else "외환차손익 계정에 기말 외화 환산손익이 있습니다. 신고한 평가방법에 맞춥니다(40호)")
        q = ["외화 평가방법 신고 여부를 알려 주십시오"]
        if hit:
            q.append("외환차익 · 외환차손 계정의 기말 줄이 외화예금 · 외화 채권 · 채무의 기말 환산인지 알려 주십시오")
        self.add("fx", "조정 후보", "가능", title, guide=["2-1"], topics=["fx"] if t.exists else (), accounts=used,
                 amounts=None if t.exists else {"current": net}, basis=basis, papers=[], forms=["40갑", "40을"], questions=q)

    def rule_depreciation(self) -> None:
        tg, it, dep, am, acc = (self.T[k] for k in ("tangible", "intangible", "depreciation", "amortization", "accum_dep"))
        if not (tg.exists or it.exists or dep.exists or am.exists or acc.exists):
            return
        basis = [describe(x) for x in (tg, it, dep, am) if x.exists]
        if acc.exists and not dep.has_current:
            basis.append("감가상각누계액은 있는데 당기 감가상각비가 없습니다(상각이 끝난 자산이면 정상)")
        forms = []
        names = tg.names + it.names
        if any(not re.search(r"^건물$|구축물", n) for n in tg.names) or (dep.exists and not tg.exists):
            forms.append("20_1")
        if any(re.search(r"^건물$|구축물", n) for n in tg.names) or it.exists:
            forms.append("20_2")
        forms.append("20_4")
        guide = (["2-3-5-1"] if (tg.exists or dep.exists or acc.exists) else []) + (["2-3-8-1"] if (it.exists or am.exists) else [])
        self.add("depreciation", "조정 후보", "가능", "감가상각 시부인을 확인합니다", guide=guide,
                 topics=["tangible", "intangible", "depreciation", "amortization"],
                 amounts=self.agg("depreciation", "amortization"), basis=basis, papers=[], forms=forms,
                 questions=["고정자산대장(취득일 · 취득가액 · 내용연수 · 상각방법)을 보내 주십시오"] if names or dep.exists else [])

    def rule_hidden_advance(self) -> None:
        """가지급금 · 대여금 계정이 아닌 자산 계정(전도금 · 선급금 등)에 가지급 · 가불 적요가 있으면 인정이자 대상인지 본다.
        현금 · 예금 계정 줄과, 같은 전표에 가지급금 · 대여금 계정이 있는 줄(그 계정 거래의 상대 줄)은 뺀다."""
        loan = set(self.T["loan"].codes)
        skip = loan | {str(a.get("code")) for a in self.accounts if RX_CASH_NAME.search(clean(a.get("name")))}
        assets = {str(a.get("code")): a for a in self.accounts if a.get("class") == "자산" and str(a.get("code")) not in skip}
        found: dict[str, Hits] = {}
        for r in self.J:
            if r["account"] not in assets:
                continue
            words = [m.group(0) for m in RX_ADVANCE.finditer(str(r.get("memo") or ""))]
            if not words or any(o["account"] in loan for o in self.voucher_of(r) if o is not r):
                continue
            found.setdefault(r["account"], Hits()).add(r, words)
        for code, h in found.items():
            a = assets[code]
            closing = _int(a.get("closing"))
            if closing <= 0 and h.n < 2:
                continue
            name = clean(a.get("name"))
            self.add(f"advance:{code}", "조정 후보", "가능", f"{name} 계정에 가지급 · 가불 적요가 있습니다. 인정이자 대상인지 확인합니다",
                     guide=["2-3-3-1", "2-3-3-2"], accounts=[code], amounts={"current": closing},
                     basis=[f"{name} 기말 잔액 {won(closing)}원", f"{name} " + h.text("가지급 · 가불"),
                            "인정이자 조서에 이 계정의 가지급 · 가불 적요 거래처를 「확인 필요」 로 넣었습니다. 특수관계인 「예」 를 "
                            "고르면 인정이자를 계산합니다"],
                     papers=["loan_interest"], forms=["19갑", "19을"],
                     questions=[f"{name} 잔액의 상대방(임원 · 직원 · 거래처)과 업무 관련 여부, 약정 이자를 알려 주십시오"])

    def rule_loan_moved(self) -> None:
        """가지급금 · 대여금 계정 대변 줄인데 같은 전표에 현금 · 예금이 없고 다른 채권 · 자산 계정 차변이 있는 전표(돈 없이 옮긴
        「반제처리」, 10-19 평가세트 한 곳). 인정이자 적수 · 다음 해 가지급금 계산에서 빠질 수 있다."""
        loan = set(self.T["loan"].codes)
        if not loan:
            return
        h, moved_to = Hits(), []
        for (day, no), group in self.vouchers.items():
            out = [r for r in group if r["account"] in loan and r["credit"] > 0]
            if not out or any(RX_CASH_NAME.search(self.name_of(r)) for r in group):
                continue
            dest = [r for r in group if r["account"] not in loan and r["debit"] > 0
                    and self.by_code.get(r["account"], {}).get("class") == "자산"]
            if not dest:
                continue
            for r in out:
                h.add({"debit": r["credit"], "credit": 0}, [w for w in [str(r.get("memo") or "")[:12]] if w])
            moved_to += [self.name_of(r) for r in dest if self.name_of(r) not in moved_to]
        if not h or h.amount < 1_000_000:
            return
        self.add("loan_moved", "신고 점검", "가능", "가지급금 · 대여금을 돈 없이 다른 계정으로 옮긴 전표가 있습니다",
                 guide=["2-3-3-1"], accounts=sorted(loan), amounts={"current": h.amount},
                 basis=[f"가지급금 · 대여금 대변 {h.n}줄 {won(h.amount)}원, 같은 전표에 현금 · 예금이 없고 차변은 {' · '.join(moved_to[:4])}",
                        "실제로 돌려받지 않았으면 옮긴 계정 잔액도 가지급금으로 보고 인정이자 · 업무무관 지급이자를 계산합니다"],
                 papers=["loan_interest"], forms=["19갑", "19을"],
                 questions=["가지급금 · 대여금을 다른 계정으로 옮긴 까닭과 그 금액을 실제로 회수했는지 알려 주십시오"])

    def rule_car_disposal(self) -> None:
        """차량 자산 계정 대변과 처분손실 차변이 같은 전표인 차량 처분. 처분손실이 800만원(1년 미만 사업연도는 월할)을 넘으면
        업무용승용차일 때 넘는 금액을 손금불산입하고 다음 사업연도로 넘긴다(법인세법 제27조의2 제4항). 업무용승용차 여부는 회계사가 본다."""
        veh = set(self.T["vehicles"].codes)
        if not veh:
            return
        span = self.fy_dates()
        months = 12
        if span:
            months = max(1, min(12, (span[1].year - span[0].year) * 12 + span[1].month - span[0].month + 1))
        limit = CAR_DISPOSAL_LIMIT * months // 12
        for (day, no), group in self.vouchers.items():
            if not any(r["account"] in veh and r["credit"] > 0 for r in group):
                continue
            loss = sum(r["debit"] - r["credit"] for r in group if "처분손실" in self.name_of(r))
            if loss <= limit:
                continue
            memo = next((str(r.get("memo") or "") for r in group if r.get("memo")), "")
            self.add(f"car_disposal:{day}:{no}", "조정 후보", "가능",
                     "차량 처분손실이 800만원을 넘습니다. 업무용승용차면 넘는 금액을 손금불산입합니다",
                     guide=["2-3-21-1"], accounts=sorted({r["account"] for r in group if r["account"] in veh or "처분손실" in self.name_of(r)}),
                     amounts={"current": loss}, basis=[f"{day} 전표 {no}(적요 「{memo[:30]}」) 차량 처분손실 {won(loss)}원, 한도 {won(limit)}원, "
                                                       f"넘는 금액 {won(loss - limit)}원",
                                                       "조서 4 업무용승용차 「처분손실 적용」 칸이 기본 「부」 라 회계사가 여 · 부를 정합니다"],
                     papers=["business_car"], forms=["29"],
                     questions=["처분한 차량이 개별소비세 과세 승용차인지, 매수인이 특수관계인인지와 처분 당시 시가를 알려 주십시오"])

    # ------------------------------------------------------------ 10-20 AR 5차 규칙

    @staticmethod
    def _subject_parts(subject: str) -> tuple[str, str]:
        """전기 15호 과목 「세금과공과(가상부담금)」 → (「세금과공과」, 「가상부담금」). 괄호가 없으면 (과목, 과목)."""
        s = re.sub(r"\s+", "", str(subject or ""))
        m = re.match(r"^(.*?)\((.+)\)$", s)
        return (clean(m.group(1)), m.group(2)) if m else (clean(s), s)

    def rule_prior_pairs(self) -> None:
        """전기 15호에 같은 과목의 유보 가산 · 차감이 짝으로 있고(당기 계상분 가산 + 전기분 추인 차감) 당기에도 같은 계정 · 적요 거래가
        있으면 당기에도 같은 짝 조정이 생길지 본다(10-20). 전기 유보 추인과 당기분을 조서가 따로 계산하는 과목(PAIR_SKIP)은 뺀다.
        「같은 거래」 는 적요에 괄호 안 낱말(괄호가 없으면 과목 이름)이 든 줄이고, 금액은 과목 이름과 같은 손익 계정 줄만 센다."""
        groups: dict[str, list[dict]] = {}
        for a in self.prior_adj:
            if a.get("disposition") == "유보":
                groups.setdefault(re.sub(r"\s+", "", str(a.get("subject") or "")), []).append(a)
        for subj, adjs in groups.items():
            adds = [a for a in adjs if a.get("side") == "가산"]
            subs = [a for a in adjs if a.get("side") == "차감"]
            if not adds or not subs or subject_key(subj) in PAIR_SKIP:
                continue
            base, word = self._subject_parts(subj)
            if len(word) < 3:
                continue
            hits = [r for r in self.J if word in re.sub(r"\s+", "", str(r.get("memo") or ""))]
            mine = [r for r in hits if base and base in self.name_of(r)
                    and self.by_code.get(r["account"], {}).get("class") in ("비용", "수익")]
            if not mine:
                continue
            add_amt = sum(_int(a.get("amount")) for a in adds)
            sub_amt = sum(_int(a.get("amount")) for a in subs)
            cur = sum(r["debit"] - r["credit"] for r in mine)
            by_acct: dict[str, list[int]] = {}           # 같은 적요의 다른 계정 [차변, 대변]
            for r in hits:
                if all(r is not x for x in mine):
                    e = by_acct.setdefault(self.name_of(r), [0, 0])
                    e[0] += r["debit"]
                    e[1] += r["credit"]
            key = f"prior_pair:{subj}"
            basis = [f"전기 15호 {subj} 가산 {won(add_amt)}원 유보 · 차감 {won(sub_amt)}원 유보(당기분 계상 · 전기분 추인 짝)",
                     f"당기 {' · '.join(dict.fromkeys(self.name_of(r) for r in mine))} 적요에 「{word}」 {len(mine)}줄 {won(cur)}원"]
            basis += [f"같은 적요의 {k} 차변 {won(dr)}원 · 대변 {won(cr)}원" for k, (dr, cr) in list(by_acct.items())[:3]]
            if any(abs(dr - add_amt) <= 1000 or abs(cr - add_amt) <= 1000 for dr, cr in by_acct.values()):
                basis.append(f"전기 가산(유보) {won(add_amt)}원과 같은 금액이 당기에 다른 계정에서 정리됐습니다(전기분 지급 · 추인 대상)")
            self.add(key, "전기 연속", "가능", f"전기 {subj} 유보 가산 · 차감 짝 조정이 당기에도 이어질 수 있습니다", guide=["1-3"],
                     accounts=sorted({r["account"] for r in mine}),
                     amounts={"prior": add_amt, "current": cur, "change": cur - add_amt}, basis=basis,
                     prior_treatment=f"전기 15호 {subj} 가산 {won(add_amt)}원 유보 · 차감 {won(sub_amt)}원 유보",
                     papers=["reserve_50", "summary_15"], forms=["15", "50을"],
                     questions=[f"당기 말 미지급으로 계상한 {word}과 전기분 지급 내역(지급일 · 금액)을 알려 주십시오"],
                     todo=["조서 「소득금액조정」 전기 조정 대조 표에서 이 짝이 「당기 반영」 O 로 들어갔는지 봅니다(설정 · 추인 금액을 찾으면 "
                           "기본값이 O). 들어가지 않았으면 「당기 금액」 을 넣고 O 로 바꾼 뒤 ctax wp 를 다시 돌립니다"])
            for a in adjs:
                self.pair_adj[id(a)] = key
            self.pair_res[base] = key
            self.pair_res[subj] = key

    def rule_prior_donation_other(self) -> None:
        """전기 22호에서 그 밖의 기부금(코드 50)으로 적은 적요가 당기 기부금 전표에 다시 나오면 당기 조서가 일반기부금으로 두지 않게
        본다(10-20). 줄 잇기는 기부금 조서(wp donation.match_prior_other)와 같고, 조서 분류 기본값도 「비지정」 이 된다."""
        t = self.T["donation"]
        if not t.codes:
            return
        try:
            from ctax.wp.papers.donation import match_prior_other, prior_other
        except Exception:                                # noqa: BLE001 (조서 패키지가 깨져도 AR 은 돈다)
            return
        others = prior_other(self.P)
        if not others:
            return
        hits = Hits()
        for r in self.lines_of(t.codes):
            if r["debit"] - r["credit"] <= 0:
                continue
            got = match_prior_other(f"{r.get('partner') or ''} {r.get('memo') or ''}", others)
            if got:
                hits.add(r, [got["core"]])
        if not hits:
            return
        prior_amt = sum(_int(r.get("금액")) for r in others)
        basis = [f"전기 22호 그 밖의 기부금(코드 50) {len(others)}줄 {won(prior_amt)}원(" +
                 " · ".join(dict.fromkeys(r["적요"] for r in others[:4])) + ")",
                 "당기 기부금 " + hits.text("같은 적요"),
                 "기부금 조서 분류 기본값을 「비지정」 으로 두었습니다(일반기부금으로 두면 한도 안에서 손금이 됩니다)"]
        nd = [a for a in self.prior_adj if a.get("side") == "가산" and "비지정" in f"{a.get('subject') or ''}{a.get('note') or ''}"]
        if nd:
            basis.append(f"전기 15호 비지정기부금 손금불산입 {won(sum(_int(a.get('amount')) for a in nd))}원")
        self.add("prior_donation_other", "전기 연속", "확실",
                 "전기 22호에서 그 밖의 기부금으로 적은 기부처 · 적요가 당기 기부금에 다시 있습니다. 일반기부금으로 두지 않는지 확인합니다",
                 guide=["1-3", "2-3-22-1"], accounts=sorted({*t.codes}),
                 amounts={"prior": prior_amt, "current": hits.amount, "change": hits.amount - prior_amt}, basis=basis,
                 prior_treatment=f"전기 22호 그 밖의 기부금 {won(prior_amt)}원", papers=["donation"], forms=["21", "22", "15"],
                 questions=["당기 기부처가 법정 일반기부금 단체인지 기부금 영수증과 단체 지정 근거를 보내 주십시오"])

    def rule_repair_capital(self) -> None:
        """수선비 한 줄이 600만원 이상이고 적요에 공사 · 교체 · 설치 · 개조 같은 말이나 장비 모델명이 있으면 자본적 지출(즉시상각의제)인지
        본다(10-20). 같은 계정 · 거래처 · 적요의 취소 줄을 상계한 뒤에도 600만원 이상인 묶음만. 시행령 제31조 제3항(개별자산별 600만원 미만 ·
        직전 장부가액 5% 미만 · 3년 미만 주기 수선은 손금)은 자산별 금액을 알아야 해서 회계사가 본다."""
        t = self.T["repair"]
        if not t.codes:
            return
        groups: dict[tuple, list[dict]] = {}
        for r in self.lines_of(t.codes):
            core = re.sub(r"[\s\d,X×\-]+$", "", str(r.get("memo") or "").strip())
            groups.setdefault((r["account"], str(r.get("partner") or "").strip(), core), []).append(r)
        found = []
        for (_code, partner, core), rows in groups.items():
            net = sum(r["debit"] - r["credit"] for r in rows)
            top = max((r["debit"] - r["credit"] for r in rows), default=0)
            if net < REPAIR_LIMIT or top < REPAIR_LIMIT:
                continue
            words = [m.group(0) for m in RX_CAPEX_WORD.finditer(core)] + (["모델명"] if RX_MODEL.search(core) else [])
            if words:
                found.append((net, rows[0], partner, core, words))
        if not found:
            return
        found.sort(key=lambda x: -x[0])
        total = sum(x[0] for x in found)
        basis = [f"수선비 600만원 이상 묶음 {len(found)}개 {won(total)}원(적요에 {' · '.join(dict.fromkeys(w for x in found for w in x[4]))})"]
        basis += [f"{x[1].get('date')} {x[2] or '거래처 없음'} 「{x[3][:30]}」 {won(x[0])}원" for x in found[:5]]
        basis.append("자산의 내용연수를 늘리거나 가치를 높인 지출(개조 · 설치 · 증설 등)을 비용으로 적었으면 감가상각비로 보고 시부인합니다")
        self.add("repair_capital", "조정 후보", "가능", "600만원 이상 수선비에 공사 · 교체 · 설치 표기가 있습니다. 자본적 지출(즉시상각의제)인지 확인합니다",
                 guide=["2-3-5-1"], accounts=sorted({x[1]["account"] for x in found}), amounts={"current": total}, basis=basis,
                 papers=["depreciation"], forms=["20_1", "20_4"],
                 questions=["600만원 이상 수선비 가운데 자산의 내용연수를 늘리거나 가치를 높인 지출이 있으면 대상 자산과 금액, "
                            "3년 미만 주기의 정기 수선인지를 알려 주십시오"],
                 todo=["자본적 지출이면 감가상각 조서 해당 자산 묶음의 회사계상 상각비에 더해(즉시상각의제) 시부인을 적용합니다"])

    def rule_legal_fees(self) -> None:
        """지급수수료 · 수수료비용 적요 · 거래처에 변호사 · 법무법인 · 소송 · 형사가 있고 합계가 1천만원 이상이면 법인 업무와 관련된
        소송인지 본다(10-20). 대표자 · 임원 개인 사건 비용을 법인이 내면 업무무관 비용이다."""
        t = self.T["fees"]
        if not t.codes:
            return
        h, lines = Hits(), []
        for r in self.lines_of(t.codes):
            if abs(r["debit"] - r["credit"]) < 10_000:
                continue
            words = [m.group(0) for m in RX_LEGAL.finditer(str(r.get("memo") or ""))]
            words += [m.group(0) for m in RX_LEGAL_FIRM.finditer(str(r.get("partner") or ""))]
            if words:
                h.add(r, words)
                lines.append(r)
        if not h or h.amount < LEGAL_LIMIT:
            return
        partners = list(dict.fromkeys(str(r.get("partner") or "").strip() for r in lines if str(r.get("partner") or "").strip()))
        basis = ["지급수수료 " + h.text("소송 · 변호사")]
        if partners:
            basis.append(f"상대 {' · '.join(partners[:4])}")
        basis.append("법인 업무와 관련 없는 소송(대표자 · 임원 개인 사건 등) 비용은 손금이 아닙니다")
        self.add("legal_fees", "조정 후보", "가능", "지급수수료에 변호사 · 소송 비용이 많습니다. 법인 업무와 관련된 사건인지 확인합니다",
                 guide=["2-1"], accounts=sorted({r["account"] for r in lines}), amounts={"current": h.amount}, basis=basis,
                 papers=["summary_15"], forms=["15"],
                 questions=["소송 · 형사 사건마다 당사자(법인 · 대표자 · 임직원)와 사건 내용, 법인 업무와의 관련을 알려 주십시오"],
                 todo=["업무무관이면 조서 「소득금액조정」 직접 조정 줄에 손금불산입(상여 등)으로 넣습니다"])

    def rule_prior_period_pl(self) -> None:
        """잡이익 · 잡손실 같은 영업외 손익 계정 적요에 전기오류 · 전기분 수정 표기가 있으면 귀속 사업연도를 본다(10-20).
        전기오류수정손익 · 잉여금 계정은 rule_misc_accounts(prior_error)가 본다."""
        skip = set(self.T["prior_error"].codes)
        codes = [str(a.get("code")) for a in self.accounts if a.get("code") and str(a.get("code")) not in skip
                 and a.get("class") in ("수익", "비용")
                 and ("영업외" in str(a.get("section") or "") or re.search(r"잡이익|잡손실", clean(a.get("name"))))]
        h = self.scan(codes, RX_PRIOR_FIX)
        if not h or abs(h.amount) < PRIOR_FIX_MIN:
            return
        lines = [r for r in self.lines_of(codes) if RX_PRIOR_FIX.search(str(r.get("memo") or ""))]
        shown = []
        for r in sorted(lines, key=lambda r: -abs(r["debit"] - r["credit"]))[:4]:
            other = [self.name_of(o) for o in self.voucher_of(r) if o is not r]
            shown.append(f"{r.get('date')} 전표 {r.get('no')} {self.name_of(r)} {'대변' if r['credit'] else '차변'} "
                         f"{won(abs(r['debit'] - r['credit']))}원(적요 「{str(r.get('memo') or '')[:30]}」, "
                         f"상대 {' · '.join(dict.fromkeys(other[:3])) or '없음'})")
        self.add("prior_period_pl", "조정 후보", "가능",
                 "영업외 손익 계정에 전기오류 · 전기분 수정 전표가 있습니다. 귀속 사업연도를 확인합니다", guide=["2-3-18-1"],
                 accounts=sorted({r["account"] for r in lines}), amounts={"current": abs(h.amount)},
                 basis=[h.text("전기오류 · 전기분 수정"), *shown,
                        "전기 손익을 당기 손익으로 고쳤으면 당기에는 익금불산입 · 손금불산입하고 그 사업연도 신고를 고칩니다"],
                 papers=["summary_15"], forms=["15"],
                 questions=["전기오류를 고친 거래의 원래 사업연도와 내용(누락 · 과대 계상)을 알려 주십시오"],
                 todo=["전기 귀속이면 조서 「소득금액조정」 직접 조정 줄에 넣고, 그 사업연도 수정신고 · 경정청구를 회사와 정합니다"])

    def rule_officer_bonus(self) -> None:
        """임원급여(상여) 월별 금액에서 한 달이 평월(중앙값)의 두 배를 넘으면 임원 상여 지급기준을 본다(10-20).
        법인세법 시행령 제43조 제2항: 정관 · 주주총회 · 이사회 결의 지급기준을 넘는 임원 상여는 손금불산입."""
        t = self.T["officer_pay"]
        if not t.codes:
            return
        months: dict[str, int] = {}
        for r in self.lines_of(t.codes):
            m = str(r.get("date") or "")[:7]
            months[m] = months.get(m, 0) + r["debit"] - r["credit"]
        pos = sorted(v for v in months.values() if v > 0)
        if len(pos) < 6:
            return
        mid = pos[len(pos) // 2] if len(pos) % 2 else (pos[len(pos) // 2 - 1] + pos[len(pos) // 2]) // 2
        big = {m: v for m, v in sorted(months.items()) if mid > 0 and v > mid * OFFICER_RATIO}
        if not big:
            return
        excess = sum(v - mid for v in big.values())
        bonus = self.scan(t.codes, re.compile(r"상여|성과급|보너스"))
        basis = [describe(t), f"월별 평월(중앙값) {won(mid)}원, " +
                 " · ".join(f"{m[5:7].lstrip('0')}월 {won(v)}원(평월의 {v / mid:.1f}배)" for m, v in big.items()),
                 f"평월을 넘는 금액 {won(excess)}원"]
        if bonus:
            basis.append(bonus.text("상여"))
        self.add("officer_bonus", "조정 후보", "가능", "임원급여가 한 달에 평월의 두 배를 넘습니다. 임원 상여 지급기준을 확인합니다",
                 guide=["2-3-13-1"], accounts=t.codes, amounts={"current": excess}, basis=basis, papers=["summary_15"], forms=["15"],
                 questions=["정관 · 주주총회 · 이사회 결의로 정한 임원 보수 · 상여 지급기준과 그 달 지급분의 성격(상여 · 인상 · 소급)을 보내 주십시오"],
                 todo=["지급기준을 넘는 상여면 조서 「소득금액조정」 직접 조정 줄에 손금불산입(상여)으로 넣습니다"])

    def rule_dep_missing(self) -> None:
        """당기에 취득한 유형 · 무형자산인데 당기 상각비가 0 인 자산 묶음. 묶음 · 취득 · 상각 가르기는 감가상각 조서
        (wp depreciation.additions_without_dep)와 같다(10-20). 감가상각은 결산에 계상해야 손금이라 상각 누락이면 시인부족이 된다."""
        try:
            from ctax.wp.papers.depreciation import additions_without_dep
            got = additions_without_dep(self.books())
        except Exception:                                # noqa: BLE001 (조서 패키지가 깨져도 AR 은 돈다)
            return
        if not got:
            return
        total = sum(g["additions"] for g in got)
        basis = [f"{g['group']} 당기 취득 {won(g['additions'])}원(첫 취득 {g['first']}, 사용 {g['months']}개월), 당기 상각비 0원" for g in got[:5]]
        basis.append("감가상각비는 결산에 계상한 금액만 한도 안에서 손금입니다. 상각을 빠뜨렸으면 시인부족액이 생기고 이월되지 않습니다")
        self.add("dep_missing", "조정 후보", "가능", "당기에 취득한 자산의 감가상각비가 없습니다. 결산 상각 누락인지 확인합니다",
                 guide=["2-3-5-1"], accounts=[g["asset_code"] for g in got], amounts={"current": total}, basis=basis,
                 papers=["depreciation"], forms=["20_1", "20_4"],
                 questions=["당기 취득 자산의 사업 사용 시작일과 결산에서 감가상각을 하지 않은 까닭을 알려 주십시오"])

    def books(self):
        """조서(wp)의 Books 꼴로 바꾼 장부 · 전표. 조서와 같은 계산을 AR 이 재사용할 때 쓴다(10-20). 가져오지 못하면 예외."""
        if not hasattr(self, "_books"):
            from ctax.wp.books import Books, Line
            lines = [Line(str(r.get("date") or ""), str(r.get("no") or ""), str(r.get("kind") or ""), r["account"],
                          str(r.get("account_name") or ""), r["debit"], r["credit"], str(r.get("partner_code") or ""),
                          str(r.get("partner") or ""), str(r.get("memo") or "")) for r in self.J]
            info = dict(self.info)
            span = self.fy_dates()
            if span:                                     # 신고건.json 에 사업연도 날짜가 없으면 연도로 채운다(월할 계산)
                info.setdefault("fy_start", span[0].isoformat())
                info.setdefault("fy_end", span[1].isoformat())
            self._books = Books(self.L, lines, self.P, None, info, {})
        return self._books

    def rule_interim(self) -> None:
        """직전 사업연도 산출세액으로 계산한 중간예납세액이 있어 중간예납 대상인데 당기 선납세금 · 법인세등 · 미지급세금 전표에 중간예납이
        없으면(조서 3호 22 가 0) 가결산 신고 여부 · 미납 고지를 본다(10-20 회계사 검토). 중간예납 줄 가르기는 조서
        (wp summary.prepaid_rows)와 같다. 직전 기준 금액 = (산출세액 + 가산세 - 공제감면 - 원천납부 - 수시부과) × 6 / 12,
        직전 중소기업이 50만원 미만이면 의무가 없다(법인세법 제63조 제1항 제2호)."""
        c3 = self.cells3
        if not self.has_prior or self.P.get("no_prior") or not c3:
            return
        span = self.fy_dates()
        if span and (span[1] - span[0]).days < 183:
            return
        a = _int(c3.get("12")) + _int(c3.get("20"))
        b = _int(c3.get("17")) + _int(c3.get("19"))
        c, d = _int(c3.get("24")), _int(c3.get("25"))
        est = max(0, a - b - c - d) * 6 // 12
        if est <= 0 or (self.sme is True and est < 500_000):
            return
        try:
            from ctax.wp.summary import prepaid_rows
            pre = prepaid_rows(self.books())
        except Exception:                                # noqa: BLE001
            return
        if pre["interim"] > 0:
            return
        basis = [f"전기 3호 산출세액 {won(_int(c3.get('12')))}원 · 가산세 {won(_int(c3.get('20')))}원 · 공제감면 {won(b)}원 · "
                 f"원천납부 {won(c)}원" + (f" · 수시부과 {won(d)}원" if d else ""),
                 f"직전 사업연도 기준 중간예납세액(추정) {won(est)}원(× 6 / 12)",
                 "당기 선납세금 · 법인세등 · 미지급세금 차변에 중간예납 줄(적요 「중간예납」 · 납부 달 추정)이 없어 3호 22 가 0원입니다"]
        if _int(c3.get("22")):
            basis.append(f"전기에는 중간예납 {won(_int(c3.get('22')))}원을 냈습니다(전기 3호 22)")
        self.add("interim_missing", "신고 점검", "가능",
                 "직전 사업연도 산출세액이 있어 중간예납 대상인데 당기 중간예납 납부 전표가 없습니다. 가결산 신고 · 미납 고지를 확인합니다",
                 guide=["2-1"], amounts={"prior": est}, basis=basis, papers=["tax_3"], forms=["3"],
                 questions=["당기 중간예납을 가결산(중간예납기간 실적)으로 신고했는지, 내지 않아 고지서를 받았는지 알려 주십시오",
                            "중간예납을 다른 계정(가지급금 · 미지급금 · 대표자 개인 납부 등)으로 처리했으면 그 전표를 알려 주십시오"],
                 todo=["중간예납을 냈으면 납부서로 금액을 확인해 조서 3호 22 노란 칸에 넣고 ctax wp 를 다시 돌립니다"])

    def rule_construction(self) -> None:
        """건설업(전기 51호 업태 · 업종코드 45, 또는 매출 계정 이름에 공사 · 도급)인데 공사매출이 있고 기말 미완성공사 · 계약자산이
        없으면 작업진행률 기준으로 손익을 나눴는지 본다(10-20, 법인세법 시행령 제69조 제1항)."""
        rev = [a for a in self.T["revenue"].accounts if RX_CONSTRUCTION_REV.search(clean(a.get("name"))) and _int(a.get("amount")) > 0]
        biz = f"{self.company.get('biz_type') or ''} {self.company.get('item') or ''}"
        is_cons = bool(RX_CONSTRUCTION.search(biz)) or str(self.company.get("industry_code") or "").startswith("45")
        if not rev and not is_cons:
            return
        amount = sum(_int(a.get("amount")) for a in rev) if rev else self.T["revenue"].current
        ca = self.T["contract_asset"]
        if amount <= 0 or any(_int(a.get("closing")) > 0 for a in ca.accounts):
            return
        basis = [f"{' · '.join(clean(a.get('name')) for a in rev) or '매출액'} {won(amount)}원" +
                 (f"(전기 51호 업태 「{self.company.get('biz_type')}」)" if is_cons and self.company.get("biz_type") else "")]
        if ca.accounts:
            basis.append(f"{' · '.join(ca.names)} 기말 0원(기중 차변 {won(ca.debit)}원 · 대변 {won(ca.credit)}원)")
        else:
            basis.append("미완성공사 · 계약자산 · 미청구공사 계정이 없습니다")
        basis.append("사업연도를 넘기는 공사는 작업진행률로 익금 · 손금을 나눕니다. 중소기업의 1년 미만 공사와 기업회계기준으로 인도기준을 "
                     "쓴 경우는 인도일 기준을 쓸 수 있습니다")
        self.add("construction_progress", "조정 후보", "가능",
                 "공사매출이 있는데 기말 미완성공사 · 계약자산이 없습니다. 작업진행률 기준 손익 귀속을 확인합니다", guide=["2-1"],
                 accounts=[a["code"] for a in rev] + ca.codes, amounts={"current": amount}, basis=basis, papers=["summary_15"],
                 forms=["15"],
                 questions=["기말 현재 진행 중인 공사의 계약금액 · 총공사예정원가 · 누적 발생원가 · 누적 청구액과 계약기간을 알려 주십시오"],
                 todo=["진행 중 공사가 있으면 작업진행률로 계산한 수익 · 원가와 장부의 차이를 조서 「소득금액조정」 직접 조정 줄(유보)에 넣습니다"])

    def rule_misc_accounts(self) -> None:
        simple = [
            ("prior_error", "전기오류수정손익의 세무조정을 확인합니다", ["2-3-18-1"], ["15", "50을"],
             "전기오류수정 내용(어느 해 무엇을 고쳤는지)을 알려 주십시오"),
            ("grant", "국고보조금 일시상각충당금 설정 대상인지 확인합니다", ["2-3-7-1"], ["35", "36"],
             "보조금 교부 결정 통지서와 그 돈으로 산 자산을 알려 주십시오"),
            ("donation_gain", "자산수증이익 · 채무면제이익의 이월결손금 보전을 확인합니다", ["2-3-19-1"], ["15", "50갑"],
             "자산을 받거나 채무를 면제받은 상대방과 내용을 알려 주십시오"),
            ("inventory_loss", "재고자산감모손실의 실제 감모 여부를 확인합니다", ["2-3-20-1"], ["15"],
             "재고 실사표와 감모 사유를 보내 주십시오"),
            ("convertible", "전환사채 · 신주인수권부사채 세무조정을 확인합니다", ["2-3-10-1"], ["15", "50을"],
             "사채 발행 조건(전환가액 · 상환할증률)을 보내 주십시오"),
        ]
        for key, title, guide, forms, q in simple:
            t = self.T[key]
            if t.exists:
                amounts = self.period_amounts(t)
                basis = [describe(t), state(t)]
                if not isinstance(amounts, Topic):
                    basis.append(f"기말 잔액이 0원이라 기중 금액 {won(amounts['current'])}원을 이슈 금액으로 씁니다")
                self.add(key, "조정 후보", "가능", title, guide=guide, topics=[key], amounts=amounts, basis=basis, papers=[],
                         forms=forms, questions=[q])
        pe = self.T["prior_error"]
        for r in self.lines_of(pe.codes):
            texts = [str(r.get("memo") or "")] + [f"{self.name_of(o)} {o.get('memo') or ''}" for o in self.voucher_of(r)
                                                  if o is not r and o["account"] not in set(pe.codes)]
            self.fix_texts.append(" ".join(texts))
        eo = self.T["equity_other"]
        if eo.exists and eo.change != 0:
            self.add("equity_other", "조정 후보", "가능",
                     (FIRST_YEAR if self.first_year else "자본 항목이 바뀌었습니다. ") + "자본 거래의 세무조정을 확인합니다",
                     guide=["2-3-12-1"], topics=["equity_other"], basis=[describe(eo)], papers=[], forms=["15", "54"],
                     questions=["자기주식 취득 · 처분, 감자 같은 자본 거래가 있었으면 내용을 알려 주십시오"])

    # ------------------------------------------------------------ 공제감면

    def rule_credits(self) -> None:
        profit = self.ibt > 0
        has_reduction = False
        for c in self.prior_credits:
            name = str(c.get("name") or c.get("code") or "")
            amt, cf = _int(c.get("amount")), _int(c.get("carryforward"))
            base = f"전기 {name} {won(amt)}원" + (f", 이월 {won(cf)}원" if cf else "")
            key = f"credit:{name}"
            if cf > 0:
                self.add(key, "공제감면", "확실", f"전기에서 넘어온 이월세액공제가 있습니다({name})", guide=["1-4"],
                         amounts={"prior": cf}, basis=[base], papers=[], forms=["8을", "8부표3", "8갑", "4"], questions=[])
            elif re.search(r"중소기업.*감면|특별세액감면", name):
                has_reduction = True
                if profit:
                    self.add(key, "공제감면", "가능", "중소기업 특별세액감면을 당기에도 적용할지 확인합니다", guide=["1-4"],
                             amounts={"prior": amt}, basis=[base, f"당기 법인세차감전이익 {won(self.ibt)}원"], papers=[],
                             forms=["조특2", "8부표2", "8갑", "4"], questions=["올해 업종 · 사업장 소재지가 바뀌었으면 알려 주십시오"])
            elif re.search(r"창업", name):
                has_reduction = True
                if profit:
                    self.add(key, "공제감면", "가능", "창업중소기업 감면 기간 안인지 확인합니다", guide=["1-4"], amounts={"prior": amt},
                             basis=[base], papers=[], forms=["조특2의2", "조특2", "8부표2", "48"], questions=[])
            elif re.search(r"연구|인력개발", name):
                if self.T["rnd"].exists:
                    continue                 # rule 아래 rnd_credit 이 전기 공제 사실과 함께 낸다
                self.add(key, "공제감면", "자료 필요", "전기 연구 · 인력개발비 세액공제를 당기에도 받을지 확인합니다", guide=["1-4"],
                         amounts={"prior": amt}, basis=[base], papers=[], forms=["조특3_1", "조특3부표_1", "조특1", "8갑", "8부표3"],
                         questions=["연구소 · 전담부서 인정서와 연구원 인건비 명세를 보내 주십시오"])
            elif re.search(r"고용|사회보험료", name):
                self.add(key, "공제감면", "자료 필요", f"전기 {name} 사후관리(인원 감소 추징)와 추가 공제를 확인합니다", guide=["1-4"],
                         amounts={"prior": amt}, basis=[base], papers=[], forms=["조특10의9", "조특10의10", "조특1", "8갑", "8부표3"],
                         questions=["올해와 작년 월별 상시근로자 수(4대보험 가입자 명부)를 보내 주십시오"])
            elif re.search(r"투자", name):
                self.add(key, "공제감면", "자료 필요", f"전기 {name}의 당기 해당 여부를 확인합니다", guide=["1-4"], amounts={"prior": amt},
                         basis=[base], papers=[], forms=["조특8의9", "조특1부표", "조특1", "8갑"], questions=[])
            elif amt:
                self.add(key, "공제감면", "자료 필요", f"전기 {name}의 당기 해당 여부를 확인합니다", guide=["1-4"], amounts={"prior": amt},
                         basis=[base], papers=[], forms=["8갑"], questions=[])
        if self.sme is True and profit and not has_reduction:
            extra = ([f"임대 · 이자 · 배당 수입이 매출액의 {self.rent_share():.0%}입니다. 부동산임대업은 감면 업종 목록에 없고, "
                      "시행령 제42조 제2항 요건을 모두 갖춘 법인은 중소기업에서 빠질 수 있습니다"]
                     if self.rent_share() >= 0.5 else [])
            self.add("sme_reduction", "공제감면", "가능", "중소기업 특별세액감면 대상 업종 · 지역인지 확인합니다", guide=["1-1"],
                     amounts={"current": self.ibt},
                     basis=[f"{INFO_SME}에 중소기업으로 적혀 있습니다" if self.P.get("no_prior") else "전기 중소기업으로 신고",
                            f"당기 법인세차감전이익 {won(self.ibt)}원",
                            NO_PRIOR_FACT if self.P.get("no_prior") else "전기에 감면을 받지 않았습니다", *extra],
                     papers=[], forms=["조특2", "8부표2"],
                     questions=["주된 업종과 사업장 소재지(수도권 여부), 상시근로자 수를 알려 주십시오"])
        pay = self.T["payroll"]
        if pay.exists and pay.change > 0:
            self.add("employment_credit", "공제감면", "자료 필요",
                     (FIRST_YEAR if self.first_year else "급여가 늘었습니다. ") + "통합고용세액공제 대상인지 상시근로자 수로 확인합니다",
                     guide=["2-3-13-1"], topics=["payroll"], basis=[describe(pay), describe(self.T["welfare"])], papers=[],
                     forms=["조특10의9", "조특10의10", "조특1", "8갑", "8부표3"],
                     questions=["올해 월별 상시근로자 수(4대보험 가입자 명부)를 보내 주십시오" if self.first_year
                                else "올해와 작년 월별 상시근로자 수(4대보험 가입자 명부)를 보내 주십시오"])
        cap = self.T["capex"]
        if cap.exists and cap.change > 0:
            self.add("investment_credit", "공제감면", "자료 필요",
                     (FIRST_YEAR if self.first_year else "사업용 유형자산이 늘었습니다. ") + "통합투자세액공제 대상인지 확인합니다",
                     guide=["2-3-6-1"], topics=["capex"], basis=[describe(cap)], papers=[], forms=["조특8의9", "조특1부표", "조특1", "8갑"],
                     questions=["올해 취득한 기계장치 · 시설 · 건설기계의 취득일 · 금액 · 용도를 알려 주십시오"])
        rnd = self.T["rnd"]
        if rnd.exists:
            prior_rnd = [c for c in self.prior_credits if re.search(r"연구|인력개발", str(c.get("name") or ""))]
            basis = [describe(rnd)] + [f"전기에 {c.get('name')} {won(_int(c.get('amount')))}원을 받았습니다" for c in prior_rnd]
            self.add("rnd_credit", "공제감면", "가능" if (prior_rnd and rnd.has_current) else "자료 필요",
                     "연구 · 인력개발비 세액공제 대상인지 확인합니다",
                     guide=["2-3-14-1", "2-3-14-2"] + (["1-4"] if prior_rnd else []), topics=["rnd"], basis=basis, papers=[],
                     forms=["조특3_1", "조특3부표_1", "조특1", "8갑", "8부표3"],
                     questions=["기업부설연구소 · 연구개발전담부서 인정서가 있으면 보내 주십시오"])

    # ------------------------------------------------------------ 서식 필요(조서 없음)

    def net_interest(self, ii: Topic, pt: Topic) -> tuple[Hits, int] | None:
        """이자수익을 원천징수세액을 뺀 순액으로 적은 신호(5회차). 이자수익 대변 줄 적요에 세금 표기(「이자세금:11,000원」 꼴)가 있고
        같은 전표에 선납세금 · 세금과공과 · 법인세등 줄이 없으면 센다. 환급 · 가산금 표기 줄(국세 환급가산금)은 뺀다.
        적요의 세금 표기 뒤 「n원」 은 회사가 적은 원천징수세액으로 보고 더한다."""
        if ii.current <= 0:
            return None
        tax_codes = set(pt.codes) | set(self.T["taxes"].codes) | set(self.T["corp_tax"].codes)
        hits, tax = Hits(), 0
        for r in self.lines_of(ii.codes):
            memo = str(r.get("memo") or "")
            words = [m.group(0) for m in RX_INT_TAX.finditer(memo)]
            if r["credit"] <= 0 or not words or re.search(r"환급|가산금", memo):
                continue
            if any(o["account"] in tax_codes for o in self.voucher_of(r) if o is not r):
                continue
            m = RX_WON.search(memo[memo.find(words[0]):])
            amount = int(m.group(1).replace(",", "")) if m else None
            if amount == 0:                      # 「이자세금:0원」 은 원천징수가 없었다는 표기(세액 1천원 미만)
                continue
            hits.add(r, words)
            tax += amount or 0
        return (hits, tax) if hits else None

    def rule_forms_needed(self) -> None:
        ii, pt = self.T["interest_income"], self.T["prepaid_tax"]
        net = self.net_interest(ii, pt)
        if ii.has_current or pt.has_current or pt.touched:
            forms = ["10갑"] + (["지방43의5갑"] if (pt.has_current or pt.touched) else [])
            basis = [describe(ii)] + ([describe(pt)] if pt.exists else [])
            if pt.exists and pt.current == 0 and getattr(pt, "debit", 0):     # 기말 0 은 결산 때 법인세비용으로 대체한 것
                basis.append(f"선납세금 기중 차변 {won(pt.debit)}원(기말 0 원은 결산 때 법인세비용으로 대체한 금액)")
            if self.fund_note:
                basis.append(self.fund_note)
            if ii.current > 0 and not pt.exists and not net:
                basis.append("선납세금 계정이 없습니다. 원천징수된 이자를 받은 돈(세금을 뺀 금액)으로만 적었으면 이자수익에 원천징수세액이 "
                             "빠져 있습니다")
            self.add("withholding", "서식 필요", "확실" if (pt.has_current or pt.touched) else "가능",
                     "원천납부세액명세서(10호 갑)를 작성합니다", guide=["2-3-4-1"], topics=["interest_income", "prepaid_tax"],
                     amounts=self.agg("interest_income", "dividend"), basis=basis, papers=[], forms=forms,
                     questions=["이자 · 배당을 받을 때 원천징수된 세액 명세(금융기관 원천징수영수증)를 보내 주십시오"])
        if net:
            hits, tax = net
            self.add("interest_net", "조정 후보", "가능", "이자수익을 원천징수세액을 뺀 금액으로 적은 것으로 보입니다(익금 · 기납부세액 확인)",
                     guide=["2-3-4-1"], accounts=sorted({*ii.codes}), amounts={"current": tax} if tax else {},
                     basis=[f"이자수익 줄 가운데 적요에 세금 표기가 있고 같은 전표에 선납세금 · 세금 계정이 없는 줄 {hits.n}줄 "
                            f"{won(-hits.amount)}원({' · '.join(hits.words[:4])})",
                            *([f"그 적요에 적힌 금액 합계 {won(tax)}원"] if tax else []),
                            "선납세금 계정이 없습니다" if not pt.exists else describe(pt),
                            "원천징수세액만큼 이자수익(익금)이 빠지고 10호(갑) 기납부세액에서도 빠질 수 있습니다"],
                     papers=["summary_15", "tax_3"], forms=["10갑", "지방43의5갑", "15"],
                     questions=["이 이자의 금융기관 원천징수영수증(이자 총액 · 원천징수세액)을 보내 주십시오"],
                     todo=["원천징수영수증으로 세액을 확인해 조서 「소득금액조정」 직접 조정 줄(익금산입)과 「과세표준 · 세액」 원천납부세액 칸에 "
                           "넣고 ctax wp 를 다시 돌립니다"])
        cogs = [a for a in self.accounts if 501 <= code3(a.get("code", "")) <= 799 and _int(a.get("amount"))]
        if cogs:
            self.add("cogs", "서식 필요", "확실", "제조 · 공사 원가 계정이 있어 원가명세서(표준 부속명세서)를 작성합니다", guide=["2-1"],
                     accounts=[a["code"] for a in cogs], amounts={"current": sum(_int(a.get("amount")) for a in cogs)},
                     basis=[f"500~700번대 원가 계정 {len(cogs)}개"], papers=[], forms=["std_cogs"], questions=[])
        cap, sp = self.T["capital"], self.T["share_premium"]
        if cap.change or sp.change:
            self.add("share_change", "서식 필요", "확실",
                     FIRST_YEAR + "주식등변동상황명세서(54호)에 설립 때 발행한 주식과 주주를 적습니다" if self.first_year
                     else "자본금이 바뀌었습니다. 주식등변동상황명세서(54호)에 증자 · 감자를 반영합니다",
                     guide=["1-2", "2-3-11-1"], topics=["capital", "share_premium"], basis=[describe(cap), describe(sp)], papers=[],
                     forms=["54"], questions=["법인 등기부등본과 주주명부를 보내 주십시오" if self.first_year
                                              else "증자 · 감자 등기부등본과 주주명부를 보내 주십시오"])
        self.add("share_transfer", "서식 필요", "자료 필요", "주주 사이 주식 양도가 있었는지 확인합니다", guide=["2-3-11-2"],
                 amounts={}, basis=[describe(cap)], papers=[], forms=["54", "54부표"],
                 questions=["올해 주주 사이 주식 양도 · 증여가 있었으면 주주명부와 양도 계약서를 보내 주십시오"])
        rev_prior = _int(self.prior_totals.get("revenue")) or self.T["revenue"].prior
        if rev_prior >= EXPENSE_EVIDENCE_REVENUE:
            self.add("expense_evidence", "서식 필요", "확실", "직전 수입금액이 30억 원 이상입니다. 지출증명서류 합계표(77호)를 작성 · 보관합니다",
                     guide=["2-1"], amounts={"prior": rev_prior}, basis=[f"전기 매출액 {won(rev_prior)}원"], papers=[], forms=["77"],
                     questions=[])
        prior_tax = (self.T["corp_tax"].prior > 0 or _int(self.prior_totals.get("corporate_tax")) > 0
                     or any(subject_key(a.get("subject")) == "corp_tax" for a in self.prior_adj))
        if self.sme is True and self.ibt < 0 and prior_tax:
            self.add("carryback", "서식 필요", "가능", "결손이 났습니다. 중소기업 결손금 소급공제(68호)를 신청할지 고릅니다", guide=["1-1"],
                     amounts={"current": self.ibt}, basis=[f"당기 법인세차감전손실 {won(self.ibt)}원", "전기 중소기업 · 전기 법인세등 있음"],
                     papers=[], forms=["68"], questions=["직전 사업연도 법인세를 환급받는 소급공제를 신청할지 알려 주십시오"])

    # ------------------------------------------------------------ 전기 연속

    def rule_prior(self) -> None:
        for a in self.prior_adj:
            subject, amount = str(a.get("subject") or ""), _int(a.get("amount"))
            side, disp = str(a.get("side") or ""), str(a.get("disposition") or "")
            key = subject_key(subject, a.get("note"))
            treat = f"전기 15호 {side} {subject} {won(amount)}원 {disp}".strip()
            base = f"전기 15호 {subject} {won(amount)}원" + (f"({a.get('note')})" if a.get("note") else "")
            pair = self.pair_adj.get(id(a))
            if pair and pair in self.issues:            # 유보 가산 · 차감 짝(rule_prior_pairs, 10-20)
                self.adj_fate.append((a, "짝 조정 반복 예상", pair))
                continue
            if (side == "가산" and self.prior_vat and "nondeductible_vat" in self.issues
                    and (amount == self.prior_vat or RX_NONDEDUCT_VAT.search(f"{subject}{a.get('note') or ''}"))):
                iss = self.issues["nondeductible_vat"]       # 전기 세금공과금명세서 불공제 매입세액 합계와 같은 15호 줄(10-20)
                iss["basis"].append(base + ". 전기 세금공과금명세서 불공제 매입세액 손금불산입 합계와 같습니다")
                iss["prior_treatment"] = "; ".join(x for x in (iss["prior_treatment"], treat) if x)
                self.adj_fate.append((a, "반복 예상", "nondeductible_vat"))
                continue
            if key and key in self.issues and self.issues[key]["kind"] != "신고 점검":
                iss = self.issues[key]
                iss["basis"].append(base)
                iss["prior_treatment"] = "; ".join(x for x in (iss["prior_treatment"], treat) if x)
                if iss["certainty"] in ("가능", "자료 필요") and iss["kind"] == "조정 후보":
                    iss["certainty"] = "확실"
                self.adj_fate.append((a, "반복 예상", key))
                continue
            if key is None:
                k = f"prior:{subject}:{amount}"
                self.add(k, "전기 연속", "자료 필요", f"전기 {subject} 조정을 당기 계정에 잇지 못했습니다", guide=["1-3"],
                         amounts={"prior": amount}, basis=[base], prior_treatment=treat, papers=[], forms=["15"],
                         questions=[])
                self.adj_fate.append((a, "잇지 못함", k))
                continue
            t = self.agg(*KEY_TOPICS.get(key, []))
            alive = (self.corp_tax_amount > 0) if key == "corp_tax" else (t.has_current if t.accounts else False)
            k = f"prior:{key}:{subject}"
            if alive:
                self.add(k, "전기 연속", "가능", f"전기 {subject} 조정이 당기에도 이어질 수 있습니다", guide=["1-3"],
                         topics=KEY_TOPICS.get(key, []), basis=[base, describe(t)], prior_treatment=treat,
                         papers=KEY_PAPERS.get(key, []), forms=["15"] + (["50을"] if disp == "유보" else []), questions=[])
                self.adj_fate.append((a, "반복 예상", k))
            else:
                why = "당기 법인세등 0원" if key == "corp_tax" else (f"{describe(t)}" if t.accounts else "당기에 같은 계정이 없습니다")
                self.add(k, "전기 연속", "확실", f"전기 {subject} 조정 대상이 당기에는 없습니다", guide=["1-3"],
                         topics=KEY_TOPICS.get(key, []), amounts={"prior": amount, "current": 0, "change": -amount},
                         basis=[base, why], prior_treatment=treat,
                         papers=KEY_PAPERS.get(key, []) if disp == "유보" else [], forms=[], questions=[])
                self.adj_fate.append((a, "소멸", k))
        for r in self.prior_res:
            subject, closing = str(r.get("subject") or ""), _int(r.get("closing"))
            key = subject_key(subject)
            line = f"전기 50호(을) {subject} 기말 유보 {won(closing)}원. 당기 추인을 확인합니다"
            pair = self.pair_res.get(re.sub(r"\s+", "", subject)) or self.pair_res.get(clean(subject))
            if pair and pair in self.issues:            # 짝 조정 과목의 유보 잔액은 그 전기 연속 이슈에 붙인다(10-20)
                iss = self.issues[pair]
                iss["basis"].append(line)
                iss["prior_treatment"] = "; ".join(x for x in (iss["prior_treatment"], f"전기 50호(을) {subject} 기말 유보 {won(closing)}원") if x)
                self.adj_fate.append(({"subject": subject, "amount": closing, "side": "유보"}, "추인 확인", pair))
                continue
            if key and key in self.issues and self.issues[key]["kind"] != "신고 점검":
                iss = self.issues[key]
                iss["basis"].append(line)
                if "50을" not in iss["forms"]:
                    iss["forms"].append("50을")
                # 전기 유보가 남아 있으면 당기 추인 조정이 반드시 따른다
                treat = f"전기 50호(을) {subject} 기말 유보 {won(closing)}원"
                if treat not in (iss["prior_treatment"] or ""):
                    iss["prior_treatment"] = "; ".join(x for x in (iss["prior_treatment"], treat) if x)
                if iss["certainty"] in ("가능", "자료 필요") and iss["kind"] == "조정 후보":
                    iss["certainty"] = "확실"
                self.adj_fate.append(({"subject": subject, "amount": closing, "side": "유보"}, "추인 확인", key))
                continue
            # 같은 과목의 「이어질 수 있습니다」 전기 연속 줄에 합친다(소멸 줄은 따로 둔다. 전액 추인이 따로 보여야 한다)
            same = [k for k, v in self.issues.items() if key and k.startswith(f"prior:{key}:") and v["kind"] == "전기 연속"
                    and v["title"].endswith("이어질 수 있습니다")]
            if same:
                iss = self.issues[same[0]]
                iss["basis"].append(line)
                iss["prior_treatment"] = "; ".join(x for x in (iss["prior_treatment"], f"전기 50호(을) {subject} 기말 유보 {won(closing)}원") if x)
                iss["forms"] += [f for f in ("15", "50을") if f not in iss["forms"]]
                iss["papers"] += [x for x in papers_for(f"prior:{key}", ["reserve_50", *KEY_PAPERS.get(key, [])]) if x not in iss["papers"]]
                if iss["title"].endswith("이어질 수 있습니다"):
                    iss["title"] = f"전기 {subject} 조정의 유보 {won(closing)}원이 남아 있습니다. 당기 추인을 확인합니다"
                self.adj_fate.append(({"subject": subject, "amount": closing, "side": "유보"}, "추인 확인", same[0]))
                continue
            t = self.agg(*KEY_TOPICS.get(key or "", []))
            gone = bool(key) and not t.has_current
            k = f"reserve:{subject}"
            self.add(k, "전기 연속", "확실" if gone else "가능",
                     f"전기 유보 {subject} {won(closing)}원" + ("은 계정이 없어져 전액 추인 대상입니다" if gone else "의 당기 추인을 확인합니다"),
                     guide=["1-3"], topics=KEY_TOPICS.get(key or "", []), amounts={"prior": closing}, basis=[line],
                     prior_treatment=f"전기 50호(을) 기말 {won(closing)}원", papers=["reserve_50", *KEY_PAPERS.get(key or "", [])],
                     forms=["15", "50을"], questions=[])
            self.adj_fate.append(({"subject": subject, "amount": closing, "side": "유보"}, "추인 확인", k))

    def link_prior_fixes(self) -> None:
        """전기오류수정 전표가 전기 50호(을) 유보 과목과 같은 자산 · 부채를 고친 것으로 보이면 두 이슈를 잇는다(5회차).
        전표 글(적요 · 상대 계정 이름)에 유보 과목 이름이나 그 과목의 낱말(LINK_WORDS)이 있으면 잇는다. 번호는 finalize 가 단다."""
        pe = self.issues.get("prior_error")
        if pe is None or not self.fix_texts:
            return
        text = " ".join(self.fix_texts)
        for r in self.prior_res:
            subject = str(r.get("subject") or "")
            rx = LINK_WORDS.get(subject_key(subject) or "")
            if not subject or not (re.sub(r"\s+", "", subject) in re.sub(r"\s+", "", text) or (rx and re.search(rx, text))):
                continue
            mark = f"전기 50호(을) {subject} 기말 유보"
            targets = [k for k, v in self.issues.items() if k != "prior_error" and any(b.startswith(mark) for b in v["basis"])]
            pe["basis"].append(f"전기 50호(을) {subject} 유보 {won(_int(r.get('closing')))}원과 같은 자산 · 부채를 고친 전표로 보입니다"
                               "(전기오류수정 전표의 적요 · 상대 계정)")
            for k in targets:
                pe.setdefault("_links", []).append(k)
                self.issues[k].setdefault("_links", []).append("prior_error")
                self.issues[k]["basis"].append(f"당기 전기오류수정 전표({won(self.gross(self.T['prior_error']))}원)가 이 유보 과목을 "
                                               "고친 것으로 보입니다")

    # ------------------------------------------------------------ 가이드 줄 판정(사실)

    def guide_lines(self) -> None:
        T = self.T
        none = "해당 없음"

        def present(gid, t: Topic, absent: str, keys=(), status_if=None):
            if t.exists:
                self.judge(gid, status_if or none, [describe(t) + " · " + state(t).replace("계정 상태 ", "")], keys)
            else:
                self.judge(gid, none, [absent])

        # 1절
        if not self.has_prior:
            for gid in ("1-1", "1-3", "1-4"):
                self.judge(gid, "자료 필요", ["전기 세무조정계산서(전기.json)가 없습니다"])
        else:
            c = self.company
            kind = {True: "중소기업", False: "중소기업 아님"}.get(c.get("sme"), "모름")
            facts = [f"{INFO_SME if self.P.get('no_prior') else '전기'} 회사 종류 {kind}(종류별구분 {c.get('kind_code') or '없음'})"]
            if c.get("industry_code") or c.get("biz_type"):
                facts.append(f"업태 {c.get('biz_type') or ''} · 업종코드 {c.get('industry_code') or ''}".strip())
            self.judge("1-1", none if c.get("sme") is not None else "자료 필요", facts, ["sme_reduction", "carryback"])
            # 1-3
            if self.P.get("no_prior"):          # 전기 신고서가 없는 신고 건(신설 첫 해 · 첫 수임)
                self.judge("1-3", none, [NO_PRIOR_FACT])
            elif self.adj_fate:
                facts = []
                for a, fate, _k in self.adj_fate[:5]:
                    side = a.get("side") or ""
                    facts.append(f"{side} {a.get('subject')} {won(_int(a.get('amount')))}원 {a.get('disposition') or ''}".strip()
                                 + f": {fate}")
                if len(self.adj_fate) > 5:
                    facts.append(f"외 {len(self.adj_fate) - 5}줄")
                self.judge("1-3", none, facts, [k for _a, _f, k in self.adj_fate])
            else:
                self.judge("1-3", none, ["전기 15호 조정 · 50호(을) 유보가 없습니다"])
            # 1-4
            if self.P.get("no_prior"):
                self.judge("1-4", none, [NO_PRIOR_FACT])
            elif self.prior_credits:
                facts = [f"{c.get('name')} {won(_int(c.get('amount')))}원" + (f"(이월 {won(_int(c.get('carryforward')))}원)"
                         if _int(c.get("carryforward")) else "") for c in self.prior_credits[:4]]
                if self.ibt <= 0:
                    facts.append(f"당기 결산 법인세차감전손익 {won(self.ibt)}원(세무조정 전)입니다. 세무조정 · 이월결손금 공제 뒤 "
                                 "과세표준과 산출세액이 생기는지 보고 감면 · 공제 가능액을 정합니다")
                self.judge("1-4", none, facts, [f"credit:{c.get('name') or c.get('code')}" for c in self.prior_credits])
            elif not self.prior_filed("8갑"):
                self.judge("1-4", "자료 필요", ["전기 신고서에 8호(갑)이 보이지 않아 공제감면 이력을 확인하지 못했습니다"
                                                 "(신고서에 없거나 엔진이 찾지 못함)"])
            else:
                self.judge("1-4", none, ["전기 8호(갑) 공제감면이 없습니다"])
        cap = T["capital"]
        rev = T["revenue"]
        rental = self.rental_test()
        facts = [describe(cap) + (" · 변동 없음" if cap.change == 0 else f" · 증감 {won(cap.change)}원")]
        facts += self.rental_facts()
        if rental["share"] >= 0.5:
            holder = self.top_holder_fact()
            self.add("rental_main", "신고 점검", "가능",
                     "임대 · 이자 · 배당 수입이 매출액의 50% 이상입니다. 부동산임대업 주업 등 법인 요건(시행령 제42조 제2항)을 확인합니다",
                     guide=["1-2"], topics=[x["topic"] for x in rental["parts"] if x["amount"]],
                     basis=facts + ([holder] if holder else []), papers=[], forms=["51", "3"],
                     questions=["사업연도 종료일 현재 지배주주등(특수관계인 포함) 지분율 합계가 50%를 넘는지 알려 주십시오",
                                "상시근로자 수가 5명 미만인지 알려 주십시오(최대주주와 그 친족, 근로계약 1년 미만, 단시간근로자는 빼고 셉니다)",
                                "간주임대료 익금가산액(조세특례제한법 제138조)이 있으면 알려 주십시오"])
        self.judge("1-2", none, facts, ["share_change"])

        # 2절 머리
        found = [T[k].label for k in ("corp_tax", "entertainment", "vehicle_cost", "taxes", "misc_loss", "donation",
                                      "retirement_allowance", "retirement_plan", "allowance", "accrued_income", "accrued_expense",
                                      "securities", "loan", "fx", "depreciation") if T[k].has_current]
        self.judge("2-1", none, [f"계정 {len(self.accounts)}개, 세무조정과 이어진 계정 {len(found)}종({', '.join(found)})"],
                   ["corp_tax", "tax_refund", "fx", "cogs", "expense_evidence", "tax_zero"] + [k for k in self.issues if k.startswith("check:")])
        assets = _int(self.tot.get("assets"))
        rev_prior = _int(self.prior_totals.get("revenue")) or rev.prior
        facts = [f"당기 매출액 {won(rev.current)}원(전기 {won(rev_prior)}원) · 자산총계 {won(assets)}원"]
        if self.sme is True and assets >= SME_ASSET_LIMIT:
            self.add("sme_size", "신고 점검", "가능", "중소기업으로 신고해 왔는데 자산총계가 5천억 원 이상입니다", guide=["2-2"],
                     amounts={"current": assets}, basis=facts, papers=[], forms=["51"], questions=[])
        sme_fact = ({True: "전기 중소기업. 자산총계는 5천억 원 미만입니다", False: "전기 중소기업 아님"}.get(
            self.sme, "전기 회사 종류를 모릅니다") if self.sme is not True or assets < SME_ASSET_LIMIT else "전기 중소기업")
        facts.append(sme_fact.replace("전기", INFO_SME, 1) if self.P.get("no_prior") else sme_fact)
        facts += self.sme_scale(rev.current)
        # 당기 중소기업 · 소기업 여부는 당기 업종별 매출액과 유예기간으로 사람이 정한다. 전기 결과만으로 「해당 없음」 으로 두지 않는다
        self.judge("2-2", "자료 필요", facts + ["업종별 매출 기준과 유예기간은 사람이 정합니다"],
                   [k for k in ("sme_size", "sme_small") if k in self.issues])

        # 2-3 계정별
        s, spl = T["securities"], T["securities_pl"]
        present("2-3-1-1", s, "유가증권 계정이 없습니다")
        if spl.exists:
            self.judge("2-3-1-2", none, self.pl_lines(spl))
        elif s.exists:
            self.judge("2-3-1-2", "자료 필요", ["평가손익 · 처분손익 계정은 없습니다. 유가증권명세서로 취득가액을 확인합니다"])
        else:
            self.judge("2-3-1-2", none, ["유가증권과 평가 · 처분손익 계정이 없습니다"])
        present("2-3-1-3", T["dividend"], "배당금수익이 없습니다")
        if self.fund_note:
            self.judge("2-3-1-3", none, [self.fund_note])
        if s.exists:
            self.judge("2-3-1-4", "자료 필요", ["해외 유가증권인지는 유가증권명세서 · 회사 질의로만 압니다"])
        else:
            self.judge("2-3-1-4", none, ["유가증권 계정이 없습니다"])

        al, bd, rc = T["allowance"], T["bad_debt"], T["receivable"]
        if al.exists or bd.exists:
            self.judge("2-3-2-1", none, [describe(al) if al.exists else "대손충당금 계정 없음", describe(rc)])
        else:
            self.judge("2-3-2-1", none, [describe(rc) + ". 대손충당금 계정이 없습니다" if rc.exists else "채권 · 대손충당금 계정이 없습니다"])
        if al.exists or bd.exists:
            sp = self.allowance_split()
            self.judge("2-3-2-2", none, [f"대손충당금 차변 {won(al.debit)}원(채권 상계 {won(sp['written_off'])}원 · 환입 "
                                         f"{won(sp['reversed'])}원) · 직접 대손 {won(sp['direct'])}원 · 대손상각비 {won(bd.current)}원"])
        else:
            self.judge("2-3-2-2", none, ["대손충당금 · 대손상각비가 없습니다"])

        ln = T["loan"]
        present("2-3-3-1", ln, "대여금 · 가지급금 · 주임종채권 계정이 없습니다")
        if ln.exists:
            path = self.balance_path(ln.codes) if ln.touched else None
            self.judge("2-3-3-2", none, [f"대여금 증감 {won(ln.change)}원 · 이자수익 {won(T['interest_income'].current)}원"]
                       + ([f"기중 최대 잔액 {won(path['peak'])}원 · 일별 잔액 평균 {won(path['average'])}원"] if path else []))
            self.judge("2-3-3-3", none, [describe(T["interest_expense"]) if T["interest_expense"].exists else "이자비용이 없습니다",
                                         describe(T["borrowing"]) if T["borrowing"].exists else "차입금이 없습니다"])
        else:
            self.judge("2-3-3-2", none, ["대여금 계정이 없습니다"])
            self.judge("2-3-3-3", none, ["대여금 계정이 없어 지급이자 손금불산입 대상이 아닙니다"])

        ii, pt = T["interest_income"], T["prepaid_tax"]
        self.judge("2-3-4-1", none, [describe(ii) if ii.exists else "이자수익이 없습니다",
                                     describe(pt) if pt.exists else "선납세금 계정이 없습니다"])
        present("2-3-4-2", T["accrued_income"], "미수수익 계정이 없습니다")

        tg, dep, acc = T["tangible"], T["depreciation"], T["accum_dep"]
        if tg.exists or dep.exists or acc.exists:
            pf = [c for c in ("20_1", "20_2", "20_4") if self.prior_filed(c)]
            self.judge("2-3-5-1", none, [describe(tg) if tg.exists else "유형자산 본계정이 장부에 없습니다(누계액만 있음)",
                                         describe(dep), f"전기 제출 감가상각 서식 {' · '.join(pf) if pf else '없음'}"])
            self.judge("2-3-5-2", "자료 필요", ["유형자산명세서(고정자산대장)가 받은자료에 없습니다"])
            dres = [r for r in self.prior_res if subject_key(r.get("subject")) == "depreciation"]
            if not self.has_prior:
                self.judge("2-3-5-3", "자료 필요", ["전기 50호(을)이 없습니다"])
            elif dres:
                self.judge("2-3-5-3", none, [f"전기 감가상각 유보 {len(dres)}줄"], ["depreciation"] + [f"reserve:{r.get('subject')}" for r in dres])
            else:
                self.judge("2-3-5-3", none, [f"유형자산 증감 {won(tg.change)}원", "전기 50호(을)에 감가상각 유보가 없습니다"])
        else:
            for gid in ("2-3-5-1", "2-3-5-2", "2-3-5-3"):
                self.judge(gid, none, ["유형자산 · 감가상각비 계정이 없습니다"])

        cp = T["capex"]
        self.judge("2-3-6-1", none, [describe(cp) + f" · 증감 {won(cp.change)}원" if cp.exists else "기계장치 · 시설장치 · 건설중인자산 · 건물 · 건설기계 계정이 없습니다"])
        present("2-3-7-1", T["grant"], "국고보조금 계정이 없습니다")
        itg = self.agg("intangible", "amortization")
        present("2-3-8-1", itg, "무형자산 · 무형자산상각비 계정이 없습니다")
        p9 = self.agg("accrued_expense", "provision", "retirement_allowance")
        present("2-3-9-1", p9, "미지급비용 · 충당부채 계정이 없습니다")
        present("2-3-10-1", T["convertible"], "전환사채 · 신주인수권부사채 계정이 없습니다")
        sp = T["share_premium"]
        self.judge("2-3-11-1", none, [describe(cap) + f" · 증감 {won(cap.change)}원"] + ([describe(sp)] if sp.exists else []))
        self.judge("2-3-11-2", "자료 필요", ["주주 변동은 장부로 알 수 없어 회사에 묻습니다"])
        eo = T["equity_other"]
        self.judge("2-3-12-1", none, [describe(eo) + f" · 증감 {won(eo.change)}원" if eo.exists else "자기주식 · 감자차손익 · 자본조정 계정이 없습니다"])
        pay = T["payroll"]
        self.judge("2-3-13-1", none, [describe(pay) + f" · 증감 {won(pay.change)}원" if pay.exists else "급여 계정이 없습니다",
                                      describe(T["welfare"]) if T["welfare"].exists else "복리후생비 계정이 없습니다"])
        rnd = T["rnd"]
        present("2-3-14-1", rnd, "경상연구개발비 · 개발비 계정이 없습니다")
        present("2-3-14-2", rnd, "경상연구개발비 · 개발비 계정이 없습니다")
        present("2-3-15-1", self.agg("taxes", "misc_loss"), "세금과공과 · 잡손실 계정이 없습니다")
        present("2-3-16-1", T["entertainment"], "기업업무추진비 계정이 없습니다")
        fr = T["freight"]
        self.judge("2-3-17-1", none, ([describe(fr) + f" · {fr.status()}"] if fr.exists else ["운반비 계정이 없습니다"])
                   + ["제3자물류비용 세액공제(조특법 제104조의14)는 2020년 12월 31일 이전에 끝나는 과세연도까지라 당기 공제 대상이 아닙니다"])
        pe = T["prior_error"]
        present("2-3-18-1", pe, "전기오류수정손익 계정이 없습니다")
        present("2-3-19-1", T["donation_gain"], "자산수증이익 · 채무면제이익 계정이 없습니다")
        present("2-3-20-1", T["inventory_loss"], "재고자산감모손실 계정이 없습니다")
        car = self.agg("vehicles", "vehicle_cost")
        present("2-3-21-1", car, "차량운반구 · 차량유지비 계정이 없습니다")
        present("2-3-22-1", T["donation"], "기부금 계정이 없습니다")

    # ------------------------------------------------------------ 마무리

    @staticmethod
    def bucket(iss: dict) -> int:
        if iss["kind"] == "신고 점검":
            return 0
        if iss["kind"] == "서식 필요":
            return 5
        if iss["kind"] == "전기 연속":
            return 2
        return {"확실": 1, "가능": 3, "자료 필요": 4}.get(iss["certainty"], 4)

    @staticmethod
    def size(iss: dict) -> int:
        a = iss.get("amounts") or {}
        return max([abs(_int(a.get(k))) for k in ("current", "prior", "change") if a.get(k) is not None] or [0])

    @classmethod
    def foldable(cls, iss: dict) -> bool:
        """작은 조정 후보 묶음(FOLD_LIMIT). 확실 · 전기 처리가 있는 줄 · 다른 종류는 접지 않는다."""
        return (iss["kind"] == "조정 후보" and iss["certainty"] == "가능" and not iss.get("prior_treatment")
                and cls.size(iss) < FOLD_LIMIT)

    def finalize(self) -> dict:
        keys = list(self.issues)
        folded = {k: self.foldable(self.issues[k]) for k in keys}
        order = sorted(keys, key=lambda k: (self.bucket(self.issues[k]), folded[k], -self.size(self.issues[k]), keys.index(k)))
        numbers = {k: i + 1 for i, k in enumerate(order)}
        issues = []
        for k in order:
            iss = dict(self.issues[k])
            rule = iss.pop("key")
            for gid in iss["guide"]:
                self.judge(gid, "이슈", keys=[k])
            extra = iss.pop("law_extra", [])
            links = iss.pop("_links", [])
            if links:
                iss["basis"] = iss["basis"] + [f"함께 볼 이슈 {numbers[x]}" for x in dict.fromkeys(links) if x in numbers]
            iss["law"] = law_for(rule, iss["title"]) + [dict(x) for k in extra for x in load_laws().get(k, [])]
            iss["folded"] = folded[k]
            iss["key"] = issue_key(iss)
            iss["rule"] = rule
            issues.append({"no": numbers[k], **iss})
        guide = []
        for g in load_guide():
            j = self.judg.get(g["id"]) or {"status": "자료 필요", "facts": ["엔진 판정 규칙이 없습니다"], "keys": []}
            nos = sorted({numbers[k] for k in j["keys"] if k in numbers})
            status = j["status"] or "자료 필요"
            if status == "이슈" and not nos:
                status = "해당 없음"
            if nos and status != "이슈":
                status = "이슈"
            guide.append({"id": g["id"], "group": g["section"], "title": g["title"], "text": g["text"], "status": status,
                          "facts": j["facts"][:6] or ["엔진 판정 근거가 없습니다"], "issues": nos})
        return {"guide": guide, "issues": issues, "forms": self.forms_list(issues)}

    def forms_list(self, issues: list[dict]) -> list[dict]:
        eng = engine_forms()
        rows: dict[str, dict] = {}

        def row(code: str) -> dict:
            if code not in rows:
                rows[code] = {"code": code, "name": form_name(code), "prior_filed": self.prior_filed(code), "status": None,
                              "why": [], "by": "엔진" if code in eng else "사람"}
            return rows[code]

        for code in BASIC_FORMS:
            row(code)["status"] = "해당"
        for iss in issues:
            for code in iss["forms"]:
                r = row(code)
                if iss["no"] not in r["why"]:
                    r["why"].append(iss["no"])
                if r["status"] != "해당":
                    r["status"] = "해당" if iss["certainty"] == "확실" and iss["kind"] != "전기 연속" else "확인"
        if (self.info or {}).get("가산세"):            # 신고건.json 에 사람이 넣은 가산세가 있으면 9호를 만든다
            r = row("9")
            r["status"] = "해당"
            if "신고건 가산세" not in r["why"]:
                r["why"].append("신고건 가산세")
        for code, f in self.prior_forms.items():
            if code not in rows:
                row(code)["status"] = "확인"
        return list(rows.values())

    def first_year_text(self) -> None:
        """첫 사업연도면 이슈 근거와 가이드 사실 글에서 전기 대비 글(「(전기 0원)」 · 「증감 …원」 · 「신규」)을 뺀다. 전기 금액이
        모두 0 이라 뜻이 없는 글이다. 이슈 금액(amounts)과 판정은 그대로 둔다."""
        if not self.first_year:
            return

        def clean(texts: list) -> list:
            out = [RX_FIRST_YEAR.sub("", str(t)) for t in texts if str(t) != "계정 상태 신규"]
            return list(dict.fromkeys(t for t in out if t))

        for iss in self.issues.values():
            iss["basis"] = clean(iss["basis"])
        for j in self.judg.values():
            j["facts"] = clean(j["facts"])

    def run(self) -> dict:
        self.check_ledger()
        self.check_tax_zero()
        self.check_prior_loss()
        self.check_prior_forms()
        self.check_prior_car()
        self.rule_loans()
        self.rule_corp_tax()
        self.rule_entertainment()
        self.rule_car()
        self.rule_penalty()
        self.rule_retirement()
        self.rule_donation()
        self.check_prior_donation()
        self.rule_hidden_advance()
        self.rule_loan_moved()
        self.rule_car_disposal()
        self.rule_repair_capital()
        self.rule_legal_fees()
        self.rule_prior_period_pl()
        self.rule_officer_bonus()
        self.rule_dep_missing()
        self.rule_construction()
        self.rule_interim()
        self.rule_bad_debt()
        self.rule_accrued()
        self.rule_securities()
        self.rule_fx()
        self.rule_depreciation()
        self.rule_misc_accounts()
        self.rule_credits()
        self.rule_forms_needed()
        self.rule_prior_pairs()
        self.rule_prior_donation_other()
        self.rule_prior()
        self.link_prior_fixes()
        self.guide_lines()
        self.first_year_text()
        return self.finalize()


def issue_key(iss: dict) -> str:
    """이슈 key(CONTRACT.md 14.1): 종류 · 가이드 · 계정을 「|」 로 이은 글. 같은 key 가 둘일 수 있어 결론 이어받기는 rule 도 본다."""
    return "|".join([str(iss.get("kind") or ""), ",".join(iss.get("guide") or []), ",".join(iss.get("accounts") or [])])


def build(ledger: dict, journal: list[dict], prior: dict | None, info: dict | None = None) -> dict:
    """AR.json 내용을 만든다. journal 은 read_journal 꼴(debit · credit 정수, closing 참거짓)."""
    return Builder(ledger, journal, prior, info).run()


def validate(ar: dict) -> list[str]:
    """계약 7절 검사. 문제 글 목록(빈 목록이면 통과)."""
    out = []
    ids = [g["id"] for g in load_guide()]
    got = [g["id"] for g in ar.get("guide", [])]
    if got != ids:
        out.append("가이드 줄이 guide.yaml 과 다릅니다")
    for g in ar.get("guide", []):
        if g.get("status") not in STATUSES:
            out.append(f"가이드 {g.get('id')} 판정이 비었습니다")
        if not g.get("facts"):
            out.append(f"가이드 {g.get('id')} 근거 사실이 없습니다")
    issues = ar.get("issues", [])
    if [i["no"] for i in issues] != list(range(1, len(issues) + 1)):
        out.append("이슈 번호가 1부터 이어지지 않습니다")
    last = -1
    for i in issues:
        if i["kind"] not in KINDS:
            out.append(f"이슈 {i['no']} 종류 {i['kind']}")
        if i["certainty"] not in CERTAINTIES:
            out.append(f"이슈 {i['no']} 확실도 {i['certainty']}")
        b = Builder.bucket(i)
        if b < last:
            out.append(f"이슈 {i['no']} 순서가 어긋납니다")
        last = b
        if not isinstance(i.get("law", []), list) or any(not x.get("ref") or x.get("grade") not in GRADES for x in i.get("law", [])):
            out.append(f"이슈 {i['no']} 근거 조문 등급이 비었습니다")
        if not isinstance(i.get("folded", False), bool):
            out.append(f"이슈 {i['no']} folded 가 참거짓이 아닙니다")
    for f in ar.get("forms", []):
        if f.get("status") not in FORM_STATUSES:
            out.append(f"서식 {f.get('code')} 판정 {f.get('status')}")
    text = json.dumps(ar, ensure_ascii=False)
    if "—" in text:
        out.append("줄표(—)가 있습니다")
    sentences = [i["title"] for i in issues] + [q for i in issues for q in [*i.get("questions", []), *i.get("todo", [])]] +         [f for g in ar.get("guide", []) for f in g.get("facts", [])]
    for t in sentences:
        if str(t).rstrip().endswith("?"):
            out.append(f"물음표로 끝나는 문장: {t}")
    return out
