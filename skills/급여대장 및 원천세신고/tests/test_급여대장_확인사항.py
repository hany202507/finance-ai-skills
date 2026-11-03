# -*- coding: utf-8 -*-
"""대장에 표시만 하고 계산하지 않는 것. 월 중 입퇴사 일할, 국외 근무 건강보험 경감."""
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "모듈" / "급여대장" / "scripts"))
import run as R  # noqa: E402


def _키트(tmp_path, 입사일="2024-01-01", 퇴사일="", 항목=(("BASE", 3000000),)):
    (tmp_path / "hr_card.csv").write_text(
        "사번,성명,소득구분,입사일,퇴사일,부양가족수,6세이하자녀수,8_20세자녀수,국민연금가입,건강보험가입,고용보험가입,이메일,근로계약서,비고\n"
        f"E001,김가상,상용,{입사일},{퇴사일},1,0,0,Y,Y,Y,a@example.com,,\n", encoding="utf-8")
    (tmp_path / "pay_contract.csv").write_text(
        "사번,적용시작일,항목코드,금액\n" + "".join(f"E001,2024-01-01,{k},{v}\n" for k, v in 항목), encoding="utf-8")
    규칙 = "항목코드,제도,구분,한도금액,한도단위,근거,등급\n"
    for 제도 in ("소득세", "국민연금", "건강보험", "고용보험"):
        규칙 += f"BASE,{제도},과세,,,시험,★★★\n"
    for 제도, 구분 in (("소득세", "한도부비과세"), ("국민연금", "제외"), ("건강보험", "산입"), ("고용보험", "제외")):
        규칙 += f"OVERSEA,{제도},{구분},1000000,월,시험,★★★\n"
    (tmp_path / "pay_item_rule.csv").write_text(규칙, encoding="utf-8")
    return tmp_path


def _근거(tmp_path, **k):
    return R.run(_키트(tmp_path, **k), "2026-07", tmp_path / "산출", 회사="샘플회사(가상)")["행들"][0].근거


def test_월_중_퇴사는_일할이_없다고_표시한다(tmp_path):
    assert any(g.startswith("확인필요") and "일할" in g for g in _근거(tmp_path, 퇴사일="2026-07-18"))


def test_월_중_입사는_일할이_없다고_표시한다(tmp_path):
    assert any(g.startswith("확인필요") and "일할" in g for g in _근거(tmp_path, 입사일="2026-07-13"))


def test_1일_입사와_말일_퇴사는_표시하지_않는다(tmp_path):
    assert not any("일할" in g for g in _근거(tmp_path, 입사일="2026-07-01", 퇴사일="2026-07-31"))


def test_국외근로수당을_받으면_건강보험_경감을_확인하라고_표시한다(tmp_path):
    근거 = _근거(tmp_path, 항목=(("BASE", 3000000), ("OVERSEA", 800000)))
    assert any(g.startswith("확인필요") and "§73②" in g for g in 근거)


def test_회사_이름을_빼면_멈추고_표는_깨지지_않는다(tmp_path):
    스크립트 = Path(R.__file__)
    환경 = {k: v for k, v in os.environ.items() if k != "PYTHONUTF8"}
    환경["PYTHONDONTWRITEBYTECODE"] = "1"
    키트 = _키트(tmp_path)
    r = subprocess.run([sys.executable, str(스크립트), str(키트), "2026-07", "-o", str(tmp_path / "산출")], capture_output=True, env=환경)
    assert r.returncode != 0
    r = subprocess.run([sys.executable, str(스크립트), str(키트), "2026-07", "-o", str(tmp_path / "산출"), "--회사", "샘플회사(가상)"],
                       capture_output=True, env=환경)
    assert r.returncode == 0 and "사번".encode("utf-8") in r.stdout


def test_그_달_지급이_없는_사람은_대장에서_빼고_까닭을_남긴다(tmp_path):
    r = R.run(_키트(tmp_path, 항목=(("BASE", 0),)), "2026-07", tmp_path / "산출", 회사="샘플회사(가상)")
    assert r["행들"] == [] and ("김가상", "그 달 지급 없음") in r["뺀사람"]


def test_엑셀_총지급액은_모든_지급항목을_더한다(tmp_path):
    """열 목록에 없는 항목(연구보조비 · 출산지원금)이 엑셀 합계에서 빠지면 신고서 총지급액이 줄어든다."""
    import openpyxl
    키트 = _키트(tmp_path, 항목=(("BASE", 3000000), ("RESEARCH", 200000), ("BIRTH", 2000000)))
    규칙 = (키트 / "pay_item_rule.csv").read_text(encoding="utf-8")
    for 코드 in ("RESEARCH", "BIRTH"):
        for 제도 in ("소득세", "국민연금", "건강보험", "고용보험"):
            규칙 += f"{코드},{제도},전액비과세,,,시험,★★★\n"
    (키트 / "pay_item_rule.csv").write_text(규칙, encoding="utf-8")
    r = R.run(키트, "2026-07", tmp_path / "산출", 회사="샘플회사(가상)")
    ws = openpyxl.load_workbook(r["엑셀"])["급여대장"]
    머리 = [c.value for c in ws[3]]
    총열 = 머리.index("총지급액") + 1
    assert "연구보조비" in 머리 and "출산지원금" in 머리
    assert ws.cell(4, 총열).value == f"=SUM(E4:{openpyxl.utils.get_column_letter(총열 - 1)}4)"
    assert sum(ws.cell(4, c).value or 0 for c in range(5, 총열)) == r["행들"][0].총지급액 == 5200000
