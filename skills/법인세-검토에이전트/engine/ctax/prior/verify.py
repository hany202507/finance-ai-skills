"""전기 읽기 결과 검사: 서식 정의 계산식 검산(서식 안 · 서식 사이)과 PDF 쪽 글자 대조. 값은 바꾸지 않고 problems 만 더한다.

계산식은 서식 정의(`prior/defs` 가 먼저, 없으면 `forms/defs`)의 formula 이고 계산기는 `ctax.forms.calc` 다. 읽은 값을 모두 고정(pin)한
뒤 란마다 그 란의 계산식만 따로 셈해 읽은 값과 견준다. 계산식이 읽은 란의 상태는 넷이다.

  읽음     값이 있다. 그 값으로 셈한다
  빈칸     칸은 있는데 비었다. 엔진이 다 읽는 서식(코드 파서 서식)에서 읽지 않은 란, 스킬 답의 null. 0 으로 셈한다
           (계산식이 있는 란이면 그 계산식 값으로 셈한다, calc 가 그렇게 한다)
  읽지 않음 일부만 읽는 서식(PARTIAL: 1호 글 란 · 54 · 29 · 51 · 40갑 · 47갑 · 조특 같은 낱말 좌표 서식)에서 읽지 않은 란,
           아예 읽지 않은 서식의 란, 스킬 답에 없는 란.
           이 란을 쓰는 계산식은 검산하지 않는다
  칸 없음   스킬 답의 "absent"(그 판 서식에 칸이 없다). 이 란을 쓰는 계산식은 검산하지 않는다

검산하는 란 자체가 빈칸인데 계산식 값이 0 이 아니면 둘로 가른다. 계산식 값이 그 서식 쪽 글자에 있으면 「읽지 않은 칸일 수 있다」 로
problems 에 남기고, 쪽 어디에도 없으면 서식이 비워 둔 칸으로 보고 오류로 세지 않는다(센 수만 summary 의 form_blank).

PDF 글자 대조는 서식마다 그 서식 쪽 낱말에서 금액을 뽑는다. 쪽에 있는 MISSED_MIN 원 이상 금액이 그 서식 결과에 없으면
missing_amount, 결과의 MADE_UP_MIN 원 이상 금액이 쪽 글자에 없으면 not_in_text 다. 부호는 견주지 않는다(절댓값).
"""
from __future__ import annotations

import ast
import json
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path

from ctax.forms import calc
from ctax.forms.registry import form_from_dict

PRIOR_DEFS = Path(__file__).resolve().parent / "defs"
FORMS_DEFS = Path(__file__).resolve().parents[1] / "forms" / "defs"

MISSED_MIN = 10_000          # 쪽 글자에 있는데 결과에 없는 금액으로 보는 가장 작은 금액(인쇄된 한도 · 코드 번호를 빼려고)
MADE_UP_MIN = 1_000          # 결과에 있는데 쪽 글자에 없는 금액으로 보는 가장 작은 금액
TOLERANCE = 1                # 계산식 값과 읽은 값의 차이가 이보다 작으면 맞다(원 단위 정수끼리라 사실상 같아야 맞다)
SAMPLE = 12                  # problems why 에 적는 금액 표본 수
NUM_DTYPES = ("won", "int")
# 정의 계산식이 그 서식에 실제로 적는 값과 다를 수 있어 검산하지 않는 란(서식, 란 또는 "*"). 근거는 NOTES.md 「10-27 검사」
SKIP_ITEMS = {
    ("3", "48"): "분납할 세액은 한도 안에서 고르는 값이고 끝수 처리도 신고 프로그램마다 다르다",
    ("51", "*"): "51호 규모 기준 칸은 억원 단위로 따로 읽고, 자산총액의 기준이 표준재무상태표 자산총계와 다를 수 있다",
    ("8갑", "16B_3"): "정의는 8호 부표3 1절 (104)(당기분)를 가리키는데 신고서의 8호(갑) 대상세액은 이월분까지 더한 값일 수 있다",
}
SKIP_TEXT_FORMS = {"1", "세무조정계산서총괄표", "63의13", "77", "전산조직운용명세서", "지출증명서류수취검토서식"}


