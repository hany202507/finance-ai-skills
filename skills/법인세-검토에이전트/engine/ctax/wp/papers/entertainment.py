"""6 기업업무추진비: 신용카드 등 미사용액 · 한도초과 손금불산입(기타사외유출). 23호(갑)(을).

증빙 종류(2026-10-29 이정아 회계사 기준): 건당 기준 금액(3만원, 경조사비 20만원)을 넘는 지출 가운데 신용카드 등으로 확인되지
않는 줄은 작성자가 노란 칸 「증빙 종류」(EVIDENCE_KINDS)를 고른다. 「없음」 을 고른 줄만 신용카드 등 미사용액으로 손금불산입한다.
고르지 않은 줄은 확인 줄로 남기고 미사용액에 넣지 않는다(계정 · 결제수단으로 미사용을 추정하지 않는다). 세금계산서를 받은 지출도
있어 일괄 판정하지 않는다. 계정별 서식 23호(을)(`ctax/acct/calc.py`)도 같은 칸(`_색인/조서입력.json`)을 읽고 같은 함수로 판정한다.
"""
from __future__ import annotations

import re
from fractions import Fraction

from ..books import Books, frac, rate, rd
from ..model import MISSING, Adj, LineRow, Paper, line_keys, subject_of
from ..sheet import Book, Rows, adj_table, forms_table, head, ledger, lines_dry, notes, verify, verify_rows

NAME = "기업업무추진비"
FORMS = ["23갑", "23을"]
LEDGER_CHECK = True
PICK = "증빙 종류"
OLD_PICK = "부인 여부"              # 10-29 전 노란 칸(O 부인 · X 시인). 그 값이 남아 있으면 O → 없음, X → 있음 으로 읽는다
NONE = "없음"
# 경조사비(20만원 기준): 계정별 서식과 같은 말 목록. 적요 · 거래처를 본다
GIFT = re.compile(r"경조|축의|조의|부의|부조|화환|조화|근조|조문|결혼|장례|상조|빙모|빙부|모친상|부친상|조모상|조부상")
# 적격증빙(법인세법 제25조 제2항 · 시행령 제41조): 신용카드 등(직불 · 기명식 선불카드 포함) · 현금영수증 · 세금계산서 · 계산서 ·
# 원천징수영수증. 「없음」 만 미사용이다. 「있음」 은 10-29 전 값(종류를 적지 않은 적격증빙)으로 읽기만 한다
EVIDENCE_KINDS = ("신용카드 등", "현금영수증", "세금계산서", "계산서", "원천징수영수증", NONE)
NOT_NEEDED = "고를 필요 없음"      # 기준 금액 이하 · 취소 줄
_ALIAS = {"카드": "신용카드 등", "신용카드": "신용카드 등", "체크카드": "신용카드 등", "직불카드": "신용카드 등",
          "법인카드": "신용카드 등", "전자세금계산서": "세금계산서", "전자계산서": "계산서", "원천징수": "원천징수영수증",
          "무": NONE, "미수취": NONE, "증빙없음": NONE, "있음": "있음"}
# 23호(갑) ⑨ 문화 · ⑪ 전통시장 · ⑫ 지역사랑상품권 · ⑬ 온누리상품권 기업업무추진비 지출액(노란 칸 key = values key)
SPENT = ("문화 지출액", "전통시장 지출액", "지역사랑상품권 지출액", "온누리상품권 지출액")
# 온누리상품권은 법률 제21612호 시행일(2026-05-12)이 속하는 과세연도 지출분부터 ⑭ 한도에 넣는다(조특법 제136조 제6항 · 부칙 제4조).
# 그 날이 속하는 12개월 사업연도는 개시일이 2025-05-13 이후다. 2025 표(값 0)를 쓰는 사업연도라도 개시일이 이 날 이후면 1 이다.
# 서식 쪽 params 「접대비.온누리상품권적용」 과 같은 기준(개시일)이다. 12개월이 안 되는 사업연도는 확인 줄로 사람이 본다
ONNURI_LAW_START = "2026-05-12"
ONNURI_FROM = "2025-05-13"


