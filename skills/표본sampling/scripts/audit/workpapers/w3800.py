"""3800 초도감사기초잔액(감사기준서 510, R7 2026-10-06).

초도감사일 때만 만든다(폴더 표준 conditional). 엔진은 사실과 숫자만 채우고 판단은 기입란이다.

  전기 감사 여부와 근거    전기 감사보고서 · DART · 작년 감사 폴더로 엔진이 판단(audit.prior). 모르면 회계사 기입란
                           감사받지 않았으면 맨 위에 감사기준서 710 문단 14 안내(기타사항에 대응수치가 감사받지 않았다고 적음)
  전임감사인 조서 열람     받은 전기조서 목록과 열람 여부(예 · 아니오 · 해당 없음) 기입란(510 문단 6(c)(i))
  기초잔액 대사표          표시과목마다 당기 기초(당기 시산표 − 당기 분개장) ↔ 전기 재무제표(전기 감사보고서 · DART · 받은 재무제표)
                           ↔ 전임 8100B(또는 작년 8800 · 회사제시 전기 시산표) 계정 합과 차이(510 문단 6(a)). 계정별 시트도 둔다
  회계정책 일관성          510 문단 6(b) · 8 점검 문항(예 · 아니오 · 해당 없음)
  대체절차                 전기조서가 없거나 전기 미감사면 필수(510 문단 6(c)(ii)(iii))
  결론                     510 문단 10~12
"""
from __future__ import annotations

from pathlib import Path

from .. import prior, wp
from . import common
from .common import ask

NO = "3800"
SHEET, ACC_SHEET = "3800", "계정별 기초잔액"
RED = wp.RED


def _effective_audited(ps: dict, old: dict) -> tuple[bool | None, str]:
    """(전기 감사 여부, 근거). 엔진이 정하지 못했으면 회계사 기입값(예 · 아니오)을 쓴다."""
    if ps.get("prior_audited") is not None:
        return ps["prior_audited"], ps.get("audited_basis") or "엔진"
    v = str(old.get((SHEET, "전기 재무제표 감사 여부")) or "").strip()
    if v in ("예", "아니오"):
        return v == "예", "회계사 기입"
    return None, "판단 근거 없음"


