"""PIN lock: the app opens behind a PIN, and every move, copy, delete, undo, replace, data wipe and API-key change needs
the PIN again (a short-lived, single-use action token bound to that exact request). Enforced by the server.

What it protects against: someone using AuraSort on a computer you left unlocked. What it does not: anyone signed in
to your OS account can still use other tools, so lock your screen and use your OS password, BitLocker or FileVault.

Storage: never the PIN itself. A random 16-byte salt and scrypt (PBKDF2-HMAC-SHA256 with 600,000 iterations where
scrypt is missing) in pin.json in the data folder, readable by the user only. Failed attempts are stored there too, so
the growing lockout survives a restart."""
import hashlib
import hmac
import json
import os
import secrets
import threading
import time

from . import config
from .log import log
from .platform_utils import make_private, replace_file

PIN_LENGTHS = (4, 6)
_lock = threading.RLock()
_state = dict(unlocked=False, last=0.0, remember_until=0.0)
_tokens = {}            # action token -> (action, request hash, expires)
_set_cache = {}         # pin.json path -> is a PIN set (checked on every request, so not read from disk each time)


class PinError(ValueError):
    """Why: every PIN refusal has a stable code (wrong_pin, locked_out, pin_required...) and a plain message."""

    def __init__(self, message, code, status=403, **extra):
        super().__init__(message)
        self.code, self.status, self.extra = code, status, extra


def _file():
    return config.DATA_DIR / config.PIN_FILE_NAME


def _load():
    """Why: read under the same lock as the writes (Windows cannot replace pin.json while it is open)."""
    with _lock:
        try:
            with open(_file(), encoding="utf-8") as fh:
                d = json.load(fh)
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}


def _save(d):
    """Why: written atomically (a crash never leaves half a file) and private to the user."""
    with _lock:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        tmp = _file().with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(d, fh)
        replace_file(tmp, _file())
        make_private(_file(), is_dir=False)
        _set_cache.pop(str(_file()), None)


def _derive(pin, rec):
    """Why: a slow, salted hash: a copied pin.json does not give the PIN away quickly (10^4 or 10^6 guesses, each costly)."""
    salt = bytes.fromhex(rec["salt"])
    if rec.get("algo") == "scrypt":
        n, r, p = rec["n"], rec["r"], rec["p"]
        return hashlib.scrypt(pin.encode(), salt=salt, n=n, r=r, p=p, maxmem=256 * n * r + (1 << 20), dklen=32)
    return hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, rec["iterations"], dklen=32)


def _new_record(pin):
    rec = dict(v=1, salt=secrets.token_hex(16), digits=len(pin), set=int(time.time()))
    try:
        rec.update(algo="scrypt", n=config.PIN_SCRYPT_N, r=8, p=1)
        rec["hash"] = _derive(pin, rec).hex()
    except (AttributeError, ValueError):   # a Python built without OpenSSL scrypt
        rec = dict(v=1, salt=rec["salt"], digits=len(pin), set=rec["set"], algo="pbkdf2", iterations=config.PIN_PBKDF2_ITERATIONS)
        rec["hash"] = _derive(pin, rec).hex()
    return rec


def valid_format(pin):
    return isinstance(pin, str) and pin.isascii() and pin.isdigit() and len(pin) in PIN_LENGTHS


def is_weak(pin):
    """Why: 0000, 1234, 1111, 2580... are guessed first. The UI warns; it does not refuse."""
    if not valid_format(pin):
        return True
    d = [int(c) for c in pin]
    steps = {d[i + 1] - d[i] for i in range(len(d) - 1)}
    common = {"1234", "0000", "1111", "1212", "7777", "1004", "2000", "4444", "2222", "6969", "2580", "0852", "123456", "654321",
              "111111", "000000", "121212", "112233", "159753", "246810", "135790"}
    return pin in common or len(set(d)) <= 2 or steps <= {1} or steps <= {-1}


def is_set():
    key = str(_file())
    if key not in _set_cache:
        rec = _load()
        _set_cache[key] = bool(rec.get("hash") and rec.get("salt"))
    return _set_cache[key]


# ---------------- attempts and lockout ----------------
def _lockout(rec):
    """Why: seconds still locked (0 = free). After 5 wrong tries: 30 s, then 1, 5 and 15 minutes for each further miss."""
    return max(0, int(rec.get("locked_until", 0) - time.time()))


def _fail(rec):
    rec["fails"] = rec.get("fails", 0) + 1
    over = rec["fails"] - config.PIN_FREE_TRIES
    if over >= 0:
        delays = config.PIN_LOCKOUT_S
        rec["locked_until"] = time.time() + delays[min(over, len(delays) - 1)]
    _save(rec)
    log.warning("wrong PIN entered (%s in a row)", rec["fails"])   # never the PIN itself


