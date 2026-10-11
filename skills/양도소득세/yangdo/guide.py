# -*- coding: utf-8 -*-
"""홈택스 입력 안내서와 부속서류 목록. 신고값(C8)을 읽어 마크다운 글자로 만든다. 계산하지 않는다.

전자신고 파일 형식검증이 막힐 때 홈택스 「양도소득세 정기신고(일반)」 화면에 직접 입력하도록, 화면 순서대로 넣을 값을 적는다.
화면 이름은 조사 자료(근거조사 조사요약 「서식전자신고질문지」, 2025-11-27 국세청 홈택스 신고 대본)에서 확인한 것만 쓰고,
확인하지 못한 이름에는 「(화면 이름 확인 필요)」 를 붙인다.

인적사항을 다루는 규칙(global.md 「실행 중 정한 것」):
  주민등록번호·전화번호는 쓰지 않는다. 신고인 본인 정보는 「신고인 JSON 을 보고 입력」 이라고만 적는다.
  입력 안내서는 출력 폴더의 로컬 파일이라 자산 소재지, 거래상대방 상호, 양수인 성명은 적는다. 화면에 직접 쳐 넣는 값이다.
신고값의 확인사항 가운데 전자신고 파일 레코드에 관한 것은 싣지 않는다.
"""
import json
import os
import re

from yangdo import SKILL_DIR
from yangdo import codes as rate_codes

EFILE_DIR = os.path.join(SKILL_DIR, "efile")
NEED_NAME = "(화면 이름 확인 필요)"
NEED_VALUE = "입력 필요"
MENU = "세금신고 > 양도소득세 신고 > 양도소득세 신고하기 > 정기신고(일반)"

# 이 안내서의 절 이름, 홈택스 화면 이름. 화면 이름은 2025-11-27 국세청 대본의 순서(기본정보, 양수인, 양도자산 및 거래일,
# 양도소득금액, 세율 선택 도우미, 장특공 계산기, 세액계산, 분납·환급계좌)에서 온다
SCREENS = (
    ("기본정보", "기본정보"),
    ("양수인", "양수인"),
    ("양도자산", "양도자산 및 거래일"),
    ("취득가액", "양도소득금액의 취득가액 입력 " + NEED_NAME),
    ("필요경비", "양도소득금액의 필요경비 상세"),
    ("세액계산", "세율 선택 도우미, 장특공 계산기, 세액계산"),
    ("납부", "분납·환급계좌, 제출 뒤 신고내역 조회"),
)

KIND_LABEL = {"예정": "예정신고", "확정": "확정신고(예정신고를 하지 않은 정기신고)"}
BUYER_ID_LABEL = {"1": "주민등록번호", "2": "법인사업자등록번호 또는 법인등록번호"}
LTD_LABEL = {"표2": "1세대1주택(표2)", "표1": "1세대1주택 외(표1)", "없음": "적용배제"}
EVIDENCE_NOTE = {"10": "기타(계좌이체 등 금융거래 증빙)"}
ACQ_EXPENSE_CODE = "111"          # 부표3 매입가액
DEPRECIATION_CODE = "141"         # 부표3 감가상각비(취득가액에서 뺀다)
ACQ_TAX_ELECTRONIC = "11201"      # 부표3 취득세

# 신고값 확인사항 가운데 전자신고 파일 전용 문장을 가르는 표지. 레코드 칸 번호(05-46, 03-31), 「0n 레코드」, 법정동코드, 등기목적·등기원인.
# 칸 번호 무늬는 날짜 조각(2027-01-31 의 01-31)을 칸 번호로 읽지 않는다: 앞이 숫자나 - 이거나 뒤에 숫자나 - 가 이어지면 칸 번호가 아니다.
# 「레코드」 라는 글자만으로 거르지 않는다: 「필요경비에서 뺀 지출이라 부표3·07 레코드에 넣지 않았다」는 화면 입력에도 알려야 하는 문장이다
FILE_ONLY = re.compile(r"(?<![\d-])0[1-7]-\d+(?![\d-])|\b0[1-7] 레코드|법정동코드|등기목적|등기원인")
KEEP_NOTE = ("필요경비에서 뺀",)

