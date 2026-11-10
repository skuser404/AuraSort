"""Corrupted files, duplicates and cleanup candidates. Everything here only reads; acting on results always goes
through the normal Move / Recycle Bin flows with their confirmations."""
import hashlib
import json
import os
import time

from . import config, index_db, integrity, jobs

SEV = ("corrupted", "damaged", "warning")
GROUPS_PER_PAGE = 50
DRIVE_SKEW = 1.5   # the drive's share of problems must be this much larger than its share of checked files
DUP_FULL_BUF = 4 * 1024 * 1024
SKIP_FLAGS = index_db.FLAG_CLOUD | index_db.FLAG_BUNDLE   # never read online-only placeholders or opaque bundles


def _path(r):
    return os.path.join(r["path"], r["name"])


# ---------------- integrity check ----------------
def _cached(db, r, mode):
    row = db.execute("SELECT size, mtime, mode FROM integrity WHERE file=?", (r["id"],)).fetchone()
    return bool(row and row[0] == r["size"] and abs(row[1] - r["mtime"]) < 1 and (row[2] == "deep" or mode == "quick"))


def run_integrity(job, rows, mode):
    """Why: read-only checks of every file; results are cached by size + modified time, so a re-check is fast."""
    deep = mode == "deep"
    job.extra.update(checked=0, problems=0, by_sev={s: 0 for s in SEV}, mode=mode)
    db, batch = index_db.reader(), []
    for r in rows:
        job.checkpoint()
        job.current_file = r["name"]
        if not _cached(db, r, mode):
            res = integrity.check(_path(r), r["ext"], deep)
            f = res.get("findings") or []
            batch.append((r["id"], r["size"], r["mtime"], mode, res["status"], f[0]["sev"] if f else "", f[0]["code"] if f else "", json.dumps(f), time.time()))
            if len(batch) >= config.SCAN_BATCH_ROWS:
                _save(batch)
        job.extra["checked"] += 1
        job.done += 1
        job.bytes += r["size"]
    _save(batch)
    s = integrity_summary()
    job.extra.update(problems=s["problems"], by_sev=s["by_sev"])


def _save(batch):
    if not batch:
        return
    with index_db.write_lock():
        c = index_db.writer()
        c.executemany("INSERT INTO integrity(file, size, mtime, mode, status, sev, code, findings, checked) VALUES(?,?,?,?,?,?,?,?,?) "
                      "ON CONFLICT(file) DO UPDATE SET size=excluded.size, mtime=excluded.mtime, mode=excluded.mode, status=excluded.status, "
                      "sev=excluded.sev, code=excluded.code, findings=excluded.findings, checked=excluded.checked", batch)
        c.commit()
    batch.clear()
    index_db.bump()


def integrity_summary():
    """Why: counts per severity, when it last ran, and a hint when one drive holds most of the problems."""
    db = index_db.reader()
    checked, last = db.execute("SELECT COUNT(*), MAX(checked) FROM integrity").fetchone()
    by = dict(db.execute("SELECT sev, COUNT(*) FROM integrity WHERE status='problem' GROUP BY sev").fetchall())
    drives = db.execute("SELECT dirs.drive, COUNT(*) FROM integrity JOIN files ON files.id=integrity.file JOIN dirs ON dirs.id=files.dir "
                        "WHERE integrity.status='problem' AND integrity.sev IN ('corrupted','damaged') GROUP BY dirs.drive").fetchall()
    bad = sum(n for _, n in drives)
    per_drive = dict(db.execute("SELECT dirs.drive, COUNT(*) FROM integrity JOIN files ON files.id=integrity.file JOIN dirs ON dirs.id=files.dir GROUP BY dirs.drive").fetchall())
    hint = ""
    for drive, n in drives:
        # only meaningful with several drives: a drive holding most problems but far fewer of the checked files
        share_files = per_drive.get(drive, 0) / max(1, checked or 0)
        if (drive and len(per_drive) > 1 and bad >= config.DRIVE_PROBLEM_MIN_FILES and n / bad >= config.DRIVE_PROBLEM_SHARE_HINT
                and n / bad > share_files * DRIVE_SKEW):
            hint = (f"{n} of the {bad} damaged files are on {drive}. That can mean the drive is failing: back it up first, then check it "
                    f"({'chkdsk in Windows' if config.WIN else 'Disk Utility First Aid' if config.MAC else 'fsck or smartctl'}).")
    by_sev = {s: by.get(s, 0) for s in SEV}
    return dict(checked=checked or 0, last=last, problems=sum(by_sev.values()), by_sev=by_sev, hint=hint)


