# -*- coding: utf-8 -*-
import copy
import json
import os
import re

import pymupdf
import pytest

from yangdo import engine, filing, forms, return_values
from cases import CASES
import filers

SKILL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CASE_NAMES = ("A", "S1", "BF", "K")


def _rv(name):
    r = engine.calculate(CASES[name], today="2026-10-11")
    f = filers.get(name)
    for aid in f["자산"]:
        f["자산"][aid]["법정동코드"] = "1120011400"
    f["신고인"]["주소"]["법정동코드"] = "1144010200"
    return return_values.build(r, CASES[name], filing.load(f))


_CACHE = {}


def _rv_cached(name):
    if name not in _CACHE:
        _CACHE[name] = _rv(name)
    return copy.deepcopy(_CACHE[name])


def _squash(s):
    return re.sub(r"\s+", "", s or "")


def _parts(value):
    """placement 값에서 PDF 에 나와야 할 글자 목록. 후보 목록이면 그중 하나가 나오면 된다(호출하는 쪽에서 본다)."""
    if isinstance(value, dict):
        return [v for v in value.values() if v not in (None, "")]
    return [value]


# ------------------------------------------------------------ 브리프 시험

def test_render_writes_two_pdfs_with_values(tmp_path):
    paths = forms.render(_rv("S1"), str(tmp_path))
    assert [os.path.basename(p) for p in paths] == ["양도소득세_신고서.pdf", "지방소득세_신고서.pdf"]
    doc = pymupdf.open(paths[0])
    text = "".join(p.get_text() for p in doc)
    for s in ("1,800,000,000", "609,800,000", "21,000,000", "153,393,334", "38,349,466", "김합성"):
        assert s in text, s
    assert os.path.getsize(paths[0]) < 1_500_000


def test_pages_are_main_schedule1_schedule3():
    doc = pymupdf.open(forms.render(_rv("S1"), os.path.join(os.environ.get("TMP", "."), "_t12"))[0])
    assert doc.page_count == 2 + 1 + 1          # 본지 2쪽, 부표1 1쪽, 부표3 1쪽(행이 30 이하)


def test_every_mapping_target_exists():
    for name in os.listdir(os.path.join(SKILL, "forms", "매핑")):
        m = json.load(open(os.path.join(SKILL, "forms", "매핑", name), encoding="utf-8"))
        fl = {"별지84": ["필드목록_별지84_신고및납부계산서.json", "필드목록_별지84부표1_양도소득금액계산명세서.json",
                         "필드목록_별지84부표3_취득가액및필요경비계산상세명세서.json",
                         "필드목록_별지84부표3_2_취득가액및필요경비계산상세명세서.json"],
              "별지40의11": ["필드목록_지방세_별지40의11_신고및납부계산서.json"]}[m["서식"]]
        ids = set()
        for x in fl:
            ids |= {f["id"] for f in json.load(open(os.path.join(SKILL, "forms", "필드목록", x), encoding="utf-8"))["fields"]}
        for c in m["칸"]:
            assert c["필드"] in ids, (name, c["필드"])


def test_four_assets_split_schedule1(tmp_path):
    rv = _rv("S1")
    rv["부표1"] = rv["부표1"] * 4
    doc = pymupdf.open(forms.render(rv, str(tmp_path))[0])
    assert doc.page_count == 2 + 2 + 1


# ------------------------------------------------------------ 매핑 표

def _mappings():
    d = os.path.join(SKILL, "forms", "매핑")
    return {n: json.load(open(os.path.join(d, n), encoding="utf-8")) for n in sorted(os.listdir(d))}


def _fields(names):
    out = {}
    for x in names:
        for f in json.load(open(os.path.join(SKILL, "forms", "필드목록", x), encoding="utf-8"))["fields"]:
            out[f["id"]] = f
    return out


def test_mapping_columns_exist_and_are_not_shaded():
    """매핑의 열이 필드목록 칸에 있고, 음영·쓰지않음 칸을 가리키지 않는다."""
    for name, m in _mappings().items():
        fields = _fields(m["필드목록"])
        alias = m.get("열") or {}
        for c in m["칸"]:
            f = fields[c["필드"]]
            assert not f.get("쓰지않음"), (name, c["필드"])
            cols = list((f.get("좌표") or {}).get("값_칸_해석") or {})
            if c.get("형식") == "체크":
                want = list(c["선택"].values())
            elif c.get("열") is None:
                want = [cols[0]] if len(cols) == 1 else []
                assert want, (name, c["필드"], "열을 골라야 한다")
            else:
                a = alias.get(c["열"], c["열"])
                want = a["칸"] if isinstance(a, dict) else [a]
            for col in want:
                assert col in cols, (name, c["필드"], col)
                assert col not in f.get("음영_열", []), (name, c["필드"], col)


