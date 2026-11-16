# -*- coding: utf-8 -*-
"""부가세 신고서 빠른 검토. 분개장 엑셀과 출력된 신고서 PDF 두 개만 읽는다.

실행
    python -I -X utf8 quick_review.py <분개장.xlsx> <신고서.pdf> [--md 결과.md]
    python -I -X utf8 quick_review.py <폴더>          # 폴더 아래 xlsx 1개 · pdf 1개

-I 로 돌리면 스크립트 폴더가 import 경로에 안 들어간다. 그래서 파일 하나로 둔다.
숫자는 이 스크립트가 낸 것만 보고한다. Claude 가 다시 계산하지 않는다.
"""
import os
import re
import sys
import glob
from collections import defaultdict

# ── 상수 ─────────────────────────────────────
DEPOSIT = "부가세예수"      # 매출세액 계정 이름에 든 말
ADVANCE = "부가세대급"      # 매입세액
UNPAID_TAX = "미지급세금"
CASH_CODES = range(101, 104)   # 현금 · 당좌 · 보통예금
FIXED_CODES = range(201, 231)  # 유형자산 (누계액 제외)
CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮"
NUM = re.compile(r"^-?\d{1,3}(,\d{3})+$|^-?\d+$")
COMMA_NUM = re.compile(r"^-?\d{1,3}(,\d{3})+$")
RAN_END = re.compile(r"\((\d{1,2})\)$")
RAN_START = re.compile(r"^\((\d{1,2})\)")
PERIOD = re.compile(r"(\d{4})년제?(\d)기\((\d{2})월(\d{2})일[~∼～](\d{2})월(\d{2})일")
BIZ = re.compile(r"\d{3}-\d{2}-\d{5}")


def num(v):
    if v is None or v == "":
        return 0
    if isinstance(v, (int, float)):
        return int(round(v))
    t = str(v).replace(",", "").strip()
    try:
        return int(round(float(t)))
    except ValueError:
        return 0


def f(v):
    return f"{v:,}" if isinstance(v, int) else (v or "")


# ── 분개장 ───────────────────────────────────
def read_ledger(path):
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    rows = list(wb.active.iter_rows(values_only=True))
    wb.close()
    hi = next((i for i, r in enumerate(rows[:10])
               if r and "전표일자" in [str(c).strip() for c in r if c is not None]
               and "계정과목" in [str(c).strip() for c in r if c is not None]), None)
    if hi is None:
        raise SystemExit("분개장 머리글(전표일자 · 계정과목)을 첫 10행에서 못 찾았습니다")
    head = [str(c).strip() if c is not None else "" for c in rows[hi]]
    ci = {k: head.index(k) for k in ("전표일자", "전표번호", "계정과목", "차변", "대변")}
    ci["코드"] = ci["계정과목"] - 1
    ci["거래처"] = head.index("거래처") if "거래처" in head else None
    ci["적요"] = head.index("적요") if "적요" in head else None
    lines, footer = [], None
    for r in rows[hi + 1:]:
        if not r or all(c in (None, "") for c in r):
            continue
        d = str(r[ci["전표일자"]] or "").strip()
        if d.startswith("합계"):
            m = re.search(r"([\d,]+)", d)
            footer = (num(m.group(1)) if m else None, num(r[ci["차변"]]), num(r[ci["대변"]]))
            continue
        if not re.match(r"\d{4}-\d{2}-\d{2}", d):
            continue
        g = lambda k: r[ci[k]] if ci.get(k) is not None and ci[k] < len(r) else None
        lines.append(dict(date=d[:10], no=str(g("전표번호") or "").strip(),
                          code=num(g("코드")), name=str(g("계정과목") or "").strip(),
                          dr=num(g("차변")), cr=num(g("대변")),
                          who=str(g("거래처") or "").strip(), memo=str(g("적요") or "").strip()))
    return lines, footer


