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
        if not flow and re.search(r"전기\s*초|전전기\s*말", norm(t.header[j])):      # 재작성한 재무상태표의 「제 31기 전기초」 열(2026-11-09)
            out[j] = "PP.e"
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


# 확정 규칙(2026-11-09 레퍼 규칙 엔진화): 공시 원문에 판정 없이 넣었을 때 금액이 98% 넘게 맞는 근거. AI 읽기 자료에 싣지 않고 바로 연결로 넣는다.
# 공개 원문 200건: 변동표 98.3% · 같은 주석 표 98.4% · 자본변동표 97.9% · 계산식 100%. 재무제표끼리 97.9% · 변동표 과목 97.6% 는 기준에 조금 못 미쳐
# 후보로 두고, 이름 · 주석 열 · 자본변동표 총포괄 · 현금흐름 조정(조건부)도 후보다.
CONFIRMED = {"변동표", "같은 주석 표", "자본변동표", "계산식"}


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
        if (lt.id == rt.id and how != "변동표") or not _isnum(lt.nums[li][lj]) or not _isnum(rt.nums[ri][rj]):
            return                                        # 같은 표 안은 「당기 열 기초 = 전기 열 기말」 만(2026-11-09, 그 전에는 막혀 하나도 나오지 않았다)
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

    def add_calc(how, left, rights, expr, basis):
        """계산식 후보: 왼쪽 칸 = expr(오른쪽 칸들). 항 자리는 {0} {1} …."""
        lt, li, lj = left
        key = ("식", (lt.id, li, lj), tuple((t.id, i, j) for t, i, j in rights))
        if key in seen or not all(_isnum(t.nums[i][j]) for t, i, j in [left] + list(rights)):
            return
        seen.add(key)
        out.append({"how": how, "left": _ref_of(lt, li, lj, fs.periods.get(lt.id)), "right": [_ref_of(t, i, j, fs.periods.get(t.id)) for t, i, j in rights],
                    "grade": "항등식", "basis": basis, "expr": expr})

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
    _fs_cross_props(doc, fs, add)
    _sce_tci_props(doc, fs, add_sum)
    if not interim:
        _roll_props(doc, add)
    _note_cells_props(doc, interim, add)
    _move_fs_props(doc, fs, interim, add, add_sum)
    _group_props(doc, add_sum)
    _calc_props(doc, add_calc)
    _pair_props(doc, fs, interim, add)
    _sentence_props(doc, add)
    order = {t.id: k for k, t in enumerate(doc.tables())}
    out.sort(key=lambda x: (order.get(x["left"]["table"], 0), x["left"]["row"], x["left"]["col"]))
    for x in out:
        if x["how"] in CONFIRMED and not x.get("when"):
            x["tier"] = "확정"
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


