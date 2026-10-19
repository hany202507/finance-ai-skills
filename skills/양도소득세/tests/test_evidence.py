# -*- coding: utf-8 -*-
"""증빙 검증·반영 시험. 계약서와 영수증은 합성 PDF 를 시험 안에서 만든다(실제 자료 없음)."""
import copy
import json
import os

import fitz
import pytest

from yangdo import evidence as E

CONTRACT_P1 = ["부동산 매매계약서", "제1조 매매대금은 일금 1,500,000,000원으로 한다.",
               "제2조 계약금은 2026년 9월 1일에 지급한다."]
CONTRACT_P2 = ["제3조 잔금은 2026년 11월 15일에 지급한다.", "제7조 용도변경 특약 없음.",
               "매도인 주민등록번호 800101-1234567"]


def _pdf(path, pages):
    d = fitz.open()
    for lines in pages:
        p = d.new_page()
        for i, line in enumerate(lines):
            p.insert_text((50, 80 + 24 * i), line, fontname="korea", fontsize=11)
    d.save(path)
    d.close()


@pytest.fixture
def folder(tmp_path):
    f = tmp_path / "증빙"
    f.mkdir()
    _pdf(str(f / "1_매매계약서.pdf"), [CONTRACT_P1, CONTRACT_P2])
    _pdf(str(f / "2_세금계산서.pdf"), [["공급가액 12,000,000원", "작성일자 2022-03-02", "공급자 사업자등록번호 123-45-67890",
                                        "품목 샷시 교체 공사"]])
    # 글자층이 없는 이미지: 쪽을 그림으로 찍어 PNG 로 저장한다
    d = fitz.open()
    p = d.new_page()
    p.insert_text((50, 80), "취득세 납부 2,100,000원", fontname="korea", fontsize=14)
    p.get_pixmap(dpi=80).save(str(f / "3_취득세영수증.png"))
    d.close()
    return str(f)


@pytest.fixture
def inv(folder):
    return E.inventory(folder)


def _item(문항, 값, 문서, 발췌, 쪽=1, 확신="확실", 자산="A"):
    return {"문항": 문항, "자산": 자산, "값": 값, "출처": {"문서": 문서, "쪽": 쪽, "발췌": 발췌}, "확신": 확신}


FACTS = {"자산": [{"id": "A"}]}


def test_inventory_marks_text_layer_and_scans(inv):
    docs = {d["파일"]: d for d in inv["문서"]}
    assert [d["id"] for d in inv["문서"]] == ["D01", "D02", "D03"]
    assert docs["1_매매계약서.pdf"]["글자층"] is True and docs["1_매매계약서.pdf"]["쪽수"] == 2
    assert docs["3_취득세영수증.png"]["글자층"] is False and "불확실" in docs["3_취득세영수증.png"]["안내"]


def test_inventory_missing_folder(tmp_path):
    with pytest.raises(E.EvidenceError):
        E.inventory(str(tmp_path / "없음"))


@pytest.mark.parametrize("text,want", [("5억 3천만원", 530000000), ("3,000만원", 30000000), ("일금 1,500,000,000원", 1500000000),
                                       ("2억", 200000000), ("1억 2,000만원", 120000000)])
def test_amounts_in(text, want):
    assert want in E.amounts_in(text)


def test_dates_in_reads_common_forms():
    assert E.dates_in("2026년 11월 15일, 2022-03-02, 2020.1.5") == {"2026-11-15", "2022-03-02", "2020-01-05"}


def test_verified_values_are_applied(inv):
    items = [_item("A11", "2026-11-15", "D01", "잔금은 2026년 11월 15일에 지급한다", 쪽=2),
             _item("M01", 1500000000, "D01", "매매대금은 일금 1,500,000,000원으로 한다."),
             _item("A13", False, "D01", "용도변경 특약 없음", 쪽=2)]
    f, rep = E.apply(FACTS, items, inv)
    a = f["자산"][0]
    assert a["양도"]["잔금일"] == "2026-11-15" and a["전체양도가액"] == 1500000000 and a["양도"]["용도변경특약"] is False
    assert len(rep["반영"]) == 3 and not rep["거절"] and not rep["확인필요"]
    assert FACTS == {"자산": [{"id": "A"}]}  # 원본은 그대로


