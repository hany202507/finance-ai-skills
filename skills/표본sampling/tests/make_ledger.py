# -*- coding: utf-8 -*-
"""예시 자료 `examples/모의자료/매출원장.xlsx` 를 만든다. 가상 회사 가온정밀(가상)의 2025년 매출 원장 1,200행이다.

    python tests/make_ledger.py

회사 · 거래처 · 품목 · 금액은 모두 지어낸 값이다. 제목 줄과 빈 줄 뒤에 머리줄이 오고, 반품(음수) 13건, 고액 8건, 합계 행 1, 결산일 뒤 거래 1건을
일부러 넣었다. 시험(`tests/test_sample.py`)도 같은 함수로 자료를 만든다.
"""
from __future__ import annotations

import random
from datetime import date, timedelta
from pathlib import Path

from openpyxl import Workbook

ROWS = 1200


def make_ledger(path: Path) -> dict:
    """가상 매출 원장을 path 에 쓰고 심은 건수(반품 neg · 고액 big)를 돌려준다."""
    rng = random.Random(7)
    wb = Workbook()
    ws = wb.active
    ws.title = "매출장"
    ws.append(["(주)가온정밀(가상) 매출 원장"])
    ws.append([])
    ws.append(["전표일자", "전표번호", "거래처명", "품목", "구분", "공급가액", "세액", "합계금액"])
    neg = big = 0
    for i in range(ROWS):
        d = date(2025, 1, 1) + timedelta(days=rng.randrange(365))
        kind = rng.choice(["제품", "제품", "상품", "수출"])
        amt = round(rng.lognormvariate(14.5, 1.1), -3)
        if i % 150 == 5:
            amt, big = 150_000_000 + i * 1000, big + 1
        if i % 97 == 0:
            amt, neg = -amt / 10, neg + 1
        ws.append([d, f"S-{i:05d}", f"거래처{rng.randrange(1, 41):02d}", f"품목{rng.randrange(30)}", kind, amt, round(amt * 0.1),
                   round(amt * 1.1)])
    ws.append([None, None, "합계", None, None, 0, 0, 0])
    ws.append([date(2026, 1, 3), "S-99999", "거래처01", "품목1", "제품", 5_000_000, 500_000, 5_500_000])
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return {"neg": neg, "big": big}


if __name__ == "__main__":
    out = Path(__file__).resolve().parents[1] / "examples" / "모의자료" / "매출원장.xlsx"
    info = make_ledger(out)
    print(f"{out} ({ROWS}행, 반품 {info['neg']}건, 고액 {info['big']}건)")
