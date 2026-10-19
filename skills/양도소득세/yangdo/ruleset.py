# -*- coding: utf-8 -*-
"""규칙세트 읽기. 판정·계산 코드는 이 모듈로만 세율·공제율·기준금액·기한을 얻는다."""
import hashlib
import json
import os
from decimal import Decimal

from yangdo import RULES_DIR
from yangdo.dates import Holidays, to_date

EDITION_FILES = ["ruleset.json", "코드표.json", "행정구역_대응.json",
                 "고시/조정대상지역.json", "고시/투기과열지구.json", "고시/투기지역.json"]
# 공휴일 표는 신고기한을 옮길 때 쓴다(dates.filing_deadline). 없으면 공휴일을 모르는 규칙세트가 된다
HOLIDAY_FILE = "공휴일.json"
# 서식 판·전자신고 규격 판(설계 ① 다섯 묶음)과 공휴일 표. rules 폴더 기준 상대 경로. 판 id 에 들어가지만,
# rules 폴더만 따로 쓰는 경우(시험의 임시 사본, --rules)가 있어 파일이 없을 때는 대조하지 않는다.
# 서식 매핑(신고값 키 → 서식 칸)과 필드목록(칸 좌표)도 넣는다. 이 파일이 바뀌면 같은 신고값에서 다른 신고서가 나오는데
# 서식판.json 의 원본 sha256 만으로는 잡히지 않는다. 폴더에 파일을 더하면 이 목록에도 더한다(시험이 폴더와 견준다)
FORM_TABLES = ["../forms/매핑/본지.json", "../forms/매핑/부표1.json", "../forms/매핑/부표3.json", "../forms/매핑/지방.json",
               "../forms/필드목록/필드목록_별지84_신고및납부계산서.json",
               "../forms/필드목록/필드목록_별지84부표1_양도소득금액계산명세서.json",
               "../forms/필드목록/필드목록_별지84부표3_2_취득가액및필요경비계산상세명세서.json",
               "../forms/필드목록/필드목록_별지84부표3_취득가액및필요경비계산상세명세서.json",
               "../forms/필드목록/필드목록_지방세_별지40의11_신고및납부계산서.json"]
EDITION_EXTRA = ["../forms/서식판.json", "../efile/법정동코드.json", "../efile/codes_c116300.json", HOLIDAY_FILE] + FORM_TABLES


class RuleError(Exception):
    pass


