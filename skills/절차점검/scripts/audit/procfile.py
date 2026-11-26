"""절차 점검(파일 방식). 조서 엑셀 파일 하나를 받는다. 감사 폴더 · 조서목록이 없어도 된다.

엔진이 양식을 모르므로 절차 표가 어디 있는지는 에이전트가 위치 파일로 알려 준다. 엔진은
  ① 그 범위에서 절차 줄을 빠짐없이 뽑고(rows · view)
  ② 판정이 줄마다 있는지 · 근거 칸이 실제로 있는지 검사해 조서 옆에 점검표를 쓰고(accept)
  ③ 회계사가 고른 줄만 조서 옆 검토의견 파일에 옮긴다(apply).
조서 파일은 건드리지 않는다. 적절한지의 판정은 에이전트가 하고 결론은 회계사가 낸다.
범위 밖에 절차가 더 있는지는 엔진이 다 알 수 없다. 범위에 붙은 행만 본다. 점검표에 범위를 적어 회계사가 보게 한다.

  scan(path)                         시트마다 쓰인 범위 · 칸 글 · 절차 표 후보
  view(path, layout)                 절차 줄과 그 영역의 확인 항목
  accept(path, layout, patch, ...)   판정 검사 → 절차점검_<파일>.xlsx · 절차점검_<파일>.json
  apply(path, who, picks)            고른 줄 → 검토의견_<파일>.xlsx
  status(path)                       점검 안 함 · 최신 · 조서 바뀜

위치 파일: {"area": "4000C", "tables": [{"sheet", "first_row", "last_row", "step", "applies"?, "ref"?, "result"?, "who"?,
            "excluded"?: {"<행>": "<뺀 까닭>"}}]}
판정 파일: {"workpaper": "<파일 이름>", "verdicts": [{"key": <번호 또는 "시트!행">, "verdict", "missing", "cites"}],
            "coverage"?: {"<절차 번호>": [<번호 또는 key>, ...]}}
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font
from openpyxl.utils import column_index_from_string, get_column_letter

from . import procrules as R
from .procrules import AREA, DONE, FRESH, NA, NEVER, NO_CITE, OK, OPEN, PART1, PICK, STALE, Rejected

FORMAT = 1
RECEIVED_DIR = "00 받은자료"
MIN_REASON = 15                     # 「해당 없음」 사유 글자 수(표시 기준)
MAX_IDS_PER_ROW = 3                 # 절차 줄 하나를 대응표에서 쓸 수 있는 절차 번호 수
COLS = ("step", "applies", "ref", "result", "who")
TABLE_KEYS = {"sheet", "first_row", "last_row", "head_row", "excluded", "continued", *COLS}
NEAR = 3                            # 범위 위아래로 빈 행을 건너 살피는 행 수
REVIEW_HEAD = ["번호", "위치", "의견", "답변", "상태"]
REVIEW_HEAD_ROW, REVIEW_FIRST = 3, 4
OPEN_STATE = "열림"
NA_WORDS = {"해당없음", "해당사항없음", "미해당", "비해당", "N/A", "NA", "N", "NO", "X", "×"}
DONE_WORDS = {"해당", "수행", "적용", "Y", "YES", "예", "O", "○", "V", "✓", "✔"}
DELIMS = ":：-–(（,·/"              # 「해당 없음(사유)」 처럼 까닭을 붙일 때 낱말 뒤에 올 수 있는 글자
GUESS = {"step": ("절차", "PROCEDURE"), "applies": ("해당", "적용"), "ref": ("조서번호", "조서", "W/P", "REF", "참조"),
         "result": ("결과", "결론", "RESULT"), "who": ("수행자", "담당")}
NOT_HUMAN = ("AI", "에이전트", "루틴", "CLAUDE", "GPT")
WORDS = {"rows_from": "절차 표", "rows_cmd": "`rows` 가 보인 번호나 key 를 그대로 적습니다", "work_cell": "절차 표 범위 밖의 수행 칸",
         "other": "조서 이름이", "listed": "함께 준 조서(--with)",
         "cite_forms": "「시트!칸」 · 「<함께 준 조서 이름>:시트!칸」 · 「받은자료:<경로>」"}


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _paths(path: Path) -> tuple[Path, Path, Path]:
    """(기록, 점검표, 검토의견). 모두 조서 옆에 둔다."""
    p = Path(path)
    return (p.with_name(f"절차점검_{p.stem}.json"), p.with_name(f"절차점검_{p.stem}.xlsx"), p.with_name(f"검토의견_{p.stem}.xlsx"))


def _open(path: Path):
    p = Path(path)
    if not p.is_file() or p.suffix.lower() not in (".xlsx", ".xlsm"):
        raise ValueError(f"조서 엑셀 파일(xlsx)이 아닙니다: {path}")
    return load_workbook(p, data_only=True), load_workbook(p)


# ---------------------------------------------------------------- 확인 항목 정의
def points(area: str) -> list[dict]:
    """그 영역의 확인 항목 [{id, title, what, points, refs}]. 정의가 없으면 빈 목록."""
    f = Path(__file__).resolve().parent.parent / "definitions" / "proc_points.yaml"
    if not f.is_file():
        return []
    import yaml

    steps = (((yaml.safe_load(f.read_text(encoding="utf-8")) or {}).get("areas") or {}).get(area) or {}).get("steps") or {}
    return [{"id": x["id"], "title": x["title"], "what": x["what"], "points": [p["name"] for p in x.get("points") or []],
             "refs": [f"{q['cite']}: {q['about']}" for q in x.get("refs") or []]} for _, x in sorted(steps.items())]


def defined_areas() -> list[str]:
    f = Path(__file__).resolve().parent.parent / "definitions" / "proc_points.yaml"
    if not f.is_file():
        return []
    import yaml

    return sorted(((yaml.safe_load(f.read_text(encoding="utf-8")) or {}).get("areas") or {}))


# ---------------------------------------------------------------- 훑어보기
def scan(path: Path, max_rows: int = 80, max_cols: int = 15, width: int = 40) -> dict:
    """조서를 읽기 전에 훑는다. 시트마다 쓰인 범위 · 병합 칸 · 칸 글(앞 max_rows 행)과 절차 표 후보. 후보는 제안이다."""
    wb, raw = _open(path)
    out = {"file": Path(path).name, "sheets": [], "candidates": [], "defined_areas": defined_areas()}
    for ws in wb.worksheets:
        if ws.title.startswith("_"):
            continue
        cells = []
        for r in range(1, min(ws.max_row, max_rows) + 1):
            c = {get_column_letter(i): R.text(ws.cell(r, i).value)[:width] for i in range(1, min(ws.max_column, max_cols) + 1)
                 if R.text(ws.cell(r, i).value)}
            if c:
                cells.append({"r": r, "c": c})
        out["sheets"].append({"name": ws.title, "max_row": ws.max_row, "max_col": get_column_letter(ws.max_column),
                              "merged": [str(m) for m in ws.merged_cells.ranges][:40], "shown_rows": min(ws.max_row, max_rows), "cells": cells})
        out["candidates"] += _guess(ws)
    wb.close()
    raw.close()
    return out


def _guess(ws) -> list[dict]:
    """머리글 낱말로 절차 표 후보를 찾는다. 절차 열이 있는 머리글 행마다 하나."""
    out = []
    for r in range(1, min(ws.max_row, 200) + 1):
        heads = {get_column_letter(c): re.sub(r"\s+", "", R.text(ws.cell(r, c).value)).upper() for c in range(1, min(ws.max_column, 30) + 1)}
        heads = {k: v for k, v in heads.items() if v and len(v) <= 12}
        found = {}
        for role in ("applies", "ref", "result", "who", "step"):        # 「절차」 는 「절차 결과」 같은 머리글에 뺏기지 않게 마지막에
            for col, h in heads.items():
                if col not in found.values() and any(k in h for k in GUESS[role]):
                    found[role] = col
                    break
        if "step" not in found or len(found) < 2:
            continue
        sc = column_index_from_string(found["step"])
        last, gap = r, 0
        for rr in range(r + 1, ws.max_row + 1):
            if R.text(ws.cell(rr, sc).value):
                last, gap = rr, 0
            else:
                gap += 1
                if gap > 1:
                    break
        if last > r:
            out.append({"sheet": ws.title, "head_row": r, "first_row": r + 1, "last_row": last, **found})
    return out


# ---------------------------------------------------------------- 위치 파일 · 절차 줄
def _col(v, name: str, probs: list, where: str) -> int | None:
    if v is None:
        return None
    try:
        return column_index_from_string(str(v).strip().upper())
    except (ValueError, AttributeError):
        probs.append(f"{where}: {name} 은 열 글자(A · B …)입니다: {v}")
        return None


def _layout(layout, wb) -> tuple[str, list[dict]]:
    """위치 파일 검사. (영역, 표 목록). 어긋나면 Rejected."""
    if not isinstance(layout, dict) or not isinstance(layout.get("tables"), list) or not layout["tables"]:
        raise Rejected(['위치 파일은 {"area": "<영역>", "tables": [{"sheet", "first_row", "last_row", "step", ...}]} 꼴입니다'])
    probs = []
    extra = sorted(set(layout) - {"area", "tables"})
    if extra:
        probs.append(f"위치 파일 맨 위에 쓸 수 없는 항목입니다: {', '.join(extra)}")
    area = layout.get("area")
    if not isinstance(area, str) or not area.strip():
        probs.append("위치 파일에 area(영역 번호, 예: 4000C)를 적습니다")
    tables = []
    for i, t in enumerate(layout["tables"], 1):
        where = f"{i}번째 표"
        if not isinstance(t, dict):
            probs.append(f"{where}: 객체여야 합니다")
            continue
        extra = sorted(set(t) - TABLE_KEYS)
        if extra:
            probs.append(f"{where}: 쓸 수 없는 항목입니다: {', '.join(extra)}")
        sheet = t.get("sheet")
        if not isinstance(sheet, str) or sheet not in wb.sheetnames or sheet.startswith("_"):
            probs.append(f"{where}: 조서에 없는 시트입니다: {sheet}")
            continue
        ws = wb[sheet]
        a, b = t.get("first_row"), t.get("last_row")
        if not all(isinstance(x, int) and not isinstance(x, bool) for x in (a, b)) or a < 1 or b < a or b > ws.max_row:
            probs.append(f"{where}: first_row · last_row 는 그 시트의 쓰인 범위(1 ~ {ws.max_row}행) 안의 행 번호입니다: {a} ~ {b}")
            continue
        cols = {k: _col(t.get(k), k, probs, where) for k in COLS}
        if cols["step"] is None:
            probs.append(f"{where}: step(절차 글이 있는 열)을 적습니다")
            continue
        used = [c for c in cols.values() if c]
        if len(used) != len(set(used)):
            probs.append(f"{where}: 같은 열을 두 칸에 썼습니다")
        ex = t.get("excluded") or {}
        if not isinstance(ex, dict):
            probs.append(f"{where}: excluded 는 {{\"<행>\": \"<뺀 까닭>\"}} 꼴입니다")
            ex = {}
        excluded = {}
        for k, why in ex.items():
            if not str(k).strip().isdigit() or not isinstance(why, str) or len(why.strip()) < 2:
                probs.append(f"{where}: excluded 는 행 번호와 뺀 까닭(2자 이상)입니다: {k}: {why}")
            else:
                excluded[int(str(k).strip())] = why.strip()
        head = t.get("head_row")
        if head is not None and head != a - 1:
            probs.append(f"{where}: head_row(머리글 행)는 first_row 바로 윗행({a - 1})만 적습니다: {head}")
        cont = t.get("continued") or []
        if not isinstance(cont, list) or not all(isinstance(x, int) and not isinstance(x, bool) and a < x <= b for x in cont):
            probs.append(f"{where}: continued 는 윗줄에 이어지는 행 번호 목록입니다(범위 안, 첫 행 뺌): {cont}")
            cont = []
        tables.append({"sheet": sheet, "first_row": a, "last_row": b, "cols": cols, "excluded": excluded,
                       "head_row": head, "continued": set(cont)})
    for i, t in enumerate(tables):
        for u in tables[i + 1:]:
            if t["sheet"] == u["sheet"] and t["first_row"] <= u["last_row"] and u["first_row"] <= t["last_row"]:
                probs.append(f"같은 시트({t['sheet']})의 두 표가 행이 겹칩니다")
    if probs:
        raise Rejected(probs)
    return area.strip(), tables


def _state(v, has_col: bool, result: str) -> tuple[str, str | None]:
    """해당 여부 칸 값 → (상태, 표시). 정해 둔 낱말과 꼭 맞을 때만 읽는다. 못 읽으면 미정으로 둔다."""
    if not has_col:
        return (DONE, None) if result else (OPEN, None)
    if isinstance(v, bool):
        return OPEN, f"해당 여부 칸이 참 · 거짓 값입니다(글로 적힌 값만 읽습니다): {v}"
    s = re.sub(r"\s+", "", R.text(v)).upper()
    if not s:
        return OPEN, None
    for words, state in ((NA_WORDS, NA), (DONE_WORDS, DONE)):       # 「해당없음」 을 「해당」 보다 먼저 본다
        for w in sorted(words, key=len, reverse=True):
            if s == w or (len(w) > 1 and s.startswith(w) and s[len(w)] in DELIMS):
                return state, None
    return OPEN, f"해당 여부 값을 읽지 못함: {R.text(v)[:20]}"


def _rows(wb, raw, tables: list[dict]) -> tuple[list[dict], list[str]]:
    """절차 줄과 범위 문제. 절차 열에 글이 있는 행이 절차 줄이다. 절차 열이 비고 다른 칸에 글이 있는 행은 윗줄에 잇는다."""
    out, probs = [], []
    for t in tables:
        ws, wr, cols = wb[t["sheet"]], raw[t["sheet"]], t["cols"]
        sc = cols["step"]
        merged = {(m.min_row, m.min_col): m for m in ws.merged_cells.ranges}
        cur, span = None, 0                               # span: 지금 절차 칸의 병합이 닿는 마지막 행
        for r in range(t["first_row"], t["last_row"] + 1):
            if r in t["excluded"]:
                continue
            vals = {k: (ws.cell(r, c).value if c else None) for k, c in cols.items()}
            uncached = [f"{get_column_letter(c)}{r}" for k, c in cols.items() if c and isinstance(wr.cell(r, c).value, str)
                        and wr.cell(r, c).value.startswith("=") and ws.cell(r, c).value is None]
            step = R.text(vals["step"])
            if not step:
                more = {k: R.text(v) for k, v in vals.items() if k != "step" and R.text(v)}
                if (more or uncached) and cur is not None and (r <= span or r in t["continued"]):
                    cur["cont_rows"].append(r)            # 병합한 절차 칸 아래의 행이거나 위치 파일이 이어진 행이라고 적은 행
                    cur["uncached"] += uncached
                    for k, v in more.items():
                        cur[k] = (cur[k] + "\n" + v) if cur[k] else v
                    if cur["_applies_raw"] in (None, "") and vals["applies"] not in (None, ""):
                        cur["_applies_raw"] = vals["applies"]
                elif more or uncached:
                    probs.append(f"{t['sheet']} {r}행: 절차 열은 비었는데 다른 칸에 글이나 수식이 있습니다. 윗줄에 이어지는 행이면 continued 에, "
                                 f"절차와 관계없는 행이면 excluded 에 까닭과 함께 적습니다. 따로 선 절차면 절차 열을 다시 봅니다")
                continue
            m = merged.get((r, sc))
            span = m.max_row if m else r
            cur = {"part": PART1, "key": f"{t['sheet']}!{r}", "sheet": t["sheet"], "row": r, "step": step.split("\n")[0][:120],
                   "step_full": step, "applies": R.text(vals["applies"]), "ref": R.text(vals["ref"]), "result": R.text(vals["result"]),
                   "who": R.text(vals["who"]), "cont_rows": [], "uncached": uncached, "has": {k: bool(c) for k, c in cols.items()},
                   "merged_to": m.max_row if m and m.max_row > r else None, "_applies_raw": vals["applies"]}
            out.append(cur)
        # 범위에 붙은 행: 아래로 이어지는 절차 열 글, 머리글 한 줄 위로 이어지는 절차 열 글
        def near(rng) -> list[int]:
            """범위 밖으로 이어지는 절차 열 글. 빈 행을 NEAR 줄까지 건너 살핀다."""
            got, gap = [], 0
            for r in rng:
                if R.text(ws.cell(r, sc).value):
                    got.append(r)
                    gap = 0
                else:
                    gap += 1
                    if gap >= NEAR:
                        break
            return got

        below = near(range(t["last_row"] + 1, ws.max_row + 1))
        above = [r for r in near(range(t["first_row"] - 1, 0, -1)) if r != t["head_row"]]
        others = [(u["first_row"], u["last_row"]) for u in tables if u["sheet"] == t["sheet"] and u is not t]
        loose = [r for r in below + above if r not in t["excluded"] and not any(a <= r <= b for a, b in others)]
        if loose:
            probs.append(f"{t['sheet']} 절차 표 범위({t['first_row']} ~ {t['last_row']}행) 가까이의 행 {', '.join(map(str, sorted(loose)))} 의 "
                         f"절차 열에도 글이 있습니다. 절차 줄이면 범위를 넓히고, 아니면 excluded 에 행 번호와 까닭을 적습니다"
                         f"(머리글 행은 head_row 에 적습니다)")
    out.sort(key=lambda x: (x["sheet"], x["row"]))
    keys = [x["step"] for x in out]
    for n, x in enumerate(out, 1):
        x["n"] = n
        x["dup_step"] = keys.count(x["step"]) > 1
    return out, probs


def _flag(rs: list[dict]) -> None:
    for r in rs:
        f = r["flags"] = []
        has = r.pop("has")
        r["state"], bad = _state(r.pop("_applies_raw"), has["applies"], r["result"])
        if bad:
            f.append(bad)
        if r["uncached"]:
            f.append("수식 칸의 계산값이 없음(엑셀에서 열어 저장한 뒤 다시 점검): " + " · ".join(r["uncached"]))
        if r["cont_rows"]:
            f.append("아래 행의 글을 이 절차 줄에 이었음: " + ", ".join(map(str, r["cont_rows"])) + "행")
        if r["state"] == OPEN and not bad:
            f.append("해당 여부 빈칸" if has["applies"] else "수행 결과 빈칸")
        elif r["state"] == DONE:
            if has["result"] and not r["result"]:
                f.append("「해당」 인데 수행 결과 빈칸")
            if has["ref"] and not r["ref"]:
                f.append("수행 위치(조서번호 칸) 빈칸")
            if has["who"] and not r["who"]:
                f.append("수행자 빈칸")
        elif r["state"] == NA and has["result"] and len(r["result"]) < MIN_REASON:
            f.append(f"「해당 없음」 사유가 {MIN_REASON}자 미만")
        r["must"] = True


def view(path: Path, layout: dict) -> dict:
    """에이전트가 판정할 때 읽는 입력. 위치 파일이 어긋나면 Rejected. 범위 문제는 range_problems 에 담는다(판정 받을 때 거부)."""
    path = Path(path)
    wb, raw = _open(path)
    try:
        area, tables = _layout(layout, wb)
        rs, probs = _rows(wb, raw, tables)
        sheets = [s for s in wb.sheetnames if not s.startswith("_")]
    finally:
        wb.close()
        raw.close()
    _flag(rs)
    notes = []
    for t in tables:
        mine = [r for r in rs if r["sheet"] == t["sheet"] and t["first_row"] <= r["row"] <= t["last_row"]]
        for k in ("applies", "ref", "result", "who"):
            if t["cols"][k] and mine and not any(r[k] for r in mine):
                notes.append(f"{t['sheet']} 절차 표의 {k} 열({get_column_letter(t['cols'][k])})이 모든 절차 줄에서 비어 있습니다. 열을 맞게 적었는지 봅니다")
    pts = points(area)
    return {"file": path.name, "path": path, "area": area, "defined": bool(pts), "area_points": pts, "defined_areas": defined_areas(),
            "sheets": sheets, "tables": tables, "rows": rs, "range_problems": probs, "layout_notes": notes, "status": status(path)}


# ---------------------------------------------------------------- 판정 받기
class _Books(R.Books):
    """절차 표를 시트가 아니라 칸 범위로 본다. 같은 시트에 절차 표와 수행 기록이 함께 있는 양식이 있다.
    절차 표와 겹치는 근거는 절차 표로 본다. 표 안의 글에 바깥 빈칸을 붙여 수행 근거로 내는 것을 받지 않는다."""

    def __init__(self, *a, rects: list | None = None, **k):
        super().__init__(*a, **k)
        self.rects = rects or []

    def is_cover(self, tag: str, box: tuple) -> bool:
        c1, r1, c2, r2 = box
        return any(tag == t and c1 <= b and c2 >= a and r1 <= y and r2 >= x for t, a, b, x, y in self.rects)   # 조금이라도 겹치면 절차 표


def _finder(rs: list[dict], part, key) -> dict | None:
    """번호(n) · key(시트!행) · 절차 글(하나뿐일 때)로 절차 줄을 찾는다."""
    if isinstance(key, bool):
        return None
    if isinstance(key, int) or (isinstance(key, str) and key.strip().isdigit()):
        return next((r for r in rs if r["n"] == int(str(key).strip())), None)
    if not isinstance(key, str) or not key.strip():
        return None
    k = key.strip().replace("'", "")
    hit = [r for r in rs if k in (r["key"], r["step"])]
    return hit[0] if len(hit) == 1 else None


def _aliases(also: list | None, path: Path) -> tuple[dict, list[str]]:
    """--with 값(「이름=경로」 또는 경로) → {이름: {"file": 절대 경로}}. 이름은 근거 글에 쓰므로 「:」 「!」 를 받지 않는다."""
    out, probs = {}, []
    for a in also or []:
        name, _, p = str(a).partition("=") if "=" in str(a) and not re.match(r"^[A-Za-z]:[\\/]", str(a)) else ("", "", str(a))
        f = Path(p)
        f = f if f.is_absolute() else (Path(path).parent / f)
        name = (name or f.stem).strip()
        if not f.is_file():
            probs.append(f"함께 준 조서 파일이 없습니다: {a}")
        elif not name or any(ch in name for ch in ":!'") or name == Path(path).name or name in out:
            probs.append(f"함께 준 조서의 이름을 근거에 쓸 수 없습니다(「:」 「!」 없이, 서로 다르게. 「이름=경로」 로 줍니다): {name}")
        else:
            out[name] = {"file": f.resolve().as_posix()}
    return out, probs


def _coverage(cov, pts: list[dict], rs: list[dict], items: list[dict]) -> tuple[dict, list[str]]:
    """대응표 검사. 정의의 절차 번호마다 그 절차를 다루는 절차 줄을 적는다. 조서에 없는 절차는 영역 줄로 남아야 한다."""
    ids = [p["id"] for p in pts]
    if not isinstance(cov, dict):
        return {}, [f"이 영역은 확인 항목 정의가 있습니다. 판정 파일에 coverage(절차 번호 → 그 절차를 다루는 절차 줄)를 적습니다: {' · '.join(ids)}"]
    probs, out, used = [], {}, {}
    for k in sorted(set(cov) - set(ids)):
        probs.append(f"coverage 에 정의에 없는 절차 번호가 있습니다: {k}")
    area_keys = [x["key"] for x in items if x["part"] == AREA and x["verdict"] == "수행 기록 없음"]
    for i in ids:
        v = cov.get(i)
        if not isinstance(v, list):
            probs.append(f"coverage 에 {i} 가 없습니다. 그 절차를 다루는 절차 줄의 번호 목록을 적고, 조서에 없으면 빈 목록 [] 을 적습니다")
            continue
        keys = []
        for k in v:
            row = _finder(rs, PART1, k)
            if row is None:
                probs.append(f"coverage {i}: 절차 표에 없는 줄입니다: {k}")
            elif row["key"] not in keys:
                keys.append(row["key"])
                used.setdefault(row["key"], []).append(i)
        out[i] = keys
        if not v and not any(a == i or a.startswith(i + " ") for a in area_keys):
            probs.append(f"coverage {i} 가 빈 목록입니다. 조서에 그 절차가 없다는 영역 줄(판정 「수행 기록 없음」)을 판정에 넣습니다"
                         f'({{"part": "영역", "key": "{i} <절차 이름>", "verdict": "수행 기록 없음", ...}})')
    for key, who in used.items():
        if len(who) > MAX_IDS_PER_ROW:
            probs.append(f"절차 줄 {key} 하나를 절차 번호 {len(who)}개({' · '.join(who)})에 대었습니다. 줄 하나는 {MAX_IDS_PER_ROW}개까지 댑니다")
    return out, probs


def accept(path: Path, layout: dict, patch: dict, received: Path | None = None, also: list | None = None, now: str | None = None) -> dict:
    """판정을 검사해 조서 옆에 점검표와 기록을 쓴다. 하나라도 어긋나면 Rejected 를 올리고 아무것도 쓰지 않는다."""
    path = Path(path)
    root = path.parent
    v = view(path, layout)
    rs = v["rows"]
    probs = list(v["range_problems"])
    if not rs:
        raise Rejected(probs + ["위치 파일의 범위에 절차 줄이 없습니다"])
    if not isinstance(patch, dict) or not isinstance(patch.get("verdicts"), list):
        raise Rejected(['판정은 {"workpaper": "<조서 파일 이름>", "verdicts": [...]} 꼴입니다'])
    extra = sorted(set(patch) - {"workpaper", "verdicts", "coverage"})
    if extra:
        probs.append(f"맨 위에 쓸 수 없는 항목입니다: {', '.join(extra)}")
    if patch.get("workpaper") != path.name:
        probs.append(f"workpaper 가 {path.name} 이 아닙니다: {patch.get('workpaper')}")
    listed, p2 = _aliases(also, path)
    probs += p2
    rec_dir = Path(received) if received else (root / RECEIVED_DIR if (root / RECEIVED_DIR).is_dir() else None)
    if received and not Path(received).is_dir():
        probs.append(f"받은자료 폴더가 없습니다: {received}")
        rec_dir = None
    rects = [(f"{path.name}:{t['sheet']}", min(c for c in t["cols"].values() if c), max(c for c in t["cols"].values() if c),
              t["first_row"], t["last_row"]) for t in v["tables"]]
    books = _Books(path.name, root, path, listed=listed, received=rec_dir, outside=True, rects=rects,
                   words={**WORDS, "received": rec_dir.name if rec_dir else RECEIVED_DIR})
    seen: set = set()
    items = []
    try:
        for i, item in enumerate(patch["verdicts"]):
            if isinstance(item, dict) and "part" not in item:
                item = {**item, "part": PART1}
            p, rec = R.check_item(item, i, rs, books, seen, finder=_finder)
            probs += p
            if rec:
                items.append(rec)
    finally:
        books.close()
    left = [r for r in rs if (r["part"], r["key"]) not in seen]
    if left:
        probs.append(f"판정이 없는 절차 줄 {len(left)}개: " + " / ".join(f"{r['n']}번 {r['key']}" for r in left))
    probs += R.same_cites(items, path.name)
    cov = {}
    if v["defined"]:
        cov, p3 = _coverage(patch.get("coverage"), v["area_points"], rs, items)
        probs += p3
    elif patch.get("coverage"):
        probs.append(f"영역 {v['area']} 는 확인 항목 정의가 없어 coverage 를 받지 않습니다(정의가 있는 영역: {' · '.join(v['defined_areas']) or '없음'})")
    if probs:
        raise Rejected(probs)

    at = now or _now()
    order = {(r["part"], r["key"]): r["n"] for r in rs}
    items.sort(key=lambda x: (0, 0) if x["part"] == AREA else (1, order[(x["part"], x["key"])]))
    todo = [x for x in items if x["verdict"] not in OK]
    for n, x in enumerate(todo, 1):
        x["n"] = n
    rec_file, sheet_file, _ = _paths(path)
    old = _load(path)
    fixed = R.carry(items, old)
    counts = {"rows": len(rs), "todo": len(todo), "ok": len(items) - len(todo), "skipped": 0, "fixed": fixed,
              "unknown": sum(1 for x in items if x["verdict"] == NO_CITE), "area": sum(1 for x in items if x["part"] == AREA)}
    rec = {"format_version": FORMAT, "no": path.name, "area": v["area"], "defined": v["defined"], "at": at,
           "workpaper_file": path.name, "workpaper_sha256": R.sha(path),
           "deps": {k: R.sha(p) for k, p in sorted(books.deps.items())},
           "layout": layout, "received": rec_dir.resolve().as_posix() if rec_dir else None, "points_sha256": _points_sha(v["area"]),
           "file": sheet_file.name, "counts": counts, "items": items, "skipped": [], "coverage": cov}
    tmp_sheet, tmp_rec = sheet_file.with_name("~" + sheet_file.name), rec_file.with_name("~" + rec_file.name)
    try:                                                # 둘 다 만든 뒤에 바꾼다. 기록을 먼저 바꿔, 끊기면 apply 가 점검표와 기록이 다르다고 멈춘다
        R.write_sheet(tmp_sheet, rec, _notes(rec, v), _hint(rec), title=f"절차 점검표 {path.name}", skipped_head=None,
                      notes_head="점검한 범위(회계사가 확인합니다)")
        tmp_rec.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp_rec, rec_file)
        os.replace(tmp_sheet, sheet_file)
    finally:
        for f in (tmp_sheet, tmp_rec):
            if f.exists():
                f.unlink()
    return rec


def _hint(rec: dict) -> str:
    return (f"대상 조서 {rec['workpaper_file']} · 영역 {rec['area']} · 점검 {rec['at']} · AI 판정(확인 전). 「반영」 칸에 「{PICK}」 를 적은 줄만 "
            f"검토의견 파일에 옮깁니다. 적지 않은 줄은 이 파일에만 남습니다")


def _notes(rec: dict, v: dict) -> list[str]:
    out = []
    for t in v["tables"]:
        cols = " · ".join(f"{k} {get_column_letter(c)}열" for k, c in t["cols"].items() if c)
        out.append(f"절차 표: {t['sheet']} {t['first_row']} ~ {t['last_row']}행({cols}). 범위는 AI 가 정했습니다. 이 범위 밖의 절차는 점검하지 않았습니다")
        for r, why in sorted(t["excluded"].items()):
            out.append(f"범위에서 뺀 행: {t['sheet']} {r}행({why})")
        if t["continued"]:
            out.append(f"윗줄에 이은 행: {t['sheet']} " + ", ".join(map(str, sorted(t["continued"]))) + "행")
    out += v.get("layout_notes") or []
    if rec["defined"]:
        titles = {p["id"]: p["title"] for p in v["area_points"]}
        for i, keys in rec["coverage"].items():
            out.append(f"{i} {titles.get(i, '')}: " + (" · ".join(keys) if keys else "조서에 절차 줄 없음"))
    else:
        out.append(f"영역 {rec['area']} 는 확인 항목 정의가 없습니다. 조서에 적힌 절차 줄만 점검했습니다. 조서에 없는 절차는 보지 못합니다")
    return out


# ---------------------------------------------------------------- 상태 · 골라서 반영
def _load(path: Path) -> dict | None:
    f = _paths(path)[0]
    if not f.is_file():
        return None
    try:
        rec = json.loads(f.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    return rec if isinstance(rec, dict) and rec.get("format_version") == FORMAT and isinstance(rec.get("items"), list) else None


def _points_sha(area: str) -> str:
    """그 영역 확인 항목 정의의 지문. 정의가 바뀌면 다시 점검한다."""
    import hashlib

    return hashlib.sha256(json.dumps(points(area), ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]


def _stale(path: Path, rec: dict) -> list[str]:
    changed = R.stale(Path(path).parent, rec)
    if rec.get("points_sha256") and rec["points_sha256"] != _points_sha(rec["area"]):
        changed.append(f"확인 항목 정의({rec['area']})")
    return changed


def status(path: Path) -> dict:
    """{check(점검 안 함 · 최신 · 조서 바뀜), at, todo, applied, changed}."""
    path = Path(path)
    rec = _load(path)
    if rec is None:
        return {"check": NEVER, "at": None, "todo": None, "applied": None, "changed": []}
    changed = _stale(path, rec)
    return {"check": STALE if changed else FRESH, "at": rec["at"], "todo": rec["counts"]["todo"],
            "applied": sum(1 for x in rec["items"] if x.get("applied")), "changed": changed}


def _human(who) -> str:
    w = (who or "").strip()
    if not w or w.upper().startswith(NOT_HUMAN):
        raise Rejected([f"검토의견에 옮기는 것은 사람만 합니다(--who 에 이름): {who}"])
    return w


def _review_book(f: Path, name: str):
    if f.is_file():
        wb = load_workbook(f)
        ws = wb.worksheets[0]
        if [R.text(ws.cell(REVIEW_HEAD_ROW, c).value) for c in range(1, 6)] != REVIEW_HEAD:
            wb.close()
            raise Rejected([f"검토의견 파일의 머리글이 이 스킬이 만든 것과 다릅니다: {f.name}. 파일을 옮기거나 이름을 바꾼 뒤 다시 합니다"])
        return wb, ws
    wb = Workbook()
    ws = wb.active
    ws.title = "검토의견"
    ws["A1"] = f"검토의견 {name}"
    ws["A1"].font = Font(size=14, bold=True)
    for c, (h, w) in enumerate(zip(REVIEW_HEAD, (6, 60, 60, 40, 10)), 1):
        ws.cell(REVIEW_HEAD_ROW, c, h).font = Font(bold=True)
        ws.column_dimensions[get_column_letter(c)].width = w
    return wb, ws


def apply(path: Path, who: str, picks: list[int] | None = None, now: str | None = None) -> dict:
    """고른 줄만 조서 옆 검토의견 파일에 「열림」 으로 잇는다. picks 를 주면 그 번호를, 주지 않으면 점검표 「반영」 칸이 「예」 인 줄을 옮긴다."""
    path = Path(path)
    who = _human(who)
    rec = _load(path)
    if rec is None:
        raise Rejected([f"{path.name} 의 절차 점검 기록이 없습니다. 먼저 판정을 넣습니다(check)"])
    changed = _stale(path, rec)
    if changed:                                         # 쓰기 전에 본다. 고친 조서의 옛 판정을 검토의견에 넣지 않는다
        raise Rejected([f"점검 뒤에 바뀌었거나 없어진 파일이 있습니다: {' · '.join(changed)}. 점검을 다시 돌린 뒤 반영합니다(rows → check)"])
    rec_file, sheet, review = _paths(path)
    todo = {x["n"]: x for x in rec["items"] if x["n"]}
    if sheet.is_file():                                 # 번호로 골라도 점검표가 기록과 같은지 먼저 본다(쓰기 전)
        wb0 = load_workbook(sheet, data_only=True)
        try:
            R.sheet_rows(wb0[R.SHEET] if R.SHEET in wb0.sheetnames else wb0.worksheets[0], rec)
        finally:
            wb0.close()
    want = set(picks) if picks else R.picks(sheet, rec)
    bad = sorted(want - set(todo))
    if bad:
        raise Rejected([f"점검표 「볼 것」 에 없는 번호입니다: {', '.join(map(str, bad))} (1 ~ {len(todo)})"])
    at = now or _now()
    moved, already = [], []
    if want:
        wb, ws = _review_book(review, path.name)
        for n in sorted(want):
            x = todo[n]
            if x["applied"]:
                already.append(n)
                continue
            tag = R.tag(x)
            used = [r for r in range(REVIEW_FIRST, ws.max_row + 1) if any(R.text(ws.cell(r, c).value) for c in range(2, 6))]
            dup = next((r for r in used if tag in R.text(ws.cell(r, 2).value)), None)
            r = dup or ((used[-1] + 1) if used else REVIEW_FIRST)      # 가운데 빈 줄은 다시 쓰지 않는다. 맨 아래에 잇는다
            op = r - REVIEW_FIRST + 1
            if not dup:                                 # 앞 실행이 검토의견만 쓰고 끊겼으면 두 번 쓰지 않고 기록만 잇는다
                ws.cell(r, 1, op)
                ws.cell(r, 2, f"{x['step']} (근거 {' · '.join(x['cites']) or '없음'}) · 절차 점검 {x['verdict']} · {who} 가 고름 {tag}")
                ws.cell(r, 3, x["missing"])
                ws.cell(r, 5, OPEN_STATE)
            x["applied"] = {"by": who, "at": at, "opinion": op, "sig": R.sig(x)}
            x["prior"] = None
            moved.append(n)
        wb.save(review)
    if moved:
        rec_file.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    if sheet.is_file():                                 # 점검표의 「반영 결과」 칸을 기록과 맞춘다. 앞 실행이 기록만 쓰고 끊겼어도 여기서 채운다
        wb2 = load_workbook(sheet)
        ws2 = wb2[R.SHEET]
        dirty = False
        for n, r in R.sheet_rows(ws2, rec).items():
            want_text = R.applied_text(todo[n]["applied"], todo[n].get("prior"))
            if todo[n]["applied"] and (R.text(ws2.cell(r, 7).value) != want_text or R.text(ws2.cell(r, 6).value) != PICK):
                ws2.cell(r, 6, PICK)                    # 회계사가 적은 「예」 는 그대로 둔다
                ws2.cell(r, 7, want_text)
                dirty = True
        if dirty:
            wb2.save(sheet)
        wb2.close()
    return {"file": path.name, "review": review.name, "moved": moved, "already": already,
            "left": sorted(set(todo) - want - {n for n, x in todo.items() if x["applied"]})}
