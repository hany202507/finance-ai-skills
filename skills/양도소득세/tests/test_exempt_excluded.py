# -*- coding: utf-8 -*-
"""계획 2b G2: 전액 비과세 자산은 신고서와 전자신고 파일에서 빼고 과세 자산만 신고한다.

합성 사례(실제 사람·주소·거래와 관계없다). 기대값은 규칙세트의 율과 세율로 손계산했다(엔진이나 신고값 출력에서 옮긴 값이 아니다).
  GF  G(마포 주택, 일시적 2주택 비과세, 2026-11-30 양도 10억원, 전액 비과세) + F(평택 토지, 2026-11-01 양도 10억원, 환산취득가액)
      F: 환산취득가액 1,000,000,000 × 200,000,000/500,000,000 = 400,000,000, 개산공제 200,000,000 × 3% = 6,000,000
         양도차익 594,000,000, 장기보유특별공제(21년, 표1 30%) 178,200,000, 양도소득금액 415,800,000
         기본공제 2,500,000(전액 비과세 자산은 기본공제를 받지 않는다), 과세표준 413,300,000
         산출세액 94,060,000 + 113,300,000 × 40% = 139,380,000, 지방소득세 9,406,000 + 113,300,000 × 4% = 13,938,000
      예정신고(2026-12-20): 전자신고세액공제 20,000 → 납부할 세액 139,360,000. 지방 2,000 → 13,936,000
      확정신고(2027-05-20, 예정신고 안 함): 예정신고 건은 F 하나다(G 는 세액이 없어 건이 아니다)
         무신고 139,380,000 × 20% = 27,876,000
         납부기한 2027-01-31(일) → 2027-02-01, 일수 02-02 ~ 05-19 = 27 + 31 + 30 + 19 = 107
         납부지연 139,380,000 × 107 × 22/100,000 = 3,281,005.2 → 3,281,000, 계 31,157,000, 납부할 세액 170,537,000
         지방: 무신고 13,938,000 × 20% = 2,787,600, 기한 2027-03-31, 일수 04-01 ~ 05-20 = 50
               납부지연 13,938,000 × 50 × 22/100,000 = 153,318, 계 2,940,918, 납부할 총세액 16,878,918
  SGF 과세 자산 둘 사이에 전액 비과세 자산이 낀 확정신고. 손계산은 test_exempt_asset_between_two_taxable_assets_on_a_final_return 에 있다
      S(평택 토지, 2025-06-01 3억원 취득, 2026-10-20 4억원 양도, 보유 2년 미만) + G + F
  GT  G + T(평택 토지, 2015-05-01 3억원 취득, 2026-11-10 5억원 양도, 양도 중개수수료 2,000,000). 부표3·07 행이 생기는 과세 자산
      T: 양도차익 500,000,000 − 300,000,000 − 2,000,000 = 198,000,000, 장기보유특별공제(11년, 표1 22%) 43,560,000
         양도소득금액 154,440,000, 과세표준 151,940,000, 산출세액 151,940,000 × 38% − 19,940,000 = 37,797,200
"""
import copy
import json
import os

import pymupdf
import pytest

import filers
import make_return as MR
import mcp_server
from cases import CASES, F자산, asset, 평택
from yangdo import engine, filing, forms_check, guide, penalty, return_values

TODAY = "2026-10-11"
DASH = chr(0x2014)
PDFS = {"양도소득세_신고서.pdf", "지방소득세_신고서.pdf"}
GUIDES = {"홈택스_입력안내.md", "부속서류.md"}
CALC = {"result.json", "양도소득세_검토.md", "양도소득세_계산근거.xlsx"}
LEFT_OUT = "전액 비과세로 판정한 자산(G)은 신고서와 전자신고 파일에 넣지 않았다"
NO_TAXABLE = "신고서를 만들 과세 자산이 없다"

T자산 = asset("T", "토지", 평택, "2015-05-01", "2026-11-10", 500_000_000, 300_000_000, 토지사용현황="사업용",
            필요경비={"취득세": 0, "취득부대": [], "자본적지출": [], "기타": [],
                  "양도비": [{"내용": "중개수수료", "지급일": "2026-11-10", "금액": 2_000_000, "증빙종류": "현금영수증",
                            "상대방": "합성공인중개사", "사업자번호": "0000000015"}]})


S자산 = asset("S", "토지", 평택, "2025-06-01", "2026-10-20", 400_000_000, 300_000_000, 토지사용현황="사업용")


def sgf_facts():
    """자산 순서 S(과세, 2년 미만 보유 토지), G(전액 비과세 주택), F(과세 토지). 전액 비과세 자산이 가운데 있다."""
    f = copy.deepcopy(CASES["G"])
    f["자산"] = [copy.deepcopy(S자산), f["자산"][0], copy.deepcopy(F자산)]
    return f


def gf_facts():
    f = copy.deepcopy(CASES["G"])          # 자산 순서는 G(전액 비과세), F(과세)
    f["자산"].append(copy.deepcopy(F자산))
    return f


def gt_facts():
    f = copy.deepcopy(CASES["G"])
    f["자산"].append(copy.deepcopy(T자산))
    return f


