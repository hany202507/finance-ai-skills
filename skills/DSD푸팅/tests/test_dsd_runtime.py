"""DSD 푸팅 실행 시간 고침(2026-10-22). 시험 자료는 모두 합성이다.

P2 판정자료의 근거 묶음, P3 문장읽기 줄이기, P4 전기 대사의 XBRL 항목 · 표현 차이 사전, P5 판독 캐시 · 글꼴 재사용, P6 읽기 자료 줄이기, P7 dsd fetch.
"""
from __future__ import annotations

import io
import json
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "scripts"))

import run  # noqa: E402
from audit.report import dart_fetch as F  # noqa: E402
from audit.report import dsd_ai as A  # noqa: E402
from audit.report import dsd_compare as C  # noqa: E402
from audit.report import dsd_diff as D  # noqa: E402
from audit.report import dsd_grid as G  # noqa: E402
from audit.report import dsd_links as L  # noqa: E402
from audit.report import dsd_text as T  # noqa: E402
from audit.report import dsd_verify as V  # noqa: E402



def cli(argv):
    return run.main(argv[1:])          # 공개본 실행기는 dsd 하위 명령만 받는다

def _tab(tid, header, rows, labels=None, xbrl=None):
    return G.Table(tid, "", 1, header, rows, [[None] + [G.to_num(x) for x in r[1:]] for r in rows], labels=labels, xbrl=xbrl)


def _doc(parts, name="mini"):
    return G.Doc(name, "", [G.Part(k, title, [("t", x) if isinstance(x, G.Table) else ("p", x) for x in items]) for k, title, items in parts])


def _prior(new, old):
    out, lost = L.prior_checks(new, old, C.match(new, old))
    return {(c.table, c.r, c.c): c.terms[0][:3] for c in out}, lost


# ---------------------------------------------------------------- P4 전기 대사
def test_xbrl_prior_context():
    """올해 전기 문맥 P → 작년 C, BP → P. 반기 · 분기의 비교 연도 말 · 연간 문맥은 사업보고서의 FY 로도 찾는다."""
    assert L.xbrl_prior(("A", "PFY2025eHY_X_Y")) == [("A", "CFY2025eHY_X_Y"), ("A", "CFY2025eFY_X_Y")]
    assert L.xbrl_prior(("A", "PFY2025dHYA_X", False)) == [("A", "CFY2025dHYA_X")]
    assert L.xbrl_prior(("A", "BPFY2024eHY")) == [("A", "PFY2024eHY"), ("A", "PFY2024eFY")]
    assert L.xbrl_prior(("A", "PFY2024eFY")) == [("A", "CFY2024eFY")]
    assert L.xbrl_prior(("A", "CFY2026eHYA")) == []


@pytest.mark.parametrize("now,last", [
    ("단기차입금의 순감소", "단기차입금의 순증가(감소)"),
    ("이자수익", "이자수익(금융수익)"),
    ("장기차입금의 차입", "사채 및 장기차입금의 차입"),
    ("기타포괄손익-공정가치금융자산의 처분", "기타포괄손익-공정가치측정금융자산의처분"),
    ("기타 변동을 통한 증가(감소), 유형자산", "기타 변동에 따른 증가(감소), 유형자산"),
    ("감가상각비, 사용권자산", "사용권자산감가상각비"),
    ("기초 배출권", "기초"),
    ("기말 배출권", "반기말"),
    ("배당금", "지급될 배당금"),
    ("금융자산 합계", "총 금융자산"),
])
def test_prior_alias_pairs(now, last):
    """한 상장사 2026 반기 별도에서 AI 가 prior_pairs 로 적은 짝(10-21)이 표현 차이 사전으로 같은 이름이 된다."""
    assert L.prior_alias(now) == L.prior_alias(last)


def test_prior_alias_keeps_different_names():
    assert L.prior_alias("기말상품재고액") != L.prior_alias("기말")           # 붙여 쓴 과목은 변동표의 기말 줄이 아니다
    assert L.prior_alias("장기차입금의 차입") != L.prior_alias("장기차입금의 상환")
    assert L.prior_alias("단기차입금의 순감소") != L.prior_alias("장기차입금의 순감소")