def onnuri_item(rates: dict, fy_start: str | None) -> dict:
    """이 사업연도의 「온누리상품권 한도 적용(1 · 0)」 항목 {value, basis, grade}. 표 값이 0 이어도 개시일이 ONNURI_FROM 이후면 1."""
    item = rates["entertainment"]["onnuri_applies"]
    start = str(fy_start or "")
    if item["value"] or start < ONNURI_FROM:
        return item
    return {"value": 1, "grade": "★★★",
            "basis": f"조세특례제한법 제136조 제6항 (온누리상품권을 더함, 법률 제21612호 2026.5.12 공포 · 시행) · 부칙(법률 제21612호) "
                     f"제4조 「이 법 시행일이 속하는 과세연도에 지출하는 분부터」. 사업연도 개시일 {start} 이 {ONNURI_FROM} 이후라 "
                     "12개월 사업연도에 2026.5.12 이 속한다(2026-11-03 TaxDoctor · korean-law 원문 · 부칙)"}


def basis(rates: dict) -> list[tuple]:
    ent = rates["entertainment"]
    rows = [("기업업무추진비 기본한도(중소기업)", ent["base_sme"]["value"], ent["base_sme"]["basis"], ent["base_sme"]["grade"], None),
            ("기업업무추진비 기본한도(일반)", ent["base_general"]["value"], ent["base_general"]["basis"], ent["base_general"]["grade"], None)]
    for i, (cap, rt) in enumerate(ent["revenue_tiers"]["value"], start=1):
        if cap is not None:
            rows.append((f"수입금액 구간{i} 상한", cap, ent["revenue_tiers"]["basis"], ent["revenue_tiers"]["grade"], None))
        rows.append((f"수입금액 구간{i} 비율", rt, ent["revenue_tiers"]["basis"], ent["revenue_tiers"]["grade"], "0.00%"))
    rows.append(("특수관계인 수입금액 비율", ent["related_party_ratio"]["value"], ent["related_party_ratio"]["basis"],
                 ent["related_party_ratio"]["grade"], "0%"))
    rows.append(("부동산임대업 주업 한도 비율", ent["real_estate_ratio"]["value"], ent["real_estate_ratio"]["basis"],
                 ent["real_estate_ratio"]["grade"], "0%"))
    for name, key, fmt in (("문화 기업업무추진비 한도율", "culture_ratio", "0%"),
                           ("전통시장 등 기업업무추진비 한도율", "market_ratio", "0%"),
                           ("온누리상품권 한도 적용(1 · 0)", "onnuri_applies", "0")):
        rows.append((name, ent[key]["value"], ent[key]["basis"], ent[key]["grade"], fmt))
    return rows


def tier_limit(revenue: int, tiers) -> int:
    """수입금액 기준 한도(법인세법 제25조 제4항 제2호 표)."""
    (c1, r1), (c2, r2), (_, r3) = tiers
    x = max(revenue, 0)
    if x <= c1:
        v = x * frac(r1)
    elif x <= c2:
        v = c1 * frac(r1) + (x - c1) * frac(r2)
    else:
        v = c1 * frac(r1) + (c2 - c1) * frac(r2) + (x - c2) * frac(r3)
    return rd(v)


def _squash(v) -> str:
    return re.sub(r"\s", "", str(v if v is not None else ""))


def norm_evidence(v) -> str | None:
    """노란 칸 값을 EVIDENCE_KINDS(또는 옛 값 「있음」)로 맞춘다. 비었으면 "", 읽지 못하면 None."""
    t = _squash(v)
    if not t:
        return ""
    for k in EVIDENCE_KINDS:
        if t == _squash(k):
            return k
    return _ALIAS.get(t)


def is_unused(kind: str | None) -> bool:
    """신용카드 등 미사용으로 손금불산입하는 줄인가. 「없음」 을 고른 줄만이다."""
    return kind == NONE


