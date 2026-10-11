# -*- coding: utf-8 -*-
"""신고값. 계획 1 결과(C4)·사실관계(C1)·신고인(C7, filing.load 통과본)으로 서식 란별 값과 전자신고 레코드 집계(C8)를 만든다.

서식 PDF(forms), 서식 검산(forms_check), 전자신고 생성기(efile), 입력 안내서(guide)가 이 결과를 읽는다.
세액은 엔진 결과를 옮기고 다시 계산하지 않는다. 예외는 넷이다.
  지방소득세 세율구분 열의 산출세액: 엔진은 합계만 내므로 합산 묶음마다 calc.rate_tax 로 구해 열에 나누고 합계와 대사한다.
  합산 비교세액이 이길 때 전자신고 03 행: 합계 산출세액을 세율구분 행에 과세표준 비율로 나눈다(규격서 p37 10번, p40).
    서식 본지·지방 열은 나누지 않는다. 세율구분 열은 엔진 세율별 값, 국내소계는 열 합, 합계만 비교세액(작성 사례 09).
  서식 ⑨ 세율 표기: 열 과세표준이 속한 구간 세율(forms/서식판.json 「본지_세율표기」).
  전자신고세액공제·분납: 규칙세트 값(T4).
인적사항(성명, 주민등록번호, 주소, 전화, 양수인)은 신고인·양수인·신고 절에만 둔다. 예외는 부표1·05 소재지(지번)와 부표3·07
매입가액 행 상호(신고인 JSON 자산[id].취득상대방, 매도인 성명)다. 이 값은 입력 안내서·검토 문서·MCP 응답에 옮기지 않는다
(global.md 「신고값 인적 성격 값」). 신고값 파일은 통째로 인적사항 파일로 다룬다(C8). 확인사항에는 값을 싣지 않는다.

전자신고 행의 키는 efile/layout_c116300.json 필드 name 그대로다(자료구분·서식코드·공란 제외). 다른 점은 아래뿐이다.
  05 계산명세: 「자산」(자산 id)을 더 싣는다.
  07 필요경비명세: 07-3 은 「일련번호」, 07-4(5자리) 는 「전자코드」, 07-7 은 「사업자번호」 키에 둔다.
     「구분코드」는 부표3 과 같은 서식 3자리 코드다. 「자산」(자산 id)을 더 싣는다.
일련번호는 정수, 비율(RATE) 칸은 소수 자리를 맞춘 백분율 문자열("38.00"), 금액은 원 단위 정수다.
"""
import copy
import hashlib
import json
import os
import re
from collections import namedtuple
from decimal import ROUND_DOWN, Decimal

from yangdo import SKILL_DIR, calc, filing, ruleset
from yangdo import bjd as bjd_mod
from yangdo.dates import to_date

FORMS_DIR = os.path.join(SKILL_DIR, "forms")
EFILE_DIR = os.path.join(SKILL_DIR, "efile")
SKIP_FIELDS = ("자료구분", "서식코드", "공란")
SHORT = ("1년미만", "2년미만")

ACQ_LABEL = {"실지거래가액": "실지거래가액", "매매사례가액": "매매사례가액", "감정가액": "감정가액", "환산가액": "환산취득가액"}

# 필요경비 항목 → codes_c116300.json["필요경비구분"] 의 키. 계획 1 M09 선택지는 코드로, 자유 글은 낱말로 고른다.
# 묶음을 서식 부표3 의 칸 이름에 맞췄다: 발코니·샷시는 「용도변경·개량·이용편의」, 보일러·냉난방은 「엘리베이터·냉난방 설치」,
# M09 「그 밖의 가치 증가 공사」(기타가치증가)는 「자산가치 증가 등 수선비」.
CAPEX_CODE = {
    "발코니확장": "자본적지출_용도변경개량", "샷시": "자본적지출_용도변경개량", "용도변경개조": "자본적지출_용도변경개량",
    "보일러": "자본적지출_엘리베이터냉난방", "승강기냉난방": "자본적지출_엘리베이터냉난방",
    "재해복구": "자본적지출_재해원상복구", "기타가치증가": "자본적지출_가치증가수선비",
}
# 자유 글 내용에 낱말이 있으면 그 코드. 앞에서부터 처음 맞는 것을 쓴다
WORD_CODE = {
    "취득부대": [("법무", "법무사비용"), ("등기", "법무사비용"), ("중개", "취득중개수수료")],
    "자본적지출": [("피난", "자본적지출_피난시설"), ("엘리베이터", "자본적지출_엘리베이터냉난방"),
              ("승강기", "자본적지출_엘리베이터냉난방"), ("냉난방", "자본적지출_엘리베이터냉난방"),
              ("재해", "자본적지출_재해원상복구"), ("용도변경", "자본적지출_용도변경개량"), ("개량", "자본적지출_용도변경개량"),
              ("확장", "자본적지출_용도변경개량"), ("부담금", "개발부담금재건축부담금")],
    "기타": [("수익자", "수익자부담금"), ("부담금", "개발부담금재건축부담금"), ("변호사", "취득후쟁송_변호사비용"),
           ("소송", "취득후쟁송_기타소송화해비용"), ("화해", "취득후쟁송_기타소송화해비용"), ("쟁송", "취득후쟁송_기타소송화해비용"),
           ("철거", "토지장애철거비"), ("도로", "도로시설비"), ("사방", "사방사업소요비용")],
    "양도비": [("채권", "채권매각차손등")],
}
FALLBACK_CODE = {"취득부대": "기타부대비용", "자본적지출": "자본적지출_기타", "기타": "기타비용_기타", "양도비": "양도중개수수료등"}
# 07 행에서 레이아웃 name 과 다르게 쓰는 키(레이아웃 name → 신고값 키)
EXPENSE_RENAMES = {"필요경비신고자료일련번호": "일련번호", "구분코드": "전자코드", "사업자등록번호": "사업자번호"}


class Unsupported(Exception):
    """신고 범위가 아니다(기신고 합산, 신고기한이 다른 예정신고 등). 계획은 그 범위를 다룰 계획 번호, 「없음」은 계획 없음."""

    def __init__(self, message, 계획="5"):
        super().__init__(message)
        self.계획 = 계획


def _read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _ymd(s):
    return s.replace("-", "") if s else ""


def _int(x):
    return int(x or 0)


def _bracket(base, table):
    """누진세율표에서 과세표준이 속한 구간의 세율. calc.progressive 와 같은 구간 고르기."""
    row = table[0]
    for r in table:
        if base > r[0]:
            row = r
    return row[2]


def _pct(rate):
    """세율 Decimal → 서식 표기 「38%」, 「3.8%」."""
    if rate is None:
        return ""
    return format((Decimal(rate) * 100).normalize(), "f") + "%"


