"""조서 엑셀 공통 서식(2026-11-03, 설계 문서).

모든 감사 조서 엑셀(공통 모듈 wp.Book, WTB 양식, DSD 엑셀, 점검표 · 종결 · 세팅)이 글꼴 · 색 · 칠 · 테두리 · 숫자 형식을 여기서만 가져온다.
요청(11-03): 「각 조서의 기본 포맷, 폰트, 컬러 통일성 갖추고 이건 매번 고정적으로 나오게」.

  font(**k)          맑은 고딕 글꼴(같은 인자는 하나만 만든다)
  finish(wb)         저장 직전. 값이 있는 칸 가운데 맑은 고딕이 아닌 글꼴을 맑은 고딕으로 바꾼다(크기 · 굵기 · 색은 둔다). 바꾼 칸 수
  lint(path)         저장된 엑셀에서 맑은 고딕이 아닌 글꼴과 팔레트에 없는 글자 · 칠 색. 시험이 만든 조서마다 0건이어야 한다

칸의 뜻(범례):
  흰 칸      엔진 값 · 수식. 숨김 `_검산` 시트가 엔진 기대값과 맞대므로 검토자가 다시 계산하지 않는다
  연보라     AI 작성(확인 전). 「AI 작성」 시트에서 O · X
  노랑       감사인 기입란
  분홍       엔진이 짚은 예외
"""
from __future__ import annotations

import functools
from pathlib import Path

from openpyxl.styles import Border, Font, PatternFill, Side

FONT = "맑은 고딕"
SIZE_TITLE, SIZE_SECTION, SIZE_BODY, SIZE_NOTE = 14, 11, 10, 9

# 글자 색
NAVY = "1B2A4A"          # 제목 · 절 제목 · 머리줄 칠 · 링크
INK = "1A1C19"           # 본문
MUTED = "6B7167"         # 설명 · 라벨
RED = "B3261E"           # 엔진이 짚은 예외 · FALSE
GREEN = "1E7B34"         # 맞음
WHITE = "FFFFFF"         # 머리줄 글자 · 숨긴 열쇠 글자
AI_INK = "26215C"        # AI 작성 칸 글자
AI_LINE = "534AB7"       # AI 작성 칸 왼쪽 선
BORDER = "DFE5DB"        # 칸 테두리

# 칠
FILL_HEAD = PatternFill("solid", fgColor=NAVY)       # 머리줄
FILL_IN = PatternFill("solid", fgColor="FFF2CC")     # 감사인 기입란
FILL_FLAG = PatternFill("solid", fgColor="F8E1E5")   # 엔진이 짚은 예외
FILL_SUB = PatternFill("solid", fgColor="F1F6EF")    # 소계 · 합계 줄
FILL_AI = PatternFill("solid", fgColor="EEEDFE")     # AI 작성(확인 전)
FILL_ASK = PatternFill("solid", fgColor="F8CBAD")    # 결과 상태: 확인
FILL_MINOR = PatternFill("solid", fgColor="FFE699")  # 결과 상태: 단수 차이
FILL_NONE = PatternFill("solid", fgColor="E7E6E6")   # 결과 상태: 걸린 검증 없음 · 회색 칸
FILL_WP = PatternFill("solid", fgColor="DDEBF7")     # 결과 상태: 조서와 맞출 숫자

THIN = Side(style="thin", color=BORDER)
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
AI_BOX = Border(left=Side(style="thick", color=AI_LINE), right=THIN, top=THIN, bottom=THIN)

WON = '#,##0;[Red]-#,##0;"-"'
PCT = '0.0%;[Red]-0.0%;"-"'

PALETTE_FONT = {NAVY, INK, MUTED, RED, GREEN, WHITE, AI_INK, "000000"}
PALETTE_FILL = {f.fgColor.rgb[-6:] for f in (FILL_HEAD, FILL_IN, FILL_FLAG, FILL_SUB, FILL_AI, FILL_ASK, FILL_MINOR, FILL_NONE, FILL_WP)} | {WHITE}

LEGEND = ("칸의 뜻: 흰 칸은 엔진 값 · 수식(숨김 _검산 시트가 맞대므로 다시 계산하지 않아도 됨) · 연보라는 AI 작성(확인 전, 「AI 작성」 시트에서 O · X) · "
          "노랑은 감사인 기입란 · 분홍은 엔진이 짚은 예외")


@functools.lru_cache(maxsize=None)
def _font(size, items: tuple) -> Font:
    return Font(name=FONT, size=size, **dict(items))


