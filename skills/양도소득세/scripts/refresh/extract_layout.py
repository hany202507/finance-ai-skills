# -*- coding: utf-8 -*-
"""양도소득세 전자신고 파일설명서 추출본에서 변환신고 파일 레이아웃(레코드 01 02 03 04 05 07)을 JSON 으로 옮긴다.

  python scripts/refresh/extract_layout.py --표 <…_표.txt> --쪽 <…_쪽별.txt> [--출력 efile/layout_c116300.json]
                                           [--규격판 efile/규격판.json] [--초안 layout_draft.json]

추출본 두 가지를 읽는다.
  _표.txt   원본 .doc 를 docx 로 바꿔 표마다 셀을 ' | ' 로 이은 글. 필드 표와 「다. 테이블별 길이」 표를 여기서 읽는다
  _쪽별.txt 원본을 PDF 로 찍어 쪽마다 뽑은 글. 필드 설명이 있는 쪽(page)을 여기서 찾는다
규격서 원본과 추출본은 저장소에 넣지 않는다. 이 JSON 은 규격에서 기계로 뽑은 것이라 저장소에 둔다.

검증
  1. 필드마다 원문 누적길이 = 앞 필드까지 길이 합 + 자기 길이
  2. 필드 길이 합 = 「다. 테이블별 길이」 표 값(규격서 p17)
2 가 어긋나면 FIXUPS 에 그 레코드의 길이 고침이 있고 그 값이 필드 합과 같을 때만 통과한다.
하나라도 어긋나면 종료코드 1, 아무 파일도 쓰지 않는다(부가세 extract_vat_layout.py 와 같은 규칙).
표 셀을 고쳐 읽은 곳과 뺀 행도 FIXUPS 에 근거와 함께 적는다. 고친 셀은 원문 값이 FIXUPS 에 적은 것과 같을 때만 고친다.
분류 칸의 값 목록을 점검내용으로 읽은 곳(종류 분류칸)과 값 목록 검사에 쓸 허용 목록(종류 허용)도 FIXUPS 에 둔다.
FIXUPS 에 없는 분류 칸 값, 적용할 필드가 없는 FIXUPS 는 오류다.
종류 정한값 은 표를 고치지 않는다. 원문만으로 정하지 못해 이 스킬이 정한 값(세무프로그램코드 9000 등)을 근거와 함께 적어 둔 것이고,
레이아웃 파일의 FIXUPS 에 그대로 실려 신고_확인.md 의 「규격서 미확인 칸」 문장이 된다.
--초안 을 주면 레코드별 필드 수·길이를 그 초안과 대조해 다른 곳을 표준오류에 찍는다(종료코드에는 영향 없음).
"""
import argparse
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(os.path.dirname(HERE))

RECORDS = ("01", "02", "03", "04", "05", "07")
# 「다. 테이블별 길이」 표(p17)의 File 칸
FILE_NAMES = {
    "01": "양도소득세과세표준신고서 HEADER",
    "02": "양도소득세과세표준신고서 기본사항",
    "03": "양도소득과세표준신고서 세율별내역",
    "04": "양도소득과세표준신고서 양수인내역",
    "05": "양도소득금액 계산명세",
    "07": "취득가액및필요경비계산상세명세",
}
# 수록순서(p104), 레이아웃 쪽, 항목 설명 쪽
META = {
    "01": {"이름": "HEADER", "원문이름": "양도소득세과세표준신고서 HEADER", "건수": "One", "정렬키": "", "레이아웃쪽": [25, 25], "설명쪽": [25, 28]},
    "02": {"이름": "기본사항", "원문이름": "양도소득세과세표준신고서 기본사항 테이블", "건수": "One", "정렬키": "", "레이아웃쪽": [29, 29], "설명쪽": [29, 30]},
    "03": {"이름": "세율별내역", "원문이름": "양도소득과세표준신고서 세율별내역 테이블", "건수": "Multi", "정렬키": "국내외분/세율구분", "레이아웃쪽": [31, 31], "설명쪽": [32, 43]},
    "04": {"이름": "양수인내역", "원문이름": "양도소득과세표준신고서 양수인내역 테이블", "건수": "Multi", "정렬키": "일련번호", "레이아웃쪽": [44, 44], "설명쪽": [44, 44]},
    "05": {"이름": "양도소득금액계산명세", "원문이름": "양도소득금액계산명세 테이블", "건수": "Multi", "정렬키": "일련번호", "레이아웃쪽": [45, 46], "설명쪽": [47, 53]},
    "07": {"이름": "취득가액및필요경비계산상세명세", "원문이름": "취득가액및필요경비계산상세명세 테이블", "건수": "Multi", "정렬키": "일련번호/구분코드/구분코드별_일련번호", "레이아웃쪽": [59, 59], "설명쪽": [59, 61]},
}

