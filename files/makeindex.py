#!/usr/bin/env python3
"""out 디렉터리의 산출물로 index.html 을 만든다 — 주소에 파일명을 안 치게.

사용: makeindex.py <out디렉터리>
"""
import json, pathlib, sys, time, html

out = pathlib.Path(sys.argv[1])
rows = []
for j in sorted(out.glob("*.json")):
    try:
        d = json.loads(j.read_text(encoding="utf-8"))
    except Exception:
        continue
    h = j.with_suffix(".html")
    if not h.exists():
        continue
    cs = d.get("commits") or []
    rows.append({
        "name": d.get("repo") or j.stem, "href": h.name,
        "commits": len(cs), "files": len(d.get("files") or []),
        "events": len(d.get("events") or []),
        "deps": len(d.get("deps") or []),
        "lanes": d.get("lanes") or 1,
        "t0": cs[0]["t"] if cs else 0, "t1": cs[-1]["t"] if cs else 0,
        "built": d.get("built") or int(h.stat().st_mtime),
        "size": h.stat().st_size,
    })
rows.sort(key=lambda r: -r["built"])
day = lambda t: time.strftime("%Y-%m-%d", time.localtime(t)) if t else "–"
minute = lambda t: time.strftime("%m-%d %H:%M", time.localtime(t))

cards = "\n".join(f'''    <a class="card" href="{html.escape(r['href'])}">
      <span class="name">{html.escape(r['name'])}</span>
      <span class="nums">
        <b>{r['commits']}</b> commits · <b>{r['files']}</b> files ·
        <b>{r['events']}</b> changes · <b>{r['lanes']}</b> lanes{
        f" · <b>{r['deps']}</b> deps" if r['deps'] else ""}
      </span>
      <span class="span">{day(r['t0'])} → {day(r['t1'])}</span>
      <span class="built">생성 {minute(r['built'])} · {r['size']//1024}KB</span>
    </a>''' for r in rows)

(out / "index.html").write_text(f'''<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Commit Strata</title>
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
:root{{--ground:#0D121B;--panel:#151B27;--line:#2C3648;--ink:#DCE3EF;
      --dim:#9DA8BE;--mute:#8592A8;--accent:#FFC272}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--ground);color:var(--ink);
     font-family:Archivo,'Helvetica Neue',Arial,sans-serif;
     display:flex;justify-content:center;padding:56px 24px 80px}}
main{{width:100%;max-width:720px}}
h1{{margin:0;font-size:19px;font-weight:700;letter-spacing:-.01em}}
.sub{{margin:8px 0 30px;font-size:12.5px;color:var(--mute);line-height:1.6}}
.grid{{display:flex;flex-direction:column;gap:1px;background:var(--line);
      border:1px solid var(--line);border-radius:6px;overflow:hidden}}
.card{{background:var(--panel);padding:16px 20px;text-decoration:none;color:inherit;
      display:grid;gap:5px;transition:background .14s}}
.card:hover{{background:#1A2231}}
.card:focus-visible{{outline:2px solid var(--accent);outline-offset:-2px}}
.name{{font-family:'IBM Plex Mono',monospace;font-size:14px;color:var(--accent);font-weight:500}}
.nums{{font-size:11.5px;color:var(--dim);font-variant-numeric:tabular-nums}}
.nums b{{color:var(--ink);font-weight:600}}
.span,.built{{font-family:'IBM Plex Mono',monospace;font-size:10.5px;color:var(--mute)}}
.empty{{background:var(--panel);padding:22px 20px;font-size:12.5px;color:var(--mute)}}
code{{font-family:'IBM Plex Mono',monospace;background:#1A2231;padding:2px 6px;
     border-radius:3px;color:var(--dim)}}
</style></head><body><main>
  <h1>Commit Strata</h1>
  <p class="sub">레포를 구조 × 시간 3D 지층으로 세운 것. 새로 만들려면
    <code>codestrata &lt;레포경로&gt;</code></p>
  <div class="grid">
{cards if rows else '    <div class="empty">아직 만든 것이 없습니다.</div>'}
  </div>
</main></body></html>''', encoding="utf-8")
print(f"[codestrata] index.html  ({len(rows)}개)")
