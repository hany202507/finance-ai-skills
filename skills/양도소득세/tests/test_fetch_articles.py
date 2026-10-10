# -*- coding: utf-8 -*-
import json

import fetch_articles as fa

LAW_JSON = {"법령": {
    "기본정보": {"시행일자": "20260701", "공포번호": "21221", "공포일자": "20251223"},
    "조문": {"조문단위": [
        {"조문번호": "103", "조문여부": "조문", "조문제목": "양도소득 기본공제",
         "조문내용": "제103조(양도소득 기본공제)", "항": [{"항내용": "① 각각 연 250만원을\r\n공제한다.  "}]},
        {"조문번호": "159", "조문가지번호": "4", "조문여부": "조문", "조문제목": "장기보유특별공제",
         "조문내용": "제159조의4 거주기간이 2년 이상인 것"},
        {"조문번호": "1", "조문여부": "전문", "조문내용": "제1장 총칙"}]},
    "부칙": {"부칙단위": [
        {"부칙공포번호": "21221", "부칙공포일자": "20251223", "부칙내용": [["제1조(시행일) 이 법은 2026년 7월 1일부터 시행한다."]]},
        {"부칙공포번호": "20000", "부칙공포일자": "20240101", "부칙내용": "옛 부칙"}]}}}


def test_article_units_keys_and_text():
    u = fa.article_units(LAW_JSON)
    assert set(u) == {"103", "159의4"}
    assert u["103"]["text"] == "제103조(양도소득 기본공제)\n① 각각 연 250만원을\n공제한다."
    assert len(u["103"]["sha256"]) == 64


def test_own_addenda_only_this_promulgation():
    a = fa.own_addenda(LAW_JSON, "21221")
    assert list(a) == ["21221"] and "2026년 7월 1일" in a["21221"]["text"]


ROWS = [
    {"법령명한글": "소득세법", "법령일련번호": "1", "시행일자": "20240101", "공포일자": "20231231", "공포번호": "1"},
    {"법령명한글": "소득세법", "법령일련번호": "2", "시행일자": "20250101", "공포일자": "20241231", "공포번호": "2"},
    {"법령명한글": "소득세법", "법령일련번호": "3", "시행일자": "20250101", "공포일자": "20250110", "공포번호": "3"},
    {"법령명한글": "소득세법", "법령일련번호": "4", "시행일자": "20260701", "공포일자": "20251223", "공포번호": "4"},
    {"법령명한글": "소득세법", "법령일련번호": "5", "시행일자": "20270101", "공포일자": "20260901", "공포번호": "5"},
    {"법령명한글": "소득세법 시행령", "법령일련번호": "9", "시행일자": "20260701", "공포일자": "20260601", "공포번호": "9"},
]


def test_pick_versions_from_in_force_at_start():
    vs = fa.pick_versions(ROWS, "소득세법", "20250101", "20261009")
    assert [(v["MST"], v["상태"]) for v in vs] == [("3", "연혁"), ("4", "현행"), ("5", "시행예정")]
    assert vs[0]["시행일"] == "2025-01-01"


def test_td_key():
    assert fa.td_key("원천 스냅샷 moleg-eflaw:280405@20260701#38a5") == "280405@20260701"
    assert fa.td_key("없음") is None


def test_fetch_writes_files_and_report(tmp_path):
    rules = tmp_path / "rules"
    rules.mkdir()
    (rules / "감시조문.json").write_text(json.dumps(
        {"기준시작": "2025-01-01", "법령": {"소득세법": ["103", "159의4"]}}, ensure_ascii=False), encoding="utf-8")
    calls = []

    def api(path, params):
        calls.append((path, dict(params)))
        if path == "lawSearch.do":
            rows = [dict(r, 법령ID="001") for r in ROWS if r["법령명한글"] == "소득세법"]
            return {"LawSearch": {"law": rows if params["page"] == 1 else []}}
        j = json.loads(json.dumps(LAW_JSON))
        j["법령"]["기본정보"]["시행일자"] = params["efYd"]
        return j

    def td(law, label):
        return "%s %s (현행, 시행 2026.07.01) 원천 스냅샷 moleg-eflaw:4@20260701#ab" % (law, label)

    rep = fa.fetch(str(rules), api, td, "2026-10-09")
    assert rep["오류"] == []
    pans = json.loads((rules / "조문" / "판목록.json").read_text(encoding="utf-8"))
    assert [p["MST"] for p in pans["법령"]["소득세법"]] == ["3", "4", "5"]
    one = json.loads((rules / "조문" / "소득세법" / "4@2026-07-01.json").read_text(encoding="utf-8"))
    assert set(one["조문"]) == {"103", "159의4"}
    rec = json.loads((rules / "확인기록.json").read_text(encoding="utf-8"))
    assert rec["확인일"] == "2026-10-09"
    assert all(r["일치"] for r in rec["TaxDoctor"]) and len(rec["TaxDoctor"]) == 2
    assert any(p == "lawService.do" and q.get("target") == "eflaw" for p, q in calls)
    assert not any(q.get("target") == "law" for p, q in calls)


