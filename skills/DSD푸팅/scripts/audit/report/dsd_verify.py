"""DSD 푸팅: 고칠 칸의 근거 계산, 독립 검증 반영, 판정자료(2026-10-18, 11단계).

판정이 「이 칸이 틀렸고 맞는 숫자는 N 이다」 라고 적으면(findings 의 fix · correct · evidence) 엔진이 근거 칸의 값을 계산해
맞는 숫자를 받치는지 본다. 근거 칸은 검증의 두 칸이 아닌 세 번째 칸이어야 한다(작년 보고서 · 다른 주석 · 정산표 · 함께 낸 보고서).
받치지 못하면 판정은 그대로 두고 「고칠 쪽 미정」 으로 적는다. 엔진이 고칠 쪽을 정하지는 않는다.

독립 검증: 판정을 쓴 에이전트와 다른 에이전트가 판정자료(dsd_판정자료.md)를 읽고 판정마다 다른 설명을 지워 본 결과를
결과 폴더의 판정검증.json 에 적는다. 엔진이 읽어 유지 · 바꿈을 엑셀 「볼 것」 의 검증 열과 표지에 적고, 바꿈이면 판정을 바꾼다.

    판정검증.json: [{"id": "<검증 id>", "result": "유지" | "바꿈", "why": "…",
                    "verdict": "<바꿈일 때 새 판정>", "cause": "…", "fix": {칸}, "correct": 숫자, "evidence": [{칸}, …]}]
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import dsd_links
from .dsd_grid import Doc
from .dsd_links import PAIR_ID, PRIOR_ID, Check, _isnum, _labels

WTB_ID = "조서:"
REVIEW = "판정검증.json"
PACK = "dsd_판정자료.md"
RESULTS = ("유지", "바꿈")
VERDICTS = ("숫자 오류", "표시 오류", "설명 부족", "보고서 불일치", "작년 보고서 불일치", "식 고침", "확인", "걸지 않음", "엔진 판독", "설명됨")


def _fmt(v: float) -> str:
    return f"{v:,.0f}" if abs(v - round(v)) < 1e-6 else f"{v:,.4f}".rstrip("0").rstrip(".")


def resolve(ref: dict, doc: Doc, prior: Doc | None = None, wtb: Doc | None = None, other: Doc | None = None):
    """칸 이름을 (앞머리 붙은 표 id, 줄, 열, 표) 로 푼다. 작년: · 조서: · 짝: 앞머리면 그 문서에서 찾는다."""
    if not isinstance(ref, dict) or not ref.get("table"):
        return None
    tid = str(ref["table"])
    for pre, d in ((PRIOR_ID, prior), (WTB_ID, wtb), (PAIR_ID, other)):
        if tid.startswith(pre):
            if d is None:
                return None
            got = dsd_links._resolve(d, dict(ref, table=tid[len(pre):], exact=_exact(ref, tid[len(pre):])), None)
            return (pre + got[0].id, got[1], got[2], got[0]) if got else None
    got = dsd_links._resolve(doc, dict(ref, exact=_exact(ref, tid)), None)
    return (got[0].id, got[1], got[2], got[0]) if got else None


def _exact(ref: dict, base: str) -> bool:
    """재무제표 본표의 「당기」 「전기」 만 기간 열 이름으로 찾고 나머지 열 이름은 글자 그대로 찾는다(dsd_ai._ref_of 와 같다)."""
    b = base.lstrip("②③④")
    return not (not b.startswith("주석") and not b.startswith("자본변동표") and ref.get("col") in ("당기", "전기"))


def cell_name(tid: str, t, r: int, k: int) -> str:
    return f"{tid} {_labels(t)[r]} · {t.header[k]}".strip(" ·")


def _won(t, r: int, k: int):
    v = t.nums[r][k]
    return v * t.unit_at(r, k) if _isnum(v) else None


def apply_fix(c: Check, note: dict, doc: Doc, prior: Doc | None = None, wtb: Doc | None = None, other: Doc | None = None) -> None:
    """판정의 고칠 칸 · 맞는 숫자 · 근거 칸을 검증에 붙이고 근거를 계산해 c.fix_note 에 적는다."""
    if not note.get("fix"):
        return
    got = resolve(note["fix"], doc, prior, wtb, other)
    if got is None:
        c.fix_cell, c.correct, c.fix_note = None, None, "고칠 쪽 미정: 고칠 칸을 보고서에서 찾지 못했다"
        return
    tid, r, k, t = got
    c.fix_cell = (tid, r, k)
    c.correct = float(note["correct"]) if isinstance(note.get("correct"), (int, float)) and not isinstance(note.get("correct"), bool) else None
    if c.correct is None:
        c.fix_note = "고칠 쪽 미정: 맞는 숫자를 적지 않았다"
        return
    own = {(c.table, c.r, c.c)} | {tuple(x[:3]) for x in c.terms}
    cur = t.nums[r][k]
    if isinstance(cur, (int, float)) and cur and c.correct and abs(abs(c.correct) - abs(cur)) <= 0.5 and (c.correct > 0) != (cur > 0):
        c.fix_note = _sign_only(c, note, doc, prior, wtb, other)
        return
    want = c.correct * t.unit_at(r, k)
    vals, why = [], []
    for e in note.get("evidence") or []:
        g = resolve(e, doc, prior, wtb, other)
        if g is None:
            why.append(f"근거 칸 「{e.get('table')} {e.get('row')} · {e.get('col')}」 을 찾지 못했다" if isinstance(e, dict) else "근거 칸 꼴이 틀렸다")
            continue
        if (g[0], g[1], g[2]) in own:
            why.append(f"「{cell_name(g[0], g[3], g[1], g[2])}」 은 이 검증의 칸이라 근거가 될 수 없다")
            continue
        w = _won(g[3], g[1], g[2])
        if w is None:
            why.append(f"「{cell_name(g[0], g[3], g[1], g[2])}」 에 숫자가 없다")
            continue
        vals.append((w, cell_name(g[0], g[3], g[1], g[2]), g[3].unit_at(g[1], g[2])))
    tol = 0.5 * max([t.unit_at(r, k)] + [x[2] for x in vals])
    hit = next((x for x in vals if abs(x[0] - want) <= tol + 1e-6), None)
    if hit is not None:
        c.fix_note = f"근거 확인: 「{hit[1]}」 {_fmt(hit[0] / t.unit_at(r, k))}"
    elif len(vals) > 1 and abs(sum(x[0] for x in vals) - want) <= tol * len(vals) + 1e-6:
        c.fix_note = "근거 확인: " + " + ".join(f"「{x[1]}」" for x in vals) + f" = {_fmt(sum(x[0] for x in vals) / t.unit_at(r, k))}"
    elif not note.get("evidence"):
        c.fix_note = "고칠 쪽 미정: 근거 칸을 적지 않았다(검증의 두 칸 말고 세 번째 근거가 필요하다)"
    else:
        shown = ", ".join(f"「{x[1]}」 {_fmt(x[0] / t.unit_at(r, k))}" for x in vals[:3])
        c.fix_note = "고칠 쪽 미정: " + ("; ".join(why) if why and not vals else f"근거 칸 값({shown})이 맞는 숫자 {_fmt(c.correct)} 와 다르다")


def _sign_only(c: Check, note: dict, doc: Doc, prior: Doc | None, wtb: Doc | None, other: Doc | None) -> str:
    """부호만 바꾸는 고침의 근거. 다른 표는 같은 금액을 반대 부호로 적을 수 있어(재무상태표는 결손금을 양수로 적고 빼고,
    자본변동표 · 결손금처리계산서는 음수로 적는다) 작년 보고서의 같은 줄 부호만 근거로 받는다(실제 회사 자료 결손금, 11단계 재평가)."""
    for e in note.get("evidence") or []:
        if not (isinstance(e, dict) and str(e.get("table", "")).startswith(PRIOR_ID)):
            continue
        g = resolve(e, doc, prior, wtb, other)
        w = _won(g[3], g[1], g[2]) if g is not None else None
        if w:
            name = cell_name(g[0], g[3], g[1], g[2])
            if (w > 0) == (c.correct > 0):
                return f"근거 확인(부호): 작년 보고서 「{name}」 도 {_fmt(w / g[3].unit_at(g[1], g[2]))} 로 같은 부호다"
            return f"고칠 쪽 미정: 작년 보고서 「{name}」 은 {_fmt(w / g[3].unit_at(g[1], g[2]))} 로 맞는 숫자와 부호가 다르다"
    return "고칠 쪽 미정: 부호만 바꾸는 고침이다. 다른 표는 같은 금액을 반대 부호로 적을 수 있어 작년 보고서의 같은 줄이 근거여야 한다"


def apply_fixes(checks: list[Check], notes: list[dict], doc: Doc, prior: Doc | None = None, wtb: Doc | None = None, other: Doc | None = None) -> None:
    by = {dsd_links.idk(c.id): c for c in checks}
    for x in notes or []:
        c = by.get(dsd_links.idk(x.get("id", "")))
        if c is not None:
            apply_fix(c, x, doc, prior, wtb, other)


def load_review(path: Path) -> list[dict]:
    path = Path(path)
    if not path.exists():
        return []
    got = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(got, dict):
        got = got.get("items") or []
    return [x for x in got if isinstance(x, dict)]


def apply_review(checks: list[Check], items: list[dict], doc: Doc, prior: Doc | None = None, wtb: Doc | None = None,
                 other: Doc | None = None) -> list[str]:
    """독립 검증 결과를 검증에 반영한다. 문제 목록(없는 id, 결과 · 판정 이름이 틀림)을 돌려준다."""
    by = {dsd_links.idk(c.id): c for c in checks}
    problems = []
    for n, x in enumerate(items, 1):
        c = by.get(dsd_links.idk(x.get("id", "")))
        res = x.get("result")
        if c is None:
            problems.append(f"판정검증 {n}번째: 검증 id 「{x.get('id')}」 가 없다")
            continue
        if res not in RESULTS or not str(x.get("why", "")).strip():
            problems.append(f"판정검증 {n}번째: result({' · '.join(RESULTS)})와 why 를 적어 주십시오")
            continue
        if res == "바꿈" and x.get("verdict") not in VERDICTS:
            problems.append(f"판정검증 {n}번째: 바꿈이면 verdict({' · '.join(VERDICTS)})를 적어 주십시오")
            continue
        c.verified, c.verify_why = res, str(x["why"]).strip()
        if res == "바꿈":
            before = c.finding
            if c.when in (dsd_links.DISPLAY, dsd_links.EXPLAIN, dsd_links.LAST_YEAR, "판정: 확인할 차이"):
                c.when = ""
            c.dropped = ""
            dsd_links.apply_finding(c, {"verdict": x["verdict"], "why": c.verify_why, "cause": x.get("cause")})
            if before:
                c.verify_why += f" (처음 판정: {before[:80]})"
        if x.get("fix"):
            apply_fix(c, x, doc, prior, wtb, other)
    return problems


BUNDLE_CELLS = 12      # 근거 묶음의 줄마다 적는 칸 수. 넓은 표(특수관계자 거래 39열)는 이 칸만큼만 적고 검증의 열과 끝 열은 늘 넣는다
BUNDLE_LINES = 18      # 근거 묶음의 줄 수(2026-10-23: 작년 같은 표의 합계 · 이웃 줄을 더하며 12 → 18)
PRIOR_NEAR = 2         # 작년 같은 표에서 짝지은 줄 위아래로 함께 적는 줄 수
PARA_LINES = 4         # 근거 묶음에 싣는 올해 주석 문장 수(2026-10-23)
PRIOR_PARA_LINES = 3   # 작년 주석 문장 수
PARA_WIDTH = 220       # 문장 하나의 글자 수(넘으면 맞은 낱말 앞뒤만)
# 줄 이름에서 문장을 고를 때 쓰지 않는 낱말(기간 · 합계 · 금액 이름)
_STOP = {"합계", "소계", "총계", "당기", "전기", "당기말", "전기말", "당반기", "전반기", "당분기", "전분기", "반기말", "기초", "기말", "금액", "공시금액",
         "장부금액", "누적", "3개월", "주석", "구분", "내역", "기타", "증가", "감소", "변동", "당기중", "전기중", "공시", "계"}

# 판정자료 맨 앞 한 화면(2026-10-23 분석 6.4). 판정 · 독립 검증 에이전트가 SKILL.md 를 열지 않고 적게 꼴과 순서를 싣는다
FORMAT = [
    "## 판정 쓰는 법",
    "",
    "판정은 연결.json 의 findings(전기 대사 차이는 prior)에 더하고 python -m audit dsd foot <dsd> --links 연결.json … 으로 다시 돌린다.",
    '- findings: {"id": "<아래 ## 줄의 검증 id>", "verdict": "숫자 오류", "why": "원인 칸, 두 금액, 어느 숫자가 틀렸고 맞는 숫자는 무엇인지, 근거 문단", '
    '"cause": "원인 한 줄(같은 원인의 검증끼리 같은 글)"}.',
    "- verdict: 숫자 오류(적힌 금액이 틀렸고 고칠 숫자가 있음) · 표시 오류(금액은 맞고 줄 · 열 이름, 기간 이름, 분류가 틀림) · 설명 부족(금액은 맞고 문장이 금액을 다 설명하지 못함) · "
    "작년 보고서 불일치(작년 숫자가 틀렸고 올해는 맞음) · 식 고침 · 확인 · 걸지 않음 · 엔진 판독. FALSE 로 세는 것은 숫자 오류뿐이다.",
    '- 숫자 오류는 고칠 칸 · 맞는 숫자 · 세 번째 근거를 적는다: "fix": "주석5-1:1:1", "correct": 1122000000(그 칸의 표시 단위), "evidence": ["재무상태표:6:1"]. '
    '근거는 검증의 두 칸이 아닌 칸이다. 작년 보고서는 {"table": "작년:주석5-1", "row": "줄 이름", "col": "열 이름"}, 정산표는 「조서:」, 함께 낸 보고서는 「짝:」. '
    "어느 쪽이 맞는지 근거가 없으면 fix 를 적지 않는다. 부호만 다른 차이는 표시 오류부터 보고, 부호 고침은 작년 보고서의 같은 줄만 근거가 된다.",
    '- prior(전기 대사): {"id": "전기|…", "verdict": "불일치 | 작년 불일치 | 설명됨 | 걸지 않음", "why": "…"}.',
    '- 「확인」 가운데 늘 나는 차이는 findings 에 "usual": "유형 이름" 을 함께 적는다(취득과 현금흐름표, 처분과 현금흐름표, 범주별 표와 본표의 범위, 배당 결의와 지급, 퇴직급여의 범위). '
    "독립 검증에서 빠지고 회계사가 유형마다 표본으로 본다. 재분류 공시 없는 전기 차이, FALSE 와 원인이 같은 차이, 같은 식이 다른 기간에는 맞는 차이, 그 유형에서 보통 나는 크기를 넘는 차이에는 "
    '적지 않는다(연결에 붙어 있으면 "usual": "" 로 뗀다).',
    "- why 는 회계사가 엑셀 칸에서 읽는 글이다. 주석 번호 · 과목 이름 · 금액으로 적고 문장마다 마침표로 끝낸다. 파일 · 키 이름과 규칙 번호는 적지 않는다.",
    "- 순서: 차이 설명 후보마다 「해당 없음」 이나 「이것으로 설명됨」 을 정한다. 금액이 같다는 것만으로 설명됐다고 하지 않는다. 근거 묶음으로 정할 수 없을 때만 원문을 연다. "
    "「회계사 확인」 으로 넘기지 않는다. 등급과 안 맞을 때 정하는 순서는 스킬 references/판정-근거.md.",
    '- 독립 검증(판정을 쓴 에이전트와 다른 에이전트): 판정검증.json 에 [{"id": "…", "result": "유지 | 바꿈", "why": "…", "verdict": "바꿈일 때 새 판정"}] 를 적고 foot 을 다시 돌린다. '
    "「독립 검증: 대상 아님」 은 건너뛴다. 규칙은 스킬 references/판정-검증.md.",
    "",
]


def _row_text(tid: str, t, r: int, focus: int | None = None) -> str:
    """표 한 줄: 「[표] 「줄 이름」: 열 값 · 열 값 …」. 열 이름의 공통 앞부분은 뗀다."""
    pre = dsd_links.col_prefix(t.header)
    cols = [j for j in range(1, len(t.header)) if _isnum(t.nums[r][j]) or (str(t.rows[r][j] or "").strip() and str(t.header[j]).strip())]      # 이름 없는 글자 열은 줄 이름이다
    if len(cols) > BUNDLE_CELLS:
        keep = {cols[-1]} | ({focus} if focus in cols else set())
        near = sorted(cols, key=lambda j: abs(j - (focus if focus is not None else 0)))
        keep |= set(near[:BUNDLE_CELLS - len(keep)])
        cols = sorted(keep)
    cells = []
    for j in cols:
        v = t.nums[r][j]
        text = _fmt(v) if _isnum(v) else str(t.rows[r][j]).strip()[:40]
        cells.append(f"{dsd_links.cut_prefix(t.header[j], pre) or f'{j + 1}째 열'} {text}")
    return f"[{tid}] 「{_labels(t)[r]}」: " + (" · ".join(cells) or "(빈 줄)")


def _words(labels: list[str]) -> list[str]:
    """줄 이름의 낱말(두 글자 이상, 기간 · 합계 이름은 뺀다). 「종속기업, 관계기업 및 공동기업 투자의 취득」 → 종속기업 · 관계기업 · 공동기업 · 투자 · 취득"""
    out = []
    for lab in labels:
        for w in re.split(r"[\s,·ㆍ()\[\]「」:/]+|및", str(lab or "")):
            w = re.sub(r"(의|와|과|에|로)$", "", re.sub(r"^[\d.)]+", "", w.strip()))
            if len(w) >= 2 and w not in _STOP and not re.fullmatch(r"[\d.,%\-]+", w):
                out.append(w)
    return list(dict.fromkeys(out))


_BIG = re.compile(r"\d{1,3}(,\d{3})+")      # 문장 속 큰 금액(천 단위 쉼표)


def _clip(text: str, at: int) -> str:
    if len(text) <= PARA_WIDTH:
        return text
    a = max(0, min(at - PARA_WIDTH // 3, len(text) - PARA_WIDTH))
    return ("…" if a else "") + text[a:a + PARA_WIDTH] + ("…" if a + PARA_WIDTH < len(text) else "")


def _sentences(parts: list, words: list[str], amounts: list[str], limit: int) -> list[tuple[str, str]]:
    """주석 문단에서 검증을 설명할 만한 문장. 두 금액 · 차이가 든 문장을 먼저, 그다음 줄 이름의 낱말이 많이 든 문장. (주석 번호, 문장)"""
    got = []
    for p in parts:
        for x in p.items:
            if x[0] != "p":
                continue
            sents = [t.strip() for t in re.split(r"(?<=다\.)\s*", str(x[1])) if t.strip()]
            for k, sent in enumerate(sents):
                big = bool(_BIG.search(sent))
                if "다음과 같" in sent or not (sent.endswith(("다.", "다")) or big):
                    continue                          # 표를 소개하는 문장(「… 내역은 다음과 같습니다」)과 표 제목(「…에 대한 공시」)은 근거가 안 된다
                amt = [a for a in amounts if a in sent]
                hit = [w for w in words if w in sent]
                if not amt and not hit:
                    continue
                at = sent.find(amt[0] if amt else hit[0])
                text = _clip(sent, at)
                nxt = sents[k + 1] if k + 1 < len(sents) else ""
                if not big and _BIG.search(nxt):      # 금액은 뒷문장에 있곤 하다(10-23 한 상장사 4회: 콜옵션 문단의 둘째 문장 「취득원가는 1,241,750백만원」 을 찾으려 원문을 열었다)
                    text += " " + _clip(nxt, _BIG.search(nxt).start())
                    big = True
                got.append((3 * len(amt) + len(hit) + big, -len(got), p.key, text))
    got.sort(reverse=True)
    seen, out = set(), []
    for _, _, key, sent in got:
        if sent not in seen:
            seen.add(sent)
            out.append((key, sent))
        if len(out) >= limit:
            break
    return out


def _title(t: str) -> str:
    from .base import norm

    return norm(re.sub(r"^\s*[\d.]+\s*", "", str(t or "")))


def _paragraphs(doc: Doc, c: Check, cells: list, prior: Doc | None) -> list[str]:
    """검증 하나의 문장 근거(2026-10-23). 두 칸이 든 주석과 작년 보고서의 같은 주석(전기 대사가 짝지은 표, 제목이 같은 주석)에서
    두 금액 · 차이나 줄 이름의 낱말이 든 문장을 싣는다. 10-23 한 상장사 재기에서 검증 에이전트가 원문을 11번 열어 찾은 것이
    이 보고서 주석 11 의 과거근무원가 문장, 작년 반기보고서 주석 6 의 콜옵션 행사 문장이었다."""
    tabs = {t.id: t for t in doc.tables()}
    labels, now, before = [], [], []
    for tid, r, _ in cells:
        base = tid[len(PRIOR_ID):] if tid.startswith(PRIOR_ID) else tid
        src = prior if tid.startswith(PRIOR_ID) else (doc if tid in tabs else None)
        if src is None:
            continue
        try:
            part = src.part_of(base)
            t = next(x[1] for x in part.items if x[0] == "t" and x[1].id == base)
        except StopIteration:
            continue
        if 0 <= r < len(t.rows):
            labels.append(_labels(t)[r])
        (before if src is prior else now).append(part)
    if prior is not None:
        titles = {_title(p.title) for p in now if p.key.startswith("주석")}
        before += [p for p in prior.parts if p.key.lstrip("②③④").startswith("주석") and _title(p.title) in titles]
    now = [p for p in {id(p): p for p in now}.values() if p.key.startswith("주석")]      # Part 는 해시가 안 돼 id 로 겹친 것을 뺀다
    before = list({id(p): p for p in before}.values())
    words = _words(labels)
    vals = [c.left, c.right, (c.left or 0) - (c.right or 0)]
    amounts = list(dict.fromkeys(_fmt(abs(v)) for v in vals if isinstance(v, (int, float)) and abs(v) >= 1000))
    out = [f"  - 문단 [{k}] {sent}" for k, sent in _sentences(now, words, amounts, PARA_LINES)]
    out += [f"  - 작년 문단 [{k}] {sent}" for k, sent in _sentences(before, words, amounts, PRIOR_PARA_LINES)]
    return out


def _bundle(doc: Doc, c: Check, tabs: dict, rowmap: dict, prior: Doc | None = None) -> list[str]:
    """검증 하나의 근거 묶음(2026-10-22 실행 시간 P2). 검증 에이전트가 원문을 다시 뒤지지 않게 판정자료에 함께 적는다.
    - 두 칸이 든 표의 그 줄(표 줄)
    - 같은 주석의 다른 표에서 줄 이름이 같은 줄과 그 표의 합계 줄(같은 주석)
    - 작년 보고서의 같은 표 줄. 전기 대사가 짝지은 줄이다(작년)
    - 작년 같은 표의 합계 줄과 짝지은 줄 위아래 두 줄(작년 같은 표, 2026-10-23). 10-22 한 상장사 재기에서 차이를 설명하는 작년 줄
      (미처분이익잉여금, 확정기여 비용)이 묶음에 없어 검증 에이전트가 원문을 12번 열었다"""
    from .base import norm

    cells = [(c.table, c.r, c.c)] + [(tid, r, k) for tid, r, k, _ in c.terms]
    shown, out = set(), []
    for tid, r, k in cells:
        t = tabs.get(tid)
        if t is not None and (tid, r) not in shown and 0 <= r < len(t.rows):
            shown.add((tid, r))
            out.append("  - 표 줄 " + _row_text(tid, t, r, k))
    for tid, r, _ in cells:
        t = tabs.get(tid)
        if t is None or tid not in {x.id for x in doc.tables()} or not (0 <= r < len(t.rows)):
            continue
        name = norm(_labels(t)[r])
        for q in (x[1] for x in doc.part_of(tid).items if x[0] == "t"):
            if q.kind:
                continue
            for i, lab in enumerate(_labels(q)):
                if (q.id, i) in shown:
                    continue
                same = name and norm(lab) == name and q.id != tid
                total = q.id == tid and dsd_links.total_kind(lab) is not None and any(_isnum(v) for v in q.nums[i][1:])
                if same or total:
                    shown.add((q.id, i))
                    out.append("  - 같은 주석 " + _row_text(q.id, q, i))
    hits = []
    for tid, r, _ in cells:
        hit = rowmap.get((tid, r))
        if hit and hit not in shown and hit[0] in tabs:
            shown.add(hit)
            hits.append(hit)
            out.append("  - 작년 " + _row_text(hit[0], tabs[hit[0]], hit[1]))
    hits += [(tid, r) for tid, r, _ in cells if tid.startswith(PRIOR_ID) and tid in tabs]      # 전기 대사 검증이면 그 작년 칸의 표
    for tid, r in hits:
        q = tabs[tid]
        labels = _labels(q)
        near = [i for i in range(max(0, r - PRIOR_NEAR), min(len(q.rows), r + PRIOR_NEAR + 1)) if i != r]
        tots = [i for i, lab in enumerate(labels) if dsd_links.total_kind(lab) is not None]
        for i in near + tots:
            if (tid, i) in shown or not any(_isnum(v) for v in q.nums[i][1:]):
                continue
            shown.add((tid, i))
            out.append("  - 작년 같은 표 " + _row_text(tid, q, i))
    return out[:BUNDLE_LINES] + _paragraphs(doc, c, cells + [(h[0], h[1], None) for h in hits if (h[0], h[1], None) not in cells], prior)


# 전기 대사 판정(apply_prior_verdicts)이 근거 글 뒤에 붙인 「판정 …: …」. 판정은 「판정」 줄에 따로 적으니 근거 줄에서는 뗀다.
# 검증 에이전트가 판정 글을 읽기 전에 근거를 보게 하려는 것이다(10-22 한 상장사 재기에서 검증 에이전트가 근거 줄의 판정 글을 먼저 봤다)
_PRIOR_VERDICT = re.compile(r"(^| · )판정 (불일치|작년 불일치|설명됨|걸지 않음): .*$", re.S)


def pack(doc: Doc, checks: list[Check], tabs: dict, cause: dict, last: dict, prior: Doc | None = None) -> str:
    """판정자료: FALSE · 확인 검증마다 두 칸, 차이, 차이 설명 후보, 작년 보고서, 판정, 근거 묶음을 한 곳에. 판정을 쓰거나 검증하는 에이전트가 읽는다."""
    rowmap = {(c.table, c.r): (c.terms[0][0], c.terms[0][1]) for c in checks if c.group == "전기" and c.terms}      # 올해 줄 → 전기 대사가 짝지은 작년 줄
    rows = [c for c in checks if c.ok is False and not c.minor and not c.excluded]
    rows.sort(key=lambda c: (0 if dsd_links.failed(c) else 1, (cause.get(c.id) or (9999,))[0], -abs((c.left or 0) - (c.right or 0))))
    out = ["# dsd 판정자료", "", *FORMAT,
           "## 이 자료", "",
           "FALSE · 확인 검증마다 두 칸의 금액, 차이, 엔진이 찾은 차이 설명 후보, 작년 보고서의 같은 칸, 지금 판정을 적었다.",
           "「근거 묶음」 은 두 칸이 든 표의 줄, 같은 주석에서 줄 이름이 같은 줄과 합계 줄, 작년 보고서의 같은 표 줄과 그 표의 합계 줄 · 이웃 줄, "
           "그리고 두 칸이 든 주석과 작년 같은 주석의 문장 가운데 두 금액 · 차이나 줄 이름의 낱말이 든 것이다. 원문을 열기 전에 이것부터 본다.", "",
           f"- FALSE(숫자 오류) {sum(1 for c in rows if dsd_links.failed(c))}건, 확인 · 표시 오류 · 설명 부족 · 작년 보고서의 오류 {sum(1 for c in rows if not dsd_links.failed(c))}건",
           f"- 독립 검증 대상 {sum(1 for c in rows if not dsd_links.no_review(c))}건. 판정이 확인인 늘 나는 차이 {sum(1 for c in rows if dsd_links.sampled(c))}건과"
           f" 엔진이 근거를 확인한 숫자 오류 {sum(1 for c in rows if dsd_links.engine_checked(c))}건,"
           f" 정산표 대사에서 엔진이 정한 수정분개 미반영 {sum(1 for c in rows if dsd_links.wtb_checked(c))}건은 독립 검증을 하지 않는다"
           "(2026-10-22 결정. 「독립 검증: 대상 아님」 으로 적었다)", ""]
    for c in rows:
        t = tabs.get(c.table)
        left = cell_name(c.table, t, c.r, c.c) if t is not None else c.table
        d = (c.left or 0) - (c.right or 0)
        out.append(f"## {c.id}")
        out.append(f"- 상태: {dsd_links.kind_of(c)}" + (f" · 원인 {cause[c.id][0]}" if c.id in cause else "") + f" · {c.group} · {c.kind}")
        out.append(f"- 왼쪽 칸: {left} = {_fmt(c.left or 0)}")
        out.append(f"- 대사 대상: {c.label} = {_fmt(c.right or 0)}")
        out.append(f"- 차이: {_fmt(d)} (단위 {c.unit:g}원)" + (f" · 허용 폭 {c.tol:g}" if c.tol else ""))
        basis = _PRIOR_VERDICT.sub("", c.basis or "")
        if basis:
            out.append(f"- 근거: {basis}")
        if c.when:
            out.append(f"- 조건 · 판정 표시: {c.when}")
        if last.get(c.id):
            out.append(f"- 작년 보고서: {last[c.id]}")
        if c.hints:
            out.append("- 차이 설명 후보:")
            out += [f"  - [{h['kind']}] {h['text']}" for h in c.hints]
        else:
            out.append("- 차이 설명 후보: 엔진이 찾은 것 없음")
        bundle = _bundle(doc, c, tabs, rowmap, prior)
        if bundle:
            out += ["- 근거 묶음:"] + bundle
        out.append(f"- 판정: {c.finding or '(없음)'}")
        if c.fix_note:
            out.append(f"- 고칠 칸 · 근거: {c.fix_note}")
        if c.verified:
            out.append(f"- 독립 검증: {c.verified}. {c.verify_why}")
        elif dsd_links.sampled(c):
            out.append(f"- 독립 검증: 대상 아님(늘 나는 차이 「{c.usual}」. 회계사가 표본으로 본다)")
        elif dsd_links.engine_checked(c):
            out.append("- 독립 검증: 대상 아님(엔진이 근거 칸으로 맞는 숫자를 확인했다)")
        elif dsd_links.wtb_checked(c):
            out.append("- 독립 검증: 대상 아님(엔진이 정산표로 확인했다. dsd 금액 = 회사제시 금액, 차이 = 수정분개)")
        out.append("")
    return "\n".join(out)
