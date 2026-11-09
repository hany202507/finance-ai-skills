"""4000 계정별 조서(R4, 2026-10-05. 골격 재편 2026-10-12).

만들 영역은 두 가지에서 정한다: 이슈 대장의 대응 조서(4000*)와 유의적 계정(표시과목 금액이 수행중요성 초과).
4000CL 우발부채 및 약정사항은 잔액이 없어도 늘 만든다(definitions/workpapers.yaml always_areas). 이 영역의 Lead 는 금액 대신 절차 표다.
한 파일의 시트는 「표지」(한공회 4000 실증절차 Part 1 · Part 2, 이슈 대응 줄, 해당 여부) → 「Lead」(리드시트 · 계정 명세 ·
정산표 대사 · 절차 목록 · 결론) → 절차 시트(.01 <이름> …) → 「.NN 주석」 → 요약 시트 → 「받은자료」 순서다(audit.workpapers.skeleton).
4000C 매출채권은 거래처별 명세와 금액 단위 표본, 4000P 매출은 매출 분석 · 기간 분할 금액 단위 표본 · 매출 요약(audit.workpapers.sales)을 더한다.
영역별 절차 시트 둘째 묶음(Cut-off · 월별 변동 · 기말 후 출금 검토 · 충당부채 변동 · 자본변동표 · 변동내역 · 손실충당금 검토)은
audit.workpapers.substantive 가 만든다. 자료가 없어 만들지 않은 시트는 Lead 의 절차 목록 아래에 안내 한 줄이 남는다.
표지의 「AI 제안(확인 전)」 열은 `wp suggest` 로 넣은 해당 여부 제안(audit.workpapers.suggest)이고 기입란이 아니다.
「받은자료」 시트에는 이 조서를 만들면서 엔진이 읽은 받은자료(common.reading)와 색인의 연결 조서가 이 조서인 받은자료를 적는다.
설계 문서
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from openpyxl.utils import get_column_letter

from .. import figures, folder, priorwp, reader, riskplan, wp
from . import common, issuedetail, recalc, sales, sampling, skeleton, suggest
from .common import ask, won

PROC_FILE = Path(__file__).resolve().parents[2] / "tools" / "proto_data" / "kicpa_4000_part1.json"
PROC2_FILE = PROC_FILE.with_name("kicpa_4000_part2.json")      # 「추가 고려 절차」(2026-10-08)
TICKS = [("√", "장부 · 시산표와 대사함"), ("Λ", "가로 · 세로 합계 재계산함"), ("C", "조회 회신과 대사함"),
         ("V", "증빙과 대사함"), ("S", "기말 후 입금 확인함"), ("PY", "전기조서 · 전기 감사받은 재무제표와 대사함"),
         ("GL", "총계정원장 · 분개장과 대사함"), ("R", "재계산함(이자 · 감가상각 · 적수)")]


def procedures() -> dict:
    return json.loads(PROC_FILE.read_text(encoding="utf-8"))


def procedures2() -> dict:
    """한공회 4000 Part 2 「추가 고려 절차」. 조건이 맞을 때만 쓰는 묶음이다(2026-10-08 감사 전문가 회의)."""
    return json.loads(PROC2_FILE.read_text(encoding="utf-8")) if PROC2_FILE.exists() else {}


def _area_order() -> list[str]:
    std = folder.load_standard()
    for f in std["folders"]:
        if f["path"] == "4000 계정별":
            return [str(x) for x in f["workpapers"]]
    return []


def select(d: Path, ctx: dict | None = None) -> list[dict]:
    """만들 4000 영역과 생긴 이유. [{no, code, why: [..], issues: [이슈 번호]}]"""
    ctx = ctx or context(d)
    out: dict[str, dict] = {}

    def add(code: str, why: str, issue: int | None = None):
        no = f"4000{code}"
        e = out.setdefault(no, {"no": no, "code": code, "why": [], "issues": []})
        if why not in e["why"]:
            e["why"].append(why)
        if issue is not None and issue not in e["issues"]:
            e["issues"].append(issue)

    for i in ctx["issues"]:
        r = i.get("response_wp") or ""
        if folder._is_area(r) and i.get("status") != "닫힘":
            add(r[4:], f"이슈 {i['no']}", i["no"])
    pm = ctx["mat"]["performance"]
    groups: dict[tuple, list] = {}
    # 묶음(소계) 줄은 계정이 아니다. 그 금액으로 영역을 열면 잔액 · 당기 거래가 0 인 영역이 열린다
    # (2026-10-18 샘플 A: 합계잔액시산표의 「<재고자산>」 줄 대변 합계로 재고 잔액 0 인 회사에 4000E 가 열림)
    accts = [r for r in ctx["tb"] if not figures.is_group_row(r["name"])]
    for r in accts:
        if r["area"]:
            groups.setdefault((r["area"], r["line"]), []).append(r)
    for (a, line), rs in groups.items():
        v = sum(r["disp"] for r in rs)
        if pm and abs(v) > pm:
            whole = all(r["area"] == a for r in accts if r["line"] == line)
            what = line if whole else f"{line} 중 {', '.join(r['name'] for r in rs)}"
            add(a, f"유의적 계정({what} {won(v)} > 수행중요성 {won(pm)})")
    try:                                     # R9 A5: 적요에 당기 표시가 있는 기말 후 지급은 4000AA 부외부채 검토로 본다
        hinted = [x for x in recalc.unrecorded(ctx)["rows"] if x["hint"]]
    except (KeyError, ValueError, TypeError):
        hinted = []
    if hinted:
        add("AA", f"부외부채 검토 후보(기말 후 지급 중 적요에 당기 표시 {len(hinted)}건)")
    for code, why in (ctx["defs"].get("always_areas") or {}).items():       # 잔액이 없어도 감사마다 보는 영역(4000CL)
        add(str(code), str(why))
    order = _area_order()
    return sorted(out.values(), key=lambda e: (order.index(e["no"]) if e["no"] in order else len(order), e["no"]))


def context(d: Path, seed: int | None = None, risk: str | None = None) -> dict:
    defs = common.load_def("workpapers.yaml")
    return {"d": Path(d), "defs": defs, "tb": common.tb_rows(d, defs), "prior": figures.prior(d), "mat": common.materiality(d),
            "issues": (common.idx(d, "이슈.json", {"issues": []}) or {"issues": []})["issues"], "seed": seed, "risk": risk,
            "_j": None, "_adj": None, "prior_wp": priorwp.load(Path(d))}


def area_risk(ctx: dict, code: str) -> dict:
    """영역 위험(2302 감사인 값 → 없으면 분석적 검토 결과로 낸 엔진 제안). 한 번 계산해 ctx 에 둔다."""
    plans = ctx.setdefault("_plans", {})
    if code not in plans:
        plans[code] = riskplan.area_plan(ctx["d"], code, issues=ctx["issues"])
    return plans[code]


def sample_risk(ctx: dict, code: str, chosen: dict) -> str:
    """표본 위험 수준: 명령 --risk → 표본 시트에 감사인이 고른 값 → 2302 감사인 위험 → 2700B 감사인 기본값 → sampling.yaml 기본값.
    감사인이 적은 값이 앞선다(2026-10-16, 2700B sampling.default_risk 가 무시되던 것을 고침).
    2026-11-02 결정: 감사인 값이 없으면 열린 이슈 · 유의적 위험 영역은 sampling.yaml risk_area_default(높음), 그 밖은 아래 기본값이다.
    2026-10-25 결정: 감사인 값이 없으면 엔진 영역 위험 제안(대부분 높음 3.00) 대신 기본값(실무 예시, 신뢰계수 1.00)을 쓴다.
    엔진 영역 위험 제안은 표지 · 리드에 참고로 남는다(riskplan.sample_risk)."""
    from .. import params

    if ctx.get("risk") or chosen.get("risk"):
        return ctx.get("risk") or chosen.get("risk")
    plan = area_risk(ctx, code)
    if plan["source"] == riskplan.SOURCE_AUDITOR:
        return riskplan.sample_risk(plan)
    try:
        v = params.overrides(Path(ctx["d"])).get("sampling.default_risk")
    except Exception:          # 2700B 를 읽지 못하면 감사인 값 없음으로 본다
        v = None
    st = sampling.settings()
    if v:
        return v
    return st.get("risk_area_default") if st.get("risk_area_default") and (plan["significant"] or plan["issues"]) else st["default_risk"]


def _journals(ctx: dict) -> dict:
    if ctx["_j"] is None:
        ctx["_j"] = common.journals(ctx["d"])
    return ctx["_j"]


# ---------------------------------------------------------------- 표본 모집단
def ar_population(ctx: dict) -> dict:
    """매출채권 거래처별 잔액, 신규 여부, 기말 후 입금 · 취소. 4000C 와 3320 이 함께 쓴다."""
    d = ctx["d"]
    ar = common.ar_by_party(d)
    j = _journals(ctx)
    before = common.prior_parties(j)
    jet = common.load_def("jet.yaml")["accounts"]
    collect: dict[str, float] = {}
    cancel: dict[str, float] = {}
    for v in common.vouchers(j["post"]):
        for x in v.lines:
            if x.cr and x.party and _is(x.code, x.name, jet["receivable"]):
                drs = [y for y in v.lines if y.dr]
                if any(_is(y.code, y.name, jet["cash"]) for y in drs):
                    collect[x.party] = collect.get(x.party, 0) + x.cr
                elif any(_is(y.code, y.name, jet["revenue"]) for y in drs):
                    cancel[x.party] = cancel.get(x.party, 0) + x.cr
    rows = [{"party": p, "amount": a, "new": (p not in before) if before is not None else None,
             "collected": collect.get(p, 0), "cancelled": cancel.get(p, 0)} for p, a in ar["rows"]]
    tb_ar = sum(r["disp"] for r in ctx["tb"] if r["line"] == "매출채권") if any(r["line"] == "매출채권" for r in ctx["tb"]) else \
        sum(r["disp"] for r in ctx["tb"] if common.in_ranges(r["code"], jet["receivable"]["ranges"]))
    return {"rows": rows, "source": ar["source"], "excluded": ar.get("excluded", []), "new_known": before is not None, "tb": tb_ar,
            "post_files": sorted({x.file for x in j["post"]})}


def _is(code, name, group: dict) -> bool:
    if code is not None and common.in_ranges(code, group.get("ranges", [])):
        return True
    return code is None and any(k in (name or "") for k in group.get("names", []))


AR_WHAT = "매출채권 거래처별 기말 잔액"


def ar_sample(ctx: dict) -> dict | None:
    pop = ar_population(ctx)
    pm = ctx["mat"]["performance"]
    if not pop["rows"] or not pm:
        return None
    ch = sampling.chosen_for(ctx, "4000C", AR_WHAT)      # 명령 --risk 가 앞선다(예상 왜곡표시는 시트 값, 2026-11-09)
    return {"pop": pop, "s": sampling.mus([(r["party"], r["amount"]) for r in pop["rows"]], pm, sample_risk(ctx, "C", ch),
                                          ctx["seed"], ch.get("factor"), ch.get("expected", 0))}


# ---------------------------------------------------------------- 표지
SUGGEST_HEAD = "AI 제안(확인 전)"
PLAN_HEAD = "위험 기반 계획(엔진 제안)"      # 2302 위험 → 표준 절차 선택(2026-10-16, audit/riskplan.py)
COVER_HEAD = ["감사절차", "경영진 주장", "조서번호", "해당 여부", SUGGEST_HEAD, "수행 결과", "수행자", PLAN_HEAD]
COVER_WIDTHS = [64, 14, 26, 12, 36, 40, 14, 34]
PRIOR_HEAD, PRIOR_WIDTH = "전기 수행(참고)", 40          # 전기조서에 절차 목록이 있을 때만 붙는 열(2026-10-12)
# 절차의 성격 · 시기(2026-11-03, 감사기준서 330 문단 6). 표마다 끝 두 열이다. 처음 값은 엔진 제안(definitions/workpapers.yaml cover)
NATURE_HEAD, TIMING_HEAD = "성격", "시기"
NATURES = ("세부 테스트", "실증 분석적 절차", "통제 테스트", "질문 · 관찰")
TIMINGS = ("중간", "기말", "기말 후")
APPLIES = ["해당", "해당 없음"]
RED = wp.RED


def nature_timing(text: str, defs: dict, interim: bool = False) -> tuple[str, str]:
    """절차 글로 고른 (성격, 시기) 제안. 규칙은 definitions/workpapers.yaml cover 의 nature_rules · timing_rules."""
    c = defs.get("cover") or {}
    t = str(text or "").split("\n")[0]                     # 절차 제목 줄만 본다(세부 글의 「분석적 검토」 · 「후속측정」 에 걸리지 않게)
    nature = next((r["nature"] for r in c.get("nature_rules") or [] if any(w in t for w in r["words"])), c.get("nature_default", "세부 테스트"))
    timing = next((r["timing"] for r in c.get("timing_rules") or [] if any(w in t for w in r["words"])), None)
    return nature, timing or ("중간" if interim else c.get("timing_default", "기말"))


def _nt_cells(b, ws, row: int, nt: tuple, names: dict, text: str, nature: str | None = None) -> None:
    """표지 절차 줄의 성격 · 시기 기입란. nt = (첫 열, 성격 목록 검증, 시기 목록 검증, 중간감사인가, defs)."""
    col, dvn, dvt, interim, defs = nt
    nat, tim = nature_timing(text, defs, interim)
    for c, lab, val, dv in ((col, names["nature"], nature or nat, dvn), (col + 1, names["timing"], tim, dvt)):
        x = ask(b, ws, row, c, lab, rule="optional", value=val, wrap=False)
        dv.add(x.coordinate)
        b.prefill_labels.add(b.inputs[-1][2])


def _cover_head(b, ws, code: str, defs: dict) -> int:
    """한공회 4000 표지 머리(설계 3절): 1~2행 제목, 4~5행 회사명 · 작성자 · 일자와 결산일 · 검토자 · 일자, 6~9행 경영진 주장 약어."""
    ws["A1"] = "실 증 절 차"
    ws["A1"].font = wp.font(size=16, bold=True, color=wp.NAVY)
    ws["A2"] = f"({code}. {b.title})"
    ws["A2"].font = wp.font(size=12, bold=True, color=wp.NAVY)
    ws["A3"] = " · ".join(x for x in (b.no, b.standard, f"회사제시 {b.version}" if b.version else "") if x)
    ws["A3"].font = wp.font(size=9, color=wp.MUTED)
    for r, (lab, val, who) in enumerate([("회사명", b.company, "작성자"), ("결산일", b.fy_end, "검토자")], 4):
        ws.cell(r, 1, f"{lab}: {val or ''}").font = wp.font(bold=True)
        ws.cell(r, 2, who).font = wp.font(color=wp.MUTED)
        ws.cell(r, 4, "일자").font = wp.font(color=wp.MUTED)
        if who == "작성자":
            ws.cell(r, 3, b.preparer).font = wp.font()
            ws.cell(r, 5, date.today().isoformat()).font = wp.font()
        else:
            b.ask(ws, r, 3, "검토자", rule="optional")
            b.ask(ws, r, 5, "검토 일자", rule="optional")
    b.status_block(ws, 4, 7)
    b.required_mark(ws, 4, 9)          # 소규모 감사 건의 필수 영역(4000CL, 2026-10-26)
    marks = [f"{a} {t}" for a, t in (defs.get("cover") or {}).get("assertions") or []]
    ws.cell(6, 1, "경영진 주장").font = wp.font(bold=True, color=wp.NAVY)
    half = (len(marks) + 1) // 2
    for r, part in ((7, marks[:half]), (8, marks[half:])):
        ws.cell(r, 1, " · ".join(part)).font = wp.font(size=9, color=wp.MUTED)
    ws.cell(9, 1, "노란 칸은 감사인 기입란. 해당 없는 절차는 지우지 않고 「해당 여부」에 「해당 없음」, 「수행 결과」에 사유를 적습니다").font = \
        wp.font(size=9, color=wp.MUTED, italic=True)
    b.legend(ws, 10)                   # 칸의 뜻과 11행 「AI 작성 칸 n개」(2026-11-03). AI 제안 열은 연보라다
    b.summary_at = (ws.title, 11)      # 4000 은 표지에 요약을 둔다
    return 12


def _proc_row(b, ws, row: int, text: str, assertions: list[str], names: dict, dv, ref: str | None = None,
              required: bool = True, bold: bool = False, color: str | None = None, height: float | None = None,
              suggestion: dict | None = None, prior: str | None = None, plan: dict | None = None, nt: tuple | None = None,
              nature: str | None = None) -> None:
    """실증절차 한 줄. names 는 기입란 이름 {조서번호, 해당 여부, 수행 결과, 수행자}.
    suggestion 은 `wp suggest` 로 넣은 해당 여부 제안이다. 「해당 여부」 옆 칸에 글로만 적고 기입란으로 등록하지 않는다.
    prior 는 전기조서의 절차 목록에서 이 줄에 이은 절차 이름이다(여덟째 칸, 참고)."""
    b.put(ws, row, 1, text, wrap=True, bold=bold, color=color)
    b.put(ws, row, 2, ", ".join(assertions))
    ask(b, ws, row, 3, names["ref"], rule="optional", value=ref or None)
    dv.add(ask(b, ws, row, 4, names["applies"], rule="optional").coordinate)
    note = suggest.cell_text(suggestion)
    if note:                                             # AI 제안(확인 전). 해당 여부는 감사인이 노란 칸에 적는다(2026-11-03 AI 칸 표시)
        b.ai(ws, row, 5, note, what=f"해당 여부 제안: {common.short(text, 40)}", basis="_색인/절차제안.json")
    else:
        b.put(ws, row, 5, None, wrap=True, color=wp.MUTED)
    ask(b, ws, row, 6, names["result"], rule="required" if required else "optional")
    ask(b, ws, row, 7, names["who"], rule="optional")
    if plan:
        b.put(ws, row, 8, f"{plan['plan']}\n{plan['reason']}", wrap=True, color=RED if "대응" in plan["plan"] else wp.MUTED)
    if prior is not None:
        b.put(ws, row, 9, prior or None, wrap=True, color=wp.MUTED)
    if nt:
        _nt_cells(b, ws, row, nt, names, text, nature)
    if note:                                             # 제안 글이 잘리지 않게 줄 높이를 맞춘다(한글 한 글자를 열 너비 1.7 로 본다)
        lines = -(-len(note) * 1.7 // COVER_WIDTHS[4])
        height = max(height or 15, 15 * min(8, lines))
    if height:
        ws.row_dimensions[row].height = height


def step_condition(ctx: dict, step: str) -> str | None:
    """표준 절차의 전제 조건을 회사 자료로 본다(2026-10-16). 조건이 비어 있으면 None(위험으로 계획한다).
    조건이 확인되지 않으면 「판단 필요」 의 사유 글을 돌려준다. 엔진은 해당 없음을 정하지 않는다."""
    d = Path(ctx["d"])
    if "기타수익" in step:
        other = [r for r in ctx["tb"] if r.get("disp") and "수익" in str(r.get("name") or "") and "매출" not in str(r.get("line") or "")]
        if not other:
            return "시산표에 기타수익(영업외수익) 계정 금액이 없음. 확인되면 「해당 없음」 과 사유를 적는다"
    if "특수관계자" in step:
        made = {w["no"] for w in (common.idx(d, "조서목록.json", {"workpapers": []}) or {"workpapers": []})["workpapers"]
                if w.get("file") and (d / w["file"]).exists()}
        if "3500" not in made:
            return "특수관계자 목록(3500)이 아직 없음. 특수관계자와 거래 유무를 확인한 뒤 정한다"
    if "외화" in step:
        fx = [r for r in ctx["tb"] if r.get("disp") and any(k in str(r.get("name") or "") for k in ("외화", "외환", "환산"))]
        if not fx:
            return "시산표에 외화 · 외화환산 계정 금액이 없음. 외화 채권이 없으면 「해당 없음」 과 사유를 적는다"
    if "내부거래" in step:
        return "본지점 · 연결 내부거래가 있을 때만 수행"
    if "유형별" in step and "수익인식" in step:
        from . import progress

        if progress.schedule(ctx):
            return "진행률 명세가 있다. (4) 수주산업 절차는 「진행기준 매출」 시트로 수행하고 나머지 유형은 계약서로 확인한다"
        return "반품권 · 진행기준 · 본인/대리인 같은 수익 유형이 있는지 계약서로 확인한 뒤 정한다"
    return None


def _risk_summary(b, ws, row: int, rp: dict) -> int:
    """표지 「위험평가와 대응 계획」: 2302 위험(감사인 값 또는 엔진 제안)과 근거, 그 위험으로 고른 절차 · 범위(2026-10-16)."""
    row = b.section(ws, row, "위험평가와 대응 계획 (2302 → 이 조서. 감사기준서 330 문단 7)")
    items = [("평가된 위험", riskplan.text(rp)),
             ("근거(분석적 검토)", "\n".join(rp["reasons"]) or "이슈 · 패턴 없음"),
             ("대응", "아래 표준 절차의 「위험 기반 계획」 열: 위험 주장과 겹치는 절차는 「수행 · 위험 대응」, 나머지는 「수행 · 기본」 또는 「판단 필요」. "
                      + ("유의적 위험이라 위험 대응 절차에 세부테스트를 포함한다(문단 21). " if rp["significant"] else "")
                      + f"표본 신뢰계수는 표본 시트에서 정한다(영역 위험으로 고르면 {riskplan.sample_risk(rp)})")]
    if rp["source"] == riskplan.SOURCE_ENGINE:
        items.append(("확인", "2302 고유위험 · 유의적 위험 칸이 비어 엔진 제안을 썼다. 2302 에 적으면 다시 만들 때 그 값으로 계획한다"))
    for lab, val in items:
        b.put(ws, row, 1, f"{lab}: {val}", wrap=True, color=RED if lab == "평가된 위험" else None, bold=lab == "평가된 위험")
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=len(COVER_HEAD))
        ws.row_dimensions[row].height = 15 * max(1, val.count("\n") + 1 + len(val) // 150)
        row += 1
    return row + 1


def _cover(b, code: str, ctx: dict, area_issues: list[dict], related: list[dict], names: dict) -> None:
    """「표지」: 이슈 대응 절차(붉은 글자) · Part 1 절차 예시 · Part 2 추가 고려 절차 · 같은 영역의 다른 이슈.
    해당 여부는 엔진이 판정하지 않는다(묶음 에이전트가 제안하고 회계사가 확정한다). names 는 {시트 기본 이름: 번호 붙인 이름}."""
    from .vouch import _dv

    defs = ctx["defs"]
    ws, _ = b.sheet(skeleton.COVER, widths=COVER_WIDTHS, head=False)
    row = _cover_head(b, ws, code, defs)
    dv = _dv(ws, APPLIES)
    dvn, dvt = _dv(ws, list(NATURES)), _dv(ws, list(TIMINGS))
    interim = "중간" in Path(b.d).name
    nt = lambda col: (col, dvn, dvt, interim, defs)              # noqa: E731
    sug = suggest.for_wp(b.d, b.no)                      # {(part, 절차 이름): 제안}. 엔진은 해당 여부를 판정하지 않는다
    rp = area_risk(ctx, code)
    row = _risk_summary(b, ws, row, rp)
    if area_issues:
        row = b.section(ws, row, "이슈 대응 절차 (분석적 검토에서 나온 위험에 구체적으로 대응. 감사기준서 330 문단 21)")
        row = b.head(ws, row, COVER_HEAD + [NATURE_HEAD, TIMING_HEAD])
        for i in area_issues:
            todo = (defs.get("issue_steps") or {}).get(i.get("source"), "")
            detail = sales.issue_detail(ctx, i) if code == "P" else issuedetail.lines(ctx, i, names)
            key = f"이슈 {i['no']}"
            text = f"이슈 {i['no']} 대응: {i['title']}" + (f"\n{todo}" if todo else "") + "".join(f"\n· {x}" for x in detail)
            _proc_row(b, ws, row, text, i.get("assertions") or [],
                      {"ref": f"조서번호: {key}", "applies": f"해당 여부: {key}", "result": f"수행 결과: {key}", "who": f"수행자: {key}",
                       "nature": f"성격: {key}", "timing": f"시기: {key}"},
                      dv, bold=True, color=RED, height=15 * min(12, 3 + 2 * len(detail)),
                      plan={"plan": "수행 · 이슈 대응", "reason": f"이슈 {i['no']} " + ", ".join(i.get("assertions") or [])},
                      nt=nt(len(COVER_HEAD) + 1), nature="세부 테스트")
            row += 1
        row += 1
    items = (procedures().get(code) or {}).get("items", [])
    # 전기조서의 절차 목록(2026-10-12). 있으면 「전기 수행(참고)」 열을 붙이고 표지 절차 줄에 잇는다. 엔진은 해당 여부를 정하지 않는다
    shown = [it for it in items if "감사결론" not in it["step"]]
    pw = priorwp.for_area(b.d, b.no, ctx.get("prior_wp"))
    pprocs = (pw or {}).get("procedures") or []
    matched, unmatched = priorwp.match_procedures([it["step"] for it in shown], pprocs) if pprocs else ({}, [])
    head = COVER_HEAD + ([PRIOR_HEAD] if pprocs else [])
    if pprocs:
        ws.column_dimensions[get_column_letter(len(head))].width = PRIOR_WIDTH
    nt_col = len(head) + 1
    head = head + [NATURE_HEAD, TIMING_HEAD]
    for c, w in ((nt_col, 16), (nt_col + 1, 10)):
        ws.column_dimensions[get_column_letter(c)].width = w
    row = b.section(ws, row, f"Part 1. 절차 예시 (한공회 4000 {code} Part 1. 회사 상황에 맞게 고친다)")
    row = b.head(ws, row, head)
    if not items:
        b.put(ws, row, 1, f"한공회 4000 Part 1 에 {code} 영역 절차가 없습니다. 절차를 직접 적어 주십시오", wrap=True, flag=True)
        ask(b, ws, row, 6, "수행 결과: 절차")
        row += 1
    rules = defs.get("proc_refs") or []
    hit = 0
    for n, it in enumerate(shown):
        key = common.short(it["step"], 30)
        ref = proc_refs(it["step"], code, b.no, names, rules)
        hit += bool(ref)
        was = "\n".join(priorwp.procedure_text(p) for p in matched.get(n, [])) if pprocs else None
        _proc_row(b, ws, row, it["step"] + ("\n" + "\n".join(it["detail"][:2]) if it["detail"] else ""), it["assertions"],
                  {"ref": f"조서번호: {key}", "applies": f"해당 여부: {key}", "result": f"수행 결과: {key}", "who": f"수행자: {key}",
                   "nature": f"성격: {key}", "timing": f"시기: {key}"},
                  dv, ref=ref, height=15 * min(4, max(2, 1 + len(it["detail"][:2]), len(matched.get(n, [])))), suggestion=sug.get((1, key)),
                  prior=was, plan=riskplan.step_plan(rp, it["assertions"], condition=step_condition(ctx, it["step"] + " ".join(it["detail"][:1]))),
                  nt=nt(nt_col))
        row += 1
    if pprocs:
        src = sorted({Path(p["source"]["path"]).name for p in pprocs})
        ws.cell(row, 1, "전기 수행(참고)은 전기조서의 절차 목록을 절차 이름의 낱말로 이은 것입니다(확인 전). 전기에 수행했다는 판정이 아닙니다. 출처: "
                        + ", ".join(src)).font = wp.font(size=9, color=wp.MUTED)
        row += 1
        if unmatched:
            ws.cell(row, 1, "위 절차에 잇지 못한 전기 절차(전기조서의 글이고 이슈 번호는 전기 감사의 번호다): " + " · ".join(priorwp.procedure_text(p) for p in unmatched)).font = \
                wp.font(size=9, color=wp.MUTED)
            row += 1
    if items:
        ws.cell(row, 1, f"조서번호 칸의 처음 값은 엔진이 절차 글로 붙인 이 파일의 시트 이름과 다른 조서번호입니다({hit}개, "
                        "definitions/workpapers.yaml proc_refs). 엔진이 붙인 칸은 다시 만들면 엔진 값으로 돌아가고, 빈 칸에 적은 값은 남습니다").font = \
            wp.font(size=9, color=wp.MUTED)
        row += 1
        ws.cell(row, 1, "성격 · 시기 칸의 처음 값은 엔진이 절차 글로 고른 제안입니다(definitions/workpapers.yaml cover). 평가된 위험에 맞게 고쳐 주십시오. "
                        "고친 값은 다시 만들어도 남습니다(감사기준서 330 문단 6)").font = wp.font(size=9, color=wp.MUTED)
        row += 1
    row = _cover_part2(b, ws, row, code, items, dv, sug, rp, ctx, nt(len(COVER_HEAD) + 1))
    if related:
        row += 1
        row = b.section(ws, row, "같은 영역의 다른 이슈(대응 조서가 다른 곳)")
        for i in related:
            b.put(ws, row, 1, f"이슈 {i['no']}: {i['title']}", wrap=True)
            b.put(ws, row, 2, ", ".join(i.get("assertions") or []))
            b.put(ws, row, 3, f"대응 조서 {i.get('response_wp') or '없음'}")
            row += 1


def _cover_part2(b, ws, row: int, code: str, part1_items: list[dict], dv, sug: dict | None = None, rp: dict | None = None,
                 ctx: dict | None = None, nt: tuple | None = None) -> int:
    """한공회 4000 Part 2 「추가 고려 절차」(2026-10-08 감사 전문가 회의).

    원본이 조건부로 쓰라고 한 묶음이다. P 영역 4번 칸의 안내가 그 예다.
    「진행기준을 적용하여 인식하는 매출이 있는 경우 Part 2의 절차를 추가 고려」.
    그래서 엔진은 해당 여부를 판정하지 않는다. 조건 문구를 그대로 보이고 「해당 여부」를 회계사 확인 칸으로 둔다.
    칸은 모두 선택이라 비워 두어도 조서 검사를 통과한다. 기입란 이름은 Part 1 과 겹치지 않게 「추가 절차 …」 로 시작한다."""
    items = (procedures2().get(code) or {}).get("items", [])
    if not items:
        return row
    row += 1
    row = b.section(ws, row, f"Part 2. 추가 고려 절차 (한공회 4000 {code} Part 2. 조건이 맞을 때만 수행한다)")
    hints = [t for it in part1_items for t in [it["step"], *it["detail"]] if "Part 2" in t]
    for t in hints:                                      # 원본이 적어 둔 조건 문구를 그대로 보인다
        b.put(ws, row, 1, t, wrap=True, color=wp.MUTED)
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=len(COVER_HEAD))
        row += 1
    row = b.head(ws, row, COVER_HEAD + ([NATURE_HEAD, TIMING_HEAD] if nt else []))
    for it in items:
        key = common.short(it["step"], 30)
        _proc_row(b, ws, row, it["step"] + ("\n" + "\n".join(it["detail"][:2]) if it["detail"] else ""), it["assertions"],
                  {"ref": f"추가 절차 조서번호: {key}", "applies": f"추가 절차 해당 여부: {key}", "result": f"추가 절차 결과: {key}",
                   "who": f"추가 절차 수행자: {key}", "nature": f"추가 절차 성격: {key}", "timing": f"추가 절차 시기: {key}"},
                  dv, required=False, height=15 * min(4, 1 + len(it["detail"][:2])), nt=nt,
                  suggestion=(sug or {}).get((2, key)), plan=riskplan.step_plan(rp, it["assertions"], part=2, condition=step_condition(ctx, it["step"]) if ctx else None)
                  if rp else None)
        row += 1
    ws.cell(row, 1, "해당하는 절차에만 「해당」을 적고 결과를 채웁니다. 비워 두면 수행하지 않은 것으로 봅니다. "
                    "출처: 한공회 4000 계정별 실증절차 2026 Part 2 (tools/make_kicpa_procs.py 로 뽑습니다)").font = wp.font(size=9, color=wp.MUTED)
    return row + 1


# ---------------------------------------------------------------- Lead
def _ticks(b, ws, row: int) -> int:
    row = b.section(ws, row, "틱마크")
    for mark, text in TICKS:
        ws.cell(row, 1, mark).font = wp.font(bold=True, color=wp.RED)
        ws.cell(row, 2, text).font = wp.font(color=wp.MUTED)
        row += 1
    return row


def _mat_block(b, ws, row: int, ctx: dict) -> tuple[int, str]:
    m = ctx["mat"]
    row = b.section(ws, row, "수행중요성")
    ws.cell(row, 1, "수행중요성").font = wp.font(color=wp.MUTED)
    b.put(ws, row, 2, m["performance"], fmt=wp.WON, flag=m["candidate"])
    b.put(ws, row, 3, m["basis"] or "2700A 에 수행중요성이 없고 후보도 계산하지 못했습니다", wrap=True, flag=m["candidate"])
    ws.merge_cells(start_row=row, start_column=3, end_row=row, end_column=7)
    return row + 2, f"$B${row}"


def _risk_block(b, ws, row: int, rp: dict, ctx: dict, code: str) -> int:
    """Lead 「위험평가와 대응」: 2302 위험 → 이 조서에서 고른 절차 · 범위를 한 표로(2026-10-16, 감사기준서 330 문단 7)."""
    row = b.section(ws, row, "위험평가와 대응 (2302 경영진주장 수준 위험 → 이 조서의 절차 · 범위)")
    issues = [i for i in ctx["issues"] if i.get("area") == code and i.get("status") == "열림"]
    items = [("고유위험", rp["level"]), ("유의적 위험", "예" if rp["significant"] else "아니오"),
             ("위험 경영진 주장", ", ".join(rp["assertions"]) or "없음"), ("평가 출처", rp["source"]),
             ("근거", "; ".join(rp["reasons"]) or "이슈 · 패턴 없음"),
             ("관련 이슈", "; ".join(f"이슈 {i['no']} {i['title']} → {i.get('response_wp') or '대응 조서 없음'}" for i in issues) or "없음"),
             ("범위", f"영역 위험으로 고르면 표본 위험 수준 {riskplan.sample_risk(rp)}(적용 값은 표본 시트)"
                     + (" · 유의적 위험이라 세부테스트 포함(문단 21)" if rp["significant"] else "")),
             ("절차 선택", "표지 「위험 기반 계획」 열. 위험 주장과 겹치는 표준 절차를 위험 대응으로, 그 밖은 기본 또는 판단 필요로 둔다")]
    for lab, val in items:
        ws.cell(row, 1, lab).font = wp.font(color=wp.MUTED)
        b.put(ws, row, 2, val, wrap=True, flag=lab == "평가 출처" and rp["source"] == riskplan.SOURCE_ENGINE)
        ws.merge_cells(start_row=row, start_column=2, end_row=row, end_column=10)
        ws.row_dimensions[row].height = 15 * max(1, 1 + len(str(val)) // 130)
        row += 1
    return row + 1


NO_ADJ = "이 조서 계정에 들어온 수정분개 없음. 8100A 에서 처리를 '수정' 으로 정한 분개가 생기면 수정 반영(python -m audit apply) 때 들어갑니다"


def adjustments(ctx: dict) -> dict:
    """Lead 수정 열에 넣을 분개. WTB 양식 수정사항과 같은 목록이다(2026-10-16): 8100A 처리 '수정'(정본) +
    8100A 에서 아직 처리를 정하지 않은 엔진 후보 가운데 반영 여부 「예」 + WTB 에 직접 적은 줄(audit.wtbform.adjustment_rows).
    그래서 Lead 확정 = WTB 최종이다. 8100A 가 아닌 줄은 재무제표 · DART 에 들어가지 않으므로 pending 에 따로 모아
    Lead 가 8100A 에 옮기라고 묻는다. 분석 결과가 없으면 8100A 만 본다(R9 A1 과 같다).
    {"by_code": {코드: (차변, 대변)}, "lines": {코드: 줄 수}, "pending": {코드: [글]}, "wtb": WTB 상대 경로 | None, "error"}.
    조서 여럿을 한 번에 만들 때 한 번만 읽도록 ctx 에 넣어 둔다."""
    from .. import wtbform
    from ..report import misstatement

    if ctx.get("_adj") is not None:
        return ctx["_adj"]
    d = Path(ctx["d"])
    out: dict[str, tuple] = {}
    lines: dict[str, int] = {}
    pending: dict[str, list[str]] = {}
    err, rec = None, wtbform.record(d)

    def add(code, dr, cr):
        a, c = out.get(code, (0, 0))
        out[code] = (a + (dr or 0), c + (cr or 0))
        lines[code] = lines.get(code, 0) + 1

    try:
        an = d / "_색인" / "분석.json"
        if an.exists():
            res = json.loads(an.read_text(encoding="utf-8"))
            rows = wtbform.adjustment_rows(d, res, (d / rec["path"]) if rec else None)["rows"]
            for r in rows:
                if str(r.get("use") or "").strip() != "예" or not r.get("code"):
                    continue
                code = str(r["code"])
                add(code, r.get("dr"), r.get("cr"))
                if r.get("source") != wtbform.SRC_A:
                    src = "엔진 후보(8100B 수정 제안)" if r.get("source") == wtbform.SRC_B else "WTB 에 직접 적은 줄"
                    pending.setdefault(code, []).append(f"{src}" + (f" 이슈 {r['no']}" if r.get("no") not in (None, "") else ""))
        else:
            st = misstatement.read(d)
            if st["path"] is not None:
                for e in misstatement.plan(d, figures.current_tb(d), st)["adjust"]:
                    add(str(e["code"]), e["dr"], e["cr"])
    except Exception as e:  # noqa: BLE001  수정 목록을 못 읽어도 리드는 만든다
        out, lines, pending, err = {}, {}, {}, f"수정 목록(8100A · WTB)을 읽지 못함({type(e).__name__}). 수정 열은 비워 둠"
    ctx["_adj"] = {"by_code": out, "lines": lines, "pending": pending, "wtb": rec["path"] if rec else None, "error": err}
    return ctx["_adj"]


def adjust_note(adj: dict, rows: list[dict]) -> str:
    """Lead 의 수정 안내 한 줄. 이 조서 계정에 들어온 수정분개만 센다.
    수정이 없는 영역은 8100A 가 생기기 전과 뒤, 다른 영역에 수정이 생긴 뒤에도 문구가 같다.
    그래야 수정 반영 때 상관없는 조서의 내용이 바뀌지 않아 검사 통과 · 검토 끝이 남는다(2026-10-12)."""
    if adj.get("error"):
        return adj["error"]
    lines = adj.get("lines") or {c: 1 for c in adj.get("by_code") or {}}        # 줄 수가 없으면 계정 수로 센다
    n = sum(lines.get(str(r["code"]), 0) for r in rows)
    p = sum(len((adj.get("pending") or {}).get(str(r["code"]), [])) for r in rows)
    if not n:
        return NO_ADJ
    return (f"WTB 수정사항(8100A 처리 '수정' 정본) 가운데 이 조서 계정 {n}줄" +
            (f". 그중 {p}줄은 8100A 에 아직 없어 재무제표 · DART 에 들어가지 않는다(아래 「WTB 대사」 확인 칸)" if p else ""))


def _purpose_block(b, ws, row: int, code: str) -> int:
    """감사목적 기입란. 엔진은 한공회 절차표의 경영진주장만 옮긴다(R9 A1)."""
    asr = []
    for it in (procedures().get(code) or {}).get("items", []):
        for a in it.get("assertions", []):
            if a not in asr:
                asr.append(a)
    row = b.section(ws, row, "감사목적")
    if asr:
        ws.cell(row, 1, "한공회 4000 Part 1 이 영역 절차의 경영진주장: " + ", ".join(asr)).font = wp.font(size=9, color=wp.MUTED)
        row += 1
    ask(b, ws, row, 1, "감사목적", rule="required")
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=10)
    ws.row_dimensions[row].height = 30
    return row + 2


def _result_block(b, ws, row: int) -> int:
    row = b.section(ws, row, "감사절차 및 결과 (표지의 절차를 수행한 결과 요약. 절차 시트의 차이 · 예외를 적는다)")
    ask(b, ws, row, 1, "감사절차 및 결과", rule="required")
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=10)
    ws.row_dimensions[row].height = 45
    return row + 2


def notes_for(code: str, lines: list[str]) -> list[tuple[int, str]]:
    """이 영역과 이어진 8400 주석 (번호, 제목). 주석 정의(report_fs.yaml notes)의 순서가 주석 초안 번호다(R9 A1)."""
    from ..report.base import defs as rdefs

    keyed = recalc.defs().get("lead_notes", {})
    have = {reader._norm(x) for x in lines}
    out = []
    for n, spec in enumerate(rdefs()["notes"], 1):
        units = {reader._norm(u) for u in spec.get("units", [])}
        if (units & have) or code in keyed.get(spec["key"], []):
            out.append((n, spec["title"]))
    return out


def _notes_block(b, ws, row: int, code: str, lines: list[str]) -> int:
    ns = notes_for(code, lines)
    row = b.section(ws, row, "주석 공시사항")
    if ns:
        ws.cell(row, 1, "이어진 8400 주석(주석 초안 번호): " + " · ".join(f"주석 {n}. {t}" for n, t in ns)).font = wp.font(size=9, color=wp.NAVY)
        row += 1
        ask(b, ws, row, 1, "주석 공시사항 검토", rule="required")
    else:
        ws.cell(row, 1, "이 영역과 이어진 8400 주석이 없습니다. 공시할 사항이 있으면 적어 주십시오").font = wp.font(size=9, color=wp.MUTED)
        row += 1
        ask(b, ws, row, 1, "주석 공시사항 검토", rule="optional")
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=10)
    ws.row_dimensions[row].height = 30
    return row + 2


def _proc_list(b, ws, row: int, plan: dict, pending: list[str] | None = None) -> int:
    """절차 목록 「절차 · 시트」: 이 파일의 절차 시트를 번호 붙인 이름으로 차례로 적는다(설계 4절 5번).
    pending 은 자료가 없어 만들지 않은 절차 시트의 안내 글이다(substantive.add_sheets). 목록 아래에 한 줄씩 적는다."""
    row = b.section(ws, row, "절차 목록 (이 파일의 절차 시트. 실증절차 전체와 해당 여부는 표지에 있다)")
    for col, last, text in ((1, 7, "절차"), (8, 9, "시트")):
        b.head(ws, row, [text] * (last - col + 1), col=col)
        ws.merge_cells(start_row=row, start_column=col, end_row=row, end_column=last)
    row += 1
    for base, name, text in plan["procedures"]:
        b.put(ws, row, 1, text or base, wrap=True)
        b.put(ws, row, 8, name)
        for col, last in ((1, 7), (8, 9)):
            for c in range(col, last + 1):
                ws.cell(row, c).border = wp.BOX
            ws.merge_cells(start_row=row, start_column=col, end_row=row, end_column=last)
        row += 1
    for t in pending or []:
        ws.cell(row, 1, "만들지 않은 절차 시트 " + t).font = wp.font(size=9, color=RED)
        row += 1
    rest = plan["summaries"] + [skeleton.RECEIVED]
    ws.cell(row, 1, "번호 없는 시트: " + " · ".join(rest) + ". 원자료 대신 넣은 집계와 이 조서가 쓴 받은자료 목록이다").font = \
        wp.font(size=9, color=wp.MUTED)
    return row + 2


def _prior_block(b, ws, row: int, ctx: dict) -> int:
    """「전기 조서 내용(참고)」: 전기조서에서 읽은 글(계정의 주요 성격 · 메모 · 절차 · 발견사항 · 결론 · 수정사항)과 출처(2026-10-12).
    기입란이 아니다. Lead 맨 아래에 두어 위쪽 칸의 행 번호를 건드리지 않는다. 숫자는 대사하지 않은 전기조서의 글 그대로다."""
    pw = priorwp.for_area(b.d, b.no, ctx.get("prior_wp"))
    if not pw:
        return row
    cfg = priorwp.defs()
    names, keep = cfg["kind_names"], cfg["scan"]["lead_lines"]

    def line(text: str, **k) -> None:
        nonlocal row
        b.put(ws, row, 1, text, wrap=True, **k)
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=10)
        ws.row_dimensions[row].height = 15 * min(6, max(1, -(-len(text) * 17 // 1900)))
        row += 1

    row = b.section(ws, row + 1, "전기 조서 내용 (참고. 기입란이 아니다. 전기조서의 글을 그대로 옮긴 것이고 숫자는 대사하지 않았다)")
    for kind in cfg["lead_order"]:
        for blk in pw["blocks"]:
            if blk["kind"] != kind or not blk["lines"] or (blk.get("role") != "lead" and kind not in ("findings", "conclusion")):
                continue
            line(f"{names[kind]} · {priorwp.source_text(blk)}", bold=True, color=wp.NAVY)
            for t in blk["lines"][:keep]:
                line(t)
            more = len(blk["lines"]) - keep + blk.get("truncated", 0)
            if more > 0:
                line(f"이하 {more}줄은 전기조서 원본에 있습니다", color=wp.MUTED)
    if pw["procedures"]:
        line("전기 절차 목록 · " + priorwp.source_text(pw["procedures"][0]), bold=True, color=wp.NAVY)
        for p in pw["procedures"]:
            line(priorwp.procedure_text(p))
    if pw["adjustments"]:
        line("전기 수정사항(전기조서의 분개 줄) · " + priorwp.source_text(pw["adjustments"][0]), bold=True, color=wp.NAVY)
        for e in pw["adjustments"]:
            line(f"차변 {e['dr']} {e['dr_amount']:,} / 대변 {e['cr']} {e['cr_amount']:,}" + (f" · {e['note']}" if e.get("note") else ""))
    others = [f"{blk['title']}({blk['source']['sheet']})" for blk in pw["blocks"] if blk["kind"] == "section" and blk["lines"]]
    if others:
        line("기타 블록(전기조서 원본 참고): " + " · ".join(others[:12]) + (f" 외 {len(others) - 12}개" if len(others) > 12 else ""),
             color=wp.MUTED)
    return row


def _lead_steps_sheet(b, code: str, ctx: dict, why: list[str] | None, plan: dict, pending: list[str], steps: list[dict]) -> dict:
    """금액 리드시트가 없는 영역(4000CL)의 「Lead」: 「번호 · 감사절차 · 수행 결과 · 참조 · 발견사항 여부」 표 · 수행중요성 · 절차 목록 ·
    감사목적 · 감사절차 및 결과 · 주석 공시사항 · 결론. 줄은 definitions/workpapers.yaml 의 lead_steps 다. 수행 결과와 발견사항 여부는 기입란이다."""
    ref = wp.sheet_ref(skeleton.LEAD)
    ws, row = b.sheet(skeleton.LEAD, widths=[8, 40, 44, 26, 16, 10, 10, 10, 10, 10])
    if why:
        ws.cell(6, 1, "생긴 이유: " + " · ".join(why)).font = wp.font(size=9, color=wp.MUTED)
    row = b.section(ws, row, "감사절차와 수행 결과 (이 영역은 계정 금액이 없어 리드시트 대신 절차 표를 둔다)")
    row = b.head(ws, row, ["번호", "감사절차", "수행 결과", "참조", "발견사항 여부"])
    first = row
    for n, st in enumerate(steps, 1):
        refs = [str(st["wp"])] if st.get("wp") else []
        if st.get("sheet"):
            refs.append(plan["names"].get(st["sheet"]) or "만들지 않음(자료 없음)")
        b.put(ws, row, 1, n)
        b.put(ws, row, 2, st["step"], wrap=True)
        ask(b, ws, row, 3, f"절차 결과: {st['step']}", rule="required")
        b.put(ws, row, 4, " · ".join(refs), wrap=True)
        ask(b, ws, row, 5, f"발견사항 여부: {st['step']}", rule="yesno")
        ws.row_dimensions[row].height = 30
        row += 1
    b.verify(f"{b.no} Lead 절차 줄 수", f'=COUNTIF({ref}A{first}:A{row - 1},">0")', len(steps))
    ws.cell(row, 1, "발견사항 여부는 예 · 아니오 · 해당 없음 가운데 하나로 적습니다. 예이면 수행 결과에 내용을 적고 결론에 반영해 주십시오").font = \
        wp.font(size=9, color=wp.MUTED)
    row += 2
    row, _ = _mat_block(b, ws, row, ctx)
    row = _proc_list(b, ws, row, plan, pending)
    row = _purpose_block(b, ws, row, code)
    row = _result_block(b, ws, row)
    row = _notes_block(b, ws, row, code, [])
    row = b.conclusion(ws, row, 10)
    _prior_block(b, ws, row, ctx)
    return {}


def _lead_sheet(b, no: str, code: str, ctx: dict, rows: list[dict], lines: list[str], why: list[str] | None, plan: dict,
                pending: list[str] | None = None) -> dict:
    """「Lead」: 리드시트 · 계정 명세 · 정산표 대사 · 수행중요성 · 절차 목록 · 감사목적 · 감사절차 및 결과 · 주석 공시사항 · 틱마크 · 결론.
    금액은 시산표에서 넣고 수정 열은 8100A 를 따른다. {표시과목: 리드시트 행} 을 돌려준다(주석 시트 수식이 쓴다)."""
    d = b.d
    ref = wp.sheet_ref(skeleton.LEAD)
    ws, row = b.sheet(skeleton.LEAD, widths=[22, 18, 16, 16, 18, 18, 18, 10, 26, 34, 8])
    pm = ctx["mat"]["performance"]
    if why:
        ws.cell(6, 1, "생긴 이유: " + " · ".join(why)).font = wp.font(size=9, color=wp.MUTED)
    sched = common.schedule_balances(d)
    adj = adjustments(ctx)

    # R9 A1: 회사제시 · 수정 차변 · 대변 · 확정(Audited) · 전기 확정 · 증감 · 증감률(샘플 진단 6.2 리드 열)
    row = b.section(ws, row, "리드시트 (표시 금액: 부채 · 자본 · 수익은 양수로 보인다. 수정은 8100A 처리 '수정' 분개)")
    row = b.head(ws, row, ["표시과목", "당기(회사제시)", "수정 차변", "수정 대변", "당기(확정)", "전기(확정)", "증감", "증감률",
                           "전기 출처", "증감 사유", "틱마크"])
    l0 = row
    assert l0 == skeleton.LEAD_FIRST          # 절차 시트의 Lead 참조 수식(skeleton.lead_rows)이 이 행을 가리킨다
    det_sec = l0 + len(lines) + 2
    det_first = det_sec + 2
    det_last = det_first + max(len(rows), 1) - 1

    def rng(c):
        return f"${c}${det_first}:${c}${det_last}"

    def net_adj(r):
        dr, cr = adj["by_code"].get(str(r["code"]), (0, 0))
        return r["sign"] * (dr - cr)

    lead_rows = {}
    for line in lines:
        cur = sum(r["disp"] for r in rows if r["line"] == line)
        fin = cur + sum(net_adj(r) for r in rows if r["line"] == line)
        pv, src = common.prior_for(line, ctx["prior"], ctx["defs"])
        lead_rows[line] = row
        b.put(ws, row, 1, line, bold=True)
        for col, dc in ((2, "D"), (3, "E"), (4, "F"), (5, "G")):
            b.put(ws, row, col, f'=SUMIF({rng("C")},A{row},{rng(dc)})', fmt=wp.WON)
        if pv is not None:
            b.put(ws, row, 6, pv, fmt=wp.WON)
        else:
            ask(b, ws, row, 6, f"전기 금액: {line}", rule="optional", fmt=wp.WON)
        b.put(ws, row, 7, f'=IF(F{row}="","",E{row}-F{row})', fmt=wp.WON)
        b.put(ws, row, 8, f'=IF(F{row}="","",IF(F{row}=0,"",G{row}/ABS(F{row})))', fmt=wp.PCT)
        b.put(ws, row, 9, src, wrap=True, flag=pv is None)
        big = pv is not None and pm and abs(fin - pv) > pm
        ask(b, ws, row, 10, f"증감 사유: {line}", rule="required" if big else "optional")
        b.put(ws, row, 11, "√ PY" if pv is not None else "√")          # 시산표 대사(검산) · 전기 재무제표 대사
        b.verify(f"Lead {line} 당기 = 시산표 표시과목 합", f"={ref}B{row}", cur)
        b.verify(f"Lead {line} 확정 = 회사제시 + WTB 수정사항", f"={ref}E{row}", fin)
        row += 1
    if not lines:
        b.put(ws, row, 1, f"시산표에 {code} 영역으로 대응한 계정이 없습니다. 3650A 계정 매핑을 확인해 주십시오", flag=True, wrap=True)
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=10)
    ws.cell(l0 + max(len(lines), 1), 1, "수정: " + adjust_note(adj, rows)).font = wp.font(size=9, color=wp.MUTED)
    row = det_sec
    row = b.section(ws, row, "계정 명세 (시산표" + (f" · 계정명세서 {sched['source']}" if sched["source"] else " · 계정명세서 없음") + ")")
    row = b.head(ws, row, ["계정코드", "계정명", "표시과목", "당기(회사제시)", "수정 차변", "수정 대변", "당기(확정)", "계정명세서", "차이",
                           "영역 근거", "틱마크"])
    assert row == det_first
    for r in rows:
        dr, cr = adj["by_code"].get(str(r["code"]), (0, 0))
        b.put(ws, row, 1, r["code"])
        b.put(ws, row, 2, r["name"])
        b.put(ws, row, 3, r["line"])
        b.put(ws, row, 4, r["disp"], fmt=wp.WON)
        b.put(ws, row, 5, dr or None, fmt=wp.WON)
        b.put(ws, row, 6, cr or None, fmt=wp.WON)
        b.put(ws, row, 7, f'=D{row}+({r["sign"]})*(IF(E{row}="",0,E{row})-IF(F{row}="",0,F{row}))', fmt=wp.WON)
        sv = sched["balances"].get(str(r["code"]))
        if sv is not None:
            b.put(ws, row, 8, r["sign"] * sv, fmt=wp.WON)
            b.put(ws, row, 9, f'=IF(H{row}="","",D{row}-H{row})', fmt=wp.WON, flag=r["sign"] * sv != r["disp"])
        else:
            b.put(ws, row, 8, None)
            b.put(ws, row, 9, None)
        b.put(ws, row, 10, r["area_basis"], wrap=True)
        b.put(ws, row, 11, "√" if sv is not None and r["sign"] * sv == r["disp"] else "")     # 계정명세서와 일치
        row += 1
    if rows:
        b.verify(f"{no} 계정 명세 합 = 시산표 영역 합", f"=SUM({ref}D{det_first}:D{det_first + len(rows) - 1})", sum(r["disp"] for r in rows))
    ws.cell(row, 1, "당기는 계정 명세의 표시과목별 합(SUMIF). 확정 = 회사제시 + 표시 부호 × (수정 차변 − 수정 대변). "
                    "계정명세서와 차이가 있으면 붉게 보인다. 틱마크 √ = 시산표 · 계정명세서와 대사, PY = 전기 재무제표와 대사(엔진)").font = wp.font(size=9, color=wp.MUTED)
    row += 2
    row = _wtb_form_block(b, ws, row, rows, lines, l0, adj)
    row, _ = _mat_block(b, ws, row, ctx)
    row = _risk_block(b, ws, row, area_risk(ctx, code), ctx, code)
    row = _proc_list(b, ws, row, plan, pending)
    row = _purpose_block(b, ws, row, code)
    row = _result_block(b, ws, row)
    row = _notes_block(b, ws, row, code, lines)
    row = _ticks(b, ws, row)
    row = b.conclusion(ws, row, 10)
    _prior_block(b, ws, row, ctx)
    assert lead_rows == skeleton.lead_rows(lines)
    return lead_rows


def make(d: Path, no: str, ctx: dict, why: list[str] | None = None, force: bool = False) -> dict:
    """4000 영역 조서 한 파일. 시트 순서는 표지 → Lead → 절차 시트 → 주석 → 요약 시트 → 받은자료(설계 2절).
    절차 · 요약 시트를 먼저 만들어 번호 붙인 이름을 정하고(skeleton.plan), 표지의 조서번호와 Lead 의 절차 목록에 그 이름을 적는다.
    이름 바꾸기와 순서는 다 만든 뒤 skeleton.finish 가 한 번에 한다."""
    from . import substantive, vouch

    code = no[4:]
    std = folder.load_standard()
    title = (std.get("workpaper_names") or {}).get(no) or (procedures().get(code) or {}).get("title") or no
    issues = ctx["issues"]
    area_issues = [i for i in issues if i.get("response_wp") == no and i.get("status") != "닫힘"]
    related = [i for i in issues if i.get("area") == code and i.get("response_wp") != no and i.get("status") != "닫힘"]
    std_txt = "감사기준서 500 · 한공회 4000 " + code + (" · 이슈 " + ", ".join(str(i["no"]) for i in area_issues) if area_issues else "")
    b = wp.Book(d, no, title=title, standard=std_txt)
    b.state_sheet = skeleton.COVER            # 조서 상태 칸은 절차 시트가 아니라 표지에 둔다(2026-10-26)
    rows = [r for r in ctx["tb"] if r["area"] == code]
    lines = []
    for r in rows:
        if r["line"] not in lines:
            lines.append(r["line"])

    # 이 조서를 만들면서 엔진이 숫자를 가져온 받은자료를 모아 「받은자료」 시트에 「엔진이 읽음」 으로 적는다.
    # 시산표 · 전기 재무제표 · 분개장은 ctx 가 한 번 읽어 여러 조서가 함께 쓰므로 여기와 common.Journals 가 적는다
    with common.reading() as read:
        common.note_read(*{r.get("path") for r in ctx["tb"]})          # Lead 금액 · 영역 대응은 회사제시 시산표에서 온다
        if lines and ctx["prior"]:
            common.note_read(ctx["prior"].get("path"))                 # Lead 전기(확정). 받은자료가 아닌 원천이면 시트에 싣지 않는다
        if code == "C":
            _sheet_ar(b, ctx)
        if code == "P":
            sales.add_sheets(b, ctx)          # 매출 요약 · 매출 분석 · 기간 분할 표본(R9 B4)
        recalc.add_sheets(b, code, ctx)          # R9 묶음 A 절차 시트
        # 절차 시트 둘째 묶음(2026-10-12): P Cut-off · R 월별 변동 · CL 기말 후 출금 검토 · FF 충당부채 변동 · GG 자본변동표 ·
        # G · H 변동내역 · C 손실충당금 검토. 자료가 없어 만들지 않은 시트는 Lead 절차 목록 아래에 안내를 남긴다
        area = {"code": code, "rows": rows, "lines": lines, "lead_rows": skeleton.lead_rows(lines)}
        pending = substantive.add_sheets(b, code, ctx, area)
        vouch.add_sheets(b, code, ctx)           # 4000A 금융기관별 잔액 · CC · EE · Q · R 표본 · GG 변동 전수(2026-10-09)
        plan = skeleton.plan(b, code, ctx["defs"])

        _cover(b, code, ctx, area_issues, related, plan["names"])
        steps = (ctx["defs"].get("lead_steps") or {}).get(code)
        if steps and not rows:                   # 금액 리드시트가 없는 영역(4000CL)
            lead_rows = _lead_steps_sheet(b, code, ctx, why, plan, pending, steps)
            ns = notes_for(code, [])
            skeleton.notes_sheet(b, [], {}, None, empty=(
                "이 영역은 계정 금액이 없어 금액 대사 줄이 없습니다. 회사가 제시한 주석(소송 · 담보와 보증 · 약정)을 조회 회신, 약정서, 의사록과 대조하고 "
                "결과를 아래 결론에 적어 주십시오" + (". 이어진 8400 주석: " + " · ".join(f"주석 {n}. {t}" for n, t in ns) if ns else "")))
        else:
            lead_rows = _lead_sheet(b, no, code, ctx, rows, lines, why, plan, pending)
            skeleton.notes_sheet(b, lines, lead_rows, lambda line: notes_for(code, [line]))
        skeleton.received_sheet(b, d, no, read)
    skeleton.finish(b, code, ctx["defs"])
    return common.save(b, force=force)


def wtb_by_code(d: Path) -> dict | None:
    """8100B 정산표의 계정별 회사제시 금액과 반영된 수정(수정 제안 「반영 여부」 가 「예」). {코드: (회사제시, 최종)}.
    금액은 시산표 부호(차변 +). 8100B 가 없으면 None."""
    from openpyxl import load_workbook

    path = wp.path_for(d, "8100B")
    if not path.exists():
        return None
    wb = load_workbook(path, data_only=False)
    try:
        if "계정별" not in wb.sheetnames:
            return None
        acc, hi = wb["계정별"], None
        for r in range(1, 20):
            if acc.cell(r, 1).value == "코드":
                hi = r
                break
        if hi is None:
            return None
        base = {}
        for r in range(hi + 1, acc.max_row + 1):
            code, v = acc.cell(r, 1).value, acc.cell(r, 7).value
            if code not in (None, "") and isinstance(v, (int, float)):
                base[str(code)] = v
        adj: dict[str, float] = {}
        if "수정 제안" in wb.sheetnames:
            ws = wb["수정 제안"]
            for r in range(1, ws.max_row + 1):
                code, dr, cr, ok = ws.cell(r, 2).value, ws.cell(r, 5).value, ws.cell(r, 6).value, ws.cell(r, 7).value
                if code not in (None, "") and str(ok or "").strip() == "예":
                    adj[str(code)] = adj.get(str(code), 0) + (dr or 0) - (cr or 0)
        return {c: (v, v + adj.get(c, 0)) for c, v in base.items()}
    finally:
        wb.close()


def _wtb_form_block(b, ws, row: int, rows: list[dict], lines: list[str], l0: int, adj: dict) -> int:
    """Lead ↔ WTB(회계사 양식) 대사(2026-10-16). WTB 가 먼저 만들어지고 Lead 는 WTB 수정사항과 같은 목록을 쓴다.
    그래서 Lead 확정은 WTB 최종과 같다. 여기서 보는 것은 둘이다.
    (1) WTB 파일이 지금 수정 목록(8100A · 8100B 반영 여부)과 같은 판인가. 다르면 수정 반영(apply)이 필요하다
    (2) 8100A 에 아직 없는 수정 줄(엔진 후보 · WTB 직접 기입). 재무제표 · DART 와 달라지므로 확인 칸을 필수로 둔다"""
    from .. import apply as apply_mod
    from .. import wtbform

    d = b.d
    rec = wtbform.record(d)
    row = b.section(ws, row, "WTB 대사 (WTB 확정 → 이 Lead. Lead 확정 = WTB 최종)")
    if rec is None:
        ws.cell(row, 1, "WTB 양식이 없습니다. python -m audit wtbform <폴더> 로 WTB 를 먼저 만들고 이 조서를 다시 만들어 주십시오").font = \
            wp.font(size=9, color=RED)
        ask(b, ws, row + 1, 2, "WTB 없음 확인", rule="required")
        ws.cell(row + 1, 1, "WTB 없음 확인").font = wp.font(color=wp.MUTED)
        return row + 3
    sig = apply_mod.signature(d)
    stale = rec.get("adjust", []) != sig["adjust"] or rec.get("wtb", []) != sig["wtb"]
    ws.cell(row, 1, f"WTB: {rec['path']} (만든 시각 {rec.get('at', '')})").font = wp.font(size=9, color=wp.MUTED)
    row += 1
    row = b.head(ws, row, ["표시과목", "Lead 확정", "WTB 최종", "차이", "8100A 에 없는 수정", "", "", "", "", "", "틱마크"])
    for i, line in enumerate(lines):
        rs = [r for r in rows if r["line"] == line]
        fin = 0
        for r in rs:
            dr, cr = adj["by_code"].get(str(r["code"]), (0, 0))
            fin += r["disp"] + r["sign"] * (dr - cr)
        pend = [f"{r['code']} {t}" for r in rs for t in (adj.get("pending") or {}).get(str(r["code"]), [])]
        lr = l0 + i
        b.put(ws, row, 1, line)
        b.put(ws, row, 2, f"=E{lr}", fmt=wp.WON)
        b.put(ws, row, 3, reader._int(fin), fmt=wp.WON)
        b.put(ws, row, 4, f"=B{row}-C{row}", fmt=wp.WON)
        b.put(ws, row, 5, "; ".join(pend) or None, wrap=True, flag=bool(pend))
        b.put(ws, row, 11, "WTB" if not pend and not stale else "")
        b.verify(f"Lead {line} 확정 = WTB 최종", f"={wp.sheet_ref(skeleton.LEAD)}B{row}", reader._int(fin))
        row += 1
        if pend:
            ws.cell(row, 1, "8100A 옮김 확인").font = wp.font(color=wp.MUTED)
            ask(b, ws, row, 2, f"8100A 옮김 확인: {line}", rule="required")
            ws.cell(row, 3, "8100A 에 이슈와 수정분개로 옮기고 수정 반영(python -m audit apply)을 돌리면 이 칸이 사라진다. "
                            "옮기지 않을 거면 까닭을 적는다").font = wp.font(size=9, color=wp.MUTED)
            row += 1
    if stale:
        ws.cell(row, 1, "WTB 파일이 지금 8100A 수정분개 · 8100B 반영 여부와 다른 판입니다. python -m audit apply 로 WTB 와 이 조서를 함께 다시 "
                        "만들어 주십시오").font = wp.font(size=9, color=RED)
        ask(b, ws, row + 1, 2, "WTB 판 다름 확인", rule="required")
        ws.cell(row + 1, 1, "WTB 판 다름 확인").font = wp.font(color=wp.MUTED)
        row += 2
    ws.cell(row, 1, "틱마크 WTB = WTB 최종과 대사함(같은 수정 목록 · 같은 판, 8100A 에 모두 있음)").font = wp.font(size=9, color=wp.MUTED)
    return row + 2


def _wtb_block(b, ws, row: int, rows: list[dict], lines: list[str], l0: int) -> int:
    """Lead ↔ 8100B 정산표 대사(2026-10-09). Lead 는 시산표에서 바로 숫자를 가져오므로 같은 회사제시 금액이어야 한다.
    확정 금액은 Lead 가 WTB 수정 목록을, 8100B 가 수정 제안 「반영 예」 만 보므로 8100A 수정이 있으면 차이가 난다."""
    w = wtb_by_code(b.d)
    row = b.section(ws, row, "정산표(8100B) 대사")
    if w is None:
        ws.cell(row, 1, "8100B 정산표가 아직 없습니다. 분석적 검토(python -m audit analyze)를 돌리면 생기고, 이 조서를 다시 만들면 대사합니다").font = \
            wp.font(size=9, color=wp.MUTED)
        return row + 2
    row = b.head(ws, row, ["표시과목", "Lead 당기", "8100B 회사제시", "차이", "Lead 확정", "8100B 최종", "차이", "", "", "", "틱마크"])
    for i, line in enumerate(lines):
        rs = [r for r in rows if r["line"] == line]
        comp = sum(r["sign"] * w[str(r["code"])][0] for r in rs if str(r["code"]) in w)
        fin = sum(r["sign"] * w[str(r["code"])][1] for r in rs if str(r["code"]) in w)
        missing = [str(r["code"]) for r in rs if str(r["code"]) not in w]
        lr = l0 + i
        b.put(ws, row, 1, line)
        b.put(ws, row, 2, f"=B{lr}", fmt=wp.WON)
        b.put(ws, row, 3, reader._int(comp), fmt=wp.WON)
        b.put(ws, row, 4, f"=B{row}-C{row}", fmt=wp.WON)
        b.put(ws, row, 5, f"=E{lr}", fmt=wp.WON)
        b.put(ws, row, 6, reader._int(fin), fmt=wp.WON)
        b.put(ws, row, 7, f"=E{row}-F{row}", fmt=wp.WON)
        if missing:
            b.put(ws, row, 9, "8100B 에 없는 계정: " + ", ".join(missing), wrap=True, flag=True)
        b.put(ws, row, 11, "√" if not missing else "")
        b.verify(f"Lead {line} 당기 = 8100B 회사제시", f"={wp.sheet_ref(skeleton.LEAD)}C{row}", reader._int(sum(r["disp"] for r in rs)))
        row += 1
    ws.cell(row, 1, "8100B 「계정별」 시트 회사제시와 「수정 제안」 반영 예. 확정 차이는 8100A 수정과 8100B 반영이 다를 때 난다").font = \
        wp.font(size=9, color=wp.MUTED)
    return row + 2


def proc_refs(step: str, code: str, no: str, sheets, rules: list[dict]) -> str:
    """절차 글로 정한 참조. 같은 조서 안 시트는 만들어진 것만 적는다. 「4000C .01 거래처별 · 3320」 꼴.
    sheets 는 {규칙의 시트 기본 이름: 이 파일의 실제 이름(번호 붙은 이름)} 이다. 목록을 주면 이름 그대로 쓴다."""
    names = sheets if isinstance(sheets, dict) else {s: s for s in sheets}
    out = []
    for r in rules:
        if r.get("area") and r["area"] != code:
            continue
        if not any(k in step for k in r.get("keys", [])):
            continue
        if r.get("sheet"):
            if r["sheet"] in names:
                out.append(f"{no} {names[r['sheet']]}")
        elif r.get("wp") and r["wp"] != no:
            out.append(str(r["wp"]))
    return " · ".join(dict.fromkeys(out))


def _sample_params(b, ws, row: int, s: dict, ctx: dict, what: str, extra: list[tuple] | None = None) -> int:
    """extra 는 모집단 줄 바로 아래에 덧붙이는 [(이름, 값, 서식)] 이다(4000R 의 모집단에서 뺀 계정)."""
    m = ctx["mat"]
    row = b.section(ws, row, f"표본 크기 계산 근거 ({s['method']})")
    for lab, val, fmt in [("모집단", what, None), *(extra or []), ("모집단 금액", s["total"], wp.WON), ("모집단 항목 수", s["count"], "#,##0"),
                          ("허용왜곡표시(수행중요성)", s["tolerable"], wp.WON), ("수행중요성 근거", m["basis"], None),
                          ("적용 위험 수준", s["risk"], None), ("신뢰수준", s["confidence"], wp.PCT), ("신뢰계수", s["factor"], "0.00"),
                          ("예상 왜곡표시", s.get("expected", 0), wp.WON), ("확장계수", s.get("ef") or None, "0.00"),
                          ("표본 간격 = (허용왜곡표시 − 예상 왜곡표시 × 확장계수) ÷ 신뢰계수", s["interval"], wp.WON),
                          ("계획 표본 수 = 올림(모집단 금액 ÷ 표본 간격)", s["size"], "#,##0"),
                          ("시드", s["seed"], "0"), ("시작점", s["start"], wp.WON)]:
        ws.cell(row, 1, lab).font = wp.font(color=wp.MUTED)
        b.put(ws, row, 2, val, fmt=fmt, wrap=fmt is None, flag=(lab == "수행중요성 근거" and m["candidate"]))
        row += 1
    row = sample_count_note(b, ws, row, s)
    row = risk_inputs(b, ws, row, what)
    ws.cell(row, 1, "출처: definitions/sampling.yaml (신뢰계수 = −ln(1 − 신뢰수준), 확장계수는 잘못된 수용 위험별 표, 감사-표본sampling 방법론 docs/표본-방법론.md)").font = \
        wp.font(size=9, color=wp.MUTED)
    return row + 2


def sample_count_note(b, ws, row: int, s: dict) -> int:
    """계획 표본 수 · 실제로 찍힌 점 수 · 고른 항목 수가 왜 다른지(2026-10-09)."""
    pts = sum(r["hits"] for r in s["selected"])
    for lab, val in (("실제로 찍힌 점 수", pts), ("고른 항목 수", len(s["selected"]))):
        ws.cell(row, 1, lab).font = wp.font(color=wp.MUTED)
        b.put(ws, row, 2, val, fmt="#,##0")
        row += 1
    why = []
    if pts < s["size"]:
        why.append(f"점은 시작점({won(s['start'])})부터 간격마다 찍혀 모집단 끝을 넘으면 멈춘다. 그래서 계획 표본 수(올림 값)보다 "
                   f"{s['size'] - pts}개 적을 수 있다")
    if len(s["selected"]) < pts:
        many = [r for r in s["selected"] if r["hits"] > 1]
        why.append(f"간격보다 큰 항목은 점을 여러 개 받는다({len(many)}개 항목이 {sum(r['hits'] for r in many)}점). 그래서 고른 항목 수가 점 수보다 적다")
    if why:
        ws.cell(row, 1, ". ".join(why)).font = wp.font(size=9, color=wp.MUTED)
        row += 1
    return row


def sampling_guide(b, ws, row: int) -> int:
    """표본 수를 고르는 방법을 조서에 글로 적는다(2026-10-08 감사 전문가 회의).

    감사기준에 기법 · 개수 지침이 없어 판단을 모른다는 지적을 받아 넣었다. 문장은 definitions/sampling.yaml 의
    guide 이고 감사반 방법론에 맞게 고칠 수 있다. 비면 블록을 넣지 않는다. 엔진은 이 글로 표본을 바꾸지 않는다."""
    lines = sampling.settings().get("guide") or []
    if not lines:
        return row
    row = b.section(ws, row, "샘플링 가이드 (표본 수를 고르는 방법)")
    for i, line in enumerate(lines, 1):
        ws.cell(row, 1, str(i)).font = wp.font(color=wp.MUTED)
        b.put(ws, row, 2, line, wrap=True)
        row += 1
    ws.cell(row, 1, "출처: definitions/sampling.yaml 의 guide. 감사반 방법론에 맞게 고칠 수 있습니다. "
                    "표본은 위 계산 근거로 뽑고, 이 글은 감사인이 수를 정할 때 보는 참고입니다").font = wp.font(size=9, color=wp.MUTED)
    return row + 2


def risk_inputs(b, ws, row: int, what: str, cmd: str | None = None) -> int:
    """위험 수준(드롭다운) · 신뢰계수 직접 입력 칸(2026-10-07). 비우면 sampling.yaml 기본값. 적으면 wp make 를 다시 돌릴 때 그 값으로 뽑는다.
    cmd 를 주면(단독 표본 조서, 2026-11-09) 다시 뽑는 명령과 빈 칸일 때 설명을 그 조서에 맞춘다."""
    from openpyxl.worksheet.datavalidation import DataValidation

    st = sampling.settings()
    ws.cell(row, 1, "위험 수준(감사인 판단)").font = wp.font(color=wp.MUTED)
    cell = ask(b, ws, row, 2, f"위험 수준 확인: {what}", rule="optional")
    dv = DataValidation(type="list", formula1='"' + ",".join(st["risk_levels"]) + '"', allow_blank=True)
    ws.add_data_validation(dv)
    dv.add(cell.coordinate)
    lv = " · ".join(f"{k} {v['confidence']:.0%} → {v['factor']:.2f}" for k, v in st["risk_levels"].items())
    empty = (f"비우면 {st['default_risk']}" if cmd else
             f"비우면 2302 · 2700B 값, 그것도 없으면 열린 이슈 · 유의적 위험 영역은 {st.get('risk_area_default') or st['default_risk']}, 그 밖은 {st['default_risk']}")
    ws.cell(row, 3, f"고르면 신뢰계수가 바뀐다({lv}). {empty}"
                    + ("(표본 간격 = 수행중요성, 실무 예시)" if st["default_risk"] == "기본" else "")
            ).font = wp.font(size=9, color=wp.MUTED)
    row += 1
    ws.cell(row, 1, "신뢰계수 직접 입력").font = wp.font(color=wp.MUTED)
    ask(b, ws, row, 2, f"신뢰계수 직접 입력: {what}", rule="optional", fmt="0.00")
    again = cmd or f"python -m audit wp make <폴더> {b.no}"
    ws.cell(row, 3, f"감사반 방법론 표의 계수를 쓰려면 적는다(위험 수준보다 앞선다). 바꾼 뒤 `{again}` 를 다시 돌리면 그 값으로 다시 뽑는다"
            ).font = wp.font(size=9, color=wp.MUTED)
    row += 1
    ws.cell(row, 1, "예상 왜곡표시 직접 입력").font = wp.font(color=wp.MUTED)
    ask(b, ws, row, 2, f"예상 왜곡표시 직접 입력: {what}", rule="optional", fmt=wp.WON)
    ws.cell(row, 3, "전기 왜곡 · 통제 결함으로 왜곡을 예상하면 적는다. 간격 = (허용왜곡표시 − 예상 × 확장계수) ÷ 신뢰계수라 표본이 늘고, "
                    "왜곡이 몇 건 나와도 상한이 허용왜곡표시 이내일 수 있다. 비우면 0").font = wp.font(size=9, color=wp.MUTED)
    return row + 1


from .vouch import evidence_cell, evidence_note  # noqa: E402,F401  (sales.py 가 여기서 가져다 쓴다)


def confirm_status(d: Path) -> dict | None:
    """3320 조회 대장(_색인/조회.json)의 매출채권 거래처별 상태. {거래처: "3320 #4 회신 일치"}. 3320 을 아직 만들지 않았으면 None."""
    data = common.idx(d, "조회.json")
    if data is None:
        return None
    out = {}
    for e in data.get("confirmations", []):
        if e.get("kind") == "매출채권":
            out[e["target"]] = f"3320 #{e['no']} {e.get('status') or ''}".strip()
    return out


def _sample_list(b, ws, row: int, s: dict, label: str, pop_ref: str | None = None, confirm: dict | None = None,
                 evidence: list[str] | None = None) -> int:
    """선정 항목 표(vouch.table). confirm 을 주면(4000C) 3320 조회 상태 열을 붙인다. 받은 증빙은 거래처 이름으로 잇는다."""
    from . import vouch

    evidence = evidence or []
    row = b.section(ws, row, f"선정 항목 {len(s['selected'])}개 (간격 이상인 고액 항목은 반드시 걸린다)")
    pre = []
    if confirm is not None:
        def conf(r):
            st = confirm.get(r["key"]) if confirm else None
            if st is None:
                return ("3320 대상 아님" if confirm else "3320 만들기 전"), True
            return ("C " + st if st.endswith("회신 일치") else st), "차이" in st
        pre = [("조회(3320)", conf)]
    row, first = vouch.table(b, ws, row, s["selected"], label, evidence,
                             lambda r: common.match_evidence(evidence, party=str(r["key"])), pre=pre)
    if s["selected"]:
        b.verify(f"{b.no} 표본 금액 합", f"=SUM('{ws.title}'!C{first}:C{row - 1})", sum(r["amount"] for r in s["selected"]))
    if s.get("excluded"):
        ws.cell(row, 1, f"금액이 0 이하라 모집단에서 뺀 항목 {len(s['excluded'])}개: " + ", ".join(str(k) for k, _ in s["excluded"][:10])).font = wp.font(size=9, color=wp.RED)
        row += 1
    if confirm is not None:
        ws.cell(row, 1, "조회(3320): 3320 조회 대장의 번호와 상태(_색인/조회.json, 3320 을 만든 때 기준). 회신 일치는 틱마크 C. "
                        "회신이 오면 3320 을 다시 만든 뒤 이 조서를 다시 만듭니다").font = wp.font(size=9, color=wp.MUTED)
        row += 1
    row = vouch.footnote(ws, row, evidence)
    return vouch.evaluation(b, ws, row + 1, s, first, first + len(s["selected"]) - 1, s.get("what") or label)


def _sheet_ar(b, ctx: dict) -> None:
    pop = ar_population(ctx)
    ws, row = b.sheet("거래처별", widths=[18, 18, 12, 18, 18, 14, 30, 14])
    if not pop["rows"]:
        b.put(ws, row, 1, "연령분석표 · 계정명세서(외상매출금)에서 거래처별 잔액을 찾지 못했습니다. 받은자료 명세서 폴더에 넣어 주십시오", flag=True, wrap=True)
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=7)
        return
    row = b.section(ws, row, f"거래처별 기말 잔액 ({pop['source']})")
    row = b.head(ws, row, ["거래처", "기말 잔액", "신규", "기말 후 입금", "기말 후 취소", "조회 대상", "비고", "틱마크"])
    conf = confirm_status(ctx["d"]) or {}
    first = row
    sm = ar_sample(ctx)
    picked = {r["key"] for r in sm["s"]["selected"]} if sm else set()
    # 줄이 많으면 금액 상위와 「기타 (n곳)」 한 줄로 줄인다. 표본 · 신규 · 기말 후 취소 거래처는 남긴다(설계 7절)
    top = skeleton.top_n(ctx["defs"])
    shown, rest = skeleton.top_rows(pop["rows"], top, lambda r: r["amount"],
                                    keep=lambda r: r["party"] in picked or bool(r["new"]) or bool(r["cancelled"]))
    for r in shown:
        b.put(ws, row, 1, r["party"], flag=bool(r["new"]))
        b.put(ws, row, 2, r["amount"], fmt=wp.WON)
        b.put(ws, row, 3, "신규" if r["new"] else ("" if r["new"] is not None else "판정 못 함"), flag=bool(r["new"]))
        b.put(ws, row, 4, r["collected"], fmt=wp.WON)
        b.put(ws, row, 5, r["cancelled"], fmt=wp.WON, flag=bool(r["cancelled"]))
        b.put(ws, row, 6, "표본" if r["party"] in picked else "")
        b.put(ws, row, 7, "기말 후 같은 거래처 매출 취소" if r["cancelled"] else "")
        ticks = (["S"] if r["collected"] and r["collected"] >= r["amount"] else []) + \
                (["C"] if str(conf.get(r["party"]) or "").endswith("회신 일치") else [])
        b.put(ws, row, 8, " ".join(ticks))
        row += 1
    if rest:
        b.put(ws, row, 1, skeleton.others_label(rest))
        b.put(ws, row, 2, sum(r["amount"] for r in rest), fmt=wp.WON)
        b.put(ws, row, 3, "")
        b.put(ws, row, 4, sum(r["collected"] for r in rest), fmt=wp.WON)
        b.put(ws, row, 5, sum(r["cancelled"] for r in rest), fmt=wp.WON)
        b.put(ws, row, 6, "")
        b.put(ws, row, 7, "금액 상위가 아닌 거래처 합계", color=wp.MUTED)
        b.put(ws, row, 8, "")
        row += 1
    last = row - 1
    b.put(ws, row, 1, "합계", bold=True)
    for col in (2, 4, 5):
        L = get_column_letter(col)
        b.put(ws, row, col, f"=SUM({L}{first}:{L}{last})", fmt=wp.WON, bold=True)
    tot = row
    row += 1
    b.put(ws, row, 1, "시산표 매출채권")
    b.put(ws, row, 2, pop["tb"], fmt=wp.WON)
    row += 1
    b.put(ws, row, 1, "차이")
    b.put(ws, row, 2, f"=B{tot}-B{row - 1}", fmt=wp.WON, flag=sum(r["amount"] for r in pop["rows"]) != pop["tb"])
    b.verify("4000C 거래처별 합계", f"='거래처별'!B{tot}", sum(r["amount"] for r in pop["rows"]))
    b.verify("4000C 거래처별 합계 − 시산표 매출채권", f"='거래처별'!B{row}", sum(r["amount"] for r in pop["rows"]) - pop["tb"])
    row += 1
    note = "신규: 전기 분개장에 없던 거래처." if pop["new_known"] else "전기 분개장이 없어 신규 거래처를 판정하지 못했습니다."
    ws.cell(row, 1, note + " 기말 후 입금 · 취소: " + (", ".join(pop["post_files"]) or "기말 후 분개장 없음")
            + ". 틱마크 S = 기말 후 입금이 잔액 이상, C = 3320 회신 일치(엔진이 대사한 것만)").font = wp.font(size=9, color=wp.MUTED)
    if rest:
        row += 1
        ws.cell(row, 1, "거래처 " + skeleton.top_note(len(pop["rows"]), len(shown), len(rest), top, "표본 · 신규 · 기말 후 취소 거래처",
                                                   pop["source"])).font = wp.font(size=9, color=wp.MUTED)
    row += 2
    if sm:
        from .vouch import widths as vw

        ws2, r2 = b.sheet("표본", widths=vw(22, pre=1))
        r2 = _sample_params(b, ws2, r2, sm["s"], ctx, AR_WHAT)
        r2 = _sample_list(b, ws2, r2, sm["s"], "거래처", confirm=confirm_status(ctx["d"]) or {},
                          evidence=common.evidence_files(ctx["d"]))
        sampling_guide(b, ws2, r2 + 1)          # 표본 수를 고르는 방법(2026-10-08 감사 전문가 회의)
