# -*- coding: utf-8 -*-
"""원천세 DB 스파인 — SQLite 연결·스키마 적용·효력일자 조회.

효력일자(eff_from~eff_to, NULL=무기한) 구간에서 유효한 1행을 뽑는 게 핵심 헬퍼.
"""
import os
import sqlite3

SCHEMA = os.path.join(os.path.dirname(__file__), "schema.sql")


def connect(path=":memory:"):
    """스키마가 적용된 연결을 반환한다."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    with open(SCHEMA, encoding="utf-8") as fh:
        conn.executescript(fh.read())
    return conn


def effective_row(conn, table, where, on_date):
    """`table`에서 `where` 조건 + on_date가 효력구간에 드는 최신 1행을 dict로 반환.

    구간 중첩 시 eff_from이 가장 늦은(=최신 개정) 행을 택한다.
    """
    clause = " AND ".join(f"{k}=:{k}" for k in where)
    q = (f"SELECT * FROM {table} WHERE {clause} "
         f"AND eff_from<=:d AND (eff_to IS NULL OR eff_to>=:d) "
         f"ORDER BY eff_from DESC LIMIT 1")
    r = conn.execute(q, {**where, "d": on_date}).fetchone()
    return dict(r) if r else None
