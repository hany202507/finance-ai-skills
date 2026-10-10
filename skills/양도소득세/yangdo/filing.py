# -*- coding: utf-8 -*-
"""신고인 정보. 신고인.json(계약 C7)의 형식을 검사하고, 빠진 것을 서식 단계 문항 F01~F06 으로 돌려준다.

load      형식만 본다. 값이 비어 있으면 통과시키고(질문으로 돌린다), 적혀 있는데 틀리면 FilingError 를 낸다.
questions 비어 있거나 하나로 정하지 못한 값을 문항 목록으로 낸다. 목록이 비면 신고값을 만들 수 있다.

신고인 JSON 의 인적사항(성명, 주민등록번호, 전화, 주소)은 오류 문장과 질문 내용에 쓰지 않는다. 항목 이름만 적는다.
법정동코드 찾기는 bjd 모듈(Bjd.lookup, candidates, exists)이 한다. 시험은 가짜 객체를 bjd 인자로 넣는다.
주민등록번호의 검증번호는 2020-10 이후 발급·변경된 번호가 옛 규칙과 맞지 않을 수 있어 오류가 아니라 경고로 돌린다.
load 가 돌려주는 dict 의 `_경고` 목록이다(값을 싣지 않는 문장, 없으면 빈 목록).
"""
import copy
import json
import os
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from fractions import Fraction

from yangdo.dates import to_date


class FilingError(Exception):
    """신고인 JSON 의 형식이 틀렸거나 이번 범위가 아니다."""


SECTIONS = {"신고": dict, "신고인": dict, "양수인": list, "자산": dict}
구분값 = ("예정", "확정")
내외국인 = ("1", "9")
양수인구분 = ("1", "2")        # 1 주민등록번호, 2 사업자등록번호
RRN_W = (2, 3, 4, 5, 6, 7, 8, 9, 2, 3, 4, 5)
BIZ_W = (1, 3, 7, 1, 3, 7, 1, 3, 5)
FIELD_NAMES = ("성명", "주민등록번호", "전화", "내외국인", "거주구분", "거주지국", "국적")
ADDR_NAMES = ("시도", "시군구", "읍면동", "번지", "호")
BUYER_NAMES = ("구분", "내외국인", "번호", "성명", "지분")
RRN_WARNING = "의 검증번호가 옛 규칙과 다르다. 2020-10 이후 발급·변경된 번호가 아니면 다시 확인하라"
경매원인후보 = "0336 임의경매로 인한 매각, 0337 강제경매로 인한 매각, 0302, 0303, 0015 경락, 0021 공매"


def _err(where, msg):
    raise FilingError("%s: %s" % (where, msg))


def _blank(v):
    return v is None or (isinstance(v, str) and not v.strip())


# ---------------------------------------------------------------- 낱개 검사

def rrn_shape_ok(s):
    """주민등록번호(외국인등록번호 포함) 13자리 ASCII 숫자, 앞 6자리가 있는 생년월일, 성별 자리 1~8.

    성별 자리 1·2·5·6 은 1900년대, 3·4·7·8 은 2000년대 출생이다. 검증번호는 여기서 보지 않는다.
    """
    if not (isinstance(s, str) and re.fullmatch(r"[0-9]{13}", s)) or s[6] not in "12345678":
        return False
    year = (1900 if s[6] in "1256" else 2000) + int(s[0:2])
    try:
        date(year, int(s[2:4]), int(s[4:6]))
    except ValueError:
        return False
    return True


def rrn_ok(s):
    """주민등록번호 13자리와 검증번호. 모양이 맞아도 2020-10 이후 번호는 이 규칙과 다를 수 있다."""
    if not (isinstance(s, str) and re.fullmatch(r"[0-9]{13}", s)):
        return False
    return (11 - sum(int(a) * b for a, b in zip(s, RRN_W)) % 11) % 10 == int(s[12])


def biz_ok(s):
    """사업자등록번호 10자리와 검증번호. 아홉째 자리 곱의 10의 몫을 더한다."""
    if not (isinstance(s, str) and re.fullmatch(r"[0-9]{10}", s)):
        return False
    total = sum(int(a) * b for a, b in zip(s, BIZ_W)) + int(s[8]) * BIZ_W[8] // 10
    return (10 - total % 10) % 10 == int(s[9])