FIXUPS = [
    {"레코드": "01", "종류": "길이", "값": 350,
     "내용": "길이 표 300, 필드 표 누적 350. 350 을 쓴다",
     "근거": "p17 길이 표는 300, p25 필드 표 누적은 350 이다. p2 변경내역(2023.4.27)에 세무대리인성명·세무대리인생년월일을 넣으며 "
             "기존 레이아웃 길이를 조정했다고 적혀 있다. 300 으로 맞추면 공란(47)이 -3 이 되어 맞출 수 없다",
     "확인": "홈택스 형식검증"},
    {"레코드": "01", "종류": "셀", "no": 9, "name": "신고구분상세코드", "칸": "check", "원문": "01,03, 3, 35, Not null", "값": "01,03",
     "내용": "점검내용을 01,03 으로 읽는다",
     "근거": "p25 PDF 표의 9번 행에는 「01,03」 만 있다. docx 로 바꾼 표 행에만 「3 | 35 | Not null」 칸이 더 붙어 있다",
     "확인": "원문 대조"},
    {"레코드": "02", "종류": "삭제행", "name": "도로명_법정동코드(행안부)",
     "내용": "번호 칸이 「삭제」인 행(CHAR 10, 누적 217)은 필드에 넣지 않는다",
     "근거": "p29 표에서 번호가 17(거주지국명) 다음 18(도로명_도로명코드)로 이어지고, 18번 누적 219 = 207 + 12 다. "
             "넣으면 필드 합이 410 이 되어 길이 표 400 과 어긋난다",
     "확인": "원문 대조"},
    {"레코드": "05", "종류": "분류칸", "no": 4, "name": "과세구분", "원문": "01,05",
     "내용": "분류 칸의 값 목록 「01,05」 를 점검내용으로 읽는다(점검내용 칸은 비어 있다)",
     "근거": "p45 표 4번 행: 점검내용 칸 공란, 분류 칸 「01,05」. 01,05 는 분류 이름이 아니라 값 목록이다",
     "확인": "원문 대조"},
    {"레코드": "05", "종류": "허용", "no": 4, "name": "과세구분", "값": ["01", "05", "ZZ"],
     "내용": "점검내용은 01,05 그대로 두고, 필드에 허용 목록 01·05·ZZ 를 둔다. 값 목록으로 검사하는 쪽은 허용 을 쓴다",
     "근거": "p45 필드 표 값 목록은 「01,05」, p47 4번 설명은 「'01'비과세, '05'과세제외 'ZZ'해당없음」. 과세 자산은 ZZ 다(codes 과세구분.해당없음)",
     "확인": "홈택스 형식검증"},
    {"레코드": "05", "종류": "셀", "no": 5, "name": "국내외분(소재지)", "칸": "check", "원문": "1, 1,2", "값": "1,2",
     "내용": "점검내용을 1,2 로 읽는다(분류 칸의 값 목록 「1,2」 를 점검내용으로 옮긴 것도 이 고침에 든다)",
     "근거": "p45 표 5번 행은 점검내용 칸 「1」, 분류 칸 「1,2」 다. 같은 표 4번(과세구분)도 값 목록 「01,05」 가 분류 칸에 있다. "
             "p47 세율구분 표는 국내 1·국외 2, 같은 쪽 5번 설명은 국내 1·국외 9 라 국외 코드는 정하지 못했다(국외는 다루지 않음)",
     "확인": "원문 대조"},
    # 종류 정한값: 표를 고쳐 읽은 곳이 아니라, 원문만으로 정하지 못해 이 스킬이 정한 값이다. 레이아웃 필드에는 손대지 않는다.
    # 홈택스 형식검증으로 확정할 칸이라 신고_확인.md 의 「규격서 미확인 칸」이 「칸이름: 내용」으로 싣는다(make_return._unconfirmed).
    # 칸번호 는 가리키는 칸 번호 목록이고 레이아웃에 있는 번호인지는 시험이 본다
    {"레코드": "01", "종류": "정한값", "칸이름": "01-23 세무프로그램코드", "칸번호": [23],
     "내용": "규격서 p27~28 표에 없는 프로그램이라 9000(기타)을 썼다",
     "근거": "p27~28 세무프로그램코드 표에 이 프로그램이 없다. 표의 「기타」 코드가 9000 이다(codes 세무프로그램코드.기타)",
     "확인": "홈택스 형식검증"},
    {"레코드": "01", "종류": "정한값", "칸이름": "01-18~22·26·27 세무대리인 칸", "칸번호": [18, 19, 20, 21, 22, 26, 27],
     "내용": "본인 신고라 공란으로 두었다",
     "근거": "p25 필드 표에서 세무대리인 칸은 모두 Null 허용이다. 본인 신고에서 비워도 되는지는 원문에 문장이 없다",
     "확인": "홈택스 형식검증"},
    {"레코드": "03", "종류": "정한값", "칸이름": "03-31 주민세_세율", "칸번호": [30, 31, 32, 33],
     "내용": "합계 행만 10.00, 나머지 행은 0. 03-30·32·33 주민세 금액 칸은 0 이다",
     "근거": "p43 31번 「10% (01000) 합계(국내외분:Z, 세율구분:00) 이외 항목에는 '0'으로 채움」. 주민세 금액 칸은 2020-01-01 이후 "
             "국세 파일에 적지 않는 지방소득세 란이라 0 으로 두었다(p32)",
     "확인": "홈택스 형식검증"},
    {"레코드": "05", "종류": "정한값", "칸이름": "05-62 장기보유특별공제적용구분코드", "칸번호": [62],
     "내용": "규격서에 값 설명이 없어 ZZ(해당없음)를 넣는다",
     "근거": "p53 62번 칸에 값 목록이나 설명이 없다. 이 스킬은 코드표의 기본값 ZZ 를 쓴다(codes 장기보유특별공제적용구분코드.기본). "
             "같은 쪽 보유거주기간코드(64·65번)의 ZZ 가 해당없음이라 맞춰 정했다",
     "확인": "홈택스 형식검증"},
]

