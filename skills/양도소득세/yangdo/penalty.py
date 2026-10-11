# -*- coding: utf-8 -*-
"""예정신고를 하지 않은 확정신고의 가산세: 예정신고 무신고가산세와 납부지연가산세.

율은 rules/ruleset.json 에서 읽는다(가산세.무신고.율, 가산세.무신고.확정신고감면율, 가산세.납부지연.일이자율,
가산세.납부지연.납부일산입). 계산 방식과 끝수는 국세청 「2023년 유형별 확정신고 사례」(확정신고 작성 사례 09)의
「무신고 가산세」「납부지연 가산세」 계산 근거와 서식 가산세 줄을 따랐다. 대조 기록은 references/정답지.md 「가산세 대조」에 있다.

  건            예정신고 한 건. 예정신고 기한의 말일이 같은 과세 자산의 묶음이다(양도일이 속하는 달이 같은 자산,
                허가 전에 대금을 청산한 허가구역 토지는 허가일이 속하는 달)
  예정신고세액  그 건만 예정신고했을 때의 산출세액. 엔진 결과의 자산별 과세표준(기본공제를 먼저 양도한 자산부터 뺀 값)을
                같은 세율로 합산하는 자산끼리 더해 세율을 적용한다(사례 8). 다른 건의 양도소득금액과는 합산하지 않는다(사례 4·5)
  무신고        건별 예정신고세액의 합 × 율 × (1 − 감면율). 원 미만을 버린다(사례 8: 8,478,692 × 20% × 50% = 847,869).
                건별·열별 값은 건마다 원 미만을 버리고, 합계에 모자라는 원을 세액이 가장 큰 건에 더한다(사례 8 서식: 787,556 · 60,313)
  무신고_감면전 감면율을 곱하지 않은 금액. 끝수는 무신고와 같은 방식이다
  납부지연      건마다 예정신고세액 × 일수 × 일이자율. 10원 미만을 버린다(사례 2·4·5·8 의 모든 줄)
  일수          납부기한(토요일·일요일이면 다음 월요일) 다음 날부터 납부일 전날까지. 규칙 `가산세.납부지연.납부일산입` 이 1 인
                구간의 납부는 납부일까지
  열            본지 세율구분 열. 건의 가산세를 그 건의 세율구분별 세액 비율로 나눈다(원문 사례는 모두 건 하나가 열 하나다)

해석이 들어간 곳 둘은 결과와 확인사항에 다른 쪽 금액을 함께 싣는다.
  감면          확정신고기한까지 신고한 경우의 감면을 적용했다. 적용되지 않는 쪽의 금액이 무신고_감면전이다
  같은 달 양도  같은 달에 다른 날 양도한 자산을 한 건으로 합산했다. 양도일마다 따로 신고하는 쪽의 금액이 양도일별이다

납부일이 납부기한 이전인 건은 예정신고 기한 안이라 가산세가 없다.
건별 세액이나 납부기한을 조문과 원문 사례로 정할 수 없으면 Unsupported 로 멈춘다.
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
# 감면 조문의 근거 발췌에 이 글자가 있으면 문구가 바뀐 뒤의 구간이다(그 전 구간은 「과세표준신고를 한 경우」)
RELIEF_NEW_WORDING = "기한 후 신고를 한 경우"


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


def amounts(taxes, day_counts, rate, relief, daily):
    """건별 예정신고세액과 일수 → (무신고 합계, 건별 무신고, 건별 납부지연).

    일수가 None 인 건은 납부기한이 지나지 않은 건이라 0 이고 합계의 세액에도 넣지 않는다.
    무신고 합계는 세액의 합에 율을 곱해 원 미만을 버린다. 건별 값은 건마다 버린 뒤 모자라는 원을 세액이 가장 큰 건에 더한다.
    납부지연은 건마다 LATE_UNIT 원 미만을 버린다. relief 에 0 을 주면 감면 전 금액이다.
    """
    factor = Decimal(rate) * (1 - Decimal(relief))
    due = [i for i, d in enumerate(day_counts) if d is not None]
    total = calc.floor(Decimal(sum(taxes[i] for i in due)) * factor)
    per_case = [0] * len(taxes)
    late = [0] * len(taxes)
    for i in due:
        per_case[i] = calc.floor(Decimal(taxes[i]) * factor)
        late[i] = calc.floor(Decimal(taxes[i]) * day_counts[i] * Decimal(daily)) // LATE_UNIT * LATE_UNIT
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


def _tax(members, rs):
    """한 번에 예정신고하는 자산들의 세액. (세율구분 표기별 세액, 합).
    같은 세율로 합산하는 자산끼리 과세표준을 더해 세율을 적용한다. 세율이 다른 자산이 섞였고 합산 비교세액이 더 크면 정하지 않는다."""
    merged = {}
    for m in members:
        merged.setdefault(m["계산"]["합산묶음"], []).append(m)
    cols = {}
    for group in merged.values():
        anchor = calc.group_anchor(group)
        code = anchor["계산"]["코드"]
        base = sum(m["계산"]["과세표준"] for m in group)
        tax, _ = calc.rate_tax(anchor["판정"], base, rs, to_date(anchor["판정"]["양도일"]))
        name = "%s-%s" % (code["국내외분"], code["세율구분"])
        cols[name] = cols.get(name, 0) + tax
    tax = sum(cols.values())
    if len(merged) >= 2:
        first = min(to_date(m["판정"]["양도일"]) for m in members)
        whole = sum(m["계산"]["과세표준"] for m in members)
        compare = calc.floor(calc.progressive(whole, rs.value("기본세율", first)))
        if compare > tax:
            raise Unsupported(
                "자산 %s: 예정신고 기한이 같은 자산의 합산 비교세액 %s원이 세율별 세액의 합 %s원보다 크다. 이 경우의 예정신고 세액과 "
                "세율구분 열별 가산세는 국세청 작성 사례에 계산 방식이 없어 정하지 않았다"
                % (", ".join(m["id"] for m in members), compare, tax))
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
          "양도일별": [{"자산", "양도일", "예정신고세액"}] 또는 None}.
    양도일별은 건을 양도일마다 따로 신고하는 것으로 볼 때의 세액이다(양도일이 하나면 항목도 하나).
    rows 는 엔진 결과의 계산.자산이다. 과세표준과 합산 묶음, 세율구분 코드를 그대로 쓴다.
    """
    assets = {a.get("id"): a for a in facts.get("자산") or []}
    notes, grouped = [], {}
    for r in sorted(rows, key=lambda r: (r["판정"]["양도일"], r["id"])):
        if r["판정"]["전액비과세"]:
            continue
        nominal, adjusted = dates.filing_deadline("예정", _deadline_base(r, assets.get(r["id"]) or {}, notes), rs)
        grouped.setdefault(nominal, (adjusted, []))[1].append(r)
    out = []
    for nominal in sorted(grouped):
        adjusted, members = grouped[nominal]
        ids = [m["id"] for m in members]
        cols, tax = _tax(members, rs)
        if nominal != adjusted:
            notes.append("자산 %s: 예정신고 기한 말일 %s 이 %s요일이라 다음 월요일 %s 을 납부기한으로 보았다"
                         % (", ".join(ids), nominal.isoformat(), dates.WEEKDAY_KO[nominal.weekday()], adjusted.isoformat()))
        out.append({"자산": ids, "예정신고세액": tax, "기한말일": nominal, "납부기한": adjusted, "열": cols,
                    "양도일별": _by_sale_date(members, rs)})
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


