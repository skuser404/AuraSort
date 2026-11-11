"""AuraSort's own trash, for places where the operating system has none (Android/Termux) and for "Replace" (the file
that would be overwritten is kept here so Undo can put it back on every OS).

Files are moved (renamed, never copied) into `.AuraSortTrash` at the top of the same drive or storage, and listed in
apptrash.json in the data folder, so Settings > AuraSort trash can restore them. Nothing is ever erased unless the
user turns on the purge timer (off by default); that timer is the only code in AuraSort that deletes for good."""
import json
import os
import secrets
import shutil
import threading
import time

from . import config
from .log import log
from .platform_utils import long_path, make_private, replace_file, within
from .safety import unique_name

_lock = threading.Lock()


def _index_path():
    return config.DATA_DIR / config.APPTRASH_INDEX


def _load():
    try:
        with open(_index_path(), encoding="utf-8") as fh:
            d = json.load(fh)
        return d if isinstance(d, list) else []
    except (OSError, ValueError):
        return []


def _save(items):
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _index_path().with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(items, fh, ensure_ascii=False)
    replace_file(tmp, _index_path())
    if not config.WIN:   # Windows: inherits the data folder's user-only ACL
        make_private(_index_path(), is_dir=False)


def trash_root(path):
    """Why: the highest writable folder on the same drive as the file, so moving into the trash is a rename (instant,
    nothing copied, nothing that can be half-done). On Android that is /storage/emulated/0."""
    d = os.path.dirname(os.path.abspath(path))
    dev = os.stat(long_path(d)).st_dev
    best = d
    while True:
        parent = os.path.dirname(best)
        if parent == best:
            break
        try:
            if os.stat(long_path(parent)).st_dev != dev or not os.access(parent, os.W_OK):
                break
        except OSError:
            break
        best = parent
    return os.path.join(best, config.APPTRASH_DIR_NAME)


def put(path, reason="deleted"):
    """Why: move one file into the app trash; returns its record. Raises OSError if it cannot be renamed there."""
    root = trash_root(path)
    item_id = time.strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(4)
    folder = os.path.join(root, item_id)
    os.makedirs(long_path(folder), exist_ok=True)
    if not config.WIN:
        try:
            os.chmod(root, 0o700)
        except OSError:
            pass
    stored = os.path.join(folder, os.path.basename(path))
    try:
        size = os.lstat(long_path(path)).st_size
        os.rename(long_path(path), long_path(stored))   # same drive by construction: a rename, never a copy + delete
    except OSError:
        try:
            os.rmdir(long_path(folder))
        except OSError:
            pass
        raise
    rec = dict(id=item_id, original=os.path.abspath(path), stored=stored, size=size, time=int(time.time()), reason=reason)
    with _lock:
        items = _load()
        items.append(rec)
        _save(items)
    log.info("moved a file into the AuraSort trash (%s)", reason)
    return rec


def items():
    """Why: Settings > AuraSort trash lists what can be restored (entries whose file is gone are dropped)."""
    with _lock:
        all_items = _load()
        keep = [i for i in all_items if os.path.lexists(long_path(i.get("stored", "")))]
        if len(keep) != len(all_items):
            _save(keep)
    return sorted(keep, key=lambda i: -i.get("time", 0))


def restore(item_id, target=None):
    """Why: put a trashed file back where it was (or `target`), never over an existing file: a clash gets ' (1)'."""
    with _lock:
        all_items = _load()
        rec = next((i for i in all_items if i.get("id") == item_id), None)
        if not rec:
            raise ValueError("That item is no longer in the AuraSort trash.")
        dest = target or rec["original"]
        parent = os.path.dirname(dest)
        os.makedirs(long_path(parent), exist_ok=True)
        final = os.path.join(parent, unique_name(parent, os.path.basename(dest)))
        os.rename(long_path(rec["stored"]), long_path(final))
        try:
            os.rmdir(long_path(os.path.dirname(rec["stored"])))
        except OSError:
            pass
        _save([i for i in all_items if i.get("id") != item_id])
    log.info("restored a file from the AuraSort trash")
    return final


def purge_old(days=None):
    """Why: the optional purge timer (Settings, off by default). Only items older than `days` are erased, and only
    inside .AuraSortTrash folders. Returns how many were erased."""
    from . import settings
    days = settings.load().get("apptrash_purge_days", 0) if days is None else days
    if not days:
        return 0
    cutoff, gone = time.time() - days * 86400, 0
    with _lock:
        all_items = _load()
        keep = []
        for i in all_items:
            stored = i.get("stored", "")
            folder = os.path.dirname(stored)
            if i.get("time", 0) < cutoff and os.path.basename(os.path.dirname(folder)) == config.APPTRASH_DIR_NAME \
                    and within(stored, os.path.dirname(folder)):
                try:
                    if os.path.isdir(long_path(folder)):
                        shutil.rmtree(long_path(folder))
                    gone += 1
                    continue
                except OSError:
                    log.warning("could not erase an old AuraSort trash item")
            keep.append(i)
        _save(keep)
    if gone:
        log.info("purge timer erased %s AuraSort trash items older than %s days", gone, days)
    return gone
