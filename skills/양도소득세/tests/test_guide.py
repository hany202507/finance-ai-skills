# -*- coding: utf-8 -*-
import copy
import re

from yangdo import engine, filing, guide, return_values
from cases import CASES
import filers

SCREENS = ["기본정보", "양수인", "양도자산", "취득가액", "필요경비", "세액계산", "납부"]


def _rv(name, **over):
    r = engine.calculate(CASES[name], today="2026-10-11")
    f = filers.get(name)
    for aid in f["자산"]:
        f["자산"][aid]["법정동코드"] = "1120011400"
    f["신고인"]["주소"]["법정동코드"] = "1144010200"
    f["신고"].update(over)
    return return_values.build(r, CASES[name], filing.load(f))


def test_input_guide_lists_screens_in_order_with_amounts():
    md = guide.hometax_input(_rv("S1"))
    order = ["기본정보", "양수인", "양도자산", "취득가액", "필요경비", "세액계산", "납부"]
    pos = [md.index(x) for x in order]
    assert pos == sorted(pos)
    assert "1,800,000,000" in md and "38,349,466" in md


def test_input_guide_has_no_rrn():
    md = guide.hometax_input(_rv("S1"))
    assert "0001011" not in md                      # 주민등록번호는 안내서에 쓰지 않는다


def test_attachment_list():
    md = guide.attachments(_rv("S1"), CASES["S1"])
    for s in ("매매계약서", "취득", "양도", "필요경비 증빙", "세금계산서", "현금영수증"):
        assert s in md


# ---- 아래는 T13 에서 더한 시험 ----

def test_screen_sections_are_numbered_in_order():
    md = guide.hometax_input(_rv("S1"))
    sec = re.findall(r"^## ([1-7])\. (\S+)", md, re.M)
    assert [n for n, _ in sec] == list("1234567")
    assert [name for _, name in sec] == SCREENS


def test_input_guide_header_warns_and_keeps_personal_numbers_out():
    for name in ("S1", "BF"):
        rv = _rv(name)
        md = guide.hometax_input(rv)
        head = md.split("## ", 1)[0]
        assert "신고 내용이 들어 있다" in head and "공유에 주의" in head
        assert "형식검증이 통과하면 이 안내서는 필요 없다" in head
        # 신고인·양수인 주민등록번호와 전화번호는 어디에도 없다
        secret = [rv["신고인"]["주민등록번호"], rv["신고인"]["전화"]] + [b["번호"] for b in rv["양수인"]]
        secret += [b["전화"] for b in rv["양수인"] if b["전화"]]
        for s in secret:
            assert s not in md
        assert "신고인 본인 정보" in md


def test_input_guide_screen_names_from_research():
    md = guide.hometax_input(_rv("S1"))
    for name in ("양도자산 및 거래일", "양도소득금액", "세율 선택 도우미", "장특공 계산기", "합산신고대상 불러오기",
                 "분납·환급계좌", "정기신고"):
        assert name in md
    assert "(화면 이름 확인 필요)" in md


def test_input_guide_s1_values():
    rv = _rv("S1")
    md = guide.hometax_input(rv)
    for s in ("600,000,000", "6,600,000", "12,000,000", "9,000,000", "21,000,000", "609,800,000", "1,169,200,000",
              "779,466,667", "389,733,333", "233,839,999", "155,893,334", "2,500,000", "153,393,334", "20,000",
              "38,329,466", "서울특별시 성동구"):
        assert s in md, s
    assert "이합성" in md                              # 양수인 성명은 화면에 직접 입력하는 값이다
    assert "합성법무사" in md and "2118104565" in md   # 필요경비 상세의 거래상대방


def test_input_guide_local_income_tax_via_wetax():
    rv = _rv("S1")
    md = guide.hometax_input(rv)
    assert "위택스" in md and "지방소득세 신고하기" in md
    assert "3,834,946" in md


def test_input_guide_installment():
    rv = _rv("S1", 분납신청=True)
    t = rv["본지"]["열"]["합계"]
    md = guide.hometax_input(rv)
    assert t["분납"] > 0
    assert "{:,}".format(t["분납"]) in md and "{:,}".format(t["신고기한내납부"]) in md
    assert "분납하지 않는다" not in md
    assert "분납하지 않는다" in guide.hometax_input(_rv("S1"))


def test_input_guide_confirmed_return_has_no_electronic_credit():
    md = guide.hometax_input(_rv("BF"))
    assert "확정신고" in md
    assert "206,274,000" in md                         # 납부할 세액 = 산출세액
    assert "20,000" not in " ".join(l for l in md.splitlines() if "전자신고세액공제" in l)   # 확정신고에는 공제가 없다


def test_input_guide_two_assets_and_converted_acquisition():
    rv = _rv("BF")
    md = guide.hometax_input(rv)
    assert "환산취득가액" in md
    assert "500,000,000" in md and "200,000,000" in md   # 매입가액, 환산 자산의 취득 시 기준시가
    assert "개산공제" in md                              # 환산 자산의 기타필요경비
    assert "### 자산 B" in md and "### 자산 F" in md


def test_input_guide_warns_about_prior_filings():
    md = guide.hometax_input(_rv("S1"))
    i = md.index("합산신고대상 불러오기")
    assert "멈추고" in md[i:i + 400]


def test_input_guide_marks_blank_required_values():
    md = guide.hometax_input(_rv("BF"))
    assert "입력 필요" in md                            # 매입가액 행 거래상대방이 신고인 JSON 에 없다


