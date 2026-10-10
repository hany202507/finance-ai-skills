# -*- coding: utf-8 -*-
import hashlib
import importlib.util
import json
import os

import pymupdf
import pytest

from yangdo import forms_pdf

SKILL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FORMS = os.path.join(SKILL, "forms")
FL = os.path.join(FORMS, "필드목록")
PDF84 = os.path.join(FORMS, "원본", "별지84_양도소득과세표준신고및납부계산서.pdf")


def _load(name):
    with open(os.path.join(FL, name), encoding="utf-8") as f:
        return json.load(f)


F0 = _load("필드목록_별지84_신고및납부계산서.json")
F1 = _load("필드목록_별지84부표1_양도소득금액계산명세서.json")
F3 = _load("필드목록_별지84부표3_취득가액및필요경비계산상세명세서.json")


def _field(d, fid):
    return next(f for f in d["fields"] if f["id"] == fid)


def _printed(page):
    return [pymupdf.Rect(w[:4]) for w in page.get_text("words")]


def _overlaps(used, printed):
    return [p for u in used for p in printed if u.intersects(p) and (u & p).get_area() > 1]


def _all_lists():
    docs = {}
    for name in sorted(os.listdir(FL)):
        d = _load(name)
        path = os.path.join(FORMS, d["meta"]["원본파일"])
        if path not in docs:
            docs[path] = pymupdf.open(path)
        yield name, d, docs[path]


def _cells(f):
    """(열, 칸, 그 열에 걸리는 기준점) 목록. 칸이 없으면 라벨 상자에서 기준점을 찾는다."""
    c = f.get("좌표") or {}
    g = c.get("값_칸_해석") or {}
    slots = f.get("기준점") or []
    if not g:
        return [(None, c["라벨_bbox"], slots)] if slots else []
    return [(col, r, [s for s in slots if not s.get("열") or col in s["열"]]) for col, r in g.items()]


def test_font_renders_hangul():
    font, name, _ = forms_pdf.load_font()
    assert font.has_glyph(ord("양"))
    assert name


def test_env_font_comes_first(tmp_path, monkeypatch):
    p = tmp_path / "f.ttf"
    p.write_bytes(pymupdf.Font("korea").buffer)
    monkeypatch.setenv("YANGDO_FONT", str(p))
    font, name, path = forms_pdf.load_font()
    assert path == str(p) and font.has_glyph(ord("양"))


def test_builtin_font_path_writes_extractable_hangul(tmp_path, monkeypatch):
    monkeypatch.delenv("YANGDO_FONT", raising=False)
    monkeypatch.setattr(forms_pdf, "_font_candidates", lambda: [])
    font = forms_pdf.load_font()
    assert font[2] is None and font[0].has_glyph(ord("양"))
    doc = pymupdf.open(PDF84)
    rect = pymupdf.Rect(300, 200, 400, 212)
    used = forms_pdf.put(doc[0], rect, "김합성", font=font)
    assert rect.contains(used)
    out = str(tmp_path / "b.pdf")
    assert forms_pdf.save(doc, out) < 600_000
    assert "김합성" in pymupdf.open(out)[0].get_text(clip=rect)


def test_amount_lands_inside_cell_and_avoids_printed_text(tmp_path):
    doc = pymupdf.open(PDF84)
    page = doc[4]                                    # 부표1 (5쪽)
    rect = pymupdf.Rect(_field(F1, "양도가액")["좌표"]["값_칸_해석"]["자산1"])
    printed = _printed(page)
    used = forms_pdf.put(page, rect, "1,800,000,000")
    assert rect.contains(used)
    assert not _overlaps([used], printed)


def test_long_text_shrinks_instead_of_overflowing(tmp_path):
    doc = pymupdf.open(PDF84)
    rect = pymupdf.Rect(100, 100, 200, 110)
    used = forms_pdf.put(doc[0], rect, "아주긴상호명합성인테리어주식회사")
    assert rect.contains(used)


def test_text_that_cannot_fit_raises(tmp_path):
    doc = pymupdf.open(PDF84)
    with pytest.raises(ValueError):
        forms_pdf.put(doc[0], pymupdf.Rect(100, 100, 140, 110), "아주긴상호명합성인테리어주식회사")


