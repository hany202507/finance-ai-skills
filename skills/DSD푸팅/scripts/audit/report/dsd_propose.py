"""DSD 푸팅: 엔진이 내는 연결 후보(2026-10-22, 실행 시간 점검 P1).

AI 가 연결을 처음부터 다 적으면 쓰는 양이 연결 수에 비례한다(한 상장사 2026 반기 별도 344건, 약 4만 4천 토큰).
엔진이 금액을 보지 않고 위치 · 이름 · XBRL 코드로 후보를 낸다. AI 는 후보마다 O · X · 식 고침을 적고 후보에 없는 연결만 새로 적는다.
금액이 같다는 것은 근거로 쓰지 않는다(3단계 반려, 설계 6.3절). 후보는 AI 가 O 를 적어야 연결이 되고 confirmed 는 false 다.

후보의 근거(how):
  XBRL       DART 정기보고서 원문의 숫자 칸에 붙은 계정 코드(ACODE)와 기간 · 차원(ACONTEXT)이 같은 칸. 「공시금액」 차원과
             연결 · 별도 차원은 떼고 본다. 기초 잔액 코드(…AtBeginningOfPeriod)는 그 기간의 시작 시점(전기말)으로 읽는다.
             차원 구성원 이름이 다른 칸의 계정 코드와 같으면(자본 항목 「이익잉여금」 구성원 ↔ 이익잉여금 계정) 같은 항목으로 본다.
  주석 열     재무제표 과목이 가리킨 주석(주석 열, 과목 옆 번호) 표에서 과목 이름이 같은 줄, 또는 그 과목을 제목으로 단 표의 합계 줄.
  이름        과목 이름과 같은 줄 이름(주석 열이 없는 보고서는 주석 제목 · 표 제목으로 그 과목의 표인지 정한다).
  변동표      변동표의 기초 · 기말 = 재무상태표 전기 · 당기. 연차 보고서는 당기 표 기초 = 전기 표 기말.
  자본변동표  자본변동표의 열(자본 항목)과 기초 · 기말 줄 = 재무상태표 과목, 순이익 줄 = 손익계산서.
  회사별 표   같은 주석의 범주 합계 표 칸 = 회사별 표 같은 줄에서 열 이름이 그 범주 열 이름으로 시작하는 칸들의 합(10-22 2차).
  이름 짝     이름이 다른 흔한 짝(조건부): 변동표 취득 = 현금흐름표 취득, 변동표 감가상각비 · 상각 = 성격별 비용, 성격별 퇴직급여 = 확정급여 비용.
  문장        문장 금액 표의 「표 안 글자 칸」 줄 = 같은 표의 금액 칸(글에서 금액 바로 앞에 적힌 줄 · 열 이름, 없으면 그 열의 하나뿐인 금액 칸).

기간은 칸마다 정한다. XBRL 문맥이 있으면 문맥에서, 없으면 열 이름 · 줄 이름 · 표 위 문단(「당반기말」 「<전기>」) · 표 제목의
「당기 · 전기 · 기초 · 기말」 로 정한다. 기간을 못 정한 칸에는 후보를 내지 않는다. 후보는 문서만으로 정해지므로 같은 파일이면 번호가 같다.
"""
from __future__ import annotations

import re
from collections import Counter

from .base import norm
from .dsd_grid import Doc, Table
from .dsd_links import _isnum, _labels, _ref, col_prefix, cut_prefix, is_rate, period_col, period_labels, span_of, term_of, total_kind

FS = ("재무상태표", "손익계산서", "현금흐름표")
SKIP_NOTES = ("특수관계", "외화", "담보", "우발", "약정", "위험", "민감도", "만기", "보증", "부문")      # 과목의 일부만 담는 주석. 부문 주석은 열마다 부문이라 합계 열만 쓴다
_SKIP_HEAD = re.compile(r"이내|미만|초과|이하|이후|이상|~")     # 만기 구간 열
_AMOUNT_WORDS = ("금액", "장부금액", "순장부금액", "공시금액", "장부가액", "잔액", "순액", "합계", "계", "총계")
_PAD_WORDS = {"금융자산", "금융부채", "합계", "총계", "소계", "계", "기초", "기말", "반기말", "분기말", "당기말", "전기말", "당반기말", "당분기말",
              "장부금액", "순장부금액", "공시금액", "금액", "잔액"}
_POINT_S = re.compile(r"기초|기시|당기초|01\.01|1월1일|\(당기초\)")
_POINT_E = re.compile(r"기말|반기말|분기말|당기말|전기말|보고기간\s*종료일|보고기간말|06\.30|12\.31|09\.30|03\.31")
_REL = re.compile(r"(당|전)\s*(반기|분기|기)(말)?")
_TITLE_TAIL = re.compile(r"(?:의)?(?:세부내역|내역|변동내역|변동내용|변동|구성내역|구성|명세|현황|장부금액|증감|내용|세부정보|공시)+$")
_NUM_HEAD = re.compile(r"^\s*(?:\d+\.|\(\d+\)|[가-하]\.|[①-⑳]|\d+\))\s*")
ENTITY_AXIS = "ConsolidatedAndSeparateFinancialStatementsAxis"
DEFAULT_DIMS = {("CarryingAmountAccumulatedDepreciationAmortisationAndImpairmentAndGrossCarryingAmountAxis", "ReportedAmountMember")}
EPS_DIM = ("ClassesOfShareCapitalAxis", "OrdinarySharesMember")      # 손익계산서의 주당이익은 보통주 주당이익이다(K-IFRS 1033 문단 66)
MEMBER_AXES = ("ComponentsOfEquityAxis", "ClassesOfFinancialAssetsAxis", "ClassesOfFinancialLiabilitiesAxis")
_CTX = re.compile(r"^(BP|P|C)FY(\d{4})([de])([A-Za-z0-9]*)$")


def _plain(s) -> str:
    """이름 견주기용: 각주 · 괄호 안 덧말 · 띄어쓰기 · 문장부호를 뗀다."""
    s = re.sub(r"\((?:\*|주)\s*\d*\)|\*\d*", "", str(s or ""))
    s = re.sub(r"\([^)]*\)|\[[^\]]*\]", "", s)
    return re.sub(r"[\s,·ㆍ\-()「」\[\]:/]", "", s)


def _fs_name(label: str) -> str:
    return _plain(_NUM_HEAD.sub("", str(label or "")))


def _variants(name: str) -> set[str]:
    out = {name}
    if name.endswith("액") and len(name) >= 3:
        out.add(name[:-1])                                # 「매출액」 ↔ 「매출」
    return {x for x in out if len(x) >= 2}


def _subject(text: str) -> str:
    """주석 제목 · 표 제목에서 과목 이름 부분(「유형자산 장부금액 변동」 → 유형자산)."""
    t = _plain(_NUM_HEAD.sub("", str(text or "")))
    prev = None
    while prev != t:
        prev, t = t, _TITLE_TAIL.sub("", t)
    return t


