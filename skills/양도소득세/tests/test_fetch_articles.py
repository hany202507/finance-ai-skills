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
