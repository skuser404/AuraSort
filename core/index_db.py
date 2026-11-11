"""SQLite index of scanned files (WAL mode): thread-local readers, one lock-guarded writer, server-side filtering."""
import json
import os
import sqlite3
import threading
import time
import unicodedata

from . import classify, config, dates
from .log import log
from .platform_utils import make_private

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS projects(id INTEGER PRIMARY KEY, path TEXT NOT NULL UNIQUE, seen INTEGER);
CREATE TABLE IF NOT EXISTS dirs(
  id INTEGER PRIMARY KEY, path TEXT NOT NULL UNIQUE, lpath TEXT NOT NULL, drive TEXT, dev INTEGER,
  project INTEGER NOT NULL DEFAULT -1, kind TEXT NOT NULL DEFAULT 'ok', included INTEGER NOT NULL DEFAULT 1,
  nfiles INTEGER NOT NULL DEFAULT 0, nsub INTEGER NOT NULL DEFAULT 0, seen INTEGER);
CREATE TABLE IF NOT EXISTS files(
  id INTEGER PRIMARY KEY, dir INTEGER NOT NULL, name TEXT NOT NULL, lname TEXT NOT NULL, ext TEXT NOT NULL,
  cat TEXT NOT NULL, sub TEXT NOT NULL, size INTEGER NOT NULL, mtime REAL NOT NULL, ctime REAL, atime REAL,
  flags INTEGER NOT NULL DEFAULT 0, seen INTEGER, UNIQUE(dir, name));
CREATE INDEX IF NOT EXISTS ix_files_cat_size ON files(cat, size);
CREATE INDEX IF NOT EXISTS ix_files_size ON files(size);
CREATE INDEX IF NOT EXISTS ix_files_ext ON files(ext);
CREATE INDEX IF NOT EXISTS ix_files_mtime ON files(mtime);
CREATE INDEX IF NOT EXISTS ix_files_ctime ON files(ctime);
CREATE INDEX IF NOT EXISTS ix_files_atime ON files(atime);
CREATE INDEX IF NOT EXISTS ix_files_lname ON files(lname);
CREATE INDEX IF NOT EXISTS ix_files_dir ON files(dir);
CREATE TABLE IF NOT EXISTS scans(id INTEGER PRIMARY KEY, started REAL, finished REAL, mode TEXT, roots TEXT, files INTEGER,
  bytes INTEGER, noaccess INTEGER, state TEXT);
CREATE TABLE IF NOT EXISTS snapshots(id INTEGER PRIMARY KEY, time REAL, drive TEXT, used INTEGER, total INTEGER, bytype TEXT);
CREATE TABLE IF NOT EXISTS integrity(file INTEGER PRIMARY KEY, size INTEGER, mtime REAL, mode TEXT, status TEXT, sev TEXT,
  code TEXT, findings TEXT, checked REAL);
