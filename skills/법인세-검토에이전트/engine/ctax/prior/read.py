"""전기 세무조정계산서 PDF 하나를 `_색인/전기.json` 꼴(CONTRACT.md 6절)로 읽는다.

쪽 분리와 칸 읽기는 옮겨 온 파서(pdf.split_pages · pdf.read_cells)가 하고, 이 모듈은 그 칸을 계약의 묶음으로 바꾼다.

  forms        목차와 쪽 머리 표시로 정한 서식 목록. 같은 서식 코드의 쪽은 하나로 묶는다(20호(1) 은 목차 항목 셋).
  company      1호(①③⑧⑨⑩⑮) · 51호 (26)(27) 동그라미 · 표지(기수)
  cells        파서가 읽은 서식의 한 줄 란(row 0) 전부. 1호는 글, 3호 세율(11 · 14 · 35 · 60)은 인쇄된 % 정수.
               54호 1절 주식수 · 액면가 · 자본금과 3절 합계 줄은 cells["54"](form54.py), 29호 2절 합계 줄은 cells["29"],
               51호 규모 기준 칸(억원)은 cells["51"](form29.py)
  rows         줄 꼴 서식의 줄 {서식: [{란: 값}]}. 29호 3절 차량별 한도초과 이월 줄(rows["29"], form29.py), 54호 3절 주주 줄(rows["54"], form54.py), 21호 5절 기부금 이월액 명세 ·
               6절 해당 사업연도 기부금 지출액 명세 줄(rows["21"], form21.py), 22호 기부금명세서 줄(rows["22"]) ·
               세금공과금명세서 비고(손금불산입 등)가 있는 줄(rows["세금공과금명세서"], form22.py)
  adjustments  15호 줄. 조정내용(note)은 15호 부표1(가산) · 부표2(차감)에서 금액으로 짝지어 붙인다
  reserves     50호(을) 줄
  losses       50호(갑) Ⅱ 결손금 계산서 줄
  credits      8호(갑) 감면 · 공제 줄(8호(갑)이 없으면 3호 17 · 19 란)
  credit_years 8호 부표3 2절(당기공제세액 및 이월액 계산)의 연도별 줄. 소계 · 합계 줄은 뺀다
  employment   조특 10호의8 · 10호의9(고용 세액공제 공제세액계산서)의 차수별 세액공제액과 상시근로자 수(employ.py).
               10호의8 의 차수별 계는 cells["조특10의8"] 의 `1차_계` · `2차_계` · `3차_계` · `합계` 에도 둔다
  rnd          조특 3호(1)(일반연구 및 인력개발비 명세서)의 해당 과세연도 발생액 · 직전 4년 발생액 · 공제세액(rnd.py).
               신고서에 그 서식이 없으면 키가 없다
  listed       세무조정계산서총괄표에 O 가 찍힌 서식 [{code, no(서식번호 글), name, applies(해당사항 O), attached(첨부 O)}].
               첨부 O 인데 이 PDF 에 그 서식 쪽이 없으면 problems(ref 「총괄표.<code>」)에 적는다(10-21). 총괄표가 없으면 []
  problems     파서 확인사항 중 「없어도 되는 서식」 과 값이 같은 중복을 뺀 것, 그리고 이 모듈이 더하는 확인사항

PDF 없이 시험할 수 있게 묶음 함수(adjustments_from 등)는 Cell 목록만 받는다.
"""
from __future__ import annotations

import re
from collections import OrderedDict

from ctax.prior.defs import form_def
from ctax.prior.employ import read_employment
from ctax.prior import grid
from ctax.prior.form21 import read_21
from ctax.prior.form22 import read_22, read_taxes
from ctax.prior.form29 import carry_rows, read_29, scale_51
from ctax.prior.form54 import read_54
from ctax.prior.pdf import Cell, Problem, _toc, read_cells, split_pages
from ctax.prior.rnd import read_rnd

RATE_CODES = {"11", "14", "35", "60"}
AMT = re.compile(r"^[△\-]?\d{1,3}(?:[,:]\d{3})+$")
BODY_TOP = 135                          # 쪽 머리(서식 표시 · 제목) 아래부터 금액을 센다
# 금액이 없어도 빈 서식이 아닌 글 서식
TEXT_FORMS = {"1", "63의13", "77", "전산조직운용명세서", "세무조정계산서총괄표", "지출증명서류수취검토서식"}
EMPLOY_FORMS = ("조특10의8", "조특10의9", "조특10의9_1")       # 쪽에 격자 자료(선 · 글자)를 붙여 읽는 서식
RND_FORM = "조특3_1"                                          # 위와 같이 격자로 읽는 서식(rnd.py)
RND_CODES = ("16B", "13M")                                    # 일반 연구 · 인력개발비 세액공제(8호(갑) 코드)
DISPOSITIONS = ("유보", "기타사외유출", "상여", "배당", "기타소득", "기타")
TOTAL_NAME = re.compile(r"(소\s*계|합\s*계|총\s*계)")

# 별지 표시 → 계약 6절 서식 코드(일반 규칙으로 안 되는 것만)
SPECIAL = {"3호의2(1)": "std_bs", "3호의2(2)": "std_bs", "3호의2(3)": "std_bs_fin", "3호의2(4)": "std_bs_fin_sum",
           "3호의3(1)": "std_is", "3호의3(2)": "std_is_fin", "3호의3(3)": "std_cogs", "3호의3(4)": "std_re",
           "6-11호": "세금공과금명세서", "6-12호": "선급비용명세서"}
