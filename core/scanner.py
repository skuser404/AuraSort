"""Scanning into the SQLite index. Quick Scan = usual user folders; Deep Scan = chosen drives/folders.

Runs on a background job with a small worker pool per drive (os.scandir, DirEntry.stat reused, links/junctions
skipped), live partial counters, pause/resume/cancel and a files/second ETA."""
import collections
import errno
import os
import queue
import shutil
import sqlite3
import stat
import threading
import time

from . import classify, config, history, index_db, jobs, settings
from .log import log
from .schema import NOTHING_SELECTED, BadRequest
from .platform_utils import (created_time, drive_media, drive_of, is_hidden_system, is_online_only, is_reparse_or_link, long_path,
                             quick_folders, within)
from .safety import canonical, folder_kind, is_project, is_protected

_IGNORED_NAMES = config.IGNORED_FILE_NAMES
_IGNORED_PREFIXES = config.IGNORED_FILE_PREFIXES
PROJECT_LOOKUP_LEVELS = 30          # how far above a scan root we look for a project marker
QUEUE_POLL_S = 0.1
WRITER_FLUSH_S = 0.5
CURRENT = {"job": None}


class ScanFailed(Exception):
    """Why: a fatal problem (the index cannot be written) ends the scan with a plain message, a stable code and a hint."""

    def __init__(self, message, code, hint="", step=""):
        super().__init__(message)
        self.code, self.hint, self.step = code, hint, step


# sqlite3 message fragment -> (code, message, hint). Anything else is reported as "index_error".
INDEX_ERRORS = (
    ("locked", "index_busy", "The file index is being used by another AuraSort window or program.",
     "Close other AuraSort windows (or restart the PC), then try again."),
    ("full", "disk_full", "The drive that holds your AuraSort data is full.", "Free some space on that drive, then try again."),
    ("readonly", "index_readonly", "The file index could not be written (the data folder is read-only).",
     "Check that your user folder is writable, then try again."),
    ("disk i/o", "index_io", "The file index could not be written (a disk read/write error).", "Check the drive for errors, then try again."),
)


def index_failure(ex, step):
    """Why: turn a database error into words a person can act on (the traceback goes to the log)."""
    low = str(ex).lower()
    for frag, code, msg, hint in INDEX_ERRORS:
        if frag in low:
            return ScanFailed(msg, code, hint, step)
    return ScanFailed("The file index could not be updated.", "index_error", f"Details are in the log file: {config.LOG_FILE_SHOWN}", step)


def errno_name(ex):
    """Why: 'EACCES'/'EPERM'/'WinError 5' tell antivirus or Controlled Folder Access apart from macOS privacy blocks."""
    win = getattr(ex, "winerror", None)
    if win:
        return f"WinError {win}"
    code = getattr(ex, "errno", None)
    return errno.errorcode.get(code, str(code)) if code is not None else type(ex).__name__


def storable(text):
    """Why: Windows allows names with broken Unicode (lone surrogates, e.g. from old phones or bad unzips); SQLite can't store them."""
    try:
        text.encode("utf-8")
        return True
    except UnicodeEncodeError:
        return False


# ---------------- validation ----------------
def clean_roots(roots, report=None):
    """Why: every root is resolved (8.3 names, links) and must not be protected. A missing folder is skipped (counted in
    `report`) as long as something else is left to scan; with nothing left, the request is refused with a clear message."""
    out, missing = [], 0
    for r in roots:
        r = canonical(r)
        if not os.path.isdir(r):
            missing += 1
            continue
        if is_protected(r):
            name = os.path.basename(r.rstrip(os.sep)) or r
            raise BadRequest(f"'{name}' is a protected system folder and is never scanned.", "protected",
                             "Remove it from the list, or pick a folder inside your user folder.")
        if not any(within(r, o) for o in out):
            out = [o for o in out if not within(o, r)] + [r]   # drop roots nested in other roots
    if report is not None and missing:
        report["missing_root"] = report.get("missing_root", 0) + missing
    if not out:
        if missing:
            msg = ("The folder to scan was not found (it was moved, renamed, or its drive is unplugged)." if missing == 1
                   else "None of the folders to scan were found (moved, renamed, or the drive is unplugged).")
            raise BadRequest(msg, "not_found", "Plug the drive back in, or remove the folder and add it again.")
        raise BadRequest(NOTHING_SELECTED, "nothing_selected", "Tick a drive or add a folder on the Scan page.")
    return out


