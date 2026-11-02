# -*- coding: utf-8 -*-
"""C103900 업로드 파일 형식검증. 규격서에서 읽은 것만 본다. 생성기 코드를 부르지 않는다.

    python validate_c103900.py <파일> [--신고값 신고값_YYYYMM.json]

하나라도 실패하면 종료코드 1. 고정길이 파일은 한 칸만 밀려도 홈택스에서 막히므로 눈으로 보지 않고 여기로 본다.
"""
import argparse
import json
import re
import sys
from pathlib import Path

LAYOUT = json.loads((Path(__file__).resolve().parent.parent / "references" / "layout_c103900.json").read_text(encoding="utf-8"))
ENC = LAYOUT["인코딩"]
CRLF = b"\r\n"
REC_LEN = LAYOUT["레코드길이"]
CODES = LAYOUT["소득코드"]
FIELDS = {k: [tuple(f[:3]) for f in v["필드"]] for k, v in LAYOUT["레코드"].items()}


def slice_fields(rec, kind):
    out, pos = {}, 0
    for name, typ, ln in FIELDS[kind]:
        out[name] = rec[pos:pos + ln]
        pos += ln
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("파일"); ap.add_argument("--신고값")
    a = ap.parse_args()
    p = Path(a.파일)
    b = p.read_bytes()
    results = []

    def check(name, ok, note=""):
        results.append((name, bool(ok), note))

    check("C1 파일명이 YYYYMMDDC103900.NN 꼴", re.fullmatch(r"\d{8}C103900\.(01|02|03)", p.name), p.name)
    try:
        b.decode(ENC); check("C2 KSC-5601 완성형(cp949)으로 읽힘", True, f"{len(b)}바이트")
    except UnicodeDecodeError as e:
        check("C2 KSC-5601 완성형(cp949)으로 읽힘", False, str(e))
    check("C3 마지막 레코드 뒤에도 CR/LF", b.endswith(CRLF))
    check("C3b 파일 안에 CR/LF 아닌 홀로 된 LF·CR 없음", b.replace(CRLF, b"").count(b"\n") == 0 and b.replace(CRLF, b"").count(b"\r") == 0)

    recs = [r for r in b.split(CRLF) if r]
    bad = []
    for i, r in enumerate(recs, 1):
        kind = r[:2].decode(ENC, "replace")
        if r[2:9] != b"C103900" or kind not in REC_LEN:
            bad.append(f"{i}번째 자료구분 {kind}/{r[2:9]!r} 는 이 신고서 것이 아님")
        elif len(r) != REC_LEN[kind]:
            bad.append(f"{i}번째 {kind} 길이 {len(r)} (규격 {REC_LEN[kind]})")
    check("C4 자료구분별 레코드 길이 21=400·22=200·23=150", not bad, "; ".join(bad) or f"{len(recs)}개")

    h = slice_fields(recs[0], "21") if recs and recs[0][:2] == b"21" else None
    check("C5 첫 레코드가 21C103900, 22는 한 줄, 그 뒤 23", h is not None and sum(r[:2] == b"22" for r in recs) == 1
          and all(r[:2] == b"23" for r in recs[2:]))
    if h is None:
        report(results); return
    d = {k: v.decode(ENC, "replace") for k, v in h.items()}
    check("C6 사업자등록번호 숫자 10자리(하이픈 없이)", re.fullmatch(r"\d{10} {3}", d["납세자ID"]), d["납세자ID"].strip())
    check("C6b 고정값 세목코드 14·신고구분 01·종류 F01·민원코드 FF001/FF101",
          d["세목코드"] == "14" and d["신고구분코드"] == "01" and d["신고서종류코드"] == "F01"
          and d["민원종류코드"] in ("FF001", "FF101")
          and (d["민원종류코드"] == "FF101") == (d["신고구분상세코드"] == "02"))
    check("C6c 필수 문자칸(사용자ID·법인명·대표자명·작성일자·세무프로그램코드) 비어 있지 않음",
          all(d[k].strip() for k in ("사용자ID", "법인명", "대표자명", "작성일자", "세무프로그램코드")))
    check("C6d Y/N 칸 아홉이 Y 또는 N", all(d[k] in "YN" for k in
          ("연말정산여부", "소득처분여부", "환급신청여부", "일괄납부여부", "사업자단위과세여부",
           "신고서부표여부", "차월이월환급세액승계명세여부", "기납부세액명세서제출여부")))
    check("C6e 은행코드·계좌번호는 둘 다 있거나 둘 다 공란", bool(d["은행코드"].strip()) == bool(d["계좌번호"].strip()))
    귀, 지, 제 = d["귀속연월"], d["지급연월"], d["제출연월"]
    ok7 = False
    if re.fullmatch(r"\d{6}", 제):
        y, m = int(제[:4]), int(제[4:])
        ok7 = 지 == (f"{y}{m - 1:02d}" if m > 1 else f"{y - 1}12")
    if d["원천신고구분"] == "01" and d["신고구분상세코드"] == "01":
        check("C7 매월 정기신고: 지급연월 = 제출연월 - 1", ok7, f"귀속 {귀} 지급 {지} 제출 {제}")
    else:
        check("C7 (매월 정기 아님 · 연월 관계 생략)", True, f"원천신고구분 {d['원천신고구분']} 상세 {d['신고구분상세코드']}")
    check("C8 지급연월 >= 귀속연월, 같은 연도", 지 >= 귀 and 지[:4] == 귀[:4], f"귀속 {귀} 지급 {지}")
    check("C8b 작성일자 = 파일명 앞 8자리", d["작성일자"] == p.name[:8] and d["신고구분상세코드"] == p.name[-2:])

    table, fmt_bad, order = {}, [], []
    for i, r in enumerate(recs, 1):
        if r[:2] != b"23":
            continue
        f = slice_fields(r, "23")
        code = f["원천징수소득코드"].decode(ENC, "replace")
        order.append(code)
        vals = {}
        for name, typ, ln in FIELDS["23"][3:11]:
            x = f[name]
            pat = rb"-\d{14}|\d{15}" if typ == "S" else rb"\d{15}"
            if not re.fullmatch(pat, x):
                fmt_bad.append(f"{code} {name} {x!r}")
            vals[name] = int(x) if re.fullmatch(rb"-?\d+", x) else 0
        if f["공란"].strip():
            fmt_bad.append(f"{code} 공란에 값")
        neg_ok_tax = code in CODES["소득세음수가능"]
        neg_ok_farm = code in CODES["농특세음수가능"]
        if vals["징수세액_소득세등"] < 0 and not neg_ok_tax:
            fmt_bad.append(f"{code} 소득세등 음수 불가")
        if vals["징수세액_농특세"] < 0 and not neg_ok_farm:
            fmt_bad.append(f"{code} 농특세 음수 불가")
        if vals["당월조정환급세액"] < 0 and d["신고구분상세코드"] != "02":
            fmt_bad.append(f"{code} 당월조정환급세액 음수는 수정신고만")
        if code not in CODES["유효"]:
            fmt_bad.append(f"{code} 코드표에 없음")
        elif not (CODES["유효"][code][1] <= 지 + "01" <= CODES["유효"][code][2]):
            fmt_bad.append(f"{code} 는 지급연월 {지} 에 적용 종료/미시행")
        if not any(vals.values()):
            fmt_bad.append(f"{code} 0으로만 채운 줄(금지)")
        table[code] = vals
    check("C9 23 레코드 금액칸 여덟: 15자리 0채움, 부호는 허용 칸에만, 유효 코드, 0줄 없음", not fmt_bad, "; ".join(fmt_bad) or ", ".join(order))

    inv = []
    for code, v in table.items():
        n, pay = v["인원"], v["총지급액"]
        if (n == 0 and pay > 0) or (n > 0 and pay <= 0) or (n > 0 and n >= pay) or n >= 500000 or pay >= 10_000_000_000_000 or (n and pay // n >= 100_000_000_000):
            inv.append(f"{code} 인원 {n} 총지급액 {pay}")
    check("C9b 인원·총지급액 오류검증표(표3 #4·5)", not inv, "; ".join(inv))

    wrong = []
    for sub, parts in CODES["가감계"].items():
        if sub in table:
            for k in ("인원", "총지급액", "징수세액_소득세등", "징수세액_농특세", "가산세"):
                if table[sub][k] != sum(table.get(p_, {}).get(k, 0) for p_ in parts):
                    wrong.append(f"{sub}.{k}")
    check("C10 가감계 = 구성코드 합(인원·총지급액·소득세·농특세·가산세)", not wrong, "; ".join(wrong))

    comps = [c for c in list(CODES["가감계"]) + CODES["단독"] if c in table]
    if "A99" in table:
        w99 = [k for k in ("인원", "총지급액", "징수세액_소득세등", "징수세액_농특세", "가산세", "당월조정환급세액", "납부세액_소득세등", "납부세액_농특세")
               if table["A99"][k] != sum(table[c][k] for c in comps)]
        check("C11 A99 총합계 = 가감계 + 단독코드 (여덟 칸 전부)", not w99, "; ".join(w99))
        check("C11b 가감계·단독 줄의 납부세액 = 소득세등 + 가산세 - 당월조정환급", all(
            table[c]["납부세액_소득세등"] == table[c]["징수세액_소득세등"] + table[c]["가산세"] - table[c]["당월조정환급세액"] for c in comps))
    else:
        check("C11 A99 총합계 = 가감계 + 단독코드", False, "A99 줄 없음")

    r22 = slice_fields(next(r for r in recs if r[:2] == b"22"), "22")
    v22 = {k: int(v) for k, v in r22.items() if k not in ("자료구분", "서식코드", "공란")}
    check("C12 22 레코드: 차감잔액=⑫-⑬, 조정대상=⑭+⑮+⑯+⑰, 차월이월=⑱-⑲, ⑲=A99 ⑨",
          v22["차감잔액"] == v22["전월미환급세액"] - v22["기환급신청세액"]
          and v22["조정대상환급세액"] == v22["차감잔액"] + v22["일반환급세액"] + v22["신탁재산세액"] + v22["그밖의환급세액_금융회사등"] + v22["그밖의환급세액_합병등"]
          and v22["차월이월환급세액"] == v22["조정대상환급세액"] - v22["당월조정환급세액계"]
          and ("A99" not in table or v22["당월조정환급세액계"] == table["A99"]["당월조정환급세액"])
          and (d["환급신청여부"] == "Y") == (v22["환급신청액"] > 0))
    check("C12b 연말정산여부 = 연말정산 코드 존재 여부", (d["연말정산여부"] == "Y") == bool(set(CODES["연말정산여부Y"]) & set(table)))

    if a.신고값:
        j = json.loads(Path(a.신고값).read_text(encoding="utf-8"))
        exp = {m[0]: m[1:4] for m in j["명세"]}
        got = {c: [v["인원"], v["총지급액"], v["징수세액_소득세등"]] for c, v in table.items()}
        check("C13 신고값(명세)과 코드별 인원·총지급액·소득세등 일치", exp == got,
              "" if exp == got else f"다름: {[c for c in set(exp) | set(got) if exp.get(c) != got.get(c)]}")
    report(results)


def report(results):
    fails = 0
    for name, ok, note in results:
        fails += not ok
        print(("통과  " if ok else "실패  ") + name + (f"\n      {note}" if note else ""))
    print(f"\n검사 {len(results)}개 · 통과 {len(results) - fails} · 실패 {fails}")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
