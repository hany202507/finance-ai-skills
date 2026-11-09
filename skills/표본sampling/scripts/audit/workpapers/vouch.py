"""표본 증빙 대조 표와 부속 시트가 없던 영역의 시트(2026-10-09).

요청 「남은 것도 다 개발해」(계정별 조서 연결 점검, 설계 문서 3절).

  table(...)                 표본 한 줄마다 받은 증빙 · 검사 항목(금액 · 일자 · 기간 · 거래처 · 증빙 종류) · 검사 결과 칸.
                             4000C · 4000P · 아래 영역 표본이 같은 표를 쓴다
  add_sheets(b, code, ctx)   4000A 금융기관별 잔액, 4000CC · 4000EE · 4000Q · 4000R 증빙 대조 표본, 4000GG 자본 변동(전수)
                             4000R 은 같은 표시과목인데 다른 영역이 맡는 계정을 모집단에서 빼고 무엇을 뺐는지 표본 근거에 적는다(2026-10-12)

검사 항목 칸은 감사인이 고른다(√ 일치 · ✗ 다름 · 해당 없음). 엔진은 증빙 파일을 이름으로 잇기만 하고 내용을 판정하지 않는다.
틱마크는 엔진이 실제로 대사한 곳에만 단다(C 조회 · 잔액증명 일치). V(증빙과 대사)는 감사인이 단다.
"""
from __future__ import annotations

from pathlib import Path

from openpyxl.worksheet.datavalidation import DataValidation

from .. import reader, wp
from . import common, sampling
from .common import ask

CHOICES = ["√ 일치", "✗ 다름", "해당 없음"]
EV_KINDS = ["세금계산서", "계약서", "거래명세서", "출고증 · 인수증", "입금표 · 통장", "청구서 · 영수증", "잔액확인서", "기타"]
# (머리 글, 기입란 이름 앞머리). 「증빙」 은 예전 「증빙」 칸의 이름을 그대로 써서 이미 적은 값이 옮겨 온다
ATTRS = [("금액", "금액 대사"), ("일자 · 기간", "기간 귀속"), ("거래처", "거래처 대사")]
TOT_ATTR = ("입금 · 지급", "통장 대사")          # 감사-TOT 표본 표에만(2026-10-26). 통장 입금 · 지급을 감사인이 확인한다


def _dv(ws, values: list[str]):
    dv = DataValidation(type="list", formula1='"' + ",".join(values) + '"', allow_blank=True)
    ws.add_data_validation(dv)
    return dv


def evidence_note(files: list[str]) -> str:
    if not files:
        return "받은 증빙: 받은자료 증빙 폴더가 비어 있습니다. 표본 증빙을 넣고 다시 만들면 파일 이름의 거래처 · 전표번호로 행에 잇습니다"
    return (f"받은 증빙: 받은자료 증빙 폴더 파일 {len(files)}개를 이름(거래처 · 전표번호)으로 이었습니다. 파일 안의 내용은 보지 않았으므로 "
            "검사 항목과 검사 결과는 감사인이 증빙을 보고 적습니다")


def evidence_cell(b, ws, row: int, col: int, hits: list[str], any_files: bool) -> None:
    if hits:
        names = [Path(h).name for h in hits[:3]] + ([f"외 {len(hits) - 3}개"] if len(hits) > 3 else [])
        b.put(ws, row, col, "; ".join(names), wrap=True)
    else:
        b.put(ws, row, col, "없음" if any_files else "", flag=any_files)


