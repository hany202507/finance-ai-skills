# -*- coding: utf-8 -*-
"""신고값(C8)을 법령 서식 원본 위에 얹어 신고서 PDF 두 벌을 만든다.

  양도소득세_신고서.pdf  별지 제84호서식 본지(1·2쪽), 부표1(5쪽), 부표3 (1)(14쪽)·(2)(16쪽)
  지방소득세_신고서.pdf  지방세 별지 제40호의11서식(1·2쪽)

어느 신고값을 어느 칸에 쓰는지는 `forms/매핑/*.json` 에 있고, 칸 좌표는 필드목록(`forms/필드목록/`)에 있다.
이 모듈은 둘을 이어 `plan()` 으로 「무엇을 어느 쪽 어느 칸에」 를 정하고, `render()` 가 원본에서 필요한 쪽만
새 문서로 옮겨 `forms_pdf.put_field` 로 쓴다. 값을 다시 계산하지 않는다. 예외는 부표3 의 소계 행(① ③ ⑥ ⑧ ⑨ ⑫)으로,
서식이 요구하는 행 합이라 명세 행에서 더하고, ⑤ 계·⑬ 계가 신고값과 같은지 대조한다.

매핑 파일 모양(서식마다 하나):

  {"서식": "별지84", "쪽": "본지", "채움쪽": 1, "덧붙임쪽": [2], "필드목록": [...],
   "열": {"합계": "양도소득세 합계", "세율구분": {"목록": "본지.세율구분", "칸": ["세율구분별 열1", ...]}},
   "칸": [{"신고값": "본지.열.{표기}.과세표준", "필드": "과세표준", "열": "세율구분", "형식": "금액"}, ...],
   "안씀": {"신고.홈택스ID": "서식에 칸이 없다", ...}}

- `신고값`: 신고값 JSON 경로(점과 [n]). 목록이면 형식이 값 목록을 받는다. `{i}` 는 반복 열의 항목 번호, `{표기}` 는 세율구분 표기.
- `열`: 매핑 「열」 표의 이름이거나 필드목록 열 이름. 「열」 표에서 `목록`·`칸` 이 있는 것은 반복 열이다. 항목이 칸보다
  많으면 장을 나누고, 반복 열이 아닌 칸은 첫 장에만 쓴다(`장마다: true` 인 칸은 장마다).
- `형식`: 금액 글 코드 세율 날짜 연월일 면적 기간 체크 세율구분 자산종류 주민등록번호 사업자번호 전화 주소 납세지
  소재지 자산소재지 양수인성명 지분 관계 국가명 은행 감면율 고유번호. 금액 0 은 비우고 `0적음: true` 인 칸만 0 을 적는다.
- `부분`: 기준점이 여럿인 칸(일자·원인, 금액·코드, 면적·지분)을 여러 줄로 나눠 적을 때 그 부분 이름. `있을때` 경로가
  비면 그 칸을 통째로 비운다.
- `줄`·`맞춤`·`pad`: 칸에 쓰는 방법(forms_pdf.put_field 인자).
- `안씀`: 서식에 옮기지 않는 신고값 경로와 이유. `[*]` 는 모든 번호. `unplaced()` 시험이 이 표와 매핑을 함께 본다.

인적사항(성명·주민등록번호·주소·전화·양수인·소재지)은 PDF 에만 쓴다. 칸에 들어가지 않을 때 내는 오류 문장과
확인사항에는 필드 이름만 적고 값을 옮기지 않는다.
"""
import json
import os
import re
from decimal import Decimal

import pymupdf

from yangdo import SKILL_DIR, forms_pdf

FORMS_DIR = os.path.join(SKILL_DIR, "forms")
EFILE_DIR = os.path.join(SKILL_DIR, "efile")
OUT_NATIONAL = "양도소득세_신고서.pdf"
OUT_LOCAL = "지방소득세_신고서.pdf"
MAPPINGS = {"국세": ("본지.json", "부표1.json", "부표3.json"), "지방": ("지방.json",)}
SIZE = 7.5

