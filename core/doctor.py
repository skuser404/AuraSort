"""Self-check for "the scan finds 0 files on my friend's PC": `py server.py --doctor` and Settings > Diagnostics.

Every check runs on its own (one failure never hides the others) and reports facts only: no file names, the home
folder shown as ~ and the user name masked. A short test scan uses the scanner's real rules, so it shows exactly what
a scan would skip on this machine and why."""
import getpass
import json
import locale
import os
import queue
import re
import shutil
import sqlite3
import struct
import sys
import tempfile
import time
import traceback

from . import config, index_db, platform_utils

OK, WARN, FAIL = "ok", "warn", "fail"
PROBLEM_SKIPS = ("no_access", "unreadable", "error", "bad_name", "vanished")   # skip reasons that mean "something blocked the scan"
SELF_TEST_FILES = (("photo.jpg", b"\xff\xd8\xff\xe0 test"), ("notes.txt", b"hello"), ("song.mp3", b"ID3 test"), ("report.pdf", b"%PDF-1.4"),
                   ("Tax 2025/résumé.docx", b"PK test"), ("archive.zip", b"PK\x03\x04"))


def _user():
    try:
        return getpass.getuser()
    except (OSError, KeyError):
        return ""


def mask(text):
    """Why: diagnostics are pasted into public issues: the home folder becomes ~ and the user name <user> (any case)."""
    text = str(text)
    for home in {str(config.HOME), os.path.expanduser("~")}:
        if home and len(home) > 3:
            text = re.sub(re.escape(home), "~", text, flags=re.I)
            text = re.sub(re.escape(home.replace("\\", "/")), "~", text, flags=re.I)
    user = _user()
    if len(user) >= 3:
        text = re.sub(r"(?<![A-Za-z0-9])" + re.escape(user) + r"(?![A-Za-z0-9])", "<user>", text, flags=re.I)
    return text


class Report:
    """Why: one list of checks, each with a status, a short value and (for problems) what to do."""

    def __init__(self):
        self.checks, self.facts = [], {}

    def add(self, name, status, value, fix="", detail=None):
        self.checks.append(dict(name=name, status=status, value=mask(value), fix=fix, **({"detail": detail} if detail else {})))

    def run(self, name, fn):
        """Why: an exception in one check is reported with its traceback (masked) instead of stopping the doctor."""
        try:
            fn(self)
        except Exception as ex:  # noqa: BLE001 - the point of the doctor is to report every failure, whatever it is
            self.add(name, FAIL, f"{type(ex).__name__}: {ex}", "This is a bug. Please send this report.",
                     detail=mask("".join(traceback.format_exception(type(ex), ex, ex.__traceback__))[-3000:]))


# ---------------- checks ----------------
def _system(r):
    r.facts.update(app=config.APP_NAME, version=config.APP_VERSION, os=platform_utils.OS_NAME, platform=config.PLATFORM)
    r.add("App", OK, f"{config.APP_NAME} {config.APP_VERSION}")
    r.add("Operating system", OK, f"{platform_utils.OS_NAME} ({config.PLATFORM})")
    bits = struct.calcsize("P") * 8
    py = f"{platform_utils.PYTHON_VERSION} {bits}-bit ({sys.implementation.name}) at {sys.executable}"
    if sys.version_info < (3, 10):
        r.add("Python", FAIL, py, "Install Python 3.10 or newer (winget install Python.Python.3.12, or python.org).")
    elif "WindowsApps" in sys.executable:
        r.add("Python", WARN, py, "This is the Microsoft Store Python. It works, but it can see a redirected AppData. "
                                  "The python.org installer (winget install Python.Python.3.12) is recommended.")
    else:
        r.add("Python", OK, py)


def _encoding(r):
    enc = dict(preferred=locale.getpreferredencoding(False), filesystem=sys.getfilesystemencoding(),
               stdout=getattr(sys.stdout, "encoding", None), locale=locale.getlocale()[0] or "", utf8_mode=bool(sys.flags.utf8_mode))
    r.facts["encoding"] = enc
    value = ", ".join(f"{k}={v}" for k, v in enc.items())
    r.add("Text encoding", OK if sys.getfilesystemencoding().lower().replace("-", "") in ("utf8", "mbcs") else WARN, value,
          "" if sys.getfilesystemencoding() else "Set PYTHONUTF8=1 and start AuraSort again.")