def _relief_note(rs, paid, relief, gross):
    """감면을 적용했다는 전제와, 적용되지 않을 때의 금액. 문구가 바뀐 뒤의 구간이면 바뀐 날과 확정하지 못한 점을 적는다."""
    entry = rs.entry(RELIEF_KEY, paid)
    changed = any(RELIEF_NEW_WORDING in x for g in entry["근거"] for x in g["발췌"])
    text = "확정신고기한까지 신고하면 무신고가산세를 %s 감면하는 규정(%s)을 적용했다. " % (_pct(relief), _articles(rs, (RELIEF_KEY,), paid))
    if changed:
        text += ("이 규정의 문구가 %s 부터 「%s」로 바뀌었고, 확정신고서로 신고하는 것이 여기에 해당하는지는 이 도구가 확정하지 못했다. "
                 % (entry["시작"], RELIEF_NEW_WORDING))
    return text + "감면이 적용되지 않으면 무신고가산세는 %s원이다. 세무 전문가와 확인한다" % gross


def _alternative(found, counts, rate, relief, daily):
    """같은 달에 다른 날 양도한 자산을 양도일마다 따로 신고하는 것으로 볼 때의 가산세. 그런 건이 없거나 정할 수 없으면 None."""
    if not any(c["양도일별"] is None or len(c["양도일별"]) >= 2 for c in found):
        return None
    if any(c["양도일별"] is None for c in found):
        return None
    flat = [(c, n, s) for c, n in zip(found, counts) for s in c["양도일별"]]
    taxes, ns = [s["예정신고세액"] for _, _, s in flat], [n for _, n, _ in flat]
    total, per, late = amounts(taxes, ns, rate, relief, daily)
    gross, _, _ = amounts(taxes, ns, rate, 0, daily)
    lines = [{"자산": s["자산"], "양도일": s["양도일"], "예정신고세액": s["예정신고세액"], "납부기한": c["납부기한"].isoformat(),
              "기한경과": n is not None, "일수": n or 0, "무신고": a, "납부지연": b}
             for (c, n, s), a, b in zip(flat, per, late)]
    return {"예정신고세액": sum(taxes), "무신고": total, "무신고_감면전": gross, "납부지연": sum(late),
            "계": total + sum(late), "건": lines}


