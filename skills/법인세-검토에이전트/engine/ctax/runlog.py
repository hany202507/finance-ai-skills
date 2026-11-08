"""실행 기록 `_색인/기록.jsonl`. `python -m ctax <명령> <신고 건>` 이 돌 때마다 한 줄을 덧붙인다.

  run(cmd, argv, fn)   fn(argv) 를 돌리고 한 줄을 적는다. 끝 코드를 돌려준다(`__main__._call` 이 부른다)
  run_root(cmd, argv, fn)  회사들 폴더를 받는 명령(chief · closing --all)은 `<회사들 폴더>/_법인세실장/기록.jsonl` 에 적는다(10-31)
  read(case_dir)       기록 줄 목록(오래된 것부터). 파일이 없으면 빈 목록, 깨진 줄은 건너뛴다
  read_root(root)      회사들 폴더 기록 줄 목록
  last(rows)           명령마다 마지막 줄 {command: row}
  failed(row)          그 줄이 예외(exit -1)나 끝 코드 2 로 끝났는지

한 줄: {"at", "command", "args", "caller", "exit", "seconds", "error"}. `at` 은 시작한 때, `caller` 는 환경변수
CTAX_CALLER(없으면 「터미널」. 화면 단추는 「화면」, 스킬은 스킬 이름을 준다).
예외로 죽으면 exit -1 과 오류 글 마지막 줄을 적고 예외는 그대로 올린다. 끝 코드 2 는 명령이 마지막에 찍은 줄을 error 에 둔다.
이 실행 안에서 실패로 남은 단계(신고건.json steps 의 ok false · note)가 있으면 그 note 를 앞에 붙인다. review · std 처럼
안에서 단계를 돌리는 명령은 마지막 줄이 「(받은자료 읽기 0.1초, 끝 코드 2)」 뿐이라 까닭이 note 에만 있다(10-31 QA 결함 3).
신고 건 폴더가 없는 호출(ui serve · ui sample · 도움말 · 없는 폴더)과 status 는 적지 않는다. `run` 은 안의 단계마다 한 줄이다.
기록을 쓰지 못해도 명령은 그대로 끝난다.

건별 잠금 `_색인/실행중.json`{host, pid, caller, command, at}(설계안 2026-10-30 3.2절). 긴 쓰기 명령만 `__main__` 디스패치가
잡고 끝날 때 놓는다. 답 넣기 명령은 잠금 없이 자기 파일만 쓰되 잠겨 있으면 세 번 다시 시도한 뒤 끝 코드 3.
  lock_acquire(case, cmd)  잡는다. 잡았으면 None, 잠겨 있으면 그 레코드. 쓰고 LOCK_CONFIRM_SECONDS 뒤 다시 읽어 자기 레코드인지 확인한다
  lock_release(case)       자기 레코드일 때만 지운다
  lock_holder(case)        살아 있는 레코드. 같은 host 면 pid 생존, 다른 host 면 at 기준 LOCK_STALE_MINUTES 안. 아니면 None
  lock_wait(case)          답 넣기 명령용. ANSWER_WAIT_SECONDS 안에 ANSWER_RETRIES 번 본다. 끝까지 잠겨 있으면 그 레코드
  refuse(case, cmd, argv, rec, answer)  끝 코드 3 줄을 기록.jsonl 에 적고 까닭을 찍은 뒤 3 을 돌려준다
`failed` 는 끝 코드 3 도 실패로 본다(돌지 않았다).
"""
from __future__ import annotations

import json
import os
import re
import socket
import sys
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path

from .case import INDEX

