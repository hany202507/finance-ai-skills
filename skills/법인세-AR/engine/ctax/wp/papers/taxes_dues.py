"""1 세금과공과 · 잡손실: 벌과금 · 가산세 · 과태료 손금불산입(기타사외유출). 원장 줄마다 노란 「부인 여부」.

잡손실 줄의 기본 「부인 여부」(3회차 R3-5 에서 고침). 성격을 모르는 줄을 부인하던 규칙이 평가세트 한 회사에서 경정청구 수수료 ·
제품불량 보상 같은 큰 금액을 부인해서, 가산세 · 과태료로 볼 표시가 있는 줄만 기본 부인(O)으로 둔다.

  X  수수료 · 용역 대가     적요에 수수료 · 용역 · 대행 · 자문 · 컨설팅(4회차). 「법인세 경정청구 수수료」 처럼 세금 낱말이 있어도
                            세금이 아니라 대가다. 가산세 낱말보다 먼저 본다(계정이 벌과금 · 가산세면 이 줄을 건너뛴다)
  X  사계약 연체료          낱말이 연체료 · 연체이자 · 연체가산금뿐이고 관청 줄이 아님(4회차). 전기요금 같은 사계약 납부지연 연체료는
                            벌과금이 아니다(법인세법 기본통칙 21-0…3, ★★☆)
  O  가산세 · 과태료        적요 · 거래처에 가산세 · 과태료 · 벌과금 · 범칙금 · 통행료 같은 낱말(books.PENALTY), 계정이 벌과금 · 가산세
  O  제재 공과금            적요에 초과배출부과금 · 초과부과금(SANCTION, 법인세법 제21조 제5호)
  X  단수 차이              적요에 「단수」 · 「절사」
  X  단수 차이              관청 줄 중 10원 미만(국고금 관리법 제47조 제1항 끝수, 4회차에 100원에서 낮춤)
  X  세금 본세 차액         관청 줄인데 적요의 회사 분류가 세금과공과(「세금과공과」 · 「공과금」)인 줄(4회차). 회사가 본세로 분류한
                            납부의 차액이라 가산세로 추정하지 않는다(확인 목록)
  X  환급 차액              납부처가 관청인데 같은 전표에 예금 입금이 있는 줄(4회차). 환급받을 돈이 장부 채권보다 적게 들어온 차액이라
                            관청에 낸 돈이 아니다. 성격은 회계사 확인 목록에 남긴다
  O  가산세 · 과태료 추정   납부처가 관청(세무서 · 국세 · 부가세 · 시청 · 구청 · 경찰 등, books.AUTHORITY). 세금 본세는 잡손실로
                            처리하지 않아 관청에 낸 잡손실은 가산세 · 과태료로 본다. 원천세 수정 납부의 10원 ~ 99원도 여기
  X  단수 차이              관청이 아닌 줄 중 100원 미만
  O  차량 과태료 추정       적요 · 거래처가 리스 · 캐피탈 · 렌트 회사나 차종이고 한 줄 CAR_FINE_CAP 이하. 리스 차량 과태료는
                            차량 명의자인 리스 회사가 대납하고 청구한다. 정답지 한 곳이 이런 줄을 부인했다
  X  단수 차이 추정         1,000원 미만
  X  확인 필요              위 어디에도 맞지 않는 줄(성격을 적요로 알 수 없음). 조정하지 않고 회계사 확인 목록에 금액을 남긴다

잡비 계정(10-19). 원가 · 판관비 「잡비」 계정 줄 중 적요 · 거래처에 과태료 · 벌과금 같은 낱말(PENALTY)이 있는 줄은 O, 나머지는 X.
평가세트 한 회사가 「자동차검사위반과태료」 를 잡비(도)에 적어 조정이 빠졌다. 수수료 · 용역 낱말 줄과 사계약 연체료는 잡손실과 같이 뺀다.

리스 금융사(fx3). 차량 리스 회사는 「캐피탈」 말고 「파이낸셜 · 파이낸스」(자동차 제조사 금융사)도 있다. 리스료와 같은 전표로 청구된
잡손실(과태료 대납분)이 이 낱말로 빠져 「확인 필요」 가 되던 것을 리스 낱말에 더했다.

불공제 매입세액(fx3). 세금과공과 · 잡손실 줄 중 적요에 불공제 · 매입세액. 매입세액은 원칙이 손금불산입이고(법인세법 제21조 제1호)
면세사업 관련 · 비영업용 소형승용차(부가가치세법 제39조 제1항 제5호) · 기업업무추진비 관련(제6호) · 영수증 수취분 등은 손금이다
(법인세법 시행령 제22조 제1항, 시행규칙 제11조). 세금계산서 미수취 · 부실기재 · 합계표 미제출 · 사업무관 · 등록 전 매입세액은
손금불산입이다. 사유는 장부로 알 수 없어 기본 X(조정 없음)와 확인 줄(넣으면 얼마)만 둔다. 기업업무추진비 관련분은 기업업무추진비
한도 계산에 더해야 한다. 10-21: 전기 세금공과금명세서에서 같은 적요를 손금불산입했으면(전기 15호 불공제 가산 줄만 있으면 모든 불공제
줄) 전기 처리를 따라 기본 O 이고 확인 줄을 낸다(`prior_nondeduct`).
"""
from __future__ import annotations

