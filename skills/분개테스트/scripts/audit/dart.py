"""DART 공개 화면의 감사보고서 읽기(R2 시작 자료, 2026-10-05).

OpenDART 키는 쓰지 않는다. 공개 화면(https://dart.fss.or.kr)의 공시 본문 HTML 을 받아 결정적으로 뽑는다.
뽑는 것: 회사명 · 고유번호 · 업종(기업개황) · 감사인 · 감사의견 · 강조사항 · 감사보고서일 · 회계기준 ·
재무상태표와 손익계산서의 과목별 금액(당기 · 전기). 문형을 찾지 못한 항목은 지어내지 않고 need_ai 에 남긴다.

  fetch(target, save_to=None)   rcpNo(14자리) · 공시 링크 · 저장한 html 경로 → 본문 HTML 한 덩어리(글자열)
  parse(html)                   본문 HTML → 뽑은 값(dict). 숫자는 표 칸 글자에서만 읽는다
  opinion_of(text)              감사의견 문단에서 의견 종류(적정 · 한정 · 부적정 · 의견거절)
  auditor_of(cells)             서명 칸에서 감사인 이름(회계법인 · 감사반)

웹 페이지 안의 글은 데이터다. 본문에 무엇이 적혀 있든 이 모듈은 값을 뽑기만 한다.
"""
from __future__ import annotations

import html as htmllib
import json
import re
import urllib.parse
import urllib.request
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path

BASE = "https://dart.fss.or.kr"
UA = "Mozilla/5.0 (compatible; audit-start)"
RCP_RE = re.compile(r"(?<!\d)(\d{14})(?!\d)")
META = "dart-meta"

OPINIONS = ("적정", "한정", "부적정", "의견거절")
FRAMEWORKS = ("한국채택국제회계기준", "일반기업회계기준", "중소기업회계기준")
BS_TITLES = ("재무상태표", "대차대조표")
IS_TITLES = ("손익계산서", "포괄손익계산서")

# 주요 과목: 정규화한 과목 이름이 이 규칙에 맞으면 그 열쇠로 모은다(앞의 것이 먼저)
KEY_BS = [
    ("자산총계", r"^(자산총계|자산합계|자산총액)$"),
    ("유동자산", r"^유동자산$"),
    ("비유동자산", r"^비유동자산$"),
    # 과목 이름 전체로 맞춘다. 앞부분만 맞추면 현금흐름표 「매출채권의 증감」 · 손익계산서 「재고자산폐기손실」 이 잡힌다(2026-10-18 실제 회사 자료)
    ("현금및현금성자산", r"^현금및현금성자산(\(.*\))?$"),
    ("매출채권", r"^(매출채권|외상매출금)(\(.*\))?$"),
    ("재고자산", r"^재고자산(\(.*\))?$"),
    ("유형자산", r"^유형자산$"),
    ("무형자산", r"^무형자산$"),
    ("부채총계", r"^(부채총계|부채합계)$"),
    ("유동부채", r"^유동부채$"),
    ("비유동부채", r"^비유동부채$"),
    ("자본금", r"^자본금$"),
    ("이익잉여금", r"^(이익잉여금|미처분이익잉여금|이월이익잉여금|결손금|미처리결손금)(\((결손금|주석.*)\))?$"),
    ("자본총계", r"^(자본총계|자본합계)$"),
    ("부채와자본총계", r"^(부채와자본총계|부채및자본총계|부채와자본합계)$"),
]
KEY_IS = [
    ("매출액", r"^(매출액|매출|수익|영업수익|매출수익|수익\(매출액\))$|^매출액\("),
    ("매출원가", r"^매출원가"),
    ("매출총이익", r"^매출총(이익|손실|손익)"),
    ("판매비와관리비", r"^판매비와관리비"),
    ("영업이익", r"^영업(이익|손실|손익)"),
    ("법인세비용차감전순이익", r"^법인세(비용)?차감전"),
    ("법인세비용", r"^법인세(비용|수익)(?!차감)"),
    ("당기순이익", r"^당기순(이익|손실|손익)"),
]