# 목차 한 항목이 서식 둘을 담는 경우(「기업업무추진비조정명세서(갑/을)」, 「과목별소득금액조정명세서」)의 서식 이름
NAMES = {"15부표1": "과목별소득금액조정명세서(1)", "15부표2": "과목별소득금액조정명세서(2)",
         "23갑": "기업업무추진비조정명세서(갑)", "23을": "기업업무추진비조정명세서(을)",
         "std_bs": "표준재무상태표", "std_is": "표준손익계산서", "std_cogs": "부속명세서(표준원가명세서)",
         "std_bs_fin": "표준재무상태표(금융·보험·증권업)", "std_bs_fin_sum": "합계표준재무상태표(금융·보험·증권업)",
         "std_is_fin": "표준손익계산서(금융·보험·증권업)"}
HINT = re.compile(r"^(조특|지방|농특|국조)?(\d+(?:-\d+)?)호(?:의(\d+))?(?:\((갑|을|병|\d+)\))?(부표\d*)?(?:\((갑|을|병|\d+)\))?$")


# ---------------------------------------------------------------- 서식 목록

def hint_code(hint: str):
    """쪽 머리 표시(pdf.norm_hint 꼴) → (서식 코드, 아는 서식인가). 목차로만 정한 쪽은 목차 이름 그대로, known False."""
    if not hint or hint == "목차":
        return None, False
    if hint.startswith("목차:"):
        return hint[3:], False
    if hint in SPECIAL:
        return SPECIAL[hint], True
    m = HINT.match(hint)
    if not m:
        return hint, False
    law, no, sub, k1, bu, k2 = m.groups()
    code = (law or "") + no + (f"의{sub}" if sub else "")
    for k, part in ((k1, None), (None, bu), (k2, None)):
        if part:
            code += part
        elif k:
            code += k if k in ("갑", "을", "병") else f"_{k}"
    return code, True


def forms_from(pages: list[dict], cells: list[Cell] | None = None) -> list[dict]:
    """쪽 목록(split_pages)에서 서식 목록. 파서가 정한 form_code(15호 부표2 머리 오표기를 제목으로 바로잡은 것)가 있으면
    그것을 쓴다. 이름은 그 서식 첫 쪽이 든 목차 항목 이름이다."""
    toc = sorted(e for p in pages if p.get("form_hint") == "목차" for e in _toc(p.get("text", "")))

    def section(no):
        hit = [e for e in toc if e[0] <= no]
        return hit[-1][1] if hit else ""

    valued = {c.form_code for c in (cells or []) if c.value is not None or (c.text and c.form_code == "1")}
    out: "OrderedDict[str, dict]" = OrderedDict()
    for p in pages:
        code, known = hint_code(p.get("form_hint", ""))
        if p.get("form_code"):
            code, known = p["form_code"], True
        if not code:
            continue
        n = sum(1 for w in p.get("words", []) if w[1] > BODY_TOP and AMT.match(str(w[4]).replace(" ", "")))
        f = out.get(code)
        if f is None:
            f = out[code] = {"code": code, "name": section(p["page_no"]) or code, "page": p["page_no"], "pages": 0,
                             "blank": True, "known": known, "_amounts": 0}
        f["pages"] += 1
        f["_amounts"] += n
    for f in out.values():
        f["blank"] = f.pop("_amounts") == 0 and f["code"] not in valued and f["code"] not in TEXT_FORMS
        f["name"] = NAMES.get(f["code"], f["name"])
    return list(out.values())


# ---------------------------------------------------------------- 칸 묶음

def _rows(cells: list[Cell], form_code: str) -> "OrderedDict[int, dict]":
    rows: "OrderedDict[int, dict]" = OrderedDict()
    for c in sorted((c for c in cells if c.form_code == form_code and c.row_no >= 1), key=lambda c: c.row_no):
        rows.setdefault(c.row_no, {})[c.item_code] = c.value if c.value is not None else c.text
    return rows


def _int(v) -> int:
    if v is None or v == "":
        return 0
    return int(round(float(v)))


def disposition(text) -> str:
    t = re.sub(r"\s+", "", str(text or ""))
    for d in DISPOSITIONS:
        if t.startswith(d):
            return d
    return t


def _sub_notes(cells: list[Cell], form_code: str) -> list[dict]:
    """15호 부표 줄 [{subject, amount, note}]. ⑤조정내용이 다음 줄로 넘친 줄(과목 · 금액 없이 조정내용만 있는 줄)은 앞 줄에 붙인다."""
    out: list[dict] = []
    for row in _rows(cells, form_code).values():
        subject, amount, note = row.get("1"), row.get("2"), str(row.get("5") or "")
        if subject is None and amount is None:
            if out and note:
                out[-1]["note"] += note
            continue
        out.append({"subject": str(subject or ""), "amount": _int(amount), "note": note, "used": False})
    return out