# ---------------------------------------------------------------- 정의

@lru_cache(maxsize=None)
def defn(code: str):
    """(registry.Form, 정의 폴더 이름). prior/defs 가 먼저(파서가 쓰는 란 코드), 없으면 forms/defs. 둘 다 없으면 (None, "")."""
    for base, name in ((PRIOR_DEFS, "prior/defs"), (FORMS_DEFS, "forms/defs")):
        p = base / f"{code}.json"
        if p.exists():
            try:
                return form_from_dict(json.loads(p.read_text(encoding="utf-8"))), name
            except (ValueError, KeyError, SyntaxError):
                return None, ""
    return None, ""


def canonical(form: str, item: str) -> str | None:
    f, _ = defn(str(form))
    it = f.find(str(item)) if f is not None else None
    return it.code if it is not None else None


# ---------------------------------------------------------------- 값 묶음

class Values:
    """검산에 쓰는 값. keys 는 (서식, 정본 란 코드, 줄).

    full     빈 란을 빈칸(0)으로 보는 서식(엔진이 다 읽는 서식 · 스킬이 모든 란에 답한 서식)
    absent   칸 없음 (서식, 란)
    blank    빈칸으로 답한 (서식, 란, 줄)(스킬 답의 null)
    unread   full 서식이지만 답하지 않은 (서식, 란). 읽지 않은 란으로 본다
    pages    서식 → 쪽 글자 숫자 묶음(PageNumbers 목록)
    """

    def __init__(self):
        self.vals: dict[tuple, object] = {}
        self.full: set[str] = set()
        self.absent: set[tuple] = set()
        self.blank: set[tuple] = set()
        self.unread: set[tuple] = set()
        self.pages: dict[str, list] = {}

    def put(self, form, item, row, value) -> bool:
        code = canonical(form, item)
        if code is None or value is None or value == "":
            return False
        self.vals[(str(form), code, int(row))] = value
        return True

    @property
    def forms(self) -> set[str]:
        return {k[0] for k in self.vals} | self.full


class _Log(dict):
    """계산 중에 읽은 (서식, 란, 줄)을 적어 두는 dict(calc.Store.values 대신). 고정한 값은 values[k] 로 읽힌다."""

    def __init__(self, *a):
        super().__init__(*a)
        self.seen: list = []

    def __getitem__(self, k):
        self.seen.append(k)
        return super().__getitem__(k)

    def get(self, k, default=None):
        self.seen.append(k)
        return super().get(k, default)


class _Store(calc.Store):
    def __init__(self):
        super().__init__()
        self.values = _Log()


# ---------------------------------------------------------------- 서식 안 · 서식 사이 검산

def _num(v):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return v


def _won(v) -> str:
    if v is None:
        return "빈칸"
    return f"{int(round(v)):,}" if float(v).is_integer() else str(v)


def _refs(formula: str) -> set[str]:
    """계산식이 글자로 부르는 다른 서식 코드(F('15', ...) · F.sum('15', ...))."""
    out = set()
    for n in ast.walk(ast.parse(formula, mode="eval")):
        if isinstance(n, ast.Call) and n.args and isinstance(n.args[0], ast.Constant):
            fn = n.func
            if (isinstance(fn, ast.Name) and fn.id == "F") or (isinstance(fn, ast.Attribute) and fn.attr in ("sum", "rows")):
                out.add(str(n.args[0].value))
    return out


