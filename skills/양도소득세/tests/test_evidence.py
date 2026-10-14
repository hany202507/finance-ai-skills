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
