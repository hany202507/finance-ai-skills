# -*- coding: utf-8 -*-
"""부속명세서를 공식 서식 모양으로 그린다.

원문은 국가법령정보센터의 서식 PDF 여덟 종이다(assets/_받기.py --all 로 받는다).
제출자 인적사항·총합계·명세의 칸 구성과 동그라미 번호를 그대로 옮겼다.

| 서식 | 개정 |
|---|---|
| 별지 제38호서식(1) 매출처별 세금계산서합계표(갑) | 2024. 3. 22. |
| 별지 제39호서식(1) 매입처별 세금계산서합계표(갑) | 2024. 3. 22. |
| 별지 제16호서식(1) 신용카드매출전표등 수령명세서(갑) | 2019. 3. 20. |
| 별지 제23호서식 신용카드매출전표등 발행금액 집계표 | 2019. 3. 20. |
| 별지 제22호서식 공제받지 못할 매입세액 명세서 | 2026. 3. 20. |
| 별지 제27호서식 건물 등 감가상각자산 취득명세서 | 2025. 7. 4. |
| 별지 제29호서식 영세율 매출명세서 | 2023. 3. 20. |
| 소득세법 시행규칙 별지 제29호서식(1) 매입처별 계산서합계표 | 2023. 3. 20. |

**제출용이 아니다.** 검토·보관용이다.

서식 3번 「전자세금계산서 외 발급분 명세」는 전자분만 있으면 원래 비운다.
검토에는 거래처별 명세가 있어야 해서 그 칸에 적고 아래에 왜 적었는지 한 줄 붙인다.
"""
from form21 import esc, won, biz, CSS as BASE_CSS

CSS = BASE_CSS + """
.att{page-break-before:always}
.att:first-of-type{page-break-before:auto}
.atitle{text-align:center; font-size:14pt; font-weight:700; letter-spacing:.04em;
        margin:1mm 0 .5mm}
.aperiod{text-align:center; font-size:8.6pt; letter-spacing:.15em; margin-bottom:1.5mm}
.anum{font-weight:700; font-size:8.4pt; margin:2.5mm 0 1mm}
.side{font-size:7pt; text-align:right; margin-bottom:.8mm}
.why{font-size:7.2pt; color:#444; margin:.8mm 0 2mm}
.decl{font-size:7.6pt; line-height:1.6; margin-top:3mm}
"""

HEAD_FMT = ('<div class="fhead">■ {law} 시행규칙 [별지 제{no}호서식{sub}] '
            '&lt;개정 {rev}&gt; &nbsp;&nbsp;&nbsp; '
            '홈택스(www.hometax.go.kr)에서도 신청할 수 있습니다.</div>')


def _head(no, rev, title, period, *, law="부가가치세법", sub="", side="(앞쪽)"):
    return (HEAD_FMT.format(law=law, no=no, sub=sub, rev=rev)
            + f'<div class="atitle">{esc(title)}</div>'
            + f'<div class="aperiod">{esc(period)}</div>'
            + f'<div class="side">{esc(side)}</div>')


def _person(company, 사업자번호, 대표자, 주소="", 거래기간="", 작성일="", *, full=True):
    """1. 제출자 인적사항. 서식마다 칸이 조금씩 다르지만 골격은 같다."""
    b = ['<div class="anum">1. 제출자 인적사항</div><table>'
         "<tr><th style='width:17%'>① 사업자등록번호</th>"
         f"<td class='c' style='width:33%'>{esc(biz(사업자번호))}</td>"
         "<th style='width:17%'>② 상호(법인명)</th>"
         f"<td class='l'>{esc(company)}</td></tr>"
         "<tr><th>③ 성명(대표자)</th>"
         f"<td class='l'>{esc(대표자)}</td>"
         "<th>④ 사업장 소재지</th>"
         f"<td class='l'>{esc(주소)}</td></tr>"]
    if full:
        b.append(f"<tr><th>⑤ 거래기간</th><td class='c'>{esc(거래기간)}</td>"
                 f"<th>⑥ 작성일</th><td class='c'>{esc(작성일)}</td></tr>")
    b.append("</table>")
    return "".join(b)


