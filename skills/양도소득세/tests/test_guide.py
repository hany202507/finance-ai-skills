# -*- coding: utf-8 -*-
import copy
import re

import pytest

from yangdo import engine, filing, guide, return_values
from cases import CASES, F자산
import filers

SCREENS = ["기본정보", "양수인", "양도자산", "취득가액", "필요경비", "세액계산", "납부"]


def _rv(name, 취득상대방_비움=False, **over):
    """취득상대방_비움: 신고인 사본에서 취득상대방을 지워 매입가액 행의 거래상대방이 빈 신고값을 만든다."""
    r = engine.calculate(CASES[name], today="2026-10-11")
    f = filers.get(name)
    for aid in f["자산"]:
        f["자산"][aid]["법정동코드"] = "1120011400"
        if 취득상대방_비움:
            f["자산"][aid].pop("취득상대방", None)
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


def test_screen_table_and_section_titles_name_each_screen_the_same_way():
    md = guide.hometax_input(_rv("S1"))
    titles = dict(re.findall(r"^## [1-7]\. (\S+) \(홈택스 화면: (.+)\)$", md, re.M))
    order = md.split("## 화면 순서", 1)[1].split("## 신고 요약", 1)[0]
    table = {m[0]: m[1] for m in re.findall(r"^\| [1-7] \| (\S+) \| (.+?) \|$", order, re.M)}
    assert list(titles) == SCREENS and titles == table, (titles, table)


def test_expense_kind_names_do_not_carry_the_form_number():
    """코드표의 (10) 양도시 중개수수료 같은 이름은 안내서와 부속서류에서 번호 없이 적는다. 신고값의 이름은 그대로다."""
    rv = _rv("S1")
    assert any(r["구분"].startswith("(10) ") for s in rv["부표3"] for r in s["행"])
    for md in (guide.hometax_input(rv), guide.attachments(rv, CASES["S1"], _res("S1"))):
        assert "양도시 중개수수료 등 직접지출비용" in md and "(10)" not in md
    assert guide._kind_name({"구분": "(11) 국민주택채권 및 토지개발채권 매각차손등 기타경비"}).startswith("국민주택채권")
    assert guide._kind_name({"구분": "도로시설비 등"}) == "도로시설비 등"


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
    assert "합성법무사" in md and "0000000034" in md   # 필요경비 상세의 거래상대방과 사업자번호
    assert "입력 필요" not in md                       # 합성 자료가 필수 칸을 다 채워서 빈 칸 표시가 나오지 않는다


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
    assert "206,274,000" in md and "252,384,480" in md  # 산출세액, 납부할 세액 = 산출세액 + 가산세 46,110,480
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
    assert "입력 필요" not in guide.hometax_input(_rv("BF"))              # 값이 다 있으면 표시하지 않는다
    md = guide.hometax_input(_rv("BF", 취득상대방_비움=True))
    assert "입력 필요" in md                            # 매입가액 행 거래상대방이 신고인 JSON 에 없다


def test_input_guide_style():
    for name in ("A", "S1", "BF", "K"):
        md = guide.hometax_input(_rv(name))
        assert chr(0x2014) not in md
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
        assert chr(0x2014) not in md
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


def _mixed_facts():
    """전액 비과세 주택 G 와 과세 토지 F(환산취득가액)."""
    facts = copy.deepcopy(CASES["G"])
    facts["자산"].append(copy.deepcopy(F자산))
    return facts


def test_exempt_asset_is_not_in_the_guides():
    """전액 비과세 자산은 신고서에 넣지 않는다. 입력 안내서는 과세 자산만 적고 넣지 않은 자산을 따로 알린다.
    전액 비과세 자산뿐이면 신고값이 없어 안내서도 없다."""
    facts = _mixed_facts()
    rv, res = _rv_facts(facts)
    md = guide.hometax_input(rv)
    assert "### 자산 F" in md and "### 자산 G" not in md and "입력 필요" not in md
    assert "## 신고서에 넣지 않은 자산" in md and "전액 비과세" in md
    assert "과세되는 자산이 없다" not in md
    att = guide.attachments(rv, facts, res)
    assert "넣지 않은 자산 G" in att and "근거 자료" not in att
    with pytest.raises(return_values.NoTaxableAsset):
        _rv_facts(CASES["G"])


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
                                         "증빙종류": "세금계산서", "상대방": "합성", "사업자번호": "0000000034"}]
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
        md = guide.hometax_input(_rv(name, 취득상대방_비움=True))
        assert "입력 필요" in md
        assert md.count("신고값에 값이 없는 항목이다") == 1
        assert md.index("신고값에 값이 없는 항목이다") < md.index("## 화면 순서")
    md = guide.hometax_input(_rv_facts(_mixed_facts())[0])      # F 는 환산취득가액이라 빈 값이 없다
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


