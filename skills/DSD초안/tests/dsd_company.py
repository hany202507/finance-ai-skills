"""회사 dsd 꼴 합성 시험 자료(2026-10-26, DSD 네 기능 설계 7절 순서 0). 회사 · 사람 · 금액은 모두 가상이다.

엔진이 만든 dsd(tests/dsd_fixture.py, make_demo_dart.py)에는 없는 회사 편집기 파일의 꼴을 넣었다:
DOCUMENT-HEADER 요약 코드, 정오표 INSERTION, COVER(회사명 칸 안 줄바꿈 &cr;, 기간 TU, 주소 표 ROWSPAN), TOC,
감사보고서 절(수신인 · 서명 테두리 없는 표, 굵은 SPAN 소제목이 든 P), 재무제표(재무상태표는 FINANCE, 나머지는 회사가 일반 표로 만든
과목 · 주석 · 내역 · 합계 여섯 칸), 주석(제목과 본문이 한 P 안에 &cr; 와 SPAN 으로 이어진 꼴, 여러 줄 머리줄 ROWSPAN · COLSPAN,
괄호 음수 · 「-」, 외화 글자가 붙은 칸, 테두리 없는 숫자 표, 오른쪽 「(단위 : 원)」 한 칸 표), 외부감사 실시내용(EXTRACTION 표).

    make_company_dsd(path)                      당기 보고서(제 5 기, 2025년)
    make_company_dsd(path, year=-1)             작년 보고서(제 4 기). 그 당기 열이 당기 보고서 전기 열과 같다
    make_company_dsd(path, cash_bank="1,250,000")   칸 하나만 다른 판(현금 주석과 재무상태표 같이 바뀜)

판을 바꾸는 열쇠는 BASE 에 있다. 판 비교 시험(test_dsd_versions.py)이 이 열쇠로 v1 · v2 를 만든다.
"""
from __future__ import annotations

import zipfile
from pathlib import Path

NAME = "누리정밀(가상)"
BASE = dict(
    year=0,
    cash_bank=None,            # 현금 주석 「보통예금」 당기말(재무상태표 현금및현금성자산 · 합계도 따라 바뀐다)
    ppe_extra_row=False,       # 유형자산 변동 표에 「구축물」 줄을 더한다
    split_ppe=False,           # 유형자산 변동 표를 당기 · 전기 두 표로 나눈다
    insert_note=False,         # 주석 2 뒤에 「3. 공정가치」 를 끼워 뒤 주석 번호가 하나씩 밀린다
    drop_note=False,           # 마지막 주석(특수관계자)을 뺀다
    retitle_note=False,        # 「4. 매출채권」 제목을 「4. 매출채권 및 기타채권」 으로 고친다(insert_note 와 같이 쓰면 번호도 밀린다)
    para=None,                 # 주석 1 본문 첫 문장
    add_col=False,             # 매출채권 표에 「전전기말」 열을 더한다
    swap_paras=False,          # 주석 1 의 문단 둘 순서를 바꾼다
    report_date="2026년 3월 14일",
    ext_hours=None,            # 외부감사 실시내용 감사시간(담당이사)
    cover_ceo="대표이사 김 하 늘",
    head_text=None,            # 매출채권 표 머리줄 「당기말」 칸 글자
    fx_text=None,              # 외화 표 「USD 12,000」 칸 글자
)

CR = "&amp;cr;"


def _y(year: int) -> int:
    return 2025 + year


# 금액은 (당기, 전기, 전전기). year=-1 이면 뒤의 둘을 쓴다
CASH = [("현금", "50,000", "40,000", "30,000"), ("보통예금", "1,200,000", "960,000", "700,000"), ("외화예금", "150,000", "100,000", "70,000")]
AR = [("매출채권", "3,100,000", "2,700,000", "2,300,000"), ("손실충당금", "(100,000)", "(80,000)", "(60,000)")]
PPE_CUR = [["토지", "2,000,000", "-", "-", "-", "2,000,000"],
           ["건물", "1,500,000", "-", "-", "(50,000)", "1,450,000"],
           ["기계장치", "800,000", "300,000", "(20,000)", "(130,000)", "950,000"]]
PPE_PRI = [["토지", "2,000,000", "-", "-", "-", "2,000,000"],
           ["건물", "1,550,000", "-", "-", "(50,000)", "1,500,000"],
           ["기계장치", "700,000", "220,000", "-", "(120,000)", "800,000"]]