def test_schedule3_rows_cover_every_expense_code():
    """부표3 매핑의 행 표가 codes 의 필요경비구분 전자코드를 모두 받고, 행·소계·계·명세 행이 필드목록에 있다."""
    m = _mappings()["부표3.json"]
    fields = _fields(m["필드목록"])
    codes = json.load(open(os.path.join(SKILL, "efile", "codes_c116300.json"), encoding="utf-8"))["필요경비구분"]
    assert {v["전자코드"] for v in codes.values()} == set(m["행"])
    named = list(m["행"].values()) + list(m["소계"]) + list(m["계"]) + m["명세행"]
    named += [x for v in m["소계"].values() for x in v] + [x for r in m["계"].values() for x in r["더함"] + r.get("뺌", [])]
    assert [x for x in named if x not in fields] == []
    assert len(set(m["행"].values())) == len(m["행"])                # 한 행에 전자코드 하나


def test_mapping_pages_are_registered():
    reg = json.load(open(os.path.join(SKILL, "forms", "서식판.json"), encoding="utf-8"))["서식"]
    for name, m in _mappings().items():
        pages = reg[m["서식"]]["쪽"][m["쪽"]]
        used = [m["채움쪽"]] + m.get("덧붙임쪽", []) + ([m["명세쪽"]] if m.get("명세쪽") else [])
        assert set(used) <= set(pages), name


def test_mapping_files_hold_no_filer_values():
    """매핑 파일에는 신고값 경로만 있다. 합성 신고인의 이름·번호·주소가 들어 있지 않다."""
    rv = _rv_cached("S1")
    secrets = [rv["신고인"]["성명"], rv["신고인"]["주민등록번호"], rv["신고인"]["전화"], rv["양수인"][0]["성명"],
               rv["양수인"][0]["번호"], rv["부표1"][0]["소재지"]]
    for name in os.listdir(os.path.join(SKILL, "forms", "매핑")):
        text = open(os.path.join(SKILL, "forms", "매핑", name), encoding="utf-8").read()
        for s in secrets:
            assert s not in text, name


# ------------------------------------------------------------ 빠진 값·칸 위치

@pytest.mark.parametrize("name", CASE_NAMES)
def test_every_form_value_is_placed_or_excused(name):
    """신고값에서 서식에 들어갈 값(0·빈칸 아닌 것)이 모두 매핑으로 놓이거나, 매핑 「안씀」 에 이유가 있다."""
    assert forms.unplaced(_rv_cached(name)) == []


@pytest.mark.parametrize("name", CASE_NAMES)
def test_every_placed_value_shows_inside_its_cell(name, tmp_path):
    """계획한 값이 저장한 PDF 의 그 칸 안에서 글자로 나온다(칸 밀림·잘림·빠짐)."""
    rv = _rv_cached(name)
    plan = forms.plan(rv)
    paths = forms.render(rv, str(tmp_path))
    docs = {"국세": pymupdf.open(paths[0]), "지방": pymupdf.open(paths[1])}
    missing = []
    for which in ("국세", "지방"):
        for p in plan[which]["칸"]:
            page = docs[which][p["쪽"]]
            got = _squash(page.get_text(clip=pymupdf.Rect(p["칸"])))
            value = p["값"]
            if isinstance(value, list):
                ok = any(all(_squash(x) in got for x in _parts(v)) for v in value)
            else:
                ok = all(_squash(x) in got for x in _parts(value))
            if not ok:
                missing.append((which, p["쪽"], p["필드"], p["열"]))
    assert not missing, missing