import re

from ..books import AUTHORITY, PENALTY, Books
from ..model import Adj, LineRow, Paper, subject_of
from ..sheet import Book, Rows, adj_table, forms_table, head, ledger, lines_dry, notes, verify, verify_rows

NAME = "세금과공과 잡손실"
FORMS = ["세금공과금명세서"]
LEDGER_CHECK = True
PICK = "부인 여부"

ROUNDING = re.compile(r"단수|절사")
FEE = re.compile(r"수수료|용역|대행|자문|컨설팅")
LATE_FEE = re.compile(r"연체료|연체이자|연체가산금|연체금")
TAX_CATEGORY = re.compile(r"세금과공과|공과금")
# 법령의 금지 · 제한 위반을 이유로 부과되는 공과금(법인세법 제21조 제5호). 대기환경보전법 초과부과금(배출허용기준 초과)만 둔다.
# 기본부과금 · 환경개선부담금 · 폐기물처분부담금은 위반 제재가 아니라 넣지 않았다
SANCTION = re.compile(r"초과배출부과금|초과부과금")
# 차량번호만 있는 줄은 넣지 않는다(환경개선부담금 같은 차량 공과금도 차량번호를 적는다). 과태료 낱말이 있으면 위 PENALTY 가 잡는다
LEASE_CAR = re.compile(r"캐피탈|파이낸셜|파이낸스|리스료|리스사|오토리스|렌트|렌터카|렌탈카|BMW|벤츠|BENZ|아우디|AUDI|볼보|"
                       r"포르쉐|렉서스|테슬라|폭스바겐|토요타|도요타|혼다|재규어|랜드로버|링컨|캐딜락|지프|푸조|마세라티",
                       re.IGNORECASE)
# 불공제 매입세액 대체 줄(세금과공과 · 잡손실). 사유별 손금 여부는 회계 판단이라 기본 X
NONDEDUCT = re.compile(r"불공제|매입세액")
NONDEDUCT_LABEL = "불공제 매입세액"
NONDEDUCT_WHY = ("불공제 매입세액. 면세사업 · 비영업용 소형승용차 · 기업업무추진비 관련분은 손금, 세금계산서 미수취 · 부실기재 · "
                 "사업무관분은 손금불산입이라 사유를 보고 정하십시오(법인세법 제21조 제1호, 시행령 제22조 제1항)")
# 차량 과태료 한 건은 수만 원에서 십여만 원이다. 여러 건을 묶어 청구한 줄을 생각해 한 줄 30만원까지만 과태료로 추정한다(회계사와 맞춰 볼 값)
CAR_FINE_CAP = 300_000
GUESSED = ("가산세 · 과태료 추정", "차량 과태료 추정")
UNKNOWN = "확인 필요"
REFUND_GAP = "환급 차액"
TAX_GAP = "세금 본세 차액"
# 국고금 끝수(국고금 관리법 제47조 제1항). 관청 줄은 이보다 작을 때만 단수 차이다(rates_2025.yaml taxes_dues.treasury_rounding)
TREASURY_ROUNDING = 10
CASH = re.compile(r"현금|예금|당좌")


