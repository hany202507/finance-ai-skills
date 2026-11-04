"""DSD 판 비교 엑셀(2026-10-26). 판비교_<옛>_<새>.xlsx.

  요약       부분마다 추가 · 삭제 · 변경 · 번호 바뀜 · 옮김 · 나뉨 · 합침 수, 바뀐 숫자 칸 수와 차이 절댓값 합. 맨 아래 합계
  바뀐 곳    한 줄에 바뀐 곳 하나: 종류 · 단위 · 부분 · 위치 · 옛 · 새 · 차이 · 메모. 글은 바뀐 글자를 빨갛게 적는다. 부분을 누르면 그 칸으로 간다
  같이 고칠 곳  새 판에서 고친 옛 값이 옛 판의 다른 곳에도 있었는데 새 판에서 그곳은 그대로인 것(2026-11-04). 있을 때만
  부분 시트  바뀐 부분만. 새 판 원문에 바뀐 칸 · 문단은 빨간 글자(옛 값은 칸 메모), 새 줄 · 새 문단 · 새 열은 빨간 바탕,
             없어진 줄 · 문단 · 표는 원래 있던 곳에 회색 취소선, 옮긴 것은 노란 바탕. 없어진 부분은 「옛_」 시트에 회색 취소선으로 둔다
"""
from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter as L

from .. import wp
from .. import style
from .dsd_book import NUM, RED, _link, _q, _rich_diff, _style_head, print_setup
from .dsd_versions import KINDS, Change, PartDiff, Result, summary_rows, totals

SUMMARY, CHANGES, LEFTOVERS = "요약", "바뀐 곳", "같이 고칠 곳"
FILL_NEW = style.FILL_FLAG          # 새로 생긴 칸(2026-11-03 공통 팔레트)
FILL_MOVED = style.FILL_WP          # 바뀐 칸. 노랑은 감사인 기입란이라 HTML 보기와 같은 하늘색
FILL_ZERO = style.FILL_NONE
GRAY = style.MUTED
FIRST = 4
TEXT_KINDS = ("문단", "제목", "머리줄", "칸", "줄")


def _sheet_name(key: str, used: set, prefix: str = "") -> str:
    name = "".join("_" if ch in wp.SHEET_NAME_BAD else ch for ch in prefix + key)[: wp.SHEET_NAME_MAX]
    base, n = name, 2
    while name in used or name in (SUMMARY, CHANGES):
        name = f"{base[: wp.SHEET_NAME_MAX - 3]}({n})"
        n += 1
    used.add(name)
    return name


def _gone_font():
    return wp.font(color=GRAY, strike=True)


def _comment(text: str) -> Comment:
    c = Comment(text[:1500], "판 비교")
    c.width, c.height = 320, 120
    return c


def _shown(v) -> str:
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return f"{v:,.0f}" if float(v).is_integer() else f"{v:,.4f}".rstrip("0")
    return str(v or "")


def _near(pairs: dict, j: int) -> int:
    """옛 항목 j 를 끼워 넣을 곳: 옛 차례가 j 보다 앞인 짝 가운데 가장 뒤의 새 항목 뒤. 없으면 -1(맨 앞)."""
    return max((i for i, jj in pairs.items() if jj < j), default=-1)


