"""판단 → 조서 노란 칸 잇기(bestar/link.py). 합성 장부만 쓴다."""
from __future__ import annotations

import json

import openpyxl
import pytest

from ctax.wp import cli as wp_cli

from bestar import decide, link, memos, paths, steps
from tests.test_flow import case, good_steps, issues, memo_file, run_steps, write_step  # noqa: F401


@pytest.fixture
def wp_case(case):  # noqa: F811
    assert wp_cli.main([str(case)]) in (0, 1)
    assert link.xlsx_path(paths.case(case)).exists()
    return case


def set_cell(root, paper, key, value):
    """회계사가 엑셀에서 노란 칸을 고친 것처럼 쓰고 조서 계산을 다시 돌린다."""
    c = paths.case(root)
    cell = link.cells(c)[(paper, key)]
    wb = openpyxl.load_workbook(link.xlsx_path(c))
    wb[cell["sheet"]][cell["cell"]].value = value
    wb.save(link.xlsx_path(c))
    wp_cli.main([str(root)])


def value(root, paper, key):
    return link.cells(paths.case(root))[(paper, key)]["value"]


def a_pick(root):
    """시험에 쓸 pick 칸 하나(엔진 기본값과 반대 값을 넣는다)."""
    for (paper, key), cell in link.cells(paths.case(root)).items():
        if cell["kind"] == "pick":
            return paper, key, cell["default"], "X" if cell["default"] == "O" else "O"
    pytest.skip("합성 장부에 pick 칸이 없습니다")


# ---------------------------------------------------------------- 전제

@pytest.mark.parametrize("premise,small,want", [
    ("중소기업(소기업)", None, {"중소기업 여부": "여", "소기업 여부": "여"}),
    ("중소기업(중기업)", None, {"중소기업 여부": "여", "소기업 여부": "부"}),
    ("중소기업", "미충족", {"중소기업 여부": "여", "소기업 여부": "부"}),
    ("중소기업", "미확인", {"중소기업 여부": "여"}),
    ("중견기업", "충족", {"중소기업 여부": "부"}),
    ("미확인", None, {}),
])
def test_premise_sets(premise, small, want):
    f2 = {"premise": premise, "status": "확인 필요", "tests": [{"name": "소기업", "result": small}] if small else []}
    got = {s["key"]: s["value"] for s in link.premise_sets(f2)}
    assert got == want


def sme_tests(small: str):
    return ([{"name": n, "result": "충족"} for n in ("업종", "규모", "자산총액", "유예기간")]
            + [{"name": "독립성", "result": "미확인"}, {"name": "소기업", "result": "충족" if small == "여" else "미충족"}])


def test_excel_edit_is_not_overwritten_by_premise(wp_case):
    c = paths.case(wp_case)
    default = link.cells(c)[("credits", "소기업 여부")]["default"]
    manual = "부" if default == "여" else "여"
    set_cell(wp_case, "credits", "소기업 여부", manual)       # 회계사가 엑셀에서 먼저 고침
    good_steps(wp_case, f2_tests=sme_tests(default))          # 2-(2) 는 엔진 기본값 쪽으로 판단
    run_steps(wp_case)
    assert value(wp_case, "credits", "소기업 여부") == manual
    assert any(w["key"] == "소기업 여부" for w in link.plan(c)["kept"])


def test_f2_premise_written_when_untouched(wp_case):
    c = paths.case(wp_case)
    default = link.cells(c)[("credits", "소기업 여부")]["default"]
    want = "부" if default == "여" else "여"
    good_steps(wp_case, f2_tests=sme_tests(want))
    run_steps(wp_case)
    assert value(wp_case, "credits", "소기업 여부") == want
    linked = json.loads(link.state_path(c).read_text(encoding="utf-8"))["linked"]
    assert linked["credits|소기업 여부"]["prev"] == default


def test_f2_sets_checked(wp_case):
    good_steps(wp_case)
    c = paths.case(wp_case)
    for sid in ("P1", "P2", "P3", "P4", "F1"):
        assert steps.cmd_done(c, sid, False) == 0
    f2 = json.loads((wp_case / "_색인/AR_단계/F2.json").read_text(encoding="utf-8"))
    f2["carry"]["sets"] = [{"paper": "depreciation", "key": "내용연수/없는자산", "value": 5, "why": "건설용장비"}]
    (wp_case / "_색인/AR_단계/F2.json").write_text(json.dumps(f2, ensure_ascii=False), encoding="utf-8")
    probs = steps.check_step(c, "F2")
    assert any("없습니다" in p for p in probs)