def adjustments_from(cells: list[Cell]) -> list[dict]:
    """15호 줄 → [{side, subject, amount, disposition, code, note}]. 가산(익금산입 · 손금불산입) 줄 다음 차감 줄, 서식 순서대로."""
    rows = _rows(cells, "15")
    out = []
    for side, (s, a, d, k), sub in (("가산", ("1", "2", "3", "3_2"), "15부표1"), ("차감", ("4", "5", "6", "6_2"), "15부표2")):
        notes = _sub_notes(cells, sub)
        for row in rows.values():
            if row.get(s) is None and row.get(a) is None:
                continue
            subject, amount = str(row.get(s) or ""), _int(row.get(a))
            hit = next((n for n in notes if not n["used"] and n["amount"] == amount and n["subject"] == subject), None) \
                or next((n for n in notes if not n["used"] and n["amount"] == amount), None)
            if hit:
                hit["used"] = True
            out.append({"side": side, "subject": subject, "amount": amount, "disposition": disposition(row.get(d)),
                        "code": str(row.get(k) or ""), "note": hit["note"] if hit else ""})
    return out


def reserves_from(cells: list[Cell]) -> list[dict]:
    """50호(을) 줄 → [{subject, opening, decrease, increase, closing}]. 금액이 없고 과목만 있는 줄은 앞 줄 과목이 넘친 것으로 본다."""
    out: list[dict] = []
    for row in _rows(cells, "50을").values():
        amounts = [row.get(k) for k in ("2", "3", "4", "5")]
        subject = str(row.get("1") or "")
        if all(v is None for v in amounts):
            if out and subject:
                out[-1]["subject"] += subject
            continue
        out.append({"subject": subject, "opening": _int(amounts[0]), "decrease": _int(amounts[1]),
                    "increase": _int(amounts[2]), "closing": _int(amounts[3])})
    return out


def losses_from(cells: list[Cell]) -> list[dict]:
    """50호(갑) Ⅱ 결손금 계산서 줄 → [{year, incurred, used, remaining}]. used 는 ⑮감소 계, remaining 은 (18)잔액 계(없으면
    ⑪차감계 − ⑮)."""
    out = []
    for row in _rows(cells, "50갑").values():
        if not any(k.startswith("결손_") for k in row):
            continue
        year = re.match(r"\d{4}", str(row.get("결손_6") or ""))
        incurred = _int(row.get("결손_7") if row.get("결손_7") is not None else row.get("결손_8"))
        used = _int(row.get("결손_15"))
        remaining = _int(row["결손_18"]) if row.get("결손_18") is not None else _int(row.get("결손_11", incurred)) - used
        out.append({"year": year.group(0) if year else str(row.get("결손_6") or ""), "incurred": incurred,
                    "used": used, "remaining": remaining})
    return out


def credit_name(code: str) -> str:
    form = form_def("8갑")
    it = form.find(code) if form else None
    if it is None:
        return ""
    name = re.sub(r"^\(\d+\)\s*", "", it.name)
    return re.split(r"\s*(「|법률 제|구 「|④|③|⑦)", name)[0].strip()


def credits_from(cells: list[Cell]) -> list[dict]:
    """8호(갑) 줄 → [{name, code, amount, carryforward}]. 주 열(④감면 · ⑦공제세액)만 보고 소계 · 합계 줄은 뺀다. 이월액은
    공제 줄의 ⑤전기이월액 + ⑥당기발생액 − ⑦공제세액(소멸분은 빼지 않았다). 8호(갑)이 없으면 3호 17 · 19 란."""
    v = {c.item_code: c.value for c in cells if c.form_code == "8갑" and c.row_no == 0 and c.value is not None}
    out = []
    form = form_def("8갑")
    for code, amount in v.items():
        if "_" in code or not amount:
            continue
        it = form.find(code) if form else None
        if it is not None and (it.total or TOTAL_NAME.search(it.name.split("「")[0])):
            continue
        carry = 0
        if f"{code}_5" in v or f"{code}_6" in v:
            carry = max(0, _int(v.get(f"{code}_5")) + _int(v.get(f"{code}_6")) - _int(amount))
        out.append({"name": credit_name(code) or code, "code": code, "amount": _int(amount), "carryforward": carry})
    _carry_8bu3(cells, out)
    if out or v:
        return out
    three = {c.item_code: c.value for c in cells if c.form_code == "3" and c.row_no == 0}
    for code, name in (("17", "최저한세 적용대상 공제감면세액"), ("19", "최저한세 적용제외 공제감면세액")):
        if three.get(code):
            out.append({"name": name, "code": None, "amount": _int(three[code]), "carryforward": 0})
    return out


def _norm(s) -> str:
    return re.sub(r"[\s·ㆍ∙.,()「」]", "", str(s or ""))


def _carry_8bu3(cells: list[Cell], credits: list[dict]) -> None:
    """8호 부표3 2절 줄의 (125)이월액을 공제 코드별로 더해 credits 의 carryforward 에 넣는다. 구분 글((105))을 8부표3 1절 코드로
    바꾸고(grid_forms.credit_code), 안 되면 8호(갑) 공제 이름과 글자로 맞춘다. 당기 공제액이 없고 이월액만 있는 공제는 금액 0 으로
    더한다."""
    from ctax.prior.grid_forms import credit_code
    rows = _rows(cells, "8부표3")
    if not rows:
        return
    by_code: dict = {}
    for row in rows.values():
        name = row.get("105")
        if not name or not row.get("125"):
            continue
        code = credit_code(str(name)) or next((c["code"] for c in credits if c["code"] and _norm(c["name"]) == _norm(name)), None)
        key = code or str(name)
        by_code.setdefault(key, [str(name), 0])[1] += _int(row.get("125"))
    for key, (name, carry) in by_code.items():
        hit = next((c for c in credits if c["code"] == key), None)
        if hit:
            hit["carryforward"] = carry
        else:
            credits.append({"name": name, "code": key if re.fullmatch(r"\d[0-9A-Z]{2}", key) else None, "amount": 0,
                            "carryforward": carry})