def quick_roots():
    """Why: Quick Scan = Downloads, Documents, Desktop, Pictures, Videos/Movies, Music (whichever exist)."""
    return [q["path"] for q in quick_folders() if q["exists"]]


def never_project():
    """Why: the home folder (VS Code puts .vscode there), its parent, drive roots and the standard user folders
    are containers, not projects; treating them as projects would lock every file below them."""
    home = canonical(config.HOME)
    names = {os.path.normcase(home), os.path.normcase(os.path.dirname(home))}
    names |= {os.path.normcase(canonical(q["path"])) for q in quick_folders()}
    return names


def _project_above(root, blocked):
    """Why: a scan root inside a project (e.g. a website's assets folder) still belongs to that project. Strict markers
    only: one stray file above the root (a .gitignore in the user folder) must not lock every file below it."""
    p = os.path.dirname(root)
    for _ in range(PROJECT_LOOKUP_LEVELS):
        parent = os.path.dirname(p)
        if parent == p or os.path.normcase(p) in blocked:
            return None
        try:
            if is_project(set(os.listdir(long_path(p))), strict=True):
                log.info("scan: a scan folder is inside a project folder (%s levels up); its files are left alone", root.count(os.sep) - p.count(os.sep))
                return p
        except OSError:
            pass
        parent = os.path.dirname(p)
        if parent == p:
            return None
        p = parent
    return None