# 원문 분류 칸 중 날짜 형식 이름은 DATE 로 모은다. 원문 값은 필드의 분류원문 에 남긴다
CLASS_KNOWN = {"FIX", "LIST", "CODE", "AMT", "AMT+", "RATE", "SEQ", "DATE", "ID", "USERID", "SPACE"}
CLASS_DATE = {"YYYYMM", "YYYYMMDD", "YYYY MMDD"}
TYPES = {"CHAR": "C", "VARCHAR": "C", "VARCHAR2": "C", "NUMBER": "N", "NUMERIC": "N"}

# 설명 쪽을 이름으로 찾지 못하는 필드(설명 문장의 이름이나 번호가 표와 다름)
PAGE_OVERRIDE = {
    ("01", 27): 28,   # 27.세무대리인생년월일: p27 은 22번 아래 ※ 줄, 설명은 p28
    ("03", 14): 41,   # 설명은 「14.원천신고납부세액공제」
    ("04", 6): 44, ("04", 7): 44,   # 설명은 「6. 양수인주민등록번호」「7. 양수인성명」
    ("05", 6): 47,    # 설명 번호가 「5. 세율구분」
    ("05", 60): 53,   # 설명은 「60. 소득금액감면대상」
}
PREFIX_STRIP = r"^(거래일자|거래자산면적|거래금액|양수인|소재지|주소|도로명|농어촌특별세|주민세)_"


class LayoutError(Exception):
    pass


