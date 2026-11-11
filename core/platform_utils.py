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

WIN, MAC, ANDROID = config.WIN, config.MAC, config.ANDROID
DRIVE_INFO_TIMEOUT_S = 2.5        # a dead network drive must not freeze the drive list
SUBPROCESS_TIMEOUT_S = 5

if WIN:
    import ctypes
    from ctypes import wintypes

# Windows GetDriveTypeW results
_WIN_DRIVE_TYPES = {2: "removable", 3: "internal", 4: "network", 5: "optical", 6: "ram"}
_WIN_EXTERNAL_BUSES = {4, 7, 12, 13}   # 1394, USB, SD, MMC (STORAGE_BUS_TYPE)
_KNOWN_FOLDERS = {  # Windows FOLDERIDs, so OneDrive-redirected or moved folders are found
    "Downloads": "{374DE290-123F-4565-9164-39C4925E467B}", "Documents": "{FDD39AD0-238F-46AF-ADB4-6C85480369C7}",
    "Desktop": "{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}", "Pictures": "{33E28130-4E1E-4676-835A-98395C3BC3BB}",
    "Videos": "{18989B1D-99B5-455B-841C-AB7C74E4DDFC}", "Music": "{4BD8D571-6D19-48D3-BE97-422220080E43}",
}
_FOLDERID_PROFILE = "{5E6C858F-0E22-4760-9AFE-EA3317B67173}"
QUICK_NAMES = ("Downloads", "Documents", "Desktop", "Pictures", "Movies" if MAC else "Videos", "Music")
_XDG_KEYS = {"Downloads": "XDG_DOWNLOAD_DIR", "Documents": "XDG_DOCUMENTS_DIR", "Desktop": "XDG_DESKTOP_DIR",
             "Pictures": "XDG_PICTURES_DIR", "Videos": "XDG_VIDEOS_DIR", "Music": "XDG_MUSIC_DIR"}
ANDROID_STORAGE = os.environ.get("AURASORT_ANDROID_STORAGE") or "/storage/emulated/0"   # the phone's shared storage (Termux also sees it as /sdcard and ~/storage/shared); the variable is for tests
_ANDROID_QUICK = (("Downloads", "Download"), ("Documents", "Documents"), ("Camera", "DCIM"), ("Pictures", "Pictures"),
                  ("Videos", "Movies"), ("Music", "Music"))

# Windows reparse points. Only "name surrogates" (symlinks, junctions, mount points) point somewhere else; OneDrive/iCloud
# placeholders, deduplicated files and app links are reparse points too, but they ARE the file and must be listed.
REPARSE_ATTR = 0x400
NAME_SURROGATE_BIT = 0x20000000
CLOUD_TAG_MASK, CLOUD_TAG = 0xFFFF0FFF, 0x9000001A   # IO_REPARSE_TAG_CLOUD and CLOUD_1..CLOUD_F (OneDrive Files On-Demand)
LONG_PATH_AT = 240                 # longer Windows paths get the \\?\ prefix (MAX_PATH is 260 without long-path support)


# ---------------- known folders ----------------
def _win_known_folder(guid):
    """Why: Desktop/Documents may live in OneDrive or on another drive; SHGetKnownFolderPath returns the real location."""
    class GUID(ctypes.Structure):
        _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]
    g = GUID()
    out = ctypes.c_wchar_p()
    try:
        ctypes.oledll.ole32.CLSIDFromString(guid, ctypes.byref(g))
        ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(g), 0, None, ctypes.byref(out))
        return out.value
    except OSError:
        return None
    finally:
        ctypes.windll.ole32.CoTaskMemFree(out)


def _same(a, b):
    try:
        return os.path.normcase(os.path.abspath(str(a))) == os.path.normcase(os.path.abspath(str(b)))
    except (TypeError, ValueError):
        return False