def table(b, ws, row: int, selected: list[dict], label: str, evidence: list[str], match, pre: list[tuple] | None = None,
          reason=None, tot=None) -> tuple[int, int]:
    """표본 표. (다음 행, 첫 행). pre 는 [(머리 글, fn(r) -> (값, 강조))] 로 선정 이유 뒤에 붙는 열(4000C 조회 상태).
    match(r) 은 그 행에 이을 증빙 파일 목록. reason(r) 은 선정 이유 글(기본: 고액 항목 · 간격 선정).
    tot(r) 을 주면(감사-TOT, 2026-10-26) 받은 증빙 앞에 엔진 대조 칸 아홉(tot.HEADS)을 넣고 확인 칸에 「입금 · 지급」 을 더한다.
    tot(r) 은 tot.check 결과 dict 이고 r["tot"] 에 남긴다. 확인 칸 · 검사 결과는 엔진이 채우지 않는다."""
    from . import tot as tot_mod

    pre = pre or []
    attrs = ATTRS + ([TOT_ATTR] if tot else [])
    auto = tot_mod.HEADS if tot else []
    heads = ["#", label, "금액", "누적 금액", "걸린 점 수", "선정 이유"] + [h for h, _ in pre] + auto + \
            ["받은 증빙"] + [h for h, _ in attrs] + ["증빙 종류", "검사 결과", "왜곡표시 금액"]
    row = b.head(ws, row, heads)
    c_auto = 7 + len(pre)
    c_ev = c_auto + len(auto)
    c_attr = c_ev + 1
    c_kind = c_attr + len(attrs)
    c_err = c_kind + 2
    b.sample_cols = {"err": c_err, "result": c_kind + 1, "check": c_attr}      # eval_numbers 가 읽는다. 금액 대사가 첫 확인 칸이다
    dv_ok, dv_kind = _dv(ws, CHOICES), _dv(ws, EV_KINDS)
    dv_err = DataValidation(type="decimal", operator="between", formula1="-1000000000000000", formula2="1000000000000000", allow_blank=True,
                            showErrorMessage=True, error="왜곡표시 금액은 숫자로 적습니다. 설명은 검사 결과 칸에 적습니다")
    ws.add_data_validation(dv_err)
    first = row
    for n, r in enumerate(selected, 1):
        b.put(ws, row, 1, n)
        b.put(ws, row, 2, r["key"], wrap=True)
        b.put(ws, row, 3, r["amount"], fmt=wp.WON)
        b.put(ws, row, 4, r.get("cum"), fmt=wp.WON)
        b.put(ws, row, 5, r.get("hits"))
        why = reason(r) if reason else ("고액 항목" if r.get("key_item") else "간격 선정")
        b.put(ws, row, 6, why, flag=bool(r.get("key_item")))
        for i, (_, fn) in enumerate(pre):
            v, fl = fn(r)
            b.put(ws, row, 7 + i, v, wrap=True, flag=fl)
        if tot:
            r["tot"] = tot(r)
            if r["tot"]:
                tot_mod.put(b, ws, row, c_auto, r["tot"])
        evidence_cell(b, ws, row, c_ev, match(r), bool(evidence))
        for i, (_, lab) in enumerate(attrs):
            dv_ok.add(ask(b, ws, row, c_attr + i, f"{lab}: {r['key']}", rule="optional").coordinate)
        dv_kind.add(ask(b, ws, row, c_kind, f"증빙: {r['key']}", rule="optional").coordinate)
        ask(b, ws, row, c_kind + 1, f"검사 결과: {r['key']}")
        dv_err.add(ask(b, ws, row, c_err, f"왜곡표시 금액: {r['key']}", rule="optional", fmt=wp.WON).coordinate)
        row += 1
    return row, first


def _is_mus(s: dict | None) -> bool:
    return bool(s and s.get("selected") and str(s.get("method") or "").startswith("금액 단위"))


HELP_HEADS = ["투영(과대)", "투영(과소)", "증분 허용(과대)", "증분 허용(과소)"]


