# -*- coding: utf-8 -*-
"""매입매출장만으로 부가가치세 신고서 본지를 그린다. 자기 검증용이다.

  python make_return.py <폴더> [산출폴더]

폴더에서 `매입매출장_*.xlsx` 를 전부 찾아 파일 하나에 신고 단위 하나로 본다.
같은 꼬리표를 가진 `일반전표_*.xlsx` 가 있으면 대사에 쓴다.

산출 (신고 단위마다)
  신고서_<기간>.pdf              별지 제21호서식 본지. 홈택스 출력과 같은 모양
  신고서_산출근거_<기간>.xlsx     란별 값이 장부 어디서 왔는지 네 시트

`return_review.py` 와 다른 점은 **직원 작성본과 대조하지 않는다**는 것뿐이다.
롤업과 본지 계산식은 같은 함수를 부른다. 두 벌로 적으면 다음 개정 때 한쪽만 고친다.

**신고하지 않는다.** 홈택스 화면을 자동으로 조작하지 않는다. 서명은 회계사가 진다.
"""
import os
import re
import sys
import glob

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import form21_pdf                                                  # noqa: E402
import to_pdf                                                      # noqa: E402
from ledger_io import _rows_from_xlsx, write_xlsx, n, s            # noqa: E402
from return_review import (rollup, build, verify_form, rule,       # noqa: E402
                           SALES_VT, BUY_VT)

sys.stdout.reconfigure(encoding="utf-8")

MM_GUBUN = "매입매출구분(1-매출/2-매입)"

# 란마다 어느 행이 들어오는지. 보고서에 그대로 적어 사람이 따라갈 수 있게 한다
LANE_NOTE = {
    "(1)": "매출 · 과세유형 11 (세금계산서 발급)",
    "(3)": "매출 · 과세유형 17·22 (신용카드·현금영수증)",
    "(6)": "매출 · 과세유형 16 (영세율 기타). 세액 없음",
    "면세": "매출 · 과세유형 13·18·23 (면세). 과세표준 밖",
    "(10)": "매입 · 과세유형 51 중 기본계정이 고정자산이 아닌 것",
    "(12)": "매입 · 과세유형 51 중 기본계정이 고정자산인 것",
    "(15)": "매입 · 과세유형 57·61 (신용카드·현금영수증 수령)",
    "(17)": "매입 · 과세유형 54 (불공제). (10)(12)에 넣었다가 여기서 뺀다",
    "계산서": "매입 · 과세유형 53 (면세 계산서). 본지 밖. 계산서합계표로 간다",
}


def period_of(path):
    """파일 이름에서 신고 단위를 읽는다. `매입매출장_2026-1기확정.xlsx` 꼴."""
    stem = os.path.splitext(os.path.basename(path))[0]
    tail = stem.split("_", 1)[1] if "_" in stem else stem
    m = re.match(r"(\d{4})-(\d)기\s*(예정|확정)", tail)
    if not m:
        return tail, tail, True, None
    y, half, kind = m.group(1), int(m.group(2)), m.group(3)
    q = {(1, "예정"): ("1.1", "3.31"), (1, "확정"): ("4.1", "6.30"),
         (2, "예정"): ("7.1", "9.30"), (2, "확정"): ("10.1", "12.31")}[(half, kind)]
    label = f"{y}년 제{half}기 {kind}신고 ({q[0]} ~ {q[1]})"
    # 홈택스 출력물은 신고기간 칸에 **과세기간 전체**를 적는다. 확정도 1.1 부터다
    span = {1: ("01", "01", "06", "30"), 2: ("07", "01", "12", "31")}[half]
    if kind == "예정":
        span = {1: ("01", "01", "03", "31"), 2: ("07", "01", "09", "30")}[half]
    return tail, label, kind == "확정", (int(y), half) + span


def evidence(rows, fixed_acct):
    """란별로 건수까지 세어 근거 표를 만든다. 합계는 롤업과 같아야 한다."""
    out = {}
    for r in rows:
        vt, gubun = n(r["과세유형"]), n(r[MM_GUBUN])
        if gubun == 1:
            key = SALES_VT.get(vt)
        elif vt == 51:
            key = "(12)" if s(r["기본계정"]) in fixed_acct else "(10)"
        else:
            key = BUY_VT.get(vt)
        if not key:
            out.setdefault("미배정", [0, 0, 0])
            out["미배정"][0] += 1
            out["미배정"][1] += n(r["공급가액"])
            out["미배정"][2] += n(r["부가세"])
            continue
        out.setdefault(key, [0, 0, 0])
        out[key][0] += 1
        out[key][1] += n(r["공급가액"])
        out[key][2] += n(r["부가세"])
    return out


