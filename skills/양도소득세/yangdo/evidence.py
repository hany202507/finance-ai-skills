# -*- coding: utf-8 -*-
"""증빙 자료(매매계약서, 영수증, 세금계산서 등)에서 읽어 낸 값을 검증해 사실관계에 넣는다.

문서를 읽는 일은 Claude 가 한다. 이 모듈은 읽는 일을 하지 않고, Claude 가 적은 값이 증빙 원문에 실제로 있는지
대조하고(지어낸 값 걸러내기), 사실관계에 이미 있는 값과 부딪히는지 가른 뒤, 대조를 통과한 값만 넣는다.

추출 한 건의 모양:
  {"문항": "A11", "자산": "A", "값": "2026-11-15",
   "출처": {"문서": "D01", "쪽": 2, "발췌": "잔금은 2026년 11월 15일에 지급한다"},
   "확신": "확실" | "불확실", "비고": ""}

판정:
  반영   글자층이 있는 문서에서 발췌가 원문에 있고 값이 발췌에 있으며 확신이 「확실」이고 사실관계에 다른 값이 없다
  일치   이미 같은 값이 있다(교차 확인으로 세어 보여 준다)
  충돌   이미 다른 값이 있다. 덮어쓰지 않는다

경비 목록 문항(M08~M11)은 서류마다 따로 낸다. 이번 실행에서 넣은 목록에는 다음 서류의 줄을 이어 붙인다.
같은 줄은 일치로 세고, 지급일·금액이 같은데 다른 칸이 다른 줄은 같은 지출을 서류 두 장으로 낸 것일 수 있어 충돌로 올린다.
사실관계에 원래 있던 목록은 늘리지 않는다(충돌).
  확인필요  스캔본·사진이거나 확신이 불확실이거나 값이 발췌에서 대조되지 않는다. 정황만 보여 주는 값(A07 등기)은 제안으로 둔다.
           사용자가 확인표에서 고른다
  거절   없는 문항, 없는 문서, 글자층 원문에 없는 발췌, 형식이 틀린 값, 인적사항, 번지가 든 소재지 발췌

값이 발췌에 있는지는 날짜·금액(value_problem), 선택 값의 낱말(choice_problem), 소재지(address_problem)로 본다.
특약에 조항이 「없다」는 값(A13 아니오, A14 0원)은 발췌로 보일 수 없어 문서 전체에서 그 조항의 낱말을 찾는다(absence_problem).
"""
import copy
import json
import os
import re
import zipfile

from yangdo import facts as F
from yangdo import questions as Q
from yangdo.regions import SIDO_SHORT

PDF = ".pdf"
IMAGES = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".heic")
PLAIN = (".txt", ".md", ".csv")
MIN_CHARS_PER_PAGE = 20          # 쪽당 글자가 이보다 적으면 스캔본으로 본다
RRN = re.compile(r"(?<!\d)\d{6}\s*-?\s*[1-8]\d{6}(?!\d)")
DATE = re.compile(r"(\d{4})\s*[.\-/년]\s*(\d{1,2})\s*[.\-/월]\s*(\d{1,2})")
NUMBER = re.compile(r"\d[\d,]*\d|\d")
UNIT_SPAN = re.compile(r"(?:\d[\d,]*\s*(?:억|천만|백만|십만|만)\s*)+(?:\d[\d,]*\s*(?:천|백|십)?)?\s*원?")
UNIT_TOKEN = re.compile(r"(\d[\d,]*)\s*(억|천만|백만|십만|만|천|백|십)?")
MULTIPLIER = {"억": 10 ** 8, "천만": 10 ** 7, "백만": 10 ** 6, "십만": 10 ** 5, "만": 10 ** 4, "천": 1000, "백": 100, "십": 10, None: 1, "": 1}


class EvidenceError(Exception):
    """사용자에게 그대로 보여 줄 문장을 든 오류."""


# ---- 문서 읽기 -------------------------------------------------------------

def _squash(s):
    return re.sub(r"\s+", "", str(s))


def _docx_text(path):
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml").decode("utf-8", "replace")
    paras = re.findall(r"<w:p[ >].*?</w:p>", xml, flags=re.S)
    return ["\n".join(re.sub(r"<[^>]+>", "", re.sub(r"</w:t>\s*<w:t[^>]*>", "", p)) for p in paras)]


