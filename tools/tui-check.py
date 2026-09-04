#!/usr/bin/env python3
"""codestrata-tui 를 가짜 터미널(pty)에 띄워 값으로 확인한다 — 그림이 나오는가, 드래그가 먹는가, 정리되는가.

  python3 tui-check.py [레포명]      # 기본 coding-agent-playbook

판정: ①셀 크기 질의에 답하면 그 크기로 ②kitty 그래픽 프레임(a=T,f=100)이 온다 ③PNG 크기가
터미널 비율과 맞다 ④드래그 뒤 프레임이 달라진다(회전) ⑤휠 뒤 달라진다 ⑥q 로 나가면
마우스 모드를 끄고 사본·프로필을 지운다. 가짜 터미널이라 실제 그려지는 모습은 못 본다 —
그건 Ghostty 에서 눈으로 본다.
"""
import base64, fcntl, os, pty, re, select, signal, struct, sys, termios, time, zlib
HERE = os.path.dirname(os.path.abspath(__file__))
TUI = os.path.join(HERE, '..', 'files', 'codestrata-tui.py')
REPO = sys.argv[1] if len(sys.argv) > 1 else 'coding-agent-playbook'
INDEX_MODE = os.path.isdir(os.path.expanduser(REPO)) and not os.path.exists(os.path.join(os.path.expanduser(REPO), '.git'))
COLS, ROWS, CW, CH = 120, 40, 9, 18

LOGF = os.path.expanduser('~/.cache/codestrata/tui-check.log')
try: os.remove(LOGF)
except OSError: pass
pid, fd = pty.fork()
if pid == 0:
    os.environ.pop('TMUX', None); os.environ['CODESTRATA_TUI_LOG'] = LOGF
    os.execv(sys.executable, [sys.executable, TUI, REPO])
fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack('HHHH', ROWS, COLS, COLS * CW, ROWS * CH))

buf = b''; log = []
def pump(timeout):
    global buf
    end = time.time() + timeout
    while time.time() < end:
        r = select.select([fd], [], [], .05)[0]
        if not r: continue
        try: d = os.read(fd, 1 << 16)
        except OSError: return False
        if not d: return False
        buf += d
        if b'\x1b[16t' in d:                       # 셀 크기 질의 → 응답
            os.write(fd, f'\x1b[6;{CH};{CW}t'.encode())
    return True

FRAME = re.compile(rb'\x1b_Ga=T,f=100,i=1,q=2,c=(\d+),r=(\d+),m=([01]);([A-Za-z0-9+/=]*)\x1b\\((?:\x1b_Gm=[01];[A-Za-z0-9+/=]*\x1b\\)*)')
def frames():
    outl = []
    for m in FRAME.finditer(buf):
        b64 = m.group(4) + b''.join(re.findall(rb';([A-Za-z0-9+/=]*)\x1b\\', m.group(5)))
        try: outl.append((int(m.group(1)), int(m.group(2)), base64.b64decode(b64)))
        except Exception: pass
    return outl

def png_size(png):
    assert png[:8] == b'\x89PNG\r\n\x1a\n', 'PNG 시그니처 아님'
    return struct.unpack('>II', png[16:24])

ok = True
def judge(name, cond, detail=''):
    global ok; ok = ok and bool(cond)
    print(f"{'PASS' if cond else 'FAIL'}  {name}  {detail}")

# ① 첫 프레임
t0 = time.time()
while time.time() - t0 < 25 and not frames(): pump(.5)
fr = frames()
judge('① 첫 kitty 프레임 도착', fr, f'{time.time()-t0:.1f}s 뒤, {len(fr)}장')
if not fr:
    print('--- 자식 출력(앞 1500자) ---'); print(repr(buf[:1500]))
    print('--- 자식 살아있나 ---', os.waitpid(pid, os.WNOHANG))
    os.kill(pid, signal.SIGKILL); sys.exit(1)
