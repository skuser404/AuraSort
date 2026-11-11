"""Send files to the Recycle Bin / Trash. Never deletes permanently: if the bin is unavailable the file is skipped."""
import datetime as _dt
import os
import shutil
import subprocess  # nosec B404  # fixed argument lists only
import urllib.parse

from . import config
from .log import log
from .platform_utils import drive_of, drive_type

WIN, MAC = config.WIN, config.MAC
OSA_TIMEOUT_S = 120
# Automated tests only: when set, "trashed" files are moved into this folder instead of the real Recycle Bin/Trash
# (so test runs never fill the user's bin). Still never a permanent delete.
TEST_TRASH_ENV = "AURASORT_TEST_TRASH_DIR"

if WIN:
    import ctypes
    from ctypes import wintypes

    class _SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", ctypes.c_void_p), ("pTo", ctypes.c_void_p),
                    ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", wintypes.BOOL), ("hNameMappings", ctypes.c_void_p),
                    ("lpszProgressTitle", wintypes.LPCWSTR)]

FO_DELETE = 0x3
FOF_SILENT, FOF_NOCONFIRMATION, FOF_ALLOWUNDO, FOF_NOERRORUI, FOF_WANTNUKEWARNING = 0x4, 0x10, 0x40, 0x400, 0x4000
# ALLOWUNDO = Recycle Bin. WANTNUKEWARNING = if Windows would destroy a file instead (too big for the bin), it asks first.
WIN_FLAGS = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI | FOF_WANTNUKEWARNING


class TrashResult:
    """Why: callers need per-file outcomes (trashed / skipped with a reason) to report honestly."""

    def __init__(self):
        self.trashed, self.failed = [], []   # failed: list of (path, reason)

    def fail(self, path, reason):
        self.failed.append((path, reason))


def bin_available(path):
    """Why: on Windows, network and removable drives have no Recycle Bin, so deleting there would be permanent.
    Android has no trash at all: AuraSort's own trash folder is used there (always available)."""
    if config.ANDROID or not WIN:
        return True
    return drive_type(drive_of(path)) in ("internal",)  # GetDriveTypeW DRIVE_FIXED (internal *and* external USB disks)


def _win_trash(paths, res):
    """Why: SHFileOperationW with FOF_ALLOWUNDO is the documented way to move files into the Recycle Bin."""
    for i in range(0, len(paths), config.TRASH_BATCH):
        batch = paths[i:i + config.TRASH_BATCH]
        buf = ctypes.create_unicode_buffer("\0".join(batch) + "\0")  # double-NUL terminated list
        op = _SHFILEOPSTRUCTW(hwnd=None, wFunc=FO_DELETE, pFrom=ctypes.addressof(buf), pTo=None, fFlags=WIN_FLAGS)  # buf stays alive
        rc = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
        for p in batch:
            if not os.path.lexists(p):
                res.trashed.append(p)
            elif op.fAnyOperationsAborted:
                res.fail(p, "cancelled - the file was not sent to the Recycle Bin")
            else:
                res.fail(p, f"Windows could not move it to the Recycle Bin (code {rc:#x})")


def _mac_trash(paths, res):
    """Why: asking Finder to delete keeps macOS 'Put Back'; paths go in as arguments, never into the script text."""
    script = ['on run argv', 'repeat with p in argv', 'tell application "Finder" to delete (POSIX file (contents of p) as alias)',
              'end repeat', 'end run']
    args = ["osascript"] + [a for line in script for a in ("-e", line)]
    for i in range(0, len(paths), config.TRASH_BATCH):
        batch = paths[i:i + config.TRASH_BATCH]
        try:
            subprocess.run(args + batch, capture_output=True, timeout=OSA_TIMEOUT_S, check=False)  # nosec B603 B607
        except (OSError, subprocess.SubprocessError) as ex:
            log.warning("Finder trash failed: %s", type(ex).__name__)
        for p in batch:
            if os.path.lexists(p):
                res.fail(p, "Finder did not move it to the Trash (check Automation permission for Finder)")
            else:
                res.trashed.append(p)


def _trashinfo_text(original_path, when):
    """Why: the freedesktop spec needs a .trashinfo file so the desktop can restore the file later."""
    quoted = urllib.parse.quote(original_path)
    return f"[Trash Info]\nPath={quoted}\nDeletionDate={when.strftime('%Y-%m-%dT%H:%M:%S')}\n"