def _sga(now_salary, last_salary, english=False, xbrl=False):
    """셋째 칸만 다른 줄(판매비와관리비 소계 아래 급여 · 운반비). 줄 키(앞 두 칸)가 같아 이름 짝으로는 못 잇는다.
    english 면 작년 줄 이름을 모두 다르게 적는다(이름으로는 잇지 못한다)."""
    head = ["구분", "", "", "당기", "전기"]
    names = [["판관비 합계", "", ""], ["판관비 합계", "소계", "급여"], ["판관비 합계", "소계", "운반비"]]
    old_names = [["SG&A", "", ""], ["SG&A", "sub", "Salaries"], ["SG&A", "sub", "Freight"]] if english else names
    label = lambda r: " ".join(x for x in r if x)      # noqa: E731
    new = _tab("주석9-1", head, [names[0] + ["320", "300"], names[1] + ["110", now_salary], names[2] + ["60", "40"]], labels=[label(r) for r in names],
               xbrl={(1, 4): ("Salaries", "PFY2025dFY_S"), (2, 4): ("Freight", "PFY2025dFY_S")} if xbrl else None)
    old = _tab("주석9-1", head, [old_names[0] + ["300", "280"], old_names[1] + [last_salary, "90"], old_names[2] + ["45", "30"]],
               labels=[label(r) for r in old_names], xbrl={(1, 3): ("Salaries", "CFY2025dFY_S", False), (2, 3): ("Freight", "CFY2025dFY_S", False)} if xbrl else None)
    return _doc([("주석9", "판매비와관리비", [new])]), _doc([("주석9", "판매비와관리비", [old])])


def test_same_key_rows_paired_by_full_label():
    """줄 키가 같고 금액이 다른 줄(재작성)도 전체 줄 이름이 같으면 잇는다. 금액이 다르니 확인으로 나온다."""
    new, old = _sga("80", "85")
    got, lost = _prior(new, old)
    assert got[("주석9-1", 1, 4)] == ("작년:주석9-1", 1, 3) and got[("주석9-1", 2, 4)] == ("작년:주석9-1", 2, 3)
    assert not lost


def test_xbrl_rows_pair_when_names_differ():
    """줄 이름도 금액도 다르면 이름 짝 · 숫자 짝으로는 못 잇는다. XBRL 항목(코드 · 기간 · 차원)이 같으면 같은 칸이라 잇고, 금액이 다르니 확인이다."""
    new, old = _sga("80", "85", english=True, xbrl=True)
    got, lost = _prior(new, old)
    assert got[("주석9-1", 1, 4)] == ("작년:주석9-1", 1, 3) and got[("주석9-1", 2, 4)] == ("작년:주석9-1", 2, 3)
    assert not lost
    new, old = _sga("80", "85", english=True)
    got, lost = _prior(new, old)
    assert ("주석9-1", 1, 4) not in got and any("판관비 합계 소계 급여" in x["why"] for x in lost)      # XBRL 항목이 없으면 예전처럼 못 찾은 줄


def test_xbrl_overrides_wrong_name_pair():
    """이름 짝이 가리킨 작년 줄의 XBRL 항목이 다르고 같은 항목인 줄이 따로 있으면 그 줄과 견준다."""
    head = ["구분", "당기말", "전기말"]
    new = _doc([("주석4", "기타", [_tab("주석4-1", head, [["기타", "5", "4"]], xbrl={(0, 2): ("OtherAssets", "PFY2025eFY_C")})])])
    old = _doc([("주석4", "기타", [_tab("주석4-1", head, [["기타", "9", "8"], ["기타자산", "4", "3"]],
                                      xbrl={(0, 1): ("OtherLiabilities", "CFY2025eFY_C", False), (1, 1): ("OtherAssets", "CFY2025eFY_C", False)})])])
    got, _ = _prior(new, old)
    assert got[("주석4-1", 0, 2)] == ("작년:주석4-1", 1, 1)


