"""시험용 합성 회사 입력과 빈 양식. 실제 회사 자료가 아니다.

샘플창업(가상): 2023-03-02 수도권 밖에서 제조업으로 창업한 일반(청년 아님) 법인. 2023 결손, 2024 처음 소득 → 2025 과세연도는 감면 2차 연도.
기대값(2025 과세연도): 감면율 50%, 추가감면율 12%(상시근로자 12 → 15, 종전 제7항 × 50/100),
11O 6,720,000원 · 111 대상 28,000,000원 → 최저한세로 2,000,000원 배제 → 26,000,000원, 합계 32,720,000원.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font

from .. import xlsx as X
from ..inputdef import write_sheet
from .model import COMPANY_ROWS, DEF_INTRO, SOURCE, S_CO, S_YEARS, YEAR_COLS, YEAR_SOURCE, definitions

COMPANY = {
    "과세연도 시작일": date(2025, 1, 1),
    "과세연도 종료일": date(2025, 12, 31),
    "중소기업": "Y",
    "창업일": date(2023, 3, 2),
    "업종": "제조업",
    "업종 단서 제외 업종": "N",
    "창업 지역": "수도권 밖",
    "대표자 생년월일": date(1980, 5, 10),
    "대표자 병역 개월 수": 24,
    "대표자 최대주주": "Y",
    "신성장 서비스업": "N",
    "산출세액": 56_000_000,
    "과세표준": 400_000_000,
    "감면소득": 400_000_000,
    "수입금액": 2_500_000_000,
    "최저한세율": 0.07,
    "먼저 적용할 다른 최저한세 대상 감면 · 공제": 2_000_000,
    "통합고용 · 고용증대 세액공제": 5_000_000,
    "적용 선택": "창업감면",
}
YEARS = [
    (date(2023, 3, 2), date(2023, 12, 31), -30_000_000, 50_000_000, 6),
    (date(2024, 1, 1), date(2024, 12, 31), 120_000_000, 900_000_000, 12),
    (date(2025, 1, 1), date(2025, 12, 31), 400_000_000, 2_500_000_000, 15),
]
EXPECT = {"total": 32_720_000, "o_final": 6_720_000, "t_7": 28_000_000, "t_final": 26_000_000, "rate": 0.5, "add_rate": 0.12, "nth": 2}


def write(path: Path, company: dict | None = None, years: list | None = None, blank: bool = False) -> Path:
    """회사 · 연도별 두 시트. blank 면 값 없이 머리글과 설명만."""
    co = {} if blank else dict(COMPANY, **(company or {}))
    yrs = [] if blank else (YEARS if years is None else years)
    wb = Workbook()
    ws = wb.active
    ws.title = S_CO
    X.header(ws, 1, ["항목", "값", "설명", "받는 곳"])
    for i, (key, kind, default, desc) in enumerate(COMPANY_ROWS, start=2):
        X.cell(ws, i, 1, key)
        v = co.get(key, None if blank else (default if default not in (None, "") else None))
        c = X.cell(ws, i, 2, v, kind="input", money=kind == "won")
        if kind == "date":
            c.number_format = "yyyy-mm-dd"
        X.cell(ws, i, 3, desc + (" (필수)" if default is None else ""), wrap=True)
        X.cell(ws, i, 4, SOURCE.get(key, ""), wrap=True)
    X.widths(ws, [42, 24, 90, 48])
    ws2 = wb.create_sheet(S_YEARS)
    X.header(ws2, 1, list(YEAR_COLS))
    for i, y in enumerate(yrs, start=2):
        for j, val in enumerate(y, start=1):
            c = X.cell(ws2, i, j, val, kind="input", money=j in (3, 4))
            if j <= 2:
                c.number_format = "yyyy-mm-dd"
    ws2.cell(row=1, column=7, value="창업한 과세연도부터 해당 과세연도까지 한 줄씩. 감면사업 소득금액은 각 사업연도 소득금액 중"
             " 감면사업분(결손이면 음수)").font = Font(name=X.FONT, color="666666", size=9)
    X.widths(ws2, [18, 18, 20, 20, 16])
    write_sheet(wb, definitions(), DEF_INTRO)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return Path(path)
