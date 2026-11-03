# -*- coding: utf-8 -*-
"""받은 자료 찾기: 급여대장 엑셀 · csv 셋 · 회사기초정보 · Drive 링크. 모자라면 멈추고 묻는다."""
import base64
import json
import shutil
import subprocess
import sys
from pathlib import Path

import openpyxl
import pytest

스킬 = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(스킬 / "scripts"))
import 실행 as X  # noqa: E402
import 입력 as 입  # noqa: E402

샘플 = 스킬 / "examples" / "샘플회사"


def _기초정보만(tmp_path):
    폴더 = tmp_path / "받은"
    폴더.mkdir()
    shutil.copyfile(샘플 / "받은자료" / "회사기초정보_1234512345.xlsx", 폴더 / "회사기초정보_1234512345.xlsx")
    return 폴더


def _회사양식대장(경로, 귀속="2026-07"):
    """급여 프로그램마다 열 이름이 다르다. 이름 · 지급계 · 갑근세 · 주민세 · 고용형태 로 적은 대장."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = f"{int(귀속[5:])}월"
    ws.append([f"{귀속} 급여 지급 내역"])
    ws.append([])
    ws.append(["사원번호", "이름", "고용형태", "기본급", "식대", "지급계", "갑근세", "주민세", "비고"])
    ws.append(["S01", "가나다", "정규", 3_000_000, 200_000, 3_200_000, 74_350, 7_430, ""])
    ws.append(["S02", "라마바", "정규", 4_000_000, 200_000, 4_200_000, 187_000, 18_700, ""])
    ws.append(["S03", "사아자", "프리랜서", 1_000_000, 0, 1_000_000, 30_000, 3_000, "3.3%"])
    ws.append(["", "합계", "", 8_000_000, 400_000, 8_400_000, 291_350, 29_130, ""])
    wb.save(경로)
    return 경로


@pytest.mark.parametrize("링크,종류,아이디", [
    ("https://drive.google.com/drive/folders/1AbCdEfGhIjKlMnOpQrStUvWxYz012345?usp=sharing", "폴더", "1AbCdEfGhIjKlMnOpQrStUvWxYz012345"),
    ("https://drive.google.com/drive/u/1/folders/1AbCdEfGhIjKlMnOpQ", "폴더", "1AbCdEfGhIjKlMnOpQ"),
    ("https://drive.google.com/file/d/1ZyXwVuTsRqPoNmLkJiHg/view?usp=drivesdk", "파일", "1ZyXwVuTsRqPoNmLkJiHg"),
    ("https://docs.google.com/spreadsheets/d/1SheetIdSheetId1234/edit#gid=0", "파일", "1SheetIdSheetId1234"),
    ("https://drive.google.com/open?id=1OpenIdOpenId12345", "모름", "1OpenIdOpenId12345"),
])
def test_드라이브_링크에서_id_를_뽑는다(링크, 종류, 아이디):
    assert 입.드라이브링크(링크) == {"종류": 종류, "id": 아이디}


def test_링크가_아니면_None():
    assert 입.드라이브링크(r"C:\자료\급여") is None
    assert 입.드라이브링크("https://example.com/folders/abcdefghijk") is None


def test_드라이브_링크로_신고하면_내려받으라고_멈춘다():
    r = X.신고("https://drive.google.com/drive/folders/1AbCdEfGhIjKlMnOpQ")
    assert r["종료"] == 3 and r["링크"]["종류"] == "폴더"


def test_풀기는_base64_를_파일로_쓴다(tmp_path):
    원 = (샘플 / "받은자료" / "회사기초정보_1234512345.xlsx").read_bytes()
    글 = base64.b64encode(원).decode()
    p = 입.풀기(글[:60] + "\n" + 글[60:], tmp_path / "x" / "회사기초정보_1234512345.xlsx")
    assert p.read_bytes() == 원
    p2 = 입.풀기(json.dumps({"content": 글}), tmp_path / "y.xlsx")
    assert p2.read_bytes() == 원


def test_엑셀이_아닌_글을_xlsx_로_풀면_멈춘다(tmp_path):
    with pytest.raises(입.확인필요, match="xlsx"):
        입.풀기(base64.b64encode("이름,금액\n".encode()).decode(), tmp_path / "급여대장.xlsx")


def test_회사기초정보가_없으면_빈_틀을_만들고_한_번에_묻는다(tmp_path):
    폴더 = tmp_path / "받은"
    폴더.mkdir()
    _회사양식대장(폴더 / "급여대장_2026-07.xlsx")
    with pytest.raises(X.확인필요) as e:
        X.신고(폴더, "2026-07", 계산값=False)
    assert (폴더 / "회사기초정보_작성.xlsx").exists()
    글 = str(e.value)
    assert "홈택스" in 글 and "세무대리인" in 글 and "환급" in 글


def test_회사기초정보가_틀_양식이_아니어도_항목_값으로_읽는다(tmp_path):
    폴더 = tmp_path / "받은"
    폴더.mkdir()
    _회사양식대장(폴더 / "급여대장_2026-07.xlsx")
    원 = openpyxl.load_workbook(샘플 / "받은자료" / "회사기초정보_1234512345.xlsx").active
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "기초정보"
    ws.append(["항목", "값"])
    for r in 원.iter_rows(values_only=True):
        if r[6] and r[2] not in (None, ""):
            ws.append([r[1], r[2]])
    wb.save(폴더 / "회사기초정보_1234512345.xlsx")
    r = X.신고(폴더, "2026-07", 계산값=False)
    assert r["형식검증"]["통과"] == r["형식검증"]["검사"] == 22


def test_회사기초정보에_항목_값_머리가_없으면_빈_틀을_주고_멈춘다(tmp_path):
    폴더 = tmp_path / "받은"
    폴더.mkdir()
    _회사양식대장(폴더 / "급여대장_2026-07.xlsx")
    wb = openpyxl.Workbook()
    wb.active.append(["사업자등록번호", "1234512345"])
    wb.save(폴더 / "회사기초정보_1234512345.xlsx")
    with pytest.raises(X.확인필요, match="머리행"):
        X.신고(폴더, "2026-07", 계산값=False)


def test_회사_양식_급여대장도_열_이름_별칭으로_읽는다(tmp_path):
    폴더 = _기초정보만(tmp_path)
    _회사양식대장(폴더 / "급여대장_2026-07.xlsx")
    r = X.신고(폴더, 계산값=False)
    표 = {c["코드"]: (c["인원"], c["총지급액"], c["소득세"]) for c in r["소득코드별"]}
    assert 표["A01"] == (2, 7_400_000, 261_350)
    assert 표["A25"] == (1, 1_000_000, 30_000)
    assert r["급여대장출처"] == "받은 급여대장"
    assert r["형식검증"]["통과"] == r["형식검증"]["검사"] == 22


def test_급여대장이_여러_달이면_신고_달을_묻는다(tmp_path):
    폴더 = _기초정보만(tmp_path)
    _회사양식대장(폴더 / "급여대장_2026-06.xlsx", "2026-06")
    _회사양식대장(폴더 / "급여대장_2026-07.xlsx")
    with pytest.raises(X.확인필요, match="2026-06, 2026-07"):
        X.신고(폴더, 계산값=False)


def test_csv_가_일부만_있으면_무엇이_빠졌는지_말한다(tmp_path):
    폴더 = _기초정보만(tmp_path)
    shutil.copyfile(샘플 / "받은자료" / "hr_card.csv", 폴더 / "hr_card.csv")
    with pytest.raises(X.확인필요, match="hr_card.csv 만"):
        X.신고(폴더, "2026-07", 계산값=False)


def test_한글_이름_csv_도_급여대장을_만든다(tmp_path):
    폴더 = _기초정보만(tmp_path)
    for 원, 새 in (("hr_card.csv", "인사카드.csv"), ("pay_contract.csv", "급여계약.csv"), ("pay_item_rule.csv", "항목규칙.csv")):
        shutil.copyfile(샘플 / "받은자료" / 원, 폴더 / 새)
    r = X.신고(폴더, "2026-07", 계산값=False)
    assert r["급여대장출처"].startswith("인사카드")
    assert {c["코드"]: c["인원"] for c in r["소득코드별"]}["A01"] == 5


def test_퇴사는_월통상임금이_없으면_묻는다(tmp_path):
    폴더 = tmp_path / "샘플"
    shutil.copytree(샘플, 폴더)
    with pytest.raises(X.확인필요, match="통상임금"):
        X.퇴사(폴더, "E002", "2026-07-31", None)


def test_명령행_종료코드(tmp_path):
    환경 = {"PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1", "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", "")}
    환경["PATH"] = __import__("os").environ.get("PATH", "")
    스크립트 = 스킬 / "scripts" / "실행.py"
    r = subprocess.run([sys.executable, str(스크립트), "링크", "https://drive.google.com/file/d/1ZyXwVuTsRqPoNmLkJiHg/view"],
                       capture_output=True, env=환경)
    assert r.returncode == 0 and json.loads(r.stdout.decode("utf-8"))["종류"] == "파일"
    r = subprocess.run([sys.executable, str(스크립트), "신고", str(tmp_path)], capture_output=True, env=환경)
    assert r.returncode == 2 and "회사기초정보" in r.stderr.decode("utf-8")
    r = subprocess.run([sys.executable, str(스크립트), "신고", "https://drive.google.com/drive/folders/1AbCdEfGhIjKlMnOpQ"],
                       capture_output=True, env=환경)
    assert r.returncode == 3


def test_그해_입사자의_퇴사는_입사한_달부터_대장을_찾는다(tmp_path):
    폴더 = tmp_path / "받은"
    폴더.mkdir()
    for m in range(4, 11):
        행 = {"사번": "E009", "성명": "오가상", "소득구분": "상용", "소득코드": "A01", "지급": {"BASE": 2_800_000, "MEAL": 200_000},
              "총지급액": 3_000_000, "표준": {"소득세": 2_800_000}, "비과세": {"소득세": 200_000}, "국민연금": 133_000,
              "건강보험": 100_660, "장기요양보험": 13_220, "고용보험": 25_200, "소득세": 56_800, "지방소득세": 5_680}
        (폴더 / f"급여대장_2026-{m:02d}.json").write_text(json.dumps([행], ensure_ascii=False), encoding="utf-8")
    r = X.퇴사(폴더, "E009", "2026-10-31", 3_000_000, 입사일="2026-04-01", 생년월일="1998-07-07")
    assert r["중도정산"]["총급여"] == 7 * 2_800_000 and r["퇴직금"]["퇴직금"] == 0


def test_대장에서_뺀_사람과_까닭을_요약에_싣는다(tmp_path):
    폴더 = tmp_path / "샘플"
    shutil.copytree(샘플 / "받은자료", 폴더)
    with open(폴더 / "hr_card.csv", "a", encoding="utf-8") as f:
        f.write("E009,나가상,상용,2024-01-02,2026-06-30,1,0,0,Y,Y,Y,,,,1990-01-01\n")
    r = X.신고(폴더, "2026-07", 계산값=False)
    assert {"성명": "나가상", "까닭": "퇴사"} in r["급여대장뺀사람"]
