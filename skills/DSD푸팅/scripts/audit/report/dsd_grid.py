"""회사 제시 dsd 를 재무제표 넷과 주석 번호별 격자로 읽는다(DSD 푸팅, 2026-10-12).

dsd.read_dsd 는 블록 목록을 낸다(조서 세션이 그 형태를 읽으므로 바꾸지 않는다). 여기서는 같은 판독기(_Reader)를 이어받아
표를 머리줄 · 행 이름 · 숫자 격자로 읽고, 문단과 표의 순서를 지킨 채 부분(재무제표 하나, 주석 번호 하나)으로 나눈다.
"""
from __future__ import annotations

import hashlib
import os
import pickle
import re
import sys
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET

from . import dsd
from .base import norm

CELLS = ("TD", "TH", "TE", "TU")
_NUM = re.compile(r"^[-+]?\d+(\.\d+)?$")


_CELL_UNIT = (("백만원", 1000000), ("천원", 1000), ("%", 0.01))


def cell_unit(s) -> float | None:
    """칸 글자 끝에 단위가 붙어 있으면 그 단위(원으로 몇 배인지, % 는 0.01). 「346,820천원」 은 1000, 「27.19%」 는 0.01.
    붙은 단위가 없거나 「원」 · 「주」 면 None(표의 단위를 쓴다). 「원」 · 「주」 는 예전부터 떼고 표의 단위로 읽었다. 단위 줄이 없어
    백만원을 이어받은 주식수 표와 견주는 연결이 이미 많아, 「주」 칸만 1 로 두면 그 연결이 어긋난다(10단계 스터디, 한 상장사 별도 배당받을 주식).
    주식수 · 주당 금액을 계산에 쓸 때는 calcs 의 칸에 단위를 적는다."""
    t = str(s or "").replace("　", "").replace(" ", "").strip()
    for word, u in _CELL_UNIT:
        if t.endswith(word) and to_num(t[:-len(word)]) is not None:
            return u
    return None


def to_num(s):
    """칸 글자를 숫자로. 괄호와 △ 는 음수, 「-」 는 0, 빈칸과 숫자가 아닌 글자는 None. 소수는 그대로 둔다.
    끝에 붙은 「원」 「주」 는 뗀다. 「천원」 · 「백만원」 · 「%」 가 붙은 칸은 그 글자를 떼고 읽는다. 그 칸의 단위는 cell_unit 이 알려 준다
    (예전에는 표의 단위와 다를 수 있어 숫자로 읽지 않았다. 9단계 평가에서 검증 범위에서 표시 없이 빠지는 칸으로 지적됐다, 2026-10-15)."""
    t = str(s or "").replace("　", "").replace(",", "").replace(" ", "").strip()
    for word, _ in _CELL_UNIT:
        if t.endswith(word) and len(t) > len(word):
            t = t[:-len(word)]
            break
    t = re.sub(r"[=─━_]{2,}", "", t)                 # 금액 아래 밑줄을 글자로 그린 원문(「7,146,100,000 ====」)
    t = re.sub(r"(?<=\d)\((?:US\$|[A-Z]{3})[^()]*\)$", "", t)      # 금액 뒤에 외화를 붙인 칸(「120,532(USD 84백만)」)
    if not t:
        return None
    if t in ("-", "–", "−"):
        return 0
    neg = False
    if t.startswith("(-)"):                          # 「(-)30,431」
        neg, t = True, t[3:]
    if t.startswith("(") and t.endswith(")"):
        neg, t = True, t[1:-1]
    if t[:1] in ("△", "▲", "−"):
        neg, t = True, t[1:]
    if t.endswith("원") or t.endswith("주"):          # 「1,000원」 「9,400,000주」
        t = t[:-1]
    if not _NUM.match(t):
        return None
    x = float(t)
    x = -x if neg else x
    return int(x) if x == int(x) else x


def expand(trs, fill: bool, of=None) -> list[list]:
    """TR 목록의 COLSPAN · ROWSPAN 을 풀어 네모난 격자로 만든다. fill 이면 묶인 칸마다 같은 글자를 넣고(머리줄),
    아니면 왼쪽 위 칸에만 넣는다(본문: 숫자가 두 번 세어지지 않게). of 를 주면 글자 대신 of(칸) 을 같은 자리에 넣고 빈 자리는 None 이다
    (칸의 XBRL 항목을 글자 격자와 같은 자리에 둘 때)."""
    blank, get = ("", dsd._text) if of is None else (None, of)
    grid: list[list] = []
    carry: dict[int, tuple] = {}
    for tr in trs:
        row: list = []

        def take():
            while len(row) in carry:
                n, t = carry[len(row)]
                if n == 1:
                    del carry[len(row)]
                else:
                    carry[len(row)] = (n - 1, t)
                row.append(t if fill else blank)

        for cell in (x for x in tr if x.tag in CELLS):
            take()
            t = get(cell)
            cs, rs = int(cell.get("COLSPAN") or 1), int(cell.get("ROWSPAN") or 1)
            for k in range(cs):
                if rs > 1:
                    carry[len(row)] = (rs - 1, t)
                row.append(t if (k == 0 or fill) else blank)
        take()
        grid.append(row)
    w = max((len(r) for r in grid), default=0)
    return [r + [blank] * (w - len(r)) for r in grid]


def _xbrl(cell):
    """칸의 XBRL 항목(계정 코드, 기간 · 차원 문맥, 부호를 뒤집어 보였는지). 코드나 문맥이 없으면 None."""
    code, ctx = (cell.get("ACODE") or "").strip(), (cell.get("ACONTEXT") or "").strip()
    return (code, ctx, (cell.get("ANEGATED") or "").strip().upper() == "Y") if code and ctx else None