def test_s1_shows_core_cells():
    plan = forms.plan(_rv_cached("S1"))
    by = {(p["필드"], p["열"]): p["값"] for p in plan["국세"]["칸"] if p["쪽"] == 0}
    assert by[("과세표준", "양도소득세 합계")] == "153,393,334"
    assert by[("세율구분코드", "세율구분별 열1")] == {"국내외분": "1", "세율구분": "10"}
    assert by[("신고구분", "예정신고")] == "V"
    assert by[("신고인.주민등록번호", "첫_칸")] == "000101-1234564"
    assert ("감면세액", "양도소득세 합계") not in by                # 0 금액은 비운다
    assert ("분납할세액", "국내분 소계") not in by                  # 세율구분 열이 하나면 분납은 합계 열에만
    s1 = {(p["필드"], p["열"]): p["값"] for p in plan["국세"]["칸"] if p["쪽"] == 2}
    assert s1[("장기보유특별공제", "자산1")] == {"금액": "233,839,999", "코드": "01"}
    assert s1[("자산종류코드", "자산1")] == {"자산종류": "고가주택", "코드": "2"}
    assert ("양도면적.토지", "합계") not in s1                      # 부표1 면적 합계 칸은 인쇄된 칸이 없다
    s3 = {(p["필드"], p["열"]): p["값"] for p in plan["국세"]["칸"] if p["쪽"] == 3}
    assert s3[("부표3.⑤계", "지급금액")] == "609,800,000"
    assert s3[("부표3.법무사비용", "거래상대방 사업자등록번호")] == "211-81-04565"
    assert ("부표3.매입가액", "지급일") not in s3                   # 음영 칸


def test_zero_totals_are_written():
    """0 금액은 비우지만 합계 성격 칸(부표3 ⑬)은 0 도 적는다."""
    plan = forms.plan(_rv_cached("A"))
    s3 = {(p["필드"], p["열"]): p["값"] for p in plan["국세"]["칸"] if p["쪽"] == 3}
    assert s3[("부표3.⑬기타필요경비계", "지급금액")] == "0"
    assert ("부표3.⑨계", "지급금액") not in s3


# ------------------------------------------------------------ 장 나눔

def test_schedule1_continuation_sheet_leaves_total_column_blank():
    rv = _rv_cached("S1")
    rv["부표1"] = rv["부표1"] * 4
    plan = forms.plan(rv)
    pages = plan["국세"]["쪽"]
    assert pages == [1, 2, 5, 5, 14]
    second = [p for p in plan["국세"]["칸"] if p["쪽"] == 3]
    assert [p["열"] for p in second if p["필드"] == "양도가액"] == ["자산1"]
    assert not [p for p in second if p["열"] == "합계"]
    assert any("부표1" in s and "2장" in s for s in plan["확인사항"])


def _many_rate_columns(n):
    rv = _rv_cached("S1")
    labels = []
    for k in range(n):
        lab = "1-%d" % (10 + k)
        labels.append({"국내외분": "1", "세율구분": str(10 + k), "표기": lab})
        rv["본지"]["열"][lab] = copy.deepcopy(rv["본지"]["열"]["1-10"])
        rv["지방"]["열"][lab] = copy.deepcopy(rv["지방"]["열"]["1-10"])
    rv["본지"]["세율구분"] = labels
    rv["지방"]["세율구분"] = copy.deepcopy(labels)
    return rv


def test_rate_columns_beyond_the_form_split_main_and_local(tmp_path):
    rv = _many_rate_columns(4)
    plan = forms.plan(rv)
    assert plan["국세"]["쪽"][:3] == [1, 1, 2]                      # 본지 세율구분 3열, 4번째 열은 이어지는 장
    assert plan["지방"]["쪽"] == [1, 1, 2]                          # 40의11 은 2열
    cont = [p for p in plan["국세"]["칸"] if p["쪽"] == 1]
    assert {p["열"] for p in cont if p["필드"] == "과세표준"} == {"세율구분별 열1"}
    assert {p["필드"] for p in cont} >= {"신고인.성명", "신고인.주민등록번호", "귀속연도"}
    assert not [p for p in cont if p["필드"] in ("양수인", "신고일자", "신고인서명")]
    paths = forms.render(rv, str(tmp_path))
    assert pymupdf.open(paths[0]).page_count == 3 + 1 + 1
    assert pymupdf.open(paths[1]).page_count == 3


def test_three_rate_columns_fit_one_main_sheet_but_two_local_sheets():
    plan = forms.plan(_many_rate_columns(3))
    assert plan["국세"]["쪽"][:2] == [1, 2]
    assert plan["지방"]["쪽"] == [1, 1, 2]


# ------------------------------------------------------------ 부표3 (2)

