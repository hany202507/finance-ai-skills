"""R4 실행 단계 조서(2026-10-05): 4000 계정별 조서(표지 · Lead · 절차 시트) · 3600-JET · 표본 · 3320 외부조회 · 3650A 감사전재무제표확인
· 3800 초도감사기초잔액(R7, 초도감사일 때만).

  make(d, nos=None, seed=None, risk=None, force=False)  조서를 만든다. nos 를 주지 않으면 이 단계 몫 전부
  check(d, nos=None)                                    색인을 맞춘 뒤 wp.check(+ 엔진 재계산)로 검사하고 조서목록 상태를 바꾼다
  plan(d)                                               이 단계에서 만들 조서와 생긴 이유

숫자는 figures · reader 에서 엔진이 읽는다. 판단 칸(결론 · 검사 결과 · 확인)은 비워 둔다.
"""
from __future__ import annotations

from pathlib import Path

from .. import folder, params, wp
from . import common, confirm, fsrec, jet, lead, w3800, xlcalc

FIXED = ("3650A", "3600-JET", "3320", "3800")


@params.engaged
def plan(d: Path, ctx: dict | None = None) -> list[dict]:
    ctx = ctx or lead.context(d)
    areas = lead.select(d, ctx)
    out = [{"no": "3650A", "why": ["필수"]}]
    # 3320 을 4000 보다 먼저 만든다. 4000C 표본 시트가 3320 조회 대장(_색인/조회.json)의 번호 · 상태를 가져다 쓴다(2026-10-09)
    out += [{"no": "3320", "why": ["필수(감사기준서 505)"]}]
    out += [{"no": a["no"], "why": a["why"]} for a in areas]
    out += [{"no": "3600-JET", "why": ["필수(감사기준서 240)"]}]
    if common.case(d).get("engagement_kind") == "초도감사":
        out.append({"no": "3800", "why": ["초도감사(감사기준서 510)"]})
    return out


@params.engaged
def make(d: Path, nos: list[str] | None = None, seed: int | None = None, risk: str | None = None, force: bool = False,
         now: str | None = None) -> dict:
    d = Path(d)
    folder.scan(d, now=now, quiet_log=True)
    ctx = lead.context(d, seed=seed, risk=risk)
    todo = plan(d, ctx)
    whys = {x["no"]: x["why"] for x in todo}
    if nos:
        bad = [n for n in nos if n not in FIXED and not folder._is_area(n)]
        if bad:
            raise ValueError("이 단계 조서가 아닙니다: " + ", ".join(bad) + " (3650A · 3600-JET · 3320 · 3800 · 4000<영역>)")
        todo = [{"no": n, "why": whys.get(n, ["회계사 지정"])} for n in nos]
    made, kept, errors = [], [], []
    wtb = None
    if any(folder._is_area(x["no"]) for x in todo):      # WTB 확정 → 4000 Lead 순서(2026-10-16). 없으면 먼저 만든다
        from .. import wtbform

        wtb = wtbform.ensure(d)
    for x in todo:
        no = x["no"]
        try:
            if no == "3650A":
                r = fsrec.make(d, ctx, force=force)
            elif no == "3600-JET":
                r = jet.make(d, ctx, force=force)
            elif no == "3320":
                r = confirm.make(d, ctx, force=force)
            elif no == "3800":
                r = w3800.make(d, ctx, force=force)
            else:
                r = lead.make(d, no, ctx, why=x["why"], force=force)
            r["why"] = x["why"]
            made.append(r)
        except common.Kept as e:
            kept.append({"no": no, "message": str(e)})
        except (ValueError, KeyError) as e:
            errors.append({"no": no, "message": str(e)})
    rep = folder.scan(d, now=now, quiet_log=True)
    _set_why(d, {r["no"]: r["why"] for r in made})
    c = common.case(d)
    at = now or folder._now()
    what = f"실행 단계 조서 {len(made)}개를 만들었습니다: " + ", ".join(r["no"] for r in made)
    if kept:
        what += f". 기입값을 지키려고 만들지 않은 조서 {', '.join(k['no'] for k in kept)}"
    c.setdefault("log", []).insert(0, {"at": at, "who": "조서", "what": what,
                                      "wrote": [Path(r["path"]).relative_to(d).as_posix() for r in made]})
    common.put_idx(d, "감사건.json", c)
    folder.validate_index(d)
    return {"made": made, "kept": kept, "errors": errors, "scan": rep, "mat": ctx["mat"], "wtb": wtb}