def eval_numbers(b, ws, row: int, s: dict, first: int, last: int, title: str) -> tuple[int, dict]:
    """표 하나의 표본 결과 수치(감사기준서 530 문단 14). 금액 단위 표본의 투영이다. 고액 기준(기본은 표본 간격) 이상 항목은 왜곡표시 그대로,
    미만은 오염률(왜곡표시 ÷ 장부 금액) × 표본 간격. 과대 · 과소를 상계하지 않으려고 나눠 둔다.
    표 오른쪽에 항목별 투영 칸을 수식으로 둔다(2026-11-09). 증분 허용 칸은 표를 다 만든 뒤 eval_conclude 가 채운다(순위를 표를 가로질러 매긴다).
    수식이라 칸을 적으면 바로 바뀐다. (다음 행, 칸 주소 · 표 정보)."""
    from openpyxl.utils import get_column_letter as L

    c = b.sample_cols
    iv = s["interval"]
    kt = min(s.get("key_threshold") or iv, iv)
    E, R, K = L(c["err"]), L(c["result"]), L(c["check"])
    h = c["err"] + 1
    po, pu, io, iu = (L(h + i) for i in range(4))
    b.head(ws, first - 1, HELP_HEADS, col=h)
    for i in range(4):
        ws.column_dimensions[L(h + i)].width = 14
    for r in range(first, last + 1):
        b.put(ws, r, h, f"=IF(AND(ISNUMBER({E}{r}),{E}{r}>0,C{r}<{kt}),{E}{r}/C{r}*{iv},0)", fmt=wp.WON)
        b.put(ws, r, h + 1, f"=IF(AND(ISNUMBER({E}{r}),{E}{r}<0,C{r}<{kt}),-{E}{r}/C{r}*{iv},0)", fmt=wp.WON)
    amt, err = f"C{first}:C{last}", f"{E}{first}:{E}{last}"
    res, chk = f"{R}{first}:{R}{last}", f"{K}{first}:{K}{last}"
    row = b.section(ws, row, title)
    refs = {"first": first, "last": last, "po": po, "pu": pu, "io": io, "iu": iu, "interval": iv, "key": kt,
            "factor": s["factor"], "confidence": s.get("confidence"), "err": E}
    for key, lab, val, fmt in [("pending", "검사 결과가 빈 항목", f"=COUNTBLANK({res})", "#,##0"),
                               ("nodiff", "금액 대사가 「✗ 다름」 인데 왜곡표시 금액이 빈 항목", f'=COUNTIFS({chk},"{CHOICES[1]}",{err},"")', "#,##0"),
                               ("found", "표본에서 찾은 왜곡표시(순액)", f"=SUM({err})", wp.WON),
                               ("over", "투영한 왜곡표시: 과대계상(고액 그대로 + 투영)",
                                f"=SUMPRODUCT(({amt}>={kt})*({err}>0)*{err})+SUM({po}{first}:{po}{last})", wp.WON),
                               ("under", "투영한 왜곡표시: 과소계상(고액 그대로 + 투영)",
                                f"=SUMPRODUCT(({amt}>={kt})*({err}<0)*{err})-SUM({pu}{first}:{pu}{last})", wp.WON)]:
        ws.cell(row, 1, lab).font = wp.font(color=wp.MUTED)
        b.put(ws, row, 2, val, fmt=fmt)
        refs[key] = f"B{row}"
        row += 1
    return row + 1, refs


def _factor_block(b, ws, row: int, col: int, conf: float, n: int) -> str:
    """오류 k 건 포아송 상한 F(k) 와 ΔF(k) 표를 col 열부터 쓴다. ΔF 범위(절대 주소)를 돌려준다."""
    from openpyxl.utils import get_column_letter as L

    from . import sampling_eval as se

    ws.cell(row, col, f"MUS 계수 (신뢰수준 {conf:.1%}, 오류 k 건 포아송 상한)").font = wp.font(bold=True, color=wp.NAVY)
    row = b.head(ws, row + 1, ["k", "F(k)", "ΔF(k) = F(k) − F(k−1)"], col=col)
    top = row
    for k, f, d in se.factor_table(conf, max(n, 1)):
        b.put(ws, row, col, k, fmt="0")
        b.put(ws, row, col + 1, f, fmt="0.0000")
        b.put(ws, row, col + 2, d, fmt="0.0000")
        row += 1
    for i, w in enumerate((6, 10, 14)):
        ws.column_dimensions[L(col + i)].width = max(ws.column_dimensions[L(col + i)].width or 0, w)
    return f"${L(col + 2)}${top}:${L(col + 2)}${row - 1}"


