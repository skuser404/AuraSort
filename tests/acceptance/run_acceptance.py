#!/usr/bin/env python3
"""Acceptance test for "the scan finds 0 files / stands still": starts the real server.py with a brand-new empty home,
on a free port, reads the token from the page like the browser does, and drives the API exactly as the UI does
(info -> PIN -> scan -> poll scan/status -> summary -> every category's list).

    python tests/acceptance/run_acceptance.py [--python <exe> ...] [--only <variant>] [--keep]

Every variant must end with a scan state of done or error (never a hang); a normal folder must give files > 0 that
match what is really on disk, categories that add up to the total, no share above 100%, and a reason whenever 0 files
are found. Prints one PASS/FAIL line per variant and exits 1 if any failed. Standard library only."""
import argparse
import http.client
import json
import os
import re
import shutil
import socket
import subprocess  # nosec B404  # starts our own server.py with a fixed argument list
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PIN = "4826"
SCAN_TIMEOUT_S = 90
WIN = os.name == "nt"

# ~200 files over every category, with the awkward cases from real reports.
KINDS = {"jpg": b"\xff\xd8\xff\xe0JFIF", "png": b"\x89PNG\r\n\x1a\n", "mp4": b"\x00\x00\x00\x18ftypmp42", "mp3": b"ID3\x03",
         "pdf": b"%PDF-1.4\n", "docx": b"PK\x03\x04docx", "zip": b"PK\x03\x04", "exe": b"MZ\x90\x00", "txt": b"hello", "py": b"print(1)\n"}


