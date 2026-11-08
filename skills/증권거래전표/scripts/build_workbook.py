"""원장·전표 워크북을 수식으로 만든다.

원천 입력(거래 행의 금액·수량·증권사 잔액, 환율표, 기초 잔고, 설정)만 값으로 두고
나머지는 전부 그 셀을 참조하는 수식이다. 엔진 값은 '엔진대조' 시트에만 두고 차이를 수식으로 잰다.
"""
from __future__ import annotations

from decimal import Decimal

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill, Border, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

import engine as E

INPUT = PatternFill("solid", fgColor="FFF2CC")     # 노란 칸: 입력값
HEAD = PatternFill("solid", fgColor="D9E1F2")
BOLD = Font(bold=True)
THIN = Side(style="thin", color="BFBFBF")
NUMF = '#,##0;[Red]-#,##0'
FXF = '#,##0.00;[Red]-#,##0.00'
RATEF = '#,##0.00##'
QTYF = '#,##0.######'

FIRST = 6          # 원장 첫 데이터 행
ACC_FIRST, ACC_LAST = 6, 60        # 설정 계정표 범위
BFX_FIRST, BFX_LAST = 7, 16        # 기초 외화
BSEC_FIRST, BSEC_LAST = 21, 220    # 기초 종목

LEDGER_COLS = [
    ("A", "순번"), ("B", "일자"), ("C", "이벤트"), ("D", "종목키"), ("E", "통화"), ("F", "수량"),
    ("G", "외화총액"), ("H", "외화비용"), ("I", "원화금액"), ("J", "원화비용"),
    ("K", "증권사 원화잔액"), ("L", "증권사 외화잔액"), ("M", "증권사 잔고수량"),
    ("N", "적용환율"), ("O", "외화흐름"), ("P", "외화잔액"), ("Q", "외화장부 변동"), ("R", "외화장부금액"),
    ("S", "원화흐름"), ("T", "원화잔액"), ("U", "수량변동"), ("V", "직전 보유수량"), ("W", "직전 보유원가"),
    ("X", "취득원가"), ("Y", "원가변동"), ("Z", "매도원가"), ("AA", "처분대가"), ("AB", "처분손익"),
    ("AC", "외환차손익"), ("AD", "지급수수료"), ("AE", "배당·이자수익"), ("AF", "원천세·현지세"),
    ("AG", "보유수량(후)"), ("AH", "보유원가(후)"), ("AI", "원화잔액 차이"), ("AJ", "외화잔액 차이"),
    ("AK", "수량 차이"), ("AL", "전표 차대차이"), ("AM", "직전 외화잔액"), ("AN", "직전 외화장부"),
    ("AO", "원문 거래종류"), ("AP", "종목명"), ("AQ", "원본 위치"), ("AR", "환율 출처"),
    ("AS", "대여 중 수량"), ("AT", "대여 변동"),
]


def _acc(key):
    return f'INDEX(설정!$B${ACC_FIRST}:$B${ACC_LAST},MATCH("{key}",설정!$A${ACC_FIRST}:$A${ACC_LAST},0))'


def _accname(key):
    return f'INDEX(설정!$C${ACC_FIRST}:$C${ACC_LAST},MATCH("{key}",설정!$A${ACC_FIRST}:$A${ACC_LAST},0))'


def resolve_key(cfg, key):
    afs = cfg.get("분류", "단기매매") == "매도가능"
    if key == "증권":
        return "매도가능증권" if afs else "단기매매증권"
    if afs and key in ("처분이익", "처분손실", "평가이익", "평가손실"):
        return "매도가능" + key
    return key


def _num(v):
    if v is None:
        return None
    if isinstance(v, Decimal):
        return int(v) if v == v.to_integral_value() else float(v)
    return v


def _style_header(ws, row, ncol):
    for c in range(1, ncol + 1):
        cell = ws.cell(row, c)
        cell.fill, cell.font = HEAD, BOLD
        cell.alignment = Alignment(wrap_text=True, vertical="center", horizontal="center")


