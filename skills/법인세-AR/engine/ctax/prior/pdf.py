"""전기 세무조정계산서 PDF(국세청 일괄출력) 읽기. corptax.engine.intake.prior_pdf 에서 옮겼다(DB 적재 부분은 뺐다).

쪽 분리(split_pages)
  쪽 머리(위쪽 100pt 안)의 `별지제N호서식…` 표시를 서식 표시(form_hint)로 쓴다. 본문에도
  `[별지제3호서식부표(2)]` 같은 참조 문구가 나오므로 머리만 본다. 표시는 공백·'서식'·'의' 를 지운 뒤
  `호` 뒤에 숫자가 오면 '의' 를 다시 넣어 맞춘다(`3호3서식(4)` 와 `3호의3서식(4)` 는 같은 `3호의3(4)`).
  조세특례제한법·지방세법 서식은 번호가 법인세법 서식과 겹치므로(조특 3호서식(1), 조특 1호서식)
  `조특`·`지방`·`농특` 을 앞에 붙인다. 표시가 없는 쪽은 2~4쪽 목차(제목·시작 쪽)로 정한다. 같은 목차
  항목 안이면 앞 쪽의 표시를 잇고(표준재무상태표 59·60쪽), 항목이 새로 시작하는 쪽이면
  `목차:<제목>` 이다(결산보고서 103쪽 이후).

코드 서식 결정론 파서(parse_pages·parse_coded)
  코드가 인쇄된 서식 일곱 개(FORMS)를 이 모듈이 읽는다. AI 는 쓰지 않는다. 코드 없는 서식과 격자 코드 서식(15·15부표·50을·
  50갑·20_4·8을·8부표3·32·34·23을·세금공과금·선급비용, 21 은 틀만)은 engine.intake.prior_grid 가 칸 격자로 읽는다(단계 B B2).
  쪽 분류(classify)는 격자 서식이면 머리 표시보다 제목을 먼저 본다.
  1. 코드 열: 머리글 `코드` 단어의 x 위치. 머리글이 없는 쪽(3호, 8갑 이어진 쪽)은 코드 모양 단어의
     x 중심을 묶어 세로로 3개 이상 줄 선 곳을 코드 열로 보고, 그것도 없으면 같은 서식 앞 쪽의 열을 잇는다.
     앞 쪽 열을 먼저 잇지 않는 까닭은 FY2025 8갑처럼 이어진 쪽의 코드 열이 앞 쪽 머리글과 어긋날 수
     있어서다.
  2. 값 단어(숫자·콤마·콜론·부호)는 왼쪽에서 가장 가까운 코드 열에 속한다. 같은 열·같은 줄의 값
     단어는 x 순으로 이어 붙여 한 칸이 된다. 표준재무제표는 천 단위 자리를 콜론으로 찍어
     `7:848:372:309`, `:534:157:936` 처럼 나오고 숫자가 없는 묶음은 `:` 만 남는다. 콜론을 지워 합친다.
  3. 칸은 같은 코드 열에서 세로 거리가 가장 가까운 코드에 붙는다(NEAR=12pt 안). 3호 수정신고는 한 란에
     두 줄이 위아래로 5pt 어긋나 찍히므로 줄 맞춤이 아니라 거리로 붙인다.
  4. 금액 열이 여럿인 서식(8갑)은 머리글의 원문자 열(③대상세액 ④감면세액, ⑤전기이월액 ⑥당기발생액
     ⑦공제세액) 가운데 오른쪽 끝(x1)이 가장 가까운 열로 나눈다. 맨 오른쪽 열(감면·공제세액, 3호로 가는
     값)이 item_code 그대로이고, 나머지 열은 `<코드>_<열 번호>` 다(예 `149_5` 전기이월액, `111_3` 대상세액).
     단계 B B1 태스크 9 부터 8갑 서식 정의(forms/defs/8갑.json)가 있고 란 코드가 이 규칙과 같다(계획 D21). 그래서 탭 3 전기 확인
     전기 값의 란 이름·자료형·줄 검사는 정의에서 온다. 정의에 없는 8갑 코드(FY2025 인쇄본에만 있는 161·199·164·165 줄,
     계획 D16)에 값이 찍히면 확인사항이다(_unknown_codes 가 정의가 있는 모든 서식을 본다, 단계 B B2).
  5. 코드가 없는 금액(3호 '각사업연도소득금액(=)'·'산출세액(=)' 되풀이 줄)은 같은 줄 근처에 되풀이
     표시 `(=)` 가 있거나 값이 같은 코드 열의 어느 코드 칸과 같을 때만 조용히 지나간다(칸은 만들지 않는다).
     둘 다 아니면 확인사항이다. 서식 구조가 바뀌어 진짜 코드 칸을 놓친 것일 수 있어서다.

값 규칙
  - item_code 는 인쇄된 코드 그대로(정정 E19). 3호 `01`, 표준FS `3`·`67`, 이잉처분 `01`, 8갑 `16B`,
    1호는 원문자 번호를 숫자로(③ → `3`).
  - 1·3호 수정신고(FY2024 경정청구)는 한 란에 두 줄이 찍힌다. 위 줄의 `△` 는 음수가 아니라 최초신고
    표시다. 경정청구 값이 row_no=0(하류가 읽는 값), 최초신고 값은 row_no=`ROW_ORIGINAL_FILING`(=1) 이다.
    최초신고 줄에 text 를 남기지 않는다. 두 줄의 구분은 row_no 가 한다. 그 밖의 음수는 `-` 로 찍힌다.
    AMENDED 밖의 서식은 `△` 가 줄 어디에 있든(콜론 격자에서 따로 떨어진 토큰으로 나와도) 음수 표시다.
  - 3호 세율 란(11·14·35·60)은 인쇄된 % 를 소수로 바꾼다(19 → 0.19).
  - 단계 B B1 태스크 10 부터 3호 서식 정의(forms/defs/3.json)가 있고 란 코드가 이 파서의 두 글자 코드와 같다(옛 번호
    (101)~(166) 은 정의의 란 별칭). 그래서 탭 3 전기 확인의 전기 값 란 이름·자료형(세율 란은 정의의 rate)·줄 검사(최초신고 줄은
    AMENDED 예외)는 정의에서 온다.
  - B1 태스크 11 부터 1호 정의(forms/defs/1.json)도 있다. ①~⑮ 란 이름은 이 파서가 찾는 제목(values.LABELS_1)과 같고(계획
    D26) 전기 PDF 서식 일곱이 모두 정의가 있다. 1호 ①~⑫ 는 text 다. ⑬ 법인구분·⑭ 조정구분·⑮ 종류별구분은 고른 칸에
    동그라미가 벡터로 그려지고 텍스트 층에는 선택지 목록만 있다. 그래서 동그라미 안 글자를 읽는다(⑬ `1.내국`, ⑭ `1.외부`,
    ⑮ 종류별 구분 코드 `30`). 날짜 틀만 있는 빈 란(⑫ `. . ~ . .`)은 넣지 않는다.

DB 적재(load_prior)와 확인사항 문구(problem_text)는 옮기지 않았다. ctax 는 결과를 ctax.prior.read 가 전기.json 으로 쓴다.
검산(스펙 §6): 3호 (01) = 표준IS (219) 당기순손익, 표준BS (228) 자산총계 = (383) 부채와자본총계.
"""
import json
import re
from dataclasses import dataclass, replace
from pathlib import Path