PPE_PRI2 = [["토지", "1,800,000", "200,000", "-", "-", "2,000,000"],
            ["건물", "1,600,000", "-", "-", "(50,000)", "1,550,000"],
            ["기계장치", "650,000", "150,000", "-", "(100,000)", "700,000"]]


def _num(s: str) -> int:
    s = s.replace(",", "")
    if s in ("-", ""):
        return 0
    return -int(s[1:-1]) if s.startswith("(") else int(s)


def _fmt(v: int) -> str:
    if v == 0:
        return "-"
    return f"({-v:,})" if v < 0 else f"{v:,}"


def _pick(row, year):
    return (row[-3], row[-2]) if year == 0 else (row[-2], row[-1])


def _td(text="", tag="TD", **a) -> str:
    attrs = "".join(f' {k}="{v}"' for k, v in a.items())
    return f"<{tag}{attrs}>{text}</{tag}>"


def _tr(cells: list[str], copy="Y") -> str:
    return f'<TR ACOPY="{copy}" ADELETE="{copy}" HEIGHT="30">' + "".join(cells) + "</TR>"


def _unit_right() -> str:
    """회사 파일의 단위 줄: 오른쪽 정렬 한 칸 테두리 없는 표."""
    return ('<TABLE ACLASS="NORMAL" AFIXTABLE="N" BORDER="0" WIDTH="600"><COLGROUP WIDTH="600"><COL WIDTH="600"></COL></COLGROUP><TBODY>'
            + _tr([_td("(단위 : 원)", ALIGN="RIGHT", WIDTH="591", HEIGHT="23")]) + "</TBODY></TABLE>")


def _head(cells: list[str]) -> str:
    return "<THEAD>" + _tr([_td(c, "TH", ACOPYCOL="Y", ADELETECOL="Y", AMOVECOL="N", VALIGN="MIDDLE") for c in cells]) + "</THEAD>"


def _grid(header: list[str], rows: list[list[str]], head_xml: str | None = None) -> str:
    cols = len(header)
    body = "".join(_tr([_td(c, ALIGN="RIGHT" if j else "LEFT", VALIGN="MIDDLE") for j, c in enumerate(r)]) for r in rows)
    return (f'<TABLE ACLASS="NORMAL" AFIXTABLE="N" BORDER="1" WIDTH="600"><COLGROUP WIDTH="600">' + '<COL WIDTH="100"></COL>' * cols + "</COLGROUP>"
            + (head_xml or _head(header)) + f"<TBODY>{body}</TBODY></TABLE>")


def _note_p(n: int, title: str, body: str) -> str:
    """주석 제목과 본문이 한 P 에 이어진 회사 파일 꼴."""
    return f'<P USERMARK="B">{CR}{n}. {title}{CR}{CR}<SPAN USERMARK="!B">{body}</SPAN></P>'