_MOVE_ROW = re.compile(r"^(?:취득원가|감가상각누계액|상각누계액|손상차손누계액|정부보조금|환율변동효과|환율차이|사업결합.*증감|대체|기타|순외환차이)$")
_CARRY_HEAD = re.compile(r"장부|순액|잔액|^말$|^기말$|^합계$|^계$|^금액$|^$")
_OTHER_MEASURE = re.compile(r"취득|원가|누계|충당금|손상|재평가|보조금|평가손실|할인차금|명목|액면|채권액|총액")
_RISK_INTRO = re.compile(r"위험|노출|민감도|사업결합|취득일")
_FLOW_INTRO = re.compile(r"순손익|손익|수익|비용|발생한|인식한|인식된")
_BAL_INTRO = re.compile(r"장부금액|잔액|말\s*현재|기말|구성|내역은\s*다음")
_FLOW_OTHER_NOTE = re.compile(r"유형자산|무형자산|투자부동산|사용권자산|리스|퇴직|종업원급여|확정급여|부가가치")
_INVESTEE_NOTE = re.compile(r"관계기업|종속기업|공동기업|지분법")


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
        intro = _intros(p)
        title = _plain(p.title)
        for t in tables:
            if _skip_note(doc, t):
                continue
            if _SUBSET_WORDS.search(intro.get(t.id, "")):
                continue                                  # 담보 · 사용제한 · 운휴 자산 표는 일부 금액이다(공시 원문 76% 다름, 2026-11-09)
            rel = _rel_word(labels_of.get(t.id, "") or t.caption)
            rel2 = _table_rel(labels_of.get(t.id, ""), t.caption)
            subjects = {s for s in (_subject(p.title), _subject(t.caption), _subject(labels_of.get(t.id, ""))) if len(s) >= 2}
            said = intro.get(t.id, "") + " " + norm(str(t.caption or ""))
            has_carry = any(_CARRY_HEAD.search(_measure(h)) for h in t.header[1:])
            not_bal = bool(_RISK_INTRO.search(said)) or (bool(_FLOW_INTRO.search(said)) and not _BAL_INTRO.search(said))
            pointed = refs.get(p.key, set())
            labels = _labels(t)
            cols = [j for j in range(1, len(t.header)) if any(_isnum(r[j]) for r in t.nums) and not is_rate(t.header[j])]
            vcols = _value_cols(t, cols)
            data_rows = [i for i in range(len(t.rows)) if any(_isnum(t.nums[i][j]) and not t.rate(i, j) for j in cols) and not is_rate(_labels(t)[i])]
            totals = [i for i in data_rows if total_kind(labels[i]) == "합계"]
            items = {i: _item(t, i) for i in data_rows}
            bal = _table_kind(t, rel[1])

            adj = _cf_adjust(doc, p.key, cf_refs)

            def link(i, j, lt, li, how, basis, flow, t=t, rel=rel, rel2=rel2, adj=adj, has_carry=has_carry, not_bal=not_bal):
                fname = _fs_name(_labels(lt)[li])
                head = norm(str(t.header[j] or ""))
                if "소계" in norm(_labels(t)[i]):
                    return False                          # 소계 줄은 일부다(공시 원문 86% 다름)
                if not flow:                              # 재무상태표 과목(2026-11-09 지난 실행 AI 의 X 이유를 규칙으로)
                    if adj or not_bal:
                        return False                      # 현금흐름 조정 · 범주별 순손익 · 리스 손익 · 사업결합(취득일) · 신용위험 노출 표는 잔액이 아니다
                    if "수량" in head or (has_carry and _OTHER_MEASURE.search(_measure(head)) and not _CARRY_HEAD.search(_measure(head))):
                        return False                      # 장부금액 열이 있는 표의 취득원가 · 누계액 · 충당금 열, 수량 열
                    if (re.search(r"단기|유동", fname) and "비유동" not in fname and "비유동" in head) or \
                            (re.search(r"장기|비유동", fname) and re.search(r"(?<!비)유동", head) and "비유동" not in head):
                        return False                      # 유동 과목 ↔ 비유동 열, 비유동 과목 ↔ 유동 열
                if flow and _FLOW_OTHER_NOTE.search(title):
                    return False                          # 손익 과목 ↔ 유형자산 · 퇴직급여 · 부가가치 주석: 제조원가 몫이 섞인다(85% 다름)
                if _INVESTEE_NOTE.search(title) and not re.search(r"투자|지분법", fname):
                    return False                          # 관계기업 주석의 「자본총계」 「당기순이익」 은 피투자회사 금액이다
                crel = next((r for r in (_rel_last(t.header[j]), _rel_last(_labels(t)[i]), rel2) if r[0]), None)
                # 표의 기간은 표 앞 글 마지막 문장 뒤로 정한다(첫 낱말로 정하면 「(*) 당기 중 … ② 전기」 를 당기로 읽는다). 모르면 옛 방식
                per = note_period(doc, t, i, j, flow, interim, crel if crel and crel[1] != "초" else rel)
                hit = fs.cell(lt, li, per) if per else None
                if hit and adj and fname in ("당기순이익", "당기순손익") and not lt.id.startswith("현금흐름표"):
                    add(how, (t, i, j), hit, basis)       # 현금흐름 조정 내역의 당기순이익은 더하는 줄이라 손익계산서와 같은 부호다(AI 가 매번 고쳤다)
                elif hit and adj and not lt.id.startswith("현금흐름표"):      # 현금흐름 조정 내역 = 손익 과목: 조건부, 수익 · 이익은 부호 반대
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
                for flow in ((False, True) if name in pointed else (False,)):      # 손익 · 현금흐름 과목은 그 주석을 가리킬 때만 가로 표 열로 잇는다(그 밖은 공시 원문 89% 다름)
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
            # 표 설명이 재무제표의 다른 과목을 말하면(퇴직급여충당부채 주석 안 「(2) 퇴직연금운용자산의 공정가치 및 변동내역」) 제목 과목에 잇지 않는다
            # (2026-11-09 스터디 15 별도: 운용자산 변동표 · 구성 표를 퇴직급여충당부채에 이었다)
            # 설명 글 전체가 아니라 「…의 (공정가치 및) 변동 · 구성 · 내역 · 명세」 앞 과목만 본다. 각주 글(「(*) 유형자산에서 투자부동산으로 …」)이
            # 설명 자리에 든 표가 있다(스터디 02 연결). 재무상태표 두 줄이 같은 주석을 가리켜도(퇴직급여충당부채 · 퇴직연금운용자산 → 주석10)
            # 제목으로 정한 과목만 이 표의 과목이다
            m = re.search(r"([가-힣A-Za-z]+)의(?:공정가치및)?(?:변동|구성|내역|명세)", norm(t.caption or ""))
            subj = ({norm(x) for x in (_subject(p.title), _subject(labels_of.get(t.id, ""))) if len(x) >= 2} if by_title
                    else {norm(x) for x in pointed})
            if m and any(len(n) >= 4 and m.group(1).endswith(n) and not any(n in x or x in n for x in subj) for n in fs.by_name):
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
                    # 줄이 하나인 표의 그 줄이 재무제표의 다른 과목이면(유형자산 주석의 「토지」 한 줄 표) 1) 이 이름으로 잇는다.
                    # 제목 과목(유형자산)에 잇지 않는다(2026-11-09 스터디 16 별도 주석4-3 토지 공시지가 표)
                    if one and items[i] and items[i] not in subjects and fs.lines(items[i]):
                        continue
                    what = "합계 줄" if i in totals else ("기초 · 기말 줄" if i in ends else "줄이 하나")
                    # 공시지가 · 공정가치 · 시가 열은 장부금액이 아니다(판정-근거 3절)
                    for j in [k for k in (vcols if i in ends or not pcols else pcols) if not re.search(r"공시지가|공정가치|시가", norm(t.header[k]))]:
                        link(i, j, lt, li, "주석 열" if _fs_name(_labels(lt)[li]) in pointed else "이름",
                             f"{p.key} {_subject(p.title) or p.title} 표의 {what} = {lt.id} 「{_labels(lt)[li]}」", flow)
    order = {t.id: k for k, t in enumerate(doc.tables())}
    for (name, per), cells in pool.items():               # 4) 재무제표에 없는 과목이 여러 주석에: 주석마다 한 칸일 때만, 앞 주석 칸에 잇는다
        notes = Counter(doc.part_of(c[0].id).key for c in cells)
        tabs = Counter(c[0].id for c in cells)
        if len(notes) < 2 or len(notes) > 3 or max(tabs.values()) > 1 or max(notes.values()) > 1:
            continue
        if _MOVE_ROW.search(name) or any(_movement(c[0]) for c in cells) or any("성격별" in _plain(doc.part_of(c[0].id).title) for c in cells):
            continue                                      # 변동표의 「취득원가」 「환율차이」 「손상차손」 은 주석마다 다른 자산의 변동이다. 성격별 비용 ↔ 판관비 명세는 범위가 다르다
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

    kinds = {j: _sce_col(t.header[j]) for j in cols}
    has_total = any(k == "total" for k in kinds.values())
    for i, lab in enumerate(labels):
        point, rel = _point(lab), block(i)
        for j in cols:
            tail = str(t.header[j])[len(head):].strip() if head else str(t.header[j]).strip()
            tail = _PARENT_HEAD.sub("", tail) if kinds.get(j) is None else tail      # 「지배기업지분 자본금」 → 자본금(2026-11-09 공개 연결 보고서)
            whole = not tail or total_kind(t.header[j]) == "합계"
            if has_total and kinds.get(j) == "parent":
                # 전체 합계 열이 따로 있으면 「지배기업지분 합계」 열은 전체 합계가 아니다. 손익계산서 총액에 잇지 않고 귀속 줄에 잇는다(_sce_tci_props).
                # 전체로 이은 후보는 AI 가 매번 X 로 지웠다(2026-11-08 공개 연결 보고서 P0011 ~ P0020)
                whole = False
                if point:
                    per = _ctx_period(*tags[(i, j)][:2]) if (i, j) in tags else None
                    if per is None and rel:
                        per = ("P.e" if rel == "C" else "PP.e") if point == "s" else ("C.e" if rel == "C" else ("Ph.e" if interim else "P.e"))
                    for lt in fs.tables:
                        if not lt.id.startswith("재무상태표"):
                            continue
                        for li, x in enumerate(_labels(lt)):
                            nx = _fs_name(x)
                            if ("지배" in nx or "소유주" in nx) and "비지배" not in nx and any(_isnum(v) for v in lt.nums[li][1:]):
                                hit = fs.cell(lt, li, per) if per else None
                                if hit:
                                    add("자본변동표", (t, i, j), hit, f"자본변동표 「{lab}」 줄 「{t.header[j]}」 열 = 재무상태표 「{x}」")
                                break
                    continue
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


_PARENT_HEAD = re.compile(r"^\s*지배\s*기업(?:의)?\s*(?:소유주\s*(?:에게\s*귀속되는\s*)?)?(?:지분|자본)?\s*")


_CF_SPLIT = re.compile(r"감가상각비|상각비|퇴직급여|급여|이자비용|이자수익|배당금수익|법인세비용|복리후생비|주식보상비용|주식보상비")
_CF_SKIP = re.compile(r"활동|현금흐름|합계|소계|총계|^계$|조정|가산|차감|증가|감소|순증|순감|변동|수취|지급|납부|환급|유입|유출|취득|처분$|상환|차입|발행")