# 칸이 좁아 소재지·주소를 줄여 쓸 때의 시도 약칭(행정구역 이름의 관용 약칭)
SIDO_SHORT = {
    "서울특별시": "서울", "부산광역시": "부산", "대구광역시": "대구", "인천광역시": "인천", "광주광역시": "광주",
    "대전광역시": "대전", "울산광역시": "울산", "세종특별자치시": "세종", "경기도": "경기", "강원도": "강원",
    "강원특별자치도": "강원", "충청북도": "충북", "충청남도": "충남", "전라북도": "전북", "전북특별자치도": "전북",
    "전라남도": "전남", "경상북도": "경북", "경상남도": "경남", "제주특별자치도": "제주",
}
_ALIGN = {"금액": "right", "면적": "right", "세율": "right", "감면율": "right", "코드": "center", "체크": "center",
          "날짜": "center", "주민등록번호": "center", "사업자번호": "center", "전화": "center", "지분": "center"}
_TOKEN = re.compile(r"([^.\[\]]+)|\[(\d+)\]")
_LOT = re.compile(r"^\d+(-\d+)?$")
_UNIT = re.compile(r"^[0-9A-Za-z-]+(동|호)$")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ------------------------------------------------------------ 경로

def _get(obj, path):
    """「본지.열.합계.과세표준」, 「부표1[0].양도가액」 꼴 경로의 값. 없으면 None."""
    cur = obj
    for name, idx in _TOKEN.findall(path):
        if name:
            if not isinstance(cur, dict) or name not in cur:
                return None
            cur = cur[name]
        else:
            k = int(idx)
            if not isinstance(cur, list) or k >= len(cur):
                return None
            cur = cur[k]
    return cur


def _fill(path, ctx):
    for k, v in ctx.items():
        path = path.replace("{%s}" % k, str(v))
    return path