# ---------------------------------------------------------------- 표지 · 감사보고서
def _cover(v: dict) -> str:
    y = _y(v["year"])
    n = 5 + v["year"]
    period = ('<TABLE-GROUP ACLASS="COVER" ADELETETABLE="N"><TABLE ACLASS="EXTRACTION" AFIXTABLE="Y" WIDTH="600" BORDER="0">'
              '<COLGROUP WIDTH="600"><COL WIDTH="342"></COL><COL WIDTH="258"></COL></COLGROUP><TBODY>'
              + _tr([_td(f"제 {n} 기", CLASS="NORMAL", COLSPAN="2", ALIGN="CENTER", USERMARK="F-BT14 ")], "N")
              + _tr([_td(f"{y}년 01월 01일", "TU", CLASS="NORMAL", ALIGN="RIGHT", AUNIT="PERIODFROM", AUNITVALUE=f"{y}0101"), _td("부터", CLASS="NORMAL", AUPDATECONT="N")], "N")
              + _tr([_td(f"{y}년 12월 31일", "TU", CLASS="NORMAL", ALIGN="RIGHT", AUNIT="PERIODTO", AUNITVALUE=f"{y}1231"), _td("까지", CLASS="NORMAL", AUPDATECONT="N")], "N")
              + "</TBODY></TABLE></TABLE-GROUP>")
    prior = ('<TABLE ACLASS="NORMAL" AFIXTABLE="N" BORDER="0" WIDTH="600"><COLGROUP WIDTH="600"><COL WIDTH="342"></COL><COL WIDTH="258"></COL></COLGROUP><TBODY>'
             + _tr([_td(f"제 {n - 1} 기", COLSPAN="2", ALIGN="CENTER", USERMARK="F-BT14 ")])
             + _tr([_td(f"{y - 1}년 01월 01일", ALIGN="RIGHT"), _td("부터")]) + _tr([_td(f"{y - 1}년 12월 31일", ALIGN="RIGHT"), _td("까지")])
             + "</TBODY></TABLE>")
    addr = ('<TABLE ACLASS="NORMAL" AFIXTABLE="Y" BORDER="0" WIDTH="600"><COLGROUP WIDTH="600"><COL WIDTH="100"></COL><COL WIDTH="108"></COL><COL WIDTH="392"></COL></COLGROUP><TBODY>'
            + _tr([_td("본점 소재지 : ", ROWSPAN="2", AUPDATECONT="N", ALIGN="RIGHT"), _td("(도로명주소)", AUPDATECONT="N"), _td("경기도 가상시 미래로 10")], "N")
            + _tr([_td("(전   화)", AUPDATECONT="N"), _td("031-000-0000")], "N")
            + "</TBODY></TABLE>")
    return ('<COVER><P>' + CR + '</P>'
            '<TABLE ACLASS="NORMAL" AFIXTABLE="N" BORDER="0" WIDTH="600"><COLGROUP WIDTH="600"><COL WIDTH="600"></COL></COLGROUP><TBODY>'
            + _tr([_td(f"주식회사 누리정밀{CR}(가상)", ALIGN="CENTER", USERMARK="F-BT18 ")]) + "</TBODY></TABLE>"
            f'<P>{CR}{CR}</P><P USERMARK="F-18  A-C">재 무 제 표 에 대 한</P><COVER-TITLE ATOC="Y" ATOCID="1">감   사   보   고   서</COVER-TITLE><P>{CR}{CR}{CR}</P>'
            + period + "<P></P>" + prior + f"<P>{CR}{CR}</P>"
            + '<TABLE ACLASS="NORMAL" AFIXTABLE="N" BORDER="0" WIDTH="600"><COLGROUP WIDTH="600"><COL WIDTH="600"></COL></COLGROUP><TBODY>'
            + _tr([_td(f"{NAME}", ALIGN="CENTER")]) + "</TBODY></TABLE>"
            + addr + "</COVER>")


def _report(v: dict) -> str:
    y = _y(v["year"])
    recv = ('<TABLE ACLASS="NORMAL" AFIXTABLE="N" WIDTH="600" BORDER="0"><COLGROUP WIDTH="600"><COL WIDTH="374"></COL><COL WIDTH="226"></COL></COLGROUP><TBODY>'
            + _tr([_td(f"주식회사 누리정밀(가상)"), _td("")]) + _tr([_td("주주 및 이사회 귀중"), _td("", ALIGN="RIGHT")]) + "</TBODY></TABLE>")
    body = (f'<P USERMARK="B">감사의견{CR}</P>'
            f"<P>우리는 주식회사 누리정밀(가상)(이하 &quot;회사&quot;)의 재무제표를 감사하였습니다. 해당 재무제표는 {y}년 12월 31일 현재의 재무상태표, "
            f"동일로 종료되는 보고기간의 손익계산서, 자본변동표, 현금흐름표 그리고 중요한 회계정책 정보를 포함한 재무제표의 주석으로 구성되어 있습니다.{CR}{CR}"
            f"우리의 의견으로는 별첨된 회사의 재무제표는 회사의 {y}년 12월 31일 현재의 재무상태와 동일로 종료되는 보고기간의 재무성과 및 현금흐름을 "
            f"일반기업회계기준에 따라, 중요성의 관점에서 공정하게 표시하고 있습니다.{CR}{CR}"
            f'<SPAN USERMARK="B">감사의견근거{CR}</SPAN>{CR}우리는 대한민국의 회계감사기준에 따라 감사를 수행하였습니다.{CR}{CR}'
            f'<SPAN USERMARK="B">재무제표에 대한 경영진과 지배기구의 책임{CR}</SPAN>{CR}경영진은 일반기업회계기준에 따라 이 재무제표를 작성하고 공정하게 표시할 책임이 있습니다.</P>')
    sign = ('<TABLE WIDTH="600" ACLASS="NORMAL" AFIXTABLE="N" BORDER="0"><COLGROUP WIDTH="600"><COL WIDTH="600"></COL></COLGROUP><TBODY>'
            + _tr([_td("서울특별시 가상구 감사로 1", ALIGN="RIGHT")]) + _tr([_td("한  빛  회  계  법  인(가상)", ALIGN="RIGHT")])
            + _tr([_td("대 표 이 사  이 가 상", ALIGN="RIGHT")]) + _tr([_td(v["report_date"], ALIGN="RIGHT")]) + "</TBODY></TABLE>")
    valid = ('<TABLE BORDER="1" WIDTH="600" ACLASS="NORMAL" AFIXTABLE="N"><COLGROUP WIDTH="600"><COL WIDTH="600"></COL></COLGROUP><TBODY>'
             + _tr([_td("이 감사보고서는 감사보고서일 현재로 유효한 것입니다. 따라서 감사보고서일 후 이 보고서를 열람하는 시점 사이에 "
                        "첨부된 회사의 재무제표에 중요한 영향을 미칠 수 있는 사건이나 상황이 발생할 수도 있습니다.")]) + "</TBODY></TABLE>")
    return ('<SECTION-1 ACLASS="MANDATORY" APARTSOURCE="SOURCE"><TITLE ATOC="Y" ATOCID="2">독립된 감사인의 감사보고서</TITLE><P></P>'
            + recv + "<P></P>" + body + sign + "<P></P>" + valid + "<PGBRK></PGBRK></SECTION-1>")