_cache = {}


def _codes():
    if "codes" not in _cache:
        with open(os.path.join(EFILE_DIR, "codes_c116300.json"), encoding="utf-8") as f:
            _cache["codes"] = json.load(f)
    return _cache["codes"]


# ------------------------------------------------------------ 글자 도구

def _n(x):
    return "{:,}".format(int(x or 0))


def _won(x):
    return _n(x) + "원"


def _date(s):
    """YYYYMMDD 또는 YYYY-MM-DD → YYYY-MM-DD. 비면 빈 글자."""
    s = str(s or "")
    if len(s) == 8 and s.isdigit():
        return "%s-%s-%s" % (s[:4], s[4:6], s[6:])
    return s


def _cell(x):
    s = "-" if x is None or x == "" else str(x)
    return s.replace("|", "\\|").replace("\n", " ")


def _table(head, rows):
    out = ["| " + " | ".join(head) + " |", "|" + "|".join(" --- " for _ in head) + "|"]
    for r in rows:
        out.append("| " + " | ".join(_cell(c) for c in r) + " |")
    return out


def _pairs(rows):
    return _table(["항목", "넣을 값"], rows)


def _area(land, bldg):
    return "토지 %s㎡ · 건물 %s㎡" % (land, bldg)


def _code_name(group, code):
    for v in _codes()[group].values():
        if v.get("코드") == code:
            return v.get("이름") or code
    return code


def _evidence_name(code):
    return (_codes()["증빙종류목록"].get(code) or {}).get("이름") or code


def _expense_meta():
    """전자코드 → {필수, 묶음}. 필수는 지급금액이 있으면 사업자번호·지급일자·증빙종류를 적어야 하는 구분."""
    if "meta" not in _cache:
        _cache["meta"] = {v["전자코드"]: v for v in _codes()["필요경비구분"].values()}
    return _cache["meta"]


def _is_acq(row):
    """부표3 행이 취득가액 묶음(매입가액·취득세·부대비용·가산·차감)이면 참."""
    return (_expense_meta().get(row.get("전자코드")) or {}).get("묶음", "").startswith("취득가액")


def _is_deduct(row):
    return "차감항목" in (_expense_meta().get(row.get("전자코드")) or {}).get("묶음", "")


def _sheet3(rv):
    return {s["자산"]: s for s in rv.get("부표3") or []}


def _head(title, kind_note=None, enter=True):
    """머리글. enter 가 참이면 주민등록번호·전화번호를 화면에 입력하는 안내를 붙인다(입력 안내서만)."""
    secret = "주민등록번호와 전화번호는 이 파일에 적지 않는다."
    if enter:
        secret += " 신고인 JSON 에 있는 「신고인 본인 정보」를 보고 화면에 입력한다."
    out = ["# " + title, "", "- 이 파일에는 신고 내용이 들어 있다. 공유에 주의한다.", "- " + secret]
    if kind_note:
        out += kind_note
    return out


# ------------------------------------------------------------ 입력 안내서

def _row_table(rows):
    """부표3 행 → 필요경비 상세 표(구분 · 증빙종류 · 거래상대방 · 사업자번호 · 지급금액 · 지급일자)."""
    meta = _expense_meta()
    body = []
    for r in rows:
        must = (meta.get(r["전자코드"]) or {}).get("필수", False)
        label = r["구분"] + (" (취득가액에서 뺀다)" if _is_deduct(r) else "")
        ev = _evidence_name(r["증빙코드"]) if r["증빙코드"] else (NEED_VALUE if must else "")
        name = r["상호"] or NEED_VALUE
        biz = r["사업자번호"] or (NEED_VALUE if must else "")
        day = r["지급일"] or (NEED_VALUE if must and r["금액"] else "")
        body.append([label, ev, name, biz, _won(r["금액"]), day])
    return _table(["구분", "증빙종류", "거래상대방(상호)", "사업자번호", "지급금액", "지급일자"], body)