def test_xbrl_fact_found_in_other_prior_table():
    """작년 표 짝에 없는 줄은 작년 보고서 전체에서 같은 XBRL 항목을 찾는다(한 상장사 2026 반기 별도 주석 3-2 기타금융자산)."""
    head = ["구분", "당기말", "전기말"]
    new = _doc([("주석3", "금융상품", [_tab("주석3-1", head, [["현금", "10", "8"], ["기타금융자산", "5", "4"]],
                                          xbrl={(1, 2): ("OtherFinancialAssets", "PFY2025eFY_C")})])])
    old = _doc([("주석3", "금융상품", [_tab("주석3-1", head, [["현금", "8", "7"]])]),
                ("주석9", "기타자산", [_tab("주석9-1", ["구분", "당기말", "전기말"], [["기타", "4", "3"]],
                                          xbrl={(0, 1): ("OtherFinancialAssets", "CFY2025eFY_C", False)})])])
    got, lost = _prior(new, old)
    assert got[("주석3-1", 1, 2)] == ("작년:주석9-1", 0, 1) and not lost


# ---------------------------------------------------------------- P3 문장읽기
def _segs():
    S = T.Seg
    return [S("S1", "주석", "1. 일반", "제목", "1. 일반"), S("S2", "주석", "1. 일반", "표 1 줄", "현금 | 1,000 | 2,000", 1),
            S("S3", "주석", "1. 일반", "표 1 줄", "공시금액", 2), S("S4", "주석", "1. 일반", "문단", "회사는 제조업을 한다.", 1),
            S("S5", "주석", "2. 재고", "표 2 줄", "공시금액", 1), S("S6", "주석", "2. 재고", "표 2 줄", "공시금액 | 30", 2)]


def test_text_reading_drops_number_cells_and_repeats():
    res = {"facts": {}, "candidates": [], "engine": [], "segments": _segs()}
    text = T.reading(res)
    assert "S2 [표 1 줄 1] 현금\n" in text and "1,000" not in text
    assert "S3 [표 1 줄 2] 공시금액 (같은 글 2곳 더: S5, S6)" in text
    assert "S5 [" not in text and "S6 [" not in text and "S1 [제목] **1. 일반**" in text
    got, bad, _ = T.check_ai(_segs(), {"findings": [{"seg": "S6", "quote": "공시금액", "kind": "오타", "fix": "공시 금액", "basis": "띄어쓰기"}]}, [])
    assert len(got) == 1 and not bad                                # 묶인 S번호로 적어도 원문 그대로라 받는다


def test_text_reading_keeps_numbers_in_audit_hours_table():
    """외부감사 실시내용의 인원수 · 감사시간은 숫자 푸팅이 보지 않으니 문장읽기에 숫자까지 둔다(10-22 가온정밀 재기)."""
    S = T.Seg
    segs = [S("S1", "외부감사 실시내용", "", "표 1 줄", "투입 인원수 | 1 | 1 | 3 | 3 | 0 | 0", 1), S("S2", "주석", "1. 일반", "표 1 줄", "현금 | 1,000", 1)]
    text = T.reading({"facts": {}, "candidates": [], "engine": [], "segments": segs})
    assert "S1 [표 1 줄 1] 투입 인원수 | 1 | 1 | 3 | 3 | 0 | 0" in text and "S2 [표 1 줄 1] 현금\n" in text


# ---------------------------------------------------------------- P6 읽기 자료
def test_reading_summarizes_rate_only_and_text_only_tables():
    rate = _tab("주석2-1", ["기업명", "업종", "지분율(%)"], [["가회사", "제조", "100.0"], ["나회사", "판매", "60.0"]])
    words = _tab("주석2-2", ["", "위험"], [["기술", "환율 위험에 노출되어 있습니다"]])
    money = _tab("주석2-3", ["기업명", "장부금액", "지분율(%)"], [["가회사", "1,000", "100.0"]])
    text = A.reading(_doc([("주석2", "종속기업", [rate, words, money])]))
    assert "[주석2-1] 지분율 · 비율만 있는 표. 줄 2개" in text and "나회사 | 판매" not in text
    assert "[주석2-2] 글만 있는 표" in text and "노출되어" not in text
    assert "| 가회사 | 1,000 | 100 |" in text                     # 금액이 하나라도 있으면 그대로 적는다


