"""AR 5차(10-20) 시험: 메모 이어받기의 허용 금액, 새 규칙 열한 개. 합성 장부 · 전표 · 전기 신고서 글만 쓴다(고객 자료 없음).

  memo     `--memo` 검사가 받아 준 조정.json 금액 메모가 다음 `ctax ar` 에서 버려지지 않는다
  a        전기 15호 유보 가산 · 차감 짝(prior_pair:<과목>)
  b        전기 22호 그 밖의 기부금 적요가 당기에 다시(prior_donation_other)
  c        전기에 손금불산입한 불공제 매입세액(nondeductible_vat 확실)
  d        수선비 600만원 이상 · 공사 · 모델명(repair_capital)
  e        지급수수료 소송 · 변호사(legal_fees)
  f        영업외 손익 계정의 전기오류 수정(prior_period_pl)
  h        임원급여 평월 두 배(officer_bonus)
  i        당기 취득 자산 상각비 0(dep_missing)
  j        공사매출 · 미완성공사 없음(construction_progress)
  중간예납  직전 산출세액이 있는데 중간예납 전표가 없음(interim_missing)
"""
from __future__ import annotations

import json

from ctax.ar import cli, engine, memo
from ctax.tests.test_ar import acc, ledger, prior, run, write_case
from ctax.tests.test_ar_fx1 import row, rules, with_accounts
from ctax.tests.test_ar_memo import good_memo, read_ar


def guide(ar, gid):
    return next(g for g in ar["guide"] if g["id"] == gid)


# ---------------------------------------------------------------- 메모 이어받기

def test_carry_keeps_memo_with_workpaper_amount():
    ar = run()
    m = good_memo(ar)
    m["items"][0]["why"] = "조서가 계산한 한도초과 1,234,567원을 손금불산입합니다."
    assert memo.validate(m, ar, {1_234_567}) == []
    memo.apply(m, ar)
    new = run()
    assert any("금액이 바뀌어" in n for n in memo.carry(new, ar, None))           # 허용 금액 없이는 버린다(전과 같음)
    new = run()
    notes = memo.carry(new, ar, None, allowed={1_234_567})
    assert not any("금액이 바뀌어" in n for n in notes)
    assert new["issues"][0]["memo"]["why"].startswith("조서가 계산한")


def test_dropped_memo_message_fits_wrapping_skill():
    assert "ctax ar --memo" not in memo.MEMO_DROPPED
    assert "메모 명령으로 넣으십시오" in memo.MEMO_DROPPED.format(no=3)


def test_cli_rerun_keeps_memo_using_adjust_json(case_dir):
    write_case(case_dir)
    assert cli.main([str(case_dir)]) == 0
    (case_dir / "_색인" / "조정.json").write_text(json.dumps({"papers": [], "adjustments": [
        {"paper": "entertainment", "amount": 7_654_321}]}, ensure_ascii=False), encoding="utf-8")
    m = good_memo(read_ar(case_dir))
    m["items"][0]["why"] = "조서 한도초과 7,654,321원을 손금불산입합니다."
    path = case_dir.parent / "메모.json"
    path.write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")
    assert cli.main([str(case_dir), "--memo", str(path)]) == 0
    assert cli.main([str(case_dir)]) == 0
    assert read_ar(case_dir)["issues"][0]["memo"]["why"].startswith("조서 한도초과 7,654,321원")


# ---------------------------------------------------------------- a. 전기 유보 가산 · 차감 짝

PAIR_ADJ = [
    {"side": "가산", "subject": "세금과공과(가상부담금)", "amount": 5_000_000, "disposition": "유보", "code": "400",
     "note": "당기가상부담금 미지급 계상분 손금불산입"},
    {"side": "차감", "subject": "세금과공과(가상부담금)", "amount": 4_000_000, "disposition": "유보", "code": "100",
     "note": "전기가상부담금 지급분 손금산입"},
]


