# -*- coding: utf-8 -*-
import pytest

from yangdo import calc as engine_calc
from yangdo import workbook as W

TABLE = [[0, 0, "0.06"], [14000000, 840000, "0.15"], [50000000, 6240000, "0.24"], [88000000, 15360000, "0.35"],
         [150000000, 37060000, "0.38"], [300000000, 94060000, "0.40"], [500000000, 174060000, "0.42"],
         [1000000000, 384060000, "0.45"]]
LOCAL = [[0, 0, "0.006"], [14000000, 84000, "0.015"], [50000000, 624000, "0.024"], [88000000, 1536000, "0.035"],
         [150000000, 3706000, "0.038"], [300000000, 9406000, "0.040"], [500000000, 17406000, "0.042"],
         [1000000000, 38406000, "0.045"]]


def row(id, 종류, v, c):
    base_v = {"id": id, "종류": 종류, "양도일": "2026-10-01", "고가주택": False, "전액비과세": False, "미등기": False,
              "중과": None, "단기": None}
    base_v.update(v)
    return {"id": id, "판정": base_v, "계산": c}


def calc(양도, 취득, 차익, 과세, 율, 장특공, 소득, 공제, 과표, 세액, 지방, 단일, 가산, 지방단일, 지방가산,
         전체=None, 그룹="주택", 종류="기본", 묶음=None):
    return {"양도가액": 양도, "전체양도가액": 전체 or 양도, "취득가액": 취득, "필요경비": 0, "양도차익": 차익,
            "과세양도차익": 과세, "장특공률": 율, "장특공": 장특공, "양도소득금액": 소득, "기본공제": 공제,
            "과세표준": 과표, "산출세액": 세액, "지방소득세": 지방, "고가주택기준": 1200000000,
            "적용세율": {"단일": 단일, "가산": 가산, "지방단일": 지방단일, "지방가산": 지방가산},
            "세율그룹": 그룹, "세율종류": 종류, "합산묶음": 묶음}


RESULT = {
    "자산": [
        row("A", "주택", {"고가주택": True},
            calc(1500000000, 800000000, 700000000, 140000000, "0.80", 112000000, 28000000, 2500000, 25500000,
                 2565000, 256500, None, "0", None, "0", 묶음="기본")),
        row("J", "주택", {"중과": "중과2", "단기": "2년미만"},
            calc(900000000, 800000000, 100000000, 100000000, "0", 0, 100000000, 0, 100000000,
                 60000000, 6000000, "0.60", "0.20", "0.060", "0.020", 그룹="중과2", 종류="2년미만",
                 묶음="중과2·주택·2년미만")),
        row("E", "토지", {"미등기": True},
            calc(300000000, 100000000, 200000000, 200000000, "0", 0, 200000000, 0, 200000000,
                 140000000, 14000000, "0.70", None, "0.070", None, 그룹="미등기", 종류=None, 묶음="미등기")),
        row("G", "주택", {"전액비과세": True},
            calc(1000000000, None, None, 0, "0", 0, 0, 0, 0, 0, 0, None, "0", None, "0")),
    ],
    "합계": {"과세표준": 325500000, "자산별세액": 202565000, "호별합산세액": 202565000, "합산비교세액": 104260000,
             "산출세액": 202565000, "지방_자산별": 20256500, "지방_호별합산": 20256500, "지방_합산비교": 10426000,
             "지방소득세": 20256500},
    "세율표": {"국세": TABLE, "지방": LOCAL},
}


def test_recalc_matches_rows_and_totals(tmp_path):
    p = W.write(RESULT, str(tmp_path / "양도소득세_계산근거.xlsx"))
    assert W.compare(p, RESULT) == []


def test_compare_detects_difference(tmp_path):
    p = W.write(RESULT, str(tmp_path / "w.xlsx"))
    import copy
    bad = copy.deepcopy(RESULT)
    bad["자산"][0]["계산"]["산출세액"] += 1
    bad["합계"]["산출세액"] += 1
    msgs = W.compare(p, bad)
    assert any(m.startswith("W A 산출세액") for m in msgs) and any("합계" in m for m in msgs)


