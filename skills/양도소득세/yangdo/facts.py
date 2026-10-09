# -*- coding: utf-8 -*-
"""사실관계 JSON 검사. 원자료 날짜로 취득·양도 시기를 정하고, 범위와 빠진 사실을 모은다.

자료형은 질문지/문항.json 의 답형식 하나로 검사한다. form_problem 이 그 표이고, 질문지 answer() 와 prepare() 가 같이 쓴다.
엔진이 읽는 예아니오·선택·복수선택 키에 다른 자료형이 들어오면(문자열 「false」, 「해당없음」 글자 하나 등) 그 문항을 되묻는다.
질문지가 묻는데 엔진이 읽지 않는 키는 COLLECT_ONLY 에 이유와 함께 적는다. 읽는 키는 계산하거나, 계산하지 않고
다루지않음(계획 5)이나 확인사항으로 돌린다. tests/test_scope_contract.py 가 이 약속을 지키는지 본다.
"""
import json
import re
from datetime import date
from fractions import Fraction

from yangdo import QUESTIONS_PATH, dates, 첫양도일
from yangdo.regions import CAPITAL, SIDO_SHORT

PERSONAL_KEYS = {"성명", "주민등록번호", "외국인등록번호", "전화번호", "휴대전화", "환급계좌", "계좌번호", "이메일", "양수인",
                 "주소", "도로명주소", "지번주소", "상세주소", "거주지"}
RRN = re.compile(r"(?<!\d)\d{6}-?[1-8]\d{6}(?!\d)")
ADDRESS_KEYS = {"소재지", "취득당시소재지"}
SHARE_MSG = "지분은 단독 또는 {구분: 공동, 분자, 분모} 로 적습니다"
OK_LAND_USE = ("사업용", "주택부수토지")
의제취득기준 = date(1985, 1, 1)  # 국세청 작성요령 의제취득일. 이 전 취득은 계획 5
WHOLE_MSG = "금액은 원 단위 정수로 적습니다"
NONNEG_MSG = "금액은 0 이상이어야 합니다"
EMPTY_MSG = "금액이 비어 있습니다"
SHAPE_PRICE_MSG = "기준시가는 취득과 양도 칸마다 토지·건물·주택 금액을 적습니다"
EXPENSE_GROUPS = (("취득부대", "M08"), ("자본적지출", "M09"), ("기타", "M10"), ("양도비", "M11"))
RESIDENCE_MSG = "거주기간은 [전입일, 전출일] 두 날짜를 한 구간으로 적습니다"
FORM_MSG = "%s 의 값 형식이 맞지 않습니다. 받는 형식: %s"
FORM_KINDS = ("예아니오", "선택", "복수선택", "목록")
CHOICE_DICT_KEYS = {"자산[].지분"}  # 선택 문항인데 {구분: 공동, 분자, 분모} 묶음으로도 답하는 키
LAND_NAMES = ("대지면적", "정착면적", "용도지역")
LAND_MSG = "부수토지는 대지면적·정착면적(제곱미터)·용도지역을 이름으로 한 dict 로 적습니다"

# 질문지(범위 계획1)가 묻지만 엔진이 읽지 않는 키. 문항.json 의 키 그대로 적고 읽지 않는 이유를 한 줄로 적는다.
# 여기 든 키는 prepare 의 자료형 검사도 받지 않는다(answer() 는 받는다). 엔진이 읽기 시작하면 이 표에서 지운다.
# tests/test_scope_contract.py 가 표에 든 키를 yangdo 가 읽으면 시험이 깨지게 해서 낡은 항목이 남지 않게 한다.
COLLECT_ONLY = {
    "연간.기신고": "같은 해 다른 양도는 확인사항(연간.다른양도)으로만 안내한다. 기신고 금액은 합산하지 않는다",
    "자산[].주택유형": "질문지 보이는조건(A05, A06, L01)에만 쓴다. 판정은 주거사용개시일을 직접 읽는다",
    "자산[].면적": "서식 기재용이다. 판정과 계산에 쓰지 않는다",
    "세대.세대원": "1세대 판정은 배우자(H01)와 1세대요건(H02)으로 한다. 세대원 목록은 읽지 않는다",
    "자산[].거주_일부미거주": "거주요건은 거주기간 구간(H07)으로만 판정한다. 일부 미거주 표시는 읽지 않는다",
    "세대.주택목록[신규].취득원인": "신규 주택의 취득일은 주택 목록(H04)의 취득일을 쓴다. 취득 원인은 읽지 않는다",
    "자산[].취득.상대방유형": "환산 전에 실제 금액을 찾아보라는 안내용이다. 계산에 쓰지 않는다",
    "자산[].토지등급": "취득 당시 토지 기준시가 환산은 하지 않는다. 입력한 기준시가를 그대로 쓴다",
    "자산[].토지거래허가": "허가 신청일과 허가일은 한시배제 나·다목 판정(계획 5)에 쓴다. 지금은 토지거래허가대상(X05) 답만 확인사항으로 안내한다",
}


