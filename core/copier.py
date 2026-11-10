"""Fast, verified copies ("pin to pin").
1. copy into a temporary "<name>.aurasort-part" file in the destination folder (the OS fast path where possible),
2. for moves, flush and fsync it, 3. verify (size always; full BLAKE2b hash, or sampled blocks for "fast"),
4. copy timestamps/permissions and rename it atomically to the final name, never over an existing file,
5. for a move across drives, delete the source only after all of that succeeded. On any failure the source is kept and
only our own partial file is removed."""
import errno
import hashlib
import os
import secrets
import shutil
import time

from . import config
from .safety import unique_name

PART_SUFFIX = ".aurasort-part"
VERIFY_MODES = ("full", "fast", "size")
BUF = 4 * 1024 * 1024                  # reusable copy buffer (never whole files in memory)
NOBUF_MIN = 256 * 1024 * 1024          # Windows: unbuffered I/O for very large files
SAMPLE_BLOCK = 64 * 1024
SAMPLE_COUNT = 8
LOCK_RETRY_S = (0.2, 0.6, 1.5)         # locked (in use) files: retry with backoff, then skip
WIN_SHARING = (32, 33)                 # ERROR_SHARING_VIOLATION, ERROR_LOCK_VIOLATION
WIN_DISK_FULL = (39, 112)              # ERROR_HANDLE_DISK_FULL, ERROR_DISK_FULL
LONG_PATH = 240


class CopyError(OSError):
    """Why: one friendly reason per failed file; the source is always intact when this is raised."""


class DiskFull(CopyError):
    """Why: a full destination stops the whole job cleanly instead of failing file after file."""


def long_path(p):
    """Why: Windows paths over 260 characters need the \\\\?\\ prefix."""
    if not config.WIN or len(p) < LONG_PATH or p.startswith("\\\\?\\"):
        return p
    p = os.path.abspath(p)
    return "\\\\?\\UNC\\" + p[2:] if p.startswith("\\\\") else "\\\\?\\" + p


def same_volume(src, dst_dir):
    """Why: same device = a rename (instant, nothing to verify)."""
    try:
        return os.stat(src).st_dev == os.stat(dst_dir).st_dev
    except OSError:
        return False


def _is_disk_full(e):
    return getattr(e, "errno", None) == errno.ENOSPC or getattr(e, "winerror", None) in WIN_DISK_FULL


def _is_locked(e):
    return getattr(e, "winerror", None) in WIN_SHARING


# ---------------- the copy itself ----------------
if config.WIN:
    import ctypes
    from ctypes import wintypes
    _PROGRESS = ctypes.WINFUNCTYPE(wintypes.DWORD, ctypes.c_longlong, ctypes.c_longlong, ctypes.c_longlong, ctypes.c_longlong,
                                   wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE, wintypes.HANDLE, wintypes.LPVOID)
    COPY_FILE_FAIL_IF_EXISTS, COPY_FILE_NO_BUFFERING, PROGRESS_CONTINUE, PROGRESS_CANCEL = 0x1, 0x1000, 0, 1
    _K32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _K32.CopyFileExW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, _PROGRESS, wintypes.LPVOID, ctypes.POINTER(wintypes.BOOL), wintypes.DWORD]


def _win_copy(src, tmp, on_bytes, should_stop):
    """Why: CopyFileExW is the fastest Windows path; its callback reports progress and lets us cancel."""
    seen = [0]

    def cb(total, done, *_):
        if on_bytes and done > seen[0]:
            on_bytes(done - seen[0])
            seen[0] = done
        return PROGRESS_CANCEL if should_stop and should_stop() else PROGRESS_CONTINUE
    flags = COPY_FILE_FAIL_IF_EXISTS | (COPY_FILE_NO_BUFFERING if os.path.getsize(src) >= NOBUF_MIN else 0)
    cancel = wintypes.BOOL(False)
    routine = _PROGRESS(cb) if (on_bytes or should_stop) else ctypes.cast(None, _PROGRESS)   # small files: no Python callback at all
    if not _K32.CopyFileExW(long_path(src), long_path(tmp), routine, None, ctypes.byref(cancel), flags):
        err = ctypes.get_last_error()
        raise OSError(None, ctypes.FormatError(err).strip(), src, err)


def _buffered_copy(src, tmp, on_bytes, should_stop):
    """Why: portable fallback with progress and cancel: one reusable buffer, readinto, exclusive create."""
    buf = bytearray(BUF)
    view = memoryview(buf)
    with open(long_path(src), "rb") as fi, open(long_path(tmp), "xb") as fo:
        while True:
            if should_stop and should_stop():
                raise CopyError("cancelled")
            n = fi.readinto(buf)
            if not n:
                break
            fo.write(view[:n])
            if on_bytes:
                on_bytes(n)


def _mac_clone(src, tmp):
    """Why: on one APFS volume a copy can be an instant copy-on-write clone."""
    import ctypes
    libc = ctypes.CDLL(None, use_errno=True)
    if not hasattr(libc, "clonefile") or libc.clonefile(os.fsencode(src), os.fsencode(tmp), 0) != 0:
        raise OSError(ctypes.get_errno(), "clone failed")


