# -*- coding: utf-8 -*-
import hashlib
import json
import os

import pytest

import import_bjd
from yangdo import bjd

B = bjd.load()


def test_known_codes():
    assert B.lookup("서울특별시", "종로구", "청운동") == "1111010100"
    assert B.lookup("서울특별시", "성동구", "성수동") is None          # 성수동1가·2가로 나뉘어 하나로 정할 수 없다
    assert set(B.candidates("서울특별시", "성동구", "성수동")) >= {"1120011400", "1120011500"}


def test_exists_only_current():
    assert B.exists("1111010100")
    assert not B.exists("0000000000")


def test_ri_level_codes_are_not_returned_for_eup_myeon():
    codes = B.candidates("경기도", "평택시", "고덕동")
    assert codes and all(c.endswith("00") for c in codes)


# --- 위는 계획서 시험. 아래는 자료의 모양을 붙잡는 시험 ---

def test_eup_myeon_and_ri_are_separate_keys():
    # 읍·면 이름만 적으면 읍·면 코드 하나이고, 리 코드는 「읍면 리」 로 적어야 받는다
    assert B.candidates("경기도", "평택시", "고덕면") == ["4122033000"]
    assert B.lookup("경기도", "평택시", "고덕면 당현리") == "4122033021"
    assert B.lookup("경기도", "평택시", "당현리") is None


def test_exact_name_wins_over_numbered_variants():
    # 영등포동 은 그 이름의 법정동이 따로 있고 영등포동1가 ~ 8가도 있다. 적은 이름 그대로인 쪽을 돌려준다
    assert B.lookup("서울특별시", "영등포구", "영등포동") == "1156010100"
    assert B.lookup("서울특별시", "영등포구", "영등포동1가") == "1156010200"
    assert len(B.candidates("서울특별시", "성동구", "성수동")) == 2


def test_hanja_suffix_rows_are_ambiguous_without_hanja():
    c = B.candidates("충청북도", "청주시 상당구", "미원면 기암리")
    assert c == ["4311132026", "4311132033"]
    assert B.lookup("충청북도", "청주시 상당구", "미원면 기암리") is None
    assert B.lookup("충청북도", "청주시 상당구", "미원면 기암리(基岩)") == "4311132033"


def test_general_gu_is_part_of_sigungu():
    assert B.lookup("경기도", "수원시 장안구", "파장동") == "4111112900"
    assert B.lookup("경기도", "수원시", "파장동") is None              # 구 이름까지 적어야 한다
    assert B.lookup("경기도", "화성시 효행구", "기안동") == "4159310200"
    assert B.lookup("경기도", "화성시", "기안동") is None


def test_sejong_has_no_sigungu():
    assert B.lookup("세종특별자치시", "", "반곡동") == "3611010100"
    assert B.lookup("세종특별자치시", None, "반곡동") == "3611010100"


def test_whitespace_is_normalized():
    assert B.lookup(" 서울특별시", "종로구 ", "청운동") == "1111010100"
    assert B.lookup("경기도", "평택시", "고덕면  당현리") == "4122033021"


def test_blank_or_unknown_names_return_nothing():
    assert B.candidates("서울특별시", "종로구", "") == []
    assert B.candidates("서울특별시", "종로구", None) == []
    assert B.candidates("서울특별시", "없는구", "청운동") == []
    assert B.lookup("서울특별시", "종로구", "없는동") is None


def test_name_of_code():
    assert B.name("1111010100") == "서울특별시 종로구 청운동"
    assert B.name("4159310200") == "경기도 화성시 효행구 기안동"
    assert B.name("0000000000") is None


def test_exists_accepts_every_level_but_only_strings():
    assert B.exists("1100000000")        # 시도
    assert B.exists("1111000000")        # 시군구
    assert B.exists("3611000000")        # 세종은 시도 코드가 3611000000
    assert not B.exists("3600000000")
    assert not B.exists("111101010")     # 9자리
    assert not B.exists(1111010100)
    assert not B.exists(None)


