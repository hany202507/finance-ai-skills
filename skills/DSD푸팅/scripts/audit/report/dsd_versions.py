"""DSD 판 비교(2026-10-26, DSD 네 기능 설계 3.4 의 D). `python -m audit dsd diff <옛 판> <새 판>`.

회사가 v2 를 v3 로 고쳐 올 때 무엇이 더해지고 빠지고 바뀌었는지를 엑셀 하나로 낸다. 푸팅(`dsd foot --prev`)을 돌리지 않고 판만 견준다.

견주는 부분: 표지 · 감사보고서(검토보고서) · 재무제표 · 주석 · 외부감사 실시내용 · 그 밖의 절. 재무제표와 주석은 검증용 판독(dsd_grid)을,
그 밖의 절은 dsd._Reader 블록을 쓴다. 「주석N-문장」 표(문단 속 금액을 모은 표)는 견주지 않는다(문단 바뀜으로 한 번만 센다).

짝 맞추기는 dsd_compare 의 함수를 그대로 쓰고 아래를 더했다(foot --prev 의 「바뀐 곳」 은 그대로다).
  부분    주석 번호가 달라도 제목이 비슷하면 짝(번호가 밀리고 제목도 조금 바뀐 주석). 번호 바뀜 · 제목 바뀜 · 옮김을 적는다
  표      짝 없는 표끼리 숫자로 이어 「나뉨 · 합침」(dsd_compare.match_numbers). 금액만으로 일대일 짝은 짓지 않는다
  줄      이름이 같은 줄이 여럿이면 위 묶음 머리(숫자 없는 줄) 이름을 붙여 가른다. 이름 바뀜 · 옮김을 적는다
  열      새 열 · 없어진 열 · 머리줄 글자 바뀜
  문단    같은 문단 → 바뀐 구간 안에서 글자 비율이 가장 높은 짝 → 순서를 보지 않고 같은 글 · 비슷한 글(옮김)

0건은 「판독 값이 같다」 는 뜻이다. 빈칸 · 「-」 · 0 을 같게 보고 서식 · 줄바꿈은 보지 않는다.
"""
from __future__ import annotations

import hashlib
import json
import re
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter
from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

from .base import norm
from . import dsd, dsd_compare, dsd_grid
from .dsd_grid import Doc, Part, Table

SECTIONS = ("SECTION-1", "SECTION-2", "SECTION-3")
KINDS = ("추가", "삭제", "변경", "옮김", "나뉨", "합침")


@dataclass
class Change:
    kind: str                 # 추가 · 삭제 · 변경 · 옮김 · 나뉨 · 합침
    unit: str                 # 부분 · 제목 · 번호 · 표 · 열 · 머리줄 · 줄 · 칸 · 문단
    part: str                 # 새 판 부분(없어진 부분이면 옛 판 부분)
    where: str                # 「주석5-1 보통예금 · 당기말」
    old: object = ""
    new: object = ""
    diff: float | None = None
    memo: str = ""
    anchor: tuple | None = None       # (부분, 항목 열쇠, 줄, 열). 항목 열쇠는 ("n", 새 항목 번호) 나 ("o", 옛 항목 번호), 줄 -1 은 머리줄

    @property
    def numeric(self) -> bool:
        return self.unit == "칸" and self.diff is not None


@dataclass
class PartDiff:
    new: Part | None
    old: Part | None
    paras: dict = field(default_factory=dict)        # 새 항목 번호 → 옛 항목 번호(문단)
    tables: dict = field(default_factory=dict)       # 새 항목 번호 → (옛 항목 번호, {새 줄: 옛 줄}, {새 열: 옛 열})
    moved: set = field(default_factory=set)          # 옮긴 새 항목 번호
    moved_rows: dict = field(default_factory=dict)   # 새 항목 번호 → 옮긴 새 줄
    changes: list = field(default_factory=list)

    @property
    def key(self) -> str:
        return (self.new or self.old).key


@dataclass
class Leftover:
    """같이 고칠 곳 후보(2026-11-04): 새 판에서 고친 옛 값이 옛 판의 다른 곳에도 있었는데 새 판에서 그곳은 그대로 남은 것."""
    part: str                 # 남은 곳의 새 판 부분
    unit: str                 # 칸 · 문단
    where: str                # 남은 곳 「주석36-3 제1회 교환사채 · 발행될 보통주식수」 · 「주석26 문단」
    value: float              # 그대로 남은 옛 값
    changed: str              # 고친 곳 「주석22-3 교환대상 주식수(*2) · 제1회 무기명식 사모 교환사채」
    new_value: float | None   # 고친 곳의 새 값(문단 숫자를 고친 것이면 None)
    text: str = ""            # 남은 곳이 문단이면 그 숫자 앞뒤 글
    anchor: tuple | None = None


@dataclass
class Result:
    old: Doc
    new: Doc
    parts: list                                      # [PartDiff] 새 판 순서, 없어진 부분은 옛 판에서 그 앞 부분의 짝 뒤에
    leftovers: list = field(default_factory=list)    # [Leftover] 같이 고칠 곳 후보

    @property
    def changes(self) -> list[Change]:
        return [c for p in self.parts for c in p.changes]

    def count(self) -> Counter:
        return Counter(c.kind for c in self.changes)


# ---------------------------------------------------------------- 읽기: 재무제표 · 주석 밖의 절
def _root(path: Path):
    path = Path(path)
    if path.suffix.lower() == ".xml":
        return ET.fromstring(dsd.lenient_xml(path.read_bytes()))
    with zipfile.ZipFile(path) as z:
        name = next((n for n in z.namelist() if n.lower().endswith("contents.xml")), None)
        if name is None:
            raise ValueError(f"dsd 안에 contents.xml 이 없습니다: {path}")
        return ET.fromstring(z.read(name))


def _plain_table(tid: str, rows: list[list[str]]) -> Table:
    w = max((len(r) for r in rows), default=0)
    rows = [list(r) + [""] * (w - len(r)) for r in rows]
    header, body = (rows[0], rows[1:]) if rows else ([], [])
    nums = [[None] + [dsd_grid.to_num(c) for c in r[1:]] for r in body]
    return Table(tid, "", 1, header, body, nums)


def _fs_title(title: str) -> bool:
    return dsd.part_of(title) in ("(첨부) 재무제표", "주석") or dsd_grid.section_of(title) in (dsd_grid.FS, dsd_grid.NOTES)


