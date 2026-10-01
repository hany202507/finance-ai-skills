# -*- coding: utf-8 -*-
"""return_review.py 를 합성 입력으로 돌린다.

자동 항목 18개를 어떻게 확인하는가

  끝까지 돌려서 검출   B2 · B4 · C5 · C7 · C8 · D5 · D6 · E1 · E3   (오류 fixture)
  함수에 변조 입력     A1 · A2 · A3 · A4 · C1 · C2 · C3 · C4 · C5 · C6 · C8

A군과 C1~C6·C8 의 대사는 같은 장부에서 본지와 부속명세를 함께 만들기 때문에 입력을
아무리 틀려도 끝까지 돌리면 0원으로 맞는다. 산출 코드가 틀렸을 때 걸리는 검사다.
그래서 verify_form · tie 에 값을 바꾼 본지와 부속명세를 직접 넣어 걸리는지 본다.
"""
import csv
import io
import os
import re
import shutil
import subprocess
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
SCRIPTS = os.path.join(SKILL, "scripts")
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, HERE)

import make_fixture as F          # noqa: E402
import return_review as RR        # noqa: E402
from ledger_io import _rows_from_csv  # noqa: E402

AUTO = {"A1", "A2", "A3", "A4", "B2", "B4", "C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8",
        "D5", "D6", "E1", "E3"}


def run(folder, out):
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1", VAT_NO_BROWSER="1")
    p = subprocess.run([sys.executable, os.path.join(SCRIPTS, "return_review.py"), folder, out],
                       capture_output=True, text=True, encoding="utf-8", env=env)
    return p


def findings(out):
    """확인사항 표에서 (검사, 항목) 을 읽는다."""
    md = [f for f in os.listdir(out) if f.startswith("확인사항_신고서_")][0]
    rows = []
    for line in io.open(os.path.join(out, md), encoding="utf-8"):
        m = re.match(r"^\| ([A-H]\d+) \| (.+?) \|", line)
        if m:
            rows.append((m.group(1), m.group(2)))
    return rows


def report(out):
    md = [f for f in os.listdir(out) if f.startswith("검토리포트_신고서_")][0]
    return io.open(os.path.join(out, md), encoding="utf-8").read()


@pytest.fixture(scope="module")
def made(tmp_path_factory):
    root = tmp_path_factory.mktemp("fx")
    good, bad, make = F.저장(str(root))
    return {"good": good, "bad": bad, "make": make, "root": str(root)}


def test_진단항목_자동은_18개다():
    cat = _rows_from_csv(os.path.join(SKILL, "rules", "진단항목.csv"))
    assert len(cat) == 40
    assert {r["번호"] for r in cat if r["수행"] == "자동"} == AUTO
    assert sum(r["수행"] == "검토자" for r in cat) == 20
    assert sum(r["수행"] == "자료 미확보" for r in cat) == 2


def test_본지가_손으로_더한_값과_같다(made):
    from ledger_io import _rows_from_xlsx
    rows = _rows_from_xlsx(os.path.join(made["good"], "매입매출장_2026-1기확정.xlsx"))
    fixed = {r["계정코드"] for r in _rows_from_csv(os.path.join(SKILL, "rules", "고정자산_계정.csv"))}
    form = {r[0]: r for r in RR.build(RR.rollup(rows, fixed), 5000)}
    for k, (sup, tax) in F.EXPECTED.items():
        assert (form[k][2], form[k][3]) == (sup, tax), k
    assert RR.verify_form(list(form.values())) == []


def test_정상판은_정지도_확인도_없다(made, tmp_path):
    p = run(made["good"], str(tmp_path))
    assert p.returncode == 0, p.stdout + p.stderr
    assert findings(str(tmp_path)) == []
    rep = report(str(tmp_path))
    assert "## 통과" in rep
    # 검토 범위에 40개가 전부 찍히고 자동 항목은 전부 통과다
    rows = re.findall(r"^\| ([A-H]\d+) \| .+? \| .+? \| (.+?) \| (.+?) \|$", rep, re.M)
    assert len(rows) == 40
    assert {no for no, how, res in rows if how == "자동" and res == "통과"} == AUTO
    for name in ("본지_대사_2026-04~06.xlsx", "부속명세_2026-04~06.xlsx",
                 "신고서_2026-04~06.html", "부속명세_2026-04~06.html"):
        assert os.path.exists(os.path.join(str(tmp_path), name)), name