class FactsError(Exception):
    pass


class Missing(Exception):
    def __init__(self, 문항, 자산, 내용):
        super().__init__(내용)
        self.문항, self.자산, self.내용 = 문항, 자산, 내용

    def to_dict(self):
        return {"문항": self.문항, "자산": self.자산, "내용": self.내용}


class OutOfScope(Exception):
    def __init__(self, 자산, 내용, 계획):
        super().__init__(내용)
        self.자산, self.내용, self.계획 = 자산, 내용, 계획

    def to_dict(self):
        return {"자산": self.자산, "내용": self.내용, "계획": self.계획}


def _walk_keys(o):
    if isinstance(o, dict):
        for k, v in o.items():
            yield k
            yield from _walk_keys(v)
    elif isinstance(o, list):
        for v in o:
            yield from _walk_keys(v)


def _walk_values(o):
    if isinstance(o, dict):
        for v in o.values():
            yield from _walk_values(v)
    elif isinstance(o, list):
        for v in o:
            yield from _walk_values(v)
    elif isinstance(o, str):
        yield o


def _walk_pairs(o):
    if isinstance(o, dict):
        for k, v in o.items():
            yield k, v
            yield from _walk_pairs(v)
    elif isinstance(o, list):
        for v in o:
            yield from _walk_pairs(v)


def check_personal(f):
    bad = PERSONAL_KEYS & set(_walk_keys(f))
    if bad:
        raise FactsError("인적사항 %s 는 사실관계에 넣지 않습니다. 신고인.json 에 따로 두십시오" % sorted(bad))
    if any(k in ADDRESS_KEYS and v is not None and not isinstance(v, dict) for k, v in _walk_pairs(f)):
        raise FactsError("소재지는 시도·시군구·읍면동으로 나눠 적습니다. 주소 문자열은 넣지 않습니다")
    if any(RRN.search(v) for v in _walk_values(f)):
        raise FactsError("주민등록번호로 보이는 값은 사실관계에 넣지 않습니다")


def get(obj, path, default=None):
    node = obj
    for p in path.split("."):
        if not isinstance(node, dict) or node.get(p) is None:
            return default
        node = node[p]
    return node


def need(obj, path, 문항, 자산id, 내용=None):
    v = get(obj, path)
    if v is None:
        raise Missing(문항, 자산id, 내용 or "%s 가 필요합니다" % path)
    return v


def split_key(key):
    """문항 키가 놓인 곳. ('자산'|'주택'|'전역', 경로 조각). 자산[] 은 자산마다, 세대.주택목록[] 은 집마다 있다."""
    parts = key.split(".")
    if parts[0] == "자산[]":
        return "자산", parts[1:]
    if parts[0] == "세대" and len(parts) > 1 and parts[1] in ("주택목록[]", "주택목록[신규]"):
        return "주택", parts[2:]
    return "전역", parts


_QUESTIONS, _FORM_RULES = {}, {}


def load_questions(path=None):
    """질문지/문항.json. 경로마다 한 번만 읽는다."""
    path = path or QUESTIONS_PATH
    if path not in _QUESTIONS:
        with open(path, encoding="utf-8") as fh:
            _QUESTIONS[path] = json.load(fh)
    return _QUESTIONS[path]


