# -*- coding: utf-8 -*-
"""절차점검 실행기. 조서 엑셀 파일 하나로 절차 줄 읽기 · 판정 검사 · 점검표 · 고른 줄 옮기기.

    python run.py scan <조서.xlsx> [--sheet <시트>] [--rows <행 수>] [--width <글자 수>] [--json]
        조서를 훑는다. 시트마다 쓰인 범위 · 칸 글과 절차 표 후보. 아무것도 쓰지 않는다.
    python run.py rows <조서.xlsx> --layout <위치.json> [--json]
        위치 파일의 범위에서 절차 줄을 뽑는다. 그 영역의 확인 항목(정의가 있는 영역)을 함께 낸다.
    python run.py check <조서.xlsx> --layout <위치.json> --verdicts <판정.json> [--received <받은자료 폴더>] [--with <이름=다른 조서.xlsx> ...]
        판정을 검사해 조서 옆에 절차점검_<파일>.xlsx(점검표)와 절차점검_<파일>.json(기록)을 쓴다. 조서는 건드리지 않는다.
    python run.py apply <조서.xlsx> --who <이름> [--pick 번호...]
        점검표 「반영」 칸이 「예」 인 줄(또는 --pick 번호)만 조서 옆 검토의견_<파일>.xlsx 에 「열림」 으로 잇는다.
    python run.py status <조서.xlsx> [--json]
        점검 안 함 · 최신 · 조서 바뀜.

끝난 값: 0(읽음 · 씀), 1(입력 오류 · 판정 거부).
판정은 Claude 가 하고 엔진은 근거 칸이 실제로 있는지와 판정이 줄마다 있는지를 검사한다. 결론은 감사인이 낸다.
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


def main(argv: list[str] | None = None) -> int:
    from audit import cli_procfile

    ap = argparse.ArgumentParser(prog="run.py", description="절차점검: 조서 엑셀 파일 하나로 감사절차 수행 여부를 점검한다")
    sub = ap.add_subparsers(dest="cmd", required=True)
    cli_procfile.register(sub)
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] != "procfile":            # `run.py scan …` 과 `run.py procfile scan …` 둘 다 받는다
        args.insert(0, "procfile")
    a = ap.parse_args(args)
    return int(a.func(a) or 0)


if __name__ == "__main__":
    sys.exit(main())