def test_오류판은_자동항목을_하나씩_잡는다(made, tmp_path):
    p = run(made["bad"], str(tmp_path))
    assert p.returncode == 1, p.stdout + p.stderr
    got = findings(str(tmp_path))
    codes = {c for c, _ in got}
    assert codes == {"B2", "B4", "C5", "C7", "C8", "D5", "D6", "E1", "E3"}
    rep = report(str(tmp_path))
    stop = rep.split("## 정지")[1].split("## 확인")[0]
    ask = rep.split("## 확인")[1].split("## 부속명세 대사")[0]
    for c in ("B2", "B4", "C5", "C7", "C8", "D5", "D6"):
        assert f"[{c}]" in stop, c
    for c in ("E1", "E3"):
        assert f"[{c}]" in ask, c
    # C8 은 첨부서류 없음과 신고로 보지 않는 부분 두 줄. 0.5퍼센트 가산세 1,500원
    assert sum(c == "C8" for c, _ in got) == 2
    assert "가산세 1,500원" in rep
    # 근거 칸은 이 스킬의 진단항목 번호나 법령·서식만 가리킨다
    grounds = re.findall(r"^- 근거 : (.+)$", rep, re.M)
    assert grounds
    for g in grounds:
        assert re.search(r"진단항목|법|서식", g), g


def test_계산서_수취목록이_없으면_C7은_확인이다(made, tmp_path):
    src = tmp_path / "in"
    shutil.copytree(made["good"], src)
    os.remove(src / "tax_invoices.csv")
    out = tmp_path / "out"
    p = run(str(src), str(out))
    assert p.returncode == 0, p.stdout + p.stderr
    assert findings(str(out)) == [("C7", "계산서 수취목록 원천이 없어 계산서합계표를 대조하지 못했다")]


def test_전기_신고서가_없으면_E1_E3는_미실행으로_남는다(made, tmp_path):
    src = tmp_path / "in"
    shutil.copytree(made["good"], src)
    os.remove(src / "vat_return_prior.csv")
    out = tmp_path / "out"
    run(str(src), str(out))
    rep = report(str(out))
    assert "| E1 | 매출 증감률 | 확인 | 자동 | 미실행 (원천 없음: vat_return_prior) |" in rep
    assert "| E3 | 부담률 | 확인 | 자동 | 미실행 (원천 없음: vat_return_prior) |" in rep


# ── 끝까지 돌려서는 안 걸리는 검사: 함수에 변조 입력을 넣는다 ─────────────
def _mine(made):
    from ledger_io import _rows_from_xlsx
    rows = _rows_from_xlsx(os.path.join(made["good"], "매입매출장_2026-1기확정.xlsx"))
    fixed = {r["계정코드"] for r in _rows_from_csv(os.path.join(SKILL, "rules", "고정자산_계정.csv"))}
    zero = _rows_from_csv(os.path.join(SKILL, "rules", "영세율_구분.csv"))
    return rows, fixed, RR.build(RR.rollup(rows, fixed), 5000), zero


def _set(form, no, sup=None, tax=None):
    out = []
    for r in form:
        if r[0] == no:
            r = (r[0], r[1], r[2] if sup is None else sup, r[3] if tax is None else tax)
        out.append(r)
    return out


@pytest.mark.parametrize("no,lane,sup,tax", [
    ("A1", "(16)", 2_170_001, None),
    ("A2", "(18)", 1_870_001, None),
    ("A3", "㉰", None, 453_001),
    ("A4", "(30)", None, 448_001),
])
def test_A군_검증식은_본지_산식이_틀리면_걸린다(made, no, lane, sup, tax):
    _, _, form, _ = _mine(made)
    bad = RR.verify_form(_set(form, lane, sup, tax))
    assert no in {b[0] for b in bad}


def test_A1은_11란을_상수로_두지_않는다(made):
    """(11) 수출기업 수입 납부유예가 있으면 (16) 이 그만큼 줄어야 한다."""
    _, _, form, _ = _mine(made)
    bad = RR.verify_form(_set(form, "(11)", 10_000))
    assert "A1" in {b[0] for b in bad}