def ledger_facts(lines):
    by = defaultdict(list)
    for x in lines:
        by[(x["date"], x["no"])].append(x)
    is_dep = lambda x: DEPOSIT in x["name"]
    is_adv = lambda x: ADVANCE in x["name"]
    is_sale = lambda x: str(x["code"]).startswith("4") and "매출" in x["name"]
    is_fixed = lambda x: x["code"] in FIXED_CODES and "누계" not in x["name"]

    def closing(v):
        return (any(is_dep(x) and x["dr"] for x in v) and
                any((is_adv(x) and x["cr"]) or UNPAID_TAX in x["name"] or
                    (x["code"] in CASH_CODES and x["cr"]) for x in v))

    F = dict(vouchers=len(by), lines=len(lines),
             dr=sum(x["dr"] for x in lines), cr=sum(x["cr"] for x in lines),
             dates=(min(x["date"] for x in lines), max(x["date"] for x in lines)),
             months=sorted({x["date"][:7] for x in lines}),
             unbalanced=[(k, sum(x["dr"] - x["cr"] for x in v)) for k, v in by.items()
                         if sum(x["dr"] - x["cr"] for x in v)],
             dep=0, dep_lines=0, adv=0, close=[], a=0, b=0, b_n=0, c=0, c_list=[],
             fx_buy=[], fx_sell=[], close_dep=0, close_adv=0, close_unpaid=0, close_misc=0)
    for k, v in sorted(by.items()):
        if closing(v):
            F["close"].append(k)
            F["close_dep"] += sum(x["dr"] for x in v if is_dep(x))
            F["close_adv"] += sum(x["cr"] for x in v if is_adv(x))
            F["close_unpaid"] += sum(x["cr"] - x["dr"] for x in v if UNPAID_TAX in x["name"])
            F["close_misc"] += sum(x["dr"] - x["cr"] for x in v if "잡손실" in x["name"]) \
                - sum(x["cr"] - x["dr"] for x in v if "잡이익" in x["name"])
            continue
        dep = sum(x["cr"] - x["dr"] for x in v if is_dep(x))
        F["dep"] += dep
        F["dep_lines"] += sum(1 for x in v if is_dep(x))
        F["adv"] += sum(x["dr"] - x["cr"] for x in v if is_adv(x))
        sale = sum(x["cr"] - x["dr"] for x in v if is_sale(x))
        has_dep = any(is_dep(x) for x in v)
        if has_dep and any(is_sale(x) for x in v):
            F["a"] += sale
        elif has_dep:
            F["b"] += dep * 10
            F["b_n"] += 1
        elif sale:
            F["c"] += sale
            who = next((x["who"] for x in v if is_sale(x)), "")
            F["c_list"].append(f"{k[0][5:]} {k[1]} {who} {sale:,}")
        for x in v:
            if is_fixed(x) and x["dr"] > 0:
                F["fx_buy"].append((k, x["name"], x["dr"], any(is_adv(y) for y in v)))
            if is_fixed(x) and x["cr"] > 0:
                cash = sum(y["dr"] for y in v if y["code"] in CASH_CODES or "미수금" in y["name"])
                F["fx_sell"].append((k, x["name"], x["cr"], has_dep, cash))
    return F


# ── 신고서 PDF ────────────────────────────────
def _lines(words):
    out = []
    for w in sorted(words, key=lambda w: (w[1], w[0])):
        h = max(w[3] - w[1], 1.0)
        if out and abs(w[1] - out[-1][0]) <= h * 0.5:
            out[-1][1].append(w)
        else:
            out.append([w[1], [w]])
    res = []
    for _, ws in out:
        ws.sort(key=lambda w: w[0])
        res.append(ws)
    return res


def _lines_mid(words):
    """높이의 가운데로 묶는다. 서식 원본에 값을 얹은 PDF 는 금액이 칸 이름보다 1~2pt 위에서
    시작해, 윗변으로 묶으면 금액이 윗줄(세로로 걸친 「과세」 같은 칸 이름)로 붙는다.
    위하고 출력물은 윗변 묶음이 맞아 본지에서 못 읽은 란을 채울 때만 쓴다."""
    out = []
    mid = lambda w: (w[1] + w[3]) / 2
    for w in sorted(words, key=lambda w: (mid(w), w[0])):
        h = max(w[3] - w[1], 1.0)
        if out and abs(mid(w) - out[-1][0]) <= h * 0.4:
            out[-1][1].append(w)
        else:
            out.append([mid(w), [w]])
    return [sorted(ws, key=lambda w: w[0]) for _, ws in out]


def _mid_of(txt, mid, target):
    joined, spans = "", []
    for t, m in zip(txt, mid):
        spans.append((len(joined), len(joined) + len(t), m))
        joined += t
    i = joined.find(target)
    if i < 0:
        return None
    ms = [m for a, b, m in spans if a < i + len(target) and b > i]
    return sum(ms) / len(ms) if ms else None


def _kind(top):
    t = top
    # 본지 2장 머리는 출력 프로그램마다 다르다. 위하고는 「(2장앞쪽)」, 2026. 3. 20. 서식 원본은
    # 「(6쪽(제2장중제4쪽)앞쪽)」 이다
    for k, key in (("본지1", "별지제21호서식"), ("본지2", "2장앞쪽"), ("본지2", "제2장중"),
                   ("카드갑", "수령명세서(갑)"), ("카드을", "수령명세서(을)"),
                   ("불공제", "공제받지못할매입세액명세서"),
                   ("매출세계", "매출처별세금계산서합계표"), ("매입세계", "매입처별세금계산서합계표"),
                   ("매출계", "매출처별계산서합계표"), ("매입계", "매입처별계산서합계표"),
                   ("수출", "수출실적명세서"), ("영세율", "영세율매출명세서"),
                   ("감가", "감가상각자산취득명세서"), ("단위과세", "사업자단위과세")):
        if key in t:
            return k
    return "기타"


def _ints(ws):
    return [num(w[4]) for w in ws if NUM.match(w[4])]


def _total_row(ls, single_amount):
    """합계표 「합계」 줄. 금액이 낱자로 나와 x 간격이 가장 큰 곳에서 공급가액과 세액을 자른다."""
    for ws in ls:
        # 「합 계」 로 두 낱말로 나오는 서식도 있다
        if ws[0][4] == "합" and len(ws) > 1 and ws[1][4] == "계":
            ws = [ws[0][:4] + ("합계",) + ws[0][5:]] + ws[2:]
        if ws[0][4] != "합계":
            continue
        ns = [w for w in ws[1:] if NUM.match(w[4])]
        if len(ns) < 2:
            return dict(처수=0, 매수=0, 공급가액=0, 세액=0)
        cnt, sheets, digits = num(ns[0][4]), num(ns[1][4]), ns[2:]
        if single_amount:
            return dict(처수=cnt, 매수=sheets, 공급가액=num("".join(w[4] for w in digits)), 세액=0)
        gaps = [(digits[i + 1][0] - digits[i][2], i) for i in range(len(digits) - 1)]
        if not gaps:
            return dict(처수=cnt, 매수=sheets, 공급가액=num(digits[0][4]) if digits else 0, 세액=0)
        g, i = max(gaps)
        sup = num("".join(w[4] for w in digits[:i + 1]))
        tax = num("".join(w[4] for w in digits[i + 1:]))
        bad = sup and not (0.05 <= tax / sup <= 0.15)
        return dict(처수=cnt, 매수=sheets, 공급가액=sup, 세액=tax, 못읽음=bad)
    return None


