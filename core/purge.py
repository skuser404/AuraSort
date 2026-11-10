"""'Delete my AuraSort data': removes AuraSort's own data (never your files), then recreates an empty data folder."""
import os
import shutil

from . import config, docai, history, index_db, jobs, keystore
from .log import close_file, reopen_file
from .platform_utils import within


def _inside_data(p):
    """Why: only paths inside ~/.aurasort may ever be removed here."""
    return within(os.path.abspath(str(p)), os.path.abspath(str(config.DATA_DIR)))


def delete_all():
    """Why: index, History/Undo logs, snapshots, thumbnails, settings, the log, AI results and a saved API key.
    Returns the list of what was removed (names only)."""
    if any(j.state in ("running", "paused", "waiting") for j in jobs.JOBS.values()):
        raise ValueError("Stop the running scan, move or check first.")
    removed = []
    docai.clear()
    removed.append("Document Insights results")
    keystore.clear()
    removed.append("saved API key (if any)")
    index_db.wipe()   # emptied in place (other threads may hold the file open on Windows), then vacuumed
    removed.append("file index and scan snapshots")
    had_log = close_file()
    try:
        for d, label in ((config.HISTORY_DIR, "History and Undo logs"), (config.THUMB_DIR, "thumbnails")):
            if d.exists() and _inside_data(d):
                shutil.rmtree(d)
            removed.append(label)
        for f, label in ((config.SETTINGS_FILE, "settings"),):
            if f.exists() and _inside_data(f):
                f.unlink()
            removed.append(label)
        for folder in {config.LOG_FILE.parent, config.DATA_DIR}:   # logs/server.log*, plus the old aurasort.log* of earlier versions
            for f in list(folder.glob(config.LOG_FILE.name + "*")) + list(folder.glob(f"{config.APP_SLUG}.log*")):
                if _inside_data(f) and f.is_file():
                    f.unlink()
        removed.append("log")
    finally:
        history.ensure_dirs()
        if had_log:
            reopen_file()
    return removed