def evidence_default(ln, voucher: list, acct_name: str) -> tuple[str, str]:
    """기준 금액을 넘는 줄의 증빙 종류 기본값과 까닭. 신용카드 등으로 확인되면 「신용카드 등」, 적요 · 거래처에 증빙 이름이
    적혀 있으면 그 종류, 확인되지 않으면 빈 글(작성자가 고른다). 계정 · 결제수단으로 미사용을 추정하지 않는다.
    조서와 계정별 서식(acct.calc)이 같이 쓴다."""
    if "카드" in (acct_name or ""):
        return "신용카드 등", "카드 계정"
    text = f"{ln.partner or ''} {ln.memo or ''}"
    if "카드" in text:
        return "신용카드 등", "적요 · 거래처에 카드 표시"
    for word in ("현금영수증", "세금계산서", "계산서"):
        if word in text:
            return word, f"적요 · 거래처에 {word} 표시"
    cr = [o for o in voucher if o is not ln and o.credit > 0]
    if any("카드" in (o.account_name or "") or "카드" in (o.partner or "") for o in cr):
        return "신용카드 등", "카드 대금으로 지급"
    if any(("미지급" in (o.account_name or "") or "외상매입" in (o.account_name or "")) and o.partner for o in cr):
        return "", "거래처 미지급금으로 지급. 세금계산서 · 계산서를 받았는지 확인해 고르세요"
    if ln.kind == "출금":
        return "", "현금 출금 전표. 증빙 종류를 고르세요(없으면 「없음」)"
    return "", "계좌이체 등, 증빙 표시 없음. 증빙 종류를 고르세요(없으면 「없음」)"


def choose_evidence(default: str, *values) -> tuple[str, str]:
    """(쓴 증빙 종류, 출처). values 는 (출처, 회계사 값) 후보를 앞선 순서로. 비었거나 읽지 못한 값은 건너뛴다."""
    for src, v in values:
        k = norm_evidence(v)
        if k:
            return k, src
    return default, "기본"


def evidence_choice(overrides, key: str, default: str) -> tuple[str, str, object]:
    """조서입력.json 의 이 줄 값으로 고른 증빙 종류. (값, 출처, 읽지 못한 원래 값 또는 None).
    overrides 는 key → 값을 돌려주는 함수(없으면 MISSING). 조서와 계정별 서식이 같이 쓴다."""
    got = overrides(f"{PICK}/{key}")
    old = overrides(f"{OLD_PICK}/{key}")
    legacy = {"O": NONE, "X": "있음"}.get(str(old).strip().upper()) if old is not MISSING else None
    kind, src = choose_evidence(default, (PICK, None if got is MISSING else got), (OLD_PICK, legacy))
    bad = got if got is not MISSING and _squash(got) and norm_evidence(got) is None else None
    return kind, src, bad


ESTATE = "부동산임대업 주업"
# 노란 칸에 적을 수 있는 말. 「여」 로 읽는 말은 엑셀 ⑧ 수식(OR)과 같아야 한다
ESTATE_YES = ("여", "예", "Y", "O")
ESTATE_ALIAS = {**{k: "여" for k in ESTATE_YES}, **{k: "부" for k in ("부", "아니오", "아니요", "N", "X")}}
RELATED = "특수관계인 수입금액"


def answered(p: Paper, b: Books, key: str) -> bool:
    """회계사가 이 노란 칸에 답했는가. 값을 바꿨거나, 기본값 그대로 두고 「회계사 답」 시트에 메모 · 근거를 적었으면 답이다."""
    return b.override(p.id, key) is not MISSING or (p.id, key) in (b.answers or {})


def estate_choice(p: Paper, b: Books) -> tuple[bool, dict]:
    """부동산임대업 주업 여부(법인세법 제25조 제5항 · 시행령 제42조 제2항). 기본값은 업무용승용차 조서와 같은 근거
    (`business_car.estate_judge`, 17호 업종코드)이고, 업무용승용차 조서 노란 칸에 회계사 값이 있으면 그 값이다. 없으면 「부」."""
    from .business_car import ESTATE as CAR_ESTATE, estate_judge
    info = estate_judge(b)
    car = b.override("business_car", CAR_ESTATE)
    car = ESTATE_ALIAS.get(str(car).strip().upper()) if car is not MISSING else None
    default = car or info["default"]
    raw = p.take(b, ESTATE, default)
    value = ESTATE_ALIAS.get(str(raw).strip().upper())
    info.update({"default": default, "raw": raw, "value": value or "부", "unread": value is None and bool(str(raw).strip()),
                 "from_car": car is not None, "answered": answered(p, b, ESTATE)})
    return info["value"] == "여", info


