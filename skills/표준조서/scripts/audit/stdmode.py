"""표준조서 공개판 갈림(2026-11-26). 설계 문서 4절.

공개 스킬(finance-ai-skills `표준조서`)은 이 저장소의 stdwp · stdfeed · stdtb 사본을 쓴다. 계산은 같고 안내 글만 다르다.
공개 스킬의 scripts/run.py 가 STANDALONE 을 참으로 바꾼다. 감사 건(정본)에서는 거짓 그대로다.

  STANDALONE      참이면 감사 폴더 없이 자료 폴더 하나로 돌리는 공개판(조회 대장 3320 · 2700B · 엔진 4000 조서 없음)
  cmd(sub, long)  표준조서 명령 안내 글. 정본 `std refresh` · `python -m audit std refresh`, 공개판 `python scripts/run.py refresh <자료 폴더>`
"""
from __future__ import annotations

STANDALONE = False


def cmd(sub: str, long: bool = False) -> str:
    if STANDALONE:
        return "python scripts/run.py " + sub + ("" if sub == "list" else " <자료 폴더>")
    return ("python -m audit std " if long else "std ") + sub