# ---- 기간 ----------------------------------------------------------------------------------------------
# 칸의 기간 이름: C.e 당기말, P.e 전기말(= 당기초), PP.e 전전기말(= 전기초), Ph.e 전반기 · 전분기말, C.d · P.d 누적 기간, C.q · P.q 3개월

def _ctx_period(code: str, ctx: str) -> str | None:
    m = _CTX.match(ctx.split("_", 1)[0])
    if not m:
        return None
    rel, kind, suf = {"C": "C", "P": "P", "BP": "PP"}[m.group(1)], m.group(3), m.group(4)
    if kind == "e":
        key = "C.e" if rel == "C" else "PP.e" if rel == "PP" else ("Ph.e" if suf.endswith("A") else "P.e")
    elif suf.endswith("Q"):
        key = rel + ".q"
    elif rel == "P" and not (suf.endswith("A") or suf == "FY"):
        key = "P.y"                                       # 반기보고서 안의 전기 1년(PFY2025dHY)
    else:
        key = rel + ".d"
    if "AtBeginningOfPeriod" in code:                     # 기초 잔액: 누적 기간의 시작 시점
        return {"C": "P.e", "P": "PP.e"}.get(rel) if not key.endswith(".q") else None
    if "AtEndOfPeriod" in code and kind == "d":
        return {"C.d": "C.e", "P.d": "P.e" if suf == "FY" else "Ph.e"}.get(key)
    return key


def _fact(code: str, ctx: str) -> tuple | None:
    """XBRL 항목: (계정 코드, 기간, 차원). 연결 · 별도 차원과 「공시금액」 차원은 뗀다."""
    period = _ctx_period(code, ctx)
    if period is None:
        return None
    local = code.split("_", 1)[1] if "_" in code else code
    local = re.sub(r"At(?:Beginning|End)OfPeriod(?:Cf)?$", "", local)
    toks = ctx.split("_")[1:]
    dims, k = [], 0
    while k + 3 < len(toks):                              # 차원은 (이름공간, 축, 이름공간, 구성원) 네 토막씩이다
        axis, member = toks[k + 1], toks[k + 3]
        k += 4
        if axis == ENTITY_AXIS or (axis, member) in DEFAULT_DIMS:
            continue
        dims.append((axis, member))
    if local.endswith("EarningsLossPerShare") and dims == [EPS_DIM]:
        dims = []
    return local, period, tuple(sorted(dims))


MEMBER_CODES = ("Equity", "FinancialAssets", "FinancialLiabilities")     # 구성원 이름이 곧 계정인 합계 코드. 「감가상각비 · 매출원가 구성원」 은 매출원가가 아니다


def _member_fact(f: tuple) -> tuple | None:
    """차원 하나짜리 칸을 그 구성원 이름의 계정으로 본 항목(「Equity · 자본 항목 = IssuedCapital」 → IssuedCapital)."""
    if len(f[2]) != 1 or f[0] not in MEMBER_CODES or f[2][0][0] not in MEMBER_AXES:      # 범주 축(CategoriesOf…)의 「기타금융부채」 는 종류 축의 「기타」 와 다르다
        return None
    member = f[2][0][1]
    if not member.endswith("Member") or "MemberOf" in member:
        return None
    return member[:-6], f[1], ()


def _fs_periods(t: Table) -> dict:
    """재무제표 본표의 숫자 열마다 기간 이름."""
    out = {}
    tags = t.xbrl or {}
    terms = {j: term_of(h) for j, h in enumerate(t.header) if j and term_of(h) is not None}
    top = max(terms.values()) if terms else None
    a, b = period_col(t, "당기"), period_col(t, "전기")
    flow = not t.id.startswith("재무상태표")
    for j in range(1, len(t.header)):
        got = Counter(_ctx_period(*tags[(i, j)][:2]) for i in range(len(t.rows)) if (i, j) in tags)
        got.pop(None, None)
        if got:
            out[j] = got.most_common(1)[0][0]
            continue
        if j in terms:
            rel = "C" if terms[j] == top else "P"
        elif j == a:
            rel = "C"
        elif j == b:
            rel = "P"
        else:
            continue
        out[j] = rel + ((".q" if "3개월" in t.header[j] else ".d") if flow else ".e")
    return out


def _rel_word(text: str) -> tuple[str | None, str | None]:
    """(C · P, 말 · 반기) 「당반기말」 → (C, 말), 「전반기」 → (P, 반기)."""
    m = _REL.search(norm(text))
    if not m:
        return None, None
    return ("C" if m.group(1) == "당" else "P"), ("말" if m.group(3) else m.group(2))


def _point(text: str) -> str | None:
    t = norm(text)
    if _POINT_S.search(t) and not re.search(r"기초자산", t):
        return "s"
    if _POINT_E.search(t):
        return "e"
    return None


def note_period(doc: Doc, t: Table, i: int, j: int, flow: bool, interim: bool, table_rel: tuple) -> str | None:
    """주석 칸 (i, j) 의 기간 이름. flow 면 손익 · 현금흐름 과목과 견줄 칸(기간), 아니면 잔액(시점)."""
    tag = (t.xbrl or {}).get((i, j))
    if tag:
        return _ctx_period(*tag[:2])
    head, lab = str(t.header[j] or ""), _labels(t)[i]
    rel, word = _rel_word(head)
    if rel is None:
        rel, word = _rel_word(lab)
    if rel is None:
        rel, word = table_rel
    point = _point(head) or _point(lab)
    if flow:
        if point:
            return None
        rel = rel or "C"
        q = "3개월" in head or "3개월" in (t.caption or "")
        return rel + (".q" if q else ".d")
    if point == "s":
        return {"C": "P.e", "P": "PP.e", None: "P.e"}[rel]
    if rel is None:
        return "C.e" if point == "e" else None
    if rel == "C":
        return "C.e"
    if interim and word in ("반기", "분기"):              # 전반기 표의 기말은 작년 같은 반기 말이다(재무상태표 전기는 전기말)
        return "Ph.e"
    return "P.e"


# ---- 후보 ----------------------------------------------------------------------------------------------

def _value_cols(t: Table, cols: list[int]) -> list[int]:
    """금액 열: 열 이름이 기간 · 금액 · 합계뿐이거나 비어 있는 열. 범주 · 종류별 열과 합계 열이 함께 있으면 합계 열만."""
    keep = []
    for j in cols:
        h = _plain(_REL.sub("", norm(t.header[j])))
        h = re.sub(r"^제\d+기|\d{4}|반기|분기|누적|3개월|당기|전기", "", h)
        if not h or any(h.endswith(w) for w in _AMOUNT_WORDS) or total_kind(t.header[j]) == "합계":
            keep.append(j)
    if len(cols) == 1:                                   # 숫자 열이 하나뿐인 표는 그 열이 금액 열이다
        return list(cols)
    totals = [j for j in keep if total_kind(t.header[j]) == "합계"]
    items = [j for j in cols if j not in keep]
    if items and totals:
        return totals
    return keep if not items or totals else []