def _credit_code(name, credits: list[dict]):
    """8호 부표3 2절 (105)구분 글 → 공제 코드. 1절 구분 이름으로 맞추고(grid_forms.credit_code), 안 되면 8호(갑) 공제 이름과
    글자로 맞춘다. 못 찾으면 None."""
    from ctax.prior.grid_forms import credit_code
    return credit_code(str(name)) or next((c["code"] for c in credits if c["code"] and _norm(c["name"]) == _norm(name)), None)


def credit_years_from(cells: list[Cell], credits: list[dict] | None = None) -> tuple[list[dict], list[str]]:
    """8호 부표3 2절 줄 → ([{code, name, year, period, due_current, due_carried, cut_min, cut_other, used, expired,
    carryforward}], 문제 글). 줄은 서식 차례 그대로이고 소계 · 합계 줄은 파서가 이미 뺐다. year 는 (106)사업연도 글의 끝 날
    연도(정수), period 는 인쇄된 글 그대로. due_current (107) · due_carried (108) · cut_min (121) 최저한세 미공제 · cut_other
    (122) 그 밖의 미공제 · used (123) · expired (124) · carryforward (125). 금액이 하나도 없는 줄은 넣지 않는다."""
    out, why = [], []
    for n, row in _rows(cells, "8부표3").items():
        amounts = {k: _int(row.get(k)) for k in ("107", "108", "121", "122", "123", "124", "125")}
        if not any(amounts.values()) and not any(isinstance(v, (int, float)) and v for v in row.values()):
            continue
        name = str(row.get("105") or "")
        period = str(row.get("106") or "")
        nums = re.findall(r"\d{4,8}", period)
        year = int(nums[-1][:4]) if nums else None
        if year is None:
            why.append(f"8호 부표3 2절 {n}줄({name[:20]})의 (106)사업연도 「{period}」 를 읽지 못했습니다")
        out.append({"code": _credit_code(name, credits or []), "name": name, "year": year, "period": period,
                    "due_current": amounts["107"], "due_carried": amounts["108"], "cut_min": amounts["121"],
                    "cut_other": amounts["122"], "used": amounts["123"], "expired": amounts["124"],
                    "carryforward": amounts["125"]})
    return out, why


def _employment_check(employment: dict, credit_years: list[dict]) -> list[str]:
    """10호의8 · 10호의9 의 세액공제액이 8호 부표3 2절 그 과세연도 줄의 (107)당기분과 같은지 본다. 부표3 줄이 없으면 보지 않는다."""
    why = []
    for key, code, name in (("10의8", "18F", "고용증대"), ("10의9", "18S", "통합고용")):
        e = employment.get(key)
        if not e or e.get("total") is None or not e.get("fy"):
            continue
        rows = [r for r in credit_years if r["code"] == code and r["year"] == e["fy"]]
        if rows and sum(r["due_current"] for r in rows) != e["total"]:
            why.append(f"조특 {key[:2]}호{key[2:]} 세액공제액 {e['total']:,} 이 8호 부표3 2절 {name} {e['fy']} 줄의 (107)당기분 "
                       f"{sum(r['due_current'] for r in rows):,} 과 다릅니다")
    return why


def _rnd_check(rnd: dict | None, credit_years: list[dict]) -> list[str]:
    """조특 3호(1) ㊶ 이 8호 부표3 2절 일반 연구 · 인력개발비 세액공제 그 과세연도 줄의 (107)당기분과 같은지 본다.
    부표3 줄이 없으면 보지 않는다."""
    if not rnd or rnd.get("공제세액") is None or not rnd.get("fy"):
        return []
    rows = [r for r in credit_years if r["code"] in RND_CODES and r["year"] == rnd["fy"]]
    if rows and sum(r["due_current"] for r in rows) != rnd["공제세액"]:
        return [f"조특 3호(1) ㊶ 해당 연도에 공제받을 세액 {rnd['공제세액']:,} 이 8호 부표3 2절 일반 연구 · 인력개발비 세액공제 "
                f"{rnd['fy']} 줄의 (107)당기분 {sum(r['due_current'] for r in rows):,} 과 다릅니다"]
    return []


def cells_from(cells: list[Cell]) -> dict:
    """한 줄 란(row 0) 전부 {서식: {란: 값}}. 금액은 정수, 1호는 글, 3호 세율은 인쇄된 % 정수(0.19 → 19)."""
    out: dict = {}
    for c in cells:
        if c.row_no != 0:
            continue
        if c.value is None:
            val = c.text
        elif c.form_code == "3" and c.item_code in RATE_CODES:
            val = int(round(c.value * 100))
        else:
            val = _int(c.value)
        out.setdefault(c.form_code, {})[c.item_code] = val
    for fc in ("1", "3", "50갑", "8갑"):
        out.setdefault(fc, {})
    return out


# ---------------------------------------------------------------- 회사 정보

COVER_NO = re.compile(r"第\s*(\d+)\s*期")
COVER_FROM = re.compile(r"自\s*(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")
COVER_TO = re.compile(r"至\s*(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")
PERIOD_1 = re.compile(r"(\d{4})[.\-](\d{1,2})[.\-](\d{1,2})\s*~\s*(\d{4})[.\-](\d{1,2})[.\-](\d{1,2})")