def read_return(path):
    import fitz
    R = dict(ran={}, pages=[], biz=[], periods=[], kind=None, company=None, forms={})
    doc = fitz.open(path)
    for pno, pg in enumerate(doc):
        ls = _lines(pg.get_text("words"))
        top = "".join(w[4] for ws in ls[:3] for w in ws)
        kind = _kind(top)
        R["pages"].append(kind)
        flat = ["".join(w[4] for w in ws) for ws in ls]
        # 식별: 사업자번호 · 기간
        for ws, j in zip(ls, flat):
            if "사업자등록번호" in j:
                k = next(i for i, w in enumerate(ws) if "사업자등록번호" in w[4])
                d = re.sub(r"\D", "", "".join(w[4] for w in ws[k + 1:]))
                if len(d) >= 10:
                    R["biz"].append((pno + 1, d[:10]))
                    break
        else:
            # 서식 이름이 없는 이어지는 쪽은 거래처 명세뿐이라 첫 사업자번호가 거래처 것이다
            m = BIZ.search("\n".join(flat)) if kind != "기타" else None
            if m:
                R["biz"].append((pno + 1, m.group().replace("-", "")))
        m = next((PERIOD.search(j) for j in flat if PERIOD.search(j)), None)
        if m:
            R["periods"].append((pno + 1, f"{m[3]}-{m[4]}~{m[5]}-{m[6]}", f"{m[1]}년 {m[2]}기"))
        if kind == "카드을":
            # 을 쪽에도 갑 이름이 각주로 나온다. 행만 읽는다
            rows = R["forms"].setdefault("카드을", [])
            for ws in ls:
                t = [w[4] for w in ws]
                if len(t) >= 6 and re.match(r"^\d{4}-", t[1]) and BIZ.fullmatch(t[2]):
                    rows.append((t[2], num(t[-3]), num(t[-2]), num(t[-1])))
            continue
        if kind in ("본지1", "본지2"):
            _read_main(ls, flat, R, pno)
            # 못 읽은 란만 가운데 묶음으로 한 번 더 채운다(먼저 읽은 값은 그대로 둔다)
            lm = _lines_mid(pg.get_text("words"))
            _read_main(lm, ["".join(w[4] for w in ws) for ws in lm], R, pno)
        if kind == "불공제":
            # 3. 공통매입세액 안분계산명세 ~ 4. 사이에 금액이 있는지
            sec = False
            for ws, j in zip(ls, flat):
                if j.startswith("3.") and "공통매입세액" in j:
                    sec = True
                    continue
                if sec and j.startswith("4."):
                    break
                if sec and any(COMMA_NUM.match(w[4]) for w in ws):
                    R["forms"]["공통안분"] = True
        if kind == "수출":
            for ws in ls:
                t = [w[4] for w in ws]
                k = next((i for i, x in enumerate(t) if re.match(r"^\d{5}-\d{2}-\d{6}", x)), None)
                if k is None or len(t) < k + 6:
                    continue
                R["forms"].setdefault("수출행", []).append(dict(
                    신고번호=t[k], 선적일=t[k + 1], 통화=t[k + 2],
                    환율=float(t[k + 3].replace(",", "")), 외화=float(t[k + 4].replace(",", "")),
                    원화=num(t[k + 5])))
        if kind in ("카드갑", "불공제"):
            d = R["forms"].setdefault(kind, {})
            for ws in ls:
                c = ws[0][4][:1]
                ns = _ints(ws)
                if c in CIRCLED and (kind == "카드갑" or c in "①②③④⑤⑥⑦⑧⑨"):
                    d[c] = tuple(ns[-3:]) if len(ns) >= 3 else (0, 0, 0)
        elif kind in ("매출세계", "매입세계", "매출계", "매입계"):
            R["forms"][kind] = _total_row(ls, kind in ("매출계", "매입계"))
        elif kind == "수출":
            for ws, j in zip(ls, flat):
                if j.startswith("⑨") and "합계" in j:
                    R["forms"]["수출"] = _ints(ws)[-1] if _ints(ws) else 0
        elif kind == "영세율":
            for ws, j in zip(ls, flat):
                if j.startswith("⑬"):
                    ns = [n for w, n in zip(ws, [num(w[4]) for w in ws]) if COMMA_NUM.match(w[4])]
                    R["forms"]["영세율"] = ns[-1] if ns else 0
        elif kind == "감가":
            R["forms"]["감가"] = True
    doc.close()
    return R


