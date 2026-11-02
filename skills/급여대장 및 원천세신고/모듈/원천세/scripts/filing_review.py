# -*- coding: utf-8 -*-
"""신고 전 리뷰 — 세율·금액 데이터가 신고기간에 유효하고 원문 대사됐는지 검증하는 게이트.

**왜 필요한가**: 이 엔진의 계산 로직은 결정론이지만, 정답은 **데이터**가 정한다.
요율·고시액이 낡거나 추측이면 계산이 아무리 정확해도 신고가 틀린다. 실제로 이 프로젝트에서
원문 대사로 다음이 드러났다 —
  · 장애인 부담기초액 가산을 배수로 추정 → 고시는 **절대금액**이었고 값이 전부 달랐다.
  · 한·미 조약 사용료를 15% 단일로 추정 → 원문은 §14(1) 15% / §14(2) 10%로 갈렸다.
  · 국민연금 요율은 **본문(§88③ 1천분의 65 = 13%)만 보면 틀리고**, 부칙 제4조 경과조치가
    2026년 9.5%를 정한다.

**설계**: 코드는 '무엇을 대사해야 하는지'를 결정론으로 뽑는다(아래). 원문 확인 자체는
        에이전트가 korean-law MCP로 수행하고 `record_verification()`으로 기록한다.
        `gate()`가 열려야 신고 산출로 넘어간다.
"""
from dataclasses import dataclass
from datetime import date

# 대사 유효기간(일) — 이보다 오래된 대사는 재확인 대상(고시는 연 단위로 바뀐다)
대사_유효일수 = 180

# 신고에 반드시 필요한 데이터셋 → 원문 확인 지침(에이전트가 korean-law MCP로 수행)
필수데이터셋 = {
    "간이세액표": "소득세법 시행령 별표2 — 국세청 조견표 원문 적재본과 대조. 개정 시행일 확인.",
    "자녀세액공제": "소득세법 시행령 별표2 §3 — 개정으로 갈림(2024.3.1판 vs 2026.3.1판).",
    "국민연금요율": "국민연금법 §88③ **및 부칙 제4조 경과조치**. 본문은 최종 13%, 연도별 실제 요율은 부칙.",
    "국민연금기준소득월액": "국민연금법 시행령·공단 고시. **매년 7월 1일 변경** — 신고월이 7월 경계를 넘는지 확인.",
    "건강보험요율": "국민건강보험법 시행령 §44 — 연도별 개정.",
    "장기요양요율": "노인장기요양보험법 시행령 §4 — 건강보험료 대비 비율.",
    "고용보험요율": "고용보험법 시행령 §12 — 실업급여 근로자 부담분.",
}

# 노무 레이어(부담금 산정 시)
부담데이터셋 = {
    "장애인부담기초액": "고용노동부 고시 「장애인 고용부담금의 부담기초액」 — **배수 아닌 절대금액**. 이행률 구간별.",
    "최저임금": "고용노동부 최저임금 고시 — 미고용 부담기초액과 교차검증(시급×209).",
    "장애인의무고용률": "장애인고용법 §28·시행령 — 민간 의무고용률.",
}


# 연말정산 데이터셋 — **매년 개정** → 원문대사 + 교차확인(cross_check) 둘 다 필수(3자 교차).
# 근거: verification-triangulation. 원문만·웹만 둘 다 함정.
연말정산데이터셋 = {
    "기본세율": "소득세법 §55 — 과세표준 8구간·누진공제. 귀속연도 개정 확인.",
    "근로소득공제": "소득세법 §47 — 총급여 구간별 누진, 한도 2,000만.",
    "인적공제": "소득세법 §50~§51 — 기본 150만·추가공제·소득요건.",
    "자녀세액공제": "소득세법 §59의2 — **2025 귀속 상향(25/30/40만)**. 매년 변동.",
    "연금계좌세액공제": "소득세법 §59의3 — 공제율(12/15%)·한도(600/900만).",
    "특별세액공제": "소득세법 §59의4 — 보장성·의료비(문턱3%)·교육비·기부금. 6세이하 의료비 한도폐지 등 매년 변동.",
    "월세세액공제": "조특법 §95의2 — 공제율(15/17%)·대상한도·요건.",
    "신용카드소득공제": "조특법 §126의2 — 문턱·결제수단별 공제율·한도. 추가공제 항목 매년 변동.",
    "소득공제종합한도": "조특법 §132의2 — 2,500만.",
}


