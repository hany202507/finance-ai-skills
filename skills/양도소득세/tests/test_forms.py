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


def test_pages_are_main_schedule1_schedule3(tmp_path):
    doc = pymupdf.open(forms.render(_rv("S1"), str(tmp_path))[0])
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
        for c in m.get("칸", []):                       # 부표3 은 「칸」 없이 행·소계·계 표로 쓴다
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
        for c in m.get("칸", []):
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
    assert s3[("부표3.법무사비용", "거래상대방 사업자등록번호")] == "000-00-00034"
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
    second = dict(law, 상호="합성등기사무소", 사업자번호="0000000015", 금액=300000)
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


def test_narrow_cells_keep_clear_of_the_ruled_lines(tmp_path):
    """부표3 (2) 「구분」과 본지 ② 양수인 성명은 좁은 칸이다. 글자가 칸 선에 붙지 않게 왼쪽에 맞추고 좌우 2pt 를 띄운다."""
    rv = _rv_cached("S1")
    rows = rv["부표3"][0]["행"]
    work = next(x for x in rows if x["전자코드"] == "26001")          # 구분 이름이 두 줄로 나뉘는 「용도변경,개량,이용편의를 위한 지출」
    second = dict(work, 상호="합성창호", 금액=2000000)
    work["금액"] -= 2000000
    rows.insert(rows.index(work) + 1, second)
    rv["양수인"][0]["성명"] = "남궁합성합성"
    rv["양수인"].append(dict(rv["양수인"][0], 일련번호=2, 성명="박합성"))
    plan = forms.plan(rv)
    name = next(p for p in plan["국세"]["칸"] if p["필드"] == "양수인" and p["열"] == "성명")
    kind = next(p for p in plan["국세"]["칸"] if p["필드"] == "부표3(2).01" and p["열"] == "구분")
    assert name["값"] == "남궁합성합성 외 1명" and (name["맞춤"], name["pad"]) == (None, 2)
    assert (kind["맞춤"], kind["pad"], kind["줄"]) == ("left", 2, 2)
    doc = pymupdf.open(forms.render(rv, str(tmp_path))[0])
    for p in (name, kind):
        cell = pymupdf.Rect(p["칸"])
        words = [pymupdf.Rect(w[:4]) for w in doc[p["쪽"]].get_text("words", clip=cell)]
        assert words, p["필드"]
        assert min(w.x0 for w in words) >= cell.x0 + 2 - 0.05, (p["필드"], "왼쪽 선에 붙었다")
        assert max(w.x1 for w in words) <= cell.x1 - 2 + 0.05, (p["필드"], "오른쪽 선에 붙었다")
        assert abs(min(w.x0 for w in words) - (cell.x0 + 2)) < 0.6, (p["필드"], "왼쪽 맞춤이 아니다")


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


def _forms_copy(tmp_path):
    """매핑이나 필드목록을 바꿔 보는 시험용 forms 폴더 사본."""
    import shutil
    d = tmp_path / "forms"
    shutil.copytree(os.path.join(SKILL, "forms"), str(d))
    return d


def _edit_json(path, edit):
    data = json.loads(path.read_text(encoding="utf-8"))
    edit(data)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _narrow(d, list_name, fid, col, width):
    """필드목록 사본에서 칸 하나의 폭을 줄인다(왼쪽 끝은 그대로)."""
    def edit(data):
        f = next(x for x in data["fields"] if x["id"] == fid)
        r = f["좌표"]["값_칸_해석"][col]
        r[2] = r[0] + width
    _edit_json(d / "필드목록" / list_name, edit)