def _pair_rows(memo_text="당기 가상부담금"):
    return [row("2025-03-10", "1", "262", "미지급비용", 5_000_000, 0, "가상부담금 1회"),
            row("2025-03-10", "1", "103", "보통예금", 0, 5_000_000, "가상부담금 1회"),
            row("2025-12-31", "2", "817", "세금과공과금(판)", 6_000_000, 0, memo_text),
            row("2025-12-31", "2", "262", "미지급비용", 0, 6_000_000, memo_text)]


def test_prior_pair_continues():
    pr = prior(adjustments=prior()["adjustments"] + PAIR_ADJ,
               reserves=[{"subject": "세금과공과", "opening": 4_000_000, "decrease": 4_000_000, "increase": 5_000_000,
                          "closing": 5_000_000}])
    led = with_accounts(acc("262", "미지급비용", "부채", 6_000_000, 5_000_000))
    ar = run(led, _pair_rows(), pr)
    iss = rules(ar)["prior_pair:세금과공과(가상부담금)"]
    assert iss["kind"] == "전기 연속" and iss["certainty"] == "가능" and iss["guide"] == ["1-3"]
    assert iss["amounts"] == {"prior": 5_000_000, "current": 6_000_000, "change": 1_000_000}
    assert iss["accounts"] == ["817"]
    assert any("미지급비용 차변 5,000,000원" in b for b in iss["basis"])
    assert any("전기분 지급 · 추인 대상" in b for b in iss["basis"])
    assert any(b.startswith("전기 50호(을) 세금과공과 기말 유보") for b in iss["basis"])      # 50호(을) 줄도 이 이슈에
    assert iss["law"][0]["ref"].startswith("법인세법 제40조 제1항")
    assert "reserve_50" in iss["papers"] and "50을" in iss["forms"]
    pen = rules(ar).get("penalty")
    assert pen is None or not any("가상부담금" in b for b in pen["basis"])                   # 세금과공과 이슈에 섞지 않는다
    fates = guide(ar, "1-3")["facts"]
    assert any("짝 조정 반복 예상" in f for f in fates)


def test_prior_pair_needs_same_memo_and_skips_paper_subjects():
    pr = prior(adjustments=prior()["adjustments"] + PAIR_ADJ)
    assert not [k for k in rules(run(jr=_pair_rows("다른 공과금"), pr=pr)) if k.startswith("prior_pair:")]
    accrued = [{**a, "subject": "미지급비용(급여)"} for a in PAIR_ADJ]          # 미지급비용은 조서가 짝을 계산한다
    rows = [row("2025-12-31", "2", "802", "직원급여(판)", 6_000_000, 0, "미지급비용(급여) 연차")]
    assert not [k for k in rules(run(jr=rows, pr=prior(adjustments=accrued))) if k.startswith("prior_pair:")]


# ---------------------------------------------------------------- b. 전기 22호 그 밖의 기부금

ROWS_22 = [{"유형": "일반", "코드": "40", "과목": "기부금", "월": "2024.03", "적요": "가상복지관 운영지원금", "기부처": "", "금액": 3_000_000},
           {"유형": "기타", "코드": "50", "과목": "기부금", "월": "2024.07", "적요": "7월가상방역지원금(", "기부처": "", "금액": 2_000_000},
           {"유형": "기타", "코드": "50", "과목": "기부금", "월": "2024.12", "적요": "가상마을발전기금", "기부처": "가상마을", "금액": 5_000_000}]


def _donation_rows():
    return [row("2025-03-10", "1", "933", "기부금", 3_000_000, 0, "가상복지관 운영지원금"),
            row("2025-08-10", "2", "933", "기부금", 1_000_000, 0, "8월가상방역지원금(가상상사)"),
            row("2025-12-10", "3", "933", "기부금", 5_000_000, 0, "가상마을발전기금")]


def test_prior_other_donation_reappears():
    pr = prior(rows={"22": ROWS_22})
    led = with_accounts(acc("933", "기부금", "비용", 9_000_000, 10_000_000, lines=3), drop=("933",))
    iss = rules(run(led, _donation_rows(), pr))["prior_donation_other"]
    assert iss["kind"] == "전기 연속" and iss["certainty"] == "확실"
    assert iss["amounts"] == {"prior": 7_000_000, "current": 6_000_000, "change": -1_000_000}
    assert "2-3-22-1" in iss["guide"] and iss["papers"] == ["donation"]
    assert any("같은 적요 표기 2줄 6,000,000원" in b for b in iss["basis"])
    assert any(x["ref"].startswith("법인세법 제24조 제4항") for x in iss["law"])