@pytest.mark.parametrize("no,sheet", [
    ("C1", "38호_매출처별"), ("C2", "39호_매입처별"), ("C3", "16호_수령명세서"),
    ("C4", "23호_발행금액집계표"), ("C5", "22호_공제받지못할"), ("C6", "27호_건물등취득"),
    ("C8", "29호_영세율매출명세서"),
])
def test_C군_대사는_부속명세가_한_줄_빠지면_걸린다(made, no, sheet):
    rows, fixed, form, zero = _mine(made)
    att = RR.attachments(rows, fixed, zero)
    assert att[sheet], sheet
    att[sheet] = att[sheet][1:]
    tie = {c["검사"]: c for c in RR.tie(att, form, RR.card_exempt_sales(rows))}
    assert tie[no]["공급가액 차이"] != 0


def test_C군_세액도_따로_본다(made):
    """공급가액은 맞고 세액만 1원 다르면 걸려야 한다. 건별 반올림 차이를 잡는 검사다."""
    rows, fixed, form, zero = _mine(made)
    att = RR.attachments(rows, fixed, zero)
    att["38호_매출처별"][0] = dict(att["38호_매출처별"][0], 세액=att["38호_매출처별"][0]["세액"] + 1)
    c1 = next(c for c in RR.tie(att, form, RR.card_exempt_sales(rows)) if c["검사"] == "C1")
    assert c1["공급가액 차이"] == 0 and c1["세액 차이"] == 1


def test_C4는_계산서_면세매출을_카드_집계표와_비교하지_않는다(made):
    """23호 면세 매출분은 카드·현금영수증 면세(18·23)만이다.
    원본은 면세수입금액 전체와 비교해 계산서 면세 매출(13)이 있으면 그만큼 어긋났다."""
    rows, fixed, form, zero = _mine(made)
    att = RR.attachments(rows, fixed, zero)
    old = next(c for c in RR.tie(att, form) if c["검사"] == "C4")
    new = next(c for c in RR.tie(att, form, RR.card_exempt_sales(rows)) if c["검사"] == "C4")
    assert old["공급가액 차이"] == -150_000
    assert new["공급가액 차이"] == 0


def test_22호는_사유별로_묶인다(made):
    rows, fixed, form, zero = _mine(made)
    att = RR.attachments(rows, fixed, zero)
    assert [r["사유"] for r in att["22호_공제받지못할"]] == ["④"]


@pytest.mark.parametrize("v,want", [
    ("4", "④"), (4, "④"), ("4.기업업무추진비", "④"), ("④", "④"), ("8", "⑧"),
    ("", ""), (None, ""), ("9", ""), ("0", ""), ("가", ""),
])
def test_불공제사유_읽기(v, want):
    assert RR.deny_mark(v) == want


def test_공개판_규칙에_식별정보가_없다():
    params = {r["항목"]: r["값"] for r in
              _rows_from_csv(os.path.join(SKILL, "rules", "신고_파라미터.csv"))}
    assert params["회사명"] == "(주)예시상사"
    for k in ("사업자등록번호", "대표자", "사업장 주소", "사업장 전화", "휴대전화", "전자우편"):
        assert params[k] == "", k


def test_영세율_매출명세서는_내국신용장을_부가가치세법_칸에_적는다(made):
    """내국신용장(과세유형 12)은 부가가치세법 제21조 영세율이다. 「그 밖의 법률」 칸이 아니다."""
    import attach_forms
    rows, fixed, form, zero = _mine(made)
    att = RR.attachments(rows, fixed, zero)
    html = attach_forms.f29(att["29호_영세율매출명세서"],
                            {"period": "", "company": "", "biz": "", "ceo": "", "addr": ""})
    i = html.index("⑪")
    assert "800,000" in html[i:html.index("⑫")]          # 직수출 300,000 + 내국신용장 500,000
    tail = html[html.index("⑫"):html.index("⑬")]
    assert "500,000" not in tail and "800,000" not in tail
    assert "<td class='l'>내국신용장·구매확인서에 의하여 공급하는 재화</td><td class='n'>500,000</td>" in html
