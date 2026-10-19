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
from yangdo import edition, engine, filing, forms_check, penalty, return_values


TODAY = "2026-10-11"
DASH = chr(0x2014)
PDFS = {"양도소득세_신고서.pdf", "지방소득세_신고서.pdf"}
GUIDES = {"홈택스_입력안내.md", "부속서류.md"}
CALC = {"result.json", "양도소득세_검토.md", "양도소득세_계산근거.xlsx"}
# 넣지 않은 자산을 알리는 문장의 첫 문장(공개본은 「신고서에 넣지 않았다」)
LEFT_OUT = return_values.left_out_note(["G"]).split(". ")[0]
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


def test_forms_check_rejects_a_return_without_a_taxable_asset():
    """과세 자산이 없는 결과로는 어떤 신고값도 통과하지 못한다."""
    r, rv = _build(gf_facts(), mixed_filer())
    only = _calc(CASES["G"])
    msgs = forms_check.check(rv, only, facts=CASES["G"])
    assert any("과세 자산이 없" in m for m in msgs), msgs


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


# ---------------------------------------------------------------- 진입점: 전액 비과세 자산뿐인 건


def test_withheld_has_no_exempt_asset_reason():
    """전액 비과세 자산은 신고서를 막는 사유가 아니다. 사유는 가산세를 계산하지 못한 확정신고 하나다."""
    res = {"계산": {"자산": [{"id": "F", "판정": {"전액비과세": False}}, {"id": "G", "판정": {"전액비과세": True}}]}}
    assert MR.withheld({"신고": {"구분": "예정"}, "가산세": None}, res) == []
    failed = {"계산": False, "사유": "자산 B, F: 정하지 않았다", "계획": "없음"}
    assert [w["이름"] for w in MR.withheld({"신고": {"구분": "확정"}, "가산세": failed}, res)] == ["확정신고 가산세"]


