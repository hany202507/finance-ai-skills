# -*- coding: utf-8 -*-
"""회사기초정보 엑셀을 만든다. 홈택스 업로드 파일(C103900)에 들어가야 하는데 신고서에는 없는 값들.

    python make_company_info_xlsx.py <출력.xlsx> [설정.json]      # 설정 JSON 이 있으면 그 값을 채워 넣는다

시트 「회사기초정보」 한 장. 노란 칸(값)만 채운다. 생성기(make_c103900.py --설정 <이 파일>)가 키 열로 읽는다.
"""
import json
import sys
from pathlib import Path

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

FONT = "맑은 고딕"
YELLOW = PatternFill("solid", fgColor="FFFF00")
GRAY = PatternFill("solid", fgColor="F2F2F2")
HEAD = PatternFill("solid", fgColor="D9E1F2")
THIN = Side(style="thin", color="BFBFBF")
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)

# (구분, 항목, 키, 필수, 형식·예시, 어디에 쓰이나)
ROWS = [
    ("회사 식별", "사업자등록번호", "사업자번호", "필수", "숫자 10자리, 하이픈 없이 (1234512345)", "헤더 납세자ID. 신고서 시트 J5 와 같아야 한다 (규격서 표1 #3)"),
    ("회사 식별", "상호(법인명)", "상호", "필수", "사업자등록증 그대로 (주식회사 샘플)", "헤더 법인명 (표1 #17). 영문 상호는 소리나는 대로 한글로"),
    ("회사 식별", "대표자 성명", "대표자", "필수", "홍길동 (성·이름 붙여서)", "헤더 대표자명 (표1 #21)"),
    ("홈택스 신고", "홈택스 사용자 ID", "사용자ID", "필수", "홈택스 로그인 ID. 세무대리인이 올리면 대리인 ID", "헤더 사용자ID (표1 #11). 틀리면 접수 자체가 안 된다"),
    ("홈택스 신고", "신고 종류", "신고구분상세코드", "필수", "01 정기 / 02 수정 / 03 기한후", "파일명 끝 두 자리·민원종류코드 (표1 #6·12)"),
    ("홈택스 신고", "납부 주기", "원천신고구분", "필수", "매월 / 반기", "헤더 원천신고구분 (표1 #22). 신고서 시트 B4 와 같아야 한다"),
    ("홈택스 신고", "세무프로그램 업체코드", "세무프로그램코드", "필수", "9000 (규격서 문구) 또는 9999. 업체코드가 있으면 그것", "헤더 세무프로그램코드 (표1 #34)"),
    ("세무대리인", "세무대리인 명의 신고 여부", "세무대리인신고여부", "필수", "Y / N", "N 이면 아래 넷은 비운다"),
    ("세무대리인", "세무대리인 사업자번호", "세무대리인사업자번호", "대리 신고 시", "숫자 10자리", "표1 #13"),
    ("세무대리인", "세무대리인 성명", "세무대리인성명", "대리 신고 시", "", "표1 #14"),
    ("세무대리인", "세무대리인 관리번호", "세무대리인관리번호", "대리 신고 시", "6자리", "표1 #15"),
    ("세무대리인", "세무대리인 전화번호", "세무대리인전화번호", "대리 신고 시", "02-647-1234 (하이픈 포함)", "표1 #16"),
    ("사업장", "사업장 소재지", "사업장소재지", "선택", "한글로. 시도·구군·길·건물번호·층 순. 35자 이내", "표1 #18. 신고서 시트 B6 와 같아야 한다. 영문·한자는 소리나는 대로 한글로"),
    ("사업장", "사업장 전화번호", "사업장전화번호", "선택", "02-647-1234", "표1 #19"),
    ("사업장", "전자메일 주소", "전자메일주소", "선택", "", "표1 #20"),
    ("신고 표시", "소득처분 신고 여부", "소득처분여부", "필수", "Y / N (보통 N)", "법인 소득처분(인정상여 등) 신고하는 달만 Y (표1 #24)"),
    ("신고 표시", "본점 일괄납부 여부", "일괄납부여부", "필수", "Y / N (보통 N)", "국세청 승인 사업자만 Y (표1 #26)"),
    ("신고 표시", "사업자단위과세 여부", "사업자단위과세여부", "필수", "Y / N (보통 N)", "표1 #27"),
    ("환급계좌", "환급받을 은행", "은행코드", "환급신청 시", "은행코드 3자리 (004 국민, 020 우리, 081 하나, 088 신한, 011 농협, 003 기업)", "표1 #31. 계좌번호와 둘 다 있거나 둘 다 비어야 한다"),
    ("환급계좌", "환급받을 계좌번호", "계좌번호", "환급신청 시", "하이픈 없이", "표1 #32"),
]

CODE_FROM_TEXT = {"신고구분상세코드": {"정기": "01", "수정": "02", "기한후": "03"}}