def clean_name(s: str) -> str:
    s = re.sub(r"주식회사|유한회사|㈜|[(（]?\s*[주유]\s*[)）]", "", s or "")
    return re.sub(r"\s+", "", s)


def cover_info(text: str) -> dict:
    """표지 글에서 기수 · 사업연도 · 법인명."""
    out = {}
    m = COVER_NO.search(text or "")
    if m:
        out["period_no"] = int(m.group(1))
    a, b = COVER_FROM.search(text or ""), COVER_TO.search(text or "")
    if a:
        out["fy_start"] = f"{a.group(1)}-{int(a.group(2)):02d}-{int(a.group(3)):02d}"
    if b:
        out["fy_end"] = f"{b.group(1)}-{int(b.group(2)):02d}-{int(b.group(3)):02d}"
        tail = (text or "")[b.end():].strip()
        if tail:
            out["name"] = clean_name(tail)
    return out


def sme_marks(page) -> dict:
    """51호 첫 쪽의 (26) 중소기업 · (27) 소기업 적정 여부 동그라미. {'26': True|False, '27': ...}. 동그라미 안 글자가 「적」
    이면 True, 「부」 면 False. 란 번호 글자 아래, 같은 열에 있는 첫 동그라미를 본다."""
    circles = []
    for d in page.get_drawings():
        r = d["rect"]
        if d["items"] and all(i[0] == "c" for i in d["items"]) and 8 < r.width < 45 and 8 < r.height < 35:
            t = re.sub(r"\s+", "", page.get_textbox(r))
            circles.append(((r.x0 + r.x1) / 2, r.y0, t))
    labels = {}
    for w in page.get_text("words"):
        if w[4] in ("(26)", "(27)") and w[0] > page.rect.width * 0.7:
            labels.setdefault(w[4][1:3], ((w[0] + w[2]) / 2, w[1]))
    out = {}
    ys = sorted(y for _, y in labels.values())
    for no, (xc, y) in labels.items():
        nxt = min((v for v in ys if v > y), default=1e9)
        hit = sorted((c for c in circles if abs(c[0] - xc) < 25 and y < c[1] < nxt), key=lambda c: c[1])
        if hit:
            t = hit[0][2]
            out[no] = True if t.startswith("적") else False if t.startswith("부") else None
    return out


def sector_51(page) -> dict:
    """51호 첫 쪽 사업요건 표 첫 줄의 업태((01) 칸 「( … )업」 괄호 안 글)와 기준경비율코드((04) 칸 여섯 자리 숫자).
    1호가 없는 신고본의 회사 정보(업태 · 주업종코드)로 쓴다. 못 찾으면 빈 dict."""
    words = page.get_text("words")
    head = next((w for w in words if "기준경비율코드" in w[4]), None)
    if head is None:
        return {}
    codes = sorted((w for w in words if re.fullmatch(r"\d{6}", w[4]) and w[1] > head[3]
                    and head[0] - 10 <= (w[0] + w[2]) / 2 <= head[2] + 10), key=lambda w: w[1])
    if not codes:
        return {}
    code = codes[0]
    yc = (code[1] + code[3]) / 2
    texts = [w[4] for w in sorted((w for w in words if abs((w[1] + w[3]) / 2 - yc) < 4 and w[2] <= code[0]),
                                  key=lambda w: w[0])]
    out = {"industry_code": code[4]}
    if "(" in texts:
        start = len(texts) - 1 - texts[::-1].index("(")
        biz = []
        for t in texts[start + 1:]:
            if t.startswith(")"):
                break
            biz.append(t)
        if biz:
            out["biz_type"] = "".join(biz)
    return out


def company_from(cells: list[Cell], cover: dict, sme: dict, sector: dict | None = None) -> dict:
    """회사 정보. 1호 란이 먼저이고, 1호가 없는 신고본은 업태 · 주업종코드를 51호(sector_51)에서 채운다."""
    one = {c.item_code: c.text for c in cells if c.form_code == "1" and c.row_no == 0}
    m = re.search(r"\s*⑩\s*주업종코드\s*(\S*)\s*$", one.get("9") or "")
    if m:                                       # ⑨ 종목 글이 길면 같은 줄 ⑩ 주업종코드가 한 낱말로 붙어 읽힌다
        one["9"] = one["9"][:m.start()].strip()
        one.setdefault("10", m.group(1) or None)
    sector = sector or {}
    return {"name": clean_name(one.get("3") or "") or cover.get("name", ""),
            "sme": sme.get("26"), "small": sme.get("27"),
            "kind_code": one.get("15"), "industry_code": one.get("10") or sector.get("industry_code"),
            "biz_type": one.get("8") or sector.get("biz_type"), "item": one.get("9"), "period_no": cover.get("period_no"),
            "biz_no": one.get("1")}


# ---------------------------------------------------------------- 확인사항