def test_summary_cells():
    s = W.summary_cells(4, 3)
    assert s["산출세액"] == "R9" and s["지방소득세"] == "S9"
    assert s["호별합산세액"] == "R14" and s["지방_호별합산"] == "S14"  # 묶음 행 3개는 11~13행, 그 아래가 호별 합산


def test_same_rate_rows_are_summed_by_formula(tmp_path):
    """기본세율 자산 둘은 SUMIF 로 과세표준을 합친 뒤 한 번에 세율표를 적용한다(제104조⑤2호)."""
    result = {
        "자산": [
            row("B", "주택", {}, calc(700000000, 510000000, 190000000, 190000000, "0.14", 26600000, 163400000, 0,
                                      163400000, 42152000, 4215200, None, "0", None, "0", 묶음="기본")),
            row("F", "토지", {}, calc(1000000000, 406000000, 594000000, 594000000, "0.30", 178200000, 415800000, 0,
                                      415800000, 140380000, 14038000, None, "0", None, "0", 그룹="일반", 묶음="기본")),
        ],
        "합계": {"과세표준": 579200000, "자산별세액": 182532000, "호별합산세액": 207324000, "합산비교세액": 207324000,
                 "산출세액": 207324000, "지방_자산별": 18253200, "지방_호별합산": 20732400, "지방_합산비교": 20732400,
                 "지방소득세": 20732400},
        "세율표": {"국세": TABLE, "지방": LOCAL},
    }
    p = W.write(result, str(tmp_path / "합산.xlsx"))
    assert W.compare(p, result) == []
    import copy
    bad = copy.deepcopy(result)
    bad["합계"]["호별합산세액"] = 182532000  # 자산별로만 세액을 낸 값이면 대조에서 걸려야 한다
    assert any("호별합산세액" in m for m in W.compare(p, bad))


# ---- 최종 검토 반영 ---------------------------------------------------------------------------
def _sheet(path, **kw):
    import openpyxl
    return openpyxl.load_workbook(path, **kw)["계산"]


def test_unregistered_rate_label_has_no_none(tmp_path):
    """미등기 행의 세율 칸은 「미등기·None」 이 아니라 「미등기」 로 적는다."""
    p = W.write(RESULT, str(tmp_path / "w.xlsx"))
    ws = _sheet(p)
    labels = {ws["A%d" % r].value: ws["C%d" % r].value for r in range(2, 6)}
    assert labels == {"A": "주택·기본", "J": "중과2·2년미만", "E": "미등기", "G": "주택·기본"}
    assert not any("None" in str(ws["C%d" % r].value) for r in range(2, 6))


@pytest.mark.parametrize("bad_id", ["=1+1", "+1", "-1+1", "@SUM(A1)", '=HYPERLINK("http://x","a")', "\t=1", "\r=1"])
def test_user_text_never_becomes_a_formula(tmp_path, bad_id):
    import copy
    result = copy.deepcopy(RESULT)
    result["자산"][0]["id"] = bad_id
    p = W.write(result, str(tmp_path / "w.xlsx"))
    cell = _sheet(p)["A2"]
    # lxml 이 없으면 openpyxl 은 \r 을 이스케이프하지 않고 쓰고, XML 파서는 읽을 때 날것의 \r 을 \n 으로 바꾼다(XML 1.0 줄끝 처리).
    # 이 시험이 지키는 것은 글자로 남는다는 점이라 그 경우의 \n 도 받는다
    assert cell.value in (bad_id, bad_id.replace("\r", "\n")) and cell.data_type == "s"
    assert W.compare(p, result) == []   # 수식으로 쓴 칸과 대조는 그대로 맞는다


