# -*- coding: utf-8 -*-
"""법인세 AR 스킬 명령. 모든 명령의 첫 인자는 신고 건 폴더(<회사>/<연도> 법인세)다.

  python scripts/ar.py engine <신고건>              받은자료 읽기 → 전기 신고서 읽기 → AR 규칙(엔진)
  python scripts/ar.py step next|done|status <신고건> [<단계>] [--redo]
                                                     1-(1)~2-(2) 판단을 한 단계씩(AI 가 쓰고 엔진이 검사)
  python scripts/ar.py memo <신고건> <메모.json>     이슈 메모 검사 · 넣기(금액 · 조문 등급 · 문체)
  python scripts/ar.py credits <신고건> <제안.json>  공제 · 감면 제안 검사 · 넣기(전표 줄과 금액 대조)
  python scripts/ar.py sum <신고건> --what .. (--lines 1,5-9 | --account 901 [--memo 정규식])  전표 합계(엔진 계산)
  python scripts/ar.py pdf <신고건> --page N --form 29 --what .. --amount N   엔진이 못 읽은 전기 PDF 값 적기
  python scripts/ar.py facts <신고건>                적어 둔 합계 · PDF 값 보기
  python scripts/ar.py page <신고건> <쪽> [--zoom 2]  전기 신고서 PDF 한 쪽을 그림으로(칸이 깨져 글로 못 읽을 때)
  python scripts/ar.py finish <신고건>               빠진 것 검사 → AR 보고서(MD) · 엑셀
  python scripts/ar.py view <신고건> [--artifact 파일]  한 파일 화면(선택). --artifact 는 Claude 아티팩트로 올릴 꼴
  python scripts/ar.py serve <신고건> [--port 8852]  분석적 검토 화면을 띄우고 판단(질문 답 · 반영)을 저장
  python scripts/ar.py inputs <신고건> [--paper id] [--grep 정규식] [--changed]   조서 노란 칸 목록(질문지 sets 에 쓸 칸)
  python scripts/ar.py answer <신고건> [<uid> --value v | --values a,b | --undo] [--other 글]   화면 없이 질문지에 답
  python scripts/ar.py apply <신고건> [--dry]       답 · 2-(2) 전제를 조서 노란 칸에 맞추고 조서를 다시 계산
  python scripts/ar.py compare <신고건> [<최종 신고서.pdf>]   최종 세무조정계산서와 AR 대조(놓친 것 · AR 만 짚은 것 · 조서 금액)
  python scripts/ar.py status <신고건>               지금 어디까지 했는지

끝 코드: 0 성공, 1 검사에 걸림, 2 앞 단계가 없거나 입력을 읽지 못함.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine"))
sys.path.insert(0, str(ROOT))
os.environ.setdefault("PYTHONUTF8", "1")
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    cmd, rest = argv[0], argv[1:]
    if cmd == "engine":
        from bestar import pipeline
        return pipeline.engine(rest)
    if cmd == "step":
        from bestar import steps
        return steps.main(rest)
    if cmd == "memo":
        from bestar import memos
        return memos.main(rest)
    if cmd == "credits":
        from bestar import credits
        return credits.main(rest)
    if cmd in ("sum", "pdf", "facts"):
        from bestar import facts
        return facts.main(cmd, rest)
    if cmd == "page":
        from bestar import page
        return page.main(rest)
    if cmd == "finish":
        from bestar import finish
        return finish.main(rest)
    if cmd == "view":
        from bestar import view_cmd
        return view_cmd.main(rest)
    if cmd == "serve":
        from bestar import serve
        return serve.main(rest)
    if cmd in ("inputs", "answer", "apply"):
        from bestar import link
        return {"inputs": link.main_inputs, "answer": link.main_answer, "apply": link.main_apply}[cmd](rest)
    if cmd == "compare":
        from bestar import compare
        return compare.main(rest)
    if cmd == "status":
        from bestar import pipeline
        return pipeline.status(rest)
    print(f"모르는 명령입니다: {cmd}\n{__doc__}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