FILE = "기록.jsonl"
SKIP = ("status",)                 # 점검은 읽기만 하므로 적지 않는다
DEFAULT_CALLER = "터미널"
CASE_RE = re.compile(r"^\d{4}\s*법인세$")
ERROR_MAX = 500
ROOT_DIR = "_법인세실장"           # chief.build.OUT_DIR 과 같다(runlog 는 chief 를 import 하지 않는다)
LOCK_FILE = "실행중.json"          # 건별 잠금
LOCK_CONFIRM_SECONDS = 2.0        # 쓰고 다시 읽기까지 기다리는 시간(Drive 동기화 지연). 시험은 줄인다
LOCK_STALE_MINUTES = 30           # 다른 host 레코드는 at 뒤 이 시간이 지나면 무효
ANSWER_RETRIES = 3                # 답 넣기 명령이 잠금을 다시 보는 횟수
ANSWER_WAIT_SECONDS = 30.0        # 그 재시도를 이 시간 안에
STILL_ACTIVE = 259                # Windows GetExitCodeProcess


def caller() -> str:
    return (os.environ.get("CTAX_CALLER") or "").strip() or DEFAULT_CALLER


def case_of(cmd: str, argv: list[str]) -> Path | None:
    """인자에서 신고 건 폴더를 찾는다. 옵션이 아닌 인자 가운데 처음 나오는 있는 폴더다. 없으면 None.

    `ui` 는 `ui export <신고 건>` 만 적는다(serve 는 끝나지 않고, export 에 회사들 폴더를 주면 신고 건 하나가 아니다).
    `context` 는 save · add · confirm 에 신고 건을 줬을 때만(show · check 는 읽기, `add <회사>` 는 회사 폴더). `closing --all` 은 회사들 폴더라 없다."""
    if cmd in SKIP or (cmd == "ui" and argv[:1] != ["export"]):
        return None
    if cmd == "context" and argv[:1] in (["show"], ["check"]):      # 읽기만 한다
        return None
    if cmd == "closing" and "--all" in argv:                         # 회사들 폴더. run_root 가 적는다
        return None
    for a in argv:
        if not isinstance(a, str) or not a or a.startswith("-"):
            continue
        try:
            p = Path(a)
            if not p.is_dir():
                continue
            p = p.resolve()
        except OSError:
            continue
        if cmd in ("ui", "context") and not CASE_RE.match(p.name):   # context add <회사> · ui export <회사들 폴더> 는 적지 않는다
            return None
        return p
    return None


