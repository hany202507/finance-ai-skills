"""원고 엑셀 → dsd(2026-10-26, DSD 네 기능 설계 3.2 의 A). `python -m audit dsd build <원고.xlsx> [--out 파일]`.

바탕 고치기(바탕이 dsd): 원고 엑셀의 _원본 시트에 든 바탕 contents.xml 에서 고친 요소의 글자 구간만 바꾼다(dsd_source).
  손대지 않은 요소는 그대로         원고를 고치지 않고 만들면 contents.xml 이 바이트까지 바탕과 같다
  문단 · 칸 글                     바뀐 글이 SPAN · 줄 글 한 조각 안이면 그 조각만 바꿔 서식을 남긴다. 조각을 넘으면 요소 글 전체를 바꾸고 「서식 잃음」
  숫자 칸                          원문 꼴(괄호 · △ 음수, 「-」, 쉼표, 끝 글자)로 다시 쓴다
  줄 더하기                        같은 표의 위 줄(없으면 아래 줄) TR 을 복사. ACOPY="Y" 인 줄만, 병합 칸이 든 줄은 막는다
  줄 지우기                        ADELETE="Y" 인 줄만, 병합 칸이 든 줄은 막는다
  문단 더하기 · 지우기             이웃 P 를 복사해 넣는다 · 그 P 를 뺀다
  주석 빼기 · 번호 다시 매기기      목차 시트. 번호는 주석 제목과 본문 · 표 칸의 「주석 N」 을 같은 대응표로 바꾼다
  열 더하기 · 지우기                1차는 막는다(원고 검사에 적는다)
  TU 날짜 칸                       글을 고치면 AUNITVALUE 도 같은 날짜로
틀로 쓰기(바탕이 공시 xml): dsd.write_dsd 의 틀(별도 감사보고서)에 원고를 블록으로 넣는다(frame).

만든 dsd 는 zip 주석에 「원고판」 표시를 남긴다. report dart 가 덮어쓰는 엔진 파일(audit-engine)로 보지 않는다.
요약 코드(SUMMARY)는 옮기거나 새로 채우지 않는다. 바탕 값이 남아 있으면 원고 검사에 적는다(감사의견 구분은 8600 에서 채운다).
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

from .base import norm
from . import dsd_draft, dsd_draft_book as RB
from .dsd_draft import CELLS, Draft, format_num, parse_num
from .dsd_draft_book import issue, value_text
from .dsd_source import Node, Source, escape, shown

STAMP = "원고판"


@dataclass
class Plan:
    edits: list = field(default_factory=list)          # (시작, 끝, 새 바이트)
    issues: list = field(default_factory=list)
    changed: int = 0                                   # 바꾼 요소 수
    added: int = 0
    removed: int = 0
    rolled: bool = False                               # 롤포워드 원고(지우지 못한 재작년 줄의 숫자를 비운다)


# ---------------------------------------------------------------- 글 조각
def _segments(src: Source, n: Node) -> list[tuple[int, int, str]] | None:
    """요소 글의 조각 [(시작, 끝, 원고 글)]. 자식 요소 안에 또 요소가 있으면 None(조각으로 못 나눈다)."""
    if n.es is None:
        return [(n.se, n.se, "")]
    out = []
    pos = n.se
    for c in n.kids:
        if c.kids:
            return None
        out.append((pos, c.s, shown(_text_between(src, pos, c.s))))
        if c.es is None:
            out.append((c.se, c.se, ""))
        else:
            out.append((c.se, c.es, shown(src.text(c))))
        pos = c.e
    out.append((pos, n.es, shown(_text_between(src, pos, n.es))))
    return out


def _text_between(src: Source, a: int, b: int) -> str:
    from xml.sax.saxutils import unescape

    return unescape(src.raw[a:b].decode("utf-8"), {"&quot;": '"', "&apos;": "'"})


def _escape_like(old_raw: bytes, new: str) -> str:
    """escape 와 같되 원문 조각의 줄바꿈 꼴(글 속 줄바꿈 문자 · &amp;cr;)을 차례대로 살린다. 줄바꿈 수가 같을 때만.
    원문의 글 속 줄바꿈 문자를 &cr;(편집기 줄바꿈)로 바꾸면 편집기 화면에서 「12,345」 와 「주」 가 두 줄로 갈렸다(2026-11-06)."""
    out = escape(new)
    try:
        kinds = re.findall(r"\r?\n|&amp;cr;", old_raw.decode("utf-8"))
    except UnicodeDecodeError:
        return out
    parts = out.split("&amp;cr;")
    if all(k == "&amp;cr;" for k in kinds) or len(parts) - 1 != len(kinds):
        return out
    return parts[0] + "".join(k + p for k, p in zip(kinds, parts[1:]))


def text_edit(src: Source, n: Node, new: str) -> tuple[list, bool]:
    """요소 글을 new 로. (고침 구간들, 서식을 잃었는지). 바뀐 곳이 한 조각 안이면 그 조각만, 아니면 안 글 전체를 바꾼다."""
    new = new.replace("\r\n", "\n").replace("\r", "\n")
    segs = _segments(src, n)
    if segs is not None:
        old = "".join(s[2] for s in segs)
        if old == new:
            return [], False
        bounds, k = [], 0
        for a, b, t in segs:
            bounds.append((k, k + len(t)))
            k += len(t)
        ops = [op for op in SequenceMatcher(None, old, new, autojunk=False).get_opcodes() if op[0] != "equal"]
        touched: dict[int, list] = {}
        ok = True
        for tag, i1, i2, j1, j2 in ops:
            hit = [s for s, (x, y) in enumerate(bounds) if (x <= i1 < y) or (x < i2 <= y) or (i1 == i2 and x <= i1 <= y)]
            if len(hit) != 1:
                ok = False
                break
            touched.setdefault(hit[0], []).append((tag, i1, i2, j1, j2))
        if ok and touched:
            edits = []
            for s, items in touched.items():
                a, b, t = segs[s]
                x0 = bounds[s][0]
                piece = list(t)
                for tag, i1, i2, j1, j2 in sorted(items, key=lambda z: -z[1]):
                    piece[i1 - x0:i2 - x0] = list(new[j1:j2])
                edits.append((a, b, _escape_like(src.raw[a:b], "".join(piece)).encode("utf-8")))
            return edits, False
    if n.es is None:
        return [], True
    lost = bool(n.kids)
    return [(n.se, n.es, escape(new).encode("utf-8"))], lost


# ---------------------------------------------------------------- 표 구조
def _grid(t: Node) -> tuple[list, dict, dict]:
    """TABLE 의 (TR 목록, {TR: [칸 노드 · None(덮임)]}, {TR: 병합이 걸린 줄인지})."""
    trs = []
    for sec in t.kids:
        if sec.tag in ("THEAD", "TBODY"):
            trs += sec.findall("TR")
    taken: dict = {}
    cells, spanned = {}, {}
    for r, tr in enumerate(trs):
        row, c, sp = [], 0, False
        for n in tr.kids:
            if n.tag not in CELLS:
                continue
            while (r, c) in taken:
                row.append(None)
                sp = True
                c += 1
            rs, cs = int(n.get("ROWSPAN") or 1), int(n.get("COLSPAN") or 1)
            if rs > 1:
                sp = True
            row.append(n)
            for dr in range(rs):
                for dc in range(cs):
                    if dr or dc:
                        taken[(r + dr, c + dc)] = True
            for _ in range(cs - 1):
                c += 1
                row.append(None)
            c += 1
        while (r, c) in taken:
            row.append(None)
            sp = True
            c += 1
        cells[tr.k], spanned[tr.k] = row, sp
    return trs, cells, spanned


def _tu_date(text: str) -> str | None:
    m = re.search(r"(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일", text)
    return f"{int(m.group(1)):04d}{int(m.group(2)):02d}{int(m.group(3)):02d}" if m else None


# ---------------------------------------------------------------- 계획
_DASH = {"-", "－", "—", "–"}


def _cell_value(rv, orig: dsd_draft.Cell, sheet: str, where: str, plan: Plan, cached=None) -> str | None:
    """원고 칸 → 새 원문 글. 그대로면 None."""
    text, num, note = value_text(rv, cached)
    if note:
        level = "막음" if note.startswith(("날짜로", "계산되지", "수식 오류")) else "확인"
        plan.issues.append(issue("엑셀 손상", sheet, where, note + (f" · 원문 「{orig.text}」 을 그대로 둔다" if level == "막음" else ""), level))
        if level == "막음":
            return None
    if orig.num is not None:
        if num is None and text.strip():
            v, f = parse_num(text)
            if v is None:
                if orig.text.strip() not in _DASH:   # 「-」 만 있던 칸은 빈칸이다. 롤포워드가 글을 옮겨 넣어도 손상이 아니다(2026-11-07)
                    plan.issues.append(issue("엑셀 손상", sheet, where, f"숫자였던 칸이 글자가 됨: 「{text[:40]}」"))
                return text if text != orig.text else None
            num = v
        if num is None:
            return "" if orig.text.strip() else None
        if abs(float(num) - float(orig.num)) < 1e-9:
            return None
        if num == 0 and not (orig.fmt or {}).get("zero"):
            return "-"                                     # dsd 는 0 을 「-」 로 적는다(롤포워드가 「-」 를 「0」 으로 바꿨다, 2026-11-06 D8)
        return format_num(num, orig.fmt)
    if num is not None and not orig.text.strip():
        # 빈칸이던 칸(롤포워드가 옮긴 전기 칸 등)은 원문 꼴이 없어 쉼표 · 괄호 음수로 쓴다. 원고 숫자를 그대로 쓰면
        # 「36000000」 이 됐다(2026-11-09 공개 원문 2024 → 2025 초안을 실제 2025 공시와 칸마다 견준 시험)
        # 사용자가 엑셀에 꼴을 갖춰 적은 글(「1,234」 · 「12.5%」)이면 그 꼴을, 숫자면 소수 자리만 살린다
        f = parse_num(text)[1] if isinstance(rv, str) and text.strip() else None
        if not (f and (f.get("comma") or f.get("suf") or f.get("dec") or f.get("neg"))):
            dec = len(repr(float(num)).split(".")[1].rstrip("0")) if not float(num).is_integer() else 0
            f = {"neg": "paren", "comma": True, "dec": min(dec, 6), "suf": ""}
        return "-" if num == 0 else format_num(num, f)
    if num is not None and text != orig.text:
        o = orig.text.strip()
        if o.isdigit() and (o.startswith("0") or len(o) >= 12):
            plan.issues.append(issue("엑셀 손상", sheet, where, f"앞자리 0 · 긴 코드가 숫자로 바뀜: 원문 「{o}」 을 그대로 둔다", "막음"))
            return None
        if parse_num(orig.text)[0] is None and orig.text.strip():
            if num == 0:
                return "-"                     # 롤포워드가 옮긴 「-」(0) 이다. 글 칸에는 「-」 로 적는다(2026-11-07 특수관계자 명단 표)
            plan.issues.append(issue("엑셀 손상", sheet, where, f"글자 칸이 숫자로 바뀜: 「{orig.text[:30]}」 → {text}"))
    new = text.replace("\r\n", "\n")
    return None if new == orig.text else new


def _num_text(rv, cached, ref: dsd_draft.Cell | None) -> str:
    text, num, _ = value_text(rv, cached)
    if num is not None:
        if num == 0 and not (ref.fmt if ref is not None and ref.fmt else {}).get("zero"):
            return "-"                                     # 새 줄도 0 은 「-」(2026-11-06 D8)
        return format_num(num, ref.fmt if ref is not None and ref.fmt else None)
    return text


def plan(r: RB.Read) -> tuple[Plan, Draft, Source]:
    orig = dsd_draft.from_raw(r.contents, r.meta, r.base)
    src = Source(r.contents)
    p = Plan(issues=list(r.issues), rolled=bool(r.info.get("rolled")))   # 첫 인자는 edits 다. 원고 읽기 경고가 고칠 목록에 들어가 build 가 멈췄다(2026-11-09)
    names = {RB._sheet_name(s.key): s for s in orig.sheets}
    excel = dict(r.sheets)
    toc_names = {t[0] for t in r.toc}
    # 목차: 빠진 주석 · 번호
    renum = {}
    if r.toc:
        for t_name, n, _ in r.toc:
            s = names.get(t_name)
            if s is not None and s.note is not None and n is not None and n != s.note:
                renum[s.note] = n
    if renum:
        _renumber(orig, excel, names, renum)
    for name, s in names.items():
        if r.toc and name not in toc_names:
            if s.kind != "주석":
                p.issues.append(issue("목차", "목차", name, "주석이 아닌 시트는 목차에서 지워도 빼지 않는다", "막음"))
                continue
            for ln in s.lines:
                if ln.kind in ("제목", "문단", "표", "글 표") and ln.loc is not None:
                    n = src.nodes[ln.loc]
                    p.edits.append((n.s, n.e, b""))
            p.removed += 1
            continue
        if name not in excel:
            p.issues.append(issue("엑셀 손상", name, "", "시트가 없어졌거나 이름이 바뀌었다. 이 부분은 바탕 그대로 둔다", "막음"))
            continue
        _sheet_plan(src, s, name, excel[name], p)
    _roll_checks(r, orig, excel, p)
    for name in excel:
        if name not in names:
            p.issues.append(issue("엑셀 손상", name, "", "바탕에 없는 시트다(새 시트는 dsd 로 옮기지 않는다)", "막음"))
    return p, orig, src


def _roll_checks(r: RB.Read, orig: Draft, excel: dict, p: Plan) -> None:
    """롤포워드한 원고에서 남은 곳: 당기 칸이 빈 표, 당기 칸이 바탕 판(작년 판) 당기 칸과 같은 표(옮기기만 하고 새 숫자를 넣지 않음)."""
    idx = dsd_draft.cell_index(orig)
    for t in r.info.get("rolled_tables") or []:
        name = RB._sheet_name(t["sheet"])
        rl = {x.loc: x for x in excel.get(name) or [] if x.loc is not None}
        new_vals, old_vals = [], []
        for loc in t.get("cells") or []:
            if loc not in idx:
                continue
            key, i, j, oc = idx[loc]
            line = next((s for s in orig.sheets if s.key == key)).lines[i]
            x = rl.get(line.loc)
            if x is None:
                continue
            v = x.values[j] if j < len(x.values) else None
            new_vals.append(value_text(v, x.cached[j] if j < len(x.cached) else None)[1])
            old_vals.append(oc.num)
        if not new_vals:
            continue
        where = f"표 {t['table']}"
        if all(v is None for v in new_vals):
            p.issues.append(issue("롤포워드", name, where, "당기 칸이 비어 있다(전기로 옮기기만 했다)"))
        elif any(o is not None for o in old_vals) and all((v or 0) == (o or 0) for v, o in zip(new_vals, old_vals)):
            p.issues.append(issue("롤포워드", name, where, "당기 칸이 바탕 판(작년 판) 당기 칸과 같다. 새 숫자를 넣지 않았다"))


def _sheet_plan(src: Source, s: dsd_draft.Sheet, name: str, rlines: list, p: Plan) -> None:
    orig_by_loc = {ln.loc: ln for ln in s.lines if ln.loc is not None}
    seen: set = set()
    order: list[int] = []
    anchor: Node | None = None                         # 새 문단 · 표를 넣을 곳(바로 앞 요소)
    base_p: Node | None = next((src.nodes[ln.loc] for ln in s.lines if ln.kind in ("문단", "제목") and ln.loc is not None
                                and src.nodes[ln.loc].tag == "P"), None)
    pending: dict = {}                                 # anchor 요소 끝 → [새 바이트]
    i = 0
    while i < len(rlines):
        rl = rlines[i]
        if rl.kind in ("표", "글 표"):
            j = i + 1
            while j < len(rlines) and rlines[j].kind != "표끝":
                j += 1
            block = rlines[i:j + 1]
            ol = orig_by_loc.get(rl.loc) if rl.loc is not None and rl.loc not in seen else None
            if ol is None or ol.kind not in ("표", "글 표"):
                p.issues.append(issue("dsd 로 옮기기", name, f"A{rl.row}", "새 표는 1차에서 dsd 로 옮기지 않는다(같은 주석의 표를 복사하는 기능은 다음 판)", "막음"))
            else:
                seen.add(rl.loc)
                order.append(rl.loc)
                _table_plan(src, s, name, src.nodes[rl.loc], block, p, seen)
                anchor = src.nodes[rl.loc]
            i = j + 1
            continue
        if rl.kind in ("머리", "줄", "표끝"):
            i += 1
            continue
        text, _, note = value_text(rl.values[0] if rl.values else None, rl.cached[0] if rl.cached else None)
        if rl.loc is not None and rl.loc in orig_by_loc and rl.loc not in seen and orig_by_loc[rl.loc].kind in ("문단", "제목"):
            seen.add(rl.loc)
            order.append(rl.loc)
            n = src.nodes[rl.loc]
            ol = orig_by_loc[rl.loc]
            if note:
                p.issues.append(issue("엑셀 손상", name, f"C{rl.row}", note))
            new = text.replace("\r\n", "\n")
            if new != ol.cells[0].text:
                edits, lost = text_edit(src, n, new)
                p.edits += edits
                p.changed += 1 if edits else 0
                if lost:
                    p.issues.append(issue("서식 잃음", name, f"C{rl.row}", "부분 서식(굵게 등)이 있던 문단의 여러 곳을 고쳐 문단 글 전체를 바꿨다. 편집기에서 서식을 확인한다"))
            anchor = n
        else:
            if not text.strip():
                i += 1
                continue
            at = anchor if anchor is not None else (src.nodes[s.lines[0].loc] if s.lines and s.lines[0].loc is not None else None)
            if at is None:
                p.issues.append(issue("dsd 로 옮기기", name, f"C{rl.row}", "넣을 곳을 찾지 못한 새 문단", "막음"))
            else:
                start = src.raw[base_p.s:base_p.se] if base_p is not None and not base_p.kids else b"<P>"
                key = at.e
                pending.setdefault(key, []).append(b"\n" + start + escape(text).encode("utf-8") + b"</P>")
                p.added += 1
        i += 1
    for loc, ln in orig_by_loc.items():
        if loc not in seen and ln.kind in ("문단", "제목"):
            n = src.nodes[loc]
            p.edits.append((n.s, n.e, b""))
            p.removed += 1
    if order != sorted(order):
        p.issues.append(issue("엑셀 손상", name, "", "위치 번호 차례가 바탕과 다르다(줄을 잘라 붙이거나 정렬했다). 차례는 바꾸지 않고 글만 옮겼다", "막음"))
    for key, chunks in pending.items():
        p.edits.append((key, key, b"".join(chunks)))


def _table_plan(src: Source, s: dsd_draft.Sheet, name: str, t: Node, block: list, p: Plan, seen: set) -> None:
    trs, cells, spanned = _grid(t)
    orig = {ln.loc: ln for ln in s.lines if ln.kind in ("머리", "줄") and ln.loc is not None and src.nodes[ln.loc].parent is not None
            and src.nodes[ln.loc].parent.parent is t}
    rows = [rl for rl in block if rl.kind in ("머리", "줄")]
    width = max([len(ln.cells) for ln in orig.values()] + [0])
    used: set = set()
    prev_tr: Node | None = None
    pending: dict = {}
    order = []
    row_of = {tr.k: i for i, tr in enumerate(trs)}
    seq: list = []                                     # 원고 차례: ("old", 바탕 줄 차례) · ("new", 원고 줄, 넣을 곳, 위 줄 뒤인지)
    for rl in rows:
        ol = orig.get(rl.loc) if rl.loc is not None and rl.loc not in used else None
        if rl.loc is not None and rl.loc in used:
            p.issues.append(issue("엑셀 손상", name, f"B{rl.row}", "같은 위치 번호가 두 줄에 있다(줄을 복사해 붙였다). 아래 줄을 새 줄로 본다"))
        if len(rl.values) > width and any(v not in (None, "") for v in rl.values[width:]):
            p.issues.append(issue("dsd 로 옮기기", name, f"{RB.L(RB.C0 + width)}{rl.row}", "표에 열을 더했다. 열 추가 · 삭제는 1차에서 막는다", "막음"))
        if ol is not None:
            used.add(rl.loc)
            seen.add(rl.loc)
            order.append(rl.loc)
            tr = src.nodes[rl.loc]
            row_nodes = cells[tr.k]
            for j, oc in enumerate(ol.cells):
                rv = rl.values[j] if j < len(rl.values) else None
                cv = rl.cached[j] if j < len(rl.cached) else None
                where = f"{RB.L(RB.C0 + j)}{rl.row}"
                if oc.covered or oc.loc is None:
                    if rv not in (None, ""):
                        p.issues.append(issue("엑셀 손상", name, where, "병합으로 덮인 칸에 글을 썼다. dsd 로 옮기지 않는다", "막음"))
                    continue
                new = _cell_value(rv, oc, name, where, p, cv)
                if new is None:
                    continue
                n = src.nodes[oc.loc]
                edits, lost = text_edit(src, n, new)
                p.edits += edits
                p.changed += 1 if edits else 0
                if lost and new.strip():           # 비운 칸(롤포워드 당기 칸)은 서식이 남을 글이 없다(2026-11-06)
                    p.issues.append(issue("서식 잃음", name, where, "칸 안 서식을 잃었다"))
                if n.tag == "TU" and n.get("AUNITVALUE") is not None:
                    d = _tu_date(new)
                    if d:
                        p.edits += _attr_edit(src, n, "AUNITVALUE", d)
            prev_tr = tr
            seq.append(("old", row_of[tr.k]))
            continue
        # 새 줄: 넣을 곳만 적어 두고, 세로 병합을 맞추며 만든다(_place_rows)
        if all(v in (None, "") for v in rl.values):
            continue
        if not trs:
            p.issues.append(issue("dsd 로 옮기기", name, f"A{rl.row}", "복사할 줄이 없는 표", "막음"))
            continue
        body = next((tr for tr in trs if tr.parent is not None and tr.parent.tag != "THEAD"), None)
        if prev_tr is not None and not (rl.kind == "줄" and prev_tr.parent is not None and prev_tr.parent.tag == "THEAD" and body is not None):
            seq.append(("new", rl, prev_tr.e, True))
        else:                                      # 표 첫 줄, 또는 머리(THEAD) 바로 아래 본문 줄: 본문 첫 줄 앞에 넣는다. 머리 안에 넣었다(2026-11-10)
            seq.append(("new", rl, (body or trs[0]).s, False))
    stay = []
    for loc, ln in orig.items():
        if loc in used:
            continue
        tr = src.nodes[loc]
        if (tr.get("ADELETE") or "").upper() != "Y":
            # 롤포워드 원고: 지우지 못한 줄은 재작년 줄이라 숫자가 전기 칸에 남았다. 숫자만 비워 남긴다(2026-11-09 전수 대조)
            blank = _blank_numbers(src, ln, p) if p.rolled else 0
            p.issues.append(issue("dsd 로 옮기기", name, "", "편집기가 지우기를 허용하지 않은 줄(ADELETE)이라 지우지 않았다"
                                  + (f"(숫자 칸 {blank}개는 비웠다. 편집기에서 줄을 지운다)" if blank else "") + f": 「{_row_label(ln)}」", "막음"))
            stay.append(row_of[tr.k])
            continue
        p.edits.append((tr.s, tr.e, b""))
        p.removed += 1
    _place_rows(src, name, t, trs, orig, _final_rows(seq, stay), p, pending)
    if order != sorted(order):
        p.issues.append(issue("엑셀 손상", name, "", "표 줄의 위치 번호 차례가 바탕과 다르다(줄을 옮기거나 정렬했다). 줄 차례는 바꾸지 않았다", "막음"))
    for key, chunks in pending.items():
        p.edits.append((key, key, b"".join(chunks)))


def _span(n: Node) -> tuple[int, int]:
    def one(v):
        try:
            return max(1, int(v or 1))
        except ValueError:
            return 1
    return one(n.get("ROWSPAN")), one(n.get("COLSPAN"))


def _layout(trs: list) -> list[dict]:
    """줄마다 {열: (칸 노드, 칸이 시작하는 줄, 시작 열)}. 세로 · 가로 병합으로 덮인 열도 덮는 칸으로 적는다."""
    taken: dict = {}
    out = []
    for r, tr in enumerate(trs):
        row, c = {}, 0
        for n in tr.kids:
            if n.tag not in CELLS:
                continue
            while (r, c) in taken:
                row[c] = taken[(r, c)]
                c += 1
            rs, cs = _span(n)
            for dr in range(rs):
                for dc in range(cs):
                    taken[(r + dr, c + dc)] = (n, r, c)
            for dc in range(cs):
                row[c + dc] = (n, r, c)
            c += cs
        while (r, c) in taken:
            row[c] = taken[(r, c)]
            c += 1
        out.append(row)
    return out


def _grid_problems(src: Source) -> "Counter":
    """표마다 칸 모양 어긋남: 세로 병합이 머리(THEAD) · 본문(TBODY) 경계나 표 끝을 넘는 칸, 줄마다 다른 칸 수.
    {(표 첫 칸 글, 어긋남): 수}. 바탕과 견줘 새로 생긴 것만 build 가 막음으로 낸다(회사 표가 원래 고르지 않을 수 있다)."""
    from collections import Counter

    out = Counter()
    for t in (n for n in src.nodes if n.tag == "TABLE"):
        trs = [tr for sec in t.kids if sec.tag in ("THEAD", "TBODY") for tr in sec.findall("TR")]
        if not trs:
            continue
        first = next((n for tr in trs for n in tr.kids if n.tag in CELLS), None)
        head = re.sub(r"<[^>]+>", "", src.raw[first.se:first.es].decode("utf-8", "replace")).strip()[:20] if first is not None and first.es else ""
        for r, tr in enumerate(trs):
            for n in tr.kids:
                if n.tag in CELLS and _span(n)[0] > 1:
                    rs = _span(n)[0]
                    if r + rs > len(trs) or any(trs[r + d].parent is not tr.parent for d in range(1, rs)):
                        out[(head, "세로 병합이 머리 · 본문 경계나 표 끝을 넘는다")] += 1
        widths = [max(row) + 1 if row else 0 for row in _layout(trs)]
        if len(set(widths)) > 1:
            out[(head, "줄마다 칸 수가 다르다")] += 1
    return out


def _final_rows(seq: list, stay: list) -> list:
    """dsd 에 남을 표 줄 차례: 원고 차례(남긴 바탕 줄 · 새 줄)에 지우지 못한 바탕 줄을 바탕 차례대로 끼운다."""
    out, left = [], sorted(stay)
    for e in seq:
        if e[0] == "old":
            while left and left[0] < e[1]:
                out.append(("old", left.pop(0)))
        out.append(e)
    return out + [("old", r) for r in left]


def _place_rows(src: Source, name: str, t: Node, trs: list, orig: dict, rows: list, p: Plan, pending: dict) -> None:
    """새 줄을 만들어 넣고 세로 병합(ROWSPAN)을 남은 줄에 맞춘다(2026-11-10 요청 「오류가 있을 수 없는 스킬」).
    rows 는 dsd 에 남을 줄 차례(_final_rows). 규칙은 하나다: 덮인 칸은 바로 위 줄에서 그 열을 가진 칸에 잇는다.
      바탕 줄   바탕 표에서 위 칸에 덮인 열이 덮인 칸이다. 위 줄에 같은 열 칸이 없으면(병합 칸을 가진 줄을 지웠고 위가 다른 모양)
                바탕 병합 칸을 그 줄에 다시 넣는다.
      새 줄     원고에서 앞쪽 칸이 덮인 칸 색(롤포워드가 당기 표의 병합을 본떠 칠한 것)이면 덮인 칸이다. 남은 바탕 줄 사이에 끼었고
                아래 바탕 줄이 그 열에서 덮였고 이 줄 그 열이 비었으면 위 칸에 잇는다(사람이 묶음 안에 넣은 줄).
    새 칸 · 바탕 칸의 ROWSPAN 은 이은 줄 수다. 그 전에는 병합 칸이 든 줄을 넣지도 지우지도 못해 숫자만 비워 두었다."""
    lay = _layout(trs)
    width = max((max(r) + 1 for r in lay if r), default=0)
    info: dict = {}                            # 칸 열쇠 → {"cols", "rows"(차례들), "node"(바탕 칸 | None), "kind"(바탕 · 다시 · 새), "row"}
    cover: list = []                           # 차례마다 {열: 칸 열쇠}
    made: list = []

    def above(prev: dict, cols: range, head: bool):
        x = prev.get(cols.start)                # 머리 줄은 머리 칸에, 본문 줄은 본문 칸에만 잇는다(본문 줄이 THEAD 칸 ROWSPAN 에 들어갔다, 2026-11-10)
        return x if x is not None and info[x]["cols"] == cols and info[x]["head"] == head else None

    def head_row(r: int) -> bool:
        ln = orig.get(trs[r].k)
        return (trs[r].parent is not None and trs[r].parent.tag == "THEAD") or (ln is not None and ln.kind == "머리")

    def text_of(r: int, c: int) -> str:
        ln = orig.get(trs[r].k)
        return norm_text(ln.cells[c].text) if ln is not None and c < len(ln.cells) else ""

    for k, e in enumerate(rows):
        prev = cover[-1] if cover else {}
        if e[0] == "old":
            r = e[1]
            row = {}
            for c0, (n, r0) in sorted({c0: (n, r0) for n, r0, c0 in lay[r].values()}.items()):
                cols = range(c0, c0 + _span(n)[1])
                if r0 == r:
                    x = n.k
                    info[x] = {"cols": cols, "rows": [k], "node": n, "kind": "바탕", "row": r, "head": head_row(r), "text": text_of(r, c0)}
                else:
                    # 바탕 줄은 바탕 병합 칸(남았거나 다시 넣은 것)이나, 같은 글의 새 줄 칸(당기 표에서 묶음 첫 줄을 가져온 것)에만 잇는다
                    x = above(prev, cols, head_row(r))
                    if x is not None and not (x == n.k or info[x]["node"] is n or (info[x]["kind"] == "새" and info[x]["text"] == text_of(r0, c0))):
                        x = None
                    if x is None:
                        x = ("다시", k, c0)
                        info[x] = {"cols": cols, "rows": [k], "node": n, "kind": "다시", "row": r, "head": head_row(r), "text": text_of(r0, c0)}
                    else:
                        info[x]["rows"].append(k)
                for c in cols:
                    row[c] = x
            cover.append(row)
            continue
        _, rl, key, after = e
        nxt = next((rows[m][1] for m in range(k + 1, len(rows)) if rows[m][0] == "old"), None)
        vals, gray = rl.values, getattr(rl, "gray", None) or []
        lead = next((j for j in range(max(len(vals), len(gray))) if not (j < len(gray) and gray[j])), len(vals))
        join, drop = [], set()
        for x in dict.fromkeys(prev.values()):
            cols = info[x]["cols"]
            if info[x]["head"] != (rl.kind == "머리"):
                continue
            inside = (nxt is not None and all(c in lay[nxt] and lay[nxt][c][1] < nxt for c in cols)
                      and all(c >= len(vals) or vals[c] in (None, "") for c in cols))
            if cols.stop <= lead or inside:
                join.append(x)
                drop |= set(cols)
        need = [j for j, v in enumerate(vals) if v not in (None, "") and j not in drop]
        g2 = {j for j in range(len(gray)) if gray[j] and j not in drop}
        pos = next((rows[m][1] for m in range(k - 1, -1, -1) if rows[m][0] == "old"), 0)
        i = _template(trs, lay, orig, width, pos, rl.kind, drop, need, g2)
        if i is None:
            p.issues.append(issue("dsd 로 옮기기", name, f"A{rl.row}", "값이 든 칸과 칸 모양이 맞는 줄(복사를 허용한 줄)이 표에 없어 새 줄을 넣지 못했다", "막음"))
            cover.append(prev)                 # 넣지 못한 줄: 아래 줄이 위 줄을 그대로 잇는다
            continue
        row = {}
        for x in join:
            info[x]["rows"].append(k)
            for c in info[x]["cols"]:
                row[c] = x
        for c0, n in sorted({c0: n for n, r0, c0 in lay[i].values() if r0 == i and c0 not in drop}.items()):
            x = ("새", k, c0)
            info[x] = {"cols": range(c0, c0 + _span(n)[1]), "rows": [k], "node": None, "kind": "새", "row": None, "head": rl.kind == "머리",
                       "text": norm_text(rl.values[c0]) if c0 < len(rl.values) and rl.values[c0] is not None else ""}
            for c in info[x]["cols"]:
                row[c] = x
        cover.append(row)
        made.append((k, rl, key, after, i, drop))
    for x, v in info.items():                  # 바탕 칸의 세로 병합을 이은 줄 수에 맞추고, 다시 넣을 칸을 넣는다
        n, many = v["node"], len(v["rows"])
        if v["kind"] == "바탕" and many != _span(n)[0]:
            p.edits += _attr_set(src, n, "ROWSPAN", str(many))
        elif v["kind"] == "다시":
            r = v["row"]
            at = _cell_slot(trs[r], lay[r], r, v["cols"].start)
            p.edits.append((at, at, _with_attr(src.raw[n.s:n.e], n.se - n.s, "ROWSPAN", str(many))))
    for k, rl, key, after, i, drop in made:
        spans = {x[2]: len(v["rows"]) for x, v in info.items() if v["kind"] == "새" and x[1] == k}
        new_tr = _new_tr(src, trs[i], lay[i], i, rl, orig.get(trs[i].k), drop, spans)
        pending.setdefault(key, []).append((b"\n" + new_tr) if after else (new_tr + b"\n"))
        p.added += 1
        if t.get("ACLASS") == "FINANCE":
            p.issues.append(issue("dsd 로 옮기기", name, f"A{rl.row}", "재무제표 새 과목: 단계(ALEVEL) · 계정코드(ACODE)는 본뜬 줄 것을 복사했다. 편집기에서 확인한다"))


def _template(trs: list, lay: list, orig: dict, width: int, pos: int, kind: str, drop: set, need: list, g2: set) -> int | None:
    """새 줄에 본뜰 TR 차례. 새 줄이 가질 열(drop 밖)마다 그 줄에서 시작하는 칸이 있고, 값이 든 열마다 칸이 시작하고, drop 열의 칸은
    통째로 drop 안에 있고, 복사를 허용하는(ACOPY) 줄. 가로 병합 모양이 원고 회색 칸(g2)과 같은 줄을 먼저, 같은 종류(머리 · 줄),
    가까운 줄, 같은 거리면 위 줄. 바로 위 줄만 복사하면 위 줄이 가로 병합 머리 줄일 때 새 줄 숫자가 사라졌다(2026-11-10 초안 검산)."""
    def fits(i: int, strict: bool) -> bool:
        if (trs[i].get("ACOPY") or "").upper() != "Y":
            return False
        row = lay[i]
        for c in range(width):
            got = row.get(c)
            if got is None:
                if strict and c not in drop:
                    return False
                continue
            n, r0, c0 = got
            cols = range(c0, c0 + _span(n)[1])
            if c in drop:
                if r0 == i and any(x not in drop for x in cols):
                    return False
            elif r0 != i or any(x in drop for x in cols):
                return False
        return all(j in row and row[j][1] == i and row[j][2] == j for j in need)

    def miss(i: int) -> int:
        return sum(1 for c, (n, r0, c0) in lay[i].items() if c not in drop and (c0 != c) != (c in g2))

    def kind_of(i: int) -> str:
        ln = orig.get(trs[i].k)
        return ln.kind if ln is not None else ""

    for strict in (True, False):
        cand = [i for i in range(len(trs)) if fits(i, strict)]
        if cand:
            return min(cand, key=lambda i: (miss(i), kind_of(i) != kind, abs(i - pos), i > pos))
    return None


def _attr_set(src: Source, n: Node, name: str, value: str) -> list:
    """칸 시작 태그의 속성 값을 바꾸고, 없으면 더한다."""
    tag = src.raw[n.s:n.se]
    new = _with_attr(tag, len(tag), name, value)
    return [(n.s, n.se, new)] if new != tag else []


def _with_attr(piece: bytes, se: int, name: str, value: str) -> bytes:
    tag, rest = piece[:se].decode("utf-8"), piece[se:]
    if re.search(rf'\b{name}="[^"]*"', tag):
        tag = re.sub(rf'(\b{name}=")[^"]*(")', lambda m: m.group(1) + value + m.group(2), tag, count=1)
    else:
        cut = len(tag) - (2 if tag.endswith("/>") else 1)
        tag = tag[:cut] + f' {name}="{value}"' + tag[cut:]
    return tag.encode("utf-8") + rest


def _cell_slot(tr: Node, row: dict, r: int, c0: int) -> int:
    """r 줄(tr)에 c0 열에서 시작하는 칸을 넣을 바이트 위치: 그 뒤 열에서 시작하는 첫 칸 앞, 없으면 마지막 칸 뒤."""
    own = sorted({cc: n for col, (n, rr, cc) in row.items() if rr == r}.items())
    later = [n for cc, n in own if cc > c0]
    if later:
        return later[0].s
    return own[-1][1].e if own else tr.se


def _new_tr(src: Source, tr: Node, row: dict, i: int, rl, ref, drop: set, spans: dict) -> bytes:
    """tr(i 줄)을 본떠 새 줄 바이트를 만든다: drop 열의 칸은 빼고, 남은 칸은 rl 값과 세로 병합 수(spans)로."""
    edits = []
    for col, (n, r0, c0) in sorted(row.items()):
        if r0 != i or col != c0:
            continue
        if c0 in drop:
            edits.append((n.s - tr.s, n.e - tr.s, b""))
            continue
        rs = spans.get(c0, 1)
        if _span(n)[0] != rs:
            edits.append((n.s - tr.s, n.se - tr.s, _with_attr(src.raw[n.s:n.se], n.se - n.s, "ROWSPAN", str(rs))))
        if n.es is None:
            continue
        rv = rl.values[c0] if c0 < len(rl.values) else None
        cv = rl.cached[c0] if c0 < len(rl.cached) else None
        rc = ref.cells[c0] if ref is not None and c0 < len(ref.cells) else None
        edits.append((n.se - tr.s, n.es - tr.s, escape(_num_text(rv, cv, rc)).encode("utf-8")))
    piece = src.raw[tr.s:tr.e]
    out, at = [], 0
    for a, b, new in sorted(edits):
        out.append(piece[at:a])
        out.append(new)
        at = b
    out.append(piece[at:])
    return b"".join(out)


def _blank_numbers(src: Source, ln, p: Plan) -> int:
    """줄의 숫자 칸 글을 비운다. 여러 줄을 덮는 칸(ROWSPAN)은 다른 줄 숫자이기도 해서 두고, 비운 칸 수를 돌려준다."""
    k = 0
    for c in ln.cells:
        if c.covered or c.loc is None or c.num is None or c.span[0] > 1:
            continue
        edits, _ = text_edit(src, src.nodes[c.loc], "")
        p.edits += edits
        k += 1 if edits else 0
    p.changed += k
    return k


def _row_label(ln) -> str:
    return next((c.text for c in ln.cells if c.text.strip()), "")[:30]


def _attr_edit(src: Source, n: Node, name: str, value: str) -> list:
    tag = src.raw[n.s:n.se].decode("utf-8")
    m = re.search(rf'({name}=")([^"]*)(")', tag)
    if not m or m.group(2) == value:
        return []
    a = n.s + len(tag[:m.start(2)].encode("utf-8"))
    b = n.s + len(tag[:m.end(2)].encode("utf-8"))
    return [(a, b, value.encode("utf-8"))]


_REF = re.compile(r"(주석\s*)(\d+)")


def _map_refs(text: str, renum: dict, heading: bool) -> str:
    out = _REF.sub(lambda m: m.group(1) + str(renum.get(int(m.group(2)), int(m.group(2)))), text)
    return out


def _renumber(orig: Draft, excel: dict, names: dict, renum: dict) -> None:
    """주석 번호 다시 매기기를 원고 값에 먼저 넣는다: 주석 제목 줄의 앞 번호, 글 · 칸의 「주석 N」, 재무제표 주석 열 칸(「5」 · 「5,6」).
    그 뒤의 비교가 바뀐 칸만 고친다."""
    for name, s in names.items():
        rl = excel.get(name)
        if not rl:
            continue
        head = s.lines[0].loc if s.kind == "주석" and s.lines else None
        for line in rl:
            for j, v in enumerate(line.values):
                if isinstance(v, str):
                    new = v
                    if head is not None and line.loc == head and s.note in renum:
                        new = re.sub(rf"^(\s*){s.note}(\s*\.)", lambda m: f"{m.group(1)}{renum[s.note]}{m.group(2)}", new, count=1)
                    new = _map_refs(new, renum, heading=False)
                    if s.kind == "재무제표" and re.fullmatch(r"\s*\d+(\s*,\s*\d+)*\s*", new) and line.kind == "줄" and j <= 2:
                        new = re.sub(r"\d+", lambda m: str(renum.get(int(m.group(0)), int(m.group(0)))), new)
                    line.values[j] = new
                elif s.kind == "재무제표" and isinstance(v, int) and line.kind == "줄" and 0 < j <= 2 and v in renum:
                    line.values[j] = renum[v]


# ---------------------------------------------------------------- 쓰기
def _stamp(xlsx_sha: str, base_sha: str) -> bytes:
    return json.dumps({STAMP: xlsx_sha, "바탕": base_sha}, ensure_ascii=False).encode("utf-8")


FIXED_TIME = (1980, 1, 1, 0, 0, 0)       # 압축 안 파일 시각. 같은 입력이면 바이트까지 같은 파일(2026-11-10 요청 「매번 동일하게」)


def steady_zip(path: Path, edit=None) -> None:
    """저장한 zip(엑셀 등)의 안 파일 시각을 고정해 다시 쓴다. edit(이름, 바이트) 가 있으면 그 결과로 바꿔 쓴다."""
    src = zipfile.ZipFile(io.BytesIO(path.read_bytes()))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for i in src.infolist():
            data = src.read(i.filename)
            zi = zipfile.ZipInfo(i.filename, FIXED_TIME)
            zi.compress_type, zi.external_attr = i.compress_type, i.external_attr
            z.writestr(zi, edit(i.filename, data) if edit else data)
        z.comment = src.comment
    path.write_bytes(buf.getvalue())


def zip_dsd(path: Path, contents: bytes, meta: bytes, comment: bytes = b"") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in (("contents.xml", contents), ("meta.xml", meta)):
            zi = zipfile.ZipInfo(name, FIXED_TIME)
            zi.compress_type, zi.external_attr = zipfile.ZIP_DEFLATED, 0o600 << 16
            z.writestr(zi, data)
        z.comment = comment
    path.write_bytes(buf.getvalue())
    return path


def build(xlsx: Path, out: Path | None = None) -> dict:
    """원고 엑셀로 dsd 를 만든다. {path, issues, changed, added, removed, mode}."""
    xlsx = Path(xlsx)
    r = RB.read(xlsx)
    out = Path(out) if out else xlsx.with_name(xlsx.stem.removeprefix("원고_") + "_원고판.dsd")
    if r.base != "dsd":
        from . import dsd_frame

        res = dsd_frame.build(r, out)
        return dict(res, mode="틀로 쓰기")
    p, orig, src = plan(r)
    contents = src.apply(_dedupe(p.edits))
    summary = orig.info.get("summary") or {}
    if (r.info.get("rolled") or summary.get("SUPV_OPIN")) and any(summary.values()):
        p.issues.append(issue("요약 코드", "", "", "바탕의 요약 코드(자산총계 · 감사의견 구분 등)가 그대로 남아 있다. 제출 전 편집기 「문서 헤더정보」 와 8600 에서 확인한다"))
    for (head, what), k in (_grid_problems(Source(contents)) - _grid_problems(src)).items():   # 바탕에 없던 칸 모양 어긋남(2026-11-10)
        p.issues.append(issue("편집기 구조", "", "", f"표 칸 모양이 어긋났다({what}{f' {k}곳' if k > 1 else ''}): 「{head}」 로 시작하는 표", "막음"))
    empty = len(re.findall(rb"<TBODY[^>]*>\s*</TBODY>", contents))
    if empty:                                   # 편집기 스키마(Dart4.xsd)는 TBODY 에 TR 이 하나 이상 있어야 한다(2026-11-07 한 회사 초안)
        p.issues.append(issue("편집기 구조", "", "", f"줄이 하나도 없는 표 {empty}개. DART 편집기가 「문서를 열 수 없습니다」 로 거절한다", "막음"))
    path = zip_dsd(out, contents, r.meta, _stamp(hashlib.sha256(xlsx.read_bytes()).hexdigest(), r.sha256))
    return {"path": path, "issues": p.issues, "changed": p.changed, "added": p.added, "removed": p.removed, "mode": "바탕 고치기",
            "same_bytes": contents == r.contents}


def _dedupe(edits: list) -> list:
    """같은 구간을 두 번 지우는 고침(주석을 빼며 그 안 문단도 지운 것)을 하나로, 지운 구간 안의 고침은 버린다."""
    import bisect

    dels = sorted((a, b) for a, b, new in edits if new == b"" and b > a)
    xs = [x for x, _ in dels]
    top, m = [], -1                                      # top[i] = dels[:i+1] 의 가장 큰 끝. 고침마다 전부 훑으면 큰 보고서에서 수십 초가 걸렸다(2026-11-07)
    for _, y in dels:
        m = max(m, y)
        top.append(m)
    out, seen = [], set()
    for a, b, new in sorted(edits, key=lambda x: (x[0], -(x[1] - x[0]))):
        i = bisect.bisect_left(xs, a)
        inside = i > 0 and top[i - 1] > a                # 시작이 a 앞이고 a 를 넘어가는 지운 구간(x < a < y, 그리고 a < b 면 x < a ≤ b ≤ y 도 여기에 든다)
        if not inside and a != b:                        # 넣기는 지운 구간의 가장자리면 남긴다. 같은 시작에서 더 긴 지운 구간이 있으면 버린다
            j = bisect.bisect_right(xs, a)
            inside = any(y > b for _, y in dels[i:j])
        if inside or (a, b, new) in seen:
            continue
        seen.add((a, b, new))
        out.append((a, b, new))
    return out


def stamp_of(path: Path) -> dict:
    try:
        with zipfile.ZipFile(path) as z:
            return json.loads(z.comment.decode("utf-8")) if z.comment else {}
    except (zipfile.BadZipFile, ValueError, OSError):
        return {}


def is_draft_build(path: Path) -> bool:
    return STAMP in stamp_of(path)


def norm_text(s) -> str:
    return norm(str(s or ""))