def _sec_basic(rv):
    s, p = rv["신고"], rv["신고인"]
    cd = _codes()
    code = p.get("코드") or {}
    cn = (cd["국가"].get(p.get("국적")) or {}).get("이름") or p.get("국적")
    rows = [
        ["메뉴", MENU],
        ["신고구분", KIND_LABEL.get(s["구분"], s["구분"])],
        ["귀속연도", s.get("귀속연도") or str(s["양도일자"])[:4]],
        ["양도일", _date(s["양도일자"]) + (" (양도일이 여럿이면 마지막 날)" if len(rv["부표1"]) > 1 else "")],
        ["작성일", _date(s["작성일"]) + " (이 날 신고하는 것으로 세액을 계산했다)"],
        ["신고인 본인 정보", "성명, 주민등록번호, 주소, 전화번호가 로그인 정보로 화면에 나오는지는 (확인 필요)이다. 나오지 않거나 다르면 "
                        "신고인 JSON 의 신고인 절을 보고 직접 입력한다. 이 안내서에는 적지 않는다"],
        ["거주구분", (cd["거주구분"].get(p.get("거주구분")) or {}).get("이름") or p.get("거주구분")],
        ["내외국인", (cd["내외국인"].get(p.get("내외국인")) or {}).get("이름") or p.get("내외국인")],
        ["거주지국", code.get("거주지국명") or p.get("거주지국")],
        ["국적", cn],
    ]
    return ["## 1. 기본정보 (홈택스 화면: 기본정보)", ""] + _pairs(rows) + [""]


def _sec_buyers(rv):
    out = ["## 2. 양수인 (홈택스 화면: 양수인)", ""]
    if not rv.get("양수인"):
        return out + ["신고값에 양수인이 없다. 신고인 JSON 의 양수인 절을 채운 뒤 신고값을 다시 만든다.", ""]
    body = []
    cd = _codes()
    for b in rv["양수인"]:
        rel = b.get("관계표기") or ""
        name = (cd["양수인관계목록"].get(b.get("관계")) or {}).get("이름")
        if name and name != rel:
            rel = (rel + " " if rel else "") + "(%s)" % name
        share = "%s/%s" % (b.get("지분분자"), b.get("지분분모"))
        body.append([b["일련번호"], b["자산"], b.get("성명"), (cd["내외국인"].get(b.get("내외국인")) or {}).get("이름"),
                     rel, share])
    out += _table(["순번", "자산", "성명", "내외국인", "양도인과의 관계", "지분"], body)
    ids = sorted({BUYER_ID_LABEL.get(b.get("구분"), "등록번호") for b in rv["양수인"]})
    out += ["", "%s는 신고인 JSON 의 양수인 절을 보고 입력한다. 이 안내서에는 적지 않는다." % ", ".join(ids), ""]
    return out


def _sec_assets(rv):
    out = ["## 3. 양도자산 (홈택스 화면: 양도자산 및 거래일)", ""]
    detail = {c["자산"]: c for c in rv["전자신고"]["계산명세"]}
    for a in rv["부표1"]:
        tax_class = _code_name("과세구분", detail[a["자산"]]["과세구분"])
        rows = [
            ["과세구분", tax_class],
            ["자산종류", _code_name("자산종류", detail[a["자산"]]["자산의종류"])],
            ["소재지", a.get("소재지")],
            ["총면적", _area(a["총면적_토지"], a["총면적_건물"])],
            ["지분", "%s/%s" % (a.get("지분분자", 1), a.get("지분분모", 1))],
            ["양도면적", _area(a["양도면적_토지"], a["양도면적_건물"])],
            ["취득면적", _area(a["취득면적_토지"], a["취득면적_건물"])],
            ["양도일", "%s (원인: %s)" % (a["양도일"], a.get("양도원인") or "-")],
            ["취득일", "%s (원인: %s)" % (a["취득일"], a.get("취득원인") or "-")],
        ]
        if a.get("보유기간") or a.get("거주기간"):
            rows.append(["보유기간 · 거주기간", "%s · %s %s" % (a.get("보유기간") or "-", a.get("거주기간") or "-", NEED_NAME)])
        out += ["### 자산 %s" % a["자산"], ""] + _pairs(rows) + [""]
    out += ["화면의 선택 항목 이름이 위 이름과 다르면 뜻이 같은 항목을 고른다. 뜻이 분명하지 않으면 입력을 멈추고 확인한다.", ""]
    return out


