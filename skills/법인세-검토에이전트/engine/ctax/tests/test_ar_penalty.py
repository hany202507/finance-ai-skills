"""AR penalty 규칙 시험(4회차). 수수료 · 용역 대가와 단수 줄은 세금 낱말이 있어도 「세금 · 과태료 표기」 로 세지 않고,
초과배출부과금(법인세법 제21조 제5호)은 센다. 합성 장부만 쓴다."""
from __future__ import annotations

from ctax.tests.test_ar import by_title, journal, run


def _row(code, name, dr, memo, no):
    return {"date": "2025-06-30", "no": f"9{no:04d}", "kind": "차변", "account": code, "account_name": name, "debit": dr,
            "credit": 0, "partner_code": "", "partner": "", "memo_code": "", "memo": memo, "closing": False}


def _penalty(ar):
    return next(i for i in ar["issues"] if i.get("rule") == "penalty")


def test_fee_line_is_not_a_penalty():
    jr = [r for r in journal() if r["account"] != "960"] + [_row("960", "잡손실", 450_000, "법인세 경정청구 수수료", 1),
                                                            _row("960", "잡손실", 50_000, "부가세 단수차액", 2)]
    pen = _penalty(run(jr=jr))
    assert not any(b.startswith("잡손실 적요") for b in pen["basis"])


def test_sanction_charge_counts():
    jr = [r for r in journal() if r["account"] != "960"] + [_row("960", "잡손실", 450_000, "2025년상반기대기초과배출부과금", 1),
                                                            _row("960", "잡손실", 50_000, "법인세 신고대행 수수료", 2)]
    pen = _penalty(run(jr=jr))
    line = next(b for b in pen["basis"] if b.startswith("잡손실 적요"))
    assert "1줄 450,000원" in line and "초과배출부과금" in line
    assert by_title(run(jr=jr), "가산세 · 과태료로 보이는")
