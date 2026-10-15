# -*- coding: utf-8 -*-
"""채권·채무 거래처코드 빈칸은 확인이고, 마스터에 없는 코드는 반려다(2026-10-16 대표 지시).

가능한 한 채우는 것이 목표지만 회사에 따라 못 채우는 라벨이 있다. 빈칸이어도 더존 업로드는
되고 거래처별 잔액만 안 선다. 반대로 적은 코드가 마스터에 없으면 더존이 파일 전체를 반려한다.
"""
import openpyxl

from test_verification_integrity import 돌리기, 업로드쓰기, 성한_매출

외상매입_빈코드 = [6, 15, 3, 251, "외상매입금", None, "다수(매입처)", "상품매입대금 결제", 5000, None]
외상매입_코드 = [6, 15, 3, 251, "외상매입금", "00999", "없는거래처", "상품매입대금 결제", 5000, None]
보통예금 = [6, 15, 4, 103, "보통예금", None, "다수(매입처)", "상품매입대금 결제", None, 5000]


def 마스터쓰기(d, 코드들):
    wb = openpyxl.Workbook(); ws = wb.active
    ws.append(["거래처코드", "거래처명", "구분", "사업자(주민)등록번호", "비고"])
    for c in 코드들:
        ws.append([c, f"거래처{c}", "매입처", None, None])
    p = d / "거래처마스터.xlsx"
    wb.save(p)
    return str(p)


def test_채권채무_거래처코드_빈칸은_반려가_아니라_확인이다(tmp_path):
    # profile_nuri 는 거래처별칭을 둔 프로파일이다. 예전에는 이런 프로파일에서 빈칸이 FAIL 이었다
    업로드쓰기(tmp_path, [외상매입_빈코드, 보통예금], [성한_매출])
    code, out = 돌리기("verify_upload.py", [str(tmp_path), "2026-06", "profile_nuri"])
    assert code == 0, out
    assert "[확인] 채권채무 계정 [251] 의 거래처 '다수(매입처)' 에 거래처코드가 없다" in out, out
    assert "채권채무 거래처코드 0/1" in out, out


def test_마스터에_없는_거래처코드는_반려한다(tmp_path):
    업로드쓰기(tmp_path, [외상매입_코드, 보통예금], [성한_매출])
    master = 마스터쓰기(tmp_path, ["00101", "00102"])
    code, out = 돌리기("verify_upload.py", [str(tmp_path), "2026-06", "profile_nuri", master])
    assert code == 1 and "거래처코드=00999" in out and "거래처마스터에 없다" in out, out