def canonical_hash(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    s = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def write_edition(rules_dir, 확인일):
    files = {p: canonical_hash(os.path.join(rules_dir, p))
             for p in EDITION_FILES + EDITION_EXTRA if os.path.exists(os.path.join(rules_dir, p))}
    if "ruleset.json" not in files:
        raise RuleError("ruleset.json 이 없어 기준정보 판을 만들 수 없다")
    body = json.dumps(files, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    ed = {"id": hashlib.sha256(body.encode("utf-8")).hexdigest()[:16], "확인일": 확인일, "파일": files}
    with open(os.path.join(rules_dir, "기준정보판.json"), "w", encoding="utf-8") as f:
        json.dump(ed, f, ensure_ascii=False, indent=1, sort_keys=True)
    return ed


def label(조, 항="", 공포번호=None):
    """조문 이름. label("47의2", "①2호") 는 「제47조의2①2호」, 부칙은 「부칙(제N호)」."""
    if 조 == "부칙":
        return "부칙(제%s호)" % 공포번호
    if "의" in 조:
        a, b = 조.split("의", 1)
        return "제%s조의%s%s" % (a, b, 항 or "")
    return "제%s조%s" % (조, 항 or "")


_label = label   # 옛 이름. scripts/build_ruleset.py 가 쓴다


def _conv(unit, v):
    if unit == "근거" or v is None:
        return None
    if unit in ("원", "년", "개월", "월", "일"):
        return int(v)
    if unit == "율":
        return Decimal(str(v))
    if unit == "세율표":
        return [[int(a), int(b), Decimal(str(c))] for a, b, c in v]
    if unit == "율표":
        return [[int(a), Decimal(str(b))] for a, b in v]
    return v  # 날짜는 문자열 그대로


def _in_force(pans, on):
    """대조에 통과한 판 중 on 에 시행 중이던 판의 시행일. on 이 모든 판보다 이르면(부칙 근거 등) 가장 이른 판."""
    dates = sorted(p["시행일"] for p in pans)
    if not dates:
        return None
    before = [x for x in dates if x <= str(to_date(on))]
    return before[-1] if before else dates[0]


class Ruleset:
    def __init__(self, data, edition, 공휴일=None):
        self.data = data
        self.edition = edition
        self.공휴일 = 공휴일  # dates.Holidays 또는 None(표 파일이 없는 rules 폴더)

    @property
    def 판id(self):
        return self.edition["id"]

    @property
    def 확인일(self):
        return self.edition["확인일"]

    @property
    def 기준시작(self):
        return self.data["기준시작"]

    def _rule(self, key):
        try:
            return self.data["규칙"][key]
        except KeyError:
            raise RuleError("규칙세트에 %s 가 없다" % key)

    def entry(self, key, on):
        d = to_date(on)
        for e in self._rule(key)["이력"]:
            s, t = to_date(e["시작"]), to_date(e["끝"])
            if (s is None or s <= d) and (t is None or d <= t):
                return e
        raise RuleError("%s: %s 에 적용할 값이 없다" % (key, d))

    def value(self, key, on):
        return _conv(self._rule(key)["단위"], self.entry(key, on)["값"])

    def cite(self, key, on):
        out = []
        for g in self.entry(key, on)["근거"]:
            out.append({"key": key, "법령": g["법령"], "조항": _label(g["조"], g.get("항", ""), g.get("공포번호")),
                        "시행일": _in_force(g.get("판", []), on),
                        "발췌": g["발췌"], "URL": g["URL"]})
        return out

    def notes(self, key, on):
        d = to_date(on)
        out = []
        for u in self.entry(key, on).get("예정변경", []):
            if d >= to_date(u["시행일"]):
                out.append("%s %s 가 %s 시행예정 개정으로 바뀔 수 있다. 바뀐 값은 확인하지 않았다(%s)"
                           % (u["법령"], _label(u["조"]), u["시행일"], u["내용"]))
        for p in self.data.get("계류", []):
            if key in p["영향키"] and d >= to_date(p["시작"]):
                out.append("계류: %s (%s, %s)" % (p["내용"], p["출처"], p["등급"]))
        return out


def load(rules_dir=None):
    rules_dir = rules_dir or RULES_DIR
    ed_path = os.path.join(rules_dir, "기준정보판.json")
    if not os.path.exists(ed_path):
        raise RuleError("기준정보판.json 이 없다. python scripts/build_ruleset.py build 를 먼저 돌려라")
    with open(ed_path, encoding="utf-8") as f:
        ed = json.load(f)
    for p, h in ed["파일"].items():
        fp = os.path.join(rules_dir, p)
        if p in EDITION_EXTRA and not os.path.exists(fp):
            continue
        if not os.path.exists(fp) or canonical_hash(fp) != h:
            raise RuleError("%s 가 기준정보 판 %s 과 다르다. python scripts/build_ruleset.py 판 을 다시 돌려라" % (p, ed["id"]))
    holidays = None
    hp = os.path.join(rules_dir, HOLIDAY_FILE)
    if os.path.exists(hp):
        if HOLIDAY_FILE not in ed["파일"]:  # 해시로 대조하지 않은 표는 쓰지 않는다
            raise RuleError("%s 이 기준정보 판 %s 에 없다. python scripts/build_ruleset.py 판 을 다시 돌려라" % (HOLIDAY_FILE, ed["id"]))
        with open(hp, encoding="utf-8") as f:
            holidays = Holidays(json.load(f))
    with open(os.path.join(rules_dir, "ruleset.json"), encoding="utf-8") as f:
        return Ruleset(json.load(f), ed, holidays)
