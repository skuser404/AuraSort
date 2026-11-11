"""Move, copy and Recycle Bin jobs. Never overwrites: a name clash is skipped, kept as 'name (1).ext', or (only when you
chose Replace) the existing file is first moved into AuraSort's trash so Undo can put it back. Never deletes
permanently, re-checks every file right before acting, and logs a manifest for History (and Undo for moves)."""
import os
import shutil
import time

import threading
from concurrent.futures import ThreadPoolExecutor

from . import apptrash, config, conflicts as clash, copier, history, jobs, trash
from .platform_utils import drive_media, drive_of
from .safety import clean_part, is_plain_file, is_protected, real_inside, unique_name

_nc = os.path.normcase
CLOUD_FLAG = 4   # index_db.FLAG_CLOUD (not imported here to keep mover independent of the index)


def verify_source(src, expected_dir, size, mtime):
    """Why: the file may have changed since the scan (TOCTOU); refuse links, edits, moves and protected locations."""
    if not is_plain_file(src):
        return "missing, or not a regular file anymore"
    try:
        if _nc(os.path.realpath(os.path.dirname(src))) != _nc(os.path.realpath(expected_dir)):
            return "its folder changed since the scan"
        st = os.stat(src)
    except OSError:
        return "missing"
    if st.st_size != size or int(st.st_mtime) != int(mtime):
        return "changed since the scan"
    if is_protected(src):
        return "inside a protected folder"
    return None


def move_file(src, dst):
    """Why: rename on the same drive; across drives copy, verify the size, and only then remove the original."""
    if copier.same_volume(src, os.path.dirname(dst)):
        os.rename(src, dst)
        return dst
    return copier.copy_verified(src, os.path.dirname(dst), os.path.basename(dst), "full", move=True)   # verified before the source goes


def drive_free(paths):
    """Why: 'space freed' is measured on the real drives involved, before and after the job."""
    seen, total = set(), 0
    for p in paths:
        try:
            dev = os.stat(p).st_dev
            if dev in seen:
                continue
            seen.add(dev)
            total += shutil.disk_usage(p).free
        except OSError:
            continue
    return total


def target_dir(real_dest, sub):
    """Why: sub-folders come from data (category/sub-category/reason), so each part is sanitised and contained."""
    parts = [clean_part(p) for p in str(sub).replace("\\", "/").split("/") if p not in ("", ".", "..")]
    tdir = os.path.join(real_dest, *parts)
    if not real_inside(tdir, real_dest) and _nc(os.path.abspath(tdir)) != _nc(real_dest):
        raise OSError("destination escaped its folder")
    return tdir


def device(path):
    """Why: one place answers 'which drive is this on' (tests use it to simulate a second drive)."""
    try:
        return os.stat(path).st_dev
    except OSError:
        return None


def _rename_no_overwrite(src, tdir, name):
    """Why: same-drive moves are instant renames, but must never replace a file that appeared meanwhile."""
    for _ in range(50):
        dst = os.path.join(tdir, unique_name(tdir, name))
        try:
            if config.WIN:
                os.rename(copier.long_path(src), copier.long_path(dst))   # Windows refuses to rename over a file
            else:
                try:
                    os.link(src, dst)
                    os.unlink(src)
                except FileExistsError:
                    raise
                except OSError:   # file system without hard links (FAT/exFAT): plain rename of a name we just checked
                    os.rename(src, dst)
            return dst
        except FileExistsError:
            continue
    raise OSError("could not find a free name")


class Skipped(OSError):
    """Why: a file left alone on purpose (you chose Skip for a name clash) is counted apart from failures."""