# ---------------------------------------------------------------- 질문지 답

def memo_with_sets(root, tmp_path, sets_yes, sets_no):
    p = memo_file(root, tmp_path)
    data = json.loads(p.read_text(encoding="utf-8"))
    data["items"][0]["choices"] = {"title": "이 거래를 조정할까요", "options": [
        {"value": "yes", "label": "조정해요", "effect": "조서 칸을 바꿔요", "sets": sets_yes},
        {"value": "no", "label": "두어요", "effect": "조서 그대로", "sets": sets_no}]}
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return p, data["items"][0]["issue"]


def test_choice_sets_checked(wp_case, tmp_path):
    good_steps(wp_case)
    run_steps(wp_case)
    paper, key, default, other = a_pick(wp_case)
    bad, _ = memo_with_sets(wp_case, tmp_path, [{"paper": paper, "key": key + "없음", "value": other}], None)
    assert memos.main([str(wp_case), str(bad)]) == 1
    bad, _ = memo_with_sets(wp_case, tmp_path, [{"paper": paper, "key": key, "value": "예"}], None)
    assert memos.main([str(wp_case), str(bad)]) == 1                    # pick 칸은 O · X


def test_answer_writes_and_undo_restores(wp_case, tmp_path):
    good_steps(wp_case)
    run_steps(wp_case)
    c = paths.case(wp_case)
    paper, key, default, other = a_pick(wp_case)
    p, no = memo_with_sets(wp_case, tmp_path, [{"paper": paper, "key": key, "value": other}],
                           [{"paper": paper, "key": key, "value": default}])
    assert memos.main([str(wp_case), str(p)]) == 0
    k = f"issue|{next(i for i in issues(wp_case) if i['no'] == no)['key']}|{next(i for i in issues(wp_case) if i['no'] == no)['rule']}"
    decide.decide(c, k, value="yes")
    r = link.sync(c)
    assert not r["problem"] and len(r["writes"]) == 1
    assert value(wp_case, paper, key) == other
    inp = json.loads((wp_case / "_색인/조서입력.json").read_text(encoding="utf-8"))
    assert any(x["key"] == key and x["value"] == other for x in inp["cells"])    # 조서 계산이 회계사 값으로 읽었다
    decide.decide(c, k, value="no")
    link.sync(c)
    assert value(wp_case, paper, key) == default
    decide.decide(c, k, value="yes")
    link.sync(c)
    decide.undo(c, k)
    link.sync(c)
    assert value(wp_case, paper, key) == default
    assert not json.loads(link.state_path(c).read_text(encoding="utf-8"))["linked"].get(f"{paper}|{key}")


def test_excel_edit_after_answer_is_kept(wp_case, tmp_path):
    good_steps(wp_case)
    run_steps(wp_case)
    c = paths.case(wp_case)
    paper, key, default, other = a_pick(wp_case)
    p, no = memo_with_sets(wp_case, tmp_path, [{"paper": paper, "key": key, "value": other}], None)
    assert memos.main([str(wp_case), str(p)]) == 0
    i = next(i for i in issues(wp_case) if i["no"] == no)
    k = f"issue|{i['key']}|{i['rule']}"
    d = decide.load(c)
    d["decisions"][k] = {"value": "yes", "at": "2000-01-01T00:00:00", "by": "회계사"}    # 오래전에 고른 답
    decide.save(c, d)
    link.sync(c)
    assert value(wp_case, paper, key) == other
    set_cell(wp_case, paper, key, default)                 # 그 뒤 엑셀에서 되돌림
    r = link.sync(c)
    assert r["kept"] and value(wp_case, paper, key) == default
    d = decide.load(c)                                     # 엑셀에서 고친 뒤 다시 고르면 넣는다
    d["decisions"][k] = {"value": "yes", "at": "2999-01-01T00:00:00", "by": "회계사"}
    decide.save(c, d)
    link.sync(c)
    assert value(wp_case, paper, key) == other


def test_review_shows_sets(wp_case, tmp_path):
    good_steps(wp_case)
    run_steps(wp_case)
    paper, key, default, other = a_pick(wp_case)
    p, no = memo_with_sets(wp_case, tmp_path, [{"paper": paper, "key": key, "value": other}], None)
    assert memos.main([str(wp_case), str(p)]) == 0
    from bestar import review
    q = next(q for q in review.build(paths.case(wp_case))["questions"] if q["uid"] == f"issue:{no}")
    assert q["options"][0]["sets_text"] and q["options"][0]["sets_text"][0].endswith(f"→ {other}")
    assert q["options"][1]["sets_text"] == []