def _rate_field(rate, dec=2):
    """세율 Decimal → 전자신고 RATE 칸 백분율 문자열(소수 dec 자리). None 이면 0."""
    q = Decimal(1).scaleb(-dec)
    return str((Decimal(rate or 0) * 100).quantize(q))


def _allocate(total, bases):
    """총액을 과세표준 비율로 나눈다. 원 미만은 버리고, 남는 원은 과세표준이 가장 큰 칸(같으면 앞 칸)에 더한다."""
    if not bases:
        return []
    whole = sum(bases)
    if not whole:
        return [total] + [0] * (len(bases) - 1)
    parts = [total * b // whole for b in bases]
    top = max(range(len(bases)), key=lambda j: (bases[j], -j))
    parts[top] += total - sum(parts)
    return parts


def _area(v):
    """면적을 소수 셋째 자리까지(아래는 버림) float 로. 전자신고 면적 칸이 NUMBER(11,3) 이다."""
    if v is None:
        return 0.0
    return float(Decimal(str(v)).quantize(Decimal("0.001"), rounding=ROUND_DOWN))


def load_codes(efile_dir=None):
    """전자신고 코드표(efile/codes_c116300.json). filing 의 질문 F07 이 필수 구분코드를 볼 때도 같은 표를 쓴다."""
    return _read_json(os.path.join(efile_dir or EFILE_DIR, "codes_c116300.json"))


def expense_key(group, item):
    """필요경비 항목이 가는 codes["필요경비구분"] 의 키. 계획 1 M09 선택지는 코드로, 자유 글은 낱말로 고른다."""
    text = str(item.get("내용") or "")
    if group == "자본적지출" and text in CAPEX_CODE:
        return CAPEX_CODE[text]
    for word, key in WORD_CODE.get(group, []):
        if word in text:
            return key
    return FALLBACK_CODE[group]


# 부표3·07 행이 되는 지출 하나. group 은 매입가액 · 취득세 · 취득부대 · 감가상각비 · 자본적지출 · 기타 · 양도비,
# key 는 codes["필요경비구분"] 의 키, item 은 사실관계 필요경비 항목(매입가액 · 취득세 · 감가상각비는 항목이 없어 None),
# no 는 그 항목이 사실관계 묶음 목록에서 몇 번째인지(1부터, 엔진이 뺀 항목도 센다. 항목이 없으면 0)
ExpenseLine = namedtuple("ExpenseLine", "group key item no")


def expense_lines(a, c):
    """한 자산에서 부표3·07 행이 되는 지출 목록(정렬 전 순서). a 는 사실관계 자산, c 는 엔진 계산(result["계산"]["자산"][i]["계산"]).

    어느 지출이 어느 구분코드 행이 되는지, 매입가액 행이 언제 생기는지를 정하는 한 곳이다. 신고값 생성과 filing 의 질문
    F07(지급처 사업자번호)·F08(취득 상대방)이 같은 규칙을 쓴다.
    실지거래가액이면 매입가액 · 취득세 · 취득부대 · 감가상각비 · 자본적지출 · 기타 · 양도비가 모두 줄이 된다. 환산취득가액을
    쓰되 자본적지출·양도비를 필요경비로 하는 경우(취득가액 0, 소득세법 제97조②2호 단서)는 그 둘만 줄이 된다.
    전액 비과세(취득가액 None)와 그 밖의 방법은 줄이 없다. 엔진이 필요경비에서 뺀 지출(calc.drop_reason)은 줄이 아니다.
    """
    if c["취득가액"] is None:
        return []
    ex = a.get("필요경비") or {}

    def items(groups):
        return [ExpenseLine(g, expense_key(g, it), it, n) for g in groups
                for n, it in enumerate(ex.get(g) or [], 1) if not calc.drop_reason(g, it)]

    method = c["취득가액방법"]
    if method == "실지거래가액":
        lines = [ExpenseLine("매입가액", "매입가액", None, 0)]
        if _int(ex.get("취득세")):
            lines.append(ExpenseLine("취득세", "취득세", None, 0))
        lines += items(("취득부대",))
        if _int(a.get("감가상각비")):
            lines.append(ExpenseLine("감가상각비", "감가상각비", None, 0))
        return lines + items(("자본적지출", "기타", "양도비"))
    if c["취득가액"] == 0 and method == "환산가액":
        return items(("자본적지출", "양도비"))
    return []


class _Builder:
    def __init__(self, result, facts, filer, rules_dir, forms_dir, efile_dir):
        self.result, self.facts, self.filer = result, facts, filer
        self.calc = result["계산"]
        self.rs = ruleset.load(rules_dir)
        self.rules_dir = rules_dir
        self.forms_dir = forms_dir or FORMS_DIR
        self.efile_dir = efile_dir or EFILE_DIR
        self.codes = load_codes(self.efile_dir)
        self.layout = _read_json(os.path.join(self.efile_dir, "layout_c116300.json"))
        self.form_reg_path = os.path.join(self.forms_dir, "서식판.json")
        self.form_reg = _read_json(self.form_reg_path)
        self.assets = {a["id"]: a for a in facts.get("자산") or []}
        self.lots = filer.get("자산") or {}
        self.notes = []
        self._bjd = None
        self.special = self.codes["세율별특수행"]           # 03 국내 소계·합계 행의 (국내외분, 세율구분)

    # ------------------------------------------------------------ 공통

    def note(self, text):
        if text not in self.notes:
            self.notes.append(text)

    @property
    def bjd(self):
        if self._bjd is None:
            self._bjd = bjd_mod.load(self.efile_dir, self.rules_dir)
        return self._bjd

    def record(self, no, values, renames=None, extra=()):
        """레이아웃 필드 순서로 행을 만든다. 없는 칸은 수치 0(비율은 0.00), 문자 공란. 모르는 키가 있으면 오류."""
        renames = renames or {}
        out = {}
        for fld in self.layout["레코드"][no]["필드"]:
            if fld["name"] in SKIP_FIELDS:
                continue
            key = renames.get(fld["name"], fld["name"])
            if key in values:
                out[key] = values[key]
            elif fld["type"] == "N":
                out[key] = _rate_field(0, fld["dec"]) if fld["class"] == "RATE" else 0
            else:
                out[key] = ""
        unknown = set(values) - set(out) - set(extra)
        if unknown:
            raise ValueError("레코드 %s 에 없는 칸: %s" % (no, ", ".join(sorted(unknown))))
        for k in extra:
            out[k] = values.get(k)
        return out

    @staticmethod
    def col_key(row):
        c = row["계산"]["코드"]
        return c["국내외분"], c["세율구분"]

    # ------------------------------------------------------------ 신고

    def filing_section(self):
        s = self.filer.get("신고") or {}
        kind = s.get("구분")
        cd = self.codes
        if kind not in cd["신고구분"]:
            raise ValueError("신고.구분(예정 또는 확정)이 없어 신고값을 만들 수 없다")
        made = s.get("작성일")
        if not made:
            raise ValueError("신고.작성일이 없어 신고값을 만들 수 없다")
        rows = self.calc["자산"]
        sold = [r["판정"]["양도일"] for r in rows]
        last = max(sold)
        if to_date(made) < to_date(last):
            raise ValueError("신고.작성일 %s 이 양도일 %s 보다 앞선다" % (made, last))
        if kind == "확정" and (self.facts.get("연간") or {}).get("기신고"):    # 수집 전용 키(facts.COLLECT_ONLY)
            raise Unsupported("확정신고에 같은 해 예정신고분(기신고)을 합산하는 신고는 계획 5 에서 다룬다", "5")
        if kind == "예정" and len({d[:7] for d in sold}) > 1:
            raise Unsupported("예정신고는 신고기한(양도월 말일부터 2개월)이 같은 양도건끼리 한다. 양도월이 다른 자산(%s)은 따로 신고한다"
                              % ", ".join("%s %s" % (r["id"], r["판정"]["양도일"]) for r in rows), "없음")
        if any(self.col_key(r)[0] != self.special["국내소계"]["국내외분"] for r in rows):
            raise Unsupported("국외 자산 신고는 다루지 않는다", "없음")
        if kind == "예정" and any((self.assets.get(r["id"]) or {}).get("토지거래허가대상") == "예" for r in rows):
            self.note("토지거래허가대상 자산이 있다. 허가 전에 대금을 청산했으면 예정신고 유형이 3(토지거래허가구역 안 토지)이고 "
                      "신고기한이 허가일 기준이다. 신고유형 1 로 두었으니 확인한다(규격서 p26)")
        if kind == "확정":    # 기신고가 있으면 위에서 Unsupported 이므로 여기 오는 확정신고는 예정신고를 하지 않은 것이다
            self.note("예정신고를 하지 않은 확정신고에는 예정신고 무신고가산세와 납부지연가산세가 붙는다. 이 신고값은 가산세를 "
                      "계산하지 않아 0 으로 두었으므로 납부할 세액이 실제보다 적다. 가산세는 신고 전에 따로 계산해 더한다")
        self.kind, self.made, self.last_sold = kind, made, last
        return {"구분": kind, "구분코드": cd["신고구분"][kind]["코드"], "상세코드": cd["신고구분상세"]["정기"]["코드"],
                "유형": cd["신고유형"][kind]["코드"], "과세기간": last[:4] + "01", "귀속연도": last[:4],
                "서식종류": cd["서식종류"][kind]["코드"], "작성일": _ymd(made), "제출년월": _ymd(made)[:6],
                "양도일자": _ymd(last), "홈택스ID": s.get("홈택스ID"), "분납신청": s.get("분납신청") is True}

    # ------------------------------------------------------------ 신고인·양수인

    def dong(self, addr, where, qid):
        code = filing.dong_code(addr, bjd=self.bjd, on=self.made)
        if not code:
            self.note("%s 법정동코드를 정하지 못했다. 신고인 JSON 에 10자리로 적는다(질문 %s)" % (where, qid))
        return code

    def filer_section(self):
        p = copy.deepcopy(self.filer.get("신고인") or {})
        addr = p.get("주소") or {}
        addr["법정동코드"] = self.dong(addr, "신고인 주소의", "F01") if addr else None
        if not addr:
            self.note("신고인 주소가 없다(질문 F01)")
        p["주소"] = addr
        cd = self.codes
        country = p.get("거주지국")
        p["코드"] = {"내외국인여부": (cd["내외국인여부"].get(p.get("내외국인")) or {}).get("코드"),
                    "거주구분": (cd["거주구분"].get(p.get("거주구분")) or {}).get("코드"),
                    "거주지국": country, "거주지국명": (cd["국가"].get(country) or {}).get("이름"),
                    "국적": p.get("국적")}
        return p

    def buyers_section(self):
        order = {r["id"]: i for i, r in enumerate(self.calc["자산"])}
        buyers = sorted(self.filer.get("양수인") or [], key=lambda b: order.get(b.get("자산"), len(order)))
        out = []
        for i, b in enumerate(buyers, 1):
            rel = (self.assets.get(b.get("자산")) or {}).get("매수인관계")
            code = (self.codes["양수인관계"].get(rel) or {}).get("코드") or b.get("관계코드")
            if not code:
                self.note("%s: 양수인 %d번째의 관계코드가 없다(질문 F02, 규격서 p107~109)" % (b.get("자산"), i))
            share = b.get("지분") or {}
            out.append({"자산": b.get("자산"), "일련번호": i, "구분": b.get("구분"), "내외국인": b.get("내외국인"),
                        "번호": b.get("번호"), "성명": b.get("성명"), "전화": b.get("전화"),
                        "지분분자": share.get("분자"), "지분분모": share.get("분모"), "관계": code, "관계표기": rel})
        if not out:
            self.note("양수인이 없다(질문 F02)")
        return out

    # ------------------------------------------------------------ 부표1·부표3·05·07

    def place(self, a, lot, code):
        name = self.bjd.name(code) if code else None
        if not name:
            loc = a.get("소재지") or {}
            name = " ".join(loc.get(k) for k in ("시도", "시군구", "읍면동") if loc.get(k))
        lot = lot or {}
        parts = [name]
        no = lot.get("번지")
        if no and no != "0":
            no = ("산 " if lot.get("특수지") == "1" else "") + no
            if lot.get("호") and lot["호"] != "0":
                no += "-" + lot["호"]
            parts.append(no)
        for k, unit in (("아파트명", ""), ("아파트동", "동"), ("아파트호", "호")):
            v = lot.get(k)
            if v:
                parts.append(v if (not unit or v.endswith(unit)) else v + unit)
        return " ".join(p for p in parts if p)

    def registry(self, aid, side, a, lot):
        """(등기목적, 등기원인). 신고인 JSON 자산[id].등기목적·등기원인 이 있으면 그것, 없으면 codes 기본값."""
        cause = (a.get(side) or {}).get("원인")
        where = "자산.%s" % aid
        over_p = (lot or {}).get("등기목적") or {}
        over_c = (lot or {}).get("등기원인") or {}
        if not isinstance(over_p, dict) or set(over_p) - {"취득", "양도"}:
            raise filing.FilingError("%s.등기목적: {\"취득\": \"A1ZZAZ\"} 처럼 취득이나 양도 쪽 키로 적는다" % where)
        purposes, causes = self.codes["등기목적목록"], self.codes["등기원인목록"]
        p_entry = self.codes[side + "등기목적"].get(cause) or {}
        c_entry = self.codes[side + "등기원인"].get(cause) or {}
        purpose = over_p.get(side) or p_entry.get("코드")
        if over_p.get(side) and over_p[side] not in purposes:
            raise filing.FilingError("%s.등기목적.%s: 규격서 p109 의 6자리 등기목적 코드(%s)로 적는다"
                                     % (where, side, ", ".join(purposes)))
        no_cause = purpose in self.codes["등기원인생략목적"]["코드"]   # 소유권보존이면 등기원인을 적지 않는다(규격서 p49)
        if no_cause:
            reg = ""
        else:
            reg = over_c.get(side) or c_entry.get("코드")
            allowed = causes.get(purpose) or {}
            if over_c.get(side) and allowed and over_c[side] not in allowed:
                raise filing.FilingError("%s.등기원인.%s: 등기목적 %s 에 쓰는 등기원인 코드가 아니다(규격서 p109~110)"
                                         % (where, side, purpose))
        if not over_p.get(side) and p_entry.get("확인"):
            self.note("%s: %s 원인 %s 의 등기목적 기본값 %s(%s)를 썼다. %s"
                      % (aid, side, cause, purpose, p_entry.get("이름"), p_entry["확인"]))
        if not no_cause and not over_c.get(side) and c_entry.get("확인"):
            self.note("%s: %s 원인 %s 의 등기원인 기본값 %s(%s)를 썼다. %s"
                      % (aid, side, cause, reg, c_entry.get("이름"), c_entry["확인"]))
        if not purpose:
            self.note("%s: %s 원인 %s 의 등기목적 코드를 정하지 못했다. 신고인 JSON %s.등기목적.%s 에 6자리로 적는다"
                      % (aid, side, cause, where, side))
        if reg is None:
            self.note("%s: %s 원인 %s 의 등기원인 코드를 정하지 못했다. 신고인 JSON %s.등기원인.%s 에 4자리로 적는다(질문 F04)"
                      % (aid, side, cause, where, side))
        return purpose, reg

    def schedule3_row(self, key, amount, date="", partner="", evidence=None, biz=""):
        e = self.codes["필요경비구분"][key]
        ev = (self.codes["증빙종류"].get(evidence) or {}).get("코드") if evidence else None
        return {"구분코드": e["코드"], "전자코드": e["전자코드"], "구분": e["이름"], "상호": partner or "", "사업자번호": biz or "",
                "지급일": date or "", "금액": amount, "증빙코드": ev or "", "_필수": e["필수"], "_묶음": e["묶음"]}

    def biz_no(self, aid, it):
        """필요경비 항목의 사업자번호(사실관계 선택 키, 10자리 숫자). 모양이 틀리면 빈 글자와 확인사항."""
        v = it.get("사업자번호")
        if v in (None, ""):
            return ""
        if not (isinstance(v, str) and re.fullmatch(r"[0-9]{10}", v)):
            self.note("%s: 필요경비 %s 의 사업자번호가 숫자 10자리가 아니라 비웠다" % (aid, it.get("내용")))
            return ""
        if not filing.biz_ok(v):
            self.note("%s: 필요경비 %s 의 사업자번호 검증번호가 맞지 않는다. 다시 확인한다" % (aid, it.get("내용")))
        return v

    def seller(self, aid, lot):
        """매입가액(111·11101) 행의 거래상대방. 신고인 JSON 자산[id].취득상대방(성명 또는 상호). 없으면 빈 글자."""
        v = (lot or {}).get("취득상대방")
        if v in (None, ""):
            return ""
        if not isinstance(v, str) or not filing.ksx1001_ok(v) or len(v.encode("cp949")) > 60:
            raise filing.FilingError("자산.%s.취득상대방: 전자신고 파일(KS X 1001 완성형)로 쓸 수 있는 60바이트 이내 글자로 적는다" % aid)
        return v

    def tax_office(self, a):
        """취득세(112·11201) 행의 거래상대방. 취득세 납세지는 부동산 소재지다(지방세법 제8조①1호). 취득 당시 소재지가 있으면 그것."""
        loc = a.get("취득당시소재지") or a.get("소재지") or {}
        return " ".join(loc.get(k) for k in ("시도", "시군구") if loc.get(k))

    def expense_rows(self, aid, a, v, c):
        """(부표3 행, 부표1 취득가액, 부표1 기타필요경비). 부표3 은 실지거래가액 자산과, 환산취득가액 대신 자본적지출·양도비를
        필요경비로 한 자산(소득세법 제97조②2호 단서)만 쓴다. 엔진이 뺀 지출(calc.drop_reason)은 넣지 않는다."""
        if c["취득가액"] is None:                        # 전액비과세
            return [], None, None
        ex = a.get("필요경비") or {}
        method = c["취득가액방법"]
        rows = []
        for ln in expense_lines(a, c):
            it = ln.item
            if ln.group == "매입가액":
                rows.append(self.schedule3_row("매입가액", c["취득가액"] + _int(a.get("감가상각비")), v["취득일"],
                                               self.seller(aid, self.lots.get(aid))))
            elif ln.group == "취득세":
                rows.append(self.schedule3_row("취득세", _int(ex.get("취득세")), partner=self.tax_office(a)))
                self.note("%s: 07 레코드 취득세(11201) 행 상호는 취득세 납세지인 부동산 소재지 시군구 이름으로 적었다"
                          "(지방세법 제8조①1호, 규격서 p60 「거래상대방의 상호」)" % aid)
            elif ln.group == "감가상각비":
                rows.append(self.schedule3_row("감가상각비", _int(a.get("감가상각비"))))
            else:
                rows.append(self.schedule3_row(ln.key, _int(it.get("금액")), it.get("지급일"), it.get("상대방"),
                                               it.get("증빙종류"), self.biz_no(aid, it)))
        rows.sort(key=lambda x: x["전자코드"])
        # 부표3 ⑤ 계 = ①+③-④ 또는 ②+③-④, ⑬ 기타 필요경비 계 = ⑨+⑫(codes 필요경비구분 묶음)
        acq = sum(x["금액"] for x in rows if x["_묶음"].startswith("취득가액") and "차감항목" not in x["_묶음"]) \
            - sum(x["금액"] for x in rows if "차감항목" in x["_묶음"])
        other = sum(x["금액"] for x in rows if x["_묶음"].startswith("기타필요경비"))
        if method == "실지거래가액":
            if acq + other != c["취득가액"] + c["필요경비"]:
                raise ValueError("%s: 부표3 합계 %s원이 엔진 취득가액·필요경비 합 %s원과 다르다"
                                 % (aid, acq + other, c["취득가액"] + c["필요경비"]))
            return rows, acq, other
        if rows and other != c["필요경비"]:
            raise ValueError("%s: 부표3 기타필요경비 %s원이 엔진 필요경비 %s원과 다르다" % (aid, other, c["필요경비"]))
        return rows, c["취득가액"], c["필요경비"]

    def years_text(self, n):
        """햇수 n → 「n년 이상 n+1년 미만」. 0 은 「1년 미만」, 10 이상은 「10년 이상」(05-64·65 코드와 같은 눈금)."""
        rule = self.form_reg["부표1_기간표기"]
        if n >= 10:
            return rule["끝"]
        if n <= 0:
            return rule["처음"]
        return rule["형식"].format(n=n, n1=n + 1)

    def period_text(self, code):
        if code is None or code in self.form_reg["부표1_기간표기"]["빈칸"]:
            return ""
        return self.years_text(int(code))

    def residence_text(self, code, a, v):
        """⑩ 거주기간. 거주 코드가 Z1·Z2(거주요건 해당없음)여도 거주한 구간이 있으면 거주년을 적는다(국세청 작성 사례 03)."""
        if code in self.form_reg["부표1_기간표기"]["거주로채움"] and a.get("거주기간"):
            return self.years_text(v["거주년"])
        return self.period_text(code)

    def standard_prices(self, aid, a, c):
        """(서식 기준시가, 전자신고 기준시가). 환산취득가액으로 신고할 때만 적는다(부표1 기준시가 머리글, 규격서 p49·p52)."""
        keys = ("양도_건물", "양도_토지", "양도_합계", "취득_건물", "취득_토지", "취득_합계")
        form = dict.fromkeys(keys, 0)
        ef = {}
        sides = (("양도", "양도시기준시가"), ("취득", "취득시기준시가"))
        for side, head in sides:
            for k in ("건물_일반건물", "건물_오피스텔,상업용", "건물_개별,공동주택", "토지", "합계"):
                ef["%s_%s" % (head, k)] = 0
        if c.get("취득가액방법") != "환산가액":
            return form, ef
        bs = a.get("기준시가") or {}
        for side, head in sides:
            d = bs.get(side) or {}
            house, bldg, land = _int(d.get("주택")), _int(d.get("건물")), _int(d.get("토지"))
            form.update({side + "_건물": house + bldg, side + "_토지": land, side + "_합계": house + bldg + land})
            ef.update({head + "_건물_일반건물": bldg, head + "_건물_개별,공동주택": house, head + "_토지": land,
                       head + "_합계": house + bldg + land})
            if bldg:
                self.note("%s: %s 당시 건물 기준시가를 일반건물 칸(05-%s)에 넣었다. 오피스텔·상업용 건물이면 그 칸(05-%s)으로 옮긴다"
                          % (aid, side, "46" if side == "양도" else "51", "47" if side == "양도" else "52"))
        return form, ef

    def asset(self, n, row):
        aid, v, c = row["id"], row["판정"], row["계산"]
        code = c["코드"]
        a = self.assets.get(aid)
        if a is None:
            raise ValueError("결과의 자산 %s 가 사실관계에 없다" % aid)
        lot = self.lots.get(aid)
        if lot is None:
            self.note("%s: 신고인 JSON 자산에 이 자산의 지번이 없다(질문 F04)" % aid)
        given = (lot or {}).get("법정동코드")
        dcode = self.dong(dict(a.get("소재지") or {}, 법정동코드=given), "%s: 소재지의" % aid, "F04")
        # 면적: 공동소유면 신고인 JSON 총면적(전체 면적), 없으면 사실관계 면적
        total = (lot or {}).get("총면적") or a.get("면적") or {}      # 면적은 수집 전용 키(facts.COLLECT_ONLY), 서식 기재용
        if not total:
            self.note("%s: 면적이 없어 면적 칸을 0 으로 두었다(질문 A20)" % aid)
        j = a.get("지분") or "단독"
        num, den = (j["분자"], j["분모"]) if isinstance(j, dict) and j.get("구분") == "공동" else (1, 1)
        share = Decimal(str(num)) / Decimal(str(den))
        tot_l, tot_b = _area(total.get("토지")), _area(total.get("건물"))
        sold_l, sold_b = _area(Decimal(str(tot_l)) * share), _area(Decimal(str(tot_b)) * share)

        rows, acq, other = self.expense_rows(aid, a, v, c)
        for why in c.get("필요경비_제외") or []:
            self.note("%s: 필요경비에서 뺀 지출이라 부표3·07 레코드에 넣지 않았다. %s" % (aid, why))
        form_bs, ef_bs = self.standard_prices(aid, a, c)
        p_purpose, p_cause = self.registry(aid, "양도", a, lot)
        a_purpose, a_cause = self.registry(aid, "취득", a, lot)
        ltd_codes = self.form_reg["부표1_장특공코드"]["코드"]
        표2 = v["장특공"] == "표2"
        kind = code["자산종류"]
        sheet1 = {
            "자산": aid, "세율구분표기": "%s-%s" % (code["국내외분"], code["세율구분"]),
            "소재지국": self.codes["소재지국"]["국내"]["이름"], "소재지": self.place(a, lot, dcode), "부동산고유번호": "",
            "자산종류": kind.lstrip("0") or "0",
            "양도일": v["양도일"], "양도원인": (a.get("양도") or {}).get("원인"),
            "취득일": v["취득일"], "취득원인": (a.get("취득") or {}).get("원인"),
            "총면적_토지": tot_l, "총면적_건물": tot_b, "지분분자": num, "지분분모": den,
            "양도면적_토지": sold_l, "양도면적_건물": sold_b, "취득면적_토지": sold_l, "취득면적_건물": sold_b,
            "보유기간": self.period_text(code["보유기간"]), "거주기간": self.residence_text(code["거주기간"], a, v),
            "양도가액": c["양도가액"], "취득가액": acq, "취득가액종류": ACQ_LABEL.get(c["취득가액방법"], ""),
            "토초세": 0, "기타필요경비": other, "양도차익": c["양도차익"], "비과세양도차익": c["비과세양도차익"],
            "과세양도차익": c["과세양도차익"], "장특공": c["장특공"], "장특공코드": ltd_codes[v["장특공"]],
            "장특공거주기간": self.years_text(v["거주년"]) if 표2 else "",
            "양도소득금액": c["양도소득금액"], "감면소득금액": 0, "감면종류": "", "감면율": 0, "기준시가": form_bs,
        }
        sheet3 = None
        exp_rows = []
        if rows:
            sheet3 = {"자산": aid, "행": [{k: x[k] for k in x if not k.startswith("_")} for x in rows],
                      "취득가액계": acq, "기타필요경비계": other}
            missing_name = [x["전자코드"] for x in rows if not x["상호"]]
            if missing_name:
                self.note("%s: 07 레코드 상호는 Not Null 인데(규격서 p59~60) %s 행의 거래상대방 상호가 없어 비웠다. "
                          "매입가액 행은 신고인 JSON 자산[id].취득상대방(매도인 성명 또는 상호), 나머지 행은 사실관계 필요경비 상대방에 적는다"
                          % (aid, ", ".join(missing_name)))
            need_date = [x["전자코드"] for x in rows if x["_필수"] and x["금액"] and not x["지급일"]]
            if need_date:
                self.note("%s: 07 레코드 %s 행은 지급금액이 있으면 지급일자가 필수인데(규격서 p60) 없어 비웠다. "
                          "사실관계 필요경비 항목의 지급일에 적는다" % (aid, ", ".join(need_date)))
            need_biz = [x["전자코드"] for x in rows if x["_필수"] and x["금액"] and not x["사업자번호"]]
            if need_biz:
                self.note("%s: 07 레코드 %s 행은 지급금액이 있으면 사업자번호가 필수인데(규격서 p60) 없어 비웠다. "
                          "사실관계 필요경비 항목의 사업자번호(10자리)에 적는다" % (aid, ", ".join(need_biz)))
            for k, x in enumerate(rows, 1):
                must = x["_필수"]
                exp_rows.append(self.record("07", {
                    "일련번호": n, "전자코드": x["전자코드"], "상세일련번호": k, "상호": x["상호"],
                    "사업자번호": x["사업자번호"] if must else "",
                    "지급일자": _ymd(x["지급일"]) if must else "", "지급금액": x["금액"],
                    "증빙종류코드": (x["증빙코드"] if must else self.codes["메타"]["증빙_필수아닌행"]["코드"]),
                    "구분코드": x["구분코드"], "자산": aid,
                }, renames=EXPENSE_RENAMES, extra=("구분코드", "자산")))
        lot = lot or {}
        calc05 = self.record("05", {
            "일련번호": n, "과세구분": code["과세구분"], "국내외분(소재지)": code["국내외분"], "세율구분": code["세율구분"],
            "자산의종류": kind, "소재지_법정동코드": dcode, "소재지_특수지코드": lot.get("특수지") or "0",
            "소재지_번지": lot.get("번지"), "소재지_호": lot.get("호") or "0", "소재지_아파트명": lot.get("아파트명") or "",
            "소재지_아파트동": lot.get("아파트동") or "", "소재지_아파트호": lot.get("아파트호") or "",
            "거래일자_양도일자": _ymd(v["양도일"]), "거래일자_양도등기목적": p_purpose, "거래일자_양도등기원인": p_cause,
            "거래일자_취득일자": _ymd(v["취득일"]), "거래일자_취득등기목적": a_purpose, "거래일자_취득등기원인": a_cause,
            "거래자산면적_총면적_토지_면적": tot_l, "거래자산면적_총면적_토지_지분(분자)": num,
            "거래자산면적_총면적_토지_지분(분모)": den, "거래자산면적_총면적_건물_면적": tot_b,
            "거래자산면적_총면적_건물_지분(분자)": num, "거래자산면적_총면적_건물_지분(분모)": den,
            "거래자산면적_양도면적_토지_면적": sold_l, "거래자산면적_양도면적_건물_면적": sold_b,
            "거래자산면적_취득면적_토지_면적": sold_l, "거래자산면적_취득면적_건물_면적": sold_b,
            "거래금액_양도가액": c["양도가액"], "거래금액_취득가액": acq or 0, "취득가액종류": code["취득가액종류"] or "",
            "기타필요경비": other or 0, "양도차익_전체양도차익": c["양도차익"] or 0,
            "양도차익_비과세양도차익": c["비과세양도차익"] or 0, "양도차익_과세대상양도차익": c["과세양도차익"],
            "장기보유특별공제": c["장특공"], "양도소득금액": c["양도소득금액"], "감면종류": code["감면종류"],
            "자동계산불러오기구분값": self.codes["자동계산불러오기구분"]["변환프로그램"]["코드"],
            "소재지국": self.codes["소재지국"]["국내"]["코드"], "소재지국명": self.codes["소재지국"]["국내"]["이름"],
            "필요경비신고자료일련번호": n if exp_rows else 0,
            "장기보유특별공제적용구분코드": code["장특공적용구분"], "주택거주기간년수": v["거주년"] if 표2 else 0,
            "1세대1주택비과세_보유기간": code["보유기간"], "1세대1주택_비과세_거주기간": code["거주기간"],
            "자산": aid, **ef_bs,
        }, extra=("자산",))
        return sheet1, sheet3, calc05, exp_rows

    # ------------------------------------------------------------ 본지·지방·03

    def applied_rate(self, members, base, local):
        """열에 쓰는 세율(Decimal). 합산 묶음이 둘 이상이면 None."""
        if not members or len({m["계산"]["합산묶음"] for m in members}) != 1:
            return None
        anchor = calc.group_anchor(members)
        v, c = anchor["판정"], anchor["계산"]
        on = to_date(v["양도일"])
        r = calc.rates(v, self.rs, on, local)
        if r["가산"] is None or c["세율종류"] in SHORT:
            return r["단일"]
        return _bracket(base, self.rs.value(("지방." if local else "") + "기본세율", on)) + r["가산"]

    def local_by_column(self, taxed):
        groups = {}
        for r in taxed:
            groups.setdefault(r["계산"]["합산묶음"], []).append(r)
        out = {}
        for members in groups.values():
            anchor = calc.group_anchor(members)
            base = sum(m["계산"]["과세표준"] for m in members)
            tax = calc.rate_tax(anchor["판정"], base, self.rs, to_date(anchor["판정"]["양도일"]), local=True)[0]
            k = self.col_key(anchor)
            out[k] = out.get(k, 0) + tax
        if sum(out.values()) != self.calc["합계"]["지방_호별합산"]:
            raise ValueError("지방소득세 세율구분별 합 %s원이 엔진 호별합산 %s원과 다르다"
                             % (sum(out.values()), self.calc["합계"]["지방_호별합산"]))
        return out

    @staticmethod
    def nat_column(income, deduct, base, rate, tax, credit, inst=0):
        due = tax - credit
        return {"양도소득금액": income, "기신고양도소득금액": 0, "감면소득금액": 0, "기본공제": deduct, "과세표준": base,
                "세율": rate, "산출세액": tax, "감면세액": 0, "외국납부": 0, "원천징수": 0, "연금계좌": 0,
                "전자신고공제": credit, "가산세": 0, "가산세_신고": 0, "가산세_납부": 0, "가산세_기장": 0, "기신고세액": 0,
                "납부할세액": due, "분납": inst, "신고기한내납부": due - inst}

    @staticmethod
    def local_column(base, rate, tax):
        return {"과세표준": base, "세율": rate, "산출세액": tax, "감면세액": 0, "외국납부": 0, "원천징수": 0, "연금계좌": 0,
                "전자신고공제": 0, "가산세": 0, "가산세_신고": 0, "가산세_납부": 0, "가산세_기타": 0, "기신고세액": 0,
                "납부할세액": tax, "신고기한내납부": tax}

    @staticmethod
    def split_credit(credit, cols, taxes):
        """전자신고세액공제를 세율구분 열(행)에 앞에서부터 산출세액만큼 나눈다(규격서 p43 36번)."""
        left, out = credit, {}
        for k in cols:
            out[k] = give = min(left, max(0, taxes[k]))
            left -= give
        return out

    def installment(self, due):
        """분납할 세액(소득세법 제112조, 시행령 제175조). 신고.분납신청이 참일 때만."""
        req = (self.filer.get("신고") or {}).get("분납신청")
        if req is None:
            self.note("신고.분납신청이 비어 있어 분납하지 않는 것으로 했다(질문 F03)")
        if req is not True:
            return 0
        base_amt = self.rs.value("분납.기준금액", self.last_sold)
        if due <= base_amt:
            return 0
        if due <= self.rs.value("분납.상한기준", self.last_sold):
            return due - base_amt
        return calc.floor(Decimal(due) * self.rs.value("분납.상한율", self.last_sold))

    @staticmethod
    def blank_payment(col, single, keys):
        """세율구분 열·국내소계의 납부 행. 열이 여럿이면 모두 비우고(국세청 확정신고 작성 사례 09), 하나면 납부할세액까지만
        적는다(예정신고 작성 사례 03·06·07·08 은 ⑰ 납부할 세액을 열에도 적고 ⑱ 분납·⑲ 납부세액은 합계에만 적었다)."""
        for k in keys if not single else keys[2:]:
            col[k] = None
        return col

    def main_forms(self):
        total = self.calc["합계"]
        taxed = [r for r in self.calc["자산"] if not r["판정"]["전액비과세"]]
        rate_rows = self.calc["세율별"]
        cols = [(x["국내외분"], x["세율구분"]) for x in rate_rows]
        bases = {k: x["과세표준"] for k, x in zip(cols, rate_rows)}
        members = {k: [r for r in taxed if self.col_key(r) == k] for k in cols}
        labels = [{"국내외분": d, "세율구분": s, "표기": "%s-%s" % (d, s)} for d, s in cols]
        single = len(cols) == 1
        for k, m in members.items():
            if len({r["계산"]["합산묶음"] for r in m}) > 1:
                self.note("세율구분 %s-%s 열에 합산 묶음이 둘 이상이라 세율 칸을 비웠다" % k)

        # 세율구분 열은 엔진 세율별 산출세액과 그 열의 적용 세율. 합산 비교세액이 이겨도 열은 그대로 두고 합계 열만 비교세액이다
        # (본지 작성방법 8, 국세청 확정신고 작성 사례 09: 1-47 열 12,045,000·35%, 1-10 열 196,272,000·42%, 국내분 소계는
        # 열 합 208,317,000, 합계 212,022,000, 합계·소계 ⑨ 공란)
        nat_tax = {k: x["산출세액"] for k, x in zip(cols, rate_rows)}
        loc_tax = self.local_by_column(taxed)
        nat_rate = {k: self.applied_rate(members[k], bases[k], False) for k in cols}
        loc_rate = {k: self.applied_rate(members[k], bases[k], True) for k in cols}
        merged_win = total["합산비교세액"] > total["호별합산세액"]
        local_win = total["지방_합산비교"] > total["지방_호별합산"]
        if merged_win:
            self.note("합산 비교 세액이 커서 합계 산출세액 %s원이 세율구분 열의 합 %s원과 다르다(소득세법 제104조⑤, 서식 작성방법 8)"
                      % (total["산출세액"], sum(nat_tax.values())))
        if local_win:
            self.note("지방소득세도 합산 비교 세액이 커서 합계 산출세액 %s원이 세율구분 열의 합 %s원과 다르다(별지40의11 작성방법 7)"
                      % (total["지방소득세"], sum(loc_tax.values())))

        # 전자신고세액공제(예정신고만, 기준일 신고일 = 작성일)와 분납
        rule = self.rs.value("전자신고세액공제.예정", self.made) if self.kind == "예정" else 0
        credit = min(rule, max(0, total["산출세액"]))
        col_credit = self.split_credit(credit, cols, nat_tax)
        inst = self.installment(total["산출세액"] - credit)

        nat_cols = {k: self.nat_column(sum(r["계산"]["양도소득금액"] for r in members[k]),
                                       sum(r["계산"]["기본공제"] for r in members[k]), bases[k], _pct(nat_rate[k]),
                                       nat_tax[k], col_credit[k]) for k in cols}
        loc_cols = {k: self.local_column(bases[k], _pct(loc_rate[k]), loc_tax[k]) for k in cols}
        nat_total_rate = nat_cols[cols[0]]["세율"] if single and not merged_win else ""
        loc_total_rate = loc_cols[cols[0]]["세율"] if single and not local_win else ""
        sum_nat = self.nat_column(sum(r["계산"]["양도소득금액"] for r in taxed), sum(r["계산"]["기본공제"] for r in taxed),
                                  total["과세표준"], nat_total_rate, total["산출세액"], credit, inst)
        sub_nat = self.nat_column(sum(c["양도소득금액"] for c in nat_cols.values()), sum(c["기본공제"] for c in nat_cols.values()),
                                  sum(bases.values()), nat_total_rate, sum(nat_tax.values()), sum(col_credit.values()))
        sum_loc = self.local_column(total["과세표준"], loc_total_rate, total["지방소득세"])
        sub_loc = self.local_column(sum(bases.values()), loc_total_rate, sum(loc_tax.values()))
        nat_pay = ("기신고세액", "납부할세액", "분납", "신고기한내납부")
        loc_pay = ("기신고세액", "납부할세액", "신고기한내납부")
        for c in list(nat_cols.values()) + [sub_nat]:
            self.blank_payment(c, single, nat_pay)
        for c in list(loc_cols.values()) + [sub_loc]:
            self.blank_payment(c, single, loc_pay)
        zero_nat = self.nat_column(0, 0, 0, "", 0, 0)
        zero_loc = self.local_column(0, "", 0)
        main = {"세율구분": labels, "열": dict([("합계", sum_nat), ("국내소계", sub_nat)]
                                         + [(l["표기"], nat_cols[(l["국내외분"], l["세율구분"])]) for l in labels]
                                         + [("국외소계", zero_nat)])}
        local = {"세율구분": copy.deepcopy(labels),
                 "열": dict([("합계", sum_loc), ("국내소계", sub_loc)]
                           + [(l["표기"], loc_cols[(l["국내외분"], l["세율구분"])]) for l in labels]
                           + [("국외소계", zero_loc)])}
        if total["지방소득세"]:
            self.note("지방소득세 전자신고세액공제(지방세특례제한법 제167조의3, 별지40의11 작성방법 11)는 규칙세트에 값이 없어 0 으로 두었다")
        return main, local, self.efile_rates(total, taxed, cols, bases, nat_rate, nat_tax, credit, inst, merged_win)

    def efile_rates(self, total, taxed, cols, bases, nat_rate, nat_tax, credit, inst, merged_win):
        """03 레코드: 국내 소계, 세율구분 행, 합계. 합계 행 = 세율구분 행 합이어야 해서(규격서 p37 10번) 합산 비교세액이 이기면
        합계 산출세액을 세율구분 행에 과세표준 비율로 나눈다(p40). 세율 칸은 행의 적용 세율(p37 9번), 00 행은 0."""
        if merged_win:
            tax = dict(zip(cols, _allocate(total["산출세액"], [bases[k] for k in cols])))
            self.note("전자신고 03 레코드는 합계 행 산출세액이 세율구분 행 합과 같아야 해서(규격서 p37 10번, p40) 합산 비교세액을 "
                      "세율구분 행에 과세표준 비율로 나눠 적었다. 원 미만은 버리고 남는 원은 과세표준이 가장 큰 행에 더했다")
        else:
            tax = dict(nat_tax)
        row_credit = self.split_credit(credit, cols, tax)
        fields = {f["name"]: f for f in self.layout["레코드"]["03"]["필드"]}
        resident = fields["주민세_세율"]                 # 합계 행만 점검값 01000(10.00%), 나머지 행 0(규격서 p43 31번)
        q = Decimal(1).scaleb(-resident["dec"])
        resident_rate = str(Decimal(resident["check"]).scaleb(-resident["dec"]).quantize(q))
        sub, tot = self.special["국내소계"], self.special["합계"]

        def row(d, s, income, deduct, base, rate, t, cr, last):
            due = t - cr
            return self.record("03", {
                "국내외분": d, "세율구분": s, "양도소득금액": income, "양도소득기본공제": deduct, "과세표준": base,
                "세율": _rate_field(rate, fields["세율"]["dec"]), "산출세액": t, "자진납부할세액": due,
                "분납할세액": inst if last else 0, "자진납부세액": due - inst if last else 0, "전자신고세액공제": cr,
                "주민세_세율": resident_rate if last else _rate_field(0, resident["dec"]),
            })

        income = {k: sum(r["계산"]["양도소득금액"] for r in taxed if self.col_key(r) == k) for k in cols}
        deduct = {k: sum(r["계산"]["기본공제"] for r in taxed if self.col_key(r) == k) for k in cols}
        allsum = (sum(income.values()), sum(deduct.values()), sum(bases.values()), None, sum(tax.values()), credit)
        rows = ([row(sub["국내외분"], sub["세율구분"], *allsum, False)]
                + [row(k[0], k[1], income[k], deduct[k], bases[k], nat_rate[k], tax[k], row_credit[k], False) for k in cols]
                + [row(tot["국내외분"], tot["세율구분"], *allsum, True)])
        rows.sort(key=lambda x: (x["국내외분"], x["세율구분"]))
        self.note("전자신고 03 레코드에 국내 소계 행(국내외분 1, 세율구분 00)을 넣었다(규격서 p32). 03-31 주민세_세율은 합계 행만 "
                  "10.00(점검값 01000), 나머지 행은 0 이다(p43 31번). 농어촌특별세가 없어 03-23 세율은 0 이다(p42 은 세율 행에 20%). "
                  "셋 다 홈택스 형식검증으로 확인한다")
        return rows

    # ------------------------------------------------------------ 묶기

    def build(self):
        out = {}
        filing_sec = self.filing_section()
        for w in self.filer.get("_경고") or []:
            self.note(w)
        with open(self.form_reg_path, "rb") as f:
            form_sha = hashlib.sha256(f.read()).hexdigest()[:16]
        out["판"] = {"기준정보": self.result["기준정보"]["판"], "서식": form_sha, "규격": self.layout["규격"]["판"]}
        out["신고"] = filing_sec
        out["신고인"] = self.filer_section()
        out["양수인"] = self.buyers_section()
        sheet1, sheet3, calc05, exp07 = [], [], [], []
        for n, row in enumerate(self.calc["자산"], 1):
            s1, s3, c5, e7 = self.asset(n, row)
            sheet1.append(s1)
            if s3:
                sheet3.append(s3)
            calc05.append(c5)
            exp07 += e7
        main, local, rates = self.main_forms()
        money = ("양도가액", "취득가액", "토초세", "기타필요경비", "양도차익", "비과세양도차익", "과세양도차익", "장특공",
                 "양도소득금액", "감면소득금액")
        totals = {k: sum(_int(s[k]) for s in sheet1) for k in money}
        totals["기준시가"] = {k: sum(s["기준시가"][k] for s in sheet1) for k in sheet1[0]["기준시가"]} if sheet1 else {}
        out.update({"본지": main, "부표1": sheet1, "부표1합계": totals, "부표3": sheet3, "지방": local,
                    "전자신고": {"세율별": rates, "계산명세": calc05, "필요경비명세": exp07}, "확인사항": list(self.notes)})
        return out


def build(result, facts, filer, rules_dir=None, forms_dir=None, efile_dir=None):
    """신고값 JSON(C8). result 는 상태가 완료인 engine.calculate 결과, filer 는 filing.load 를 통과한 신고인 정보.

    신고 범위가 아니면 Unsupported(계획 속성), 결과가 끝나지 않았거나 신고 구분·작성일이 없으면 ValueError,
    신고인 JSON 의 등기목적·등기원인 고쳐 쓰기 값이 틀리면 filing.FilingError.
    """
    if not result or result.get("상태") != "완료" or not result.get("계산"):
        raise ValueError("계산이 끝난 결과(상태 완료)만 신고값으로 만든다")
    b = _Builder(result, facts, filer, rules_dir, forms_dir, efile_dir)
    if result["기준정보"]["판"] != b.rs.판id:
        raise ValueError("결과의 기준정보 판 %s 이 지금 판 %s 과 다르다. 지금 판으로 다시 계산한 결과를 넣는다"
                         % (result["기준정보"]["판"], b.rs.판id))
    return b.build()
