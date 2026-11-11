"""Request schemas: the one place that says what each API body may contain, with defaults and readable 400 errors.

The front end and the server share this contract (documented in docs/ARCHITECTURE.md, checked by tests/test_contract.py).
Unknown fields are logged as a warning; with AURASORT_STRICT_SCHEMA=1 (the test suites) they are refused, so a renamed
field (camelCase vs snake_case, `folders` vs `roots`...) fails a test instead of being silently ignored."""
import os
import re

from . import config, settings
from .log import log


class BadRequest(ValueError):
    """Why: invalid input becomes HTTP 400 with {error, code, hint}; never a crash, never a stack trace in the browser."""

    def __init__(self, message, code="invalid", hint=""):
        super().__init__(message)
        self.code, self.hint = code, hint


# Every POST body field each route reads. tests/test_contract.py checks server.py reads nothing else and the UI sends nothing else.
POST_FIELDS = {
    "settings": tuple(k for k in settings.DEFAULTS if k not in settings.SECURITY_KEYS),
    "scan/estimate": ("mode", "roots"),
    "scan/start": ("mode", "roots", "skip", "est_files"),
    "scan/control": ("action",),
    "rows": ("ids",),
    "folders/include": ("ids", "included", "preset"),
    "open": ("id", "macro_ok"),
    "reveal": ("id", "job"),
    "plan": ("dest", "formats", "types"),
    "execute": ("allow_project", "allow_viewonly", "conflicts", "dest", "flat", "formats", "ids", "layout", "mode", "types", "verify"),
    "conflicts": ("allow_project", "allow_viewonly", "dest", "flat", "formats", "ids", "kind", "layout", "mode", "types"),
    "integrity/start": ("ids", "mode"),
    "duplicates/start": (),
    "quarantine": ("allow_project", "allow_viewonly", "conflicts", "ids", "verify"),
    "data/delete": ("confirm",),
    "interrupted/resume": ("id",),
    "interrupted/clean": ("id",),
    "selection": ("ids",),
    "trash": ("allow_project", "allow_viewonly", "confirm_count", "ids"),
    "open-trash": (),
    "mkdir": ("name", "parent"),
    "job/control": ("action", "id"),
    "undo": ("id",),
    "ai/settings": ("accept_cloud", "accept_local", "settings"),
    "ai/key": ("key", "remember"),
    "ai/test": ("mode",),
    "ai/engine/start": (),
    "ai/pull": ("model",),
    "ai/start": ("ids", "mode"),
    "ai/confirm": ("allow_confidential", "job"),
    "ai/clear": (),
    "ai/reset": (),
    "pin/set": ("current", "pin"),
    "pin/unlock": ("pin",),
    "pin/lock": (),
    "pin/verify": ("action", "pin", "request"),
    "pin/reset": ("confirm",),
    "pin/settings": settings.SECURITY_KEYS,
    "apptrash/restore": ("id",),
    "elevate": (),
}
# Guarded routes also carry the single-use PIN confirmation (core/pin.py); it is checked and removed before the route runs.
for _route in config.PIN_GUARDED:
    POST_FIELDS[_route] = tuple(POST_FIELDS.get(_route, ())) + ("action_token",)
SCAN_MODES = ("quick", "deep")
_DRIVE_ONLY = re.compile(r"^[A-Za-z]:$")
NOTHING_SELECTED = "Pick at least one drive or folder."


def strict():
    """Why: tests refuse unknown fields; a normal run only logs them (an extra harmless field must not break the app)."""
    return os.environ.get(config.SCHEMA_STRICT_ENV) == "1"


def check_fields(route_name, body):
    """Why: catch front-end/back-end field mismatches at the boundary."""
    allowed = POST_FIELDS.get(route_name)
    if allowed is None:
        return
    extra = sorted(k for k in body if k not in allowed)
    if not extra:
        return
    if strict():
        raise BadRequest(f"Unknown field(s) for {route_name}: {', '.join(extra)}.", "unknown_field")
    log.warning("request %s: ignored unknown field(s) %s", route_name, ", ".join(extra))


