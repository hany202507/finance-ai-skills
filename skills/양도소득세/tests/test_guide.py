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


def _res(name):
    return engine.calculate(CASES[name], today="2026-10-11")


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
    md = guide.attachments(_rv("S1"), CASES["S1"], _res("S1"))
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
    md = guide.attachments(_rv("S1"), CASES["S1"], _res("S1"))
    assert "신고 부속·증빙서류 제출" in md
    assert "양도 매매계약서" in md and "취득 매매계약서" in md
    assert "신규 주택" in md and "2028-06-02" in md           # 일시적 2주택이면 신규 주택 취득 계약서(엔진의 처분기한)
    assert "기준시가" not in md                               # 실지거래가액이면 기준시가 자료는 없다
    i = md.index("필요경비 증빙")
    for s in ("세금계산서", "현금영수증", "합성법무사", "합성인테리어", "9,000,000", "12,000,000"):
        assert s in md[i:], s
    assert md.index("세금계산서", i) < md.index("합성인테리어", i)  # 증빙종류별로 묶는다


def test_attachment_list_groups_by_evidence_kind():
    md = guide.attachments(_rv("S1"), CASES["S1"], _res("S1"))
    i = md.index("필요경비 증빙")
    j = md.index("현금영수증", i)
    k = md.index("세금계산서", i)
    assert md.count("세금계산서", i) >= 1 and md.count("**세금계산서**") == 1 and md.count("**현금영수증**") == 1
    assert j != k


def test_attachment_list_converted_acquisition_needs_standard_price_papers():
    rv = _rv("BF")
    md = guide.attachments(rv, CASES["BF"], _res("BF"))
    assert "기준시가" in md
    assert "200,000,000" in md and "500,000,000" in md        # 환산 자산 F 의 취득·양도 기준시가
    assert "신규 주택" not in md                              # BF 는 일시적 2주택이 아니다


def test_attachment_list_has_no_personal_numbers():
    for name in ("S1", "BF"):
        rv = _rv(name)
        md = guide.attachments(rv, CASES[name], _res(name))
        for s in [rv["신고인"]["주민등록번호"], rv["신고인"]["전화"]] + [b["번호"] for b in rv["양수인"]]:
            assert s not in md
        assert "—" not in md
        assert not any(line.rstrip().endswith(("?", "？")) for line in md.splitlines())


def test_attachment_list_for_plain_asset_has_contracts_only():
    rv = _rv("A")
    md = guide.attachments(rv, CASES["A"], _res("A"))
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
    return return_values.build(r, facts, filing.load(f)), r


def _attach_args(facts, kind="예정", made="2026-12-20"):
    rv, res = _rv_facts(facts, kind, made)
    return rv, facts, res


def test_all_exempt_asset_has_no_blank_markers():
    facts = CASES["G"]
    rv, res = _rv_facts(facts)
    md = guide.hometax_input(rv)
    assert "전액 비과세" in md and "입력 필요" not in md
    assert "과세되는 자산이 없다" in md
    att = guide.attachments(rv, facts, res)
    assert "전액 비과세" in att and "근거 자료" not in att


def test_two_rate_columns():
    facts = CASES["BC"]
    rv, _ = _rv_facts(facts, "확정", "2027-05-20")
    md = guide.hometax_input(rv)
    cols = [x["표기"] for x in rv["본지"]["세율구분"]]
    assert len(cols) == 2
    for c in cols:
        assert "세율구분 " + c in md
    assert "{:,}".format(rv["본지"]["열"]["합계"]["납부할세액"]) in md


def test_comparable_sale_and_appraisal_attachments():
    f = copy.deepcopy(CASES["F"])
    f["자산"][0]["매매사례가액"] = 450_000_000
    att = guide.attachments(*_attach_args(f))
    assert "매매사례가액 근거 자료" in att and "기준시가 확인" not in att
    f = copy.deepcopy(CASES["F"])
    f["자산"][0]["감정가액"] = [500_000_000, 520_000_000]
    att = guide.attachments(*_attach_args(f))
    assert "감정평가서" in att and "기준시가 확인" not in att


def test_converted_price_with_actual_costs_exception():
    f = copy.deepcopy(CASES["F"])
    f["자산"][0]["필요경비"]["자본적지출"] = [{"내용": "기타가치증가", "지급일": "2010-01-01", "금액": 500_000_000,
                                         "증빙종류": "세금계산서", "상대방": "합성", "사업자번호": "2118104565"}]
    rv, res = _rv_facts(f)
    md = guide.hometax_input(rv)
    assert "제97조②2호 단서" in md and "500,000,000" in md
    att = guide.attachments(rv, f, res)
    assert "기준시가 확인" in att and "**세금계산서**" in att and "합성" in att


# ---- fix round 1: 일시적 2주택은 엔진 판정만 읽는다 ----

NEW_HOUSE = "신규 주택(일시적 2주택의 다른 집) 취득 계약서"


def test_new_house_contract_listed_when_engine_flags_temporary_two_house():
    res = _res("S1")
    assert res["계산"]["자산"][0]["판정"]["일시적2주택"] is True
    att = guide.attachments(_rv("S1"), CASES["S1"], res)
    assert NEW_HOUSE in att
    assert res["계산"]["자산"][0]["판정"]["처분기한"] in att       # 엔진이 정한 값을 그대로 적는다