def _onedrive_roots():
    """Why: OneDrive sets these variables to its folders; a quick folder inside one is 'in OneDrive'."""
    return [os.environ[k] for k in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial") if os.environ.get(k)]


def _xdg_user_dirs(home):
    """Why: Linux desktops may rename Downloads etc. (other languages, other places); ~/.config/user-dirs.dirs says where."""
    out = {}
    cfg = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.join(str(home), ".config"), "user-dirs.dirs")
    if not _same(home, os.path.expanduser("~")):
        cfg = os.path.join(str(home), ".config", "user-dirs.dirs")   # a custom HOME (tests) reads its own file only
    try:
        with open(cfg, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                k, _, v = line.strip().partition("=")
                if k.startswith("XDG_") and v:
                    v = v.strip().strip('"').replace("$HOME", str(home))
                    if os.path.isabs(v) and not _same(v, home):   # XDG uses $HOME itself for "not set"
                        out[k] = v
    except OSError:
        pass
    return out


def dev_key(st_dev):
    """Why: Python 3.12+ on Windows reports the full 64-bit volume serial as st_dev; for about half of all drives it is
    2**63 or more, which SQLite cannot store (OverflowError). Every folder of a scan was then skipped and the scan found
    0 files. The same 64 bits as a signed number fit, and stay unique and comparable."""
    if st_dev is None:
        return None
    st_dev = int(st_dev) & 0xFFFFFFFFFFFFFFFF
    return st_dev - (1 << 64) if st_dev >= (1 << 63) else st_dev


def within(child, parent):
    """Why: containment checks must ignore case on Windows and never be fooled by '..'."""
    try:
        c, p = os.path.normcase(os.path.abspath(child)), os.path.normcase(os.path.abspath(parent))
        return os.path.commonpath([c, p]) == p
    except ValueError:
        return False


def quick_folders():
    """Why: Quick Scan covers the usual user folders, found where the OS really keeps them (never just assumed to be
    ~/Downloads): Windows Known Folders (OneDrive-redirected or moved to another drive), XDG user dirs on Linux, the
    phone's shared storage on Android. Each entry says where its path came from and whether it is in OneDrive."""
    home = config.HOME
    if ANDROID:
        root = ANDROID_STORAGE if os.path.isdir(ANDROID_STORAGE) else str(home)
        return [dict(name=n, path=os.path.join(root, d), exists=os.path.isdir(os.path.join(root, d)), source="android", onedrive=False)
                for n, d in _ANDROID_QUICK]
    real_profile = _win_known_folder(_FOLDERID_PROFILE) if WIN else None
    # The Known Folder API answers for the signed-in user. With a custom HOME (tests, fixtures) only answers inside it count.
    trust_os = WIN and real_profile and _same(real_profile, home)
    xdg = _xdg_user_dirs(home) if config.LINUX else {}
    out = []
    for name in QUICK_NAMES:
        path, source = None, "default"
        if WIN and name in _KNOWN_FOLDERS:
            kf = _win_known_folder(_KNOWN_FOLDERS[name])
            if kf and (trust_os or within(kf, home)):
                path, source = kf, "windows"
        elif config.LINUX and _XDG_KEYS.get(name) in xdg:
            path, source = xdg[_XDG_KEYS[name]], "xdg"
        path = path or str(home / name)
        out.append(dict(name=name, path=path, exists=os.path.isdir(path), source=source,
                        onedrive=any(within(path, r) for r in _onedrive_roots())))
    return out


def default_destination():
    """Why: sorted files go to one predictable folder in the user's home by default. On Android that is the phone's
    shared storage: the Termux home is private to Termux (the Gallery cannot see it, and it goes with the app)."""
    if ANDROID and os.path.isdir(ANDROID_STORAGE):
        return os.path.join(ANDROID_STORAGE, config.DEST_FOLDER_NAME)
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


def _os_name():
    """Why: the OS name for error reports, read WITHOUT the platform module's system()/release(): on Windows those query
    WMI through _wmi.pyd, which can crash the whole Python process when two request threads call it at once."""
    try:
        if WIN:
            v = sys.getwindowsversion()
            return f"Windows {'11' if v.major == 10 and v.build >= 22000 else v.major} (build {v.build})"
        if MAC:
            import platform as _platform   # mac_ver() reads a plist file; it never touches WMI
            return f"macOS {_platform.mac_ver()[0] or ''}".strip()
        return f"{os.uname().sysname} {os.uname().release}"
    except (OSError, AttributeError, ValueError):
        return "unknown"


OS_NAME = _os_name()
PYTHON_VERSION = ".".join(str(n) for n in sys.version_info[:3])
DRIVE_BLANK = dict(id="", root="", name="Drive", type="unknown", fs="", ready=False, recycle_bin=False, total=0, used=0, free=0)


def _android_roots():
    """Why: on Android the useful "drives" are the phone's shared storage and any SD card (/storage/XXXX-XXXX)."""
    roots = [ANDROID_STORAGE] if os.path.isdir(ANDROID_STORAGE) else []
    try:
        roots += sorted(e.path for e in os.scandir("/storage") if e.name not in ("emulated", "self") and e.is_dir())
    except OSError:
        pass
    return roots


def _android_drive(root):
    use = _usage(root)
    name = "Phone storage" if root == ANDROID_STORAGE else f"SD card ({os.path.basename(root)})"
    return dict(id=root, root=root, name=name, type="internal" if root == ANDROID_STORAGE else "removable", fs="",
                ready=use is not None, recycle_bin=True, **(use or {}))


def list_drives():
    """Why: the scan screen lists every drive; each probe has a timeout so an unplugged/dead drive can't hang the UI."""
    if ANDROID:
        return [{**DRIVE_BLANK, **_android_drive(r)} for r in _android_roots()]
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
            except Exception as ex:  # noqa: BLE001 - one broken drive must not hide the others
                root = f"{args[0]}:\\" if WIN else args[-2] if len(args) > 1 else args[0]
                if isinstance(ex, concurrent.futures.TimeoutError):
                    log.warning("drive %s did not answer in %s s (unplugged or asleep)", root, DRIVE_INFO_TIMEOUT_S)
                else:
                    log.warning("drive %s could not be read", root, exc_info=True)
                out.append(dict(id=root, root=root, name="Not responding", type="unknown", fs="", ready=False, recycle_bin=False))
    return [{**DRIVE_BLANK, **d} for d in out]   # every record has every key, even for a drive that is not ready


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
    if ANDROID:
        return ["/"] + _android_roots()
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
    """Why: symlinks and Windows junctions can create scan loops or escape a folder, so they are skipped. Other reparse
    points (OneDrive/iCloud placeholders, deduplicated files) are the real file: skipping those made whole OneDrive
    folders look empty."""
    if stat.S_ISLNK(entry_stat.st_mode):
        return True
    attrs = getattr(entry_stat, "st_file_attributes", 0)
    if not attrs & REPARSE_ATTR:
        return False
    tag = getattr(entry_stat, "st_reparse_tag", 0)
    return not tag or bool(tag & NAME_SURROGATE_BIT)   # unknown tag: treated as a link (the safe side)


def is_cloud_reparse(entry_stat):
    """Why: a OneDrive Files On-Demand placeholder (synced or online-only) carries a cloud reparse tag."""
    tag = getattr(entry_stat, "st_reparse_tag", 0)
    return bool(getattr(entry_stat, "st_file_attributes", 0) & REPARSE_ATTR and (tag & CLOUD_TAG_MASK) == CLOUD_TAG)


def is_online_only(entry_stat):
    """Why: reading an online-only file makes OneDrive/iCloud download it, so such files are listed from metadata only."""
    return bool(getattr(entry_stat, "st_file_attributes", 0) & config.CLOUD_ATTRS or getattr(entry_stat, "st_flags", 0) & config.MAC_DATALESS)


def long_path(path):
    """Why: Windows refuses paths over 260 characters unless long paths are enabled; the \\\\?\\ prefix lifts that limit."""
    if not WIN or len(path) < LONG_PATH_AT or path.startswith("\\\\?\\"):
        return path
    path = os.path.abspath(path)
    return "\\\\?\\UNC\\" + path[2:] if path.startswith("\\\\") else "\\\\?\\" + path


def is_hidden_system(entry_stat):
    """Why: Windows folders flagged hidden+system (e.g. system volume data) are never scanned."""
    attrs = getattr(entry_stat, "st_file_attributes", 0)
    return bool(attrs & 0x2) and bool(attrs & 0x4)


# ---------------- opening things (argument lists only, never a shell) ----------------
class NoFileManager(OSError):
    """Why: Termux on Android (and a Linux box without a desktop) has no file manager to open: the UI then shows the
    path with a Copy button instead of failing."""


def _spawn(args):
    """Why: launching helpers must never block the server or go through a shell."""
    try:
        subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)  # nosec B603  # fixed arg list
    except FileNotFoundError:
        raise NoFileManager(f"{args[0]} is not available here") from None