def def_checks(v: Values, *, fy_start: str, sme: bool = True, only: set[str] | None = None) -> tuple[list[dict], dict]:
    """정의 계산식 검산 → (problems, summary). only 를 주면 그 서식의 란만 검산한다(서식 사이 검산은 왼쪽 란 기준).

    summary: {"form": {ok, fail, unread, form_blank}, "cross": {...}, "skipped": n}."""
    forms = {}
    for code in v.forms:
        f, _ = defn(code)
        if f is not None:
            forms[code] = f
    store = _Store()
    for k, val in v.vals.items():
        store.values[k] = val
        store.pinned.add(k)
    summary = {"form": {"ok": 0, "fail": 0, "unread": 0, "form_blank": 0},
               "cross": {"ok": 0, "fail": 0, "unread": 0, "form_blank": 0}, "skipped": 0}
    out: list[dict] = []
    for code in sorted(forms):
        if only is not None and code not in only:
            continue
        f = forms[code]
        for it in f.items:
            if it.fn is None or it.dtype not in NUM_DTYPES or (code, it.code) in SKIP_ITEMS or (code, "*") in SKIP_ITEMS:
                continue
            rows = store.row_numbers(code) if it.rows else [0]
            for r in rows:
                k = (code, it.code, r)
                if (code, it.code) in v.absent or (code, it.code) in v.unread:
                    continue
                read = v.vals.get(k)
                if read is None and code not in v.full and k not in v.blank:
                    continue                                     # 읽지 않은 란
                got = _eval(store, forms, k, it, v, fy_start, sme)
                if got is None:
                    summary["skipped"] += 1
                    continue
                want, seen_forms, unread_inputs = got
                cross = any(x != code for x in seen_forms)
                bucket = summary["cross" if cross else "form"]
                rv = _num(read)
                if read is not None and rv is None:
                    continue                                     # 글 값
                if rv is not None and abs(rv - want) < TOLERANCE:
                    bucket["ok"] += 1
                    continue
                if rv is None:
                    if abs(want) < TOLERANCE:
                        bucket["ok"] += 1
                        continue
                    if not _on_pages(v, code, want):
                        bucket["form_blank"] += 1               # 서식이 비워 둔 칸
                        continue
                    bucket["unread"] += 1
                else:
                    bucket["fail"] += 1
                out.append(_check_problem(code, it, r, rv, want, cross, seen_forms, unread_inputs))
    return out, summary


def _eval(store: _Store, forms: dict, k: tuple, it, v: Values, fy_start: str, sme: bool):
    """란 k 의 계산식을 읽은 값으로 셈한다. → (값, 읽은 서식들, 빈칸으로 셈한 입력) 또는 None(검산하지 않음)."""
    store.values.seen = []
    missing: set = set()
    acc = calc.F(store, forms, {}, [k], fy_start, sme, missing)
    acc.form, acc.row = k[0], k[2]
    try:
        want = it.fn(acc)
    except (calc.Uncomputed, calc.CycleError, KeyError, TypeError, ValueError, ZeroDivisionError):
        return None
    if missing or _num(want) is None:
        return None                                              # 정의가 없거나 읽지 않은 서식을 부른다
    seen = [x for x in store.values.seen if x != k]
    blank_inputs = []
    for x in seen:
        if (x[0], x[1]) in v.absent or (x[0], x[1]) in v.unread:
            return None                                          # 칸 없음 · 답하지 않은 란을 쓰는 계산식
        if x not in v.vals:
            if x[0] not in v.full and x not in v.blank:
                return None                                      # 읽지 않은 란을 쓰는 계산식
            blank_inputs.append(x)
    forms_seen = {x[0] for x in seen} | (_refs(it.formula) & set(forms))
    return want, forms_seen, sorted({f"{x[0]}.{x[1]}" for x in blank_inputs})


