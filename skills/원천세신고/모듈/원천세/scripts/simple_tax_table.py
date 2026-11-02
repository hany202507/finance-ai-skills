# -*- coding: utf-8 -*-
"""근로소득 간이세액표 — 소득세법 시행령 [별표 2] (제189조제1항 관련).

원칙: 표 세액·자녀공제·고액 기준액은 **원문 조견표를 적재**(1원 대사). 조회·산식 로직만 결정론.
      효력일자로 이력화 — 표 개정(예: 2026.3.1) 전후 급여를 각각 정확히 계산.

별표2 §2 공제대상가족수: 본인·배우자 각 1명 포함.
별표2 §3 자녀세액공제(8세~20세): **개정으로 갈림** → ref_child_credit(효력일자).
         2024.3.1판 12,500/29,160/+25,000 → 2026.3.1판 20,830/45,830/+33,330.
별표2 §4 가족수 11명 초과: (11명 세액) − (10명 세액 − 11명 세액) × 초과수.
별표2 §6 월급여 10,000천원 초과: (10,000천원 세액) + 구간별 산식.
소득령 §194: 80/120% 선택분은 간이세액에 비율 적용.

데이터: data/gani_YYYY-MM-DD.json (tools/parse_gani_xlsx.py로 조견표 원문에서 생성).
"""
import json
import os
from decimal import Decimal, ROUND_DOWN

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

만원 = 10_000_000      # 별표2 §6 기준점(월급여 10,000천원)

# 별표2 §6 고액 산식: (하한, 상수, 98%적용, 세율, 추가상수). 하한 초과 ~ 다음 하한 이하.
# 구간 이음매가 자기정합(14,000 지점 = 상수 1,397,000 등) — 테스트로 검증.
고액구간 = [
    (10_000_000, 0,          True,  Decimal("0.35"), 25_000),
    (14_000_000, 1_397_000,  True,  Decimal("0.38"), 0),
    (28_000_000, 6_610_600,  True,  Decimal("0.40"), 0),
    (30_000_000, 7_394_600,  False, Decimal("0.40"), 0),
    (45_000_000, 13_394_600, False, Decimal("0.42"), 0),
    (87_000_000, 31_034_600, False, Decimal("0.45"), 0),
]
근로소득_반영률 = Decimal("0.98")


def _floor(dec):
    return int(dec.to_integral_value(rounding=ROUND_DOWN))


def load_official(conn, path=None, *, eff_to=None):
    """조견표 JSON(원문 파싱본)을 적재. eff_from은 JSON에 담겨 있다. 적재 행수 반환."""
    path = path or os.path.join(DATA_DIR, "gani_2026-03-01.json")
    with open(path, encoding="utf-8") as fh:
        d = json.load(fh)
    eff = d["eff_from"]
    rows = [(lo * 1000, hi * 1000, dep, tax, eff, eff_to)
            for lo, hi, taxes in d["brackets"]
            for dep, tax in enumerate(taxes, start=1)]
    conn.executemany(
        "INSERT INTO ref_simple_tax_table(pay_min,pay_max,dependents,tax,eff_from,eff_to) "
        "VALUES(?,?,?,?,?,?)", rows)
    c = d["child_credit"]
    conn.execute("INSERT INTO ref_child_credit(one,two,extra,eff_from,eff_to) VALUES(?,?,?,?,?)",
                 (c["one"], c["two"], c["extra"], eff, eff_to))
    conn.executemany(
        "INSERT INTO ref_gani_base10000(dependents,tax,eff_from,eff_to) VALUES(?,?,?,?)",
        [(dep, tax, eff, eff_to) for dep, tax in enumerate(d["base_10000"], start=1)])
    conn.commit()
    return len(rows)


