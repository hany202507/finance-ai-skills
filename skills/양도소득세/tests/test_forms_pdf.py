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


def test_plain_cell_refuses_dict_or_list_value():
    """기준점이 없는 칸에 묶음 값을 주면 글자로 바꿔 쓰지 않고 막는다(「{'a': 1}」 이 서식에 찍히지 않게)."""
    doc = pymupdf.open(PDF84)
    page = doc[4]
    f = _field(F1, "양도가액")
    for bad in ({"금액": "1,000"}, ["1,000"], ("1,000",)):
        with pytest.raises(ValueError):
            forms_pdf.put_field(page, f, bad, col="자산1")
    assert "1,000" not in page.get_text()


def test_put_field_passes_padding_to_narrow_cells():
    doc = pymupdf.open(PDF84)
    page = doc[13]
    f = _field(F3, "부표3.법무사비용")
    rect = pymupdf.Rect(f["좌표"]["값_칸_해석"]["지급일"])
    wide = forms_pdf.put_field(page, f, "2018.03.15", col="지급일", pad=0.5)[0]
    assert rect.contains(wide)
    doc2 = pymupdf.open(PDF84)
    narrow = forms_pdf.put_field(doc2[13], f, "2018.03.15", col="지급일")[0]
    assert wide.height > narrow.height                  # 여백을 줄이면 글자를 덜 줄인다


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


def test_put_overflow_is_its_own_value_error_subclass():
    page = pymupdf.open().new_page(width=200, height=100)
    with pytest.raises(forms_pdf.Overflow) as e:
        forms_pdf.put(page, [10, 10, 40, 24], "합성" * 30)
    assert isinstance(e.value, ValueError)
    assert "합성" not in str(e.value) and "60자" in str(e.value)      # 글자는 싣지 않고 글자 수만 적는다
    assert page.get_text().strip() == ""


def test_put_field_overflow_names_the_cell_not_the_value():
    page = pymupdf.open().new_page(width=200, height=100)
    field = {"id": "X칸", "좌표": {"값_칸_해석": {"a": [10, 10, 40, 24]}}}
    with pytest.raises(forms_pdf.Overflow) as e:
        forms_pdf.put_field(page, field, "합성" * 30, col="a")
    assert "X칸" in str(e.value) and " a" in str(e.value) and "합성" not in str(e.value)


def _anchored_page():
    """가운데에 「-」 가 인쇄된 칸 하나짜리 쪽. (쪽, 칸, 기준점 둘)."""
    page = pymupdf.open().new_page(width=200, height=100)
    rect = [10, 10, 110, 30]
    font = forms_pdf.load_font()
    forms_pdf._ensure(page, font)
    page.insert_text((58, 24), "-", fontsize=8, fontname=font[1])
    slots = [{"패턴": "-", "쓰는곳": "앞", "부분": "앞"}, {"패턴": "-", "쓰는곳": "뒤", "부분": "뒤"}]
    return page, rect, slots


def test_anchored_cell_writes_nothing_when_a_later_part_overflows():
    """기준점 칸은 모든 부분이 들어가는지 먼저 재고 쓴다. 뒤 부분이 넘치면 앞 부분도 쪽에 남지 않는다."""
    page, rect, slots = _anchored_page()
    with pytest.raises(forms_pdf.Overflow):
        forms_pdf.put_anchored(page, rect, slots, {"앞": "12", "뒤": "합성" * 30})
    assert page.get_text().split() == ["-"]                         # 인쇄된 글자만 남았다
    used = forms_pdf.put_anchored(page, rect, slots, {"앞": "12", "뒤": "34"})
    assert len(used) == 2 and sorted(page.get_text().split()) == ["-", "12", "34"]
    assert used[0].x1 <= 58 <= used[1].x0                           # 앞 부분은 「-」 왼쪽, 뒤 부분은 오른쪽


def test_put_field_refuses_fields_the_filer_does_not_write():
    """「쓰지않음」 필드(관리번호, 인쇄된 목록 등)는 값을 주어도 쓰지 않고 이유를 댄다."""
    page = pymupdf.open().new_page(width=200, height=100)
    field = {"id": "관리번호", "좌표": {"값_칸_해석": {"a": [10, 10, 60, 24]}}, "쓰지않음": "세무서가 적는 칸"}
    with pytest.raises(ValueError) as e:
        forms_pdf.put_field(page, field, "123", col="a")
    assert "적지 않는 칸" in str(e.value) and "세무서가 적는 칸" in str(e.value) and not isinstance(e.value, forms_pdf.Overflow)
    assert page.get_text().strip() == ""
    # 실제 필드목록의 쓰지않음 필드도 모두 거절한다
    refused = 0
    for name, d, _doc in _all_lists():
        for f in d["fields"]:
            if f.get("쓰지않음"):
                with pytest.raises(ValueError, match="적지 않는 칸"):
                    forms_pdf.put_field(page, f, "1")
                refused += 1
    assert refused > 0


def test_used_box_covers_the_text_that_was_written():
    """put 이 돌려주는 상자는 실제로 쓴 글자를 덮는다. 쪽에서 다시 읽은 낱말 상자가 그 안에 있고 칸을 넘지 않는다."""
    for text, align, lines, rect in (("1,800,000,000", "right", 1, [10, 10, 110, 24]), ("합성아파트", "left", 1, [10, 30, 110, 44]),
                                     ("서울특별시 성동구 성수동1가 456", "left", 2, [10, 50, 80, 74]), ("V", "center", 1, [120, 10, 132, 22])):
        page = pymupdf.open().new_page(width=200, height=100)
        used = forms_pdf.put(page, rect, text, align=align, lines=lines)
        words = [pymupdf.Rect(w[:4]) for w in page.get_text("words")]
        assert words and "".join(w[4] for w in page.get_text("words")) == text.replace(" ", "")
        cell = pymupdf.Rect(rect)
        for w in words:
            assert used.x0 - 0.6 <= w.x0 and w.x1 <= used.x1 + 0.6, (text, w, used)      # 낱말 상자의 가로가 쓴 상자 안
            assert used.y0 - 1.5 <= w.y0 and w.y1 <= used.y1 + 1.5, (text, w, used)
        assert cell.x0 - 0.01 <= used.x0 and used.x1 <= cell.x1 + 0.01 and cell.y0 - 0.01 <= used.y0 and used.y1 <= cell.y1 + 0.01


def test_put_field_non_overflow_errors_are_not_overflow():
    page = pymupdf.open().new_page(width=200, height=100)
    shaded = {"id": "X", "좌표": {"값_칸_해석": {"a": [10, 10, 60, 24]}}, "음영_열": ["a"]}
    for field, col in ((shaded, "a"), ({"id": "X", "좌표": {"값_칸_해석": {"a": [10, 10, 60, 24]}}}, "zz")):
        with pytest.raises(ValueError) as e:
            forms_pdf.put_field(page, field, "가", col=col)
        assert not isinstance(e.value, forms_pdf.Overflow)
