"""위하고 전표 줄과 검증 워크북을 만든다.

계산은 engine.py 가 한다. 위하고 업로드 파일은 엔진 값만 쓴다(엑셀이 없어도, 엑셀 판이 달라도 같은 파일이 나온다).
2026-11-08 까지는 엑셀이 재계산한 값으로 업로드 파일을 썼는데, 엑셀 2016 에 없는 MAXIFS 때문에 해외 거래 환율이 0 이 됐다.

검증 워크북(요약 · 전표 · 거래원장 · 기초·기말)은 2026-11-09 부터 수식으로 잇는다. 값만 있으면 회계사가 잔액 · 원가 ·
손익이 어디서 왔는지 엑셀에서 따라갈 수 없다(대표 지적). 거래원장은 증권사 파일 값과 기초 잔고에서 잔액 · 장부금액 ·
손익을 계산하고, 전표 시트 금액은 거래원장 칸을 가리킨다. 수식은 엑셀 2007 부터 있는 함수(formula_check.FUNCS)만 쓴다.
만들 때마다 formula_check 가 수식을 다시 계산해 엔진 값과 칸마다 맞춰 보고, 엔진 값을 수식 칸의 저장값으로 넣는다
(미리보기 · 휴대폰에서도 숫자가 보이고, 엑셀은 열 때 다시 계산한다).
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

from openpyxl import Workbook
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

import engine as E
import formula_check as FC
import wehago_upload as WU

INPUT = PatternFill("solid", fgColor="FFF2CC")     # 노란 칸: 회계사가 적는 칸
HEAD = PatternFill("solid", fgColor="D9E1F2")
BAD = PatternFill("solid", fgColor="F8CBAD")
GOOD = PatternFill("solid", fgColor="E2EFDA")
BOLD = Font(bold=True)
NUMF = '#,##0;[Red]-#,##0'
FXF = '#,##0.00#;[Red]-#,##0.00#'
RATEF = '#,##0.00##'
QTYF = "General"           # '#,##0.######' 은 정수 수량에 마침표가 남는다(100.)
DATEF = "yyyy-mm-dd"

NO_BALANCE = ("검토", "정보", "대여")              # 잔액 계산을 하지 않는 행
TRADES = ("해외매수", "해외매도", "국내매수", "국내매도")
HOLD = TRADES + ("주식수변동",)
FX_PL = ("환전_외화원화", "해외매수", "해외원천세")
PASS_NOTE = "PASS 는 계산과 대사만 본다. 원천 자료가 맞는지, 계정 분류 · 기초 장부금액 · 기말 단가가 맞는지는 보지 않는다."
EDIT_NOTE = ("이 파일에서 숫자를 고치면 수식은 다시 계산되지만 위하고 업로드 파일은 바뀌지 않는다. "
             "고칠 값은 설정(기초 · 기말)이나 환율표에 넣고 다시 돌린다.")
FC_NAME = "검증 파일 수식 재계산 차이 칸 수"
FC_DESC = "검증 파일 수식을 다시 계산한 값이 엔진 값(위하고 업로드 파일)과 다른 칸. 0 이 아니면 스킬 결함이다"

SHEET_S, SHEET_J, SHEET_L, SHEET_B = "요약", "전표", "거래원장", "기초·기말"


def _num(v):
    if v is None:
        return None
    if isinstance(v, Decimal):
        return int(v) if v == v.to_integral_value() else float(v)
    return v


def _q(sheet):
    """수식 안 시트 이름. 가운뎃점 같은 글자가 있어 늘 따옴표로 감싼다."""
    return "'" + sheet.replace("'", "''") + "'!"


def _text(v):
    """SUMIF 조건으로 쓰는 글자 칸(종목코드 · 통화). 엑셀 조건에서 * ? ~ 는 와일드카드라 전각으로 바꿔 둔다."""
    if v in (None, ""):
        return None
    return str(v).replace("~", "～").replace("*", "＊").replace("?", "？")


def _put(ws, r, c, formula, expected, X, fmt=None):
    """수식 칸을 쓰고, formula_check 가 맞춰 볼 엔진 값을 X 에 적는다."""
    cell = ws.cell(r, c, formula)
    X[(ws.title, cell.coordinate)] = expected
    if fmt:
        cell.number_format = fmt
    return cell


def _header(ws, row, names, col=1):
    for j, t in enumerate(names, col):
        c = ws.cell(row, j, t)
        c.fill, c.font = HEAD, BOLD
        c.alignment = Alignment(wrap_text=True, vertical="center", horizontal="center")


def _date(v):
    if v in (None, ""):
        return None
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    from read_source import parse_date
    return parse_date(v)


def party_name(cfg, broker):
    return (cfg.get("거래처") or {}).get("증권사", broker) or ""


def memo(tx, kind, broker, cfg):
    head = E.MEMO.get(kind, tx.raw_type).format(ccy=tx.ccy)
    nm = tx.name or ""
    if kind in TRADES:
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


# ---------------------------------------------------------------- 전표 줄
def journal_lines(res, broker=""):
    """엔진 결과 → 위하고 전표 줄(0원 줄 제외). 업로드 파일과 검증 워크북 「전표」 시트가 이 목록을 그대로 쓴다.

    줄: {key, date, gubun(3 차변 · 4 대변), code, name, party, memo, dr, cr, src}. key 는 거래 순번, 결산 줄은 'Y'.
    src 는 검증 워크북에서 금액 칸이 가리킬 곳이다. ('L', res.rows 위치, 엔진 열, 부호) · ('Y' | 'F', 기말 항목 위치, 부호).
    """
    cfg = res.cfg
    party = party_name(cfg, broker)
    limit = int(cfg.get("적요길이", 40))
    out = []

    def add(key, date, side, acc, amt, pty, m, src):
        amt = E.R0(Decimal(amt))
        if amt == 0:
            return
        code, name = acc
        out.append({"key": key, "date": date, "gubun": 3 if side == "dr" else 4, "code": str(code), "name": name,
                    "party": pty, "memo": WU.clean_memo(m, limit),
                    "dr": int(amt) if side == "dr" else 0, "cr": int(amt) if side == "cr" else 0, "src": src})

    for j, row in enumerate(res.rows):
        if row.kind not in E.LINES:
            continue
        tx = row.tx
        m = memo(tx, row.kind, broker, cfg)
        # make_lines 는 LINES 항목마다 줄 하나를 같은 차례로 낸다
        for (spec_side, _, val), (side, acc, v, key) in zip(E.LINES[row.kind], row.lines):
            pty = party if key in ("원화예수금", "외화예수금") else (tx.counterparty or "") if key == "이체상대" else ""
            if spec_side == "pl":
                src = ("L", j, val, 1 if side == "cr" else -1)
            else:
                src = ("L", j, val.lstrip("-"), -1 if val.startswith("-") else 1)
            add(tx.seq, tx.date, side, acc, v, pty, m, src)

    end = _date((cfg.get("기말") or {}).get("일자"))
    if end is None:
        return out
    sec = E.acct(cfg, "증권")
    for i, it in enumerate(res.year_end):
        pl = it["pl"]
        if not pl:
            continue
        m = f"[결산] 평가 {it['name']}"[:36] + " #Y"
        if pl > 0:
            add("Y", end, "dr", sec, pl, "", m, ("Y", i, 1))
            add("Y", end, "cr", E.acct(cfg, "평가이익"), pl, "", m, ("Y", i, 1))
        else:
            add("Y", end, "dr", E.acct(cfg, "평가손실"), -pl, "", m, ("Y", i, -1))
            add("Y", end, "cr", sec, -pl, "", m, ("Y", i, -1))
    for i, it in enumerate(res.fx_end):
        pl = it["pl"]
        if not pl:
            continue
        m = f"[결산] 외화환산 {it['ccy']} #Y"
        if pl > 0:
            add("Y", end, "dr", E.acct(cfg, "외화예수금"), pl, party, m, ("F", i, 1))
            add("Y", end, "cr", E.acct(cfg, "환산이익"), pl, "", m, ("F", i, 1))
        else:
            add("Y", end, "dr", E.acct(cfg, "환산손실"), -pl, "", m, ("F", i, -1))
            add("Y", end, "cr", E.acct(cfg, "외화예수금"), -pl, party, m, ("F", i, -1))
    return out


# ---------------------------------------------------------------- 대사 · 검산
def recon(r):
    """한 행의 증권사 잔액 대사. (비교한 항목 수, [다른 항목 설명])."""
    t, n, bad = r.tx, 0, []
    if r.kind in NO_BALANCE:
        return 0, []
    if t.krw_bal is not None and (t.ccy == "KRW" or r.S != 0):
        n += 1
        if r.T != t.krw_bal:
            bad.append(f"원화 증권사 {t.krw_bal:,} 차이 {r.T - t.krw_bal:+,}")
    if t.fx_bal is not None and t.ccy != "KRW":
        n += 1
        if r.P != t.fx_bal:
            bad.append(f"{t.ccy} 증권사 {t.fx_bal:,} 차이 {r.P - t.fx_bal:+,}")
    if t.hold_qty is not None and r.kind in HOLD:
        n += 1
        if r.AG - r.AS != t.hold_qty:
            lent = f"(대여 중 {r.AS} 제외)" if r.AS else ""
            bad.append(f"수량 증권사 {t.hold_qty} 차이 {r.AG - r.AS - t.hold_qty:+}{lent}")
    return n, bad


def checks(res, lines):
    """[(항목, 값, 판정, 설명)]. 판정은 OK · 확인필요 · 중단. 중단이 하나라도 있으면 위하고 업로드 파일을 쓰지 않는다."""
    rows, cfg = res.rows, res.cfg
    by = {}
    for ln in lines:
        by[ln["key"]] = by.get(ln["key"], 0) + ln["dr"] - ln["cr"]
    mis = {"원화": 0, "외화": 0, "수량": 0}
    for r in rows:
        for b in recon(r)[1]:
            mis["수량" if b.startswith("수량") else "원화" if b.startswith("원화") else "외화"] += 1
    no_rate = sum(1 for r in rows if r.kind in E.LINES and r.tx.ccy != "KRW" and not r.kind.startswith("환전") and r.N == 0)
    stops = [i for i in res.issues if i[0] == "중단"]
    b_sec = (cfg.get("기초") or {}).get("종목") or []
    no_book = sum(1 for s in b_sec if Decimal(str(s.get("수량", 0) or 0)) > 0 and Decimal(str(s.get("장부금액", 0) or 0)) == 0)
    no_price = sum(1 for it in res.year_end if it["qty"] != 0 and it["price"] is None)
    no_end = 0 if _date((cfg.get("기말") or {}).get("일자")) else sum(
        1 for it in list(res.year_end) + list(res.fx_end) if it["pl"])
    total = sum(ln["dr"] - ln["cr"] for ln in lines)
    out = [
        ("전표 차변 − 대변", total, "중단", "전체 차대 일치"),
        ("차대가 안 맞는 거래 수", sum(1 for v in by.values() if v), "중단", "거래(순번)마다 차변 합 = 대변 합"),
        ("중단 사유 수", len(stops), "중단", "환율 없음 · 보유보다 많은 매도 · 외화 잔액보다 많은 출금. 확인사항 [중단]"),
        ("환율 없는 외화 거래 수", no_rate, "중단", "환율표에 그 날짜 이전 환율이 없다"),
        ("원화잔액 불일치 수", mis["원화"], "확인필요", "계산 원화예수금 잔액 vs 증권사 현금잔액(거래원장 「원화 차이」 열)"),
        ("외화잔액 불일치 수", mis["외화"], "확인필요", "계산 외화예수금 잔액 vs 증권사 외화예수금(거래원장 「외화 차이」 열)"),
        ("보유수량 불일치 수", mis["수량"], "확인필요", "계산 보유수량(대여 중 제외) vs 증권사 잔고수량(거래원장 「수량 차이」 열)"),
        ("검토대기(전표 없음) 수", sum(1 for r in rows if r.kind == "검토"), "확인필요", "입출고 · 기업행위: 확인사항 [검토대기]"),
        ("가계정 기표 수", sum(1 for r in rows if "가계정" in r.kind), "확인필요", "규칙에 없는 거래: 확인사항 [미분류]"),
        ("장부금액 없는 기초 보유 종목 수", no_book, "확인필요",
         "기초 수량은 있는데 장부금액이 0 이다(역산한 기초). 팔면 원가가 낮게 잡혀 처분이익이 부풀려진다. 설정 「기초」 에 전기말 장부금액을 넣고 다시 돌린다"),
        ("기말 단가 미입력 종목 수", no_price, "확인필요", "설정 「기말」 의 단가 · 환율(기초·기말 시트)"),
        ("기말일이 없어 빠진 결산 전표 수", no_end, "확인필요", "설정 「기말」 의 일자"),
    ]
    return [(n, v, "OK" if not v else bad, d) for n, v, bad, d in out]


def totals(res, lines):
    rs = res.rows
    s = lambda f: sum((getattr(r, f) for r in rs), Decimal(0))
    return [
        ("처분손익", s("AB")), ("외환차손익", s("AC")), ("배당 · 이자수익(세전)", s("AE")), ("원천세 · 현지세", s("AF")),
        ("지급수수료(매수 수수료)", s("AD")),
        ("기말 평가손익", sum((it["pl"] for it in res.year_end if it["pl"] is not None), Decimal(0))),
        ("외화예수금 환산손익", sum((it["pl"] for it in res.fx_end if it["pl"] is not None), Decimal(0))),
        ("기말 보유원가", sum((it["cost"] for it in res.year_end), Decimal(0))),
        ("전표 차변 합계", sum(ln["dr"] for ln in lines)), ("전표 대변 합계", sum(ln["cr"] for ln in lines)),
    ]


# ---------------------------------------------------------------- 거래원장 열
# (열 이름, 머리글, 너비, 서식). 열 이름이 엔진 Row 필드 이름이면 그 값을 계산하는 열이다.
LEDGER = [
    ("seq", "순번", 6, None), ("date", "일자", 11, DATEF), ("raw", "거래", 16, None), ("kind", "처리", 12, None),
    ("name", "종목", 22, None), ("key", "종목코드", 10, None), ("ccy", "통화", 5, None),
    ("qty", "수량", 9, QTYF), ("G", "외화금액", 11, FXF), ("H", "외화비용", 9, FXF), ("I", "원화금액", 13, NUMF),
    ("J", "원화비용", 10, NUMF),
    ("N", "적용환율", 10, RATEF),
    ("O", "외화 흐름", 11, FXF), ("P", "외화잔액", 11, FXF), ("fxb", "증권사 외화잔액", 11, FXF),
    ("fxd", "외화 차이", 9, FXF), ("pk", "직전 외화 장부금액", 13, NUMF), ("Q", "외화 장부금액 변동", 13, NUMF),
    ("S", "원화 흐름", 13, NUMF), ("T", "원화잔액", 13, NUMF), ("krb", "증권사 원화잔액", 13, NUMF),
    ("krd", "원화 차이", 10, NUMF),
    ("U", "수량 변동", 9, QTYF), ("AT", "대여 변동", 8, QTYF), ("AG", "보유수량", 9, QTYF),
    ("hq", "증권사 잔고수량", 9, QTYF), ("hqd", "수량 차이", 8, QTYF), ("W", "직전 장부금액", 13, NUMF),
    ("Y", "장부금액 변동", 13, NUMF),
    ("AB", "처분손익", 12, NUMF), ("AC", "외환차손익", 11, NUMF), ("AE", "배당 · 이자(세전)", 12, NUMF),
    ("AF", "원천세 · 현지세", 11, NUMF), ("AD", "매수 수수료", 10, NUMF),
    ("rsrc", "환율 근거", 22, None),
]
IDX = {k: i for i, (k, *_) in enumerate(LEDGER, 1)}
COL = {k: get_column_letter(i) for k, i in IDX.items()}
FMT = {k: f for k, _, _, f in LEDGER}
GROUPS = [("거래", "seq", "ccy"), ("증권사 파일 값", "qty", "J"), ("환율", "N", "N"), ("외화예수금", "O", "Q"),
          ("원화예수금", "S", "krd"), ("종목 수량 · 장부금액", "U", "Y"), ("손익", "AB", "AD")]
FIRST = 4                  # 첫 자료 행(1 설명 · 2 묶음 · 3 머리글). 기초 줄이 먼저 온다
DIFF = ("fxd", "krd", "hqd")


def _kind_formulas(k, i, out_qty):
    """거래 종류마다 엔진 run() 의 계산을 그대로 옮긴 수식. {열 이름: 수식}."""
    c = lambda key: f"{COL[key]}{i}"
    G, H, I, J, N, Q = c("G"), c("H"), c("I"), c("J"), c("N"), c("Q")
    pb = f"ROUND({c('P')}-{c('O')},3)"              # 직전 외화잔액

    def out_book(amt):                              # 외화를 내보낼 때 줄어드는 장부금액(이동평균)
        return f"=IF({pb}<=0,0,IF(ROUND({amt},3)={pb},-{c('pk')},-ROUND({c('pk')}*({amt})/{pb},0)))"

    held = f"({c('AG')}-{c('U')})"                  # 직전 보유수량
    out_cost = f"=-IF({held}<=0,0,IF({c('qty')}>={held},{c('W')},ROUND({c('W')}*{c('qty')}/{held},0)))"
    f = {}
    if k == "환전_원화외화":
        f["O"], f["Q"] = f"={G}", f"={I}"
    elif k == "환전_외화원화":
        f["O"], f["Q"] = f"=-{G}", out_book(G)
    elif k == "해외매수":
        f["O"], f["Q"] = f"=-({G}+{H})", out_book(f"{G}+{H}")
    elif k == "해외매도":
        f["O"], f["Q"] = f"={G}-{H}", f"=ROUND(({G}-{H})*{N},0)"
    elif k in ("해외배당", "해외이자"):
        f["O"], f["Q"] = f"={G}-{H}", f"={c('AE')}-{c('AF')}"
    elif k == "해외원천세":
        f["O"], f["Q"] = f"=-{H}", out_book(H)
    elif k == "환전정산입금":
        f["Q"] = f"=-{I}"
    elif k == "환전정산출금":
        f["Q"] = f"={I}"
    elif k in ("해외세금환급", "외화입금", "외화가계정입"):
        f["O"], f["Q"] = f"={G}", f"=ROUND({G}*{N},0)"
    elif k in ("외화출금", "외화가계정출"):
        f["O"], f["Q"] = f"=-{G}", out_book(G)
    s = {"입금": f"={I}", "출금": f"=-{I}", "환전_원화외화": f"=-{I}", "환전_외화원화": f"={I}", "환전정산입금": f"={I}",
         "환전정산출금": f"=-{I}", "원화세금": f"=-{I}", "국내매수": f"=-({I}+{J})", "국내매도": f"={I}-{J}",
         "국내배당": f"={I}-{J}", "원화이자": f"={I}-{J}", "대여수수료": f"={I}-{J}", "원화가계정입": f"={I}",
         "원화가계정출": f"=-{I}"}.get(k)
    if s:
        f["S"] = s
    if k in ("해외매수", "국내매수"):
        f["U"] = f"={c('qty')}"
        f["Y"] = f"=ROUND({G}*{N},0)" if k == "해외매수" else f"={I}"
        f["AD"] = f"=ROUND({H}*{N},0)" if k == "해외매수" else f"={J}"
    elif k in ("해외매도", "국내매도"):
        f["U"], f["Y"] = f"=-{c('qty')}", out_cost
        f["AB"] = f"={Q}+{c('Y')}" if k == "해외매도" else f"={c('S')}+{c('Y')}"
    elif k == "주식수변동":
        if out_qty:
            f["U"], f["Y"] = f"=-{c('qty')}", out_cost
        else:
            # 종목코드가 바뀌는 기업행위: 같은 날 출고 행에서 떼어 놓은 장부금액을 가져온다
            p = i - 1
            f["U"] = f"={c('qty')}"
            f["Y"] = (f"=-SUMIFS(${COL['Y']}${FIRST}:{COL['Y']}{p},${COL['date']}${FIRST}:{COL['date']}{p},{c('date')},"
                      f"${COL['kind']}${FIRST}:{COL['kind']}{p},\"주식수변동\")")
    if k == "환전_외화원화":
        f["AC"] = f"={I}+{Q}"
    elif k == "해외매수":
        f["AC"] = f"={c('Y')}+{c('AD')}+{Q}"
    elif k == "해외원천세":
        f["AC"] = f"={c('AF')}+{Q}"
    if k in ("해외배당", "해외이자"):
        f["AE"], f["AF"] = f"=ROUND({G}*{N},0)", f"=ROUND({H}*{N},0)"
    elif k == "해외원천세":
        f["AF"] = f"=ROUND({H}*{N},0)"
    elif k in ("국내배당", "원화이자", "대여수수료"):
        f["AE"], f["AF"] = f"={I}", f"={J}"
    return f


def _cum(crit, field, row, end):
    """첫 자료 행부터 end 행까지 crit 열 값이 row 행과 같은 줄의 field 합(기초 줄 포함 누계)."""
    return (f"SUMIF(${COL[crit]}${FIRST}:{COL[crit]}{end},{COL[crit]}{row},"
            f"${COL[field]}${FIRST}:{COL[field]}{end})")


def _ledger(ws, res, opening, X):
    """거래원장. 맨 위 기초 줄은 「기초·기말」 시트 기초 잔고를 가리키고, 거래 줄은 증권사 파일 값에서 수식으로 계산한다.
    돌려주는 값: {'last': 마지막 행, 'rows': res.rows 차례의 행 번호}."""
    ws["A1"], ws["A1"].font = ("거래원장: 증권사 파일 값(수량 ~ 원화비용)과 기초 잔고에서 잔액 · 장부금액 · 손익을 수식으로 계산한다. "
                               "맨 위 기초 줄은 「기초·기말」 시트를 가리킨다. 차이 열이 0 이 아니면 계산 잔액이 증권사 잔액과 다르다"), BOLD
    for title, a, b in GROUPS:
        cell = ws.cell(2, IDX[a], title)
        cell.font, cell.fill = BOLD, HEAD
        cell.alignment = Alignment(horizontal="center")
        if IDX[b] > IDX[a]:
            ws.merge_cells(start_row=2, start_column=IDX[a], end_row=2, end_column=IDX[b])
    _header(ws, 3, [h for _, h, _, _ in LEDGER])

    def val(r, key, v):
        cell = ws.cell(r, IDX[key], _num(v))
        if FMT[key]:
            cell.number_format = FMT[key]

    def fml(r, key, formula, expected):
        _put(ws, r, IDX[key], formula, expected, X, FMT[key])

    r = FIRST
    # 기초 줄: 원화 · 외화 · 종목
    ref, krw = opening["krw"]
    val(r, "raw", "기초"), val(r, "kind", "기초"), val(r, "ccy", "KRW")
    fml(r, "S", f"={ref}", krw)
    fml(r, "T", f"=SUM(${COL['S']}${FIRST}:{COL['S']}{r})", krw)
    r += 1
    for ccy, ref_bal, bal, ref_book, book in opening["fx"]:
        val(r, "raw", "기초"), val(r, "kind", "기초"), val(r, "ccy", _text(ccy))
        fml(r, "O", f"={ref_bal}", bal)
        fml(r, "P", f"=ROUND({_cum('ccy', 'O', r, r)},3)", E.R3(bal))
        fml(r, "Q", f"={ref_book}", book)
        r += 1
    run_qty = {}
    for s in opening["sec"]:
        key = _text(s["key"])
        val(r, "raw", "기초"), val(r, "kind", "기초"), val(r, "name", s["name"]), val(r, "key", key)
        val(r, "ccy", s["ccy"])
        fml(r, "U", f"={s['qty'][0]}", s["qty"][1])
        if s["lent"][1]:
            fml(r, "AT", f"={s['lent'][0]}", s["lent"][1])
        run_qty[key] = run_qty.get(key, Decimal(0)) + s["qty"][1]
        fml(r, "AG", f"={_cum('key', 'U', r, r)}", run_qty[key])
        fml(r, "Y", f"={s['book'][0]}", s["book"][1])
        r += 1

    rows = []
    for row in res.rows:
        t, k = row.tx, row.kind
        fx = t.ccy != "KRW"
        rows.append(r)
        for key, v in (("seq", t.seq), ("date", t.date), ("raw", t.raw_type), ("kind", k), ("name", t.name),
                       ("key", _text(t.key)), ("ccy", _text(t.ccy)), ("qty", t.qty or None), ("G", t.G or None),
                       ("H", t.H or None), ("I", t.I or None), ("J", t.J or None), ("rsrc", row.rate_src or None)):
            val(r, key, v)
        if fx and t.fx_bal is not None:
            val(r, "fxb", t.fx_bal)
        if t.krw_bal is not None:
            val(r, "krb", t.krw_bal)
        if t.hold_qty is not None:
            val(r, "hq", t.hold_qty)
        if fx and k in ("환전_원화외화", "환전_외화원화"):
            fml(r, "N", f"=IF({COL['G']}{r}=0,0,{COL['I']}{r}/{COL['G']}{r})", row.N)
        elif fx and row.N:
            val(r, "N", row.N)
        engine = {"O": row.O, "Q": row.Q, "S": row.S, "U": row.U, "Y": row.Y, "AD": row.AD, "AB": row.AB,
                  "AC": row.AC, "AE": row.AE, "AF": row.AF}
        for key, formula in _kind_formulas(k, r, k == "주식수변동" and E.is_out(t.raw_type)).items():
            fml(r, key, formula, engine[key])
        if fx and (k in E.LINES or k == "주식수변동"):
            fml(r, "P", f"=ROUND({_cum('ccy', 'O', r, r)},3)", row.P)
        if fx and k in E.LINES:
            fml(r, "pk", f"={_cum('ccy', 'Q', r, r - 1)}", row.R - row.Q)
        if k in E.LINES or k == "주식수변동":
            fml(r, "T", f"=SUM(${COL['S']}${FIRST}:{COL['S']}{r})", row.T)
        if k in HOLD:
            fml(r, "AG", f"={_cum('key', 'U', r, r)}", row.AG)
            fml(r, "W", f"={_cum('key', 'Y', r, r - 1)}", row.W)
        if k == "대여":
            fml(r, "AT", f"={'' if '출고' in t.raw_type else '-'}{COL['qty']}{r}", row.AT)
        if k not in NO_BALANCE:
            if t.krw_bal is not None and (t.ccy == "KRW" or row.S != 0):
                fml(r, "krd", f"={COL['T']}{r}-{COL['krb']}{r}", row.T - t.krw_bal)
            if t.fx_bal is not None and fx:
                fml(r, "fxd", f"={COL['P']}{r}-{COL['fxb']}{r}", row.P - t.fx_bal)
            if t.hold_qty is not None and k in HOLD:
                fml(r, "hqd", f"={COL['AG']}{r}-{_cum('key', 'AT', r, r)}-{COL['hq']}{r}", row.AG - row.AS - t.hold_qty)
        r += 1
    last = r - 1
    ws.freeze_panes = f"C{FIRST}"
    ws.auto_filter.ref = f"A3:{COL['rsrc']}{last}"
    for key in DIFF:
        ws.conditional_formatting.add(f"{COL[key]}{FIRST}:{COL[key]}{last}",
                                      CellIsRule(operator="notEqual", formula=["0"], fill=BAD))
    for key, _, w, _ in LEDGER:
        ws.column_dimensions[COL[key]].width = w
    ws.row_dimensions[3].height = 30
    return {"last": last, "rows": rows}


# ---------------------------------------------------------------- 기초 · 기말
def _opening(ws, cfg):
    """기초 잔고 표(값). 거래원장 기초 줄이 이 칸들을 가리킨다. 돌려주는 값: (칸 주소와 값, 다음 행)."""
    begin = cfg.get("기초") or {}
    ws["A1"], ws["A1"].font = ("기초 · 기말: 기초는 설정 「기초」(비었으면 거래내역에서 추정), 기말 수량 · 장부금액은 거래원장 합계, "
                               "기말 평가는 설정 「기말」 의 단가 · 환율"), BOLD
    q = _q(SHEET_B)
    ws.cell(3, 1, "기초 잔고").font = Font(bold=True, size=12)
    _header(ws, 4, ["구분", "이름", "통화", "수량 · 외화잔액", "장부금액(원)", "대여 중 수량", "출처 · 비고"])
    r = 5
    out = {"fx": [], "sec": []}

    def row_(vals, note):
        for j, v in enumerate(vals, 1):
            ws.cell(r, j, _num(v))
        ws.cell(r, 7, note)
        ws.cell(r, 4).number_format, ws.cell(r, 5).number_format = QTYF, NUMF
        if "추정" in str(note):
            ws.cell(r, 7).fill = INPUT

    krw = Decimal(str(begin.get("원화예수금", 0) or 0))
    row_(("원화예수금", "", "KRW", None, krw, None), "")
    out["krw"] = (f"{q}E{r}", krw)
    r += 1
    for c, v in sorted((begin.get("외화") or {}).items()):
        bal, book = Decimal(str(v.get("잔액", 0) or 0)), Decimal(str(v.get("장부금액", 0) or 0))
        row_(("외화예수금", c, c, bal, book, None), v.get("출처", ""))
        ws.cell(r, 4).number_format = FXF
        out["fx"].append((c, f"{q}D{r}", bal, f"{q}E{r}", book))
        r += 1
    for s in begin.get("종목") or []:
        qty, book = Decimal(str(s.get("수량", 0) or 0)), Decimal(str(s.get("장부금액", 0) or 0))
        lent = Decimal(str(s.get("대여중", 0) or 0))
        row_(("종목", s["종목"], s.get("통화", "KRW"), qty, book, lent or None), s.get("출처", ""))
        out["sec"].append({"key": s.get("종목코드") or s["종목"], "name": s["종목"], "ccy": s.get("통화", "KRW"),
                           "qty": (f"{q}D{r}", qty), "book": (f"{q}E{r}", book), "lent": (f"{q}F{r}", lent)})
        r += 1
    return out, r


def _closing(ws, r, res, cfg, led, X):
    """기말 표. 수량 · 장부금액은 거래원장에서 SUMIF 로 모으고, 평가 · 환산은 단가 · 환율(값)로 계산한다."""
    begin = cfg.get("기초") or {}
    end = cfg.get("기말") or {}
    L, last = _q(SHEET_L), led["last"]
    rng = lambda key: f"{L}${COL[key]}${FIRST}:${COL[key]}${last}"
    r += 1
    ws.cell(r, 1, "기말").font = Font(bold=True, size=12)
    ws.cell(r, 3, f"기말일 {end.get('일자') or '없음'} · 단가 출처 {end.get('단가출처') or '없음'}")
    r += 1
    ws.cell(r, 1, "원화예수금 기말 잔액(계산)")
    krw_end = Decimal(str(begin.get("원화예수금", 0) or 0)) + sum((x.S for x in res.rows), Decimal(0))
    _put(ws, r, 5, f"=SUM({rng('S')})", krw_end, X, NUMF)
    r += 2
    _header(ws, r, ["종목", "종목코드", "통화", "보유수량", "보유원가(원)", "기말단가", "기말환율", "평가액(원)", "평가손익"])
    r += 1
    ye = {}
    for i, it in enumerate(res.year_end):
        ws.cell(r, 1, it["name"]), ws.cell(r, 2, _text(it["key"])), ws.cell(r, 3, it["ccy"])
        _put(ws, r, 4, f"=SUMIF({rng('key')},B{r},{rng('U')})", it["qty"], X, QTYF)
        _put(ws, r, 5, f"=SUMIF({rng('key')},B{r},{rng('Y')})", it["cost"], X, NUMF)
        ws.cell(r, 6, _num(it["price"])).number_format = RATEF
        ws.cell(r, 7, _num(it["rate"])).number_format = RATEF
        if it["fv"] is not None:
            _put(ws, r, 8, f"=ROUND(D{r}*F{r}*G{r},0)", it["fv"], X, NUMF)
            _put(ws, r, 9, f"=H{r}-E{r}", it["pl"], X, NUMF)
        elif it["qty"] != 0:
            ws.cell(r, 6).fill = BAD
        ye[i] = r
        r += 1
    r += 1
    _header(ws, r, ["외화예수금", "", "", "외화잔액", "장부금액(원)", "", "기말환율", "환산액(원)", "환산손익"])
    r += 1
    fx = {}
    for i, it in enumerate(res.fx_end):
        ws.cell(r, 1, _text(it["ccy"]))
        _put(ws, r, 4, f"=ROUND(SUMIF({rng('ccy')},A{r},{rng('O')}),3)", it["bal"], X, FXF)
        _put(ws, r, 5, f"=SUMIF({rng('ccy')},A{r},{rng('Q')})", it["book"], X, NUMF)
        ws.cell(r, 7, _num(it["rate"])).number_format = RATEF
        if it["rate"] is not None:
            _put(ws, r, 8, f"=ROUND(D{r}*G{r},0)", it["krw"], X, NUMF)
            _put(ws, r, 9, f"=H{r}-E{r}", it["pl"], X, NUMF)
        else:
            ws.cell(r, 7).fill = BAD
        fx[i] = r
        r += 1
    for row in ws.iter_rows(min_row=3):
        for c in row:
            if c.column == 7 and isinstance(c.value, str):
                c.alignment = Alignment(wrap_text=True, vertical="top")
    for col, w in zip("ABCDEFGHI", (26, 22, 10, 16, 16, 14, 40, 16, 14)):
        ws.column_dimensions[col].width = w
    return {"ye": ye, "fx": fx}


# ---------------------------------------------------------------- 전표
def _journal(ws, lines, led, clo, X):
    ws["A1"], ws["A1"].font = ("전표: 위하고 업로드 파일과 같은 줄(0원 줄 제외). 금액은 거래원장 칸(결산 줄 Y 는 기초·기말 시트 "
                               "평가손익 칸)을 가리키는 수식이다. 거래번호는 거래원장 순번"), BOLD
    head = ["거래번호", "일자", "구분", "계정코드", "계정과목명", "거래처명", "적요", "차변", "대변"]
    _header(ws, 2, head)
    L, B = _q(SHEET_L), _q(SHEET_B)
    r = 3
    for ln in lines:
        for j, v in enumerate([ln["key"], ln["date"], ln["gubun"], ln["code"], ln["name"], ln["party"], ln["memo"]], 1):
            ws.cell(r, j, v)
        ws.cell(r, 2).number_format = DATEF
        amt_col = 8 if ln["dr"] else 9
        ws.cell(r, 17 - amt_col, 0).number_format = NUMF
        amount = ln["dr"] or ln["cr"]
        src = ln.get("src")
        if src and src[0] == "L":
            _, j, field, sign = src
            key, s2 = {"X": ("Y", 1), "Z": ("Y", -1)}.get(field, (field, 1))
            f = f"={'-' if sign * s2 < 0 else ''}{L}{COL[key]}{led['rows'][j]}"
            _put(ws, r, amt_col, f, amount, X, NUMF)
        elif src:
            kind, i, sign = src
            row = clo["ye" if kind == "Y" else "fx"][i]
            _put(ws, r, amt_col, f"={'-' if sign < 0 else ''}{B}I{row}", amount, X, NUMF)
        else:
            ws.cell(r, amt_col, amount).number_format = NUMF
        r += 1
    ws.cell(r, 7, "합계").font = BOLD
    dr, cr = sum(ln["dr"] for ln in lines), sum(ln["cr"] for ln in lines)
    if lines:
        _put(ws, r, 8, f"=SUM(H3:H{r - 1})", dr, X, NUMF)
        _put(ws, r, 9, f"=SUM(I3:I{r - 1})", cr, X, NUMF)
    else:
        ws.cell(r, 8, 0), ws.cell(r, 9, 0)
    ws.cell(r, 8).font = ws.cell(r, 9).font = BOLD
    ws.freeze_panes = "A3"
    ws.auto_filter.ref = f"A2:I{max(2, r - 1)}"
    for col, w in zip("ABCDEFGHI", (9, 11, 5, 8, 18, 14, 44, 13, 13)):
        ws.column_dimensions[col].width = w
    return r


# ---------------------------------------------------------------- 검증 워크북
def build(path, res, lines, cks, broker="", status=0, upload_note="", upload_checks=(), diag=None, opening_hint=None):
    """검증 워크북을 쓴다. 수식을 다시 계산해 엔진 값과 다른 칸이 있으면 확인필요로 올린다.

    돌려주는 값: (결론 코드, 수식 재계산 검산 줄 (항목, 값, 판정, 설명), 다른 칸 [(시트, 칸, 수식, 계산값, 엔진 값)]).
    """
    cfg = res.cfg
    wb = Workbook()
    ws = wb.active
    ws.title = SHEET_S
    wsJ, wsL, wsB = wb.create_sheet(SHEET_J), wb.create_sheet(SHEET_L), wb.create_sheet(SHEET_B)
    X = {}
    opening, r = _opening(wsB, cfg)
    led = _ledger(wsL, res, opening, X)
    clo = _closing(wsB, r, res, cfg, led, X)
    jt = _journal(wsJ, lines, led, clo, X)
    fc_row = _summary(ws, res, lines, cks, broker, upload_note, upload_checks, diag or [], opening_hint or [],
                      {"last": led["last"], "jt": jt, **clo}, X)
    bad = FC.check(wb, X)
    fc = (FC_NAME, len(bad), "OK" if not bad else "확인필요", FC_DESC)
    ws.cell(fc_row, 2, len(bad)).number_format = NUMF
    ws.cell(fc_row, 3, fc[2]).fill = GOOD if not bad else INPUT
    if bad and status == 0:
        status = 2
    ws["B4"], ws["B4"].font = {0: "통과", 2: "확인필요", 3: "중단"}.get(status, str(status)), BOLD
    ws["B4"].fill = GOOD if status == 0 else BAD if status == 3 else INPUT
    wb.save(path)
    FC.write_cached(path, X)
    return status, fc, bad


def _summary(ws, res, lines, cks, broker, upload_note, upload_checks, diag, hint, ref, X):
    """요약 시트. 검산 · 합계 가운데 다른 시트에서 셀 수 있는 것은 수식으로 쓴다. 돌려주는 값: 수식 재계산 검산 줄의 행."""
    cfg = res.cfg
    dates = [r.tx.date for r in res.rows if r.tx.date]
    period = f"{min(dates)} ~ {max(dates)}" if dates else ""
    ws["A1"], ws["A1"].font = "증권 거래 전표 검증", Font(bold=True, size=14)
    ws["A2"] = (f"회사 {cfg.get('회사', '')} · 증권사 {broker or '판별 못함'} · 거래 {period} · 분류 {cfg.get('분류', '단기매매')} · "
                f"만든 때 {dt.datetime.now():%Y-%m-%d %H:%M}")
    ws["A4"], ws["A4"].font = "결론", BOLD
    ws["D4"] = upload_note
    ws["D4"].alignment = Alignment(wrap_text=True, vertical="top")
    ws["A5"] = PASS_NOTE
    ws["A6"] = EDIT_NOTE
    L, B, J = _q(SHEET_L), _q(SHEET_B), _q(SHEET_J)
    last, jt = ref["last"], ref["jt"]
    r = 8

    def section(title, names, cols):
        nonlocal r
        ws.cell(r, 1, title).font = Font(bold=True, size=12)
        r += 1
        for name, col in zip(names, cols):
            _header(ws, r, [name], col)
        r += 1

    def mark(cell, v):
        cell.fill = GOOD if v == "OK" else BAD if v in ("중단", "반려", "위험") else INPUT if v in ("확인필요", "확인") else PatternFill()

    def nonzero(key):
        rg = f"{L}{COL[key]}{FIRST}:{COL[key]}{last}"
        return f'=COUNTIF({rg},">0")+COUNTIF({rg},"<0")'

    by_formula = {
        "전표 차변 − 대변": (f"={J}H{jt}-{J}I{jt}", "중단"),
        "원화잔액 불일치 수": (nonzero("krd"), "확인필요"),
        "외화잔액 불일치 수": (nonzero("fxd"), "확인필요"),
        "보유수량 불일치 수": (nonzero("hqd"), "확인필요"),
    }
    section("검산", ["항목", "값", "판정", "설명"], [1, 2, 3, 4])
    for name, val, verdict_, desc in cks:
        ws.cell(r, 1, name)
        if name in by_formula and (name != "전표 차변 − 대변" or lines):
            formula, bad = by_formula[name]
            _put(ws, r, 2, formula, val, X, NUMF)
            c = _put(ws, r, 3, f'=IF(B{r}=0,"OK","{bad}")', verdict_, X)
        else:
            ws.cell(r, 2, _num(val)).number_format = NUMF
            c = ws.cell(r, 3, verdict_)
        mark(c, verdict_)
        ws.cell(r, 4, desc)
        r += 1
    fc_row = r
    ws.cell(r, 1, FC_NAME), ws.cell(r, 4, FC_DESC)
    r += 2
    section("위하고 올리기 전 검사", ["항목", "값", "판정", "예"], [1, 2, 3, 4])
    if not upload_checks:
        ws.cell(r, 1, "업로드 파일을 만들지 않아 검사하지 않았다")
        r += 1
    for name, val, verdict_, ex in upload_checks:
        ws.cell(r, 1, name), ws.cell(r, 2, _num(val))
        mark(ws.cell(r, 3, verdict_), verdict_)
        ws.cell(r, 4, ex)
        r += 1
    r += 1

    def col_sum(key):
        return f"=SUM({L}{COL[key]}{FIRST}:{COL[key]}{last})"

    def rows_sum(rows, col):
        rs = sorted(rows.values())
        return f"=SUM({B}{col}{rs[0]}:{col}{rs[-1]})" if rs else None

    sums = {"처분손익": col_sum("AB"), "외환차손익": col_sum("AC"), "배당 · 이자수익(세전)": col_sum("AE"),
            "원천세 · 현지세": col_sum("AF"), "지급수수료(매수 수수료)": col_sum("AD"),
            "기말 평가손익": rows_sum(ref["ye"], "I"), "외화예수금 환산손익": rows_sum(ref["fx"], "I"),
            "기말 보유원가": rows_sum(ref["ye"], "E"),
            "전표 차변 합계": f"={J}H{jt}" if lines else None, "전표 대변 합계": f"={J}I{jt}" if lines else None}
    section("합계", ["항목", "금액(원)"], [1, 2])
    for name, v in totals(res, lines):
        ws.cell(r, 1, name)
        if sums.get(name):
            _put(ws, r, 2, sums[name], v, X, NUMF)
        else:
            ws.cell(r, 2, _num(v)).number_format = NUMF
        r += 1
    r += 1
    if diag:
        section("자료 진단", ["항목", "", "판정", "내용", "할 일"], [1, 2, 3, 4, 5])
        for name, verdict_, body, todo in diag:
            ws.cell(r, 1, name)
            mark(ws.cell(r, 3, verdict_), verdict_)
            ws.cell(r, 4, body), ws.cell(r, 5, todo)
            r += 1
        r += 1
    section("확인사항", ["구분", "순번", "일자", "내용", "회계사 결론"], [1, 2, 3, 4, 5])
    for kind, tx, msg in res.issues:
        ws.cell(r, 1, kind)
        if tx is not None:
            ws.cell(r, 2, tx.seq)
            ws.cell(r, 3, tx.date).number_format = DATEF
            msg = f"{tx.raw_type} {tx.name}".strip() + ": " + msg
        ws.cell(r, 4, msg)
        mark(ws.cell(r, 1), "중단" if kind == "중단" else "확인" if kind in ("확인", "대사", "미분류", "검토대기") else "")
        ws.cell(r, 5).fill = INPUT
        r += 1
    for h in hint:
        ws.cell(r, 1, "기초 추정"), ws.cell(r, 4, h)
        ws.cell(r, 5).fill = INPUT
        r += 1
    for row in ws.iter_rows(min_row=4):
        for c in row:
            if c.row not in (5, 6) and not (c.fill and c.fill.fgColor.rgb == HEAD.fgColor.rgb):
                c.alignment = Alignment(wrap_text=c.column in (1, 4, 5), vertical="top")
    for col, w in zip("ABCDE", (44, 12, 10, 80, 36)):
        ws.column_dimensions[col].width = w
    return fc_row
