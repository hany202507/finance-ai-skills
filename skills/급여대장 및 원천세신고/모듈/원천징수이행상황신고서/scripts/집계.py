# -*- coding: utf-8 -*-
"""지급자료 → 원천징수 집계표 엑셀 + 신고값 JSON.

급여대장(근로)과 그 밖의 원천징수 지급자료(사업 3.3%·일용·기타·퇴직 등)를 한 표로 모아
소득코드별로 집계하고, 가감계와 총합계를 규칙대로 만든다.

원칙
- 계산은 결정론이다. 소득세는 지급자료에 있는 값을 그대로 더한다. 다시 곱하지 않는다
- **지방소득세는 신고서에 안 들어간다.** 위택스 신고용으로 따로 집계만 해 둔다
- 소득코드를 못 정하는 행이 있으면 멈추고 묻는다. 추측해서 넣지 않는다
- 엑셀 합계는 값이 아니라 SUMIF 수식으로 남긴다. 사람이 근거를 따라갈 수 있어야 한다
"""
import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

# ── 소득코드 (규격서 표25) ────────────────────────────
소득구분명 = {
    "A01": "근로소득 간이세액", "A02": "근로소득 중도퇴사", "A03": "근로소득 일용근로",
    "A04": "근로소득 연말정산 합계", "A05": "근로소득 연말정산 분납신청",
    "A06": "근로소득 연말정산 납부금액", "A10": "근로소득 가감계",
    "A21": "퇴직소득 연금계좌", "A22": "퇴직소득 그 외", "A20": "퇴직소득 가감계",
    "A25": "사업소득 매월징수", "A26": "사업소득 연말정산", "A30": "사업소득 가감계",
    "A41": "기타소득 연금계좌", "A42": "기타소득 그 외", "A43": "기타소득 종교인(매월)",
    "A44": "기타소득 종교인(연말정산)", "A49": "기타소득 가상자산",
    "A59": "기타소득 인적용역", "A40": "기타소득 가감계",
    "A45": "연금소득 공적연금(매월)", "A46": "연금소득 연말정산",
    "A48": "연금소득 연금계좌", "A47": "연금소득 가감계",
    "A50": "이자소득", "A60": "배당소득", "A69": "저축해지 추징세액 등",
    "A70": "비거주자 양도소득", "A71": "금융투자소득", "A80": "내외국법인 원천",
    "A90": "수정신고(세액)", "A99": "총합계",
}

# 가감계 = 구성 코드의 합
가감계규칙 = {
    "A10": ["A01", "A02", "A03", "A04"],
    "A20": ["A21", "A22"],
    "A30": ["A25", "A26"],
    "A40": ["A41", "A42", "A43", "A44", "A49", "A59"],
    "A47": ["A45", "A46", "A48"],
}
# 총합계 = 가감계 + 가감계가 없는 단독 코드
총합계구성 = list(가감계규칙) + ["A50", "A60", "A69", "A70", "A71", "A80", "A90"]

# 세목코드 (규격서 표31). 헤더에 넣는 대표 세목
세목 = {"근로": "14", "사업": "13", "기타": "16", "퇴직": "21",
        "이자": "11", "배당": "12", "연금": "17"}

열별칭 = {
    "성명": ["성명", "이름", "성 명", "소득자", "소득자명"],
    "사번": ["사번", "사원번호", "사원코드"],
    "총지급액": ["총지급액", "지급총액", "지급계", "총 지급액", "지급액"],
    "소득세": ["소득세", "근로소득세", "갑근세", "원천징수세액", "소득세등"],
    "지방소득세": ["지방소득세", "지방세", "주민세"],
    "농특세": ["농특세", "농어촌특별세"],
    "소득구분": ["소득구분", "구분코드", "소득코드", "구분", "소득종류", "고용형태"],
    "입사일": ["입사일", "입사일자"],
    "퇴사일": ["퇴사일", "퇴사일자"],
    "지급월": ["지급월", "귀속월", "귀속연월"],
    "비고": ["비고", "메모", "참고", "적요"],
}
지급항목열 = ['기본급', '연장수당', '연장·야간·휴일수당', '야간수당', '휴일수당',
              '직책수당', '식대', '자가운전보조금', '육아수당', '국외근로수당',
              '출산지원금', '생산직 연장수당', '연구보조비', '단체보장성보험료',
              '상여금', '기타수당', '일용급여', '용역대가', '퇴직금']


