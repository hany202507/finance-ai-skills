"""DSD 푸팅의 연결: 합계 구조 탐지 · 이름으로 칸 찾기 · 규칙 연결 · 검증 계산(2026-10-12).

합계 구조는 이름(합계 · 소계 · 기초 · 기말)으로 후보를 세우고, 표의 절반 이상에서 금액이 맞는 구조만 채택한다.
채택한 구조에서 안 맞는 칸이 FALSE 다. 채택한 구조는 연결 정의에 남아 다음 판에서 이름으로 다시 풀리므로,
다음 판에서 합계가 안 맞으면 FALSE 가 된다. 연결 정의는 표 번호 · 행 이름 · 열 이름으로 적는다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from itertools import product

import yaml

from .base import DEFS, norm
from .dsd_grid import Doc, Table


@dataclass
class Check:
    id: str
    kind: str
    group: str
    table: str
    r: int
    c: int
    terms: list
    span: tuple | None
    label: str
    source: str
    basis: str = ""
    tol: int = 0
    excluded: bool = False
    confirmed: bool = False
    left: float | None = None
    right: float | None = None
    ok: bool | None = None
    minor: bool = False            # 안 맞지만 차이가 표시 단위로 MINOR 이하(단수 차이). 엑셀에서 노랑, FALSE 로 세지 않는다
    plain: bool = False            # 표의 단위를 쓰지 않는다. 환산 배수는 terms 의 부호 자리와 left_div 에 들어 있다(전기 대사)
    left_div: float = 1            # 왼쪽 칸을 나눌 수(당기 표가 작년 표보다 잔 단위일 때)
    when: str = ""                 # 조건부 연결의 조건. 금액이 달라도 FALSE 가 아니고 「확인」 이다
    finding: str = ""              # 이 검증의 차이를 판정한 결과(보고서 불일치 · 확인 … 과 근거). 엑셀 「볼 것」 시트에 나온다
    usual: str = ""                # 늘 나는 차이의 유형 이름(취득과 현금흐름표, 범주별 표와 본표 …). 「볼 것」 시트에서 아래쪽에 모은다
    expr: str = ""                 # 계산 검증의 식. 항 자리는 {0} {1} …(terms 차례), 더하기 · 빼기 · 곱하기 · 나누기와 괄호. 비면 terms 를 부호대로 더한다
    minor_limit: float = 0         # 단수로 볼 차이의 한도(표시 단위). 천원 · 백만원 표나 단위를 바꿔 견준 검증은 MINOR, 원 단위끼리와 계산 검증은 0
    weak: bool = False             # 걸 근거가 약한 연결(주석에 문장이 없고 줄 이름으로만 읽었다). 차이가 나면 「볼 것」 맨 아래에 둔다
    unit: float = 1                # 「이 칸 값」 · 「대사 대상 값」 의 단위(원으로 몇 배인지). 엑셀에 단위로 적는다
    dropped: str = ""              # 판정으로 뺀 검증(걸지 않음 · 엔진 판독 · 설명됨). 회계사의 확인 칸(X)과 따로 둔다. 결과는 빈칸, 「볼 것」 맨 아래
    cause: str = ""                # 판정이 적은 원인(「작년 자본변동표 주식발행초과금」). 「볼 것」 이 같은 원인끼리 묶는다
    cmp: str = ""                  # 부분 대사(11단계): le 면 왼쪽 ≤ 오른쪽, ge 면 왼쪽 ≥ 오른쪽. 비면 같아야 한다
    hints: list = field(default_factory=list)      # 차이 설명 후보(11단계, dsd_diff). 「볼 것」 과 판정자료에 나온다
    fix_cell: tuple | None = None  # 판정이 고치라고 한 칸 (표 id, 줄, 열)
    correct: float | None = None   # 그 칸의 맞는 숫자(그 칸의 표시 단위)
    fix_note: str = ""             # 고칠 쪽 근거를 엔진이 계산한 결과(「근거 확인: …」 · 「고칠 쪽 미정: …」)
    verified: str = ""             # 독립 검증 결과(유지 · 바꿈). 비면 검증 전
    verify_why: str = ""           # 독립 검증의 근거
    zero_left: bool = False        # 왼쪽 칸이 보고서에 없어 0 으로 견준다(12단계: 처분계산서에 이익준비금 적립 줄이 없음). 칸 주소는 그 줄이 들어갈 곳


MINOR = 3     # 단수 차이로 보는 한도(표시 단위). 천원 단위 주석끼리 1~3 다른 연결이 공시 보고서 세 건에서 35건 나왔다


def failed(c: Check) -> bool:
    """FALSE 로 세는 검증. 단수 차이와 조건부 연결의 차이, 근거가 약한 연결의 차이는 뺀다."""
    return c.ok is False and not c.minor and not c.when and not c.weak and not c.dropped


def covered(checks: list[Check]) -> set:
    """어느 검증에든 들어간 칸 {(표 id, 줄, 열)}. 검증의 왼쪽 칸과 더해지는 칸이다. 뺀 검증(X)은 세지 않는다."""
    out = set()
    for c in checks:
        if c.excluded or c.dropped:
            continue
        out.add((c.table, c.r, c.c))
        if c.span:
            tid, r0, c0, r1, c1 = c.span
            out |= {(tid, r, k) for r in range(r0, r1 + 1) for k in range(c0, c1 + 1)}
        for tid, r, k, _ in c.terms:
            out.add((tid, r, k))
    return out


def asks(c: Check) -> bool:
    """「확인」 으로 세는 검증. 조건부 연결이나 근거가 약한 연결인데 금액이 다르다(단수 차이는 뺀다)."""
    return c.ok is False and not c.minor and (bool(c.when) or c.weak) and not c.dropped


def sampled(c: Check) -> bool:
    """독립 검증을 하지 않고 회계사가 표본으로 보는 「늘 나는 차이」(2026-10-22 결정). 늘 나는 차이 유형(usual)이 붙은 검증이
    판정까지 「확인」 으로 끝난 것만이다. 숫자 오류 · 표시 오류 · 설명 부족 · 작년 보고서 불일치로 판정되면 apply_finding 이 usual 을 지우고,
    판정이 없거나 근거가 약한 연결이면 여기 들지 않는다. 한 상장사 2026 반기 별도에서 이런 확인 9건의 독립 검증에 10분이 들었고 결론이 모두 같았다."""
    return asks(c) and bool(c.usual) and not c.weak and c.finding.startswith("확인")


def engine_checked(c: Check) -> bool:
    """독립 검증을 하지 않는 숫자 오류(2026-10-22 결정). 판정이 숫자 오류이고 엔진이 「근거 확인」 을 낸 것이다. 근거 칸(검증한 두 칸이 아닌
    작년 보고서 · 다른 주석 · 정산표 칸)으로 계산한 금액이 판정의 맞는 숫자와 같다는 것을 엔진이 이미 확인했다. 부호만 바꾸는 고침은 작년 보고서의
    같은 줄만 근거로 받는다(「근거 확인(부호)」). 「고칠 쪽 미정」 은 계속 독립 검증한다. 가온정밀 모의 dsd 의 FALSE 1건이 이 경우였다."""
    return failed(c) and c.finding.startswith(("숫자 오류", "보고서 불일치")) and c.fix_note.startswith("근거 확인")


def no_review(c: Check) -> bool:
    """독립 검증 에이전트에게 보내지 않는 판정: 늘 나는 차이(sampled)와 엔진이 근거를 확인한 숫자 오류(engine_checked)."""
    return sampled(c) or engine_checked(c)


@lru_cache(maxsize=1)
def rules() -> dict:
    return yaml.safe_load((DEFS / "dsd_link_rules.yaml").read_text(encoding="utf-8"))


def _isnum(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


_FOOT = re.compile(r"\((?:\*|주)\s*\d*\)|\*\d*")


def total_kind(label: str) -> str | None:
    raw = _FOOT.sub("", str(label)).strip()       # 「계(*2)」 「합계(주1)」 의 각주 표시를 뗀다
    t = norm(raw)
    if re.search(r"(^|\s)계$", raw) and not t.endswith(("누계", "소계")):      # 「자산 계」 「차감 계」
        return "합계"
    if t.endswith("소계"):
        return "소계"
    if t == "계" or t.endswith("합계") or t.endswith("총계"):
        return "합계"
    return None


def _ref(names: list[str], i: int) -> list:
    return [names[i], sum(1 for x in names[:i + 1] if norm(x) == norm(names[i]))]


def _find(names: list[str], name: str, nth: int = 1) -> int | None:
    hits = [i for i, x in enumerate(names) if norm(x) == norm(name)]
    return hits[nth - 1] if len(hits) >= nth else None


def _labels(t: Table) -> list[str]:
    """줄 이름. 글자 열이 둘인 표는 두 칸을 이은 이름이다(「기초 취득원가」)."""
    return t.labels or [r[0] for r in t.rows]


_TERM = re.compile(r"제\s*(\d+)\s*\(?\s*[당전]?\s*\)?\s*기")      # 「제 3 기 반기말」 「제 2 (당) 기」 의 기수


def term_of(header: str) -> int | None:
    m = _TERM.search(str(header))
    return int(m.group(1)) if m else None


def span_of(header: str) -> str:
    """열의 기간 종류. 반기 · 분기 · 연."""
    h = norm(header)
    return "반기" if "반기" in h else ("분기" if "분기" in h else "연")


def period_col(t: Table, period: str) -> int | None:
    """재무제표 표의 당기 · 전기 열. 머리줄에 「당」 · 「전」 이 든 첫 열. 없으면 기수(「제 3 기」)가 큰 쪽이 당기다.
    반기 · 분기 손익계산서처럼 한 기에 열이 둘(3개월 · 누적)이면 누적 열이다. 기수도 없으면 숫자 열의 첫째 · 둘째."""
    key = "당" if period == "당기" else "전"
    hits = [j for j, h in enumerate(t.header) if j and key in h]
    if hits and len(hits) < len(t.header) - 1:   # 모든 열에 같은 표시가 있으면 기수로 정한다(「제43(전)기」 「제42(전)기」 머리줄 오타, DART 00242509 2025)
        return hits[0]
    terms = {j: term_of(h) for j, h in enumerate(t.header) if j and term_of(h) is not None}
    kinds = sorted(set(terms.values()), reverse=True)
    if len(kinds) >= 2:
        want = kinds[0] if period == "당기" else kinds[1]
        cols = [j for j, k in terms.items() if k == want]
        return next((j for j in cols if "누적" in t.header[j]), cols[0])
    numeric = [j for j in range(1, len(t.header)) if any(_isnum(r[j]) for r in t.nums)]
    k = 0 if period == "당기" else 1
    return numeric[k] if len(numeric) > k else None


def find_row(t: Table, label: str, nth: int = 1) -> int | None:
    if label == "@last":
        return next((i for i in range(len(t.rows) - 1, -1, -1) if any(_isnum(v) for v in t.nums[i])), None)
    i = _find(_labels(t), label, nth)
    if i is None and t.old_labels:               # 줄 이름을 여러 칸으로 읽기 전에 적은 것(첫 칸 이름, 빈 이름과 순번)도 받는다
        i = _find(t.old_labels, label, nth)
    return i


def find_col(t: Table, name: str, nth: int = 1) -> int | None:
    if name == "@last":
        return len(t.header) - 1 if len(t.header) > 1 else None
    if name in ("당기", "전기"):
        return period_col(t, name)
    j = _find(t.header, name, nth)
    pre = col_prefix(t.header) if j is None else ""
    return _find([cut_prefix(h, pre) for h in t.header], name, nth) if pre else j


def col_prefix(header: list[str]) -> str:
    """숫자 열 이름이 모두 함께 쓰는 앞부분(낱말 단위, 띄어 쓴 8자 이상). XBRL 표는 열마다 「특수관계자의 범주 모든 특수관계자의 합계 …」 처럼
    같은 앞부분을 되풀이한다. 읽기 자료는 이 앞부분을 한 번만 적고(2026-10-22 실행 시간 P6), 연결에 뗀 이름을 적어도 find_col 이 같은 열로 푼다.
    열이 셋 미만이거나 앞부분이 짧으면 ""."""
    names = [h for h in header[1:] if str(h).strip()]          # 이름 없는 열은 줄 이름 열이다
    if len(names) < 3:
        return ""
    words = [str(h).split() for h in names]
    k = 0
    while all(len(w) > k + 1 and w[k] == words[0][k] for w in words):      # 열마다 낱말을 하나 이상 남긴다
        k += 1
    pre = " ".join(words[0][:k])
    return pre if len(norm(pre)) >= 8 else ""


def cut_prefix(name: str, pre: str) -> str:
    """열 이름에서 공통 앞부분(col_prefix)을 뗀 이름."""
    s = str(name)
    return s[len(pre):].strip() if pre and s.startswith(pre) else s


def _vsum(t: Table, rows: list[int], c: int) -> float:
    return round(sum(t.nums[i][c] for i in rows if _isnum(t.nums[i][c])), 6)


def _hsum(t: Table, r: int, cols: list[int]) -> float:
    return round(sum(t.nums[r][j] for j in cols if _isnum(t.nums[r][j])), 6)


DECREASE = ("감소", "처분", "환입", "사용", "지급", "상환", "회수", "제거", "제각", "폐기", "매각", "상실", "소멸")


def is_rate(name: str) -> bool:
    """더해도 뜻이 없는 열 · 행(지분율, 이자율, %)."""
    t = norm(name)
    if re.search(r"환율(변동|차이|효과|의변동|로인한)", t):      # 「환율변동효과」 는 변동표의 금액 줄이다
        return False
    return "%" in t or "율" in t


def _pick(cell, others: list[int], i: int, cands: list, exact=(), tol=lambda n: 0):
    """합계 항목 i 의 구조 후보 가운데 금액 근거가 있는 것을 고른다. 후보는 (꼴, 항목 번호들, 부호들 또는 None).

    근거가 되는 직교 칸은 합계 칸이 숫자이고 항 가운데 숫자가 둘 이상이며 전부 0 은 아닌 칸이다.
    이름으로 세운 후보(cands)는 근거 칸에서 안 맞는 칸이 max(1, 근거 칸 수 // 4) 이하일 때,
    금액에서 찾은 후보(exact)는 근거 칸이 둘 이상이고 전부 맞을 때 채택한다. 항목이 하나뿐인 후보는 버린다."""

    def value(c, o):
        signs = c[2] or [1] * len(c[1])
        return round(sum(s * cell(j, o) for j, s in zip(c[1], signs) if _isnum(cell(j, o))), 6)

    def live(c):
        return [o for o in others if _isnum(cell(i, o)) and sum(1 for j in c[1] if _isnum(cell(j, o))) >= 2
                and (cell(i, o) != 0 or any(_isnum(cell(j, o)) and cell(j, o) != 0 for j in c[1]))]

    def hits(c):
        return sum(1 for o in live(c) if abs(value(c, o) - cell(i, o)) <= tol(len(c[1])) + 1e-9)      # 단수 허용 폭은 검증과 같다

    cands = [c for c in cands if len(c[1]) >= 2]
    best = max(cands, key=hits, default=None)
    n = len(live(best)) if best else 0
    if best and n and hits(best) == n:
        return best
    found = next((c for c in exact if len(c[1]) >= 2 and len(live(c)) >= 2 and hits(c) == len(live(c))), None)
    if found:                                   # 이름 후보가 일부만 맞는데 부호를 바꾼 구조가 전부 맞으면 그쪽이 구조다
        return found
    if best and hits(best) and n - hits(best) <= max(1, n // 4):
        return best
    return None


def _struct(names: list[str], i: int, best) -> dict:
    mode, items, signs = best
    s = {"total": _ref(names, i), "mode": mode}
    s.update({"rows": [_ref(names, j) for j in items]} if mode == "rows" else {"from": _ref(names, items[0]), "to": _ref(names, items[-1])})
    if signs:
        s["signs"] = signs
    return s


def _signed(items: list[int]) -> list:
    """부호를 금액에서 찾을 후보들. 빼는 항이 적은 것부터. 전부 빼는 것도 있다(유출액 합계를 음수로 적은 현금흐름표)."""
    if not 2 <= len(items) <= 9:
        return []
    combos = sorted(product((1, -1), repeat=len(items)), key=lambda t: (t.count(-1), t))
    return [("rows", items, list(t)) for t in combos if -1 in t]


def _axis(names: list[str], cell, others: list[int], first: int = 0, tol=lambda n: 0) -> list[dict]:
    """한 축(행 이름 또는 열 이름)에서 합계 구조를 찾는다. cell(i, o) 는 i 번째 항목의 o 번째 직교 칸 숫자다.

    합계 · 소계 이름이 붙은 항목마다 가능한 구조(소계들의 합, 소계와 그 뒤 항목의 합, 소계를 뺀 항목의 합, 바로 앞 합계 뒤부터의 합)를
    세운다. 변동표(기초 … 기말)는 그대로 더한 구조, 감소 · 처분 같은 이름의 항목을 뺀 구조, 부호를 금액에서 찾은 구조를 세운다.
    채택 기준은 _pick 에 있다.
    공개 원문 209건에서 이름만으로 걸었더니 검증 31,180건 중 3,605건이 FALSE 였고 거의 전부 구조를 잘못 잡은 것이었다(2026-10-12)."""
    kinds = [total_kind(x) if i >= first else None for i, x in enumerate(names)]
    out = []

    def add(i, cands, exact=()):
        best = _pick(cell, others, i, cands, exact, tol)
        if best:
            out.append(_struct(names, i, best))

    for i, k in enumerate(kinds):
        if not k:
            continue
        prev_any = max((j for j in range(first, i) if kinds[j]), default=first - 1)
        prev_top = max((j for j in range(first, i) if kinds[j] == "합계"), default=first - 1)
        cands = []
        if k == "합계":
            seg = list(range(prev_top + 1, i))
            subs = [j for j in seg if kinds[j] == "소계"]
            if subs:
                cands.append(("rows", subs, None))
                tail = [j for j in seg if j > subs[-1]]
                if tail:
                    cands.append(("rows", subs + tail, None))
                leaves = [j for j in seg if not kinds[j]]
                if leaves:
                    cands.append(("rows", leaves, None))
        block = list(range(prev_any + 1, i))
        if block:
            cands.append(("range", block, None))
        add(i, cands)
    low = [norm(x) for x in names]
    a = None
    for i, x in enumerate(low):
        if i < first:
            continue
        if x.startswith("기초"):
            a = i
        elif x.startswith("기말") and a is not None and i > a + 1 and not kinds[i]:
            items = list(range(a, i))
            named = [-1 if j > a and any(w in low[j] for w in DECREASE) else 1 for j in items]
            cands = [("range", items, None)]
            if -1 in named:
                cands.append(("rows", items, named))
            add(i, cands, _signed(items))
            a = None
    return out


CHAIN = ("손익계산서", "현금흐름표", "이익잉여금처분계산서")


def detect_fs(t: Table) -> list[dict]:
    """재무제표 본표의 세로 구조. 과목 단계(t.levels)로 후보를 세우고 금액 근거로 채택한다(_pick).

    1) 위 과목 = 바로 아래 단계 과목의 합. 안 맞으면 부호를 금액에서 찾는다(매출원가 = 기초 + 매입 - 기말).
    2) 가장 윗단계의 총계 = 앞 총계 뒤부터의 윗단계 과목 합(자산총계 = 유동자산 + 비유동자산).
    3) 손익계산서 · 현금흐름표의 차례 계산: 윗단계 과목이 앞 계산 결과부터 그 앞 줄까지의 더하기 빼기와
       당기 · 전기 둘 다 맞으면 건다(매출총이익 = 매출액 - 매출원가, 영업이익 = 매출총이익 - 판매비와관리비)."""
    labels, lv, n = _labels(t), t.levels, len(t.rows)
    cols = [c for c in range(1, len(t.header)) if any(_isnum(r[c]) for r in t.nums)]

    def cell(i, c):
        return t.nums[i][c]

    def has(i):
        return lv[i] is not None and any(_isnum(t.nums[i][c]) for c in cols)

    def tol(k):
        return _tol(t, k)

    out, done = [], set()
    for p in range(n):
        if not has(p):
            continue
        under = []
        for j in range(p + 1, n):
            if lv[j] is not None and lv[j] <= lv[p]:
                break
            if has(j):
                under.append(j)
        if not under:
            continue
        m = min(lv[j] for j in under)
        items = [j for j in under if lv[j] == m]
        best = _pick(cell, cols, p, [("rows", items, None)], _signed(items), tol)
        if best:
            out.append(_struct(labels, p, best))
            done.add(p)
    tops = [x for x in lv if x is not None]
    if not tops:
        return out
    top = [i for i in range(n) if has(i) and lv[i] == min(tops)]
    chain = any(t.id.startswith(x) for x in CHAIN)
    last = 0
    for k, i in enumerate(top):
        if i in done:
            continue
        cands = []
        if total_kind(labels[i]):
            prev = max((q for q in range(k) if total_kind(labels[top[q]])), default=-1)
            cands.append(("rows", top[prev + 1:k], None))
        items = top[last:k][-9:] if chain else []
        best = _pick(cell, cols, i, cands, ([("rows", items, None)] + _signed(items)) if len(items) >= 2 else (), tol)
        if best:
            out.append(_struct(labels, i, best))
            last = k
    return out


def _masked(t: Table) -> Table:
    """% 가 붙은 칸을 숫자가 아닌 칸으로 둔 표(엔진의 합계 구조 찾기용). 비율은 더하지 않는다."""
    if not any(t.rate(i, j) for (i, j) in (t.cell_units or {})):
        return t
    import copy

    q = copy.copy(t)
    q.nums = [[None if t.rate(i, j) else v for j, v in enumerate(r)] for i, r in enumerate(t.nums)]
    return q


def detect(t: Table) -> dict:
    """표 안 합계 구조. 재무제표 본표는 과목 단계로(detect_fs), 그 밖의 표는 합계 이름으로(_axis) 세로 구조를 찾는다.
    과목 단계를 모르는 재무제표 본표의 세로 구조는 걸지 않는다. 비율 열 · 행과 % 가 붙은 칸은 더하지 않는다.
    문장 속 금액을 모은 표(kind 「문장」)는 합계 구조가 없다."""
    if t.kind:
        return {"vsum": [], "hsum": []}
    t = _masked(t)
    rows = [r for r in range(len(t.rows)) if not is_rate(_labels(t)[r])]
    cols = [c for c in range(1, len(t.header)) if not is_rate(t.header[c])]
    if t.levels:
        v = detect_fs(t)
    else:
        v = [] if t.finance else _axis(_labels(t), lambda i, c: t.nums[i][c], cols, tol=lambda n: _tol(t, n))
    first = 2 if len(t.header) > 2 and norm(t.header[1]).startswith("주석") else 1      # 본표의 주석 번호 열은 더하는 열이 아니다
    h = _axis(t.header, lambda j, r: t.nums[r][j] if j else None, rows, first=first, tol=lambda n: _tol(t, n))
    return {"vsum": v, "hsum": h}


def _sig(t: Table) -> list[str]:
    return [norm(h) for h in t.header]


def _tol(t: Table, n: int) -> int:
    """천원 · 백만원 단위 표의 합계는 반올림한 항을 더한 것이라 단수 차이가 난다. 항 수의 절반(적어도 1)까지 허용한다."""
    return max(1, n // 2) if t.unit > 1 else 0


def _checks_from_structure(t: Table, s: dict, unresolved: list) -> list[Check]:
    out, labels = [], _labels(t)
    used: dict[str, int] = {}

    def uid(cid):                                # 한 합계 칸을 두 식으로 검증하면(기말 = 기초 + 변동, 기말 = 자산 + 부채) 둘째부터 번호를 붙인다
        used[cid] = used.get(cid, 0) + 1
        return cid if used[cid] == 1 else f"{cid}~{used[cid]}"

    def need(x):                                 # 엔진이 찾은 구조는 항에 숫자가 둘 이상인 칸에만 건다. 하나뿐인 칸까지 걸었더니 공개 원문 209건에서
        return 1 if x.get("source") == "AI" else 2      # FALSE 가 100건 가까이 늘었다(10-13). AI 가 표를 읽고 정한 구조는 하나여도 건다

    pre = col_prefix(t.header)

    def named(names, name, axis):                # 재무제표 본표의 열은 「당기」 「전기」 로 적어도 된다
        got = {norm(o) for o in names}
        if axis == "v":
            got |= {norm(t.header[c]) for o in names if o in ("당기", "전기") and (c := period_col(t, o)) is not None}
            return norm(name) in got or norm(cut_prefix(name, pre)) in got      # 열 이름의 공통 앞부분을 떼고 적은 것(읽기 자료의 꼴)
        return norm(name) in got

    def wanted(x, name, axis):                   # only 가 있으면 거기 적힌 열(줄)에만 건다. 없으면 비율 이름과 skip 을 뺀다
        if x.get("only"):
            return named(x["only"], name, axis)
        return not is_rate(name) and not named(x.get("skip", []), name, axis)

    def miss(what, ref):
        unresolved.append({"table": t.id, "kind": what, "why": f"{what}: 「{ref[0]}」 을 찾지 못함"})

    def items_of(x, find, what):
        """구조 한 줄을 (항목 번호들, 부호들, 이어진 범위인지) 로 푼다. 이름을 못 찾으면 None."""
        if x["mode"] == "rows":
            got = [find(t, *r) for r in x["rows"]]
            bad = next((r for r, g in zip(x["rows"], got) if g is None), None)
        else:
            a, b = find(t, *x["from"]), find(t, *x["to"])
            bad = x["from"] if a is None else (x["to"] if b is None else None)
            got = list(range(a, b + 1)) if bad is None else []
        if bad is not None:
            miss(what, bad)
            return None
        signs = x.get("signs") or [x.get("sign", 1)] * len(got)      # 범위 구조의 sign: 전부 빼는 합(유출액 소계가 음수고 항목이 양수)
        return got, signs, x["mode"] == "range" and x.get("sign", 1) == 1

    def text(names, got, signs, whole):
        if whole:
            return f"{names[got[0]]}~{names[got[-1]]} 합"
        return " ".join(("+ " if g > 0 else "- ") + names[k] for k, g in zip(got, signs)).lstrip("+ ")

    for v in s.get("vsum", []):
        i = find_row(t, *v["total"])
        if i is None:
            miss("세로합", v["total"])
            continue
        r = items_of(v, find_row, "세로합")
        if r is None:
            continue
        rows, signs, whole = r
        src = v.get("source", "규칙")
        for c in range(1, len(t.header)):
            if not _isnum(t.nums[i][c]) or not wanted(v, t.header[c], "v") or sum(1 for k in rows if _isnum(t.nums[k][c])) < need(v):
                continue
            if src != "AI" and (t.rate(i, c) or any(t.rate(k, c) for k in rows)):      # 엔진 구조는 % 칸에 걸지 않는다
                continue
            out.append(Check(uid(f"세로합|{t.id}|{v['total'][0]}#{v['total'][1]}|{t.header[c]}#{_ref(t.header, c)[1]}"), "세로합", "합계", t.id, i, c,
                             [(t.id, k, c, g) for k, g in zip(rows, signs)], (t.id, rows[0], c, rows[-1], c) if whole else None,
                             text(labels, rows, signs, whole), src, v.get("basis", ""), tol=_tol(t, len(rows))))
    for h in s.get("hsum", []):
        j = find_col(t, *h["total"])
        if j is None:
            miss("가로합", h["total"])
            continue
        r = items_of(h, find_col, "가로합")
        if r is None:
            continue
        cols, signs, whole = r
        src = h.get("source", "규칙")
        for i in range(len(t.rows)):
            if not _isnum(t.nums[i][j]) or not wanted(h, labels[i], "h") or sum(1 for c in cols if _isnum(t.nums[i][c])) < need(h):
                continue
            if src != "AI" and (t.rate(i, j) or any(t.rate(i, c) for c in cols)):
                continue
            out.append(Check(uid(f"가로합|{t.id}|{labels[i]}#{_ref(labels, i)[1]}|{h['total'][0]}#{h['total'][1]}"), "가로합", "합계", t.id, i, j,
                             [(t.id, i, c, g) for c, g in zip(cols, signs)], (t.id, i, cols[0], i, cols[-1]) if whole else None,
                             text(t.header, cols, signs, whole), src, h.get("basis", ""), tol=_tol(t, len(cols))))
    return out


def overlay(t: Table, s: dict | None, over: list[dict]) -> dict:
    """엔진이 금액 근거로 찾은 구조에 AI 가 표를 읽고 정한 합계를 얹는다.
    같은 합계 줄 · 열은 AI 가 정한 것으로 바꾸고, AI 가 합계가 아니라고 한 것(off)은 뺀다."""
    out = {"vsum": list((s or {}).get("vsum", [])), "hsum": list((s or {}).get("hsum", []))}
    for x in over:
        key, find = ("vsum", find_row) if x["axis"] == "v" else ("hsum", find_col)
        i = find(t, *x["total"])
        mine = lambda y: y.get("source") == "AI" or i is None or find(t, *y["total"]) != i      # noqa: E731  엔진 것만 뺀다. 한 합계 줄에 AI 구조가 둘일 수 있다
        if x.get("keep") and not x.get("off"):     # 엔진 구조를 두고 식을 하나 더한다(기말 = 기초 + 변동 에 더해 기말 = 자산 + 부채)
            pass
        elif x.get("only"):                        # 일부 열(줄)만 정한 AI 구조(합계가 아니라고 한 것도)는 엔진 구조를 그 열(줄)에서만 대신한다
            out[key] = [y if mine(y) else dict(y, skip=list(y.get("skip", [])) + list(x["only"])) for y in out[key]]
        else:
            out[key] = [y for y in out[key] if mine(y)]
        if not x.get("off"):
            out[key].append(x)
    return out


def struct_text(t: Table, x: dict, axis: str) -> str:
    """합계 구조 한 줄을 읽을 수 있는 글로. 「유동자산」 = 당좌자산 + 재고자산"""
    what = "줄" if axis == "vsum" else "열"
    name = lambda r: r[0] if str(r[0]).strip() else f"(이름 없는 {what} {r[1]}번째)"      # noqa: E731
    if x["mode"] == "range":
        body = ("- " if x.get("sign", 1) < 0 else "") + f"{name(x['from'])}~{name(x['to'])} 합"
    else:
        signs = x.get("signs") or [1] * len(x["rows"])
        body = " ".join(("+ " if g > 0 else "- ") + name(r) for r, g in zip(x["rows"], signs)).lstrip("+ ")
    more = f" ({', '.join(x['only'])} 에만)" if x.get("only") else ""
    return f"「{name(x['total'])}」 = {body}{more}"


def _resolve(doc: Doc, ref: dict, period: str | None, other: Doc | None = None):
    """연결 정의의 칸 하나를 (표, 줄, 열) 로 푼다. 표 이름이 「짝:」 으로 시작하면 함께 낸 다른 보고서(other)의 표다.
    그 표는 id 에 「짝:」 을 붙인 얕은 복사본으로 돌려준다(검증의 terms 와 엑셀 주소가 당기 보고서의 같은 이름 표와 갈린다)."""
    tid = str(ref["table"])
    if tid.startswith(PAIR_ID):
        q = other.table(tid[len(PAIR_ID):]) if other is not None else None
        if q is None:
            return None
        import copy

        t = copy.copy(q)
        t.id = PAIR_ID + q.id
    else:
        t = doc.table(tid)
    if t is None:
        return None
    names = ref["row"] if isinstance(ref["row"], list) else [ref["row"]]
    if ref.get("row_nth") == "@period":          # 한 표에 두 기간을 위아래로 둔 표(자본변동표): 이름이 맞는 줄의 마지막이 당기, 그 앞이 전기다
        hits = sorted({i for n in names for i, x in enumerate(_labels(t)) if norm(x) == norm(n)})
        r = hits[-1 if period == "당기" else -2] if len(hits) == 2 and period in ("당기", "전기") else None
    else:
        r = next((x for x in (find_row(t, n, ref.get("row_nth", 1)) for n in names) if x is not None), None)
    if ref.get("exact"):                         # 금액 근거로 건 연결은 열 이름을 글자 그대로 찾는다
        c = _find(t.header, ref["col"], ref.get("col_nth", 1))
        pre = col_prefix(t.header) if c is None else ""
        if pre:                                  # 공통 앞부분을 뗀 열 이름(읽기 자료의 꼴, 2026-10-22 P6)
            c = _find([cut_prefix(h, pre) for h in t.header], ref["col"], ref.get("col_nth", 1))
    else:
        c = find_col(t, ref.get("col") or period or "당기", ref.get("col_nth", 1))
    if r is None or c is None or not (0 <= c < len(t.header)):
        return None
    return t, r, c


def _kind(doc: Doc, left: str, rights: list[str]) -> str:
    if any(str(x).startswith(PAIR_ID) for x in [left] + list(rights)):
        return "보고서 간"                         # 함께 낸 다른 보고서(연결 ↔ 별도)와 견주는 연결
    fs = lambda tid: not doc.part_of(tid).key.startswith("주석")      # noqa: E731
    if fs(left) and all(fs(x) for x in rights):
        return "재무제표 간"
    return "주석 간" if not fs(left) and not any(fs(x) for x in rights) else "주석-재무제표"


WEAK_WHEN = "주석에 문장 없이 줄 이름과 표의 구성으로만 건 연결이다"


def calc_tol(t: Table, r: int, c: int) -> float:
    """계산 검증의 허용 폭: 왼쪽 칸에 적힌 마지막 자리 하나(「4,950」 은 1, 「22.26%」 는 0.01).
    반올림과 절사를 모두 받는다. 주당이익은 원 미만을 버리는 회사가 많다(부천공업 2025: 1,451,211,687 ÷ 27,505 = 52,762.65 를 52,762 로 적음)."""
    text = str(t.rows[r][c] or "").replace(",", "")
    m = re.search(r"\.(\d+)", text)
    return 10 ** -(len(m.group(1)) if m else 0)


_LOSS_MARK = re.compile(r"\((?:\*|주)\s*\d*\)|\[[^\]]*\]|\s")


def income_sign(label: str, v) -> int:
    """이익 방향으로 읽는 배수. 「당기순손실」 처럼 손실만 적는 줄의 양수는 손실 금액이라 -1 이다.
    「당기순이익(손실)」 · 「당기순이익」 줄과 음수로 적은 손실 줄은 적힌 부호 그대로다(DART 정정공시 짝 · 실제 회사 자료의 보고서 13건, 검증 26건이 손익계산서에 손실을 양수로 적었다)."""
    return -1 if _isnum(v) and v > 0 and _LOSS_MARK.sub("", str(label)).endswith("순손실") else 1


def _link_checks(doc: Doc, link: dict, source: str, strict: bool, unresolved: list, other: Doc | None = None) -> list[Check]:
    out = []
    for period in (link.get("periods") or [None]):
        left = _resolve(doc, link["left"], period, other)
        rights = [_resolve(doc, x, period, other) for x in link["right"]]
        if left is None or any(x is None for x in rights):
            if strict:
                unresolved.append({"table": link["left"]["table"], "kind": "연결", "why": f"연결 {link['id']}: 이름으로 칸을 찾지 못함"})
            continue
        t, r, c = left
        if not _isnum(t.nums[r][c]) or not all(_isnum(x[0].nums[x[1]][x[2]]) for x in rights):
            continue
        expr = str(link.get("expr") or "")
        terms = [(x[0].id, x[1], x[2], 1 if expr else ref.get("sign", 1)) for x, ref in zip(rights, link["right"])]
        if link.get("loss_sign") and not expr:       # 양쪽을 이익 방향으로 맞춰 견준다(손실만 적는 줄의 양수는 손실 금액)
            ls = income_sign(_labels(t)[r], t.nums[r][c])
            terms = [(tid, i, j, g * ls * income_sign(_labels(x[0])[i], x[0].nums[i][j])) for (tid, i, j, g), x in zip(terms, rights)]
        names = [f"{x[0].id} {_labels(x[0])[x[1]]}" for x in rights]
        if len(set(names)) < len(names):                 # 같은 줄의 여러 열을 더하면 이름이 되풀이된다
            names = [f"{n} · {x[0].header[x[2]]}".rstrip(" ·") for n, x in zip(names, rights)]
        if expr:
            label = expr.format(*[f"[{n}]" for n in names])
        else:
            label = "".join((" - " if x[3] < 0 else " + ") + n for n, x in zip(names, terms)).removeprefix(" + ").strip()
        weak = link.get("grade") == "약함"
        when = str(link.get("when") or "") or (WEAK_WHEN if weak else "")
        kind = "계산" if expr else (link.get("kind") or _kind(doc, t.id, [x[0] for x in terms]))
        if expr:                                     # 계산 검증의 기본 허용 폭: 왼쪽 칸의 마지막 자리와, 항마다 적힌 단위의 반올림 폭(절반)의 합 가운데 큰 쪽
            lu = t.unit_at(r, c)                     # (백만원으로 적힌 문장 금액 여럿을 더해 천원 칸과 견줄 때, 10단계 04_연결)
            spread = sum(0.5 * x[0].unit_at(x[1], x[2]) for x in rights if x[0].unit_at(x[1], x[2]) > lu) / lu
            tol = link.get("tol", max(calc_tol(t, r, c), spread))
        else:
            tol = link.get("tol", 0)
        cmp = str(link.get("cmp") or "") if not expr else ""
        if cmp:
            label = ("≤ " if cmp == "le" else "≥ ") + label
        out.append(Check(link["id"] + (f"|{period}" if period else ""), kind, "레퍼",
                         t.id, r, c, terms, None, label, source, link.get("basis", ""), tol=tol, when=when,
                         usual=str(link.get("usual") or ""), expr=expr, weak=weak, cmp=cmp))
    return out


def _pair(c: Check):
    """두 칸이 같다는 연결의 두 칸. 그런 연결이 아니면 None."""
    if c.group != "레퍼" or c.expr or c.cmp or len(c.terms) != 1 or abs(c.terms[0][3]) != 1:      # 손실 줄 부호를 맞춘 규칙(-1)도 같은 두 칸이다
        return None
    return frozenset([(c.table, c.r, c.c), tuple(c.terms[0][:3])])


def _drop_same(checks: list[Check]) -> list[Check]:
    """두 칸이 같다는 연결이 규칙과 AI 양쪽에 있으면 규칙 쪽만 남긴다(왼쪽과 오른쪽이 바뀐 것도 같은 연결이다)."""
    pair = _pair
    ruled = {pair(c) for c in checks if c.source != "AI"} - {None}
    sums = {(c.table, c.r, c.c, frozenset(c.terms)) for c in checks if c.group == "합계"}      # 같은 표 안 연결이 합계 구조와 같으면 합계 쪽만 남긴다
    out = [c for c in checks if not (c.source == "AI" and c.group == "레퍼" and not c.expr and (pair(c) in ruled or (c.table, c.r, c.c, frozenset(c.terms)) in sums))]
    # 규칙 연결이 합계 구조와 같은 식이면(부채와자본총계 = 부채총계 + 자본총계) 합계 쪽만 남긴다. 9단계 재평가: 같은 검증이 합계와 레퍼로 두 번 걸렸다
    flat = {(c.table, c.r, c.c, frozenset(c.terms)) for c in out if c.group == "합계"}
    return [c for c in out if not (c.group == "레퍼" and not c.expr and (c.table, c.r, c.c, frozenset(c.terms)) in flat)]


LAST_YEAR = "작년 보고서의 숫자가 틀렸다(올해 숫자는 맞다)"
DISPLAY = "판정: 표시 오류(금액은 맞고 이름 · 기간 · 분류 표시가 틀림)"
EXPLAIN = "판정: 설명 부족(금액은 맞고 문장이 금액을 다 설명하지 못함)"
OLD_VERDICT = {"보고서 불일치": "숫자 오류"}      # 11단계 앞의 이름. 옛 판정 파일은 숫자 오류로 읽는다


def verdict_name(v: str) -> str:
    return OLD_VERDICT.get(v, v)


def apply_finding(c: Check, note: dict) -> None:
    """판정을 검증에 붙이고 엑셀 상태에 반영한다(10단계 재평가: 판정과 상태가 따로 놀았다).
    숫자 오류(옛 이름 보고서 불일치): 조건부 · 근거 약한 연결이어도 조건을 떼어 FALSE. 표시 오류 · 설명 부족(11단계): 금액은 맞으니
    FALSE 로 세지 않고 따로 모은다. 확인: FALSE 를 「확인」 으로. 작년 보고서 불일치: 올해는 맞고 작년 보고서가 틀렸다. 고칠 것이 없으니
    「확인」 으로 두고 늘 나는 차이에서 뺀다. 걸지 않음 · 엔진 판독 · 설명됨: 판정으로 뺀다(회계사 확인 칸은 비워 둔다)."""
    v = verdict_name(note["verdict"])
    c.finding = f"{v}: {note['why']}"
    c.cause = str(note.get("cause") or c.cause or "")
    if v == "숫자 오류":
        c.when, c.usual, c.weak = "", "", False
    elif v == "표시 오류":
        c.when, c.usual, c.weak = DISPLAY, "", False
    elif v == "설명 부족":
        c.when, c.usual, c.weak = EXPLAIN, "", False
    elif v == "확인" and not c.when and not c.weak:
        c.when = "판정: 확인할 차이"
    if v == "확인" and "usual" in note:              # 판정이 늘 나는 차이 유형을 붙이거나 뗀다(빈 값이면 뗀다. 2026-10-22)
        c.usual = str(note["usual"] or "")
    elif v == "작년 보고서 불일치":
        c.when, c.usual, c.weak = c.when or LAST_YEAR, "", False
    elif v in ("걸지 않음", "엔진 판독", "설명됨"):
        c.dropped = v


def kind_of(c: Check) -> str:
    """「볼 것」 · 표지에서 세는 판정 종류. 숫자 오류 · 표시 오류 · 설명 부족 · 작년 보고서의 오류 · 확인 · 단수 · 맞음 · 뺌."""
    if c.dropped or c.excluded:
        return "뺌"
    if c.ok is not False:
        return "맞음"
    if c.minor:
        return "단수"
    if failed(c):
        return "숫자 오류"
    return {DISPLAY: "표시 오류", EXPLAIN: "설명 부족", LAST_YEAR: "작년 보고서의 오류"}.get(c.when, "확인")


def apply_marks(checks: list[Check], marks: dict) -> None:
    """회계사가 지난 엑셀에 적은 확인(X 는 쓰지 않음, O 는 맞는 연결)을 검증에 옮긴다."""
    for c in checks:
        m = marks.get(c.id) or {}
        c.excluded, c.confirmed = bool(m.get("excluded")), bool(m.get("confirmed"))


def build(doc: Doc, defs: dict | None = None, amount_links: bool = False, other: Doc | None = None) -> tuple[list[Check], dict, list[dict]]:
    """검증 목록 · 새 연결 정의 · 풀지 못한 연결. defs 가 있으면 그 구조와 연결을 이름으로 다시 풀고, 없는 표만 새로 탐지한다.

    표 사이 연결(레퍼)은 AI 가 주석을 읽고 뜻으로 정의해 defs 의 links 에 넣은 것을 쓴다(dsd_ai). amount_links 를 켜면
    금액이 같은 칸을 엔진이 찾아 함께 건다(dsd_refs). 금액 대조는 뜻을 모르고 금액이 같은 칸만 이어서 틀린 숫자를 잡지 못하고
    우연히 같은 칸(만기분석의 명목현금흐름, 법인세가 0 일 때의 세전손실)을 건다. 그래서 기본은 끄고 AI 의 참고와 채점에 쓴다."""
    defs = defs or {}
    stored = {(s["table"], tuple(s.get("sig") or [])): s for s in defs.get("structures", [])}
    sums, no_sums = list(defs.get("sums", [])), list(defs.get("no_sums", []))      # AI 가 표를 읽고 정한 합계 구조와, 합계가 아니라고 한 줄 · 열
    units = list(defs.get("units", []))            # 엔진이 단위를 잘못 읽은 표를 AI 가 바로잡은 것(단위 줄이 없어 앞 표의 단위를 이어받은 표)
    for u in units:
        if doc.table(u["table"]) is not None:
            doc.table(u["table"]).unit = u["unit"]
    over: dict[str, list] = {}
    for x in sums + [dict(n, off=True) for n in no_sums]:
        over.setdefault(x["table"], []).append(x)
    checks, unresolved, structures = [], [], []
    for t in doc.tables():
        s = stored.get((t.id, tuple(_sig(t))))
        if s is None:
            d = detect(t)
            s = {"table": t.id, "sig": _sig(t), **d} if d["vsum"] or d["hsum"] else None
        if s is not None:
            structures.append(s)
        if s is None and t.id not in over:
            continue
        checks += _checks_from_structure(t, overlay(t, s, over.get(t.id, [])), unresolved)
    links = list(defs.get("links", []))
    have = {x["id"] for x in links}
    for x in links:
        if str(x["left"].get("table", "")).startswith(PAIR_ID) or any(str(r.get("table", "")).startswith(PAIR_ID) for r in x["right"]):
            if other is None:                    # 다른 보고서와 잇는 연결은 그 보고서를 함께 줬을 때만 건다(--pair)
                continue
        checks += _link_checks(doc, x, x.get("source", "규칙"), True, unresolved, other)
    for x in rules().get("fs_links", []):
        if x["id"] in have:
            continue
        got = _link_checks(doc, x, "규칙", False, unresolved)
        if got:
            checks += got
            links.append(dict(x, source="규칙"))
    from . import dsd_appropriation, dsd_kicpa       # 처분계산서 규칙과 감리지적 유형 검사(12단계). 연결 정의에 남기지 않고 판마다 다시 찾는다

    for got in (dsd_appropriation.checks(doc), dsd_kicpa.checks(doc)):
        checks += [c for c in got if c.id.split("|")[0] not in have]
    for x in (rules().get("pair_links", []) if other is not None else []):      # 함께 낸 다른 보고서와 견주는 규칙(--pair)
        if x["id"] in have:
            continue
        got = _link_checks(doc, x, "규칙", False, unresolved, other)
        if got:
            checks += got
            links.append(dict(x, source="규칙"))
    from . import dsd_refs                       # 표 사이 숫자 연결을 금액 근거로 찾는다. 이미 걸린 칸은 건너뛴다

    have = {x["id"] for x in links}
    taken = {(c.table, c.r, c.c) for c in checks if c.group == "레퍼"}
    for x in (dsd_refs.detect(doc, taken) if amount_links else []):
        if x["id"] in have:
            continue
        got = _link_checks(doc, x, "규칙", False, unresolved)
        if got:
            checks += got
            links.append(x)
    before = checks
    checks = _drop_same(checks)
    marks = defs.get("marks", {})
    apply_marks(checks, marks)
    notes = {x["id"]: x for x in defs.get("findings", [])}
    for c in checks:
        if c.id in notes:
            apply_finding(c, notes[c.id])
    # 규칙과 같은 두 칸이라 뺀 AI 연결에 적어 둔 판정은 남은 규칙 검증으로 옮긴다(12단계: 처분계산서 규칙을 넣자 스터디 보고서에서
    # AI 가 먼저 적고 판정한 처분계산서 연결이 빠지고 규칙 검증의 판정이 비었다)
    ruled = {_pair(c): c for c in checks if c.source != "AI" and _pair(c) is not None}
    kept = {id(c) for c in checks}
    for g in before:
        r = ruled.get(_pair(g)) if id(g) not in kept and g.id in notes else None
        if r is not None and not r.finding:
            apply_finding(r, notes[g.id])
    return checks, {"version": 1, "source": doc.source, "structures": structures, "sums": sums, "no_sums": no_sums, "units": units, "links": links, "marks": marks,
                    "prior": list(defs.get("prior", [])), "findings": list(defs.get("findings", [])), "skipped": list(defs.get("skipped", [])),
                    "workpapers": list(defs.get("workpapers", [])), "prior_pairs": list(defs.get("prior_pairs", []))}, unresolved


PRIOR_ID = "작년:"      # 작년 보고서의 표 id 앞에 붙인다(검증의 terms 와 엑셀 주소에서 당기 표와 가른다)
PAIR_ID = "짝:"         # 함께 낸 다른 보고서(연결과 별도)의 표 id 앞에 붙인다
# 전기 대사는 조건부다(K-IFRS 1001 문단 41 재분류, 1105 문단 34 중단영업 재표시). 금액이 다르면 「확인」 이고 재분류 공시가 있는지 본다
PRIOR_WHEN = "전기 금액을 재분류하거나 다시 작성하지 않았다"


def _scale(t: Table, q: Table, rows: dict, a: int, b: int) -> float:
    """당기 표의 전기 열과 작년 표의 당기 열 사이 표시 단위 배수. 같은 표를 해마다 다른 단위로 적는 회사가 있다(원 ↔ 천원, USD ↔ 천USD).
    단위 줄을 못 읽는 표도 있어 금액으로 정한다: 짝지은 줄에서 양쪽 다 0 이 아닌 칸으로 가장 많이 맞는 배수를 쓰고, 같으면 1 이다."""
    best, top = 1, -1
    for k in (1, 1000, 0.001, 1000000, 0.000001):
        n = 0
        for i, j in rows.items():
            if (i, a) in (t.cell_units or {}) or (j, b) in (q.cell_units or {}):      # 칸에 단위가 붙은 칸은 배수를 정하는 데 쓰지 않는다
                continue
            v, w = t.nums[i][a], q.nums[j][b]
            if not (_isnum(v) and _isnum(w) and v and w):      # 0 이 든 칸은 배수를 말해 주지 않는다. 올해 0 · 작년 351,882 를
                continue                                        # ×0.000001 에서 맞는 줄로 세어 작년 146,134,773 을 146 으로 견줬다(한 상장사 2025 연결)
            if k == 1:
                hit = v == w
            else:                                   # 큰 단위에서 맞춘다
                hit = abs(round(v / k) - w) <= 1 if k > 1 else abs(v - round(w * k)) <= 1
            if hit:
                n += 1
        if n > top:
            best, top = k, n
    return best


def _same_period(new_header: str, old_header: str) -> bool:
    """당기 보고서의 전기 열과 작년 보고서의 당기 열이 같은 기간인가. 기수가 둘 다 읽히면 같아야 하고, 기간 종류(반기 · 분기 · 연)가 같아야 한다.
    반기보고서의 전반기 손익을 작년 사업보고서의 연간 손익과 견주지 않게 한다."""
    a, b = term_of(new_header), term_of(old_header)
    if a is not None and b is not None and a != b:
        return False
    return span_of(new_header) == span_of(old_header)


def _same_name_rows(t: Table, q: Table, rows: dict, pairs: list) -> None:
    """이름이 같은 줄이 여럿인 표(차입처 · 차입종류가 같은 차입금 여러 줄)의 줄 짝을 다시 정한다. rows 를 고친다.
    이름만으로는 어느 줄인지 알 수 없으므로 견줄 금액이 모두 같은 줄끼리 먼저 잇고, 남은 줄이 양쪽에 하나씩일 때만 잇는다.
    그 밖에는 짝을 지운다(순서로 이으면 줄이 늘거나 준 해에 다른 차입금과 견주게 된다)."""
    from .dsd_compare import row_keys

    nk, ok = row_keys(t), row_keys(q)
    groups: dict[str, list] = {}
    for i, k in enumerate(nk):
        groups.setdefault(k, [[], []])[0].append(i)
    for j, k in enumerate(ok):
        if k in groups:
            groups[k][1].append(j)
    for k, (ns, os_) in groups.items():
        if len(ns) < 2 and len(os_) < 2:
            continue
        for i in ns:
            rows.pop(i, None)
        free = list(os_)
        left = []
        for i in ns:
            hit = next((j for j in free if pairs and all(_isnum(t.nums[i][a]) and _isnum(q.nums[j][b]) and t.nums[i][a] == q.nums[j][b] for a, b in pairs)), None)
            if hit is None:
                left.append(i)
            else:
                rows[i] = hit
                free.remove(hit)
        left = [i for i in left if any(_isnum(t.nums[i][a]) and t.nums[i][a] for a, _ in pairs)]      # 견줄 금액이 없는 줄(0 · 빈칸)은 짝을 찾지 않는다
        free = [j for j in free if any(_isnum(q.nums[j][b]) and q.nums[j][b] for _, b in pairs)]
        if len(left) == 1 and len(free) == 1 and _text_sig(t, left[0]) == _text_sig(q, free[0]):
            rows[left[0]] = free[0]                 # 글자 칸(채무자 · 대출기간 · 차입처)까지 같을 때만 잇는다(한 상장사 2025 PF 보증 표에서 다른 사업장끼리 이었다)


def _text_sig(t: Table, i: int) -> tuple:
    """줄의 글자 칸(숫자가 아닌 칸). 이름이 같은 줄을 가를 때 쓴다."""
    return tuple(norm(str(v)) for j, v in enumerate(t.rows[i]) if j and not _isnum(t.nums[i][j]) and str(v or "").strip() not in ("", "-"))


def apply_prior_verdicts(checks: list[Check], verdicts: list[dict]) -> None:
    """전기 대사 차이에 적어 둔 판정을 반영한다. 불일치는 조건을 떼어 FALSE 로 세고, 설명됨 · 걸지 않음은 검증에서 뺀다."""
    by = {x["id"]: x for x in verdicts}
    for c in checks:
        v = by.get(c.id)
        if v is None:
            continue
        c.basis = (c.basis + " · " if c.basis else "") + f"판정 {v['verdict']}: {v['why']}"
        name = {"불일치": "숫자 오류", "작년 불일치": "작년 보고서 불일치"}.get(v["verdict"], v["verdict"])
        c.finding = f"{name}: {v['why']}"
        if v["verdict"] == "불일치":
            c.when = ""
        elif v["verdict"] == "작년 불일치":
            c.when = LAST_YEAR
        else:
            c.dropped = v["verdict"]                 # 설명됨 · 걸지 않음. 회계사 확인 칸(X)과 따로 둔다(10단계 재평가: 도구가 X 를 미리 적었다)


def join_priors(docs: list[Doc]) -> tuple[Doc, list]:
    """작년 보고서 여럿을 한 문서로 잇는다. (이은 문서, [(원래 문서, 표 이름 앞머리)]).
    둘째 보고서부터는 부분 이름과 표 이름 앞에 ② ③ 을 붙여 엑셀 시트와 주소가 겹치지 않게 한다."""
    import copy

    if len(docs) == 1:
        return docs[0], [(docs[0], "")]
    parts, groups = list(docs[0].parts), [(docs[0], "")]
    for n, d in enumerate(docs[1:], 2):
        tag = chr(0x245F + n)                    # ② ③ …
        for p in d.parts:
            q = copy.copy(p)
            q.key = tag + p.key
            q.items = [(x[0], copy.copy(x[1])) if x[0] == "t" else x for x in p.items]
            for x in q.items:
                if x[0] == "t":
                    x[1].id = tag + x[1].id
            parts.append(q)
        groups.append((d, tag))
    return Doc(" + ".join(d.source for d in docs), docs[0].sha256, parts), groups


def _prior_check(cid: str, t: Table, i: int, a: int, q: Table, k: int, b: int, k10: float, tag: str, label: str) -> Check:
    """전기 대사 검증 하나. 어느 쪽이든 칸에 단위가 붙어 있으면(「6,806,616천원」 「22.26%」) 표의 단위 배수 대신 칸의 단위로 환산해 견준다.
    표 단위 배수(k10)는 금액 줄로 정하므로 한 표에 금액과 비율 · 단위 붙은 칸이 섞이면 그 칸에는 맞지 않는다(10단계 스터디, 24번 자본금 · 유효세율)."""
    if (i, a) in (t.cell_units or {}) or (k, b) in (q.cell_units or {}):
        return Check(cid, "전기", "전기", t.id, i, a, [(PRIOR_ID + tag + q.id, k, b, 1)], None, label, "규칙", "칸에 붙은 단위로 견줌", when=PRIOR_WHEN)
    return Check(cid, "전기", "전기", t.id, i, a, [(PRIOR_ID + tag + q.id, k, b, k10 if k10 < 1 else 1)], None, label, "규칙",
                 "" if k10 == 1 else f"작년 보고서와 표시 단위가 다름(×{k10:g})", plain=True, left_div=k10 if k10 > 1 else 1, when=PRIOR_WHEN)


_SCE_OPEN = re.compile(r"(기초|초\)|1월\s*1일|0?1\.\s*0?1|\.\s*1\.\s*1)")
_SCE_CLOSE = re.compile(r"(기말|말\)|12월\s*31일|12\.\s*31|반기말|분기말)")
_SCE_DATE = re.compile(r"\d{2,4}\s*[년.]\s*\d{1,2}\s*[월.]\s*\d{1,2}\s*일?|\d{1,2}\.\s*\d{1,2}|\((?:전전기|전기|당기)(?:초|말)\)|(?:전전기|전기|당기)(?:초|말)")


def _sce_blocks(t: Table) -> list[list[int]]:
    """자본변동표의 기간 구간. 줄 이름이 기초(「2024년 1월 1일 (전기초)」 「01.01(당기초)」)인 줄에서 새 구간이 시작한다."""
    labels = _labels(t)
    starts = [i for i, x in enumerate(labels) if _SCE_OPEN.search(str(x)) and any(_isnum(v) for v in t.nums[i])]
    blocks = [list(range(a, b)) for a, b in zip(starts, starts[1:] + [len(labels)])]
    out: list[list[int]] = []                       # 기말 줄이 없는 구간(전기오류수정이 있으면 「전기초(보고금액)」 「수정후 전기초」 처럼 기초 줄이 둘)은 다음 구간에 붙인다
    for b in blocks:
        if out and not any(_SCE_CLOSE.search(str(labels[i])) for i in out[-1]):
            out[-1] += b
        else:
            out.append(b)
    return out


def _prior_sce(t: Table, q: Table, tag: str) -> tuple[list[Check], list[dict]]:
    """자본변동표의 전기 대사: 올해 표의 전기 구간(첫 구간) = 작년 표의 당기 구간(마지막 구간). 구간의 첫 줄(기초)과 마지막 줄(기말)은 자리로,
    나머지는 날짜 · 「(전기초)」 를 뗀 줄 이름으로, 열은 열 이름으로 짝짓는다. 10단계 전까지는 자본변동표의 전기를 견주지 않았다."""
    from .dsd_compare import _name, _pairs

    a, b = _sce_blocks(t), _sce_blocks(q)
    if len(a) < 2 or not b:
        return [], []
    cur, old = a[0], b[-1]
    strip = lambda x: _name(_SCE_DATE.sub("", str(x)))      # noqa: E731
    la, lb = _labels(t), _labels(q)
    rows = {cur[0]: old[0], cur[-1]: old[-1]}
    mid = _pairs([strip(la[i]) for i in cur[1:-1]], [strip(lb[j]) for j in old[1:-1]])
    rows.update({cur[1 + i]: old[1 + j] for i, j in mid.items()})
    cols = _pairs([_name(h) for h in t.header], [_name(h) for h in q.header])
    out, lost = [], []
    for i in cur:
        for c in range(1, len(t.header)):
            v = t.nums[i][c]
            if not _isnum(v) or c not in cols:
                continue
            j = rows.get(i)
            if j is None or not _isnum(q.nums[j][cols[c]]):
                if v != 0:
                    lost.append({"table": t.id, "kind": "전기", "why": f"전기: 작년 보고서 {q.id} 에서 「{la[i]}」 금액을 찾지 못함"})
                continue
            out.append(_prior_check(f"전기|{t.id}|{la[i]}#{_ref(la, i)[1]}|{t.header[c]}#{_ref(t.header, c)[1]}", t, i, c, q, j, cols[c], 1, tag,
                                    f"작년 {tag}{q.id}(당기 구간) {lb[j]} · {q.header[cols[c]]}"))
    return out, lost


def _ai_rows(t: Table, q: Table, rows: dict, pairs: list) -> None:
    """AI 가 짝지어 준 줄(이름이 바뀐 과목)을 줄 짝에 더한다. rows 를 고친다."""
    for x in pairs or []:
        if x.get("table") != t.id:
            continue
        i, j = find_row(t, x["row"], x.get("row_nth", 1)), find_row(q, x["prior_row"], x.get("prior_row_nth", 1))
        if i is not None and j is not None:
            rows[i] = j


# 전기 대사의 XBRL 항목과 표현 차이 사전(2026-10-22 실행 시간 P4). 한 상장사 2026 반기 별도에서 AI 가 prior_pairs 30건으로 메운 31줄을 엔진이 먼저 잇는다
_XBRL_PRIOR = re.compile(r"^(BP|P)(FY\d{4})([ed])([A-Z0-9]+)(.*)$", re.S)


def xbrl_prior(fact: tuple) -> list[tuple]:
    """올해 보고서 전기 칸의 XBRL 항목(계정 코드, 문맥, …) → 작년 보고서에서 같은 사실을 가리키는 (계정 코드, 문맥) 후보. 전기 칸이 아니면 [].
    문맥 앞머리 P(전기)는 작년 보고서의 C(당기), BP(전전기)는 P 다. 반기 · 분기 보고서의 비교 연도 말 · 연간 문맥(HY · Q1 처럼 A · Q 가 붙지 않은 것)은
    작년 사업보고서의 FY 로도 찾는다. 올해 반기 「PFY2025eHY」(전기말) = 작년 사업보고서 「CFY2025eFY」, 올해 반기 「PFY2025dHYA」(전반기 누적) = 작년 반기 「CFY2025dHYA」.
    문맥의 차원(뒤에 붙은 축 · 멤버)은 그대로 같아야 한다."""
    code, ctx = fact[0], fact[1]
    m = _XBRL_PRIOR.match(ctx)
    if not m:
        return []
    head = ("P" if m.group(1) == "BP" else "C") + m.group(2) + m.group(3)
    out = [(code, head + m.group(4) + m.group(5))]
    if m.group(4) != "FY" and not m.group(4).endswith(("A", "Q")):
        out.append((code, head + "FY" + m.group(5)))
    return out


def _xbrl_rows(t: Table, q: Table, rows: dict, cols: list) -> None:
    """XBRL 항목이 같은 줄을 잇는다. rows 를 고친다. 같은 항목은 같은 사실이라 이름 짝보다 앞선다. 다만 이름 짝이 가리킨 작년 칸에도 항목이 있고
    그것이 다를 때만 바꾼다. 작년 표의 같은 열에 그 항목이 한 줄뿐일 때만 잇는다. 줄 이름 키(row_keys)가 앞 두 칸만 써서
    셋째 칸만 다른 줄이 같은 키가 되면 이름으로 잇지 못한다(한 상장사 2026 반기 별도 주석 19-2 판매비와관리비 열한 줄, 21-2 이자수익 · 이자비용)."""
    if not t.xbrl or not q.xbrl:
        return
    idx: dict = {}
    for (k, b), f in q.xbrl.items():
        idx.setdefault(f[:2], set()).add((k, b))
    for a, b in cols:
        for i in range(len(t.rows)):
            f = t.xbrl.get((i, a))
            want = xbrl_prior(f) if f else []
            hits = {k for g in want for k, bb in idx.get(g, ()) if bb == b}
            if len(hits) != 1:
                continue
            k, j = hits.pop(), rows.get(i)
            if j is None or (q.xbrl.get((j, b)) is not None and q.xbrl[(j, b)][:2] not in want):
                rows[i] = k


@lru_cache(maxsize=1)
def _prior_names() -> dict:
    d = yaml.safe_load((DEFS / "dsd_prior_names.yaml").read_text(encoding="utf-8")) or {}
    return {"open_close": re.compile(d["open_close"]), "swap": re.compile(d["swap"]),
            "replace": [(re.compile(p), r) for p, r in d.get("replace") or []]}


def prior_alias(label: str) -> str:
    """전기 대사용 줄 이름: 표현 차이 사전(dsd_prior_names.yaml)으로 바꾼 이름. 「단기차입금의 순감소」 와 「단기차입금의 순증가(감소)」 가 같은 이름이 된다."""
    from .dsd_compare import _FOOT

    r = _prior_names()
    s = re.sub(r"\s+", " ", _FOOT.sub("", str(label or ""))).strip()
    m = r["open_close"].match(s)
    if m:
        return m.group(1)
    m = r["swap"].match(s)
    if m:
        s = m.group(2) + m.group(1)
    s = norm(s)
    for p, rep in r["replace"]:
        s = p.sub(rep, s)
    return re.sub(r"[\-·ㆍ,]", "", s)


def _alias_rows(t: Table, q: Table, rows: dict) -> None:
    """이름 짝 · XBRL 항목으로 잇지 못한 줄을 표현 차이 사전으로 잇는다. rows 를 고친다. 글자 열을 이은 전체 이름으로 견주고,
    바꾼 이름이 양쪽 표에 하나씩인 줄만 잇는다. 이미 이은 작년 줄은 다시 쓰지 않는다."""
    a, b = [prior_alias(x) for x in _labels(t)], [prior_alias(x) for x in _labels(q)]
    taken = set(rows.values())
    for i, k in enumerate(a):
        if i in rows or not k or a.count(k) != 1 or b.count(k) != 1:
            continue
        j = b.index(k)
        if j not in taken:
            rows[i] = j
            taken.add(j)


def _xbrl_lost(doc: Doc, prior: Doc, tag: str, out: list[Check], lost: list[dict]) -> list[dict]:
    """줄 짝으로 작년 칸을 찾지 못한 전기 금액을 작년 보고서 전체에서 같은 XBRL 항목으로 찾는다. 찾은 칸은 out 에 검증을 더하고,
    남은 「못 찾은 줄」 을 돌려준다. 표 짝을 찾지 못한 주석(한 상장사 2026 반기 별도 주석 3-2 · 3-4 · 16-2 ↔ 작년 사업보고서 4-1 · 4-3 · 19-1)에 쓴다.
    작년 보고서에 같은 항목이 여러 칸이면 처음 나온 칸과 견준다(같은 사실이라 금액이 같아야 한다)."""
    idx: dict = {}
    for q in prior.tables():
        for (k, b), f in sorted((q.xbrl or {}).items()):
            idx.setdefault(f[:2], (q, k, b))
    if not idx:
        return lost
    have = {(c.table, c.r, c.c) for c in out}
    keep = []
    for u in lost:
        t = doc.table(u["table"]) if "row" in u else None
        if t is None or not t.xbrl:
            keep.append(u)
            continue
        i, missing, labels = u["row"], False, _labels(t)
        for a in range(1, len(t.header)):
            f, v = t.xbrl.get((i, a)), t.nums[i][a]
            if f is None or not _isnum(v) or (t.id, i, a) in have or not xbrl_prior(f):
                continue
            hit = next((idx[g] for g in xbrl_prior(f) if g in idx), None)
            if hit is None or not _isnum(hit[0].nums[hit[1]][hit[2]]):
                missing = missing or v != 0
                continue
            q, k, b = hit
            k10 = (q.unit or 1) / (t.unit or 1)
            cid = f"전기|{t.id}|{labels[i]}#{_ref(labels, i)[1]}|{t.header[a]}#{_ref(t.header, a)[1]}"
            out.append(_prior_check(cid, t, i, a, q, k, b, k10 if k10 != 1 else 1, tag,
                                    f"작년 {tag}{q.id} {q.rows[k][0]} · {q.header[b]}(XBRL 항목이 같은 칸)"))
            have.add((t.id, i, a))
        if missing:
            keep.append(u)
    return keep


def prior_checks(doc: Doc, prior: Doc, m, tag: str = "", pairs: list | None = None) -> tuple[list[Check], list[dict]]:
    """전기 대사: 당기 보고서의 전기 숫자 = 작년 보고서의 당기 숫자. m 은 dsd_compare.match(doc, prior).

    재무제표 본표(자본변동표 제외)는 전기 열과 작년 표의 당기 열을 맞춘다. 주석 표는 열 이름에 「전기」 가 있고 작년 표에
    그 자리를 「당기」 로 바꾼 이름의 열이 있을 때 맞춘다(전기말 ↔ 당기말). 줄은 행 이름으로 짝짓는다.
    작년 표에서 줄을 찾지 못한 전기 금액은 검증을 만들지 않고 풀지 못한 연결로 낸다(과목 재분류, 새 과목).
    당기 표와 전기 표를 따로 둔 주석(「<전기>」 변동표)은 표 짝을 정해야 해서 다음 단계의 AI 연결 몫이다."""
    out, unresolved, done = [], [], {}
    ai_pairs = pairs
    olds = {t.id: t for t in prior.tables()}
    swaps = (("전기말", "당기말"), ("전기말", "당기"), ("전기", "당기"), ("전반기", "당반기"), ("전분기", "당분기"))
    if doc_span(doc) != "연" and doc_span(prior) == "연":      # 반기 · 분기의 「전기」 열은 전반기 손익일 수 있어 사업보고서와는 「전기말」 만 견준다
        swaps = swaps[:2]
    for t in doc.tables():
        mt = m.tables.get(t.id)
        if not mt:
            continue
        q, rows = olds[mt[0]], dict(mt[1])
        statement = not doc.part_of(t.id).key.startswith("주석")
        pairs = []
        if statement:
            if t.id.startswith("자본변동표"):
                more, gone = _prior_sce(t, q, tag)
                out += more
                unresolved += gone
                continue
            a, b = period_col(t, "전기"), period_col(q, "당기")
            if a is not None and b is not None and a != period_col(t, "당기") and _same_period(t.header[a], q.header[b]):
                pairs.append((a, b))
            term = term_of(t.header[a]) if a is not None else None
            qh = [norm(h) for h in q.header]
            for j, h in enumerate(t.header):          # 전기 열이 여럿이면(반기 손익의 3개월 · 누적) 작년 보고서에서 머리줄이 같은 열과 견준다
                if j and j != a and term is not None and term_of(h) == term and qh.count(norm(h)) == 1:
                    pairs.append((j, qh.index(norm(h))))
        else:
            qh = [norm(h) for h in q.header]
            for j, h in enumerate(t.header):
                name = norm(h)                       # 반기 「전기말」 열은 사업보고서의 「당기말」 · 「당기」 열과 견준다(11단계)
                for old, new in swaps:
                    if j and old in name and qh.count(name.replace(old, new)) == 1:
                        pairs.append((j, qh.index(name.replace(old, new))))
                        break
        labels = _labels(t)
        done[t.id] = {a for a, _ in pairs}
        _more_rows(t, q, rows)
        _same_name_rows(t, q, rows, pairs)
        _xbrl_rows(t, q, rows, pairs)
        _alias_rows(t, q, rows)
        _ai_rows(t, q, rows, ai_pairs)
        for a, b in pairs:
            k10 = _scale(t, q, rows, a, b)
            for i in range(len(t.rows)):
                v = t.nums[i][a]
                if not _isnum(v):
                    continue
                k = rows.get(i)
                if k is None or not _isnum(q.nums[k][b]):
                    if v != 0:
                        unresolved.append({"table": t.id, "kind": "전기", "why": f"전기: 작년 보고서 {q.id} 에서 「{labels[i]}」 금액을 찾지 못함", "row": i})
                    continue
                out.append(_prior_check(f"전기|{t.id}|{labels[i]}#{_ref(labels, i)[1]}|{t.header[a]}#{_ref(t.header, a)[1]}", t, i, a, q, k, b, k10, tag,
                                        f"작년 {tag}{q.id} {q.rows[k][0]} · {q.header[b]}"))
    more, lost = _prior_split_tables(doc, prior, m, tag, {c.id for c in out}, ai_pairs, done)
    out += more
    left = _xbrl_lost(doc, prior, tag, out, unresolved + lost)      # 줄 짝으로 못 찾은 줄은 작년 보고서 전체에서 같은 XBRL 항목을 찾는다
    seen, gone = set(), []
    for x in left:                              # 같은 줄을 열마다 알리지 않는다
        if (x["table"], x["why"]) not in seen:
            seen.add((x["table"], x["why"]))
            gone.append({k: v for k, v in x.items() if k != "row"})      # 줄 번호는 XBRL 찾기에만 쓴다. 바깥 꼴은 그대로 둔다
    return out, gone


_PERIOD_LABEL = re.compile(r"^(?:[①-⑳]|\(\d+\)|\d+\))?\s*[<(\[〈]?\s*(당|전)(반기|분기|기)(말)?(?![가-힣])")


def period_labels(part) -> dict:
    """표 바로 위 문단이 「당반기 (단위 : 백만원)」 「<전기>」 처럼 기간을 적은 표의 기간 이름. {표 id: 당반기 | 전반기 | 당기말 | 전기말 …}"""
    out, last = {}, ""
    for x in part.items:
        if x[0] == "p":
            last = x[1].strip()
            continue
        m = _PERIOD_LABEL.match(last)
        if m:
            out[x[1].id] = "".join(g or "" for g in m.groups())
        last = ""
    return out


PERIOD_PAIRS = {"전기말": ("당기말", "당기"), "전기": ("당기", "당기말"), "전반기": ("당반기",), "전반기말": ("당반기말",),
                "전분기": ("당분기",), "전분기말": ("당분기말",)}


def _hdr(h: str) -> str:
    """열 이름 견주기용: 띄어쓰기 · 쉼표 · 가운뎃점 · 「의」 를 뗀다(「금융자산의 범주 합계」 = 「금융자산, 범주 합계」)."""
    from .dsd_compare import _name

    return re.sub(r"[,·ㆍ\s]|의(?=[가-힣])", "", _name(h))


def _col_pairs(t: Table, q: Table) -> list[tuple[int, int]] | None:
    """두 표의 숫자 열 짝. 열 이름이 모두 같으면(견주기용 이름) 이름으로, 열 수가 같고 이름이 거의 같으면 자리로 짝짓는다. 못 지으면 None."""
    from difflib import SequenceMatcher

    a, b = [_hdr(h) for h in t.header], [_hdr(h) for h in q.header]
    if len(a) != len(b):
        return None
    if a == b:
        return [(j, j) for j in range(1, len(a))]
    sims = [SequenceMatcher(None, x, y).ratio() for x, y in zip(a[1:], b[1:]) if x or y]
    return [(j, j) for j in range(1, len(a))] if sims and min(sims) >= 0.75 else None


_PERIOD_WORD = re.compile(r"(?:^|(?<=\s))(당|전)(반기말|분기말|기말|반기|분기|기)(?=$|[\s(\d])")


def _period_cols(t: Table, label: str = "") -> dict:
    """{숫자 열: (기간 이름, 기간 이름을 뺀 열 이름)}. 열 이름에 「전반기 3개월」 처럼 기간이 있으면 그것을, 없으면 표 위 기간 이름(label)을 쓴다.
    「당기손익인식금융자산」 의 「당기」 는 기간이 아니다(뒤에 빈칸 · 괄호 · 숫자가 오거나 끝일 때만 기간으로 읽는다)."""
    out = {}
    for j in range(1, len(t.header)):
        h = str(t.header[j] or "")
        mm = _PERIOD_WORD.search(h)
        if mm:
            out[j] = (mm.group(1) + mm.group(2), _hdr(h[:mm.start()] + " " + h[mm.end():]))
        elif label:
            out[j] = (label, _hdr(h))
    return out


def _loose_key(k: str) -> str:
    """줄 짝 이름을 느슨하게: 마지막 이름만, 괄호 안 · 각주 표시([주2]) · 띄어쓰기 · 붙임표를 뗀다."""
    k = re.sub(r"\([^)]*\)|\[[^\]]*\]", "", str(k).split("|")[-1])
    return re.sub(r"[\s\-·ㆍ,]", "", k)


_XBRL_WORDS = re.compile(r"^(?:장부금액|공시금액|금액)+$")


def _same_core(a: str, b: str) -> bool:
    """기간을 뺀 열 이름이 같은가. 한쪽이 다른 쪽의 끝이면 앞에 붙은 말이 XBRL 의 「장부금액 · 공시금액」 일 때만 같다고 본다
    (올해 「장부금액 공시금액 3개월」 = 작년 「3개월」). 한 상장사 2026 반기의 「부문의 합계 연결실체 내 내부거래조정 지역 합계」 를
    작년 「지역 합계」 와 짝지었다(11단계 재평가)."""
    if a == b:
        return True
    if not (a and b):
        return False
    long, short = (a, b) if len(a) > len(b) else (b, a)
    return long.endswith(short) and bool(_XBRL_WORDS.match(long[:-len(short)]))


def _agree(t: Table, q: Table, rows: dict, cols: list) -> float:
    """짝지은 칸 가운데 금액이 같은 칸의 비율(표 단위 배수를 맞춰 견준다). 둘 다 0 이거나 빈 칸은 세지 않는다."""
    n = same = 0
    for a, b in cols:
        k = _scale(t, q, rows, a, b)
        for i, j in rows.items():
            v, w = t.nums[i][a], q.nums[j][b]
            if not (_isnum(v) and _isnum(w) and (v or w)):
                continue
            n += 1
            if (v == 0) != (w == 0):                 # 한쪽만 0 이면 다른 금액이다(단위 배수로 0 과 1,027 을 같다고 보지 않는다)
                continue
            same += (v == w) if k == 1 else (abs(round(v / k) - w) <= 1 if k > 1 else abs(v - round(w * k)) <= 1)
    return same / n if n else 0.0


def _loose_rows(t: Table, q: Table, rows: dict) -> None:
    """이름 짝에서 빠진 줄을 느슨한 이름(_loose_key)으로 잇는다. rows 를 고친다. 느슨한 이름이 양쪽 표에 하나뿐인 줄만 잇는다
    (한 상장사 2025 주석8-6 「(주)가나다」 ↔ 작년 「(주)가나다[주]」)."""
    from .dsd_compare import row_keys

    a, b = [_loose_key(k) for k in row_keys(t)], [_loose_key(k) for k in row_keys(q)]
    taken = set(rows.values())
    for i, k in enumerate(a):
        if i in rows or not k or a.count(k) != 1 or b.count(k) != 1:
            continue
        j = b.index(k)
        if j not in taken:
            rows[i] = j
            taken.add(j)


def _more_rows(t: Table, q: Table, rows: dict) -> None:
    """짝지은 두 표에서 matcher 가 잇지 않은 줄을 줄 이름 짝(dsd_compare._pairs)과 느슨한 이름(_loose_rows)으로 더 잇는다. rows 를 고친다.
    이미 이은 작년 줄은 다시 쓰지 않는다. 11단계 첫 판은 이 줄들을 다른 작년 표에서까지 찾다가 틀린 표와 짝지었다(한 상장사 주석8-6 ↔ 작년 8-1)."""
    from .dsd_compare import _pairs, row_keys

    taken = set(rows.values())
    for i, j in _pairs(row_keys(t), row_keys(q)).items():
        if i not in rows and j not in taken:
            rows[i] = j
            taken.add(j)
    _loose_rows(t, q, rows)


def _cross_cols(tp: dict, qp: dict, n_cols: int) -> list[tuple[int, int]]:
    """올해 표의 전기 열 ↔ 작년 표의 당기 열 짝. 기간 이름이 짝(PERIOD_PAIRS)이고 기간을 뺀 열 이름이 같거나 한쪽이 다른 쪽의 끝이면 짝짓는다
    (올해 XBRL 「장부금액 공시금액 3개월」 ↔ 작년 「당반기 3개월」). 기간을 뺀 이름이 비면 숫자 열이 하나인 표끼리만 짝짓는다."""
    out, taken = [], set()
    for j, (per, core) in tp.items():
        wants = PERIOD_PAIRS.get(per, ("당" + per[1:],))
        for b, (qper, qcore) in qp.items():
            if b in taken or qper not in wants:
                continue
            if _same_core(core, qcore) or ((not core or not qcore) and n_cols == 1):
                out.append((j, b))
                taken.add(b)
                break
    return out


def doc_span(doc: Doc) -> str:
    """보고서의 기간 종류(반기 · 분기 · 연). 재무상태표 · 손익계산서 · 현금흐름표의 당기 열 이름으로 정한다.
    본표의 다른 열은 보지 않는다(한 상장사 2025 연결 자본변동표의 열 이름 때문에 감사보고서를 「분기」 로 읽었다)."""
    for name in ("재무상태표", "손익계산서", "현금흐름표"):
        t = doc.table(name)
        a = period_col(t, "당기") if t is not None else None
        if a is not None:
            return span_of(t.header[a])
    return "연"


def _prior_split_tables(doc: Doc, prior: Doc, m, tag: str, have: set, ai_pairs: list | None = None,
                        done: dict | None = None) -> tuple[list[Check], list[dict]]:
    """당기 표와 전기 표를 따로 둔 주석의 전기 대사. 표 위 문단이 「전반기」 인 표를 작년 보고서의 「당반기」 표와 견준다
    (「전기말」 ↔ 「당기말」 · 「당기」, 「전기」 ↔ 「당기」). 열 이름이 같거나 거의 같은 표끼리, 같은 머리줄이 여럿이면 줄 이름이 많이 겹치는 표와 짝짓는다.
    줄은 이름으로 짝짓는다. 기간 이름이 맞는 표가 작년 보고서에 없으면 견주지 않는다(반기보고서의 전반기 표를 사업보고서와 견주지 않는다).
    11단계: 반기 주석은 「전기말」, 사업보고서는 같은 표에 「당기」 를 적고 열 이름도 조금씩 달라(「금융자산의 범주 합계」 · 「금융자산, 범주 합계」)
    한 상장사 2026 반기 주석의 전기 대사가 0건이었다."""
    from .dsd_compare import _pairs, row_keys

    out, lost, done = [], [], done or {}
    olds = {p.key: p for p in prior.parts}
    by_id = {q.id: q for q in prior.tables()}
    interim = doc_span(doc) != "연" and doc_span(prior) == "연"      # 반기 · 분기의 「전기」 열은 전반기 손익일 수 있어 사업보고서와 견주지 않는다
    for p in doc.parts:
        op = olds.get(m.parts.get(p.key))
        if op is None or not p.key.startswith("주석"):
            continue
        ln, lo = period_labels(p), period_labels(op)
        old_tabs = [x[1] for x in op.items if x[0] == "t"]
        used: set = set()
        for t in (x[1] for x in p.items if x[0] == "t"):
            label = ln.get(t.id, "")
            tp = {j: v for j, v in _period_cols(t, label).items()
                  if v[0].startswith("전") and j not in done.get(t.id, ()) and (not interim or v[0] == "전기말")}
            if not tp:
                continue
            n_rows = max(1, sum(1 for i in range(len(t.rows)) if any(_isnum(v) for v in t.nums[i][1:])))
            best = None
            mt = m.tables.get(t.id)
            first = by_id.get(mt[0]) if mt and not label else None
            cands = ([first] + [q for q in old_tabs if q is not first]) if first is not None else old_tabs
            for q in cands:
                if best is not None and best[1] is first:         # 짝지은 작년 표로 짝이 지어지면 다른 표는 보지 않는다. 짝이 안 지어질 때만 찾는다
                    break                                         # (한 상장사 2025 주석9-4 는 짝지은 표가 틀려 작년 9-3 을 찾아야 했다)
                if label and q.id in used:
                    continue
                cols = _cross_cols(tp, _period_cols(q, lo.get(q.id, "")), len(t.header) - 1)
                if label and lo.get(q.id) in PERIOD_PAIRS.get(label, ()) and not cols:
                    cols = _col_pairs(t, q) or []
                if not cols:
                    continue
                rows = _pairs(row_keys(t), row_keys(q))
                if len(rows) / n_rows < 0.5:             # 올해 XBRL 「금융수익|이자수익(금융수익)」 ↔ 작년 「이자수익」
                    loose = _pairs([_loose_key(k) for k in row_keys(t)], [_loose_key(k) for k in row_keys(q)])
                    if len(loose) > len(rows):
                        rows = loose
                share = len(rows) / n_rows
                if (share >= 0.5 or len(rows) >= 3) and (best is None or (share, len(cols)) > (best[0], len(best[3]))):
                    if q is not first and not label and _agree(t, q, rows, cols) < 0.5:
                        continue                  # 짝지은 표도 기간 표시도 없이 이름만으로 찾은 다른 표는 금액이 반 넘게 맞을 때만 쓴다
                    best = (share, q, rows, cols)  # (한 상장사 2025 주석7-4 통화선도 표가 「유동항목 · 비유동항목 · 합계」 만 맞아 작년 7-1 과 짝지어졌다)
            if best is None:
                continue
            share, q, rows, cols = best
            used.add(q.id)
            _same_name_rows(t, q, rows, cols)
            _xbrl_rows(t, q, rows, cols)
            _alias_rows(t, q, rows)
            _ai_rows(t, q, rows, ai_pairs)
            labels = _labels(t)
            for a, b in cols:
                k10 = _scale(t, q, rows, a, b)
                for i in range(len(t.rows)):
                    v = t.nums[i][a]
                    if not _isnum(v):
                        continue
                    r = rows.get(i)
                    if r is None or not _isnum(q.nums[r][b]):
                        if v != 0 and share >= 0.5:          # 줄 이름이 반 넘게 겹친 표만 못 찾은 줄을 알린다(꼴이 다른 작년 표는 일부 줄만 짝짓는다)
                            lost.append({"table": t.id, "kind": "전기", "why": f"전기: 작년 보고서 {q.id} 에서 「{labels[i]}」 금액을 찾지 못함", "row": i})
                        continue
                    cid = f"전기|{t.id}|{labels[i]}#{_ref(labels, i)[1]}|{t.header[a]}#{_ref(t.header, a)[1]}"
                    if cid in have:
                        continue
                    have.add(cid)
                    out.append(_prior_check(cid, t, i, a, q, r, b, k10, tag, f"작년 {tag}{q.id}({lo.get(q.id)} 표) {q.rows[r][0]} · {q.header[b]}"))
    return out, lost


def calc_value(expr: str, vals: list[float]) -> float | None:
    """계산 검증의 식에 값을 넣어 계산한다. 식은 넣을 때(dsd_ai.apply) 숫자 · 사칙 · 괄호 · 항 자리만 있는지 검사했다. 0 으로 나누면 None."""
    import ast

    code = expr.format(*[f"({v!r})" for v in vals])
    try:      # MIN · MAX · ABS 는 엔진 규칙의 식에만 쓴다(엑셀 함수와 같은 이름, 12단계 이익준비금)
        return float(eval(compile(ast.parse(code, mode="eval"), "<계산>", "eval"), {"__builtins__": {}}, {"MIN": min, "MAX": max, "ABS": abs}))      # noqa: S307  검사한 식만 온다
    except ZeroDivisionError:
        return None


def evaluate(doc: Doc, checks: list[Check], prior: Doc | None = None, wtb: Doc | None = None, other: Doc | None = None) -> None:
    """검증마다 왼쪽 · 오른쪽 금액과 결과를 채운다. 단위가 다르면 큰 단위로 환산해 반올림하고 차이 1 을 허용한다.
    칸에 단위가 붙은 칸(「346,820천원」 「1,000원」)은 그 칸의 단위로 본다.
    허용 폭을 넘지만 차이가 단수 한도 이하면 단수 차이(minor)로 표시한다. 단수 한도는 천원 · 백만원 표이거나 단위를 바꿔 견준 검증만 MINOR 다.
    원 단위끼리는 반올림이 없으니 1원 차이도 FALSE 다(9단계 재평가: 원 단위 파일의 1원 차이가 노랑이었다).
    계산 검증(expr)은 항마다 원(또는 수량 · 비율)으로 바꿔 식을 계산하고 왼쪽 칸의 단위로 되돌려 견준다."""
    tabs = {t.id: t for t in doc.tables()}
    if prior is not None:
        tabs.update({PRIOR_ID + t.id: t for t in prior.tables()})
    if wtb is not None:
        tabs.update({"조서:" + t.id: t for t in wtb.tables()})
    if other is not None:
        tabs.update({PAIR_ID + t.id: t for t in other.tables()})
    for c in checks:
        lt = tabs[c.table]
        lu = lt.unit_at(c.r, c.c)
        if c.expr:
            vals = [tabs[tid].nums[r][k] * tabs[tid].unit_at(r, k) if _isnum(tabs[tid].nums[r][k]) else 0 for tid, r, k, _ in c.terms]
            v = calc_value(c.expr, vals)
            left = 0 if c.zero_left else lt.nums[c.r][c.c]
            c.left, c.right, c.unit, c.minor_limit, c.minor = left, (round(v / lu, 6) if v is not None else None), lu, 0, False
            if c.right is None:
                c.ok = False
            elif c.cmp:                              # 부등식 계산 검증(12단계 이익준비금 적립 ≥ 법정 최소액)
                d = c.left - c.right
                c.ok = (d <= c.tol + 1e-9) if c.cmp == "le" else (d >= -c.tol - 1e-9)
            else:
                c.ok = abs(c.left - c.right) <= c.tol + 1e-9
            continue
        if c.plain:
            scaled = c.left_div != 1 or any(abs(s) != 1 for *_, s in c.terms)
            right = sum(s * tabs[tid].nums[r][k] for tid, r, k, s in c.terms if _isnum(tabs[tid].nums[r][k]))
            left = lt.nums[c.r][c.c] / c.left_div
            c.left, c.right = (round(left), round(right)) if scaled else (round(left, 6), round(right, 6))
            c.tol = max(c.tol, 1) if scaled else c.tol
            c.unit = lu * c.left_div
            c.minor_limit = MINOR if (c.unit > 1 or scaled) else 0
            c.ok = abs(c.left - c.right) <= c.tol + 1e-9
            c.minor = not c.ok and abs(c.left - c.right) <= c.minor_limit + 1e-9
            continue
        units = {lu} | {tabs[tid].unit_at(r, k) for tid, r, k, _ in c.terms}
        big = max(units)
        scale = (lambda v, u: v * u / big) if len(units) > 1 else (lambda v, u: v)
        left = scale(lt.nums[c.r][c.c], lu)
        right = sum(s * scale(tabs[tid].nums[r][k], tabs[tid].unit_at(r, k)) for tid, r, k, s in c.terms if _isnum(tabs[tid].nums[r][k]))
        if len(units) > 1:
            left, right, c.tol = round(left), round(right), max(c.tol, 1)
        c.left, c.right, c.unit = round(left, 6), round(right, 6), big
        c.minor_limit = MINOR if (big > 1 or len(units) > 1) else 0
        if c.cmp:                                    # 부분 대사: 일부만 담은 표의 금액은 전체 과목보다 클 수 없다(11단계)
            d = c.left - c.right
            c.ok = (d <= c.tol + 1e-9) if c.cmp == "le" else (d >= -c.tol - 1e-9)
            c.minor_limit, c.minor = 0, False
            continue
        c.ok = abs(c.left - c.right) <= c.tol + 1e-9
        c.minor = not c.ok and abs(c.left - c.right) <= c.minor_limit + 1e-9