def _finance_tags(t) -> list[list]:
    """FINANCE 표의 본문 줄마다 칸의 XBRL 항목. dsd._finance_rows 가 묶인 열(내역 · 합계)에서 마지막으로 글자가 있는 칸을 고르는 것과 같은 칸을 고른다."""
    head = t.find("THEAD/TR")
    if head is None:
        return [[_xbrl(c) for c in tr if c.tag in ("TD", "TH", "TE", "TU")] for sec in t if sec.tag in ("THEAD", "TBODY") for tr in sec.findall("TR")][1:]
    spans = [int(c.get("COLSPAN") or 1) for c in head if c.tag in ("TH", "TD", "TE")]
    out = []
    for tr in t.findall("TBODY/TR"):
        cells = [c for c in tr if c.tag in ("TD", "TH", "TE", "TU")]
        row, i = [], 0
        for sp in spans:
            grp = [c for c in cells[i:i + sp] if dsd._text(c)]
            row.append(_xbrl(grp[-1]) if grp else None)
            i += sp
        out.append(row)
    return out


def col_names(head: list[list[str]]) -> list[str]:
    """여러 줄 머리줄을 열마다 이름 하나로 잇는다. 위아래가 같은 글자면 한 번만 쓴다."""
    out = []
    for j in range(len(head[0]) if head else 0):
        parts: list[str] = []
        for r in head:
            t = r[j].strip()
            if t and (not parts or parts[-1] != t):
                parts.append(t)
        out.append(" ".join(parts))
    return out


STATEMENTS = (("재무상태표", ("재무상태표", "대차대조표")), ("손익계산서", ("포괄손익계산서", "손익계산서")),
              ("자본변동표", ("자본변동표",)), ("현금흐름표", ("현금흐름표",)),
              ("이익잉여금처분계산서", ("이익잉여금처분계산서", "결손금처리계산서")))
UNITS = {"원": 1, "천원": 1000, "백만원": 1000000}
_UNIT = re.compile(r"단위\s*[:：]\s*(백만원|천원|원)")
_NOTE_HEAD = re.compile(r"^(\d+)\s*\.\s*(?!\d)(.+)$", re.S)
_TITLE_END = re.compile(r"\s(?:가\.|\(1\)|\(가\)|1\)|①)")
FS, NOTES, OTHER = "(첨부) 재무제표", "주석", "그 외 절"


@dataclass
class Table:
    id: str
    caption: str
    unit: int
    header: list[str]
    rows: list[list[str]]
    nums: list[list]
    finance: bool = False
    levels: list | None = None        # 재무제표 본표의 과목 단계(0 이 가장 위). 모르면 None
    refs: list | None = None          # 재무제표 본표의 줄마다 과목이 가리키는 주석 번호들(「(주석 5,13)」, 주석 열)
    labels: list | None = None        # 줄 이름. 글자 열이 둘이면 두 칸을 이은 것(「기초 취득원가」). None 이면 첫 칸
    old_labels: list | None = None    # 묶인 칸을 채우기 전의 첫 칸. 앞서 적은 연결(빈 이름과 순번)을 풀 때 쓴다
    cell_units: dict | None = None    # 칸에 단위가 붙은 칸 {(줄, 열): 단위}. 「천원」 1000, 「원」 · 「주」 1, 「%」 0.01. 없는 칸은 표의 단위
    kind: str = ""                    # 「문장」 이면 주석 문단에서 꺼낸 금액을 모은 표(원문에는 없는 표)
    xbrl: dict | None = None          # 숫자 칸의 XBRL 항목 {(줄, 열): (ACODE, ACONTEXT, ANEGATED)}. DART 정기보고서 원문 xml 에만 있다(2026-10-22 연결 후보)

    def unit_at(self, i: int, j: int) -> float:
        """칸 하나의 단위. 칸에 단위가 붙어 있으면 그것, 아니면 표의 단위."""
        return (self.cell_units or {}).get((i, j), self.unit)

    def rate(self, i: int, j: int) -> bool:
        """% 가 붙은 칸. 금액이 아니라 더하는 합계 구조와 검증 범위에서 뺀다."""
        return (self.cell_units or {}).get((i, j)) == 0.01


@dataclass
class Part:
    key: str
    title: str
    items: list = field(default_factory=list)


@dataclass
class Doc:
    source: str
    sha256: str
    parts: list[Part]
    stats: dict = field(default_factory=dict)      # 원문 대조: 원문 표 수, 읽은 표 수, 문단으로 읽은 표 수, 틀 표 수

    def tables(self) -> list[Table]:
        return [x[1] for p in self.parts for x in p.items if x[0] == "t"]

    def table(self, tid: str) -> Table | None:
        return next((t for t in self.tables() if t.id == tid), None)

    def part_of(self, tid: str) -> Part:
        return next(p for p in self.parts for x in p.items if x[0] == "t" and x[1].id == tid)


def section_of(title: str) -> str | None:
    """절 제목이 재무제표 절인지 주석 절인지. dsd.part_of 는 「(첨부)재무제표」 와 「주석」 만 알아본다. 공개 원문에는
    「재무제표」 · 「연결재무제표」 · 「재무제표에 대한 주석」 · 「연결재무제표에 대한 주석」 절도 있고, 주석 뒤에
    「내부회계관리제도 검토의견」 절이 이어진다(2026-10-12 공개 원문 209건)."""
    t = norm(title).replace("(첨부)", "").replace("첨부", "").replace("연결", "").replace("별도", "")
    if t in ("주석", "재무제표주석", "재무제표에대한주석"):
        return NOTES
    if t == "재무제표":
        return FS
    if "내부회계관리제도" in t or "검토의견" in t or "감사보고서" in t or "외부감사실시내용" in t:
        return OTHER
    return None