def form_problem(q, value):
    """문항 q 의 답형식에 이 값이 맞는지 본다. 맞으면 None, 틀리면 받는 형식을 설명한 글.

    예아니오는 bool, 선택은 선택지 코드 하나(글자), 복수선택은 선택지 코드의 목록, 목록은 list 다.
    그 밖의 답형식(날짜, 금액, 주소 등)은 여기서 보지 않는다. 날짜는 dates.to_date, 금액은 _money 가 본다.
    값이 없는 것(None)은 아직 답하지 않은 것이라 호출하는 쪽이 따로 다룬다.
    질문지 answer() 가 답을 받을 때와 prepare() 가 사실관계를 읽을 때 같은 함수를 쓴다.
    """
    kind = q["답형식"]
    codes = [o["코드"] for o in q.get("선택지") or []]
    if kind == "예아니오":
        return None if isinstance(value, bool) else "true 또는 false"
    if kind == "선택" and codes:
        keys = q.get("키") or []
        v = value.get("구분") if isinstance(value, dict) and keys and keys[0] in CHOICE_DICT_KEYS else value
        return None if isinstance(v, str) and v in codes else "다음 중 하나를 글자로: %s" % ", ".join(codes)
    if kind == "복수선택" and codes:
        ok = isinstance(value, list) and all(isinstance(v, str) and v in codes for v in value)
        return None if ok else "다음 중 고른 것을 목록으로(하나만 골라도 목록, 없으면 []): %s" % ", ".join(codes)
    if kind == "목록":
        return None if isinstance(value, list) else "목록"
    return None


def form_rules(path=None):
    """prepare 가 자료형을 검사하는 키 표. [(문항, 단위, 경로)] 이고 문항.json 의 답형식에서 만든다.

    엔진이 읽지 않는 키(COLLECT_ONLY), 신규 주택 키([신규]), 서식 전용 문항은 뺀다.
    자산 안의 목록(거주기간, 필요경비)은 모양별 검사(_check_residence, _check_money)가 따로 있어 뺀다.
    """
    path = path or QUESTIONS_PATH
    if path not in _FORM_RULES:
        rules = []
        for q in load_questions(path)["문항"]:
            if q["답형식"] not in FORM_KINDS or q["범위"] == "서식단계":
                continue
            for key in q["키"]:
                where, parts = split_key(key)
                if key in COLLECT_ONLY or "[신규]" in key or (where == "자산" and q["답형식"] == "목록"):
                    continue
                rules.append((q, where, ".".join(parts)))
        _FORM_RULES[path] = rules
    return _FORM_RULES[path]


def with_ro(word):
    """「교환」 은 「교환으로」, 「기타」 는 「기타로」. 받침이 없거나 ㄹ 받침이면 로, 그 밖에는 으로."""
    code = ord(word[-1]) - 0xAC00 if word else -1
    if 0 <= code < 11172:
        return word + ("로" if code % 28 in (0, 8) else "으로")
    return word + "로"


def _cause(원인):
    return "기타 원인으로" if 원인 == "기타" else with_ro(원인)


def _land_ratio(zone, capital):
    """부수토지 비과세 배율(시행령 제154조⑦). 도시지역 안 수도권의 주거·상업·공업지역 3배, 수도권 녹지지역 5배,
    수도권 밖 도시지역 5배, 그 밖의 용도지역(관리·농림·자연환경보전) 10배. 용도지역 이름으로 정하지 못하면 None."""
    if "녹지" in zone:
        return 5
    if any(w in zone for w in ("주거", "상업", "공업")):
        return 3 if capital else 5
    if any(w in zone for w in ("관리", "농림", "자연환경")):
        return 10
    return None


def land_problem(value):
    """L01 부수토지 답의 모양. 맞으면 None, 틀리면 안내. 질문지 answer() 와 prepare() 가 같이 쓴다."""
    if not isinstance(value, dict) or set(value) - set(LAND_NAMES):
        return LAND_MSG
    for name in LAND_NAMES[:2]:
        v = value.get(name)
        if isinstance(v, bool) or not isinstance(v, (int, float)) or v <= 0:
            return "%s 은 0 보다 큰 숫자로 적습니다" % name
    zone = value.get("용도지역")
    if not isinstance(zone, str) or _land_ratio(zone, True) is None:
        return "용도지역은 제1종일반주거지역, 자연녹지지역, 계획관리지역처럼 토지이용계획확인서의 이름으로 적습니다"
    return None