def _sum_block(title, 처수라벨, cnt, mae, sup, tax=None):
    """2. 총합계. 전자분에 전부 들어가고 그 외 발급분은 0 이다."""
    tax_th = "<th style='width:20%'>⑩ 세 액</th>" if tax is not None else ""
    def row(label, c, m, s, t, bold=False):
        cls = " class='sum'" if bold else ""
        tc = f"<td class='n'>{won(t)}</td>" if tax is not None else ""
        return (f"<tr{cls}>{label}<td class='n'>{won(c)}</td><td class='n'>{won(m)}</td>"
                f"<td class='n'>{won(s)}</td>{tc}</tr>")
    b = [f'<div class="anum">{title}</div><table>'
         "<tr><th colspan='2' style='width:30%'>구 분</th>"
         f"<th style='width:10%'>⑦ {처수라벨}</th><th style='width:8%'>⑧ 매수</th>"
         f"<th style='width:22%'>⑨ 공급가액</th>{tax_th}</tr>"]
    b.append(row("<td class='c' colspan='2'><b>합 계</b></td>", cnt, mae, sup, tax, True))
    b.append("<tr><td class='c' rowspan='3' style='width:20%'>과세기간 종료일 다음 달"
             " 11일까지 전송된 전자세금계산서 발급분</td>"
             "<td class='c' style='width:10%'>사업자등록번호 발급분</td>"
             f"<td class='n'>{won(cnt)}</td><td class='n'>{won(mae)}</td>"
             f"<td class='n'>{won(sup)}</td>"
             + (f"<td class='n'>{won(tax)}</td>" if tax is not None else "") + "</tr>")
    for lab in ("주민등록번호 발급분", "소 계"):
        v = (cnt, mae, sup, tax) if lab == "소 계" else (0, 0, 0, 0 if tax is not None else None)
        b.append(row(f"<td class='c'>{lab}</td>", *v))
    b.append("<tr><td class='c' rowspan='3'>위 전자세금계산서 외의 발급분</td>"
             "<td class='c'>사업자등록번호 발급분</td>"
             f"<td class='n'>0</td><td class='n'>0</td><td class='n'>0</td>"
             + ("<td class='n'>0</td>" if tax is not None else "") + "</tr>")
    for lab in ("주민등록번호 발급분", "소 계"):
        b.append(row(f"<td class='c'>{lab}</td>", 0, 0, 0, 0 if tax is not None else None))
    b.append("</table>")
    return "".join(b)


def _detail(title, rows, 처라벨, *, tax=True, why=""):
    """3. 거래처별 명세."""
    tax_th = "<th style='width:18%'>⑯ 세액</th>" if tax else ""
    b = [f'<div class="anum">{title}</div><table>'
         "<tr><th style='width:6%'>⑪ 번호</th><th style='width:16%'>⑫ 사업자등록번호</th>"
         f"<th style='width:24%'>⑬ {처라벨}</th><th style='width:7%'>⑭ 매수</th>"
         f"<th style='width:20%'>⑮ 공급가액</th>{tax_th}<th>비고</th></tr>"]
    for k, r in enumerate(rows, 1):
        tc = f"<td class='n'>{won(r['세액'])}</td>" if tax else ""
        b.append(f"<tr><td class='c'>{k}</td>"
                 f"<td class='c'>{esc(biz(r['사업자등록번호']))}</td>"
                 f"<td class='l'>{esc(r['거래처명'])}</td>"
                 f"<td class='n'>{won(r['매수'])}</td>"
                 f"<td class='n'>{won(r['공급가액'])}</td>{tc}<td></td></tr>")
    tc = (f"<td class='n'>{won(sum(r['세액'] for r in rows))}</td>") if tax else ""
    b.append(f"<tr class='sum'><td class='c' colspan='3'><b>합 계</b></td>"
             f"<td class='n'>{won(sum(r['매수'] for r in rows))}</td>"
             f"<td class='n'>{won(sum(r['공급가액'] for r in rows))}</td>{tc}<td></td></tr>")
    b.append("</table>")
    if why:
        b.append(f'<div class="why">{esc(why)}</div>')
    return "".join(b)