def integrity_results(sev="", page=1, per=config.PAGE_SIZE):
    """Why: problem files first by severity, with what is wrong, why it may have happened and what to do."""
    if sev and sev not in SEV:
        raise ValueError("Unknown severity.")
    db = index_db.reader()
    w, a = "WHERE status='problem'" + (" AND sev=?" if sev else ""), [sev] if sev else []
    total = db.execute(f"SELECT COUNT(*) FROM integrity {w}", a).fetchone()[0]  # nosec B608  # values are ? parameters; identifiers come from allow-lists
    pages = max(1, -(-total // per))
    page = min(max(1, page), pages)
    order = "CASE sev WHEN 'corrupted' THEN 0 WHEN 'damaged' THEN 1 ELSE 2 END, file"
    found = db.execute(f"SELECT file, findings FROM integrity {w} ORDER BY {order} LIMIT ? OFFSET ?", a + [per, (page - 1) * per]).fetchall()  # nosec B608  # values are ? parameters; identifiers come from allow-lists
    rows = {r["id"]: r for r in index_db.rows_by_ids([f for f, _ in found])}
    out = [dict(rows[f], findings=json.loads(fs)) for f, fs in found if f in rows]
    return dict(total=total, page=page, pages=pages, per=per, size=sum(r["size"] for r in out), rows=out, summary=integrity_summary())


def integrity_csv():
    """Why: 'Export CSV' of the problem list (paths included: the user asked for this file)."""
    db = index_db.reader()
    lines = ["path,size,severity,problem,likely cause,what to do"]
    q = lambda s: '"' + str(s).replace('"', '""') + '"'
    for fid, fs in db.execute("SELECT file, findings FROM integrity WHERE status='problem' ORDER BY file"):
        r = index_db.file_by_id(fid)
        if r:
            for f in json.loads(fs)[:1]:
                lines.append(",".join(q(x) for x in (_path(r), r["size"], f["sev"], f["detail"], f["cause"], f["fix"])))
    return "\r\n".join(lines) + "\r\n"


# ---------------- duplicates (staged hashing) ----------------
def _partial(path, size):
    h = hashlib.blake2b(digest_size=16)
    with open(path, "rb") as fh:
        h.update(fh.read(config.DUP_PARTIAL_BYTES))
        if size > 2 * config.DUP_PARTIAL_BYTES:
            fh.seek(size - config.DUP_PARTIAL_BYTES)
            h.update(fh.read(config.DUP_PARTIAL_BYTES))
    return h.hexdigest()


def _full(path):
    h, buf = hashlib.blake2b(digest_size=32), bytearray(DUP_FULL_BUF)
    with open(path, "rb") as fh:
        while True:
            n = fh.readinto(buf)
            if not n:
                break
            h.update(memoryview(buf)[:n])
    return h.hexdigest()


def run_duplicates(job):
    """Why: stage 1 groups by size (free), stage 2 hashes only the first and last 64 KB, stage 3 fully hashes what still
    matches. Hashes are cached per file (size + modified time), so re-runs only read new or changed files."""
    db = index_db.reader()
    sizes = [s for (s,) in db.execute("SELECT size FROM files WHERE size >= ? AND flags & ? = 0 GROUP BY size HAVING COUNT(*) > 1",
                                      (config.DUP_MIN_BYTES, SKIP_FLAGS))]
    cand = []
    for i in range(0, len(sizes), index_db.SQL_VARS):
        part = sizes[i:i + index_db.SQL_VARS]
        cand += [dict(id=r[0], size=r[1], mtime=r[2], path=os.path.join(r[3], r[4])) for r in db.execute(
            f"SELECT files.id, files.size, files.mtime, dirs.path, files.name FROM files JOIN dirs ON dirs.id=files.dir "  # nosec B608  # values are ? parameters; identifiers come from allow-lists
            f"WHERE files.size IN ({','.join('?' * len(part))}) AND files.flags & ? = 0", part + [SKIP_FLAGS])]
    cache = {f: (s, m, p, fu) for f, s, m, p, fu in db.execute("SELECT file, size, mtime, part, full FROM hashes")}
    job.total, job.total_bytes = len(cand), sum(c["size"] for c in cand)
    job.extra.update(stage="partial", groups=0, wasted=0)
    rows, by_part = [], {}
    for c in cand:
        job.checkpoint()
        job.current_file = os.path.basename(c["path"])
        old = cache.get(c["id"])
        fresh = old and old[0] == c["size"] and abs(old[1] - c["mtime"]) < 1
        try:
            c["part"] = old[2] if fresh and old[2] else _partial(c["path"], c["size"])
            c["full"] = old[3] if fresh else None
            by_part.setdefault((c["size"], c["part"]), []).append(c)
        except OSError:
            pass
        job.done += 1
    job.extra["stage"] = "full"
    need = [c for g in by_part.values() if len(g) > 1 for c in g if not c["full"]]
    job.total, job.done, job.bytes, job.total_bytes = len(need), 0, 0, sum(c["size"] for c in need)
    for c in need:
        job.checkpoint()
        job.current_file = os.path.basename(c["path"])
        try:
            c["full"] = _full(c["path"])
        except OSError:
            c["full"] = None
        job.done += 1
        job.bytes += c["size"]
    for c in cand:
        if "part" in c:
            rows.append((c["id"], c["size"], c["mtime"], c["part"], c.get("full")))
    with index_db.write_lock():
        w = index_db.writer()
        w.executemany("INSERT INTO hashes(file, size, mtime, part, full) VALUES(?,?,?,?,?) ON CONFLICT(file) DO UPDATE SET size=excluded.size, "
                      "mtime=excluded.mtime, part=excluded.part, full=COALESCE(excluded.full, hashes.full)", rows)
        w.execute("INSERT OR REPLACE INTO meta(k, v) VALUES('duplicates_checked', ?)", (str(time.time()),))
        w.commit()
    index_db.bump()
    s = duplicate_summary()
    job.extra.update(stage="done", groups=s["groups"], wasted=s["wasted"])


def _dup_groups():
    db = index_db.reader()
    return db.execute("SELECT hashes.full, COUNT(*), MAX(files.size) FROM hashes JOIN files ON files.id=hashes.file "
                      "WHERE hashes.full IS NOT NULL AND files.size = hashes.size AND ABS(files.mtime - hashes.mtime) < 1 GROUP BY hashes.full HAVING COUNT(*) > 1 ORDER BY MAX(files.size) * (COUNT(*) - 1) DESC").fetchall()


def duplicate_summary():
    g = _dup_groups()
    row = index_db.reader().execute("SELECT v FROM meta WHERE k='duplicates_checked'").fetchone()
    return dict(groups=len(g), files=sum(n for _, n, _ in g), wasted=sum(s * (n - 1) for _, n, s in g), last=float(row[0]) if row else None)


def duplicate_results(page=1, per=GROUPS_PER_PAGE):
    """Why: groups of identical files, biggest waste first; the newest copy in each group is marked as the one to keep."""
    g = _dup_groups()
    pages = max(1, -(-len(g) // per))
    page = min(max(1, page), pages)
    db, out = index_db.reader(), []
    for full, n, size in g[(page - 1) * per: page * per]:
        ids = [f for (f,) in db.execute("SELECT file FROM hashes WHERE full=?", (full,))]
        members = sorted(index_db.rows_by_ids(ids), key=lambda r: -r["mtime"])
        out.append(dict(size=size, n=len(members), wasted=size * (len(members) - 1), keep=members[0]["id"] if members else None, rows=members))
    return dict(total=len(g), page=page, pages=pages, per=per, groups=out, summary=duplicate_summary())


def duplicate_extras():
    """Why: 'Select all but the newest' resolves to explicit ids."""
    ids, sizes = [], []
    for full, _, _ in _dup_groups():
        members = sorted(index_db.rows_by_ids([f for (f,) in index_db.reader().execute("SELECT file FROM hashes WHERE full=?", (full,))]), key=lambda r: -r["mtime"])
        for r in members[1:]:
            ids.append(r["id"])
            sizes.append(r["size"])
    return ids, sizes


# ---------------- cleanup candidates (rules, no reading) ----------------
DAY = 86400
REASONS = (
    ("partial", "Unfinished downloads", "Downloads that stopped before they completed (older than {d} days).", config.PARTIAL_MIN_AGE_DAYS),
    ("temp", "Temporary files", "Files apps left behind while working (older than {d} days).", config.TEMP_MIN_AGE_DAYS),
    ("empty", "Empty files", "Files with no content at all (0 bytes).", 0),
    ("installers", "Old installers", "Setup files in Downloads you probably already installed (older than {d} days).", config.OLD_INSTALLER_DAYS),
)


def _cleanup_where(reason, now):
    ok_dirs = "files.dir IN (SELECT id FROM dirs WHERE kind NOT IN ('project','assets'))"
    if reason == "partial":
        return f"{ok_dirs} AND files.flags & 2 AND files.mtime < ?", [now - config.PARTIAL_MIN_AGE_DAYS * DAY]
    if reason == "temp":
        exts = sorted(config.TEMP_EXTS)
        return f"{ok_dirs} AND files.ext IN ({','.join('?' * len(exts))}) AND files.mtime < ?", exts + [now - config.TEMP_MIN_AGE_DAYS * DAY]
    if reason == "empty":
        return f"{ok_dirs} AND files.size = 0", []
    if reason == "installers":
        sql = f"{ok_dirs} AND files.cat = 'Installers & Apps' AND files.mtime < ? AND files.dir IN (SELECT id FROM dirs WHERE lpath LIKE ?)"  # nosec B608  # fixed text; values are ? parameters
        return sql, [now - config.OLD_INSTALLER_DAYS * DAY, "%downloads%"]
    raise ValueError("Unknown cleanup group.")


def cleanup_summary(now=None):
    """Why: the 'Clean junk files' review list: counts and sizes per reason, nothing selected or removed automatically."""
    now, db, out = now or time.time(), index_db.reader(), []
    for key, label, desc, days in REASONS:
        w, a = _cleanup_where(key, now)
        n, s = db.execute(f"SELECT COUNT(*), COALESCE(SUM(files.size),0) FROM files WHERE {w}", a).fetchone()  # nosec B608  # values are ? parameters; identifiers come from allow-lists
        out.append(dict(key=key, label=label, desc=desc.format(d=days), n=n, size=s))
    d = duplicate_summary()
    out.append(dict(key="duplicates", label="Duplicate copies", desc="Extra copies of identical files (the newest copy is kept).", n=d["files"] - d["groups"], size=d["wasted"], link="duplicates"))
    return out


def cleanup_rows(reason, page=1, per=config.PAGE_SIZE, now=None):
    w, a = _cleanup_where(reason, now or time.time())
    db = index_db.reader()
    total = db.execute(f"SELECT COUNT(*) FROM files WHERE {w}", a).fetchone()[0]  # nosec B608  # values are ? parameters; identifiers come from allow-lists
    pages = max(1, -(-total // per))
    page = min(max(1, page), pages)
    ids = [r[0] for r in db.execute(f"SELECT files.id FROM files WHERE {w} ORDER BY files.size DESC, files.id LIMIT ? OFFSET ?", a + [per, (page - 1) * per])]  # nosec B608  # values are ? parameters; identifiers come from allow-lists
    rows = index_db.rows_by_ids(ids)
    return dict(total=total, page=page, pages=pages, per=per, size=sum(r["size"] for r in rows), rows=rows)


def cleanup_ids(reason, now=None):
    w, a = _cleanup_where(reason, now or time.time())
    rows = index_db.reader().execute(f"SELECT files.id, files.size FROM files WHERE {w}", a).fetchall()  # nosec B608  # values are ? parameters; identifiers come from allow-lists
    return [r[0] for r in rows], [r[1] for r in rows]


# ---------------- starting jobs ----------------
def start_integrity(mode, ids=None):
    if mode not in ("quick", "deep"):
        raise ValueError("Unknown check mode.")
    if jobs.running("integrity"):
        raise ValueError("A check is already running.")
    if ids is None:
        ids, _ = index_db.ids_for({"scope": "all"})
    rows = []
    for i in range(0, len(ids), index_db.SQL_VARS):
        rows += [r for r in index_db.rows_by_ids(ids[i:i + index_db.SQL_VARS]) if not r["flags"] & SKIP_FLAGS]
    job = jobs.Job("integrity", total=len(rows), total_bytes=sum(r["size"] for r in rows), mode=mode)
    return jobs.start(job, run_integrity, rows, mode)


def start_duplicates():
    if jobs.running("duplicates"):
        raise ValueError("Duplicates are already being checked.")
    return jobs.start(jobs.Job("duplicates"), run_duplicates)