# ---------------- the walk ----------------
class _Walk:
    """Why: shared state of one scan: skip rules, counters (lock-protected) and the queue to the DB writer."""

    def __init__(self, job, skip, dest_roots, roots=()):
        self.job, self.skip, self.dest_roots = job, [os.path.normcase(s) for s in skip], [os.path.normcase(d) for d in dest_roots]
        self.roots = {os.path.normcase(r) for r in roots}
        self.lock, self.sink = threading.Lock(), queue.Queue()
        self.queues, self.never_project = [], never_project()
        self.fatal = None          # set by the writer when the index cannot be written: every worker stops

    def stopping(self):
        return self.job._cancel or self.fatal is not None

    def skip_item(self, reason, n=1, ex=None):
        """Why: nothing is dropped silently: every skipped folder or file is counted with its reason (and OS error code,
        which tells 'Windows/antivirus blocked it' from 'macOS privacy blocked it')."""
        with self.lock:
            ext = self.job.extra
            sk = ext["skipped"]
            sk[reason] = sk.get(reason, 0) + n
            if reason == "no_access":
                ext["noaccess"] += n
            elif reason in ("unreadable", "vanished"):
                ext["unreadable"] += n
            if ex is not None:
                code = errno_name(ex)
                ext["errors_by_code"][code] = ext["errors_by_code"].get(code, 0) + n
                first = sk[reason] == n
        if ex is not None and first:   # the first of each kind goes to the log (paths are masked there)
            log.warning("scan: first '%s' skip: %s (%s)", reason, type(ex).__name__, errno_name(ex))

    @staticmethod
    def reason_for(ex):
        """Why: one mapping from OS errors to the reasons shown in the UI."""
        if isinstance(ex, PermissionError):
            return "no_access"
        if isinstance(ex, (FileNotFoundError, NotADirectoryError)):
            return "vanished"
        return "unreadable"

    def skipped(self, path):
        p = os.path.normcase(path)
        return any(p == s or p.startswith(s.rstrip(os.sep) + os.sep) for s in self.skip)

    def kind_for(self, path, project):
        p = os.path.normcase(path)
        if any(p == d or p.startswith(d.rstrip(os.sep) + os.sep) for d in self.dest_roots):
            return "sorted"
        return folder_kind(path, 0 if project else -1)

    def count(self, path, files, nbytes, by_cat, drive, notes=None):
        """Why: counters are updated once per folder (not per file) to keep lock traffic low."""
        ex = self.job.extra
        with self.lock:
            for k, n in (notes or {}).items():
                if n:
                    ex["notes"][k] = ex["notes"].get(k, 0) + n
            ex["found"] += len(files)
            ex["bytes"] += nbytes
            ex["dirs"] += 1
            for c, n in by_cat.items():
                ex["by_cat"][c] = ex["by_cat"].get(c, 0) + n
            d = ex["drive_stats"].get(drive)
            if d is not None:
                d["scanned"] += nbytes
            ex["recent"] = (ex["recent"] + [path])[-config.SCAN_STATUS_RECENT_DIRS:]
            ex["queued"] = sum(q.qsize() for q in self.queues)
            self.job.current_file = path
            self.job.done = ex["found"]
            self.job.bytes = ex["bytes"]
            if self.job.total and ex["found"] >= self.job.total:
                self.job.total = int(ex["found"] * 1.1) + 1   # estimate was low: keep the bar honest (never 100% early)

    def scan_dir(self, item, q, drive, dev):
        """Why: list one folder; files go to the writer, sub-folders back onto the queue."""
        d, project = item
        if not storable(d):
            self.skip_item("bad_name")
            return
        try:
            with os.scandir(long_path(d)) as it:   # \\?\ for long Windows paths; the stored path stays the normal one
                entries = list(it)
        except OSError as ex:              # no permission, folder removed mid-scan, drive unplugged...
            self.skip_item(self.reason_for(ex), ex=ex)
            return
        nd = os.path.normcase(d)
        if project is None and os.path.dirname(d) != d and nd not in self.never_project \
                and is_project({e.name for e in entries}, strict=nd in self.roots):
            project = d
        files, nsub, nbytes, by_cat = [], 0, 0, collections.Counter()
        notes = collections.Counter()
        for e in entries:
            if not storable(e.name):
                self.skip_item("bad_name")
                continue
            path = os.path.join(d, e.name)
            try:
                st = e.stat(follow_symlinks=False)
                if is_reparse_or_link(st):
                    self.skip_item("link")
                    continue
                name = e.name
                if stat.S_ISDIR(st.st_mode):
                    nsub += 1
                    if name.lower().endswith(config.MAC_BUNDLE_EXTS):
                        files.append(self.bundle_row(path, name, st))
                        nbytes += files[-1][4]
                        by_cat[files[-1][2]] += 1
                    elif name.startswith(".") or is_hidden_system(st):
                        self.skip_item("hidden")
                    elif is_protected(path):
                        self.skip_item("protected")
                    elif self.skipped(path):
                        self.skip_item("skip_list")
                    else:
                        q.put((path, project))
                elif stat.S_ISREG(st.st_mode):
                    low = name.lower()
                    if low in _IGNORED_NAMES or low.startswith(_IGNORED_PREFIXES):
                        self.skip_item("system_file")
                        continue
                    ext, cat, sub = classify.classify(name)
                    flags = 0
                    if ext in config.PARTIAL_DOWNLOAD_EXTS:
                        flags |= index_db.FLAG_PARTIAL
                        notes["partial"] += 1
                    if is_online_only(st):
                        flags |= index_db.FLAG_CLOUD   # listed from metadata only; reading it would make OneDrive/iCloud download it
                        notes["online_only"] += 1
                    if cat == classify.OTHER:
                        notes["other_ext"] += 1
                    files.append((name, ext, cat, sub, st.st_size, st.st_mtime, created_time(st), st.st_atime, flags))
                    nbytes += st.st_size
                    by_cat[cat] += 1
            except OSError as ex:          # the file vanished or is locked between listing and stat
                self.skip_item(self.reason_for(ex), ex=ex)
                continue
        if project is not None:
            notes["project"] += len(files)
        self.sink.put((d, project, self.kind_for(d, project), drive, dev, nsub, files))
        self.count(d, files, nbytes, by_cat, drive, notes)

    @staticmethod
    def bundle_row(path, name, st):
        """Why: macOS bundles (.app, .photoslibrary...) are one opaque item: listed with their total size, never opened."""
        total = 0
        for root, _, fs in os.walk(path):
            for f in fs:
                try:
                    total += os.lstat(os.path.join(root, f)).st_size
                except OSError:   # one unreadable item inside an app bundle: the bundle's size is then a lower bound
                    continue
        ext, cat, sub = classify.classify(name)
        return (name, ext, cat, sub, total, st.st_mtime, created_time(st), st.st_atime, index_db.FLAG_BUNDLE)

    def walk_drive(self, roots, drive):
        """Why: a small worker pool per drive; pause blocks the workers, cancel drains the queue."""
        q = queue.Queue()
        self.queues.append(q)
        for r in roots:
            q.put((r, _project_above(r, self.never_project)))
        try:
            dev = os.stat(roots[0]).st_dev
        except OSError:
            dev = None
        stop = threading.Event()
        job = self.job

        def worker():
            while not stop.is_set():
                try:
                    item = q.get(timeout=QUEUE_POLL_S)
                except queue.Empty:
                    continue
                try:
                    if not self.stopping():
                        job._run.wait()
                        if not self.stopping():
                            self.scan_dir(item, q, drive, dev)
                except Exception:  # noqa: BLE001 - one bad folder must not stop the scan: counted and logged with its traceback
                    log.exception("scan: a folder failed and was skipped")
                    self.skip_item("error")
                finally:
                    q.task_done()
        try:
            media = drive_media(drive)
        except Exception:  # noqa: BLE001 - a drive that stops answering is scanned with the default pool size
            log.exception("scan: drive type could not be read")
            media = "unknown"
        self.job.extra.setdefault("media", {})[drive] = media
        threads = [threading.Thread(target=worker, daemon=True, name="scan-worker") for _ in range(config.SCAN_WORKERS.get(media, config.SCAN_WORKERS_PER_DRIVE))]
        for t in threads:
            t.start()
        q.join()
        stop.set()
        for t in threads:
            t.join()