TAIL = '<div class="ftail">210mm×297mm[백상지 80g/㎡ 또는 중질지 80g/㎡]</div>'
WHY_E = ("전자세금계산서 발급분이라 이 칸은 원래 비웁니다. "
         "검토에 거래처별 명세가 있어야 해서 적었습니다.")


# ── 서식별 ───────────────────────────────────────────────────
def f38(rows, ctx):
    n = len(rows)
    return ("".join([
        _head("38", "2024. 3. 22.", "매출처별 세금계산서합계표(갑)", ctx["period"], sub="(1)"),
        _person(ctx["company"], ctx["biz"], ctx["ceo"], ctx["addr"],
                ctx["range"], ctx["today"]),
        _sum_block("2. 매출세금계산서 총합계", "매출처 수", n,
                   sum(r["매수"] for r in rows), sum(r["공급가액"] for r in rows),
                   sum(r["세액"] for r in rows)),
        _detail("3. 과세기간 종료일 다음 달 11일까지 전송된 전자세금계산서 외 "
                "발급분 매출처별 명세", rows, "상호(법인명)", why=WHY_E),
        TAIL]))


def f39(rows, ctx):
    n = len(rows)
    return ("".join([
        _head("39", "2024. 3. 22.", "매입처별 세금계산서합계표(갑)", ctx["period"], sub="(1)"),
        _person(ctx["company"], ctx["biz"], ctx["ceo"], ctx["addr"],
                ctx["range"], ctx["today"]),
        _sum_block("2. 매입세금계산서 총합계", "매입처 수", n,
                   sum(r["매수"] for r in rows), sum(r["공급가액"] for r in rows),
                   sum(r["세액"] for r in rows)),
        _detail("3. 과세기간 종료일 다음 달 11일까지 전송된 전자세금계산서 외 "
                "발급분 매입처별 명세", rows, "상호(법인명)", why=WHY_E),
        TAIL]))


def f16(rows, ctx):
    카드 = ctx["구분"].get("사업용신용카드", (0, 0, 0))
    현금 = ctx["구분"].get("현금영수증", (0, 0, 0))
    tot = tuple(카드[k] + 현금[k] for k in range(3))

    def r(lab, v):
        return (f"<tr><td class='l'>{lab}</td><td class='n'>{won(v[0])}</td>"
                f"<td class='n'>{won(v[1])}</td><td class='n'>{won(v[2])}</td></tr>")
    b = [_head("16", "2019. 3. 20.", "신용카드매출전표등 수령명세서(갑)", ctx["period"],
               sub="(1)"),
         '<div class="anum">1. 제출자 인적사항</div><table>'
         "<tr><th style='width:17%'>① 상호(법인명)</th>"
         f"<td class='l' style='width:33%'>{esc(ctx['company'])}</td>"
         "<th style='width:17%'>② 사업자등록번호</th>"
         f"<td class='c'>{esc(biz(ctx['biz']))}</td></tr>"
         f"<tr><th>③ 성명(대표자)</th><td class='l' colspan='3'>{esc(ctx['ceo'])}</td></tr>"
         "</table>",
         '<div class="anum">2. 신용카드 등 매입명세 합계</div><table>'
         "<tr><th style='width:34%'>구 분</th><th style='width:18%'>거래건수</th>"
         "<th style='width:24%'>공급가액</th><th>세 액</th></tr>",
         r("<b>④ 합 계</b>", tot), r("⑤ 현금영수증", 현금),
         r("⑥ 화물운전자복지카드", (0, 0, 0)), r("⑦ 사업용 신용카드", 카드),
         r("⑧ 그 밖의 신용카드 등", (0, 0, 0)), "</table>",
         _detail("3. 그 밖의 신용·직불카드, 기명식 선불카드, 직불전자지급수단 및 "
                 "기명식선불전자지급수단 매출전표 수령금액 합계", rows, "공급자(가맹점)",
                 why="사업용 신용카드와 현금영수증은 등록분이라 이 칸을 원래 비웁니다. "
                     "검토에 공급자별 명세가 있어야 해서 적었습니다."),
         TAIL]
    return "".join(b)


