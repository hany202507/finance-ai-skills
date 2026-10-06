# -*- coding: utf-8 -*-
"""부가세 전표 판단 결정론 룰셋 엔진.
JudgmentInput(정규화된 경제적 사건) → Judgment(더존 필드 확정).
계산·판정은 결정론. LLM 없음. 판단성 항목은 hitl=True(자동확정 금지).
근거: 부가세법 §39, 시행령 §88⑤·§81·§63.
근거: 부가세법 §39·§10·§26·§29, 시행령 §88⑤·§81·§63 (아래 룰셋 주석에 조문 병기)
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, Tuple
from collections import Counter


class Purpose(Enum):
    접대 = "접대"
    복리후생 = "복리후생"
    사업무관 = "사업무관"
    차량_소형승용 = "차량_소형승용"
    여객운송_개인서비스 = "여객운송_개인서비스"   # 목욕·이발·미용·여객운송·입장권·과세의료·수의진료·무도/운전학원 (령§88⑤)
    면세관련 = "면세관련"
    토지_자본적지출 = "토지_자본적지출"
    자산취득 = "자산취득"
    일반경비 = "일반경비"


class DenyReason(Enum):
    """신고서 「공제받지못할매입세액명세서」 ①~⑧ 대응. 명칭으로 식별(더존코드 매핑은 G3)."""
    필요적기재누락 = "①필요적기재누락"
    사업무관 = "②사업무관"
    비영업용승용차 = "③비영업용승용차"
    접대비 = "④접대비"
    면세관련 = "⑤면세관련"
    토지관련 = "⑥토지관련"
    등록전 = "⑦등록전"
    금스크랩계좌 = "⑧금스크랩계좌"


class Routing(Enum):
    매입매출 = "매입매출"
    일반 = "일반"


class ZeroRateType(Enum):
    """영세율 유형 (부가세법 §21~24)."""
    직수출 = "직수출"                          # §21②1 세계면제 → 16
    내국신용장_구매확인서 = "내국신용장_구매확인서"   # §21②3 영세율세계 → 12
    국외용역 = "국외용역"                       # §22
    외국항행 = "외국항행"                       # §23
    기타외화획득 = "기타외화획득"                 # §24


class DeemedSupply(Enum):
    """간주공급 (부가세법 §10) — 세계 없는 과세매출(직매장반출 제외)."""
    자가공급_면세전용 = "자가공급_면세전용"        # §10①
    자가공급_비영업용승용차 = "자가공급_비영업용승용차"  # §10②
    직매장반출 = "직매장반출"                    # §10③ 세계발급 → 11
    개인적공급 = "개인적공급"                    # §10④
    사업상증여 = "사업상증여"                    # §10⑤
    폐업시잔존 = "폐업시잔존"                    # §10⑥


@dataclass
class JudgmentInput:
    방향: str                                  # '매출' | '매입'
    증빙: frozenset                            # {'세금계산서','계산서','카드','현금영수증','은행','지출결의서'}
    총액: int = 0                              # VAT 포함 총액(카드·현금영수증)
    공급가: Optional[int] = None               # 세계처럼 이미 분리돼 있으면 값
    세액: Optional[int] = None
    전자세계: bool = False
    과세구분: str = "과세"                      # '과세'|'영세_국내'|'수출'|'면세'
    수입: bool = False                         # 수입세금계산서
    공급자_사업자번호: Optional[str] = None
    거래처_과세유형: Optional[str] = None       # '일반'|'간이'|'면세'|None
    거래처_공급대가_4800이상: Optional[bool] = None
    카드_가맹점_확인: bool = False              # 가맹점 사업자번·과세유형 확보
    품명: str = ""
    지출목적: Optional[Purpose] = None
    자본적지출: bool = False
    소형승용_영업용: bool = False               # 운수·렌터카·운전학원 등 예외(공제)
    증빙흠결: bool = False                      # 세계 미수취·필요적기재 부실·합계표 부실
    전기승계_확정: bool = False                 # 전기 확정판단 승계건 → 자동확정 허용
    # 매출측 판단축 (2026-07-15, 매출측 설계문서)
    면세대상: bool = False                      # §26 면세 재화·용역
    영세율유형: Optional[ZeroRateType] = None    # §21~24
    간주공급유형: Optional[DeemedSupply] = None  # §10
    매입세액공제이력: bool = False               # 간주공급 과세 전제(매입 시 공제받은 재화)
    업종: Optional[str] = None                  # 업종 프로파일 컨텍스트
    조정사유: Optional[str] = None               # §29: 에누리/환입/매출할인/장려금/하자보증금/파손
    조정금액: int = 0                           # 조정 대상 금액(양수)
    등록전_매입: bool = False                   # §39①8 등록 전 매입(20일 역산 예외는 상위 판정)
    금거래계좌_미사용: bool = False              # 조특법 §106의4·§106의9 (금·스크랩 업종)


@dataclass
class Judgment:
    라우팅: Routing
    구분: Optional[str]                        # '매출'|'매입'|None(일반)
    과세유형: Optional[int]
    불공제사유: Optional[DenyReason]
    공급가: int
    세액: int
    신뢰도: str                                # '높음'|'중간'|'낮음'
    hitl: bool
    근거: List[Tuple[str, str]] = field(default_factory=list)   # [(법령, 설명)]
    고정자산: bool = False                      # 신고서 (12) 고정자산매입 분리용


# 과세유형표 (더존업로드양식.md + H2 수출16 반영)
SALES_TAXTYPE = {
    ("세금계산서", "과세"): 11,
    ("세금계산서", "영세_국내"): 12,
    ("계산서", "면세"): 13,
    ("무증빙", "과세"): 14,
    ("수출", "수출"): 16,
    ("카드", "과세"): 17,
    ("현금영수증", "과세"): 22,
    ("현금영수증", "면세"): 23,
}
PURCH_TAXTYPE = {
    ("세금계산서", "과세"): 51,
    ("세금계산서", "영세_국내"): 52,
    ("계산서", "면세"): 53,
    ("수입", "과세"): 55,
    ("카드", "과세"): 57,
    ("카드", "면세"): 58,
    ("현금영수증", "과세"): 61,
}

_UNGWANG_54 = 54  # 더존 매입 불공 과세유형
_VAT_EVIDENCE = {"세금계산서", "계산서", "카드", "현금영수증"}
_EVIDENCE_PRIORITY = ["세금계산서", "계산서", "카드", "현금영수증"]


# ---------------------------------------------------------------- S1 라우팅
def route(inp: JudgmentInput) -> Routing:
    """S1 전표 라우팅. 부가세 신고대상 증빙이 있으면 매입매출, 아니면 일반."""
    if inp.수입 or (inp.증빙 & _VAT_EVIDENCE):
        return Routing.매입매출
    return Routing.일반


# ---------------------------------------------------------------- S3 과세유형
def primary_evidence(inp: JudgmentInput) -> str:
    """주 증빙 선택. 수입은 taxtype에서 우선 처리하므로 여기선 일반 증빙만."""
    for e in _EVIDENCE_PRIORITY:
        if e in inp.증빙:
            return e
    return "무증빙"


def taxtype(inp: JudgmentInput) -> Optional[int]:
    """S3 과세유형 판정. 방향+주증빙+과세구분 → 더존 과세유형 코드."""
    if inp.방향 == "매출":
        if inp.과세구분 == "수출":
            return SALES_TAXTYPE[("수출", "수출")]
        ev = primary_evidence(inp)
        if ev == "무증빙":
            return SALES_TAXTYPE[("무증빙", "과세")]       # 건별 14
        return SALES_TAXTYPE.get((ev, inp.과세구분))
    else:  # 매입
        if inp.수입:
            return PURCH_TAXTYPE[("수입", "과세")]
        ev = primary_evidence(inp)
        return PURCH_TAXTYPE.get((ev, inp.과세구분))


# ---------------------------------------------------------------- S4 공제/불공제
@dataclass
class DenyResult:
    불공제사유: Optional[DenyReason] = None
    라우팅오버라이드: Optional[Routing] = None
    근거: List[Tuple[str, str]] = field(default_factory=list)
    hitl: bool = False


def _hitl(inp: JudgmentInput) -> bool:
    """판단성 항목은 전기승계 확정이 아니면 HITL."""
    return not inp.전기승계_확정


def deny_check(inp: JudgmentInput) -> DenyResult:
    """S4 매입세액 공제/불공제. 매출은 대상 아님."""
    if inp.방향 != "매입":
        return DenyResult()

    # 령§88⑤: 카드/현금영수증 수취해도 불공제 업종 → 일반전표 전액비용
    if inp.지출목적 is Purpose.여객운송_개인서비스:
        return DenyResult(라우팅오버라이드=Routing.일반,
                          근거=[("부가세법 시행령 §88⑤", "여객운송·개인서비스업 전액비용")],
                          hitl=_hitl(inp))

    # §39①6 접대비 — 실무: 매입세액 미공제, 일반전표 전액비용(매입매출/불공제명세 미기재)
    if inp.지출목적 is Purpose.접대:
        return DenyResult(라우팅오버라이드=Routing.일반,
                          근거=[("부가세법 §39①6", "기업업무추진비 관련 — 일반전표 전액비용")],
                          hitl=_hitl(inp))
    # §39①4 사업무관
    if inp.지출목적 is Purpose.사업무관:
        return DenyResult(불공제사유=DenyReason.사업무관,
                          근거=[("부가세법 §39①4", "사업무관 지출")], hitl=_hitl(inp))
    # §39①5 비영업용 소형승용차 (영업용 직접사용은 예외=공제)
    if inp.지출목적 is Purpose.차량_소형승용 and not inp.소형승용_영업용:
        return DenyResult(불공제사유=DenyReason.비영업용승용차,
                          근거=[("부가세법 §39①5", "비영업용 소형승용차")], hitl=_hitl(inp))
    # §39①7전 면세관련
    if inp.지출목적 is Purpose.면세관련:
        return DenyResult(불공제사유=DenyReason.면세관련,
                          근거=[("부가세법 §39①7", "면세사업 관련")], hitl=_hitl(inp))
    # §39①7후 토지 자본적지출
    if inp.지출목적 is Purpose.토지_자본적지출 and inp.자본적지출:
        return DenyResult(불공제사유=DenyReason.토지관련,
                          근거=[("부가세법 §39①7", "토지의 자본적 지출")], hitl=_hitl(inp))
    # §39①8 사업자등록 전 매입
    if inp.등록전_매입:
        return DenyResult(불공제사유=DenyReason.등록전,
                          근거=[("부가세법 §39①8", "사업자등록 전 매입(20일 역산 예외 별도)")], hitl=_hitl(inp))
    # 조특법 금·스크랩 거래계좌 미사용
    if inp.금거래계좌_미사용:
        return DenyResult(불공제사유=DenyReason.금스크랩계좌,
                          근거=[("조특법 §106의4·§106의9", "금·스크랩 거래계좌 미사용")], hitl=_hitl(inp))
    # §39①1·2 증빙흠결(합계표 부실·세계 미수취/필요적기재 부실)
    if inp.증빙흠결:
        return DenyResult(불공제사유=DenyReason.필요적기재누락,
                          근거=[("부가세법 §39①1·2", "세계/합계표 흠결")], hitl=_hitl(inp))
    # 간이·면세사업자 매입: 세계 없으면 일반전표. 단 공급대가 4,800만↑ 간이는 세계 발급의무→공제.
    if inp.거래처_과세유형 in ("간이", "면세"):
        발급의무 = (inp.거래처_과세유형 == "간이" and inp.거래처_공급대가_4800이상 is True)
        세계있음 = "세금계산서" in inp.증빙
        if not (발급의무 and 세계있음):
            return DenyResult(라우팅오버라이드=Routing.일반,
                              근거=[("부가세법 §36·§32", "간이·면세사업자 매입 전액비용")],
                              hitl=_hitl(inp))
    # 카드 가맹점 사업자번·과세유형 미확인 → 근거불충분, 일반전표
    if "카드" in inp.증빙 and not inp.카드_가맹점_확인:
        return DenyResult(라우팅오버라이드=Routing.일반,
                          근거=[("근거불충분", "카드 가맹점 사업자번호·과세유형 미확인")],
                          hitl=_hitl(inp))
    return DenyResult()


# ---------------------------------------------------------------- S6 금액분해
def split_amount(inp: JudgmentInput) -> Tuple[int, int]:
    """S6 금액분해. (공급가, 세액). 카드·현금영수증 총액은 10/11·1/11로 분해."""
    if inp.과세구분 in ("면세", "영세_국내", "수출"):
        base = inp.공급가 if inp.공급가 is not None else inp.총액
        return (base, 0)
    if inp.공급가 is not None and inp.세액 is not None:
        return (inp.공급가, inp.세액)
    공급가 = inp.총액 * 10 // 11
    세액 = inp.총액 - 공급가
    return (공급가, 세액)


# ---------------------------------------------------------------- 매출 판단축 (S3-매출 확장)
@dataclass
class SalesResult:
    과세유형: Optional[int]                     # None = 과세대상 아님(확인 필요)
    hitl: bool = False
    근거: List[Tuple[str, str]] = field(default_factory=list)
    첨부: Optional[str] = None                  # 필요 첨부서류(영세율 등)


def sales_taxtype(inp: JudgmentInput) -> SalesResult:
    """매출 4단계 우선순위 판정: 면세(§26)→영세율(§21~24)→간주공급(§10)→일반."""
    # (a) 면세 §26 → 계산서 13 / 현금영수증면세 23
    if inp.면세대상:
        code = 23 if "현금영수증" in inp.증빙 else 13
        return SalesResult(code, 근거=[("부가세법 §26", "면세 재화·용역")])

    # (b) 영세율 §21~24 → 세계발급이면 12, 미발급(직수출)이면 16
    if inp.영세율유형 is not None:
        z = inp.영세율유형
        if z is ZeroRateType.직수출:
            return SalesResult(16, hitl=_hitl(inp), 근거=[("부가세법 §21②1", "직수출")],
                               첨부="수출실적명세서")
        if z is ZeroRateType.내국신용장_구매확인서:
            return SalesResult(12, hitl=_hitl(inp), 근거=[("부가세법 §21②3", "내국신용장·구매확인서")],
                               첨부="내국신용장·구매확인서 전자발급명세서")
        # 국외용역·외국항행·기타외화획득 — 세계발급 케이스 의존 → 기본 16 + HITL
        return SalesResult(16, hitl=True, 근거=[("부가세법 §22~24", f"영세율({z.value})")],
                           첨부="영세율첨부서류제출명세서")

    # (c) 간주공급 §10 → 직매장반출만 11(세계), 나머지 14(건별). 매입세액 공제이력 전제.
    if inp.간주공급유형 is not None:
        if not inp.매입세액공제이력:
            return SalesResult(None, hitl=True,
                               근거=[("부가세법 §10", "간주공급 — 매입세액 공제이력 없어 과세대상 아님, 확인")])
        code = 11 if inp.간주공급유형 is DeemedSupply.직매장반출 else 14
        return SalesResult(code, hitl=True,
                           근거=[("부가세법 §10", f"간주공급({inp.간주공급유형.value}), 시가과세")])

    # (d) 일반과세 → 기존 taxtype (11/17/22 등)
    return SalesResult(taxtype(inp))


def adjust_base(inp: JudgmentInput) -> int:
    """§29 과세표준 조정 델타. 에누리·환입·매출할인·파손=차감(음수). 장려금·하자보증금=0(공제 안 됨)."""
    차감 = {"에누리", "환입", "매출할인", "파손"}
    if inp.조정사유 in 차감:
        return -inp.조정금액
    return 0  # 장려금·하자보증금 등: 과세표준 불공제(별도 처리)


# ---------------------------------------------------------------- 업종 프로파일 게이팅
# 업종 코드 → (근거태그, 활성 유의사항). 매칭되면 판정 결과의 근거에 리마인더로 부착.
INDUSTRY_REMINDERS = {
    "부동산임대": ("업종:부동산임대", "간주임대료(보증금×이자율) 매출 산입 + 부동산임대공급가액명세서(§29⑩)"),
    "건설도급": ("업종:건설도급", "공급시기 완성도·중간지급조건부 확인(§16)"),
    "수출": ("업종:수출", "영세율 첨부(수출실적명세서)·선적일 공급시기(§21·§15)"),
    "여객운송_개인서비스": ("업종:여객운송·개인서비스", "매출 세계발급면제(령§71)·매입 §88⑤ 불공"),
    "의료교육금융": ("업종:의료·교육·금융", "면세·계산서 원칙(§26), 과세분(성형 등) 구분"),
    "음식숙박소매": ("업종:음식·숙박·소매", "신용카드 발행세액공제 대상(§46) 확인"),
    "전자상거래": ("업종:전자상거래", "판매대행(오픈마켓·PG) 매출 이중계상 금지(§10⑦)"),
    "금스크랩": ("업종:금·스크랩", "금거래계좌 미사용분 불공(조특법)"),
}


def industry_reminders(inp: JudgmentInput) -> List[Tuple[str, str]]:
    """업종 프로파일 게이팅 — 해당 업종 유의사항을 근거 리마인더로 활성화."""
    r = INDUSTRY_REMINDERS.get(inp.업종)
    return [r] if r else []


# ---------------------------------------------------------------- judge 오케스트레이터
def _judge_sales(inp: JudgmentInput) -> Judgment:
    """매출 판단. sales_taxtype 4분기 + 과세표준 조정."""
    sr = sales_taxtype(inp)
    공급가, 세액 = split_amount(inp)
    델타 = adjust_base(inp)
    if 델타:
        공급가 += 델타
        # 세액도 과세매출이면 비례 조정(면세·영세는 세액 0 유지)
        if 세액:
            세액 = 공급가 * 10 // 100 if inp.과세구분 == "과세" else 세액
    근거 = list(sr.근거)
    if 델타:
        근거.append(("부가세법 §29", f"과세표준 조정({inp.조정사유} {델타})"))
    라우팅 = Routing.매입매출 if sr.과세유형 is not None else Routing.일반
    return Judgment(라우팅=라우팅, 구분="매출" if sr.과세유형 is not None else None,
                    과세유형=sr.과세유형, 불공제사유=None,
                    공급가=공급가, 세액=세액,
                    신뢰도="중간" if sr.hitl else "높음", hitl=sr.hitl, 근거=근거)


def _judge_core(inp: JudgmentInput) -> Judgment:
    """부가세 전표 판단 오케스트레이터 S1→S6 (업종 리마인더는 judge 래퍼에서 부착)."""
    if inp.방향 == "매출":
        return _judge_sales(inp)
    근거: List[Tuple[str, str]] = []
    공급가, 세액 = split_amount(inp)

    deny = deny_check(inp)
    근거 += deny.근거

    # 라우팅 오버라이드(여객운송·간이무발급·카드미확인) → 일반전표 전액비용
    if deny.라우팅오버라이드 is Routing.일반:
        return Judgment(라우팅=Routing.일반, 구분=None, 과세유형=None,
                        불공제사유=None, 공급가=inp.총액 if inp.공급가 is None else inp.공급가,
                        세액=0, 신뢰도="중간", hitl=deny.hitl, 근거=근거)

    라우팅 = route(inp)
    if 라우팅 is Routing.일반:
        return Judgment(라우팅=Routing.일반, 구분=None, 과세유형=None, 불공제사유=None,
                        공급가=공급가, 세액=세액, 신뢰도="높음", hitl=False, 근거=근거)

    # 매입매출: 과세유형·불공제 반영
    구분 = inp.방향
    if deny.불공제사유 is not None:
        과세유형 = _UNGWANG_54
        세액_out = 세액          # 불공제는 세액을 분리해 두되 공제 안 함(B5 롤업)
        불공 = deny.불공제사유
    else:
        과세유형 = taxtype(inp)
        세액_out = 세액
        불공 = None

    # 신뢰도·HITL
    필수결측 = (inp.방향 == "매입" and inp.지출목적 is None)
    if 필수결측:
        신뢰도, hitl = "낮음", True
        근거.append(("HITL", "지출목적 결측 — 공제/불공제 판단 불가"))
    else:
        신뢰도 = "높음"
        hitl = deny.hitl
    고정자산 = bool(inp.자본적지출) or (inp.지출목적 is Purpose.자산취득)
    return Judgment(라우팅=Routing.매입매출, 구분=구분, 과세유형=과세유형,
                    불공제사유=불공, 공급가=공급가, 세액=세액_out,
                    신뢰도=신뢰도, hitl=hitl, 근거=근거, 고정자산=고정자산)


def judge(inp: JudgmentInput) -> Judgment:
    """부가세 전표 판단 진입점. 코어 판정 + 업종 프로파일 리마인더 부착."""
    j = _judge_core(inp)
    j.근거 = list(j.근거) + industry_reminders(inp)
    return j


# ---------------------------------------------------------------- 배치 요약
def summarize(cases) -> dict:
    """배치 판정 요약. 전문가 확인용 분포 + HITL 카운트."""
    out = {"총건": 0, "매입매출": 0, "일반": 0, "불공제": 0, "HITL": 0,
           "사유별": Counter()}
    for inp in cases:
        j = judge(inp)
        out["총건"] += 1
        out["매입매출" if j.라우팅 is Routing.매입매출 else "일반"] += 1
        if j.불공제사유 is not None:
            out["불공제"] += 1
            out["사유별"][j.불공제사유.value] += 1
        if j.hitl:
            out["HITL"] += 1
    out["사유별"] = dict(out["사유별"])
    return out
