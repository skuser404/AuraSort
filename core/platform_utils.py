"""OS-specific helpers: drives, known folders, opening/revealing files, user name, admin check, private permissions."""
import concurrent.futures
import getpass
import os
import plistlib
import shutil
import stat
import string
import subprocess  # nosec B404  # only fixed argument lists, never shell=True
import sys
from pathlib import Path

from . import config
from .log import log

WIN, MAC = config.WIN, config.MAC
DRIVE_INFO_TIMEOUT_S = 2.5        # a dead network drive must not freeze the drive list
SUBPROCESS_TIMEOUT_S = 5

if WIN:
    import ctypes
    from ctypes import wintypes

# Windows GetDriveTypeW results
_WIN_DRIVE_TYPES = {2: "removable", 3: "internal", 4: "network", 5: "optical", 6: "ram"}
_WIN_EXTERNAL_BUSES = {4, 7, 12, 13}   # 1394, USB, SD, MMC (STORAGE_BUS_TYPE)
_KNOWN_FOLDERS = {  # Windows FOLDERIDs, so OneDrive-redirected folders are found
    "Downloads": "{374DE290-123F-4565-9164-39C4925E467B}", "Documents": "{FDD39AD0-238F-46AF-ADB4-6C85480369C7}",
    "Desktop": "{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}", "Pictures": "{33E28130-4E1E-4676-835A-98395C3BC3BB}",
    "Videos": "{18989B1D-99B5-455B-841C-AB7C74E4DDFC}", "Music": "{4BD8D571-6D19-48D3-BE97-422220080E43}",
}
QUICK_NAMES = ("Downloads", "Documents", "Desktop", "Pictures", "Movies" if MAC else "Videos", "Music")


# ---------------- known folders ----------------
def _win_known_folder(guid):
    """Why: Desktop/Documents may live in OneDrive; SHGetKnownFolderPath returns the real location."""
    class GUID(ctypes.Structure):
        _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]
    g = GUID()
    ctypes.oledll.ole32.CLSIDFromString(guid, ctypes.byref(g))
    out = ctypes.c_wchar_p()
    try:
        ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(g), 0, None, ctypes.byref(out))
        return out.value
    except OSError:
        return None
    finally:
        ctypes.windll.ole32.CoTaskMemFree(out)


def within(child, parent):
    """Why: containment checks must ignore case on Windows and never be fooled by '..'."""
    try:
        c, p = os.path.normcase(os.path.abspath(child)), os.path.normcase(os.path.abspath(parent))
        return os.path.commonpath([c, p]) == p
    except ValueError:
        return False


def quick_folders():
    """Why: Quick Scan covers the usual user folders (Downloads, Documents, Desktop, Pictures, Videos/Movies, Music)."""
    out = []
    for name in QUICK_NAMES:
        path = None
        if WIN and name in _KNOWN_FOLDERS:
            kf = _win_known_folder(_KNOWN_FOLDERS[name])
            if kf and within(kf, config.HOME):  # honour a custom HOME (tests) instead of the real profile
                path = kf
        path = path or str(config.HOME / name)
        out.append(dict(name=name, path=path, exists=os.path.isdir(path)))
    return out


def default_destination():
    """Why: sorted files go to one predictable folder in the user's home by default."""
    return str(config.HOME / config.DEST_FOLDER_NAME)


# ---------------- drives ----------------
def _usage(root):
    """Why: total/used/free for one mount; None when the drive is not ready (empty card reader)."""
    try:
        u = shutil.disk_usage(root)
        return dict(total=u.total, used=u.used, free=u.free)
    except OSError:
        return None


def _win_volume(root):
    """Why: the volume label and file system make drives recognisable ("Backup (E:)")."""
    name, fs = ctypes.create_unicode_buffer(261), ctypes.create_unicode_buffer(261)
    ok = ctypes.windll.kernel32.GetVolumeInformationW(root, name, 261, None, None, None, fs, 261)
    return (name.value, fs.value) if ok else ("", "")