def run(job, dest, mode, ops, on_done=None, label="", verify_mode="full", conflicts=None):
    """Why: the single file-transfer pipeline. ops = dicts with fid, src, dir, name, size, mtime, cat, sub.
    Same-drive moves rename; everything else goes through copier.copy_verified (verified before any source is removed).
    `conflicts` = {action: skip|keep|replace, skip_identical, per: {fid: action}} decides what a name clash does."""
    kind = "quarantine" if label == "quarantine" else mode
    choice = clash.clean_choice(conflicts)
    written = set()     # paths this job created: a later file in the same batch never replaces one of them
    seen = set()
    ops = sorted((o for o in ops if not (o["fid"] in seen or seen.add(o["fid"]))), key=lambda o: (o["dir"].lower(), o["name"].lower()))
    m = dict(id=job.id, kind=kind, time=int(time.time()), dest=dest, mode=mode, undone=False, ops=[], label=label, state="running",
             verify=verify_mode, plan=[{k: o[k] for k in ("fid", "src", "dir", "name", "size", "mtime", "cat", "sub")} for o in ops])
    history.save(m)   # journal first: after a crash this says exactly what was planned and what was done
    os.makedirs(dest, exist_ok=True)
    real_dest = os.path.realpath(dest)
    watch = [real_dest] + sorted({op["dir"] for op in ops})
    job.extra.update(current=[], by_cat={}, free_before=drive_free(watch), free_after=None, mode=mode, dest=dest, skipped=0, moved=0,
                     verified=0, verify=verify_mode, src_drives=sorted({drive_of(o["dir"]) for o in ops}), dest_drive=drive_of(real_dest),
                     clash_skipped=0, clash_kept=0, replaced=0, clash_names=[])
    lock, dev = threading.Lock(), {}
    dest_dev = device(real_dest)

    def same_dev(op):
        if op["dir"] not in dev:
            dev[op["dir"]] = device(op["dir"])
        return dev[op["dir"]] is not None and dev[op["dir"]] == dest_dev

    def live(op):   # large files report progress and can be cancelled mid-file; small ones between files
        big = op["size"] >= config.COPY_SMALL_FILE_BYTES
        return dict(on_bytes=add_for(op) if big else None, should_stop=(lambda: job._cancel) if big else None)

    progress = {}

    def add_for(op):
        def add(n):
            with lock:
                job.bytes += n
                progress[op["fid"]] = progress.get(op["fid"], 0) + n
        return add

    def decide(op, target):
        """Why: per-file choice first, then 'skip identical', then the choice for all."""
        if op["fid"] in choice["per"]:
            return choice["per"][op["fid"]]
        if choice["skip_identical"] and clash.same_content(op["src"], target):
            return "skip"
        return choice["action"]

    def one(op):
        job.checkpoint()
        job.current_file = op["name"]
        aside = None
        try:
            problem = verify_source(op["src"], op["dir"], op["size"], op["mtime"])
            if problem:
                raise OSError(problem)
            tdir = target_dir(real_dest, op["sub"])
            if _nc(os.path.realpath(op["dir"])) == _nc(os.path.realpath(tdir)):
                raise OSError("already in that folder")
            os.makedirs(tdir, exist_ok=True)
            renamed = mode == "move" and same_dev(op)
            if not renamed and op.get("flags", 0) & CLOUD_FLAG:
                raise OSError("online-only file (OneDrive/iCloud): make it available offline first")
            target = os.path.join(tdir, op["name"])
            if os.path.lexists(target):
                with lock:
                    ours = _nc(target) in written
                what = "keep" if ours else decide(op, target)
                if what == "skip":
                    raise Skipped("a file with this name is already there (skipped, as you chose)")
                if what == "replace":
                    if not is_plain_file(target) or is_protected(target):
                        raise OSError("the existing item is a folder, a link or protected, so it was not replaced")
                    try:
                        aside = apptrash.put(target, "replaced")   # set aside first: recoverable, and Undo restores it
                    except OSError as ex:
                        raise OSError(f"the existing file could not be set aside ({type(ex).__name__}: read-only or in use), so nothing was replaced") from None
                elif not ours:
                    with lock:
                        job.extra["clash_kept"] += 1
            dst = (_rename_no_overwrite(op["src"], tdir, op["name"]) if renamed else
                   copier.copy_verified(op["src"], tdir, op["name"], verify_mode, move=mode == "move", **live(op)))
            rel = "/".join(os.path.relpath(tdir, real_dest).split(os.sep))
            with lock:
                written.add(_nc(dst))
                rec = dict(src=op["src"], dst=dst, size=op["size"], fid=op["fid"], cat=op["cat"])
                if aside:
                    rec["replaced"] = dict(id=aside["id"], path=aside["original"])
                    job.extra["replaced"] += 1
                m["ops"].append(rec)
                job.extra["verified"] += 0 if renamed else 1
                _count_done(job, op, os.path.basename(real_dest) if rel == "." else rel)
            aside = None
            if on_done:
                on_done(op, dst)
        except copier.DiskFull:
            _put_back(aside)
            raise
        except Skipped:
            with lock:
                job.extra["clash_skipped"] += 1
                if len(job.extra["clash_names"]) < config.JOB_CURRENT_KEEP:
                    job.extra["clash_names"].append(op["name"])
        except OSError as err:
            _put_back(aside)
            with lock:
                job.extra["skipped"] += 1
                job.error(f"{op['name']}: {err}")
        finally:
            with lock:
                job.bytes += op["size"] - progress.pop(op["fid"], 0)
                job.done += 1
                if job.done % config.MANIFEST_SAVE_EVERY == 0:
                    history.save(m)

    small = [o for o in ops if not (mode == "move" and same_dev(o)) and o["size"] < config.COPY_SMALL_FILE_BYTES]
    rest = [o for o in ops if o not in small]
    try:
        for op in rest:   # renames and large copies: one at a time (streaming, kind to hard disks)
            one(op)
        if small:         # many small cross-drive copies: a few in parallel
            with ThreadPoolExecutor(max_workers=config.COPY_SMALL_THREADS.get(drive_media(drive_of(real_dest)), 4)) as pool:
                for f in [pool.submit(one, o) for o in small]:
                    f.result()
        m["state"] = "done"
    except copier.DiskFull:
        m["state"] = "stopped"
        job.error("Stopped: the destination drive is full. Every file already copied is complete and verified; nothing was half-moved.")
        job.finish("error")
    except jobs.Cancelled:
        m["state"] = "cancelled"
        raise
    finally:
        if m["state"] == "running":
            m["state"] = "error"
        m["count"] = len(m["ops"])
        m["size"] = sum(o["size"] for o in m["ops"])
        m["failed"] = job.extra.get("skipped", 0)
        history.save(m)
        job.extra["free_after"] = drive_free(watch)