def _lines(elems, key: str, title: str) -> Part:
    """문단과 표의 줄을 한 줄씩 문단으로 둔다(「제 5 기」 「2025년 01월 01일 부터」). 표지 · 재무제표 표지 · 주석 머리 · 정정신고."""
    items = []
    for e in elems:
        for c in e.iter():
            if c.tag in ("P", "COVER-TITLE"):
                t = dsd._text(c)
                if t:
                    items.append(("p", t))
            elif c.tag == "TR":
                t = " ".join(x for x in (dsd._text(k) for k in c if k.tag in dsd_grid.CELLS) if x)
                if t:
                    items.append(("p", t))
    return Part(key, title, items)


_STATEMENT = re.compile(r"재무상태표|대차대조표|손익계산서|자본변동표|현금흐름표|이익잉여금처분|결손금처리")
_NOTE_HEAD = re.compile(r"^\s*\d+\s*[.)]")


def _front(sec, stop) -> list:
    """절 첫머리: 제목 뒤부터 stop 이 참인 첫 요소 앞까지(재무제표 절의 표지, 주석 절의 회사명 · 기간 표)."""
    out = []
    for c in sec:
        if c.tag == "TITLE" or c.tag in ("WARNING", "PGBRK", "COMMENT"):
            continue
        if c.tag in SECTIONS or c.tag in ("INSERTION", "LIBRARY", "PART") or stop(c):
            break
        out.append(c)
    return out


def _fs_stop(c) -> bool:
    if c.tag == "TABLE-GROUP" and not (c.get("ACLASS") or "").upper().startswith("COVER"):
        return True
    return bool(_STATEMENT.search(norm("".join(c.itertext()))))


def _note_stop(c) -> bool:
    return c.tag in ("P", "TITLE") and bool(_NOTE_HEAD.match(dsd._text(c)))


def _without_sections(e):
    """안에 든 절(INSERTION · LIBRARY 속 절까지)을 뺀 사본. 안에 든 절은 따로 부분이 된다."""
    out = ET.Element(e.tag, e.attrib)
    out.text = e.text
    for k in e:
        if k.tag in SECTIONS or k.tag == "TITLE":
            continue
        out.append(_without_sections(k) if k.tag in ("INSERTION", "LIBRARY", "PART") else k)
    return out


def _section_part(e, title: str, key: str) -> Part:
    r = dsd._Reader()
    p = dsd.part_of(title)
    r.part = "감사보고서" if (p == "감사보고서" or "검토보고서" in norm(title)) else (p or title)
    r.walk(_without_sections(e))
    items, k = [], 0
    for b in r.out:
        if b[0] == "table":
            k += 1
            items.append(("t", _plain_table(f"{key}-{k}", b[1])))
        elif b[0] == "cap" and len(b) == 3:
            continue
        elif b[0] in ("h", "p", "cap"):
            items.append(("p", b[2] if b[0] == "h" else b[1]))
    return Part(key, title, items)


def _is_notes(title: str) -> bool:
    return dsd.part_of(title) == "주석" or dsd_grid.section_of(title) == dsd_grid.NOTES


def _layout(root) -> list:
    """BODY 의 차례: 정정신고 · 표지 · 그 밖의 절(Part)과 재무제표 · 주석이 들어갈 곳({"cover": 재무제표 표지, "notes": 주석 머리})."""
    out, seen = [], Counter()
    grid: dict = {}

    def add_notes_head(sec):
        if "notes" not in grid:
            head = _lines(_front(sec, _note_stop), "주석 머리", "주석 첫머리(첫 주석 앞)")
            grid["notes"] = head if head.items else None

    def walk(e):
        for c in e:
            if c.tag == "COVER":
                out.append(_lines([k for k in c], "표지", "표지"))
            elif c.tag == "CORRECTION":
                t = c.find("TITLE")
                out.append(_section_part(c, dsd._text(t) if t is not None else "정정신고", "정정신고"))
            elif c.tag in SECTIONS:
                t = c.find("TITLE")
                title = dsd._text(t) if t is not None else ""
                if _fs_title(title):
                    if not any(x is grid for x in out):
                        out.append(grid)
                    if _is_notes(title):
                        add_notes_head(c)
                    else:
                        if "cover" not in grid:
                            cov = _lines(_front(c, _fs_stop), "재무제표 표지", "재무제표 표지")
                            grid["cover"] = cov if cov.items else None
                        for sub in c.iter():
                            if sub is not c and sub.tag in SECTIONS:
                                st = sub.find("TITLE")
                                if st is not None and _is_notes(dsd._text(st)):
                                    add_notes_head(sub)
                                    break
                    continue
                p = dsd.part_of(title)
                key = p if p in ("감사보고서", "외부감사 실시내용") else (re.sub(r"\s+", " ", title).strip() or "제목 없는 절")
                if "검토보고서" in norm(title):
                    key = "검토보고서"
                seen[key] += 1
                if seen[key] > 1:
                    key = f"{key}({seen[key]})"
                out.append(_section_part(c, title, key))
                walk(c)                                 # 안에 든 절은 따로
            elif c.tag in ("INSERTION", "LIBRARY", "PART"):
                walk(c)

    body = root.find("BODY")
    if body is not None:
        walk(body)
    if not any(x is grid for x in out):
        out.append(grid)
    return out


def read_doc(path: Path, cache: Path | None = None) -> Doc:
    """판 비교용 문서: 검증용 판독(재무제표 · 주석)에 정정신고 · 표지 · 감사보고서 · 재무제표 표지 · 주석 머리 · 외부감사 실시내용 · 그 밖의 절을
    문서 차례대로 더한 것."""
    path = Path(path)
    grid = dsd_grid.read_cached(path, cache) if cache is not None else dsd_grid.read_grid(path)
    parts = []
    for x in _layout(_root(path)):
        if isinstance(x, dict):
            if x.get("cover"):
                parts.append(x["cover"])
            fs = [p for p in grid.parts if _note_no(p.key) is None]
            notes = [p for p in grid.parts if _note_no(p.key) is not None]
            parts.extend(fs)
            if x.get("notes"):
                parts.append(x["notes"])
            parts.extend(notes)
        else:
            parts.append(x)
    return Doc(grid.source, grid.sha256, parts, grid.stats)


