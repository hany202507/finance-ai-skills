# -*- coding: utf-8 -*-
"""양도소득세 전자신고 변환파일(서식코드 C116300, 규격서 V5.17) 생성기.

신고값 JSON(C8, return_values.build)을 고정길이 CP949 레코드로 옮긴다. 값을 계산하거나 판정하지 않는다.
칸 위치·길이·고정값은 efile/layout_c116300.json, 코드는 efile/codes_c116300.json, 잠금은 efile/규격판.json 에서 읽는다.

    build_records(rv)  레코드 바이트 목록(줄 끝 없음). 01 → 02 → 03 → 04 → 05 → 07 (규격서 p104)
    build(rv)          (레코드 바이트 목록, 경고 문장 목록). 경고는 확인이 필요한 코드를 썼거나 환급계좌를 적지 않은 경우다
    write(rv, out_dir) 임시 폴더에 쓰고 독립 검증기를 별도 프로세스로 돌린 뒤, 통과한 파일만 최종 이름으로 남긴다

검증기(yangdo.efile_check)는 import 하지 않는다. 생성기와 검증기가 같은 코드를 타면 같이 틀리기 때문이다.
홈택스 로그인·형식검증·제출은 사람이 한다.

칸 채우기(규격서 p19~23)
  문자 칸   왼쪽부터 쓰고 남는 바이트는 공백. ASCII(0x20~0x7E)와 KS X 1001 완성형 한글·기호 2바이트만 쓴다(p15).
            한자와 CP949 확장 글자(「똠」 등)는 받지 않는다. 검증기와 같은 범위다.
  수치 칸   오른쪽 맞춤, 앞은 0. 음수는 맨 앞에 「-」. 비율·면적·지분은 소수점 없이 소수 자리만큼 늘려 쓴다(53.05 → 05305).
  일련번호  문자 칸이어도 앞을 0 으로 채운 6자리(p23 9번). 04-3, 05-3, 07-3, 07-5.
  번지·호   문자 칸으로 왼쪽부터 쓴다(p23 「문자(숫자·영문자 포함)」). 05-10·11 은 레이아웃 분류가 SEQ 지만 일련번호가 아니다.

신고값에 없어 여기서 정하는 칸
  01-4 납세자구분      코드표 「납세자구분」을 신고인.내외국인으로 찾는다(p26). 코드표 값에 「확인」이 있으면 경고로 낸다.
  01-23 세무프로그램코드 코드표 「세무프로그램코드」의 「기타」(p28).
  01-15·16 환급계좌    합계 행 자진납부할세액이 음수이고 신고값 맨 위 「환급계좌」가 있을 때만. 환급세액이 500만원 이상이면
                       적지 않는다(p26). 환급이 있는데 계좌를 적지 못하면 경고로 낸다. 예금종류(01-17)와 세무대리인 칸
                       (01-18~22·26·27)은 공란이다.
  02-18~25 도로명 칸   쓰지 않는다(법정동 주소 02-3~9 를 쓴다, p30). 수치 칸 02-21·22 는 0 으로 채운다.
  04-3 일련번호        신고값 양수인 목록의 차례대로 1부터.

오류
  Locked      규격판이 잠겼거나 읽을 수 없거나 레이아웃과 판이 다르다. write 가 낸다.
  BuildError  신고값을 레코드로 옮길 수 없다(ValueError 의 하위). 칸 길이 초과, 완성형에 없는 글자, 빈 Not Null 칸
              (수치 칸도 None 이면 0 으로 채우지 않는다), 규격서에 없는 코드. write 는 이 오류를 검증 문장으로 돌려주고
              파일을 남기지 않는다.
  ValueError  write 에 스킬의 efile 폴더가 아닌 efile_dir 를 주었다(검증기가 그 폴더로 검증하지 못한다).
  KeyError    신고값 전자신고 행에 레이아웃에 없는 키가 있거나 있어야 할 키가 없다(신고값 생성기와 레이아웃이 어긋남).
오류 문장과 검증 문장에는 칸 이름만 쓴다. 성명·주민등록번호·전화·주소 같은 값은 싣지 않는다.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from decimal import ROUND_DOWN, Decimal, InvalidOperation

from yangdo import SKILL_DIR

EFILE_DIR = os.path.join(SKILL_DIR, "efile")
LAYOUT_FILE = "layout_c116300.json"
CODES_FILE = "codes_c116300.json"
SPEC_FILE = "규격판.json"
CRLF = b"\r\n"
CHECK_MODULE = "yangdo.efile_check"
CHECK_TIMEOUT = 300                       # 초
WARN_PREFIX = "경고: "                    # 검증기가 표준 오류에 쓰는 경고 줄의 머리

TMP_PREFIX = ".efile-"                    # write 가 출력 폴더 아래에 만드는 임시 폴더 이름의 머리
REJECTED_NAME = "검증안됨.tmp"            # 지우지 못한 임시 파일에 붙이는 이름(제출용 이름이 아니다)
SUBMIT_NAME = re.compile(r"^[0-9]{8}[A-Z][0-9]{6}\.[0-9]{2}$")       # 제출용 파일 이름 꼴(p20)
PROGRAM_KEY = "기타"                      # 01-23: 코드표 세무프로그램코드에서 쓰는 항목
REFUND_ACCOUNT_LIMIT = 5000000            # 01-16: 환급세액이 이 금액 이상이면 계좌를 적지 않는다(p26)
ACCOUNT_MAX = 16                          # 01-16: 계좌번호 16자리 이내(p26)
SERIAL_WIDTH = 6                          # 일련번호 6자리(p23)
SERIAL_FIELDS = {"04": ("일련번호",), "05": ("일련번호",), "07": ("필요경비신고자료일련번호", "상세일련번호")}
# 07 행에서 신고값 키가 레이아웃 name 과 다른 칸(레이아웃 name → 신고값 키, return_values 머리말)
EXPENSE_RENAMES = {"필요경비신고자료일련번호": "일련번호", "구분코드": "전자코드", "사업자등록번호": "사업자번호"}
ROW_EXTRAS = {"03": (), "05": ("자산",), "07": ("구분코드", "자산")}        # 신고값 행에만 있고 파일에 쓰지 않는 키
# 레이아웃 비고는 Null 허용이지만 항목 설명이 필수입력이라고 적은 칸
REQUIRED_BY_TEXT = {("02", "주소_번지"): "필수입력, 무번지면 특수지코드 9 와 0, 규격서 p30",
                    ("02", "주소_호"): "필수입력, 호가 없으면 0, 규격서 p30"}
# 코드표에서 정하는 칸. 값이 없으면(None) 「규격서에 없는 코드」로 알리고 어디서 받는지 덧붙인다
CODE_FIELDS = {
    ("01", "납세자구분"): "신고인 JSON 신고인.내외국인(1 내국인, 9 외국인)",
    ("01", "세무프로그램코드"): "코드표 세무프로그램코드의 %s 항목" % PROGRAM_KEY,
    ("02", "내외국인여부"): "신고인 JSON 신고인.내외국인",
    ("02", "거주구분"): "신고인 JSON 신고인.거주구분",
    ("02", "거주지국명"): "신고인 JSON 신고인.거주지국",
    ("04", "양수인_주민사업자구분"): "신고인 JSON 양수인[].구분",
    ("04", "양수인_내외국인_구분코드"): "신고인 JSON 양수인[].내외국인",
    ("04", "양수인_양도자와의관계"): "신고인 JSON 양수인[].관계코드(질문 F02)",
    ("05", "거래일자_양도등기목적"): "신고인 JSON 자산[id].등기목적.양도",
    ("05", "거래일자_양도등기원인"): "신고인 JSON 자산[id].등기원인.양도(질문 F04)",
    ("05", "거래일자_취득등기목적"): "신고인 JSON 자산[id].등기목적.취득",
    ("05", "거래일자_취득등기원인"): "신고인 JSON 자산[id].등기원인.취득(질문 F04)",
    ("07", "증빙종류코드"): "사실관계 필요경비 항목의 증빙종류",
}


class Locked(Exception):
    """규격판이 잠겨 있어(또는 읽을 수 없거나 레이아웃과 판이 달라) 전자신고 파일을 만들지 않는다."""


class BuildError(ValueError):
    """신고값을 레코드로 옮길 수 없다. 문장에는 칸 이름만 쓰고 값은 싣지 않는다."""


# ---------------------------------------------------------------- 칸 채우기

def _ksx_ok(b):
    """ASCII(0x20~0x7E)와 KS X 1001 완성형 2바이트(한글 0xB0~0xC8 행, 기호 0xA1~0xAC 행, 둘째 0xA1~0xFE)만인지."""
    i, n = 0, len(b)
    while i < n:
        x = b[i]
        if 0x20 <= x <= 0x7E:
            i += 1
        elif (0xB0 <= x <= 0xC8 or 0xA1 <= x <= 0xAC) and i + 1 < n and 0xA1 <= b[i + 1] <= 0xFE:
            i += 2
        else:
            return False
    return True


def _c(v, n, where=""):
    """문자 칸: 왼쪽부터, 남는 바이트는 공백. KS X 1001 완성형과 ASCII 만. where 는 오류 문장에 쓸 칸 이름."""
    if v is None:
        s = ""
    elif isinstance(v, str):
        s = v
    elif isinstance(v, int) and not isinstance(v, bool):
        s = str(v)
    else:
        raise BuildError("%s: 문자 칸에 글자가 아닌 값이 왔다" % (where or "문자 칸"))
    try:
        b = s.encode("cp949")
    except UnicodeEncodeError:
        b = None
    if b is None or not _ksx_ok(b):
        raise BuildError("%s: KS X 1001 완성형에 없는 글자가 있다(한글 완성형과 ASCII 만 쓴다, 규격서 p15)" % (where or "문자 칸"))
    if len(b) > n:
        raise BuildError("%s: 칸 길이 %d바이트를 넘는다" % (where or "문자 칸", n))
    return b + b" " * (n - len(b))


def _n(v, n, dec=0, where=""):
    """수치 칸: 오른쪽 맞춤 0 채움. 음수는 맨 앞 '-'. dec 자리 고정 소수(소수점 없음, 그 아래는 버린다)."""
    try:
        if isinstance(v, bool):
            raise InvalidOperation
        d = Decimal(str(v if v not in (None, "") else 0))
        q = int((d * (10 ** dec)).to_integral_value(rounding=ROUND_DOWN))
    except (InvalidOperation, ValueError, OverflowError):
        raise BuildError("%s: 수치 칸에 숫자가 아닌 값이 왔다" % (where or "수치 칸"))
    body = str(abs(q))
    if len(body) > (n - 1 if q < 0 else n):
        raise BuildError("%s: 칸 길이 %d자리를 넘는다" % (where or "수치 칸", n))
    if q < 0:
        return ("-" + body.rjust(n - 1, "0")).encode("ascii")
    return body.rjust(n, "0").encode("ascii")


def _blank(v):
    return v is None or (isinstance(v, str) and not v.strip())


def _read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------- 잠금

def _lock_reason(efile_dir=None):
    """파일을 만들면 안 되는 까닭. 만들어도 되면 None."""
    d = efile_dir or EFILE_DIR
    try:
        spec = _read_json(os.path.join(d, SPEC_FILE))
        base = _read_json(os.path.join(d, LAYOUT_FILE))["규격"]
    except (OSError, ValueError, KeyError, TypeError):
        return "규격판(efile/%s)이나 레이아웃을 읽을 수 없다" % SPEC_FILE
    if not isinstance(spec, dict) or spec.get("잠금") is not False:
        return "규격판이 잠겨 있다(efile/%s 의 잠금). 새 규격서 판을 확인하고 레이아웃을 맞춘 뒤에 푼다" % SPEC_FILE
    if (spec.get("판"), spec.get("sha256")) != (base.get("판"), base.get("sha256")):
        return "규격판 %s 과 레이아웃의 규격서 판 %s 이 다르다" % (spec.get("판"), base.get("판"))
    return None


def _spec_locked(efile_dir=None):
    return _lock_reason(efile_dir) is not None


# ---------------------------------------------------------------- 레코드 조립

class _Builder:
    def __init__(self, rv, efile_dir=None):
        d = efile_dir or EFILE_DIR
        self.rv = rv
        self.layout = _read_json(os.path.join(d, LAYOUT_FILE))
        self.codes = _read_json(os.path.join(d, CODES_FILE))
        self.notes = []                    # 경고 문장(칸 이름만, 값은 싣지 않는다)

    def note(self, text):
        if text not in self.notes:
            self.notes.append(text)

    def fields(self, kind):
        return self.layout["레코드"][kind]["필드"]

    def fixed(self, kind, name):
        """레이아웃 점검내용이 곧 고정값인 칸(자료구분, 서식코드, 세목코드, 민원종류코드)."""
        return next(f for f in self.fields(kind) if f["name"] == name)["check"]

    def table_code(self, table, key, kind, name, row=None):
        """코드표 table 에서 key 의 코드. 항목이 없거나 코드가 null 이면 「규격서에 없는 코드」(값은 문장에 싣지 않는다).

        코드표 값에 「확인」이 있으면(규격서가 직접 정하지 않아 기본값으로 쓴 코드) 그 문장을 경고로 남긴다.
        """
        entry = (self.codes.get(table) or {}).get(key) if isinstance(key, str) else None
        no = next(f["no"] for f in self.fields(kind) if f["name"] == name)
        if not isinstance(entry, dict) or entry.get("코드") is None:
            raise BuildError("규격서에 없는 코드: %s-%d %s(%s코드표 %s). %s 를 확인한다"
                             % (kind, no, name, "%d번째 줄, " % row if row else "", table, CODE_FIELDS[(kind, name)]))
        if entry.get("확인"):
            self.note("%s-%d %s: %s" % (kind, no, name, entry["확인"]))
        return entry["코드"]

    def record(self, kind, vals, row=None):
        """레이아웃 필드 순서대로 한 줄. vals 는 {필드 name: 값}. 없는 칸은 수치 0, 문자 공란.

        자료구분·서식코드(1·2번)는 레이아웃 고정값, 공란 칸은 공백이다. 레이아웃에 없는 이름이 오면 KeyError.
        vals 에 이름이 있는데 값이 None 인 Not Null 칸은 문자든 수치든 BuildError 다.
        """
        rec = self.layout["레코드"][kind]
        fields = rec["필드"]
        own = {f["name"] for f in fields if f["no"] > 2 and f["class"] != "SPACE"}
        unknown = set(vals) - own
        if unknown:
            raise KeyError("레코드 %s 레이아웃에 없는 칸: %s" % (kind, ", ".join(sorted(unknown))))
        tail = "(%d번째 줄)" % row if row else ""
        out = []
        for f in fields:
            name = f["name"]
            where = "%s-%d %s%s" % (kind, f["no"], name, tail)
            if f["no"] <= 2:
                out.append(_c(f["check"], f["len"], where))
            elif f["class"] == "SPACE":
                out.append(b" " * f["len"])
            elif f["type"] == "N":
                # 값을 받아야 하는 수치 칸이 비어 오면 0 으로 채우지 않는다(p19 「NUMBER 값이 들어오지 않으면 오류」)
                if f["notnull"] and name in vals and _blank(vals[name]):
                    raise BuildError("%s: 값이 없다(Not Null 수치 칸, 규격서 p19)" % where)
                out.append(_n(vals.get(name), f["len"], f["dec"], where))
            else:
                v = vals.get(name)
                hint = CODE_FIELDS.get((kind, name))
                # 코드 칸은 Null 허용이어도 None 이면 코드를 정하지 못한 것이다(빈 글자는 규격서가 적지 않게 한 칸)
                if hint and _blank(v) and (f["notnull"] or (name in vals and v is None)):
                    raise BuildError("규격서에 없는 코드: %s. %s 에서 받는다" % (where, hint))
                if _blank(v) and (f["notnull"] or (kind, name) in REQUIRED_BY_TEXT):
                    raise BuildError("%s: 값이 없다(%s)" % (where, REQUIRED_BY_TEXT.get((kind, name), "Not Null 칸, 규격서 p19")))
                out.append(_c(v, f["len"], where))
        raw = b"".join(out)
        assert len(raw) == rec["길이"], "레코드 %s 길이 %d, 규격 %d" % (kind, len(raw), rec["길이"])
        return raw

    def from_row(self, kind, row, renames=None):
        """신고값 전자신고 행 → {필드 name: 값}. 행의 키는 레이아웃 name 그대로여야 한다(0 칸까지 모두)."""
        renames = renames or {}
        vals, used = {}, set(ROW_EXTRAS[kind])
        for f in self.fields(kind):
            if f["no"] <= 2 or f["class"] == "SPACE":
                continue
            key = renames.get(f["name"], f["name"])
            if key not in row:
                raise KeyError("신고값 전자신고 %s 행에 없는 키: %s" % (kind, key))
            vals[f["name"]] = row[key]
            used.add(key)
        unknown = set(row) - used
        if unknown:
            raise KeyError("레코드 %s 레이아웃에 없는 키: %s" % (kind, ", ".join(sorted(unknown))))
        for name in SERIAL_FIELDS.get(kind, ()):
            vals[name] = self.serial(vals[name], "%s %s" % (kind, name))
        return vals

    @staticmethod
    def serial(v, where):
        """일련번호: 앞을 0 으로 채운 6자리(규격서 p23)."""
        if isinstance(v, bool) or not isinstance(v, int) or not 0 < v < 10 ** SERIAL_WIDTH:
            raise BuildError("%s: 일련번호가 1 이상 %d자리 정수가 아니다" % (where, SERIAL_WIDTH))
        return str(v).rjust(SERIAL_WIDTH, "0")

    # 01 HEADER
    def header(self):
        rv = self.rv
        s, p = rv["신고"], rv["신고인"]
        vals = {
            "납세자ID": p.get("주민등록번호"),
            "납세자구분": self.table_code("납세자구분", p.get("내외국인"), "01", "납세자구분"),
            "세목코드": self.fixed("01", "세목코드"),
            "신고구분코드": s["구분코드"], "신고유형": s["유형"], "과세기간_년월": s["과세기간"],
            "신고구분상세코드": s["상세코드"], "신고서종류코드": s["서식종류"],
            "민원종류코드": self.fixed("01", "민원종류코드"), "사용자ID": s.get("홈택스ID"), "제출년월": s["제출년월"],
            "성명": p.get("성명"), "작성일자": s["작성일"], "양도일자": s["양도일자"],
            "세무프로그램코드": self.table_code("세무프로그램코드", PROGRAM_KEY, "01", "세무프로그램코드"),
        }
        vals.update(self.refund_account())
        return self.record("01", vals)

    def refund_account(self):
        """01-15·16. 환급받을 세액(합계 행 자진납부할세액이 음수)이 500만원 미만이고 환급계좌가 있을 때만(p26).

        환급이 없으면 환급계좌를 읽지 않는다(C7). 환급이 있는데 받은 환급계좌를 적지 못하면 까닭을 경고로 남긴다
        (계좌번호 값은 싣지 않는다).
        """
        acct = self.rv.get("환급계좌")
        if not acct:                               # None 이나 빈 글자(신고인 JSON 은 "" 로 올 수 있다)
            return {}
        t = self.codes["세율별특수행"]["합계"]
        total = [r for r in self.rv["전자신고"]["세율별"] if (r.get("국내외분"), r.get("세율구분")) == (t["국내외분"], t["세율구분"])]
        due = total[0].get("자진납부할세액") if total else 0
        if isinstance(due, bool) or not isinstance(due, int) or due >= 0:
            return {}
        where = "01-15·16 환급계좌"
        if not isinstance(acct, dict):
            self.note(where + ": 신고값 환급계좌가 {은행코드, 계좌번호} 모양이 아니라 적지 않았다")
            return {}
        if -due >= REFUND_ACCOUNT_LIMIT:
            self.note(where + ": 환급받을 세액이 %d만원 이상이라 은행코드와 계좌번호를 적지 않았다. 계좌개설(변경)신고서로 "
                      "관할 세무서에 신고한다(규격서 p26)" % (REFUND_ACCOUNT_LIMIT // 10000))
            return {}
        bank, number = acct.get("은행코드"), acct.get("계좌번호")
        if _blank(bank) or _blank(number):
            self.note(where + ": 은행코드와 계좌번호 가운데 빈 것이 있어 둘 다 적지 않았다")
            return {}
        if not (self.codes["은행"].get(bank) or {}).get("환급계좌"):
            raise BuildError("01-15 은행코드(국세환급금): 환급계좌로 쓸 수 있는 은행코드(규격서 p113)가 아니다")
        if not (isinstance(number, str) and re.fullmatch(r"[0-9]{1,%d}" % ACCOUNT_MAX, number)):
            raise BuildError("01-16 계좌번호(국세환급금): 숫자 %d자리 이내가 아니다(규격서 p26)" % ACCOUNT_MAX)
        return {"은행코드(국세환급금)": bank, "계좌번호(국세환급금)": number}

    # 02 기본사항
    def basic(self):
        p = self.rv["신고인"]
        a = p.get("주소") or {}
        c = p.get("코드") or {}
        return self.record("02", {
            "주소_법정동코드": a.get("법정동코드"), "주소_특수지코드": a.get("특수지") or "0",       # 특수지가 비면 0(global.md)
            "주소_번지": a.get("번지"), "주소_호": a.get("호"), "주소_아파트명": a.get("아파트명"),
            "주소_아파트동": a.get("아파트동"), "주소_아파트호": a.get("아파트호"),
            "전화번호": p.get("전화"), "전자메일주소": p.get("전자메일"),
            "내외국인여부": c.get("내외국인여부"), "거주구분": c.get("거주구분"),
            "거주지국코드": c.get("거주지국"), "거주지국명": c.get("거주지국명"), "국적코드": c.get("국적"),
        })

    # 03 세율별내역: 국내외분·세율구분 순(p104)
    def rates(self):
        rows = sorted(self.rv["전자신고"]["세율별"], key=lambda r: (str(r["국내외분"]), str(r["세율구분"])))
        return [self.record("03", self.from_row("03", r), i) for i, r in enumerate(rows, 1)]

    # 04 양수인내역: 신고값 양수인 목록의 차례대로 일련번호 1부터
    def buyers(self):
        out = []
        for i, b in enumerate(self.rv["양수인"], 1):
            out.append(self.record("04", {
                "일련번호": self.serial(i, "04 일련번호"),
                "양수인_주민사업자구분": self.table_code("양수인구분", b.get("구분"), "04", "양수인_주민사업자구분", i),
                "양수인_내외국인_구분코드": self.table_code("내외국인", b.get("내외국인"), "04", "양수인_내외국인_구분코드", i),
                "양수인_주민등록번호": b.get("번호"), "양수인_성명": b.get("성명"), "양수인_전화번호": b.get("전화"),
                "양수인_지분(분자)": b.get("지분분자"), "양수인_지분(분모)": b.get("지분분모"),
                "양수인_양도자와의관계": b.get("관계"),
            }, i))
        return out

    # 05 양도소득금액계산명세: 일련번호 순(p104)
    def assets(self):
        rows = sorted(self.rv["전자신고"]["계산명세"], key=lambda r: r["일련번호"])
        return [self.record("05", self.from_row("05", r), i) for i, r in enumerate(rows, 1)]

    # 07 취득가액및필요경비계산상세명세: 일련번호·구분코드·상세일련번호 순(p104)
    def expenses(self):
        rows = sorted(self.rv["전자신고"]["필요경비명세"], key=lambda r: (r["일련번호"], str(r["전자코드"]), r["상세일련번호"]))
        return [self.record("07", self.from_row("07", r, EXPENSE_RENAMES), i) for i, r in enumerate(rows, 1)]

    def build(self):
        edition = self.layout["규격"]["판"]
        if (self.rv.get("판") or {}).get("규격") != edition:
            raise BuildError("신고값의 규격 판이 레이아웃의 규격서 판 %s 과 다르다. 지금 판으로 신고값을 다시 만든다" % edition)
        return [self.header(), self.basic()] + self.rates() + self.buyers() + self.assets() + self.expenses()


def build(rv, efile_dir=None):
    """신고값 JSON(C8) → (레코드 바이트 목록, 경고 문장 목록). 레코드는 줄 끝 없이 01 → 02 → 03 → 04 → 05 → 07.

    옮길 수 없는 값이 있으면 BuildError(ValueError), 신고값 행의 키가 레이아웃과 어긋나면 KeyError.
    경고는 코드표가 「확인」을 단 코드를 썼거나(외국인 납세자구분 09) 환급이 있는데 환급계좌를 적지 못한 경우다.
    """
    b = _Builder(rv, efile_dir)
    return b.build(), list(b.notes)


def build_records(rv, efile_dir=None):
    """신고값 JSON(C8) → 레코드 바이트 목록. build 에서 경고를 뺀 것이다."""
    return build(rv, efile_dir)[0]


# ---------------------------------------------------------------- 파일 쓰기

def file_name(rv, efile_dir=None):
    """<작성일자 YYYYMMDD><서식코드>.<신고구분상세코드> (규격서 p20)."""
    s = rv["신고"]
    made, detail = s.get("작성일"), s.get("상세코드")
    if not (isinstance(made, str) and re.fullmatch(r"[0-9]{8}", made) and isinstance(detail, str) and re.fullmatch(r"[0-9]{2}", detail)):
        raise BuildError("신고.작성일(YYYYMMDD)과 신고.상세코드(2자리)로 파일명을 만들 수 없다")
    form = _read_json(os.path.join(efile_dir or EFILE_DIR, LAYOUT_FILE))["레코드"]["01"]["서식코드"]
    return "%s%s.%s" % (made, form, detail)


def _run_check(python, path, rv_path):
    """검증기를 별도 프로세스로 돌린다. (실패 문장 목록, 경고 문장 목록). 입출력은 UTF-8 로 고정한다."""
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    env["PYTHONPATH"] = os.pathsep.join(x for x in (SKILL_DIR, env.get("PYTHONPATH")) if x)
    try:
        p = subprocess.run([python, "-m", CHECK_MODULE, path, "--신고값", rv_path], cwd=SKILL_DIR, env=env,
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=CHECK_TIMEOUT)
    except (OSError, subprocess.SubprocessError) as e:     # 실행 파일 없음(FileNotFoundError), 시간 초과(TimeoutExpired) 등
        return ["검증기(%s)를 돌리지 못해 파일을 남기지 않았다(%s)" % (CHECK_MODULE, type(e).__name__)], []
    warns = [x[len(WARN_PREFIX):] for x in p.stderr.splitlines() if x.startswith(WARN_PREFIX)]
    if p.returncode == 0:
        return [], warns
    fails = [x for x in p.stdout.splitlines() if x.strip()] if p.returncode == 1 else []
    return fails or ["검증기(%s)가 종료코드 %d 로 끝나 파일을 남기지 않았다" % (CHECK_MODULE, p.returncode)], warns


def _same_dir(a, b):
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def _remove_work(work):
    """임시 폴더를 지운다. 다 지웠으면 None, 남았으면 알릴 문장(폴더·파일 이름만).

    폴더 삭제는 막힐 수 있다(Windows 에서 백신·색인기가 파일을 잡은 경우). 그래서 제출용 이름의 파일을 먼저 지우고,
    지우지 못하면 제출용이 아닌 이름으로 바꾼다. 검증을 통과하지 않은 파일이 제출용 이름으로 남지 않게 하려는 것이다.
    """
    try:
        names = os.listdir(work)
    except OSError:
        names = []
    for n in names:
        if not SUBMIT_NAME.match(n):
            continue
        path = os.path.join(work, n)
        try:
            os.remove(path)
        except OSError:
            try:
                os.replace(path, os.path.join(work, REJECTED_NAME))
            except OSError:
                pass
    try:
        shutil.rmtree(work)
    except OSError:
        pass
    if not os.path.lexists(work):
        return None
    base = os.path.basename(work)
    try:
        stuck = sorted(n for n in os.listdir(work) if SUBMIT_NAME.match(n))
    except OSError:
        stuck = []
    if stuck:
        return ("임시 폴더 %s 에 검증을 통과하지 않은 파일 %s 이 제출용 이름으로 남아 있다. 제출하지 말고 폴더째 직접 지운다"
                % (base, ", ".join(stuck)))
    return "임시 폴더 %s 를 지우지 못했다. 신고값 임시 JSON 과 검증 전 임시 파일(인적사항)이 남아 있을 수 있으니 직접 지운다" % base


def _sweep(out_dir):
    """앞선 실행이 강제 종료 등으로 남긴 임시 폴더(.efile-*)를 지운다. 지우지 못한 폴더마다 문장 하나."""
    left = []
    for n in sorted(os.listdir(out_dir)):
        path = os.path.join(out_dir, n)
        if n.startswith(TMP_PREFIX) and os.path.isdir(path) and not os.path.islink(path):
            msg = _remove_work(path)
            if msg:
                left.append(msg)
    return left


def write(rv, out_dir, efile_dir=None, python=sys.executable):
    """전자신고 파일을 out_dir 에 쓴다. {"경로": 경로 또는 None, "검증": [실패 문장], "파일명": 이름, "경고": [경고 문장]}.

    차례: 잠금 확인(Locked, 이때는 출력 폴더를 건드리지 않는다) → 같은 이름의 옛 파일과 앞선 실행이 남긴 임시 폴더
    (.efile-*) 지움 → 레코드 조립 → out_dir 아래 임시 폴더에 최종 이름으로 쓰기
    → `python -m yangdo.efile_check <파일> --신고값 <임시 JSON>` 별도 프로세스 → 종료코드 0 이면 out_dir 의 최종 이름으로 옮김.
    검증에 실패하거나 레코드를 만들지 못하면(BuildError) 파일을 남기지 않고 문장을 「검증」에 담는다.
    신고값의 작성일·상세코드로 파일명조차 만들 수 없으면 BuildError 를 그대로 낸다.
    검증기는 파일명도 보므로 임시 파일을 임시 폴더 안에 최종 이름으로 둔다. 끝나면 그 파일부터 지우고 폴더를 지운다.
    폴더를 지우지 못하면 삼키지 않고 알린다. 검증에 실패한 실행이면 「검증」에, 통과한 실행이면 「경고」에 문장을 더한다.
    경고에는 검증기의 알림(주민등록번호 검증번호가 옛 규칙과 다름, 막지 않는다)과 build 의 경고도 들어간다.
    out_dir 는 상대 경로여도 된다. 절대 경로로 바꿔 쓰고 「경로」도 절대 경로로 돌려준다.
    efile_dir 는 스킬의 efile 폴더(기본값)만 받는다. 검증기 명령줄에 폴더 인자가 없어 다른 폴더의 레이아웃·코드로
    만든 파일은 같은 기준으로 검증할 수 없기 때문이다. 다른 폴더가 오면 ValueError 다.
    """
    if efile_dir is not None and not _same_dir(efile_dir, EFILE_DIR):
        raise ValueError("write 의 efile_dir 는 스킬의 efile 폴더만 받는다. 검증기 명령줄에 폴더 인자가 없어 "
                         "다른 폴더의 레이아웃·코드로 만든 파일은 같은 기준으로 검증할 수 없다")
    if _spec_locked(efile_dir):
        raise Locked(_lock_reason(efile_dir) or "규격판이 잠겨 있어 전자신고 파일을 만들지 않는다")
    name = file_name(rv, efile_dir)
    # 검증기는 스킬 폴더를 작업 폴더로 돈다. 파이썬 3.10·3.11 의 mkdtemp 는 dir 가 상대 경로면 상대 경로를 돌려주므로
    # 출력 폴더를 먼저 절대 경로로 바꾼다. 돌려주는 「경로」도 절대 경로다
    out_dir = os.path.abspath(out_dir)
    os.makedirs(out_dir, exist_ok=True)
    final = os.path.join(out_dir, name)
    if os.path.lexists(final):
        os.remove(final)
    warns = _sweep(out_dir)
    try:
        records, notes = build(rv, efile_dir)
    except BuildError as e:
        return {"경로": None, "검증": ["전자신고 레코드를 만들지 못했다. %s" % e], "파일명": name, "경고": warns}
    warns += notes
    work = tempfile.mkdtemp(prefix=TMP_PREFIX, dir=out_dir)
    left = None
    try:
        tmp = os.path.join(work, name)
        with open(tmp, "wb") as f:
            f.write(b"".join(r + CRLF for r in records))
        rv_path = os.path.join(work, "신고값.json")
        with open(rv_path, "w", encoding="utf-8") as f:
            json.dump(rv, f, ensure_ascii=False)
        fails, checked = _run_check(python, tmp, rv_path)
        warns += checked
        if not fails:
            os.replace(tmp, final)
    finally:
        left = _remove_work(work)
    if fails:
        return {"경로": None, "검증": fails + ([left] if left else []), "파일명": name, "경고": warns}
    return {"경로": final, "검증": [], "파일명": name, "경고": warns + ([left] if left else [])}