def f23(ctx):
    과세공급, 과세세액 = ctx["23과세"]
    면세 = ctx["23면세"]
    카드계 = 과세공급 + 과세세액 + 면세

    def r(lab, tot, card, cash, etc, bold=False):
        c = " class='sum'" if bold else ""
        return (f"<tr{c}><td class='c'>{lab}</td><td class='n'>{won(tot)}</td>"
                f"<td class='n'>{won(card)}</td><td class='n'>{won(cash)}</td>"
                f"<td class='n'>{won(etc)}</td></tr>")
    return "".join([
        _head("23", "2019. 3. 20.", "신용카드매출전표등 발행금액 집계표", ctx["period"],
              side=""),
        '<div class="anum">1. 제출자 인적사항</div><table>'
        "<tr><th style='width:17%'>① 상호(법인명)</th>"
        f"<td class='l' style='width:33%'>{esc(ctx['company'])}</td>"
        "<th style='width:17%'>② 성명(대표자)</th>"
        f"<td class='l'>{esc(ctx['ceo'])}</td></tr>"
        "<tr><th>③ 사업장 소재지</th>"
        f"<td class='l'>{esc(ctx['addr'])}</td>"
        "<th>④ 사업자등록번호</th>"
        f"<td class='c'>{esc(biz(ctx['biz']))}</td></tr></table>",
        '<div class="anum">2. 신용카드매출전표등 발행금액 현황</div><table>'
        "<tr><th style='width:16%'>구분</th><th style='width:21%'>⑤ 합계</th>"
        "<th style='width:21%'>⑥ 신용·직불·<br>기명식 선불카드</th>"
        "<th style='width:21%'>⑦ 현금영수증</th>"
        "<th>⑧ 직불전자지급수단 및<br>기명식선불전자지급수단</th></tr>",
        r("<b>합계</b>", 카드계, 카드계, 0, 0, True),
        r("과세 매출분", 과세공급 + 과세세액, 과세공급 + 과세세액, 0, 0),
        r("면세 매출분", 면세, 면세, 0, 0),
        r("봉사료", 0, 0, 0, 0), "</table>",
        '<div class="anum">3. 신용카드매출전표등 발행금액(⑤ 합계) 중 '
        '세금계산서(계산서) 발급명세</div><table>'
        "<tr><th style='width:28%'>⑨ 세금계산서 발급금액</th>"
        "<td class='n' style='width:22%'>0</td>"
        "<th style='width:28%'>⑩ 계산서 발급금액</th><td class='n'>0</td></tr></table>"
        '<div class="why">과세 매출분은 공급대가(부가가치세 포함)로 적습니다. '
        '3번은 장부에서 알 수 없어 0 으로 둡니다. 카드 결제분에 세금계산서를 '
        '함께 발급한 건이 있으면 회계사가 채웁니다(진단항목 D1).</div>',
        TAIL])