def _increments(b, ws, refs: list[dict], df: str) -> None:
    """증분 허용 칸. 투영 값을 모든 표를 합쳐 큰 순서로 세운 순위 i 에 (ΔF(i) − 1) 을 곱한다. 같은 값은 앞 표 · 위 행이 먼저다.
    순위의 「큰 값 수」 는 SUMPRODUCT 로 센다(COUNTIF 의 ">"&x 는 x 를 글자로 바꿔 소수가 잘린다)."""
    from openpyxl.utils import column_index_from_string as CI

    for side, inc in (("po", "io"), ("pu", "iu")):
        rngs = [f"${t[side]}${t['first']}:${t[side]}${t['last']}" for t in refs]
        for ti, t in enumerate(refs):
            col = CI(t[inc])
            for r in range(t["first"], t["last"] + 1):
                x = f"{t[side]}{r}"
                above = "+".join(f"SUMPRODUCT(({g}>{x})*1)" for g in rngs)
                ties = "".join(f"+COUNTIF({g},{x})" for g in rngs[:ti])
                rank = f"{above}{ties}+COUNTIF(${t[side]}${t['first']}:{x},{x})"
                b.put(ws, r, col, f"=IF({x}>0,{x}*(INDEX({df},{rank})-1),0)", fmt=wp.WON)


def eval_conclude(b, ws, row: int, refs: list[dict], tolerable, what: str) -> int:
    """표본 결과 평가(감사기준서 530 문단 11 · 13 · 15 · A19 · A22 · A23). 기간 · 층으로 나눠 뽑은 표는 refs 를 모아 한 번만 판정한다.
    2026-11-09: 상한 왜곡표시 = 기본 정밀도(신뢰계수 × 표본 간격) + 투영 + 증분 허용 + 변이를 과대 · 과소 따로 내어
    허용왜곡표시와 견준다. 표가 여럿이어도 같은 간격 · 같은 신뢰수준이라 합쳐 계산한다. 엔진 계산은 sampling_eval.mus 와 같다."""
    from openpyxl.utils import column_index_from_string as CI
    from openpyxl.utils import get_column_letter as L

    from . import sampling_eval as se

    total = lambda k: "+".join(r[k] for r in refs)
    t0 = refs[0]
    conf = t0["confidence"] or se.confidence_of(t0["factor"])
    n = sum(t["last"] - t["first"] + 1 for t in refs)
    fcol = CI(t0["iu"]) + 2
    df = _factor_block(b, ws, row, fcol, conf, n)
    _increments(b, ws, refs, df)
    rng = lambda k: ",".join(f"{t[k]}{t['first']}:{t[k]}{t['last']}" for t in refs)
    row = b.section(ws, row, f"표본 결과 평가 (감사기준서 530 문단 15 · A22): {what}")
    ws.cell(row, 1, "변이로 본 왜곡표시 금액(왜곡표시 금액 칸에서 빼고 여기 적음, 과대계상 양수)").font = wp.font(color=wp.MUTED)
    anomaly = f"B{row}"
    ask(b, ws, row, 2, f"변이 왜곡표시: {what}", rule="optional", fmt=wp.WON)
    row += 1
    cells = {}
    lines = [("bp", "기본 정밀도 = 신뢰계수 × 표본 간격", f"={t0['factor']}*{t0['interval']}"),
             ("pov", "투영한 왜곡표시: 과대계상 합", f"={total('over')}"),
             ("iov", "증분 허용: 과대계상(투영 큰 순서 i 에 ΔF(i) − 1 을 곱해 더함)", f"=SUM({rng('io')})"),
             ("uov", "상한 왜곡표시: 과대계상 = 기본 정밀도 + 투영 + 증분 + 변이", None),
             ("pun", "투영한 왜곡표시: 과소계상 합(양수로)", f"=-({total('under')})"),
             ("iun", "증분 허용: 과소계상", f"=SUM({rng('iu')})"),
             ("uun", "상한 왜곡표시: 과소계상 = 기본 정밀도 + 투영 + 증분 + 변이", None),
             ("est", "모집단 왜곡표시 추정치 = 투영(과대 − 과소) + 변이 (문단 A22 최선의 추정치)", None)]
    for key, lab, f in lines:
        ws.cell(row, 1, lab).font = wp.font(color=wp.MUTED)
        cells[key] = f"B{row}"
        row += 1

    def put(k, f):
        b.put(ws, int(cells[k][1:]), 2, f, fmt=wp.WON, bold=k in ("uov", "uun"))

    for key, _, f in lines:
        if f:
            put(key, f)
    put("uov", f"={cells['bp']}+{cells['pov']}+{cells['iov']}+MAX(N({anomaly}),0)")
    put("uun", f"={cells['bp']}+{cells['pun']}+{cells['iun']}+MAX(-N({anomaly}),0)")
    put("est", f"={cells['pov']}-{cells['pun']}+N({anomaly})")
    ws.cell(row, 1, "허용왜곡표시").font = wp.font(color=wp.MUTED)
    tol = f"B{row}"
    b.put(ws, row, 2, tolerable, fmt=wp.WON)
    row += 1
    ws.cell(row, 1, "허용왜곡표시와 견줌").font = wp.font(color=wp.MUTED)
    hi = f"MAX({cells['uov']},{cells['uun']})"
    none = f"AND({cells['pov']}=0,{cells['pun']}=0,N({anomaly})=0)"
    b.put(ws, row, 2, f'=IF({total("pending")}>0,"{se.V_PENDING}",IF({total("nodiff")}>0,"{se.V_NODIFF}",'
                      f'IF(ROUND({hi},0)<=ROUND({tol},0),IF({none},"{se.V_NONE}","{se.V_WITHIN}"),'
                      f'IF(ABS({cells["est"]})>{tol},"{se.V_EST_OVER}","{se.V_UPPER_OVER}"))))', wrap=True)
    ws.row_dimensions[row].height = 45
    row += 1
    ws.cell(row, 1, "평가(왜곡표시의 성격 · 원인, 변이 근거, 다른 분야 영향, 모집단 결론)").font = wp.font(color=wp.MUTED)
    ask(b, ws, row, 2, f"표본 결과 평가: {what}")
    ws.row_dimensions[row].height = 45
    row += 1
    for text in ("왜곡표시 금액은 장부 금액 − 증빙으로 확인한 금액이다(과대계상이 양수). 항목이 절차 대상이 아닌 것으로 밝혀지면(무효 전표 등) 대체 항목을 고른다(문단 10). "
                 "증빙이 없어 절차를 적용할 수 없으면 대체 절차 결과를 검사 결과에 적고, 대체 절차도 못 하면 항목 금액 전부를 왜곡표시로 적는다(문단 11). 투영값은 8100A 로 옮기지 않는다. 옮길 금액은 회계사가 정한다",
                 "예상 왜곡표시를 0 으로 정해 뽑았으면 간격 미만 항목에서 왜곡이 하나만 나와도 상한이 허용왜곡표시를 넘는다(설계 때 예상한 왜곡보다 큰 왜곡, 문단 A22). "
                 f"그때는 회사 조사 · 수정 요구, 표본 확대, 다른 절차 가운데 고른다(문단 A23). 계수 표는 표 오른쪽 {L(fcol)}열에 있다"):
        ws.cell(row, 1, text).font = wp.font(size=9, color=wp.MUTED)
        row += 1
    return row + 1


