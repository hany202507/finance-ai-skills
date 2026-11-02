# -*- coding: utf-8 -*-
"""산출한 집계표를 기준 파일(전월 확정본·정답본)과 셀 단위로 맞춰 본다.

숫자가 맞는지 눈으로 훑는 것과, 331개 셀을 전부 대 보는 것은 다른 일이다.
엔진을 고칠 때마다 이걸 돌리면 「숫자는 그대로 두고 구조만 고쳤다」를 증명할 수 있다.

세 층으로 나눠 본다. 층마다 틀렸을 때의 무게가 다르기 때문이다.
  금액   계산된 숫자가 다르다            → 실패. 신고가 틀린다
  구조   행·코드·항목 배치가 다르다      → 실패. 서식이 틀린다
  표기   수식 글자나 라벨만 다르다        → 알림. 값이 같으면 고친 자국일 수 있다
"""
import sys
from pathlib import Path

import openpyxl
from openpyxl.utils import get_column_letter as CL

금액시트 = ("지급내역", "집계", "신고서")


def _열(ws, r, c):
    return ws.cell(r, c).value


def 맞춰보기(산출, 기준):
    a수 = openpyxl.load_workbook(기준); b수 = openpyxl.load_workbook(산출)
    a값 = openpyxl.load_workbook(기준, data_only=True)
    b값 = openpyxl.load_workbook(산출, data_only=True)
    금액, 구조, 표기 = [], [], []

    없는시트 = [n for n in a수.sheetnames if n not in b수.sheetnames]
    if 없는시트:
        구조.append(f"시트 없음: {', '.join(없는시트)}")

    for 이름 in a수.sheetnames:
        if 이름 not in b수.sheetnames:
            continue
        af, bf, av, bv = a수[이름], b수[이름], a값[이름], b값[이름]
        R = max(af.max_row, bf.max_row); C = max(af.max_column, bf.max_column)
        for r in range(1, R + 1):
            for c in range(1, C + 1):
                칸 = f"{이름}!{CL(c)}{r}"
                x, y = _열(af, r, c), _열(bf, r, c)
                if x == y:
                    continue
                xv, yv = _열(av, r, c), _열(bv, r, c)
                숫자 = isinstance(xv, (int, float)) or isinstance(yv, (int, float))
                if 숫자:
                    if (xv or 0) != (yv or 0):
                        금액.append(f"{칸}  기준 {xv} / 산출 {yv}")
                    elif 이름 in 금액시트:
                        표기.append(f"{칸}  수식만 다름 (값 {yv} 동일)\n      기준 {x}\n      산출 {y}")
                elif 이름 == "확인사항":
                    continue                      # 확인사항은 아래에서 항목 단위로 본다
                else:
                    (구조 if 이름 in 금액시트 and c <= 3 else 표기).append(
                        f"{칸}  기준 {x!r} / 산출 {y!r}")

    # 확인사항은 사람이 적는 판단 기록이라 글자가 같을 수 없다. 항목이 빠졌는지만 본다
    확인 = []
    if "확인사항" in a수.sheetnames and "확인사항" in b수.sheetnames:
        뽑기 = lambda ws: {str(ws.cell(r, 1).value).strip(): str(ws.cell(r, 3).value or "").strip()
                           for r in range(2, ws.max_row + 1) if ws.cell(r, 1).value}
        기 , 산 = 뽑기(a수["확인사항"]), 뽑기(b수["확인사항"])
        for 항목 in 기:
            if 항목 not in 산:
                확인.append(f"빠진 항목: 「{항목}」 (기준의 정한 값: {기[항목] or '빈칸'})")
            elif 기[항목] and not 산[항목]:
                확인.append(f"「{항목}」 기준은 정해져 있는데 산출은 빈칸")
        더한것 = [k for k in 산 if k not in 기]
        if 더한것:
            확인.append(f"기준에 없는 항목 {len(더한것)}건 추가: {', '.join(더한것)}")
    return 금액, 구조, 표기, 확인


def 출력(산출, 기준):
    금액, 구조, 표기, 확인 = 맞춰보기(산출, 기준)
    print(f"기준 {Path(기준).name}  ←→  산출 {Path(산출).name}")
    for 제목, 목록, 무게 in (("금액", 금액, "실패"), ("구조", 구조, "실패"),
                             ("표기", 표기, "알림"), ("확인사항", 확인, "알림")):
        머리 = "OK " if not 목록 else ("✗ " if 무게 == "실패" else "· ")
        print(f"\n{머리}{제목} — {'이상 없음' if not 목록 else f'{len(목록)}건 ({무게})'}")
        for x in 목록[:40]:
            print("    ", x)
        if len(목록) > 40:
            print(f"     ... 외 {len(목록)-40}건")
    나쁨 = bool(금액 or 구조)
    print("\n판정:", "불일치 — 금액·구조가 다릅니다" if 나쁨 else "일치 — 금액과 구조가 같습니다")
    return 0 if not 나쁨 else 1


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("사용: python -m 대조 <산출.xlsx> <기준.xlsx>"); sys.exit(2)
    sys.exit(출력(sys.argv[1], sys.argv[2]))
