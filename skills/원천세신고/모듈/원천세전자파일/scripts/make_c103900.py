# -*- coding: utf-8 -*-
"""원천징수이행상황신고서 → 홈택스 전자파일변환 업로드 파일(C103900) 생성기.

규격 값은 이 코드에 없다. 전부 ../references/layout_c103900.json 에서 읽는다.
규격이 개정되면 그 파일만 고친다.

입력
  --집계표  신고서 단계가 만든 원천징수집계_YYYYMM.xlsx (지급내역 시트 재집계 · 신고서 시트 머리에서 회사정보)
  --신고값  또는 신고값_YYYYMM.json ({"회사":…, "기간":…, "명세":[[코드,인원,총지급액,소득세,농특세,가산세,조정환급,납부소득세,납부농특세],…]})
  --설정    회사기초정보_<사업자번호>.xlsx (시트 「회사기초정보」, 노란 값 칸) 또는 설정_<사업자번호>.json
            홈택스ID·소재지·세무대리인·세무프로그램코드 등 신고서에 없는 것. assets/ 의 템플릿 참조
  --산출    산출 폴더. 파일명은 규격대로 {작성일자}C103900.{신고구분상세코드}

    python make_c103900.py --집계표 원천징수집계_202607.xlsx --설정 설정_1234512345.json --산출 산출/
    python make_c103900.py --신고값 신고값_202607.json --설정 설정_1234512345.json --산출 산출/

빠진 필수값이 있으면 파일을 내지 않고 '빠진 것' 목록을 찍고 종료코드 2로 멈춘다.
"""
import argparse
import json
import sys
from pathlib import Path

LAYOUT = json.loads((Path(__file__).resolve().parent.parent / "references" / "layout_c103900.json").read_text(encoding="utf-8"))
ENC = LAYOUT["인코딩"]
CRLF = b"\r\n"
REC = {k: [tuple(f[:3]) for f in v["필드"]] for k, v in LAYOUT["레코드"].items()}
REC_LEN = LAYOUT["레코드길이"]
CODES = LAYOUT["소득코드"]


def fit(value, typ, length):
    """수록요령 다.9~10: 문자는 좌측 수록·우측 공란, 수치는 0 채움, 음수는 '-' 뒤 자리."""
    if typ == "C":
        b = str(value if value is not None else "").encode(ENC)
        if len(b) > length:
            raise ValueError(f"{value!r} 가 {length}바이트를 넘습니다({len(b)}바이트)")
        return b + b" " * (length - len(b))
    v = int(value or 0)
    if typ == "N":
        if v < 0:
            raise ValueError(f"양수 항목에 음수가 왔습니다: {v}")
        return f"{v:0{length}d}".encode(ENC)
    if typ == "S":
        return (f"-{-v:0{length - 1}d}" if v < 0 else f"{v:0{length}d}").encode(ENC)
    raise ValueError(typ)


def record(kind, values):
    b = b"".join(fit(values.get(name), typ, ln) for name, typ, ln in REC[kind])
    assert len(b) == REC_LEN[kind], (kind, len(b), REC_LEN[kind])
    return b + CRLF


# ── 입력 읽기 ────────────────────────────────────────────────────────────────────

def from_workbook(xlsx):
    import openpyxl
    wb = openpyxl.load_workbook(xlsx)
    rows = []
    for r in wb["지급내역"].iter_rows(min_row=2, values_only=True):
        if r[0] and r[1]:
            rows.append((r[1], int(r[5] or 0), int(r[6] or 0), int(r[7] or 0)))
    s = wb["신고서"]

    def num(cell):
        v = s[cell].value
        return int(v) if isinstance(v, (int, float)) else 0

    hdr = {"신고구분": s["B4"].value, "귀속연월": str(s["F4"].value), "지급연월": str(s["J4"].value),
           "상호": s["B5"].value, "대표자": s["F5"].value, "사업자번호": str(s["J5"].value),
           "제출연월": str(s["F6"].value), "작성일자": str(s["J6"].value),
           "소재지": s["B6"].value or ""}
    refund = {"전월미환급세액": num("A46"), "기환급신청세액": num("B46"), "일반환급세액": num("D46"),
              "신탁재산세액": num("E46"), "그밖의환급세액_금융회사등": num("F46"),
              "그밖의환급세액_합병등": num("G46"), "환급신청액": num("K46")}
    return aggregate(rows), hdr, refund


