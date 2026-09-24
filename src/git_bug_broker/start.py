"""Start, stop or inspect the git-bug web UI that owns one repository's store.

    git-bug-broker-start <repo> [--port 38420]      start (idempotent: reuses a live one)
    git-bug-broker-start <repo> --status            print the endpoint, exit 1 if down
    git-bug-broker-start <repo> --stop              stop it gracefully (Ctrl+Break to its console)

Writes <repo>/.git/git-bug-broker/endpoint.json ({url, port, pid, repo, started})
and logs to webui.log beside it. Never passes --read-only, and never --open unless
--open is given. Only stops a web UI it recorded itself.
"""
import argparse
import datetime
import json
import os
import subprocess
import sys
import time
import urllib.request

from . import client as C


def alive(url):
    try:
        req = urllib.request.Request(url.rstrip("/") + "/graphql",
                                     json.dumps({"query": "{repository{name}}"}).encode(),
                                     {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=3) as r:
            return "data" in json.load(r)
    except Exception:
        return False


def start(repo, port, open_browser):
    sd = C.state_dir(repo)
    os.makedirs(sd, exist_ok=True)
    ep = C.read_endpoint(repo)
    if ep and alive(ep["url"]):
        print(json.dumps({**ep, "reused": True}))
        return 0
    args = ["git-bug", "webui", "--port", str(port), "--open" if open_browser else "--no-open",
            "--log-errors"]
    log = open(os.path.join(sd, "webui.log"), "ab")
    kw = {}
    if os.name == "nt":
        # A hidden console of its own, so --stop can send it Ctrl+Break.
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0
        kw = {"creationflags": subprocess.CREATE_NEW_CONSOLE, "startupinfo": si}
    else:
        kw = {"start_new_session": True}
    p = subprocess.Popen(args, cwd=repo, stdout=log, stderr=log, stdin=subprocess.DEVNULL, **kw)
    url = f"http://127.0.0.1:{port}"
    for _ in range(100):
        if alive(url):
            break
        if p.poll() is not None:
            print(f"git-bug webui exited with {p.returncode}; see {sd}/webui.log", file=sys.stderr)
            return 1
        time.sleep(0.1)
    else:
        print("web UI did not answer within 10s", file=sys.stderr)
        return 1
    ep = {"url": url, "port": port, "pid": p.pid, "repo": os.path.abspath(repo),
          "started": datetime.datetime.now().isoformat(timespec="seconds")}
    with open(os.path.join(sd, "endpoint.json"), "w", encoding="utf-8") as f:
        json.dump(ep, f, indent=1)
    print(json.dumps(ep))
    return 0


def _ctrl_c_windows(pid):
    # Go delivers Ctrl+Break as os.Interrupt, so git-bug shuts down and closes
    # its index. Ctrl+C would be ignored by a process started on a new console.
    # The helper attaches to that console and dies of the same event, so its exit
    # code means nothing; the caller checks the endpoint instead.
    code = ("import ctypes;k=ctypes.windll.kernel32;k.FreeConsole();"
            f"k.AttachConsole({pid}) and k.GenerateConsoleCtrlEvent(1,0)")
    subprocess.run([sys.executable, "-c", code], creationflags=subprocess.CREATE_NO_WINDOW)
    return True


def stop(repo):
    ep = C.read_endpoint(repo)
    if not ep:
        print("no recorded web UI for this repository")
        return 0
    pid = ep["pid"]
    if os.name == "nt":
        sent = _ctrl_c_windows(pid)
    else:
        import signal
        try:
            os.kill(pid, signal.SIGINT)
            sent = True
        except ProcessLookupError:
            sent = False
    for _ in range(100):
        if not alive(ep["url"]):
            break
        time.sleep(0.1)
    if alive(ep["url"]):
        print(f"web UI pid {pid} still answering after Ctrl+Break (sent={sent}); not killing it",
              file=sys.stderr)
        return 1
    os.remove(os.path.join(C.state_dir(repo), "endpoint.json"))
    print(json.dumps({"stopped": pid, "graceful": sent}))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("repo")
    ap.add_argument("--port", type=int, default=38420)
    ap.add_argument("--open", action="store_true")
    ap.add_argument("--stop", action="store_true")
    ap.add_argument("--status", action="store_true")
    a = ap.parse_args()
    if a.stop:
        return stop(a.repo)
    if a.status:
        ep = C.read_endpoint(a.repo)
        up = bool(ep and alive(ep["url"]))
        print(json.dumps({**(ep or {}), "alive": up}))
        return 0 if up else 1
    return start(a.repo, a.port, a.open)


if __name__ == "__main__":
    sys.exit(main())