def test_prior_other_donation_quiet_without_match():
    pr = prior(rows={"22": ROWS_22[:1]})
    assert "prior_donation_other" not in rules(run(jr=_donation_rows(), pr=pr))


# ---------------------------------------------------------------- c. 불공제 매입세액

def _vat_rows():
    return [row("2025-03-31", "1", "817", "세금과공과금(판)", 1_500_000, 0, "불공제매입세액대체"),
            row("2025-03-31", "1", "135", "부가세대급금", 0, 1_500_000, "불공제매입세액대체")]


def test_prior_nondeductible_vat_makes_issue_sure():
    taxes = [{"과목": "세금과공과(제)", "일자": "03/31", "적요": "불공제매입세액대체", "금액": 2_000_000, "비고": "손금불산입"},
             {"과목": "세금과공과(제)", "일자": "12/31", "적요": "당기가상부담금", "금액": 9_000_000, "비고": "손금불산입취소"}]
    adj = {"side": "가산", "subject": "세금과공과", "amount": 2_000_000, "disposition": "기타사외유출", "code": "500",
           "note": "세금과공과금중손금불산입항목"}
    pr = prior(rows={"세금공과금명세서": taxes}, adjustments=prior()["adjustments"] + [adj])
    iss = rules(run(jr=_vat_rows(), pr=pr))["nondeductible_vat"]
    assert iss["certainty"] == "확실" and iss["title"].startswith("전기에 손금불산입한 불공제 매입세액")
    assert iss["amounts"] == {"prior": 2_000_000, "current": 1_500_000, "change": -500_000}
    assert any("전기 세금공과금명세서 「불공제매입세액대체」 1줄 2,000,000원" in b for b in iss["basis"])
    assert any("전기 15호 세금과공과 2,000,000원" in b for b in iss["basis"])                 # 15호 줄도 이 이슈에
    assert iss["prior_treatment"]
    plain = rules(run(jr=_vat_rows()))["nondeductible_vat"]
    assert plain["certainty"] == "가능" and plain["amounts"] == {"current": 1_500_000}


# ---------------------------------------------------------------- d. 수선비

def test_repair_capital_words_and_model_and_reversal():
    rows = [row("2025-04-01", "1", "520", "수선비(제)", 9_000_000, 0, "소각로 내화물 보수공사 1", "가상공사"),
            row("2025-05-01", "2", "520", "수선비(제)", 7_000_000, 0, "가상냉동고 DF1234XY 외 1 X 7,000,000", "가상상사"),
            row("2025-06-01", "3", "520", "수선비(제)", 8_000_000, 0, "바닥 포장공사", "가상공사2"),
            row("2025-06-02", "4", "520", "수선비(제)", 0, 8_000_000, "바닥 포장공사", "가상공사2"),       # 취소
            row("2025-07-01", "5", "520", "수선비(제)", 12_000_000, 0, "정기 점검 수리", "가상정비"),     # 낱말 없음
            row("2025-08-01", "6", "520", "수선비(제)", 5_000_000, 0, "배관 교체공사", "가상설비")]       # 600만원 미만
    led = with_accounts(acc("520", "수선비(제)", "비용", 33_000_000, 0, lines=6))
    iss = rules(run(led, rows))["repair_capital"]
    assert iss["amounts"] == {"current": 16_000_000} and iss["accounts"] == ["520"]
    assert iss["papers"] == ["depreciation"] and iss["guide"] == ["2-3-5-1"]
    assert any("묶음 2개 16,000,000원" in b and "모델명" in b and "공사" in b for b in iss["basis"])
    assert any(x["ref"].startswith("법인세법 시행령 제31조 제2항") for x in iss["law"])


# ---------------------------------------------------------------- e. 소송 · 변호사 비용

