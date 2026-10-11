# -*- coding: utf-8 -*-
"""고시 이력으로 조정대상지역·투기과열지구·투기지역 해당 여부를 기준일마다 판정한다.

공고를 효력발생일 순서로 다시 적용한다. 지정된 기간은 지정일부터 해제일 전날까지다.
지구 단위 지정은 지번 경계 자료가 없어 문항 A02 로 묻는다.

시도가 합쳐진 경우(행정구역_대응.json 의 통합. 2026-07-01 전남광주통합특별시)는 옛 시도 이름과 새 시도 이름을 모두 받는다.
고시 이력은 새 이름으로 맞춰 판정하고, 광역시 해당 여부(metro)는 시군구가 통합 전 어느 시도의 것이었는지로 정한다.
통합 근거 법률이 다른 법령의 광역시·도 규정을 그 법령이 개정될 때까지 자치구 관할구역에는 광역시 규정으로,
시·군 관할구역에는 도 규정으로 적용하게 했기 때문이다. 그래서 통합 전후와 적은 이름에 관계없이 결과가 같다.
옛 시도 이름은 제 시군구일 때만(또는 시군구를 비웠을 때만) 새 이름으로 바꾼다. 전라남도 서구처럼 맞지 않는 주소는
바꾸지 않아 고시 이력을 잇지 않고, 통합 뒤 기준일의 metro 는 None 이다.

시의 동 지역을 광역시가 아닌 지역으로 보는 것은 그 특례를 적용한 결과이고, 특례에는 소관 기관이 달리 정할 수 있다는
단서가 있다. 그래서 통합 뒤 기준일의 그런 주소는 metro_caveat 로 알려 판정이 확인사항을 달게 한다.
"""
import json
import os

from yangdo import RULES_DIR
from yangdo.dates import to_date

REGIMES = ("조정대상지역", "투기과열지구", "투기지역")
SIDO_SHORT = {"서울": "서울특별시", "부산": "부산광역시", "대구": "대구광역시", "인천": "인천광역시",
              "광주": "광주광역시", "대전": "대전광역시", "울산": "울산광역시", "세종": "세종특별자치시",
              "경기": "경기도", "강원": "강원특별자치도", "충북": "충청북도", "충남": "충청남도",
              "전북": "전북특별자치도", "전남": "전라남도", "경북": "경상북도", "경남": "경상남도",
              "제주": "제주특별자치도",
              "서울시": "서울특별시", "부산시": "부산광역시", "대구시": "대구광역시", "인천시": "인천광역시",
              "대전시": "대전광역시", "울산시": "울산광역시", "세종시": "세종특별자치시",
              "광주특별시": "전남광주통합특별시"}       # 통합 근거 법률이 정한 약칭. 질문지 시도 목록의 순서가 바뀌지 않게 맨 뒤에 둔다
CAPITAL = {"서울특별시", "인천광역시", "경기도"}
METRO = {"부산광역시", "대구광역시", "대전광역시", "울산광역시", "광주광역시"}    # 광주광역시는 통합 전 날짜에 옛 이름으로 적은 주소에 쓴다
SEJONG = "세종특별자치시"
KNOWN_SIDO = set(SIDO_SHORT.values())
_PLAIN = object()      # 합쳐진 시도와 관계없는 주소


class NeedAnswer(Exception):
    def __init__(self, 문항, 내용, 후보=None):
        super().__init__(내용)
        self.문항 = 문항
        self.내용 = 내용
        self.후보 = list(후보 or [])


def _d(v):
    """날짜 값을 date 로. 글자는 YYYY-MM-DD 만 받고(dates.to_date), 비었거나 다른 모양이면 ValueError."""
    d = to_date(v)
    if d is None:
        raise ValueError("날짜가 비었습니다: %r" % (v,))
    return d


def _clean(s):
    return " ".join(str(s or "").split())


def _prefix(item, value):
    return value == item or value.startswith(item + " ")