# ---------------------------------------------------------------- 재무제표
def _amounts(v: dict) -> dict:
    y = v["year"]
    cash = [(r[0], *_pick(r, y)) for r in CASH]
    if v["cash_bank"] and y == 0:
        cash[1] = (cash[1][0], v["cash_bank"], cash[1][2])
    ar = [(r[0], *_pick(r, y)) for r in AR]
    ppe = PPE_CUR if y == 0 else PPE_PRI
    ppe_pri = PPE_PRI if y == 0 else PPE_PRI2
    out = {"cash": cash, "ar": ar, "ppe": ppe, "ppe_pri": ppe_pri}
    out["cash_t"] = (sum(_num(c[1]) for c in cash), sum(_num(c[2]) for c in cash))
    out["ar_t"] = (sum(_num(c[1]) for c in ar), sum(_num(c[2]) for c in ar))
    out["ppe_t"] = (sum(_num(r[5]) for r in ppe), sum(_num(r[5]) for r in ppe_pri))
    return out


def _bs(v: dict, a: dict) -> str:
    n = 5 + v["year"]
    cash, ar, ppe = a["cash_t"], a["ar_t"], a["ppe_t"]
    cur = (cash[0] + ar[0], cash[1] + ar[1])
    tot = (cur[0] + ppe[0], cur[1] + ppe[1])
    debt = (2_000_000, 1_900_000) if v["year"] == 0 else (1_900_000, 1_800_000)
    cap = (3_000_000, 3_000_000)
    re_ = (tot[0] - debt[0] - cap[0], tot[1] - debt[1] - cap[1])
    rows = [("자산", 0, None, None, False, ""), ("Ⅰ. 유동자산", 0, cur[0], cur[1], False, ""),
            ("현금및현금성자산", 1, cash[0], cash[1], True, "5"), ("매출채권", 1, ar[0], ar[1], True, "4"),
            ("Ⅱ. 비유동자산", 0, ppe[0], ppe[1], False, ""), ("유형자산", 1, ppe[0], ppe[1], True, "6"),
            ("자산총계", 0, tot[0], tot[1], False, ""), ("부채", 0, None, None, False, ""),
            ("Ⅰ. 유동부채", 0, debt[0], debt[1], False, ""), ("매입채무", 1, debt[0], debt[1], True, ""),
            ("부채총계", 0, debt[0], debt[1], False, ""), ("자본", 0, None, None, False, ""),
            ("Ⅰ. 자본금", 0, cap[0], cap[1], False, "7"), ("Ⅱ. 이익잉여금", 0, re_[0], re_[1], False, ""),
            ("자본총계", 0, cap[0] + re_[0], cap[1] + re_[1], False, ""), ("부채와자본총계", 0, tot[0], tot[1], False, "")]
    trs = []
    for lab, lv, c, p, inner, note in rows:
        cells = [lab, note, _fmt(c) if inner and c is not None else "", "" if inner or c is None else _fmt(c),
                 _fmt(p) if inner and p is not None else "", "" if inner or p is None else _fmt(p)]
        trs.append(_tr([_td(x, "TE", ACODE="1", ADELIM=str(i), **({"ALEVEL": str(lv)} if i == 0 else {})) for i, x in enumerate(cells)]))
    return ('<TABLE ACLASS="FINANCE" BORDER="1" WIDTH="600"><COLGROUP WIDTH="600">' + '<COL WIDTH="100"></COL>' * 6 + "</COLGROUP>"
            f'<THEAD><TR ACOPY="N" ADELETE="N"><TH>과 목</TH><TH>주석</TH><TH COLSPAN="2">제 {n} (당) 기말</TH><TH COLSPAN="2">제 {n - 1} (전) 기말</TH></TR></THEAD>'
            f"<TBODY>{''.join(trs)}</TBODY></TABLE>"), {"tot": tot, "re": re_}