def _same_month_note(c, n, nonfiling, delay, rate, relief, daily):
    """같은 달 다른 날 양도를 한 건으로 합산했다는 것과, 양도일마다 따로 신고하는 것으로 볼 때의 금액."""
    text = ("자산 %s: 같은 달에 양도해(%s) 예정신고 기한이 같다. 한 예정신고서로 신고했을 세액 %s원을 예정신고 세액으로 "
            "보았다(세율이 같은 자산은 과세표준을 합산한다). "
            % (", ".join(c["자산"]), ", ".join("%s %s" % (i, s["양도일"]) for s in c["양도일별"] or [] for i in s["자산"])
               or "양도일이 둘 이상", c["예정신고세액"]))
    if c["양도일별"] is None:
        return text + "양도일마다 따로 신고하는 것으로 볼 때의 세액은 정하지 못했다"
    taxes = [s["예정신고세액"] for s in c["양도일별"]]
    text += "양도일마다 따로 신고하는 것으로 보면 예정신고 세액은 %s원" % sum(taxes)
    if n is None:
        return text + "이다"
    alt, _, alt_late = amounts(taxes, [n] * len(taxes), rate, relief, daily)
    return text + (", 무신고가산세 %s원, 납부지연가산세 %s원이다(합산한 이 계산은 %s원, %s원)" % (alt, sum(alt_late), nonfiling, delay))