def from_json(path):
    j = json.loads(Path(path).read_text(encoding="utf-8"))
    table = {m[0]: [int(x) for x in m[1:9]] for m in j["明細" if "明細" in j else "명세"]}
    hdr = {"신고구분": j.get("기간", {}).get("신고구분", "매월"), **j["기간"],
           "상호": j["회사"]["상호"], "대표자": j["회사"]["대표자"], "사업자번호": j["회사"]["사업자번호"]}
    refund = {k: int(v) for k, v in j.get("환급", {}).items()}
    for k in ("전월미환급세액", "기환급신청세액", "일반환급세액", "신탁재산세액",
              "그밖의환급세액_금융회사등", "그밖의환급세액_합병등", "환급신청액"):
        refund.setdefault(k, 0)
    return table, hdr, refund


def aggregate(rows):
    """코드별 [인원, 총지급액, 소득세등, 농특세, 가산세, 당월조정환급, 납부소득세, 납부농특세]."""
    t = {}
    for code, pay, tax, farm in rows:
        a = t.setdefault(code, [0] * 8)
        a[0] += 1; a[1] += pay; a[2] += tax; a[3] += farm
    for sub, parts in CODES["가감계"].items():
        if any(p in t for p in parts):
            a = [sum(t.get(p, [0] * 8)[i] for p in parts) for i in range(6)] + [0, 0]
            a[6] = a[2] + a[4] - a[5]      # ⑩ = ⑥ + ⑧ - ⑨
            a[7] = a[3]                    # ⑪
            t[sub] = a
    for c in CODES["단독"]:
        if c in t:
            t[c][6] = t[c][2] + t[c][4] - t[c][5]; t[c][7] = t[c][3]
    comps = [c for c in list(CODES["가감계"]) + CODES["단독"] if c in t]
    t["A99"] = [sum(t[c][i] for c in comps) for i in range(8)]
    return t


# ── 조립 ─────────────────────────────────────────────────────────────────────────

REQUIRED_SETTINGS = ["사용자ID", "세무프로그램코드"]


def load_settings(path):
    path = Path(path)
    if path.suffix.lower() == ".xlsx":
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from make_company_info_xlsx import read
        return read(path)
    return json.loads(path.read_text(encoding="utf-8"))


