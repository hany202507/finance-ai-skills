# -*- coding: utf-8 -*-
"""판정 함수 단위 시험. 실제 회사 자료는 넣지 않는다(가상 숫자)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import quick_review as q  # noqa: E402


def L(date, no, code, name, dr=0, cr=0, who="갑"):
    return dict(date=date, no=no, code=code, name=name, dr=dr, cr=cr, who=who, memo="")


def ledger():
    return [
        L("2026-01-05", "1", 108, "외상매출금", dr=1100), L("2026-01-05", "1", 401, "상품매출", cr=1000),
        L("2026-01-05", "1", 255, "부가세예수금", cr=100),
        L("2026-02-03", "2", 146, "상품", dr=500), L("2026-02-03", "2", 135, "부가세대급금", dr=50),
        L("2026-02-03", "2", 251, "외상매입금", cr=550),
        L("2026-03-31", "3", 255, "부가세예수금", dr=100), L("2026-03-31", "3", 135, "부가세대급금", cr=50),
        L("2026-03-31", "3", 261, "미지급세금", cr=50),
    ]


def ret(ran):
    return dict(ran=ran, pages=["본지1", "본지2"], biz=[(1, "1234567890"), (2, "1234567890")],
                periods=[(1, "01-01~03-31", "2026년 1기")], kind="예정", company="(주)가", forms={})


GOOD = {1: (1000, 100), 9: (1000, 100), 10: (500, 50), 16: (500, 50), 18: (500, 50),
        "㉰": (None, 50), 30: (0, 50), 31: (1000, None), 35: (1000, None)}


def verdicts(ran):
    lines = ledger()
    F = q.ledger_facts(lines)
    return {r["no"]: r["verdict"] for r in q.review(lines, F, None, ret(ran))}


def test_clean_case_passes_ledger_checks():
    v = verdicts(GOOD)
    for no in (1, 2, 3, 11, 12, 13, 15):
        assert v[no] == q.PASS, (no, v[no])
    assert v[10] == q.NA


def test_formula_break_is_flagged():
    bad = dict(GOOD)
    bad[30] = (0, 60)
    v = verdicts(bad)
    assert v[3] == q.CHECK and v[15] == q.CHECK


def test_output_tax_mismatch():
    bad = dict(GOOD)
    bad[1] = bad[9] = (1000, 130)
    assert verdicts(bad)[11] == q.CHECK


def test_missing_main_page_is_unread():
    lines = ledger()
    F = q.ledger_facts(lines)
    R = ret({})
    R["pages"] = ["카드갑"]
    res = q.review(lines, F, None, R)
    assert all(r["verdict"] == q.UNREAD for r in res if r["no"] >= 3)


def test_ledger_imbalance():
    lines = ledger()
    lines[0]["dr"] = 1000
    F = q.ledger_facts(lines)
    res = {r["no"]: r for r in q.review(lines, F, None, ret(GOOD))}
    assert res[2]["verdict"] == q.CHECK and res[2]["diff"] == -100


def test_ai_material_lists_taxi_candidate():
    lines = ledger() + [
        L("2026-03-10", "9", 812, "여비교통비(판)", dr=10000, who="가나택시"),
        L("2026-03-10", "9", 135, "부가세대급금", dr=1000, who="가나택시"),
        L("2026-03-10", "9", 253, "미지급금", cr=11000),
    ]
    F = q.ledger_facts(lines)
    R = ret(GOOD)
    txt = q.ai_material(lines, F, R, q.review(lines, F, None, R))
    assert "가나택시" in txt and "안분 대상 아님" in txt