def font(**k) -> Font:
    """같은 인자의 글꼴은 하나만 만들어 함께 쓴다. 칸마다 새로 만들면 큰 엑셀에서 수 초가 든다(2026-10-22 DSD푸팅 실행 시간).
    돌려받은 글꼴을 고치지 말고 새로 부른다."""
    size = k.pop("size", SIZE_BODY)
    try:
        return _font(size, tuple(sorted(k.items())))
    except TypeError:                                 # 목록처럼 해시할 수 없는 값
        return Font(name=FONT, size=size, **k)


def link(cell, location: str) -> None:
    """책 안의 칸으로 가는 링크(「'시트'!B7」). 글자는 남색 밑줄."""
    from openpyxl.worksheet.hyperlink import Hyperlink
    cell.hyperlink = Hyperlink(ref=cell.coordinate, location=location)
    cell.font = font(color=NAVY, underline="single")


def _rgb(color) -> str | None:
    """openpyxl 색에서 RRGGBB. 테마 · 색 없음이면 None."""
    if color is None or getattr(color, "type", "rgb") != "rgb":
        return None
    v = color.rgb
    if not isinstance(v, str) or len(v) < 6 or v.upper() == "00000000":     # 「00000000」 은 openpyxl 의 빈 색
        return None
    return v[-6:].upper()


def finish(wb) -> int:
    """값이 있는 칸 가운데 맑은 고딕이 아닌 칸을 맑은 고딕으로 바꾼다. 엑셀 기본(Calibri 11, 꾸밈 없음)이면 본문 크기 10 으로 한다.
    크기 · 굵기 · 기울임 · 밑줄 · 취소선 · RGB 색은 그대로 둔다. 바꾼 칸 수."""
    n = 0
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for c in row:
                if c.value is None:
                    continue
                f = c.font
                if f is not None and f.name == FONT:
                    continue
                plain = f is None or (f.name in (None, "Calibri") and (f.sz in (None, 11)) and not f.b and not f.i and _rgb(f.color) is None)
                k = {}
                if not plain and f is not None:
                    if f.b:
                        k["bold"] = True
                    if f.i:
                        k["italic"] = True
                    if f.u:
                        k["underline"] = f.u
                    if f.strike:
                        k["strike"] = True
                    if _rgb(f.color):
                        k["color"] = _rgb(f.color)
                    if f.vertAlign:
                        k["vertAlign"] = f.vertAlign
                size = SIZE_BODY if plain or f is None or f.sz is None else f.sz
                c.font = font(size=size, **k)
                n += 1
    return n


def lint(path: Path) -> list[str]:
    """저장된 엑셀의 보이는 시트에서 맑은 고딕이 아닌 글꼴, 팔레트에 없는 글자 · 칠 색, 조건부 서식의 팔레트 밖 색. 「시트!칸: 무엇」."""
    from openpyxl import load_workbook

    wb = load_workbook(path)
    out: list[str] = []
    for ws in wb.worksheets:
        if ws.sheet_state != "visible" or ws.title.startswith("_"):
            continue
        for row in ws.iter_rows():
            for c in row:
                if c.value is None:
                    continue
                f = c.font
                if f is not None and f.name != FONT:
                    out.append(f"{ws.title}!{c.coordinate}: 글꼴 {f.name}")
                fc = _rgb(f.color) if f is not None else None
                if fc and fc not in PALETTE_FONT:
                    out.append(f"{ws.title}!{c.coordinate}: 글자 색 {fc}")
                if c.fill is not None and c.fill.fill_type == "solid":
                    bg = _rgb(c.fill.fgColor)
                    if bg and bg not in PALETTE_FILL:
                        out.append(f"{ws.title}!{c.coordinate}: 칠 {bg}")
        for rng in ws.conditional_formatting:
            for rule in rng.rules:
                dxf = rule.dxf
                if dxf is None:
                    continue
                if dxf.font is not None:
                    if dxf.font.name not in (None, FONT):
                        out.append(f"{ws.title} 조건부 서식 {rng.sqref}: 글꼴 {dxf.font.name}")
                    fc = _rgb(dxf.font.color)
                    if fc and fc not in PALETTE_FONT:
                        out.append(f"{ws.title} 조건부 서식 {rng.sqref}: 글자 색 {fc}")
                if dxf.fill is not None:
                    bg = _rgb(dxf.fill.fgColor) or _rgb(dxf.fill.bgColor)
                    if bg and bg not in PALETTE_FILL:
                        out.append(f"{ws.title} 조건부 서식 {rng.sqref}: 칠 {bg}")
    return out
