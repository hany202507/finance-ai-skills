# -*- coding: utf-8 -*-
"""표준조서 실행기. 시산표 · 전기 재무제표 · 분개장 · 매출채권 명세가 든 자료 폴더 하나로 정산표와 계정별 표준조서를 만든다.

    python run.py list
        조서 목록(조서번호 · 이름 · 정산표 영역 · 절차 시트)
    python run.py make <자료 폴더> --company <회사> --fy-end YYYY-MM-DD [--fy-start YYYY-MM-DD] [--as-of YYYY-MM-DD]
        [--pm <수행중요성>] [--risk 기본|낮음|보통|높음] [--area 4000C ...] [--force] [--json]
        자료 폴더 안에 감사 폴더 「표준조서_<결산일> 기말감사」(--as-of 면 「표준조서_<기준일> 중간감사」)를 세우고
        자료 파일을 「00 받은자료」 로 복사해 읽은 뒤 정산표(8000 감사완결/8100B_정산표.xlsx)와 표준조서(4000 계정별/표준조서/)를 만든다.
        이미 있는 표준조서는 건너뛴다(--force 면 다시 그리고 회계사 글은 옮긴다).
    python run.py refresh <자료 폴더> [--as-of YYYY-MM-DD] [--pm …] [--risk …] [--area …] [--json]
        자료 폴더의 바뀐 파일을 다시 읽어 정산표를 다시 만들고 표준조서의 정산표 시트 · 엔진 표를 다시 씌운다. 회계사 칸은 그대로 둔다.
    python run.py fill <자료 폴더> --area 4000C --patch <json 파일> [--as-of …] [--json]
        에이전트 글(메모 · 증감 사유 · 해당 여부 제안)을 「AI 작성」 칸으로 넣는다. 금액 꼴 글이 있으면 아무것도 쓰지 않는다.
    python run.py check <자료 폴더> [--as-of …] [--slots] [--json]
        정산표 판 · Lead 대사 차이 · 확인 전 AI 칸 · 빈 해당 여부 · 결론 빈 칸. --slots 는 fill 이 받는 칸 이름.
    python run.py roll <작년 자료 폴더> <올해 자료 폴더> [--prev-as-of YYYY-MM-DD] [--as-of …] [--json]
        작년 표준조서를 올해 감사 폴더로 옮겨 머리 · 서명 · 그해 글을 비우고 올해 정산표를 씌운다(올해 make 를 먼저 돌린다).
        같은 해 중간감사 조서를 기말감사로 옮기면 두 자료 폴더가 같고 --prev-as-of 에 중간감사 기준일을 준다.

끝난 값: 0(됨), 1(입력 오류 · 거부), 2(대사 차이 · 멈춘 조서가 있음).
숫자는 엔진이 받은자료에서 읽은 것만 쓴다. 수행중요성 · 위험 수준 · 해당 여부 · 결론은 감사인이 정한다.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
os.environ.setdefault("AUDIT_OCR", "off")
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass

from audit import stdmode  # noqa: E402

stdmode.STANDALONE = True

RECEIVED = "00 받은자료"
PREFIX = "표준조서_"
READ = (".xlsx", ".xlsm", ".csv")
RISKS = ("기본", "낮음", "보통", "높음")
SYNCED = "표준조서_동기화.json"      # _색인 아래. run.py 가 자료 폴더에서 복사한 파일 목록(이 목록에 있는 것만 지운다)


class Stop(Exception):
    """입력 오류. 아무것도 쓰지 않았다."""


# ---------------------------------------------------------------- 감사 폴더
def _iso(s: str | None, what: str) -> str | None:
    if s is None:
        return None
    try:
        return date.fromisoformat(s).isoformat()
    except ValueError:
        raise Stop(f"{what} 는 YYYY-MM-DD 로 적어 주십시오: {s}")


def _folders(src: Path) -> list[Path]:
    return sorted((p for p in src.iterdir() if p.is_dir() and p.name.startswith(PREFIX) and (p / "_색인" / "감사건.json").is_file()),
                  key=lambda p: p.stat().st_mtime, reverse=True)


def _name(fy_end: str, as_of: str | None) -> str:
    return f"{PREFIX}{as_of} 중간감사" if as_of else f"{PREFIX}{fy_end} 기말감사"


def _find(src: Path, as_of: str | None = None, flag: str = "--as-of") -> Path:
    """자료 폴더 안의 감사 폴더. --as-of 를 주면 「표준조서_<기준일> 중간감사」, 주지 않으면 기말감사 폴더.
    기말감사 폴더가 없고 중간감사 폴더가 하나뿐이면 그것. 그 밖에 여럿이면 고르지 않고 멈춘다."""
    if not src.is_dir():
        raise Stop(f"자료 폴더가 없습니다: {src}")
    got = _folders(src)
    if not got:
        raise Stop(f"표준조서 감사 폴더가 없습니다. 먼저 `python scripts/run.py make {src} --company … --fy-end …`")
    names = ", ".join(p.name for p in got)
    if as_of:
        hit = [p for p in got if p.name == _name("", as_of)]
        if not hit:
            raise Stop(f"{as_of} 중간감사 폴더가 없습니다. 있는 것: {names}")
        return hit[0]
    year_end = [p for p in got if p.name.endswith(" 기말감사")]
    if len(year_end) == 1:
        return year_end[0]
    if not year_end and len(got) == 1:
        return got[0]
    raise Stop(f"감사 폴더가 여럿입니다({names}). 중간감사면 {flag} <기준일> 을 주십시오. "
               "기말감사 폴더가 둘 이상이면 쓰지 않는 폴더를 자료 폴더 밖으로 옮기십시오")


def _sources(src: Path) -> tuple[list[Path], list[Path]]:
    """자료 폴더의 읽을 파일과 읽지 않는 파일. 감사 폴더(표준조서_*) · 엑셀 임시 파일(~$) · 숨김 파일은 보지 않는다."""
    take, skip = [], []
    for p in sorted(src.rglob("*")):
        rel = p.relative_to(src)
        if not p.is_file() or rel.parts[0].startswith(PREFIX) or any(x.startswith((".", "~$")) for x in rel.parts):
            continue
        (take if p.suffix.lower() in READ else skip).append(p)
    return take, skip


def _digest(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _sync(src: Path, d: Path) -> dict:
    """자료 파일을 받은자료로 복사한다(하위 폴더 그대로). 내용이 바뀐 파일만 다시 쓴다.
    자료 폴더에서 사라진 파일은 이 실행기가 앞서 복사한 것(_색인/표준조서_동기화.json)만 받은자료에서 뺀다.
    감사인이 받은자료에 직접 넣은 파일은 건드리지 않는다. 회사 원본(자료 폴더)은 읽기만 한다."""
    take, skip = _sources(src)
    if not take:
        raise Stop(f"읽을 엑셀 · CSV 파일이 없습니다: {src}")
    rec = d / RECEIVED
    log = d / "_색인" / SYNCED
    try:
        before = set(json.loads(log.read_text(encoding="utf-8")).get("files") or [])
    except (OSError, ValueError):
        before = set()
    want = {p.relative_to(src).as_posix(): p for p in take}
    added, changed, removed = [], [], []
    for rel, p in want.items():
        dst = rec / rel
        if dst.exists() and dst.stat().st_size == p.stat().st_size and _digest(dst) == _digest(p):
            continue
        (changed if dst.exists() else added).append(rel)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, dst)
    for rel in sorted(before - set(want)):
        f = rec / rel
        if f.is_file():
            removed.append(rel)
            f.unlink()
    log.write_text(json.dumps({"source": str(src), "files": sorted(want)}, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"added": added, "changed": changed, "removed": removed, "skipped": [str(p.relative_to(src)) for p in skip]}


def _case(d: Path) -> dict:
    return json.loads((d / "_색인" / "감사건.json").read_text(encoding="utf-8"))


def _basis(d: Path) -> str:
    """감사 폴더의 기준일(중간감사면 기준일, 아니면 결산일)."""
    case = _case(d)
    return str((case.get("std") or {}).get("as_of") or case.get("fiscal_year_end") or "")


def _set_std(d: Path, pm: float | None, risk: str | None, as_of: str | None) -> dict:
    """감사인 입력을 _색인/감사건.json 「std」 칸에 적는다. 주지 않은 값은 앞에 적은 값을 그대로 둔다."""
    p = d / "_색인" / "감사건.json"
    case = _case(d)
    std = dict(case.get("std") or {})
    if pm is not None:
        if pm <= 0:
            raise Stop("수행중요성(--pm)은 0 보다 큰 금액이어야 합니다")
        std["performance"] = pm
    if risk is not None:
        std["risk"] = risk
    if as_of is not None:
        std["as_of"] = as_of
    case["std"] = std
    p.write_text(json.dumps(case, ensure_ascii=False, indent=1), encoding="utf-8")
    return std


def _read(d: Path) -> None:
    from audit import folder, index

    folder.scan(d)
    index.read_all(d, use_ocr=False)


def _wtb(d: Path) -> Path:
    from audit import stdtb

    try:
        return stdtb.build(d, _case(d).get("std", {}).get("as_of"))
    except LookupError as e:
        raise Stop(str(e))


def _tb_note(d: Path) -> str | None:
    """정산표에 쓴 시산표의 기간(색인)이 감사 기준일과 다르거나 연도만 있어 가를 수 없으면 확인할 줄 하나."""
    from audit import figures

    rows = figures.current_tb(d)
    if not rows:
        return None
    tb = Path(str(rows[0]["path"]))
    try:
        files = json.loads((d / "_색인" / "문서목록.json").read_text(encoding="utf-8")).get("files") or []
    except (OSError, ValueError):
        return None
    hit = next((f for f in files if str(f.get("path") or "").replace("\\", "/") == tb.as_posix()), None)
    period = str((hit or {}).get("period") or "").strip()
    basis = _basis(d)
    if not period or not basis:
        return None
    end = period.split("~")[-1].strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", end):
        same = end == basis
    elif re.fullmatch(r"\d{4}-\d{2}", end):
        same = end == basis[:7]
    elif re.fullmatch(r"\d{4}", end):
        same = None if (_case(d).get("std") or {}).get("as_of") else end == basis[:4]
    else:
        same = None
    if same:
        return None
    why = "기준일과 다릅니다" if same is False else "기간이 연도만 적혀 있어 중간 기준일 시산표인지 가를 수 없습니다"
    return f"확인: 정산표에 쓴 시산표 {tb.name} 의 기간 {period} 이 감사 기준일 {basis} 과 맞는지 보십시오({why})"


# ---------------------------------------------------------------- 출력
def _out(a, obj, lines: list[str]) -> None:
    if getattr(a, "json", False):
        print(json.dumps(obj, ensure_ascii=False, indent=1, default=str))
    else:
        print("\n".join(lines))


def _feeds(x: dict) -> str:
    out = []
    if x.get("filled"):
        out.append("엔진 채움 " + ", ".join(x["filled"]))
    if x.get("feed_errors"):
        out.append("못 채움 " + "; ".join(f"{k} {v}" for k, v in x["feed_errors"].items()))
    return ("  " + " · ".join(out)) if out else ""


def _sync_lines(s: dict) -> list[str]:
    lines = []
    for k, lab in (("added", "새로 읽음"), ("changed", "바뀐 파일"), ("removed", "자료 폴더에 없어 뺌")):
        if s[k]:
            lines.append(f"{lab} {len(s[k])}개: " + ", ".join(s[k][:8]) + (" …" if len(s[k]) > 8 else ""))
    if s["skipped"]:
        lines.append(f"읽지 않은 파일 {len(s['skipped'])}개(공개판은 엑셀 xlsx · CSV 만 읽습니다): " + ", ".join(s["skipped"][:8]))
    return lines


def _std_line(std: dict) -> str:
    pm = std.get("performance")
    return ("수행중요성 " + (f"{pm:,.0f}원" if pm else "없음(--pm 을 주면 4000C .02 표본을 뽑습니다)")
            + " · 표본 위험 수준 " + (std.get("risk") or "기본(정하지 않음)"))


def _unassigned(res: dict) -> list[str]:
    u = res.get("unassigned") or []
    if not u:
        return []
    return [f"정산표 「영역」 이 표준조서 정의에 없는 계정 {len(u)}개: " + ", ".join(f"{x['code']} {x['name']}({x['area'] or '빈 칸'})" for x in u[:12])]


# ---------------------------------------------------------------- 명령
def _check_areas(area) -> None:
    from audit.stdwp import list_defs

    known = {x["code"] for x in list_defs()}
    bad = [x for x in (area or []) if x not in known]
    if bad:
        raise Stop(f"없는 조서번호입니다: {', '.join(bad)}. `python scripts/run.py list` 로 보십시오")


def cmd_list(a) -> int:
    from audit.stdwp import list_defs

    rows = list_defs()
    _out(a, rows, [f"{x['code']:<9} {x['name']:<12} 영역 {x['letter']:<5} {', '.join(x['sheets'])}" for x in rows])
    return 0


def cmd_make(a) -> int:
    from audit import folder, stdwp

    src = Path(a.src).resolve()
    if not src.is_dir():
        raise Stop(f"자료 폴더가 없습니다: {src}")
    fy_end, fy_start, as_of = _iso(a.fy_end, "--fy-end"), _iso(a.fy_start, "--fy-start"), _iso(a.as_of, "--as-of")
    if as_of and as_of > fy_end:
        raise Stop(f"중간감사 기준일 {as_of} 이 결산일 {fy_end} 보다 뒤입니다")
    if fy_start and not fy_start <= (as_of or fy_end):
        raise Stop(f"사업연도 시작일 {fy_start} 이 {'기준일' if as_of else '결산일'} {as_of or fy_end} 보다 뒤입니다")
    if not _sources(src)[0]:                                          # 감사 폴더를 만들기 전에 본다(아무것도 쓰지 않음)
        raise Stop(f"읽을 엑셀 · CSV 파일이 없습니다: {src}")
    _check_areas(a.area)
    if a.pm is not None and a.pm <= 0:
        raise Stop("수행중요성(--pm)은 0 보다 큰 금액이어야 합니다")
    d = src / _name(fy_end, as_of)
    if not (d / "_색인" / "감사건.json").is_file():
        folder.scaffold(d, a.company, fy_end, "계속감사", fiscal_year_start=fy_start)
    s = _sync(src, d)
    std = _set_std(d, a.pm, a.risk, as_of)
    _read(d)
    wtb = _wtb(d)
    res = stdwp.make(d, a.area, None, a.force)
    note = _tb_note(d)
    lines = [f"감사 폴더: {d}", *_sync_lines(s), f"정산표: {wtb}", _std_line(std), *([note] if note else [])]
    lines += [f"만듦  {x['code']}  계정 {x['accounts']}개  {x['file']}" + _feeds(x) for x in res["made"]]
    lines += [f"건너뜀 {x['code']}  {x['why']}" for x in res["skipped"]]
    lines += _unassigned(res)
    _out(a, {"folder": str(d), "sync": s, "wtb": str(wtb), "std": std, "tb_note": note, **res}, lines)
    return 0


def cmd_refresh(a) -> int:
    from audit import stdwp

    src = Path(a.src).resolve()
    _check_areas(a.area)
    d = _find(src, _iso(a.as_of, "--as-of"))
    if a.pm is not None and a.pm <= 0:
        raise Stop("수행중요성(--pm)은 0 보다 큰 금액이어야 합니다")
    s = _sync(src, d)
    std = _set_std(d, a.pm, a.risk, None)
    _read(d)
    wtb = _wtb(d)
    res = stdwp.refresh(d, a.area, None)
    note = _tb_note(d)
    lines = [f"감사 폴더: {d}", *_sync_lines(s), f"정산표: {wtb}", _std_line(std), *([note] if note else [])]
    for x in res["done"]:
        extra = []
        if x.get("added"):
            extra.append("새 계정 " + ", ".join(x["added"]))
        if x.get("gone"):
            extra.append("정산표에 없음 " + ", ".join(x["gone"]))
        if x.get("note"):
            extra.append(x["note"])
        lines.append(f"씌움 {x['code']}  " + (" · ".join(extra) or "계정 변동 없음") + _feeds(x))
    lines += [f"멈춤 {x['code']}  {x['why']}" for x in res["stopped"]]
    lines += _unassigned(res)
    if not res["done"] and not res["stopped"]:
        lines.append("표준조서가 없습니다. 먼저 make")
    _out(a, {"folder": str(d), "sync": s, "wtb": str(wtb), "std": std, "tb_note": note, **res}, lines)
    return 2 if res["stopped"] else 0


def cmd_fill(a) -> int:
    from audit import stdwp

    d = _find(Path(a.src).resolve(), _iso(a.as_of, "--as-of"))
    try:
        patch = json.loads(Path(a.patch).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise Stop(f"--patch 파일을 읽지 못했습니다: {e}")
    res = stdwp.fill(d, a.area, patch)
    _out(a, res, [f"넣음 {res['code']}  칸 {res['written']}개 · 확인 전 AI 칸 모두 {res['ai_total']}개  {res['file']}"])
    return 0


def cmd_check(a) -> int:
    from audit import stdwp

    d = _find(Path(a.src).resolve(), _iso(a.as_of, "--as-of"))
    res = stdwp.check(d)
    lines, bad = [f"감사 폴더: {d}"], False
    for x in res:
        msg = [f"{x['code']}  정산표 {x['source']} · 씌움 {x['refreshed']}"]
        if x["stale"]:
            msg.append("정산표가 더 새로움(refresh)")
            bad = True
        if x["diff"]:
            msg.append("대사 차이 " + ", ".join(f"{d_['block']} {d_['cell']} {d_.get('diff', d_.get('error'))}" for d_ in x["diff"]))
            bad = True
        if x.get("busy"):
            msg.append("엑셀에서 열려 있음")
        msg.append(f"확인 전 AI 칸 {x['ai_open']} · 빈 해당 여부 {x['apply_blank']}")
        if x.get("conclusion_blank"):
            msg.append("결론 빈 칸 " + ", ".join(x["conclusion_blank"]))
        if x.get("feed_errors"):
            msg.append("엔진 못 채움 " + "; ".join(f"{k} {v}" for k, v in x["feed_errors"].items()))
        lines.append(" · ".join(msg))
        if a.slots:
            lines.append("  칸: " + ", ".join(x["slots"]))
    if not res:
        lines.append(f"표준조서가 없습니다. 먼저 `python scripts/run.py make {Path(a.src)} --company … --fy-end …`")
        _out(a, res, lines)
        return 1
    _out(a, res, lines)
    return 2 if bad else 0


def cmd_roll(a) -> int:
    from audit import stdwp

    prev = _find(Path(a.prev).resolve(), _iso(a.prev_as_of, "--prev-as-of"), "--prev-as-of")
    d = _find(Path(a.src).resolve(), _iso(a.as_of, "--as-of"))
    if prev.resolve() == d.resolve():
        raise Stop(f"옮길 곳과 옮겨 올 곳이 같은 감사 폴더입니다: {d.name}. "
                   "같은 자료 폴더의 중간감사 조서를 기말감사로 옮기면 --prev-as-of <중간감사 기준일> 을 주십시오")
    if _basis(prev) >= _basis(d):
        raise Stop(f"옮겨 올 조서({prev.name}, 기준일 {_basis(prev)})가 옮길 곳({d.name}, 기준일 {_basis(d)})보다 늦거나 같습니다. "
                   "작년 · 앞 기간 조서를 올해 · 뒤 기간으로만 옮깁니다")
    res = stdwp.roll(prev, d, None)
    lines = [f"작년 {prev} → 올해 {d}"]
    lines += [f"옮김 {x['file']}" + (f"  ({x['skip']})" if x.get("skip") else "") for x in res["moved"]]
    lines += [f"씌움 {x['code']}" for x in res["refresh"]["done"]]
    lines += [f"멈춤 {x['code']}  {x['why']}" for x in res["refresh"]["stopped"]]
    _out(a, res, lines)
    return 2 if res["refresh"]["stopped"] else 0


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="run.py", description="표준조서: 자료 폴더 하나로 정산표와 계정별 표준조서를 만든다")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("list", help="조서 목록")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_list)

    def common(p, folder_arg: bool = True):
        if folder_arg:
            p.add_argument("src", help="자료 폴더(시산표 · 전기 재무제표 · 분개장 · 매출채권 명세가 있는 곳)")
        p.add_argument("--as-of", default=None, help="중간감사 기준일(그 감사 폴더를 고를 때)")
        p.add_argument("--json", action="store_true")

    m = sub.add_parser("make", help="정산표와 표준조서를 만든다")
    common(m)
    m.add_argument("--company", required=True, help="회사 이름(조서 머리)")
    m.add_argument("--fy-end", required=True, help="결산일(사업연도 끝) 2025-12-31")
    m.add_argument("--fy-start", default=None, help="사업연도 시작일(반기 · 짧은 사업연도만)")
    for p in (m, r := sub.add_parser("refresh", help="바뀐 자료로 정산표와 표준조서를 다시 씌운다")):
        if p is r:
            common(r)
        p.add_argument("--pm", type=float, default=None, help="수행중요성(감사인이 정한 금액). 4000C .02 금액 단위 표본에 쓴다")
        p.add_argument("--risk", choices=RISKS, default=None, help="표본 위험 수준(기본 · 낮음 · 보통 · 높음)")
        p.add_argument("--area", nargs="*", default=None, help="조서번호(4000C 4000A …). 비우면 정산표에 계정이 있는 영역")
    m.add_argument("--force", action="store_true", help="있는 표준조서를 다시 그린다(회계사 글은 옮긴다)")
    m.set_defaults(func=cmd_make)
    r.set_defaults(func=cmd_refresh)
    f = sub.add_parser("fill", help="에이전트 글을 AI 칸으로 넣는다")
    common(f)
    f.add_argument("--area", required=True)
    f.add_argument("--patch", required=True)
    f.set_defaults(func=cmd_fill)
    c = sub.add_parser("check", help="정산표 판 · 대사 차이 · 확인 전 AI 칸")
    common(c)
    c.add_argument("--slots", action="store_true")
    c.set_defaults(func=cmd_check)
    o = sub.add_parser("roll", help="작년 표준조서를 올해로 옮긴다")
    o.add_argument("prev", help="작년 자료 폴더(같은 해 중간감사 → 기말감사면 올해 자료 폴더와 같아도 된다)")
    common(o)
    o.add_argument("--prev-as-of", default=None, help="옮겨 올 쪽이 중간감사면 그 기준일")
    o.set_defaults(func=cmd_roll)
    return ap


def main(argv: list[str] | None = None) -> int:
    from audit.stdwp import Problem

    a = _parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    try:
        return int(a.func(a) or 0)
    except (Stop, Problem) as e:
        print(str(e))
        return 1


if __name__ == "__main__":
    sys.exit(main())
