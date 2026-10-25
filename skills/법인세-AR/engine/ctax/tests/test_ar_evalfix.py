"""corporate-tax-ar v1.0 평가세트 실행이 드러낸 엔진 다섯 가지(2026-10-18) 시험. 합성 장부 · 전표 · 전기 신고서 글만 쓴다.

1. 수익에 든 환급을 법인세 · 지방소득세와 부가세로 나눈다
2. 전기 29호 업무외사용금액이 전기 15호에 없으면 신고 점검
3. 가이드 2-2 를 「해당 없음」 으로 두지 않는다(전기 51호 소기업 기준을 넘으면 이슈)
4. 결산 손실만으로 「감면할 세액이 없다」 고 단정하지 않는다
5. 외환차손익 계정의 기말 환산 줄을 외화환산 이슈 · 조서에 잡는다
"""
from __future__ import annotations

from ctax.prior.form29 import scale_51, total_row
from ctax.tests.test_ar import acc, ledger, prior, run
from ctax.tests.test_ar_fx1 import row, rules, with_accounts


def guide(ar, gid):
    return next(g for g in ar["guide"] if g["id"] == gid)


# ---------------------------------------------------------------- 1. 환급 줄 나누기

def test_refund_lines_split_corporate_and_vat():
    rows = [row("2025-01-10", "1", "930", "잡이익", 0, 1_000_000, "법인세등_법인세등_가상세무서_경정청구환급(24년법인세경정청구)"),
            row("2025-01-10", "1", "930", "잡이익", 0, 100_000, "법인지방소득세 환급"),
            row("2025-01-10", "1", "930", "잡이익", 0, 2_000_000, "법인세등_부가세_가상세무서_경정청구환급(24년4분기부가세경정청구)"),
            row("2025-03-31", "2", "930", "잡이익", 0, 500, "부가세 환급 단수"),
            row("2025-01-10", "1", "120", "미수금", 3_100_000, 0, "경정청구환급")]
    led = with_accounts(acc("930", "잡이익", "수익", 3_100_500, 0), acc("120", "미수금", "자산", 3_100_000, 0))
    for a in led["accounts"]:
        if a["code"] == "930":
            a["section"] = "영업외수익"
    ref = rules(run(led, rows))["tax_refund"]
    assert ref["title"] == "법인세 · 부가세 환급액이 수익에 있습니다. 익금불산입을 확인합니다"
    assert ref["amounts"] == {"current": 3_100_000} and ref["accounts"] == ["930"]
    assert any("법인세 · 지방소득세 환급 표기 2줄 △1,100,000원" in b for b in ref["basis"])
    assert any("부가세 환급 표기 1줄 △2,000,000원" in b for b in ref["basis"])
    assert any("익금 여부를 회계사가 정합니다" in b for b in ref["basis"])
    assert len(ref["questions"]) == 2 and any(x["ref"].startswith("법인세법 제18조 제5호") for x in ref["law"])


def test_refund_only_corporate_keeps_title():
    rows = [row("2025-02-10", "1", "930", "잡이익", 0, 700_000, "법인세 환급액")]
    led = with_accounts(acc("930", "잡이익", "수익", 700_000, 0))
    ref = rules(run(led, rows))["tax_refund"]
    assert ref["title"].startswith("법인세 환급액이 수익에 있습니다") and ref["amounts"] == {"current": 700_000}
    assert not any("부가세" in b for b in ref["basis"])


def test_local_tax_ten_percent_goes_with_corporate_and_interest_apart():
    rows = [row("2025-01-24", "1", "930", "잡이익", 0, 10_000_000, "법인세 환급액"),
            row("2025-01-24", "1", "930", "잡이익", 0, 300_000, "국세환급 가산이자"),
            row("2025-02-18", "2", "930", "잡이익", 0, 1_000_000, "지방세 환급"),
            row("2025-03-18", "3", "930", "잡이익", 0, 70_000, "지방세 환급")]
    led = with_accounts(acc("930", "잡이익", "수익", 11_370_000, 0))
    ref = rules(run(led, rows))["tax_refund"]
    assert ref["title"] == "법인세 · 지방세 환급액 · 환급가산금이 수익에 있습니다. 익금불산입을 확인합니다"
    assert any("법인세 · 지방소득세 환급 표기 2줄 △11,000,000원" in b and "법인세 환급의 10%" in b for b in ref["basis"])
    assert any("세목을 모르는 지방세 환급 표기 1줄 △70,000원" in b for b in ref["basis"])
    assert any("환급가산금 표기 1줄 △300,000원" in b for b in ref["basis"])
    assert any(x["ref"].startswith("법인세법 제18조 제4호") for x in ref["law"])


