import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import coverage_check as cc  # noqa: E402


def row(name, mst, ef, prom="20260101", no="1"):
    return {"법령명한글": name, "법령일련번호": mst, "시행일자": ef, "공포일자": prom, "공포번호": no}


def pages(*rows_per_page):
    total = sum(len(r) for r in rows_per_page)
    def search(name, page):
        rows = rows_per_page[page - 1] if page <= len(rows_per_page) else []
        return {"LawSearch": {"totalCnt": str(total), "law": rows}}
    return search


def test_norm():
    assert cc.norm("댐건설·관리 및 주변지역지원") == cc.norm("댐건설ㆍ관리 및  주변지역지원")


def test_parse_taxdoctor_list():
    text = "수록 현행 법령 2건 (국세 2):\n- 소득세법 (법률, 시행 2026.07.01)\n- 소득세법 시행령 (대통령령, 시행 2026.10.01)\n"
    got = cc.parse_taxdoctor_list(text)
    assert got == {cc.norm("소득세법"): "20260701", cc.norm("소득세법 시행령"): "20261001"}


def test_resolve_finds_exact_on_second_page_and_in_force_version():
    search = pages([row("민간임대주택에 관한 특별법", "1", "20260101")],
                   [row("주택법", "289171", "20270309", "20260901"), row("주택법", "289171", "20260908", "20260301")])
    hit = cc.resolve(search, "주택법", "20261009")
    assert (hit["법령일련번호"], hit["시행일자"]) == ("289171", "20260908")


def test_resolve_none_when_no_exact_name():
    assert cc.resolve(pages([row("공영주택법", "9", "19630101")]), "주택법", "20261009") is None


def test_find_admrul():
    def search_admrul(name, page):
        return {"AdmRulSearch": {"totalCnt": "1", "admrul": [{"행정규칙ID": "85055", "행정규칙명": "조정대상지역 지정", "행정규칙일련번호": "2100000281588", "발령일자": "20260701"}]}}
    assert cc.find_admrul(search_admrul, "조정대상지역", "85055")["행정규칙일련번호"] == "2100000281588"
    assert cc.find_admrul(search_admrul, "조정대상지역", "99999") is None


LISTING = {
    "주제": "시험",
    "법령": [
        {"이름": "소득세법", "구분": "세법"},
        {"이름": "주택법", "구분": "비세법"},
        {"이름": "토지수용법", "구분": "비세법"},
        {"이름": "채권은행협의회 운영협약", "구분": "비세법"},
        {"이름": "없는법", "구분": "비세법"},
    ],
    "고시": [
        {"이름": "조정대상지역 지정·해제 공고", "분류": "지역목록", "출처": {"종류": "행정규칙", "행정규칙ID": "85055", "검색어": "조정대상지역"}},
        {"이름": "개별공시지가", "분류": "개별사실", "출처": {"종류": "확인처", "곳": ["부동산공시가격알리미"]}},
        {"이름": "빈 확인처", "분류": "개별사실", "출처": {"종류": "확인처", "곳": []}},
    ],
}
ALIASES = {"별칭": [
    {"인용명": "토지수용법", "현행명": "공익사업을 위한 토지 등의 취득 및 보상에 관한 법률", "종류": "폐지대체", "근거": "2002 공익사업법 제정으로 폐지", "등급": "★★★"},
    {"인용명": "채권은행협의회 운영협약", "현행명": "", "종류": "비법령", "근거": "은행 간 협약. 법령 아님", "등급": "★★☆"},
]}


def fake_search(name, page):
    table = {
        "소득세법": [row("소득세법", "280405", "20260701")],
        "주택법": [row("주택법", "289171", "20260908")],
        "공익사업을 위한 토지 등의 취득 및 보상에 관한 법률": [row("공익사업을 위한 토지 등의 취득 및 보상에 관한 법률", "1", "20260101")],
    }
    rows = table.get(name, []) if page == 1 else []
    return {"LawSearch": {"totalCnt": str(len(table.get(name, []))), "law": rows}}


def fake_admrul(name, page):
    return {"AdmRulSearch": {"totalCnt": "1", "admrul": [{"행정규칙ID": "85055", "행정규칙명": "조정대상지역 지정", "행정규칙일련번호": "1", "발령일자": "20260701"}]}}


def test_check_report():
    rep = cc.check(LISTING, ALIASES, fake_search, fake_admrul, {cc.norm("소득세법"): "20260701"}, "20261009")
    by = {x["이름"]: x for x in rep["항목"]}
    assert by["소득세법"]["해소"] and by["소득세법"]["TaxDoctor"] is True
    assert by["주택법"]["해소"] and by["주택법"]["TaxDoctor"] is None
    assert by["토지수용법"]["해소"] and by["토지수용법"]["현행명"].startswith("공익사업")
    assert by["채권은행협의회 운영협약"]["해소"] and "법령 아님" in by["채권은행협의회 운영협약"]["사유"]
    assert not by["없는법"]["해소"]
    assert by["조정대상지역 지정·해제 공고"]["해소"]
    assert by["개별공시지가"]["해소"]
    assert not by["빈 확인처"]["해소"]
    assert rep["요약"] == {"전체": 8, "해소": 6, "미해소": 2, "경고": 0}


def test_check_warns_when_tax_law_not_in_taxdoctor():
    listing = {"주제": "시험", "법령": [{"이름": "소득세법", "구분": "세법"}], "고시": []}
    rep = cc.check(listing, {"별칭": []}, fake_search, fake_admrul, {}, "20261009")
    item = rep["항목"][0]
    assert item["해소"] and item["TaxDoctor"] is False
    assert rep["요약"]["경고"] == 1


def test_main_exit_codes(tmp_path, monkeypatch):
    lp = tmp_path / "l.json"; ap = tmp_path / "a.json"; op = tmp_path / "o.json"
    import json
    lp.write_text(json.dumps(LISTING, ensure_ascii=False), encoding="utf-8")
    ap.write_text(json.dumps(ALIASES, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(cc, "make_sources", lambda use_td: (fake_search, fake_admrul, None))
    code = cc.main(["--목록", str(lp), "--별칭", str(ap), "--출력", str(op), "--기준일", "20261009", "--TaxDoctor생략"])
    assert code == 1
    assert json.loads(op.read_text(encoding="utf-8"))["요약"]["미해소"] == 2
