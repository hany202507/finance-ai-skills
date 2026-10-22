"""시험용 합성 dsd(값은 모두 가상). 재무제표 넷과 주석 셋.

    make_dsd(path)                       당기 보고서(제 2 기). 열은 당기 · 전기
    make_dsd(path, year=-1)              작년 보고서(제 1 기). 그 당기 열이 위 보고서의 전기 열과 같다
    make_dsd(path, ppe_end_machine="181")   칸 하나만 다른 판

바꿀 수 있는 값은 BASE 의 열쇠다. extra 는 주석 절 끝에 그대로 붙일 XML 이다(주석을 더 넣을 때). 금액은 (당기, 전기, 전전기) 셋으로 적고 year 에 따라 앞 둘이나 뒤 둘을 쓴다.
"""
from __future__ import annotations

import zipfile
from pathlib import Path

BASE = dict(year=0, ppe_end_machine=None, ppe_total_end=None, bs_ppe=None, ar_total=None, ar_total_prior=None, extra_ppe_row=False, alevel=True, unit="원",
            extra="",
            para="회사는 2024년에 설립되어 정밀 부품을 제조합니다.")

# (과목, 단계, 안쪽 칸인지, 당기, 전기, 전전기). 금액이 없으면 머리 줄
BS = [("자산", 0, False, "", "", ""),
      ("Ⅰ.유동자산", 0, False, "600", "500", "400"),
      ("현금및현금성자산", 1, True, "100", "80", "30"),
      ("매출채권(주석3)", 1, True, "500", "420", "370"),
      ("Ⅱ.비유동자산", 0, False, "900", "800", "700"),
      ("유형자산(주석2)", 1, True, "900", "800", "700"),
      ("자산총계", 0, False, "1,500", "1,300", "1,100"),
      ("부채", 0, False, "", "", ""),
      ("Ⅰ.유동부채", 0, False, "400", "300", "200"),
      ("매입채무", 1, True, "400", "300", "200"),
      ("부채총계", 0, False, "400", "300", "200"),
      ("자본", 0, False, "", "", ""),
      ("Ⅰ.자본금", 0, False, "1,000", "1,000", "900"),
      ("Ⅱ.이익잉여금", 0, False, "100", "-", "-"),
      ("자본총계", 0, False, "1,100", "1,000", "900"),
      ("부채와자본총계", 0, False, "1,500", "1,300", "1,100")]
IS = [("Ⅰ.매출액", 0, False, "2,000", "1,800", "1,600"),
      ("Ⅱ.매출원가", 0, False, "1,500", "1,400", "1,300"),
      ("Ⅲ.매출총이익", 0, False, "500", "400", "300"),
      ("Ⅳ.판매비와관리비", 0, False, "400", "400", "300"),
      ("감가상각비", 1, True, "88", "80", "70"),
      ("기타", 1, True, "312", "320", "230"),
      ("Ⅴ.당기순이익", 0, False, "100", "-", "-")]
CF = [("Ⅰ.영업활동으로 인한 현금흐름", 0, False, "208", "150", "100"),
      ("당기순이익", 1, True, "100", "-", "-"),
      ("감가상각비", 1, True, "88", "80", "70"),
      ("운전자본의 변동", 1, True, "20", "70", "30"),
      ("Ⅱ.투자활동으로 인한 현금흐름", 0, False, "(188)", "(100)", "(90)"),
      ("Ⅲ.현금의 증가", 0, False, "20", "50", "10"),
      ("Ⅳ.기초의 현금", 0, False, "80", "30", "20"),
      ("Ⅴ.기말의 현금", 0, False, "100", "80", "30")]
AR = [("매출채권", "520", "440", "390"), ("대손충당금", "(20)", "(20)", "(20)"), ("합 계", "500", "420", "370")]
UNIT = '<TABLE BORDER="0"><TBODY><TR><TD>(단위 : {unit})</TD></TR></TBODY></TABLE>'


def _pick(row, year):
    """(당기, 전기) 두 값. year 가 -1 이면 한 해 앞의 것."""
    return (row[-3], row[-2]) if year == 0 else (row[-2], row[-1])


def _fin_table(head, rows, year, alevel, over=None):
    over = over or {}
    out = []
    for lab, lv, inner, *_ in rows:
        cur, pri = _pick((lab, lv, inner, *_), year)
        cur = over.get(lab, cur)
        cells = (lab, cur, "", pri, "") if inner else (lab, "", cur, "", pri)
        lvl = f' ALEVEL="{lv}"' if alevel else ""
        out.append("<TR>" + "".join(f'<TE ACODE="1" ADELIM="{i}"{lvl if i == 0 else ""}>{v}</TE>' for i, v in enumerate(cells)) + "</TR>")
    return ('<TABLE ACLASS="FINANCE" BORDER="1"><THEAD><TR><TH>과 목</TH>'
            f'<TH COLSPAN="2">{head[0]}</TH><TH COLSPAN="2">{head[1]}</TH></TR></THEAD>'
            f"<TBODY>{''.join(out)}</TBODY></TABLE>")


