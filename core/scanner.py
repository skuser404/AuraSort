"""Scanning into the SQLite index. Quick Scan = usual user folders; Deep Scan = chosen drives/folders.

Runs on a background job with a small worker pool per drive (os.scandir, DirEntry.stat reused, links/junctions
skipped), live partial counters, pause/resume/cancel and a files/second ETA."""
import collections
import os
import queue
import shutil
import stat
import threading
import time

from . import classify, config, history, index_db, jobs, settings
from .log import log
from .platform_utils import created_time, drive_media, drive_of, is_hidden_system, is_reparse_or_link, quick_folders, within
from .safety import canonical, folder_kind, is_project, is_protected

_IGNORED_NAMES = config.IGNORED_FILE_NAMES
_IGNORED_PREFIXES = config.IGNORED_FILE_PREFIXES
PROJECT_LOOKUP_LEVELS = 30          # how far above a scan root we look for a project marker
QUEUE_POLL_S = 0.1
WRITER_FLUSH_S = 0.5
CURRENT = {"job": None}


# ---------------- validation ----------------
def clean_roots(roots):
    """Why: every root is resolved (8.3 names, links), must exist and must not be protected."""
    out = []
    for r in roots:
        r = canonical(r)
        if not os.path.isdir(r):
            raise ValueError("One of the folders to scan does not exist (or its drive is unplugged).")
        if is_protected(r):
            raise ValueError("One of the folders to scan is a protected system folder.")
        if not any(within(r, o) for o in out):
            out = [o for o in out if not within(o, r)] + [r]   # drop roots nested in other roots
    if not out:
        raise ValueError("Choose at least one folder or drive to scan.")
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
    """Why: a scan root inside a project (e.g. a website's assets folder) still belongs to that project."""
    p = os.path.dirname(root)
    for _ in range(PROJECT_LOOKUP_LEVELS):
        parent = os.path.dirname(p)
        if parent == p or os.path.normcase(p) in blocked:
            return None
        try:
            if is_project(set(os.listdir(p))):
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

    def __init__(self, job, skip, dest_roots):
        self.job, self.skip, self.dest_roots = job, [os.path.normcase(s) for s in skip], [os.path.normcase(d) for d in dest_roots]
        self.lock, self.sink = threading.Lock(), queue.Queue()
        self.queues, self.never_project = [], never_project()

    def skipped(self, path):
        p = os.path.normcase(path)
        return any(p == s or p.startswith(s.rstrip(os.sep) + os.sep) for s in self.skip)

    def kind_for(self, path, project):
        p = os.path.normcase(path)
        if any(p == d or p.startswith(d.rstrip(os.sep) + os.sep) for d in self.dest_roots):
            return "sorted"
        return folder_kind(path, 0 if project else -1)

    def count(self, path, files, nbytes, by_cat, drive):
        """Why: counters are updated once per folder (not per file) to keep lock traffic low."""
        ex = self.job.extra
        with self.lock:
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
        try:
            entries = list(os.scandir(d))
        except PermissionError:
            with self.lock:
                self.job.extra["noaccess"] += 1
            return
        except OSError:
            with self.lock:
                self.job.extra["unreadable"] += 1
            return
        if project is None and os.path.dirname(d) != d and os.path.normcase(d) not in self.never_project                 and is_project({e.name for e in entries}):
            project = d
        files, nsub, nbytes, by_cat = [], 0, 0, collections.Counter()
        for e in entries:
            try:
                st = e.stat(follow_symlinks=False)
                if is_reparse_or_link(st):
                    continue
                name = e.name
                if stat.S_ISDIR(st.st_mode):
                    nsub += 1
                    if name.lower().endswith(config.MAC_BUNDLE_EXTS):
                        files.append(self.bundle_row(e.path, name, st))
                        nbytes += files[-1][4]
                        by_cat[files[-1][2]] += 1
                    elif not (name.startswith(".") or is_hidden_system(st) or is_protected(e.path) or self.skipped(e.path)):
                        q.put((e.path, project))
                elif stat.S_ISREG(st.st_mode):
                    low = name.lower()
                    if low in _IGNORED_NAMES or low.startswith(_IGNORED_PREFIXES):
                        continue
                    ext, cat, sub = classify.classify(name)
                    flags = index_db.FLAG_PARTIAL if ext in config.PARTIAL_DOWNLOAD_EXTS else 0
                    if getattr(st, "st_file_attributes", 0) & config.CLOUD_ATTRS or getattr(st, "st_flags", 0) & config.MAC_DATALESS:
                        flags |= index_db.FLAG_CLOUD   # listed from metadata only; reading it would make OneDrive/iCloud download it
                    files.append((name, ext, cat, sub, st.st_size, st.st_mtime, created_time(st), st.st_atime, flags))
                    nbytes += st.st_size
                    by_cat[cat] += 1
            except OSError:
                continue
        self.sink.put((d, project, self.kind_for(d, project), drive, dev, nsub, files))
        self.count(d, files, nbytes, by_cat, drive)

    @staticmethod
    def bundle_row(path, name, st):
        """Why: macOS bundles (.app, .photoslibrary...) are one opaque item: listed with their total size, never opened."""
        total = 0
        for root, _, fs in os.walk(path):
            for f in fs:
                try:
                    total += os.lstat(os.path.join(root, f)).st_size
                except OSError:
                    pass
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
                    if not job._cancel:
                        job._run.wait()
                        if not job._cancel:
                            self.scan_dir(item, q, drive, dev)
                except Exception:  # noqa: BLE001 - one bad folder must not stop the scan
                    log.exception("scan: folder failed")
                finally:
                    q.task_done()
        media = drive_media(drive)
        self.job.extra.setdefault("media", {})[drive] = media
        threads = [threading.Thread(target=worker, daemon=True, name="scan-worker") for _ in range(config.SCAN_WORKERS.get(media, config.SCAN_WORKERS_PER_DRIVE))]
        for t in threads:
            t.start()
        q.join()
        stop.set()
        for t in threads:
            t.join()