class _GridReader(dsd._Reader):
    """dsd._Reader 의 걷기(절 · 제목 · 문단 판독)를 그대로 쓰고 표만 격자로 읽는다.
    블록 ("grid", 머리줄, 본문, 재무제표 본표 여부, 머리줄에 적힌 단위, 과목 단계, 첫 열 원문, 묶인 첫 칸, 칸의 XBRL 항목 격자 | None)."""

    def add(self, b):
        if b[0] == "h" and b[1] in (2, 3):
            sec = section_of(b[2])
            if sec:
                self.part = sec
                b = ("h", 1, sec)
        super().add(b)

    def __init__(self):
        super().__init__()
        self.stats = {"원문 표": 0, "틀 표": 0, "테두리 없는 표": 0, "문단으로 읽은 숫자 표": 0}

    def table(self, t):
        if self.part not in (FS, NOTES):
            return
        if (t.get("BORDER") or "1").strip() == "0":
            if _layout(t):                       # 틀 표: 칸 안에 문단과 표가 들어 있다. 칸 안을 차례대로 읽는다
                self.stats["틀 표"] += 1
                for cell in _cells(t):
                    if (cell.text or "").strip():
                        self.para(re.sub(r"\s+", " ", cell.text.replace(dsd.CR, " ")).strip())
                    self.walk(cell)
                return
            rows = dsd._rows(t)
            if not _bare_table(rows):
                if any(_money_row(r) for r in rows):
                    self.stats["문단으로 읽은 숫자 표"] += 1       # 금액이 든 줄이 하나뿐인 테두리 없는 표. 문단으로 읽었으니 원문과 견준다
                for r in rows:
                    line = " ".join(x for x in r if x)
                    if line:
                        self.add(("p", line))
                return
            self.stats["테두리 없는 표"] += 1    # 테두리만 없는 숫자 표는 표로 읽는다
        self.stats["원문 표"] += 1
        unit, levels, raw, tags = None, None, None, None
        tagged = any(c.get("ACONTEXT") for c in t.iter() if c.tag in CELLS)     # DART 정기보고서 원문의 XBRL 칸
        if t.get("ACLASS") == "FINANCE":
            rows = dsd._finance_rows(t)
            header, body = (rows[0], rows[1:]) if rows else ([], [])
            tags = _finance_tags(t) if tagged else None
            fin = True
            firsts = [next((c for c in tr if c.tag in CELLS), None) for tr in t.findall("TBODY/TR")]
            raw = [dsd._text(c) if c is not None else "" for c in firsts]
            lv = [int(c.get("ALEVEL")) if c is not None and (c.get("ALEVEL") or "").isdigit() else None for c in firsts]
            levels = lv if any(x is not None for x in lv) and len(lv) == len(body) else None
        else:
            head, body = expand(t.findall("THEAD/TR"), True), expand(t.findall("TBODY/TR"), False)
            tags = expand(t.findall("TBODY/TR"), False, _xbrl) if tagged else None
            keep = []
            for r in head:                       # 머리줄 안의 「(단위 : 천원)」 줄은 단위로 읽고 열 이름에서 뺀다
                texts = {x.strip() for x in r if x.strip()}
                marks = {x for x in texts if len(texts) > 1 and len(norm(x)) <= 12 and _UNIT.fullmatch(norm(x).strip("()"))}
                if len(marks) == 1:              # 「당 기」 칸과 같은 줄에 묶인 「(단위:천원)」 칸(DART 00227041 2025 담보 · 보증 표). 단위로 읽고 그 칸을 비운다
                    unit = UNITS[_UNIT.fullmatch(norm(next(iter(marks))).strip("()")).group(1)]
                    r = ["" if x.strip() in marks else x for x in r]
                    texts -= marks
                only = next(iter(texts)) if len(texts) == 1 else ""
                if "단위" in only and len(norm(only)) <= 20:      # 「(단위: 주, 원)」 처럼 단위가 둘이면 단위는 정하지 않고 줄만 뺀다
                    m = _UNIT.search(only)
                    unit = UNITS[m.group(1)] if m else unit
                else:
                    keep.append(r)
            if keep:
                header = col_names(keep)
            else:
                trs = t.findall("TBODY/TR")
                skip, k, u = _body_head(trs, body)
                unit = u or unit
                if skip or k > 1:                # 단위 줄을 빼고, 여러 줄 머리줄은 묶인 칸을 채워 열 이름으로 잇는다
                    header, body = col_names(expand(trs[skip:skip + k], True)), expand(trs[skip + k:], False)
                    tags = expand(trs[skip + k:], False, _xbrl) if tagged else None
                else:
                    header, body = (body[0], body[1:]) if body else ([], [])
                    tags = tags[1:] if tags else None
            fin = False
        merged = None
        if not fin:                              # 세로로 묶인 첫 칸(ROWSPAN)의 글자를 아래 줄에도 알려 준다
            trs = t.findall("TBODY/TR")
            full = expand(trs, True)[len(trs) - len(body):] if len(trs) >= len(body) else []
            if len(full) == len(body):
                merged = [{j: f[j] for j in range(min(3, len(r), len(f))) if not r[j].strip() and f[j].strip()} for r, f in zip(body, full)]
                merged = merged if any(0 in m for m in merged) else None      # 첫 칸이 묶인 표만. 묶인 칸은 앞의 세 열까지 본다
        w = max([len(header)] + [len(r) for r in body])
        header = list(header) + [""] * (w - len(header))
        body = [list(r) + [""] * (w - len(r)) for r in body]
        if raw is None:
            raw = [r[0] if r else "" for r in body]
        if tags is not None:
            tags = [list(r) + [None] * (w - len(r)) for r in tags][:len(body)] if len(tags) >= len(body) else None
        self.add(("grid", header, body, fin, unit, levels, raw, merged, tags))


def _cells(t):
    """표의 칸을 차례대로(THEAD · TBODY 의 TR 안)."""
    for sec in t:
        if sec.tag in ("THEAD", "TBODY"):
            for tr in sec.findall("TR"):
                yield from (c for c in tr if c.tag in CELLS)


def _layout(t) -> bool:
    """칸 안에 표가 든 테두리 없는 표. 정기보고서(XBRL) 주석은 주석 하나를 이런 틀 표 한 칸에 문단과 표로 넣는다.
    칸 글자를 한 줄로 이으면 안의 표가 문장이 되어 숫자 칸이 하나도 안 생긴다(한 상장사 2026 반기 연결의 관계기업 투자 주석, 9단계 평가)."""
    return any(x.tag in ("TABLE", "TABLE-GROUP") for c in _cells(t) for x in c.iter() if x is not c)


