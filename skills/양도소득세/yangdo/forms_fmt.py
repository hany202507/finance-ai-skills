# -*- coding: utf-8 -*-
"""신고값을 서식 칸에 적는 글자로 바꾼다. forms.py 의 매핑 「형식」 이름마다 함수 하나(`_Fmt.f_<형식>`)가 있다.

돌려주는 값은 글자, {부분: 글자}(기준점이 여럿인 칸), 후보 목록(앞에서부터 칸에 들어가는 것을 쓴다), 또는 빈 글자다.
후보 목록의 마지막이 빈 글자면 앞 후보가 칸에 들어가지 않을 때 그 칸을 비운다는 뜻이다(코드표에 한글 이름이 없는 국가).
값을 다시 계산하지 않는다. 좁은 칸에 쓸 주소·소재지의 줄임 후보(`_shorter`)도 여기서 만든다.
코드표나 매핑에 없는 값, 꼴이 다른 값은 ValueError 로 멈춘다. 문장에는 필드 이름만 적고 값을 옮기지 않는다
(인적사항이 로그에 남지 않게).
"""
import re
from decimal import ROUND_DOWN, Decimal

# 칸이 좁아 소재지·주소를 줄여 쓸 때의 시도 약칭(행정구역 이름의 관용 약칭)
SIDO_SHORT = {
    "서울특별시": "서울", "부산광역시": "부산", "대구광역시": "대구", "인천광역시": "인천", "광주광역시": "광주",
    "대전광역시": "대전", "울산광역시": "울산", "세종특별자치시": "세종", "경기도": "경기", "강원도": "강원",
    "강원특별자치도": "강원", "충청북도": "충북", "충청남도": "충남", "전라북도": "전북", "전북특별자치도": "전북",
    "전라남도": "전남", "경상북도": "경북", "경상남도": "경남", "제주특별자치도": "제주",
    "전남광주통합특별시": "광주특별시",      # 통합 근거 법률이 정한 약칭(regions.SIDO_SHORT 의 반대 방향)
}
_LOT = re.compile(r"^\d+(-\d+)?$")
_UNIT = re.compile(r"^[0-9A-Za-z-]+(동|호)$")


def _digits(v):
    return re.sub(r"\D", "", str(v or ""))


def _ymd(v):
    s = _digits(v)
    if not s:
        return None
    if len(s) != 8:
        raise ValueError("날짜가 8자리가 아니다")
    return s


def _shorter(full):
    """소재지·주소 글자를 칸에 맞게 줄인 후보(긴 것부터). 시도 약칭 → 아파트 이름 빼기 → 시도 빼기 → 번지까지."""
    tokens = full.split()
    if not tokens:
        return []
    out = [full]
    k = next((j for j, t in enumerate(tokens) if j > 0 and _LOT.match(t)), None)
    head = SIDO_SHORT.get(tokens[0])
    tail = [t for t in tokens[k + 1:] if _UNIT.match(t)] if k is not None else []
    if head:
        out.append(" ".join([head] + tokens[1:]))
        if k is not None:
            out.append(" ".join([head] + tokens[1:k + 1] + tail))
    out.append(" ".join(tokens[1:]))
    if k is not None:
        out.append(" ".join(tokens[1:k + 1] + tail))
        if head:
            out.append(" ".join([head] + tokens[1:k + 1]))
        out.append(" ".join(tokens[1:k + 1]))
        if k > 2:
            out.append(" ".join(tokens[2:k + 1]))
    seen, uniq = set(), []
    for s in out:
        if s and s not in seen:
            seen.add(s)
            uniq.append(s)
    return uniq


def _address(a, mountain=None):
    """신고인 주소(C7 dict) → 「서울특별시 마포구 공덕동 1 합성아파트 101동 1001호」.
    mountain 은 지번 앞에 「산」을 붙이는 특수지 코드다(코드표 특수지에서 이름이 「산」인 코드)."""
    if not isinstance(a, dict):
        return str(a or "")
    parts = [a.get(k) for k in ("시도", "시군구", "읍면동") if a.get(k)]
    no = a.get("번지")
    if no and no != "0":
        no = ("산 " if mountain and a.get("특수지") == mountain else "") + no
        if a.get("호") and a["호"] != "0":
            no += "-" + a["호"]
        parts.append(no)
    for k, unit in (("아파트명", ""), ("아파트동", "동"), ("아파트호", "호")):
        v = a.get(k)
        if v:
            parts.append(v if (not unit or v.endswith(unit)) else v + unit)
    return " ".join(parts)


