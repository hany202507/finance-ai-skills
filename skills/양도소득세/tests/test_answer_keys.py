# -*- coding: utf-8 -*-
"""정답지 대조. 국세청 홈택스 양도소득세 신고서 작성 사례(2023)를 엔진 → 신고값 → 서식 검산 → 전자신고 파일까지 돌린다.

사례와 기대값은 tests/answer_keys.py, 옮긴 방법과 손계산은 references/정답지.md 에 있다.
  엔진          과세표준·산출세액·지방소득세가 현행 기대값(규칙세트로 손계산한 값)과 같다
  서식 검산     forms_check.check 가 빈 목록이다
  서식 값       부표1 ③·⑪~⑱·기준시가, 본지 ④~⑩, 부표3 구분코드별 금액이 원문 서식의 같은 칸과 같다.
                「제외」에 든 칸은 이유와 함께 현행 기대값과 비교한다
  납부 행       전자신고세액공제·납부할 세액·분납·납부세액(원문 2022-03 서식 ⑭·⑰·⑱·⑲, 지금 서식 ⑮·⑱·⑲·⑳)
  범위 아님     엔진의 다루지않음이나 신고값의 Unsupported 로 멈춘다(틀린 세액이나 신고서를 내지 않는다)
  가산세        예정신고를 하지 않은 확정신고(사례 09 하위 8)의 본지 ⑯ 과 납부할 세액, 03 레코드 가산세 칸이 현행 기대값과 같다
아직 고치지 않은 결함은 xfail(strict=True)로 남긴다(파일 끝). 지금은 남은 것이 없다.
"""
import copy
import os

import pytest

from yangdo import edition, engine, filing, forms_check, penalty, return_values, ruleset
from answer_keys import KEYS, OUT, SKIP


TODAY = "2026-10-11"
NAMES = sorted(KEYS)
# 홈택스 자료실의 작성 사례 10건. 확정신고 사례 09 는 하위 사례가 여덟이다
ALL_CASES = {"01", "02", "03", "04", "05", "06", "07", "08", "10"} | {"09-%d" % n for n in range(1, 9)}
_CACHE = {}


def _run(name):
    """(엔진 결과, 신고값). 한 번만 만들고 사본을 준다."""
    if name not in _CACHE:
        k = KEYS[name]
        r = engine.calculate(copy.deepcopy(k["facts"]), today=k.get("오늘", TODAY))
        rv = None
        if r["상태"] == "완료":
            rv = return_values.build(r, k["facts"], filing.load(copy.deepcopy(k["filer"])))
        _CACHE[name] = (r, rv)
    return copy.deepcopy(_CACHE[name])


def _blank(x):
    return x in (None, "", 0)


def _same(got, want):
    """원문이 비운 칸(0 또는 빈 글자)은 신고값의 None·0·빈 글자와 같게 본다."""
    return _blank(got) if _blank(want) else got == want


def _want(k, form, col, key, original):
    """그 칸의 기대값. 「제외」에 든 칸은 현행 기대값, 나머지는 원문 서식 값."""
    excluded = k["제외"].get((form, col, key))
    return excluded[1] if excluded else original


# ---------------------------------------------------------------- 정답지 자체

def test_every_published_case_is_classified():
    """작성 사례는 빠짐없이 대조(KEYS), 범위 아님(OUT), 대조하지 않음(SKIP) 가운데 한 곳 이상에 든다.
    사례 02 만 둘에 든다(원문 날짜는 범위 아님, 의제취득일을 넣은 변형은 대조)."""
    assert set(KEYS) | set(OUT) | set(SKIP) == ALL_CASES
    assert set(KEYS) & set(OUT) == {"02"}
    assert not set(SKIP) & (set(KEYS) | set(OUT))
    assert all(isinstance(why, str) and why for why in SKIP.values())


