# -*- coding: utf-8 -*-
"""별지 제21호서식 제4쪽 (36)~(90). 홈택스 출력물은 이것을 제2장으로 냅니다.

`form21.build(..., 제2장=True)` 일 때만 붙습니다. 기본은 안 붙입니다.
**직원 작성본 PDF 를 읽는 쪽이 란 번호로 훑기 때문에** (36)~(90) 이 붙으면
읽는 란 수가 달라집니다. 검토 대상 신고서는 한 장으로 둡니다.

## 칸이 여덟입니다

표 전체가 **여덟 칸**입니다. 묶음이 둘까지 붙는 줄이 있어서입니다.

    세로머리 · 묶음1 · 묶음2 · 이름 · 란번호 · 금액 · 세율 · 세액

예정신고 누락분만 묶음을 둘 씁니다((7)매출 → 과세/영세율). 나머지는 묶음이 하나거나
없어서 `colspan` 으로 메웁니다. **머리행의 「구 분」도 네 칸을 덮어야 합니다.**
한때 두 칸만 덮어 놓아서 금액·세율·세액 머리가 한 칸씩 왼쪽으로 밀려 있었습니다.
란번호 위에 「금 액」이 오고 세액 값은 머리 없는 칸에 놓였습니다.

칸 이름과 세율은 서식 원문을 그대로 옮긴 것입니다. 서식이 개정되면 이 파일을 고칩니다.

> **(41)~(43) 묶음 이름은 「(13)매입」입니다.** 홈택스 출력물은 「(12)매입」으로 찍는데
> 서식 원문과 작성방법 제2쪽 바목(「(13)란 … 제4쪽 (43)합계란의 금액과 세액을 적습니다」)이
> (13)이라서 원문을 따릅니다. 홈택스가 옛 번호를 남겨 둔 것으로 보입니다.
"""

# (란, 이름, 세율, 묶음). 묶음이 문자열이면 그 줄에서 세로 머리를 열고,
# 빈 문자열이면 앞 묶음에 이어지고, None 이면 묶음이 없어 이름이 세 칸을 먹는다
GASAN = [
    ("(64)", "사업자미등록 등", "뒤쪽참조", None),
    ("(65)", "지연발급 등", "1/100", "세금계산서"),
    ("(66)", "지연수취", "5/1,000", ""),
    ("(67)", "미발급 등", "2/100", ""),
    ("(68)", "가공 발급ㆍ수취 등", "4/100", ""),
    ("(69)", "지연전송", "3/1,000", "전자세금계산서<br>발급명세 전송"),
    ("(70)", "미전송", "5/1,000", ""),
    ("(71)", "제출 불성실", "5/1,000", "세금계산서<br>합계표"),
    ("(72)", "지연제출", "3/1,000", ""),
    ("(73)", "무신고(일반)", "뒤쪽참조", "신고 불성실"),
    ("(74)", "무신고(부당)", "뒤쪽참조", ""),
    ("(75)", "과소ㆍ초과환급신고(일반)", "뒤쪽참조", ""),
    ("(76)", "과소ㆍ초과환급신고(부당)", "뒤쪽참조", ""),
    ("(77)", "납부지연", "뒤쪽참조", None),
    ("(78)", "영세율 과세표준신고 불성실", "5/1,000", None),
    ("(79)", "현금매출명세서 불성실", "1/100", None),
    ("(80)", "부동산임대공급가액명세서 불성실", "1/100", None),
    ("(81)", "거래계좌 미사용", "뒤쪽참조", "매입자 납부특례"),
    ("(82)", "거래계좌 지연입금", "뒤쪽참조", ""),
    ("(83)", "신용카드매출전표등 수령명세서 미제출ㆍ과다기재", "5/1,000", None),
]
SPAN = {"세금계산서": 4, "전자세금계산서<br>발급명세 전송": 2,
        "세금계산서<br>합계표": 2, "신고 불성실": 4, "매입자 납부특례": 2}

CSS = """
.pbrk{page-break-before:always}
.p2note{font-size:9pt; font-weight:700; margin:1mm 0}
table.p2 th.side{font-size:8.5pt; line-height:1.25}
table.p2 th.side2{font-size:8.5pt; line-height:1.25}
table.p2 td.rate,table.p2 th.rate{font-size:7.5pt}
table.p2 .gray{background:#E8E8E8}
"""