# 신고서 총지급액은 비과세를 포함하되, 지급명세서 제출이 면제되는 비과세는 뺀다
# (서식 작성방법 → 소득세법 시행령 §214①2의2·2의3). 우리 대장에 나오는 것 중에는 자가운전보조금
# (령 §12 3호)이 그것이다. 식대(법 §12 3호 러목)·육아수당·국외근로(거목)는 면제 목록에 없어 남긴다.
면제비과세열 = ["자가운전보조금", "자가운전", "차량유지비", "여비", "일직료", "숙직료",
              "제복", "작업복", "선원식료"]


class 확인필요(Exception):
    """사람이 정해야 하는 것. 추측하지 않고 멈춘다."""


# 대장의 구분 글자 → 소득코드. 앞에 있는 것이 먼저 맞는다 (중도퇴사·퇴직을 상용보다 먼저 본다)
구분코드 = [
    (("중도퇴사", "중도정산", "퇴사정산", "정산"), "A02"),
    (("퇴직금", "퇴직소득", "퇴직급여"), "A22"),
    (("일용", "아르바이트", "알바", "단기"), "A03"),
    (("프리랜서", "사업소득", "사업", "용역", "3.3"), "A25"),
    (("기타소득", "기타"), "A42"),
    (("상용", "정규", "정직원", "근로", "직원", "월급"), "A01"),
]


def 코드로(구분, 기본코드="A01"):
    """구분 칸의 글자를 소득코드로. 이미 코드면 그대로. 모르면 확인필요."""
    t = str(구분 or "").strip()
    if not t:
        return 기본코드
    if re.fullmatch(r"A\d\d", t.upper()):
        return t.upper()
    for 말들, 코드 in 구분코드:
        if any(m in t for m in 말들):
            return 코드
    raise 확인필요(f"구분 「{t}」 을 소득코드로 못 옮겼습니다. 규격서 표25 의 코드로 정해주세요")


def _num(v):
    if v is None or v == "":
        return 0
    if isinstance(v, str):
        v = v.replace(",", "").replace(" ", "").replace("　", "")
        if v in ("", "-"):
            return 0
    try:
        return int(Decimal(str(v)))
    except (InvalidOperation, ValueError):
        return 0


def 귀속시트(wb, 귀속연월):
    """귀속연월(YYYYMM)에 맞는 시트. 노무법인 대장은 달마다 시트가 쌓인다."""
    y, m = 귀속연월[:4], int(귀속연월[4:6])
    후보 = {f"{m}월", f"{m:02d}월", f"{y}-{m:02d}", f"{y}.{m:02d}", f"{y}.{m}", f"{y}{m:02d}", f"{y}년{m}월"}
    맞는 = [n for n in wb.sheetnames if any(h in n.replace(" ", "") for h in 후보)]
    if len(맞는) == 1:
        return wb[맞는[0]]
    if len(wb.sheetnames) == 1:
        return wb[wb.sheetnames[0]]
    if not 맞는 and "급여대장" in wb.sheetnames:         # 급여대장 스킬 출력은 달마다 파일 하나, 시트 넷이다
        ws = wb["급여대장"]
        제목달 = re.search(r"(20\d{2})-(0[1-9]|1[0-2])", str(ws["A1"].value or ""))
        if 제목달 and 제목달.group(1) + 제목달.group(2) != 귀속연월:
            raise 확인필요(f"「급여대장」 시트 제목은 {제목달.group(0)} 인데 귀속연월은 {귀속연월} 입니다. 어느 쪽이 맞는지 정해 주세요")
        return ws
    raise 확인필요(f"{귀속연월} 귀속 시트를 못 골랐습니다. 시트: {', '.join(wb.sheetnames)}. sheet= 로 지정해 주세요")