def sha256(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def read_tables(text):
    out = []
    for m in re.finditer(r"##### TABLE (\d+)  \(앞 문단: (.*?)\)\n(.*?)(?=\n##### TABLE|\Z)", text, re.S):
        rows = [r for r in m.group(3).strip().split("\n") if r.strip()]
        out.append((int(m.group(1)), rows))
    return out


def read_pages(text):
    pages = {}
    for m in re.finditer(r"===== PAGE (\d+) =====\n(.*?)(?====== PAGE|\Z)", text, re.S):
        pages[int(m.group(1))] = norm_page(m.group(2))
    return pages


def norm_page(s):
    return re.sub(r"[\s　'‘’“”\"]", "", s)


def cells(row):
    return [x.strip() for x in row.split(" | ")]


def length_table(tables):
    for no, rows in tables:
        if rows and [re.sub(r"\s+", "", c) for c in cells(rows[0])][:3] == ["서식명", "File", "길이"]:
            out = {}
            for r in rows[1:]:
                c = cells(r)
                if len(c) >= 3:
                    out[re.sub(r"\s+", " ", c[1]).strip()] = c[2]
            return out
    raise LayoutError("「다. 테이블별 길이」 표(서식명 | File | 길이)를 찾지 못했다")


def parse_row(row, rec, tno):
    c = cells(row)
    if len(c) < 6:
        raise LayoutError("TABLE %d 행의 칸이 모자란다: %r" % (tno, row))
    numcell, name, typ, ln, acc, rest = c[0], c[1], c[2], c[3], c[4], c[5:]
    note = rest[0] if rest else ""
    R = rest[1:]
    item = ""
    m = re.search(r"\s*\((\d+(?:,\d+)?)\)\s*$", note)
    if m and "null" in note.lower():
        item, note = "(%s)" % m.group(1), note[:m.start()].strip()
    cls = ""
    nz = [i for i, x in enumerate(R) if x]
    if nz and (R[nz[-1]] in CLASS_KNOWN or R[nz[-1]] in CLASS_DATE):
        cls = R[nz[-1]]
        R = R[:nz[-1]] + R[nz[-1] + 1:]
    chk = []
    for x in R:
        if re.fullmatch(r"\(\d+(?:,\d+)?\)", x):
            item = x
        elif x:
            chk.append(x)
    t = TYPES.get(re.sub(r"\s+", "", typ).upper())
    if t is None:
        raise LayoutError("%s %s: 타입 %r 를 모른다" % (rec, name, typ))
    lm = re.fullmatch(r"(\d+)(?:,(\d+))?", re.sub(r"\s+", "", ln))
    if not lm or not re.fullmatch(r"\d+", acc):
        raise LayoutError("%s %s: 길이 %r 누적 %r 를 못 읽는다" % (rec, name, ln, acc))
    # 마지막 칸(분류)에 분류 이름이 아닌 값이 있으면 위에서 점검내용으로 옮겼다. FIXUPS 에 있어야 받는다
    last = c[-1]
    moved = last if last and last not in CLASS_KNOWN and last not in CLASS_DATE else ""
    return {"삭제": numcell == "삭제", "원문명": name, "type": t, "len": int(lm.group(1)), "dec": int(lm.group(2) or 0),
            "누적": int(acc), "비고": note, "서식항목": item, "check": ", ".join(chk), "class": cls, "분류칸값": moved}


def field_tables(tables):
    found = {}
    for no, rows in tables:
        if not rows or [re.sub(r"\s+", "", c) for c in cells(rows[0])][:3] != ["번호", "한글명", "TYPE"] or len(rows) < 3:
            continue
        a, b = cells(rows[1]), cells(rows[2])
        if len(a) < 7 or re.sub(r"\s+", "", a[1]) != "자료구분" or re.sub(r"\s+", "", b[1]) != "서식코드":
            continue
        kind = next((x for x in a[5:] if re.fullmatch(r"\d\d", x)), None)
        if kind in RECORDS:
            if kind in found:
                raise LayoutError("자료구분 %s 필드 표가 둘이다(TABLE %d, %d)" % (kind, found[kind][0], no))
            found[kind] = (no, rows[1:])
    missing = [k for k in RECORDS if k not in found]
    if missing:
        raise LayoutError("필드 표를 찾지 못한 레코드: %s" % ", ".join(missing))
    return found


def field_page(rec, no, name, pages):
    if (rec, no) in PAGE_OVERRIDE:
        return PAGE_OVERRIDE[(rec, no)]
    lo, hi = META[rec]["설명쪽"]
    base = re.sub(PREFIX_STRIP, "", name)
    for c in ("%d.%s" % (no, name), "%d.%s" % (no, base), "%d.%s" % (no, name[:4]), "%d.%s" % (no, base[:3])):
        n = norm_page(c)
        hits = [p for p in range(lo, hi + 1) if n in pages.get(p, "")]
        if hits:
            return hits[0]
    lo, hi = META[rec]["레이아웃쪽"]   # 설명 문장이 없으면 레이아웃 표에서 그 행이 있는 쪽
    n = norm_page("%d%s" % (no, name))
    return next((p for p in range(lo, hi + 1) if n in pages.get(p, "")), lo)


def normalize_name(s):
    return re.sub(r"\s+", "", s).replace("–", "-")


def default_of(note):
    m = re.search(r"default\s*['‘’]?([^'‘’\s]+)", note, re.I)
    return m.group(1) if m else None


def build_record(rec, tno, rows, lengths, pages, errors):
    fix_cells = {(x["no"], x["칸"]): x for x in FIXUPS if x["레코드"] == rec and x["종류"] == "셀"}
    fix_moved = {x["no"]: x for x in FIXUPS if x["레코드"] == rec and x["종류"] == "분류칸"}
    fix_allow = {x["no"]: x for x in FIXUPS if x["레코드"] == rec and x["종류"] == "허용"}
    cell_nos = {no for no, _ in fix_cells}
    dropped_names = {normalize_name(x["name"]) for x in FIXUPS if x["레코드"] == rec and x["종류"] == "삭제행"}
    fields, dropped, pos = [], [], 0
    for row in rows:
        raw = parse_row(row, rec, tno)
        if raw["삭제"]:
            if normalize_name(raw["원문명"]) not in dropped_names:
                errors.append("%s: 번호 칸이 「삭제」인 행 %s 가 FIXUPS 에 없다" % (rec, raw["원문명"]))
            dropped.append({"name": normalize_name(raw["원문명"]), "type": raw["type"], "len": raw["len"], "원문누적": raw["누적"], "비고": raw["비고"]})
            continue
        no = len(fields) + 1
        start = pos + 1
        pos += raw["len"]
        if raw["누적"] != pos:
            errors.append("%s %d %s: 원문 누적 %d, 길이 합 %d" % (rec, no, raw["원문명"], raw["누적"], pos))
        name = normalize_name(raw["원문명"])
        f = {"no": no, "name": name, "type": raw["type"], "len": raw["len"], "dec": raw["dec"],
             "notnull": bool(re.search(r"not\s*null", raw["비고"], re.I))}
        d = default_of(raw["비고"])
        if d is not None:
            f["default"] = d
        check = raw["check"]
        fx = fix_cells.pop((no, "check"), None)
        if fx:
            if fx["name"] != name or check not in (fx["원문"], fx["값"]):
                errors.append("%s %d: FIXUPS 셀 고침의 원문(%s %r)이 지금 표(%s %r)와 다르다" % (rec, no, fx["name"], fx["원문"], name, check))
            check = fx["값"]
        if raw["분류칸값"]:
            mv = fix_moved.pop(no, None)
            if mv:
                if mv["name"] != name or mv["원문"] != raw["분류칸값"]:
                    errors.append("%s %d: FIXUPS 분류칸 원문(%s %r)이 지금 표(%s %r)와 다르다" % (rec, no, mv["name"], mv["원문"], name, raw["분류칸값"]))
            elif no not in cell_nos:
                errors.append("%s %d %s: 분류 칸 값 %r 를 점검내용으로 읽었다(FIXUPS 에 없음)" % (rec, no, name, raw["분류칸값"]))
        f["check"] = check
        al = fix_allow.pop(no, None)
        if al:
            if al["name"] != name:
                errors.append("%s %d: FIXUPS 허용의 필드(%s)가 지금 표(%s)와 다르다" % (rec, no, al["name"], name))
            f["허용"] = list(al["값"])
        cls = raw["class"]
        f["class"] = "DATE" if cls in CLASS_DATE else cls
        f["start"], f["end"] = start, pos
        f["page"] = field_page(rec, no, raw["원문명"], pages)
        if raw["서식항목"]:
            f["서식항목"] = raw["서식항목"]
        f["비고"] = raw["비고"]
        if name != raw["원문명"]:
            f["원문명"] = raw["원문명"]
        if cls in CLASS_DATE:
            f["분류원문"] = cls
        fields.append(f)
    for (no, _), fx in fix_cells.items():
        errors.append("%s %d %s: FIXUPS 셀 고침을 적용할 필드가 없다" % (rec, no, fx["name"]))
    for no, fx in list(fix_moved.items()) + list(fix_allow.items()):
        errors.append("%s %d %s: FIXUPS %s 을 적용할 필드가 없다" % (rec, no, fx["name"], fx["종류"]))
    for n in sorted(dropped_names - {d["name"] for d in dropped}):
        errors.append("%s: FIXUPS 삭제행 %s 가 표에 없다" % (rec, n))
    total = sum(f["len"] for f in fields)
    raw_len = lengths.get(FILE_NAMES[rec])
    if raw_len is None or not str(raw_len).isdigit():
        errors.append("%s: 길이 표에서 %s 의 길이를 찾지 못했다" % (rec, FILE_NAMES[rec]))
        table_len = None
    else:
        table_len = int(raw_len)
        if total != table_len:
            fx = [x for x in FIXUPS if x["레코드"] == rec and x["종류"] == "길이"]
            if not fx:
                errors.append("%s: 필드 길이 합 %d, 길이 표 %d (FIXUPS 에 없음)" % (rec, total, table_len))
            elif fx[0]["값"] != total:      # 길이 고침은 있는데 그 값도 필드 합과 다르다
                errors.append("%s: 필드 길이 합 %d, 길이 표 %d (FIXUPS 길이 고침 %s 과도 다름)" % (rec, total, table_len, fx[0]["값"]))
    m = META[rec]
    r = {"이름": m["이름"], "원문이름": m["원문이름"], "서식코드": fields[1]["check"] if len(fields) > 1 else "",
         "길이": total, "길이표": table_len, "건수": m["건수"], "정렬키": m["정렬키"],
         "레이아웃쪽": m["레이아웃쪽"], "설명쪽": m["설명쪽"], "필드": fields}
    if dropped:
        r["삭제행"] = dropped
    return r


def build(table_text, page_text, spec):
    errors = []
    first = table_text.split("\n", 1)[0]
    stem = os.path.splitext(spec.get("원본", ""))[0]
    if not stem or stem not in first:
        errors.append("_표.txt 첫 줄의 원본 이름이 규격판(%s)과 다르다: %s" % (spec.get("원본"), first[:120]))
    tables = read_tables(table_text)
    pages = read_pages(page_text)
    lengths = length_table(tables)
    found = field_tables(tables)
    records = {}
    for rec in RECORDS:
        tno, rows = found[rec]
        records[rec] = build_record(rec, tno, rows, lengths, pages, errors)
        if records[rec]["필드"] and records[rec]["필드"][0]["check"] != rec:
            errors.append("%s: 자료구분 점검값이 %r" % (rec, records[rec]["필드"][0]["check"]))
        names = [f["name"] for f in records[rec]["필드"]]
        dup = sorted({n for n in names if names.count(n) > 1})
        if dup:
            errors.append("%s: 같은 이름의 필드 %s" % (rec, ", ".join(dup)))
    return records, errors


def compare_draft(records, draft_path):
    with open(draft_path, encoding="utf-8") as f:
        draft = json.load(f)
    diffs = []
    for rec, r in records.items():
        d = draft.get("records", {}).get(rec)
        if d is None:
            diffs.append("%s: 초안에 없음" % rec)
            continue
        n, total = len(r["필드"]), r["길이"]
        if (d.get("필드수"), d.get("필드길이합")) != (n, total):
            diffs.append("%s: 필드 수·길이 추출 %d·%d, 초안 %s·%s" % (rec, n, total, d.get("필드수"), d.get("필드길이합")))
    return diffs


def dump(doc):
    """레코드의 필드는 한 줄에 하나씩 쓴다(검토할 때 줄 단위로 비교하기 쉽게)."""
    head = {k: v for k, v in doc.items() if k != "레코드"}
    lines = ["{"]
    lines.append(' "규격": %s,' % json.dumps(head["규격"], ensure_ascii=False))
    lines.append(' "추출본": %s,' % json.dumps(head["추출본"], ensure_ascii=False))
    lines.append(' "필드키": %s,' % json.dumps(head["필드키"], ensure_ascii=False))
    lines.append(' "레코드": {')
    recs = list(doc["레코드"].items())
    for i, (rec, r) in enumerate(recs):
        lines.append('  "%s": {' % rec)
        items = [(k, v) for k, v in r.items() if k != "필드"]
        for k, v in items:
            lines.append('   "%s": %s,' % (k, json.dumps(v, ensure_ascii=False)))
        lines.append('   "필드": [')
        for j, f in enumerate(r["필드"]):
            lines.append("    %s%s" % (json.dumps(f, ensure_ascii=False), "," if j < len(r["필드"]) - 1 else ""))
        lines.append("   ]")
        lines.append("  }%s" % ("," if i < len(recs) - 1 else ""))
    lines.append(" },")
    lines.append(' "순서": %s,' % json.dumps(doc["순서"], ensure_ascii=False))
    lines.append(' "FIXUPS": [')
    for j, x in enumerate(doc["FIXUPS"]):
        lines.append("  %s%s" % (json.dumps(x, ensure_ascii=False), "," if j < len(doc["FIXUPS"]) - 1 else ""))
    lines.append(" ]")
    lines.append("}")
    return "\n".join(lines) + "\n"


FIELD_KEYS = {
    "no": "레코드 안 순번(원문 번호와 같음. 삭제 행은 세지 않음)",
    "name": "원문 한글명에서 공백을 빼고 반각 대시(-)로 맞춘 이름. 바꾼 경우 원문명 에 원문",
    "type": "C 문자(CHAR) 또는 N 수치(NUMBER)",
    "len": "바이트. NUMBER(m,n) 은 m, 소수점 문자 없음",
    "dec": "소수 자리 n",
    "notnull": "원문 비고가 Not Null 이면 true",
    "default": "원문 비고의 default 값(있을 때만)",
    "check": "원문 점검내용(FIX 면 고정값)",
    "허용": "값 목록 검사에 쓸 목록(있을 때만). check 와 설명이 다른 칸에 FIXUPS 근거로 둔다. 있으면 check 대신 이것으로 검사한다",
    "class": "원문 분류. YYYYMM·YYYYMMDD 는 DATE 로 모으고 분류원문 에 원문",
    "start": "1 부터 센 시작 바이트", "end": "끝 바이트",
    "page": "항목 설명이 있는 규격서 쪽(설명이 없으면 레이아웃 쪽)",
    "서식항목": "원문 비고의 (n), 신고서식 항목번호",
    "비고": "원문 비고 칸",
}


def main(argv=None):
    ap = argparse.ArgumentParser(description="양도소득세 전자신고 레이아웃 추출(C116300 레코드 01 02 03 04 05 07)")
    ap.add_argument("--표", required=True, help="규격서 추출본 _표.txt")
    ap.add_argument("--쪽", required=True, help="규격서 추출본 _쪽별.txt")
    ap.add_argument("--출력", default=os.path.join(SKILL, "efile", "layout_c116300.json"))
    ap.add_argument("--규격판", default=os.path.join(SKILL, "efile", "규격판.json"))
    ap.add_argument("--초안", default=None, help="대조할 layout_draft.json(선택)")
    a = ap.parse_args(argv)
    with open(a.표, encoding="utf-8") as f:
        table_text = f.read()
    with open(a.쪽, encoding="utf-8") as f:
        page_text = f.read()
    with open(a.규격판, encoding="utf-8") as f:
        spec = json.load(f)
    try:
        records, errors = build(table_text, page_text, spec)
    except LayoutError as e:
        records, errors = None, [str(e)]
    if errors:
        for e in errors:
            print("오류: " + e, file=sys.stderr)
        print("레이아웃을 쓰지 않았다(오류 %d건)" % len(errors), file=sys.stderr)
        return 1
    if a.초안:
        for d in compare_draft(records, a.초안):
            print("초안과 다름: " + d, file=sys.stderr)
    doc = {
        "규격": {"판": spec["판"], "게시": spec["게시"], "sha256": spec["sha256"], "인코딩": "cp949", "줄끝": "\r\n"},
        "추출본": {"표": {"이름": os.path.basename(a.표), "sha256": sha256(a.표)},
                   "쪽": {"이름": os.path.basename(a.쪽), "sha256": sha256(a.쪽)}},
        "필드키": FIELD_KEYS,
        "레코드": records,
        "순서": list(RECORDS),
        "FIXUPS": FIXUPS,
    }
    out_dir = os.path.dirname(os.path.abspath(a.출력))
    os.makedirs(out_dir, exist_ok=True)
    tmp = a.출력 + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(dump(doc))
    os.replace(tmp, a.출력)
    for rec, r in records.items():
        print("%s %s 필드 %d 길이 %d 길이표 %s" % (rec, r["이름"], len(r["필드"]), r["길이"], r["길이표"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
