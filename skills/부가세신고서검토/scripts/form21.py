# -*- coding: utf-8 -*-
"""부가가치세법 시행규칙 별지 제21호서식(2026. 3. 20. 개정)을 그린다.

직원이 넘기는 작성본도, 회계사가 조서에 철하는 검토본도 이 모양이어야 한다.
표 구조·란 번호·기호(㉮~㉹)·세율 칸은 서식 원문을 그대로 옮겼다.
원문은 스킬 폴더 assets/별지21호_일반과세자_부가가치세신고서.pdf 다.

**제출용이 아니다.** 실제 신고는 홈택스 전자신고나 더존 전송으로 한다.
"""

CSS = """
@page{size:A4 portrait; margin:8mm 9mm 6mm 9mm}
*{box-sizing:border-box; margin:0; padding:0}
body{font-family:'Malgun Gothic','맑은 고딕','Apple SD Gothic Neo','Noto Sans KR',
     'Noto Sans CJK KR','NanumGothic',sans-serif; font-size:7.6pt;
     line-height:1.18; color:#111; font-variant-numeric:tabular-nums;
     word-break:keep-all}
.fhead{font-size:7pt; margin-bottom:1.4mm}
.ftitle{text-align:center; font-size:12pt; font-weight:700; letter-spacing:-.02em;
        margin:.8mm 0 1.2mm; line-height:1.4}
.ftitle .sm{font-size:9.5pt}
.ftitle{display:flex; align-items:center; justify-content:center; gap:2.5mm}
.ftitle .tl{white-space:nowrap}
.ftitle .cks{display:inline-flex; flex-direction:column; font-size:9pt;
  font-weight:600; line-height:1.5; text-align:left}
.ftitle .cks i{font-style:normal; white-space:nowrap}
table tr.shade th,table tr.shade td{background:#E8E8E8}
.fnote{font-size:6.9pt; margin-bottom:1.1mm; display:flex; justify-content:space-between}
table{width:100%; border-collapse:collapse; margin-bottom:.8mm}
th,td{border:.5pt solid #444; padding:.38mm 1mm; vertical-align:middle; font-size:7.4pt}
th{background:#F2F2F2; font-weight:400; text-align:center}
td.l{text-align:left}
td.c{text-align:center}
td.n{text-align:right; white-space:nowrap}
td.g{background:#D9D9D9}
td.v{text-align:center; width:6mm; padding:.6mm .3mm; line-height:1.1}
.sec{font-weight:700; font-size:8pt; margin:1.5mm 0 .8mm}
.ftail{font-size:6.9pt; text-align:right; margin-top:.6mm}
.sig{font-size:7pt; line-height:1.45; vertical-align:top}
.inner{margin:0; border:none}
.inner.tel{width:100%}
.inner.tel th,.inner.tel td{border:none; border-left:.5pt solid #444}
.inner.tel tr:first-child th{border-bottom:.5pt solid #444}
.inner.tel th:first-child,.inner.tel td:first-child{border-left:none}
.inner td,.inner th{border:.5pt solid #444}
/* 검토본에 덧붙는 것 */
.rev{page-break-before:always}
.rev h2{font-size:11pt; margin:0 0 2mm; padding-bottom:1.2mm;
        border-bottom:1.6pt solid #111}
.rev .meta{font-size:8.4pt; color:#333; margin-bottom:2.5mm}
.rev .note{font-size:8pt; color:#333; margin:1.5mm 0 3mm}
.stop{color:#B5322A; font-weight:700}
td.neg{color:#B5322A}
tr.key td{background:#FFF6E5}
.sign{margin-top:7mm; border-top:.8pt solid #111; padding-top:3mm; font-size:8.4pt}
.sign table{border:none}
.sign td{border:none; padding:2mm 0 0}
.sign .line{border-bottom:.5pt solid #666; height:9mm; width:52mm}
.foot{margin-top:4mm; font-size:7.4pt; color:#555; border-top:.5pt solid #CCC;
      padding-top:2mm}
"""