def test_long_header_prefix_written_once_and_resolved():
    pre = "특수관계자의 범주 모든 특수관계자의 합계"
    head = ["", f"{pre} 가회사", f"{pre} 나회사", f"{pre} 다회사"]
    t = _tab("주석5-1", head, [["매출", "10", "20", "30"]])
    text = A.reading(_doc([("주석5", "특수관계자", [t])]))
    assert f"열 이름 공통 앞부분 「{pre}」" in text and "| 매출 | 10 | 20 | 30 |" in text and "|  | 가회사 | 나회사 | 다회사 |" in text
    assert L.find_col(t, "나회사") == 2 and L.find_col(t, f"{pre} 나회사") == 2
    assert L.col_prefix(["", "당기말 장부금액", "당기말 공정가치", "당기말 합계"]) == ""          # 짧은 앞부분은 그대로 둔다


def test_link_with_cut_column_name_is_applied_with_full_name():
    """읽기 자료의 뗀 열 이름으로 적은 연결도 넣는다. 연결 정의에는 원래 열 이름으로 둔다(한 상장사 반기에서 찾은 결함, 10-22)."""
    pre = "특수관계자의 범주 모든 특수관계자의 합계"
    t = _tab("주석5-1", ["", f"{pre} 가회사", f"{pre} 나회사", f"{pre} 다회사"], [["매출", "10", "20", "30"]])
    s = _tab("주석5-2", ["구분", "금액"], [["가회사 매출", "10"]])
    doc = _doc([("주석5", "특수관계자", [t, s])])
    link = {"left": {"table": "주석5-1", "row": "매출", "col": "가회사"}, "right": [{"table": "주석5-2", "row": "가회사 매출", "col": "금액"}],
            "basis": "주석 5 거래 표와 매출 명세"}
    new, problems = A.apply(doc, {}, {"links": [link]})
    assert problems == [] and new["links"][-1]["left"]["col"] == f"{pre} 가회사"
    assert L._resolve(doc, {"table": "주석5-1", "row": "매출", "col": "나회사", "exact": True}, None)[2] == 2


# ---------------------------------------------------------------- P5 캐시
def test_read_cached_reuses_parse(tmp_path, monkeypatch):
    from dsd_fixture import make_dsd

    src = make_dsd(tmp_path / "a.dsd")
    cache = tmp_path / "cache"
    first = G.read_cached(src, cache)
    assert len(list(cache.glob("*.pkl"))) == 1
    monkeypatch.setattr(G, "read_grid", lambda p: (_ for _ in ()).throw(AssertionError("다시 판독함")))
    again = G.read_cached(src, cache)
    assert [t.nums for t in again.tables()] == [t.nums for t in first.tables()] and again is not first
    again.tables()[0].nums[0][1] = -1                                 # 돌려받은 문서를 고쳐도 캐시는 그대로다
    assert G.read_cached(src, cache).tables()[0].nums[0][1] != -1


def test_font_reused():
    from audit import wp

    assert wp.font(bold=True) is wp.font(bold=True) and wp.font(bold=True) is not wp.font()
    assert wp.font(size=9, color="6B7167").size == 9