def make_fixture(root):
    """Returns how many files a scan must find (everything except what is inside hidden folders such as .git)."""
    root = Path(root)
    n = 0
    for i in range(18):
        for ext, data in KINDS.items():
            p = root / ("Photos 2025" if ext in ("jpg", "png") else "Mixed") / f"file {i:02d}.{ext}"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data * (i + 1))
            n += 1
    for rel, data in (("Résumé Ünïcödé/naïve café.pdf", b"%PDF-1.4"), ("Résumé Ünïcödé/日本語 ファイル.txt", b"x"),
                      ("empty file.txt", b""), ("zero byte photo.jpg", b""), (".hidden notes.txt", b"dot files are listed"),
                      ("website/package.json", b"{}"), ("website/index.html", b"<html>"), ("website/css/site.css", b"a{}"),
                      ("website/images/logo.png", b"\x89PNG")):
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        n += 1
    for rel in ("website/.git/HEAD", "website/.git/config", ".cache/thumb.db"):   # inside hidden folders: never scanned
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")
    return n


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Server:
    def __init__(self, python, home, env_extra=None):
        self.port = free_port()
        self.home = Path(home)
        env = dict(os.environ, HOME=str(home), USERPROFILE=str(home), PYTHONIOENCODING="utf-8", AURASORT_STRICT_SCHEMA="1",
                   AURASORT_TEST_TRASH_DIR=str(Path(home).parent / "test-bin"))
        env.pop("AURASORT_FAKE_PLATFORM", None)
        env.update(env_extra or {})
        self.proc = subprocess.Popen([python, str(ROOT / "server.py"), "--no-browser", "--port", str(self.port)], cwd=str(ROOT), env=env,  # nosec B603
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.token, self.host = None, f"localhost:{self.port}"
        for _ in range(120):
            try:
                st, body = self.raw("GET", "/")
                if st == 200:
                    self.token = re.search(r'name="app-token" content="([^"]+)"', body.decode()).group(1)
                    break
            except OSError:
                pass
            time.sleep(0.25)
        if not self.token:
            raise RuntimeError("server did not start:\n" + self.stop())

    def raw(self, method, path, body=None, host=None, origin=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        h = {"Host": host or self.host}
        if self.token:
            h["X-AuraSort-Token"] = self.token
        if origin:
            h["Origin"] = origin
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            h["Content-Type"] = "application/json"
        try:
            c.request(method, path, body=data, headers=h)
            r = c.getresponse()
            return r.status, r.read()
        finally:
            c.close()

    def api(self, path, body=None, **kw):
        st, raw = self.raw("POST" if body is not None else "GET", "/api/" + path, body, **kw)
        try:
            return st, json.loads(raw or b"{}")
        except ValueError:
            return st, {"raw": raw[:200].decode("utf-8", "replace")}

    def stop(self):
        self.proc.terminate()
        try:
            return self.proc.communicate(timeout=10)[0].decode("utf-8", "replace")
        except subprocess.TimeoutExpired:
            self.proc.kill()
            return ""


def scan(srv, body, **kw):
    """The Scan page: start, then poll like pollScan() until the job ends (a hang is a failure, not a wait)."""
    st, r = srv.api("scan/start", body, **kw)
    if st != 200:
        return dict(http=st, refused=r)
    t0 = time.time()
    while time.time() - t0 < SCAN_TIMEOUT_S:
        st, s = srv.api("scan/status", **kw)
        if s.get("state") not in ("running", "paused"):
            return s
        time.sleep(0.1)
    return dict(state="HANG", after_s=SCAN_TIMEOUT_S)


def check_numbers(srv, expect, problems, **kw):
    """Totals, categories, lists and shares must agree (the 197% report)."""
    _, summ = srv.api("summary", **kw)
    if expect is not None and summ.get("total") != expect:
        problems.append(f"summary total {summ.get('total')} != {expect} files on disk")
    if not summ.get("consistent", False):
        problems.append("summary says the index numbers do not agree")
    cats = summ.get("by_cat", {})
    if sum(c["n"] for c in cats.values()) != summ.get("total"):
        problems.append("categories do not add up to the total")
    tot = summ.get("total_size") or 0
    for name, c in cats.items():
        if tot and c["size"] > tot:
            problems.append(f"{name} share above 100%")
        if c["n"]:
            st, page = srv.api("files?" + "type=" + name.replace(" ", "%20").replace("&", "%26") + "&per=500", **kw)
            if page.get("total") != c["n"]:
                problems.append(f"{name}: badge {c['n']} but list {page.get('total')}")
    _, ext = srv.api("extensions", **kw)
    disk = ext.get("disk_total") or 0
    for r in ext.get("rows", []):
        if disk and r.get("disk_size", r["size"]) > disk:
            problems.append(f".{r['ext']} share of disk above 100%")
    return summ


def deny_read(path):
    """Simulates 'permission denied' (Windows: an ACL deny for this user; elsewhere: chmod 000)."""
    if WIN:
        subprocess.run(["icacls", str(path), "/deny", f"{os.environ.get('USERNAME')}:(OI)(CI)(RD,X)"], capture_output=True, check=False)  # nosec B603 B607
    else:
        os.chmod(path, 0)


def allow_read(path):
    if WIN:
        subprocess.run(["icacls", str(path), "/remove:d", os.environ.get("USERNAME", "")], capture_output=True, check=False)  # nosec B603 B607
    else:
        os.chmod(path, 0o755)


# ---------------- variants ----------------
def v_basic(srv, base, host=None, origin=None):
    root = srv.home / "Downloads"
    n = make_fixture(root)
    s = scan(srv, {"mode": "deep", "roots": [str(root)], "skip": []}, host=host, origin=origin)
    return s, n


VARIANTS = {}


def variant(name, env=None, home_name="Test User"):
    def deco(fn):
        VARIANTS[name] = (fn, env or {}, home_name)
        return fn
    return deco


@variant("host localhost")
def _(srv, base):
    return v_basic(srv, base, host=f"localhost:{srv.port}")


@variant("host 127.0.0.1")
def _(srv, base):
    return v_basic(srv, base, host=f"127.0.0.1:{srv.port}")


@variant("host [::1]")
def _(srv, base):
    return v_basic(srv, base, host=f"[::1]:{srv.port}")


@variant("origin present (http://localhost)")
def _(srv, base):
    return v_basic(srv, base, origin=f"http://localhost:{srv.port}")


@variant("origin absent")
def _(srv, base):
    return v_basic(srv, base)


@variant("OneDrive-like path with a space", home_name="Sunil Kumar")
def _(srv, base):
    root = srv.home / "OneDrive" / "Downloads"
    n = make_fixture(root)
    return scan(srv, {"mode": "deep", "roots": [str(root)], "skip": []}), n


@variant("scan root is itself a project (package.json + .git)")
def _(srv, base):
    root = srv.home / "Downloads" / "myrepo"
    n = make_fixture(root)
    (root / "package.json").write_bytes(b"{}")
    (root / ".git").mkdir()
    (root / ".git" / "HEAD").write_bytes(b"ref")
    return scan(srv, {"mode": "deep", "roots": [str(root)], "skip": []}), n + 1   # package.json itself is a file too


@variant("repo cloned inside Downloads (only its subtree is a project)")
def _(srv, base):
    root = srv.home / "Downloads"
    n = make_fixture(root)
    repo = root / "AuraSort"
    (repo / ".git").mkdir(parents=True)
    (repo / "server.py").write_bytes(b"x")
    s = scan(srv, {"mode": "deep", "roots": [str(root)], "skip": []})
    s["_project_must_be_at_most"] = 5   # the website/ folder (4 files) + the repo (1 file); not the whole root
    return s, n + 1


@variant("Quick Scan of the usual folders")
def _(srv, base):
    n = make_fixture(srv.home / "Downloads")
    n += make_fixture(srv.home / "Documents")
    return scan(srv, {"mode": "quick", "roots": [], "skip": []}), n


def _android_env(base):
    return {"AURASORT_FAKE_PLATFORM": "android", "AURASORT_ANDROID_STORAGE": str(base / "fake" / "storage" / "emulated" / "0")}


@variant("Android: Quick Scan of the phone storage", env="android")
def _(srv, base):
    st = base / "fake" / "storage" / "emulated" / "0"
    n = make_fixture(st / "Download") + make_fixture(st / "DCIM")
    return scan(srv, {"mode": "quick", "roots": [], "skip": []}), n


@variant("Android: storage not readable (termux-setup-storage not run)", env="android")
def _(srv, base):
    st = base / "fake" / "storage" / "emulated" / "0"
    make_fixture(st / "Download")
    deny_read(st)
    try:
        s = scan(srv, {"mode": "quick", "roots": [], "skip": []})
        s2 = scan(srv, {"mode": "deep", "roots": [str(st)], "skip": []})
    finally:
        allow_read(st)
    s["_also"] = s2
    s["_expect_reason"] = "termux-setup-storage"
    return s, 0


@variant("Android: storage folder does not exist", env="android")
def _(srv, base):
    s = scan(srv, {"mode": "quick", "roots": [], "skip": []})
    s["_expect_reason"] = "termux-setup-storage"
    return s, 0


@variant("corrupt data folder (garbage index, settings and PIN files)", env="corrupt")
def _(srv, base):
    return v_basic(srv, base)


@variant("data folder from 1.0.0 (old index schema)", env="old")
def _(srv, base):
    return v_basic(srv, base)


def prepare_data(home, kind):
    d = home / ".aurasort"
    d.mkdir(parents=True, exist_ok=True)
    if kind == "corrupt":
        (d / "index.sqlite3").write_bytes(b"this is not a database" * 50)
        (d / "settings.json").write_bytes(b"{not json")
        (d / "pin.json").write_bytes(b"\x00\xff garbage")
    elif kind == "old":
        import sqlite3
        c = sqlite3.connect(str(d / "index.sqlite3"))
        c.executescript("CREATE TABLE dirs(id INTEGER PRIMARY KEY, path TEXT NOT NULL UNIQUE, drive TEXT, seen INTEGER);"
                        "CREATE TABLE files(id INTEGER PRIMARY KEY, dir INTEGER, name TEXT, lname TEXT, ext TEXT, cat TEXT, sub TEXT, "
                        "size INTEGER, mtime REAL, ctime REAL, atime REAL, seen INTEGER, UNIQUE(dir, name));"
                        "CREATE TABLE scans(id INTEGER PRIMARY KEY, started REAL, mode TEXT, roots TEXT);")
        c.close()


def run_one(python, name):
    fn, env_kind, home_name = VARIANTS[name]
    base = Path(tempfile.mkdtemp(prefix="aurasort-accept-"))
    home = base / home_name
    home.mkdir()
    env = _android_env(base) if env_kind == "android" else {}
    if env_kind in ("corrupt", "old"):
        prepare_data(home, env_kind)
    problems, srv, out = [], None, ""
    try:
        srv = Server(python, home, env)
        st, info = srv.api("info")
        if st != 200:
            problems.append(f"info answered {st}")
        st, r = srv.api("pin/set", {"pin": PIN})
        if st != 200:
            problems.append(f"pin/set answered {st}: {r}")
        s, expect = fn(srv, base)
        state = s.get("state")
        if "refused" in s:
            msg = json.dumps(s["refused"])
            if s.get("_expect_reason") is None and "_expect_reason" not in s:
                problems.append(f"scan/start refused ({s['http']}): {msg[:200]}")
            elif s.get("_expect_reason") and s["_expect_reason"] not in msg:
                problems.append(f"refused without saying what to do: {msg[:200]}")
            return problems, f"refused {s['http']} {s['refused'].get('code')}: {s['refused'].get('error', '')[:90]}"
        if state not in ("done", "error"):
            problems.append(f"scan ended as {state!r} (must be done or error)")
        found = s.get("found", 0)
        if s.get("_expect_reason"):
            text = json.dumps(s.get("explain", [])) + json.dumps(s.get("failure") or {})
            if found or s["_expect_reason"] not in text:
                problems.append(f"0 files without the reason '{s['_expect_reason']}': explain={s.get('explain')}")
            if "_also" in s:
                also = s["_also"]
                t2 = json.dumps(also)
                if s["_expect_reason"] not in t2:
                    problems.append(f"Deep Scan of the storage: no '{s['_expect_reason']}' hint: {t2[:200]}")
            detail = f"0 files, explained: {[e['code'] for e in s.get('explain', [])]}"
        else:
            if not found:
                problems.append(f"0 files found (expected {expect}); skipped={s.get('skipped')} explain={s.get('explain')}")
            elif found != expect:
                problems.append(f"found {found}, but {expect} are on disk; skipped={s.get('skipped')}")
            check_numbers(srv, expect, problems)
            proj = (s.get("notes") or {}).get("project", 0)
            if "_project_must_be_at_most" in s and proj > s["_project_must_be_at_most"]:
                problems.append(f"{proj} files counted as project files (the whole root was treated as a project)")
            detail = f"found {found}/{expect}, skipped {s.get('skipped')}, project files {proj}"
        return problems, detail
    except Exception as ex:  # noqa: BLE001 - a crash in a variant is a failure with its reason
        problems.append(f"{type(ex).__name__}: {ex}")
        return problems, ""
    finally:
        if srv:
            out = srv.stop()
            if problems:
                tail = "\n".join(out.splitlines()[-25:])
                problems.append("server output (last lines):\n      " + tail.replace("\n", "\n      "))
        shutil.rmtree(base, ignore_errors=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--python", action="append", help="interpreter(s) to run the server with (default: this one)")
    ap.add_argument("--only", help="run variants whose name contains this text")
    a = ap.parse_args()
    pythons = a.python or [sys.executable]
    failed = 0
    for py in pythons:
        ver = subprocess.run([py, "-c", "import sys;print(sys.version.split()[0])"], capture_output=True, text=True, check=False).stdout.strip()  # nosec B603
        print(f"== Python {ver} ({py})", flush=True)
        for name in VARIANTS:
            if a.only and a.only.lower() not in name.lower():
                continue
            problems, detail = run_one(py, name)
            print(f"{'PASS' if not problems else 'FAIL'}  {name}: {detail}", flush=True)
            for p in problems:
                print("      - " + p, flush=True)
            failed += bool(problems)
    print(f"\n{'ALL PASSED' if not failed else str(failed) + ' FAILED'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
