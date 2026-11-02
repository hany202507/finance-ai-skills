# -*- coding: utf-8 -*-
"""입사·퇴사 이벤트 기반 의무 스캐너 — 캘린더(정기 신고)가 못 잡는 사건성 의무.

정기 신고는 compliance_calendar가, **사건이 만든 기한**은 이 모듈이 잡는다:
  입사 → 근로계약서(즉시)·건강보험 취득(14일)·연금/고용 취득(다음달 15일)
  퇴사 → 상실신고(14일/다음달 15일)·**퇴직금 14일 내 지급(근퇴법 §9)**·
         **중도퇴사 연말정산(퇴사월 급여 지급 시, 소득법 §137)**·퇴직소득세 원천징수
외주 SaaS에서 가장 자주 터지는 사고 지점 — payee의 join_date/leave_date를 스캔해 자동 표면화.
"""
from dataclasses import dataclass
from datetime import date, timedelta


@dataclass
class EventObligation:
    payee_id: int
    성명: str
    이벤트: str          # '입사' | '퇴사'
    의무: str
    기한: str            # YYYY-MM-DD
    dday: int            # 기준일 대비 (음수=지남)
    근거: str


def _다음달15(d):
    y, m = (d.year, d.month + 1) if d.month < 12 else (d.year + 1, 1)
    return date(y, m, 15)


def _다음달10(d):
    y, m = (d.year, d.month + 1) if d.month < 12 else (d.year + 1, 1)
    return date(y, m, 10)


def 계속근로1년(입사, 퇴사):
    """계속근로 1년을 날짜로 센다(근퇴법 §4① 단서). 입사일 다음 해 같은 날의 전날까지 다니면 1년이다.
    일수로 세면 평년 1년(364일 차이)을 1년 미만으로 보고, 윤년이 낀 해는 하루가 어긋난다.
    2월 29일 입사자는 다음 해 3월 1일을 같은 날로 본다. 입퇴사처리 스킬의 퇴직금 계산과 같은 기준이다."""
    try:
        돌 = date(입사.year + 1, 입사.month, 입사.day)
    except ValueError:
        돌 = date(입사.year + 1, 3, 1)
    return 퇴사 >= 돌 - timedelta(days=1)


# (의무, 기한계산, 근거)
입사의무 = [
    ("근로계약서 서면 명시·교부", lambda d: d, "근기법 §17 · §114 (미교부 500만원 이하 벌금)"),
    ("건강보험 자격취득신고", lambda d: d + timedelta(days=14), "건보법 §8② (14일 이내)"),
    ("국민연금·고용보험 자격취득신고", _다음달15, "연금법 시행규칙 §6① · 징수법 §16의10③ (다음달 15일)"),
]
퇴사의무 = [
    ("건강보험 자격상실신고", lambda d: d + timedelta(days=15), "건보법 §9①3 · §10② · 시행규칙 §4④2 (끝난 날의 다음 날부터 14일)"),
    ("국민연금·고용보험 자격상실신고", _다음달15, "연금법 시행규칙 §6① · 징수법 §16의10④ (다음달 15일)"),
    ("퇴직금 지급", lambda d: d + timedelta(days=14),
     "근퇴법 §9 (14일 이내 — 합의 연장 가능하나 미지급 시 지연이자 20%·형사처벌)"),
    ("중도퇴사 연말정산(약식)", lambda d: date(d.year, d.month, 25) if d.day <= 25 else _다음달10(d),
     "소득법 §137① (퇴사월 급여 지급 시 정산) — run_yearend.중도정산 실행"),
    ("퇴직소득세 원천징수·이행상황신고 포함", _다음달10, "소득법 §146·§128 (지급월 다음달 10일)"),
]


def scan_events(conn, 기준일, *, 창=45, company_id=None):
    """기준일 ±창 내 입사·퇴사자의 사건성 의무를 기한·D-day와 함께 반환."""
    ref = date.fromisoformat(기준일)
    lo, hi = (ref - timedelta(days=창)).isoformat(), (ref + timedelta(days=창)).isoformat()
    cond, args = "", [lo, hi, lo, hi]
    if company_id is not None:
        cond = " AND company_id=?"
        args.append(company_id)
    rows = conn.execute(
        f"SELECT id,name,join_date,leave_date FROM payee "
        f"WHERE payee_type='근로자' AND ((join_date BETWEEN ? AND ?) "
        f"OR (leave_date BETWEEN ? AND ?)){cond}", args).fetchall()

    out = []
    for r in rows:
        if r["join_date"] and lo <= r["join_date"] <= hi:
            d = date.fromisoformat(r["join_date"])
            for 의무, fn, 근거 in 입사의무:
                due = fn(d)
                out.append(EventObligation(r["id"], r["name"], "입사", 의무,
                                           due.isoformat(), (due - ref).days, 근거))
        if r["leave_date"] and lo <= r["leave_date"] <= hi:
            d = date.fromisoformat(r["leave_date"])
            # 근속 1년 미만이면 퇴직급여 지급의무 없음(근퇴법 §4①)
            근속1년미만 = bool(r["join_date"]) and not 계속근로1년(date.fromisoformat(r["join_date"]), d)
            for 의무, fn, 근거 in 퇴사의무:
                if 근속1년미만 and 의무.startswith("퇴직금"):
                    out.append(EventObligation(
                        r["id"], r["name"], "퇴사",
                        "퇴직금 지급의무 없음(근속 1년 미만) — 잔여연차수당만 확인",
                        d.isoformat(), (d - ref).days, "근퇴법 §4① (계속근로 1년 이상만)"))
                    continue
                if 근속1년미만 and 의무.startswith("퇴직소득세"):
                    continue                        # 퇴직금 없으면 퇴직소득세도 없음
                due = fn(d)
                out.append(EventObligation(r["id"], r["name"], "퇴사", 의무,
                                           due.isoformat(), (due - ref).days, 근거))
    return sorted(out, key=lambda o: o.기한)