def _win_is_external(letter):
    """Why: USB/SD disks report as 'fixed'; the storage bus type tells internal from external."""
    k32 = ctypes.windll.kernel32
    k32.CreateFileW.restype = wintypes.HANDLE
    h = k32.CreateFileW(f"\\\\.\\{letter}:", 0, 3, None, 3, 0, None)  # no access rights needed, share read|write
    if not h or h == wintypes.HANDLE(-1).value:
        return False
    try:
        query = (ctypes.c_ubyte * 12)()             # STORAGE_PROPERTY_QUERY{StorageDeviceProperty, PropertyStandardQuery}
        buf = (ctypes.c_ubyte * 1024)()
        got = wintypes.DWORD()
        ok = k32.DeviceIoControl(wintypes.HANDLE(h), 0x2D1400, query, 12, buf, 1024, ctypes.byref(got), None)
        if not ok or got.value < 32:
            return False
        removable, bus = buf[10], int.from_bytes(bytes(buf[28:32]), "little")
        return bool(removable) or bus in _WIN_EXTERNAL_BUSES
    finally:
        k32.CloseHandle(wintypes.HANDLE(h))


def _win_seek_penalty(letter):
    """Why: SSD or spinning disk: IOCTL_STORAGE_QUERY_PROPERTY(StorageDeviceSeekPenaltyProperty). None if unknown."""
    k32 = ctypes.windll.kernel32
    k32.CreateFileW.restype = wintypes.HANDLE
    h = k32.CreateFileW(f"\\\\.\\{letter}:", 0, 3, None, 3, 0, None)
    if not h or h == wintypes.HANDLE(-1).value:
        return None
    try:
        query = (ctypes.c_ubyte * 12)()
        query[0] = 7                                   # PropertyId = StorageDeviceSeekPenaltyProperty
        buf = (ctypes.c_ubyte * 12)()
        got = wintypes.DWORD()
        if not k32.DeviceIoControl(wintypes.HANDLE(h), 0x2D1400, query, 12, buf, 12, ctypes.byref(got), None) or got.value < 9:
            return None
        return bool(buf[8])                            # DEVICE_SEEK_PENALTY_DESCRIPTOR.IncursSeekPenalty
    finally:
        k32.CloseHandle(wintypes.HANDLE(h))


_MEDIA = {}


def drive_media(root):
    """Why: the scan sizes its thread pool by drive type: ssd, hdd, usb, network or unknown (cached per drive)."""
    if root in _MEDIA:
        return _MEDIA[root]
    kind, media = drive_type(root), "unknown"
    try:
        if kind == "network":
            media = "network"
        elif kind in ("external", "removable"):
            media = "usb"
        elif WIN and len(root) >= 2 and root[1] == ":":
            pen = _win_seek_penalty(root[0])
            media = "unknown" if pen is None else "hdd" if pen else "ssd"
        elif MAC:
            media = "ssd"                              # internal Mac storage has been flash for years
        else:
            media = _linux_media(root)
    except (OSError, AttributeError, ValueError):
        media = "unknown"
    _MEDIA[root] = media
    return media


def _linux_media(root):
    """Why: /sys/block/<disk>/queue/rotational says 1 for spinning disks."""
    dev = os.stat(root).st_dev
    major, minor = os.major(dev), os.minor(dev)
    try:
        with open(f"/sys/dev/block/{major}:{minor}/../queue/rotational", encoding="ascii") as fh:
            return "hdd" if fh.read().strip() == "1" else "ssd"
    except OSError:
        try:
            with open(f"/sys/dev/block/{major}:{minor}/queue/rotational", encoding="ascii") as fh:
                return "hdd" if fh.read().strip() == "1" else "ssd"
        except OSError:
            return "unknown"


def _win_drive(letter):
    """Why: one dict per drive letter with type, label, file system and space."""
    root = f"{letter}:\\"
    kind = _WIN_DRIVE_TYPES.get(ctypes.windll.kernel32.GetDriveTypeW(root), "unknown")
    label, fs = _win_volume(root) if kind != "network" else ("", "")
    if kind == "internal" and _win_is_external(letter):
        kind = "external"
    use = _usage(root)
    return dict(id=root, root=root, name=label or {"internal": "Local Disk", "network": "Network drive"}.get(kind, "Drive"),
                type=kind, fs=fs, ready=use is not None, recycle_bin=kind in ("internal", "external"), **(use or {}))


def _win_drives():
    """Why: Windows exposes drives as letters A-Z; GetLogicalDrives says which exist."""
    mask = ctypes.windll.kernel32.GetLogicalDrives()
    return [c for i, c in enumerate(string.ascii_uppercase) if mask & (1 << i)]