def _land_lot(seller=None):
    return dict(filers.lot("300", seller), 아파트명="", 아파트동="", 아파트호="")


def mixed_filer(taxed="F", 구분="예정", 작성일="2026-12-20", with_exempt=True, seller=None):
    """과세 자산 하나와 G 의 합성 신고인. with_exempt 가 거짓이면 G 의 지번과 양수인을 적지 않는다(신고서에 넣지 않는 자산이다)."""
    lots = {taxed: _land_lot(seller)}
    buyers = [filers.buyer(taxed, "박합성", "45678")]
    if with_exempt:
        lots["G"] = filers.lot("77")
        buyers.insert(0, filers.buyer("G"))
    return filers.filer(구분, 작성일, lots, buyers)


def g_only_filer(구분="예정", 작성일="2026-12-20"):
    return filers.filer(구분, 작성일, {"G": filers.lot("77")}, [filers.buyer("G")])


def _calc(facts):
    r = engine.calculate(copy.deepcopy(facts), today=TODAY)
    assert r["상태"] == "완료", r["질문"] or r["다루지않음"] or r["검산"]
    return r


def _build(facts, filer):
    r = _calc(facts)
    return r, return_values.build(r, facts, filing.load(copy.deepcopy(filer)))


def _main(tmp_path, facts, filer, today=TODAY):
    fp, gp, out = tmp_path / "f.json", tmp_path / "g.json", tmp_path / "out"
    fp.write_text(json.dumps(facts, ensure_ascii=False), encoding="utf-8")
    gp.write_text(json.dumps(filer, ensure_ascii=False), encoding="utf-8")
    return MR.main(["--사실관계", str(fp), "--신고인", str(gp), "--출력", str(out), "--오늘", today]), out


def _read(out, name):
    with open(os.path.join(str(out), name), encoding="utf-8") as fh:
        return fh.read()


def _records(out, name):
    """전자신고 파일의 레코드를 자료구분(앞 2바이트)별로 모은다."""
    with open(os.path.join(str(out), name), "rb") as fh:
        lines = [ln for ln in fh.read().split(b"\r\n") if ln]
    by = {}
    for ln in lines:
        by.setdefault(ln[:2].decode("ascii"), []).append(ln)
    return by


def _pdf_text(out, name):
    doc = pymupdf.open(os.path.join(str(out), name))
    try:
        return "\n".join(page.get_text() for page in doc)
    finally:
        doc.close()


# ---------------------------------------------------------------- 엔진: 전액 비과세 자산은 합계와 열에 금액이 없다

def test_engine_totals_of_the_mixed_case_are_the_taxable_asset_alone():
    c = _calc(gf_facts())["계산"]
    g, f = c["자산"]
    assert (g["id"], g["판정"]["전액비과세"], g["계산"]["기본공제"], g["계산"]["합산묶음"]) == ("G", True, 0, None)
    assert (f["계산"]["양도소득금액"], f["계산"]["기본공제"], f["계산"]["과세표준"]) == (415_800_000, 2_500_000, 413_300_000)
    assert c["세율별"] == [{"국내외분": "1", "세율구분": "10", "과세표준": 413_300_000, "산출세액": 139_380_000}]
    t = c["합계"]
    assert (t["과세표준"], t["산출세액"], t["지방소득세"], t["합산비교세액"]) == (413_300_000, 139_380_000, 13_938_000, 0)


# ---------------------------------------------------------------- 신고값

def test_return_values_leave_out_the_exempt_asset():
    r, rv = _build(gf_facts(), mixed_filer())
    assert [x["자산"] for x in rv["부표1"]] == ["F"]
    assert rv["부표3"] == []                                         # F 는 환산취득가액이라 부표3 이 없다
    assert [(b["자산"], b["일련번호"]) for b in rv["양수인"]] == [("F", 1)]
    rows = rv["전자신고"]["계산명세"]
    assert [(x["자산"], x["일련번호"], x["과세구분"]) for x in rows] == [("F", 1, "ZZ")]
    assert rv["전자신고"]["필요경비명세"] == []
    assert rv["제외자산"] == [{"자산": "G", "사유": "전액 비과세"}]
    assert [x["표기"] for x in rv["본지"]["세율구분"]] == ["1-10"]
    for name in ("합계", "국내소계", "1-10"):
        c = rv["본지"]["열"][name]
        assert (c["양도소득금액"], c["기본공제"], c["과세표준"], c["산출세액"]) == (415_800_000, 2_500_000, 413_300_000, 139_380_000), name
        assert (c["전자신고공제"], c["납부할세액"]) == (20_000, 139_360_000), name
    loc = rv["지방"]["열"]["합계"]
    assert (loc["과세표준"], loc["산출세액"], loc["전자신고공제"], loc["납부할세액"]) == (413_300_000, 13_938_000, 2_000, 13_936_000)
    t = rv["부표1합계"]
    assert (t["양도가액"], t["양도차익"], t["양도소득금액"]) == (1_000_000_000, 594_000_000, 415_800_000)      # G 의 양도가액 10억원이 들지 않는다
    z = [x for x in rv["전자신고"]["세율별"] if x["국내외분"] == "Z"][0]
    assert (z["양도소득금액"], z["과세표준"], z["산출세액"], z["자진납부할세액"]) == (415_800_000, 413_300_000, 139_380_000, 139_360_000)
    assert rv["신고"]["양도일자"] == "20261101"                       # 신고서에 넣은 자산의 양도일이다(G 는 2026-11-30)
    note = [m for m in rv["확인사항"] if "전액 비과세로 판정한 자산" in m]
    assert note == [LEFT_OUT + ". 비과세 요건을 과세관청이 달리 보면 그 자산은 신고하지 않은 것이 된다. 세무 전문가와 확인한다"]
    assert not [m for m in rv["확인사항"] if m.startswith("G:")]      # 넣지 않은 자산의 지번·등기 코드 문장이 없다
    assert forms_check.check(rv, r, facts=gf_facts()) == []


