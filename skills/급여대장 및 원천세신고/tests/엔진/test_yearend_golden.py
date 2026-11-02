# -*- coding: utf-8 -*-
"""연말정산 골든 케이스 — 국세청 공식 계산 예시 end-to-end 대사.

앵커(국세청 2025 귀속 안내): 총급여 33,800,000 → 근로소득공제 10,320,000,
근로소득금액 23,480,000. (750만 + (3,380만−1,500만)×15% = 1,032만)
"""
import db
from yearend_param import seed_2025, 근로소득공제, 산출세액
from income_deduction import compute as 소득공제
from tax_credit import compute as 세액공제
from yearend_engine import settle


def _conn():
    conn = db.connect(":memory:"); seed_2025(conn); return conn


def test_국세청예시_근로소득공제():
    # 국세청 공식 예시값
    assert 근로소득공제(33_800_000) == 10_320_000


def test_국세청예시_근로소득금액():
    conn = _conn()
    r = 소득공제(conn, 2025, {"부양가족": [{"관계": "본인"}]}, 33_800_000)
    assert r.근로소득금액 == 23_480_000


def test_국세청예시_과세표준_산출세액_독립검산():
    # 본인만(기본공제 150만), 연금보험료 1,520,100(총급여×4.5% 근사) 가정 → 과세표준·산출세액 손검산
    conn = _conn()
    자료 = {"부양가족": [{"관계": "본인"}], "연금보험료": 1_520_000}
    r = 소득공제(conn, 2025, 자료, 33_800_000)
    # 과세표준 = 23,480,000 − 1,500,000 − 1,520,000 = 20,460,000
    assert r.과세표준 == 20_460_000
    # 산출세액 = 20,460,000 × 15% − 1,260,000 = 3,069,000 − 1,260,000 = 1,809,000
    assert 산출세액(r.과세표준, conn, 2025) == 1_809_000


def test_국세청예시_end_to_end_정산():
    conn = _conn()
    conn.execute("INSERT INTO payee(id,name,resident_type,payee_type) "
                 "VALUES(1,'김근로','거주자','근로자')")
    # 총급여 33,800,000 정확히 (연 1건), 기납부 간이세액표 원천징수 합계 1,800,000 가정
    conn.execute("INSERT INTO payment(payee_id,income_type,accrual_ym,gross,nontax) "
                 "VALUES(1,'근로','2025-12',33800000,0)")
    conn.execute("INSERT INTO withholding_result(payment_id,income_tax,local_tax) "
                 "VALUES((SELECT max(id) FROM payment),1800000,180000)")
    conn.execute("INSERT INTO yearend_deduction(payee_id,귀속연도,항목,금액,부속) "
                 "VALUES(1,2025,'부양가족',0,'[{\"관계\":\"본인\"}]')")
    conn.execute("INSERT INTO yearend_deduction(payee_id,귀속연도,항목,금액,부속) "
                 "VALUES(1,2025,'연금보험료',1520000,NULL)")
    conn.commit()
    s = settle(conn, 2025, 1)
    assert s.총급여 == 33_800_000
    assert s.기납부 == 1_800_000
    assert s.근로소득금액 == 23_480_000
    assert s.과세표준 == 20_460_000
    assert s.산출세액 == 1_809_000
    # 결정세액 = 산출 − 세액공제(근로소득세액공제 등). 정산세액 = 결정 − 기납부
    assert s.결정세액 == max(0, s.산출세액 - s.세액공제계)
    assert s.정산세액 == s.결정세액 - s.기납부


def test_월세_총급여8천만초과_배제():
    conn = _conn()
    r = 세액공제(conn, 2025, {"월세액": 6_000_000}, 90_000_000, 5_000_000)
    assert r.월세 == 0                       # 총급여 8천만 초과 → 요건 미충족


def test_월세_8천만이하_15퍼센트():
    conn = _conn()
    # 총급여 7천만(5,500만 초과 8천만 이하) → 15%
    r = 세액공제(conn, 2025, {"월세액": 6_000_000}, 70_000_000, 5_000_000)
    assert r.월세 == int(6_000_000 * 0.15)