def _read_main(ls, flat, R, pno):
    cx = None
    for ws, j in zip(ls, flat):
        if pno == 0 and R["kind"] is None and "예정" in j and "확정" in j and "√" in j:
            v = next(w for w in ws if w[4] == "√")
            right = [w for w in ws if w[4] in ("예정", "확정") and w[0] > v[0]]
            R["kind"] = min(right, key=lambda w: w[0])[4] if right else None
        if R["company"] is None:
            m = re.search(r"신고인(.+?)\(서명", j)
            if m:
                R["company"] = m.group(1)
        if all(k in j for k in ("구분", "금액", "세율", "세액")):
            txt, mid = [w[4] for w in ws], [(w[0] + w[2]) / 2 for w in ws]
            g, s = _mid_of(txt, mid, "금액"), _mid_of(txt, mid, "세액")
            if g and s:
                cx = (g, s)
            continue
        idx = next((i for i in range(len(ws) - 1, -1, -1) if RAN_END.search(ws[i][4])
                    and not NUM.match(ws[i][4])), None)
        if idx is None:
            idx = next((i for i, w in enumerate(ws) if RAN_START.match(w[4])), None)
        if idx is None:
            if any(w[4] == "㉰" for w in ws):
                k = next(i for i, w in enumerate(ws) if w[4] == "㉰")
                ns = [num(w[4]) for w in ws[k + 1:] if NUM.match(w[4])]
                if ns:
                    R["ran"].setdefault("㉰", (None, ns[0]))
            continue
        w0 = ws[idx][4]
        n = int((RAN_END.search(w0) or RAN_START.match(w0)).group(1))
        after = ws[idx + 1:]
        if 31 <= n <= 35 or 85 <= n <= 90:
            v = next((num(w[4]) for w in after if COMMA_NUM.match(w[4])), None)
            if v is not None:
                R["ran"].setdefault(n, (v, None))
            continue
        if cx is None:
            continue
        sup = tax = None
        for w in after:
            if not NUM.match(w[4]):
                continue
            m = (w[0] + w[2]) / 2
            if abs(m - cx[1]) < abs(m - cx[0]):
                tax = num(w[4])
            else:
                sup = num(w[4])
        if sup is None and tax is None:
            continue
        R["ran"].setdefault(n, (sup or 0, tax or 0))


# ── 판정 ─────────────────────────────────────
PASS, CHECK, NA, UNREAD = "통과", "확인필요", "해당없음", "못읽음"


