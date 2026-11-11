"""HTTP plumbing: local-only checks, token auth, JSON in/out, static files. Routes live in server.py."""
import collections
import gzip
import hashlib
import json
import os
import re
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

from . import config, pin, schema
from .log import log

STATIC_TYPES = {"html": "text/html; charset=utf-8", "js": "text/javascript; charset=utf-8", "mjs": "text/javascript; charset=utf-8", "css": "text/css; charset=utf-8",
                "svg": "image/svg+xml", "png": "image/png", "ico": "image/x-icon", "json": "application/json", "md": "text/plain; charset=utf-8", "woff2": "font/woff2"}


CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; "
       "font-src 'self'; connect-src 'self'; worker-src 'self'; frame-src 'self'; object-src 'none'; base-uri 'none'; "
       "form-action 'none'; frame-ancestors 'none'")
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer", "X-Frame-Options": "DENY",
    "Cross-Origin-Resource-Policy": "same-origin", "Cross-Origin-Opener-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=(), serial=(), bluetooth=(), "
                          "hid=(), midi=(), display-capture=(), clipboard-read=(), interest-cohort=()",
}
COMPRESSIBLE = ("application/json", "text/")
SIGNED_ROUTES = ("thumb", "file")          # authorised by an expiring HMAC signature instead of the token header
RATE_KEYS = {"scan/start": "scan", "scan/estimate": "estimate", "execute": "execute", "trash": "trash", "open": "open",
             "integrity/start": "integrity", "duplicates/start": "duplicates", "mkdir": "mkdir", "undo": "undo",
             "quarantine": "execute", "ai/start": "ai", "ai/pull": "ai", "ai/test": "ai", "ai/key": "ai", "ai/engine/start": "ai",
             "pin/unlock": "pin", "pin/verify": "pin", "pin/set": "pin", "pin/reset": "pin", "diagnostics": "diagnostics",
             "apptrash/restore": "undo", "conflicts": "estimate"}
PASSIVE_ROUTES = ("scan/status", "job", "pin/status")   # polling: does not count as activity for the idle lock
_RATE, _RATE_LOCK = {}, threading.Lock()
# Legal documents live once, at the repo root; the app shows exactly those files at legal/<name> (allow-list only).
LEGAL_FILES = ("TERMS_OF_USE.md", "ACCEPTABLE_USE.md", "PRIVACY_POLICY.md", "AI_DATA_NOTICE.md", "THIRD_PARTY_NOTICES.md", "CODE_OF_CONDUCT.md", "LICENSE")
RANGE_RX = re.compile(r"^bytes=(\d*)-(\d*)$")
OPEN_FLAGS = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)   # never follow a link swapped in later
_TECHNICAL = re.compile(r"invalid literal|could not convert|not supported between|object has no attribute|unexpected keyword|"
                        r"argument|NoneType|[\\/][^\s]+[\\/]", re.I)


def friendly_error(ex):
    """Why: our own ValueErrors carry friendly text; technical parser messages (or anything with a path) become generic."""
    msg = str(ex) if isinstance(ex, ValueError) else ""
    return "Invalid request." if not msg or _TECHNICAL.search(msg) else msg


class ApiError(Exception):
    """Why: route code raises a status + friendly message (+ a stable code and a hint); the handler turns it into JSON."""

    def __init__(self, status, message, code="", hint=""):
        super().__init__(message)
        self.status, self.code, self.hint = status, code or STATUS_CODES.get(status, "error"), hint


STATUS_CODES = {400: "invalid", 401: "session_expired", 403: "forbidden", 404: "not_found", 405: "not_allowed", 409: "confirm_needed",
                413: "too_large", 416: "bad_range", 423: "locked", 429: "rate_limited", 500: "internal", 507: "disk_full"}
INTERNAL_HINT = f"Details are in the log file: {config.LOG_FILE_SHOWN}"