def _fs_cross_props(doc: Doc, fs: _Fs, add) -> None:
    """재무제표끼리(2026-11-09 레퍼 규칙 3단계): 간접법 현금흐름표의 조정 줄 = 손익계산서의 같은 이름 과목(감가상각비 · 외화환산손실 ·
    유형자산처분이익), 현금흐름표 당기순이익 = 손익계산서 당기순이익, 현금흐름표 기초 · 기말 현금 = 재무상태표 현금및현금성자산.
    이름이 두 표에 한 번씩일 때만. 수익 · 이익은 「차감」 구역 아래면 같은 부호, 아니면 반대 부호(조정에서 뺀다)."""
    cf = [t for t in fs.tables if t.id.startswith("현금흐름표")]
    pl = [t for t in fs.tables if t.id.startswith(("손익계산서", "포괄손익계산서"))]
    bs = [t for t in fs.tables if t.id.startswith("재무상태표")]
    if not cf:
        return
    names = Counter()
    for t in pl:
        for lab in _labels(t):
            names[_fs_name(lab)] += 1
    for t in cf:
        labels = _labels(t)
        counted = Counter(_fs_name(x) for x in labels)
        section = ""
        for i, lab in enumerate(labels):
            name = _fs_name(lab)
            if re.search(r"차감|가산|조정|영업활동|투자활동|재무활동", name):
                section = name
            net = name in ("당기순이익", "당기순손익")
            if len(name) < 3 or counted[name] != 1:
                continue
            if re.search(r"^(?:기초|기말)의?현금|현금및현금성자산의?(?:기초|기말)", name) or re.search(r"(?:기초|기말)현금및현금성자산$", name):
                start = "기초" in name
                for lt in bs:
                    for li, x in enumerate(_labels(lt)):
                        if _fs_name(x) not in ("현금및현금성자산", "현금및현금등가물"):
                            continue
                        for j, per in fs.periods.get(t.id, {}).items():
                            if not _isnum(t.nums[i][j]) or per[-2:] != ".d":
                                continue
                            want = ({"C": "P.e", "P": "PP.e"} if start else {"C": "C.e", "P": "P.e"}).get(per[0])
                            hit = fs.cell(lt, li, want) if want else None
                            if hit:                   # 기초 현금은 전기 재무상태표 재작성 · 매각예정 분류로 다른 일이 있다(공시 원문 200건 기초만 2% 넘게 다름)
                                add("재무제표끼리" if not start else "현금흐름표 기초 현금", (t, i, j), hit,
                                    f"현금흐름표 「{lab}」 = 재무상태표 「{x}」({'기초' if start else '기말'})")
                        break
                continue
            if "조정" not in section and "가산" not in section and "차감" not in section and name not in ("당기순이익", "당기순손실", "당기순손익"):
                continue                                  # 영업활동 조정 구역 밖(투자 · 재무활동)의 같은 이름은 현금 금액이다
            if _CF_SKIP.search(name) and name not in ("당기순이익", "당기순손실", "당기순손익"):
                continue
            if names[name] != 1:
                continue
            if not net and _CF_SPLIT.search(name):
                continue                                  # 감가상각비 · 퇴직급여는 제조원가 몫, 이자는 현금 이자를 따로 적어 손익계산서와 자주 다르다
            sign = 1
            if _GAIN.search(name) and not _LOSS.search(name) and "차감" not in section and name not in ("당기순이익", "당기순손익"):
                sign = -1                                 # 조정에서 빼는 수익 · 이익은 음수로 적는다
            if name == "당기순손실":
                continue                                  # 손실을 양수로 적은 손익계산서 · 음수로 적은 현금흐름표가 섞여 부호를 정할 수 없다
            for lt in pl:
                li = next((k for k, x in enumerate(_labels(lt)) if _fs_name(x) == name), None)
                if li is None:
                    continue
                for j, per in fs.periods.get(t.id, {}).items():
                    hit = fs.cell(lt, li, per) if _isnum(t.nums[i][j]) else None
                    if not hit:
                        continue
                    if net:
                        add("재무제표끼리", (t, i, j), hit, f"현금흐름표 「{lab}」 = {lt.id} 「{_labels(lt)[li]}」")
                    else:                                 # 감가상각비 · 퇴직급여는 제조원가 몫이 섞여 손익계산서와 다른 일이 많다(공시 원문 120건 25% 다름)
                        add("현금흐름 조정", (t, i, j), hit, f"현금흐름표 「{lab}」 = {lt.id} 「{_labels(lt)[li]}」(같은 이름, {section or '조정'})",
                            grade="조건부", when="현금흐름 조정 금액이 그 손익 과목 금액 전부다(제조원가 · 다른 계정에 들어간 몫이 없다)", sign=sign)


def _one(labels: list[str], want, avoid=None) -> int | None:
    hit = [i for i, x in enumerate(labels) if want.search(x) and not (avoid and avoid.search(x))]
    return hit[0] if len(hit) == 1 else None


def _calc_props(doc: Doc, add_calc) -> None:
    """계산식(2026-11-09 레퍼 규칙 3단계 E): 주당이익 주석의 기본주당이익 = 보통주 순이익 ÷ 가중평균유통보통주식수(같은 열),
    자본금 주석의 자본금 = 발행주식수 × 1주 액면금액. 주식수 · 주당 금액 칸의 단위가 원 · 주(1)일 때만(표 단위 천원을 곱하면 틀린다)."""
    for p in doc.parts:
        if not p.key.startswith("주석"):
            continue
        title = _plain(p.title)
        for x in p.items:
            if x[0] != "t" or x[1].kind:
                continue
            t = x[1]
            labels = [_plain(v) for v in _labels(t)]
            cols = [j for j in range(1, len(t.header)) if any(_isnum(r[j]) for r in t.nums)]
            if "주당" in title:
                for kind, mark in (("기본", re.compile(r"희석")), ("희석", None)):
                    if kind == "기본":
                        eps = _one(labels, re.compile(r"^(?:기본)?주당(?:순)?(?:이익|손익|손실)$"), mark)
                        num = _one(labels, re.compile(r"보통주.*순(?:이익|손익|손실)|순(?:이익|손익|손실).*보통주"), mark) \
                            or _one(labels, re.compile(r"순(?:이익|손익|손실)"), re.compile(r"희석|우선주|조정|차감|가산|배당"))
                        den = _one(labels, re.compile(r"가중평균.*주식수"), mark)
                    else:
                        eps = _one(labels, re.compile(r"^희석주당(?:순)?(?:이익|손익|손실)$"))
                        num = _one(labels, re.compile(r"희석.*순(?:이익|손익|손실)|순(?:이익|손익|손실).*희석"))
                        den = _one(labels, re.compile(r"희석.*가중평균.*주식수|가중평균.*희석.*주식수"))
                    if None in (eps, num, den) or len({eps, num, den}) < 3:
                        continue
                    for j in cols:
                        if t.unit_at(eps, j) != 1 or t.unit_at(den, j) != 1:
                            continue                      # 주당 금액 · 주식수에 표 단위(천원)를 곱하면 틀린다
                        add_calc("계산식", (t, eps, j), [(t, num, j), (t, den, j)], "{0} / {1}",
                                 f"{p.key} {t.id} 「{_labels(t)[eps]}」 = 「{_labels(t)[num]}」 ÷ 「{_labels(t)[den]}」({t.header[j]})")
            if "자본금" in title or "자본" == title[-2:]:
                cap = _one(labels, re.compile(r"^(?:보통주)?자본금$"))
                sh = _one(labels, re.compile(r"발행(?:한)?주식(?:의)?(?:총)?수|발행주식수"), re.compile(r"수권|할"))
                par = _one(labels, re.compile(r"(?:1|일)?주(?:당|의)?액면(?:금액|가액|가)?$"))
                if None in (cap, sh, par) or len({cap, sh, par}) < 3:
                    continue
                for j in cols:
                    if t.unit_at(sh, j) != 1 or t.unit_at(par, j) != 1:
                        continue
                    add_calc("계산식", (t, cap, j), [(t, sh, j), (t, par, j)], "{0} * {1}",
                             f"{p.key} {t.id} 「{_labels(t)[cap]}」 = 「{_labels(t)[sh]}」 × 「{_labels(t)[par]}」({t.header[j]})")


