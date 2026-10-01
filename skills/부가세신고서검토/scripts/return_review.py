# -*- coding: utf-8 -*-
"""직원이 작성한 부가가치세 신고서를 장부에서 다시 만든 본지와 대조하고,
부속명세서를 장부에서 만들어 본지와 맞춘다.

  python return_review.py <장부폴더> [산출폴더]

장부폴더에는 **수정 후 장부**와 **직원 작성 신고서**가 있어야 한다.
장부가 틀린 채로 신고서를 보면 원인을 되짚게 된다. 매입매출장검토를 먼저 돌린다.

산출
  검토리포트_신고서_<기간>.md
  신고서_<기간>.pdf             본지 · 크로스 체크 · 검토 결과 · 서명란
  부속명세_<기간>.pdf            서식 8종 · 본지 대사
  본지_대사_<기간>.xlsx        내 본지 · 직원 작성본 · 란별 차이
  부속명세_<기간>.xlsx          서식 8종 + 검증
  확인사항_신고서_<기간>.md

본지 (1)~(30) 계산식은 부가가치세법 시행규칙 별지 제21호서식 <개정 2026. 3. 20.> 그대로다.
검증식(A군)이 안 맞으면 정지로 세운다. 산출 코드가 잘못된 것이니 그 회차 산출물은 쓰지 않는다.
"""
import os
import sys
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
RULES = os.path.normpath(os.path.join(HERE, "..", "rules"))

# 매입매출장검토를 불러 쓰지 않는다. 공용 함수는 이 폴더의 ledger_io.py 에 한 벌 더 있다
from ledger_io import (load, pick, n, s, write_xlsx,  # noqa: E402
                       _rows_from_csv, coverage_md)

STOP, ASK = "정지", "확인"

SALES_VT = {11: "(1)", 12: "(5)", 14: "(4)", 17: "(3)", 22: "(3)", 16: "(6)",
            13: "면세", 18: "면세", 23: "면세"}
BUY_VT = {57: "(15)", 61: "(15)", 54: "(17)", 53: "계산서"}

# 별지 제22호서식 2번 표의 사유 ①~⑧. 장부 「불공제사유」 칸의 1~8 을 이 순서로 읽는다
DENY = "①②③④⑤⑥⑦⑧"


def deny_mark(v):
    """불공제사유 칸 값을 ①~⑧ 로 바꾼다. 비었거나 1~8 밖이면 빈 문자열."""
    t = s(v)
    if t and t[0] in DENY:
        return t[0]
    digits = ""
    for ch in t:
        if not ch.isdigit():
            break
        digits += ch
    if digits and 1 <= int(digits) <= len(DENY):
        return DENY[int(digits) - 1]
    return ""


def card_exempt_sales(rows):
    """신용카드·현금영수증으로 받은 면세 매출(과세유형 18·23) 공급가액.
    23호 집계표의 면세 매출분은 이것만이다. 계산서(13) 면세 매출은 들어가지 않는다."""
    return sum(n(r["공급가액"]) for r in rows
               if n(r["매입매출구분(1-매출/2-매입)"]) == 1 and n(r["과세유형"]) in (18, 23))


def rule(name):
    p = os.path.join(RULES, name)
    return _rows_from_csv(p) if os.path.exists(p) else []


def rollup(rows, fixed_acct):
    """란별로 공급가액과 세액을 함께 더한다.
    세액을 공급가액의 10퍼센트로 다시 계산하지 않는다. 건별 반올림과 어긋나
    합계표가 본지와 몇 원 벌어진다. 합계표는 0원으로 맞아야 하는 서식이다."""
    agg, vat = defaultdict(int), defaultdict(int)
    for r in rows:
        sup = n(r["공급가액"])
        if n(r["매입매출구분(1-매출/2-매입)"]) == 1:
            key = SALES_VT.get(n(r["과세유형"]))
        elif n(r["과세유형"]) == 51:
            key = "(12)" if s(r["기본계정"]) in fixed_acct else "(10)"
        else:
            key = BUY_VT.get(n(r["과세유형"]))
        if key:
            agg[key] += sup
            vat[key] += n(r["부가세"])
        # 불공제 세금계산서(54)는 (10) 일반매입에 들어간 채로 (17) 에서 뺀다.
        # (17) 에만 넣으면 (16) 에서 빠지고 (18) 에서 또 빠져 납부세액이 불공제 세액만큼 높아진다
        if key == "(17)":
            agg["(10)"] += sup
            vat["(10)"] += n(r["부가세"])
    return agg, vat


