# -*- coding: utf-8 -*-
"""절차 점검(파일 방식) 시험 · 예시 자료. 가상 회사 새론기공(가상)의 매출채권 조서를 회계사가 손수 만든 양식으로 쓴다.

    python tests/make_procfile_sample.py <출력 폴더> [--defect]

출력 폴더에 「매출채권_조서.xlsx」 와 「00 받은자료/」(거래처별 채권명세 · 조회 발송회신 대장)를 만든다.
--defect 를 주면 결함 넷을 심는다.
  ① 조회: 표본 12곳 가운데 3곳이 미회신인데 대체 절차가 없고 감사프로그램에는 「예외 없음」 으로 적혀 있다
  ② 대손충당금: 1년 초과 구간의 설정률과 결론 칸이 비어 있다
  ③ 특수관계자 채권 절차 줄이 감사프로그램에 없다(명세에는 특수관계 거래처가 둘 있다)
  ④ 외화환산을 「N/A · 외화 채권 없음」 으로 두었는데 명세에 USD 거래처가 있다
실제 회사와 관계없는 지어낸 숫자다.
"""
from __future__ import annotations

import sys
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font

COMPANY = "새론기공(가상)"
WP = "매출채권_조서.xlsx"
RECEIVED = "00 받은자료"
PARTIES = [("대양산업", 412_500_000), ("미래정공", 286_000_000), ("한솔기전", 198_400_000), ("동해머티리얼", 154_000_000),
           ("서진테크", 132_700_000), ("청운엔지니어링", 97_300_000), ("새론홀딩스", 88_000_000), ("우리금형", 76_450_000),
           ("새론물류", 64_900_000), ("진성하이텍", 51_200_000), ("가람전자", 43_800_000), ("늘봄상사", 38_600_000),
           ("두레화학", 27_500_000), ("바른기계", 19_800_000), ("온누리철강", 12_350_000)]
RELATED = ("새론홀딩스", "새론물류")
PRIOR = 1_548_200_000


def _bold(ws, row: int) -> None:
    for c in ws[row]:
        c.font = Font(bold=True)