def _sce_col(header: str) -> str | None:
    """자본변동표 열의 갈래: total(전체 합계 · 총계) · parent(지배기업 소유주지분 합계) · nci(비지배지분) · None(자본 항목)."""
    n = norm(header)
    if "비지배" in n:
        return "nci"
    if total_kind(header) == "합계" or n.endswith("총계"):
        return "parent" if ("지배" in n or "소유주" in n) else "total"
    return None


_TCI_STOP = re.compile(r"소유주|거래|배당|자본에직접|증자|감자|자기주식|주식기준|주식선택권|합병|연결범위|전환|대체|변동|이익준비금|적립")
_TCI_ITEM_OK = re.compile(r"당기순|기타포괄|재측정|환산|지분법|평가|위험회피|재평가|공정가치|파생|순확정급여|해외사업|이익잉여금변동|자본변동")


def _sce_tci_props(doc: Doc, fs: _Fs, add_sum) -> None:
    """자본변동표의 「총포괄손익」 묶음 합 = 포괄손익계산서 총포괄손익(전체 합계 열), 그 지배 · 비지배 귀속 줄(지배 합계 열 · 비지배 열).
    당기순이익 줄의 지배 합계 열 · 비지배 열 = 포괄손익계산서 당기순이익의 귀속 줄. 금액은 보지 않는다(2026-11-08 3단계:
    공개 연결 보고서 에서 자본변동표만 「지분법이익잉여금변동」 을 총포괄손익에 넣은 차이를 세 실행 가운데 하나만 잡았다).
    묶음 머리 줄에 금액이 있으면 그 줄이 합계다. 머리 줄에 금액이 없으면 다음 묶음 머리(「소유주와의 거래」 · 배당 · 기말 줄)까지 더한다."""
    t = doc.table("자본변동표")
    st = next((x for x in fs.tables if x.id.startswith("손익계산서")), None)
    if t is None or st is None:
        return
    sl = _labels(st)
    num = lambda q, i: any(_isnum(v) for v in q.nums[i][1:])  # noqa: E731

    def attrib(k0: int, what: str) -> dict:
        """귀속 줄. 「총포괄손익의 귀속:」 · 「당기순손익의 귀속:」 머리가 있으면 그 아래에서, 없으면 k0 아래에서 찾는다.
        총포괄 귀속에서는 순이익 귀속 줄을, 순이익 귀속에서는 총포괄 줄을 건너뛴다(한 상장사: 두 귀속 묶음이 맨 끝에 이어 있다)."""
        tci_word = what == "tci"
        # 머리 줄에 금액이 적힌 보고서가 있다(「당기총포괄이익(손실)의 귀속 | 512,306」, 2026-11-09 스터디 02 연결). 금액으로 가르지 않는다
        head = next((k for k, x in enumerate(sl) if "귀속" in norm(x)
                     and (("총포괄" in norm(x)) == tci_word) and (tci_word or "순" in norm(x))), None)
        start = head if head is not None else k0
        got = {}
        for k in range(start + 1, min(start + 4, len(sl))):
            n = norm(sl[k])
            if k > start + 1 and n.endswith(":"):
                break
            if (tci_word and re.search(r"당기순|순이익|순손익|순손실", n)) or (not tci_word and "총포괄" in n):
                continue
            if "비지배" in n:
                got.setdefault("nci", k)
            elif "지배" in n or "소유주" in n:
                got.setdefault("parent", k)
        return got

    tci = next((i for i, x in enumerate(sl) if "총포괄" in norm(x) and num(st, i)), None)
    ni = next((i for i, x in enumerate(sl) if norm(x).startswith(("당기순이익", "당기순손익", "당기순손실", "반기순이익", "분기순이익")) and num(st, i)), None)
    cols = [j for j in range(1, len(t.header)) if any(_isnum(r[j]) for r in t.nums)]
    kinds = {j: _sce_col(t.header[j]) for j in cols}
    if not any(kinds.values()):
        return
    labels = _labels(t)
    starts = [i for i, lab in enumerate(labels) if _point(lab) == "s"]

    def block(i):
        k = max((s0 for s0 in starts if s0 <= i), default=None)
        if k is None:
            return None
        if "당기초" in norm(labels[k]):
            return "C"
        return _rel_word(labels[k])[0] or ("C" if k == starts[-1] else "P")

    for i0, lab in enumerate(labels):
        n = norm(lab).rstrip(":")
        rel = block(i0)
        if rel is None:
            continue
        per = rel + ".d"
        if n.startswith(("총포괄", "당기총포괄")) and tci is not None:
            if any(_isnum(t.nums[i0][j]) for j in cols):
                rows = [i0]
            else:
                rows = []
                for k in range(i0 + 1, len(labels)):
                    lk = labels[k]
                    nk = norm(lk)
                    # 묶음 안 소제목 「기타포괄손익:」 은 넘긴다. 여기서 끊었더니 묶음이 「당기순이익」 한 줄로 줄어 총포괄이익 · 귀속 줄을
                    # 당기순이익 줄과 견줬다(2026-11-09 스터디 07 연결). 묶음을 닫는 소계 줄에 금액이 있으면 그 줄이 묶음 합계다
                    if nk.endswith(":") and "기타포괄" in nk:
                        continue
                    if total_kind(lk) and any(_isnum(t.nums[k][j]) for j in cols):
                        rows = [k]
                        break
                    if not nk or nk.endswith(":") or _point(lk) or total_kind(lk) or (_TCI_STOP.search(nk) and not _TCI_ITEM_OK.search(nk)):
                        break
                    if any(_isnum(t.nums[k][j]) for j in cols):
                        rows.append(k)
            if not rows:
                continue
            target = {"total": tci, **attrib(tci, "tci")}
            for j, kd in kinds.items():
                if kd is None or target.get(kd) is None:
                    continue
                hit = fs.cell(st, target[kd], per)
                cells = [(t, k, j) for k in rows if _isnum(t.nums[k][j])]
                if not hit or not cells:
                    continue
                what = f"「{lab}」 줄" if rows == [i0] else f"「{lab}」 아래 {len(cells)}줄(「{labels[rows[0]]}」 ~ 「{labels[rows[-1]]}」)의 합"
                add_sum("자본변동표 총포괄", hit, cells, f"포괄손익계산서 「{sl[target[kd]]}」 = 자본변동표 {what} · 「{t.header[j]}」 열")
        elif ni is not None and n.startswith(("당기순이익", "당기순손익", "당기순손실", "반기순이익", "분기순이익")):
            att = attrib(ni, "ni")
            for j, kd in kinds.items():
                if kd not in ("parent", "nci") or att.get(kd) is None or not _isnum(t.nums[i0][j]):
                    continue
                hit = fs.cell(st, att[kd], per)
                if hit:
                    add_sum("자본변동표 총포괄", hit, [(t, i0, j)], f"포괄손익계산서 「{sl[ni]}」 의 「{sl[att[kd]]}」 = 자본변동표 「{lab}」 줄 · 「{t.header[j]}」 열")


