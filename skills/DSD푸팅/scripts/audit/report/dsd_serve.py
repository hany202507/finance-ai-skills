"""DSD 검토 화면 서버(2026-11-04). `python -m audit dsd serve <결과 폴더>`.

foot --html 이 만든 DSD보기 HTML 을 이 PC 안(127.0.0.1)에서만 열고, 화면의 「수정」 을 받아 dsd 수정판을 쓰고 다시 검증한다.

  GET  /              지금 판의 DSD보기 HTML(수정판이 있으면 수정판, 없으면 원본)
  GET  /api/state     수정 기록 · 원본 · 수정판 이름 · 마지막 검증 시간
  POST /api/fix       {"items": [...]} 고침을 기록에 더하고 원본부터 다시 써서 수정판을 만든 뒤 foot 을 다시 돌린다
  POST /api/undo      마지막 수정 묶음을 빼고 다시 만든다
  POST /api/refresh   지금 판으로 foot 을 다시 돌린다(AI 가 원본 폴더에서 연결 · 판정을 넣은 뒤)
  GET  /api/dsd       수정판 dsd 내려받기

원본 dsd 는 건드리지 않는다. 수정판은 수정 기록(수정기록.json)을 원본에 처음부터 다시 써서 만든다(dsd_fix.rebuild). 그래서 되돌리기가
기록에서 한 묶음을 빼는 것으로 끝난다. foot 옵션은 원본으로 foot 을 돌릴 때 남긴 dsd_실행.json 을 그대로 쓰고 --links 는 주지 않는다
(연결 정의 dsd_연결정의.json 이 이름으로 다시 풀린다). 바깥 주소로는 열지 않는다.
"""
from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote

from . import dsd_fix, dsd_view

RUN_FILE = "dsd_실행.json"
PKG_ROOT = Path(__file__).resolve().parents[2]          # 감사/ (python -m audit 를 부르는 곳). 공개 스킬이면 scripts/(run.py 가 있는 곳)
_OPTS = ("prev", "wtb", "pair", "facts", "case", "stage")


def save_run(out: Path, a, src: Path) -> None:
    """foot 이 원본 dsd 로 돌 때 옵션을 남긴다. 수정판으로 다시 돌릴 때(서버) 쓴다. 수정판으로 돌 때는 덮지 않는다."""
    if dsd_fix.stamp_of(src):
        return
    run = {"dsd": str(Path(src).resolve()), "prior": [str(Path(p).resolve()) for p in (a.prior or [])],
           "text": [str(Path(p).resolve()) for p in (a.text or [])], "mask": str(Path(a.mask).resolve()) if a.mask else "",
           "made": datetime.now().strftime("%Y-%m-%d %H:%M")}
    for k in _OPTS:
        v = getattr(a, k, None)
        run[k] = str(Path(v).resolve()) if v and k not in ("stage",) else (v or "")
    (Path(out) / RUN_FILE).write_text(json.dumps(run, ensure_ascii=False, indent=1), encoding="utf-8")


def foot_argv(run: dict, dsd: Path, out: Path) -> list[str]:
    # 감사 엔진은 python -m audit dsd foot, 공개 DSD푸팅 스킬(엔진 일부만 담고 __main__ 이 없다)은 scripts/run.py foot 로 부른다
    if (PKG_ROOT / "audit" / "__main__.py").exists():
        argv = [sys.executable, "-m", "audit", "dsd", "foot", str(dsd), "--out", str(out), "--html"]
    else:
        argv = [sys.executable, str(PKG_ROOT / "run.py"), "foot", str(dsd), "--out", str(out), "--html"]
    for k in _OPTS:
        if run.get(k):
            argv += [f"--{k}", run[k]]
    if run.get("prior"):
        argv += ["--prior", *run["prior"]]
    if run.get("text") and all(Path(p).exists() for p in run["text"]):
        argv += ["--text", *run["text"]]
    if run.get("mask"):
        argv += ["--mask", run["mask"]]
    return argv


