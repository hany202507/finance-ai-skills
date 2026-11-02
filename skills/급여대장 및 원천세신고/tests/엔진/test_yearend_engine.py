# -*- coding: utf-8 -*-
"""연말정산 파이프라인 settle 테스트."""
import db
from yearend_param import seed_2025
from yearend_engine import settle, Settlement, NeedsInfo


def _seed(conn, *, 월급=4_000_000, 월세=150_000, 부양="본인만"):
    seed_2025(conn)
    conn.execute("INSERT INTO payee(id,name,resident_type,payee_type) "
                 "VALUES(1,'홍길동','거주자','근로자')")
    for m in range(1, 13):
        conn.execute("INSERT INTO payment(payee_id,income_type,accrual_ym,gross,nontax) "
                     f"VALUES(1,'근로','2025-{m:02d}',{월급},0)")
        conn.execute("INSERT INTO withholding_result(payment_id,income_tax,local_tax) "
                     f"VALUES((SELECT max(id) FROM payment),{월세},{월세//10})")
    if 부양 == "본인만":
        가족 = '[{"관계":"본인"}]'
    conn.execute("INSERT INTO yearend_deduction(payee_id,귀속연도,항목,금액,부속) "
                 f"VALUES(1,2025,'부양가족',0,'{가족}')")
    conn.commit()


def test_settle_구조_및_정산():
    conn = db.connect(":memory:"); _seed(conn, 월급=4_000_000, 월세=150_000)
    r = settle(conn, 2025, 1)
    assert isinstance(r, Settlement)
    assert r.총급여 == 48_000_000
    assert r.기납부 == 150_000 * 12
    assert r.정산세액 == r.결정세액 - r.기납부
    assert r.지방소득세 == r.결정세액 // 10


def test_settle_환급_음수():
    # 기납부를 크게 → 정산세액 음수(환급)
    conn = db.connect(":memory:"); _seed(conn, 월급=4_000_000, 월세=500_000)
    r = settle(conn, 2025, 1)
    assert r.정산세액 < 0


def test_settle_명세_항목():
    conn = db.connect(":memory:"); _seed(conn)
    r = settle(conn, 2025, 1)
    assert "소득공제계" in r.명세 and "세액공제계" in r.명세
    assert r.명세["인적공제"] == 1_500_000            # 본인만


def test_settle_needs_info():
    conn = db.connect(":memory:"); seed_2025(conn)
    conn.execute("INSERT INTO payee(id,name,resident_type,payee_type) "
                 "VALUES(1,'홍','거주자','근로자')")
    conn.execute("INSERT INTO payment(payee_id,income_type,accrual_ym,gross,nontax) "
                 "VALUES(1,'근로','2025-01',4000000,0)")
    # 배우자 소득요건 미상 → NeedsInfo
    conn.execute("INSERT INTO yearend_deduction(payee_id,귀속연도,항목,금액,부속) "
                 "VALUES(1,2025,'부양가족',0,'[{\"관계\":\"본인\"},{\"관계\":\"배우자\"}]')")
    conn.commit()
    r = settle(conn, 2025, 1)
    assert isinstance(r, NeedsInfo)
