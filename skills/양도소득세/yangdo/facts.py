# -*- coding: utf-8 -*-
"""사실관계 JSON 검사. 원자료 날짜로 취득·양도 시기를 정하고, 범위와 빠진 사실을 모은다."""
import re
from datetime import date
from fractions import Fraction

from yangdo import dates, 첫양도일

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


def _prepare_asset(f, a, out):
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
        raise OutOfScope(aid, "%s 으로 양도한 자산" % 원인, "5")
    if 원인 not in ("매매", "수용", "경매"):
        raise Missing("P03", aid, "양도 원인 코드 %s 를 알 수 없습니다" % 원인)
    취득원인 = need(a, "취득.원인", "A15", aid)
    if 취득원인 in ("상속", "증여", "부담부증여", "조합원"):
        raise OutOfScope(aid, "%s 으로 취득한 자산" % 취득원인, "5")
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
    if 종류 == "주택":
        if [x for x in get(f, "세대.특례주택") or [] if x != "없음"]:
            raise OutOfScope(aid, "상속·임대·혼인·동거봉양·농어촌 주택 특례가 걸린 세대", "5")
        if get(f, "세대.입주권분양권"):
            raise OutOfScope(aid, "세대가 조합원입주권·분양권을 가진 경우", "5")
    if 종류 == "토지" and a.get("등기") is not False:
        용도 = need(a, "토지사용현황", "A21", aid)
        if 용도 not in OK_LAND_USE:
            raise OutOfScope(aid, "비사업용 토지 판정이 필요한 토지(%s)" % 용도, "5")
    if need(a, "계약금액일치", "M04", aid) is False:
        raise OutOfScope(aid, "실제 거래가액과 계약서 금액이 다르다", "없음")
    if 종류 == "주택":
        _check_residence(a)
    _check_money(a)
    if 원인 == "수용":
        out["확인사항"].append("%s: 수용 양도의 조세특례제한법 감면은 계산하지 않았다" % aid)


def prepare(f):
    _check_asset_ids(f)
    out = {"시기": {}, "질문": [], "다루지않음": [], "확인사항": []}
    if get(f, "신고인.거주자") is False:
        out["다루지않음"].append(OutOfScope(None, "비거주자 양도", "없음").to_dict())
    for a in f.get("자산") or []:
        try:
            _prepare_asset(f, a, out)
        except Missing as m:
            out["질문"].append(m.to_dict())
        except OutOfScope as o:
            out["다루지않음"].append(o.to_dict())
    _check_house_prices(f, out)
    if get(f, "연간.다른양도"):
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
