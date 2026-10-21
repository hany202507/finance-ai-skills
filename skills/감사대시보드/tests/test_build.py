"""예시 _색인 으로 대시보드를 만들어 단계 · 항목 · 이슈가 들어갔는지 본다."""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build  # noqa: E402

EX = ROOT / "examples" / "가온정밀(가상) 2025 기말감사"


def data_of(html: str) -> dict:
    s = html[html.index("const D = ") + len("const D = "):]
    return json.JSONDecoder().raw_decode(s)[0]


def test_example_builds(tmp_path):
    out = tmp_path / "d.html"
    assert build.main([str(EX), "--out", str(out)]) == 0
    d = data_of(out.read_text(encoding="utf-8"))
    assert [s["name"] for s in d["stages"]] == ["시작", "위험평가", "실행", "보고", "종결"]
    assert sum(len(s["items"]) for s in d["stages"]) == 27
    assert sum(len(i["wps"]) for s in d["stages"] for i in s["items"]) == 58
    assert d["issues_total"] == 10 and d["missing_total"] == 7 and d["demo"] is False


def test_issue_evidence_and_routing():
    d = build.build(EX / "_색인", demo=False)
    sales = next(i for s in d["stages"] for i in s["items"] if i["name"] == "매출 · 매출채권")
    i2 = next(x for x in sales["issues"] if x["no"] == 2)
    assert i2["role"] == "대응" and i2["origin"] == "2120A" and i2["response"] == "4000P"
    assert i2["evidence"][0]["diff"] == 1_500_000_000
    ana = next(i for s in d["stages"] for i in s["items"] if i["name"] == "분석적 검토")
    assert {x["role"] for x in ana["issues"]} == {"발견"}


def test_demo_overlays_status_only():
    plain = build.build(EX / "_색인", demo=False)
    demo = build.build(EX / "_색인", demo=True)
    st = lambda d: {w["no"]: w["status"] for s in d["stages"] for i in s["items"] for w in i["wps"]}
    assert st(demo)["2120A"] == "검사 통과" and st(demo)["4000P"] == "검토 요청"
    assert st(plain)["2120A"] != "검사 통과"
    assert plain["issues_total"] == demo["issues_total"]


def test_index_folder_or_audit_folder(tmp_path):
    a, b = tmp_path / "a.html", tmp_path / "b.html"
    build.main([str(EX), "--out", str(a)])
    build.main([str(EX / "_색인"), "--out", str(b)])
    assert a.read_text(encoding="utf-8") == b.read_text(encoding="utf-8")


def test_template_has_no_placeholder_left(tmp_path):
    out = tmp_path / "d.html"
    build.main([str(EX), "--out", str(out), "--demo"])
    html = out.read_text(encoding="utf-8")
    assert "/*__DATA__*/" not in html and re.search(r'"demo": true', html)