def _money_row(r: list[str]) -> bool:
    """첫 칸이 아닌 곳에 금액(연도 · % 가 아닌 숫자)이 있는 줄."""
    for x in r[1:]:
        v = to_num(x)
        if v is not None and not (1900 <= abs(v) <= 2100 and float(v).is_integer()) and x.strip() not in ("-", "–", "−") and cell_unit(x) != 0.01:
            return True
    return False


def _bare_table(rows: list[list[str]]) -> bool:
    """테두리만 없는 숫자 표. 두 칸 이상 찬 줄이 둘 이상이고, 금액이 있는 줄(_money_row)이 둘 이상이다.
    단위 줄 · 서명 줄 · 「제 10 기 2025년 1월 1일부터」 같은 머리 표, 「-」 로 시작하는 글 목록은 여기 걸리지 않는다."""
    full = [r for r in rows if sum(1 for x in r if x) >= 2]
    return len(full) >= 2 and sum(1 for r in full if _money_row(r)) >= 2


def _body_head(trs: list, body: list[list[str]]) -> tuple[int, int, int | None]:
    """THEAD 가 없는 표의 본문에서 (맨 앞 단위 줄 수, 머리줄 수, 단위). 첫 줄이 「(단위: 천원)」 한 칸이면 단위 줄이다.
    머리줄은 한 줄이 기본이고, 첫 머리줄에 세로로 묶인 칸(ROWSPAN)이 있으면 그 줄 수까지, 가로로 묶인 칸(COLSPAN)이 있고
    다음 줄의 첫 칸이 비고 숫자가 없으면 두 줄이다."""
    skip, unit = 0, None
    while skip < len(body) - 1:
        texts = {x.strip() for x in body[skip] if x.strip()}
        only = next(iter(texts)) if len(texts) == 1 else ""
        if not ("단위" in only and len(norm(only)) <= 20):
            break
        m = _UNIT.search(only)
        unit = UNITS[m.group(1)] if m else unit
        skip += 1
    if skip >= len(trs):
        return 0, 1, None
    cells = [c for c in trs[skip] if c.tag in CELLS]
    span = max([int(c.get("ROWSPAN") or 1) for c in cells] or [1])
    wide = any(int(c.get("COLSPAN") or 1) > 1 for c in cells)

    def label_row(r):                             # 숫자가 없는 줄(연도 같은 네 자리 수는 이름으로 본다)
        vals = [to_num(x) for x in r]
        return any(x.strip() for x in r) and not any(v is not None and not (1900 <= abs(v) <= 2100) and x.strip() not in ("-", "–", "−") for v, x in zip(vals, r))

    k = 1
    if span > 1 and skip + span < len(body) and all(label_row(body[skip + i]) for i in range(1, span)):
        k = span
    elif wide and skip + 2 < len(body) and not body[skip + 1][0].strip() and label_row(body[skip + 1]):
        k = 2
    return skip, k, unit


def _statement(b) -> str | None:
    """재무제표 제목이면 그 이름. 굵은 제목이거나 12자 이하 문단(「연결 재무상태표」)이어야 한다."""
    text = b[2] if b[0] == "h" else b[1]
    t = norm(text)
    if b[0] != "h" and len(t) > 12:
        return None
    return next((key for key, names in STATEMENTS if any(n in t for n in names)), None)


def _note_starts(blocks: list) -> dict:
    """주석 절에서 주석 제목인 블록을 고른다. {블록 번호: (주석 번호, 제목, 제목 뒤 본문)}.

    「N. 제목」 으로 시작하는 블록이 후보다. 주석 안 번호 목록(1. 2. 3.)도 같은 꼴이라, 번호가 늘어나는 차례 가운데
    점수 합이 가장 큰 것을 고른다. 점수는 굵은 제목 3, 짧은 문단 2, 긴 문단(제목과 본문이 한 문단) 1 이다.
    제목 꼴이 달라 못 읽은 번호가 있어도 끊기지 않게 번호 둘이 빠진 것까지 잇는다(못 읽은 주석은 앞 주석에 붙는다)."""
    cands: dict[int, list] = {}
    sec = None
    for i, b in enumerate(blocks):
        if b[0] == "h" and b[1] == 1:
            sec = b[2]
            continue
        if sec != NOTES or b[0] not in ("h", "p"):
            continue
        text = (b[2] if b[0] == "h" else b[1]).strip()
        m = _NOTE_HEAD.match(text)
        if not m:
            continue
        rest = m.group(2).strip()
        short = len(text) <= 40 and not text.endswith("다.")
        score = 3 if b[0] == "h" else (2 if short else 1)
        if b[0] == "h" or short:
            title, tail = rest, ""
        else:
            e = _TITLE_END.search(rest)
            k = e.start() if e and e.start() <= 30 else min(len(rest), 20)
            title, tail = rest[:k].strip(), rest[k:].strip()
        cands.setdefault(int(m.group(1)), []).append((i, score, re.sub(r"\s*[:：]\s*$", "", title), tail))
    flat = sorted((c[0], n, c[1], c[2], c[3]) for n, cs in cands.items() for c in cs)      # (블록 번호, 주석 번호, 점수, 제목, 본문)
    if not flat:
        return {}
    first = min(n for _, n, *_ in flat)
    if first > 2:
        return {}
    best: list[float] = []
    back: list[int | None] = []
    for a, (pos, n, score, _, _) in enumerate(flat):
        prev = [(best[b], b) for b in range(a) if flat[b][1] < n <= flat[b][1] + 3]      # 번호가 둘 빠진 것까지 잇는다
        if prev:
            w, b = max(prev)
            best.append(w + score)
            back.append(b)
        elif n == first:
            best.append(score)
            back.append(None)
        else:
            best.append(float("-inf"))
            back.append(None)
    a = max(range(len(flat)), key=lambda k: (best[k], -k))
    out = {}
    while a is not None and best[a] > float("-inf"):
        pos, n, _, title, tail = flat[a]
        out[pos] = (n, title, tail)
        a = back[a]
    return out