DENY_ROWS = [("①", "필요적 기재사항 누락 등"), ("②", "사업과 직접 관련 없는 지출"),
             ("③", "「개별소비세법」 제1조제2항제3호에 따른 자동차 구입·유지 및 임차"),
             ("④", "기업업무추진비 및 이와 유사한 비용 관련"),
             ("⑤", "면세사업등 관련"), ("⑥", "토지의 자본적 지출 관련"),
             ("⑦", "사업자등록 전 매입세액"),
             ("⑧", "금·구리 스크랩 거래계좌 미사용 관련 매입세액")]


def f22(rows, ctx):
    """사유별 합계. rows 의 「사유」는 return_review.deny_mark 가 붙인 ①~⑧ 이다.
    사유가 비었거나 ①~⑧ 밖이면 어느 줄에도 안 들어가 합계와 사유별 합이 어긋난다.
    그 건은 진단항목 C5 가 정지로 세운다."""
    b = [_head("22", "2026. 3. 20.", "공제받지 못할 매입세액 명세서", ctx["period"]),
         '<div class="anum">1. 제출자 인적사항</div><table>'
         "<tr><th style='width:20%'>상호(법인명)</th>"
         f"<td class='l' style='width:30%'>{esc(ctx['company'])}</td>"
         "<th style='width:18%'>성명(대표자)</th>"
         f"<td class='l' style='width:14%'>{esc(ctx['ceo'])}</td>"
         "<th>사업자등록번호</th>"
         f"<td class='c'>{esc(biz(ctx['biz']))}</td></tr></table>",
         '<div class="anum">2. 공제받지 못할 매입세액 명세</div><table>'
         "<tr><th rowspan='2' style='width:44%'>매입세액 불공제 사유</th>"
         "<th colspan='3'>세금계산서</th><th rowspan='2' style='width:10%'>비고</th></tr>"
         "<tr><th style='width:9%'>매수</th><th style='width:19%'>공급가액</th>"
         "<th style='width:18%'>매입세액</th></tr>"]
    tot = [0, 0]
    for mk, nm in DENY_ROWS:
        hit = [r for r in rows if r.get("사유") == mk]
        c = sum(r["매수"] for r in hit)
        s_ = sum(r["공급가액"] for r in hit)
        t = sum(r["세액"] for r in hit)
        tot[0] += s_
        tot[1] += t
        b.append(f"<tr><td class='l'>{mk} {esc(nm)}</td><td class='n'>{won(c)}</td>"
                 f"<td class='n'>{won(s_)}</td><td class='n'>{won(t)}</td><td></td></tr>")
    b.append(f"<tr class='sum'><td class='l'><b>⑨ 합계</b></td>"
             f"<td class='n'>{won(sum(r['매수'] for r in rows))}</td>"
             f"<td class='n'>{won(tot[0])}</td><td class='n'>{won(tot[1])}</td>"
             f"<td></td></tr></table>")
    if not rows:
        b.append('<div class="why">해당 건이 없습니다. 세금계산서를 받아 (10)(12)에 '
                 '넣었다가 (17)에서 빼는 건만 적습니다. 카드로 결제한 불공제는 애초에 '
                 '(15)에 넣지 않는 것으로 끝나 여기 적지 않습니다. '
                 '적으면 합계가 (17)과 안 맞습니다.</div>')
    b.append('<div class="anum">3. 공통매입세액 안분 계산 명세</div>'
             '<div class="why">장부만으로는 안분 대상을 정하지 않습니다. 과세사업과 '
             '면세사업에 함께 쓰는 매입이 있으면 회계사가 따로 계산해 적습니다.</div>')
    b.append(TAIL)
    return "".join(b)