def test_two_lines_when_allowed():
    doc = pymupdf.open(PDF84)
    page = doc[4]
    rect = pymupdf.Rect(_field(F1, "소재지국")["좌표"]["값_칸_해석"]["자산1"])
    used = forms_pdf.put(page, rect, "서울특별시 성동구 성수동 123", align="left", lines=2)
    assert rect.contains(used)
    assert "성수동" in page.get_text(clip=rect)


def test_anchor_finds_printed_hyphen_in_rate_code_cell():
    doc = pymupdf.open(PDF84)
    f = next(x for x in F0["fields"] if x["번호"] == "③")
    rect = pymupdf.Rect(f["좌표"]["값_칸_해석"]["세율구분별 열1"])
    a = forms_pdf.anchor(doc[0], rect, "-")
    assert a is not None and rect.contains(a)


def test_rate_code_is_split_around_printed_hyphen():
    doc = pymupdf.open(PDF84)
    page = doc[0]
    f = _field(F0, "세율구분코드")
    rect = pymupdf.Rect(f["좌표"]["값_칸_해석"]["세율구분별 열1"])
    printed = _printed(page)
    hy = forms_pdf.anchor(page, rect, "-")
    used = forms_pdf.put_field(page, f, {"국내외분": "1", "세율구분": "10"}, col="세율구분별 열1")
    assert used[0].x1 <= hy.x0 and used[1].x0 >= hy.x1
    assert all(rect.contains(u) for u in used)
    assert not _overlaps(used, printed)


def test_schedule1_bracket_cells_keep_clear_of_printed_marks():
    doc = pymupdf.open(PDF84)
    page = doc[4]
    printed = _printed(page)
    used = []
    for fid, value in [("세율구분코드", {"국내외분": "1", "세율구분": "10"}),
                       ("자산종류코드", {"자산종류": "고가주택", "코드": "2"}),
                       ("양도일원인", {"일자": "2026.11.20", "원인": "매매"}),
                       ("취득일원인", {"일자": "2018.03.15", "원인": "매매"}),
                       ("총면적.건물", {"면적": "84.00", "지분분자": "1", "지분분모": "1"}),
                       ("보유기간", {"이상": "8", "미만": "9"}),
                       ("장기보유특별공제", {"금액": "233,839,999", "코드": "01"}),
                       ("장특공적용대상거주기간", {"이상": "7", "미만": "8"})]:
        f = _field(F1, fid)
        rect = pymupdf.Rect(f["좌표"]["값_칸_해석"]["자산1"])
        got = forms_pdf.put_field(page, f, value, col="자산1")
        assert len(got) == len(value) and all(rect.contains(u) for u in got), fid
        used += got
    assert not _overlaps(used, printed)
    text = page.get_text()
    for s in ("233,839,999", "2026.11.20", "매매", "84.00"):
        assert s in text


def test_schedule3_detail_amount_uses_amount_column():
    total = _field(F3, "부표3.⑤계")["좌표"]["값_칸_해석"]["지급금액"]
    for f in F3["fields"]:
        r = f["좌표"]["값_칸_해석"]["지급금액"]
        assert (r[0], r[2]) == (total[0], total[2]), f["id"]


def test_shaded_columns_are_refused():
    doc = pymupdf.open(PDF84)
    page = doc[13]
    f = _field(F3, "부표3.매입가액")
    assert "지급일" in f["음영_열"] and "지급금액" not in f["음영_열"]
    with pytest.raises(ValueError):
        forms_pdf.put_field(page, f, "2018.03.15", col="지급일")
    used = forms_pdf.put_field(page, f, "600,000,000", col="지급금액")
    assert pymupdf.Rect(f["좌표"]["값_칸_해석"]["지급금액"]).contains(used[0])


def test_schedule3_part2_has_thirty_rows():
    d = _load("필드목록_별지84부표3_2_취득가액및필요경비계산상세명세서.json")
    rows = [f for f in d["fields"] if f["id"].startswith("부표3(2).")]
    assert len(rows) == 30 and {f["쪽"] for f in rows} == {16}
    cols = ["구분코드", "구분", "거래상대방 상호", "거래상대방 사업자등록번호", "지급일", "지급금액", "증빙종류(코드)"]
    ys = []
    for f in rows:
        g = f["좌표"]["값_칸_해석"]
        assert list(g) == cols, f["id"]
        ys.append(g["지급금액"][1])
    assert ys == sorted(ys)


