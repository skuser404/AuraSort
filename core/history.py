"""History of every action (moves, copies, Recycle Bin, quarantine, scans, integrity checks) as JSON manifests."""
import json
import os
import re
import shutil
import time

from . import config
from .log import log
from .platform_utils import make_private

KINDS = ("move", "copy", "trash", "quarantine", "scan", "integrity", "duplicates")
UNDOABLE = ("move", "quarantine")
_SAFE_ID = re.compile(r"[^0-9A-Za-z_-]")


def ensure_dirs():
    """Why: the data folders must exist with user-only permissions before anything is written."""
    for d in (config.DATA_DIR, config.HISTORY_DIR, config.THUMB_DIR):
        existed = d.exists()
        d.mkdir(parents=True, exist_ok=True)
        if not existed:
            make_private(d, is_dir=True)


def migrate_legacy():
    """Why: history written by earlier versions stays visible and undoable; originals are left untouched."""
    copied = 0
    for old in config.LEGACY_DATA_DIRS:
        src = old / "history"
        if not src.is_dir():
            continue
        for f in src.glob("*.json"):
            target = config.HISTORY_DIR / f.name
            if target.exists():
                continue
            try:
                m = json.loads(f.read_text(encoding="utf-8"))
                m.setdefault("kind", m.get("mode", "move"))
                m["imported"] = True
                save(m)
                copied += 1
            except (OSError, ValueError):
                log.warning("skipped an unreadable legacy history file")
    if copied:
        log.info("imported %d history entries from an earlier version", copied)
    return copied


def new_id():
    """Why: ids sort by time and stay unique even for two actions in the same second."""
    return time.strftime("%Y%m%d-%H%M%S") + "-" + os.urandom(2).hex()


def path_for(hid):
    """Why: ids come from the browser, so they are reduced to safe characters before touching the disk."""
    hid = _SAFE_ID.sub("", str(hid))
    if not hid:
        raise ValueError("History entry not found.")
    return config.HISTORY_DIR / f"{hid}.json"


def save(m):
    """Why: atomic write (temp + replace) so a crash never leaves a half-written undo manifest."""
    p = path_for(m["id"])
    if not p.parent.is_dir():
        ensure_dirs()                  # the data folder was removed while the app ran (e.g. by a cleaner tool)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(m), encoding="utf-8")
    os.replace(tmp, p)
    if not config.WIN:
        make_private(p, is_dir=False)


def load(hid):
    """Why: undo and 'open destination' need the full manifest."""
    p = path_for(hid)
    if not p.is_file():
        raise ValueError("History entry not found.")
    return json.loads(p.read_text(encoding="utf-8"))


def summary(m, fallback_id=""):
    """Why: the history list and Recent Activity only need a compact description of each entry. Entries written by
    earlier versions may lack fields (even the id), so every field has a default."""
    ops = [o for o in (m.get("ops") or []) if isinstance(o, dict)]
    kind = m.get("kind") or m.get("mode", "move")
    return dict(id=m.get("id") or fallback_id, kind=kind, time=m.get("time", 0), dest=m.get("dest", ""), undone=m.get("undone", False),
                count=m.get("count", len(ops)), size=m.get("size", sum(o.get("size", 0) for o in ops)),
                failed=m.get("failed", 0), imported=m.get("imported", False), undoable=kind in UNDOABLE and not m.get("undone"),
                label=m.get("label", ""), state=m.get("state", "done"))


def entries(limit=config.HISTORY_LIST_MAX, kinds=None):
    """Why: newest first; ids start with a timestamp so sorting by name is sorting by time."""
    out = []
    for f in sorted(config.HISTORY_DIR.glob("*.json"), key=lambda f: f.name, reverse=True):
        try:
            m = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            log.warning("history: an entry could not be read and was skipped")
            continue
        if not isinstance(m, dict):
            log.warning("history: an entry has an unknown format and was skipped")
            continue
        s = summary(m, f.stem)
        if kinds and s["kind"] not in kinds:
            continue
        out.append(s)
        if len(out) >= limit:
            break
    return out


def record(kind, **fields):
    """Why: scans and integrity checks are logged as simple events for Recent Activity."""
    m = dict(id=new_id(), kind=kind, time=int(time.time()), **fields)
    save(m)
    return m


def mark_interrupted():
    """Why: at start-up, a manifest still marked 'running' means the app stopped mid-job (crash, power loss):
    it is marked 'interrupted' so the user can Resume or Clean up. Nothing is ever half-moved silently."""
    found = 0
    for f in config.HISTORY_DIR.glob("*.json"):
        try:
            m = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if m.get("state") == "running":
            m["state"] = "interrupted"
            save(m)
            found += 1
    if found:
        log.warning("%d job(s) were interrupted last time", found)
    return found


def interrupted():
    """Why: the jobs to offer Resume / Clean up for."""
    out = []
    for f in sorted(config.HISTORY_DIR.glob("*.json"), reverse=True):
        try:
            m = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if m.get("state") == "interrupted":
            done = {o.get("fid") for o in m.get("ops", [])}
            left = [p for p in m.get("plan", []) if p["fid"] not in done and os.path.exists(p["src"])]
            out.append(dict(summary(m), left=len(left), left_bytes=sum(p["size"] for p in left), mode=m.get("mode"), verify=m.get("verify", "full")))
    return out


def remove_empty_dirs(root):
    """Why: after undo, folders created by a move are removed only if empty (files are never deleted)."""
    for d, _, _ in os.walk(root, topdown=False):
        if os.path.normcase(d) == os.path.normcase(str(root)):
            continue
        try:
            os.rmdir(d)  # fails (and is ignored) unless the folder is empty
        except OSError:
            pass


def disk_free(path):
    """Why: free-space numbers before/after a job come from the real disk."""
    p = os.path.abspath(path)
    while not os.path.exists(p) and os.path.dirname(p) != p:
        p = os.path.dirname(p)
    return shutil.disk_usage(p).free
