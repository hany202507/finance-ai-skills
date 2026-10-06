# -*- coding: utf-8 -*-
"""글로우빔 원천(dict 목록) → 결산 엔진이 읽는 raw 엑셀 8종.

CSV · 엑셀 로더(close_folder.py)가 build_raw 를 부른다.
매출은 정산서·인보이스에서 총액으로 잡고 통장 입금은 채권 회수로만 쓴다. 수출은 영세(ZERO).
"""
import os, re, io, csv, sys, calendar, openpyxl


def period_range(period):
    """기간 문자열 해석 규칙. 다른 진입점은 import 시 stdout 을 바꿔 pytest 아래에서
    깨지므로 여기 따로 둔다."""
    p = str(period).strip()
    m = re.fullmatch(r"(\d{4})Q([1-4])", p)
    if m:
        y, q = int(m.group(1)), int(m.group(2)); m1, m2 = q * 3 - 2, q * 3
    elif re.fullmatch(r"(\d{4})H([12])", p):
        y, h = int(p[:4]), int(p[-1]); m1, m2 = (1, 6) if h == 1 else (7, 12)
    elif re.fullmatch(r"(\d{4})-(\d{2})", p):
        y, m1 = int(p[:4]), int(p[5:7]); m2 = m1
    else:
        raise SystemExit(f"기간 라벨을 못 읽었습니다: {period}")
    last = calendar.monthrange(y, m2)[1]
    oy, om = (y - 1, 12) if m1 == 1 else (y, m1 - 1)
    return (f"{y}-{m1:02d}-01", f"{y}-{m2:02d}-{last}", f"{y}-{m1:02d}", f"{y}-{m2:02d}",
            f"{oy}-{om:02d}-{calendar.monthrange(oy, om)[1]}")


# 통장 적요 → (계정 라벨, 거래처 라벨). 앞에서부터 처음 맞는 것
BANK_LABEL = [
    (r"^(SWIFT|WIRE|T/T|PAYPAL|해외송금) ", "매출채권회수", "해외바이어"),
    (r"쿠팡\(주\) 정산",           "매출채권회수", "쿠팡"),
    (r"네이버파이낸셜\(주\) 정산",   "매출채권회수", "네이버"),
    (r"\(주\)지마켓 정산",          "매출채권회수", "지마켓"),
    (r"씨제이올리브영\(주\) 대금",   "매출채권회수", "올리브영"),
    (r"카페24\(주\) 정산",          "매출채권회수", "카페24"),
    (r"틱톡샵 정산",               "매출채권회수", "틱톡샵"),
    (r"^급여 ",                    "급여",        "임직원"),
    (r"^인플루언서 협찬 ",          "협찬(개인)",   "인플루언서"),
    (r"법인카드 정산",              "신용카드대금", "법인카드"),
    (r"(원료대금|제품매입|부자재대금)$", "매입대금결제", "다수(매입처)"),
    (r"(운임|특송|보관료|FEDEX|DHL|풀필먼트|통관|택배비)", "매입대금결제", "다수(매입처)"),
    (r"(구글애즈|검색광고|메타 광고|유튜브 광고|카카오모먼트|틱톡 포 비즈니스)", "매입대금결제", "다수(매입처)"),
    (r"(ASP|구독료|위하고|AWS|PG수수료|카드가맹 수수료|특허|법무사)", "매입대금결제", "다수(매입처)"),
    (r"(오피스넥스|간식비|전기요금|수도요금|건물관리비|통신요금|^임차료)", "매입대금결제", "다수(매입처)"),
    (r"(여행자보험|단체상해보험)",   "보험료",      "보험사"),
    (r"^출장비",                   "출장비",      "임직원"),
    (r"(국민연금공단|국민건강보험공단|근로복지공단|원천세 납부)", "4대보험", "공단/세무서"),
    (r"법인세 납부",               "법인세납부",   "세무서"),
    (r"대출 실행",                 "차입실행",     "기업은행"),
    (r"대출이자",                  "이자비용",     "기업은행"),
    (r"취득",                     "자산취득",     "비품매입처"),
]
PLATFORM_CODE = {"쿠팡": "COUPANG", "네이버": "NAVER", "지마켓": "GMARKET",
                 "올리브영": "OLIVEYOUNG", "카페24": "CAFE24", "틱톡샵": "TIKTOK"}
CARD_ISSUER = "기업BC"


def to_i(x):
    return int(float(x)) if x not in ("", None) else 0


def digits(biz):
    return re.sub(r"\D", "", str(biz or ""))


# 신규 거래의 성격을 적요가 스스로 설명하는 토큰. 이게 있으면 사람이 안 봐도 계정이 선다.
# 없으면 전기에 같은 거래가 있었을 때만 그 방식을 승계한다
설명토큰 = re.compile(r"^(SWIFT|WIRE|T/T|PAYPAL) |(원료대금|제품매입|부자재대금)$")


def 뼈대(memo):
    """숫자를 지운 적요의 모양. 거래처 이름이 달라도 같은 종류인지 보려는 것이다."""
    return re.sub(r"\s+", " ", re.sub(r"\d+", "#", str(memo or ""))).strip()