import pymupdf as fitz

from ctax.prior.grid import amount, reading_order
from ctax.prior.defs import LABELS_1, form_def, form_name

# 파서가 읽는 서식: form_hint → form_code
FORMS = {"1호": "1", "3호": "3", "8호(갑)": "8갑", "3호의2(1)": "std_bs", "3호의3(1)": "std_is",
         "3호의3(3)": "std_cogs", "3호의3(4)": "std_re",
         # 금융 · 보험 · 증권업 법인용 표준재무제표(4회차 R4-2). 합계표준재무상태표는 차변 · 대변 두 금액 열이라 _parse_sum 이 읽는다
         "3호의2(3)": "std_bs_fin", "3호의2(4)": "std_bs_fin_sum", "3호의3(2)": "std_is_fin"}
# 일반법인용과 금융업용은 둘 중 하나만 낸다. 신고본에 금융업용 쪽이 하나라도 있으면 금융업용 셋을, 없으면 일반법인용 둘을 찾는다
STD_GENERAL = ("std_bs", "std_is")
STD_FIN = ("std_bs_fin", "std_bs_fin_sum", "std_is_fin")

# 서식별 코드 모양. multi: 금액 열이 여럿(원문자 머리글로 나눈다). rates: % 로 찍히는 세율 란.
# merged: 긴 과목 이름이 코드와 한 낱말로 찍히는 표준재무제표(「…미처리결손금403」 「…단기차입금236」 「…평가손익362」). 낱말 끝이
# 머리글 코드 열 안에 있을 때만 코드로 뗀다. 금융업용에서 먼저 봤고(R4-2) 일반법인용도 같은 꼴이다(읽기 점수판 2026-10-23)
SPEC = {
    "3": {"code": r"\d{2}", "rates": {"11", "14", "35", "60"}},
    "8갑": {"code": r"\d[0-9A-Z]{2}", "multi": True},
    "std_bs": {"code": r"\d{1,3}", "merged": True},
    "std_is": {"code": r"\d{1,3}", "merged": True},
    "std_cogs": {"code": r"\d{1,3}", "merged": True},
    "std_re": {"code": r"\d{2}", "merged": True},
    "std_bs_fin": {"code": r"\d{1,3}", "merged": True},
    "std_is_fin": {"code": r"\d{1,3}", "merged": True},
    "std_bs_fin_sum": {"code": r"\d{1,3}"},
}
AMENDED = {"1", "3"}                    # △ 가 최초신고 줄 표시인 서식
ROW_ORIGINAL_FILING = 1                 # AMENDED 서식에서 최초신고 줄의 row_no(경정청구 줄은 0)

CIRCLED = {chr(0x2460 + i): i + 1 for i in range(20)}          # ① → 1
LAWS = (("조세특례제한법", "조특"), ("지방세법", "지방"), ("농어촌특별세법", "농특"))

TOP_BAND = 100                          # 서식 표시를 찾는 쪽 머리 높이(pt)
TITLE_BAND = 135                        # 격자 서식 제목을 찾는 쪽 머리 높이(pt, FY2025 32호 제목 아래 끝 127)
MARK = re.compile(r"별\s*지\s*(?:제\s*)?(\d[^\]】\n]*?)\s*[\]】]")
TOC = re.compile(r"(\d+)\.\s*([^\n]+?)-{3,}\s*(\d+)")
VALUE = re.compile(r":*△?:*-?[\d,:]*\d[\d,:]*|:+|△")    # ':-1:610:178:123' 처럼 앞 콜론 뒤 부호도 온다.
                                                          # 마지막 '|△' 는 콜론 격자에서 따로 떨어진 △ 토큰
REPEAT_MARK = re.compile(r"\(\s*=\s*\)")                # 3호 '각사업연도소득금액(=)' 같은 되풀이 줄 표시
LINE_TOL = 2.0                          # 같은 줄로 보는 y 중심 차이
NEAR = 12.0                             # 칸을 코드에 붙이는 세로 거리 상한(3호 ⑦ 세액계 줄은 9.6pt 어긋난다)

# 서식 레이아웃에 기댄 판정 상수(전부 pt, 두 PDF 실측 기준)
MARK_MIN, MARK_MAX = 6.0, 16.0          # 1호 선택 동그라미로 볼 도형의 한 변 범위(실측 10.8pt 정사각)
MARK_SQUARE_TOL = 2.0                   # 그 도형의 가로·세로 차이 허용치
CODE_HEAD_LEFT, CODE_HEAD_RIGHT = 6.0, 24.0   # 머리글 '코드' 단어 x 위치에서 코드 열 경계를 넓히는 폭
VALUE_HEAD_BAND = 200.0                 # 8갑 금액 열 머리글(③④⑤⑥⑦)을 찾는 쪽 위쪽 y 한계
LABEL_LINE_TOL = 3.0                    # 1호 원문자 란에서 같은 줄로 보는 y 중심 차이
CHOICE_MARK_TOL = 6.0                   # 1호 ⑬⑭ 동그라미가 원문자 줄과 같다고 볼 y 차이 허용치
KIND_CODE_ABOVE, KIND_CODE_BELOW = 15.0, 100.0   # 1호 ⑮ 표를 찾는 범위: 제목 줄 위·아래
KIND_CODE_X_MAX = 300.0                 # 1호 ⑮ 표가 있다고 볼 쪽 왼쪽 x 한계