def test_long_address_is_shortened_to_fit_and_noted(tmp_path):
    """칸에 다 들어가지 않는 소재지는 줄인 후보를 쓰고, 줄여 썼다는 확인사항을 붙인다. 폭을 줄인 합성 칸으로 실제로 써 본다."""
    rv = _rv_cached("S1")
    full = rv["부표1"][0]["소재지"]
    cell = next(p for p in forms.plan(rv)["국세"]["칸"] if p["필드"] == "양수인" and p["열"] == "양도자산 소재지")
    assert isinstance(cell["값"], list) and cell["값"][0] == full and len(cell["값"]) > 2

    def written(forms_dir, out):
        """(쓴 후보의 번호, 더해진 확인사항). 후보는 긴 것부터라 쪽 글자에 처음 나오는 후보가 쓴 후보다."""
        rv = _rv_cached("S1")
        before = list(rv["확인사항"])
        paths = forms.render(rv, str(tmp_path / out), forms_dir=forms_dir)
        text = _squash(pymupdf.open(paths[0])[0].get_text())
        return next(i for i, v in enumerate(cell["값"]) if _squash(v) in text), [s for s in rv["확인사항"] if s not in before]

    real, added = written(None, "real")                    # 본지 ② 칸은 한 줄짜리라 원래 서식에서도 전체 글자가 들어가지 않는다
    assert real >= 1
    notes = [s for s in added if "별지84 본지 ② 양도자산 소재지" in s]
    assert len(notes) == 1 and "시도 이름을 줄이거나 아파트 이름 등을 빼고" in notes[0]
    assert full not in "\n".join(added) and "성수동" not in "\n".join(added)   # 값은 싣지 않는다
    d = _forms_copy(tmp_path)                              # 칸을 더 좁히면 더 짧은 후보로 넘어간다
    _narrow(d, "필드목록_별지84_신고및납부계산서.json", "양수인", "양도자산 소재지", 50)
    narrow, added = written(str(d), "narrow")
    assert narrow > real and len([s for s in added if "별지84 본지 ② 양도자산 소재지" in s]) == 1


def test_shortened_note_matches_the_kind_of_cell(tmp_path):
    """줄여 썼다는 문장은 칸의 형식마다 다르다. 납세지와 자산종류 칸에 「아파트 이름」을 뺐다고 적지 않는다."""
    d = _forms_copy(tmp_path)
    _narrow(d, "필드목록_지방세_별지40의11_신고및납부계산서.json", "신고인.납세지", "첫_칸", 20)
    rv = _rv_cached("S1")
    before = list(rv["확인사항"])
    real = _rv_cached("S1")
    forms.render(real, str(tmp_path / "real"))
    assert not any("① 납세지" in s for s in real["확인사항"])                  # 원래 서식의 칸에는 그대로 들어간다
    paths = forms.render(rv, str(tmp_path / "out"), forms_dir=str(d))
    text = _squash(pymupdf.open(paths[1])[0].get_text())
    assert "서울마포구" in text                                               # 후보 「서울 마포구」를 썼다
    added = [s for s in rv["확인사항"] if s not in before]
    notes = [s for s in added if "별지40의11 ① 납세지" in s]
    assert len(notes) == 1 and "시도 이름을 줄이거나 빼고" in notes[0] and "아파트" not in notes[0]
    assert forms.shortened_note({"이름": "별지84 부표1 자산1 자산종류", "형식": "자산종류"}) == (
        "별지84 부표1 자산1 자산종류 칸이 좁아 자산종류 이름을 짧은 이름으로 적었다. 코드는 그대로다")
    assert "줄인 값으로 적었다" in forms.shortened_note({"이름": "X", "형식": "글"})
    for kind in ("주소", "소재지", "자산소재지"):
        assert "아파트 이름 등을 빼고" in forms.shortened_note({"이름": "X", "형식": kind})


def test_blank_note_says_which_forms_left_the_cell_blank():
    a = {"서식": "별지84 본지"}
    b = {"서식": "별지40의11"}
    both = forms.blank_note("신고인.국적", [a, b], 2)
    assert both.count("국적") == 1 and "별지84 본지·별지40의11 칸에 들어가지 않아 비워 두었다" in both and "나머지" not in both
    one = forms.blank_note("신고인.국적", [b], 2)
    assert "별지84" not in one and one.endswith("나머지 서식에는 영문 이름을 적었다")


def test_cell_name_does_not_repeat_a_column_named_like_the_field():
    assert forms._cell_name("별지84 본지", "신고인.국적", "국적") == "별지84 본지 신고인.국적"
    assert forms._cell_name("별지84 부표1", "자산1", "자산종류") == "별지84 부표1 자산1 자산종류"