def _whole(v):
    if isinstance(v, bool):
        raise FactsError("지분 분자·분모는 정수여야 합니다")
    if isinstance(v, int):
        return v
    if isinstance(v, float) and v.is_integer():
        return int(v)
    if isinstance(v, str) and re.fullmatch(r"[0-9]+", v):
        return int(v)
    raise FactsError("지분 분자·분모는 정수여야 합니다")


def share(a):
    j = (a or {}).get("지분") or "단독"
    if j == "단독":
        return Fraction(1)
    if not isinstance(j, dict):
        raise FactsError(SHARE_MSG)
    if "구분" not in j:
        if "분자" in j or "분모" in j:
            raise FactsError(SHARE_MSG)
        return Fraction(1)
    if j["구분"] == "단독":
        return Fraction(1)
    if j["구분"] != "공동":
        raise FactsError(SHARE_MSG)
    n, d = _whole(j.get("분자")), _whole(j.get("분모"))
    if not 0 < n <= d:
        raise FactsError("지분 분자·분모는 0 < 분자 <= 분모 인 정수여야 합니다")
    return Fraction(n, d)


def _money(v, 문항, 자산id):
    """금액 한 칸을 검사한다. None 은 아직 없는 값이라 넘기고(없으면 need 가 묻는다), 정수만 받는다.
    목록 안의 칸은 묻는 need 가 없으므로 _listed_money 를 쓴다.
    소수가 없는 실수는 정수로 본다. 글자와 bool 은 받지 않는다(엔진이 int() 와 크기 비교를 섞어 쓴다)."""
    if v is None:
        return
    if isinstance(v, bool) or not isinstance(v, (int, float)) or (isinstance(v, float) and not v.is_integer()):
        raise Missing(문항, 자산id, WHOLE_MSG)
    if v < 0:
        raise Missing(문항, 자산id, NONNEG_MSG)


def _listed_money(v, 문항, 자산id):
    """목록 안의 금액 칸(감정가액 원소, 지출 항목의 금액). 이 칸은 따로 묻는 need 가 없어 비어 있어도 여기서 묻는다."""
    if v is None:
        raise Missing(문항, 자산id, EMPTY_MSG)
    _money(v, 문항, 자산id)


def _check_money(a):
    """엔진이 읽는 금액 칸 전부. 첫 번째로 걸린 칸 하나만 Missing 으로 올린다."""
    aid = a.get("id")
    _money((a.get("양도") or {}).get("매수인부담세액"), "A14", aid)
    _money(a.get("전체양도가액"), "M01", aid)
    _money(a.get("시가참고"), "M03", aid)
    _money(a.get("전체취득가액"), "M06", aid)
    ex = a.get("필요경비")
    if ex is not None and not isinstance(ex, dict):
        raise Missing("M07", aid, "필요경비는 취득세와 취득부대·자본적지출·기타·양도비 목록으로 나눠 적습니다")
    ex = ex or {}
    _money(ex.get("취득세"), "M07", aid)
    for group, 문항 in EXPENSE_GROUPS:
        items = ex.get(group)
        if items is None:
            continue
        if not isinstance(items, list):
            raise Missing(문항, aid, "%s 는 지출마다 내용·지급일·금액·증빙종류·상대방을 적은 목록입니다" % group)
        for it in items:
            if not isinstance(it, dict):
                raise Missing(문항, aid, "%s 는 지출마다 내용·지급일·금액·증빙종류·상대방을 적은 목록입니다" % group)
            _listed_money(it.get("금액"), 문항, aid)
    _money(a.get("감가상각비"), "M12", aid)
    _money(a.get("매매사례가액"), "M21", aid)
    appraisals = a.get("감정가액")
    if appraisals is not None:
        if not isinstance(appraisals, list):
            raise Missing("M21", aid, "감정가액은 감정평가마다 금액 하나씩 적은 목록입니다")
        for x in appraisals:
            _listed_money(x, "M21", aid)
    bs = a.get("기준시가")
    if bs is not None:
        if not isinstance(bs, dict):
            raise Missing("M22", aid, SHAPE_PRICE_MSG)
        for side in ("취득", "양도"):
            part = bs.get(side)
            if part is None:
                continue
            if not isinstance(part, dict):
                raise Missing("M22", aid, SHAPE_PRICE_MSG)
            for v in part.values():
                _money(v, "M22", aid)