def test_exempt_asset_needs_no_lot_or_buyer_in_the_filer_file():
    """신고서에 넣지 않는 자산의 지번과 양수인은 묻지 않는다. 적어 두었어도 신고값에 옮기지 않는다."""
    facts = gf_facts()
    r = _calc(facts)
    bare = filing.load(mixed_filer(with_exempt=False))
    assert filing.questions(bare, facts, r) == []
    assert [q["문항"] for q in filing.questions(bare, facts)] == ["F02", "F04"]      # 계산 결과 없이 물으면 어느 자산이 빠질지 모른다
    rv = return_values.build(r, facts, bare)
    assert [x["자산"] for x in rv["부표1"]] == ["F"] and [b["자산"] for b in rv["양수인"]] == ["F"]
    full = return_values.build(r, facts, filing.load(mixed_filer()))
    dumped = json.dumps(full, ensure_ascii=False)
    assert filers.buyer("G")["번호"] not in dumped                 # G 양수인의 번호가 신고값에 없다
    assert filers.buyer("F", "박합성", "45678")["번호"] in dumped


def test_exempt_asset_does_not_decide_the_filing_month_or_deadline():
    """예정신고 묶음과 신고기한은 신고서에 넣는 자산으로 정한다. F 를 2026-10-05 에 양도하고 G 는 2026-11-30 에 양도했다.
    F 의 예정신고 기한은 2026-12-31 이고, 2026-12-20 에 만드는 예정신고서에는 F 만 들어간다."""
    facts = gf_facts()
    facts["자산"][1]["양도"]["잔금일"] = "2026-10-05"
    r, rv = _build(facts, mixed_filer())
    assert [x["자산"] for x in rv["부표1"]] == ["F"] and rv["신고"]["양도일자"] == "20261005"
    assert forms_check.check(rv, r, facts=facts) == []


def test_only_exempt_assets_is_no_taxable_asset():
    r = _calc(CASES["G"])
    with pytest.raises(return_values.NoTaxableAsset) as e:
        return_values.build(r, CASES["G"], filing.load(g_only_filer()))
    assert isinstance(e.value, return_values.Unsupported) and e.value.계획 == "없음"
    assert NO_TAXABLE in str(e.value) and "G" in str(e.value) and e.value.자산 == ["G"]


def test_sequence_numbers_follow_the_assets_in_the_return():
    """G 가 앞에 있어도 05·07 의 일련번호는 신고서에 넣은 자산만으로 1 부터 센다."""
    facts = gt_facts()
    r, rv = _build(facts, mixed_filer("T", seller=filers.SELLER))
    assert [x["자산"] for x in rv["부표1"]] == ["T"] and [s["자산"] for s in rv["부표3"]] == ["T"]
    row = rv["전자신고"]["계산명세"][0]
    assert (row["자산"], row["일련번호"], row["필요경비신고자료일련번호"]) == ("T", 1, 1)
    assert [(x["자산"], x["일련번호"], x["상세일련번호"], x["지급금액"]) for x in rv["전자신고"]["필요경비명세"]] == [
        ("T", 1, 1, 300_000_000), ("T", 1, 2, 2_000_000)]
    t = rv["본지"]["열"]["합계"]
    assert (t["양도소득금액"], t["과세표준"], t["산출세액"]) == (154_440_000, 151_940_000, 37_797_200)
    assert forms_check.check(rv, r, facts=facts) == []