def formulas_for(kind, r, cfg):
    """원장 한 행의 계산 수식. engine.run 의 식과 같아야 한다."""
    afs = cfg.get("분류", "단기매매") == "매도가능"
    p = r - 1
    f = {}
    fx_kinds = {"환전_원화외화", "환전_외화원화", "해외매수", "해외매도", "해외배당", "해외이자", "해외원천세",
                "외화입금", "외화출금", "외화가계정입", "외화가계정출", "환전정산입금", "환전정산출금", "해외세금환급"}
    if kind in fx_kinds:
        if kind.startswith("환전정산"):
            pass
        elif kind.startswith("환전"):
            f["N"] = f"=IF(G{r}=0,0,I{r}/G{r})"
        else:
            f["N"] = (f"=SUMIFS(환율표!$C:$C,환율표!$B:$B,E{r},환율표!$A:$A,"
                      f"_xlfn.MAXIFS(환율표!$A:$A,환율표!$B:$B,E{r},환율표!$A:$A,\"<=\"&B{r}))")
        f["AM"] = (f"=ROUND(SUMIFS(기초!$B${BFX_FIRST}:$B${BFX_LAST},기초!$A${BFX_FIRST}:$A${BFX_LAST},E{r})"
                   f"+SUMIFS(O$5:O{p},E$5:E{p},E{r}),3)")
        f["AN"] = (f"=SUMIFS(기초!$C${BFX_FIRST}:$C${BFX_LAST},기초!$A${BFX_FIRST}:$A${BFX_LAST},E{r})"
                   f"+SUMIFS(Q$5:Q{p},E$5:E{p},E{r})")
        f["P"] = f"=ROUND(AM{r}+O{r},3)"
        f["R"] = f"=AN{r}+Q{r}"

        def out(amt):
            return f"=IF(AM{r}<=0,0,IF(ABS({amt}-AM{r})<0.0005,-AN{r},-ROUND(AN{r}*({amt})/AM{r},0)))"

        if kind == "환전_원화외화":
            f["O"], f["Q"], f["S"] = f"=G{r}", f"=I{r}", f"=-I{r}"
        elif kind == "환전_외화원화":
            f["O"], f["Q"], f["S"] = f"=-G{r}", out(f"G{r}"), f"=I{r}"
            f["AC"] = f"=I{r}+Q{r}"
        elif kind == "해외매수":
            f["O"] = f"=-(G{r}+H{r})"
            f["X"] = f"=ROUND(G{r}*N{r},0)+ROUND(H{r}*N{r},0)" if afs else f"=ROUND(G{r}*N{r},0)"
            f["AD"] = "=0" if afs else f"=ROUND(H{r}*N{r},0)"
            f["Q"] = out(f"G{r}+H{r}")
            f["AC"] = f"=ROUND(G{r}*N{r},0)+ROUND(H{r}*N{r},0)+Q{r}"
        elif kind == "해외매도":
            f["O"] = f"=G{r}-H{r}"
            f["AA"] = f"=ROUND((G{r}-H{r})*N{r},0)"
            f["Q"] = f"=AA{r}"
        elif kind in ("해외배당", "해외이자"):
            f["O"] = f"=G{r}-H{r}"
            f["AE"], f["AF"] = f"=ROUND(G{r}*N{r},0)", f"=ROUND(H{r}*N{r},0)"
            f["Q"] = f"=AE{r}-AF{r}"
        elif kind == "해외원천세":
            f["O"] = f"=-H{r}"
            f["AF"] = f"=ROUND(H{r}*N{r},0)"
            f["Q"] = out(f"H{r}")
            f["AC"] = f"=AF{r}+Q{r}"
        elif kind in ("외화입금", "외화가계정입", "해외세금환급"):
            f["O"], f["Q"] = f"=G{r}", f"=ROUND(G{r}*N{r},0)"
        elif kind == "환전정산입금":
            f["S"], f["Q"] = f"=I{r}", f"=-I{r}"
        elif kind == "환전정산출금":
            f["S"], f["Q"] = f"=-I{r}", f"=I{r}"
        elif kind in ("외화출금", "외화가계정출"):
            f["O"], f["Q"] = f"=-G{r}", out(f"G{r}")
    else:
        if kind in ("입금", "원화가계정입"):
            f["S"] = f"=I{r}"
        elif kind in ("출금", "원화가계정출"):
            f["S"] = f"=-I{r}"
        elif kind == "국내매수":
            f["S"] = f"=-(I{r}+J{r})"
            f["X"] = f"=I{r}+J{r}" if afs else f"=I{r}"
            f["AD"] = "=0" if afs else f"=J{r}"
        elif kind == "국내매도":
            f["S"] = f"=I{r}-J{r}"
            f["AA"] = f"=I{r}-J{r}"
        elif kind == "원화세금":
            f["S"] = f"=-I{r}"
        elif kind in ("국내배당", "원화이자", "대여수수료"):
            f["S"] = f"=I{r}-J{r}"
            f["AE"], f["AF"] = f"=I{r}", f"=J{r}"
    lent_open = (f"SUMIFS(기초!$G${BSEC_FIRST}:$G${BSEC_LAST},기초!$A${BSEC_FIRST}:$A${BSEC_LAST},D{r})")
    if kind == "대여":
        # 대여출고 +, 대여회수입고 − (원문 거래종류로 정한다). 소유는 그대로라 전표 없음
        f["AT"] = f'=IF(ISNUMBER(SEARCH("출고",AO{r})),F{r},-F{r})'
        f["AS"] = f"={lent_open}+SUMIFS(AT$5:AT{r},D$5:D{r},D{r})"
        return f
    if kind in ("해외매수", "국내매수", "해외매도", "국내매도", "주식수변동"):
        f["V"] = (f"=SUMIFS(기초!$D${BSEC_FIRST}:$D${BSEC_LAST},기초!$A${BSEC_FIRST}:$A${BSEC_LAST},D{r})"
                  f"+SUMIFS(U$5:U{p},D$5:D{p},D{r})")
        f["W"] = (f"=SUMIFS(기초!$E${BSEC_FIRST}:$E${BSEC_LAST},기초!$A${BSEC_FIRST}:$A${BSEC_LAST},D{r})"
                  f"+SUMIFS(Y$5:Y{p},D$5:D{p},D{r})")
        if kind == "주식수변동":
            # 출고(원문에 출고 · 감자): 비례 장부금액을 뗀다. 입고: 같은 날 앞선 주식수변동 행이 떼어 놓은 금액을 가져간다
            out = f'OR(ISNUMBER(SEARCH("출고",AO{r})),AND(NOT(ISNUMBER(SEARCH("입고",AO{r}))),ISNUMBER(SEARCH("감자",AO{r}))))'
            f["U"] = f"=IF({out},-F{r},F{r})"
            f["Z"] = f"=IF({out},IF(V{r}<=0,0,IF(F{r}>=V{r},W{r},ROUND(W{r}*F{r}/V{r},0))),0)"
            pend = f'SUMIFS(Y$5:Y{p},B$5:B{p},B{r},C$5:C{p},"주식수변동")'
            f["Y"] = f"=IF({out},-Z{r},-{pend})"
        elif kind.endswith("매수"):
            f["U"], f["Y"] = f"=F{r}", f"=X{r}"
        else:
            f["U"] = f"=-F{r}"
            f["Z"] = f"=IF(V{r}<=0,0,IF(F{r}>=V{r},W{r},ROUND(W{r}*F{r}/V{r},0)))"
            f["Y"] = f"=-Z{r}"
            f["AB"] = f"=AA{r}-Z{r}"
        f["AG"], f["AH"] = f"=V{r}+U{r}", f"=W{r}+Y{r}"
        f["AS"] = f"={lent_open}+SUMIFS(AT$5:AT{p},D$5:D{p},D{r})"
        f["AK"] = f'=IF(M{r}="","",AG{r}-AS{r}-M{r})'
    if kind not in ("검토", "정보"):
        f["T"] = f"=기초!$B$3+SUM(S$5:S{r})"
        f["AI"] = f'=IF(OR(K{r}="",AND(E{r}<>"KRW",S{r}=0)),"",T{r}-K{r})'
        f["AJ"] = f'=IF(OR(L{r}="",E{r}="KRW"),"",ROUND(P{r}-L{r},3))'
        f["AL"] = f"=SUMIFS(전표!$H:$H,전표!$J:$J,A{r})-SUMIFS(전표!$I:$I,전표!$J:$J,A{r})"
    return f