def review(L, F, footer, R):
    out = []
    ran = R["ran"]
    S = lambda n: (ran.get(n) or (0, 0))[0] or 0
    T = lambda n: (ran.get(n) or (0, 0))[1] or 0
    has_main = "본지1" in R["pages"]
    fm = R["forms"]

    def add(no, item, rep, other, diff, verdict, notes=()):
        out.append(dict(no=no, item=item, rep=rep, other=other, diff=diff,
                        verdict=verdict, notes=list(notes)))

    # 1 식별 · 기간
    bz = {b for _, b in R["biz"]}
    pr = {p for _, p, _ in R["periods"]}
    main_p = next((p for pn, p, _ in R["periods"] if pn == 1), None)
    led_p = f"{F['dates'][0][5:]}~{F['dates'][1][5:]}"
    notes = []
    if len(bz) > 1:
        notes.append("사업자번호가 쪽마다 다름: " + ", ".join(f"{p}쪽 {b}" for p, b in R["biz"]))
    if len(pr) > 1:
        notes.append("기간이 쪽마다 다름: " + ", ".join(f"{p}쪽 {x}" for p, x, _ in R["periods"]))
    if main_p:
        a, b = main_p.split("~")
        if not (a <= F["dates"][0][5:] and F["dates"][1][5:] <= b):
            notes.append(f"분개장 전표일자 {led_p} 가 신고기간 {main_p} 를 벗어남")
        sm, em = int(a[:2]), int(b[:2])
        miss = [m for m in range(sm, em + 1)
                if f"{F['dates'][0][:4]}-{m:02d}" not in F["months"]]
        if miss:
            notes.append("전표가 없는 달: " + ", ".join(f"{m}월" for m in miss))
    add(1, "식별 · 기간", main_p or "", led_p, "",
        UNREAD if not main_p else (CHECK if notes else PASS), notes)

    # 2 분개장 차대
    d = F["dr"] - F["cr"]
    notes = [f"{k[0][5:]} {k[1]} 차대 {v:+,}" for k, v in F["unbalanced"]]
    if footer and footer[0] is not None and footer[0] != F["vouchers"]:
        notes.insert(0, f"합계행 건수 {footer[0]:,} ≠ 전표 {F['vouchers']:,}")
    v2 = CHECK if d or (footer and footer[0] is not None and footer[0] != F["vouchers"]) else PASS
    if v2 == PASS and notes:
        notes = ["(참고) 전표별 불일치가 서로 상쇄됨: " + "; ".join(notes)]
    add(2, "분개장 차대", "", f"{F['dr']:,}", d, v2, notes)

    if not has_main:
        for i, it in enumerate(["본지 산식", "세율 10%", "매출 세금계산서합계표", "매입 세금계산서합계표",
                                "카드수령명세서", "불공제명세서", "계산서합계표", "영세율",
                                "매출세액 ↔ 예수금", "매입세액 ↔ 대급금", "과세표준 ↔ 매출계정",
                                "고정자산", "정리분개 · 납부세액"], 3):
            add(i, it, "", "", "", UNREAD, ["신고서 본지 1쪽(별지 제21호서식)을 못 찾음"])
        return out

    # 3 본지 산식
    ga = T(9)
    na = T(18)
    checks = [
        ("(9) 금액", S(9), sum(S(i) for i in range(1, 8)) + S(8)),
        ("(9) 세액", T(9), sum(T(i) for i in range(1, 8)) + T(8)),
        ("(35)=(9)", S(35) if 35 in ran else S(9), S(9)),
        ("(31)~(34) 합=(35)", sum(S(i) for i in range(31, 35)), S(35) if 35 in ran else S(9)),
        ("(16) 금액", S(16), S(10) - S(11) + S(12) + S(13) + S(14) + S(15)),
        ("(16) 세액", T(16), T(10) - T(11) + T(12) + T(13) + T(14) + T(15)),
        ("(18)", T(18), T(16) - T(17)),
        ("(52)=(15)", T(52), T(15)),
        ("(56)=(17)", T(56), T(17)),
        ("㉰=㉮-㉯", T("㉰"), ga - na),
        ("(30)", T(30), T("㉰") - sum(T(i) for i in range(21, 28)) + T(28) + T(29)),
    ]
    bad = [f"{nm} 신고 {a:,} 계산 {b:,} 차이 {a - b:+,}" for nm, a, b in checks if a != b]
    add(3, f"본지 산식 {len(checks)}식", "", "", 0 if not bad else len(bad), CHECK if bad else PASS, bad)

    # 4 세율 10%
    cnt = {1: (fm.get("매출세계") or {}).get("매수", 0), 10: (fm.get("매입세계") or {}).get("매수", 0),
           15: (fm.get("카드갑") or {}).get("④", (0,))[0], 17: (fm.get("불공제") or {}).get("⑨", (0,))[0]}
    bad, worst = [], None
    for n in (1, 2, 3, 4, 10, 12, 15, 17):
        if not S(n):
            continue
        diff = T(n) - round(S(n) * 0.1)
        tol = max(1000, cnt.get(n, 0) * 10)
        if abs(diff) > tol:
            bad.append(f"({n}) 세액 {T(n):,} 금액×10% {round(S(n) * 0.1):,} 차이 {diff:+,} (허용 {tol:,})")
            worst = worst or (n, diff)
    if worst and worst[0] == 15:
        for b, k, s, t in fm.get("카드을", []):
            if abs(t - s * 0.1) > k * 10 + 10:
                bad.append(f"  카드 을 {b} 건수 {k} 공급가액 {s:,} 세액 {t:,}")
    add(4, "세율 10%" + (f" ({worst[0]})" if worst else ""), "", "",
        worst[1] if worst else 0, CHECK if bad else PASS, bad)

    # 5 매출 세금계산서합계표
    t = fm.get("매출세계")
    if t is None:
        add(5, "매출 세금계산서합계표", f"{S(1) + S(5):,}", "", "",
            CHECK if S(1) + S(5) else NA, ["합계표 쪽이 없음"] if S(1) + S(5) else [])
    elif t.get("못읽음"):
        add(5, "매출 세금계산서합계표", "", "", "", UNREAD, ["합계표 금액 경계를 못 정함"])
    else:
        ds, dt = t["공급가액"] - (S(1) + S(5)), t["세액"] - (T(1) + T(5))
        v = PASS if ds == 0 and dt == 0 else (f"{PASS}(단수)" if ds == 0 and abs(dt) <= t["매수"] else CHECK)
        add(5, "매출 세금계산서합계표 세액", f"{T(1) + T(5):,}", f"{t['세액']:,}", -dt, v,
            [f"공급가액 차이 {ds:+,}"] if ds else [])

    # 6 매입 세금계산서합계표
    t = fm.get("매입세계")
    if t is None:
        add(6, "매입 세금계산서합계표", f"{S(10) + S(12):,}", "", "",
            CHECK if S(10) + S(12) else NA, ["합계표 쪽이 없음"] if S(10) + S(12) else [])
    elif t.get("못읽음"):
        add(6, "매입 세금계산서합계표", "", "", "", UNREAD, ["합계표 금액 경계를 못 정함"])
    else:
        ds, dt = t["공급가액"] - (S(10) + S(12)), t["세액"] - (T(10) + T(12))
        add(6, "매입 세금계산서합계표", f"{S(10) + S(12):,}", f"{t['공급가액']:,}", -ds,
            PASS if ds == 0 and dt == 0 else CHECK, [f"세액 차이 {dt:+,}"] if dt else [])

    # 7 카드수령명세서
    g = fm.get("카드갑")
    if g is None:
        add(7, "카드수령명세서", f"{T(15):,}", "", "", CHECK if T(15) else NA,
            ["(15) 가 있는데 신용카드매출전표등수령명세서가 없음"] if T(15) else [])
    else:
        z = (0, 0, 0)
        four = g.get("④", z)
        parts = [g.get(c, z) for c in "⑤⑥⑦⑧"]
        eul = fm.get("카드을", [])
        eul_s = (sum(r[2] for r in eul), sum(r[3] for r in eul))
        bad = []
        if four[1:] != (S(44) + S(45), T(44) + T(45)):
            bad.append(f"④ {four[1]:,}/{four[2]:,} ≠ (44)+(45) {S(44) + S(45):,}/{T(44) + T(45):,}")
        if tuple(sum(p[i] for p in parts) for i in range(3)) != four:
            bad.append("⑤+⑥+⑦+⑧ ≠ ④")
        if eul and eul_s != g.get("⑧", z)[1:]:
            bad.append(f"을 명세 합 {eul_s[0]:,}/{eul_s[1]:,} ≠ ⑧ {g.get('⑧', z)[1]:,}/{g.get('⑧', z)[2]:,}")
        add(7, "카드수령명세서 ④=(44)+(45)", f"{T(44) + T(45):,}", f"{four[2]:,}",
            four[2] - T(44) - T(45), CHECK if bad else PASS, bad)

    # 8 불공제명세서
    g = fm.get("불공제")
    if g is None:
        add(8, "불공제명세서", f"{T(17):,}", "", "", CHECK if T(17) else NA,
            ["(17) 이 있는데 공제받지못할매입세액명세서가 없음"] if T(17) else [])
    else:
        # (17) = (56) = (53) 사유별 + (54) 공통매입 안분 + (55) 대손처분. ⑨ 는 사유별 합계라 (53) 과 맞춘다
        nine = g.get("⑨", (0, 0, 0))
        s56 = (S(53) + S(54) + S(55), T(53) + T(54) + T(55))
        ok = nine[1:] == (S(53), T(53)) and s56 == (S(17), T(17))
        add(8, "불공제명세서 ⑨=(53), (17)=(53)+(54)+(55)", f"{T(17):,}", f"{nine[2] + T(54) + T(55):,}",
            nine[2] + T(54) + T(55) - T(17),
            PASS if ok else CHECK, [] if ok else [f"⑨ {nine[1]:,}/{nine[2]:,}, (53) {S(53):,}/{T(53):,}, "
                                                  f"(54) {S(54):,}/{T(54):,}, (17) {S(17):,}/{T(17):,}"])

    # 9 계산서합계표
    bad, rep, oth = [], [], []
    for k, n, label in (("매출계", 89, "매출"), ("매입계", 90, "매입")):
        t = fm.get(k)
        if t is None and not S(n):
            continue
        if t is not None and not t.get("공급가액") and not S(n):
            continue        # 서식은 있지만 금액이 없다. 해당없음
        if t is None or not S(n):
            bad.append(f"{label}: 합계표 {'없음' if t is None else format(t['공급가액'], ',')}, ({n}) {S(n):,}")
            continue
        rep.append(f"({n}) {S(n):,}")
        oth.append(f"{t['공급가액']:,}")
        if t["공급가액"] != S(n):
            bad.append(f"{label} 합계표 {t['공급가액']:,} ≠ ({n}) {S(n):,}")
    add(9, "계산서합계표 = (89)(90)", " ".join(rep), " ".join(oth), "",
        CHECK if bad else (PASS if rep else NA), bad)

    # 10 영세율
    zr, ex, zs = fm.get("영세율"), fm.get("수출"), S(5) + S(6)
    if zr is None and ex is None and not zs:
        add(10, "영세율", "", "", "", NA)
    else:
        bad = []
        if zr is None and zs:
            bad.append(f"본지 (5)+(6) {zs:,} 인데 영세율매출명세서 없음")
        if zr is not None and zr != zs:
            bad.append(f"영세율매출명세서 ⑬ {zr:,} ≠ 본지 (5)+(6) {zs:,}")
        if ex is not None and ex > S(6):
            bad.append(f"수출실적명세서 ⑨ {ex:,} > 본지 (6) {S(6):,}")
        other = zr if zr is not None else (ex or 0)
        add(10, "영세율 (5)+(6)", f"{zs:,}", f"{other:,}", zs - other, CHECK if bad else PASS, bad)

    # 11 매출세액 ↔ 예수금
    diff = ga - F["dep"]
    notes = []
    if diff and diff == F["close_misc"]:
        notes.append(f"차이 {diff:,}원은 정리전표 잡손실·잡이익과 같음(본지 세액 절사)")
    v = PASS if diff == 0 else (f"{PASS}(단수)" if abs(diff) <= F["dep_lines"] else CHECK)
    add(11, "매출세액 ㉮ ↔ 예수금", f"{ga:,}", f"{F['dep']:,}", diff, v, notes)

    # 12 매입세액 ↔ 대급금
    diff = na - F["adv"]
    notes = []
    if diff and T(16) == F["adv"]:
        notes.append("대급금이 (16) 세액과 같음. 불공제분이 대급금에 남아 있음")
    add(12, "매입세액 ㉯ ↔ 대급금", f"{na:,}", f"{F['adv']:,}", diff, PASS if diff == 0 else CHECK, notes)

    # 13 과세표준 ↔ 매출계정
    tax_base = sum(S(i) for i in range(1, 5))
    other_base = S(5) + S(6) + S(85) + S(86)
    bad = []
    d1 = tax_base - (F["a"] + F["b"])
    if abs(d1) > F["b_n"] * 10:
        bad.append(f"(1)~(4) {tax_base:,} ≠ 매출계정 {F['a']:,} + 매출계정 없는 예수금×10 {F['b']:,}")
    if other_base != F["c"]:
        bad.append(f"(5)+(6)+(85)+(86) {other_base:,} ≠ 예수금 없는 매출 {F['c']:,}")
        bad += [f"  {x}" for x in F["c_list"][:3]] + ([f"  외 {len(F['c_list']) - 3}건"] if len(F["c_list"]) > 3 else [])
    if abs(S(34) - F["b"]) > F["b_n"] * 10:
        bad.append(f"(34) 수입금액제외 {S(34):,} ≠ 매출계정 없는 과세분(고정자산 매각 등) {F['b']:,}")
    add(13, "과세표준 ↔ 매출계정", f"{tax_base + other_base:,}", f"{F['a'] + F['b'] + F['c']:,}",
        tax_base + other_base - F["a"] - F["b"] - F["c"], CHECK if bad else PASS, bad)

    # 14 고정자산
    bad, ref = [], []
    buy = sum(x[2] for x in F["fx_buy"])
    if buy and not (S(12) + S(45)):
        for k, nm, amt, adv in F["fx_buy"]:
            bad.append(f"{k[0][5:]} {k[1]} {nm} 취득 {amt:,}, (12)·(45) 0"
                       + (", 감가상각자산취득명세서 없음" if not fm.get("감가") else "")
                       + ("" if adv else ", 대급금 없음"))
    for k, nm, amt, dep, cash in F["fx_sell"]:
        if dep:
            continue
        msg = f"{k[0][5:]} {k[1]} {nm} 매각 장부 {amt:,}" + (f", 입금 {cash:,}" if cash else "") + ", 예수금 없음"
        (ref if "토지" in nm else bad).append(msg)
    add(14, "고정자산 취득 · 매각", f"(12)+(45) {S(12) + S(45):,}", f"취득 {buy:,}", "",
        CHECK if bad else PASS, bad + [f"(참고) {x}" for x in ref])

    # 15 정리분개 · 납부세액
    bad = []
    if not F["close"]:
        bad.append("부가세 정리전표(예수금 차변 · 대급금 대변)가 없음")
    else:
        if F["close_dep"] != F["dep"]:
            bad.append(f"정리 예수금 {F['close_dep']:,} ≠ 발생 {F['dep']:,}")
        if F["close_adv"] != F["adv"]:
            bad.append(f"정리 대급금 {F['close_adv']:,} ≠ 발생 {F['adv']:,}")
        if F["close_unpaid"] != T(30):
            bad.append(f"미지급세금 {F['close_unpaid']:,} ≠ (30) {T(30):,}")
    cl = ", ".join(f"{k[0][5:]} {k[1]}" for k in F["close"][:2])
    add(15, "미지급세금 = (30)", f"{T(30):,}", f"{F['close_unpaid']:,}", T(30) - F["close_unpaid"],
        CHECK if bad else PASS, bad + ([f"(참고) 정리전표 {cl}"] if cl and not bad else []))
    return out


