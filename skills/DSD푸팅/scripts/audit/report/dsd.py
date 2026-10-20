"""DART 편집기 dsd 파일 쓰기와 읽기 (2026-10-06).

규격 근거는 dsd 샘플 1건, 공개 감사보고서 원문(OpenDART XML) 204건과 공개 자료다(docs/specs/2026-10-06-감사-DART-dsd-규격.md). dsd 는 zip 이고 안에 contents.xml(dart4.xsd 꼴
본문)과 meta.xml 이 있다.

  write_dsd(path, parts, info)   HTML 과 같은 부분 목록 [(부분 이름, 블록 목록)] 과 회사 정보로 dsd 를 쓴다
  read_dsd(path) -> blocks       dsd 를 HTML 과 같은 블록 목록으로 읽는다(report/base.py 블록 꼴)
  untouched(path)                엔진이 만든 그대로인지(zip 주석의 해시와 contents.xml · meta.xml). 없으면 참

쓰기는 틀 채우기다. definitions/dart_dsd_frame.xml 은 샘플 contents.xml 에서 값과 회사 문장을 지우고 요소 · 속성 · 순서만 남긴
틀이다(tools/make_dsd_frame.py 로 만든다). 엔진은 틀을 읽어 값만 채운다:
  표지 · 목차          회사명 · 기수 · 기간(TU) · 감사인 명칭. 목차는 틀 그대로(쪽 번호는 비움)
  감사인의 감사보고서  틀의 INSERTION(AFREQUENCY 0 → 1) 안 LIBRARY 에 SECTION-1 을 둔다. 안 모양은 공개 감사보고서 원문 24건의 꼴
                       (수신인 표 · 소제목과 문단 · 서명 표 · 보고서일 · 유효기간 안내 상자)
  (첨부) 재무제표      머리 표(회사명 · 당기 · 전기 기수와 기간 · 작성 문구와 대표이사 · 본점 · 전화), 재무제표마다
                       INSERTION > LIBRARY > TABLE-GROUP(머리 EXTRACTION 표 + FINANCE 본표 + 별첨 문구). FINANCE 본표는
                       과목 · 당기 내역 · 당기 합계 · 전기 내역 · 전기 합계 다섯 칸, 칸은 모두 TE(ACODE · ADELIM · ALEVEL).
                       재무제표 표가 없으면 그 INSERTION 을 AFREQUENCY 0 으로 비운다
  주석                 머리 표, 굵은 번호 제목 P, 본문 P, 단위 표 + 본표. 「표 N-k」 설명은 쓰지 않는다
  외부감사 실시내용    틀의 EXTRACTION 표(INS_SUB · INS_NUT · INS_CONT · INS_COMM) TE · TU 칸에 DART 검토 조서 기입 값
  검토 전 초안 상자     BODY 맨 앞 WARNING(본문 절에는 넣지 않는다)

회사가 만든 dsd 를 읽을 때: COVER · TOC · INSERTION 의 COMMENT · LIBRARYLIST · 편집기 안내 WARNING 은 뺀다. 테두리 없는 표(BORDER="0",
기수 · 단위 · 서명 줄)는 문단으로, 재무제표 표(FINANCE)는 당기 · 전기 두 칸씩 묶인 열을 한 칸으로 합치고 과목 이름의 번호와
「(주석 …)」 를 뗀다. 주석 절 표 앞에 「표 N-k」 설명이 없으면 주석 번호와 표 순서로 「표 N-k (dsd 위치로 붙인 번호)」 를 붙인다.
"""
from __future__ import annotations

import copy
import hashlib
import io
import json
import re
import zipfile
from datetime import date
from pathlib import Path
from xml.etree import ElementTree as ET

from .base import DEFS, fmt, norm, parse_num

STAMP = "audit-engine"
PARTS = ("감사보고서", "(첨부) 재무제표", "주석", "외부감사 실시내용")
# 절 제목의 AASSOCNOTE. 감사보고서는 공개 원문 24건에서, 나머지는 dsd 샘플에서 확인했다
ASSOC = {"감사보고서": "D-0-0-1-0", "(첨부) 재무제표": "D-0-0-0-0", "주석": "D-0-1-0-0", "외부감사 실시내용": "D-0-2-0-0"}
REPORT_ENG = "Independent Auditor’s Audit Report"
# 요약 코드 SUPV_OPIN. 공개 원문 199건에서 적정은 모두 100000000000(옛 dart3 일부는 11자리), 의견거절 2건은 411010010000.
# 첫 자리가 의견 종류다. 둘째 자리부터의 뜻은 모르므로 적정만 채운다(규격 문서 3.1절)
SUPV_OPIN = {"적정": "100000000000"}
HEAD_MARK = {2: "F-14 B", 3: "B", 4: "F-11 B"}
CR = "&cr;"                       # dsd 본문의 줄바꿈 표시(XML 에는 &amp;cr; 로 들어간다)
# 요약 코드(SUMMARY/EXTRACTION) 18개. 샘플 순서 그대로다. 뜻은 규격 문서 표를 본다
SUMMARY_CODES = ("AUDIT_CIK", "SUPV_OPIN", "GMSH_DATE", "CRP_RGS_NO", "FIN_STAT", "TOT_ASSETS", "TOT_DEBTS", "TOT_SALES",
                 "TOT_EMPL", "ETC_OTHR_YN", "POW_OTHR_YN", "ACC_PROF_YN", "IFRS_YN", "FIN_YN", "CRP_RGS_CLS", "LINK_FLAG",
                 "PREV_IACS", "PREV_YN")
DOC_CODE = "00760"               # 감사보고서 서식 코드(DOCUMENT-NAME ACODE · meta 의 bsn-id 등)
FORMULA = ("20221027", "6.0")    # FORMULA-VERSION ADATE · 값
EDITVER = "5.061"
_CAP = re.compile(r"^표\s*\d+-\d+\s")
_NOTE = re.compile(r"^(\d+)\s*\.\s*\S")


def path_of(html_path: Path) -> Path:
    """DART_제출파일_v<판>.html 옆의 .dsd 경로."""
    return Path(html_path).with_suffix(".dsd")


