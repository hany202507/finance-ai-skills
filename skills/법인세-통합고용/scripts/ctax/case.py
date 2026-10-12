"""신고 건 폴더 하나(`<회사>/<연도> 법인세/`)의 경로와 `_색인` JSON 읽기 · 쓰기. 계약은 CONTRACT.md 1 · 4절."""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

RECEIVED = "00 받은자료"
PRIOR = "00 받은자료/전기"
AR_DIR = "1 AR"
WP_DIR = "2 조서"
FORMS_DIR = "3 서식"
INDEX = "_색인"
DASHBOARD = "대시보드.html"

# 단계 이름 → 그 단계가 쓰는 JSON. 앞 단계가 없을 때 안내에 쓴다.
STEP_OUTPUT = {"read": "장부.json", "prior": "전기.json", "ar": "AR.json", "wp": "조정.json", "forms": "서식.json",
               "score": "채점.json"}


class MissingInput(Exception):
    """앞 단계 산출이나 입력 파일이 없다. 명령은 끝 코드 2 로 끝낸다."""


class Case:
    def __init__(self, folder: str | Path):
        self.root = Path(folder).resolve()
        if not self.root.is_dir():
            raise MissingInput(f"신고 건 폴더가 없습니다: {self.root}")
        m = re.match(r"(\d{4})\s*법인세", self.root.name)
        self.fy = m.group(1) if m else ""
        self.company = self.root.parent.name

    # 경로
    @property
    def received(self) -> Path:
        return self.root / RECEIVED

    @property
    def prior_dir(self) -> Path:
        return self.root / PRIOR

    @property
    def index_dir(self) -> Path:
        return self.root / INDEX

    def out_dir(self, name: str) -> Path:
        """`1 AR` · `2 조서` · `3 서식` 처럼 산출 폴더. 없으면 만든다."""
        p = self.root / name
        p.mkdir(parents=True, exist_ok=True)
        return p

    def index_path(self, name: str) -> Path:
        self.index_dir.mkdir(parents=True, exist_ok=True)
        return self.index_dir / name

    def rel(self, path: Path) -> str:
        return Path(path).resolve().relative_to(self.root).as_posix()

    # JSON
    def has(self, name: str) -> bool:
        return (self.index_dir / name).exists()

    def read_json(self, name: str, step: str | None = None) -> dict:
        p = self.index_dir / name
        if not p.exists():
            hint = f" 먼저 ctax {step} 을 돌리세요" if step else ""
            raise MissingInput(f"{INDEX}/{name} 이 없습니다.{hint}")
        return json.loads(p.read_text(encoding="utf-8"))

    def write_json(self, name: str, data: dict) -> Path:
        p = self.index_path(name)
        p.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        return p

    def need(self, step: str) -> dict:
        """앞 단계 산출 JSON 을 읽는다. 없으면 MissingInput."""
        return self.read_json(STEP_OUTPUT[step], step)

    # 신고건.json
    def info(self) -> dict:
        p = self.index_dir / "신고건.json"
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
        return {"company": self.company, "fy": self.fy, "fy_start": f"{self.fy}-01-01" if self.fy else "",
                "fy_end": f"{self.fy}-12-31" if self.fy else "", "steps": {}}

    def mark_step(self, name: str, ok: bool, note: str = "", outputs: list[str] | None = None) -> None:
        info = self.info()
        info.setdefault("steps", {})[name] = {"at": datetime.now().isoformat(timespec="seconds"), "ok": bool(ok),
                                              "note": note, "outputs": outputs or []}
        self.write_json("신고건.json", info)


def won(n: int | float | None) -> str:
    """금액을 1,234,567 꼴 글로. None 은 빈 글."""
    if n is None:
        return ""
    return f"{int(round(n)):,}"
