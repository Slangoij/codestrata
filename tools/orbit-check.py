"""뷰어의 카메라 조작을 헤드리스 크로미움 + CDP 로 검증한다.

  python3 -m venv /tmp/csvenv && /tmp/csvenv/bin/pip install websocket-client
  /tmp/csvenv/bin/python orbit-check.py [레포명]        # 기본 coding-agent-playbook

산출물 HTML(~/debug-captures/codebase-3d/<레포>.html)을 읽어, CDN 의 three.js 를 인라인한
사본을 홈에 만든 뒤(헤드리스에서 file:// 하위 스크립트가 막히므로) 시나리오를 돌린다.
뷰어를 고쳤으면 `codestrata <레포> --no-serve` 로 다시 구운 뒤에 돌린다.
음성 대조군: 사본의 패닝 코드를 옛 것으로 되돌려 같은 판정이 FAIL 나는지 본다.
"""
import re, shutil, urllib.request as _u
import json, subprocess, time, urllib.request, websocket, os, sys

PORT = 9333
REPO = sys.argv[1] if len(sys.argv) > 1 else 'coding-agent-playbook'
SRC  = REPO if REPO.endswith('.html') else os.path.expanduser(f'~/debug-captures/codebase-3d/{REPO}.html')  # 경로를 주면 그 파일(대조군용)
VIEW = os.path.expanduser('~/cs-view-test.html')   # 숨김 파일이 아니어야 snap 크로미움이 읽는다
THREE_URL = 'https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js'
cache = os.path.expanduser('~/.cache/codestrata-three.min.js')
os.makedirs(os.path.dirname(cache), exist_ok=True)
if not os.path.exists(cache):
    with _u.urlopen(THREE_URL) as r, open(cache,'wb') as f: shutil.copyfileobj(r, f)