def memo(tx, kind, broker, cfg):
    head = E.MEMO.get(kind, tx.raw_type).format(ccy=tx.ccy)
    nm = tx.name or ""
    if kind in ("해외매수", "해외매도", "국내매수", "국내매도"):
        q = tx.qty.normalize() if hasattr(tx.qty, "normalize") else tx.qty
        s = f"{head} {nm} {q:f}주"
    elif kind in ("해외배당", "국내배당"):
        s = f"{head} {nm}"
    elif kind in ("환전_원화외화", "환전_외화원화"):
        s = f"{head} {tx.G:,.2f}"
    else:
        s = head
    s = f"[{broker}] {s}" if broker else s
    tag = f" #{tx.seq}"
    lim = int(cfg.get("적요길이", 40))
    if len(s) + len(tag) > lim:
        s = s[: lim - len(tag)]
    return s + tag


def build(res: E.Result, rates_rows, path, broker="", opening_hint=None):
    cfg = res.cfg
    wb = Workbook()
    ws0 = wb.active
    ws0.title = "안내"
    _guide(ws0, cfg, broker)

    # ---------------- 설정
    st = wb.create_sheet("설정")
    st["A1"], st["A1"].font = "설정 (노란 칸만 고친다. 바꾸면 원장·전표가 다시 계산된다)", BOLD
    st["A2"], st["B2"] = "회사", cfg.get("회사", "")
    st["A3"], st["B3"] = "증권사", broker
    st["A4"], st["B4"] = "분류(단기매매/매도가능)", cfg.get("분류", "단기매매")
    for c in ("B2", "B3", "B4"):
        st[c].fill = INPUT
    st.append([])
    hdr_row = ACC_FIRST - 1
    st.cell(hdr_row, 1, "계정 키"), st.cell(hdr_row, 2, "계정코드"), st.cell(hdr_row, 3, "계정명"), st.cell(hdr_row, 4, "비고")
    _style_header(st, hdr_row, 4)
    accounts = dict(E.DEFAULT_ACCOUNTS)
    accounts.update({k: tuple(v) for k, v in (cfg.get("계정") or {}).items()})
    for i, (k, (code, name)) in enumerate(accounts.items()):
        r = ACC_FIRST + i
        st.cell(r, 1, k)
        st.cell(r, 2, str(code)).fill = INPUT
        st.cell(r, 3, name).fill = INPUT
    st["F5"], st["F5"].font = "기말", BOLD
    st["F6"], st["G6"] = "기말일", cfg.get("기말", {}).get("일자") or ""
    st["G6"].fill = INPUT
    st["F8"], st["G8"] = "통화", "기말환율"
    _style_header(st, 8, 7)
    st["F8"].fill = st["G8"].fill = HEAD
    end_rates = (cfg.get("기말") or {}).get("환율") or {}
    ccys = sorted({r.tx.ccy for r in res.rows if r.tx.ccy != "KRW"} | set(end_rates))
    ccy_row = {}
    for i, c in enumerate(ccys):
        rr = 9 + i
        st.cell(rr, 6, c)
        v = end_rates.get(c)
        st.cell(rr, 7, float(v) if v not in (None, "") else None).fill = INPUT
        st.cell(rr, 7).number_format = RATEF
        ccy_row[c] = rr
    st["F20"], st["G20"] = "거래처명(예수금)", cfg.get("거래처", {}).get("증권사", broker)
    st["G20"].fill = INPUT
    for col, w in zip("ABCDEFG", (22, 10, 24, 30, 3, 18, 14)):
        st.column_dimensions[col].width = w

    # ---------------- 환율표
    rt = wb.create_sheet("환율표")
    rt.append(["일자", "통화", "환율", "출처"])
    _style_header(rt, 1, 4)
    for d, c, v, s in rates_rows:
        rt.append([d, c, float(v), s])
        rt.cell(rt.max_row, 1).number_format = "yyyy-mm-dd"
        rt.cell(rt.max_row, 3).number_format = RATEF
        for k in range(1, 5):
            rt.cell(rt.max_row, k).fill = INPUT
    rt.column_dimensions["A"].width = 12
    rt.column_dimensions["D"].width = 40

    # ---------------- 기초
    bs = wb.create_sheet("기초")
    begin = cfg.get("기초", {})
    bs["A1"], bs["A1"].font = "기초 잔고(전기말 장부). 노란 칸이 입력값", BOLD
    bs["A3"], bs["B3"] = "원화예수금 기초", _num(Decimal(str(begin.get("원화예수금", 0) or 0)))
    bs["B3"].fill, bs["B3"].number_format = INPUT, NUMF
    bs.cell(BFX_FIRST - 1, 1, "통화"), bs.cell(BFX_FIRST - 1, 2, "외화잔액"), bs.cell(BFX_FIRST - 1, 3, "장부금액(원)"), bs.cell(BFX_FIRST - 1, 4, "출처·비고")
    _style_header(bs, BFX_FIRST - 1, 4)
    bfx = begin.get("외화") or {}
    for i, c in enumerate(sorted(set(bfx) | set(ccys))):
        r = BFX_FIRST + i
        v = bfx.get(c, {})
        bs.cell(r, 1, c).fill = INPUT
        bs.cell(r, 2, _num(Decimal(str(v.get("잔액", 0) or 0)))).fill = INPUT
        bs.cell(r, 3, _num(Decimal(str(v.get("장부금액", 0) or 0)))).fill = INPUT
        bs.cell(r, 4, v.get("출처", ""))
        bs.cell(r, 2).number_format, bs.cell(r, 3).number_format = FXF, NUMF
    h = BSEC_FIRST - 1
    for j, t in enumerate(["종목키", "종목명", "통화", "수량", "장부금액(원)", "출처·비고", "대여 중 수량"], 1):
        bs.cell(h, j, t)
    _style_header(bs, h, 7)
    for i, s in enumerate(begin.get("종목") or []):
        r = BSEC_FIRST + i
        vals = [s.get("종목코드") or s["종목"], s["종목"], s.get("통화", "KRW"),
                _num(Decimal(str(s.get("수량", 0) or 0))), _num(Decimal(str(s.get("장부금액", 0) or 0))), s.get("출처", "")]
        for j, v in enumerate(vals, 1):
            c = bs.cell(r, j, v)
            if j <= 5:
                c.fill = INPUT
        bs.cell(r, 5).number_format = NUMF
        bs.cell(r, 7, _num(Decimal(str(s.get("대여중", 0) or 0)))).fill = INPUT
    for col, w in zip("ABCDEFG", (28, 28, 8, 12, 16, 40, 12)):
        bs.column_dimensions[col].width = w

    # ---------------- 거래원장
    lg = wb.create_sheet("거래원장")
    lg["A1"], lg["A1"].font = "거래원장: 노란 칸(A~M, AO~AR)은 증권사 파일에서 옮긴 원천값, 나머지는 수식", BOLD
    lg["A2"] = ("G·H 외화 체결금액·비용, I·J 원화 거래금액·비용(수수료·세금·원천세). 원가는 종목별 이동평균, "
                "외화예수금은 통화별 이동평균 장부금액. 처분손익 = 처분대가(비용 차감) − 매도원가")
    for c, name in LEDGER_COLS:
        lg[f"{c}5"] = name
    _style_header(lg, 5, len(LEDGER_COLS))
    lg.freeze_panes = "E6"
    for i, row in enumerate(res.rows):
        r = FIRST + i
        tx = row.tx
        vals = {"A": tx.seq, "B": tx.date, "C": row.kind, "D": tx.key, "E": tx.ccy, "F": _num(tx.qty),
                "G": _num(tx.G), "H": _num(tx.H), "I": _num(tx.I), "J": _num(tx.J),
                "K": _num(tx.krw_bal), "L": _num(tx.fx_bal), "M": _num(tx.hold_qty),
                "AO": tx.raw_type, "AP": tx.name, "AQ": tx.src, "AR": row.rate_src}
        for c, v in vals.items():
            cell = lg[f"{c}{r}"]
            cell.value = v
            cell.fill = INPUT
        lg[f"B{r}"].number_format = "yyyy-mm-dd"
        for c, fml in formulas_for(row.kind, r, cfg).items():
            lg[f"{c}{r}"] = fml
        for c in ("G", "H", "L", "O", "P", "AJ", "AM"):
            lg[f"{c}{r}"].number_format = FXF
        lg[f"N{r}"].number_format = RATEF
        for c in ("I", "J", "K", "Q", "R", "S", "T", "W", "X", "Y", "Z", "AA", "AB", "AC", "AD", "AE", "AF", "AH", "AI", "AL", "AN"):
            lg[f"{c}{r}"].number_format = NUMF
        for c in ("F", "M", "U", "V", "AG", "AK"):
            lg[f"{c}{r}"].number_format = QTYF
    last = FIRST + len(res.rows) - 1
    for c, _ in LEDGER_COLS:
        lg.column_dimensions[c].width = 13
    lg.column_dimensions["D"].width = 26
    lg.column_dimensions["AP"].width = 26
    lg.column_dimensions["AQ"].width = 30

    # ---------------- 기말평가
    ye = wb.create_sheet("기말평가")
    ye["A1"], ye["A1"].font = "기말 평가: 노란 칸(기말 단가)을 넣으면 평가 전표가 생긴다. 단가 출처는 잔고증명서", BOLD
    hdr = ["종목키", "종목명", "통화", "보유수량", "보유원가(원)", "기말단가", "기말환율", "평가액(원)", "평가손익", "단가 출처"]
    for j, t in enumerate(hdr, 1):
        ye.cell(3, j, t)
    _style_header(ye, 3, len(hdr))
    sec_rows = []
    for i, it in enumerate(res.year_end):
        r = 4 + i
        sec_rows.append((r, it))
        ye.cell(r, 1, it["key"]), ye.cell(r, 2, it["name"]), ye.cell(r, 3, it["ccy"])
        ye.cell(r, 4, f"=SUMIFS(기초!$D${BSEC_FIRST}:$D${BSEC_LAST},기초!$A${BSEC_FIRST}:$A${BSEC_LAST},A{r})+SUMIFS(거래원장!$U:$U,거래원장!$D:$D,A{r})")
        ye.cell(r, 5, f"=SUMIFS(기초!$E${BSEC_FIRST}:$E${BSEC_LAST},기초!$A${BSEC_FIRST}:$A${BSEC_LAST},A{r})+SUMIFS(거래원장!$Y:$Y,거래원장!$D:$D,A{r})")
        c = ye.cell(r, 6, _num(it["price"]))
        c.fill = INPUT
        if it["ccy"] == "KRW":
            ye.cell(r, 7, 1)
        else:
            ye.cell(r, 7, f"=IFERROR(INDEX(설정!$G$9:$G$19,MATCH(C{r},설정!$F$9:$F$19,0)),\"\")")
        ye.cell(r, 8, f'=IF(OR(F{r}="",G{r}=""),"",ROUND(D{r}*F{r}*G{r},0))')
        ye.cell(r, 9, f'=IF(H{r}="","",H{r}-E{r})')
        ye.cell(r, 10, (cfg.get("기말") or {}).get("단가출처", "")).fill = INPUT
        ye.cell(r, 4).number_format = QTYF
        for k in (5, 8, 9):
            ye.cell(r, k).number_format = NUMF
        ye.cell(r, 6).number_format = RATEF
        ye.cell(r, 7).number_format = RATEF
    fr0 = 6 + len(res.year_end)
    ye.cell(fr0, 1, "외화예수금 환산").font = BOLD
    for j, t in enumerate(["통화", "외화잔액", "장부금액(원)", "기말환율", "환산액(원)", "환산손익"], 1):
        ye.cell(fr0 + 1, j, t)
    _style_header(ye, fr0 + 1, 6)
    fx_rows = []
    for i, it in enumerate(res.fx_end):
        r = fr0 + 2 + i
        fx_rows.append((r, it))
        ye.cell(r, 1, it["ccy"])
        ye.cell(r, 2, f"=ROUND(SUMIFS(기초!$B${BFX_FIRST}:$B${BFX_LAST},기초!$A${BFX_FIRST}:$A${BFX_LAST},A{r})+SUMIFS(거래원장!$O:$O,거래원장!$E:$E,A{r}),3)")
        ye.cell(r, 3, f"=SUMIFS(기초!$C${BFX_FIRST}:$C${BFX_LAST},기초!$A${BFX_FIRST}:$A${BFX_LAST},A{r})+SUMIFS(거래원장!$Q:$Q,거래원장!$E:$E,A{r})")
        ye.cell(r, 4, f"=IFERROR(INDEX(설정!$G$9:$G$19,MATCH(A{r},설정!$F$9:$F$19,0)),\"\")")
        ye.cell(r, 5, f'=IF(D{r}="","",ROUND(B{r}*D{r},0))')
        ye.cell(r, 6, f'=IF(E{r}="","",E{r}-C{r})')
        ye.cell(r, 2).number_format = FXF
        for k in (3, 5, 6):
            ye.cell(r, k).number_format = NUMF
        ye.cell(r, 4).number_format = RATEF
    for col, w in zip("ABCDEFGHIJ", (26, 26, 8, 12, 16, 12, 12, 16, 14, 30)):
        ye.column_dimensions[col].width = w

    # ---------------- 전표
    jv = wb.create_sheet("전표")
    jv["A1"], jv["A1"].font = "전표: 금액은 거래원장·기말평가 셀을 참조한다. 0원 줄은 업로드 파일에서 뺀다", BOLD
    jh = ["전표키", "일자", "구분", "계정코드", "계정명", "거래처", "적요", "차변", "대변", "원장 순번"]
    for j, t in enumerate(jh, 1):
        jv.cell(3, j, t)
    _style_header(jv, 3, len(jh))
    jr = 4
    party = "설정!$G$20"
    for i, row in enumerate(res.rows):
        if row.kind not in E.LINES:
            continue
        r = FIRST + i
        tx = row.tx
        m = memo(tx, row.kind, broker, cfg)
        for side, key, val in E.LINES[row.kind]:
            neg = val.startswith("-")
            col = val.lstrip("-")
            ref = f"거래원장!{col}{r}"
            amt = f"-{ref}" if neg else ref
            jv.cell(jr, 1, tx.seq)
            jv.cell(jr, 2, f"=거래원장!B{r}").number_format = "yyyy-mm-dd"
            if side == "pl":
                gain, loss = (resolve_key(cfg, k) for k in E.PL_PAIR[key])
                jv.cell(jr, 3, f"=IF(H{jr}>0,3,4)")
                jv.cell(jr, 4, f"=IF({amt}<0,{_acc(loss)},{_acc(gain)})")
                jv.cell(jr, 5, f"=IF({amt}<0,{_accname(loss)},{_accname(gain)})")
                jv.cell(jr, 8, f"=MAX(-({amt}),0)")
                jv.cell(jr, 9, f"=MAX({amt},0)")
            else:
                k = resolve_key(cfg, key)
                jv.cell(jr, 3, 3 if side == "dr" else 4)
                jv.cell(jr, 4, f"={_acc(k)}")
                jv.cell(jr, 5, f"={_accname(k)}")
                jv.cell(jr, 8 if side == "dr" else 9, f"={amt}")
                jv.cell(jr, 9 if side == "dr" else 8, 0)
                if k in ("원화예수금", "외화예수금"):
                    jv.cell(jr, 6, f"={party}")
                elif k == "이체상대":
                    jv.cell(jr, 6, tx.counterparty or "")
            jv.cell(jr, 7, m)
            jv.cell(jr, 10, tx.seq)
            jr += 1
    end_date = (cfg.get("기말") or {}).get("일자")
    ye_first_line = jr
    sec_key = resolve_key(cfg, "증권")
    gain, loss = resolve_key(cfg, "평가이익"), resolve_key(cfg, "평가손실")
    for r, it in sec_rows:
        pl = f"N(기말평가!I{r})"
        memo_s = f"[결산] 평가 {it['name']}"[:36] + " #Y"
        # 평가이익: 차변 증권 / 대변 평가이익. 평가손실: 차변 평가손실 / 대변 증권
        jv.cell(jr, 1, "Y"), jv.cell(jr, 2, end_date), jv.cell(jr, 3, 3)
        jv.cell(jr, 4, f"=IF({pl}<0,{_acc(loss)},{_acc(sec_key)})")
        jv.cell(jr, 5, f"=IF({pl}<0,{_accname(loss)},{_accname(sec_key)})")
        jv.cell(jr, 7, memo_s), jv.cell(jr, 8, f"=ABS({pl})"), jv.cell(jr, 9, 0), jv.cell(jr, 10, "기말")
        jr += 1
        jv.cell(jr, 1, "Y"), jv.cell(jr, 2, end_date), jv.cell(jr, 3, 4)
        jv.cell(jr, 4, f"=IF({pl}<0,{_acc(sec_key)},{_acc(gain)})")
        jv.cell(jr, 5, f"=IF({pl}<0,{_accname(sec_key)},{_accname(gain)})")
        jv.cell(jr, 7, memo_s), jv.cell(jr, 8, 0), jv.cell(jr, 9, f"=ABS({pl})"), jv.cell(jr, 10, "기말")
        jr += 1
    for r, it in fx_rows:
        pl = f"N(기말평가!F{r})"
        memo_s = f"[결산] 외화환산 {it['ccy']} #Y"
        jv.cell(jr, 1, "Y"), jv.cell(jr, 2, end_date), jv.cell(jr, 3, 3)
        jv.cell(jr, 4, f"=IF({pl}<0,{_acc('환산손실')},{_acc('외화예수금')})")
        jv.cell(jr, 5, f"=IF({pl}<0,{_accname('환산손실')},{_accname('외화예수금')})")
        jv.cell(jr, 6, f"=IF({pl}<0,\"\",{party})")
        jv.cell(jr, 7, memo_s), jv.cell(jr, 8, f"=ABS({pl})"), jv.cell(jr, 9, 0), jv.cell(jr, 10, "기말")
        jr += 1
        jv.cell(jr, 1, "Y"), jv.cell(jr, 2, end_date), jv.cell(jr, 3, 4)
        jv.cell(jr, 4, f"=IF({pl}<0,{_acc('외화예수금')},{_acc('환산이익')})")
        jv.cell(jr, 5, f"=IF({pl}<0,{_accname('외화예수금')},{_accname('환산이익')})")
        jv.cell(jr, 6, f"=IF({pl}<0,{party},\"\")")
        jv.cell(jr, 7, memo_s), jv.cell(jr, 8, 0), jv.cell(jr, 9, f"=ABS({pl})"), jv.cell(jr, 10, "기말")
        jr += 1
    jlast = jr - 1
    for rr in range(4, jr):
        jv.cell(rr, 2).number_format = "yyyy-mm-dd"
        jv.cell(rr, 8).number_format = NUMF
        jv.cell(rr, 9).number_format = NUMF
    jv.cell(jr + 1, 7, "합계").font = BOLD
    jv.cell(jr + 1, 8, f"=SUM(H4:H{jlast})").number_format = NUMF
    jv.cell(jr + 1, 9, f"=SUM(I4:I{jlast})").number_format = NUMF
    for col, w in zip("ABCDEFGHIJ", (8, 12, 6, 9, 20, 18, 44, 14, 14, 9)):
        jv.column_dimensions[col].width = w

    # ---------------- 엔진대조
    ec = wb.create_sheet("엔진대조")
    ec["A1"], ec["A1"].font = "엔진대조: B 이후 '엔진' 열은 engine.py 가 따로 계산한 값(입력). '차이' 열이 모두 0 이어야 한다", BOLD
    cmp_cols = ["P", "Q", "R", "T", "X", "Z", "AB", "AC", "AE", "AF", "AG", "AH"]
    ec.cell(3, 1, "원장 행")
    for j, c in enumerate(cmp_cols):
        ec.cell(3, 2 + 2 * j, f"엔진 {c}")
        ec.cell(3, 3 + 2 * j, f"차이 {c}")
    _style_header(ec, 3, 1 + 2 * len(cmp_cols))
    for i, row in enumerate(res.rows):
        r = FIRST + i
        er = 4 + i
        ec.cell(er, 1, r)
        for j, c in enumerate(cmp_cols):
            v = row.get(c)
            if row.kind in ("검토", "정보"):
                v = None
            ec.cell(er, 2 + 2 * j, _num(v)).fill = INPUT
            tol = "0.0005" if c == "P" else "0.5"
            ec.cell(er, 3 + 2 * j, f'=IF(B{er}="",0,IF(ABS(N(거래원장!{c}{r})-{get_column_letter(2+2*j)}{er})<{tol},0,N(거래원장!{c}{r})-{get_column_letter(2+2*j)}{er}))')
    elast = 3 + len(res.rows)
    diff_ranges = ",".join(f"엔진대조!{get_column_letter(3+2*j)}4:{get_column_letter(3+2*j)}{elast}" for j in range(len(cmp_cols)))

    # ---------------- 검산
    ck = wb.create_sheet("검산", 1)
    ck["A1"], ck["A1"].font = "검산: 차이는 0, 판정은 OK 여야 넘긴다", BOLD
    for j, t in enumerate(["항목", "값", "판정", "설명"], 1):
        ck.cell(3, j, t)
    _style_header(ck, 3, 4)
    L = f"{FIRST}:{last}"
    rng = lambda c: f"거래원장!{c}{FIRST}:{c}{last}"
    checks = [
        ("전표 차변 − 대변", f"=SUM(전표!H4:H{jlast})-SUM(전표!I4:I{jlast})", "0", "전체 차대 일치"),
        ("차대가 안 맞는 거래 수", f"=COUNTIF({rng('AL')},\">0.5\")+COUNTIF({rng('AL')},\"<-0.5\")", "0", "거래별 전표 차대(거래원장 AL)"),
        ("원화잔액 불일치 수", f"=COUNTIF({rng('AI')},\">0.5\")+COUNTIF({rng('AI')},\"<-0.5\")", "0", "계산 원화예수금 잔액 vs 증권사 현금잔액(거래원장 AI)"),
        ("외화잔액 불일치 수", f"=COUNTIF({rng('AJ')},\">0.0005\")+COUNTIF({rng('AJ')},\"<-0.0005\")", "0", "계산 외화예수금 잔액 vs 증권사 외화예수금(거래원장 AJ)"),
        ("보유수량 불일치 수", f"=COUNTIF({rng('AK')},\">0.0000001\")+COUNTIF({rng('AK')},\"<-0.0000001\")", "0", "계산 보유수량 vs 증권사 잔고수량(거래원장 AK)"),
        ("엔진 대조 차이 수", "=" + "+".join(f"COUNTIF({x},\"<>0\")" for x in diff_ranges.split(",")), "0",
         "engine.py 값과 수식 값(엔진대조 시트)"),
        ("환율 없는 외화 거래 수", f"=SUMPRODUCT(--({rng('E')}<>\"KRW\"),--({rng('C')}<>\"검토\"),--(LEFT({rng('C')},4)<>\"환전정산\"),--({rng('N')}=0))", "0", "환율표에 그 날짜 이전 환율이 없다"),
        ("검토대기(전표 없음) 수", f"=COUNTIF({rng('C')},\"검토\")", "0", "입출고·기업행위: 확인사항 시트"),
        ("가계정 기표 수", f"=COUNTIF({rng('C')},\"*가계정*\")", "0", "규칙에 없는 거래: 확인사항 시트"),
        ("기말 단가 미입력 종목 수", f"=COUNTIFS(기말평가!D4:D{max(4, 3+len(res.year_end))},\"<>0\",기말평가!F4:F{max(4, 3+len(res.year_end))},\"\")" if res.year_end else "=0", "0", "기말평가 시트 F열"),
    ]
    for i, (name, fml, ok, desc) in enumerate(checks):
        r = 4 + i
        ck.cell(r, 1, name)
        ck.cell(r, 2, fml)
        ck.cell(r, 3, f'=IF(ABS(N(B{r}))<0.5,"OK","확인필요")')
        ck.cell(r, 4, desc)
        ck.cell(r, 2).number_format = NUMF
    r = 4 + len(checks) + 1
    ck.cell(r, 1, "보유원가 합계(원장)"), ck.cell(r, 2, f"=SUM(기말평가!E4:E{max(4, 3+len(res.year_end))})")
    ck.cell(r + 1, 1, "처분손익 합계"), ck.cell(r + 1, 2, f"=SUM({rng('AB')})")
    ck.cell(r + 2, 1, "외환차손익 합계"), ck.cell(r + 2, 2, f"=SUM({rng('AC')})")
    ck.cell(r + 3, 1, "배당·이자수익 합계"), ck.cell(r + 3, 2, f"=SUM({rng('AE')})")
    ck.cell(r + 4, 1, "원천세·현지세 합계"), ck.cell(r + 4, 2, f"=SUM({rng('AF')})")
    ck.cell(r + 5, 1, "지급수수료 합계"), ck.cell(r + 5, 2, f"=SUM({rng('AD')})")
    for k in range(r, r + 6):
        ck.cell(k, 2).number_format = NUMF
    ck.cell(r + 7, 1, "PASS 는 계산과 대사만 본다. 원천 자료가 맞는지, 계정 분류·기초 장부금액·기말 단가가 맞는지는 보지 않는다.")
    for col, w in zip("ABCD", (30, 16, 10, 60)):
        ck.column_dimensions[col].width = w

    # ---------------- 확인사항
    iq = wb.create_sheet("확인사항")
    for j, t in enumerate(["구분", "순번", "일자", "거래", "내용", "회계사 결론"], 1):
        iq.cell(1, j, t)
    _style_header(iq, 1, 6)
    for k, (kind, tx, msg) in enumerate(res.issues, 2):
        iq.cell(k, 1, kind)
        if tx is not None:
            iq.cell(k, 2, tx.seq), iq.cell(k, 3, str(tx.date)), iq.cell(k, 4, f"{tx.raw_type} {tx.name}".strip())
        iq.cell(k, 5, msg)
        iq.cell(k, 6).fill = INPUT
    if opening_hint:
        k = iq.max_row + 2
        iq.cell(k, 1, "기초 추정").font = BOLD
        for line in opening_hint:
            k += 1
            iq.cell(k, 1, "기초 추정"), iq.cell(k, 5, line)
    for col, w in zip("ABCDEF", (10, 6, 12, 30, 90, 30)):
        iq.column_dimensions[col].width = w

    wb.save(path)
    return {"ledger_last": last, "journal_last": jlast, "checks": len(checks)}