def evaluation(b, ws, row: int, s: dict, first: int, last: int, what: str) -> int:
    """표 하나로 뽑은 표본의 결과 수치와 평가."""
    if not _is_mus(s) or last < first:
        return row
    row, refs = eval_numbers(b, ws, row, s, first, last, f"표본 결과 수치 (감사기준서 530 문단 14): {what}")
    return eval_conclude(b, ws, row, [refs], s["tolerable"], what)


def widths(label_w: int = 30, pre: int = 0, tot: bool = False) -> list[int]:
    from . import tot as tot_mod

    return [30, label_w, 18, 18, 10, 12] + [22] * pre + (tot_mod.WIDTHS if tot else []) + [26, 10, 10, 10] + \
        ([10] if tot else []) + [14, 30, 16]


def footnote(ws, row: int, evidence: list[str]) -> int:
    ws.cell(row, 1, evidence_note(evidence)).font = wp.font(size=9, color=wp.MUTED)
    ws.cell(row + 1, 1, "검사 항목: √ 일치 · ✗ 다름 · 해당 없음 가운데 고른다. 다름이 있으면 검사 결과에 차이와 처리를 적는다(8100A 왜곡표시 후보)").font = \
        wp.font(size=9, color=wp.MUTED)
    return row + 2


# ---------------------------------------------------------------- 영역별 표본 · 전수
def _area_codes(ctx: dict, code: str) -> tuple[set, set]:
    rows = [r for r in ctx["tb"] if r["area"] == code]
    return {str(r["code"]) for r in rows}, {reader._norm(r["name"]) for r in rows}