def problems_from(problems: list[Problem], cells: list[Cell], forms: list[dict]) -> list[Problem]:
    """파서 확인사항에서 「없어도 되는 서식」 과 값이 같은 중복을 빼고, 결손금 표 누락을 더한다."""
    codes = {f["code"]: f for f in forms}
    three = {c.item_code: c.value for c in cells if c.form_code == "3" and c.row_no == 0}
    kept = {(c.form_code, c.item_code, c.row_no): c.value for c in cells}
    cogs = codes.get("제조원가명세서")
    out = []
    for q in problems:
        if q.target_ref == "8갑" and not (three.get("17") or three.get("19")):
            continue                            # 공제감면이 없는 회사는 8호(갑)이 없다
        if q.target_ref == "std_cogs" and not (cogs and not cogs["blank"]):
            continue                            # 원가명세서 없는 회사
        if q.target_ref.endswith(".중복"):
            fc, item, row = q.target_ref[:-3].rsplit(".", 2)
            m = re.search(r"값\s*([-\d,]+)", q.why)
            if m and kept.get((fc, item, int(row))) == int(m.group(1).replace(",", "")):
                continue                        # 쪽마다 되풀이 찍힌 같은 값
        out.append(q)
    return out


def _loss_check(problems: list[Problem], cells: list[Cell], fy: str, losses: list[dict]) -> list[Problem]:
    """3호 06 이 음수인데 50호(갑) 결손금 표에 그해 줄이 없으면 확인사항을 내고, losses 에 3호 06 으로 만든 줄을 더한다
    (derived 「3호 06」). 다음 해 이월결손금 공제의 시작 값이 되기 때문이다. 신고본 분석에서 결손 PDF 4개 중 3개가 그해 줄을
    빠뜨렸다."""
    three = {c.item_code: c.value for c in cells if c.form_code == "3" and c.row_no == 0}
    income = three.get("06")
    out = [q for q in problems if q.target_ref != "loss.missing"]
    if income is not None and income < 0 and fy:
        years = sorted({r["year"] for r in losses})
        if fy not in years:
            out.append(Problem("loss.missing", f"{fy} 사업연도가 결손인데 50호(갑) 결손금 표에 그해 줄이 없다",
                               f"3호 06 각사업연도소득금액 {int(income):,}. 결손금 표의 연도: {', '.join(years) or '없음'}."
                               f" losses 에 {fy} 줄을 3호 06 으로 더했다. 이월결손금 공제 전에 확인 필요"))
            loss = -_int(income)
            losses.append({"year": fy, "incurred": loss, "used": 0, "remaining": loss, "derived": "3호 06"})
    return out


NUM = re.compile(r"^\(?-?[\d,]+\)?$")


def statement_rows(text: str) -> list[tuple[str, list[int]]]:
    """재무제표 쪽 글(낱말마다 줄바꿈) → [(과목, [금액, ...])]. 금액 앞의 글을 이어 붙여 과목으로 본다. 괄호 금액은 음수."""
    rows, label, nums = [], "", []
    for tok in (t.strip() for t in text.splitlines()):
        if not tok:
            continue
        if NUM.match(tok.replace(" ", "")) and any(ch.isdigit() for ch in tok):
            v = int(re.sub(r"[^\d]", "", tok))
            nums.append(-v if tok.startswith(("(", "-")) else v)
            continue
        if nums:
            rows.append((label, nums))
            label, nums = "", []
        label += tok.replace(" ", "")
    if nums:
        rows.append((label, nums))
    return rows


def _prior_column_loss(problems: list[Problem], pages: list[dict], cells: list[Cell], fy: str,
                       losses: list[dict]) -> list[Problem]:
    """결손금 표에 직전 사업연도(fy-1) 줄이 없는데 전기 신고서 손익계산서 비교란이 당기순손실이면 그 금액으로 결손금 줄을
    더한다(derived 「손익계산서 비교란」). 결손금 표를 비워 낸 신고서가 있어 이 비교란이 그해 결손을 알 수 있는 유일한 곳이다.
    세무상 결손금은 그해 신고서 3호 06 이라 회계 손실과 다를 수 있으니 확인사항을 함께 낸다. 당기 열이 3호 01 과 맞을 때만
    읽은 것으로 본다(열을 잘못 읽지 않았는지 보는 장치). 직전 해가 이익인데 이월결손금 공제(3호 07)가 0 이면 줄을 더하지 않는다."""
    if not fy.isdigit():
        return problems
    year = str(int(fy) - 1)
    if any(r["year"] == year for r in losses):
        return problems
    three = {c.item_code: c.value for c in cells if c.form_code == "3" and c.row_no == 0}
    ni = three.get("01")
    for p in pages:
        if hint_code(p.get("form_hint", ""))[0] != "손익계산서":
            continue
        for label, nums in statement_rows(p.get("text") or ""):
            name = re.sub(r"^[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩⅪⅫ0-9.]+", "", label)
            if name not in ("당기순손실", "당기순이익", "당기순손익", "당기순이익(손실)", "당기순손익(손실)") or len(nums) < 2:
                continue
            cur, prev = nums[0], nums[1]
            if name == "당기순손실":
                cur, prev = -cur, -prev
            if ni is None or _int(ni) != cur or prev >= 0:
                return problems
            loss = -prev
            if _int(three.get("06")) > 0 and not _int(three.get("07")):
                # 이익을 낸 해에 이월결손금 공제가 없었으면 그 앞 해 세무상 결손은 없었던 것으로 본다(공제는 고를 수 없다)
                return problems + [Problem("loss.prior_column", f"{year} 회계 손실이 있는데 {fy} 이월결손금 공제가 없다",
                                           f"전기 손익계산서 비교란 당기순손실 {loss:,}, {fy} 3호 07 은 0 이다. {year} 세무상 결손금이"
                                           f" 없었는지 확인 필요(있었다면 {fy} 공제 누락이다). 결손금 줄은 더하지 않았다")]
            used = min(loss, _int(three.get("07"))) if _int(three.get("06")) > 0 else 0
            losses.append({"year": year, "incurred": loss, "used": used, "remaining": loss - used,
                           "derived": "손익계산서 비교란"})
            losses.sort(key=lambda r: r["year"])
            return problems + [Problem("loss.prior_column", f"{year} 사업연도 결손금을 손익계산서 비교란으로 더했다",
                                       f"50호(갑) 결손금 표에 {year} 줄이 없고 전기 손익계산서 비교란 당기순손실이 {loss:,} 이다."
                                       f" 세무상 결손금은 {year} 신고서 3호 06 이라 다를 수 있다. 그해 신고서로 확인 필요")]
    return problems


