"""시험용 합성 회사 입력과 빈 양식. 실제 회사 자료가 아니다.

샘플기계(가상): 수도권 밖 기타 기계 및 장비 제조업(별표 3 제13호, 120억원), 매출액 90억원 → 소기업 · 수도권 외 · 감면율 30%.
2025 과세연도. 각 사업연도 소득 8억2천만원 중 이자수익 2천만원은 감면 제외, 이월결손금 1억원(생긴 사업 불분명)은 소득금액 비례 안분.
상시근로자 30 → 28.5(1.5명 감소)라 감면한도 92,500,000원. 같은 해 통합고용 세액공제 4천만원은 함께 받고 최저한세로 일부 이월.
기대값: 감면소득 702,439,025원, ⑦ = ⑧ = ⑨ = 34,185,365원, 통합고용 당기 32,214,635원 · 이월 7,785,365원.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from openpyxl import Workbook

from .. import xlsx as X
from ..inputdef import write_sheet
from .model import ALIASES, COMPANY_ROWS, DEF_INTRO, EXCLUDED, SOURCE, STARTUP_YEAR, S_CO, definitions

COMPANY = {
    "과세연도 시작일": date(2025, 1, 1),
    "과세연도 종료일": date(2025, 12, 31),
    "중소기업": "Y",
    "업종": "제조업",
    EXCLUDED: "N",
    "일반 서적 출판업": "N",
    "별표 3 업종 호": 13,
    "매출액": 9_000_000_000,
    STARTUP_YEAR: "N",
    "본점 수도권": "N",
    "감면 사업장 수도권": "N",
    "각 사업연도 소득금액": 820_000_000,
    "감면 제외 소득": 20_000_000,
    "이월결손금 · 비과세 · 소득공제": 100_000_000,
    "공제액등이 생긴 사업": "불분명",
    "과세표준": 720_000_000,
    "산출세액": 116_800_000,
    "상시근로자 수(해당)": 28.5,
    "상시근로자 수(직전)": 30,
    "최저한세율": 0.07,
    "먼저 적용할 다른 최저한세 대상 감면 · 공제": 0,
    "통합고용 세액공제": 40_000_000,
    "제127조 제4항 세액공제": 0,
    "같은 사업장 다른 감면": 0,
    "적용 선택": "중소기업특별세액감면",
}
EXPECT = {"reduced_income": 702_439_025, "a7": 34_185_365, "a9": 34_185_365, "total": 34_185_365, "limit": 92_500_000,
          "emp_now": 32_214_635, "emp_carry": 7_785_365, "rate": 0.3, "key": "소기업|수도권 외|그 밖"}


def write(path: Path, company: dict | None = None, blank: bool = False, drop: tuple = ()) -> Path:
    """회사 시트 하나. blank 면 값 없이 머리글과 설명만. drop 의 항목은 값을 비운다."""
    co = {} if blank else dict(COMPANY, **{ALIASES.get(k, k): v for k, v in (company or {}).items()})
    wb = Workbook()
    ws = wb.active
    ws.title = S_CO
    X.header(ws, 1, ["항목", "값", "설명", "받는 곳"])
    for i, (key, kind, default, desc) in enumerate(COMPANY_ROWS, start=2):
        X.cell(ws, i, 1, key)
        v = None if key in drop else co.get(key)
        c = X.cell(ws, i, 2, v, kind="input", money=kind == "won")
        if kind == "date":
            c.number_format = "yyyy-mm-dd"
        X.cell(ws, i, 3, desc + (" (필수)" if default is None else ""), wrap=True)
        X.cell(ws, i, 4, SOURCE.get(key, ""), wrap=True)
    X.widths(ws, [42, 24, 90, 48])
    write_sheet(wb, definitions(), DEF_INTRO)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return Path(path)