def _estate_messages(p: Paper, b: Books, info: dict, before: int, after: int) -> None:
    law = "법인세법 제25조 제5항 · 시행령 제42조 제2항"
    cut = f"⑧ 일반 한도 {before:,}원의 50% {after:,}원"
    if info["unread"]:
        p.confirm.append(f"노란 칸 「{ESTATE}」 값 「{info['raw']}」 을 읽지 못해 「부」 로 계산했습니다(여 · 부)")
    elif info["answered"]:
        p.notes.append(f"{ESTATE}는 회계사 값 「{info['value']}」 로 계산했습니다" + (f"({cut}, {law})" if info["value"] == "여" else ""))
    elif info["from_car"]:
        p.notes.append(f"{ESTATE}는 업무용승용차 조서 노란 칸 값 「{info['value']}」 을 따랐습니다" +
                       (f"({cut}, {law})" if info["value"] == "여" else ""))
    elif not info["judged"]:
        p.confirm.append(f"조정후수입금액명세서(17호) 업종코드가 비어 {ESTATE} 여부를 판정하지 않고 「부」 로 계산했습니다. 부동산임대업이 "
                         "주된 사업이고 지배주주등 지분 50% 초과 · 상시근로자 5명 미만이면(시행령 제42조 제2항) 노란 칸 "
                         f"「{ESTATE}」 를 「여」 로 바꾸세요(한도의 50%, {law})")
    elif info["value"] == "여":
        p.confirm.append(f"{info['basis']}. {ESTATE}로 보아 {cut}를 한도로 썼습니다({law}). 지배주주등 지분 50% 초과 · 상시근로자 "
                         f"5명 미만 요건도 갖춰야 합니다. 갖추지 않았으면 노란 칸 「{ESTATE}」 를 「부」 로 바꾸세요")
    else:
        p.notes.append(f"{info['basis']}. 기업업무추진비 한도는 50% 로 줄이지 않았습니다(요건을 갖추면 노란 칸 「{ESTATE}」 를 「여」 로)")


def _related_messages(p: Paper, b: Books, related: int) -> None:
    """특수관계인 수입금액 노란 칸이 비어(0) 있을 때. 전기 23호(을) ② 특수관계인간 거래금액을 읽을 수 있으면 그 값과 견준다."""
    if related or answered(p, b, RELATED):
        return
    c23 = b.prior_cell_form("23을")
    law = "특수관계인 거래 수입금액은 한도 비율의 10%, 법인세법 제25조 제4항 제2호 단서"
    keep = "0 이 맞으면 「회계사 답」 시트에 근거를 적으세요"
    if not any(k in c23 for k in ("1", "2", "3")):
        p.confirm.append(f"특수관계인 매출이 있으면 노란 칸 「{RELATED}」 에 넣으세요. 전기 23호(을) ② 특수관계인간 거래금액을 읽지 못해 "
                         f"0 으로 계산했습니다({law}). {keep}")
        return
    try:
        prior_rel = int(round(float(str(c23.get("2") or 0).replace(",", ""))))
    except ValueError:
        prior_rel = 0
    if prior_rel:
        p.confirm.append(f"전기 23호(을) ② 특수관계인간 거래금액이 {prior_rel:,}원인데 당기 「{RELATED}」 노란 칸이 비어 0 으로 계산했습니다"
                         f"({law}). 당기 특수관계인 매출을 넣으세요. {keep}")
    else:
        p.notes.append("전기 23호(을) ② 특수관계인간 거래금액이 0원이라 당기 특수관계인 수입금액도 0 으로 두었습니다")


