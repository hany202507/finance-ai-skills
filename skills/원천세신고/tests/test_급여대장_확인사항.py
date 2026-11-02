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
