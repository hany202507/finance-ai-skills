# -*- coding: utf-8 -*-
from decimal import Decimal

from yangdo import keys
from yangdo import ruleset as R

RS = R.load()


def test_every_key_present_from_start():
    for k in keys.VALUE_KEYS + keys.CITE_KEYS:
        start = keys.LATE_KEYS.get(k, "2025-01-01")
        for on in (start, "2026-10-09", "2027-12-31"):
            RS.entry(k, on)
            assert RS.cite(k, on), k


def test_spot_values():
    assert RS.value("기본공제", "2026-10-09") == 2500000
    assert RS.value("고가주택기준", "2025-01-01") == 1200000000
    assert RS.value("기본세율", "2026-10-09")[-1] == [1000000000, 384060000, Decimal("0.45")]
    assert RS.value("지방.기본세율", "2026-10-09")[-1] == [1000000000, 38406000, Decimal("0.045")]
    assert RS.value("장특공.표2.거주", "2026-10-09")[0] == [2, Decimal("0.08")]
    assert RS.value("단기.주택.2년미만", "2026-10-09") == Decimal("0.60")


def test_history_values():
    assert RS.value("중과.한시배제.가목.양도기한", "2025-01-15") == "2025-05-09"
    assert RS.value("중과.한시배제.가목.양도기한", "2026-01-01") == "2026-05-09"
    assert RS.value("일시적2주택.처분기한.일반", "2026-09-30") == 3
    assert RS.value("일시적2주택.처분기한.일반", "2026-11-01") == 3
    assert RS.value("일시적2주택.처분기한.조정", "2026-11-01") == 2
    assert RS.value("일시적2주택.조정기한.신규취득시작", "2025-06-01") == "2026-08-04"


def test_pending_amendment_note():
    assert any(n.startswith("계류") for n in RS.notes("중과.2주택", "2026-06-01"))
    assert not any(n.startswith("계류") for n in RS.notes("중과.2주택", "2026-05-09"))


def test_cites_have_urls_and_versions():
    for k in keys.VALUE_KEYS + keys.CITE_KEYS:
        on = keys.LATE_KEYS.get(k, "2026-10-09")
        for c in RS.cite(k, on):
            assert c["URL"].startswith("https://www.law.go.kr/법령/") and c["시행일"], k