_ROMAN = re.compile(r"^\s*[,.]?\s*[IVXⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ∥][IVXⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ∥\s]*\.")
_SUB = re.compile(r"^\s*(?:\(\d+\)|\d+\.|[가-하]\.)")


def _infer_levels(raw: list[str], nums: list[list]) -> list | None:
    """과목 단계가 적히지 않은 재무제표 본표(일반 표, 옛 원문)에서 과목 앞 번호로 단계를 짐작한다.
    로마 숫자와 총계 · 금액 없는 머리 줄은 0, 「(1)」 · 「1.」 · 「가.」 는 1, 나머지는 2. 번호가 하나도 없으면 None(구조를 걸지 않는다).
    짐작한 단계로 세운 구조도 금액 근거가 있어야 채택되므로 틀린 짐작은 검증 줄을 만들지 못할 뿐이다."""
    if not any(_ROMAN.match(x) for x in raw):
        return None
    out = []
    for x, r in zip(raw, nums):
        t = norm(dsd._label(x))
        if _ROMAN.match(x) or t.endswith("총계") or not any(v is not None for v in r):
            out.append(0)
        elif _SUB.match(x):
            out.append(1)
        else:
            out.append(2)
    return out


_REF_IN_LABEL = re.compile(r"\(\s*주\s*석?\s*([\d,\s.~\-]+)\)")


def _note_refs(raw_label: str, note_cells: list[str]) -> list[int]:
    """과목이 가리키는 주석 번호들. 과목 이름 뒤 「(주석3,13)」 과 주석 열의 「5, 13」 을 읽는다."""
    text = " ".join(m.group(1) for m in _REF_IN_LABEL.finditer(raw_label)) + " " + " ".join(note_cells)
    return sorted({int(x) for x in re.findall(r"\d+", text) if 0 < int(x) < 100})


def _merge_same_columns(header: list[str], body: list[list[str]], tags: list | None = None) -> tuple[list[str], list[list[str]], list | None]:
    """머리줄 이름이 같은 이웃 열을 한 열로 합친다(줄마다 마지막으로 값이 있는 칸). 재무제표 본표를 일반 표로 만든 회사는
    기간 하나에 내역 칸과 합계 칸을 두고 머리줄을 묶는다. dsd._finance_rows 가 FINANCE 표에 하는 일과 같다.
    tags(칸의 XBRL 항목 격자)를 주면 고른 칸의 항목을 같은 자리로 옮긴다."""
    groups: list[list[int]] = []
    for j, h in enumerate(header):
        if j > 1 and h.strip() and norm(h) == norm(header[groups[-1][0]]):
            groups[-1].append(j)
        else:
            groups.append([j])
    groups = [g if all(sum(1 for j in g if r[j].strip()) <= 1 for r in body) else [[j] for j in g] for g in groups]
    groups = [x for g in groups for x in (g if g and isinstance(g[0], list) else [g])]      # 한 줄에 값이 둘 있는 묶음은 합치지 않는다
    if all(len(g) == 1 for g in groups):
        return header, body, tags
    pick = [[next((j for j in reversed(g) if r[j].strip()), None) for g in groups] for r in body]
    out = [["" if j is None else r[j] for j in pk] for r, pk in zip(body, pick)]
    if tags is not None:
        tags = [[None if j is None else tg[j] for j in pk] for tg, pk in zip(tags, pick)]
    return [header[g[0]] for g in groups], out, tags


def _split_missing(blocks: list) -> tuple[list, dict]:
    """주석 제목이 앞 문단 끝에 붙은 것을 나눠 놓친 주석 번호를 살린다. (나눈 블록들, 주석 시작).

    OpenDART 원문에는 문단 구분이 사라져 「…제공되어 있습니다5. 유형자산당사의 당기중…」 처럼 한 문단이 된 곳이 있다.
    찾은 주석 번호 사이에 빠진 번호 N 이 있으면, 그 사이 문단에서 문장 끝 바로 뒤의 「N. 제목」 을 찾아 문단을 나눈다.
    마지막으로 찾은 번호의 다음 번호도 같은 방법으로 찾는다. 스터디 보고서 34건 가운데 열 건 넘게 이 때문에 표가 앞 주석 번호로 읽혔다(2026-10-13)."""
    blocks = list(blocks)
    for _ in range(60):
        starts = _note_starts(blocks)
        found = sorted((pos, v[0]) for pos, v in starts.items())
        if not found:
            return blocks, starts
        gaps = [(p1, p2, n1 + 1) for (p1, n1), (p2, n2) in zip(found, found[1:]) if n2 > n1 + 1]
        gaps.append((found[-1][0], len(blocks), found[-1][1] + 1))
        hit = None
        for lo, hi, n in gaps:
            pat = re.compile(r"(?<=[다\.\)\]])\s*(?<!\d)" + str(n) + r"\.\s*(?=[가-힣A-Za-z])")
            for i in range(lo, hi):
                b = blocks[i]
                if b[0] == "h" and b[1] == 1 and i > lo:      # 다음 절
                    break
                if b[0] != "p" or len(b) != 2:
                    continue
                m = pat.search(b[1])
                if m and m.start() > 0:
                    hit = (i, b[1][:m.start()].rstrip(), b[1][m.start():].lstrip())
                    break
            if hit:
                break
        if not hit:
            return blocks, starts
        i, head, rest = hit
        blocks[i:i + 1] = [("p", head), ("p", rest)]
    return blocks, _note_starts(blocks)


