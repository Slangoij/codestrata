#!/usr/bin/env python3
"""배치 방식 두 가지를 가짜 터미널에서 값으로 가른다(2026-09-04).

tmux 는 통과시킨 그림을 자기 화면 모형에 안 남겨서, 페인이 둘 이상이면 같은 그림이 두 페인에
겹쳐 나온다. 자리표시자(U+10EEEE) 방식은 그림을 전송만 하고 셀마다 평범한 글자를 찍어 고정하므로
tmux 가 페인 경계를 지켜 준다. 이 검사는 두 방식이 실제로 다른 바이트를 내보내는지 본다.

  python3 placement-check.py [레포명]
"""
import fcntl, os, pty, re, select, struct, sys, termios, time, importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
TUI = os.path.join(HERE, '..', 'files', 'codestrata-tui.py')
REPO = sys.argv[1] if len(sys.argv) > 1 else 'coding-agent-playbook'
COLS, ROWS, CW, CH = 100, 30, 9, 18
ROWS_IMG = ROWS - 1
PH = '\U0010EEEE'

spec = importlib.util.spec_from_file_location('cstui', TUI)
cstui = importlib.util.module_from_spec(spec); spec.loader.exec_module(cstui)

def run(mode):
    pid, fd = pty.fork()
    if pid == 0:
        os.environ.pop('TMUX', None)
        os.environ['CODESTRATA_PLACEMENT'] = mode
        os.execv(sys.executable, [sys.executable, TUI, REPO])
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack('HHHH', ROWS, COLS, COLS * CW, ROWS * CH))
    buf = b''; end = time.time() + 40; settle = None
    while time.time() < end:
        if not select.select([fd], [], [], .05)[0]:
            if settle and time.time() > settle: break
            continue
        try: d = os.read(fd, 1 << 16)
        except OSError: break
        if not d: break
        buf += d
        if b'\x1b[16t' in d: os.write(fd, f'\x1b[6;{CH};{CW}t'.encode())
        # 첫 프레임을 본 뒤 2초 더 읽는다 — 자리표시자 격자는 한 번에 다 오지 않는다.
        # 조건이 맞자마자 끊으면 격자가 잘려 "개수 부족"이라는 가짜 실패가 난다(자를 먼저 의심, §2).
        seen = (PH.encode() in buf) if mode == 'unicode' else (b'a=T,f=100' in buf)
        if seen and settle is None: settle = time.time() + 2.0
        if settle and time.time() > settle: break
    try: os.write(fd, b'q')
    except OSError: pass
    time.sleep(1.5)
    try: os.close(fd)
    except OSError: pass
    os.waitpid(pid, 0)
    return buf.decode('utf-8', 'replace')

ok = True
def check(name, cond, detail=''):
    global ok
    ok = ok and bool(cond)
    print(f"{'PASS' if cond else 'FAIL'}  {name}  {detail}")

uni = run('unicode')
check('① 자리표시자 모드: 전송만 하고 표시하지 않는다(a=t, a=T 없음)',
      'a=t,f=100' in uni and 'a=T,f=100' not in uni,
      f"a=t {uni.count('a=t,f=100')}회 · a=T {uni.count('a=T,f=100')}회")
m = re.search(r'a=p,U=1,i=(\d+),p=1,c=(\d+),r=(\d+)', uni)
check('② 가상 배치가 화면 칸 수와 맞는다', bool(m) and (int(m.group(2)), int(m.group(3))) == (COLS, ROWS_IMG),
      m.group(0) if m else '가상 배치 없음')
check('③ 자리표시자를 셀 수만큼 찍는다', uni.count(PH) == COLS * ROWS_IMG,
      f'{uni.count(PH)}개 (기대 {COLS * ROWS_IMG})')
rows_seen = {}
for r, body in re.findall(r'\x1b\[(\d+);1H\x1b\[38;5;1m([^\x1b]*)', uni):
    if PH in body: rows_seen[int(r)] = body
bad = [r for r, b in rows_seen.items() if b[1] != cstui.RCD[r - 1]]
check('④ 각 줄의 행 결합문자가 그 줄 번호와 맞는다', not bad and len(rows_seen) == ROWS_IMG,
      f'{len(rows_seen)}줄 · 어긋난 줄 {bad[:3]}')
first = rows_seen.get(1, '')
cols_ok = all(first[i * 3 + 2] == cstui.RCD[i] for i in range(min(COLS, len(first) // 3)))
check('⑤ 첫 줄의 열 결합문자가 0,1,2… 순서다', cols_ok, f'{len(first) // 3}칸 확인')

dir_ = run('direct')
check('⑥ 음성 대조군 — 직접 배치에는 자리표시자가 없다',
      PH not in dir_ and 'a=T,f=100' in dir_,
      f"자리표시자 {dir_.count(PH)}개 · a=T {dir_.count('a=T,f=100')}회")
print('전체:', 'PASS' if ok else 'FAIL')
sys.exit(0 if ok else 1)