def 자녀세액공제(conn, 자녀8_20세수, on_date):
    """별표2 §3 — 효력일자 기준 자녀공제액."""
    n = 자녀8_20세수
    if n <= 0:
        return 0
    r = conn.execute(
        "SELECT one,two,extra FROM ref_child_credit "
        "WHERE eff_from<=? AND (eff_to IS NULL OR eff_to>=?) ORDER BY eff_from DESC LIMIT 1",
        (on_date, on_date)).fetchone()
    if r is None:
        raise LookupError(f"자녀공제 미적재: {on_date}. 별표2 원문 적재 필요.")
    if n == 1:
        return r["one"]
    if n == 2:
        return r["two"]
    return r["two"] + (n - 2) * r["extra"]


def _표세액(conn, 월급여, 가족수, on_date):
    row = conn.execute(
        "SELECT tax FROM ref_simple_tax_table WHERE dependents=? "
        "AND pay_min<=? AND pay_max>? AND eff_from<=? AND (eff_to IS NULL OR eff_to>=?) "
        "ORDER BY eff_from DESC LIMIT 1",
        (가족수, 월급여, 월급여, on_date, on_date)).fetchone()
    if row is None:
        raise LookupError(
            f"간이세액표 미적재 구간: {on_date} 월급여 {월급여} 가족 {가족수}. 원문 적재 필요.")
    return row[0]


def _base10000(conn, 가족수, on_date):
    row = conn.execute(
        "SELECT tax FROM ref_gani_base10000 WHERE dependents=? "
        "AND eff_from<=? AND (eff_to IS NULL OR eff_to>=?) ORDER BY eff_from DESC LIMIT 1",
        (가족수, on_date, on_date)).fetchone()
    if row is None:
        raise LookupError(f"10,000천원 기준액 미적재: {on_date} 가족 {가족수}")
    return row[0]


def _고액세액(conn, 월급여, 가족수, on_date):
    """별표2 §6 — 월급여 10,000천원 초과 산식."""
    base = _base10000(conn, 가족수, on_date)
    if 월급여 == 만원:
        return base
    구간 = [g for g in 고액구간 if 월급여 > g[0]][-1]
    하한, 상수, 반영, 세율, 추가 = 구간
    초과 = Decimal(월급여 - 하한)
    if 반영:
        초과 = 초과 * 근로소득_반영률
    return base + 상수 + _floor(초과 * 세율) + 추가


def _가족수세액(conn, 월급여, 가족수, on_date):
    """가족수별 표 세액(11명 초과·고액 산식 포함)."""
    if 가족수 > 11:
        # 별표2 §4
        t11 = _가족수세액(conn, 월급여, 11, on_date)
        t10 = _가족수세액(conn, 월급여, 10, on_date)
        return t11 - (t10 - t11) * (가족수 - 11)
    if 월급여 >= 만원:
        return _고액세액(conn, 월급여, 가족수, on_date)
    return _표세액(conn, 월급여, 가족수, on_date)


def lookup(conn, 월급여_과세, 공제대상가족수, *, on_date, 자녀8_20세수=0, 비율=100):
    """간이세액표 월 소득세(원). 표/산식 세액 − 자녀공제 → 비율 적용, 음수 0.

    월급여_과세: 비과세·학자금 제외 월급여. on_date: 지급일(효력일자 판정).
    """
    fam = max(공제대상가족수, 1)
    base = _가족수세액(conn, 월급여_과세, fam, on_date)
    base = max(0, base - 자녀세액공제(conn, 자녀8_20세수, on_date))
    if 비율 != 100:
        base = _floor(Decimal(base) * Decimal(비율) / Decimal(100))
    return base


def seed_row(conn, *, pay_min, pay_max, dependents, tax, eff_from="2024-03-01", eff_to=None):
    """조견표 1행 적재(테스트·부분 보정용)."""
    conn.execute(
        "INSERT INTO ref_simple_tax_table(pay_min,pay_max,dependents,tax,eff_from,eff_to) "
        "VALUES(?,?,?,?,?,?)", (pay_min, pay_max, dependents, tax, eff_from, eff_to))
    conn.commit()
