"""dsd 문장 검토(2026-10-17). 표가 아닌 글(표지 · 감사보고서 · 주석 문단 · 외부감사 실시내용)과 표 안 글자를 읽어
오타 · 표현 · 사실 불일치 · 공시 누락을 찾는다. 숫자 푸팅(dsd_links)과 같은 엑셀에 「문장 검토」 시트로 나온다.

「푸팅은 상호 레퍼도 해야겠지만 오타 표현수정도 다 잡아야 해. 주소수정, 경영진 변경 등 공시필요한 주요 내용 포함해서.
물론 회계감사기간 등 표 이외 것들도」.

맡는 일
  엔진   글을 위치(S번호)와 함께 읽기, 기준 사실(기준사실.json)과 대조(회사명 · 대표이사 · 본점 주소 · 감사인 주소 · 감사기간 · 감사보고서일 ·
         옛 값이 남은 곳), 보고서 안 일관성(대표이사 이름 · 감사보고서일), 오타 사전 · 기준서 용어 · 반복 낱말 · 띄어쓰기 · 율과 률 · 날짜 쉼표 · 괄호 짝,
         작년 보고서와 같은 문장에 남은 작년 날짜, 외부감사 실시내용에 남은 작년 날짜
  AI     문장읽기.md 를 처음부터 끝까지 읽고 오타 · 어색한 표현 · 사실 불일치 · 공시가 필요한데 빠진 내용을 문장.json 에 적는다
         (발췌는 원문 글자 그대로. 엔진이 원문에 있는지 확인하고 없으면 받지 않는다)
  회계사 시트의 확인(O · X)과 고칠지 정하기

기준사실.json 꼴(값은 문자열, 여럿이면 목록. old 는 바뀌기 전 값, source 는 근거 자료)
  {"회사명": {"value": "가온정밀(가상)"}, "대표이사": {"value": "김가온(가상)", "old": ["이가온(가상)"], "source": "이사회의사록 2025-09-01"},
   "본점 주소": {"value": "경기도 …", "old": ["서울특별시 …"]}, "감사인 주소": {"value": "…"},
   "감사기간": [{"구분": "현장감사", "기간": "2026-02-09~2026-02-13"}], "감사보고서일": {"value": "2026-03-10"}, "결산일": {"value": "2025-12-31"}}

  segments(path) -> [Seg]                          글 조각(S번호 · 부분 · 제목 · 종류 · 글)
  review(path, facts, prior=None, ai=None, case=None) -> {"segments", "engine", "ai", "invalid", "disclosures", "candidates"}
  reading(result, facts) -> str                    AI 가 읽을 문장읽기.md
  add_sheet(wb, result)                            「문장 검토」 시트
"""
from __future__ import annotations

import json
import re
import zipfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .. import folder, wp

SHEET = "문장 검토"
CR = "&cr;"
PARTICLES = "이가은는을를의와과도께"          # 이름 바로 뒤에 붙는 조사(대표이사 이름 읽기)


@dataclass
class Seg:
    id: str
    part: str
    head: str
    kind: str          # 제목 · 문단 · 표 줄 · 표지
    text: str
    n: int = 0         # 그 제목 아래 몇 번째(문단 · 표 줄)

    @property
    def where(self) -> str:
        h = f" · {self.head}" if self.head and self.head != self.part else ""
        return f"{self.part}{h} · {self.kind} {self.n}" if self.n else f"{self.part}{h} · {self.kind}"


def defs() -> dict:
    return folder.read_yaml(folder.DEFS / "dsd_text.yaml")