def _row_name(label: str) -> str:
    """줄 이름에서 과목 이름 부분: 앞뒤의 합계 · 기간 · 「금융자산」 같은 구역 낱말을 뗀다(「금융자산 합계 현금및현금성자산」 → 현금및현금성자산)."""
    if _plain(label) in ("합계", "총계", "소계", "계"):      # 「합 계」 「소 계」(「자본총계」 는 과목 이름이다)
        return ""
    words = str(label or "").split()
    while words and _plain(words[0]) in _PAD_WORDS:
        words = words[1:]
    while words and _plain(words[-1]) in _PAD_WORDS:
        words = words[:-1]
    t = _plain(" ".join(words))
    t = re.sub(r"^(?:기초|기말|반기말|분기말|당기말|전기말)(?=.)", "", t)      # 「기초장부금액」 「반기말장부금액」
    return re.sub(r"(?<=.)(?:순장부금액|장부금액|금액|잔액)$", "", t) if t not in _PAD_WORDS else ""


def _common_head(names: list[str]) -> str:
    if len(names) < 2:
        return ""
    words = [n.split() for n in names]
    out = []
    for k in range(min(len(w) for w in words)):
        if len({w[k] for w in words}) == 1:
            out.append(words[0][k])
        else:
            break
    return " ".join(out)


class _Fs:
    """재무제표 본표의 과목: 이름 → [(표, 줄)]."""

    def __init__(self, doc: Doc):
        self.tables = [t for t in doc.tables() if any(t.id == n or t.id.startswith(n + "-") for n in FS)]
        self.periods = {t.id: _fs_periods(t) for t in self.tables}
        self.by_name: dict[str, list] = {}
        self.by_subject: dict[str, list] = {}
        for t in self.tables:
            for i, lab in enumerate(_labels(t)):
                name = _fs_name(lab)
                if len(name) < 2 or not any(_isnum(v) for v in t.nums[i][1:]):
                    continue
                for v in _variants(name):
                    self.by_name.setdefault(v, []).append((t, i))
                short = re.sub(r"^(?:단기|장기)", "", name)      # 주석 제목 「차입금」 ↔ 과목 「장기차입금」(제목으로 찾을 때만)
                if short != name and len(short) >= 2:
                    self.by_subject.setdefault(short, []).append((t, i))

    def cell(self, t: Table, i: int, period: str):
        j = next((j for j, p in self.periods[t.id].items() if p == period and _isnum(t.nums[i][j])), None)
        return None if j is None else (t, i, j)

    def lines(self, name: str, flow: bool | None = None, subject: bool = False) -> list:
        got = self.by_name.get(name, []) + (self.by_subject.get(name, []) if subject and name not in self.by_name else [])
        if flow is not None:
            got = [(t, i) for t, i in got if (not t.id.startswith("재무상태표")) == flow]
        return got


def _ref_of(t: Table, i: int, j: int, fs_periods: dict | None = None) -> dict:
    row, nth = _ref(_labels(t), i)
    out = {"table": t.id, "row": row}
    if nth != 1:
        out["row_nth"] = nth
    if fs_periods is not None and j in (period_col(t, "당기"), period_col(t, "전기")) and not t.id.startswith("자본변동표"):
        out["col"] = "당기" if j == period_col(t, "당기") else "전기"
        return out
    col, cn = _ref(t.header, j)
    out["col"] = col
    if cn != 1:
        out["col_nth"] = cn
    return out


def _text(t: Table, i: int, j: int) -> str:
    return f"{t.id} 「{_labels(t)[i]}」 · 「{t.header[j] or str(j + 1) + '번째 열'}」"


def proposals(doc: Doc) -> list[dict]:
    """연결 후보 목록. [{id, how, left, right, grade, basis, (when)}]. 금액은 보지 않는다."""
    from . import dsd_links

    fs = _Fs(doc)
    interim = dsd_links.doc_span(doc) in ("반기", "분기")
    ruled = set()                                       # 엔진 규칙(대차, 자본변동표 기말 총계 …)이 이미 거는 칸 짝
    for c in dsd_links.build(doc, {})[0]:
        if c.group != "합계":
            for x in c.terms:
                ruled.add(frozenset([(c.table, c.r, c.c), (x[0], x[1], x[2])]))
    out: list[dict] = []
    seen: set = set()

    def add(how, left, right, basis, grade="항등식", when=None, sign=1):
        lt, li, lj = left
        rt, ri, rj = right
        if lt.id == rt.id or not _isnum(lt.nums[li][lj]) or not _isnum(rt.nums[ri][rj]):
            return
        key = frozenset([(lt.id, li, lj), (rt.id, ri, rj)])
        if key in seen or key in ruled:
            return
        seen.add(key)
        r = _ref_of(rt, ri, rj, fs.periods.get(rt.id))
        if sign < 0:
            r["sign"] = -1
        x = {"how": how, "left": _ref_of(lt, li, lj, fs.periods.get(lt.id)), "right": [r], "grade": grade, "basis": basis}
        if when:
            x["when"] = when
        out.append(x)

    def add_sum(how, left, rights, basis, grade="항등식", when=None, sum_of=None):
        """왼쪽 칸 = 오른쪽 칸들의 합. sum_of 는 읽기 자료의 한 줄 글(표 · 줄 · 열 이름 앞부분 · 칸 수)."""
        lt, li, lj = left
        key = ("합", (lt.id, li, lj), frozenset((t.id, i, j) for t, i, j in rights))
        if key in seen:
            return
        seen.add(key)
        x = {"how": how, "left": _ref_of(lt, li, lj, fs.periods.get(lt.id)), "right": [_ref_of(t, i, j, fs.periods.get(t.id)) for t, i, j in rights],
             "grade": grade, "basis": basis}
        if when:
            x["when"] = when
        if sum_of:
            x["sum_of"] = sum_of
        out.append(x)

    _xbrl_props(doc, fs, add)
    _name_props(doc, fs, interim, add)
    _sce_props(doc, fs, interim, add)
    if not interim:
        _roll_props(doc, add)
    _group_props(doc, add_sum)
    _pair_props(doc, fs, interim, add)
    _sentence_props(doc, add)
    order = {t.id: k for k, t in enumerate(doc.tables())}
    out.sort(key=lambda x: (order.get(x["left"]["table"], 0), x["left"]["row"], x["left"]["col"]))
    for k, x in enumerate(out, 1):
        x["id"] = f"P{k:04d}"
    return [{"id": x.pop("id"), **x} for x in out]


