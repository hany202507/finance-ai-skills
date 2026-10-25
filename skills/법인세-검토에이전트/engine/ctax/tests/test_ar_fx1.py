"""ctax ar 5회차(엔진 고칠 목록) 시험. 합성 장부 · 전표만 쓴다(고객 이름 · 금액 없음)."""
from __future__ import annotations

from ctax.ar import engine, memo
from ctax.tests.test_ar import acc, by_title, ledger, prior, run


def row(date, no, code, name, dr, cr, memo_text="", partner=""):
    return {"date": date, "no": no, "kind": "차변" if dr else "대변", "account": code, "account_name": name, "debit": dr,
            "credit": cr, "partner_code": "", "partner": partner, "memo_code": "", "memo": memo_text, "closing": False}


def with_accounts(*extra, drop=()):
    base = [a for a in ledger()["accounts"] if a["code"] not in drop]
    return ledger(accounts=base + list(extra))


def rules(ar):
    return {i["rule"]: i for i in ar["issues"]}


# ---------------------------------------------------------------- 메모 검사: 법령 번호는 금액이 아니다

def test_memo_tokens_skip_law_numbers_and_dates():
    text = ("법인세법 제55조 제1항 제2호는 부칙 <제20613호, 20241231> 제5조와 법률 제20613호, 대통령령 제35347호, "
            "MST 279739 로 확인했습니다. 금액 12,345원과 98765원")
    assert sorted(v for _raw, v in memo.tokens(text)) == [12_345, 98_765]


# ---------------------------------------------------------------- 배당금수익: 펀드 · 신탁 분배금은 후보에서 뺀다

def _dividend_case(rows):
    led = with_accounts(acc("125", "매도가능증권", "자산", 50_000_000, 40_000_000),
                        acc("136", "선납세금", "자산", 0, 0, debit=1_400_000, credit=1_400_000, closing=0),
                        acc("903", "배당금수익", "수익", sum(r["credit"] for r in rows if r["account"] == "903"), 0))
    return run(led, rows)


def test_fund_distributions_are_not_dividend_candidates():
    rows = [row("2025-05-15", "1", "903", "배당금수익", 0, 10_000_000, "증권 계좌 배당수익"),
            row("2025-05-15", "1", "136", "선납세금", 1_400_000, 0, "이자소득 원천징수"),
            row("2025-05-15", "1", "125", "매도가능증권", 8_600_000, 0, "배당수익 재투자"),
            row("2025-12-26", "2", "125", "매도가능증권", 0, 30_000_000, "만기"),
            row("2025-12-26", "2", "903", "배당금수익", 0, 2_000_000, "만기"),
            row("2025-12-26", "2", "103", "보통예금", 32_000_000, 0, "대체입")]
    ar = _dividend_case(rows)
    assert "dividend" not in rules(ar)
    wh = rules(ar)["withholding"]
    assert any("펀드 · 신탁 분배금" in b and "12,000,000원" in b for b in wh["basis"])
    g = next(g for g in ar["guide"] if g["id"] == "2-3-1-3")
    assert any("익금불산입 후보에서 뺐습니다" in f for f in g["facts"])


def test_plain_dividend_stays_and_card_purchase_in_same_voucher_is_not_fund():
    rows = [row("2025-04-16", "1", "103", "보통예금", 5_000_000, 0, "가상전자 배당금"),
            row("2025-04-16", "1", "903", "배당금수익", 0, 5_000_000, "가상전자 배당금"),
            row("2025-04-16", "1", "106", "기타단기금융상품", 3_000_000, 0, "CMA 매수"),
            row("2025-04-16", "1", "103", "보통예금", 0, 3_000_000, "CMA 매수"),
            row("2025-11-12", "2", "903", "배당금수익", 0, 1_000_000, "펀드 분배금"),
            row("2025-11-12", "2", "103", "보통예금", 1_000_000, 0, "")]
    ar = _dividend_case(rows)
    dv = rules(ar)["dividend"]
    assert any("1줄 1,000,000원" in b and "남은 후보 5,000,000원" in b for b in dv["basis"])
    assert any(x["ref"].startswith("법인세법 제73조 제1항 제2호") for x in dv["law"])


# ---------------------------------------------------------------- 투자 판정 계정: 건설기계