def read_ledger(xlsx, sheet=None, 기본코드="A01", 귀속연월=None, 정보=None):
    """급여대장에서 인별 행을 읽는다. 머리행은 성명과 총지급액이 같이 있는 줄.

    정보 에 dict 를 넘기면 시트 목록·고른 시트·면제열·대장에 있던 지급항목을 담아 준다.
    확인사항을 규칙으로 세우려면 「대장이 어떻게 생겼는지」가 필요한데, 행만 봐서는 모른다.
    """
    wb = openpyxl.load_workbook(xlsx, data_only=True)
    if sheet:
        ws = wb[sheet]
    elif 귀속연월:
        ws = 귀속시트(wb, 귀속연월)
    else:
        ws = wb[wb.sheetnames[0]]

    머리, 열, 항목열, 면제열 = None, {}, {}, {}
    for r in range(1, min(ws.max_row, 30) + 1):
        vals = {}
        for c in range(1, ws.max_column + 1):
            v = ws.cell(r, c).value
            if isinstance(v, str):
                t = v.strip()
                for key, names in 열별칭.items():
                    if t in names:
                        vals[key] = c
        if "성명" in vals and "총지급액" in vals:
            머리, 열 = r, vals
            항목열 = {ws.cell(r, c).value.strip(): c for c in range(1, ws.max_column + 1)
                      if isinstance(ws.cell(r, c).value, str)
                      and ws.cell(r, c).value.strip() in 지급항목열}
            면제열 = {ws.cell(r, c).value.strip(): c for c in range(1, ws.max_column + 1)
                      if isinstance(ws.cell(r, c).value, str)
                      and ws.cell(r, c).value.strip() in 면제비과세열}
            break
    if 머리 is None:
        raise 확인필요("성명과 총지급액 열을 못 찾았습니다. 열 이름을 알려주시면 별칭에 넣겠습니다")
    if "소득세" not in 열:                             # 0 으로 두면 신고서가 0원으로 나오고 아무도 모른다
        있는열 = [str(ws.cell(머리, c).value).strip() for c in range(1, ws.max_column + 1)
                  if ws.cell(머리, c).value not in (None, "")]
        raise 확인필요(f"소득세 열을 못 찾았습니다. 대장 머리행: {', '.join(있는열)}. "
                       "소득세 열 이름을 알려주시면 별칭에 넣겠습니다")

    사람 = []
    for r in range(머리 + 1, ws.max_row + 1):
        이름 = ws.cell(r, 열["성명"]).value
        if not 이름 or not str(이름).strip():
            continue
        t = str(이름).replace(" ", "")
        if t in ("계", "합계", "총계", "소계") or t.endswith("소계") or t.endswith("합계"):
            continue                                    # 집계 줄은 사람이 아니다
        사람행 = any(ws.cell(r, 열[k]).value not in (None, "")
                     for k in ("사번", "입사일") if k in 열)
        if not 사람행 and ("사번" in 열 or "입사일" in 열):
            continue                                    # 합계행·참고표를 걸러낸다
        총 = _num(ws.cell(r, 열["총지급액"]).value)
        if 총 == 0 and 항목열:
            총 = sum(_num(ws.cell(r, c).value) for c in 항목열.values())
        if 총 == 0:
            continue
        면제 = sum(_num(ws.cell(r, c).value) for c in 면제열.values())
        g = lambda k: _num(ws.cell(r, 열[k]).value) if k in 열 else 0
        코드 = 코드로(ws.cell(r, 열["소득구분"]).value if "소득구분" in 열 else "", 기본코드)
        사람.append({"성명": str(이름).strip(), "소득코드": 코드,
                     "대장총지급액": 총, "면제비과세": 면제, "총지급액": 총 - 면제,
                     "소득세": g("소득세"), "지방소득세": g("지방소득세"),
                     "농특세": g("농특세"), "출처": Path(str(xlsx)).name,
                     "퇴사일": ws.cell(r, 열["퇴사일"]).value if "퇴사일" in 열 else None,
                     "비고": ws.cell(r, 열["비고"]).value if "비고" in 열 else None})
    if not 사람:
        raise 확인필요("인별 행을 하나도 못 읽었습니다")
    if 정보 is not None:
        정보.update({"시트목록": list(wb.sheetnames), "시트": ws.title,
                     "면제열": list(면제열), "지급항목": list(항목열), "머리행": 머리})
    return 사람


def 집계(행들):
    """소득코드별로 묶고 가감계·총합계를 만든다."""
    for p in 행들:
        if p["소득코드"] not in 소득구분명:
            raise 확인필요(
                f"{p['성명']} 의 소득코드 {p['소득코드']} 를 모르겠습니다. "
                "규격서 표25 의 코드로 정해주세요")
    묶음 = {}
    for p in 행들:
        g = 묶음.setdefault(p["소득코드"], {"인원": 0, "총지급액": 0, "소득세": 0,
                                            "농특세": 0, "지방소득세": 0})
        g["인원"] += 1
        for k in ("총지급액", "소득세", "농특세", "지방소득세"):
            g[k] += p[k]

    for 계, 구성 in 가감계규칙.items():
        있음 = [c for c in 구성 if c in 묶음]
        if 있음:
            묶음[계] = {k: sum(묶음[c][k] for c in 있음)
                        for k in ("인원", "총지급액", "소득세", "농특세", "지방소득세")}
    총 = [c for c in 총합계구성 if c in 묶음]
    묶음["A99"] = {k: sum(묶음[c][k] for c in 총)
                   for k in ("인원", "총지급액", "소득세", "농특세", "지방소득세")}
    return 묶음