def make(d: Path, ctx: dict | None = None, force: bool = False) -> dict:
    from ..analysis.data import Data
    from ..analysis.engine import Engine, disp

    d = Path(d)
    case = common.case(d)
    if case.get("engagement_kind") != "초도감사":
        raise ValueError("3800 초도감사기초잔액은 초도감사일 때만 만듭니다(감사건 감사 구분이 계속감사입니다)")
    ps = prior.info(d)
    old = common.old_inputs(d, NO)
    audited, basis = _effective_audited(ps, old)
    situation = ps.get("situation")
    no_wp = situation == prior.SITUATIONS[2]
    alt_required = no_wp or audited is False

    D = Data(d)
    E = Engine(D)
    lines = [x for x in E.compare_lines() if x["stmt"] == "BS"]

    b = wp.Book(d, NO, standard="감사기준서 510 초도감사-기초잔액 · 710 문단 13 · 14 · 한공회 서식 3800")
    ws, row = b.sheet(SHEET, [34, 20, 20, 18, 20, 18, 30])
    if audited is False:
        ws.cell(6, 1, "전기 재무제표가 감사받지 않았습니다. 감사보고서 기타사항에 대응수치가 감사받지 않은 것이라고 적습니다(감사기준서 710 문단 14). "
                      "그래도 기초잔액에 대한 충분하고 적합한 감사증거를 입수해야 합니다(510 문단 6)").font = wp.font(size=10, bold=True, color=RED)
    elif audited is None:
        ws.cell(6, 1, "전기 재무제표 감사 여부를 엔진이 정하지 못했습니다(전기 감사보고서 · DART · 작년 감사 폴더 없음). 아래 칸에 적어 주십시오. "
                      "감사받지 않았으면 기타사항에 대응수치가 감사받지 않은 것이라고 적습니다(감사기준서 710 문단 14)").font = wp.font(size=10, bold=True, color=RED)
    else:
        ws.cell(6, 1, f"전기 재무제표는 감사받았습니다({basis}). 감사보고서 기타사항에 전기 감사인 · 의견을 적습니다(감사기준서 710 문단 13)"
                ).font = wp.font(size=9, color=wp.MUTED)

    # 1. 전기 감사 여부
    op = ps.get("opinion") or {}
    row = b.section(ws, row, "1. 전기 감사 여부와 근거 (엔진)")
    row = b.head(ws, row, ["항목", "내용", "근거", "", "", "", ""])
    facts = [("전기 자료 상황", situation, prior.label(ps)),
             ("전기 재무제표 감사 여부", {True: "예", False: "아니오", None: "판독 필요"}[audited], basis),
             ("전기 감사인", op.get("auditor") or "판독 필요", op.get("source") or ""),
             ("전기 감사의견", op.get("kind") or "판독 필요", op.get("source") or ""),
             ("전기 감사보고서일", op.get("report_date") or "판독 필요", op.get("source") or "")]
    for k, v, src in facts:
        b.put(ws, row, 1, k)
        b.put(ws, row, 2, v, flag=v == "판독 필요", wrap=True)
        b.put(ws, row, 3, src, wrap=True, color=wp.MUTED)
        ws.merge_cells(start_row=row, start_column=3, end_row=row, end_column=7)
        row += 1
    if ps.get("prior_audited") is None:
        b.put(ws, row, 1, "전기 재무제표 감사 여부(회계사)", bold=True)
        ask(b, ws, row, 2, "전기 재무제표 감사 여부", rule="yesno", value=old.get((SHEET, "전기 재무제표 감사 여부")))
        row += 1
    if op.get("kind") and op["kind"] != "적정":
        ws.cell(row, 1, f"전기 감사의견이 {op['kind']}입니다. 변형을 초래한 사항이 당기 중요왜곡표시위험에 미치는 영향을 평가해 주십시오(510 문단 9 · 13)"
                ).font = wp.font(size=9, color=RED)
        row += 1
    row += 1

    # 2. 전임감사인 조서 열람
    row = b.section(ws, row, "2. 전임감사인 조서 열람 (510 문단 6(c)(i))")
    got = ps.get("workpapers") or []
    b.put(ws, row, 1, "받은 전기조서")
    b.put(ws, row, 2, "\n".join(got) if got else "없음", wrap=True, flag=not got)
    ws.merge_cells(start_row=row, start_column=2, end_row=row, end_column=7)
    ws.row_dimensions[row].height = 15 * max(1, len(got))
    row += 1
    b.put(ws, row, 1, "전임감사인 조서 열람(예 · 아니오 · 해당 없음)")
    ask(b, ws, row, 2, "전임감사인 조서 열람", rule="yesno", value=old.get((SHEET, "전임감사인 조서 열람")))
    row += 1
    b.put(ws, row, 1, "열람 범위와 결과")
    ask(b, ws, row, 2, "전임감사인 조서 열람 범위와 결과", rule="optional", value=old.get((SHEET, "전임감사인 조서 열람 범위와 결과")))
    ws.merge_cells(start_row=row, start_column=2, end_row=row, end_column=7)
    row += 2

    # 3. 기초잔액 대사표(표시과목)
    pf_src = (D.sources or {}).get("prior_fs")
    src_basis = next((s["basis"] for s in D.prior_info["sources"]), None)
    row = b.section(ws, row, "3. 기초잔액 대사 (510 문단 6(a), 표시 금액)")
    ws.cell(row, 1, f"당기 기초 = 당기 시산표 − 당기 분개장. 전기 재무제표: {pf_src or '없음'}. 계정 단위 원천: {src_basis or '없음'}").font = wp.font(size=9, color=wp.MUTED)
    row += 1
    row = b.head(ws, row, ["표시과목", "당기 기초(장부)", "전기 재무제표", "차이(장부 − 재무제표)", f"{src_basis or '전기 원천'} 계정 합",
                           "차이(장부 − 원천)", "비고"])
    first = row
    for ln in lines:
        accs = [D.acct[c] for c in ln["codes"]]
        src_sum = None
        if src_basis:
            vals = [next((s["amount"] for s in a.get("prior_sources") or [] if s["basis"] == src_basis), None) for a in accs]
            src_sum = None if not accs or any(v is None for v in vals) else sum(disp(a, v) for a, v in zip(accs, vals))
        book = ln["prior_derived"]
        b.put(ws, row, 1, ln["label"], wrap=True)
        b.put(ws, row, 2, book, fmt=wp.WON)
        b.put(ws, row, 3, ln["prior_fs"], fmt=wp.WON)
        b.put(ws, row, 4, f'=IF(OR(B{row}="",C{row}=""),"",B{row}-C{row})', fmt=wp.WON)
        b.put(ws, row, 5, src_sum, fmt=wp.WON)
        b.put(ws, row, 6, f'=IF(OR(B{row}="",E{row}=""),"",B{row}-E{row})', fmt=wp.WON)
        d1 = None if book is None or ln["prior_fs"] is None else book - ln["prior_fs"]
        d2 = None if book is None or src_sum is None else book - src_sum
        if d1 is not None:
            b.verify(f"기초잔액 {ln['label']} 장부 − 전기 재무제표", f"='{SHEET}'!D{row}", d1)
        if d2 is not None:
            b.verify(f"기초잔액 {ln['label']} 장부 − 전기 원천", f"='{SHEET}'!F{row}", d2)
        if (d1 or 0) or (d2 or 0):
            b.put(ws, row, 7, "차이 있음", flag=True)
        row += 1
    if not lines:
        b.put(ws, row, 1, "당기 시산표가 없어 대사하지 못했습니다", color=wp.MUTED)
        row += 1
    elif not D.has["gl_cur"]:
        ws.cell(row, 1, "당기 분개장이 없어 당기 기초(장부)를 계산하지 못했습니다").font = wp.font(size=9, color=RED)
        row += 1
    row += 1

    # 4. 회계정책 일관성
    fw = ((common.idx(d, "시작자료.json", {}) or {}).get("company") or {}).get("framework")
    row = b.section(ws, row, "4. 회계정책 일관성 (510 문단 6(b) · 8)")
    b.put(ws, row, 1, "전기 회계기준(엔진 판독)")
    b.put(ws, row, 2, fw or "판독 필요", flag=not fw)
    row += 1
    for lab, text in (("기초잔액 회계정책 적합", "기초잔액에 적합한 회계정책이 반영되어 있는지(510 문단 6(b))"),
                      ("회계정책 일관 적용", "기초잔액에 반영된 회계정책이 당기에 일관되게 적용되는지, 변경이 있으면 재무보고체계에 따라 "
                                       "처리 · 표시 · 공시되었는지(510 문단 8)")):
        b.put(ws, row, 1, text, wrap=True)
        ask(b, ws, row, 2, lab, rule="yesno", value=old.get((SHEET, lab)))
        ws.row_dimensions[row].height = 45
        row += 1
    b.put(ws, row, 1, "회계정책 점검 근거")
    ask(b, ws, row, 2, "회계정책 점검 근거", rule="optional", value=old.get((SHEET, "회계정책 점검 근거")))
    ws.merge_cells(start_row=row, start_column=2, end_row=row, end_column=7)
    row += 2

    # 5. 대체절차
    row = b.section(ws, row, "5. 기초잔액 대체절차 (510 문단 6(c)(ii)(iii))")
    why = ("전기조서가 없습니다" if no_wp else "전기 재무제표가 감사받지 않았습니다") if alt_required else "전임감사인 조서 열람으로 증거를 얻었으면 비워 둘 수 있습니다"
    ws.cell(row, 1, f"{why}. 당기 감사절차가 기초잔액 증거가 되는지, 기초잔액에 대한 특정 절차(기말 후 회수 · 지급, 실사 · 조회 등)를 적어 주십시오"
            ).font = wp.font(size=9, color=RED if alt_required else wp.MUTED)
    row += 1
    b.put(ws, row, 1, "대체절차와 결과", bold=True)
    ask(b, ws, row, 2, "기초잔액 대체절차", rule="required" if alt_required else "optional", value=old.get((SHEET, "기초잔액 대체절차")))
    ws.merge_cells(start_row=row, start_column=2, end_row=row, end_column=7)
    ws.row_dimensions[row].height = 60
    row += 1
    b.conclusion(ws, row, 7, "기초잔액 결론(510 문단 10~12)")

    # 계정별
    wa, r = b.sheet(ACC_SHEET, [10, 22, 20, 30, 20, 18])
    wa.cell(6, 1, "시산표 부호(차변 +). 당기 기초 = 당기 시산표 − 당기 분개장. 원천마다 값과 장부와의 차이").font = wp.font(size=9, color=wp.MUTED)
    r = b.head(wa, r, ["코드", "계정명", "당기 기초(장부)", "다른 원천", "원천 값", "차이(장부 − 원천)"])
    for a in D.tb:
        if a["section"] not in ("자산", "부채", "자본"):
            continue
        others = [s for s in a.get("prior_sources") or [] if s["basis"] not in (prior.BASIS["book_bs"],)]
        b.put(wa, r, 1, a["code"])
        b.put(wa, r, 2, a["name"])
        b.put(wa, r, 3, a.get("prior_book"), fmt=wp.WON)
        if others:
            s = others[0]
            b.put(wa, r, 4, s["basis"] + (" (계정 없음)" if s.get("absent") else ""), wrap=True)
            b.put(wa, r, 5, s["amount"], fmt=wp.WON)
            diff = None if a.get("prior_book") is None else a["prior_book"] - s["amount"]
            b.put(wa, r, 6, f'=IF(OR(C{r}="",E{r}=""),"",C{r}-E{r})', fmt=wp.WON)
            if diff is not None:
                b.verify(f"계정 {a['code']} 장부 − 원천", f"='{ACC_SHEET}'!F{r}", diff)
        else:
            b.put(wa, r, 4, "없음", color=wp.MUTED)
        r += 1
    out = common.save(b, force=force)
    out.update(audited=audited, alt_required=alt_required, lines=len(lines))
    return out