# ---------------------------------------------------------------- 글자 다루기
def norm(s: str) -> str:
    """공백을 모두 지운다(DART 는 '회 계 법 인' 처럼 글자 사이를 띄운다)."""
    return re.sub(r"[\s　\xa0]+", "", s or "")


def item_name(s: str) -> str:
    """표의 과목 이름을 비교용으로 다듬는다. 앞 번호(Ⅰ. 1. (1) 가.)와 주석 표시, 공백을 뗀다."""
    s = norm(s)
    s = re.sub(r"^[\(（]?([ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+|[IVX]+|\d{1,2}|[가-하])[\)）\.]+", "", s)
    s = re.sub(r"\(주석[\d,\s]*\)$", "", s)
    return s.strip(".")


def amount(s: str) -> int | None:
    """표 칸 글자 → 금액. (1,234) · △1,234 · -1,234 는 음수, '-' 하나는 0. 금액 꼴이 아니면 None."""
    t = norm(s)
    if t in ("-", "−", "–"):
        return 0
    neg = False
    if t.startswith("(") and t.endswith(")"):
        neg, t = True, t[1:-1]
    if t[:1] in ("△", "▲", "-", "−"):
        neg, t = True, t[1:]
    if not re.fullmatch(r"\d{1,3}(,\d{3})+|\d+", t):
        return None
    v = int(t.replace(",", ""))
    return -v if neg else v


def opinion_of(text: str) -> str | None:
    """감사의견 문단의 정해진 문형으로 의견을 정한다. 문형이 없으면 None(AI 판독 몫).
    의견거절 · 부적정 · 한정을 먼저 본다(적정 문형이 한정 문단 안에도 들어 있다)."""
    t = norm(text)
    if "의견을표명하지않습니다" in t or "의견거절" in t:
        return "의견거절"
    if "공정하게표시하고있지않습니다" in t or "부적정의견" in t:
        return "부적정"
    if "한정의견" in t or ("제외하고는" in t and "공정하게표시하고있습니다" in t):
        return "한정"
    if "공정하게표시하고있습니다" in t or "적정의견" in t:
        return "적정"
    return None


def auditor_of(cells: list[str]) -> str | None:
    """서명 칸(짧은 글)에서 회계법인 · 감사반 이름. 뒤에서부터 본다(서명은 보고서 끝에 있다)."""
    for c in reversed(cells):
        t = norm(c)
        if not t or len(t) > 30:
            continue
        m = re.fullmatch(r"(.{0,20}?회계법인)(\(유한\))?", t) or re.fullmatch(r"회계법인(.{1,20})", t)
        if m and "회계법인" in t:
            if t.startswith("회계법인") and len(t) > 4:
                return "회계법인 " + t[4:]
            return t
        m = re.fullmatch(r"(.{1,25}감사반)(\(제?\d+호\))?", t)
        if m:
            return t
    return None


def framework_of(text: str) -> str | None:
    t = norm(text)
    for f in FRAMEWORKS:
        if f in t:
            return f
    if "K-IFRS" in t:
        return "한국채택국제회계기준"
    return None


def date_of(text: str) -> str | None:
    m = re.search(r"(20\d\d)년(\d{1,2})월(\d{1,2})일", norm(text))
    return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}" if m else None


TERM_RE = re.compile(r"제\s*(\d{1,3})\s*(?:\(\s*당\s*\)\s*)?기(?=\s|말|\d|$)")


def term_of(texts: list[str]) -> int | None:
    """표지 · 재무제표 머리의 「제 15 기」 · 「제 15 (당) 기」 에서 그 보고서의 기수. 「제 14 (전) 기」 는 보지 않는다.
    처음 나온 것을 쓴다(표지가 맨 앞이다). 없으면 None (2026-10-06)."""
    for t in texts:
        m = TERM_RE.search(str(t))
        if m:
            return int(m.group(1))
    return None