def test_final_return_penalty_note_reaches_input_guide():
    """확정신고 가산세 확인사항은 FILE_ONLY 에 걸리지 않아 입력 안내서에도 나간다. 날짜 글자(2027-02-01)를 레코드 칸 번호로
    읽어 거르지 않는다. 세액이 달라질 수 있는 해석 둘(감면 전 금액, 같은 달 양도의 대안 금액)이 빠지면 안 된다."""
    rv = _rv("BF", 구분="확정", 작성일="2027-05-20")
    notes = [m for m in rv["확인사항"] if "가산세" in m]
    assert len(notes) >= 8
    md = guide.hometax_input(rv)
    for m in notes:
        assert not guide.is_file_only_note(m), m
        assert m in md, m
    part = md.split("## 확인사항", 1)[1]
    assert "감면 없이" in part and "감면이 적용되면 무신고가산세는 20,627,400원" in part
    assert "양도일마다 따로 신고하는 것으로 보면" in part and "36,306,400원" in part
    assert "부정행위" in part and "다루지 않는다" in part


# ---- 날짜 글자(YYYY-01-dd ~ YYYY-07-dd)를 레코드 칸 번호로 읽어 확인사항을 거르지 않는다 ----

def _deadline_rv(name, made, mutate=None, **over):
    f = copy.deepcopy(CASES[name])
    if mutate:
        mutate(f)
    r = engine.calculate(f, today="2026-10-11")
    filer = filers.get(name)
    for aid in filer["자산"]:
        filer["자산"][aid]["법정동코드"] = "1120011400"
    filer["신고인"]["주소"]["법정동코드"] = "1144010200"
    filer["신고"].update(작성일=made, **over)
    return return_values.build(r, f, filing.load(filer))


def _permit_facts(permit_date):
    def mutate(f):
        a = f["자산"][0]
        a["토지거래허가대상"] = "예"
        if permit_date:
            a["토지거래허가"] = {"신청일": "2026-10-01", "허가일": permit_date}
    return mutate


def test_deadline_notes_with_january_to_july_dates_reach_input_guide():
    cases = [
        ("주말 보정", _deadline_rv("S1", "2027-02-01"), "정기신고로 만들었다", "2027-01-31"),   # 말일 2027-01-31 일요일
        ("허가일 기준", _deadline_rv("S1", "2027-02-01", _permit_facts("2027-01-10")), "허가일(2027-01-10)", "2027-01-10"),
        # 허가일이 없어도 작성일이 양도일 기준 기한(2027-02-01) 안이면 신고값을 만들고 그 날짜를 담은 확인사항을 남긴다
        ("허가일 없음", _deadline_rv("S1", "2027-02-01", _permit_facts(None)), "허가구역 단서에 해당하는지 알 수 없다", "2027-02-01"),
    ]
    for label, rv, key, date_text in cases:
        notes = [m for m in rv["확인사항"] if key in m]
        assert len(notes) == 1, label
        if date_text:
            assert date_text in notes[0] and re.search(r"-0[1-7]-", notes[0]), label        # 1~7월 날짜를 담은 문장이다
        assert not guide.FILE_ONLY.search(notes[0]), label
        assert "- " + notes[0] in guide.hometax_input(rv), label


def test_file_only_pattern_ignores_every_iso_date():
    """2025~2040년 모든 날짜가 문장에 들어 있어도 칸 번호로 읽지 않는다."""
    from datetime import date, timedelta
    d, end = date(2025, 1, 1), date(2040, 12, 31)
    while d <= end:
        assert not guide.FILE_ONLY.search("신고기한 말일 %s 이 일요일이라 다음 월요일 %s 까지로 보았다" % (d, d + timedelta(days=1))), d
        d += timedelta(days=1)