def test_keys_carry_only_synthetic_people():
    """공개 저장소라 신고인·양수인·지급처는 합성값이다. 사업자번호는 0000000xxx 꼴이고 검증번호가 맞는다."""
    for name, k in list(KEYS.items()) + list(OUT.items()):
        for a in k["facts"]["자산"]:
            for group in ("취득부대", "자본적지출", "기타", "양도비"):
                for it in a["필요경비"][group]:
                    assert it["사업자번호"].startswith("0000000") and filing.biz_ok(it["사업자번호"]), (name, it["내용"])
                    assert it["상대방"].startswith("합성"), (name, it["내용"])
        f = k.get("filer")
        if not f:
            continue
        assert f["신고인"]["성명"].endswith("합성") and f["신고인"]["주민등록번호"].startswith("000101")
        for b in f["양수인"]:
            assert b["성명"].endswith("합성") and b["번호"].startswith("000102"), name
        for lot in f["자산"].values():
            assert lot.get("취득상대방", "최합성").endswith("합성"), name


@pytest.mark.parametrize("name", NAMES)
def test_today_is_not_before_any_sale_date(name):
    """엔진에 주는 오늘 날짜가 사례의 양도일보다 앞서지 않는다. 09-8 은 C 의 양도일이 기본 오늘보다 뒤라 사례에 오늘을 적었다."""
    k = KEYS[name]
    last = max(a["양도"]["잔금일"] for a in k["facts"]["자산"])
    assert k.get("오늘", TODAY) >= last, (name, last)
    assert ("오늘" in k) == (last > TODAY), name                  # 필요한 사례에만 적는다
    r, _ = _run(name)
    assert r["기준정보"]["오늘"] == k.get("오늘", TODAY) and r["기준정보"]["낡음"] is False


def test_cells_that_need_confirmation_are_marked():
    """원문과 다르게 둔 까닭을 원문만으로 확정하지 못한 칸은 이유가 「확인 필요」로 시작한다. 03 의 납부세액(분납)과 07 의 ⑰."""
    from answer_keys import CONFIRM
    marked = sorted((name, form, col, key) for name, k in KEYS.items()
                    for (form, col, key), (why, _) in k["제외"].items() if why.startswith(CONFIRM))
    assert marked == [("03", "납부", "합계", "신고기한내납부"), ("07", "부표1", "A", "장특공거주기간")]
    assert "분납" in KEYS["03"]["제외"][("납부", "합계", "신고기한내납부")][0]
    assert KEYS["03"]["filer"]["신고"]["분납신청"] is False
    # 03 이 분납을 신청했다면: 납부할 세액 21,921,400 이 2천만원을 넘어 50% 인 10,960,700 까지 분납한다
    k = KEYS["03"]
    r, _ = _run("03")
    asked = copy.deepcopy(k["filer"])
    asked["신고"]["분납신청"] = True
    t = return_values.build(r, k["facts"], filing.load(asked))["본지"]["열"]["합계"]
    assert (t["납부할세액"], t["분납"], t["신고기한내납부"]) == (21_921_400, 10_960_700, 10_960_700)


def test_case_01_rate_and_deduction_codes_come_from_the_simplified_return():
    """사례 01 만 세율구분표기와 장특공코드를 원문 값으로 둔다(원문의 간편신고서 쪽 값). 원문 부표1 에 그 값이 없는 다른
    예정신고 사례에는 두지 않는다."""
    assert (KEYS["01"]["부표1"]["A"]["세율구분표기"], KEYS["01"]["부표1"]["A"]["장특공코드"]) == ("1-10", "02")
    for name in ("02", "03", "07", "08"):
        assert "장특공코드" not in KEYS[name]["부표1"]["A"] and "세율구분표기" not in KEYS[name]["부표1"]["A"], name


def test_schedule1_period_cells_follow_the_original():
    """부표1 ⑨ 보유기간, ⑩ 거주기간. 원문은 1세대1주택 고가주택 사례(03)에만 적었고 나머지 사례는 비웠다. 신고값도 같다."""
    for name in NAMES:
        _, rv = _run(name)
        for a in rv["부표1"]:
            want = KEYS[name]["부표1"][a["자산"]]
            assert (a["보유기간"], a["거주기간"]) == (want["보유기간"], want["거주기간"]), (name, a["자산"])
            assert (want["보유기간"] != "") == (name == "03"), name