def test_fetch_reports_taxdoctor_mismatch(tmp_path):
    rules = tmp_path / "rules"
    rules.mkdir()
    (rules / "감시조문.json").write_text(json.dumps(
        {"기준시작": "2025-01-01", "법령": {"소득세법": ["103"]}}, ensure_ascii=False), encoding="utf-8")

    def api(path, params):
        if path == "lawSearch.do":
            return {"LawSearch": {"law": [dict(r, 법령ID="001") for r in ROWS[:5]] if params["page"] == 1 else []}}
        j = json.loads(json.dumps(LAW_JSON))
        j["법령"]["기본정보"]["시행일자"] = params["efYd"]
        return j

    rep = fa.fetch(str(rules), api, lambda law, label: "moleg-eflaw:999@20260101#x", "2026-10-09")
    rec = json.loads((rules / "확인기록.json").read_text(encoding="utf-8"))
    assert rec["TaxDoctor"][0]["일치"] is False
    assert rep["불일치"] == 1


def test_upcoming_version_is_refetched_but_current_is_not(tmp_path):
    rules = tmp_path / "rules"
    rules.mkdir()
    (rules / "감시조문.json").write_text(json.dumps(
        {"기준시작": "2025-01-01", "법령": {"소득세법": ["103"]}}, ensure_ascii=False), encoding="utf-8")
    calls = []

    def api(path, params):
        calls.append((path, params.get("MST")))
        if path == "lawSearch.do":
            return {"LawSearch": {"law": [dict(r, 법령ID="001") for r in ROWS[:5]] if params["page"] == 1 else []}}
        j = json.loads(json.dumps(LAW_JSON))
        j["법령"]["기본정보"]["시행일자"] = params["efYd"]
        return j

    td = lambda law, label: "moleg-eflaw:4@20260701#x"
    fa.fetch(str(rules), api, td, "2026-10-09")
    up = rules / "조문" / "소득세법" / "5@2027-01-01.json"
    up.write_text(up.read_text(encoding="utf-8").replace("250만원", "300만원"), encoding="utf-8")
    calls.clear()
    rep = fa.fetch(str(rules), api, td, "2026-10-09")
    fetched = [m for p, m in calls if p == "lawService.do"]
    assert fetched == ["5"] and rep["갱신"] == 1 and rep["새판"] == 0
    assert "250만원" in up.read_text(encoding="utf-8")
    assert b"\r\n" not in (rules / "조문" / "판목록.json").read_bytes()


# DRF 가 목내용을 중첩 목록으로 주는 모양을 줄인 시험 자료다. 실제 응답에서 시행령 제167조의3 제1항 제12호가 이렇게 온다.
NESTED_LAW_JSON = {"법령": {
    "기본정보": {"시행일자": "20260701", "공포번호": "21221", "공포일자": "20251223"},
    "조문": {"조문단위": [
        {"조문번호": "167", "조문가지번호": "3", "조문여부": "조문", "조문제목": "1세대3주택 이상에 해당하는 주택의 범위",
         "조문내용": "제167조의3(1세대3주택 이상에 해당하는 주택의 범위)",
         "항": [{"항번호": "①", "항내용": [["① 법 제104조제7항제1호에서 대통령령으로 정하는 주택이란 다음 각 호의 주택을 말한다."]],
                 "호": [
                     {"호번호": "2.", "호내용": "2. 다음 각 목의 어느 하나에 해당하는 주택",
                      "목": [{"목번호": "가.", "목내용": [["가. 가목 본문", "   1) 가목 세목 하나", "   2) 가목 세목 둘"]]},
                             {"목번호": "나.", "목내용": ["나. 나목 본문"]},
                             {"목번호": "다.", "목내용": [["다. 다목 본문"], ["   1) 다목 세목"]]}]},
                     {"호번호": "12.", "호내용": "12. 다음 각 목의 어느 하나에 해당하는 주택",
                      "목": {"목번호": "가.", "목내용": [[["가. 깊이 중첩된 목", "   1) 깊이 중첩된 세목"]]]}}]}]},
        {"조문번호": "1", "조문여부": "전문", "조문내용": "제1장 총칙"}]},
    "부칙": {}}}