def _check_residence(a):
    """거주기간은 [전입일, 전출일] 구간의 목록이다. 끝이 비어 있는 구간은 엔진이 셀 수 없어 받지 않는다."""
    aid = a.get("id")
    periods = a.get("거주기간")
    if periods is None:
        return
    if not isinstance(periods, (list, tuple)):
        raise Missing("H07", aid, RESIDENCE_MSG)
    for p in periods:
        if not isinstance(p, (list, tuple)) or len(p) != 2:
            raise Missing("H07", aid, RESIDENCE_MSG)
        try:
            start, end = dates.to_date(p[0]), dates.to_date(p[1])
        except ValueError:
            raise Missing("H07", aid, "거주기간 날짜 형식이 YYYY-MM-DD 가 아닙니다")
        if start is None or end is None:
            raise Missing("H07", aid, RESIDENCE_MSG)
        if end < start:
            raise Missing("H07", aid, "전출일이 전입일보다 앞섭니다")


def _check_asset_ids(f):
    seen = set()
    for a in f.get("자산") or []:
        aid = a.get("id") if isinstance(a, dict) else None
        if aid is None or (isinstance(aid, str) and not aid.strip()) or isinstance(aid, (list, dict)):
            raise FactsError("자산마다 비어 있지 않은 id 가 필요합니다")
        if not isinstance(aid, str) or aid != aid.strip():
            raise FactsError("자산 id 는 앞뒤 공백이 없는 글자여야 합니다. 세대 주택목록의 자산id 와 글자로 맞춥니다")
        if aid in seen:
            raise FactsError("자산 id 가 겹칩니다: %s" % aid)
        seen.add(aid)


def _check_house_prices(f, out):
    houses = get(f, "세대.주택목록")
    for h in houses if isinstance(houses, list) else []:
        if not isinstance(h, dict):
            continue
        try:
            _money(h.get("양도당시기준시가"), "X01", h.get("id"))
        except Missing as m:
            out["질문"].append(m.to_dict())


def _form_missing(q, 자산, path, value):
    hint = None if value is None else form_problem(q, value)
    return Missing(q["id"], 자산, FORM_MSG % (path, hint)) if hint else None


def _check_global_forms(f):
    """신고인·연간·세대 키의 자료형. 어긋난 문항마다 Missing 을 낸다. 세대 키는 주택을 파는 사실관계에서만 엔진이 읽는다."""
    house_sale = any(isinstance(a, dict) and a.get("종류") == "주택" for a in f.get("자산") or [])
    bad = []
    for q, where, path in form_rules():
        if where != "전역" or (path.startswith("세대.") and not house_sale):
            continue
        m = _form_missing(q, None, path, get(f, path))
        if m:
            bad.append(m)
    houses = get(f, "세대.주택목록")
    if house_sale and isinstance(houses, list) and not all(isinstance(h, dict) for h in houses):
        bad.append(Missing("H04", None, "주택 목록은 집마다 id, 소재지, 취득일을 가진 dict 의 목록으로 적습니다"))
    return bad


def _check_house_forms(f, out):
    """주택 목록의 집마다 선택 키(제12호해당)의 자료형."""
    houses = get(f, "세대.주택목록")
    for h in houses if isinstance(houses, list) else []:
        if not isinstance(h, dict):
            continue
        for q, where, path in form_rules():
            if where == "주택":
                m = _form_missing(q, h.get("id"), path, get(h, path))
                if m:
                    out["질문"].append(m.to_dict())


def _check_asset_forms(a, aid):
    """자산 한 건의 예아니오·선택·복수선택 키 자료형. 첫 번째로 어긋난 문항을 Missing 으로 올린다."""
    for q, where, path in form_rules():
        if where == "자산":
            m = _form_missing(q, aid, path, get(a, path))
            if m:
                raise m