def 신고값(묶음, 회사, 기간, 환급=None, 플래그=None, 납부코드=None):
    """홈택스전자신고 스킬에 넘길 JSON 구조. 납부세액은 가감계와 총합계에만 적는다."""
    납부 = set(납부코드 or (list(가감계규칙) + ["A99"]))
    명세 = []
    for code in sorted(묶음):
        g = 묶음[code]
        세 = g["소득세"]
        명세.append([code, g["인원"], g["총지급액"], 세, g["농특세"], 0, 0,
                     max(세, 0) if code in 납부 else 0, 0])
    return {"회사": 회사, "기간": 기간, "명세": 명세,
            "환급": 환급 or {}, "플래그": 플래그 or {},
            "위택스_지방소득세": 묶음["A99"]["지방소득세"]}


# ── 엑셀 ───────────────────────────────────────────────
얇 = Side(style="thin", color="BBBBBB")
테 = Border(left=얇, right=얇, top=얇, bottom=얇)
머리채움 = PatternFill("solid", fgColor="EEEEEE")


def _머리(ws, row, names, widths=None):
    for j, n in enumerate(names, start=1):
        c = ws.cell(row, j, n)
        c.font = Font(bold=True)
        c.fill = 머리채움
        c.alignment = Alignment(horizontal="center")
        c.border = 테
    if widths:
        for col, w in zip("ABCDEFGH", widths):
            ws.column_dimensions[col].width = w


