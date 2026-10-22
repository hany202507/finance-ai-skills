"""DSD 푸팅 연결 후보(2026-10-22, 실행 시간 점검 P1). 엔진이 금액을 보지 않고 위치 · 이름 · XBRL 코드로 후보를 내고,
AI 는 연결.json 의 proposals 에 후보 번호로 O · X · 고침을 적는다. 시험 자료는 합성 dsd · xml 이고 값은 모두 가상이다."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "scripts"))

from dsd_fixture import make_dsd  # noqa: E402

import run  # noqa: E402
from audit.report import dsd_ai as A  # noqa: E402
from audit.report import dsd_grid as G  # noqa: E402
from audit.report import dsd_links as L  # noqa: E402
from audit.report import dsd_propose as P  # noqa: E402



def cli(argv):
    return run.main(argv[1:])          # 공개본 실행기는 dsd 하위 명령만 받는다

def _doc(tmp_path, name="a.dsd", **kw):
    return G.read_grid(make_dsd(tmp_path / name, **kw))


def _texts(props):
    return {A.proposal_text(x) for x in props}


def test_proposals_by_name_and_position(tmp_path):
    got = _texts(P.proposals(_doc(tmp_path)))
    assert "주석2-1 「합 계」 · 「기말」 = 재무상태표 「유형자산」 · 「당기」 [주석 열]" in got        # 변동표 기말 = 재무상태표 당기(과목이 주석 2 를 가리킴)
    assert "주석2-1 「합 계」 · 「기초」 = 재무상태표 「유형자산」 · 「전기」 [주석 열]" in got
    assert "주석3-1 「합 계」 · 「당기말」 = 재무상태표 「매출채권」 · 「당기」 [주석 열]" in got
    assert "주석3-1 「합 계」 · 「전기말」 = 재무상태표 「매출채권」 · 「전기」 [주석 열]" in got
    assert any(t.startswith("자본변동표 「1.1(당기초)」 · 「자 본 금」 = 재무상태표 「자본금」 · 「전기」") for t in got)
    assert not any("「매출채권」 · 「당기말」 = 재무상태표" in t for t in got)          # 합계 줄이 있는 표의 내역 한 줄은 내지 않는다
    assert not any("현금흐름표 「당기순이익」" in t and "자본변동표" in t for t in got)    # 순이익은 손익계산서에만 잇는다


def test_proposals_ignore_amounts(tmp_path):
    """금액을 바꾼 판에서도 후보가 같다. 금액이 같다는 것을 근거로 쓰지 않는다(3단계 반려)."""
    a = P.proposals(_doc(tmp_path))
    b = P.proposals(_doc(tmp_path, "b.dsd", ppe_total_end="901", ar_total="999", bs_ppe="905"))
    assert a == b and a


def test_apply_o_x_edit(tmp_path):
    doc = _doc(tmp_path)
    props = P.proposals(doc)
    ids = [x["id"] for x in props]
    ar = next(x["id"] for x in props if A.proposal_text(x).startswith("주석3-1 「합 계」 · 「당기말」"))
    rest = [i for i in ids if i not in (ids[0], ar)]
    patch = {"proposals": {"O": rest, "X": {ids[0]: "가상 시험의 이유"},
                           "고침": [{"id": ar, "right": [{"table": "재무상태표", "row": "매출채권", "col": "당기"}], "grade": "약함"}]}}
    defs, problems = A.apply(doc, {}, patch)
    assert problems == []
    via = [x for x in defs["links"] if x.get("via")]
    assert len(via) == len(ids) - 1 and all(x["source"] == "AI" and x["confirmed"] is False for x in via)
    edited = next(x for x in via if x["via"] == ar)
    assert edited["grade"] == "약함" and "엔진 후보를 고침" in edited["basis"]
    assert any(s["what"].startswith(f"엔진 후보 {ids[0]}:") and s["why"] == "가상 시험의 이유" for s in defs["skipped"])
    assert set(defs["proposal_marks"].values()) == {"O", "X", "고침"} and len(defs["proposal_marks"]) == len(ids)
    checks, _, _ = L.build(doc, defs)
    L.evaluate(doc, checks)
    bad = [c for c in checks if c.source == "AI" and c.group == "레퍼" and not c.ok]
    assert bad and all(c.c == 3 and c.table == "주석2-1" for c in bad)      # 변동표의 감가상각비 (88) = 손익계산서 88: 부호를 AI 가 고칠 후보


def test_apply_takes_unmarked_proposals_by_default(tmp_path):
    """판정을 적지 않은 후보는 기본으로 연결이 된다(2026-10-22 결정). AI 는 X · 고침만 적는다."""
    doc = _doc(tmp_path)
    ids = [x["id"] for x in P.proposals(doc)]
    defs, problems = A.apply(doc, {}, {"proposals": {"O": ids[1:]}})
    assert problems == [] and defs["proposal_marks"][A._psig(doc, P.proposals(doc)[0])] == "기본"
    first = next(x for x in defs["links"] if x.get("via") == ids[0])
    assert "판정 없이 넣음" in first["basis"] and first["confirmed"] is False
    defs, problems = A.apply(doc, {}, {"proposals": {"X": {ids[0]: "가상 시험의 이유"}}})      # X 만 적어도 나머지는 들어간다
    assert problems == [] and len([x for x in defs["links"] if x.get("via")]) == len(ids) - 1
    defs, problems = A.apply(doc, {}, {"links": []})                                          # proposals 를 아예 적지 않아도 기본으로 들어간다
    assert problems == [] and len([x for x in defs["links"] if x.get("via")]) == len(ids)
    _, problems = A.apply(doc, {}, {"proposals": {"O": ids + ["P9999"]}})
    assert any("P9999" in x for x in problems)
    _, problems = A.apply(doc, {}, {"proposals": {"O": ids, "X": {ids[0]: "이유"}}})
    assert any("두 번" in x for x in problems)
    _, problems = A.apply(doc, {}, {"proposals": {"O": ids[1:], "X": {ids[0]: ""}}})
    assert any("이유" in x for x in problems)
    defs, problems = A.apply(doc, {}, {"proposals": {"O": [f"{ids[0]}-{ids[-1]}"]}})      # 이어진 번호는 범위로
    assert problems == [] and len([x for x in defs["links"] if x.get("via")]) == len(ids)


def test_apply_with_null_proposals_keeps_old_behavior(tmp_path):
    """"proposals": null 이면 후보를 넣지 않고 예전처럼 links 만 넣는다."""
    doc = _doc(tmp_path)
    patch = {"links": [{"left": {"table": "주석3-1", "row": "합 계", "col": "당기말"}, "right": [{"table": "재무상태표", "row": "매출채권", "col": "당기"}],
                        "basis": "주석 3 합계"}], "proposals": None}
    defs, problems = A.apply(doc, {}, patch)
    assert problems == [] and len(defs["links"]) == 1 and defs["proposal_marks"] == {}


def test_hand_link_same_as_proposal_counted_once(tmp_path):
    doc = _doc(tmp_path)
    x = P.proposals(doc)[0]
    hand = {"left": x["left"], "right": x["right"], "basis": "AI 가 직접 적은 같은 연결"}
    defs, problems = A.apply(doc, {}, {"links": [hand]})
    assert problems == []
    sigs = [A._sig(A._ref_of(doc, l["left"])) + "=" + "+".join(A._sig(A._ref_of(doc, r)) for r in l["right"]) for l in defs["links"]]
    assert len(sigs) == len(set(sigs))                                                       # 같은 두 칸은 한 번만 검증한다


def test_add_counts_earlier_marks(tmp_path):
    doc = _doc(tmp_path)
    ids = [x["id"] for x in P.proposals(doc)]
    defs, problems = A.apply(doc, {}, {"proposals": {"O": ids[:-1], "X": {ids[-1]: "이유"}}})
    assert problems == []
    more, problems = A.apply(doc, defs, {"links": [], "proposals": {}}, add=True)
    assert problems == [] and len(more["proposal_marks"]) == len(ids)


def test_cli_links_writes_proposals(tmp_path, capsys):
    src = make_dsd(tmp_path / "a.dsd")
    out = tmp_path / "out"
    assert cli(["dsd", "links", str(src), "--out", str(out)]) == 0
    req = json.loads((out / "dsd_연결요청.json").read_text(encoding="utf-8"))
    assert req["proposals"] and all(x["id"].startswith("P") for x in req["proposals"])
    reading = (out / "dsd_읽기자료.md").read_text(encoding="utf-8")
    assert "후보 P0001:" in reading
    assert "엔진 연결 후보" in capsys.readouterr().out
    patch = tmp_path / "연결.json"
    patch.write_text(json.dumps({"proposals": {"O": [x["id"] for x in req["proposals"]]}}, ensure_ascii=False), encoding="utf-8")
    assert cli(["dsd", "links", str(src), "--apply", str(patch), "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert f"엔진 후보 {len(req['proposals'])}건: 판정 없이 넣음 0 · O {len(req['proposals'])} · X 0 · 고침 0" in printed
    req = json.loads((out / "dsd_연결요청.json").read_text(encoding="utf-8"))
    assert all(x.get("mark") == "O" for x in req["proposals"])
    assert "후보 P0001 (O):" in (out / "dsd_읽기자료.md").read_text(encoding="utf-8")


# ---- XBRL ------------------------------------------------------------------------------------------

ENT = "_ifrs-full_ConsolidatedAndSeparateFinancialStatementsAxis_ifrs-full_SeparateMember"
RA = "_ifrs-full_CarryingAmountAccumulatedDepreciationAmortisationAndImpairmentAndGrossCarryingAmountAxis_dart_ReportedAmountMember"


def _te(v, code="", ctx="", neg=False):
    a = f' ACODE="{code}" ACONTEXT="{ctx}"' if code else ""
    return f'<TE{a}{" ANEGATED=" + chr(34) + "Y" + chr(34) if neg else ""}>{v}</TE>'


def _fin(head, rows):
    body = "".join("<TR>" + _te(lab) + "".join(_te(v, c, x, n) for v, c, x, n in cells) + "</TR>" for lab, cells in rows)
    return (f'<TABLE ACLASS="FINANCE" BORDER="1"><THEAD><TR><TH>과 목</TH>{"".join(f"<TH>{h}</TH>" for h in head)}</TR></THEAD>'
            f"<TBODY>{body}</TBODY></TABLE>")


def _norm_table(head, rows):
    th = "".join(f"<TH>{h}</TH>" for h in head)
    body = "".join("<TR><TD>" + lab + "</TD>" + "".join(f'<TD ACODE="{c}" ACONTEXT="{x}"{" ANEGATED=" + chr(34) + "Y" + chr(34) if n else ""}>{v}</TD>' for v, c, x, n in cells) + "</TR>"
                   for lab, cells in rows)
    return f'<TABLE ACLASS="NORMAL" BORDER="1"><THEAD><TR>{th}</TR></THEAD><TBODY>{body}</TBODY></TABLE>'


def _xbrl_xml(tmp_path) -> Path:
    unit = '<TABLE BORDER="0"><TBODY><TR><TD>(단위 : 백만원)</TD></TR></TBODY></TABLE>'
    group = lambda title, table: f"<TABLE-GROUP><TITLE>{title}</TITLE>{unit}{table}</TABLE-GROUP>"      # noqa: E731
    bs = _fin(["제 2 기말", "제 1 기말"], [
        ("현금및현금성자산", [("50", "ifrs-full_CashAndCashEquivalents", "CFY2026eFY" + ENT, False), ("40", "ifrs-full_CashAndCashEquivalents", "PFY2025eFY" + ENT, False)]),
        ("재고자산", [("70", "ifrs-full_Inventories", "CFY2026eFY" + ENT, False), ("60", "ifrs-full_Inventories", "PFY2025eFY" + ENT, False)]),
        ("자산총계", [("120", "ifrs-full_Assets", "CFY2026eFY" + ENT, False), ("100", "ifrs-full_Assets", "PFY2025eFY" + ENT, False)])])
    cf = _fin(["제 2 기", "제 1 기"], [
        ("기초현금및현금성자산", [("40", "ifrs-full_CashAndCashEquivalentsAtBeginningOfPeriodCf", "CFY2026eFY" + ENT, False),
                                  ("30", "ifrs-full_CashAndCashEquivalentsAtBeginningOfPeriodCf", "PFY2025eFY" + ENT, False)])])
    n1 = _norm_table(["구분", "공시금액"], [
        ("Opening stock", [("60", "ifrs-full_Inventories", "PFY2025eFY" + ENT + RA, False)]),
        ("Closing stock", [("70", "ifrs-full_Inventories", "CFY2026eFY" + ENT + RA, False)]),
        ("Dep. charge", [("5", "ifrs-full_DepreciationExpense", "CFY2026dFY" + ENT + RA, True)])])
    n2 = _norm_table(["구분", "공시금액"], [("Nature dep.", [("5", "ifrs-full_DepreciationExpense", "CFY2026dFY" + ENT + RA, False)])])
    xml = ('<?xml version="1.0" encoding="utf-8"?>\n<DOCUMENT><BODY><SECTION-1 ACLASS="MANDATORY"><TITLE ATOC="Y">(첨부)재 무 제 표</TITLE>'
           + group("재 무 상 태 표", bs) + group("현 금 흐 름 표", cf)
           + '<SECTION-2 ACLASS="MANDATORY"><TITLE ATOC="Y">주석</TITLE>'
           + '<P USERMARK="B">1. 영업 자산</P><P>내역은 다음과 같습니다.</P>' + unit + n1
           + '<P USERMARK="B">2. 비용</P><P>내역은 다음과 같습니다.</P>' + unit + n2
           + "</SECTION-2></SECTION-1></BODY></DOCUMENT>")
    p = tmp_path / "x.xml"
    p.write_text(xml, encoding="utf-8")
    return p


def test_xbrl_tags_are_read(tmp_path):
    doc = G.read_grid(_xbrl_xml(tmp_path))
    t = doc.table("재무상태표")
    assert t.xbrl[(1, 1)] == ("ifrs-full_Inventories", "CFY2026eFY" + ENT, False)
    assert doc.table("주석1-1").xbrl[(2, 1)][2] is True                 # ANEGATED="Y"


def test_xbrl_proposals(tmp_path):
    got = {A.proposal_text(x): x for x in P.proposals(G.read_grid(_xbrl_xml(tmp_path)))}
    assert "주석1-1 「Closing stock」 · 「공시금액」 = 재무상태표 「재고자산」 · 「당기」 [XBRL]" in got        # 「공시금액」 차원은 뗀다
    assert "주석1-1 「Opening stock」 · 「공시금액」 = 재무상태표 「재고자산」 · 「전기」 [XBRL]" in got
    assert "주석2-1 「Nature dep.」 · 「공시금액」 = -주석1-1 「Dep. charge」 · 「공시금액」 [XBRL]" in got     # 한쪽만 부호를 뒤집어 보였다
    assert "현금흐름표 「기초현금및현금성자산」 · 「당기」 = 재무상태표 「현금및현금성자산」 · 「전기」 [XBRL]" in got   # 기초 잔액 코드 = 전기말


@pytest.mark.parametrize("code,ctx,want", [
    ("ifrs-full_Inventories", "CFY2026eHYA" + ENT + RA, ("Inventories", "C.e", ())),
    ("ifrs-full_Inventories", "PFY2025eHY" + ENT, ("Inventories", "P.e", ())),           # 반기보고서의 전기말
    ("ifrs-full_Inventories", "PFY2025eHYA" + ENT, ("Inventories", "Ph.e", ())),         # 작년 같은 반기 말
    ("ifrs-full_Revenue", "CFY2026dHYQ" + ENT, ("Revenue", "C.q", ())),
    ("dart_EquityAtBeginningOfPeriod", "CFY2026dHYA" + ENT + "_ifrs-full_ComponentsOfEquityAxis_ifrs-full_IssuedCapitalMember",
     ("Equity", "P.e", (("ComponentsOfEquityAxis", "IssuedCapitalMember"),))),
    ("ifrs-full_BasicEarningsLossPerShare", "CFY2026dHYA" + ENT + "_ifrs-full_ClassesOfShareCapitalAxis_ifrs-full_OrdinarySharesMember",
     ("BasicEarningsLossPerShare", "C.d", ())),                                         # 손익계산서 주당이익 = 보통주
])
def test_fact(code, ctx, want):
    assert P._fact(code, ctx) == want


def test_member_fact_only_for_equity_and_classes():
    eq = P._fact("ifrs-full_Equity", "CFY2026eFY" + ENT + "_ifrs-full_ComponentsOfEquityAxis_ifrs-full_RetainedEarningsMember")
    assert P._member_fact(eq) == ("RetainedEarnings", "C.e", ())
    dep = P._fact("ifrs-full_DepreciationExpense", "CFY2026dFY" + ENT + "_ifrs-full_AttributionOfExpensesByNatureToTheirFunctionAxis_ifrs-full_CostOfSalesMember")
    assert P._member_fact(dep) is None                                     # 감가상각비의 매출원가 배분은 매출원가가 아니다


# ---- 2차(10-22): 회사별 표 · 이름 짝 · 문장 ------------------------------------------------------------

def _tab(head, rows):
    """칸이 (값, XBRL 코드, 문맥, 부호 뒤집음) 이거나 글자인 NORMAL 표."""
    def td(v):
        if isinstance(v, tuple):
            val, code, ctx, neg = v
            return f'<TD ACODE="{code}" ACONTEXT="{ctx}"{" ANEGATED=" + chr(34) + "Y" + chr(34) if neg else ""}>{val}</TD>'
        return f"<TD>{v}</TD>"
    th = "".join(f"<TH>{h}</TH>" for h in head)
    body = "".join("<TR><TD>" + lab + "</TD>" + "".join(td(v) for v in cells) + "</TR>" for lab, cells in rows)
    return f'<TABLE ACLASS="NORMAL" BORDER="1"><THEAD><TR>{th}</TR></THEAD><TBODY>{body}</TBODY></TABLE>'


def _second_xml(tmp_path, name="s.xml", a=(10, 20, 5, 7, 40, 3, 30, 50, 9, 6), xbrl=True) -> Path:
    """회사별 표 · 이름 짝 · 문장 후보를 시험할 합성 반기 원문. a 는 금액이고 후보는 a 에 따라 바뀌지 않아야 한다."""
    unit = '<TABLE BORDER="0"><TBODY><TR><TD>(단위 : 백만원)</TD></TR></TBODY></TABLE>'
    group = lambda title, table: f"<TABLE-GROUP><TITLE>{title}</TITLE>{unit}{table}</TABLE-GROUP>"      # noqa: E731
    c, ent = "CFY2026dHYA", ENT
    x = (lambda v, code, neg=False: (v, code, c + ent, neg)) if xbrl else (lambda v, code, neg=False: v)      # noqa: E731
    cf = _fin(["제 2 기 반기", "제 1 기 반기"], [("유형자산의 취득", [(f"({a[4]})", "ifrs-full_PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities", c + ent, True),
                                                             ("(1)", "ifrs-full_PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities", "PFY2025dHYA" + ent, True)])]) \
        if xbrl else _fin(["제 2 기 반기", "제 1 기 반기"], [("유형자산의 취득", [(f"({a[4]})", "", "", False), ("(1)", "", "", False)])])
    related = (_tab(["", "범주 종속기업 가사", "범주 종속기업 기타", "범주 관계기업 나사", "범주 관계기업 다사"],
                    [("매출", [a[0], a[1], a[2], a[3]]), ("매입", [1, 2, 3, 4])])
               + "<P>당반기 (단위 : 백만원)</P>"
               + _tab(["", "범주 종속기업", "범주 관계기업"], [("매출", [a[0] + a[1], a[2] + a[3]]), ("매입", [3, 7])]))
    ppe = _tab(["", "공시금액"], [("기초 유형자산", [x(100, "ifrs-full_PropertyPlantAndEquipment")]),
                                  ("일반취득 및 자본적지출, 유형자산", [x(a[4], "ifrs-full_AdditionsOtherThanThroughBusinessCombinationsPropertyPlantAndEquipment")]),
                                  ("감가상각비, 유형자산", [x(f"({a[5]})", "ifrs-full_DepreciationPropertyPlantAndEquipment", True)]),
                                  ("반기말 유형자산", [x(137, "ifrs-full_PropertyPlantAndEquipment")])])
    nature = _tab(["", "공시금액 누적"], [("성격별 비용 감가상각비", [x(a[5], "ifrs-full_DepreciationExpense")]),
                                         ("성격별 비용 퇴직급여", [x(a[8], "ifrs-full_PostemploymentBenefitExpense")])])
    db = _tab(["", "합계"], [("당기근무원가, 확정급여제도", [x(a[9], "ifrs-full_CurrentServiceCostDefinedBenefitPlans")]),
                            ("퇴직급여비용 합계, 확정급여제도", [x(a[9], "ifrs-full_PostemploymentBenefitExpenseDefinedBenefitPlans")])])
    capital = _tab(["", "보통주", "우선주", "주식의 종류 합계"], [
        ("발행할 주식의 총수(단위: 주)", ["", "", 1000]),
        ("발행주식 액면 총액(백만원)", [a[6] - 10, 10, a[6]]),
        ("납입자본금(백만원)", ["", "", a[7]]),
        ("자본금에 대한 설명", ["", "", f"발행주식의 액면총액은 {a[6]}백만원(보통주 {a[6] - 10}백만원, 우선주 10백만원)으로 이익소각으로 인하여 납입자본금 {a[7]}백만원과 상이합니다."]),
        ("주식에 대한 설명", ["", "", "발행할 주식의 총수는 1,000주(1주의 액면금액: 5,000원)입니다."])])
    notes = [("특수관계자", "<P>당반기 (단위 : 백만원)</P>" + related), ("유형자산", ppe), ("비용의 성격별 분류", nature),
             ("순확정급여부채", db), ("자본금", capital)]
    body = "".join(f'<P USERMARK="B">{k}. {title}</P><P>내역은 다음과 같습니다.</P>{unit}{t}' for k, (title, t) in enumerate(notes, 1))
    xml = ('<?xml version="1.0" encoding="utf-8"?>\n<DOCUMENT><BODY><SECTION-1 ACLASS="MANDATORY"><TITLE ATOC="Y">(첨부)반 기 재 무 제 표</TITLE>'
           + group("현 금 흐 름 표", cf) + '<SECTION-2 ACLASS="MANDATORY"><TITLE ATOC="Y">주석</TITLE>' + body + "</SECTION-2></SECTION-1></BODY></DOCUMENT>")
    p = tmp_path / name
    p.write_text(xml, encoding="utf-8")
    return p


def test_group_proposals_sum_company_columns(tmp_path):
    doc = G.read_grid(_second_xml(tmp_path))
    got = [x for x in P.proposals(doc) if x["how"] == "회사별 표"]
    assert len(got) == 4                                                   # 줄 둘 × 범주 둘
    sub = next(x for x in got if x["left"]["row"] == "매출" and x["left"]["col"] == "범주 종속기업")
    assert [r["col"] for r in sub["right"]] == ["범주 종속기업 가사", "범주 종속기업 기타"] and sub["grade"] == "항등식"
    rel = next(x for x in got if x["left"]["row"] == "매출" and x["left"]["col"] == "범주 관계기업")
    assert rel["grade"] == "조건부" and rel["when"]                        # 범주에 「기타」 열이 없으면 회사를 다 담았는지 모른다
    assert "열 이름이 「범주 종속기업」 로 시작하는 2칸의 합 [회사별 표]" in A.proposal_text(sub)
    defs, problems = A.apply(doc, {}, {"proposals": {"O": [x["id"] for x in P.proposals(doc)]}})
    assert problems == []
    checks, _, _ = L.build(doc, defs)
    L.evaluate(doc, checks)
    multi = [c for c in checks if c.source == "AI" and len(c.terms) == 2 and c.table.startswith("주석1")]
    assert len(multi) == 4 and all(c.ok for c in multi)


def test_pair_proposals_xbrl_sign(tmp_path):
    texts = _texts(P.proposals(G.read_grid(_second_xml(tmp_path))))
    assert any(t.startswith("주석2-1 「일반취득 및 자본적지출, 유형자산」 · 「공시금액」 = -현금흐름표 「유형자산의 취득」 · 「당기」 [이름 짝 · 조건부") for t in texts)
    assert any(t.startswith("주석2-1 「감가상각비, 유형자산」 · 「공시금액」 = -주석3-1 「성격별 비용 감가상각비」") for t in texts)      # ANEGATED 로 부호를 정한다
    assert any(t.startswith("주석3-1 「성격별 비용 퇴직급여」 · 「공시금액 누적」 = 주석4-1 「퇴직급여비용 합계, 확정급여제도」 · 「합계」 [이름 짝 · 조건부") for t in texts)
    plain = _texts(P.proposals(G.read_grid(_second_xml(tmp_path, "n.xml", xbrl=False))))
    assert any(t.startswith("주석2-1 「감가상각비, 유형자산」 · 「공시금액」 = 주석3-1 「성격별 비용 감가상각비」") for t in plain)       # XBRL 이 없으면 같은 부호(AI 가 고친다)


def test_sentence_proposals_name_before_amount(tmp_path):
    got = {x["left"].get("row_nth", 1): x["right"][0] for x in P.proposals(G.read_grid(_second_xml(tmp_path))) if x["how"] == "문장"}
    assert {k: (v["row"], v["col"]) for k, v in got.items()} == {
        1: ("발행주식 액면 총액(백만원)", "주식의 종류 합계"),
        2: ("발행주식 액면 총액(백만원)", "보통주"),                       # 열 이름만 있으면 앞 금액의 줄을 잇는다
        3: ("발행주식 액면 총액(백만원)", "우선주"),
        4: ("납입자본금(백만원)", "주식의 종류 합계")}                       # 「총수는 1,000주(1주의 액면금액: 5,000원)」 은 이름 뒤에 다른 숫자가 있어 내지 않는다


def test_second_proposals_ignore_amounts(tmp_path):
    a = P.proposals(G.read_grid(_second_xml(tmp_path)))
    b = P.proposals(G.read_grid(_second_xml(tmp_path, "b.xml", a=(11, 23, 8, 2, 77, 4, 31, 52, 1, 2))))
    assert a == b and {x["how"] for x in a} >= {"회사별 표", "이름 짝", "문장"}