def page2(rows, p2, 사업자번호):
    from form21 import esc, won, biz

    d = {r[0]: r for r in rows}

    def v(k, i):
        return d[k][i] if k in d and isinstance(d[k][i], int) else 0

    g = p2.get
    l15s, l15t = v("(15)", 2), v("(15)", 3)
    fix_s, fix_t = g("고정자산 카드매입", (0, 0))
    gen_s, gen_t = l15s - fix_s, l15t - fix_t
    l17s, l17t = v("(17)", 2), v("(17)", 3)
    l19 = v("(19)", 3)
    free = v("면세", 2)

    def tail(no, sup, rate=None, tax=0, sup_gray=False, tax_gray=False):
        """란번호 · 금액 · 세율 · 세액 네 칸. 적지 않는 칸은 회색으로 막는다."""
        sc = ("<td class='n gray'></td>" if sup_gray
              else f"<td class='n'>{won(sup)}</td>")
        rc = (f"<td class='c rate'>{rate}</td>" if rate
              else "<td class='c gray'></td>")
        tc = ("<td class='n gray'></td>" if tax_gray
              else f"<td class='n'>{won(tax)}</td>")
        return f"<td class='c'>{no}</td>{sc}{rc}{tc}"

    def head(span, title):
        return (f"<tr><th rowspan='{span}' class='side'>{title}</th>"
                "<th colspan='4'>구 분</th><th>금 액</th><th>세율</th>"
                "<th>세 액</th></tr>")

    b = ['<div class="pbrk"></div>',
         '<div class="fnote"><span></span><span>(제2장 앞쪽)</span></div>',
         '<div class="p2note">※ 이 쪽은 해당 사항이 있는 사업자만 사용합니다.</div>',
         "<table><tr><th style='width:16%'>사업자등록번호</th>"
         f"<td class='c' style='width:26%'>{esc(biz(사업자번호))}</td>"
         "<td class='l' style='border:none'>*사업자등록번호는 반드시 적으시기 "
         "바랍니다.</td></tr></table>",
         "<table class='p2'><colgroup>"
         "<col style='width:12%'><col style='width:9%'><col style='width:8%'>"
         "<col style='width:17%'><col style='width:6%'><col style='width:20%'>"
         "<col style='width:9%'><col style='width:19%'></colgroup>"]

    # ── 예정신고 누락분 명세 (36)~(43) · 묶음이 둘인 유일한 구간 ──
    b.append(head(9, "예정신고<br>누 락 분<br>명 세"))
    b.append("<tr><th rowspan='5' class='side2'>(7)매출</th>"
             "<th rowspan='2' class='side2'>과세</th>"
             "<td class='l'>세 금 계 산 서</td>"
             + tail("(36)", 0, "10/100", 0) + "</tr>")
    b.append("<tr><td class='l'>기 타</td>" + tail("(37)", 0, "10/100", 0) + "</tr>")
    b.append("<tr><th rowspan='2' class='side2'>영세율</th>"
             "<td class='l'>세 금 계 산 서</td>"
             + tail("(38)", 0, "0/100", 0, tax_gray=True) + "</tr>")
    b.append("<tr><td class='l'>기 타</td>"
             + tail("(39)", 0, "0/100", 0, tax_gray=True) + "</tr>")
    b.append("<tr><td class='l' colspan='2'>합 계</td>" + tail("(40)", 0) + "</tr>")
    b.append("<tr><th rowspan='3' class='side2'>(13)매입</th>"
             "<td class='l' colspan='2'>세 금 계 산 서</td>"
             + tail("(41)", 0) + "</tr>")
    b.append("<tr><td class='l' colspan='2'>그 밖의 공제매입세액</td>"
             + tail("(42)", 0) + "</tr>")
    b.append("<tr><td class='l' colspan='2'>합 계</td>" + tail("(43)", 0) + "</tr>")

    # ── (15) 그 밖의 공제매입세액 명세 (44)~(52) ──
    b.append(head(10, "(15)<br>그 밖의 공제<br>매 입 세 액<br>명 세"))
    b.append("<tr><th rowspan='2' colspan='2' class='side2'>신용카드매출전표등<br>"
             "수령명세서 제출분</th><td class='l'>일반매입</td>"
             + tail("(44)", gen_s, None, gen_t) + "</tr>")
    b.append("<tr><td class='l'>고정자산매입</td>"
             + tail("(45)", fix_s, None, fix_t) + "</tr>")
    for no, lb, rate, blocked in [
            ("(46)", "의제매입세액", "뒤쪽 참조", False),
            ("(47)", "재활용폐자원등 매입세액", "뒤쪽 참조", False),
            ("(48)", "과세사업전환 매입세액", None, True),
            ("(49)", "재고매입세액", None, True),
            ("(50)", "변제대손세액", None, True),
            ("(51)", "외국인 관광객에 대한 환급세액", None, True)]:
        b.append(f"<tr><td class='l' colspan='3'>{lb}</td>"
                 + tail(no, 0, rate, 0, sup_gray=blocked) + "</tr>")
    b.append("<tr><td class='l' colspan='3'>합 계</td>"
             + tail("(52)", l15s, None, l15t) + "</tr>")

    # ── (17) 공제받지 못할 매입세액 명세 (53)~(56) ──
    b.append(head(5, "(17)<br>공제받지<br>못 할<br>매입세액<br>명 세"))
    for no, lb, sup, tax in [("(53)", "공제받지 못할 매입세액", l17s, l17t),
                             ("(54)", "공통매입세액 중 면세사업등 해당 세액", 0, 0),
                             ("(55)", "대손처분받은 세액", 0, 0),
                             ("(56)", "합 계", l17s, l17t)]:
        b.append(f"<tr><td class='l' colspan='3'>{lb}</td>"
                 + tail(no, sup, None, tax) + "</tr>")

    # ── (19) 그 밖의 경감·공제세액 명세 (57)~(63) ──
    b.append(head(8, "(19)<br>그 밖의<br>경감ㆍ공제<br>세액 명세"))
    for no, lb, tax in [("(57)", "전자신고 세액공제", l19),
                        ("(58)", "전자세금계산서 발급세액 공제", 0),
                        ("(59)", "일반택시 운송사업자 경감세액", 0),
                        ("(60)", "대리납부 세액공제", 0),
                        ("(61)", "현금영수증사업자 세액공제", 0),
                        ("(62)", "기타", 0),
                        ("(63)", "합 계", l19)]:
        b.append(f"<tr><td class='l' colspan='3'>{lb}</td>"
                 + tail(no, 0, None, tax, sup_gray=True) + "</tr>")

    # ── (29) 가산세액 명세 (64)~(84) ──
    b.append(head(22, "(29)<br>가산세액 명세"))
    for no, lb, rate, grp in GASAN:
        if grp:
            cell = f"<th rowspan='{SPAN[grp]}' colspan='2' class='side2'>{grp}</th>"
            name = f"<td class='l'>{lb}</td>"
        elif grp == "":
            cell = ""
            name = f"<td class='l'>{lb}</td>"
        else:
            cell = ""
            name = f"<td class='l' colspan='3'>{lb}</td>"
        b.append("<tr>" + cell + name + tail(no, 0, rate, 0) + "</tr>")
    b.append("<tr><td class='l' colspan='3'>합 계</td>"
             + tail("(84)", 0, None, 0, sup_gray=True) + "</tr>")

    # ── 면세사업 수입금액 (85)~(88) ──
    b.append("<tr><th rowspan='5' class='side'>면세사업<br>수입금액</th>"
             "<th colspan='2'>업 태</th><th colspan='2'>종 목</th>"
             "<th>코드번호</th><th colspan='2'>금 액</th></tr>")
    b.append(f"<tr><td class='c'>(85)</td><td class='c'>{esc(g('면세 업태', ''))}</td>"
             f"<td class='c' colspan='2'>{esc(g('면세 종목', ''))}</td>"
             f"<td class='c'>{esc(g('면세 업종코드', ''))}</td>"
             f"<td class='n' colspan='2'>{won(free)}</td></tr>")
    b.append("<tr><td class='c'>(86)</td><td></td><td colspan='2'></td><td></td>"
             "<td class='n' colspan='2'></td></tr>")
    b.append("<tr><td class='c'>(87)</td><td class='l' colspan='4'>수입금액 제외"
             "</td><td class='n' colspan='2'></td></tr>")
    b.append("<tr><td class='l' colspan='5'>(88) 합 계</td>"
             f"<td class='n' colspan='2'>{won(free)}</td></tr>")

    # ── 계산서 발급 및 수취 명세 (89)(90) ──
    b.append("<tr><th rowspan='2' class='side'>계산서 발급<br>및 수취 명세</th>"
             "<td class='l' colspan='4'>(89) 계산서 발급금액</td>"
             f"<td class='n' colspan='2'>{won(g('계산서 발급', 0))}</td></tr>")
    b.append("<tr><td class='l' colspan='4'>(90) 계산서 수취금액</td>"
             f"<td class='n' colspan='2'>{won(g('계산서 수취', 0))}</td></tr>")
    b.append("</table>")
    b.append('<div class="ftail">210mm×297mm[백상지(80g/㎡) 또는 '
             '중질지(80g/㎡)]</div>')
    return "".join(b)
