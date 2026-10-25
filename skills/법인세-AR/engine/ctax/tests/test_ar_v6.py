"""AR · 전기 읽기 6차(10-21) 시험. 합성 장부 · 합성 전기 신고서 글 · 합성 낱말 좌표만 쓴다(고객 자료 없음).

  총괄표    세무조정계산서총괄표 첨부 O 인데 PDF 에 없는 서식은 problems, AR 은 낸 서식으로 본다(19호 「내지 않았습니다」 막기)
  29호 3절  감가상각비(상당액) 한도초과금액 이월명세 차량별 줄(낱말 가로 위치로 빈 란을 가림)
  화물차    차량 줄이 모두 화물차 · 건설기계면 업무용승용차 이슈 없이 가이드 2-3-21-1 「해당 없음」
"""
from __future__ import annotations

from ctax.prior.form29 import carry_rows
from ctax.prior.read import build, listed_from, total_code
from ctax.tests.test_ar import by_title, journal, prior, run

# ---------------------------------------------------------------- 총괄표

TOTAL_TEXT = "\n".join([
    "법인세세무조정계산서총괄표", "해당사항유무", "첨부유무", "연번", "서식번호",
    "1", "제1호", "법인세과세표준및세액신고서", "O", "O",
    "2", "제2호", "농어촌특별세과세표준및세액신고서",
    "46", "제19호(갑)", "가지급금등의인정이자조정명세서(갑)", "O", "O",
    "47", "제19호(을)", "가지급금등의인정이자조정명세서(을)", "O", "O",
    "48", "제20호(1)", "유형고정자산감가상각비조정명세서(정률법)", "O",
    "6", "제3호2(1)", "표준대차대조표(일반법인용)", "O", "O",
    "187", "국조법제6-11호", "가상국조서식", "O", "O",
    "224", "별지제29호서식", "업무용승용차관련비용명세서", "O", "O",
])


def test_total_code_mapping():
    assert total_code("제19호(갑)") == "19갑" and total_code("제20호(1)") == "20_1" and total_code("제3호2(1)") == "std_bs"
    assert total_code("별지제29호서식") == "29" and total_code("제16호2") == "16의2" and total_code("제8호부표3") == "8부표3"
    assert total_code("조특법제10호8") == "조특10의8"
    assert total_code("국조법제6-11호") is None and total_code("제00호") is None


def test_listed_forms_missing_from_pdf_are_problems():
    pages = [{"page_no": 1, "form_code": "세무조정계산서총괄표", "form_hint": "목차:세무조정계산서총괄표", "text": TOTAL_TEXT, "words": []},
             {"page_no": 2, "form_code": "1", "form_hint": "1호", "text": "", "words": []}]
    got = {x["code"]: x for x in listed_from(pages)}
    assert set(got) == {"1", "19갑", "19을", "20_1", "std_bs", "29"}
    assert got["20_1"]["attached"] is False and got["19갑"]["attached"] is True
    data = build(pages, [], [])
    refs = {q["ref"] for q in data["problems"] if q["ref"].startswith("총괄표.")}
    assert refs == {"총괄표.19갑", "총괄표.19을", "총괄표.std_bs", "총괄표.29"}       # 1호는 PDF 에 있고 20호(1)은 첨부 O 가 없다
    assert data["listed"] and list(data)[-2:] == ["listed", "problems"]


def test_ar_treats_listed_19_as_filed():
    pr = prior(listed=[{"code": "19갑", "no": "제19호(갑)", "name": "", "applies": True, "attached": True},
                       {"code": "19을", "no": "제19호(을)", "name": "", "applies": True, "attached": True}])
    ar = run(pr=pr)
    assert not by_title(ar, "인정이자 조정과 19호가 없습니다")
    hit = by_title(ar, "인정이자 계산이 필요합니다")[0]
    assert any("전기 총괄표에" in b and "첨부 O 표시가 있습니다" in b for b in hit["basis"])
    assert not any("내지 않았습니다" in b for b in hit["basis"])
    assert any("19호 갑 · 을" in q for q in hit["questions"])


