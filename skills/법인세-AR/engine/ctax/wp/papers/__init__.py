"""조서 등록부. 이 목록의 순서가 계산 · 시트 · 조정.json papers 순서이고, 번호는 시트 이름 앞에 붙는다.

새 조서는 `papers/<id>.py` 파일 하나와 이 목록의 한 줄이다(README.md). 집계 넷(15호 · 3호 · 50호 · 결손금)은
등록부 밖(`summary.py` · `excel.py`)에서 모든 조서를 받아 만든다.
"""
from __future__ import annotations

from importlib import import_module
from types import ModuleType

# (조서 id, 번호). 번호 순서로 둔다.
ORDER: list[tuple[str, str]] = [
    ("corporate_tax", "0"),
    ("taxes_dues", "1"),
    ("accrued_expense", "2"),
    ("accrued_income", "3"),
    ("business_car", "4"),
    ("depreciation", "5"),
    ("entertainment", "6"),
    ("donation", "8"),
    ("loan_interest", "9"),
    ("bad_debt", "10"),
    ("retirement", "11"),
    ("securities", "12"),
    ("dividend", "13"),
    ("prepaid", "14"),
    ("fx", "15"),
    ("prior_error", "16"),
    ("interest_denial", "17"),
    ("credits", "20"),
]

AGGREGATES = ["summary_15", "tax_3", "reserve_50", "loss"]


def entries() -> list[tuple[str, str, ModuleType]]:
    """(id, 번호, 모듈). 모듈은 NAME · FORMS · compute(p, b) · write(bk, p) 를 낸다."""
    out = []
    for pid, no in ORDER:
        mod = import_module(f"{__name__}.{pid}")
        for need in ("NAME", "FORMS", "compute", "write"):
            if not hasattr(mod, need):
                raise AttributeError(f"조서 {pid} 에 {need} 이 없습니다(papers/README.md)")
        out.append((pid, no, mod))
    return out