def write_workbook(경로, 회사, 기간, 행들, 묶음, 확인사항=(), 환급=None):
    """시트 넷. 지급내역 → 집계 → 신고서 순으로 전부 수식이라 셀을 누르면 근거로 내려간다.

    지급내역   인별 행. 급여대장에서 읽은 그대로
    집계       소득코드별 COUNTIF·SUMIF. 가감계와 총합계
    신고서     원천징수이행상황신고서 서식 배치. 모든 숫자가 집계 시트를 가리키는 수식
    확인사항   사람이 정해야 하는 것
    """
    wb = openpyxl.Workbook()

    # ── 지급내역 ──
    ws = wb.active
    ws.title = "지급내역"
    _머리(ws, 1, ["성명", "소득코드", "소득구분", "대장총지급액", "면제비과세", "총지급액",
                  "소득세", "농특세", "지방소득세", "출처"],
          (14, 10, 22, 15, 12, 15, 14, 12, 14, 26))
    ws.column_dimensions["J"].width = 26
    for i, p in enumerate(행들, start=2):
        for j, v in enumerate([p["성명"], p["소득코드"], 소득구분명.get(p["소득코드"], ""),
                               p.get("대장총지급액", p["총지급액"]), p.get("면제비과세", 0),
                               p["총지급액"], p["소득세"], p["농특세"],
                               p["지방소득세"], p["출처"]], start=1):
            c = ws.cell(i, j, v)
            c.border = 테
            if j in (4, 5, 6, 7, 8, 9):
                c.number_format = "#,##0;-#,##0"
    ws.cell(len(행들) + 3, 1, "총지급액 = 대장총지급액 − 면제비과세. 면제비과세는 지급명세서 제출이 면제되는 "
                             "비과세(시행령 §214①2의2·2의3)로, 자가운전보조금이 그것이다. "
                             "식대·육아수당·국외근로는 비과세여도 총지급액에 남긴다").font = Font(size=9, color="666666")
    끝 = len(행들) + 1

    # ── 집계 ──
    ws2 = wb.create_sheet("집계")
    ws2["A1"] = "소득코드별 집계"
    ws2["A1"].font = Font(size=13, bold=True)
    ws2["A2"] = "지급내역 시트를 COUNTIF·SUMIF 로 모은 것. 신고서 시트가 여기를 가리킵니다"
    ws2["A2"].font = Font(size=9, color="666666")
    행 = 4
    _머리(ws2, 행, ["코드", "소득구분", "인원", "총지급액", "소득세등", "농특세"],
          (10, 24, 10, 16, 14, 12))
    detail = [c for c in sorted(묶음) if c not in 가감계규칙 and c != "A99"]
    for i, code in enumerate(detail, start=1):
        r = 행 + i
        ws2.cell(r, 1, code).border = 테
        ws2.cell(r, 2, 소득구분명.get(code, "")).border = 테
        for j, col in zip(range(3, 7), ("B", "F", "G", "H")):
            함수 = "COUNTIF" if j == 3 else "SUMIF"
            인자 = (f"지급내역!$B$2:$B${끝},$A{r}" if j == 3
                    else f"지급내역!$B$2:$B${끝},$A{r},지급내역!${col}$2:${col}${끝}")
            c = ws2.cell(r, j, f"={함수}({인자})")
            c.number_format = "#,##0"
            c.border = 테
    맨끝 = 행 + len(detail)

    r = 맨끝 + 1
    가감계행 = []
    for 계, 구성 in 가감계규칙.items():
        있음 = [c for c in 구성 if c in 묶음]
        if not 있음:
            continue
        r += 1
        가감계행.append(r)
        ws2.cell(r, 1, 계).font = Font(bold=True)
        ws2.cell(r, 2, 소득구분명[계]).font = Font(bold=True)
        for j in range(3, 7):
            칸 = [f"{chr(64+j)}{행+1+detail.index(c)}" for c in 있음]
            c = ws2.cell(r, j, "=" + "+".join(칸))
            c.number_format = "#,##0"
            c.font = Font(bold=True)
            c.border = 테
    r += 1
    # 총합계 = 가감계 전부 + 가감계가 없는 단독코드(이자·배당·법인원천…).
    # 가감계 블록만 더하면 단독코드가 통째로 빠진다. 셀을 하나씩 짚어 그 사고를 막는다.
    단독행 = [행 + 1 + detail.index(c) for c in detail if c in 총합계구성]
    ws2.cell(r, 1, "A99").font = Font(bold=True)
    ws2.cell(r, 2, "총합계").font = Font(bold=True)
    for j in range(3, 7):
        L = chr(64 + j)
        칸 = [f"{L}{x}" for x in 가감계행 + 단독행]
        c = ws2.cell(r, j, ("=" + "+".join(칸)) if 칸 else 0)
        c.number_format = "#,##0"
        c.font = Font(bold=True)
        c.border = 테
    집계끝 = r
    ws2.cell(r + 2, 1, "지방소득세는 이 신고서에 들어가지 않습니다. 위택스에 따로 신고합니다")
    ws2.cell(r + 3, 1, f"위택스 신고액(개인별 절사 합) {묶음['A99']['지방소득세']:,}원")

    # ── 신고서 (서식 배치) ──
    ws3 = wb.create_sheet("신고서")
    _신고서서식(ws3, 회사, 기간, 행, 집계끝, 환급 or {})

    # ── 확인사항 ──
    ws4 = wb.create_sheet("확인사항")
    _머리(ws4, 1, ["항목", "왜 확인해야 하나", "정한 값"], (30, 60, 20))
    for i, 줄 in enumerate(확인사항, start=2):
        항목, 이유 = 줄[0], 줄[1]
        정한값 = 줄[2] if len(줄) > 2 else ""      # 답을 받았으면 여기 남긴다
        ws4.cell(i, 1, 항목).border = 테
        ws4.cell(i, 2, 이유).border = 테
        ws4.cell(i, 3, 정한값).border = 테
        for j in (2, 3):
            ws4.cell(i, j).alignment = Alignment(wrap_text=True, vertical="top")
        if not 정한값:
            ws4.cell(i, 3).fill = PatternFill("solid", fgColor="FFF3CD")

    wb.save(경로)
    return 경로