def open_file(path):
    """Why: 'Open file' hands a (non-executable) file to the default app (on Android: termux-open, if Termux has it)."""
    if ANDROID:
        if not shutil.which("termux-open"):
            raise NoFileManager("termux-open is not available")
        _spawn(["termux-open", path])
        return
    if WIN:
        os.startfile(path)  # nosec B606  # callers block executable types first
    elif MAC:
        _spawn(["open", "--", path])
    else:
        _spawn(["xdg-open", path])


def reveal(path):
    """Why: 'Open location' selects the file in Explorer/Finder instead of opening it."""
    if ANDROID:
        raise NoFileManager("Android has no way to open a folder from Termux")
    if WIN:
        _spawn(["explorer", "/select,", os.path.normpath(path)])
    elif MAC:
        _spawn(["open", "-R", "--", path])
    else:
        _spawn(["xdg-open", os.path.dirname(path)])


def open_folder(path):
    """Why: 'Open destination' shows a folder in the file manager."""
    if ANDROID:
        raise NoFileManager("Android has no way to open a folder from Termux")
    if WIN:
        _spawn(["explorer", os.path.normpath(path)])
    elif MAC:
        _spawn(["open", "--", path])
    else:
        _spawn(["xdg-open", path])


def open_url(url):
    """Why: the start-up page opens in the browser; Termux has no desktop browser hook, so it uses termux-open-url."""
    if ANDROID and shutil.which("termux-open-url"):
        _spawn(["termux-open-url", url])
        return
    import webbrowser
    webbrowser.open(url)