def _rank(t: Table) -> int:
    for k, n in enumerate(("재무상태표", "손익계산서", "현금흐름표", "자본변동표")):
        if t.id == n or t.id.startswith(n + "-"):
            return k
    return 9


def _xbrl_props(doc: Doc, fs: _Fs, add) -> None:
    """XBRL 항목이 같은 칸."""
    groups: dict[tuple, list] = {}
    for t in doc.tables():
        for (i, j), (code, ctx, neg) in (t.xbrl or {}).items():
            f = _fact(code, ctx)
            if f is None:
                continue
            groups.setdefault(f, []).append((t, i, j, False, neg))
            alt = _member_fact(f)
            if alt is not None:
                groups.setdefault(alt, []).append((t, i, j, True, neg))
    order = {t.id: k for k, t in enumerate(doc.tables())}
    for f, cells in groups.items():
        if len({c[0].id for c in cells}) < 2 or not any(not c[3] for c in cells):
            continue
        cells.sort(key=lambda c: (c[3], _rank(c[0]), order[c[0].id], c[1], c[2]))      # 구성원 이름으로 들어온 칸은 계정 칸(앞)에만 잇는다
        anchor = cells[0]
        for c in cells[1:]:
            if c[0].id == anchor[0].id or (c[3] and anchor[3]):
                continue
            via = "차원 구성원 이름이 계정 코드와 같다" if (c[3] or anchor[3]) else "계정 코드 · 기간 · 차원이 같다"
            flip = c[4] != anchor[4]                       # 한쪽만 부호를 뒤집어 보인 칸(변동표의 감가상각비는 음수, 배분 표는 양수)
            add("XBRL", c[:3], anchor[:3], f"XBRL {f[0]} ({via}{', 한쪽은 부호를 뒤집어 보임' if flip else ''})", sign=-1 if flip else 1)


def _skip_note(doc: Doc, t: Table) -> bool:
    title = doc.part_of(t.id).title
    return any(w in _plain(title) for w in SKIP_NOTES) or any(_SKIP_HEAD.search(str(h)) for h in t.header[1:])


def _label_cols(t: Table) -> int:
    """줄 이름으로 이은 글자 열의 수(dsd_ai._label_cols 와 같다)."""
    numeric = lambda j: any(_isnum(r[j]) and r[j] != 0 and not t.rate(i, j) for i, r in enumerate(t.nums))      # noqa: E731
    return min(next((j for j in range(1, len(t.header)) if numeric(j)), len(t.header)), 3)


def _item(t: Table, i: int) -> str:
    """줄의 과목 이름. 줄 이름을 여러 칸으로 이은 표는 마지막 칸이다(「성격별 비용 | 감가상각비」 → 감가상각비, 「기초 | 유형자산」 → 유형자산)."""
    if t.labels:
        cells = [str(c).strip() for c in t.rows[i][:_label_cols(t)] if str(c).strip()]
        if cells:
            return _row_name(cells[-1])
    return _row_name(_labels(t)[i])


_GAIN = re.compile(r"수익|이익|차익|환입")
_LOSS = re.compile(r"손실|차손|비용|상각비|원가")
CF_ADJ_WHEN = "현금흐름 조정 금액이 그 손익 과목 금액 전부다"


def _cf_adjust(doc: Doc, key: str, cf_refs: set) -> bool:
    """간접법 현금흐름의 조정 내역 주석(현금흐름표 과목이 가리킨 주석, 제목이 현금흐름표)."""
    return key in cf_refs or "현금흐름" in _plain(next((p.title for p in doc.parts if p.key == key), ""))


def _adjust_sign(name: str) -> int:
    """조정 내역에서 수익 · 이익은 빼고 비용 · 손실은 더한다. 이름이 수익 · 이익이면 손익 과목과 부호가 반대다."""
    return -1 if _GAIN.search(name) and not _LOSS.search(name) else 1


def _table_kind(t: Table, rel_word: str | None) -> bool:
    """잔액 표인가(기간 이름에 「말」, 열 · 줄에 기초 · 기말). 아니면 손익 · 현금흐름처럼 기간 금액의 표다."""
    return rel_word == "말" or any(_point(h) for h in t.header[1:]) or any(_point(x) for x in _labels(t))