html = open(SRC, encoding='utf-8').read()
tag = f'<script src="{THREE_URL}"></script>'
assert tag in html, 'three.js CDN 태그를 못 찾았다 — 뷰어가 바뀌었나'
html = html.replace(tag, '<script>' + open(cache, encoding='utf-8').read() + '</script>')
html = html.replace('window.__cs = {', 'window.__three_camera = camera; window.__cs_layout = layout; window.__cs_events = events; window.__cs_H = H; window.__cs_yOf = yOf;\nwindow.__cs = {')
open(VIEW, 'w', encoding='utf-8').write(html)
prof = os.path.expanduser('~/.cache/codestrata-chrome-profile')
proc = subprocess.Popen(['chromium','--headless=new','--enable-unsafe-swiftshader','--disable-gpu',
    '--no-sandbox', f'--remote-debugging-port={PORT}', '--remote-allow-origins=*', f'--user-data-dir={prof}',
    '--window-size=900,700', 'file://' + VIEW],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    ws_url = None
    for _ in range(60):
        try:
            tabs = json.load(urllib.request.urlopen(f'http://127.0.0.1:{PORT}/json/list'))
            for t in tabs:
                if t['type'] == 'page' and 'cs-view-test' in t.get('url',''):
                    ws_url = t['webSocketDebuggerUrl']; break
            if ws_url: break
        except Exception: pass
        time.sleep(0.5)
    assert ws_url, 'CDP 타깃을 찾지 못했다'
    ws = websocket.create_connection(ws_url, timeout=60)
    mid = [0]
    def send(method, params=None):
        mid[0] += 1
        ws.send(json.dumps({'id':mid[0], 'method':method, 'params':params or {}}))
        while True:
            m = json.loads(ws.recv())
            if m.get('id') == mid[0]: return m
    send('Runtime.enable'); send('Page.enable')
    time.sleep(3)   # 뷰어 초기화 대기

    scenario = r"""
(async () => {
  const L = [], log = m => L.push(m);
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const errs = []; window.addEventListener('error', e => errs.push(e.message));
  const el = document.querySelector('canvas');
  if (!el) return 'FATAL: canvas 없음 (THREE=' + (typeof THREE) + ')';
  el.setPointerCapture = () => {}; el.releasePointerCapture = () => {};
  const mk = (t,x,y,shift) => new PointerEvent(t, {pointerId:1, clientX:x, clientY:y,
      shiftKey:!!shift, button:0, buttons:1, bubbles:true, cancelable:true});
  const drag = (shift, dx, dy) => {
    el.dispatchEvent(mk('pointerdown', 400, 300, shift));
    for (let i=1;i<=4;i++) el.dispatchEvent(mk('pointermove', 400+dx*i/4, 300+dy*i/4, shift));
    el.dispatchEvent(mk('pointerup', 400+dx, 300+dy, shift));
  };
  const c = __cs.cam;
  const P = () => ({tx:+c.tx.toFixed(3), ty:+c.ty.toFixed(3), tz:+c.tz.toFixed(3),
                    ou:+c.ou.toFixed(3), ov:+c.ov.toFixed(3), th:+c.theta.toFixed(3)});
  const dist = () => { const p = window.__three_camera.position;
    return Math.hypot(p.x-c.tx, p.y-c.ty, p.z-c.tz); };
  const same = (a,b) => a.tx===b.tx && a.ty===b.ty && a.tz===b.tz;

  __cs.setSelCommit(20); __cs.orbitToSelection(); await sleep(700);
  const a = P();
  log('판정0 회전중심이 원점이 아님: ' + ((a.tx||a.ty||a.tz) ? 'PASS' : 'FAIL — 이 아래 판정은 검증력 없음')); log('선택직후 pivot=' + JSON.stringify(a));
  drag(true, 120, 60);
  const b = P(); log('shift드래그후 = ' + JSON.stringify(b));
  log('판정1 패닝이 회전중심을 안 옮김: ' + (same(a,b) ? 'PASS' : 'FAIL'));
  log('판정2 패닝이 실제로 먹음(ou/ov 변화): ' + ((b.ou!==a.ou || b.ov!==a.ov) ? 'PASS' : 'FAIL'));
  const d0 = dist(); drag(false, 150, 0); const d1 = dist(), cc = P();
  log('판정3 회전축이 pivot (거리 ' + d0.toFixed(2) + ' → ' + d1.toFixed(2) + '): ' + (Math.abs(d0-d1) < 0.5 ? 'PASS' : 'FAIL'));
  log('판정4 회전이 pivot 유지: ' + (same(a,cc) ? 'PASS' : 'FAIL'));
  log('판정5 회전이 실제로 먹음: ' + (cc.th !== a.th ? 'PASS' : 'FAIL'));
  __cs.setSelCommit(-1); await sleep(500);
  const e0 = P(); drag(true, 100, 0); const e1 = P();
  log('판정6 선택없으면 예전대로 과녁 이동: ' + ((!same(e0,e1) && e1.ou===0 && e1.ov===0) ? 'PASS' : 'FAIL')
      + ' ' + JSON.stringify(e0) + ' → ' + JSON.stringify(e1));
  // 'f' 로 재조준하면 다시 노드가 중심 + 화면 중앙
  __cs.setSelCommit(20); __cs.orbitToSelection(); await sleep(700);
  const f = P(); log('판정7 f/선택 재조준시 오프셋 해제: ' + ((f.ou===0 && f.ov===0) ? 'PASS' : 'FAIL'));

  // ── 구슬 클릭: 눌린 "그 구슬"이 회전 중심이어야 한다(그 파일의 최신 구슬이 아니라)
  __cs.setSelCommit(-1); await sleep(400);
  {
    const ev = window.__cs_events, H = window.__cs_H, yOf = window.__cs_yOf, camera = window.__three_camera;  // 사본에 심은 손잡이(옛 HTML 도 됨)
    const px = document.getElementById('scrub'); if (px) { px.value = px.max; px.dispatchEvent(new Event('input')); }
    const latest = new Map(); for (const e of ev) latest.set(e.f, Math.max(latest.get(e.f) ?? -1, e.c));
    let tried = 0, verdict = 'FAIL(후보 없음)';
    for (let k = 0; k < ev.length && tried < 12; k++) {
      if (ev[k].c === latest.get(ev[k].f)) continue;          // 최신 구슬은 판정력이 없다
      const lay = window.__cs_layout; if (!lay) { verdict = 'FAIL(layout 손잡이 없음)'; break; }
      const w = new THREE.Vector3(lay.px[ev[k].f], yOf(ev[k].c) - H/2, lay.py[ev[k].f]);
      const v = w.clone().project(camera); if (v.z > 1) continue;
      const sx = (v.x*.5+.5)*innerWidth, sy = (-v.y*.5+.5)*innerHeight;
      if (sx < 300 || sx > innerWidth-320 || sy < 60 || sy > innerHeight-80) continue; // 패널에 가린 자리는 피한다
      tried++;
      el.dispatchEvent(mk('pointermove', sx, sy, false));
      const got = __cs.hoverEventCi;                     // 새 코드에만 있다(옛 코드는 undefined)
      if (got !== undefined && got !== ev[k].c) continue; // 다른 구슬이 더 가까웠다 — 다음 후보
      el.dispatchEvent(mk('pointerdown', sx, sy, false)); el.dispatchEvent(mk('pointerup', sx, sy, false));
      el.dispatchEvent(new MouseEvent('click', {clientX:sx, clientY:sy, bubbles:true}));
      await sleep(700);
      const want = yOf(ev[k].c) - H/2, top = yOf(latest.get(ev[k].f)) - H/2;
      verdict = (Math.abs(c.ty - want) < 0.05 ? 'PASS' : 'FAIL') +
        ` (누른 구슬 y=${want.toFixed(2)} · 그 파일 최신 구슬 y=${top.toFixed(2)} · 회전중심 y=${c.ty.toFixed(2)}, pinned=${__cs.pinned})`;
      break;
    }
    log('판정8 옛 구슬을 눌러도 그 구슬이 회전중심: ' + verdict);
  }
  // ── 커서 기준 줌: 커서 아래(과녁 깊이 평면) 지점이 줌 뒤에도 같은 화면 자리에 있어야 한다
  {
    const camera = __cs.camera ?? window.__three_camera; camera.updateMatrixWorld();
    const mx = 700, my = 180, ndx = mx/innerWidth*2-1, ndy = 1-my/innerHeight*2;
    const th = Math.tan(camera.fov*Math.PI/360), m = camera.matrixWorld.elements;
    const R = new THREE.Vector3(m[0],m[1],m[2]), U = new THREE.Vector3(m[4],m[5],m[6]), F = new THREE.Vector3(-m[8],-m[9],-m[10]);
    const W = camera.position.clone().add(F.multiplyScalar(c.dist))
      .add(R.multiplyScalar(ndx*th*camera.aspect*c.dist)).add(U.multiplyScalar(ndy*th*c.dist));
    const before = W.clone().project(camera);
    const dBefore = c.dist;
    for (let i = 0; i < 3; i++) el.dispatchEvent(new WheelEvent('wheel', {deltaY:-100, clientX:mx, clientY:my, bubbles:true, cancelable:true}));
    camera.updateMatrixWorld();
    const after = W.clone().project(camera);
    const drift = Math.hypot((after.x-before.x)*innerWidth/2, (after.y-before.y)*innerHeight/2);
    log(`판정9 커서 기준 줌(거리 ${dBefore.toFixed(1)}→${c.dist.toFixed(1)}, 커서 아래 점의 화면 이동 ${drift.toFixed(2)}px): ` + (drift < 1 && c.dist < dBefore ? 'PASS' : 'FAIL'));
  }
  // ── 키보드만으로: 화살표 이동(회전 중심 유지) · Enter 선택 · Tab 파일 순환
  {
    const kd = (key, shift=false) => window.dispatchEvent(new KeyboardEvent('keydown', {key, shiftKey:shift, bubbles:true, cancelable:true}));
    __cs.setSelCommit(20); __cs.orbitToSelection(); await sleep(600);
    const k0 = P(); kd('ArrowRight'); kd('ArrowUp'); const k1 = P();
    log('판정10 화살표 이동: 오프셋 변화·회전중심 유지: ' + ((k1.ou !== k0.ou && k1.ov !== k0.ov && same(k0, k1)) ? 'PASS' : 'FAIL') + ' ' + JSON.stringify(k1));
    kd('Escape'); await sleep(100);
    const sc = document.getElementById('scrub'); sc.value = 15; sc.dispatchEvent(new Event('input'));
    kd('Enter'); await sleep(600);
    const want = __cs.commitWorldPos(15), e1 = P();
    log('판정11 Enter 로 지금 시점 커밋 선택·회전중심: ' + ((__cs.selCommit === 15 && Math.abs(e1.ty - want.y) < 0.05) ? 'PASS' : 'FAIL') + ` sel=${__cs.selCommit} ty=${e1.ty} want=${want.y.toFixed(3)}`);
    const fs = __cs.events.filter(e => e.c === 15).map(e => e.f);
    kd('Tab'); await sleep(600); const p1 = __cs.pinned; const t1 = P();
    kd('Tab'); await sleep(600); const p2 = __cs.pinned;
    const wantY = __cs.yOf(15) - __cs.H/2;
    log('판정12 Tab 으로 그 커밋의 파일 순환·그 구슬이 회전중심: ' + ((fs.includes(p1) && Math.abs(t1.ty - wantY) < 0.05 && (fs.length < 2 || p2 !== p1)) ? 'PASS' : 'FAIL') + ` files=${fs.length} pinned ${p1}→${p2}`);
  }
  {   // 태블릿·폰: 휠도 Shift 도 없으므로 두 손가락이 유일한 줌·이동 수단이다
    const pe = (t,id,x,y) => el.dispatchEvent(new PointerEvent(t, {pointerId:id, clientX:x, clientY:y,
        pointerType:'touch', isPrimary:id===1, button:0, buttons:1, bubbles:true, cancelable:true}));
    const d0 = __cs.cam.dist, o0 = __cs.cam.ou;
    pe('pointerdown',1,600,400); pe('pointerdown',2,700,400); await sleep(60);
    pe('pointermove',1,500,400); pe('pointermove',2,800,400); await sleep(250);   // 벌리면 다가간다
    const d1 = __cs.cam.dist;
    pe('pointermove',1,560,400); pe('pointermove',2,860,400); await sleep(250);   // 같이 밀면 이동한다
    const o1 = __cs.cam.ou;
    pe('pointerup',1,560,400); pe('pointerup',2,860,400); await sleep(120);
    log('판정13 두 손가락 핀치로 줌: ' + (d1 < d0 - 1 ? 'PASS' : 'FAIL') + ` dist ${d0.toFixed(1)} → ${d1.toFixed(1)}`);
    log('판정14 두 손가락으로 밀면 이동: ' + (Math.abs(o1 - o0) > 0.5 ? 'PASS' : 'FAIL') + ` ou ${o0.toFixed(2)} → ${o1.toFixed(2)}`);
    log('판정15 캔버스가 터치를 브라우저에 안 뺏김(touch-action): ' + (getComputedStyle(el).touchAction === 'none' ? 'PASS' : 'FAIL') + ' ' + getComputedStyle(el).touchAction);
  }
  log('JS오류 ' + errs.length + '건 ' + errs.join(' | '));
  return L.join('\n');
})()
"""
    r = send('Runtime.evaluate', {'expression': scenario, 'awaitPromise': True, 'returnByValue': True})
    res = r.get('result', {}).get('result', {})
    print(res.get('value') or json.dumps(r)[:800])
finally:
    for f in (VIEW,):
        try: os.remove(f)
        except OSError: pass
    proc.terminate()
    try: proc.wait(timeout=10)
    except Exception: proc.kill()
