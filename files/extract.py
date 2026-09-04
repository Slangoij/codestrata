#!/usr/bin/env python3
"""git 히스토리 -> 3D 시각화용 JSON.

축: X·Y = 파일 구조/co-change, Z = 시간(커밋). 커밋 DAG 는 레인으로 펼친다.
개인정보 금지: 작성자 이름·이메일은 뽑지 않는다.
"""
import json, subprocess, sys, os, re, time, collections

REPO = sys.argv[1] if len(sys.argv) > 1 else "."
OUT  = sys.argv[2] if len(sys.argv) > 2 else "data.json"

SEP_C, SEP_F = "\x01", "\x1f"

def git(*args):
    return subprocess.run(["git", "-C", REPO, *args],
                          capture_output=True, text=True, check=True).stdout

def _refs(raw):
    """'HEAD -> main, origin/main, tag: v1' -> ['main','origin/main','tag: v1'].
    'HEAD ->' 를 통째로 버리면 main 이 사라진다."""
    out = []
    for r in (x.strip() for x in raw.split(",")):
        if not r or r == "HEAD":
            continue
        out.append(r[len("HEAD ->"):].strip() if r.startswith("HEAD ->") else r)
    return out

RE_BRACE = re.compile(r"^(.*?)\{(.*?) => (.*?)\}(.*)$")

def norm_path(p):
    """rename 표기를 새 경로로 정규화: 'a/{x => y}/c' , 'old => new'."""
    m = RE_BRACE.match(p)
    if m:
        pre, _old, new, post = m.groups()
        return (pre + new + post).replace("//", "/")
    if " => " in p:
        return p.split(" => ", 1)[1]
    return p

# --all: 브랜치 커밋까지. --date-order: 시간축과 어긋나지 않게.
raw = git("log", "--all", "--reverse", "--date-order", "--numstat",
          f"--pretty=format:{SEP_C}%H{SEP_F}%P{SEP_F}%at{SEP_F}%D{SEP_F}%s")

commits, events = [], []
for block in raw.split(SEP_C):
    if not block.strip():
        continue
    head, *rest = block.split("\n")
    sha, parents, ts, refs, subject = head.split(SEP_F, 4)
    files = []
    for line in rest:
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        add, dele, path = parts
        if add == "-" or dele == "-":      # 바이너리
            continue
        files.append((norm_path(path), int(add), int(dele)))
    ci = len(commits)
    commits.append({
        "sha": sha, "t": int(ts), "subject": subject[:120],
        "p": parents.split() if parents.strip() else [],
        # HEAD 표기·원격 중복은 걷어낸다
        "refs": _refs(refs),
    })
    for path, add, dele in files:
        events.append({"c": ci, "f": path, "a": add, "d": dele})

idx_of_sha = {c["sha"]: i for i, c in enumerate(commits)}

# ── 커밋 DAG 레인 ────────────────────────────────────────────
# 오름차순으로 훑으며 첫 자식은 부모 레인을 잇고, 갈라지는 자식은 새 레인.
children = collections.defaultdict(list)
for c in commits:
    for p in c["p"]:
        if p in idx_of_sha:
            children[p].append(c["sha"])

lane_of, free, nxt = {}, [], 0
def alloc():
    global nxt
    if free:
        return free.pop(0)
    nxt += 1
    return nxt - 1

for c in commits:
    sha = c["sha"]
    if sha not in lane_of:
        lane_of[sha] = alloc()
    l = lane_of[sha]
    kids = sorted(children[sha], key=lambda s: idx_of_sha[s])
    for i, k in enumerate(kids):
        if k in lane_of:
            continue
        lane_of[k] = l if i == 0 else alloc()
    if not kids and l not in free:          # 팁이면 레인을 놓아 준다
        free.append(l)

for c in commits:
    c["lane"] = lane_of[c["sha"]]
    c["merge"] = len(c["p"]) > 1
    c["p"] = [idx_of_sha[p] for p in c["p"] if p in idx_of_sha]
    c["sha"] = c["sha"][:7]