def _sec_acquisition(rv):
    out = ["## 4. 취득가액 (홈택스 화면: 양도소득금액)", "",
           "양도소득금액 화면에서 양도가액과 취득가액을 넣는다. 아래 표의 행은 필요경비 상세에 구분을 골라 한 줄씩 입력한다. "
           "취득가액 종류와 기준시가를 넣는 란의 이름은 확인하지 못했다 %s. "
           "홈택스가 국세청 자료로 취득세와 현금영수증 수수료를 자동으로 채울 수 있다(2025-11-27 국세청 대본). "
           "자동으로 채운 금액이 아래와 다르면 증빙을 보고 고친다." % NEED_NAME, ""]
    sheet3 = _sheet3(rv)
    for a in rv["부표1"]:
        sh = sheet3.get(a["자산"])
        rows = [["양도가액", _won(a["양도가액"]) + (" (공동소유라 본인 지분 금액)" if a.get("지분분모", 1) != 1 else "")]]
        if a["취득가액종류"]:
            rows += [["취득가액 종류", a["취득가액종류"]], ["취득가액", _won(a["취득가액"])]]
        out += ["### 자산 %s" % a["자산"], ""] + _pairs(rows) + [""]
        if not a["취득가액종류"]:
            out += ["전액 비과세 자산이라 취득가액을 입력하지 않는다.", ""]
        if sh:
            acq = [r for r in sh["행"] if _is_acq(r)]
            if acq:
                out += _row_table(acq) + [""]
            out += ["취득가액 합계 %s" % _won(sh["취득가액계"]), ""]
        if a["취득가액종류"] == "환산취득가액":
            b = a["기준시가"]
            if a["취득가액"]:
                out += ["환산취득가액은 양도 당시와 취득 당시 기준시가로 계산한다. 화면에 기준시가를 넣고 환산 결과가 위 취득가액과 같은지 본다.", ""]
            else:
                out += ["환산취득가액과 개산공제의 합이 자본적지출과 양도비의 합보다 작아서 자본적지출과 양도비를 필요경비로 하고 "
                        "취득가액은 0원으로 한다(소득세법 제97조②2호 단서). 화면에 기준시가를 넣었을 때 같은 결과가 나오는지 본다.", ""]
            out += _table(["기준시가", "건물(주택 포함)", "토지", "합계"],
                          [["양도 당시", _won(b["양도_건물"]), _won(b["양도_토지"]), _won(b["양도_합계"])],
                           ["취득 당시", _won(b["취득_건물"]), _won(b["취득_토지"]), _won(b["취득_합계"])]]) + [""]
        elif a["취득가액종류"] in ("매매사례가액", "감정가액"):
            out += ["%s 근거 자료는 부속서류 목록에서 확인한다." % a["취득가액종류"], ""]
    return out


def _sec_expenses(rv):
    out = ["## 5. 필요경비 (홈택스 화면: 양도소득금액의 필요경비 상세)", "",
           "취득세와 취득 부대비용은 앞 절 4 의 표에 있다. 이 절은 자본적지출, 양도비 같은 나머지 필요경비다. "
           "구분 · 증빙종류 · 거래상대방 · 지급금액 · 지급일자를 한 줄씩 입력한다.", ""]
    sheet3 = _sheet3(rv)
    for a in rv["부표1"]:
        sh = sheet3.get(a["자산"])
        out += ["### 자산 %s" % a["자산"], ""]
        other = [r for r in (sh["행"] if sh else []) if not _is_acq(r)]
        if other:
            out += _row_table(other) + [""]
        elif a["기타필요경비"]:
            out += ["입력할 행이 없다. 기타필요경비 %s은 %s 자산에 쓰는 개산공제로 계산된 금액이다. "
                    "화면이 자동으로 계산한 값이 같은지 본다." % (_won(a["기타필요경비"]), a["취득가액종류"]), ""]
        else:
            out += ["입력할 필요경비가 없다.", ""]
        out += ["기타필요경비 합계 %s" % _won(a["기타필요경비"]), ""]
    return out


