"""회계사 입력 되읽기(계약 14.2). `ctax wp` 가 조서.xlsx 를 다시 쓰기 전에 노란 칸 값을 읽는다.

1. 숨은 시트 `_입력` 의 key ↔ 칸 표로 칸마다 지금 값을 읽는다.
2. 엔진 기본값(그 표의 default)과 다른 칸만 회계사 값으로 본다. 같으면(손대지 않았거나 되돌렸으면) 회계사 값을 지운다.
3. `_색인/조서입력.json` 에 모은다: {"cells": [{"paper", "key", "value", "at", "from": "조서.xlsx", "by", "memo"}],
                                     "notes": [{"paper", "key", "memo", "by", "at"}]}.
   지난 실행에 모은 값 중 이번 엑셀 `_입력` 표에 없는 key(줄이 장부에서 사라진 경우 등)는 그대로 둔다.
4. 누가 · 언제 · 메모(10-29): by 는 그 조서 머리의 「작성」(없으면 「검토」) 칸, 없으면 엑셀 파일의 마지막 저장한 사람,
   그것도 없으면 부른 쪽(CTAX_CALLER). at 은 값이나 메모가 바뀐 것을 본 때. 메모는 노란 칸의 엑셀 메모(comment)나
   「회계사 답」 시트의 메모 칸에서 읽는다(엔진이 붙인 「회계사 답:」 · 「작년 답:」 줄은 뺀다). 기본값 그대로인 칸에 메모만 있으면
   cells 가 아니라 notes 에 둔다(기본값이 나중에 바뀌어도 옛 값을 회계사 값으로 묶지 않으려는 것). 맥락(papers[].context)의 by · at 과 같은 꼴이다.

칸을 가리는 것은 칸 주소가 아니라 key 다. 시트 모양이 바뀌어도 key 가 같으면 값이 따라간다.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from ..case import Case
from .model import normalize
from .sheet import INPUT_SHEET

INPUT_JSON = "조서입력.json"


HEAD_KEYS = ("작성", "작성일", "검토", "검토일")      # 조서 머리 칸(누가 · 언제 작성 · 검토했는지)
ANSWER_SHEET = "회계사 답"
AUTO_LINES = ("회계사 답:", "작년 답:")              # 엔진이 엑셀 메모에 붙이는 줄
MEMO_PREFIX = "메모:"


def comment_memo(comment) -> str:
    """노란 칸 엑셀 메모에서 회계사가 쓴 글. 엔진이 붙인 줄과 엑셀이 붙이는 「작성자:」 머리를 뺀다."""
    if comment is None or not comment.text:
        return ""
    text = str(comment.text).replace("\r", "")
    author = str(comment.author or "").strip()
    if author and author != "ctax" and text.startswith(f"{author}:"):
        text = text[len(author) + 1:]
    out = []
    for line in text.split("\n"):
        t = line.strip()
        if not t or t.startswith(AUTO_LINES):
            continue
        out.append(t[len(MEMO_PREFIX):].strip() if t.startswith(MEMO_PREFIX) else t)
    return "\n".join(out).strip()


def read_workbook(path: Path) -> tuple[list[dict], str]:
    """조서.xlsx 의 노란 칸 [{paper, key, value, default, kind, memo_comment, memo_sheet, by}] 과 문제(읽지 못했으면 까닭)."""
    if not path.exists():
        return [], ""
    try:
        from openpyxl import load_workbook
        wb = load_workbook(path)
    except Exception as e:  # 열려 있거나 깨진 파일
        return [], f"{path.name} 을 읽지 못했습니다({type(e).__name__})"
    if INPUT_SHEET not in wb.sheetnames:
        return [], f"{path.name} 에 {INPUT_SHEET} 시트가 없습니다(1회차 조서). 노란 칸을 읽지 않고 새로 씁니다"
    out = []
    # 「회계사 답」 행을 (시트, 칸, 항목)으로 찾는다. 회계사가 줄을 정렬하거나 끼워도 메모 · 근거가 제 칸에 붙게(11-01)
    answer_rows: dict[tuple, int] = {}
    if ANSWER_SHEET in wb.sheetnames:
        for i, ar in enumerate(wb[ANSWER_SHEET].iter_rows(values_only=True), start=1):
            if ar and len(ar) >= 3 and ar[0] and ar[1] and ar[2]:
                answer_rows.setdefault((str(ar[0]), str(ar[1]), str(ar[2])), i)
    for row in wb[INPUT_SHEET].iter_rows(min_row=2, values_only=True):
        if not row or not row[0] or not row[1]:
            continue
        paper, key, sheet, cell, default, kind, memo_cell, basis_cell = (list(row) + [None] * 8)[:8]
        kind = kind or "text"
        if sheet not in wb.sheetnames:
            continue
        c = wb[sheet][cell]
        value = c.value
        memo_sheet = basis_sheet = None
        at_row = answer_rows.get((str(sheet), str(cell), str(key)))
        if at_row and memo_cell:                       # 행을 못 찾으면(회계사가 지움) 지난번 메모 · 근거를 둔다
            v = wb[ANSWER_SHEET].cell(row=at_row, column=9).value
            memo_sheet = "" if v is None else str(v).strip()
        if at_row and basis_cell:
            v = wb[ANSWER_SHEET].cell(row=at_row, column=10).value
            basis_sheet = "" if v is None else str(v).strip()
        if isinstance(value, str) and value.startswith("="):
            continue   # 회계사가 수식을 넣은 칸은 값을 알 수 없어 읽지 않는다
        out.append({"paper": str(paper), "key": str(key), "value": normalize(value, kind),
                    "default": normalize(default, kind), "kind": kind,
                    "memo_comment": comment_memo(c.comment), "memo_sheet": memo_sheet, "basis_sheet": basis_sheet})
    saver = str(wb.properties.lastModifiedBy or "").strip()
    saver = "" if saver.lower() in ("openpyxl", "") else saver
    heads: dict[str, str] = {}
    for r in out:
        if r["key"] in ("작성", "검토") and r["value"] and not heads.get(r["paper"]):
            heads[r["paper"]] = str(r["value"])
    for r in out:
        r["by"] = heads.get(r["paper"]) or saver
    return out, ""


def _memo(r: dict, prev: str) -> str:
    """이번 엑셀의 메모. 「회계사 답」 시트 칸과 엑셀 메모 가운데 지난번과 달라진 쪽, 둘 다 그대로면 지난번 메모."""
    sheet, comment = r.get("memo_sheet"), r.get("memo_comment") or ""
    if sheet is not None and sheet != prev:
        return sheet
    if comment != prev and (comment or sheet is None):
        return comment
    return prev


def collect(case: Case, xlsx: Path) -> tuple[dict, list[str]]:
    """조서.xlsx 와 지난 조서입력.json 을 합쳐 조서입력.json 을 쓰고 {(paper, key): value} 를 돌려준다."""
    from .. import runlog

    old = case.read_json(INPUT_JSON) if case.has(INPUT_JSON) else {"cells": []}
    cells = {(c["paper"], c["key"]): c for c in old.get("cells", []) if c.get("paper") and c.get("key")}
    notes = {(n["paper"], n["key"]): n for n in old.get("notes", []) or [] if n.get("paper") and n.get("key")}
    rows, problem = read_workbook(xlsx)
    problems = [problem] if problem else []
    now = datetime.now().isoformat(timespec="seconds")
    caller = runlog.caller()
    for r in rows:
        k = (r["paper"], r["key"])
        prev = cells.get(k)
        by = r.get("by") or caller
        if r["value"] == r["default"]:
            cells.pop(k, None)
            had = notes.get(k) or (prev if prev and (prev.get("memo") or prev.get("basis")) else None) or {}
            memo = _memo(r, str(had.get("memo") or ""))
            # 기본값 그대로인 칸의 근거도 남긴다(원본과 맞춰 본 기록, 11-01). 시트에 칸이 없던 옛 조서면 지난번 근거
            basis = r["basis_sheet"] if r.get("basis_sheet") is not None else str(had.get("basis") or "")
            if not memo and not basis:
                notes.pop(k, None)
            elif memo != had.get("memo") or basis != str(had.get("basis") or "") or k not in notes:
                same = memo == had.get("memo") and basis == str(had.get("basis") or "")
                notes[k] = {"paper": r["paper"], "key": r["key"], "memo": memo,
                            "by": had.get("by", by) if same else by, "at": had.get("at", now) if same else now,
                            **({"basis": basis} if basis else {})}
            continue
        memo = _memo(r, str((prev or {}).get("memo") or ""))
        # 근거(파일 · 쪽): 「회계사 답」 시트 근거 칸. 시트에 칸이 없던 옛 조서면 지난번 근거(11-01 PBC 대조)
        basis = r["basis_sheet"] if r.get("basis_sheet") is not None else str((prev or {}).get("basis") or "")
        if prev and prev.get("value") == r["value"] and str(prev.get("memo") or "") == memo \
                and str(prev.get("basis") or "") == basis:
            continue
        notes.pop(k, None)
        cells[k] = {"paper": r["paper"], "key": r["key"], "value": r["value"], "at": now, "from": "조서.xlsx", "by": by,
                    **({"memo": memo} if memo else {}), **({"basis": basis} if basis else {})}
    data = {"cells": sorted(cells.values(), key=lambda c: (c["paper"], c["key"]))}
    if notes:
        data["notes"] = sorted(notes.values(), key=lambda n: (n["paper"], n["key"]))
    if data["cells"] or notes or case.has(INPUT_JSON):
        case.write_json(INPUT_JSON, data)
    return {(c["paper"], c["key"]): c["value"] for c in data["cells"]}, problems


def answers(case: Case) -> dict:
    """{(paper, key): {"value"?, "by", "at", "memo", "from"}} 조서를 다시 쓸 때 엑셀 메모 · 「회계사 답」 시트를 채우는 값."""
    try:
        data = case.read_json(INPUT_JSON) if case.has(INPUT_JSON) else {}
    except ValueError:
        return {}
    out = {}
    for n in data.get("notes") or []:
        if n.get("paper") and n.get("key"):
            out[(n["paper"], n["key"])] = {"by": n.get("by", ""), "at": n.get("at", ""), "memo": n.get("memo", ""), "from": "메모",
                                           "basis": n.get("basis", "")}
    for c in data.get("cells") or []:
        if c.get("paper") and c.get("key"):
            out[(c["paper"], c["key"])] = {"value": c.get("value"), "by": c.get("by", ""), "at": c.get("at", ""),
                                           "memo": c.get("memo", ""), "from": c.get("from", ""), "basis": c.get("basis", "")}
    return out