# ---------------------------------------------------------------- 짝 맞추기
def _note_no(key: str) -> int | None:
    m = re.fullmatch(r"주석(\d+)", key)
    return int(m.group(1)) if m else None


def _title_score(a: str, b: str) -> float:
    """두 주석 제목이 같은 주석일 정도. 회사 파일은 제목과 본문이 한 문단이라 제목에 본문이 붙어 읽히기도 한다(「회사의 개요 주식회사 …」).
    한쪽에만 본문이 붙었으면 짧은 쪽 길이만큼 앞을 견준다."""
    x, y = dsd_compare._name(a), dsd_compare._name(b)
    r = SequenceMatcher(None, x, y, autojunk=False).ratio()
    short, long_ = sorted((x, y), key=len)
    if len(short) >= 2 and len(long_) > len(short):
        r = max(r, SequenceMatcher(None, short, long_[:len(short)], autojunk=False).ratio() * 0.95)
    return r


def match_parts(new: Doc, old: Doc) -> dict[str, str]:
    """새 부분 → 옛 부분. 주석은 제목이 같은 것 → 번호가 같고 제목이 비슷한 것 → 번호를 보지 않고 제목이 비슷한 것(6할 이상) 순."""
    out, used = {}, set()
    olds = {p.key: p for p in old.parts}
    for p in new.parts:
        if _note_no(p.key) is None and p.key in olds:
            out[p.key] = p.key
            used.add(p.key)
    notes = [q for q in old.parts if _note_no(q.key) is not None]
    for p in new.parts:
        if _note_no(p.key) is None:
            continue
        same = [q for q in notes if q.key not in used and norm(q.title) == norm(p.title)]
        if same:
            q = min(same, key=lambda q: abs(_note_no(q.key) - _note_no(p.key)))
            out[p.key] = q.key
            used.add(q.key)
    for p in new.parts:
        if _note_no(p.key) is not None and p.key not in out:
            q = olds.get(p.key)
            if q is not None and q.key not in used and _title_score(p.title, q.title) >= 0.6:
                out[p.key] = q.key
                used.add(q.key)
    cand = []
    for p in new.parts:
        if _note_no(p.key) is None or p.key in out:
            continue
        for q in notes:
            if q.key not in used:
                r = _title_score(p.title, q.title)
                if r >= 0.6:
                    cand.append((r, -abs(_note_no(q.key) - _note_no(p.key)), p.key, q.key))
    for _, _, a, b in sorted(cand, reverse=True):
        if a not in out and b not in used:
            out[a] = b
            used.add(b)
    return out


def _lis(pairs: list[tuple[int, int]]) -> set[int]:
    """(새 차례, 옛 차례) 를 새 차례로 놓았을 때 옛 차례가 늘어나는 가장 긴 줄의 새 차례들. 나머지가 옮긴 것이다."""
    pairs = sorted(pairs)
    if not pairs:
        return set()
    import bisect

    tails, idx, prev = [], [], [-1] * len(pairs)
    for k, (_, o) in enumerate(pairs):
        i = bisect.bisect_left([pairs[t][1] for t in tails], o)
        if i == len(tails):
            tails.append(k)
        else:
            tails[i] = k
        prev[k] = tails[i - 1] if i else -1
    out, k = set(), tails[-1]
    while k != -1:
        out.add(pairs[k][0])
        k = prev[k]
    return out


def row_names(t: Table) -> list[str]:
    """줄을 가리는 이름. 이름이 같은 줄이 여럿이면(「소계」 · 「기타」) 위 묶음 머리 이름을 앞에 붙인다.
    묶음 머리는 바로 위의 숫자 없는 줄 가운데 이름이 하나뿐인 줄이고, 없으면 바로 위의 이름이 하나뿐인 줄이다."""
    keys = dsd_compare.row_keys(t)
    cnt = Counter(keys)
    out, head, last = [], "", ""
    for i, k in enumerate(keys):
        has_num = any(isinstance(v, (int, float)) for v in t.nums[i][1:])
        if cnt[k] == 1:
            last = k
            if not has_num:
                head = k
        out.append(f"{head or last}>{k}" if cnt[k] > 1 and (head or last) else k)
    return out


def _clean(p: Part) -> Part:
    return Part(p.key, p.title, [x for x in p.items if not (x[0] == "t" and x[1].kind == "문장")])


def _match_paras(np: Part, op: Part) -> tuple[dict, set]:
    """문단 짝 {새 항목 번호: 옛 항목 번호} 와 옮긴 새 항목 번호."""
    ni = [i for i, x in enumerate(np.items) if x[0] == "p"]
    oi = [i for i, x in enumerate(op.items) if x[0] == "p"]
    a, b = [norm(np.items[i][1]) for i in ni], [norm(op.items[i][1]) for i in oi]
    out: dict[int, int] = {}
    for tag, a0, a1, b0, b1 in SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal":
            for k in range(a1 - a0):
                out[a0 + k] = b0 + k
        elif tag == "replace":
            sc = sorted(((SequenceMatcher(None, a[x], b[y], autojunk=False).ratio(), -abs((x - a0) - (y - b0)), x, y)
                         for x in range(a0, a1) for y in range(b0, b1)), reverse=True)
            used = set()
            for r, _, x, y in sc:
                if r >= 0.5 and x not in out and y not in used:
                    out[x] = y
                    used.add(y)
    used = set(out.values())
    left_o = [y for y in range(len(b)) if y not in used]
    for x in range(len(a)):                              # 순서를 보지 않고 같은 글(옮긴 문단)
        if x in out:
            continue
        y = next((y for y in left_o if b[y] == a[x] and y not in used), None)
        if y is not None:
            out[x] = y
            used.add(y)
    sc = sorted(((SequenceMatcher(None, a[x], b[y], autojunk=False).ratio(), x, y) for x in range(len(a)) if x not in out
                 for y in range(len(b)) if y not in used and a[x] and b[y]), reverse=True)
    for r, x, y in sc:
        if r >= 0.6 and x not in out and y not in used:
            out[x] = y
            used.add(y)
    keep = _lis(list(out.items()))
    moved = {ni[x] for x in out if x not in keep}
    return {ni[x]: oi[y] for x, y in out.items()}, moved


def _row_text(t: Table, i: int) -> str:
    return " · ".join(f"{t.header[c]} {t.rows[i][c]}".strip() for c in range(1, len(t.header)) if (t.rows[i][c] or "").strip())[:300]


