"""감리지적 유형 검사(12단계, 2026-10-19). 한공회 · 금감원 감리지적사례에서 보고서 안의 숫자와 표만으로 볼 수 있는 것을 고른다.

| 검사 | 감리지적사례 | 결과 |
|---|---|---|
| 특수관계자 대여금 · 차입금 잔액이 당기말과 전기말에 다른데 기중 자금거래 표나 문장이 없다 | KICPA-2025-37 · 38, KICPA-2024-36 (일반기업회계기준 25.6, K-IFRS 1024 문단 18) | 알림 |
| 특수관계자에게 제공한 보증의 금액이 특수관계자 주석과 보증 주석에서 다르다 | KICPA-2024-37 · 38 (일반기업회계기준 25.9, 14.21) | 확인 |
| 특수관계자에게 제공한 보증이 한 주석에만 있다 | KICPA-2024-37 · 40, KICPA-2025-44 | 알림 |
| 담보로 제공한 자산의 장부금액이 그 자산의 재무상태표 금액보다 크다 | KICPA-2025-42 · 43 (일반기업회계기준 10.48) | 부분 대사(≤) |

연결은 뜻으로만 짓는다. 특수관계자 주석과 보증 주석은 상대방 이름이 같은 줄끼리, 담보 표와 재무상태표는 자산 이름이 같은 과목끼리 잇고,
금액이 같다는 것으로 잇지 않는다(4단계 대표 반려). 담보 표에서 같은 자산을 담보권자마다 줄을 나눠 적는 회사가 많아 줄을 더하지 않고 줄마다 견준다.
"""
from __future__ import annotations

import re

from .base import norm
from .dsd_grid import Doc, Table

RP_NOTE = re.compile(r"특수관계")
FUND = ("대여금", "차입금", "가지급금", "가수금")
_FLOW = re.compile(r"대여(?!금)|회수|차입(?!금)|상환|자금거래|자금\s*거래|자금대여|자금차입|출자|증자|기초|증가|감소|변동")
_FLOW_CELL = re.compile(r"자금대여|자금차입|자금거래|대여(?!금)|회수|차입(?!금)|상환")
_COMPANY = re.compile(r"\(주\)|㈜|주식회사|\(유\)|유한회사|\(재\)|재단법인|\(사\)|사단법인|\(합\)|합자회사|\*+\d*|\(\*\d*\)|\[[^\]]*\]")
GENERIC = {"대표이사", "임원", "주주", "종업원", "합계", "계", "소계", "기타", "관계기업", "종속기업", "지배기업", "특수관계자", "회사", "당사",
           "주요경영진", "개인", "최대주주", "임직원", "기타특수관계자", "공동기업", "기타의특수관계자", "임원등", "대표이사등", "-", ""}
LEGEND = "감리지적 유형"