# 부가세 대상이 아예 아닌 계정. 일반전표에 있는 것이 정상이라 세우지 않는다
NEVER_VAT = {"801", "803", "805", "806", "818", "835", "840"}

# 일반전표에 남아 있으면 부가세를 다시 봐야 하는 계정. 이유가 계정마다 다르다
WATCH = {
    "813": "기업업무추진비. 증빙이 세금계산서·카드면 매입매출전표로 올려 (17)로 뺍니다",
    "822": "차량유지비. 비영업용 승용차면 불공제, 화물차면 공제입니다",
    "812": "여비교통비. 항공·택시는 여객운송이라 카드 매입세액 공제가 안 됩니다",
    "811": "복리후생비. 직원 회식은 공제 대상입니다. 접대와 섞이지 않았는지 봅니다",
    "833": "광고선전비. 금액이 크면 세금계산서 수취 누락을 봅니다",
    "824": "운반비. 택배·물류는 보통 세금계산서가 나옵니다",
    "830": "소모품비. 카드·현금영수증 증빙이면 (15)로 갑니다",
    "831": "지급수수료. 플랫폼 수수료 세금계산서 미수취가 여기 숨습니다",
}


def tie_journal(mm, gj):
    """일반전표에 남은 비용 중 부가세를 다시 봐야 할 것을 세운다.

    **매출 총액 대사는 하지 않는다.** 매출은 전부 매입매출전표로 가고 일반전표에
    수익 계정이 없는 것이 정상이라, 빼서 비교하면 매출 전액이 차이로 찍힌다.

    실제로 볼 것은 이쪽이다. 접대비·차량유지비가 일반전표에만 있으면 증빙이 없어
    비용으로만 처리한 것이거나, 매입세액을 공제받거나 불공제로 빼야 할 것을 놓친 것이다."""
    if not gj:
        return []
    in_mm = {s(r["기본계정"]) for r in mm if n(r[MM_GUBUN]) == 2}
    agg = {}
    for r in gj:
        code = s(r.get("계정과목코드"))
        if code in NEVER_VAT:
            continue
        if not (code.startswith(("5", "8")) or code in ("146", "150", "153")):
            continue
        a = agg.setdefault(code, [s(r.get("계정과목명")), 0, 0])
        a[1] += 1
        a[2] += n(r.get("차변")) - n(r.get("대변"))
    out = []
    for code in sorted(agg):
        name, cnt, amt = agg[code]
        if not amt:
            continue
        out.append({
            "계정코드": code, "계정과목": name, "건수": cnt, "일반전표 금액": amt,
            "매입매출장에도 있나": "있음" if code in in_mm else "**일반전표에만**",
            "볼 것": WATCH.get(code, "부가세 대상 거래인지, 증빙이 무엇인지 봅니다"),
        })
    return out