CREATE TABLE IF NOT EXISTS hashes(file INTEGER PRIMARY KEY, size INTEGER, mtime REAL, part TEXT, full TEXT);
"""
FLAG_BUNDLE, FLAG_PARTIAL, FLAG_CLOUD = 1, 2, 4   # FLAG_CLOUD: an online-only placeholder (OneDrive/iCloud): never read, only listed
# Tie-breaks follow the index direction (indexes include the rowid), so SQLite walks an index instead of sorting 200k rows.
SORTS = {"size": "files.size DESC, files.id DESC", "name": "files.lname ASC, files.id ASC", "date": "files.{dcol} DESC, files.id DESC",
         "oldest": "files.{dcol} ASC, files.id ASC", "smallest": "files.size ASC, files.id ASC"}
FILE_COLS = ("files.id, files.name, files.ext, files.cat, files.sub, files.size, files.mtime, files.ctime, files.atime, files.flags, "
             "files.dir, dirs.path, dirs.kind, dirs.project, dirs.included, dirs.drive")
MAX_IDS_PARAM = 50000

_local = threading.local()
_write_lock = threading.RLock()
_writer = {}
_cache = {}
_state = dict(version=0)


def norm_lower(name):
    """Why: search and sorting use one canonical form (Unicode NFC, lower case); the original name stays on disk."""
    return unicodedata.normalize("NFC", name).lower()


SCHEMA_VERSION = 2          # PRAGMA user_version: 0 = 1.0.0 (no version yet), 2 = this layout
JOURNAL = {"mode": ""}      # the journal mode actually in use (shown by --doctor)


def _connect():
    """Why: WAL lets the UI read while a scan writes; NORMAL sync is safe in WAL and much faster. Some folders (network
    shares, a few sync tools) cannot do WAL: SQLite then keeps its normal journal, which is slower but correct."""
    conn = sqlite3.connect(str(config.INDEX_DB), timeout=30, check_same_thread=False)
    try:
        mode = str(conn.execute("PRAGMA journal_mode=WAL").fetchone()[0]).lower()
        if mode != "wal" and JOURNAL["mode"] != mode:
            log.warning("the file index cannot use WAL in this folder; using journal mode %r instead (slower, still safe)", mode)
        JOURNAL["mode"] = mode
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.execute("PRAGMA cache_size=-32000")
    except sqlite3.Error:
        conn.close()                   # a damaged file must not stay open (Windows could not rename or delete it)
        raise
    return conn


# Tables the next scan rebuilds completely; an outdated one is recreated. The others (scan list, storage trend) are kept.
REBUILDABLE = ("files", "dirs", "projects", "integrity", "hashes")


def expected_columns():
    """Why: the schema text is the single source of truth; compare against it instead of a second hand-written list."""
    m = sqlite3.connect(":memory:")
    try:
        m.executescript(SCHEMA)
        tables = [t for (t,) in m.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        return {t: [(r[1], r[2]) for r in m.execute(f"PRAGMA table_info({t})")] for t in tables}  # nosec B608  # names come from our own schema
    finally:
        m.close()


def migrate(c):
    """Why: an index written by an earlier version can lack columns (e.g. 'lpath'); writing to it would fail in the middle of a
    scan. Outdated index tables are recreated (the scan refills them); other tables get the missing columns added."""
    have = {t for (t,) in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    changed, rebuild = [], False
    for table, cols in expected_columns().items():
        if table not in have:
            continue
        current = {r[1] for r in c.execute(f"PRAGMA table_info({table})")}  # nosec B608  # table names come from our own schema
        missing = [(n, t) for n, t in cols if n not in current]
        if not missing:
            continue
        changed.append(table)
        if table in REBUILDABLE:
            rebuild = True
        else:
            for name, typ in missing:
                c.execute(f"ALTER TABLE {table} ADD COLUMN {name} {typ}")  # nosec B608  # identifiers come from our own schema
    if rebuild:
        for table in REBUILDABLE:
            c.execute(f"DROP TABLE IF EXISTS {table}")  # nosec B608  # fixed tuple above
    if changed:
        c.commit()
        log.warning("index from an earlier version updated (%s)%s", ", ".join(changed), "; run a scan to rebuild it" if rebuild else "")
    return changed


def _set_aside_broken():
    """Why: a damaged index file (not a database at all) would stop every scan; it is only a cache, so it is renamed and rebuilt."""
    _writer.clear()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    for suffix in ("", "-wal", "-shm"):
        p = str(config.INDEX_DB) + suffix
        if os.path.exists(p):
            os.replace(p, f"{config.INDEX_DB}.broken-{stamp}{suffix}")
    log.warning("the file index was damaged; it was renamed to index.sqlite3.broken-%s and a new one was created", stamp)


def _upgrade(w):
    """Why: the stored schema version says whether this index came from an older AuraSort; migrate it, then stamp it."""
    have = w.execute("PRAGMA user_version").fetchone()[0]
    if have > SCHEMA_VERSION:
        log.warning("the file index was written by a newer AuraSort (schema %s); it is rebuilt by the next scan", have)
        for table in REBUILDABLE:
            w.execute(f"DROP TABLE IF EXISTS {table}")  # nosec B608  # fixed tuple
    elif have < SCHEMA_VERSION:
        migrate(w)
    w.executescript(SCHEMA)
    w.execute(f"PRAGMA user_version={SCHEMA_VERSION}")  # nosec B608  # an int constant


def init():
    """Why: create (or update) the schema once and keep the database (and its WAL files) readable by the user only.
    If an old or damaged index cannot be upgraded it is set aside and rebuilt: it only caches what a scan can re-read."""
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    fresh = not config.INDEX_DB.exists()
    with _write_lock:
        try:
            w = writer()
            _upgrade(w)
        except sqlite3.DatabaseError as ex:
            if any(w in str(ex).lower() for w in ("locked", "busy", "readonly", "disk i/o", "unable to open")):
                raise                          # a busy or unwritable index is not damaged: never set a good one aside
            log.warning("the file index could not be opened or upgraded (%s: %s); setting it aside", type(ex).__name__, ex)
            close_all()                    # Windows can't rename a file this process still has open
            _set_aside_broken()
            fresh = True
            w = writer()
            _upgrade(w)
        w.commit()
    if fresh:
        for suffix in ("", "-wal", "-shm"):
            p = str(config.INDEX_DB) + suffix
            if os.path.exists(p):
                make_private(p, is_dir=False)
    bump()


def reader():
    """Why: one connection per request thread; reconnect if the database file changed (tests switch homes)."""
    key = str(config.INDEX_DB)
    if getattr(_local, "key", None) != key:
        _local.conn, _local.key = _connect(), key
    return _local.conn


def writer():
    """Why: SQLite allows one writer; callers hold _write_lock while using it."""
    key = str(config.INDEX_DB)
    if key not in _writer:
        _writer.clear()
        _writer[key] = _connect()
    return _writer[key]


def write_lock():
    """Why: scanner, mover and the include/exclude toggles all write; they must take turns."""
    return _write_lock


def close_all():
    """Why: tests delete their temp folders; open handles would block that on Windows."""
    for c in _writer.values():
        c.close()
    _writer.clear()
    if getattr(_local, "conn", None):
        _local.conn.close()
        _local.conn, _local.key = None, None


WIPE_TABLES = ("files", "dirs", "projects", "scans", "snapshots", "integrity", "hashes", "meta")


def wipe():
    """Why: 'Delete my AuraSort data' empties the index in place, then VACUUM and a truncating WAL checkpoint remove the
    old pages from the file, so nothing about your files is left in it."""
    with _write_lock:
        c = writer()
        for t in WIPE_TABLES:
            c.execute(f"DELETE FROM {t}")  # nosec B608  # table names come from the fixed tuple above
        c.commit()
        try:
            c.execute("VACUUM")
            c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.OperationalError:
            pass   # a reader is busy: the rows are already gone; free pages are reused and cleared on the next scan
    bump()


def bump():
    """Why: cached summaries and the search index are keyed by a version that changes on every write."""
    _state["version"] += 1
    _cache.clear()


def version():
    return _state["version"]


CACHE_MAX = 256


def cached(key, fn):
    """Why: summary, extensions, counts, facets and the search index are expensive on 200k files but change only after writes."""
    v = _state["version"]
    hit = _cache.get(key)
    if hit and hit[0] == v:
        return hit[1]
    val = fn()
    if len(_cache) > CACHE_MAX:
        _cache.clear()
    _cache[key] = (v, val)
    return val


# ---------------- writing (scanner) ----------------
class ScanWriter:
    """Why: the scanner's single writer thread batches dir/file upserts; ids stay stable across re-scans."""

    def __init__(self, scan_id):
        self.scan_id, self.conn = scan_id, writer()
        self.proj_ids, self.pending = {}, 0

    def project(self, path):
        if path is None:
            return -1
        if path not in self.proj_ids:
            self.conn.execute("INSERT INTO projects(path, seen) VALUES(?, ?) ON CONFLICT(path) DO UPDATE SET seen=excluded.seen",
                              (path, self.scan_id))
            self.proj_ids[path] = self.conn.execute("SELECT id FROM projects WHERE path=?", (path,)).fetchone()[0]
        return self.proj_ids[path]

    def add(self, path, project_path, kind, drive, dev, nsub, files):
        """files: list of (name, ext, cat, sub, size, mtime, ctime, atime, flags)."""
        proj = self.project(project_path)
        included = 1 if kind == "ok" else 0
        self.conn.execute(
            "INSERT INTO dirs(path, lpath, drive, dev, project, kind, included, nfiles, nsub, seen) VALUES(?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(path) DO UPDATE SET lpath=excluded.lpath, drive=excluded.drive, dev=excluded.dev, project=excluded.project, "
            "included=CASE WHEN dirs.kind=excluded.kind THEN dirs.included ELSE excluded.included END, kind=excluded.kind, "
            "nfiles=excluded.nfiles, nsub=excluded.nsub, seen=excluded.seen",
            (path, norm_lower(path), drive, dev, proj, kind, included, len(files), nsub, self.scan_id))
        did = self.conn.execute("SELECT id FROM dirs WHERE path=?", (path,)).fetchone()[0]
        if files:
            self.conn.executemany(
                "INSERT INTO files(dir, name, lname, ext, cat, sub, size, mtime, ctime, atime, flags, seen) VALUES(?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(dir, name) DO UPDATE SET lname=excluded.lname, ext=excluded.ext, cat=excluded.cat, sub=excluded.sub, "
                "size=excluded.size, mtime=excluded.mtime, ctime=excluded.ctime, atime=excluded.atime, flags=excluded.flags, seen=excluded.seen",
                [(did, n, norm_lower(n), e, c, s, sz, mt, ct, at, fl, self.scan_id) for n, e, c, s, sz, mt, ct, at, fl in files])
        self.pending += len(files) + 1
        if self.pending >= config.SCAN_BATCH_ROWS:
            self.commit()

    def commit(self):
        self.conn.commit()
        self.pending = 0

    def finish(self, prune):
        """Why: a completed scan replaces the index (rows not seen are removed); a cancelled scan keeps old rows."""
        c = self.conn
        if prune:
            sid = self.scan_id
            c.execute("DELETE FROM files WHERE seen IS NOT ?", (sid,))
            c.execute("DELETE FROM dirs WHERE seen IS NOT ?", (sid,))
            c.execute("DELETE FROM projects WHERE seen IS NOT ?", (sid,))
            c.execute("DELETE FROM integrity WHERE file NOT IN (SELECT id FROM files)")
            c.execute("DELETE FROM hashes WHERE file NOT IN (SELECT id FROM files)")
        orphans = c.execute("DELETE FROM files WHERE dir NOT IN (SELECT id FROM dirs)").rowcount   # rows no list could show
        if orphans:
            log.error("the file index had %s file rows without a folder; they were removed", orphans)
        c.commit()
        c.execute("ANALYZE")   # fresh statistics so the planner picks the right index on large indexes
        c.commit()
        bump()


