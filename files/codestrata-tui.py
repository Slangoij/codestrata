#!/usr/bin/env python3
"""codestrata-tui — 산출물 HTML 을 브라우저 없이 **터미널 안에서** 보고 조작한다.

  codestrata-tui                          # 지금 폴더가 속한 레포 (없으면 목록)
  codestrata-tui <레포경로>                 # 그 레포 (그림이 없거나 낡았으면 먼저 굽는다)
  codestrata-tui ~                        # 레포가 아닌 폴더 → 그 아래 레포 목록. 목록에서 Tab·Enter 로 연다
  codestrata-tui <레포명>                   # ~/debug-captures/codebase-3d/<레포명>.html

원리: 헤드리스 크로미움이 뷰어를 그리고, 그 화면을 kitty 그래픽 프로토콜로 터미널 셀에
직접 뿌린다. 터미널의 키·마우스(드래그·휠·Shift+드래그)는 CDP 로 브라우저에 그대로 넘긴다.
그래서 조작법은 브라우저 뷰어와 같다(`?` 도움말). `q` 또는 Ctrl+C 로 나간다.

전제: kitty 그래픽을 아는 터미널(Ghostty·kitty·WezTerm). tmux 안이면 `allow-passthrough on`.
ssh 너머에서도 된다 — 그림은 이스케이프 시퀀스라 지금 앉은 기기의 터미널이 그린다.
의존성: python3 표준 라이브러리 + chromium. (websocket 라이브러리 없이 CDP 를 직접 말한다.)

한계:
- 초당 5~8프레임(소프트웨어 렌더 + PNG). 회전은 되지만 브라우저처럼 매끄럽지는 않다.
- 마우스 좌표는 셀 단위라 드래그가 셀 크기(≈8px)씩 끊긴다. 커서만 움직이는 hover 는 안 온다
  (버튼을 누른 채 움직일 때만 이벤트가 오는 모드) — 클릭 직전에 그 자리로 hover 를 한 번 보낸다.
- 셀의 픽셀 크기를 터미널이 알려 주지 않으면(일부 tmux 경로) 폭:높이 = 1:2 로 가정한다.
"""
import base64, json, os, re, select, shutil, signal, socket, struct, subprocess, sys, termios, threading, time, tty, unicodedata, urllib.request

OUT_DIR   = os.path.expanduser('~/debug-captures/codebase-3d')
def work_dir():
    """사본·프로필을 두는 곳. snap 크로미움은 홈의 숨김 디렉터리(~/.cache)를 못 읽어
    페이지가 오류 화면으로 뜬다(2026-09-02 실측) → snap 이면 ~/snap/chromium/common 아래."""
    if find_chromium().startswith('/snap/'):
        return os.path.expanduser('~/snap/chromium/common/codestrata')
    return os.path.expanduser('~/.cache/codestrata')
THREE_URL = 'https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js'
THREE_TAG = f'<script src="{THREE_URL}"></script>'
MAX_W     = int(os.environ.get('CODESTRATA_MAXW', 1920))   # 스크린샷 폭 상한 — 크면 프레임이 느려진다
PLAY_SS   = float(os.environ.get('CODESTRATA_PLAY_SS', 0.6))  # 재생 중 밀도. 프레임 전송량이 절반으로 준다
SS        = float(os.environ.get('CODESTRATA_SS', 1.0))    # 픽셀 밀도(deviceScaleFactor). 셀 크기를 못 구해
                                                           # 터미널이 확대하는 상황에서만 올린다(2 정도)
LOG = open(os.environ['CODESTRATA_TUI_LOG'], 'a') if os.environ.get('CODESTRATA_TUI_LOG') else None
def log(*a):
    if LOG: LOG.write(' '.join(str(x) for x in a) + '\n'); LOG.flush()

