"""회사 맥락으로 모으는 회계사 답의 목록.

조서 노란 칸(조서입력.json) 가운데 회사가 해마다 바꾸지 않는 사실만 모은다. 한 해에만 맞는 금액(추계액 · 한도 · 유보 추인액 등)은
모으지 않는다. 근거: 10-29 회의(PSMP 49~51, 유가증권 최초 취득가액 · 대여금 특수관계를 매년 묻지 않게), 10-27(A6k3 88~90, 전기 판단과
일관성), 10-13(qfGo 97, 주식변동은 해마다 입력).

ENGINE: (조서 id, key 또는 key 앞부분, 종류, 대상 이름). key 가 「/」 로 끝나면 앞부분이고 그 뒤가 대상(거래처 · 차량 · 법인 등)이다.
MANUAL: 조서 칸이 없어 `ctax context add` 로 적는 종류. 다음 해 엔진 기본값으로 쓰지 않고 보여 주기만 한다.
"""
from __future__ import annotations

ENGINE = [
    ("loan_interest", "특수관계인/", "가지급금 · 대여금 특수관계", "거래처"),
    ("loan_interest", "소득처분/", "인정이자 소득처분", "거래처"),
    ("business_car", "임차 구분/", "업무용승용차 리스 · 렌트 구분", "차량"),
    ("business_car", "대상/", "업무용승용차 해당 여부", "차량"),
    ("business_car", "부동산임대업 주업", "부동산임대업 주업 여부", ""),
    ("dividend", "지분율/", "피투자법인 지분율", "법인"),
    ("dividend", "상장 여부/", "피투자법인 상장 여부", "법인"),
    ("dividend", "대상 여부/", "수입배당금 익금불산입 대상", "법인"),
    ("credits", "소기업 여부", "소기업 여부", ""),
    ("credits", "수도권 여부", "수도권 여부", ""),
    ("credits", "감면 업종", "감면 업종", ""),
    ("depreciation", "상각방법/", "감가상각 상각방법", "자산 묶음"),
    ("depreciation", "내용연수/", "감가상각 내용연수", "자산 묶음"),
    ("fx", "평가방법 신고", "외화환산 평가방법 신고", ""),
    ("donation", "사회적기업 여부", "사회적기업 여부", ""),
]

# 기업업무추진비 증빙 종류는 줄(일자 · 전표 · 계정 · 금액)마다 고르므로 그대로는 다음 해에 맞는 줄이 없다.
# 거래처별로 모아 「증빙 종류/거래처:<거래처>」 로 두고, 다음 해 조서는 같은 거래처 줄의 까닭 칸에 작년 답을 적기만 한다.
EVIDENCE_PAPER, EVIDENCE_PICK = "entertainment", "증빙 종류"
EVIDENCE_KIND = "기업업무추진비 거래처별 증빙 종류"
EVIDENCE_PREFIX = f"{EVIDENCE_PICK}/거래처:"

COMPANY = "회사"            # 조서가 아닌 맥락(paper 칸에 넣는 값)
MANUAL = {
    "유가증권": "종목. 값은 취득일=… 주식수=… 취득가액=… 꼴",
    "주식변동": "변동일 또는 주주. 값은 변동 내용(양도 · 증자 · 주식 수)",
    "관계기업": "법인 이름. 값은 지분율 · 관계(관계회사 · 지분법 등)",
    "업종코드": "대상 없이 값만(주업종코드)",
    "특수관계인": "이름. 값은 관계(대표이사 · 주주 · 임원 등)",
    "메모": "대상은 짧은 제목. 값은 남길 글",
    "내년메모": "제목(--title). 값은 다음 해 계획서(ctax plan)가 「작년 메모」 후보로 읽는 글. AI 가 쓰면 --by AI 로 넣고 회계사 확인 전이다",
}
NEXT_YEAR = "내년메모"      # 클로징 마감 설명 next_year[] 와 `context add --kind 내년메모` 가 적는다(10-30 설계안 5.3절)
AI = "AI"
# 신고 건에서 저절로 모으는 회사 사실(엔진 기본값으로 쓰지 않는다)
AUTO = {"업종코드": "신고건.json 회사정보 주업종코드", "주주": "신고건.json 주주(사업연도마다 한 벌)",
        "이슈 결론": "AR 이슈 회계사 결론(결론 칸 · ctax set issue)", "서식 제출": "ctax set form 낸다 · 안 낸다"}


def engine_kind(paper: str, key: str) -> tuple[str, str] | None:
    """조서 칸이 맥락으로 모으는 것이면 (종류, 대상), 아니면 None."""
    if paper == EVIDENCE_PAPER and key.startswith(EVIDENCE_PREFIX):
        return EVIDENCE_KIND, key[len(EVIDENCE_PREFIX):]
    for p, k, kind, _what in ENGINE:
        if p != paper:
            continue
        if k.endswith("/") and key.startswith(k) and len(key) > len(k):
            return kind, key[len(k):]
        if key == k:
            return kind, ""
    return None


def fact_id(paper: str, key: str) -> str:
    return f"{paper}|{key}"