def test_construction_equipment_counts_for_investment_credit():
    led = with_accounts(acc("217", "건설용장비", "자산", 20_000_000, 0))
    inv = rules(run(led))["investment_credit"]
    assert "217" in inv["accounts"] and inv["amounts"]["change"] == 20_000_000
    assert any("시행규칙 제12조" in x["ref"] for x in inv["law"])


# ---------------------------------------------------------------- 대손충당금: 한도 비교 · 환입은 대손이 아니다

def test_allowance_over_one_percent_is_certain():
    led = with_accounts(acc("109", "대손충당금", "자산", -1_000_000, -1_000_000, lines=0, debit=0, credit=0, closing=-1_000_000))
    bd = rules(run(led))["bad_debt"]
    assert bd["certainty"] == "가능"                       # 외상매출금 30,000,000 + 주임종 70,000,000 의 1% = 1,000,000 은 넘지 않음
    led = with_accounts(acc("109", "대손충당금", "자산", -1_500_000, -1_500_000, lines=0, debit=0, credit=0, closing=-1_500_000))
    bd = rules(run(led))["bad_debt"]
    assert bd["certainty"] == "확실" and any("1,000,000원보다 커 한도초과" in b for b in bd["basis"])
    assert any(x["ref"].startswith("법인세법 시행령 제61조 제2항") for x in bd["law"])


def test_allowance_excludes_related_party_loans_like_the_paper():
    """10-25 대표 지시: 주임종 · 가지급금 · 대여금은 특수관계인 대여로 보아 설정 대상에서 빼고(조서 설정제외 기본값), 뺀 한도와 넣은
    한도를 다 적는다. 근거 조문에 법인세법 제34조 제2항이 붙는다."""
    led = with_accounts(acc("109", "대손충당금", "자산", -1_500_000, -1_500_000, lines=0, debit=0, credit=0, closing=-1_500_000))
    bd = rules(run(led))["bad_debt"]
    text = " ".join(bd["basis"])
    assert "매출채권 · 미수금 30,000,000원의 1% 300,000원보다 커 한도초과가 생깁니다" in text
    assert "70,000,000원은 특수관계인 대여로 보아 설정 대상에서 뺐습니다" in text
    assert "넣어 계산한 한도 1,000,000원보다 커 한도초과입니다" in text
    assert any(x["ref"].startswith("법인세법 제34조 제2항") for x in bd["law"])
    led = with_accounts(acc("109", "대손충당금", "자산", -900_000, -900_000, lines=0, debit=0, credit=0, closing=-900_000))
    text = " ".join(rules(run(led))["bad_debt"]["basis"])
    assert "설정 대상에 넣으면 한도 1,000,000원이라 한도초과가 없습니다" in text


def test_allowance_within_wide_base_stays_possible():
    led = with_accounts(acc("109", "대손충당금", "자산", -900_000, -900_000, lines=0, debit=0, credit=0, closing=-900_000))
    bd = rules(run(led))["bad_debt"]
    assert bd["certainty"] == "가능"
    assert any("매출채권 · 미수금 30,000,000원의 1% 300,000원보다 큽니다" in b for b in bd["basis"])


def test_reversal_entry_is_not_a_write_off():
    rows = [row("2025-01-31", "1", "109", "대손충당금", 200_000, 0, "당월충당금 환입"),
            row("2025-01-31", "1", "835", "대손상각비(판)", -200_000, 0, "당월충당금 환입")]
    led = with_accounts(acc("109", "대손충당금", "자산", -100_000, -300_000, debit=200_000, credit=0, closing=-100_000),
                        acc("835", "대손상각비(판)", "비용", -200_000, 0))
    bd = rules(run(led, rows))["bad_debt"]
    assert any("환입 200,000원. 채권을 대손으로 지운 전표는 없습니다" in b for b in bd["basis"])
    assert not any("대손 처리한 채권이 있습니다" in b for b in bd["basis"])


# ---------------------------------------------------------------- 대여금: 면제 적요라도 예금 입금이면 회수 · 기중 잔액

