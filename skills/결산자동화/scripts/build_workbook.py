# -*- coding: utf-8 -*-
"""결산확정 워크북(8시트, 전부 수식) + 더존 업로드 2종 생성.

산출물(설계서 §8):
  결산확정_{기간}.xlsx           — 분개장·결산조정분개·시산표·손익계산서·재무상태표·현금흐름표_직접법·근거·검증리포트
  일반전표_업로드_더존_{기간}.xlsx  — 값·숫자형
  매입매출전표_업로드_더존_{기간}.xlsx — 값·숫자형·per-invoice

시산표는 분개장을 SUMIFS로, 재무제표는 시산표 셀을 참조한다(하드코딩 금지).
분개 한 줄을 고치면 시산표→재무제표까지 자동 재계산된다.
"""
import sys, os, importlib
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from close_engine import Engine, to_int

HDR = Font(bold=True, color="FFFFFF")
HFILL = PatternFill("solid", fgColor="305496")
SUB = Font(bold=True)
YEL = PatternFill("solid", fgColor="FFF2CC")
GRN = PatternFill("solid", fgColor="E2EFDA")
thin = Side(style="thin", color="BFBFBF")
BORD = Border(left=thin, right=thin, top=thin, bottom=thin)
WON = '#,##0'

def style_header(ws, row, ncol):
    for c in range(1, ncol + 1):
        cell = ws.cell(row=row, column=c)
        cell.font = HDR; cell.fill = HFILL
        cell.alignment = Alignment(horizontal="center", vertical="center")

def col(n):
    from openpyxl.utils import get_column_letter
    return get_column_letter(n)

