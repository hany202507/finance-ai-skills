# -*- coding: utf-8 -*-
"""고시 이력으로 조정대상지역·투기과열지구·투기지역 해당 여부를 기준일마다 판정한다.

공고를 효력발생일 순서로 다시 적용한다. 지정된 기간은 지정일부터 해제일 전날까지다.
지구 단위 지정은 지번 경계 자료가 없어 문항 A02 로 묻는다.
"""
import json
import os
from datetime import date

from yangdo import RULES_DIR

REGIMES = ("조정대상지역", "투기과열지구", "투기지역")
SIDO_SHORT = {"서울": "서울특별시", "부산": "부산광역시", "대구": "대구광역시", "인천": "인천광역시",
              "광주": "광주광역시", "대전": "대전광역시", "울산": "울산광역시", "세종": "세종특별자치시",
              "경기": "경기도", "강원": "강원특별자치도", "충북": "충청북도", "충남": "충청남도",
              "전북": "전북특별자치도", "전남": "전라남도", "경북": "경상북도", "경남": "경상남도",
              "제주": "제주특별자치도",
              "서울시": "서울특별시", "부산시": "부산광역시", "대구시": "대구광역시", "인천시": "인천광역시",
              "대전시": "대전광역시", "울산시": "울산광역시", "세종시": "세종특별자치시"}
CAPITAL = {"서울특별시", "인천광역시", "경기도"}
METRO = {"부산광역시", "대구광역시", "대전광역시", "울산광역시", "광주광역시"}
SEJONG = "세종특별자치시"
UNKNOWN_METRO = {"전남광주통합특별시"}
KNOWN_SIDO = set(SIDO_SHORT.values()) | {"전남광주통합특별시"}


class NeedAnswer(Exception):
    def __init__(self, 문항, 내용, 후보=None):
        super().__init__(내용)
        self.문항 = 문항
        self.내용 = 내용
        self.후보 = list(후보 or [])


def _d(v):
    return v if isinstance(v, date) else date.fromisoformat(str(v))


def _clean(s):
    return " ".join(str(s or "").split())


def _prefix(item, value):
    return value == item or value.startswith(item + " ")