def _admin(r):
    admin = platform_utils.is_admin()
    r.facts["admin"] = admin
    if admin and config.WIN:
        r.add("Administrator / root", OK, "administrator permission (as the installer sets it up); Windows system folders are still skipped")
    elif admin:
        r.add("Administrator / root", WARN, "running as root", "Not needed: start AuraSort as your normal user.")
    else:
        r.add("Administrator / root", OK, "standard user" + (": folders Windows protects (other users, some system places) are skipped"
                                                             if config.WIN else ""))


def _data_folder(r):
    d = config.DATA_DIR
    r.facts["data_dir"] = mask(d)
    if not d.exists():
        r.add("Data folder", OK, f"{d} (not created yet: a first run)")
        probe_parent = d.parent
    else:
        probe_parent = d
    try:
        fd, probe = tempfile.mkstemp(prefix=".doctor-", dir=str(probe_parent))
        os.close(fd)
        os.remove(probe)
        writable = True
    except OSError as ex:
        writable = False
        r.add("Data folder", FAIL, f"{d} is not writable ({type(ex).__name__})",
              "AuraSort keeps its index in your user folder. Check that you can create files there (antivirus, Controlled Folder Access, a read-only profile).")
    if writable and d.exists():
        r.add("Data folder", OK, f"{d} (writable)")
    try:
        free = shutil.disk_usage(str(probe_parent)).free
        r.add("Free space for the index", OK if free > 200 * 1024 ** 2 else WARN, f"{free / 1024 ** 3:.1f} GB free",
              "" if free > 200 * 1024 ** 2 else "Free some space on this drive: the index needs room to grow.")
    except OSError as ex:
        r.add("Free space for the index", WARN, type(ex).__name__)