# ================================================================= 워크북
def build(eng, out_path, period):
    P = eng.P
    wb = openpyxl.Workbook()

    # ---------------- 1) 분개장
    ws = wb.active; ws.title = "분개장"
    heads = ["전표No","일자","구분","계정코드","계정","차변","대변","현금흐름","분류","적요","거래처"]
    ws.append(heads); style_header(ws, 1, len(heads))
    for l in eng.J:
        ws.append([l["no"], l["date"], l["gubun"], l["code"], l["acct"],
                   l["debit"] or None, l["credit"] or None, l["cf"], l["cls"], l["desc"], l["party"]])
    last = ws.max_row
    ws.append(["", "", "", "", "합계", f"=SUM(F2:F{last})", f"=SUM(G2:G{last})"])
    for r in range(2, ws.max_row + 1):
        ws.cell(r, 6).number_format = WON; ws.cell(r, 7).number_format = WON
    JN = last  # 분개장 데이터 마지막 행

    # ---------------- 2) 결산조정분개
    wa = wb.create_sheet("결산조정분개")
    h2 = ["조정번호","일자","계정코드","계정","차변","대변","적요"]
    wa.append(h2); style_header(wa, 1, len(h2))
    for a in eng.ADJ:
        wa.append([a[0], a[1], a[2], a[3], a[4] or None, a[5] or None, a[6]])
    la = wa.max_row
    wa.append(["","","","합계", f"=SUM(E2:E{la})", f"=SUM(F2:F{la})"])
    for r in range(2, wa.max_row + 1):
        wa.cell(r, 5).number_format = WON; wa.cell(r, 6).number_format = WON

    # ---------------- 3) 시산표
    wt = wb.create_sheet("시산표")
    h3 = ["코드","계정","기초잔액","기중차변","기중대변","조정차변","조정대변","기말잔액"]
    wt.append(h3); style_header(wt, 1, len(h3))
    # 코드→계정명(분개장 우선, 조정 보완)
    names = {}
    for l in eng.J: names.setdefault(l["code"], l["acct"])
    for a in eng.ADJ: names.setdefault(a[2], a[3])
    codes = sorted(names)
    ts_row = {}
    for code in codes:
        r = wt.max_row + 1; ts_row[code] = r
        wt.append([code, names[code],
            f'=SUMIFS(분개장!$F$2:$F${JN},분개장!$D$2:$D${JN},$A{r},분개장!$C$2:$C${JN},"전기이월")-SUMIFS(분개장!$G$2:$G${JN},분개장!$D$2:$D${JN},$A{r},분개장!$C$2:$C${JN},"전기이월")',
            f'=SUMIFS(분개장!$F$2:$F${JN},분개장!$D$2:$D${JN},$A{r},분개장!$C$2:$C${JN},"<>전기이월")',
            f'=SUMIFS(분개장!$G$2:$G${JN},분개장!$D$2:$D${JN},$A{r},분개장!$C$2:$C${JN},"<>전기이월")',
            f'=SUMIFS(결산조정분개!$E$2:$E${la},결산조정분개!$C$2:$C${la},$A{r})',
            f'=SUMIFS(결산조정분개!$F$2:$F${la},결산조정분개!$C$2:$C${la},$A{r})',
            f'=C{r}+D{r}-E{r}+F{r}-G{r}'])
    tot = wt.max_row + 1
    wt.append(["", "합계",
        f"=SUM(C2:C{tot-1})", f"=SUM(D2:D{tot-1})", f"=SUM(E2:E{tot-1})",
        f"=SUM(F2:F{tot-1})", f"=SUM(G2:G{tot-1})", f"=SUM(H2:H{tot-1})"])
    for r in range(2, wt.max_row + 1):
        for cc in range(3, 9): wt.cell(r, cc).number_format = WON
    wt.cell(tot, 2).font = SUB
    def H(code): return f"시산표!$H${ts_row[code]}"
    def C(code): return f"시산표!$C${ts_row[code]}"

    # ---------------- 4) 손익계산서
    wi = wb.create_sheet("손익계산서")
    wi.append(["과목","금액","비고"]); style_header(wi, 1, 3)
    rowmap = {}
    def IS(label, formula, note="", bold=False):
        wi.append([label, formula, note]); r = wi.max_row
        wi.cell(r, 2).number_format = WON
        if bold:
            wi.cell(r, 1).font = SUB; wi.cell(r, 2).font = SUB
        return r
    _s401 = H(401) if 401 in ts_row else "0"
    _s404 = H(404) if 404 in ts_row else "0"
    r_sales = IS("I. 매출액", f"=-({_s401}+{_s404})", "", True)
    if 401 in ts_row: IS(f"   {names[401]}", f"=-{H(401)}")
    if 404 in ts_row: IS(f"   {names[404]}", f"=-{H(404)}")
    r_cogs = IS("II. 매출원가", f"=({H(451) if 451 in ts_row else '0'}+{H(452) if 452 in ts_row else '0'})", "", True)
    if 451 in ts_row: IS("   상품매출원가", f"=+{H(451)}")
    if 452 in ts_row: IS("   식자재비", f"=+{H(452)}")
    r_gp = IS("III. 매출총이익", f"=B{r_sales}-B{r_cogs}", "", True)
    sga = [c for c in codes if 800 <= c < 900]
    r_sga = IS("IV. 판매비와관리비", "=" + "+".join(H(c) for c in sga), "", True)
    for c in sga: IS(f"   {names[c]}", f"=+{H(c)}")
    r_op = IS("V. 영업이익", f"=B{r_gp}-B{r_sga}", "", True)
    r_oi = IS("VI. 영업외수익", f"=-{H(901)}" if 901 in ts_row else "=0", "", True)
    if 901 in ts_row: IS("   이자수익", f"=-{H(901)}")
    r_oe = IS("VII. 영업외비용", f"=+{H(951)}" if 951 in ts_row else "=0", "", True)
    if 951 in ts_row: IS("   이자비용", f"=+{H(951)}")
    r_bt = IS("VIII. 법인세비용차감전순이익", f"=B{r_op}+B{r_oi}-B{r_oe}", "", True)
    r_tax = IS("IX. 법인세비용", f"=+{H(998)}" if 998 in ts_row else "=0",
              "998 계상분. 없으면 연말 확정 - 확인사항")
    r_ni = IS("X. 당기순이익", f"=B{r_bt}-B{r_tax}", "", True)
    NI = f"손익계산서!$B${r_ni}"

    # ---------------- 5) 재무상태표
    wb2 = wb.create_sheet("재무상태표")
    wb2.append(["과목","기초","증감","기말"]); style_header(wb2, 1, 4)
    def BS(label, base, end, bold=False):
        wb2.append([label, base, "" if base=="" else f"=D{wb2.max_row+1}-B{wb2.max_row+1}", end])
        r = wb2.max_row
        wb2.cell(r,3).value = "" if base=="" else f"=D{r}-B{r}"
        for cc in (2,3,4): wb2.cell(r,cc).number_format = WON
        if bold:
            for cc in range(1,5): wb2.cell(r,cc).font = SUB
        return r
    assets = [c for c in codes if 100 <= c < 250]
    liabs  = [c for c in codes if 250 <= c < 331]
    equity = [c for c in codes if 331 <= c < 400]
    wb2.append(["[자산]"]); wb2.cell(wb2.max_row,1).font = SUB
    a_rows = []
    for c in assets:
        r = BS(f"  {names[c]}", f"=+{C(c)}", f"=+{H(c)}"); a_rows.append(r)
    r_at = BS("자산총계", "=" + "+".join(f"B{r}" for r in a_rows), "=" + "+".join(f"D{r}" for r in a_rows), True)
    wb2.append(["[부채]"]); wb2.cell(wb2.max_row,1).font = SUB
    l_rows = []
    for c in liabs:
        r = BS(f"  {names[c]}", f"=-{C(c)}", f"=-{H(c)}"); l_rows.append(r)
    r_lt = BS("부채총계", "=" + "+".join(f"B{r}" for r in l_rows), "=" + "+".join(f"D{r}" for r in l_rows), True)
    wb2.append(["[자본]"]); wb2.cell(wb2.max_row,1).font = SUB
    e_rows = []
    for c in equity:
        r = BS(f"  {names[c]}", f"=-{C(c)}", f"=-{H(c)}"); e_rows.append(r)
    r_ni2 = BS("  당기순이익", "=0", f"={NI}"); e_rows.append(r_ni2)
    r_et = BS("자본총계", "=" + "+".join(f"B{r}" for r in e_rows), "=" + "+".join(f"D{r}" for r in e_rows), True)
    r_le = BS("부채와자본총계", f"=B{r_lt}+B{r_et}", f"=D{r_lt}+D{r_et}", True)

    # ---------------- 6) 현금흐름표_직접법
    wc = wb.create_sheet("현금흐름표_직접법")
    wc.append(["구분","항목","금액"]); style_header(wc, 1, 3)
    tags = []
    for l in eng.J:
        if l["cf"] and l["cf"] not in tags: tags.append(l["cf"])
    op = [t for t in tags if t.startswith("영업")]
    inv = [t for t in tags if t.startswith("투자")]
    fin = [t for t in tags if t.startswith("재무")]
    # 어디에도 안 붙는 태그는 버리지 않는다. 버리면 기말현금이 조용히 어긋난다
    etc = [t for t in tags if t not in op and t not in inv and t not in fin]
    def CF(sec, tag):
        f = f'=SUMIFS(분개장!$F$2:$F${JN},분개장!$H$2:$H${JN},"{tag}")-SUMIFS(분개장!$G$2:$G${JN},분개장!$H$2:$H${JN},"{tag}")'
        wc.append([sec, tag, f]); r = wc.max_row; wc.cell(r,3).number_format = WON; return r
    wc.append(["[영업활동]"]); wc.cell(wc.max_row,1).font = SUB
    op_rows = [CF("영업", t) for t in op]
    inv_rows = []
    if inv:
        wc.append(["[투자활동]"]); wc.cell(wc.max_row,1).font = SUB
        inv_rows = [CF("투자", t) for t in inv]
    wc.append(["[재무활동]"]); wc.cell(wc.max_row,1).font = SUB
    fin_rows = [CF("재무", t) for t in fin]
    etc_rows = []
    if etc:
        wc.append(["[분류 미정]"]); wc.cell(wc.max_row,1).font = SUB
        etc_rows = [CF("미정", t) for t in etc]
    all_rows = op_rows + inv_rows + fin_rows + etc_rows
    r_net = wc.max_row + 1
    wc.append(["", "현금 순증감", "=" + "+".join(f"C{r}" for r in all_rows)]); wc.cell(r_net,3).number_format=WON; wc.cell(r_net,2).font=SUB
    r_beg = wc.max_row + 1
    wc.append(["", "기초현금", f"=+{C(103)}"]); wc.cell(r_beg,3).number_format=WON
    r_end = wc.max_row + 1
    wc.append(["", "기말현금", f"=C{r_net}+C{r_beg}"]); wc.cell(r_end,3).number_format=WON; wc.cell(r_end,2).font=SUB
    CF_END = f"현금흐름표_직접법!$C${r_end}"

    # ---------------- 7) 근거
    wg = wb.create_sheet("근거")
    wg.append(["항목","값","비고"]); style_header(wg, 1, 3)
    ev = [
        ("매출액", f"=-({_s401}+{_s404})", "세금계산서 매출 공급가 합"),
        ("매출원가", f"=B{2}", "상품매출원가+식자재비 (손익 II)"),
        ("판매관리비", f"=손익계산서!$B${r_sga}", "판관비 합"),
        ("영업이익", f"=손익계산서!$B${r_op}", ""),
        ("당기순이익", f"={NI}", "법인세 분기 미계상"),
        ("미지급세금(1기 부가세)", str(eng.vat_payable), "매출세액-공제가능매입세액"),
        ("카드 매입세액 공제", str(eng.card_deduct), "식대·포장(가맹점 사업자번호 확보)"),
        ("기말현금", f"={CF_END}", "기초+은행 순증감"),
    ]
    for i,(a,b,c) in enumerate(ev):
        wg.append([a,b,c]); wg.cell(wg.max_row,2).number_format = WON
    wg.cell(3,2).value = f"=손익계산서!$B${r_cogs}"

    # ---------------- 8) 검증리포트
    wv = wb.create_sheet("검증리포트")
    wv.append(["No","검증항목","결과","상세"]); style_header(wv, 1, 4)
    wv.append(["", "※ '별도 검증'은 이 워크북에서 볼 수 없는 항목이다. "
               "검산 스크립트가 따로 본다. PASS 로 적지 않는다", "", ""])
    checks = [
        ("시산표 차변합=대변합(기말합=0)", f'=IF(시산표!$H${tot}=0,"PASS","FAIL")', "시산표 기말잔액 합계"),
        ("재무상태표 자산=부채+자본", f'=IF(재무상태표!$D${r_at}=재무상태표!$D${r_le},"PASS","FAIL")', "대차 균형"),
        ("현금흐름표 기말현금=BS 보통예금", f'=IF(ROUND({CF_END}-{H(103)},0)=0,"PASS","FAIL")', "직접법 현금 대사"),
        ("당기순이익=매출-원가-판관비+영업외-법인세",
         f'=IF(ROUND({NI}-(손익계산서!B{r_sales}-손익계산서!B{r_cogs}-손익계산서!B{r_sga}+손익계산서!B{r_oi}-손익계산서!B{r_oe}-손익계산서!B{r_tax}),0)=0,"PASS","FAIL")',
         "손익 구성요소 합과 대사"),
        ("매출액=세금계산서+채널매출", f'=IF(-({_s401}+{_s404})={eng._tax_sales()+eng._channel_sales()},"PASS","FAIL")', f"세금계산서 {eng._tax_sales():,} + 채널 {eng._channel_sales():,}"),
        ("부가세 정합(정리 후 예수/대급=0)", f'=IF(AND({H(255)}=0,{H(135)}=0),"PASS","FAIL")', f"미지급세금 {eng.vat_payable:,}"),
        # 비용 계정이 대변 잔액이면 부호가 뒤집힌 것이다. 이건 시산표에서 볼 수 있다
        ("비용 계정 기말이 음수 아님",
         ('=IF(AND(' + ",".join(f"{H(c)}>=0" for c in sorted(c for c in codes if 800 <= c < 900))
          + '),"PASS","FAIL")') if any(800 <= c < 900 for c in codes) else '="해당 없음"',
         "판관비 계정 기말 부호"),
        ("수익 계정 기말이 양수 아님",
         ('=IF(AND(' + ",".join(f"{H(c)}<=0" for c in sorted(c for c in codes if 400 <= c < 410))
          + '),"PASS","FAIL")') if any(400 <= c < 410 for c in codes) else '="해당 없음"',
         "매출 계정 기말 부호"),
        # 아래는 이 워크북 안에서 볼 수 없다. 검사하지 않은 것을 PASS 라고 적지 않는다
        ("일반전표 차=대 / 매입매출 공급·세액", '="별도 검증"', "verify_upload.py 가 업로드 파일을 본다"),
        ("더존 양식·사업자번호·거래처코드", '="별도 검증"', "verify_upload.py"),
        ("수식 연결(하드코딩 아님)", '="별도 검증"', "verify_close.py 가 수식 개수를 센다"),
        ("잠정 항목 확인사항 등재", '="별도 검증"', "확인사항_*.docx 참조"),
        ("매입세액 불공제 사유 검토(전수)", '="전문가 확인"', "확인사항 참조. 판단 항목이라 자동 판정 없음"),
    ]
    for i,(name,f,detail) in enumerate(checks, 1):
        wv.append([i, name, f, detail])

    # 열너비
    for sh in wb.worksheets:
        for i,c in enumerate(sh.columns, 1):
            w = max((len(str(x.value)) for x in c if x.value is not None), default=8)
            sh.column_dimensions[col(i)].width = min(max(w+2, 10), 42)
    wb.save(out_path)
    return dict(ts_row=ts_row, JN=JN)