def _check_problem(code, it, row, read, want, cross, seen_forms, blank_inputs) -> dict:
    where = f"{code} ({it.code})" + (f" {row}번 줄" if row else "")
    others = sorted(x for x in seen_forms if x != code)
    kind = "check_cross" if cross else "check_form"
    if read is None:
        title = f"{'서식 사이' if cross else '서식 안'} 검산: {where} 이 비었는데 계산식 값이 쪽 글자에 있다(읽지 않은 칸일 수 있다)"
    else:
        title = f"{'서식 사이' if cross else '서식 안'} 검산이 맞지 않는다: {where} {_short(it.name)}"
    why = (f"읽은 값 {_won(read)} · 계산식 {_won(want)}" + (f" (차이 {_won((read or 0) - want)})" if read is not None else "")
           + f". 식 {it.formula}" + (f". 견준 서식 {', '.join(others)}" if others else "")
           + (f". 빈칸으로 셈한 란 {', '.join(blank_inputs[:6])}" if blank_inputs else ""))
    p = {"title": title, "why": why, "kind": kind, "form": code, "item": it.code, "label": _short(it.name),
         "expected": int(round(want)), "read": None if read is None else int(round(read)),
         "diff": None if read is None else int(round(read - want)), "formula": it.formula,
         "ref": f"verify.{kind}.{code}.{it.code}.{row}"}
    if row:
        p["row"] = row
    if others:
        p["with"] = others
    return p


def _short(name: str) -> str:
    return re.sub(r"\s+", " ", str(name or "")).strip()[:40]


# ---------------------------------------------------------------- 쪽 글자 숫자

GROUPED = re.compile(r"[0-9]{1,3}(?:[,:][0-9]{3})+")
NUMBER = re.compile(r"[0-9][0-9,:]*")
HEAD = re.compile(r"^[△▲\-－(（]?\d{1,3}(?:,\d{3})*,$")          # 줄 끝에서 잘린 금액 앞부분(「1,234,」)
ASCII3 = re.compile(r"^[0-9]{1,3}$")                               # 세 자리씩 띄어 적은 숫자(「①」 같은 글자는 isdigit 이 참이라 쓰지 않는다)
TAIL = re.compile(r"^\d{3}(?:,\d{3})*[)）]?$")                    # 다음 줄로 넘어간 뒷부분(「567」 · 「567,890)」)


class PageNumbers:
    """쪽 하나의 숫자. amounts: 천 단위로 묶어 적은 금액(쉼표 · 콜론), present: 쪽에 있는 모든 숫자(묶음 · 맨 숫자 · 띄어 적은
    세 자리씩 띄어 적은 숫자를 이은 것). 부호 표기(△ · 괄호 · -)는 떼고 절댓값으로 둔다."""

    def __init__(self, page_no: int, words: list):
        self.page_no = page_no
        self.amounts: set[int] = set()
        self.present: set[int] = set()
        self.counts: Counter = Counter()          # 숫자가 찍힌 낱말 수(같은 금액이 몇 번 찍혔나)
        toks = [(str(w[4]), w[1], w[3]) for w in words]
        joined: list[tuple[str, float, float]] = []
        i = 0
        while i < len(toks):
            t, y0, y1 = toks[i]
            if HEAD.match(t) and i + 1 < len(toks) and TAIL.match(toks[i + 1][0]) and toks[i + 1][1] >= y0:
                joined.append((t + toks[i + 1][0], y0, y1))
                i += 2
                continue
            joined.append((t, y0, y1))
            i += 1
        run, run_y = "", None
        for t, y0, _y1 in joined:
            here = set()
            for m in GROUPED.finditer(t):
                n = int(re.sub(r"[,:]", "", m.group()))
                self.amounts.add(n)
                here.add(n)
            for m in NUMBER.finditer(t):
                digits = re.sub(r"[,:]", "", m.group())
                if digits:
                    here.add(int(digits))
            self.present |= here
            self.counts.update(here)
            if ASCII3.match(t):
                run = run + t if run and run_y is not None and abs(run_y - y0) < 2 else t
                run_y = y0
                self.present.add(int(run))
            else:
                run, run_y = "", None


def page_numbers(pages: list[dict]) -> list[PageNumbers]:
    return [PageNumbers(p.get("page_no") or 0, p.get("words") or []) for p in pages if p.get("words")]