def 미분류인가(memo, 전기모양):
    """전기에 없던 거래인데 적요가 성격을 설명하지도 않으면 전문가가 볼 것이다.

    전기에 있던 거래는 그때 정한 방식이 있으므로 토큰이 없어도 승계한다.
    전기 자료가 없으면(첫 달) 판정할 근거가 없으니 미분류로 몰지 않는다.
    """
    if not 전기모양:
        return False
    if 뼈대(memo) in 전기모양:
        return False
    return not 설명토큰.search(str(memo or ""))


def label(memo):
    for pat, lab, party in BANK_LABEL:
        if re.search(pat, memo):
            return lab, party
    return "", ""


def _save(out, name, header, rows):
    wb = openpyxl.Workbook(); ws = wb.active; ws.append(header)
    for r in rows:
        ws.append(r)
    wb.save(os.path.join(out, name))
    return len(rows)


def _in(dstr, f, t):
    return f <= str(dstr)[:10] <= t


def build_raw(out, src, period):
    """src 의 각 표에서 period 안의 행만 골라 raw 8종을 쓴다."""
    os.makedirs(out, exist_ok=True)
    f, t, ym1, ym2, open_d = period_range(period)
    n = {}

    rows = []
    for r in src["opening"]:
        if str(r["기준일"])[:10] != open_d:
            continue
        amt = to_i(r["기초잔액"]); asset = r["구분"] == "자산"
        dr, cr = (amt, 0) if asset else (0, amt)
        if amt < 0:
            dr, cr = (0, -amt) if asset else (-amt, 0)
        rows.append([open_d, "전기이월", int(r["계정코드"]), r["계정과목"], dr, cr, "", f"전기이월({open_d})", ""])
    if not rows:
        raise SystemExit(f"기초잔액 {open_d} 이 없습니다")
    n["opening"] = _save(out, "00_전기이월분개장.xlsx",
                         ["일자", "구분", "계정코드", "계정", "차변", "대변", "거래처", "적요", "관리적요"], rows)

    rows = []
    for r in sorted(src["payroll"], key=lambda r: (r["귀속연월"], r["사번"])):
        if not (ym1 <= r["귀속연월"] <= ym2):
            continue
        tot = to_i(r["기본급"]) + to_i(r["수당"])
        ded = sum(to_i(r[k]) for k in ("국민연금", "건강보험", "장기요양", "고용보험", "소득세", "지방소득세"))
        rows.append([r["귀속연월"], r["사번"], r["성명"], r["소득구분"], to_i(r["기본급"]), to_i(r["비과세"]), tot,
                     to_i(r["국민연금"]), to_i(r["건강보험"]), to_i(r["장기요양"]), to_i(r["고용보험"]),
                     to_i(r["소득세"]), to_i(r["지방소득세"]), ded, to_i(r["실지급액"])])
    n["payroll"] = _save(out, "02_급여대장.xlsx",
                         ["귀속월", "사번", "성명", "직무", "기본급", "식대(비과세)", "총지급액", "국민연금", "건강보험",
                          "장기요양", "고용보험", "소득세", "지방소득세", "공제합계", "실지급액"], rows)

    # 대상 기간 앞의 거래로 '전기에 있던 모양'을 만든다. 이게 규칙 승계의 근거다
    전기모양 = {뼈대(r["적요"]) for r in src["bank"] if str(r["거래일자"])[:10] < f}

    rows, unmapped, 미분류수 = [], {}, 0
    for r in sorted(src["bank"], key=lambda r: to_i(r["일련번호"])):
        if not _in(r["거래일자"], f, t):
            continue
        lab, party = label(r["적요"])
        if 미분류인가(r["적요"], 전기모양):
            # 규칙에 걸려도 신규 거래면 전문가가 본다. 임의로 기표하지 않는다
            lab, party, 미분류수 = "미분류", "미확인", 미분류수 + 1
        if not lab:
            unmapped[r["적요"]] = unmapped.get(r["적요"], 0) + 1
        i_, o_ = to_i(r["입금액"]), to_i(r["출금액"])
        rows.append([str(r["거래일자"])[:10], r["계좌"], i_ or None, o_ or None, r["적요"],
                     "입금" if i_ else "출금", lab, party])
    n["bank"] = _save(out, "03_은행거래내역.xlsx",
                      ["거래일시", "계좌별칭", "입금", "출금", "적요", "거래구분", "계정 라벨", "거래처 라벨"], rows)
    if unmapped:
        print("  ! 라벨 미매칭 적요:", unmapped)
    if 전기모양:
        print(f"     미분류        {미분류수:>5}행  (전기에 없고 적요가 성격을 설명하지 않는 건)")

    rows = [[str(r["승인일"])[:10], CARD_ISSUER, r["카드번호"], r["가맹점명"], r["업종"],
             digits(r["사업자번호"]), to_i(r["승인금액"]), 0]
            for r in sorted(src["card"], key=lambda r: (r["승인일"], r["승인시각"])) if _in(r["승인일"], f, t)]
    n["card"] = _save(out, "04_카드승인내역.xlsx",
                      ["승인일시", "카드사", "카드번호", "가맹점명", "가맹점 업종", "가맹점 사업자번호",
                       "승인금액(원)", "취소금액(원)"], rows)

    rows = [[str(r["작성일자"])[:10], r["매출매입구분"], "일반", r["상호"], digits(r["사업자번호"]), r["품목"],
             to_i(r["공급가액"]), to_i(r["부가세"]), to_i(r["합계금액"]), ""]
            for r in sorted(src["tax"], key=lambda r: (r["작성일자"], r["승인번호"])) if _in(r["작성일자"], f, t)]
    n["tax"] = _save(out, "05_세금계산서.xlsx",
                     ["작성일자", "매출매입", "과세유형", "거래처상호", "거래처사업자번호", "대표품목",
                      "공급가액", "세액", "합계금액", "입금예정일"], rows)

    # 채널매출: 플랫폼별·월별 판매총액(과세), 수출 월별 원화(영세). 거래성격은 전부 직판
    agg = {}
    for r in src["settlements"]:
        if not _in(r["정산일"], f, t):
            continue
        k = (str(r["정산일"])[:7], PLATFORM_CODE[r["플랫폼"]], r["플랫폼"], "TAXABLE", r["플랫폼"])
        a = agg.setdefault(k, [0, 0]); a[0] += 1; a[1] += to_i(r["판매총액"])
    for r in src["exports"]:
        if not _in(r["인보이스일"], f, t):
            continue
        k = (str(r["인보이스일"])[:7], "EXPORT", "수출", "ZERO", "해외바이어")
        a = agg.setdefault(k, [0, 0]); a[0] += 1; a[1] += to_i(r["원화금액"])
    rows = [[ym, ch, chname, "직판", kind, "NONE", "", cnt, amt, amt, 0, party]
            for (ym, ch, chname, kind, party), (cnt, amt) in sorted(agg.items())]
    n["channel"] = _save(out, "06_채널매출.xlsx",
                         ["인식월", "채널", "채널명", "거래성격", "과세구분", "할인유형", "사은품구분",
                          "건수", "대가총액", "정가총액", "할인액", "거래처라벨"], rows)

    fee = {}
    for r in src["settlements"]:
        if not _in(r["정산일"], f, t):
            continue
        k = (str(r["정산일"])[:7], r["플랫폼"]); fee[k] = fee.get(k, 0) + to_i(r["판매수수료"])
    rows = [[ym, PLATFORM_CODE[pf], "판매수수료상계", pf, amt, pf] for (ym, pf), amt in sorted(fee.items()) if amt]
    n["settle"] = _save(out, "07_정산차감.xlsx", ["인식월", "채널", "항목", "상대처", "금액", "거래처라벨"], rows)

    rows = [[r["더존거래처코드"], r["상호"], r["유형"], digits(r["사업자번호"]), r.get("비고", "")]
            for r in src["partners"]]
    n["partners"] = _save(out, "거래처마스터.xlsx",
                          ["거래처코드", "거래처명", "구분", "사업자(주민)등록번호", "비고"], rows)
    return n