def _route_house(a, aid):
    """엔진이 계산하지 않는 주택 사실. 답이 있으면 계산하지 않고 다루지않음(계획 5)으로 돌린다."""
    if a.get("다가구일괄양도") not in (None, "일괄"):
        raise OutOfScope(aid, "다가구주택을 호실별로 나눠 양도(시행령 제155조⑮, 호실마다 한 채로 본다)", "5")
    if get(a, "양도.용도변경특약") is True:
        raise OutOfScope(aid, "매매계약 뒤 주택 외 용도로 바꿔 양도(시행령 제154조① 괄호, 1주택 판정일이 매매계약일)", "5")
    if a.get("비거주자전환") is True:
        raise OutOfScope(aid, "비거주자일 때부터 보유한 주택을 거주자로 전환한 뒤 양도(보유·거주기간 통산, 시행령 제154조⑧2호)", "5")
    if a.get("재건축통산") is True:
        raise OutOfScope(aid, "멸실 뒤 재건축한 주택(보유·거주기간 통산, 시행령 제154조⑧1호)", "5")
    land = a.get("부수토지")
    if land is not None:
        problem = land_problem(land)
        if problem:
            raise Missing("L01", aid, problem)
        sido = get(a, "소재지.시도")
        ratio = _land_ratio(land["용도지역"], SIDO_SHORT.get(sido, sido) in CAPITAL)
        if land["대지면적"] > land["정착면적"] * ratio:
            raise OutOfScope(aid, "주택부수토지가 건물 정착면적의 %d배를 넘는다(%s, 시행령 제154조⑦). 넘는 땅은 비사업용 토지로 본다"
                             % (ratio, land["용도지역"]), "5")


def _route_price(a, aid, out):
    """양도가액에 영향을 주는 사실. 금액 형식 검사 뒤에 부른다."""
    if (get(a, "양도.매수인부담세액") or 0) > 0:
        raise OutOfScope(aid, "매수인이 부담한 양도소득세가 있는 양도", "5")
    if a.get("매수인관계") not in (None, "타인"):
        시가, 가액 = a.get("시가참고"), a.get("전체양도가액")
        if 시가 is not None and 가액 is not None and 가액 < 시가:
            raise OutOfScope(aid, "특수관계인에게 시가보다 낮게 양도(부당행위계산 부인 검토 대상)", "5")
        out["확인사항"].append("%s: 특수관계인 거래는 시가와 비교해 부당행위계산 부인 대상인지 확인한다(소득세법 제101조)" % aid)


def _route_same_day(f, out):
    """같은 날 주택을 여러 채 양도하면 거주자가 고른 순서대로 양도한 것으로 본다(시행령 제154조⑨). 순서를 반영하지 않으므로 계산하지 않는다.

    사실관계에 같은 날 양도한 주택 자산이 둘 이상이거나, 같은날양도순서(P07, 예아니오)가 참이면 그 날의 주택 자산을 돌려보낸다.
    P07 은 다른 양도를 따로 돌린 사실관계에서도 같은 날 양도를 알려 준다. 참이 아닌 값은 같은 날 양도가 없다는 뜻이다.
    예아니오가 아닌 값(글자 「아니요」 등)은 prepare 의 자료형 검사(form_rules)가 P07 을 되묻는다.
    자산으로 넣지 않고 세대 주택목록에만 적은 집도 양도일(`양도일`)이 있으면 같은 날 양도한 집으로 센다(houses_at 이 그 날짜로 보유 여부를 정한다).
    """
    선언 = get(f, "연간.같은날양도순서") is True
    이미 = {x["자산"] for x in out["다루지않음"]}
    by_day = {}
    for a in f.get("자산") or []:
        aid = a.get("id")
        t = out["시기"].get(aid)
        if t and a.get("종류") == "주택" and aid not in 이미:
            by_day.setdefault(t["양도일"], []).append(aid)
    listed = _listed_sale_days(f, out)
    for day, ids in by_day.items():
        if len(ids) >= 2 or 선언 or day in listed:
            for aid in ids:
                out["다루지않음"].append(OutOfScope(aid, "같은 날 주택 여러 채 양도(시행령 제154조⑨ 선택 순서)", "5").to_dict())


