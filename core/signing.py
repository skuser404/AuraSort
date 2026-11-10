"""Short-lived HMAC-signed links for thumbnails and previews, so the main token never appears in a URL."""
import hashlib
import hmac
import secrets
import time

from . import config

_SECRET = secrets.token_bytes(32)   # new every run: old links stop working when the server restarts
KINDS = ("thumb", "file")


def _mac(kind, fid, exp):
    """Why: the signature binds the link to one file, one purpose and one expiry time."""
    msg = f"{kind}:{int(fid)}:{int(exp)}".encode()
    return hmac.new(_SECRET, msg, hashlib.sha256).hexdigest()[: config.SIG_HEX_CHARS]


def url(kind, fid, ttl=config.SIGNED_URL_TTL_S, now=None):
    """Why: an <img>/<video> tag cannot send headers, so it gets a signed, expiring link instead of the token."""
    if kind not in KINDS:
        raise ValueError("unknown link kind")
    exp = int((now or time.time()) + ttl)
    return f"/api/{kind}?id={int(fid)}&exp={exp}&sig={_mac(kind, fid, exp)}"


def verify(kind, fid, exp, sig, now=None):
    """Why: constant-time check of the signature, and refuse expired links."""
    try:
        fid, exp = int(fid), int(exp)
    except (TypeError, ValueError):
        return False
    if exp < (now or time.time()) or kind not in KINDS:
        return False
    return hmac.compare_digest(_mac(kind, fid, exp), str(sig or ""))