def _sec_tax(rv):
    s, sheets = rv["신고"], rv["부표1"]
    out = ["## 6. 세액계산 (홈택스 화면: 세율 선택 도우미, 장특공 계산기, 세액계산)", ""]
    # 세율 선택 도우미
    table = rate_codes.load().data.get("세율구분", {})
    out += ["### 세율 선택 도우미", "", "도우미의 질문에 답해 아래 세율구분이 나오는지 본다. 다르면 사실관계 입력을 다시 확인한다.", ""]
    body = []
    for a in sheets:
        code = a["세율구분표기"].split("-")[-1]
        info = table.get(code) or {}
        body.append([a["자산"], a["세율구분표기"], info.get("세율"), info.get("대상")])
    out += _table(["자산", "세율구분", "세율", "대상"], body) + [""]
    # 장특공 계산기
    out += ["### 장특공 계산기", "", "장기보유특별공제 계산기에 아래 값을 넣고 결과가 같은지 본다.", ""]
    body = []
    for a in sheets:
        body.append([a["자산"], a.get("보유기간"), a.get("거주기간") or a.get("장특공거주기간"),
                     "%s %s" % (a["장특공코드"], _ltd_label(a["장특공코드"])), _won(a["장특공"])])
    out += _table(["자산", "보유기간", "거주기간", "장특공 구분", "장기보유특별공제"], body) + [""]
    # 양도소득금액 확인표
    out += ["### 계산 결과 확인", "", "홈택스가 자동으로 계산한 값이 아래와 같은지 본다. 다르면 제출하지 않고 입력한 금액을 다시 확인한다.", ""]
    keys = (("양도가액", "양도가액"), ("취득가액", "취득가액"), ("기타필요경비", "기타필요경비"), ("양도차익", "양도차익"),
            ("비과세양도차익", "비과세양도차익"), ("과세양도차익", "과세양도차익"), ("장특공", "장기보유특별공제"),
            ("양도소득금액", "양도소득금액"))
    total = rv["부표1합계"]
    head = ["항목"] + [a["자산"] for a in sheets] + (["합계"] if len(sheets) > 1 else [])
    body = []
    for k, label in keys:
        row = [label] + [_won(a[k]) for a in sheets]
        if len(sheets) > 1:
            row.append(_won(total[k]))
        body.append(row)
    out += _table(head, body) + [""]
    # 합산신고대상
    out += ["### 합산신고대상 불러오기", "",
            "같은 해에 먼저 신고한 양도가 없어야 이 안내서의 값이 맞다. 화면이 합산신고대상을 불러오면 입력을 멈추고 확인한다. "
            "기신고 합산은 이 스킬이 계산하지 않는다.", ""]
    # 세액
    main = rv["본지"]
    labels = [x["표기"] for x in main["세율구분"]]
    cols = main["열"]
    if not labels:
        return out + ["### 세액계산 결과", "", "과세되는 자산이 없다(전액 비과세). 세액을 입력하지 않는다.", ""]
    rows = (("양도소득금액", "양도소득금액"), ("기본공제", "기본공제"), ("과세표준", "과세표준"), ("세율", "세율"),
            ("산출세액", "산출세액"), ("감면세액", "감면세액"), ("전자신고공제", "전자신고세액공제"), ("납부할세액", "납부할 세액"))

    def put(k, v):
        if v is None or v == "":
            return "-"
        return v if k == "세율" else _won(v)

    if len(labels) == 1:
        head = ["항목", "합계 (세율구분 %s)" % labels[0]]
        body = [[label, put(k, cols["합계"].get(k))] for k, label in rows]
    else:
        head = ["항목"] + ["세율구분 %s" % x for x in labels] + ["합계"]
        body = [[label] + [put(k, cols[x].get(k)) for x in labels] + [put(k, cols["합계"].get(k))] for k, label in rows]
    out += ["### 세액계산 결과", ""] + _table(head, body) + [""]
    note = ["감면세액, 외국납부세액공제, 원천징수세액, 가산세는 0원이라 입력하지 않는다."]
    if s["구분"] == "예정":
        note.append("전자신고세액공제 %s을 넣었다. 홈택스가 자동으로 적용하는지는 (확인 필요)이다. 화면 값이 이 금액과 같은지 본다. "
                    "직접 넣는 란이 있으면 이 금액을 넣는다." % _won(cols["합계"].get("전자신고공제")))
    else:
        note.append("확정신고에는 전자신고세액공제가 없다.")
    return out + [" ".join(note), ""]


