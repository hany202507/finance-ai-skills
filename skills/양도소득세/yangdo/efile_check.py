# -*- coding: utf-8 -*-
"""양도소득세 전자신고 변환파일(서식코드 C116300) 독립 검증기.

생성기(yangdo/efile.py), 신고값 생성기(yangdo/return_values.py), 엔진 계산(yangdo/calc.py)을 부르지 않는다.
레이아웃 표(efile/layout_c116300.json)에서는 칸 위치만, 코드표(efile/codes_c116300.json)와 법정동코드 표에서는
값 목록만 읽고 파일 바이트를 처음부터 다시 읽는다. 레코드 길이와 서식코드는 이 파일에도 따로 적어 두고 레이아웃이
이 표와 다르면 검사 전에 실패한다. 레이아웃이 틀려 생성기와 함께 틀리는 것을 막으려는 것이다.

문장 끝 괄호가 근거다. (pNN) 은 「양도소득세 전자신고 파일설명서 V5.17」 원문 쪽(쪽별 추출본 120쪽 기준),
(브리프) 는 계획서 T11 브리프가 정한 검사로 원문에 그 문장이 없는 것, (서식 ⑱) 은 신고서 작성요령(p19 「언급이
없는 한 신고서-첨부서류 작성요령에 준함」), (결정) 은 global.md 「실행 중 정한 것」과 컨트롤러 결정, (추론) 은
원문을 근거로 한 추론이다.

    python -m yangdo.efile_check <파일> [--신고값 신고값.json]

통과면 「검증 통과 (n줄)」 과 종료코드 0, 실패면 문장마다 한 줄과 종료코드 1. 주민등록번호 검증번호가 옛 규칙과
다른 것은 실패가 아니라 경고다(2020-10 이후 발급·변경 번호는 옛 규칙이 맞지 않을 수 있다). 경고는 표준 오류에
「경고: 」 로 쓰고 종료코드를 바꾸지 않는다. 출력은 UTF-8 이다.

신고값(--신고값, check_file 의 rv)을 주면 파일을 신고값과 대사한다. 01·02·04 는 신고 구분과 인적사항 칸을, 03·05·07 은
자료구분·서식코드와 공란을 뺀 모든 칸을 신고값 전자신고 절(세율별, 계산명세, 필요경비명세)의 같은 이름 값과 견준다.
05 의 날짜·면적·법정동코드·지번·등기목적·등기원인·자산종류·과세구분·세율구분과 07 의 구분코드·상호·사업자등록번호·
지급일자·증빙종류코드·지급금액이 여기에 든다. 파일에 값을 옮겨 적는 규칙(왼쪽 맞춤, 0 채움, 고정 소수)은 이 파일에 따로 적었다.

문장에는 칸 이름, 코드, 금액, 날짜만 쓴다. 성명·주민등록번호·주소·전화 같은 인적사항 값은 쓰지 않는다.
신고값 대사에서 금액이 아닌 칸이 다르면 값 대신 칸 이름과 신고값 경로만 쓴다(지번과 07 상호는 인적 성격의 값이다).
"""
import argparse
import functools
import json
import os
import re
import sys
from datetime import date
from decimal import ROUND_DOWN, Decimal, InvalidOperation
from fractions import Fraction

from yangdo import SKILL_DIR
from yangdo import bjd as _bjd

EFILE_DIR = os.path.join(SKILL_DIR, "efile")
LAYOUT_FILE = "layout_c116300.json"
CODES_FILE = "codes_c116300.json"

# 검증기가 따로 갖는 표(p17·p25: 01 은 필드 표 누적 350, FIXUPS). 레이아웃이 이 표와 다르면 검사하지 않는다
LENGTHS = {"01": 350, "02": 400, "03": 450, "04": 150, "05": 700, "07": 200}
FORMS = {"01": "C116300", "02": "C116300", "03": "C116300", "04": "C116300", "05": "C116400", "07": "C116600"}
ORDER = ("01", "02", "03", "04", "05", "07")          # p104 수록순서
REQUIRED = ("01", "02", "03", "04", "05")
SINGLE = ("01", "02")                                 # One Record
# 규격서에 있지만 국내 부동산 예정·확정 정기신고에 쓰지 않는 레코드(06 주식, 08~13 계약서, 14~30)
UNHANDLED = frozenset(["06"] + ["%02d" % i for i in range(8, 31)])
FILE_NAME = re.compile(r"^(\d{8})C116300\.(0[13])$")  # p20, global.md 파일명
CRLF = b"\r\n"

# HEADER 23 세무프로그램코드(p27~28, 41개, 기타 9000)
PROGRAM_CODES = frozenset(
    ["%04d" % n for n in list(range(1001, 1011)) + [1012, 1013, 1014, 1016, 1017, 1018, 1019, 1029, 1030]
     + list(range(1031, 1038)) + list(range(1039, 1053))] + ["9000"])

# 세율별내역 03 국내분 세율구분(p32~37 자진납부서 세율구분 1-xx)
RATES_03 = frozenset("10 15 20 40 23 39 46 30 11 35 36 31 37 38 71 73 21 51 53 52 54 55 57 56 58 "
                     "47 84 82 48 85 83 49 88 86 50 89 87 61 62 70 63 80 81 95 92 94".split())
# 05 계산명세 국내 세율구분: 03 표에서 주식·파생상품·국외전출(06 레코드 몫)을 빼고 p47 의 '09 특례 코드를 더한다
RATES_05 = (RATES_03 - frozenset("61 62 70 63 80 81 94".split())) | frozenset("25 26 27 28".split())

# 03 금액 칸 번호. 합계 행 = 세율구분 행 합(p37~43). 36 전자신고세액공제는 합산 문장이 없고 상한만 있다(p43)
SUM_03 = (5, 6, 7, 8, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 22, 24, 25, 26, 27, 34, 35, 37)
TOTAL_ONLY_03 = (20, 21, 28, 29)                       # 합계 행 이외 0(p42~43)
# 주민세 금액 칸 0(global.md 지방소득세 결정). 31 주민세_세율은 아래 FIXED_TOTAL_ONLY 로 본다
LOCAL_03 = (30, 32, 33)
# 점검내용이 칸 길이와 같은 숫자열인 N 칸은 그 값이 고정값이다. 다만 이 표의 칸은 합계 행(03 의 Z/00)에만 고정값을
# 쓰고 나머지 행(세율구분 행, 소계 1/00, Z/98)은 0 이다. 03-31 주민세_세율: p43 「10% (01000) 합계(국내외분:Z,
# 세율구분:00) 이외 항목에는 '0'으로 채움 →사용안함」, global.md 03-31 결정(홈택스 형식검증으로 확인할 항목)
FIXED_TOTAL_ONLY = {("03", 31): "p43"}
LOCAL_ROW_ZERO_03 = (8, 10, 11, 12, 14, 15, 16, 17, 18, 19, 21, 35)   # 지방소득세 행(Z/98) 금액 0(p32)
# 05-41 장기보유특별공제를 적을 수 있는 세율구분. p50 41번은 「세율구분(10)[2 년이상]인 경우만 가능」이라 적지만, 같은 항목의
# p51 은 적용하지 않는 자산 목록에서 비사업용토지를 「2016 년 양도분부터는 가능」이라 하고, p33 세율 표의 1-11 이
# 「2 년이상 보유한 비사업용 토지(2016.1.1 이후 양도분부터 적용)」다. 그래서 11 도 받는다. 엔진은 지금 11 을 내지 않는다
LTD_RATES = ("10", "11")
E_FILING_CREDIT_CAP = 20000          # 03-36 세율별·소계·합계 최대 20,000원(p43)
PENSION_CREDIT_CAP = 10000000        # 03-37 소계·합계 최대 1,000만원(p43)