def _name_props(doc: Doc, fs: _Fs, interim: bool, add) -> None:
    """주석 표 칸 = 재무제표 과목, 주석 칸 = 다른 주석 칸.
    1) 줄의 과목 이름 = 재무제표 과목 이름(금액 열 · 합계 열에서). 2) 열 이름 = 과목 이름인 가로 표(금액 줄에서).
    3) 과목을 제목으로 단 표(또는 과목이 가리킨 주석의 첫 표)의 합계 줄 · 기초 · 기말 줄. 4) 재무제표에 없는 과목 이름이 두 주석에 한 번씩."""
    refs: dict[str, set] = {}                            # 주석 번호 → 그 주석을 가리킨 과목 이름
    line_refs: dict[tuple, set] = {}                     # (재무제표, 줄) → 그 과목이 가리킨 주석
    for t in fs.tables:
        for i, rs in enumerate(t.refs or []):
            for n in rs:
                refs.setdefault(f"주석{n}", set()).add(_fs_name(_labels(t)[i]))
                line_refs.setdefault((t.id, i), set()).add(f"주석{n}")

    def elsewhere(lt, li, key):
        """「기타」 로 시작하는 과목이 다른 주석을 가리키고, 이 주석은 다른 과목이 가리킨다(성격별 비용 주석의 「기타 비용」 ≠ 손익계산서 기타비용)."""
        mine = line_refs.get((lt.id, li))
        return _fs_name(_labels(lt)[li]).startswith("기타") and bool(mine) and key not in mine and bool(refs.get(key))

    pool: dict[tuple, list] = {}                          # (과목 이름, 기간) → 주석 칸들(4)
    cf_refs = {k for t in fs.tables if t.id.startswith("현금흐름표") for rs in (t.refs or []) for k in (f"주석{n}" for n in rs)}
    for p in doc.parts:
        if not p.key.startswith("주석"):
            continue
        labels_of = period_labels(p)
        tables = [x[1] for x in p.items if x[0] == "t" and not x[1].kind]
        for t in tables:
            if _skip_note(doc, t):
                continue
            rel = _rel_word(labels_of.get(t.id, "") or t.caption)
            subjects = {s for s in (_subject(p.title), _subject(t.caption), _subject(labels_of.get(t.id, ""))) if len(s) >= 2}
            pointed = refs.get(p.key, set())
            labels = _labels(t)
            cols = [j for j in range(1, len(t.header)) if any(_isnum(r[j]) for r in t.nums) and not is_rate(t.header[j])]
            vcols = _value_cols(t, cols)
            data_rows = [i for i in range(len(t.rows)) if any(_isnum(t.nums[i][j]) and not t.rate(i, j) for j in cols) and not is_rate(_labels(t)[i])]
            totals = [i for i in data_rows if total_kind(labels[i]) == "합계"]
            items = {i: _item(t, i) for i in data_rows}
            bal = _table_kind(t, rel[1])

            adj = _cf_adjust(doc, p.key, cf_refs)

            def link(i, j, lt, li, how, basis, flow, t=t, rel=rel, adj=adj):
                per = note_period(doc, t, i, j, flow, interim, rel)
                hit = fs.cell(lt, li, per) if per else None
                if hit and adj and not lt.id.startswith("현금흐름표"):      # 현금흐름 조정 내역 = 손익 과목: 조건부, 수익 · 이익은 부호 반대
                    add(how, (t, i, j), hit, basis, grade="조건부", when=CF_ADJ_WHEN, sign=_adjust_sign(_fs_name(_labels(lt)[li])))
                elif hit:
                    add(how, (t, i, j), hit, basis)
                return hit is not None

            # 1) 줄의 과목 이름 = 과목 이름. 합계 줄이 있는 표에서 제목과 같은 이름의 줄은 내역 한 줄이라 합계 줄로 잇는다(3)
            for i in data_rows:
                name = items[i]
                if not name or (totals and name in subjects and i not in totals):
                    continue
                hit_fs = False
                for flow in (False, True):
                    lines = fs.lines(name, flow)
                    if len({id(lt) for lt, _ in lines}) != len(lines):      # 한 표에 같은 이름 과목이 둘이면 고르지 않는다
                        continue
                    for lt, li in lines:
                        if elsewhere(lt, li, p.key):
                            continue
                        why = "가리킨 주석" if name in pointed else "같은 이름"
                        for j in vcols:
                            hit_fs |= link(i, j, lt, li, "주석 열" if name in pointed else "이름",
                                           f"{p.key} 「{labels[i]}」 줄 = {lt.id} 「{_labels(lt)[li]}」({why})", flow)
                if not hit_fs and len(name) >= 3 and not fs.lines(name) and not total_kind(labels[i]) and "소계" not in norm(labels[i]):      # 소계 아래 줄은 일부만 담는다(판관비 주석의 감가상각비)
                    for j in vcols:
                        per = note_period(doc, t, i, j, not bal, interim, rel)
                        if per:
                            pool.setdefault((name, per), []).append((t, i, j, adj))
            # 2) 열 이름 = 과목 이름(가로 표). 금액 줄은 이름이 「금융자산」 「합계」 처럼 과목이 아닌 줄
            vrows = [i for i in data_rows if not items[i]]
            head = _common_head([t.header[j] for j in cols])
            for j in cols:
                if j in vcols:
                    continue
                name = _row_name(str(t.header[j])[len(head):] if head else t.header[j])
                for flow in (False, True):
                    lines = fs.lines(name, flow) if name else []
                    if len({id(lt) for lt, _ in lines}) != len(lines):
                        continue
                    for lt, li in lines:
                        if elsewhere(lt, li, p.key):
                            continue
                        for i in vrows:
                            link(i, j, lt, li, "주석 열" if name in pointed else "이름",
                                 f"{p.key} 「{t.header[j]}」 열 = {lt.id} 「{_labels(lt)[li]}」", flow)
            # 3) 과목을 제목으로 단 표의 합계 줄 · 기초 · 기말 줄 · 줄이 하나인 표. 제목으로 못 정하면 과목이 가리킨 주석의 첫 표와 그 짝(같은 머리줄의 전기 표)
            cands = set()
            for s in subjects:
                cands |= {(lt.id, li) for lt, li in fs.lines(s, subject=True)}
            by_title = bool(cands)
            first = tables[0] if tables else None
            if len(pointed) == 1 and not cands and first is not None and (t is first or [norm(h) for h in t.header] == [norm(h) for h in first.header]):
                cands = {(lt.id, li) for s in pointed for lt, li in fs.lines(s)}
            if not cands or len({c[0] for c in cands}) != len(cands):      # 표마다 과목이 하나로 정해질 때만
                continue
            ends = [i for i in data_rows if _point(labels[i]) and (not items[i] or items[i] in subjects)]
            one = len(data_rows) == 1 and (by_title or len(vcols) == 1)
            rows = totals[-1:] if totals else (data_rows if one else [])
            pcols = [k for k in cols if _point(t.header[k])]
            for lid, li in cands:
                lt = doc.table(lid)
                flow = not lid.startswith("재무상태표")
                for i in rows + ([] if flow else ends):
                    if items[i] and items[i] not in subjects and i not in ends and not one:
                        continue
                    what = "합계 줄" if i in totals else ("기초 · 기말 줄" if i in ends else "줄이 하나")
                    for j in (vcols if i in ends or not pcols else pcols):
                        link(i, j, lt, li, "주석 열" if _fs_name(_labels(lt)[li]) in pointed else "이름",
                             f"{p.key} {_subject(p.title) or p.title} 표의 {what} = {lt.id} 「{_labels(lt)[li]}」", flow)
    order = {t.id: k for k, t in enumerate(doc.tables())}
    for (name, per), cells in pool.items():               # 4) 재무제표에 없는 과목이 여러 주석에: 주석마다 한 칸일 때만, 앞 주석 칸에 잇는다
        notes = Counter(doc.part_of(c[0].id).key for c in cells)
        tabs = Counter(c[0].id for c in cells)
        if len(notes) < 2 or len(notes) > 3 or max(tabs.values()) > 1 or max(notes.values()) > 1:
            continue
        cells.sort(key=lambda c: order[c[0].id])
        a = cells[0]
        for c in cells[1:]:
            text = f"{doc.part_of(c[0].id).key} 「{_labels(c[0])[c[1]]}」 = {doc.part_of(a[0].id).key} 「{_labels(a[0])[a[1]]}」(같은 과목 이름)"
            if c[3] != a[3]:                              # 한쪽이 현금흐름 조정 내역
                add("이름", c[:3], a[:3], text, grade="조건부", when=CF_ADJ_WHEN, sign=_adjust_sign(name))
            else:
                add("이름", c[:3], a[:3], text)


