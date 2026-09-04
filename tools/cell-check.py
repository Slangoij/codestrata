#!/usr/bin/env python3
"""cell_pixels() 만 따로 재는 검사 — 셀 크기가 틀리면 종횡비가 어긋나 글자가 뭉개진다(2026-09-03).

가짜 터미널이 ①CSI 16t 에 답할 때 ②16t 는 무시하고 14t/18t 에만 답할 때 ③아무 것도 답하지 않을 때
세 경우를 각각 만들어, 각 경로가 실제로 쓰이는지 값으로 본다. 부작용이 없는 함수만 부르므로
크로미움을 띄우지 않는다.
"""
import os, pty, re, select, sys, termios, tty, importlib.util

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location('cstui', os.path.join(HERE, 'files', 'codestrata-tui.py'))
cstui = importlib.util.module_from_spec(spec); spec.loader.exec_module(cstui)

def run(mode):
    """가짜 터미널을 열고 자식이 cell_pixels 를 부르게 한다. 부모가 질의에 mode 대로 답한다."""
    pid, fd = pty.fork()
    if pid == 0:                                   # 자식: 질의를 보내고 결과를 부모에게 알린다
        try:
            os.environ.pop('CODESTRATA_CELL', None)
            # 실제 프로그램과 같은 순서: 원시 모드로 바꾼 뒤 질의한다. 정규 모드에서는
            # 줄바꿈 없는 응답이 read 로 넘어오지 않아 검사 자체가 거짓 FAIL 을 낸다.
            tty.setraw(sys.stdin.fileno())
            cw, ch, src = cstui.cell_pixels(sys.stdin.fileno())
            sys.stderr.write(f'RESULT {cw} {ch} {src}\n'); sys.stderr.flush()
        finally:
            os._exit(0)
    buf = b''; out = b''
    while True:
        if not select.select([fd], [], [], 3.0)[0]: break
        try: chunk = os.read(fd, 4096)
        except OSError: break
        if not chunk: break
        buf += chunk; out += chunk
        if mode != 'none':
            if b'\x1b[16t' in buf and mode == '16t':
                os.write(fd, b'\x1b[6;18;9t'); buf = b''
            if b'\x1b[14t' in buf and mode == '14t18t':
                os.write(fd, b'\x1b[4;702;1080t'); buf = buf.replace(b'\x1b[14t', b'')
            if b'\x1b[18t' in buf and mode == '14t18t':
                os.write(fd, b'\x1b[8;39;120t'); buf = buf.replace(b'\x1b[18t', b'')
        if b'RESULT' in out: break
    os.close(fd); os.waitpid(pid, 0)
    m = re.search(rb'RESULT (\d+) (\d+) (\S+)', out)
    return (int(m.group(1)), int(m.group(2)), m.group(3).decode()) if m else None

ok = True
def check(name, cond, detail=''):
    global ok
    ok = ok and cond
    print(f"{'PASS' if cond else 'FAIL'}  {name}  {detail}")

r = run('16t');     check('① 16t 에 답하면 그 값을 쓴다', r == (9, 18, '16t'), str(r))
r = run('14t18t');  check('② 16t 무응답이면 14t/18t 로 나눈다', r == (9, 18, '14t/18t'), str(r))
r = run('none');    check('③ 아무 응답도 없으면 가정값이라고 밝힌다', r == (8, 16, '기본값(가정)'), str(r))

os.environ['CODESTRATA_CELL'] = '11x23'
check('④ CODESTRATA_CELL 이 모든 질의보다 우선', cstui.cell_pixels(0) == (11, 23, 'env'), str(cstui.cell_pixels(0)))
os.environ.pop('CODESTRATA_CELL')

# ⑤ file:// 사본이 charset 을 선언하는가 — 없으면 크로미움이 인코딩을 추측하고,
#    three.js 를 앞에 인라인한 탓에 비ASCII 가 파일 84% 지점에 처음 나와 Latin-1 로 떨어진다.
#    그러면 장면의 한글이 전부 깨진다(2026-09-03 실측). 서버 모드는 헤더가 있어 안 걸린다.
import glob, re as _re
srcs = glob.glob(os.path.expanduser('~/debug-captures/codebase-3d/*.html'))
srcs = [f for f in srcs if os.path.basename(f) != 'index.html']
if not srcs:
    print('SKIP  ⑤ charset 검사  구워진 HTML 이 없습니다')
else:
    copy = cstui.make_copy(srcs[0])
    head = open(copy, 'rb').read(1024)
    try: os.remove(copy)
    except OSError: pass
    check('⑤ file:// 사본이 첫 1024바이트 안에 charset 을 선언', bool(_re.search(rb'<meta[^>]*charset', head, _re.I)),
          os.path.basename(srcs[0]))
    nonascii = next((i for i, b in enumerate(open(copy if os.path.exists(copy) else srcs[0], 'rb').read()) if b > 0x7f), -1)
    print(f'    (참고: 원본에서 비ASCII 첫 위치 {nonascii})')

print('전체:', 'PASS' if ok else 'FAIL'); sys.exit(0 if ok else 1)