def test_invented_quote_is_rejected(inv):
    f, rep = E.apply(FACTS, [_item("A11", "2026-12-31", "D01", "잔금은 2026년 12월 31일에 지급한다")], inv)
    assert rep["거절"] and "원문에 없다" in rep["거절"][0]["사유"]
    assert "양도" not in f["자산"][0] or f["자산"][0]["양도"].get("잔금일") is None


def test_value_not_in_quote_waits_for_confirmation(inv):
    f, rep = E.apply(FACTS, [_item("M01", 1600000000, "D01", "매매대금은 일금 1,500,000,000원으로 한다.")], inv)
    assert rep["확인필요"] and "1,600,000,000" in rep["확인필요"][0]["사유"]
    assert f["자산"][0].get("전체양도가액") is None


def test_uncertain_and_scanned_documents_wait_for_confirmation(inv):
    items = [_item("A11", "2026-11-15", "D01", "잔금은 2026년 11월 15일에 지급한다", 쪽=2, 확신="불확실"),
             _item("M07", 2100000, "D03", "취득세 납부 2,100,000원")]
    f, rep = E.apply(FACTS, items, inv)
    assert len(rep["확인필요"]) == 2 and not rep["반영"]
    assert "글자층이 없는" in rep["확인필요"][1]["사유"]


def test_existing_different_value_is_a_conflict_and_same_value_is_a_match(inv):
    facts = {"자산": [{"id": "A", "양도": {"잔금일": "2026-11-20"}, "전체양도가액": 1500000000}]}
    items = [_item("A11", "2026-11-15", "D01", "잔금은 2026년 11월 15일에 지급한다", 쪽=2),
             _item("M01", 1500000000, "D01", "매매대금은 일금 1,500,000,000원으로 한다.")]
    f, rep = E.apply(facts, items, inv)
    assert f["자산"][0]["양도"]["잔금일"] == "2026-11-20"
    assert len(rep["충돌"]) == 1 and len(rep["일치"]) == 1 and not rep["반영"]


def test_same_question_twice_with_different_values_conflicts(inv):
    items = [_item("A11", "2026-11-15", "D01", "잔금은 2026년 11월 15일에 지급한다", 쪽=2),
             _item("A11", "2026-09-01", "D01", "계약금은 2026년 9월 1일에 지급한다")]
    f, rep = E.apply(FACTS, items, inv)
    assert f["자산"][0]["양도"]["잔금일"] == "2026-11-15"
    assert len(rep["반영"]) == 1 and len(rep["충돌"]) == 1


def test_resident_number_never_reaches_report_or_facts(inv):
    bad = _item("A13", False, "D01", "매도인 주민등록번호 800101-1234567", 쪽=2)
    f, rep = E.apply(FACTS, [bad], inv)
    assert "800101" not in json.dumps(rep, ensure_ascii=False) and "800101" not in json.dumps(f, ensure_ascii=False)
    assert "******-*******" in json.dumps(rep, ensure_ascii=False)
    worse = _item("A13", "800101-1234567", "D01", "매도인 주민등록번호 800101-1234567", 쪽=2)
    _, rep2 = E.apply(FACTS, [worse], inv)
    assert rep2["거절"] and "800101" not in json.dumps(rep2, ensure_ascii=False)


def test_unknown_question_document_and_empty_quote_are_rejected(inv):
    items = [_item("Z99", 1, "D01", "x"), _item("M01", 1, "D77", "x"), _item("M01", 1, "D01", "")]
    _, rep = E.apply(FACTS, items, inv)
    assert len(rep["거절"]) == 3


def test_wrong_page_number_is_tolerated_when_quote_is_in_the_document(inv):
    f, rep = E.apply(FACTS, [_item("A11", "2026-11-15", "D01", "잔금은 2026년 11월 15일에 지급한다", 쪽=1)], inv)
    assert len(rep["반영"]) == 1