def _ltd_label(code):
    names = {v: k for k, v in _forms_ltd().items()}
    return LTD_LABEL.get(names.get(code), "")


def _forms_ltd():
    if "ltd" not in _cache:
        with open(os.path.join(SKILL_DIR, "forms", "서식판.json"), encoding="utf-8") as f:
            _cache["ltd"] = json.load(f)["부표1_장특공코드"]["코드"]
    return _cache["ltd"]


def _sec_payment(rv):
    s = rv["신고"]
    t = rv["본지"]["열"]["합계"]
    loc = rv["지방"]["열"]["합계"]
    due, inst = t.get("납부할세액") or 0, t.get("분납") or 0
    out = ["## 7. 납부 (홈택스 화면: 분납·환급계좌, 제출 뒤 신고내역 조회)", ""]
    rows = [["납부할 세액(국세)", _won(due)]]
    if s.get("분납신청") and inst:
        rows += [["분납", "신청한다"], ["분납할 세액", _won(inst)], ["신고기한 내 납부할 세액", _won(t.get("신고기한내납부"))]]
    elif s.get("분납신청"):
        rows += [["분납", "신청했지만 납부할 세액이 분납 기준 이하라 분납할 세액이 0원이다. 분납 란은 비워 둔다"],
                 ["신고기한 내 납부할 세액", _won(due)]]
    else:
        rows += [["분납", "분납하지 않는다"], ["신고기한 내 납부할 세액", _won(due)]]
    rows.append(["환급계좌", "입력하지 않는다. 환급받을 세액이 없다" if due > 0 else "환급받을 세액이 있으면 신고인 JSON 의 환급계좌를 본다"])
    out += _pairs(rows) + [""]
    out += ["신고서를 제출한 뒤 신고내역 조회에서 접수증과 납부서를 출력한다. 부속서류는 「신고 부속·증빙서류 제출」 메뉴에서 올린다. "
            "목록은 부속서류 목록 파일에 있다.", ""]
    out += ["### 지방소득세 (위택스)", "",
            "지방소득세는 국세와 따로 신고한다. 홈택스 신고를 마친 뒤 신고내역 화면의 「지방소득세 신고하기」 버튼으로 위택스에 연계한다"
            "(2020년 화면 기준, 지금 화면의 버튼 이름은 확인이 필요하다). 신고기한은 위택스 화면에서 확인한다.", ""]
    out += _pairs([["과세표준", _won(loc.get("과세표준"))], ["세율", loc.get("세율") or "-"], ["산출세액", _won(loc.get("산출세액"))],
                   ["납부할 세액(지방소득세)", _won(loc.get("납부할세액"))]]) + [""]
    out += ["위택스 화면에 채워진 값이 위 금액과 다르면 위택스 값을 확인한다. 지방소득세 전자신고세액공제는 %s으로 계산했다."
            % _won(loc.get("전자신고공제")), ""]
    return out


def _sec_notes(rv):
    notes = [x for x in rv.get("확인사항") or [] if any(k in x for k in KEEP_NOTE) or not FILE_ONLY.search(x)]
    if not notes:
        return []
    out = ["## 확인사항", ""] + ["- " + x for x in notes]
    return out + ["", "전자신고 파일에만 쓰는 확인사항은 신고값의 확인사항에 있다. 이 안내서에는 싣지 않는다.", ""]


