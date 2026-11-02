"""사업연도별 세율 표. 조서는 사업연도 개시일로 표를 고른다. 합성 장부만 쓴다.

  2025 이하   rates_2025.yaml(9 · 19 · 21 · 24%), 이전과 같다
  2026        rates_2026.yaml(10 · 20 · 22 · 25%, 법인세법 제55조 제1항 · 부칙 제21217호 제5조). 2026 판으로 확인하지 못한
              항목은 2025 값을 쓰고 등급을 ☆ 로 낮춘다
  2027 이후   표가 없으면 조서를 만들지 않고 멈춘다
"""
from __future__ import annotations

import csv
import json

import openpyxl
import pytest
import yaml

from ctax.tests.test_ar import journal, ledger, prior
from ctax.wp import cli as wp_cli
from ctax.wp.books import RATES_FILE, NoRates, load_rates, rate
from ctax.wp.summary import progressive_tax


def _items(rates):
    for group, items in rates.items():
        if isinstance(items, dict):
            for key, item in items.items():
                yield group, key, item


def test_2025_table_is_unchanged():
    base = load_rates()
    assert load_rates(fy_start="2025-01-01") == base and load_rates(fy_start="2025-07-01") == base
    assert rate(base, "corporate_tax", "brackets") == [[200000000, 0.09], [20000000000, 0.19], [300000000000, 0.21], [None, 0.24]]


def test_2026_brackets():
    r = load_rates(fy_start="2026-01-01")
    br = r["corporate_tax"]["brackets"]
    assert r["fy"] == "2026" and br["grade"] == "★★★"
    assert br["value"] == [[200000000, 0.10], [20000000000, 0.20], [300000000000, 0.22], [None, 0.25]]
    assert progressive_tax(20000000000, br["value"]) == 3980000000      # 39억8천만원
    assert progressive_tax(300000000000, br["value"]) == 65580000000    # 655억8천만원
    assert r["donation"]["social_enterprise_ratio"]["value"] == 0.3
    assert r["entertainment"]["onnuri_applies"]["value"] == 1


def test_2026_unchecked_items_are_star():
    r, base = load_rates(fy_start="2026-01-01"), load_rates()
    over = yaml.safe_load(RATES_FILE.with_name("rates_2026.yaml").read_text(encoding="utf-8"))
    for group, key, item in _items(r):
        assert item.get("grade") in ("★★★", "★★☆", "☆") and item.get("basis"), (group, key)
        if key not in (over.get(group) or {}):
            assert item["value"] == base[group][key]["value"], (group, key)
            assert item["grade"] == "☆" and item["basis"].startswith("2026 판 미확인"), (group, key)


def test_2027_has_no_table():
    with pytest.raises(NoRates, match="2027 사업연도 세율 표가 없습니다"):
        load_rates(fy_start="2027-01-01")


def _case(tmp_path, year):
    root = tmp_path / "가상회사" / f"{year} 법인세"
    idx = root / "_색인"
    idx.mkdir(parents=True)
    (idx / "장부.json").write_text(json.dumps(ledger(), ensure_ascii=False), encoding="utf-8")
    (idx / "전기.json").write_text(json.dumps(prior(fy=str(year - 1), fy_end=f"{year - 1}-12-31"), ensure_ascii=False),
                                  encoding="utf-8")
    rows = journal()
    with (idx / "전표.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    return root


def test_2026_case_uses_2026_rates(tmp_path):
    root = _case(tmp_path, 2026)
    assert wp_cli.main([str(root)]) in (0, 1)
    s = json.loads((root / "_색인" / "조정.json").read_text(encoding="utf-8"))["summary"]
    assert s["computed_tax"] == progressive_tax(s["tax_base"], rate(load_rates(fy_start="2026-01-01"), "corporate_tax", "brackets"))
    assert "기준 2026" in openpyxl.load_workbook(root / "2 조서" / "조서.xlsx").sheetnames


def test_2027_case_stops(tmp_path, capsys):
    root = _case(tmp_path, 2027)
    assert wp_cli.main([str(root)]) == 2
    assert "2027 사업연도 세율 표가 없습니다" in capsys.readouterr().out
    assert not (root / "_색인" / "조정.json").exists()
