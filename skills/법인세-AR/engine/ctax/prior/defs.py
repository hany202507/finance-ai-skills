"""전기 PDF 파서가 쓰는 서식 정의(란 코드 · 이름 · 별칭)만 읽는다.

corptax 의 forms.registry · values · stdfs 에서 파서가 쓰는 부분(form_def · item_name · form_name · LABELS_1)만 옮겼다.
수식 · 계산은 읽지 않는다. 정의 JSON 은 같은 폴더 `defs/` 에 필요한 서식만 복사해 두었다.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

DEFS = Path(__file__).resolve().parent / "defs"

# 1호 원문자 란의 인쇄 제목(공백 없이). 파서는 이 제목을 찾아 그 뒤의 글자를 값으로 읽는다
LABELS_1 = {1: "사업자등록번호", 2: "법인등록번호", 3: "법인명", 4: "전화번호", 5: "대표자성명",
            6: "전자우편주소", 7: "소재지", 8: "업태", 9: "종목", 10: "주업종코드", 11: "사업연도",
            12: "수시부과기간", 13: "법인구분", 14: "조정구분", 15: "종류별구분"}

FORM_NAMES = {"std_bs": "표준재무상태표", "std_is": "표준손익계산서", "std_cogs": "제조원가명세서",
              "std_bs_fin": "표준재무상태표(금융업)", "std_bs_fin_sum": "합계표준재무상태표(금융업)",
              "std_is_fin": "표준손익계산서(금융업)",
              "std_re": "이익잉여금처분계산서", "1": "1호", "3": "3호", "8갑": "8호(갑)", "50을": "50호(을)",
              "15": "15호", "15부표1": "15호 부표1", "15부표2": "15호 부표2", "50갑": "50호(갑)", "20_4": "20호(4)",
              "8부표3": "8호 부표3", "8을": "8호(을)", "32": "32호", "34": "34호", "23을": "23호(을)", "21": "21호"}
FORM_SHORT = {"std_bs": "표준BS", "std_is": "표준IS", "std_cogs": "원가명세서", "std_re": "이익잉여금처분",
              "std_bs_fin": "표준BS(금융업)", "std_bs_fin_sum": "합계표준BS(금융업)", "std_is_fin": "표준IS(금융업)"}


def form_name(code, short: bool = False) -> str:
    code = str(code)
    if short and code in FORM_SHORT:
        return FORM_SHORT[code]
    return FORM_NAMES.get(code, code)


@dataclass(frozen=True)
class Item:
    code: str
    name: str
    dtype: str = "won"
    rows: bool = False
    aliases: tuple = ()
    total: bool = False


class Form:
    def __init__(self, code: str, title: str, items: list, aliases: dict | None = None):
        self.code, self.title, self.items, self.aliases = code, title, items, aliases or {}
        self._index = {}
        for it in items:
            for c in (it.code, *it.aliases):
                self._index.setdefault(str(c), it)

    def find(self, code):
        return self._index.get(str(code))


def _item(d: dict) -> Item:
    return Item(code=str(d["code"]), name=d.get("label", d.get("name", "")), dtype=d.get("dtype", "won"),
                rows=bool(d.get("rows", False)), aliases=tuple(str(a) for a in d.get("aliases", ())),
                total=bool(d.get("total", False)))


@lru_cache(maxsize=None)
def _load(code: str):
    p = DEFS / f"{code}.json"
    if not p.exists():
        return None
    d = json.loads(p.read_text(encoding="utf-8"))
    return Form(str(d["code"]), d.get("title", str(d["code"])), [_item(it) for it in d["items"]], d.get("aliases", {}))


def form_def(form_code):
    """서식 정의. 정의 파일이 없으면 None."""
    return _load(str(form_code))


def item_name(form_code, item_code) -> str:
    form = form_def(form_code)
    it = form.find(item_code) if form is not None else None
    return it.name if it is not None else ""
