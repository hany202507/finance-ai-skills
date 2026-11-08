"""서식 란 값 저장소와 수식 계산. corptax-impl `engine/calc.py` 의 Store · F · evaluate 를 DB 없이 줄여 옮겼다.

Store 의 열쇠는 (서식, 란, 줄)이다. 줄 0 은 단일 란, 1 부터가 다행 서식의 줄이다. pin=True 로 넣은 값은 수식이 덮지 않는다
(정의에서는 수식 란이지만 목업이 다른 서식 대신 조서 값을 바로 넣는 란, 예: 3호 17 공제감면세액).
정의에 없는 서식(8갑 · 9 · 10갑 · 17 · std_cogs 등)을 수식이 읽으면 0 으로 보고 F.missing 에 남긴다.
"""
from __future__ import annotations

from ctax.forms import params as P


class CycleError(Exception):
    pass


class Uncomputed(Exception):
    """상수가 그 사업연도에 없어 계산하지 못한 란."""


class Store:
    def __init__(self):
        self.values: dict[tuple, object] = {}
        self.pinned: set = set()
        self.sources: dict[tuple, str] = {}

    @staticmethod
    def key(form, item, row=0) -> tuple:
        return (str(form), str(item), int(row))

    def set(self, form, item, value, row=0, source: str = "", pin: bool = False) -> None:
        k = self.key(form, item, row)
        self.values[k] = value
        if source:
            self.sources[k] = source
        if pin:
            self.pinned.add(k)

    def get(self, form, item, row=0, default=0):
        v = self.values.get(self.key(form, item, row), default)
        return default if v is None else v

    def source(self, form, item, row=0) -> str:
        return self.sources.get(self.key(form, item, row), "")

    def row_numbers(self, form) -> list:
        form = str(form)
        return sorted({k[2] for k in self.values if k[0] == form and k[2] >= 1})


def _empty(item):
    return "" if item is not None and item.dtype in ("text", "date") else 0


class F:
    def __init__(self, store: Store, forms: dict, memo: dict, stack: list, fy_start: str, sme: bool, missing: set):
        self.store, self.forms, self.memo, self.stack = store, forms, memo, stack
        self.fy_start, self.sme, self.missing = fy_start, sme, missing
        self.form = None
        self.row = 0

    def __call__(self, form, item, row=0):
        form, item = str(form), str(item)
        f = self.forms.get(form)
        if f is None:
            self.missing.add(f"{form}.{item}")
            return 0
        it = f.find(item)
        if it is None:
            raise KeyError(f"{form}.{item} 은 정의에 없다")
        return _value((form, it.code, int(row)), self)

    def here(self, item, row=None):
        return self(self.form, item, self.row if row is None else row)

    def total(self, *vals):
        return sum(v for v in vals if v is not None)

    def sum(self, form, item):
        form = str(form)
        if form not in self.forms:
            self.missing.add(f"{form}.{item}")
            return 0
        return sum((self(form, item, r) or 0) for r in self.store.row_numbers(form))

    def rows(self, form, **filters) -> list:
        f = self.forms.get(str(form))
        if f is None:
            return []
        out = []
        for r in self.store.row_numbers(form):
            row = {"row_no": r, **{it.code: self(form, it.code, r) for it in f.row_items}}
            if all(row.get(k) == v for k, v in filters.items()):
                out.append(row)
        return out

    def param(self, key, prior=False):
        if key == "세율.구간" and not prior and str(self.fy_start) >= "2025-01-01":
            # 1호 (36) 부동산임대업 주업법인 「여」: 법인세법 §55①2 세율(2025-01-01 이후 개시). 세율표를 고르는 조건일 뿐 계산 입력이
            # 아니므로 dict.get 으로 읽어 전기 검산(prior/verify 의 읽은 란 기록)에 1호 의존을 남기지 않는다
            mark = dict.get(self.store.values, self.store.key("1", "36", 0), "")
            if str(mark or "").strip() == "여":
                try:
                    return P.get("세율.구간.소규모", self.fy_start, self.sme)
                except P.NoValue:
                    pass
        try:
            return P.get(key, self.fy_start, self.sme)
        except P.NoValue as e:
            raise Uncomputed(str(e)) from None


def _value(k: tuple, acc: F):
    st = acc.store
    if k in st.pinned:
        return st.values[k]
    if k in acc.memo:
        return acc.memo[k]
    item = acc.forms[k[0]].find(k[1])
    if item.fn is None:
        return st.get(k[0], k[1], k[2], _empty(item))
    if k in acc.stack:
        raise CycleError("수식이 순환한다: " + " → ".join(".".join(map(str, x)) for x in acc.stack + [k]))
    acc.stack.append(k)
    sub = F(st, acc.forms, acc.memo, acc.stack, acc.fy_start, acc.sme, acc.missing)
    sub.form, sub.row = k[0], k[2]
    try:
        v = item.fn(sub)
    finally:
        acc.stack.pop()
    if isinstance(v, float) and item.dtype == "won":
        v = int(round(v))
    acc.memo[k] = v
    return v


def evaluate(store: Store, forms: dict, *, fy_start: str, sme: bool = True) -> tuple[dict, set]:
    """수식 란을 전부 계산해 store 에 써 넣는다. 반환은 ({(서식, 란, 줄): 값}, 정의 밖 서식 참조 집합).
    다행 서식의 줄 수식은 그 서식에 값이 있는 줄마다 계산한다. 상수가 없는 란은 None."""
    memo: dict = {}
    missing: set = set()
    root = F(store, forms, memo, [], fy_start, sme, missing)
    out = {}
    for f in forms.values():
        for it in f.items:
            if it.fn is None:
                continue
            for r in (store.row_numbers(f.code) if it.rows else [0]):
                k = (f.code, it.code, r)
                try:
                    out[k] = _value(k, root)
                except Uncomputed:
                    out[k] = None
    for k, v in out.items():
        if k not in store.pinned:
            store.values[k] = v
            store.sources.setdefault(k, "수식")
    return out, missing