def test_file_only_pattern_still_catches_record_field_numbers():
    for text in ("03-31 주민세_세율은 합계 행만 10.00 이다", "일반건물 칸(05-46)에 넣었다", "05-10·11 칸에 적었다",
                 "02-21 칸은 비웠다", "03-30~33 칸은 0 이다", "07 레코드 상호는 Not Null 이다", "01 레코드 길이",
                 "03-31-32 칸은 0 이다", "주민세 칸(03-30-33)", "05-64-65 코드"):      # 칸 번호 뒤에 - 로 이은 꼴
        assert guide.FILE_ONLY.search(text), text
    for text in ("2027-01-31", "2027-03-01-2027-03-02 사이", "기한 2026-07-31 까지", "1-10 열", "제167조의3", "10-20 구간"):
        assert not guide.FILE_ONLY.search(text), text


# ---- T18: 매입가액 행의 지급일자 ----
# 부표3 서식은 매입가액(111) 행의 지급일 칸을 음영으로 막았고 전자신고 07 레코드도 이 행의 지급일자를 비운다.
# 신고값 행에는 취득일이 들어 있지만 신고서와 파일에 쓰지 않는 값이라 안내서가 옮기지 않는다.

def _section4(md):
    return md.split("## 4. ", 1)[1].split("## 5. ", 1)[0]


def _cells(line):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def test_purchase_price_row_has_no_payment_date_in_the_guide():
    for name in ("S1", "A", "K"):
        rv = _rv(name)
        md = guide.hometax_input(rv)
        sec = _section4(md)
        rows = [ln for ln in sec.splitlines() if ln.startswith("| 매입가액 ")]
        assert rows, name
        for ln in rows:
            assert _cells(ln)[-1] == "-", (name, ln)            # 지급일자 칸이 비었다(빈 칸은 표에 - 로 나온다)
        for a in rv["부표1"]:
            assert a["취득일"] not in " ".join(rows), name        # 취득일을 대신 채워 넣지 않는다


def test_purchase_price_note_follows_the_table_and_is_marked_unconfirmed():
    sec = _section4(guide.hometax_input(_rv("S1")))
    lines = sec.splitlines()
    table_end = max(i for i, ln in enumerate(lines) if ln.startswith("|"))
    note = [ln for ln in lines[table_end + 1:] if "매입가액 행의 지급일자" in ln]
    assert len(note) == 1
    assert "부표3" in note[0] and "전자신고 파일" in note[0] and "취득일" in note[0] and "(확인 필요)" in note[0]
    assert "2018-03-15" in note[0]                               # 화면이 요구하면 넣을 취득일을 알려 준다


def test_other_rows_keep_their_payment_dates():
    sec = _section4(guide.hometax_input(_rv("S1")))
    rows = {_cells(ln)[0]: _cells(ln) for ln in sec.splitlines() if ln.startswith("| ") and not ln.startswith("| ---")}
    assert rows["기타 부대 비용 - 법무사비용"][-1] == "2018-03-15"
    assert rows["취득세"][-1] == "-"


def test_no_purchase_price_note_without_a_purchase_price_row():
    sec = _section4(guide.hometax_input(_rv_facts(CASES["F"])[0]))   # 환산취득가액이라 부표3 이 없다
    assert "매입가액 행의 지급일자" not in sec


def test_purchase_price_note_has_no_banned_style():
    md = guide.hometax_input(_rv("S1"))
    assert chr(0x2014) not in md
    assert not [ln for ln in md.splitlines() if ln.rstrip().endswith("?")]


# ---- 확정신고 안내서의 가산세 문장 ----
# 확정신고 안내서는 가산세를 넣은 납부할 세액과, 가산세를 어떻게 셌는지를 화면에 넣을 값과 함께 적는다.
# BF 손계산: 무신고 41,254,800(감면 없음. 감면이 적용되면 20,627,400), 납부지연 4,855,680, 계 46,110,480, 납부할 세액 252,384,480

# 「가산세는 0원」 꼴의 문장. 금액의 끝자리 0(25,483,080원)은 걸리지 않게 사이 글자에서 숫자를 뺀다
ZERO_PENALTY = re.compile(r"가산세[^.\n0-9]{0,20}0원")