def test_schedule1_tax_rate_code_has_the_same_size_in_every_asset_column(tmp_path):
    """부표1 ① 세율구분은 자산 열마다 괄호 폭이 달라(둘째 열은 한 칸 좁다) 글자가 5pt 까지 줄던 칸이다. 세 열 모두 7.5pt 로 찍고
    인쇄된 괄호와 겹치지 않는다."""
    rv = _rv_cached("BF")
    assert len(rv["부표1"]) == 2
    paths = forms.render(rv, str(tmp_path / "bf"))
    page = pymupdf.open(paths[0])[2]                 # 새 문서의 3쪽이 부표1 이다
    words = [w for w in page.get_text("words") if 143 < w[1] < 154 and w[0] > 290]
    spans = [(sp["text"].strip(), sp["size"], sp["bbox"]) for b in page.get_text("dict")["blocks"] for ln in b.get("lines", [])
             for sp in ln["spans"] if 138 < sp["bbox"][1] < 156 and sp["bbox"][0] > 290 and re.fullmatch(r"\d+", sp["text"].strip())]
    assert [t for t, _, _ in spans] == ["1", "10", "1", "10"] and {round(sz, 1) for _, sz, _ in spans} == {7.5}
    closers = sorted(w[0] for w in words if w[4] == ")")
    for text, _, box in spans:
        if text == "10":
            assert not any(box[0] < x <= box[2] - 0.2 for x in closers), (box, closers)     # 글자가 닫는 괄호 위로 넘어가지 않는다


def test_anchored_gap_can_be_set_per_side():
    from yangdo import forms_pdf
    assert forms_pdf._gap(None, "뒤") == forms_pdf.GAP and forms_pdf._gap(-0.5, "앞") == -0.5
    assert forms_pdf._gap({"뒤": -0.5}, "뒤") == -0.5 and forms_pdf._gap({"뒤": -0.5}, "앞") == forms_pdf.GAP


def test_schedule3_totals_follow_the_mapping_table(tmp_path):
    """부표3 ⑤·⑬ 계의 0 적음과 소계·합계액을 적는 열은 매핑 표가 정한다. 읽지 않는 「칸」 항목은 두지 않는다."""
    m = _mappings()["부표3.json"]
    assert "칸" not in m and m["금액열"] == "지급금액"
    assert all(r["0적음"] is True and r["열"] == m["금액열"] for r in m["계"].values())

    def s3(forms_dir=None):
        p = forms.plan(_rv_cached("A"), forms_dir=forms_dir)
        return {(c["필드"], c["열"]): c["값"] for c in p["국세"]["칸"] if c["필드"].startswith("부표3.")}
    assert s3()[("부표3.⑬기타필요경비계", "지급금액")] == "0" and ("부표3.①소계", "지급금액") in s3()
    d = _forms_copy(tmp_path)
    _edit_json(d / "매핑" / "부표3.json", lambda mm: mm["계"]["부표3.⑬기타필요경비계"].update({"0적음": False}))
    assert ("부표3.⑬기타필요경비계", "지급금액") not in s3(str(d))
    _edit_json(d / "매핑" / "부표3.json", lambda mm: mm.update(금액열="없는 열"))
    with pytest.raises(ValueError, match="없는 열"):
        s3(str(d))


def test_unplaced_is_judged_form_by_form(tmp_path):
    """국세 서식과 지방 서식은 저마다 신고·신고인·양수인 절을 놓거나 「안씀」으로 이유를 대야 한다. 한쪽 매핑에서 빠진 경로를
    다른 쪽 매핑이 가리지 않는다."""
    rv = _rv_cached("S1")
    assert forms.unplaced(rv) == []
    d = _forms_copy(tmp_path)
    _edit_json(d / "매핑" / "지방.json", lambda m: m["안씀"].pop("신고.홈택스ID"))
    assert forms.unplaced(rv, forms_dir=str(d)) == ["지방: 신고.홈택스ID"]
    d2 = _forms_copy(tmp_path / "second")
    _edit_json(d2 / "매핑" / "본지.json", lambda m: m["안씀"].pop("양수인[*].전화"))
    rv["양수인"][0]["전화"] = "0212345678"
    assert forms.unplaced(rv, forms_dir=str(d2)) == ["국세: 양수인[0].전화"]
    p = forms.plan(rv)
    assert set(p["서식별"]) == {"국세", "지방"} and "신고.홈택스ID" in p["서식별"]["지방"]["안씀"]
    assert "지방.열.국외소계" not in p["서식별"]["국세"]["안씀"]            # 지방 매핑의 항목은 국세 쪽에 섞이지 않는다


