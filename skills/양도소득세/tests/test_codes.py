# -*- coding: utf-8 -*-
from yangdo import codes as CD

CODES = CD.load()


def v(**kw):
    base = {"일세대일주택": True, "비과세": True, "취득일": "2019-03-01", "보유년": 7, "거주년": 5,
            "조정_취득일": {"지정": True}, "공고전계약_취득": False}
    base.update(kw)
    return base


def test_rate_codes():
    assert CODES.rate_code("주택", "기본") == "10"
    assert CODES.rate_code("주택", "1년미만") == "46"
    assert CODES.rate_code("일반", "2년미만") == "15"
    assert CODES.rate_code("미등기", None) == "30"
    assert CODES.rate_code("중과2", "2년미만") == "82"
    assert CODES.rate_code("중과3", "기본") == "49"


def test_every_selected_code_is_listed():
    sel = CODES.data["세율구분_선택"]
    used = {sel["미등기"]} | {c for g in sel.values() if isinstance(g, dict) for c in g.values()}
    assert used <= set(CODES.data["세율구분"])


def test_asset_tax_acq_codes():
    assert CODES.asset_code("토지", False) == "01"
    assert CODES.asset_code("주택", True) == "02"
    assert CODES.asset_code("주택", False) == "03"
    assert CODES.asset_code("건물", False) == "04"
    assert CODES.tax_class(True) == "01" and CODES.tax_class(False) == "ZZ"
    assert CODES.acq_code("환산가액") == "04" and CODES.acq_code(None) is None


def test_period_and_residence_codes():
    assert CODES.period_code(0) == "00" and CODES.period_code(7) == "07" and CODES.period_code(15) == "10"
    assert CODES.residence_code(v()) == "05"
    assert CODES.residence_code(v(취득일="2014-11-01")) == "Z1"
    assert CODES.residence_code(v(조정_취득일={"지정": False})) == "Z2"
    assert CODES.residence_code(v(공고전계약_취득=True)) == "Z2"
    assert CODES.residence_code(v(비과세=False)) == "ZZ"
    assert CODES.holding_code(v()) == "07" and CODES.holding_code(v(일세대일주택=False)) == "ZZ"