@dataclass
class Cell:
    form_code: str
    item_code: str
    row_no: int
    value: float | None
    text: str | None
    bbox: tuple
    page_no: int | None = None


@dataclass
class Problem:
    target_ref: str
    title: str
    why: str


# ---------------------------------------------------------------- 쪽 분리

def norm_hint(s: str) -> str:
    """`3호의2서식(1)`·`3호3서식(4)`·`8호서식(갑)` 같은 표기를 `3호의2(1)`·`3호의3(4)`·`8호(갑)` 으로."""
    s = re.sub(r"\s+", "", s).replace("서식", "").replace("의", "")
    s = re.sub(r"^제", "", s)
    return re.sub(r"호(?=\d)", "호의", s)


def _yc(w) -> float:
    return (w[1] + w[3]) / 2


def _lines(words):
    """쪽 단어를 읽는 순서로(grid.reading_order). 전에는 y 중심을 1pt 로 반올림해 줄을 나눠, 같은 줄 단어 y 가 반올림 경계에
    걸리면 순서가 뒤섞였다(B2 리뷰 I1). 기준 신고본 두 해 쪽 분류·코드 서식 값은 바꾸기 전과 같다."""
    return reading_order(words)


def _marker(words) -> str:
    top = " ".join(w[4] for w in _lines([w for w in words if w[1] < TOP_BAND]))
    m = MARK.search(top)
    if not m:
        return ""
    law = next((short for name, short in LAWS if name in top[:m.start()]), "")
    return law + norm_hint(m.group(1))


def _toc(text: str) -> list[tuple[int, str]]:
    return [(int(m.group(3)), re.sub(r"\s+", "", m.group(2))) for m in TOC.finditer(text)]


def _marks(page) -> list[tuple]:
    """고른 칸에 그려진 동그라미(곡선만으로 된 작은 정사각 도형)와 그 안의 글자."""
    out = []
    for d in page.get_drawings():
        r = d["rect"]
        if d["items"] and all(i[0] == "c" for i in d["items"]) and MARK_MIN < r.width < MARK_MAX \
                and abs(r.width - r.height) < MARK_SQUARE_TOL:
            out.append((r.x0, r.y0, r.x1, r.y1, page.get_textbox(r).strip()))
    return out


def title_form(top: str):
    """쪽 머리 글(top)에 든 격자 서식 제목의 서식. 둘 이상 들면 가장 긴 제목이다(짧은 제목이 긴 제목 안에 들 수 있다, B2 리뷰
    M3). 없으면 None."""
    from ctax.prior import grid_forms as prior_grid
    hit = [fc for fc, title in prior_grid.TITLES.items() if title in (top or "")]
    return max(hit, key=lambda fc: len(prior_grid.TITLES[fc])) if hit else None


def classify(hint: str, top: str):
    """쪽의 서식 코드. 코드 서식(FORMS)은 머리 표시로 정한다(제목과 어긋나는지는 title_conflict 가 따로 본다). 그 밖에 표시가
    있는 쪽(인쇄된 표시든 앞 쪽 표시를 이은 것이든)은 격자 서식 제목(title_form)을 먼저 보고, 제목이 없으면 표시(prior_grid.
    HINTS)로 정한다(FY2024 28쪽은 머리 표시가 '15호부표1' 인데 제목은 과목별소득금액조정명세서(2)다, 제목 없는 34호 50쪽은 이은
    표시로 34 다). 목차로 정한 쪽(결산부속명세서 안의 '선급비용명세서' 같은 제목)과 표시가 없는 쪽은 제목을 보지 않는다. top 은
    쪽 머리 TITLE_BAND 안의 글(grid.norm)이다. 파서가 읽지 않는 쪽은 None."""
    from ctax.prior import grid_forms as prior_grid
    if hint in FORMS:
        return FORMS[hint]
    if hint and not hint.startswith("목차"):
        titled = title_form(top)
        if titled:
            return titled
    return prior_grid.HINTS.get(hint)


def title_conflict(hint: str, top: str):
    """코드 서식 머리 표시(FORMS)가 있는 쪽 머리에 격자 서식 제목이 있으면 그 격자 서식. 분류는 표시대로 두되(classify)
    _parse_pages 가 확인사항을 낸다. 격자 쪽이 앞 쪽의 코드 서식 표시를 잇거나 표시가 잘못 인쇄되면 코드 서식 파서로 조용히
    가는 것을 막는다(B2 리뷰 M3). 기준 신고본 두 해에는 이런 쪽이 없다. 그 밖에는 None."""
    return title_form(top) if hint in FORMS else None