def open_trash():
    """Why: after deleting, the summary offers 'Open Recycle Bin' so files can be restored."""
    if ANDROID:
        raise NoFileManager("AuraSort's own trash is in Settings")
    if WIN:
        _spawn(["explorer", "shell:RecycleBinFolder"])
    elif MAC:
        _spawn(["open", os.path.expanduser("~/.Trash")])
    else:
        _spawn(["xdg-open", "trash:///"])


# ---------------- user / privileges ----------------
def user_display_name():
    """Why: the top bar greets the user by name; read locally and never sent anywhere else. On Android the account is an
    app id such as u0_a1282, not a name, so no name is shown."""
    if ANDROID:
        return ""
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


def device_name():
    """Why: the unlock screen names the computer ("Asked on LAPTOP-7F2"), so a PIN prompt on the wrong device is obvious."""
    try:
        import socket
        return socket.gethostname() or "this computer"
    except OSError:
        return "this computer"


def os_user():
    """Why: the OS account AuraSort runs as (the PIN protects AuraSort inside this account, not the account itself)."""
    try:
        return getpass.getuser()
    except (OSError, KeyError, ImportError):
        return ""


def relaunch_elevated(args, cwd):
    """Why: the optional "Restart with administrator permission" (Windows only). Windows shows its own UAC prompt;
    True only if the person accepted and the new process started. Your own folders never need this."""
    if not WIN:
        return False
    params = subprocess.list2cmdline(args)
    rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, cwd, 1)
    return int(rc) > 32   # <= 32 is an error code; 5 = the person declined the prompt


def is_admin():
    """Why: running as Administrator/root widens what a mistake could touch, so we warn."""
    if WIN:
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except (OSError, AttributeError):
            return False
    return hasattr(os, "geteuid") and os.geteuid() == 0


REPLACE_RETRIES = 40          # x 25 ms: Windows refuses to replace a file another thread is reading at that moment


def replace_file(tmp, dst):
    """Why: the atomic "write a temp file, then swap it in" step. On Windows os.replace fails with WinError 5 while another
    thread has the target open for reading; that lasts milliseconds, so it is retried instead of failing the request."""
    import time
    for i in range(REPLACE_RETRIES):
        try:
            os.replace(tmp, dst)
            return
        except PermissionError:
            if not WIN or i == REPLACE_RETRIES - 1:
                raise
            time.sleep(0.025)


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