def norm_path(value, field):
    """Why: one rule for every path the browser sends: a non-empty absolute path; 'C:' means the drive 'C:\\'."""
    if not isinstance(value, str) or not value.strip():
        raise BadRequest(f"Each entry in '{field}' must be a folder path.", "bad_path")
    p = value.strip()
    if "\0" in p or len(p) > config.MAX_PATH_CHARS:
        raise BadRequest(f"One of the paths in '{field}' is not valid.", "bad_path")
    if config.WIN:
        p = strip_long_prefix(p)       # "\\?\C:\..." must meet the same protection rules as "C:\..."
        if _DRIVE_ONLY.match(p):
            p += "\\"                  # Windows reads a bare "C:" as "the current folder on C:", never what people mean
    if not os.path.isabs(p):
        raise BadRequest(f"Paths in '{field}' must be full paths (like C:\\Users\\you\\Music or /home/you/Music).", "bad_path")
    return os.path.normpath(p)         # "a\\..\\b" -> "b"; a drive root keeps its separator ("C:\\")


def strip_long_prefix(p):
    """Why: the Windows long-path prefix is an internal detail; every rule compares normal spellings."""
    if p.startswith("\\\\?\\UNC\\"):
        return "\\\\" + p[8:]
    if p.startswith("\\\\?\\") or p.startswith("\\\\.\\"):
        return p[4:]
    return p


def path_list(body, field, max_items=config.SCAN_MAX_ROOTS):
    """Why: lists default to [] when missing or null; anything else that is not a list of paths is a clear 400."""
    value = body.get(field)
    if value is None:
        return []
    if not isinstance(value, list):
        raise BadRequest(f"'{field}' must be a list of folder paths.", "bad_type")
    if len(value) > max_items:
        raise BadRequest(f"Too many entries in '{field}' (at most {max_items}).", "too_many")
    out, seen = [], set()
    for v in value:
        p = norm_path(v, field)
        key = os.path.normcase(os.path.normpath(p))
        if key not in seen:            # "C:\Music" and "c:\music\" are the same folder on Windows
            seen.add(key)
            out.append(p)
    return out


def nonneg_int(body, field, default=0):
    """Why: counts from the browser may be missing, null or a float; negative or non-numeric values are refused."""
    value = body.get(field, default)
    if value is None or value == "":
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise BadRequest(f"'{field}' must be a number of 0 or more.", "bad_type")
    return int(value)


def scan_request(body, need_roots=True):
    """Why: the scan request contract: {mode: 'quick'|'deep', roots: [path], skip: [path], est_files: int}.
    Quick Scan with no roots means 'the usual folders'; Deep Scan needs at least one drive or folder."""
    mode = body.get("mode") or "quick"
    if mode not in SCAN_MODES:
        raise BadRequest("Unknown scan mode. Use Quick Scan or Deep Scan.", "bad_mode")
    req = dict(mode=mode, roots=path_list(body, "roots"), skip=path_list(body, "skip", settings.MAX_LIST),
               est_files=nonneg_int(body, "est_files"))
    if need_roots and mode == "deep" and not req["roots"]:
        raise BadRequest(NOTHING_SELECTED, "nothing_selected", "Tick a drive or add a folder on the Scan page.")
    return req


def id_list(body, field="ids", required=False, max_items=None):
    """Why: selections are lists of index ids (never paths). Missing -> [] (or a 400 when required); non-numbers -> 400."""
    value = body.get(field)
    if value is None or value == []:
        if required:
            raise BadRequest("Nothing is selected.", "nothing_selected", "Tick one or more files first.")
        return []
    if not isinstance(value, list):
        raise BadRequest(f"'{field}' must be a list of file ids.", "bad_type")
    try:
        out = [int(i) for i in value if not isinstance(i, bool)]
    except (TypeError, ValueError):
        raise BadRequest(f"'{field}' must contain file ids only.", "bad_type") from None
    return out[:max_items] if max_items else out


def one_id(body, field="id"):
    """Why: a single index id; missing or not a number is a clear 400 instead of a TypeError deep in the code."""
    value = body.get(field)
    if isinstance(value, bool) or value is None or value == "":
        raise BadRequest(f"'{field}' is missing.", "missing_field")
    try:
        return int(value)
    except (TypeError, ValueError):
        raise BadRequest(f"'{field}' must be a number.", "bad_type") from None


def text(body, field, default="", max_chars=1024):
    """Why: short text fields (names, actions, job ids); anything that is not text is refused."""
    value = body.get(field, default)
    if value is None:
        return default
    if not isinstance(value, str):
        raise BadRequest(f"'{field}' must be text.", "bad_type")
    return str(value)[:max_chars]


def obj(body, field):
    """Why: nested objects (AI settings) default to {}; a list or a string is refused."""
    value = body.get(field)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise BadRequest(f"'{field}' must be an object.", "bad_type")
    return value