def _guide(ws, cfg, broker):
    lines = [
        ("증권 거래 전표 워크북", True),
        (f"회사: {cfg.get('회사','')}   증권사: {broker}   분류: {cfg.get('분류','단기매매')}", False),
        ("", False),
        ("시트", True),
        ("검산: 차대·잔액 대사·엔진 대조. 모두 OK 여야 넘긴다", False),
        ("설정: 계정코드·기말일·기말환율(입력)", False),
        ("환율표: 외화 거래일의 매매기준율(입력, 출처 표시)", False),
        ("기초: 전기말 원화·외화예수금, 종목별 수량·장부금액(입력)", False),
        ("거래원장: 증권사 파일 원천값(노란 칸) + 수식 계산(원가·잔액·손익)", False),
        ("기말평가: 기말 단가를 넣으면 평가손익·외화환산 계산", False),
        ("전표: 거래원장·기말평가 셀을 참조하는 분개", False),
        ("엔진대조: Python 엔진 값과 수식 값의 차이", False),
        ("확인사항: 회계사가 정할 것(계정, 기초, 검토대기, 원천세)", False),
        ("", False),
        ("수식으로 만들 수 없는 값(증권사 원천값·환율·기초 장부·기말 단가)은 노란 칸이고 출처를 옆에 적는다.", False),
    ]
    for i, (t, b) in enumerate(lines, 1):
        ws.cell(i, 1, t).font = Font(bold=b, size=13 if i == 1 else 11)
    ws.column_dimensions["A"].width = 100