# ---------------------------------------------------------------- 한 PDF

def build(pages: list[dict], cells: list[Cell], problems: list[Problem], cover_text: str = "", sme: dict | None = None,
          file_year: str = "", sector: dict | None = None) -> dict:
    """쪽 목록 · 칸 · 파서 확인사항 → 전기.json 본문(pdf 경로 빼고). PDF 없이 시험할 때도 이 함수를 쓴다."""
    forms = forms_from(pages, cells)
    cover = cover_info(cover_text)
    one = {c.item_code: c.text for c in cells if c.form_code == "1" and c.row_no == 0}
    m = PERIOD_1.search(one.get("11") or "")
    fy_start = cover.get("fy_start") or (f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}" if m else "")
    fy_end = cover.get("fy_end") or (f"{m.group(4)}-{int(m.group(5)):02d}-{int(m.group(6)):02d}" if m else "")
    fy = fy_start[:4] or file_year
    if not fy_end and fy:
        fy_end = f"{fy}-12-31"
    qs = problems_from(problems, cells, forms)
    losses = losses_from(cells)
    qs = _loss_check(qs, cells, fy, losses)
    qs = _prior_column_loss(qs, pages, cells, fy, losses)
    if sme is not None and ("26" not in sme or "27" not in sme) and "51" in {f["code"] for f in forms}:
        qs.append(Problem("51.marks", "51호 중소기업 · 소기업 적정 여부 동그라미를 찾지 못했다",
                          f"찾은 란: {', '.join(sorted(sme)) or '없음'}"))
    out_cells, out_rows = cells_from(cells), {}
    cells54, rows54, why54 = read_54(pages_of(pages, "54"))
    if cells54:
        out_cells["54"] = cells54
    if rows54:
        out_rows["54"] = rows54
    for why in why54:
        qs.append(Problem("54.read", "54호 주식등변동상황명세서를 다 읽지 못했다", why))
    listed = listed_from(pages)
    qs += _listed_check(listed, forms)
    cells29, why29 = read_29([p for p in pages_of(pages, "29") if any(f["code"] == "29" and not f["blank"] for f in forms)])
    if cells29:
        out_cells["29"] = cells29
    for why in why29:
        qs.append(Problem("29.read", "29호 업무용승용차관련비용명세서 2절 합계 줄을 다 읽지 못했다", why))
    rows29, why29c = carry_rows(pages_of(pages, "29"))
    if rows29:
        out_rows["29"] = rows29
    for why in why29c:
        qs.append(Problem("29.carry", "29호 3절 감가상각비(상당액) 한도초과금액 이월명세를 다 읽지 못했다", why))
    pages51 = pages_of(pages, "51")
    if pages51:
        got51 = scale_51(pages51[0].get("words") or [])
        if got51:
            out_cells["51"] = got51
    rows21, why21 = read_21(pages_of(pages, "21"))
    if rows21:
        out_rows["21"] = rows21
    for why in why21:
        qs.append(Problem("21.read", "21호 기부금조정명세서 5 · 6절(기부금 이월액)을 다 읽지 못했다", why))
    for code, reader in (("22", read_22), ("세금공과금명세서", read_taxes)):     # 빈 쪽이면 줄이 없다
        got = reader(pages_of(pages, code))
        if got:
            out_rows[code] = got
    credits = credits_from(cells)
    credit_years, why_years = credit_years_from(cells, credits)
    for why in why_years:
        qs.append(Problem("8부표3.years", "8호 부표3 2절 연도별 줄을 다 읽지 못했다", why))
    employment, why_emp = read_employment(pages_of(pages, "조특10의8"),
                                          pages_of(pages, "조특10의9") + pages_of(pages, "조특10의9_1"), fy)
    for why in why_emp + _employment_check(employment, credit_years):
        qs.append(Problem("employment.read", "조특 10호의8 · 10호의9(고용 세액공제 공제세액계산서)를 확인해야 한다", why))
    if any(not f["blank"] for f in forms if f["code"] == "조특10의9_2"):
        qs.append(Problem("employment.10의9_2", "조특 10호의9서식(2)는 아직 읽지 않는다",
                          "2026. 3. 20. 신설 서식(2026년 12월 31일이 속하는 과세연도부터)이라 employment 에 넣지 않았다"))
    e8 = employment.get("10의8")
    if e8:
        parts = {f"{r['차수']}차_계": r["amount"] for r in e8["by_year"] if r["amount"]}
        if e8.get("total"):
            parts["합계"] = e8["total"]
        if parts:
            out_cells["조특10의8"] = parts
    rnd_pages = pages_of(pages, RND_FORM)
    extra = {}
    if rnd_pages:
        extra["rnd"], why_rnd = read_rnd(rnd_pages, fy)
        for why in why_rnd + _rnd_check(extra["rnd"], credit_years):
            qs.append(Problem("rnd.read", "조특 3호(1)(일반연구 및 인력개발비 명세서)를 확인해야 한다", why))
    return {"fy": fy, "fy_end": fy_end, "forms": forms, "company": company_from(cells, cover, sme or {}, sector if not any(c.form_code == "1" for c in cells) else None),
            "cells": out_cells, "rows": out_rows, "adjustments": adjustments_from(cells), "reserves": reserves_from(cells),
            "losses": losses, "credits": credits, "credit_years": credit_years, "employment": employment, **extra,
            "listed": listed,
            "problems": [{"title": q.title, "why": q.why, "ref": q.target_ref} for q in qs]}


