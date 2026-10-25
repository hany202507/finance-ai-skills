# -*- coding: utf-8 -*-
"""엔진 단계(받은자료 읽기 → 전기 신고서 읽기 → AR 규칙 → 조서 계산)와 진행 상태."""
from __future__ import annotations

import json
from pathlib import Path

from ctax.ar import cli as ar_cli
from ctax.intake import cli as read_cli
from ctax.prior import cli as prior_cli
from ctax.wp import cli as wp_cli

from bestar import keep, paths


def engine(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: ar.py engine <신고건>")
        return 2
    folder = argv[0]
    try:
        keep.save_added_conclusions(paths.case(folder))
    except Exception:  # noqa: BLE001 (처음 돌릴 때는 폴더 상태가 덜 갖춰져 있다)
        pass
    worst = 0
    for name, run in (("받은자료 읽기", read_cli.main), ("전기 신고서 읽기", prior_cli.main), ("AR 규칙", ar_cli.main),
                      ("조서 계산(세무조정 금액)", wp_cli.main)):
        print(f"== {name}")
        if run is prior_cli.main and _synthetic_prior(folder):
            # 시연 회사(academy-product `ctax demo --with-errors`)는 전기 PDF 없이 합성 전기.json 을 바로 둔다. 그대로 쓴다
            print("합성 전기 신고서 값(_색인/전기.json)이 있어 PDF 읽기를 건너뜁니다")
            continue
        code = run([folder])
        if code == 2:
            print(f"{name} 단계에서 멈췄습니다(끝 코드 2).")
            return 2
        worst = max(worst, code)
    print("== 다음: python scripts/ar.py step next " + json.dumps(folder, ensure_ascii=False))
    return worst


def status(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: ar.py status <신고건>")
        return 2
    case = paths.case(argv[0])
    from bestar import steps
    rows = [("엔진(AR.json)", (paths.index(case) / "AR.json").exists())]
    log = steps.read_log(case)
    done = [e["id"] for e in log]
    for sid, label in steps.SEQUENCE:
        rows.append((f"{label} {steps.TITLE[sid]}", sid in done))
    ar = paths.read_ar(case) if rows[0][1] else {}
    issues = ar.get("issues", [])
    memo_n = sum(1 for i in issues if i.get("memo"))
    rows.append((f"이슈 메모 {memo_n}/{len(issues)}", bool(issues) and memo_n == len(issues)))
    rows.append(("공제 · 감면 제안", (paths.index(case) / paths.CREDITS).exists()))
    rows.append(("엑셀 · 화면", (case.root / paths.VIEW).exists()))
    for name, ok in rows:
        print(f"[{'끝' if ok else '  '}] {name}")
    return 0

def _synthetic_prior(folder: str) -> bool:
    """_색인/전기.json 이 `synthetic: true` 이면 참(전기 PDF 없이 값을 바로 둔 시연 회사)."""
    p = paths.index(paths.case(folder)) / "전기.json"
    try:
        return bool(json.loads(p.read_text(encoding="utf-8")).get("synthetic"))
    except (OSError, ValueError):
        return False