def test_exempt_asset_between_two_taxable_assets_on_a_final_return(tmp_path):
    """과세 자산 S 와 F 사이에 전액 비과세 G 가 낀 확정신고(예정신고 안 함, 작성일 2027-05-20).
    신고서에는 S, F 순서로 두 자산만 들어가고 05·04 일련번호는 1, 2 로 이어진다. 세율구분 열은 둘이고 합산 비교세액이 크다.

    손계산(규칙세트의 율과 세율)
      S: 양도차익 400,000,000 − 300,000,000 = 100,000,000. 보유 2년 미만이라 장기보유특별공제가 없다. 먼저 양도한 자산이라
         기본공제 2,500,000 을 받는다(전액 비과세 G 는 받지 않는다). 과세표준 97,500,000
         2년 미만 보유 세율 40%: 39,000,000(누진세율 15,360,000 + 9,500,000 × 35% = 18,685,000 보다 크다). 세율구분 1-15
      F: 양도소득금액 415,800,000(GF 와 같다), 기본공제 없음. 과세표준 415,800,000
         산출세액 94,060,000 + 115,800,000 × 40% = 140,380,000. 세율구분 1-10
      세율별 세액의 합 39,000,000 + 140,380,000 = 179,380,000
      합산 비교세액: 과세표준 합 513,300,000 → 174,060,000 + 13,300,000 × 42% = 179,646,000. 이쪽이 커서 산출세액은 179,646,000
      가산세: 양도월이 달라 예정신고 건이 둘이다(S 10월, F 11월). 가산세는 건별 예정신고 세액에 붙는다
         무신고 (39,000,000 + 140,380,000) × 20% = 35,876,000(S 7,800,000, F 28,076,000)
         S 건: 기한 말일 2026-12-31(목), 일수 2027-01-01 ~ 05-19 = 31 + 28 + 31 + 30 + 19 = 139
               납부지연 39,000,000 × 139 × 22/100,000 = 1,192,620
         F 건: 기한 말일 2027-01-31(일) → 2027-02-01, 일수 02-02 ~ 05-19 = 107
               납부지연 140,380,000 × 107 × 22/100,000 = 3,304,545.2 → 3,304,540
         납부지연 합 4,497,160, 가산세 계 40,373,160
      ⑱ 납부할 세액 179,646,000 + 40,373,160 = 220,019,160. 합산 비교세액이 커서 가산세와 납부할 세액은 합계 열에만 적는다
      03 레코드 산출세액 안분(과세표준 비율, 원 미만 버림, 남는 원은 과세표준이 큰 행):
         1-10 행 179,646,000 × 415,800,000 ÷ 513,300,000 = 145,522,709.5 → 145,522,709, 1-15 행 34,123,290.4 → 34,123,290,
         합이 1원 모자라 1-10 행이 145,522,710
      지방: 세율별 3,900,000(97,500,000 × 4%) + 14,038,000(9,406,000 + 115,800,000 × 4%) = 17,938,000
            합산 비교세액 17,406,000 + 13,300,000 × 4.2% = 17,964,600. 이쪽이 커서 지방소득세는 17,964,600
            무신고 17,938,000 × 20% = 3,587,600
            S 건: 국세 기한 말일 2026-12-31 + 2개월 = 2027-02-28(일), 다음 날 3·1절 → 2027-03-02. 일수 03-03 ~ 05-20 = 29 + 30 + 20 = 79
                  납부지연 3,900,000 × 79 × 22/100,000 = 67,782
            F 건: 2027-01-31 + 2개월 = 2027-03-31(수). 일수 04-01 ~ 05-20 = 50. 납부지연 14,038,000 × 50 × 22/100,000 = 154,418
            가산세 계 3,587,600 + 222,200 = 3,809,800, ⑮ 납부할 총세액 17,964,600 + 3,809,800 = 21,774,400"""
    facts = sgf_facts()
    lots = {"S": _land_lot(filers.SELLER), "G": filers.lot("77"), "F": _land_lot()}
    buyers = [filers.buyer("S", "정합성", "56789"), filers.buyer("G"), filers.buyer("F", "박합성", "45678")]
    f = filers.filer("확정", "2027-05-20", lots, buyers)
    r = _calc(facts)
    assert [(x["id"], x["판정"]["전액비과세"]) for x in r["계산"]["자산"]] == [("S", False), ("G", True), ("F", False)]
    total = r["계산"]["합계"]
    assert (total["호별합산세액"], total["합산비교세액"], total["산출세액"]) == (179_380_000, 179_646_000, 179_646_000)
    code, out = _main(tmp_path, facts, f)
    assert code == 0, _read(out, "신고_확인.md")
    rv = json.loads(_read(out, "신고값.json"))
    # 부표1 순서와 일련번호: 넣은 자산만으로 1 부터 이어진다
    assert [x["자산"] for x in rv["부표1"]] == ["S", "F"] and rv["제외자산"] == [{"자산": "G", "사유": "전액 비과세"}]
    assert [(x["자산"], x["일련번호"], x["세율구분"]) for x in rv["전자신고"]["계산명세"]] == [("S", 1, "15"), ("F", 2, "10")]
    assert [(b["자산"], b["일련번호"]) for b in rv["양수인"]] == [("S", 1), ("F", 2)]
    assert [s["자산"] for s in rv["부표3"]] == ["S"] and {x["일련번호"] for x in rv["전자신고"]["필요경비명세"]} == {1}
    # 세율구분 열 둘, 합산 비교세액이 커서 열과 소계의 가산세·납부할 세액은 비운다
    cols = rv["본지"]["열"]
    assert sorted(x["표기"] for x in rv["본지"]["세율구분"]) == ["1-10", "1-15"]
    assert (cols["1-15"]["과세표준"], cols["1-15"]["산출세액"], cols["1-15"]["기본공제"]) == (97_500_000, 39_000_000, 2_500_000)
    assert (cols["1-10"]["과세표준"], cols["1-10"]["산출세액"], cols["1-10"]["기본공제"]) == (415_800_000, 140_380_000, 0)
    t = cols["합계"]
    assert (t["과세표준"], t["산출세액"]) == (513_300_000, 179_646_000)
    assert (t["가산세_신고"], t["가산세_납부"], t["가산세"], t["납부할세액"]) == (35_876_000, 4_497_160, 40_373_160, 220_019_160)
    for name in ("국내소계", "1-10", "1-15"):
        assert cols[name]["가산세"] is None and cols[name]["납부할세액"] is None, name
    assert [(c["자산"], c["예정신고세액"], c["납부기한"], c["일수"], c["무신고"], c["납부지연"]) for c in rv["가산세"]["건"]] == [
        (["S"], 39_000_000, "2026-12-31", 139, 7_800_000, 1_192_620), (["F"], 140_380_000, "2027-02-01", 107, 28_076_000, 3_304_540)]
    loc = rv["지방"]["열"]["합계"]
    assert (loc["산출세액"], loc["가산세_신고"], loc["가산세_납부"], loc["가산세"], loc["납부할세액"]) == \
        (17_964_600, 3_587_600, 222_200, 3_809_800, 21_774_400)
    assert forms_check.check(rv, r, facts=facts) == []
    # 전자신고 파일: 04 양수인 둘, 05 계산명세 둘이 000001, 000002 로 이어지고 03 은 소계·두 세율구분 행·합계다
    by = _records(out, "20270520C116300.01")
    assert {k: len(v) for k, v in by.items()} == {"01": 1, "02": 1, "03": 4, "04": 2, "05": 2, "07": 1}
    assert [ln[9:15] for ln in by["05"]] == [b"000001", b"000002"] and [ln[9:15] for ln in by["04"]] == [b"000001", b"000002"]
    assert by["07"][0][9:15] == b"000001"
    rows03 = {ln[9:12]: ln for ln in by["03"]}
    assert sorted(rows03) == [b"100", b"110", b"115", b"Z00"]
    tax = {k: int(ln[69:82]) for k, ln in rows03.items()}
    assert tax == {b"100": 179_646_000, b"110": 145_522_710, b"115": 34_123_290, b"Z00": 179_646_000}
    z = rows03[b"Z00"]
    assert [int(z[a:b]) for a, b in ((134, 147), (147, 160), (160, 173), (186, 199))] == [35_876_000, 4_497_160, 40_373_160, 220_019_160]
    pdf = _pdf_text(out, "양도소득세_신고서.pdf")
    assert "2026.11.30" not in pdf and "2026.10.20" in pdf and "2026.11.01" in pdf        # G 의 양도일은 신고서에 없다
    assert "220,019,160" in pdf and "21,774,400" in _pdf_text(out, "지방소득세_신고서.pdf")


