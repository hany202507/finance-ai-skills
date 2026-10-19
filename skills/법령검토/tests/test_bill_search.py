import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import bill_search as bs  # noqa: E402

# 2026-10-19 의안정보시스템 검색 결과(findSchPaging.do) 한 행의 모양
ROW = """<tr> <td class="mnone" title="{no}">{no}</td> <td class="align_left">
<a href="javascript:;" data-bill_no="{no}" data-bill-id="{bid}" onclick="goDetailPage(this);" title="x">
<i class="{ico}">{icotext}</i> {name} </a>
<ul class="mobile_board_date"> <li>{no}</li> <li>의원</li> </ul> </td>
<td class="mnone" title="{who}">{who}</td> <td class="mnone">{prop}</td> <td class="mnone">{done}</td> <td class="mnone">{result}</td>
<td> <a href="javascript:;" data-bill-id="{bid}" onclick="openSummaryPopup(this);"><img alt="미리보기"></a> </td>
<td class="mnone" title="{stage}"> <div> {stage} </div> </td> </tr>"""


def row(no, name, ico="ico_kye", icotext="계류의안", who="의원", prop="2026-10-19", done="", result="", stage="접수", bid=None):
    return ROW.format(no=no, bid=bid or f"PRC_{no}", ico=ico, icotext=icotext, name=name, who=who,
                      prop=prop, done=done, result=result, stage=stage)


PAGE = ('<input type="hidden" id="pager_count_text" value="4">'
        + row("2221951", "소득세법 일부개정법률안(김영환의원 등 10인)")
        + row("2213751", "소득세법 일부개정법률안(대안)(기획재정위원장)", ico="ico_cheo", icotext="처리의안",
              who="위원장", done="2026-04-02", result="원안가결", stage="공포")
        + row("2220001", "조세특례제한법 일부개정법률안(소득세법 관련)")
        + row("2220002", "소득세법 일부개정법률안(정부)", ico="ico_cheo", icotext="처리의안", who="정부",
              done="2026-10-10", result="수정가결", stage="정부이송", bid="ARC_X"))

# 2026-10-19 의안 요약 화면(billSummary.do)의 모양. 본문 앞에 닫히지 않은 <script> 가 있다
SUMMARY = (
    "<h3>제안이유 및 주요내용</h3><script>var glb_ctxPathJS = '/bill';"
    '<h4>[2221231] 소득세법 일부개정법률안</h4><pre class="print_pre">제안이유 및 주요내용\r\n\r\n'
    "  현행법은 1세대 1주택으로서 실지거래가액이 12억원 이하인 주택의 양도소득을 비과세하고 있음.\r\n"
    "(안 제89조의2 신설 등)</pre><script>menuNm: '제안이유 및 주요내용'</script>"
)


def test_parse_rows_reads_columns_and_drops_icon_text():
    total, rows = bs.parse_rows(PAGE)
    assert total == 4 and len(rows) == 4
    r = rows[0]
    assert (r["의안번호"], r["의안명"], r["제안자구분"], r["제안일"], r["진행"]) == (
        "2221951", "소득세법 일부개정법률안(김영환의원 등 10인)", "의원", "2026-10-19", "접수")


def test_stage_and_law_filter():
    _, rows = bs.parse_rows(PAGE)
    got = [(r["의안번호"], bs.stage(r), bs.is_bill_of(r, "소득세법")) for r in rows]
    assert got == [("2221951", "계류", True), ("2213751", None, True),
                   ("2220001", "계류", False), ("2220002", "국회통과", True)]


def test_article_pattern():
    p = bs.jo_pattern("제89조")
    assert p.search("안 제89조제1항제3호") and p.search("제 89 조")
    assert not p.search("안 제89조의2 신설")
    assert bs.jo_pattern("제341조의2").search("안 제341조의2")


def test_article_pattern_accepts_scan_articles_notation():
    assert bs.jo_pattern("제27의2조").search("안 제27조의2제3항")


def test_parse_targets():
    assert bs.parse_targets(["소득세법:제89조, 제95조", "상법:제341조"]) == [
        ("소득세법", ["제89조", "제95조"]), ("상법", ["제341조"])]


def test_summary_text_reads_print_pre_only():
    got = bs.summary_text(SUMMARY)
    assert got.startswith("현행법은 1세대 1주택") and got.endswith("(안 제89조의2 신설 등)")
    assert "glb_ctxPathJS" not in got
    assert bs.summary_text("<p>없음</p>") == ""