# ── 파일 노드 ────────────────────────────────────────────────
alive = set(git("ls-files").split("\n"))
per_file = collections.defaultdict(lambda: {"changes": 0, "add": 0, "dele": 0,
                                            "first": None, "last": None})
for e in events:
    s = per_file[e["f"]]
    s["changes"] += 1
    s["add"] += e["a"]; s["dele"] += e["d"]
    if s["first"] is None:
        s["first"] = e["c"]
    s["last"] = e["c"]

files, idx = [], {}
for path, s in sorted(per_file.items()):
    idx[path] = len(files)
    files.append({
        "path": path,
        "dir": os.path.dirname(path) or ".",
        "ext": (os.path.splitext(path)[1] or "").lstrip(".").lower(),
        "changes": s["changes"], "add": s["add"], "dele": s["dele"],
        "first": s["first"], "last": s["last"],
        "alive": path in alive,
    })
for e in events:
    e["f"] = idx[e["f"]]

# ── co-change 엣지 ───────────────────────────────────────────
by_commit = collections.defaultdict(list)
for e in events:
    by_commit[e["c"]].append(e["f"])
pair = collections.Counter()
for ci, fs in by_commit.items():
    fs = sorted(set(fs))
    if len(fs) > 25:
        continue
    for i in range(len(fs)):
        for j in range(i + 1, len(fs)):
            pair[(fs[i], fs[j])] += 1
links = [{"s": a, "t": b, "w": w} for (a, b), w in pair.items() if w >= 2]

# ── graphify 의존 엣지 -> 파일 단위로 접는다 ──────────────────
# graph.json 은 networkx node-link 이고 엣지가 **심볼 단위**라, 양끝 심볼의
# source_file 로 접어 파일 쌍으로 만든다. 파일 내부 구조(contains/method/defines)는
# 같은 파일로 접히므로 의존이 아니다 — 제외한다.
DEP_RELATIONS = {"imports", "imports_from", "calls", "indirect_call",
                 "inherits", "uses", "references"}
deps, dep_kinds, graph_meta = [], {}, None
gpath = os.path.join(REPO, "graphify-out", "graph.json")
if os.path.exists(gpath):
    with open(gpath) as fh:
        G = json.load(fh)
    sym_file = {n["id"]: n.get("source_file") for n in G.get("nodes", [])}
    pair = collections.Counter()
    kinds = collections.defaultdict(collections.Counter)
    skipped = collections.Counter()
    for l in G.get("links", []):
        rel = l.get("relation")
        if rel not in DEP_RELATIONS:
            skipped[rel] += 1
            continue
        a, b = sym_file.get(l.get("source")), sym_file.get(l.get("target"))
        if not a or not b or a == b:
            continue
        if a not in idx or b not in idx:      # git 이 추적하지 않는 파일
            continue
        i, j = sorted((idx[a], idx[b]))
        pair[(i, j)] += 1
        kinds[(i, j)][rel] += 1
    deps = [{"s": a, "t": b, "w": w,
             "k": kinds[(a, b)].most_common(1)[0][0]}
            for (a, b), w in pair.items()]
    graph_meta = {"built_at_commit": (G.get("built_at_commit") or "")[:7],
                  "nodes": len(G.get("nodes", [])), "links": len(G.get("links", [])),
                  "relations_used": sorted(DEP_RELATIONS),
                  "skipped": dict(skipped)}
    print(f"  graphify: 심볼 엣지 {len(G.get('links', []))} -> 파일 의존 {len(deps)} 쌍")

data = {"repo": os.path.basename(os.path.abspath(REPO)),
        "commits": commits, "files": files, "events": events, "links": links,
        "deps": deps, "graph": graph_meta, "lanes": nxt,
        "built": int(time.time())}
with open(OUT, "w") as fh:
    json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))

print(f"repo={data['repo']}  commits={len(commits)}  files={len(files)}  "
      f"events={len(events)}  links={len(links)}  lanes={nxt}  "
      f"merges={sum(1 for c in commits if c['merge'])}  "
      f"refs={sum(1 for c in commits if c['refs'])}  deps={len(deps)}  "
      f"bytes={os.path.getsize(OUT)}")