def _row_labels(header: list[str], body: list[list[str]], nums: list[list], merged: list | None) -> tuple[list | None, list | None]:
    """줄 이름과, 묶인 칸을 채우기 전의 첫 칸. 첫 칸이 세로로 묶여 있거나 머리줄의 첫 두 칸 이름이 같으면(가로로 묶인 「구분」)
    숫자 열 앞의 글자 열(셋까지)을 이어 이름으로 삼는다(「기초 취득원가」). 세로로 묶인 글자는 아래 줄에 채운다. body 를 채워서 돌려준다.
    DART 화면에서는 묶인 칸으로 보이는 표다. 첫 칸만 이름으로 읽으면 스터디 당기 보고서 34건에서 줄 4,177개의 이름이 비었다(2026-10-13)."""
    if len(header) < 3 or not body:
        return None, None
    same_head = norm(header[0]) == norm(header[1]) and norm(header[0]) != ""
    if not (merged or same_head) or norm(header[1]).startswith("주석"):
        return None, None
    numeric = lambda j: any(isinstance(r[j], (int, float)) and r[j] != 0 for r in nums)      # noqa: E731
    k = next((j for j in range(1, len(header)) if numeric(j)), len(header))
    k = min(k, 3)
    if k < 2:                                    # 둘째 열이 숫자 열이면 이름 열은 하나다
        return None, None
    old = [r[0] for r in body]
    for r, m in zip(body, merged or []):
        for j, text in m.items():
            if j < k:
                r[j] = text
    labels = [" ".join(dict.fromkeys(x for x in (r[j].strip() for j in range(k)) if x)) for r in body]
    return labels, old


def _parts(blocks: list) -> tuple[list[Part], int]:
    parts: list[Part] = []
    blocks, starts = _split_missing(blocks)
    sec, cur, pending_unit, fs_unit, last_text = None, None, None, 1, ""
    part_unit, dropped = None, 0                             # 그 부분에서 앞 표가 쓴 단위. 단위 줄이 없는 표가 이어받는다
    for i, b in enumerate(blocks):
        if b[0] == "h" and b[1] == 1:
            sec, cur = b[2], None
            continue
        if sec not in (FS, NOTES) or (b[0] == "cap" and len(b) == 3):
            continue
        if b[0] in ("h", "p", "cap"):
            text = b[2] if b[0] == "h" else b[1]
            start = None
            if sec == FS and _statement(b):
                start = (_statement(b), _statement(b), "")
            elif i in starts:
                n, title, tail = starts[i]
                start = (f"주석{n}", title, tail)
            if start:
                same = next((p for p in parts if p.key == start[0]), None)      # 「재무상태표(계속)」 처럼 제목이 다시 나오면 이어 쓴다
                cur = same or Part(start[0], start[1])
                part_unit = None
                if same is None:
                    parts.append(cur)
                last_text = ""
                m = _UNIT.search(start[1])                # 주석 제목에 붙은 단위(「13. 이익잉여금처분계산서(단위: 천원)」, DART 00411288 2025)
                if m:
                    pending_unit = UNITS[m.group(1)]
                if start[2]:
                    cur.items.append(("p", start[2]))
                    last_text = start[2]
                    m = _UNIT.search(start[2])
                    if m:
                        pending_unit = UNITS[m.group(1)]
                continue
            m = _UNIT.search(text)
            if m:
                pending_unit = UNITS[m.group(1)]
                if sec == FS:
                    fs_unit = pending_unit
            if cur is not None and not (m and len(norm(text)) <= 14):      # 단위만 적힌 줄은 표 제목이 아니다
                last_text = text
            if cur is not None:
                cur.items.append(("p", text))
            continue
        if b[0] == "grid" and cur is not None:
            _, header, body, fin, unit, levels, raw, merged, tags = b
            k = sum(1 for x in cur.items if x[0] == "t") + 1
            tid = cur.key if (sec == FS and k == 1) else f"{cur.key}-{k}"
            if not fin:
                header, body, tags = _merge_same_columns(header, body, tags)        # 기간마다 내역 · 합계 두 칸을 둔 표(일반 표로 만든 재무제표, 결손금처리계산서 주석)
            if sec == FS and not fin:
                body = [[dsd._label(r[0])] + r[1:] for r in body]
            # 과목 옆 주석 번호 열은 숫자가 아니다. 머리줄이 두 줄이면 「지배기업소유주 주석」 처럼 위 칸 이름이 앞에 붙는다(연결 자본변동표, 10단계)
            skip = {j for j, h in enumerate(header) if sec == FS and j and (norm(h).endswith("주석") or norm(h).endswith("주석번호"))}
            nums = [[None] + [None if j in skip else to_num(c) for j, c in enumerate(r[1:], 1)] for r in body]
            cu = {(i, j): u for i, r in enumerate(body) for j, c in enumerate(r[1:], 1) if j not in skip and nums[i][j] is not None and (u := cell_unit(c)) is not None}
            unit = unit or pending_unit or part_unit or fs_unit
            part_unit = unit
            if sec == FS:
                fs_unit = unit
            refs = None
            if sec == FS:
                refs = [_note_refs(raw[i] if i < len(raw) else "", [r[j] for j in skip]) for i, r in enumerate(body)]
            if sec == FS and levels is None and cur.key != "자본변동표":
                levels = _infer_levels(raw, nums)
            plain = [[None if cu.get((i, j)) == 0.01 else v for j, v in enumerate(r)] for i, r in enumerate(nums)]      # % 칸은 줄 이름 경계를 정할 때 숫자로 치지 않는다(이율 열은 이름 쪽이다)
            labels, old = _row_labels(header, body, plain, merged) if sec == NOTES else (None, None)
            # 칸에 붙은 단위는 표의 단위와 같아도 남긴다. 단위 줄이 없어 앞 표의 단위를 이어받은 표에서도 칸의 단위가 맞고,
            # 전기 대사는 단위가 붙은 칸을 칸의 단위로 견준다(24번 작년 보고서의 「6,806,616천원」)
            xb = {(i, j): tags[i][j] for i in range(len(nums)) for j in range(1, len(nums[i])) if tags and j < len(tags[i]) and tags[i][j] and nums[i][j] is not None}
            cur.items.append(("t", Table(tid, last_text[:200], unit, header, body, nums, fin, levels if sec == FS else None, refs, labels, old, cu or None,
                                         xbrl=xb or None)))
            pending_unit, last_text = None, ""
        elif b[0] == "grid":
            dropped += 1                                 # 첫 재무제표 · 주석 제목 앞의 표. 어느 부분에도 넣지 못했다
    for p in parts:
        if p.key.startswith("주석"):
            t = sentence_table(p)
            if t is not None:
                p.items.append(("t", t))
    return parts, dropped


