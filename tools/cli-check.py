#!/usr/bin/env python3
"""Braille 문자 3D codestrata의 투영·회전·줌·키 입력을 확인한다."""
import importlib.util,os,pty,select,subprocess,sys,time
HERE=os.path.dirname(os.path.abspath(__file__))
CLI=os.path.abspath(os.path.join(HERE,"..","files","codestrata-cli.py"))
target=sys.argv[1] if len(sys.argv)>1 else "coding-agent-playbook"
run=subprocess.run([sys.executable,CLI,"--plain","--width","100","--height","24",target],
                   capture_output=True,text=True)
checks=[]
def check(name,cond,detail=""):
    checks.append(bool(cond));print(("PASS" if cond else "FAIL")+"  "+name+("  "+detail if detail else ""))
check("정적 3D CLI 종료코드",run.returncode==0,f"rc={run.returncode}")
braille=sum(0x2800<=ord(ch)<=0x28ff for ch in run.stdout)
check("Braille 문자 픽셀로 장면 렌더링",braille>80,f"{braille} cells")
check("3D 카메라 값 표시",all(x in run.stdout for x in ("θ","φ","zoom")))
check("HTML/Chromium 비출력","<html" not in run.stdout.lower() and "chromium" not in run.stdout.lower())
spec=importlib.util.spec_from_file_location("codestrata_cli",CLI)
mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
check("요청한 표시 폭을 넘지 않음",max((mod.display_width(x) for x in run.stdout.splitlines()),default=0)<=100)
data,_=mod.load_data(mod.target_json(target));view=mod.View(data)
def art():
    return "".join(ch for row in mod.scene(view,100,20) for ch,_ in row)
base=art();view.theta+=.4;rotated=art()
view.dist*=.7;zoomed=art();view.move_commit(-1);timed=art()
check("카메라 회전이 3D 장면 자체를 바꿈",base!=rotated,
      f"{sum(a!=b for a,b in zip(base,rotated))} cells")
check("줌이 3D 장면 자체를 바꿈",rotated!=zoomed)
check("시간 이동이 3D 장면 자체를 바꿈",zoomed!=timed)
pid,fd=pty.fork()
if pid==0:
    os.environ["TERM"]="xterm-256color";os.execv(sys.executable,[sys.executable,CLI,target])
seen=b"";end=time.time()+10
while time.time()<end:
    if select.select([fd],[],[],.1)[0]:
        try:seen+=os.read(fd,65536)
        except OSError:break
    if b"CODESTRATA" in seen:break
os.write(fd,b"hlud+-jk\t\r0q");deadline=time.time()+8;got=0
while time.time()<deadline:
    if select.select([fd],[],[],.05)[0]:
        try:seen+=os.read(fd,65536)
        except OSError:pass
    got,_=os.waitpid(pid,os.WNOHANG)
    if got:break
check("curses 3D 조작키 뒤 q 종료",bool(got),f"화면={len(seen)} bytes")
if not got:os.kill(pid,9);os.waitpid(pid,0)
print("전체:","PASS" if all(checks) else "FAIL");raise SystemExit(0 if all(checks) else 1)