def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def won(v):
    if v in ("", None):
        return ""
    try:
        return f"{int(v):,}"
    except (TypeError, ValueError):
        return str(v)


def _cells(no, sup, tax, rate="", mark="", gray=False, sup_cell=""):
    """란번호 · 금액 · 세율 · 세액 네 칸.

    세율 칸은 매입세액 줄에서 막혀 있고(회색) 합계 줄에서는 기호가 들어간다.

    `sup_cell` 은 금액 칸을 어떻게 둘지다. 홈택스 출력물을 그대로 따른다.
    세액만 있는 란은 금액 칸에 0 을 찍지 않는다. 0 원을 신고한 것으로 읽히기 때문이다.

      ""      금액을 찍는다
      blank   흰 빈칸. (21)~(25)·(29)
      gray    회색으로 막는다. 적는 칸이 아니라는 뜻. (19)·(26)~(28)
    """
    g = " g" if (gray and not mark) else ""
    sg = " g" if sup_cell == "gray" else ""
    val = "" if sup_cell else won(sup)
    return (f"<td class='c' style='width:6.5%'>{esc(no)}</td>"
            f"<td class='n{sg}' style='width:22%'>{val}</td>"
            f"<td class='c{g}' style='width:8.5%'>{esc(mark or rate)}</td>"
            f"<td class='n' style='width:20%'>{won(tax)}</td>")


TAIL_ROWS = [("(22)", "소규모 개인사업자 부가가치세 감면세액", "㉲"),
             ("(23)", "예정신고 미환급세액", "㉳"),
             ("(24)", "예정고지세액", "㉴"),
             ("(25)", "수시부과세액", "㉵"),
             ("(26)", "사업양수자가 대리납부한 세액", "㉶"),
             ("(27)", "매입자 납부특례에 따라 납부한 세액", "㉷"),
             ("(28)", "신용카드업자가 대리납부한 세액", "㉸"),
             ("(29)", "가산세액 계", "㉹")]


def biz(no):
    """사업자등록번호를 찍을 때만 하이픈을 넣는다.
    저장은 키트 관례대로 숫자 열 자리다. partners.csv 와 같은 꼴을 쓴다."""
    d = "".join(c for c in str(no) if c.isdigit())
    return f"{d[:3]}-{d[3:5]}-{d[5:]}" if len(d) == 10 else str(no)