def compute(p: Paper, b: Books) -> None:
    accts = b.accounts(cls="비용", any_of=("접대비", "기업업무추진비"))
    p.accounts = accts
    g_lim = rate(b.rates, "entertainment", "card_threshold_general")
    gift_lim = rate(b.rates, "entertainment", "card_threshold_gift")
    vouchers: dict[tuple, list] = {}
    for x in b.all_lines():
        vouchers.setdefault((x.date, x.no), []).append(x)
    for ln in b.lines_of(accts):
        amt, text = ln.amount, ln.text
        gift = bool(GIFT.search(text))
        if amt <= 0:
            p.lines.append(LineRow(ln, "취소 · 음수 줄", NOT_NEEDED))
            continue
        if amt <= (gift_lim if gift else g_lim):
            p.lines.append(LineRow(ln, "경조금 20만원 이하" if gift else "3만원 이하", NOT_NEEDED))
            continue
        acct_name = ln.account_name or b.by_code.get(ln.account, {}).get("name", "")
        kind, why = evidence_default(ln, vouchers.get((ln.date, ln.no), []), acct_name)
        p.lines.append(LineRow(ln, "경조금 20만원 초과" if gift else "3만원 초과", kind, why=why))
    line_keys(p)
    unread = []
    for r in p.lines:
        r.default = r.pick
        if r.pick == NOT_NEEDED:
            continue
        r.pick, src, bad = evidence_choice(lambda k: b.override(p.id, k), r.key, r.pick)
        if bad is not None:
            unread.append((r, bad))
        if src != "기본" and r.pick != r.default:
            p.overridden[f"{PICK}/{r.key}"] = {"value": r.pick, "default": r.default}
        hint = b.suggest(p.id, f"{PICK}/거래처:{r.line.partner}") if r.pick == "" and r.line.partner else None
        if hint:   # 작년에 같은 거래처 줄에 고른 증빙(회사 맥락). 계정별 서식과 값이 같아야 해 칸은 채우지 않고 까닭에만 적는다
            r.why = f"{r.why}. 작년 답: {hint['value']}({hint.get('fy', '')} 사업연도, 확인 전)"
    total = sum(r.line.amount for r in p.lines)
    no_card = sum(r.line.amount for r in p.lines if is_unused(r.pick))
    open_rows = [r for r in p.lines if r.pick == ""]
    for r in p.lines:
        if r.default == "":
            r.default = None              # 엑셀에 빈 칸으로 쓰이므로 _입력 기본값도 빈 칸(None)으로 맞춘다
    sme = b.sme
    months = b.months
    base_amt = rate(b.rates, "entertainment", "base_sme" if sme else "base_general")
    base = rd(Fraction(base_amt * months, 12))
    revenue = p.take(b, "수입금액", int(b.totals.get("revenue") or 0), "int")
    related = p.take(b, RELATED, 0, "int")
    # 23호(갑) ⑨ · ⑪ · ⑫ · ⑬ 지출액은 장부 계정으로 가릴 수 없어 노란 칸(기본 0)
    spent = {k: p.take(b, k, 0, "int") for k in SPENT}
    tiers = rate(b.rates, "entertainment", "revenue_tiers")
    lim_total = tier_limit(revenue, tiers)
    lim_general = tier_limit(revenue - related, tiers)
    rev_limit = lim_general + rd((lim_total - lim_general) * frac(rate(b.rates, "entertainment", "related_party_ratio")))
    estate, estate_info = estate_choice(p, b)
    general0 = base + rev_limit                                                      # ④ + ⑥ + ⑦
    # 부동산임대업 주업 등은 제25조 제4항 각 호 합계의 100분의 50(같은 조 제5항, 23호(갑) ⑧). 문화 · 전통시장 한도는 이 ⑧ 의 20%
    general = rd(general0 * frac(rate(b.rates, "entertainment", "real_estate_ratio"))) if estate else general0   # ⑧
    culture = min(spent["문화 지출액"], rd(general * frac(rate(b.rates, "entertainment", "culture_ratio"))))   # ⑩
    onnuri = onnuri_item(b.rates, b.info.get("fy_start"))
    if onnuri is not b.rates["entertainment"]["onnuri_applies"]:
        # 이 사업연도에 맞춘 세율 표. 기준 시트 「온누리상품권 한도 적용(1 · 0)」 줄도 이 값을 쓴다(excel._basis)
        p.extra["rates"] = {**b.rates, "entertainment": {**b.rates["entertainment"], "onnuri_applies": onnuri}}
    onnuri_in = spent["온누리상품권 지출액"] * int(onnuri["value"])
    market = min(spent["전통시장 지출액"] + spent["지역사랑상품권 지출액"] + onnuri_in,
                 rd(general * frac(rate(b.rates, "entertainment", "market_ratio"))))   # ⑭
    limit = general + culture + market                                              # ⑮
    net = total - no_card
    excess = max(0, net - limit)
    # 「일반수입금액」 · 「특수관계인 수입금액」 은 23호(을) ① · ② 로 간다(forms/fill.fill_23 이 「수입금액」 이 든 첫 키를 ① 로 읽는다)
    p.values = {"해당금액": total, "신용카드미사용": no_card, "차감해당금액": net, "기본한도": base,
                "일반수입금액": revenue - related, "수입금액": revenue, RELATED: related, "수입금액기준한도": rev_limit,
                ESTATE: estate_info["value"], "부동산임대업 전 일반한도": general0, "일반한도": general, **spent,
                "문화한도": culture, "전통시장등한도": market, "한도": limit, "한도초과": excess,
                "손금산입한도내": min(net, limit),
                # 23호(을) ⑨ · ⑩(경조금 20만원 초과) · ⑮ · ⑯(그 밖 3만원 초과): 기준금액 초과 줄의 총액과 그중 증빙 「없음」
                "경조사비 기준금액 초과액": sum(r.line.amount for r in p.lines if r.label == "경조금 20만원 초과"),
                "경조사비 신용카드미사용": sum(r.line.amount for r in p.lines if r.label == "경조금 20만원 초과" and is_unused(r.pick)),
                "기준금액 초과액": sum(r.line.amount for r in p.lines if r.label == "3만원 초과"),
                "기준금액 초과 신용카드미사용": sum(r.line.amount for r in p.lines if r.label == "3만원 초과" and is_unused(r.pick))}
    subj = subject_of(accts, "기업업무추진비")
    p.adjustments = [
        Adj("가산", subj, no_card, "기타사외유출", "기업업무추진비 신용카드 미사용",
            "기업업무추진비 신용카드 등 미사용액 손금불산입", "신용카드미사용"),
        Adj("가산", subj, excess, "기타사외유출", "기업업무추진비 한도초과", "기업업무추진비 한도초과액 손금불산입", "한도초과"),
    ]
    p.values["증빙 미선택"] = sum(r.line.amount for r in open_rows)
    p.values["증빙 미선택 건수"] = len(open_rows)
    if open_rows:
        p.confirm.append(f"기준 금액(3만원, 경조사비 20만원)을 넘는 지출 {len(open_rows)}건 {p.values['증빙 미선택']:,}원은 신용카드 등으로 "
                         f"확인되지 않았고 증빙 종류를 고르지 않아 신용카드 등 미사용액에 넣지 않았습니다. 노란 칸 「{PICK}」 에서 "
                         f"{' · '.join(EVIDENCE_KINDS)} 중 하나를 고르세요(「{NONE}」 만 손금불산입)")
    for r, v in unread:
        p.confirm.append(f"{r.line.date} 전표 {r.line.no} 「{PICK}」 값 「{v}」 을 읽지 못해 기본값으로 두었습니다"
                         f"({' · '.join(EVIDENCE_KINDS)})")
    p.notes.append("한도 계산의 수입금액은 손익계산서 매출액을 썼습니다")
    if total or accts:
        _related_messages(p, b, related)
        _estate_messages(p, b, estate_info, general0, general)
    if not any(spent.values()):
        p.notes.append("문화 · 전통시장 · 지역사랑상품권 · 온누리상품권 기업업무추진비 지출액은 장부로 가릴 수 없어 0 으로 두었습니다"
                       "(조특법 제136조 제3항 · 제6항, 해당하면 노란 칸에 지출액을 넣으세요)")
    if spent["온누리상품권 지출액"] and not onnuri_in:
        p.confirm.append("온누리상품권 기업업무추진비는 2026.5.12 이 속하는 과세연도 지출분부터 한도에 더합니다(법률 제21612호 부칙 제4조)."
                         " 이 사업연도 한도 계산에서는 뺐습니다(23호(갑) ⑬ 에는 적음)")
    if spent["온누리상품권 지출액"] and onnuri_in and months < 12:
        # 12개월이 안 되는 사업연도는 개시일만으로 시행일이 속하는지 알 수 없다(월수가 12 미만이면 개시일 · 종료일이 다 있다).
        # 종료일이 시행일 앞이면 그 사업연도는 적용 전이라 확인 줄에 올린다. 값은 서식(params)과 같게 개시일 기준으로 둔다
        start, end = str(b.info.get("fy_start") or ""), str(b.info.get("fy_end") or "")
        msg = (f"사업연도({start} ~ {end})가 {months}개월이라 온누리상품권 한도 적용(1)을 개시일로만 정했습니다. 온누리상품권 "
               "기업업무추진비는 2026.5.12 이 속하는 과세연도 지출분부터 한도에 더합니다(법률 제21612호 부칙 제4조)")
        if end >= ONNURI_LAW_START:
            p.notes.append(f"{msg}. 종료일이 2026.5.12 이후라 한도에 넣었습니다")
        else:
            p.confirm.append(f"{msg}. 종료일이 2026.5.12 앞이라 이 사업연도는 ⑬ 을 ⑭ 한도에서 빼야 합니다. 늘어나는 한도초과액을 "
                             "15호 「직접 조정」 줄에 넣으세요")
    if sum(spent.values()) > net:
        p.confirm.append(f"문화 · 전통시장 등 지출액 합계 {sum(spent.values()):,}원이 ③ 차감 해당금액 {net:,}원보다 큽니다"
                         "(23호(갑) 작성방법 4 · 5: ③ 가운데 지출액)")
    if not b.sme_known:
        p.confirm.append("전기 신고서에서 중소기업 여부를 읽지 못해 중소기업으로 보았습니다")
    p.settle(bool(total or accts))