def _six(n: int, rows: list[tuple], period="기") -> str:
    """회사가 일반 표로 만든 재무제표: 과목 · 주석 · 당기 내역 · 당기 합계 · 전기 내역 · 전기 합계."""
    head = ("<THEAD>" + _tr([_td("과 목", "TH", ROWSPAN="2"), _td("주석", "TH", ROWSPAN="2"), _td(f"제 {n} (당) {period}", "TH", COLSPAN="2"),
                             _td(f"제 {n - 1} (전) {period}", "TH", COLSPAN="2")])
            + _tr([_td("금 액", "TH", COLSPAN="2"), _td("금 액", "TH", COLSPAN="2")]) + "</THEAD>")
    body = []
    for lab, note, c, p, inner in rows:
        cells = [lab, note, _fmt(c) if inner else "", "" if inner else _fmt(c), _fmt(p) if inner else "", "" if inner else _fmt(p)]
        body.append(_tr([_td(x, ALIGN="RIGHT" if j > 1 else ("CENTER" if j == 1 else "LEFT")) for j, x in enumerate(cells)]))
    return ('<TABLE ACLASS="NORMAL" AFIXTABLE="N" BORDER="1" WIDTH="600"><COLGROUP WIDTH="600">' + '<COL WIDTH="100"></COL>' * 6 + "</COLGROUP>"
            + head + "<TBODY>" + "".join(body) + "</TBODY></TABLE>")


# 해마다의 값(작년 판의 당기 열 = 당기 판의 전기 열이 되게)
SALES = {2025: 10_000_000, 2024: 9_000_000, 2023: 8_000_000}
COGS = {2025: 7_000_000, 2024: 6_500_000, 2023: 6_000_000}
RE = {2023: 2_490_000, 2022: 2_290_000}                     # 재무상태표에 없는 해의 이익잉여금
CASH_T = {2023: 800_000, 2022: 600_000}
DEP = {2025: 180_000, 2024: 170_000, 2023: 150_000}
INV = {2025: -280_000, 2024: -220_000, 2023: -350_000}


def _is(v: dict, ni: tuple) -> str:
    n = 5 + v["year"]
    y = _y(v["year"])
    sales = (SALES[y], SALES[y - 1])
    cogs = (COGS[y], COGS[y - 1])
    gp = (sales[0] - cogs[0], sales[1] - cogs[1])
    sga = (gp[0] - ni[0], gp[1] - ni[1])
    rows = [("Ⅰ. 매출액", "", sales[0], sales[1], False), ("Ⅱ. 매출원가", "", cogs[0], cogs[1], False), ("Ⅲ. 매출총이익", "", gp[0], gp[1], False),
            ("Ⅳ. 판매비와관리비", "", sga[0], sga[1], False), ("Ⅴ. 당기순이익", "", ni[0], ni[1], False)]
    return _six(n, rows)


def _sce(v: dict, re_: tuple) -> str:
    y = _y(v["year"])
    ni = re_[0] - re_[1]
    rows = [[f"{y}.01.01 (당기초)", "3,000,000", _fmt(re_[1]), _fmt(3_000_000 + re_[1])],
            ["당기순이익", "-", _fmt(ni), _fmt(ni)],
            [f"{y}.12.31 (당기말)", "3,000,000", _fmt(re_[0]), _fmt(3_000_000 + re_[0])]]
    return _grid(["과 목", "자본금", "이익잉여금", "총 계"], rows)