# ── AI 1차 검토 자료 ──────────────────────────
# 스크립트는 후보만 모은다. 공제 여부 · 원인 판단은 SKILL.md 「AI 1차 검토」 대로 Claude 가 한다.
NONDED_ACCT = ("업무추진", "접대", "차량", "여비교통", "기부", "토지")
NONDED_WHO = ("택시", "모빌리티", "카카오T", "도로공사", "대리운전", "항공", "코레일", "철도", "고속버스",
              "주차", "골프", "상품권")


def ai_material(lines, F, R, res):
    out = ["", "## AI 1차 검토 자료", "", "### A. 불공제 후보 (부가세대급금이 붙은 전표)", ""]
    by = defaultdict(list)
    for x in lines:
        by[(x["date"], x["no"])].append(x)
    cand = []
    for k, v in sorted(by.items()):
        adv = sum(x["dr"] - x["cr"] for x in v if ADVANCE in x["name"])
        if not adv or k in F["close"]:
            continue
        exp = [x for x in v if x["dr"] and ADVANCE not in x["name"]]
        hit_acct = [x for x in exp if any(s in x["name"] for s in NONDED_ACCT)]
        hit_who = [x for x in v if any(s in x["who"] or s in x["memo"] for s in NONDED_WHO)]
        if hit_acct or hit_who:
            e = (hit_acct or exp or v)[0]
            cand.append(f"| {k[0][5:]} {k[1]} | {e['name']} | {e['who'][:20]} | {e['memo'][:20]} | {e['dr']:,} | {adv:,} |")
    if cand:
        out += ["| 전표 | 계정 | 거래처 | 적요 | 공급가액 | 대급금 |", "|---|---|---|---|---|---|"] + cand
    else:
        out.append("후보 없음")
    nd = (R["forms"].get("불공제") or {})
    rows = [f"{c} {v[0]}매 {v[1]:,} / {v[2]:,}" for c, v in sorted(nd.items()) if c != "⑨" and any(v)]
    out += ["", "신고서 불공제명세: " + (", ".join(rows) if rows else "없음")]

    out += ["", "### B. 수출실적명세서 행 재계산 (외화 × 환율)", ""]
    ex = R["forms"].get("수출행", [])
    if ex:
        out += ["| 신고번호 | 선적일 | 통화 | 환율 | 외화 | 원화(신고) | 외화×환율 | 차이 |", "|---|---|---|---|---|---|---|---|"]
        for e in ex:
            calc = int(e["외화"] * e["환율"])
            out.append(f"| {e['신고번호']} | {e['선적일']} | {e['통화']} | {e['환율']:,} | {e['외화']:,.2f} "
                       f"| {e['원화']:,} | {calc:,} | {e['원화'] - calc:+,} |")
        out.append(f"장부의 예수금 없는 매출: " + ("; ".join(F["c_list"]) or "없음"))
    else:
        out.append("수출실적명세서 없음")

    out += ["", "### C. 공통매입세액 안분", ""]
    ran = R["ran"]
    S = lambda n: (ran.get(n) or (0, 0))[0] or 0
    taxfree = S(85) + S(86)
    total = S(9) + taxfree
    if taxfree:
        out.append(f"면세수입금액 (85)+(86) {taxfree:,} / 과세표준 (9) {S(9):,} + 면세 = 면세비율 {taxfree / total:.4%}")
        out.append("불공제명세서 3. 공통매입세액 안분계산명세: " + ("금액 있음" if R["forms"].get("공통안분") else "비어 있음"))
        out.append(f"계산서 매출 (89) {S(89):,} · 장부 면세 매출계정 대변(예수금 없는 매출) {F['c']:,}")
    else:
        out.append("면세수입금액 없음. 안분 대상 아님")

    out += ["", "### D. 확인필요 · 차이 항목", ""]
    for r in res:
        if r["verdict"] in (CHECK, UNREAD) or (r["diff"] not in (0, "", None) and r["verdict"] != NA):
            out.append(f"- {r['no']} {r['item']} [{r['verdict']}] 차이 {f(r['diff'])}: " + " / ".join(r["notes"][:4]))
    return "\n".join(out)