def _foreign(rv, code="CD"):
    """합성 신고인을 국적 code 인 외국인으로 바꾼 신고값."""
    rv["신고인"].update(내외국인="9", 국적=code)
    rv["신고인"]["코드"].update(내외국인여부="N", 국적=code)
    return rv


def test_code_without_a_korean_name_uses_the_english_name_or_stays_blank(tmp_path):
    """코드표에 코드는 있는데 한글 이름이 비어 있으면 멈추지 않는다. 신고인이 고칠 수 있는 입력이 아니기 때문이다.
    영문 이름이 있으면 그것을 적고(칸에 들어가지 않으면 비운다), 영문 이름도 없으면 비우고 확인사항으로 알린다.
    코드표 「국가」에서 한글 이름이 빈 코드는 CD(콩고민주공화국) 하나다(규격서 원문의 한글 명칭 칸이 비어 있다)."""
    import shutil
    codes = json.load(open(os.path.join(SKILL, "efile", "codes_c116300.json"), encoding="utf-8"))
    assert [k for k, v in codes["국가"].items() if not v["이름"]] == ["CD"] and codes["국가"]["CD"]["영문"]
    # 1) 국적 CD: 영문 이름이 후보이고, 본지와 지방 서식의 국적 칸(폭 52pt)에는 들어가지 않아 비운다
    rv = _foreign(_rv_cached("S1"))
    plan = forms.plan(rv)
    cell = next(p for p in plan["국세"]["칸"] if p["필드"] == "신고인.국적" and p["열"] == "국적")
    assert cell["값"] == [codes["국가"]["CD"]["영문"], ""]
    assert any("신고인.국적" in s and "한글 이름이 없어" in s and "CD" not in s for s in plan["확인사항"])
    paths = forms.render(rv, str(tmp_path / "cd"))
    for p in paths:
        assert "CONGO" not in pymupdf.open(p)[0].get_text()
    # 국적 칸의 확인사항은 한 줄이다. 본지와 지방 서식을 한 문장에 묶고, 「영문 이름을 적는다」는 미리 알림은 비웠다는 문장으로 바뀐다
    blank = [s for s in rv["확인사항"] if "국적" in s]
    assert len(blank) == 1 and "비워 두었다" in blank[0] and blank[0].count("국적") == 1
    assert "별지84 본지" in blank[0] and "별지40의11" in blank[0] and "CD" not in blank[0] and "CONGO" not in blank[0]
    assert not any(s.endswith(forms.forms_fmt.ENGLISH_NOTE_TAIL) for s in rv["확인사항"])
    # 2) 영문 이름이 짧으면 칸에 적는다
    e = tmp_path / "efile"
    shutil.copytree(os.path.join(SKILL, "efile"), str(e))
    _edit_json(e / "codes_c116300.json", lambda c: c["국가"]["CD"].update(영문="DR Congo"))
    cell = next(p for p in forms.plan(rv, efile_dir=str(e))["국세"]["칸"] if p["필드"] == "신고인.국적" and p["열"] == "국적")
    assert cell["값"] == ["DR Congo", ""]
    # 3) 영문 이름도 없는 코드(은행 표에는 영문 칸이 없다): 비우고 확인사항 한 줄. 코드 값은 싣지 않는다
    rv = _rv_cached("S1")
    rv["환급계좌"] = {"은행코드": "004", "계좌번호": "1234567890"}
    named = forms.plan(rv)
    assert any(p["필드"] == "환급계좌.금융기관명" for p in named["국세"]["칸"])               # 이름이 있으면 그대로 놓인다
    _edit_json(e / "codes_c116300.json", lambda c: c["은행"]["004"].update(이름=""))
    plan = forms.plan(rv, efile_dir=str(e))
    assert not any(p["필드"] == "환급계좌.금융기관명" for p in plan["국세"]["칸"])
    notes = [s for s in plan["확인사항"] if "금융기관명" in s]
    assert notes and all("이름이 코드표" in s and "비워 두었다" in s and "004" not in s for s in notes)
    # 4) 코드표에 없는 코드는 그대로 멈춘다(test_unknown_code_stops_instead_of_going_blank)