def test_exempt_asset_row_is_never_built(tmp_path):
    """신고값 생성은 전액 비과세 자산의 행을 만들지 않는다. 빠뜨리지 않고 행을 만들려 하면 멈춘다(빈 값으로 채운 행이 나가지 않게)."""
    facts = gf_facts()
    r = _calc(facts)
    b = return_values._Builder(r, facts, filing.load(mixed_filer()), None, None, None)
    b.filing_section()
    exempt = next(x for x in r["계산"]["자산"] if x["판정"]["전액비과세"])
    with pytest.raises(ValueError, match="전액 비과세 자산 G"):
        b.asset(1, exempt)
    # 질문 F07·F08 은 모든 자산을 훑으므로 지출 줄을 고르는 규칙은 전액 비과세 자산에 빈 목록을 준다
    assert return_values.expense_lines(facts["자산"][0], exempt["계산"]) == []


# ---------------------------------------------------------------- 서식 검산: 뺀 자산은 엔진 판정으로 가린다

def test_forms_check_catches_an_exempt_asset_in_the_return():
    facts = gf_facts()
    r, rv = _build(facts, mixed_filer())

    def fails(bad):
        return forms_check.check(bad, r, facts=facts)

    bad = copy.deepcopy(rv)                                         # 부표1 에 G 를 넣었다
    bad["부표1"].insert(0, dict(copy.deepcopy(rv["부표1"][0]), 자산="G", 양도소득금액=0, 과세양도차익=0, 장특공=0))
    assert any("G" in m and "전액 비과세" in m and "부표1" in m for m in fails(bad))
    bad = copy.deepcopy(rv)                                         # 양수인에 G 의 양수인이 있다
    bad["양수인"].append(dict(copy.deepcopy(rv["양수인"][0]), 자산="G", 일련번호=2))
    assert any("양수인" in m and "G" in m for m in fails(bad))
    bad = copy.deepcopy(rv)                                         # 계산명세(05)에 G 행이 있다
    bad["전자신고"]["계산명세"].append(dict(copy.deepcopy(rv["전자신고"]["계산명세"][0]), 자산="G", 일련번호=2))
    assert any("계산명세" in m and "G" in m for m in fails(bad))
    bad = copy.deepcopy(rv)                                         # 뺀 자산을 적지 않았다
    bad["제외자산"] = []
    assert any("제외자산" in m and "G" in m for m in fails(bad))
    bad = copy.deepcopy(rv)                                         # 과세 자산을 뺐다고 적었다
    bad["제외자산"] = [{"자산": "G", "사유": "전액 비과세"}, {"자산": "F", "사유": "전액 비과세"}]
    assert any("제외자산" in m for m in fails(bad))
    bad = copy.deepcopy(rv)                                         # 과세 자산 F 를 부표1 에서 뺐다
    bad["부표1"] = []
    assert any("부표1 자산" in m and "엔진" in m for m in fails(bad))