def _sce_props(doc: Doc, fs: _Fs, interim: bool, add) -> None:
    """자본변동표: 기초 · 기말 줄 × 자본 항목 열 = 재무상태표 과목(합계 열은 자본총계), 순이익 · 기타포괄손익 줄의 합계 열 = 손익계산서 같은 이름 과목.
    열 이름 앞의 공통 낱말(「자본의 구성요소」)은 뗀다. 블록의 기간은 기초 줄 이름(「전기말(당기초)」)으로, 없으면 기초 줄이 둘이면 앞이 전기다."""
    t = doc.table("자본변동표")
    if t is None:
        return
    cols = [j for j in range(1, len(t.header)) if any(_isnum(r[j]) for r in t.nums)]
    head = _common_head([t.header[j] for j in cols])
    labels = _labels(t)
    tags = t.xbrl or {}
    starts = [i for i, lab in enumerate(labels) if _point(lab) == "s"]

    def block(i):
        k = max((s for s in starts if s <= i), default=None)
        if k is None:
            return None
        if "당기초" in norm(labels[k]):
            return "C"
        return _rel_word(labels[k])[0] or ("C" if k == starts[-1] else "P")

    for i, lab in enumerate(labels):
        point, rel = _point(lab), block(i)
        for j in cols:
            tail = str(t.header[j])[len(head):].strip() if head else str(t.header[j]).strip()
            whole = not tail or total_kind(t.header[j]) == "합계"
            per = _ctx_period(*tags[(i, j)][:2]) if (i, j) in tags else None
            if point:
                if per is None and rel:
                    per = ("P.e" if rel == "C" else "PP.e") if point == "s" else ("C.e" if rel == "C" else ("Ph.e" if interim else "P.e"))
                for lt, li in fs.lines("자본총계" if whole else _plain(tail), False):
                    hit = fs.cell(lt, li, per) if per else None
                    if hit:
                        add("자본변동표", (t, i, j), hit, f"자본변동표 「{lab}」 줄 「{t.header[j]}」 열 = 재무상태표 「{_labels(lt)[li]}」")
            elif whole:
                per = per or (rel + ".d" if rel else None)
                lines = fs.lines(_fs_name(lab), True)
                if any(not lt.id.startswith("현금흐름표") for lt, _ in lines):      # 순이익 · 기타포괄손익은 손익계산서에만 잇는다
                    lines = [(lt, li) for lt, li in lines if not lt.id.startswith("현금흐름표")]
                for lt, li in lines:
                    hit = fs.cell(lt, li, per) if per else None
                    if not hit:
                        continue
                    if lt.id.startswith("현금흐름표"):
                        add("자본변동표", (t, i, j), hit, f"자본변동표 「{lab}」 = 현금흐름표 「{_labels(lt)[li]}」", grade="조건부",
                            when="자본변동표의 금액이 모두 그 기간에 현금으로 오갔다")
                    else:
                        add("자본변동표", (t, i, j), hit, f"자본변동표 「{lab}」 줄 합계 열 = {lt.id} 「{_labels(lt)[li]}」")


def _roll_props(doc: Doc, add) -> None:
    """연차 보고서: 같은 주석의 당기 변동표 기초 = 전기 변동표 기말(같은 줄 · 같은 열 이름)."""
    for p in doc.parts:
        if not p.key.startswith("주석"):
            continue
        labels_of = period_labels(p)
        tabs = [x[1] for x in p.items if x[0] == "t" and not x[1].kind]
        for a in tabs:
            ra = _rel_word(labels_of.get(a.id, "") or a.caption)[0]
            if ra != "C":
                continue
            for b in tabs:
                rb = _rel_word(labels_of.get(b.id, "") or b.caption)[0]
                if b is a or rb != "P" or [norm(h) for h in a.header] != [norm(h) for h in b.header]:
                    continue
                la, lb = [norm(x) for x in _labels(a)], [norm(x) for x in _labels(b)]
                for i, x in enumerate(la):
                    if _point(x) != "s":
                        continue
                    k = next((k for k, y in enumerate(lb) if _point(y) == "e"), None)
                    if k is None:
                        continue
                    for j in range(1, len(a.header)):
                        if _isnum(a.nums[i][j]) and _isnum(b.nums[k][j]):
                            add("변동표", (a, i, j), (b, k, j), f"{p.key} 당기 표 「{_labels(a)[i]}」 = 전기 표 「{_labels(b)[k]}」")
                for j, h in enumerate(a.header):          # 열이 기초 · 기말인 변동표
                    if j and _point(h) == "s":
                        k = next((k for k, y in enumerate(b.header) if k and _point(y) == "e"), None)
                        if k is None:
                            continue
                        for i in range(len(la)):
                            ib = next((n for n, y in enumerate(lb) if y == la[i]), None)
                            if ib is not None and _isnum(a.nums[i][j]) and _isnum(b.nums[ib][k]):
                                add("변동표", (a, i, j), (b, ib, k), f"{p.key} 당기 표 「{a.header[j]}」 = 전기 표 「{b.header[k]}」")


# ---- 2차(10-22): 회사별 표 · 이름 짝 · 문장 ----------------------------------------------------------------

def _sp(s) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip()


def _group_props(doc: Doc, add_sum) -> None:
    """같은 주석의 범주 합계 표 = 회사별 표. 두 표의 줄 이름과 기간 이름(표 위 문단의 「당반기」 「전기말」)이 같고, 회사별 표의 열 이름이
    합계 표의 열 이름 뒤에 회사 이름을 붙인 꼴이면(「… 모든 종속기업의 합계」 → 「… 모든 종속기업의 합계 가나다㈜」) 합계 표 칸 = 회사별 표
    같은 줄의 그 열들의 합이다. XBRL 꼴 특수관계자 주석이 이렇다(한 상장사 2026 반기 별도 주석 28). 범주마다 「기타」 열이 있으면 회사를 모두 담은 것으로
    보고 항등식, 없으면 조건부다. 열 이름이 맞는 회사별 표가 둘 이상이면(기간 이름이 없는 표 둘) 고르지 않는다."""
    for p in doc.parts:
        if not p.key.startswith("주석"):
            continue
        labels_of = period_labels(p)
        tabs = [x[1] for x in p.items if x[0] == "t" and not x[1].kind]
        for a in tabs:
            rows = [norm(x) for x in _labels(a)]
            heads = {k: _sp(a.header[k]) for k in range(1, len(a.header))
                     if _sp(a.header[k]) and not is_rate(a.header[k]) and any(_isnum(r[k]) for r in a.nums)}
            match = []
            for b in tabs:
                if b is a or [norm(x) for x in _labels(b)] != rows or labels_of.get(b.id) != labels_of.get(a.id):
                    continue
                groups = {k: [j for j in range(1, len(b.header)) if _sp(b.header[j]).startswith(h + " ")] for k, h in heads.items()}
                if any(len(g) >= 2 for g in groups.values()):
                    match.append((b, groups))
            if len(match) != 1:
                continue
            b, groups = match[0]
            for k, g in groups.items():
                if len(g) < 2:
                    continue
                whole = any(_plain(_sp(b.header[j])[len(heads[k]):]) == "기타" for j in g)
                for i, lab in enumerate(_labels(a)):
                    if not _isnum(a.nums[i][k]) or a.rate(i, k) or is_rate(lab):
                        continue
                    terms = [(b, i, j) for j in g if _isnum(b.nums[i][j])]
                    if not terms:
                        continue
                    add_sum("회사별 표", (a, i, k), terms,
                            f"{p.key} 범주 합계 표 = 회사별 표 {b.id} 의 같은 줄, 같은 범주 열 {len(terms)}칸의 합" + (" (범주마다 「기타」 열이 있다)" if whole else ""),
                            grade="항등식" if whole else "조건부", when=None if whole else "회사별 표에 그 범주의 회사가 모두 있다",
                            sum_of={"table": b.id, "row": _ref(_labels(b), i)[0], "head": cut_prefix(heads[k], col_prefix(b.header)), "n": len(terms)})