def _writer(walk, scan_id, done_evt):
    """Why: one thread owns all SQLite writes for the scan (batched transactions)."""
    w = index_db.ScanWriter(scan_id)
    last = time.time()
    while True:
        try:
            item = walk.sink.get(timeout=QUEUE_POLL_S)
        except queue.Empty:
            if done_evt.is_set() and walk.sink.empty():
                break
            item = None
        with index_db.write_lock():
            if item:
                w.add(*item)
            if time.time() - last > WRITER_FLUSH_S:
                w.commit()
                last = time.time()
    with index_db.write_lock():
        w.commit()
    return w


def _run(job, roots, skip):
    """Why: the whole scan: group roots by drive, walk drives in parallel, write, prune, snapshot, log."""
    ex = job.extra
    scan_id = index_db.begin_scan(ex["mode"], roots)
    walk = _Walk(job, skip, settings.load()["dest_roots"])
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
    wt = threading.Thread(target=lambda: result.update(w=_writer(walk, scan_id, done_evt)), daemon=True, name="scan-writer")
    wt.start()
    walkers = [threading.Thread(target=walk.walk_drive, args=(rs, d), daemon=True, name="scan-drive") for d, rs in groups.items()]
    for t in walkers:
        t.start()
    for t in walkers:
        t.join()
    done_evt.set()
    wt.join()
    cancelled = job._cancel
    with index_db.write_lock():
        result["w"].finish(prune=not cancelled)
    state = "cancelled" if cancelled else "done"
    index_db.end_scan(scan_id, state, ex["found"], ex["bytes"], ex["noaccess"])
    if not cancelled:
        threading.Thread(target=_warm_caches, daemon=True, name="warm").start()
        _snapshots(groups)
        history.record("scan", mode=ex["mode"], count=ex["found"], size=ex["bytes"], roots=len(roots), noaccess=ex["noaccess"],
                       label="Quick Scan" if ex["mode"] == "quick" else "Deep Scan")
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
        raise ValueError("Unknown scan mode.")
    roots = clean_roots(quick_roots() if mode == "quick" and not roots else roots)
    skip = [canonical(s) for s in skip]
    job = jobs.Job("scan", total=int(est_files or 0), mode=mode, roots=roots, found=0, bytes=0, dirs=0, queued=0, noaccess=0,
                   unreadable=0, by_cat={}, recent=[], drive_stats={})
    CURRENT["job"] = job
    return jobs.start(job, _run, roots, skip)


# ---------------- estimate ----------------
def estimate(roots, seconds=config.ESTIMATE_BENCH_SECONDS):
    """Why: before scanning, a short files/second benchmark + used space gives an honest time range."""
    roots = clean_roots(roots)
    t0, files, nbytes, dirs = time.time(), 0, 0, 0
    stack, complete = list(roots), True
    while stack:
        if time.time() - t0 > seconds:
            complete = False
            break
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                for e in it:
                    try:
                        st = e.stat(follow_symlinks=False)
                        if is_reparse_or_link(st):
                            continue
                        if stat.S_ISDIR(st.st_mode):
                            if not (e.name.startswith(".") or is_protected(e.path)):
                                stack.append(e.path)
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
        used = sum(shutil.disk_usage(r).used for r in whole) if whole else 0
        est_files = max(files * (1 + len(stack) / max(dirs, 1)), used / max(avg, 1) if used else 0)
    scan_rate = max(rate * 0.8, 1.0)   # writing the index costs roughly a fifth of the walking speed
    secs = est_files / scan_rate
    return dict(files_per_s=round(rate), est_files=int(est_files), complete=complete, sample_files=files, sample_seconds=round(elapsed, 2),
                low_s=round(secs * config.ESTIMATE_LOW_FACTOR), high_s=round(max(secs * config.ESTIMATE_HIGH_FACTOR, 1)))


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
    if snap["state"] == "done":
        snap["pct"] = 100.0
    elif job.total:
        snap["pct"] = min(99.0, snap["pct"])
    else:
        q, d = ex.get("queued", 0), ex.get("dirs", 0)
        snap["pct"] = round(min(95.0, 100.0 * d / max(d + q, 1)), 1)
    return snap