def build(out: Path, defect: bool = False) -> Path:
    out = Path(out)
    (out / RECEIVED).mkdir(parents=True, exist_ok=True)
    total = sum(a for _, a in PARTIES)
    fx = "미래정공" if defect else None                      # 결함 ④: 이 거래처가 USD
    confirm = PARTIES[:12]
    no_reply = {p for p, _ in confirm[-3:]} if defect else set()

    wb = Workbook()
    ws = wb.active
    ws.title = "감사프로그램"
    ws["A1"] = f"{COMPANY} 2025 기말감사 · 매출채권 감사프로그램"
    ws["A1"].font = Font(size=13, bold=True)
    ws["A2"] = "작성 김가을 · 검토"
    ws.append([])
    ws.append(["번호", "감사절차", "해당", "조서", "수행자", "수행 결과"])
    _bold(ws, 4)
    prog = [
        (1, "매출채권 총괄표를 만들어 시산표 · 전기 감사보고서 잔액과 맞추고 큰 증감의 원인을 적는다", "Y", "C10 총괄", "김가을",
         "시산표 · 전기 감사보고서 잔액과 일치. 증감은 4분기 매출 증가에 따른 것으로 확인"),
        (2, "거래처별 명세의 합계를 검산하고 원장과 맞춘다. 대변 잔액 · 장기 미회수 항목을 살핀다", "Y", "C20 명세", "김가을",
         "명세 합계가 총괄표와 일치. 대변 잔액 없음. 1년 초과 2곳은 충당금 조서에서 검토"),
        (3, "거래처에 조회서를 보내 회신을 장부 잔액과 맞추고 미회신 · 차이는 대체 절차를 한다", "Y", "C30 조회", "김가을",
         "금액 상위 12곳 발송. 회신 모두 일치. 예외 없음"),
        (4, "매출채권이 아닌 채권이 섞였는지, 장단기 구분이 맞는지 본다", "Y", "C20 명세", "김가을",
         "비매출 채권 없음. 회수 약정이 1년을 넘는 채권 없음"),
        (5, "연령분석으로 회수가 의심되는 채권을 가려 대손충당금 설정이 적정한지 본다", "Y", "C50 충당금", "김가을",
         "연령구간별 설정률을 과거 대손 경험과 견줌. 장부 충당금과 차이 없음"),
        (6, "결산일 전후 매출이 인도 시점에 맞는 기간에 기록됐는지 검사한다", "Y", "C60 기간귀속", "김가을",
         "결산일 전후 10건의 출고일과 매출 인식일이 같은 기간. 예외 없음"),
        (7, "외화 매출채권의 기말 환산을 다시 계산한다", "N/A", "", "", "외화 채권 없음" if defect else "명세의 통화 열이 모두 KRW 이고 수출 매출이 없어 외화 채권이 없음"),
        (8, "특수관계자 채권을 가려 금액을 확정하고 특수관계자 조서 · 주석과 잇는다", "Y", "C20 명세", "김가을",
         "특수관계 거래처 2곳의 잔액을 명세에서 확정하고 특수관계자 조서에 넘김"),
        (9, "확정한 금액을 주석과 맞추고 담보 제공 등 공시사항을 확인한다", "Y", "C90 주석", "김가을",
         "주석 금액이 확정 금액과 일치. 담보 제공 채권 없음(차입 약정서 확인)"),
    ]
    for row in prog:
        if defect and row[0] == 8:                           # 결함 ③
            continue
        ws.append(list(row))
    ws.append([])
    ws.append([])
    ws.append([None, "결론: 매출채권은 중요성의 관점에서 적정하게 표시되어 있음"])

    c10 = wb.create_sheet("C10 총괄")
    c10.append(["계정", "전기말(감사보고서)", "당기말(장부)", "증감", "시산표", "차이", "증감 원인"])
    _bold(c10, 1)
    c10.append(["매출채권", PRIOR, total, total - PRIOR, total, 0, "4분기 대양산업 · 미래정공 납품 증가"])
    c10.append(["대손충당금", -21_400_000, -27_377_500, -5_977_500, -27_377_500, 0, "1년 초과 채권 증가"])
    c10.append([])
    c10.append(["결론", "시산표 · 전기 감사보고서와 일치함"])

    c20 = wb.create_sheet("C20 명세")
    c20.append(["거래처", "통화", "잔액(원)", "특수관계", "1년 초과", "비고"])
    _bold(c20, 1)
    for name, amt in PARTIES:
        c20.append([name, "USD" if name == fx else "KRW", amt, "예" if name in RELATED else "", "예" if name in ("바른기계", "온누리철강") else "",
                    "원장 잔액과 일치"])
    c20.append(["합계", None, total, None, None, "총괄표와 일치"])
    c20.append([])
    c20.append(["검산", "거래처별 잔액 합계를 다시 더해 원장 · 총괄표와 맞춤. 대변 잔액 없음. 비매출 채권 없음"])
    c20.append(["특수관계자", "새론홀딩스 · 새론물류 잔액을 특수관계자 조서에 넘김"])
    if True:                                                 # 결함 넷 말고는 두 판이 같다
        c20.append(["장단기 구분", "거래처 15곳의 공급계약서 결제 조건을 봄. 모두 인도 뒤 90일 안 결제라 장기로 나눌 채권 없음. "
                    "1년 초과 2곳은 연체이고 회수 약정을 다시 맺지 않아 유동으로 둠"])

    c30 = wb.create_sheet("C30 조회")
    c30.append(["거래처", "장부 금액", "발송일", "회신일", "회신 금액", "차이", "대체 절차", "결론"])
    _bold(c30, 1)
    for name, amt in confirm:
        if name in no_reply:                                 # 결함 ①
            c30.append([name, amt, "2026-01-08", None, None, None, None, None])
        else:
            c30.append([name, amt, "2026-01-08", "2026-01-21", amt, 0, None, "일치"])
    c30.append([])
    c30.append(["표본 선정", "금액 상위 12곳(잔액의 96%). 나머지 3곳은 금액이 작아 뽑지 않음"])

    c50 = wb.create_sheet("C50 충당금")
    c50.append(["연령구간", "잔액", "설정률", "충당금(계산)", "장부 충당금", "차이"])
    _bold(c50, 1)
    aging = [("3개월 이내", 1_250_900_000, 0.005), ("3 ~ 6개월", 286_000_000, 0.02), ("6개월 ~ 1년", 134_450_000, 0.05),
             ("1년 초과", 32_150_000, None if defect else 0.27)]     # 결함 ②
    for name, bal, rate in aging:
        c50.append([name, bal, rate, round(bal * rate) if rate is not None else None, None, None])
    calc = sum(round(b * r) for _, b, r in aging if r is not None)
    c50.append(["합계", sum(b for _, b, _ in aging), None, calc, 27_377_500, calc - 27_377_500 if not defect else None])
    c50.append([])
    c50.append(["설정률 근거", "최근 3개년 구간별 대손 경험률. 1년 초과 2곳은 회수 약정서를 받아 봄"])
    c50.append(["결론", None if defect else "장부 충당금과 차이 없음. 설정이 적정함"])

    c60 = wb.create_sheet("C60 기간귀속")
    c60.append(["전표번호", "매출 인식일", "출고일", "거래처", "금액", "같은 기간"])
    _bold(c60, 1)
    days = [("2025-12-26", "2025-12-26"), ("2025-12-29", "2025-12-29"), ("2025-12-30", "2025-12-30"), ("2025-12-30", "2025-12-29"),
            ("2025-12-31", "2025-12-31"), ("2026-01-02", "2026-01-02"), ("2026-01-05", "2026-01-05"), ("2026-01-05", "2026-01-03"),
            ("2026-01-06", "2026-01-06"), ("2026-01-07", "2026-01-07")]
    for i, (rec, ship) in enumerate(days, 1):
        c60.append([f"S-{2400 + i}", rec, ship, PARTIES[i % 6][0], 18_500_000 + i * 1_250_000, "예"])
    c60.append([])
    c60.append(["결론", "10건 모두 출고일과 매출 인식일이 같은 사업연도. 예외 없음"])

    c90 = wb.create_sheet("C90 주석")
    c90.append(["항목", "주석 금액", "확정 금액", "차이"])
    _bold(c90, 1)
    c90.append(["매출채권", total, total, 0])
    c90.append(["대손충당금", -27_377_500, -27_377_500, 0])
    c90.append(["특수관계자 채권", 152_900_000, 152_900_000, 0])
    c90.append([])
    c90.append(["담보 제공", "차입 약정서에 매출채권 담보 조항 없음"])
    c90.append(["결론", "주석 금액이 확정 금액과 일치함"])
    wb.save(out / WP)

    rb = Workbook()
    r1 = rb.active
    r1.title = "채권명세"
    r1.append(["거래처", "통화", "잔액(원)", "특수관계"])
    for name, amt in PARTIES:
        r1.append([name, "USD" if name == fx else "KRW", amt, "예" if name in RELATED else ""])
    rb.save(out / RECEIVED / "거래처별_채권명세.xlsx")
    cb = Workbook()
    c1 = cb.active
    c1.title = "발송회신"
    c1.append(["거래처", "발송일", "회신일", "회신 금액"])
    for name, amt in confirm:
        c1.append([name, "2026-01-08", None if name in no_reply else "2026-01-21", None if name in no_reply else amt])
    cb.save(out / RECEIVED / "조회_발송회신대장.xlsx")
    return out / WP


LAYOUT = {"area": "4000C", "tables": [{"sheet": "감사프로그램", "head_row": 4, "first_row": 5, "last_row": 13, "step": "B", "applies": "C",
                                       "ref": "D", "who": "E", "result": "F", "excluded": {"16": "결론 줄"}}]}


def layout(defect: bool = False) -> dict:
    last = 12 if defect else 13
    t = dict(LAYOUT["tables"][0], last_row=last, excluded={str(last + 3): "결론 줄"})
    return {"area": "4000C", "tables": [t]}


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 1:
        print(__doc__)
        sys.exit(2)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    print(build(Path(args[0]), defect="--defect" in sys.argv))
