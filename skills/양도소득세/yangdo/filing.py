# -*- coding: utf-8 -*-
"""신고인 정보. 신고인.json(계약 C7)의 형식을 검사하고, 빠진 것을 서식 단계 문항 F01~F08 으로 돌려준다.

load      형식만 본다. 값이 비어 있으면 통과시키고(질문으로 돌린다), 적혀 있는데 틀리면 FilingError 를 낸다.
questions 비어 있거나 하나로 정하지 못한 값을 문항 목록으로 낸다. 목록이 비면 신고값을 만들 수 있다.
          F07(필수 구분코드 지출의 지급처 사업자번호와 지급일)과 F08(매입가액 행의 취득 상대방)은 계산이 끝난 결과를 보고 묻는다.
          전자신고 파일 검증기가 막는 입력 가운데 신고인 파일과 사실관계로 알 수 있는 것은 여기서 먼저 묻는다. 신고서 PDF 를
          만든 뒤에야 파일 검증에서 걸리지 않게 하려는 것이다: 0 으로만 된 번지(00), 앞에 0 을 붙인 번지, 시도·시군구 단계의
          법정동코드, 필수 구분코드 지출의 빠진 지급일.

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

from yangdo import edition
from yangdo.dates import to_date
# KS X 1001 완성형 검사(yangdo/ksx.py). 옛 이름 filing.ksx1001_ok 로도 부를 수 있다
from yangdo.ksx import ksx1001_ok


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
# 등기목적 소유권이전(A1ZZCZ)에 쓰는 경매 쪽 등기원인(규격서 p109~110, efile/codes_c116300.json 등기원인목록). 코드마다 이름을 적는다
경매원인후보 = ("0336 임의경매로 인한 매각, 0337 강제경매로 인한 매각, 0302 임의경매로 인한 낙찰, 0303 강제경매로 인한 낙찰, "
          "0015 경락, 0021 공매")
# 법정동코드 10자리는 시도 2 + 시군구 3 + 읍면동 3 + 리 2 자리다. 읍면동 자리가 000 이면 시도나 시군구 행이다
_ABOVE_DONG = re.compile(r"[0-9]{5}000[0-9]{2}")


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


def _text(v, where, maxbytes, symbols=False):
    if _blank(v):
        return
    if not isinstance(v, str):
        _err(where, "글자로 적는다")
    if not ksx1001_ok(v, symbols):
        _err(where, "한글 완성형(KS X 1001)과 ASCII 가 아닌 글자가 있다" if edition.PUBLIC
             else "전자신고 파일(KS X 1001 완성형)로 쓸 수 없는 글자가 있다")
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
    _text(lot.get("취득상대방"), w + ".취득상대방", 60)
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


# ---------------------------------------------------------------- 모르는 키

UNKNOWN_KEYS_HEAD = "신고인 파일의 다음 키는 양식에 없는 이름이라 반영하지 않았다"
_ADDRESS_KEYS = {"시도", "시군구", "읍면동", "특수지", "번지", "호", "아파트명", "아파트동", "아파트호", "법정동코드"}
_KNOWN_KEYS = {
    "": {"신고", "신고인", "양수인", "자산", "환급계좌", "세무대리인"},
    "신고": {"구분", "작성일", "홈택스ID", "분납신청"},
    "신고인": set(FIELD_NAMES) | {"주소", "전자메일"},
    "신고인.주소": _ADDRESS_KEYS,
    "양수인": {"자산", "구분", "내외국인", "번호", "성명", "전화", "지분", "관계코드"},
    "자산": (_ADDRESS_KEYS - {"시도", "시군구", "읍면동"}) | {"총면적", "취득상대방", "등기원인", "등기목적"},     # 자산 소재지는 사실관계에서 읽는다
    "환급계좌": {"은행코드", "계좌번호"},
}


def _unknown_keys(f):
    """구역마다 받는 키 목록에 없는 키의 경로(키 이름만, 값은 싣지 않는다). `_` 로 시작하는 키는 양식의 설명용 키라 뺀다."""
    def extra(d, where, known):
        return ["%s.%s" % (where, k) if where else str(k) for k in d if not str(k).startswith("_") and k not in known]
    found = extra(f, "", _KNOWN_KEYS[""])
    for sec in ("신고", "신고인", "환급계좌"):
        if isinstance(f.get(sec), dict):
            found += extra(f[sec], sec, _KNOWN_KEYS[sec])
    if isinstance(f.get("신고인"), dict) and isinstance(f["신고인"].get("주소"), dict):
        found += extra(f["신고인"]["주소"], "신고인.주소", _KNOWN_KEYS["신고인.주소"])
    for i, b in enumerate(f.get("양수인") if isinstance(f.get("양수인"), list) else [], 1):
        if isinstance(b, dict):
            found += extra(b, "양수인[%d]" % i, _KNOWN_KEYS["양수인"])
    for aid, lot in (f.get("자산") if isinstance(f.get("자산"), dict) else {}).items():
        if isinstance(lot, dict):
            found += extra(lot, "자산.%s" % aid, _KNOWN_KEYS["자산"])
    return [x[:60] for x in found]


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
    unknown = _unknown_keys(f)
    if unknown:
        warns.append("%s: %s. 키 이름이 신고인_양식.json 과 같은지 확인한다" % (UNKNOWN_KEYS_HEAD, ", ".join(unknown)))
    f["_경고"] = warns
    return f


# ---------------------------------------------------------------- 법정동코드

class _Late:
    """bjd 를 처음 쓸 때 읽는다. 주지 않으면 yangdo.bjd.load() 를 부른다.

    법정동코드를 확인할 일(코드가 적혀 있어 존재를 보거나, 시도·시군구·읍면동으로 찾는 일)이 없으면 읽지 않는다.
    그래서 주소가 하나도 없는 신고인만 bjd 모듈 없이 돈다. 코드가 모두 적힌 신고인도 존재 검사 때문에 읽는다.
    """

    def __init__(self, bjd=None, efile_dir=None):
        self._bjd = bjd
        self._efile_dir = efile_dir

    def get(self):
        if self._bjd is None:
            from yangdo import bjd as _bjd
            self._bjd = _bjd.load(self._efile_dir)
        return self._bjd


def _resolve(addr, late, on):
    """(상태, 값). 상태는 ok(코드), no_address, ambiguous(후보 목록), not_found, unknown_code(적은 코드),
    above_dong(적은 코드가 시도나 시군구 단계). 전자신고 파일의 법정동코드 칸(02-3, 05-8)은 읍면동이나 리 단계 코드만 받는다."""
    addr = addr or {}
    given = addr.get("법정동코드")
    if not _blank(given):
        if not late.get().exists(given):
            return "unknown_code", given
        if isinstance(given, str) and _ABOVE_DONG.fullmatch(given):
            return "above_dong", given
        return "ok", given
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
    """주소의 법정동코드 10자리. 적어 둔 코드가 법정동코드표에 있는 읍면동(또는 리) 단계 코드면 그것, 적지 않았으면 시도·시군구·읍면동으로 찾는다.

    찾지 못했거나 후보가 여럿이거나 적어 둔 코드가 표에 없거나 시도·시군구 단계면 None. questions 와 신고값 생성이 같은 방법으로 찾도록 여기 한 곳에 둔다.
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