def split_pages(pdf_path) -> list[dict]:
    """쪽마다 {page_no, form_hint, form_code, text, words}. form_code 는 파서가 읽는 서식일 때만 있다(classify).
    1호 쪽에는 marks(동그라미)를, 격자 서식 쪽에는 grid(선·글자, grid.page_data)를 붙인다. form_hint 는 인쇄된 머리 표시
    그대로다(분류가 제목으로 바로잡아도 표시는 두어 쪽 목록과 대조할 수 있게)."""
    from ctax.prior import grid
    from ctax.prior import grid_forms as prior_grid
    doc = fitz.open(str(pdf_path))
    try:
        raw = []
        for i, page in enumerate(doc):
            words = page.get_text("words")          # (x0, y0, x1, y1, word, block, line, wordno)
            raw.append({"page_no": i + 1, "text": page.get_text(), "words": words, "marker": _marker(words),
                        "top": grid.norm("".join(w[4] for w in _lines(words) if w[1] < TITLE_BAND))})
        toc_pages = {p["page_no"] for p in raw if p["words"] and _lines(p["words"])[0][4] == "목차"}
        toc = sorted(e for p in raw if p["page_no"] in toc_pages for e in _toc(p["text"]))

        def section(no):
            hit = [e for e in toc if e[0] <= no]
            return hit[-1] if hit else None

        pages, prev = [], None
        for p in raw:
            sec = section(p["page_no"])
            if p["page_no"] in toc_pages:
                hint = "목차"
            elif p["marker"]:
                hint = p["marker"]
            elif prev and sec and prev["section"] == sec and prev["form_hint"] not in ("", "목차"):
                hint = prev["form_hint"]            # 표시 없는 이어진 쪽
            elif sec:
                hint = "목차:" + sec[1]
            else:
                hint = ""
            cur = {"page_no": p["page_no"], "form_hint": hint, "form_code": classify(hint, p["top"]),
                   "text": p["text"], "words": p["words"], "section": sec}
            other = title_conflict(hint, p["top"])
            if other:
                cur["title_form"] = other           # 코드 서식 표시 쪽의 격자 서식 제목(_parse_pages 가 확인사항으로)
            if cur["form_code"] == "1":
                cur["marks"] = _marks(doc[p["page_no"] - 1])
            elif cur["form_code"] in prior_grid.FORMS:
                cur["grid"] = grid.page_data(doc[p["page_no"] - 1])
            pages.append(cur)
            prev = cur
        for p in pages:
            p.pop("section")
        return pages
    finally:
        doc.close()


# ---------------------------------------------------------------- 코드 서식

def _union(ws) -> tuple:
    return (round(min(w[0] for w in ws), 1), round(min(w[1] for w in ws), 1),
            round(max(w[2] for w in ws), 1), round(max(w[3] for w in ws), 1))


def _code_columns(words, code_re) -> tuple[list[tuple], bool]:
    """코드 열 [(x0, x1)] 과 묶음으로 찾았는지 여부. 머리글 `코드` 가 있으면 그 x 위치, 없으면 코드 모양
    단어의 x 중심이 3pt 안에서 세로로 3개 이상 줄 선 곳이다."""
    heads = [w for w in words if w[4].startswith("코드")]
    if heads:
        return sorted((w[0] - CODE_HEAD_LEFT, w[0] + CODE_HEAD_RIGHT) for w in heads), False
    cands = sorted((w for w in words if re.fullmatch(code_re, w[4])), key=lambda w: (w[0] + w[2]) / 2)
    groups, group = [], []
    for w in cands:
        if group and (w[0] + w[2]) / 2 - (group[-1][0] + group[-1][2]) / 2 > 3:
            groups.append(group)
            group = []
        group.append(w)
    groups.append(group)
    return [(min(w[0] for w in g) - 2, max(w[2] for w in g) + 2) for g in groups if len(g) >= 3], True


def _value_heads(words) -> list[tuple[int, float]]:
    """8갑 금액 열 머리글: (원문자 번호, 오른쪽 끝 x). '코드⑤전기이월액' 처럼 붙은 머리글도 잡는다."""
    out = []
    for w in words:
        m = re.search(r"([③④⑤⑥⑦])[가-힣()]*액$", w[4])
        if m and w[1] < VALUE_HEAD_BAND:
            out.append((CIRCLED[m.group(1)], w[2]))
    return out


def _num(s: str):
    t = s.replace("△", "").replace(",", "").replace(":", "")
    if t == "":
        return None
    if not re.fullmatch(r"-?\d+", t):
        raise ValueError(s)
    return int(t)


def _has_repeat_mark(words, y: float) -> bool:
    """y 근처(NEAR 안)에 되풀이 표시 `(=)` 가 있으면 참. 라벨과 값이 줄마다 다른 기준선에 찍혀도(FY2024
    3호처럼) 잡도록 NEAR 만큼 넓게 본다."""
    nearby = "".join(w[4] for w in sorted((w for w in words if abs(_yc(w) - y) <= NEAR), key=lambda w: w[0]))
    return bool(REPEAT_MARK.search(nearby))