def ksx1001_ok(text, symbols=False):
    """CP949 로 쓸 때 KS X 1001 완성형 2바이트(첫 바이트 0xB0~0xC8, 둘째 0xA1~0xFE)와 ASCII(0x20~0x7E)만 쓰는지.

    CP949 는 「똠」 같은 확장 영역 글자도 인코딩해 주지만 전자신고 파일에서는 받지 않는다. symbols 가 참이면
    기호 행(첫 바이트 0xA1~0xAC, 가운뎃점 등)도 받는다.
    """
    try:
        raw = text.encode("cp949")
    except UnicodeEncodeError:
        return False
    i = 0
    while i < len(raw):
        b = raw[i]
        if 0x20 <= b <= 0x7E:
            i += 1
            continue
        if i + 1 >= len(raw) or not 0xA1 <= raw[i + 1] <= 0xFE:
            return False
        if not (0xB0 <= b <= 0xC8 or (symbols and 0xA1 <= b <= 0xAC)):
            return False
        i += 2
    return True


def _text(v, where, maxbytes, symbols=False):
    if _blank(v):
        return
    if not isinstance(v, str):
        _err(where, "글자로 적는다")
    if not ksx1001_ok(v, symbols):
        _err(where, "전자신고 파일(KS X 1001 완성형)로 쓸 수 없는 글자가 있다")
    if len(v.encode("cp949")) > maxbytes:
        _err(where, "CP949 로 %d바이트를 넘을 수 없다" % maxbytes)


def _digits(v, where, label, n=None, maxn=None):
    if _blank(v):
        return
    ok = isinstance(v, str) and re.fullmatch(r"[0-9]+", v) and (len(v) == n if n else len(v) <= maxn)
    if not ok:
        _err(where, label)


def _choice(v, where, allowed):
    if not _blank(v) and v not in allowed:
        _err(where, "%s 중 하나로 적는다" % ", ".join("'%s'" % a for a in allowed))


def _number(v, where):
    """JSON 숫자를 Decimal 로. 전자신고 파일의 수치 칸이 NUMBER(11,3)이라 소수 셋째 자리, 정수 8자리까지만 받는다."""
    if isinstance(v, bool) or not isinstance(v, (int, float, Decimal)):
        _err(where, "숫자로 적는다")
    try:
        d = Decimal(str(v))
    except InvalidOperation:
        _err(where, "숫자로 적는다")
    if not d.is_finite() or d < 0 or d >= 10 ** 8 or d.as_tuple().exponent < -3:
        _err(where, "0 이상 1억 미만, 소수 셋째 자리까지의 숫자로 적는다")
    return d


def _share(v, where):
    """지분 {분자, 분모} 를 분수로. 비어 있으면 None."""
    if _blank(v):
        return None
    if not isinstance(v, dict) or set(v) - {"분자", "분모"} or v.get("분자") is None or v.get("분모") is None:
        _err(where, "{\"분자\": 숫자, \"분모\": 숫자} 로 적는다")
    a, b = _number(v["분자"], where + ".분자"), _number(v["분모"], where + ".분모")
    if a <= 0 or b <= 0 or a > b:
        _err(where, "0 보다 크고 1 이하인 분수여야 한다")
    return Fraction(a) / Fraction(b)


def _date(v, where):
    if _blank(v):
        return
    if not isinstance(v, str):
        _err(where, "YYYY-MM-DD 로 적는다")
    try:
        to_date(v)
    except ValueError:
        _err(where, "있는 날짜를 YYYY-MM-DD 로 적는다")


# ---------------------------------------------------------------- 구역별 검사

def _check_filing(s):
    _choice(s.get("구분"), "신고.구분", 구분값)
    _date(s.get("작성일"), "신고.작성일")
    hid = s.get("홈택스ID")
    if not _blank(hid) and not (isinstance(hid, str) and re.fullmatch(r"[\x21-\x7e]{1,20}", hid)):
        _err("신고.홈택스ID", "공백 없는 영문·숫자·기호 20자 이내로 적는다")
    if not _blank(s.get("분납신청")) and not isinstance(s["분납신청"], bool):
        _err("신고.분납신청", "true 또는 false 로 적는다")