def _writer(walk, scan_id, done_evt, result):
    """Why: one thread owns all SQLite writes for the scan (batched transactions). It never dies silently: a folder that
    can't be stored is skipped and counted; a database failure (locked, disk full, damaged) is handed to the scan as fatal."""
    try:
        w = index_db.ScanWriter(scan_id)
        result["w"] = w
        last = time.time()
        while walk.fatal is None:
            try:
                item = walk.sink.get(timeout=QUEUE_POLL_S)
            except queue.Empty:
                if done_evt.is_set() and walk.sink.empty():
                    break
                item = None
            with index_db.write_lock():
                if item:
                    try:
                        w.add(*item)
                    except (sqlite3.IntegrityError, ValueError, OverflowError) as ex:   # one bad row: skip that folder only
                        log.warning("scan: a folder could not be stored and was skipped (%s)", type(ex).__name__)
                        walk.skip_item("error")
                if time.time() - last > WRITER_FLUSH_S:
                    w.commit()
                    last = time.time()
        if walk.fatal is None:
            with index_db.write_lock():
                w.commit()
    except Exception as ex:  # noqa: BLE001 - sqlite3 errors and anything unexpected: stop the scan with a clear reason
        log.exception("scan: writing the file index failed")
        walk.fatal = ex


def _step(job, name):
    """Why: a failure report says which step failed ('reading folders', 'writing the index'...), never a bare exception name."""
    job.extra["step"] = name