ASSETS = ("유형자산", "무형자산", "투자부동산")
_ASSET_WORDS = re.compile(r"사용권자산포함|" + "|".join(ASSETS))
_BUY = re.compile(r"취득|자본적지출")
_NOT_BUY = re.compile(r"취득원가|사업결합|연결범위|종속기업|처분|대체")
DEP_NAMES = {"유형자산": ("감가상각비", "감가상각", "상각비", "상각"), "무형자산": ("상각비", "상각")}
NATURE_NAME = {"유형자산": "감가상각비", "무형자산": "무형자산상각비"}
BUY_WHEN = "취득한 금액을 그 기간에 모두 현금으로 치렀다(취득 관련 미지급금 변동 · 현금 없는 취득이 없다)"
DEP_WHEN = "성격별 비용의 {0}가 모두 이 변동표의 것이다(다른 자산의 상각이 섞이지 않았다)"
DB_WHEN = "퇴직급여가 모두 확정급여제도 비용이다(확정기여형 비용이 없다)"


def _cells_by_period(doc: Doc, t: Table, cells: list, interim: bool, rel: tuple) -> dict:
    """[(줄, 열)] → {기간 이름: (표, 줄, 열)}. 같은 기간 칸이 둘 이상이면 그 기간은 뺀다."""
    got: dict = {}
    for i, j in cells:
        per = note_period(doc, t, i, j, True, interim, rel)
        if per:
            got.setdefault(per, []).append((t, i, j))
    return {k: v[0] for k, v in got.items() if len(v) == 1}


def _item_cells(t: Table, want) -> list:
    """이름이 want(이름 → 참거짓)에 맞는 칸. 줄이 항목인 표는 그 줄 × 금액 열, 열이 항목인 표(「구분 | 기초 | 취득 | … | 기말」)는 그 열 × 합계 줄."""
    labels = _labels(t)
    cols = [j for j in range(1, len(t.header)) if any(_isnum(r[j]) for r in t.nums) and not is_rate(t.header[j])]
    data_rows = [i for i in range(len(t.rows)) if any(_isnum(t.nums[i][j]) for j in cols) and not is_rate(labels[i])]
    vcols = _value_cols(t, cols)
    out = [(i, j) for i in data_rows if want(_item(t, i)) for j in vcols]
    if not out:
        totals = [i for i in data_rows if total_kind(labels[i]) == "합계"]
        row = totals[-1] if totals else (data_rows[0] if len(data_rows) == 1 else None)
        if row is not None:
            out = [(row, j) for j in cols if want(_row_name(t.header[j]))]
    return out


def _sign(a: tuple, b: tuple) -> int:
    """두 칸 모두 XBRL 항목이 있으면 한쪽만 부호를 뒤집어 보였는지(ANEGATED)로 부호를 정한다. 없으면 같은 부호로 낸다(고칠 곳은 AI 가 고친다)."""
    ta, tb = (a[0].xbrl or {}).get(a[1:]), (b[0].xbrl or {}).get(b[1:])
    return -1 if ta and tb and ta[2] != tb[2] else 1


def _pair_props(doc: Doc, fs: _Fs, interim: bool, add) -> None:
    """이름이 다른 흔한 짝(조건부). 금액은 보지 않는다.
    1) 유형자산 · 무형자산 · 투자부동산 변동표의 취득(「일반취득 및 자본적지출」 「개별취득」) = 현금흐름표 「○○의 취득」.
    2) 유형자산 변동표의 감가상각비 = 성격별 비용 주석의 감가상각비, 무형자산 변동표의 상각 = 성격별 비용의 무형자산상각비.
    3) 성격별 비용의 퇴직급여 = 퇴직급여 주석에서 근무원가를 더한 표의 합계 줄.
    칸은 기간(당기 · 전기 누적)이 같을 때만 잇는다."""
    rolls, nature, db = [], [], []
    for p in doc.parts:
        if not p.key.startswith("주석"):
            continue
        labels_of = period_labels(p)
        title = _plain(p.title)
        asset = next((a for a in ASSETS if a in title), None)
        for x in p.items:
            if x[0] != "t" or x[1].kind:
                continue
            t = x[1]
            rel = _rel_word(labels_of.get(t.id, "") or t.caption)
            labels = _labels(t)
            if asset and (any(_point(h) for h in t.header[1:]) or any(_point(v) for v in labels)):
                rolls.append((asset, t, rel))
            if "성격별" in title or "성격별" in _plain(t.caption):
                nature.append((t, rel))
            if re.search(r"퇴직급여|확정급여", title) and any("근무원가" in norm(v) for v in labels):
                db.append((t, rel))

    def bare(name):
        return _ASSET_WORDS.sub("", name or "")

    def nature_cells(nt, nrel, name):
        rows = [i for i in range(len(nt.rows)) if re.sub(r"^(?:비용의)?성격별(?:비용)?(?=.)", "", _item(nt, i)) == name]      # 줄 이름이 한 칸이면 「성격별 비용 감가상각비」
        if len(rows) != 1:
            return None, {}
        cols = [j for j in range(1, len(nt.header)) if _isnum(nt.nums[rows[0]][j])]
        return rows[0], _cells_by_period(doc, nt, [(rows[0], j) for j in _value_cols(nt, cols)], interim, nrel)

    for asset, t, rel in rolls:
        key = doc.part_of(t.id).key
        buy = _cells_by_period(doc, t, _item_cells(t, lambda n: bool(_BUY.search(bare(n))) and not _NOT_BUY.search(n or "")), interim, rel)
        for lt, li in fs.lines(asset + "의취득", True) + fs.lines(asset + "취득", True):
            if not lt.id.startswith("현금흐름표"):
                continue
            for per, cell in buy.items():
                hit = fs.cell(lt, li, per)
                if hit:
                    add("이름 짝", cell, hit, f"{key} 변동표 「{_labels(t)[cell[1]]}」 = 현금흐름표 「{_labels(lt)[li]}」(취득)",
                        grade="조건부", when=BUY_WHEN, sign=_sign(cell, hit))
        if asset not in NATURE_NAME:
            continue
        dep = _cells_by_period(doc, t, _item_cells(t, lambda n: bare(n) in DEP_NAMES[asset] or n == NATURE_NAME[asset]), interim, rel)
        for nt, nrel in nature:
            row, got = nature_cells(nt, nrel, NATURE_NAME[asset])
            for per, cell in dep.items():
                if per in got:
                    add("이름 짝", cell, got[per], f"{key} 변동표 「{_labels(t)[cell[1]]}」 = 성격별 비용 「{_labels(nt)[row]}」",
                        grade="조건부", when=DEP_WHEN.format(NATURE_NAME[asset]), sign=_sign(cell, got[per]))
    for nt, nrel in nature:
        row, mine = nature_cells(nt, nrel, "퇴직급여")
        for t, rel in db:
            labels = _labels(t)
            tot = [i for i, v in enumerate(labels) if (total_kind(v) == "합계" or "합계" in norm(v)) and any(_isnum(x) for x in t.nums[i][1:])]
            if not tot:
                continue
            i = tot[-1]
            cols = [j for j in range(1, len(t.header)) if _isnum(t.nums[i][j]) and not is_rate(t.header[j])]
            got = _cells_by_period(doc, t, [(i, j) for j in _value_cols(t, cols)], interim, rel)
            for per, cell in mine.items():
                if per in got:
                    add("이름 짝", cell, got[per], f"성격별 비용 「{_labels(nt)[row]}」 = {doc.part_of(t.id).key} 「{labels[i]}」(확정급여 비용)",
                        grade="조건부", when=DB_WHEN, sign=_sign(cell, got[per]))


