#!/usr/bin/env python3
"""codestrata-cli — Chromium 없이 Braille 문자로 git 지층을 3D 렌더링한다."""
import argparse, curses, datetime as dt, json, math, os, shutil, subprocess, sys, unicodedata

OUT_DIR = os.path.expanduser("~/debug-captures/codebase-3d")
DOT = ((1, 8), (2, 16), (4, 32), (64, 128))

def git_root(path):
    r = subprocess.run(["git","-C",path,"rev-parse","--show-toplevel"],
                       capture_output=True,text=True)
    return r.stdout.strip() if r.returncode == 0 else None

def target_json(arg):
    if arg and arg.endswith((".json",".html")):
        return os.path.abspath(os.path.splitext(os.path.expanduser(arg))[0]+".json")
    candidate=os.path.expanduser(arg) if arg else os.getcwd()
    root=git_root(candidate) if os.path.isdir(candidate) else None
    if root:
        out=os.path.join(OUT_DIR,os.path.basename(root)+".json")
        head=subprocess.run(["git","-C",root,"log","-1","--format=%ct"],
                            capture_output=True,text=True).stdout.strip()
        if not os.path.exists(out) or (head.isdigit() and os.path.getmtime(out)<int(head)):
            print(f"[codestrata-cli] 데이터를 만듭니다: {root}",file=sys.stderr)
            if subprocess.run(["codestrata",root,"--no-serve"]).returncode:
                raise SystemExit(1)
        return out
    if arg and not os.path.isdir(candidate):
        return os.path.join(OUT_DIR,arg+".json")
    return None

def load_data(path):
    if path and not os.path.exists(path):
        raise SystemExit(f"[codestrata-cli] 데이터가 없습니다: {path}")
    if not path:
        found=sorted((os.path.join(OUT_DIR,n) for n in os.listdir(OUT_DIR)
                      if n.endswith(".json")),key=os.path.getmtime,reverse=True) \
              if os.path.isdir(OUT_DIR) else []
        if not found:
            raise SystemExit("[codestrata-cli] 데이터가 없습니다: 먼저 codestrata <레포> --no-serve")
        path=found[0]
    with open(path,encoding="utf-8") as f: return json.load(f),path

def display_width(text):
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)

def clip(text,width):
    if width<=0:return ""
    if display_width(text)<=width:return text
    out=[]; used=0
    for ch in text:
        n=2 if unicodedata.east_asian_width(ch) in "WF" else 1
        if used+n>width-1:break
        out.append(ch);used+=n
    return "".join(out)+"…"

class RNG:
    def __init__(self,seed=20260901):self.seed=seed
    def next(self):
        self.seed=self.seed*16807%2147483647
        return self.seed/2147483647

def file_layout(data):
    """웹판과 같은 결정적 force layout: 디렉터리 부채꼴 + co-change/deps 인력."""
    files,links,deps=data["files"],data.get("links",[]),data.get("deps",[])
    n=len(files); rng=RNG(); dirs=sorted({f["dir"] for f in files}) or ["."]
    angles={d:i/len(dirs)*math.tau for i,d in enumerate(dirs)}
    x=[];z=[]
    for f in files:
        a=angles[f["dir"]]+(rng.next()-.5)*.9; r=26+rng.next()*34
        x.append(math.cos(a)*r);z.append(math.sin(a)*r)
    maxw=max([l["w"] for l in links] or [1])
    # Python TUI 시작 시간을 제한하면서 구조 관계는 충분히 정착시키는 반복 수.
    iterations=90 if n<220 else 42
    for it in range(iterations):
        cool=1-it/iterations; fx=[0.0]*n;fz=[0.0]*n
        for i in range(n):
            for j in range(i+1,n):
                dx=x[i]-x[j];dz=z[i]-z[j];d2=dx*dx+dz*dz or .01
                if d2>9000:continue
                force=340/d2;dist=math.sqrt(d2);dx=dx/dist*force;dz=dz/dist*force
                fx[i]+=dx;fz[i]+=dz;fx[j]-=dx;fz[j]-=dz
        for edge,k0 in ((links,.012),(deps,.030)):
            for l in edge:
                a,b=l["s"],l["t"]; k=k0*((l.get("w",1)/maxw) if edge is links else 1)+(.004 if edge is links else 0)
                dx=(x[b]-x[a])*k;dz=(z[b]-z[a])*k
                fx[a]+=dx;fz[a]+=dz;fx[b]-=dx;fz[b]-=dz
        cent={}
        for i,f in enumerate(files):
            c=cent.setdefault(f["dir"],[0.,0.,0]);c[0]+=x[i];c[1]+=z[i];c[2]+=1
        for c in cent.values():c[0]/=c[2];c[1]/=c[2]
        for i,f in enumerate(files):
            c=cent[f["dir"]];fx[i]+=(c[0]-x[i])*.022-x[i]*.0018;fz[i]+=(c[1]-z[i])*.022-z[i]*.0018
            x[i]+=max(-4,min(4,fx[i]))*cool;z[i]+=max(-4,min(4,fz[i]))*cool
    outer=max([math.hypot(x[i],z[i]) for i in range(n)] or [1])
    lanes=max(1,data.get("lanes",1)); inner=max(21,(lanes-1)/2*min(9,46/lanes)+9)
    for i in range(n):
        r=math.hypot(x[i],z[i]) or 1e-6;k=(inner+r/outer*47)/r;x[i]*=k;z[i]*=k
    return list(zip(x,z)),inner,inner+47