def _run(job, roots, skip):
    """Why: the whole scan: group roots by drive, walk drives in parallel, write, prune, snapshot, log."""
    ex = job.extra
    _step(job, "starting")
    try:
        scan_id = index_db.begin_scan(ex["mode"], roots)
    except sqlite3.Error as e:
        raise index_failure(e, "starting") from e
    try:
        _scan(job, roots, skip, scan_id)
    except jobs.Cancelled:
        raise                              # already recorded as cancelled
    except BaseException:
        try:
            index_db.end_scan(scan_id, "cancelled" if job._cancel else "error", ex["found"], ex["bytes"], ex["noaccess"])
        except sqlite3.Error:
            log.exception("scan: could not record the scan's end")
        raise


def _scan(job, roots, skip, scan_id):
    """Why: the walk itself (see _run for the bookkeeping around it)."""
    ex = job.extra
    walk = _Walk(job, skip, settings.load()["dest_roots"], roots)
    groups = collections.defaultdict(list)
    for r in roots:
        groups[drive_of(r)].append(r)
    for drive in groups:
        try:
            used = shutil.disk_usage(drive).used
        except OSError:
            used = 0
        ex["drive_stats"][drive] = dict(root=drive, used=used, scanned=0, whole=any(os.path.dirname(r) == r for r in groups[drive]))
    done_evt = threading.Event()
    result = {}
    wt = threading.Thread(target=_writer, args=(walk, scan_id, done_evt, result), daemon=True, name="scan-writer")
    wt.start()
    _step(job, "reading folders")
    walkers = [threading.Thread(target=walk.walk_drive, args=(rs, d), daemon=True, name="scan-drive") for d, rs in groups.items()]
    for t in walkers:
        t.start()
    for t in walkers:
        t.join()
    done_evt.set()
    _step(job, "writing the index")
    wt.join()
    if walk.fatal is not None:
        raise index_failure(walk.fatal, "writing the index") from walk.fatal
    cancelled = job._cancel
    _step(job, "finishing")
    try:
        with index_db.write_lock():
            result["w"].finish(prune=not cancelled)
        index_db.end_scan(scan_id, "cancelled" if cancelled else "done", ex["found"], ex["bytes"], ex["noaccess"])
    except sqlite3.Error as e:
        log.exception("scan: finishing the file index failed")
        raise index_failure(e, "finishing") from e
    if not cancelled:
        threading.Thread(target=_warm_caches, daemon=True, name="warm").start()
        _after_scan(groups, roots, ex)
    job.total = max(job.total, ex["found"])
    job.done = ex["found"]
    if cancelled:
        raise jobs.Cancelled()


def _warm_caches():
    """Why: build the summary and the search index right after a scan, so the first search and dashboard are instant."""
    try:
        index_db.summary()
        index_db.search_index()
        index_db.facets({"scope": "all"})
    except Exception:  # noqa: BLE001 - warming is best effort
        log.exception("cache warm-up failed")


def _after_scan(groups, roots, ex):
    """Why: the storage-trend snapshot and the History entry are extras: if they fail the scan itself still succeeded."""
    try:
        _snapshots(groups)
    except Exception:  # noqa: BLE001 - logged with traceback; the new index is already saved
        log.exception("scan: storage snapshot failed")
    try:
        history.record("scan", mode=ex["mode"], count=ex["found"], size=ex["bytes"], roots=len(roots), noaccess=ex["noaccess"],
                       label="Quick Scan" if ex["mode"] == "quick" else "Deep Scan")
    except Exception:  # noqa: BLE001 - same: History is a record of the scan, not part of it
        log.exception("scan: History entry could not be written")


def _snapshots(groups):
    """Why: one snapshot per drive after each scan feeds the storage trend chart (real numbers only)."""
    db = index_db.reader()
    for drive in groups:
        try:
            u = shutil.disk_usage(drive)
        except OSError:
            continue
        bytype = dict(db.execute("SELECT files.cat, SUM(files.size) FROM files JOIN dirs ON dirs.id=files.dir WHERE dirs.drive=? GROUP BY files.cat",
                                 (drive,)).fetchall())
        index_db.save_snapshot(drive, u.used, u.total, bytype)