def _cf(v: dict, a: dict, ni: tuple) -> str:
    n = 5 + v["year"]
    y = _y(v["year"])
    cash = a["cash_t"]
    before = CASH_T[y - 2]
    dep = (DEP[y], DEP[y - 1])
    inv = (INV[y], INV[y - 1])
    inc = (cash[0] - cash[1], cash[1] - before)
    op = (inc[0] - inv[0], inc[1] - inv[1])
    wc = (op[0] - ni[0] - dep[0], op[1] - ni[1] - dep[1])
    rows = [("Ⅰ. 영업활동현금흐름", "", op[0], op[1], False), ("당기순이익", "", ni[0], ni[1], True), ("감가상각비", "", dep[0], dep[1], True),
            ("운전자본의 변동", "", wc[0], wc[1], True), ("Ⅱ. 투자활동현금흐름", "", inv[0], inv[1], False), ("Ⅲ. 현금의 증가", "", inc[0], inc[1], False),
            ("Ⅳ. 기초의 현금", "", cash[1], before, False), ("Ⅴ. 기말의 현금", "5", cash[0], cash[1], False)]
    return _six(n, rows)


def _fs(v: dict, a: dict) -> tuple[str, dict]:
    bs, bsx = _bs(v, a)
    y = _y(v["year"])
    re_pp = RE.get(y - 2)
    if re_pp is None:                                    # 당기 판: 전전기 이익잉여금은 작년 판 재무상태표의 전기 값
        re_pp = _bs(dict(v, year=v["year"] - 1, cash_bank=None), _amounts(dict(v, year=v["year"] - 1, cash_bank=None)))[1]["re"][1]
    ni = (bsx["re"][0] - bsx["re"][1], bsx["re"][1] - re_pp)

    def group(cls, title, table, lib):
        return (f'<INSERTION ABASISNUMBER="{lib}" AFREQUENCY="1" ADUPLICATION="N"><LIBRARYLIST>00760#*{title}.dsl</LIBRARYLIST>'
                f'<LIBRARY><TABLE-GROUP ACLASS="{cls}"><TITLE ATOC="N">{title}</TITLE><P USERMARK="F-14 B"></P>{_unit_right()}{table}</TABLE-GROUP></LIBRARY></INSERTION>')

    return ('<SECTION-1 ACLASS="MANDATORY"><TITLE ATOC="Y" ATOCID="3">(첨부)재 무 제 표</TITLE>'
            + group("BS", "재 무 상 태 표", bs, "FS1") + group("IS", "손 익 계 산 서", _is(v, ni), "FS2")
            + group("CE", "자 본 변 동 표", _sce(v, bsx["re"]), "FS3") + group("CF", "현 금 흐 름 표", _cf(v, a, ni), "FS4")
            + '<TABLE ACLASS="NORMAL" AFIXTABLE="N" BORDER="0" WIDTH="600"><COLGROUP WIDTH="600"><COL WIDTH="600"></COL></COLGROUP><TBODY>'
            + _tr([_td("별첨 주석은 본 재무제표의 일부입니다.", ALIGN="CENTER")]) + "</TBODY></TABLE><P></P><PGBRK></PGBRK>"), bsx


# ---------------------------------------------------------------- 주석
def _ppe_tables(v: dict, a: dict) -> str:
    head = ["구 분", "기초", "취득", "처분", "감가상각비", "기말"]
    cur, pri = [list(r) for r in a["ppe"]], [list(r) for r in a["ppe_pri"]]

    def total(rows):
        return ["합 계"] + [_fmt(sum(_num(r[j]) for r in rows)) for j in range(1, 6)]

    if v["ppe_extra_row"]:
        cur.insert(2, ["구축물", "-", "-", "-", "-", "-"])
    if v["split_ppe"]:
        return (f"<P>(1) 당기 중 유형자산의 변동내역은 다음과 같습니다.</P>{_unit_right()}" + _grid(head, cur + [total(cur)])
                + f"<P>(2) 전기 중 유형자산의 변동내역은 다음과 같습니다.</P>{_unit_right()}" + _grid(head, pri + [total(pri)]))
    # 당기 · 전기를 한 표에 위아래로 둔 꼴. 첫 열이 ROWSPAN 으로 묶여 있다
    rows = []
    for tag, part in (("당기", cur), ("전기", pri)):
        for k, r in enumerate(part + [total(part)]):
            first = _td(tag, ROWSPAN=str(len(part) + 1), VALIGN="MIDDLE") if k == 0 else ""
            rows.append(_tr(([first] if first else []) + [_td(c, ALIGN="RIGHT" if j else "LEFT") for j, c in enumerate(r)]))
    return (f"<P>(1) 당기와 전기 중 유형자산의 변동내역은 다음과 같습니다.</P>{_unit_right()}"
            '<TABLE ACLASS="NORMAL" AFIXTABLE="N" BORDER="1" WIDTH="600"><COLGROUP WIDTH="600">' + '<COL WIDTH="86"></COL>' * 7 + "</COLGROUP>"
            + _head(["기간"] + head) + "<TBODY>" + "".join(rows) + "</TBODY></TABLE>")