# ── 출력 ─────────────────────────────────────
def render(R, F, res, full):
    biz = R["biz"][0][1] if R["biz"] else ""
    biz = f"{biz[:3]}-{biz[3:5]}-{biz[5:]}" if len(biz) == 10 else biz
    per = next(((p, h) for pn, p, h in R["periods"] if pn == 1), ("", ""))
    pages = defaultdict(int)
    for k in R["pages"]:
        pages[k] += 1
    cnt = defaultdict(int)
    for r in res:
        cnt[r["verdict"].split("(")[0]] += 1
    head = [f"부가세 신고서 빠른 검토  {R['company'] or ''} {biz}  {per[1]} {R['kind'] or ''} ({per[0]})",
            f"읽은 서식 {len(R['pages'])}쪽: " + " ".join(f"{k}{v if v > 1 else ''}" for k, v in pages.items()),
            f"분개장 {F['lines']:,}줄 · 전표 {F['vouchers']:,}건      결과: "
            + " · ".join(f"{k} {cnt[k]}" for k in (PASS, CHECK, NA, UNREAD) if cnt[k]), "",
            "| # | 항목 | 신고서 | 대조값 | 차이 | 판정 |", "|---|---|---|---|---|---|"]
    for r in res:
        head.append(f"| {r['no']} | {r['item']} | {r['rep']} | {r['other']} | {f(r['diff'])} | {r['verdict']} |")
    det = []
    for r in res:
        ns = r["notes"] if r["verdict"] != PASS and not r["verdict"].startswith(PASS) else \
            [n for n in r["notes"] if n.startswith("(참고)") or "같음" in n]
        if not ns:
            continue
        show = ns if full else ns[:3]
        for n in show:
            det.append(f"{r['no']:>2}  {n}")
        if len(ns) > len(show):
            det.append(f"    외 {len(ns) - len(show)}건")
    if det:
        head += ["", "확인필요 · 참고"] + det
    return "\n".join(head)