def build(agg_vat, l19):
    agg, vat = agg_vat
    l1, l3, l4, l5, l6, ex = (agg["(1)"], agg["(3)"], agg["(4)"], agg["(5)"],
                              agg["(6)"], agg["면세"])
    l10, l12, l15, l17 = agg["(10)"], agg["(12)"], agg["(15)"], agg["(17)"]
    v1, v3, v4 = vat["(1)"], vat["(3)"], vat["(4)"]
    v10, v12, v15, v17 = vat["(10)"], vat["(12)"], vat["(15)"], vat["(17)"]
    out = v1 + v3 + v4
    # (9) 는 「과세표준 및 매출세액」 블록의 (1)~(8) 합계다. **영세율 (5)(6) 이 그 안에 있다.**
    # 영세율은 세율이 0 일 뿐 과세거래라 과세표준에 들어간다. 세액만 0 이다.
    # 별지 제21호서식 작성방법 5-가·다: (31)~(33) 은 「(9)란에 적힌 과세표준 합계액」을
    # 업태·종목별로 나눠 적고, (35) 합계액은 (9) 와 일치해야 한다.
    # 빼면 과세표준명세가 영세율만큼 모자라 법인세 수입금액 대사가 어긋난다.
    l9 = l1 + l3 + l4 + l5 + l6
    l16 = l10 + l12 + l15
    it = v10 + v12 + v15
    l17t = v17
    net = it - l17t
    pay = out - net
    return [("(1)", "세금계산서 발급분", l1, v1),
            ("(3)", "신용카드·현금영수증 발행분", l3, v3),
            ("(4)", "기타(정규영수증 외 매출분)", l4, v4),
            ("(5)", "영세율 세금계산서 발급분", l5, 0),
            ("(6)", "영세율 기타", l6, 0),
            ("(7)", "예정신고 누락분", 0, 0),
            ("(8)", "대손세액 가감", 0, 0),
            ("(9)", "합계 ㉮", l9, out),
            ("(10)", "세금계산서 수취 일반매입", l10, v10),
            ("(11)", "수출기업 수입 납부유예", 0, 0),
            ("(12)", "세금계산서 수취 고정자산매입", l12, v12),
            ("(13)", "예정신고 누락분", 0, 0),
            ("(14)", "매입자발행세금계산서", 0, 0),
            ("(15)", "그 밖의 공제매입세액", l15, v15),
            ("(16)", "합계 (10)-(11)+(12)+(13)+(14)+(15)", l16, it),
            ("(17)", "공제받지 못할 매입세액", l17, l17t),
            ("(18)", "차감계 (16)-(17) ㉯", l16 - l17, net),
            ("㉰", "납부(환급)세액 ㉮-㉯", "", pay),
            ("(19)", "그 밖의 경감·공제세액", "", l19),
            ("(20)", "신용카드매출전표등 발행공제 등", 0, 0),
            ("(21)", "경감·공제세액 합계 ㉱", "", l19),
            ("(24)", "예정고지세액 ㉴", "", 0),
            ("(29)", "가산세액계 ㉹", "", 0),
            ("(30)", "차감·가감하여 납부할 세액", "", pay - l19),
            ("면세", "면세수입금액", ex, 0)]


def verify_form(rows):
    """A군. 본지 검증식. 안 맞으면 산출 코드가 잘못된 것이다."""
    d = {r[0]: r for r in rows}
    bad = []
    # (11) 을 상수 0 으로 두면 수출기업 수입 납부유예가 있는 고객사에서 안 걸린다
    l16 = (d["(10)"][2] - d["(11)"][2] + d["(12)"][2] + d["(13)"][2]
           + d["(14)"][2] + d["(15)"][2])
    if l16 != d["(16)"][2]:
        bad.append(("A1", "(16) = (10)-(11)+(12)+(13)+(14)+(15)", l16, d["(16)"][2]))
    if d["(16)"][2] - d["(17)"][2] != d["(18)"][2]:
        bad.append(("A2", "(18) = (16) - (17)", d["(16)"][2] - d["(17)"][2], d["(18)"][2]))
    if d["(9)"][3] - d["(18)"][3] != d["㉰"][3]:
        bad.append(("A3", "㉰ = ㉮ - ㉯", d["(9)"][3] - d["(18)"][3], d["㉰"][3]))
    # 식에 적어 놓고 계산에서 빼먹으면 예정고지나 가산세가 있는 기에 안 걸린다
    l30 = d["㉰"][3] - d["(21)"][3] - d["(24)"][3] + d["(29)"][3]
    if l30 != d["(30)"][3]:
        bad.append(("A4", "(30) = ㉰ - ㉱ - ㉴ + ㉹", l30, d["(30)"][3]))
    return bad


