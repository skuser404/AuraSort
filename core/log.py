"""Logging with redaction, so tokens and personal paths never reach the log file in clear text."""
import logging
import logging.handlers

from . import config

log = logging.getLogger(config.APP_SLUG)


class Redactor(logging.Filter):
    """Why: logs end up in bug reports, so secrets become [token] and the home folder becomes ~."""

    def __init__(self):
        super().__init__()
        self.secrets = set()

    def filter(self, record):
        msg = record.getMessage()
        for s in self.secrets:
            msg = msg.replace(s, "[token]")
        home = str(config.HOME)
        msg = msg.replace(home, "~").replace(home.replace("\\", "/"), "~")
        record.msg, record.args = msg, ()
        return True


_redactor = Redactor()


def add_secret(secret):
    """Why: the per-run token must be masked in every later log line."""
    _redactor.secrets.add(secret)


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


def setup(to_file=True):
    """Why: one consistent log format (console + rotating user-only file) for the whole app."""
    log.setLevel(logging.INFO)
    if log.handlers:
        return log
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    console.addFilter(_redactor)
    log.addHandler(console)
    if to_file:
        try:
            config.DATA_DIR.mkdir(parents=True, exist_ok=True)
            fh = logging.handlers.RotatingFileHandler(config.LOG_FILE, maxBytes=config.LOG_MAX_BYTES,
                                                      backupCount=config.LOG_BACKUPS, encoding="utf-8")
            fh.setFormatter(fmt)
            fh.addFilter(_redactor)
            log.addHandler(fh)
        except OSError:
            log.warning("could not open the log file; logging to the console only")
    return log
