# -*- coding: utf-8 -*-
"""법정동코드 찾기. 전자신고 파일의 법정동코드 칸(10자리, 필수)을 채우고 검증기가 코드 존재를 검사하는 데 쓴다.

efile/법정동코드.json 은 행정표준코드 법정동코드 전체자료의 「존재」 행만 담는다(scripts/refresh/import_bjd.py).
이름을 공백으로 나눠 (시도, 시군구, 읍면동) 색인을 만든다. 읍·면 아래 리는 읍면동 칸에 「○○읍 ○○리」 로 받는다.
시군구가 일반구인 시는 「수원시 장안구」 처럼 두 낱말을 그대로 시군구로 묶는다. 세종은 시군구가 없어 빈 글자다.

찾기 규칙
- 적은 이름과 같은 법정동이 있으면 그 코드 하나만 후보다(영등포동 은 영등포동1가와 다른 법정동이다)
- 같은 이름이 없으면 「성수동1가·2가」 처럼 숫자 가가 붙은 이름과 「기암리(岐岩)」 처럼 한자가 붙은 이름을 후보로 모은다.
  리 이름이면 「창선1리·창선2리」 처럼 「리」 앞에 숫자가 붙은 이름도 모은다(창선리 로 적었을 때)
- lookup 은 후보가 정확히 하나일 때만 코드를 돌려주고, 없거나 여럿이면 None 이다. 어느 쪽인지는 candidates 로 본다
- 시도 약칭(서울, 광주특별시 등)은 지역 판정과 같은 표(regions.SIDO_SHORT)로 푼다
- 옛 시도 이름은 행정구역_대응.json 의 이름변경 중 등급이 ★★★ 인 것만 on 날짜(없으면 항상) 이후에 지금 이름으로 바꾼다.
- 시도 둘이 합쳐진 경우(같은 파일의 통합. 2026-07-01 광주광역시·전라남도 → 전남광주통합특별시)는 시군구·읍면동 이름이
  통합 전과 같아 옛 시도 이름으로 적은 주소도 on 날짜가 통합일 이후면 새 코드를 찾는다. 옛 시도 이름과 시군구가 맞지 않으면
  (전라남도 서구) 바꾸지 않는다. on 날짜가 통합일 전이면 옛 이름 그대로 찾는데, 폐지된 옛 코드는 표에 없어 None 이다
- 표에는 「존재」 행만 있어서 시군구가 바뀌며 폐지된 이름은 찾지 못한다. 원자료에서 「폐지」인 예: 인천광역시 중구 중앙동1가
  (2811010100. 중구가 폐지되어 지금은 제물포구 중앙동1가 2812510800), 경상남도 창원시 의창구 신월동(4812112600. 지금은
  성산구 신월동 4812313600). 이런 주소는 지금의 시군구 이름으로 적거나 법정동코드 10자리를 직접 적는다. 시군구가 바뀐
  이름을 지금 이름으로 잇는 표는 없다(행정구역_대응.json 은 시도 이름만 다룬다)
"""
import json
import os
import re

from yangdo import RULES_DIR, SKILL_DIR
from yangdo.dates import to_date
from yangdo.regions import SIDO_SHORT

EFILE_DIR = os.path.join(SKILL_DIR, "efile")
TABLE_FILE = "법정동코드.json"
RENAME_FILE = "행정구역_대응.json"
RENAME_GRADE = "★★★"
_VARIANT = r"(?:[0-9]+가|\([^()]*\))"
_NUMBERED_RI = r"[0-9]+리"          # 「창선리」 로 적은 이름에 맞출 「창선1리」 의 뒷부분(앞부분은 「리」 를 뗀 이름)


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
    def __init__(self, codes, renames=None, merged=None):
        self._parts, self._names = parse(codes)
        self._index = {}
        for code, (sido, gu, dong) in self._parts.items():
            if dong:
                self._index.setdefault((sido, gu), {})[dong] = code
        self._renames = {r["옛"]: r for r in (renames or []) if r.get("등급") == RENAME_GRADE}
        # 합쳐지기 전 시도 이름 → 그 시도에 있던 시군구 이름. 여기 든 옛 이름은 제 시군구일 때만 새 이름으로 바꾼다
        self._old_districts = {g["시도"]: set(g["시군구"]) for m in (merged or []) for g in m["옛"]}

    def exists(self, code):
        """지금 존재하는 법정동코드인지. 시도·시군구·읍면동·리 어느 단계든 존재 행이면 참이다."""
        return isinstance(code, str) and code in self._names

    def name(self, code):
        """코드의 전체 이름(공백으로 이은 글자). 없으면 None."""
        return self._names.get(code) if isinstance(code, str) else None

    def split(self, code):
        """코드를 (시도, 시군구, 읍면동) 으로. 없으면 None."""
        return self._parts.get(code) if isinstance(code, str) else None

    def _sido(self, sido, gu, on):
        s = _clean(sido)
        s = SIDO_SHORT.get(s, s)
        r = self._renames.get(s)
        if r and (on is None or to_date(r["시작"]) <= on):
            if s in self._old_districts and gu not in self._old_districts[s]:
                return s
            return r["새"]
        return s

    def candidates(self, 시도, 시군구, 읍면동, on=None):
        on = to_date(on)
        dong = _clean(읍면동)
        gu = _clean(시군구)
        names = self._index.get((self._sido(시도, gu, on), gu))
        if not names or not dong:
            return []
        if dong in names:
            return [names[dong]]
        pattern = re.escape(dong) + _VARIANT
        if dong.endswith("리") and len(dong.split(" ")[-1]) > 1:
            pattern += "|" + re.escape(dong[:-1]) + _NUMBERED_RI
        variant = re.compile(pattern)
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
        admin = json.load(f)
    return Bjd(codes, admin.get("이름변경", []), admin.get("통합", []))