def _parse_numeric(words, form_code: str, carry: dict | None = None) -> tuple[list[Cell], list[Problem], dict]:
    """코드 서식 한 쪽. carry 는 앞 쪽의 열 정보다(머리글 없는 이어진 쪽이 쓴다). 돌려주는 셋째 값이 다음 carry."""
    spec = SPEC[form_code]
    code_re = spec["code"]
    carry = carry or {}
    words = [w for w in words if w[4].strip()]
    cols, clustered = _code_columns(words, code_re)
    if not cols and carry.get("cols"):
        cols, clustered = carry["cols"], carry["clustered"]
    heads = (_value_heads(words) or carry.get("heads", [])) if spec.get("multi") else []
    if not cols:
        return [], [Problem(form_code, f"{form_code} 코드 열을 찾지 못했다",
                            "머리글 '코드' 도 코드 모양 단어의 세로 줄도 없다")], carry
    problems: list[Problem] = []

    def col_of(w):
        return next((i for i, (a, b) in enumerate(cols) if a <= (w[0] + w[2]) / 2 <= b), None)

    codes, values = [], []                      # codes: (열, 코드, y 중심), values: (열, 단어)
    for w in words:
        t = w[4]
        ci = col_of(w)
        if ci is not None and re.fullmatch(code_re, t):
            codes.append((ci, t, _yc(w)))
            continue
        # 라벨에 붙은 코드는 한글 · 닫는 괄호 바로 뒤의 숫자만이다. 날짜 「2024.01.01」 처럼 점 · 숫자 뒤의 숫자는 코드가 아니다
        # (std_re 머리의 사업연도가 코드 열 안에서 끝나 01 란이 여러 줄이 됐다, 점수판 10-23)
        m = re.search(rf"(?<=[가-힣)）\]])({code_re})$", t)
        edge = next((i for i, (a, b) in enumerate(cols) if abs(w[2] - (b - 2)) < 3), None) if clustered else None
        if edge is None and spec.get("merged") and not clustered:
            # 표준재무제표(merged): 긴 과목 이름이 코드와 한 낱말로 찍히고(「…미처리결손금403」 「…단기차입금236」) 그 끝이 머리글
            # 코드 열 안에 있다. 위 란(합계)과 금액이 같으면 코드 없는 금액 확인사항도 안 나와 조용히 빠졌었다(점수판 10-23)
            edge = next((i for i, (a, b) in enumerate(cols) if a <= w[2] <= b and w[0] < a), None)
        if m and m.start() > 0 and edge is not None:
            # '간접투자회사등의외국납부세액25' 처럼 제목에 붙었지만 코드 열 오른쪽 끝에 맞춰 찍힌 코드
            codes.append((edge, m.group(1), _yc(w)))
            continue
        if VALUE.fullmatch(t):
            left = [i for i, (a, b) in enumerate(cols) if b <= w[0] + 1]
            if left:
                values.append((left[-1], w))

    # 같은 코드 열·같은 금액 열·같은 줄의 값 단어를 한 칸으로
    buckets: dict[tuple, list] = {}
    for ci, w in values:
        n = min(heads, key=lambda h: abs(h[1] - w[2]))[0] if heads else None
        buckets.setdefault((ci, n), []).append(w)
    groups = []
    for key, ws in buckets.items():
        ws.sort(key=_yc)
        line = [ws[0]]
        for w in ws[1:]:
            if abs(_yc(w) - _yc(line[-1])) <= LINE_TOL:
                line.append(w)
            else:
                groups.append((key, line))
                line = [w]
        groups.append((key, line))

    principal = max((h[0] for h in heads), default=None)
    found: dict[tuple, list] = {}               # (코드, 금액 열) → [(코드와 거리, y, 원문, 값, bbox)]
    column_values: dict[int, set] = {}          # 코드 열 → 그 열에서 코드에 붙은 값(코드 없는 금액 면제 판정용)
    for (ci, n), ws in groups:
        ws.sort(key=lambda w: w[0])
        raw = "".join(w[4] for w in ws)
        digits = [w for w in ws if re.search(r"\d", w[4])]
        if not digits:
            continue                            # ':' 만 있는 빈 칸
        y = _yc(digits[0])
        near = sorted((abs(c[2] - y), c[1]) for c in codes if c[0] == ci and abs(c[2] - y) <= NEAR)
        try:
            val = _num(raw)
        except ValueError:
            code = near[0][1] if near else "?"
            problems.append(Problem(f"{form_code}.{code}.값", f"{form_code} ({code}) 금액을 읽지 못했다",
                                    f"인쇄 문자열 {raw!r}"))
            continue
        if not near:
            span = [c[2] for c in codes if c[0] == ci]
            inside = span and min(span) - NEAR <= y <= max(span) + NEAR     # 표 밖(쪽 번호 등)은 금액이 아니다
            if inside:
                # 같은 코드 열에서 이미 읽은 값과 같을 때만 면제한다(트리아지 T9: 쪽 전체에서 찾으면 다른 열의 같은
                # 값이 진짜 코드 칸을 놓친 것을 가렸다)
                known = val in column_values.get(ci, set())
                if not (_has_repeat_mark(words, y) or known):
                    problems.append(Problem(f"{form_code}.코드없음.{raw}", f"{form_code} 코드 없는 금액 {raw}",
                                            f"y={y:.0f} 근처 {NEAR:.0f}pt 안에 코드가 없고 되풀이 표시도,"
                                            " 같은 값의 코드 란도 없다"))
                # 되풀이 표시나 이미 읽은 값과 같으면 조용히 지나간다(칸은 만들지 않는다)
            continue
        dist, code = near[0]
        found.setdefault((code, n), []).append((dist, y, raw, val, _union(digits)))
        column_values.setdefault(ci, set()).add(val)

    cells = []
    for (code, n), items in found.items():
        item = code if n is None or n == principal else f"{code}_{n}"
        items.sort(key=lambda x: x[1])
        tri = [x for x in items if x[2].startswith("△")]
        plain = [x for x in items if not x[2].startswith("△")]
        if form_code in AMENDED and tri:
            # 수정신고: 위 줄 △ 가 최초신고, 아래 줄이 경정청구
            if len(tri) > 1 or len(plain) > 1:
                problems.append(Problem(f"{form_code}.{item}.줄", f"{form_code} ({item}) 금액 줄이 셋 이상이다",
                                        " / ".join(x[2] for x in items)))
            if not plain:
                problems.append(Problem(f"{form_code}.{item}.△", f"{form_code} ({item}) 최초신고 줄만 있다",
                                        f"△ 줄 {tri[0][2]} 의 짝(경정청구 줄)이 없다"))
            rows = [(ROW_ORIGINAL_FILING, tri[0])] + ([(0, plain[-1])] if plain else [])
        else:
            if len(items) > 1:
                problems.append(Problem(f"{form_code}.{item}.줄", f"{form_code} ({item}) 금액이 여러 줄이다",
                                        " / ".join(x[2] for x in items) + ". 코드에 가장 가까운 줄을 썼다"))
            rows = [(0, min(items))]
        for row_no, (_, _, raw, val, bbox) in rows:
            if val is None:
                continue
            if form_code not in AMENDED and "△" in raw:
                val = -val                      # 1·3호 밖의 △ 는 음수 표시(줄 어디에 있든, 콜론 격자로 흩어져도)
            v = val / 100 if code in spec.get("rates", ()) else val
            cells.append(Cell(form_code, item, row_no, v, None, bbox))
    return cells, problems, {"cols": cols, "clustered": clustered, "heads": heads}


def parse_coded(words, form_code: str = "std_bs") -> dict:
    """코드 서식 한 쪽의 {item_code: 값}. row_no=0(경정청구 줄·정기신고 값)만 돌려준다."""
    if form_code == "std_bs_fin_sum":
        cells, _ = _parse_sum(words)
    else:
        cells, _, _ = _parse_numeric(words, form_code)
    return {c.item_code: c.value for c in cells if c.row_no == 0}


SUM_LINE_TOL = 3.0                      # 합계표준재무상태표 한 줄로 보는 y 중심 차이(코드와 금액이 같은 기준선에 찍힌다)


