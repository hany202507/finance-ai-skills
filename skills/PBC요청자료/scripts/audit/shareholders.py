"""주주명부 판독(2026-10-18, 「주주명부는 기준을 잘 확인하고 분석해야지」).

영구조서 140 주주명부·임원명부와 받은자료의 주주명부(PDF 글자 층 · OCR(kordoc) 저장본 · 엑셀)를 엔진이 읽는다.

  기준일     문서 안 날짜(「기준일 · 현재」 가 붙은 날짜, 머리의 날짜만 있는 줄) → 파일 이름 연월 → 색인 period. 근거를 함께 둔다
  주식       종류별 주식수(보통주 · 우선주 · 상환전환우선주 · n종 등)와 발행주식 총수. 합계 줄이 있으면 그것, 없으면 주주별 합
  액면가     「액면가 · 1주의 금액 · 액면금액」 이름표 뒤 금액
  주주       주주 수, 상위 주주(주식수 · 지분율), 법인 주주

OCR 글에서 읽은 숫자 · 날짜는 확인 전이다(source 'ocr'). 기준일 판정에는 OCR 날짜를 쓰되 근거에 OCR 을 붙이고,
OCR 숫자로는 이슈 금액을 만들지 않는다(분석 audit/analysis/equity.py). 엔진은 특수관계자 여부를 정하지 않고 후보만 낸다.

  read(path, years=None, period=None) -> dict | None
  facts(r) -> 문서목록 사실 목록
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

KIND = "주주명부·임원명부"
NAME_HEAD = re.compile(r"(주주\s*명|주주\s*성명|주주|성\s*명|이름|name)", re.I)
SHARES_HEAD = re.compile(r"(소유\s*주식|보유\s*주식|주식\s*수|주식의\s*수|총\s*주식\s*수|shares)", re.I)
CLASS_HEAD = re.compile(r"(주식의\s*종류|주식\s*종류|종류|총류|class)", re.I)
RATIO_HEAD = re.compile(r"(지분|비율|%|ratio)", re.I)
CLASS_RE = re.compile(r"(상환\s*전환\s*우선주|전환\s*상환\s*우선주|상환\s*우선주|전환\s*우선주|우선주|보통주|종류주|RCPS|RCP|CPS|(?<![\d,.])\d{1,2}\s*종)")
# 합계 줄 이름. 「합제 · 합게」 는 OCR 오독(2026-10-18 실제 회사 자료 주주명부 둘째 쪽 「합제」)
TOTAL_RE = re.compile(r"^(합\s*[계제게]|총\s*계|계|소\s*계|발행\s*주식\s*(?:의)?\s*총\s*수|total)$", re.I)
OCR_COMMON = re.compile(r"보[홍용풍통]\s*주")        # 「보통주」 OCR 오독(보홍주 · 보용주 · 보풍주)
TOTAL_TEXT = re.compile(r"발행\s*주식\s*(?:의)?\s*총\s*수\s*[:：]?\s*([\d,]+)\s*주")
PAR_RE = re.compile(r"(?:1\s*주의\s*금액|액면\s*(?:가액|가|금액)?|주당\s*액면가?)\s*[:：]?\s*[#₩￦]?\s*([\d,]+)\s*원?")
ASOF_WORDS = ("기준일", "현재", "기준", "as of")
INT_RE = re.compile(r"^\(?\d{1,3}(?:,\d{3})+\)?$|^\d+$")
RATIO_RE = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*%")
DATE_RE = re.compile(r"(\d{4})\s*(?:[-./]|년)\s*(\d{1,2})\s*(?:[-./]|월)\s*(\d{1,2})(?!\d)")
ADDR_RE = re.compile(r"\s(?:(?:서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충청|충남|충북|전라|전남|전북|경상|경남|경북|제주)\S*"
                     r"|\S*(?:특별시|광역시|특별자치시|특별자치도))")
CORP_RE = re.compile(r"(주식회사|㈜|\(주\)|유한회사|투자조합|조합|펀드|Fund|FUND|Ltd|LTD|Limited|LLC|Inc|INC|Corp|Partnership|PARTNERSHIP|Pte|"
                     r"L\.?P\.?|회사|신탁|증권|자산운용|캐피탈|벤처|Investment|Holdings|홀딩스|재단|법인)")
COMMON = "보통주"
PREFERRED = "우선주(종류주)"


def _s(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v).strip()


def _int(v) -> int | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return int(v) if v.is_integer() else None
    s = re.sub(r"\s*주$", "", _s(v))          # 「250 208」 처럼 두 줄이 한 칸에 붙은 것은 숫자로 보지 않는다
    if not s or not INT_RE.match(s):
        return None
    return int(s.strip("()").replace(",", ""))


def _date(s: str) -> date | None:
    m = DATE_RE.search(s or "")
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def class_of(s: str) -> str | None:
    m = CLASS_RE.search(OCR_COMMON.sub("보통주", s or ""))
    if not m:
        return None
    return re.sub(r"\s+", "", m.group(1))


def classes_in(s: str) -> list[str]:
    """글 속 주식 종류를 나온 순서대로(머리줄 「보통주식 상환전환우선주식」)."""
    out = []
    for m in CLASS_RE.finditer(OCR_COMMON.sub("보통주", s or "")):
        lab = re.sub(r"\s+", "", m.group(1))
        if lab not in out:
            out.append(lab)
    return out


def _total_ints(cells: list) -> list[int]:
    """합계 줄의 정수들. 한 칸에 둘이 붙은 것(「383,974 658,255」)은 나눠 읽고, 백분율 · 날짜 칸은 뺀다."""
    out = []
    for c in cells:
        if isinstance(c, (int, float)) and not isinstance(c, bool):
            v = _int(c)
            if v:
                out.append(v)
            continue
        t = _s(c)
        if "%" in t or _date(t):
            continue
        for tok in t.split():
            v = _int(tok)
            if v:
                out.append(v)
    return out


def _split_total(nums: list[int]) -> tuple[int, list[int]] | None:
    """합계 줄 정수 가운데 앞의 둘 이상을 더한 값과 같은 것을 총수로 본다(보통 · 우선 · 합계 꼴)."""
    for k in range(len(nums) - 1, 1, -1):
        for i in range(0, k - 1):
            if sum(nums[i:k]) == nums[k]:
                return nums[k], nums[i:k]
    return None


def group_of(label: str | None) -> str | None:
    if not label:
        return None
    return COMMON if label == "보통주" else PREFERRED


def corporate(name: str) -> bool:
    return bool(CORP_RE.search(name or ""))


# ---------------------------------------------------------------- 줄 얻기
def _excel_rows(path: Path) -> list[tuple[int, list]]:
    from . import reader

    out = []
    wb = reader._open(Path(path))
    try:
        for n, ws in enumerate(wb.worksheets, 1):
            for r in ws.iter_rows(values_only=True):
                cells = list(r)
                if any(c not in (None, "") for c in cells):
                    out.append((n, cells))
    finally:
        wb.close()
    return out


def _pdf_rows(path: Path) -> list[tuple[int, list]]:
    """글자 층 PDF: 낱말을 세로 위치로 줄에 모으고, 가로 틈이 넓은 곳에서 칸을 나눈다."""
    import fitz

    out = []
    doc = fitz.open(str(path))
    try:
        for no, page in enumerate(doc, 1):
            words = sorted(page.get_text("words"), key=lambda w: ((w[1] + w[3]) / 2, w[0]))
            lines: list[list] = []
            for w in words:
                yc = (w[1] + w[3]) / 2
                if lines and abs(lines[-1][0] - yc) <= 3:
                    lines[-1][1].append(w)
                else:
                    lines.append([yc, [w]])
            for _, ws in lines:
                ws.sort(key=lambda w: w[0])
                cells, cur, last = [], [], None
                for w in ws:
                    if last is not None and w[0] - last > 8:
                        cells.append(" ".join(cur))
                        cur = []
                    cur.append(w[4])
                    last = w[2]
                if cur:
                    cells.append(" ".join(cur))
                out.append((no, cells))
    finally:
        doc.close()
    return out


def rows_of(path: Path) -> tuple[list[tuple[int, list]], str | None]:
    """(줄 목록 [(쪽 · 시트 번호, 칸들)], 출처 'excel' · 'text' · 'ocr' · None)."""
    from . import index, ocr, reader

    p = Path(path)
    if p.suffix.lower() in reader.READABLE:
        return _excel_rows(p), "excel"
    if p.suffix.lower() != ".pdf":
        return [], None
    pages = reader.pdf_text(p)
    if any(len(re.sub(r"\s+", "", t)) >= index.NO_TEXT_MIN for _, t in pages):
        return _pdf_rows(p), "text"
    md = ocr.find(p)
    if md is None:
        return [], None
    out = []
    for no, text in ocr.pages_of(md.read_text(encoding="utf-8")):
        out += [(no, r) for r in ocr.rows(text)]
    return out, "ocr"


# ---------------------------------------------------------------- 판독
def _header(cells: list) -> dict | None:
    txt = [_s(c) for c in cells]
    name = next((i for i, t in enumerate(txt) if t and NAME_HEAD.search(t) and not SHARES_HEAD.search(t)), None)
    shares = next((i for i, t in enumerate(txt) if t and SHARES_HEAD.search(t) and i != name), None)
    if name is None:
        name = next((i for i, t in enumerate(txt) if t and NAME_HEAD.search(t)), None)
    cls_cols = {i: class_of(t) for i, t in enumerate(txt) if t and class_of(t) and len(t) <= 12 and i not in (name, shares)}
    if name is None or (shares is None and not cls_cols):
        return None
    return {"name": name, "shares": shares,
            "class": next((i for i, t in enumerate(txt) if t and CLASS_HEAD.search(t) and i not in (name, shares)), None),
            "ratio": next((i for i, t in enumerate(txt) if t and RATIO_HEAD.search(t) and i not in (name, shares)), None),
            "class_cols": cls_cols}


def _clean_name(s: str) -> str:
    s = re.sub(r"^\s*\d{1,4}[.)]?\s+", "", s)
    m = ADDR_RE.search(" " + s)
    if m:
        s = (" " + s)[:m.start()].strip()
    s = CLASS_RE.sub("", s).replace("*", "").strip(" ,·")
    return re.sub(r"\s+", " ", s)


def _free_row(txt: list[str], cells: list) -> tuple[str, str, int] | None:
    """칸 위치에 기대지 않는 주주 줄: 주식 종류 칸을 찾고, 그 앞의 글 칸을 이름, 그 뒤 첫 정수 칸을 주식수로 본다."""
    ci = next((i for i, t in enumerate(txt) if t and class_of(t) and len(t) <= 12), None)
    if ci is None:
        return None
    name = next((_clean_name(t) for t in txt[:ci] if t and not re.fullmatch(r"[\d\s.,]+", t) and _clean_name(t)), None)
    shares = next((_int(c) for c in cells[ci + 1:] if _int(c) is not None), None)
    if not name or shares is None:
        return None
    return name, class_of(txt[ci]), shares


def _asof(rows: list[tuple[int, list]], header_at: int | None) -> date | None:
    """문서 안 기준일. 「기준일 · 현재 · 기준」 이 붙은 날짜가 먼저, 없으면 표 머리 앞의 날짜만 있는 줄."""
    head = rows if header_at is None else rows[:header_at]
    for _, cells in rows[: (header_at or len(rows)) + 2]:
        t = " ".join(_s(c) for c in cells)
        if any(w in t.lower() for w in ASOF_WORDS) and _date(t):
            return _date(t)
    for _, cells in head[:20]:
        t = " ".join(_s(c) for c in cells if _s(c))
        dt = _date(t)
        if dt and re.fullmatch(r"[\d\s.\-/년월일()]+(현재)?", t):
            return dt
    return None


def read(path: Path, years: set[int] | None = None, period: str | None = None) -> dict | None:
    """주주명부 판독. 주주 줄도 합계도 못 찾으면 기준일 · 액면가만 있는 결과를, 아무것도 못 찾으면 None."""
    rows, src = rows_of(Path(path))
    return parse(rows, src, Path(path), years, period)


def parse(rows: list[tuple[int, list]], src: str | None, p: Path, years: set[int] | None = None, period: str | None = None) -> dict | None:
    from .analysis import inst

    if not rows:
        return None
    texts = [" ".join(_s(c) for c in cells if _s(c)) for _, cells in rows]
    hdr_i, hdr = None, None
    for i, (_, cells) in enumerate(rows):
        h = _header(cells)
        if h:
            hdr_i, hdr = i, h
            break
    out = {"path": str(p), "source": src, "as_of": None, "as_of_basis": None, "par": None, "total": None, "total_basis": None,
           "classes": {}, "groups": {}, "holders": [], "holder_count": 0, "unread_rows": 0, "page": None}
    dt = _asof(rows, hdr_i)
    if dt:
        out["as_of"], out["as_of_basis"] = dt.isoformat(), "문서 안 날짜" + (" (OCR, 확인 전)" if src == "ocr" else "")
    else:
        got = inst.file_month(p.stem, years or set(range(2000, 2100)))
        if got:
            out["as_of"], out["as_of_basis"] = got
        elif period and len(str(period)) >= 7:
            out["as_of"], out["as_of_basis"] = str(period)[:10], "색인 period"
    for t in texts:
        m = PAR_RE.search(t)
        if m and (_int(m.group(1)) or 0) >= 100:
            out["par"] = _int(m.group(1))
            break
    explicit = None
    for t in texts:
        m = TOTAL_TEXT.search(t)
        if m:
            explicit = _int(m.group(1))
            break
    if hdr is not None:
        totals: dict[str, int] = {}
        class_labels = classes_in(" ".join(" ".join(_s(c) for c in cells) for _, cells in rows[hdr_i:hdr_i + 2]))
        for no, cells in rows[hdr_i + 1:]:
            txt = [_s(c) for c in cells]
            if _header(cells) and not any(_int(c) for c in cells):
                continue                                  # 쪽마다 되풀이되는 머리줄
            name_cell = txt[hdr["name"]] if hdr["name"] < len(txt) else ""
            first = next((t for t in txt if t), "")
            if TOTAL_RE.match(name_cell.replace(" ", "")) or TOTAL_RE.match(first.replace(" ", "")):
                for i, lab in hdr["class_cols"].items():
                    v = _int(cells[i]) if i < len(cells) else None
                    if v:
                        totals[lab] = v
                v = _int(cells[hdr["shares"]]) if hdr["shares"] is not None and hdr["shares"] < len(cells) else None
                if v:
                    explicit = explicit or v
                cl = class_of(" ".join(txt))
                if cl and v and not hdr["class_cols"]:
                    totals[cl] = v
                if not v and not totals:
                    # 칸 위치가 머리줄과 다른 합계 줄(OCR 둘째 쪽 표): 「보통 + 우선 = 합계」 꼴의 정수를 찾는다
                    got = _split_total(_total_ints(cells))
                    if got:
                        explicit = explicit or got[0]
                        labs = class_labels
                        if len(labs) == len(got[1]):
                            totals.update(dict(zip(labs, got[1])))
                continue
            per: dict[str, int] = {}
            for i, lab in hdr["class_cols"].items():
                v = _int(cells[i]) if i < len(cells) else None
                if v:
                    per[lab] = v
            shares = _int(cells[hdr["shares"]]) if hdr["shares"] is not None and hdr["shares"] < len(cells) else None
            cl = None
            if hdr["class"] is not None and hdr["class"] < len(txt):
                cl = class_of(txt[hdr["class"]])
            cl = cl or class_of(name_cell) or class_of(" ".join(txt))
            name = _clean_name(name_cell)
            if (shares is None and not per) or re.fullmatch(r"\d{1,4}", name_cell.strip() or "x"):
                got = _free_row(txt, cells)              # 머리줄이 없는 다음 쪽 표처럼 칸 위치가 다른 줄
                if got:
                    name, cl, shares = got
            has_num = shares is not None or per
            if not name and not has_num:
                continue
            if not has_num:
                if cl or any(_int(c) is None and re.search(r"\d", _s(c)) for c in cells[1:]):
                    out["unread_rows"] += 1       # 주주 줄인데 주식수를 읽지 못했다(OCR 쉼표 · 점 오독 등)
                continue
            if not name:
                continue
            if per and shares is None:
                shares = sum(per.values())
            ratio = None
            if hdr["ratio"] is not None and hdr["ratio"] < len(cells):
                raw = cells[hdr["ratio"]]
                if isinstance(raw, float) and 0 < raw <= 1:
                    ratio = round(raw * 100, 4)            # 엑셀 백분율 서식(0.2246)
                elif isinstance(raw, (int, float)) and not isinstance(raw, bool):
                    ratio = float(raw)
                else:
                    rt = _s(raw)
                    m = RATIO_RE.search(rt)
                    val = m.group(1) if m else (rt if re.fullmatch(r"\d{1,3}(?:\.\d+)?", rt) else None)
                    ratio = float(val) if val else None
            out["holders"].append({"name": name, "class": cl if not per else " · ".join(per), "shares": shares, "ratio": ratio,
                                   "by_class": per or ({cl: shares} if cl else {}), "corporate": corporate(name), "page": no})
        summed: dict[str, int] = {}
        unknown = 0
        for h in out["holders"]:
            if h["by_class"]:
                for lab, v in h["by_class"].items():
                    summed[lab] = summed.get(lab, 0) + v
            else:
                unknown += h["shares"]
        out["holders_sum"] = sum(h["shares"] for h in out["holders"])
        if totals:
            out["classes"] = totals
            out["total"] = explicit or sum(totals.values())
            out["total_basis"] = "합계 줄"
        elif explicit:
            out["classes"] = summed if sum(summed.values()) + unknown == explicit else {}
            out["total"], out["total_basis"] = explicit, "합계 줄"
        elif out["holders"]:
            out["classes"] = summed
            if unknown:
                out["classes"]["종류 모름"] = unknown
            out["total"], out["total_basis"] = sum(h["shares"] for h in out["holders"]), "주주별 합"
        out["holder_count"] = len(out["holders"])
        out["page"] = rows[hdr_i][0]
    elif explicit:
        out["total"], out["total_basis"] = explicit, "합계 줄"
    for lab, v in out["classes"].items():
        g = group_of(lab) or lab
        out["groups"][g] = out["groups"].get(g, 0) + v
    tot = out["total"]
    for h in out["holders"]:
        if h["ratio"] is None and tot:
            h["ratio_calc"] = round(h["shares"] / tot * 100, 2)
    if not (out["as_of"] or out["par"] or out["total"] or out["holders"]):
        return None
    return out


def top(r: dict, n: int = 5) -> list[dict]:
    return sorted(r.get("holders") or [], key=lambda h: -h["shares"])[:n]


def pct(h: dict) -> float | None:
    return h.get("ratio") if h.get("ratio") is not None else h.get("ratio_calc")


# ---------------------------------------------------------------- 문서목록 사실
FACT_PREFIX = "주주명부 "


def facts(r: dict) -> list[dict]:
    """문서목록 사실(basis 엔진). OCR 에서 나온 숫자 · 날짜 사실은 source 'ocr' · confirmed false 다."""
    ocr = r.get("source") == "ocr"
    tag = " (OCR, 확인 전)" if ocr else ""
    out = []

    def add(text, value=None, page=None):
        f = {"text": text, "basis": "엔진", "value": value}
        if page:
            f["source_page"] = f"{page}쪽" if r.get("source") != "excel" else f"{page}번째 시트"
        if ocr:
            f.update(source="ocr", confirmed=False)
        out.append(f)

    if r.get("as_of"):
        add(f"기준일 {r['as_of']}({r['as_of_basis']})")
    else:
        add(f"{FACT_PREFIX}기준일 확인 필요(문서 · 파일 이름에 날짜 없음)")
    if r.get("total"):
        cls = " · ".join(f"{k} {v:,}" for k, v in r["classes"].items())
        add(f"{FACT_PREFIX}발행주식 총수 {r['total']:,}주({r['total_basis']}{', ' + cls if cls else ''}){tag}", r["total"], r.get("page"))
    if r.get("par"):
        add(f"{FACT_PREFIX}액면가 {r['par']:,}원{tag}", r["par"])
    if r.get("holder_count"):
        add(f"{FACT_PREFIX}주주 {r['holder_count']}명(법인 {sum(1 for h in r['holders'] if h['corporate'])}명){tag}", r["holder_count"])
        for h in top(r, 3):
            p = pct(h)
            add(f"{FACT_PREFIX}상위 주주 {h['name']} {h['shares']:,}주" + (f"({p:g}%)" if p is not None else "") + tag, h["shares"], h.get("page"))
    hs = r.get("holders_sum")
    if r.get("total_basis") == "합계 줄" and hs and hs != r.get("total"):
        add(f"{FACT_PREFIX}주주별 합 {hs:,} ≠ 합계 {r['total']:,}, 쪽 그림 대조 필요{tag}", hs)
    if r.get("unread_rows"):
        add(f"{FACT_PREFIX}주식수를 읽지 못한 주주 줄 {r['unread_rows']}개{tag}", r["unread_rows"])
    return out
