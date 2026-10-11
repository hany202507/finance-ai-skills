# -*- coding: utf-8 -*-
"""예정신고를 하지 않은 확정신고의 가산세: 예정신고 무신고가산세와 납부지연가산세.

율은 rules/ruleset.json 에서 읽는다(가산세.무신고.율, 가산세.무신고.확정신고감면율, 가산세.납부지연.일이자율,
가산세.납부지연.납부일산입). 계산 방식과 끝수는 국세청 「2023년 유형별 확정신고 사례」(확정신고 작성 사례 09)의
「무신고 가산세」「납부지연 가산세」 계산 근거와 서식 가산세 줄을 따랐다. 대조 기록은 references/정답지.md 「가산세 대조」에 있다.

  건            예정신고 한 건. 예정신고 기한의 말일이 같은 과세 자산의 묶음이다(양도일이 속하는 달이 같은 자산,
                허가 전에 대금을 청산한 허가구역 토지는 허가일이 속하는 달)
  예정신고세액  그 건만 예정신고했을 때의 산출세액. 엔진 결과의 자산별 과세표준(기본공제를 먼저 양도한 자산부터 뺀 값)을
                같은 세율로 합산하는 자산끼리 더해 세율을 적용한다(사례 8). 다른 건의 양도소득금액과는 합산하지 않는다(사례 4·5)
  무신고        건별 예정신고세액의 합 × 율. 원 미만을 버린다. 건별·열별 값은 건마다 원 미만을 버리고, 합계에 모자라는 원을
                세액이 가장 큰 건에 더한다(사례 8 서식: 787,556 · 60,313).
                확정신고기한까지 신고한 경우의 감면(가산세.무신고.확정신고감면율)은 적용하지 않는다. 이 스킬이 만드는 것은
                확정신고서이고 예정신고분의 기한 후 신고서가 아니다. 2026-01-01 부터의 문언은 「확정신고기한까지 제45조의3에 따른
                기한 후 신고를 한 경우」이고, 그 전 문언(「과세표준신고를 한 경우」) 구간에도 같게 적용하지 않는다(문언으로 가르지 않는다).
                감면을 적용한 금액은 대안으로 싣는다(국세청 사례 8 은 감면을 넣은 값이다: 8,478,692 × 20% × 50% = 847,869)
  무신고_감면적용, 무신고_감면없음   감면율을 곱한 금액과 곱하지 않은 금액. 무신고는 곱하지 않은 쪽이다
  납부지연      건마다 예정신고세액 × 일수 × 일이자율. 10원 미만을 버린다(사례 2·4·5·8 의 모든 줄)
  일수          납부기한 다음 날부터 납부일 전날까지. 규칙 `가산세.납부지연.납부일산입` 이 1 인 구간의 납부는 납부일까지.
                납부기한은 예정신고 기한 말일이 토요일·일요일·공휴일·대체공휴일·노동절이면 그 다음 날로 옮긴 날이다
                (dates.filing_deadline). 공휴일 표가 덮지 않는 해에 끝나는 기한은 확인사항으로 알린다
  열            본지 세율구분 열. 건의 가산세를 그 건의 세율구분별 세액 비율로 나눈다(원문 사례는 모두 건 하나가 열 하나다)

해석이 들어간 곳 둘은 결과와 확인사항에 다른 쪽 금액을 함께 싣는다.
  감면          감면을 적용하지 않았다. 예정신고분을 기한 후 신고로 내 감면이 적용될 때의 금액이 무신고_감면적용이다
  같은 달 양도  같은 달에 다른 날 양도한 자산을 한 건으로 합산했다. 양도일마다 따로 신고하는 쪽의 금액이 양도일별이다

납부일이 납부기한 이전인 건은 예정신고 기한 안이라 가산세가 없다.
건별 세액이나 납부기한을 조문과 원문 사례로 정할 수 없으면 Unsupported 로 멈춘다.

지방소득세(양도소득에 대한 개인지방소득세)의 가산세도 같은 건으로 계산해 결과의 「지방」 에 싣는다.
  예정신고세액  건의 과세표준에 지방소득세 세율을 적용한 세액(합산 묶음마다)
  납부기한      소득세법이 정한 예정신고기한(옮기기 전)에 지방.신고기한.가산개월 을 더한 날, 쉬는 날이면 다음 날
                (dates.local_filing_deadline, 지방세법 제103조의5①, 지방세기본법 제23조·제24조①)
  무신고        세액의 합 × 지방.가산세.무신고.율. 국세와 같이 감면(지방.가산세.무신고.확정신고감면율)을 적용하지 않는다.
                지방세기본법 제57조②4호가목의 문언은 「확정신고기한까지 과세표준 신고를 한 경우」지만, 국세기본법이 같은 꼴의
                문언이던 때에도 과세관청이 예정신고분의 기한 후 신고 없이 확정신고만 한 경우를 감면 대상으로 보지 않은 예가 있고
                지방 쪽 해석은 확인하지 못했다. 감면을 적용한 금액은 대안으로 싣는다(지방.무신고_감면적용, 지방.감면안내)
  납부지연      건마다 세액 × 일수 × 지방.가산세.납부지연.일이자율. 일수는 납부기한 다음 날부터 납부일까지(지방.가산세.납부지연.납부일산입)
  끝수          무신고는 세액 합계에 율을 곱해 원 미만을 버린 뒤 건에 나누고, 납부지연은 건마다 원 미만을 버린다(LOCAL_UNIT)
조문으로 정해지지 않아 정한 가정이 둘이다(국세 기한이 쉬는 날이라 옮겨졌을 때 더하는 기준일, 가산세 금액의 끝수).
결과의 「지방.가정안내」 와 확인사항이 그 가정을 적고 위택스 화면의 값과 다르면 위택스 값을 따르라고 알린다.
납부일이 모든 건의 지방 납부기한 이전이면 지방소득세 가산세가 없다. 그때는 확인사항에 한 줄만 적고 가정안내와 감면안내는 None 이다.
"""
from decimal import Decimal