def _sqlite(r):
    r.facts["sqlite"] = sqlite3.sqlite_version
    folder = config.DATA_DIR if config.DATA_DIR.exists() else config.DATA_DIR.parent
    tmpdir = tempfile.mkdtemp(prefix=".doctor-db-", dir=str(folder))
    try:
        path = os.path.join(tmpdir, "t.sqlite3")
        c = sqlite3.connect(path)
        try:
            mode = c.execute("PRAGMA journal_mode=WAL").fetchone()[0]
            c.execute("CREATE TABLE t(x)")
            c.execute("INSERT INTO t VALUES (?)", ("ünïcødé 中文 тест",))
            c.commit()
            back = c.execute("SELECT x FROM t").fetchone()[0]
        finally:
            c.close()
        ok = back == "ünïcødé 中文 тест"
        r.add("SQLite", OK if ok and mode == "wal" else WARN, f"version {sqlite3.sqlite_version}, journal {mode}, write test {'ok' if ok else 'FAILED'}",
              "" if mode == "wal" else "This folder cannot use WAL (network share or sync tool). AuraSort still works, more slowly.")
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _index(r):
    if not config.INDEX_DB.exists():
        r.add("File index", OK, "not created yet (no scan so far)")
        return
    c = sqlite3.connect(f"file:{config.INDEX_DB}?mode=ro", uri=True, timeout=5)
    try:
        ver = c.execute("PRAGMA user_version").fetchone()[0]
        tables = {t for (t,) in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        files = c.execute("SELECT COUNT(*) FROM files").fetchone()[0] if "files" in tables else 0
        scans = c.execute("SELECT state, COUNT(*) FROM scans GROUP BY state").fetchall() if "scans" in tables else []
        orphans = c.execute("SELECT COUNT(*) FROM files WHERE dir NOT IN (SELECT id FROM dirs)").fetchone()[0] if {"files", "dirs"} <= tables else 0
    finally:
        c.close()
    r.facts["index"] = dict(schema=ver, files=files, scans=dict(scans), orphans=orphans)
    status = OK if ver == index_db.SCHEMA_VERSION and not orphans else WARN
    r.add("File index", status, f"schema {ver} (current {index_db.SCHEMA_VERSION}), {files} files, scans {dict(scans)}, orphan rows {orphans}",
          "" if status == OK else "An older or inconsistent index: start AuraSort and run a new scan (it is upgraded or rebuilt automatically).")


def _drives(r):
    drives = platform_utils.list_drives()
    r.facts["drives"] = [dict(root=d["root"], type=d["type"], ready=d["ready"], total_gb=round(d.get("total", 0) / 1024 ** 3, 1),
                              free_gb=round(d.get("free", 0) / 1024 ** 3, 1)) for d in drives]
    r.add("Drives", OK if drives else WARN, "; ".join(f"{d['root']} {d['type']}{'' if d['ready'] else ' (not ready)'}" for d in drives) or "none found")


def _quick_folders(r):
    out = []
    for q in platform_utils.quick_folders():
        readable, entries = False, 0
        if q["exists"]:
            try:
                with os.scandir(platform_utils.long_path(q["path"])) as it:
                    for _ in it:
                        entries += 1
                        if entries >= 1000:
                            break
                readable = True
            except OSError as ex:
                readable = f"no ({type(ex).__name__})"
        out.append(dict(name=q["name"], path=mask(q["path"]), source=q.get("source", ""), exists=q["exists"], readable=readable,
                        onedrive=q.get("onedrive", False), entries=entries))
    r.facts["quick_folders"] = out
    for q in out:
        bits = [q["path"], f"from {q['source']}"]
        if q["onedrive"]:
            bits.append("in OneDrive")
        if not q["exists"]:
            st, fix = WARN, "This folder does not exist, so Quick Scan skips it."
        elif q["readable"] is not True:
            st, fix = FAIL, "Reading this folder is blocked: check antivirus / Controlled Folder Access (Windows) or Full Disk Access (macOS)."
        else:
            st, fix = OK, ""
            bits.append(f"{q['entries']}{'+' if q['entries'] >= 1000 else ''} items at the top level")
        r.add(f"Quick Scan folder: {q['name']}", st, ", ".join(bits), fix)


class _FakeJob:
    """Why: the test scan drives the scanner's real folder code without the index or a background job."""

    def __init__(self):
        self._cancel, self.total, self.done, self.bytes, self.current_file = False, 0, 0, 0, ""
        self.extra = dict(found=0, bytes=0, dirs=0, queued=0, noaccess=0, unreadable=0, by_cat={}, recent=[], drive_stats={},
                          skipped={}, notes={}, errors_by_code={})


def test_scan(folder, seconds=config.DOCTOR_TEST_SCAN_S):
    """Why: walk one folder with the scanner's own rules for a few seconds and count what was found and what was skipped."""
    from . import scanner   # late import: scanner imports a lot, the doctor's other checks must work without it
    job = _FakeJob()
    roots = [os.path.realpath(folder)]
    walk = scanner._Walk(job, [], [], roots)
    q = queue.Queue()
    walk.queues.append(q)
    for r in roots:
        q.put((r, scanner._project_above(r, walk.never_project)))
    t0, complete = time.time(), True
    while not q.empty():
        if time.time() - t0 > seconds or job.extra["found"] >= config.DOCTOR_TEST_SCAN_MAX_FILES:
            complete = False
            break
        walk.scan_dir(q.get(), q, platform_utils.drive_of(roots[0]), None)
        while not walk.sink.empty():
            walk.sink.get()
    ex = job.extra
    return dict(folders=ex["dirs"], files=ex["found"], bytes=ex["bytes"], skipped=ex["skipped"], notes=ex["notes"],
                errors_by_code=ex["errors_by_code"], complete=complete, seconds=round(time.time() - t0, 2),
                explain=scanner.explain(dict(found=ex["found"], skipped=ex["skipped"], notes=ex["notes"], mode="deep")))


def _test_scan(r, folder=None):
    if not folder:
        folder = next((q["path"] for q in platform_utils.quick_folders() if q["exists"]), None)
    if not folder:
        r.add("Test scan", WARN, "no Quick Scan folder exists to test", "Run 'py server.py --doctor --folder <a folder with files>'.")
        return
    res = test_scan(folder)
    r.facts["test_scan"] = dict(res, folder=mask(folder))
    value = (f"{mask(folder)}: {res['files']} files in {res['folders']} folders in {res['seconds']} s"
             f"{'' if res['complete'] else ' (stopped early: the test is limited)'}; skipped {res['skipped'] or 'nothing'}; notes {res['notes'] or 'none'}"
             + (f"; OS errors {res['errors_by_code']}" if res["errors_by_code"] else ""))
    if res["files"]:
        r.add("Test scan", OK, value)
    else:
        why = "; ".join(f"{e['title']}: {e['body']}" for e in res["explain"]) or "The folder has no files."
        problems = {k for k in res["skipped"] if k in PROBLEM_SKIPS}   # desktop.ini or hidden folders in an empty folder are not a failure
        r.add("Test scan", FAIL if problems else WARN, value, why)


# ---------------- entry points ----------------
def collect(folder=None, scan=True):
    """Why: the same facts for the terminal (--doctor) and the UI (Settings > Diagnostics, 'Copy diagnostics')."""
    r = Report()
    for name, fn in (("System", _system), ("Encoding", _encoding), ("Administrator", _admin), ("Data folder", _data_folder),
                     ("SQLite", _sqlite), ("File index", _index), ("Drives", _drives), ("Quick Scan folders", _quick_folders)):
        r.run(name, fn)
    if scan:
        r.run("Test scan", lambda rep: _test_scan(rep, folder))
    worst = FAIL if any(c["status"] == FAIL for c in r.checks) else WARN if any(c["status"] == WARN for c in r.checks) else OK
    return dict(status=worst, time=int(time.time()), checks=r.checks, facts=r.facts)


def as_text(d):
    """Why: a plain report people can paste into an issue (statuses first, facts as JSON at the end)."""
    mark = {OK: "OK  ", WARN: "WARN", FAIL: "FAIL"}
    lines = [f"{config.APP_NAME} diagnostics ({time.strftime('%Y-%m-%d %H:%M', time.localtime(d['time']))}): overall {d['status'].upper()}", ""]
    for c in d["checks"]:
        lines.append(f"[{mark[c['status']]}] {c['name']}: {c['value']}")
        if c.get("fix"):
            lines.append(f"       -> {c['fix']}")
        if c.get("detail"):
            lines.extend("       " + ln for ln in c["detail"].splitlines())
    lines += ["", "No file names are included. Paths start at your home folder (~); your user name is shown as <user>.",
              "", "facts: " + json.dumps(d["facts"], ensure_ascii=False, default=str)]
    return "\n".join(lines)


def self_test():
    """Why: the installers' last step: scan a temporary folder of known files with the real scanner rules, so "it found N
    files" is proven on this machine before anyone relies on it. Exit code 0 = passed."""
    # In the home folder: the system temp folder is inside AppData on Windows, which the scanner (rightly) never enters.
    tmp = tempfile.mkdtemp(prefix=".aurasort-selftest ", dir=str(config.HOME) if os.path.isdir(config.HOME) else None)
    try:
        for rel, data in SELF_TEST_FILES:
            f = os.path.join(tmp, rel)
            os.makedirs(os.path.dirname(f), exist_ok=True)
            with open(f, "wb") as fh:
                fh.write(data)
        res = test_scan(tmp)
    except Exception as ex:  # noqa: BLE001 - reported, never a crash in an installer
        print(f"Self-test FAILED: {type(ex).__name__}: {mask(ex)}", flush=True)
        res = None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    want = len(SELF_TEST_FILES)
    if res and res["files"] == want:
        print(f"Self-test passed: found {res['files']} files.", flush=True)
        return 0
    if res:
        print(f"Self-test FAILED: found {res['files']} of {want} files; skipped {res['skipped']}; OS errors {res['errors_by_code']}.", flush=True)
    print("Send the output of this command to the developer:  py server.py --doctor   (macOS/Linux: python3 server.py --doctor)", flush=True)
    return 1


def main(folder=None, as_json=False):
    """Why: `py server.py --doctor`: exit code 0 = fine, 1 = something needs attention."""
    d = collect(folder)
    print(json.dumps(d, ensure_ascii=False, indent=1, default=str) if as_json else as_text(d), flush=True)
    return 0 if d["status"] != FAIL else 1