def _key(x) -> str:
    return f"{x.date.isoformat()} {x.voucher}-{x.row or ''} {x.party or ''} {x.name}".strip()


def area_lines(ctx: dict, code: str) -> list:
    """이 영역 계정의 당기 분개 행. 계정코드가 없으면 계정명으로 잇는다."""
    from .lead import _journals

    codes, names = _area_codes(ctx, code)
    return [x for x in _journals(ctx)["cur"] if (x.code and str(x.code) in codes) or (not x.code and reader._norm(x.name) in names)]


def population(ctx: dict, code: str, side: str) -> list[tuple]:
    """표본 모집단 [(열쇠, 금액, 행)]. side dr 이면 차변 − 대변, cr 이면 대변 − 차변이 양수인 행."""
    out = []
    for x in area_lines(ctx, code):
        amt = (x.dr - x.cr) if side == "dr" else (x.cr - x.dr)
        out.append((_key(x), reader._int(amt), x))
    return out


def excluded_accounts(ctx: dict, code: str) -> list[dict]:
    """이 영역과 같은 표시과목인데 다른 영역이 맡는 시산표 계정(급여 · 퇴직급여 · 감가상각비 · 무형자산상각비 · 대손상각비처럼
    account_keywords 나 감사인 확정으로 다른 영역에 간 것). 이 영역 계정이 시산표에 없으면 line_areas 에서 이 영역의 표시과목을 찾는다."""
    lines = {r["line"] for r in ctx["tb"] if r["area"] == code}
    if not lines:
        mine = {k for k, v in (ctx["defs"].get("line_areas") or {}).items() if v == code}
        lines = {r["line"] for r in ctx["tb"] if reader._norm(r["line"]) in mine}
    return [r for r in ctx["tb"] if r["line"] in lines and r["area"] != code]


def excluded_note(ctx: dict, code: str) -> str:
    out = excluded_accounts(ctx, code)
    if not out:
        return "없음(같은 표시과목의 계정이 모두 이 영역입니다)"
    by: dict[str, list] = {}
    for r in out:
        by.setdefault(r["area"] or "대응 없음", []).append(r["name"])
    parts = [f"{' · '.join(ns)}({'4000' + a if a != '대응 없음' else a})" for a, ns in by.items()]
    return ", ".join(parts) + f". 합계 {common.won(sum(r['disp'] for r in out))}. 그 영역 조서에서 봅니다"


def _settings(ctx: dict) -> dict:
    return (ctx["defs"].get("vouch") or {})


def _match_line(evidence: list[str]):
    def f(r):
        x = r["line"]
        voucher = x.voucher.rsplit("-", 1)[0] if x.voucher.count("-") >= 2 else x.voucher
        return common.match_evidence(evidence, party=x.party, voucher=voucher, day=x.date.isoformat())
    return f