def test_collect_flattens_nested_mok_lists_in_order():
    # 검토에서 재현된 입력이다. 예전에는 빈 결과였다.
    assert fa._collect({"목": [{"목내용": [["가. ...", "1) ..."]]}]}, []) == ["가. ...", "1) ..."]


def test_collect_handles_every_text_key_shape():
    node = {"조문내용": "제1조", "항": [
        {"항내용": [["① 첫 항", "   본문 이어짐"]], "호": [
            {"호내용": ["1. 첫 호"], "목": [{"목내용": [["가. 목", "   1) 세목"]]}]}]}]}
    assert fa._collect(node, []) == ["제1조", "① 첫 항", "본문 이어짐", "1. 첫 호", "가. 목", "1) 세목"]


def test_collect_skips_empty_strings_and_non_text():
    assert fa._collect({"호": [{"호내용": [["", "  ", None, 3, "1. 있음"]]}]}, []) == ["1. 있음"]


def test_article_units_keeps_all_mok_and_sub_items_in_document_order():
    u = fa.article_units(NESTED_LAW_JSON)
    assert set(u) == {"167의3"}
    lines = u["167의3"]["text"].split("\n")
    assert lines == [
        "제167조의3(1세대3주택 이상에 해당하는 주택의 범위)",
        "① 법 제104조제7항제1호에서 대통령령으로 정하는 주택이란 다음 각 호의 주택을 말한다.",
        "2. 다음 각 목의 어느 하나에 해당하는 주택",
        "가. 가목 본문", "1) 가목 세목 하나", "2) 가목 세목 둘",
        "나. 나목 본문",
        "다. 다목 본문", "1) 다목 세목",
        "12. 다음 각 목의 어느 하나에 해당하는 주택",
        "가. 깊이 중첩된 목", "1) 깊이 중첩된 세목"]


def test_fetch_keeps_nested_mok_in_saved_file(tmp_path):
    rules = tmp_path / "rules"
    rules.mkdir()
    (rules / "감시조문.json").write_text(json.dumps(
        {"기준시작": "2025-01-01", "법령": {"소득세법 시행령": ["167의3"]}}, ensure_ascii=False), encoding="utf-8")

    def api(path, params):
        if path == "lawSearch.do":
            row = {"법령명한글": "소득세법 시행령", "법령일련번호": "7", "시행일자": "20260701",
                   "공포일자": "20251223", "공포번호": "21221", "법령ID": "002"}
            return {"LawSearch": {"law": [row] if params["page"] == 1 else []}}
        j = json.loads(json.dumps(NESTED_LAW_JSON))
        j["법령"]["기본정보"]["시행일자"] = params["efYd"]
        return j

    rep = fa.fetch(str(rules), api, lambda law, label: "moleg-eflaw:7@20260701#x", "2026-10-09")
    assert rep["오류"] == [] and rep["색인쓰기"] is True
    one = json.loads((rules / "조문" / "소득세법 시행령" / "7@2026-07-01.json").read_text(encoding="utf-8"))
    text = one["조문"]["167의3"]["text"]
    assert "가. 가목 본문" in text and "나. 나목 본문" in text and "2) 가목 세목 둘" in text


# 수집 실패 때 색인을 덮어쓰지 않는다 (최종 검토 T2)

LAW_ROWS = {
    "소득세법": [dict(r, 법령ID="001") for r in ROWS if r["법령명한글"] == "소득세법"],
    "지방세법": [{"법령명한글": "지방세법", "법령일련번호": "31", "시행일자": "20260701", "공포일자": "20260101",
                  "공포번호": "31", "법령ID": "003"}],
}


def _two_law_rules(tmp_path):
    rules = tmp_path / "rules"
    (rules / "조문").mkdir(parents=True)
    (rules / "감시조문.json").write_text(json.dumps(
        {"기준시작": "2025-01-01", "법령": {"소득세법": ["103"], "지방세법": ["103"]}}, ensure_ascii=False),
        encoding="utf-8")
    (rules / "조문" / "판목록.json").write_bytes("옛 판목록".encode("utf-8"))
    (rules / "확인기록.json").write_bytes("옛 확인기록".encode("utf-8"))
    return rules


def _api_failing_on(fail_law=None, fail_path=None):
    def api(path, params):
        if path == "lawSearch.do":
            if params["query"] == fail_law and fail_path == "lawSearch.do":
                raise RuntimeError("검색 실패")
            return {"LawSearch": {"law": LAW_ROWS[params["query"]] if params["page"] == 1 else []}}
        if fail_path == "lawService.do" and params["MST"] == "31":
            raise RuntimeError("본문 실패")
        j = json.loads(json.dumps(LAW_JSON))
        j["법령"]["기본정보"]["시행일자"] = params["efYd"]
        return j
    return api