class _Sheet:
    def __init__(self, ws, width: int):
        self.ws, self.row, self.width, self.anchor = ws, FIRST, max(width, 2), {}

    def mark(self, text: str, fill=None):
        x = self.ws.cell(self.row, 1, text)
        x.font = wp.font(size=9, bold=True, color=RED if text in ("추가", "변경") else (GRAY if text == "삭제" else None))
        if fill is not None:
            x.fill = fill

    def para(self, text, *, mark="", font=None, fill=None, comment=None, key=None):
        ws = self.ws
        x = ws.cell(self.row, 2, text)
        x.alignment = Alignment(wrap_text=True, vertical="top")
        x.font = font or wp.font()
        if fill is not None:
            x.fill = fill
        if comment:
            x.comment = _comment(comment)
        if self.width > 1:
            ws.merge_cells(start_row=self.row, start_column=2, end_row=self.row, end_column=1 + self.width)
        n = len(str(text)) if not hasattr(text, "__len__") or isinstance(text, str) else sum(len(str(b)) for b in text)
        ws.row_dimensions[self.row].height = min(15 * max(1, n // (14 * self.width) + 1), 300)
        if mark:
            self.mark(mark, fill)
        if key is not None:
            self.anchor[key] = f"B{self.row}"
        self.row += 1


def _table(sh: _Sheet, key, t, pd: PartDiff | None, k: int | None, *, status: str = "", old=None, rows=None, cols=None, moved_rows=(),
           changed: dict | None = None, gone_rows: dict | None = None, new_cols=(), gone_cols=(), head_changed: dict | None = None):
    """표 하나. status 가 「추가」 면 줄마다 빨간 바탕, 「삭제」 면 회색 취소선. 짝지은 표는 바뀐 칸 · 새 줄 · 없어진 줄을 표시한다."""
    ws = sh.ws
    cap = f"[{t.id}] {t.caption}".strip()
    if gone_cols:
        cap += "  · 없어진 열: " + ", ".join(gone_cols)
    x = ws.cell(sh.row, 2, cap)
    x.font = _gone_font() if status == "삭제" else wp.font(bold=True, size=9)
    if status:
        sh.mark(status, FILL_NEW if status == "추가" else None)
    if key is not None:
        sh.anchor[(key, -1, 0)] = f"B{sh.row}"
    sh.row += 1
    hr = sh.row
    for j, h in enumerate(t.header):
        c = ws.cell(hr, 2 + j, h)
        if status == "삭제":
            c.font = _gone_font()
        else:
            _style_head(c)
            if j in new_cols:
                c.fill = FILL_NEW
                c.font = wp.font(bold=True, color=RED)
            if head_changed and j in head_changed:
                c.font = wp.font(bold=True, color=RED)
                c.comment = _comment(f"옛 머리줄: {head_changed[j]}")
        if key is not None:
            sh.anchor[(key, -1, j)] = c.coordinate
    sh.row += 1
    back_cols = {v: kk for kk, v in (cols or {}).items()}

    def gone_row(j):
        r = old.rows[j]
        sh.mark("삭제")
        for jj, v in enumerate(r):
            nj = back_cols.get(jj)
            if nj is None:
                continue
            c = ws.cell(sh.row, 2 + nj, old.nums[j][jj] if jj and old.nums[j][jj] is not None else v)
            c.font = _gone_font()
            if isinstance(c.value, (int, float)):
                c.number_format = NUM
        if key is not None:
            sh.anchor[(key, ("o", j), 0)] = f"B{sh.row}"
        sh.row += 1

    for j in (gone_rows or {}).get(-1, []):
        gone_row(j)
    for i, r in enumerate(t.rows):
        is_new = status == "추가" or (rows is not None and i not in rows)
        for j, v in enumerate(r):
            num = t.nums[i][j] if j else None
            c = ws.cell(sh.row, 2 + j, num if num is not None else v)
            if isinstance(num, (int, float)):
                c.number_format = NUM
            if status == "삭제":
                c.font = _gone_font()
            elif is_new:
                c.fill = FILL_NEW
            elif changed and (i, j) in changed:
                c.font = wp.font(bold=True, color=RED)
                c.comment = _comment(f"옛 값: {_shown(changed[(i, j)])}")
            if key is not None:
                sh.anchor[(key, i, j)] = c.coordinate
        if is_new and status != "삭제":
            sh.mark("추가", FILL_NEW)
        elif i in moved_rows:
            sh.mark("옮김", FILL_MOVED)
        elif changed and any(a == i for a, _ in changed):
            sh.mark("변경")
        sh.row += 1
        for j in (gone_rows or {}).get(i, []):
            gone_row(j)
    sh.row += 1


def _part_sheet(wb, name: str, pd: PartDiff) -> dict:
    ws = wb.create_sheet(name)
    p = pd.new or pd.old
    gone_part = pd.new is None
    width = max([len(x[1].header) for x in p.items if x[0] == "t"] + [len(x[1].header) for x in (pd.old.items if pd.old else []) if x[0] == "t"] + [6])
    ws.cell(1, 1, f"{p.key} {p.title[:80]}".strip()).font = Font(name=wp.FONT, size=14, bold=True)
    sub = ("옛 판에만 있는 부분이다" if gone_part else ("새 판에만 있는 부분이다" if pd.old is None else
           (f"옛 판 {pd.old.key}" + (f" · 옛 제목 「{pd.old.title[:60]}」" if pd.old.title != pd.new.title else ""))))
    ws.cell(2, 1, sub + ". 빨간 글자: 바뀐 칸 · 문단(옛 값은 칸 메모) · 빨간 바탕: 새 줄 · 새 문단 · 새 열 · 회색 취소선: 없어진 것 · 노란 바탕: 옮긴 것"
            ).font = wp.font(size=9, color=wp.MUTED)
    sh = _Sheet(ws, width)
    sh.anchor[None] = "A1"
    if gone_part or pd.old is None:
        status = "삭제" if gone_part else "추가"
        for k, x in enumerate(p.items):
            if x[0] == "p":
                sh.para(x[1], mark=status, font=_gone_font() if gone_part else None, fill=None if gone_part else FILL_NEW, key=(("n" if not gone_part else "o", k), None))
            else:
                _table(sh, ("n" if not gone_part else "o", k), x[1], pd, k, status=status)
    else:
        by_kind: dict = {}
        for c in pd.changes:
            by_kind.setdefault((c.unit, c.kind), []).append(c)
        old_items = pd.old.items
        used_paras = set(pd.paras.values())
        used_tabs = {v[0] for v in pd.tables.values()}
        split_ids, split_new = set(), set()                    # 나뉨 · 합침의 옛 표는 짝 표 안에서 보인다. 새 표 조각에는 없어진 줄을 끼우지 않는다
        for c in pd.changes:
            if c.unit == "표" and c.kind in ("나뉨", "합침"):
                split_ids |= {s.strip() for s in str(c.old).split(",")}
                split_new |= {s.strip() for s in str(c.new).split(",")}
        gone_items: dict[int, list] = {}
        pairs_all = dict(pd.paras)
        pairs_all.update({k: v[0] for k, v in pd.tables.items()})
        for j, x in enumerate(old_items):
            if x[0] == "p" and j not in used_paras:
                gone_items.setdefault(_near(pairs_all, j), []).append(j)
            elif x[0] == "t" and j not in used_tabs and x[1].id not in split_ids:
                gone_items.setdefault(_near(pairs_all, j), []).append(j)

        def put_gone(n):
            for j in gone_items.get(n, []):
                x = old_items[j]
                if x[0] == "p":
                    sh.para(x[1], mark="삭제", font=_gone_font(), key=(("o", j), None))
                else:
                    _table(sh, ("o", j), x[1], pd, None, status="삭제")

        put_gone(-1)
        for k, x in enumerate(pd.new.items):
            if x[0] == "p":
                j = pd.paras.get(k)
                if j is None:
                    sh.para(x[1], mark="추가", fill=FILL_NEW, font=wp.font(color=RED), key=(("n", k), None))
                else:
                    o = old_items[j][1]
                    moved = k in pd.moved
                    if o.strip() != x[1].strip() and " ".join(o.split()) != " ".join(x[1].split()):
                        _, rich = _rich_diff(o, x[1], width=10 ** 6)
                        sh.para(rich, mark="변경", comment=f"옛 문단: {o}", fill=FILL_MOVED if moved else None, key=(("n", k), None))
                    else:
                        sh.para(x[1], mark="옮김" if moved else "", fill=FILL_MOVED if moved else None, key=(("n", k), None))
            else:
                t = x[1]
                if k in pd.tables:
                    j, rows, cols = pd.tables[k]
                    q = old_items[j][1]
                    changed = {}
                    for c in pd.changes:
                        if c.unit == "칸" and c.anchor and c.anchor[1] == ("n", k):
                            changed[(c.anchor[2], c.anchor[3])] = c.old
                    gone_rows: dict = {}
                    back = set(rows.values())
                    if t.id not in split_new:
                        for jj in range(len(q.rows)):
                            if jj not in back:
                                gone_rows.setdefault(_near(rows, jj), []).append(jj)
                    head_changed = {c.anchor[3]: c.old for c in pd.changes if c.unit == "머리줄" and c.anchor and c.anchor[1] == ("n", k)}
                    new_cols = [i for i in range(1, len(t.header)) if i not in cols]
                    gone_cols = [q.header[jj] or f"{jj + 1}번째 열" for jj in range(1, len(q.header)) if jj not in cols.values()] if t.id not in split_new else []
                    _table(sh, ("n", k), t, pd, k, status="옮김" if k in pd.moved else "", old=q, rows=rows, cols=cols,
                           moved_rows=pd.moved_rows.get(k, ()), changed=changed, gone_rows=gone_rows, new_cols=new_cols, gone_cols=gone_cols,
                           head_changed=head_changed)
                else:
                    _table(sh, ("n", k), t, pd, k, status="추가")
            put_gone(k)
    ws.column_dimensions["A"].width = 6
    for j in range(2, 2 + width):
        ws.column_dimensions[L(j)].width = 34 if j == 2 else 16
    ws.freeze_panes = "B4"
    print_setup(ws, 1)
    return sh.anchor


def _cell_for(anchors: dict, c: Change) -> str:
    if not c.anchor:
        return "A1"
    _, item, r, col = c.anchor
    if item is None:
        return anchors.get(None, "A1")
    if r is None:
        return anchors.get((item, None), "A1")
    if isinstance(r, tuple):
        return anchors.get((item, r, 0)) or anchors.get((item, -1, 0), "A1")
    return anchors.get((item, r, col)) or anchors.get((item, r, 0)) or anchors.get((item, -1, 0), "A1")


def write(path: Path, res: Result, command: str = "") -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = SUMMARY
    ch = wb.create_sheet(CHANGES)
    used: set = set()
    sheets, anchors = {}, {}
    for n, pd in enumerate(res.parts):
        if not pd.changes:
            continue
        name = _sheet_name(pd.key, used, "옛_" if pd.new is None else "")
        sheets[n] = name
        anchors[n] = _part_sheet(wb, name, pd)
    _summary(ws, res, sheets, command)
    _changes(ch, res, sheets, anchors)
    if res.leftovers:
        _leftovers(wb.create_sheet(LEFTOVERS, 2), res)
    path.parent.mkdir(parents=True, exist_ok=True)
    style.finish(wb)
    wb.save(path)
    return path


def _leftovers(ws, res: Result):
    """같이 고칠 곳 후보(2026-11-04). 새 판에서 고친 옛 값이 옛 판의 다른 곳에도 있었는데 새 판에서 그곳은 그대로인 것."""
    ws.cell(1, 1, "같이 고칠 곳 후보").font = Font(name=wp.FONT, size=14, bold=True)
    ws.cell(2, 1, "새 판에서 고친 옛 값이 옛 판의 다른 표 · 문단에도 있었는데 새 판에서 그곳은 그대로다. 같이 고쳐야 하는지, 그대로가 맞는지 본다. "
                  "같은 표 · 같은 문단 안은 보지 않았고, 고친 칸이 당기 열이면 전기 · 기초 칸은 뺐다. 금액만 같은 우연일 수 있다."
            ).font = wp.font(size=9, color=wp.MUTED)
    head = ("순번", "남은 곳 부분", "남은 곳", "그대로 남은 값", "고친 곳", "고친 곳 새 값", "남은 문단 글", "검토 메모")
    for j, h in enumerate(head, 1):
        _style_head(ws.cell(3, j, h))
    for n, x in enumerate(res.leftovers, 1):
        vals = (n, x.part, x.where, x.value, x.changed, x.new_value, x.text, None)
        for j, v in enumerate(vals, 1):
            c = ws.cell(n + 3, j, v)
            c.alignment = Alignment(vertical="top", wrap_text=j in (3, 5, 7, 8))
            if isinstance(v, (int, float)) and not isinstance(v, bool) and j > 1:
                c.number_format = NUM
        ws.cell(n + 3, 8).fill = style.FILL_IN                      # 감사인 기입란
    ws.freeze_panes = "A4"
    for col, w in zip("ABCDEFGH", (6, 12, 40, 16, 40, 16, 40, 30)):
        ws.column_dimensions[col].width = w
    print_setup(ws, 3)


def _summary(ws, res: Result, sheets: dict, command: str):
    ws.cell(1, 1, "판 비교").font = Font(name=wp.FONT, size=14, bold=True)
    info = [("옛 판", res.old.source, res.old.sha256[:12]), ("새 판", res.new.source, res.new.sha256[:12])]
    for r, (a, b, h) in enumerate(info, 2):
        ws.cell(r, 1, a).font = wp.font(bold=True)
        ws.cell(r, 2, b)
        ws.cell(r, 4, f"sha256 {h}").font = wp.font(size=9, color=wp.MUTED)
    ws.cell(4, 1, "판독 값으로 견줬다. 빈칸 · 「-」 · 0 은 같게 보고 서식 · 줄바꿈은 보지 않는다. 0건이 「서식까지 같다」 는 뜻은 아니다. "
                  "변경 수에는 주석 번호만 바뀐 것을 넣지 않았다(번호 바뀜 열). 옮김은 차례만 바뀐 것이다." + (f" 만든 명령: {command}" if command else "")
            ).font = wp.font(size=9, color=wp.MUTED)
    head = ("부분", "제목", "옛 판 부분", *KINDS[:3], "번호 바뀜", *KINDS[3:], "바뀐 숫자 칸", "차이 절댓값 합")
    for j, h in enumerate(head, 1):
        _style_head(ws.cell(6, j, h))
    r = 7
    for n, row in enumerate(summary_rows(res)):
        vals = [row[h] for h in head]
        for j, v in enumerate(vals, 1):
            x = ws.cell(r, j, v)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                x.number_format = NUM
            if n not in sheets:
                x.fill = FILL_ZERO
        if n in sheets:
            _link(ws.cell(r, 1), f"{_q(sheets[n])}A1")
        r += 1
    tot = totals(res)
    ws.cell(r, 1, "합계").font = wp.font(bold=True)
    for j, h in enumerate(head, 1):
        if j > 3:
            x = ws.cell(r, j, tot[h])
            x.font = wp.font(bold=True)
            x.number_format = NUM
    if res.leftovers:                                # 같이 고칠 곳 후보(2026-11-04)
        x = ws.cell(r + 2, 1, f"같이 고칠 곳 후보 {len(res.leftovers)}곳: 새 판에서 고친 옛 값이 다른 곳에 그대로 남았다(「같이 고칠 곳」 시트)")
        x.font = wp.font(bold=True, color=RED)
        _link(x, f"{_q(LEFTOVERS)}A1")
    ws.freeze_panes = "B7"
    for col, w in zip("ABCDEFGHIJKLM", (16, 40, 12, 7, 7, 7, 9, 7, 7, 7, 11, 16, 8)):
        ws.column_dimensions[col].width = w
    print_setup(ws, 6)


def _changes(ws, res: Result, sheets: dict, anchors: dict):
    ws.cell(1, 1, "바뀐 곳").font = Font(name=wp.FONT, size=14, bold=True)
    ws.cell(2, 1, "새 판 차례. 숫자 칸은 옛 값 · 새 값 · 차이(새 - 옛), 글은 바뀐 글자를 빨갛게 적었다. 부분을 누르면 그 칸으로 간다."
            ).font = wp.font(size=9, color=wp.MUTED)
    head = ("순번", "종류", "단위", "부분", "위치", "옛", "새", "차이", "메모")
    for j, h in enumerate(head, 1):
        _style_head(ws.cell(3, j, h))
    r, n = 4, 1
    for idx, pd in enumerate(res.parts):
        for c in pd.changes:
            old, new = c.old, c.new
            if c.kind == "변경" and c.unit in TEXT_KINDS and not c.numeric and isinstance(old, str) and isinstance(new, str):
                old, new = _rich_diff(old, new)
            vals = (n, c.kind, c.unit, c.part, c.where, old, new, c.diff, c.memo)
            for j, v in enumerate(vals, 1):
                x = ws.cell(r, j, v)
                x.alignment = Alignment(vertical="top", wrap_text=j in (5, 6, 7, 9))
                if isinstance(v, (int, float)) and not isinstance(v, bool) and j > 1:
                    x.number_format = NUM
                if j == 2:
                    x.font = wp.font(bold=True, color=RED if c.kind in ("추가", "변경") else (GRAY if c.kind == "삭제" else None))
            if idx in sheets:
                _link(ws.cell(r, 4), f"{_q(sheets[idx])}{_cell_for(anchors[idx], c)}")
            r += 1
            n += 1
    ws.auto_filter.ref = f"A3:I{max(r - 1, 4)}"
    ws.freeze_panes = "A4"
    for col, w in zip("ABCDEFGHI", (6, 7, 7, 14, 40, 40, 40, 14, 24)):
        ws.column_dimensions[col].width = w
    print_setup(ws, 3)