def f27(rows, ctx):
    c = sum(r["매수"] for r in rows)
    s_ = sum(r["공급가액"] for r in rows)
    t = sum(r["세액"] for r in rows)

    def row(lab, cc, ss, tt, bold=False):
        k = " class='sum'" if bold else ""
        return (f"<tr{k}><td class='l'>{lab}</td><td class='n'>{won(cc)}</td>"
                f"<td class='n'>{won(ss)}</td><td class='n'>{won(tt)}</td><td></td></tr>")
    return "".join([
        _head("27", "2025. 7. 4.", "건물 등 감가상각자산 취득명세서", ctx["period"], side=""),
        "<table><tr><th style='width:14%'>접수번호</th><td style='width:26%'></td>"
        "<th style='width:12%'>접수일</th><td style='width:26%'></td>"
        "<th style='width:12%'>처리기간</th><td class='c'>즉시</td></tr></table>",
        '<div class="anum">1. 제출자 인적사항</div><table>'
        "<tr><th style='width:17%'>① 성명(법인명)</th>"
        f"<td class='l' style='width:33%'>{esc(ctx['company'])}</td>"
        "<th style='width:17%'>② 사업자등록번호</th>"
        f"<td class='c'>{esc(biz(ctx['biz']))}</td></tr>"
        f"<tr><th>③ 업태</th><td class='l'>{esc(ctx.get('업태', ''))}</td>"
        f"<th>④ 종목</th><td class='l'>{esc(ctx.get('종목', ''))}</td></tr></table>",
        '<div class="anum">2. 감가상각자산 취득명세 합계</div><table>'
        "<tr><th style='width:32%'>감가상각자산 종류</th><th style='width:12%'>건수</th>"
        "<th style='width:22%'>공급가액</th><th style='width:20%'>세액</th>"
        "<th>비고</th></tr>",
        row("<b>⑤ 합계</b>", c, s_, t, True),
        row("⑥ 건물·구축물", 0, 0, 0), row("⑦ 기계장치", 0, 0, 0),
        row("⑧ 차량운반구", 0, 0, 0), row("⑨ 그 밖의 감가상각자산", c, s_, t),
        "</table>",
        '<div class="decl">「부가가치세법 시행령」 제90조제3항의 표 제7호, '
        '제91조제2항의 표 제10호 및 제107조제3항에 따라 건물 등 감가상각자산 '
        '취득명세서를 제출합니다.'
        '<div style="text-align:center; margin-top:3mm">년 &nbsp;&nbsp; 월 '
        '&nbsp;&nbsp; 일</div>'
        '<div style="text-align:right">제출자 &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;'
        '(서명 또는 인)</div>'
        '<div style="font-size:9.5pt; font-weight:700; margin-top:2mm">'
        '세 무 서 장 &nbsp;귀하</div></div>',
        TAIL])


ZERO_ART = [
    ("제21조", ["직접수출(대행수출 포함)",
                "중계무역·위탁판매·외국인도 또는 위탁가공무역 방식의 수출",
                "내국신용장·구매확인서에 의하여 공급하는 재화",
                "한국국제협력단, 한국국제보건의료재단 및 대한적십자사에 공급하는 해외반출용 재화",
                "수탁가공무역 수출용으로 공급하는 재화"]),
    ("제22조", ["국외에서 공급하는 용역"]),
    ("제23조", ["선박·항공기에 의한 외국항행용역", "국제복합운송계약에 의한 외국항행용역"]),
    ("제24조", ["국내에서 비거주자·외국법인에 공급되는 재화 또는 용역",
                "수출재화임가공용역", "외국항행 선박·항공기 등에 공급하는 재화 또는 용역",
                "국내 주재 외교공관, 영사기관, 국제연합과 이에 준하는 국제기구, "
                "국제연합군 또는 미합중국군대에 공급하는 재화 또는 용역",
                "「관광진흥법 시행령」에 따른 일반여행업자가 외국인 관광객에게 "
                "공급하는 관광알선용역",
                "외국인전용판매장 또는 주한외국군인 등의 전용 유흥음식점에서 공급하는 "
                "재화 또는 용역",
                "외교관 등에게 공급하는 재화 또는 용역", "외국인환자 유치용역"]),
]