def _listed_sale_days(f, out):
    """판 날(양도일)이 적힌 주택목록 집의 양도일 모음. 시기를 정한 자산과 이어진 집(자산id)은 그 자산이 이미 세므로 뺀다.
    날짜 형식이 틀린 집은 여기서 건너뛴다. houses_at 이 H04 로 되묻는다."""
    houses = get(f, "세대.주택목록")
    days = set()
    for h in houses if isinstance(houses, list) else []:
        if not isinstance(h, dict) or h.get("자산id") in out["시기"]:
            continue
        try:
            day = dates.to_date(h.get("양도일"))
        except ValueError:
            continue
        if day is not None:
            days.add(day.isoformat())
    return days


def _prepare_asset(f, a, out, bad):
    aid = a.get("id")
    종류 = need(a, "종류", "P02", aid)
    if 종류 in ("겸용주택", "입주권", "분양권"):
        raise OutOfScope(aid, "%s 양도" % 종류, "5")
    if 종류 == "기타자산":
        raise OutOfScope(aid, "주식·회원권 등 그 밖의 자산", "없음")
    if 종류 not in ("주택", "토지", "건물"):
        raise Missing("P02", aid, "종류 코드 %s 를 알 수 없습니다" % 종류)
    원인 = need(a, "양도.원인", "P03", aid)
    if 원인 == "부담부증여":
        raise OutOfScope(aid, "부담부증여", "5")
    if 원인 in ("교환", "기타"):  # 교환은 받은 자산의 시가가 양도가액이라 이 계획이 다루지 않는다
        raise OutOfScope(aid, "%s 양도한 자산" % _cause(원인), "5")
    if 원인 == "수용":  # 수용의 양도시기는 대금 청산일, 수용 개시일, 소유권이전등기접수일 중 빠른 날이다(시행령 제162조①7호)
        raise OutOfScope(aid, "수용으로 양도한 자산(양도시기 시행령 제162조①7호, 조특법 감면)", "5")
    if 원인 not in ("매매", "경매"):
        raise Missing("P03", aid, "양도 원인 코드 %s 를 알 수 없습니다" % 원인)
    취득원인 = need(a, "취득.원인", "A15", aid)
    if 취득원인 in ("상속", "증여", "부담부증여", "조합원"):
        raise OutOfScope(aid, "%s 취득한 자산" % _cause(취득원인), "5")
    if 취득원인 == "기타":  # 점유취득(시행령 제162조①6호), 환지(9호)는 취득시기가 매매와 다르다
        raise OutOfScope(aid, "기타 원인으로 취득한 자산(점유취득·환지 등 취득시기 규칙이 다름)", "5")
    if 취득원인 not in ("매매", "분양", "신축", "경매", "공공매입"):
        raise Missing("A15", aid, "취득 원인 코드 %s 를 알 수 없습니다" % 취득원인)
    try:
        양도, 양도근거 = dates.transfer_date(a.get("양도"))
    except ValueError:
        raise Missing("A11", aid, "양도 날짜 형식이 YYYY-MM-DD 가 아닙니다")
    if 양도 is None:
        raise Missing("A11", aid, "잔금일이나 등기접수일이 필요합니다")
    if 양도 < dates.to_date(첫양도일):
        raise OutOfScope(aid, "%s 전 양도" % 첫양도일, "없음")
    try:
        취득, 취득근거 = dates.acquisition_date(a.get("취득"))
    except ValueError:
        raise Missing("A18" if 취득원인 == "신축" else "A17", aid, "취득 날짜 형식이 YYYY-MM-DD 가 아닙니다")
    if 취득 is None:
        if 취득원인 == "신축":
            raise Missing("A18", aid, "사용승인일이나 사실상 사용일이 필요합니다")
        raise Missing("A17", aid, "취득 잔금일이나 등기접수일이 필요합니다")
    if 취득 < 의제취득기준:
        raise OutOfScope(aid, "1985-01-01 전 취득(의제취득일 적용)", "5")
    if 취득 > 양도:
        raise Missing("A18" if 취득원인 == "신축" else "A17", aid, "취득일이 양도일보다 늦습니다")
    # 시기를 먼저 적는다. 질문지가 세대·거주 문항을 금액 문항보다 먼저 물을 수 있도록 엔진값이 시기만으로 돌아간다
    out["시기"][aid] = {"취득일": 취득.isoformat(), "취득근거": 취득근거, "양도일": 양도.isoformat(), "양도근거": 양도근거}
    need(a, "소재지", "A01", aid)
    _check_asset_forms(a, aid)
    # 지구 안인지 모르면(A02 모름) 조정대상지역 해당을 정하지 못한다. 판정이 A02 를 다시 묻게 두면 질문지는 이미 답한 문항이라
    # 내지 않아 대화가 끝나지 않는다. 등기하지 않은 미이행 주택은 판정이 조정대상지역을 보지 않는다
    미등기_미이행 = a.get("등기") is False and a.get("미등기사유") == "미이행"
    if 종류 == "주택" and not 미등기_미이행 and (a.get("지구해당") == "모름" or "A02:%s" % aid in (f.get("모름") or [])):
        raise OutOfScope(aid, "지구 안인지 확인되지 않음(A02 모름). 조정대상지역 해당을 정하지 못해 계산하지 않았다. "
                         "토지이용계획확인서 등으로 확인해 A02 를 예 또는 아니오로 답하면 계산한다", "없음")
    if 종류 == "주택":
        if "H05" not in bad and [x for x in get(f, "세대.특례주택") or [] if x != "없음"]:
            raise OutOfScope(aid, "상속·임대·혼인·동거봉양·농어촌 주택 특례가 걸린 세대", "5")
        if "H06" not in bad and get(f, "세대.입주권분양권"):
            raise OutOfScope(aid, "세대가 조합원입주권·분양권을 가진 경우", "5")
        _route_house(a, aid)
    if 종류 == "토지":
        용도 = need(a, "토지사용현황", "A21", aid)
        if 용도 not in OK_LAND_USE:
            raise OutOfScope(aid, "비사업용 토지 판정이 필요한 토지(%s)" % 용도, "5")
    if need(a, "계약금액일치", "M04", aid) is False:
        raise OutOfScope(aid, "실제 거래가액과 계약서 금액이 다르다", "없음")
    if 종류 == "주택":
        _check_residence(a)
    _check_money(a)
    _route_price(a, aid, out)