# 같은 주석 안 표끼리(2026-11-09 레퍼 규칙 엔진화 2단계). AI 가 손으로 쓴 연결의 39%(845/2,153)가 이 꼴이었다.
# 같은 항목 · 같은 시점의 「장부금액 꼴」 칸은 표가 달라도 같은 금액이다(구성 표 장부금액 = 변동표 기말, 당기 변동표 기초 = 전기 변동표 기말).
_CARRY = re.compile(r"^(?:기초|기말|기초잔액|기말잔액|기초금액|기말금액|기초장부금액|기말장부금액|기말순장부금액|기초순장부금액|장부금액|순장부금액|장부가액|순장부가액|"
                    r"잔액|금액|합계|계|총계|말|초)?$")


def _measure(s) -> str:
    """칸 이름에서 기간 · 단위 · 각주를 뗀 「무엇을 잰 칸인가」(「당기말 장부금액」 → 장부금액, 「제 11 (당) 기말」 → 기말)."""
    h = norm(str(s or ""))
    h = re.sub(r"\(\*\d*\)|\(주\d*\)|\(단위[^)]*\)|\(당\)|\(전\)", "", h)
    h = re.sub(r"제\s*\d+\s*기", "", h)
    h = _REL.sub(lambda m: "말" if m.group(3) else "", h)
    h = re.sub(r"\d{4}[.\-년]\s*\d{1,2}[.\-월]?\s*\d{0,2}일?|\d{4}년말?|\d{4}", "", h)
    return re.sub(r"^말(?=순?장부|잔액|금액)", "", _plain(h).replace("말기말", "기말"))   # 「당기말 장부금액」 → 장부금액(「기말장부금액」 은 그대로)


# 항목이 될 수 없는 낱말: 기간 · 측정 · 합계(「당기」 「손상차손누계액」 「적수」 를 항목으로 잡아 다른 뜻의 두 표를 이었다, 공시 원문 40건 58% 안 맞음)
_NOT_ITEM = re.compile(r"^(?:당|전)?(?:기|반기|분기)(?:초|말)?$|원가$|누계액$|정부보조금|적수|공정가치|평가|합계|소계|총계|^계$|^기타$|장부금액|장부가액|잔액$|금액$|"
                       r"취득|처분|상각|대체|증가|감소|전입|환입|지급|사용|설정|손상|재평가|환율|변동|기초|기말|비율|율$|수량|주식수|단가")
_POINT_ROW = re.compile(r"^(?:기초|기말|기초잔액|기말잔액|기초장부금액|기말장부금액|기말순장부금액|기초순장부금액|장부금액|순장부금액|장부가액)$")
# 열 이름이 시점을 말하는 칸만(「당기」 「금액」 「합계」 처럼 잔액인지 손익인지 모르는 열은 뺀다: 손익 인식 표의 「당기」 를 잔액으로 잡았다)
_POINT_COL = re.compile(r"^(?:말|초|기초|기말|기초잔액|기말잔액|기초금액|기말금액|기초장부금액|기말장부금액|기말순장부금액|기초순장부금액|장부금액|순장부금액|장부가액|순장부가액|잔액|말잔액|말금액)$")


_NEUTRAL_SEC = re.compile(r"^(?:유동|비유동|유동성|비유동성|금융자산|금융부채|자산|부채|당기|전기|당기말|전기말)(?:항목|자산|부채)?:?$")
_PERIOD_HEAD = re.compile(r"제\s*\d+\s*\(?\s*(?:당|전)?\s*\)?\s*기|\d{4}|당기|전기|반기|분기")


_REL2 = re.compile(r"(당|전)\s*\)?\s*(반기|분기|기)(말|초)?")
# 다른 뜻의 금액을 재는 표: 표 설명에 이 낱말이 한쪽에만 있으면 잇지 않는다(대손충당금 변동표의 「매출채권」 기말은 충당금이다).
# 열 이름이 「장부금액」 처럼 잰 것을 말하면 _MEASURE_WORDS 는 보지 않는다(「매출채권 등의 장부금액과 대손충당금의 내역」 표의 장부금액 열).
# _SUBSET_WORDS 는 열 이름과 상관없이 일부 금액을 담은 표다(담보로 제공된 자산의 장부금액, 운휴 자산 장부금액)
_MEASURE_WORDS = re.compile(r"충당금|손상|공정가치|차액|미실현|누계액|연령|만기|한도|약정|신용|중지|인식하지\s*(?:못|않)")
_SUBSET_WORDS = re.compile(r"담보|질권|사용제한|제한된|운휴|유휴|중에는|보험|정부보조금")
_DERIVED = re.compile(_MEASURE_WORDS.pattern + "|" + _SUBSET_WORDS.pattern)


# 무엇을 쟀는지 말하지 않는 시점 이름(이 칸의 뜻은 표 앞 글이 정한다). 「장부금액」 처럼 잰 것을 말하면 표 앞 글을 보지 않는다
_GENERIC = re.compile(r"^(?:말|초|기초|기말|기초잔액|기말잔액|기초금액|기말금액|잔액|말잔액|말금액)$")