def _notes(v: dict, a: dict) -> str:
    y = _y(v["year"])
    out = []
    k = 0

    def num() -> int:
        nonlocal k
        k += 1
        return k

    first = v["para"] or f"주식회사 누리정밀(가상)(이하 &quot;회사&quot;)은 {y - 5}년 3월 설립되어 정밀 부품의 제조 및 판매를 주요 사업으로 하고 있습니다."
    second = "회사의 본점은 경기도 가상시 미래로 10 에 있습니다."
    paras = [second, first] if v["swap_paras"] else [first, second]
    out.append(_note_p(num(), "회사의 개요", f"{paras[0]}{CR}{CR}{paras[1]}") + "<P></P>")
    # 주주 표: 테두리 있는 일반 표, % 칸
    out.append(_grid(["주주명", "주식수", "지분율"], [["김하늘(가상)", "400,000", "66.67%"], ["기타", "200,000", "33.33%"], ["합 계", "600,000", "100.00%"]]))
    out.append(_note_p(num(), "중요한 회계정책", f"회사의 재무제표는 일반기업회계기준에 따라 작성되었습니다.{CR}{CR}(1) 수익인식{CR}회사는 재화의 통제가 이전될 때 수익을 인식합니다."))
    if v["insert_note"]:
        out.append(_note_p(num(), "공정가치", "회사의 금융상품은 장부금액과 공정가치가 비슷합니다.")
                   + _unit_right() + _grid(["구 분", "장부금액", "공정가치"], [["매출채권", "3,000,000", "3,000,000"]]))
    out.append(_note_p(num(), "외화자산", "보고기간말 현재 외화자산의 내역은 다음과 같습니다."))
    fx = v["fx_text"] or "USD 12,000"
    out.append(_unit_right() + _grid(["구 분", "외화금액", "원화금액"], [["외화예금", fx, "150,000"]]))
    ar_title = "매출채권 및 기타채권" if v["retitle_note"] else "매출채권"
    out.append(_note_p(num(), ar_title, "보고기간말 현재 매출채권의 내역은 다음과 같습니다."))
    head = ["구 분", v["head_text"] or "당기말", "전기말"] + (["전전기말"] if v["add_col"] else [])
    ar_rows = [[r[0], r[1], r[2]] + (["1,000"] if v["add_col"] else []) for r in a["ar"]]
    ar_rows.append(["합 계", _fmt(a["ar_t"][0]), _fmt(a["ar_t"][1])] + (["1,000"] if v["add_col"] else []))
    out.append(_unit_right() + _grid(head, ar_rows))
    out.append(_note_p(num(), "현금및현금성자산", "보고기간말 현재 현금및현금성자산의 내역은 다음과 같습니다."))
    # 테두리 없는 숫자 표(회사 파일에 흔하다)
    rows = "".join(_tr([_td(r[0]), _td(r[1], ALIGN="RIGHT"), _td(r[2], ALIGN="RIGHT")]) for r in a["cash"])
    rows += _tr([_td("합 계"), _td(_fmt(a["cash_t"][0]), ALIGN="RIGHT"), _td(_fmt(a["cash_t"][1]), ALIGN="RIGHT")])
    out.append(_unit_right() + '<TABLE ACLASS="NORMAL" AFIXTABLE="N" BORDER="0" WIDTH="600"><COLGROUP WIDTH="600"><COL WIDTH="200"></COL><COL WIDTH="200"></COL><COL WIDTH="200"></COL></COLGROUP><TBODY>'
               + _tr([_td("구 분"), _td("당기말", ALIGN="CENTER"), _td("전기말", ALIGN="CENTER")]) + rows + "</TBODY></TABLE>")
    out.append(_note_p(num(), "유형자산", "") + _ppe_tables(v, a))
    out.append(_note_p(num(), "자본금", f"회사가 발행할 주식의 총수는 10,000,000주이며, 당기말 현재 발행한 주식수는 600,000주(1주당 금액 5,000원)입니다."))
    if not v["drop_note"]:
        out.append(_note_p(num(), "특수관계자", "회사의 최대주주는 김하늘(가상)입니다."))
    return '<SECTION-2 ACLASS="MANDATORY"><TITLE ATOC="Y" ATOCID="4">주석</TITLE>' + "".join(out) + "<PGBRK></PGBRK></SECTION-2>"