def _label(t: Table, i: int) -> str:
    if t.labels and t.labels[i]:
        return t.labels[i]
    first = (t.rows[i][0] or "").strip()
    return first or next((x for x in t.rows[i][1:3] if (x or "").strip() and dsd_grid.to_num(x) is None), "")


def _col_text(t: Table, j: int) -> str:
    vals = [f"{_label(t, i)} {t.rows[i][j]}".strip() for i in range(len(t.rows)) if (t.rows[i][j] or "").strip()]
    return " · ".join(vals)[:300]


def _ws(s) -> str:
    """견줄 글: 연속 공백만 하나로 줄인다. 띄어쓰기를 넣고 뺀 것은 바뀐 곳으로 센다(정정공시에 「1 ,500,000천원」 → 「1,500,000천원」 같은 고침이 있다)."""
    return " ".join(str(s or "").split())


_WORD = re.compile(r"[가-힣A-Za-z0-9]")


def space_lost(a, b) -> list[tuple[str, str]]:
    """옛 글 a → 새 글 b 에서 낱말 사이 띄어쓰기가 빠진 곳. [(새 판의 붙은 낱말, 옛 판의 띄어 쓴 낱말)]. 다른 고침이 함께 있는 문단도 본다.
    공백 양옆이 모두 한글 · 영문 · 숫자일 때만 센다(「1 ,500,000」 → 「1,500,000」 처럼 문장부호 앞 공백을 지운 것은 바른 고침이다).
    2026-11-04 네온테크 v2 → v3: 「2028년 3월」 → 「2028년3월」, 「날 사채권자의」 → 「날사채권자의」 처럼 새 판에서 띄어쓰기가 빠졌다."""
    a, b = str(a or ""), str(b or "")
    if a == b or len(a) > 20000:
        return []
    out = []
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag != "delete" or a[i1:i2].strip() or not (0 < i1 and i2 < len(a)) or not (_WORD.match(a[i1 - 1]) and _WORD.match(a[i2])):
            continue
        if not (0 < j1 < len(b) and b[j1 - 1] == a[i1 - 1] and b[j1] == a[i2]):     # 문단의 다른 고침과 섞인 곳은 잇닿은 글자가 같을 때만
            continue
        lo = i1
        while lo > 0 and not a[lo - 1].isspace():
            lo -= 1
        hi = i2
        while hi < len(a) and not a[hi].isspace():
            hi += 1
        bl = j1
        while bl > 0 and not b[bl - 1].isspace():
            bl -= 1
        bh = j1
        while bh < len(b) and not b[bh].isspace():
            bh += 1
        pair = (b[bl:bh], a[lo:hi])
        if pair not in out:
            out.append(pair)
    return out


def _space_memo(a, b) -> str:
    lost = space_lost(a, b)
    if lost:
        more = f" 외 {len(lost) - 2}곳" if len(lost) > 2 else ""
        return "띄어쓰기 빠짐: " + ", ".join(f"「{x}」(옛 판 「{y}」)" for x, y in lost[:2]) + more + ("" if norm(a) == norm(b) else ". 다른 고침도 있다")
    return "띄어쓰기만 바뀜" if norm(a) == norm(b) else ""


def _sig(t: Table, i: int, cols: list[int]) -> tuple | None:
    """줄의 값(줄 이름 칸 말고). 숫자 칸은 숫자, 글자 칸은 공백을 줄인 글. 값이 모두 비었거나 0 이면 None(이름만 다른 빈 줄끼리 잇지 않는다)."""
    vals, real = [], False
    for c in cols:
        if dsd_compare.numeric(t, i, c):
            v = t.nums[i][c]
            vals.append(("n", round(float(v or 0), 6)))
            real = real or bool(v)
        else:
            s = _ws(dsd_compare.cell_text(t, i, c))
            vals.append(("s", s))
            real = real or len(norm(s)) >= 4
    return tuple(vals) if real else None


def _same_value_rows(t: Table, q: Table, rows: dict, cols: dict) -> dict:
    """이름으로 짝짓지 못한 새 줄 · 옛 줄 가운데 값이 모두 같은 줄을 잇는다(줄 이름만 바꾼 줄). 같은 값의 줄이 한쪽에 둘 이상이면 잇지 않는다.
    2026-11-04 네온테크 주석20-2: 「행사청구기간」 삭제 · 「전환청구기간」 추가로 갈렸는데 값(2027.05.15 - 2028.04.15)이 같았다."""
    pairs = sorted((c, d) for c, d in cols.items() if c)
    if not pairs:
        return {}
    used = set(rows.values())
    new_sig: dict = {}
    for i in range(len(t.rows)):
        if i not in rows:
            s = _sig(t, i, [c for c, _ in pairs])
            if s is not None:
                new_sig.setdefault(s, []).append(i)
    old_sig: dict = {}
    for j in range(len(q.rows)):
        if j not in used:
            s = _sig(q, j, [d for _, d in pairs])
            if s is not None:
                old_sig.setdefault(s, []).append(j)
    return {ii[0]: old_sig[s][0] for s, ii in new_sig.items() if len(ii) == 1 and len(old_sig.get(s, [])) == 1}


def _num_close(v, w) -> bool:
    return abs((v or 0) - (w or 0)) < 1e-9


