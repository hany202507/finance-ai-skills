# -*- coding: utf-8 -*-
"""급여대장 엑셀. 합계와 차인지급액은 수식으로 남긴다.

시트 넷.
  인사카드    누가 어떤 조건인가
  과세표준    같은 급여가 제도마다 어떻게 갈리는지. 이 시트가 이 스킬의 전부다
  급여대장    사람이 행. 합계는 SUM, 실지급액은 지급−공제
  확인사항    사람이 정할 것
"""
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

얇 = Side(style="thin", color="BBBBBB")
테 = Border(left=얇, right=얇, top=얇, bottom=얇)
머리색 = PatternFill("solid", fgColor="EEF2F7")
경고색 = PatternFill("solid", fgColor="FFF3CD")
돈 = "#,##0"

지급열 = [("BASE", "기본급"), ("OT", "연장수당"), ("MEAL", "식대"),
          ("CAR", "자가운전보조금"), ("CHILD", "육아수당"), ("OVERSEA", "국외근로수당"),
          ("BONUS", "상여금"), ("HOURLY", "일용급여"), ("SERVICE", "용역대가")]
# 받은 사람이 있을 때만 열을 더한다. 이름은 신고서 단계(집계.py)가 지급항목으로 읽는 이름이다
덧붙일열 = [("RESEARCH", "연구보조비"), ("BIRTH", "출산지원금"), ("PROD_OT", "생산직 연장수당"),
            ("GROUP_INS", "단체보장성보험료")]
제도들 = ("소득세", "국민연금", "건강보험", "고용보험")


def _머리(ws, r, 값들, 폭=None):
    for i, v in enumerate(값들, start=1):
        c = ws.cell(r, i, v)
        c.font = Font(bold=True)
        c.fill = 머리색
        c.border = 테
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    if 폭:
        for i, w in enumerate(폭, start=1):
            ws.column_dimensions[get_column_letter(i)].width = w


def _지급열(행들):
    """대장에 둘 지급 열. 기본 열에 없는 항목이 빠지면 총지급액 수식에서 조용히 사라진다."""
    있는 = {k for x in 행들 for k, v in x.지급.items() if v}
    열 = list(지급열) + [(k, n) for k, n in 덧붙일열 if k in 있는]
    아는 = {k for k, _ in 열}
    return 열 + [(k, k) for k in sorted(있는 - 아는)]


