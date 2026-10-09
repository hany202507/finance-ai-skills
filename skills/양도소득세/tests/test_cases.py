# -*- coding: utf-8 -*-
import json

from cases import CASES, EXPECT

PERSONAL = {"성명", "주민등록번호", "전화번호", "환급계좌", "계좌번호"}


def walk(o):
    if isinstance(o, dict):
        for k, v in o.items():
            yield k
            yield from walk(v)
    elif isinstance(o, list):
        for v in o:
            yield from walk(v)


def test_cases_are_json_and_have_no_personal_keys():
    for name, f in CASES.items():
        json.dumps(f, ensure_ascii=False)
        assert not PERSONAL & set(walk(f)), name


def test_every_sold_house_is_linked():
    for name, f in CASES.items():
        linked = {h["자산id"] for h in f["세대"]["주택목록"] if h["자산id"]}
        for a in f["자산"]:
            if a["종류"] == "주택":
                assert a["id"] in linked, name


def test_expect_names_exist():
    assert set(EXPECT) <= set(CASES)
