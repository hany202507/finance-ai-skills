# -*- coding: utf-8 -*-
"""예시 자료로 검산 PASS 와 9/30 숫자, 검산이 깨진 입력에서 멈추는지, 규칙 추가가 반영되는지 본다."""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

HERE = Path(__file__).resolve().parent
SKILL = HERE.parent
BUILD = SKILL / "scripts" / "build.py"
EX = SKILL / "examples"
RULES = SKILL / "assets" / "분류규칙_예시.md"
ENV = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")


def run(*args):
    return subprocess.run([sys.executable, str(BUILD), *map(str, args)], capture_output=True, text=True, encoding="utf-8", env=ENV)


def data(html):
    m = re.search(r"var DATA = (\{.*?\});\n", Path(html).read_text(encoding="utf-8"), re.S)
    return json.loads(m.group(1).replace("<\\/", "</"))


def copy_inputs(tmp_path):
    d = tmp_path / "in"
    d.mkdir()
    for n in ("bank_accounts.csv", "bank_transactions.csv", "cash_schedule.csv"):
        shutil.copy(EX / n, d / n)
    return d


def test_예시_검산_PASS_와_9월30일_숫자(tmp_path):
    out = tmp_path / "dash.html"
    r = run("--입력", EX, "--규칙", RULES, "--출력", out, "--회사", "글로우빔(주)", "--휴일", "2026-10-05,2026-10-09")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "검산 PASS" in r.stdout
    o = data(out)["by"]["2026-09-30"]
    assert (o["prev"], o["in"], o["out"], o["end"]) == (6_906_881_783, 243_131_400, 70_078_700, 7_079_934_483)
    assert o["prev"] + o["in"] - o["out"] == o["end"]
    assert [f[0] for f in o["flag"]] == ["(주)한빛상사 반환"]
    md = (tmp_path / "자금일보_2026-09-30.md").read_text(encoding="utf-8")
    assert "6,906,881,783 + 243,131,400 - 70,078,700 = 7,079,934,483" in md
    assert "{{" not in out.read_text(encoding="utf-8")


def test_모든_날짜_등식(tmp_path):
    out = tmp_path / "dash.html"
    assert run("--입력", EX, "--규칙", RULES, "--출력", out, "--md없음").returncode == 0
    D = data(out)
    prev = None
    for d in D["days"]:
        o = D["by"][d]
        assert o["prev"] + o["in"] - o["out"] == o["end"], d
        assert o["end"] == sum(a[3] for a in o["accs"]), d
        if prev is not None:
            assert o["prev"] == prev, d
        prev = o["end"]


def test_거래_한_줄이_빠지면_멈춘다(tmp_path):
    d = copy_inputs(tmp_path)
    t = pd.read_csv(d / "bank_transactions.csv", dtype=str)
    t.drop(index=100).to_csv(d / "bank_transactions.csv", index=False, encoding="utf-8-sig")
    out = tmp_path / "dash.html"
    r = run("--입력", d, "--규칙", RULES, "--출력", out)
    assert r.returncode == 2, r.stdout
    assert "검산 FAIL" in r.stdout and "[줄 잔액]" in r.stdout
    assert not out.exists()


def test_계좌_간_이체_한쪽을_놓치면_멈춘다(tmp_path):
    d = copy_inputs(tmp_path)
    t = pd.read_csv(d / "bank_transactions.csv", dtype=str)
    i = t.index[(t.counterparty == "내부이체") & (t.deposit != "0")][0]
    t.loc[i, ["counterparty", "description"]] = ["주거래 계좌", "자금 이동"]
    t.to_csv(d / "bank_transactions.csv", index=False, encoding="utf-8-sig")
    r = run("--입력", d, "--규칙", RULES, "--출력", tmp_path / "dash.html")
    assert r.returncode == 2, r.stdout
    assert "[날짜 합계]" in r.stdout


def test_기말_잔액이_다르면_멈춘다(tmp_path):
    d = copy_inputs(tmp_path)
    a = pd.read_csv(d / "bank_accounts.csv", dtype=str)
    col = [c for c in a.columns if c.startswith("closing_balance")][0]
    a.loc[0, col] = str(int(a.loc[0, col]) + 1)
    a.to_csv(d / "bank_accounts.csv", index=False, encoding="utf-8-sig")
    r = run("--입력", d, "--규칙", RULES, "--출력", tmp_path / "dash.html")
    assert r.returncode == 2 and "[기말 잔액]" in r.stdout


def test_규칙을_더하면_확인_필요가_준다(tmp_path):
    rules = tmp_path / "규칙.md"
    s = RULES.read_text(encoding="utf-8")
    s = s.replace("| 14 | 출금 |", "| 14 | 출금 | 반환 | 거래처 반환 | |\n| 15 | 출금 |", 1)
    rules.write_text(s, encoding="utf-8")
    out = tmp_path / "dash.html"
    r = run("--입력", EX, "--규칙", rules, "--출력", out, "--md없음")
    assert r.returncode == 0, r.stdout
    assert "전체 확인 필요 1건" in r.stdout
    assert data(out)["by"]["2026-09-30"]["flag"] == []


def test_최신순_내보내기도_같은_결과(tmp_path):
    d = copy_inputs(tmp_path)
    t = pd.read_csv(d / "bank_transactions.csv", dtype=str)
    t.iloc[::-1].to_csv(d / "bank_transactions.csv", index=False, encoding="cp949")
    o1, o2 = tmp_path / "a.html", tmp_path / "b.html"
    assert run("--입력", EX, "--규칙", RULES, "--출력", o1, "--md없음").returncode == 0
    assert run("--입력", d, "--규칙", RULES, "--출력", o2, "--md없음").returncode == 0
    assert data(o1) == data(o2)


def test_없는_기준일은_입력_오류(tmp_path):
    r = run("--입력", EX, "--규칙", RULES, "--출력", tmp_path / "dash.html", "--기준일", "2026-09-27")
    assert r.returncode == 1 and "입력 오류" in r.stdout


def test_기준일이_대시보드_첫_화면(tmp_path):
    out = tmp_path / "dash.html"
    assert run("--입력", EX, "--규칙", RULES, "--출력", out, "--기준일", "2026-09-22").returncode == 0
    assert '"def": "2026-09-22"' in out.read_text(encoding="utf-8")
    assert (tmp_path / "자금일보_2026-09-22.md").exists()


@pytest.mark.skipif(shutil.which("node") is None, reason="node 없음")
def test_대시보드_스크립트_문법(tmp_path):
    out = tmp_path / "dash.html"
    assert run("--입력", EX, "--규칙", RULES, "--출력", out, "--md없음").returncode == 0
    js = re.search(r"<script>([\s\S]*?)</script>", out.read_text(encoding="utf-8")).group(1)
    (tmp_path / "a.js").write_text(js, encoding="utf-8")
    r = subprocess.run(["node", "--check", str(tmp_path / "a.js")], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