def build(경로, 회사, 귀속연월, 행들, 카드들, 확인사항=()):
    wb = Workbook()
    지급열 = _지급열(행들)

    # ── 인사카드 ────────────────────────────────────────
    ws = wb.active
    ws.title = "인사카드"
    열 = ["사번", "성명", "소득구분", "입사일", "퇴사일", "부양가족수",
          "6세이하자녀수", "8~20세자녀수", "국민연금", "건강보험", "고용보험", "비고"]
    _머리(ws, 1, 열, [10, 10, 9, 12, 12, 11, 13, 13, 9, 9, 9, 34])
    for i, k in enumerate(카드들, start=2):
        값 = [k["사번"], k["성명"], k["소득구분"], k["입사일"], k["퇴사일"],
              k["부양가족수"], k["6세이하자녀수"], k["8_20세자녀수"],
              "Y" if k["국민연금가입"] else "N", "Y" if k["건강보험가입"] else "N",
              "Y" if k["고용보험가입"] else "N", k.get("비고", "")]
        for j, v in enumerate(값, start=1):
            ws.cell(i, j, v).border = 테

    # ── 과세표준 ───────────────────────────────────────
    ws2 = wb.create_sheet("과세표준")
    ws2.cell(1, 1, "같은 급여가 제도마다 다르게 잡힙니다").font = Font(bold=True, size=13)
    ws2.cell(2, 1, "소득세 비과세와 4대보험 산입 여부가 같지 않습니다. "
                   "국외근로수당이 그 자리입니다")
    _머리(ws2, 4, ["사번", "성명", "총지급액"] + [f"{p} 과세표준" for p in 제도들]
          + [f"{p} 비과세" for p in 제도들], [10, 10, 13] + [15] * 8)
    r = 5
    for x in 행들:
        ws2.cell(r, 1, x.사번).border = 테
        ws2.cell(r, 2, x.성명).border = 테
        c = ws2.cell(r, 3, x.총지급액); c.number_format = 돈; c.border = 테
        for j, p in enumerate(제도들):
            c = ws2.cell(r, 4 + j, x.표준.get(p, 0)); c.number_format = 돈; c.border = 테
            c2 = ws2.cell(r, 8 + j, x.비과세.get(p, 0)); c2.number_format = 돈; c2.border = 테
        갈림 = len({x.표준.get(p, 0) for p in 제도들}) > 1
        if 갈림:
            for j in range(4, 8):
                ws2.cell(r, j).fill = 경고색
        r += 1
    ws2.cell(r + 1, 1, "노란 칸은 제도별로 과세표준이 갈린 사람입니다. "
                       "한 벌로 계산하면 여기서 틀립니다")

    # ── 급여대장 ───────────────────────────────────────
    ws3 = wb.create_sheet("급여대장")
    ws3.cell(1, 1, f"{회사} · {귀속연월} 급여대장").font = Font(bold=True, size=13)
    지급명 = [n for _, n in 지급열]
    공제명 = ["국민연금", "건강보험", "장기요양보험", "고용보험", "소득세", "지방소득세"]
    열3 = ["사번", "성명", "구분", "소득코드"] + 지급명 + ["총지급액"] + 공제명 + ["공제합계", "실지급액"]
    _머리(ws3, 3, 열3, [10, 10, 8, 10] + [13] * len(지급명) + [14] + [13] * 6 + [13, 14])
    첫 = 4
    for i, x in enumerate(행들):
        rr = 첫 + i
        ws3.cell(rr, 1, x.사번).border = 테
        ws3.cell(rr, 2, x.성명).border = 테
        ws3.cell(rr, 3, x.소득구분).border = 테
        ws3.cell(rr, 4, x.소득코드).border = 테
        for j, (코드, _) in enumerate(지급열):
            c = ws3.cell(rr, 5 + j, x.지급.get(코드, 0)); c.number_format = 돈; c.border = 테
        총열 = 5 + len(지급열)
        a, b = get_column_letter(5), get_column_letter(총열 - 1)
        c = ws3.cell(rr, 총열, f"=SUM({a}{rr}:{b}{rr})"); c.number_format = 돈; c.border = 테
        값들 = [x.국민연금, x.건강보험, x.장기요양보험, x.고용보험, x.소득세, x.지방소득세]
        for j, v in enumerate(값들):
            c = ws3.cell(rr, 총열 + 1 + j, v); c.number_format = 돈; c.border = 테
        공1, 공2 = get_column_letter(총열 + 1), get_column_letter(총열 + 6)
        c = ws3.cell(rr, 총열 + 7, f"=SUM({공1}{rr}:{공2}{rr})")
        c.number_format = 돈; c.border = 테
        총L, 공L = get_column_letter(총열), get_column_letter(총열 + 7)
        c = ws3.cell(rr, 총열 + 8, f"={총L}{rr}-{공L}{rr}")
        c.number_format = 돈; c.border = 테; c.font = Font(bold=True)
    끝 = 첫 + len(행들) - 1
    합 = 끝 + 1
    ws3.cell(합, 2, "합계").font = Font(bold=True)
    for j in range(5, len(열3) + 1):
        L = get_column_letter(j)
        c = ws3.cell(합, j, f"=SUM({L}{첫}:{L}{끝})")
        c.number_format = 돈; c.font = Font(bold=True); c.border = 테
    ws3.cell(합 + 2, 1, "지방소득세는 사람마다 절사한 뒤 더합니다. "
                        "소득세 합계에 10%를 곱하면 사람 수만큼 어긋납니다")

    # ── 확인사항 ───────────────────────────────────────
    ws4 = wb.create_sheet("확인사항")
    _머리(ws4, 1, ["항목", "왜 확인해야 하나", "정한 값"], (28, 62, 30))
    for i, 줄 in enumerate(확인사항, start=2):
        항목, 이유 = 줄[0], 줄[1]
        정한값 = 줄[2] if len(줄) > 2 else ""
        ws4.cell(i, 1, 항목).border = 테
        ws4.cell(i, 2, 이유).border = 테
        ws4.cell(i, 3, 정한값).border = 테
        for j in (2, 3):
            ws4.cell(i, j).alignment = Alignment(wrap_text=True, vertical="top")
        if not 정한값:
            ws4.cell(i, 3).fill = 경고색

    wb.save(경로)
    return 경로