def _ext(v: dict) -> str:
    hours = v["ext_hours"] or "40"
    head = "<THEAD>" + _tr([_td("구분", "TH"), _td("담당이사", "TH"), _td("업무수행이사", "TH"), _td("합계", "TH")], "N") + "</THEAD>"
    body = (_tr([_td("투입인원수"), _td("1", "TE", ACODE="QLT_PCNT"), _td("2", "TE", ACODE="ACT_PCNT"), _td("3")], "N")
            + _tr([_td("감사시간"), _td(hours, "TE", ACODE="QLT_TIME"), _td("120", "TE", ACODE="ACT_TIME"), _td(f"{int(hours) + 120}")], "N"))
    return ('<SECTION-1 ACLASS="MANDATORY"><TITLE ATOC="Y" ATOCID="5">외부감사 실시내용</TITLE>'
            '<P USERMARK="B">1. 감사대상업무</P>'
            '<TABLE ACLASS="EXTRACTION" AFIXTABLE="Y" BORDER="1" WIDTH="600"><COLGROUP WIDTH="600"><COL WIDTH="150"></COL><COL WIDTH="150"></COL><COL WIDTH="150"></COL><COL WIDTH="150"></COL></COLGROUP>'
            + head + f"<TBODY>{body}</TBODY></TABLE></SECTION-1>")


def contents(**kw) -> str:
    v = dict(BASE, **kw)
    a = _amounts(v)
    fs, _ = _fs(v, a)
    return ('<?xml version="1.0" encoding="utf-8"?>\n\n\n<DOCUMENT xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:noNamespaceSchemaLocation="dart4.xsd">\n\n'
            '<DOCUMENT-HEADER AEXT-CLASS="Y">\n<DOCUMENT-NAME ACODE="00760">감사보고서</DOCUMENT-NAME>\n<FORMULA-VERSION ADATE="20221027">6.0</FORMULA-VERSION>\n'
            '<COMPANY-NAME AREGCIK="00000000" AACCOUNTTYPE="A">누리정밀(가상)</COMPANY-NAME>\n\n<SUMMARY>\n'
            '<EXTRACTION ACODE="AUDIT_CIK" AFEATURE="BOTH">00000001</EXTRACTION>\n<EXTRACTION ACODE="SUPV_OPIN" AFEATURE="BOTH">100000000000</EXTRACTION>\n'
            f'<EXTRACTION ACODE="TOT_ASSETS" AFEATURE="BOTH">{sum(a["cash_t"][:1]) + a["ar_t"][0] + a["ppe_t"][0]}</EXTRACTION>\n</SUMMARY>\n</DOCUMENT-HEADER>\n\n'
            '<BODY ATOCID="6">\n\n<INSERTION ABASISNUMBER="SE1" AFREQUENCY="0" ADUPLICATION="N">\n<COMMENT>◆click◆ 정정문서 작성시 『정오표』 삽입</COMMENT>\n'
            '<LIBRARYLIST>일반-정정*.LCommon</LIBRARYLIST>\n</INSERTION>\n\n'
            + _cover(v) + '\n<TOC></TOC>\n' + _report(v) + "\n" + fs + "\n" + _notes(v, a) + "</SECTION-1>\n" + _ext(v)
            + "\n</BODY>\n</DOCUMENT>\n")


def public_xml(**kw) -> str:
    """같은 내용을 OpenDART 공시서류원본 꼴로: 편집기 요소(INSERTION · LIBRARY · COMMENT · LIBRARYLIST)를 걷어 내고 머리 요소를 DOCUMENT 바로 아래로."""
    import xml.etree.ElementTree as ET

    root = ET.fromstring(contents(**kw).encode("utf-8"))

    def unwrap(e):
        out = []
        for c in list(e):
            if c.tag in ("COMMENT", "LIBRARYLIST"):
                continue
            if c.tag in ("INSERTION", "LIBRARY"):
                out.extend(unwrap(c))
                continue
            kids = unwrap(c)
            for k in list(c):
                c.remove(k)
            c.extend(kids)
            out.append(c)
        return out

    head = root.find("DOCUMENT-HEADER")
    body = root.find("BODY")
    new = ET.Element("DOCUMENT")
    new.extend([x for x in head if x.tag != "SUMMARY"])
    b = ET.SubElement(new, "BODY")
    b.extend(unwrap(body))
    return '<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(new, encoding="unicode")


def make_company_dsd(path: Path, **kw) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("contents.xml", contents(**kw))
        z.writestr("meta.xml", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<METAINFO><dart-ver>5.061</dart-ver></METAINFO>')
    return path