def _mac_drive(mount):
    """Why: diskutil tells internal vs external disks on macOS; network mounts have no disk info."""
    use = _usage(mount)
    kind, name, fs = "internal", os.path.basename(mount.rstrip("/")) or "Macintosh HD", ""
    try:
        res = subprocess.run(["diskutil", "info", "-plist", mount], capture_output=True, timeout=SUBPROCESS_TIMEOUT_S, check=False)  # nosec B603 B607
        info = plistlib.loads(res.stdout) if res.returncode == 0 else {}
        name = info.get("VolumeName") or name
        fs = info.get("FilesystemName") or info.get("FilesystemType", "")
        if not info:
            kind = "network"
        elif not info.get("Internal", True) or info.get("RemovableMedia") or info.get("Ejectable"):
            kind = "external"
    except (OSError, subprocess.SubprocessError, plistlib.InvalidFileException):
        kind = "network" if mount != "/" else "internal"
    return dict(id=mount, root=mount, name=name, type=kind, fs=fs, ready=use is not None, recycle_bin=True, **(use or {}))


def _mac_mounts():
    """Why: the startup disk is '/', every other volume appears in /Volumes (one entry points back to '/')."""
    mounts = ["/"]
    try:
        for e in os.scandir("/Volumes"):
            if e.is_symlink() and os.path.realpath(e.path) == "/":
                continue
            mounts.append(e.path)
    except OSError:
        pass
    return mounts


_LINUX_REAL_FS = {"ext2", "ext3", "ext4", "xfs", "btrfs", "zfs", "f2fs", "ntfs", "ntfs3", "fuseblk", "vfat", "exfat", "hfsplus", "apfs"}
_LINUX_NET_FS = {"nfs", "nfs4", "cifs", "smb3", "smbfs", "sshfs", "fuse.sshfs", "9p"}


def _linux_mounts():
    """Why: /proc/mounts lists every mount; only real disks and network shares are useful to scan."""
    out = []
    try:
        with open("/proc/mounts", encoding="utf-8") as f:
            for line in f:
                dev, mnt, fs = line.split()[:3]
                mnt = mnt.replace("\\040", " ")
                if fs in _LINUX_REAL_FS | _LINUX_NET_FS and not mnt.startswith(("/proc", "/sys", "/dev", "/run", "/snap", "/boot")):
                    out.append((dev, mnt, fs))
    except OSError:
        out.append(("", "/", ""))
    return out


def _linux_drive(dev, mount, fs):
    """Why: network vs removable vs internal, read from the file system type and /sys."""
    kind = "network" if fs in _LINUX_NET_FS else "internal"
    base = os.path.basename(dev).rstrip("0123456789")
    try:
        with open(f"/sys/block/{base}/removable", encoding="utf-8") as f:
            if f.read().strip() == "1":
                kind = "external"
    except OSError:
        pass
    if mount.startswith(("/media/", "/run/media/", "/mnt/")) and kind == "internal":
        kind = "external"
    use = _usage(mount)
    return dict(id=mount, root=mount, name=os.path.basename(mount) or "System", type=kind, fs=fs,
                ready=use is not None, recycle_bin=True, **(use or {}))


def list_drives():
    """Why: the scan screen lists every drive; each probe has a timeout so an unplugged/dead drive can't hang the UI."""
    if WIN:
        jobs = [(_win_drive, (c,)) for c in _win_drives()]
    elif MAC:
        jobs = [(_mac_drive, (m,)) for m in _mac_mounts()]
    else:
        jobs = [(_linux_drive, m) for m in _linux_mounts()]
    out = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(jobs))) as pool:
        futs = [(pool.submit(fn, *args), args) for fn, args in jobs]
        for fut, args in futs:
            try:
                out.append(fut.result(timeout=DRIVE_INFO_TIMEOUT_S))
            except Exception:  # noqa: BLE001 - one broken drive must not hide the others
                root = f"{args[0]}:\\" if WIN else args[-2] if len(args) > 1 else args[0]
                out.append(dict(id=root, root=root, name="Not responding", type="unknown", fs="", ready=False, recycle_bin=False))
    return out


def drive_of(path):
    """Why: per-drive grouping (scan worker pools, snapshots, trash support) needs the mount a path lives on."""
    p = os.path.abspath(path)
    if WIN:
        drive = os.path.splitdrive(p)[0]
        return (drive + "\\") if drive and not drive.startswith("\\\\") else drive or p
    best = "/"
    for d in list_mount_points():
        if within(p, d) and len(d) > len(best):
            best = d
    return best


def list_mount_points():
    """Why: cheap mount list (no disk probing) for drive_of on macOS/Linux."""
    if MAC:
        return _mac_mounts()
    if WIN:
        return [f"{c}:\\" for c in _win_drives()]
    return [m for _, m, _ in _linux_mounts()]


def drive_type(root):
    """Why: Recycle Bin availability depends on the drive type (no bin on network/removable drives)."""
    if WIN:
        return _WIN_DRIVE_TYPES.get(ctypes.windll.kernel32.GetDriveTypeW(root), "unknown")
    return "internal"


