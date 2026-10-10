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


def test_extract_refuses_length_mismatch_without_fixup(tmp_path, capsys):
    """길이 표와 필드 합이 다른데 FIXUPS 에 없는 레코드가 있으면 종료코드 1, 파일을 쓰지 않는다."""
    import extract_layout
    form = {"01": "C116300", "02": "C116300", "03": "C116300", "04": "C116300", "05": "C116400", "07": "C116600"}
    table = {"01": 300, "02": 400, "03": 450, "04": 150, "05": 700, "07": 200}
    total = dict(table, **{"01": 350, "04": 160})     # 01 은 FIXUP 이 있어 통과, 04 는 없음
    lines = ["##### TABLE 1  (앞 문단: 다. 테이블별 길이)", "서식명 | File | 길이"]
    lines += ["x | %s | %d" % (extract_layout.FILE_NAMES[k], n) for k, n in table.items()]
    for i, (k, n) in enumerate(total.items(), start=2):
        lines += ["", "##### TABLE %d  (앞 문단: ○ 시험)" % i,
                  "번호 | 한글명 | TYPE | 길이 | 누적 길이 | 비  고 | 점검내용 | 분류",
                  " | 자료구분 | CHAR | 2 | 2 | Not Null | %s | FIX" % k,
                  " | 서식코드 | CHAR | 7 | 9 | Not Null | %s | FIX" % form[k],
                  " | 공란 | CHAR | %d | %d | SPACE | 길이점검 | SPACE" % (n - 9, n)]
    src, pages, out = tmp_path / "표.txt", tmp_path / "쪽별.txt", tmp_path / "layout.json"
    src.write_text("# 원본: 양도소득세 전자신고 파일설명서_V5.17_(20260428).doc\n\n" + "\n".join(lines) + "\n", encoding="utf-8")
    pages.write_text("===== PAGE 1 =====\n1\n", encoding="utf-8")
    assert extract_layout.main(["--표", str(src), "--쪽", str(pages), "--출력", str(out)]) == 1
    assert not out.exists()
    err = capsys.readouterr().err.splitlines()
    assert any(x.startswith("오류: 04") and "160" in x and "150" in x for x in err), err


def test_codes_cover_engine_values():
    assert set(C["양수인관계"]) >= {"타인", "배우자", "직계", "친족", "법인", "기타특수관계"}
    assert set(C["증빙종류"]) >= {"세금계산서", "계산서", "카드영수증", "현금영수증", "계좌이체", "간이영수증", "없음"}
    assert set(C["양도등기원인"]) >= {"매매", "경매"} and set(C["취득등기원인"]) >= {"매매", "분양", "신축", "경매", "공공매입"}
    assert all(len(v["코드"]) == 3 for v in C["필요경비구분"].values())