def _on_pages(v: Values, form: str, amount) -> bool:
    """계산식 값이 그 서식 쪽에 다른 란 몫이 아닌 채로 찍혀 있는가. 찍힌 낱말 수가 같은 금액으로 읽은 란 수보다 많아야 한다
    (결손금처리계산서 쪽에 읽힌 당기순손실이 이익잉여금처분 쪽 빈 당기순이익 란의 계산식 값과 같은 경우를 빼려고)."""
    n = abs(int(round(amount)))
    printed = sum(p.counts[n] for p in v.pages.get(form, []))
    if not printed:
        printed = 1 if any(n in p.present for p in v.pages.get(form, [])) else 0
    taken = sum(1 for k, x in v.vals.items() if k[0] == form and _num(x) is not None and abs(int(round(x))) == n)
    return printed > taken


# ---------------------------------------------------------------- 글자 대조

NOT_AMOUNT_KEYS = {"year", "first_year", "fy", "차수", "page", "row", "번호", "관계"}   # 결과 dict 에서 금액이 아닌 숫자의 키


def amounts_of(obj) -> set[int]:
    """결과 값(숫자 · 리스트 · dict)에 든 원 단위 정수 금액의 절댓값. 연도 · 차수 · 쪽 번호 키는 뺀다."""
    out: set[int] = set()
    if isinstance(obj, dict):
        for key, x in obj.items():
            if key not in NOT_AMOUNT_KEYS:
                out |= amounts_of(x)
    elif isinstance(obj, (list, tuple)):
        for x in obj:
            out |= amounts_of(x)
    elif isinstance(obj, (int, float)) and not isinstance(obj, bool) and float(obj).is_integer():
        out.add(abs(int(obj)))
    return out


def text_checks(form: str, got: set[int], pages: list[PageNumbers], *, missed_min: int = MISSED_MIN,
                made_up_min: int = MADE_UP_MIN, missing: bool = True) -> list[dict]:
    """서식 하나: 쪽 글자 ↔ 결과 금액. 쪽 글자가 없으면(스캔본) 검사하지 않는다."""
    if not pages or not any(p.present for p in pages):
        return []
    on_page: set[int] = set()
    for p in pages:
        on_page |= p.present
    out = []
    missed = sorted({(p.page_no, n) for p in pages for n in p.amounts if n >= missed_min and n not in got}) if missing else []
    if missed:
        nos = sorted({no for no, _ in missed})
        sample = ", ".join(f"{no}쪽 {n:,}" for no, n in missed[:SAMPLE])
        out.append({"title": f"{form} 쪽 글자에 있는 금액 {len(missed)}개가 읽은 결과에 없다",
                    "why": f"{sample}{' 등' if len(missed) > SAMPLE else ''}. 그 서식의 란 · 명세 줄이면 읽기를 고치고, "
                           "당초 값 · 인쇄된 한도 · 읽지 않는 절이면 그대로 둔다",
                    "kind": "missing_amount", "form": form, "pages": nos, "count": len(missed),
                    "amounts": [n for _, n in missed], "ref": f"verify.missing_amount.{form}"})
    made_up = sorted(n for n in got if n >= made_up_min and n not in on_page)
    if made_up:
        sample = ", ".join(f"{n:,}" for n in made_up[:SAMPLE])
        out.append({"title": f"{form} 읽은 금액 {len(made_up)}개가 그 서식 쪽 글자에 없다",
                    "why": f"{sample}{' 등' if len(made_up) > SAMPLE else ''}. 다른 쪽 값을 읽었거나 숫자를 잘못 읽었을 수 있다",
                    "kind": "not_in_text", "form": form, "pages": sorted(p.page_no for p in pages), "count": len(made_up),
                    "amounts": made_up, "ref": f"verify.not_in_text.{form}"})
    return out


# ---------------------------------------------------------------- 엔진 결과에 걸기