# 신고값 대사(14). 신고값 전자신고 절의 행 키는 레이아웃 필드 name 그대로다(global.md 「신고값 전자신고 키」).
# 07 행만 세 칸의 키가 다르다(필요경비신고자료일련번호 → 일련번호, 구분코드 → 5자리 전자코드, 사업자등록번호 → 사업자번호).
# 생성기(efile.py)에도 같은 뜻의 표가 있지만 가져오지 않고 여기 따로 적는다. 생성기의 표가 틀리면 함께 틀리기 때문이다
RV_KEYS_07 = {"필요경비신고자료일련번호": "일련번호", "구분코드": "전자코드", "사업자등록번호": "사업자번호"}
# 문자 칸이지만 앞을 0 으로 채운 6자리로 쓰는 일련번호 칸(p23 9번). 신고값에는 정수로 있어 수로 견준다.
# 05-10·11 번지·호는 레이아웃 분류가 SEQ 여도 일련번호가 아니라 글자 그대로 견준다
SERIAL_NAMES = {"05": ("일련번호",), "07": ("필요경비신고자료일련번호", "상세일련번호")}

_NUM = re.compile(rb"-?\d+")
_RRN_W = (2, 3, 4, 5, 6, 7, 8, 9, 2, 3, 4, 5)
_BIZ_W = (1, 3, 7, 1, 3, 7, 1, 3, 5)
_MISSING = object()


# ---------------------------------------------------------------- 낱개 판정

def _ymd(s):
    if not (isinstance(s, str) and re.fullmatch(r"\d{8}", s)):
        return None
    try:
        return date(int(s[:4]), int(s[4:6]), int(s[6:]))
    except ValueError:
        return None


def _ym_ok(s):
    return bool(isinstance(s, str) and re.fullmatch(r"\d{4}(0[1-9]|1[0-2])", s))


KSX_BYTES = "KS X 1001 완성형이나 ASCII 가 아닌 바이트가 있음(p15)"
KSX_EMPTY = "KS X 1001 완성형에 없는 글자(표의 빈 자리)가 있음(p15)"


def _ksx_problem(b):
    """ASCII(0x20~0x7E)와 KS X 1001 완성형 2바이트(한글 0xB0~0xC8, 기호 0xA1~0xAC 행, 둘째 0xA1~0xFE)만이면 None.

    생성기와 신고인 검사는 yangdo/efile_text.py 의 함수를 함께 쓴다. 검증기는 그 함수를 가져오지 않고 같은 규칙을 여기 따로
    적는다. 같은 함수를 쓰면 그 함수가 틀렸을 때 검증기도 같이 틀린다.

    바이트 범위가 맞아도 0xA2E8 처럼 표의 빈 자리는 CP949 로 읽히지 않으므로 따로 실패로 센다.
    """
    i, n = 0, len(b)
    while i < n:
        x = b[i]
        if 0x20 <= x <= 0x7E:
            i += 1
        elif (0xB0 <= x <= 0xC8 or 0xA1 <= x <= 0xAC) and i + 1 < n and 0xA1 <= b[i + 1] <= 0xFE:
            i += 2
        else:
            return KSX_BYTES
    try:
        b.decode("cp949")
    except UnicodeDecodeError:
        return KSX_EMPTY
    return None


def _rrn_shape(s):
    """13자리 숫자의 앞 6자리가 있는 생년월일이고 성별 자리가 1~8 인지(1·2·5·6 은 1900년대, 3·4·7·8 은 2000년대, p21)."""
    if s[6] not in "12345678":
        return False
    year = (1900 if s[6] in "1256" else 2000) + int(s[:2])
    return _ymd("%04d%s" % (year, s[2:6])) is not None


def _rrn_digit_ok(s):
    return (11 - sum(int(a) * b for a, b in zip(s, _RRN_W)) % 11) % 10 == int(s[12])


def _biz_ok(s):
    t = sum(int(a) * b for a, b in zip(s, _BIZ_W)) + int(s[8]) * 5 // 10
    return (10 - t % 10) % 10 == int(s[9])


def _code_list(check):
    """점검내용이 값 목록(「01,03」, 「0~9」, 「00, 01, 02~06, 07」)이면 집합, 아니면 None."""
    toks = [t.strip() for t in (check or "").split(",") if t.strip()]
    if not toks:
        return None
    out = set()
    for t in toks:
        m = re.fullmatch(r"(\d+)~(\d+)", t)
        if m:
            a, b = m.groups()
            out |= {str(i).zfill(len(a)) for i in range(int(a), int(b) + 1)}
        elif re.fullmatch(r"[0-9A-Z]{1,7}", t):
            out.add(t)
        else:
            return None
    return out


def _as_int(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float) and v.is_integer():
        return int(v)
    if isinstance(v, str) and re.fullmatch(r"-?\d+", v.strip()):
        return int(v.strip())
    return None


def _scaled(v, dec):
    """소수 dec 자리 고정 소수 칸의 값을 파일에 적는 정수로(p19~23: 소수점 없이 소수 자리만큼 늘려 쓰고 그 아래는 버린다).

    수로 읽을 수 없으면 None. 소수 자리가 없는 칸(dec 0)은 정수만 받는다.
    """
    if dec == 0:
        return _as_int(v)
    if isinstance(v, bool) or v is None:
        return None
    try:
        d = Decimal(str(v).strip())
        if not d.is_finite():
            return None
        return int((d * (10 ** dec)).to_integral_value(rounding=ROUND_DOWN))
    except (InvalidOperation, ValueError, OverflowError):
        return None


def _serial_of(x):
    """앞을 0 으로 채운 6자리 일련번호 바이트 → 정수. 꼴이 아니면 None."""
    return int(x) if re.fullmatch(rb"\d{6}", x) else None


def _is_total(r):
    """03 합계 행(국내외분 Z, 세율구분 00)인지."""
    return r.kind == "03" and (r.t(3), r.t(4)) == ("Z", "00")


def _part(items, prefix):
    """07 (구분코드, 지급금액) 목록에서 구분코드가 prefix 로 시작하는 금액 합."""
    return sum(amt for code, amt in items if code.startswith(prefix))


@functools.lru_cache(maxsize=4)
def _load_bjd(efile_dir):
    return _bjd.load(efile_dir=efile_dir)


class _Rec:
    """길이가 맞는 레코드 한 줄. 칸은 레이아웃 번호(원문 번호)로 부른다."""

    def __init__(self, line, kind, raw, fields):
        self.line, self.kind, self.raw, self.f = line, kind, raw, fields

    def b(self, no):
        f = self.f[no]
        return self.raw[f["start"] - 1:f["end"]]

    def t(self, no):
        return self.b(no).decode("cp949", "replace").rstrip(" ")

    def n(self, no):
        x = self.b(no)
        return int(x) if _NUM.fullmatch(x) else None

    def where(self, no):
        return "%d줄(%s) %d %s" % (self.line, self.kind, no, self.f[no]["name"])


# ---------------------------------------------------------------- 검사