def test_remaining_questions_list_needed_documents(inv):
    f, rep = E.apply(FACTS, [_item("M01", 1500000000, "D01", "매매대금은 일금 1,500,000,000원으로 한다.")], inv)
    ids = {p["id"] for p in rep["남은문항"]}
    assert "M01" not in ids and "A11" in ids
    a11 = next(p for p in rep["남은문항"] if p["id"] == "A11")
    assert "양도 매매계약서" in a11["증빙서류"]


def test_confirm_table_has_sections_and_no_resident_number(inv):
    items = [_item("A11", "2026-11-15", "D01", "잔금은 2026년 11월 15일에 지급한다", 쪽=2),
             _item("A13", False, "D01", "매도인 주민등록번호 800101-1234567", 쪽=2),
             _item("M07", 2100000, "D03", "취득세 납부 2,100,000원")]
    _, rep = E.apply(FACTS, items, inv)
    md = E.confirm_markdown(rep, inv)
    for head in ("사실관계에 넣은 값", "확인이 필요한 값", "아직 묻지 못한 문항"):
        assert head in md
    assert "800101" not in md and "1_매매계약서.pdf" in md


def test_capital_expenditure_list_is_checked_item_by_item(inv):
    value = [{"내용": "샷시", "지급일": "2022-03-02", "금액": 12000000, "증빙종류": "세금계산서", "상대방": "공급업체",
              "사업자번호": "1234567890"}]
    quote = "공급가액 12,000,000원 작성일자 2022-03-02"
    try:
        f, rep = E.apply(FACTS, [_item("M09", value, "D02", quote)], inv)
    except Exception as e:  # 형식 표가 다르면 이 시험이 알려 준다
        pytest.fail(str(e))
    assert rep["반영"] or rep["거절"], rep
    if rep["반영"]:
        assert f["자산"][0]["필요경비"]["자본적지출"][0]["금액"] == 12000000


def _row(내용, 지급일, 금액, 증빙종류="세금계산서", 상대방="공급업체", 사업자번호="1234567890"):
    return {"내용": 내용, "지급일": 지급일, "금액": 금액, "증빙종류": 증빙종류, "상대방": 상대방, "사업자번호": 사업자번호}


@pytest.fixture
def inv_two_receipts(folder):
    """세금계산서(D02)에 더해 발코니 공사 이체 확인증(D04)이 있는 증빙 폴더."""
    _pdf(os.path.join(folder, "4_이체확인증.pdf"), [["이체금액 18,000,000원", "이체일자 2022-05-10", "받는분 합성인테리어"]])
    return E.inventory(folder)


SASH_QUOTE = "공급가액 12,000,000원 작성일자 2022-03-02"
BALCONY_QUOTE = "이체금액 18,000,000원 이체일자 2022-05-10"


def test_list_question_rows_from_several_documents_are_joined(inv_two_receipts):
    items = [_item("M09", [_row("샷시", "2022-03-02", 12000000)], "D02", SASH_QUOTE),
             _item("M09", [_row("발코니확장", "2022-05-10", 18000000, 증빙종류="계좌이체", 상대방="합성인테리어")], "D04",
                   BALCONY_QUOTE)]
    f, rep = E.apply(FACTS, items, inv_two_receipts)
    rows = f["자산"][0]["필요경비"]["자본적지출"]
    assert [r["금액"] for r in rows] == [12000000, 18000000]
    assert len(rep["반영"]) == 2 and not rep["충돌"], rep


def test_list_question_same_row_twice_is_a_match_not_a_second_expense(inv_two_receipts):
    row = _row("샷시", "2022-03-02", 12000000)
    items = [_item("M09", [row], "D02", SASH_QUOTE), _item("M09", [dict(row)], "D02", SASH_QUOTE)]
    f, rep = E.apply(FACTS, items, inv_two_receipts)
    assert len(f["자산"][0]["필요경비"]["자본적지출"]) == 1
    assert len(rep["반영"]) == 1 and len(rep["일치"]) == 1 and not rep["충돌"], rep


