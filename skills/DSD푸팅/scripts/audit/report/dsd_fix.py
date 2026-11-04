"""DSD 고침(2026-11-04). 검토 화면에서 「수정」 을 누르면 dsd 도 바뀌게 한다.

검토 화면(HTML)에서 「수정」 을 누른 고침을 dsd 에 쓴다. 원본 dsd 는 건드리지 않고 결과 폴더의 수정판(<이름>_수정판.dsd)에 쓴다.

  고침 한 건(수정.json 의 items)
    {"kind": "num", "table": "주석5-1", "r": 2, "c": 1, "old": 1137899672, "new": 1227144486, "check": "<검증 id>", "why": "…"}
    {"kind": "text", "seg": "S246", "old": "기록하고있으며,", "new": "기록하고 있으며,", "ctx": "<원문 발췌>", "where": "…"}

  apply(src, items, out) -> {"path", "done", "failed", "lost_format"}

숫자 칸은 검증용 판독(dsd_grid)의 표 · 줄 · 열을 원고 판독(dsd_draft)의 요소로 찾는다. 두 판독은 표 번호를 다르게 센다(테두리 없는 표,
틀 표). 그래서 같은 시트(주석N · 재무상태표 …) 안에서 「값이 같고 줄 이름이 같은 숫자 칸」 을 찾고, 여럿이면 줄 안 숫자 칸 차례로 가른다.
못 찾거나 둘 이상 남으면 고치지 않고 failed 에 이유를 적는다. 숫자는 원문 꼴(괄호 · △ 음수, 쉼표, 「-」 0)로 다시 쓴다(dsd_draft.format_num).

글 고침은 old 를 원고 글(문단 · 칸)에서 찾는다. 문서 전체에서 한 곳이면 고친다. 여럿이면 원문 발췌(ctx)가 든 요소로 좁히고, 그래도 여럿이면
고치지 않는다. 바뀐 곳이 SPAN 조각 안이면 서식을 남긴다(dsd_build.text_edit).

다 쓴 뒤 수정판을 다시 판독해 숫자 칸을 원본과 견준다. 고친 칸만 새 값이고 다른 숫자 칸은 그대로여야 한다. 어긋나면 수정판을 쓰지 않는다.
제출 파일로 쓰기 전에는 DART 편집기에서 열어 확인한다(원고판과 같다).
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import tempfile
import zipfile
from pathlib import Path

from .base import norm
from . import dsd_draft, dsd_grid
from .dsd_build import text_edit
from .dsd_source import Source

STAMP = "수정판"
LOG = "수정기록.json"
_ARROW = re.compile(r"^\s*(.+?)\s*→\s*(.+?)\s*$", re.S)
_ASK = ("확인해", "확인한다", "맞춘다", "어느 쪽", "검토한다", "추가한다", "적는다", "기재한다", "넣는다", "뺀다", "반영한다", "고치지 않", "그대로 둔", "그대로 두")
# 바꿀 글이 아니라 메모로 끝난 고칠 안(「고치지 않는다(주주 이름은 그대로 둔다)」). dsd 문장은 「~습니다」 로 끝나므로 평서 「~다」 로 끝나면 메모로 본다
_NOTE_END = re.compile(r"(?<!니)(?:는다|한다|둔다|된다|본다|이다|있다|없다)\s*[.)」]*\s*$")


def fixed_name(src: Path) -> str:
    return f"{Path(src).stem}_수정판.dsd"


def text_pair(f: dict) -> tuple[str, str] | None:
    """문장 검토 지적 하나를 (찾을 글, 바꿀 글)로. 엔진은 고칠 글을 「A → B」 로, AI 는 quote 를 fix 로 바꾼다.
    고칠 글이 지시(「어느 쪽이 맞는지 … 확인해 맞춘다」)면 None. 화면이 「수정」 단추를 낼지 정하는 데도 쓴다."""
    fix = (f.get("fix") or "").strip()
    if not fix:
        return None
    m = _ARROW.match(fix)
    arrow = bool(m and "\n" not in m.group(1))
    if arrow:
        old, new = m.group(1), m.group(2)
    else:
        old, new = (f.get("quote") or "").strip(), fix
        if "…" in old:                                     # 엔진 발췌(앞뒤 40자)는 찾을 글로 쓰지 않는다
            return None
    if any(w in new for w in _ASK) or (not arrow and _NOTE_END.search(new)):   # 고칠 글이 아니라 할 일 · 메모를 적은 것
        return None
    if any(ch in new and ch not in old for ch in "÷×="):     # 「29,411주(총발행금액 ÷ 발행가액)」 처럼 계산 근거가 붙은 안
        return None
    old, new = old.strip("…").strip(), new.strip("…").strip()
    if not old or old == new or len(old) > 400:
        return None
    quote = (f.get("quote") or "").replace("…", "")
    if quote and old not in quote:                         # 엔진이 고칠 글을 다듬어 적은 것(감사기간 「~ 2026년 2월 12일」)은 원문 글이 아니다
        return None
    return old, new


# ---------------------------------------------------------------- 칸 찾기
def _sheet_keys(tid: str) -> list[str]:
    m = re.match(r"^주석(\d+)", tid)
    if m:
        return [f"주석{m.group(1)}"]
    base = tid.split("-")[0]
    return [base]


def _row_label(ln) -> str:
    out = []
    for c in ln.cells:
        if c.covered or c.num is not None:
            continue
        t = norm(c.text)
        if t:
            out.append(t)
    return "".join(out)


def _num_cells(ln) -> list:
    return [c for c in ln.cells if not c.covered and c.num is not None and c.loc is not None]


def _same(a, b) -> bool:
    return a is not None and b is not None and abs(float(a) - float(b)) < 0.5e-6 * max(1.0, abs(float(a)))


def find_cell(d: dsd_draft.Draft, t: dsd_grid.Table, r: int, c: int):
    """검증용 판독의 칸(t, r, c)을 원고 판독의 Cell 로. (Cell, None) 또는 (None, 이유)."""
    old = t.nums[r][c] if 0 <= r < len(t.nums) and 0 <= c < len(t.nums[r]) else None
    if old is None:
        return None, "숫자 칸이 아닙니다"
    label = norm((t.labels or [x[0] for x in t.rows])[r] or "")
    row_nums = [k for k, v in enumerate(t.nums[r]) if v is not None]
    ordinal = row_nums.index(c) if c in row_nums else -1
    sheets = [s for s in d.sheets if s.key in _sheet_keys(t.id)] or list(d.sheets)
    hits = []
    for s in sheets:
        for ln in s.lines:
            if ln.kind not in ("줄", "머리"):
                continue
            nums = _num_cells(ln)
            for k, cell in enumerate(nums):
                if _same(cell.num, old):
                    hits.append((ln, k, cell, len(nums)))
    if not hits:
        return None, f"원문에서 값 {old:,g} 인 칸을 찾지 못했습니다"
    if len(hits) > 1 and label:
        by_label = [h for h in hits if _row_label(h[0]) == label] or [h for h in hits if label and (label in _row_label(h[0]) or _row_label(h[0]) in label)]
        hits = by_label or hits
    if len(hits) > 1 and ordinal >= 0:
        by_pos = [h for h in hits if h[1] == ordinal and h[3] == len(row_nums)] or [h for h in hits if h[1] == ordinal]
        hits = by_pos or hits
    if len(hits) > 1:
        return None, f"값 {old:,g} · 줄 「{label}」 인 칸이 원문에 {len(hits)}곳이라 고를 수 없습니다"
    return hits[0][2], None


def _text_nodes(d: dsd_draft.Draft) -> list:
    """원고의 글 요소(문단 · 제목 · 글자 칸). (Cell, 시트 key)."""
    out = []
    for s in d.sheets:
        for ln in s.lines:
            if ln.kind in ("표", "글 표", "표끝"):
                continue
            for c in ln.cells:
                if c.loc is not None and not c.covered and c.num is None and c.text:
                    out.append((c, s.key))
    return out


def _squash(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def find_text(d: dsd_draft.Draft, old: str, ctx: str = ""):
    """글 old 가 든 요소 하나. (Cell, None) 또는 (None, 이유)."""
    hits = [(c, k) for c, k in _text_nodes(d) if old in c.text]
    if not hits:
        return None, f"원문에서 「{old[:40]}」 를 찾지 못했습니다"
    if len(hits) > 1 and ctx:
        pieces = [p for p in re.split(r"…+", ctx) if len(_squash(p)) >= 6]
        narrowed = [h for h in hits if pieces and all(_squash(p) in _squash(h[0].text) for p in pieces)]
        hits = narrowed or hits
    if len(hits) > 1:
        return None, f"「{old[:40]}」 가 원문에 {len(hits)}곳이라 고를 수 없습니다"
    return hits[0][0], None


# ---------------------------------------------------------------- 쓰기
def _raw(src: Path) -> tuple[bytes, bytes]:
    with zipfile.ZipFile(src) as z:
        name = next((n for n in z.namelist() if n.lower().endswith("contents.xml")), None)
        if name is None:
            raise ValueError(f"dsd 안에 contents.xml 이 없습니다: {src}")
        meta = next((n for n in z.namelist() if n.lower().endswith("meta.xml")), None)
        return z.read(name), (z.read(meta) if meta else b"")


def _one(raw: bytes, grid: dsd_grid.Doc, item: dict) -> tuple[bytes | None, str, bool]:
    """고침 한 건을 contents.xml 에. (새 바이트 | None, 이유, 서식 잃음)."""
    d = dsd_draft.from_raw(raw)
    src = Source(raw)
    if item.get("kind") == "num":
        t = grid.table(item.get("table", ""))
        if t is None:
            return None, f"표 {item.get('table')} 가 없습니다", False
        if t.kind == "문장":
            return None, "주석 문장 속 금액은 숫자 칸이 아닙니다. 문장 고침으로 고친다", False
        try:
            r, c = int(item["r"]), int(item["c"])
            new = float(item["new"])
        except (KeyError, TypeError, ValueError):
            return None, "줄 · 열 · 새 값이 숫자가 아닙니다", False
        cell, why = find_cell(d, t, r, c)
        if cell is None:
            return None, why, False
        fmt = cell.fmt or {}
        if new == 0 and not fmt.get("zero"):
            new_text = "-"                                 # dsd 는 0 을 「-」 로 적는다
        else:
            new_text = dsd_draft.format_num(int(new) if new.is_integer() else new, fmt)
        edits, lost = text_edit(src, src.nodes[cell.loc], new_text)
        if not edits:
            return None, "이미 그 값입니다", False
        return src.apply(edits), "", lost
    if item.get("kind") == "text":
        old, new = item.get("old") or "", item.get("new")
        if not old or new is None:
            return None, "찾을 글 · 바꿀 글이 없습니다", False
        if item.get("all"):                                 # 오타 · 띄어쓰기: 같은 글이 든 곳을 모두 고친다
            cells = [c for c, _ in _text_nodes(d) if old in c.text]
            if not cells:
                return None, f"원문에서 「{old[:40]}」 를 찾지 못했습니다", False
        else:
            cell, why = find_text(d, old, item.get("ctx") or "")
            if cell is None:
                return None, why, False
            cells = [cell]
        edits, lost = [], False
        for cell in cells:
            e, l = text_edit(src, src.nodes[cell.loc], cell.text.replace(old, new) if item.get("all") else cell.text.replace(old, new, 1))
            edits += e
            lost = lost or l
        if not edits:
            return None, "바뀐 글이 없습니다", False
        return src.apply(edits), "", lost
    return None, f"고침 종류를 모릅니다: {item.get('kind')}", False


def _read_grid(src: Path, raw: bytes) -> dsd_grid.Doc:
    with tempfile.TemporaryDirectory() as tmp:
        return dsd_grid.read_grid(_write(src, Path(tmp) / "x.dsd", raw, b""))


def _num_map(g: dsd_grid.Doc) -> dict:
    return {(t.id, r, c): v for t in g.tables() if t.kind != "문장" for r, row in enumerate(t.nums) for c, v in enumerate(row) if v is not None}


def apply(src: Path, items: list[dict], out: Path | None = None) -> dict:
    """원본 dsd 에 고침들을 차례로 쓴다. 성공한 고침만 남기고, 끝에 숫자 칸을 원본과 견준다. out 이 None 이면 쓰지 않고 결과만."""
    src = Path(src)
    raw0, _ = _raw(src)
    raw = raw0
    grid0 = dsd_grid.read_grid(src)
    done, failed, lost_fmt = [], [], []
    for it in items:
        new_raw, why, lost = _one(raw, grid0, it)
        if new_raw is None:
            failed.append({**it, "why": why})
            continue
        raw = new_raw
        done.append(it)
        if lost:
            lost_fmt.append(it)
    problems = []
    if done:
        g1 = _read_grid(src, raw)
        want = {}
        for it in done:
            if it.get("kind") == "num":
                want[(it["table"], int(it["r"]), int(it["c"]))] = float(it["new"])
        a, b = _num_map(grid0), _num_map(g1)
        for k in set(a) | set(b):
            if k in want:
                if not _same(b.get(k), want[k]):
                    problems.append(f"{k[0]} {k[1]}줄 {k[2]}열: 새 값 {want[k]:,g} 이 아니라 {b.get(k)}")
            elif not _same(a.get(k), b.get(k)) and not (a.get(k) is None and b.get(k) is None):
                problems.append(f"{k[0]} {k[1]}줄 {k[2]}열: 고치지 않은 칸이 {a.get(k)} → {b.get(k)} 로 바뀜")
    res = {"path": None, "done": done, "failed": failed, "lost_format": lost_fmt, "problems": problems[:20], "same_bytes": raw == raw0}
    if problems:
        res["failed"] = failed + [{**it, "why": "수정판을 다시 읽어 견줘 보니 다른 칸도 바뀌어 쓰지 않았다"} for it in done]
        res["done"] = []
        return res
    if out is not None and done:
        stamp = json.dumps({STAMP: len(done), "바탕": hashlib.sha256(src.read_bytes()).hexdigest()}, ensure_ascii=False).encode("utf-8")
        res["path"] = _write(src, Path(out), raw, stamp)
    return res


def _write(src: Path, out: Path, contents: bytes, comment: bytes) -> Path:
    """원본 zip 의 항목(그림 · meta.xml 등)을 그대로 두고 contents.xml 만 바꿔 쓴다."""
    out.parent.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            data = contents if info.filename.lower().endswith("contents.xml") else zin.read(info.filename)
            zout.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED)
        zout.comment = comment
    out.write_bytes(buf.getvalue())
    return out


def stamp_of(path: Path) -> dict:
    """수정판이면 {"수정판": 고침 수, "바탕": 원본 sha256}. 아니면 빈 dict."""
    try:
        with zipfile.ZipFile(path) as z:
            d = json.loads(z.comment.decode("utf-8")) if z.comment else {}
        return d if STAMP in d else {}
    except (zipfile.BadZipFile, ValueError, OSError):
        return {}


# ---------------------------------------------------------------- 수정 기록(검토 화면 서버가 쓴다)
def load_log(folder: Path) -> dict:
    p = Path(folder) / LOG
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {"original": "", "batches": []}


def save_log(folder: Path, log: dict) -> None:
    (Path(folder) / LOG).write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")


def all_items(log: dict) -> list[dict]:
    return [it for b in log.get("batches", []) for it in b.get("items", [])]


def rebuild(original: Path, folder: Path, log: dict) -> dict:
    """수정 기록 전부를 원본에 다시 써서 수정판을 만든다. 고침이 하나도 없으면 수정판을 지운다."""
    out = Path(folder) / fixed_name(original)
    items = all_items(log)
    if not items:
        if out.exists():
            out.unlink()
        return {"path": None, "done": [], "failed": [], "lost_format": [], "problems": []}
    return apply(original, items, out)