# ---------------------------------------------------------------- 29호 3절

HEAD = [(54, 64, 62, 74, "3."), (144, 64, 233, 74, "한도초과금액이월명세"), (73, 87, 91, 97, "차량"), (134, 87, 153, 97, "차종"),
        (185, 82, 212, 92, "취득일"), (172, 92, 214, 102, "(임차기간)"), (263, 87, 307, 97, "전기이월액"),
        (349, 82, 444, 92, "당기감가상각비(상당액)"), (471, 82, 547, 92, "감가상각비(상당액)"), (586, 87, 656, 97, "손금추인(산입)액"),
        (694, 87, 740, 97, "차기이월액(")]


def words(*rows):
    out = list(HEAD)
    for w in rows:
        out.append(w)
    out.append((64, 300, 289, 310, "4.업무용승용차처분손실및한도초과금액손금불산입액계산"))
    return [(*w, 0, 0, 0) for w in out]


def test_carry_rows_read_by_column():
    page = {"words": words(
        (62, 111, 103, 120, "12가3456"), (126, 111, 151, 120, "가상세단"), (170, 108, 216, 117, "2023.01.01"),
        (417, 111, 445, 120, "1,000,000"), (529, 111, 558, 120, "1,000,000"), (751, 111, 780, 120, "1,000,000"),
        (170, 116, 216, 125, "2025.12.31"),
        (62, 140, 103, 149, "34나5678"), (126, 140, 151, 149, "가상SUV"), (170, 137, 216, 146, "2019.01.01"),
        (279, 140, 307, 149, "9,000,000"), (529, 140, 558, 149, "9,000,000"), (630, 140, 656, 149, "8,000,000"),
        (751, 140, 780, 149, "1,000,000"),
        (79, 194, 95, 203, "합계"), (417, 194, 445, 203, "1,000,000"))}
    rows, why = carry_rows([page])
    assert why == []
    a, b = rows
    assert (a["car"], a["model"], a["start"], a["end"]) == ("12가3456", "가상세단", "2023.01.01", "2025.12.31")
    assert (a["opening"], a["excess"], a["cum"], a["reversal"], a["closing"]) == (0, 1000000, 1000000, 0, 1000000)
    assert (b["opening"], b["excess"], b["cum"], b["reversal"], b["closing"]) == (9000000, 0, 9000000, 8000000, 1000000)
    assert b["end"] == ""


def test_carry_row_that_does_not_add_up_is_a_problem():
    page = {"words": words((62, 111, 103, 120, "12가3456"), (417, 111, 445, 120, "1,000,000"), (751, 111, 780, 120, "2,000,000"))}
    rows, why = carry_rows([page])
    assert rows and why and "누계 = 전기 + 당기" in why[0]


# ---------------------------------------------------------------- 화물차만 있는 회사

def test_trucks_only_means_no_business_car_issue():
    jr = [r for r in journal() if r["account"] != "822"] + [
        {**journal()[2], "memo": "82다1234 포터 수리비", "debit": 6_000_000},
        {**journal()[3], "memo": "82다1234 자동차세", "debit": 3_000_000}]
    pr = prior(forms=[f for f in prior()["forms"] if f["code"] != "29"])
    ar = run(jr=jr, pr=pr)
    assert not by_title(ar, "업무용승용차 관련비용 명세")
    g = next(x for x in ar["guide"] if x["id"] == "2-3-21-1")
    assert g["status"] == "해당 없음" and any("화물차 · 건설기계" in f for f in g["facts"])


def test_passenger_line_keeps_issue():
    jr = [r for r in journal() if r["account"] != "822"] + [
        {**journal()[2], "memo": "82다1234 포터 수리비", "debit": 6_000_000},
        {**journal()[3], "memo": "렌트카 대여료 12가3456", "debit": 3_000_000}]
    pr = prior(forms=[f for f in prior()["forms"] if f["code"] != "29"])
    assert by_title(run(jr=jr, pr=pr), "업무용승용차 관련비용 명세")
