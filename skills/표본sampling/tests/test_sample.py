"""표본sampling: 리스트 파일 하나로 표본 설계 · 추출 · 평가 조서를 만든다.
자료는 시험이 만드는 가상 매출 원장이다(가상 회사 가온정밀(가상), 실제 자료 아님). 엑셀이 있는 PC 에서는 엑셀 수식 평가와 엔진 평가(sample eval)를 대조한다."""
from __future__ import annotations

import random
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest
from openpyxl import Workbook, load_workbook

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent / "scripts"), str(HERE)]

from audit import dataset, sample_wp, wp  # noqa: E402
from audit.workpapers import sampling_eval as se  # noqa: E402

TM = 300_000_000
FY_END = "2025-12-31"
ROWS = 1200


def _ledger(path: Path) -> dict:
    """가상 매출 원장. 제목 줄 · 빈 줄 뒤 머리줄, 반품(음수) 13건, 고액 8건, 합계 행 1, 결산일 뒤 거래 1건."""
    rng = random.Random(7)
    wb = Workbook()
    ws = wb.active
    ws.title = "매출장"
    ws.append(["(주)가온정밀(가상) 매출 원장"])
    ws.append([])
    ws.append(["전표일자", "전표번호", "거래처명", "품목", "구분", "공급가액", "세액", "합계금액"])
    neg = big = 0
    for i in range(ROWS):
        d = date(2025, 1, 1) + timedelta(days=rng.randrange(365))
        kind = rng.choice(["제품", "제품", "상품", "수출"])
        amt = round(rng.lognormvariate(14.5, 1.1), -3)
        if i % 150 == 5:
            amt, big = 150_000_000 + i * 1000, big + 1
        if i % 97 == 0:
            amt, neg = -amt / 10, neg + 1
        ws.append([d, f"S-{i:05d}", f"거래처{rng.randrange(1, 41):02d}", f"품목{rng.randrange(30)}", kind, amt, round(amt * 0.1),
                   round(amt * 1.1)])
    ws.append([None, None, "합계", None, None, 0, 0, 0])
    ws.append([date(2026, 1, 3), "S-99999", "거래처01", "품목1", "제품", 5_000_000, 500_000, 5_500_000])
    wb.save(path)
    return {"neg": neg, "big": big}


@pytest.fixture(scope="module")
def data(tmp_path_factory):
    d = tmp_path_factory.mktemp("sample")
    p = d / "매출원장.xlsx"
    info = _ledger(p)
    return p, info


def _make(data_path, out, **k):
    k.setdefault("fy_end", FY_END)
    k.setdefault("risk", "높음")
    k.setdefault("seed", 11)
    return sample_wp.make(data_path, k.pop("tm", TM), out, **k)


def test_scan_reads_before_asking(data):
    """뽑기 전 읽기(sample scan): AI 가 물을 것을 정하는 사실만 내고 조서는 만들지 않는다."""
    import math

    p, info = data
    before = set(p.parent.iterdir())
    s = sample_wp.scan(p, TM)
    assert set(p.parent.iterdir()) == before
    assert s["cols"]["amount"] == "공급가액" and {"세액", "합계금액"} <= set(s["other_numeric"])
    assert s["nonpositive"]["count"] == info["neg"] and s["positive"]["count"] == ROWS + 1 - info["neg"]
    assert s["fy_end_guess"] == date(2025, 12, 31) and s["outside_guess"] == 1        # 결산일 뒤 1건
    # 시산표와 견줄 사업연도 순합계: 반품(음수)은 넣고 결산일 뒤 5,000,000 은 뺀다
    assert s["net_fy_guess"] == pytest.approx(s["positive"]["total"] + s["nonpositive"]["total"] - 5_000_000)
    cand = {c["col"]: c for c in s["strata_candidates"]}
    assert set(cand) == {"구분"} and {v["value"] for v in cand["구분"]["values"]} == {"제품", "상품", "수출"}   # 품목 30 개는 후보 아님
    assert sum(v["total"] for v in cand["구분"]["values"]) == pytest.approx(s["positive"]["total"])
    assert s["party"]["distinct"] == 40
    assert [z["risk"] for z in s["sizes"]][0] == "높음"
    hi = s["sizes"][0]
    assert hi["interval"] == pytest.approx(TM / 3.0) and hi["points"] == math.ceil(s["positive"]["total"] / (TM / 3.0))
    assert hi["key_items"] == info["big"]
    assert sample_wp.scan(p)["sizes"] == []
    with pytest.raises(sample_wp.SampleError):
        sample_wp.scan(p, amount="없는 열")


def test_dataset_finds_columns_and_skips_total(data):
    p, _ = data
    ds = dataset.read(p)
    assert ds["header_row"] == 3 and ds["sheet"] == "매출장"
    assert ds["cols"]["amount"] == "공급가액" and ds["cols"]["date"] == "전표일자" and ds["cols"]["party"] == "거래처명"
    assert ds["skipped"]["합계 행"] == 1 and len(ds["rows"]) == ROWS + 1
    assert len(ds["sha"]) == 12
    with pytest.raises(dataset.DataError):
        dataset.read(p, cols={"amount": "없는 열"})