class Session:
    def __init__(self, folder: Path):
        self.folder = Path(folder).resolve()          # foot 은 다른 작업 폴더(PKG_ROOT)에서 돌아 상대 경로를 쓰면 길을 잃는다
        p = self.folder / RUN_FILE
        if not p.exists():
            raise FileNotFoundError(f"{p} 가 없습니다. 먼저 python -m audit dsd foot <dsd> … --html --out {self.folder} 로 돌린다")
        self.run = json.loads(p.read_text(encoding="utf-8"))
        self.original = Path(self.run["dsd"])
        self.lock = threading.Lock()
        self.last = {"sec": None, "line": "", "code": None}

    # ---- 판
    def fixed(self) -> Path:
        return self.folder / dsd_fix.fixed_name(self.original)

    def log(self) -> dict:
        lg = dsd_fix.load_log(self.folder)
        lg["original"] = str(self.original)
        return lg

    def current(self) -> Path:
        return self.fixed() if dsd_fix.all_items(self.log()) and self.fixed().exists() else self.original

    def html(self) -> Path | None:
        p = self.folder / dsd_view.html_name(self.current().stem)
        if p.exists():
            return p
        p = self.folder / dsd_view.html_name(self.original.stem)
        return p if p.exists() else None

    # ---- 검증
    def foot(self) -> dict:
        t0 = time.time()
        r = subprocess.run(foot_argv(self.run, self.current(), self.folder), cwd=PKG_ROOT, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", env={**_env(), "PYTHONIOENCODING": "utf-8"}, timeout=1800)
        lines = [x for x in (r.stdout or "").splitlines() if x.strip()]
        head = next((x for x in lines if "검증 " in x and "FALSE" in x), lines[-1] if lines else "")
        self.last = {"sec": round(time.time() - t0, 1), "line": head, "code": r.returncode,
                     "error": (r.stderr or "")[-1500:] if r.returncode not in (0, 1) else ""}
        return self.last

    def state(self) -> dict:
        lg = self.log()
        return {"live": True, "original": self.original.name, "fixed": self.fixed().name if self.current() != self.original else "",
                "items": dsd_fix.all_items(lg), "batches": len(lg.get("batches", [])), "last": self.last}

    def add(self, items: list[dict]) -> dict:
        """앞서 넣은 고침과 새 고침을 원본에 다시 써서 수정판을 만든다. 들어간 새 고침만 기록에 남긴다."""
        with self.lock:
            lg = self.log()
            mine = {_key(i) for i in items}
            res = dsd_fix.apply(self.original, dsd_fix.all_items(lg) + items, self.fixed())
            if res.get("problems"):                            # 다른 칸까지 바뀌어 쓰지 않았다. 앞 판을 그대로 둔다
                dsd_fix.rebuild(self.original, self.folder, lg)
                return {"ok": False, "done": 0, "failed": [x for x in res["failed"] if _key(x) in mine], "problems": res["problems"]}
            ok_items = [x for x in res["done"] if _key(x) in mine]
            failed = [x for x in res["failed"] if _key(x) in mine]
            if ok_items:
                lg.setdefault("batches", []).append({"at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "items": ok_items})
                dsd_fix.save_log(self.folder, lg)
            last = self.foot() if ok_items else self.last
            return {"ok": True, "done": len(ok_items), "failed": failed, "lost_format": len(res.get("lost_format", [])), "foot": last}

    def undo(self) -> dict:
        with self.lock:
            lg = self.log()
            if not lg.get("batches"):
                return {"ok": False, "why": "되돌릴 수정이 없습니다"}
            gone = lg["batches"].pop()
            dsd_fix.save_log(self.folder, lg)
            dsd_fix.rebuild(self.original, self.folder, lg)
            last = self.foot() if dsd_fix.all_items(lg) else self.last
            return {"ok": True, "undone": len(gone.get("items", [])), "foot": last}

    def refresh(self) -> dict:
        with self.lock:
            return {"ok": True, "foot": self.foot()}


def _key(x: dict) -> str:
    return json.dumps([x.get(k) for k in ("kind", "table", "r", "c", "new", "old", "seg")], ensure_ascii=False, default=str)


def _env() -> dict:
    import os

    return dict(os.environ)


def make_handler(s: Session):
    class H(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):            # 화면 요청마다 줄을 찍지 않는다
            pass

        def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code: int = 200):
            self._send(code, json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8"), "application/json; charset=utf-8")

        def do_GET(self):
            path = self.path.split("?")[0]
            if path in ("/", "/index.html"):
                h = s.html()
                if h is None:
                    return self._send(404, "DSD보기 HTML 이 없습니다. foot --html 을 먼저 돌린다".encode("utf-8"), "text/plain; charset=utf-8")
                return self._send(200, h.read_bytes(), "text/html; charset=utf-8")
            if path == "/api/state":
                return self._json(s.state())
            if path == "/api/dsd":
                p = s.current()
                if p == s.original:
                    return self._json({"ok": False, "why": "아직 수정한 것이 없습니다"}, 404)
                return self._send(200, p.read_bytes(), "application/octet-stream",
                                  {"Content-Disposition": f"attachment; filename*=UTF-8''{quote(p.name)}"})
            return self._send(404, b"", "text/plain")

        def do_POST(self):
            if self.headers.get("Origin") not in (None, f"http://127.0.0.1:{self.server.server_port}", f"http://localhost:{self.server.server_port}"):
                return self._json({"ok": False, "why": "다른 곳에서 온 요청"}, 403)
            n = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
            except ValueError:
                return self._json({"ok": False, "why": "json 이 아닙니다"}, 400)
            path = self.path.split("?")[0]
            try:
                if path == "/api/fix":
                    items = [x for x in body.get("items", []) if isinstance(x, dict)]
                    if not items:
                        return self._json({"ok": False, "why": "고침이 없습니다"}, 400)
                    return self._json(s.add(items))
                if path == "/api/undo":
                    return self._json(s.undo())
                if path == "/api/refresh":
                    return self._json(s.refresh())
            except Exception as e:                        # 화면에 이유를 보이고 서버는 계속 돈다
                return self._json({"ok": False, "why": f"{type(e).__name__}: {e}"}, 500)
            return self._json({"ok": False, "why": "없는 주소"}, 404)

    return H


def serve(folder: Path, port: int = 8791, open_browser: bool = True) -> None:
    s = Session(folder)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(s))
    url = f"http://127.0.0.1:{httpd.server_port}/"
    print(f"DSD 검토 화면 {url} (원본 {s.original.name} · 수정 {len(dsd_fix.all_items(s.log()))}건). 끝내려면 Ctrl+C")
    if open_browser:
        import webbrowser

        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
