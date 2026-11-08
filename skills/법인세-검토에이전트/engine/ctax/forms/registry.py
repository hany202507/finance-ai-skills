"""서식 · 란 정의. corptax-impl `engine/forms/registry.py` 를 줄여 옮겼다(조서 서식 · 캐시 · 합계 규칙은 뺐다).

정의 JSON 은 `defs/<code>.json` 이고 꼴은 {"code","title","aliases","items":[{"code","label","dtype","formula","rows",
"total","table"}]} 다. formula 는 파이썬 식이고 쓸 수 있는 이름은 FORMULA_NAMES 뿐이다.

  c('란')            같은 서식의 란(다행 서식이면 같은 줄)
  F('서식','란')      다른 서식의 란
  F.sum('서식','란')  다행 서식의 한 열 합계
  total(a, b, ...)   여러 값의 합
  param('키')        연도별 상수(params.py)
  rounddown · xround · band · progressive · bracket_rate · min_tax_brackets  fx.py
"""
from __future__ import annotations

import ast
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ctax.forms import fx

DEFS = Path(__file__).resolve().parent / "defs"
DTYPES = ("won", "rate", "text", "date", "int")
FX_NAMES = ("rounddown", "xround", "band", "progressive", "bracket_rate", "min_tax_brackets")
FORMULA_NAMES = frozenset({"c", "total", "param", "max", "min", "abs", "round", "F", *FX_NAMES})
ALLOWED_F_ATTRS = frozenset({"sum", "rows", "here", "total", "param"})


@dataclass(frozen=True)
class Item:
    code: str
    name: str
    dtype: str = "won"
    fn: Callable | None = None
    formula: str | None = None
    rows: bool = False
    aliases: tuple = ()
    total: bool = False
    table: str = ""

    def __post_init__(self):
        if self.dtype not in DTYPES:
            raise ValueError(f"{self.code}: 모르는 dtype {self.dtype!r}")


@dataclass
class Form:
    code: str
    title: str
    items: list
    aliases: dict = field(default_factory=dict)

    def __post_init__(self):
        self._index = {}
        for it in self.items:
            for c in (it.code, *it.aliases):
                if self._index.get(str(c), it) is not it:
                    raise ValueError(f"{self.code}: 란 코드 {c!r} 가 두 란에 붙어 있다")
                self._index[str(c)] = it

    def find(self, code):
        return self._index.get(str(code))

    def item(self, code) -> Item:
        it = self.find(code)
        if it is None:
            raise KeyError(f"{self.code}.{code}")
        return it

    @property
    def single_items(self) -> list:
        return [it for it in self.items if not it.rows]

    @property
    def row_items(self) -> list:
        return [it for it in self.items if it.rows]


def item_sort_key(code) -> tuple:
    """란 코드 정렬. 숫자로 시작하면 숫자 순서(3, 10, 105), 나머지는 글자 순서."""
    head = "".join(ch for ch in str(code).split("_")[0] if ch.isdigit())
    return (int(head) if head else 10**9, str(code))


def _check_names(formula: str):
    try:
        tree = ast.parse(formula, mode="eval")
    except SyntaxError as e:
        raise ValueError(f"수식을 읽을 수 없다: {formula} ({e.msg})") from e
    used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    bad = sorted(used - FORMULA_NAMES)
    if bad:
        raise ValueError(f"수식에 쓸 수 없는 이름 {bad}: {formula}")
    bad_attrs = sorted({n.attr for n in ast.walk(tree)
                        if isinstance(n, ast.Attribute) and (n.attr.startswith("_") or n.attr not in ALLOWED_F_ATTRS)})
    if bad_attrs:
        raise ValueError(f"수식에 쓸 수 없는 속성 {bad_attrs}: {formula}")


_FX = {name: getattr(fx, name) for name in FX_NAMES}


def make_fn(formula: str) -> Callable:
    _check_names(formula)
    code = compile(formula, "<formula>", "eval")

    def fn(F):
        return eval(code, {"__builtins__": {}},                       # noqa: S307 (이름을 FORMULA_NAMES 로 묶었다)
                    {"c": F.here, "total": F.total, "param": F.param,
                     "max": max, "min": min, "abs": abs, "round": round, "F": F, **_FX})

    fn.formula = formula
    return fn


def item_from_dict(d: dict) -> Item:
    formula = d.get("formula") or None
    return Item(code=str(d["code"]), name=d.get("label", d.get("name", "")), dtype=d.get("dtype", "won"),
                fn=make_fn(formula) if formula else None, formula=formula,
                rows=bool(d.get("rows", False)), aliases=tuple(str(a) for a in d.get("aliases", ())),
                total=bool(d.get("total", False)), table=str(d.get("table", "")))


def form_from_dict(d: dict) -> Form:
    return Form(str(d["code"]), d.get("title", str(d["code"])), [item_from_dict(it) for it in d["items"]],
                d.get("aliases", {}))


def load(code: str) -> Form:
    return form_from_dict(json.loads((DEFS / f"{code}.json").read_text(encoding="utf-8")))


def load_all() -> dict:
    """{서식 code: Form}. defs 폴더의 정의 전부."""
    return {p.stem: load(p.stem) for p in sorted(DEFS.glob("*.json"))}
