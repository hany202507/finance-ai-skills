# -*- coding: utf-8 -*-
import json
import os
from decimal import Decimal

import pytest

import build_ruleset as B
from yangdo import ruleset as R

LAW = "소득세법 시행령"


def pan(mst, ef, arts, addenda=None, 공포번호="1"):
    return {"법령": LAW, "MST": mst, "시행일": ef, "공포일": ef, "공포번호": 공포번호,
            "조문": {k: {"제목": "", "sha256": "h" + mst, "text": v} for k, v in arts.items()},
            "부칙": addenda or {}}


def make(tmp_path, rules, pans, td_ok=True):
    d = tmp_path / "rules"
    (d / "조문" / LAW).mkdir(parents=True)
    listing = {"기준시작": "2025-01-01", "받은날": "2026-10-09", "법령": {LAW: []}}
    for p, state in pans:
        rel = "%s/%s@%s.json" % (LAW, p["MST"], p["시행일"])
        (d / "조문" / rel).write_text(json.dumps(p, ensure_ascii=False), encoding="utf-8")
        listing["법령"][LAW].append({"MST": p["MST"], "시행일": p["시행일"], "공포일": p["공포일"],
                                    "공포번호": p["공포번호"], "상태": state, "파일": rel})
    (d / "조문" / "판목록.json").write_text(json.dumps(listing, ensure_ascii=False), encoding="utf-8")
    rec = {"확인일": "2026-10-09", "법령": {}, "TaxDoctor": [
        {"법령": LAW, "조": "167의10", "DRF": "2@20250228", "TaxDoctor": "2@20250228" if td_ok else "9@1", "일치": td_ok}]}
    (d / "확인기록.json").write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    (d / "추출규칙.json").write_text(json.dumps(rules, ensure_ascii=False), encoding="utf-8")
    return str(d)


OLD = "12의2. 보유기간이 2년 이상인 주택을 2025년 5월 9일까지 양도하는 경우 그 해당 주택"
NEW = "12의2. 보유기간이 2년 이상인 주택으로서\n가. 2026년 5월 9일까지 양도하는 주택"
FUT = "12의2. 삭제"
PANS = [(pan("1", "2025-01-01", {"167의10": OLD}), "연혁"),
        (pan("2", "2025-02-28", {"167의10": NEW}, {"36737": {"공포일": "2026-09-30", "sha256": "a",
                                                             "text": "2026년 8월 4일 이후에 조정대상지역에 있는 신규 주택을 취득하는 경우"}},
             공포번호="36737"), "현행"),
        (pan("3", "2027-01-01", {"167의10": FUT}), "시행예정")]


def g(발췌, **kw):
    return dict({"법령": LAW, "조": "167의10", "항": "①12호의2", "발췌": 발췌}, **kw)


RULES = {"규칙": [
    {"key": "중과.한시배제.가목.양도기한", "단위": "날짜", "이력": [
        {"시작": "2025-01-01", "끝": "2025-02-27", "기준일": "양도일", "값": "2025-05-09",
         "근거": [g(["2025년 5월 9일까지 양도하는 경우"])]},
        {"시작": "2025-02-28", "끝": None, "기준일": "양도일", "값": "2026-05-09",
         "근거": [g(["2026년 5월 9일까지 양도하는 주택"])]}]},
    {"key": "중과.한시배제.보유", "단위": "년", "이력": [
        {"시작": "2025-01-01", "끝": None, "기준일": "양도일", "값": 2, "근거": [g(["보유기간이 2년 이상인 주택"])]}]},
    {"key": "일시적2주택.조정기한.신규취득시작", "단위": "날짜", "이력": [
        {"시작": "2025-01-01", "끝": None, "기준일": "양도일", "값": "2026-08-04",
         "근거": [{"법령": LAW, "조": "부칙", "공포번호": "36737", "발췌": ["2026년 8월 4일 이후에"]}]}]},
    {"key": "기본세율", "단위": "세율표", "이력": [
        {"시작": "2025-01-01", "끝": None, "기준일": "양도일", "값": [[0, 0, "0.06"], [14000000, 840000, "0.15"]],
         "근거": [g(["2년 이상"])]}]},
    {"key": "판정.비교과세", "단위": "근거", "이력": [
        {"시작": "2025-01-01", "끝": None, "기준일": "양도일", "값": None, "근거": [g(["보유기간이 2년"])]}]},
], "계류": [{"id": "x", "내용": "중과 완화안", "영향키": ["중과.한시배제.보유"], "기준일": "양도일",
             "시작": "2026-05-10", "출처": "합성", "등급": "★★☆"}]}


def built(tmp_path, rules=RULES, pans=PANS, td_ok=True):
    d = make(tmp_path, rules, pans, td_ok)
    code, msgs = B.build(d)
    return d, code, msgs


def test_build_and_history_lookup(tmp_path):
    d, code, msgs = built(tmp_path)
    assert code == 0, msgs
    rs = R.load(d)
    assert rs.value("중과.한시배제.가목.양도기한", "2025-01-15") == "2025-05-09"
    assert rs.value("중과.한시배제.가목.양도기한", "2026-03-01") == "2026-05-09"
    assert rs.value("중과.한시배제.보유", "2026-03-01") == 2
    assert rs.value("기본세율", "2026-03-01") == [[0, 0, Decimal("0.06")], [14000000, 840000, Decimal("0.15")]]
    assert rs.value("판정.비교과세", "2026-03-01") is None
    assert rs.확인일 == "2026-10-09" and len(rs.판id) == 16