def _table_changes(pd: PartDiff, key: str, k: int, t: Table, q: Table, rows: dict | None = None, cols: dict | None = None) -> tuple[dict, dict]:
    """짝지은 두 표의 바뀐 곳. rows · cols 를 주면(나뉨 · 합침의 숫자 짝) 그 짝으로 칸만 견주고, 새 줄 · 없어진 줄 · 열 · 머리줄은 부르는 쪽이 센다."""
    add = pd.changes.append
    pieces = rows is not None
    if not pieces:
        nk, okk = row_names(t), row_names(q)
        rows = dsd_compare._pairs(nk, okk)
        cols = dsd_compare._pairs(t.header, q.header)
        cols.setdefault(0, 0)
        cols.update(dsd_compare._fuzzy_cols(t.header, q.header, cols))
        rows.update(dsd_compare._fuzzy_rows(t, q, rows))
        rows.update(_same_value_rows(t, q, rows, cols))
        for i in range(1, len(t.header)):
            if i not in cols:
                add(Change("추가", "열", key, f"{t.id} {t.header[i] or f'{i + 1}번째 열'}", "", _col_text(t, i), anchor=(key, ("n", k), -1, i)))
        for j in range(1, len(q.header)):
            if j not in cols.values():
                add(Change("삭제", "열", key, f"{q.id} {q.header[j] or f'{j + 1}번째 열'}", _col_text(q, j), "", anchor=(key, ("n", k), -1, 0)))
        for i, j in sorted(cols.items()):
            if i and _ws(t.header[i]) != _ws(q.header[j]):
                add(Change("변경", "머리줄", key, f"{t.id} {i + 1}번째 열", q.header[j], t.header[i], memo=_space_memo(q.header[j], t.header[i]),
                           anchor=(key, ("n", k), -1, i)))
        keep = _lis(list(rows.items()))
        pd.moved_rows[k] = {i for i in rows if i not in keep}
    for i in range(len(t.rows)):
        if i not in rows:
            if not pieces:
                add(Change("추가", "줄", key, f"{t.id} {_label(t, i)}", "", _row_text(t, i), anchor=(key, ("n", k), i, 0)))
            continue
        j = rows[i]
        if not pieces and _ws(_label(t, i)) != _ws(_label(q, j)):
            add(Change("변경", "줄", key, f"{t.id} {_label(t, i)}", _label(q, j), _label(t, i), memo=_space_memo(_label(q, j), _label(t, i)) or "줄 이름 바뀜",
                       anchor=(key, ("n", k), i, 0)))
        if i in pd.moved_rows.get(k, ()):
            add(Change("옮김", "줄", key, f"{t.id} {_label(t, i)}", f"{j + 1}번째 줄", f"{i + 1}번째 줄", anchor=(key, ("n", k), i, 0)))
        for c in range(1, len(t.header)):
            if c not in cols:
                continue
            d = cols[c]
            where = f"{t.id} {_label(t, i)} · {t.header[c]}".strip(" ·")
            if dsd_compare.numeric(t, i, c) and dsd_compare.numeric(q, j, d):
                v, w = t.nums[i][c], q.nums[j][d]
                if not _num_close(v, w):
                    flip = "부호만 바뀜" if w and _num_close(v, -w) else ""          # 결손금을 양수 → 괄호로 고친 것처럼 차이가 금액의 두 배로 보인다(2026-11-04 실제 판)
                    add(Change("변경", "칸", key, where, w or 0, v or 0, (v or 0) - (w or 0), memo=flip, anchor=(key, ("n", k), i, c)))
            else:
                a, b = dsd_compare.cell_text(q, j, d), dsd_compare.cell_text(t, i, c)
                if _ws(a) != _ws(b):
                    add(Change("변경", "칸", key, where, a, b, memo=_space_memo(a, b), anchor=(key, ("n", k), i, c)))
    if not pieces:
        back = {j: i for i, j in rows.items()}
        for j in range(len(q.rows)):
            if j not in back:
                near = max((i for i, jj in rows.items() if jj < j), default=-1)
                add(Change("삭제", "줄", key, f"{q.id} {_label(q, j)}", _row_text(q, j), "", anchor=(key, ("n", k), ("o", j), 0)))
    return rows, cols