def test_list_question_same_payment_from_another_document_waits_for_the_user(inv_two_receipts):
    """같은 지급일·금액의 지출이 다른 서류에서 다른 모양으로 오면 같은 지출을 두 서류로 낸 것일 수 있어 넣지 않는다."""
    _pdf_quote = "이체금액 18,000,000원 이체일자 2022-05-10"
    items = [_item("M09", [_row("발코니확장", "2022-05-10", 18000000)], "D04", _pdf_quote),
             _item("M09", [_row("발코니확장", "2022-05-10", 18000000, 증빙종류="계좌이체", 상대방="합성인테리어")], "D04",
                   _pdf_quote)]
    f, rep = E.apply(FACTS, items, inv_two_receipts)
    assert len(f["자산"][0]["필요경비"]["자본적지출"]) == 1
    assert len(rep["반영"]) == 1 and len(rep["충돌"]) == 1 and "같은 지급일·금액" in rep["충돌"][0]["사유"], rep


def test_list_question_already_in_facts_is_not_extended(inv_two_receipts):
    """사실관계에 원래 있던 목록은 덮어쓰지도 늘리지도 않는다. 이번 실행에서 넣은 목록만 이어 붙인다."""
    facts = {"자산": [{"id": "A", "필요경비": {"자본적지출": [_row("보일러", "2021-01-05", 3000000)]}}]}
    items = [_item("M09", [_row("샷시", "2022-03-02", 12000000)], "D02", SASH_QUOTE)]
    f, rep = E.apply(facts, items, inv_two_receipts)
    assert [r["내용"] for r in f["자산"][0]["필요경비"]["자본적지출"]] == ["보일러"]
    assert len(rep["충돌"]) == 1 and not rep["반영"], rep


def test_cli_inventory_then_apply_writes_facts_and_table(folder, tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "evidence_cli", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "evidence.py"))
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    out = str(tmp_path / "out")
    assert cli.main(["inventory", folder, "--출력", out]) == 0
    items = [_item("A11", "2026-11-15", "D01", "잔금은 2026년 11월 15일에 지급한다", 쪽=2),
             _item("M07", 2100000, "D03", "취득세 납부 2,100,000원")]
    ep = tmp_path / "증빙추출.json"
    ep.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    facts = str(tmp_path / "facts.json")  # 없으면 자산 A 로 시작한다
    assert cli.main(["apply", "--사실관계", facts, "--추출", str(ep), "--목록", os.path.join(out, "증빙_목록.json"), "--출력", out]) == 0
    f = json.load(open(facts, encoding="utf-8"))
    assert f["자산"][0]["양도"]["잔금일"] == "2026-11-15" and f["자산"][0].get("필요경비", {}).get("취득세") is None
    md = open(os.path.join(out, "증빙_확인표.md"), encoding="utf-8").read()
    assert "확인이 필요한 값" in md and "M07" in md


def test_cli_reports_bad_inputs_with_exit_code_2(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "evidence_cli2", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "evidence.py"))
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    assert cli.main(["inventory", str(tmp_path / "없음"), "--출력", str(tmp_path)]) == 2
    assert cli.main(["apply", "--사실관계", str(tmp_path / "f.json"), "--추출", str(tmp_path / "x.json"),
                     "--목록", str(tmp_path / "y.json"), "--출력", str(tmp_path)]) == 2


def test_mcp_tools_round_trip(folder, tmp_path):
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
    import mcp_server as M
    out = str(tmp_path / "mcp_out")
    r = M.call_tool("yangdo_evidence_inventory", {"folder": folder, "out_dir": out})
    assert [d["id"] for d in r["문서"]] == ["D01", "D02", "D03"]
    items = [_item("M01", 1500000000, "D01", "매매대금은 일금 1,500,000,000원으로 한다.")]
    res = M.call_tool("yangdo_evidence_apply", {"inventory_path": r["목록파일"], "extractions": items, "out_dir": out})
    assert res["반영"] == 1 and res["사실관계"]["자산"][0]["전체양도가액"] == 1500000000
    assert os.path.exists(res["확인표"])
    # facts_path 를 주면 그 파일을 고쳐 쓴다
    fp = tmp_path / "f.json"
    fp.write_text(json.dumps(FACTS), encoding="utf-8")
    res2 = M.call_tool("yangdo_evidence_apply", {"facts_path": str(fp), "inventory_path": r["목록파일"], "extractions": items, "out_dir": out})
    assert "사실관계" not in res2 and json.load(open(fp, encoding="utf-8"))["자산"][0]["전체양도가액"] == 1500000000