def test_forgive_memo_with_cash_in_is_repayment():
    rows = [row("2025-12-22", "1", "103", "보통예금", 3_000_000, 0, "가상인빌린돈면제"),
            row("2025-12-22", "1", "137", "주.임.종단기채권", 0, 3_000_000, "가상인빌린돈면제"),
            row("2025-12-23", "2", "835", "대손상각비(판)", 1_000_000, 0, "채권 포기"),
            row("2025-12-23", "2", "137", "주.임.종단기채권", 0, 1_000_000, "채권 포기")]
    loan = rules(run(ledger(), rows))["loan"]
    assert any("면제 · 포기 표기 1줄 △1,000,000원" in b for b in loan["basis"])
    assert any("돌려받은 돈으로 보고 면제에서 뺐습니다" in b and "3,000,000원" in b for b in loan["basis"])


def test_loan_during_year_is_seen_even_when_closing_is_zero():
    rows = [row("2025-01-02", "1", "134", "가지급금", 100_000_000, 0, "대표자 가지급"),
            row("2025-01-02", "1", "103", "보통예금", 0, 100_000_000, "대표자 가지급"),
            row("2025-12-31", "2", "103", "보통예금", 100_000_000, 0, "가지급금 회수"),
            row("2025-12-31", "2", "134", "가지급금", 0, 100_000_000, "가지급금 회수")]
    led = with_accounts(acc("134", "가지급금", "자산", 0, 0, lines=2, debit=100_000_000, credit=100_000_000, closing=0),
                        acc("951", "이자비용", "비용", 5_000_000, 4_000_000), drop=("137",))
    r = rules(run(led, rows))
    loan = r["loan"]
    assert loan["title"].startswith("기중에 대여금 · 가지급금이 있었는데")
    assert any("최대 100,000,000원(2025-01-02)" in b and "일별 잔액 평균 99,452,055원" in b for b in loan["basis"])
    assert any("대표 · 임원(지급) 표기 1줄 100,000,000원" in b for b in loan["basis"])
    assert any("일별 잔액 평균 99,452,055원" in b for b in r["loan_interest"]["basis"])


# ---------------------------------------------------------------- 이자 순액 계상 · 퇴직연금 운용수익

def test_net_interest_memo_without_prepaid_tax():
    rows = [row("2025-06-14", "1", "103", "보통예금", 60_000, 0, "이자세금:11,000원"),
            row("2025-06-14", "1", "901", "이자수익", 0, 60_000, "이자세금:11,000원"),
            row("2025-06-14", "2", "901", "이자수익", 0, 600, "이자세금:0원"),
            row("2025-06-14", "3", "901", "이자수익", 0, 9_000, "법인세 환급가산금")]
    net = rules(run(ledger(), rows))["interest_net"]
    assert net["kind"] == "조정 후보" and net["amounts"] == {"current": 11_000}
    assert any("1줄 60,000원" in b for b in net["basis"])
    assert net["papers"] == ["summary_15", "tax_3"] and net["todo"]


def test_plan_income_added_to_provision_is_flagged():
    rows = [row("2025-12-31", "1", "198", "퇴직연금운용자산", 650_000, 0, "퇴직연금 운용수익"),
            row("2025-12-31", "1", "295", "퇴직급여충당부채", 0, 650_000, "퇴직연금 운용수익"),
            row("2025-12-31", "2", "806", "퇴직급여(판)", 12_000_000, 0, "당기분 전입"),
            row("2025-12-31", "2", "295", "퇴직급여충당부채", 0, 12_000_000, "당기분 전입"),
            row("2025-11-30", "3", "198", "퇴직연금운용자산", 3_000_000, 0, "DB 입금"),
            row("2025-11-30", "3", "103", "보통예금", 0, 3_000_000, "DB 입금")]
    led = with_accounts(acc("198", "퇴직연금운용자산", "자산", 3_650_000, 0))
    inc = rules(run(led, rows))["retirement_income"]
    assert inc["certainty"] == "확실" and inc["amounts"] == {"current": 650_000}
    assert inc["papers"] == ["retirement"] and inc["law"][0]["ref"].startswith("법인세법 제15조 제1항")


# ---------------------------------------------------------------- 유가증권 손익: 이익과 손실을 더하지 않는다