# ── 최소 WebSocket 클라이언트 (CDP 는 텍스트 프레임만 쓴다) ──────────────────
class WS:
    def __init__(self, url):
        host, port, path = re.match(r'ws://([^:/]+):(\d+)(/.*)', url).groups()
        self.s = socket.create_connection((host, int(port)))
        key = base64.b64encode(os.urandom(16)).decode()
        self.s.sendall((f'GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\nUpgrade: websocket\r\n'
                        f'Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n').encode())
        buf = b''
        while b'\r\n\r\n' not in buf:
            buf += self.s.recv(4096)
        head, self.buf = buf.split(b'\r\n\r\n', 1)
        if b' 101 ' not in head.split(b'\r\n')[0]:
            raise ConnectionError(head[:200])
        self.s.settimeout(15)                 # 페이지가 바뀌는 중엔 응답이 안 올 수 있다 — 영원히 기다리지 않는다
        self.id = 0
    def _read(self, n):
        chunks = [self.buf]; have = len(self.buf)
        while have < n:
            d = self.s.recv(1 << 18)
            if not d: raise ConnectionError('ws closed')
            chunks.append(d); have += len(d)
        data = b''.join(chunks)
        out, self.buf = data[:n], data[n:]
        return out
    def _send(self, op, data):
        n = len(data); mask = os.urandom(4)
        if n < 126:      hdr = bytes([0x80 | op, 0x80 | n])
        elif n < 65536:  hdr = bytes([0x80 | op, 0x80 | 126]) + struct.pack('>H', n)
        else:            hdr = bytes([0x80 | op, 0x80 | 127]) + struct.pack('>Q', n)
        masked = bytes(b ^ mask[i & 3] for i, b in enumerate(data))
        self.s.sendall(hdr + mask + masked)
    def recv(self):
        while True:
            b0, b1 = self._read(2)
            op, n = b0 & 0x0f, b1 & 0x7f
            if n == 126:   n = struct.unpack('>H', self._read(2))[0]
            elif n == 127: n = struct.unpack('>Q', self._read(8))[0]
            if b1 & 0x80: self._read(4)          # 서버는 마스킹하지 않는다
            payload = self._read(n)
            if op == 0x9: self._send(0xA, payload); continue   # ping → pong
            if op == 0x8: raise ConnectionError('ws closed by peer')
            if op == 0x1: return json.loads(payload)
    def call(self, method, params=None, wait=True):
        """wait=False 면 보내기만 한다(입력 이벤트용). 늦게 오는 응답은 다음 call 이 id 로 걸러 버린다."""
        self.id += 1
        self._send(0x1, json.dumps({'id': self.id, 'method': method, 'params': params or {}}).encode())
        if not wait: return None
        while True:
            m = self.recv()
            if m.get('id') == self.id:
                if 'error' in m: raise RuntimeError(f"{method}: {m['error']}")
                return m.get('result', {})