def test_legal_fees_over_limit_only():
    rows = [row("2025-02-01", "1", "831", "지급수수료(판)", 6_000_000, 0, "변호사 착수금", "가상법무법인"),
            row("2025-09-01", "2", "831", "지급수수료(판)", 6_000_000, 0, "형사사건 성공보수", "가상법무법인"),
            row("2025-03-01", "3", "831", "지급수수료(판)", 450, 0, "전자소송인지"),
            row("2025-04-01", "4", "831", "지급수수료(판)", 900_000, 0, "법무사 등기 수수료", "가상법무사")]
    led = with_accounts(acc("831", "지급수수료(판)", "비용", 12_900_450, 0, lines=4))
    iss = rules(run(led, rows))["legal_fees"]
    assert iss["amounts"] == {"current": 12_000_000} and iss["kind"] == "조정 후보"
    assert any("상대 가상법무법인" in b for b in iss["basis"])
    assert iss["law"][0]["ref"].startswith("법인세법 제19조 제2항")
    assert "legal_fees" not in rules(run(led, rows[:1] + rows[2:]))
    other = [row("2025-01-31", f"{m}", "831", "지급수수료(판)", 3_000_000, 0, "전자상거래PG", "가상전자소송") for m in range(1, 6)]
    assert "legal_fees" not in rules(run(led, other))                            # 거래처 이름의 「소송」 만으로는 서지 않는다


# ---------------------------------------------------------------- f. 영업외 손익의 전기오류

def test_prior_period_in_misc_income():
    rows = [row("2025-01-01", "1", "146", "상품", 3_000_000, 0, "전기오류수정 상품 누락"),
            row("2025-01-01", "1", "930", "잡이익", 0, 3_000_000, "전기오류수정 상품 누락"),
            row("2025-05-01", "2", "930", "잡이익", 0, 50_000, "전기분 환급 잔액")]
    led = with_accounts(acc("930", "잡이익", "수익", 3_050_000, 0, lines=2), acc("146", "상품", "자산", 3_000_000, 0))
    iss = rules(run(led, rows))["prior_period_pl"]
    assert iss["amounts"] == {"current": 3_000_000} and iss["guide"] == ["2-3-18-1"]
    assert any("잡이익 대변 3,000,000원" in b and "상대 상품" in b for b in iss["basis"])
    assert "prior_period_pl" not in rules(run(led, rows[2:]))                    # 「전기분 환급」 만으로는 서지 않는다


# ---------------------------------------------------------------- h. 임원 상여

def _officer_rows(dec):
    out = [row(f"2025-{m:02d}-25", f"{m}", "801", "임원급여(판)", 4_000_000, 0, f"{m}월분 급여") for m in range(1, 12)]
    return out + [row("2025-12-26", "12", "801", "임원급여(판)", dec, 0, "12월분 급여 및 상여")]


def test_officer_bonus_month_over_double():
    led = with_accounts(acc("801", "임원급여(판)", "비용", 44_000_000 + 9_000_000, 40_000_000, lines=12))
    iss = rules(run(led, _officer_rows(9_000_000)))["officer_bonus"]
    assert iss["amounts"] == {"current": 5_000_000} and iss["guide"] == ["2-3-13-1"]
    assert any("12월 9,000,000원(평월의 2.2배)" in b for b in iss["basis"])
    assert iss["law"][0]["ref"].startswith("법인세법 시행령 제43조 제2항")
    assert "officer_bonus" not in rules(run(led, _officer_rows(7_500_000)))


# ---------------------------------------------------------------- i. 당기 취득 자산 상각 누락

def _asset(code, name, amount, opening=0, debit=None):
    a = acc(code, name, "자산", amount, opening, debit=debit if debit is not None else amount - opening)
    a.update({"opening": opening, "closing": amount, "section": "비유동자산", "subsection": "유형자산"})
    return a


