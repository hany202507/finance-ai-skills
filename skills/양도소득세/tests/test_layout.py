# -*- coding: utf-8 -*-
import json
import os

SKILL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
L = json.load(open(os.path.join(SKILL, "efile", "layout_c116300.json"), encoding="utf-8"))
C = json.load(open(os.path.join(SKILL, "efile", "codes_c116300.json"), encoding="utf-8"))
SPEC_LEN = {"01": 350, "02": 400, "03": 450, "04": 150, "05": 700, "07": 200}   # 01 은 FIXUP


def test_record_lengths_match_spec():
    for k, n in SPEC_LEN.items():
        r = L["레코드"][k]
        assert r["길이"] == n == sum(f["len"] for f in r["필드"])


def test_start_end_are_contiguous():
    for r in L["레코드"].values():
        pos = 1
        for f in r["필드"]:
            assert f["start"] == pos and f["end"] == pos + f["len"] - 1
            pos += f["len"]


def test_every_record_starts_with_kind_and_form_code():
    for k, r in L["레코드"].items():
        a, b = r["필드"][0], r["필드"][1]
        assert (a["name"], a["check"], b["name"]) == ("자료구분", k, "서식코드")
        assert b["check"] == r["서식코드"]


def test_header_fixup_is_recorded():
    assert any(x["레코드"] == "01" and "350" in x["내용"] for x in L["FIXUPS"])


def test_names_unique_within_record():
    for r in L["레코드"].values():
        names = [f["name"] for f in r["필드"]]
        assert len(names) == len(set(names))


def test_types_and_classes_known():
    for r in L["레코드"].values():
        for f in r["필드"]:
            assert f["type"] in ("C", "N") and f["class"] in {"FIX", "LIST", "CODE", "AMT", "AMT+", "RATE", "SEQ", "DATE", "ID", "USERID", "SPACE", ""}


FORM = {"01": "C116300", "02": "C116300", "03": "C116300", "04": "C116300", "05": "C116400", "07": "C116600"}
TABLE_LEN = {"01": 300, "02": 400, "03": 450, "04": 150, "05": 700, "07": 200}
# 합성 레코드의 공란 앞 행. FIXUPS 가 가리키는 행(01-9 셀, 02 삭제행, 05-4 분류칸·허용, 05-5 셀)을 원문 모양 그대로 넣는다
BODY = {
    "01": [" | 칸%d | CHAR | 1 | %d | Null 허용 | 길이점검 | " % (no, 7 + no) for no in range(3, 9)]
          + [" | 신고구분상세코드 | CHAR | 2 | 17 | Not Null | 01,03 |  | 3 | 35 | Not null | "],
    "02": ["삭제 | 도로명_법정동코드(행안부) | CHAR | 10 | 19 | Null 허용 | 길이점검 | "],
    "05": [" | 일련번호 | CHAR | 6 | 15 | Not Null default 1 | (2) | 숫자,길이점검 | SEQ",
           " | 과세구분 | CHAR | 2 | 17 | Not Null |  |  | 01,05",
           " | 국내외분(소재지) | CHAR | 1 | 18 | Not Null | (1) | 1 | 1,2"],
}
BODY_END = {"01": 17, "02": 9, "05": 18}


def synthetic(tmp_path, total, extra=None):
    """total: 레코드별 필드 합(공란으로 맞춤). 길이 표는 TABLE_LEN. extra: {레코드: (행 목록, 공란 앞 누적)}."""
    import extract_layout
    body = dict((k, (v, BODY_END[k])) for k, v in BODY.items())
    body.update(extra or {})
    lines = ["##### TABLE 1  (앞 문단: 다. 테이블별 길이)", "서식명 | File | 길이"]
    lines += ["x | %s | %d" % (extract_layout.FILE_NAMES[k], n) for k, n in TABLE_LEN.items()]
    for i, k in enumerate(TABLE_LEN, start=2):
        rows, pos = body.get(k, ([], 9))
        lines += ["", "##### TABLE %d  (앞 문단: ○ 시험)" % i,
                  "번호 | 한글명 | TYPE | 길이 | 누적 길이 | 비  고 | 점검내용 | 분류",
                  " | 자료구분 | CHAR | 2 | 2 | Not Null | %s | FIX" % k,
                  " | 서식코드 | CHAR | 7 | 9 | Not Null | %s | FIX" % FORM[k]]
        lines += rows
        lines += [" | 공란 | CHAR | %d | %d | SPACE | 길이점검 | SPACE" % (total[k] - pos, total[k])]
    src, pages, out = tmp_path / "표.txt", tmp_path / "쪽별.txt", tmp_path / "layout.json"
    head = "# 원본: 양도소득세 전자신고 파일설명서_V5.17_(20260428).doc"
    src.write_text("\n".join([head, ""] + lines) + "\n", encoding="utf-8")
    pages.write_text("===== PAGE 1 =====\n1\n", encoding="utf-8")
    return ["--표", str(src), "--쪽", str(pages), "--출력", str(out)], out


def errors(capsys):
    return [x for x in capsys.readouterr().err.splitlines() if x.startswith("오류: ")]