def hometax_input(rv):
    """홈택스 「양도소득세 정기신고(일반)」 화면 순서대로 넣을 값. 마크다운."""
    body = []
    for sec in (_sec_basic, _sec_buyers, _sec_assets, _sec_acquisition, _sec_expenses, _sec_tax, _sec_payment, _sec_notes):
        body += sec(rv)
    notes = [
        "- 전자신고 파일 형식검증이 통과하면 이 안내서는 필요 없다. 형식검증이 막힐 때 홈택스 화면에 직접 입력하는 용도다.",
        "- 홈택스가 자동으로 채우거나 계산한 값이 아래 값과 다르면 제출하지 않는다. 입력한 항목을 다시 확인하고, 그래도 다르면 "
        "신고서 작성을 멈추고 알린다."]
    if any(NEED_VALUE in line for line in body if line.startswith("|")):
        notes.append("- 표의 「%s」는 신고값에 값이 없는 항목이다. 계약서 등을 보고 화면에 직접 입력하거나, 신고인 JSON 과 사실관계에 "
                     "값을 채운 뒤 신고값을 다시 만든다." % NEED_VALUE)
    out = _head("양도소득세 홈택스 입력 안내서", notes + ["", "## 화면 순서", ""])
    out += _table(["순서", "이 안내서의 절", "홈택스 화면"], [[i, name, screen] for i, (name, screen) in enumerate(SCREENS, 1)]) + [""]
    t = rv["본지"]["열"]["합계"]
    loc = rv["지방"]["열"]["합계"]
    out += ["## 신고 요약", "",
            "- 신고: %s, 양도 자산 %d건" % (KIND_LABEL.get(rv["신고"]["구분"], rv["신고"]["구분"]), len(rv["부표1"])),
            "- 국세: 산출세액 %s, 납부할 세액 %s" % (_won(t.get("산출세액")), _won(t.get("납부할세액"))),
            "- 지방소득세: 산출세액 %s (위택스에서 따로 신고)" % _won(loc.get("산출세액")), ""]
    return "\n".join(out + body).rstrip() + "\n"


# ------------------------------------------------------------ 부속서류 목록

def _temporary_two_house(result, aid):
    """엔진 판정이 일시적 2주택이면 그 판정 행을 돌려준다. 아니면 None. 판정은 엔진이 하고 여기서는 읽기만 한다."""
    for row in ((result or {}).get("계산") or {}).get("자산") or []:
        if row.get("id") == aid and (row.get("판정") or {}).get("일시적2주택"):
            return row["판정"]
    return None


def _evidence_groups(rows):
    """증빙종류 코드 순서대로 (이름, 행들). 증빙종류가 없는 행은 마지막 묶음."""
    groups = {}
    for r in rows:
        groups.setdefault(r["증빙코드"], []).append(r)
    out = []
    for code in sorted(k for k in groups if k):
        out.append((EVIDENCE_NOTE.get(code) or _evidence_name(code), groups[code]))
    if "" in groups:
        out.append(("증빙종류 미입력(종류를 정한 뒤 해당 서류를 올린다)", groups[""]))
    return out


def _expense_line(r, lead=""):
    extra = [x for x in (lead,
                         ("거래상대방 %s" % r["상호"]) if r["상호"] else "",
                         ("사업자번호 %s" % r["사업자번호"]) if r["사업자번호"] else "",
                         ("지급일 %s" % r["지급일"]) if r["지급일"] else "") if x]
    return "- [ ] %s %s%s" % (r["구분"], _won(r["금액"]), (" (" + ", ".join(extra) + ")") if extra else "")


