# -*- coding: utf-8 -*-
"""DSD푸팅 실행기. DART 편집기 파일(dsd)이나 DART 공시 원문(xml) 하나로 푸팅 엑셀을 만든다.

    python run.py read  <dsd>                           판독(표 · 주석 · 칸 수)
    python run.py links <dsd> --out <폴더>              AI 가 읽을 자료(dsd_읽기자료.md)와 연결 요청 파일
    python run.py links <dsd> --apply <연결.json> --out <폴더>   AI 가 적은 연결 정의를 넣는다
    python run.py foot  <dsd> [--prior <작년 보고서>] [--wtb <정산표>] [--prev <기존 판>] --out <폴더>   푸팅 엑셀
    python run.py text  <dsd> [--prior <작년 보고서>] --out <폴더>    문장 검토(폴더에 기준사실.json 이 있으면 대표이사 · 주소 · 감사기간까지)
    python run.py fetch <접수번호 | DART PDF> --out <폴더>   OpenDART 에서 원문 xml 을 받아 연결 · 별도로 나눈다(인증키는 환경변수 DART_API_KEY)

명령과 옵션은 감사 엔진의 `dsd` 하위 명령과 같다(`python run.py foot -h`). 공개본은 감사 폴더 옵션(--case)을 쓰지 않는다.
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
    ap = argparse.ArgumentParser(prog="DSD푸팅")
    sub = ap.add_subparsers(dest="cmd", required=True)
    cli_dsd.register(sub)
    a = ap.parse_args(["dsd"] + argv)
    return a.func(a) or 0


if __name__ == "__main__":
    sys.exit(main())