def classify_misc(amt: int, account_name: str, memo: str, partner: str, cash_in: bool = False,
                  rounding: int = TREASURY_ROUNDING) -> tuple[str, str, str]:
    """잡손실 줄 하나 → (엔진 분류, 부인 여부 기본값, 근거). 위 표의 차례대로 처음 맞는 것.

    `cash_in` 은 같은 전표의 현금 · 예금 계정 합(차변 - 대변)이 양수인지(돈이 들어온 전표). `rounding` 은 관청 줄의 끝수 기준.
    """
    text = f"{partner} {memo}".strip()
    if amt <= 0:
        return "취소 · 음수 줄", "X", ""
    penalty_account = "벌과금" in account_name or "가산세" in account_name
    hit = FEE.search(memo)
    if hit and not penalty_account:
        return "수수료 · 용역 대가", "X", f"적요에 「{hit.group(0)}」. 세금 · 과태료가 아니라 용역 대가라 부인하지 않았습니다"
    hit = PENALTY.search(text)
    words = {m.group(0) for m in PENALTY.finditer(text)}
    if (hit and not penalty_account and all(LATE_FEE.fullmatch(w) for w in words)
            and not (AUTHORITY.search(memo) or AUTHORITY.search(partner))):
        return ("사계약 연체료", "X", f"「{hit.group(0)}」 이 관청 납부가 아닙니다. 전기요금 같은 사계약 납부지연 연체료는 벌과금이 "
                "아니라 부인하지 않았습니다(법인세법 기본통칙 21-0…3). 관청 체납 가산금이면 O")
    if penalty_account or hit:
        return "가산세 · 과태료", "O", f"「{hit.group(0) if hit else account_name}」"
    hit = SANCTION.search(text)
    if hit:
        return "제재 공과금", "O", f"「{hit.group(0)}」. 배출허용기준을 넘겨 부과되는 공과금(법인세법 제21조 제5호)"
    hit = NONDEDUCT.search(memo)
    if hit:
        return NONDEDUCT_LABEL, "X", NONDEDUCT_WHY
    hit = ROUNDING.search(memo)
    if hit:
        return "단수 차이", "X", f"적요에 「{hit.group(0)}」"
    hit = AUTHORITY.search(memo) or AUTHORITY.search(partner)
    if hit and amt < rounding:
        return "단수 차이", "X", f"{rounding}원 미만(국고금 관리법 제47조 제1항 끝수)"
    if hit and TAX_CATEGORY.search(memo):
        return (TAX_GAP, "X", f"납부처가 관청(「{hit.group(0)}」)이지만 적요의 회사 분류가 세금과공과입니다. 본세 차액으로 보고 "
                "부인하지 않았습니다. 가산세면 O 로 고치세요")
    if hit and cash_in:
        return (REFUND_GAP, "X", f"납부처가 관청(「{hit.group(0)}」)이지만 같은 전표에 예금 입금이 있습니다. 환급받을 돈이 장부보다 "
                "적게 들어온 차액이라 부인하지 않았습니다. 환급금에서 가산세를 뗀 것이면 O 로 고치세요")
    if not hit and amt < 100:
        return "단수 차이", "X", "100원 미만"
    if hit:
        why = f"납부처가 관청(「{hit.group(0)}」)"
        if hit.group(0) in ("부가세", "부가가치세"):
            why += ". 부가세 정산 전표의 잡손실은 가산세가 아닌 차액이 섞일 수 있어 부가세 신고서 가산세 란과 맞춰 보세요"
        return "가산세 · 과태료 추정", "O", why
    hit = LEASE_CAR.search(text)
    if hit and amt <= CAR_FINE_CAP:
        return ("차량 과태료 추정", "O",
                f"리스 · 렌트 회사나 차량 표기(「{hit.group(0)}」) 줄의 {CAR_FINE_CAP:,}원 이하 금액. 리스 차량 과태료 대납 청구로 보았습니다")
    if amt < 1000:
        return "단수 차이 추정", "X", "1,000원 미만"
    return UNKNOWN, "X", "성격을 적요로 알 수 없어 부인하지 않았습니다. 가산세 · 과태료면 부인 여부를 O 로 고치세요"