def begin_scan(mode, roots):
    """Why: every scan gets an id; rows are tagged with it so stale rows can be pruned afterwards."""
    with _write_lock:
        c = writer()
        cur = c.execute("INSERT INTO scans(started, mode, roots, state) VALUES(?,?,?,?)", (time.time(), mode, json.dumps(roots), "running"))
        c.commit()
        return cur.lastrowid


def end_scan(scan_id, state, files, nbytes, noaccess):
    with _write_lock:
        c = writer()
        c.execute("UPDATE scans SET finished=?, state=?, files=?, bytes=?, noaccess=? WHERE id=?",
                  (time.time(), state, files, nbytes, noaccess, scan_id))
        c.commit()


def last_scan():
    """Why: the dashboard says when and how the index was built (and whether one exists at all)."""
    row = reader().execute("SELECT id, started, finished, mode, roots, files, bytes, noaccess, state FROM scans "
                           "WHERE state='done' ORDER BY id DESC LIMIT 1").fetchone()
    if not row:
        return None
    keys = ("id", "started", "finished", "mode", "roots", "files", "bytes", "noaccess", "state")
    d = dict(zip(keys, row))
    d["roots"] = json.loads(d["roots"] or "[]")
    return d


def save_snapshot(drive, used, total, bytype):
    """Why: the storage trend chart is built from one snapshot per drive after each scan."""
    with _write_lock:
        c = writer()
        c.execute("INSERT INTO snapshots(time, drive, used, total, bytype) VALUES(?,?,?,?,?)", (time.time(), drive, used, total, json.dumps(bytype)))
        c.commit()