def _intros(part) -> dict[str, str]:
    """표마다 그 표를 설명하는 글: 표 앞의 마지막 설명 문단(「… 다음과 같습니다」). 「(2) 전기」 처럼 기간만 적은 문단은 건너뛰어
    당기 · 전기 두 표가 한 설명을 함께 쓴다(대손충당금 변동 「(1) 당기」 「(2) 전기」)."""
    out, desc = {}, ""
    for x in part.items:
        if x[0] == "p":
            t = norm(x[1])
            if re.search(r"(?:다음|아래)\s*과\s*같|(?:다음|아래)와\s*같", t):
                desc = t                                  # 「(*1) 감가상각비 중에는 운휴 … 내역은 다음과 같습니다」 는 각주여도 표 설명이다
            elif re.match(r"\(?\*|\(?주\d*\)|※", t) or period_labels_like(t):
                continue                                  # 각주(「(*) 당기 중 손상은 …」)와 기간만 적은 문단은 표 설명이 아니다
            elif _HEADING.match(t):
                desc = t                                  # 「다. 대손충당금 변동 내역」 처럼 번호를 단 제목도 표 설명이다
            continue
        out[x[1].id] = desc
    return out


_HEADING = re.compile(r"(?:[가-하]\.|\(\d+\)|\d+\)|[①-⑳]|\d+(?:-\d+)+\.?)\s*[가-힣A-Za-z]")


def period_labels_like(t: str) -> bool:
    return bool(re.fullmatch(r"[(<\[①-⑳\d.)\s]*(?:제\s*\d+\s*\(?\s*(?:당|전)?\s*\)?\s*기|당기|전기|당기말|전기말|당반기|전반기)[)>\]\s]*(?:\(단위[^)]*\))?", t))


def _rel_last(text) -> tuple[str | None, str | None]:
    """「제 52(전) 기」 「당기말」 처럼 기간을 적은 말의 (C · P, 말 · 기). 여러 개면 마지막 것."""
    ms = list(_REL2.finditer(norm(str(text or ""))))
    if not ms:
        return None, None
    m = ms[-1]
    return ("C" if m.group(1) == "당" else "P"), (m.group(3) or m.group(2))


def _table_rel(label: str, caption: str) -> tuple[str | None, str | None]:
    """표의 기간: 표 바로 위 기간 문단, 아니면 표 앞 글의 마지막 문장 뒤(「… 같습니다. ② 제 52(전) 기」), 아니면 표 앞 글 전체가 한 기간만 말할 때."""
    if label:
        return _rel_last(label)
    cap = norm(str(caption or ""))
    tail = re.split(r"다\.\s*", cap)[-1]
    if _REL2.search(tail):
        return _rel_last(tail)
    rels = {("C" if m.group(1) == "당" else "P") for m in _REL2.finditer(cap)}
    return _rel_last(cap) if len(rels) == 1 else (None, None)


def _movement(t: Table) -> bool:
    """변동표인가: 줄이나 열에 기초와 기말이 함께 있다."""
    for names in (_labels(t), t.header):
        ms = {_measure(x) for x in names}
        if any(_POINT_S.search(m) for m in ms) and any(_POINT_E.search(m) or m == "말" for m in ms):
            return True
    return False


def _sections(t: Table) -> list[str]:
    """줄마다 그 줄이 속한 구역 머리(숫자가 없는 줄, 「대손충당금:」). 유동 · 비유동처럼 과목을 가르지 않는 머리는 빈칸."""
    out, sec = [], ""
    labels = _labels(t)
    for i in range(len(t.rows)):
        if not any(_isnum(v) for v in t.nums[i][1:]):
            name = _plain(labels[i]).rstrip(":")
            sec = "" if not name or _NEUTRAL_SEC.match(name) else name
        out.append(sec)
    return out


def _note_cells_props(doc: Doc, interim: bool, add) -> None:
    """같은 주석의 두 표에서 같은 항목 이름 · 같은 시점의 장부금액 꼴 칸(기초 · 기말 · 장부금액 · 합계 · 금액)을 잇는다.
    항목은 줄 이름이나 열 이름(가로 표)이고, 시점은 note_period 로 정한다(기초는 앞 기말). 표마다 그 항목 · 시점 칸이 하나일 때만 걸고,
    주석 하나에서 그 항목 · 시점이 셋 넘게 나오면 뜻이 갈린 것으로 보고 걸지 않는다. 금액은 보지 않는다."""
    for p in doc.parts:
        if not p.key.startswith("주석"):
            continue
        labels_of = period_labels(p)
        tabs = [x[1] for x in p.items if x[0] == "t" and not x[1].kind and not _skip_note(doc, x[1])]
        if len(tabs) < 2:
            continue
        groups: dict[tuple, list] = {}
        intro = _intros(p)
        for t in tabs:
            rel = _table_rel(labels_of.get(t.id, ""), t.caption)
            derived = bool(_MEASURE_WORDS.search(intro.get(t.id, "")))
            subset = bool(_SUBSET_WORDS.search(intro.get(t.id, "")))
            if subset:
                continue                                  # 담보 · 운휴 자산 표는 일부 금액이다
            labels = _labels(t)
            cols = [j for j in range(1, len(t.header)) if any(_isnum(r[j]) for r in t.nums) and not is_rate(t.header[j])]
            head = _common_head([t.header[j] for j in cols])
            secs, moving = _sections(t), _movement(t)
            lc = _label_cols(t) if t.labels else 1
            compound = any(not any(_isnum(r[j]) for r in t.nums) and any(str(r[j]).strip() for r in t.rows)
                           for j in range(lc, len(t.header)))      # 차입처 · 종류처럼 글 열이 더 있으면 줄 이름만으로 항목이 정해지지 않는다
            for i in range(len(t.rows)):
                if is_rate(labels[i]):
                    continue
                row_item = _item(t, i)
                if row_item and secs[i]:
                    row_item = secs[i] + "/" + row_item         # 「대손충당금: - 매출채권」 은 매출채권이 아니다
                if row_item and i + 1 < len(t.rows) and _CONTRA.search(_plain(labels[i + 1])):
                    row_item = ""                               # 「비품」 바로 아래 「감가상각누계액」: 비품 줄은 취득원가(총액)다(2026-11-09 회사 dsd 시험)
                m_row = _measure(labels[i])
                for j in cols:
                    if not _isnum(t.nums[i][j]) or t.rate(i, j):
                        continue
                    crel = next((r for r in (_rel_last(t.header[j]), _rel_last(labels[i]), rel) if r[0]), (None, None))
                    if rel[0] and crel[0] != rel[0]:
                        continue                              # 전기 표의 「당기말」 열: 표의 기간과 열 이름이 어긋나면 걸지 않는다
                    if not (t.xbrl or {}).get((i, j)) and crel[0] is None:
                        continue                              # 당기 표인지 전기 표인지 모르면 걸지 않는다(같은 꼴 두 표를 같은 시점으로 이었다)
                    per = ({"C": "P.e", "P": "PP.e"}[crel[0]] if crel[1] == "초" and not _point(t.header[j]) and not _point(labels[i])
                           else note_period(doc, t, i, j, False, interim, crel))       # 「3) 전기초」 표의 장부금액은 전전기말이다
                    if not per:
                        continue
                    col_item = _row_name(str(t.header[j])[len(head):] if head else t.header[j])
                    m_col = _measure(t.header[j])
                    if row_item and not compound and len(row_item) >= 2 and _POINT_COL.match(m_col) and not _NOT_ITEM.search(_plain(row_item)):
                        groups.setdefault((row_item, per), []).append((t, i, j))
                    elif (col_item and len(col_item) >= 2 and _POINT_ROW.match(m_row) and not _NOT_ITEM.search(_plain(col_item))
                          and not _PERIOD_HEAD.search(norm(str(t.header[j] or "")))):    # 「제 20(전) 기」 열은 항목이 아니다
                        groups.setdefault((col_item, per), []).append((t, i, j, moving, derived and _GENERIC.match(m_row) is not None, rel[0]))
                        continue
                    else:
                        continue
                    groups[(row_item, per)][-1] = (t, i, j, moving, derived and _GENERIC.match(m_col) is not None, rel[0])
        order = {t.id: k for k, t in enumerate(tabs)}
        for (item, per), cells in groups.items():
            by_tab = Counter(c[0].id for c in cells)
            if len(by_tab) < 2 or max(by_tab.values()) > 1 or len(cells) > 3:
                continue
            if len({c[4] for c in cells}) > 1:            # 한쪽 표만 충당금 · 담보 · 공정가치 표다
                continue
            mov = [c[5] for c in cells if c[3]]
            if len(mov) > 1 and (None in mov or len(set(mov)) < len(mov)):
                continue                                  # 같은 기간 변동표 둘이 같은 시점에 걸리면 다른 것을 잰다(투자차액 변동 · 장부금액 변동). 당기 · 전기 짝이면 잇는다
            cells.sort(key=lambda c: order[c[0].id])
            cells = [c[:3] for c in cells]
            a = cells[0]
            for c in cells[1:]:
                add("같은 주석 표", c, a, f"{p.key} {c[0].id} 「{_labels(c[0])[c[1]]}」 · 「{c[0].header[c[2]]}」 = {a[0].id} 「{_labels(a[0])[a[1]]}」 · "
                    f"「{a[0].header[a[2]]}」(같은 항목 「{item}」 · 같은 시점)")


