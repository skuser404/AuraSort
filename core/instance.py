"""One AuraSort server per data folder. Two servers writing the same index at once make scans fail ("database is locked"),
so a second start finds the running one and opens it instead."""
import json
import os

from . import config

if config.WIN:
    import msvcrt
else:
    import fcntl

_HELD = {}
PORT_FILE_NAME = "server.port"


def _lock_path():
    return config.DATA_DIR / config.LOCK_FILE_NAME


def acquire():
    """Why: an OS file lock is released automatically if the process dies, so a crash never leaves a stale lock behind."""
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    fh = open(_lock_path(), "a+b")  # noqa: SIM115 - held open for the life of the server on purpose
    try:
        fh.seek(0)
        if config.WIN:
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        return False
    _HELD["fh"] = fh
    return True


def remember_port(port):
    """Why: a second start reads this to open the running server's page."""
    (config.DATA_DIR / PORT_FILE_NAME).write_text(json.dumps(dict(port=port, pid=os.getpid())), encoding="utf-8")


def running_port():
    """Why: the port of the server that holds the lock (0 if unknown)."""
    try:
        return int(json.loads((config.DATA_DIR / PORT_FILE_NAME).read_text(encoding="utf-8")).get("port") or 0)
    except (OSError, ValueError, TypeError, AttributeError):
        return 0


def release():
    """Why: tests start and stop servers in one process."""
    fh = _HELD.pop("fh", None)
    if fh:
        try:
            if config.WIN:
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass   # closing the handle below releases the lock anyway
        fh.close()