def start(mode, roots, skip, est_files=0):
    """Why: validate, then run the scan as a background job the UI can poll, pause, resume or cancel."""
    if jobs.running("scan"):
        raise ValueError("A scan is already running.")
    if mode not in ("quick", "deep"):
        raise BadRequest("Unknown scan mode. Use Quick Scan or Deep Scan.", "bad_mode")
    skipped = {}
    roots = clean_roots(quick_roots() if mode == "quick" and not roots else roots, skipped)
    skip = [canonical(s) for s in skip]
    job = jobs.Job("scan", total=int(est_files or 0), mode=mode, roots=roots, found=0, bytes=0, dirs=0, queued=0, noaccess=0,
                   unreadable=0, by_cat={}, recent=[], drive_stats={}, skipped=skipped, notes={}, errors_by_code={}, step="starting")
    CURRENT["job"] = job
    return jobs.start(job, _run, roots, skip)


# ---------------- estimate ----------------
def estimate(roots, seconds=config.ESTIMATE_BENCH_SECONDS):
    """Why: before scanning, a short files/second benchmark + used space gives an honest time range."""
    roots = clean_roots(roots, {})
    t0, files, nbytes, dirs = time.time(), 0, 0, 0
    stack, complete = list(roots), True
    while stack:
        if time.time() - t0 > seconds:
            complete = False
            break
        d = stack.pop()
        try:
            with os.scandir(long_path(d)) as it:
                for e in it:
                    try:
                        st = e.stat(follow_symlinks=False)
                        if is_reparse_or_link(st):
                            continue
                        if stat.S_ISDIR(st.st_mode):
                            path = os.path.join(d, e.name)
                            if not (e.name.startswith(".") or is_protected(path)):
                                stack.append(path)
                        elif stat.S_ISREG(st.st_mode):
                            files += 1
                            nbytes += st.st_size
                    except OSError:
                        continue
            dirs += 1
        except OSError:
            continue
    elapsed = max(time.time() - t0, 0.05)
    rate = files / elapsed
    if complete:
        est_files = files
    else:
        whole = [r for r in roots if os.path.dirname(r) == r]
        avg = nbytes / files if files else config.DEFAULT_AVG_FILE_BYTES
        used = sum(_used(r) for r in whole)
        est_files = max(files * (1 + len(stack) / max(dirs, 1)), used / max(avg, 1) if used else 0)
    scan_rate = max(rate * 0.8, 1.0)   # writing the index costs roughly a fifth of the walking speed
    secs = est_files / scan_rate
    return dict(files_per_s=round(rate), est_files=int(est_files), complete=complete, sample_files=files, sample_seconds=round(elapsed, 2),
                low_s=round(secs * config.ESTIMATE_LOW_FACTOR), high_s=round(max(secs * config.ESTIMATE_HIGH_FACTOR, 1)))


def _used(root):
    """Why: a drive unplugged during the estimate counts as empty instead of failing the request."""
    try:
        return shutil.disk_usage(root).used
    except OSError:
        return 0


def _blocked_hint():
    """Why: 'no permission' has a different fix on each OS; say the one that applies here."""
    if config.MAC:
        return ("mac_privacy", "macOS blocked access to these folders",
                "Open System Settings > Privacy & Security > Full Disk Access (or Files and Folders), allow Terminal (or the Python "
                "you started AuraSort with), quit and reopen it, then scan again.")
    if config.WIN:
        return ("windows_blocked", "Windows blocked access to these folders",
                "Check Windows Security > Virus & threat protection > Manage ransomware protection (Controlled Folder Access) and "
                "your antivirus: allow Python (python.exe / py.exe), then scan again. AuraSort does not need administrator rights.")
    if config.ANDROID:
        return ("android_storage", "Android did not allow access to your files",
                "Run termux-setup-storage in Termux, allow 'Files and media', then start AuraSort again.")
    return ("no_permission", "You do not have permission to read these folders",
            "Scan folders your user owns, or check the folder permissions (ls -ld <folder>).")