def _stem(x) -> str:
    """기초 · 기말 짝을 찾는 이름: 기간 · 기초 · 기말을 뗀 나머지(「기초장부금액」 「기말장부금액」 → 장부금액, 「이연법인세자산(부채) 기초」 → 이연법인세자산(부채))."""
    m = _measure(x)
    return re.sub(r"기초|기말|당기초|당기말|전기말|전기초|^말|^초|말$|초$", "", m)


def _pairs(names: list[str]) -> list[tuple[int, int]]:
    """기초 칸과 기말 칸의 짝(줄이나 열 번호). 기초 · 기말을 뗀 이름이 같은 것끼리, 하나씩뿐이면 그 둘."""
    starts = [k for k, x in enumerate(names) if k and _point(x) == "s" and not is_rate(x)]
    ends = [k for k, x in enumerate(names) if k and _point(x) == "e" and not is_rate(x)]
    if len(starts) == 1 and len(ends) == 1:
        a, b = _stem(names[starts[0]]), _stem(names[ends[0]])
        if not a or not b or a.endswith(b) or b.endswith(a):      # 「기초 기대수익률」 ↔ 「기말 할인율」 은 짝이 아니다
            return [(starts[0], ends[0])]
        return []
    out = []
    for a in starts:
        hit = [b for b in ends if _stem(names[b]) == _stem(names[a])]
        if len(hit) == 1:
            out.append((a, hit[0]))
    return out


def _row_pairs(labels: list[str]) -> list[tuple[int, int]]:
    return [(i - 1, k - 1) for i, k in _pairs(["_"] + labels)]


_CONTRA = re.compile(r"누계액|충당금|정부보조금|현재가치할인차금|할인발행차금|국고보조금")
_OTHER_NOTE = re.compile(r"법인세|일시적\s*차이|이연|평가|공정가치|손상|대손충당금|손실충당금|위험|민감도|특수관계|담보")
_NOT_NET = re.compile(r"취득원가|원가의?\s*변동|누계액|정부보조금|담보|손상차손의?\s*변동|공정가치")


def _move_fs_props(doc: Doc, fs: _Fs, interim: bool, add, add_sum) -> None:
    """변동표의 과목 줄 기초 · 기말 = 재무상태표 같은 이름 과목(2026-11-09 레퍼 규칙 종류 A). 열이 기초 · 취득 · … · 기말인 표는
    금액 열이 없어 1) 줄 이름 규칙이 건너뛰었다(AI 가 손으로 쓴 「주석7-4 토지 기말장부가액 = 재무상태표 토지」).
    재무상태표가 과목 바로 아래 감가상각누계액 · 대손충당금처럼 차감 과목을 적으면 변동표(순액) = 과목 + 차감 과목들.
    표 기간을 모르면, 취득원가 · 누계액 변동표면, 과목 이름이 표나 재무상태표에 두 번 나오면 걸지 않는다."""
    contra: dict[tuple, list] = {}
    pointed: dict[tuple, set] = {}                         # 과목이 가리키는 주석(과목 줄에 없으면 위로 올라가 처음 주석 번호가 있는 머리 줄)
    for lt in fs.tables:
        if not lt.id.startswith("재무상태표"):
            continue
        labels = _labels(lt)
        refs = lt.refs or [[] for _ in labels]
        for li in range(len(labels)):
            k = li
            while k >= 0 and not refs[k] and li - k < 12:
                k -= 1
            pointed[(lt.id, li)] = {f"주석{n}" for n in refs[k]} if k >= 0 else set()
            k, got = li + 1, []
            while k < len(labels) and _CONTRA.search(_fs_name(labels[k])):
                got.append(k)
                k += 1
            contra[(lt.id, li)] = got
    for p in doc.parts:
        if not p.key.startswith("주석"):
            continue
        labels_of = period_labels(p)
        intro = _intros(p)
        for x in p.items:
            if x[0] != "t" or x[1].kind or _skip_note(doc, x[1]):
                continue
            t = x[1]
            if _NOT_NET.search(intro.get(t.id, "")) or _SUBSET_WORDS.search(intro.get(t.id, "")) or _OTHER_NOTE.search(_plain(p.title) + " " + intro.get(t.id, "")):
                continue                                  # 이연법인세 변동표의 「확정급여부채」 줄은 일시적차이 · 세효과다
            rel = _table_rel(labels_of.get(t.id, ""), t.caption)[0]
            if rel is None:
                continue
            pairs = _pairs([str(h) for h in t.header])
            if len(pairs) != 1:
                continue
            js, je = pairs[0]
            if _NOT_NET.search(norm(str(t.header[js]))) or _NOT_NET.search(norm(str(t.header[je]))):
                continue
            per = {js: "P.e" if rel == "C" else "PP.e", je: "C.e" if rel == "C" else ("Ph.e" if interim else "P.e")}
            items = [_item(t, i) for i in range(len(t.rows))]
            secs = _sections(t)
            for i, name in enumerate(items):
                if not name or len(name) < 2 or items.count(name) != 1 or secs[i] or _CONTRA.search(name):
                    continue
                lines = [(lt, li) for lt, li in fs.lines(name, False)]
                if len(lines) != 1:
                    continue
                lt, li = lines[0]
                if pointed.get((lt.id, li)) and p.key not in pointed[(lt.id, li)]:
                    continue                              # 과목이 다른 주석을 가리킨다(투자부동산 주석의 「토지」, 종속기업 요약의 「유형자산」)
                for j in (js, je):
                    hit = fs.cell(lt, li, per[j]) if _isnum(t.nums[i][j]) else None
                    if not hit:
                        continue
                    subs = [(lt, k, hit[2]) for k in contra.get((lt.id, li), []) if _isnum(lt.nums[k][hit[2]])]
                    what = f"{p.key} {t.id} 「{_labels(t)[i]}」 · 「{t.header[j]}」 = 재무상태표 「{_labels(lt)[li]}」"
                    if subs:
                        add_sum("변동표 과목", (t, i, j), [hit] + subs, what + " + " + " + ".join(f"「{_labels(lt)[k]}」" for _, k, _ in subs) + "(순액)")
                    else:
                        add("변동표 과목", (t, i, j), hit, what)


