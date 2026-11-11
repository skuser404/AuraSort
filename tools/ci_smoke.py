#!/usr/bin/env python3
"""Install test: start an installed AuraSort in a brand-new home folder, set a PIN through the API, scan a small
fixture folder and require more than 0 files. Exactly the "it works on my PC but finds 0 files on my friend's" check.

    python tools/ci_smoke.py --app <folder with server.py> [--python <interpreter>] [--port 8799]

Uses only the standard library; never touches the real home folder (a temp one is used)."""
import argparse
import json
import os
import re
import shutil
import subprocess  # nosec B404  # fixed argument list: our own server.py
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

PIN = "4826"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", required=True)
    ap.add_argument("--python", default=sys.executable)
    ap.add_argument("--port", type=int, default=8799)
    a = ap.parse_args()
    tmp = Path(tempfile.mkdtemp(prefix="aurasort-smoke-"))
    home = tmp / "Test User Ünï"            # a space and non-English letters, like many real user names
    docs = home / "Documents" / "Tax 2025"
    docs.mkdir(parents=True)
    for name, data in (("résumé.pdf", b"%PDF-1.4\n"), ("photo.jpg", b"\xff\xd8\xff\xe0"), ("notes.txt", b"hello"), ("song.mp3", b"ID3")):
        (docs / name).write_bytes(data)
    (home / "Downloads").mkdir()
    (home / "Downloads" / "setup.zip").write_bytes(b"PK\x03\x04")
    env = dict(os.environ, HOME=str(home), USERPROFILE=str(home), AURASORT_TEST_TRASH_DIR=str(tmp / "bin"), PYTHONIOENCODING="utf-8")
    proc = subprocess.Popen([a.python, "server.py", "--no-browser", "--port", str(a.port)], cwd=a.app, env=env,  # nosec B603
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{a.port}"
    ok = False
    try:
        html = ""
        for _ in range(80):
            try:
                with urllib.request.urlopen(base + "/", timeout=2) as r:  # nosec B310  # loopback only
                    html = r.read().decode()
                break
            except OSError:
                time.sleep(0.25)
        token = re.search(r'name="app-token" content="([^"]+)"', html).group(1)

        def call(path, body=None):
            req = urllib.request.Request(base + "/api/" + path, data=json.dumps(body).encode() if body is not None else None,
                                         headers={"X-AuraSort-Token": token, "Content-Type": "application/json", "Host": f"127.0.0.1:{a.port}"})
            with urllib.request.urlopen(req, timeout=30) as r:  # nosec B310  # loopback only
                return json.loads(r.read())
        info = call("info")
        print("info:", info["app"], info["version"], info["os_name"], "python", info["python"], "locked" if info["locked"] else "")
        call("pin/set", {"pin": PIN})
        info = call("info")
        print("quick folders:", [(q["name"], q["exists"]) for q in info["quick"]])
        call("scan/start", {"mode": "deep", "roots": [str(home / "Documents"), str(home / "Downloads")]})
        for _ in range(300):
            s = call("scan/status")
            if s["state"] not in ("running", "paused"):
                break
            time.sleep(0.1)
        print("scan:", s["state"], "found", s.get("found"), "skipped", s.get("skipped"), "explain", s.get("explain"))
        summary = call("summary")
        print("summary total:", summary["total"], "consistent:", summary["consistent"])
        ok = s["state"] == "done" and s.get("found", 0) == 5 and summary["total"] == 5 and summary["consistent"]
        call("scan/start", {"mode": "quick", "roots": []})
        for _ in range(300):
            s = call("scan/status")
            if s["state"] not in ("running", "paused"):
                break
            time.sleep(0.1)
        print("quick scan:", s["state"], "found", s.get("found"))
        ok = ok and s.get("found", 0) >= 5
    finally:
        proc.terminate()
        try:
            out = proc.communicate(timeout=10)[0].decode("utf-8", "replace")
        except subprocess.TimeoutExpired:
            proc.kill()
            out = ""
        if not ok:
            print("---- server output ----\n" + out)
        shutil.rmtree(tmp, ignore_errors=True)
    print("SMOKE TEST", "PASSED" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
