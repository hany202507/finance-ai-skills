# -*- coding: utf-8 -*-
"""표본sampling 실행기. 계정 리스트 파일 하나로 감사 표본 조서(설계 · 표본 · 평가)를 만들고 평가한다.

    python run.py scan <리스트.xlsx> [--tm <허용왜곡표시>] [--json]
        뽑기 전에 파일을 읽는다. 조서는 만들지 않는다. 금액 열 · 다른 숫자 열 · 금액 0 이하 행 · 일자 범위 · 결산일 어림 ·
        사업연도 순합계 · 계층 후보 · 거래처 수, --tm 을 주면 위험 수준별 표본 간격 · 점 수.
    python run.py make <리스트.xlsx> --tm <허용왜곡표시> [--risk 높음|보통|낮음|기본] [--assertion <경영진 주장>] [--fy-end YYYY-MM-DD]
        [--expected <예상 왜곡표시>] [--strata <계층 열>] [--tail-months 3] [--group <거래처 열>] [--method mus|random|systematic|specific]
        [--control <시산표 · 원장 금액>] [--company <회사>] [--out <조서.xlsx>]
        표본 조서를 만든다. 기본 저장 위치는 리스트 파일 옆 「표본_<파일 이름>.xlsx」.
    python run.py eval <표본_파일.xlsx> [--json]
        감사인이 적은 검사 결과 · 왜곡표시 금액으로 평가한다(엑셀 「허용왜곡표시와 견줌」 과 같은 판정).

끝난 값: 0(씀 · 평가함), 1(입력 오류 · 덮어쓰기 멈춤). 모든 옵션은 `python run.py make --help`.
표본 크기 · 추출 · 투영은 엔진이 계산한다. 허용왜곡표시 · 위험 수준 · 왜곡표시 금액 · 결론은 감사인이 정한다.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
os.environ.setdefault("AUDIT_OCR", "off")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass


def main(argv: list[str] | None = None) -> int:
    from audit import cli_sample

    ap = argparse.ArgumentParser(prog="run.py", description="표본sampling: 계정 리스트 파일 하나로 표본 조서를 만들고 평가한다")
    sub = ap.add_subparsers(dest="cmd", required=True)
    cli_sample.register(sub)
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] != "sample":              # `run.py scan …` 과 `run.py sample scan …` 둘 다 받는다
        args.insert(0, "sample")
    a = ap.parse_args(args)
    return int(a.func(a) or 0)                    # 입력 오류 · 덮어쓰기 멈춤은 명령 함수가 1 을 돌려준다


if __name__ == "__main__":
    sys.exit(main())
