"""계정위험 제안과 위험 기반 절차 계획(2026-10-16).

분석적 검토 결과(이슈 · 부정 패턴 · 계정 금액)에서 영역마다 위험을 제안하고, 그 위험으로 4000 표준 절차를 고르고 범위(표본 위험 수준)를 정한다.
엔진은 제안만 한다. 2302 의 감사인 기입란(고유위험 · 통제위험 · 유의적 위험)이 있으면 그 값이 앞선다.

  area_plan(d, area, ...)        영역 하나의 위험과 근거 {area, level, significant, assertions, reasons, issues, source}
  step_plan(plan, assertions)    표준 절차 한 줄의 계획 {plan, reason}
  sample_risk(plan)              표본 위험 수준(sampling.yaml risk_levels 의 키)

판정 규칙(방법론 값. 바꾸면 이 주석에 날짜와 까닭을 남긴다)
  높음  열린 이슈 금액이 수행중요성 이상
  보통  열린 이슈가 있거나(수행중요성 미만), 영역 잔액이 수행중요성 초과
  낮음  그 밖
  유의적 위험 제안: 부정 패턴 후보(patterns.yaml)가 켜지고 수행중요성 이상 이슈도 있는 영역. 매출(P)은 수익인식 부정위험 추정(감사기준서 240 문단 27)
  패턴 후보는 영역마다 여럿 켜지므로 근거에는 금액 큰 둘만 적는다
근거 기준서: 감사기준서 330 문단 7(위험평가 수준이 높을수록 더 설득력 있는 증거), 문단 21(유의적 위험에는 구체적으로 대응하는 실증절차)
"""
from __future__ import annotations

import json
from pathlib import Path

ASSERTIONS = ("E/O", "C", "A/V", "CO", "RO", "P/CL")
# 2302 주장 묶음 → 한공회 4000 표지의 주장 약어
TO_COVER = {"E/O": {"E", "O"}, "C": {"C"}, "A/V": {"A", "V"}, "CO": {"CO"}, "RO": {"RO"}, "P/CL": {"P", "CL", "U"}}
REVENUE_AREAS = {"P": ("E/O", "CO")}          # 수익인식 부정위험 추정(감사기준서 240 문단 27)이 걸리는 영역과 주장
LEVELS = ("낮음", "보통", "높음")
# 고유위험요소(감사기준서 315 문단 12(f) · 31(a), 2026-11-03). 엔진은 영역 성격과 분석 결과로 제안만 한다. 고르는 것은 감사인이다
FACTORS = ("복잡성", "주관성", "변화", "불확실성", "경영진 편의")
# 회계추정치가 든 영역(감사기준서 540). 추정은 주관성 · 불확실성이 따른다(315 문단 A7). 영역 코드는 accounts.yaml area
ESTIMATE_AREAS = {"C": "대손충당금", "E": "재고자산 평가", "G": "내용연수 · 손상", "H": "상각 · 손상", "EE": "퇴직급여 측정",
                  "FF": "충당부채", "CL": "우발부채", "T": "법인세 · 이연법인세", "DL": "리스 할인율 · 기간"}
# 측정이나 인식 규정이 여러 단계인 영역(315 문단 A7 복잡성)
COMPLEX_AREAS = {"P": "수익인식(수행의무 · 기간 배분)", "DL": "리스(사용권자산 · 리스부채 측정)"}
SOURCE_ENGINE, SOURCE_AUDITOR = "엔진 제안(확인 전)", "감사인 2302"


def _idx(d: Path, name: str, default):
    p = Path(d) / "_색인" / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def _auditor(d: Path) -> dict:
    """2302 기입란 {(이름): 값}. 파일이 없거나 읽지 못하면 빈 dict."""
    from .analysis.wp_util import carry_values

    try:
        return {lab: v for (_sheet, lab), v in carry_values(Path(d), "2302").items()}
    except Exception:
        return {}


def _won(x) -> str:
    return f"{int(round(x)):,}원"


