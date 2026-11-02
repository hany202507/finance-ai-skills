# -*- coding: utf-8 -*-
"""연말정산 파이프라인 — 총급여·공제자료 → 결정세액 → 기납부 대조 → 정산세액.

총급여·기납부는 payment/withholding_result 귀속연도 합산. 공제자료는 yearend_deduction.
소득공제·세액공제 모듈 결선. 사실 미비 시 NeedsInfo.
"""
import json
from dataclasses import dataclass

import income_deduction
import tax_credit
from yearend_param import 산출세액


@dataclass
class Settlement:
    총급여: int
    근로소득금액: int
    과세표준: int
    산출세액: int
    세액공제계: int
    결정세액: int
    지방소득세: int
    기납부: int
    정산세액: int              # +추징 / −환급
    명세: dict


@dataclass
class NeedsInfo:
    requests: list


def _load_자료(conn, 귀속연도, payee_id):
    """yearend_deduction 행들을 compute가 받는 자료 dict로 조립."""
    자료 = {}
    rows = conn.execute(
        "SELECT 항목,금액,부속 FROM yearend_deduction WHERE payee_id=? AND 귀속연도=?",
        (payee_id, 귀속연도)).fetchall()
    for 항목, 금액, 부속 in rows:
        val = json.loads(부속) if 부속 else 금액
        자료[항목] = val
    자료.setdefault("부양가족", [{"관계": "본인"}])
    return 자료


def _총급여_기납부(conn, 귀속연도, payee_id):
    row = conn.execute(
        "SELECT COALESCE(SUM(p.gross - p.nontax),0), COALESCE(SUM(w.income_tax),0) "
        "FROM payment p LEFT JOIN withholding_result w ON w.payment_id=p.id "
        "WHERE p.payee_id=? AND p.income_type IN ('근로','상여') "
        "AND substr(p.accrual_ym,1,4)=?",
        (payee_id, str(귀속연도))).fetchone()
    return row[0], row[1]


def settle(conn, 귀속연도, payee_id):
    자료 = _load_자료(conn, 귀속연도, payee_id)
    총급여, 기납부 = _총급여_기납부(conn, 귀속연도, payee_id)

    소득 = income_deduction.compute(conn, 귀속연도, 자료, 총급여)
    if isinstance(소득, list):            # InfoRequest 리스트
        return NeedsInfo(소득)

    산출 = 산출세액(소득.과세표준, conn, 귀속연도)
    세액 = tax_credit.compute(conn, 귀속연도, 자료, 총급여, 산출)

    결정세액 = max(0, 산출 - 세액.공제계)
    지방 = 결정세액 // 10
    정산 = 결정세액 - 기납부
    명세 = {
        "인적공제": 소득.인적공제, "연금보험료": 소득.연금보험료,
        "특별소득공제": 소득.특별소득, "그밖소득공제": 소득.그밖,
        "종합한도초과": 소득.종합한도초과, "소득공제계": 소득.공제계,
        "근로세액공제": 세액.근로, "자녀세액공제": 세액.자녀,
        "연금계좌": 세액.연금계좌, "보장성": 세액.보장성, "의료비": 세액.의료비,
        "교육비": 세액.교육비, "기부금": 세액.기부금, "월세": 세액.월세,
        "표준세액공제": 세액.표준, "세액공제계": 세액.공제계,
    }
    return Settlement(총급여, 소득.근로소득금액, 소득.과세표준, 산출,
                      세액.공제계, 결정세액, 지방, 기납부, 정산, 명세)