def _n(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


# ---------------------------------------------------------------- 읽기
def _cover(path: Path) -> list[str]:
    if path.suffix.lower() == ".xml":
        return []
    import xml.etree.ElementTree as ET

    with zipfile.ZipFile(path) as z:
        name = next((n for n in z.namelist() if n.lower().endswith("contents.xml")), None)
        if name is None:
            return []
        root = ET.fromstring(z.read(name))
    c = root.find(".//COVER")
    if c is None:
        return []
    raw = "".join(c.itertext())
    return [re.sub(r"\s+", " ", x).strip() for x in raw.split(CR) if x.strip()]


PDF_NOISE = re.compile(r"^(전자공시시스템\s*dart\.fss\.or\.kr|Page\s*\d+|-\s*\d+\s*-)$")


def _pdf_segments(path: Path) -> list[Seg]:
    """작년 보고서가 PDF(회사가 준 전기 감사보고서)일 때의 글 조각(2026-10-18). PDF 는 문단이 줄마다 끊겨 있어 「다.」 로 끝나는 줄까지
    이어 붙여 한 문단으로 둔다. 쪽 머리글(전자공시시스템 · Page n)은 뺀다. 작년 보고서와 같은 문장 찾기에만 쓴다."""
    from ..reader import pdf_text

    out: list[Seg] = []
    buf = []
    for _, text in pdf_text(path):
        for line in text.splitlines():
            t = line.strip()
            if not t or PDF_NOISE.match(t):
                continue
            buf.append(t)
            if re.search(r"(다|요|음|함)\.$", t):
                out.append(Seg(f"S{len(out) + 1}", "작년 보고서", "", "문단", " ".join(buf), len(out) + 1))
                buf = []
    if buf:
        out.append(Seg(f"S{len(out) + 1}", "작년 보고서", "", "문단", " ".join(buf), len(out) + 1))
    return out


def segments(path: Path) -> list[Seg]:
    from . import dsd

    path = Path(path)
    if path.suffix.lower() == ".pdf":                 # --prior 로 전기 감사보고서 PDF 를 받는다(2026-10-18 실제 회사 자료)
        return _pdf_segments(path)
    out: list[Seg] = []

    def add(part, head, kind, text, n=0):
        out.append(Seg(f"S{len(out) + 1}", part, head, kind, text, n))

    for i, line in enumerate(_cover(path), 1):
        add("표지", "", "표지", line, i)
    part, head, k_p, k_t = "기타", "", 0, 0
    for b in dsd.read_dsd(path):
        if b[0] == "h" and b[1] == 1:
            part, head, k_p, k_t = b[2], b[2], 0, 0
            continue
        if b[0] == "h":
            head, k_p, k_t = b[2], 0, 0
            add(part, head, "제목", b[2])
            continue
        if b[0] in ("p", "cap"):
            k_p += 1
            add(part, head, "문단", b[1], k_p)
            continue
        if b[0] == "table":
            k_t += 1
            for r, row in enumerate(b[1], 1):
                cells = [x for x in row if x]
                if any(re.search(r"[가-힣A-Za-z]", x) for x in cells):        # 숫자만 있는 줄은 숫자 푸팅 몫
                    add(part, head, f"표 {k_t} 줄", " | ".join(cells), r)
    return out


# ---------------------------------------------------------------- 글자 규칙
_LIST_MARK = re.compile(r"(?:^|(?<=\s)|(?<=\|))(?:\d{1,2}|[가나다라마바사아자차카타파하]|[a-z]|[ⅰ-ⅹ])\)(?=\s|$)")
_COPULA = re.compile(r"([가-힣A-Za-z0-9)%」]+)\s+입니다")
_RATE = re.compile(r"(?<![가-힣])([가-힣]+?)([율률])")
_DATE_COMMA = re.compile(r"20\d\d\.\d{1,2},\d{1,2}(?!\d)")


def _rate_fix(stem: str, got: str) -> str:
    """「반품율」 은 「반품률」. 앞 글자에 받침이 있으면(ㄴ 제외) 률, 없거나 ㄴ 이면 율. 바르면 빈 글"""
    c = ord(stem[-1]) - 0xAC00 if stem else -1
    if not 0 <= c < 11172:
        return ""
    want = "률" if c % 28 not in (0, 4) else "율"
    return want if want != got else ""


# ---------------------------------------------------------------- 날짜
_D =re.compile(r"(20\d\d)\s*[년.\-/]\s*(\d{1,2})\s*[월.\-/]\s*(\d{1,2})\s*일?")
_RANGE = re.compile(r"(20\d\d)\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일\s*[~∼～-]\s*(?:(20\d\d)\s*년\s*)?(\d{1,2})\s*월\s*(\d{1,2})\s*일")


def _dates(text: str) -> list[date]:
    out = []
    for m in _D.finditer(text or ""):
        try:
            out.append(date(int(m.group(1)), int(m.group(2)), int(m.group(3))))
        except ValueError:
            pass
    return out


def _ranges(text: str) -> list[tuple[date, date]]:
    out = []
    for m in _RANGE.finditer(text or ""):
        y1 = int(m.group(1))
        y2 = int(m.group(4) or y1)
        try:
            out.append((date(y1, int(m.group(2)), int(m.group(3))), date(y2, int(m.group(5)), int(m.group(6)))))
        except ValueError:
            pass
    return out


def _parse_range(s: str) -> tuple[date, date] | None:
    m = re.match(r"\s*(\d{4}-\d{2}-\d{2})\s*~\s*(\d{4}-\d{2}-\d{2})\s*$", s or "")
    return (date.fromisoformat(m.group(1)), date.fromisoformat(m.group(2))) if m else None


def _k(d: date) -> str:
    return f"{d.year}년 {d.month}월 {d.day}일"


# ---------------------------------------------------------------- 기준 사실
def _vals(f) -> list[str]:
    if f is None:
        return []
    v = f.get("value") if isinstance(f, dict) else f
    return [str(x) for x in (v if isinstance(v, list) else [v]) if x not in (None, "")]


def _olds(f) -> list[str]:
    return [str(x) for x in ((f or {}).get("old") or [])] if isinstance(f, dict) else []


def load_facts(path: Path | None = None, case: Path | None = None) -> dict:
    """기준사실.json 을 읽고, 감사 폴더를 주면 그 폴더에서 아는 값(회사명 · 결산일)을 빈 자리에 채운다."""
    facts = json.loads(Path(path).read_text(encoding="utf-8")) if path and Path(path).exists() else {}
    if case:
        p = Path(case) / "_색인" / "감사건.json"
        if p.exists():
            c = json.loads(p.read_text(encoding="utf-8"))
            co = c.get("company")
            name = co.get("name") if isinstance(co, dict) else co
            if name and "회사명" not in facts:
                facts["회사명"] = {"value": name, "source": "감사건.json"}
            if c.get("fiscal_year_end") and "결산일" not in facts:
                facts["결산일"] = {"value": str(c["fiscal_year_end"])[:10], "source": "감사건.json"}
    return facts


def candidates(case: Path | None) -> list[dict]:
    """감사 폴더 받은자료 사실(의사록 · 등기부 등 판독) 가운데 공시가 필요할 수 있는 사건. AI 가 주석에 공시됐는지 본다.
    공시 확인 대상의 정의는 이 함수 하나다: 받은자료 사실 한 줄이 disclosure_keys 낱말을 담으면 한 건(같은 항목 · 자료 · 사실은 한 번).
    text 와 foot 가 같은 수를 내지 않으면 그 사이에 감사 폴더 색인이 바뀐 것이다(stale 로 알린다, 2026-10-18 B-7)."""
    if not case:
        return []
    p = Path(case) / "_색인" / "문서목록.json"
    if not p.exists():
        return []
    keys = defs().get("disclosure_keys") or {}
    out, seen = [], set()
    for f in json.loads(p.read_text(encoding="utf-8")).get("files", []):
        if f.get("role") != "received":
            continue
        for x in f.get("facts") or []:
            t = str(x.get("text") or "")
            for item, ks in keys.items():
                if any(_n(k) in _n(t) for k in ks):
                    c = {"item": item, "fact": t, "source": f"{f['path']} {x.get('source_page') or ''}".strip(),
                         "confirmed": bool(f.get("confirmed")) or x.get("basis") == "엔진"}
                    if _cand_key(c) not in seen:
                        seen.add(_cand_key(c))
                        out.append(c)
                    break
    return out


def _cand_key(c: dict) -> tuple:
    return (c.get("item"), _n(c.get("source")), _n(c.get("fact")))


def mark_stale(res: dict, seen: Path) -> dict:
    """foot 이 쓴 공시 확인 대상을 dsd text 가 문장검토.json 에 적은 대상과 견준다. 다르면 res["stale"] 에 앞뒤 수와 더해진 · 빠진 건을 둔다.
    AI 는 dsd text 가 쓴 문장읽기.md 의 대상만 보고 판정했으니, 다르면 dsd text 를 다시 돌려야 한다."""
    seen = Path(seen)
    if not seen.exists():
        return res
    try:
        old = json.loads(seen.read_text(encoding="utf-8")).get("candidates") or []
    except (ValueError, OSError):
        return res
    a, b = {_cand_key(c) for c in old}, {_cand_key(c) for c in res["candidates"]}
    if a != b:
        res["stale"] = {"before": len(old), "now": len(res["candidates"]),
                        "added": [c for c in res["candidates"] if _cand_key(c) not in a], "gone": [c for c in old if _cand_key(c) not in b]}
    return res


# ---------------------------------------------------------------- 엔진 규칙
_ADDR_PART = re.compile(r"^(?:[가-힣A-Za-z\d·\-]*[가-힣](?:시|도|군|구|읍|면|동|리|가|로|길)|[가-힣\d]*\d+(?:번길|길|로|가)|\d+(?:-\d+)?(?:번지)?|"
                        r"(?:지하)?\d+층|\d+호|\([^()]*\))$")
_ADDR_TAIL = ("에서", "에", "의", "로서")


def _address(tail: str, region: str) -> str:
    """시 · 도 이름부터 주소 낱말(구 · 로 · 길 · 번지 · 층 · 호)만 읽는다. 「서울특별시 강남구에 본사를 두고」 는 「서울특별시 강남구」."""
    got = [region]
    for tok in tail[len(region):].split():
        t = tok.rstrip(",.")
        end = False
        for p in _ADDR_TAIL:
            if t.endswith(p) and _ADDR_PART.match(t[: -len(p)] or "x"):
                t, end = t[: -len(p)], True
                break
        if not _ADDR_PART.match(t):
            break
        got.append(t)
        if end or tok.endswith("."):
            break
    return " ".join(got)


def _addr_prefix(a: str, b: str) -> bool:
    """두 주소가 같거나 더 짧은 쪽이 긴 쪽의 앞부분이다(낱말 단위. 「논현로 508」 은 「논현로 5081」 의 앞부분이 아니다)."""
    x, y = [t for t in re.split(r"[\s,]+", a) if t], [t for t in re.split(r"[\s,]+", b) if t]
    if len(x) > len(y):
        x, y = y, x
    return bool(x) and y[: len(x)] == x


_HEAD_MARK = re.compile(r"^\s*(?:\(\d+\)|\d+[.)]|[가-하][.)]|\([가-하]\)|[①-⑳]|[ⅰ-ⅹ][.)]?)\s*$")


def _f(seg: Seg, rule: str, kind: str, quote: str, fix: str, basis: str) -> dict:
    return {"seg": seg.id, "where": seg.where, "rule": rule, "kind": kind, "quote": quote, "fix": fix, "basis": basis, "by": "엔진"}


def _excerpt(text: str, needle: str, width: int = 40) -> str:
    i = text.find(needle)
    if i < 0:
        return text[:width * 2]
    a, b = max(0, i - width), min(len(text), i + len(needle) + width)
    return ("…" if a else "") + text[a:b] + ("…" if b < len(text) else "")


def _fy(segs: list[Seg], facts: dict) -> date | None:
    v = _vals(facts.get("결산일"))
    if v:
        try:
            return date.fromisoformat(v[0][:10])
        except ValueError:
            pass
    for s in segs:
        if s.part == "표지" and "부터" in s.text and "까지" in s.text:
            ds = _dates(s.text)
            if len(ds) >= 2:
                return ds[1]
    return None


def _fy_start(segs: list[Seg], fy: date) -> date:
    """사업연도 시작일. 표지의 「… 부터 결산일 까지」 에서, 없으면 결산일 1년 전 다음 날."""
    for s in segs:
        if s.part == "표지" and "부터" in s.text and "까지" in s.text:
            ds = _dates(s.text)
            if len(ds) >= 2 and ds[1] == fy:
                return ds[0]
    from datetime import timedelta

    try:
        return date(fy.year - 1, fy.month, fy.day) + timedelta(days=1)
    except ValueError:                                # 2월 29일 결산
        return date(fy.year - 1, fy.month, 28) + timedelta(days=1)


def engine_findings(segs: list[Seg], facts: dict, prior: list[Seg] | None = None) -> list[dict]:
    D = defs()
    out: list[dict] = []
    # 1. 옛 값이 남은 곳(주소 · 대표이사 · 상호가 바뀌었는데 예전 글이 남음)
    for key, f in facts.items():
        if not isinstance(f, dict):
            continue
        new = _vals(f)
        for old in _olds(f):
            for s in segs:
                if _n(old) and _n(old) in _n(s.text):
                    out.append(_f(s, "옛 값", "사실 불일치", _excerpt(s.text, old), f"{old} → {new[0] if new else '(새 값)'}",
                                  f"{key} 가 바뀌었다({f.get('source') or '기준사실'}). 바뀌기 전 값이 남아 있다"))
    # 2. 대표이사 이름
    pat = re.compile(D["ceo_pattern"])
    bad = set(D.get("ceo_not_name") or [])
    want = [_n(x) for x in _vals(facts.get("대표이사"))]
    olds = {_n(x) for x in _olds(facts.get("대표이사"))}
    seen: dict[str, list[Seg]] = {}
    together: set[str] = set()                       # 한 자리에 함께 적힌 공동대표 이름

    def clean(name: str) -> str | None:
        if name in bad or any(name.startswith(b) for b in bad if len(b) >= 2) or name.startswith("대표"):
            return None
        if len(name) >= 3 and name[-1] in PARTICLES and not name.endswith(")"):
            cut = name[:-1]                           # 「대표이사 이가온이」 의 조사. 뗀 이름이 기준 사실에 있거나 4글자면 뗀다
            if _n(cut) in want or _n(cut) in olds or len(name) == 4:
                name = cut
        return name

    more = re.compile(r"\s*(?:[,，、·ㆍ]|및|와|과)\s*([가-힣]{2,4}(?:\(가상\))?)(?![가-힣])")
    roles = ("이사", "감사", "사장", "회장", "위원", "주주", "회사", "법인", "임원")      # 「대표이사 김가온, 사내이사 …」 의 직함은 이름이 아니다
    for s in segs:
        for m in pat.finditer(s.text):
            first = clean(m.group(1))
            if first is None:
                continue
            names, end = [first], m.end()
            if first != m.group(1) and m.group(1)[-1] in "와과":     # 「대표이사 이가온과 박가온」: 조사가 이음말이다
                k = re.compile(r"\s*([가-힣]{2,4}(?:\(가상\))?)(?![가-힣])").match(s.text, end)
                nxt = clean(k.group(1)) if k else None
                if nxt and not nxt.endswith(roles):
                    names.append(nxt)
                    end = k.end()
            while (k := more.match(s.text, end)) is not None:      # 「공동대표이사 최시원, 김재홍」: 둘째 이름부터(2026-10-18 B-7)
                nxt = clean(k.group(1))
                if nxt is None or nxt.endswith(roles):
                    break
                names.append(nxt)
                end = k.end()
            if len(names) > 1:
                together |= {_n(x) for x in names}
            for name in names:
                seen.setdefault(_n(name), []).append(s)
                if want and _n(name) not in want and _n(name) not in olds:
                    out.append(_f(s, "대표이사", "사실 불일치", _excerpt(s.text, name), f"{name} → {' · '.join(_vals(facts['대표이사']))}",
                                  f"기준 사실의 대표이사는 {' · '.join(_vals(facts['대표이사']))}({facts['대표이사'].get('source') or '기준사실'})"
                                  + (". 공동대표이사로 적힌 이름도 모두 견준다" if len(names) > 1 else "")))
    if not want and len(seen) > 1:
        main = max(seen, key=lambda k: len(seen[k]))
        allowed = {main} | (together if main in together else set())
        for k, ss in seen.items():
            if k not in allowed:
                for s in ss:
                    out.append(_f(s, "대표이사", "일관성", _excerpt(s.text, k[:2]), "보고서 안 다른 곳의 대표이사 이름과 맞춘다",
                                  f"보고서 안에서 대표이사 이름이 둘 이상이다({', '.join(seen)})"))
    # 3. 주소
    regions = D.get("regions") or []
    addr_keys = D.get("address_keys") or []
    for key, need_key in (("본점 주소", True), ("감사인 주소", False)):
        vals = [_n(x) for x in _vals(facts.get(key))]
        if not vals:
            continue
        for s in segs:
            if need_key and (s.part == "감사보고서" or not any(k in s.text for k in addr_keys)):
                continue                                              # 감사보고서 절의 주소는 감사인 주소다
            if not need_key and (s.part != "감사보고서" or any(k in s.text for k in addr_keys)):
                continue
            for r in regions:
                i = s.text.find(r)
                if i < 0 or (not need_key and i > 2):
                    continue
                tail = s.text[i:]
                found = _address(tail, r)
                whole = any(re.search(re.escape(v) + r"(?!\d)", _n(tail)) for v in vals)      # 「가온로 55」 는 「가온로 5501」 안에 있지 않다
                if not whole and not any(_addr_prefix(found, x) for x in _vals(facts.get(key))):
                    # 더 짧은 쪽이 긴 쪽의 앞부분이면(「서울특별시 강남구」 ↔ 등기부 전체 주소) 간략 표기라 같은 주소로 본다(2026-10-18 B-7)
                    if any(_n(o) in _n(tail) for o in _olds(facts.get(key))):
                        continue                                      # 옛 값 규칙이 이미 적었다
                    out.append(_f(s, key, "사실 불일치", _excerpt(s.text, found), f"{found} → {_vals(facts[key])[0]}",
                                  f"기준 사실의 {key}({facts[key].get('source') or '기준사실'})와 다르다"))
                break
    # 4. 감사기간(외부감사 실시내용)
    want_r = []
    for x in facts.get("감사기간") or []:
        r = _parse_range(x.get("기간") if isinstance(x, dict) else str(x))
        if r:
            want_r.append((x.get("구분", "") if isinstance(x, dict) else "", r))
    ext = [s for s in segs if s.part == "외부감사 실시내용"]
    got = [(s, r) for s in ext for r in _ranges(s.text)]
    if want_r:
        for label, r in want_r:
            same = [s for s, g in got if g == r]
            if same:
                continue
            near = [(s, g) for s, g in got if label and label in s.text] or \
                   [(s, g) for s, g in got if abs((g[0] - r[0]).days) <= 31]
            if near:
                s, g = near[0]
                out.append(_f(s, "감사기간", "사실 불일치", _excerpt(s.text, _k(g[0])[5:]), f"{_k(g[0])} ~ {_k(g[1])} → {_k(r[0])} ~ {_k(r[1])}",
                              f"기준 사실의 {label or '감사기간'}({_k(r[0])} ~ {_k(r[1])})과 다르다"))
            elif ext:
                out.append(_f(ext[0], "감사기간", "공시 누락", ext[0].text[:60], f"{label} {_k(r[0])} ~ {_k(r[1])} 를 적는다",
                              f"기준 사실의 {label or '감사기간'}이 외부감사 실시내용에 없다"))
    # 4-2. 외부감사 실시내용의 감사대상 사업연도와 수행시기(2026-10-18 B-7: 작년 실시내용이 그대로 남은 dsd)
    fy = _fy(segs, facts)
    if fy:
        fy0 = _fy_start(segs, fy)
        for s in ext:
            ds = _dates(s.text)
            if not ds:
                continue
            if "사업연도" in s.text or "감사대상" in s.text:
                if max(ds) != fy or (len(ds) > 1 and min(ds) != fy0):
                    got_r = f"{_k(min(ds))} ~ {_k(max(ds))}" if len(ds) > 1 else _k(ds[0])
                    out.append(_f(s, "실시내용 사업연도", "사실 불일치", _excerpt(s.text, _k(ds[0])[:5]), f"{got_r} → {_k(fy0)} ~ {_k(fy)}",
                                  f"외부감사 실시내용의 감사대상 사업연도가 보고서의 사업연도({_k(fy0)} ~ {_k(fy)})와 다르다. 작년 실시내용이 남았을 수 있다"))
                continue
            old = sorted({d for d in ds if d < fy0})
            if old:
                out.append(_f(s, "실시내용 날짜", "사실 불일치", _excerpt(s.text, str(old[0].year)), "당기 감사의 수행시기 · 일자로 고친다",
                              f"사업연도 시작일({_k(fy0)}) 앞의 날짜({', '.join(_k(d) for d in old[:3])})가 있다. 작년 외부감사 실시내용이 남았을 수 있다"))
    # 5. 감사보고서일
    rep = [s for s in segs if s.part == "감사보고서"]
    sig = [(s, d) for s in rep for d in _dates(s.text) if _n(s.text) == _n(_k(d)) or re.fullmatch(r"\s*20\d\d\s*년.*일\s*", s.text or "")]
    valid = [(s, d) for s in rep if "감사보고서일" in s.text for d in _dates(s.text)]
    want_d = _vals(facts.get("감사보고서일"))
    want_date = date.fromisoformat(want_d[0][:10]) if want_d else None
    for s, d in sig + valid:
        if want_date and d != want_date:
            out.append(_f(s, "감사보고서일", "사실 불일치", _excerpt(s.text, _k(d)), f"{_k(d)} → {_k(want_date)}",
                          f"기준 사실의 감사보고서일({facts['감사보고서일'].get('source') or '기준사실'})과 다르다"))
    if not want_date and sig and valid and {d for _, d in sig} != {d for _, d in valid}:
        s, d = valid[0]
        out.append(_f(s, "감사보고서일", "일관성", _excerpt(s.text, _k(d)), f"서명 날짜({_k(sig[0][1])})와 맞춘다",
                      "감사인 서명 아래 날짜와 유효 기간 문단의 감사보고서일이 다르다"))
    # 6. 오타 사전 · 기준서 용어 · 반복 낱말 · 띄어쓰기 · 율과 률 · 날짜 쉼표 · 괄호 짝
    typos = D.get("typos") or {}
    terms = D.get("terms") or {}
    ok = set(D.get("repeat_ok") or [])
    rate_ok = set(D.get("rate_ok") or [])
    rep_pat = re.compile(r"(?<![가-힣A-Za-z])([가-힣A-Za-z]{2,})\s+\1(?![가-힣A-Za-z])")
    term_at: dict[str, list[Seg]] = {}
    for s in segs:
        for wrong, right in typos.items():
            if wrong in s.text or (_n(wrong) != wrong and _n(wrong) in _n(s.text)):
                out.append(_f(s, "오타 사전", "오타", _excerpt(s.text, wrong), f"{wrong} → {right}", "오타 사전(definitions/dsd_text.yaml)"))
        for wrong in terms:
            if wrong in s.text:
                term_at.setdefault(wrong, []).append(s)
        for m in rep_pat.finditer(s.text):
            if _HEAD_MARK.match(s.text[:m.start()]):
                continue                                  # 「(1) 자산관련보조금 자산관련보조금(…)을」: 소제목 줄과 본문 첫 낱말이다(2026-10-18 B-7)
            if m.group(1) not in ok:
                out.append(_f(s, "반복 낱말", "오타", _excerpt(s.text, m.group(0)), f"{m.group(0)} → {m.group(1)}", "같은 낱말이 이어서 두 번 적혔다"))
        for m in _COPULA.finditer(s.text):
            out.append(_f(s, "띄어쓰기", "오타", _excerpt(s.text, m.group(0)), f"{m.group(0)} → {m.group(1)}입니다", "「입니다」 는 앞말에 붙여 쓴다"))
        for m in _RATE.finditer(s.text):
            word, fix = m.group(0), _rate_fix(m.group(1), m.group(2))
            if fix and word not in rate_ok:
                out.append(_f(s, "율 · 률", "오타", _excerpt(s.text, word), f"{word} → {m.group(1)}{fix}", "앞 글자에 받침이 있으면(ㄴ 제외) 「률」, 없거나 ㄴ 이면 「율」"))
        for m in _DATE_COMMA.finditer(s.text):
            out.append(_f(s, "날짜 쉼표", "오타", _excerpt(s.text, m.group(0)), f"{m.group(0)} → {m.group(0).replace(',', '.')}", "날짜 구분이 쉼표로 적혔다"))
        bare = _LIST_MARK.sub("", s.text)              # 줄 앞 번호 「1)」 「가)」 의 닫는 괄호는 세지 않는다(한 상장사 2025 감사보고서에서 4건 잘못 잡음, 10-18)
        for a, b in (("(", ")"), ("「", "」"), ("“", "”")):
            if bare.count(a) != bare.count(b):
                out.append(_f(s, "괄호 짝", "오타", s.text[:80], f"{a} {bare.count(a)}개 · {b} {bare.count(b)}개를 맞춘다", "여는 괄호와 닫는 괄호 수가 다르다"))
    for wrong, ss in term_at.items():                  # 같은 옛 용어는 보고서에 한 번만 적는다(한 상장사 2026 반기에서 37칸에 따로 나옴, 10-18)
        more = f". 보고서 안 {len(ss)}곳(" + ", ".join(x.id for x in ss[:8]) + (" 등" if len(ss) > 8 else "") + ")" if len(ss) > 1 else ""
        out.append(_f(ss[0], "기준서 용어", "표현", _excerpt(ss[0].text, wrong), f"{wrong} → {terms[wrong]}", f"기준서의 용어와 다르다(definitions/dsd_text.yaml){more}"))
    # 7. 작년 보고서와 같은 문장에 남은 작년 날짜
    if prior and fy:
        before = {_n(s.text) for s in prior if s.kind == "문단"}
        blob = "".join(_n(x.text) for x in prior) if any(s.part == "작년 보고서" for s in prior) else ""     # PDF 는 줄 끊김이 달라 이어 붙인 글 안에서 찾는다
        for s in segs:
            if s.kind != "문단" or s.part not in ("주석", "감사보고서"):
                continue
            if _n(s.text) not in before and not (blob and len(_n(s.text)) >= 20 and _n(s.text) in blob):
                continue
            old = [d for d in _dates(s.text) if d.year == fy.year - 1]
            if old and not any(d.year == fy.year for d in _dates(s.text)):
                out.append(_f(s, "작년 문장", "사실 불일치", _excerpt(s.text, _k(old[0])), "날짜를 당기로 고치거나 문장이 당기에도 맞는지 확인한다",
                              f"작년 보고서와 같은 문장에 작년 날짜({_k(old[0])})만 있다"))
    # 8. 외부감사 실시내용에 작년 보고서의 날짜가 남은 줄(작년 감사의 회의 · 수행시기를 그대로 옮김)
    if prior:
        before = {d for s in prior if s.part == "외부감사 실시내용" for d in _dates(s.text)}
        flagged = {x["seg"] for x in out if x["rule"] in ("실시내용 사업연도", "실시내용 날짜")}      # 4-2 가 이미 적은 줄은 한 번만
        for s in segs:
            if s.part != "외부감사 실시내용" or s.id in flagged:
                continue
            same = [d for d in _dates(s.text) if d in before]
            if same:
                out.append(_f(s, "작년 실시내용", "일관성", s.text[:60], "당기 감사에서 한 일이 맞는지 확인하고 아니면 뺀다",
                              f"작년 보고서의 외부감사 실시내용에도 같은 날짜({_k(same[0])})가 있다"))
    # 같은 조각 · 같은 규칙 · 같은 발췌는 한 번만
    seen_k, uniq = set(), []
    for x in out:
        k = (x["seg"], x["rule"], x["fix"])
        if k not in seen_k:
            seen_k.add(k)
            uniq.append(x)
    return uniq


# ---------------------------------------------------------------- AI 결과 넣기
KINDS = ("오타", "표현", "사실 불일치", "공시 누락", "일관성")
STATUS = ("공시됨", "공시 안 됨", "해당 없음")


def check_ai(segs: list[Seg], ai: dict, engine: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    """AI 가 적은 것을 원문과 대조한다. 발췌가 그 조각에 글자 그대로 있어야 받는다. (받은 것, 받지 않은 것, 공시 확인)"""
    by = {s.id: s for s in segs}
    eng = {(x["seg"], _n(x["quote"].strip("…"))) for x in engine}
    ok, bad = [], []
    for x in ai.get("findings") or []:
        s = by.get(str(x.get("seg") or ""))
        q = str(x.get("quote") or "")
        why = None
        if s is None:
            why = f"없는 위치 {x.get('seg')}"
        elif not q or _n(q) not in _n(s.text):
            why = "발췌가 원문에 없다(원문 글자 그대로 적는다)"
        elif x.get("kind") not in KINDS:
            why = f"종류는 {' · '.join(KINDS)} 가운데 하나"
        elif not str(x.get("fix") or "").strip() or not str(x.get("basis") or "").strip():
            why = "고칠 안과 근거가 필요하다"
        if why:
            bad.append(dict(x, why=why))
            continue
        dup = any(e_seg == s.id and (_n(q) in e_q or e_q in _n(q)) for e_seg, e_q in eng)
        ok.append({"seg": s.id, "where": s.where, "rule": "AI", "kind": x["kind"], "quote": q, "fix": x["fix"], "basis": x["basis"],
                   "by": "AI", "same_as_engine": dup})
    disc = []
    for x in ai.get("disclosures") or []:
        s = by.get(str(x.get("seg") or "")) if x.get("seg") else None
        st = x.get("status")
        if st not in STATUS:
            bad.append(dict(x, why=f"공시 확인 상태는 {' · '.join(STATUS)} 가운데 하나"))
            continue
        if st == "공시됨" and s is None:
            bad.append(dict(x, why="공시됨이면 공시한 위치(seg)를 적는다"))
            continue
        disc.append({"item": x.get("item"), "source": x.get("source"), "status": st, "seg": s.id if s else "", "where": s.where if s else "",
                     "basis": x.get("basis") or ""})
    return ok, bad, disc


def review(path: Path, facts: dict | None = None, prior: Path | None = None, ai: dict | Path | None = None, case: Path | None = None) -> dict:
    segs = segments(path)
    psegs = segments(prior) if prior else None
    facts = facts or {}
    engine = engine_findings(segs, facts, psegs)
    if isinstance(ai, (str, Path)):
        ai = json.loads(Path(ai).read_text(encoding="utf-8")) if Path(ai).exists() else None
    got, bad, disc = check_ai(segs, ai or {}, engine)
    return {"segments": segs, "engine": engine, "ai": got, "invalid": bad, "disclosures": disc, "candidates": candidates(case),
            "facts": facts, "ai_given": ai is not None}


# ---------------------------------------------------------------- AI 읽기 자료
def reading(res: dict) -> str:
    facts = res["facts"]
    lines = ["# dsd 문장 읽기 자료", "",
             "처음부터 끝까지 읽고 오타 · 어색한 표현 · 사실 불일치 · 공시 누락 · 일관성을 문장.json 에 적는다(형식은 감사-DSD푸팅 스킬 「문장 검토」).",
             "발췌(quote)는 아래 글 그대로 적는다. 엔진이 이미 적은 것은 다시 적지 않아도 된다.", "", "## 기준 사실", ""]
    if facts:
        for k, v in facts.items():
            if isinstance(v, list):
                lines.append(f"- {k}: " + "; ".join(f"{x.get('구분', '')} {x.get('기간', '')}".strip() if isinstance(x, dict) else str(x) for x in v))
            else:
                lines.append(f"- {k}: {' · '.join(_vals(v))}" + (f" (옛 값: {' · '.join(_olds(v))})" if _olds(v) else "")
                             + (f" [{v.get('source')}]" if isinstance(v, dict) and v.get("source") else ""))
    else:
        lines.append("- 기준사실.json 이 없다. 보고서 안 일관성만 본다")
    if res["candidates"]:
        lines += ["", f"## 공시 확인 대상 {len(res['candidates'])}건(감사 폴더 받은자료 사실)", "", "각 건이 주석에 공시됐는지 disclosures 에 적는다.", ""]
        for c in res["candidates"]:
            lines.append(f"- [{c['item']}] {c['fact']} ({c['source']}{', 확인 전' if not c['confirmed'] else ''})")
    lines += ["", f"## 엔진이 찾은 것 {len(res['engine'])}건", ""]
    for x in res["engine"]:
        lines.append(f"- {x['seg']} [{x['kind']} · {x['rule']}] {x['quote']} → {x['fix']}")
    lines += ["", "## 글", ""]
    part = None
    for s in res["segments"]:
        if s.part != part:
            part = s.part
            lines += ["", f"### {part}", ""]
        mark = "**" if s.kind == "제목" else ""
        lines.append(f"{s.id} [{s.kind}{(' ' + str(s.n)) if s.n else ''}] {mark}{s.text}{mark}")
    return "\n".join(lines) + "\n"


def to_json(res: dict) -> dict:
    return {"engine": res["engine"], "ai": res["ai"], "invalid": res["invalid"], "disclosures": res["disclosures"],
            "candidates": res["candidates"], "segments": len(res["segments"])}


def stale_note(res: dict) -> str:
    st = res.get("stale")
    if not st:
        return ""
    return (f"공시 확인 대상이 문장 검토(dsd text) 뒤에 바뀜 {st['before']} → {st['now']}"
            f"(더해짐 {len(st['added'])} · 빠짐 {len(st['gone'])}). 감사 폴더 색인이 그사이 바뀌었다. dsd text 를 다시 돌려 AI 가 새 대상을 판정한다")


# ---------------------------------------------------------------- 엑셀
HEAD = ["번호", "찾은 곳", "종류", "규칙", "위치", "원문 발췌", "고칠 안", "근거", "확인(O · X)", "검토 메모"]
WIDTHS = [7, 7, 11, 11, 30, 50, 40, 40, 10, 30]


def add_sheet(wb, res: dict) -> None:
    from openpyxl.styles import Alignment, PatternFill

    ws = wb.create_sheet(SHEET)
    ws.cell(1, 1, "문장 검토 (표가 아닌 글과 표 안 글자: 오타 · 표현 · 사실 불일치 · 공시 누락 · 일관성)").font = wp.font(size=13, bold=True, color=wp.NAVY)
    n_e, n_a = len(res["engine"]), sum(1 for x in res["ai"] if not x["same_as_engine"])
    ws.cell(2, 1, f"엔진 {n_e}건 · AI {n_a}건" + (" · AI 문장 검토 전(문장.json 없음)" if not res["ai_given"] else "")
            + (f" · 받지 않은 AI 적음 {len(res['invalid'])}건" if res["invalid"] else "")
            + f" · 읽은 글 조각 {len(res['segments'])}개. 확인 칸에 O(고친다) · X(고치지 않는다)를 적는다").font = wp.font(color=wp.MUTED)
    for j, (h, w) in enumerate(zip(HEAD, WIDTHS), 1):
        c = ws.cell(4, j, h)
        c.font, c.fill = wp.font(bold=True, color="FFFFFF"), wp.FILL_H
        ws.column_dimensions[chr(64 + j)].width = w
    row = 5
    order = {k: i for i, k in enumerate(("사실 불일치", "공시 누락", "일관성", "오타", "표현"))}
    items = sorted(res["engine"] + [x for x in res["ai"] if not x["same_as_engine"]], key=lambda x: (order.get(x["kind"], 9), int(x["seg"][1:])))
    yellow = PatternFill("solid", fgColor="FFF2CC")
    for i, x in enumerate(items, 1):
        vals = [i, x["by"], x["kind"], x["rule"], f"{x['seg']} {x['where']}", x["quote"], x["fix"], x["basis"], None, None]
        for j, v in enumerate(vals, 1):
            c = ws.cell(row, j, v)
            c.font = wp.font(color="B3261E" if j == 3 and x["kind"] in ("사실 불일치", "공시 누락") else None)
            c.alignment = Alignment(wrap_text=True, vertical="top")
        ws.cell(row, 9).fill = yellow
        ws.cell(row, 10).fill = yellow
        row += 1
    if not items:
        ws.cell(row, 1, "찾은 것이 없습니다").font = wp.font(color=wp.MUTED)
        row += 1
    row += 1
    if res["candidates"] or res["disclosures"]:
        ws.cell(row, 1, f"공시 확인 대상 {len(res['candidates'])}건 (감사 폴더 받은자료 사실 → 주석 공시 여부)").font = wp.font(size=11, bold=True, color=wp.NAVY)
        row += 1
        if res.get("stale"):
            ws.cell(row, 1, stale_note(res)).font = wp.font(color="B3261E")
            row += 1
        for j, h in enumerate(["번호", "항목", "사실(받은자료)", "", "AI 판정", "공시 위치", "근거", "", "확인(O · X)"], 1):
            c = ws.cell(row, j, h)
            c.font, c.fill = wp.font(bold=True, color="FFFFFF"), wp.FILL_H
        row += 1
        done = {(_n(str(d.get("item"))), _n(str(d.get("source") or ""))) for d in res["disclosures"]}
        rows = [(d["item"], d.get("source") or "", d["status"], f"{d['seg']} {d['where']}".strip(), d["basis"]) for d in res["disclosures"]]
        rows += [(c["item"], f"{c['fact']} ({c['source']})", "AI 판정 전", "", "") for c in res["candidates"]
                 if not any(_n(c["item"]) == a and (not b or b in _n(c["source"]) or b in _n(c["fact"])) for a, b in done)]
        for i, (item, src, st, where, basis) in enumerate(rows, 1):
            for j, v in enumerate([i, item, src, None, st, where, basis, None, None], 1):
                c = ws.cell(row, j, v)
                c.alignment = Alignment(wrap_text=True, vertical="top")
                c.font = wp.font(color="B3261E" if j == 5 and st == "공시 안 됨" else None)
            ws.cell(row, 9).fill = yellow
            row += 1
        row += 1
    if res["invalid"]:
        ws.cell(row, 1, "받지 않은 AI 적음 (발췌가 원문에 없거나 칸이 빠짐)").font = wp.font(size=11, bold=True, color="B3261E")
        row += 1
        for x in res["invalid"]:
            ws.cell(row, 2, str(x.get("seg") or x.get("item") or "")).font = wp.font()
            ws.cell(row, 6, str(x.get("quote") or x.get("fact") or "")).font = wp.font()
            ws.cell(row, 8, x["why"]).font = wp.font(color="B3261E")
            row += 1
    ws.freeze_panes = "A5"


def summary(res: dict) -> str:
    n_a = sum(1 for x in res["ai"] if not x["same_as_engine"])
    kinds = {}
    for x in res["engine"] + [x for x in res["ai"] if not x["same_as_engine"]]:
        kinds[x["kind"]] = kinds.get(x["kind"], 0) + 1
    miss = sum(1 for d in res["disclosures"] if d["status"] == "공시 안 됨")
    return (f"문장 검토 엔진 {len(res['engine'])} · AI {n_a}" + (" (AI 검토 전)" if not res["ai_given"] else "")
            + ("".join(f" · {k} {v}" for k, v in kinds.items()))
            + (f" · 공시 안 됨 {miss}" if miss else "") + (f" · 공시 확인 대상 {len(res['candidates'])}" if res["candidates"] or res.get("stale") else "")
            + (f" · {stale_note(res)}" if res.get("stale") else ""))
