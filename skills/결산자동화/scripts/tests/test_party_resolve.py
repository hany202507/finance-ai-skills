# -*- coding: utf-8 -*-
"""거래처 해소 — 더존 업로드 거래처코드·사업자번호가 비어 나가지 않는지.

세션2 실습에서 일반전표 채권채무 35행 중 1행만 거래처코드가 차고, 매입매출 11열
사업자번호가 플랫폼 6행에서 통째로 비었다. 원천에는 둘 다 있었다. 그 회귀를 막는다.
"""
import os, sys, types
import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from close_engine import Engine, _norm


def _eng(master, P):
    """_load 를 타지 않고 리졸버만 세운다. raw 파일 없이 규칙을 검사한다."""
    e = Engine.__new__(Engine)
    e.P = P
    e.master = {}
    e._mnorm = {}
    e.party_miss = {}
    for 상호, (코드, biz) in master.items():
        e.master[상호] = (코드, biz)
        e._mnorm.setdefault(_norm(상호), (코드, biz))
    return e


MASTER = {
    "쿠팡(주)":           ("00135", 7374756724),
    "네이버파이낸셜(주)":    ("00136", 8069220720),
    "네이버(주) 검색광고":   ("00111", 5785050521),
    "씨제이올리브영(주)":    ("00138", 1713059368),
    "기업은행":            ("00001", None),
}


def P(별칭=None, 집합=None):
    m = types.ModuleType("p")
    if 별칭 is not None: m.거래처별칭 = 별칭
    if 집합 is not None: m.집합거래처 = 집합
    return m


def test_별칭이_거래처코드와_사업자번호를_같이_가져온다():
    e = _eng(MASTER, P(별칭={"쿠팡": "쿠팡(주)"}))
    assert e.resolve_party("쿠팡", 108) == ("00135", 7374756724)
    assert e.party_code("쿠팡") == "00135"
    assert e.party_biz("쿠팡") == 7374756724
    assert not e.party_miss


def test_모호한_부분일치는_찍지_않고_미해소로_남긴다():
    """'네이버' 는 네이버파이낸셜(플랫폼)과 네이버 검색광고(광고) 둘 다에 걸린다."""
    e = _eng(MASTER, P())
    assert e.resolve_party("네이버", 108) == ("", 0)
    assert "네이버" in e.party_miss


def test_별칭이_있으면_모호함이_사라진다():
    e = _eng(MASTER, P(별칭={"네이버": "네이버파이낸셜(주)"}))
    assert e.resolve_party("네이버", 108) == ("00136", 8069220720)
    assert not e.party_miss


def test_법인격_표기만_다르면_붙는다():
    e = _eng(MASTER, P())
    assert e.resolve_party("쿠팡(주)", 108)[0] == "00135"   # 완전일치
    assert e.resolve_party("쿠팡 (주)", 108)[0] == "00135"  # 공백·법인격 깎고 일치
    assert e.resolve_party("쿠팡", 108)[0] == "00135"       # 부분일치 후보가 하나뿐
    assert not e.party_miss


def test_후보가_하나뿐인_부분일치는_붙이고_둘이면_안_붙인다():
    """'올리브영' 은 씨제이올리브영(주) 하나뿐이라 별칭 없이도 붙는다."""
    e = _eng(MASTER, P())
    assert e.resolve_party("올리브영", 108) == ("00138", 1713059368)
    # 후보가 둘이 되는 순간 빈칸 + 미해소로 돌아선다
    e2 = _eng({**MASTER, "올리브영물류(주)": ("00999", 1111111111)}, P())
    assert e2.resolve_party("올리브영", 108) == ("", 0)
    assert "올리브영" in e2.party_miss


def test_집합거래처는_빈칸이_정상이고_미해소가_아니다():
    e = _eng(MASTER, P(집합={"임직원", "해외바이어"}))
    assert e.resolve_party("임직원", 254) == ("", 0)
    assert e.resolve_party("해외바이어", 108) == ("", 0)
    assert not e.party_miss, "선언한 빈칸은 누락이 아니다"


def test_별칭이_마스터에_없으면_미해소로_드러난다():
    """별칭 오타나 거래처 미등록을 조용히 넘기지 않는다."""
    e = _eng(MASTER, P(별칭={"쿠팡": "쿠팡주식회사오타"}))
    assert e.resolve_party("쿠팡", 108) == ("", 0)
    assert any("쿠팡" in k and "마스터 없음" in k for k in e.party_miss)


def test_사업자번호가_없는_마스터행은_0으로_온다():
    e = _eng(MASTER, P())
    assert e.resolve_party("기업은행", 260) == ("00001", None)
    assert e.party_biz("기업은행") == 0


def test_빈_라벨은_조회하지_않는다():
    e = _eng(MASTER, P())
    assert e.resolve_party("", 108) == ("", 0)
    assert e.resolve_party(None, 108) == ("", 0)
    assert not e.party_miss


def test_norm_은_법인격만_깎고_글자는_남긴다():
    assert _norm("네이버파이낸셜(주)") == "네이버파이낸셜"
    assert _norm("(주)지마켓") == "지마켓"
    assert _norm("틱톡샵코리아(유)") == "틱톡샵코리아"
    assert _norm("네이버(주) 검색광고") == "네이버검색광고"
    # 깎은 뒤에도 플랫폼과 광고가 구분돼야 한다
    assert _norm("네이버파이낸셜(주)") != _norm("네이버(주) 검색광고")