from yangdo import calc, dates, ruleset
from yangdo.dates import to_date

RATE_KEY = "가산세.무신고.율"
RELIEF_KEY = "가산세.무신고.확정신고감면율"
DAILY_KEY = "가산세.납부지연.일이자율"
PAID_DAY_KEY = "가산세.납부지연.납부일산입"
RULE_KEYS = (RATE_KEY, RELIEF_KEY, DAILY_KEY, PAID_DAY_KEY)
# 납부지연가산세의 끝수 단위(원). 법령 값이 아니라 국세청 작성 사례의 계산 근거가 쓴 끝수 처리다(references/규칙세트_스키마.md)
LATE_UNIT = 10
# 지방소득세 가산세의 규칙 키와 끝수 단위(원). 지방소득세는 국세청 작성 사례 같은 대조할 원문이 없어 원 미만을 버리는 것으로 정했다
LOCAL_RATE_KEY = "지방.가산세.무신고.율"
LOCAL_RELIEF_KEY = "지방.가산세.무신고.확정신고감면율"
LOCAL_DAILY_KEY = "지방.가산세.납부지연.일이자율"
LOCAL_PAID_DAY_KEY = "지방.가산세.납부지연.납부일산입"
LOCAL_MONTHS_KEY = "지방.신고기한.가산개월"
LOCAL_RULE_KEYS = (LOCAL_RATE_KEY, LOCAL_RELIEF_KEY, LOCAL_DAILY_KEY, LOCAL_PAID_DAY_KEY, LOCAL_MONTHS_KEY)
LOCAL_UNIT = 1
# 감면 조문(국세기본법 제48조②3호라목)의 문구는 규칙 가산세.무신고.확정신고감면율 의 이력 구간으로 갈린다. 첫 구간은
# 「확정신고기한까지 과세표준신고를 한 경우」, 그 뒤 구간은 「확정신고기한까지 제45조의3에 따른 기한 후 신고를 한 경우」다
# (율은 같다). 어느 구간인지는 발췌 글자가 아니라 구간의 시작 날짜로 가른다(_new_wording_from). 아래 글자는 확인사항의 설명
# 문장에만 쓴다. 감면을 적용할지는 구간으로 가르지 않는다(확정신고서에는 구간과 상관없이 적용하지 않는다)
RELIEF_NEW_WORDING = "기한 후 신고를 한 경우"
# 감면 규정의 괄호(과세표준과 세액을 경정할 것을 미리 알고 신고한 경우 제외). 감면을 적용한 대안 금액을 말하는 문장에 조건으로 붙인다
RELIEF_CONDITION = "과세표준과 세액을 경정할 것을 미리 알고 신고한 경우가 아니고 감면이 적용되면"


class Unsupported(Exception):
    """건별 예정신고 세액이나 납부기한을 조문과 국세청 사례로 정할 수 없는 경우. 가산세를 내지 않고 멈춘다."""

    def __init__(self, message, 계획="없음"):
        super().__init__(message)
        self.계획 = 계획


def days(due, paid, paid_day):
    """납부지연 일수. 납부기한 다음 날부터 납부일 전날까지이고, paid_day(규칙 가산세.납부지연.납부일산입)가 1 이면 납부일까지다.
    납부일이 납부기한 이전이면 None(기한 안)."""
    due, paid = to_date(due), to_date(paid)
    if paid <= due:
        return None
    return (paid - due).days - 1 + int(paid_day)