def _check_addr(a, where):
    if not isinstance(a, dict):
        _err(where, "시도, 시군구, 읍면동, 번지, 호를 나눈 객체로 적는다")
    for k in ("시도", "시군구", "읍면동"):
        if a.get(k) is not None and not isinstance(a[k], str):
            _err("%s.%s" % (where, k), "글자로 적는다")
    if not _blank(a.get("특수지")) and not (isinstance(a["특수지"], str) and re.fullmatch(r"[0-9]", a["특수지"])):
        _err(where + ".특수지", "0~9 한 자리 코드로 적는다")
    _digits(a.get("번지"), where + ".번지", "숫자 4자리 이내로 적는다(산·가 같은 구분은 특수지 코드에 둔다)", maxn=4)
    _digits(a.get("호"), where + ".호", "숫자 4자리 이내로 적는다", maxn=4)
    _text(a.get("아파트명"), where + ".아파트명", 40, symbols=True)
    _text(a.get("아파트동"), where + ".아파트동", 12, symbols=True)
    _text(a.get("아파트호"), where + ".아파트호", 12, symbols=True)
    _digits(a.get("법정동코드"), where + ".법정동코드", "숫자 10자리로 적는다", n=10)


def _check_rrn(n, where, label, 외국인, warns):
    """모양(13자리 ASCII 숫자, 생년월일, 성별 자리)이 틀리면 오류, 검증번호만 다르면 경고. 외국인은 검증번호를 보지 않는다."""
    if _blank(n):
        return
    if not (isinstance(n, str) and re.fullmatch(r"[0-9]{13}", n)):
        _err(where, "하이픈 없이 숫자 13자리로 적는다")
    if not rrn_shape_ok(n):
        _err(where, "생년월일(앞 6자리)이나 성별 자리(1~8)가 맞지 않는다")
    if not 외국인 and not rrn_ok(n):
        warns.append(label + RRN_WARNING)


def _check_person(p, warns):
    _text(p.get("성명"), "신고인.성명", 30)
    _choice(p.get("내외국인"), "신고인.내외국인", 내외국인)
    _check_rrn(p.get("주민등록번호"), "신고인.주민등록번호", "신고인 주민등록번호", p.get("내외국인") == "9", warns)
    if not _blank(p.get("거주구분")) and p["거주구분"] != "1":
        _err("신고인.거주구분", "거주자('1')만 받는다. 비거주자 신고는 이번 범위가 아니다")
    for k in ("거주지국", "국적"):
        if not _blank(p.get(k)) and not (isinstance(p[k], str) and re.fullmatch(r"[A-Z]{2}", p[k])):
            _err("신고인." + k, "영문 대문자 2자리 국가코드로 적는다")
    if not _blank(p.get("거주지국")) and p["거주지국"] != "KR":
        _err("신고인.거주지국", "거주자이므로 KR 이어야 한다")
    if not _blank(p.get("국적")):
        if p.get("내외국인") == "1" and p["국적"] != "KR":
            _err("신고인.국적", "내국인이면 KR 이어야 한다")
        if p.get("내외국인") == "9" and p["국적"] == "KR":
            _err("신고인.국적", "외국인이면 KR 이 아니어야 한다")
    _digits(p.get("전화"), "신고인.전화", "숫자만 12자리 이내로 적는다(하이픈과 괄호는 뺀다)", maxn=12)
    mail = p.get("전자메일")
    if not _blank(mail) and not (isinstance(mail, str) and re.fullmatch(r"[\x21-\x7e]+@[\x21-\x7e]+", mail) and len(mail) <= 50):
        _err("신고인.전자메일", "영문으로 된 메일 주소 50자 이내로 적는다")
    _check_addr(p["주소"] if p.get("주소") is not None else {}, "신고인.주소")


def _check_buyer(b, i, warns):
    w = "양수인[%d]" % i
    if not isinstance(b, dict):
        _err(w, "객체로 적는다")
    if _blank(b.get("자산")) or not isinstance(b["자산"], str):
        _err(w + ".자산", "자산 ID 를 글자로 적는다")
    _choice(b.get("구분"), w + ".구분", 양수인구분)
    _choice(b.get("내외국인"), w + ".내외국인", 내외국인)
    n = b.get("번호")
    if not _blank(n):
        if b.get("구분") == "2":
            if not biz_ok(n):
                _err(w + ".번호", "검증번호가 맞는 사업자등록번호 숫자 10자리여야 한다")
        else:
            _check_rrn(n, w + ".번호", "%s 번호" % w, b.get("내외국인") == "9", warns)
    code = b.get("관계코드")
    if not _blank(code) and not (isinstance(code, str) and re.fullmatch(r"[0-9A-Za-z]{2}", code)):
        _err(w + ".관계코드", "규격서 별첨(p107~109)의 2자리 영문·숫자 코드로 적는다")
    _text(b.get("성명"), w + ".성명", 60)
    _digits(b.get("전화"), w + ".전화", "숫자만 12자리 이내로 적는다(하이픈과 괄호는 뺀다)", maxn=12)
    _share(b.get("지분"), w + ".지분")


