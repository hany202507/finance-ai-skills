# -*- coding: utf-8 -*-
"""법정동코드 찾기. 전자신고 파일의 법정동코드 칸(10자리, 필수)을 채우고 검증기가 코드 존재를 검사하는 데 쓴다.

efile/법정동코드.json 은 행정표준코드 법정동코드 전체자료의 「존재」 행만 담는다(scripts/refresh/import_bjd.py).
이름을 공백으로 나눠 (시도, 시군구, 읍면동) 색인을 만든다. 읍·면 아래 리는 읍면동 칸에 「○○읍 ○○리」 로 받는다.
시군구가 일반구인 시는 「수원시 장안구」 처럼 두 낱말을 그대로 시군구로 묶는다. 세종은 시군구가 없어 빈 글자다.

찾기 규칙
- 적은 이름과 같은 법정동이 있으면 그 코드 하나만 후보다(영등포동 은 영등포동1가와 다른 법정동이다)
- 같은 이름이 없으면 「성수동1가·2가」 처럼 숫자 가가 붙은 이름과 「기암리(岐岩)」 처럼 한자가 붙은 이름을 후보로 모은다
- lookup 은 후보가 정확히 하나일 때만 코드를 돌려주고, 없거나 여럿이면 None 이다. 어느 쪽인지는 candidates 로 본다
- 옛 시도 이름은 행정구역_대응.json 의 이름변경 중 등급이 ★★★ 인 것만 on 날짜(없으면 항상) 이후에 지금 이름으로 바꾼다.
  ★★☆ 인 광주광역시·전라남도는 바꾸지 않아 None 이고, 신고인에게 법정동코드를 묻는 질문으로 넘어간다
"""
import json
import os
import re

from yangdo import RULES_DIR, SKILL_DIR
from yangdo.dates import to_date

EFILE_DIR = os.path.join(SKILL_DIR, "efile")
TABLE_FILE = "법정동코드.json"
RENAME_FILE = "행정구역_대응.json"
RENAME_GRADE = "★★★"
_VARIANT = r"(?:[0-9]+가|\([^()]*\))"


class BjdError(Exception):
    pass


def _clean(s):
    return " ".join(str(s or "").split())


def parse(codes):
    """{코드: 이름} 을 {코드: (시도, 시군구, 읍면동)} 으로 나눈다. 시도·시군구 행의 읍면동은 빈 글자다.

    코드는 시도 2 + 시군구 3 + 읍면동 3 + 리 2 자리다. 시군구 행은 앞 5자리 뒤가 모두 0 이고(세종은 3611000000 이
    시도 행을 겸한다), 나머지 행은 앞 5자리가 같은 시군구 행의 이름 뒤에 읍면동 이름이 붙는다.
    """
    names = {}
    for code, name in codes.items():
        if not (isinstance(code, str) and len(code) == 10 and code.isdigit()):
            raise BjdError("법정동코드는 10자리 숫자여야 합니다: %r" % (code,))
        names[code] = _clean(name)
        if not names[code]:
            raise BjdError("이름이 빈 행이 있습니다: %s" % code)
    parts, seen = {}, {}
    for code in sorted(names):
        name = names[code]
        sido = name.split(" ")[0]
        if code[5:] == "00000":
            parts[code] = (sido, name[len(sido) + 1:], "")
        else:
            head = names.get(code[:5] + "00000")
            if head is None:
                raise BjdError("시군구 행이 없습니다: %s %s" % (code, name))
            if not name.startswith(head + " "):
                raise BjdError("이름이 시군구 행 이름 「%s」 으로 시작하지 않습니다: %s %s" % (head, code, name))
            parts[code] = (sido, head[len(sido) + 1:], name[len(head) + 1:])
        if parts[code] in seen:
            raise BjdError("같은 이름의 행이 둘 있습니다: %s, %s %s" % (seen[parts[code]], code, name))
        seen[parts[code]] = code
    return parts, names


class Bjd:
    def __init__(self, codes, renames=None):
        self._parts, self._names = parse(codes)
        self._index = {}
        for code, (sido, gu, dong) in self._parts.items():
            if dong:
                self._index.setdefault((sido, gu), {})[dong] = code
        self._renames = {r["옛"]: r for r in (renames or []) if r.get("등급") == RENAME_GRADE}

    def exists(self, code):
        """지금 존재하는 법정동코드인지. 시도·시군구·읍면동·리 어느 단계든 존재 행이면 참이다."""
        return isinstance(code, str) and code in self._names

    def name(self, code):
        """코드의 전체 이름(공백으로 이은 글자). 없으면 None."""
        return self._names.get(code) if isinstance(code, str) else None

    def split(self, code):
        """코드를 (시도, 시군구, 읍면동) 으로. 없으면 None."""
        return self._parts.get(code) if isinstance(code, str) else None

    def _sido(self, sido, on):
        s = _clean(sido)
        r = self._renames.get(s)
        if r and (on is None or to_date(r["시작"]) <= on):
            return r["새"]
        return s

    def candidates(self, 시도, 시군구, 읍면동, on=None):
        on = to_date(on)
        dong = _clean(읍면동)
        names = self._index.get((self._sido(시도, on), _clean(시군구)))
        if not names or not dong:
            return []
        if dong in names:
            return [names[dong]]
        variant = re.compile(re.escape(dong) + _VARIANT)
        return sorted(code for name, code in names.items() if variant.fullmatch(name))

    def lookup(self, 시도, 시군구, 읍면동, on=None):
        c = self.candidates(시도, 시군구, 읍면동, on=on)
        return c[0] if len(c) == 1 else None


def load(efile_dir=None, rules_dir=None):
    with open(os.path.join(efile_dir or EFILE_DIR, TABLE_FILE), encoding="utf-8") as f:
        table = json.load(f)
    codes = table.get("코드")
    if not isinstance(codes, dict) or not codes:
        raise BjdError("%s 에 코드 표가 없습니다" % TABLE_FILE)
    with open(os.path.join(rules_dir or RULES_DIR, RENAME_FILE), encoding="utf-8") as f:
        renames = json.load(f).get("이름변경", [])
    return Bjd(codes, renames)