def _sample_sheet(b, ctx: dict, code: str, spec: dict) -> None:
    from .lead import risk_inputs, sampling_guide

    d = ctx["d"]
    what = spec["what"]
    pop = population(ctx, code, spec["side"])
    from . import tot as tot_mod

    kind = tot_mod.area_kind(code)                 # 감사-TOT 증빙 대조(definitions/tot.yaml areas)
    ws, row = b.sheet("표본", widths(44, tot=bool(kind)))
    ws.cell(6, 1, f"모집단: {what}. 당기 분개장에서 이 영역 계정의 행을 모았다(시산표 영역 대응 · 3650A 기준)").font = wp.font(size=9, color=wp.MUTED)
    items = [(k, a) for k, a, _ in pop]
    line_of = {k: x for k, _, x in pop}
    pm = ctx["mat"]["performance"]
    if not items or not pm:
        why = "당기 분개장에 이 영역 계정의 행이 없어" if not items else "수행중요성이 없어(2700A)"
        b.put(ws, row, 1, f"{why} 표본을 뽑지 못했습니다", flag=True, wrap=True)
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=8)
        return
    ch = sampling.chosen_for(ctx, b.no, what)
    seed = sampling.settings()["seed"] if ctx.get("seed") is None else ctx["seed"]
    from .lead import sample_risk

    s = sampling.mus(items, pm, sample_risk(ctx, code, ch), seed, ch.get("factor"), ch.get("expected", 0))     # 2302 · 2700B 를 읽지 않던 것을 고침(2026-11-02)
    for r in s["selected"]:
        r["line"] = line_of[r["key"]]
    from .lead import _sample_params

    row = _sample_params(b, ws, row, s, ctx, what,
                         extra=[("모집단에서 뺀 계정", excluded_note(ctx, code), None)] if spec.get("exclude_note") else None)
    evidence = common.evidence_files(d)
    row = b.section(ws, row, f"선정 항목 {len(s['selected'])}개 (간격 이상인 고액 항목은 반드시 걸린다)")
    row, first = table(b, ws, row, s["selected"], "일자 전표-행 거래처 계정", evidence, _match_line(evidence),
                       tot=(lambda r: tot_mod.check(ctx, kind, r["line"])) if kind else None)
    if s["selected"]:
        b.verify(f"{b.no} 표본 금액 합", f"=SUM('표본'!C{first}:C{row - 1})", sum(r["amount"] for r in s["selected"]))
    last = row - 1
    if kind:
        row = tot_mod.footnote(ws, row, ctx, kind, [r["tot"] for r in s["selected"] if r.get("tot")])
    b.verify(f"{b.no} 표본 모집단 금액", f"='표본'!B{_pop_cell_row(ws)}", s["total"])
    if s.get("excluded"):
        ws.cell(row, 1, f"금액이 0 이하라 모집단에서 뺀 행 {len(s['excluded'])}개(역분개 · 반대쪽 행). 3600-JET 에서 본다").font = \
            wp.font(size=9, color=wp.MUTED)
        row += 1
    row = footnote(ws, row, evidence)
    row = evaluation(b, ws, row + 1, s, first, last, what)
    sampling_guide(b, ws, row)


def _pop_cell_row(ws) -> int:
    for r in range(1, 40):
        if ws.cell(r, 1).value == "모집단 금액":
            return r
    return 1


def _full_sheet(b, ctx: dict, code: str, spec: dict) -> None:
    """자본 변동처럼 행이 적은 영역은 전수를 본다."""
    lines = area_lines(ctx, code)
    ws, row = b.sheet(spec.get("sheet") or "변동 전수", widths(44))
    ws.cell(6, 1, f"{spec['what']}. 행이 적어 표본 대신 전수를 본다. 의사록 · 등기부 · 주금납입증명과 대조한다").font = wp.font(size=9, color=wp.MUTED)
    if not lines:
        b.put(ws, row, 1, "당기 분개장에 이 영역 계정의 변동 행이 없습니다. 변동이 없으면 전기와 같은지 Lead 에서 확인합니다", wrap=True)
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=8)
        return
    evidence = common.evidence_files(ctx["d"])
    rows, cum = [], 0
    for x in lines:
        amt = reader._int(x.cr - x.dr)
        cum += amt
        rows.append({"key": _key(x), "amount": amt, "cum": cum, "hits": None, "line": x})
    row = b.section(ws, row, f"변동 행 {len(rows)}개 (대변 − 차변, 자본 증가가 양수)")
    row, first = table(b, ws, row, rows, "일자 전표-행 거래처 계정", evidence, _match_line(evidence), reason=lambda r: "전수")
    b.put(ws, row, 2, "순변동 합계", bold=True)
    b.put(ws, row, 3, f"=SUM(C{first}:C{row - 1})", fmt=wp.WON, bold=True)
    b.verify(f"{b.no} 변동 전수 합", f"='{ws.title}'!C{row}", sum(r["amount"] for r in rows))
    footnote(ws, row + 2, evidence)


