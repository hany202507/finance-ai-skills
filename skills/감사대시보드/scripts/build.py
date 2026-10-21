"""감사 대시보드: 감사 폴더의 _색인 을 읽어 단계 · 세부 항목 · 조서 · 스킬 · 이슈를 한 화면에 보이는 HTML 한 파일을 만든다.

    python scripts/build.py <감사 폴더 또는 _색인 폴더> --out <출력.html> [--demo]

왼쪽 사이드바에 다섯 단계와 세부 항목, 오른쪽에 고른 항목의 조서번호 · 스킬 적용 현황 · 이슈 · 빠진 자료를 보인다.
읽기만 하고 _색인 을 고치지 않는다. 표준 라이브러리만 쓴다.
"""
import argparse
import json
import sys
from pathlib import Path

# ---- 고쳐 쓰는 곳 1: 단계 → 세부 항목(이름, 조서번호, 맡은 스킬, 빠진 자료를 전부 보일지) --------------------------
# 조서번호는 한공회 감사조서 양식 번호다. 감사반 체계가 다르면 이 표만 고친다.
STAGES = [
    ("시작", "요청자료 · 계약 · 기업이해", [
        ("요청자료 목록 · 메일", ["PBC"], ["감사-시작자료", "감사-요청메일"], True),
        ("받은자료 판독", [], ["감사-맥락색인"], False),
        ("계약 조서", ["1100", "1200", "1300"], ["감사-시작자료", "감사-검토"], False),
        ("기업이해", ["2100"], ["감사-시작자료"], False),
    ]),
    ("위험평가", "정산표 · 중요성 · 분석적 검토 · 위험", [
        ("정산표", ["8100B"], ["감사-WTB"], False),
        ("중요성 · 방법론", ["2700A", "2700B"], ["감사-분석적검토"], False),
        ("분석적 검토", ["2120A"], ["감사-분석적검토"], False),
        ("주요 거래 · 의사록", ["2100-주요거래"], ["감사-주요회계처리"], False),
        ("위험평가 · 통제", ["2301", "2302", "2511", "2512", "2513", "2520", "2530", "2531", "2532", "2533"], ["감사-분석적검토", "감사-검토"], False),
        ("감사계획 · 배정", ["2110", "2110-배정"], ["감사-검토", "감사-지휘"], False),
    ]),
    ("실행", "계정별 실증절차 · 조회 · 분개테스트", [
        ("감사전 재무제표 확인", ["3650A"], ["감사-조서리드"], False),
        ("매출 · 매출채권", ["4000P", "4000C"], ["감사-매출채권"], False),
        ("자금", ["4000A", "4000BBDD", "4000D"], ["감사-자금"], False),
        ("매입 · 재고 · 원가", ["4000AA", "4000CC", "4000E", "4000Q"], ["감사-재고원가"], False),
        ("유형 · 무형자산", ["4000G", "4000H"], ["감사-유무형리스"], False),
        ("인건비", ["4000EE"], ["감사-인건비판관비"], False),
        ("우발부채 · 자본", ["4000CL", "4000GG"], ["감사-충당우발자본"], False),
        ("외부조회", ["3320"], ["감사-조회서"], False),
        ("분개테스트", ["3600-JET"], ["감사-JET"], False),
        ("특별 검토", ["3200", "3300", "3400", "3500", "3600", "3700"], ["감사-검토"], False),
    ]),
    ("보고", "수정 · 주석 · 감사보고서 · DART", [
        ("수정 반영", ["8100A", "8800"], ["감사-수정반영"], False),
        ("주석 · 종결분석", ["8400", "8110A"], ["감사-주석", "감사-푸팅"], False),
        ("재무제표 · 감사보고서", ["8810", "8820", "8300", "8500"], ["감사-감사보고서"], False),
        ("감사의견", ["8600", "8200"], ["감사-감사보고서"], False),
        ("DART 제출 파일", ["DART"], ["감사-DART", "감사-DSD푸팅"], False),
    ]),
    ("종결", "심리 · 감사 종료", [
        ("심리", ["8550"], ["감사-종결"], False),
        ("감사 종료 · 보관", ["8700"], ["감사-종결"], False),
    ]),
]
# ---- 고쳐 쓰는 곳 2: 이 저장소에 공개된 스킬(화면에 「공개」 표시) -----------------------------------------------------
PUBLIC = {"감사-시작자료": "PBC요청자료", "감사-요청메일": "PBC요청자료", "감사-JET": "분개테스트", "감사-DSD푸팅": "DSD푸팅"}
# ---- 고쳐 쓰는 곳 3: --demo 때 덮는 조서 상태(위험평가까지 끝나고 실행 단계 중인 시점) ----------------------------------
DEMO = {**{n: "검토 끝" for n in ["PBC", "1100", "1200", "1300", "2100", "2110", "2110-배정"]},
        **{n: "검사 통과" for n in ["2100-주요거래", "2120A", "2301", "2302", "2700A", "2700B", "8100B", "2511", "2512", "2513",
                                   "2520", "2530", "2531", "2532", "2533", "3650A"]},
        **{n: "검토 요청" for n in ["4000A", "4000P"]}}