def _parse_sum(words, form_code: str = "std_bs_fin_sum") -> tuple[list[Cell], list[Problem]]:
    """합계표준재무상태표(금융업) 한 쪽. 줄 모양이 [차변 합계] [계정과목] [코드] [대변 합계] 라서 코드 열 왼쪽 금액은 차변
    (`<코드>_차`), 오른쪽 금액은 대변(`<코드>_대`)이다. 일반 코드 서식 파서는 코드 열 오른쪽 금액만 읽어 차변을 놓친다.
    금액은 콜론 격자(`:  :22:356:197:202`)라 같은 줄 · 같은 쪽 값 단어를 이어 붙여 콜론을 지운다. △ · - 는 음수다."""
    words = [w for w in words if w[4].strip()]
    heads = [w for w in words if w[4].startswith("코드")]
    if not heads:
        return [], [Problem(form_code, f"{form_code} 코드 열을 찾지 못했다", "머리글 '코드' 가 없다")]
    head = min(heads, key=lambda w: w[1])
    left, right = head[0] - CODE_HEAD_LEFT, head[0] + CODE_HEAD_RIGHT
    cells, problems = [], []
    for c in words:
        if not (left <= (c[0] + c[2]) / 2 <= right and re.fullmatch(r"\d{1,3}", c[4]) and c[1] > head[1]):
            continue
        line = [w for w in words if abs(_yc(w) - _yc(c)) <= SUM_LINE_TOL and VALUE.fullmatch(w[4])]
        for side, part in (("차", [w for w in line if w[2] <= left]), ("대", [w for w in line if w[0] >= right - 2])):
            part.sort(key=lambda w: w[0])
            raw = "".join(w[4] for w in part)
            if not re.search(r"\d", raw):
                continue
            try:
                val = _num(raw)
            except ValueError:
                problems.append(Problem(f"{form_code}.{c[4]}_{side}.값", f"{form_code} ({c[4]}_{side}) 금액을 읽지 못했다",
                                        f"인쇄 문자열 {raw!r}"))
                continue
            if val is None:
                continue
            if "△" in raw:
                val = -val
            cells.append(Cell(form_code, f"{c[4]}_{side}", 0, val, None, _union([w for w in part if re.search(r"\d", w[4])])))
    return cells, problems


def _company_info(words, marks) -> tuple[list[Cell], list[Problem]]:
    """1호 ①~⑮. 원문자로 시작하는 단어부터 같은 줄의 다음 원문자 단어 앞까지가 한 란이다."""
    cells, problems = [], []
    heads = [w for w in words if w[4][:1] in CIRCLED and CIRCLED[w[4][0]] in LABELS_1]
    for h in heads:
        n = CIRCLED[h[4][0]]
        row = sorted((w for w in words if abs(_yc(w) - _yc(h)) < LABEL_LINE_TOL and w[0] >= h[0]), key=lambda w: w[0])
        stop = next((w[0] for w in row[1:] if w[4][:1] in CIRCLED), 1e9)
        row = [w for w in row if w[0] < stop]
        texts = [h[4][1:]] + [w[4] for w in row[1:]]
        label, i, value_ws, value_parts = LABELS_1[n], 0, [], []
        for k, t in enumerate(texts):
            j = 0
            while i < len(label) and j < len(t) and t[j] == label[i]:
                i, j = i + 1, j + 1
            if i < len(label):
                if j < len(t):
                    break                       # 제목이 예상과 다르다
                continue
            value_parts = ([t[j:]] if t[j:] else []) + texts[k + 1:]
            value_ws = row[k:] if t[j:] else row[k + 1:]
            break
        if i < len(label):
            problems.append(Problem(f"1.{n}", f"1호 ({n}) {label} 란 제목을 찾지 못했다", " ".join(texts)))
            continue
        text = " ".join(value_parts).strip()
        bbox = _union(value_ws) if value_ws else _union([h])
        if n in (13, 14):
            text, bbox = _choice_on_line(text, h, stop, marks)
        elif n == 15:
            text, bbox = _kind_code(h, marks)
        if text is None:
            problems.append(Problem(f"1.{n}", f"1호 ({n}) {label} 선택 표시를 찾지 못했다", "동그라미 도형이 없다"))
            continue
        if not re.search(r"[0-9A-Za-z가-힣]", text):
            continue                            # 날짜 틀만 있는 빈 란
        cells.append(Cell("1", str(n), 0, None, text, bbox))
    return cells, problems


def _choice_on_line(options_text: str, head, stop, marks):
    """⑬·⑭: 같은 줄에서 동그라미가 둘러싼 선택지 번호와 이름(`1.내국`)."""
    opts = {m.group(1): m.group(2) for m in re.finditer(r"(\d)\.\s*([^\d]*?)\s*(?=\d\.|$)", options_text)}
    for x0, y0, x1, y1, t in marks:
        if abs((y0 + y1) / 2 - _yc(head)) < CHOICE_MARK_TOL and head[0] <= (x0 + x1) / 2 < stop:
            d = re.match(r"(\d)", t)
            if d:
                name = opts.get(d.group(1))
                return (f"{d.group(1)}.{name}" if name else d.group(1)), _union([(x0, y0, x1, y1)])
    return None, None


def _kind_code(head, marks):
    """⑮ 종류별 구분: 표(상장·코스닥·기타·비영리 × 중소·중견·상호출자·그외) 안 동그라미가 둘러싼 두 자리 코드.
    표는 ⑮ 제목 줄 바로 위에서 아래로 100pt 안, 쪽 왼쪽 절반에 있다."""
    for x0, y0, x1, y1, t in marks:
        if re.fullmatch(r"\d{2}", t) and head[1] - KIND_CODE_ABOVE < (y0 + y1) / 2 < head[1] + KIND_CODE_BELOW \
                and x0 < KIND_CODE_X_MAX:
            return t, _union([(x0, y0, x1, y1)])
    return None, None


def parse_pages(pages: list[dict]) -> list[Cell]:
    """split_pages 결과에서 코드 서식 일곱 개의 칸을 전부 읽는다."""
    return _parse_pages(pages)[0]