def test_input_guide_style():
    for name in ("A", "S1", "BF", "K"):
        md = guide.hometax_input(_rv(name))
        assert "—" not in md
        assert "그리디" not in md
        assert not any(line.rstrip().endswith(("?", "？")) for line in md.splitlines())


def test_attachment_list_sections_for_s1():
    md = guide.attachments(_rv("S1"), CASES["S1"])
    assert "신고 부속·증빙서류 제출" in md
    assert "양도 매매계약서" in md and "취득 매매계약서" in md
    assert "신규 주택" in md and "2025-06-02" in md           # 일시적 2주택이면 신규 주택 취득 계약서
    assert "기준시가" not in md                               # 실지거래가액이면 기준시가 자료는 없다
    i = md.index("필요경비 증빙")
    for s in ("세금계산서", "현금영수증", "합성법무사", "합성인테리어", "9,000,000", "12,000,000"):
        assert s in md[i:], s
    assert md.index("세금계산서", i) < md.index("합성인테리어", i)  # 증빙종류별로 묶는다


def test_attachment_list_groups_by_evidence_kind():
    md = guide.attachments(_rv("S1"), CASES["S1"])
    i = md.index("필요경비 증빙")
    j = md.index("현금영수증", i)
    k = md.index("세금계산서", i)
    assert md.count("세금계산서", i) >= 1 and md.count("**세금계산서**") == 1 and md.count("**현금영수증**") == 1
    assert j != k


def test_attachment_list_converted_acquisition_needs_standard_price_papers():
    rv = _rv("BF")
    md = guide.attachments(rv, CASES["BF"])
    assert "기준시가" in md
    assert "200,000,000" in md and "500,000,000" in md        # 환산 자산 F 의 취득·양도 기준시가
    assert "신규 주택" not in md                              # BF 는 일시적 2주택이 아니다


def test_attachment_list_has_no_personal_numbers():
    for name in ("S1", "BF"):
        rv = _rv(name)
        md = guide.attachments(rv, CASES[name])
        for s in [rv["신고인"]["주민등록번호"], rv["신고인"]["전화"]] + [b["번호"] for b in rv["양수인"]]:
            assert s not in md
        assert "—" not in md
        assert not any(line.rstrip().endswith(("?", "？")) for line in md.splitlines())


def test_attachment_list_for_plain_asset_has_contracts_only():
    rv = _rv("A")
    md = guide.attachments(rv, CASES["A"])
    assert "양도 매매계약서" in md and "취득 매매계약서" in md
    assert "신규 주택" not in md and "기준시가 확인" not in md


def _rv_facts(facts, kind="예정", made="2026-12-20"):
    """사실관계를 바꿔 만든 사례용. 자산마다 합성 지번과 양수인을 붙인다."""
    r = engine.calculate(facts, today="2026-10-11")
    assert r["상태"] == "완료", r["질문"] or r["다루지않음"]
    ids = [a["id"] for a in facts["자산"]]
    f = filers.filer(kind, made, {i: filers.lot(str(100 + n)) for n, i in enumerate(ids)},
                     [filers.buyer(i, serial="3456" + str(n)) for n, i in enumerate(ids)])
    for aid in f["자산"]:
        f["자산"][aid]["법정동코드"] = "1120011400"
    f["신고인"]["주소"]["법정동코드"] = "1144010200"
    return return_values.build(r, facts, filing.load(f))


def test_all_exempt_asset_has_no_blank_markers():
    facts = CASES["G"]
    rv = _rv_facts(facts)
    md = guide.hometax_input(rv)
    assert "전액 비과세" in md and "입력 필요" not in md
    assert "과세되는 자산이 없다" in md
    att = guide.attachments(rv, facts)
    assert "전액 비과세" in att and "근거 자료" not in att


def test_two_rate_columns():
    facts = CASES["BC"]
    rv = _rv_facts(facts, "확정", "2027-05-20")
    md = guide.hometax_input(rv)
    cols = [x["표기"] for x in rv["본지"]["세율구분"]]
    assert len(cols) == 2
    for c in cols:
        assert "세율구분 " + c in md
    assert "{:,}".format(rv["본지"]["열"]["합계"]["납부할세액"]) in md


def test_comparable_sale_and_appraisal_attachments():
    f = copy.deepcopy(CASES["F"])
    f["자산"][0]["매매사례가액"] = 450_000_000
    att = guide.attachments(_rv_facts(f), f)
    assert "매매사례가액 근거 자료" in att and "기준시가 확인" not in att
    f = copy.deepcopy(CASES["F"])
    f["자산"][0]["감정가액"] = [500_000_000, 520_000_000]
    att = guide.attachments(_rv_facts(f), f)
    assert "감정평가서" in att and "기준시가 확인" not in att


def test_converted_price_with_actual_costs_exception():
    f = copy.deepcopy(CASES["F"])
    f["자산"][0]["필요경비"]["자본적지출"] = [{"내용": "기타가치증가", "지급일": "2010-01-01", "금액": 500_000_000,
                                         "증빙종류": "세금계산서", "상대방": "합성", "사업자번호": "2118104565"}]
    rv = _rv_facts(f)
    md = guide.hometax_input(rv)
    assert "제97조②2호 단서" in md and "500,000,000" in md
    att = guide.attachments(rv, f)
    assert "기준시가 확인" in att and "**세금계산서**" in att and "합성" in att
