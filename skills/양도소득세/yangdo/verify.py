# -*- coding: utf-8 -*-
"""독립 검산. 판정 경로와 상관없는 사실과 닫힌 식으로 엔진 값을 다시 본다.
워크북과 엔진이 맞는 것은 판정이 맞다는 증거가 아니다. 둘이 같은 판정을 쓰기 때문이다."""
import calendar
from datetime import date
from decimal import Decimal

from yangdo import calc, workbook

STEP = 1_000_000


def _years(a, b):
    a, b = date.fromisoformat(a), date.fromisoformat(b)
    day = min(a.day, calendar.monthrange(b.year, a.month)[1])
    return b.year - a.year - ((b.month, b.day) < (a.month, day))


def closed_ltd(v):
    """장기보유특별공제율의 닫힌 식(소득세법 제95조② 표1·표2). 규칙세트를 읽지 않는다.
    법이 바뀌어 규칙세트가 달라지면 V2 가 실패해 알려 준다. 그때 이 식도 원문대로 고친다."""
    y, r = v["보유년"], v["거주년"]
    if v["장특공"] == "표1":
        return min(Decimal("0.30"), Decimal("0.02") * y) if y >= 3 else Decimal(0)
    if v["장특공"] == "표2":
        live = min(Decimal("0.40"), Decimal("0.04") * r) if r >= 2 else Decimal(0)
        return min(Decimal("0.40"), Decimal("0.04") * y) + live
    return Decimal(0)


def _marginal(x, table):
    rate = table[0][2]
    for low, _, r in table:
        if x > low:
            rate = r
    return rate


def check(result, f, rs):
    fails, 공제합 = [], 0
    assets = {a["id"]: a for a in f["자산"]}
    for row in result["자산"]:
        v, c, a, aid = row["판정"], row["계산"], assets[row["id"]], row["id"]
        on = date.fromisoformat(v["양도일"])
        if v["전액비과세"]:
            if a["전체양도가액"] > rs.value("고가주택기준", on) or c["산출세액"] or c["지방소득세"]:
                fails.append("V1 %s: 전액비과세인데 양도가액 %s 또는 세액이 기준을 벗어난다" % (aid, a["전체양도가액"]))
            continue
        if Decimal(c["장특공률"]) != closed_ltd(v):
            fails.append("V2 %s: 장특공률 %s, 닫힌 식 %s" % (aid, c["장특공률"], closed_ltd(v)))
        if (v["중과"] or v["미등기"]) and c["장특공"]:
            fails.append("V3 %s: 중과·미등기인데 장특공 %s" % (aid, c["장특공"]))
        공제합 += c["기본공제"]
        if c["과세표준"] != c["양도소득금액"] - c["기본공제"]:
            fails.append("V4 %s: 과세표준이 양도소득금액 - 기본공제와 다르다" % aid)
        base = c["과세표준"]
        if calc.rate_tax(v, base, rs, on)[1] == "누진":
            table = rs.value("기본세율", on)
            if _marginal(base + 1, table) == _marginal(base + STEP, table) and \
                    calc.rate_tax(v, base + STEP, rs, on)[1] == "누진":
                d = calc.rate_tax(v, base + STEP, rs, on)[0] - calc.rate_tax(v, base, rs, on)[0]
                want = STEP * (_marginal(base + 1, table) + calc.rates(v, rs, on)["가산"])
                if abs(Decimal(d) - want) > 1:
                    fails.append("V5 %s: 과표 %s원 증분 세액 %s, 한계세율로 %s" % (aid, STEP, d, want))
        if abs(c["지방소득세"] * 10 - c["산출세액"]) > 10:
            fails.append("V6 %s: 지방소득세 %s, 산출세액 %s" % (aid, c["지방소득세"], c["산출세액"]))
        if c["과세양도차익"] > max(c["양도차익"], 0) or c["산출세액"] < 0:
            fails.append("V7 %s: 과세양도차익 또는 산출세액 범위 오류" % aid)
        if v["보유년"] != _years(v["취득일"], v["양도일"]):
            fails.append("V8 %s: 보유년 %s, 날짜로 센 값 %s" % (aid, v["보유년"], _years(v["취득일"], v["양도일"])))
        if v["고가주택"]:
            P = a["전체양도가액"]
            want = Decimal(c["양도차익"]) * (P - c["고가주택기준"]) / P
            if abs(Decimal(c["과세양도차익"]) - want) > 1:
                fails.append("V9 %s: 고가주택 과세양도차익 %s, 닫힌 식 %s" % (aid, c["과세양도차익"], want))
    first = min(date.fromisoformat(r["판정"]["양도일"]) for r in result["자산"])
    if 공제합 > rs.value("기본공제", first):
        fails.append("V4: 기본공제 합 %s 이 한도를 넘는다" % 공제합)
    fails += _totals(result)
    return fails


def _totals(result):
    """합계. 산출세액은 같은 세율 자산을 합산한 호별 합산 세액(제104조⑤2호)과 합산 비교 세액 중 큰 값이다."""
    t, rows = result["합계"], result["자산"]
    fails = []
    if t["산출세액"] != max(t["호별합산세액"], t["합산비교세액"]):
        fails.append("V10: 산출세액 %s 이 max(호별 합산 %s, 합산 비교 %s) 와 다르다"
                     % (t["산출세액"], t["호별합산세액"], t["합산비교세액"]))
    if t["지방소득세"] != max(t["지방_호별합산"], t["지방_합산비교"]):
        fails.append("V10: 지방소득세 %s 이 max(호별 합산 %s, 합산 비교 %s) 와 다르다"
                     % (t["지방소득세"], t["지방_호별합산"], t["지방_합산비교"]))
    if t["자산별세액"] != sum(r["계산"]["산출세액"] for r in rows) or \
            t["지방_자산별"] != sum(r["계산"]["지방소득세"] for r in rows):
        fails.append("V10: 자산별 세액 합이 자산 행의 합과 다르다")
    if t["과세표준"] != sum(r["계산"]["과세표준"] for r in rows):
        fails.append("V10: 합계 과세표준이 자산 행의 합과 다르다")
    return fails


def check_workbook(path, result):
    return workbook.compare(path, result)