def _check_lot(aid, lot):
    w = "자산.%s" % aid
    if not isinstance(lot, dict):
        _err(w, "객체로 적는다")
    _check_addr(lot, w)
    area = lot.get("총면적")
    if not _blank(area):
        if not isinstance(area, dict) or set(area) - {"토지", "건물"}:
            _err(w + ".총면적", "{\"토지\": 숫자, \"건물\": 숫자} 로 적는다")
        for k, v in area.items():
            if not _blank(v):
                _number(v, "%s.총면적.%s" % (w, k))
    cause = lot.get("등기원인")
    if not _blank(cause):
        if not isinstance(cause, dict) or set(cause) - {"취득", "양도"}:
            _err(w + ".등기원인", "{\"취득\": \"0336\", \"양도\": \"0337\"} 처럼 취득이나 양도 쪽 키로 적는다")
        for k, v in cause.items():
            _digits(v, "%s.등기원인.%s" % (w, k), "숫자 4자리 등기원인 코드로 적는다", n=4)


def _check_refund(r):
    if _blank(r):
        return
    if not isinstance(r, dict):
        _err("환급계좌", "{\"은행코드\": ..., \"계좌번호\": ...} 또는 null 로 적는다")
    _digits(r.get("은행코드"), "환급계좌.은행코드", "숫자 3자리 은행코드로 적는다", n=3)
    _digits(r.get("계좌번호"), "환급계좌.계좌번호", "숫자만 16자리 이내로 적는다(하이픈은 뺀다)", maxn=16)


# ---------------------------------------------------------------- load

def _read(src):
    if isinstance(src, dict):
        return copy.deepcopy(src)
    if isinstance(src, (str, os.PathLike)):
        try:
            with open(src, encoding="utf-8-sig") as fh:
                data = json.load(fh)
        except OSError:
            raise FilingError("신고인 파일을 읽지 못했다(%s)" % os.path.basename(os.fspath(src)))
        except ValueError:
            raise FilingError("신고인 파일이 UTF-8 JSON 이 아니다(%s)" % os.path.basename(os.fspath(src)))
        if not isinstance(data, dict):
            raise FilingError("신고인 파일의 맨 위는 객체여야 한다")
        return data
    raise FilingError("신고인 정보는 파일 경로나 객체로 받는다")


def load(src):
    """신고인 JSON(경로 또는 dict)을 읽어 형식을 검사한 복사본을 돌려준다. 틀리면 FilingError.

    빠진 구역은 빈 값으로 채운다. 값이 비어 있는 것(None, 빈 글자)은 오류가 아니라 questions 가 묻는다.
    신고인·자산의 특수지가 비면 "0"(일반 지번)으로 채운다.
    주민등록번호의 검증번호만 다르면 오류가 아니라 결과의 `_경고` 목록에 값을 싣지 않는 문장으로 둔다(항상 있고 없으면 빈 목록).
    """
    f = _read(src)
    if f.get("세무대리인") is not None:
        raise FilingError("세무대리 신고는 이번 범위가 아니다. 세무대리인은 null 로 둔다")
    for name, kind in SECTIONS.items():
        if _blank(f.get(name)):
            f[name] = kind()
        elif not isinstance(f[name], kind):
            raise FilingError("%s: %s 이어야 한다" % (name, "객체" if kind is dict else "목록"))
    f.setdefault("환급계좌", None)
    f.setdefault("세무대리인", None)
    warns = []
    _check_filing(f["신고"])
    _check_person(f["신고인"], warns)
    for i, b in enumerate(f["양수인"]):
        _check_buyer(b, i, warns)
    for aid, lot in f["자산"].items():
        _check_lot(aid, lot)
    _check_refund(f["환급계좌"])
    for a in [f["신고인"].get("주소")] + list(f["자산"].values()):
        if isinstance(a, dict) and _blank(a.get("특수지")):
            a["특수지"] = "0"
    f["_경고"] = warns
    return f


# ---------------------------------------------------------------- 법정동코드

class _Late:
    """bjd 를 처음 쓸 때 읽는다. 주지 않으면 yangdo.bjd.load() 를 부른다.

    법정동코드를 확인할 일(코드가 적혀 있어 존재를 보거나, 시도·시군구·읍면동으로 찾는 일)이 없으면 읽지 않는다.
    그래서 주소가 하나도 없는 신고인만 bjd 모듈 없이 돈다. 코드가 모두 적힌 신고인도 존재 검사 때문에 읽는다.
    """

    def __init__(self, bjd=None):
        self._bjd = bjd

    def get(self):
        if self._bjd is None:
            from yangdo import bjd as _bjd
            self._bjd = _bjd.load()
        return self._bjd