def test_new_house_decision_ignores_facts():
    res = _res("S1")
    rv = _rv("S1")
    assert guide.attachments(rv, None, res) == guide.attachments(rv, CASES["S1"], res)
    # 사실관계를 엔진 결과와 어긋나게 바꿔도 목록은 엔진 결과만 따른다
    other = copy.deepcopy(CASES["S1"])
    other["세대"]["주택목록"] = other["세대"]["주택목록"][:1]
    assert NEW_HOUSE in guide.attachments(rv, other, res)


def test_no_new_house_when_second_house_acquired_after_sale():
    f = copy.deepcopy(CASES["S1"])
    h2 = next(h for h in f["세대"]["주택목록"] if h["id"] == "H2")
    h2["취득일"], h2["계약일"], h2["계약금지급일"] = "2026-12-01", "2026-12-01", "2026-12-01"
    rv, res = _rv_facts(f, made="2026-12-20")
    assert res["계산"]["자산"][0]["판정"]["일시적2주택"] is False
    assert NEW_HOUSE not in guide.attachments(rv, f, res)


def test_no_new_house_when_second_house_already_sold():
    f = copy.deepcopy(CASES["S1"])
    h2 = next(h for h in f["세대"]["주택목록"] if h["id"] == "H2")
    h2["양도일"] = "2026-05-01"
    rv, res = _rv_facts(f)
    v = res["계산"]["자산"][0]["판정"]
    assert v["일시적2주택"] is False and v["주택수"] == 1
    assert NEW_HOUSE not in guide.attachments(rv, f, res)


def test_no_new_house_for_ordinary_asset():
    assert NEW_HOUSE not in guide.attachments(_rv("A"), CASES["A"], _res("A"))


# ---- fix round 1: 문구와 표시 ----

def test_attachment_list_head_does_not_tell_to_type_on_screen():
    head = guide.attachments(_rv("S1"), CASES["S1"], _res("S1")).split("## ", 1)[0]
    assert "화면에 입력한다" not in head and "주민등록번호와 전화번호는 이 파일에 적지 않는다" in head


def test_blank_marker_is_explained_once_in_head():
    for name in ("S1", "BF"):
        md = guide.hometax_input(_rv(name))
        assert "입력 필요" in md
        assert md.count("신고값에 값이 없는 항목이다") == 1
        assert md.index("신고값에 값이 없는 항목이다") < md.index("## 화면 순서")
    md = guide.hometax_input(_rv_facts(CASES["G"])[0])
    assert "신고값에 값이 없는 항목이다" not in md


def test_unverified_screen_behaviour_is_marked_for_checking():
    md = guide.hometax_input(_rv("S1"))
    assert "홈택스가 자동으로 적용한다" not in md and "로그인 정보로 화면에 나온다" not in md
    assert md.count("(확인 필요)") >= 2


def test_local_income_tax_credit_is_read_from_the_values():
    rv = _rv("S1")
    rv["지방"]["열"]["합계"]["전자신고공제"] = 1234
    assert "전자신고세액공제는 1,234원으로 계산했다" in guide.hometax_input(rv)
    rv["지방"]["열"]["합계"]["전자신고공제"] = 0
    assert "전자신고세액공제는 0원으로 계산했다" in guide.hometax_input(rv)


def test_asset_kind_comes_from_the_calculation_record_code():
    rv = _rv("S1")
    rv["전자신고"]["계산명세"][0]["자산의종류"] = "03"          # 부표1 의 자산종류 글자가 아니라 05 레코드 코드를 읽는다
    assert "| 자산종류 | 일반주택 |" in guide.hometax_input(rv)


def test_file_only_notes_are_left_out_and_screen_notes_are_kept():
    rv = _rv("S1")
    file_only = [
        "S1: 07 레코드 취득세(11201) 행 상호는 취득세 납세지인 시군구 이름으로 적었다",
        "전자신고 03 레코드에 국내 소계 행을 넣었다(규격서 p32). 03-31 주민세_세율은 합계 행만 10.00 이다",
        "S1: 소재지의 법정동코드를 정하지 못했다. 신고인 JSON 에 10자리로 적는다(질문 F04)",
        "S1: 양도 원인 경매의 등기목적 코드를 정하지 못했다. 6자리로 적는다",
        "S1: 양도 당시 건물 기준시가를 일반건물 칸(05-46)에 넣었다",
    ]
    kept = [
        "S1: 필요경비에서 뺀 지출이라 부표3·07 레코드에 넣지 않았다. 간이영수증만 있다",
        "토지거래허가대상 자산이 있다. 신고유형 1 로 두었으니 확인한다(규격서 p26)",
        "합산 비교 세액이 커서 합계 산출세액이 세율구분 열의 합과 다르다",
    ]
    rv["확인사항"] = file_only + kept
    md = guide.hometax_input(rv)
    for x in file_only:
        assert x not in md, x
    for x in kept:
        assert x in md, x
    assert "전자신고 파일에만 쓰는 확인사항은 신고값의 확인사항에 있다" in md