class Regions:
    def __init__(self, notices, admin):
        self.admin = admin
        self.rename = {r["옛"]: r for r in admin.get("이름변경", [])}
        self.merged, self.old_merged = {}, {}
        for m in admin.get("통합", []):
            groups = {g["시도"]: g for g in m["옛"]}
            self.merged[m["시도"]] = {"시작": _d(m["시작"]), "옛": groups,
                                    "시군구": {name: g for g in m["옛"] for name in g["시군구"]}}
            for g in m["옛"]:
                self.old_merged[g["시도"]] = {"시작": _d(m["시작"]), "시군구": set(g["시군구"])}
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

    def _sido(self, s, notes=None, on=None, gu=None):
        """시도 이름을 약칭 풀이와 이름변경으로 맞춘다. gu(시군구)를 주면 합쳐지기 전 시도 이름은 제 시군구일 때만 바꾼다."""
        s = _clean(s)
        s = SIDO_SHORT.get(s, s)
        seen = set()
        while s in self.rename and s not in seen:
            seen.add(s)
            r = self.rename[s]
            if on is not None and _d(r["시작"]) > on:
                break
            if gu and s in self.old_merged and gu not in self.old_merged[s]["시군구"]:
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
        gu = _clean((addr or {}).get("시군구"))
        a = {"시도": self._sido((addr or {}).get("시도"), notes, on, gu),
             "시군구": gu, "읍면동": _clean((addr or {}).get("읍면동"))}
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
        if not a["시군구"]:
            raise NeedAnswer("A01", "시군구를 적어 주세요")
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

    def _merged_apply(self, addr, a, on):
        """합쳐진 시도의 주소 a(canon 을 거친 것)에 적용할 규정(통합 표의 적용: 광역시, 도). 정하지 못하면 None,
        합쳐진 시도와 관계없는 주소면 _PLAIN.

        새 이름 주소는 시군구가 표에 있어야 정한다. 옛 시도 이름만 적고 시군구를 비웠으면 그 시도의 적용을 쓴다.
        옛 시도 이름이 새 이름으로 바뀌지 않은 채 남았으면 둘 가운데 하나다. 기준일이 통합 전이면 관계없는 주소로 보아
        종전 규칙(시도 이름만으로 판정)에 맡기고, 통합 뒤(또는 기준일 없음)면 시군구가 그 시도의 것이 아니라 정하지 않는다.
        """
        m = self.merged.get(a["시도"])
        if m is not None:
            g = m["시군구"].get(a["시군구"])
            if g is None and not a["시군구"]:
                raw = _clean((addr or {}).get("시도"))
                g = m["옛"].get(SIDO_SHORT.get(raw, raw))
            return g["적용"] if g else None
        old = self.old_merged.get(a["시도"])
        if old is not None and (on is None or on >= old["시작"]):
            return None
        return _PLAIN

    def metro(self, addr, on=None):
        """수도권이거나 광역시(군 제외)·세종(읍·면 제외)이면 True, 나머지 지역이면 False, 정하지 못하면 None.

        합쳐진 시도는 자치구 관할구역(통합 표의 적용이 광역시)에 광역시 규정을, 시·군 관할구역(적용이 도)에 도 규정을 적용한다.
        """
        on = _d(on) if on is not None else None
        a = self.canon(addr, on=on)
        if a["시도"] not in KNOWN_SIDO:
            return None
        if a["시도"] in CAPITAL:
            return True
        rule = self._merged_apply(addr, a, on)
        if rule is not _PLAIN:
            if rule is None:
                return None
            return rule == "광역시" and not a["시군구"].endswith("군")
        if a["시도"] in METRO:
            return not a["시군구"].endswith("군")
        if a["시도"] == SEJONG:
            first = a["읍면동"].split(" ")[0] if a["읍면동"] else ""
            return not (first.endswith("읍") or first.endswith("면"))
        return False

    def metro_caveat(self, addr, on):
        """metro 가 False 인 까닭이 합쳐진 시도의 시·군 관할구역 특례에 달린 주소면 그 시도 이름, 아니면 None.

        통합 뒤 기준일에 적용이 도인 관할구역 가운데 군도 읍·면도 아닌 곳(시의 동 지역, 시군구를 비운 옛 도 이름 주소)이다.
        특례를 적용하지 않고 합쳐진 시도 전체를 광역시로 읽으면 이런 곳만 결과가 달라진다. 군과 읍·면은 광역시 안에서도
        빼는 지역이라 어느 쪽으로 읽어도 같고, 통합 전 기준일에는 합쳐진 시도가 없었다.
        """
        on = _d(on)
        a = self.canon(addr, on=on)
        m = self.merged.get(a["시도"])
        if m is None or on < m["시작"] or self._merged_apply(addr, a, on) != "도":
            return None
        first = a["읍면동"].split(" ")[0] if a["읍면동"] else ""
        if a["시군구"].endswith("군") or first.endswith("읍") or first.endswith("면"):
            return None
        return a["시도"]

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