# ---- 빠른 문답: 계약서와 영수증으로 문항을 더 채운다 -------------------------------
# 서울 다세대(빌라) 한 채를 판 합성 사례. 양도·취득 매매계약서, 취득 때 법무사 영수증, 양도 때 중개보수 현금영수증 네 장이다.

SALE_P1 = ["부동산(다세대주택) 매매계약서",
           "1. 부동산의 표시",
           "소재지 서울특별시 마포구 망원동 123-4 합성빌라 302호",
           "건물 구조 철근콘크리트조 용도 다세대주택 면적 59.8m2",
           "제1조 매매대금 금 520,000,000원",
           "계약금 금 52,000,000원은 2026년 8월 20일에 지불하고 영수함.",
           "잔금 금 468,000,000원은 2026년 10월 30일에 지불한다."]
SALE_P2 = ["제2조 매도인은 잔금 수령과 동시에 소유권이전등기에 필요한 서류를 교부한다.",
           "특약사항",
           "1. 현 시설물 상태의 계약이며 매수인은 현장을 확인하였다.",
           "2. 잔금일까지의 관리비와 공과금은 매도인이 정산한다.",
           "계약일 2026년 8월 20일",
           "매도인 주민등록번호 800101-1234567"]
SPECIAL = "특약사항 1. 현 시설물 상태의 계약이며 매수인은 현장을 확인하였다."
BUY_P1 = ["부동산(다세대주택) 매매계약서",
          "소재지 서울특별시 마포구 망원동 123-4 합성빌라 302호",
          "제1조 매매대금 금 380,000,000원",
          "계약금 금 38,000,000원은 2019년 3월 2일에 지불하고 영수함.",
          "잔금 금 342,000,000원은 2019년 4월 30일에 지불한다."]
LAWYER = ["영수증(법무사 보수 및 비용)", "사건 소유권이전등기(매매) 서울특별시 마포구 망원동",
          "보수액 550,000원", "취득세 4,180,000원", "영수일 2019년 4월 30일", "합성법무사사무소"]
BROKER = ["현금영수증", "거래일시 2026-10-30", "가맹점명 합성공인중개사사무소", "품목 부동산 중개보수", "합계금액 2,080,000원"]


@pytest.fixture
def villa(tmp_path):
    f = tmp_path / "빌라"
    f.mkdir()
    _pdf(str(f / "1_양도_매매계약서.pdf"), [SALE_P1, SALE_P2])
    _pdf(str(f / "2_취득_매매계약서.pdf"), [BUY_P1])
    _pdf(str(f / "3_법무사_영수증.pdf"), [LAWYER])
    _pdf(str(f / "4_중개보수_현금영수증.pdf"), [BROKER])
    return E.inventory(str(f))


def _expense(내용, 지급일, 금액, 증빙종류, 상대방):
    return [{"내용": 내용, "지급일": 지급일, "금액": 금액, "증빙종류": 증빙종류, "상대방": 상대방}]