def _stray(rules):
    return [str(p) for p in rules.rglob("*") if p.is_file() and p.name.endswith(".tmp")]


def test_failed_law_leaves_old_index_files_untouched(tmp_path):
    rules = _two_law_rules(tmp_path)
    td = lambda law, label: "moleg-eflaw:4@20260701#x" if law == "소득세법" else "moleg-eflaw:31@20260701#x"
    rep = fa.fetch(str(rules), _api_failing_on(fail_path="lawService.do"), td, "2026-10-09")
    assert len(rep["오류"]) == 1 and "본문 실패" in rep["오류"][0]
    assert rep["색인쓰기"] is False
    assert (rules / "조문" / "판목록.json").read_bytes() == "옛 판목록".encode("utf-8")
    assert (rules / "확인기록.json").read_bytes() == "옛 확인기록".encode("utf-8")
    assert _stray(rules) == []
    # 성공한 법령의 판 파일은 온전히 남아 다음 실행이 이어 받는다
    assert json.loads((rules / "조문" / "소득세법" / "4@2026-07-01.json").read_text(encoding="utf-8"))["MST"] == "4"


def test_search_failure_and_taxdoctor_failure_also_keep_old_index(tmp_path):
    rules = _two_law_rules(tmp_path)
    td = lambda law, label: "moleg-eflaw:4@20260701#x"
    rep = fa.fetch(str(rules), _api_failing_on("지방세법", "lawSearch.do"), td, "2026-10-09")
    assert rep["오류"] == ["검색 실패"] and rep["색인쓰기"] is False

    def td_down(law, label):
        if law == "지방세법":
            raise RuntimeError("TaxDoctor 응답 없음")
        return "moleg-eflaw:4@20260701#x"

    rep = fa.fetch(str(rules), _api_failing_on(), td_down, "2026-10-09")
    assert rep["오류"] == ["TaxDoctor 응답 없음"] and rep["색인쓰기"] is False
    assert (rules / "조문" / "판목록.json").read_bytes() == "옛 판목록".encode("utf-8")
    assert (rules / "확인기록.json").read_bytes() == "옛 확인기록".encode("utf-8")
    assert _stray(rules) == []


def test_failed_law_adds_nothing_to_report_counts(tmp_path):
    rules = _two_law_rules(tmp_path)
    td = lambda law, label: "moleg-eflaw:999@20260101#x"  # 일치하지 않는 값
    rep = fa.fetch(str(rules), _api_failing_on(fail_path="lawService.do"), td, "2026-10-09")
    assert rep["불일치"] == 1  # 끝까지 받은 소득세법의 한 조문만 센다. 지방세법은 실패해 센 것이 없다


def test_all_laws_ok_writes_both_index_files(tmp_path):
    rules = _two_law_rules(tmp_path)
    td = lambda law, label: "moleg-eflaw:4@20260701#x" if law == "소득세법" else "moleg-eflaw:31@20260701#x"
    rep = fa.fetch(str(rules), _api_failing_on(), td, "2026-10-09")
    assert rep["오류"] == [] and rep["색인쓰기"] is True
    pans = json.loads((rules / "조문" / "판목록.json").read_text(encoding="utf-8"))
    assert set(pans["법령"]) == {"소득세법", "지방세법"}
    rec = json.loads((rules / "확인기록.json").read_text(encoding="utf-8"))
    assert set(rec["법령"]) == {"소득세법", "지방세법"} and all(r["일치"] for r in rec["TaxDoctor"])
    assert _stray(rules) == []


def test_write_atomic_replaces_whole_file_and_cleans_up_on_failure(tmp_path, monkeypatch):
    target = tmp_path / "out" / "a.json"
    fa._write_atomic(str(target), "첫 내용")
    assert target.read_bytes() == "첫 내용".encode("utf-8")
    fa._write_atomic(str(target), "줄\n바꿈")
    assert target.read_bytes() == "줄\n바꿈".encode("utf-8")  # LF 그대로

    def boom(src, dst):
        raise OSError("교체 실패")

    monkeypatch.setattr(fa.os, "replace", boom)
    try:
        fa._write_atomic(str(target), "깨진 내용")
    except OSError:
        pass
    else:
        raise AssertionError("OSError 가 나와야 한다")
    assert target.read_bytes() == "줄\n바꿈".encode("utf-8")  # 옛 파일이 그대로다
    assert [p.name for p in target.parent.iterdir()] == ["a.json"]  # 임시 파일이 남지 않는다