# ---------------- timestamps ----------------
CREATED_SUPPORTED = WIN or MAC
CREATED_NOTE = "" if CREATED_SUPPORTED else "Linux file systems do not reliably record when a file was created, so the 'Created' date is unavailable."


def created_time(st):
    """Why: creation time is st_birthtime (macOS, Windows on Python 3.12+), st_ctime on older Windows, unknown on Linux."""
    bt = getattr(st, "st_birthtime", None)
    if bt:
        return bt
    return st.st_ctime if WIN else None


def is_reparse_or_link(entry_stat):
    """Why: symlinks and Windows junctions can create scan loops or escape a folder, so they are skipped."""
    if stat.S_ISLNK(entry_stat.st_mode):
        return True
    attrs = getattr(entry_stat, "st_file_attributes", 0)
    return bool(attrs & 0x400)  # FILE_ATTRIBUTE_REPARSE_POINT


def is_hidden_system(entry_stat):
    """Why: Windows folders flagged hidden+system (e.g. system volume data) are never scanned."""
    attrs = getattr(entry_stat, "st_file_attributes", 0)
    return bool(attrs & 0x2) and bool(attrs & 0x4)


# ---------------- opening things (argument lists only, never a shell) ----------------
def _spawn(args):
    """Why: launching helpers must never block the server or go through a shell."""
    subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)  # nosec B603  # fixed arg list


def open_file(path):
    """Why: 'Open file' hands a (non-executable) file to the default app."""
    if WIN:
        os.startfile(path)  # nosec B606  # callers block executable types first
    elif MAC:
        _spawn(["open", "--", path])
    else:
        _spawn(["xdg-open", path])


def reveal(path):
    """Why: 'Open location' selects the file in Explorer/Finder instead of opening it."""
    if WIN:
        _spawn(["explorer", "/select,", os.path.normpath(path)])
    elif MAC:
        _spawn(["open", "-R", "--", path])
    else:
        _spawn(["xdg-open", os.path.dirname(path)])


def open_folder(path):
    """Why: 'Open destination' shows a folder in the file manager."""
    if WIN:
        _spawn(["explorer", os.path.normpath(path)])
    elif MAC:
        _spawn(["open", "--", path])
    else:
        _spawn(["xdg-open", path])


def open_trash():
    """Why: after deleting, the summary offers 'Open Recycle Bin' so files can be restored."""
    if WIN:
        _spawn(["explorer", "shell:RecycleBinFolder"])
    elif MAC:
        _spawn(["open", os.path.expanduser("~/.Trash")])
    else:
        _spawn(["xdg-open", "trash:///"])


# ---------------- user / privileges ----------------
def user_display_name():
    """Why: the top bar greets the user by name; read locally and never sent anywhere else."""
    if WIN:
        try:
            size = wintypes.ULONG(256)
            buf = ctypes.create_unicode_buffer(256)
            if ctypes.windll.secur32.GetUserNameExW(3, buf, ctypes.byref(size)) and buf.value.strip():  # NameDisplay
                return buf.value.strip()
        except (OSError, AttributeError):
            pass
    try:
        return getpass.getuser()
    except (OSError, KeyError):
        return ""


def is_admin():
    """Why: running as Administrator/root widens what a mistake could touch, so we warn."""
    if WIN:
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except (OSError, AttributeError):
            return False
    return hasattr(os, "geteuid") and os.geteuid() == 0


def make_private(path, is_dir=None):
    """Why: history, index and snapshots describe the user's files, so only the user may read them."""
    path = Path(path)
    is_dir = path.is_dir() if is_dir is None else is_dir
    try:
        if WIN:
            user = os.environ.get("USERNAME")
            if not user:
                return
            domain = os.environ.get("USERDOMAIN")
            who = f"{domain}\\{user}" if domain else user
            grant = f"{who}:(OI)(CI)F" if is_dir else f"{who}:F"
            subprocess.run(["icacls", str(path), "/inheritance:r", "/grant:r", grant], capture_output=True,  # nosec B603 B607
                           timeout=SUBPROCESS_TIMEOUT_S, check=False)
        else:
            os.chmod(path, 0o700 if is_dir else 0o600)
    except (OSError, subprocess.SubprocessError) as ex:
        log.warning("could not restrict permissions: %s", type(ex).__name__)


def python_cmd():
    """Why: docs and shortcuts must name the interpreter that is actually running."""
    return sys.executable
