"""최종 신고서 대조(bestar/compare.py). 신고서 PDF 대신 읽은 꼴(dict)을 준다."""
from __future__ import annotations

from pathlib import Path

from bestar import compare, finish, memos, paths
from bestar import credits as credits_mod
from tests.test_flow import case, credit_file, good_steps, memo_file, run_steps  # noqa: F401


def ready(root, tmp_path):
    good_steps(root)
    run_steps(root)
    assert memos.main([str(root), str(memo_file(root, tmp_path))]) == 0
    assert credits_mod.main([str(root), str(credit_file(tmp_path))]) == 0
    assert finish.main([str(root)]) == 0
    return paths.case(root)


def answer(adjustments, cells3=None, credits=None):
    return {"company": {"name": "가상회사"}, "fy": "2025", "adjustments": adjustments, "reserves": [], "losses": [],
            "credits": credits or [], "cells": {"3": cells3 or {}}, "problems": []}


def adj(side, subject, amount, disp="기타사외유출", note=""):
    return {"side": side, "subject": subject, "amount": amount, "disposition": disp, "note": note}


def test_points_caught_missed_and_ar_only(case, tmp_path):  # noqa: F811
    c = ready(case, tmp_path)
    ans = answer([adj("가산", "접대비(기업업무추진비)", 5_000_000, note="기업업무추진비 한도초과 손금불산입"),
                  adj("가산", "토지재평가차액", 1_234_000, "유보")],
                 cells3={"07": 3_000_000},
                 credits=[{"name": "중소기업에대한특별세액감면", "amount": 700_000}])
    d = compare.build(c, Path("가상.pdf"), ans)
    res = {x["title"]: x for x in d["items"]}
    assert res["가산 접대비(기업업무추진비)"]["result"] == "잡음"
    assert res["가산 접대비(기업업무추진비)"]["check"]["state"] == "같음"      # 조서 조정과 같은 방향 · 금액 · 처분
    assert res["가산 토지재평가차액"]["check"]["state"] == "조서 금액 없음"
    assert res["가산 토지재평가차액"]["result"] == "못 잡음"
    assert res["중소기업에대한특별세액감면 적용"]["result"] == "잡음"         # 공제 제안 이름으로 이음
    s = d["summary"]
    assert s["points"] == 4 and s["못 잡음"] >= 1
    assert any("대여금" in x["title"] for x in d["ar_only"])               # 신고서에 없는데 AR 이 짚은 것
    assert not any("법인세등" in x["title"] for x in d["ar_only"])         # 상시 항목은 빼고
    md = compare.markdown(d)
    assert "## 1. 신고서 항목을 AR 이 잡았는지" in md and "## 2. AR 만 짚은 것" in md and "토지재평가차액" in md
    assert "—" not in md and "?" not in md


def test_paper_direction_and_amount(case, tmp_path):  # noqa: F811
    c = ready(case, tmp_path)
    ans = answer([adj("차감", "기업업무추진비", 5_000_000, "기타"), adj("가산", "접대비", 4_000_000)])
    d = compare.build(c, Path("가상.pdf"), ans)
    st = {x["title"]: x["check"] for x in d["items"]}
    assert st["차감 기업업무추진비"]["state"] == "방향 반대"
    assert st["가산 접대비"]["state"] == "금액 다름" and st["가산 접대비"]["diff"] == 1_000_000
    md = compare.markdown(d)
    assert "방향 반대" in md and "+1,000,000" in md


def test_glued_subject_and_credit_names():
    assert compare.related("보험료기간미경과액", "선급비용이 있습니다. 기간 미경과액(선급비용명세서)을 확인합니다 선급비용")
    assert not compare.related("토지재평가차액", "기업업무추진비 한도 계산이 필요합니다 접대비")
    assert compare.same_credit("일반연구·인력개발비세액공제(최저한세적용제외)", "연구 · 인력개발비에 대한 세액공제")
    assert not compare.same_credit("통합고용세액공제", "통합투자세액공제")


def test_command_needs_pdf(case, tmp_path):  # noqa: F811
    ready(case, tmp_path)
    assert compare.main([str(case)]) == 2                                  # 최종 신고본 폴더가 없다
