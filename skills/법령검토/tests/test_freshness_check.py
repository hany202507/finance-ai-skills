import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import freshness_check as fc  # noqa: E402

# 2026-10-19 korean-law amendment_track(소득세법 시행령) 결과 일부
DB = [
    {"MST": "283631", "공포일": "2026-02-27", "시행일": "2027-01-01"},
    {"MST": "280865", "공포일": "2025-12-30", "시행일": "2027-01-01"},
    {"MST": "290841", "공포일": "2026-09-30", "시행일": "2026-10-01"},
    {"MST": "286211", "공포일": "2026-05-22", "시행일": "2026-07-01"},
    {"MST": "283631", "공포일": "2026-02-27", "시행일": "2026-07-01"},
]


def base(판="283631@20270101", db=DB, **over):
    b = {"기준일": "2027-02-15", "오늘": "2026-10-19",
         "법령": [{"법령": "소득세법 시행령", "조항": ["제155조 제1항"], "판": 판, "DB판": list(db)}]}
    b.update(over)
    return b


def survey(조사처, 항목=(), 상태="완료", 기간=("2026-02-27", "2026-10-19"), 검색어=("소득세법",)):
    return {"조사처": 조사처, "상태": 상태, "검색": {"출처": "시험", "기간": list(기간), "검색어": list(검색어)}, "항목": list(항목)}


def item(구분, 공포일="", 시행일="", 번호="", 대상=("제155조",), 확인="본문"):
    return {"법령": "소득세법 시행령", "구분": 구분, "번호": 번호, "공포일": 공포일, "시행일": 시행일,
            "대상조문": list(대상), "요지": "", "URL": "", "확인": 확인}


def verdicts(rep):
    return [(p["판정"], p["등급"]) for p in rep["법령"][0]["판정"]]


def test_date10_and_jo():
    assert fc.date10("20261001") == fc.date10("2026.10.01") == "2026-10-01"
    assert fc.date10("시행일") is None
    assert fc.jo("제159조의4 제1항") == "159의4"
    assert fc.jo("제155조 제1항 제1호") == "155"
    assert fc.jo("167의10") == "167의10"


def test_db_only_no_change():
    rep = fc.check(base(), [])
    assert verdicts(rep) == []
    assert rep["법령"][0]["결과"] == "변경 없음"


def test_db_only_wrong_version_for_base_date():
    # 오늘 판(2026-10-01)을 썼는데 기준일(2027-02-15)에는 2027-01-01 판이 시행 중이다
    rep = fc.check(base(판="290841@20261001"), [])
    (p,) = rep["법령"][0]["판정"]
    assert (p["판정"], p["등급"]) == ("판 다시 고르기", "조치")
    assert "283631@2027-01-01" in p["까닭"]


def test_same_effective_date_takes_latest_promulgation():
    # 2027-01-01 시행 판이 둘이면 늦게 공포된 283631 이 그날의 판이다
    rep = fc.check(base(판="280865@20270101"), [])
    assert ("판 다시 고르기", "조치") in verdicts(rep)


def test_future_versions_are_grouped_by_date():
    db = DB + [{"MST": "269541", "공포일": "2025-02-28", "시행일": "2028-01-01"},
               {"MST": "300001", "공포일": "2026-12-30", "시행일": "2028-01-01"}]
    rep = fc.check(base(db=db), [])
    (p,) = rep["법령"][0]["판정"]
    assert (p["판정"], p["등급"], p["시행일"]) == ("기준일 뒤 시행", "경고", "2028-01-01")
    assert "269541" in p["까닭"] and "300001" in p["까닭"]


def test_db_list_too_short():
    rep = fc.check(base(db=[{"MST": "283631", "공포일": "2026-02-27", "시행일": "2027-01-01"}], 기준일="2026-03-01"), [])
    assert ("확인 불가", "조치") in verdicts(rep)


def test_used_version_missing_from_db():
    assert ("기준 오류", "조치") in verdicts(fc.check(base(판="999@20270101"), []))


def test_pending_bill_is_warning_and_flags_base_date():
    rep = fc.check(base(), [survey("개정안", [item("계류", 시행일="2027-01-01", 번호="의안 2212345")])])
    (p,) = rep["법령"][0]["판정"]
    assert (p["판정"], p["등급"]) == ("개정안", "경고")
    assert "기준일 2027-02-15 에 적용될 수 있다" in p["까닭"]


def test_bill_after_base_date_is_not_applied():
    rep = fc.check(base(), [survey("개정안", [item("입법예고", 시행일="2028-01-01", 번호="공고 1")])])
    (p,) = rep["법령"][0]["판정"]
    assert "적용하지 않는다" in p["까닭"]