_SENT_AMOUNT = re.compile(r"(?<![\d,.])((?:\d[\d,]*(?:\.\d+)?\s*조\s*)?(?:\d[\d,]*(?:\.\d+)?\s*억\s*)?(?:\d[\d,]*(?:\.\d+)?\s*만\s*)?(?:\d[\d,]*(?:\.\d+)?)?)\s*(백만원|천원|원)(?![가금재화본칙천])")
_SENT_STOP = re.compile(r"[다요]\.\s*|[.;]\s+|\n")
# 외화 금액(2026-10-18 실제 회사 자료 B-7): 「JPY 184,000,000」 「USD 300,000」 처럼 통화 기호가 앞에 붙거나 「184,000,000엔」 처럼 뒤에 붙은 금액.
# 원으로 바꾸지 않고 「외화 금액」 열에 적힌 값 그대로 둔다(외화 표의 외화 금액 칸과 견준다)
_FX_CODES = "USD|EUR|JPY|CNY|RMB|GBP|HKD|SGD|VND|AUD|CAD|CHF|TWD|THB|IDR|INR|PHP|MYR|NZD"
_FX_NUM = r"((?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)"
_FX_PRE = re.compile(r"(?<![A-Za-z])(" + _FX_CODES + r"|US\$|\$|€|¥|£)\s?" + _FX_NUM + r"(?![\d,]*\d)(?!\s*(?:원|천원|백만원))")
_FX_POST = re.compile(r"(?<![\d,.])" + _FX_NUM + r"\s?(" + _FX_CODES + r"|달러|엔|위안|유로|파운드)(?![A-Za-z])")
FX_MIN = 10                                    # 「USD 1 = 1,470원」 같은 환율 기준 금액은 모으지 않는다


def _fx_amounts(text: str) -> list[tuple[int, int, str, float]]:
    """문장 속 외화 금액 (시작, 끝, 원문, 값). 앞에 붙은 통화 기호를 먼저 보고, 겹치는 뒤 붙임은 뺀다."""
    out = []
    for m in _FX_PRE.finditer(text):
        out.append((m.start(), m.end(), m.group(0).strip(), float(m.group(2).replace(",", ""))))
    for m in _FX_POST.finditer(text):
        if not any(a <= m.start() < b or a < m.end() <= b for a, b, *_ in out):
            out.append((m.start(), m.end(), m.group(0).strip(), float(m.group(1).replace(",", ""))))
    return sorted(x for x in out if x[3] >= FX_MIN)


def _fx_text(v: float) -> str:
    return f"{v:,.0f}" if float(v).is_integer() else f"{v:,.2f}"


def _won(text: str, unit_word: str) -> tuple[float, float] | None:
    """「1조 2,345억」 「80억」 「3,640,000,000」 과 단위 글자를 (원, 적힌 자릿수의 단위)로. 「80억원」 은 (8,000,000,000, 1억),
    「346,820천원」 은 (346,820,000, 1000). 자릿수 단위는 견줄 때 반올림 폭이 된다(천원으로 적은 금액을 원 단위 칸과 원까지 견주지 않게)."""
    t = text.replace(",", "").replace(" ", "")
    if not re.search(r"\d", t):
        return None
    total, rest, last = 0.0, t, None
    for word, k in (("조", 10 ** 12), ("억", 10 ** 8), ("만", 10 ** 4)):
        if word in rest:
            head, rest = rest.split(word, 1)
            if not head:
                return None
            total += float(head) * k
            last = k
    if rest:
        total += float(rest)
        last = 1
    return total * UNITS[unit_word], (last or 1) * UNITS[unit_word]


def sentence_table(p: Part) -> Table | None:
    """주석 문단에 적힌 금액(「3,640,000,000원의 보증」 「과징금 80억원」 「346,820천원」)을 모은 표. 원문에는 없는 표다.
    줄 이름은 금액 바로 앞의 글(문장 시작이나 쉼표 뒤부터), 금액 열은 원 단위로 바꾼 값이다. AI 가 이 칸을 표의 칸처럼 연결에 쓸 수 있고,
    연결되지 않은 칸은 엑셀에서 회색이라 눈으로 볼 곳으로 남는다. 단위 글자(원 · 천원 · 백만원)가 붙은 금액만 모은다
    (단위 없는 숫자는 수량인지 금액인지 알 수 없다)."""
    rows, nums, cu = [], [], {}
    for x in p.items:
        if x[0] != "p":
            continue
        text = x[1]
        for m in _SENT_AMOUNT.finditer(text):
            got = _won(m.group(1), m.group(2))
            if got is None or got[0] == 0:
                continue
            v, u = got
            before = text[:m.start()]
            cut = max([k.end() for k in _SENT_STOP.finditer(before)] + [0])
            label = re.sub(r"\s+", " ", _SENT_AMOUNT.sub("…", before[cut:])).strip()      # 앞선 금액은 「…」 로 줄인다(「매출액은 …(전기:」)
            if len(label) > 40:
                label = label[-40:]
                label = label[label.find(" ") + 1:] if " " in label[:15] else label
            label = label or "문장 금액"
            q = v / u
            rows.append([label, m.group(0).strip(), f"{v:,.0f}", ""])
            nums.append([None, None, int(q) if float(q).is_integer() else round(q, 6), None])
            cu[(len(nums) - 1, 2)] = u
        for a, _, raw, v in _fx_amounts(text):                     # 외화 금액은 「외화 금액」 열에 적힌 값 그대로
            before = text[:a]
            cut = max([k.end() for k in _SENT_STOP.finditer(before)] + [0])
            label = re.sub(r"\s+", " ", _SENT_AMOUNT.sub("…", before[cut:])).strip()
            if len(label) > 40:
                label = label[-40:]
                label = label[label.find(" ") + 1:] if " " in label[:15] else label
            rows.append([label or "문장 외화 금액", raw, "", _fx_text(v)])
            nums.append([None, None, None, int(v) if float(v).is_integer() else v])
            cu[(len(nums) - 1, 3)] = 1
    for x in p.items:                # 표 안 글자 칸에 적힌 금액(「한도 3,000,000천원」). 칸이 숫자가 아니라 표의 칸으로는 읽히지 않는다(10단계 재평가)
        if x[0] != "t" or x[1].kind:
            continue
        t = x[1]
        for r, row in enumerate(t.rows):
            for c in range(1, len(row)):
                if t.nums[r][c] is not None or not row[c]:
                    continue
                for m in _SENT_AMOUNT.finditer(str(row[c])):
                    got = _won(m.group(1), m.group(2))
                    if got is None or got[0] == 0:
                        continue
                    v, u = got
                    q = v / u
                    head = t.header[c] if c < len(t.header) else ""
                    rows.append([f"{t.id} {row[0]} · {head}".strip(" ·"), m.group(0).strip(), f"{v:,.0f}", ""])
                    nums.append([None, None, int(q) if float(q).is_integer() else round(q, 6), None])
                    cu[(len(nums) - 1, 2)] = u
                for _, _, raw, v in _fx_amounts(str(row[c])):
                    head = t.header[c] if c < len(t.header) else ""
                    rows.append([f"{t.id} {row[0]} · {head}".strip(" ·"), raw, "", _fx_text(v)])
                    nums.append([None, None, None, int(v) if float(v).is_integer() else v])
                    cu[(len(nums) - 1, 3)] = 1
    if not rows:
        return None
    return Table(f"{p.key}-문장", "문장 속 금액(적힌 단위. 외화는 외화 금액 열에 적힌 값 그대로)", 1, ["문장", "원문", "금액", "외화 금액"], rows, nums,
                 cell_units=cu, kind="문장")


