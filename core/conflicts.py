"""'A file with this name already exists': found before any move or copy, shown side by side, and resolved per file
(Skip / Keep both / Replace) or for all at once. Never an overwrite: "Replace" first moves the existing file into
AuraSort's own trash on the same drive, the journal records it, and Undo puts it back.

Why the app trash and not the Recycle Bin for Replace: Undo must restore the replaced file exactly, on every OS. A file
in AuraSort's trash can be put back by AuraSort; one in the Recycle Bin (or Finder's Trash) cannot be found again
reliably. It stays recoverable from Settings > AuraSort trash, and is never erased unless the purge timer is on."""
import os

from . import config
from .platform_utils import is_online_only, long_path
from .safety import is_plain_file, is_protected

ACTIONS = ("skip", "keep", "replace")
CHUNK = 1024 * 1024


def clean_choice(raw):
    """Why: the browser's choice is validated like every other request field (anything unknown = keep both, the safe one)."""
    if raw is None:
        return dict(action="keep", skip_identical=False, per={})
    if not isinstance(raw, dict):
        raise ValueError("Invalid conflict choice.")
    action = raw.get("action", "keep")
    if action not in ACTIONS:
        raise ValueError("Unknown conflict choice. Use skip, keep or replace.")
    per = raw.get("per") or {}
    if not isinstance(per, dict) or len(per) > config.CONFLICT_PER_FILE_MAX:
        raise ValueError("Invalid conflict choices.")
    clean = {}
    for k, v in per.items():
        if v not in ACTIONS:
            raise ValueError("Unknown conflict choice. Use skip, keep or replace.")
        try:
            clean[int(k)] = v
        except (TypeError, ValueError):
            raise ValueError("Invalid conflict choices.") from None
    return dict(action=action, skip_identical=bool(raw.get("skip_identical")), per=clean)


def _stat(path):
    try:
        return os.stat(long_path(path))
    except OSError:
        return None


def same_content(a, b, budget=None):
    """Why: 'identical content' only when sizes match and every byte matches. Online-only (OneDrive/iCloud) files are
    never read (that would download them): None = not compared. `budget` (a one-item list of bytes) limits the preview."""
    sa, sb = _stat(a), _stat(b)
    if not sa or not sb:
        return None
    if sa.st_size != sb.st_size:
        return False
    if is_online_only(sa) or is_online_only(sb):
        return None
    if budget is not None:
        if budget[0] < sa.st_size:
            return None
        budget[0] -= sa.st_size
    try:
        with open(long_path(a), "rb") as fa, open(long_path(b), "rb") as fb:
            while True:
                x, y = fa.read(CHUNK), fb.read(CHUNK)
                if x != y:
                    return False
                if not x:
                    return True
    except OSError:
        return None


def target_for(op, real_dest):
    """Why: the exact path a file would get (same rule as the mover, minus the ' (1)' a clash would add)."""
    from .mover import target_dir
    return os.path.join(target_dir(real_dest, op["sub"]), op["name"])


def find(ops, dest):
    """Why: the preview: which files already exist where they would go, both sides' size and date, and whether the
    content is identical. Also clashes inside the selection itself (two 'photo.jpg' going to one folder)."""
    real_dest = os.path.realpath(dest)
    rows, seen, budget, identical = [], {}, [config.CONFLICT_COMPARE_MAX_BYTES], 0
    total = 0
    for op in ops:
        t = target_for(op, real_dest)
        key = os.path.normcase(t)
        if key in seen:
            total += 1
            if len(rows) < config.CONFLICT_PREVIEW_MAX:
                rows.append(dict(fid=op["fid"], name=op["name"], target=t, src=dict(size=op["size"], mtime=op["mtime"]), dst=None,
                                 identical=None, within_selection=True))
            continue
        seen[key] = op["fid"]
        if not os.path.lexists(long_path(t)):
            continue
        total += 1
        st = _stat(t)
        same = same_content(op["src"], t, budget) if st else None
        identical += 1 if same else 0
        if len(rows) < config.CONFLICT_PREVIEW_MAX:
            rows.append(dict(fid=op["fid"], name=op["name"], target=t, src=dict(size=op["size"], mtime=op["mtime"]),
                             dst=dict(size=st.st_size, mtime=st.st_mtime, plain=is_plain_file(t), protected=is_protected(t),
                                      readonly=not os.access(long_path(t), os.W_OK)) if st else None,
                             identical=same, within_selection=False))
    return dict(total=total, identical=identical, rows=rows, more=max(0, total - len(rows)))