def _lot_problem(addr):
    """번지의 꼴이 전자신고 파일에 쓸 수 없으면 그 까닭(문장), 괜찮으면 None.

    0 으로만 된 번지(0, 00, 000)는 특수지가 9(무번지)일 때만 쓰고(규격서 p30·p48) 「0」 한 글자로 적는다. 특수지가 비어 있으면
    0(일반 지번)으로 본다. 앞에 0 을 붙인 번지(0123)는 받지 않는다. 숫자가 아닌 번지는 load 가 형식 오류로 막는다."""
    no = addr.get("번지")
    if not isinstance(no, str) or not no.startswith("0"):
        return None
    if re.fullmatch(r"0+", no):
        if (addr.get("특수지") or "0") != "9":
            return "번지가 0 이면 특수지가 9(무번지)여야 합니다. 번지를 확인해 주세요."
        return None if no == "0" else "무번지(특수지 9)의 번지는 0 한 글자로 적어 주세요."
    return "번지는 앞에 0 을 붙이지 않고 적어 주세요."


def _f01(p, late, on):
    p = p or {}
    a = p.get("주소") or {}
    miss = [k for k in FIELD_NAMES if _blank(p.get(k))] + ["주소." + k for k in ADDR_NAMES if _blank(a.get(k))]
    out = []
    if miss:
        out.append("신고인 본인 정보에서 빠진 것: %s." % ", ".join(miss))
    lot = _lot_problem(a)
    if lot:
        out.append("신고인.주소의 " + lot)
    state, _ = _resolve(a, late, on)      # 주소의 시도·시군구·읍면동이 비어 있으면 위에서 이미 알렸다
    if state == "unknown_code":
        out.append("신고인.주소의 법정동코드가 법정동코드표에 없습니다. 다시 확인해 주세요.")
    elif state == "above_dong":
        out.append("신고인.주소의 법정동코드가 시도나 시군구 단계 코드입니다. 읍면동(읍·면 아래 리가 있으면 리)까지 내려간 10자리 코드를 적어 주세요.")
    elif state in ("ambiguous", "not_found"):
        out.append("신고인.주소의 법정동코드를 하나로 정하지 못했습니다. 주소를 더 자세히 적거나 법정동코드 10자리를 직접 적어 주세요.")
    return [_q("F01", None, " ".join(out))] if out else []


