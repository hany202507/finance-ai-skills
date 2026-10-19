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
  값을 서식 글자로 바꾸는 규칙과 좁은 칸에 쓸 주소 줄임 후보는 `yangdo/forms_fmt.py` 에 있다.
- `부분`: 기준점이 여럿인 칸(일자·원인, 금액·코드, 면적·지분)을 여러 줄로 나눠 적을 때 그 부분 이름. `있을때` 경로가
  비면 그 칸을 통째로 비운다.
- `줄`·`맞춤`·`pad`: 칸에 쓰는 방법(forms_pdf.put_field 인자).
- `안씀`: 서식에 옮기지 않는 신고값 경로와 이유. `[*]` 는 모든 번호. `unplaced()` 시험이 이 표와 매핑을 함께 본다.
  국세 서식(본지·부표1·부표3)과 지방 서식은 저마다 본다. 두 서식이 함께 읽는 절(신고·신고인·양수인)의 경로는 두 쪽 매핑이
  각각 놓거나 이유를 대야 한다(한쪽 매핑의 「안씀」이 다른 쪽에서 빠진 칸을 가리지 않는다).

부표3 매핑은 `칸` 없이 `행`(전자코드 → 서식 행)·`행칸`·`명세칸`·`소계`·`계`·`금액열` 표로 쓴다. `계` 의 `0적음` 과 `열`,
소계와 행 합계액을 적는 `금액열` 을 `schedule3()` 이 읽는다.