def _split(total, weights):
    """총액을 가중치 비율로 나눈다. 원 미만은 버리고 남는 원은 가중치가 가장 큰 칸(같으면 앞 칸)에 더한다."""
    whole = sum(weights)
    if not whole:
        return [total] + [0] * (len(weights) - 1)
    parts = [total * w // whole for w in weights]
    top = max(range(len(weights)), key=lambda j: (weights[j], -j))
    parts[top] += total - sum(parts)
    return parts


def amounts(taxes, day_counts, rate, relief, daily, unit=LATE_UNIT):
    """건별 예정신고세액과 일수 → (무신고 합계, 건별 무신고, 건별 납부지연). unit 은 납부지연의 끝수 단위(원)다.

    일수가 None 인 건은 납부기한이 지나지 않은 건이라 0 이고 합계의 세액에도 넣지 않는다.
    무신고 합계는 세액의 합에 율을 곱해 원 미만을 버린다. 건별 값은 건마다 버린 뒤 모자라는 원을 세액이 가장 큰 건에 더한다.
    납부지연은 건마다 LATE_UNIT 원 미만을 버린다. relief 에 0 을 주면 감면을 적용하지 않은 금액이다.
    """
    factor = Decimal(rate) * (1 - Decimal(relief))
    due = [i for i, d in enumerate(day_counts) if d is not None]
    total = calc.floor(Decimal(sum(taxes[i] for i in due)) * factor)
    per_case = [0] * len(taxes)
    late = [0] * len(taxes)
    for i in due:
        per_case[i] = calc.floor(Decimal(taxes[i]) * factor)
        late[i] = calc.floor(Decimal(taxes[i]) * day_counts[i] * Decimal(daily)) // unit * unit
    if due:
        top = max(due, key=lambda i: (taxes[i], -i))
        per_case[top] += total - sum(per_case)
    return total, per_case, late


def _deadline_base(row, asset, notes):
    """예정신고 기한을 세는 기준일. 허가 전에 대금을 청산한 허가구역 토지는 허가일이다(return_values 의 신고기한 판정과 같은 기준).
    허가일 값이 없거나 읽지 못하면 납부기한을 정할 수 없다."""
    sold = to_date(row["판정"]["양도일"])
    if asset.get("토지거래허가대상") != "예":
        return sold
    try:
        permit = to_date((asset.get("토지거래허가") or {}).get("허가일"))
    except ValueError:
        permit = None
    if permit is None:
        raise Unsupported("%s: 토지거래허가 대상 자산인데 허가일 값이 없거나 읽을 수 없다. 허가 전에 대금을 청산했으면 예정신고 기한이 "
                          "허가일 기준이라 납부기한을 정할 수 없어 가산세를 계산하지 않았다" % row["id"])
    if permit > sold:
        notes.append("%s: 토지거래허가 전에 대금을 청산해 허가일(%s) 기준으로 예정신고 납부기한을 셌다. 허가 전에 허가구역 지정이 "
                     "해제됐으면 해제일 기준이라 기한이 다르다" % (row["id"], permit.isoformat()))
        return permit
    return sold


def _tax(members, rs, local=False):
    """한 번에 예정신고하는 자산들의 세액. (세율구분 표기별 세액, 합). local 이면 지방소득세 세율로 구한다.
    같은 세율로 합산하는 자산끼리 과세표준을 더해 세율을 적용한다. 세율이 다른 자산이 섞였고 합산 비교세액이 더 크면 정하지 않는다."""
    merged = {}
    for m in members:
        merged.setdefault(m["계산"]["합산묶음"], []).append(m)
    cols = {}
    for group in merged.values():
        anchor = calc.group_anchor(group)
        code = anchor["계산"]["코드"]
        base = sum(m["계산"]["과세표준"] for m in group)
        tax, _ = calc.rate_tax(anchor["판정"], base, rs, to_date(anchor["판정"]["양도일"]), local=local)
        name = "%s-%s" % (code["국내외분"], code["세율구분"])
        cols[name] = cols.get(name, 0) + tax
    tax = sum(cols.values())
    if len(merged) >= 2:
        first = min(to_date(m["판정"]["양도일"]) for m in members)
        whole = sum(m["계산"]["과세표준"] for m in members)
        compare = calc.floor(calc.progressive(whole, rs.value("지방.기본세율" if local else "기본세율", first)))
        if compare > tax:
            raise Unsupported(
                "자산 %s: 예정신고 기한이 같은 자산의 %s합산 비교세액 %s원이 세율별 세액의 합 %s원보다 크다. 이 경우의 예정신고 세액과 "
                "세율구분 열별 가산세는 국세청 작성 사례에 계산 방식이 없어 정하지 않았다"
                % (", ".join(m["id"] for m in members), "지방소득세 " if local else "", _won(compare), _won(tax)))
    return cols, tax


def _by_sale_date(members, rs):
    """건을 양도일마다 따로 신고하는 것으로 볼 때의 세액 목록. 정할 수 없으면 None."""
    dated = {}
    for m in members:
        dated.setdefault(m["판정"]["양도일"], []).append(m)
    out = []
    for sold in sorted(dated):
        try:
            _, tax = _tax(dated[sold], rs)
        except Unsupported:
            return None
        out.append({"자산": [m["id"] for m in dated[sold]], "양도일": sold, "예정신고세액": tax})
    return out


def cases(rows, facts, rs):
    """과세 자산을 예정신고 건으로 묶고 건별 예정신고세액을 구한다. (건 목록, 확인사항).

    건 = {"자산": [id], "예정신고세액": int, "기한말일": date, "납부기한": date, "열": {세율구분 표기: 세액},
          "양도일별": [{"자산", "양도일", "예정신고세액"}] 또는 None, "자산양도일": {id: 양도일}, "공휴일표": bool,
          "지방": {"예정신고세액", "열", "기한말일", "납부기한", "공휴일표", "건너뛴날"}}.
    공휴일표는 그 건의 납부기한이 끝나는 해가 공휴일 표에 있는지다(dates.Deadline).
    지방은 같은 건의 지방소득세 예정신고 세액과 지방 납부기한이다(dates.local_filing_deadline).
    양도일별은 건을 양도일마다 따로 신고하는 것으로 볼 때의 세액이다(양도일이 하나면 항목도 하나).
    rows 는 엔진 결과의 계산.자산이다. 과세표준과 합산 묶음, 세율구분 코드를 그대로 쓴다.
    """
    assets = {a.get("id"): a for a in facts.get("자산") or []}
    notes, grouped = [], {}
    for r in sorted(rows, key=lambda r: (r["판정"]["양도일"], r["id"])):
        if r["판정"]["전액비과세"]:
            continue
        base = _deadline_base(r, assets.get(r["id"]) or {}, notes)
        deadline = dates.filing_deadline("예정", base, rs)
        grouped.setdefault(deadline[0], (deadline, [], dates.local_filing_deadline("예정", base, rs)))[1].append(r)
    out = []
    for nominal in sorted(grouped):
        deadline, members, local_deadline = grouped[nominal]
        local_cols, local_tax = _tax(members, rs, local=True)
        adjusted = deadline[1]
        ids = [m["id"] for m in members]
        cols, tax = _tax(members, rs)
        if nominal != adjusted:
            notes.append("자산 %s: 예정신고 기한 말일은 %s 이고 납부기한은 %s 로 보았다. 건너뛴 날은 %s 이다"
                         % (", ".join(ids), nominal.isoformat(), adjusted.isoformat(), dates.skipped_text(deadline)))
        out.append({"자산": ids, "예정신고세액": tax, "기한말일": nominal, "납부기한": adjusted, "열": cols,
                    "양도일별": _by_sale_date(members, rs), "자산양도일": {m["id"]: m["판정"]["양도일"] for m in members},
                    "공휴일표": deadline.공휴일표,
                    "지방": {"예정신고세액": local_tax, "열": local_cols, "기한말일": local_deadline[0],
                           "납부기한": local_deadline[1], "공휴일표": local_deadline.공휴일표,
                           "건너뛴날": dates.skipped_text(local_deadline)}})
    return out, notes


def _articles(rs, keys, on):
    """규칙세트 근거의 법령과 조 이름(부칙은 뺀다). 문장에 적는 조문은 규칙세트에 근거가 실린 것뿐이다."""
    by_law = {}
    for key in keys:
        for g in rs.entry(key, on)["근거"]:
            if g["조"] == "부칙":
                continue
            names = by_law.setdefault(g["법령"], [])
            name = ruleset.label(g["조"])
            if name not in names:
                names.append(name)
    return ", ".join("%s %s" % (law, "·".join(names)) for law, names in by_law.items())


def _pct(rate):
    return format((Decimal(rate) * 100).normalize(), "f") + "%"


def _won(amount):
    """문장에 적는 금액. 천 단위 쉼표를 넣는다(20,627,400). 결과의 숫자 값은 바꾸지 않고 문장에만 쓴다."""
    return format(int(amount), ",")


def _new_wording_from(rs, on):
    """신고일 on 이 감면 조문의 문구가 바뀐 뒤의 구간이면 그 구간의 시작 날짜, 첫 구간이면 None.

    규칙 가산세.무신고.확정신고감면율 의 이력은 문구가 바뀐 날에 구간이 갈린다(율은 같다). 발췌 글자를 읽지 않고 구간의 시작
    날짜로 가른다. 발췌를 다시 받아 글자가 조금 달라져도 문장이 조용히 빠지지 않게 하려는 것이다. 문구와 발췌가 어긋나는지는
    시험(test_relief_wording_constant_matches_the_ruleset_excerpts)이 본다."""
    history = rs.data["규칙"][RELIEF_KEY]["이력"]
    first = min(to_date(e["시작"]) for e in history)
    start = to_date(rs.entry(RELIEF_KEY, on)["시작"])
    return start.isoformat() if start > first else None


def _wording_sentence(rs, on):
    """감면 조문의 문구가 바뀌었다는 설명 문장. 문구가 바뀐 뒤의 구간에만 적는다. 금액에는 쓰지 않는다."""
    since = _new_wording_from(rs, on)
    return "이 규정의 문구는 %s 부터 「%s」다. " % (since, RELIEF_NEW_WORDING) if since else ""


def local(found, rs, paid, names):
    """지방소득세 가산세. found 는 cases 의 건 목록, names 는 세율구분 표기 목록. (결과 dict, 확인사항).

    결과 키: 무신고·납부지연·계, 감면적용(언제나 False), 무신고_감면적용, 무신고_감면없음, 감면안내, 율·감면율·일이자율(문자열),
    건(자산·예정신고세액·기한말일·납부기한·기한경과·일수·무신고·무신고_감면적용·무신고_감면없음·납부지연), 열, 가정안내, 근거.
    무신고가산세는 국세와 같이 감면을 적용하지 않은 금액이다. 감면을 적용한 금액은 무신고_감면적용과 감면안내 문장에 싣는다.
    납부일이 모든 건의 지방 납부기한 이전이면 가산세가 없고, 확인사항은 그 한 줄뿐이며 가정안내와 감면안내는 None 이다.
    건이 없으면(과세 자산이 없는 사건) 규칙을 읽지 않고 0 을 돌려준다. 그때 율·감면율·일이자율은 None 이다.
    """
    out = {"무신고": 0, "무신고_감면적용": 0, "무신고_감면없음": 0, "감면적용": False, "감면안내": None, "납부지연": 0, "계": 0,
           "율": None, "감면율": None, "일이자율": None, "납부일산입": None, "건": [],
           "열": {name: {"무신고": 0, "납부지연": 0} for name in names}, "가정안내": None, "근거": []}
    if not found:
        return out, []
    rate, relief = rs.value(LOCAL_RATE_KEY, paid), rs.value(LOCAL_RELIEF_KEY, paid)
    daily, paid_day = rs.value(LOCAL_DAILY_KEY, paid), rs.value(LOCAL_PAID_DAY_KEY, paid)
    out.update(율=str(rate), 감면율=str(relief), 일이자율=str(daily), 납부일산입=bool(paid_day))
    taxes = [c["지방"]["예정신고세액"] for c in found]
    counts = [days(c["지방"]["납부기한"], paid, paid_day) for c in found]
    total, per_case, late = amounts(taxes, counts, rate, 0, daily, LOCAL_UNIT)
    with_relief, with_relief_per_case, _ = amounts(taxes, counts, rate, relief, daily, LOCAL_UNIT)
    notes = []
    for c, n, nonfiling, reduced, delay in zip(found, counts, per_case, with_relief_per_case, late):
        loc = c["지방"]
        labels, weights = list(loc["열"]), list(loc["열"].values())
        for kind, amount in (("무신고", nonfiling), ("납부지연", delay)):
            for name, part in zip(labels, _split(amount, weights)):
                out["열"].setdefault(name, {"무신고": 0, "납부지연": 0})[kind] += part
        out["건"].append({"자산": c["자산"], "예정신고세액": loc["예정신고세액"], "기한말일": loc["기한말일"].isoformat(),
                         "납부기한": loc["납부기한"].isoformat(), "기한경과": n is not None, "일수": n or 0,
                         "무신고": nonfiling, "무신고_감면적용": reduced, "무신고_감면없음": nonfiling, "납부지연": delay})
        text = ("자산 %s: 지방소득세 예정신고 세액은 %s원이고 지방소득세 예정신고기한은 %s, 납부기한은 %s 로 보았다"
                % (", ".join(c["자산"]), _won(loc["예정신고세액"]), loc["기한말일"].isoformat(), loc["납부기한"].isoformat()))
        if loc["건너뛴날"]:
            text += ". 건너뛴 날은 %s 이다" % loc["건너뛴날"]
        if n is None:
            text += ". 납부일(%s)이 이 납부기한을 지나지 않아 이 건에는 지방소득세 가산세를 계산하지 않았다" % paid.isoformat()
        notes.append(text)
    out["근거"] = [c for key in LOCAL_RULE_KEYS for c in rs.cite(key, paid)]
    if all(n is None for n in counts):
        # 납부일이 모든 건의 지방 납부기한 이전이다. 0원을 계산했다는 문장과 가정·감면 문장 대신 한 줄만 적는다
        first = min(c["지방"]["납부기한"] for c in found)
        return out, ["지방소득세는 지방 예정신고기한 %s 이전에 신고·납부하므로 가산세가 없다" % first.isoformat()]
    due_tax = sum(t for t, n in zip(taxes, counts) if n is not None)
    article = _articles(rs, (LOCAL_RELIEF_KEY,), paid)
    relief_note = ("지방소득세 무신고가산세는 감면 없이 계산했다. 지방세 쪽 감면 규정(%s)의 문구는 확정신고기한까지 신고한 경우이지만, "
                   "같은 꼴의 문구를 과세관청이 달리 본 예가 있어 적용하지 않았다. %s 지방소득세 무신고가산세는 %s원이다. "
                   "위택스 화면의 가산세와 다르면 위택스 값을 따른다. 세무 전문가와 확인한다" % (article, RELIEF_CONDITION, _won(with_relief)))
    assume = ("지방소득세 가산세는 두 가지를 가정해 계산했다. 지방소득세 예정신고기한은 소득세법이 정한 예정신고기한(토요일·일요일·공휴일이라 "
              "옮기기 전)에 %s개월을 더한 날로 보았고(%s), 무신고가산세는 세액 합계에 율을 곱해 원 미만을 버린 뒤 건에 나눴고 "
              "납부지연가산세는 건마다 원 미만을 버렸다. 위택스 화면이 계산한 가산세와 다르면 위택스 값을 따른다"
              % (rs.value(LOCAL_MONTHS_KEY, paid), _articles(rs, (LOCAL_MONTHS_KEY,), paid)))
    head = [
        "지방소득세에도 예정신고 무신고가산세 %s원과 납부지연가산세 %s원을 계산했다. 무신고가산세는 기한이 지난 건의 지방소득세 "
        "예정신고 세액 합계 %s원 × %s, 납부지연가산세는 건마다 지방소득세 예정신고 세액 × 일수 × 1일 10만분의 %s 이다(%s). "
        "일수는 지방소득세 납부기한 다음 날부터 납부일(%s)%s까지 셌다. 지방소득세도 이 날 위택스에서 신고하고 내는 것으로 보았다"
        % (_won(total), _won(sum(late)), _won(due_tax), _pct(rate), format((Decimal(daily) * 100000).normalize(), "f"),
           _articles(rs, (LOCAL_RATE_KEY, LOCAL_DAILY_KEY), paid), paid.isoformat(), "" if paid_day else " 전날"),
        relief_note, assume]
    unknown = [c for c in found if not c["지방"]["공휴일표"]]
    if unknown:
        head.append("자산 %s: 지방소득세 납부기한이 끝나는 해가 공휴일 표에 없다. 그 해의 설날·추석 연휴, 대체공휴일, 선거일, 임시공휴일은 "
                    "건너뛰지 못했다. 납부기한이 그런 날이면 실제 기한은 더 늦고 일수가 줄어든다"
                    % ", ".join(i for c in unknown for i in c["자산"]))
    out.update(무신고=total, 무신고_감면적용=with_relief, 무신고_감면없음=total, 감면안내=relief_note, 납부지연=sum(late),
               계=total + sum(late), 가정안내=assume)
    return out, head + notes


def _relief_note(rs, paid, rate, relief, with_relief):
    """감면을 적용하지 않았다는 것과 감면이 적용될 때의 금액. 감면 규정이 있다는 것, 이 스킬이 확정신고서를 만든다는 것,
    대안 금액과 그 조건(감면 규정의 괄호)을 적는다. 규정을 옮기는 말은 신고일이 속한 구간의 문구를 따른다.
      문구가 바뀐 뒤의 구간  「확정신고기한까지 예정신고분을 기한 후 신고로 내면 감면하는 규정」과 문구가 바뀐 날
      그 전 구간            「확정신고기한까지 신고하면 감면하는 규정」(조문은 「과세표준신고를 한 경우」다). 확정신고만 한 경우를
                            과세관청이 감면 대상으로 보지 않을 수 있어 적용하지 않았다고 적는다
    금액은 구간과 상관없이 같다(감면을 적용하지 않는다)."""
    head = "무신고가산세는 감면 없이 일반 무신고 율 %s 로 계산했다. " % _pct(rate)
    tail = "%s 무신고가산세는 %s원이다. 어느 쪽으로 신고할지 세무 전문가와 확인한다" % (RELIEF_CONDITION, _won(with_relief))
    article = _articles(rs, (RELIEF_KEY,), paid)
    if _new_wording_from(rs, paid):
        return (head + "예정신고를 하지 않았더라도 확정신고기한까지 예정신고분을 기한 후 신고로 내면 무신고가산세의 %s 를 감면하는 "
                "규정이 있다(%s). %s이 스킬은 기한 후 신고서를 만들지 않고 확정신고서를 만들므로 그 감면을 적용하지 않았다. "
                % (_pct(relief), article, _wording_sentence(rs, paid)) + tail)
    return (head + "예정신고를 하지 않았더라도 확정신고기한까지 신고하면 무신고가산세의 %s 를 감면하는 규정이 있다(%s). "
            "이 스킬은 예정신고분의 기한 후 신고서가 아니라 확정신고서를 만들므로, 확정신고만 한 경우를 과세관청이 감면 대상으로 "
            "보지 않을 수 있어 그 감면을 적용하지 않았다. " % (_pct(relief), article) + tail)


def _alternative(found, counts, rate, relief, daily):
    """같은 달에 다른 날 양도한 자산을 양도일마다 따로 신고하는 것으로 볼 때의 가산세. 그런 건이 없거나 정할 수 없으면 None.
    무신고는 감면을 적용하지 않은 금액, 무신고_감면적용은 규칙세트의 감면율 relief 를 곱한 금액이다."""
    if not any(c["양도일별"] is None or len(c["양도일별"]) >= 2 for c in found):
        return None
    if any(c["양도일별"] is None for c in found):
        return None
    flat = [(c, n, s) for c, n in zip(found, counts) for s in c["양도일별"]]
    taxes, ns = [s["예정신고세액"] for _, _, s in flat], [n for _, n, _ in flat]
    total, per, late = amounts(taxes, ns, rate, 0, daily)
    with_relief, _, _ = amounts(taxes, ns, rate, relief, daily)
    lines = [{"자산": s["자산"], "양도일": s["양도일"], "예정신고세액": s["예정신고세액"], "납부기한": c["납부기한"].isoformat(),
              "기한경과": n is not None, "일수": n or 0, "무신고": a, "납부지연": b}
             for (c, n, s), a, b in zip(flat, per, late)]
    return {"예정신고세액": sum(taxes), "무신고": total, "무신고_감면적용": with_relief, "납부지연": sum(late),
            "계": total + sum(late), "건": lines}


def _same_month_note(c, n, nonfiling, delay, rate, daily):
    """같은 달 다른 날 양도를 한 건으로 합산했다는 것과, 양도일마다 따로 신고하는 것으로 볼 때의 금액(감면을 적용하지 않은 금액)."""
    # 양도일은 건이 가진 자산별 양도일을 그대로 적는다(양도일별 세액을 정하지 못해 None 인 건도 같은 문장이 나온다)
    text = ("자산 %s: 같은 달에 양도해(%s) 예정신고 기한이 같다. 한 예정신고서로 신고했을 세액 %s원을 예정신고 세액으로 "
            "보았다(세율이 같은 자산은 과세표준을 합산한다). "
            % (", ".join(c["자산"]), ", ".join("%s %s" % (i, c["자산양도일"][i]) for i in c["자산"]), _won(c["예정신고세액"])))
    if c["양도일별"] is None:
        return text + "양도일마다 따로 신고하는 것으로 볼 때의 세액은 정하지 못했다"
    taxes = [s["예정신고세액"] for s in c["양도일별"]]
    text += "양도일마다 따로 신고하는 것으로 보면 예정신고 세액은 %s원" % _won(sum(taxes))
    if n is None:
        return text + "이다"
    alt, _, alt_late = amounts(taxes, [n] * len(taxes), rate, 0, daily)
    return text + (", 무신고가산세 %s원, 납부지연가산세 %s원이다(합산한 이 계산은 %s원, %s원)" % (_won(alt), _won(sum(alt_late)), _won(nonfiling), _won(delay)))


def final_return(result, facts, paid_on, rules_dir=None):
    """예정신고를 한 번도 하지 않은 확정신고의 가산세. paid_on 은 납부일(신고서 작성일)이다.

    돌려주는 값
      무신고, 납부지연, 계   원. 계 = 무신고 + 납부지연. 신고서에 적는 금액이다
      감면적용               무신고에 확정신고기한까지 신고한 경우의 감면을 넣었는지. 언제나 False 다(확정신고서에는 적용하지 않는다)
      무신고_감면적용        감면율을 곱한 무신고가산세. 예정신고분을 기한 후 신고로 내 감면이 적용될 때의 금액
      무신고_감면없음        감면율을 곱하지 않은 무신고가산세
      감면안내               감면을 어떻게 다뤘는지와 다른 쪽 금액을 적은 문장(확인사항에도 있다. 신고_확인.md 알림 절에 올린다)
      율, 감면율, 일이자율   규칙세트 값(문자열). 과세 자산이 없어 건이 없으면 규칙을 읽지 않아 None 이다
      건                     예정신고 건마다 자산·예정신고세액·기한말일·납부기한·기한경과·일수·무신고·무신고_감면적용·무신고_감면없음·납부지연
      열                     본지 세율구분 열마다 무신고·납부지연
      양도일별               같은 달에 다른 날 양도한 자산이 있을 때, 양도일마다 따로 신고하는 것으로 본 금액
                             (예정신고세액·무신고·무신고_감면적용·납부지연·계·건). 그런 건이 없으면 None. 계산에는 쓰지 않는다
      지방                   지방소득세 가산세(local 의 결과). 무신고·납부지연·계·건·열과 감면안내·가정안내를 싣는다
      확인사항, 근거         문장과 규칙세트 인용
    결과가 끝나지 않았거나 납부일이 없으면 ValueError, 정할 수 없는 경우는 Unsupported.
    """
    if not result or result.get("상태") != "완료" or not result.get("계산"):
        raise ValueError("계산이 끝난 결과가 아니라 가산세를 계산할 수 없다")
    paid = to_date(paid_on)
    if paid is None:
        raise ValueError("납부일(작성일)이 없어 가산세를 계산할 수 없다")
    if (facts.get("연간") or {}).get("기신고"):
        raise Unsupported("같은 해에 예정신고한 양도(기신고)가 있는 확정신고의 가산세는 계산하지 않는다. 예정신고를 한 번도 하지 않은 "
                          "확정신고만 다룬다", "미정")
    rs = ruleset.load(rules_dir)
    rows = result["계산"]["자산"]
    names = ["%s-%s" % (x["국내외분"], x["세율구분"]) for x in result["계산"].get("세율별") or []]
    found, notes = cases(rows, facts, rs)
    # 확정신고서에는 감면을 넣지 않는다(문언이 바뀌기 전 구간의 신고도 같다). 감면율은 대안 금액을 구할 때만 쓴다
    out = {"무신고": 0, "무신고_감면적용": 0, "무신고_감면없음": 0, "감면적용": False, "감면안내": None, "납부지연": 0, "계": 0,
           "율": None, "감면율": None, "일이자율": None, "납부일산입": None,
           "건": [], "열": {name: {"무신고": 0, "납부지연": 0} for name in names}, "양도일별": None,
           "지방": local([], rs, paid, names)[0], "확인사항": [], "근거": []}
    if not found:
        # 과세 자산이 없으면 건이 없다. 가산세 율을 읽지 않는다(납부일에 시행 중인 가산세 규칙이 없어도 0 을 돌려준다)
        return out
    rate, relief = rs.value(RATE_KEY, paid), rs.value(RELIEF_KEY, paid)
    daily, paid_day = rs.value(DAILY_KEY, paid), rs.value(PAID_DAY_KEY, paid)
    out.update(율=str(rate), 감면율=str(relief), 일이자율=str(daily), 납부일산입=bool(paid_day))

    assets = {a.get("id"): a for a in facts.get("자산") or []}
    final_due = min(dates.filing_deadline("확정", _deadline_base(r, assets.get(r["id"]) or {}, []), rs)[1]
                    for r in rows if not r["판정"]["전액비과세"])
    if paid > final_due:
        raise Unsupported("납부일 %s 이 확정신고 기한 %s 을 지났다. 기한 후 신고는 무신고가산세 감면이 달라 계산하지 않는다"
                          % (paid.isoformat(), final_due.isoformat()))

    counts = [days(c["납부기한"], paid, paid_day) for c in found]
    taxes = [c["예정신고세액"] for c in found]
    total, per_case, late = amounts(taxes, counts, rate, 0, daily)
    with_relief, with_relief_per_case, _ = amounts(taxes, counts, rate, relief, daily)

    for c, n, nonfiling, reduced, delay in zip(found, counts, per_case, with_relief_per_case, late):
        labels, weights = list(c["열"]), list(c["열"].values())
        for kind, amount in (("무신고", nonfiling), ("납부지연", delay)):
            for name, part in zip(labels, _split(amount, weights)):
                out["열"].setdefault(name, {"무신고": 0, "납부지연": 0})[kind] += part
        out["건"].append({"자산": c["자산"], "예정신고세액": c["예정신고세액"], "기한말일": c["기한말일"].isoformat(),
                         "납부기한": c["납부기한"].isoformat(), "기한경과": n is not None, "일수": n or 0,
                         "무신고": nonfiling, "무신고_감면적용": reduced, "무신고_감면없음": nonfiling, "납부지연": delay})
        if n is not None:       # 건마다 한 줄. 안내서 「가산세 계산」 표의 예정신고 세액, 납부기한, 일수, 금액과 같은 값이다
            # 일수의 끝 날은 규칙(가산세.납부지연.납부일산입)이 정한다. 2026-07-01 부터는 납부일 전날까지다
            notes.append("자산 %s: 예정신고 세액 %s원, 납부기한 %s, 일수 %d일(납부기한 다음 날부터 납부일 %s%s까지), 무신고가산세 %s원, "
                         "납부지연가산세 %s원이다"
                         % (", ".join(c["자산"]), _won(c["예정신고세액"]), c["납부기한"].isoformat(), n, paid.isoformat(),
                            " 전날" if not paid_day else "", _won(nonfiling), _won(delay)))
        if c["양도일별"] is None or len(c["양도일별"]) >= 2:
            notes.append(_same_month_note(c, n, nonfiling, delay, rate, daily))
        if n is None:
            notes.append("자산 %s: 납부일(%s)이 예정신고 납부기한(%s)을 지나지 않았다. 예정신고 기한 안이라 이 건에는 가산세를 계산하지 않았다"
                         % (", ".join(c["자산"]), paid.isoformat(), c["납부기한"].isoformat()))

    due_tax = sum(t for t, n in zip(taxes, counts) if n is not None)
    relief_note = _relief_note(rs, paid, rate, relief, with_relief)
    head = [
        "예정신고를 하지 않은 확정신고라 예정신고 무신고가산세 %s원과 납부지연가산세 %s원을 계산했다. 무신고가산세는 기한이 지난 건의 "
        "예정신고 세액 합계 %s원 × %s, 납부지연가산세는 건마다 예정신고 세액 × 일수 × 1일 10만분의 %s 이다(%s)"
        % (_won(total), _won(sum(late)), _won(due_tax), _pct(rate), format((Decimal(daily) * 100000).normalize(), "f"),
           _articles(rs, tuple(k for k in RULE_KEYS if k != RELIEF_KEY), paid)),
        relief_note,
        "납부일(%s) 기준으로 납부기한 다음 날부터 납부일%s까지 일수를 셌다. 실제 납부일이 다르면 납부지연가산세가 달라진다"
        % (paid.isoformat(), "" if paid_day else " 전날"),
        "부정행위로 신고하지 않은 경우의 무신고가산세 율은 다루지 않는다. 일반 무신고 율 %s 를 적용했다" % _pct(rate),
        "납부지연가산세는 건마다 %s원 미만을 버렸다(국세청 확정신고 작성 사례의 계산 근거와 같은 끝수 처리)" % LATE_UNIT,
    ]
    unknown = [c for c in found if not c["공휴일표"]]
    if unknown:     # 공휴일 표가 덮는 해의 기한은 공휴일까지 건너뛴 날이라 알릴 것이 없다
        head.append("자산 %s: 예정신고 납부기한이 끝나는 해가 공휴일 표에 없다. 토요일·일요일과 날짜가 고정된 공휴일·노동절만 건너뛰었고 "
                    "그 해의 설날·추석 연휴, 대체공휴일, 선거일, 임시공휴일은 건너뛰지 못했다. 납부기한이 그런 날이면 실제 기한은 "
                    "더 늦고 일수가 줄어든다" % ", ".join(i for c in unknown for i in c["자산"]))
    local_result, local_notes = local(found, rs, paid, names)
    for m in head + notes + local_notes:
        if m not in out["확인사항"]:
            out["확인사항"].append(m)
    out.update(지방=local_result)
    out.update(무신고=total, 무신고_감면적용=with_relief, 무신고_감면없음=total, 감면안내=relief_note, 납부지연=sum(late),
               계=total + sum(late), 양도일별=_alternative(found, counts, rate, relief, daily),
               근거=[c for key in RULE_KEYS for c in rs.cite(key, paid)])
    return out