def explain(s):
    """Why: a scan that finds nothing, or nothing that can be sorted, says why and what to do: never just zeros."""
    sk, notes, found = s.get("skipped") or {}, s.get("notes") or {}, s.get("found", 0)
    out = []
    add = lambda code, title, body: out.append(dict(code=code, title=title, body=body))
    if not found:
        if sk.get("no_access"):
            add(*_blocked_hint())
        if sk.get("link"):
            add("links_only", "These folders hold links or junctions, not files",
                "AuraSort does not follow links (they can loop or point outside the folder). Add the real folder they point to.")
        if sk.get("protected"):
            add("protected_only", "Everything here is inside protected system or tool folders",
                "Folders such as AppData, node_modules or Program Files are never scanned. Pick a folder with your own files.")
        if sk.get("missing_root"):
            add("missing", "A folder to scan was not found", "It was moved, renamed, or its drive is unplugged. Add it again on the Scan page.")
        if sk.get("bad_name") or sk.get("unreadable") or sk.get("error"):
            add("unreadable", "Some folders could not be read", f"Details are in the log file: {config.LOG_FILE_SHOWN}. Run 'py server.py --doctor' for a full check.")
        if not out:
            moved = [q for q in quick_folders() if q["exists"] and q.get("onedrive")]
            body = "The folders were read, but they contain no files."
            if s.get("mode") == "quick" and moved:
                body += " Your " + ", ".join(q["name"] for q in moved) + " are in OneDrive: open Settings > Diagnostics to see exactly which folders Quick Scan used."
            add("empty", "No files were found", body + " If this is wrong, run 'py server.py --doctor' and send the result.")
    else:
        if notes.get("project", 0) >= found:
            add("all_project", "Every file was treated as part of a project folder",
                "A project marker (such as package.json, .git or a .sln file) was found in or above the scanned folders, so nothing is "
                "offered for sorting. Storage > Folders shows the folders and lets you include them.")
        if notes.get("online_only", 0) * 2 >= found:
            add("online_only", "Most files are online-only (OneDrive or iCloud)",
                "They are listed with their full size but take no space on this PC. AuraSort never downloads them; previews, checks and "
                "copies need them available offline first.")
    return out


def status():
    """Why: the scan screen polls this for live partial counts (files, folders, size, per-category, per-drive)."""
    job = CURRENT["job"]
    if not job:
        return dict(state="idle")
    snap = job.snapshot()
    ex = snap
    drives = []
    for d in ex.get("drive_stats", {}).values():
        pct = min(99.0, 100.0 * d["scanned"] / d["used"]) if d["used"] and d["whole"] else None
        drives.append(dict(root=d["root"], used=d["used"], scanned=d["scanned"], pct=100.0 if snap["state"] == "done" else pct))
    snap["drives"] = drives
    snap.pop("drive_stats", None)
    sk = snap.get("skipped") or {}
    snap["skipped_total"] = sum(sk.values())
    snap["skipped_reasons"] = [dict(code=k, label=config.SCAN_SKIP_REASONS.get(k, k), n=v) for k, v in sorted(sk.items(), key=lambda kv: -kv[1])]
    snap["notes_list"] = [dict(code=k, label=config.SCAN_NOTES.get(k, k), n=v) for k, v in sorted((snap.get("notes") or {}).items(), key=lambda kv: -kv[1])]
    if snap["state"] == "done":
        snap["explain"] = explain(snap)
        snap["pct"] = 100.0
    elif job.total:
        snap["pct"] = min(99.0, snap["pct"])
    else:
        q, d = ex.get("queued", 0), ex.get("dirs", 0)
        snap["pct"] = round(min(95.0, 100.0 * d / max(d + q, 1)), 1)
    return snap