def villa_items():
    return [
        _item("P02", "주택", "D01", "용도 다세대주택"),
        _item("P03", "매매", "D01", "부동산(다세대주택) 매매계약서"),
        _item("A01", {"시도": "서울특별시", "시군구": "마포구", "읍면동": "망원동"}, "D01", "서울특별시 마포구 망원동"),
        _item("A04", "연립다세대", "D01", "용도 다세대주택"),
        _item("A07", True, "D03", "사건 소유권이전등기(매매) 서울특별시 마포구 망원동"),
        _item("A09", "2026-08-20", "D01", "계약일 2026년 8월 20일", 쪽=2),
        _item("A10", "2026-08-20", "D01", "계약금 금 52,000,000원은 2026년 8월 20일에 지불하고 영수함."),
        _item("A11", "2026-10-30", "D01", "잔금 금 468,000,000원은 2026년 10월 30일에 지불한다."),
        _item("A13", False, "D01", SPECIAL, 쪽=2),
        _item("M01", 520000000, "D01", "제1조 매매대금 금 520,000,000원"),
        _item("A15", "매매", "D02", "부동산(다세대주택) 매매계약서"),
        _item("A16", {"계약일": "2019-03-02", "계약금지급일": "2019-03-02"}, "D02",
              "계약금 금 38,000,000원은 2019년 3월 2일에 지불하고 영수함."),
        _item("A17", {"잔금일": "2019-04-30"}, "D02", "잔금 금 342,000,000원은 2019년 4월 30일에 지불한다."),
        _item("M05", "계약서", "D02", "제1조 매매대금 금 380,000,000원"),
        _item("M06", 380000000, "D02", "제1조 매매대금 금 380,000,000원"),
        _item("M07", 4180000, "D03", "취득세 4,180,000원"),
        _item("M08", _expense("법무사보수", "2019-04-30", 550000, "간이영수증", "합성법무사사무소"), "D03",
              "보수액 550,000원 취득세 4,180,000원 영수일 2019년 4월 30일"),
        _item("M11", _expense("중개수수료", "2026-10-30", 2080000, "현금영수증", "합성공인중개사사무소"), "D04",
              "거래일시 2026-10-30 가맹점명 합성공인중개사사무소 품목 부동산 중개보수 합계금액 2,080,000원"),
    ]


def test_villa_documents_fill_type_absence_and_dates(villa):
    f, rep = E.apply(FACTS, villa_items(), villa)
    a = f["자산"][0]
    assert not rep["거절"] and not rep["충돌"], rep
    assert a["종류"] == "주택" and a["양도"]["원인"] == "매매" and a["주택유형"] == "연립다세대"
    assert a["소재지"] == {"시도": "서울특별시", "시군구": "마포구", "읍면동": "망원동"}
    assert a["양도"]["용도변경특약"] is False and a["취득"]["원인"] == "매매" and a["취득가액_확인"] == "계약서"
    a13 = next(r for r in rep["반영"] if r["문항"] == "A13")
    assert "조항이 없다" in a13["사유"]
    # 법무사 영수증은 등기를 신청했다는 정황이라 넣지 않고 제안으로 올린다
    assert "등기" not in a and [r["문항"] for r in rep["확인필요"]] == ["A07"]
    assert rep["확인필요"][0]["사유"].startswith("제안")
    left = {p["id"] for p in rep["남은문항"]}
    assert not left & {"P02", "P03", "A01", "A04", "A09", "A10", "A11", "A12", "A13", "A15", "A16", "A17", "M01", "M05", "M06"}
    assert "A07" in left
    # 잔금일을 알아 양도 등기접수일(A12)은 묻지 않는 문항으로 간다
    assert [(s["id"], s["자산"]) for s in rep["생략"]] == [("A12", "A")] and "162조" in rep["생략"][0]["안내"]
    # 흔한 값은 가정으로 올린다. 넣지는 않는다
    assert {(g["id"], json.dumps(g["값"], ensure_ascii=False)) for g in rep["가정"]} == {("M02", '"타인"'), ("M04", "true")}
    assert "매수인관계" not in a and "계약금액일치" not in a
    md = E.confirm_markdown(rep, villa)
    for head in ("가정한 값", "묻지 않는 문항", "메모"):
        assert head in md
    assert "800101" not in md and "123-4" not in md


def test_confirmed_suggestion_and_assumptions_leave_only_questions_without_documents(villa):
    """확인표를 사용자가 그대로 맞다고 하면 제안과 가정을 넣는다. 그 뒤 남는 문항은 서류로 답할 수 없는 것들이다."""
    from yangdo import questions as Q
    f, rep = E.apply(FACTS, villa_items(), villa)
    f = Q.answer(f, "A07", True, 자산="A")
    for g in rep["가정"]:
        f = Q.answer(f, g["id"], g["값"], 자산=g["자산"])
    nq = Q.next_questions(f, limit=None)
    left = [p["id"] for p in nq["다음"]]
    assert not set(left) & {"A07", "M02", "M04", "A12"}
    assert {"P01", "P04", "P05", "H01", "H03", "H04"} <= set(left), left