def find_inputs(args):
    xs = [a for a in args if a.lower().endswith((".xlsx", ".xlsm"))]
    ps = [a for a in args if a.lower().endswith(".pdf")]
    for a in args:
        if os.path.isdir(a):
            xs += [p for p in glob.glob(os.path.join(a, "**", "*.xls*"), recursive=True)
                   if not os.path.basename(p).startswith("~$")]
            ps += glob.glob(os.path.join(a, "**", "*.pdf"), recursive=True)
    if len(xs) != 1 or len(ps) != 1:
        print("분개장 xlsx 1개와 신고서 pdf 1개가 필요합니다.")
        print("xlsx:", *xs, sep="\n  ")
        print("pdf:", *ps, sep="\n  ")
        sys.exit(2)
    return xs[0], ps[0]


def main(argv):
    sys.stdout.reconfigure(encoding="utf-8")
    md = None
    ai = "--ai" in argv
    argv = [a for a in argv if a != "--ai"]
    if "--md" in argv:
        i = argv.index("--md")
        md = argv[i + 1]
        argv = argv[:i] + argv[i + 2:]
    xlsx, pdf = find_inputs(argv)
    lines, footer = read_ledger(xlsx)
    F = ledger_facts(lines)
    try:
        R = read_return(pdf)
    except ImportError:
        raise SystemExit("PyMuPDF 가 없습니다. pip install pymupdf")
    if not R["ran"] and "본지1" not in R["pages"]:
        print("신고서 PDF 에서 글자를 못 읽었습니다. 스캔본이면 원본 PDF 를 다시 출력해 주세요.")
    res = review(lines, F, footer, R)
    print(render(R, F, res, full=False))
    extra = ai_material(lines, F, R, res) if ai else ""
    if extra:
        print(extra)
    if md:
        with open(md, "w", encoding="utf-8") as fp:
            fp.write(f"입력: {os.path.basename(xlsx)} · {os.path.basename(pdf)}\n\n")
            fp.write(render(R, F, res, full=True) + "\n" + extra + "\n")
        print(f"\nmd: {md}")


if __name__ == "__main__":
    main(sys.argv[1:])