CSV_FILES = {"bank": "bank_transactions.csv", "card": "card_approvals.csv", "partners": "partners.csv",
             "settlements": "platform_settlements.csv", "exports": "export_invoices.csv",
             "tax": "tax_invoices.csv", "payroll": "payroll.csv", "opening": "opening_balance.csv"}


def _read_table(path):
    """엑셀이든 CSV 든 dict 목록으로 읽는다. 엑셀은 끝 빈 칸이 잘려 오므로 채운다."""
    if path.lower().endswith(".xlsx"):
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        it = wb.active.iter_rows(values_only=True)
        head = [str(c).strip() for c in next(it) if c is not None]
        out = []
        for r in it:
            if r is None:
                continue
            vals = list(r[:len(head)]) + [None] * max(0, len(head) - len(r))
            out.append({h: ("" if v is None else str(v)) for h, v in zip(head, vals)})
        return out
    with io.open(path, encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def load_csv_tables(kit_dir):
    """폴더에서 표 여덟 벌을 읽는다. 같은 이름이 엑셀과 CSV 로 둘 다 있으면 엑셀을 쓴다."""
    src = {}
    for k, name in CSV_FILES.items():
        stem = os.path.splitext(name)[0]
        xlsx = os.path.join(kit_dir, stem + ".xlsx")
        path = xlsx if os.path.exists(xlsx) else os.path.join(kit_dir, name)
        if not os.path.exists(path):
            raise SystemExit(f"표가 없습니다: {stem}")
        src[k] = _read_table(path)
    return src


if __name__ == "__main__":
    # python glowbeam_raw.py <kit_dir> <out_dir> <기간>
    kit, out, period = sys.argv[1:4]
    sys.stdout.reconfigure(encoding="utf-8")
    for k, v in build_raw(out, load_csv_tables(kit), period).items():
        print(f"  {k:<10} {v:>6}행")
