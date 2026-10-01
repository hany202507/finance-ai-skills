# -*- coding: utf-8 -*-
"""리스회계 엔진 테스트. 계약 조건은 전부 합성값이다.

엔진 값은 닫힌 식(연금 현재가치)과, 엑셀 수식은 formulas 독립 재계산과 맞춰 본다.
"""
import json
import os
import subprocess
import sys

import openpyxl
import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(HERE, "..", "scripts")
sys.path.insert(0, SCRIPTS)
import lease_engine  # noqa: E402

BASE = {
    "계약명": "합성-사무실-01", "개시일": "2026-01-01", "리스기간_개월": 36,
    "월리스료": 2_000_000, "부가세구분": "별도",
    "연할인율": 0.06, "할인율_출처": "합성 테스트 가정",
    "지급시점": "선급", "상각기간_개월": 0,
    "보증금": 0, "리스개설직접원가": 0, "선급리스료": 0,
    "리스인센티브": 0, "복구원가추정": 0,
    "매수선택권": False, "단기소액면제": False,
}


def cond(**kw):
    c = dict(BASE)
    c.update(kw)
    return c


def run(tmp_path, c, name="t"):
    cp = tmp_path / ("조건_%s.json" % name)
    cp.write_text(json.dumps(c, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / ("리스회계_%s.xlsx" % name)
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "lease_engine.py"), str(cp), str(out)],
                       capture_output=True, text=True, encoding="utf-8", env=env)
    res = json.loads((tmp_path / ("리스회계_%s_result.json" % name)).read_text(encoding="utf-8"))
    return r, out, res


def verify(out):
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    return subprocess.run([sys.executable, os.path.join(SCRIPTS, "verify_lease.py"), str(out)],
                          capture_output=True, text=True, encoding="utf-8", env=env)


def annuity(pmt, i, n, due):
    pv = pmt * (1 - (1 + i) ** -n) / i
    return pv * (1 + i) if due else pv


def journal(out):
    ws = openpyxl.load_workbook(out)["전표"]
    rows = []
    for r in ws.iter_rows(min_row=2, values_only=True):
        if r[3] and r[1] is not None:
            rows.append(r)
    return rows


# ---------------------------------------------------------------- 엔진 값

@pytest.mark.parametrize("due", [True, False])
def test_현재가치_닫힌식(due):
    c = cond(지급시점="선급" if due else "후급")
    e = lease_engine.compute(c)
    assert e["pv"] == pytest.approx(annuity(2_000_000, 0.06 / 12, 36, due), abs=1e-4)  # 부동소수 누적오차, 1원의 만분의 일
    assert abs(e["liab_end"]) < 1e-6
    assert abs(e["dep_end"]) < 1e-6
    assert e["total_pmt"] - e["pv"] == pytest.approx(e["total_interest"], abs=1e-6)


def test_부가세_포함이면_공급가액으로():
    e = lease_engine.compute(cond(월리스료=2_200_000, 부가세구분="포함"))
    assert e["pmt"] == pytest.approx(2_000_000, abs=1e-6)


def test_보증금은_리스부채에_안_들어간다():
    a = lease_engine.compute(cond())
    b = lease_engine.compute(cond(보증금=20_000_000))
    assert a["pv"] == pytest.approx(b["pv"])
    assert b["debit"] - a["debit"] == 20_000_000


def test_매수선택권이면_상각기간이_길다():
    e = lease_engine.compute(cond(상각기간_개월=60, 매수선택권=True))
    assert e["m"] == 60 and len(e["dep_rows"]) == 60
    assert abs(e["dep_end"]) < 1e-6


# ---------------------------------------------------------------- 엑셀·검산

@pytest.mark.parametrize("name,kw", [
    ("선급", {}),
    ("후급", {"지급시점": "후급"}),
    ("보증금", {"보증금": 20_000_000}),
    ("부가세포함", {"월리스료": 2_200_000, "부가세구분": "포함"}),
    ("구성요소", {"리스개설직접원가": 1_234_567, "선급리스료": 333_333,
                 "리스인센티브": 777_777, "복구원가추정": 4_567_891}),
    ("매수선택권", {"상각기간_개월": 60, "매수선택권": True}),
])
def test_엔진과_수식이_일치한다(tmp_path, name, kw):
    r, out, res = run(tmp_path, cond(**kw), name)
    assert r.returncode == 0, r.stdout + r.stderr
    assert res["all_pass"]
    assert res["전표_차변합"] == res["전표_대변합"]
    v = verify(out)
    assert v.returncode == 0, v.stdout + v.stderr
    assert "ALL_PASS: True" in v.stdout


def test_개시_전표는_구성요소마다_상대계정이_다르다(tmp_path):
    kw = {"리스개설직접원가": 1_234_567, "선급리스료": 333_333,
          "리스인센티브": 777_777, "복구원가추정": 4_567_891}
    r, out, res = run(tmp_path, cond(**kw), "구성요소")
    first = [row for row in journal(out) if row[1] == 1]
    accts = {row[3] for row in first}
    assert {"사용권자산", "리스부채", "선급리스료", "보통예금", "복구충당부채"} <= accts
    # 수식 셀은 openpyxl 로 값을 못 읽으므로 계정·방향만 본다. 인센티브는 차변이다
    incent = [row for row in first if row[2] == "리스개시-리스인센티브 수령"]
    assert len(incent) == 1 and incent[0][4] is not None and incent[0][5] is None


def test_단기리스는_면제_플래그(tmp_path):
    r, out, res = run(tmp_path, cond(리스기간_개월=12), "단기")
    assert res["단기소액면제_플래그"] is True
    r, out, res = run(tmp_path, cond(리스기간_개월=12, 매수선택권=True), "단기매수")
    assert res["단기소액면제_플래그"] is False
