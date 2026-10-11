# -*- coding: utf-8 -*-
"""전자신고 파일에 쓸 수 있는 글자인지 보는 검사. 생성기(efile.py)와 신고인 검사(filing.py)가 이 함수를 함께 쓴다.

전자신고 파일은 CP949 이고 한글은 KS X 1001 완성형 2바이트만 받는다(규격서 p15). CP949 는 「똠」 같은 확장 영역 글자도
인코딩해 주지만 전자신고 파일에서는 받지 않는다.

검증기(efile_check.py)는 이 모듈을 가져오지 않고 같은 규칙을 자기 파일에 따로 적는다(_ksx_problem). 생성기와 같은
함수를 쓰면 그 함수가 틀렸을 때 검증기도 같이 틀리기 때문이다. 두 곳의 판정이 같은지는 시험이 본다.
"""


def ksx_bytes_ok(raw, symbols=True):
    """CP949 바이트가 ASCII(0x20~0x7E)와 KS X 1001 완성형 2바이트(한글 첫 바이트 0xB0~0xC8, 둘째 0xA1~0xFE)만인지.

    symbols 가 참이면 기호 행(첫 바이트 0xA1~0xAC, 가운뎃점 등)도 받는다.
    """
    i, n = 0, len(raw)
    while i < n:
        b = raw[i]
        if 0x20 <= b <= 0x7E:
            i += 1
            continue
        if i + 1 >= n or not 0xA1 <= raw[i + 1] <= 0xFE:
            return False
        if not (0xB0 <= b <= 0xC8 or (symbols and 0xA1 <= b <= 0xAC)):
            return False
        i += 2
    return True


def ksx1001_ok(text, symbols=False):
    """글자를 CP949 로 쓸 때 KS X 1001 완성형과 ASCII 만 쓰는지. CP949 로 쓸 수 없는 글자가 있어도 거짓이다."""
    try:
        raw = text.encode("cp949")
    except UnicodeEncodeError:
        return False
    return ksx_bytes_ok(raw, symbols)