def _raw_copy(src, tmp, size, on_bytes, should_stop, clone_ok):
    """Why: pick the fastest primitive the OS offers for this file."""
    if config.WIN:
        return _win_copy(src, tmp, on_bytes, should_stop)
    if config.MAC and clone_ok:
        try:
            _mac_clone(src, tmp)
            if on_bytes:
                on_bytes(size)
            return None
        except OSError:
            pass
    if size < NOBUF_MIN // 4:   # small/medium: shutil's kernel fast path (sendfile / copy_file_range / fcopyfile)
        if os.path.lexists(tmp):
            raise FileExistsError(tmp)
        shutil.copyfile(src, tmp, follow_symlinks=False)
        if on_bytes:
            on_bytes(size)
        return None
    return _buffered_copy(src, tmp, on_bytes, should_stop)


# ---------------- verification ----------------
def file_hash(path):
    """Why: full-content BLAKE2b (fast, in hashlib) for the default "full" verification."""
    h, buf = hashlib.blake2b(digest_size=32), bytearray(BUF)
    with open(long_path(path), "rb") as fh:
        while True:
            n = fh.readinto(buf)
            if not n:
                break
            h.update(memoryview(buf)[:n])
    return h.hexdigest()


def sampled_hash(path, size):
    """Why: "fast verify" for huge jobs: size + first, last and evenly spaced blocks."""
    h = hashlib.blake2b(digest_size=32)
    h.update(str(size).encode())
    with open(long_path(path), "rb") as fh:
        for k in range(SAMPLE_COUNT + 2):
            pos = 0 if k == 0 else max(0, size - SAMPLE_BLOCK) if k == SAMPLE_COUNT + 1 else size * k // (SAMPLE_COUNT + 1)
            fh.seek(pos)
            h.update(fh.read(SAMPLE_BLOCK))
    return h.hexdigest()


def verify(src, tmp, size, mode):
    """Why: size always; then the chosen content check."""
    if os.path.getsize(long_path(tmp)) != size:
        return False
    if mode == "full":
        return file_hash(src) == file_hash(tmp)
    if mode == "fast":
        return sampled_hash(src, size) == sampled_hash(tmp, size)
    return True


def _fsync(path):
    """Why: the copy must be on the disk, not just in a cache, before the source may go."""
    with open(long_path(path), "rb+") as fh:
        os.fsync(fh.fileno())


def _place(tmp, dst_dir, name):
    """Why: atomic rename that never replaces an existing file (Windows rename refuses; POSIX uses link + unlink)."""
    for _ in range(50):
        final = os.path.join(dst_dir, unique_name(dst_dir, name))
        try:
            if config.WIN:
                os.rename(long_path(tmp), long_path(final))
            else:
                os.link(tmp, final)
                os.unlink(tmp)
            return final
        except FileExistsError:
            continue
    raise CopyError("could not find a free name")


def copy_verified(src, dst_dir, name, verify_mode="full", move=False, on_bytes=None, should_stop=None, sleep=time.sleep, durable=None):
    """Why: the single cross-drive copy/move primitive. Returns the final path; raises CopyError (source kept).
    durable (default: only for moves) fsyncs the copy before the source is removed. A plain copy never touches the
    original, so it skips the per-file fsync (much faster on many small files) but is still fully verified."""
    durable = move if durable is None else durable
    size = os.path.getsize(src)
    tmp = os.path.join(dst_dir, f"{name}.{secrets.token_hex(4)}{PART_SUFFIX}")   # unique without probing the folder
    clone_ok = same_volume(src, dst_dir)
    try:
        for attempt in range(len(LOCK_RETRY_S) + 1):
            try:
                _raw_copy(src, tmp, size, on_bytes, should_stop, clone_ok)
                break
            except OSError as e:
                _drop(tmp)
                if _is_disk_full(e):
                    raise DiskFull("the destination drive is full") from None
                if _is_locked(e) and attempt < len(LOCK_RETRY_S):
                    sleep(LOCK_RETRY_S[attempt])
                    continue
                if should_stop and should_stop():
                    raise CopyError("cancelled") from None
                raise CopyError("in use by another program" if _is_locked(e) else f"could not copy ({e.strerror or type(e).__name__})") from None
        if durable:
            _fsync(tmp)
        if not verify(src, tmp, size, verify_mode):
            raise CopyError("the copy did not match the original, so the original was kept")
        shutil.copystat(src, long_path(tmp), follow_symlinks=False)
        final = _place(tmp, dst_dir, name)
    except BaseException:
        _drop(tmp)
        raise
    if move:
        try:
            os.remove(long_path(src))
        except OSError as e:
            raise CopyError(f"copied and verified, but the original could not be removed ({e.strerror}); both copies exist") from None
    return final


def _drop(tmp):
    """Why: only our own partial file is ever removed."""
    try:
        if tmp.endswith(PART_SUFFIX) and os.path.lexists(tmp):
            os.remove(long_path(tmp))
    except OSError:
        pass


def leftovers(folders):
    """Why: after a crash, partial copies we created are found so the user can clean them up."""
    out = []
    for root in folders:
        if not os.path.isdir(root):
            continue
        for base, _, files in os.walk(root):
            out += [os.path.join(base, f) for f in files if f.endswith(PART_SUFFIX)]
    return out