def _expense_line(amt: int, memo: str, partner: str) -> tuple[str, str, str]:
    """잡비 줄 하나 → (엔진 분류, 부인 여부 기본값, 근거). 과태료 · 벌과금 낱말이 있는 줄만 O."""
    text = f"{partner} {memo}".strip()
    hit = PENALTY.search(text)
    if amt <= 0 or not hit or FEE.search(memo):
        return "잡비", "X", ""
    words = {m.group(0) for m in PENALTY.finditer(text)}
    if all(LATE_FEE.fullmatch(w) for w in words) and not (AUTHORITY.search(memo) or AUTHORITY.search(partner)):
        return "잡비", "X", f"「{hit.group(0)}」 이 관청 납부가 아닙니다(사계약 연체료)"
    return "잡비 중 과태료 · 벌과금", "O", f"적요 · 거래처에 「{hit.group(0)}」"


def compute(p: Paper, b: Books) -> None:
    tax_accts = b.accounts(cls="비용", any_of=("세금과공과", "세금과 공과", "공과금"))
    misc_accts = b.accounts(cls="비용", any_of=("잡손실", "벌과금", "가산세"))
    misc_codes = {a["code"] for a in misc_accts}
    exp_accts = [a for a in b.accounts(cls="비용", any_of=("잡비",)) if a["code"] not in misc_codes]
    p.accounts = tax_accts + misc_accts + exp_accts
    tax_codes = {a["code"] for a in tax_accts}
    exp_codes = {a["code"] for a in exp_accts}
    cash = _cash_by_voucher(b)
    rounding = int(b.rates.get("taxes_dues", {}).get("treasury_rounding", {}).get("value", TREASURY_ROUNDING))
    for ln in b.lines_of(p.accounts):
        text, amt = ln.text, ln.amount
        if ln.account in tax_codes:
            if amt > 0 and PENALTY.search(text):
                p.lines.append(LineRow(ln, "벌과금 · 가산세 등", "O", why=f"적요 · 거래처에 「{PENALTY.search(text).group(0)}」"))
            elif amt > 0 and NONDEDUCT.search(ln.memo):
                p.lines.append(LineRow(ln, NONDEDUCT_LABEL, "X", why=NONDEDUCT_WHY))
            else:
                p.lines.append(LineRow(ln, "세금 · 공과금", "X"))
            continue
        if ln.account in exp_codes:
            p.lines.append(LineRow(ln, *_expense_line(amt, ln.memo, ln.partner)))
            continue
        name = b.by_code.get(ln.account, {}).get("name", "")
        label, pick, why = classify_misc(amt, name, ln.memo, ln.partner, cash.get((ln.date, ln.no), 0) > 0, rounding)
        p.lines.append(LineRow(ln, label, pick, why=why))
    prior_memos, prior_any = prior_nondeduct(b)
    if prior_memos or prior_any:
        for r in p.lines:
            if r.label == NONDEDUCT_LABEL and r.pick == "X" and (prior_any or _core(r.line.memo) in prior_memos):
                r.pick = "O"
                r.why = PRIOR_WHY
    p.take_lines(b, PICK)
    tax_total = sum(r.line.amount for r in p.lines if r.line.account in tax_codes)
    tax_o = sum(r.line.amount for r in p.lines if r.line.account in tax_codes and r.pick == "O")
    misc_total = sum(r.line.amount for r in p.lines if r.line.account not in tax_codes | exp_codes)
    misc_o = sum(r.line.amount for r in p.lines if r.line.account not in tax_codes | exp_codes and r.pick == "O")
    exp_total = sum(r.line.amount for r in p.lines if r.line.account in exp_codes)
    exp_o = sum(r.line.amount for r in p.lines if r.line.account in exp_codes and r.pick == "O")
    nondeduct = [r for r in p.lines if r.label == NONDEDUCT_LABEL]
    p.values = {"세금과공과": tax_total, "세금과공과 손금불산입": tax_o, "잡손실": misc_total, "잡손실 손금불산입": misc_o,
                "불공제 매입세액": sum(r.line.amount for r in nondeduct), "잡비": exp_total, "잡비 손금불산입": exp_o}
    p.adjustments = [
        Adj("가산", subject_of(tax_accts, "세금과공과"), tax_o, "기타사외유출", "세금과공과 벌과금 등",
            "세금과공과 중 벌과금 · 가산세 등 손금불산입", "세금과공과 손금불산입"),
        Adj("가산", subject_of(misc_accts, "잡손실"), misc_o, "기타사외유출", "잡손실 가산세 · 과태료",
            "잡손실 중 가산세 · 과태료 손금불산입", "잡손실 손금불산입"),
        Adj("가산", subject_of(exp_accts, "잡비"), exp_o, "기타사외유출", "잡비 과태료 등",
            "잡비 중 과태료 · 벌과금 손금불산입", "잡비 손금불산입"),
    ]
    # 회계사가 확인한 줄(부인 여부를 고친 줄)은 「추정」 확인 목록에서 뺀다
    guessed = [r for r in p.lines if r.label in GUESSED and f"{PICK}/{r.key}" not in p.overridden and r.pick == "O"]
    if guessed:
        p.confirm.append(f"잡손실 {len(guessed)}줄 {sum(r.line.amount for r in guessed):,}원은 납부처 · 차량 표기로 가산세 · 과태료를 "
                         "추정해 부인했습니다. 부인 여부를 확인하세요")
    unknown = [r for r in p.lines if r.label == UNKNOWN and f"{PICK}/{r.key}" not in p.overridden and r.pick == "X"]
    if unknown:
        p.confirm.append(f"잡손실 {len(unknown)}줄 {sum(r.line.amount for r in unknown):,}원은 성격을 적요로 알 수 없어 부인하지 "
                         "않았습니다(확인 필요). 가산세 · 과태료가 있으면 부인 여부를 O 로 고치세요")
    gap = [r for r in p.lines if r.label in (REFUND_GAP, TAX_GAP) and f"{PICK}/{r.key}" not in p.overridden and r.pick == "X"]
    if gap:
        p.confirm.append(f"잡손실 {len(gap)}줄 {sum(r.line.amount for r in gap):,}원은 관청 줄이지만 환급받을 때 덜 들어온 차액 · "
                         "회사가 세금과공과로 분류한 본세 차액이라 부인하지 않았습니다(확인 필요). 가산세면 부인 여부를 O 로 고치세요")
    followed = [r for r in nondeduct if r.why == PRIOR_WHY and f"{PICK}/{r.key}" not in p.overridden and r.pick == "O"]
    if followed:
        p.confirm.append(f"불공제 매입세액 {len(followed)}줄 {sum(r.line.amount for r in followed):,}원은 전기 신고서에서 같은 적요를 "
                         "손금불산입해 부인 여부 기본값을 O 로 두었습니다(15호 가산 · 기타사외유출). 당기 불공제 사유가 면세사업 관련 · "
                         "비영업용 소형승용차 · 기업업무추진비 관련이면 손금이라 그 줄을 X 로 바꾸십시오(법인세법 시행령 제22조 제1항)")
    left = [r for r in nondeduct if f"{PICK}/{r.key}" not in p.overridden and r.pick == "X"]
    if left:
        amt_left = sum(r.line.amount for r in left)
        p.confirm.append(f"불공제 매입세액 {len(left)}줄 {amt_left:,}원을 세금과공과 · 잡손실로 처리했습니다. 불공제 사유별 손금 여부는 회계 판단이라 "
                         "부인하지 않았습니다. 면세사업 관련 · 비영업용 소형승용차 · 기업업무추진비 관련분은 손금(기업업무추진비 관련분은 "
                         "기업업무추진비 한도 계산에 더함), 세금계산서 미수취 · 부실기재 · 합계표 미제출 · 사업무관 · 등록 전 매입세액은 "
                         f"손금불산입입니다. 모두 손금불산입 사유면 넣으면 15호 가산 {amt_left:,}원(기타사외유출)이고, 그 줄의 부인 여부를 "
                         "O 로 고치면 됩니다(법인세법 제21조 제1호, 시행령 제22조 제1항, 부가가치세법 제39조 제1항)")
    p.notes.append("임직원 개인에게 귀속되는 과태료는 상여로 바꿔야 합니다(목업은 모두 기타사외유출)")
    p.settle(bool(tax_total or misc_total or exp_o))