def _leaves(obj, prefix):
    """(경로, 값) 목록. dict·list 는 펼친다."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _leaves(v, "%s.%s" % (prefix, k) if prefix else k)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _leaves(v, "%s[%d]" % (prefix, i))
    else:
        yield prefix, obj


def _covers(pattern, path):
    """pattern 이 path 와 같거나 path 의 앞부분(점·대괄호 경계)인가. 「[*]」 는 모든 번호, 「.*」 는 모든 키."""
    rx = re.escape(pattern).replace(re.escape("[*]"), r"\[\d+\]").replace(re.escape("*"), r"[^.\[\]]+")
    return re.match(rx + r"(?:$|[.\[])", path) is not None


# ------------------------------------------------------------ 형식

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


def _address(a):
    """신고인 주소(C7 dict) → 「서울특별시 마포구 공덕동 1 합성아파트 101동 1001호」."""
    if not isinstance(a, dict):
        return str(a or "")
    parts = [a.get(k) for k in ("시도", "시군구", "읍면동") if a.get(k)]
    no = a.get("번지")
    if no and no != "0":
        no = ("산 " if a.get("특수지") == "1" else "") + no
        if a.get("호") and a["호"] != "0":
            no += "-" + a["호"]
        parts.append(no)
    for k, unit in (("아파트명", ""), ("아파트동", "동"), ("아파트호", "호")):
        v = a.get(k)
        if v:
            parts.append(v if (not unit or v.endswith(unit)) else v + unit)
    return " ".join(parts)


class _Fmt:
    """형식 이름 → 값 바꾸기. 돌려주는 값은 글자, {부분: 글자}, 후보 목록(앞에서부터 칸에 맞는 것을 쓴다), 또는 빈 글자."""

    def __init__(self, rv, mapping, codes):
        self.rv, self.m, self.codes = rv, mapping, codes

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
        q = d.quantize(Decimal("0.01"))
        if q != d:                                   # 신고값은 소수 셋째 자리까지(전자신고 면적 칸). 버리지 않고 그대로 적는다
            q = d.quantize(Decimal("0.001"))
        return format(q, ",f")

    @staticmethod
    def f_기간(v, e):
        s = str(v or "").strip()
        if not s:
            return ""
        m = re.fullmatch(r"(?:(\d+)년 이상)?\s*(?:(\d+)년 미만)?", s)
        if not m or not (m.group(1) or m.group(2)):
            raise ValueError("기간 글자가 「n년 이상 m년 미만」 꼴이 아니다")
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

    @staticmethod
    def f_주소(v, e):
        return _shorter(_address(v)) if v else ""

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
        """코드표에서 코드의 이름. 표에 없으면 멈춘다(빈칸으로 두면 값이 말없이 빠진다). 문장에는 코드 값을 싣지 않는다."""
        hit = self.codes[table].get(code)
        if hit is None:
            raise ValueError("%s: %s 코드가 코드표 「%s」에 없다" % (e.get("필드") or "?", kind, table))
        return hit.get("이름") or ""

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


def _empty(v):
    if v in (None, ""):
        return True
    if isinstance(v, dict):
        return all(x in (None, "") for x in v.values())
    if isinstance(v, list):
        return not v
    return False


# ------------------------------------------------------------ 계획

class _Planner:
    def __init__(self, rv, forms_dir, efile_dir):
        self.rv = rv
        self.forms_dir = forms_dir or FORMS_DIR
        self.reg = _read(os.path.join(self.forms_dir, "서식판.json"))["서식"]
        self.codes = _read(os.path.join(efile_dir or EFILE_DIR, "codes_c116300.json"))
        self.fields = {}
        self.notes = []
        self.used = []          # 서식에 옮겼거나 서식이 받지 않는(음영) 신고값 경로
        self.excused = {}       # 매핑 「안씀」 표

    def note(self, s):
        if s not in self.notes:
            self.notes.append(s)

    def mapping(self, name):
        m = _read(os.path.join(self.forms_dir, "매핑", name))
        for x in m["필드목록"]:
            if x not in self.fields:
                fl = _read(os.path.join(self.forms_dir, "필드목록", x))
                self.fields[x] = {f["id"]: f for f in fl["fields"]}
        self.excused.update(m.get("안씀") or {})
        return m

    def field(self, m, fid):
        for x in m["필드목록"]:
            if fid in self.fields[x]:
                return x, self.fields[x][fid]
        raise ValueError("매핑 %s 의 필드 %s 가 필드목록에 없다" % (m["쪽"], fid))

    @staticmethod
    def rect(f, col):
        c = f.get("좌표") or {}
        g = c.get("값_칸_해석") or {}
        return list(g[col]) if g else list(c["라벨_bbox"])

    @staticmethod
    def only_col(f):
        g = (f.get("좌표") or {}).get("값_칸_해석") or {}
        if len(g) != 1:
            raise ValueError("%s: 매핑에 열을 적어야 한다(%s)" % (f["id"], ", ".join(g)))
        return next(iter(g))

    def placement(self, page, m, fid, col, value, e, paths):
        lst, f = self.field(m, fid)
        col = col or self.only_col(f)
        kind = e.get("형식", "글")
        return {"쪽": page, "필드": fid, "목록": lst, "열": col, "칸": self.rect(f, col), "값": value, "신고값": paths,
                "맞춤": e.get("맞춤") or _ALIGN.get(kind), "줄": e.get("줄", 1), "pad": e.get("pad"),
                "이름": e.get("이름") or "%s %s %s" % (m["이름"], fid, col)}

    # ---- 일반 매핑(본지·부표1·지방)

    def sheets(self, m, pages, cells):
        alias = m.get("열") or {}
        groups = [v for v in alias.values() if isinstance(v, dict)]
        items, per = [], 1
        if groups:
            items = _get(self.rv, groups[0]["목록"]) or []
            per = len(groups[0]["칸"])
            if any(g["목록"] != groups[0]["목록"] or len(g["칸"]) != per for g in groups):
                raise ValueError("매핑 %s: 반복 열은 같은 목록·같은 칸 수여야 한다" % m["쪽"])
        count = max(1, -(-len(items) // per))
        if count > 1:
            noun = next(k for k, v in alias.items() if isinstance(v, dict))
            self.note("%s: %d장으로 나눴다(%s %d개, 한 장에 %d개). 합계 열은 첫 장에만 적었다"
                      % (m["이름"], count, noun, len(items), per))
        fmt = _Fmt(self.rv, m, self.codes)
        for s in range(count):
            page = len(pages)
            pages.append(m["채움쪽"])
            parts = {}
            for e in m["칸"]:
                spec = e.get("열")
                a = alias.get(spec) if spec else None
                if isinstance(a, dict):
                    for k in range(per):
                        idx = s * per + k
                        if idx >= len(items):
                            break
                        item = items[idx]
                        ctx = {"i": idx, "표기": item.get("표기", "") if isinstance(item, dict) else ""}
                        self.emit(page, m, e, a["칸"][k], ctx, fmt, cells, parts)
                elif s == 0 or e.get("장마다"):
                    self.emit(page, m, e, a if isinstance(a, str) else spec, {}, fmt, cells, parts)
            for (fid, col), (e, vals, paths) in parts.items():
                if not _empty(vals):
                    cells.append(self.placement(page, m, fid, col, vals, e, paths))
        pages.extend(m.get("덧붙임쪽") or [])

    def emit(self, page, m, e, col, ctx, fmt, cells, parts):
        raw = e["신고값"]
        paths = [_fill(p, ctx) for p in (raw if isinstance(raw, list) else [raw])]
        values = [_get(self.rv, p) for p in paths]
        self.used.extend(paths)
        value = values if isinstance(raw, list) else values[0]
        cond = e.get("있을때")
        if cond and not _get(self.rv, _fill(cond, ctx)):
            return
        kind = e.get("형식", "글")
        if kind == "체크":
            col = None
            if value not in (None, ""):
                col = e["선택"].get(str(value))
                if col is None:             # 빈칸으로 두면 체크가 말없이 빠진다. 값은 싣지 않는다
                    raise ValueError("%s: 체크 값이 매핑 「선택」(%s)에 없다" % (e["필드"], ", ".join(e["선택"])))
            out = "V" if col else ""
        else:
            out = fmt(kind, value, e)
        if e.get("부분"):
            key = (e["필드"], col)
            got = parts.setdefault(key, (e, {}, []))
            got[1][e["부분"]] = out if isinstance(out, str) else ""
            got[2].extend(paths)
            return
        if _empty(out):
            return
        cells.append(self.placement(page, m, e["필드"], col, out, e, paths))

    # ---- 부표3

    def schedule3(self, m, pages, cells):
        fmt = _Fmt(self.rv, m, self.codes)
        rows_of = m["행"]
        detail_rows = m["명세행"]
        for i, sheet in enumerate(self.rv.get("부표3") or []):
            base = "부표3[%d]" % i
            self.used.append(base + ".자산")
            page = len(pages)
            pages.append(m["채움쪽"])
            groups = {}
            for j, row in enumerate(sheet.get("행") or []):
                fid = rows_of.get(str(row.get("전자코드")))
                if fid is None:
                    raise ValueError("부표3 명세 행의 필요경비 구분 %s 에 맞는 서식 행이 매핑에 없다" % row.get("전자코드"))
                groups.setdefault(fid, []).append((j, row))
                self.used.extend("%s.행[%d].%s" % (base, j, k) for k in ("구분코드", "구분", "전자코드"))
            amount = {fid: sum(int(r["금액"] or 0) for _, r in rs) for fid, rs in groups.items()}
            # ⑤ 계·⑬ 계는 명세 행 합과 신고값이 같아야 한다
            for fid, rule in m["계"].items():
                got = sum(amount.get(x, 0) for x in rule["더함"]) - sum(amount.get(x, 0) for x in rule.get("뺌", []))
                want = int(sheet.get(rule["신고값"]) or 0)
                if got != want:
                    raise ValueError("부표3 %s: 명세 행 합 %s원이 신고값 %s %s원과 다르다"
                                     % (fid, format(got, ","), rule["신고값"], format(want, ",")))
                self.used.append("%s.%s" % (base, rule["신고값"]))
                out = fmt("금액", want, {"0적음": True})
                cells.append(self.placement(page, m, fid, rule["열"], out, {"형식": "금액"}, ["%s.%s" % (base, rule["신고값"])]))
            for fid, members in m["소계"].items():
                out = fmt("금액", sum(amount.get(x, 0) for x in members), {})
                if out:
                    cells.append(self.placement(page, m, fid, "지급금액", out, {"형식": "금액"}, []))
            details = []
            for fid, rs in groups.items():
                lst, f = self.field(m, fid)
                shaded = set(f.get("음영_열", []))
                if len(rs) > 1:
                    total = fmt("금액", amount[fid], {})
                    if total:
                        cells.append(self.placement(page, m, fid, "지급금액", total, {"형식": "금액"}, []))
                    if m["별지표시"]["열"] not in shaded:
                        cells.append(self.placement(page, m, fid, m["별지표시"]["열"], m["별지표시"]["글"], {}, []))
                    details.extend(rs)
                    for j, _ in rs:
                        self.used.extend("%s.행[%d].%s" % (base, j, c["신고값"]) for c in m["행칸"])
                    continue
                j, row = rs[0]
                for c in m["행칸"]:
                    path = "%s.행[%d].%s" % (base, j, c["신고값"])
                    self.used.append(path)
                    if c["열"] in shaded:
                        continue
                    out = fmt(c["형식"], row.get(c["신고값"]), c)
                    if not _empty(out):
                        cells.append(self.placement(page, m, fid, c["열"], out, c, [path]))
            details.sort(key=lambda x: x[0])
            for start in range(0, len(details), len(detail_rows)):
                page = len(pages)
                pages.append(m["명세쪽"])
                for slot, (j, row) in zip(detail_rows, details[start:start + len(detail_rows)]):
                    for c in m["명세칸"]:
                        path = "%s.행[%d].%s" % (base, j, c["신고값"])
                        out = fmt(c["형식"], row.get(c["신고값"]), c)
                        if not _empty(out):
                            cells.append(self.placement(page, m, slot, c["열"], out, c, [path]))

    # ---- 묶기

    def build(self):
        out = {"확인사항": self.notes}
        for which, names in MAPPINGS.items():
            pages, cells, src = [], [], None
            for name in names:
                m = self.mapping(name)
                src = os.path.join(self.forms_dir, self.reg[m["서식"]]["파일"])
                if "행" in m:
                    self.schedule3(m, pages, cells)
                    continue
                self.sheets(m, pages, cells)
            out[which] = {"원본": src, "쪽": pages, "칸": cells}
        buyers = self.rv.get("양수인") or []
        if len(buyers) > 1:
            self.used.extend("양수인[%d]" % k for k in range(1, len(buyers)))
            self.note("양수인이 %d명이라 본지 ②·별지40의11 ③ 에 첫 양수인만 적고 성명 뒤에 「외 %d명」을 붙였다. "
                      "나머지 양수인은 별지로 작성해 붙인다(본지 작성방법 3)" % (len(buyers), len(buyers) - 1))
        self.note("본지 「세무서장 귀하」 앞 관할 세무서 이름은 비워 두었다. 서면으로 낼 때 주소지 관할 세무서 이름을 적는다")
        out["사용"] = self.used
        out["안씀"] = self.excused
        return out


def plan(rv, forms_dir=None, efile_dir=None):
    """서식에 쓸 것. {"국세": {"원본", "쪽", "칸"}, "지방": {...}, "확인사항": [...], "사용": [...], "안씀": {...}}.

    「쪽」 은 새 문서의 쪽마다 원본 쪽 번호(1부터), 「칸」 은 {"쪽"(새 문서 0부터), "필드", "목록", "열", "칸"(좌표),
    "값", "신고값", "맞춤", "줄", "pad", "이름"} 목록이다. 「값」 이 목록이면 앞에서부터 칸에 들어가는 것을 쓴다."""
    return _Planner(rv, forms_dir, efile_dir).build()


def unplaced(rv, forms_dir=None, efile_dir=None):
    """서식에 들어갈 신고값(0·빈칸·거짓이 아닌 값) 가운데 매핑이 놓지도, 「안씀」 으로 이유를 대지도 않은 경로."""
    p = plan(rv, forms_dir, efile_dir)
    keys = list(p["사용"]) + list(p["안씀"])
    out = []
    for section in ("신고", "신고인", "양수인", "본지", "부표1", "부표1합계", "부표3", "지방"):
        for path, v in _leaves(rv.get(section), section):
            if v in (None, "", 0, False):
                continue
            if not any(_covers(k, path) for k in keys):
                out.append(path)
    return out


# ------------------------------------------------------------ 쓰기

def _write(page, field, c, font):
    """칸 하나를 쓴다. 값이 후보 목록이면 앞에서부터 들어가는 것을 쓴다. 쓴 후보의 번호.

    넘침(forms_pdf.Overflow)만 다음 후보로 넘기고, 다른 ValueError(음영 칸·없는 열·기준점 못 찾음)는 그 원인을 그대로 낸다.
    오류 문장에 값을 옮기지 않는다(인적사항이 로그에 남지 않게)."""
    values = c["값"] if isinstance(c["값"], list) else [c["값"]]
    for n, v in enumerate(values):
        try:
            forms_pdf.put_field(page, field, v, col=c["열"], align=c["맞춤"], size=SIZE, font=font, lines=c["줄"],
                                pad=c["pad"])
            return n
        except forms_pdf.Overflow:
            continue
        except ValueError as err:           # forms_pdf 의 이 문장들은 칸·기준점 이름만 담고 값은 담지 않는다
            raise ValueError("%s %s 칸을 쓸 수 없다: %s" % (c["필드"], c["열"], err)) from None
    raise forms_pdf.Overflow("%s %s 칸에 값이 들어가지 않는다(후보 %d개). 매핑의 줄·pad 를 고치거나 값을 줄인다"
                             % (c["필드"], c["열"], len(values))) from None


def render(rv, out_dir, forms_dir=None):
    """신고값으로 신고서 PDF 두 벌을 만들고 경로 [양도소득세_신고서.pdf, 지방소득세_신고서.pdf] 를 돌려준다.

    장을 나누거나 칸이 좁아 소재지를 줄인 사실은 rv["확인사항"] 끝에 더한다(값은 싣지 않는다)."""
    p = plan(rv, forms_dir)
    fields = {}
    root = forms_dir or FORMS_DIR
    font = forms_pdf.load_font()
    os.makedirs(out_dir, exist_ok=True)
    notes = list(p["확인사항"])
    built = []              # (임시 경로, 최종 경로). 두 문서를 모두 임시 이름으로 만든 뒤에 한꺼번에 바꾼다
    try:
        for which, name in (("국세", OUT_NATIONAL), ("지방", OUT_LOCAL)):
            part = p[which]
            path = os.path.join(out_dir, name)
            with pymupdf.open(part["원본"]) as src, pymupdf.open() as doc:
                for pg in part["쪽"]:
                    doc.insert_pdf(src, from_page=pg - 1, to_page=pg - 1)
                for c in part["칸"]:
                    if c["목록"] not in fields:
                        fields[c["목록"]] = {f["id"]: f
                                             for f in _read(os.path.join(root, "필드목록", c["목록"]))["fields"]}
                    n = _write(doc[c["쪽"]], fields[c["목록"]][c["필드"]], c, font)
                    if n:
                        notes.append("%s 칸이 좁아 시도 이름을 줄이거나 아파트 이름 등을 빼고 적었다. "
                                     "전체 글자는 신고값과 전자신고 파일에 있다" % c["이름"])
                built.append((path + ".tmp", path))     # 저장 도중 실패해도 finally 가 지우도록 먼저 적는다
                forms_pdf.save(doc, path + ".tmp")
        for tmp, path in built:
            os.replace(tmp, path)
        built = []
    finally:
        for tmp, _ in built:                # 중간에 실패하면 새로 만든 임시 파일을 지우고 이전 파일은 그대로 둔다
            if os.path.exists(tmp):
                os.remove(tmp)
    paths = [os.path.join(out_dir, n) for n in (OUT_NATIONAL, OUT_LOCAL)]
    have = rv.setdefault("확인사항", [])
    for s in notes:
        if s not in have:
            have.append(s)
    return paths