class _Checker:
    def __init__(self, efile_dir=None):
        self.dir = efile_dir or EFILE_DIR
        self.fails, self.warns = [], []
        self.nlines = 0
        self.broken = False
        with open(os.path.join(self.dir, LAYOUT_FILE), encoding="utf-8") as f:
            self.layout = json.load(f)
        with open(os.path.join(self.dir, CODES_FILE), encoding="utf-8") as f:
            self.codes = json.load(f)
        self.F = {}
        self._self_check()

    def fail(self, msg):
        self.fails.append(msg)

    def warn(self, msg):
        self.warns.append(msg)

    # 레이아웃이 검증기 표와 같은지 먼저 본다
    def _self_check(self):
        recs = self.layout.get("레코드") or {}
        for kind, n in LENGTHS.items():
            r = recs.get(kind)
            if not r or not r.get("필드"):
                self.fail("레이아웃에 레코드 %s 가 없음" % kind)
                continue
            fields = r["필드"]
            total = sum(f["len"] for f in fields)
            if total != n or r.get("길이") != n:
                self.fail("레이아웃 레코드 %s 길이 %s(필드 합 %d)가 검증기 표 %d 와 다름" % (kind, r.get("길이"), total, n))
                continue
            pos = 1
            for i, f in enumerate(fields, 1):
                if f["no"] != i or f["start"] != pos or f["end"] != pos + f["len"] - 1:
                    self.fail("레이아웃 레코드 %s %d %s 의 번호나 위치가 이어지지 않음" % (kind, f["no"], f["name"]))
                    break
                pos += f["len"]
            if fields[0]["check"] != kind or fields[1]["check"] != FORMS[kind]:
                self.fail("레이아웃 레코드 %s 의 자료구분·서식코드가 검증기 표(%s %s)와 다름" % (kind, kind, FORMS[kind]))
            self.F[kind] = {f["no"]: f for f in fields}

    def run(self, path, rv=None):
        name = os.path.basename(path)
        m = FILE_NAME.match(name)
        fdate = fext = None
        if not m:
            self.fail("파일명 %s: 「YYYYMMDDC116300.01」 또는 「.03」 꼴이 아님(p20)" % name)
        elif _ymd(m.group(1)) is None:
            self.fail("파일명 %s: 앞 8자리가 있는 날짜가 아님" % name)
        else:
            fdate, fext = m.group(1), m.group(2)
        try:
            with open(path, "rb") as f:
                data = f.read()
        except OSError as e:
            self.fail("파일을 읽을 수 없음: %s" % (e.strerror or e))
            return
        lines = self._lines(data)
        self.nlines = len(lines)
        recs, kinds = self._records(lines)
        self._order(kinds)
        for r in recs:
            self._fields(r)
        if self.broken:
            return          # 칸 위치가 어긋난 줄이 있으면 레코드 사이 대사는 하지 않는다
        by = {k: [r for r in recs if r.kind == k] for k in ORDER}
        h = by["01"][0] if len(by["01"]) == 1 else None
        b = by["02"][0] if len(by["02"]) == 1 else None
        foreign = b is not None and b.t(14) == "N"
        if h is not None:
            self._header(h, name, fdate, fext, by["05"], foreign)
        if b is not None:
            self._basic(b)
        self._rates(by["03"], by["05"])
        self._buyers(by["04"], len(by["05"]), rv)
        self._assets(by["05"], by["07"])
        self._expenses(by["07"], by["05"])
        if rv is not None:
            self._reconcile(rv, h, b, by)

    # 2. 줄 끝
    def _lines(self, data):
        if not data:
            self.fail("파일: 비어 있음")
            return []
        if re.search(rb"\r(?!\n)|(?<!\r)\n", data):
            self.fail("파일: CRLF 가 아닌 줄바꿈(홀로 된 CR 또는 LF)이 있음(p15)")
        if not data.endswith(CRLF):
            self.fail("파일: 마지막 줄 뒤에 CRLF 가 없음(p15 「각 레코드마다 CR/LF」)")
        lines = re.split(rb"\r\n|\r|\n", data)
        if lines and lines[-1] == b"":
            lines.pop()
        return lines

    # 4. 자료구분, 길이
    def _records(self, lines):
        recs, kinds = [], []
        for i, x in enumerate(lines, 1):
            if not x:
                self.fail("%d줄: 빈 줄" % i)
                self.broken = True
                continue
            kind = x[:2].decode("ascii", "replace")
            if kind not in LENGTHS:
                self.broken = True
                if kind in UNHANDLED:
                    self.fail("%d줄(%s): 이 검증기가 다루지 않는 레코드(국내 부동산 예정·확정 정기신고에 쓰지 않음)" % (i, kind))
                else:
                    self.fail("%d줄: 자료구분 「%s」 은 알 수 없음" % (i, kind))
                continue
            kinds.append((i, kind))
            if len(x) != LENGTHS[kind]:
                self.broken = True
                self.fail("%d줄(%s): 길이 %d 바이트, 규격 %d 바이트(p17~18)" % (i, kind, len(x), LENGTHS[kind]))
                problem = _ksx_problem(x)
                if problem:
                    self.fail("%d줄(%s): %s" % (i, kind, problem))
                continue
            recs.append(_Rec(i, kind, x, self.F[kind]))
        return recs, kinds

    # 5. 순서
    def _order(self, kinds):
        seq = [k for _, k in kinds]
        if kinds and kinds[0][1] != "01":
            self.fail("%d줄(%s): 첫 줄은 HEADER(01)여야 함(p104)" % kinds[0])
        for k in SINGLE:
            c = seq.count(k)
            if c > 1:
                self.fail("자료구분 %s 레코드가 %d줄 있음(한 줄이어야 함, p104)" % (k, c))
        for k in REQUIRED:
            if k not in seq:
                self.fail("자료구분 %s 레코드가 없음(p104)" % k)
        hi = -1
        for i, k in kinds:
            idx = ORDER.index(k)
            if idx < hi:
                self.fail("%d줄(%s): 순서가 틀림. %s 뒤에 올 수 없음(01 → 02 → 03 → 04 → 05 → 07, p104)" % (i, k, ORDER[hi]))
            hi = max(hi, idx)

    # 3·6. 칸마다: 바이트, Not Null, 숫자, 날짜, 고정값·값 목록
    def _fields(self, r):
        for no, f in r.f.items():
            x = r.b(no)
            chk = f.get("check") or ""
            if f["type"] == "N":
                if not _NUM.fullmatch(x):
                    self.fail(r.where(no) + ": 숫자가 아님")
                elif x.startswith(b"-") and "양의" in chk:
                    self.fail(r.where(no) + ": 음수가 올 수 없음(양의실수형식점검)")
                elif re.fullmatch(r"\d+", chk) and len(chk) == f["len"]:
                    basis = FIXED_TOTAL_ONLY.get((r.kind, no))
                    if basis and not _is_total(r):
                        if x.strip(b"0"):
                            self.fail(r.where(no) + ": 합계 행(Z/00) 이외는 0(%s 「합계 이외 항목에는 '0'으로 채움」)" % basis)
                    elif x.decode("ascii") != chk:
                        self.fail(r.where(no) + ": 고정값 %s 와 다름(레이아웃 점검값%s)"
                                  % (chk, ", 합계 행, %s" % basis if basis else ""))
                continue
            problem = _ksx_problem(x)
            if problem:
                self.fail(r.where(no) + ": " + problem)
                continue
            v = x.decode("cp949").rstrip(" ")
            if f["class"] == "SPACE":
                if v:
                    self.fail(r.where(no) + ": 공란이어야 함")
                continue
            if not v.strip():
                if f["notnull"]:
                    self.fail(r.where(no) + ": Not Null 칸이 비어 있음(p19)")
                continue
            allowed = f.get("허용") or _code_list(chk)
            if allowed is not None and v not in allowed:
                self.fail(r.where(no) + ": 「%s」 는 허용값(%s)이 아님" % (v, ",".join(sorted(allowed))))
            if f["class"] == "DATE" or "일자형식" in chk or "년월형식" in chk:
                if f["len"] == 6 and not _ym_ok(v):
                    self.fail(r.where(no) + ": 년월(YYYYMM)이 아님")
                elif f["len"] != 6 and _ymd(v) is None:
                    self.fail(r.where(no) + ": 날짜(YYYYMMDD)가 아님(p23)")
            if "숫자" in chk and not f["name"].endswith("일련번호") and not re.fullmatch(r"\d+", v):
                self.fail(r.where(no) + ": 숫자가 아님")

    def _rrn(self, r, no, foreign):
        x = r.b(no)
        if not x.strip():
            return
        if not re.fullmatch(rb"\d{13}", x):
            self.fail(r.where(no) + ": 하이픈 없는 숫자 13자리가 아님(p20)")
            return
        s = x.decode("ascii")
        if not _rrn_shape(s):
            self.fail(r.where(no) + ": 생년월일(앞 6자리)이나 성별 자리(1~8)가 맞지 않음(p21)")
        elif not foreign and not _rrn_digit_ok(s):
            self.warn(r.where(no) + ": 검증번호가 옛 규칙과 다름. 2020-10 이후 발급·변경된 번호가 아니면 다시 확인")

    def _bjd(self, r, no):
        v = r.t(no)
        if not v.strip():
            return
        if not re.fullmatch(r"\d{10}", v):
            self.fail(r.where(no) + ": 법정동코드 숫자 10자리가 아님(p24)")
        elif v[5:8] == "000":
            self.fail(r.where(no) + ": 읍면동 단계 코드가 아님(시도·시군구 단계 코드, 결정)")
        elif not _load_bjd(self.dir).exists(v):
            self.fail(r.where(no) + ": 법정동코드 표에 없음(없거나 폐지된 코드, 결정)")

    def _lot(self, r, sp_no, lot_no, ho_no):
        """번지·호는 ASCII 숫자, 번지 0 은 특수지코드 9(무번지)일 때만(p30, p48)."""
        for no in (lot_no, ho_no):
            v = r.t(no)
            if v.strip() and "숫자" not in (r.f[no].get("check") or "") and not re.fullmatch(r"\d+", v):
                self.fail(r.where(no) + ": 숫자가 아님(ASCII 숫자만)")
        lot = r.t(lot_no)
        if re.fullmatch(r"0+", lot) and r.t(sp_no) != "9":
            self.fail(r.where(lot_no) + ": 번지 0 은 특수지코드 9(무번지)일 때만 쓴다(p30·p48)")

    def _serial(self, r, no, i):
        x = r.b(no)
        if not re.fullmatch(rb"\d{6}", x):
            self.fail(r.where(no) + ": 앞을 0 으로 채운 6자리 숫자가 아님(p23)")
            return None
        if int(x) != i:
            self.fail(r.where(no) + ": %d 이어야 함(1 부터 차례로, p23)" % i)
        return int(x)

    # 01 HEADER
    def _header(self, h, name, fdate, fext, assets, foreign):
        self._rrn(h, 3, foreign)
        kind, typ, form = h.t(6), h.t(7), h.t(10)
        if form not in ("D01", "D03"):
            self.fail(h.where(10) + ": D01(확정신고서)·D03(예정신고서)이 아님(p26)")
        elif kind in ("01", "03") and {"01": "D01", "03": "D03"}[kind] != form:
            self.fail(h.where(10) + ": 6 신고구분코드 %s 와 맞지 않음(확정 01 은 D01, 예정 03 은 D03, p26 코드 뜻에서 추론)" % kind)
        if typ and ((typ in "1234" and kind == "01") or (typ in "56" and kind == "03")):
            self.fail(h.where(7) + ": 6 신고구분코드 %s 와 맞지 않음(예정 1~4, 확정 5·6, p26 코드 뜻에서 추론)" % kind)
        period, sold, wrote = h.t(8), h.t(25), h.t(24)
        if _ym_ok(period) and not period.endswith("01"):
            self.fail(h.where(8) + ": 양도연도 + 01 이 아님(p26)")
        elif _ym_ok(period) and _ymd(sold) and period != sold[:4] + "01":
            self.fail(h.where(8) + ": 25 양도일자의 연도 + 01 이 아님(p26)")
        if fdate and _ymd(wrote) and wrote != fdate:
            self.fail("파일명 %s: 앞 8자리가 1줄(01) 24 작성일자 %s 와 다름(결정)" % (name, wrote))
        if fext and h.t(9) in ("01", "03") and h.t(9) != fext:
            self.fail("파일명 %s: 확장자가 1줄(01) 9 신고구분상세코드 %s 와 다름(p20)" % (name, h.t(9)))
        if h.t(23) and h.t(23) not in PROGRAM_CODES:
            self.fail(h.where(23) + ": 「%s」 는 세무프로그램코드 목록(p27~28)에 없음" % h.t(23))
        bank, acct = h.t(15), h.t(16)
        if bool(bank.strip()) != bool(acct.strip()):
            self.fail(h.where(16) + ": 15 은행코드와 함께 쓰거나 함께 비운다(추론)")
        if bank.strip() and not (self.codes["은행"].get(bank) or {}).get("환급계좌"):
            self.fail(h.where(15) + ": 「%s」 는 환급계좌 은행코드(p113)가 아님" % bank)
        if len(acct) > 16:
            self.fail(h.where(16) + ": 16자리를 넘음(p26)")
        if any(h.t(n).strip() for n in (18, 19, 20, 21, 26)) and not (h.t(22).strip() or h.t(27).strip()):
            self.fail(h.where(22) + ": 세무대리인 칸을 쓰면 22 세무대리인관리번호나 27 세무대리인생년월일 중 하나는 적는다(p27~28)")
        self._rrn(h, 18, False)
        biz = h.b(21)
        if biz.strip() and not (re.fullmatch(rb"\d{10}", biz) and _biz_ok(biz.decode("ascii"))):
            self.fail(h.where(21) + ": 검증번호가 맞는 사업자등록번호 숫자 10자리가 아님")
        dates = [a.t(17) for a in assets if _ymd(a.t(17))]
        if dates and _ymd(sold) and sold != max(dates):
            self.fail(h.where(25) + ": 05 양도일자 가운데 가장 늦은 날 %s 와 다름(p28)" % max(dates))
        for a in assets:
            d = a.t(17)
            if not _ymd(d):
                continue
            if _ym_ok(period) and d[:4] != period[:4]:
                self.fail(a.where(17) + ": 1줄(01) 8 과세기간의 연도와 다름(추론)")
            if _ymd(wrote) and d > wrote:
                self.fail(a.where(17) + ": 1줄(01) 24 작성일자 %s 보다 늦음(추론)" % wrote)

    # 02 기본사항
    def _basic(self, b):
        self._bjd(b, 3)
        self._lot(b, 4, 5, 6)
        tel = b.t(12)
        if tel.strip() and not re.fullmatch(r"\d+", tel):
            self.fail(b.where(12) + ": 숫자만 쓴다(하이픈·괄호 없이, p22)")
        nat, res = b.t(14), b.t(15)
        if nat not in ("Y", "N"):
            self.fail(b.where(14) + ": Y(내국인)·N(외국인)이 아님(p30)")
        if res not in ("Y", "N"):
            self.fail(b.where(15) + ": Y(비거주자)·N(거주자)가 아님(p30)")
        countries = self.codes["국가"]
        for no in (16, 26):
            x = b.b(no)
            if not (re.fullmatch(rb"[A-Z]{2} ", x) and x[:2].decode("ascii") in countries):
                self.fail(b.where(no) + ": 국가코드 표(p114~119)의 영문 대문자 2자리 + 공백 1자리가 아님(p30)")
        rc, nc = b.t(16), b.t(26)
        if res == "N" and rc != "KR":
            self.fail(b.where(16) + ": 거주자(15 = N)이면 KR(p30)")
        if nat == "Y" and nc != "KR":
            self.fail(b.where(26) + ": 내국인(14 = Y)이면 KR(p30)")
        if nat == "N" and nc == "KR":
            self.fail(b.where(26) + ": 외국인(14 = N)이면 KR 이 아닌 코드(p30)")
        label = (countries.get(rc) or {}).get("이름")
        if label and b.t(17) != label:
            self.fail(b.where(17) + ": 16 거주지국코드의 이름 「%s」 와 다름(p30)" % label)

    # 03 세율별내역 (10·11)
    def _rates(self, rows, assets):
        if not rows:
            return
        keys = []
        for r in rows:
            dom, code = r.t(3), r.t(4)
            if dom == "9":
                self.fail(r.where(3) + ": 국외분(9)은 이 검증기가 다루지 않음")
                continue
            valid = {"1": RATES_03 | {"00"}, "Z": {"00", "98"}}.get(dom)
            if valid is not None and code not in valid:
                self.fail(r.where(4) + ": 「%s」 는 국내외분 %s 의 세율구분이 아님(p32~37)" % (code, dom))
            keys.append((r, dom, code))
        seen, prev = {}, None
        for r, dom, code in keys:
            k = (dom, code)
            if k in seen:
                self.fail("%d줄(03): 국내외분 %s 세율구분 %s 행이 %d줄에도 있음" % (r.line, dom, code, seen[k]))
            seen.setdefault(k, r.line)
            if prev is not None and k < prev:
                self.fail("%d줄(03): 정렬 순서(국내외분·세율구분)가 틀림(p104)" % r.line)
            prev = k if prev is None else max(prev, k)
        total = [r for r, d, c in keys if (d, c) == ("Z", "00")]
        sub = [r for r, d, c in keys if (d, c) == ("1", "00")]
        rate_rows = [(r, c) for r, d, c in keys if d == "1" and c != "00"]
        if not total:
            self.fail("03 합계 행(국내외분 Z, 세율구분 00)이 없음(p32)")
        for r, d, c in keys:
            v = {no: r.n(no) for no, f in r.f.items() if f["type"] == "N"}
            if (d, c) == ("Z", "98"):
                for no in LOCAL_ROW_ZERO_03:
                    if v[no]:
                        self.fail(r.where(no) + ": 지방소득세 행(Z/98) 금액은 2020-01-01 이후 0(p32)")
                continue
            for no in LOCAL_03:
                if v[no]:
                    self.fail(r.where(no) + ": 주민세 금액 칸은 0(국세 파일의 지방소득세 란, 결정)")
            if (d, c) != ("Z", "00"):
                for no in TOTAL_ONLY_03:
                    if v[no]:
                        self.fail(r.where(no) + ": 합계 행(Z/00)에만 쓰고 다른 행은 0(p42~43)")
            if c == "00":
                for no in (9, 23):
                    if v[no]:
                        self.fail(r.where(no) + ": 합계·소계 행(세율구분 00)은 00000(p37·p42)")
            if v[12]:
                self.fail(r.where(12) + ": 국내분에는 외국납부세액공제가 없음(p40)")
            if v[13]:
                self.fail(r.where(13) + ": 예정신고납부세액공제는 쓰지 않음(p41 「2011년 양도분은 입력불가」에서 추론)")
            if v[11] and v[34]:
                self.fail(r.where(34) + ": 11 감면세액과 함께 쓸 수 없음(p43)")
            if v[36] is not None and v[36] > E_FILING_CREDIT_CAP:
                self.fail(r.where(36) + ": %s 최대 %d원(p43)"
                          % ("세율별로" if c != "00" else "소계·합계는", E_FILING_CREDIT_CAP))
            if c == "00" and v[37] is not None and v[37] > PENSION_CREDIT_CAP:
                self.fail(r.where(37) + ": 소계·합계는 최대 %d원(p43)" % PENSION_CREDIT_CAP)
            if None not in (v[5], v[6], v[7], v[8], v[34]):
                want = v[5] + v[6] - v[34] - v[7]
                if v[8] != want:
                    self.fail(r.where(8) + ": 양도소득금액 + 기신고 - 소득감면대상 - 기본공제 %d 와 다름(p37)" % want)
            if None not in (v[15], v[16], v[35], v[17]) and v[17] != v[15] + v[16] + v[35]:
                self.fail(r.where(17) + ": 15 + 16 + 35 가산세 합 %d 와 다름(p41)" % (v[15] + v[16] + v[35]))
            terms = (v[10], v[11], v[12], v[13], v[14], v[36], v[37], v[17], v[18], v[19])
            if None not in terms:
                want = v[10] - v[11] - v[12] - v[13] - v[14] - v[36] - v[37] + v[17] - v[18]
                if v[19] != want:
                    self.fail(r.where(19) + ": 산출세액 - 감면·공제 + 가산세 - 기신고세액 %d 와 다름(서식 ⑱)" % want)
            if (d, c) == ("Z", "00") and None not in (v[19], v[20], v[21]) and v[21] != v[19] - v[20]:
                self.fail(r.where(21) + ": 자진납부할세액 - 분납할세액 %d 와 다름(서식 ⑳)" % (v[19] - v[20]))
        rate_recs = [r for r, _ in rate_rows]
        if len(total) == 1 and rate_recs:
            self._sum_rows(total[0], rate_recs, "세율구분 행")
        if len(sub) == 1 and rate_recs:
            self._sum_rows(sub[0], rate_recs, "국내 세율구분 행")
        if len(total) == 1:
            t = total[0].n(8)
            for r, _ in rate_rows:
                x = r.n(8)
                if t is None or x is None:
                    continue
                if (t > 0 and x < 0) or (t < 0 and x > 0) or (t == 0 and x != 0):
                    self.fail(r.where(8) + ": 합계 과세표준과 부호가 다름. 차익·차손이 함께 있으면 안분한다(p37)")
        # 11. 03 ↔ 05
        groups = {}
        for a in assets:
            if a.t(5) == "1":
                groups.setdefault(a.t(6), []).append(a)
        for r, c in rate_rows:
            g = groups.get(c)
            if not g:
                self.fail(r.where(4) + ": 05 에 세율구분 %s 인 자산이 없음" % c)
                continue
            for no3, no5, basis in ((5, 42, "p37"), (34, 60, "추론")):
                vals = [a.n(no5) for a in g]
                if r.n(no3) is None or None in vals:
                    continue
                if r.n(no3) != sum(vals):
                    self.fail(r.where(no3) + ": 05 세율구분 %s 자산의 %d %s 합 %d 과 다름(%s)"
                              % (c, no5, g[0].f[no5]["name"], sum(vals), basis))
        present = {c for _, c in rate_rows}
        for c, g in groups.items():
            if c not in present:
                self.fail("%d줄(05) 6 세율구분: 03 에 국내외분 1 세율구분 %s 행이 없음(p37)" % (g[0].line, c))

    def _sum_rows(self, target, parts, label):
        for no in SUM_03:
            vals = [p.n(no) for p in parts]
            t = target.n(no)
            if t is None or None in vals:
                continue
            if t != sum(vals):
                self.fail(target.where(no) + ": %s 합 %d 과 다름(p37~43)" % (label, sum(vals)))

    # 04 양수인내역 (13)
    def _buyers(self, rows, n_assets, rv):
        shares = []
        for i, r in enumerate(rows, 1):
            self._serial(r, 3, i)
            kind, nat = r.t(4), r.t(5)
            if kind == "1":
                self._rrn(r, 6, nat == "9")
            elif kind == "2":
                if nat != "1":
                    self.fail(r.where(5) + ": 법인(4 = 2)은 1(p44)")
                x = r.b(6)
                if re.fullmatch(rb"\d{10}   ", x):
                    if not _biz_ok(x[:10].decode("ascii")):
                        self.fail(r.where(6) + ": 사업자등록번호 검증번호가 맞지 않음")
                elif not re.fullmatch(rb"\d{13}", x):
                    self.fail(r.where(6) + ": 사업자등록번호 숫자 10자리나 법인등록번호 숫자 13자리가 아님(p44)")
            rel = r.t(11)
            if rel.strip():
                entry = self.codes["양수인관계목록"].get(rel)
                if entry is None:
                    self.fail(r.where(11) + ": 「%s」 는 코드표에 없음(양도자와의관계, p107~109)" % rel)
                elif entry.get("무효"):
                    self.fail(r.where(11) + ": 「%s」 는 무효 코드(%s, 결정)" % (rel, entry.get("이름", "")))
            num, den = r.n(9), r.n(10)
            if num is None or den is None:
                continue
            if den <= 0:
                self.fail(r.where(10) + ": 지분 분모가 0")
            elif num <= 0 or num > den:
                self.fail(r.where(9) + ": 지분이 0 초과 1 이하가 아님(추론)")
            else:
                shares.append((r, Fraction(num, den)))
        groups = None
        if isinstance(rv, dict) and isinstance(rv.get("양수인"), list):
            groups = []
            for i, x in enumerate(rv["양수인"]):
                if not isinstance(x, dict) or x.get("자산") is None or not str(x["자산"]).strip():
                    self.fail("신고값에 양수인[%d].자산 없음" % i)
                    groups = None
                elif groups is not None:
                    groups.append(str(x["자산"]))
            if groups is not None and len(groups) != len(rows):
                groups = None            # 줄 수가 다른 것은 신고값 대사가 따로 알린다
        if not shares or len(shares) != len(rows):
            return
        if groups:
            agg = {}
            for (r, s), g in zip(shares, groups):
                agg.setdefault(g, []).append((r, s))
            for g, items in agg.items():
                tot = sum(s for _, s in items)
                if tot != 1:
                    self.fail("%d줄(04) 9 양수인_지분(분자): 신고값 자산 %s 의 양수인 지분 합 %s 이 1 이 아님(브리프)" % (items[0][0].line, g, tot))
        else:
            tot = sum(s for _, s in shares)
            if n_assets and tot != n_assets:
                self.fail("04 양수인 지분 합 %s 이 05 자산 %d건과 맞지 않음. 자산마다 양수인 지분 합은 1 이다"
                          "(04 에는 자산을 잇는 칸이 없어 합으로 본다, 브리프)" % (tot, n_assets))

    # 05 계산명세 (7·8·11)
    def _assets(self, assets, exps):
        serials07 = {int(r.b(3)) for r in exps if re.fullmatch(rb"\d{6}", r.b(3))}
        kinds = {v["코드"] for v in self.codes["자산종류"].values()} - {"14", "17"}
        spots = set(self.codes["특수지"]) - {"Z"}
        purposes, causes = self.codes["등기목적목록"], self.codes["등기원인목록"]
        kr = self.codes["국가"]["KR"]["이름"]
        hold, live = self.codes["보유거주기간"]["보유"], self.codes["보유거주기간"]["거주"]
        for i, a in enumerate(assets, 1):
            self._serial(a, 3, i)
            if a.t(5) == "2":
                self.fail(a.where(5) + ": 국외 자산(2)은 이 검증기가 다루지 않음")
                continue
            code = a.t(6)
            if code and code not in RATES_05:
                self.fail(a.where(6) + ": 「%s」 는 국내 자산 세율구분이 아님(p32~37·p47)" % code)
            kind = a.t(7).strip()
            if kind and kind not in kinds:
                self.fail(a.where(7) + ": 「%s」 는 자산종류 코드표(p48)에 없음(14·17 은 06 레코드)" % kind)
            self._bjd(a, 8)
            sp = a.t(9)
            if sp and sp not in spots:
                self.fail(a.where(9) + ": 「%s」 는 국내 특수지코드(0~9, p107)가 아님" % sp)
            self._lot(a, 9, 10, 11)
            for p_no, c_no in ((18, 19), (21, 22)):
                purpose, cause = a.t(p_no), a.t(c_no)
                if purpose and purpose not in purposes:
                    self.fail(a.where(p_no) + ": 「%s」 는 등기목적 코드표(p109)에 없음" % purpose)
                elif purpose == "A1ZZAZ" and cause.strip():
                    self.fail(a.where(c_no) + ": 등기목적이 소유권보존(A1ZZAZ)이면 등기원인을 적지 않음(p49)")
                elif purpose and cause.strip() and cause not in causes.get(purpose, {}):
                    self.fail(a.where(c_no) + ": 「%s」 는 등기목적 %s 의 등기원인 코드(p109~110)가 아님" % (cause, purpose))
            if _ymd(a.t(20)) and _ymd(a.t(17)) and a.t(20) > a.t(17):
                self.fail(a.where(20) + ": 17 양도일자보다 늦음(추론)")
            acq = a.t(35)
            if acq and acq not in ("01", "02", "03", "04", "05"):
                self.fail(a.where(35) + ": 국내 자산 취득가액종류(01~05, p49)가 아님")
            v = {no: a.n(no) for no, f in a.f.items() if f["type"] == "N"}
            for target, want, text, basis in (
                    (38, (v[33], v[34], v[36], v[37]), "33 - 34 - 36 - 37", "브리프"),
                    (40, (v[38], v[39]), "38 - 39", "p50 「38 = 39 + 40」"),
                    (42, (v[40], v[41]), "40 - 41", "브리프")):
                if v[target] is None or None in want:
                    continue
                w = want[0] - sum(want[1:])
                if v[target] != w:
                    self.fail(a.where(target) + ": %s (%d)와 다름(%s)" % (text, w, basis))
            if a.t(4) == "05" and v[40]:
                self.fail(a.where(40) + ": 과세구분 05(전체비과세)이면 0(p50)")
            if v[41] and code not in LTD_RATES:
                self.fail(a.where(41) + ": 장기보유특별공제는 세율구분 10·11 일 때만(p33·p50·p51)")
            if v[43] and v[60]:
                self.fail(a.where(60) + ": 43 세액감면대상과 함께 쓸 수 없음(p51·p53)")
            red = (v[43] or 0) + (v[60] or 0)
            if red > 0 and v[42] is not None and v[42] < red:
                self.fail(a.where(42) + ": 43 + 60 감면소득금액 %d 보다 작음(p51)" % red)
            rk = a.t(44)
            if rk and rk != "ZZZ" and not re.fullmatch(r"\d{3}", rk):
                self.fail(a.where(44) + ": ZZZ 나 3자리 감면코드가 아님(p51)")
            if not red:
                if rk != "ZZZ":
                    self.fail(a.where(44) + ": 감면이 없으면 ZZZ(p51)")
                if v[45]:
                    self.fail(a.where(45) + ": 감면이 없으면 00000(p51)")
            elif rk in ("", "ZZZ"):
                self.fail(a.where(44) + ": 감면소득금액이 있으면 감면코드를 적는다(p51)")
            if acq != "04":
                for no in range(46, 56):
                    if v[no]:
                        self.fail(a.where(no) + ": 취득가액종류가 04(환산가액)가 아니면 0(p49·p52)")
            if a.t(56) != "1":
                self.fail(a.where(56) + ": 변환 프로그램은 1(p52)")
            if a.b(57) != b"KR ":
                self.fail(a.where(57) + ": 국내 자산은 「KR 」(p52)")
            if a.t(58) != kr:
                self.fail(a.where(58) + ": 국내 자산은 「%s」(p52)" % kr)
            if a.t(59).strip():
                self.fail(a.where(59) + ": 국내 자산은 공란(p53)")
            if a.t(64) not in hold:
                self.fail(a.where(64) + ": 「%s」 는 보유기간 코드(p53·p119)가 아님" % a.t(64))
            if a.t(65) not in live:
                self.fail(a.where(65) + ": 「%s」 는 거주기간 코드(p53·p120)가 아님" % a.t(65))
            n61 = v[61]
            if n61 is not None and n61 > 0 and n61 not in serials07:
                self.fail(a.where(61) + ": 07 에 같은 필요경비신고자료일련번호가 없음(p53·p59)")
            if n61 == 0 and acq == "01" and v[37]:
                self.fail(a.where(61) + ": 37 기타필요경비가 있으면 07 필요경비신고자료일련번호를 적는다(p53 에서 추론)")

    # 07 필요경비 상세 (12)
    # 5 상세일련번호는 필요경비신고자료일련번호마다 1 부터 차례로 센다(p60 5번 「필요경비신고자료일련번호별로 일련번호를
    # 순차적으로 부여」). p104 수록순서는 07 의 정렬 키를 「일련번호/구분코드/구분코드별_일련번호」라 적어 구분코드마다 다시
    # 세는 것처럼 읽힌다. 칸 설명인 p60 을 따르고, 줄 순서는 p104 의 키(일련번호·구분코드·상세일련번호)로 본다.
    # 구분코드 순으로 늘어놓고 차례로 세면 두 쪽의 순서가 같아진다. 홈택스 형식검증으로 확인할 항목이다
    def _expenses(self, exps, assets):
        by_code = {v["전자코드"]: v for v in self.codes["필요경비구분"].values()}
        banned = set(self.codes["메타"]["필요경비_쓰지않는코드"]["코드"])
        blank_proof = self.codes["메타"]["증빙_필수아닌행"]["코드"]
        proofs = set(self.codes["증빙종류목록"])          # p61 표: 01 02 03 04 05(계약서) 10
        serials05 = {a.n(61) for a in assets if a.n(61)}
        counters, groups, prev = {}, {}, None
        for r in exps:
            sx = r.b(3)
            s = int(sx) if re.fullmatch(rb"\d{6}", sx) else None
            if s is None:
                self.fail(r.where(3) + ": 앞을 0 으로 채운 6자리 숫자가 아님(p23)")
            elif s not in serials05:
                self.fail(r.where(3) + ": 05 의 61 필요경비신고자료일련번호에 없는 번호(p59)")
            code = r.t(4)
            info = by_code.get(code)
            if code in banned:
                self.fail(r.where(4) + ": 소계·계 코드는 쓰지 않음(p60)")
            elif info is None:
                self.fail(r.where(4) + ": 「%s」 는 필요경비 구분코드 표(p59~60)에 없음" % code)
            dx = r.b(5)
            d = int(dx) if re.fullmatch(rb"\d{6}", dx) else None
            if d is None:
                self.fail(r.where(5) + ": 앞을 0 으로 채운 6자리 숫자가 아님(p23)")
            elif s is not None:
                counters[s] = counters.get(s, 0) + 1
                if d != counters[s]:
                    self.fail(r.where(5) + ": %d 이어야 함(필요경비신고자료일련번호마다 1 부터 차례로, p60)" % counters[s])
            if None not in (s, d):
                key = (s, code, d)
                if prev is not None and key < prev:
                    self.fail("%d줄(07): 정렬 순서(일련번호·구분코드·상세일련번호)가 틀림(p104)" % r.line)
                prev = key if prev is None else max(prev, key)
            amt = r.n(9)
            biz, day, proof = r.b(7), r.t(8), r.t(10)
            if info is not None and info.get("필수"):
                if amt:
                    if not biz.strip():
                        self.fail(r.where(7) + ": 구분코드 %s 는 지급금액이 있으면 사업자등록번호를 적는다(p60)" % code)
                    elif not re.fullmatch(rb"\d{10}", biz):
                        self.fail(r.where(7) + ": 숫자 10자리가 아님(p21)")
                    if not day.strip():
                        self.fail(r.where(8) + ": 구분코드 %s 는 지급금액이 있으면 지급일자를 적는다(p60)" % code)
                    if proof == blank_proof or proof not in proofs:
                        self.fail(r.where(10) + ": 구분코드 %s 는 지급금액이 있으면 증빙종류코드(%s)를 적는다(p60~61)"
                                  % (code, ",".join(sorted(proofs))))
            elif info is not None:
                if biz.strip():
                    self.fail(r.where(7) + ": 필수가 아닌 구분코드는 공백 10자리(p60)")
                if day.strip():
                    self.fail(r.where(8) + ": 필수가 아닌 구분코드는 공백 8자리(p60)")
                if proof != blank_proof:
                    self.fail(r.where(10) + ": 필수가 아닌 구분코드는 %s(p61)" % blank_proof)
            if s is not None and info is not None and amt is not None:
                groups.setdefault(s, []).append((code, amt))
        by_serial = {}
        for a in assets:
            if a.n(61):
                by_serial.setdefault(a.n(61), []).append(a)
        for s, items in groups.items():
            dep = _part(items, "14")
            if dep > max(_part(items, "11"), _part(items, "12")) + _part(items, "13"):
                self.fail("07 필요경비신고자료일련번호 %d: 감가상각비(14xxx) %d 이 취득가액(11xxx 또는 12001) + 가산항목(13xxx)보다 큼(p60 에서 추론)" % (s, dep))
            g = by_serial.get(s) or []
            if not g or any(a.t(35) != "01" for a in g):
                continue        # 실지거래가액이 아니면 05-34 가 07 합과 같다는 근거가 없다
            acq = _part(items, "11") + _part(items, "12") + _part(items, "13") - dep
            other = _part(items, "2")
            v34, v37 = [a.n(34) for a in g], [a.n(37) for a in g]
            if None not in v34 and acq != sum(v34):
                self.fail("%d줄(05) 34 %s: 07 필요경비신고자료일련번호 %d 의 취득가액 구분코드(11xxx·12xxx·13xxx - 14xxx) 합 %d 과 다름(브리프)"
                          % (g[0].line, g[0].f[34]["name"], s, acq))
            if None not in v37 and other != sum(v37):
                self.fail("%d줄(05) 37 %s: 07 필요경비신고자료일련번호 %d 의 기타필요경비 구분코드(2xxxx) 합 %d 과 다름(브리프)"
                          % (g[0].line, g[0].f[37]["name"], s, other))

    # 14. 신고값 대사
    def _reconcile(self, rv, h, b, by):
        if not isinstance(rv, dict):
            self.fail("신고값이 JSON 객체가 아님")
            return

        def get(path, label=None):
            cur = rv
            for k in path:
                try:
                    cur = cur[k]
                except (KeyError, IndexError, TypeError):
                    self.fail("신고값에 %s 없음" % (label or ".".join(str(p) for p in path)))
                    return _MISSING
            return cur

        def same(r, no, value, numeric=False):
            a = r.t(no).strip()
            v = "" if value is None else str(value).strip()
            if numeric and a.isdigit() and v.isdigit():
                return int(a) == int(v)
            return a == v

        if h is not None:
            for no, path in ((3, ("신고인", "주민등록번호")), (14, ("신고인", "성명")), (12, ("신고", "홈택스ID")),
                             (6, ("신고", "구분코드")), (7, ("신고", "유형")), (8, ("신고", "과세기간")),
                             (9, ("신고", "상세코드")), (10, ("신고", "서식종류")), (13, ("신고", "제출년월")),
                             (24, ("신고", "작성일")), (25, ("신고", "양도일자"))):
                v = get(path)
                if v is not _MISSING and not same(h, no, v):
                    self.fail(h.where(no) + ": 신고값 %s 와 다름" % ".".join(path))
        if b is not None:
            A = ("신고인", "주소")
            for no, path, numeric in ((3, A + ("법정동코드",), False), (4, A + ("특수지",), False),
                                      (5, A + ("번지",), True), (6, A + ("호",), True), (7, A + ("아파트명",), False),
                                      (8, A + ("아파트동",), False), (9, A + ("아파트호",), False),
                                      (12, ("신고인", "전화"), False), (13, ("신고인", "전자메일"), False),
                                      (16, ("신고인", "거주지국"), False), (26, ("신고인", "국적"), False)):
                v = get(path)
                if v is _MISSING:
                    continue
                if no == 4 and (v is None or not str(v).strip()):
                    v = "0"                                  # 특수지가 비면 0(global.md)
                if not same(b, no, v, numeric):
                    self.fail(b.where(no) + ": 신고값 %s 와 다름" % ".".join(path))
            for no, key, table in ((14, "내외국인", "내외국인여부"), (15, "거주구분", "거주구분")):
                v = get(("신고인", key))
                if v is _MISSING:
                    continue
                code = (self.codes[table].get(str(v)) or {}).get("코드")
                if code is None:
                    self.fail("신고값 신고인.%s 이 코드표(%s)에 없음" % (key, table))
                elif b.t(no) != code:
                    self.fail(b.where(no) + ": 신고값 신고인.%s 와 다름" % key)
        buyers = get(("양수인",))
        if buyers is not _MISSING:
            if not isinstance(buyers, list) or len(buyers) != len(by["04"]):
                self.fail("04 %d줄이 신고값 양수인 %s 명과 다름" % (len(by["04"]), len(buyers) if isinstance(buyers, list) else "-"))
            else:
                for i, (r, _) in enumerate(zip(by["04"], buyers)):
                    for no, key in ((4, "구분"), (5, "내외국인"), (6, "번호"), (7, "성명"), (8, "전화"), (11, "관계")):
                        v = get(("양수인", i, key), "양수인[%d].%s" % (i, key))
                        if v is not _MISSING and not same(r, no, v):
                            self.fail(r.where(no) + ": 신고값 양수인[%d].%s 와 다름" % (i, key))
                    for no, key in ((9, "지분분자"), (10, "지분분모")):
                        v = get(("양수인", i, key), "양수인[%d].%s" % (i, key))
                        if v is _MISSING:
                            continue
                        try:
                            want = int(Decimal(str(v)) * 1000)
                        except (InvalidOperation, ValueError):
                            want = None
                        if want is None or r.n(no) != want:
                            self.fail(r.where(no) + ": 신고값 양수인[%d].%s 와 다름" % (i, key))
        self._reconcile_rows(get, by["03"], ("전자신고", "세율별"), "세율별",
                             lambda r: (r.t(3), r.t(4)), lambda x: (str(x["국내외분"]), str(x["세율구분"])),
                             lambda k: "%s/%s" % k, ("국내외분", "세율구분"))
        self._reconcile_rows(get, by["05"], ("전자신고", "계산명세"), "계산명세",
                             lambda r: _serial_of(r.b(3)), lambda x: _as_int(x["일련번호"]), lambda k: "%s" % k, ("일련번호",))
        self._reconcile_rows(get, by["07"], ("전자신고", "필요경비명세"), "필요경비명세",
                             lambda r: (_serial_of(r.b(3)), r.t(4), _serial_of(r.b(5))),
                             lambda x: (_as_int(x["일련번호"]), str(x["전자코드"]), _as_int(x["상세일련번호"])),
                             lambda k: "%s/%s/%s" % k, ("일련번호", "전자코드", "상세일련번호"), RV_KEYS_07)

    def _reconcile_rows(self, get, recs, path, label, file_key, rv_key, show, key_names, renames=None):
        """파일의 레코드 줄을 신고값 전자신고 절의 행과 칸마다 견준다.

        줄과 행은 key_names 칸(03 국내외분·세율구분, 05 일련번호, 07 일련번호·구분코드·상세일련번호)으로 잇는다.
        자료구분·서식코드와 공란을 뺀 모든 칸을 본다. 13자리 금액 칸은 문장에 두 금액을 싣고, 그 밖의 칸(날짜, 면적,
        법정동코드, 지번, 코드, 상호, 사업자번호 등)은 칸 이름과 신고값 경로만 싣는다. 지번과 상호는 인적 성격의 값이다.
        """
        renames = renames or {}
        rows = get(path)
        if rows is _MISSING:
            return
        if not isinstance(rows, list):
            self.fail("신고값 %s 이 목록이 아님" % ".".join(path))
            return
        want = {}
        for i, x in enumerate(rows):
            missing = [k for k in key_names if not isinstance(x, dict) or k not in x]
            if missing:
                self.fail("신고값에 전자신고.%s[%d].%s 없음" % (label, i, missing[0]))
                continue
            want[rv_key(x)] = x
        seen = set()
        for r in recs:
            k = file_key(r)
            seen.add(k)
            x = want.get(k)
            if x is None:
                self.fail("%d줄(%s): 신고값 전자신고.%s 에 %s 행이 없음" % (r.line, r.kind, label, show(k)))
                continue
            for no, f in r.f.items():
                name = f["name"]
                key = renames.get(name, name)
                if no <= 2 or f["class"] == "SPACE" or key in key_names:
                    continue
                where = "전자신고.%s[%s].%s" % (label, show(k), key)
                if key not in x:
                    self.fail("신고값에 %s 없음" % where)
                elif f["type"] == "N":
                    self._reconcile_number(r, no, f, x[key], where)
                else:
                    self._reconcile_text(r, no, name, x[key], where)
        for k in want:
            if k not in seen:
                self.fail("신고값 전자신고.%s 의 %s 행이 파일에 없음" % (label, show(k)))

    def _reconcile_number(self, r, no, f, value, where):
        money = f["len"] == 13 and f["dec"] == 0
        v = _scaled(value, f["dec"])
        if v is None:
            self.fail("신고값 %s 이 %s 아님" % (where, "정수가" if f["dec"] == 0 else "수가"))
        elif r.n(no) is not None and r.n(no) != v:
            if money:
                self.fail(r.where(no) + ": 신고값 %d 과 다름(파일 %d)" % (v, r.n(no)))
            else:
                self.fail(r.where(no) + ": 신고값 %s 와 다름" % where)

    def _reconcile_text(self, r, no, name, value, where):
        if name in SERIAL_NAMES.get(r.kind, ()):
            a, v = _serial_of(r.b(no)), _as_int(value)
            if v is None:
                self.fail("신고값 %s 이 정수가 아님" % where)
            elif a is not None and a != v:
                self.fail(r.where(no) + ": 신고값 %s 와 다름" % where)
            return
        if value is None:
            v = ""
        elif isinstance(value, str):
            v = value.rstrip(" ")
        elif isinstance(value, int) and not isinstance(value, bool):
            v = str(value)
        else:
            self.fail("신고값 %s 이 글자가 아님" % where)
            return
        if r.t(no) != v:
            self.fail(r.where(no) + ": 신고값 %s 와 다름" % where)


