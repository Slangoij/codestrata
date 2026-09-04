#!/usr/bin/env python3
"""charset 을 붙여 주는 최소 정적 서버.
붙이지 않으면 브라우저가 latin-1 로 읽어 **한글이 통째로 깨진다** —
실제로 그걸로 한 번 헛짚었다(2026-09-01)."""
import http.server, socketserver, sys, os
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8899
ROOT = sys.argv[2] if len(sys.argv) > 2 else "."
class H(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=ROOT, **kw)
    def guess_type(self, path):
        t = super().guess_type(path)
        return 'text/html; charset=utf-8' if str(t).startswith('text/html') else t
    def log_message(self, *a):
        pass
socketserver.TCPServer.allow_reuse_address = True
socketserver.TCPServer(("0.0.0.0", PORT), H).serve_forever()
