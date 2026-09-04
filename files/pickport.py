#!/usr/bin/env python3
"""쓸 포트를 고른다.  사용법: pickport.py <원하는포트> <레포명>  ->  "<포트> <모드>"

모드: new(비었음) · reuse(이미 같은 것을 서빙 중) · moved(옆 포트) · fail(전부 참)
포트 충돌로 죽으면 사용자의 첫 실행이 그 자리에서 깨진다 — 죽지 말고 가른다.
"""
import socket, sys, urllib.request

want, name = int(sys.argv[1]), sys.argv[2]

def free(p):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind(("0.0.0.0", p))
        return True
    except OSError:
        return False
    finally:
        s.close()

def serving(p):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{p}/{name}.html", timeout=1.0) as r:
            return r.status == 200
    except Exception:
        return False

if free(want):
    print(want, "new")
elif serving(want):
    print(want, "reuse")
else:
    for p in range(want + 1, want + 21):
        if free(p):
            print(p, "moved")
            break
    else:
        print(want, "fail")