def test_forms_check_rejects_a_return_without_a_taxable_asset():
    """과세 자산이 없는 결과로는 어떤 신고값도 통과하지 못한다."""
    r, rv = _build(gf_facts(), mixed_filer())
    only = _calc(CASES["G"])
    msgs = forms_check.check(rv, only, facts=CASES["G"])
    assert any("과세 자산이 없" in m for m in msgs), msgs


def test_expenses_of_a_missing_asset_are_caught():
    facts = gt_facts()
    r, rv = _build(facts, mixed_filer("T", seller=filers.SELLER))
    bad = copy.deepcopy(rv)
    bad["전자신고"]["필요경비명세"][0]["자산"] = "G"
    assert any("필요경비명세" in m and "G" in m for m in forms_check.check(bad, r, facts=facts))


# ---------------------------------------------------------------- 가산세: 전액 비과세 자산은 건에 들지 않는다

def test_penalty_cases_do_not_include_the_exempt_asset():
    facts = gf_facts()
    out = penalty.final_return(_calc(facts), facts, "2027-05-20")
    assert [(c["자산"], c["예정신고세액"], c["납부기한"], c["일수"], c["무신고"], c["납부지연"]) for c in out["건"]] == [
        (["F"], 139_380_000, "2027-02-01", 107, 27_876_000, 3_281_000)]
    assert (out["무신고"], out["납부지연"], out["계"]) == (27_876_000, 3_281_000, 31_157_000)
    assert out["양도일별"] is None                                   # 같은 달에 양도했어도 G 는 건이 아니라 대안 금액이 없다
    assert not any("같은 달" in m for m in out["확인사항"])
    loc = out["지방"]
    assert [(c["자산"], c["예정신고세액"], c["일수"]) for c in loc["건"]] == [(["F"], 13_938_000, 50)]
    assert (loc["무신고"], loc["납부지연"], loc["계"]) == (2_787_600, 153_318, 2_940_918)


# ---------------------------------------------------------------- 진입점: 섞인 신고

def test_mixed_preliminary_return_runs_to_the_end_without_the_exempt_asset(tmp_path, capsys):
    f = mixed_filer()
    code, out = _main(tmp_path, gf_facts(), f)
    shown = capsys.readouterr()
    text = _read(out, "신고_확인.md")
    assert code == 0, shown.out + shown.err + text
    name = "20261220C116300.01"
    assert CALC | GUIDES | PDFS | {name, "신고값.json", "신고_확인.md"} <= set(os.listdir(out))
    # 전자신고 파일: 05 는 F 한 건, 04 는 F 의 양수인 한 건, 07 은 없다
    by = _records(out, name)
    assert {k: len(v) for k, v in by.items()} == {"01": 1, "02": 1, "03": 3, "04": 1, "05": 1}
    assert by["05"][0][9:15] == b"000001" and by["05"][0][15:17] == b"ZZ"      # 일련번호 1, 과세구분 해당없음
    g_buyer, f_buyer = filers.buyer("G")["번호"].encode("ascii"), filers.buyer("F", "박합성", "45678")["번호"].encode("ascii")
    assert f_buyer in by["04"][0] and not any(g_buyer in ln for lines in by.values() for ln in lines)
    # 신고서 PDF: 부표1 과 양수인 란에 G 가 없다(G 양도일 2026-11-30, 취득일 2019-03-01, 양수인 이합성)
    pdf = _pdf_text(out, "양도소득세_신고서.pdf")
    assert "2026.11.01" in pdf and "2005.01.01" in pdf and "박합성" in pdf
    assert "2026.11.30" not in pdf and "2019.03.01" not in pdf and "이합성" not in pdf
    # 확인 문서: 알림과 확인사항에 한 줄, 사람이 할 일에 증빙 보관
    alerts = text.split("## 알림", 1)[1].split("##")[0]
    notes = text.split("## 확인사항", 1)[1].split("##")[0]
    for part in (alerts, notes):
        hit = [ln for ln in part.splitlines() if LEFT_OUT in ln]
        assert len(hit) == 1 and "과세관청이 달리 보면" in hit[0] and "신고하지 않은 것이 된다" in hit[0] and "세무 전문가" in hit[0]
    todo = text.split("## 사람이 할 일", 1)[1]
    keep = [ln for ln in todo.splitlines() if "넣지 않은 자산(G)" in ln]
    assert len(keep) == 1 and "비과세 요건" in keep[0] and "증빙" in keep[0] and "부속서류.md" in keep[0]
    assert "| 신고서 PDF | 만듦 |" in text and "만들지 않았다" not in text.splitlines()[2]
    assert "산출세액 139,380,000원, 지방소득세 13,938,000원" in text
    assert DASH not in text and not [ln for ln in text.splitlines() if ln.rstrip().endswith("?")]
    for v in [f["신고인"]["성명"], f["신고인"]["주민등록번호"]] + [b["번호"] for b in f["양수인"]]:
        assert v not in text and v not in shown.out