# ── 부속명세 ─────────────────────────────────────────────────
def attachments(rows, fixed_acct, zero_rule=None):
    def grp(sel, keyf):
        g = defaultdict(lambda: [0, 0, 0])
        for r in rows:
            if not sel(r):
                continue
            k = keyf(r)
            g[k][0] += 1
            g[k][1] += n(r["공급가액"])
            g[k][2] += n(r["부가세"])
        return [dict({"거래처명": k[0], "사업자등록번호": k[1], "매수": v[0],
                      "공급가액": v[1], "세액": v[2]},
                     **({"사유": k[2]} if len(k) > 2 else {}))
                for k, v in sorted(g.items()) if v[1] or v[2]]

    def key(r):
        return (s(r["거래처명"]), s(r["사업자(주민)등록번호"]))

    sale = lambda r: n(r["매입매출구분(1-매출/2-매입)"]) == 1
    buy = lambda r: n(r["매입매출구분(1-매출/2-매입)"]) == 2

    out = {}
    # 영세율 세금계산서(12)도 매출처별 합계표에 올라간다
    out["38호_매출처별"] = grp(lambda r: sale(r) and n(r["과세유형"]) in (11, 12), key)
    # 불공제 세금계산서(54)도 매입처별 합계표에 올라간다. 합계 = (10)+(12) 는 불공제분 포함이다
    out["39호_매입처별"] = grp(lambda r: buy(r) and n(r["과세유형"]) in (51, 54), key)
    out["16호_수령명세서"] = grp(lambda r: buy(r) and n(r["과세유형"]) in (57, 61), key)
    out["23호_발행금액집계표"] = grp(
        lambda r: sale(r) and n(r["과세유형"]) in (17, 18, 22, 23), key)
    # 22호는 사유별로 적는 서식이다. 거래처에 사유(①~⑧)를 붙여 묶는다
    out["22호_공제받지못할"] = grp(lambda r: buy(r) and n(r["과세유형"]) == 54,
                               lambda r: key(r) + (deny_mark(r.get("불공제사유")),))
    out["27호_건물등취득"] = grp(
        lambda r: buy(r) and n(r["과세유형"]) == 51 and s(r["기본계정"]) in fixed_acct, key)
    out["소득29호_계산서"] = grp(lambda r: buy(r) and n(r["과세유형"]) == 53, key)

    # 영세율 매출명세서 — 별지 제29호서식 (시행규칙 제62조 제10항).
    # 시행령 제91조 제2항 제12호가 확정신고서에 붙이라고 정한다. 근거 조문별로 묶는다
    zr = {s(r["과세유형"]): r for r in (zero_rule or []) if s(r["과세유형"]) != "0"}
    z = defaultdict(lambda: [0, 0])
    for r in rows:
        if not sale(r) or n(r["과세유형"]) not in (12, 16):
            continue
        m = zr.get(str(n(r["과세유형"])), {})
        k = (s(m.get("근거조문")) or "구분 미상", s(m.get("구분")) or "확인 필요",
             s(m.get("제101조 서류")) or "확인 필요")
        z[k][0] += 1
        z[k][1] += n(r["공급가액"])
    # 16호는 현금영수증과 사업용 신용카드를 나눠 적는다. 서식 칸이 다르다
    구분 = {}
    for key, vts in (("현금영수증", (61,)), ("사업용신용카드", (57,))):
        g = [0, 0, 0]
        for r in rows:
            if buy(r) and n(r["과세유형"]) in vts:
                g[0] += 1
                g[1] += n(r["공급가액"])
                g[2] += n(r["부가세"])
        구분[key] = tuple(g)
    out["_16호_구분"] = 구분

    out["29호_영세율매출명세서"] = [
        {"근거조문": k[0], "구분": k[1], "제101조 첨부서류": k[2], "건수": v[0], "금액": v[1]}
        for k, v in sorted(z.items()) if v[1]]   # 원건과 취소가 상계돼 0원이면 명세에 안 올린다
    return out


