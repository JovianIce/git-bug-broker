"""Render a git-bug store as one static HTML page.

    python tools/view.py [--out PATH] [--json PATH] [--open]

git-bug's web UI holds the search index open while it runs, and the index sits
in a BoltDB file (.git/git-bug/indexes/bugs/root.bolt) under an exclusive lock,
so every other git-bug command waits for the web UI to close. This script reads
the store once through the CLI and writes a self-contained page that holds no
lock. Rerun it to refresh.

Output goes inside .git by default so it is never committed. --json also writes
the entries as JSON Lines, which agents read instead of calling git-bug.
"""

import argparse
import datetime
import html
import json
import os
import subprocess
import sys
import webbrowser

GB = "git-bug.exe" if os.name == "nt" else "git-bug"


def git_bug(*args):
    out = subprocess.run([GB, *args], capture_output=True, text=True, encoding="utf-8")
    if out.returncode != 0:
        sys.exit(f"git-bug {' '.join(args)} failed: {out.stderr.strip()}")
    return out.stdout


def load():
    listing = json.loads(git_bug("bug", "-f", "json"))
    entries = []
    for b in listing:
        # The listing carries no comment text, so each entry is read in full.
        full = json.loads(git_bug("bug", "show", b["id"], "--format", "json"))
        labels = [l if isinstance(l, str) else l.get("name") for l in (full.get("labels") or [])]
        comments = [c.get("message", "") for c in (full.get("comments") or [])]
        entries.append({
            "id": full["human_id"],
            "status": full["status"],
            "title": full["title"],
            "labels": labels,
            "body": comments[0] if comments else "",
            "comments": comments[1:],
        })
    entries.sort(key=lambda e: (e["status"] != "open", e["title"].lower()))
    return entries


PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>git-bug issues</title><style>
:root{--bg:#fafaf7;--fg:#1d1d1b;--mut:#6b6b66;--line:#e2e1da;--card:#fff;--acc:#3553b8;--warn:#a15c00;--code:#f0efe9}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#161615;--fg:#e8e7e2;--mut:#9a9a93;--line:#2c2c2a;--card:#1e1e1c;--acc:#8fa4ff;--warn:#f0b35a;--code:#262624}}
body{background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,sans-serif;margin:0 auto;max-width:1000px;padding:20px 16px}
h1{font-size:21px;margin:0}.sub{color:var(--mut);margin:2px 0 14px}
.bar{display:flex;flex-wrap:wrap;gap:8px;position:sticky;top:0;background:var(--bg);padding:8px 0;border-bottom:1px solid var(--line);z-index:1}
.bar select,.bar input{font:inherit;background:var(--card);color:var(--fg);border:1px solid var(--line);border-radius:6px;padding:4px 8px}
.bar input[type=search]{flex:1;min-width:160px}.count{color:var(--mut);align-self:center}
details{background:var(--card);border:1px solid var(--line);border-radius:6px;margin:6px 0;padding:6px 10px}
summary{cursor:pointer}summary .id{color:var(--acc);font:13px ui-monospace,monospace;margin-right:6px}
.closed summary{color:var(--mut)}
.lab{display:inline-block;font:11px ui-monospace,monospace;border:1px solid var(--line);border-radius:4px;padding:0 5px;margin:0 2px;color:var(--mut)}
.lab.g{color:var(--warn);border-color:var(--warn)}
.txt{white-space:pre-wrap;overflow-wrap:anywhere;margin:8px 0}.cm{border-top:1px dashed var(--line);padding-top:6px;color:var(--fg)}
code{background:var(--code);padding:0 3px;border-radius:3px;font-size:13px}
</style></head><body>
<h1>git-bug issues</h1><div class="sub">Built __BUILT__ from git-bug. Static: rerun <code>python tools/view.py</code> to refresh.</div>
<div class="bar">
<select id="st"><option value="open">open</option><option value="closed">closed</option><option value="">all</option></select>
<select id="kind"><option value="">any kind</option></select>
<select id="area"><option value="">any area</option></select>
<select id="src"><option value="">any source</option></select>
<label class="count"><input type="checkbox" id="blocks"> blocks</label>
<label class="count"><input type="checkbox" id="prov"> needs-provenance</label>
<input type="search" id="q" placeholder="search titles and text">
<span class="count" id="n"></span></div>
<div id="list"></div>
<script>
const D=__DATA__;
const $=id=>document.getElementById(id);
const esc=s=>s.replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const fmt=s=>esc(s).replace(/`([^`]+)`/g,'<code>$1</code>').replace(/\\*\\*([^*]+)\\*\\*/g,'<b>$1</b>');
function fill(sel,prefix){const v=[...new Set(D.flatMap(e=>e.labels).filter(l=>l.startsWith(prefix)))].sort();
 for(const l of v){const o=document.createElement('option');o.value=l;o.textContent=l.slice(prefix.length);sel.appendChild(o)}}
fill($('kind'),'kind/');fill($('area'),'area/');fill($('src'),'source/');
function draw(){
 const st=$('st').value,k=$('kind').value,a=$('area').value,s=$('src').value,q=$('q').value.toLowerCase();
 const rows=D.filter(e=>(!st||e.status===st)&&(!k||e.labels.includes(k))&&(!a||e.labels.includes(a))&&(!s||e.labels.includes(s))
  &&(!$('blocks').checked||e.labels.includes('blocks'))&&(!$('prov').checked||e.labels.includes('needs-provenance'))
  &&(!q||(e.title+' '+e.body+' '+e.comments.join(' ')+' '+e.id).toLowerCase().includes(q)));
 $('n').textContent=rows.length+' of '+D.length;
 $('list').innerHTML=rows.map(e=>`<details class="${e.status}"><summary><span class="id">${e.id}</span>${fmt(e.title)}
  ${e.labels.map(l=>`<span class="lab${l==='blocks'?' g':''}">${esc(l)}</span>`).join('')}</summary>
  <div class="txt">${fmt(e.body)}</div>${e.comments.map(c=>`<div class="txt cm">${fmt(c)}</div>`).join('')}</details>`).join('');
}
for(const id of ['st','kind','area','src','blocks','prov'])$(id).addEventListener('change',draw);
$('q').addEventListener('input',draw);draw();
</script></body></html>"""


def main():
    root = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True).stdout.strip()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=os.path.join(root, ".git", "git-bug-view.html"))
    ap.add_argument("--json", default=os.path.join(root, ".git", "git-bug-snapshot.jsonl"),
                    help="also write the entries as JSON Lines for agents; empty to skip")
    ap.add_argument("--open", action="store_true", help="open the page in the default browser")
    args = ap.parse_args()

    entries = load()
    built = datetime.date.today().isoformat()
    data = json.dumps(entries, ensure_ascii=False).replace("</", "<\\/")
    page = PAGE.replace("__DATA__", data).replace("__BUILT__", html.escape(built))
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(page)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            for e in entries:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
    n_open = sum(e["status"] == "open" for e in entries)
    print(f"{args.out}: {len(entries)} entries, {n_open} open")
    if args.json:
        print(f"{args.json}: snapshot for agents")
    if args.open:
        webbrowser.open("file:///" + os.path.abspath(args.out).replace(os.sep, "/"))


if __name__ == "__main__":
    main()
