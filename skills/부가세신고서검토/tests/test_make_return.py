# -*- coding: utf-8 -*-
"""make_return.py 와 PDF 쪽.

서식 원본(assets/별지21호_일반과세자_부가가치세신고서.pdf)이 스킬에 들어 있어 네트워크 없이 돈다.
브라우저 인쇄(HTML → PDF)는 테스트에서 끈다(VAT_NO_BROWSER). HTML 이 남는지만 본다.
"""
import os
import subprocess
import sys

import pytest

fitz = pytest.importorskip("fitz")

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
SCRIPTS = os.path.join(SKILL, "scripts")
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, HERE)

import make_fixture as F   # noqa: E402
import form21_pdf          # noqa: E402
import to_pdf              # noqa: E402


@pytest.fixture(scope="module")
def made(tmp_path_factory):
    root = tmp_path_factory.mktemp("mk")
    _, _, make = F.저장(str(root))
    out = os.path.join(str(root), "out")
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1", VAT_NO_BROWSER="1")
    p = subprocess.run([sys.executable, os.path.join(SCRIPTS, "make_return.py"), make, out],
                       capture_output=True, text=True, encoding="utf-8", env=env)
    return p, out


def test_서식_원본이_들어_있다():
    path = form21_pdf.find_form()
    assert path and os.path.basename(path) == form21_pdf.FORM_NAME
    with fitz.open(path) as d:
        head = d[0].get_text()[:120]
        assert d.page_count == 6
        assert not d.metadata.get("author")
    assert "별지 제21호서식" in head and "2026. 3. 20." in head


def test_한글_글꼴을_찾는다():
    font, buf, where = form21_pdf.load_font()
    assert buf and font.text_length("가나다", fontsize=8) > 0, where


def test_시스템_글꼴이_없으면_내장_CJK로_쓴다(tmp_path, monkeypatch):
    """한글 글꼴이 없는 리눅스 CI 를 흉내 낸다."""
    monkeypatch.setattr(form21_pdf, "_font_candidates", lambda: [])
    font, buf, where = form21_pdf.load_font()
    assert where == "PyMuPDF 내장 CJK"
    rows = [(k, "", a, b) for k, (a, b) in F.EXPECTED.items()]
    out = str(tmp_path / "x.pdf")
    path, err = form21_pdf.build(out, company="(주)예시상사", rows=rows, 확정=True,
                                 기간=(2026, 1, "01", "01", "06", "30"))
    assert err is None
    with fitz.open(path) as d:
        t = d[0].get_text()
    assert "(주)예시상사" in t and "448,000" in t


def test_신고서_PDF를_서식_원본에_채운다(made):
    p, out = made
    assert p.returncode == 0, p.stdout + p.stderr
    assert "검증식 A1~A4 통과" in p.stdout
    pdf = os.path.join(out, "신고서_2026-1기확정.pdf")
    with fitz.open(pdf) as d:
        assert d.page_count == 2
        t = d[0].get_text()
    for s in ("(주)예시상사", "7,200,000", "640,000", "453,000", "448,000"):
        assert s in t, s
    assert os.path.exists(os.path.join(out, "신고서_산출근거_2026-1기확정.xlsx"))


def test_채운_PDF를_되읽으면_값이_같다(made):
    """읽은 란은 전부 손계산과 같아야 한다."""
    _, out = made
    got, err = to_pdf.read_return_pdf(os.path.join(out, "신고서_2026-1기확정.pdf"))
    assert err is None
    assert len(got) >= 20
    for k, (_, _, sup, tax) in got.items():
        if k in F.EXPECTED:
            want_sup, want_tax = F.EXPECTED[k]
            assert (sup or 0) == (want_sup or 0) and (tax or 0) == want_tax, k


@pytest.mark.xfail(reason="읽기 코드는 더존 출력물에 맞춰져 있다. 공식 서식 원본에 값을 얹은 PDF 는 "
                          "(3)란 줄이 세로 머리 「과세」와 묶여 갈라지고, 면세수입금액은 제2쪽 "
                          "(85)란이라 못 읽는다", strict=True)
def test_채운_PDF에서_25란을_다_읽는다(made):
    _, out = made
    got, _ = to_pdf.read_return_pdf(os.path.join(out, "신고서_2026-1기확정.pdf"))
    assert "(3)" in got and "면세" in got


def test_브라우저가_없으면_HTML만_남긴다(tmp_path, monkeypatch):
    monkeypatch.setenv("VAT_NO_BROWSER", "1")
    html, pdf = tmp_path / "a.html", tmp_path / "a.pdf"
    assert to_pdf.write("<html><body>가</body></html>", str(html), str(pdf)) is False
    assert html.exists() and not pdf.exists()