# ---------------------------------------------------------------- P2 근거 묶음
def test_pack_has_evidence_bundle():
    head = ["", "공시금액"]
    doc = _doc([("현금흐름표", "현금흐름표", [_tab("현금흐름표", ["", "당기", "전기"], [["유형자산의 취득", "-30", "-20"]])]),
                ("주석7", "유형자산", [_tab("주석7-1", head, [["취득", "25"], ["합계", "25"]]), _tab("주석7-2", head, [["취득", "18"]])])])
    prior = _doc([("주석7", "유형자산", [_tab("주석7-1", head, [["취득", "18"]])])])
    c = L.Check("AI|x", "주석-재무제표", "레퍼", "주석7-1", 0, 1, [("현금흐름표", 0, 1, -1)], None, "현금흐름표 유형자산의 취득", "AI",
                left=25, right=30, ok=False, when="미지급금 변동이 없다")
    p = L.Check("전기|주석7-1", "전기", "전기", "주석7-1", 0, 1, [("작년:주석7-1", 0, 1, 1)], None, "", "규칙", ok=True)
    text = V.pack(doc, [c, p], D.tables(doc, prior), {}, {})
    assert "- 근거 묶음:" in text
    assert "  - 표 줄 [주석7-1] 「취득」: 공시금액 25" in text and "  - 표 줄 [현금흐름표] 「유형자산의 취득」: 당기 -30 · 전기 -20" in text
    assert "  - 같은 주석 [주석7-2] 「취득」: 공시금액 18" in text and "  - 같은 주석 [주석7-1] 「합계」: 공시금액 25" in text
    assert "  - 작년 [작년:주석7-1] 「취득」: 공시금액 18" in text


# ---------------------------------------------------------------- P7 dsd fetch
def _report(rcept, year, total):
    fs = lambda kind, n: (f'<SECTION-2><TITLE>{n}. {kind}재무제표</TITLE><TABLE-GROUP><TITLE>{n}-1. {kind} 재무상태표</TITLE>'      # noqa: E731
                          '<TABLE BORDER="1"><THEAD><TR><TH></TH><TH>당기말</TH><TH>전기말</TH></TR></THEAD><TBODY>'
                          f'<TR><TD>자산총계</TD><TD>{total}</TD><TD>800</TD></TR></TBODY></TABLE></TABLE-GROUP></SECTION-2>'
                          f'<SECTION-2><TITLE>{n + 1}. {kind}재무제표 주석</TITLE><TABLE-GROUP><TITLE>1. 일반적 사항</TITLE><P>회사는 제조업을 한다.</P></TABLE-GROUP></SECTION-2>')
    xml = ('<?xml version="1.0" encoding="utf-8"?><DOCUMENT><DOCUMENT-NAME ACODE="11012">반기보고서</DOCUMENT-NAME>'
           '<COMPANY-NAME AREGCIK="00000001">가온정밀(가상)</COMPANY-NAME><BODY><SECTION-1><TITLE>III. 재무에 관한 사항</TITLE>'
           + fs("연결", 2) + fs("", 4) + "</SECTION-1></BODY></DOCUMENT>")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(f"{rcept}.xml", xml.encode("utf-8"))
    return buf.getvalue()


LISTED = {"20260814000001": "반기보고서 (2026.06)", "20260310000002": "사업보고서 (2025.12)", "20250814000003": "반기보고서 (2025.06)"}


@pytest.fixture
def fake_dart(monkeypatch):
    def zipped(name, **p):
        assert name == "document"
        return zipfile.ZipFile(io.BytesIO(_report(p["rcept_no"], 2026, 900)))

    def filings(corp, start, end, kind=""):
        return [{"rcept_no": k, "rcept_dt": k[:8], "report_nm": v, "corp_name": "가온정밀(가상)"} for k, v in LISTED.items()
                if start.strftime("%Y%m%d") <= k[:8] <= end.strftime("%Y%m%d")] + \
               [{"rcept_no": "20260814000009", "rcept_dt": "20260814", "report_nm": "임원ㆍ주요주주특정증권등소유상황보고서", "corp_name": "가온정밀(가상)"}]

    monkeypatch.setattr(F, "_zipped", zipped)
    monkeypatch.setattr(F, "filings", filings)
    monkeypatch.setattr(F, "corp_code", lambda name: "00000001")