# ---------------------------------------------------------------- 회사 정보
def million(v) -> str:
    """요약 금액 코드 값. 샘플 1건에서 원 단위 금액을 백만원 단위로 버림한 값이었다."""
    if v is None:
        return ""
    v = int(v)
    return str((abs(v) // 1_000_000) * (1 if v >= 0 else -1))


def fs_levels(F: dict | None) -> dict:
    """엔진 재무제표 줄 종류를 dsd 과목 칸 규칙(ALEVEL · 금액 칸 · 번호)으로 바꾼 표. {"bs"|"is": {과목: (단계, 칸, 번호)}}.
    칸은 detail(내역, ADELIM 1 · 3) · total(합계, ADELIM 2 · 4) · none(머리줄). 규칙은 샘플 FINANCE 표에서 읽었다(규격 문서 4.3)."""
    out = {"bs": {}, "is": {}}
    if not F:
        return out
    for r in F.get("bs") or []:
        k = r["kind"]
        if k == "header":
            v = (0, "none", False)
        elif k == "group":
            v = (0, "total", True)
        elif k == "total":
            v = (0, "total", False)
        elif r.get("unit") is not None and r["unit"].group == "자본":
            v = (0, "total", True)           # 자본은 과목(자본금 · 이익잉여금 …)이 바로 로마 숫자 줄이다
        else:
            v = (2, "detail", False)
        out["bs"][norm(r["label"])] = v
    rows = F.get("is") or []
    members = {norm(m) for r in rows if r["kind"] == "group" for m, _ in r["members"]}
    for r in rows:
        if r["kind"] in ("group", "calc") or norm(r["label"]) not in members:
            v = (0, "total", True)
        else:
            v = (1, "detail", False)
        out["is"][norm(r["label"])] = v
    return out


def info_of(d: Path, statements: dict | None = None) -> dict:
    """감사건 · 8600 「회사 정보」 · 엔진 재무제표에서 dsd 머리 정보를 모은다. 엔진에 없는 값은 비운다.
    statements 는 엔진 재무제표(fs.build 결과) 또는 key_figures 결과다."""
    from . import fs as fsm
    from .base import case
    from .opinion import read as read_opinion, read_info

    c = case(d)
    comp = c.get("company") or {}
    comp = comp if isinstance(comp, dict) else {"name": str(comp)}
    F = statements if isinstance(statements, dict) and isinstance(statements.get("bs"), list) else None
    s = fsm.key_figures(F) if F else (statements or {})
    ri = read_info(d)
    op = read_opinion(d)
    supv = SUPV_OPIN.get(op.get("kind")) if not op.get("problems") else None    # 8600 에서 회계사가 고른 의견만 옮긴다
    return {"name": comp.get("name") or "", "corp_code": comp.get("dart_corp_code") or "",
            "fiscal_year_end": c.get("fiscal_year_end") or "", "fiscal_year_start": c.get("fiscal_year_start") or "",
            "term": ri.get("term"),
            "ceo": ri.get("ceo"), "address": ri.get("address"), "phone": ri.get("phone"), "auditor": ri.get("auditor"),
            "levels": fs_levels(F),
            "summary": {"TOT_ASSETS": million(s.get("자산총계")), "TOT_DEBTS": million(s.get("부채총계")),
                        "TOT_SALES": million(s.get("매출액")), "SUPV_OPIN": supv or ""}}


def _period(info: dict) -> tuple[date | None, date | None, date | None, date | None]:
    """(당기 시작, 당기말, 전기 시작, 전기말). 감사건의 사업연도 시작일(fiscal_year_start, 반기 · 짧은 사업연도)을 따른다(R9)."""
    from .. import folder

    case = {"fiscal_year_end": info.get("fiscal_year_end"), "fiscal_year_start": info.get("fiscal_year_start") or None}
    try:
        p = folder.periods(case)
    except (ValueError, TypeError, KeyError):
        return None, None, None, None
    return p["cur_start"], p["cur_end"], p["prior_start"], p["prior_end"]


def _kdate(x: date | None) -> str:
    """TU 칸 날짜. 샘플 TU 칸은 「2024년 01월 01일」 처럼 달 · 날을 두 자리로 쓴다."""
    return f"{x.year}년 {x.month:02d}월 {x.day:02d}일" if x else ""


def _heads(info: dict) -> dict:
    """dsd 머리 글. 기수가 없으면 표지는 【기입】 칸, 재무제표 머리는 「당기」 · 「전기」 로 쓴다. 날짜는 「2025년 12월 31일」."""
    from .documents import kdate

    t = info.get("term")
    pt = t - 1 if t and t > 1 else None
    s, e, ps, pe = _period(info)
    return {"s": s, "e": e, "ps": ps, "pe": pe, "t": t, "pt": pt,
            "cover_cur": f"제 {t} 기" if t else "제 【기입: 당기 기수】 기",
            "cover_prior": f"제 {pt} 기" if pt else ("" if t else "제 【기입: 전기 기수】 기"),
            "cur": f"제 {t} (당) 기" if t else "당기", "prior": f"제 {pt} (전) 기" if pt else "전기",
            "cur_end": kdate(e) or "", "prior_end": kdate(pe) or "",
            "cur_period": f"{kdate(s)}부터 {kdate(e)}까지" if s else "",
            "prior_period": f"{kdate(ps)}부터 {kdate(pe)}까지" if s else ""}


# ---------------------------------------------------------------- 쓰기: 틀
FRAME = DEFS / "dart_dsd_frame.xml"
ROMAN = ["Ⅰ", "Ⅱ", "Ⅲ", "Ⅳ", "Ⅴ", "Ⅵ", "Ⅶ", "Ⅷ", "Ⅸ", "Ⅹ"]
ROMAN += ["Ⅹ" + x for x in ROMAN]
STATEMENTS = {   # 재무제표 → (틀의 LIBRARYLIST, 머리 줄 종류, FINANCE 머리 끝말)
    "재무상태표": ("00760_BS#*.dsl", "at", "말"),
    "손익계산서": ("00760_IS#*.dsl", "during", ""),
    "자본변동표": ("00760_PEF#*.dsl", "during", ""),
    "현금흐름표": ("00760_CF#*.dsl", "during", ""),
}
REPORT_LIB = "00760#*감사인의 감사보고서.dsl"
REPORT_FILE = "감사인의 감사보고서"        # FILENAME 글은 미확인(샘플은 이 절을 지운 판, 공개 원문은 FILENAME 을 걷어 낸 판. 규격 문서 5절)
# 재무상태표 · 손익계산서 과목 이름 → 계정코드(TE ACODE). 샘플 1건에서 이름이 같은 과목에 붙어 있던 코드만 옮겼다.
# 표준 코드표 원본은 확인하지 못했다. 표에 없는 과목은 샘플에서 사용자 추가 과목에 쓰인 99999999999999 로 둔다.
ACODES = {
    "자산": "11000000000000", "부채": "11000000000000", "자본": "11000000000000",
    "유동자산": "11200000040000", "당좌자산": "11130000030000", "현금및현금성자산": "11110000040000",
    "단기금융상품": "11122000010000", "매출채권": "11115000010000", "미수수익": "11119000010000", "미수금": "11118000010000",
    "선급금": "11141000010000", "선급비용": "11142000010000", "비유동자산": "11400000050000", "투자자산": "11300000030000",
    "매도가능증권": "11212100010000", "장기투자증권": "11212000010000", "유형자산": "11320000050000", "비품": "11318000010000",
    "시설장치": "11314600010000", "건설중인자산": "11319900010000", "무형자산": "11340000070000",
    "산업재산권": "11322000010000", "기타비유동자산": "11360000010000", "임차보증금": "11226100020000",
    "자산총계": "11500000010000", "유동부채": "11600000050000", "매입채무": "11511000010000", "미지급금": "11514000010000",
    "예수금": "11516000010000", "부가세예수금": "11516600010000", "선수금": "11515000010000", "미지급비용": "11518000010000",
    "단기차입금": "11513000010000", "비유동부채": "11700000040000", "퇴직급여충당부채": "11661000010000",
    "복구충당부채": "11664500010000", "부채총계": "11800000010000", "자본금": "11810000010000",
    "보통주자본금": "11811000010000", "우선주자본금": "11812000010000", "자본잉여금": "11820000010000",
    "주식발행초과금": "11821100010000", "자본총계": "11890000010000", "부채및자본총계": "11900000010000",
    "부채와자본총계": "11900000010000",
    "영업수익": "12100000010000", "영업비용": "12400000010000", "급여": "12412000170000", "잡급": "12412000150000",
    "퇴직급여": "12415000120000", "복리후생비": "12417000010000", "여비교통비": "12421100010000", "접대비": "12431100060000",
    "통신비": "12421200010000", "세금과공과": "12421400010000", "감가상각비": "12421600010000", "보험료": "12421800010000",
    "차량유지비": "12422200010000", "운반비": "12431600010000", "교육훈련비": "12422300010000", "도서인쇄비": "12422100010000",
    "소모품비": "12422000010000", "지급수수료": "12422402350000", "판매수수료": "12431700010000",
    "광고선전비": "12431200010000", "대손상각비": "12444000040000", "무형자산상각비": "12445000240000",
    "영업외수익": "12510000010000", "이자수익": "12510100010000", "외환차익": "12510900010000",
    "외화환산이익": "12511100010000", "유형자산처분이익": "12512300020000", "잡이익": "12511500190000",
    "영업외비용": "12600000010000", "이자비용": "12611000010000", "기부금": "12615000010000", "외환차손": "12616000010000",
    "외화환산손실": "12617400010000", "유형자산처분손실": "12626000020000", "잡손실": "12625000130000",
    "법인세비용": "12810000040000",
}
OTHER_CODE = "99999999999999"
ACODE_FILE = DEFS / "dart_acodes.yaml"     # 공개 감사보고서 원문에서 만든 표(tools/make_dart_acodes.py). ACODES 와 겹치는 과목은 모두 같다
CONTRA_ENDS = ("충당금", "누계액", "보조금", "할인차금", "할증금")
_ACODE_TABLE: dict | None = None


def acode_table() -> dict:
    global _ACODE_TABLE
    if _ACODE_TABLE is None:
        import yaml

        d = yaml.safe_load(ACODE_FILE.read_text(encoding="utf-8")) if ACODE_FILE.exists() else {}
        plain = {k: v["code"] for k, v in (d.get("plain") or {}).items()}
        plain.update({norm(k): v for k, v in ACODES.items()})
        _ACODE_TABLE = {"plain": plain, "contra": {k: v["code"] for k, v in (d.get("contra") or {}).items()}}
    return _ACODE_TABLE


def acode(label: str, parent: str | None) -> str:
    """재무상태표 · 손익계산서 과목 → TE ACODE. 차감 과목(충당금 · 누계액 등)은 바로 위 과목과 짝으로 찾는다. 표에 없으면 OTHER_CODE."""
    t, n = acode_table(), norm(label)
    if n.endswith(CONTRA_ENDS) and not n.startswith("기타포괄손익"):
        return t["contra"].get(f"{norm(parent)}/{n}", OTHER_CODE) if parent else OTHER_CODE
    return t["plain"].get(n, OTHER_CODE)
BS_HEADERS = ("자산", "부채", "자본")
BS_GROUPS = ("유동자산", "비유동자산", "유동부채", "비유동부채")
IS_TOP = ("매출액", "매출원가", "매출총이익", "판매비와관리비", "영업이익", "영업외수익", "영업외비용", "법인세비용차감전순이익",
          "법인세비용", "당기순이익", "영업수익", "영업비용")
_CAP_NUM = re.compile(r"^표\s*\d+-\d+\s*")
_UNIT = re.compile(r"\(\s*(단위\s*:[^)]*)\)\s*$")


def _el(parent, tag, text=None, **attrs):
    e = ET.SubElement(parent, tag, {k.replace("_", "-"): str(v) for k, v in attrs.items()})
    if text is not None:
        e.text = text
    return e


def _new(tag, text=None, **attrs):
    e = ET.Element(tag, {k.replace("_", "-"): str(v) for k, v in attrs.items()})
    if text is not None:
        e.text = text
    return e


def _frame() -> ET.Element:
    root = ET.fromstring(FRAME.read_bytes())
    for e in root.iter():
        if len(e) and e.text is not None and not e.text.strip():
            e.text = None
    return root


def _insert_after(parent, ref, elems: list) -> None:
    i = list(parent).index(ref)
    for k, e in enumerate(elems, 1):
        parent.insert(i + k, e)


def _insertion(body, lib: str):
    return next(e for e in body.iter("INSERTION") if (e.findtext("LIBRARYLIST") or "") == lib)


def _p(text: str = "", mark: str | None = None):
    return _new("P", text, **({"USERMARK": mark} if mark else {}))


def _flow(blocks: list, cr: bool = False, skip_title: str | None = None) -> list:
    """블록을 P · 표 요소로. 제목 단계는 HTML 과 같게 하나 내려 USERMARK 로 적는다(HTML h2 = F-14 B, h3 = B, h4 = F-11 B).
    제목 앞에는 빈 P 를 둔다. 주석 표 설명(「표 N-k 제목 (단위: 원)」)은 번호를 떼고 제목 P 와 단위 표로 나눈다
    (샘플 주석 절에 표 번호가 없다). cr 이면 본문 P 앞에 &cr; 를 붙인다(샘플 주석 문단)."""
    out, unit = [], None
    for b in blocks:
        if b[0] == "h":
            if skip_title and b[1] == 1 and norm(b[2]) == norm(skip_title):
                continue
            out += [_p(), _p(str(b[2]), HEAD_MARK[min(max(b[1] + 1, 2), 4)])]
        elif b[0] == "p":
            out.append(_p((CR if cr else "") + str(b[1])))
        elif b[0] == "cap":
            t = _CAP_NUM.sub("", str(b[1]), count=1)
            m = _UNIT.search(t)
            unit = re.sub(r"\s*:\s*", ": ", m.group(1)) if m else None
            title = (t[:m.start()] if m else t).strip()
            if title:
                out.append(_p((CR if cr else "") + title))
        elif b[0] == "table":
            if unit:
                out.append(_unit_table(unit))
            out.append(_note_table(b[1]))
            unit = None
    return out


def _unit_table(unit: str, width: int = 748):
    t = _new("TABLE", ACLASS="NORMAL", WIDTH=width, BORDER="0", AFIXTABLE="N")
    cg = _el(t, "COLGROUP", WIDTH=width)
    _el(cg, "COL", "", WIDTH="300")
    _el(cg, "COL", "", WIDTH=width - 300)
    tb = _el(t, "TBODY", ALIGN="LEFT", VALIGN="TOP")
    tr = _el(tb, "TR", ACOPY="Y", ADELETE="Y", HEIGHT="31")
    _el(tr, "TD", "", WIDTH="291", HEIGHT="24")
    _el(tr, "TD", f"({unit})", ALIGN="RIGHT", VALIGN="MIDDLE", WIDTH=width - 309, USERMARK="F-12 ", HEIGHT="24")
    return t


def _note_table(rows: list[list]):
    """주석 · 일반 표. 샘플 주석 표 꼴(NORMAL, BORDER=1, THEAD 의 TH, TBODY 의 TD, 글꼴 F-12, 첫 칸 가운데 · 숫자 오른쪽)."""
    ncol = max((len(r) for r in rows), default=1) or 1
    first = 215 if ncol > 1 else 748
    rest = (748 - first) // (ncol - 1) if ncol > 1 else 0
    ws = [first] + [rest] * (ncol - 1)
    t = _new("TABLE", ACLASS="NORMAL", AFIXTABLE="N", WIDTH=sum(ws), BORDER="1")
    cg = _el(t, "COLGROUP", WIDTH=sum(ws))
    for w in ws:
        _el(cg, "COL", "", WIDTH=w)
    if not rows:
        return t
    tr = _el(_el(t, "THEAD"), "TR", ACOPY="Y", ADELETE="Y", HEIGHT="31")
    for j in range(ncol):
        v = rows[0][j] if j < len(rows[0]) else ""
        _el(tr, "TH", str(v), VALIGN="MIDDLE", WIDTH=ws[j] - 9, ACOPYCOL="Y", ADELETECOL="Y", AMOVECOL="N", USERMARK="F-12 ",
            HEIGHT="24")
    tb = _el(t, "TBODY")
    for r in rows[1:]:
        tr = _el(tb, "TR", ACOPY="Y", ADELETE="Y", HEIGHT="31")
        for j in range(ncol):
            v = str(r[j] if j < len(r) else "")
            if j == 0:
                _el(tr, "TD", v, ALIGN="CENTER", VALIGN="MIDDLE", USERMARK="F-12 ", WIDTH=ws[j] - 9, HEIGHT="24")
            elif parse_num(v) is not None:
                _el(tr, "TD", v, ALIGN="RIGHT", VALIGN="MIDDLE", USERMARK="F-12 ", WIDTH=ws[j] - 9, HEIGHT="24")
            else:
                _el(tr, "TD", v, VALIGN="MIDDLE", USERMARK="F-12 ", WIDTH=ws[j] - 9, HEIGHT="24")
    return t


def _kept(elems: list) -> list:
    """빈 P(제목 앞 빈 줄)만 있는 목록이면 버린다."""
    return elems if any(e.text or len(e) for e in elems) else []


# ---------------------------------------------------------------- 쓰기: 표지 · 목차
def _fill_period_table(t, term: str, s: date | None, e: date | None) -> None:
    """기수 · 기간 표(표지 COVER · 재무제표 COVER2 의 EXTRACTION 표와 그 밑 전기 표). TU 칸이면 AUNITVALUE 도 쓴다."""
    rows = t.findall("TBODY/TR")
    rows[0][0].text = term
    for tr, x in ((rows[1], s), (rows[2], e)):
        c = tr[0]
        c.text = _kdate(x)
        if c.tag == "TU":
            c.set("AUNITVALUE", x.strftime("%Y%m%d") if x else "")


def _cover(body, info: dict, h: dict) -> None:
    cov = body.find("COVER")
    list(cov)[1].text = info.get("name") or ""
    _fill_period_table(cov.find("TABLE-GROUP/TABLE"), h["cover_cur"], h["s"], h["e"])
    prior = cov.find("TABLE")
    if h["cover_prior"]:
        _fill_period_table(prior, h["cover_prior"], h["ps"], h["pe"])
    else:
        cov.remove(prior)
    aud = next(p for p in cov.findall("P") if p.get("USERMARK") == "F-18 ")
    aud.text = " " * 29 + (info.get("auditor") or "【기입: 감사인 명칭】")


def _toc(body, report_title: str) -> None:
    for td in body.find("TOC").iter("TD"):
        if td.text and norm(td.text) == norm("독립된 감사인의 감사보고서") and report_title:
            td.text = report_title


# ---------------------------------------------------------------- 쓰기: 감사인의 감사보고서
_DATE = re.compile(r"^\d{4}\s*년\s*\d{1,2}\s*월\s*\d{1,2}\s*일$")
_VALID = re.compile(r"현재로\s*유효한\s*것입니다")


def report_pieces(blocks: list, title: str) -> tuple[str | None, list, list[str], str | None, str | None, list]:
    """8820 블록 → (수신인 문단, 본문 블록, 서명 줄, 보고서일, 유효기간 안내, 보고서일 뒤 블록).
    수신인은 첫 문단이 「귀중」 으로 끝날 때, 서명은 보고서일 바로 앞의 짧은 문단(60자 이하, 최대 셋)이다. 못 찾은 것은 본문에 남는다."""
    bl = [b for b in blocks if not (b[0] == "h" and b[1] == 1 and norm(b[2]) == norm(title))]
    addr = None
    if bl and bl[0][0] == "p" and str(bl[0][1]).rstrip().endswith("귀중"):
        addr, bl = str(bl[0][1]).strip(), bl[1:]
    valid = None
    k = next((i for i in range(len(bl) - 1, -1, -1) if bl[i][0] == "p" and _VALID.search(str(bl[i][1]))), None)
    if k is not None:
        valid, bl = str(bl[k][1]).strip(), bl[:k] + bl[k + 1:]
    j = next((i for i in range(len(bl) - 1, -1, -1) if bl[i][0] == "p" and _DATE.match(str(bl[i][1]).strip())), None)
    if j is None:
        return addr, bl, [], None, valid, []
    i, sign = j, []
    while i > 0 and len(sign) < 3 and bl[i - 1][0] == "p" and len(str(bl[i - 1][1])) <= 60 \
            and not str(bl[i - 1][1]).lstrip().startswith(("-", "·", "우리")):
        i -= 1
        sign.insert(0, str(bl[i][1]).strip())
    return addr, bl[:i], sign, str(bl[j][1]).strip(), valid, bl[j + 1:]


def _plain_table(rows: list[list[str]], widths: list[int], border: str, height: int = 30, align: str | None = None):
    """감사보고서 절의 일반 표(수신인 · 서명 · 유효기간 안내). 공개 감사보고서 원문(OpenDART, dart4) 24건의 꼴이다."""
    t = _new("TABLE", ACLASS="NORMAL", AFIXTABLE="N", WIDTH=sum(widths), BORDER=border)
    cg = _el(t, "COLGROUP", WIDTH=sum(widths))
    for w in widths:
        _el(cg, "COL", "", WIDTH=w)
    tb = _el(t, "TBODY")
    for r in rows:
        tr = _el(tb, "TR", ACOPY="Y", ADELETE="Y", HEIGHT=height)
        for j, w in enumerate(widths):
            _el(tr, "TD", r[j] if j < len(r) else "", WIDTH=w - 9, HEIGHT=height - 7, **({"ALIGN": align} if align else {}))
    return t


def _report(body, blocks: list) -> str:
    """감사인의 감사보고서 INSERTION 을 넣음(AFREQUENCY=1)으로 바꾸고 LIBRARY 안에 절을 둔다.
    절 모양은 공개 감사보고서 원문(OpenDART 공시서류원본파일, dart4.xsd) 24건에서 확인했다(규격 문서 5.1절):
    TITLE(ATOC=Y · AASSOCNOTE=D-0-0-1-0 · ATOCID=2 · ENG), 빈 P 둘, 수신인 표(테두리 없음, 회사명 줄 · 「주주 및 이사회 귀중」 줄),
    굵은 소제목과 본문 P, 서명 표(테두리 없음, 오른쪽 정렬), 보고서일 P, 유효기간 안내 상자(테두리 1칸 표), PGBRK.
    원문 XML 은 편집기용 INSERTION · FILENAME 을 걷어 낸 판이라 FILENAME 글은 여전히 미확인이다."""
    ins = _insertion(body, REPORT_LIB)
    title = next((str(b[2]) for b in blocks if b[0] == "h" and b[1] == 1), "독립된 감사인의 감사보고서")
    ins.set("AFREQUENCY", "1")
    lib = _el(ins, "LIBRARY")
    _el(lib, "FILENAME", REPORT_FILE, ATYPE="dsl")
    sec = _el(lib, "SECTION-1", ACLASS="MANDATORY", APARTSOURCE="SOURCE")
    _el(sec, "TITLE", title, ATOC="Y", AASSOCNOTE=ASSOC["감사보고서"], ATOCID="2", ENG=REPORT_ENG)
    addr, main, sign, day, valid, tail = report_pieces(blocks, title)
    sec.extend([_p(), _p()])
    if addr:
        k = addr.find("주주")
        rows = [[addr[:k].strip(), ""], [addr[k:].strip(), ""]] if k > 0 else [[addr, ""]]
        sec.append(_plain_table(rows, [300, 300], "0"))
    sec.extend(_flow(main, skip_title=title))
    if sign:
        sec.append(_p())
        sec.append(_plain_table([[s] for s in sign], [600], "0", align="RIGHT"))
    if day:
        sec.extend([_p(), _p(day)])
    if valid:
        sec.append(_plain_table([[valid]], [600], "1", height=99))
    sec.extend(_flow(tail))
    sec.append(_p())
    _el(sec, "PGBRK")
    return title


# ---------------------------------------------------------------- 쓰기: (첨부) 재무제표
def _split_fs(blocks: list) -> tuple[list, dict]:
    """(첨부) 재무제표 블록 → (머리 블록, {재무제표: {"table": 행, "extra": [블록]}})."""
    head, st, cur = [], {}, None
    names = {norm(k): k for k in STATEMENTS}
    for b in blocks:
        if b[0] == "h" and b[1] >= 2 and norm(b[2]) in names:
            cur = names[norm(b[2])]
            st[cur] = {"table": None, "extra": [], "head_seen": False}
            continue
        if cur is None:
            if not (b[0] == "h" and b[1] == 1):
                head.append(b)
            continue
        x = st[cur]
        if b[0] == "table" and x["table"] is None:
            x["table"] = b[1]
        elif b[0] == "p" and not x["head_seen"] and x["table"] is None and any(w in b[1] for w in ("현재", "부터", "단위")):
            x["head_seen"] = True           # 8810 의 기수 · 기준일 줄. dsd 는 머리 표에 따로 쓴다
        else:
            x["extra"].append(b)
    return head, st


def _cover_lines(head: list, info: dict) -> dict:
    """8810 머리 문단에서 대표이사 · 본점 · 전화를 읽는다. 없으면 8600 「회사 정보」 값, 그것도 없으면 【기입】 칸."""
    out = {"ceo": None, "address": None, "phone": None, "extra": []}
    for b in head:
        if b[0] != "p":
            out["extra"].append(b)
            continue
        t = str(b[1])
        n = norm(t)
        if "대표이사" in t and out["ceo"] is None:
            out["ceo"] = re.sub(r"\s*\(인\)\s*$", "", t).strip()
        elif n.startswith("본점소재지"):
            out["address"] = re.sub(r"^\s*\(도로명주소\)\s*", "", re.sub(r"^[^:]*:\s*", "", t)).strip()
        elif n.startswith("(전화)") or n.startswith("전화"):
            out["phone"] = re.sub(r"^\(?\s*전\s*화\s*\)?\s*:?\s*", "", t).strip()
        elif n == norm(info.get("name")) or "작성한것입니다" in n or (n.startswith("제") and "부터" in n):
            continue
        else:
            out["extra"].append(b)
    name = info.get("name") or ""
    out["ceo"] = out["ceo"] or f"{name} 대표이사 {info.get('ceo') or '【기입: 대표이사 성명】'}"
    out["address"] = out["address"] or info.get("address") or "【기입: 본점 소재지】"
    out["phone"] = out["phone"] or info.get("phone") or "【기입: 본점 전화번호】"
    return out


def _roman(i: int) -> str:
    return ROMAN[i] if i < len(ROMAN) else str(i + 1)


def _guess(kind: str, label: str, side: str | None) -> tuple[int, str, bool]:
    """엔진 줄 종류를 모를 때(회계사가 더한 과목 · 엔진 재무제표 없이 쓸 때) 이름으로 정한다."""
    n = norm(label)
    if kind == "bs":
        if n in BS_HEADERS:
            return (0, "none", False)
        if n.endswith("총계"):
            return (0, "total", False)
        if n in BS_GROUPS or side == "자본":
            return (0, "total", True)
        return (2, "detail", False)
    if kind == "is":
        return (0, "total", True) if n in {norm(x) for x in IS_TOP} or n.endswith("합계") else (1, "detail", False)
    if re.match(r"^\s*[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩIVX]+\.", label):          # 현금흐름표: 번호 모양으로 단계를 정한다
        return (0, "total", False)
    if re.match(r"^\s*\d+\.", label):
        return (1, "detail", False)
    return (2, "detail", False)


def _fin_rows(st: str, rows: list[list], levels: dict) -> list[tuple]:
    """재무제표 표 행 → [(과목 글, 단계, 칸, [당기, 전기], 코드)]. 번호는 샘플처럼 로마 숫자(재무상태표는 자산 · 부채 · 자본마다 다시)."""
    kind = {"재무상태표": "bs", "손익계산서": "is"}.get(st, "cf")
    lv = levels.get(kind, {}) if kind != "cf" else {}
    out, side, k, parent = [], None, 0, None
    for r in rows[1:]:
        lab = str(r[0]) if r else ""
        vals = [str(x) if x is not None else "" for x in (list(r[1:3]) + ["", ""])[:2]]
        n = norm(lab)
        if kind == "bs" and n in BS_HEADERS and not any(vals):
            side, k = lab.strip(), 0
        level, col, num = lv.get(n) or _guess(kind, lab, side)
        if col == "none" and any(vals):
            col = "total"
        text = lab
        if num:
            text = f"{_roman(k)}. {lab}"
            k += 1
        code = "" if kind == "cf" else acode(lab, parent)
        if not (n.endswith(CONTRA_ENDS) and not n.startswith("기타포괄손익")):
            parent = lab
        out.append((text, level, col, vals, code))
    return out


def _finance_body(t, rows: list[tuple]) -> None:
    """FINANCE 본문. 내역 과목은 당기 · 전기 첫 칸(ADELIM 1 · 3), 합계 과목은 둘째 칸(2 · 4)에 쓰고, 같은 기간 남은 칸은
    샘플처럼 내역 줄이면 전각 공백 · 빈 칸, 합계 줄이면 전각 공백 · 빈 칸으로 둔다."""
    widths = [int(c.get("WIDTH")) for c in t.findall("COLGROUP/COL")]
    tb = t.find("TBODY")
    for i, (text, level, col, vals, code) in enumerate(rows):
        tr = _el(tb, "TR", ACOPY="Y", ADELETE="N" if i == 0 else "Y", HEIGHT="30")
        a = {"ACODE": code, "ADELIM": "0", "ALEVEL": str(level)}
        if level:
            a["USERMARK"] = "P16" if level == 1 else "P32"
        _el(tr, "TE", text, **a, WIDTH=widths[0] - 9, HEIGHT="23")
        if col == "detail":
            cells = [vals[0], "　", vals[1], ""]
        elif col == "total":
            cells = ["　", vals[0], "", vals[1]]
        else:
            cells = ["", "", "", ""]
        for j, v in enumerate(cells, 1):
            _el(tr, "TE", v, ALIGN="RIGHT", ACODE=code, ADELIM=str(j), WIDTH=widths[j] - 9, HEIGHT="23")


def _sce_table(t, rows: list[list]) -> None:
    """자본변동표 FINANCE: 열(자본 과목 + 합계)이 회사마다 달라 COLGROUP · THEAD 를 엔진 열로 다시 쓴다. 너비 합은 샘플과 같다."""
    total = int(t.get("WIDTH"))
    ncol = max(len(r) for r in rows)
    first = int(t.find("COLGROUP/COL").get("WIDTH"))
    rest = (total - first) // max(ncol - 1, 1)
    ws = [first] + [rest] * (ncol - 1)
    cg = t.find("COLGROUP")
    for c in list(cg):
        cg.remove(c)
    for w in ws:
        _el(cg, "COL", "", WIDTH=w)
    tr = t.find("THEAD/TR")
    proto = [dict(c.attrib) for c in tr]
    for c in list(tr):
        tr.remove(c)
    for j in range(ncol):
        a = dict(proto[min(j, len(proto) - 1)])
        a["WIDTH"] = str(ws[j] - 9)
        a["ADELETECOL"] = "N" if j < 2 else "Y"
        txt = "과     목" if j == 0 else str(rows[0][j] if j < len(rows[0]) else "")
        tr.append(_new("TH", txt, **a))
    tb = t.find("TBODY")
    n = len(rows) - 1
    for i, r in enumerate(rows[1:]):
        level = 0 if i in (0, n - 1) else 1
        row = _el(tb, "TR", ACOPY="Y", ADELETE="N" if i == 0 else "Y", HEIGHT="30")
        a = {"VALIGN": "MIDDLE", "ACODE": "", "ADELIM": "0", "ALEVEL": str(level)}
        if level:
            a["USERMARK"] = "P16"
        _el(row, "TE", str(r[0]), **a, WIDTH=ws[0] - 9, HEIGHT="23")
        for j in range(1, ncol):
            v = str(r[j]) if j < len(r) and r[j] is not None else ""
            _el(row, "TE", v, ALIGN="RIGHT", VALIGN="MIDDLE", ACODE="", ADELIM=str(j), WIDTH=ws[j] - 9, HEIGHT="23")


def _statement(fs_sec, body, name: str, st: str, x: dict | None, info: dict, h: dict) -> None:
    lib_name, when, tail = STATEMENTS[st]
    ins = _insertion(body, lib_name)
    extra = _kept(_flow((x or {}).get("extra") or []))
    if not x or not x.get("table"):
        ins.set("AFREQUENCY", "0")                  # 넣지 않은 자리(샘플의 다른 빈 INSERTION 과 같다)
        lib = ins.find("LIBRARY")
        if lib is not None:
            ins.remove(lib)
        _insert_after(fs_sec, ins, extra)
        return
    tg = ins.find("LIBRARY/TABLE-GROUP")
    head, fin = tg.findall("TABLE")
    hr = head.findall("TBODY/TR")
    if when == "at":
        hr[0][0].text = f"{h['cur']} {h['cur_end']} 현재"
        hr[1][0].text = f"{h['prior']} {h['prior_end']} 현재"
    else:
        hr[0][0].text = f"{h['cur']} {h['cur_period']}"
        hr[1][0].text = f"{h['prior']} {h['prior_period']}"
    hr[2][0].text = name
    rows = x["table"]
    if st == "자본변동표":
        _sce_table(fin, rows)
    else:
        th = fin.findall("THEAD/TR/TH")
        th[1].text = f"{h['cur']}{tail}" if h["t"] else f"당기{tail}"
        th[2].text = f"{h['prior']}{tail}" if h["pt"] else f"전기{tail}"
        _finance_body(fin, _fin_rows(st, rows, info.get("levels") or {}))
    _insert_after(fs_sec, ins, extra)


def _fs(body, blocks: list, info: dict, h: dict) -> None:
    fs_sec = next(s for s in body.iter("SECTION-1") if s.find("TITLE").get("AASSOCNOTE") == "D-0-0-0-0")
    head, st = _split_fs(blocks)
    cl = _cover_lines(head, info)
    name = info.get("name") or ""
    tables = [k for k in fs_sec if k.tag == "TABLE"]
    name_t, prior_t, sign_t, addr_t = tables[:4]
    name_t.find("TBODY/TR/TD").text = name
    _fill_period_table(fs_sec.find("TABLE-GROUP/TABLE"), h["cover_cur"], h["s"], h["e"])
    if h["cover_prior"]:
        _fill_period_table(prior_t, h["cover_prior"], h["ps"], h["pe"])
    else:
        fs_sec.remove(prior_t)
    sign_t.findall("TBODY/TR")[1][0].text = cl["ceo"]
    ar = addr_t.findall("TBODY/TR")
    ar[0][2].text = " " + cl["address"]
    ar[1][1].text = " " + cl["phone"]
    _insert_after(fs_sec, addr_t, _kept(_flow(cl["extra"])))
    for k in STATEMENTS:
        _statement(fs_sec, body, name, k, st.get(k), info, h)


# ---------------------------------------------------------------- 쓰기: 주석
def _notes(body, blocks: list) -> None:
    """주석 절. 머리 표(당기 · 전기 기수와 기간, 회사명), 주석마다 굵은 번호 제목 P, 본문 P(&cr; 시작), 단위 표와 본표, 끝에 PGBRK."""
    sec = next(s for s in body.iter("SECTION-2") if s.find("TITLE").get("AASSOCNOTE") == "D-0-1-0-0")
    rest = list(blocks)
    head = []
    while rest and not (rest[0][0] == "h" and rest[0][1] >= 2):
        b = rest.pop(0)
        if b[0] == "p":
            head.append(str(b[1]))
    tb = sec.find("TABLE/TBODY")
    proto = tb.findall("TR")
    if head:
        for tr in proto:
            tb.remove(tr)
        for i, line in enumerate(head):
            tr = copy.deepcopy(proto[min(i, len(proto) - 1)])
            tr[0].text = line
            if i == len(head) - 1 and not ("부터" in line or "현재" in line):
                tr[0].attrib.pop("ALIGN", None)           # 샘플: 회사명 줄은 왼쪽
            tb.append(tr)
    first, buf = True, []

    def flush():
        for e in _flow(buf, cr=True):
            if not (e.tag == "P" and not e.text and e.get("USERMARK") is None):
                sec.append(e)
        buf.clear()

    for b in rest:
        if b[0] == "h" and b[1] == 2 and _NOTE.match(str(b[2])):
            flush()
            if not first:
                sec.append(_p())
                _el(sec, "PGBRK")
            first = False
            sec.append(_p(str(b[2]), "B"))
            continue
        buf.append(b)
    flush()
    sec.append(_p())
    _el(sec, "PGBRK")


# ---------------------------------------------------------------- 쓰기: 외부감사 실시내용
PEOPLE_CODE = ("QLT", "ACT", "ACR", "ACP", "EXP")       # dart_file.PEOPLE 순서. COT(수주산업 전문가)는 엔진 기입란에 없다
WORK_CODE = {  # dart_file.WORKS → (수행 시기 칸, 주요 내용 칸)
    "전반감사계획(감사착수단계)": ("PLN_TIM", "PLN_CNT"), "현장감사 주요내용": ("PLC_TIM", "PLC_CNT"),
    "재고자산실사(입회)": ("STK_TIM", "STK_TAG"), "금융자산실사(입회)": ("FIN_TIM", "FIN_TAG"),
    "외부조회": ("ASK_ETC", "ASK_ETC"), "지배기구와의 커뮤니케이션": ("COM_TIM", "COMM_DIS"),
    "외부전문가 활용": ("EXT_SPE", "EXT_CNT"),
}
EXT_HEADS = ("감사참여자 구분별 인원수 및 감사시간", "주요 감사실시내용")


def _ext_values(blocks: list) -> tuple[dict, list]:
    """외부감사 실시내용 블록(HTML 과 같은 기입 표 두 개)에서 칸 값을 읽어 DART 서식 코드 값으로. (코드 값, 남은 블록)."""
    from .dart_file import PEOPLE, WORKS

    vals, extra = {}, []

    def v(x):
        x = "" if x is None else str(x).strip()
        return x if x and "기입" not in x else "【기입】"

    for b in blocks:
        if b[0] == "table" and b[1] and norm(b[1][0][0]) == norm("감사참여자 구분"):
            by = {norm(r[0]): r for r in b[1][1:]}
            for p, code in zip(PEOPLE, PEOPLE_CODE):
                r = list(by.get(norm(p)) or [p]) + [""] * 4
                vals[f"NUM_{code}_TH"], vals[f"TMY_{code}_TH"] = v(r[1]), v(r[2])
                vals[f"NUM_{code}_LA"], vals[f"TMY_{code}_LA"] = v(r[3]), v(r[4])
                for per in ("TH", "LA"):
                    y = vals[f"TMY_{code}_{per}"]
                    vals[f"TMT_{code}_{per}"] = y if parse_num(y) is not None else ""
            for pre in ("NUM", "TMY", "TMT"):
                for per in ("TH", "LA"):
                    xs = [parse_num(vals[f"{pre}_{c}_{per}"]) for c in PEOPLE_CODE]
                    vals[f"{pre}_TOT_{per}"] = fmt(sum(xs)) if all(x is not None for x in xs) else ""
        elif b[0] == "table" and b[1] and len(b[1][0]) > 1 and norm(b[1][0][1]) == norm("수행 시기"):
            by = {norm(r[0]): r for r in b[1][1:]}
            for w in WORKS:
                r = list(by.get(norm(w)) or [w]) + [""] * 2
                a, c = WORK_CODE[w]
                if a == c:
                    vals[a] = f"{v(r[1])} {v(r[2])}"
                else:
                    vals[a], vals[c] = v(r[1]), v(r[2])
        elif b[0] == "h" and norm(b[2]) in {norm(x) for x in EXT_HEADS}:
            continue
        else:
            extra.append(b)
    return vals, extra


def _ext(body, blocks: list, info: dict, h: dict) -> None:
    sec = next(s for s in body.iter("SECTION-1") if s.find("TITLE").get("AASSOCNOTE") == "D-0-2-0-0")
    vals, extra = _ext_values(blocks)
    vals["SUB_COMPY"] = info.get("name") or ""
    if vals.get("COMM_DIS"):
        vals["COMM_NO"] = "1"
    for e in sec.iter():
        if e.tag == "TE" and e.get("ACODE") in vals:
            e.text = vals[e.get("ACODE")]
        elif e.tag == "TU" and e.get("AUNIT") in ("SUB_PERIODFROM", "SUB_PERIODTO"):
            x = h["s"] if e.get("AUNIT") == "SUB_PERIODFROM" else h["e"]
            e.text = _kdate(x)
            e.set("AUNITVALUE", x.strftime("%Y%m%d") if x else "")
    if extra:
        _insert_after(sec, sec.findall("SECTION-2")[-1], _kept(_flow(extra)))


# ---------------------------------------------------------------- 쓰기: 문서
def contents_xml(parts: list[tuple[str, list]], info: dict, warning: list[str] | None = None) -> str:
    """틀(definitions/dart_dsd_frame.xml, 샘플에서 값을 지운 요소 · 속성 · 순서)에 값을 채운다."""
    from .dart_file import WARN_TEXT, WARN_TITLE, _plain

    root = _frame()
    hd = root.find("DOCUMENT-HEADER")
    cn = hd.find("COMPANY-NAME")
    cn.text = info.get("name") or ""
    cn.set("AREGCIK", info.get("corp_code") or "")
    vals = dict(info.get("summary") or {})
    if info.get("auditor_cik"):
        vals["AUDIT_CIK"] = info["auditor_cik"]
    for e in hd.iter("EXTRACTION"):
        e.text = str(vals.get(e.get("ACODE")) or "")
    body = root.find("BODY")
    if warning:
        lines = [WARN_TITLE, WARN_TEXT] + [f"· {_plain(w)}" for w in warning]
        body.insert(0, _new("WARNING", CR.join(lines)))
    h = _heads(info)
    by = {p: bl for p, bl in parts}
    _cover(body, info, h)
    _toc(body, _report(body, by.get("감사보고서", [])))
    _fs(body, by.get("(첨부) 재무제표", []), info, h)
    _notes(body, by.get("주석", []))
    _ext(body, by.get("외부감사 실시내용", []), info, h)
    ET.indent(root, space="")             # 샘플처럼 줄마다 요소 하나, 들여쓰기 없음, 빈 요소도 <X></X>
    return '<?xml version="1.0" encoding="utf-8"?>\n\n' + ET.tostring(root, encoding="unicode", short_empty_elements=False) + "\n"


def meta_xml(info: dict) -> str:
    def q(s):
        return (str(s or "").replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;"))

    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<METAINFO>\n'
            f'\t<GENERATOR schema="dart4.xsd" editver="{EDITVER}"/>\n'
            f'\t<DOCUMENT-HEADER regcik="{q(info.get("corp_code"))}" regname="{q(info.get("name"))}"/>\n'
            f'\t<DOCUMENT-INFO docver="{FORMULA[1]}" bsn-id="{DOC_CODE}" rpt-id="{DOC_CODE}" doc-id="{DOC_CODE}" iscorrection="N"/>\n'
            '\t<FILE-INFO date="" size="" rnnumber="" rncheck="" rnimgfile=""/>\n</METAINFO>\n')


def _zip(path: Path, contents: str, meta: str, comment: bytes = b"") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("contents.xml", contents.encode("utf-8"))
        z.writestr("meta.xml", meta.encode("utf-8"))
        z.comment = comment
    path.write_bytes(buf.getvalue())


def write_dsd(path: Path, parts: list[tuple[str, list]], info: dict, warning: list[str] | None = None,
              note_map: dict | None = None) -> Path:
    """dsd 를 쓴다. parts 는 dart_file.write_html 과 같은 [(부분 이름, 블록)]. 검토 전 상자 줄(warning)은 BODY 맨 앞 WARNING 으로 둔다.
    zip 주석에 엔진 해시(contents.xml · meta.xml 전체)와 주석 번호 대응표를 남긴다. 편집기로 다시 저장하면 zip 주석이
    사라지고, 그러면 회계사가 고친 파일로 본다."""
    path = Path(path)
    c, m = contents_xml(parts, info, warning), meta_xml(info)
    stamp = {STAMP: _digest(c.encode("utf-8"), m.encode("utf-8"))}
    if note_map:
        stamp["note-map"] = {str(k): v for k, v in note_map.items()}
    _zip(path, c, m, json.dumps(stamp, ensure_ascii=False).encode("utf-8"))
    return path


def _digest(contents: bytes, meta: bytes) -> str:
    """엔진 해시. 본문 블록만이 아니라 contents.xml · meta.xml 전체(요약 코드 포함)를 본다."""
    return hashlib.sha256(contents + b"|" + meta).hexdigest()


def _stamp(path: Path) -> dict:
    try:
        with zipfile.ZipFile(path) as z:
            return json.loads(z.comment.decode("utf-8")) if z.comment else {}
    except (zipfile.BadZipFile, ValueError, OSError):
        return {}


def untouched(path: Path) -> bool:
    """엔진이 만든 그대로인 dsd 인지. 파일이 없으면 참(만들어도 된다)."""
    p = Path(path)
    if not p.exists():
        return True
    h = _stamp(p).get(STAMP)
    try:
        with zipfile.ZipFile(p) as z:
            return bool(h) and h == _digest(z.read("contents.xml"), z.read("meta.xml"))
    except Exception:  # noqa: BLE001  깨진 파일 · 항목이 다른 파일은 회계사 파일로 본다
        return False


def read_note_map(path: Path) -> dict[int, int] | None:
    m = _stamp(Path(path)).get("note-map") if Path(path).exists() else None
    return {int(k): int(v) for k, v in m.items()} if m else None


def parts_from_blocks(blocks: list) -> tuple[list[str], list[tuple[str, list]]]:
    """HTML 블록(read_html)을 write_dsd 의 입력 꼴로 되돌린다. (검토 전 상자 줄, 부분 목록). 회계사가 고친 HTML 로 dsd 를 만들 때 쓴다."""
    from .dart_file import WARN_TEXT, WARN_TITLE

    warn, parts, cur = [], [], None
    for b in blocks:
        if b[0] == "h" and b[1] == 1:
            cur = (b[2], [])
            parts.append(cur)
        elif cur is None:
            t = b[-1] if b[0] != "table" else ""
            if b[0] == "p" and norm(t) != norm(WARN_TEXT) and not norm(t) == norm(WARN_TITLE):
                warn.append(t[2:] if t.startswith("· ") else t)
        elif b[0] == "h":
            cur[1].append(("h", max(b[1] - 1, 1), b[2]))
        else:
            cur[1].append(b)
    return warn, parts


# ---------------------------------------------------------------- 읽기
def _text(e) -> str:
    """요소 안 글자 전체. &cr; 은 줄바꿈, 공백은 하나로 줄인다."""
    t = "".join(e.itertext()).replace(CR, "\n")
    return re.sub(r"\s+", " ", t).strip()


def _bold_level(mark: str | None) -> int | None:
    if not mark:
        return None
    toks = mark.split()
    if "B" not in toks:
        return None
    size = next((int(m.group(1)) for x in toks if (m := re.match(r"F-\D*(\d+)$", x))), None)
    if size is None or size == 12 or size == 13:
        return 3
    return 2 if size >= 14 else 4


def part_of(title: str) -> str | None:
    t = norm(title)
    if "외부감사실시내용" in t:
        return "외부감사 실시내용"
    if t in ("주석", "재무제표주석"):
        return "주석"
    if "재무제표" in t and ("첨부" in t or t == "재무제표"):
        return "(첨부) 재무제표"
    if "감사보고서" in t and "내부회계" not in t:
        return "감사보고서"
    return None


# 과목 앞 번호. 공개 원문에는 로마 숫자를 영문 · 유니코드로 섞어 쓴 것(「XⅠ.」 · 「Ⅹ I.」 · Ⅱ 대신 「∥.」)과 앞에 쉼표만 붙은 것도 있다
_LABEL_HEAD = re.compile(r"^\s*[,.]?\s*(?:[IVXⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ∥](?:\s?[IVXⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ∥])*\.|[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+|\d+\.|\(\d+\)|[가-하]\.)?\s*[,.]?\s*")
_LABEL_NOTE = re.compile(r"\s*\(\s*주\s*(?:석[^)]*|\d[\d,\s.]*)\)\s*$")       # 「(주석3,13)」 · 「(주11)」


def _label(s: str) -> str:
    s = _LABEL_NOTE.sub("", s)
    s = _LABEL_HEAD.sub("", s, count=1)
    return s.strip()


def _rows(t) -> list[list[str]]:
    rows = []
    for sec in t:
        if sec.tag not in ("THEAD", "TBODY"):
            continue
        for tr in sec.findall("TR"):
            rows.append([_text(c) for c in tr if c.tag in ("TD", "TH", "TE", "TU")])
    return rows


def _finance_rows(t) -> list[list[str]]:
    """FINANCE 표: 머리줄의 COLSPAN 으로 묶인 열(내역 · 합계)을 한 칸으로 합치고 과목 이름의 번호와 (주석 …) 를 뗀다."""
    head = t.find("THEAD/TR")
    if head is None:
        return _rows(t)
    spans = [int(c.get("COLSPAN") or 1) for c in head if c.tag in ("TH", "TD", "TE")]
    out = [[_text(c) for c in head if c.tag in ("TH", "TD", "TE")]]
    out[0][0] = _label(out[0][0]) if out[0] else ""
    for tr in t.findall("TBODY/TR"):
        cells = [_text(c) for c in tr if c.tag in ("TD", "TH", "TE", "TU")]
        row, i = [], 0
        for sp in spans:
            grp = [x for x in cells[i:i + sp] if x]
            row.append(grp[-1] if grp else "")
            i += sp
        if row:
            row[0] = _label(row[0])
        out.append(row)
    return out


class _Reader:
    def __init__(self):
        self.out, self.part, self.note, self.ntab, self.last_cap = [], None, None, 0, False

    def add(self, b):
        self.out.append(b)
        self.last_cap = b[0] == "cap"
        if b[0] == "h" and self.part == "주석":
            m = _NOTE.match(b[2])
            if m:
                self.note, self.ntab = int(m.group(1)), 0

    def para(self, t: str, mark: str | None = None):
        if not t:
            return
        if _CAP.match(t):
            self.add(("cap", t))
            return
        lv = _bold_level(mark)
        self.add(("h", lv, t) if lv else ("p", t))

    def table(self, t):
        rows0 = _rows(t)
        lines = [" ".join(x for x in r if x) for r in rows0]
        first = [next((x for x in r if x), "") for r in rows0]
        k = next((i for i, x in enumerate(first) if x.rstrip().endswith("귀중")), None)
        if self.part == "감사보고서" and k is not None and (t.get("BORDER") or "1").strip() == "0":
            # 수신인 표(회사명 줄 · 「주주 및 이사회 귀중」 줄)는 8820 의 한 문단이다. 오른쪽 칸(보고서일을 여기 적는 감사인이 있다)은 따로 읽는다
            self.add(("p", " ".join(x for x in first[:k + 1] if x)))
            for i, r in enumerate(rows0):
                rest = [x for x in r if x]
                for x in (rest[1:] if i <= k else rest):
                    self.add(("p", x))
            return
        if self.part == "감사보고서" and all(sum(1 for x in r if x) <= 1 for r in rows0):
            for line in lines:                                     # 서명 · 유효기간 안내처럼 한 칸짜리 표는 문단이다
                if line:
                    self.add(("p", line))
            return
        if (t.get("BORDER") or "1").strip() == "0":
            for line in lines:
                if line:
                    self.add(("p", line))
            return
        rows = _finance_rows(t) if t.get("ACLASS") == "FINANCE" else _rows(t)
        if self.part == "주석" and self.note is not None:
            self.ntab += 1
            if not self.last_cap:
                self.add(("cap", f"표 {self.note}-{self.ntab} (dsd 위치로 붙인 번호)", "synthetic"))
        self.add(("table", rows))

    def P(self, e):
        kids = [c for c in e if c.tag == "SPAN"]
        if self.part == "감사보고서" and sum(1 for k in kids if _bold_level(k.get("USERMARK"))) > 1:
            self.P_split(e)
            return
        if kids and not (e.text or "").replace(CR, "").strip() and _bold_level(kids[0].get("USERMARK")):
            first = kids[0]
            self.para(re.sub(r"\s+", " ", (first.text or "").replace(CR, " ")).strip(), first.get("USERMARK"))
            rest = (first.tail or "") + "".join(ET.tostring(c, encoding="unicode", method="text") for c in kids[1:])
            self.para(re.sub(r"\s+", " ", rest.replace(CR, " ")).strip())
            return
        self.para(_text(e), e.get("USERMARK"))

    def P_split(self, e):
        """감사보고서 절에서 한 P 안에 굵은 소제목 SPAN 이 여럿 이어진 꼴(공개 원문에 흔하다: 「감사의견근거」 SPAN 뒤에 본문,
        이어서 「기타사항」 SPAN ...)을 소제목마다 끊어 읽는다."""
        buf: list[str] = []

        def flush():
            self.para(re.sub(r"\s+", " ", "".join(buf).replace(CR, " ")).strip())
            buf.clear()

        buf.append(e.text or "")
        for c in e:
            t = "".join(c.itertext()) if c.tag == "SPAN" else ""
            if c.tag == "SPAN" and _bold_level(c.get("USERMARK")) and t.strip():
                flush()
                self.para(re.sub(r"\s+", " ", t.replace(CR, " ")).strip(), c.get("USERMARK"))
            else:
                buf.append(t)
            buf.append(c.tail or "")
        flush()

    def walk(self, e, depth_section: int = 0):
        from .dart_file import WARN_TITLE

        for c in e:
            tag = c.tag
            if tag in ("COVER", "TOC", "PGBRK", "COMMENT", "LIBRARYLIST", "FILENAME", "COLGROUP"):
                continue
            if tag == "WARNING":
                parts = [re.sub(r"\s+", " ", x).strip() for x in (c.text or "").split(CR)]
                if parts and norm(parts[0]) == norm(WARN_TITLE):
                    self.add(("h", 2, parts[0]))
                    for x in parts[1:]:
                        if x:
                            self.add(("p", x))
                continue
            if tag in ("SECTION-1", "SECTION-2", "SECTION-3"):
                title = c.find("TITLE")
                tt = _text(title) if title is not None else ""
                p = part_of(tt)
                if p:
                    self.part = p
                    self.add(("h", 1, p))
                    if p == "감사보고서" and norm(tt) != norm(p):
                        self.add(("h", 2, tt))      # 절 제목이 「독립된 감사인의 감사보고서」 면 8820 첫 제목과 같다
                elif tt:
                    self.add(("h", 2 if tag == "SECTION-1" else 3, tt))
                self.walk(c, depth_section + 1)
                continue
            if tag == "TITLE":
                if e.tag.startswith("SECTION"):
                    continue          # 절 제목은 위에서 읽었다
                t = _text(c)
                if t:
                    self.add(("h", 3, t))
                continue
            if tag == "P":
                self.P(c)
            elif tag == "TABLE":
                self.table(c)
            elif tag in ("INSERTION", "LIBRARY", "TABLE-GROUP", "PART"):
                self.walk(c, depth_section)
            elif tag == "SPAN":
                self.para(_text(c), c.get("USERMARK"))


_ENTITY = re.compile(r"&(?!(?:amp|lt|gt|quot|apos|#\d+|#x[0-9A-Fa-f]+);)")
_LT = re.compile(r"<(?![A-Za-z/!?])")


def lenient_xml(raw: bytes) -> bytes:
    """OpenDART 원문 XML 은 엄밀한 XML 이 아니다(공개 원문 204건 중 189건): 줄바꿈 표시 &cr; 가 개체로 그대로 있고(dsd 는 &amp;cr;),
    글자 안 꺾쇠(「<당기>」)가 이스케이프되지 않았다. 정의 안 된 &… 는 &amp;… 로, 태그 이름(영문)으로 시작하지 않는 < 는 &lt; 로 고친다."""
    try:
        s = raw.decode("utf-8")
    except UnicodeDecodeError:
        s = raw.decode("cp949", errors="replace")
    s = _LT.sub("&lt;", _ENTITY.sub("&amp;", s))
    s = re.sub(r'^(<\?xml[^>]*?encoding=")[^"]+"', r'\g<1>utf-8"', s, count=1)      # 다시 utf-8 로 쓰므로 선언도 맞춘다
    return s.encode("utf-8")


def read_dsd(path: Path) -> list:
    """dsd 를 블록 목록으로 읽는다. HTML(read_html)과 같은 꼴이다: 부분 이름은 h1, 그 안 제목은 h2 이하.
    .xml 이면 OpenDART 공시서류원본파일 XML(contents.xml 과 같은 dart4 · dart3 꼴, 편집기용 INSERTION 이 없는 판)로 읽는다."""
    if Path(path).suffix.lower() == ".xml":
        root = ET.fromstring(lenient_xml(Path(path).read_bytes()))
    else:
        with zipfile.ZipFile(Path(path)) as z:
            name = next((n for n in z.namelist() if n.lower().endswith("contents.xml")), None)
            if name is None:
                raise ValueError(f"dsd 안에 contents.xml 이 없습니다: {path}")
            root = ET.fromstring(z.read(name))
    body = root.find("BODY")
    r = _Reader()
    if body is not None:
        r.walk(body)
    real = any(b[0] == "cap" and len(b) == 2 for b in r.out)      # 「표 N-k」 설명이 하나라도 있으면 붙인 번호는 쓰지 않는다
    return [b[:2] if b[0] == "cap" else b for b in r.out if not (b[0] == "cap" and len(b) == 3 and real)]


# ---------------------------------------------------------------- 화면 표시(R9 묶음 B7): 만듦 여부 · 뼈대 비교
CF_FILE = "16_현금흐름표-간접법"


def skeleton(root) -> list[tuple]:
    """편집기 뼈대: BODY 아래 INSERTION(ABASISNUMBER · LIBRARYLIST) · LIBRARY · FILENAME · TABLE-GROUP · SECTION 과 값 표
    (FINANCE · EXTRACTION 의 ACLASS · BORDER · 열 수)를 문서 순서대로. 감사인의 감사보고서 INSERTION 안과 주석 절 본문은 보지 않는다
    (tests/test_dsd.py 의 샘플 대조와 같은 규칙)."""
    out = []

    def walk(e):
        for c in e:
            if c.tag == "INSERTION":
                lib = c.findtext("LIBRARYLIST")
                out.append(("INSERTION", c.get("ABASISNUMBER"), lib))
                if "감사인의 감사보고서" not in (lib or ""):
                    walk(c)
            elif c.tag == "FILENAME":
                out.append(("FILENAME", c.text))
            elif c.tag in ("TABLE-GROUP", "SECTION-1", "COVER", "TOC", "LIBRARY"):
                out.append((c.tag, c.get("ACLASS")))
                walk(c)
            elif c.tag == "SECTION-2":
                out.append((c.tag, c.get("ACLASS")))
                t = c.find("TITLE")
                if t is None or t.get("AASSOCNOTE") != ASSOC["주석"]:
                    walk(c)
            elif c.tag == "TABLE" and c.get("ACLASS") in ("FINANCE", "EXTRACTION"):
                out.append(("TABLE", c.get("ACLASS"), c.get("BORDER"), len(c.findall("COLGROUP/COL"))))

    body = root.find("BODY")
    if body is not None:
        walk(body)
    return out


def compare_skeleton(root) -> dict:
    """dsd 본문 뼈대를 틀(definitions/dart_dsd_frame.xml, 샘플 뼈대)과 견준다. 정해 둔 차이 둘은 빼고 본다:
    현금흐름표(자료가 없어 넣지 않은 자리)와 자본변동표 열 수(회사 자본 과목 수를 따름). {"ok", "checked", "diff": [문장]}"""
    import difflib

    f, e = skeleton(_frame()), skeleton(root)
    if ("FILENAME", CF_FILE) not in e and ("FILENAME", CF_FILE) in f:
        i = f.index(("FILENAME", CF_FILE)) - 1
        j = next((k for k in range(i + 1, len(f)) if f[k][0] == "INSERTION"), len(f))
        f = f[:i] + f[j:]
    for xs in (f, e):
        if ("TABLE-GROUP", "PEF-1") in xs:
            k = xs.index(("TABLE-GROUP", "PEF-1"))
            if k + 2 < len(xs) and xs[k + 2][0] == "TABLE":
                xs[k + 2] = xs[k + 2][:3]
    diff = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(a=f, b=e, autojunk=False).get_opcodes():
        if op == "equal":
            continue
        a = "; ".join(" ".join(str(v) for v in x if v is not None) for x in f[i1:i2][:3])
        b = "; ".join(" ".join(str(v) for v in x if v is not None) for x in e[j1:j2][:3])
        diff.append({"replace": f"틀 「{a}」 대신 「{b}」", "delete": f"틀에 있는 「{a}」 가 없음", "insert": f"틀에 없는 「{b}」 가 있음"}[op])
    return {"ok": not diff, "checked": len(f), "diff": diff}


def status(path: Path) -> dict:
    """화면 DART 조서에 보일 dsd 상태: 있는지 · 엔진이 만든 그대로인지 · 크기 · 뼈대 비교."""
    p = Path(path)
    out = {"exists": p.exists(), "untouched": None, "size": None, "skeleton": None, "error": None}
    if not p.exists():
        return out
    out["size"] = p.stat().st_size
    out["untouched"] = untouched(p)
    try:
        with zipfile.ZipFile(p) as z:
            root = ET.fromstring(z.read("contents.xml"))
        out["skeleton"] = compare_skeleton(root)
    except Exception as e:  # noqa: BLE001  깨진 zip · XML 은 그 사실만 보인다
        out["error"] = f"dsd 를 읽지 못함: {type(e).__name__}"
    return out