class View:
    def __init__(self,data):
        self.data=data;self.commit=max(0,len(data["commits"])-1)
        self.theta=-.72;self.phi=1.14;self.dist=232.
        self.target=[0.,0.,0.];self.pinned=None
        self.positions,self.inner,self.outer=file_layout(data)
        self.by_commit=[[] for _ in data["commits"]]
        for e in data["events"]:
            if e["c"]<len(self.by_commit):self.by_commit[e["c"]].append(e)
    def move_commit(self,n):
        self.commit=max(0,min(len(self.data["commits"])-1,self.commit+n))
        self.pinned=None
    def reset(self):
        self.theta=-.72;self.phi=1.14;self.dist=max(232,self.outer*3);self.target=[0.,0.,0.]
    def cycle_file(self,back=False):
        fs=[e["f"] for e in self.by_commit[self.commit]]
        if not fs:return
        i=fs.index(self.pinned) if self.pinned in fs else (-1 if not back else 0)
        self.pinned=fs[(i+(-1 if back else 1))%len(fs)]
    def focus(self):
        y=self.y_of(self.commit)
        if self.pinned is None:
            lanes=max(1,self.data.get("lanes",1));lw=min(9,46/lanes)
            self.target=[(self.data["commits"][self.commit].get("lane",0)-(lanes-1)/2)*lw,y,0]
        else:
            x,z=self.positions[self.pinned];self.target=[x,y,z]
    def y_of(self,i):
        n=len(self.data["commits"]);return (-48 if n<2 else i/(n-1)*96-48)

class Canvas:
    """한 터미널 셀을 2×4 Braille 점으로 쓰는 깊이 버퍼."""
    def __init__(self,cols,rows):
        self.cols=cols;self.rows=rows;self.w=cols*2;self.h=rows*4
        self.bits=[[0]*cols for _ in range(rows)]
        self.depth=[[1e9]*cols for _ in range(rows)]
        self.style=[[0]*cols for _ in range(rows)]
    def plot(self,x,y,depth,style=2,radius=0):
        for yy in range(y-radius,y+radius+1):
            for xx in range(x-radius,x+radius+1):
                if (xx-x)**2+(yy-y)**2>radius*radius+1:continue
                if not(0<=xx<self.w and 0<=yy<self.h):continue
                cy,cx=yy//4,xx//2
                self.bits[cy][cx]|=DOT[yy%4][xx%2]
                if depth<self.depth[cy][cx]:self.depth[cy][cx]=depth;self.style[cy][cx]=style
    def line(self,a,b,style=2):
        if not a or not b:return
        x0,y0,d0=a;x1,y1,d1=b;n=max(1,int(max(abs(x1-x0),abs(y1-y0))))
        for i in range(n+1):
            t=i/n;self.plot(round(x0+(x1-x0)*t),round(y0+(y1-y0)*t),d0+(d1-d0)*t,style)
    def rows_out(self):
        return [[(chr(0x2800+b) if b else " ",self.style[y][x]) for x,b in enumerate(row)]
                for y,row in enumerate(self.bits)]

