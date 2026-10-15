# -*- coding: utf-8 -*-
"""AI 1차 판단 — 확인 항목 추출과 AI 의견 형식 검사.

AI 의견은 근거 없이 그럴듯하게 채워지기 쉽다. 근거 없는 의견 · 확신도 누락 · 지난 실행의
id 를 형식 단계에서 막는다. 확인 항목은 raw 파일 없이 엔진 속성만 세워 검사한다.
"""
import os, sys, json, types

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from close_engine import Engine
import review_items as R


def _eng(**kw):
    e = Engine.__new__(Engine)
    e.P = types.SimpleNamespace(
        미분류_계정={"출금": (134, "가지급금"), "입금": (257, "가수금")},
        카드가맹점_계정={"META ADS": (833, "광고선전비", "해외"),
                      "식대": (811, "복리후생비", "공제")},
        상품_기초재고=0, 상품_기말재고_잠정=0, 전기_확정판단=["법인세 분기 미계상"])
    e.period = "2026Q2"
    e.unclassified_rows = []
    e.card = []
    e.party_miss = {}
    for k, v in kw.items():
        setattr(e, k, v)
    return e


def test_항목_종류별로_뽑는다(tmp_path):
    e = _eng(unclassified_rows=[["2026-05-07", "주거래", "출금", 880000, "이체 공구", "사유"],
                                ["2026-05-07", "주거래", "출금", 880000, "이체 공구", "사유"]],
             card=[["2026-04-02", "카드", "1234", "META ADS", "광고", None, 300000, 0],
                   ["2026-04-03", "카드", "1234", "식대", "음식", 1, 20000, 0]],
             party_miss={"역삼구청": {817}})
    e.P.상품_기말재고_잠정 = {"2026Q2": 40000000}
    json.dump({"fail": [], "확인": ["거래처마스터 확인"]},
              open(tmp_path / "_검증_업로드_2026Q2.json", "w", encoding="utf-8"), ensure_ascii=False)
    items = R.collect(e, str(tmp_path), "2026Q2")
    ids = [it["id"] for it in items]
    # 같은 날 같은 금액이 두 번이면 id 가 겹치지 않아야 한다
    assert ids[:2] == ["미분류-2026-05-07-출금-880000", "미분류-2026-05-07-출금-880000-2"]
    assert "잠정-기말재고" in ids
    assert "해외카드-META ADS" in ids and not any("식대" in i for i in ids)
    assert "거래처-역삼구청" in ids
    assert sum(1 for it in items if it["구분"] == "업로드 사전검증 확인") == 1
    # 다시 돌려도 id 가 같다(AI 의견을 id 로 붙이므로)
    assert [it["id"] for it in R.collect(e, str(tmp_path), "2026Q2")] == ids


def test_재고없으면_잠정재고_항목이_없다(tmp_path):
    assert R.collect(_eng(), str(tmp_path), "2026Q2") == []


ITEMS = [{"id": "a"}, {"id": "b"}, {"id": "c"}]


def test_형식_통과():
    ops = {"a": {"의견": "소모품비", "근거": ["적요"], "확신도": "낮음"},
           "b": {"판단보류": True, "의견": "입금자 확인 필요"},
           "c": {"의견": "대리납부 아님", "근거": ["부가세법 52조"], "확신도": "높음"}}
    assert R.check_opinions(ITEMS, ops) == []


def test_근거없는_의견과_틀린_확신도와_지난_id_를_잡는다():
    ops = {"a": {"의견": "소모품비", "근거": [], "확신도": "낮음"},
           "b": {"의견": "가수금", "근거": ["x"], "확신도": "아마"},
           "z": {"의견": "옛 항목", "근거": ["x"], "확신도": "높음"}}
    errs = R.check_opinions(ITEMS, ops)
    assert any(e.startswith("a:") and "근거" in e for e in errs)
    assert any(e.startswith("b:") and "확신도" in e for e in errs)
    assert any(e.startswith("c:") and "의견이 없다" in e for e in errs)
    assert any(e.startswith("z:") for e in errs)
