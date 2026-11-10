"""Cloud API key storage. Default: this session's memory only. Optional: the operating system's keychain
(Windows Credential Manager, macOS Keychain via `security`, Linux Secret Service via `secret-tool`).
Never stored in plain files, URLs, logs or the browser."""
import shutil
import subprocess  # nosec B404  # fixed argument lists only

from . import config
from .log import add_secret

_session = {"key": ""}
TIMEOUT_S = 10
ACCOUNT = "aurasort"


def set_session(key):
    """Why: the key lives in memory for this run (and is masked in the log if it ever appears)."""
    _session["key"] = key or ""
    if key:
        add_secret(key)


def get_session():
    """Why: 'is a key loaded right now' without touching the keychain."""
    return _session["key"]


def get():
    """Why: session key first, then the keychain (if the user chose to remember it)."""
    if _session["key"]:
        return _session["key"]
    key = _keychain_read()
    if key:
        set_session(key)
    return key


def has_saved():
    return bool(_keychain_read())


def clear():
    """Why: 'Withdraw consent / reset AI settings' removes the key from memory and the keychain."""
    _session["key"] = ""
    _keychain_delete()


# ---------------- OS keychains ----------------
if config.WIN:
    import ctypes
    from ctypes import wintypes

    class _CRED(ctypes.Structure):
        _fields_ = [("Flags", wintypes.DWORD), ("Type", wintypes.DWORD), ("TargetName", wintypes.LPWSTR), ("Comment", wintypes.LPWSTR),
                    ("LastWritten", wintypes.FILETIME), ("CredentialBlobSize", wintypes.DWORD), ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
                    ("Persist", wintypes.DWORD), ("AttributeCount", wintypes.DWORD), ("Attributes", ctypes.c_void_p),
                    ("TargetAlias", wintypes.LPWSTR), ("UserName", wintypes.LPWSTR)]
    CRED_TYPE_GENERIC, CRED_PERSIST_LOCAL_MACHINE = 1, 2


def remember(key):
    """Why: optional 'Remember in the OS keychain'. Returns False if no keychain is available."""
    set_session(key)
    try:
        if config.WIN:
            blob = key.encode("utf-16-le")
            buf = (ctypes.c_ubyte * len(blob)).from_buffer_copy(blob)
            cred = _CRED(Type=CRED_TYPE_GENERIC, TargetName=config.AI_KEYCHAIN_TARGET, CredentialBlobSize=len(blob),
                         CredentialBlob=ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte)), Persist=CRED_PERSIST_LOCAL_MACHINE, UserName=ACCOUNT)
            return bool(ctypes.windll.advapi32.CredWriteW(ctypes.byref(cred), 0))
        if config.MAC and shutil.which("security"):
            # note: macOS `security` takes the secret as an argument; it is visible to your own processes for a moment
            r = subprocess.run(["security", "add-generic-password", "-U", "-a", ACCOUNT, "-s", config.AI_KEYCHAIN_TARGET, "-w", key],  # nosec B603 B607
                               capture_output=True, timeout=TIMEOUT_S, check=False)
            return r.returncode == 0
        tool = shutil.which("secret-tool")
        if tool:
            r = subprocess.run([tool, "store", "--label", config.AI_KEYCHAIN_TARGET, "service", config.AI_KEYCHAIN_TARGET, "account", ACCOUNT],  # nosec B603
                               input=key.encode(), capture_output=True, timeout=TIMEOUT_S, check=False)
            return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False
    return False


def _keychain_read():
    try:
        if config.WIN:
            p = ctypes.POINTER(_CRED)()
            if not ctypes.windll.advapi32.CredReadW(config.AI_KEYCHAIN_TARGET, CRED_TYPE_GENERIC, 0, ctypes.byref(p)):
                return ""
            try:
                c = p.contents
                return bytes(c.CredentialBlob[:c.CredentialBlobSize]).decode("utf-16-le")
            finally:
                ctypes.windll.advapi32.CredFree(p)
        if config.MAC and shutil.which("security"):
            r = subprocess.run(["security", "find-generic-password", "-a", ACCOUNT, "-s", config.AI_KEYCHAIN_TARGET, "-w"],  # nosec B603 B607
                               capture_output=True, text=True, timeout=TIMEOUT_S, check=False)
            return r.stdout.strip() if r.returncode == 0 else ""
        tool = shutil.which("secret-tool")
        if tool:
            r = subprocess.run([tool, "lookup", "service", config.AI_KEYCHAIN_TARGET, "account", ACCOUNT], capture_output=True, text=True, timeout=TIMEOUT_S, check=False)  # nosec B603
            return r.stdout.strip() if r.returncode == 0 else ""
    except (OSError, ValueError, subprocess.SubprocessError):
        return ""
    return ""


def _keychain_delete():
    try:
        if config.WIN:
            ctypes.windll.advapi32.CredDeleteW(config.AI_KEYCHAIN_TARGET, CRED_TYPE_GENERIC, 0)
        elif config.MAC and shutil.which("security"):
            subprocess.run(["security", "delete-generic-password", "-a", ACCOUNT, "-s", config.AI_KEYCHAIN_TARGET], capture_output=True, timeout=TIMEOUT_S, check=False)  # nosec B603 B607
        elif shutil.which("secret-tool"):
            subprocess.run([shutil.which("secret-tool"), "clear", "service", config.AI_KEYCHAIN_TARGET, "account", ACCOUNT], capture_output=True, timeout=TIMEOUT_S, check=False)  # nosec B603
    except (OSError, subprocess.SubprocessError):
        pass