# ---------------------------------------------------------------- 2. 전기 29호 업무외사용금액 · 15호

PAGE_29 = """2. 업무용승용차관련비용손금불산입계산
차량
번호
업무사용금액
업무외사용금액
합계
가상1234
900,000
2,800,000
3,700,000
1,500,000
4,400,000
5,900,000
5,900,000
3,700,000
합계
900,000
2,800,000
3,700,000
1,500,000
4,400,000
5,900,000
5,900,000
3,700,000
210mm x 297mm
"""


def test_form29_total_row_fills_blank_excess():
    cells, why = total_row(PAGE_29)
    assert why is None
    assert cells["30"] == 5_900_000 and cells["31"] == 0 and cells["32"] == 5_900_000 and cells["33"] == 3_700_000


def test_form29_ambiguous_row_uses_word_columns():
    text = "2. 업무용승용차관련비용손금불산입계산\n합계\n1,000\n2,000\n3,000\n3,000\n"
    assert total_row(text)[0] is None
    heads = [(212, 382, 265, 392, "업무사용금액"), (427, 382, 488, 392, "업무외사용금액"), (572, 407, 625, 417, "한도초과금액"),
             (655, 388, 699, 398, "손금불산입"), (732, 388, 768, 398, "손금산입")]
    nums = [(84, 510, 101, 519, "합계"), (163, 510, 195, 519, "1,000"), (236, 510, 268, 519, "2,000"),
            (309, 510, 341, 519, "3,000"), (747, 510, 779, 519, "3,000")]
    cells, why = total_row(text, heads + nums)
    assert why is None and cells["27"] == 3_000 and cells["30"] == 0 and cells["33"] == 3_000


def test_scale_51_reads_numbers_on_same_or_next_line():
    words = [(268, 327, 311, 335, "당회사(10)"), (375, 327, 391, 335, "99.8"),
             (260, 350, 416, 358, "-「중소기업기본법시행령」별표1의규모기준(11)"), (369, 369, 389, 377, "1,000"),
             (267, 394, 311, 402, "자산총액(12)"), (374, 394, 390, 402, "59.4"),
             (268, 690, 311, 698, "당회사(14)"), (373, 689, 389, 697, "99.8"),
             (260, 707, 423, 715, "-「중소기업기본법시행령」별표3의규모기준(15)"), (326, 725, 346, 733, "120.0")]
    assert scale_51(words) == {"10": 99.8, "11": 1000.0, "12": 59.4, "14": 99.8, "15": 120.0}


def _prior_with_29(adj_extra=()):
    pr = prior()
    pr["cells"]["29"] = {"25": 900_000, "26": 2_800_000, "27": 3_700_000, "28": 1_500_000, "29": 4_400_000, "30": 5_900_000,
                         "31": 0, "32": 5_900_000, "33": 3_700_000}
    pr["adjustments"] = pr["adjustments"] + list(adj_extra)
    return pr


def test_prior_car_personal_missing_from_15():
    r = rules(run(pr=_prior_with_29()))
    miss = r["prior_car_missing"]
    assert miss["kind"] == "신고 점검" and miss["certainty"] == "확실"
    assert miss["amounts"] == {"prior": 5_900_000} and miss["forms"] == ["29", "15"]
    assert any("손금불산입 합계 5,900,000원(업무외사용금액 5,900,000원" in b for b in miss["basis"])
    assert miss["law"][0]["ref"].startswith("법인세법 제27조의2 제2항") and miss["papers"] == ["business_car"]


def test_prior_car_personal_on_15_is_quiet():
    adj = {"side": "가산", "subject": "업무용승용차", "amount": 5_900_000, "disposition": "상여", "code": "100",
           "note": "업무용승용차업무외사용금액손금불산입"}
    assert "prior_car_missing" not in rules(run(pr=_prior_with_29([adj])))