# ---------------- filters ----------------
def _like(text):
    """Why: user text inside LIKE must not act as a wildcard."""
    return "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def where(f):
    """Why: one place turns a validated filter dict into SQL (always parameterised; column names come from allow-lists)."""
    w, a = [], []
    if f.get("cat"):
        w.append("files.cat = ?")
        a.append(f["cat"])
    if f.get("cats"):
        w.append(f"files.cat IN ({','.join('?' * len(f['cats']))})")
        a += list(f["cats"])
    if f.get("exts"):
        w.append(f"files.ext IN ({','.join('?' * len(f['exts']))})")
        a += list(f["exts"])
    if f.get("folder"):   # sub-queries keep every filter on 'files' alone (no per-row join)
        w.append("files.dir IN (SELECT id FROM dirs WHERE lpath LIKE ? ESCAPE '\\')")
        a.append(_like(norm_lower(f["folder"])))
    if f.get("dir") is not None:
        w.append("files.dir = ?")
        a.append(int(f["dir"]))
    for tok in (f.get("q") or "").split():
        w.append("files.lname LIKE ? ESCAPE '\\'")
        a.append(_like(norm_lower(tok)))
    if f.get("dfrom") is not None and f.get("dto") is not None:
        col = dates.field_column(f.get("dfield"))
        w.append(f"files.{col} >= ? AND files.{col} < ?")
        a += [float(f["dfrom"]), float(f["dto"])]
    if f.get("ids") is not None:
        ids = [int(i) for i in f["ids"]][:MAX_IDS_PARAM]
        w.append(f"files.id IN ({','.join('?' * len(ids)) or 'NULL'})")
        a += ids
    if f.get("minsize"):
        w.append("files.size >= ?")
        a.append(int(f["minsize"]))
    scope = f.get("scope", "all")
    if scope in ("ready", "included"):
        w.append("files.dir IN (SELECT id FROM dirs WHERE included = 1)")
    if scope == "ready":
        movable = sorted(classify.MOVABLE | set(f.get("optin") or ()))
        w.append(f"files.cat IN ({','.join('?' * len(movable))})")
        a += movable
    if f.get("problems"):
        w.append("files.id IN (SELECT file FROM integrity WHERE status='problem')")
    return (" WHERE " + " AND ".join(w)) if w else "", a


def _row(r):
    """Why: one JSON shape for every file row the UI shows."""
    (fid, name, ext, cat, sub, size, mtime, ctime, atime, flags, did, dpath, kind, proj, inc, drive) = r
    return dict(id=fid, name=name, ext=ext, cat=cat, sub=sub, size=size, mtime=mtime, ctime=ctime, atime=atime, flags=flags,
                dir=did, path=dpath, kind=kind, project=proj, included=bool(inc), drive=drive, viewonly=classify.is_view_only(cat))


def _fkey(f):
    """Why: cache key for the counts/facets of one filter (cleared whenever the index changes)."""
    return json.dumps({k: (sorted(v) if isinstance(v, (list, set, tuple)) else v) for k, v in f.items()}, sort_keys=True, default=str)


def count(f):
    """Why: total files and bytes for a filter, on 'files' alone (no join) and cached per index version."""
    def build():
        w, a = where(f)
        return tuple(reader().execute(f"SELECT COUNT(*), COALESCE(SUM(files.size),0) FROM files{w}", a).fetchone())  # nosec B608  # values are ? parameters; identifiers come from allow-lists
    return cached("count:" + _fkey(f), build)