def test_out_case_09_3_carries_both_prior_returns():
    """확정신고 사례 09 하위 3 은 두 번 모두 예정신고했다. 기신고는 두 건이고 결정세액의 합이 원문 서식 ⑯ 기신고세액이다.
    손계산(2022년 귀속 세율표): (40,000,000 − 2,500,000) × 15% − 1,080,000 = 4,545,000, 61,600,000 × 24% − 5,220,000 = 9,564,000"""
    prior = OUT["09-3"]["facts"]["연간"]["기신고"]
    assert [x["양도소득금액"] for x in prior] == [40_000_000, 61_600_000]
    assert [x["결정세액"] for x in prior] == [4_545_000, 9_564_000]
    assert sum(x["결정세액"] for x in prior) == OUT["09-3"]["원문기신고세액"] == 14_109_000
    assert len(OUT["09-1"]["facts"]["연간"]["기신고"]) == 2 and len(OUT["09-4"]["facts"]["연간"]["기신고"]) == 1


@pytest.mark.parametrize("name", NAMES)
def test_exclusions_have_reason_and_differ_from_original(name):
    """제외 목록의 칸마다 이유가 있고, 원문 값과 현행 기대값이 실제로 다르다(같으면 제외할 까닭이 없다)."""
    k = KEYS[name]
    for (form, col, key), (why, current) in k["제외"].items():
        assert isinstance(why, str) and len(why) > 10, (form, col, key)
        if form == "납부":
            original = k["납부"][key]
        else:
            original = k[form][col]
            for part in key.split("."):
                original = original[part]
        assert not _same(current, original), (form, col, key)
    # 법이 바뀌지 않은 사례는 원문 과세표준·산출세액이 현행 기대값과 같다
    assert k["원문"]["과세표준"] == k["현행"]["과세표준"]
    assert (k["원문"]["산출세액"] == k["현행"]["산출세액"]) != (("본지", "합계", "산출세액") in k["제외"])


# ---------------------------------------------------------------- 엔진

@pytest.mark.parametrize("name", NAMES)
def test_answer_key(name):
    k = KEYS[name]
    r, _ = _run(name)
    assert r["상태"] == "완료", r["질문"] or r["다루지않음"] or r["검산"]
    assert r["경고"] == []
    t = r["계산"]["합계"]
    assert (t["과세표준"], t["산출세액"]) == (k["현행"]["과세표준"], k["현행"]["산출세액"])
    assert t["지방소득세"] == k["현행"]["지방소득세"]


# ---------------------------------------------------------------- 서식

@pytest.mark.parametrize("name", NAMES)
def test_forms_check_passes(name):
    k = KEYS[name]
    r, rv = _run(name)
    assert filing.questions(filing.load(copy.deepcopy(k["filer"])), k["facts"], r) == []
    assert forms_check.check(rv, r, facts=KEYS[name]["facts"]) == []


@pytest.mark.parametrize("name", NAMES)
def test_schedule1_matches_original_form(name):
    """부표1 ③ 자산종류, ⑪~⑱, 기준시가."""
    k = KEYS[name]
    _, rv = _run(name)
    rows = {s["자산"]: s for s in rv["부표1"]}
    assert set(rows) == set(k["부표1"])
    bad = []
    for aid, original in k["부표1"].items():
        got = rows[aid]
        for key, value in original.items():
            if key == "기준시가":
                for part, amount in value.items():
                    want = _want(k, "부표1", aid, "기준시가." + part, amount)
                    if not _same(got["기준시가"][part], want):
                        bad.append("%s 기준시가 %s: %r ≠ %r" % (aid, part, got["기준시가"][part], want))
                continue
            assert key in got, key
            want = _want(k, "부표1", aid, key, value)
            if not _same(got[key], want):
                bad.append("%s %s: %r ≠ %r" % (aid, key, got[key], want))
    assert bad == []


