"""10-20 블라인드 실행 네 곳에서 나온 보완: AI 추가 이슈 메모 줄, 같은 사안 묶기, 빈 sets, 보고서(별칭 · 합계 id · 3호 흐름)."""
from __future__ import annotations

import json

from bestar import finish, link, memos, paths, rank, report
from bestar import credits as credits_mod
from tests.test_flow import case, credit_file, good_steps, memo_file, run_steps  # noqa: F401


def done(root, tmp_path):
    good_steps(root)
    run_steps(root)
    return paths.case(root)


def test_added_line_in_memo(case, tmp_path):  # noqa: F811
    c = done(case, tmp_path)
    p = memo_file(case, tmp_path)
    data = json.loads(p.read_text(encoding="utf-8"))
    data["items"].append({"added": "a2", "law": [{"ref": "법인세법 제27조의2(업무용승용차)", "grade": "★★☆"}], "tax_effect": True,
                          "choices": {"title": "렌트 차량이 업무용승용차인가요", "options": [
                              {"value": "yes", "label": "승용차예요", "effect": "29호 한도 계산"},
                              {"value": "no", "label": "화물차예요", "effect": "조정 없음", "sets": []}]}})
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    assert memos.main([str(case), str(p)]) == 0
    a = next(x for x in finish.added_issues(c, json.loads((case / "_색인/AR_단계/F1.json").read_text(encoding="utf-8"))["carry"])
             if x["id"] == "a2")
    assert a["law"] and a["tax_effect"] and a["choices"]["title"].startswith("렌트")
    assert "added|a2" in link.question_sets(c)


def test_added_line_rejects_engine_account(case, tmp_path):  # noqa: F811
    done(case, tmp_path)
    p = memo_file(case, tmp_path)
    data = json.loads(p.read_text(encoding="utf-8"))
    data["items"].append({"added": "a1", "tax_effect": True})          # a1 은 엔진 이슈가 있는 계정
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    assert memos.main([str(case), str(p)]) == 1


def test_empty_sets_is_none():
    assert link.problems([], {}, "x") == []
    assert link.problems("a", {}, "x")


def test_sme_group_once_in_top():
    def issue(no, rule, title):
        return {"no": no, "kind": "신고 점검" if rule != "sme_reduction" else "공제감면", "certainty": "가능", "guide": ["2-2"],
                "rule": rule, "title": title, "memo": {"judgment": "판단 필요", "why": "x"}}
    ar = {"issues": [issue(1, "sme_small", "소기업 여부"), issue(2, "sme_reduction", "중소기업 감면"), issue(3, "loan", "인정이자"),
                     issue(4, "prior_loss_row", "결손금 이력")]}
    ex = {1: {"risk": "상", "tax_effect": True}, 2: {"risk": "상", "tax_effect": True}, 3: {"risk": "상"}, 4: {"risk": "중"}}
    st = {s: {"carry": {}} for s in ("P1", "P2", "P3", "P4", "F1")}
    st["F2"] = {"carry": {"status": "확정", "compare_p1": "같음"}}
    out = rank.build(ar, ex, st, [], {}, ["2-2"], taxable=True)
    top = [u["title"] for u in out["top"]]
    assert not ("소기업 여부" in top and "중소기업 감면" in top)
    assert "결손금 이력" in top                                       # 당기 소득이 있으면 위험 상 + 세액 영향


def test_report_alias_facts_and_flow(case, tmp_path):  # noqa: F811
    c = done(case, tmp_path)
    assert memos.main([str(case), str(memo_file(case, tmp_path))]) == 0
    assert credits_mod.main([str(case), str(credit_file(tmp_path))]) == 0
    assert finish.main([str(case), "--alias", "가명회사"]) == 0
    md = (case / paths.REPORT).read_text(encoding="utf-8")
    assert md.startswith("# 가명회사 ")
    assert "과세표준" in md and "차감납부할세액" in md
    assert "₩" not in md
    d = {"facts": [{"id": "s2", "type": "합계", "what": "월 급여", "net": 1234567}]}
    assert "월 급여 1,234,567원" in report._plain("합계 s2 를 봅니다. ₩5,000", {f["id"]: f for f in d["facts"]})
    assert "5,000원" in report._plain("₩5,000", {})
    assert finish.main([str(case)]) == 0                                # 별칭은 남는다
    assert (case / paths.REPORT).read_text(encoding="utf-8").startswith("# 가명회사 ")


def test_stake_tax_delta_and_order():
    from bestar import stake
    assert stake.tax_delta({"tax_base": 0}, {"amount": 10_000_000, "side": "가산"}) > 0
    assert stake.tax_delta({"tax_base": -50_000_000}, {"amount": 10_000_000, "side": "가산"}) == 0
    assert stake.problems({"amount": 7, "side": "가산"}, {8}, "x")

    def issue(no, title):
        return {"no": no, "kind": "조정 후보", "certainty": "가능", "guide": ["2-3-1-1"], "rule": f"r{no}", "title": title,
                "accounts": [str(no)], "memo": {"judgment": "판단 필요", "why": "x"}}
    ar = {"issues": [issue(1, "작은 쟁점"), issue(2, "큰 쟁점"), issue(3, "셋째"), issue(4, "넷째")]}
    ex = {1: {"risk": "상", "stake": {"amount": 1_000_000, "side": "가산"}}, 2: {"risk": "상", "stake": {"amount": 150_000_000, "side": "가산"}},
          3: {"risk": "상"}, 4: {"risk": "상"}}
    st = {s: {"carry": {}} for s in ("P1", "P2", "P3", "P4", "F1")}
    st["F2"] = {"carry": {"status": "확정", "compare_p1": "같음"}}
    out = rank.build(ar, ex, st, [], {}, ["2-3-1-1"], taxable=True, tax_summary={"tax_base": 100_000_000})
    assert out["top"][0]["title"] == "큰 쟁점" and out["top"][0]["tax_delta"] > 0


def test_memo_top_level_and_questions_override(case, tmp_path):  # noqa: F811
    done(case, tmp_path)
    p = memo_file(case, tmp_path)
    data = json.loads(p.read_text(encoding="utf-8"))
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({**data, "added": [{"added": "a2"}]}, ensure_ascii=False), encoding="utf-8")
    assert memos.main([str(case), str(bad)]) == 1                       # 맨 위 added 는 거절
    assert rank.questions_of({"memo": {"judgment": "판단 필요", "questions": []}, "questions": ["엔진 질문을 보내 주십시오"]}) == []
    assert rank.questions_of({"memo": {"judgment": "조정 없음", "questions": ["x 주십시오"]}}) == []
    assert rank.questions_of({"memo": {"judgment": "판단 필요"}, "questions": ["엔진 질문을 보내 주십시오"]}) == ["엔진 질문을 보내 주십시오"]


def test_report_number_format():
    assert report._plain("전표 금액 합계 ₩68,323,839, 공제액이 아님", {}) == "전표 금액 합계 68,323,839원, 공제액이 아님"
    f = {"s1": {"id": "s1", "type": "합계", "what": "공사매출 중 장비임대", "net": -46200000}}
    assert report._plain("합계 s1 이다", f) == "공사매출 중 장비임대 46,200,000원 이다"