# 일부만 읽는 서식(빈 란이 빈칸인지 읽지 않은 란인지 모른다). 이 서식들은 읽은 란끼리만 검산한다
PARTIAL = {"1", "54", "29", "51", "40갑", "47갑", "21", "22", "16의2", "조특10의8", "조특10의9", "조특10의9_1", "조특3_1"}
# 결과가 cells · rows 밖에 있는 서식(텍스트 대조에 쓰는 결과)
EXTRA = {"조특10의8": ("employment", "10의8"), "조특10의9": ("employment", "10의9"), "조특10의9_1": ("employment", "10의9"),
         "조특3_1": ("rnd", "cells"), "8부표3": ("credit_years", None)}
# 쪽 글자에 있는데 결과에 없는 금액(missing_amount)을 보지 않는 서식. 일부만 읽는 서식(PARTIAL)과 명세 줄을 읽지 않는 서식
NO_MISSING = {"32": "2절 명세(사람별 줄)를 읽지 않는다", "세금공과금명세서": "비고가 있는 줄만 읽는다",
              "8부표3": "1절 계산기준 글 속 금액과 2절 소계 · 합계 줄을 읽지 않는다"}


def engine_values(body: dict, cells: list, pages_by_form: dict[str, list]) -> Values:
    """엔진 결과 → Values. cells 는 파서 Cell 목록(줄 포함), body 는 build 결과(cells · rows)."""
    v = Values()
    for c in cells:
        val = c.value if c.value is not None else c.text
        if v.put(c.form_code, c.item_code, c.row_no, val) and c.form_code not in PARTIAL:
            v.full.add(c.form_code)
    for form, items in (body.get("cells") or {}).items():
        for item, val in (items or {}).items():
            k = canonical(form, item)
            if k is not None and (form, k, 0) not in v.vals and isinstance(val, (int, float)):
                v.put(form, item, 0, val)
    for form, pages in pages_by_form.items():
        v.pages[form] = page_numbers(pages)
    return v


def engine_got(body: dict, cells: list, form: str) -> set[int]:
    """서식 하나의 엔진 결과 금액(글자 대조용)."""
    got = amounts_of([c.value for c in cells if c.form_code == form and c.value is not None and not (
        form == "3" and c.item_code in ("11", "14", "35", "60"))])
    got |= amounts_of((body.get("cells") or {}).get(form) or {})
    got |= amounts_of((body.get("rows") or {}).get(form) or [])
    if form in EXTRA:
        key, sub = EXTRA[form]
        x = body.get(key) or {}
        got |= amounts_of((x.get(sub) if isinstance(x, dict) else None) if sub else x)
    return got


def run(body: dict, pages: list[dict], cells: list) -> dict:
    """build 결과에 검산 · 글자 대조 problems 를 더한다(값은 그대로). 반환은 summary."""
    from ctax.prior.read import pages_of
    extra = {f for f, (key, sub) in EXTRA.items()
             if (((body.get(key) or {}).get(sub) if isinstance(body.get(key), dict) else None) if sub else body.get(key))}
    read_forms = sorted({c.form_code for c in cells} | {k for k, x in (body.get("cells") or {}).items() if x}
                        | {k for k, x in (body.get("rows") or {}).items() if x} | extra)
    by_form = {}
    for f in read_forms:
        got = pages_of(pages, f)
        coded = [p for p in got if p.get("form_code") == f]      # 3호의2(2) 합계표준재무상태표처럼 같은 코드로 묶이나 파서가 안 읽는 쪽은 뺀다
        by_form[f] = coded or got
    v = engine_values(body, cells, by_form)
    fy_start = (body.get("fy") or "") + "-01-01" if body.get("fy") else ""
    sme = (body.get("company") or {}).get("sme")
    probs, summary = def_checks(v, fy_start=fy_start, sme=True if sme is None else bool(sme))
    texts = []
    for f in read_forms:
        if f in SKIP_TEXT_FORMS:
            continue
        texts += text_checks(f, engine_got(body, cells, f), v.pages.get(f) or [],
                             missing=f not in PARTIAL and f not in NO_MISSING)
    summary["text"] = {k: sum(1 for p in texts if p["kind"] == k) for k in ("missing_amount", "not_in_text")}
    body["problems"] += probs + texts
    return summary