# 서식의 행 순서. (구분, 소득종류, 코드). 구분이 None 이면 앞 줄과 같은 구분
서식행 = [
    ("근로소득", "간이세액", "A01"), (None, "중도퇴사", "A02"), (None, "일용근로", "A03"),
    (None, "연말정산 합계", "A04"), (None, "연말정산 분납신청", "A05"),
    (None, "연말정산 납부금액", "A06"), (None, "가감계", "A10"),
    ("퇴직소득", "연금계좌", "A21"), (None, "그 외", "A22"), (None, "가감계", "A20"),
    ("사업소득", "매월징수", "A25"), (None, "연말정산", "A26"), (None, "가감계", "A30"),
    ("기타소득", "연금계좌", "A41"), (None, "종교인소득 매월징수", "A43"),
    (None, "종교인소득 연말정산", "A44"), (None, "가상자산", "A49"),
    (None, "인적용역", "A59"), (None, "그 외", "A42"), (None, "가감계", "A40"),
    ("연금소득", "연금계좌", "A48"), (None, "공적연금(매월)", "A45"),
    (None, "연말정산", "A46"), (None, "가감계", "A47"),
    ("이자소득", "이자소득", "A50"), ("배당소득", "배당소득", "A60"),
    ("그 외", "저축 등 해지 추징세액 등", "A69"),
    ("비거주자", "양도소득", "A70"), ("금융투자소득", "금융투자소득", "A71"),
    ("법인 원천", "내·외국법인원천", "A80"), ("수정신고", "수정신고(세액)", "A90"),
    ("총합계", "총합계", "A99"),
]
납부적는코드 = set(가감계규칙) | set(총합계구성) | {"A99"}
굵은채움 = PatternFill("solid", fgColor="F5F5F5")
입력채움 = PatternFill("solid", fgColor="FFF9E6")
숨김0 = "#,##0;-#,##0;"     # 0 은 빈칸으로 보인다. 값은 숫자 그대로