def _parse_pages(pages: list[dict]) -> tuple[list[Cell], list[Problem]]:
    from ctax.prior import grid_forms as prior_grid
    cells, problems, carry = [], [], {}
    found = {p.get("form_code") for p in pages}
    fin = bool(found & set(STD_FIN))
    for fc in FORMS.values():
        if fc in (STD_GENERAL if fin else STD_FIN):
            continue                            # 일반법인용 · 금융업용 중 신고본이 쓴 쪽만 찾는다
        if fc not in found:
            why = "쪽 머리 표시와 목차로 찾았다"
            if fc == "1":
                why += ". 1호 신고서를 따로 낸 신고본일 수 있다(회사 정보는 51호 · 표지에서 읽는다)"
            problems.append(Problem(fc, f"전기 PDF 에서 {fc} 서식 쪽을 찾지 못했다", why))
    for p in pages:
        if p.get("title_form"):
            fc, no = p["form_code"], p["page_no"]
            problems.append(Problem(f"{fc}.p{no}.제목", f"{fc} {no}쪽 머리 표시와 제목이 다르다",
                                    f"{no}쪽. 머리 표시 {p['form_hint']} 대로 {fc} 로 읽었다. 쪽 머리 제목은 {p['title_form']}"
                                    " 서식 제목이다"))
    grid_pages: dict = {}
    for p in pages:
        fc = p.get("form_code")
        if fc in prior_grid.FORMS:
            grid_pages.setdefault(fc, []).append(p)
            continue
        if not fc:
            continue
        try:
            if fc == "1":
                cs, ps = _company_info(p["words"], p.get("marks", []))
            elif fc == "std_bs_fin_sum":
                cs, ps = _parse_sum(p["words"])
            else:
                cs, ps, carry[fc] = _parse_numeric(p["words"], fc, carry.get(fc))
        except Exception as e:                  # 한 쪽이 깨져도 나머지 쪽은 읽는다
            cs, ps = [], [Problem(f"{fc}.p{p['page_no']}", f"{fc} {p['page_no']}쪽을 읽다 멈췄다", repr(e))]
        for c in cs:
            c.page_no = p["page_no"]
        for q in ps:
            q.why = f"{p['page_no']}쪽. {q.why}"
        cells += cs
        problems += ps
    for fc, ps_ in grid_pages.items():
        try:
            cs, ps = prior_grid.parse(fc, ps_)
        except Exception as e:                  # 한 서식이 깨져도 나머지 서식은 읽는다
            # 격자 서식은 서식 하나를 한 번에 읽으므로 멈추면 그 서식의 모든 쪽 값을 잃는다. 제목은 쪽이 아니라 서식이고 why 는
            # 쪽 범위다(태스크 7 리뷰 I1. 전에는 첫 쪽 하나의 문제처럼 적었다)
            nos = [p["page_no"] for p in ps_]
            cs, ps = [], [Problem(f"{fc}.p{nos[0]}", f"{fc} {GRID_STOPPED}", f"{_span(nos)}쪽. {e!r}")]
        cells += cs
        problems += ps
    # 같은 란이 두 쪽에 나오면 앞 쪽 것을 쓴다
    seen, uniq = set(), []
    for c in cells:
        k = (c.form_code, c.item_code, c.row_no)
        if k in seen:
            problems.append(Problem(f"{c.form_code}.{c.item_code}.{c.row_no}.중복",
                                    f"{c.form_code} ({c.item_code}) 이 두 쪽에 있다", f"{c.page_no}쪽 값 {_fmt(c.value)} 은 버렸다"))
            continue
        seen.add(k)
        uniq.append(c)
    return uniq, problems + _checks(uniq) + _unknown_codes(uniq)


GRID_STOPPED = "서식을 읽다 멈췄다"          # 격자 서식 파서가 멈춘 문제의 제목 끝(problem_text 가 이것으로 가른다)
_SPAN = re.compile(r"^([\d~·]+)쪽\.\s*")


def _span(nos) -> str:
    """쪽 번호 목록을 글로. 하나면 '26', 이어지면 '26~27', 떨어져 있으면 '26·28'."""
    nos = sorted(set(nos))
    if len(nos) == 1:
        return str(nos[0])
    if nos[-1] - nos[0] == len(nos) - 1:
        return f"{nos[0]}~{nos[-1]}"
    return "·".join(str(n) for n in nos)


def _checks(cells) -> list[Problem]:
    """3호 01 = 표준손익계산서 당기순손익, 표준재무상태표 자산총계 = 부채와자본총계. 신고본이 금융업용 표준재무제표를 썼으면
    금융업용 란(표준손익계산서 370, 표준재무상태표 270 · 405)으로 보고, 합계표준재무상태표 차변 − 대변도 견준다."""
    v = {(c.form_code, c.item_code): c.value for c in cells if c.row_no == 0 and c.value is not None}
    forms = {c.form_code for c in cells}
    fin_is, fin_bs = "std_is_fin" in forms, "std_bs_fin" in forms
    ni = ("std_is_fin", "370") if fin_is else ("std_is", "219")
    assets, total = (("std_bs_fin", "270"), ("std_bs_fin", "405")) if fin_bs else (("std_bs", "228"), ("std_bs", "383"))
    pairs = [(("3", "01"), ni, "3호 결산서상 당기순손익 = 표준손익계산서 당기순손익"),
             (assets, total, "표준재무상태표 자산총계 = 부채와자본총계")]
    out = []
    for (fa, ia), (fb, ib), what in pairs:
        a, b = v.get((fa, ia)), v.get((fb, ib))
        if a is None or b is None or a != b:
            out.append(Problem(f"check.{fa}.{ia}={fb}.{ib}", f"검산 불일치: {what}",
                               f"{fa} ({ia}) {_fmt(a)} / {fb} ({ib}) {_fmt(b)}"))
    if fin_bs and "std_bs_fin_sum" in forms:
        for code, sign, what in (("270", 1, "자산총계 차변 합계 − 대변 합계"), ("405", -1, "부채와자본총계 대변 합계 − 차변 합계")):
            dr, cr = v.get(("std_bs_fin_sum", f"{code}_차")) or 0, v.get(("std_bs_fin_sum", f"{code}_대")) or 0
            a, b = sign * (dr - cr), v.get(("std_bs_fin", code))
            if b is None or a != b:
                out.append(Problem(f"check.std_bs_fin_sum.{code}=std_bs_fin.{code}",
                                   f"검산 불일치: 합계표준재무상태표 {what} = 표준재무상태표 ({code})",
                                   f"std_bs_fin_sum ({code}) 차변 {_fmt(dr)} · 대변 {_fmt(cr)} / std_bs_fin ({code}) {_fmt(b)}"))
    return out