def test_prior_car_excess_partly_missing_from_15():
    """10-19: 업무외사용금액 0, 렌트 차량 한도초과 가운데 한 대분이 15호에 빠짐."""
    pr = prior()
    pr["cells"]["29"] = {"27": 98_000_000, "30": 0, "31": 3_700_000, "32": 3_700_000, "33": 94_300_000}
    pr["adjustments"] = pr["adjustments"] + [{"side": "가산", "subject": "차량유지비", "amount": 3_450_000,
                                              "disposition": "기타사외유출", "code": "500", "note": "업무용승용차한도초과액손금불산입"}]
    miss = rules(run(pr=pr))["prior_car_missing"]
    assert miss["certainty"] == "가능" and miss["amounts"] == {"prior": 250_000}
    assert miss["title"].startswith("전기 29호 손금불산입 합계가 전기 15호 업무용승용차 가산 줄보다 큽니다")
    assert any("1줄 3,450,000원, 차이 250,000원" in b for b in miss["basis"])


def test_penalty_in_misc_expense_account():
    rows = [row("2025-03-10", "1", "640", "잡비(도)", 480_000, 0, "자동차검사위반과태료"),
            row("2025-03-11", "2", "640", "잡비(도)", 30_000, 0, "현장 다과")]
    led = with_accounts(acc("640", "잡비(도)", "비용", 510_000, 0))
    pen = rules(run(led, rows))["penalty"]
    assert pen["certainty"] == "확실" and "640" in pen["accounts"]
    assert pen["title"].startswith("세금과공과 · 잡손실 · 잡비에 가산세 · 과태료로 보이는 지출이 있습니다")
    assert any("잡비 적요에 과태료 · 벌과금 표기 1줄 480,000원" in b for b in pen["basis"])


# ---------------------------------------------------------------- 3 · 4. 가이드 2-2 · 1-4

def test_guide_2_2_never_none_and_small_business_limit():
    ar = run()
    assert guide(ar, "2-2")["status"] != "해당 없음"
    pr = prior()
    pr["company"]["small"] = True
    pr["cells"]["51"] = {"10": 7.5, "11": 1000.0, "12": 1.0, "14": 7.5, "15": 5.0}      # 당기 매출액 9억 > 소기업 기준 5억
    ar = run(pr=pr)
    small = rules(ar)["sme_small"]
    assert small["kind"] == "신고 점검" and small["forms"] == ["51"] and small["amounts"] == {"current": 900_000_000}
    assert any("소기업 규모기준(15) 5억 원" in b for b in small["basis"])
    g = guide(ar, "2-2")
    assert g["status"] == "이슈" and any("당기 매출액 9.0억 원" in f for f in g["facts"])


def test_guide_2_2_within_limit_needs_data():
    pr = prior()
    pr["company"]["small"] = True
    pr["cells"]["51"] = {"11": 1000.0, "14": 7.5, "15": 50.0}
    ar = run(pr=pr)
    assert "sme_small" not in rules(ar) and guide(ar, "2-2")["status"] == "자료 필요"


def test_credit_fact_does_not_assume_no_tax_on_book_loss():
    led = ledger()
    led["totals"] = {**led.get("totals", {}), "income_before_tax": -5_000_000}
    pr = prior()
    pr["credits"] = [{"name": "중소기업에 대한 특별세액감면", "amount": 100_000, "code": "112"}]
    facts = guide(run(led, pr=pr), "1-4")["facts"]
    assert not any("감면할 세액이 없습니다" in f for f in facts)
    assert any("세무조정 전" in f and "△5,000,000원" in f for f in facts)


# ---------------------------------------------------------------- 5. 외환차손익 계정의 기말 환산

FX_ROWS = [row("2025-12-31", "9", "932", "외환차손", 6_800_000, 0, "보통예금_외환차손_12.31 기준 환율 적용"),
           row("2025-12-31", "9", "104", "외화예금", 0, 6_800_000, "12.31 기준 환율 적용"),
           row("2025-04-14", "3", "932", "외환차손", 8_500, 0, "용기 잔금 USD (환산차손)"),
           row("2025-04-14", "3", "251", "외상매입금", 0, 8_500, "용기 잔금")]


def test_ar_fx_issue_from_settlement_account():
    led = with_accounts(acc("932", "외환차손", "비용", 6_808_500, 0), acc("104", "외화예금", "자산", 10_000_000, 0))
    fx = rules(run(led, FX_ROWS))["fx"]
    assert fx["title"].startswith("외환차손익 계정에 기말 외화 환산손익이 있습니다")
    assert fx["amounts"] == {"current": -6_800_000} and fx["accounts"] == ["932"] and fx["papers"] == ["fx"]
    assert any("기말 환산(날짜 · 적요) 표기 1줄 6,800,000원" in b for b in fx["basis"])
    assert any("거래일 차손익으로 보고 넣지 않았습니다" in b for b in fx["basis"])