def _f02(f, assets, skip=()):
    buyers = [b for b in f.get("양수인") or [] if b.get("자산") not in skip]      # 신고서에 넣지 않는 자산의 양수인은 보지 않는다
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


def _f04(f, facts, late, on, skip=()):
    lots = f.get("자산") or {}
    out = []
    for a in (facts or {}).get("자산") or []:
        aid = a.get("id")
        if aid in skip:
            continue
        lot = lots.get(aid)
        why = []
        if lot is None:
            why.append("신고인 파일의 자산에 이 자산의 항목이 없습니다.")
        miss = [k for k in ("번지", "호") if _blank((lot or {}).get(k))]
        if miss:
            why.append("지번에서 빠진 것: %s." % ", ".join(miss))
        bad_lot = _lot_problem(lot or {})
        if bad_lot:
            why.append(bad_lot)
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
        elif state == "above_dong":
            why.append("적은 법정동코드가 시도나 시군구 단계 코드입니다. 읍면동(읍·면 아래 리가 있으면 리)까지 내려간 10자리 코드를 적어 주세요.")
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


def _seller_ok(v):
    return isinstance(v, str) and ksx1001_ok(v) and len(v.encode("cp949")) <= 60


def _spend(ln, dated=True):
    """지출을 「취득부대의 1번째 지출(중개수수료, 2018-03-15)」 로만 가리킨다. 번호는 사실관계 목록의 순서다. 금액·상호·번호는 싣지 않는다.
    dated 가 거짓이면 지급일을 읽지 못한 지출이라 적힌 값을 옮기지 않고 「지급일 없음」으로 적는다."""
    it = ln.item
    day = it.get("지급일") if dated and isinstance(it.get("지급일"), str) and it["지급일"].strip() else None
    return "%s의 %d번째 지출(%s, %s)" % (ln.group, ln.no, it.get("내용") or "내용 없음", day or "지급일 없음")


def _paid_on_ok(v):
    """지출의 지급일이 YYYY-MM-DD 로 읽히는 있는 날짜인가."""
    if _blank(v):
        return False
    try:
        return to_date(v) is not None
    except ValueError:
        return False