def one(mm_path, gj_path, out_dir, company, params):
    period, label, is_final, span6 = period_of(mm_path)
    rows = _rows_from_xlsx(mm_path)
    gj = _rows_from_xlsx(gj_path) if gj_path else []
    fixed_acct = {s(r["계정코드"]) for r in rule("고정자산_계정.csv")}

    # 제2장 (44)(45) 는 카드 매입을 일반·고정자산으로 나눈다. (89)(90) 은 계산서다
    card_fix = [0, 0]
    issued = 0
    for r in rows:
        if (n(r[MM_GUBUN]) == 2 and n(r["과세유형"]) in (57, 61)
                and s(r["기본계정"]) in fixed_acct):
            card_fix[0] += n(r["공급가액"])
            card_fix[1] += n(r["부가세"])
        if n(r[MM_GUBUN]) == 1 and n(r["과세유형"]) == 13:
            issued += n(r["공급가액"])
    p2 = {"고정자산 카드매입": tuple(card_fix),
          "계산서 발급": issued,
          "계산서 수취": sum(n(r["공급가액"]) for r in rows
                        if n(r[MM_GUBUN]) == 2 and n(r["과세유형"]) == 53),
          # (85) 면세사업 수입금액은 업종이 따로다. 과세분 업종코드를 그대로
          # 복사하면 면세 업종을 과세 업종으로 신고하게 된다
          "면세 업태": params.get("면세 업태", ""),
          "면세 종목": params.get("면세 종목", ""),
          "면세 업종코드": params.get("면세 업종코드", "")}

    agg = rollup(rows, fixed_acct)
    # 조세특례제한법 제104조의8 제2항: 납세자가 직접 전자신고하는 확정신고만 공제한다.
    # 세무대리인이 신고하면 공제는 세무대리인 쪽(제3항)이라 납세자 신고서 (19) 는 0 이다
    대리 = s(params.get("세무대리인 신고", "아니오")) == "예"
    credit = n(params.get("전자신고세액공제", 0)) if (is_final and not 대리) else 0
    form = build(agg, credit)
    bad = verify_form(form)
    ev = evidence(rows, fixed_acct)

    # ── 근거 엑셀 ─────────────────────────────────────────
    lane_rows = []
    for k in ["(1)", "(3)", "(6)", "면세", "(10)", "(12)", "(15)", "(17)",
              "계산서", "미배정"]:
        c, sup, vat = ev.get(k, [0, 0, 0])
        if not (c or sup or vat):
            continue
        lane_rows.append({"란": k, "무엇이 들어오나": LANE_NOTE.get(k, "확인 필요"),
                          "건수": c, "공급가액": sup, "세액": vat})

    chk = [{"검사": no, "식": expr, "계산값": want, "본지 값": got,
            "차이": want - got} for no, expr, want, got in bad]
    d = {r[0]: r for r in form}
    chk.append({"검사": "A5", "식": "(9) 세액 = (1)+(3) 세액",
                "계산값": d["(1)"][3] + d["(3)"][3], "본지 값": d["(9)"][3],
                "차이": d["(1)"][3] + d["(3)"][3] - d["(9)"][3]})
    # 영세율은 세율이 0 일 뿐 과세거래라 (9) 과세표준 합계에 들어간다.
    # 한때 이 검사가 「영세율은 별도」라고 적혀 있어 틀린 (9) 를 스스로 통과시켰다
    l9 = d["(1)"][2] + d["(3)"][2] + d["(4)"][2] + d["(5)"][2] + d["(6)"][2]
    chk.append({"검사": "A6", "식": "(9) 공급가액 = (1)+(2)+(3)+(4)+(5)+(6)+(7)+(8). "
                                  "영세율도 과세표준이다",
                "계산값": l9, "본지 값": d["(9)"][2], "차이": l9 - d["(9)"][2]})
    # A7. 란마다 근거표 합계와 본지 값이 같아야 한다. 세액을 10퍼센트로 다시
    # 계산하면 여기서 몇 원이 벌어진다. 장부에 적힌 부가세를 그대로 더한다
    for k in ["(1)", "(3)", "(6)", "(10)", "(12)", "(15)", "(17)", "면세"]:
        cnt, sup, vat = ev.get(k, [0, 0, 0])
        if k not in d:
            continue
        chk.append({"검사": f"A7 {k}", "식": f"근거표 {k} 공급가액 = 본지 {k}",
                    "계산값": sup, "본지 값": d[k][2], "차이": sup - d[k][2]})
        chk.append({"검사": f"A8 {k}", "식": f"근거표 {k} 세액 = 본지 {k}",
                    "계산값": vat, "본지 값": d[k][3], "차이": vat - d[k][3]})
    chk.append({"검사": "A9", "식": "10퍼센트 재계산과의 차이 (참고. 0이 아니어도 됩니다)",
                "계산값": (d["(1)"][2] + d["(3)"][2]) // 10, "본지 값": d["(9)"][3],
                "차이": (d["(1)"][2] + d["(3)"][2]) // 10 - d["(9)"][3]})

    sheets = [
        ("1_본지", ["란", "명칭", "공급가액", "세액"],
         [{"란": r[0], "명칭": r[1], "공급가액": r[2], "세액": r[3]} for r in form],
         [8, 42, 18, 16]),
        ("2_란별_산출근거", ["란", "무엇이 들어오나", "건수", "공급가액", "세액"],
         lane_rows, [8, 52, 8, 18, 16]),
        ("3_검증식", ["검사", "식", "계산값", "본지 값", "차이"], chk,
         [7, 50, 18, 18, 12]),
    ]
    tj = tie_journal(rows, gj)
    if tj:
        sheets.append(("4_일반전표_확인", list(tj[0].keys()), tj,
                       [9, 18, 7, 18, 18, 64]))
    xp = os.path.join(out_dir, f"신고서_산출근거_{period}.xlsx")
    write_xlsx(xp, sheets)

    # ── 본지 PDF · 서식 원본에 값만 얹는다 ────────────────
    # HTML 로 서식을 다시 그리지 않는다. 폰트·자간·선 굵기를 맞춰도 원본과 같아지지 않는다
    stem = os.path.join(out_dir, f"신고서_{period}")
    ok, err = form21_pdf.build(
        stem + ".pdf", company=company, rows=form, p2=p2, 확정=is_final,
        사업자번호=params.get("사업자등록번호", ""),
        대표자=params.get("대표자", ""),
        주소=params.get("사업장 주소", ""),
        생년월일=params.get("생년월일", ""),
        사업장전화=params.get("사업장 전화", ""),
        주소지전화=params.get("주소지 전화", ""),
        휴대전화=params.get("휴대전화", ""),
        전자우편=params.get("전자우편", ""),
        업태=params.get("업태", ""), 종목=params.get("종목", ""),
        업종코드=params.get("업종코드", ""),
        세무서=params.get("관할 세무서", ""), 기간=span6,
        면세업태=params.get("면세 업태", ""),
        면세종목=params.get("면세 종목", ""),
        면세업종코드=params.get("면세 업종코드", ""))
    if err:
        print("  **", err)
    return period, label, form, bad, ev, xp, stem, ok


def main(argv):
    args = [a for a in argv if not a.startswith("--")]
    opts = dict(a[2:].split("=", 1) for a in argv
                if a.startswith("--") and "=" in a)
    if not args:
        sys.exit(__doc__)
    src = args[0]
    out_dir = args[1] if len(args) > 1 else os.path.join(src, "신고서")
    os.makedirs(out_dir, exist_ok=True)

    params = {r["항목"]: r["값"] for r in rule("신고_파라미터.csv")}
    company = opts.get("company", params.get("회사명", ""))

    mms = sorted(glob.glob(os.path.join(src, "매입매출장_*.xlsx")))
    mms = [p for p in mms if not os.path.basename(p).startswith("~$")]
    if not mms:
        sys.exit(f"매입매출장_*.xlsx 를 못 찾았습니다 · {src}")

    for mm in mms:
        tail = os.path.splitext(os.path.basename(mm))[0].split("_", 1)[1]
        gj = os.path.join(src, f"일반전표_{tail}.xlsx")
        gj = gj if os.path.exists(gj) else None
        period, label, form, bad, ev, xp, stem, ok = one(
            mm, gj, out_dir, company, params)
        d = {r[0]: r for r in form}
        print(f"\n[{label}]  {os.path.basename(mm)} · {sum(v[0] for v in ev.values()):,}행"
              + ("" if gj else "   일반전표 없음. 대사 건너뜀"))
        # (9) 가 이미 영세율을 안고 있다. 여기서 또 더하면 두 번 센다
        print(f"  과세표준 {d['(9)'][2]:>16,}   "
              f"매출세액 {d['(9)'][3]:>14,}"
              + (f"   (영세율 {d['(6)'][2]:,} 포함)" if d['(6)'][2] else ""))
        print(f"  매입세액 {d['(18)'][3]:>16,}   "
              f"납부세액 {d['㉰'][3]:>14,}")
        print(f"  전자신고세액공제 {d['(19)'][3]:>8,}   "
              f"차감납부 {d['(30)'][3]:>14,}")
        if ev.get("미배정"):
            print(f"  ** 미배정 {ev['미배정'][0]}행. 과세유형이 규칙 밖입니다")
        for no, expr, want, got in bad:
            print(f"  ** {no} 안 맞음 · {expr} · {want:,} 대 {got:,}")
        if not bad:
            print("  검증식 A1~A4 통과")
        print("  ", xp)
        print("  ", stem + (".pdf" if ok else ".html  PDF 실패. HTML 만 남았습니다"))


if __name__ == "__main__":
    main(sys.argv[1:])