@pytest.mark.parametrize("name", [n for n in NAMES if KEYS[n].get("부표3")])
def test_schedule3_matches_original_form(name):
    """부표3 구분코드별 금액과 ⑤ 계, ⑬ 계. 원문에 부표3 쪽이 있는 사례만 본다.
    사실관계에는 취득세 칸이 하나뿐이라 원문의 등록세(113)는 취득세(112)에 합쳐 비교한다."""
    k = KEYS[name]
    _, rv = _run(name)
    sheets = {s["자산"]: s for s in rv["부표3"]}
    assert set(sheets) == set(k["부표3"])
    for aid, original in k["부표3"].items():
        want = dict(original["행"])
        want["112"] = want.get("112", 0) + want.pop("113", 0)
        want = {code: amount for code, amount in want.items() if amount}
        got = {}
        for row in sheets[aid]["행"]:
            got[row["구분코드"]] = got.get(row["구분코드"], 0) + row["금액"]
        assert got == want, aid
        assert (sheets[aid]["취득가액계"], sheets[aid]["기타필요경비계"]) == (original["취득가액계"], original["기타필요경비계"])


@pytest.mark.parametrize("name", NAMES)
def test_main_form_matches_original_form(name):
    """본지 ④ 양도소득금액 ~ ⑩ 산출세액. 합계, 국내분 소계, 세율구분 열마다."""
    k = KEYS[name]
    _, rv = _run(name)
    labels = [x["표기"] for x in rv["본지"]["세율구분"]]
    assert set(labels) == set(k["본지"]) - {"합계", "국내소계"}
    assert k["열"] in labels
    bad = []
    for cname, original in k["본지"].items():
        got = rv["본지"]["열"][cname]
        for key, value in original.items():
            want = _want(k, "본지", cname, key, value)
            if not _same(got[key], want):
                bad.append("%s %s: %r ≠ %r" % (cname, key, got[key], want))
    assert bad == []


@pytest.mark.parametrize("name", NAMES)
def test_payment_rows_match_original_form(name):
    """합계 열의 전자신고세액공제, 납부할 세액, 분납할 세액, 납부세액. 감면·기신고세액은 원문도 비웠다.
    가산세는 예정신고 사례에는 없고, 확정신고 사례 09-8 은 손계산한 현행 값이다(원문 값과 다른 까닭은 「가산세 대조」)."""
    k = KEYS[name]
    assert set(k["납부"]) == {"전자신고공제", "납부할세액", "분납", "신고기한내납부"}
    _, rv = _run(name)
    got = rv["본지"]["열"]["합계"]
    bad = ["%s: %r ≠ %r" % (key, got[key], _want(k, "납부", "합계", key, value))
           for key, value in k["납부"].items() if not _same(got[key], _want(k, "납부", "합계", key, value))]
    assert bad == []
    for key in ("감면세액", "외국납부", "원천징수", "연금계좌", "기신고세액"):
        assert got[key] == 0, key
    assert got["가산세"] == (k["현행가산세"]["계"] if "현행가산세" in k else 0)
    if "현행가산세" in k:      # 원문도 납부할 세액 = 산출세액 + 가산세, 납부세액 = 납부할 세액이다
        src = k["원문가산세"]
        assert k["납부"]["납부할세액"] == k["원문"]["산출세액"] + src["계"] == src["납부할세액"] == k["납부"]["신고기한내납부"]


# ---------------------------------------------------------------- 전자신고 파일


# ---------------------------------------------------------------- 신고 범위가 아닌 사례

@pytest.mark.parametrize("name", sorted(OUT))
def test_out_of_scope_case_stops(name):
    """범위가 아닌 사례는 세액이나 신고서를 내지 않는다. 엔진이 다루지않음으로 끝나거나, 엔진은 끝나도 신고값이 Unsupported 다."""
    k = OUT[name]
    r = engine.calculate(copy.deepcopy(k["facts"]), today=TODAY)
    if k["단계"] == "엔진":
        assert r["상태"] != "완료" and r["계산"] is None
        assert r["질문"] == []
        assert any(k["이유"] in x["내용"] for x in r["다루지않음"]), r["다루지않음"]
    else:
        assert r["상태"] == "완료"
        with pytest.raises(return_values.Unsupported, match=k["이유"]):
            return_values.build(r, k["facts"], filing.load(copy.deepcopy(k["filer"])))