@pytest.mark.parametrize("qid,value,quote,ok", [
    ("A04", "연립다세대", "용도 다세대주택", True),
    ("A04", "아파트", "용도 다세대주택", False),                 # 발췌의 낱말과 다른 값
    ("A04", "주거용오피스텔", "용도 다세대주택", False),          # 오피스텔·근생을 집으로 썼는지는 문서로 정하지 않는다
    ("P02", "주택", "용도 다세대주택", True),
    ("P03", "매매", "부동산(다세대주택) 매매계약서", True),
    ("M05", "계약서", "제1조 매매대금 금 520,000,000원", True),
    ("M05", "계약서", "부동산(다세대주택) 매매계약서", False),    # 금액 문장이 아니다
])
def test_choice_values_must_match_words_in_the_quote(villa, qid, value, quote, ok):
    f, rep = E.apply(FACTS, [_item(qid, value, "D01", quote)], villa)
    assert (len(rep["반영"]) == 1) is ok and (len(rep["확인필요"]) == 1) is (not ok), rep


@pytest.mark.parametrize("quote", ["건물 용도 제1종근린생활시설 및 다세대주택", "용도 오피스텔"])
def test_mixed_use_or_officetel_building_is_not_called_a_house(tmp_path, quote):
    d = tmp_path / "겸용"
    d.mkdir()
    _pdf(str(d / "계약서.pdf"), [["부동산 매매계약서", quote, "제1조 매매대금 금 300,000,000원"]])
    inv = E.inventory(str(d))
    f, rep = E.apply(FACTS, [_item("P02", "주택", "D01", quote), _item("A04", "연립다세대", "D01", quote)], inv)
    assert not rep["반영"] and len(rep["확인필요"]) == 2 and "종류" not in f["자산"][0]


def _contract(tmp_path, special_lines):
    d = tmp_path / "특약"
    d.mkdir()
    _pdf(str(d / "계약서.pdf"), [["부동산 매매계약서", "제1조 매매대금 금 300,000,000원"], ["특약사항"] + special_lines])
    return E.inventory(str(d))


def test_use_change_clause_anywhere_in_the_contract_blocks_the_no_answer(tmp_path):
    inv = _contract(tmp_path, ["1. 현 시설물 상태의 계약이다.", "2. 매수인은 잔금 후 근린생활시설로 용도변경한다."])
    f, rep = E.apply(FACTS, [_item("A13", False, "D01", "특약사항 1. 현 시설물 상태의 계약이다.", 쪽=2)], inv)
    assert not rep["반영"] and "용도변경" in rep["확인필요"][0]["사유"] and "양도" not in f["자산"][0]


def test_no_answer_needs_the_special_terms_as_the_quote(villa):
    f, rep = E.apply(FACTS, [_item("A13", False, "D01", "제1조 매매대금 금 520,000,000원")], villa)
    assert not rep["반영"] and "특약" in rep["확인필요"][0]["사유"]


def test_explicit_no_clause_sentence_is_still_accepted(tmp_path):
    inv = _contract(tmp_path, ["1. 용도변경 특약 없음.", "2. 매수인이 양도소득세를 대신 내는 약정은 없다."])
    items = [_item("A13", False, "D01", "특약사항 1. 용도변경 특약 없음.", 쪽=2),
             _item("A14", 0, "D01", "특약사항 1. 용도변경 특약 없음.", 쪽=2)]
    f, rep = E.apply(FACTS, items, inv)
    assert [r["문항"] for r in rep["반영"]] == ["A13"], rep
    # 「양도소득세를 대신 내는 약정은 없다」는 낱말 바로 뒤에 없음이 붙지 않아 사용자 확인으로 간다
    assert [r["문항"] for r in rep["확인필요"]] == ["A14"]