@dataclass
class ReviewItem:
    dataset: str
    사유: str          # '기간미커버' | '원문미대사' | '교차확인누락' | '대사만료'
    확인지침: str
    현재상태: str = ""


def _rows(conn, dataset, 기준일):
    return conn.execute(
        "SELECT * FROM ref_provenance WHERE dataset=? "
        "AND eff_from<=? AND (eff_to IS NULL OR eff_to>=?) "
        "ORDER BY verified_on DESC", (dataset, 기준일, 기준일)).fetchall()


def _stale(verified_on, 기준일):
    if not verified_on:
        return True
    try:
        d0 = date.fromisoformat(verified_on)
        d1 = date.fromisoformat(기준일)
    except ValueError:
        return True
    return (d1 - d0).days > 대사_유효일수


def review(conn, 귀속연월, *, 부담금포함=False, 기준일=None):
    """신고 전 대사 필요 항목을 결정론으로 산출. 빈 리스트 = 게이트 통과.

    귀속연월 'YYYY-MM'. 기준일 미지정 시 귀속월 말(대사 만료 판정 기준).
    """
    기준일 = 기준일 or f"{귀속연월}-28"
    대상 = dict(필수데이터셋)
    if 부담금포함:
        대상.update(부담데이터셋)

    문제 = []
    for ds, 지침 in 대상.items():
        rows = _rows(conn, ds, 기준일)
        if not rows:
            문제.append(ReviewItem(ds, "기간미커버", 지침,
                                  f"{귀속연월} 적용 데이터 없음 — 미적재이거나 효력기간 밖"))
            continue
        # provenance는 증거다 — 기간을 커버하는 **가장 강한 증거**가 지배한다.
        원문 = [r for r in rows if r["verify_status"] == "원문대사"]
        if not 원문:
            r = rows[0]
            문제.append(ReviewItem(ds, "원문미대사", 지침,
                                  f"status={r['verify_status']} / 근거={r['basis']}"))
            continue
        if all(_stale(r["verified_on"], 기준일) for r in 원문):
            최신 = max(원문, key=lambda r: r["verified_on"] or "")
            문제.append(ReviewItem(ds, "대사만료", 지침,
                                  f"최종 대사 {최신['verified_on']} (>{대사_유효일수}일)"))
    return 문제


def gate(conn, 귀속연월, *, 부담금포함=False):
    """신고 게이트. (통과여부, 문제목록)."""
    문제 = review(conn, 귀속연월, 부담금포함=부담금포함)
    return (not 문제), 문제


def review_yearend(conn, 귀속연도, *, 기준일=None):
    """연말정산 데이터 3자 교차검증. 원문대사 **및** 교차확인(cross_check) 둘 다 있어야 통과."""
    기준일 = 기준일 or f"{귀속연도}-12-31"
    문제 = []
    for ds, 지침 in 연말정산데이터셋.items():
        rows = _rows(conn, ds, 기준일)
        원문 = [r for r in rows if r["verify_status"] == "원문대사"]
        if not 원문:
            문제.append(ReviewItem(ds, "원문미대사" if rows else "기간미커버", 지침,
                                  (f"status={rows[0]['verify_status']}" if rows else "미적재")))
            continue
        if not any((r["cross_check"] or "").strip() for r in 원문):
            문제.append(ReviewItem(ds, "교차확인누락", 지침,
                                  "원문대사됨 — 웹·개정 교차확인(cross_check) 미기록"))
        elif all(_stale(r["verified_on"], 기준일) for r in 원문):
            문제.append(ReviewItem(ds, "대사만료", 지침, "재확인 필요"))
    return 문제


def gate_yearend(conn, 귀속연도):
    문제 = review_yearend(conn, 귀속연도)
    return (not 문제), 문제


def record_verification(conn, dataset, *, basis, eff_from, eff_to=None,
                        verify_status="원문대사", verified_on=None,
                        verify_method="korean-law MCP", note=None, cross_check=None):
    """에이전트가 법령 원문으로 대사한 결과를 기록. 신고 게이트는 이 기록을 본다.

    cross_check: 연말정산 등 매년 개정 항목은 웹·개정 교차확인 내용을 함께 기록해야 게이트 통과.
    """
    conn.execute(
        "INSERT INTO ref_provenance(dataset,basis,verify_status,verified_on,"
        "verify_method,eff_from,eff_to,note,cross_check) VALUES(?,?,?,?,?,?,?,?,?)",
        (dataset, basis, verify_status, verified_on, verify_method,
         eff_from, eff_to, note, cross_check))
    conn.commit()