def test_mixed_return_guides_say_the_exempt_asset_was_left_out(tmp_path):
    code, out = _main(tmp_path, gf_facts(), mixed_filer())
    assert code == 0
    md = _read(out, "홈택스_입력안내.md")
    assert "### 자산 F" in md and "### 자산 G" not in md
    assert "양도 자산 1건" in md.split("## 신고 요약", 1)[1].split("##", 1)[0]
    left = md.split("## 신고서에 넣지 않은 자산", 1)[1].split("\n## ", 1)[0]
    assert "G" in left and "전액 비과세" in left and "화면에 입력하지 않는다" in left
    assert LEFT_OUT in md.split("## 확인사항", 1)[1]
    assert "전액 비과세 자산이라 취득가액을 입력하지 않는다" not in md and "과세되는 자산이 없다" not in md
    att = _read(out, "부속서류.md")
    heads = [ln for ln in att.splitlines() if ln.startswith("## ")]
    assert "## 자산 F" in heads and "## 자산 G" not in heads          # 올릴 서류 목록에 G 가 없다
    left = att.split("## 신고서에 넣지 않은 자산", 1)[1]
    assert "넣지 않은 자산 G" in left and "신고서에 넣지 않았다" in left and "비과세 요건" in left and "보관" in left
    assert "신규 주택" in left                                       # G 는 일시적 2주택이라 신규 주택 취득 계약서를 챙긴다
    assert "- [ ] 양도 매매계약서 사본" in left
    for doc in (md, att):
        assert DASH not in doc and not [ln for ln in doc.splitlines() if ln.rstrip().endswith("?")]
        assert filers.buyer("G")["번호"] not in doc


def test_mixed_final_return_with_penalty(tmp_path):
    f = mixed_filer(구분="확정", 작성일="2027-05-20")
    code, out = _main(tmp_path, gf_facts(), f)
    text = _read(out, "신고_확인.md")
    assert code == 0, text
    name = "20270520C116300.01"
    by = _records(out, name)
    assert {k: len(v) for k, v in by.items()} == {"01": 1, "02": 1, "03": 3, "04": 1, "05": 1}
    rv = json.loads(_read(out, "신고값.json"))
    assert [x["자산"] for x in rv["부표1"]] == ["F"] and rv["제외자산"] == [{"자산": "G", "사유": "전액 비과세"}]
    t, loc = rv["본지"]["열"]["합계"], rv["지방"]["열"]["합계"]
    assert (t["가산세_신고"], t["가산세_납부"], t["가산세"], t["납부할세액"]) == (27_876_000, 3_281_000, 31_157_000, 170_537_000)
    assert (loc["가산세_신고"], loc["가산세_납부"], loc["가산세"], loc["납부할세액"]) == (2_787_600, 153_318, 2_940_918, 16_878_918)
    assert [c["자산"] for c in rv["가산세"]["건"]] == [["F"]]
    # 03 합계 행: 15 신고불성실, 16 납부불성실, 17 계, 19 자진납부할세액
    z = [ln for ln in by["03"] if ln[9:12] == b"Z00"][0]
    assert [int(z[a:b]) for a, b in ((134, 147), (147, 160), (160, 173), (186, 199))] == [27_876_000, 3_281_000, 31_157_000, 170_537_000]
    alerts = text.split("## 알림", 1)[1].split("##")[0]
    assert LEFT_OUT in alerts and "감면 없이" in alerts
    pdf = _pdf_text(out, "양도소득세_신고서.pdf")
    assert "2026.11.30" not in pdf and "이합성" not in pdf and "2026.11.01" in pdf


def test_mixed_return_with_schedule3_and_expense_records(tmp_path):
    code, out = _main(tmp_path, gt_facts(), mixed_filer("T", seller=filers.SELLER))
    assert code == 0, _read(out, "신고_확인.md")
    by = _records(out, "20261220C116300.01")
    assert {k: len(v) for k, v in by.items()} == {"01": 1, "02": 1, "03": 3, "04": 1, "05": 1, "07": 2}
    assert by["05"][0][9:15] == b"000001"


def test_mixed_return_does_not_ask_for_the_exempt_assets_lot_or_buyer(tmp_path):
    code, out = _main(tmp_path, gf_facts(), mixed_filer(with_exempt=False))
    text = _read(out, "신고_확인.md")
    assert code == 0, text
    assert "신고인 정보 질문" not in text and LEFT_OUT in text


def test_mcp_mixed_return_reports_the_left_out_asset(tmp_path):
    f = mixed_filer()
    gp = tmp_path / "g.json"
    gp.write_text(json.dumps(f, ensure_ascii=False), encoding="utf-8")
    res = mcp_server.call_tool("yangdo_efile", {"facts": gf_facts(), "filer_path": str(gp), "out_dir": str(tmp_path / "o"),
                                                "today": TODAY})
    assert res["종료코드"] == 0 and res["상태"] == "완료" and res["다루지않음"] == []
    assert any(LEFT_OUT in x for x in res["알림"]) and any(LEFT_OUT in x for x in res["확인사항"])
    assert any("넣지 않은 자산(G)" in x for x in res["사람이할일"])
    s = json.dumps(res, ensure_ascii=False)
    for b in f["양수인"]:
        assert b["번호"] not in s and b["성명"] not in s