class Regions:
    def __init__(self, notices, admin):
        self.admin = admin
        self.rename = {r["옛"]: r for r in admin.get("이름변경", [])}
        self.events = {}
        for name in REGIMES:
            evs = (notices.get(name) or {}).get("이벤트", [])
            order = sorted(range(len(evs)), key=lambda i: (evs[i]["효력발생일"], i))
            out = []
            for i in order:
                e = dict(evs[i])
                e["지역"] = [self._canon_region(r) for r in evs[i]["지역"]]
                out.append(e)
            self.events[name] = out

    def _sido(self, s, notes=None, on=None):
        s = _clean(s)
        s = SIDO_SHORT.get(s, s)
        seen = set()
        while s in self.rename and s not in seen:
            seen.add(s)
            r = self.rename[s]
            if on is not None and _d(r["시작"]) > on:
                break
            if notes is not None and r.get("등급") != "★★★":
                notes.append("%s 를 %s 로 바꿔 판정했다(%s, %s)" % (s, r["새"], r["등급"], r.get("근거", "")))
            s = r["새"]
        return s

    def _canon_region(self, r):
        r2 = dict(r)
        r2["시도"] = self._sido(r["시도"])
        r2["시군구"] = SEJONG if r2["시도"] == SEJONG else _clean(r["시군구"])
        return r2

    def canon(self, addr, notes=None, on=None):
        a = {"시도": self._sido((addr or {}).get("시도"), notes, on),
             "시군구": _clean((addr or {}).get("시군구")), "읍면동": _clean((addr or {}).get("읍면동"))}
        if a["시도"] == SEJONG:
            a["시군구"] = SEJONG
        return a

    def _check_reorg(self, a, on):
        for s in self.admin.get("구분할", []):
            if a["시도"] == self._sido(s["시도"]) and a["시군구"] == s["시군구"] and on >= _d(s["시작"]):
                raise NeedAnswer("A01", "%s %s 는 %s 부터 구로 나뉘었습니다. 구 이름까지 적어 주세요"
                                 % (s["시도"], s["시군구"], s["시작"]))
        for s in self.admin.get("재편", []):
            if a["시도"] != self._sido(s["시도"]):
                continue
            new_only = set(s["새"]) - set(s["옛"])
            old_only = set(s["옛"]) - set(s["새"])
            if a["시군구"] in new_only and on < _d(s["시작"]):
                raise NeedAnswer("A03", "%s 는 %s 에 생긴 이름입니다. %s 당시 주소(옛 구 이름)를 알려 주세요"
                                 % (a["시군구"], s["시작"], on))
            if a["시군구"] in old_only and on >= _d(s["시작"]):
                raise NeedAnswer("A01", "%s 는 %s 에 없어진 이름입니다. 지금 구 이름으로 적어 주세요"
                                 % (a["시군구"], s["시작"]))

    def _match(self, r, a, 지구):
        """True, False, 또는 지구 답에 달렸으면 '?'."""
        if r["시도"] == a["시도"] and " " not in a["시군구"] and r["시군구"].startswith(a["시군구"] + " "):
            raise NeedAnswer("A01", "%s 는 구마다 지정이 갈립니다. 구 이름까지 적어 주세요" % a["시군구"])
        if r["시도"] != a["시도"] or not _prefix(r["시군구"], a["시군구"]):
            return False
        if r.get("범위") == "전역":
            return True
        inc, exc = r.get("포함_읍면동") or [], r.get("제외_읍면동") or []
        if (inc or exc) and not a["읍면동"]:
            raise NeedAnswer("A01", "%s 는 읍면동에 따라 지정이 갈립니다. 읍면동까지 적어 주세요" % a["시군구"])
        for items in (inc, exc):
            if items and not any(_prefix(i, a["읍면동"]) for i in items) and \
                    any(i.startswith(a["읍면동"] + " ") for i in items):
                raise NeedAnswer("A01", "%s %s 는 리 단위로 지정이 갈립니다. 리 이름까지 적어 주세요"
                                 % (a["시군구"], a["읍면동"]))
        if inc and not any(_prefix(i, a["읍면동"]) for i in inc):
            return False
        if exc and any(_prefix(i, a["읍면동"]) for i in exc):
            return False
        pz, ez = r.get("포함_지구") or [], r.get("제외_지구") or []
        if pz or ez:
            if 지구 not in ("예", "아니오"):
                return "?"
            inside = 지구 == "예"
            return inside if pz else not inside
        return True

    def status(self, regime, addr, on, 지구해당=None):
        on = _d(on)
        notes = []
        a = self.canon(addr, notes)
        if a["시도"] not in KNOWN_SIDO:
            raise NeedAnswer("A01", "시도 이름 %s 를 알 수 없습니다. 서울특별시·경기도처럼 적어 주세요" % a["시도"])
        self._check_reorg(a, on)
        cur, pend = None, None
        for e in self.events[regime]:
            if _d(e["효력발생일"]) > on:
                break
            for r in e["지역"]:
                m = self._match(r, a, 지구해당)
                if m == "?":
                    pend = r
                elif m:
                    cur = e if e["구분"] == "지정" else None
                    pend = None
        if pend is not None:
            raise NeedAnswer("A02", "%s %s 가 지구 안에 있는지에 따라 지정이 갈립니다" % (a["시군구"], a["읍면동"]),
                             후보=(pend.get("포함_지구") or []) + (pend.get("제외_지구") or []))
        return {"지정": cur is not None, "공고": cur.get("공고") if cur else None,
                "공고일": cur.get("공고일") if cur else None,
                "효력발생일": cur.get("효력발생일") if cur else None, "주석": notes}

    def designated_list(self, regime, on):
        """기준일에 지정된 지역을 공고에 나온 가장 작은 단위 이름으로 낸다(현황표 대조용).

        이름마다 공고에 나온 읍면동과 「기타동」, 지구 답 예·아니오를 넣어 status 를 돌려
        하나라도 지정이면 목록에 넣는다. 그래서 일부 지정·일부 해제가 status 와 같은 규칙으로 처리된다.
        """
        on = _d(on)
        regs = [r for e in self.events[regime] if _d(e["효력발생일"]) <= on for r in e["지역"]]
        keys = sorted({(r["시도"], r["시군구"]) for r in regs})
        leaves = [k for k in keys
                  if not any(o != k and o[0] == k[0] and o[1].startswith(k[1] + " ") for o in keys)]
        out = []
        for k in leaves:
            items = {"기타동"}
            for r in regs:
                if r["시도"] == k[0] and _prefix(r["시군구"], k[1]):
                    items |= set(r.get("포함_읍면동") or []) | set(r.get("제외_읍면동") or [])
            if any(self._designated_quiet(regime, k, emd, on) for emd in sorted(items)):
                out.append("%s %s" % k)
        return out

    def _designated_quiet(self, regime, k, emd, on):
        for z in ("예", "아니오"):
            try:
                if self.status(regime, {"시도": k[0], "시군구": k[1], "읍면동": emd}, on, z)["지정"]:
                    return True
            except NeedAnswer:
                pass
        return False

    def metro(self, addr, on=None):
        a = self.canon(addr, on=_d(on) if on is not None else None)
        if a["시도"] in CAPITAL:
            return True
        if a["시도"] in UNKNOWN_METRO:
            return None
        if a["시도"] in METRO:
            return not a["시군구"].endswith("군")
        if a["시도"] == SEJONG:
            first = a["읍면동"].split(" ")[0] if a["읍면동"] else ""
            return not (first.endswith("읍") or first.endswith("면"))
        return False

    def capital(self, addr):
        return self.canon(addr)["시도"] in CAPITAL


def load(rules_dir=None):
    rules_dir = rules_dir or RULES_DIR
    notices = {}
    for name in REGIMES:
        p = os.path.join(rules_dir, "고시", name + ".json")
        if not os.path.exists(p):
            raise FileNotFoundError("고시 파일이 없다: %s" % p)
        with open(p, encoding="utf-8") as f:
            notices[name] = json.load(f)
    with open(os.path.join(rules_dir, "행정구역_대응.json"), encoding="utf-8") as f:
        admin = json.load(f)
    return Regions(notices, admin)