# ---------------------------------------------------------------- HTML → 글 덩어리
class _Blocks(HTMLParser):
    """문서 순서대로 ("p", 글) 과 ("table", [[칸 글]]) 을 모은다. colspan 은 칸을 그만큼 늘린다."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks: list[tuple] = []
        self.comments: list[str] = []
        self.tables: list[list] = []      # 열린 표 쌓기
        self.row: list | None = None
        self.cell: list | None = None
        self.span = 1
        self.para: list[str] = []
        self.skip = 0

    def handle_comment(self, data):
        self.comments.append(data)

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in ("script", "style"):
            self.skip += 1
        elif tag == "table":
            self._flush_para()
            self.tables.append([])
        elif tag == "tr" and self.tables:
            self.row = []
            self.tables[-1].append(self.row)
        elif tag in ("td", "th") and self.tables:
            if self.row is None:
                self.row = []
                self.tables[-1].append(self.row)
            self.cell = []
            try:
                self.span = max(1, min(20, int(dict(attrs).get("colspan") or 1)))
            except ValueError:
                self.span = 1
        elif tag in ("br", "p") and self.cell is not None:
            self.cell.append(" ")
        elif tag == "p" and not self.tables:
            self._flush_para()

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in ("script", "style"):
            self.skip = max(0, self.skip - 1)
        elif tag in ("td", "th") and self.cell is not None and self.row is not None:
            text = re.sub(r"\s+", " ", "".join(self.cell)).strip()
            self.row.extend([text] * self.span)
            self.cell = None
        elif tag == "tr":
            self.row = None
        elif tag == "table" and self.tables:
            t = self.tables.pop()
            self.blocks.append(("table", [r for r in t if any(c for c in r)]))
            self.row = None
        elif tag == "p" and not self.tables:
            self._flush_para()

    def handle_data(self, data):
        if self.skip:
            return
        if self.cell is not None:
            self.cell.append(data)
        elif not self.tables:
            self.para.append(data)

    def _flush_para(self):
        t = re.sub(r"\s+", " ", "".join(self.para)).strip()
        if t:
            self.blocks.append(("p", t))
        self.para = []

    def close(self):
        super().close()
        self._flush_para()


def blocks(html: str) -> tuple[list[tuple], list[str]]:
    p = _Blocks()
    p.feed(html)
    p.close()
    return p.blocks, p.comments


def _texts(bl: list[tuple]) -> list[str]:
    """덩어리를 글 줄 목록으로(표는 칸마다 한 줄)."""
    out = []
    for kind, v in bl:
        if kind == "p":
            out.append(v)
        else:
            for r in v:
                seen = None
                for c in r:
                    if c and c != seen:
                        out.append(c)
                    seen = c
    return out


# ---------------------------------------------------------------- 재무제표 표
def _statement_title(t: str) -> str | None:
    n = norm(t)
    if n.startswith("연결"):
        return None
    if n in BS_TITLES:
        return "bs"
    if n in IS_TITLES:
        return "is"
    return None


def _unit(t: str) -> int | None:
    n = norm(t)
    m = re.search(r"단위[:：]?(백만원|천원|원)", n)
    if not m:
        return None
    return {"원": 1, "천원": 1000, "백만원": 1_000_000}[m.group(1)]


def _parse_statement(table: list[list[str]], mult: int) -> dict[str, list]:
    """머리줄에 '과목' 이 있는 표 → {과목: [당기, 전기]}. 주석 열은 뺀다. 같은 머리 글이 이어진 열을 한 기간으로 묶는다."""
    head_i = next((i for i, r in enumerate(table[:4]) if r and norm(r[0]).replace("과목", "") != norm(r[0])), None)
    if head_i is None:
        return {}
    head = table[head_i]
    groups: list[list[int]] = []
    last = None
    for j, h in enumerate(head):
        n = norm(h)
        if j == 0 or "주석" in n or "과목" in n:
            last = None
            continue
        if groups and n == last:
            groups[-1].append(j)
        else:
            groups.append([j])
        last = n
    if not groups:
        return {}
    out: dict[str, list] = {}
    for r in table[head_i + 1:]:
        if not r or not r[0]:
            continue
        name = item_name(r[0])
        if not name or name in out:
            continue
        vals = []
        for g in groups[:2]:
            v = next((amount(r[j]) for j in g if j < len(r) and amount(r[j]) is not None), None)
            vals.append(None if v is None else v * mult)
        if any(v is not None for v in vals):
            out[name] = vals + [None] * (2 - len(vals))
    return out


def statements(bl: list[tuple]) -> dict:
    """재무상태표 · 손익계산서 제목 뒤 첫 '과목' 표를 읽는다. 단위는 제목과 표 사이 '(단위 : 원)'."""
    out = {"bs": {}, "is": {}, "unit": None}
    cur, mult = None, 1
    for kind, v in bl:
        texts = [v] if kind == "p" else [c for r in v for c in r]
        if kind == "table" and cur and not out[cur] and any(norm(r[0]).find("과목") >= 0 for r in v[:4] if r):
            out[cur] = _parse_statement(v, mult)
            out["unit"] = out["unit"] or {1: "원", 1000: "천원", 1_000_000: "백만원"}[mult]
            cur = None
            continue
        for t in texts:
            st = _statement_title(t)
            if st and not out[st]:
                cur, mult = st, 1
            u = _unit(t)
            if u and cur:
                mult = u
    return out


def signed(name: str, v):
    """과목 이름이 손실 · 결손금이면 양수로 적힌 금액을 음수로 바꾼다. 감사보고서는 「영업손실 9,948,471,730」 · 「결손금 37,759,135,923」 처럼
    부호 없이 이름으로 손실을 나타낸다. 이름에 이익 · 손익이 함께 있으면(「이익잉여금(결손금)」 · 「영업손익」) 적힌 부호를 그대로 둔다."""
    if not isinstance(v, int) or v <= 0:
        return v
    n = norm(name)
    if re.match(r"^(미처리)?결손금", n) or ("손실" in n and "이익" not in n and "손익" not in n):
        return -v
    return v


def key_items(items: dict[str, list], rules: list[tuple]) -> dict[str, list]:
    """요약 과목(자산총계 · 영업이익 등)에 맞는 첫 과목. 손실 · 결손금 과목은 음수로 바꿔 둔다(영업이익 칸에 영업손실이 음수로)."""
    out = {}
    for name, vals in items.items():
        for key, pat in rules:
            if key not in out and re.search(pat, name):
                out[key] = [signed(name, x) for x in vals]
                break
    return out


# ---------------------------------------------------------------- 뽑기
def parse(html: str) -> dict:
    """본문 HTML → {company, corp_code, rcp_no, report_name, auditor, opinion, framework, emphasis, going_concern,
    report_date, fiscal_year_end, bs, is, key_bs, key_is, unit, industry, overview, need_ai}."""
    bl, comments = blocks(html)
    meta = {}
    for c in comments:
        c = c.strip()
        if c.startswith(META):
            try:
                meta.update(json.loads(c[len(META):].strip()))
            except json.JSONDecodeError:
                pass
    lines = _texts(bl)
    # 감사보고서 본문: 첫 재무제표 제목 전까지
    end = next((i for i, t in enumerate(lines) if _statement_title(t) or norm(t).startswith("(첨부)재무제표")), len(lines))
    report = lines[:end]
    report_text = " ".join(report)
    out = {"source": meta.get("source"), "rcp_no": meta.get("rcp_no"), "corp_code": meta.get("corp_code"),
           "report_name": meta.get("report_name"), "company": meta.get("corp_name"), "industry": meta.get("industry"),
           "need_ai": []}

    # 회사명: '주주 및 이사회 귀중' 앞 칸
    for i, t in enumerate(report):
        n = norm(t)
        if n.endswith("귀중"):
            name = n[: n.find("주주")] if "주주" in n else ""
            if not name and i:
                name = norm(report[i - 1])
            if name and not out["company"]:
                out["company"] = name
            break
    # 감사의견 문단: '감사의견' 제목부터 '감사의견근거' 전까지. 없으면 본문 전체
    op_text = report_text
    ni = norm(report_text)
    if "감사의견" in ni:
        a = report_text.find("감사의견")
        b = report_text.find("근거", a + 4)
        op_text = report_text[a: b if b > 0 else None]
    out["opinion"] = opinion_of(op_text) or opinion_of(report_text)
    out["framework"] = framework_of(op_text) or framework_of(report_text)
    out["fiscal_year_end"] = date_of(op_text)
    out["emphasis"] = "강조사항" in ni
    out["going_concern"] = "계속기업관련중요한불확실성" in ni
    out["key_audit_matters"] = "핵심감사사항" in ni
    out["auditor"] = auditor_of(report)
    rd = None
    for t in report:
        n = norm(t)
        if re.fullmatch(r"20\d\d년\d{1,2}월\d{1,2}일", n) and date_of(n) != out["fiscal_year_end"]:
            rd = date_of(n)
    m = re.search(r"감사보고서일\(?(20\d\d년\d{1,2}월\d{1,2}일)", ni)      # 「이 감사보고서는 감사보고서일(2024년 3월 6일) 현재로」
    out["report_date"] = date_of(m.group(1)) if m else rd
    out["term"] = term_of(lines)

    st = statements(bl)
    out["bs"] = {k: v[0] for k, v in st["bs"].items() if v[0] is not None}
    out["is"] = {k: v[0] for k, v in st["is"].items() if v[0] is not None}
    out["bs_prior"] = {k: v[1] for k, v in st["bs"].items() if v[1] is not None}
    out["is_prior"] = {k: v[1] for k, v in st["is"].items() if v[1] is not None}
    out["key_bs"] = key_items(st["bs"], KEY_BS)
    out["key_is"] = key_items(st["is"], KEY_IS)
    out["unit"] = st["unit"]

    # 회사의 개요(주석 1): 글 그대로 앞부분만. 판독 · 요약은 AI 몫
    ov = next((t for t in lines[end:] if re.match(r"^1\.\s*(일반사항|회사의\s*개요|일반적\s*사항)", t.strip())), None)
    if ov:
        ov = re.split(r"(?<=[다\.])\s*2\.\s*(?=[가-힣])", ov, maxsplit=1)[0]   # 주석 2(회계정책) 앞에서 자른다
    out["overview"] = ov[:400] if ov else None

    for k, label in (("company", "회사명"), ("auditor", "감사인"), ("opinion", "감사의견"), ("framework", "회계기준")):
        if not out[k]:
            out["need_ai"].append(f"{label} 문형을 찾지 못했습니다")
    if not out["bs"]:
        out["need_ai"].append("재무상태표 표를 찾지 못했습니다")
    if not out["is"]:
        out["need_ai"].append("손익계산서 표를 찾지 못했습니다")
    return out


# ---------------------------------------------------------------- 받기
def _get(url: str, data: dict | None = None, timeout: int = 30) -> str:
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
        cs = r.headers.get_content_charset() or "utf-8"
    return raw.decode(cs, errors="replace")


def nodes(main_html: str) -> list[dict]:
    """main.do 화면의 목차(node) 목록. [{text, rcpNo, dcmNo, eleId, offset, length, dtd}]"""
    out = []
    for m in re.finditer(r"node\d+\['text'\]\s*=\s*\"(.*?)\";(.*?)(?=node\d+\['text'\]|$)", main_html, re.S):
        body = m.group(2)
        n = {"text": re.sub(r"\s+", " ", m.group(1)).strip()}
        for k in ("rcpNo", "dcmNo", "eleId", "offset", "length", "dtd"):
            km = re.search(rf"node\d+\['{k}'\]\s*=\s*\"(.*?)\";", body)
            n[k] = km.group(1) if km else None
        if n["dcmNo"] and n["eleId"]:
            out.append(n)
    return out


def corp_of(main_html: str) -> tuple[str | None, str | None]:
    m = re.search(r"openCorpInfoNew\('(\d{8})'.*?>\s*([^<]+?)\s*</span>", main_html, re.S)
    if m:
        return m.group(1), htmllib.unescape(m.group(2)).strip()
    m = re.search(r"openCorpInfo(?:New)?\('(\d{8})'", main_html)
    return (m.group(1), None) if m else (None, None)


def corp_info(corp_code: str) -> dict:
    """기업개황 팝업(공개 화면)에서 업종명 · 법인구분 · 회사이름."""
    try:
        h = _get(f"{BASE}/dsae001/selectPopup.ax", {"selectKey": corp_code})
    except Exception:  # noqa: BLE001 - 업종은 없어도 된다
        return {}
    bl, _ = blocks(h)
    cells = _texts(bl)
    out = {}
    for i, c in enumerate(cells[:-1]):
        n = norm(c)
        if n in ("업종명", "법인구분", "회사이름") and n not in out:
            out[n] = cells[i + 1].strip()
    return {"industry": out.get("업종명"), "corp_class": out.get("법인구분"), "corp_full_name": out.get("회사이름")}


def rcp_from(target: str) -> str | None:
    m = re.search(r"rcpNo=(\d{14})", target) or RCP_RE.fullmatch(target.strip())
    return m.group(1) if m else None


def fetch(target: str, save_to: Path | None = None) -> str:
    """rcpNo · 공시 링크 · 저장한 html 경로를 받아 본문 HTML 을 돌려준다. save_to 가 있으면 거기 저장한다.
    네트워크로 받은 것은 맨 앞에 <!-- dart-meta {...} --> 를 붙여 회사 고유번호 · 업종을 함께 남긴다."""
    p = Path(target)
    if not rcp_from(target) or (p.suffix.lower() in (".html", ".htm") and p.exists()):
        if not p.exists():
            raise FileNotFoundError(f"DART 문서를 찾지 못했습니다(rcpNo 14자리 · 공시 링크 · 저장한 html 경로): {target}")
        text = p.read_bytes().decode("utf-8", errors="replace")
    else:
        rcp = rcp_from(target)
        main = _get(f"{BASE}/dsaf001/main.do?rcpNo={rcp}")
        corp, name = corp_of(main)
        tm = re.search(r"<title>(.*?)</title>", main, re.S | re.I)
        meta = {"source": f"{BASE}/dsaf001/main.do?rcpNo={rcp}", "rcp_no": rcp, "corp_code": corp, "corp_name": name,
                "report_name": re.sub(r"\s+", " ", htmllib.unescape(tm.group(1))).strip() if tm else None,
                "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M")}
        if corp:
            meta.update({k: v for k, v in corp_info(corp).items() if v})
        parts = []
        for n in nodes(main):
            q = urllib.parse.urlencode({k: n[k] for k in ("rcpNo", "dcmNo", "eleId", "offset", "length", "dtd") if n[k]})
            body = _get(f"{BASE}/report/viewer.do?{q}")
            bm = re.search(r"<body[^>]*>(.*)</body>", body, re.S | re.I)
            parts.append(f"<!-- dart-node {n['eleId']} {n['text']} -->\n" + (bm.group(1) if bm else body))
        text = (f"<!-- {META} {json.dumps(meta, ensure_ascii=False)} -->\n<html><body>\n" + "\n".join(parts) + "\n</body></html>")
    if save_to:
        Path(save_to).parent.mkdir(parents=True, exist_ok=True)
        Path(save_to).write_text(text, encoding="utf-8")
    return text