def freedesktop_trash(path, trash_dir, relative_to=None):
    """Why: Linux fallback when 'gio trash' is missing: files/ + info/*.trashinfo, created atomically, never copied."""
    files_dir, info_dir = os.path.join(trash_dir, "files"), os.path.join(trash_dir, "info")
    os.makedirs(files_dir, mode=0o700, exist_ok=True)
    os.makedirs(info_dir, mode=0o700, exist_ok=True)
    base = os.path.basename(path.rstrip("/\\"))
    stored = os.path.relpath(path, relative_to) if relative_to else os.path.abspath(path)
    name, n = base, 1
    while True:
        info_path = os.path.join(info_dir, name + ".trashinfo")
        try:
            fd = os.open(info_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            break
        except FileExistsError:
            n += 1
            stem, ext = os.path.splitext(base)
            name = f"{stem}.{n}{ext}"
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(_trashinfo_text(stored, _dt.datetime.now()))
    try:
        os.rename(path, os.path.join(files_dir, name))   # same file system only: rename never deletes data
    except OSError:
        os.remove(info_path)
        raise
    return name


def _linux_trash_dir(path):
    """Why: files on the home file system use ~/.local/share/Trash, others use $topdir/.Trash-$uid (spec)."""
    home_trash = os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"), "Trash")
    try:
        if os.stat(os.path.dirname(os.path.abspath(path))).st_dev == os.stat(os.path.expanduser("~")).st_dev:
            return home_trash, None
    except OSError:
        pass
    top = drive_of(path)
    return os.path.join(top, f".Trash-{os.getuid()}"), top


def _linux_trash(paths, res):
    """Why: prefer 'gio trash' (desktop-integrated), fall back to the freedesktop Trash spec."""
    gio = shutil.which("gio")
    for p in paths:
        ok = False
        if gio:
            try:
                ok = subprocess.run([gio, "trash", "--", p], capture_output=True, timeout=OSA_TIMEOUT_S, check=False).returncode == 0  # nosec B603
            except (OSError, subprocess.SubprocessError):
                ok = False
        if not ok:
            try:
                tdir, rel = _linux_trash_dir(p)
                freedesktop_trash(p, tdir, rel)
                ok = True
            except OSError as ex:
                res.fail(p, f"could not move it to the Trash ({type(ex).__name__})")
                continue
        if os.path.lexists(p):
            res.fail(p, "still present after moving to the Trash")
        else:
            res.trashed.append(p)


def _test_trash(paths, res, folder):
    """Why: test runs 'trash' into a plain folder (moved with a unique name, never deleted)."""
    from .safety import unique_name
    os.makedirs(folder, exist_ok=True)
    for p in paths:
        try:
            shutil.move(p, os.path.join(folder, unique_name(folder, os.path.basename(p))))
            res.trashed.append(p)
        except OSError as ex:
            res.fail(p, f"could not move it to the test bin ({type(ex).__name__})")


def fake_bin_dir():
    """Why: the server prints a clear warning when the test bin is active."""
    return os.environ.get(TEST_TRASH_ENV, "")


def send_to_trash(paths):
    """Why: the only delete path in the app. Unsupported locations are skipped and reported, never deleted."""
    res = TrashResult()
    ok_paths = []
    for p in paths:
        if not os.path.lexists(p):
            res.fail(p, "file no longer exists")
        elif not bin_available(p):
            res.fail(p, "this drive has no Recycle Bin, so it was not deleted")
        else:
            ok_paths.append(os.path.abspath(p))
    if ok_paths:
        fake = fake_bin_dir()
        if fake:
            _test_trash(ok_paths, res, fake)
        elif config.ANDROID:
            _app_trash(ok_paths, res)
        else:
            (_win_trash if WIN else _mac_trash if MAC else _linux_trash)(ok_paths, res)
    return res


def _app_trash(paths, res):
    """Why: Android has no Recycle Bin; files go to AuraSort's own trash on the same storage (restorable in Settings)."""
    from . import apptrash
    for p in paths:
        try:
            apptrash.put(p, "deleted")
            res.trashed.append(p)
        except OSError as ex:
            res.fail(p, f"could not move it to the AuraSort trash ({type(ex).__name__})")


def where_name():
    """Why: the UI says where deleted files go on this system."""
    return "the AuraSort trash" if config.ANDROID else "the Trash" if MAC or config.LINUX else "the Recycle Bin"