# ── 대상 HTML 고르기 ─────────────────────────────────────────────────────────
def git_root(d):
    r = subprocess.run(['git', '-C', d, 'rev-parse', '--show-toplevel'], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else None

def pick_target(arg):
    """codestrata 와 같은 규칙. 경로 → 그 레포의 그림(레포가 아닌 폴더면 그 아래 레포 목록),
    레포명 → ~/debug-captures/codebase-3d/<이름>.html, 없음 → 지금 폴더의 레포. 그림이 없으면 굽는다."""
    if arg and arg.endswith('.html'): return os.path.abspath(arg)
    d = os.path.expanduser(arg) if arg else os.getcwd()
    if os.path.isdir(d):
        root = git_root(d)
        html = os.path.join(OUT_DIR, os.path.basename(root) + '.html') if root else os.path.join(OUT_DIR, 'index.html')
        if not os.path.exists(html) or (root and os.path.getmtime(html) < os.path.getmtime(os.path.join(root, '.git'))):
            print(f'[codestrata-tui] 그림을 굽습니다: codestrata {root or d} --no-serve', flush=True)
            subprocess.run(['codestrata', root or d, '--no-serve'])
        return html
    return os.path.join(OUT_DIR, f'{arg}.html')

def make_copy(src):
    """헤드리스 file:// 에서는 하위 <script src> 가 막히므로 three.js 를 인라인한 사본을 만든다."""
    CACHE = work_dir(); os.makedirs(CACHE, exist_ok=True)
    three = os.path.join(CACHE, 'three.min.js')
    if not os.path.exists(three):
        try:
            with urllib.request.urlopen(THREE_URL, timeout=20) as r, open(three, 'wb') as f: shutil.copyfileobj(r, f)
        except Exception as e:
            sys.stderr.write(f'[codestrata-tui] three.js 를 받지 못했습니다({e}) — CDN 에 기대 봅니다\n')
    html = open(src, encoding='utf-8').read()
    # file:// 에는 charset 을 알려 주는 HTTP 헤더가 없다. three.js 를 앞에 인라인하면
    # 파일의 84% 지점까지 전부 ASCII 라, 크로미움의 인코딩 자동판별이 UTF-8 을 못 보고
    # Latin-1 로 떨어져 한글이 전부 깨진다(2026-09-03 실측). 추측할 여지를 없앤다.
    if not re.search(r'<meta[^>]*charset', html[:1024], re.I):
        html = '<meta charset="utf-8">\n' + html
    if os.path.basename(src) == 'index.html':
        # headless file:// 문서는 창 포커스가 없어 Tab의 기본 링크 이동이 안 된다.
        # 목록 사본 안에서만 직접 포커스하고 Enter로 연다(뷰어의 Tab 단축키는 건드리지 않는다).
        keys = """<script>
document.addEventListener('keydown', e => {
  const links = [...document.querySelectorAll('a[href]')];
  if (e.key === 'Tab' && links.length) {
    e.preventDefault();
    const at = links.indexOf(document.activeElement);
    links[(at + (e.shiftKey ? -1 : 1) + links.length) % links.length].focus();
  } else if (e.key === 'Enter' && document.activeElement?.href) {
    e.preventDefault();
    location.href = document.activeElement.href;
  }
});
</script>"""
        html = html.replace('</body>', keys + '</body>')
    if os.path.exists(three) and THREE_TAG in html:
        html = html.replace(THREE_TAG, '<script>' + open(three, encoding='utf-8').read() + '</script>')
    # 목록(index)의 링크는 원본 산출물을 가리키는데 그건 three 가 CDN 이라 헤드리스에서 안 뜬다
    # → 링크된 그림마다 인라인 사본을 만들고 링크를 그쪽으로 돌린다
    def link_copy(m):
        name = m.group(1); srcp = os.path.join(OUT_DIR, name)
        if not os.path.exists(srcp): return m.group(0)
        sub = open(srcp, encoding='utf-8').read()
        if os.path.exists(three) and THREE_TAG in sub:
            sub = sub.replace(THREE_TAG, '<script>' + open(three, encoding='utf-8').read() + '</script>')
        dst = os.path.join(CACHE, f'view-{os.getpid()}-{name}')
        open(dst, 'w', encoding='utf-8').write(sub); COPIES.append(dst)
        return f'href="file://{dst}"'
    html = re.sub(r'href="([^"/:]+\.html)"', link_copy, html)
    view = os.path.join(CACHE, f'view-{os.getpid()}.html')
    open(view, 'w', encoding='utf-8').write(html); COPIES.append(view)
    return view
COPIES = []   # 만든 사본 전부 — 끝날 때 지운다

# ── 크로미움 ─────────────────────────────────────────────────────────────────
def find_chromium():
    for c in ('chromium', 'chromium-browser', 'google-chrome', 'google-chrome-stable',
              '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
              '/Applications/Chromium.app/Contents/MacOS/Chromium'):
        p = shutil.which(c) if '/' not in c else (c if os.path.exists(c) else None)
        if p: return p
    sys.exit('[codestrata-tui] chromium 을 찾지 못했습니다')

def launch(view, w, h):
    prof = os.path.join(work_dir(), f'profile-{os.getpid()}')
    # ⚠️ 프로필 디렉터리를 미리 만들지 않는다 — snap 크로미움은 남이 만든 디렉터리에
    # ProcessSingleton 잠금을 못 만들어 rc=21 로 죽는다(2026-09-02, 5가지 조합으로 확정).
    # 빈 포트를 미리 잡아 고정으로 준다. `--remote-debugging-port=0` + DevToolsActivePort 는
    # snap 크로미움에서 파일이 안 보여 못 쓴다(2026-09-02 실측).
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0)); port = s.getsockname()[1]
    proc = subprocess.Popen([find_chromium(), '--headless=new', '--enable-unsafe-swiftshader', '--disable-gpu',
        '--no-sandbox', f'--remote-debugging-port={port}', '--remote-allow-origins=*', f'--user-data-dir={prof}',
        f'--window-size={w},{h}', '--hide-scrollbars', 'file://' + view],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ws_url = None
    for _ in range(200):
        try:
            for t in json.load(urllib.request.urlopen(f'http://127.0.0.1:{port}/json/list')):
                if t['type'] == 'page' and 'view-' in t.get('url', ''): ws_url = t['webSocketDebuggerUrl']
            if ws_url: break
        except Exception: pass
        time.sleep(.1)
    if not ws_url: proc.kill(); sys.exit('[codestrata-tui] 크로미움이 뜨지 않았습니다')
    return proc, prof, WS(ws_url)

# ── 터미널 ───────────────────────────────────────────────────────────────────
IN_TMUX = bool(os.environ.get('TMUX'))
def wrap(seq):
    """tmux 안에서는 passthrough 로 감싸야 바깥 터미널에 닿는다(allow-passthrough on 필요)."""
    return '\x1bPtmux;' + seq.replace('\x1b', '\x1b\x1b') + '\x1b\\' if IN_TMUX else seq
def out(s): sys.stdout.write(s); sys.stdout.flush()

def _ask(fd, query, pattern, timeout=.4):
    """질의를 보내고 응답을 기다린다. tmux 가 안 받아 주면 None."""
    out(query)
    buf = b''; end = time.time() + timeout
    while time.time() < end and select.select([fd], [], [], max(0, end - time.time()))[0]:
        buf += os.read(fd, 128)
        m = re.search(pattern, buf)
        if m: return m
    return None

def cell_pixels(fd):
    """셀 하나의 픽셀 크기. 이 값이 틀리면 렌더 종횡비가 어긋나 터미널이 그림을 늘려
    글자가 뭉개진다(2026-09-03 사용자 보고). 그래서 세 경로로 구하고 마지막에만 가정한다."""
    env = os.environ.get('CODESTRATA_CELL', '')
    m = re.match(r'^(\d+)x(\d+)$', env.strip())
    if m: return int(m.group(1)), int(m.group(2)), 'env'
    # ① CSI 16 t → ESC [ 6 ; 높이 ; 폭 t (셀 크기를 직접 알려 준다)
    m = _ask(fd, '\x1b[16t', rb'\x1b\[6;(\d+);(\d+)t')
    if m: return int(m.group(2)), int(m.group(1)), '16t'
    # ② CSI 14 t(글자영역 픽셀) ÷ CSI 18 t(글자영역 칸)
    a = _ask(fd, '\x1b[14t', rb'\x1b\[4;(\d+);(\d+)t')
    b = _ask(fd, '\x1b[18t', rb'\x1b\[8;(\d+);(\d+)t')
    if a and b:
        ph, pw = int(a.group(1)), int(a.group(2)); ch_, cc = int(b.group(1)), int(b.group(2))
        if cc > 0 and ch_ > 0: return max(1, pw // cc), max(1, ph // ch_), '14t/18t'
    return 8, 16, '기본값(가정)'

# ── 유니코드 자리표시자 ───────────────────────────────────────────────────────
# tmux 는 통과(passthrough)시킨 그림을 자기 화면 모형에 안 남긴다. 그래서 페인이 둘 이상이면
# 같은 그림이 두 페인에 겹쳐 나온다(2026-09-03 사용자 보고). 자리표시자 방식은 그림을 "전송만"
# 하고, 화면에는 U+10EEEE 를 셀마다 찍어 그 셀에 이미지 조각을 고정한다. 그 글자는 tmux 가
# 아는 평범한 텍스트라 페인 경계·스크롤이 그대로 지켜진다.
# 행·열 번호는 결합문자로 싣는다. 표는 kitty 의 rowcolumn-diacritics.txt(유니코드 6.0.0 기준).
_RCD_HEX = (
    "0305 030D 030E 0310 0312 033D 033E 033F 0346 034A 034B 034C 0350 0351 0352 0357 035B 0363 "
    "0364 0365 0366 0367 0368 0369 036A 036B 036C 036D 036E 036F 0483 0484 0485 0486 0487 0592 "
    "0593 0594 0595 0597 0598 0599 059C 059D 059E 059F 05A0 05A1 05A8 05A9 05AB 05AC 05AF 05C4 "
    "0610 0611 0612 0613 0614 0615 0616 0617 0657 0658 0659 065A 065B 065D 065E 06D6 06D7 06D8 "
    "06D9 06DA 06DB 06DC 06DF 06E0 06E1 06E2 06E4 06E7 06E8 06EB 06EC 0730 0732 0733 0735 0736 "
    "073A 073D 073F 0740 0741 0743 0745 0747 0749 074A 07EB 07EC 07ED 07EE 07EF 07F0 07F1 07F3 "
    "0816 0817 0818 0819 081B 081C 081D 081E 081F 0820 0821 0822 0823 0825 0826 0827 0829 082A "
    "082B 082C 082D 0951 0953 0954 0F82 0F83 0F86 0F87 135D 135E 135F 17DD 193A 1A17 1A75 1A76 "
    "1A77 1A78 1A79 1A7A 1A7B 1A7C 1B6B 1B6D 1B6E 1B6F 1B70 1B71 1B72 1B73 1CD0 1CD1 1CD2 1CDA "
    "1CDB 1CE0 1DC0 1DC1 1DC3 1DC4 1DC5 1DC6 1DC7 1DC8 1DC9 1DCB 1DCC 1DD1 1DD2 1DD3 1DD4 1DD5 "
    "1DD6 1DD7 1DD8 1DD9 1DDA 1DDB 1DDC 1DDD 1DDE 1DDF 1DE0 1DE1 1DE2 1DE3 1DE4 1DE5 1DE6 1DFE "
    "20D0 20D1 20D4 20D5 20D6 20D7 20DB 20DC 20E1 20E7 20E9 20F0 2CEF 2CF0 2CF1 2DE0 2DE1 2DE2 "
    "2DE3 2DE4 2DE5 2DE6 2DE7 2DE8 2DE9 2DEA 2DEB 2DEC 2DED 2DEE 2DEF 2DF0 2DF1 2DF2 2DF3 2DF4 "
    "2DF5 2DF6 2DF7 2DF8 2DF9 2DFA 2DFB 2DFC 2DFD 2DFE 2DFF A66F A67C A67D A6F0 A6F1 A8E0 A8E1 "
    "A8E2 A8E3 A8E4 A8E5 A8E6 A8E7 A8E8 A8E9 A8EA A8EB A8EC A8ED A8EE A8EF A8F0 A8F1 AAB0 AAB2 "
    "AAB3 AAB7 AAB8 AABE AABF AAC1 FE20 FE21 FE22 FE23 FE24 FE25 FE26 10A0F 10A38 1D185 1D186 "
    "1D187 1D188 1D189 1D1AA 1D1AB 1D1AC 1D1AD 1D242 1D243 1D244"
)
RCD = [chr(int(h, 16)) for h in _RCD_HEX.split()]
IMG_ID = 1
PLACEMENT = os.environ.get('CODESTRATA_PLACEMENT', 'auto')   # auto | unicode | direct

def use_unicode():
    """tmux 안에서는 자리표시자, 밖에서는 예전처럼 커서 위치에 직접 배치."""
    return PLACEMENT == 'unicode' or (PLACEMENT == 'auto' and IN_TMUX)

def _fg_of(img_id):
    """이미지 ID 를 전경색에 싣는다 — 자리표시자는 이 색으로 어느 그림인지 안다."""
    if img_id < 256: return f'\x1b[38;5;{img_id}m'
    return f'\x1b[38;2;{(img_id >> 16) & 255};{(img_id >> 8) & 255};{img_id & 255}m'

def placeholder_grid(cols, rows, img_id=IMG_ID):
    """셀마다 U+10EEEE + 행 결합문자 + 열 결합문자. 한 번 찍어 두면 프레임마다 다시 안 찍어도 된다."""
    cols = min(cols, len(RCD)); rows = min(rows, len(RCD))
    fg = _fg_of(img_id)
    return ''.join(f'\x1b[{r + 1};1H' + fg + ''.join('\U0010EEEE' + RCD[r] + RCD[c] for c in range(cols)) + '\x1b[39m'
                   for r in range(rows))

_grid = None          # 자리표시자를 찍어 둔 크기 (cols, rows)

def draw(png_b64, cols, rows):
    global _grid
    chunks = [png_b64[i:i + 4096] for i in range(0, len(png_b64), 4096)]
    uni = use_unicode()
    # 자리표시자 방식은 전송만(a=t) 하고 배치는 가상 배치(a=p,U=1)로, 예전 방식은 전송+표시(a=T).
    head = f'a=t,f=100,i={IMG_ID},q=2' if uni else f'a=T,f=100,i={IMG_ID},q=2,c={cols},r={rows}'
    seq = [] if uni else ['\x1b[H']
    for i, c in enumerate(chunks):
        m = 0 if i == len(chunks) - 1 else 1
        seq.append(wrap(f'\x1b_G{head + f",m={m}" if i == 0 else f"m={m}"};{c}\x1b\\'))
    if uni:
        seq.append(wrap(f'\x1b_Ga=p,U=1,i={IMG_ID},p=1,c={cols},r={rows},q=2\x1b\\'))
        if _grid != (cols, rows):
            seq.append(placeholder_grid(cols, rows)); _grid = (cols, rows)
    out(''.join(seq))

def dwidth(t):
    """터미널이 실제로 쓰는 칸 수. 한글·전각은 2칸, 결합문자는 0칸이다."""
    w = 0
    for ch in t:
        if unicodedata.combining(ch): continue
        w += 2 if unicodedata.east_asian_width(ch) in 'WF' else 1
    return w

def dclip(t, limit):
    """limit 칸을 넘지 않게 자른다. 자르면 끝에 … 를 붙인다."""
    if dwidth(t) <= limit: return t
    out_s, w = [], 0
    for ch in t:
        cw = 0 if unicodedata.combining(ch) else (2 if unicodedata.east_asian_width(ch) in 'WF' else 1)
        if w + cw > limit - 1: break
        out_s.append(ch); w += cw
    return ''.join(out_s) + '…'

def status(rows, text, cols=None):
    # ⚠️ 상태 줄이 터미널 폭을 넘으면 줄바꿈되고, 그때마다 화면이 한 줄씩 밀려 올라간다.
    # 예전에는 매 프레임 그림이 화면을 덮어 안 보였지만, 자리표시자는 한 번만 찍으므로
    # 밀린 자국이 그대로 쌓인다(2026-09-04 사용자 보고). 폭에 맞춰 자르고 줄바꿈도 끈다.
    if cols:
        text = dclip(text, max(4, cols - 3))       # 앞뒤 공백 두 칸 + 여유 한 칸
    out(f'\x1b[?7l\x1b[{rows};1H\x1b[2K\x1b[7m {text} \x1b[0m\x1b[?7h')

# ── 입력 → CDP ───────────────────────────────────────────────────────────────
MOUSE_RE = re.compile(rb'\x1b\[<(\d+);(\d+);(\d+)([Mm])')
CSI_RE   = re.compile(rb'\x1b\[([0-9;]*)([A-Za-z~])')           # ESC [ 파라미터 최종문자
CSI_KEYS = {b'A': 'ArrowUp', b'B': 'ArrowDown', b'C': 'ArrowRight', b'D': 'ArrowLeft', b'Z': 'Tab'}
NAMED = {b'\x1b': ('Escape', 0), b' ': (' ', 0), b'\r': ('Enter', 0), b'\n': ('Enter', 0), b'\t': ('Tab', 0), b'\x1b[Z': ('Tab', 8)}

class Bridge:
    def __init__(self, cdp, cols, rows_img, W, H, home_url=None, cw=8, ch=16):
        self.cdp, self.cols, self.rows, self.W, self.H = cdp, cols, rows_img, W, H
        self.cw, self.ch = cw, ch
        self.pixel = False        # 터미널이 1016(SGR 픽셀 좌표)을 지원하면 True 로 바뀐다
        self.pan = False          # p 로 켜는 패닝 모드. Shift+드래그는 터미널이 선택 기능으로
                                  # 가로채 앱까지 오지 않으므로, 켜면 그냥 드래그가 패닝이 된다
        self.home_url = home_url
        self.down = None          # (button, modifiers) 누르고 있는 버튼
    def px(self, x, y):
        if self.pixel:            # 좌표가 이미 픽셀이다 — 셀 단위로 끊기지 않는다
            return x * self.W / max(1, self.cols * self.cw), y * self.H / max(1, self.rows * self.ch)
        return (x - .5) * self.W / self.cols, (y - .5) * self.H / self.rows
    def mouse(self, typ, x, y, button='none', mods=0, **kw):
        log('mouse', typ, round(x), round(y), button, mods, kw)
        self.cdp.call('Input.dispatchMouseEvent', {'type': typ, 'x': x, 'y': y, 'button': button, 'modifiers': mods, **kw}, wait=False)
    def key(self, key, text=None, mods=0):
        log('key', repr(key), mods)
        p = {'type': 'keyDown', 'key': key, 'modifiers': mods}
        if text: p['text'] = text
        # Enter/Backspace는 페이지를 바꿀 수 있다. 보내기만 하고 곧바로 screenshot을 요청하면
        # 탐색 중인 페이지에서 응답이 유실되어 CDP 소켓이 15초 동안 멎는다.
        self.cdp.call('Input.dispatchKeyEvent', p)
        self.cdp.call('Input.dispatchKeyEvent', {'type': 'keyUp', 'key': key, 'modifiers': mods})
    def list_key(self, key, shift=False):
        """headless 목록은 키 기본동작이 불안정하다. 목록일 때만 링크를 직접 고르고 연다."""
        direction = -1 if shift else 1
        expression = f"""(() => {{
          if (document.title !== 'Commit Strata') return false;
          const links = [...document.querySelectorAll('a[href]')];
          if (!links.length) return false;
          if ({json.dumps(key)} === 'Tab') {{
            const at = links.indexOf(document.activeElement);
            links[(at + {direction} + links.length) % links.length].focus();
          }} else if ({json.dumps(key)} === 'Enter') {{
            const link = links.includes(document.activeElement) ? document.activeElement : links[0];
            return {{key:'Enter', active:link.href}};
          }} else return false;
          return {{key:{json.dumps(key)}, active:document.activeElement?.href || ''}};
        }})()"""
        result = self.cdp.call('Runtime.evaluate', {'expression': expression, 'returnByValue': True})
        value = result.get('result', {}).get('value', False)
        log('list-key', value)
        if key == 'Enter' and isinstance(value, dict) and value.get('active'):
            self.cdp.call('Page.navigate', {'url': value['active']})
        return bool(value)
    def feed(self, data):
        """한 번에 읽은 바이트 뭉치를 이벤트로 나눠 브라우저에 보낸다. 연속된 드래그 이동은 마지막 것만."""
        log('feed', repr(data[:120]))
        i = 0; pending_move = None
        def flush_move():
            nonlocal pending_move
            if pending_move: self.mouse(*pending_move); pending_move = None
        while i < len(data):
            m = MOUSE_RE.match(data, i)
            if m:
                b, x, y, kind = int(m.group(1)), int(m.group(2)), int(m.group(3)), m.group(4)
                i = m.end()
                if not self.pixel and (x > self.cols or y > self.rows + 1):
                    self.pixel = True; log('SGR 픽셀 좌표로 판정', x, y)   # 1016 이 먹은 터미널
                if y > (self.rows * self.ch if self.pixel else self.rows): continue   # 상태줄 위는 무시
                px, py = self.px(x, y)
                mods = (8 if b & 4 else 0) | (2 if b & 16 else 0)  # shift=8, ctrl=2
                if b & 64:                                       # 휠
                    flush_move()
                    self.mouse('mouseWheel', px, py, mods=mods, deltaX=0, deltaY=-100 if (b & 3) == 0 else 100)
                elif b & 32:                                     # 이동
                    if self.down: pending_move = ('mouseMoved', px, py, self.down[0], self.down[1])
                    else:         pending_move = ('mouseMoved', px, py)   # 누르지 않은 hover
                elif kind == b'M':                               # 누름
                    flush_move()
                    button = 'right' if (b & 3) == 2 else 'left'
                    pmods = mods | (8 if self.pan else 0)        # 패닝 모드면 뷰어에 Shift 로 알린다
                    self.mouse('mouseMoved', px, py)             # hover 를 먼저 갱신해야 클릭이 그 자리 노드를 잡는다
                    self.mouse('mousePressed', px, py, button, pmods, clickCount=1)
                    self.down = (button, pmods)
                else:                                            # 뗌
                    flush_move()
                    if self.down:
                        self.mouse('mouseReleased', px, py, self.down[0], self.down[1], clickCount=1); self.down = None
                continue
            # 키
            m = CSI_RE.match(data, i)
            if m:                                                # 화살표 등. 파라미터 "1;2" 의 2 = Shift
                i = m.end(); name = CSI_KEYS.get(m.group(2))
                params = m.group(1).split(b';')
                mods = 8 if (len(params) > 1 and params[1] == b'2') or m.group(2) == b'Z' else 0
                flush_move()
                if name and not (name == 'Tab' and self.list_key(name, bool(mods & 8))):
                    self.key(name, mods=mods)
                continue
            seq = data[i:i+1]; i += 1
            flush_move()
            if seq in (b'q', b'\x03', b'\x11'): return 'quit'
            if seq == b'p':                                      # 패닝 모드 토글(뷰어는 p 를 안 쓴다)
                self.pan = not self.pan; log('pan mode', self.pan); continue
            if seq in (b'\x7f', b'\x08'):
                if self.home_url: self.cdp.call('Page.navigate', {'url': self.home_url})
                else: self.cdp.call('Runtime.evaluate', {'expression': 'history.back()'})
                continue
            if seq in NAMED:
                key, mods = NAMED[seq]
                if not (key in ('Tab', 'Enter') and self.list_key(key, bool(mods & 8))):
                    self.key(key, mods=mods)
                continue
            try: ch = seq.decode()
            except UnicodeDecodeError: continue
            if ch.isprintable():
                self.key(ch, text=ch, mods=8 if (ch.isalpha() and ch.isupper()) or ch in '+_?{}<>' else 0)
        flush_move()
        return None

# ── 메인 ─────────────────────────────────────────────────────────────────────
def probe():
    """이 터미널이 셀 크기 질의에 무엇이라 답하는지만 보고 끝낸다. 그림은 그리지 않는다."""
    fd = sys.stdin.fileno(); saved = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        cw, ch, src = cell_pixels(fd)
        cols, rows = shutil.get_terminal_size()
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)
    print(f'셀 {cw}x{ch} (출처 {src}) · 터미널 {cols}x{rows}칸 · 그림 상자 {cols*cw}x{(rows-1)*ch}px'
          f' · TERM={os.environ.get("TERM")} TMUX={"예" if IN_TMUX else "아니오"}')
    if src.startswith('기본값'):
        print('→ 이 터미널은 질의에 답하지 않습니다. CODESTRATA_CELL=<폭>x<높이> 로 직접 지정하세요.')
    return 0

def main():
    src = pick_target(sys.argv[1] if len(sys.argv) > 1 else None)
    if not os.path.exists(src): sys.exit(f'[codestrata-tui] 없음: {src}  (먼저 codestrata <레포> --no-serve)')
    if not sys.stdin.isatty(): sys.exit('[codestrata-tui] 터미널에서 실행하세요')
    fd = sys.stdin.fileno(); saved = termios.tcgetattr(fd)
    view = make_copy(src); proc = prof = None
    # tmux 창이 닫히거나(SIGHUP) 죽임을 당해도(SIGTERM) finally 가 돌아 크로미움·사본을 치우게
    for sig in (signal.SIGHUP, signal.SIGTERM):
        signal.signal(sig, lambda *_: sys.exit(0))
    try:
        tty.setraw(fd)
        out('\x1b[?1049h\x1b[?25l')                    # 대체 화면, 커서 숨김
        cw, ch, cell_src = cell_pixels(fd)
        panes = 0
        if IN_TMUX:      # 통과(passthrough)한 그림은 tmux 가 페인 경계를 못 지킨다 — 둘 이상이면 어긋난다
            try:
                panes = int(subprocess.run(['tmux', 'display', '-p', '#{window_panes}'],
                                           capture_output=True, text=True, timeout=2).stdout.strip() or 0)
            except Exception:
                panes = 0
        # 1003=누르지 않아도 이동 보고(hover), 1006=SGR 좌표, 1016=SGR 픽셀 좌표(지원하면)
        out('\x1b[?1003h\x1b[?1006h\x1b[?1016h')
        def geometry():
            cols, rows = shutil.get_terminal_size()
            rows_img = max(4, rows - 1)
            box_w, box_h = max(1, cols * cw), max(1, rows_img * ch)   # 터미널이 그림을 놓을 픽셀 상자
            # CSS 크기는 상자와 같게 둔다. 폭을 키우면 글자가 화면에서 상대적으로 작아져 오히려
            # 나빠진다 — 선명도는 폭이 아니라 픽셀 밀도(deviceScaleFactor)로 올린다.
            W = max(64, min(MAX_W, box_w))
            H = max(64, int(W * box_h / box_w))            # 상자와 같은 종횡비 — 늘어나지 않는다
            return cols, rows, rows_img, W, H
        cols, rows, rows_img, W, H = geometry()
        status(rows, f'{os.path.basename(src)} 여는 중… (크로미움 기동)', cols)
        proc, prof, cdp = launch(view, W, H)
        cdp.call('Page.enable')
        cdp.call('Emulation.setDeviceMetricsOverride', {'width': W, 'height': H, 'deviceScaleFactor': SS, 'mobile': False})
        # 뷰어가 배치를 계산하는 동안(큰 저장소는 수 초) 페이지는 아무 응답도 못 한다. 그동안
        # 화면이 멎어 보이지 않게, 준비 확인은 딴 스레드에 맡기고 여기서는 경과 시간을 돌린다.
        ready = {}
        def probe_ready():
            t_end = time.time() + 120
            while time.time() < t_end:
                try:
                    r = cdp.call('Runtime.evaluate', {'expression': '!!(window.__cs && __cs.events)', 'returnByValue': True})
                    if r.get('result', {}).get('value'): ready['ok'] = True; return
                except (RuntimeError, socket.timeout, TimeoutError, OSError):
                    pass
                time.sleep(.15)
            ready['ok'] = False
        th = threading.Thread(target=probe_ready, daemon=True); th.start()
        t_start = time.time(); spin = '⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏'
        while th.is_alive():
            status(rows, f'{os.path.basename(src)} 여는 중 · 배치 계산 {time.time() - t_start:4.1f}s {spin[int(time.time() * 8) % len(spin)]}', cols)
            th.join(.12)
        log('ready', ready.get('ok'), f'{time.time() - t_start:.1f}s')
        br = Bridge(cdp, cols, rows_img, W, H, 'file://' + view if os.path.basename(src) == 'index.html' else None, cw, ch)
        resized = [False]
        signal.signal(signal.SIGWINCH, lambda *_: resized.__setitem__(0, True))
        # 자리표시자 방식은 tmux 가 페인 경계를 지켜 주므로 경고가 필요 없다. 직접 배치일 때만 알린다.
        warn = (f'  ·  ⚠tmux 페인 {panes}개 + 직접배치 — 그림이 어긋납니다. prefix z 로 확대하거나 CODESTRATA_PLACEMENT=unicode' if panes > 1 and not use_unicode() else '')
        help_line = (f'{os.path.basename(src)} · hjkl 회전 · ←→ 이동 · +- 줌 · Enter 선택 · Tab 파일 · '
                     f'p 패닝 · ? 도움말 · q 종료 · 셀{cw}×{ch}[{cell_src}]'
                     f'{" 자리표시자" if use_unicode() else " 직접배치"}{warn}')
        last_input = time.time(); frames = 0; t_frame = 0
        playing = False; play_pos = None
        def set_density(d):
            cdp.call('Emulation.setDeviceMetricsOverride', {'width': W, 'height': H, 'deviceScaleFactor': d, 'mobile': False})
        while True:
            if resized[0]:
                resized[0] = False
                cols, rows, rows_img, W, H = geometry()
                br.cols, br.rows, br.W, br.H = cols, rows_img, W, H
                cdp.call('Emulation.setDeviceMetricsOverride', {'width': W, 'height': H, 'deviceScaleFactor': SS, 'mobile': False})
                out('\x1b[2J'); globals()['_grid'] = None; last_input = time.time()
            # 입력 뒤 1.2초는 이징 애니메이션이 있을 수 있어 계속 그리고, 그 뒤엔 입력을 기다린다
            busy = time.time() - last_input < 1.2
            # 재생(스페이스) 중에는 입력이 없어도 화면이 바뀐다 — 뷰어에게 물어 계속 그린다
            if not busy:
                try:
                    st = cdp.call('Runtime.evaluate', {'expression': 'window.__cs ? [__cs.playing, ...__cs.scrub] : null', 'returnByValue': True})['result'].get('value')
                except (RuntimeError, socket.timeout, TimeoutError): st = None
                now_playing = bool(st and st[0]); play_pos = (st[1], st[2]) if st else None
                if now_playing != playing:
                    playing = now_playing; set_density(PLAY_SS if playing else SS)   # 재생 중엔 가볍게, 끝나면 선명하게
                    if not playing: last_input = time.time()                        # 마지막 한 장은 원래 밀도로
                busy = busy or playing
            r = select.select([fd], [], [], .02 if busy else .25)[0]
            if r:
                data = os.read(fd, 65536)
                # ESC 단독인지 시퀀스인지: 잠깐 더 기다려 본다
                if data.endswith(b'\x1b') and select.select([fd], [], [], .03)[0]: data += os.read(fd, 65536)
                if br.feed(data) == 'quit': break
                last_input = time.time()
            t0 = time.time()
            try:
                shot = cdp.call('Page.captureScreenshot', {'format': 'png'})['data']
            except (RuntimeError, socket.timeout, TimeoutError) as e:   # 페이지 전환 중 — 이번 프레임은 건너뛴다
                log('frame skipped', e); last_input = time.time(); continue
            draw(shot, cols, rows_img)
            t_frame = time.time() - t0; frames += 1
            if LOG:
                try: log('frame', frames, f'{t_frame*1000:.0f}ms', len(shot), cdp.call('Runtime.evaluate', {'expression': 'JSON.stringify(window.__cs ? {th:__cs.cam.theta.toFixed(3), d:__cs.cam.dist.toFixed(1), tx:__cs.cam.tx.toFixed(1)} : {title:document.title, href:location.href.slice(-40), active:document.activeElement?.href || document.activeElement?.tagName, body:document.body.innerText.slice(0,80)})', 'returnByValue': True})['result'].get('value'))
                except Exception as e: log('frame', frames, 'eval 실패', e)
            prog = f' · ▶ {play_pos[0]}/{play_pos[1]}' if playing and play_pos else ''
            status(rows, f'{help_line} · {t_frame*1000:.0f}ms{prog}'
                       f'{" ·픽셀" if br.pixel else ""}{" ·패닝" if br.pan else ""}', cols)
    finally:
        # 단계마다 따로 감싼다 — tmux 창이 먼저 닫히면 터미널 쓰기가 EIO 로 죽는데,
        # 그 예외가 파일 정리까지 건너뛰게 만들어 프로필·사본이 남았다(2026-09-02).
        if proc:
            proc.terminate()
            try: proc.wait(5)                  # 다 죽기 전에 지우면 크로미움이 프로필을 다시 써서 잔재가 남는다
            except Exception: proc.kill()
        for c in COPIES:
            try: os.remove(c)
            except OSError: pass
        if prof: shutil.rmtree(prof, ignore_errors=True)
        try: out('\x1b[?1003l\x1b[?1002l\x1b[?1016l\x1b[?1006l' + wrap('\x1b_Ga=d,d=A,q=2\x1b\\') + '\x1b[?25h\x1b[?1049l')
        except OSError: pass
        try: termios.tcsetattr(fd, termios.TCSADRAIN, saved)
        except Exception: pass

if __name__ == '__main__':
    if '--probe' in sys.argv: sys.exit(probe())
    main()