def _unknown_codes(cells) -> list[Problem]:
    """읽은 란을 서식 정의(forms/defs, values.form_def)의 란 코드와 맞춘다. 정의가 있는 서식의 정의에 없는 코드는 잘못 읽었거나
    서식 개정으로 생긴 줄이다(FY2025 8갑 161·199·164·165 같은 줄, B1 계획 D16). 조용히 빠지면 탭 3 전기 확인에서도 고칠 수 없으므로
    확인사항이다(설계 §7 B2). 전에는 표준재무제표 넷만 봤다."""
    out, seen = [], set()
    for c in cells:
        form = form_def(c.form_code)
        if form is None or form.find(c.item_code) is not None or (c.form_code, c.item_code) in seen:
            continue
        seen.add((c.form_code, c.item_code))
        out.append(Problem(f"{c.form_code}.{c.item_code}.정의", f"{c.form_code} ({c.item_code}) 는 서식 정의에 없는 코드다",
                           f"{c.page_no}쪽 값 {_fmt(c.value) if c.value is not None else c.text}"))
    return out


def _fmt(v) -> str:
    if v is None:
        return "없음"
    return f"{v:,.0f}" if float(v).is_integer() else str(v)


ROW_CHANGED = "승인 값 {} 은 같고 같은 줄의 다른 란이 바뀌었다"      # 줄 단위로 되돌린 란의 근거(problem_text 가 읽는다)


def _rows_unchanged(cells, kept) -> dict:
    """여러 줄 서식의 줄마다 다시 읽은 칸이 옛 대조 완료 칸과 모두 같은가. {(서식, 줄): 참·거짓}, 줄 번호 1 부터(재리뷰 R-I1).
    견주는 것은 그 줄의 rule 칸 전부다. 란 집합과 값·글이 같아야 하고, 칸 하나라도 바뀌거나 빠지거나 새로 생기면 거짓이다.
    사람·AI 값 칸은 양쪽에서 뺀다(사람 값이 막은 파서 칸은 따로 확인사항이 된다). 옛 줄에 대조 전 칸이 있었으면(적재 앞머리에서
    지웠다) 새로 읽은 그 칸이 옛 쪽에 없어 거짓이다. 부분 대조 줄을 물려받지 않는다(§7 B3 '부분 대조 줄')."""
    new_rows, old_rows = {}, {}
    for c in cells:
        o = kept.get((c.form_code, c.item_code, c.row_no))
        if c.row_no >= 1 and (o is None or o["source_kind"] == "rule"):
            new_rows.setdefault((c.form_code, c.row_no), {})[c.item_code] = (c.value, c.text or None)
    for (fc, code, row), o in kept.items():
        if row >= 1 and o["status"] == "approved" and o["source_kind"] == "rule":
            old_rows.setdefault((fc, row), {})[code] = (o["value"], o["text"] or None)
    return {k: new_rows.get(k) == v for k, v in old_rows.items()}


def _differs(row, c: Cell) -> bool:
    """사람이 넣은 행과 다시 읽은 칸이 다른가. 키인은 금액이나 글 하나만 쓰므로(cells.set_prior_value) 읽은 칸이 금액이면
    금액을, 글이면 글을 견준다."""
    if c.value is not None:
        return row["value"] is None or float(row["value"]) != float(c.value)
    return (row["text"] or None) != (c.text or None)


# ---------------------------------------------------------------- 적재

def find_prior_pdf(folder, fy_start: str) -> Path | None:
    """입력 폴더에서 전기(당기 개시 연도의 앞 해) 세무조정계산서 PDF."""
    p = Path(folder) / f"FY{int(fy_start[:4]) - 1}_법인세세무조정계산서.pdf"
    return p if p.exists() else None


def _canonical(form_code: str, item_code: str) -> str:
    """란 코드를 서식 정의의 정본 코드로(Form.find(code).code). 정의나 란이 없으면 그대로(정의에 없는 코드는 파서가 확인사항을
    낸다)."""
    form = form_def(form_code)
    it = form.find(str(item_code)) if form is not None else None
    return it.code if it is not None else str(item_code)


def _canonical_cells(cells: list) -> list:
    """파서가 읽은 값의 란 코드를 정본으로 바꾼다(B1 최종 리뷰 M3). 란 별칭(3호 옛 번호 101 = 01, std_re 27_2 = 27_r2)으로 읽은
    값을 그대로 쓰면 탭 3 전기 확인의 수정·다시 계산이 정본 코드로 찾아 같은 란에 둘째 행이 생기거나 값이 안 보인다. 바꾼 뒤 같은 란이
    둘이면(별칭과 정본으로 두 번 읽음) 파서 잘못이라 ValueError 로 멈춘다."""
    out, seen = [], {}
    for c in cells:
        code = _canonical(c.form_code, c.item_code)
        key = (c.form_code, code, c.row_no)
        if key in seen:
            raise ValueError(f"전기 PDF 파서가 한 란 {c.form_code}.{code} 을 두 번 읽었다({seen[key]}, {c.item_code}). 파서는"
                             " 란 하나를 한 번만, 정본 코드로 낸다")
        seen[key] = c.item_code
        out.append(c if code == c.item_code else replace(c, item_code=code))
    return out


def read_cells(pages: list[dict]) -> tuple[list, list]:
    """쪽 목록(split_pages)에서 코드 서식·격자 서식 값을 읽어 정본 란 코드로 바꾼 (Cell 목록, Problem 목록). DB 에 쓰지 않는다
    (분석적 검토 AR 엔진의 전기 구조 측정이 쓴다, engine.ar.prior_profile.from_pages)."""
    cells, problems = _parse_pages(pages)
    return _canonical_cells(cells), problems