PRIOR_WHY = "전기 신고서에서 같은 적요의 불공제 매입세액을 손금불산입했습니다(전기 처리를 따름). 사유가 바뀌었으면 X"


def _core(memo: str) -> str:
    return re.sub(r"[\s\d,.()/\-]", "", memo or "")


def prior_nondeduct(b: Books) -> tuple[set[str], bool]:
    """전기에 손금불산입한 불공제 매입세액(10-21). (적요 모음, 적요를 모르는 손금불산입이 있었는지).
    전기 세금공과금명세서 줄 가운데 적요에 불공제 · 매입세액이 있고 비고가 손금불산입인 줄의 적요(빈칸 · 숫자를 뺀 글)를 모은다.
    그 서식 줄이 없고 전기 15호 가산 줄 과목 · 조정내용에 불공제가 있으면 적요를 모르는 손금불산입으로 본다(AR prior_nondeductible 과 같다)."""
    prior = b.prior or {}
    memos = {_core(r.get("적요")) for r in (prior.get("rows") or {}).get("세금공과금명세서") or []
             if NONDEDUCT.search(str(r.get("적요") or "")) and str(r.get("비고") or "").startswith("손금불산입")
             and "취소" not in str(r.get("비고") or "")}
    memos.discard("")
    if memos:
        return memos, False
    adds = [a for a in prior.get("adjustments") or [] if a.get("side") == "가산"
            and "불공제" in f"{a.get('subject') or ''} {a.get('note') or ''}"]
    return set(), bool(adds)