def _tier(x: str, c1: str, r1: str, c2: str, r2: str, r3: str) -> str:
    return (f"ROUNDDOWN(IF({x}<={c1},{x}*{r1},IF({x}<={c2},{c1}*{r1}+({x}-{c1})*{r2},"
            f"{c1}*{r1}+({c2}-{c1})*{r2}+({x}-{c2})*{r3})),0)")


def write(bk: Book, p: Paper) -> None:
    s = head(bk, p)
    row = 5
    _, first, last = lines_dry(p, row + verify_rows(p))
    row = verify(bk, s, row, p, first, last)
    row, first, last = ledger(bk, s, row, p, PICK, kind="text")
    R = bk.ref
    row = s.section(row, "3. 한도 시부인")
    r = Rows(bk, s, p, row)
    g = r.g
    r.put("해당금액", "① 기업업무추진비 해당금액", f"=SUM(G{first}:G{last})")
    r.put("신용카드미사용", f"② 신용카드 등 미사용액(증빙 종류 「{NONE}」)", f'=SUMIFS(G{first}:G{last},I{first}:I{last},"{NONE}")')
    r.put("차감해당금액", "③ 차감 해당금액(① - ②)", f"={g('해당금액')}-{g('신용카드미사용')}")
    r.put("월수", "사업연도 월수", f"={R['사업연도 월수']}", fmt="0")
    r.put("기본한도", "④ 기본한도(중소기업 3,600만원 · 일반 1,200만원 × 월수/12)",
          f'=ROUNDDOWN(IF({R["중소기업 여부"]}="여",{R["기업업무추진비 기본한도(중소기업)"]},{R["기업업무추진비 기본한도(일반)"]})*{g("월수")}/12,0)')
    r.put("수입금액", "수입금액(손익계산서 매출액)", p.inputs["수입금액"], kind="input", input_kind="int")
    r.put(RELATED, "특수관계인 수입금액(23호(을) ②)", p.inputs[RELATED], kind="input", input_kind="int")
    r.put("일반수입금액", "일반 수입금액", f"={g('수입금액')}-{g('특수관계인 수입금액')}")
    t = (R["수입금액 구간1 상한"], R["수입금액 구간1 비율"], R["수입금액 구간2 상한"], R["수입금액 구간2 비율"], R["수입금액 구간3 비율"])
    r.put("총수입금액기준", "⑤ 총수입금액 기준", "=" + _tier(g("수입금액"), *t))
    r.put("일반수입금액기준", "⑥ 일반수입금액 기준", "=" + _tier(g("일반수입금액"), *t))
    r.put("수입금액기준한도", "수입금액 기준 한도(⑥ + (⑤ - ⑥) × 10%)",
          f"={g('일반수입금액기준')}+ROUNDDOWN(({g('총수입금액기준')}-{g('일반수입금액기준')})*{R['특수관계인 수입금액 비율']},0)")
    r.put("부동산임대업 전 일반한도", "④ + ⑥ + ⑦", f"={g('기본한도')}+{g('수입금액기준한도')}")
    r.put(ESTATE, f"{ESTATE}(여 · 부, 법인세법 제25조 제5항 · 시행령 제42조 제2항)", p.inputs[ESTATE], kind="input")
    r.put("일반한도", "⑧ 일반 기업업무추진비 한도액(④ + ⑥ + ⑦, 부동산임대업 주업이면 × 50%)",
          f'=IF(OR({",".join(f"{g(ESTATE)}=" + chr(34) + k + chr(34) for k in ESTATE_YES)}),ROUNDDOWN({g("부동산임대업 전 일반한도")}*{R["부동산임대업 주업 한도 비율"]},0),'
          f'{g("부동산임대업 전 일반한도")})')
    labels = {"문화 지출액": "⑨ 문화 기업업무추진비 지출액", "전통시장 지출액": "⑪ 전통시장 기업업무추진비 지출액",
              "지역사랑상품권 지출액": "⑫ 지역사랑상품권 기업업무추진비 지출액",
              "온누리상품권 지출액": "⑬ 온누리상품권 기업업무추진비 지출액(2026.5.12 이 속하는 과세연도 지출분부터 한도에 더함)"}
    r.put("문화 지출액", labels["문화 지출액"], p.inputs["문화 지출액"], kind="input", input_kind="int")
    r.put("문화한도", "⑩ 문화 기업업무추진비 한도액(⑨ 와 ⑧ × 20% 중 적은 금액)",
          f"=MIN({g('문화 지출액')},ROUNDDOWN({g('일반한도')}*{R['문화 기업업무추진비 한도율']},0))")
    for key in SPENT[1:]:
        r.put(key, labels[key], p.inputs[key], kind="input", input_kind="int")
    r.put("전통시장등한도", "⑭ 전통시장 · 지역사랑상품권 · 온누리상품권 한도액(⑪ + ⑫ + ⑬ 과 ⑧ × 20% 중 적은 금액)",
          f"=MIN({g('전통시장 지출액')}+{g('지역사랑상품권 지출액')}+{g('온누리상품권 지출액')}*{R['온누리상품권 한도 적용(1 · 0)']},"
          f"ROUNDDOWN({g('일반한도')}*{R['전통시장 등 기업업무추진비 한도율']},0))")
    r.put("한도", "⑮ 기업업무추진비 한도액 합계(⑧ + ⑩ + ⑭)", f"={g('일반한도')}+{g('문화한도')}+{g('전통시장등한도')}")
    r.put("한도초과", "⑯ 한도초과액", f"=MAX(0,{g('차감해당금액')}-{g('한도')})")
    r.put("손금산입한도내", "⑰ 손금산입 한도 내 지출액", f"=MIN({g('차감해당금액')},{g('한도')})")
    row = adj_table(bk, s, r.row + 1, p)
    row = forms_table(bk, s, row, p, [("23갑", "① 기업업무추진비 해당금액", "해당금액"),
                                      ("23갑", "② 신용카드 등 미사용 손금불산입액", "신용카드미사용"),
                                      ("23갑", "⑧ 일반 기업업무추진비 한도액", "일반한도"),
                                      ("23갑", "⑮ 한도액 합계", "한도"), ("23갑", "⑯ 한도초과액", "한도초과"),
                                      ("23을", "신용카드 등 미사용액", "신용카드미사용")])
    notes(s, row, p)