def _part_diff(np: Part | None, op: Part | None) -> PartDiff:
    pd = PartDiff(np, op)
    if np is None or op is None:
        p = np or op
        kind = "추가" if np is not None else "삭제"
        n_t = sum(1 for x in p.items if x[0] == "t" and x[1].kind != "문장")
        n_p = sum(1 for x in p.items if x[0] == "p")
        what = f"문단 {n_p} · 표 {n_t}"
        pd.changes.append(Change(kind, "부분", p.key, f"{p.key} {p.title[:60]}".strip(), "" if np else what, what if np else "", anchor=(p.key, None, None, None)))
        return pd
    key = np.key
    if _note_no(np.key) is not None and np.key != op.key:
        pd.changes.append(Change("변경", "번호", key, f"{op.key} → {np.key}", op.key, np.key, memo=np.title[:60], anchor=(key, None, None, None)))
    if _ws(np.title) != _ws(op.title):
        memo = _space_memo(op.title, np.title) or ("제목과 같은 문단에 붙은 본문도 제목으로 읽었다" if max(len(np.title), len(op.title)) > 40 else "")
        pd.changes.append(Change("변경", "제목", key, key, op.title, np.title, memo=memo, anchor=(key, None, None, None)))
    a, b = _clean(np), _clean(op)
    pd.new, pd.old = a, b
    pd.paras, moved = _match_paras(a, b)
    pd.moved |= moved
    n_idx = {x[1].id: i for i, x in enumerate(a.items) if x[0] == "t"}
    o_idx = {x[1].id: i for i, x in enumerate(b.items) if x[0] == "t"}
    nt = [x[1] for x in a.items if x[0] == "t"]
    ot = [x[1] for x in b.items if x[0] == "t"]
    pairs = dsd_compare._match_tables(a, b)
    if _note_no(np.key) is None:                    # 재무제표 · 그 밖의 절의 표는 머리줄 글자가 달라도 차례대로 같은 표다
        for i, t in enumerate(nt):
            if t.id not in pairs and i < len(ot) and ot[i].id not in pairs.values():
                pairs[t.id] = ot[i].id
    split = _splits(nt, ot, pairs)
    for t in split["new"]:
        pairs.pop(t, None)
    pairs = {t: o for t, o in pairs.items() if o not in split["old"]}
    nt2 = [t for t in nt if t.id not in split["new"]]
    ot2 = [q for q in ot if q.id not in split["old"]]
    otab = {t.id: t for t in ot}
    ntab = {t.id: t for t in nt}
    order = _lis([(n_idx[t], o_idx[o]) for t, o in pairs.items()])
    for t in nt2:
        if t.id in pairs:
            q = otab[pairs[t.id]]
            k = n_idx[t.id]
            if k not in order:
                pd.moved.add(k)
                pd.changes.append(Change("옮김", "표", key, f"{t.id} {t.caption[:40]}".strip(), q.id, t.id, anchor=(key, ("n", k), -1, 0)))
            rows, cols = _table_changes(pd, key, k, t, q)
            pd.tables[k] = (o_idx[q.id], rows, cols)
    for t in nt2:
        if t.id not in pairs:
            pd.changes.append(Change("추가", "표", key, f"{t.id} {t.caption[:40]}".strip(), "", (f"{len(t.rows)}줄 · " + _row_text(t, 0)) if t.rows else "빈 표",
                                     anchor=(key, ("n", n_idx[t.id]), -1, 0)))
    for q in ot2:
        if q.id not in pairs.values():
            pd.changes.append(Change("삭제", "표", key, f"{q.id} {q.caption[:40]}".strip(), (f"{len(q.rows)}줄 · " + _row_text(q, 0)) if q.rows else "빈 표", "",
                                     anchor=(key, ("o", o_idx[q.id]), -1, 0)))
    for kind, groups in split["items"]:
        first = min(n_idx[tid] for tid, _, _, _ in groups)
        news = sorted({tid for tid, _, _, _ in groups}, key=lambda x: n_idx[x])
        olds_ = sorted({oid for _, oid, _, _ in groups}, key=lambda x: o_idx[x])
        pd.changes.append(Change(kind, "표", key, ", ".join(news), ", ".join(olds_), ", ".join(news),
                                 memo="옛 표의 숫자가 새 표 여럿에 나뉘어 있다" if kind == "나뉨" else "옛 표 여럿의 숫자가 새 표 하나에 모여 있다",
                                 anchor=(key, ("n", first), -1, 0)))
        covered_n: dict = {}
        covered_o: dict = {}
        for tid, oid, rows, cols in groups:
            t, q = ntab[tid], otab[oid]
            _table_changes(pd, key, n_idx[tid], t, q, rows, cols)
            covered_n.setdefault(tid, set()).update(rows)
            covered_o.setdefault(oid, set()).update(rows.values())
            if n_idx[tid] not in pd.tables:
                pd.tables[n_idx[tid]] = (o_idx[oid], rows, cols)
        for tid, got in covered_n.items():
            t = ntab[tid]
            for i in range(len(t.rows)):
                if i not in got and any(isinstance(v, (int, float)) and v for v in t.nums[i][1:]):
                    pd.changes.append(Change("추가", "줄", key, f"{t.id} {_label(t, i)}", "", _row_text(t, i), anchor=(key, ("n", n_idx[tid]), i, 0)))
        for oid, got in covered_o.items():
            q = otab[oid]
            for j in range(len(q.rows)):
                if j not in got and any(isinstance(v, (int, float)) and v for v in q.nums[j][1:]):
                    pd.changes.append(Change("삭제", "줄", key, f"{q.id} {_label(q, j)}", _row_text(q, j), "", anchor=(key, ("n", first), -1, 0), memo="나뉜 표 어디에도 없는 줄"))
    for i, x in enumerate(a.items):
        if x[0] != "p":
            continue
        j = pd.paras.get(i)
        if j is None:
            pd.changes.append(Change("추가", "문단", key, f"{key} 문단", "", x[1], anchor=(key, ("n", i), None, None)))
            continue
        if i in pd.moved:
            pd.changes.append(Change("옮김", "문단", key, f"{key} 문단", "", x[1][:80], anchor=(key, ("n", i), None, None)))
        if _ws(b.items[j][1]) != _ws(x[1]):
            pd.changes.append(Change("변경", "문단", key, f"{key} 문단", b.items[j][1], x[1], memo=_space_memo(b.items[j][1], x[1]),
                                     anchor=(key, ("n", i), None, None)))
    used = set(pd.paras.values())
    for j, x in enumerate(b.items):
        if x[0] == "p" and j not in used:
            pd.changes.append(Change("삭제", "문단", key, f"{key} 문단", x[1], "", anchor=(key, ("o", j), None, None)))
    return pd


def _piece(small: Table, big: Table, hits: set) -> tuple[dict, dict]:
    """나뉜(모인) 표 조각과 큰 표의 줄 · 열 짝 {조각 줄: 큰 표 줄}, {조각 열: 큰 표 열}. 숫자로 이어진 큰 표의 줄들이 첫 칸 묶음(「당기」 · 「전기」)을
    같이 쓰면 그 묶음 줄만 두고, 묶음 이름을 뗀 줄 이름으로 짝짓는다(당기 · 전기 표는 같은 숫자를 나눠 가져 숫자로는 줄을 가를 수 없다)."""
    sk, bk = dsd_compare.row_keys(small), dsd_compare.row_keys(big)
    groups = Counter(bk[j].split("|")[0] for j in hits if "|" in bk[j])
    if groups:
        g = groups.most_common(1)[0][0]
        sub = [j for j in range(len(big.rows)) if "|" in bk[j] and bk[j].split("|")[0] == g]
    else:
        sub = sorted(hits)
    m = dsd_compare._pairs([k.split("|")[-1] for k in sk], [bk[j].split("|")[-1] for j in sub])
    rows = {i: sub[jj] for i, jj in m.items()}
    cols = dsd_compare._pairs(small.header, big.header)
    cols.setdefault(0, 0)
    cols.update(dsd_compare._fuzzy_cols(small.header, big.header, cols))
    return rows, cols