def _roll_props(doc: Doc, add) -> None:
    """같은 주석의 당기 변동표 기초 = 전기 변동표 기말(같은 꼴 두 표, 같은 줄 · 같은 열), 한 표 안에서 당기 열 기초 = 전기 열 기말.
    표의 기간은 표 바로 위 기간 문단이나 표 앞 글 마지막 문장 뒤로 정하고(11-09), 모르면 걸지 않는다. 기초 · 기말 칸은 이름으로 짝짓는다."""
    for p in doc.parts:
        if not p.key.startswith("주석"):
            continue
        labels_of = period_labels(p)
        tabs = [x[1] for x in p.items if x[0] == "t" and not x[1].kind]
        rel = {}
        for t in tabs:
            r, w = _table_rel(labels_of.get(t.id, ""), t.caption)
            rel[t.id] = "PP" if (r, w) == ("P", "초") else r      # 「(전기초)」 표는 전기 표가 아니다
        heads = {t.id: [norm(h) for h in t.header] for t in tabs}
        rows = {t.id: [norm(x) for x in _labels(t)] for t in tabs}
        keys = {t.id: [f"{sec}/{x}" for sec, x in zip(_sections(t), rows[t.id])] for t in tabs}   # 구역 머리까지 붙인 줄 이름

        def same_row(a, b, i):
            # 줄 이름(구역 머리 포함)이 두 표에 하나씩만 있을 때 그 줄
            ka, kb = keys[a.id], keys[b.id]
            hit = [n for n, y in enumerate(kb) if y == ka[i]]
            return hit[0] if len(hit) == 1 and ka.count(ka[i]) == 1 else None

        def overlap(a, b) -> float:
            ha, hb = set(heads[a.id][1:]), set(heads[b.id][1:])
            ra, rb = set(rows[a.id]), set(rows[b.id])
            return (len(ha & hb) + len(ra & rb)) / max(len(ha | hb) + len(ra | rb), 1)

        for a in tabs:
            if rel[a.id] != "C":
                continue
            cand = [(overlap(a, b), b) for b in tabs if b is not a and rel[b.id] == "P" and heads[b.id][:1] == heads[a.id][:1]]
            cand = sorted([c for c in cand if c[0] >= 0.5], key=lambda c: -c[0])
            if not cand or (len(cand) > 1 and cand[1][0] == cand[0][0]):
                continue                                 # 짝이 될 전기 표가 없거나 둘이면 어느 것인지 모른다
            b = cand[0][1]
            la, lb, ha, hb = rows[a.id], rows[b.id], heads[a.id], heads[b.id]
            ends_rows = [e2 for _, e2 in _row_pairs(lb)]
            for i, e in _row_pairs(la):                 # 줄이 기초 · 기말인 변동표: 열은 이름으로 짝짓는다
                k = same_row(a, b, e)
                if k is None and len(ends_rows) == 1:
                    k = ends_rows[0]                      # 「당기초금액」 = 전기 표 「전기말금액」
                if k is None:
                    continue
                for j in range(1, len(ha)):
                    jb = next((m for m in range(1, len(hb)) if hb[m] == ha[j]), None) if ha.count(ha[j]) == 1 and hb.count(ha[j]) == 1 else None
                    if jb is not None and _isnum(a.nums[i][j]) and _isnum(b.nums[k][jb]):
                        add("변동표", (a, i, j), (b, k, jb), f"{p.key} 당기 표 「{_labels(a)[i]}」 = 전기 표 「{_labels(b)[k]}」")
            ends_b = {_stem(b.header[e]): e for _, e in _pairs([str(h) for h in b.header])}
            for j, _e in _pairs([str(h) for h in a.header]):  # 열이 기초 · 기말인 변동표: 줄은 이름으로 짝짓는다
                k = ends_b.get(_stem(a.header[j]))
                if k is None and len(ends_b) == 1:
                    k = next(iter(ends_b.values()))
                if k is None:
                    continue
                for i in range(len(la)):
                    ib = same_row(a, b, i)
                    if ib is not None and _isnum(a.nums[i][j]) and _isnum(b.nums[ib][k]):
                        add("변동표", (a, i, j), (b, ib, k), f"{p.key} 당기 표 「{a.header[j]}」 = 전기 표 「{b.header[k]}」")
        cost = bool(re.search(r"매출원가|제조원가|원가명세", _plain(p.title)))
        for t in tabs:                                   # 한 표: 줄이 기초 · 기말, 열이 당기 · 전기
            if cost:
                continue                                  # 매출원가 계산의 「기말재고액」 은 빼는 줄이라 부호가 다르다
            la = [norm(x) for x in _labels(t)]
            cols = {j: _rel_last(h) for j, h in enumerate(t.header) if j}
            for i, k in _row_pairs(la):
                for jc, (rc, wc) in cols.items():
                    if rc != "C":
                        continue
                    mates = [jp for jp, (rp, wp) in cols.items() if rp == "P" and _stem(t.header[jp]) == _stem(t.header[jc])]
                    if len(mates) == 1 and _isnum(t.nums[i][jc]) and _isnum(t.nums[k][mates[0]]) and not t.rate(i, jc) and not t.rate(k, mates[0]):
                        add("변동표", (t, i, jc), (t, k, mates[0]), f"{p.key} {t.id} 당기 열 「{_labels(t)[i]}」 = 전기 열 「{_labels(t)[k]}」")


# ---- 2차(10-22): 회사별 표 · 이름 짝 · 문장 ----------------------------------------------------------------

def _sp(s) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip()


def _group_props(doc: Doc, add_sum) -> None:
    """같은 주석의 범주 합계 표 = 회사별 표. 두 표의 줄 이름과 기간 이름(표 위 문단의 「당반기」 「전기말」)이 같고, 회사별 표의 열 이름이
    합계 표의 열 이름 뒤에 회사 이름을 붙인 꼴이면(「… 모든 종속기업의 합계」 → 「… 모든 종속기업의 합계 삼성디스플레이㈜」) 합계 표 칸 = 회사별 표
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