def attachments(rv, facts, result):
    """신고 부속·증빙서류 목록. 자산마다 매매계약서 사본, 필요경비 증빙(증빙종류별 묶음), 환산이면 기준시가 자료,
    일시적 2주택이면 신규 주택 취득 계약서. 마크다운.

    일시적 2주택은 엔진 결과 result["계산"]["자산"][i]["판정"]["일시적2주택"] 만 읽는다. 엔진 결과에는 신규 주택 id 가 없어
    신규 주택은 일반 문구로 적는다. facts 는 계약(C9)에 따라 받지만 이 함수는 판정에 쓰지 않는다."""
    out = _head("양도소득세 신고 부속·증빙서류 목록", enter=False)
    out += ["", "## 올리는 방법", "",
            "- 홈택스 「신고 부속·증빙서류 제출」 메뉴에서 PDF 나 이미지 파일로 올린다.",
            "- 신고서를 제출한 뒤 신고내역 조회에서 「증빙서류 제출여부」 가 N 이면 눌러 같은 첨부 화면으로 갈 수 있다"
            "(2020년 화면 기준, 지금 화면은 확인이 필요하다).",
            "- 전자신고 파일에는 매매계약서 레코드를 쓰지 않는다. 계약서 사본도 이 메뉴로 올린다.", ""]
    sheet3 = _sheet3(rv)
    for a in rv["부표1"]:
        aid = a["자산"]
        out += ["## 자산 %s" % aid, "", "%s, 양도일 %s" % (a.get("소재지"), a["양도일"]), ""]
        method = a["취득가액종류"]
        no = [0]

        def title(text):
            no[0] += 1
            return ["### %d. %s" % (no[0], text), ""]

        # 매매계약서
        out += title("매매계약서 사본")
        out.append("- [ ] 양도 매매계약서 사본 (양도일 %s, 양도가액 %s)" % (a["양도일"], _won(a["양도가액"])))
        if method == "실지거래가액":
            out.append("- [ ] 취득 매매계약서 사본 (취득일 %s, 매입가액 %s)" % (a["취득일"], _won(_purchase(sheet3.get(aid), a))))
        elif method == "환산취득가액":
            out.append("- [ ] 취득 매매계약서 사본 (취득일 %s). 있으면 올린다. 취득가액은 환산취득가액으로 신고했다" % a["취득일"])
        elif method == "매매사례가액":
            out.append("- [ ] 매매사례가액 근거 자료 (유사 매매 계약서나 실거래가 자료)")
        elif method == "감정가액":
            out.append("- [ ] 감정평가서 사본")
        else:
            out.append("- 전액 비과세 자산이라 신고값에 취득가액이 없다. 취득 매매계약서와 비과세 요건을 보이는 서류는 이 목록에 넣지 않았다")
        out.append("")
        # 필요경비 증빙
        out += title("필요경비 증빙 (증빙종류별 묶음)")
        sh = sheet3.get(aid)
        rows = [r for r in (sh["행"] if sh else []) if r["구분코드"] not in (ACQ_EXPENSE_CODE, DEPRECIATION_CODE)]
        tax_rows = [r for r in rows if r["전자코드"] == ACQ_TAX_ELECTRONIC]
        rows = [r for r in rows if r["전자코드"] != ACQ_TAX_ELECTRONIC]
        if not rows and not tax_rows:
            extra = " 기타필요경비 %s은 개산공제다." % _won(a["기타필요경비"]) if a["기타필요경비"] else ""
            out += ["증빙을 올릴 필요경비가 없다." + extra, ""]
        for name, group in _evidence_groups(rows):
            out += ["**%s**" % name] + [_expense_line(r) for r in group] + [""]
        if tax_rows:
            out += ["**취득세 납부 서류**"] + [_expense_line(dict(r, 상호=""), "납부영수증이나 납부확인서") for r in tax_rows] + [""]
        out += ["법정 증빙이 없는 지출(간이영수증만 있는 경우 포함)은 필요경비에서 뺐으므로 올리지 않는다.", ""]
        # 일시적 2주택
        temp = _temporary_two_house(result, aid)
        if temp:
            out += title("신규 주택 취득 계약서 (일시적 2주택)")
            limit = " (처분기한 %s)" % temp["처분기한"] if temp.get("처분기한") else ""
            out += ["- [ ] 신규 주택(일시적 2주택의 다른 집) 취득 계약서 사본" + limit, ""]
        # 환산이면 기준시가
        if method == "환산취득가액":
            b = a["기준시가"]
            out += title("기준시가 확인 자료 (환산취득가액)")
            out += ["- [ ] 양도 당시 기준시가 확인 자료 (합계 %s)" % _won(b["양도_합계"]),
                    "- [ ] 취득 당시 기준시가 확인 자료 (합계 %s)" % _won(b["취득_합계"]),
                    "", "토지는 개별공시지가 확인원, 주택은 개별주택가격이나 공동주택가격 확인서 같은 서류다.", ""]
    return "\n".join(out).rstrip() + "\n"


def _purchase(sheet, a):
    """매입가액(111) 행의 금액. 행이 없으면 부표1 취득가액."""
    for r in (sheet or {}).get("행") or []:
        if r["구분코드"] == ACQ_EXPENSE_CODE:
            return r["금액"]
    return a["취득가액"]