def _put_back(aside):
    """Why: a Replace whose move then failed must not lose the file that was set aside: it goes straight back."""
    if aside:
        try:
            apptrash.restore(aside["id"], aside["original"])
        except (OSError, ValueError):
            pass   # still safe in the AuraSort trash, listed in Settings


def _count_done(job, op, to):
    """Why: the same live counters (per category + recent files) for every kind of job."""
    ex = job.extra
    ex["moved"] += 1
    bc = ex["by_cat"].setdefault(op["cat"], dict(moved=0, bytes=0))
    bc["moved"] += 1
    bc["bytes"] += op["size"]
    ex["current"] = (ex["current"] + [dict(seq=ex["moved"], id=op["fid"], name=op["name"], cat=op["cat"], size=op["size"], to=to)])[-config.JOB_CURRENT_KEEP:]


def run_trash(job, ops, on_removed=None):
    """Why: the only delete path: files go to the Recycle Bin/Trash in batches, each re-checked first; History keeps the list."""
    m = dict(id=job.id, kind="trash", time=int(time.time()), dest="", mode="trash", undone=False, ops=[], label="")
    job.extra.update(current=[], by_cat={}, mode="trash", dest="", skipped=0, moved=0)
    norm = lambda p: _nc(os.path.abspath(p))
    try:
        for i in range(0, len(ops), config.TRASH_BATCH):
            job.checkpoint()
            batch, ready = ops[i:i + config.TRASH_BATCH], []
            for op in batch:
                problem = verify_source(op["src"], op["dir"], op["size"], op["mtime"])
                if problem:
                    job.extra["skipped"] += 1
                    job.error(f"{op['name']}: {problem}")
                else:
                    ready.append(op)
            res = trash.send_to_trash([op["src"] for op in ready])
            gone = {norm(p) for p in res.trashed}
            done = [op for op in ready if norm(op["src"]) in gone]
            for op in done:
                m["ops"].append(dict(src=op["src"], size=op["size"], fid=op["fid"], cat=op["cat"]))
                _count_done(job, op, "Recycle Bin")
            for p, reason in res.failed:
                job.extra["skipped"] += 1
                job.error(f"{os.path.basename(p)}: {reason}")
            if done and on_removed:
                on_removed([op["fid"] for op in done])
            job.current_file = batch[-1]["name"]
            job.done = i + len(batch)
            job.bytes += sum(op["size"] for op in batch)
            history.save(m)
    finally:
        m["count"] = len(m["ops"])
        m["size"] = sum(o["size"] for o in m["ops"])
        m["failed"] = job.extra.get("skipped", 0)
        history.save(m)


def undo(hid, on_restored=None):
    """Why: puts moved files back (never overwriting) and removes only folders that became empty."""
    m = history.load(hid)
    if m.get("kind", m.get("mode")) not in history.UNDOABLE:
        raise ValueError("Only moves can be undone. Copies stay where they are; deleted files are in the Recycle Bin.")
    if m.get("undone"):
        raise ValueError("This was already undone.")
    back = lost = put_back = 0
    for op in reversed(m["ops"]):
        src, dst = op["src"], op["dst"]
        if not is_plain_file(dst):
            lost += 1
            continue
        try:
            parent = os.path.dirname(src)
            os.makedirs(parent, exist_ok=True)
            target = os.path.join(parent, unique_name(parent, os.path.basename(src)))
            move_file(dst, target)
            back += 1
            if on_restored:
                on_restored(op, target)
        except OSError:
            lost += 1
            continue
        if op.get("replaced"):   # the file that Replace set aside goes back where it was
            try:
                apptrash.restore(op["replaced"]["id"], op["replaced"]["path"])
                put_back += 1
            except (OSError, ValueError):
                pass   # still in the AuraSort trash (Settings), never lost
    history.remove_empty_dirs(m["dest"])
    m["undone"] = True
    history.save(m)
    return dict(restored=back, missing=lost, replaced_restored=put_back)