def build(table, hdr, refund, st):
    missing = [k for k in REQUIRED_SETTINGS if not st.get(k)]
    # 회사기초정보 엑셀에 식별값이 있으면 신고서와 같아야 한다. 다른 회사 신고서에 붙이는 사고를 막는다.
    for k in ("사업자번호", "상호", "대표자"):
        if st.get(k) and str(st[k]).strip() != str(hdr.get(k, "")).strip():
            missing.append(f"{k}가 다릅니다: 기초정보 {st[k]!r} · 신고서 {hdr.get(k)!r}")
    if st.get("사업장소재지") and hdr.get("소재지") and " ".join(str(st["사업장소재지"]).split()) != " ".join(str(hdr["소재지"]).split()):
        missing.append(f"사업장소재지가 다릅니다: 기초정보 {st['사업장소재지']!r} · 신고서 {hdr['소재지']!r} (한쪽을 고쳐 같게 하십시오)")
    if st.get("원천신고구분") and not str(hdr.get("신고구분", "")).startswith(str(st["원천신고구분"])[:2]):
        missing.append(f"납부 주기가 다릅니다: 기초정보 {st['원천신고구분']!r} · 신고서 {hdr.get('신고구분')!r}")
    if st.get("세무대리인신고여부", "N").upper() == "Y" and not all(st.get(k) for k in ("세무대리인사업자번호", "세무대리인성명", "세무대리인관리번호", "세무대리인전화번호")):
        missing.append("세무대리인 명의 신고인데 대리인 사업자번호·성명·관리번호·전화번호 중 빈 것이 있습니다")
    for k in ("사업자번호", "상호", "대표자", "귀속연월", "지급연월", "제출연월", "작성일자"):
        if not hdr.get(k):
            missing.append(k)
    if bool(st.get("은행코드")) != bool(st.get("계좌번호")):
        missing.append("은행코드와 계좌번호는 둘 다 있거나 둘 다 비어야 합니다")
    if missing:
        return None, None, missing

    detail = st.get("신고구분상세코드", "01")
    need_annex = [c for c in CODES["부표필요"] if c in table and any(table[c])]
    warnings = []
    if need_annex:
        warnings.append(f"부표(레코드 24) 대상 소득 {need_annex} 이 있습니다. 이 생성기는 본표만 만듭니다")
    invalid = [c for c in table if c not in CODES["유효"] or not (CODES["유효"][c][1] <= hdr["지급연월"] + "01" <= CODES["유효"][c][2])]
    if invalid:
        return None, None, [f"지급연월 {hdr['지급연월']} 에 쓸 수 없는 소득코드: {invalid}"]

    out = record("21", {
        "자료구분": "21", "서식코드": "C103900", "납세자ID": hdr["사업자번호"], "세목코드": "14",
        "신고구분코드": "01", "신고구분상세코드": detail, "신고서종류코드": "F01",
        "귀속연월": hdr["귀속연월"], "지급연월": hdr["지급연월"], "제출연월": hdr["제출연월"],
        "사용자ID": st["사용자ID"], "민원종류코드": "FF101" if detail == "02" else "FF001",
        "세무대리인사업자번호": st.get("세무대리인사업자번호", ""), "세무대리인성명": st.get("세무대리인성명", ""),
        "세무대리인관리번호": st.get("세무대리인관리번호", ""), "세무대리인전화번호": st.get("세무대리인전화번호", ""),
        "법인명": hdr["상호"], "사업장소재지": st.get("사업장소재지", ""),
        "사업장전화번호": st.get("사업장전화번호", ""), "전자메일주소": st.get("전자메일주소", ""),
        "대표자명": hdr["대표자"],
        "원천신고구분": "02" if str(hdr.get("신고구분", "")).startswith("반기") else "01",
        "연말정산여부": "Y" if set(CODES["연말정산여부Y"]) & set(table) else "N",
        "소득처분여부": st.get("소득처분여부", "N"),
        "환급신청여부": "Y" if refund["환급신청액"] and detail == "01" else "N",
        "일괄납부여부": st.get("일괄납부여부", "N"), "사업자단위과세여부": st.get("사업자단위과세여부", "N"),
        "신고서부표여부": "Y" if need_annex else "N",
        "차월이월환급세액승계명세여부": "N", "기납부세액명세서제출여부": "N",
        "은행코드": st.get("은행코드", ""), "계좌번호": st.get("계좌번호", ""),
        "작성일자": hdr["작성일자"], "세무프로그램코드": st["세무프로그램코드"],
    })
    차감 = refund["전월미환급세액"] - refund["기환급신청세액"]
    조정대상 = 차감 + sum(refund[k] for k in ("일반환급세액", "신탁재산세액", "그밖의환급세액_금융회사등", "그밖의환급세액_합병등"))
    당월조정계 = table["A99"][5]
    out += record("22", {**refund, "자료구분": "22", "서식코드": "C103900", "차감잔액": 차감,
                         "조정대상환급세액": 조정대상, "당월조정환급세액계": 당월조정계,
                         "차월이월환급세액": 조정대상 - 당월조정계,
                         "환급신청액": refund["환급신청액"] if detail == "01" else 0,
                         "승계대상합계차월이월환급세액": 0})
    for code in sorted(table):                      # 규격서는 줄 순서를 정하지 않는다. 코드 정렬순
        a = table[code]
        if code != "A99" and not any(a):            # 금액 없는 코드는 줄을 만들지 않는다 (표3 설명)
            continue
        out += record("23", {"자료구분": "23", "서식코드": "C103900", "원천징수소득코드": code,
                             "인원": a[0], "총지급액": a[1], "징수세액_소득세등": a[2], "징수세액_농특세": a[3],
                             "가산세": a[4], "당월조정환급세액": a[5], "납부세액_소득세등": a[6], "납부세액_농특세": a[7]})
    fname = LAYOUT["파일명"].format(작성일자=hdr["작성일자"], 신고구분상세코드=detail)
    return fname, out, warnings


def dump(path):
    for i, r in enumerate(Path(path).read_bytes().split(CRLF), 1):
        if r:
            print(i, len(r), r.decode(ENC))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--집계표"); ap.add_argument("--신고값"); ap.add_argument("--설정", required=False)
    ap.add_argument("--산출", default="산출"); ap.add_argument("--dump")
    a = ap.parse_args()
    if a.dump:
        dump(a.dump); return
    try:
        st = load_settings(a.설정) if a.설정 else {}
    except ValueError as e:
        print(f"회사기초정보를 읽지 못했습니다: {e}")
        sys.exit(2)
    if a.집계표:
        table, hdr, refund = from_workbook(a.집계표)
    elif a.신고값:
        table, hdr, refund = from_json(a.신고값)
    else:
        sys.exit("--집계표 또는 --신고값 이 필요합니다")
    fname, data, notes = build(table, hdr, refund, st)
    if data is None:
        print("파일을 만들지 않았습니다. 빠진 것:")
        for m in notes:
            print("  -", m)
        sys.exit(2)
    outdir = Path(a.산출); outdir.mkdir(parents=True, exist_ok=True)
    (outdir / fname).write_bytes(data)
    print(f"wrote {outdir / fname}  ({len(data)} bytes, {data.count(CRLF)} records)")
    for w in notes:
        print("주의:", w)
    for c in sorted(table):
        if any(table[c]):
            print(" ", c, table[c])


if __name__ == "__main__":
    main()