def build(company, period, rows, *, 확정=True, 사업자번호="",
          대표자="", 주소="", 업종코드="",
          업태="", 종목="", 세무서="", 신고일="", 과세기간="",
          생년월일="", 사업장전화="", 주소지전화="", 휴대전화="", 전자우편="",
          제2장=False, p2=None, extra=""):
    """별지 제21호서식을 그린다.

    `제2장=True` 면 제4쪽(36)~(90) 명세를 둘째 장으로 붙인다. 홈택스 출력물이 그 모양이다.
    기본은 False 다. **직원 작성본 PDF 를 읽는 쪽이 란 번호로 훑기 때문에**
    (36)~(90) 이 붙으면 읽는 란 수가 달라진다. 검토 대상 신고서는 한 장으로 둔다."""
    d = {r[0]: r for r in rows}

    def v(k, i):
        return d[k][i] if k in d else 0

    def chk(on):
        return "[√]" if on else "[&nbsp;&nbsp;]"

    b = ['<div class="fhead">■ 부가가치세법 시행규칙 [별지 제21호서식] '
         '&lt;개정 2026. 3. 20.&gt; &nbsp;&nbsp;&nbsp; '
         '홈택스(www.hometax.go.kr)에서도 신청할 수 있습니다.</div>',
         '<div class="ftitle">'
         '<span class="tl">일반과세자 부가가치세</span>'
         '<span class="cks">'
         f'<i>{chk(not 확정)}예정 &nbsp;{chk(확정)}확정</i>'
         f'<i>{chk(False)}기한후과세표준</i>'
         f'<i>{chk(False)}영세율 등 조기환급</i></span>'
         '<span class="tl">신고서</span></div>',
         '<div class="fnote"><span></span><span>(제1장 앞쪽)</span></div>',
         "<table><tr class='shade'><th style='width:13%'>관리번호</th><td style='width:57%'></td>"
         "<th style='width:14%'>처리기간</th><td class='c' style='width:16%'>즉시</td></tr>"
         f"<tr class='shade'><th>신고기간</th><td class='l' colspan='3'>{esc(과세기간 or period)}"
         "</td></tr></table>",
         "<table>"
         "<tr><th rowspan='3' style='width:7%'>사업자</th>"
         "<th style='width:11%'>상호<br>(법인명)</th>"
         f"<td class='l' style='width:24%'>{esc(company)}</td>"
         "<th style='width:10%'>성명<br>(대표자명)</th>"
         f"<td class='l' style='width:13%'>{esc(대표자)}</td>"
         "<th style='width:14%'>사업자등록번호</th>"
         f"<td class='c'>{esc(biz(사업자번호))}</td></tr>"
         # 전화번호는 사업장·주소지·휴대전화 세 칸으로 갈린다. 서식 원문이 그렇다
         f"<tr><th>생년월일</th><td class='l'>{esc(생년월일)}</td><th>전화번호</th>"
         "<td colspan='3' style='padding:0'><table class='inner tel'>"
         "<tr><th style='width:33%'>사업장</th><th style='width:33%'>주소지</th>"
         "<th>휴대전화</th></tr>"
         f"<tr><td class='c'>{esc(사업장전화)}</td>"
         f"<td class='c'>{esc(주소지전화)}</td>"
         f"<td class='c'>{esc(휴대전화)}</td></tr></table></td></tr>"
         f"<tr><th>사업장 주소</th><td class='l' colspan='3'>{esc(주소)}</td>"
         f"<th>전자우편<br>주소</th><td class='l'>{esc(전자우편)}</td></tr></table>",
         '<div class="sec">① 신고내용</div>',
         "<table><tr><th colspan='4' style='width:43%'>구분</th><th>금액</th>"
         "<th style='width:8.5%'>세율</th><th>세액</th></tr>"]

    # 과세표준 및 매출세액 — 9줄
    b.append("<tr><td class='v' rowspan='9'>과<br>세<br>표<br>준<br>및<br>매<br>출<br>세<br>액</td>"
             "<td class='c' rowspan='4' style='width:6%'>과세</td>"
             "<td class='l'>세금계산서 발급분</td>"
             + _cells("(1)", v("(1)", 2), v("(1)", 3), "10/100") + "</tr>")
    for no, nm in (("(2)", "매입자발행 세금계산서"),
                   ("(3)", "신용카드·현금영수증 발행분"),
                   ("(4)", "기타(정규영수증 외 매출분)")):
        b.append(f"<tr><td class='l'>{esc(nm)}</td>"
                 + _cells(no, v(no, 2), v(no, 3), "10/100") + "</tr>")
    b.append("<tr><td class='c' rowspan='2'>영세율</td><td class='l'>세금계산서 발급분</td>"
             + _cells("(5)", v("(5)", 2), v("(5)", 3), "0/100") + "</tr>")
    b.append("<tr><td class='l'>기타</td>"
             + _cells("(6)", v("(6)", 2), v("(6)", 3), "0/100") + "</tr>")
    for no, nm in (("(7)", "예정신고 누락분"), ("(8)", "대손세액 가감")):
        b.append(f"<tr><td class='l' colspan='2'>{esc(nm)}</td>"
                 + _cells(no, v(no, 2), v(no, 3)) + "</tr>")
    b.append("<tr><td class='l' colspan='2'>합계</td>"
             + _cells("(9)", v("(9)", 2), v("(9)", 3), mark="㉮") + "</tr>")

    # 매입세액 — 9줄
    b.append("<tr><td class='v' rowspan='9'>매<br>입<br>세<br>액</td>"
             "<td class='c' rowspan='3'>세금<br>계산서<br>수취분</td>"
             "<td class='l'>일반매입</td>"
             + _cells("(10)", v("(10)", 2), v("(10)", 3), gray=True) + "</tr>")
    # (11) 금액 칸은 서식에서 막혀 있다. 세액만 적는 란이다
    b.append("<tr><td class='l'>수출기업 수입분 납부유예</td>"
             + _cells("(11)", v("(11)", 2), v("(11)", 3), gray=True,
                      sup_cell="gray") + "</tr>")
    b.append("<tr><td class='l'>고정자산매입</td>"
             + _cells("(12)", v("(12)", 2), v("(12)", 3), gray=True) + "</tr>")
    for no, nm in (("(13)", "예정신고 누락분"), ("(14)", "매입자발행 세금계산서"),
                   ("(15)", "그 밖의 공제매입세액"),
                   ("(16)", "합계 (10)-(11)+(12)+(13)+(14)+(15)"),
                   ("(17)", "공제받지 못할 매입세액")):
        b.append(f"<tr><td class='l' colspan='2'>{esc(nm)}</td>"
                 + _cells(no, v(no, 2), v(no, 3), gray=True) + "</tr>")
    b.append("<tr><td class='l' colspan='2'>차감계 (16)-(17)</td>"
             + _cells("(18)", v("(18)", 2), v("(18)", 3), mark="㉯") + "</tr>")
    b.append("<tr><td class='l' colspan='4'>납부(환급)세액 (매출세액㉮-매입세액㉯)</td>"
             "<td class='n'></td><td class='c'>㉰</td>"
             f"<td class='n'>{won(v('㉰', 3))}</td></tr>")

    # 경감·공제세액 — 3줄
    b.append("<tr><td class='v' rowspan='3'>경<br>감<br>공<br>제</td>"
             "<td class='l' colspan='2'>그 밖의 경감·공제세액</td>"
             + _cells("(19)", v("(19)", 2), v("(19)", 3),
                      sup_cell="gray") + "</tr>")
    b.append("<tr><td class='l' colspan='2'>신용카드매출전표등 발행공제 등</td>"
             + _cells("(20)", v("(20)", 2), v("(20)", 3)) + "</tr>")
    b.append("<tr><td class='l' colspan='2'>합계</td>"
             + _cells("(21)", v("(21)", 2), v("(21)", 3), mark="㉱",
                      sup_cell="blank") + "</tr>")
    # (26)~(28) 은 금액 칸이 아예 막혀 있다. 나머지는 흰 빈칸이다
    BLOCKED = {"(26)", "(27)", "(28)"}
    for no, nm, mk in TAIL_ROWS:
        b.append(f"<tr><td class='l' colspan='3'>{esc(nm)}</td>"
                 + _cells(no, v(no, 2), v(no, 3), mark=mk,
                          sup_cell="gray" if no in BLOCKED else "blank")
                 + "</tr>")
    b.append("<tr><td class='l' colspan='4'>차감·가감하여 납부할 세액(환급받을 세액)"
             " (㉰-㉱-㉲-㉳-㉴-㉵-㉶-㉷-㉸+㉹)</td><td class='n'></td>"
             f"<td class='c'>(30)</td><td class='n'>{won(v('(30)', 3))}</td></tr>")
    b.append("<tr><td class='l' colspan='6'>총괄 납부 사업자가 납부할 세액"
             "(환급받을 세액)</td><td class='n'></td></tr></table>")

    b.append("<table><tr><th style='width:22%'>② 국세환급금 계좌신고</th>"
             "<th style='width:12%'>거래은행</th><td style='width:20%'></td>"
             "<th style='width:10%'>은행<br>지점</th><th style='width:12%'>계좌번호</th>"
             "<td></td></tr></table>")
    b.append("<table><tr><th style='width:22%'>③ 폐업 신고</th>"
             "<th style='width:12%'>폐업일</th><td style='width:26%'></td>"
             "<th style='width:12%'>폐업 사유</th><td></td></tr></table>")
    b.append("<table><tr><th style='width:22%'>④ 영세율 상호주의</th>"
             "<th style='width:14%'>여[&nbsp;&nbsp;]부[√]</th>"
             "<th style='width:12%'>적용구분</th><td style='width:12%'></td>"
             "<th style='width:8%'>업종</th><td style='width:14%'></td>"
             "<th style='width:12%'>해당 국가</th><td></td></tr></table>")

    b.append(
        "<table><tr>"
        "<td style='width:50%; vertical-align:top; padding:0; border:none'>"
        "<table class='inner'><tr><th colspan='5'>⑤ 과세표준명세</th></tr>"
        "<tr><th style='width:8%'></th><th style='width:17%'>업태</th>"
        "<th style='width:22%'>종목</th><th style='width:13%'>생산요소</th>"
        "<th style='width:16%'>업종 코드</th><th>금 액</th></tr>"
        f"<tr><td class='c'>(31)</td><td class='c'>{esc(업태)}</td>"
        f"<td class='c'>{esc(종목)}</td><td></td>"
        f"<td class='c'>{esc(업종코드)}</td><td class='n'>{won(v('(9)', 2))}</td></tr>"
        "<tr><td class='c'>(32)</td><td></td><td></td><td></td><td></td><td></td></tr>"
        "<tr><td class='c'>(33)</td><td></td><td></td><td></td><td></td><td></td></tr>"
        "<tr><td class='c'>(34)</td><td class='l' colspan='4'>수입금액 제외</td>"
        "<td class='n'></td></tr>"
        "<tr><td class='c'>(35)</td><td class='l' colspan='4'>합 계</td>"
        f"<td class='n'>{won(v('(9)', 2))}</td></tr>"
        + ("" if 제2장 else
           "<tr><td class='l' colspan='5'>면세사업 수입금액</td>"
           f"<td class='n'>{won(v('면세', 2))}</td></tr>")
        + "</table></td>"
        "<td class='sig' style='border:none; padding-left:3mm'>"
        "「부가가치세법」 제48조·제49조 또는 제59조와 「국세기본법」 제45조의3에 따라 "
        "위의 내용을 신고하며, 위 내용을 충분히 검토하였고 신고인이 알고 있는 사실 "
        "그대로를 정확하게 적었음을 확인합니다.<br><br>"
        + (f"<div style='text-align:right'>{esc(신고일)}</div>" if 신고일 else
           "<div style='text-align:right'>년 &nbsp;&nbsp; 월 &nbsp;&nbsp; 일</div>") +
        "<div style='text-align:right'>신고인 : &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;"
        "&nbsp;&nbsp;&nbsp;&nbsp; (서명 또는 인)</div><br>"
        "세무대리인은 조세전문자격자로서 위 신고서를 성실하고 공정하게 작성하였음을 "
        "확인합니다."
        "<div style='text-align:right'>세무대리인 : &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;"
        "&nbsp;&nbsp; (서명 또는 인)</div><br>"
        f"<div style='font-size:10pt; font-weight:700'>{esc(세무서)} 세무서장 &nbsp;귀하</div>"
        "<div style='text-align:right'>첨부서류 &nbsp;뒤쪽 참조</div>"
        "</td></tr></table>")
    b.append("<table><tr><th rowspan='2' style='width:14%'>세무대리인</th>"
             "<th style='width:12%'>성 명</th><td style='width:22%'></td>"
             "<th style='width:18%'>사업자등록번호</th><td></td></tr>"
             "<tr><th>관리번호</th><td></td><th>생년월일</th><td></td>"
             "<th style='width:12%'>전화번호</th><td></td></tr></table>")
    b.append('<div class="ftail">210mm×297mm[백상지(80g/㎡) 또는 중질지(80g/㎡)]</div>')
    if 제2장:
        b.append(_page2(rows, p2 or {}, 사업자번호))
    b.append(extra)

    return (f"<!doctype html><html lang='ko'><head><meta charset='utf-8'>"
            f"<title>{esc(company)} {esc(period)} 부가가치세 신고서</title>"
            f"<style>{CSS}{_p2css()}</style></head>"
            f"<body>{''.join(b)}</body></html>")


def _page2(rows, p2, 사업자번호):
    from form21_p2 import page2
    return page2(rows, p2, 사업자번호)


def _p2css():
    from form21_p2 import CSS as C
    return C