def test_checkbox_cells_sit_inside_printed_brackets():
    doc = pymupdf.open(PDF84)
    page = doc[0]
    f = _field(F0, "신고구분")
    assert list(f["좌표"]["값_칸_해석"]) == ["예정신고", "확정신고", "수정신고", "기한후신고"]
    used = forms_pdf.put_field(page, f, "V", col="예정신고")
    assert pymupdf.Rect(f["좌표"]["값_칸_해석"]["예정신고"]).contains(used[0])


def test_saved_pdf_is_small(tmp_path):
    doc = pymupdf.open(PDF84)
    forms_pdf.put(doc[0], pymupdf.Rect(300, 200, 400, 212), "김합성")
    n = forms_pdf.save(doc, str(tmp_path / "o.pdf"))
    assert n < 600_000


def test_every_mapped_field_has_a_value_cell():
    for name in os.listdir(FL):
        d = _load(name)
        for f in d["fields"]:
            if f.get("음영") or f.get("쓰지않음"):
                continue
            c = f.get("좌표", {})
            assert c.get("값_칸_해석") or c.get("값_칸") or f.get("기준점"), (name, f["id"])


def test_field_lists_point_to_registered_originals():
    reg = json.load(open(os.path.join(FORMS, "서식판.json"), encoding="utf-8"))["서식"]
    by_file = {v["파일"]: v for v in reg.values()}
    for name in os.listdir(FL):
        m = _load(name)["meta"]
        v = by_file[m["원본파일"]]
        assert m["sha256"] == v["sha256"], name
        pages = {p for ps in v["쪽"].values() for p in ps}
        assert {f["쪽"] for f in _load(name)["fields"]} <= pages, name


def test_plain_value_cells_have_no_printed_text():
    """기준점 없이 쓰는 칸 안에 인쇄 글자가 있으면 값이 그 글자와 겹친다."""
    bad = []
    for name, d, doc in _all_lists():
        for f in d["fields"]:
            if f.get("음영") or f.get("쓰지않음"):
                continue
            page = doc[f["쪽"] - 1]
            words = page.get_text("words")
            for col, r, slots in _cells(f):
                if slots or col is None or col in f.get("음영_열", []):
                    continue
                R = pymupdf.Rect(r)
                hit = [w[4] for w in words if R.contains(pymupdf.Point((w[0] + w[2]) / 2, (w[1] + w[3]) / 2))]
                if hit:
                    bad.append((name, f["id"], col, hit))
    assert not bad, bad


def test_anchor_patterns_are_printed_where_the_list_says():
    bad = []
    for name, d, doc in _all_lists():
        for f in d["fields"]:
            page = doc[f["쪽"] - 1]
            for col, r, slots in _cells(f):
                for s in slots:
                    if forms_pdf.anchor(page, pymupdf.Rect(r), s["패턴"], nth=s.get("순번", 0)) is None:
                        bad.append((name, f["id"], col, s["패턴"]))
    assert not bad, bad


def _fetcher_module():
    spec = importlib.util.spec_from_file_location("forms_fetch", os.path.join(FORMS, "_받기.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_refetch_keeps_file_when_a_new_edition_appears(tmp_path):
    mod = _fetcher_module()
    os.makedirs(tmp_path / "원본")
    old = b"%PDF-1.7 old" + b"0" * 3000
    (tmp_path / "원본" / "a.pdf").write_bytes(old)
    reg = {"서식": {"별지84": {"파일": "원본/a.pdf", "sha256": hashlib.sha256(old).hexdigest(), "flSeq": 1}}}
    (tmp_path / "서식판.json").write_text(json.dumps(reg), encoding="utf-8")
    new = b"%PDF-1.7 new" + b"1" * 3000
    lines = []
    assert mod.run(str(tmp_path), fetch=lambda seq: old, out=lines.append) == 0
    assert mod.run(str(tmp_path), fetch=lambda seq: new, out=lines.append) == 1
    assert (tmp_path / "원본" / "a.pdf").read_bytes() == old
    assert mod.run(str(tmp_path), 교체=True, fetch=lambda seq: new, out=lines.append) == 0
    assert (tmp_path / "원본" / "a.pdf").read_bytes() == new
    assert any("새 판" in s for s in lines)