def test_area_and_period_formats():
    from yangdo import forms_fmt
    fmt = forms_fmt._Fmt({}, {}, {"특수지": {}})
    # 면적: 소수 둘째 자리까지, 셋째 자리 값이 있으면 셋째 자리까지. 그 아래는 신고값과 같이 버린다(반올림하지 않는다)
    assert [fmt("면적", v, {}) for v in (84.0, 84.5, 12.345, 1234.5, 0, None, "")] == ["84.00", "84.50", "12.345", "1,234.50", "", "", ""]
    assert fmt("면적", "84.9996", {}) == "84.999" and fmt("면적", "84.9951", {}) == "84.995"
    assert fmt("기간", "3년 이상 4년 미만", {}) == {"이상": "3", "미만": "4"}
    assert fmt("기간", "10년 이상", {}) == {"이상": "10", "미만": ""} and fmt("기간", "", {}) == ""
    with pytest.raises(ValueError) as e:
        fmt("기간", "약 3년쯤", {"필드": "보유기간"})
    assert "보유기간" in str(e.value) and "약 3년쯤" not in str(e.value)


def test_address_shortening_knows_the_merged_province_and_the_mountain_code():
    from yangdo import forms_fmt
    assert forms.SIDO_SHORT is forms_fmt.SIDO_SHORT and forms.SIDO_SHORT["전남광주통합특별시"] == "광주특별시"
    cands = forms_fmt._shorter("전남광주통합특별시 서구 치평동 1200 합성아파트 101동 1001호")
    assert "광주특별시 서구 치평동 1200 합성아파트 101동 1001호" in cands and cands[-1] == "치평동 1200"
    codes = json.load(open(os.path.join(SKILL, "efile", "codes_c116300.json"), encoding="utf-8"))
    fmt = forms_fmt._Fmt({}, {}, codes)
    addr = {"시도": "경기도", "시군구": "평택시", "읍면동": "고덕동", "특수지": "1", "번지": "12", "호": "3"}
    assert fmt("주소", addr, {})[0] == "경기도 평택시 고덕동 산 12-3"
    assert fmt("주소", dict(addr, 특수지="0"), {})[0] == "경기도 평택시 고덕동 12-3"
    codes["특수지"]["1"]["이름"], codes["특수지"]["2"]["이름"] = "가", "산"        # 「산」 코드는 코드표의 이름으로 찾는다
    fmt = forms_fmt._Fmt({}, {}, codes)
    assert fmt("주소", addr, {})[0] == "경기도 평택시 고덕동 12-3"
    assert fmt("주소", dict(addr, 특수지="2"), {})[0] == "경기도 평택시 고덕동 산 12-3"


def test_sources_hold_no_private_use_characters():
    """사용자 정의 영역 글자(U+E000~U+F8FF)는 편집기에서 보이지 않는다. 코드에는 \\uf000 같은 이스케이프로 적는다."""
    bad = []
    for sub in ("yangdo", "scripts", os.path.join("scripts", "refresh")):
        folder = os.path.join(SKILL, sub)
        for name in sorted(os.listdir(folder)):
            if name.endswith(".py"):
                src = open(os.path.join(folder, name), encoding="utf-8").read()
                if any(0xE000 <= ord(ch) <= 0xF8FF for ch in src):
                    bad.append(os.path.join(sub, name))
    assert bad == []


def test_local_form_uses_local_values():
    plan = forms.plan(_rv_cached("S1"))
    by = {(p["필드"], p["열"]): p["값"] for p in plan["지방"]["칸"] if p["쪽"] == 0}
    assert by[("산출세액", "지방소득세 합계")] == "3,834,946"
    assert by[("세율", "세율구분별 열1")] == "3.8%"
    assert by[("기본정보.신고유형", "첫_칸")] == "1"
    assert by[("기본정보.양도일자", "첫_칸")] == "2026.11.20"
    assert by[("신고인.납세지", "첫_칸")] == ["서울특별시 마포구", "서울 마포구", "마포구"]   # 시ㆍ군ㆍ구 단위까지(작성방법 2)
    assert by[("신고일자", "첫_칸")] == {"년": "2026", "월": "12", "일": "15"}