def _resolve(addr, late, on):
    """(상태, 값). 상태는 ok(코드), no_address, ambiguous(후보 목록), not_found, unknown_code(적은 코드)."""
    addr = addr or {}
    given = addr.get("법정동코드")
    if not _blank(given):
        return ("ok", given) if late.get().exists(given) else ("unknown_code", given)
    parts = [addr.get(k) for k in ("시도", "시군구", "읍면동")]
    if any(_blank(p) for p in parts):
        return "no_address", None
    b = late.get()
    code = b.lookup(parts[0], parts[1], parts[2], on=on)
    if code:
        return "ok", code
    cands = list(b.candidates(*parts) or [])
    return ("ambiguous", cands) if cands else ("not_found", None)


def dong_code(addr, bjd=None, on=None):
    """주소의 법정동코드 10자리. 적어 둔 코드가 법정동코드표에 있으면 그것, 없으면 시도·시군구·읍면동으로 찾는다.

    찾지 못했거나 후보가 여럿이면 None. questions 와 신고값 생성이 같은 방법으로 찾도록 여기 한 곳에 둔다.
    """
    state, val = _resolve(addr, _Late(bjd), on)
    return val if state == "ok" else None


# ---------------------------------------------------------------- questions

def _q(no, asset, text):
    return {"문항": no, "자산": asset, "내용": text}


def _share_or_none(v):
    try:
        return _share(v, "지분")
    except FilingError:
        return None


def _zero_lot(addr):
    """번지 0 은 특수지가 9(무번지)일 때만 쓴다. 특수지가 비어 있으면 0(일반 지번)으로 본다."""
    return addr.get("번지") == "0" and (addr.get("특수지") or "0") != "9"


def _f01(p, late, on):
    p = p or {}
    a = p.get("주소") or {}
    miss = [k for k in FIELD_NAMES if _blank(p.get(k))] + ["주소." + k for k in ADDR_NAMES if _blank(a.get(k))]
    out = []
    if miss:
        out.append("신고인 본인 정보에서 빠진 것: %s." % ", ".join(miss))
    if _zero_lot(a):
        out.append("신고인.주소의 번지가 0 이면 특수지가 9(무번지)여야 합니다. 번지를 확인해 주세요.")
    state, _ = _resolve(a, late, on)      # 주소의 시도·시군구·읍면동이 비어 있으면 위에서 이미 알렸다
    if state == "unknown_code":
        out.append("신고인.주소의 법정동코드가 법정동코드표에 없습니다. 다시 확인해 주세요.")
    elif state in ("ambiguous", "not_found"):
        out.append("신고인.주소의 법정동코드를 하나로 정하지 못했습니다. 주소를 더 자세히 적거나 법정동코드 10자리를 직접 적어 주세요.")
    return [_q("F01", None, " ".join(out))] if out else []


def _f02(f, assets):
    buyers = f.get("양수인") or []
    out = []
    asset_ids = list(assets)
    for aid in asset_ids + [a for a in dict.fromkeys(b.get("자산") for b in buyers) if a not in assets]:
        mine = [b for b in buyers if b.get("자산") == aid]
        why = []
        related = (assets.get(aid) or {}).get("매수인관계") not in (None, "", "타인")
        if aid not in assets:
            why.append("양수인에 적은 자산 ID 가 사실관계의 자산에 없습니다. 자산 ID 를 확인해 주세요.")
        elif not mine:
            why.append("이 자산을 산 양수인이 없습니다. 양수인에 구분, 내외국인, 번호, 성명, 지분을 적어 주세요.")
        for n, b in enumerate(mine, 1):
            miss = [k for k in BUYER_NAMES + (("관계코드",) if related else ()) if _blank(b.get(k))]
            if miss:
                why.append("양수인 %d번째에 빠진 것: %s." % (n, ", ".join(miss)))
        if related and any(_blank(b.get("관계코드")) for b in mine):
            why.append("양수인이 양도인과 타인이 아니라서 양수인마다 규격서 p107~109 관계코드(2자리)를 적어야 합니다.")
        shares = [_share_or_none(b.get("지분")) for b in mine]
        if mine and all(s is not None for s in shares) and sum(shares) != 1:
            why.append("양수인 지분의 합이 %s 입니다. 한 자산의 지분 합은 1 이어야 합니다." % sum(shares))
        if why:
            out.append(_q("F02", aid, " ".join(why)))
    return out