def area_plan(d: Path, area: str, issues: list[dict] | None = None, analysis: dict | None = None,
              performance: float | None = None, auditor: dict | None = None) -> dict:
    d = Path(d)
    issues = issues if issues is not None else _idx(d, "이슈.json", {"issues": []})["issues"]
    an = analysis if analysis is not None else _idx(d, "분석.json", {})
    pm = performance
    if pm is None:
        v = (an.get("inputs") or {}).get("materiality.performance")
        pm = v.get("value") if isinstance(v, dict) else v
    reasons, assertions, nos = [], set(), []
    level = 0
    balance = sum(abs(a.get("cur_disp") or 0) for a in an.get("accounts") or [] if a.get("area") == area)
    if pm and balance > pm:
        level = max(level, 1)
        reasons.append(f"잔액 {_won(balance)} > 수행중요성 {_won(pm)}")
    for i in issues:
        if i.get("status") != "열림" or i.get("area") != area:
            continue
        amt = abs(i.get("amount") or 0)
        big = bool(pm and amt >= pm)
        level = max(level, 2 if big else 1)
        assertions |= set(i.get("assertions") or [])
        nos.append(i["no"])
        reasons.append(f"이슈 {i['no']} {i['title']} {_won(amt)}" + (" (수행중요성 이상)" if big else ""))
    # 부정 패턴은 후보 묶음이라 영역마다 여럿 켜진다. 패턴만으로 유의적 위험을 올리지 않고, 수행중요성 이상의 열린 이슈가 함께 있을 때만 올린다
    significant = False
    pats = sorted((p for p in an.get("patterns") or [] if p.get("area") == area), key=lambda p: -(p.get("amount") or 0))
    big_issue = level == 2
    if pats:
        if big_issue:
            significant = True
        shown = ", ".join(f"{p['id']} {p['title']}" for p in pats[:2]) + (f" 외 {len(pats) - 2}개" if len(pats) > 2 else "")
        reasons.append(f"부정 패턴 후보 {shown}" + ("" if big_issue else " (수행중요성 이상 이슈가 없어 유의적 위험으로 올리지 않음)"))
    if area in REVENUE_AREAS:
        significant = True
        assertions |= set(REVENUE_AREAS[area])
        reasons.append("수익인식 부정위험 추정(감사기준서 240 문단 27)")
    out = {"area": area, "level": LEVELS[level], "significant": significant,
           "assertions": [a for a in ASSERTIONS if a in assertions], "reasons": reasons, "issues": nos,
           "source": SOURCE_ENGINE, "suggested": {"level": LEVELS[level], "significant": significant}}
    aud = auditor if auditor is not None else _auditor(d)
    lv, sig = aud.get(f"고유위험: {area}"), aud.get(f"유의적 위험: {area}")
    if lv in LEVELS:
        out.update(level=lv, source=SOURCE_AUDITOR)
    if sig in ("예", "아니오"):
        out.update(significant=sig == "예", source=SOURCE_AUDITOR)
    return out


def inherent_factors(plan: dict, patterns: list[dict] | None = None) -> list[tuple[str, str]]:
    """영역 하나의 고유위험요소 제안 [(요소, 근거)]. 확인 전 엔진 제안이고 2302 「고유위험요소」 칸은 감사인이 적는다.
    변화: 분석적 검토의 열린 이슈. 주관성 · 불확실성: 회계추정치 영역. 복잡성: 측정 · 인식이 여러 단계인 영역.
    경영진 편의: 수익인식 부정위험 추정(감사기준서 240 문단 27) 영역과 부정 패턴 후보가 켜진 영역."""
    area = plan["area"]
    out = []
    if area in COMPLEX_AREAS:
        out.append(("복잡성", COMPLEX_AREAS[area]))
    if area in ESTIMATE_AREAS:
        out.append(("주관성", f"회계추정치({ESTIMATE_AREAS[area]})"))
    if plan.get("issues"):
        out.append(("변화", "분석적 검토 이슈 " + ", ".join(str(n) for n in plan["issues"])))
    if area in ESTIMATE_AREAS:
        out.append(("불확실성", f"측정 불확실성({ESTIMATE_AREAS[area]})"))
    pats = [p for p in patterns or [] if p.get("area") == area]
    if area in REVENUE_AREAS or pats:
        why = ["수익인식 부정위험 추정(감사기준서 240 문단 27)"] if area in REVENUE_AREAS else []
        why += [f"부정 패턴 후보 {len(pats)}개"] if pats else []
        out.append(("경영진 편의", " · ".join(why)))
    return out


def factors_text(factors: list[tuple[str, str]]) -> str:
    return "고유위험요소 제안: " + (" · ".join(f"{f}({w})" for f, w in factors) if factors else "엔진이 찾은 요소 없음")


def cover_assertions(plan: dict) -> set[str]:
    return set().union(*(TO_COVER[a] for a in plan["assertions"])) if plan["assertions"] else set()


def step_plan(plan: dict, step_assertions: list[str], part: int = 1, condition: str | None = None) -> dict:
    """표준 절차 한 줄의 계획. 해당 여부는 감사인이 정한다(이 값은 참고).
    condition 은 회사 자료로 본 전제 조건(예: 기타수익 계정 없음). 있으면 위험보다 먼저 「판단 필요」 로 둔다."""
    hit = sorted(cover_assertions(plan) & {a.strip() for a in step_assertions})
    if part == 2:
        return {"plan": "조건 확인", "reason": condition or "추가 고려 절차. 조건(원문 안내)이 맞을 때만 수행"}
    if condition:
        return {"plan": "판단 필요", "reason": condition}
    if hit and plan["level"] != "낮음":
        why = f"위험 주장 {', '.join(hit)}" + (f" · 이슈 {', '.join(str(n) for n in plan['issues'])}" if plan["issues"] else "")
        return {"plan": "수행 · 위험 대응" + (" (유의적 위험: 세부테스트 포함)" if plan["significant"] else ""), "reason": why}
    if plan["level"] != "낮음":
        return {"plan": "수행 · 기본", "reason": "유의적 계정 기본 절차(위험 주장과 겹치지 않음)"}
    return {"plan": "판단 필요", "reason": "위험 낮음. 생략하면 사유를 적는다"}


def sample_risk(plan: dict) -> str:
    """표본 위험 수준. 위험이 높을수록 더 설득력 있는 증거(감사기준서 330 문단 7(b)) → 신뢰수준을 높인다."""
    return "높음" if plan["significant"] else plan["level"]


def text(plan: dict) -> str:
    sig = "유의적 위험" if plan["significant"] else "유의적 위험 아님"
    return f"고유위험 {plan['level']} · {sig} · 위험 주장 {', '.join(plan['assertions']) or '없음'} ({plan['source']})"

