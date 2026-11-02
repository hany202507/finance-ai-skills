# -*- coding: utf-8 -*-
"""퇴사 의무표의 계속근로 1년 판정. 일수가 아니라 날짜로 센다(근퇴법 §4① 단서).

입사일 다음 해 같은 날의 전날까지 다니면 1년이다. 2월 29일 입사자는 다음 해 3월 1일을 같은 날로 본다.
입퇴사처리 스킬의 퇴직금 계산과 같은 기준이다.
"""
import pytest

import db
from event_obligations import scan_events


def _퇴사(입사일, 퇴사일):
    conn = db.connect(":memory:")
    conn.execute("INSERT INTO payee(id,name,resident_type,payee_type,join_date,leave_date) "
                 "VALUES(1,'대상','거주자','근로자',?,?)", (입사일, 퇴사일))
    conn.commit()
    return [o.의무 for o in scan_events(conn, 퇴사일, 창=0) if o.이벤트 == "퇴사"]


@pytest.mark.parametrize("입사일,퇴사일,있음", [
    ("2025-01-01", "2025-12-31", True),    # 평년 꼭 1년(364일 차이)
    ("2025-01-01", "2025-12-30", False),
    ("2024-01-01", "2024-12-30", False),   # 윤년이라 365일 차이지만 1년이 안 됐다
    ("2024-01-01", "2024-12-31", True),
    ("2025-03-02", "2026-02-28", False),
    ("2025-03-02", "2026-03-01", True),
    ("2024-02-29", "2025-02-27", False),
    ("2024-02-29", "2025-02-28", True),
])
def test_퇴직금_의무는_계속근로_1년을_날짜로_센다(입사일, 퇴사일, 있음):
    의무 = _퇴사(입사일, 퇴사일)
    assert any(x.startswith("퇴직금 지급") and "의무 없음" not in x for x in 의무) is 있음
    assert any("지급의무 없음" in x for x in 의무) is (not 있음)
    assert any(x.startswith("퇴직소득세") for x in 의무) is 있음