def _xlsx_text(path):
    import openpyxl
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    pages = []
    for ws in wb.worksheets:
        rows = []
        for r in ws.iter_rows(values_only=True):
            cells = [str(c) for c in r if c is not None]
            if cells:
                rows.append(" ".join(cells))
        pages.append("\n".join(rows))
    return pages


def read_pages(path):
    """쪽별 글자 목록. 글자를 읽을 수 없는 종류는 빈 목록."""
    ext = os.path.splitext(path)[1].lower()
    if ext == PDF:
        import fitz
        with fitz.open(path) as d:
            return [p.get_text() for p in d]
    if ext in PLAIN:
        for enc in ("utf-8-sig", "cp949"):
            try:
                with open(path, encoding=enc) as f:
                    return [f.read()]
            except UnicodeDecodeError:
                continue
        return []
    if ext == ".docx":
        return _docx_text(path)
    if ext == ".xlsx":
        return _xlsx_text(path)
    return []


def inventory(folder):
    """폴더의 증빙 파일 목록. 문서 id(D01, D02, ...)는 파일 이름 순서로 붙인다."""
    if not os.path.isdir(folder):
        raise EvidenceError("증빙 폴더가 없다: %s" % folder)
    docs = []
    names = []
    for d, _, files in os.walk(folder):
        for n in files:
            if not n.startswith(".") and not n.startswith("~$"):
                names.append(os.path.join(d, n))
    for i, p in enumerate(sorted(names), 1):
        ext = os.path.splitext(p)[1].lower()
        try:
            pages = read_pages(p)
        except Exception as e:  # 깨진 파일은 목록에 올리되 글자층 없음으로 둔다
            pages, note = [], "파일을 열지 못했다(%s)" % type(e).__name__
        else:
            note = None
        chars = sum(len(_squash(t)) for t in pages)
        layer = bool(pages) and chars >= MIN_CHARS_PER_PAGE * len(pages)
        if note is None and not layer:
            if ext in IMAGES:
                note = "사진·스캔 이미지라 글자 대조를 할 수 없다. 화면으로 읽고 확신을 「불확실」로 적는다"
            elif ext == PDF:
                note = "글자층이 없는 PDF(스캔본)라 글자 대조를 할 수 없다. 화면으로 읽고 확신을 「불확실」로 적는다"
            elif ext == ".hwp" or ext == ".hwpx":
                note = "한글 파일은 읽지 못한다. PDF 로 저장해 다시 넣는다"
            else:
                note = "글자를 읽을 수 없는 종류다"
        docs.append({"id": "D%02d" % i, "파일": os.path.relpath(p, folder).replace(os.sep, "/"), "종류": ext.lstrip(".") or "없음",
                     "쪽수": len(pages) or None, "글자수": chars, "글자층": layer, "안내": note})
    return {"폴더": os.path.abspath(folder), "문서": docs}


def load_texts(inv):
    """목록의 글자층 문서마다 쪽별 글자. 문서 id 에서 쪽 목록으로."""
    out = {}
    for d in inv["문서"]:
        if d["글자층"]:
            out[d["id"]] = read_pages(os.path.join(inv["폴더"], d["파일"]))
    return out


# ---- 값이 발췌에 있는지 -----------------------------------------------------

def dates_in(text):
    out = set()
    for y, m, d in DATE.findall(text):
        out.add("%04d-%02d-%02d" % (int(y), int(m), int(d)))
    return out


def amounts_in(text):
    """발췌에서 읽을 수 있는 금액(원). 쉼표 숫자, 「5억 3천만원」, 「3,000만원」, 「2억」 꼴을 읽는다."""
    out = set()
    masked = text
    for m in UNIT_SPAN.finditer(text):
        total = 0
        for num, unit in UNIT_TOKEN.findall(m.group(0)):
            total += int(num.replace(",", "")) * MULTIPLIER[unit or None]
        out.add(total)
        masked = masked.replace(m.group(0), " ", 1)
    for tok in NUMBER.findall(masked):
        n = tok.replace(",", "")
        if n.isdigit():
            out.add(int(n))
    return out


def _leaves(v):
    if isinstance(v, dict):
        for x in v.values():
            yield from _leaves(x)
    elif isinstance(v, (list, tuple)):
        for x in v:
            yield from _leaves(x)
    else:
        yield v