_UNIT_PAREN = re.compile(r"\(\s*(?:단위\s*:?\s*)?(?:원|천원|백만원|억원|주|%|\*?\s*\d*|주\s*\d+)\s*\)")


def _words(name: str) -> list[str]:
    """이름을 글에서 찾을 낱말로: 단위 · 각주 괄호를 떼고 띄어쓰기 · 쉼표 · 괄호로 나눈다(「발행주식 액면 총액(백만원)」 → 발행주식 · 액면 · 총액,
    「임직원 주식보상(우수인력)」 → 임직원 · 주식보상 · 우수인력)."""
    s = _UNIT_PAREN.sub(" ", str(name or ""))
    return [w for w in re.split(r"[\s,·ㆍ:()\[\]]+", s) if w]


def _find_words(text: str, words: list[str], start: int = 0) -> int | None:
    """띄어쓰기를 뗀 글에서 낱말이 차례로 다 나오면 마지막 낱말이 끝나는 자리."""
    if not words:
        return None
    pos = start
    for w in words:
        k = text.find(w, pos)
        if k < 0:
            return None
        pos = k + len(w)
    return pos


def _sentence_props(doc: Doc, add) -> None:
    """문장 금액 표의 「표 안 글자 칸」 줄(「주석15-1 자본금에 대한 설명 · 주식의 종류 합계」) = 같은 표의 금액 칸.
    그 글자 칸에서 금액 바로 앞의 글(앞 금액 뒤부터)에 그 표의 줄 이름이 있으면 그 줄, 그 뒤에 열 이름이 있으면 그 열(없으면 글자 칸의 열)이다.
    줄 이름 없이 열 이름만 있으면 앞 금액의 줄을 잇는다(「액면총액은 664,865백만원(보통주 584,628백만원」). 줄 이름도 열 이름도 없으면
    그 열에 금액 칸이 하나뿐일 때만 그 칸이다. 이름과 금액 사이에 다른 숫자가 끼면 내지 않는다(「총수는 250억주(1주의 액면금액: 100원)」).
    금액이 같은 칸을 찾지 않는다(설계 6.3절)."""
    from .dsd_grid import _SENT_AMOUNT, _won

    for p in doc.parts:
        s = doc.table(f"{p.key}-문장")
        if s is None:
            continue
        found: dict[str, list] = {}
        for x in p.items:
            if x[0] != "t" or x[1].kind:
                continue
            t = x[1]
            for r, row in enumerate(t.rows):
                for c in range(1, len(row)):
                    if t.nums[r][c] is not None or not row[c]:
                        continue
                    text, prev = str(row[c]), 0
                    for m in _SENT_AMOUNT.finditer(text):      # dsd_grid.sentence_table 과 같은 차례로 금액을 센다
                        got = _won(m.group(1), m.group(2))
                        if got is None or got[0] == 0:
                            continue
                        head = t.header[c] if c < len(t.header) else ""
                        found.setdefault(f"{t.id} {row[0]} · {head}".strip(" ·"), []).append((t, r, c, norm(text[prev:m.start()])))
                        prev = m.end()
        labels = _labels(s)
        rows_of = Counter(lab for i, lab in enumerate(labels) if _isnum(s.nums[i][2]))
        nth, carry = Counter(), {}
        for i, lab in enumerate(labels):
            if not _isnum(s.nums[i][2]):
                continue
            k = nth[lab]
            nth[lab] += 1
            got = found.get(lab) or []
            if len(got) != rows_of[lab]:
                continue
            t, r, c, seg = got[k]
            tl, pre, here = _labels(t), col_prefix(t.header), (t.id, r, c)

            def money(ii, jj, t=t, tl=tl):
                return _isnum(t.nums[ii][jj]) and not t.rate(ii, jj) and not is_rate(tl[ii]) and not is_rate(t.header[jj])

            best = None                                   # (줄, 줄 이름이 끝나는 자리)
            for ii, v in enumerate(tl):
                if ii != r and any(money(ii, jj) for jj in range(1, len(t.header))):
                    end = _find_words(seg, _words(v))
                    if end is not None and (best is None or end > best[1]):
                        best = (ii, end)
            col, cend = c, None
            for jj in range(1, len(t.header)):
                if jj == c:                               # 글자 칸의 열 이름(「성과연동주식보상제도」)은 다른 열을 가리킨 것이 아니다
                    continue
                end = _find_words(seg, _words(cut_prefix(t.header[jj], pre)), best[1] if best else 0)
                if end is not None and len(seg) - end <= 3 and (cend is None or end > cend):      # 열 이름은 금액 바로 앞(「(보통주 584,628백만원」)
                    col, cend = jj, end
            last = max([x for x in (best[1] if best else None, cend) if x is not None], default=None)
            if last is not None and re.search(r"\d", seg[last:]):      # 이름과 금액 사이에 다른 숫자가 있다
                carry[here] = None
                continue
            if best:
                row, why = best[0], "글에서 금액 바로 앞에 줄 이름이 있다"
            elif cend is not None and carry.get(here) is not None:
                row, why = carry[here], "글에서 금액 바로 앞에 열 이름이 있고 줄은 앞 금액의 줄이다"
            else:
                only = [ii for ii in range(len(tl)) if ii != r and money(ii, c)]
                if cend is not None or len(only) != 1:
                    carry[here] = None
                    continue
                row, why = only[0], "그 열의 금액 칸이 하나뿐이다"
            carry[here] = row
            if money(row, col):
                add("문장", (s, i, 2), (t, row, col), f"{t.id} 「{tl[r]}」 칸 글의 금액 = 같은 표 「{tl[row]}」 · 「{t.header[col]}」({why})")