def append(case_dir: str | Path, row: dict, sub: str = INDEX) -> None:
    try:
        d = Path(case_dir) / sub
        d.mkdir(parents=True, exist_ok=True)
        with (d / FILE).open("a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        pass


class _Tail:
    """출력을 그대로 흘리면서 마지막 줄만 기억한다(끝 코드 2 의 오류 글로 쓴다)."""

    def __init__(self, stream):
        self._stream = stream
        self.last = ""

    def write(self, s):
        for line in str(s).splitlines():
            if line.strip():
                self.last = line.strip()
        return self._stream.write(s)

    def __getattr__(self, name):
        return getattr(self._stream, name)


SUMMARY_LINE = re.compile(r"^\(.+ \d+(?:\.\d+)?초, 끝 코드 -?\d+\)$")     # review · std 가 단계마다 찍는 요약 줄


def _steps(case: Path) -> dict:
    try:
        info = json.loads((case / INDEX / "신고건.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    steps = info.get("steps") if isinstance(info, dict) and isinstance(info.get("steps"), dict) else {}
    return {k: (v.get("at"), v.get("ok"), v.get("note")) for k, v in steps.items() if isinstance(v, dict)}


def _step_reason(before: dict, after: dict) -> str:
    """이 실행에서 새로 남거나 바뀐 단계 가운데 실패(ok false)인 것의 note. 여럿이면 「 / 」 로 잇는다."""
    hits = [v for k, v in after.items() if v != before.get(k) and v[1] is False and str(v[2] or "").strip()]
    hits.sort(key=lambda v: str(v[0]))
    return " / ".join(dict.fromkeys(str(v[2]).strip() for v in hits))


def root_of(argv: list[str]) -> Path | None:
    """회사들 폴더 인자: 옵션이 아닌 인자 가운데 처음 나오는 있는 폴더."""
    for a in argv:
        if isinstance(a, str) and a and not a.startswith("-"):
            try:
                p = Path(a)
                if p.is_dir():
                    return p.resolve()
            except OSError:
                continue
    return None


def run_root(cmd: str, argv: list[str], fn) -> int:
    """회사들 폴더를 받는 명령. `<회사들 폴더>/_법인세실장/기록.jsonl` 에 한 줄. 폴더가 없으면 적지 않는다."""
    root = root_of(argv)
    if root is None:
        return int(fn(argv) or 0)
    return _run(root, ROOT_DIR, cmd, argv, fn, reason=False)


def run(cmd: str, argv: list[str], fn) -> int:
    """fn(argv) 를 돌리고 기록 한 줄을 적는다. 신고 건 폴더를 찾지 못하면 적지 않고 그대로 돌린다."""
    case = case_of(cmd, argv)
    if case is None:
        return int(fn(argv) or 0)
    return _run(case, INDEX, cmd, argv, fn, reason=True)


def _run(where: Path, sub: str, cmd: str, argv: list[str], fn, reason: bool) -> int:
    row = {"at": datetime.now().isoformat(timespec="seconds"), "command": cmd, "args": [str(a) for a in argv],
           "caller": caller(), "exit": 0, "seconds": 0.0, "error": ""}
    before = _steps(where) if reason else {}
    out, err = _Tail(sys.stdout), _Tail(sys.stderr)
    old = sys.stdout, sys.stderr
    sys.stdout, sys.stderr = out, err
    t0 = time.perf_counter()
    try:
        row["exit"] = int(fn(argv) or 0)
        return row["exit"]
    except SystemExit as e:            # argparse 가 인자 오류로 끝낸 것
        row["exit"] = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
        raise
    except BaseException as e:         # noqa: BLE001 (적고 그대로 올린다)
        row["exit"] = -1
        row["error"] = (traceback.format_exception_only(type(e), e)[-1].strip() or type(e).__name__)[:ERROR_MAX]
        raise
    finally:
        sys.stdout, sys.stderr = old
        row["seconds"] = round(time.perf_counter() - t0, 2)
        if row["exit"] == 2 and not row["error"]:
            last_line = err.last or out.last
            # 마지막 줄이 이미 까닭이면 그대로 둔다. review · std 의 단계 요약 줄이면 이 실행에서 실패로 남은 단계 note 를 앞에 붙인다
            why = _step_reason(before, _steps(where)) if reason and (not last_line or SUMMARY_LINE.match(last_line)) else ""
            row["error"] = (f"{why} / {last_line}" if why and last_line else (why or last_line))[:ERROR_MAX]
        append(where, row, sub)


def read(case_dir: str | Path) -> list[dict]:
    return _read_file(Path(case_dir) / INDEX / FILE)


def _read_file(p: Path) -> list[dict]:
    try:
        text = p.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    rows = []
    for line in text.splitlines():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if isinstance(r, dict) and r.get("command"):
            rows.append(r)
    return rows


def read_root(root: str | Path) -> list[dict]:
    return _read_file(Path(root) / ROOT_DIR / FILE)


def last(rows: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for r in rows:
        out[str(r.get("command"))] = r
    return out


def failed(row: dict) -> bool:
    return row.get("exit") in (-1, 2, 3)


# ---- 건별 잠금 ---------------------------------------------------------------------------------------------------

def host() -> str:
    try:
        return socket.gethostname() or "?"
    except OSError:
        return "?"


def pid_alive(pid: int) -> bool:
    """같은 host 의 프로세스가 살아 있는지. 모르면(권한 없음) 살아 있는 것으로 본다."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        k = ctypes.windll.kernel32
        h = k.OpenProcess(0x1000, False, pid)                   # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return k.GetLastError() == 5                        # ERROR_ACCESS_DENIED: 있기는 하다
        try:
            code = ctypes.c_ulong()
            if not k.GetExitCodeProcess(h, ctypes.byref(code)):
                return True
            return code.value == STILL_ACTIVE
        finally:
            k.CloseHandle(h)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def lock_path(case_dir: str | Path) -> Path:
    return Path(case_dir) / INDEX / LOCK_FILE


def lock_read(case_dir: str | Path) -> dict | None:
    """레코드를 그대로 읽는다(살았는지는 보지 않는다). 없거나 깨졌으면 None."""
    try:
        rec = json.loads(lock_path(case_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return rec if isinstance(rec, dict) and rec.get("at") else None


def lock_alive(rec: dict | None, now: datetime | None = None) -> bool:
    if not rec:
        return False
    if str(rec.get("host") or "") == host():
        return pid_alive(rec.get("pid"))
    try:
        at = datetime.fromisoformat(str(rec.get("at")))
    except ValueError:
        return False
    return (now or datetime.now()) - at < timedelta(minutes=LOCK_STALE_MINUTES)


def lock_holder(case_dir: str | Path) -> dict | None:
    rec = lock_read(case_dir)
    return rec if lock_alive(rec) else None


def _same(a: dict | None, b: dict | None) -> bool:
    return bool(a and b) and all(str(a.get(k)) == str(b.get(k)) for k in ("host", "pid", "at", "command"))


def _write_lock(case_dir: str | Path, rec: dict) -> None:
    p = lock_path(case_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)


def lock_acquire(case_dir: str | Path, cmd: str) -> dict | None:
    """잠금을 잡는다. 잡았으면 None, 다른 실행이 잡고 있으면 그 레코드. 쓴 뒤 다시 읽어 자기 레코드인지 확인한다."""
    held = lock_holder(case_dir)
    if held:
        return held
    rec = {"host": host(), "pid": os.getpid(), "caller": caller(), "command": cmd,
           "at": datetime.now().isoformat(timespec="seconds")}
    try:
        _write_lock(case_dir, rec)
    except OSError:
        return None                                             # 잠금을 못 쓰는 폴더면 잠금 없이 돈다(기록과 같다)
    time.sleep(LOCK_CONFIRM_SECONDS)
    again = lock_read(case_dir)
    if again is None:
        try:
            _write_lock(case_dir, rec)
        except OSError:
            pass
        return None
    return None if _same(again, rec) else again


def lock_release(case_dir: str | Path) -> None:
    """자기 레코드(host · pid 같음)일 때만 지운다."""
    rec = lock_read(case_dir)
    if not rec or str(rec.get("host")) != host() or str(rec.get("pid")) != str(os.getpid()):
        return
    try:
        lock_path(case_dir).unlink()
    except OSError:
        pass


def lock_wait(case_dir: str | Path) -> dict | None:
    """답 넣기 명령용. 잠겨 있으면 ANSWER_WAIT_SECONDS 안에 ANSWER_RETRIES 번 본다. 끝까지 잠겨 있으면 그 레코드."""
    held = None
    tries = max(1, ANSWER_RETRIES)
    for i in range(tries):
        held = lock_holder(case_dir)
        if not held:
            return None
        if i < tries - 1:
            time.sleep(ANSWER_WAIT_SECONDS / max(1, tries - 1))
    return held


def busy_message(rec: dict) -> str:
    return (f"다른 실행이 돌고 있습니다({rec.get('host', '?')} {rec.get('caller', '?')} {rec.get('command', '?')} "
            f"{rec.get('at', '?')})")


def refuse(case_dir: str | Path, cmd: str, argv: list[str], rec: dict, answer: bool = False) -> int:
    """잠겨 있어 돌리지 않은 명령. 기록.jsonl 에 끝 코드 3 줄을 적고 까닭을 찍는다."""
    msg = busy_message(rec)
    msg += ". 답을 넣지 못했습니다. 다시 넣어 주십시오" if answer else ". 끝난 뒤 다시 돌려 주십시오"
    append(case_dir, {"at": datetime.now().isoformat(timespec="seconds"), "command": cmd, "args": [str(a) for a in argv],
                      "caller": caller(), "exit": 3, "seconds": 0.0, "error": msg[:ERROR_MAX]})
    line = f"끝 코드 3: {msg}"
    try:
        print(line)
    except UnicodeEncodeError:
        sys.stdout.buffer.write((line + "\n").encode("utf-8", "replace"))
    return 3
