"""입력 정의 한 벌로 입력 양식의 「정의」 시트와 스킬 꾸러미의 references/입력정의.md 를 함께 만든다.

창업감면 · 중소감면 model.py 의 COMPANY_ROWS(항목, 종류, 기본값, 설명)와 SOURCE(받는 곳)를 받는다.
글로 따로 쓰지 않으니 코드가 읽는 항목과 문서의 항목이 어긋나지 않는다. 다른 ctax 모듈은 xlsx 만 읽는다.
"""
from __future__ import annotations

from . import xlsx as X

KIND = {"date": "날짜(YYYY-MM-DD)", "yn": "Y · N", "won": "원", "num": "숫자", "int": "정수", "rate": "비율(7% 는 0.07)",
        "text": "글"}
S_DEF = "정의"


def kind_label(kind: str, picks: dict[str, tuple]) -> str:
    if kind.startswith("pick:"):
        opts = [o for o in picks.get(kind[5:], ()) if o]
        if 0 < len(opts) <= 6:
            return "고름: " + " · ".join(opts)
        return f"고름(양식의 목록 {len(opts)}개)" if opts else "고름"
    return KIND.get(kind, kind)


def default_label(kind: str, default) -> str:
    if default is None:
        return "필수"
    if default == "":
        return "비워도 됨"
    if kind == "rate" and isinstance(default, (int, float)):
        return f"{default * 100:g}%"
    if kind == "won" and isinstance(default, (int, float)):
        return f"{default:,}"
    return str(default)


def rows(sheet: str, company_rows: list, sources: dict, picks: dict[str, tuple]) -> list[tuple]:
    """(시트, 항목, 형식, 비면, 받는 곳, 설명) 줄."""
    return [(sheet, key, kind_label(kind, picks), default_label(kind, default), sources.get(key, ""), desc)
            for key, kind, default, desc in company_rows]


def column_rows(sheet: str, columns: tuple, sources: dict, kinds: dict, required: tuple, notes: dict | None = None) -> list[tuple]:
    """표 시트(한 줄에 여러 열)의 열 정의."""
    notes = notes or {}
    return [(sheet, col, KIND.get(kinds.get(col, ""), kinds.get(col, "")), "필수" if col in required else "비워도 됨",
             sources.get(col, ""), notes.get(col, "")) for col in columns]


HEAD = ("시트", "항목", "형식", "비면", "받는 곳", "설명")


def write_sheet(wb, defs: list[tuple], intro: str) -> None:
    """입력 양식 맨 뒤에 「정의」 시트를 둔다. 엔진은 이 시트를 읽지 않는다."""
    ws = wb.create_sheet(S_DEF)
    ws.cell(row=1, column=1, value=intro).font = X.NOTE_FONT
    X.header(ws, 2, list(HEAD))
    for i, r in enumerate(defs, start=3):
        for j, v in enumerate(r, start=1):
            X.cell(ws, i, j, v, wrap=j >= 5)
    X.widths(ws, [10, 40, 22, 12, 48, 80])
    ws.freeze_panes = "A3"


def markdown(title: str, intro: str, defs: list[tuple]) -> str:
    def esc(v) -> str:
        return str(v).replace("|", "\\|").replace("\n", " ")
    out = [f"# {title}", "", intro, "", "| " + " | ".join(HEAD) + " |", "|" + "---|" * len(HEAD)]
    out += ["| " + " | ".join(esc(v) for v in r) + " |" for r in defs]
    return "\n".join(out) + "\n"