def test_formula_cells_stay_formulas(tmp_path):
    ws = _sheet(W.write(RESULT, str(tmp_path / "w.xlsx")))
    assert ws["I2"].data_type == "f" and ws["R2"].data_type == "f" and ws["Q2"].data_type == "f"


def _group_result(order):
    """같은 묶음에 가산세율이 다른 두 자산. X 는 10-15 양도(가산 0.25), Y 는 07-01 양도(가산 0.20)."""
    x = row("X", "주택", {"중과": "중과2", "양도일": "2026-10-15"},
            calc(900000000, 800000000, 100000000, 100000000, "0", 0, 100000000, 0, 100000000,
                 45000000, 4500000, None, "0.25", None, "0.025", 그룹="중과2", 종류="기본", 묶음="중과2"))
    y = row("Y", "주택", {"중과": "중과2", "양도일": "2026-07-01"},
            calc(900000000, 800000000, 100000000, 100000000, "0", 0, 100000000, 0, 100000000,
                 44000000, 4400000, None, "0.20", None, "0.020", 그룹="중과2", 종류="기본", 묶음="중과2"))
    rows = {"XY": [x, y], "YX": [y, x]}[order]
    return {"자산": rows, "합계": {"과세표준": 200000000, "자산별세액": 89000000, "호별합산세액": 0, "합산비교세액": 0,
                               "산출세액": 0, "지방_자산별": 8900000, "지방_호별합산": 0, "지방_합산비교": 0, "지방소득세": 0},
            "세율표": {"국세": TABLE, "지방": LOCAL}}


@pytest.mark.parametrize("order", ["XY", "YX"])
def test_group_row_takes_rates_from_earliest_transfer(tmp_path, order):
    """묶음 행의 세율은 입력 순서가 아니라 양도일이 가장 이른 구성원(Y)의 행에서 가져온다."""
    result = _group_result(order)
    ws = _sheet(W.write(result, str(tmp_path / "w.xlsx")))
    group_row = 2 + len(result["자산"]) + 5   # n + 7
    assert ws["A%d" % group_row].value == "묶음 중과2"
    src = int(ws["E%d" % group_row].value.lstrip("=E"))
    assert ws["A%d" % src].value == "Y"
    assert ws["V%d" % group_row].value == "=V%d" % src


def test_workbook_picks_group_anchor_with_the_engine_rule(monkeypatch):
    """묶음 대표의 정의는 calc.group_anchor 하나다. 워크북이 따로 구현하면 두 정의가 갈라질 수 있다(m-6)."""
    asked = []
    real = engine_calc.group_anchor

    def spy(members):
        asked.append(sorted(m["id"] for m in members))
        return real(members)

    monkeypatch.setattr(engine_calc, "group_anchor", spy)
    for order in ("XY", "YX"):
        asked.clear()
        rows = _group_result(order)["자산"]
        groups = W._groups(rows)
        assert asked == [["X", "Y"]]
        assert {k: rows[i]["id"] for k, i in groups.items()} == {"중과2": "Y"}   # 양도일이 이른 Y
    assert not hasattr(W, "_earliest")


def test_workbook_group_anchor_breaks_a_tie_by_id_like_the_engine():
    x = _group_result("XY")["자산"][0]
    y = _group_result("XY")["자산"][1]
    x["판정"]["양도일"] = y["판정"]["양도일"] = "2026-10-15"   # 양도일이 같으면 id 가 앞선 자산이 대표다
    for rows in ([x, y], [y, x]):
        groups = W._groups(rows)
        assert rows[groups["중과2"]]["id"] == "X"
        assert rows[groups["중과2"]] is engine_calc.group_anchor(rows)


def test_recalc_does_not_print_progress_bar(tmp_path, capsys):
    p = W.write(RESULT, str(tmp_path / "w.xlsx"))
    capsys.readouterr()
    cells = W.recalc(p)
    err = capsys.readouterr().err
    assert "it/s" not in err and "%|" not in err and "\r" not in err
    assert cells[("계산", "R2")] is not None