def test_bill_whose_planned_date_has_passed_says_so():
    rep = fc.check(base(), [survey("개정안", [item("정부안", 시행일="2026-10-01")])])
    (p,) = rep["법령"][0]["판정"]
    assert (p["판정"], p["등급"]) == ("개정안", "경고")
    assert "예정 시행일 2026-10-01 이 지났다" in p["까닭"]


def test_notice_with_promulgation_date_is_judged_as_promulgated():
    rep = fc.check(base(), [survey("개정안", [item("입법예고", "2026-09-30", "2026-10-01", "공고 222")])])
    (p,) = rep["법령"][0]["판정"]
    assert (p["구분"], p["판정"], p["등급"]) == ("공포", "판 목록에 있음", "참고")


def test_published_but_not_in_db_needs_action():
    rep = fc.check(base(), [survey("공포", [item("공포", "2026-10-15", "2026-10-15", "대통령령 제36800호")])])
    assert ("DB 미반영", "조치") in verdicts(rep)


def test_not_in_db_other_article_read_in_full_is_note_only():
    it = item("공포", "2026-10-15", "2026-10-15", "대통령령 제36800호", 대상=("제167조의10",), 확인="본문")
    assert verdicts(fc.check(base(), [survey("공포", [it])])) == [("다른 조문 개정", "참고")]


def test_not_in_db_other_article_from_list_only_still_needs_action():
    it = item("공포", "2026-10-15", "2026-10-15", "대통령령 제36800호", 대상=("제167조의10",), 확인="목록")
    assert ("DB 미반영", "조치") in verdicts(fc.check(base(), [survey("공포", [it])]))


def test_published_and_in_db_is_note_only():
    # 시행일을 비운 공포도 판 목록의 공포일로 맞춘다
    rep = fc.check(base(), [survey("공포", [item("공포", "2026-09-30", "", "대통령령 제36737호")])])
    assert verdicts(rep) == [("판 목록에 있음", "참고")]


def test_effective_date_differs_from_db():
    rep = fc.check(base(), [survey("공포", [item("공포", "2026-09-30", "2026-11-01", "대통령령 제36737호")])])
    assert ("시행일 불일치", "조치") in verdicts(rep)


def test_failed_survey_is_not_no_change():
    s = survey("개정안", 상태="실패")
    s["까닭"] = "의안정보시스템 검색 화면이 열리지 않았다"
    assert ("확인 불가", "조치") in verdicts(fc.check(base(), [s]))


def test_required_survey_missing():
    rep = fc.check(base(필수조사처=["개정안"]), [])
    assert any(p["조사처"] == "개정안" and p["판정"] == "확인 불가" for p in rep["법령"][0]["판정"])


def test_search_sentence_containing_law_name_counts():
    rep = fc.check(base(), [survey("개정안", 검색어=("소득세법 시행령 입법예고 2026",))])
    assert rep["법령"][0]["결과"] == "변경 없음"


def test_search_terms_must_cover_law():
    assert ("확인 불가", "조치") in verdicts(fc.check(base(), [survey("개정안", 검색어=("지방세법",))]))


def test_publication_search_must_start_at_used_version():
    rep = fc.check(base(), [survey("공포", 기간=("2026-03-05", "2026-10-19"))])
    assert any("공포일 2026-02-27 부터가 아니다" in p["까닭"] for p in rep["법령"][0]["판정"])


def test_surveys_disagree_on_effective_date():
    s = [survey("개정안", [item("계류", 시행일="2027-01-01", 번호="의안 2212345")]),
         survey("국회", [item("계류", 시행일="2027-07-01", 번호="의안 2212345")])]
    assert ("불일치", "조치") in verdicts(fc.check(base(), s))


def test_main_exit_codes(tmp_path):
    b = tmp_path / "기준.json"
    out = tmp_path / "최신화점검.json"
    b.write_text(json.dumps(base(), ensure_ascii=False), encoding="utf-8")
    assert fc.main(["--기준", str(b), "--출력", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["요약"]["변경 없음"] == 1
    assert out.with_suffix(".md").exists()

    b.write_text(json.dumps(base(판="290841@20261001"), ensure_ascii=False), encoding="utf-8")
    assert fc.main(["--기준", str(b), "--출력", str(out)]) == 1

    bad = tmp_path / "깨짐.json"
    bad.write_text("{", encoding="utf-8")
    assert fc.main(["--기준", str(bad), "--출력", str(out)]) == 2