class Handler(BaseHTTPRequestHandler):
    """Why: one place enforces Host/Origin/token rules for every request before any route runs."""

    server_version = config.APP_NAME
    sys_version = ""
    token = ""  # nosec B105  # not a password (header name / empty default / local test token)
    port = config.DEFAULT_PORT
    routes = {}           # "GET name" / "POST name" -> function(handler, qs, body)

    def log_message(self, *args):  # noqa: D401 - silence default access log (paths would leak into the console)
        return

    # ---------------- responses ----------------
    def send(self, code, body, ctype="application/json", extra=None):
        """Why: every response gets the security headers; large JSON/text is gzipped."""
        if isinstance(body, (dict, list)):
            body = json.dumps(body, separators=(",", ":")).encode()
        elif isinstance(body, str):
            body = body.encode()
        headers = {"Cache-Control": "no-store", "Content-Security-Policy": CSP, **SECURITY_HEADERS, **(extra or {})}
        if (len(body) >= config.GZIP_MIN_BYTES and ctype.startswith(COMPRESSIBLE)
                and "gzip" in self.headers.get("Accept-Encoding", "") and "Content-Encoding" not in headers):
            body = gzip.compress(body, compresslevel=5)
            headers["Content-Encoding"] = "gzip"
            headers["Vary"] = "Accept-Encoding"
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in headers.items():
            if v is not None:
                self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def fail(self, status, message, code="", hint="", **extra):
        """Why: every API error has the same shape, {error, code, hint}; the UI maps the code to friendly text."""
        self.send(status, {"error": message, "code": code or STATUS_CODES.get(status, "error"), "hint": hint, **extra})

    def send_file(self, path, ctype, extra=None):
        """Why: previews stream big files in chunks and honour one HTTP range, so video and audio can seek."""
        with os.fdopen(os.open(path, OPEN_FLAGS), "rb") as fh:
            size = os.fstat(fh.fileno()).st_size
            start, end, code = 0, size - 1, 200
            m = RANGE_RX.match(self.headers.get("Range", "").strip())
            if m and size and (m.group(1) or m.group(2)):
                a, z = m.groups()
                start, end = (max(0, size - int(z)), size - 1) if a == "" else (int(a), min(int(z), size - 1) if z else size - 1)
                if start > end:
                    return self.send(416, b"", "text/plain", {"Content-Range": f"bytes */{size}"})
                code = 206
            length = max(0, end - start + 1)
            headers = {"Cache-Control": "no-store", "Content-Security-Policy": CSP, **SECURITY_HEADERS, "Accept-Ranges": "bytes", **(extra or {})}
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(length))
            if code == 206:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            for k, v in headers.items():
                self.send_header(k, v)
            self.end_headers()
            if self.command == "HEAD":
                return None
            fh.seek(start)
            try:
                while length > 0:
                    chunk = fh.read(min(config.STREAM_CHUNK, length))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    length -= len(chunk)
            except ConnectionError:   # the browser stopped reading (seek, close): normal for media
                self.close_connection = True
        return None

    # ---------------- checks ----------------
    def ok_host(self):
        return self.headers.get("Host", "") in {f"{h}:{self.port}" for h in config.ALLOWED_HOST_NAMES}

    def ok_origin(self):
        o = self.headers.get("Origin")
        return o is None or o in {f"http://{h}:{self.port}" for h in config.ALLOWED_HOST_NAMES}

    def ok_token(self):
        """Why: every API call needs the per-run token in a header (constant-time compare); signed links are checked by their route."""
        return secrets.compare_digest(self.headers.get(config.TOKEN_HEADER, ""), self.token)

    def rate_ok(self, name):
        """Why: expensive endpoints (scan, move, trash, open…) are rate-limited so a runaway client can't hammer the disk."""
        key = RATE_KEYS.get(name)
        if not key:
            return True
        limit, window = config.RATE_LIMITS[key]
        now = time.monotonic()
        with _RATE_LOCK:
            q = _RATE.setdefault(key, collections.deque())
            while q and now - q[0] > window:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
        return True

    def read_json(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise ApiError(400, "Malformed request.") from None
        if n > config.MAX_BODY_BYTES:
            self.close_connection = True   # refuse without reading it
            raise ApiError(413, "Request too large.")
        raw = self.rfile.read(n) if n else b"{}"
        try:
            body = json.loads(raw or b"{}")
        except ValueError:
            raise ApiError(400, "Malformed request.") from None
        if not isinstance(body, dict):
            raise ApiError(400, "Malformed request.")
        return body

    # ---------------- dispatch ----------------
    def refuse(self, status, message, code=""):
        """Why: a request refused before its body is read (403/401/405/429) still has that body on the socket; closing
        with unread data makes Windows reset the connection, and the browser then sees "connection reset" instead of
        our JSON error. Small bodies are read and dropped first; big ones close the connection on purpose."""
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        if 0 < n <= config.MAX_BODY_BYTES:
            self.rfile.read(n)
        elif n:
            self.close_connection = True
        return self.fail(status, message, code)

    def pin_gate(self, name):
        """Why: the PIN lock is enforced here, for every API route (signed preview links included), not only in the UI.
        Before a PIN exists only the setup screens work; while locked only the unlock screen does."""
        if name in config.PIN_OPEN_ROUTES:
            return None
        if not pin.is_set():
            return (423, "Set up your PIN first.", "pin_not_set")
        if not pin.unlocked(touch=name not in PASSIVE_ROUTES):
            return (423, "AuraSort is locked. Enter your PIN to unlock it.", "locked")
        return None

    def handle_any(self, method):
        u = urlparse(self.path)
        if not self.ok_host():
            return self.refuse(403, "Open the app from the address printed by the server.")
        if not u.path.startswith("/api/"):
            if method not in ("GET", "HEAD"):
                return self.refuse(405, "Not allowed.")
            return self.static(u.path)
        if not self.ok_origin() or self.headers.get("Sec-Fetch-Site", "same-origin") not in ("same-origin", "none"):
            return self.refuse(403, "Cross-site request blocked.")
        name = u.path[5:]
        if name not in SIGNED_ROUTES and not self.ok_token():
            return self.refuse(401, "Session expired. Reload the page.")
        if not self.rate_ok(name):
            return self.refuse(429, "Too many requests. Wait a moment and try again.")
        gate = self.pin_gate(name)
        if gate:
            return self.refuse(*gate)
        try:
            body = self.read_json() if method == "POST" else {}
            fn = self.routes.get(f"{'GET' if method == 'HEAD' else method} {name}")   # HEAD = GET without the body
            if not fn:
                raise ApiError(404, "Unknown endpoint.")
            if method == "POST":
                schema.check_fields(name, body)
                action = config.PIN_GUARDED.get(name)
                if action:   # move, copy, delete, undo, replace, data wipe, API keys: a fresh PIN confirmation for this exact request
                    pin.consume(body.pop("action_token", None), action, body)
            fn(self, parse_qs(u.query), body)
        except ApiError as ex:
            self.fail(ex.status, str(ex), ex.code, ex.hint)
        except pin.PinError as ex:
            self.fail(ex.status, str(ex), ex.code, "", **ex.extra)
        except schema.BadRequest as ex:
            self.fail(400, str(ex), ex.code, ex.hint)
        except ValueError as ex:   # our own checks raise ValueError with friendly text; parser errors become generic
            log.info("request %s %s refused: %s", method, u.path, ex)
            self.fail(400, friendly_error(ex), "invalid")
        except Exception:  # noqa: BLE001 - KeyError, TypeError... are bugs: full traceback to the log, never to the browser
            log.exception("request failed: %s %s", method, u.path)
            self.fail(500, "Something went wrong on our side.", "internal", INTERNAL_HINT)

    def do_GET(self):
        self.handle_any("GET")

    def do_HEAD(self):
        self.handle_any("HEAD")

    def do_POST(self):
        self.handle_any("POST")

    # ---------------- static ----------------
    def static(self, path):
        rel = "index.html" if path in ("/", "") else path.lstrip("/")
        root = config.WEB_DIR.resolve()
        if rel.startswith("legal/") and rel[6:] in LEGAL_FILES and not (root / rel).is_file():
            root, rel = config.WEB_DIR.resolve().parent, rel[6:]   # the single source at the repo root
        try:
            f = (root / rel).resolve()
        except (OSError, ValueError):
            return self.fail(404, "Not found.")
        if root not in f.parents or not f.is_file():
            return self.fail(404, "Not found.")
        ctype = STATIC_TYPES.get(f.suffix[1:].lower(), "application/octet-stream")
        data = f.read_bytes()
        if f.name == "index.html":
            data = data.replace(b"__TOKEN__", self.token.encode())
        etag = '"' + hashlib.sha256(data).hexdigest()[:32] + '"'
        if self.headers.get("If-None-Match") == etag:
            self.send_response(304)
            self.send_header("ETag", etag)
            for k, v in SECURITY_HEADERS.items():
                self.send_header(k, v)
            self.end_headers()
            return None
        return self.send(200, data, ctype, {"ETag": etag, "Cache-Control": "no-cache"})


def qs_get(qs, key, default=""):
    """Why: query strings arrive as lists; routes want one value."""
    return qs.get(key, [default])[0]


def route(table, method, name):
    """Why: decorator to register a route function in the table used by Handler."""
    def deco(fn):
        table[f"{method} {name}"] = fn
        return fn
    return deco