# ---------------------------------------------------------------- 진입점: 전액 비과세 자산뿐인 건

@pytest.mark.parametrize("kind,made", [("예정", "2026-12-20"), ("확정", "2027-05-20")])
def test_only_exempt_assets_stops_with_code_2(tmp_path, capsys, kind, made):
    f = g_only_filer(kind, made)
    code, out = _main(tmp_path, CASES["G"], f)
    shown = capsys.readouterr()
    assert code == 2, shown.out + shown.err
    names = set(os.listdir(out))
    assert CALC | {"신고_확인.md"} <= names
    assert not (PDFS | GUIDES | {"신고값.json"}) & names and not [n for n in names if "C116300" in n]
    text = _read(out, "신고_확인.md")
    assert NO_TAXABLE in text.splitlines()[2] and "(종료코드 2)" in text.splitlines()[2]
    assert NO_TAXABLE in shown.out
    alerts = text.split("## 알림", 1)[1].split("##")[0]
    assert "전액 비과세로 판정한 자산(G)뿐" in alerts and "세무 전문가" in alerts and "가산세" not in alerts
    assert "만들지 않음(과세 자산 없음)" in text
    todo = text.split("## 사람이 할 일", 1)[1]
    assert "비과세 요건" in todo and "증빙" in todo and "세무 전문가" in todo
    for word in ("형식검증", "내용검증", "로그인", "제출", "위택스", "참고용"):
        assert word not in todo, word
    prose = "\n".join(ln for ln in text.splitlines() if not ln.startswith("|"))
    assert "다루지않음" not in prose
    assert DASH not in text and not [ln for ln in text.splitlines() if ln.rstrip().endswith("?")]
    for v in (f["신고인"]["성명"], f["신고인"]["주민등록번호"], f["양수인"][0]["번호"]):
        assert v not in text and v not in shown.out


def test_only_exempt_assets_stops_before_reading_the_filer_file(tmp_path):
    """과세 자산이 없으면 신고인 파일의 빠진 값을 묻기 전에 끝낸다(신고서를 만들지 않으니 신고인 정보가 필요 없다)."""
    f = g_only_filer()
    f["양수인"] = []
    del f["자산"]["G"]
    code, out = _main(tmp_path, CASES["G"], f)
    text = _read(out, "신고_확인.md")
    assert code == 2 and NO_TAXABLE in text and "신고인 정보 질문" not in text


def test_mcp_only_exempt_assets(tmp_path):
    gp = tmp_path / "g.json"
    gp.write_text(json.dumps(g_only_filer(), ensure_ascii=False), encoding="utf-8")
    res = mcp_server.call_tool("yangdo_efile", {"facts": CASES["G"], "filer_path": str(gp), "out_dir": str(tmp_path / "o"),
                                                "today": TODAY})
    assert res["종료코드"] == 2 and res["상태"] == "다루지않음" and NO_TAXABLE in res["요약"]
    assert res["서식검산"] is None and res["전자신고"] is None
    assert any(x["내용"].startswith("전액 비과세 자산뿐인 건") for x in res["다루지않음"])
    assert "다루지않음" not in " ".join(res["알림"] + res["사람이할일"] + [res["요약"]])


def test_withheld_has_no_exempt_asset_reason():
    """전액 비과세 자산은 신고서를 막는 사유가 아니다. 사유는 가산세를 계산하지 못한 확정신고 하나다."""
    res = {"계산": {"자산": [{"id": "F", "판정": {"전액비과세": False}}, {"id": "G", "판정": {"전액비과세": True}}]}}
    assert MR.withheld({"신고": {"구분": "예정"}, "가산세": None}, res) == []
    failed = {"계산": False, "사유": "자산 B, F: 정하지 않았다", "계획": "없음"}
    assert [w["이름"] for w in MR.withheld({"신고": {"구분": "확정"}, "가산세": failed}, res)] == ["확정신고 가산세"]


def test_guide_functions_take_values_without_exempt_assets():
    """안내서와 부속서류 목록은 신고값의 제외자산 절을 읽어 넣지 않은 자산을 적는다. 과세 자산만 있는 신고값에는 그 절이 없다."""
    facts = gf_facts()
    r, rv = _build(facts, mixed_filer())
    assert "## 신고서에 넣지 않은 자산" in guide.hometax_input(rv)
    assert "## 신고서에 넣지 않은 자산" in guide.attachments(rv, facts, r)
    r1 = _calc(CASES["S1"])
    f1 = filers.get("S1")
    f1["자산"]["S1"]["법정동코드"] = "1120011400"
    rv1 = return_values.build(r1, CASES["S1"], filing.load(f1))
    assert rv1["제외자산"] == []
    assert "넣지 않은 자산" not in guide.hometax_input(rv1) and "넣지 않은 자산" not in guide.attachments(rv1, CASES["S1"], r1)
