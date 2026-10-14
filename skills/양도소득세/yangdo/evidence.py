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
  확인필요  스캔본·사진이거나 확신이 불확실이거나 값이 발췌에서 대조되지 않는다. 사용자가 확인표에서 고른다
  거절   없는 문항, 없는 문서, 글자층 원문에 없는 발췌, 형식이 틀린 값, 인적사항
"""
import copy
import json
import os
import re
import zipfile

from yangdo import facts as F
from yangdo import questions as Q

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
    """(판정, 사유). 판정은 반영가능 | 확인필요 | 거절. 사실관계와의 충돌은 apply 가 가른다."""
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
    if meta["글자층"]:
        page = _page_text(texts, doc, src.get("쪽"))
        if _squash(quote) not in _squash(page or ""):
            full = "\n".join(texts.get(doc) or [])
            if _squash(quote) not in _squash(full):
                return "거절", "발췌가 문서 %s 의 원문에 없다. 문서에 적힌 문장을 그대로 옮겨야 한다" % doc
            # 다른 쪽에 있으면 쪽 번호만 틀린 것이다. 값 대조는 계속한다
        prob = value_problem(item["값"], quote)
        if prob:
            return "확인필요", prob
        if item.get("확신") != "확실":
            return "확인필요", "읽은 쪽이 확신이 불확실이라고 적었다"
        return "반영가능", None
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


def _brief(item):
    src = item.get("출처") or {}
    return {"문항": item.get("문항"), "자산": item.get("자산"), "주택": item.get("주택"), "값": _redact_value(item.get("값")),
            "문서": src.get("문서"), "쪽": src.get("쪽"), "발췌": redact(src.get("발췌")), "비고": redact(item.get("비고"))}


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
    for item in items:
        verdict, why = check_item(item, docs, texts, bank)
        row = _brief(item) if isinstance(item, dict) else {"문항": None}
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
            f = Q.answer(f, q["id"], item["값"], 자산=asset["id"] if asset else None, 주택=house["id"] if house else None)
        except (ValueError, F.FactsError) as e:
            rep["거절"].append(dict(row, 사유="답 형식이 맞지 않는다: %s" % e))
            continue
        seen[marker] = item["값"]
        rep["반영"].append(row)
    rest = Q.next_questions(f, limit=None)
    rep["남은문항"] = [{"id": p["id"], "질문": p["질문"], "자산": p["자산"], "주택": p["주택"], "증빙서류": p["증빙서류"]}
                    for p in rest["다음"]]
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
    table("사실관계에 넣은 값", rep["반영"], base)
    table("확인이 필요한 값(넣지 않았습니다)", rep["확인필요"], base + [("사유", lambda r: r["사유"])])
    table("사실관계의 값과 다른 값(덮어쓰지 않았습니다)", rep["충돌"], base + [("사유", lambda r: r["사유"])])
    table("이미 같은 값이 있어 교차 확인된 값", rep["일치"], base[:3])
    table("받지 않은 값", rep["거절"], [("문항", lambda r: r.get("문항")), ("사유", lambda r: r["사유"]), ("출처", src)])
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