def test_mus_with_strata_and_periods(data, tmp_path):
    p, info = data
    r = _make(p, tmp_path / "표본.xlsx", strata="구분", tail_months=3)
    assert r["excluded"] == info["neg"] + 1                      # 반품 13 · 결산일 뒤 1
    assert r["pop_count"] == ROWS - info["neg"]
    assert r["interval"] == pytest.approx(TM / 3.0)
    assert r["key_items"] == info["big"] and r["key_threshold"] == pytest.approx(TM / 3.0)
    labels = {s["label"] for s in r["strata"]}
    assert len(labels) == 6 and "제품 · 2025-10 ~ 2025-12" in labels and "수출 · 2025-01 ~ 2025-09" in labels
    wb = load_workbook(r["path"])
    assert wb.sheetnames[:3] == ["설계", "표본", "모집단에서 뺀 항목"]
    assert wb[sample_wp.META].sheet_state == "hidden"
    # 같은 시드면 같은 표본
    r2 = _make(p, tmp_path / "표본2.xlsx", strata="구분", tail_months=3)
    keys = lambda path: sorted(x["label"] for x in wp.readback(path) if x["label"].startswith("검사 결과: "))
    assert keys(r["path"]) == keys(r2["path"])
    r3 = _make(p, tmp_path / "표본3.xlsx", strata="구분", tail_months=3, seed=12)
    assert keys(r3["path"]) != keys(r["path"])


def test_population_reconciles_to_control(data, tmp_path):
    """모집단 대사(530 문단 A5 · 500 문단 9): 사업연도 순합계 − 시산표 · 원장 금액. 표본 크기에는 쓰지 않는다."""
    import excel_recalc

    p, info = data
    s = sample_wp.scan(p)
    r = _make(p, tmp_path / "대사없음.xlsx")
    assert r["net_fy"] == pytest.approx(s["net_fy_guess"])          # 모집단 + 반품, 결산일 뒤 제외
    assert r["excluded_by"][sample_wp.FY_OUT]["count"] == 1 and r["control"] is None and r["control_diff"] is None
    r2 = _make(p, tmp_path / "대사.xlsx", control=r["net_fy"] - 1000)
    assert r2["control_diff"] == pytest.approx(1000)
    assert (r2["interval"], r2["points"], r2["selected"]) == (r["interval"], r["points"], r["selected"])   # 크기는 그대로
    if not excel_recalc.recalc(r2["path"]):
        pytest.skip("엑셀이 없어 수식을 계산하지 못함")
    assert _value(r2["path"], "설계", "대사 차이") == pytest.approx(1000)


def test_group_by_party_keeps_party_with_late_row(data, tmp_path):
    p, _ = data
    r = _make(p, tmp_path / "거래처.xlsx", group="거래처명")
    assert r["pop_count"] == 40 and r["excluded"] == 1             # 결산일 뒤 한 행만 빠지고 거래처01 은 남는다
    inp = {x["label"] for x in wp.readback(r["path"])}
    assert "검사 결과: 거래처01" in inp or any(k.startswith("검사 결과: 거래처") for k in inp)


def test_rerun_uses_sheet_inputs_and_carries(data, tmp_path):
    from audit.workpapers.common import Kept

    p, _ = data
    out = tmp_path / "표본.xlsx"
    r = _make(p, out, risk=None)
    assert r["risk"] == "기본" and r["risk_source"].startswith("초기값")
    results = lambda path: {i["label"]: i for i in wp.readback(path) if i["label"].startswith("검사 결과: ")}
    later = set(results(_make(p, tmp_path / "높음.xlsx", risk="높음")["path"]))
    x = {i["label"]: i for i in wp.readback(out)}
    gone = next(k for k in results(out) if k not in later)       # 위험 수준을 높이면 빠지는 항목
    wb = load_workbook(out)
    wb[x["위험 수준 확인: 모집단"]["sheet"]][x["위험 수준 확인: 모집단"]["ref"]] = "높음"
    wb[x[gone]["sheet"]][x[gone]["ref"]] = "세금계산서 대사 일치"
    wb.save(out)
    with pytest.raises(Kept):               # 검사 결과를 적은 항목이 새 표본에 없으면 멈춘다
        _make(p, out, risk=None)
    r = _make(p, out, risk=None, force=True)
    assert r["risk"] == "높음" and r["risk_source"] == "조서 「위험 수준 확인」" and r["lost"] == [f"표본!{gone}"]
    first = next(iter(results(out)))
    x = {i["label"]: i for i in wp.readback(out)}
    wb = load_workbook(out)
    wb[x[first]["sheet"]][x[first]["ref"]] = "세금계산서 대사 일치"
    wb.save(out)
    r = _make(p, out, risk=None)
    assert r["risk"] == "높음" and not r["lost"]
    assert {i["label"]: i["value"] for i in wp.readback(out)}[first] == "세금계산서 대사 일치"