# 영문 이름 후보 확인사항의 끝 문장. forms.render 는 칸을 실제로 비웠으면 이 문장으로 끝나는 확인사항을 비웠다는 문장으로 바꾼다
ENGLISH_NOTE_TAIL = "칸에 들어가지 않으면 비워 둔다"


class _Fmt:
    """형식 이름 → 값 바꾸기. 돌려주는 값은 글자, {부분: 글자}, 후보 목록(앞에서부터 칸에 맞는 것을 쓴다), 또는 빈 글자."""

    def __init__(self, rv, mapping, codes, note=None):
        """note 는 확인사항 한 줄을 받는 함수다(없으면 버린다). 값을 싣지 않는 문장만 넘긴다."""
        self.rv, self.m, self.codes = rv, mapping, codes
        self.note = note or (lambda text: None)
        self.mountain = next((v.get("코드") for v in (codes.get("특수지") or {}).values() if v.get("이름") == "산"), None)

    def __call__(self, kind, value, e):
        f = getattr(self, "f_" + kind, None)
        if f is None:
            raise ValueError("매핑 형식 %r 을 모른다" % kind)
        return f(value, e)

    @staticmethod
    def f_금액(v, e):
        if v is None or v == "":
            return ""
        v = int(v)
        if v == 0 and not e.get("0적음"):
            return ""
        return format(v, ",")

    @staticmethod
    def f_글(v, e):
        return "" if v is None else str(v).strip()

    f_코드 = f_글
    f_세율 = f_글

    @staticmethod
    def f_날짜(v, e):
        s = _ymd(v)
        return "%s.%s.%s" % (s[:4], s[4:6], s[6:]) if s else ""

    @staticmethod
    def f_연월일(v, e):
        s = _ymd(v)
        return {"년": s[:4], "월": str(int(s[4:6])), "일": str(int(s[6:]))} if s else ""

    @staticmethod
    def f_면적(v, e):
        if v in (None, ""):
            return ""
        d = Decimal(str(v))
        if d == 0:
            return ""
        # 소수 둘째 자리까지 적고, 셋째 자리에 값이 있으면 셋째 자리까지 적는다. 신고값의 면적은 이미 셋째 자리까지라
        # (return_values._area, 전자신고 면적 칸) 그대로 옮겨진다. 그 아래 자리가 있는 값을 받으면 신고값과 같이 버린다
        q = d.quantize(Decimal("0.01"), rounding=ROUND_DOWN)
        if q != d:
            q = d.quantize(Decimal("0.001"), rounding=ROUND_DOWN)
        return format(q, ",f")

    @staticmethod
    def f_기간(v, e):
        s = str(v or "").strip()
        if not s:
            return ""
        m = re.fullmatch(r"(?:(\d+)년 이상)?\s*(?:(\d+)년 미만)?", s)
        if not m or not (m.group(1) or m.group(2)):       # 빈칸으로 두면 기간이 말없이 빠진다. 값은 싣지 않는다
            raise ValueError("%s: 기간 글자가 「n년 이상 m년 미만」 꼴이 아니다" % (e.get("필드") or "?"))
        return {"이상": m.group(1) or "", "미만": m.group(2) or ""}

    @staticmethod
    def f_세율구분(v, e):
        s = str(v or "")
        if not s:
            return ""
        d, _, r = s.partition("-")
        return {"국내외분": d, "세율구분": r}

    def f_자산종류(self, v, e):
        if not v:
            return ""
        names = self.m["자산종류"].get(str(v))
        if names is None:
            raise ValueError("부표1 자산종류 코드 %s 의 이름이 매핑 「자산종류」 표에 없다" % v)
        if not isinstance(names, list):
            return {"자산종류": names, "코드": str(v)}
        return [{"자산종류": n, "코드": str(v)} for n in names]

    @staticmethod
    def f_주민등록번호(v, e):
        s = _digits(v)
        if len(s) == 13:
            return s[:6] + "-" + s[6:]
        if len(s) == 10:
            return "%s-%s-%s" % (s[:3], s[3:5], s[5:])
        return "" if v is None else str(v)

    @staticmethod
    def f_사업자번호(v, e):
        s = _digits(v)
        if len(s) == 10:
            return "%s-%s-%s" % (s[:3], s[3:5], s[5:])
        return "" if v is None else str(v)

    @staticmethod
    def f_전화(v, e):
        s = _digits(v)
        if len(s) < 8:
            return s
        if not s.startswith("0"):
            return "%s-%s" % (s[:-4], s[-4:])
        area = 2 if s.startswith("02") else 3
        a, rest = s[:area], s[area:]
        return "%s-%s-%s" % (a, rest[:-4], rest[-4:])

    def f_주소(self, v, e):
        return _shorter(_address(v, self.mountain)) if v else ""

    @staticmethod
    def f_납세지(v, e):
        """지방소득세 납세지: 시ㆍ군ㆍ구 단위까지(별지40의11 작성방법 2). 자치구가 아닌 구는 시까지."""
        if not isinstance(v, dict):
            return ""
        sido, sgg = v.get("시도") or "", (v.get("시군구") or "").split()
        place = sgg[0] if sgg else ""
        full = " ".join(x for x in (sido, place) if x)
        cands = [full]
        if SIDO_SHORT.get(sido) and place:
            cands.append(SIDO_SHORT[sido] + " " + place)
        if place:
            cands.append(place)
        return cands if full else ""

    @staticmethod
    def f_소재지(v, e):
        return _shorter(str(v)) if v else ""

    def f_자산소재지(self, v, e):
        row = next((a for a in self.rv.get("부표1") or [] if a.get("자산") == v), None)
        return _shorter(row["소재지"]) if row and row.get("소재지") else ""

    def f_양수인성명(self, v, e):
        if not v:
            return ""
        n = len(self.rv.get("양수인") or [])
        return "%s 외 %d명" % (v, n - 1) if n > 1 else str(v)

    @staticmethod
    def f_지분(v, e):
        num, den = v
        return "%s/%s" % (num, den) if num and den else ""

    def _name(self, table, code, kind, e):
        """코드표에서 코드의 이름. 표에 없는 코드는 멈춘다(빈칸으로 두면 값이 말없이 빠진다). 문장에는 코드 값을 싣지 않는다.

        표에 있는데 한글 이름이 빈 코드는 멈추지 않는다. 규격서 원문이 한글 명칭을 비운 코드(국가 CD)라 신고인이 고칠 수 있는
        입력이 아니다. 영문 이름이 있으면 [영문, ""] 후보를 돌려주어 칸에 들어가면 영문으로 적고 들어가지 않으면 비운다.
        영문 이름도 없으면 비운다. 어느 쪽이든 확인사항으로 알린다."""
        hit = self.codes[table].get(code)
        where = e.get("필드") or "?"
        if hit is None:
            raise ValueError("%s: %s 코드가 코드표 「%s」에 없다" % (where, kind, table))
        if hit.get("이름"):
            return hit["이름"]
        if hit.get("영문"):
            self.note("%s 칸: 코드표 「%s」에 이 %s 코드의 한글 이름이 없어 영문 이름을 적는다. %s"
                      % (where, table, kind, ENGLISH_NOTE_TAIL))
            return [hit["영문"], ""]
        self.note("%s 칸: 이 %s 코드의 이름이 코드표 「%s」에 없어 비워 두었다. 서면으로 낼 때 직접 적는다" % (where, kind, table))
        return ""

    def f_관계(self, v, e):
        label, code = v
        if label:
            return str(label)
        return self._name("양수인관계목록", code, "양수인 관계", e) if code else ""

    def f_국가명(self, v, e):
        return self._name("국가", v, "국가", e) if v else ""

    def f_은행(self, v, e):
        return self._name("은행", v, "은행", e) if v else ""

    @staticmethod
    def f_감면율(v, e):
        return "%s%%" % v if v not in (None, "", 0) else ""

    @staticmethod
    def f_고유번호(v, e):
        s = _digits(v)
        if not s:
            return ""
        if len(s) != 14:
            raise ValueError("부동산고유번호가 14자리가 아니다")
        return {"앞4자리": s[:4], "가운데4자리": s[4:8], "뒤6자리": s[8:]}