def files_page(f, sort="size", page=1, per=config.PAGE_SIZE):
    """Why: server-side filter + sort + pagination, so the browser never receives 200k records.
    The page's ids come from an index walk on 'files'; folder details are joined for those rows only."""
    w, a = where(f)
    total, size = count(f)
    pages = max(1, -(-total // per))
    page = min(max(1, int(page)), pages)
    order = SORTS.get(sort, SORTS["size"]).format(dcol=dates.field_column(f.get("dfield")))
    ids = [r[0] for r in reader().execute(f"SELECT files.id FROM files{w} ORDER BY {order} LIMIT ? OFFSET ?", a + [per, (page - 1) * per])]  # nosec B608  # values are ? parameters; identifiers come from allow-lists
    return dict(total=total, size=size, page=page, pages=pages, per=per, rows=rows_by_ids(ids))


def facets(f):
    """Why: format chips and category counts reflect every filter except their own (cached per index version)."""
    def build():
        db = reader()
        w, a = where({k: v for k, v in f.items() if k != "exts"})
        exts = db.execute(f"SELECT files.ext, COUNT(*) FROM files{w} GROUP BY files.ext ORDER BY 2 DESC", a).fetchall()  # nosec B608  # values are ? parameters; identifiers come from allow-lists
        w, a = where({k: v for k, v in f.items() if k not in ("cat", "cats")})
        cats = db.execute(f"SELECT files.cat, COUNT(*), COALESCE(SUM(files.size),0) FROM files{w} GROUP BY files.cat", a).fetchall()  # nosec B608  # values are ? parameters; identifiers come from allow-lists
        return dict(ext=[[e, n] for e, n in exts], cat={c: dict(n=n, size=s) for c, n, s in cats})
    return cached("facets:" + _fkey(f), build)


def ids_for(f, limit=None):
    """Why: 'Select all N matching' and filter-based actions resolve to explicit ids (with their sizes) on the server."""
    w, a = where(f)
    q = f"SELECT files.id, files.size FROM files{w} ORDER BY files.id"  # nosec B608  # values are ? parameters; identifiers come from allow-lists
    rows = reader().execute(q + (" LIMIT ?" if limit else ""), a + ([int(limit)] if limit else [])).fetchall()
    return [r[0] for r in rows], [r[1] for r in rows]


DATE_GROUPS = {"day": "%Y-%m-%d", "month": "%Y-%m"}


def _date_rows(f, group):
    """Why: the calendar and the timeline group files by local day or month in one SQL pass."""
    col = dates.field_column(f.get("dfield"))
    w, a = where(f)
    w += (" AND" if w else " WHERE") + f" files.{col} > 0"
    sql = (f"SELECT strftime('{DATE_GROUPS[group]}', files.{col}, 'unixepoch', 'localtime') AS k, COUNT(*), "  # nosec B608  # values are ? parameters; identifiers come from allow-lists
           f"COALESCE(SUM(files.size), 0) FROM files{w} GROUP BY k ORDER BY k")
    return [[k, n, s] for k, n, s in reader().execute(sql, a) if k]


def calendar(f, year):
    """Why: files per local calendar day of one year, for the heatmap (cached per index version)."""
    g = {k: v for k, v in f.items() if k not in ("dfrom", "dto")}
    g["dfrom"], g["dto"] = dates.range_for("year", str(int(year)))
    return cached("calendar:" + _fkey(g), lambda: dict(year=int(year), days=_date_rows(g, "day")))


def timeline(f):
    """Why: files per month across every year, for the timeline bars (cached per index version)."""
    g = {k: v for k, v in f.items() if k not in ("dfrom", "dto")}
    return cached("timeline:" + _fkey(g), lambda: dict(months=_date_rows(g, "month")))


SQL_VARS = 900   # ids per IN (...) query (SQLite's parameter limit is 999 on older builds)


def selection_stats(ids):
    """Why: confirmation dialogs show exactly what a selection holds, grouped by type, folder kind and drive."""
    ids = sorted({int(i) for i in ids})
    db, groups, found = reader(), {}, 0
    for i in range(0, len(ids), SQL_VARS):
        part = ids[i:i + SQL_VARS]
        for cat, kind, drive, n, s in db.execute(
                "SELECT files.cat, dirs.kind, COALESCE(dirs.drive, ''), COUNT(*), COALESCE(SUM(files.size), 0) FROM files "  # nosec B608  # values are ? parameters; identifiers come from allow-lists
                f"JOIN dirs ON dirs.id=files.dir WHERE files.id IN ({','.join('?' * len(part))}) GROUP BY 1, 2, 3", part):
            g = groups.setdefault((cat, kind, drive), [0, 0])
            g[0] += n
            g[1] += s
            found += n
    rows = [[c, k, d, n, s] for (c, k, d), (n, s) in sorted(groups.items())]
    return dict(n=found, size=sum(r[4] for r in rows), groups=rows, missing=len(ids) - found)


def file_by_id(fid):
    """Why: every action resolves ids through the index, never through paths from the browser."""
    r = reader().execute(f"SELECT {FILE_COLS} FROM files JOIN dirs ON dirs.id=files.dir WHERE files.id=?", (int(fid),)).fetchone()  # nosec B608  # values are ? parameters; identifiers come from allow-lists
    return _row(r) if r else None


def rows_by_ids(ids):
    """Why: search results arrive from the worker as ranked ids; rows keep that order."""
    ids = [int(i) for i in ids][:MAX_IDS_PARAM]
    if not ids:
        return []
    rows = reader().execute(f"SELECT {FILE_COLS} FROM files JOIN dirs ON dirs.id=files.dir WHERE files.id IN ({','.join('?' * len(ids))})", ids).fetchall()  # nosec B608  # values are ? parameters; identifiers come from allow-lists
    by = {r[0]: _row(r) for r in rows}
    return [by[i] for i in ids if i in by]


def extensions():
    """Why: the 'All extensions' page lists every extension with count, size and category. disk_size leaves out
    online-only files: they take no space on this PC, so counting them made '% of disk' go past 100%."""
    def build():
        rows = reader().execute(f"SELECT ext, cat, COUNT(*), SUM(size), SUM(CASE WHEN flags & {FLAG_CLOUD} THEN 0 ELSE size END) "  # nosec B608  # an int constant
                                "FROM files GROUP BY ext, cat ORDER BY 4 DESC").fetchall()
        return [dict(ext=e, cat=c, n=n, size=s or 0, disk_size=d or 0) for e, c, n, s, d in rows]
    return cached("extensions", build)


def consistency():
    """Why: every number on screen must come from the same rows. Totals, category badges and lists are compared; a
    difference is logged as an error and shown as 'refresh data' instead of silently wrong numbers."""
    def build():
        db = reader()
        files = db.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        joined = db.execute("SELECT COUNT(*) FROM files JOIN dirs ON dirs.id=files.dir").fetchone()[0]
        by_cat = dict(db.execute("SELECT cat, COUNT(*) FROM files JOIN dirs ON dirs.id=files.dir GROUP BY cat").fetchall())
        unknown = sum(n for c, n in by_cat.items() if c not in classify.CATEGORY_NAMES)
        ok = files == joined == sum(by_cat.values()) and not unknown
        if not ok:
            log.error("index numbers disagree: %s file rows, %s with a folder, %s by category, %s in unknown categories", files, joined, sum(by_cat.values()), unknown)
        return dict(ok=ok, files=files, with_folder=joined, by_category=sum(by_cat.values()), unknown_category=unknown)
    return cached("consistency", build)


def summary():
    """Why: the dashboard's numbers (all real) in one cached query set."""
    def build():
        db = reader()
        by = {c: dict(n=0, size=0, ready=0, ready_size=0, disk_size=0) for c in classify.CATEGORY_NAMES}
        for cat, n, size, rn, rs, ds in db.execute(
                "SELECT files.cat, COUNT(*), SUM(files.size), SUM(dirs.included), SUM(CASE WHEN dirs.included=1 THEN files.size ELSE 0 END), "
                f"SUM(CASE WHEN files.flags & {FLAG_CLOUD} THEN 0 ELSE files.size END) "  # nosec B608  # an int constant
                "FROM files JOIN dirs ON dirs.id=files.dir GROUP BY files.cat"):
            movable = cat in classify.MOVABLE
            by.setdefault(cat, dict(n=0, size=0, ready=0, ready_size=0, disk_size=0)).update(
                n=n, size=size or 0, ready=(rn or 0) if movable else 0, ready_size=(rs or 0) if movable else 0, disk_size=ds or 0)
        total = sum(v["n"] for v in by.values())
        cloud_n, cloud_size = db.execute(f"SELECT COUNT(*), COALESCE(SUM(size), 0) FROM files WHERE flags & {FLAG_CLOUD}").fetchone()  # nosec B608  # an int constant
        projects = [dict(path=p, n=n, size=s or 0) for p, n, s in db.execute(
            "SELECT projects.path, COUNT(files.id), SUM(files.size) FROM projects JOIN dirs ON dirs.project=projects.id "
            "JOIN files ON files.dir=dirs.id GROUP BY projects.id ORDER BY 2 DESC LIMIT 50")]
        big_dirs = [dict(id=i, path=p, n=n, size=s, kind=k) for i, p, k, n, s in db.execute(
            "SELECT dirs.id, dirs.path, dirs.kind, COUNT(*), SUM(files.size) FROM files JOIN dirs ON dirs.id=files.dir "
            "GROUP BY dirs.id ORDER BY 5 DESC LIMIT ?", (config.BIGGEST_N,))]
        big_files = [_row(r) for r in db.execute(f"SELECT {FILE_COLS} FROM files JOIN dirs ON dirs.id=files.dir ORDER BY files.size DESC LIMIT ?",  # nosec B608  # values are ? parameters; identifiers come from allow-lists
                                                 (config.BIGGEST_N,))]
        kinds = dict(db.execute("SELECT kind, COUNT(*) FROM dirs WHERE nfiles > 0 GROUP BY kind").fetchall())
        samples = {c: [r[0] for r in db.execute("SELECT name FROM files WHERE cat=? ORDER BY size DESC LIMIT ?", (c, SAMPLE_NAMES))]
                   for c in SCENE_CATS}   # real names for the dashboard scene (names only, no paths)
        ready = sum(v["ready"] for v in by.values())
        return dict(version=version(), scan=last_scan(), by_cat=by, total=total, total_size=sum(v["size"] for v in by.values()),
                    disk_size=sum(v["disk_size"] for v in by.values()), cloud_n=cloud_n, cloud_size=cloud_size, consistent=consistency()["ok"],
                    ready=ready, ready_size=sum(v["ready_size"] for v in by.values()), left_alone=total - ready,
                    projects=projects, project_count=kinds.get("project", 0), asset_dirs=kinds.get("assets", 0),
                    biggest_folders=big_dirs, biggest_files=big_files, samples=samples)
    return cached("summary", build)


SCENE_CATS = ("Images", "Videos", "Audio", "Documents", "PDFs", "Archives")   # the folder tabs in the dashboard scene
SAMPLE_NAMES = 4


def folders(q="", cat="", kind="all"):
    """Why: 'Review folders' lists every folder that holds files, with counts per category and its include state."""
    db = reader()
    w, a = ["dirs.nfiles > 0"], []
    if q:
        w.append("dirs.lpath LIKE ? ESCAPE '\\'")
        a.append(_like(norm_lower(q)))
    if kind == "warn":
        w.append("dirs.kind != 'ok'")
    rows = db.execute("SELECT dirs.id, dirs.path, dirs.kind, dirs.project, dirs.included, files.cat, COUNT(*), SUM(files.size) "  # nosec B608  # values are ? parameters; identifiers come from allow-lists
                      f"FROM dirs JOIN files ON files.dir=dirs.id WHERE {' AND '.join(w)} GROUP BY dirs.id, files.cat", a).fetchall()
    out = {}
    for did, path, k, proj, inc, c, n, s in rows:
        d = out.setdefault(did, dict(id=did, path=path, kind=k, project=proj, included=bool(inc), n=0, size=0, by={}))
        d["n"] += n
        d["size"] += s
        d["by"][c] = n
    res = [d for d in out.values() if not cat or cat in d["by"]]
    res.sort(key=lambda d: -d["n"])
    proj_paths = dict(db.execute("SELECT id, path FROM projects").fetchall())
    for d in res:
        d["project_path"] = proj_paths.get(d["project"], "")
    return res


def set_included(ids=None, preset=None, value=True):
    """Why: ticking/unticking folders decides what 'ready to sort' means; presets reset to safe defaults."""
    with _write_lock:
        c = writer()
        if preset == "safe":
            c.execute("UPDATE dirs SET included = CASE WHEN kind='ok' THEN 1 ELSE 0 END")
        elif preset == "none":
            c.execute("UPDATE dirs SET included = 0")
        elif preset == "all":
            c.execute("UPDATE dirs SET included = 1")
        elif ids:
            ids = [int(i) for i in ids][:MAX_IDS_PARAM]
            c.execute(f"UPDATE dirs SET included=? WHERE id IN ({','.join('?' * len(ids))})", [1 if value else 0] + ids)  # nosec B608  # values are ? parameters; identifiers come from allow-lists
        c.commit()
    bump()


def search_index():
    """Why: the browser's search worker needs names + a few columns (not full records) to rank fuzzy matches instantly."""
    def build():
        db = reader()
        dirs = db.execute("SELECT id, path, kind, included FROM dirs WHERE nfiles > 0 ORDER BY id").fetchall()
        dpos = {d[0]: i for i, d in enumerate(dirs)}
        exts, epos = [], {}
        cats = list(classify.CATEGORY_NAMES)
        cpos = {c: i for i, c in enumerate(cats)}
        cols = dict(id=[], name=[], cat=[], ext=[], dir=[], size=[], mtime=[], ctime=[], atime=[])
        for fid, name, ext, cat, size, mt, ct, at, did in db.execute(
                "SELECT id, name, ext, cat, size, mtime, ctime, atime, dir FROM files ORDER BY id"):
            if ext not in epos:
                epos[ext] = len(exts)
                exts.append(ext)
            cols["id"].append(fid)
            cols["name"].append(unicodedata.normalize("NFC", name))
            cols["cat"].append(cpos.get(cat, len(cats) - 1))
            cols["ext"].append(epos[ext])
            cols["dir"].append(dpos.get(did, -1))
            cols["size"].append(size)
            cols["mtime"].append(int(mt))
            cols["ctime"].append(int(ct) if ct else 0)
            cols["atime"].append(int(at) if at else 0)
        payload = dict(version=version(), cats=cats, exts=exts, dirs=[d[1] for d in dirs], dir_id=[d[0] for d in dirs],
                       dir_kind=[d[2] for d in dirs], dir_inc=[d[3] for d in dirs], **cols)
        return json.dumps(payload, separators=(",", ":")).encode()
    return cached("search_index", build)


# ---------------- updates after actions (lists stay correct without a rescan) ----------------
LISTENERS = []   # called with [file ids] whenever files are moved away or removed (Document Insights forgets their results)


def _notify(fids):
    for fn in LISTENERS:
        fn(list(fids))

def _ensure_dir(c, path, kind):
    """Why: files moved into a new folder need that folder in the index (destinations start unticked: 'sorted')."""
    from .platform_utils import drive_of
    row = c.execute("SELECT id FROM dirs WHERE path=?", (path,)).fetchone()
    if row:
        return row[0]
    try:
        dev = os.stat(path).st_dev
    except OSError:
        dev = None
    seen = c.execute("SELECT MAX(id) FROM scans").fetchone()[0]
    cur = c.execute("INSERT INTO dirs(path, lpath, drive, dev, project, kind, included, nfiles, nsub, seen) VALUES(?,?,?,?,-1,?,?,0,0,?)",
                    (path, norm_lower(path), drive_of(path), dev, kind, 1 if kind == "ok" else 0, seen))
    return cur.lastrowid


def record_move(fid, new_path, kind="sorted"):
    """Why: after a move the file keeps its id but points at its new folder and name."""
    with _write_lock:
        c = writer()
        old = c.execute("SELECT dir FROM files WHERE id=?", (int(fid),)).fetchone()
        if not old:
            return
        did = _ensure_dir(c, os.path.dirname(new_path), kind)
        name = os.path.basename(new_path)
        c.execute("UPDATE files SET dir=?, name=?, lname=? WHERE id=?", (did, name, norm_lower(name), int(fid)))
        c.execute("UPDATE dirs SET nfiles = nfiles - 1 WHERE id=?", (old[0],))
        c.execute("UPDATE dirs SET nfiles = nfiles + 1 WHERE id=?", (did,))
        c.commit()
    bump()
    _notify([fid])


def record_copy(fid, new_path, kind="sorted"):
    """Why: a copy is a new file on disk, so it gets its own row (and id) in the index."""
    with _write_lock:
        c = writer()
        src = c.execute("SELECT ext, cat, sub, size, mtime, ctime, atime, flags, seen FROM files WHERE id=?", (int(fid),)).fetchone()
        if not src:
            return
        did = _ensure_dir(c, os.path.dirname(new_path), kind)
        name = os.path.basename(new_path)
        c.execute("INSERT OR IGNORE INTO files(dir, name, lname, ext, cat, sub, size, mtime, ctime, atime, flags, seen) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                  (did, name, norm_lower(name)) + tuple(src))
        c.execute("UPDATE dirs SET nfiles = nfiles + 1 WHERE id=?", (did,))
        c.commit()
    bump()


def record_removed(fids):
    """Why: files sent to the Recycle Bin disappear from every list immediately."""
    fids = [int(i) for i in fids]
    if not fids:
        return
    with _write_lock:
        c = writer()
        for i in range(0, len(fids), 900):
            part = fids[i:i + 900]
            marks = ",".join("?" * len(part))
            c.execute(f"UPDATE dirs SET nfiles = nfiles - (SELECT COUNT(*) FROM files WHERE files.dir = dirs.id AND files.id IN ({marks})) "  # nosec B608  # values are ? parameters; identifiers come from allow-lists
                      f"WHERE id IN (SELECT dir FROM files WHERE id IN ({marks}))", part + part)
            c.execute(f"DELETE FROM files WHERE id IN ({marks})", part)  # nosec B608  # values are ? parameters; identifiers come from allow-lists
            c.execute(f"DELETE FROM integrity WHERE file IN ({marks})", part)  # nosec B608  # values are ? parameters; identifiers come from allow-lists
            c.execute(f"DELETE FROM hashes WHERE file IN ({marks})", part)  # nosec B608  # values are ? parameters; identifiers come from allow-lists
        c.commit()
    bump()
    _notify(fids)


def plan(f, dest_dev=None):
    """Why: the move preview (counts per category/sub-folder, source folders, cross-drive bytes) computed server-side."""
    w, a = where(f)
    db = reader()
    by = {}
    for cat, sub, n, s in db.execute(f"SELECT files.cat, files.sub, COUNT(*), SUM(files.size) FROM files JOIN dirs ON dirs.id=files.dir{w} "  # nosec B608  # values are ? parameters; identifiers come from allow-lists
                                     "GROUP BY files.cat, files.sub", a):
        c = by.setdefault(cat, dict(n=0, size=0, subs={}))
        c["n"] += n
        c["size"] += s
        c["subs"][sub] = n
    dirs = [dict(path=p, n=n) for p, n in db.execute(
        f"SELECT dirs.path, COUNT(*) FROM files JOIN dirs ON dirs.id=files.dir{w} GROUP BY dirs.id ORDER BY 2 DESC LIMIT 200", a)]  # nosec B608  # values are ? parameters; identifiers come from allow-lists
    ndirs = db.execute(f"SELECT COUNT(DISTINCT files.dir) FROM files JOIN dirs ON dirs.id=files.dir{w}", a).fetchone()[0]  # nosec B608  # values are ? parameters; identifiers come from allow-lists
    cross = 0
    if dest_dev is not None:
        cross = db.execute(f"SELECT COALESCE(SUM(files.size),0) FROM files JOIN dirs ON dirs.id=files.dir{w}"  # nosec B608  # values are ? parameters; identifiers come from allow-lists
                           + (" AND" if w else " WHERE") + " (dirs.dev IS NULL OR dirs.dev != ?)", a + [dest_dev]).fetchone()[0]
    projects = db.execute(f"SELECT COUNT(*) FROM files JOIN dirs ON dirs.id=files.dir{w}" + (" AND" if w else " WHERE") + " dirs.kind IN ('project', 'assets')",  # nosec B608  # values are ? parameters; identifiers come from allow-lists
                          a).fetchone()[0]
    return dict(by_cat=by, n=sum(c["n"] for c in by.values()), size=sum(c["size"] for c in by.values()), dirs=dirs, ndirs=ndirs,
                cross_bytes=cross, project_files=projects)


def snapshots(drive=None, since=0):
    """Why: the storage trend chart (used space over time) from real post-scan snapshots."""
    q = "SELECT time, drive, used, total, bytype FROM snapshots WHERE time >= ?"
    a = [since]
    if drive:
        q += " AND drive = ?"
        a.append(drive)
    return [dict(time=t, drive=d, used=u, total=tt, bytype=json.loads(b or "{}")) for t, d, u, tt, b in reader().execute(q + " ORDER BY time", a)]
