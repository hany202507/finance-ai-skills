# -*- coding: utf-8 -*-
"""연말정산 연간 롤오버 — 새 귀속연도는 값만 이월하고 검증기록은 비워 게이트가 막게 한다.

원리: 새 연도는 게이트가 자동 차단 → 에이전트가 원문 출처 3자 교차 → 바뀐 것만 갱신·
      안 바뀐 것은 confirm_unchanged로 "전년 동일" 도장 → diff로 변경분 검토 → 게이트 통과.
"매년 제대로 정밀화"를 delta 검증으로 만든다(전체 재작성 금지).
"""
from dataclasses import dataclass

import filing_review


@dataclass
class ParamDiff:
    key: str
    a: object            # 연도 A 값 (없으면 None)
    b: object            # 연도 B 값 (없으면 None)
    상태: str            # '변경' | '신규' | '삭제' | '동일'


def prepare_year(conn, 신규연도, *, 기준연도=None):
    """전년 파라미터·세율표를 신규연도로 값 복제(잠정). provenance는 복제 안 함 → 게이트 차단.

    반환: 개정 확인 워크시트 [{dataset, 전년값, 근거}] — 에이전트가 이걸 들고 소스 대사.
    """
    기준연도 = 기준연도 or (신규연도 - 1)
    # 이미 준비됐으면 중복 복제 방지
    exists = conn.execute("SELECT 1 FROM ref_yearend_param WHERE 귀속연도=? LIMIT 1",
                          (신규연도,)).fetchone()
    if not exists:
        params = conn.execute(
            "SELECT key,value,근거 FROM ref_yearend_param WHERE 귀속연도=?", (기준연도,)).fetchall()
        conn.executemany(
            "INSERT INTO ref_yearend_param(귀속연도,key,value,근거) VALUES(?,?,?,?)",
            [(신규연도, k, v, g) for k, v, g in params])
        brackets = conn.execute(
            "SELECT 하한,세율,누진공제 FROM ref_tax_bracket WHERE 귀속연도=?", (기준연도,)).fetchall()
        conn.executemany(
            "INSERT INTO ref_tax_bracket(귀속연도,하한,세율,누진공제) VALUES(?,?,?,?)",
            [(신규연도, lo, r, p) for lo, r, p in brackets])
        conn.commit()

    # 워크시트: 연말정산데이터셋 각 항목 + 전년 대표값(있으면)
    worksheet = []
    for ds, 지침 in filing_review.연말정산데이터셋.items():
        prov = conn.execute(
            "SELECT basis FROM ref_provenance WHERE dataset=? ORDER BY verified_on DESC LIMIT 1",
            (ds,)).fetchone()
        worksheet.append({"dataset": ds, "확인지침": 지침,
                          "전년근거": prov["basis"] if prov else None,
                          "상태": "확인필요"})
    return worksheet


def diff_years(conn, A, B):
    """귀속연도 A·B 파라미터·세율표 값 비교. 변경/신규/삭제만 반환(동일 제외)."""
    def _params(y):
        return {k: v for k, v in conn.execute(
            "SELECT key,value FROM ref_yearend_param WHERE 귀속연도=?", (y,)).fetchall()}
    pa, pb = _params(A), _params(B)
    diffs = []
    for k in sorted(set(pa) | set(pb)):
        va, vb = pa.get(k), pb.get(k)
        if va == vb:
            continue
        상태 = "신규" if va is None else "삭제" if vb is None else "변경"
        diffs.append(ParamDiff(k, va, vb, 상태))
    # 세율표 구간수·값 비교(요약: 구간별 세율)
    def _brk(y):
        return {lo: (r, p) for lo, r, p in conn.execute(
            "SELECT 하한,세율,누진공제 FROM ref_tax_bracket WHERE 귀속연도=?", (y,)).fetchall()}
    ba, bb = _brk(A), _brk(B)
    for lo in sorted(set(ba) | set(bb)):
        if ba.get(lo) != bb.get(lo):
            diffs.append(ParamDiff(f"세율구간_{lo}", ba.get(lo), bb.get(lo),
                                   "신규" if lo not in ba else "삭제" if lo not in bb else "변경"))
    return diffs


def confirm_unchanged(conn, 신규연도, dataset, *, verified_on, cross_check,
                      basis=None):
    """'전년과 동일' 확인 — 원문대사+cross_check를 신규연도 효력으로 기록해 게이트에 기여."""
    if basis is None:
        prev = conn.execute(
            "SELECT basis FROM ref_provenance WHERE dataset=? ORDER BY verified_on DESC LIMIT 1",
            (dataset,)).fetchone()
        basis = (prev["basis"] if prev else dataset) + " (전년 승계·당해 재확인)"
    filing_review.record_verification(
        conn, dataset, basis=basis, verify_status="원문대사",
        verified_on=verified_on, verify_method="연간 롤오버 confirm_unchanged",
        eff_from=f"{신규연도}-01-01", eff_to=f"{신규연도}-12-31",
        note="전년과 동일 확인", cross_check=cross_check)
