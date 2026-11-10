"""Logging with redaction, so tokens and personal paths never reach the log file in clear text.

Full tracebacks are kept (in the terminal and in ~/.aurasort/logs/server.log) because a bug report needs them;
the redactor runs on the final formatted text, so the traceback is masked too. File contents are never logged."""
import logging
import logging.handlers
import sys
import threading

from . import config

log = logging.getLogger(config.APP_SLUG)


class Redactor:
    """Why: logs end up in bug reports, so secrets become [token] and the home folder becomes ~."""

    def __init__(self):
        self.secrets = set()

    def __call__(self, text):
        for s in self.secrets:
            text = text.replace(s, "[token]")
        home = str(config.HOME)
        return text.replace(home, "~").replace(home.replace("\\", "/"), "~")


class SafeFormatter(logging.Formatter):
    """Why: redact the whole formatted record (message *and* traceback), not just the message."""

    def format(self, record):
        return _redact(super().format(record))


_redact = Redactor()
FORMAT = "%(asctime)s %(levelname)s [%(threadName)s] %(message)s"


def add_secret(secret):
    """Why: the per-run token must be masked in every later log line."""
    _redact.secrets.add(secret)


def redact(text):
    """Why: error reports shown in the UI use the same masking as the log."""
    return _redact(str(text))


def close_file():
    """Why: 'Delete my AuraSort data' must release the log file (Windows cannot delete an open file); returns whether one was open."""
    had = False
    for hd in list(log.handlers):
        if isinstance(hd, logging.FileHandler):
            log.removeHandler(hd)
            hd.close()
            had = True
    return had


def reopen_file():
    """Why: after the data folder was recreated, logging to the file continues."""
    for hd in list(log.handlers):
        log.removeHandler(hd)
        hd.close()
    return setup(to_file=True)


def _thread_crash(args):
    """Why: an exception that escapes any thread (scan writer, workers, timers) is logged with its traceback, never lost."""
    if issubclass(args.exc_type, SystemExit):
        return
    log.error("thread %s crashed", getattr(args.thread, "name", "?"), exc_info=(args.exc_type, args.exc_value, args.exc_traceback))


def _main_crash(exc_type, exc, tb):
    """Why: same for the main thread (start-up errors)."""
    if issubclass(exc_type, KeyboardInterrupt):
        return sys.__excepthook__(exc_type, exc, tb)
    log.critical("%s stopped because of an unexpected error", config.APP_NAME, exc_info=(exc_type, exc, tb))
    return None


def setup(to_file=True):
    """Why: one consistent log format (console + rotating user-only file) for the whole app."""
    log.setLevel(logging.INFO)
    if log.handlers:
        return log
    fmt = SafeFormatter(FORMAT)
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    log.addHandler(console)
    threading.excepthook = _thread_crash
    sys.excepthook = _main_crash
    if to_file:
        try:
            config.LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
            fh = logging.handlers.RotatingFileHandler(config.LOG_FILE, maxBytes=config.LOG_MAX_BYTES,
                                                      backupCount=config.LOG_BACKUPS, encoding="utf-8", errors="backslashreplace")
            fh.setFormatter(fmt)
            log.addHandler(fh)
        except OSError:
            log.warning("could not open the log file; logging to the console only")
    return log
