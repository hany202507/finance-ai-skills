# -*- coding: utf-8 -*-
"""보통예금 출금은 손익계정과 직접 상대하지 않는다 — 검산 함수와 엔진 규칙."""
import os, sys
import openpyxl
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from verify_close import pl_direct_cash_vouchers
from close_engine import Engine


def _sheet(rows):
    wb = openpyxl.Workbook(); ws = wb.active
    ws.append(["전표No", "일자", "구분", "계정코드", "계정", "차변", "대변"])
    for no, code, dr, cr in rows:
        ws.append([no, "2026-01-01", "x", code, "", dr or None, cr or None])
    return ws


def test_direct_expense_payment_is_flagged():
    ws = _sheet([(1, 819, 100, 0), (1, 103, 0, 100)])
    assert pl_direct_cash_vouchers(ws) == [1]


def test_payable_route_passes():
    ws = _sheet([(1, 819, 100, 0), (1, 253, 0, 100), (2, 253, 100, 0), (2, 103, 0, 100)])
    assert pl_direct_cash_vouchers(ws) == []


def test_receipt_and_asset_are_not_counted():
    ws = _sheet([(1, 103, 50, 0), (1, 901, 0, 50),     # 이자수익 입금
                 (2, 962, 100, 0), (2, 103, 0, 100)])   # 임차보증금 지급
    assert pl_direct_cash_vouchers(ws) == []


def test_engine_helpers():
    assert Engine.is_pl(801) and Engine.is_pl(951)
    assert not Engine.is_pl(962) and not Engine.is_pl(253) and not Engine.is_pl(103)
