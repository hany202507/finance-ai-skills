"""문장 검토(scripts/audit/report/dsd_text.py): 주주 명단의 이름과 엔진 지적과 겹친 AI 지적(2026-10-21)."""
import json
import zipfile
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from audit.report import dsd_text  # noqa: E402

CR = "&amp;cr;"


def _dsd(path: Path, note1: str, period: str = "2026년 2월 9일 ~ 2월 13일", valid: str = "2026년 3월 10일", extra: str = "", more: str = "",
         ext_rows: str = "") -> Path:
    body = f"""<?xml version="1.0" encoding="utf-8"?>
<DOCUMENT><BODY>
<COVER><P>가온정밀(가상){CR}재 무 제 표 에 대 한 감 사 보 고 서{CR}제 20 기 2025년 01월 01일 부터 2025년 12월 31일 까지{CR}가온감사반(가상)</P></COVER>
<SECTION-1><TITLE>감사보고서</TITLE>
<P>우리는 회사의 재무제표를 감사하였습니다.</P>
<P>서울특별시 감사로 10, 5층</P>
<P>2026년 3월 10일</P>
<P>이 감사보고서는 감사보고서일({valid}) 현재로 유효한 것입니다.</P>
</SECTION-1>
<SECTION-1><TITLE>주석</TITLE>
<P USERMARK="B F-12">1. 회사의 개요</P>
<P>{note1}</P>
<P USERMARK="B F-12">2. 중요한 회계정책</P>
<P>회사의 재무제표는 일반기업회계기준에 따라 작성되었습니다.{extra}</P>{more}
</SECTION-1>
<SECTION-1><TITLE>외부감사 실시내용</TITLE>
<TABLE BORDER="1"><TBODY>{ext_rows}<TR><TD>현장감사</TD><TD>수행시기</TD><TD>{period}</TD></TR></TBODY></TABLE>
</SECTION-1>
</BODY></DOCUMENT>"""
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("contents.xml", body.encode("utf-8"))
        z.writestr("meta.xml", b"<META/>")
    return path


FACTS = {"대표이사": {"value": "이가온", "old": ["김가온"], "source": "이사회의사록"},
         "본점 주소": {"value": "경기도 가온로 55", "old": ["서울특별시 가온로 20"]},
         "감사인 주소": {"value": "서울특별시 감사로 10, 5층"},
         "감사기간": [{"구분": "현장감사", "기간": "2026-02-09~2026-02-13"}],
         "감사보고서일": {"value": "2026-03-10"}, "결산일": {"value": "2025-12-31"}}


def test_shareholder_name_keeps_name_and_fixes_title(tmp_path):
    """주식수 · 지분율이 붙은 이름은 주주 명단이다. 전 대표이사 이름을 새 대표이사로 바꾸라고 하지 않고 직함을 고치라고 낸다(가온정밀 실습 S101, 10-21)."""
    more = "<P>보고기간 말 현재 주주 구성은 대표이사 김가온 240,000주(60%), 가온홀딩스 160,000주(40%)입니다.</P><P>주주 김가온 240,000주(60%)입니다.</P>"
    p = _dsd(tmp_path / "a.dsd", "본사는 경기도 가온로 55에 있습니다. 대표이사 김가온이 회사를 대표합니다.", more=more)
    r = dsd_text.review(p, FACTS)
    by = {s.id: s.text for s in r["segments"]}
    olds = {by[x["seg"]][:6]: x["fix"] for x in r["engine"] if x["rule"] == "옛 값"}
    assert olds["본사는 경기"] == "김가온 → 이가온"                                       # 대표이사 자리의 옛 이름은 바꾼다
    assert olds["보고기간 말"] == "「대표이사 김가온」 의 직함을 빼거나 바꾼다(주주 이름은 그대로 둔다)"
    assert "주주 김가온" not in olds                                                    # 직함 없이 주주로만 적힌 전 대표이사는 맞다
    assert not any("→ 이가온" in x["fix"] for x in r["engine"] if by[x["seg"]].startswith(("보고기간", "주주")))
    p = _dsd(tmp_path / "b.dsd", "대표이사 김가온이 지분 60%를 보유합니다.")
    r = dsd_text.review(p, {"대표이사": {"value": "이가온"}})                            # 옛 값이 없어도 같다(대표이사 규칙)
    assert [x["fix"] for x in r["engine"] if x["rule"] == "대표이사"] == ["「대표이사 김가온」 의 직함을 빼거나 바꾼다. 이름이 틀린 것이면 주주명부로 확인해 고친다"]


def test_ai_finding_at_engine_spot_shows_when_fix_differs(tmp_path):
    """같은 곳에 엔진과 같은 고칠 안이면 엑셀에 한 번만, 고칠 안이 다르면 AI 지적도 함께 나온다(가온정밀 실습 S101 · S227, 10-21)."""
    p = _dsd(tmp_path / "a.dsd", "x", period="2026년 2월 9일 ~ 2월 12일 | 일 | 명 | 명", extra=" 재무재표를 참고합니다.")
    segs = dsd_text.segments(p)
    per = next(s.id for s in segs if "2월 12일" in s.text)
    typo = next(s.id for s in segs if "재무재표" in s.text)
    ai = {"findings": [{"seg": per, "quote": "일 | 명 | 명", "kind": "공시 누락", "fix": "현장감사 일수와 투입인원을 적는다", "basis": "칸이 비었다"},
                       {"seg": typo, "quote": "재무재표", "kind": "오타", "fix": "재무재표 → 재무제표", "basis": "오타"},
                       {"seg": typo, "quote": "재무재표를", "kind": "오타", "fix": "재무제표", "basis": "오타"}]}
    r = dsd_text.review(p, FACTS, ai=ai)
    assert any(x["rule"] == "감사기간" and x["seg"] == per for x in r["engine"])
    shown = [x for x in r["ai"] if not x["same_as_engine"]]
    assert [(x["seg"], x["rule"]) for x in shown] == [(per, "AI(엔진과 같은 곳)")]                # 엔진과 같은 고칠 안 둘은 숨는다
    from openpyxl import Workbook

    wb = Workbook()
    dsd_text.add_sheet(wb, r)
    rows = [row for row in wb[dsd_text.SHEET].iter_rows(min_row=5, values_only=True) if row[0]]
    assert sum(1 for row in rows if str(row[4]).startswith(per + " ")) == 2                    # 날짜 지적과 빈칸 지적이 다 보인다
    assert sum(1 for row in rows if str(row[4]).startswith(typo + " ")) == 1
    assert " · AI 1 · " in dsd_text.summary(r)