# ------------------------------------------------------------ 검토 뒤 마무리: 오류 원인 안내

def _cell(value, col="a", **kw):
    c = {"필드": "X", "열": col, "값": value, "맞춤": "left", "줄": 1, "pad": None}
    c.update(kw)
    return c


def _field(**kw):
    f = {"id": "X", "좌표": {"값_칸_해석": {"a": [10, 10, 60, 24]}}}
    f.update(kw)
    return f


def _blank_page():
    return pymupdf.open().new_page(width=200, height=100)


SENTINEL = "합성비밀값"


def test_write_overflow_says_value_does_not_fit_without_echoing_it():
    font = forms.forms_pdf.load_font()
    with pytest.raises(forms.forms_pdf.Overflow) as e:
        forms._write(_blank_page(), _field(), _cell(SENTINEL * 20), font)
    assert "들어가지 않는다" in str(e.value) and "값을 줄인다" in str(e.value)
    assert SENTINEL not in str(e.value)
    assert e.value.__cause__ is None and e.value.__suppress_context__


def test_write_uses_next_candidate_only_on_overflow():
    font = forms.forms_pdf.load_font()
    assert forms._write(_blank_page(), _field(), _cell([SENTINEL * 20, "짧다"]), font) == 1


@pytest.mark.parametrize("field, col, want", [
    (_field(쓰지않음="관리번호"), "a", "적지 않는 칸"),
    (_field(음영_열=["a"]), "a", "음영"),
    (_field(), "zz", "열"),
    (_field(기준점=[{"패턴": "@@", "쓰는곳": "뒤"}]), "a", "기준점"),
])
def test_write_other_value_errors_keep_their_own_reason(field, col, want):
    """기준점을 못 찾음·음영 칸·없는 열은 「칸에 값이 들어가지 않는다」 로 바뀌지 않고, 값도 싣지 않는다."""
    font = forms.forms_pdf.load_font()
    with pytest.raises(ValueError) as e:
        forms._write(_blank_page(), field, _cell(SENTINEL, col=col), font)
    msg = str(e.value)
    assert want in msg and "들어가지 않는다" not in msg and "값을 줄인다" not in msg
    assert not isinstance(e.value, forms.forms_pdf.Overflow)
    assert "X" in msg and SENTINEL not in msg


def test_write_does_not_try_next_candidate_after_a_non_overflow_error():
    font = forms.forms_pdf.load_font()
    with pytest.raises(ValueError) as e:
        forms._write(_blank_page(), _field(음영_열=["a"]), _cell(["하나", "둘"]), font)
    assert "음영" in str(e.value)


# ------------------------------------------------------------ 검토 뒤 마무리: 말없이 빈칸이 되는 길

@pytest.mark.parametrize("edit, kind", [
    (lambda rv: rv["양수인"][0].update(관계표기=None, 관계="QQ"), "관계"),
    (lambda rv: rv["신고인"].update(국적="QQ"), "국가"),
    (lambda rv: rv.update(환급계좌={"은행코드": "QQ"}), "은행"),
])
def test_unknown_code_stops_instead_of_going_blank(edit, kind):
    rv = _rv_cached("S1")
    edit(rv)
    with pytest.raises(ValueError) as e:
        forms.plan(rv)
    assert kind in str(e.value) and "코드표" in str(e.value)
    assert "QQ" not in str(e.value)


def test_known_codes_still_resolve():
    rv = _rv_cached("S1")
    rv["양수인"][0].update(관계표기=None, 관계="ZA")
    by = {(p["필드"], p["열"]): p["값"] for p in forms.plan(rv)["국세"]["칸"] if p["쪽"] == 0}
    assert by[("양수인", "양도인과의 관계")]


def test_check_value_not_in_mapping_stops_instead_of_going_blank():
    rv = _rv_cached("S1")
    rv["신고"]["구분"] = "수정"
    with pytest.raises(ValueError) as e:
        forms.plan(rv)
    assert "신고구분" in str(e.value) and "선택" in str(e.value)
    assert "수정" not in str(e.value)