def test_several_items_of_one_kind_go_to_detail_sheet():
    rv = _rv_cached("S1")
    rows = rv["부표3"][0]["행"]
    law = next(x for x in rows if x["전자코드"] == "11401")
    second = dict(law, 상호="합성등기사무소", 사업자번호="1018101238", 금액=300000)
    law["금액"] -= 300000
    rows.insert(rows.index(law) + 1, second)
    plan = forms.plan(rv)
    assert plan["국세"]["쪽"] == [1, 2, 5, 14, 16]
    s3 = {(p["필드"], p["열"]): p["값"] for p in plan["국세"]["칸"] if p["쪽"] == 3}
    assert s3[("부표3.법무사비용", "거래상대방 사업자등록번호")] == "별지 작성"
    assert s3[("부표3.법무사비용", "지급금액")] == "800,000"
    assert ("부표3.법무사비용", "거래상대방 상호") not in s3
    d = {(p["필드"], p["열"]): p["값"] for p in plan["국세"]["칸"] if p["쪽"] == 4}
    assert d[("부표3(2).01", "구분코드")] == "114" and d[("부표3(2).01", "지급금액")] == "500,000"
    assert d[("부표3(2).02", "거래상대방 상호")] == "합성등기사무소" and d[("부표3(2).02", "지급금액")] == "300,000"
    assert ("부표3(2).03", "구분코드") not in d


def test_more_than_thirty_detail_rows_add_another_detail_sheet():
    rv = _rv_cached("S1")
    rows = rv["부표3"][0]["행"]
    cap = next(x for x in rows if x["전자코드"] == "26001")
    extra = [dict(cap, 금액=1000) for _ in range(31)]
    cap["금액"] -= 31000
    rows[rows.index(cap) + 1:rows.index(cap) + 1] = extra
    plan = forms.plan(rv)
    assert plan["국세"]["쪽"] == [1, 2, 5, 14, 16, 16]


def test_schedule3_rows_must_add_up():
    rv = _rv_cached("S1")
    rv["부표3"][0]["행"][0]["금액"] += 1
    with pytest.raises(ValueError):
        forms.plan(rv)


# ------------------------------------------------------------ 양수인·인적사항

def test_second_buyer_is_noted_not_dropped_silently():
    plan = forms.plan(_rv_cached("BF"))
    by = {(p["필드"], p["열"]): p["값"] for p in plan["국세"]["칸"] if p["쪽"] == 0}
    assert by[("양수인", "성명")] == "이합성 외 1명"
    assert any("양수인이 2명" in s for s in plan["확인사항"])
    loc = {(p["필드"], p["열"]): p["값"] for p in plan["지방"]["칸"] if p["쪽"] == 0}
    assert loc[("양수인", "성명")] == "이합성 외 1명"


def test_render_adds_notes_without_personal_values(tmp_path):
    rv = _rv_cached("BF")
    forms.render(rv, str(tmp_path))
    notes = "\n".join(rv["확인사항"])
    assert "양수인이 2명" in notes
    for s in (rv["신고인"]["성명"], rv["양수인"][1]["성명"], rv["부표1"][0]["소재지"], rv["양수인"][0]["번호"]):
        assert s not in notes


def test_value_that_cannot_fit_raises_without_echoing_it(tmp_path):
    rv = _rv_cached("S1")
    rv["신고인"]["성명"] = "합성" * 40
    with pytest.raises(ValueError) as e:
        forms.render(rv, str(tmp_path))
    assert "합성합성" not in str(e.value)
    assert "신고인.성명" in str(e.value)


def test_long_address_is_shortened_to_fit_and_noted():
    rv = _rv_cached("S1")
    plan = forms.plan(rv)
    cell = next(p for p in plan["국세"]["칸"] if p["필드"] == "양수인" and p["열"] == "양도자산 소재지")
    assert isinstance(cell["값"], list) and cell["값"][0] == rv["부표1"][0]["소재지"]


def test_local_form_uses_local_values():
    plan = forms.plan(_rv_cached("S1"))
    by = {(p["필드"], p["열"]): p["값"] for p in plan["지방"]["칸"] if p["쪽"] == 0}
    assert by[("산출세액", "지방소득세 합계")] == "3,834,946"
    assert by[("세율", "세율구분별 열1")] == "3.8%"
    assert by[("기본정보.신고유형", "첫_칸")] == "1"
    assert by[("기본정보.양도일자", "첫_칸")] == "2026.11.20"
    assert by[("신고인.납세지", "첫_칸")] == ["서울특별시 마포구", "서울 마포구", "마포구"]   # 시ㆍ군ㆍ구 단위까지(작성방법 2)
    assert by[("신고일자", "첫_칸")] == {"년": "2026", "월": "12", "일": "15"}