def _f07(aid, lines, codes):
    """07 레코드는 필수 구분코드에 지급금액이 있으면 사업자번호와 지급일자가 있어야 한다(규격서 p60).
    사업자번호가 비었거나 검증번호가 틀린 지출, 지급일이 없거나 읽을 수 없는 지출을 모아 자산마다 한 번에 묻는다."""
    blank, wrong, undated = [], [], []
    for ln in lines:
        it = ln.item
        if it is None or not codes[ln.key]["필수"] or not int(it.get("금액") or 0):
            continue
        if not biz_ok(it.get("사업자번호")):
            (blank if _blank(it.get("사업자번호")) else wrong).append(_spend(ln))
        if not _paid_on_ok(it.get("지급일")):
            undated.append(_spend(dated=False, ln=ln))
    if not (blank or wrong or undated):
        return []
    text = ["전자신고 07 레코드는 지급금액이 있는 필수 구분코드 지출에 지급처 사업자번호와 지급일자가 있어야 합니다(규격서 p60)."]
    if blank:
        text.append("사업자번호가 비어 있는 지출: %s." % ", ".join(blank))
    if wrong:
        text.append("사업자번호의 형식이나 검증번호가 틀린 지출: %s." % ", ".join(wrong))
    if undated:
        text.append("지급일이 없거나 읽을 수 없는 지출: %s." % ", ".join(undated))
    if blank or wrong:
        text.append("사실관계의 해당 지출 항목에 사업자번호를 하이픈 없이 숫자 10자리로 적어 주세요.")
    if undated:
        text.append("사실관계의 해당 지출 항목 지급일에 YYYY-MM-DD 로 적어 주세요.")
    return [_q("F07", aid, " ".join(text))]


def _f08(aid, lines, lot):
    """07 레코드의 매입가액(11101) 행은 상호가 Not Null 이고 취득 상대방(매도인)의 성명이나 상호를 쓴다(규격서 p59~60)."""
    if not any(ln.group == "매입가액" for ln in lines):
        return []
    v = (lot or {}).get("취득상대방")
    if not _blank(v) and _seller_ok(v):
        return []
    if edition.PUBLIC:      # 공개본에는 전자신고 파일이 없다. 같은 값을 부표3 매입가액 행의 거래상대방 칸에 적는다
        head = ("적은 취득상대방에 신고서에 쓸 수 없는 글자(한글 완성형이 아닌 글자, ㈜·가운뎃점 같은 기호 포함)가 있거나 60바이트를 "
                "넘습니다. " if not _blank(v) else
                "부표3 매입가액 행의 거래상대방 칸에 산 곳(매도인)의 성명이나 상호를 적습니다. ")
    else:
        head = ("적은 취득상대방에 전자신고 파일로 쓸 수 없는 글자(㈜·가운뎃점 같은 기호 포함)가 있거나 60바이트를 넘습니다. " if not _blank(v) else
                "전자신고 07 레코드의 매입가액(11101) 행에는 산 곳(매도인)의 성명이나 상호가 있어야 합니다(규격서 p59~60). ")
    return [_q("F08", aid, head + "신고인 파일의 자산 항목 취득상대방에 한글 완성형 글자로 60바이트(한글 30자) 안에서 적어 주세요.")]


def _f07_f08(f, facts, result, efile_dir=None):
    """계산이 끝난 결과(상태 완료)가 있을 때만 묻는다. 07 행이 어느 지출에서 생기는지는 취득가액 방법이 정하기 때문이다.
    필수 구분코드는 efile_dir 의 코드표에서 읽는다(신고값을 만들 때 return_values.build 에 주는 폴더와 같아야 한다)."""
    if not isinstance(result, dict) or result.get("상태") != "완료" or not (result.get("계산") or {}).get("자산"):
        return []
    from yangdo import return_values      # return_values 가 이 모듈을 읽으므로 늦게 읽는다
    assets = {a.get("id"): a for a in (facts or {}).get("자산") or []}
    lots = f.get("자산") or {}
    codes = None
    out7, out8 = [], []
    for row in result["계산"]["자산"]:
        aid, a = row.get("id"), assets.get(row.get("id"))
        if a is None:
            continue
        lines = return_values.expense_lines(a, row["계산"])
        if codes is None and any(ln.item is not None for ln in lines):
            codes = return_values.load_codes(efile_dir)["필요경비구분"]
        out7 += _f07(aid, lines, codes)
        out8 += _f08(aid, lines, lots.get(aid))
    return out7 + out8