def _f03(f):
    if _blank((f.get("신고") or {}).get("분납신청")):
        return [_q("F03", None, "분납을 신청하면 신고.분납신청에 true, 아니면 false 를 적어 주세요. 분납할 수 있는 세액인지는 신고서를 만들 때 규칙세트로 따로 봅니다.")]
    return []


def _f04(f, facts, late, on):
    lots = f.get("자산") or {}
    out = []
    for a in (facts or {}).get("자산") or []:
        aid = a.get("id")
        lot = lots.get(aid)
        why = []
        if lot is None:
            why.append("신고인 파일의 자산에 이 자산의 항목이 없습니다.")
        miss = [k for k in ("번지", "호") if _blank((lot or {}).get(k))]
        if miss:
            why.append("지번에서 빠진 것: %s." % ", ".join(miss))
        if _zero_lot(lot or {}):
            why.append("번지가 0 이면 특수지가 9(무번지)여야 합니다. 번지를 확인해 주세요.")
        cause = (lot or {}).get("등기원인") or {}
        for side in ("취득", "양도"):
            if (a.get(side) or {}).get("원인") == "경매" and _blank(cause.get(side)):
                why.append("경매로 %s한 자산은 임의경매인지 강제경매인지를 엔진이 나누지 않아 등기원인 코드를 직접 받습니다. "
                           "자산의 등기원인 %s 에 4자리 코드를 적어 주세요. 후보: %s." % (side, side, 경매원인후보))
        addr = dict(a.get("소재지") or {}, 법정동코드=(lot or {}).get("법정동코드"))
        state, val = _resolve(addr, late, on)
        if state == "no_address":
            why.append("사실관계의 소재지에서 읍면동을 알 수 없어 법정동코드를 찾지 못했습니다. 자산의 법정동코드에 10자리로 적어 주세요.")
        elif state == "not_found":
            why.append("법정동코드를 찾지 못했습니다. 자산의 법정동코드에 10자리로 적어 주세요.")
        elif state == "ambiguous":
            why.append("법정동코드를 하나로 정하지 못했습니다. 후보 %d개: %s. 하나를 골라 자산의 법정동코드에 적어 주세요."
                       % (len(val), ", ".join(val[:10])))
        elif state == "unknown_code":
            why.append("적은 법정동코드가 법정동코드표에 없습니다. 다시 확인해 주세요.")
        if why:
            out.append(_q("F04", aid, " ".join(why)))
    return out


def _f05(f):
    s = f.get("신고") or {}
    miss = [("신고." + k) for k in ("구분", "작성일") if _blank(s.get(k))]
    if miss:
        return [_q("F05", None, "적어야 할 것: %s. 구분은 예정 또는 확정, 작성일은 YYYY-MM-DD 로 적습니다." % ", ".join(miss))]
    return []


def _f06(f):
    if _blank((f.get("신고") or {}).get("홈택스ID")):
        return [_q("F06", None, "신고서를 올릴 홈택스 사용자 ID 를 신고.홈택스ID 에 적어 주세요.")]
    return []


def questions(filer, facts, result=None, bjd=None):
    """빠진 신고인 정보를 문항 목록으로. [{"문항": "F01", "자산": None, "내용": "..."}]. 비면 신고값을 만들 수 있다.

    filer 는 load 의 결과, facts 는 사실관계(자산 목록을 본다). result 는 지금은 쓰지 않는다(분납 가능 여부는
    규칙세트 값이라 신고값 생성이 판정한다). bjd 는 시험용 주입 인자이고 없으면 yangdo.bjd.load() 를 처음 쓸 때 읽는다.
    내용에는 인적사항 값을 쓰지 않고 항목 이름만 적는다.

    타인이 아닌 양수인(사실관계 매수인관계)은 관계코드를 F02 로, 경매로 취득하거나 양도한 자산은 등기원인을 F04 로 묻는다.
    번지 0 은 특수지 9 일 때만 받아 F01·F04 로 되묻는다.
    """
    late = _Late(bjd)
    on = ((filer.get("신고") or {}).get("작성일")) or None
    assets = {a.get("id"): a for a in (facts or {}).get("자산") or []}
    return (_f01(filer.get("신고인"), late, on) + _f02(filer, assets) + _f03(filer)
            + _f04(filer, facts, late, on) + _f05(filer) + _f06(filer))