def check(pin):
    """Why: one place compares a PIN (constant time) and applies the persisted lockout to every caller."""
    with _lock:
        rec = _load()
        if not rec.get("hash"):
            raise PinError("Set a PIN first.", "pin_not_set", 409)
        wait = _lockout(rec)
        if wait:
            raise PinError(f"Too many wrong PINs. Try again in {_human(wait)}.", "locked_out", 429, retry_after=wait)
        ok = valid_format(pin) and hmac.compare_digest(_derive(pin, rec).hex(), rec["hash"])
        if not ok:
            _fail(rec)
            wait = _lockout(rec)
            left = max(0, config.PIN_FREE_TRIES - rec["fails"])
            if wait:
                raise PinError(f"Wrong PIN. Too many tries: wait {_human(wait)}.", "locked_out", 429, retry_after=wait)
            raise PinError(f"Wrong PIN. {left} {'try' if left == 1 else 'tries'} left before a short wait.", "wrong_pin", 403, attempts_left=left)
        if rec.get("fails") or rec.get("locked_until"):
            rec["fails"], rec["locked_until"] = 0, 0
            _save(rec)
        return True


def _human(s):
    return f"{s} seconds" if s < 90 else f"{round(s / 60)} minutes"


# ---------------- session (unlocked or not) ----------------
def set_pin(pin, current=None):
    """Why: first run sets the PIN; changing it later needs the current one."""
    if not valid_format(pin):
        raise PinError("The PIN must be 4 or 6 digits.", "bad_pin", 400)
    with _lock:
        if is_set():
            if current is None:
                raise PinError("A PIN is already set. Enter the current PIN to change it.", "pin_exists", 409)
            check(current)
        _save(_new_record(pin))
        _state.update(unlocked=True, last=time.monotonic())
    log.info("PIN %s", "changed" if current is not None else "set")
    return dict(weak=is_weak(pin))


def unlock(pin):
    check(pin)
    with _lock:
        _state.update(unlocked=True, last=time.monotonic())
    return True


def lock():
    with _lock:
        _state.update(unlocked=False, remember_until=0.0)
        _tokens.clear()


def idle_s():
    from . import settings
    return max(1, int(settings.load().get("pin_idle_min") or config.PIN_IDLE_MIN_DEFAULT)) * 60


def unlocked(touch=True):
    """Why: the session locks itself after the idle time; `touch` counts this request as activity."""
    with _lock:
        if not _state["unlocked"]:
            return False
        now = time.monotonic()
        if now - _state["last"] > idle_s():
            _state.update(unlocked=False, remember_until=0.0)
            _tokens.clear()
            log.info("locked after %s minutes without activity", idle_s() // 60)
            return False
        if touch:
            _state["last"] = now
        return True


def status():
    from . import settings
    rec = _load()
    s = settings.load()
    return dict(set=bool(rec.get("hash")), unlocked=unlocked(touch=False), digits=rec.get("digits", 4), locked_for=_lockout(rec),
                attempts_left=max(0, config.PIN_FREE_TRIES - rec.get("fails", 0)), idle_min=int(s.get("pin_idle_min") or config.PIN_IDLE_MIN_DEFAULT),
                remember_min=int(s.get("pin_remember_min") or 0), remember_active=time.monotonic() < _state["remember_until"])


# ---------------- action tokens ----------------
def request_hash(body):
    """Why: the token is bound to the exact request it was issued for; any change to the request makes it useless."""
    clean = {k: v for k, v in (body or {}).items() if k != "action_token"}
    return hashlib.sha256(json.dumps(clean, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def issue(action, body, pin=None):
    """Why: the PIN is asked before each guarded action; the answer is a single-use token valid for 60 seconds."""
    from . import settings
    if action not in config.PIN_ACTIONS:
        raise PinError("Unknown action.", "bad_action", 400)
    if not unlocked():
        raise PinError("AuraSort is locked. Enter your PIN to unlock it.", "locked", 423)
    remember_min = int(settings.load().get("pin_remember_min") or 0)
    if pin is None or pin == "":
        if not (remember_min and time.monotonic() < _state["remember_until"]):
            raise PinError("Enter your PIN to continue.", "pin_required", 403)
    else:
        check(pin)
        if remember_min:
            _state["remember_until"] = time.monotonic() + remember_min * 60
    tok = secrets.token_urlsafe(24)
    with _lock:
        now = time.monotonic()
        for k in [k for k, v in _tokens.items() if v[2] < now]:
            del _tokens[k]
        _tokens[tok] = (action, request_hash(body), now + config.PIN_ACTION_TOKEN_S)
    return tok


def consume(token, action, body):
    """Why: called by the server before a guarded route runs. One use only; wrong action, changed request or an old
    token are all refused."""
    with _lock:
        entry = _tokens.pop(str(token or ""), None)
    if not entry:
        raise PinError("Confirm with your PIN first.", "pin_required", 403)
    a, h, exp = entry
    if time.monotonic() > exp:
        raise PinError("The PIN confirmation expired. Try again.", "pin_expired", 403)
    if a != action or not hmac.compare_digest(h, request_hash(body)):
        raise PinError("The PIN confirmation was for a different action. Try again.", "pin_mismatch", 403)
    return True


def reset_everything():
    """Why: 'Forgot PIN': AuraSort's own settings, history and index are wiped (never your files) and setup starts again."""
    from . import purge
    removed = purge.delete_all()
    with _lock:
        try:
            _file().unlink()
        except FileNotFoundError:
            pass
        _set_cache.clear()
        _state.update(unlocked=False, last=0.0, remember_until=0.0)
        _tokens.clear()
    log.warning("PIN reset: AuraSort's own data was wiped")
    return removed
