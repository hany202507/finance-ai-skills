"""DSD초안: 가상 회사(누리정밀(가상))의 작년 dsd 하나로 당기 초안을 만든다. 같은 파일이면 바이트까지 같고, sheet → build 와 본문이 같다."""
from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent / "scripts"), str(HERE)]

from dsd_company import make_company_dsd  # noqa: E402
from run import main as cli  # noqa: E402


def _contents(path: Path) -> bytes:
    with zipfile.ZipFile(path) as z:
        return z.read("contents.xml")


def test_draft_from_prior_dsd(tmp_path, capsys):
    prev = make_company_dsd(tmp_path / "작년.dsd", year=-1)
    a, b, c = tmp_path / "a", tmp_path / "b", tmp_path / "c"
    assert cli(["draft", str(prev), "--out", str(a)]) == 0
    out = capsys.readouterr().out
    assert "누리정밀(가상)" in out and "다음 기수 초안 →" in out and "초안 검산" in out
    stem = "누리정밀(가상)_2025_감사보고서_초안"
    dsd_a, book_a = a / f"{stem}.dsd", a / f"원고_{stem}.xlsx"
    assert dsd_a.exists() and book_a.exists() and (a / f"초안안내_원고_{stem}.txt").exists()
    issues = json.loads((a / f"원고검사_원고_{stem}.json").read_text(encoding="utf-8"))
    assert isinstance(issues, list) and not [x for x in issues if x.get("분류") == "초안 검산"]   # 만든 dsd 가 원고와 같다
    assert cli(["draft", str(prev), "--out", str(b)]) == 0
    capsys.readouterr()
    for name in (dsd_a.name, book_a.name):
        assert (a / name).read_bytes() == (b / name).read_bytes()                 # 같은 전기 파일이면 바이트까지 같다
    assert cli(["sheet", str(prev), "--roll", "--out", str(c)]) == 0
    assert cli(["build", str(c / "원고_작년.xlsx")]) == 0
    capsys.readouterr()
    assert _contents(dsd_a) == _contents(c / "작년_원고판.dsd")


def test_draft_rejects_bad_input(tmp_path, capsys):
    assert cli(["draft", str(tmp_path / "없음.dsd")]) == 2
    bad = tmp_path / "아님.dsd"
    bad.write_bytes(b"not a zip")
    assert cli(["draft", str(bad)]) == 2
    capsys.readouterr()