# ---------------------------------------------------------------- 진입점

def _check(path, efile_dir=None, rv=None):
    c = _Checker(efile_dir)
    if not c.fails:
        c.run(path, rv)
    return c.fails, c.warns, c.nlines


def check_file_ex(path, efile_dir=None, rv=None):
    """(실패 문장 목록, 경고 문장 목록). 실패가 비면 통과. 경고는 주민등록번호 검증번호가 옛 규칙과 다른 것."""
    fails, warns, _ = _check(path, efile_dir=efile_dir, rv=rv)
    return fails, warns


def check_file(path, efile_dir=None, rv=None):
    """실패 문장 목록. 비면 통과. rv(신고값 JSON, C8)를 주면 01·02·04 의 신고 구분·인적사항 칸과 03·05·07 의 모든 칸을 대사한다."""
    return check_file_ex(path, efile_dir=efile_dir, rv=rv)[0]


def main(argv=None):
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="python -m yangdo.efile_check",
                                 description="양도소득세 전자신고 변환파일(C116300) 독립 검증")
    ap.add_argument("파일")
    ap.add_argument("--신고값", dest="rv", help="신고값 JSON(C8) 경로. 주면 신고인 칸과 03·05·07 의 모든 칸을 대사한다")
    a = ap.parse_args(argv)
    rv = None
    if a.rv:
        try:
            with open(a.rv, encoding="utf-8") as f:
                rv = json.load(f)
        except (OSError, ValueError) as e:
            print("신고값 파일을 읽을 수 없음: %s" % e)
            return 1
    fails, warns, n = _check(a.파일, rv=rv)
    for w in warns:
        print("경고: " + w, file=sys.stderr)
    if fails:
        for m in fails:
            print(m)
        return 1
    print("검증 통과 (%d줄)" % n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