# ---------------------------------------------------------------- 4000A 금융기관별 잔액
def bank_balances(ctx: dict) -> dict:
    """계정명세서 예금 시트 줄을 금융기관별로 묶고 잔액증명(PDF 판독) · 3320 조회 대장 상태를 붙인다."""
    from . import banks

    ctl = banks.control_rows(ctx["d"], ctx)
    by: dict[str, dict] = {}
    for x in ctl["rows"]:
        if x["type"] != "예금":
            continue
        e = by.setdefault(x["bank"], {"bank": x["bank"], "kinds": [], "schedule": 0})
        e["schedule"] += x["amount"] or 0
        common.note_read(x.get("path"))                  # 이 조서가 쓴 계정명세서(예금 시트)
        if x.get("kind"):
            e["kinds"].append(str(x["kind"]))
    conf = {e["target"]: e for e in (common.idx(ctx["d"], "조회.json", {}) or {}).get("confirmations", []) if e.get("kind") == "은행"}
    for name, e in by.items():
        c = ctl["confirmations"].get(name) or {}
        e["certificate"] = c.get("예금")
        e["cert_file"] = c.get("file")
        common.note_read(c.get("path"))                  # 이 금융기관의 잔액증명 PDF
        e["diff"] = None if e["certificate"] is None else reader._int(e["certificate"] - e["schedule"])
        cf = conf.get(name)
        e["confirm"] = f"3320 #{cf['no']} {cf.get('status') or ''}".strip() if cf else None
    tb = reader._int(sum(r["disp"] for r in ctx["tb"] if r["area"] == "A"))
    return {"rows": list(by.values()), "sources": ctl["sources"], "tb": tb}


def _bank_sheet(b, ctx: dict) -> None:
    m = bank_balances(ctx)
    ws, row = b.sheet("금융기관별 잔액", [20, 24, 18, 18, 16, 26, 22, 8])
    ws.cell(6, 1, "계정명세서 예금 시트를 금융기관별로 묶고 잔액증명(받은자료 PDF, 엔진 판독)과 3320 은행조회 상태를 붙였다. "
                  "은행조회 회신은 은행조회 회신 프로그램이 정본이다").font = wp.font(size=9, color=wp.MUTED)
    if not m["rows"]:
        b.put(ws, row, 1, "계정명세서에서 예금 시트를 찾지 못했습니다(제예금 · 보통예금 등). 받은자료 명세서 폴더를 확인해 주십시오", flag=True, wrap=True)
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=7)
        return
    row = b.section(ws, row, "금융기관별 잔액 (" + (" · ".join(m["sources"]) or "계정명세서") + ")")
    row = b.head(ws, row, ["금융기관", "예금 종류", "계정명세서", "잔액증명", "차이", "잔액증명 파일", "3320 은행조회", "틱마크"])
    first = row
    for e in m["rows"]:
        b.put(ws, row, 1, e["bank"])
        b.put(ws, row, 2, " · ".join(dict.fromkeys(e["kinds"])), wrap=True)
        b.put(ws, row, 3, e["schedule"], fmt=wp.WON)
        b.put(ws, row, 4, e["certificate"], fmt=wp.WON, flag=e["certificate"] is None)
        b.put(ws, row, 5, f'=IF(D{row}="","",D{row}-C{row})', fmt=wp.WON, flag=bool(e["diff"]))
        b.put(ws, row, 6, e["cert_file"] or "잔액증명 없음", wrap=True, flag=not e["cert_file"])
        b.put(ws, row, 7, e["confirm"] or "3320 대상 아님", wrap=True, flag=not e["confirm"])
        b.put(ws, row, 8, "C" if e["diff"] == 0 else "")
        row += 1
    b.put(ws, row, 1, "합계", bold=True)
    b.put(ws, row, 3, f"=SUM(C{first}:C{row - 1})", fmt=wp.WON, bold=True)
    b.put(ws, row, 8, "Λ")
    tot = row
    b.verify("4000A 금융기관별 계정명세서 합", f"='금융기관별 잔액'!C{tot}", sum(e["schedule"] for e in m["rows"]))
    row += 1
    b.put(ws, row, 1, "시산표 현금및현금성자산 영역")
    b.put(ws, row, 3, m["tb"], fmt=wp.WON)
    b.put(ws, row, 5, f"=C{tot}-C{row}", fmt=wp.WON)
    row += 1
    ws.cell(row, 1, "차이는 현금 시재 · 예금이 아닌 계정(정기예금이 다른 영역이면) 때문일 수 있다. 틱마크 C 는 잔액증명과 일치한 줄").font = \
        wp.font(size=9, color=wp.MUTED)


def add_sheets(b, code: str, ctx: dict) -> None:
    spec = (_settings(ctx) or {}).get(code)
    if code == "A":
        _bank_sheet(b, ctx)
    if not spec:
        return
    if spec.get("full"):
        _full_sheet(b, ctx, code, spec)
    else:
        _sample_sheet(b, ctx, code, spec)