def test_final_return_guide_shows_the_penalty_amounts():
    md = guide.hometax_input(_rv("BF"))
    assert "확정신고" in md
    assert not ZERO_PENALTY.search(md), ZERO_PENALTY.search(md).group(0)
    body = md.split("### 세액계산 결과", 1)[1].split("## 7.", 1)[0]
    rows = {ln.split("|")[1].strip(): ln for ln in body.splitlines() if ln.startswith("|")}
    assert "41,254,800" in rows["가산세(무신고)"] and "4,855,680" in rows["가산세(납부지연)"]
    assert "46,110,480" in rows["가산세 계"] and "252,384,480" in rows["납부할 세액"]
    assert "감면세액, 외국납부세액공제, 원천징수세액은 0원이라 입력하지 않는다" in body
    assert "가산세는 계산하지 않았다" not in body and "이 값으로 입력하지 않는다" not in md
    # 건별 계산: 예정신고 세액, 납부기한, 일수
    calc = md.split("### 가산세 계산", 1)[1].split("##", 1)[0]
    assert "206,274,000" in calc and "2027-02-01" in calc and "107" in calc and "F, B" in calc
    assert "2027-05-20" in calc and "납부일" in calc           # 납부일은 작성일로 보았다
    assert "예정신고 세액 × 20%," in calc and "(1 - 50%)" not in calc      # 계산식에 감면이 없다
    assert "감면 없이 계산했다" in calc and "감면이 적용되면 무신고가산세는 20,627,400원" in calc
    assert "따로 계산해 더한다" not in md
    top = md.split("## 신고 요약", 1)[1].split("##", 1)[0]
    assert "가산세 46,110,480원" in top and "납부할 세액 252,384,480원" in top
    pay = md.split("## 7.", 1)[1]
    assert "252,384,480" in pay
    # 지방소득세: 산출세액 20,627,400 + 가산세 4,352,381(무신고 4,125,480 감면 없음, 납부지연 226,901) = 24,979,781
    local = pay.split("### 지방소득세", 1)[1]
    rows = {ln.split("|")[1].strip(): ln for ln in local.splitlines() if ln.startswith("|")}
    assert "4,125,480" in rows["가산세(무신고)"] and "226,901" in rows["가산세(납부지연)"]
    assert "24,979,781" in rows["납부할 세액(지방소득세)"]
    assert "지방소득세 예정신고 세액 × 20%," in local and "(1 - 50%)" not in local      # 계산식에 감면이 없다
    assert "지방소득세 무신고가산세는 감면 없이 계산했다. 감면이 적용되면 무신고가산세는 2,062,740원" in local
    assert "2027-03-31" in local and "50" in local               # 지방소득세 납부기한과 일수
    assert "두 가지를 가정" in local and "위택스 값을 따른다" in local
    assert "지방소득세 가산세는 계산하지 않았다" not in md and "가산세가 빠진" not in md


def test_final_return_guide_with_installment_says_the_limit_excludes_penalty():
    md = guide.hometax_input(_rv("BF", 분납신청=True))
    pay = md.split("## 7.", 1)[1].split("### 지방소득세", 1)[0]
    assert "103,137,000" in pay and "149,247,480" in pay
    assert "가산세를 뺀 세액" in md.split("## 확인사항", 1)[1]


def test_final_return_guide_when_penalty_could_not_be_determined():
    """가산세를 계산하지 못한 확정신고(같은 달에 양도한 두 자산의 합산 비교세액이 이긴 경우)는 0원이라고 적지 않는다."""
    facts = copy.deepcopy(CASES["BF"])
    facts["자산"][1]["취득"]["잔금일"] = "2025-06-01"
    r = engine.calculate(facts, today="2026-10-11")
    f = filers.get("BF")
    for aid in f["자산"]:
        f["자산"][aid]["법정동코드"] = "1120011400"
    rv = return_values.build(r, facts, filing.load(f))
    assert rv["가산세"]["계산"] is False
    md = guide.hometax_input(rv)
    assert not ZERO_PENALTY.search(md)
    body = md.split("### 세액계산 결과", 1)[1].split("## 7.", 1)[0]
    assert "가산세는 계산하지 못했다" in body and "이 값으로 입력하지 않는다" in body and "합산 비교세액" in body
    assert "### 가산세 계산" not in md


def test_preliminary_return_guide_still_says_penalty_is_zero():
    md = guide.hometax_input(_rv("S1"))
    assert "감면세액, 외국납부세액공제, 원천징수세액, 가산세는 0원이라 입력하지 않는다." in md
    assert "가산세(무신고)" not in md and "### 가산세 계산" not in md


def test_guide_shows_local_efile_credit():
    md = guide.hometax_input(_rv("S1"))
    pay = md.split("### 지방소득세", 1)[1]
    assert "3,832,946원" in pay and "전자신고세액공제는 2,000원" in pay      # 3,834,946 - 2,000
    assert "지방소득세 가산세" not in pay