def questions(filer, facts, result=None, bjd=None, efile_dir=None):
    """빠진 신고인 정보를 문항 목록으로. [{"문항": "F01", "자산": None, "내용": "..."}]. 비면 신고값을 만들 수 있다.

    filer 는 load 의 결과, facts 는 사실관계(자산 목록을 본다). result 는 engine.calculate 의 결과이고, 상태가 완료일 때만
    F07·F08 을 묻는다(None 이거나 끝나지 않았으면 두 문항은 건너뛴다. 분납 가능 여부는 규칙세트 값이라 신고값 생성이 판정한다).
    bjd 는 시험용 주입 인자이고 없으면 yangdo.bjd.load() 를 처음 쓸 때 읽는다.
    efile_dir 는 법정동코드 표와 코드표를 읽는 폴더다(없으면 기본 efile 폴더). return_values.build 에 다른 폴더를 줄 때 같은 것을 준다.
    내용에는 인적사항 값을 쓰지 않고 항목 이름만 적는다.

    타인이 아닌 양수인(사실관계 매수인관계)은 관계코드를 F02 로, 경매로 취득하거나 양도한 자산은 등기원인을 F04 로 묻는다.
    번지 0 은 특수지 9 일 때만 받아 F01·F04 로 되묻는다(00 처럼 0 으로만 된 번지와 앞에 0 을 붙인 번지도 되묻는다).
    적어 둔 법정동코드가 시도나 시군구 단계 코드면 F01·F04 로 되묻는다.
    F07 은 필수 구분코드 필요경비에 지급금액이 있는데 사실관계의 사업자번호(10자리, 검증번호)가 없거나 틀린 자산, 지급일이
    없거나 YYYY-MM-DD 로 읽을 수 없는 자산을, F08 은
    매입가액 행이 생기는데 자산[id].취득상대방이 없거나 쓸 수 없는 자산을 묻는다. 두 문항이 보는 07 행의 규칙은
    return_values.expense_lines 가 정한다.
    계산이 끝난 결과가 전액 비과세로 판정한 자산은 신고서에 넣지 않으므로 그 자산의 양수인(F02)과 지번(F04)을 묻지 않는다.
    신고인 파일에 그 자산의 양수인이나 지번이 있어도 알리지 않는다. 결과가 없으면 어느 자산이 빠질지 몰라 모든 자산을 묻는다.
    공개본(edition.PUBLIC)은 F06(홈택스 사용자 ID)을 묻지 않는다. 그 값은 전자신고 파일에만 쓰고 서식에는 칸이 없다.
    """
    late = _Late(bjd, efile_dir)
    on = ((filer.get("신고") or {}).get("작성일")) or None
    skip = _left_out(result)
    assets = {a.get("id"): a for a in (facts or {}).get("자산") or [] if a.get("id") not in skip}
    return (_f01(filer.get("신고인"), late, on) + _f02(filer, assets, skip) + _f03(filer)
            + _f04(filer, facts, late, on, skip) + _f05(filer) + ([] if edition.PUBLIC else _f06(filer))
            + _f07_f08(filer, facts, result, efile_dir))


def _left_out(result):
    """계산이 끝난 결과가 전액 비과세로 판정한 자산 id. 결과가 없거나 끝나지 않았으면 빈 목록."""
    if not isinstance(result, dict) or result.get("상태") != "완료":
        return []
    from yangdo import return_values      # return_values 가 이 모듈을 읽으므로 늦게 읽는다
    return return_values.exempt_ids(result)