인적사항(성명·주민등록번호·주소·전화·양수인·소재지)은 PDF 에만 쓴다. 칸에 들어가지 않을 때 내는 오류 문장과
확인사항에는 필드 이름만 적고 값을 옮기지 않는다.
"""
import json
import os
import re

import pymupdf

from yangdo import SKILL_DIR, edition, forms_fmt, forms_pdf
from yangdo.forms_fmt import SIDO_SHORT, _Fmt  # noqa: F401  SIDO_SHORT 는 예전부터 이 모듈의 이름으로도 읽는다

FORMS_DIR = os.path.join(SKILL_DIR, "forms")
EFILE_DIR = os.path.join(SKILL_DIR, "efile")
OUT_NATIONAL = "양도소득세_신고서.pdf"
OUT_LOCAL = "지방소득세_신고서.pdf"
MAPPINGS = {"국세": ("본지.json", "부표1.json", "부표3.json"), "지방": ("지방.json",)}
SIZE = 7.5

_ALIGN = {"금액": "right", "면적": "right", "세율": "right", "감면율": "right", "코드": "center", "체크": "center",
          "날짜": "center", "주민등록번호": "center", "사업자번호": "center", "전화": "center", "지분": "center"}
_TOKEN = re.compile(r"([^.\[\]]+)|\[(\d+)\]")


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
        self.used = []          # 서식에 옮겼거나 서식이 받지 않는(음영) 신고값 경로. build 가 서식(국세·지방)마다 새로 둔다
        self.excused = {}       # 매핑 「안씀」 표. 위와 같다

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
        if g and col not in g:
            raise ValueError("%s: 매핑이 가리키는 열 %s 이 필드목록에 없다(%s)" % (f["id"], col, ", ".join(g)))
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
                "맞춤": e.get("맞춤") or _ALIGN.get(kind), "줄": e.get("줄", 1), "pad": e.get("pad"), "간격": e.get("간격"),
                "이름": e.get("이름") or _cell_name(m["이름"], fid, col), "형식": kind, "서식": m["이름"]}

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
        fmt = _Fmt(self.rv, m, self.codes, self.note)
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
        fmt = _Fmt(self.rv, m, self.codes, self.note)
        rows_of = m["행"]
        detail_rows = m["명세행"]
        money_col = m["금액열"]              # 소계와 행 합계액을 적는 열
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
                out = fmt("금액", want, {"0적음": rule.get("0적음", False)})
                if out:
                    cells.append(self.placement(page, m, fid, rule["열"], out, {"형식": "금액"}, ["%s.%s" % (base, rule["신고값"])]))
            for fid, members in m["소계"].items():
                out = fmt("금액", sum(amount.get(x, 0) for x in members), {})
                if out:
                    cells.append(self.placement(page, m, fid, money_col, out, {"형식": "금액"}, []))
            details = []
            for fid, rs in groups.items():
                lst, f = self.field(m, fid)
                shaded = set(f.get("음영_열", []))
                if len(rs) > 1:
                    total = fmt("금액", amount[fid], {})
                    if total:
                        cells.append(self.placement(page, m, fid, money_col, total, {"형식": "금액"}, []))
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
        out = {"확인사항": self.notes, "서식별": {}}
        buyers = self.rv.get("양수인") or []
        for which, names in MAPPINGS.items():
            pages, cells, src = [], [], None
            self.used, self.excused = [], {}
            for name in names:
                m = self.mapping(name)
                src = os.path.join(self.forms_dir, self.reg[m["서식"]]["파일"])
                if "행" in m:
                    self.schedule3(m, pages, cells)
                    continue
                self.sheets(m, pages, cells)
            out[which] = {"원본": src, "쪽": pages, "칸": cells}
            if len(buyers) > 1:             # 둘째 양수인부터는 어느 서식에도 칸이 없다(아래 확인사항으로 알린다)
                self.used.extend("양수인[%d]" % k for k in range(1, len(buyers)))
            out["서식별"][which] = {"사용": self.used, "안씀": self.excused}
        if len(buyers) > 1:
            self.note("양수인이 %d명이라 본지 ②·별지40의11 ③ 에 첫 양수인만 적고 성명 뒤에 「외 %d명」을 붙였다. "
                      "나머지 양수인은 별지로 작성해 붙인다(본지 작성방법 3)" % (len(buyers), len(buyers) - 1))
        self.note("본지 「세무서장 귀하」 앞 관할 세무서 이름은 비워 두었다. 서면으로 낼 때 주소지 관할 세무서 이름을 적는다")
        out["사용"] = [p for part in out["서식별"].values() for p in part["사용"]]
        out["안씀"] = {k: v for part in out["서식별"].values() for k, v in part["안씀"].items()}
        return out


def plan(rv, forms_dir=None, efile_dir=None):
    """서식에 쓸 것. {"국세": {"원본", "쪽", "칸"}, "지방": {...}, "확인사항": [...], "서식별": {...}, "사용": [...], "안씀": {...}}.

    「쪽」 은 새 문서의 쪽마다 원본 쪽 번호(1부터), 「칸」 은 {"쪽"(새 문서 0부터), "필드", "목록", "열", "칸"(좌표),
    "값", "신고값", "맞춤", "줄", "pad", "간격", "이름", "형식", "서식"} 목록이다. 「값」 이 목록이면 앞에서부터 칸에 들어가는 것을 쓴다.
    「서식별」 은 {"국세": {"사용", "안씀"}, "지방": {...}} 로, 그 서식의 매핑이 놓은 신고값 경로와 「안씀」 표다.
    「사용」·「안씀」 은 두 서식의 것을 합친 것이다."""
    return _Planner(rv, forms_dir, efile_dir).build()


# 서식마다 옮겨 적어야 하는 신고값 절. 신고·신고인·양수인은 두 서식이 함께 읽는다
FORM_SECTIONS = {"국세": ("신고", "신고인", "양수인", "본지", "부표1", "부표1합계", "부표3"),
                 "지방": ("신고", "신고인", "양수인", "지방")}


def unplaced(rv, forms_dir=None, efile_dir=None):
    """서식에 들어갈 신고값(0·빈칸·거짓이 아닌 값) 가운데 매핑이 놓지도, 「안씀」 으로 이유를 대지도 않은 경로.

    국세 서식과 지방 서식을 따로 본다(FORM_SECTIONS). 돌려주는 글자는 「국세: 신고.홈택스ID」 꼴이다. 두 서식을 합쳐 보면
    한쪽 매핑에서 빠진 칸을 다른 쪽 매핑의 「안씀」 이 가린다."""
    p = plan(rv, forms_dir, efile_dir)
    out = []
    for which, sections in FORM_SECTIONS.items():
        keys = list(p["서식별"][which]["사용"]) + list(p["서식별"][which]["안씀"])
        for section in sections:
            for path, v in _leaves(rv.get(section), section):
                if v in (None, "", 0, False):
                    continue
                if not any(_covers(k, path) for k in keys):
                    out.append("%s: %s" % (which, path))
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
                                pad=c["pad"], gap=c.get("간격"))
            return n
        except forms_pdf.Overflow:
            continue
        except ValueError as err:           # forms_pdf 의 이 문장들은 칸·기준점 이름만 담고 값은 담지 않는다
            raise ValueError("%s %s 칸을 쓸 수 없다: %s" % (c["필드"], c["열"], err)) from None
    raise forms_pdf.Overflow("%s %s 칸에 값이 들어가지 않는다(후보 %d개). 매핑의 줄·pad 를 고치거나 값을 줄인다"
                             % (c["필드"], c["열"], len(values))) from None


# 칸이 좁아 첫 후보 대신 뒤 후보를 썼을 때의 확인사항. 칸의 형식마다 무엇을 줄였는지가 다르다(값은 싣지 않는다)
_SHORT_NOTES = {
    "주소": "시도 이름을 줄이거나 아파트 이름 등을 빼고 적었다. 전체 글자는 신고값과 전자신고 파일에 있다",
    "납세지": "시도 이름을 줄이거나 빼고 적었다. 시ㆍ군ㆍ구 이름은 그대로다",
    "자산종류": "자산종류 이름을 짧은 이름으로 적었다. 코드는 그대로다",
}
_SHORT_NOTES["소재지"] = _SHORT_NOTES["자산소재지"] = _SHORT_NOTES["주소"]
_SHORT_NOTE_OTHER = "줄인 값으로 적었다. 전체 글자는 신고값에 있다"


def _cell_name(form, fid, col):
    """칸 이름. 열 이름이 필드 이름의 끝과 같으면(신고인.국적 의 국적 열) 한 번만 적는다."""
    return "%s %s" % (form, fid) if fid.rsplit(".", 1)[-1] == col else "%s %s %s" % (form, fid, col)


def shortened_note(c):
    """칸 c(plan 의 칸 항목)를 첫 후보가 아닌 뒤 후보로 썼다는 확인사항 문장.
    공개본은 신고값과 전자신고 파일을 쓰지 않으므로 전체 글자가 있는 곳을 입력 파일(사실관계, 신고인 파일)로 적는다."""
    text = _SHORT_NOTES.get(c.get("형식"), _SHORT_NOTE_OTHER)
    if edition.PUBLIC:
        text = text.replace("신고값과 전자신고 파일에", "사실관계와 신고인 파일에").replace("신고값에", "사실관계와 신고인 파일에")
    return "%s 칸이 좁아 %s" % (c["이름"], text)


def blank_note(field, cells, total):
    """영문 이름 후보 [영문, ""] 가 칸에 들어가지 않아 칸을 비운 사실을 필드마다 한 문장으로 쓴다.
    cells 는 비운 칸 항목, total 은 그 필드에서 영문 이름 후보를 가진 칸의 수다(일부 서식에만 들어갔으면 그렇게 밝힌다)."""
    forms = "·".join(dict.fromkeys(c["서식"] for c in cells))
    s = "%s 칸: 코드표에 한글 이름이 없어 영문 이름을 적으려 했으나 %s 칸에 들어가지 않아 비워 두었다. 서면으로 낼 때 직접 적는다" % (field, forms)
    return s + ("" if len(cells) == total else ". 나머지 서식에는 영문 이름을 적었다")


def render(rv, out_dir, forms_dir=None):
    """신고값으로 신고서 PDF 두 벌을 만들고 경로 [양도소득세_신고서.pdf, 지방소득세_신고서.pdf] 를 돌려준다.

    장을 나누거나 칸이 좁아 줄인 후보로 쓴 사실은 rv["확인사항"] 끝에 더한다(값은 싣지 않는다)."""
    p = plan(rv, forms_dir)
    fields = {}
    root = forms_dir or FORMS_DIR
    font = forms_pdf.load_font()
    os.makedirs(out_dir, exist_ok=True)
    notes = list(p["확인사항"])
    english = {}            # 필드 -> [영문 이름 후보를 가진 칸 수, 칸에 들어가지 않아 비운 칸 목록]
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
                    if isinstance(c["값"], list) and c["값"][-1] == "" and len(c["값"]) > 1:
                        english.setdefault(c["필드"], [0, []])[0] += 1
                    if n and c["값"][n] == "":
                        english[c["필드"]][1].append(c)
                    elif n:
                        notes.append(shortened_note(c))
                built.append((path + ".tmp", path))     # 저장 도중 실패해도 finally 가 지우도록 먼저 적는다
                forms_pdf.save(doc, path + ".tmp")
        for tmp, path in built:
            os.replace(tmp, path)
        built = []
    finally:
        for tmp, _ in built:                # 중간에 실패하면 새로 만든 임시 파일을 지우고 이전 파일은 그대로 둔다
            if os.path.exists(tmp):
                os.remove(tmp)
    for field, (total, blank) in english.items():
        if blank:       # 「영문 이름을 적는다. 칸에 들어가지 않으면 비워 둔다」 는 비웠다는 문장으로 바꾼다
            notes = [x for x in notes if not (x.startswith("%s 칸: " % field) and x.endswith(forms_fmt.ENGLISH_NOTE_TAIL))]
            notes.append(blank_note(field, blank, total))
    paths = [os.path.join(out_dir, n) for n in (OUT_NATIONAL, OUT_LOCAL)]
    have = rv.setdefault("확인사항", [])
    for s in notes:
        if s not in have:
            have.append(s)
    return paths