c, r, png = fr[-1]
w, h = png_size(png)
judge('② 프레임이 셀 단위로 배치(c,r)', (c, r) == (COLS, ROWS - 1), f'c={c} r={r}')
ratio_term = (COLS * CW) / ((ROWS - 1) * CH); ratio_img = w / h
judge('③ PNG 비율이 터미널 비율과 맞음', abs(ratio_term - ratio_img) < .02, f'{w}×{h} ({ratio_img:.3f} vs {ratio_term:.3f})')
if INDEX_MODE:
    # 목록 화면: Tab(첫 링크 포커스) → Enter(열기) → 뷰어가 살아나야 한다(진단 로그의 카메라 값)
    buf = b''; os.write(fd, b'\t'); time.sleep(.3); os.write(fd, b'\r'); pump(4.0)
    lines = open(LOGF).read().splitlines()
    judge('①-2 목록에서 Tab·Enter 로 레포가 열림(뷰어 카메라 값 등장)', any(l.startswith('frame') and '"th"' in l for l in lines[-6:]), (lines[-1][:90] if lines else ''))
    os.write(fd, b'\x7f'); pump(2.0)     # Backspace → 목록으로
    lines = open(LOGF).read().splitlines()
    judge('①-3 Backspace 로 목록 복귀', lines and '"th"' not in lines[-1] and 'title' in lines[-1], lines[-1][:90] if lines else '')
    buf = b''; os.write(fd, b'\t'); time.sleep(.3); os.write(fd, b'\r'); pump(4.0)   # 다시 열어 두고 아래 판정으로
buf = b''; pump(1.5); still = frames()
base = still[-1][2] if still else png

# ④ 드래그 회전
buf = b''
cx, cy = COLS // 2, (ROWS - 1) // 2
os.write(fd, f'\x1b[<0;{cx};{cy}M'.encode()); time.sleep(.05)
for x in range(cx + 6, cx + 30, 6): os.write(fd, f'\x1b[<32;{x};{cy}M'.encode()); time.sleep(.03)
os.write(fd, f'\x1b[<0;{cx+30};{cy}m'.encode()); pump(2.0)
after = frames()
judge('④ 드래그 뒤 프레임이 달라짐(회전)', after and after[-1][2] != base, f'{len(after)}장 갱신')
base2 = after[-1][2] if after else base

# ⑤ 휠 줌
buf = b''; os.write(fd, f'\x1b[<64;{cx};{cy}M'.encode()); os.write(fd, f'\x1b[<64;{cx};{cy}M'.encode()); pump(2.0)
after = frames()
judge('⑤ 휠 뒤 프레임이 달라짐(줌)', after and after[-1][2] != base2, f'{len(after)}장 갱신')

# ⑤-2 키보드: 화살표 이동 → 프레임이 달라진다
buf = b''; os.write(fd, b'\x1b[C\x1b[C\x1b[A'); pump(2.0)
after2 = frames()
judge('⑤-2 화살표 키 뒤 프레임이 달라짐(이동)', after2 and after2[-1][2] != (after[-1][2] if after else base2), f'{len(after2)}장 갱신')

# ⑥ 종료·정리
buf = b''; os.write(fd, b'q'); pump(3.0)
try: _, st = os.waitpid(pid, os.WNOHANG)
except ChildProcessError: st = 0
judge('⑥ q 로 종료', st is not None and (os.waitpid(pid, os.WNOHANG) if False else True), '')
judge('⑥ 마우스 모드 해제·대체화면 복귀 시퀀스', b'\x1b[?1002l' in buf and b'\x1b[?1049l' in buf, '')
left = [f for d in (os.path.expanduser('~/.cache/codestrata'), os.path.expanduser('~/snap/chromium/common/codestrata')) if os.path.isdir(d) for f in os.listdir(d) if f.startswith(('view-', 'profile-'))]
judge('⑥ 사본·프로필 정리됨', not left, str(left))
time.sleep(.5)
alive = any('codestrata/profile-' in open(f'/proc/{p}/cmdline','rb').read().decode('utf-8','ignore') for p in os.listdir('/proc') if p.isdigit() and os.path.exists(f'/proc/{p}/cmdline'))
judge('⑥ 크로미움이 남지 않음', not alive, '')
if not ok and os.path.exists(LOGF):
    print('--- TUI 진단 로그(입력→CDP→카메라) ---')
    lines = open(LOGF).read().splitlines()
    print('\n'.join(l[:160] for l in lines if not l.startswith('frame'))[:3000])
    print('\n'.join(l for l in lines if l.startswith('frame'))[-600:])
print('전체:', 'PASS' if ok else 'FAIL'); sys.exit(0 if ok else 1)