def test_buyer_paid_tax_absence(villa, tmp_path):
    f, rep = E.apply(FACTS, [_item("A14", 0, "D01", SPECIAL, 쪽=2)], villa)
    assert f["자산"][0]["양도"]["매수인부담세액"] == 0 and len(rep["반영"]) == 1
    inv = _contract(tmp_path, ["1. 이 거래의 양도소득세는 매수인이 부담한다."])
    f2, rep2 = E.apply(FACTS, [_item("A14", 0, "D01", "특약사항 1. 이 거래의 양도소득세는 매수인이 부담한다.", 쪽=2)], inv)
    assert not rep2["반영"] and "양도소득세" in rep2["확인필요"][0]["사유"]


def test_true_and_false_are_not_mixed_up_with_amounts():
    assert E.is_absence("A13", False) and not E.is_absence("A13", 0) and not E.is_absence("A13", True)
    assert E.is_absence("A14", 0) and not E.is_absence("A14", False) and not E.is_absence("A14", 1)


def test_registration_suggestion_from_a_scan_is_still_a_suggestion(inv):
    f, rep = E.apply(FACTS, [_item("A07", True, "D03", "취득세 납부 2,100,000원")], inv)
    assert rep["확인필요"][0]["사유"].startswith("제안") and "등기" not in f["자산"][0]


@pytest.mark.parametrize("value,quote", [
    ({"시도": "서울특별시", "시군구": "마포구", "읍면동": "망원동"}, "소재지 서울특별시 마포구 망원동 123-4"),
    ({"시도": "서울특별시", "시군구": "마포구", "읍면동": "망원동 123-4"}, "서울특별시 마포구 망원동"),
])
def test_address_with_lot_number_is_rejected_and_not_echoed(villa, value, quote):
    f, rep = E.apply(FACTS, [_item("A01", value, "D01", quote)], villa)
    assert rep["거절"] and "읍면동까지만" in rep["거절"][0]["사유"]
    assert "123-4" not in json.dumps(rep, ensure_ascii=False) and "소재지" not in f["자산"][0]


@pytest.mark.parametrize("text,is_number", [
    ("서울특별시 중구 을지로3가", False), ("서울특별시 종로구 종로1·2·3·4가동", False), ("서울특별시 노원구 상계10동", False),
    ("서울특별시 마포구 망원동 123-4", True), ("서울특별시 중구 세종대로 110", True), ("테헤란로 123길 45", True),
    ("망원동 합성빌라 302호", True), ("망원동 101동", True), ("망원동 12번지", True),
])
def test_address_number_pattern_keeps_dong_names(text, is_number):
    assert bool(E.ADDRESS_NUMBER.search(text)) is is_number


def test_address_parts_must_be_in_the_quote(villa):
    _, rep = E.apply(FACTS, [_item("A01", {"시도": "서울특별시", "시군구": "용산구", "읍면동": "망원동"}, "D01",
                                   "서울특별시 마포구 망원동")], villa)
    assert rep["확인필요"] and "용산구" in rep["확인필요"][0]["사유"]
    _, rep2 = E.apply(FACTS, [_item("A01", {"시도": "서울", "시군구": "마포구"}, "D01", "서울특별시 마포구 망원동")], villa)
    assert len(rep2["반영"]) == 1    # 시도 약칭도 받는다


def test_mcp_apply_returns_applied_rows_assumptions_and_skipped(villa, tmp_path):
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
    import mcp_server as M
    inv_path = tmp_path / "증빙_목록.json"
    inv_path.write_text(json.dumps(villa, ensure_ascii=False), encoding="utf-8")
    res = M.call_tool("yangdo_evidence_apply", {"inventory_path": str(inv_path), "extractions": villa_items(),
                                                "out_dir": str(tmp_path / "out")})
    assert res["반영"] == len(res["넣은값"]) and any(r["문항"] == "A04" for r in res["넣은값"])
    assert {g["id"] for g in res["가정"]} == {"M02", "M04"} and [s["id"] for s in res["생략"]] == ["A12"]
    assert "800101" not in json.dumps(res, ensure_ascii=False)