def f29(rows, ctx):
    """영세율 매출명세서. 칸은 rules/영세율_구분.csv 의 「구분」으로 정한다.

    직수출은 제21조 첫 줄, 내국신용장·구매확인서는 제21조 셋째 줄,
    용역의 국외공급은 제22조, 외국항행용역은 제23조 첫 줄이다. 모두 부가가치세법 영세율이다.
    근거조문 문자열로 고르면 내국신용장(시행령 제31조)이 「그 밖의 법률」로 잘못 간다."""
    SLOT = {"직수출": ("제21조", 0), "내국신용장·구매확인서": ("제21조", 2),
            "용역의 국외공급": ("제22조", 0), "외국항행용역": ("제23조", 0)}
    put = {}
    기타 = 0
    for r in rows:
        k = SLOT.get(r["구분"])
        if k:
            put[k] = put.get(k, 0) + r["금액"]
        else:
            기타 += r["금액"]
    부가법 = sum(put.values())
    b = [_head("29", "2023. 3. 20.", "영세율 매출명세서", ctx["period"]),
         '<div class="anum">1. 제출자 인적사항</div><table>'
         "<tr><th style='width:17%'>① 상호(법인명)</th>"
         f"<td class='l' style='width:33%'>{esc(ctx['company'])}</td>"
         "<th style='width:17%'>② 사업자등록번호</th>"
         f"<td class='c'>{esc(biz(ctx['biz']))}</td></tr>"
         f"<tr><th>③ 성명(대표자)</th><td class='l'>{esc(ctx['ceo'])}</td>"
         f"<th>④ 사업장 소재지</th><td class='l'>{esc(ctx['addr'])}</td></tr>"
         f"<tr><th>⑤ 업태</th><td class='l'>{esc(ctx.get('업태', ''))}</td>"
         f"<th>⑥ 종목</th><td class='l'>{esc(ctx.get('종목', ''))}</td></tr></table>",
         '<div class="anum">2. 영세율 적용 공급실적 합계</div><table>'
         "<tr><th style='width:7%'>⑦ 구분</th><th style='width:13%'>⑧ 조문</th>"
         "<th>⑨ 내 용</th><th style='width:20%'>⑩ 금액(원)</th></tr>"]
    first = True
    total_rows = sum(len(v) for _, v in ZERO_ART)
    for art, items in ZERO_ART:
        for k, it in enumerate(items):
            cells = ""
            if first:
                cells += f"<td class='v' rowspan='{total_rows}'>부<br>가<br>가<br>치<br>세<br>법</td>"
                first = False
            if k == 0:
                cells += f"<td class='c' rowspan='{len(items)}'>{esc(art)}</td>"
            amt = put.get((art, k), 0)
            b.append(f"<tr>{cells}<td class='l'>{esc(it)}</td>"
                     f"<td class='n'>{won(amt)}</td></tr>")
    b.append("<tr class='sum'><td class='c' colspan='3'>"
             "<b>⑪ 「부가가치세법」에 따른 영세율 적용 공급실적 합계</b></td>"
             f"<td class='n'>{won(부가법)}</td></tr>")
    b.append("<tr><td class='c' colspan='3'>"
             "⑫ 「조세특례제한법」 및 그 밖의 법률에 따른 영세율 적용 공급실적 합계</td>"
             f"<td class='n'>{won(기타)}</td></tr>")
    b.append("<tr class='sum'><td class='c' colspan='3'>"
             "<b>⑬ 영세율 적용 공급실적 총 합계 ⑪+⑫</b></td>"
             f"<td class='n'>{won(부가법 + 기타)}</td></tr></table>")
    b.append('<div class="why">직수출은 첨부서류로 수출실적명세서(별지 제40호서식(1))를 '
             '같이 내야 합니다. 다른 영세율은 부가가치세법 시행령 제101조 제1항 표의 '
             '서류를 냅니다. 안 내면 그 부분은 신고로 보지 않습니다'
             '(시행령 제91조 제3항 제1호).</div>')
    b.append(TAIL)
    return "".join(b)


