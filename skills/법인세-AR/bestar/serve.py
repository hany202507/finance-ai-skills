# -*- coding: utf-8 -*-
"""분석적 검토 화면을 이 PC 에서 띄우고, 회계사가 고른 답 · 반영을 _색인/AR_단계/판단.json 에 저장한다.

  ar.py serve <신고건> [--port 8852]     브라우저로 http://localhost:8852/ 를 연다

이 PC(127.0.0.1)에서만 열린다. 판단을 저장한 뒤 ar.py finish 를 다시 돌리면 엑셀 · 한 파일 화면에도 나온다.
고른 보기에 sets 가 있으면 조서 노란 칸을 맞추고 조서를 다시 계산한 뒤(bestar/link.py) 응답 notice 에 바뀐 금액을 싣는다.
"""
from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from bestar import decide, link, paths, review, review_view


def make_handler(c):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):          # 조용히
            pass

        def _send(self, code: int, body: bytes, ctype: str):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code=200):
            self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

        def do_GET(self):
            path = self.path.split("?")[0]
            if path.endswith("/api/data"):
                return self._json(review.build(c))
            if path in ("/", "/index.html") or path.endswith("/"):
                html = review_view.render(review.build(c), "live")
                return self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")
            self._send(404, b"not found", "text/plain; charset=utf-8")

        def do_POST(self):
            path = self.path.split("?")[0]
            try:
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
            except (ValueError, UnicodeDecodeError):
                return self._json({"error": "본문을 읽지 못했습니다"}, 400)
            keys = review.build(c)["keys"]
            def key(uid):
                return keys.get(uid, uid)
            if path.endswith("/api/decide"):
                if not body.get("uid"):
                    return self._json({"error": "uid 가 없습니다"}, 400)
                decide.decide(c, key(body["uid"]), value=body.get("value"), values=body.get("values"), other=body.get("other"))
            elif path.endswith("/api/accept"):
                decide.accept(c, [key(u) for u in body.get("uids") or []])
            elif path.endswith("/api/undo"):
                decide.undo(c, key(body.get("uid") or ""))
            else:
                return self._json({"error": "모르는 주소"}, 404)
            msg = ""
            if not path.endswith("/api/accept"):            # 답이 조서 칸을 바꾸면 조서를 다시 계산한다
                r = link.sync(c)
                msg = link.notice(r, link.paper_names(c))
            self._json({**review.build(c), "notice": msg})
    return Handler


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="ar.py serve")
    p.add_argument("folder")
    p.add_argument("--port", type=int, default=8852)
    a = p.parse_args(argv)
    c = paths.case(a.folder)
    from bestar import steps
    if not steps.finished(c) or not (paths.index(c) / "조정.json").exists():
        print("ar.py engine 과 1-(1) ~ 2-(2) 단계를 먼저 끝냅니다.")
        return 2
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), make_handler(c))
    print(f"http://localhost:{a.port}/ 를 브라우저로 여십시오(끝내려면 Ctrl+C)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0