def value_problem(value, quote):
    """값의 날짜와 금액이 발췌에 없으면 그 문장. 날짜·금액이 아닌 값(선택, 예아니오, 이름)은 대조하지 않는다."""
    ds, am = dates_in(quote), amounts_in(quote)
    for v in _leaves(value):
        if isinstance(v, bool) or v is None:
            continue
        if isinstance(v, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
            if v not in ds:
                return "날짜 %s 가 발췌에 없다" % v
        elif isinstance(v, (int, float)) and not isinstance(v, bool):
            if v == 0:
                continue
            if int(v) not in am:
                return "금액 %s 가 발췌에 없다" % format(int(v), ",")
    return None


# 선택 문항의 코드마다 발췌에 하나는 있어야 하는 낱말(띄어쓰기는 보지 않는다). 표에 있는 문항과 코드만 대조한다.
# None 인 코드는 문서만으로 정하지 않는 값이다(오피스텔·근린생활시설을 집으로 썼는지는 사실의 문제). 늘 확인필요다.
# 다른 코드의 낱말이나 CHOICE_BLOCK 의 낱말이 함께 나오면 문서가 한 값으로 정하지 못한 것이라 확인필요다.
RESIDENTIAL = ("아파트", "연립주택", "다세대주택", "단독주택", "다가구주택", "공동주택")
MIXED_USE = ("근린생활", "상가", "점포", "사무소", "오피스텔", "업무시설")   # 주택과 다른 용도가 섞였거나 주거용인지 문서로 모르는 건물
CHOICE_WORDS = {
    "P02": {"주택": RESIDENTIAL},
    "P03": {"매매": ("매매계약",), "경매": ("매각허가", "매각대금", "경매")},
    "A04": {"아파트": ("아파트",), "연립다세대": ("연립", "다세대"), "단독주택": ("단독주택",), "다가구주택": ("다가구",),
            "주거용오피스텔": None, "주거용근생": None},
    "A15": {"매매": ("매매계약",), "분양": ("분양계약", "공급계약"), "경매": ("매각허가", "매각대금", "경매")},
    "M05": {"계약서": ("매매대금", "매매가격", "분양대금", "분양가격", "공급대금", "공급가격")},
}
CHOICE_BLOCK = {"P02": MIXED_USE, "A04": MIXED_USE}

# 특약에 그런 조항이 없다는 값. (그 값, 조항을 가리키는 낱말). 없음은 발췌로 보일 수 없으니 발췌에는 특약 부분을 문서에 적힌
# 그대로 옮기고(「특약」이 들어가야 한다), 엔진이 그 문서 전체에서 낱말을 찾는다. 낱말 바로 뒤에 「없음」 등이 붙은 곳
# (「용도변경 특약 없음」)은 세지 않는다. 하나라도 나오면 넣지 않고 확인필요로 둔다.
SPECIAL_TERMS = "특약"
ABSENCE = {
    "A13": (False, ("용도변경", "용도를변경", "주택외", "주택이아닌", "주택아닌", "근린생활", "멸실", "철거")),
    "A14": (0, ("양도소득세", "양도세", "대납")),
}
NEGATION = re.compile(r"없(?:음|다|습|으|고)")
SENTENCE_BREAK = re.compile(r"[.,;。]|\d+[.)]")

# 증빙이 정황만 보여 주는 문항. 대조를 통과해도 넣지 않고 제안으로 확인필요에 올린다. 사용자가 맞다고 하면 answer 로 넣는다.
SUGGEST_ONLY = {
    "A07": "제안: 등기는 등기사항증명서 갑구로 확인하는 사실이다. 법무사 영수증·등기 비용은 소유권이전등기를 신청했다는 정황이라 "
           "넣지 않았다. 사용자가 본인 이름으로 등기를 마쳤다고 확인하면 넣는다",
}

# 소재지 발췌·값에 번지, 도로명 건물번호, 동·호수가 있으면 받지 않는다(읍면동까지만 옮긴다).
# 「을지로3가」, 「종로1·2·3·4가동」 같은 동 이름은 번호 뒤에 가·점이 붙어 건물번호로 보지 않는다
ADDRESS_NUMBER = re.compile(r"\d+\s*-\s*\d+|\d+\s*번지|\d+\s*[호층]|(?:로|길)\s*\d+(?![\d가·.,])|\d{3,}\s*동")
ADDRESS_MASK = "(번지·호수가 있어 옮기지 않았다)"


def choice_problem(qid, value, quote):
    table = CHOICE_WORDS.get(qid)
    if not table or not isinstance(value, str) or value not in table:
        return None
    words = table[value]
    if words is None:
        return "「%s」는 문서만으로 정하지 않는 값이다. 사용자에게 확인한다" % value
    s = _squash(quote)
    if not any(w in s for w in words):
        return "발췌에 「%s」에 맞는 낱말(%s)이 없다" % (value, ", ".join(words))
    others = [w for c, ws in table.items() if c != value and ws for w in ws if w in s]
    others += [w for w in CHOICE_BLOCK.get(qid, ()) if w in s]
    if others:
        return "발췌에 다른 값을 가리키는 낱말(%s)도 있다" % ", ".join(sorted(set(others)))
    return None


def _negated(text, end):
    tail = SENTENCE_BREAK.split(text[end:end + 8], 1)[0]
    return NEGATION.search(tail) is not None


def is_absence(qid, value):
    """특약에 조항이 없다는 값인지(A13 의 false, A14 의 0). false 와 0 은 자료형까지 같아야 한다."""
    rule = ABSENCE.get(qid)
    return rule is not None and type(value) is type(rule[0]) and value == rule[0]


def absence_problem(qid, value, quote, pages):
    """특약에 조항이 없다는 값이면 그 근거를 본다. 문제가 있으면 그 문장, 없으면 None. 없음 값이 아니면 None."""
    if not is_absence(qid, value):
        return None
    if SPECIAL_TERMS not in _squash(quote):
        return "특약에 그런 조항이 없다는 값은 특약 부분을 발췌로 옮겨야 대조한다(발췌에 「특약」이 없다)"
    text = _squash("\n".join(pages or []))
    hits = sorted({w for w in ABSENCE[qid][1] for m in re.finditer(re.escape(w), text) if not _negated(text, m.end())})
    if hits:
        return "문서에 「%s」가 나온다. 그런 조항이 아닌지 특약을 확인한다" % "」, 「".join(hits)
    return None


def _address_values(value):
    return [v for k, v in value.items() if isinstance(v, str)] if isinstance(value, dict) else [value]


def address_problem(q, value, quote):
    """소재지 값의 시도·시군구·읍면동이 발췌에 있는지. 시도는 약칭(서울, 경기 등)도 받는다."""
    if q["답형식"] != "주소" or not isinstance(value, dict):
        return None
    s = _squash(quote)
    for k in ("시도", "시군구", "읍면동"):
        v = value.get(k)
        if not isinstance(v, str) or not v:
            continue
        names = {_squash(v)}
        if k == "시도":
            full = SIDO_SHORT.get(v, v)
            names |= {_squash(full)} | {_squash(short) for short, f in SIDO_SHORT.items() if f == full}
        if not any(n in s for n in names):
            return "소재지의 %s 「%s」가 발췌에 없다" % (k, v)
    return None


def redact(text):
    return RRN.sub("******-*******", str(text or ""))


# ---- 추출 한 건 검증 --------------------------------------------------------

def _bank():
    return {q["id"]: q for q in Q.load()["문항"]}


def _page_text(texts, doc, page):
    pages = texts.get(doc)
    if pages is None:
        return None
    if page is None:
        return "\n".join(pages)
    try:
        return pages[int(page) - 1]
    except (ValueError, IndexError, TypeError):
        return "\n".join(pages)


def check_item(item, docs, texts, bank=None):
    """(판정, 사유). 판정은 반영가능 | 확인필요 | 거절. 사실관계와의 충돌은 apply 가 가른다.

    반영가능의 사유는 보통 None 이고, 없다는 값(ABSENCE)을 넣을 때만 그 근거를 적는다.
    """
    bank = bank or _bank()
    if not isinstance(item, dict):
        return "거절", "추출 항목이 JSON 객체가 아니다"
    q = bank.get(item.get("문항"))
    if q is None:
        return "거절", "%s 라는 문항이 없다" % item.get("문항")
    if item.get("값") is None:
        return "거절", "값이 비었다"
    src = item.get("출처") or {}
    quote = src.get("발췌")
    if not quote or not str(quote).strip():
        return "거절", "출처의 발췌가 비었다. 문서에서 값이 나온 문장을 그대로 적어야 한다"
    doc = src.get("문서")
    meta = docs.get(doc)
    if meta is None:
        return "거절", "문서 %s 가 증빙 목록에 없다" % doc
    if RRN.search(json.dumps(item.get("값"), ensure_ascii=False)):
        return "거절", "값에 주민등록번호로 보이는 것이 있다"
    try:
        F.check_personal({"값": item["값"]})
    except F.FactsError as e:
        return "거절", str(e)
    if q["답형식"] == "주소" and any(ADDRESS_NUMBER.search(str(v)) for v in [quote] + _address_values(item["값"])):
        return "거절", "소재지에 번지·건물번호·호수가 있다. 시도, 시군구, 읍면동까지만 옮긴다"
    if meta["글자층"]:
        page = _page_text(texts, doc, src.get("쪽"))
        if _squash(quote) not in _squash(page or ""):
            full = "\n".join(texts.get(doc) or [])
            if _squash(quote) not in _squash(full):
                return "거절", "발췌가 문서 %s 의 원문에 없다. 문서에 적힌 문장을 그대로 옮겨야 한다" % doc
            # 다른 쪽에 있으면 쪽 번호만 틀린 것이다. 값 대조는 계속한다
        prob = (value_problem(item["값"], quote) or choice_problem(q["id"], item["값"], quote)
                or address_problem(q, item["값"], quote) or absence_problem(q["id"], item["값"], quote, texts.get(doc)))
        if prob:
            return "확인필요", prob
        if item.get("확신") != "확실":
            return "확인필요", "읽은 쪽이 확신이 불확실이라고 적었다"
        if q["id"] in SUGGEST_ONLY:
            return "확인필요", SUGGEST_ONLY[q["id"]]
        if is_absence(q["id"], item["값"]):   # 위 absence_problem 을 통과했다
            return "반영가능", "특약에 그런 조항이 없다(문서에서 「%s」 등을 찾지 못했다)" % ABSENCE[q["id"]][1][0]
        return "반영가능", None
    if q["id"] in SUGGEST_ONLY:
        return "확인필요", SUGGEST_ONLY[q["id"]]
    return "확인필요", "글자층이 없는 문서라 글자 대조를 하지 못했다"


# ---- 사실관계에 넣기 --------------------------------------------------------

def _unit(f, q, item):
    """(자산, 주택). 자산 id 를 안 적었고 자산이 하나뿐이면 그 자산이다."""
    kind = Q.unit_kind(q)
    asset = house = None
    if kind in ("자산", "신규"):
        aid = item.get("자산")
        assets = f.get("자산") or []
        if aid is None and len(assets) == 1:
            aid = assets[0].get("id")
        asset = next((a for a in assets if a.get("id") == aid), None)
        if asset is None:
            raise EvidenceError("%s 는 자산마다 묻는 문항인데 자산 %s 가 사실관계에 없다" % (q["id"], aid))
    if kind in ("주택", "신규"):
        hid = item.get("주택")
        hs = F.get(f, "세대.주택목록") or []
        if hid is None and len(hs) == 1:
            hid = hs[0].get("id")
        house = next((h for h in hs if h.get("id") == hid), None)
        if house is None:
            raise EvidenceError("%s 는 주택마다 묻는 문항인데 주택 %s 가 없다" % (q["id"], hid))
    return asset, house


def _existing(f, q, asset, house):
    keys = q["키"]
    if len(keys) == 1:
        return Q.read(f, keys[0], asset, house)
    names = [k.rsplit(".", 1)[-1] for k in keys]
    vals = {n: Q.read(f, k, asset, house) for k, n in zip(keys, names)}
    return {n: v for n, v in vals.items() if v is not None} or None


def _same(old, new):
    if isinstance(new, dict) and isinstance(old, dict):
        return all(old.get(k) == v for k, v in new.items())
    return old == new


def _empty(v):
    return v is None or v == [] or v == {}


def _redact_value(v):
    if isinstance(v, str):
        return redact(v)
    if isinstance(v, dict):
        return {k: _redact_value(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_redact_value(x) for x in v]
    return v


def _brief(item, bank):
    src = item.get("출처") or {}
    row = {"문항": item.get("문항"), "자산": item.get("자산"), "주택": item.get("주택"), "값": _redact_value(item.get("값")),
           "문서": src.get("문서"), "쪽": src.get("쪽"), "발췌": redact(src.get("발췌")), "비고": redact(item.get("비고"))}
    q = bank.get(item.get("문항"))
    if q is not None and q["답형식"] == "주소":   # 번지가 든 소재지는 보고에도 옮기지 않는다
        if ADDRESS_NUMBER.search(str(src.get("발췌") or "")):
            row["발췌"] = ADDRESS_MASK
        if any(ADDRESS_NUMBER.search(str(v)) for v in _address_values(item.get("값"))):
            row["값"] = ADDRESS_MASK
    return row


EXPENSE_QUESTIONS = {문항 for _, 문항 in F.EXPENSE_GROUPS}   # M08~M11. 서류마다 따로 내고 이어 붙인다
SAME_PAYMENT_MSG = "같은 지급일·금액의 지출이 이미 들어갔다. 같은 지출을 서류 두 장으로 낸 것인지 확인하라"


def _payment(r):
    return (r.get("지급일"), r.get("금액")) if isinstance(r, dict) else None


def _join_rows(have, rows):
    """(새로 붙일 줄, 충돌 사유). 이미 있는 줄과 똑같은 줄은 건너뛴다."""
    new = []
    for r in rows:
        if r in have or r in new:
            continue
        if _payment(r) is not None and any(_payment(h) == _payment(r) for h in have + new):
            return [], SAME_PAYMENT_MSG
        new.append(r)
    return new, None


def apply(facts, items, inv, texts=None):
    """추출 목록을 검증해 사실관계에 넣는다. (새 사실관계, 보고) 를 돌려준다. 원본 facts 는 바꾸지 않는다."""
    if not isinstance(items, list):
        raise EvidenceError("증빙추출은 JSON 목록이어야 한다")
    docs = {d["id"]: d for d in inv["문서"]}
    texts = texts if texts is not None else load_texts(inv)
    bank = _bank()
    f = copy.deepcopy(facts)
    rep = {"반영": [], "일치": [], "충돌": [], "확인필요": [], "거절": []}
    seen = {}
    added = {}      # 이번 실행에서 넣은 경비 목록. 다음 서류의 줄을 여기에 이어 붙인다
    for item in items:
        verdict, why = check_item(item, docs, texts, bank)
        row = _brief(item, bank) if isinstance(item, dict) else {"문항": None}
        if verdict == "반영가능" and why:
            row["사유"] = why
        if verdict == "거절":
            rep["거절"].append(dict(row, 사유=why))
            continue
        if verdict == "확인필요":
            rep["확인필요"].append(dict(row, 사유=why))
            continue
        q = bank[item["문항"]]
        try:
            asset, house = _unit(f, q, item)
        except EvidenceError as e:
            rep["거절"].append(dict(row, 사유=str(e)))
            continue
        marker = (q["id"], asset["id"] if asset else None, house["id"] if house else None)
        unit = {"자산": asset["id"] if asset else None, "주택": house["id"] if house else None}
        if marker in added and isinstance(item["값"], list):
            new, why = _join_rows(added[marker], item["값"])
            if why:
                rep["충돌"].append(dict(row, 사유=why))
            elif not new:
                rep["일치"].append(dict(row, 사유="이번에 넣은 줄과 같다"))
            else:
                try:
                    f = Q.answer(f, q["id"], added[marker] + new, **unit)
                except (ValueError, F.FactsError) as e:
                    rep["거절"].append(dict(row, 사유="답 형식이 맞지 않는다: %s" % e))
                    continue
                added[marker] = added[marker] + new
                rep["반영"].append(row)
            continue
        old = _existing(f, q, asset, house)
        if marker in seen and not _same(seen[marker], item["값"]):
            rep["충돌"].append(dict(row, 사유="같은 문항에 다른 값을 두 번 냈다. 앞의 값: %s" % json.dumps(seen[marker], ensure_ascii=False)))
            continue
        if not _empty(old):
            if _same(old, item["값"]):
                rep["일치"].append(dict(row, 사유="사실관계에 같은 값이 이미 있다"))
            else:
                rep["충돌"].append(dict(row, 사유="사실관계에 이미 다른 값이 있다: %s" % json.dumps(old, ensure_ascii=False)))
            continue
        try:
            f = Q.answer(f, q["id"], item["값"], **unit)
        except (ValueError, F.FactsError) as e:
            rep["거절"].append(dict(row, 사유="답 형식이 맞지 않는다: %s" % e))
            continue
        seen[marker] = item["값"]
        if q["id"] in EXPENSE_QUESTIONS and isinstance(item["값"], list):
            added[marker] = list(item["값"])
        rep["반영"].append(row)
    rest = Q.next_questions(f, limit=None)
    rep["남은문항"] = [{"id": p["id"], "섹션": p["섹션"], "질문": p["질문"], "자산": p["자산"], "주택": p["주택"],
                     "증빙서류": p["증빙서류"]} for p in rest["다음"]]
    # 남은 문항 가운데 흔한 값을 가정해 확인표에 함께 올릴 것(사용자가 맞다고 해야 넣는다)과, 묻지 않는 선택 문항
    rep["가정"] = [{"id": p["id"], "자산": p["자산"], "주택": p["주택"], "질문": p["질문"], "값": p["가정"]["값"],
                  "문구": p["가정"]["문구"]} for p in rest["다음"] if p.get("가정")]
    rep["생략"] = rest["생략"]
    return f, rep


# ---- 확인표 -----------------------------------------------------------------

def _val(v):
    s = json.dumps(v, ensure_ascii=False)
    return s if len(s) <= 80 else s[:77] + "..."


def confirm_markdown(rep, inv):
    names = {d["id"]: d["파일"] for d in inv["문서"]}
    L = ["# 증빙 확인표", ""]
    L.append("증빙에서 읽어 사실관계에 넣은 값과, 사용자가 확인해야 하는 값입니다. 문서에 적힌 문장(발췌)을 옆에 붙였습니다.")
    L.append("")

    def table(title, rows, cols):
        L.append("## %s (%d)" % (title, len(rows)))
        L.append("")
        if not rows:
            L.extend(["없음", ""])
            return
        L.append("| " + " | ".join(c for c, _ in cols) + " |")
        L.append("|" + "---|" * len(cols))
        for r in rows:
            L.append("| " + " | ".join(str(fn(r)).replace("|", "/").replace("\n", " ") for _, fn in cols) + " |")
        L.append("")

    src = lambda r: "%s 쪽%s" % (names.get(r.get("문서"), r.get("문서")), r.get("쪽") or "-")
    base = [("문항", lambda r: r["문항"] + ("(%s)" % r["자산"] if r.get("자산") else "")), ("값", lambda r: _val(r["값"])),
            ("출처", src), ("발췌", lambda r: r["발췌"])]
    unit = lambda r: r["id"] + ("(%s)" % r["자산"] if r.get("자산") else "") + ("(%s)" % r["주택"] if r.get("주택") else "")
    table("사실관계에 넣은 값", rep["반영"], base + [("메모", lambda r: r.get("사유") or "")])
    table("확인이 필요한 값(넣지 않았습니다)", rep["확인필요"], base + [("사유", lambda r: r["사유"])])
    table("가정한 값(사용자가 맞다고 하면 넣습니다)", rep.get("가정") or [],
          [("문항", unit), ("값", lambda r: _val(r["값"])), ("가정", lambda r: r["문구"])])
    table("사실관계의 값과 다른 값(덮어쓰지 않았습니다)", rep["충돌"], base + [("사유", lambda r: r["사유"])])
    table("이미 같은 값이 있어 교차 확인된 값", rep["일치"], base[:3])
    table("받지 않은 값", rep["거절"], [("문항", lambda r: r.get("문항")), ("사유", lambda r: r["사유"]), ("출처", src)])
    table("묻지 않는 문항(알면 넣습니다)", rep.get("생략") or [], [("문항", unit), ("안내", lambda r: r.get("안내") or "")])
    L.append("## 아직 묻지 못한 문항 (%d)" % len(rep["남은문항"]))
    L.append("")
    for p in rep["남은문항"][:40]:
        docs = ", ".join(p["증빙서류"] or []) or "서류 없이 답하는 문항"
        L.append("- %s%s %s (필요한 서류: %s)" % (p["id"], "(%s)" % p["자산"] if p.get("자산") else "", p["질문"][:60], docs))
    if len(rep["남은문항"]) > 40:
        L.append("- 그 밖에 %d개" % (len(rep["남은문항"]) - 40))
    L.append("")
    L.append("계산 결과는 검토용이며 증빙의 진위와 문서끼리의 일치는 이 표가 보지 않습니다.")
    return "\n".join(L) + "\n"