def _신고서서식(ws, 회사, 기간, 집계머리, 집계끝, 환급):
    """원천징수이행상황신고서 서식 배치. 숫자 칸은 전부 집계 시트를 가리키는 SUMIF."""
    ws["A1"] = "원천징수이행상황신고서"
    ws["A1"].font = Font(size=15, bold=True)
    ws["A1"].alignment = Alignment(horizontal="center")
    ws.merge_cells("A1:K1")
    ws["A2"] = ("검토 방법: 숫자 칸을 누르면 집계 시트로, 집계 시트를 누르면 지급내역으로 "
                "내려갑니다. 값을 직접 고치지 않습니다")
    ws["A2"].font = Font(size=9, color="666666")

    머리 = [("① 신고구분", 기간.get("신고구분", "매월"), "② 귀속연월", 기간["귀속연월"],
             "③ 지급연월", 기간["지급연월"]),
            ("법인명(상호)", 회사.get("상호", ""), "대표자", 회사.get("대표자", ""),
             "사업자등록번호", 회사.get("사업자번호", "")),
            ("사업장 소재지", 회사.get("소재지", ""), "제출연월", 기간.get("제출연월", ""),
             "작성일자", 기간.get("작성일자", ""))]
    열자리 = (1, 2, 5, 6, 9, 10)
    for i, 줄 in enumerate(머리, start=4):
        for k, v in enumerate(줄):
            c = ws.cell(i, 열자리[k], v)
            c.border = 테
            if k % 2 == 0:
                c.font = Font(bold=True)
                c.fill = 머리채움
        ws.merge_cells(start_row=i, start_column=2, end_row=i, end_column=4)
        ws.merge_cells(start_row=i, start_column=6, end_row=i, end_column=8)
        ws.merge_cells(start_row=i, start_column=10, end_row=i, end_column=11)

    ws["A8"] = "1. 원천징수 명세 및 납부세액"
    ws["A8"].font = Font(bold=True, size=11)

    r0 = 9
    위 = ["소득자 소득구분", None, "코드", "원천징수명세", None, None, None, None,
          "⑨ 당월 조정 환급세액", "납부세액", None]
    아래 = ["구분", "소득종류", "코드", "④ 인원", "⑤ 총지급액", "⑥ 소득세등",
            "⑦ 농어촌특별세", "⑧ 가산세", "⑨ 당월조정환급세액", "⑩ 소득세등", "⑪ 농어촌특별세"]
    for j, v in enumerate(위, start=1):
        c = ws.cell(r0, j, v)
        c.font = Font(bold=True)
        c.fill = 머리채움
        c.border = 테
        c.alignment = Alignment(horizontal="center", vertical="center")
    for j, v in enumerate(아래, start=1):
        c = ws.cell(r0 + 1, j, v)
        c.font = Font(bold=True)
        c.fill = 머리채움
        c.border = 테
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.merge_cells(start_row=r0, start_column=1, end_row=r0, end_column=2)
    ws.merge_cells(start_row=r0, start_column=4, end_row=r0, end_column=8)
    ws.merge_cells(start_row=r0, start_column=10, end_row=r0, end_column=11)
    ws.row_dimensions[r0 + 1].height = 30

    코드범위 = f"집계!$A${집계머리+1}:$A${집계끝}"
    집계열 = {"D": "C", "E": "D", "F": "E", "G": "F"}    # 신고서 열 → 집계 열
    첫 = r0 + 2
    구분시작 = {}
    납부행 = []          # ⑩⑪ 을 적는 줄 = 가감계 + 단독코드 (A99 는 이들의 합)
    for i, (구분, 종류, 코드) in enumerate(서식행):
        r = 첫 + i
        굵게 = 코드 in 납부적는코드
        if 구분:
            구분시작[r] = 구분
            ws.cell(r, 1, 구분).font = Font(bold=True)
        ws.cell(r, 2, 종류)
        ws.cell(r, 3, 코드).alignment = Alignment(horizontal="center")
        for 열, 집열 in 집계열.items():
            c = ws[f"{열}{r}"]
            c.value = f"=SUMIF({코드범위},$C{r},집계!${집열}${집계머리+1}:${집열}${집계끝})"
            c.number_format = 숨김0
        ws[f"H{r}"] = 0                     # 가산세. 있으면 여기 적는다
        ws[f"H{r}"].number_format = 숨김0
        ws[f"I{r}"] = 0                     # 당월 조정 환급세액. 환급 조정에서 정한다
        ws[f"I{r}"].number_format = 숨김0
        if 굵게:
            # ⑩ = ⑥징수세액 + ⑧가산세 − ⑨당월조정환급세액, 하한 0.
            # 규격서 표 머리가 「납부세액 / 소득세등(가산세 포함)」이고, 이 칸은
            # '양의정수형식점검' 대상이라 음수로 나가면 형식검증에서 걸린다.
            # 가감계가 음수면 그 금액은 ⑮일반환급으로 넘어간다.
            ws[f"J{r}"] = f"=MAX(0,F{r}+H{r}-I{r})"
            ws[f"K{r}"] = f"=MAX(0,G{r})"
            납부행.append(r)
            ws[f"J{r}"].number_format = 숨김0
            ws[f"K{r}"].number_format = 숨김0
        for j in range(1, 12):
            c = ws.cell(r, j)
            c.border = 테
            if 굵게:
                c.font = Font(bold=True)
                c.fill = 굵은채움
        for 열 in ("H", "I"):
            ws[f"{열}{r}"].fill = 입력채움
    끝 = 첫 + len(서식행) - 1
    총합계행 = 끝
    조정행 = [x for x in 납부행 if x != 총합계행]
    # A99 는 위 줄들의 합이다. 따로 F−I 로 다시 계산하면 각 줄에 환급을 배분한 순간 어긋난다
    if 조정행:
        for L in ("I", "J", "K"):
            ws[f"{L}{총합계행}"] = "=" + "+".join(f"{L}{x}" for x in 조정행)
            ws[f"{L}{총합계행}"].number_format = 숨김0
        ws[f"I{총합계행}"].fill = 굵은채움
    # 같은 구분은 세로로 합친다
    시작들 = sorted(구분시작)
    for a, b in zip(시작들, 시작들[1:] + [끝 + 1]):
        if b - a > 1:
            ws.merge_cells(start_row=a, start_column=1, end_row=b - 1, end_column=1)
            ws.cell(a, 1).alignment = Alignment(vertical="center")

    # ── 2. 환급세액 조정 ──
    r = 끝 + 2
    ws.cell(r, 1, "2. 환급세액 조정").font = Font(bold=True, size=11)
    항목 = ["⑫ 전월 미환급세액", "⑬ 기환급 신청세액", "⑭ 차감잔액 (⑫-⑬)",
            "⑮ 일반환급", "⑯ 신탁재산",
            "⑰ 그 밖의 환급세액 금융회사 등", "⑰ 그 밖의 환급세액 합병 등",
            "⑱ 조정대상 환급세액 (⑭+⑮+⑯+⑰)",
            "⑲ 당월조정 환급세액계", "⑳ 차월이월 환급세액 (⑱-⑲)", "㉑ 환급신청액"]
    for j, v in enumerate(항목, start=1):
        c = ws.cell(r + 1, j, v)
        c.font = Font(bold=True, size=9)
        c.fill = 머리채움
        c.border = 테
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[r + 1].height = 42
    rv = r + 2
    입력 = {1: 환급.get("전월미환급세액", 0), 2: 환급.get("기환급신청세액", 0),
            4: 환급.get("일반환급", 0), 5: 환급.get("신탁재산", 0),
            6: 환급.get("금융회사등", 0), 7: 환급.get("합병등", 0),
            11: 환급.get("환급신청액", 0)}

    def L(j):
        return chr(64 + j)

    for j in range(1, 12):
        c = ws.cell(rv, j)
        if j in 입력:
            c.value = 입력[j]
            c.fill = 입력채움
        elif j == 3:
            c.value = f"={L(1)}{rv}-{L(2)}{rv}"
        elif j == 8:
            c.value = f"={L(3)}{rv}+{L(4)}{rv}+{L(5)}{rv}+{L(6)}{rv}+{L(7)}{rv}"
        elif j == 9:
            # ⑲ = 각 소득의 가감계 항목에 적은 ⑨당월조정환급세액의 합계 (규격서 10번 항목).
            # A99 의 ⑨ 하나만 가리키면 각 줄에 배분한 환급이 여기 안 잡혀,
            # 같은 환급이 ⑳차월이월에 또 남는다
            c.value = ("=" + "+".join(f"I{x}" for x in 조정행)) if 조정행 else 0
        elif j == 10:
            c.value = f"={L(8)}{rv}-{L(9)}{rv}"
        c.number_format = 숨김0
        c.border = 테

    ws.cell(rv + 2, 1, "노란 칸은 입력값입니다. 가산세·조정환급·환급조정은 급여대장에 없으므로 "
                       "확인사항을 보고 사람이 적습니다").font = Font(size=9, color="666666")
    ws.cell(rv + 3, 1, "지방소득세는 이 신고서에 들어가지 않습니다. 위택스에 따로 신고합니다"
            ).font = Font(size=9, color="666666")

    for col, w in zip("ABCDEFGHIJK", (11, 20, 7, 8, 14, 13, 11, 9, 12, 13, 11)):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = f"D{첫}"