def test_dep_missing_for_new_asset():
    rows = [row("2025-04-10", "1", "217", "건설용장비", 9_000_000, 0, "가상굴삭기 취득"),
            row("2025-04-10", "1", "103", "보통예금", 0, 9_000_000, "가상굴삭기 취득")]
    led = with_accounts(_asset("217", "건설용장비", 9_000_000), drop=("208", "209"))
    iss = rules(run(led, rows))["dep_missing"]
    assert iss["amounts"] == {"current": 9_000_000} and iss["accounts"] == ["217"]
    assert any("건설용장비 당기 취득 9,000,000원(첫 취득 2025-04-10, 사용 9개월)" in b for b in iss["basis"])
    dep = rows + [row("2025-12-31", "2", "818", "감가상각비(판)", 1_000_000, 0, "상각"),
                  row("2025-12-31", "2", "218", "감가상각누계액", 0, 1_000_000, "상각")]
    led2 = with_accounts(_asset("217", "건설용장비", 9_000_000), acc("218", "감가상각누계액", "자산", -1_000_000, 0),
                         drop=("208", "209"))
    for a in led2["accounts"]:
        if a["code"] == "218":
            a.update({"section": "비유동자산", "subsection": "유형자산"})
    assert "dep_missing" not in rules(run(led2, dep))


# ---------------------------------------------------------------- j. 공사매출 · 작업진행률

def test_construction_without_contract_asset():
    led = with_accounts(acc("407", "공사매출", "수익", 500_000_000, 300_000_000),
                        acc("170", "미완성공사", "자산", 0, 0, debit=200_000_000, credit=200_000_000, closing=0))
    iss = rules(run(led, []))["construction_progress"]
    assert iss["amounts"] == {"current": 500_000_000} and "170" in iss["accounts"]
    assert any("미완성공사 기말 0원" in b for b in iss["basis"])
    assert any(x["ref"].startswith("법인세법 시행령 제69조 제1항") for x in iss["law"])
    led_open = with_accounts(acc("407", "공사매출", "수익", 500_000_000, 300_000_000),
                             acc("170", "미완성공사", "자산", 30_000_000, 0))
    assert "construction_progress" not in rules(run(led_open, []))
    assert "construction_progress" not in rules(run())                          # 건설업이 아니고 공사매출도 없음
    pr = prior(company={"name": "가상회사", "sme": True, "kind_code": "30", "biz_type": "건설업"})
    assert "construction_progress" in rules(run(pr=pr))                          # 업태가 건설업이면 매출 계정 이름과 상관없이


# ---------------------------------------------------------------- 중간예납

def _interim_prior(**cells):
    pr = prior()
    pr["cells"]["3"] = {**pr["cells"]["3"], **cells}
    return pr


def test_interim_missing_when_prior_tax():
    ar = run(pr=_interim_prior(**{"12": 20_000_000, "17": 2_000_000, "24": 1_000_000}))
    iss = rules(ar)["interim_missing"]
    assert iss["kind"] == "신고 점검" and iss["amounts"] == {"prior": 8_500_000}
    assert any("중간예납세액(추정) 8,500,000원" in b for b in iss["basis"])
    assert iss["law"][0]["ref"].startswith("법인세법 제63조 제1항")


def test_interim_paid_or_small_sme_is_quiet():
    paid = [row("2025-08-29", "1", "136", "선납세금", 8_500_000, 0, "법인세 중간예납"),
            row("2025-08-29", "1", "103", "보통예금", 0, 8_500_000, "법인세 중간예납")]
    led = with_accounts(acc("136", "선납세금", "자산", 0, 0, debit=8_500_000, credit=8_500_000, closing=0))
    assert "interim_missing" not in rules(run(led, paid, _interim_prior(**{"12": 20_000_000})))
    assert "interim_missing" not in rules(run(pr=_interim_prior(**{"12": 900_000})))       # 중소기업 45만원 < 50만원
    assert "interim_missing" not in rules(run())                                          # 전기 산출세액 없음


# ---------------------------------------------------------------- 공통

def test_new_rules_validate_and_have_laws():
    pr = prior(adjustments=prior()["adjustments"] + PAIR_ADJ, rows={"22": ROWS_22})
    ar = run(jr=_pair_rows() + _donation_rows() + _vat_rows(), pr=pr)
    assert engine.validate(ar) == []
    for i in ar["issues"]:
        assert i["law"] and all(x["grade"] for x in i["law"])