def read_grid(path: Path) -> Doc:
    """dsd(zip) 또는 OpenDART 원문 xml 을 읽는다."""
    path = Path(path)
    raw = path.read_bytes()
    if path.suffix.lower() == ".xml":
        root = ET.fromstring(dsd.lenient_xml(raw))
    else:
        with zipfile.ZipFile(path) as z:
            name = next((n for n in z.namelist() if n.lower().endswith("contents.xml")), None)
            if name is None:
                raise ValueError(f"dsd 안에 contents.xml 이 없습니다: {path}")
            root = ET.fromstring(z.read(name))
    r = _GridReader()
    body = root.find("BODY")
    if body is not None:
        r.walk(body)
    parts, dropped = _parts(r.out)
    read = sum(1 for p in parts for x in p.items if x[0] == "t" and not x[1].kind)
    return Doc(path.name, hashlib.sha256(raw).hexdigest(), parts, dict(r.stats, **{"읽은 표": read, "어느 부분에도 넣지 못한 표": dropped}))


CACHE_DAYS = 30                                # 이보다 오래 안 쓴 판독 캐시는 지운다


def cache_dir() -> Path:
    """판독 캐시 폴더. 이 PC 의 사용자 폴더(LOCALAPPDATA 아래 audit-dsd/판독)에 둔다. 결과 폴더에 두면 남이 준 결과 폴더의 pickle 을 읽게 된다
    (pickle 은 읽을 때 코드가 돌 수 있다). 고객 자료의 판독 결과라 공유 폴더에 두지 않는다."""
    return Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".cache") / "audit-dsd" / "판독"


def _code_sig() -> str:
    """판독 코드(이 파일 · dsd.py · base.py)와 파이썬 판의 지문. 코드가 바뀌면 캐시를 쓰지 않는다."""
    global _SIG
    if _SIG is None:
        h = hashlib.sha256(sys.version.encode())
        for f in (Path(__file__), Path(dsd.__file__), Path(__file__).with_name("base.py")):
            h.update(f.read_bytes())
        _SIG = h.hexdigest()[:12]
    return _SIG


_SIG: str | None = None


def read_cached(path: Path, cache: Path | None) -> Doc:
    """read_grid 와 같다. cache 폴더에 「파일 sha256 · 코드 지문」 별로 판독 결과를 두고 다시 쓴다(2026-10-22 실행 시간 P5).
    foot 를 여러 번 돌려도 작년 보고서 · 짝 보고서를 다시 판독하지 않는다. 돌려주는 문서는 매번 새로 풀어낸 사본이라 고쳐도 캐시에 남지 않는다."""
    path = Path(path)
    if cache is None:
        return read_grid(path)
    sha, sig = hashlib.sha256(path.read_bytes()).hexdigest(), _code_sig()
    p = Path(cache) / f"{sha}-{sig}.pkl"
    if p.exists():
        try:
            doc = pickle.loads(p.read_bytes())
            doc.source = path.name
            os.utime(p)                               # 쓴 날을 남겨 오래 안 쓴 것만 지운다
            return doc
        except Exception:                             # 깨진 캐시는 버리고 다시 읽는다
            pass
    doc = read_grid(path)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        now = time.time()
        for old in p.parent.glob("*.pkl"):            # 코드가 바뀌어 못 쓰게 된 캐시와 오래 안 쓴 캐시
            if not old.stem.endswith(sig) or now - old.stat().st_mtime > CACHE_DAYS * 86400:
                old.unlink(missing_ok=True)
        p.write_bytes(pickle.dumps(doc, protocol=pickle.HIGHEST_PROTOCOL))
    except OSError:
        pass
    return doc


def to_json(doc: Doc) -> dict:
    def item(x):
        if x[0] == "p":
            return {"p": x[1]}
        t = x[1]
        return {"table": {"id": t.id, "caption": t.caption, "unit": t.unit, "header": t.header, "rows": t.rows,
                          "nums": t.nums, "finance": t.finance, "levels": t.levels, "refs": t.refs}}

    return {"source": doc.source, "sha256": doc.sha256,
            "parts": [{"key": p.key, "title": p.title, "items": [item(x) for x in p.items]} for p in doc.parts]}