def fs29(rows, ctx):
    n = len(rows)
    return "".join([
        _head("29", "2023. 3. 20.", "매입처별 계산서합계표(갑)", ctx["period"],
              law="소득세법", sub="(1)", side="(3쪽 중 제1쪽)"),
        _person(ctx["company"], ctx["biz"], ctx["ceo"], ctx["addr"],
                ctx["range"], ctx["today"]),
        _sum_block("2. 매입계산서 총합계", "매입처 수", n,
                   sum(r["매수"] for r in rows), sum(r["공급가액"] for r in rows)),
        _detail("3. 과세기간 종료일 다음 달 11일까지 전송된 전자계산서 외 "
                "발급분 매입처별 명세", rows, "상호(법인명)", tax=False, why=WHY_E),
        '<div class="why">면세 매입이라 부가가치세 본지의 매입란에는 올라가지 '
        '않습니다. 매입처별 세금계산서합계표(별지 제39호서식)에 넣으면 (10)과 '
        '안 맞습니다.</div>',
        TAIL])


ORDER = [("38호_매출처별", f38), ("39호_매입처별", f39), ("16호_수령명세서", f16),
         ("23호_발행금액집계표", None), ("22호_공제받지못할", f22),
         ("27호_건물등취득", f27), ("29호_영세율매출명세서", f29),
         ("소득29호_계산서", fs29)]


def build(company, period, att, ver, ctx):
    """부속명세 전체. 서식마다 한 쪽씩, 맨 앞에 본지 대사표를 둔다."""
    tr = []
    for c in ver:
        gs, gv = c["공급가액 차이"], c["세액 차이"]
        tr.append(
            f"<tr><td class='c'>{esc(c['검사'])}</td><td class='l'>{esc(c['무엇'])}</td>"
            f"<td class='n'>{won(c['부속명세 공급가액'])}</td>"
            f"<td class='n'>{won(c['본지 공급가액'])}</td>"
            f"<td class='n{' neg' if gs else ''}'>"
            f"{format(gs, '+,') if gs else '0'}</td>"
            f"<td class='n'>{won(c['부속명세 세액'])}</td>"
            f"<td class='n'>{won(c['본지 세액'])}</td>"
            f"<td class='n{' neg' if gv else ''}'>"
            f"{'-' if gv is None else (format(gv, '+,') if gv else '0')}</td></tr>")
    pages = ['<div class="att"><div class="atitle">부가가치세 신고 부속명세서</div>'
             f'<div class="aperiod">{esc(company)} · {esc(period)}</div>'
             '<div class="anum">본지 대사</div><table>'
             "<tr><th style='width:6.5%'>검사</th><th style='width:25%'>무엇</th>"
             "<th>부속명세 공급가액</th><th>본지 공급가액</th><th style='width:9%'>차이</th>"
             "<th>부속명세 세액</th><th>본지 세액</th><th style='width:8%'>차이</th></tr>"
             + "".join(tr) + "</table>"
             '<div class="why">공급가액과 세액이 전부 0원이어야 합니다. '
             '공급가액만 보면 건별 반올림으로 생긴 세액 차이가 안 잡힙니다.</div>'
             '<div class="foot">부가세신고서검토 스킬이 만들었습니다. '
             '제출용이 아니라 검토·보관용입니다. 서식은 원문의 칸 구성을 옮긴 것입니다.'
             '</div></div>']
    for name, fn in ORDER:
        rows = att.get(name, [])
        html = f23(ctx) if name.startswith("23호") else fn(rows, ctx)
        pages.append(f'<div class="att">{html}</div>')
    return (f"<!doctype html><html lang='ko'><head><meta charset='utf-8'>"
            f"<title>{esc(company)} {esc(period)} 부속명세서</title>"
            f"<style>{CSS}</style></head><body>{''.join(pages)}</body></html>")