def test_securities_gain_and_loss_are_listed_apart():
    led = with_accounts(acc("182", "지분법적용투자주식", "자산", 90_000_000, 95_000_000),
                        acc("922", "장기투자자산평가익", "수익", 4_000_000, 0),
                        acc("944", "지분법손실", "비용", 5_000_000, 3_000_000))
    sec = rules(run(led))["securities"]
    assert any(b.startswith("평가 · 지분법 이익(익금불산입 후보): 장기투자자산평가익 4,000,000원") for b in sec["basis"])
    assert any(b.startswith("평가 · 지분법 · 손상 손실(손금불산입 후보): 지분법손실 5,000,000원") for b in sec["basis"])
    assert not any("9,000,000원" in b for b in sec["basis"])


# ---------------------------------------------------------------- 전기오류수정: 기중 금액 · 전기 유보와 잇기

def test_prior_error_uses_period_amount_and_links_reserve():
    rows = [row("2025-12-31", "1", "371", "전기오류수정손실", 40_000_000, 0, "전기채권과대계상"),
            row("2025-12-31", "1", "257", "가수금", 0, 40_000_000, "전기채권과대계상"),
            row("2025-12-31", "2", "377", "미처분이익잉여금", 40_000_000, 0, "전기오류수정손실"),
            row("2025-12-31", "2", "371", "전기오류수정손실", 0, 40_000_000, "처분전이익잉여금에 대체")]
    led = with_accounts(acc("371", "전기오류수정손실", "자본", 0, 0, lines=2, debit=40_000_000, credit=40_000_000, closing=0))
    pr = prior(reserves=[{"subject": "외상매출금", "opening": 0, "decrease": 0, "increase": -10_000_000, "closing": -10_000_000}])
    ar = run(led, rows, pr)
    pe = rules(ar)["prior_error"]
    assert pe["amounts"] == {"prior": None, "current": 40_000_000, "change": None} and pe["folded"] is False
    linked = [i for i in ar["issues"] if any("외상매출금 기말 유보" in b for b in i["basis"]) and i["rule"] != "prior_error"]
    assert linked
    assert f"함께 볼 이슈 {linked[0]['no']}" in pe["basis"]
    assert f"함께 볼 이슈 {pe['no']}" in linked[0]["basis"]


# ---------------------------------------------------------------- 근거 조문: 빈 이슈가 없다

def test_every_issue_has_law_and_new_refs():
    pr = prior(adjustments=prior()["adjustments"] + [
        {"side": "가산", "subject": "알 수 없는 과목", "amount": 777_000, "disposition": "유보", "code": "400", "note": ""}])
    led = with_accounts(acc("411", "임대료수입", "수익", 5_000_000_000, 4_000_000_000),
                        acc("939", "재고자산감모손실", "비용", 2_000_000, 0))
    led["checks"] = [{"id": "pl_match", "ok": False, "title": "", "detail": "", "amounts": {"diff": 10}}]
    ar = run(led, None, pr)
    for i in ar["issues"]:
        assert i["law"], i["title"]
    r = rules(ar)
    assert r["check:pl_match"]["law"][0]["ref"].startswith("법인세법 제60조 제2항")
    assert any(x["ref"].startswith("법인세법 제55조 제1항 제2호") for x in r["rental_main"]["law"])
    refs = [x["ref"] for x in r["inventory_loss"]["law"]]
    assert refs[0].startswith("법인세법 제19조 제1항") and refs[1].startswith("법인세법 제42조 제3항 제1호")
    unlinked = [i for i in ar["issues"] if i["rule"].startswith("prior:알 수 없는 과목")][0]
    assert unlinked["law"][0]["grade"] == "☆"
    assert engine.validate(ar) == []


# ---------------------------------------------------------------- 세금과공과: 단수 차이 줄 · 불공제 매입세액

def test_tiny_rounding_lines_are_not_penalties_and_nondeductible_vat_issue():
    led = with_accounts(acc("817", "세금과공과", "비용", 1_000_001, 0))
    rows = [row("2025-03-10", "1", "817", "세금과공과", 1, 0, "부가세 단수차"),
            row("2025-04-10", "2", "817", "세금과공과", 1_000_000, 0, "불공제매입세액대체")]
    r = rules(run(led, rows))
    assert r["penalty"]["certainty"] == "가능"                       # 1원 「부가세」 줄은 가산세 표기로 세지 않는다
    nv = r["nondeductible_vat"]
    assert nv["amounts"]["current"] == 1_000_000 and "taxes_dues" in nv["papers"]