# ---------------------------------------------------------------- 총괄표

TOTAL_FORM = "세무조정계산서총괄표"
TOTAL_ROW = re.compile(r"^\d+$")
TOTAL_CODE = re.compile(r"^(조특|제|별지)")


def total_code(text: str) -> str | None:
    """총괄표 서식번호 글(「제19호(갑)」 · 「제3호2(1)」 · 「조특법제10호8」 · 「별지제29호서식」) → 6절 서식 code. 국조법 서식 · 「제00호」 는 None."""
    t = re.sub(r"\s", "", text or "")
    if not t or t.startswith("국조"):
        return None
    law = "조특" if t.startswith("조특") else ""
    t = re.sub(r"^(조특법(시행규칙|규칙)?|별지)?제?", "", t).replace("서식", "")
    m = re.match(r"^(\d+(?:-\d+)?)호(\d+)(.*)$", t)
    if m:
        t = f"{m.group(1)}호의{m.group(2)}{m.group(3)}"
    if not re.match(r"^[1-9]\d*(-\d+)?호", t):
        return None
    code, known = hint_code(law + t)
    return code if known else None


def listed_from(pages: list[dict]) -> list[dict]:
    """세무조정계산서총괄표 쪽 글 → O 가 찍힌 줄. 줄은 「연번 · 서식번호 · 서식명 · O(해당사항) · O(첨부)」 차례로 찍힌다."""
    out, seen = [], set()
    for p in pages_of(pages, TOTAL_FORM):
        lines = [x.strip() for x in (p.get("text") or "").splitlines() if x.strip()]
        i = 0
        while i < len(lines):
            if not (TOTAL_ROW.match(lines[i]) and i + 1 < len(lines) and TOTAL_CODE.match(lines[i + 1])):
                i += 1
                continue
            no, j, name = lines[i + 1], i + 2, []
            while j < len(lines) and not TOTAL_ROW.match(lines[j]) and lines[j] != "O":
                name.append(lines[j])
                j += 1
            marks = 0
            while j < len(lines) and lines[j] == "O":
                marks += 1
                j += 1
            code = total_code(no)
            if marks and code and code not in seen:
                seen.add(code)
                out.append({"code": code, "no": no, "name": "".join(name), "applies": True, "attached": marks >= 2})
            i = j
    return out


def _listed_check(listed: list[dict], forms: list[dict]) -> list[Problem]:
    have = {f["code"] for f in forms}
    out = []
    for x in listed:
        if x["attached"] and x["code"] not in have:
            out.append(Problem(f"총괄표.{x['code']}", f"총괄표에 {x['no']} {x['name']} 첨부 O 가 있는데 PDF 에 그 서식이 없다",
                               "받은 PDF 가 신고서 일부만 담았을 수 있다. 그 서식을 내지 않았다고 보지 말고 회사에 그 쪽을 받는다"))
    return out


def pages_of(pages: list[dict], code: str) -> list[dict]:
    """서식 code 의 쪽(쪽 차례). forms_from 과 같이 파서가 정한 form_code 가 먼저, 없으면 쪽 머리 표시."""
    out = []
    for p in pages:
        got = p.get("form_code") or hint_code(p.get("form_hint", ""))[0]
        if got == code:
            out.append(p)
    return out


def read_prior(pdf_path) -> dict:
    """PDF 하나 → 전기.json 본문(pdf 경로 빼고)."""
    import pymupdf
    pages = split_pages(pdf_path)
    cells, problems = read_cells(pages)
    doc = pymupdf.open(str(pdf_path))
    try:
        cover = doc[0].get_text() if len(doc) else ""
        sme, sector = {}, {}
        first51 = next((p["page_no"] for p in pages if p.get("form_hint") == "51호"), None)
        if first51:
            sme = sme_marks(doc[first51 - 1])
            sector = sector_51(doc[first51 - 1])
        for p in pages:                             # 고용 세액공제 계산서는 칸 테두리 선으로 읽는다(employ.py)
            if hint_code(p.get("form_hint", ""))[0] in EMPLOY_FORMS + (RND_FORM,) and "grid" not in p:
                p["grid"] = grid.page_data(doc[p["page_no"] - 1])
    finally:
        doc.close()
    m = re.match(r"(\d{4})", str(getattr(pdf_path, "name", pdf_path)).split("\\")[-1].split("/")[-1])
    return build(pages, cells, problems, cover, sme, m.group(1) if m else "", sector)
