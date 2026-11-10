# -*- coding: utf-8 -*-
"""DSD초안 실행기. 전기(작년) 감사보고서 · 연결감사보고서 dsd 하나로 당기 초안 dsd 를 만든다.

    python run.py draft <전기.dsd> [--out <폴더>]
        당기 숫자 → 전기 칸, 당기 칸 비움, 기수 · 해 +1, 변동표의 새 당기 기초 = 작년 기말. 원고 엑셀 · 원고 검사 · 초안 검산 · 안내까지 낸다.
    python run.py sheet <dsd> --out <폴더>          dsd 를 원고 엑셀로(고칠 때)
    python run.py build <원고.xlsx> [--out <dsd>]    고친 원고 엑셀로 dsd 를 다시 만든다

회사가 준 전기 dsd 든, DSD변환 스킬이 작년 공시 원문으로 만든 dsd 든 같은 명령이다. 같은 전기 파일이면 몇 번을 돌려도 결과가 바이트까지 같다.
명령과 옵션은 감사 엔진의 `dsd` 하위 명령과 같다(`python run.py draft -h`). 끝난 값: 0(만듦), 2(파일 없음 · 읽지 못함 · 결산연도 모름).
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass


def main(argv=None) -> int:
    from audit import cli_dsd

    argv = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser(prog="DSD초안")
    sub = ap.add_subparsers(dest="cmd", required=True)
    cli_dsd.register(sub)
    a = ap.parse_args(["dsd"] + argv)
    return a.func(a) or 0


if __name__ == "__main__":
    sys.exit(main())