def test_excerpt_missing_in_old_version_fails(tmp_path):
    bad = json.loads(json.dumps(RULES))
    bad["규칙"][0]["이력"] = [{"시작": "2025-01-01", "끝": None, "기준일": "양도일", "값": "2026-05-09",
                               "근거": [g(["2026년 5월 9일까지 양도하는 주택"])]}]
    d, code, msgs = built(tmp_path, bad)
    assert code == 1
    assert any("2025-01-01" in m for m in msgs)
    assert not os.path.exists(os.path.join(d, "ruleset.json"))


def test_upcoming_change_is_recorded_not_failed(tmp_path):
    d, code, _ = built(tmp_path)
    rs = R.load(d)
    e = rs.entry("중과.한시배제.보유", "2026-03-01")
    assert e["예정변경"] and e["예정변경"][0]["시행일"] == "2027-01-01"
    assert rs.notes("중과.한시배제.보유", "2026-12-31") == ["계류: 중과 완화안 (합성, ★★☆)"]
    assert any("2027-01-01" in n for n in rs.notes("중과.한시배제.보유", "2027-01-02"))
    assert rs.notes("중과.한시배제.보유", "2026-05-09") == []


def test_addenda_ground(tmp_path):
    d, code, _ = built(tmp_path)
    rs = R.load(d)
    c = rs.cite("일시적2주택.조정기한.신규취득시작", "2026-10-09")[0]
    assert c["조항"] == "부칙(제36737호)" and c["URL"].startswith("https://www.law.go.kr/법령/소득세법%20시행령")
    bad = json.loads(json.dumps(RULES))
    bad["규칙"][2]["이력"][0]["근거"][0]["발췌"] = ["2026년 9월 1일 이후에"]
    assert built(tmp_path / "b", bad)[1] == 1


def test_cite_format(tmp_path):
    d, _, _ = built(tmp_path)
    c = R.load(d).cite("중과.한시배제.보유", "2026-03-01")[0]
    assert c["key"] == "중과.한시배제.보유" and c["조항"] == "제167조의10①12호의2"
    assert c["시행일"] == "2025-02-28" and c["URL"].endswith("/제167조의10")


def test_taxdoctor_mismatch_blocks(tmp_path):
    d, code, msgs = built(tmp_path, td_ok=False)
    assert code == 1 and any("TaxDoctor" in m for m in msgs)


def test_overlapping_history_fails(tmp_path):
    bad = json.loads(json.dumps(RULES))
    bad["규칙"][1]["이력"] = [
        {"시작": "2025-01-01", "끝": "2026-01-01", "기준일": "양도일", "값": 2, "근거": [g(["보유기간이 2년 이상인 주택"])]},
        {"시작": "2025-06-01", "끝": None, "기준일": "양도일", "값": 2, "근거": [g(["보유기간이 2년 이상인 주택"])]}]
    d, code, msgs = built(tmp_path, bad)
    assert code == 1 and any("겹친다" in m for m in msgs)


@pytest.mark.parametrize("mutate,word", [
    (lambda r: r["규칙"][1]["이력"][0].update(근거=[]), "근거가 없다"),
    (lambda r: r["규칙"][1]["이력"][0]["근거"][0].update(발췌=[]), "발췌가 비었다"),
    (lambda r: r["규칙"][1]["이력"][0]["근거"][0].update(발췌=[" "]), "발췌가 비었다"),
    (lambda r: r["규칙"][3].update(단위="세율"), "단위"),
])
def test_empty_grounds_and_unknown_unit_fail(tmp_path, mutate, word):
    bad = json.loads(json.dumps(RULES))
    mutate(bad)
    d, code, msgs = built(tmp_path, bad)
    assert code == 1 and any(word in m for m in msgs)


def test_cite_date_is_version_in_force_on_date(tmp_path):
    d, _, _ = built(tmp_path)
    rs = R.load(d)
    assert rs.cite("중과.한시배제.보유", "2025-01-15")[0]["시행일"] == "2025-01-01"
    assert rs.cite("중과.한시배제.보유", "2026-03-01")[0]["시행일"] == "2025-02-28"
    assert rs.cite("일시적2주택.조정기한.신규취득시작", "2025-06-01")[0]["시행일"] == "2025-02-28"


def test_edition_detects_edit_and_rebuild(tmp_path):
    d, _, _ = built(tmp_path)
    p = os.path.join(d, "ruleset.json")
    with open(p, encoding="utf-8") as f:
        data = json.load(f)
    data["확인일"] = "2026-10-10"
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    with pytest.raises(R.RuleError):
        R.load(d)
    R.write_edition(d, "2026-10-10")
    assert R.load(d).확인일 == "2026-10-10"


def test_uncovered_date_raises(tmp_path):
    d, _, _ = built(tmp_path)
    with pytest.raises(R.RuleError):
        R.load(d).value("중과.한시배제.보유", "2024-12-31")


def test_squash_and_find(tmp_path):
    assert B.squash("│ 100분의 70 │\n") == "100분의70"
    d, _, _ = built(tmp_path)
    lines = B.find(d, LAW, "167의10", "2026년 5월 9일까지")
    assert lines == ["2025-01-01 MST 1 없음", "2025-02-28 MST 2 있음", "2027-01-01 MST 3 없음"]