def _splits(new: list[Table], old: list[Table], pairs: dict) -> dict:
    """나뉨(옛 표 하나 → 새 표 여럿) · 합침(옛 표 여럿 → 새 표 하나). 이름으로 짝짓지 못한 표가 숫자로 다른 표에 이어지고, 그 다른 표가 짝이 없거나
    짝과 줄이 8할 넘게 맞지 않을 때만 본다(이름 짝이 다 맞는 표를 숫자로 다시 묶지 않는다. 일대일로만 이어지면 금액만으로 짝짓지 않는다).
    items 는 (종류, [(새 표, 옛 표, {새 줄: 옛 줄}, {새 열: 옛 열})])."""
    out = {"new": set(), "old": set(), "items": []}
    ntab, otab = {t.id: t for t in new}, {t.id: t for t in old}
    back_pairs = {o: t for t, o in pairs.items()}
    lone_n = [t for t in new if t.id not in pairs]
    lone_o = [q for q in old if q.id not in back_pairs]
    if not lone_n and not lone_o:
        return out

    def cover(t, q) -> tuple[float, float]:
        m = dsd_compare._pairs(row_names(t), row_names(q))
        return len(m) / max(len(t.rows), 1), len(m) / max(len(q.rows), 1)

    one = lambda ts: Doc("", "", [Part("x", "", [("t", t) for t in ts])])      # noqa: E731
    if lone_n:
        fwd = dsd_compare.match_numbers(one(lone_n), one(old))
        by_old: dict[str, list] = {}
        for tid, m in fwd.items():
            by_old.setdefault(m[0], []).append(tid)
        for oid, tids in by_old.items():
            mate = back_pairs.get(oid)
            if mate is not None and cover(ntab[mate], otab[oid])[1] >= 0.8:
                continue
            members = sorted(tids + ([mate] if mate else []), key=[t.id for t in new].index)
            if len(members) < 2:
                continue
            q = otab[oid]
            groups = []
            for tid in members:
                hits = set(fwd[tid][1].values()) if tid in fwd else set(range(len(q.rows)))
                r, c = _piece(ntab[tid], q, hits)
                groups.append((tid, oid, r, c))
            out["items"].append(("나뉨", groups))
            out["new"] |= set(members)
            out["old"].add(oid)
    lone_o = [q for q in lone_o if q.id not in out["old"]]
    if lone_o:
        back = dsd_compare.match_numbers(one(lone_o), one([t for t in new if t.id not in out["new"]]))
        by_new: dict[str, list] = {}
        for oid, m in back.items():
            by_new.setdefault(m[0], []).append(oid)
        for tid, oids in by_new.items():
            mate = pairs.get(tid)
            if mate is not None and (mate in out["old"] or cover(ntab[tid], otab[mate])[0] >= 0.8):
                continue
            members = sorted(oids + ([mate] if mate else []), key=[q.id for q in old].index)
            if len(members) < 2:
                continue
            t = ntab[tid]
            groups = []
            for oid in members:
                hits = set(back[oid][1].values()) if oid in back else set(range(len(t.rows)))
                r, c = _piece(otab[oid], t, hits)
                groups.append((tid, oid, {v: k for k, v in r.items()}, {v: k for k, v in c.items()}))
            out["items"].append(("합침", groups))
            out["new"].add(tid)
            out["old"] |= set(members)
    return out


def compare(old: Doc, new: Doc) -> Result:
    pm = match_parts(new, old)
    olds = {p.key: p for p in old.parts}
    o_order = {p.key: i for i, p in enumerate(old.parts)}
    keep = _lis([(i, o_order[pm[p.key]]) for i, p in enumerate(new.parts) if p.key in pm])
    out = []
    for i, p in enumerate(new.parts):
        q = olds.get(pm.get(p.key))
        pd = _part_diff(p, q)
        if q is not None and i not in keep:
            pd.changes.insert(0, Change("옮김", "부분", p.key, f"{p.key} {p.title[:40]}".strip(), f"옛 판 {o_order[q.key] + 1}번째", f"새 판 {i + 1}번째",
                                        anchor=(p.key, None, None, None)))
        out.append(pd)
    gone = [q for q in old.parts if q.key not in pm.values()]
    for q in gone:                                    # 없어진 부분은 옛 판에서 그 앞 부분의 짝 뒤에 둔다
        prev = [k for k in old.parts[:o_order[q.key]] if k.key in pm.values()]
        back = {v: k for k, v in pm.items()}
        at = next((n for n, pd in enumerate(out) if pd.new is not None and prev and pd.new.key == back[prev[-1].key]), -1)
        out.insert(at + 1, _part_diff(None, q))
    res = Result(old, new, out)
    res.leftovers = _leftovers(res)
    return res


# ---------------------------------------------------------------- 같이 고칠 곳 후보(2026-11-04)
# 회사가 한 곳만 고치고 같은 숫자가 있던 다른 곳은 그대로 둔 것. 편집기 「문서 비교」 는 바뀐 곳만 보여 이런 곳을 못 본다.
# 2026-11-04 네온테크 별도 v2 → v3: 주석22-3 교환대상 주식수 1,084,990 → 1,084,992(주석26 문단도 고침), 주석36-3 발행될 보통주식수는 1,084,990 그대로.
_COMMA_NUM = re.compile(r"(?<![\d,.])\d{1,3}(?:,\d{3})+(?![\d,])")
MIN_LEFT = 1000                 # 이보다 작은 수(차례 · 개월 · 비율)는 우연히 같은 곳이 많다
MAX_PLACES = 8                  # 옛 판에 이보다 많은 곳에 있던 값은 고르지 않는다(어림수 · 자주 쓰는 금액)
_PRIOR = re.compile(r"전\s*기|전\s*반\s*기|전\s*분\s*기|기\s*초|\(\s*전\s*\)")
_CURRENT = re.compile(r"당\s*기|당\s*반\s*기|당\s*분\s*기|\(\s*당\s*\)")


def _year_like(w: float) -> bool:
    return float(w).is_integer() and 1900 <= w <= 2100


def _prior_place(header: str, label: str) -> bool:
    return bool(_PRIOR.search(header or "") or re.match(r"\s*(기\s*초|전\s*기\s*말)", label or ""))