def tie(att, form, card_exempt=None):
    """부속명세 합계를 본지와 맞춘다. **공급가액과 세액을 둘 다 본다.**
    공급가액만 보면 건별 반올림으로 생긴 세액 차이가 안 잡힌다."""
    d = {r[0]: r for r in form}

    def tot(name, field="공급가액"):
        return sum(r[field] for r in att.get(name, []))

    checks = [
        ("C1", "38호 매출처별 합계 = (1)+(5)",
         tot("38호_매출처별"), d["(1)"][2] + d["(5)"][2],
         tot("38호_매출처별", "세액"), d["(1)"][3] + d["(5)"][3]),
        ("C2", "39호 매입처별 합계 = (10)+(12)",
         tot("39호_매입처별"), d["(10)"][2] + d["(12)"][2],
         tot("39호_매입처별", "세액"), d["(10)"][3] + d["(12)"][3]),
        ("C3", "16호 수령명세서 합계 = (15)",
         tot("16호_수령명세서"), d["(15)"][2], tot("16호_수령명세서", "세액"), d["(15)"][3]),
        ("C4", "23호 발행금액집계표 = (3) 공급대가 + 카드 면세",
         tot("23호_발행금액집계표") + tot("23호_발행금액집계표", "세액"),
         d["(3)"][2] + d["(3)"][3]
         + (d["면세"][2] if card_exempt is None else card_exempt), None, None),
        ("C5", "22호 공제받지못할 합계 = (17)",
         tot("22호_공제받지못할"), d["(17)"][2], tot("22호_공제받지못할", "세액"), d["(17)"][3]),
        ("C6", "27호 건물등취득 합계 = (12)",
         tot("27호_건물등취득"), d["(12)"][2], tot("27호_건물등취득", "세액"), d["(12)"][3]),
        ("C8", "29호 영세율매출명세서 = (5)+(6)",
         tot("29호_영세율매출명세서", "금액"), d["(5)"][2] + d["(6)"][2], None, None),
    ]
    out = []
    for no, what, gs, ws, gv, wv in checks:
        out.append({"검사": no, "무엇": what,
                    "부속명세 공급가액": gs, "본지 공급가액": ws, "공급가액 차이": gs - ws,
                    "부속명세 세액": gv, "본지 세액": wv,
                    "세액 차이": (gv - wv) if gv is not None else None})
    return out


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    folder = os.path.abspath(sys.argv[1])
    out = os.path.abspath(sys.argv[2]) if len(sys.argv) > 2 \
        else os.path.join(folder, "신고서검토")
    os.makedirs(out, exist_ok=True)

    t = load(folder)
    led = pick(t, "매입매출장")
    if not led:
        print("매입매출장을 못 찾았습니다.")
        sys.exit(1)
    # 상계하지 않는다. 원건·취소·재발행 세 행 묶음에서 취소와 재발행이 짝지어 지워진다.
    # 신고서는 합계로 보는 것이라 음수 행을 그대로 더한다
    live = list(led)
    months = sorted({f"{n(r['년도'])}-{n(r['월']):02d}" for r in live})
    period = f"{months[0]}~{months[-1][-2:]}"
    확정 = True

    fixed_acct = {s(r["계정코드"]) for r in rule("고정자산_계정.csv")}
    파라미터 = {s(r["항목"]): s(r["값"]) for r in rule("신고_파라미터.csv")}
    # 조세특례제한법 제104조의8: 납세자가 직접 전자신고할 때만(제2항). 세무대리인이 신고하면 공제는
    # 세무대리인 쪽(제3항)이라 납세자 신고서 (19) 는 0 이다
    대리 = 파라미터.get("세무대리인 신고", "아니오") == "예"
    e_credit = 0 if (대리 or not 확정) else int(파라미터.get("전자신고세액공제", 5000))
    법인 = 파라미터.get("법인여부", "예") == "예"

    mine = build(rollup(live, fixed_acct), e_credit)
    d_mine = {r[0]: r for r in mine}

    # 직원 작성본은 PDF 로 받는다. 직원이 더존에서 뽑아 넘기는 것이 PDF 다.
    # 엑셀·CSV 로 받은 경우도 읽는다
    import glob as _glob
    import to_pdf
    d_staff, pdf_src, pdf_err = {}, None, None
    for cand in (sorted(_glob.glob(os.path.join(folder, "신고서*작성본*.pdf")))
                 + sorted(_glob.glob(os.path.join(folder, "신고서*.pdf")))):
        d_staff, pdf_err = to_pdf.read_return_pdf(cand)
        d_staff = d_staff or {}
        pdf_src = os.path.basename(cand)
        break
    if not d_staff:
        for r in (pick(t, "신고서_직원작성본") or pick(t, "vat_return_1st_staff")):
            d_staff[s(r["란"])] = (s(r["란"]), s(r["명칭"]),
                                   n(r["공급가액"]), n(r["세액"]))

    findings = []

    def add(no, grade, what, target, expect, actual, look, ground):
        findings.append({"검사": no, "등급": grade, "무엇": what, "대상": target,
                         "기대": expect, "실제": actual, "볼 곳": look, "근거": ground})

    # A군 검증식
    for no, expr, got, want in verify_form(mine):
        add(no, STOP, "본지 검증식이 안 맞는다", expr, f"{want:,}", f"{got:,}",
            "산출 코드", "별지 제21호서식 <개정 2026. 3. 20.>")

    # B군 장부 대 신고서 (크로스 체크)
    diff_rows = []
    # PDF 에서 읽으면 금액이 빈 란은 None 으로 온다. 0 과 구분해서 다룬다
    def z(x):
        return 0 if x in (None, "") else int(x)

    for no, nm, sup, tax in mine:
        if no not in d_staff:
            continue
        _, _, ssup, stax = d_staff[no]
        if z(sup) != z(ssup) or z(tax) != z(stax):
            diff_rows.append({"란": no, "명칭": nm, "내 본지 공급가액": sup,
                              "직원 공급가액": ssup, "공급가액 차이": z(ssup) - z(sup),
                              "내 본지 세액": tax, "직원 세액": stax,
                              "세액 차이": z(stax) - z(tax)})
    for r in diff_rows:
        no = r["란"]
        if no == "(19)":
            add("D6", STOP, "전자신고세액공제 금액이 다르다",
                f"(19) 직원 {r['직원 세액']:,}원",
                f"확정신고 전자신고분은 {e_credit:,}원"
                + (" (세무대리인 신고라 납세자 공제 없음)" if 대리 else ""),
                f"{r['직원 세액']:,}원으로 적혀 있다",
                "직원 작성 신고서 (19)란",
                "조세특례제한법 제104조의8 제2항 · 별지 제21호서식 (19)란")
        elif no in ("(1)", "(3)", "(6)", "면세"):
            add("B2", STOP, "과세표준이 장부와 다르다",
                f"{no} {r['명칭']} 차이 {r['공급가액 차이']:+,}원",
                "장부 매출 합계 = 신고서 과세표준",
                f"직원 신고서가 {r['공급가액 차이']:+,}원",
                "매입매출장 매출 행과 원천 집계",
                "진단항목 B2 · 별지 제21호서식 (1)(3)(6)란·면세수입금액")
        elif no in ("(10)", "(12)", "(15)", "(17)"):
            add("B4", STOP, "매입세액이 장부와 다르다",
                f"{no} {r['명칭']} 차이 {r['공급가액 차이']:+,}원",
                "장부 매입 합계 = 신고서 매입란",
                f"직원 신고서가 {r['공급가액 차이']:+,}원",
                "매입매출장 매입 행과 tax_invoices·card_approvals",
                "진단항목 B4 · 별지 제21호서식 (10)(12)(15)(17)란")

    if 법인 and d_staff.get("(20)", ("", "", 0, 0))[3]:
        add("D5", STOP, "법인인데 신용카드 발행공제가 들어갔다",
            f"(20) {d_staff['(20)'][3]:,}원", "법인이면 (20) = 0", "0이 아니다",
            "직원 작성 신고서 (20)란", "부가가치세법 제46조 제1항 제1호 가목")

    # C군 부속명세 대 본지
    zero_rule = rule("영세율_구분.csv")
    att = attachments(live, fixed_acct, zero_rule)
    card_exempt = card_exempt_sales(live)
    ties = tie(att, mine, card_exempt)
    for c in ties:
        for kind in ("공급가액", "세액"):
            gap = c[f"{kind} 차이"]
            if not gap:
                continue
            add(c["검사"], STOP, f"부속명세서 {kind} 합계가 본지와 안 맞는다", c["무엇"],
                f'{c[f"본지 {kind}"]:,}원',
                f'{c[f"부속명세 {kind}"]:,}원 ({gap:+,})',
                "부속명세 해당 시트의 거래처별 합계",
                f"진단항목 {c['검사']} · 부속 서식 합계 = 본지 란")

    # C5 사유 코드 공란. 사유가 없으면 22호 사유별 표에 안 올라가 사유별 합이 (17)과 어긋난다
    blank = [r for r in att.get("22호_공제받지못할", []) if not r.get("사유")]
    if blank:
        add("C5", STOP, "불공제 세금계산서의 사유 코드가 비어 있다",
            f"{len(blank)}개 거래처 · 공급가액 {sum(r['공급가액'] for r in blank):,}원",
            "과세유형 54 행마다 불공제사유 1~8",
            "사유가 없어 별지 제22호서식 사유별 표에 못 올렸다",
            "매입매출장 과세유형 54 행의 불공제사유 칸",
            "진단항목 C5 · 부가가치세법 제39조 제1항 · 시행규칙 별지 제22호서식")

    # C7 계산서합계표 — 본지 밖이라 원천 면세 매입과 맞춘다
    ti_src = pick(t, "tax_invoices")
    src_exempt = sum(n(r["공급가액"]) for r in ti_src
                     if s(r["매출매입구분"]) == "매입" and n(r["부가세"]) == 0
                     and months[0] <= s(r["작성일자"])[:7] <= months[-1])
    got_exempt = sum(r["공급가액"] for r in att.get("소득29호_계산서", []))
    if not ti_src:
        # 원천이 없으면 정지로 세우지 않는다. 대조를 못 한 것이지 틀린 것이 아니다
        src_exempt = got_exempt
        add("C7", ASK, "계산서 수취목록 원천이 없어 계산서합계표를 대조하지 못했다",
            f"소득 29호 합계 {got_exempt:,}원 (장부 과세유형 53)",
            "홈택스 계산서 수취목록 합계 = 계산서합계표",
            "tax_invoices 표가 없어 장부 안에서만 집계했다",
            "홈택스 계산서 수취목록을 받아 tax_invoices 로 넣는다",
            "법인세법 제121조 제5항 · 소득세법 제163조 제5항")
    elif got_exempt != src_exempt:
        add("C7", STOP, "계산서합계표가 원천 면세 매입과 안 맞는다",
            "소득 29호 매입처별 계산서합계표",
            f"{src_exempt:,}원", f"{got_exempt:,}원 ({got_exempt - src_exempt:+,})",
            "tax_invoices 부가세 0원 행", "법인세법 제121조 제5항 · 소득세법 제163조 제5항")

    # C8 영세율 첨부서류 — 안 내면 그 부분은 신고로 보지 않는다
    zero_base = d_mine["(5)"][2] + d_mine["(6)"][2]
    if zero_base:
        need = {}
        for r in att.get("29호_영세율매출명세서", []):
            need.setdefault(r["제101조 첨부서류"], [0, r["근거조문"], r["구분"]])
            need[r["제101조 첨부서류"]][0] += r["금액"]
        src_by_doc = {s(r["제101조 서류"]): s(r["원천 표"]) for r in zero_rule}
        missing = 0
        for doc, (amt, ground, gubun) in sorted(need.items()):
            table = src_by_doc.get(doc, "")
            have = bool(table and pick(t, table))
            if have:
                continue
            missing += amt
            add("C8", STOP, "영세율 첨부서류가 없다",
                f"{gubun} {amt:,}원 · {doc}",
                f"확정신고서에 {doc} 를 첨부한다",
                f"원천에 {table or '해당 자료'} 가 없어 만들 수 없다",
                f"{table or '수출신고필증·외화입금증명서'} 를 받아 온다",
                "부가가치세법 시행령 제101조 제1항·제2항 · "
                f"{ground}")
        if missing:
            penalty = round(missing * 0.005)
            add("C8", STOP, "첨부 안 한 부분은 신고로 보지 않는다",
                f"영세율 과세표준 {missing:,}원",
                "첨부서류를 내야 그 부분이 신고로 인정된다",
                f"안 내면 그만큼 영세율과세표준을 신고하지 않은 것이 되어 "
                f"과소신고가산세에 더해지는 가산세 {penalty:,}원 (0.5퍼센트)",
                "시행령 제91조 제3항 제1호",
                "부가가치세법 시행령 제91조 제3항 제1호 · "
                "국세기본법 제47조의3 제2항 제2호")

    # E군 전기 대비. 과세기간 길이가 다르면 월수로 환산해서 본다
    prior = pick(t, "vat_return_prior")
    skipped = {}
    if not prior:
        skipped = {"E1": "원천 없음: vat_return_prior", "E3": "원천 없음: vat_return_prior"}
    if prior:
        was_m = int(파라미터.get("전기 과세기간 개월수", 6))
        now_m = len(months)
        k = now_m / was_m
        dp = {s(r["란"]): (n(r["공급가액"]), n(r["세액"])) for r in prior}
        th_rate = int(파라미터.get("증감률 임계", 30))
        for no, label in (("(1)", "세금계산서 매출"), ("(3)", "카드·현금영수증 매출"),
                          ("(10)", "일반매입")):
            was = dp.get(no, (0, 0))[0]
            now = d_mine[no][2]
            if not was:
                continue
            base = was * k
            rate = (now - base) / base * 100
            if abs(rate) > th_rate:
                add("E1", ASK, "전기 대비 증감이 크다",
                    f"{no} {label} 전기 {was:,}원({was_m}개월) -> "
                    f"{now_m}개월 환산 {round(base):,}원 · 당기 {now:,}원 ({rate:+.1f}%)",
                    f"월 평균 기준 ±{th_rate}퍼센트 이내",
                    f"{rate:+.1f}퍼센트", "vat_return_prior", "진단항목 E1")
        # E3 부담률. 과세기간 길이와 무관하다
        pw, ps = dp.get("(1)", (0, 0)), dp.get("(3)", (0, 0))
        base_ts = pw[0] + ps[0]
        if base_ts:
            was_rate = (pw[1] + ps[1] - dp.get("(10)", (0, 0))[1]
                        - dp.get("(15)", (0, 0))[1] + dp.get("(17)", (0, 0))[1]) \
                / base_ts * 100
            now_ts = d_mine["(1)"][2] + d_mine["(3)"][2]
            now_rate = d_mine["(30)"][3] / now_ts * 100 if now_ts else 0
            th_pp = int(파라미터.get("부담률 임계", 5))
            if abs(now_rate - was_rate) > th_pp:
                add("E3", ASK, "부담률이 전기와 크게 다르다",
                    f"전기 {was_rate:.2f}% -> 당기 {now_rate:.2f}% "
                    f"({now_rate - was_rate:+.2f}%p)",
                    f"전기 대비 ±{th_pp}퍼센트포인트 이내",
                    f"{now_rate - was_rate:+.2f}퍼센트포인트",
                    "납부세액 ÷ 과세표준", "진단항목 E3")

    # ── 산출 ──────────────────────────────────────────────────
    stop = [f for f in findings if f["등급"] == STOP]
    ask = [f for f in findings if f["등급"] == ASK]

    cmp_rows = []
    for no, nm, sup, tax in mine:
        _, _, ssup, stax = d_staff.get(no, (no, nm, "", ""))
        cmp_rows.append({"란": no, "명칭": nm, "내 본지 공급가액": sup, "내 본지 세액": tax,
                         "직원 공급가액": ssup, "직원 세액": stax,
                         "공급가액 차이": (n(ssup) - n(sup)) if no in d_staff else "",
                         "세액 차이": (n(stax) - n(tax)) if no in d_staff else ""})
    write_xlsx(os.path.join(out, f"본지_대사_{period}.xlsx"),
               [("본지 대사", ["란", "명칭", "내 본지 공급가액", "내 본지 세액",
                            "직원 공급가액", "직원 세액", "공급가액 차이", "세액 차이"],
                 cmp_rows, [8, 38, 20, 18, 20, 18, 18, 16])])

    ATT_COLS = ["거래처명", "사업자등록번호", "매수", "공급가액", "세액"]
    ZERO_COLS = ["근거조문", "구분", "제101조 첨부서류", "건수", "금액"]
    ver = list(ties) + [{"검사": "C7", "무엇": "소득29호 계산서합계표 = 원천 면세 매입",
                         "부속명세 공급가액": got_exempt, "본지 공급가액": src_exempt,
                         "공급가액 차이": got_exempt - src_exempt,
                         "부속명세 세액": 0, "본지 세액": 0, "세액 차이": 0}]
    ver.sort(key=lambda r: int(r["검사"][1:]))
    VER_COLS = ["검사", "무엇", "부속명세 공급가액", "본지 공급가액", "공급가액 차이",
                "부속명세 세액", "본지 세액", "세액 차이"]
    sheets = [("검증", VER_COLS, ver, [8, 38, 20, 20, 16, 18, 18, 14])]
    for name, rows in att.items():
        if name.startswith("_"):
            continue
        if name.startswith("29호_영"):
            sheets.append((name, ZERO_COLS, rows, [34, 24, 34, 10, 20]))
        elif name.startswith("22호"):
            sheets.append((name, ATT_COLS + ["사유"], rows, [26, 18, 8, 20, 18, 8]))
        else:
            sheets.append((name, ATT_COLS, rows, [26, 18, 8, 20, 18]))
    write_xlsx(os.path.join(out, f"부속명세_{period}.xlsx"), sheets)

    L = [f"# 부가가치세 신고서·부속명세 검토 리포트 · {period}", "",
         f"- 검출 {len(findings)}건 (정지 {len(stop)} · 확인 {len(ask)})",
         f"- 직원 작성 납부세액 {d_staff.get('(30)', ('', '', 0, 0))[3]:,}원 · "
         f"내 본지 {d_mine['(30)'][3]:,}원 · "
         f"차이 {d_staff.get('(30)', ('', '', 0, 0))[3] - d_mine['(30)'][3]:+,}원", ""]
    if stop:
        L += ["## 정지", "", "**신고하지 않습니다.**", ""]
        for f in stop:
            L += [f"### [{f['검사']}] {f['무엇']}", "", f"- 대상 : {f['대상']}",
                  f"- 기대 : {f['기대']}", f"- 실제 : {f['실제']}",
                  f"- 볼 곳 : {f['볼 곳']}", f"- 근거 : {f['근거']}", ""]
    if ask:
        L += ["## 확인", "", "회계사가 읽고 판정합니다.", ""]
        for f in ask:
            L += [f"### [{f['검사']}] {f['무엇']}", "", f"- 대상 : {f['대상']}",
                  f"- 기대 : {f['기대']}", f"- 실제 : {f['실제']}",
                  f"- 볼 곳 : {f['볼 곳']}", f"- 근거 : {f['근거']}", ""]
    if not findings:
        L += ["## 통과", "", "본지와 부속명세가 전부 맞습니다. 회계사 서명 후 신고합니다.", ""]
    L += ["## 부속명세 대사", "",
          "| 검사 | 무엇 | 공급가액 차이 | 세액 차이 |", "|---|---|---:|---:|"]
    for c in ties:
        gv = c["세액 차이"]
        L.append(f"| {c['검사']} | {c['무엇']} | {c['공급가액 차이']:+,} | "
                 f"{'-' if gv is None else format(gv, '+,')} |")
    L += [""] + coverage_md(findings, rule("진단항목.csv"), skipped)
    L += ["", "---", "",
          "**리뷰는 회계사가 합니다.** 이 스킬은 볼 것을 모아 줄 뿐이고 판정과 서명은 회계사가 집니다.",
          "홈택스 화면을 자동으로 조작하지 않습니다.", ""]
    with open(os.path.join(out, f"검토리포트_신고서_{period}.md"), "w",
              encoding="utf-8") as f:
        f.write("\n".join(L))

    C = [f"# 확인사항 · 신고서 {period}", "",
         "| 검사 | 항목 | 상황 | 무엇을 정해야 하나 |", "|---|---|---|---|"]
    for f in findings:
        C.append(f"| {f['검사']} | {f['무엇']} | {f['대상']} | {f['기대']} |")
    C += ["", "**표에 한 줄로 올라간 것만 등재입니다.**", ""]
    with open(os.path.join(out, f"확인사항_신고서_{period}.md"), "w",
              encoding="utf-8") as f:
        f.write("\n".join(C))

    # PDF. 엑셀은 작업용이고 서명·보관본은 PDF 다
    import to_pdf
    company = 파라미터.get("회사명", "")
    y, m1, m2 = months[0][:4], int(months[0][5:7]), int(months[-1][5:7])
    기 = "제1기" if m2 <= 6 else "제2기"
    label = f"{y}년 {기} {'확정' if 확정 else '예정'}신고 ({m1}.1 ~ {m2}.{[31,29,31,30,31,30,31,31,30,31,30,31][m2-1]})"
    pdfs = []
    for stem, doc in (
            (f"신고서_{period}",
             to_pdf.build_return_html(company, label, mine, d_staff, findings, '')),
            (f"부속명세_{period}",
             to_pdf.build_attach_html(company, label, att, ver, {
                 "company": company, "period": label,
                 "biz": 파라미터.get("사업자등록번호", ""),
                 "ceo": 파라미터.get("대표자", ""),
                 "addr": 파라미터.get("사업장 주소", ""),
                 "업태": 파라미터.get("업태", ""), "종목": 파라미터.get("종목", ""),
                 "range": f"{months[0]}-01 ~ {months[-1]}-{[31,29,31,30,31,30,31,31,30,31,30,31][int(months[-1][5:7])-1]}",
                 "today": "", "구분": att.get("_16호_구분", {}),
                 "23과세": (d_mine["(3)"][2], d_mine["(3)"][3]),
                 "23면세": card_exempt}))):
        ok = to_pdf.write(doc, os.path.join(out, stem + ".html"),
                          os.path.join(out, stem + ".pdf"))
        pdfs.append((stem, ok))

    print("=" * 72)
    print(f"신고서·부속명세 검토 · {period}")
    print("=" * 72)
    sp = d_staff.get("(30)", ("", "", 0, 0))[3] or 0
    if pdf_src:
        칸 = len([k for k in d_staff if k.startswith("(") or k == "면세"])
        print(f"  직원 작성본 {pdf_src} 에서 란 {칸}개를 읽었습니다")
    elif pdf_err:
        print(f"  PDF 를 못 읽었습니다: {pdf_err}")
    print(f"  직원 작성 납부세액 {sp:,}원 · 내 본지 {d_mine['(30)'][3]:,}원 "
          f"(차이 {sp - d_mine['(30)'][3]:+,}원)")
    print(f"  검출 {len(findings)}건   정지 {len(stop)} · 확인 {len(ask)}\n")
    for f in findings:
        print(f"  [{f['검사']:<3}] {f['등급']}  {f['무엇']}")
        print(f"         {f['대상']}")
    print("\n  [부속명세 대사]   공급가액과 세액을 둘 다 봅니다")
    for c in ver:
        gs, gv = c["공급가액 차이"], c["세액 차이"]
        m1 = "0원" if gs == 0 else f"{gs:+,}"
        m2 = "-" if gv is None else ("0원" if gv == 0 else f"{gv:+,}")
        print(f"   {c['검사']}  {c['무엇']:<38} 공급가액 {m1:>12} · 세액 {m2:>12}")
    print("\n  [서명·보관본]")
    for stem, ok in pdfs:
        print(f"   {stem}.pdf  {'만들었습니다' if ok else 'HTML 만 남았습니다'}")
    if not all(ok for _, ok in pdfs):
        print("   Edge 나 Chrome 이 없어 인쇄를 못 했습니다. "
              "HTML 을 열어 Ctrl+P 로 뽑으면 같습니다")
    print(f"\n산출 -> {out}")
    return 1 if stop else 0


if __name__ == "__main__":
    sys.exit(main())