def test_fetch_pdf_name_splits_and_prints_foot(tmp_path, fake_dart, capsys):
    pdf = tmp_path / "[가온정밀(가상)]반기검토보고서(2026.08.14).pdf"
    pdf.write_bytes(b"")
    assert F.from_pdf(pdf)[0] == "20260814000001"
    assert cli(["dsd", "fetch", str(pdf), "--out", str(tmp_path / "o")]) == 0
    out = capsys.readouterr().out
    for r in LISTED:
        assert (tmp_path / "o" / f"원문_{r}" / f"{r}_별도.xml").exists() and (tmp_path / "o" / f"원문_{r}" / f"{r}_연결.xml").exists()
    line = next(x for x in out.splitlines() if "dsd foot" in x and x.split('"')[1].endswith("20260814000001_별도.xml"))
    assert line.index("20260310000002_별도.xml") < line.index("20250814000003_별도.xml")      # 직전 사업보고서, 작년 같은 기간 순
    assert '--pair "' in line and "20260814000001_연결.xml" in line
    doc = G.read_grid(tmp_path / "o" / "원문_20260814000001" / "20260814000001_별도.xml")
    assert doc.table("재무상태표").nums[0][1] == 900


def test_fetch_never_prints_key(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DART_API_KEY", "SECRET-KEY-123")

    def boom(url, timeout=0):
        raise OSError(f"연결 실패 {url}")

    monkeypatch.setattr(F.urllib.request, "urlopen", boom)
    monkeypatch.setattr(F.time, "sleep", lambda s: None)
    assert cli(["dsd", "fetch", "20260814000001", "--out", str(tmp_path)]) == 2
    out = capsys.readouterr()
    assert "원문을 받지 못함" in out.out and "SECRET-KEY-123" not in out.out + out.err


def test_fetch_rejects_unknown_input(tmp_path, capsys):
    assert cli(["dsd", "fetch", "한 상장사", "--out", str(tmp_path)]) == 2
    assert "접수번호(14자리)" in capsys.readouterr().out


# ---------------------------------------------------------------- 늘 나는 차이는 독립 검증 대신 회계사 표본(2026-10-22 결정)
def _usual_check():
    return L.Check("AI|취득", "주석-재무제표", "레퍼", "주석7-1", 0, 1, [("현금흐름표", 0, 1, -1)], None, "현금흐름표 유형자산의 취득", "AI",
                   left=25, right=30, ok=False, when="미지급금 변동이 없다", usual="취득과 현금흐름표")


def test_usual_confirmed_difference_skips_independent_review():
    c = _usual_check()
    assert not L.sampled(c)                                             # 판정 전에는 독립 검증 대상이다
    L.apply_finding(c, {"verdict": "확인", "why": "전기말 미지급금 지급"})
    assert L.sampled(c)
    for verdict in ("숫자 오류", "표시 오류", "설명 부족", "작년 보고서 불일치"):
        c = _usual_check()
        L.apply_finding(c, {"verdict": verdict, "why": "x"})
        assert not L.sampled(c) and c.usual == ""
    c = _usual_check()
    L.apply_finding(c, {"verdict": "확인", "why": "차이가 평소보다 크다", "usual": ""})          # 판정이 유형을 떼면 독립 검증으로 돌아간다
    assert not L.sampled(c)
    c = _usual_check()
    c.weak = True
    L.apply_finding(c, {"verdict": "확인", "why": "x"})
    assert not L.sampled(c)                                             # 근거가 약한 연결은 늘 나는 차이로 빼지 않는다


def test_pack_marks_usual_difference_not_for_review():
    head = ["", "공시금액"]
    doc = _doc([("현금흐름표", "현금흐름표", [_tab("현금흐름표", ["", "당기", "전기"], [["유형자산의 취득", "-30", "-20"]])]),
                ("주석7", "유형자산", [_tab("주석7-1", head, [["취득", "25"]])])])
    c = _usual_check()
    L.apply_finding(c, {"verdict": "확인", "why": "전기말 미지급금 지급"})
    text = V.pack(doc, [c], D.tables(doc), {}, {})
    assert "- 독립 검증 대상 0건. 판정이 확인인 늘 나는 차이 1건과 엔진이 근거를 확인한 숫자 오류 0건은 독립 검증을 하지 않는다" in text
    assert "- 독립 검증: 대상 아님(늘 나는 차이 「취득과 현금흐름표」. 회계사가 표본으로 본다)" in text


def _number_error(fix_note):
    c = L.Check("AI|재고", "주석-재무제표", "레퍼", "주석5-1", 0, 1, [("재무상태표", 0, 1, 1)], None, "재무상태표 재고자산", "AI",
                left=1212, right=1122, ok=False)
    L.apply_finding(c, {"verdict": "숫자 오류", "why": "자리를 바꿔 적었다"})
    c.fix_note = fix_note
    return c


def test_engine_checked_number_error_skips_independent_review():
    """엔진이 근거 칸으로 맞는 숫자를 확인한 숫자 오류는 독립 검증에 보내지 않는다(2026-10-22 결정)."""
    c = _number_error("근거 확인: 「재무상태표 재고자산 · 당기」 1,122")
    assert L.engine_checked(c) and L.no_review(c) and not L.sampled(c)
    assert L.engine_checked(_number_error("근거 확인(부호): 작년 보고서 「결손금」 도 5 로 같은 부호다"))
    for note in ("고칠 쪽 미정: 근거 칸이 없다", ""):
        c = _number_error(note)
        assert not L.engine_checked(c) and not L.no_review(c)                 # 고칠 쪽을 엔진이 확인하지 못하면 계속 독립 검증
    c = _number_error("근거 확인: x")
    L.apply_finding(c, {"verdict": "표시 오류", "why": "이름만 틀렸다"})
    assert not L.engine_checked(c)                                          # 숫자 오류가 아니면 해당하지 않는다


def test_pack_marks_engine_checked_not_for_review():
    doc = _doc([("재무상태표", "재무상태표", [_tab("재무상태표", ["", "당기", "전기"], [["재고자산", "1122", "1020"]])]),
                ("주석5", "재고자산", [_tab("주석5-1", ["", "당기말"], [["재고자산", "1212"]])])])
    c = _number_error("근거 확인: 「재무상태표 재고자산 · 당기」 1,122")
    text = V.pack(doc, [c], D.tables(doc), {}, {})
    assert "엔진이 근거를 확인한 숫자 오류 1건은 독립 검증을 하지 않는다" in text and "- 독립 검증 대상 0건." in text
    assert "- 독립 검증: 대상 아님(엔진이 근거 칸으로 맞는 숫자를 확인했다)" in text


def test_pack_basis_hides_prior_verdict():
    """전기 대사 판정 글은 판정 줄에만 나오고 근거 줄에는 붙지 않는다(10-22 한 상장사 재기)."""
    doc = _doc([("재무상태표", "재무상태표", [_tab("재무상태표", ["", "당기", "전기"], [["재고자산", "1122", "1020"]])])])
    c = L.Check("전기|재고", "전기", "전기", "재무상태표", 0, 2, [], None, "작년 재무상태표 재고자산", "엔진", left=1020, right=1000, ok=False,
                basis="작년 보고서의 당기 금액")
    L.apply_prior_verdicts([c], [{"id": "전기|재고", "verdict": "불일치", "why": "작년 보고서가 맞다"}])
    text = V.pack(doc, [c], D.tables(doc), {}, {})
    assert "- 근거: 작년 보고서의 당기 금액\n" in text and "판정 불일치: 작년 보고서가 맞다" not in text.split("- 판정")[0]


def test_findings_usual_kept_by_apply():
    doc = _doc([("주석7", "유형자산", [_tab("주석7-1", ["", "공시금액"], [["취득", "25"]])])])
    new, problems = A.apply(doc, {}, {"links": [], "findings": [{"id": "AI|x", "verdict": "확인", "why": "크다", "usual": ""}]})
    assert problems == [] and new["findings"][0]["usual"] == ""