# ---------------------------------------------------------------- 정답지 대조에서 나온 결함(고친 것은 일반 시험, 남은 것은 xfail)

def _require(ok):
    """xfail 시험의 전제. 전제가 틀리면 예상한 실패(AssertionError)가 아니라 오류로 드러나게 한다."""
    if not ok:
        raise RuntimeError("xfail 시험의 전제가 맞지 않는다")


def test_final_return_without_preliminary_return_notes_the_penalty():
    """예정신고를 하지 않은 확정신고 신고값은 가산세를 넣었다는 것, 감면이 적용되지 않을 때의 금액, 다루지 않는 경우를
    확인사항에 싣는다."""
    k = KEYS["09-8"]
    r, rv = _run("09-8")
    want = k["현행가산세"]
    _require(rv["신고"]["구분"] == "확정")
    notes = rv["확인사항"]
    # 문장의 금액은 천 단위 쉼표로 적는다(1,587,738원)
    assert any("예정신고를 하지 않은 확정신고" in m and "무신고가산세 %s원" % format(want["무신고"], ",") in m
               and "납부지연가산세 %s원" % format(want["납부지연"], ",") in m for m in notes)
    assert any("본지 ⑯" in m and "%s원" % format(want["계"], ",") in m for m in notes)
    assert any("감면 없이" in m and "감면이 적용되면" in m and "%s원" % format(want["무신고_감면적용"], ",") in m
               and "2026-01-01" in m for m in notes)
    assert "1,587,738원" in " ".join(notes) and "1587738" not in " ".join(notes)
    assert any("부정행위" in m and "다루지 않는다" in m for m in notes)
    assert not any("계산하지 않아 0 으로 두었으므로" in m for m in notes)


def test_final_return_without_preliminary_return_penalty_in_form_matches_hand_calculation():
    """본지 ⑯ 가산세와 ⑱ 납부할 세액(계획 2 에서 xfail 로 남겼던 결함). 원문 서식은 2022년 귀속 세율표와 2023-05-31 납부로
    847,869 · 335,360 · 1,183,229, 납부할 세액 9,661,921 이다(무신고가산세에 50% 감면을 적용했다). 현행 기대값은 규칙세트의
    율·세율로 손계산했고 지금 문언에 따라 감면을 적용하지 않는다(references/정답지.md 「가산세 대조」):
    1,587,738 · 312,000 · 1,899,738, 납부할 세액 7,938,692 + 1,899,738 = 9,838,430."""
    k = KEYS["09-8"]
    r, rv = _run("09-8")
    want, src = k["현행가산세"], k["원문가산세"]
    _require(rv["신고"]["구분"] == "확정")
    _require(k["원문"]["산출세액"] + src["계"] == src["납부할세액"])       # 원문 ⑰ = ⑩ + ⑮ (공제와 기신고세액이 없다)
    _require(k["현행"]["산출세액"] + want["계"] == want["납부할세액"] == 9_838_430)
    cols = rv["본지"]["열"]
    # 원문은 합계, 국내분 소계, 세율구분 열에 모두 적었다(행 1859~1862)
    for name in ("합계", "국내소계"):
        c = cols[name]
        assert (c["가산세_신고"], c["가산세_납부"], c["가산세_기장"], c["가산세"]) == \
            (want["무신고"], want["납부지연"], 0, want["계"]), name
    for label, x in want["열"].items():
        c = cols[label]
        assert (c["가산세_신고"], c["가산세_납부"], c["가산세"]) == (x["무신고"], x["납부지연"], x["무신고"] + x["납부지연"]), label
    t = cols["합계"]
    assert t["납부할세액"] == want["납부할세액"]
    assert (t["전자신고공제"], t["기신고세액"], t["분납"], t["신고기한내납부"]) == (0, 0, 0, want["납부할세액"])
    assert rv["가산세"]["계산"] is True and rv["가산세"]["감면적용"] is False
    assert rv["가산세"]["무신고_감면적용"] == want["무신고_감면적용"]
    assert [{key: c[key] for key in want["건"][0]} for c in rv["가산세"]["건"]] == want["건"]