기본확인사항 = [
    ("중도퇴사자 정산", "중도퇴사 정산으로 환급이 생기면 A02 소득세가 음수입니다. 급여대장에는 안 보입니다"),
    ("전월미환급세액", "있으면 자료구분 22 의 (12)에 넣고 (19)당월조정환급세액계까지 이어집니다"),
    ("반기납부 여부", "반기면 귀속연월은 반기 시작월, 지급연월은 반기 종료월입니다"),
    ("근로소득 밖의 지급", "사업 3.3%·일용·기타소득 지급이 있었는지. 있으면 그 코드로 행을 더 넣습니다"),
    ("비과세 총지급액 처리", "총지급액에 넣을 비과세 범위를 달마다 다르게 잡으면 지급명세서와 어긋납니다"),
]


def run(급여대장, 회사, 기간, 출력폴더=".", sheet=None, 추가행=(), 환급=None, 플래그=None,
        행수정=None, 확인사항=None):
    """행수정 은 대장에서 읽은 행 하나를 받아 고쳐 돌려주는 함수다.

    비과세를 총지급액에서 빼는 것처럼 **금액만 바뀌고 인원은 그대로인** 조정에 쓴다.
    추가행으로 넣으면 인원이 같이 늘어 A01 인원이 틀린다.
    """
    행들 = [dict(r) for r in read_ledger(급여대장, sheet=sheet, 귀속연월=기간.get("귀속연월"))]
    if 행수정:
        행들 = [행수정(r) or r for r in 행들]
    행들 = 행들 + [dict(r) for r in 추가행]
    묶음 = 집계(행들)
    out = Path(출력폴더)
    out.mkdir(parents=True, exist_ok=True)
    ym = 기간["귀속연월"]
    xlsx = write_workbook(out / f"원천징수집계_{ym}.xlsx", 회사, 기간, 행들, 묶음,
                          확인사항 if 확인사항 is not None else 기본확인사항, 환급=환급)
    값 = 신고값(묶음, 회사, 기간, 환급, 플래그)
    js = out / f"신고값_{ym}.json"
    js.write_text(json.dumps(값, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"엑셀": str(xlsx), "신고값": str(js), "묶음": 묶음, "행수": len(행들)}