def final_return(result, facts, paid_on, rules_dir=None):
    """예정신고를 한 번도 하지 않은 확정신고의 가산세. paid_on 은 납부일(신고서 작성일)이다.

    돌려주는 값
      무신고, 납부지연, 계   원. 계 = 무신고 + 납부지연
      무신고_감면전          감면율을 곱하지 않은 무신고가산세(감면이 적용되지 않는 쪽으로 해석될 때의 금액)
      율, 감면율, 일이자율   계산에 쓴 규칙세트 값(문자열)
      건                     예정신고 건마다 자산·예정신고세액·기한말일·납부기한·기한경과·일수·무신고·무신고_감면전·납부지연
      열                     본지 세율구분 열마다 무신고·납부지연
      양도일별               같은 달에 다른 날 양도한 자산이 있을 때, 양도일마다 따로 신고하는 것으로 본 금액
                             (예정신고세액·무신고·무신고_감면전·납부지연·계·건). 그런 건이 없으면 None. 계산에는 쓰지 않는다
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
                          "확정신고만 다룬다", "5")
    rs = ruleset.load(rules_dir)
    rate, relief = rs.value(RATE_KEY, paid), rs.value(RELIEF_KEY, paid)
    daily, paid_day = rs.value(DAILY_KEY, paid), rs.value(PAID_DAY_KEY, paid)
    rows = result["계산"]["자산"]
    names = ["%s-%s" % (x["국내외분"], x["세율구분"]) for x in result["계산"].get("세율별") or []]
    found, notes = cases(rows, facts, rs)
    out = {"무신고": 0, "무신고_감면전": 0, "납부지연": 0, "계": 0, "율": str(rate), "감면율": str(relief), "일이자율": str(daily),
           "건": [], "열": {name: {"무신고": 0, "납부지연": 0} for name in names}, "양도일별": None, "확인사항": [], "근거": []}
    if not found:
        return out

    assets = {a.get("id"): a for a in facts.get("자산") or []}
    final_due = min(dates.filing_deadline("확정", _deadline_base(r, assets.get(r["id"]) or {}, []), rs)[1]
                    for r in rows if not r["판정"]["전액비과세"])
    if paid > final_due:
        raise Unsupported("납부일 %s 이 확정신고 기한 %s 을 지났다. 기한 후 신고는 무신고가산세 감면이 달라 계산하지 않는다"
                          % (paid.isoformat(), final_due.isoformat()))

    counts = [days(c["납부기한"], paid, paid_day) for c in found]
    taxes = [c["예정신고세액"] for c in found]
    total, per_case, late = amounts(taxes, counts, rate, relief, daily)
    gross, gross_per_case, _ = amounts(taxes, counts, rate, 0, daily)

    for c, n, nonfiling, before, delay in zip(found, counts, per_case, gross_per_case, late):
        labels, weights = list(c["열"]), list(c["열"].values())
        for kind, amount in (("무신고", nonfiling), ("납부지연", delay)):
            for name, part in zip(labels, _split(amount, weights)):
                out["열"].setdefault(name, {"무신고": 0, "납부지연": 0})[kind] += part
        out["건"].append({"자산": c["자산"], "예정신고세액": c["예정신고세액"], "기한말일": c["기한말일"].isoformat(),
                         "납부기한": c["납부기한"].isoformat(), "기한경과": n is not None, "일수": n or 0,
                         "무신고": nonfiling, "무신고_감면전": before, "납부지연": delay})
        if c["양도일별"] is None or len(c["양도일별"]) >= 2:
            notes.append(_same_month_note(c, n, nonfiling, delay, rate, relief, daily))
        if n is None:
            notes.append("자산 %s: 납부일(%s)이 예정신고 납부기한(%s)을 지나지 않았다. 예정신고 기한 안이라 이 건에는 가산세를 계산하지 않았다"
                         % (", ".join(c["자산"]), paid.isoformat(), c["납부기한"].isoformat()))

    due_tax = sum(t for t, n in zip(taxes, counts) if n is not None)
    head = [
        "예정신고를 하지 않은 확정신고라 예정신고 무신고가산세 %s원과 납부지연가산세 %s원을 계산했다. 무신고가산세는 기한이 지난 건의 "
        "예정신고 세액 합계 %s원 × %s × (1 − %s), 납부지연가산세는 건마다 예정신고 세액 × 일수 × 1일 10만분의 %s 이다(%s)"
        % (total, sum(late), due_tax, _pct(rate), _pct(relief), format((Decimal(daily) * 100000).normalize(), "f"),
           _articles(rs, RULE_KEYS, paid)),
        _relief_note(rs, paid, relief, gross),
        "납부일(%s) 기준으로 납부기한 다음 날부터 납부일%s까지 일수를 셌다. 실제 납부일이 다르면 납부지연가산세가 달라진다"
        % (paid.isoformat(), "" if paid_day else " 전날"),
        "부정행위로 신고하지 않은 경우의 무신고가산세 율과, 과세표준과 세액을 경정할 것을 미리 알고 신고해 감면이 없는 경우는 다루지 않는다. "
        "일반 무신고 율 %s 와 감면 %s 를 적용했다" % (_pct(rate), _pct(relief)),
        "납부지연가산세는 건마다 %s원 미만을 버렸다(국세청 확정신고 작성 사례의 계산 근거와 같은 끝수 처리)" % LATE_UNIT,
        "납부기한의 끝이 공휴일·대체공휴일·노동절이면 그 다음 날이 기한이라 일수가 줄어든다. 이 계산은 토요일·일요일만 옮겼다",
    ]
    for m in head + notes:
        if m not in out["확인사항"]:
            out["확인사항"].append(m)
    out.update(무신고=total, 무신고_감면전=gross, 납부지연=sum(late), 계=total + sum(late),
               양도일별=_alternative(found, counts, rate, relief, daily),
               근거=[c for key in RULE_KEYS for c in rs.cite(key, paid)])
    return out
