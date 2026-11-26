"""PDF 글자에서 숫자를 읽는다(R3, 2026-10-05).

받은자료 PDF(세무신고 · 의사록 · 약정서 · 잔액증명)의 글자에서 정해진 이름표 바로 뒤 금액을 찾는다. 결정적이다.
금액마다 몇 쪽에서 읽었는지 단다. 이름표를 못 찾으면 값을 지어 넣지 않고 None 으로 둔다.
글자 층이 없는 스캔본은 OCR(kordoc) 저장본 글을 읽는다(2026-10-18, audit.ocr). 결과마다 source 가 'text' · 'ocr' · None 이다.
OCR 값은 확인 전이라 분석(data.py)이 대사 · 이슈 금액에 쓰지 않고 「OCR 값 확인 필요」 로 돌린다.
OCR 저장본도 없으면 빈 결과가 되고, 그때는 AI 판독(문서목록 facts, 문장만)으로 안건 존재만 세운다.

  vat(path)          부가세 신고서: 기간, 과세표준(과세 · 영세율 · 합계), 매출세액
  withholding(path)  원천징수이행상황신고서: 귀속월별 인원 · 총지급액, 합계
  corptax(path)      법인세 세무조정계산서: 사업연도, 각사업연도소득, 산출세액, 총부담세액, 유보 잔액
  loan(path)         차입 약정서: 금리(연 %), 약정금액, 합계, 금융기관. 보증료 영수증 · 청구서는 kind '보증료'(약정 금액 없음)
  bank(path)         잔액증명: 기준일, 금융기관, 예금 잔액, 대출금 잔액
  minutes(path)      의사록: 회의, 일자, 안건마다 제목 · 쪽 · 금액들 · 상대방 · 결의
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

AMOUNT_RE = re.compile(r"^\(?-?[\d,]+\)?$")
MONEY_IN_TEXT = re.compile(r"(\d{1,3}(?:,\d{3})+|\d{4,})\s*원")
SPAN_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})\s*~\s*(\d{4})-(\d{2})-(\d{2})")
KDATE_RE = re.compile(r"(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일")


def read_lines(path: Path) -> tuple[list[tuple[int, str]], str | None]:
    """(줄 목록, 출처). 글자 층 → OCR(kordoc) 저장본 순서(audit.ocr.pdf_pages). 출처는 'text' · 'ocr' · None(글자 없음)."""
    from .. import ocr

    pages, src = ocr.pdf_pages(Path(path))
    out = []
    for no, text in pages:
        for ln in text.splitlines():
            s = ln.strip()
            if s:
                out.append((no, s))
    return out, src


def lines(path: Path) -> list[tuple[int, str]]:
    return read_lines(path)[0]


def amount(s: str) -> int | None:
    s = s.strip().replace(" ", "")
    if not AMOUNT_RE.match(s) or not re.search(r"\d", s):
        return None
    neg = s.startswith("(") and s.endswith(")")
    v = int(s.strip("()").replace(",", ""))
    return -v if neg else v


def _key(s: str) -> str:
    return re.sub(r"[\s()·,]", "", s)


def after(ls: list[tuple[int, str]], labels: list[str], start: int = 0, look: int = 6, nth: int = 0):
    """이름표 줄 다음 look 줄 안의 금액. (값, 쪽, 줄 번호) 또는 None. nth 는 이름표 뒤 몇 번째 금액인지."""
    keys = [_key(x) for x in labels]
    for i in range(start, len(ls)):
        if _key(ls[i][1]) in keys:
            found = 0
            for j in range(i + 1, min(len(ls), i + 1 + look)):
                v = amount(ls[j][1])
                if v is not None:
                    if found == nth:
                        return v, ls[j][0], i
                    found += 1
            return None
    return None


def _span(ls) -> tuple[date, date] | None:
    for _, s in ls:
        m = SPAN_RE.search(s)
        if m:
            g = [int(x) for x in m.groups()]
            return date(g[0], g[1], g[2]), date(g[3], g[4], g[5])
    return None


def _ref(path: Path, page: int) -> str:
    return f"{Path(path).name} {page}쪽"


# ---------------------------------------------------------------- 세무신고
def vat(path: Path) -> dict:
    ls, src = read_lines(path)
    sp = _span(ls)
    out = {"kind": "부가세", "path": str(path), "start": sp[0].isoformat() if sp else None, "end": sp[1].isoformat() if sp else None,
           "values": {}, "refs": {}}
    m = next((re.search(r"(\d{4})\s*년\s*제\s*(\d)\s*기", s) for _, s in ls if re.search(r"(\d{4})\s*년\s*제\s*(\d)\s*기", s)), None)
    out["period"] = f"{m.group(1)}-{m.group(2)}" if m else (f"{sp[0].year}-{1 if sp[0].month <= 6 else 2}" if sp else None)
    for item, labels in (("과세표준_합계", ["합계(과세표준)", "과세표준 합계", "과세표준및매출세액 합계", "합계"]),
                         ("과세표준_과세", ["과세 세금계산서 발급분"]),
                         ("과세_기타", ["과세 기타"]),
                         ("과세표준_영세율", ["영세율 세금계산서 발급분"]),
                         ("영세율_기타", ["영세율 기타"])):
        r = after(ls, labels)
        if r:
            out["values"][item] = r[0]
            out["refs"][item] = _ref(path, r[1])
    r = after(ls, ["합계(과세표준)", "과세표준 합계", "합계"], nth=1)
    if r:
        out["values"]["매출세액"] = r[0]
        out["refs"]["매출세액"] = _ref(path, r[1])
    v = out["values"]
    if "과세_기타" in v and "과세표준_과세" in v:
        v["과세표준_과세"] += v.pop("과세_기타")
        out["refs"].pop("과세_기타", None)
    if "영세율_기타" in v and "과세표준_영세율" in v:
        v["과세표준_영세율"] += v.pop("영세율_기타")
        out["refs"].pop("영세율_기타", None)
    out["source"] = src
    return out


def withholding(path: Path) -> dict:
    ls, src = read_lines(path)
    m = next((re.search(r"(\d{4})\s*년\s*귀속", s) for _, s in ls if re.search(r"(\d{4})\s*년\s*귀속", s)), None)
    out = {"kind": "원천세", "path": str(path), "year": int(m.group(1)) if m else None, "months": {}, "values": {}, "refs": {}}
    ym = re.compile(r"^(\d{4})-(\d{2})$")
    i = 0
    while i < len(ls):
        a = ym.match(ls[i][1])
        if a and i + 3 < len(ls) and ym.match(ls[i + 1][1]):
            heads = amount(ls[i + 2][1])
            pay = amount(ls[i + 3][1])
            if heads is not None and pay is not None:
                out["months"][ls[i][1]] = {"heads": heads, "pay": pay, "ref": _ref(path, ls[i][0])}
                i += 4
                continue
        i += 1
    r = after(ls, ["합계"])
    if r:
        out["values"]["근로소득_지급액"] = r[0]
        out["refs"]["근로소득_지급액"] = _ref(path, r[1])
    elif out["months"]:
        out["values"]["근로소득_지급액"] = sum(x["pay"] for x in out["months"].values())
        out["refs"]["근로소득_지급액"] = "귀속월 행 합"
    if out["months"]:
        hs = [x["heads"] for x in out["months"].values()]
        out["values"]["근로소득_인원"] = round(sum(hs) / len(hs), 4)
        out["refs"]["근로소득_인원"] = "귀속월 인원 평균"
        if out["year"] is None:
            out["year"] = int(next(iter(out["months"]))[:4])
    out["source"] = src
    return out


def corptax(path: Path) -> dict:
    ls, src = read_lines(path)
    sp = _span(ls)
    out = {"kind": "법인세", "path": str(path), "start": sp[0].isoformat() if sp else None, "end": sp[1].isoformat() if sp else None,
           "year": sp[1].year if sp else None, "values": {}, "refs": {}}
    for item, labels in (("결산서상당기순손익", ["결산서상 당기순손익", "결산서상 당기순이익"]),
                         ("각사업연도소득", ["각사업연도소득금액", "각 사업연도 소득금액"]),
                         ("과세표준", ["과세표준"]),
                         ("산출세액", ["산출세액 합계", "산출세액"]),
                         ("총부담세액", ["총부담세액"]),
                         ("유보_기말잔액합계", ["유보 기말잔액 합계", "유보 기말잔액합계"])):
        r = after(ls, labels)
        if r:
            out["values"][item] = r[0]
            out["refs"][item] = _ref(path, r[1])
    out["source"] = src
    return out


# ---------------------------------------------------------------- 약정서 · 잔액증명
GUARANTEE_FEE = re.compile(r"보\s*증\s*료")
RECEIPT = re.compile(r"(영\s*수\s*증|청\s*구\s*내\s*역|청\s*구\s*서|납\s*부\s*안\s*내)")
CONTRACT_WORDS = re.compile(r"(여신\s*거래\s*약정|대출\s*약정|차입\s*약정|한도\s*약정|대출\s*거래\s*약정|금전\s*소비\s*대차)")


def _institution(path: Path, ls) -> tuple[str | None, str | None]:
    """(금융기관 이름, 근거). 파일 이름이 먼저다. 글 속에는 납부 계좌 은행 같은 다른 은행 이름도 있어서다(2026-10-18)."""
    from . import inst

    got = inst.name(Path(path).stem, file=True)
    if got:
        return got, "파일 이름"
    for _, s in ls:
        got = inst.name(s, file=True)
        if got:
            return got, "글자"
    return None, None


SECURITY_DOC = re.compile(r"(근?\s*질\s*권\s*설\s*정|근\s*저\s*당|저\s*당\s*권\s*설\s*정|신\s*용\s*보\s*증\s*서|보\s*증\s*서|담\s*보\s*제\s*공)")
SECURITY = "담보·보증"                       # 질권 · 근저당 설정 계약서와 신용보증서. 차입 약정 금액이 없는 서류다(2026-10-19)


def security_doc(ls) -> bool:
    """질권 · 근저당 설정 계약서, 보증기관 신용보증서. 여신 · 대출 약정 문구가 없으면 차입 약정서가 아니다.
    근질권설정계약서를 약정서로 세어 「약정서 금액을 읽지 못한 차입처」 가 됐고, 약정서가 없는 차입처가 신용보증서 때문에
    「약정서 없음」 으로 잡히지 않았다(2026-10-19 가상 회사 세트)."""
    text = " ".join(s for _, s in ls)
    return bool(SECURITY_DOC.search(text) and not CONTRACT_WORDS.search(text))


def guarantee_fee(ls) -> bool:
    """보증기관(기술보증기금 · 신용보증기금 등)의 보증료 영수증 · 청구서. 금액이 보증료라 차입 약정 금액으로 쓰면 안 된다(2026-10-18)."""
    text = " ".join(s for _, s in ls)
    return bool(GUARANTEE_FEE.search(text) and RECEIPT.search(text) and not CONTRACT_WORDS.search(text))


def loan(path: Path) -> dict:
    ls, src = read_lines(path)
    if guarantee_fee(ls):
        n, basis = _institution(path, ls)
        amt = None
        for i, (_, s) in enumerate(ls):
            if _key(s) in ("보증금액", "대상금액"):
                for j in range(i + 1, min(len(ls), i + 12)):
                    m = re.match(r"^(\d{1,3}(?:,\d{3})+)(?:\s|$)", ls[j][1])
                    if m and amount(m.group(1)):
                        amt = amount(m.group(1))
                        break
                if amt:
                    break
        return {"kind": "보증료", "path": str(path), "rates": [], "rate_ref": None, "facilities": [], "values": {}, "refs": {},
                "lender": n, "lender_basis": basis, "guarantee_amount": amt, "source": src}
    if security_doc(ls):
        n, basis = _institution(path, ls)
        return {"kind": SECURITY, "path": str(path), "rates": [], "rate_ref": None, "facilities": [], "values": {}, "refs": {},
                "lender": n, "lender_basis": basis, "source": src}
    rates = []
    for no, s in ls:
        for m in re.finditer(r"연\s*([\d.]+)\s*%", s):
            rates.append((float(m.group(1)) / 100, no))
    out = {"kind": "약정", "path": str(path), "rates": sorted({r for r, _ in rates}),
           "rate_ref": _ref(path, rates[0][1]) if rates else None, "facilities": [], "values": {}, "refs": {}}
    for i, (no, s) in enumerate(ls):
        if re.search(r"(대출|차입|여신|자금)", s) and not re.search(r"(조|약정서)", s) and i + 1 < len(ls):
            v = amount(ls[i + 1][1])
            if v is not None and v > 0:
                out["facilities"].append({"name": s, "amount": v, "ref": _ref(path, ls[i + 1][0])})
    r = after(ls, ["합계"])
    if r:
        out["values"]["약정합계"] = r[0]
        out["refs"]["약정합계"] = _ref(path, r[1])
    elif out["facilities"]:
        out["values"]["약정합계"] = sum(f["amount"] for f in out["facilities"])
        out["refs"]["약정합계"] = "약정 행 합"
    out["lender"], out["lender_basis"] = _institution(path, ls)
    out["source"] = src
    return out


AS_OF_WORDS = ("기준일", "현재", "기준", "指定日", "現在")
ISSUE_WORDS = ("발급", "발행", "출력", "조회일", "인쇄", "Date", "照会日時", "発行")
TIME_RE = re.compile(r"\d{4}\D{1,3}\d{1,2}\D{1,3}\d{1,2}\D{0,2}\s+\d{1,2}:\d{2}")    # 조회 · 출력 시각이 붙은 날짜


def as_of(ls) -> str | None:
    """잔액증명 기준일. '기준일 · 현재 · as of' 가 붙은 날짜가 먼저, 없으면 발급일 · 출력일이 아닌 첫 날짜.
    '2024-10-31' · '2024.10.31' · '2024년10월31일' 꼴을 읽는다(2026-10-18, 실제 회사 자료 은행 잔액증명은 한글 날짜만 있었다)."""
    from . import inst

    strong = weak = None
    for i, (_, s) in enumerate(ls):
        ds = inst.dates(s)
        if _key(s) in ("증명기준일", "기준일") and i + 1 < len(ls):
            nxt = inst.dates(ls[i + 1][1])
            if nxt:
                return nxt[0].isoformat()
        if not ds:
            continue
        if any(w in s for w in AS_OF_WORDS) or "asof" in _key(s).lower():
            strong = strong or ds[0]
        elif not any(w in s for w in ISSUE_WORDS) and not TIME_RE.search(s):
            weak = weak or ds[0]
    got = strong or weak
    return got.isoformat() if got else None


def _fc_re() -> re.Pattern:
    from . import defs

    curs = "|".join(sorted((defs.load("analytics").get("fx_translation") or {}).get("currencies") or {"USD": 1}))
    return re.compile(r"(?<![A-Za-z])(" + curs + r")\s*([\d,]+(?:\.\d+)?)(?![\d,.])")


def bank_fx(path: Path, ls) -> list[dict]:
    """잔액증명 외화예금 줄: 계좌 칸의 「(USD 216,500.00)」 과 그 줄 · 다음 두 줄 안의 원화 환산액(2026-10-20, X-fx-translation).
    [{currency, fc, krw, account, ref}]. 원화 환산액을 못 찾은 줄은 뺀다."""
    rx = _fc_re()
    out = []
    for i, (no, s) in enumerate(ls):
        m = rx.search(s)
        if not m:
            continue
        fc = float(m.group(2).replace(",", ""))
        rest = s[m.end():].strip(" )")
        krw = amount(rest) if rest else None
        for j in range(i + 1, min(len(ls), i + 3)):
            if krw is not None:
                break
            krw = amount(ls[j][1])
        if krw is None or not fc:
            continue
        out.append({"currency": m.group(1), "fc": fc, "krw": krw, "account": s[:m.start()].strip(" ("), "ref": _ref(path, no)})
    return out


def bank(path: Path) -> dict:
    ls, src = read_lines(path)
    out = {"kind": "잔액증명", "path": str(path), "as_of": as_of(ls), "values": {}, "refs": {}}
    out["fx"] = bank_fx(path, ls)
    out["institution"], out["institution_basis"] = _institution(path, ls)
    dep = loans = None
    dep_ref = loan_ref = None
    for i, (no, s) in enumerate(ls):
        k = _key(s)
        if k.endswith("예금") and k not in ("예금주",):
            for j in range(i + 1, min(len(ls), i + 4)):
                v = amount(ls[j][1])
                if v is not None:
                    dep = (dep or 0) + v
                    dep_ref = _ref(path, ls[j][0])
                    break
        if k in ("대출금합계", "대출합계", "차입금합계"):
            r = after(ls, [s], start=i)
            if r:
                loans, loan_ref = r[0], _ref(path, r[1])
    if loans is None:
        tot = 0
        for i, (no, s) in enumerate(ls):
            if _key(s) == "대출금":
                for j in range(i + 1, min(len(ls), i + 4)):
                    v = amount(ls[j][1])
                    if v is not None:
                        tot += v
                        loan_ref = _ref(path, ls[j][0])
                        break
        loans = tot if loan_ref else None
    if dep is not None:
        out["values"]["예금"] = dep
        out["refs"]["예금"] = dep_ref
    if loans is not None:
        out["values"]["대출금"] = loans
        out["refs"]["대출금"] = loan_ref
    out["source"] = src
    return out


# ---------------------------------------------------------------- 의사록
AGENDA_RE = re.compile(r"^제\s*(\d+)\s*호\s*의안\s*(.+)$")
# 번호 없는 안건 「의안. 기업운전자금 대출의 건」(2026-10-18 실제 회사 자료 OCR 의사록). 「의안을 부의하고」 같은 문장은 구분 기호가 없어 맞지 않는다
AGENDA_ONE_RE = re.compile(r"^의안\s*[.:．]\s*(.+의\s*건)\s*$")
PARTY_RE = re.compile(r"([가-힣A-Za-z0-9㈜()]+?)(?:으로부터|로부터|에게|와의|과의)")
BANK_RE = re.compile(r"([가-힣A-Za-z]+(?:은행|캐피탈|증권|보험|금고))")
END_RE = re.compile(r"^(의장은 이상으로|위 의사의 경과|이상으로)")


def minutes(path: Path) -> dict:
    ls, src = read_lines(path)
    meeting = None
    for _, s in ls[:5]:
        m = re.search(r"(이사회|주주총회|임시주주총회|정기주주총회)\s*의사록", s)
        if m:
            meeting = "주주총회" if "주주총회" in m.group(1) else "이사회"
            break
    day = None
    for _, s in ls:
        m = KDATE_RE.search(s)
        if m and ("일시" in s or day is None):
            day = date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
            if "일시" in s:
                break
    items = []
    cur = None
    for no, s in ls:
        m = AGENDA_RE.match(s)
        m1 = None if m else AGENDA_ONE_RE.match(s)
        if m or m1:
            cur = {"no": int(m.group(1)) if m else 1, "agenda": s, "page": no, "body": []}
            items.append(cur)
            continue
        if cur is None:
            continue
        if END_RE.match(s) or "(계속)" in s:
            if END_RE.match(s):
                cur = None
            continue
        cur["body"].append(s)
    out_items = []
    for it in items:
        body = " ".join(it["body"])
        amounts = [int(x.replace(",", "")) for x in MONEY_IN_TEXT.findall(body)]
        party = None
        m = PARTY_RE.search(body)
        if m:
            party = m.group(1)
        else:
            b = BANK_RE.search(body)
            party = b.group(1) if b else None
        if party:
            party = re.sub(r"^(의장은|회사는|당사는)\s*", "", party)
        res = "부결" if "부결" in body else ("가결" if "가결" in body or "승인" in body else None)
        out_items.append({"no": it["no"], "agenda": it["agenda"], "page": it["page"], "amounts": amounts, "body": body,
                          "counterparty": party, "resolution": res})
    return {"kind": "의사록", "path": str(path), "meeting": meeting, "date": day, "items": out_items, "source": src}


def amount_after_label(body: str, label: str) -> int | None:
    m = re.search(re.escape(label) + r"\D{0,12}?(\d{1,3}(?:,\d{3})+|\d{4,})\s*원", body)
    return int(m.group(1).replace(",", "")) if m else None
