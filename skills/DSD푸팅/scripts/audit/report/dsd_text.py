"""dsd 문장 검토(2026-10-17). 표가 아닌 글(표지 · 감사보고서 · 주석 문단 · 외부감사 실시내용)과 표 안 글자를 읽어
오타 · 표현 · 사실 불일치 · 공시 누락을 찾는다. 숫자 푸팅(dsd_links)과 같은 엑셀에 「문장 검토」 시트로 나온다.

「푸팅은 상호 레퍼도 해야겠지만 오타 표현수정도 다 잡아야 해. 주소수정, 경영진 변경 등 공시필요한 주요 내용 포함해서.
물론 회계감사기간 등 표 이외 것들도」.

맡는 일
  엔진   글을 위치(S번호)와 함께 읽기, 기준 사실(기준사실.json)과 대조(회사명 · 대표이사 · 본점 주소 · 감사인 주소 · 감사기간 · 감사보고서일 ·
         옛 값이 남은 곳), 보고서 안 일관성(대표이사 이름 · 감사보고서일), 오타 사전 · 기준서 용어 · 반복 낱말 · 띄어쓰기(사전 규칙 · 한 글 안 섞임) ·
         율과 률 · 날짜 쉼표 · 괄호 짝,
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
  reading(result) -> str                           AI 가 읽을 문장읽기.md
  reading_parts(result, n) -> [str]                문장읽기를 주석 제목에서 끊어 n 몫으로(에이전트 n 명이 동시에 읽는다)
  merge_ai([문장.json …]) -> dict                  나눈 몫의 문장.json 을 하나로
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
    cells: tuple = ()  # 외부감사 실시내용 표 줄의 원래 칸(빈 칸 포함). 빈칸 규칙이 본다(2026-10-23)
    hdr: tuple = ()    # 그 표의 첫 줄 칸

    @property
    def where(self) -> str:
        h = f" · {self.head}" if self.head and self.head != self.part else ""
        return f"{self.part}{h} · {self.kind} {self.n}" if self.n else f"{self.part}{h} · {self.kind}"


def defs() -> dict:
    return folder.read_yaml(folder.DEFS / "dsd_text.yaml")


def _n(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


# ---------------------------------------------------------------- 읽기
_COVER_TAIL = re.compile(r"\s+(부터|까지)(?=\s|$)")


def _cover(path: Path) -> list[str]:
    if path.suffix.lower() == ".xml":
        return []
    import xml.etree.ElementTree as ET

    from . import dsd_breaks

    try:
        raw, _ = dsd_breaks.prepare(path, text=True)
    except ValueError:
        return []
    root = ET.fromstring(raw)
    c = root.find(".//COVER")
    if c is None:
        return []
    raw = "".join(c.itertext())
    # 표지 기간 표는 날짜와 「부터」 · 「까지」 가 다른 칸이다. 칸 사이 빈칸을 띄어쓰기로 읽어 「01일 부터」 를 지적했다(2026-11-08 회사 dsd S4)
    return [_COVER_TAIL.sub(r"\1", re.sub(r"\s+", " ", x).strip()) for x in raw.split(CR) if x.strip()]


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

    def add(part, head, kind, text, n=0, cells=(), hdr=()):
        out.append(Seg(f"S{len(out) + 1}", part, head, kind, text, n, cells, hdr))

    for i, line in enumerate(_cover(path), 1):
        add("표지", "", "표지", line, i)
    part, head, k_p, k_t = "기타", "", 0, 0
    for b in dsd.read_dsd(path, note_refs=True, text=True):  # 과목 옆 「(주석2)」 를 남겨 AI 가 참조 번호를 맞춰 본다(2026-11-06 N1). 흰 글자는 뺀다(11-08)
        if b[0] == "h" and b[1] == 1:
            part, head, k_p, k_t = b[2], b[2], 0, 0
            continue
        if b[0] == "h":
            head, k_p, k_t = b[2], 0, 0
            add(part, head, "제목", b[2])
            continue
        if b[0] in ("p", "cap"):
            k_p += 1
            if _TOC_LINE.search(b[1]):                # 점선으로 쪽 번호를 잇는 목차 문단. 공시 화면에 목차가 없어 줄바꿈을 되살리지 못하고,
                continue                              # 「13내부회계관리제도」 같은 붙음이 틀린 지적이 됐다(2026-11-09 한 상장사 별도 S3)
            add(part, head, "문단", b[1], k_p)
            continue
        if b[0] == "table":
            k_t += 1
            ext = part == "외부감사 실시내용"
            for r, row in enumerate(b[1], 1):
                cells = [x for x in row if x]
                if any(re.search(r"[가-힣A-Za-z]", x) for x in cells):        # 숫자만 있는 줄은 숫자 푸팅 몫
                    add(part, head, f"표 {k_t} 줄", " | ".join(cells), r, tuple(row) if ext else (), tuple(b[1][0]) if ext and b[1] else ())
    return out


_TOC_LINE = re.compile(r"-{8,}\s*\d+[^-]*-{8,}\s*\d+")


# ---------------------------------------------------------------- 글자 규칙
_NOTE1 = re.compile(r"^\s*1\s*[.)]\s*\S")
_NOTE2 = re.compile(r"^\s*2\s*[.)]\s*\S")
_PLACE = re.compile(r"소재|본점|본사|주소|위치하|(?:특별시|광역시|특별자치시|특별자치도|경기도|강원도|충청북도|충청남도|전라북도|전라남도|경상북도|경상남도|제주도)")
_APPROVE = re.compile(r"승인|확정")


def required_findings(segs: list[Seg]) -> list[dict]:
    """주석에 반드시 적을 것 두 가지가 빠졌는지(2026-11-08, S4 에서 회사 개요 소재지 문단을 지운 것을 세 번 모두 놓쳤다).
    1) 회사 개요(주석 1)에 소재지 · 본점 주소가 없다: 기업회계기준서 제1001호 문단 138(1)
    2) 연차 재무제표 주석에 재무제표 발행승인(승인 · 확정)이 없다: 제1010호 문단 17(반기 · 분기 보고서는 보지 않는다)
    주석 1 제목을 찾지 못하면(제목이 문단 서식) 1) 은 보지 않는다."""
    out = []
    notes = [s for s in segs if s.part == "주석"]
    if not notes:
        return out
    # 주석 제목을 굵은 글씨가 아닌 문단으로 적은 보고서가 있다(2026-11-08 S4v2 팜양주: 「1. 회사의 개요」 가 문단)
    i1 = next((k for k, s in enumerate(notes) if _NOTE1.match(s.text)
               and (s.kind == "제목" or len(s.text) <= 30 or re.search(r"개요|일반", s.text[:20]))), None)
    if i1 is not None:
        i2 = next((k for k in range(i1 + 1, len(notes)) if _NOTE2.match(notes[k].text)), len(notes))
        body = notes[i1:i2]
        # 표 줄은 보지 않는다. 연결 보고서의 종속기업 표 머리 「소재지」 가 지배기업 소재지로 읽혔다(2026-11-08 S4v2 티앤이코리아).
        # 문단 138 은 「재무제표와 함께 공표된 기타 정보에 공시되지 않았다면」 이다. 재무제표 머리 · 표지의 본점 소재지 줄에 주소가 있으면 누락이 아니다
        # (공개 원문 121건에서 주석에만 소재지가 없는 보고서 다섯을 지적했고 다섯 모두 머리에 주소가 있었다)
        head_place = any(_PLACE.search(s.text) for s in segs if s.part != "주석" and not s.kind.startswith("표 ") and s.part != "외부감사 실시내용")
        if len(body) >= 2 and not head_place and not any(_PLACE.search(s.text) for s in body if not s.kind.startswith("표")):
            out.append(_f(notes[i1], "필수 공시", "공시 누락", notes[i1].text[:60], "회사 개요에 본점(등록된 사무소) 소재지를 적는다",
                          "기업회계기준서 제1001호 문단 138(1): 기업의 소재지와 법적 형태, 설립지 국가, 등록된 본점사무소의 주소를 주석으로 공시한다"
                          "(재무제표와 함께 공표된 다른 정보에 없으면). 주석 1 에 소재지 · 본점 · 주소 글이 없다"))
    head = " ".join(s.text for s in segs[:60] if s.part in ("표지", "감사보고서", "기타"))
    interim = bool(re.search(r"반기|분기|중간재무", head))
    if not interim and not any(_APPROVE.search(s.text) and re.search(r"재무제표|발행", s.text) for s in notes):
        out.append(_f(notes[0], "필수 공시", "공시 누락", notes[0].text[:60], "재무제표 발행승인일과 승인자(이사회 · 주주총회)를 주석에 적는다",
                      "기업회계기준서 제1010호 문단 17: 재무제표의 발행승인일과 승인자를 공시한다. 주석에 재무제표 승인 · 확정 글이 없다"))
    return out


def _unpaired(text: str, a: str, b: str) -> tuple[int, int]:
    """짝 없는 여는 괄호 수와 닫는 괄호 수. 닫는 괄호는 앞에 열린 괄호가 있으면 그것을 닫는다. 열린 괄호가 없을 때만 목록 번호(「1)」 「가)」)를
    목록 번호로 본다. 수만 세면 「(주석 27)」 의 「27)」 을 목록 번호로 빼 틀린 지적이 났다(2026-11-08 라벨 세트 31건 가운데 거의 전부)."""
    if a not in text and b not in text:
        return 0, 0
    marks = {m.end() - 1 for m in _LIST_MARK.finditer(text)} if a == "(" else set()
    if a == "(":                                  # 전화번호 지역번호 「031)123-4567」(2026-11-08 S4v2 팜양주)
        marks |= {m.end() - 1 for m in re.finditer(r"(?<![\d(])0\d{1,2}\)(?=\s*\d)", text)}
    depth = stray = 0
    for i, ch in enumerate(text):
        if ch == a:
            depth += 1
        elif ch == b:
            if depth:
                depth -= 1
            elif i not in marks:
                stray += 1
    return depth, stray


# 줄바꿈 표시 「⏎」 뒤도 줄 앞이다(2026-11-08: 「⏎1)」 「⏎2)」 를 짝 없는 괄호로 셌다, 공개 별도 보고서 7건)
_LIST_MARK = re.compile(r"(?:^|(?<=\s)|(?<=\|)|(?<=\u23ce))(?:\d{1,2}|[가나다라마바사아자차카타파하]|[a-z]|[ⅰ-ⅹ])\)(?=\s|$|\u23ce)")
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
# 외부감사 실시내용 표의 「2024.12.2 ~ 2024.12.4」 · 「2024.12.2 ~ 12.4」 꼴(2026-11-06 실제 회사: 이 꼴을 못 읽어 감사기간을
# 모두 「공시 누락」 으로 잘못 짚고, 끝이 시작보다 앞인 「2024.10.11 ~ 2024.10.5」 는 놓쳤다)
_RANGE_DOT = re.compile(r"(?<!\d)(20\d\d)\s*\.\s*(\d{1,2})\s*\.\s*(\d{1,2})\.?\s*[~∼～]\s*(?:(20\d\d)\s*\.\s*)?(\d{1,2})\s*\.\s*(\d{1,2})(?!\d)")


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
    ms = sorted([*_RANGE.finditer(text or ""), *_RANGE_DOT.finditer(text or "")], key=lambda m: m.start())
    for m in ms:
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
    # 도로명주소 끝 괄호 안 참고항목(동 · 건물 이름)은 빼고 적는 회사가 많다. 등기부 주소와 견줄 때 뺀다(2026-11-06 실제 회사 D13)
    a, b = re.sub(r"\([^()]*\)", " ", a), re.sub(r"\([^()]*\)", " ", b)
    x, y = [t for t in re.split(r"[\s,]+", a) if t], [t for t in re.split(r"[\s,]+", b) if t]
    if len(x) > len(y):
        x, y = y, x
    return bool(x) and y[: len(x)] == x


_HEAD_MARK = re.compile(r"^\s*(?:\(\d+\)|\d+[.)]|[가-하][.)]|\([가-하]\)|[①-⑳]|[ⅰ-ⅹ][.)]?)\s*$")


def _xbrl_total(s: "Seg", word: str) -> bool:
    """표 머리줄의 XBRL 합계 열 이름(「부문의 합계 | 부문의 합계 합계」). DART 가 도메인 이름(「부문의 합계」) 뒤에 「합계」 를 붙여 만든 이름이라
    회사가 고칠 오타가 아니다. 같은 줄에 「<도메인 이름>」 칸이 있고 이 칸이 「<도메인 이름> 합계」 일 때만 반복 낱말로 보지 않는다
    (한 상장사 2026 반기 별도 주석27, 2026-11-04)."""
    if not s.kind.startswith("표"):
        return False
    cells = [c.strip() for c in s.text.split(" | ")]
    return any(c.endswith(f"{word} {word}") and c[: -len(word) - 1].strip() in cells for c in cells)


_HOLDING = re.compile(r"[이가은는의]?\s*(?:(?:보통주|우선주|주식|지분율?)\s*)?\d[\d,]*(?:\.\d+)?\s*(?:주(?![당년간])|%)")
def _auditor_sign(segs: list) -> set:
    """감사인 서명란(감사인 주소 · 「회계법인」 · 「감사반」 이름 · 대표이사)의 조각 id. 서명란 대표이사는 감사인 대표라
    회사 대표이사와 견주지 않는다(2026-11-06 다른 회사 시험 N5: 띄어 쓴 회계법인 이름 다음 줄 「대표이사 ○○○」)."""
    out = set()
    for i, s in enumerate(segs):
        if "대표" not in s.text:               # 감사보고서 끝만이 아니다. 내부회계관리제도 감사보고서 서명란도 같다(2026-11-07 상장사 시험 S2865)
            continue
        near = [x for x in segs[max(0, i - 2): i + 1] if x.part == s.part]
        if any(re.search(r"회계법인|감사반", re.sub(r"\s+", "", x.text)) and len(x.text) <= 60 for x in near):
            out.add(s.id)
    return out


_CEO_TITLE = re.compile(r"(?:공동)?대표이사\s*(?:인\s*)?$")


def _holding(text: str, end: int) -> bool:
    """이름 바로 뒤에 주식수 · 지분율이 붙었다(「김가온 240,000주(60%)」 「김가온이 지분 60%를」). 주주 명단의 이름이라 대표이사가 바뀌어도
    이름은 그대로고 직함만 틀린다(2026-10-21 가온정밀 실습 S101: 주주 김가온을 새 대표이사 이가온으로 바꾸라고 냈다)."""
    if _HOLDING.match(text, end):
        return True
    rest = text[end:]                          # 주주현황 표 줄 「김가온 | 64,128 | - | 64,128 | 9.35%」(2026-11-06 실제 회사 D13)
    if not rest.lstrip().startswith("|"):
        return False
    cells = [c.strip() for c in rest.split("|")[1:]]
    return len(cells) >= 2 and all(re.fullmatch(r"[-\d,.]*%?", c) for c in cells) and any(c.endswith("%") for c in cells) \
        and any(re.search(r"\d", c) and not c.endswith("%") for c in cells)


_JOSA = ("에서는", "으로는", "으로서", "으로써", "에서", "으로", "에게", "에는", "에도", "은", "는", "이", "가", "을", "를", "의", "에", "과", "와", "로", "도")
_GLUE_END = ("의", "을", "를", "에", "는", "은", "한", "된", "할", "될", "적인")     # 이 글자로 끝난 말 뒤에 붙은 낱말은 띄어 써야 한다
_STUCK = re.compile(r"^(?:하(?:고|여|는|며|였|지|기|게|면)|한다|합니다|할|함|되(?:고|어|었|는|며|지|기)|된|될|됨|됩니다|적인|적으로|시키)")


def _stem(w: str) -> str:
    """낱말 끝 조사 하나를 뗀다(뗀 뒤 두 글자 이상일 때만)."""
    for j in _JOSA:
        if w.endswith(j) and len(w) - len(j) >= 2:
            return w[: -len(j)]
    return w


def _word_span(text: str, a: int, b: int) -> tuple[int, int]:
    """[a, b) 를 감싼 어절의 처음과 끝. 빈칸과 표 칸 구분(|)에서 끊는다."""
    while a > 0 and not text[a - 1].isspace() and text[a - 1] != "|":
        a -= 1
    while b < len(text) and not text[b].isspace() and text[b] != "|":
        b += 1
    return a, b


def _fs_row(s: Seg) -> bool:
    return s.kind.startswith("표") and "재무제표" in s.part and "주석" not in s.part


def _mixed(text: str) -> list[tuple[int, str, str]]:
    """한 글 안에서 「A B」 와 「AB」 를 함께 쓴 곳 가운데 틀린 쪽이 분명한 것(2026-10-22). (고칠 자리, 띄움 · 붙임, 근거).
    붙인 쪽이 틀림: A 가 조사 · 어미(의 · 을 · 에 · 는 · 한 · 된 …)로 끝난다(「자산의원가에」 「있는경우」). 띈 쪽이 틀림: B 가 「하고 · 되었습니다 ·
    적인」 처럼 앞말에 붙는 말이다(「분류 하고」 「승인 되었습니다」). 둘 다 아니면 「공정가치 측정 · 공정가치측정」 같은 전문 용어라
    맞춤법이 둘 다 허용하니 적지 않는다(공개 감사보고서 15건에서 이런 짝이 절반을 넘었다)."""
    stems = {}
    for m in re.finditer(r"(?<![가-힣])[가-힣]{4,}(?![가-힣])", text):
        stems.setdefault(_stem(m.group(0)), []).append(m.start())
    out = []
    for m in re.finditer(r"(?<![가-힣])(?=([가-힣]{2,}) ([가-힣]{2,})(?![가-힣]))", text):
        x, y = m.group(1), m.group(2)
        at = stems.get(x + _stem(y))
        if not at:
            continue
        why = f"한 글 안에서 「{x} {y}」 와 「{text[at[0]:at[0] + len(x + _stem(y))]}」 를 섞어 썼다"
        if len(x) >= 3 and x.endswith(_GLUE_END):
            out += [(i + len(x), "ins", why) for i in at]
        elif _STUCK.match(y):
            out.append((m.start() + len(x), "del", why))
    return out


def spacing_findings(segs: list[Seg], D: dict, xml: bool = False, skip: dict | None = None) -> list[dict]:
    """띄어쓰기 규칙(definitions/dsd_text.yaml 의 spacing)과 한 글 안에서 「A B」 · 「AB」 를 섞어 쓴 곳(2026-10-22).
    한 상장사 2026 반기 별도 문장 검토에서 AI 가 하나씩 적던 붙여 쓴 띄어쓰기 오타를 엔진으로 옮겼다. 한 어절에 규칙이 여럿 걸리면
    고칠 안 하나로 합친다(「배당에관한사항 → 배당에 관한 사항」). 같은 어절은 보고서에 한 번만 적고 나온 곳(S번호)을 근거에 붙인다.
    skip 은 조각마다 오타 사전이 이미 잡은 낱말이다(같은 곳을 두 번 적지 않는다)."""
    rules = [(r, re.compile(r["pat"])) for r in D.get("spacing") or [] if not (xml and r.get("dsd_only"))]
    skip = skip or {}
    found: dict[tuple, dict] = {}
    places: dict[tuple, list[str]] = {}
    for s in segs:
        fs = _fs_row(s)
        edits: dict[tuple[int, str], str] = {}        # (자리, 띄움 ins · 붙임 del) → 근거. del 의 자리는 지울 빈칸
        taken = [(m.start(), m.end()) for w in skip.get(s.id, ()) for m in re.finditer(re.escape(w), s.text)]
        for r, pat in rules:
            if fs and r.get("fs") is False:
                continue
            for m in pat.finditer(s.text):
                if any(m.group(0) in w for w in skip.get(s.id, ())) or any(a < m.end() and m.start() < b for a, b in taken):
                    continue
                edits.setdefault((m.end("a"), "del") if r.get("join") else (m.start("b"), "ins"), r["basis"])
        if not fs:
            for pos, op, why in _mixed(s.text):
                edits.setdefault((pos, op), why)
        spans: list[list] = []                        # [처음, 끝, [고칠 것]]
        for (pos, op), why in sorted(edits.items()):
            a, b = _word_span(s.text, pos - 1, pos if op == "ins" else pos + 1)
            if spans and a < spans[-1][1]:
                spans[-1][1] = max(spans[-1][1], b)
                spans[-1][2].append((pos, op, why))
            else:
                spans.append([a, b, [(pos, op, why)]])
        for a, b, ed in spans:
            word, fixed = s.text[a:b], s.text[a:b]
            for pos, op, _ in sorted(ed, reverse=True):
                i = pos - a
                fixed = fixed[:i] + " " + fixed[i:] if op == "ins" else fixed[:i] + fixed[i + 1:]
            k = (word, fixed)
            places.setdefault(k, [])
            if s.id not in places[k]:
                places[k].append(s.id)
            if k not in found:
                why = ". ".join(dict.fromkeys(x for _, _, x in ed))
                found[k] = _f(s, "띄어쓰기", "오타", _excerpt(s.text, word), f"{word} → {fixed}", why)
    out = []
    for k, x in found.items():
        if len(places[k]) > 1:
            x["basis"] += f". 보고서 안 {len(places[k])}곳(" + ", ".join(places[k][:8]) + (" 등" if len(places[k]) > 8 else "") + ")"
        out.append(x)
    return out


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


def engine_findings(segs: list[Seg], facts: dict, prior: list[Seg] | None = None, xml: bool = False) -> list[dict]:
    """xml 이면 줄바꿈이 빠진 본문이다. 띄어쓰기 규칙 가운데 dsd_only 를 쓰지 않는다.
    글의 「⏎」 는 원문 줄바꿈이다(2026-11-08 D1). 사실 대조(1 ~ 5, 7 이후)는 「⏎」 를 빈칸으로 본 글로, 오타 · 띄어쓰기 · 괄호(6)는 「⏎」 를 둔 글로 본다
    (줄바꿈 자리는 붙음 · 띄어쓰기가 아니다)."""
    import dataclasses

    from .dsd import BRK

    marked = segs
    segs = [dataclasses.replace(s, text=s.text.replace(BRK, " ")) if BRK in s.text else s for s in segs]
    if prior:
        prior = [dataclasses.replace(s, text=s.text.replace(BRK, " ")) if BRK in s.text else s for s in prior]
    D = defs()
    out: list[dict] = []
    # 1. 옛 값이 남은 곳(주소 · 대표이사 · 상호가 바뀌었는데 예전 글이 남음)
    for key, f in facts.items():
        if not isinstance(f, dict):
            continue
        new = _vals(f)
        src = f.get("source") or "기준사실"
        for old in _olds(f):
            for s in segs:
                if not (_n(old) and _n(old) in _n(s.text)):
                    continue
                at = [m.start() for m in re.finditer(re.escape(old), s.text)] if key == "대표이사" else []
                rename = not at                               # 띄어쓰기가 달라 글자 그대로 못 찾은 곳은 이름을 바꾼다
                for i in at:
                    if not _holding(s.text, i + len(old)):
                        rename = True
                        continue
                    t = _CEO_TITLE.search(s.text, 0, i)       # 직함 없이 주주로만 적힌 전 대표이사 이름은 맞다
                    if t:
                        held = s.text[t.start(): i + len(old)]
                        out.append(_f(s, "옛 값", "사실 불일치", _excerpt(s.text, held), f"「{held}」 의 직함을 빼거나 바꾼다(주주 이름은 그대로 둔다)",
                                      f"{key} 가 바뀌었다({src}). 주식수 · 지분율이 붙은 주주 이름이라 고칠 것은 직함이다. 주주는 주주명부로 확인한다"))
                if rename:
                    out.append(_f(s, "옛 값", "사실 불일치", _excerpt(s.text, old), f"{old} → {new[0] if new else '(새 값)'}",
                                  f"{key} 가 바뀌었다({src}). 바뀌기 전 값이 남아 있다"))
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
    signed = _auditor_sign(segs)
    for s in segs:
        if s.id in signed:
            continue
        for m in pat.finditer(s.text):
            first = clean(m.group(1))
            if first is None:
                continue
            names, end = [(first, m.start(1))], m.end()
            if first != m.group(1) and m.group(1)[-1] in "와과":     # 「대표이사 이가온과 박가온」: 조사가 이음말이다
                k = re.compile(r"\s*([가-힣]{2,4}(?:\(가상\))?)(?![가-힣])").match(s.text, end)
                nxt = clean(k.group(1)) if k else None
                if nxt and not nxt.endswith(roles):
                    names.append((nxt, k.start(1)))
                    end = k.end()
            while (k := more.match(s.text, end)) is not None:      # 「공동대표이사 김가온, 이가온」: 둘째 이름부터(2026-10-18 B-7)
                nxt = clean(k.group(1))
                if nxt is None or nxt.endswith(roles):
                    break
                names.append((nxt, k.start(1)))
                end = k.end()
            if len(names) > 1:
                together |= {_n(x) for x, _ in names}
            for name, at in names:
                held = s.text[m.start(): at + len(name)] if _holding(s.text, at + len(name)) else ""      # 주주 명단의 이름(10-21)
                seen.setdefault(_n(name), []).append((s, held))
                if want and _n(name) not in want and _n(name) not in olds:
                    cur, src = " · ".join(_vals(facts["대표이사"])), facts["대표이사"].get("source") or "기준사실"
                    if held:
                        out.append(_f(s, "대표이사", "사실 불일치", _excerpt(s.text, held), f"「{held}」 의 직함을 빼거나 바꾼다. 이름이 틀린 것이면 주주명부로 확인해 고친다",
                                      f"기준 사실의 대표이사는 {cur}({src}). 주식수 · 지분율이 붙은 주주 이름이다. 전 대표이사가 주주로 남은 것이면 직함만 틀렸다"))
                        continue
                    out.append(_f(s, "대표이사", "사실 불일치", _excerpt(s.text, name), f"{name} → {cur}",
                                  f"기준 사실의 대표이사는 {cur}({src})" + (". 공동대표이사로 적힌 이름도 모두 견준다" if len(names) > 1 else "")))
    if not want and len(seen) > 1:
        main = max(seen, key=lambda k: len(seen[k]))
        allowed = {main} | (together if main in together else set())
        for k, ss in seen.items():
            if k not in allowed:
                for s, held in ss:
                    fix = f"「{held}」 의 직함과 이름을 주주명부로 확인한다(전 대표이사가 주주로 남은 것이면 직함만 고친다)" if held else "보고서 안 다른 곳의 대표이사 이름과 맞춘다"
                    out.append(_f(s, "대표이사", "일관성", _excerpt(s.text, k[:2]), fix, f"보고서 안에서 대표이사 이름이 둘 이상이다({', '.join(seen)})"))
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
    told: set = set()                            # 기준 사실로 고칠 기간을 적은 칸(끝 날짜 지적을 겹쳐 내지 않는다, 2026-11-06)
    if want_r:
        for label, r in want_r:
            same = [s for s, g in got if g == r]
            if same:
                continue
            near = [(s, g) for s, g in got if label and label in s.text] or \
                   [(s, g) for s, g in got if abs((g[0] - r[0]).days) <= 31]
            if near:
                s, g = near[0]
                told.add((id(s), g))
                out.append(_f(s, "감사기간", "사실 불일치", _excerpt(s.text, _k(g[0])[5:]), f"{_k(g[0])} ~ {_k(g[1])} → {_k(r[0])} ~ {_k(r[1])}",
                              f"기준 사실의 {label or '감사기간'}({_k(r[0])} ~ {_k(r[1])})과 다르다"))
            elif ext:
                out.append(_f(ext[0], "감사기간", "공시 누락", ext[0].text[:60], f"{label} {_k(r[0])} ~ {_k(r[1])} 를 적는다",
                              f"기준 사실의 {label or '감사기간'}이 외부감사 실시내용에 없다"))
    for s, g in got:
        if g[1] < g[0] and (id(s), g) not in told:   # 끝이 시작보다 앞인 기간은 기준 사실이 없어도 틀린 글이다
            out.append(_f(s, "감사기간", "사실 불일치", _excerpt(s.text, str(g[1].day)), f"{_k(g[0])} ~ {_k(g[1])} → 끝 날짜를 고친다",
                          "기간의 끝 날짜가 시작 날짜보다 앞이다"))
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
    # 5-2. 필수 공시(2026-11-08): 회사 개요의 소재지 · 재무제표 발행승인
    out += required_findings(segs)
    # 6. 오타 사전 · 기준서 용어 · 반복 낱말 · 띄어쓰기 · 율과 률 · 날짜 쉼표 · 괄호 짝(줄바꿈 표시를 둔 글로 본다)
    plain_segs, segs = segs, marked
    typos = D.get("typos") or {}
    terms = D.get("terms") or {}
    ok = set(D.get("repeat_ok") or [])
    rate_ok = set(D.get("rate_ok") or [])
    rep_pat = re.compile(r"(?<![가-힣A-Za-z])([가-힣A-Za-z]{2,})\s+\1(?![가-힣A-Za-z])")
    term_at: dict[str, list[Seg]] = {}
    typo_at: dict[str, list[str]] = {}
    for s in segs:
        for wrong, right in typos.items():
            if wrong in s.text or (_n(wrong) != wrong and _n(wrong) in _n(s.text)):
                typo_at.setdefault(s.id, []).append(wrong)
                out.append(_f(s, "오타 사전", "오타", _excerpt(s.text, wrong), f"{wrong} → {right}", "오타 사전(definitions/dsd_text.yaml)"))
        for wrong in terms:
            if wrong in s.text:
                term_at.setdefault(wrong, []).append(s)
        for m in rep_pat.finditer(s.text):
            if _HEAD_MARK.match(s.text[:m.start()]):
                continue                                  # 「(1) 자산관련보조금 자산관련보조금(…)을」: 소제목 줄과 본문 첫 낱말이다(2026-10-18 B-7)
            if _xbrl_total(s, m.group(1)):
                continue                                  # 「부문의 합계 합계」: XBRL 도메인 이름 뒤에 DART 가 붙인 「합계」
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
        for a, b in (("(", ")"), ("「", "」"), ("“", "”")):
            left, stray = _unpaired(s.text, a, b)
            if left or stray:
                out.append(_f(s, "괄호 짝", "오타", s.text[:80], f"짝 없는 {a} {left}개 · {b} {stray}개를 맞춘다", "여는 괄호와 닫는 괄호의 짝이 맞지 않는다"))
    for wrong, ss in term_at.items():                  # 같은 옛 용어는 보고서에 한 번만 적는다(한 상장사 2026 반기에서 37칸에 따로 나옴, 10-18)
        more = f". 보고서 안 {len(ss)}곳(" + ", ".join(x.id for x in ss[:8]) + (" 등" if len(ss) > 8 else "") + ")" if len(ss) > 1 else ""
        out.append(_f(ss[0], "기준서 용어", "표현", _excerpt(ss[0].text, wrong), f"{wrong} → {terms[wrong]}", f"기준서의 용어와 다르다(definitions/dsd_text.yaml){more}"))
    out += spacing_findings(segs, D, xml, typo_at)
    segs = plain_segs
    # 7. 작년 보고서와 같은 문장에 남은 작년 날짜
    if prior and fy:
        before = {_n(s.text) for s in prior if s.kind == "문단"}
        blob = "".join(_n(x.text) for x in prior) if any(s.part == "작년 보고서" for s in prior) else ""     # PDF 는 줄 끊김이 달라 이어 붙인 글 안에서 찾는다
        for s in segs:
            if s.kind != "문단" or s.part not in ("주석", "감사보고서"):
                continue
            if _n(s.text) not in before and not (blob and len(_n(s.text)) >= 20 and _n(s.text) in blob):
                continue
            if re.match(r"\s*제\s*\d+\s*(?:\(\s*[당전]\s*\))?\s*기\s*[:：]", s.text):
                continue                          # 「제 18 기 : 2024년 1월 1일부터 …」 는 전기 기간 머리다(2026-11-07 상장사 시험 S217)
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
    out += blank_findings(segs)
    # 같은 조각 · 같은 규칙 · 같은 발췌는 한 번만
    seen_k, uniq = set(), []
    for x in out:
        k = (x["seg"], x["rule"], x["fix"])
        if k not in seen_k:
            seen_k.add(k)
            uniq.append(x)
    return uniq


EXT_UNITS = ("일", "명", "회", "시간")
# 「감사참여자 구분별 인원수 및 감사시간」 표의 열 묶음(외부감사 실시내용 서식). 줄마다 끝 14칸이 묶음마다 당기 · 전기다
EXT_GROUPS = ("품질관리 검토자", "담당이사", "등록 공인회계사", "수습 공인회계사", "전산감사 · 세무 · 가치평가 등 전문가", "건설계약 등 수주산업 전문가", "합계")


def version_spacing(res: dict, changes: list, prev_name: str) -> int:
    """판 비교(dsd_versions)에서 새 판에 띄어쓰기가 빠진 낱말을 문장 검토의 오타로 더한다(2026-11-04 네온테크 v2 → v3: 「2028년3월」 ·
    「날사채권자의」 · 「대하여회사의」). 낱말이 든 S번호를 찾지 못하거나 엔진이 이미 같은 곳을 잡았으면 더하지 않는다. 더한 수."""
    from .dsd_versions import space_lost

    segs = res.get("segments") or []
    n = 0
    for c in changes:
        if c.kind != "변경" or c.unit not in ("문단", "칸", "줄", "머리줄", "제목"):
            continue
        for glued, spaced in space_lost(c.old, c.new):
            seg = next((s for s in segs if glued in s.text), None)
            if seg is None or any(x["seg"] == seg.id and glued in (x.get("quote", "") + x.get("fix", "")) for x in res["engine"]):
                continue
            res["engine"].append(_f(seg, "판 비교 띄어쓰기 빠짐", "오타", _excerpt(seg.text, glued), f"{glued} → {spaced}",
                                    f"옛 판({prev_name})에는 「{spaced}」 로 띄어 썼다"))
            n += 1
    return n


def blank_findings(segs: list[Seg]) -> list[dict]:
    """외부감사 실시내용 표의 빈칸(2026-10-23). 공시된 감사보고서 329건(공개 원문 · 스터디 · 정정공시 짝 · 한 상장사)의 실시내용 표에는
    빈칸이 하나도 없었다(없는 값은 「-」 로 적는다). 회사가 준 dsd 에는 감사인이 채울 칸이 비어 있곤 하다. 가온정밀 실습에서 문장 검토 AI 가
    일수 · 인원 · 장소 · 횟수 · 일자 빈칸을 줄마다 하나씩 적느라 지적의 절반 가까이를 썼다. 엔진이 줄마다 한 번 적는다.
    빈칸 이름: 뒤 칸이 단위(일 · 명 · 회 · 시간)면 「일」 앞 숫자, 앞 칸이 글이면 「그 글」 옆 칸, 첫 줄과 칸 수가 같은 표(커뮤니케이션 표)면
    그 열 이름, 인원수 · 감사시간 표면 열 묶음(「건설계약 등 수주산업 전문가」 당기 · 전기)."""
    out = []
    for s in segs:
        if s.part != "외부감사 실시내용" or not s.cells:
            continue
        cells = [str(x or "").strip() for x in s.cells]
        holes = [j for j, x in enumerate(cells) if j and not x]
        if not holes:
            continue
        hdr = [str(x or "").strip() for x in s.hdr]
        staff = any(_n(h).startswith("품질관리") for h in hdr) and len(cells) >= 15
        base = len(cells) - 14
        names: list[str] = []
        if staff and all(not cells[j] for j in range(base, len(cells))):
            names.append(f"「{' '.join(x for x in cells[:base] if x)}」 줄의 인원수 · 시간 전부")
        else:
            groups: dict[str, list[str]] = {}
            for j in holes:
                nxt = cells[j + 1] if j + 1 < len(cells) else ""
                if staff and j >= base:
                    k = j - base
                    groups.setdefault(EXT_GROUPS[k // 2], []).append("당기" if k % 2 == 0 else "전기")
                elif nxt in EXT_UNITS:
                    names.append(f"「{nxt}」 앞 숫자")
                elif re.search(r"[가-힣A-Za-z]", cells[j - 1]) and cells[j - 1] not in EXT_UNITS:
                    names.append(f"「{cells[j - 1]}」 옆 칸")
                elif len(hdr) == len(cells) and hdr != cells and hdr[j]:
                    names.append(f"「{hdr[j]}」")
            names += [f"「{g}」 {' · '.join(ps)}" for g, ps in groups.items()]
        names = list(dict.fromkeys(names))
        quote = next(x for x in cells if x)
        what = ", ".join(names[:6]) if names else f"빈칸 {len(holes)}곳"
        out.append(_f(s, "실시내용 빈칸", "공시 누락", quote, "빈칸에 값을 적는다(없으면 「-」)",
                      f"외부감사 실시내용 표에 빈칸이 있다({what}). 공시된 감사보고서의 실시내용 표에는 빈칸이 없다(없는 값은 「-」)"))
    return out


# ---------------------------------------------------------------- AI 결과 넣기
KINDS = ("오타", "표현", "사실 불일치", "공시 누락", "일관성")
STATUS = ("공시됨", "공시 안 됨", "해당 없음")


def _same_fix(ai_fix: str, eng_fix: str) -> bool:
    """AI 의 고칠 안이 엔진 것과 같다. 엔진의 「A → B」 에서 B 만 적은 것도 같다."""
    a = _n(ai_fix)
    return a == _n(eng_fix) or ("→" in eng_fix and a == _n(eng_fix.split("→")[-1]))


def check_ai(segs: list[Seg], ai: dict, engine: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    """AI 가 적은 것을 원문과 대조한다. 발췌가 그 조각에 글자 그대로 있어야 받는다. (받은 것, 받지 않은 것, 공시 확인)
    엔진 지적과 같은 곳(같은 S번호, 발췌가 겹침)이라도 고칠 안이 다르면 숨기지 않고 규칙 칸에 「AI(엔진과 같은 곳)」 으로 함께 낸다.
    엔진 발췌는 앞뒤 40자를 붙인 글이라 한 줄의 다른 문제도 겹쳐 보인다(2026-10-21 가온정밀 실습: S227 현장감사 줄의 날짜 지적에
    빈칸 지적이, S101 의 틀린 이름 바꾸기 안에 AI 의 직함 고치기 안이 가려졌다)."""
    by = {s.id: s for s in segs}
    eng = [(x["seg"], _n(x["quote"].strip("…")), x["fix"]) for x in engine]
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
        near = [e_fix for e_seg, e_q, e_fix in eng if e_seg == s.id and (_n(q) in e_q or e_q in _n(q))]
        dup = any(_same_fix(x["fix"], e_fix) for e_fix in near)
        ok.append({"seg": s.id, "where": s.where, "rule": "AI(엔진과 같은 곳)" if near and not dup else "AI", "kind": x["kind"], "quote": q,
                   "fix": x["fix"], "basis": x["basis"], "by": "AI", "same_as_engine": dup})
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


# 회사제시 초안의 감사인 절(2026-11-04 결정, 판단필요 5). 회사가 감사 중에 낸 dsd 에는 외부감사 실시내용 · 감사보고서 본문이
# 비어 있는 것이 보통이다. 이 두 절의 공시 누락 지적은 「감사인 작성 전」 으로 따로 묶고 공시 누락에서 뺀다. 제출 직전 판은 지금처럼 센다
AUDITOR_PARTS = ("외부감사 실시내용", "감사보고서")
DRAFT_KIND = "감사인 작성 전"
STAGES = ("회사제시", "제출")


def stage_of(path: Path) -> str:
    """dsd 가 회사가 낸 초안(회사제시)인지 DART 제출 직전 판(제출)인지. 파일 이름에 「회사제시」 가 있거나 받은자료 폴더 안이면 회사제시다.
    감사-DART 가 만든 제출 파일(8000 감사완결)과 OpenDART 원문은 제출이다. 맞지 않으면 foot · text 의 --stage 로 정한다."""
    p = Path(path)
    return "회사제시" if "회사제시" in p.name or any("받은자료" in x for x in p.parts) else "제출"


def mark_draft(segs: list[Seg], findings: list[dict]) -> int:
    """회사제시 초안이면 감사인이 쓰는 절의 공시 누락 지적을 「감사인 작성 전」 으로 바꾼다. 바꾼 수를 돌려준다."""
    part = {s.id: s.part for s in segs}
    n = 0
    for x in findings:
        if x.get("kind") == "공시 누락" and part.get(x.get("seg")) in AUDITOR_PARTS:
            x["kind"] = DRAFT_KIND
            x["basis"] = (x.get("basis") or "") + " (회사제시 초안이라 감사인이 쓰는 절의 지적은 공시 누락에서 뺐다. 제출 직전 판에서 다시 본다)"
            n += 1
    return n


def review(path: Path, facts: dict | None = None, prior: Path | None = None, ai: dict | Path | None = None, case: Path | None = None,
           stage: str | None = None) -> dict:
    """stage: 회사제시 · 제출. 없으면 stage_of(path) 로 정한다(2026-11-04)."""
    segs = segments(path)
    psegs = segments(prior) if prior else None
    facts = facts or {}
    from . import dsd_breaks

    kind = dsd_breaks.kind_of(Path(path))
    nobreak = kind["줄바꿈"] == "없음"               # 줄바꿈이 빠진 본문(공시 화면 없는 xml · 그것을 바꾼 dsd, 2026-11-08 D2)
    engine = engine_findings(segs, facts, psegs, xml=nobreak)
    if isinstance(ai, (str, Path)):
        ai = json.loads(Path(ai).read_text(encoding="utf-8")) if Path(ai).exists() else None
    got, bad, disc = check_ai(segs, ai or {}, engine)
    stage = stage or stage_of(path)
    drafted = mark_draft(segs, engine + got) if stage == "회사제시" else 0
    return {"segments": segs, "engine": engine, "ai": got, "invalid": bad, "disclosures": disc, "candidates": candidates(case),
            "facts": facts, "ai_given": ai is not None, "xml": nobreak, "원본": kind, "stage": stage, "drafted": drafted}


# ---------------------------------------------------------------- AI 읽기 자료
PART_MIN = 100                                      # 나눈 몫 하나의 글 줄이 이보다 적으면 나누지 않는다


def _units(res: dict) -> list[tuple[Seg, list[str]]]:
    """읽기 자료에 적을 조각과 같은 글이 나온 S번호들. 같은 글은 처음 한 번만 적는다(제목 · 표지는 묶지 않는다)."""
    segs = res["segments"]
    shown = {s.id: _shown(s) for s in segs}
    same: dict[str, list[str]] = {}
    for s in segs:
        if s.kind not in ("제목", "표지"):
            same.setdefault(shown[s.id], []).append(s.id)
    out = []
    for s in segs:
        ids = same.get(shown[s.id], [s.id]) if s.kind not in ("제목", "표지") else [s.id]
        if ids[0] == s.id:
            out.append((s, ids))
    return out


def _line(s: Seg, same: list[str]) -> str:
    """문장읽기의 글 한 줄."""
    mark = "**" if s.kind == "제목" else ""
    tail = f" (같은 글 {len(same) - 1}곳 더: {', '.join(same[1:])})" if len(same) > 1 else ""
    return f"{s.id} [{s.kind}{(' ' + str(s.n)) if s.n else ''}] {mark}{_shown(s)}{mark}{tail}"


def _cuts(units: list, n: int) -> list[int]:
    """units 를 글자 수가 비슷한 n 몫으로 나눌 자리(몫이 시작하는 units 번호). 주석 제목이나 부분이 바뀌는 곳에서만 끊는다."""
    w = [len(_line(s, same)) + 1 for s, same in units]
    total = sum(w)
    # 주석 제목을 굵은 제목이 아닌 문단(「12. 퇴직급여」)으로 적은 보고서는 끊을 자리가 부분 경계뿐이라 한 몫에 몰렸다(2026-11-09 한 상장사 별도
    # 222줄 · 1,502줄). 주석 번호로 시작하는 짧은 문단에서도 끊는다
    def head(s):
        return s.part == "주석" and (s.kind == "제목" or (s.kind == "문단" and len(s.text) <= 40 and re.match(r"^\s*\d{1,2}\s*[.)]\s*\S", s.text)))
    ok = [i for i in range(1, len(units)) if head(units[i][0]) or units[i][0].part != units[i - 1][0].part]
    acc, run = [], 0
    for x in w:
        acc.append(run)
        run += x
    cuts: list[int] = []
    for k in range(1, n):
        cand = [i for i in ok if not cuts or i > cuts[-1]]
        if not cand:
            break
        best = min(cand, key=lambda i: abs(acc[i] - total * k / n))
        if abs(acc[best] - total * k / n) > total * 0.15:      # 목표에서 전체의 15% 넘게 벗어나면 표 줄이 아닌 아무 조각 앞에서 끊는다
            loose = [i for i in range(1, len(units)) if (not cuts or i > cuts[-1]) and not units[i][0].kind.startswith("표")]
            if loose:
                best = min(loose, key=lambda i: abs(acc[i] - total * k / n))
        cuts.append(best)
    return [0] + cuts


def _spacing_names() -> str:
    return " · ".join(r["name"] for r in defs().get("spacing") or [])


def reading(res: dict, part: tuple[int, int, list] | None = None) -> str:
    """AI 가 읽을 문장읽기.md. part 를 주면(몇째, 모두 몇, 그 몫의 units) 나눈 몫 하나만 적는다(reading_parts)."""
    facts = res["facts"]
    units = part[2] if part else _units(res)
    ids = {s.id for s, _ in units}
    for _, more in units:
        ids |= set(more)
    k, n = (part[0], part[1]) if part else (1, 1)
    first, last = (units[0][0].id, units[-1][0].id) if units else ("", "")
    lines = ["# dsd 문장 읽기 자료" + (f" ({k}/{n}: {first} ~ {last})" if n > 1 else ""), "",
             "처음부터 끝까지 읽고 오타 · 어색한 표현 · 사실 불일치 · 공시 누락 · 일관성을 문장.json 에 적는다(형식은 감사-DSD푸팅 스킬의 references/문장-검토.md).",
             "발췌(quote)는 아래 글 그대로 적는다. 엔진이 이미 적은 것은 다시 적지 않는다. 엔진의 고칠 안이 틀렸거나 엔진이 잡은 줄에 다른 문제가 있으면 "
             "그 줄을 발췌해 적는다(엑셀에 엔진 지적과 함께 나온다).",
             f"띄어쓰기는 엔진 규칙({_spacing_names()})이 보고서 전체에서 찾았다. 아래 「엔진이 찾은 것」 에 있는 곳은 다시 적지 않는다. "
             "엔진 규칙이 모든 꼴을 잡지 못하므로, 규칙과 같은 꼴이어도 엔진 목록에 없는 붙음 · 띄어쓰기는 적는다(2026-11-08: 「반기재무제표를작성하고」 를 엔진도 AI 도 놓쳤다).",
             "「표 N-k (dsd 위치로 붙인 번호)」 는 판독이 붙인 번호다. 원문에는 없으니 근거 · 고칠 곳으로 쓰지 않는다. 칸 사이(「|」)와 표지 칸 사이의 빈칸은 원문에서 칸이 나뉜 자리다.",
             "「⏎」 는 원문(편집기의 줄바꿈, 공시 원문이면 공시 화면의 줄바꿈)에서 줄이 바뀐 자리다. 「자본⏎잉여금」 처럼 칸 안에서 줄을 바꾼 것은 띄어쓰기 · 표기 통일로 적지 않는다. "
             "발췌에는 「⏎」 를 그대로 둔다.",
             "표 줄의 「#」 는 숫자 칸이다(값은 숫자 푸팅이 본다. 발췌에 「#」 를 쓰지 않는다). 줄 끝 숫자 칸은 줄였다. 위 줄과 합친 칸(병합 칸)은 아래 줄에 다시 나오지 않아, "
             "칸 수가 머리줄보다 적으면 앞 칸이 위 줄과 합쳐진 것이다. 칸이 빠졌다 · 비었다는 지적은 원문 칸을 보고 적는다."]
    if res.get("xml"):
        lines.append("이 본문에는 문단 안 줄바꿈이 빠져 있다(OpenDART xml 이나 공시 화면 없이 바꾼 dsd). 두 문장이나 목록 항목이 붙어 보인다(「…습니다.회사의」 「측정나머지」). "
                     "붙음 · 띄어쓰기는 오타로 적지 않는다.")
    if n > 1:
        lines += ["", f"보고서 글을 {n} 몫으로 나눈 가운데 {k}번째다. 아래 「글」 에 있는 S번호만 맡는다. 다른 몫은 다른 에이전트가 읽는다. "
                  "주석 참조 번호와 주석 제목은 「목차」 로 맞춰 본다.",
                  "공시 확인 대상은 맡은 글에서 공시한 곳을 찾으면 「공시됨」 과 S번호, 맡은 글에 없으면 「공시 안 됨」 으로 적는다. "
                  "엔진이 몫을 합칠 때 한 몫이라도 공시됨이면 공시됨으로 둔다.",
                  ("필수 공시 목록 대조(스킬 「문장 검토」 3번)는 이 몫이 한다. 앞 몫의 주석은 「목차」 의 제목으로 본다." if k == n
                   else "필수 공시 목록 대조(스킬 「문장 검토」 3번)는 마지막 몫이 한다. 이 몫은 하지 않는다.")]
    lines += ["", "## 기준 사실", ""]
    if facts:
        for key, v in facts.items():
            if isinstance(v, list):
                lines.append(f"- {key}: " + "; ".join(f"{x.get('구분', '')} {x.get('기간', '')}".strip() if isinstance(x, dict) else str(x) for x in v))
            else:
                lines.append(f"- {key}: {' · '.join(_vals(v))}" + (f" (옛 값: {' · '.join(_olds(v))})" if _olds(v) else "")
                             + (f" [{v.get('source')}]" if isinstance(v, dict) and v.get("source") else ""))
    else:
        lines.append("- 기준사실.json 이 없다. 보고서 안 일관성만 본다")
    if res["candidates"]:
        lines += ["", f"## 공시 확인 대상 {len(res['candidates'])}건(감사 폴더 받은자료 사실)", "", "각 건이 주석에 공시됐는지 disclosures 에 적는다.", ""]
        for c in res["candidates"]:
            lines.append(f"- [{c['item']}] {c['fact']} ({c['source']}{', 확인 전' if not c['confirmed'] else ''})")
    if n > 1:
        lines += ["", "## 목차(보고서 전체의 제목)", ""]
        for s in res["segments"]:
            if s.kind == "제목":
                lines.append(f"- {s.id} {s.part} · {s.text}" + ("" if s.id in ids else " (다른 몫)"))
    eng = [x for x in res["engine"] if x["seg"] in ids]
    lines += ["", f"## 엔진이 찾은 것 {len(eng)}건" + (f"(이 몫, 보고서 전체 {len(res['engine'])}건)" if n > 1 else ""), ""]
    for x in eng:
        if x["rule"] == "띄어쓰기":
            lines.append(f"- {x['seg']} [띄어쓰기] {x['fix']}")
        else:
            lines.append(f"- {x['seg']} [{x['kind']} · {x['rule']}] {x['quote']} → {x['fix']}")
    lines += ["", "## 글", "",
              "표 줄은 글자가 든 칸만 적었다(숫자 칸은 숫자 푸팅이 본다). 외부감사 실시내용의 표는 숫자까지 적었다. 같은 글은 처음 한 번만 적고 같은 글이 나온 S번호를 붙였다. "
              "발췌는 그 S번호들의 글에 모두 그대로 있다. 적을 때는 맨 앞 번호를 쓴다.", ""]
    cur = None
    for s, same in units:
        if s.part != cur:
            cur = s.part
            lines += ["", f"### {cur}", ""]
        lines.append(_line(s, same))
    return "\n".join(lines) + "\n"


def reading_parts(res: dict, n: int = 2) -> list[str]:
    """문장읽기를 앞뒤 n 몫으로 나눈다(2026-10-22). 문장 검토 에이전트 n 명이 한 몫씩 동시에 읽는다. 한 상장사 2026 반기 별도는 749줄을
    한 에이전트가 읽어 17.6분이 걸렸다(숫자 쪽 12.7분). 주석 제목에서 끊고, 몫마다 기준 사실 · 공시 확인 대상 · 보고서 전체 목차 ·
    그 몫의 엔진 지적을 싣는다. 글이 짧아 한 몫이 PART_MIN 줄보다 적으면 그만큼 덜 나눈다."""
    units = _units(res)
    n = max(1, min(n, len(units) // PART_MIN))
    if n == 1:
        return [reading(res)]
    cuts = _cuts(units, n) + [len(units)]
    parts = [units[cuts[i]:cuts[i + 1]] for i in range(len(cuts) - 1)]
    return [reading(res, (i + 1, len(parts), u)) for i, u in enumerate(parts)]


def _same_src(a: str, b: str) -> bool:
    """근거 자료 글이 같은 자료다. 문장부호를 빼고 한쪽이 다른 쪽의 앞부분이다."""
    a, b = re.sub(r"[\W_]", "", a or ""), re.sub(r"[\W_]", "", b or "")
    return a.startswith(b) or b.startswith(a)


def merge_ai(parts: list[dict]) -> dict:
    """나눈 몫마다 적은 문장.json 을 하나로 합친다. findings 는 이어 붙이고 같은 S번호 · 발췌 · 고칠 안은 한 번만 둔다.
    disclosures 는 항목이 같고 근거 자료가 같으면(문장부호를 빼고 한쪽이 다른 쪽의 앞부분이면 같다) 한 건으로, 상태는
    공시됨 > 공시 안 됨 > 해당 없음 순으로 고른다(한 몫이라도 공시한 곳을 찾았으면 공시됨). 가온정밀 재기(10-22)에서 한 몫은
    「이사회의사록 2025-09-01」, 다른 몫은 「이사회의사록 2025-09-01 대표이사 선임(…)」 으로 적어 같은 건이 둘로 갈렸다."""
    rank = {"공시됨": 0, "공시 안 됨": 1, "해당 없음": 2}
    findings, seen, disc = [], set(), []
    for p in parts:
        for x in p.get("findings") or []:
            k = (str(x.get("seg")), _n(str(x.get("quote") or "")), _n(str(x.get("fix") or "")))
            if k not in seen:
                seen.add(k)
                findings.append(x)
        for d in p.get("disclosures") or []:
            item = _n(str(d.get("item") or ""))
            at = next((i for i, o in enumerate(disc) if _n(str(o.get("item") or "")) == item
                       and _same_src(str(o.get("source") or ""), str(d.get("source") or ""))), None)
            if at is None:
                disc.append(d)
            elif rank.get(d.get("status"), 9) < rank.get(disc[at].get("status"), 9):
                disc[at] = d
    return {"findings": findings, "disclosures": disc}


def _shown(s: Seg) -> str:
    """읽기 자료에 보일 글. 표 줄은 글자(한글 · 영문)가 든 칸만 남긴다. 「현금및현금성자산 | 12,581,632 | 0」 은 「현금및현금성자산」 이다
    (2026-10-22 실행 시간 P3: 한 상장사 2026 반기 별도 문장읽기 1,333줄 가운데 표 줄 931줄, 그중 533줄이 이름 칸 하나에 숫자 칸).
    외부감사 실시내용의 표는 숫자까지 그대로 둔다. 인원수 · 감사시간은 숫자 푸팅이 보지 않아서, 빼면 빈칸인지 알 수 없다
    (같은 날 가온정밀 재기에서 문장 검토 에이전트가 dsd 원문을 직접 풀어 읽었다)."""
    if not s.kind.startswith("표") or s.part == "외부감사 실시내용":
        return s.text
    # 숫자 칸은 「#」, 「-」 칸은 그대로 둔다. 칸을 통째로 빼면 AI 가 칸이 비었다고 읽었다
    # (2026-11-08 회사 dsd 「교환가액의 조정」 칸 공시 누락, 약정 표에 은행이 빠졌다는 지적 둘 다 틀림)
    out = []
    for c in (x.strip() for x in s.text.split(" | ")):
        if re.search(r"[가-힣A-Za-z]", c):
            out.append(c)
        elif re.fullmatch(r"[-–—]+", c):
            out.append("-")
        elif c:
            out.append("#")
    while out and out[-1] == "#":                 # 줄 끝의 숫자 칸은 줄인다(이름 칸 하나에 숫자 칸들인 줄이 대부분이다)
        out.pop()
    return " | ".join(out)


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


def ai_mark(cell) -> None:
    """AI 작성 칸 모양(audit/style.py). 연보라 · 왼쪽 보라 선 · 보라 글자."""
    from .. import style
    cell.fill, cell.border = style.FILL_AI, style.AI_BOX
    cell.font = style.font(color=style.AI_INK)


def ai_counts(res: dict) -> tuple[int, int]:
    """(AI 문장 지적 수, AI 공시 판정 수). 엔진과 같은 곳을 적은 AI 지적은 따로 줄이 없어 세지 않는다."""
    if not res:
        return 0, 0
    return sum(1 for x in res.get("ai", []) if not x.get("same_as_engine")), len(res.get("disclosures", []))
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
    order = {k: i for i, k in enumerate(("사실 불일치", "공시 누락", "일관성", "오타", "표현", DRAFT_KIND))}
    items = sorted(res["engine"] + [x for x in res["ai"] if not x["same_as_engine"]], key=lambda x: (order.get(x["kind"], 9), int(x["seg"][1:])))
    yellow = wp.FILL_IN
    for i, x in enumerate(items, 1):
        vals = [i, x["by"], x["kind"], x["rule"], f"{x['seg']} {x['where']}", x["quote"], x["fix"], x["basis"], None, None]
        for j, v in enumerate(vals, 1):
            c = ws.cell(row, j, v)
            c.font = wp.font(color=wp.RED if j == 3 and x["kind"] in ("사실 불일치", "공시 누락") else None)
            c.alignment = Alignment(wrap_text=True, vertical="top")
        ws.cell(row, 9).fill = yellow
        ws.cell(row, 10).fill = yellow
        if str(x["by"]).startswith("AI"):             # AI 가 찾은 지적은 발췌 · 고칠 안 · 근거를 연보라로(2026-11-03 조서 공통 서식)
            for j in (6, 7, 8):
                ai_mark(ws.cell(row, j))
        row += 1
    if not items:
        ws.cell(row, 1, "찾은 것이 없습니다").font = wp.font(color=wp.MUTED)
        row += 1
    row += 1
    if res["candidates"] or res["disclosures"]:
        ws.cell(row, 1, f"공시 확인 대상 {len(res['candidates'])}건 (감사 폴더 받은자료 사실 → 주석 공시 여부)").font = wp.font(size=11, bold=True, color=wp.NAVY)
        row += 1
        if res.get("stale"):
            ws.cell(row, 1, stale_note(res)).font = wp.font(color=wp.RED)
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
                c.font = wp.font(color=wp.RED if j == 5 and st == "공시 안 됨" else None)
            if st != "AI 판정 전":                     # AI 의 공시 판정
                for j in (5, 6, 7):
                    ai_mark(ws.cell(row, j))
            ws.cell(row, 9).fill = yellow
            row += 1
        row += 1
    if res["invalid"]:
        ws.cell(row, 1, "받지 않은 AI 적음 (발췌가 원문에 없거나 칸이 빠짐)").font = wp.font(size=11, bold=True, color=wp.RED)
        row += 1
        for x in res["invalid"]:
            ws.cell(row, 2, str(x.get("seg") or x.get("item") or "")).font = wp.font()
            ws.cell(row, 6, str(x.get("quote") or x.get("fact") or "")).font = wp.font()
            ws.cell(row, 8, x["why"]).font = wp.font(color=wp.RED)
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
            + (" · 회사제시 초안(감사인 절 지적은 「감사인 작성 전」)" if res.get("stage") == "회사제시" else "")
            + (f" · {stale_note(res)}" if res.get("stale") else ""))
