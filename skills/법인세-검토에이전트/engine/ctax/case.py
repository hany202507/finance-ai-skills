"""신고 건 폴더 하나(`<회사>/<연도> 법인세/`)의 경로와 `_색인` JSON 읽기 · 쓰기. 계약은 CONTRACT.md 1 · 4절."""
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path

RECEIVED = "00 받은자료"
PRIOR = "00 받은자료/전기"
AR_DIR = "1 AR"
WP_DIR = "2 조서"
FORMS_DIR = "3 서식"
FILING_DIR = "4 신고서"
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
        """통째로 다시 쓴다. 임시 파일에 쓰고 바꿔 넣어 읽는 쪽(chief · 화면)이 반쯤 쓴 파일을 보지 않게 한다. 같은 건을 두 실행이
        함께 쓰는 것은 디스패치의 건별 잠금(`runlog.lock_acquire`, 설계안 10-30 3.2절)이 막는다. 바꿔 넣지 못하면(Drive 가 잡고 있음)
        그대로 덮어쓴다."""
        p = self.index_path(name)
        text = json.dumps(data, ensure_ascii=False, indent=1)
        tmp = p.with_name(f"{p.name}.{os.getpid()}.tmp")
        try:
            tmp.write_text(text, encoding="utf-8")
            os.replace(tmp, p)
        except OSError:
            try:
                tmp.unlink()
            except OSError:
                pass
            p.write_text(text, encoding="utf-8")
        return p

    def running(self) -> dict | None:
        """이 건을 지금 돌리고 있는 실행 {host, pid, caller, command, at}. 없거나 죽은 레코드면 None(실장 현황의 busy 표시용)."""
        from . import runlog

        return runlog.lock_holder(self.root)

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


def file_sha1(p: Path) -> str:
    """파일 내용 해시(sha1 16진). 장부.json · 전기.json 이 읽은 판을 적는다(intake/stale.py, 10-31). 꾸러미마다 들어가는 이 파일에 둔다."""
    import hashlib

    h = hashlib.sha1()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def won(n: int | float | None) -> str:
    """금액을 1,234,567 꼴 글로. None 은 빈 글."""
    if n is None:
        return ""
    return f"{int(round(n)):,}"