DEMO_AI_DONE = ("받은자료 판독", "스캔본 의사록", "분석.json 과 이슈")
# AI 몫 가운데 조서번호가 문장에 없는 것을 어느 항목에 보일지
AI_HOME = {"받은자료 판독": "받은자료 판독", "스캔본 의사록": "주요 거래 · 의사록", "분석.json 과 이슈": "분석적 검토"}
DONE = ("검토 끝", "검사 통과")


def load(idx: Path, name: str, default):
    p = idx / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def build(idx: Path, demo: bool) -> dict:
    case = load(idx, "감사건.json", None)
    if case is None:
        sys.exit(f"{idx} 에 감사건.json 이 없습니다. 감사 폴더나 그 안의 _색인 폴더를 주십시오")
    wps = load(idx, "조서목록.json", {}).get("workpapers", [])
    docs = load(idx, "문서목록.json", {})
    issues = load(idx, "이슈.json", {}).get("issues", [])
    ana = load(idx, "분석.json", {})
    run = load(idx, "실행기록.json", {})
    assume = DEMO if demo else {}
    ai_done = DEMO_AI_DONE if demo else ()

    by = {w["no"]: w for w in wps}
    fid = {f["id"]: f for f in ana.get("findings", [])}
    pat = {p["id"]: p["title"] for p in ana.get("patterns", [])}
    ana_by_no = {a["issue"]: a for a in ana.get("issues", [])}

    def status(n):
        w = by.get(n)
        if not w:
            return "없음"
        eng = {"없음": "미작성"}.get(w.get("status"), w.get("status") or "미작성")
        return assume.get(n, eng)

    def engine_runs(nos, skills):
        """실행기록에서 이 항목의 조서를 만든 엔진 단계와 그 조서에 해당하는 결과 줄."""
        res, seen = [], set()
        for st in run.get("steps", []):
            own = set(skills) & set(st.get("skills", []))
            if not own and not set(nos) & set(st.get("workpapers", [])):
                continue
            out, argv = st.get("output", []), st.get("argv", [])
            if argv[3:4] == ["analyze"]:
                lines = [o.strip() for o in out if "만듦" in o]
            elif own and set(st.get("workpapers", [])) <= set(nos):
                lines = [o.strip() for o in out]
            else:
                lines, keep = [], False
                for o in out:
                    if not o.startswith("    "):
                        keep = any(o.strip().startswith((n + ":", n + " ")) for n in nos)
                    if keep:
                        lines.append(o.strip())
                lines += [o for o in out if o.startswith("조서 ")]
            if tuple(lines) in seen:
                continue
            seen.add(tuple(lines))
            cmd = " ".join(a for a in argv[2:5] if not a.startswith("<"))
            res.append({"cmd": "python -m " + cmd, "code": st.get("code"), "skills": st.get("skills", []), "lines": lines[:10]})
        return res

    def ai_rows(nos, name):
        rows = []
        for a in run.get("ai", []):
            w = a["what"]
            home = next((v for k, v in AI_HOME.items() if w.startswith(k)), None)
            if home == name or (home is None and any(n in w.split(" 표지")[0].split(" · ") for n in nos)):
                rows.append({"what": w, "how": a.get("how", ""), "done": w.startswith(ai_done) if ai_done else False})
        return rows

    def cpa_rows(nos, name):
        rows = []
        for x in run.get("left", {}).get("회계사", []):
            wp = x.get("workpaper")
            if (wp in nos and status(wp) not in DONE + ("검토 요청",)) or (wp is None and name == "받은자료 판독"):
                rows.append({"title": x["title"], "detail": x.get("detail") or ""})
        for n in nos:
            if status(n) == "검토 요청":
                rows.append({"title": f"{n} 검토의견을 적어 주십시오", "detail": f"동료가 남긴 검토의견_{n}.xlsx 를 읽어 서명과 검토 끝을 적습니다(감사-검토)"})
        return rows

    def issue_rows(nos):
        rows = []
        for i in issues:
            if i.get("response_wp") not in nos and i.get("origin_wp") not in nos:
                continue
            a = ana_by_no.get(i["no"], {})
            ev = []
            for f in a.get("findings", []):
                x = fid.get(f)
                if x:
                    m = x.get("metric") or {}
                    ev.append({"title": x.get("title"), "left": m.get("left"), "right": m.get("right"), "diff": m.get("diff"), "refs": x.get("refs") or []})
                if len(ev) == 3:
                    break
            rows.append({"no": i["no"], "title": i["title"], "account": i.get("account"), "amount": i.get("amount"),
                         "assertions": i.get("assertions") or [], "source": i.get("source"), "origin": i.get("origin_wp"),
                         "response": i.get("response_wp"), "status": i.get("status"), "score": a.get("score"),
                         "evidence": ev, "patterns": [pat.get(p, p) for p in a.get("patterns", [])][:4],
                         "role": "대응" if i.get("response_wp") in nos else "발견"})
        return rows

    stages = []
    for sname, what, subs in STAGES:
        items = []
        for name, nos, skills, all_missing in subs:
            wl = [{"no": n, "name": (by.get(n) or {}).get("name", ""), "status": status(n), "why": (by.get(n) or {}).get("why") or "",
                   "file": (by.get(n) or {}).get("file") or ""} for n in nos if n in by]
            iss = issue_rows(nos)
            runs = engine_runs(nos, skills) if nos else []
            for r in runs:  # analyze 의 「이슈 N 만듦」 줄은 이 항목에 걸린 이슈만 남긴다
                if r["cmd"].endswith("analyze"):
                    r["lines"] = [x for x in r["lines"] if any(x.startswith(f"이슈 {i['no']} ") for i in iss)]
            missing = [{"item": m["item"], "wp": m.get("workpaper") or "", "issue": m.get("issue")} for m in docs.get("missing", [])
                       if all_missing or any(n in (m.get("workpaper") or "") for n in nos)]
            items.append({"name": name, "skills": skills, "wps": wl, "runs": runs, "ai": ai_rows(nos, name),
                          "cpa": cpa_rows(nos, name), "issues": iss, "missing": missing})
        stages.append({"name": sname, "what": what, "items": items})

    inp = {k: (v or {}).get("value") for k, v in ana.get("inputs", {}).items()}
    return {
        "company": case["company"]["name"], "industry": case["company"].get("industry"), "fy_end": case.get("fiscal_year_end", ""),
        "kind": case.get("engagement_kind", ""), "version": case.get("company_version"), "demo": demo,
        "materiality": [inp.get("materiality.overall"), inp.get("materiality.performance"), inp.get("materiality.trivial")],
        "stages": stages, "public": PUBLIC, "files": len(docs.get("files", [])),
        "issues_total": len(issues), "missing_total": len(docs.get("missing", [])),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="감사 폴더의 _색인 으로 대시보드 HTML 을 만든다")
    ap.add_argument("folder", help="감사 폴더(<회사>/<연도> 기말감사) 또는 그 안의 _색인 폴더")
    ap.add_argument("--out", required=True, help="출력 HTML 경로")
    ap.add_argument("--demo", action="store_true", help="시연용: 실행 단계 중인 시점으로 조서 상태를 덮는다(화면에 안내 띠)")
    a = ap.parse_args(argv)
    f = Path(a.folder)
    idx = f if f.name == "_색인" else f / "_색인"
    data = build(idx, a.demo)
    html = (Path(__file__).with_name("template.html")).read_text(encoding="utf-8")
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html.replace("/*__DATA__*/null", json.dumps(data, ensure_ascii=False)), encoding="utf-8")
    n_items = sum(len(s["items"]) for s in data["stages"])
    n_wps = sum(len(i["wps"]) for s in data["stages"] for i in s["items"])
    print(f"{out}: 단계 5 · 세부 항목 {n_items} · 조서 {n_wps} · 이슈 {data['issues_total']} · 빠진 자료 {data['missing_total']}"
          + (" · 시연 상태" if a.demo else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