def test_abolished_names_are_not_found():
    # 2026-07-01 에 광주광역시·전라남도가 없어지고 전남광주통합특별시가 생겼다(자료 기준). 존재 행만 담는다
    assert not B.exists("2900000000")
    assert not B.exists("4600000000")
    assert B.exists("1200000000")
    assert B.lookup("전남광주통합특별시", "강진군", "강진읍") == "1278025000"
    assert B.lookup("전남광주통합특별시", "동구", "충장로1가") == "1221012700"


def test_old_gwangju_jeonnam_names_return_none_even_with_date():
    # 행정구역_대응.json 은 이 둘을 ★★☆(해석) 로 두었다. 코드 찾기에서는 바꾸지 않고 질문으로 넘긴다
    for on in (None, "2026-06-30", "2026-07-01", "2026-12-20"):
        assert B.lookup("광주광역시", "동구", "충장로1가", on=on) is None
        assert B.lookup("전라남도", "강진군", "강진읍", on=on) is None
        assert B.candidates("전라남도", "강진군", "강진읍", on=on) == []


def test_confirmed_renames_apply_from_their_start_date():
    new = B.lookup("강원특별자치도", "춘천시", "효자동")
    assert new == "5111011200"
    assert B.lookup("강원도", "춘천시", "효자동") == new                       # 날짜가 없으면 지금 이름으로
    assert B.lookup("강원도", "춘천시", "효자동", on="2026-12-20") == new
    assert B.lookup("강원도", "춘천시", "효자동", on="2023-06-11") == new       # 시작일 당일부터
    assert B.lookup("강원도", "춘천시", "효자동", on="2023-06-10") is None      # 개칭 전 날짜는 옛 이름 그대로라 표에 없다
    assert B.lookup("전라북도", "전주시 완산구", "전동3가", on="2026-01-01") == \
        B.lookup("전북특별자치도", "전주시 완산구", "전동3가")


def test_on_must_be_iso_date():
    with pytest.raises(ValueError):
        B.lookup("강원도", "춘천시", "효자동", on="20261220")


# --- 표 파일 ---

TABLE = os.path.join(bjd.EFILE_DIR, "법정동코드.json")


def _table():
    with open(TABLE, encoding="utf-8") as f:
        return json.load(f)


def test_table_source_and_counts_agree():
    t = _table()
    s = t["출처"]
    for k in ("이름", "URL", "파일명", "sha256", "받은날", "인코딩", "자료행", "존재행"):
        assert s[k], k
    assert len(s["sha256"]) == 64
    assert s["존재행"] == len(t["코드"])
    assert s["존재행"] < s["자료행"]
    assert os.path.getsize(TABLE) < 1_500_000


def test_table_codes_are_ten_digits_and_names_are_clean():
    t = _table()["코드"]
    assert list(t) == sorted(t)
    for code, name in t.items():
        assert len(code) == 10 and code.isdigit(), code
        assert name == " ".join(name.split()), (code, name)
    assert len(set(t.values())) == len(t)


def test_every_code_resolves_by_its_own_name():
    # 표의 모든 읍면동·리 코드가 자기 주소로 다시 찾아지는지. 가로 나뉜 이름과 한자 이름은 후보에 자기 코드가 들어 있으면 된다
    t = _table()["코드"]
    n = 0
    for code, name in t.items():
        parts = B.split(code)
        if not parts[2]:
            continue
        n += 1
        assert code in B.candidates(*parts), (code, name)
        if B.lookup(*parts) is not None:
            assert B.lookup(*parts) == code
    assert n == len([c for c in t if c[5:] != "00000"])     # 시도·시군구 행을 뺀 나머지 전부


# --- 원자료 가져오기 ---

HEADER = "법정동코드\t법정동명\t폐지여부"


def _raw(lines, enc="cp949", header=HEADER, eol="\r\n"):
    return (eol.join([header] + lines) + eol).encode(enc)