def projector(view,canvas):
    sp,cp=math.sin(view.phi),math.cos(view.phi);ct,st=math.cos(view.theta),math.sin(view.theta)
    direction=(sp*ct,cp,sp*st);right=(st,0,-ct);up=(-cp*ct,sp,-cp*st)
    cam=tuple(view.target[i]+view.dist*direction[i] for i in range(3))
    aspect=canvas.w/canvas.h;tan=math.tan(math.radians(42)/2)
    def project(p):
        rel=tuple(p[i]-cam[i] for i in range(3))
        depth=-sum(rel[i]*direction[i] for i in range(3))
        if depth<=1:return None
        xx=sum(rel[i]*right[i] for i in range(3))/(depth*tan*aspect)
        yy=sum(rel[i]*up[i] for i in range(3))/(depth*tan)
        if abs(xx)>1.3 or abs(yy)>1.3:return None
        return ((xx*.5+.5)*(canvas.w-1),(-yy*.5+.5)*(canvas.h-1),depth)
    return project

def scene(view,cols,rows):
    d=view.data;c=Canvas(cols,rows);p=projector(view,c);floor=-48
    # 바닥 원과 방사선: 회전하면 타원이 되어 깊이가 바로 읽힌다.
    for radius in (view.inner,view.inner+(view.outer-view.inner)*.5,view.outer):
        prev=None
        for i in range(73):
            a=i/72*math.tau;now=p((math.cos(a)*radius,floor,math.sin(a)*radius))
            c.line(prev,now,1);prev=now
    for i in range(0,24,3):
        a=i/24*math.tau
        c.line(p((math.cos(a)*view.inner,floor,math.sin(a)*view.inner)),
               p((math.cos(a)*view.outer,floor,math.sin(a)*view.outer)),1)
    # 바닥 관계: co-change는 흐리게, 실제 code dependency는 밝은 아치.
    for l in d.get("links",[]):
        x0,z0=view.positions[l["s"]];x1,z1=view.positions[l["t"]]
        c.line(p((x0,floor,z0)),p((x1,floor,z1)),1)
    for dep in d.get("deps",[]):
        x0,z0=view.positions[dep["s"]];x1,z1=view.positions[dep["t"]]
        prev=None;span=math.hypot(x1-x0,z1-z0);lift=min(26,span*.3)
        for i in range(9):
            t=i/8;now=p((x0+(x1-x0)*t,floor+math.sin(t*math.pi)*lift,z0+(z1-z0)*t))
            c.line(prev,now,5);prev=now
    # 파일 기둥.
    for i,f in enumerate(d["files"]):
        if f.get("first") is None or f["first"]>view.commit:continue
        x,z=view.positions[i];top=view.y_of(min(f["last"],view.commit))
        c.line(p((x,view.y_of(f["first"]),z)),p((x,top,z)),2)
        q=p((x,floor,z))
        if q:c.plot(round(q[0]),round(q[1]),q[2],2,1 if i==view.pinned else 0)
    # 변경 구슬.
    for e in d["events"]:
        if e["c"]>view.commit:continue
        x,z=view.positions[e["f"]];q=p((x,view.y_of(e["c"]),z))
        if q:
            churn=e.get("a",0)+e.get("d",0);r=1 if churn>=80 else 0
            style=4 if e["c"]==view.commit or e["f"]==view.pinned else 3
            c.plot(round(q[0]),round(q[1]),q[2],style,r)
    # 중앙 커밋 DAG.
    lanes=max(1,d.get("lanes",1));lw=min(9,46/lanes)
    def commit_pos(i):
        return ((d["commits"][i].get("lane",0)-(lanes-1)/2)*lw,view.y_of(i),0)
    for i,commit in enumerate(d["commits"][:view.commit+1]):
        here=commit_pos(i)
        for parent in commit.get("p",[]):
            if parent<=view.commit:c.line(p(commit_pos(parent)),p(here),6)
        q=p(here)
        if q:c.plot(round(q[0]),round(q[1]),q[2],4 if i==view.commit else 6,
                    1 if commit.get("merge") or i==view.commit else 0)
    # 선택한 커밋에서 그 층의 변경 파일로 다리.
    origin=p(commit_pos(view.commit))
    for e in view.by_commit[view.commit]:
        x,z=view.positions[e["f"]];c.line(origin,p((x,view.y_of(view.commit),z)),4)
    return c.rows_out()