def build(out, values=None):
    values = values or {}
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "회사기초정보"
    ws["A1"] = "원천세 홈택스 업로드 파일 · 회사 기초정보"
    ws["A1"].font = Font(name=FONT, size=14, bold=True)
    ws["A2"] = "노란 칸(값)만 채웁니다. 이 파일을 원천세전자파일 스킬에 넘기면 신고서(집계표)와 합쳐 업로드 파일을 만듭니다. 규격 출처는 국세청 「원천세이행상황신고서 전산매체제출요령」(2026-05-16)."
    ws["A2"].font = Font(name=FONT, size=9, color="595959")
    heads = ["구분", "항목", "값", "필수", "형식·예시", "어디에 쓰이나 (규격서 출처)", "키"]
    for c, h in enumerate(heads, 1):
        cell = ws.cell(row=4, column=c, value=h)
        cell.font = Font(name=FONT, bold=True); cell.fill = HEAD; cell.border = BOX
        cell.alignment = Alignment(vertical="center", wrap_text=True)
    for r, (grp, item, key, req, fmt, use) in enumerate(ROWS, 5):
        vals = [grp, item, values.get(key, ""), req, fmt, use, key]
        for c, v in enumerate(vals, 1):
            cell = ws.cell(row=r, column=c, value=v)
            cell.font = Font(name=FONT, size=10, color="808080" if c == 7 else "000000")
            cell.border = BOX
            cell.alignment = Alignment(vertical="center", wrap_text=True)
        ws.cell(row=r, column=3).fill = YELLOW
        ws.cell(row=r, column=3).font = Font(name=FONT, size=10, color="0000FF", bold=True)
        ws.cell(row=r, column=3).number_format = "@"
        if req == "필수":
            ws.cell(row=r, column=4).font = Font(name=FONT, size=10, bold=True, color="C00000")
        ws.cell(row=r, column=7).fill = GRAY
    for col, w in zip("ABCDEFG", (11, 24, 30, 11, 44, 52, 20)):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "A5"
    n = 5 + len(ROWS) + 1
    ws.cell(row=n, column=1, value="범례").font = Font(name=FONT, bold=True)
    ws.cell(row=n + 1, column=1, value="노란 칸 = 입력. 파란 글씨 = 사람이 정한 값. 회색 「키」열 = 프로그램이 읽는 이름이니 고치지 않습니다.").font = Font(name=FONT, size=9)
    ws.cell(row=n + 2, column=1, value="사업자번호·상호·대표자·납부 주기는 신고서(집계표) 시트에도 있습니다. 둘이 다르면 생성기가 멈춥니다.").font = Font(name=FONT, size=9)
    wb.save(out)


def read(path):
    """생성기가 부른다. 키 → 값 dict.

    틀 양식은 시트 「회사기초정보」 4행 머리에 「키」 · 「값」 이 있다. 신고서 단계(회사정보.py)는 「항목」 · 「값」 만 있는
    엑셀도 읽으므로 여기서도 읽는다. 시트 이름이 다르면 첫 시트를, 머리행은 위 20줄에서 찾고, 「키」 열이 없으면
    「항목」 글자를 틀의 항목 이름(또는 키 이름)으로 맞춘다. 머리행이 없으면 KeyError 대신 알아듣는 문장으로 멈춘다.
    """
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb["회사기초정보"] if "회사기초정보" in wb.sheetnames else wb.worksheets[0]
    머리 = None
    for r in range(1, min(ws.max_row, 20) + 1):
        cols = {str(ws.cell(row=r, column=c).value or "").strip(): c for c in range(1, ws.max_column + 1)}
        if "값" in cols and ("키" in cols or "항목" in cols):
            머리 = r, cols
            break
    if 머리 is None:
        raise ValueError(f"{Path(path).name} 에서 회사기초정보 머리행(「항목」 또는 「키」, 그리고 「값」)을 못 찾았습니다. "
                         "make_company_info_xlsx.py 로 만든 빈 틀에 옮겨 적어 주세요")
    hr, cols = 머리
    kc, vc, ic = cols.get("키"), cols["값"], cols.get("항목")
    라벨 = {항목: 키 for _, 항목, 키, *_ in ROWS}
    키들 = set(라벨.values())
    out = {}
    for r in range(hr + 1, ws.max_row + 1):
        k = ws.cell(row=r, column=kc).value if kc else None
        if not k and ic:
            t = str(ws.cell(row=r, column=ic).value or "").strip()
            k = 라벨.get(t) or (t if t in 키들 else None)
        if not k:
            continue
        v = ws.cell(row=r, column=vc).value
        v = "" if v is None else str(v).strip()
        if k in CODE_FROM_TEXT and v in CODE_FROM_TEXT[k]:
            v = CODE_FROM_TEXT[k][v]
        out[k] = v
    return out


if __name__ == "__main__":
    out = Path(sys.argv[1])
    vals = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8")) if len(sys.argv) > 2 else {}
    build(out, vals)
    print("wrote", out)
