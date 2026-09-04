#!/usr/bin/env python3
"""viewer 템플릿에 데이터를 끼워 단일 HTML 을 만든다.
사용: assemble.py <viewer.html> <data.json> <out.html>"""
import sys, pathlib
tpl, data, out = (pathlib.Path(p) for p in sys.argv[1:4])
s = tpl.read_text(encoding='utf-8')
assert '__DATA__' in s, 'viewer.html 에 __DATA__ 자리가 없습니다'
out.write_text(s.replace('__DATA__', data.read_text(encoding='utf-8')), encoding='utf-8')
print(f"[codestrata] {out}  ({out.stat().st_size//1024}KB)")
