# -*- coding: utf-8 -*-
"""한 파일 화면(선택). 보고서는 finish 가 MD 로 쓰고, 화면이 필요할 때만 이 명령을 쓴다.

  ar.py view <신고건>                      1 AR/AR_화면.html (읽기 전용, 브라우저로 연다)
  ar.py view <신고건> --artifact <파일>    Claude 아티팩트로 올릴 꼴(doctype · html · head · body 태그를 뗀 것)

실제 회사 자료가 든 화면을 아티팩트로 올리는 일은 사용자가 요청할 때만, 비공개로 한다(SKILL.md).
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

from bestar import paths, review, review_view, steps


def artifact_form(html: str, title: str) -> str:
    html = re.sub(r"<!doctype html>\s*", "", html, flags=re.I)
    html = re.sub(r"</?html[^>]*>\s*", "", html, flags=re.I)
    html = re.sub(r"</?head>\s*", "", html, flags=re.I)
    html = re.sub(r"</?body[^>]*>\s*", "", html, flags=re.I)
    html = re.sub(r"<meta [^>]*>\s*", "", html, flags=re.I)
    html = re.sub(r'<link rel="icon"[^>]*>\s*', "", html)
    return re.sub(r"<title>.*?</title>", f"<title>{title}</title>", html, count=1, flags=re.S)


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="ar.py view")
    p.add_argument("folder")
    p.add_argument("--artifact")
    a = p.parse_args(argv)
    c = paths.case(a.folder)
    if not steps.finished(c) or not (paths.index(c) / "조정.json").exists():
        print("ar.py engine 과 1-(1) ~ 2-(2) 단계를 먼저 끝냅니다.")
        return 2
    d = review.build(c)
    if a.artifact:
        out = Path(a.artifact)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(artifact_form(review_view.render(d, "static"), f"{d.get('company')} 분석적 검토"), encoding="utf-8")
        print(f"아티팩트용 화면: {out}")
    else:
        review_view.write(d, c.root / paths.VIEW, "static")
        print(f"화면: {paths.VIEW}")
    return 0