def test_final_return_penalty_matches_hand_calculation():
    """예정신고를 하지 않은 확정신고(사례 09 하위 8)의 가산세. penalty.final_return 이 원문 방식과 규칙세트의 율·세율로 손계산한
    기대값과 같다. 신고값은 이 값을 본지와 03 레코드에 옮긴다(위 시험)."""
    k = KEYS["09-8"]
    r, _ = _run("09-8")
    want = k["현행가산세"]
    _require(want["계"] == want["무신고"] + want["납부지연"] and want["계"] != k["원문가산세"]["계"])
    got = penalty.final_return(r, k["facts"], k["filer"]["신고"]["작성일"])
    assert (got["무신고"], got["납부지연"], got["계"]) == (want["무신고"], want["납부지연"], want["계"])
    assert [{key: c[key] for key in want["건"][0]} for c in got["건"]] == want["건"]
    assert got["열"] == want["열"]
    # 예정신고분을 기한 후 신고로 내 감면이 적용되면 무신고가산세는 절반이다. 결과와 확인사항이 그 금액을 싣는다
    assert got["감면적용"] is False and got["무신고_감면적용"] == want["무신고_감면적용"]
    assert any("감면이 적용되면" in m and "%s원" % format(want["무신고_감면적용"], ",") in m for m in got["확인사항"])
    assert got["양도일별"] is None                      # A·B 는 같은 날 양도라 대안 계산이 없다


def test_penalty_method_reproduces_source_amounts_to_the_won():
    """원문이 적은 건별 세액과 일수(2022년 귀속 세율표, 납부일까지 센 일수)를 같은 계산식에 넣으면 원문 서식 ⑮ 의 합계와
    열별 값이 원 단위까지 나온다. 율(무신고 20% × 50%, 1일 10만분의 22)은 원문과 지금 규칙세트가 같다."""
    src = KEYS["09-8"]["원문가산세"]
    rs = ruleset.load()
    on = KEYS["09-8"]["filer"]["신고"]["작성일"]
    total, per_case, late = penalty.amounts([c["예정신고세액"] for c in src["건"]], [c["일수"] for c in src["건"]],
                                            rs.value("가산세.무신고.율", on), rs.value("가산세.무신고.확정신고감면율", on),
                                            rs.value("가산세.납부지연.일이자율", on))
    assert (total, sum(late), total + sum(late)) == (src["무신고"], src["납부지연"], src["계"])
    assert per_case == [c["무신고"] for c in src["건"]] and late == [c["납부지연"] for c in src["건"]]
    assert src["열"] == {"1-10": {"무신고": per_case[0], "납부지연": late[0]}, "1-20": {"무신고": per_case[1], "납부지연": late[1]}}


def test_short_holding_house_gets_no_temporary_exclusion_hint():
    """보유 2년 미만 주택(사례 08)에는 한시배제 안내가 붙지 않는다(시행령 제167조의3①12호의2 본문: 보유 2년 이상)."""
    r, _ = _run("08")
    _require(r["계산"]["자산"][0]["판정"]["보유년"] < 2)
    assert not any("한시배제" in m for m in r["확인사항"])


def test_late_preliminary_return_is_not_built_as_regular_return():
    """1월 양도분의 예정신고 기한(2026-03-31, 화요일)을 지난 작성일은 기한후신고라 Unsupported 다. 기한 당일은 정기신고다."""
    k = KEYS["01"]
    r, _ = _run("01")
    _require(r["계산"]["자산"][0]["판정"]["양도일"] == "2026-01-15")
    on_time = copy.deepcopy(k["filer"])
    on_time["신고"]["작성일"] = "2026-03-31"
    assert return_values.build(r, k["facts"], filing.load(on_time))["신고"]["상세코드"] == "01"
    late = copy.deepcopy(k["filer"])
    late["신고"]["작성일"] = "2026-04-01"
    with pytest.raises(return_values.Unsupported, match="2026-03-31"):
        return_values.build(r, k["facts"], filing.load(late))
    late["신고"]["작성일"] = "2026-06-30"
    with pytest.raises(return_values.Unsupported, match="기한후신고"):
        return_values.build(r, k["facts"], filing.load(late))
