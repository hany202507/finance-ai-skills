"""명령줄: 절차 점검(파일 방식). 조서 엑셀 파일 하나로 절차 줄 읽기 · 판정 검사 · 점검표 · 고른 줄 옮기기.

  procfile scan <조서.xlsx> [--sheet <시트>] [--rows <행 수>] [--width <글자 수>] [--json]
      조서를 훑는다. 시트마다 쓰인 범위 · 칸 글과 절차 표 후보. 아무것도 쓰지 않는다
  procfile rows <조서.xlsx> --layout <위치.json> [--json]
      위치 파일의 범위에서 절차 줄을 뽑는다. 그 영역의 확인 항목(정의가 있는 영역)을 함께 낸다
  procfile check <조서.xlsx> --layout <위치.json> --verdicts <판정.json> [--received <받은자료 폴더>] [--with <이름=다른 조서.xlsx> ...]
      판정을 검사해 조서 옆에 절차점검_<파일>.xlsx(점검표)와 절차점검_<파일>.json(기록)을 쓴다. 조서는 건드리지 않는다
  procfile apply <조서.xlsx> --who <이름> [--pick 번호...]
      점검표 「반영」 칸이 「예」 인 줄(또는 --pick 번호)만 조서 옆 검토의견_<파일>.xlsx 에 「열림」 으로 잇는다
  procfile status <조서.xlsx> [--json]
      점검 안 함 · 최신 · 조서 바뀜

끝난 값: 0(읽음 · 씀), 1(입력 오류 · 판정 거부).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def register(sub) -> None:
    p = sub.add_parser("procfile", help="절차 점검(파일 방식): 조서 엑셀 파일 하나로 절차 줄 · 판정 검사 · 점검표")
    ss = p.add_subparsers(dest="pcmd", required=True)
    sc = ss.add_parser("scan", help="조서를 훑어 시트 · 칸 글 · 절차 표 후보를 보인다")
    sc.add_argument("workpaper")
    sc.add_argument("--sheet", default=None, help="이 시트만 보인다")
    sc.add_argument("--rows", type=int, default=80, help="시트마다 보일 행 수(기본 80)")
    sc.add_argument("--width", type=int, default=40, help="칸 글을 자르는 글자 수(기본 40). 수행 시트를 읽을 때는 크게 준다")
    sc.add_argument("--json", action="store_true")
    sc.set_defaults(func=_scan)
    rw = ss.add_parser("rows", help="위치 파일의 범위에서 절차 줄을 뽑는다")
    rw.add_argument("workpaper")
    rw.add_argument("--layout", required=True)
    rw.add_argument("--json", action="store_true")
    rw.set_defaults(func=_rows)
    ck = ss.add_parser("check", help="판정을 검사해 조서 옆에 점검표를 쓴다")
    ck.add_argument("workpaper")
    ck.add_argument("--layout", required=True)
    ck.add_argument("--verdicts", required=True)
    ck.add_argument("--received", default=None, help="받은자료 폴더. 주지 않으면 조서 폴더의 「00 받은자료」")
    ck.add_argument("--with", dest="also", action="append", default=[], help="근거로 쓸 다른 조서. 「이름=경로」 또는 경로")
    ck.add_argument("--json", action="store_true")
    ck.set_defaults(func=_check)
    ap = ss.add_parser("apply", help="고른 줄만 조서 옆 검토의견 파일에 옮긴다")
    ap.add_argument("workpaper")
    ap.add_argument("--who", required=True, help="옮기는 사람 이름")
    ap.add_argument("--pick", type=int, nargs="*", default=None, help="점검표 번호. 주지 않으면 「반영」 칸이 「예」 인 줄")
    ap.add_argument("--json", action="store_true")
    ap.set_defaults(func=_apply)
    st = ss.add_parser("status", help="점검 상태")
    st.add_argument("workpaper")
    st.add_argument("--json", action="store_true")
    st.set_defaults(func=_status)


def _json(path: str, what: str):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as e:
        raise ValueError(f"{what} 파일을 읽지 못했습니다: {path} ({e})") from None


def _dump(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=1, default=str))


def _guard(fn):
    def run(a) -> int:
        from .procrules import Rejected

        try:
            return fn(a)
        except Rejected as e:
            print("받지 않았습니다. 아무것도 쓰지 않았습니다.")
            for x in e.problems:
                print(f"  - {x}")
            return 1
        except ValueError as e:
            print(str(e))
            return 1
        except PermissionError as e:
            print(f"파일을 쓰지 못했습니다. 엑셀에서 열어 둔 파일이면 닫고 다시 합니다: {e.filename}")
            return 1
    return run


@_guard
def _scan(a) -> int:
    from . import procfile

    out = procfile.scan(Path(a.workpaper), max_rows=a.rows, width=a.width)
    if a.sheet:
        out["sheets"] = [s for s in out["sheets"] if s["name"] == a.sheet]
        out["candidates"] = [c for c in out["candidates"] if c["sheet"] == a.sheet]
    if a.json:
        _dump(out)
        return 0
    print(f"조서 {out['file']}")
    for s in out["sheets"]:
        print(f"\n[{s['name']}] 쓰인 범위 ~{s['max_col']}{s['max_row']}" + (f" · 병합 {len(s['merged'])}곳" if s["merged"] else "")
              + (f" · 앞 {s['shown_rows']}행만 보임" if s["shown_rows"] < s["max_row"] else ""))
        for row in s["cells"]:
            print(f"  {row['r']:>3} | " + " | ".join(f"{k}: {v}" for k, v in row["c"].items()))
    print("\n절차 표 후보(제안입니다. 조서를 보고 고칩니다)")
    for c in out["candidates"] or []:
        cols = " · ".join(f"{k} {c[k]}" for k in ("step", "applies", "ref", "result", "who") if k in c)
        print(f"  {c['sheet']} {c['first_row']} ~ {c['last_row']}행(머리글 {c['head_row']}행) · {cols}")
    if not out["candidates"]:
        print("  머리글 낱말로 찾은 후보가 없습니다. 칸 글을 보고 위치 파일을 직접 씁니다")
    print(f"\n확인 항목 정의가 있는 영역: {' · '.join(out['defined_areas']) or '없음'}")
    return 0


@_guard
def _rows(a) -> int:
    from . import procfile

    v = procfile.view(Path(a.workpaper), _json(a.layout, "위치"))
    keep = ("n", "key", "step", "applies", "ref", "result", "who", "state", "flags", "cont_rows", "dup_step")
    out = {"file": v["file"], "area": v["area"], "defined": v["defined"], "defined_areas": v["defined_areas"], "sheets": v["sheets"],
           "status": v["status"], "range_problems": v["range_problems"], "layout_notes": v["layout_notes"], "rows": [{k: r[k] for k in keep} for r in v["rows"]],
           "area_points": v["area_points"],
           "verdicts": list(procfile.R.VERDICTS), "aspects": list(procfile.R.ASPECTS)}
    if a.json:
        _dump(out)
        return 0
    print(f"조서 {v['file']} · 영역 {v['area']} · 절차 줄 {len(v['rows'])}개 · 점검 상태 {v['status']['check']}")
    for r in v["rows"]:
        print(f"  {r['n']:>2}. [{r['key']}] {r['step']}")
        print(f"      해당 여부 {r['applies'] or '빈칸'}({r['state']}) · 수행 위치 {r['ref'] or '빈칸'} · 수행자 {r['who'] or '빈칸'}")
        if r["result"]:
            print(f"      수행 결과: {r['result'][:200]}")
        for f in r["flags"]:
            print(f"      표시: {f}")
    for p in v["range_problems"]:
        print(f"범위 문제(고치기 전에는 판정을 받지 않습니다): {p}")
    for p in v["layout_notes"]:
        print(f"알림: {p}")
    if v["defined"]:
        print(f"\n영역 {v['area']} 의 확인 항목(판정 파일 coverage 에 절차 번호마다 절차 줄을 댑니다)")
        for p in v["area_points"]:
            print(f"  {p['id']} {p['title']}: {p['what']}")
            if p["points"]:
                print(f"      볼 항목: {' · '.join(p['points'])}")
    else:
        print(f"\n영역 {v['area']} 는 확인 항목 정의가 없습니다(있는 영역: {' · '.join(v['defined_areas']) or '없음'}). 조서에 적힌 절차 줄만 점검합니다")
    return 0


@_guard
def _check(a) -> int:
    from . import procfile

    rec = procfile.accept(Path(a.workpaper), _json(a.layout, "위치"), _json(a.verdicts, "판정"), received=a.received, also=a.also)
    if a.json:
        _dump(rec)
        return 0
    print(f"점검표를 썼습니다: {Path(a.workpaper).with_name(rec['file'])}")
    print(procfile.R.summary(rec).replace(" · 수행 안 함 0줄", ""))
    if not rec["defined"]:
        print(f"영역 {rec['area']} 는 확인 항목 정의가 없어 조서에 적힌 절차 줄만 점검했습니다")
    for x in rec["items"]:
        if x["n"]:
            print(f"  {x['n']}. {x['verdict']} · {x['step'][:40]} · {x['missing']}")
    print("AI 판정이고 확인 전입니다. 점검표 「반영」 칸에 「예」 를 적은 줄만 검토의견에 옮깁니다(apply)")
    return 0


@_guard
def _apply(a) -> int:
    from . import procfile

    out = procfile.apply(Path(a.workpaper), a.who, a.pick)
    if a.json:
        _dump(out)
        return 0
    if out["moved"]:
        print(f"검토의견에 옮겼습니다: {out['review']} · 번호 {', '.join(map(str, out['moved']))}")
    else:
        print("옮긴 줄이 없습니다. 점검표 「반영」 칸에 「예」 를 적거나 --pick 으로 번호를 줍니다")
    if out["already"]:
        print(f"이미 옮긴 줄: {', '.join(map(str, out['already']))}")
    if out["left"]:
        print(f"고르지 않은 줄 {len(out['left'])}개는 점검표에만 남습니다")
    return 0


@_guard
def _status(a) -> int:
    from . import procfile

    st = procfile.status(Path(a.workpaper))
    if a.json:
        _dump(st)
        return 0
    print(f"{Path(a.workpaper).name}: {st['check']}" + (f" · 점검 {st['at']} · 볼 것 {st['todo']}줄 · 검토의견에 옮긴 줄 {st['applied']}줄" if st["at"] else ""))
    if st["changed"]:
        print(f"  점검 뒤에 바뀐 파일: {' · '.join(st['changed'])}")
    return 0


if __name__ == "__main__":      # python -m audit.cli_procfile 로도 돈다
    import argparse

    _ap = argparse.ArgumentParser(prog="procfile")
    _sub = _ap.add_subparsers(dest="cmd", required=True)
    register(_sub)
    _a = _ap.parse_args(["procfile", *sys.argv[1:]])
    sys.exit(int(_a.func(_a) or 0))