def test_specific_needs_criteria(data, tmp_path):
    p, _ = data
    with pytest.raises(sample_wp.SampleError):
        _make(p, tmp_path / "x.xlsx", method="specific")
    r = _make(p, tmp_path / "특정.xlsx", method="specific", top=20, window=5)
    assert r["selected"] >= 20


def _fill(path: Path, errors: dict) -> None:
    """검사 결과를 모두 「확인」 으로, errors 는 {항목 순번: 왜곡표시 금액}."""
    inp = wp.readback(path)
    wb = load_workbook(path)
    res = [x for x in inp if x["label"].startswith("검사 결과: ")]
    for x in res:
        wb[x["sheet"]][x["ref"]] = "확인"
    errs = {x["label"]: x for x in inp if x["label"].startswith("왜곡표시 금액: ")}
    for n, v in errors.items():
        key = res[n]["label"].split(": ", 1)[1]
        e = errs[f"왜곡표시 금액: {key}"]
        wb[e["sheet"]][e["ref"]] = v
    wb.save(path)


def _value(path: Path, sheet: str, label: str):
    ws = load_workbook(path, data_only=True)[sheet]
    return next(ws.cell(r, 2).value for r in range(1, ws.max_row + 1) if str(ws.cell(r, 1).value or "").startswith(label))


def _amounts(path: Path) -> list[float]:
    ws = load_workbook(path)["표본"]
    inp = [x for x in wp.readback(path) if x["label"].startswith("검사 결과: ")]
    return [ws.cell(ws[x["ref"]].row, 3).value for x in inp]


@pytest.mark.parametrize("method,extra", [("mus", {"strata": "구분", "expected": 20_000_000}), ("mus", {}),
                                          ("random", {"strata": "구분"}), ("systematic", {}), ("specific", {"top": 20})])
def test_excel_formula_matches_engine(data, tmp_path, method, extra):
    import excel_recalc

    p, _ = data
    r = _make(p, tmp_path / f"표본_{method}.xlsx", method=method, **extra)
    path = r["path"]
    amts = _amounts(path)
    small = [i for i, a in enumerate(amts) if a < r["interval"]]
    big = [i for i, a in enumerate(amts) if a >= r["interval"]]
    errors = {small[0]: round(amts[small[0]] * 0.01), small[1]: -round(amts[small[1]] * 0.02)}
    if big:
        errors[big[0]] = 1_000_000
    _fill(path, errors)
    ev = sample_wp.evaluate(path)
    assert ev["pending"] == 0 and ev["with_error"] == len(errors)
    if not excel_recalc.recalc(path):
        pytest.skip("엑셀이 없어 수식을 계산하지 못함")
    assert _value(path, "표본", "허용왜곡표시와 견줌") == ev["verdict"]
    if method == "mus":
        assert _value(path, "표본", "상한 왜곡표시: 과대계상") == pytest.approx(ev["upper_over"], rel=1e-9)
        assert _value(path, "표본", "상한 왜곡표시: 과소계상") == pytest.approx(ev["upper_under"], rel=1e-9)
        assert ev["verdict"] == (se.V_WITHIN if extra.get("expected") else se.V_UPPER_OVER)
    elif method in ("random", "systematic"):
        assert _value(path, "표본", "투영한 왜곡표시: 과대계상 합") == pytest.approx(ev["projected_over"], rel=1e-9)
        assert _value(path, "표본", "투영한 왜곡표시: 과소계상 합") == pytest.approx(ev["projected_under"], rel=1e-9)
    assert _value(path, "설계", "대사 차이") == "금액을 적으면 계산"


def test_cli_make_and_eval(data, tmp_path, capsys):
    from run import main

    p, _ = data
    out = tmp_path / "cli.xlsx"
    assert main(["sample", "scan", str(p), "--tm", str(TM)]) == 0
    text = capsys.readouterr().out
    assert "금액=공급가액" in text and "결산일 어림 2025-12-31" in text and "계층 후보 「구분」" in text and "위험 높음" in text
    assert "사업연도 순합계" in text
    assert main(["sample", "scan", str(p), "--amount", "없는 열"]) == 1
    capsys.readouterr()
    net = sample_wp.scan(p)["net_fy_guess"]
    assert main(["sample", "make", str(p), "--tm", str(TM), "--fy-end", FY_END, "--risk", "높음", "--strata", "구분",
                 "--control", str(net), "--out", str(out)]) == 0
    text = capsys.readouterr().out
    assert "표본 간격 100,000,000원" in text and "계층 제품" in text
    assert "모집단 대사: 사업연도 순합계" in text and "(일치)" in text
    assert main(["sample", "make", str(p), "--tm", str(TM), "--fy-end", FY_END, "--out", str(tmp_path / "cli2.xlsx")]) == 0
    assert "시산표 · 원장 금액을 받지 않음" in capsys.readouterr().out
    assert main(["sample", "eval", str(out)]) == 0
    assert se.V_PENDING in capsys.readouterr().out
    assert main(["sample", "make", str(p), "--tm", "0"]) == 1
