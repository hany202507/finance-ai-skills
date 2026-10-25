# -*- coding: utf-8 -*-
"""신고 건 폴더 안의 파일 위치. 엔진(ctax)과 같은 폴더 꼴을 쓴다.

<회사>/<연도> 법인세/
  00 받은자료/            분개장 · 재무제표 · 거래처원장 엑셀, 전기/ 에 전기 세무조정계산서 PDF
  _색인/                  장부.json · 전표.csv · 전기.json · AR.json (엔진)
  _색인/AR_단계/          P1~F2.json, 순서.json, 전제.json (AI 판단과 진행 기록)
  _색인/공제제안.json      공제 · 감면 제안 (AI)
  _색인/AR_요약.json       세 묶음 요약 (finish)
  1 AR/AR_이슈.xlsx        엔진 엑셀 + 요약 · AR 한 장 · 계정 전수 · AI 추가 이슈 · 공제 제안 · 순서와 전제 시트
  1 AR/AR_보고서.md        AR 보고서(finish)
  1 AR/AR_화면.html        한 파일 화면(ar.py view, 선택)
"""
from __future__ import annotations

import json
from pathlib import Path

from ctax.case import AR_DIR, INDEX, Case

STEPS_DIR = "AR_단계"
CREDITS = "공제제안.json"
SUMMARY = "AR_요약.json"
XLSX = f"{AR_DIR}/AR_이슈.xlsx"
VIEW = f"{AR_DIR}/AR_화면.html"
REPORT = f"{AR_DIR}/AR_보고서.md"


def case(folder: str | Path) -> Case:
    return Case(folder)


def index(c: Case) -> Path:
    return c.root / INDEX


def steps_dir(c: Case) -> Path:
    d = index(c) / STEPS_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def read_json(path: Path, default=None):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def read_ar(c: Case) -> dict:
    return read_json(index(c) / "AR.json", {}) or {}