def layout(view,width,height,rendered=None):
    d=view.data;c=d["commits"][view.commit]
    title=clip(f"◆ CODESTRATA 3D / {d.get('repo','?')}   {len(d['commits'])} commits · {len(d['files'])} files · {len(d.get('links',[]))} co-change · {len(d.get('deps',[]))} deps",width)
    stamp=dt.datetime.fromtimestamp(c["t"]).strftime("%Y-%m-%d %H:%M")
    info=clip(f"◆ {c['sha']}  {stamp}   θ{view.theta:+.2f} φ{view.phi:.2f} zoom {view.dist:.0f}   {c['subject']}",width)
    canvas_rows=max(5,height-4)
    rendered=rendered if rendered is not None else scene(view,width,canvas_rows)
    art=["".join(ch for ch,_ in row) for row in rendered]
    pin=("  FILE "+d["files"][view.pinned]["path"]) if view.pinned is not None else ""
    help_=clip("h/l 좌우회전  u/d 상하회전  +/- 줌  j/k 시간  Tab 파일  Enter 중심  0 원점  q 종료"+pin,width)
    return [(title,1),(info,4)]+[(line,0) for line in art]+[(help_,5)]

ANSI={0:"",1:"\x1b[1;35m",2:"\x1b[36m",3:"\x1b[34m",4:"\x1b[1;33m",5:"\x1b[32m",6:"\x1b[37m"}
def print_plain(view,width,height):
    color=sys.stdout.isatty() and os.environ.get("NO_COLOR") is None
    for text,style in layout(view,width,height):
        print(ANSI[style]+text+"\x1b[0m" if color and style else text)

def run_curses(screen,view):
    curses.curs_set(0);curses.use_default_colors()
    colors=(curses.COLOR_MAGENTA,curses.COLOR_BLUE,curses.COLOR_CYAN,curses.COLOR_YELLOW,
            curses.COLOR_GREEN,curses.COLOR_WHITE)
    for i,fg in enumerate(colors,1):curses.init_pair(i,fg,-1)
    while True:
        screen.erase();height,width=screen.getmaxyx()
        rendered=scene(view,width,max(5,height-4))
        rows=layout(view,width,height,rendered)
        for y,(text,style) in enumerate(rows):
            if y in (0,1,len(rows)-1):
                try:screen.addnstr(y,0,text,max(1,width-1),curses.color_pair(style)|(curses.A_BOLD if y<2 else 0))
                except curses.error:pass
            else:
                cells=rendered[y-2]
                for x,(ch,st) in enumerate(cells[:max(1,width-1)]):
                    try:screen.addch(y,x,ch,curses.color_pair(st) if st else 0)
                    except curses.error:pass
        screen.refresh();key=screen.getch()
        if key in (ord("q"),3,17):return
        if key in (ord("h"),curses.KEY_LEFT):view.theta-=.12
        elif key in (ord("l"),curses.KEY_RIGHT):view.theta+=.12
        elif key==ord("u"):view.phi=max(.15,view.phi-.10)
        elif key==ord("d"):view.phi=min(math.pi-.15,view.phi+.10)
        elif key in (ord("+"),ord("="),curses.KEY_UP):view.dist=max(48,view.dist*.88)
        elif key in (ord("-"),ord("_"),curses.KEY_DOWN):view.dist=min(620,view.dist*1.12)
        elif key==ord("j"):view.move_commit(-1)
        elif key==ord("k"):view.move_commit(1)
        elif key in (9,curses.KEY_BTAB):view.cycle_file(key==curses.KEY_BTAB)
        elif key in (10,13,curses.KEY_ENTER):view.focus()
        elif key==ord("0"):view.reset()

def main(argv=None):
    p=argparse.ArgumentParser(description="Chromium 없는 Braille 문자 3D codestrata")
    p.add_argument("target",nargs="?");p.add_argument("--plain",action="store_true")
    p.add_argument("--width",type=int);p.add_argument("--height",type=int)
    a=p.parse_args(argv);data,_=load_data(target_json(a.target));view=View(data)
    if a.plain or not(sys.stdin.isatty() and sys.stdout.isatty()):
        size=shutil.get_terminal_size((100,30));print_plain(view,a.width or size.columns,a.height or size.lines)
    else:
        os.environ.setdefault("ESCDELAY","25");curses.wrapper(run_curses,view)
if __name__=="__main__":main()