def prepare(f):
    _check_asset_ids(f)
    out = {"시기": {}, "질문": [], "다루지않음": [], "확인사항": []}
    shared = _check_global_forms(f)
    out["질문"] += [m.to_dict() for m in shared]
    bad = {m.문항 for m in shared}
    if "P01" not in bad and get(f, "신고인.거주자") is False:
        out["다루지않음"].append(OutOfScope(None, "비거주자 양도", "없음").to_dict())
    for a in f.get("자산") or []:
        try:
            _prepare_asset(f, a, out, bad)
        except Missing as m:
            out["질문"].append(m.to_dict())
        except OutOfScope as o:
            out["다루지않음"].append(o.to_dict())
    _check_house_prices(f, out)
    _check_house_forms(f, out)
    _route_same_day(f, out)
    if "P05" not in bad and get(f, "연간.다른양도"):
        out["확인사항"].append("같은 해 다른 양도는 이 계산에 들어가지 않았다. 기본공제와 합산 비교(소득세법 제104조⑤)를 다시 확인하라")
    return out


def houses_at(f, on, prep):
    on = dates.to_date(on)
    out = []
    for h in get(f, "세대.주택목록") or []:
        aid = h.get("자산id")
        t = (prep.get("시기") or {}).get(aid) if aid else None
        try:
            acq = dates.to_date(t["취득일"]) if t else dates.to_date(h.get("취득일"))
            sold = dates.to_date(t["양도일"]) if t else dates.to_date(h.get("양도일"))
        except ValueError:
            raise Missing("H04", aid, "주택 목록 %s 의 날짜 형식이 YYYY-MM-DD 가 아닙니다" % h.get("id"))
        if acq is None:
            raise Missing("H04", aid, "주택 목록 %s 의 취득일이 필요합니다" % h.get("id"))
        if acq > on:
            continue
        if sold is not None and sold < on:
            continue
        out.append(h)
    return out