def test_empty_check_value_stays_blank():
    rv = _rv_cached("S1")
    rv["신고인"]["거주구분"] = None
    by = {(p["필드"], p["열"]) for p in forms.plan(rv)["국세"]["칸"] if p["쪽"] == 0}
    assert not any(f == "신고인.거주구분" for f, _ in by)


def _slot_names(field, col):
    slots = field.get("기준점") or []
    slots = [slots] if isinstance(slots, dict) else slots
    return [s.get("부분") for s in slots if not s.get("열") or col in s["열"]]


_PART_KEYS = {"연월일": {"년", "월", "일"}, "세율구분": {"국내외분", "세율구분"}, "자산종류": {"자산종류", "코드"},
              "기간": {"이상", "미만"}, "고유번호": {"앞4자리", "가운데4자리", "뒤6자리"}}


def test_mapping_part_names_match_anchor_names():
    """매핑 「부분」 이름과 값 묶음의 키가 필드목록 기준점의 「부분」 이름과 같다. 다르면 그 부분이 말없이 빠진다."""
    bad = []
    for name, m in _mappings().items():
        fields = _fields(m["필드목록"])
        alias = m.get("열") or {}
        for c in m.get("칸", []):
            f = fields[c["필드"]]
            spec = c.get("열")
            a = alias.get(spec, spec)
            cols = (a["칸"] if isinstance(a, dict) else [a]) if spec else list((f.get("좌표") or {}).get("값_칸_해석") or {})
            for col in cols:
                names = _slot_names(f, col)
                if c.get("부분"):
                    if c["부분"] not in names:
                        bad.append((name, c["필드"], col, c["부분"], names))
                elif c.get("형식") in _PART_KEYS and names and set(names) != _PART_KEYS[c["형식"]]:
                    bad.append((name, c["필드"], col, c["형식"], names))
    assert bad == []


# ------------------------------------------------------------ 검토 뒤 마무리: 두 파일을 함께 바꾼다

def _fail_on_local(monkeypatch, how):
    real_write, real_save = forms._write, forms.forms_pdf.save

    def write(page, field, c, font):
        if how == "write" and "지방" in c["목록"]:
            raise ValueError("합성 실패")
        return real_write(page, field, c, font)

    def save(doc, path):
        if how == "save" and os.path.basename(path).startswith("지방소득세"):
            raise OSError("합성 저장 실패")
        return real_save(doc, path)

    monkeypatch.setattr(forms, "_write", write)
    monkeypatch.setattr(forms.forms_pdf, "save", save)


@pytest.mark.parametrize("how, exc", [("write", ValueError), ("save", OSError)])
def test_local_failure_leaves_no_new_national_pdf_or_tmp(tmp_path, monkeypatch, how, exc):
    _fail_on_local(monkeypatch, how)
    with pytest.raises(exc):
        forms.render(_rv_cached("S1"), str(tmp_path))
    assert os.listdir(str(tmp_path)) == []


@pytest.mark.parametrize("how, exc", [("write", ValueError), ("save", OSError)])
def test_local_failure_keeps_the_previous_pair_untouched(tmp_path, monkeypatch, how, exc):
    old = {"양도소득세_신고서.pdf": b"old-national", "지방소득세_신고서.pdf": b"old-local"}
    for n, b in old.items():
        (tmp_path / n).write_bytes(b)
    _fail_on_local(monkeypatch, how)
    with pytest.raises(exc):
        forms.render(_rv_cached("S1"), str(tmp_path))
    assert {n: (tmp_path / n).read_bytes() for n in os.listdir(str(tmp_path))} == old


def test_render_replaces_both_files_and_leaves_no_tmp(tmp_path):
    for n in ("양도소득세_신고서.pdf", "지방소득세_신고서.pdf"):
        (tmp_path / n).write_bytes(b"old")
    paths = forms.render(_rv_cached("S1"), str(tmp_path))
    assert sorted(os.listdir(str(tmp_path))) == ["양도소득세_신고서.pdf", "지방소득세_신고서.pdf"]
    assert all(pymupdf.open(p).page_count >= 2 for p in paths)