def _leftovers(res: "Result") -> list[Leftover]:
    """새 판에서 고친 옛 값(숫자 칸, 문단 속 쉼표 숫자)이 옛 판의 다른 표 · 문단에도 있었고, 그 짝이 새 판에서 그대로인 곳.
    같은 표 · 같은 문단 안은 보지 않는다(당기만 고치고 전기는 그대로인 것이 보통이다). 고친 칸이 당기 열이고 남은 곳이 전기 · 기초면 뺀다."""
    changed = []
    for pd in res.parts:
        if pd.new is None or pd.old is None:
            continue
        for c in pd.changes:
            if c.kind != "변경" or not c.anchor:
                continue
            own = (pd.key, c.anchor[1])
            if c.unit == "칸" and c.numeric and not c.memo.startswith("부호"):
                w = abs(float(c.old or 0))
                k, i, col = c.anchor[1][1], c.anchor[2], c.anchor[3]
                t = pd.new.items[k][1]
                cur = bool(_CURRENT.search(t.header[col] if col < len(t.header) else ""))
                if w >= MIN_LEFT and not _year_like(w):
                    changed.append((w, c.where, c.new, own, cur))
            elif c.unit == "문단":
                news = set(_COMMA_NUM.findall(str(c.new)))
                for x in set(_COMMA_NUM.findall(str(c.old))) - news:
                    w = float(x.replace(",", ""))
                    if w >= MIN_LEFT:
                        changed.append((w, c.where, None, own, False))
    if not changed:
        return []
    want = {w for w, *_ in changed}
    places: dict = {}
    for pd in res.parts:
        if pd.new is None or pd.old is None:
            continue
        a, b = pd.new, pd.old
        back = {}
        for k, (j, rows, cols) in pd.tables.items():
            back.setdefault(j, (k, {o: n for n, o in rows.items()}, {o: n for n, o in cols.items()}))
        pback = {j: i for i, j in pd.paras.items()}
        for j, x in enumerate(b.items):
            if x[0] == "t":
                q = x[1]
                if q.kind == "문장":
                    continue
                for r, row in enumerate(q.nums):
                    for col, v in enumerate(row):
                        if v is None or abs(float(v)) not in want:
                            continue
                        loc = None
                        if j in back:
                            k, rr, cc = back[j]
                            nr, nc = rr.get(r), cc.get(col)
                            t = a.items[k][1]
                            if nr is not None and nc is not None and nr < len(t.nums) and nc < len(t.nums[nr]):
                                nv = t.nums[nr][nc]
                                head = t.header[nc] if nc < len(t.header) else ""
                                loc = {"unit": "칸", "own": (pd.key, ("n", k)), "where": f"{t.id} {_label(t, nr)} · {head}".strip(" ·"),
                                       "same": nv is not None and abs(float(nv)) == abs(float(v)), "anchor": (pd.key, ("n", k), nr, nc), "text": "",
                                       "prior": _prior_place(head, _label(t, nr))}
                        places.setdefault(abs(float(v)), []).append(loc)
            else:
                for s in _COMMA_NUM.findall(x[1]):
                    w = float(s.replace(",", ""))
                    if w not in want:
                        continue
                    loc = None
                    i = pback.get(j)
                    if i is not None:
                        nt = a.items[i][1]
                        pos = nt.find(s)
                        loc = {"unit": "문단", "own": (pd.key, ("n", i)), "where": f"{pd.key} 문단", "same": pos >= 0, "anchor": (pd.key, ("n", i), None, None),
                               "text": nt[max(0, pos - 30):pos + len(s) + 15] if pos >= 0 else "", "prior": False}
                    places.setdefault(w, []).append(loc)
    out, seen = [], set()
    for w, where, nv, own, cur in changed:
        locs = places.get(w, [])
        if len(locs) > MAX_PLACES:
            continue
        for loc in locs:
            if loc is None or not loc["same"] or loc["own"] == own or (cur and loc["prior"]):
                continue
            if loc["anchor"] in seen:
                continue
            seen.add(loc["anchor"])
            out.append(Leftover(loc["anchor"][0], loc["unit"], loc["where"], w, where, nv, loc["text"], loc["anchor"]))
    return out


def compare_files(old: Path, new: Path, cache: Path | None = None) -> Result:
    return compare(read_doc(old, cache), read_doc(new, cache))


# ---------------------------------------------------------------- 요약 · json
def summary_rows(res: Result) -> list[dict]:
    out = []
    for pd in res.parts:
        cnt = Counter(c.kind for c in pd.changes)
        nums = [c for c in pd.changes if c.numeric]
        renum = sum(1 for c in pd.changes if c.unit == "번호")
        row = {"부분": pd.key, "제목": (pd.new or pd.old).title[:60], "옛 판 부분": pd.old.key if pd.old else "", **{k: cnt.get(k, 0) for k in KINDS}}
        row["변경"] -= renum
        row.update({"번호 바뀜": renum, "바뀐 숫자 칸": len(nums), "차이 절댓값 합": sum(abs(c.diff) for c in nums)})
        out.append(row)
    return out


def to_json(res: Result) -> dict:
    def ch(c: Change) -> dict:
        d = asdict(c)
        d.pop("anchor")
        return d

    def lo(x: Leftover) -> dict:
        d = asdict(x)
        d.pop("anchor")
        return d

    return {"old": res.old.source, "new": res.new.source, "old_sha256": res.old.sha256, "new_sha256": res.new.sha256,
            "count": dict(res.count()), "parts": summary_rows(res), "changes": [ch(c) for c in res.changes],
            "leftovers": [lo(x) for x in res.leftovers]}


def totals(res: Result) -> dict:
    """요약 시트 맨 아래 줄과 같은 셈. 변경은 번호 바뀜을 뺀 수다."""
    rows = summary_rows(res)
    keys = (*KINDS, "번호 바뀜", "바뀐 숫자 칸", "차이 절댓값 합")
    out = {k: sum(r[k] for r in rows) for k in keys}
    out["바뀐 부분"] = sum(1 for p in res.parts if p.changes)
    return out


def line(res: Result) -> str:
    n = totals(res)
    head = " · ".join(f"{k} {n[k]}" for k in KINDS if n[k] or k in KINDS[:4])
    renum = f" · 번호 바뀜 {n['번호 바뀜']}" if n["번호 바뀜"] else ""
    left = f" · 같이 고칠 곳 후보 {len(res.leftovers)}" if res.leftovers else ""
    return f"{res.old.source} → {res.new.source}: {head}{renum} (바뀐 숫자 칸 {n['바뀐 숫자 칸']}, 바뀐 부분 {n['바뀐 부분']}){left}"


def file_stem(old: Path, new: Path) -> str:
    def cut(s: str) -> str:
        s = re.sub(r'[\\/:*?"<>|\[\]]', "_", s)
        return s if len(s) <= 40 else s[:30] + "_" + hashlib.sha1(s.encode()).hexdigest()[:6]

    a, b = Path(old).stem, Path(new).stem
    k = 0
    while k < min(len(a), len(b)) and a[k] == b[k]:
        k += 1
    k = max(a.rfind("_", 0, k), a.rfind(" ", 0, k)) + 1 if k < min(len(a), len(b)) else k
    if k >= 8:                                       # 같은 이름의 두 판(「…_v2」 · 「…_v3」): 앞 이름은 한 번만. 엑셀은 218자 넘는 경로를 열지 못한다
        return f"판비교_{cut(a[:k].rstrip('_ '))}_{cut(a[k:]) or '옛'}_{cut(b[k:]) or '새'}"
    return f"판비교_{cut(a)}_{cut(b)}"


def write_json(path: Path, res: Result) -> Path:
    path.write_text(json.dumps(to_json(res), ensure_ascii=False, indent=1), encoding="utf-8")
    return path