# ---------------------------------------------------------------- 10-19 나참유통 · 조미코리아 실행에서 더한 것

def test_advance_memo_outside_loan_account():
    rows = [row("2025-07-03", "1", "138", "전도금", 1_500_000, 0, "가상솔루션 가불"),
            row("2025-07-03", "1", "103", "보통예금", 0, 1_500_000, "가상솔루션 가불"),
            row("2025-08-28", "2", "103", "보통예금", 43_000_000, 0, "가상솔루션 가지급 반제"),
            row("2025-08-28", "2", "138", "전도금", 0, 43_000_000, "가상솔루션 가지급 반제")]
    led = with_accounts(acc("138", "전도금", "자산", 380_000_000, 420_000_000))
    adv = rules(run(led, rows))["advance:138"]
    assert adv["title"].startswith("전도금 계정에 가지급 · 가불 적요가 있습니다")
    assert adv["amounts"] == {"current": 380_000_000} and adv["papers"] == ["loan_interest"]
    assert any("가지급 · 가불 표기 2줄" in b for b in adv["basis"])
    assert adv["law"][0]["ref"].startswith("법인세법 시행령 제89조")


def test_car_disposal_loss_over_limit():
    rows = [row("2025-03-04", "5", "208", "차량운반구", 0, 60_000_000, "법인 승용차 매각"),
            row("2025-03-04", "5", "209", "감가상각누계액", 49_818_181, 0, "법인 승용차 매각"),
            row("2025-03-04", "5", "103", "보통예금", 1_500_000, 0, "법인 승용차 매각"),
            row("2025-03-04", "5", "970", "유형자산처분손실", 8_681_819, 0, "법인 승용차 매각")]
    led = with_accounts(acc("970", "유형자산처분손실", "비용", 8_681_819, 0))
    r = rules(run(led, rows))
    d = r["car_disposal:2025-03-04:5"]
    assert d["amounts"] == {"current": 8_681_819} and any("넘는 금액 681,819원" in b for b in d["basis"])
    assert d["law"][0]["ref"].startswith("법인세법 제27조의2 제4항")


def test_prior_donation_counted_twice():
    led = with_accounts(acc("953", "기부금", "비용", 10_000_000, 14_000_000))
    pr = prior()
    pr["rows"] = {"21": [{"절": 6, "사업연도": "2024", "종류": "특례", "26": 6_000_000, "27": 6_000_000, "28": 0},
                         {"절": 6, "사업연도": "2024", "종류": "일반", "26": 8_000_000, "27": 8_000_000, "28": 0}]}
    pr["adjustments"] = pr["adjustments"] + [{"side": "가산", "subject": "기부금", "amount": 6_000_000, "disposition": "기타사외유출",
                                              "code": "500", "note": "기부금한도초과액손금불산입"}]
    ov = rules(run(led, pr=pr))["prior_donation_overlap"]
    assert ov["kind"] == "신고 점검" and ov["amounts"] == {"prior": 6_000_000}
    assert ov["law"][0]["ref"].startswith("법인세법 제24조")


def test_prior_small_mark_contradicts_scale():
    pr = prior()
    pr["company"]["small"] = False
    pr["cells"]["51"] = {"11": 1000.0, "14": 7.5, "15": 80.0}
    small = rules(run(pr=pr))["sme_small"]
    assert small["title"].startswith("전기 51호는 소기업 「부」 인데 매출액이 소기업 규모기준 안입니다")
    assert any("51호 안에서 어긋남" in b for b in small["basis"])


def test_loan_moved_without_cash():
    rows = [row("2025-12-31", "9", "137", "주.임.종단기채권", 0, 44_000_000, "반제처리"),
            row("2025-12-31", "9", "108", "외상매출금", 44_000_000, 0, "반제처리")]
    mv = rules(run(ledger(), rows))["loan_moved"]
    assert mv["kind"] == "신고 점검" and mv["amounts"] == {"current": 44_000_000}
    assert any("차변은 외상매출금" in b for b in mv["basis"])


def test_credit_fact_when_form_8_missing():
    pr = prior()
    pr["forms"] = [f for f in pr["forms"] if f["code"] != "8갑"]
    pr["credits"] = []
    g = guide(run(pr=pr), "1-4")
    assert g["status"] == "자료 필요" and any("8호(갑)이 보이지 않아" in f for f in g["facts"])
