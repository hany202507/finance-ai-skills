# -*- coding: utf-8 -*-
"""DB 스파인 — 스키마 생성·효력일자 조회 테스트."""
import db


def test_schema_creates_core_tables():
    conn = db.connect(":memory:")
    names = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"company", "payee", "payee_contract", "dependent",
            "insurance_enrollment", "payment", "payment_line",
            "withholding_result", "filing",
            "ref_income_type", "ref_insurance_rate", "ref_treaty_rate",
            "ref_simple_tax_table"} <= names


def test_effective_row_picks_valid_interval():
    conn = db.connect(":memory:")
    conn.execute("INSERT INTO payee(id,name,rrn_masked,resident_type,payee_type) "
                 "VALUES(1,'홍길동','800101-1******','거주자','근로자')")
    conn.execute("INSERT INTO payee_contract(payee_id,monthly_pay,eff_from,eff_to) "
                 "VALUES(1,3000000,'2026-01-01','2026-06-30')")
    conn.execute("INSERT INTO payee_contract(payee_id,monthly_pay,eff_from,eff_to) "
                 "VALUES(1,3300000,'2026-07-01',NULL)")
    conn.commit()
    row = db.effective_row(conn, "payee_contract", {"payee_id": 1}, "2026-07-15")
    assert row["monthly_pay"] == 3300000
    row2 = db.effective_row(conn, "payee_contract", {"payee_id": 1}, "2026-03-01")
    assert row2["monthly_pay"] == 3000000


def test_effective_row_none_when_out_of_range():
    conn = db.connect(":memory:")
    conn.execute("INSERT INTO payee(id,name,rrn_masked,resident_type,payee_type) "
                 "VALUES(1,'홍길동','800101-1******','거주자','근로자')")
    conn.execute("INSERT INTO payee_contract(payee_id,monthly_pay,eff_from,eff_to) "
                 "VALUES(1,3000000,'2026-01-01','2026-06-30')")
    conn.commit()
    assert db.effective_row(conn, "payee_contract", {"payee_id": 1}, "2025-12-31") is None