MINI = [
    "1100000000\t서울특별시\t존재",
    "1111000000\t서울특별시 종로구\t존재",
    "1111010100\t서울특별시 종로구 청운동\t존재",
    "1111010200\t서울특별시 종로구 신교동\t폐지",
    "4119200000\t경기도 부천시 원미구 \t존재",                 # 이름 끝에 공백이 붙은 행이 실제 자료에 있다
    "4119210100\t경기도 부천시 원미구 원미동\t존재",
    "2900000000\t광주광역시\t폐지",
]


def test_convert_keeps_only_existing_rows_and_cleans_names():
    out = import_bjd.convert(_raw(MINI), 인코딩="cp949")
    assert out["코드"] == {"1100000000": "서울특별시", "1111000000": "서울특별시 종로구",
                          "1111010100": "서울특별시 종로구 청운동", "4119200000": "경기도 부천시 원미구",
                          "4119210100": "경기도 부천시 원미구 원미동"}
    assert out["자료행"] == 7 and out["존재행"] == 5


def test_convert_is_independent_of_line_ending_style():
    a = import_bjd.convert(_raw(MINI), 인코딩="cp949")
    b = import_bjd.convert(_raw(MINI, eol="\n"), 인코딩="cp949")
    assert a == b
    assert a["sha256"] == b["sha256"]
    assert a["sha256"] == hashlib.sha256(_raw(MINI)).hexdigest()


@pytest.mark.parametrize("raw,msg", [
    (_raw(MINI, header="코드\t이름\t상태"), "머리글"),
    (_raw(["1100000000\t서울특별시"]), "3열"),
    (_raw(["110000000\t서울특별시\t존재"]), "10자리"),
    (_raw(["1100000000\t서울특별시\t현존"]), "폐지여부"),
    (_raw(["1100000000\t서울특별시\t존재", "1100000000\t서울특별시\t존재"]), "중복"),
    (_raw(["1100000000\t서울특별시\t존재", "1111010100\t서울특별시 종로구 청운동\t존재"]), "시군구"),
    (_raw(["1100000000\t서울특별시\t존재", "1111000000\t서울특별시 종로구\t존재",
           "1111010100\t부산광역시 종로구 청운동\t존재"]), "이름"),
    (_raw(["1100000000\t서울특별시\t폐지"]), "존재 행이 없"),
    (_raw(["1100000000\t서울특별시\t존재", "1111000000\t서울특별시 종로구\t존재",
           "1111010100\t서울특별시 종로구 청운동\t존재", "1111010200\t서울특별시 종로구 청운동\t존재"]), "같은 이름"),
])
def test_convert_rejects_malformed_input(raw, msg):
    with pytest.raises(import_bjd.SourceError) as e:
        import_bjd.convert(raw, 인코딩="cp949")
    assert msg in str(e.value)


def test_convert_rejects_wrong_encoding():
    with pytest.raises(import_bjd.SourceError) as e:
        import_bjd.convert(_raw(MINI, enc="cp949"), 인코딩="utf-8")
    assert "인코딩" in str(e.value)


def test_main_writes_table_and_checks_sha(tmp_path):
    src = tmp_path / "법정동코드 전체자료.txt"
    src.write_bytes(_raw(MINI))
    out = tmp_path / "법정동코드.json"
    sha = hashlib.sha256(_raw(MINI)).hexdigest()
    args = ["--입력", str(src), "--출력", str(out), "--받은날", "2026-10-11", "--sha256", sha]
    assert import_bjd.main(args) == 0
    t = json.loads(out.read_text(encoding="utf-8"))
    assert t["출처"]["파일명"] == "법정동코드 전체자료.txt"
    assert t["출처"]["sha256"] == sha and t["출처"]["받은날"] == "2026-10-11"
    assert t["출처"]["자료행"] == 7 and t["출처"]["존재행"] == 5
    assert list(t["코드"]) == sorted(t["코드"])
    # 같은 입력이면 같은 파일
    first = out.read_bytes()
    assert import_bjd.main(args) == 0
    assert out.read_bytes() == first
    # 기대한 해시와 다르면 쓰지 않는다
    out.unlink()
    assert import_bjd.main(args[:-1] + ["0" * 64]) == 1
    assert not out.exists()