def _set_why(d: Path, whys: dict) -> None:
    data = common.idx(d, "조서목록.json")
    changed = False
    for w in data["workpapers"]:
        if w["no"] in whys and (not w.get("why") or w["why"] in ("", "필수")) and folder._is_area(w["no"]):
            w["why"] = " · ".join(whys[w["no"]])
            changed = True
    if changed:
        common.put_idx(d, "조서목록.json", data)


@params.engaged
def check(d: Path, nos: list[str] | None = None, now: str | None = None) -> list[dict]:
    """조서마다 {no, file, status, problems, skipped}. wp.Book 으로 만든 xlsx 만 검사한다."""
    from openpyxl import load_workbook

    d = Path(d)
    folder.scan(d, now=now, quiet_log=True)
    wps = common.idx(d, "조서목록.json")["workpapers"]
    by = {w["no"]: w for w in wps}
    targets = nos or [w["no"] for w in wps if w.get("file")]
    out = []
    for no in targets:
        w = by.get(no)
        if w is None:
            out.append({"no": no, "file": None, "status": None, "problems": [], "skipped": "조서목록에 없음"})
            continue
        f = w.get("file")
        if not f:
            out.append({"no": no, "file": None, "status": w["status"], "problems": [], "skipped": "파일 없음"})
            continue
        p = d / f
        if p.suffix.lower() in (".docx", ".html"):
            # 워드 · HTML 초안은 남은 기입란 표시로 검사한다(2026-10-05 통합)
            problems = wp.check_doc(p)
            if not problems and w["status"] == "검토 끝":
                out.append({"no": no, "file": f, "status": "검토 끝", "problems": [], "skipped": "검토 끝 유지"})
                continue
            out.append({"no": no, "file": f, "status": wp.mark_checked(d, no, problems), "problems": problems, "skipped": None})
            continue
        if p.suffix.lower() != ".xlsx":
            out.append({"no": no, "file": f, "status": w["status"], "problems": [], "skipped": "엑셀 · 워드 조서가 아님"})
            continue
        wb = load_workbook(p, read_only=True)
        made_by_engine = wp.META_SHEET in wb.sheetnames
        wb.close()
        if not made_by_engine:
            out.append({"no": no, "file": f, "status": w["status"], "problems": [], "skipped": "엔진(wp.Book)이 만든 조서가 아님"})
            continue
        problems = wp.check(p)
        for v in xlcalc.verify(p):
            if v["ok"] is False and not any(v["label"] in x for x in problems):
                problems.append(f"검산 불일치(엔진 재계산): {v['label']} 계산 {v['got']} · 엔진 {v['expected']}")
        if not problems and w["status"] == "검토 끝":
            out.append({"no": no, "file": f, "status": "검토 끝", "problems": [], "skipped": "검토 끝 유지"})
            continue
        st = wp.mark_checked(d, no, problems)
        out.append({"no": no, "file": f, "status": st, "problems": problems, "skipped": None})
    c = common.case(d)
    done = [x for x in out if not x["skipped"]]
    if done:
        c.setdefault("log", []).insert(0, {"at": now or folder._now(), "who": "검사",
                                          "what": f"조서 {len(done)}개를 검사했습니다. 검사 통과 {sum(1 for x in done if x['status'] == '검사 통과')}, "
                                                  f"작성중 {sum(1 for x in done if x['status'] == '작성중')}",
                                          "read": [x["file"] for x in done], "wrote": ["_색인/조서목록.json"]})
        common.put_idx(d, "감사건.json", c)
    return out