def _cash_by_voucher(b: Books) -> dict:
    """전표(일자, 번호)마다 현금 · 예금 계정의 차변 - 대변. 양수면 돈이 들어온 전표다(예수금은 「예수」 라 걸리지 않는다)."""
    codes = {a["code"] for a in b.accounts(cls="자산") if CASH.search(a.get("name") or "")}
    out: dict = {}
    for ln in b.lines:
        if ln.account in codes:
            out[(ln.date, ln.no)] = out.get((ln.date, ln.no), 0) + ln.debit - ln.credit
    return out


def basis(rates: dict) -> list[tuple]:
    t = rates["taxes_dues"]
    r, f = t["treasury_rounding"], t["private_late_fee"]
    out = [("잡손실 관청 줄 끝수 기준", r["value"], r["basis"], r["grade"], None),
           ("잡손실 사계약 연체료", f["value"], f["basis"], f["grade"], None)]
    v = (rates.get("vat_nondeductible") or {}).get("rule")
    if v:
        out.append(("불공제 매입세액", v["value"], v["basis"], v["grade"], None))
    return out


def write(bk: Book, p: Paper) -> None:
    s = head(bk, p)
    row = 5
    _, first, last = lines_dry(p, row + verify_rows(p))
    row = verify(bk, s, row, p, first, last)
    row, first, last = ledger(bk, s, row, p, PICK)
    exp_codes = [a["code"] for a in p.accounts if "잡비" in a["name"] and not any(w in a["name"] for w in ("잡손실", "벌과금", "가산세"))]
    tax_codes = [a["code"] for a in p.accounts if not any(w in a["name"] for w in ("잡손실", "벌과금", "가산세"))
                 and a["code"] not in exp_codes]
    misc_codes = [a["code"] for a in p.accounts if a["code"] not in tax_codes and a["code"] not in exp_codes]

    def total(codes, only_o=False):
        if not codes:
            return "=0"
        parts = []
        for code in codes:
            if only_o:
                parts.append(f'SUMIFS(G{first}:G{last},C{first}:C{last},"{code}",I{first}:I{last},"O")')
            else:
                parts.append(f'SUMIF(C{first}:C{last},"{code}",G{first}:G{last})')
        return "=" + "+".join(parts)

    row = s.section(row, "3. 손금불산입 집계")
    r = Rows(bk, s, p, row)
    r.put("세금과공과", "세금과공과 합계", total(tax_codes))
    r.put("세금과공과 손금불산입", "세금과공과 중 부인(O)", total(tax_codes, True))
    r.put("잡손실", "잡손실 합계", total(misc_codes))
    r.put("잡손실 손금불산입", "잡손실 중 부인(O)", total(misc_codes, True))
    if exp_codes:
        r.put("잡비", "잡비 합계", total(exp_codes))
        r.put("잡비 손금불산입", "잡비 중 과태료 · 벌과금 부인(O)", total(exp_codes, True))
    r.put("불공제 매입세액", "불공제 매입세액 줄 합계(엔진 분류, 사유별 손금 여부는 회계 판단)",
          f'=SUMIF(H{first}:H{last},"{NONDEDUCT_LABEL}",G{first}:G{last})', note="법인세법 제21조 제1호 · 시행령 제22조 제1항")
    row = adj_table(bk, s, r.row + 1, p)
    row = forms_table(bk, s, row, p, [("세금공과금명세서", "계", "세금과공과"),
                                      ("세금공과금명세서", "손금불산입계", "세금과공과 손금불산입")])
    notes(s, row, p)