def _isnum(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _labels(t: Table) -> list[str]:
    return t.labels or [r[0] for r in t.rows]


def name_key(s) -> str:
    """상대방 이름 맞추기: 법인 표시 · 공백 · 각주 · 끝의 쌍점을 뗀다."""
    k = _COMPANY.sub("", norm(s)).rstrip(":：")
    return re.sub(r"\((?:구|舊)[^)]*\)|\(.*?\)$", "", k)


def _notes(doc: Doc, pat: re.Pattern) -> list:
    return [p for p in doc.parts if p.key.startswith("주석") and pat.search(norm(p.title)[:40])]


def _tables(p) -> list[Table]:
    return [x[1] for x in p.items if x[0] == "t" and x[1].kind != "문장"]


def _paras(p) -> list[str]:
    return [x[1] for x in p.items if x[0] == "p"]


def _period_of(text: str) -> str | None:
    t = norm(text)
    cur, prev = re.search(r"당기|당반기|당분기|당기말", t), re.search(r"전기|전반기|전분기|전기말", t)
    if cur and not prev:
        return "당기"
    if prev and not cur:
        return "전기"
    return None


def _total_row(t: Table) -> int | None:
    labs = [norm(x) for x in _labels(t)]
    return next((i for i in range(len(labs) - 1, -1, -1) if labs[i] in ("합계", "계", "총계", "합계금액")), None)


# ---------------------------------------------------------------- 1. 특수관계자 자금거래
def _fund_totals(t: Table, period_hint: str | None) -> dict:
    """특수관계자 채권 · 채무 표에서 자금 성격 과목(대여금 · 차입금 …)의 기간별 합. {(과목, 기간): 원}.
    과목이 줄 이름에 있으면(「대표이사 단기대여금」 줄) 그 줄만 더하고, 줄 이름에 없을 때만 머리줄에 과목이 든 열(「대여금 당기말」)을 더한다.
    두 가지를 함께 더하면 같은 금액을 두 번 센다(DART 00679059: 머리줄 「채권(단기대여금) 당기」 에 미수수익 줄도 있었다)."""
    out: dict = {}
    labs = _labels(t)
    total = _total_row(t)
    words = [" ".join(c for c, v in zip(r, t.nums[i]) if v is None) for i, r in enumerate(t.rows)]      # 줄의 글자 칸(특수관계자 · 계정과목)
    by_row = [(i, next(f for f in FUND if f in norm(x))) for i, x in enumerate(words) if i != total and any(f in norm(x) for f in FUND)]
    if by_row:
        for i, w in by_row:
            for j, h in enumerate(t.header):
                per = (_period_of(h) or period_hint) if j else None
                if per and _isnum(t.nums[i][j]) and not re.search(r"증가|감소|대여(?!금)|회수|차입(?!금)|상환", norm(h)):
                    out[(w, per)] = out.get((w, per), 0) + t.nums[i][j] * t.unit
        return out
    for j, h in enumerate(t.header):
        w = next((f for f in FUND if f in norm(h)), None) if j else None
        per = (_period_of(h) or period_hint) if w else None
        if per is None:
            continue
        if total is not None and _isnum(t.nums[total][j]):
            v = t.nums[total][j]
        else:
            v = sum(t.nums[i][j] for i in range(len(t.rows)) if _isnum(t.nums[i][j]) and norm(labs[i]) not in ("합계", "계", "소계"))
        out[(w, per)] = out.get((w, per), 0) + v * t.unit
    return out


def fund_alerts(doc: Doc) -> list[dict]:
    out = []
    for p in _notes(doc, RP_NOTE):
        tabs = _tables(p)
        flow = [t for t in tabs if _FLOW.search(norm(" ".join(t.header) + t.caption)) or any(_FLOW_CELL.search(norm(c)) for r in t.rows for c in r[:3])]      # 거래내용 열의 「자금대여, 이자수익」(공개 원문 186)
        # 거래 내역 표에 자금 과목을 손익 거래와 함께 적은 것도 공시다(DART 01472754: 매입 · 매출 줄 사이의 「장단기대여금」, 공개 원문 181: 공사수익 · 이자비용 줄 사이의
        # 「단기차입금」). 자금 과목만 있는 표는 제목이 「거래내역」 이어도 잔액 표다(두원상선 2025 주석11)
        flow += [t for t in tabs if re.search(r"거래", norm(_title(t))) and not re.search(r"잔액|채권|채무", norm(_title(t)))
                 and any(f in norm(c) for r in t.rows for c in r[:3] for f in FUND)
                 and any(re.search(r"수익|비용|매출|매입|수수료|임차료|임대료|이자", norm(c)) for r in t.rows for c in r[:3])]
        said = any(re.search(r"자금거래|자금\s*거래|자금의?\s*(대여|차입)|(대여|차입)\s*및\s*(회수|상환)", x) for x in _paras(p))
        if flow or said:
            continue
        got: dict = {}
        for t in tabs:
            hint = _period_of(t.caption) or _period_of(t.header[0] if t.header else "")
            for k, v in _fund_totals(t, hint).items():
                got[k] = got.get(k, 0) + v
        moved = [(w, got[(w, "당기")], got[(w, "전기")]) for w in FUND if (w, "당기") in got and (w, "전기") in got and abs(got[(w, "당기")] - got[(w, "전기")]) >= 1]
        if moved:
            why = "; ".join(f"{w} 당기말 {a:,.0f}원 · 전기말 {b:,.0f}원" for w, a, b in moved)
            out.append({"what": f"{LEGEND}: 특수관계자 대여금 · 차입금 잔액이 바뀌었는데 기중 자금거래 공시가 없음", "n": len(moved),
                        "why": f"{p.key}: {why}. 기초 · 기말 잔액만 적고 기중 대여 · 회수 · 차입 · 상환 금액을 적지 않은 꼴이다"
                               f"(일반기업회계기준 25.6, K-IFRS 1024 문단 18, 감리지적 KICPA-2025-37 · 38)"})
    return out


# ---------------------------------------------------------------- 2. 특수관계자에게 제공한 보증
_GIVEN = re.compile(r"제공한(?!자)|제공하고|제공하는(?!자)|제공받는자|제공받은자|피보증|보증받는|보증대상|채무자")
_TAKEN = re.compile(r"제공받고|제공받은(?!자)|받은(?!자)|로부터|받고있|제공자|제공한자|제공하는자|보증인|보증제공자")
_AMOUNT = re.compile(r"보증금액|보증한도|한도금액|보증제공금액|채권최고|설정금액|금액")


def _title(t: Table) -> str:
    """표 제목. 「(*) …」 로 시작하는 글은 앞 표의 각주라 이 표의 제목이 아니다(DART 00318088: 거래 표 앞 각주의 현지금융 보증 문장)."""
    c = t.caption.strip()
    return "" if re.match(r"^\(?\*", c) else c


def _guarantee_given(t: Table) -> bool:
    """타인(특수관계자)에게 제공한 보증 표. 회사가 받은 보증 표가 훨씬 많아(서울보증보험 · 대표이사 연대보증) 「받은 · 로부터 · 제공자」 가 있으면 뺀다."""
    text = norm(_title(t) + " " + " ".join(t.header))
    if "보증" not in text:
        return False
    return bool(_GIVEN.search(text)) and not _TAKEN.search(text)


def _amount_col(t: Table) -> int | None:
    """보증 금액 열. 당기 금액 열이 하나뿐일 때만 고른다. 실행금액 · 보증한도 · 보증금액처럼 금액 열이 여럿이면 두 주석의 어느 열끼리
    같아야 하는지 이름만으로 정할 수 없다(한 상장사 2025: 특수관계자 주석의 「보증한도」 와 보증 주석의 「보증금액」 이 같은 금액)."""
    cols = [j for j, h in enumerate(t.header) if j and _AMOUNT.search(norm(h)) and any(_isnum(r[j]) for r in t.nums) and _period_of(h) != "전기"]
    return cols[0] if len(cols) == 1 else None


def _table_period(t: Table) -> str:
    return _period_of(_title(t)) or _period_of(t.header[0] if t.header else "") or "당기"


def _current(t: Table, rows: list[int]) -> bool:
    """그 상대방에게 당기말 보증이 남아 있는가. 당기 · 전기 열을 둔 표에서 당기 금액이 모두 0 이면 끝난 보증이다(공개 원문 104: 당기 「-」 · 전기 4,000,000)."""
    if _table_period(t) == "전기":
        return False
    cols = [j for j, h in enumerate(t.header) if j and _period_of(h) == "당기"]
    if not cols:
        return True
    vals = [t.nums[i][j] for i in rows for j in cols]
    return not vals or any(not _isnum(v) or v for v in vals)


def consolidated(doc: Doc) -> bool:
    """연결 보고서인가. 본표 제목에 「연결」 이 없는 원문도 있어(공개 원문 119) 주석 글의 「연결회사 · 연결실체」 도 센다."""
    if any("연결" in norm(p.title) for p in doc.parts if not p.key.startswith("주석")):
        return True
    text = " ".join(x[1] for p in doc.parts if p.key.startswith("주석") for x in p.items if x[0] == "p")
    group, own = len(re.findall(r"연결회사|연결실체|연결기업", text)), len(re.findall(r"당사", text))
    return group >= 10 and group > own                  # 별도 보고서도 종속기업 주석에 「연결회사」 를 몇 번 쓴다(공개 원문 016 · 174)


def _party_col(t: Table) -> int:
    for j, h in enumerate(t.header):
        if re.search(r"제공받는자|제공받은자|피보증|보증받는|보증대상|채무자|특수관계자|회사명|명칭|거래처", norm(h)):
            return j
    return 0


def _parties(t: Table) -> dict:
    """{상대방 이름: [줄 번호]}. 이름이 아닌 칸(합계 · 대표이사 · 숫자)은 뺀다. 「〃」 · 「"」 는 윗줄 이름이다."""
    j = _party_col(t)
    out: dict = {}
    last = ""
    for i, r in enumerate(t.rows):
        raw = r[j] if j < len(r) else ""
        if norm(raw) in ('"', "〃", "''", "″"):
            raw = last
        last = raw
        k = name_key(raw)
        if k in GENERIC or len(k) < 2 or re.fullmatch(r"[\d,.\-()]+", k):
            continue
        out.setdefault(k, []).append(i)
    return out


def guarantee_checks(doc: Doc) -> tuple[list, list[dict]]:
    from .dsd_links import Check

    rp_parts = _notes(doc, RP_NOTE)
    rp_ids = {p.key for p in rp_parts}
    rp_given = [t for p in rp_parts for t in _tables(p) if _guarantee_given(t)]
    other_given = [t for p in doc.parts if p.key.startswith("주석") and p.key not in rp_ids for t in _tables(p) if _guarantee_given(t)]
    checks, alerts = [], []
    other_names: dict = {}
    for t in other_given:
        for k, rows in _parties(t).items():
            other_names.setdefault(k, []).append((t, rows))
    other_text = norm(" ".join(x for p in doc.parts if p.key.startswith("주석") and p.key not in rp_ids for x in _paras(p))
                      + " ".join(c for p in doc.parts if p.key.startswith("주석") and p.key not in rp_ids for t in _tables(p) for r in t.rows for c in r))
    missing = []
    for t in rp_given:
        a = _amount_col(t)
        for k, rows in _parties(t).items():
            if k not in other_names:
                if k not in name_key(other_text) and k not in other_text and _current(t, rows):
                    missing.append(f"{t.id} {k}")
                continue
            if a is None or len(rows) != 1 or not _isnum(t.nums[rows[0]][a]):
                continue
            terms = []
            for q, qrows in other_names[k]:
                if _table_period(q) != _table_period(t):
                    continue
                b = _amount_col(q)
                if b is None:
                    continue
                terms += [(q.id, i, b, 1) for i in qrows if _isnum(q.nums[i][b])]
            if not terms:
                continue
            r = rows[0]
            checks.append(Check(f"감리-보증|{t.id}|{k}", "주석 간", "레퍼", t.id, r, a, terms, None,
                                " + ".join(f"{q} {_labels(doc.table(q))[i]}" for q, i, _, _ in terms), "규칙",
                                "특수관계자에게 제공한 보증 = 보증(우발부채) 주석의 같은 상대방 보증 금액(일반기업회계기준 25.9 · 14.21, K-IFRS 1024 문단 18(2), "
                                "감리지적 KICPA-2024-37 · 38: 특수관계자 보증 미기재 · 과소기재)",
                                when="두 주석이 같은 금액(보증 한도 또는 실행액)을 적었다"))
    if missing:
        alerts.append({"what": f"{LEGEND}: 특수관계자에게 제공한 보증이 보증(우발부채) 주석에 없음", "n": len(missing),
                       "why": "; ".join(missing[:20]) + ". 타인에게 제공한 보증은 자원 유출 가능성이 낮아도 주석에 적는다(일반기업회계기준 14.21, 감리지적 KICPA-2025-44)"})
    # 보증 주석에서 특수관계자에게 제공한 보증이 특수관계자 주석에 없음
    rp_names = set()
    rp_blob = ""
    for p in rp_parts:
        for t in _tables(p):
            for r in t.rows:
                for c in r[:3]:
                    k = name_key(c)
                    if k not in GENERIC and len(k) >= 2 and not re.fullmatch(r"[\d,.\-()]+", k):
                        rp_names.add(k)
        rp_blob += norm(" ".join(_paras(p)) + " ".join(t.caption + " ".join(c for r in t.rows for c in r) for t in _tables(p)))
    rp_guaranteed = {k for t in rp_given for k in _parties(t)}
    lost = []
    group = consolidated(doc)
    for k, places in other_names.items():
        if k not in rp_names or k in rp_guaranteed:
            continue
        t0, rows0 = places[0]
        if RP_NOTE.search(norm(_title(t0))):         # 보증 주석이 이미 특수관계자 보증으로 적었다(공개 원문 193: 「특수관계자의 차입을 위하여 제공한 지급보증(주석 18 참조)」)
            continue
        if group and any("종속" in norm(c) for i in rows0 for c in t0.rows[i]):      # 연결 보고서에서 종속회사에 준 보증은 연결 안의 거래다
            continue
        if not _current(t0, rows0):
            continue
        near = [m.start() for m in re.finditer(re.escape(k), rp_blob)]
        if any("보증" in rp_blob[max(0, s - 80): s + 120] for s in near):
            continue
        lost.append(f"{places[0][0].id} {k}")
    if lost:
        alerts.append({"what": f"{LEGEND}: 보증 주석의 특수관계자 보증이 특수관계자 주석에 없음", "n": len(lost),
                       "why": "; ".join(lost[:20]) + ". 특수관계자에게 제공한 보증은 특수관계자 주석에도 적는다(일반기업회계기준 25.9, K-IFRS 1024 문단 18(2), 감리지적 KICPA-2024-37 · 40)"})
    return checks, alerts


# ---------------------------------------------------------------- 3. 담보 제공 자산 장부금액 ≤ 재무상태표
_PLEDGE = re.compile(r"담보")
_PLEDGE_NOT = re.compile(r"제공받|받은|받고|로부터|보유하고있는담보|수취")
_BOOK = re.compile(r"장부금액|장부가액|장부가|순장부")
_ASSET_COL = re.compile(r"담보제공자산|제공자산|담보자산|자산명|자산|물건|담보물|과목|계정")
PPE = ("토지", "건물", "구축물", "기계장치", "차량운반구", "공구와기구", "비품", "시설장치", "건설중인자산", "선박", "항공기")
_SPLIT = re.compile(r"[,，·ㆍ/、&]|및|와|과(?=[가-힣]{2})")


def _asset_names(text: str) -> tuple[list[str], list[str]]:
    """담보 자산 칸의 과목 이름. (괄호 밖 이름, 괄호 안 이름). 「조치원 공장(토지,건물)」 은 괄호 안 이름으로 찾는다."""
    t = re.sub(r"\(\*\d*\)|\(주\d*\)", "", norm(text))
    inner = [x for g in re.findall(r"\(([^)]*)\)", t) for x in _SPLIT.split(g) if x and not re.search(r"포함|일부|등$", x)]
    outer = [x for x in _SPLIT.split(re.sub(r"\([^)]*\)", "", t)) if x]
    return outer, inner


def _bs_cells(bs: Table, names: list[str], j: int, extra: tuple = ()) -> list[tuple] | None:
    """자산 이름마다 재무상태표 줄. 하나라도 못 찾으면 None.
    - 같은 이름 줄이 여럿이면(매도가능증권 유동 · 비유동, DART 00227041) 모두 더한다.
    - 유형자산 종류(토지 · 건물 …)는 재무상태표에 그 줄이 없으면 유형자산과 투자부동산 줄로 묶는다(토지 · 건물이 투자부동산인 회사, 공개 원문 018).
    - 자기주식처럼 음수로 적은 과목은 크기로 견준다(공개 원문 168)."""
    from .dsd_appropriation import key

    keys = [key(x) for x in _labels(bs)]
    rows: list[int] = []
    for n in list(names) + list(extra):
        hit = [x for x, k in enumerate(keys) if k == n and _isnum(bs.nums[x][j])]
        if not hit and n in PPE:
            hit = [x for x, k in enumerate(keys) if k in ("유형자산", "투자부동산") and _isnum(bs.nums[x][j])]
        if not hit:
            return None
        rows += [x for x in hit if x not in rows]
    return [(bs.id, i, j, -1 if bs.nums[i][j] < 0 else 1) for i in rows]


def pledge_checks(doc: Doc) -> list:
    from .dsd_links import Check, period_col

    bs = doc.table("재무상태표")
    if bs is None:
        return []
    out = []
    for p in doc.parts:
        if not p.key.startswith("주석"):
            continue
        before = ""
        for x in p.items:
            if x[0] == "p":
                before = x[1]
                continue
            t = x[1]
            lead, before = before, ""
            if t.kind == "문장":
                continue
            text = norm(t.caption + " " + " ".join(t.header))
            if not _PLEDGE.search(text) or _PLEDGE_NOT.search(norm(t.caption)):
                continue
            books = [j for j, h in enumerate(t.header) if j and _BOOK.search(norm(h)) and not re.search(r"감정", norm(h))]
            if not books:
                continue
            ac = next((j for j, h in enumerate(t.header) if j not in books and _ASSET_COL.search(norm(h)) and not re.search(r"금액|가액", norm(h))), 0)
            total = _total_row(t)
            names_of = []
            last = ""
            for i, r in enumerate(t.rows):
                raw = r[ac] if ac < len(r) else ""
                if norm(raw) in ('"', "〃", "''", "″"):
                    raw = last
                last = raw or last
                names_of.append(raw)
            for i, r in enumerate(t.rows):
                if i == total:
                    continue
                for b in books:
                    if not _isnum(t.nums[i][b]) or t.nums[i][b] <= 0:
                        continue
                    span = [names_of[i]]                  # 장부금액 칸이 아래 줄과 세로로 묶였으면(아래 줄 칸이 빈칸) 그 줄의 자산도 이 금액에 든다(DART 01660465)
                    k = i + 1
                    while k < len(t.rows) and k != total and not str(t.rows[k][b]).strip() and str(t.rows[k][ac] if ac < len(t.rows[k]) else "").strip():
                        span.append(names_of[k])
                        k += 1
                    per = _period_of(t.header[b]) or _period_of(t.caption) or _period_of(lead) or "당기"
                    j = period_col(bs, per)
                    if j is None:
                        continue
                    outer = [n for raw in span for n in _asset_names(raw)[0]]
                    inner = [n for raw in span for n in _asset_names(raw)[1]]
                    if not outer and not inner:
                        continue
                    extra = ("투자부동산",) if any("투자부동산" in n for n in inner) else ()
                    terms = _bs_cells(bs, outer, j, extra) or (_bs_cells(bs, inner, j) if inner else None)
                    if not terms:
                        continue
                    out.append(Check(f"감리-담보|{t.id}|{i}|{b}", "주석-재무제표", "레퍼", t.id, i, b, terms, None,
                                     " + ".join(f"재무상태표 {_labels(bs)[x[1]]}" for x in terms), "규칙",
                                     "담보로 제공한 자산의 장부금액은 그 자산의 재무상태표 금액을 넘을 수 없다(일반기업회계기준 10.48, "
                                     "감리지적 KICPA-2025-42 · 43: 담보제공자산 과다 · 누락 기재). 재무상태표에 차감 표시한 과목은 크기로 견준다", cmp="le"))
    return out


def checks(doc: Doc) -> list:
    got, _ = guarantee_checks(doc)
    return got + pledge_checks(doc)


def alerts(doc: Doc) -> list[dict]:
    """원문 대조에 붙이는 알림(공시가 빠졌을 수 있는 곳)."""
    _, al = guarantee_checks(doc)
    return fund_alerts(doc) + al