def _table(header, rows):
    th = "".join(f"<TH>{h}</TH>" for h in header)
    body = "".join("<TR>" + "".join(f"<TD>{c}</TD>" for c in r) + "</TR>" for r in rows)
    return f'<TABLE ACLASS="NORMAL" BORDER="1"><THEAD><TR>{th}</TR></THEAD><TBODY>{body}</TBODY></TABLE>'


def contents(**kw) -> str:
    v = dict(BASE, **kw)
    y = v["year"]
    n = 2 + y                                    # 기수
    bs_over = {"Ⅱ.비유동자산": v["bs_ppe"], "유형자산(주석2)": v["bs_ppe"]} if v["bs_ppe"] else {}
    bs = _fin_table((f"제 {n} (당) 기말", f"제 {n - 1} (전) 기말"), BS, y, v["alevel"], bs_over)
    is_ = _fin_table((f"제 {n} (당) 기", f"제 {n - 1} (전) 기"), IS, y, v["alevel"])
    cf = _fin_table((f"제 {n} (당) 기", f"제 {n - 1} (전) 기"), CF, y, v["alevel"])
    a, b = ("1,000", "100") if y == 0 else ("1,000", "-")
    total = "1,100" if y == 0 else "1,000"
    sce = ('<TABLE ACLASS="FINANCE" BORDER="1"><THEAD><TR><TH>과 목</TH><TH>자 본 금</TH><TH>이익잉여금</TH><TH>총 계</TH></TR></THEAD><TBODY>'
           f'<TR><TE>{2025 + y}.1.1(당기초)</TE><TE>1,000</TE><TE>-</TE><TE>1,000</TE></TR>'
           f'<TR><TE>당기순이익</TE><TE>-</TE><TE>{b}</TE><TE>{b}</TE></TR>'
           f'<TR><TE>{2025 + y}.12.31(당기말)</TE><TE>{a}</TE><TE>{b}</TE><TE>{total}</TE></TR></TBODY></TABLE>')
    if y == 0:
        ppe_rows = [["토지", "300", "-", "-", "300"], ["건물", "400", "50", "(30)", "420"],
                    ["기계장치", "100", "138", "(58)", v["ppe_end_machine"] or "180"]]
        ppe_total = ["합 계", "800", "188", "(88)", v["ppe_total_end"] or "900"]
    else:
        ppe_rows = [["토지", "300", "-", "-", "300"], ["건물", "350", "70", "(20)", "400"], ["기계장치", "50", "110", "(60)", "100"]]
        ppe_total = ["합 계", "700", "180", "(80)", "800"]
    if v["extra_ppe_row"]:
        ppe_rows.insert(1, ["구축물", "-", "-", "-", "-"])
    ppe = _table(["구 분", "기초", "취득", "감가상각비", "기말"], ppe_rows + [ppe_total])
    ar_rows = [[r[0], *_pick(r, y)] for r in AR]
    if v["ar_total"]:
        ar_rows[-1][1] = v["ar_total"]
    if v["ar_total_prior"]:
        ar_rows[-1][2] = v["ar_total_prior"]
    ar = _table(["구 분", "당기말", "전기말"], ar_rows)

    unit = UNIT.format(unit=v["unit"])

    def group(title, table):
        return f'<TABLE-GROUP><TITLE>{title}</TITLE>{unit}{table}</TABLE-GROUP>'

    return ('<?xml version="1.0" encoding="utf-8"?>\n<DOCUMENT><BODY>'
            '<SECTION-1 ACLASS="MANDATORY"><TITLE ATOC="Y">(첨부)재 무 제 표</TITLE>'
            + group("재 무 상 태 표", bs) + group("손 익 계 산 서", is_) + group("자 본 변 동 표", sce) + group("현 금 흐 름 표", cf)
            + '<SECTION-2 ACLASS="MANDATORY"><TITLE ATOC="Y">주석</TITLE>'
            f'<P USERMARK="B">1. 회사의 개요</P><P>{v["para"]}</P>'
            '<P USERMARK="B">2. 유형자산</P><P>(1) 당기 중 유형자산의 변동내역은 다음과 같습니다.</P>' + unit + ppe
            + '<P USERMARK="B">3. 매출채권</P><P>보고기간말 현재 매출채권의 내역은 다음과 같습니다.</P>' + unit + ar
            + v["extra"] + "</SECTION-2></SECTION-1></BODY></DOCUMENT>")


def make_dsd(path: Path, **kw) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("contents.xml", contents(**kw))
        z.writestr("meta.xml", '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><METAINFO></METAINFO>')
    return path