def test_extract_applies_fixups_on_synthetic_input(tmp_path, capsys):
    """FIXUPS 대상 행이 원문 모양이면 오류 없이 쓴다. 01 은 길이 표 300 이지만 FIXUP 350 으로 통과한다."""
    import extract_layout
    args, out = synthetic(tmp_path, dict(TABLE_LEN, **{"01": 350}))
    assert extract_layout.main(args) == 0, errors(capsys)
    lay = json.load(open(out, encoding="utf-8"))["레코드"]
    assert (lay["01"]["길이"], lay["01"]["길이표"], lay["01"]["필드"][8]["check"]) == (350, 300, "01,03")
    assert [d["name"] for d in lay["02"]["삭제행"]] == ["도로명_법정동코드(행안부)"] and lay["02"]["길이"] == 400
    f4, f5 = lay["05"]["필드"][3], lay["05"]["필드"][4]
    assert (f4["check"], f4["허용"], f5["check"]) == ("01,05", ["01", "05", "ZZ"], "1,2")


def test_extract_refuses_length_mismatch_without_fixup(tmp_path, capsys):
    """길이 표와 필드 합이 다른데 FIXUPS 에 없는 레코드가 있으면 종료코드 1, 파일을 쓰지 않는다. 오류는 그 레코드 하나뿐이다."""
    import extract_layout
    args, out = synthetic(tmp_path, dict(TABLE_LEN, **{"01": 350, "04": 160}))
    assert extract_layout.main(args) == 1
    assert not out.exists()
    err = errors(capsys)
    assert len(err) == 1 and err[0].startswith("오류: 04") and "160" in err[0] and "150" in err[0], err


def test_extract_refuses_fixup_length_that_differs_from_fields(tmp_path, capsys, monkeypatch):
    """FIXUPS 길이 값(351)이 필드 합(350)과 다르면 통과시키지 않는다."""
    import extract_layout
    fixups = [dict(x, 값=351) if (x["레코드"], x["종류"]) == ("01", "길이") else x for x in extract_layout.FIXUPS]
    monkeypatch.setattr(extract_layout, "FIXUPS", fixups)
    args, out = synthetic(tmp_path, dict(TABLE_LEN, **{"01": 350}))
    assert extract_layout.main(args) == 1
    assert not out.exists()
    err = errors(capsys)
    assert len(err) == 1 and err[0].startswith("오류: 01") and "350" in err[0] and "300" in err[0], err


def test_extract_refuses_unlisted_class_cell_value(tmp_path, capsys):
    """분류 칸에 분류 이름이 아닌 값이 있는데 FIXUPS 에 없으면 거부한다."""
    import extract_layout
    extra = {"04": ([" | 양수인_주민사업자구분 | CHAR | 1 | 10 | Not Null |  |  | 1,2"], 10)}
    args, out = synthetic(tmp_path, dict(TABLE_LEN, **{"01": 350}), extra)
    assert extract_layout.main(args) == 1
    assert not out.exists()
    err = errors(capsys)
    assert len(err) == 1 and err[0].startswith("오류: 04 3") and "분류 칸" in err[0], err


def test_layout_allows_zz_for_taxation_kind():
    f = L["레코드"]["05"]["필드"][3]
    assert (f["name"], f["check"], f["허용"]) == ("과세구분", "01,05", ["01", "05", "ZZ"])
    kinds = {(x["레코드"], x.get("no"), x["종류"]) for x in L["FIXUPS"]}
    assert {("05", 4, "분류칸"), ("05", 4, "허용")} <= kinds


def test_codes_follow_runtime_decisions():
    assert (C["증빙종류"]["계좌이체"]["코드"], C["증빙종류"]["계좌이체"]["쪽"]) == ("10", 61)
    for cause in ("분양", "공공매입"):
        assert C["취득등기목적"][cause]["코드"] == "A1ZZCZ" and C["취득등기목적"][cause]["확인"]
        assert C["취득등기원인"][cause]["코드"] == "0055" and C["취득등기원인"][cause]["확인"]
        assert C["취득등기목적"][cause]["확인"].startswith("등기사항증명서와 다르면 신고인 JSON 자산[id].등기목적.취득(6자리)으로 고친다")
        assert C["취득등기원인"][cause]["확인"].startswith("등기사항증명서와 다르면 신고인 JSON 자산[id].등기원인.취득(4자리)으로 고친다")
    assert C["취득등기원인"]["경매"]["코드"] is None and C["양도등기원인"]["경매"]["코드"] is None
    assert all(C["양수인관계"][k]["코드"] is None for k in ("배우자", "직계", "친족", "법인", "기타특수관계"))
    assert C["양수인관계"]["타인"]["코드"] == "ZA"
    assert C["양수인관계목록"]["00"].get("무효") is True
    assert (C["거주구분"]["1"]["코드"], C["거주구분"]["9"]["코드"]) == ("N", "Y")
    assert "확인" in C["메타"]


def test_codes_cover_engine_values():
    assert set(C["양수인관계"]) >= {"타인", "배우자", "직계", "친족", "법인", "기타특수관계"}
    assert set(C["증빙종류"]) >= {"세금계산서", "계산서", "카드영수증", "현금영수증", "계좌이체", "간이영수증", "없음"}
    assert set(C["양도등기원인"]) >= {"매매", "경매"} and set(C["취득등기원인"]) >= {"매매", "분양", "신축", "경매", "공공매입"}
    assert all(len(v["코드"]) == 3 for v in C["필요경비구분"].values())
