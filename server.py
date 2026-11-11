#!/usr/bin/env python3
"""AuraSort local server: routes only. Plumbing is in core/web.py, logic in the core/ modules.
Binds to 127.0.0.1 only, needs a per-run token, never permanently deletes files."""
import argparse
import atexit
import codecs
import hashlib
import io
import os
import re
import secrets
import shutil
import socket
import socketserver
import sys
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path

from core import (apptrash, checks, classify, config, conflicts, copier, dates, docai, extract, hardware, history, index_db, instance, jobs, keystore, llm, mover, pin,
                  platform_utils, purge, scanner, schema, sensitive, settings, signing, trash)
from core.log import add_secret, log, setup as setup_log
from core.safety import canonical, check_destination, is_plain_file, protection_reason, safe_folder_name
from core.web import ApiError, Handler, qs_get, route

try:
    from PIL import Image  # optional, faster thumbnails (pinned in requirements.txt)
except ImportError:  # pragma: no cover
    Image = None

R = Handler.routes
EXT_RX = re.compile(r"^[a-z0-9]{1,10}$")
MAX_FORMATS = 30
MAX_PER_PAGE = 500
QTEXT_MAX = 100
FOLDER_MAX = 120
DAY_S = 86400


# ---------------- request helpers ----------------
def filters_from(qs):
    """Why: every list endpoint shares one strict parser for type/format/folder/q/date/scope params."""
    f = {}
    cat = qs_get(qs, "type")
    if cat and cat != "all":
        if cat not in classify.CATEGORY_NAMES:
            raise ApiError(400, "Unknown file type.")
        f["cat"] = cat
    exts = [e for e in qs_get(qs, "format").lower().split(",") if e]
    if exts:
        if any(not EXT_RX.match(e) for e in exts):
            raise ApiError(400, "Invalid format filter.")
        f["exts"] = exts[:MAX_FORMATS]
    if qs_get(qs, "folder"):
        f["folder"] = qs_get(qs, "folder")[:FOLDER_MAX]
    if qs_get(qs, "q"):
        f["q"] = qs_get(qs, "q")[:QTEXT_MAX]
    if qs_get(qs, "dir"):
        f["dir"] = int(qs_get(qs, "dir"))
    if qs_get(qs, "date"):
        f["dfrom"], f["dto"] = dates.range_for(qs_get(qs, "date"), qs_get(qs, "from") or None, qs_get(qs, "to") or None)
    elif qs_get(qs, "dfrom") and qs_get(qs, "dto"):
        f["dfrom"], f["dto"] = float(qs_get(qs, "dfrom")), float(qs_get(qs, "dto"))
    if qs_get(qs, "datefield"):
        dates.field_column(qs_get(qs, "datefield"))   # validates
        f["dfield"] = qs_get(qs, "datefield")
    scope = qs_get(qs, "scope", "all")
    if scope not in ("all", "ready", "included"):
        raise ApiError(400, "Unknown scope.")
    f["scope"] = scope
    if qs_get(qs, "problems") == "1":
        f["problems"] = True
    if scope == "ready":
        f["optin"] = settings.load()["optin"]
    return f


def page_args(qs):
    """Why: pagination is bounded so no request can ask for everything at once."""
    sort = qs_get(qs, "sort", "size")
    if sort not in index_db.SORTS:
        raise ApiError(400, "Unknown sort.")
    per = min(max(1, int(qs_get(qs, "per", str(config.PAGE_SIZE)))), MAX_PER_PAGE)
    return sort, max(1, int(qs_get(qs, "page", "1"))), per


def file_path(row):
    """Why: the on-disk path is always rebuilt from the server's own index."""
    return os.path.join(row["path"], row["name"])


def with_links(rows):
    """Why: image rows get a short-lived signed thumbnail link (the token never goes into a URL)."""
    out = []
    for r in rows:
        r = dict(r)
        if r.get("cat") == "Images" and not r.get("flags", 0) & index_db.FLAG_CLOUD:   # never make OneDrive/iCloud download a file
            r["thumb"] = signing.url("thumb", r["id"])
        out.append(r)
    return out


def require_file(fid):
    """Why: unknown ids are a 404, never a crash."""
    try:
        fid = int(fid)
    except (TypeError, ValueError):
        raise ApiError(400, "That file id is not valid.", "bad_type") from None
    row = index_db.file_by_id(fid)
    if not row:
        raise ApiError(404, "That file is no longer in the index. Scan again.")
    return row


# ---------------- info, drives, browsing, settings ----------------
@route(R, "GET", "info")
def r_info(h, qs, b):
    """Why: product strings, platform facts and quick folders the UI needs once at start. While locked (or before a PIN
    exists) only what the welcome and unlock screens show: no folders, no paths."""
    base = dict(app=config.APP_NAME, tagline=config.TAGLINE, subline=config.SUBLINE, version=config.APP_VERSION, os=config.PLATFORM,
                os_name=platform_utils.OS_NAME, device=platform_utils.device_name(), os_user=platform_utils.os_user(),
                admin=platform_utils.is_admin(), log_file=config.LOG_FILE_SHOWN, pin=pin.status(), trash_name=trash.where_name(),
                python=platform_utils.PYTHON_VERSION)   # the error report ("Copy details") works on the unlock screen too
    if not (pin.is_set() and pin.unlocked(touch=False)):
        return h.send(200, dict(base, locked=True))
    h.send(200, dict(base, locked=False, home=str(config.HOME), sep=os.sep, quick=platform_utils.quick_folders(),
                     dest=settings.load()["dest"] or platform_utils.default_destination(), pil=bool(Image),
                     user=platform_utils.user_display_name(), created_supported=platform_utils.CREATED_SUPPORTED,
                     created_note=platform_utils.CREATED_NOTE, has_index=index_db.last_scan() is not None,
                     # first start: the page runs a Quick Scan by itself (no index yet); test servers turn it off
                     auto_scan=index_db.last_scan() is None and os.environ.get(config.NO_AUTO_SCAN_ENV) != "1",
                     apptrash=config.ANDROID or bool(apptrash.items())))


# ---------------- PIN lock (core/pin.py; enforced for every route in core/web.py) ----------------
def _pin_value(b, key="pin"):
    v = b.get(key)
    if not isinstance(v, str):
        raise ApiError(400, "Enter the PIN as digits.", "bad_pin")
    return v


@route(R, "GET", "pin/status")
def r_pin_status(h, qs, b):
    h.send(200, dict(pin.status(), device=platform_utils.device_name(), os_user=platform_utils.os_user(), os_name=platform_utils.OS_NAME))


@route(R, "POST", "pin/set")
def r_pin_set(h, qs, b):
    """Why: first run sets the PIN (4 or 6 digits); changing it needs the current PIN."""
    current = b.get("current")
    h.send(200, pin.set_pin(_pin_value(b), current=None if current is None else _pin_value(b, "current")))


@route(R, "POST", "pin/unlock")
def r_pin_unlock(h, qs, b):
    pin.unlock(_pin_value(b))
    h.send(200, {"ok": True})


@route(R, "POST", "pin/lock")
def r_pin_lock(h, qs, b):
    pin.lock()
    h.send(200, {"ok": True})


@route(R, "POST", "pin/verify")
def r_pin_verify(h, qs, b):
    """Why: before a move, copy, delete, undo, replace, data wipe or API-key change the PIN is asked again; the answer
    is a 60-second, single-use token for exactly that request."""
    req = schema.obj(b, "request")
    p = b.get("pin")
    h.send(200, {"action_token": pin.issue(schema.text(b, "action"), req, None if p in (None, "") else _pin_value(b))})


@route(R, "POST", "pin/reset")
def r_pin_reset(h, qs, b):
    """Why: 'Forgot PIN': wipes AuraSort's own settings, history and index (never your files); setup starts again."""
    if b.get("confirm") != "RESET":
        raise ApiError(400, "Type RESET to confirm.", "confirm_needed")
    h.send(200, {"removed": pin.reset_everything()})


@route(R, "POST", "pin/settings")
def r_pin_settings(h, qs, b):
    """Why: idle lock, 'remember for N minutes' and the AuraSort trash purge timer (PIN needed: they weaken protection)."""
    h.send(200, {k: v for k, v in settings.update(**{k: b[k] for k in settings.SECURITY_KEYS if k in b}).items() if k in settings.SECURITY_KEYS})


# ---------------- optional: restart with administrator permission (Windows) ----------------
def _hand_over():
    """Why: the elevated copy waits for this one's lock; release it and stop so it can take over."""
    instance.release()
    log.info("handing over to the elevated AuraSort")
    os._exit(0)


@route(R, "POST", "elevate")
def r_elevate(h, qs, b):
    """Why: only for other users' folders or system drives (your own files never need it); Windows asks first (UAC).
    Declining changes nothing. Windows system folders stay skipped even with administrator permission."""
    if not config.WIN:
        raise ApiError(400, "This is only available on Windows.", "not_supported")
    if platform_utils.is_admin():
        raise ApiError(400, "AuraSort already runs with administrator permission.", "already_admin")
    args = [os.path.abspath(__file__), "--wait-for-lock"]
    if not platform_utils.relaunch_elevated(args, start_folder()):
        return h.send(200, {"ok": False, "declined": True})
    h.send(200, {"ok": True})
    threading.Timer(1.0, _hand_over).start()


# ---------------- AuraSort's own trash (Android; files kept by "Replace") ----------------
@route(R, "GET", "apptrash")
def r_apptrash(h, qs, b):
    apptrash.purge_old()
    h.send(200, dict(items=apptrash.items(), purge_days=settings.load()["apptrash_purge_days"], purge_choices=config.APPTRASH_PURGE_CHOICES_DAYS))


@route(R, "POST", "apptrash/restore")
def r_apptrash_restore(h, qs, b):
    """Why: put a file back from the AuraSort trash (never over another file)."""
    try:
        h.send(200, {"path": apptrash.restore(schema.text(b, "id"))})
    except OSError:
        raise ApiError(400, "That file could not be put back (its folder is read-only, or the drive is missing).") from None


@route(R, "GET", "diagnostics")
def r_diagnostics(h, qs, b):
    """Why: Settings > Diagnostics shows the same report as 'py server.py --doctor' (the test scan only when asked)."""
    from core import doctor
    d = doctor.collect(scan=qs_get(qs, "scan") == "1")
    d["text"] = doctor.as_text(d)
    h.send(200, d)


@route(R, "GET", "drives")
def r_drives(h, qs, b):
    """Why: every internal/external/network drive with type and space (unready drives included, marked)."""
    h.send(200, platform_utils.list_drives())


@route(R, "GET", "browse")
def r_browse(h, qs, b):
    """Why: the folder picker lists sub-folders, marking protected ones (with the reason) as disabled."""
    path = qs_get(qs, "path")
    if not path:
        quick = [dict(name=q["name"], path=q["path"], protected=False, quick=True) for q in platform_utils.quick_folders() if q["exists"]]
        drives = [dict(name=f"{d['name']} ({d['root'].rstrip(os.sep) or d['root']})", path=d["root"], protected=False, drive=True)
                  for d in platform_utils.list_drives() if d.get("ready")]
        return h.send(200, dict(path="", parent=None, crumbs=[], dirs=quick + drives))
    path = canonical(path)
    missing = ""
    if not os.path.isdir(path):        # e.g. the default AuraSortFiles before the first move: open the nearest folder that exists
        missing, p = path, os.path.dirname(path)
        while not os.path.isdir(p) and os.path.dirname(p) != p:
            p = os.path.dirname(p)
        if not os.path.isdir(p):
            raise ApiError(404, "That folder (and its drive) is not available.", "not_found", "Plug the drive in, or choose another folder.")
        path = p
    if protection_reason(path):
        raise ApiError(400, "That folder is protected and can't be opened here.", "protected")
    try:
        out = []
        for e in sorted(os.scandir(path), key=lambda x: x.name.lower()):
            if e.name.startswith(".") or not e.is_dir(follow_symlinks=False):
                continue
            reason = protection_reason(e.path)
            out.append(dict(name=e.name, path=e.path, protected=bool(reason), reason=reason or ""))
    except OSError:
        raise ApiError(400, "That folder can't be opened (no access, or the drive was removed).") from None
    crumbs, p = [], path
    while True:
        crumbs.append(dict(name=os.path.basename(p.rstrip(os.sep)) or p, path=p))
        parent = os.path.dirname(p)
        if parent == p:
            break
        p = parent
    parent = os.path.dirname(path)
    return h.send(200, dict(path=path, parent=parent if parent != path else "", crumbs=crumbs[::-1], dirs=out,
                          missing=os.path.basename(missing.rstrip(os.sep)) if missing else ""))


@route(R, "GET", "settings")
def r_settings(h, qs, b):
    """Why: remembered scan folders, skip list, destination and opt-ins."""
    h.send(200, settings.load())


@route(R, "POST", "settings")
def r_settings_save(h, qs, b):
    """Why: scan folders, skip list, destination and opt-ins are remembered between runs."""
    h.send(200, settings.update(**{k: v for k, v in b.items() if k in settings.DEFAULTS and k not in settings.SECURITY_KEYS}))


@route(R, "GET", "disk")
def r_disk(h, qs, b):
    """Why: free space on the destination drive for the move preview."""
    p = os.path.abspath(qs_get(qs, "path") or str(config.HOME))
    while not os.path.exists(p) and os.path.dirname(p) != p:
        p = os.path.dirname(p)
    u = shutil.disk_usage(p)
    h.send(200, dict(path=p, total=u.total, used=u.used, free=u.free, dev=platform_utils.dev_key(os.stat(p).st_dev)))


# ---------------- scanning ----------------
@route(R, "POST", "scan/estimate")
def r_scan_estimate(h, qs, b):
    """Why: 'Estimated scan time: ~X-Y min' from a short benchmark + used space."""
    req = schema.scan_request(b)
    h.send(200, scanner.estimate((req["roots"] or scanner.quick_roots()) if req["mode"] == "quick" else req["roots"]))


@route(R, "POST", "scan/start")
def r_scan_start(h, qs, b):
    """Why: Quick Scan (user folders) or Deep Scan (chosen drives/folders) in the background."""
    req = schema.scan_request(b)
    job = scanner.start(req["mode"], req["roots"], req["skip"], est_files=req["est_files"])
    settings.update(mode=req["mode"], skip=req["skip"], **({"roots": req["roots"]} if req["mode"] == "deep" else {}))   # remembered once the scan really started
    h.send(200, {"job": job.id})


@route(R, "POST", "scan/control")
def r_scan_control(h, qs, b):
    """Why: pause, resume or cancel the running scan."""
    job = scanner.CURRENT["job"]
    if not job or job.state not in ("running", "paused"):
        raise ApiError(400, "No scan is running.")
    action = b.get("action")
    if action not in ("pause", "resume", "cancel"):
        raise ApiError(400, "Unknown action.")
    getattr(job, action)()
    h.send(200, scanner.status())


@route(R, "GET", "scan/status")
def r_scan_status(h, qs, b):
    """Why: live partial counts for the scan screen."""
    h.send(200, scanner.status())


# ---------------- browsing the index ----------------
@route(R, "GET", "summary")
def r_summary(h, qs, b):
    """Why: dashboard numbers (cached until the index changes)."""
    s = dict(index_db.summary())
    s["biggest_files"] = with_links(s["biggest_files"])
    h.send(200, s)


@route(R, "GET", "files")
def r_files(h, qs, b):
    """Why: one paginated, filtered list endpoint for every page (100 per page by default) + facet counts."""
    f = filters_from(qs)
    sort, page, per = page_args(qs)
    out = index_db.files_page(f, sort, page, per)
    out["rows"] = with_links(out["rows"])
    if qs_get(qs, "facets") != "0":
        out["facets"] = index_db.facets(f)
    if not out["total"] and f.get("dfrom") is not None:
        out["nearest"] = nearest_days(f)
    h.send(200, out)


def nearest_days(f):
    """Why: an empty date filter suggests the closest days that do have files."""
    col = dates.field_column(f.get("dfield"))
    w, a = index_db.where({k: v for k, v in f.items() if k not in ("dfrom", "dto")})
    db = index_db.reader()
    joiner = " AND" if w else " WHERE"
    before = db.execute(f"SELECT MAX(files.{col}) FROM files JOIN dirs ON dirs.id=files.dir{w}{joiner} files.{col} < ?", a + [f["dfrom"]]).fetchone()[0]  # nosec B608  # values are ? parameters; identifiers come from allow-lists
    after = db.execute(f"SELECT MIN(files.{col}) FROM files JOIN dirs ON dirs.id=files.dir{w}{joiner} files.{col} >= ?", a + [f["dto"]]).fetchone()[0]  # nosec B608  # values are ? parameters; identifiers come from allow-lists
    return dict(before=dates.day_key(before) if before else None, after=dates.day_key(after) if after else None)


@route(R, "GET", "files/ids")
def r_file_ids(h, qs, b):
    """Why: 'Select all N matching' resolves to explicit ids (with sizes, so the selection bar shows exact totals)."""
    ids, sizes = index_db.ids_for(filters_from(qs))
    h.send(200, dict(ids=ids, sizes=sizes, size=sum(sizes)))


@route(R, "POST", "rows")
def r_rows(h, qs, b):
    """Why: the search worker ranks ids; the page's rows (paths, flags) come from the server."""
    h.send(200, with_links(index_db.rows_by_ids(schema.id_list(b, max_items=config.PAGE_SIZE * 5))))


@route(R, "GET", "extensions")
def r_extensions(h, qs, b):
    """Why: the 'All extensions' table (count, size, category) plus total disk size for '% of disk'."""
    total = 0
    scan = index_db.last_scan()
    for drive in {platform_utils.drive_of(r) for r in (scan or {}).get("roots", [])}:
        try:
            total += shutil.disk_usage(drive).total
        except OSError:
            pass
    h.send(200, dict(rows=index_db.extensions(), disk_total=total))


@route(R, "GET", "folders")
def r_folders(h, qs, b):
    """Why: 'Review folders' list with include state (the client virtualises long lists)."""
    h.send(200, index_db.folders(qs_get(qs, "q")[:FOLDER_MAX], qs_get(qs, "type"), qs_get(qs, "kind", "all")))


@route(R, "POST", "folders/include")
def r_folders_include(h, qs, b):
    """Why: tick/untick folders; project and asset folders need an explicit confirmation in the UI first."""
    preset = b.get("preset")
    if preset not in (None, "safe", "none", "all"):
        raise ApiError(400, "Unknown preset.")
    index_db.set_included(ids=schema.id_list(b) if b.get("ids") is not None else None, preset=preset, value=bool(b.get("included", True)))
    h.send(200, {"ok": True})


@route(R, "GET", "search-index")
def r_search_index(h, qs, b):
    """Why: compact names + columns for the browser's search worker (built once per index version)."""
    h.send(200, index_db.search_index())


@route(R, "GET", "snapshots")
def r_snapshots(h, qs, b):
    """Why: storage trend points (one per scan per drive)."""
    days = min(max(1, int(qs_get(qs, "days", "30"))), 3650)
    h.send(200, index_db.snapshots(qs_get(qs, "drive") or None, time.time() - days * DAY_S))


@route(R, "GET", "calendar")
def r_calendar(h, qs, b):
    """Why: the calendar heatmap counts files per day of one year (modified, created or last opened)."""
    year = int(qs_get(qs, "year") or time.localtime().tm_year)
    if not config.YEAR_MIN <= year <= config.YEAR_MAX:
        raise ApiError(400, "Invalid year.")
    h.send(200, index_db.calendar(filters_from(qs), year))


@route(R, "GET", "timeline")
def r_timeline(h, qs, b):
    """Why: the timeline counts files per month across every year."""
    h.send(200, index_db.timeline(filters_from(qs)))


# ---------------- files ----------------
def _thumb_cache_path(row):
    """Why: thumbnails are cached on disk, keyed by id + size + mtime so edits invalidate them."""
    key = hashlib.sha256(f"{row['id']}:{row['size']}:{int(row['mtime'])}".encode()).hexdigest()[:32]
    return config.THUMB_DIR / f"{key}.jpg"


@route(R, "GET", "thumb")
def r_thumb(h, qs, b):
    """Why: lazy image thumbnails behind a signed, expiring link (sandboxed, cached on disk)."""
    if not signing.verify("thumb", qs_get(qs, "id"), qs_get(qs, "exp"), qs_get(qs, "sig")):
        raise ApiError(403, "This preview link has expired. Reload the page.")
    row = require_file(qs_get(qs, "id", "-1"))
    path = file_path(row)
    if row["cat"] != "Images" or not is_plain_file(path):
        raise ApiError(404, "No preview.")
    hdr = {"Content-Security-Policy": "sandbox", "Cache-Control": "private, max-age=600"}
    cache = _thumb_cache_path(row)
    if cache.is_file():
        return h.send(200, cache.read_bytes(), "image/jpeg", hdr)
    if Image:
        try:
            with Image.open(path) as im:
                im.thumbnail((config.THUMB_PX, config.THUMB_PX))
                buf = io.BytesIO()
                im.convert("RGB").save(buf, "JPEG", quality=config.THUMB_QUALITY)
            data = buf.getvalue()
            try:
                config.THUMB_DIR.mkdir(parents=True, exist_ok=True)
                cache.write_bytes(data)
            except OSError:
                pass
            return h.send(200, data, "image/jpeg", hdr)
        except (OSError, ValueError, Image.DecompressionBombError):
            pass
    mime = classify.PREVIEW_MIME.get(row["ext"])
    if row["ext"] in classify.WEB_THUMB_EXTS and mime and row["size"] < config.THUMB_RAW_MAX_BYTES:
        return h.send(200, Path(path).read_bytes(), mime, hdr)
    raise ApiError(404, "No preview.")


def text_excerpt(path):
    """Why: text previews show the start of a file as plain text; binary files (NUL bytes) get no text preview."""
    with open(path, "rb") as fh:
        raw = fh.read(config.TEXT_PREVIEW_BYTES + 1)
    truncated, raw = len(raw) > config.TEXT_PREVIEW_BYTES, raw[:config.TEXT_PREVIEW_BYTES]
    for bom, enc in ((codecs.BOM_UTF8, "utf-8-sig"), (codecs.BOM_UTF16_LE, "utf-16"), (codecs.BOM_UTF16_BE, "utf-16")):
        if raw.startswith(bom):
            return raw.decode(enc, errors="replace"), truncated
    if b"\x00" in raw[:config.TEXT_SNIFF_BYTES]:
        return None, False
    return raw.decode("utf-8", errors="replace"), truncated


@route(R, "GET", "preview")
def r_preview(h, qs, b):
    """Why: the preview panel gets full details plus a signed content link, a text excerpt, or the reason there is none."""
    row = require_file(qs_get(qs, "id", "-1"))
    path, kind = file_path(row), classify.preview_kind(row["ext"])
    out = dict(file=with_links([row])[0], kind=kind, open_block=classify.open_block_reason(row["ext"]),
               macro=row["ext"] in classify.MACRO_OFFICE, created_supported=platform_utils.CREATED_SUPPORTED)
    if row["flags"] & index_db.FLAG_CLOUD:
        out["kind"] = "cloud"   # an online-only placeholder: reading it would download it
    elif not is_plain_file(path):
        out["kind"] = "missing"
    elif kind in classify.STREAM_KINDS:
        out["src"] = signing.url("file", row["id"])
    elif kind == "text":
        try:
            out["text"], out["truncated"] = text_excerpt(path)
        except OSError:
            out["text"] = None
        if out["text"] is None:
            out["kind"] = "none"
    h.send(200, out)


PDF_CSP = "frame-ancestors 'self'"   # the browser's PDF viewer refuses sandboxed documents; framing stays same-origin only
MEDIA_CSP = "sandbox; default-src 'none'; img-src 'self' data:; media-src 'self'; style-src 'unsafe-inline'"


@route(R, "GET", "file")
def r_file(h, qs, b):
    """Why: previews stream the real file behind a signed, expiring link (Range requests let video and audio seek)."""
    if not signing.verify("file", qs_get(qs, "id"), qs_get(qs, "exp"), qs_get(qs, "sig")):
        raise ApiError(403, "This preview link has expired. Close the preview and open it again.")
    row = require_file(qs_get(qs, "id", "-1"))
    kind, mime, path = classify.preview_kind(row["ext"]), classify.preview_mime(row["ext"]), file_path(row)
    if kind not in classify.STREAM_KINDS or not mime or not is_plain_file(path):
        raise ApiError(404, "No preview.")
    hdr = {"Cache-Control": "private, max-age=600", "Content-Disposition": "inline", "X-Frame-Options": "SAMEORIGIN",
           "Content-Security-Policy": PDF_CSP if kind == "pdf" else MEDIA_CSP}
    try:
        h.send_file(path, mime, hdr)
    except OSError:
        raise ApiError(404, "The file is no longer there. Scan again to refresh.") from None


@route(R, "POST", "open")
def r_open(h, qs, b):
    """Why: 'Open file' hands a document or media file to its default app, but never anything that can run code."""
    row = require_file(b.get("id", -1))
    reason = classify.open_block_reason(row["ext"])
    if reason:
        raise ApiError(400, reason)
    path = file_path(row)
    if not is_plain_file(path):
        raise ApiError(400, "The file is no longer there. Scan again to refresh.")
    if not config.WIN and os.access(path, os.X_OK):
        raise ApiError(400, "This file is marked as a program on your system, so it is not opened. Use Open location instead.")
    if row["ext"] in classify.MACRO_OFFICE and not b.get("macro_ok"):
        raise ApiError(409, "This Office file can contain macros. Confirm before opening it.")
    try:
        platform_utils.open_file(path)
    except platform_utils.NoFileManager:
        return h.send(200, {"ok": False, "fallback": "copy", "path": path})   # the UI shows the path with a Copy button
    log.info("opened file id %s with its default app", row["id"])
    h.send(200, {"ok": True})


@route(R, "POST", "reveal")
def r_reveal(h, qs, b):
    """Why: 'Open location' / 'Open destination' (paths come from the index or our own manifest only)."""
    if b.get("job"):
        dest = str(history.load(schema.text(b, "job")).get("dest") or "")
        if not os.path.isdir(dest):
            raise ApiError(400, "That destination folder no longer exists.")
        try:
            platform_utils.open_folder(dest)
        except platform_utils.NoFileManager:
            return h.send(200, {"ok": False, "fallback": "copy", "path": dest})
    else:
        row = require_file(b.get("id", -1))
        path = file_path(row)
        if not os.path.lexists(path):
            raise ApiError(400, "The file is no longer there. Scan again to refresh.")
        try:
            platform_utils.reveal(path)
        except platform_utils.NoFileManager:
            return h.send(200, {"ok": False, "fallback": "copy", "path": path})
    h.send(200, {"ok": True})


# ---------------- planning & moving ----------------
def _plan_filters(b):
    """Why: the move preview and the move itself use exactly the same selection rules."""
    opt = settings.load()["optin"]
    types = [t for t in (b.get("types") or []) if t in classify.CATEGORY_NAMES]
    allowed = sorted((set(types) or classify.MOVABLE) & (classify.MOVABLE | set(opt)))
    f = dict(scope="ready", cats=allowed or ["__none__"], optin=opt)
    exts = [e for e in (b.get("formats") or []) if isinstance(e, str) and EXT_RX.match(e)]
    if exts:
        f["exts"] = exts[:MAX_FORMATS]
    return f


@route(R, "POST", "plan")
def r_plan(h, qs, b):
    """Why: exact preview of what a move would do (counts, sub-folders, source folders, cross-drive bytes)."""
    dev = None
    if b.get("dest"):
        p = os.path.abspath(schema.norm_path(b.get("dest"), "dest"))
        while not os.path.exists(p) and os.path.dirname(p) != p:
            p = os.path.dirname(p)
        try:
            dev = platform_utils.dev_key(os.stat(p).st_dev)   # compared with the index's stored drive ids
        except OSError:
            dev = None   # the destination drive is gone: the preview counts every file as a copy
    h.send(200, index_db.plan(_plan_filters(b), dev))


LAYOUTS = ("here", "type", "organized")   # straight into the folder / one folder per type / type + sub-folder
GUARDED_KINDS = ("project", "assets")      # folders whose files belong to an app, site or edit


def _ops_for(ids, b, layout="organized"):
    """Why: move, copy and Recycle Bin share one rule set: project/asset files and view-only types are left alone unless opted in."""
    optin = set(settings.load()["optin"]) | {c for c in (b.get("allow_viewonly") or []) if c in classify.VIEW_ONLY}
    allow_project = bool(b.get("allow_project"))
    ops, blocked = [], 0
    for r in _rows_in_chunks(ids):
        if (r["kind"] in GUARDED_KINDS and not allow_project) or (r["viewonly"] and r["cat"] not in optin):
            blocked += 1
            continue
        sub = "" if layout == "here" else r["cat"] if layout == "type" else f"{r['cat']}/{r['sub']}"
        ops.append(dict(fid=r["id"], src=file_path(r), dir=r["path"], name=r["name"], size=r["size"], mtime=r["mtime"], cat=r["cat"], sub=sub, flags=r["flags"]))
    return ops, blocked


def _by_cat(ops):
    """Why: the move stage draws one vault per category with the exact number of files queued."""
    out = {}
    for o in ops:
        c = out.setdefault(o["cat"], dict(n=0, size=0))
        c["n"] += 1
        c["size"] += o["size"]
    return out


def _ids(b):
    """Why: selections arrive as explicit ids (never paths) and must not be empty."""
    return schema.id_list(b, required=True)


def _transfer_request(b):
    """Why: the conflict preview and the move itself read the request the same way (destination, mode, layout, files)."""
    dest = check_destination(b.get("dest", ""))
    mode = b.get("mode", "move")
    if mode not in ("move", "copy"):
        raise ApiError(400, "Unknown mode.")
    layout = b.get("layout") or ("type" if b.get("flat") else "organized")
    if layout not in LAYOUTS:
        raise ApiError(400, "Unknown layout.")
    ids = _ids(b) if b.get("ids") is not None else index_db.ids_for(_plan_filters(b))[0]
    ops, blocked = _ops_for(ids, b, layout)
    return dest, mode, ops, blocked


@route(R, "POST", "conflicts")
def r_conflicts(h, qs, b):
    """Why: before a move or copy: which files already exist where they would go ("12 files already exist in this
    folder"), both sides' size and date, and whether the content is identical. Read-only."""
    if b.get("kind") == "quarantine":   # the Corrupted page's Quarantine: same rules, its own folder
        dest, ops = _quarantine_dest(create=False), _ops_for(_ids(b), b, "here")[0]
    else:
        dest, _, ops, _ = _transfer_request(b)
    h.send(200, conflicts.find(ops, dest) if os.path.isdir(dest) else dict(total=0, identical=0, rows=[], more=0))


@route(R, "POST", "execute")
def r_execute(h, qs, b):
    """Why: starts a move/copy job from explicit ids (selection) or the preview's filters; progress via /api/job."""
    dest, mode, ops, blocked = _transfer_request(b)
    verify = b.get("verify") or config.VERIFY_DEFAULT
    if verify not in copier.VERIFY_MODES:
        raise ApiError(400, "Unknown verification mode.")
    choice = conflicts.clean_choice(b.get("conflicts"))
    _check_space(dest, mode, ops)
    job = _start_transfer(dest, mode, ops, verify, blocked=blocked, conflicts=choice)
    settings.remember_destination(dest)
    h.send(200, {"job": job.id, "count": len(ops), "blocked": blocked, "by_cat": _by_cat(ops)})


def _start_transfer(dest, mode, ops, verify, label="", conflicts=None, **extra):
    """Why: one place starts a move/copy job and keeps the index in step with every finished file."""
    def on_done(op, dst):
        (index_db.record_move if mode == "move" else index_db.record_copy)(op["fid"], dst)
    job = jobs.Job("move", total=len(ops), total_bytes=sum(o["size"] for o in ops), **extra)
    return jobs.start(job, lambda j: mover.run(j, dest, mode, ops, on_done, label=label, verify_mode=verify, conflicts=conflicts))


def _existing(path):
    p = os.path.abspath(path)
    while not os.path.exists(p) and os.path.dirname(p) != p:
        p = os.path.dirname(p)
    return p


def _check_space(dest, mode, ops):
    """Why: refuse up front when the copies would not fit (same-drive moves need no space)."""
    root = _existing(dest)
    try:
        dev, free = os.stat(root).st_dev, shutil.disk_usage(root).free
    except OSError:
        return
    devs = {}
    need = 0
    for o in ops:
        if o["dir"] not in devs:
            try:
                devs[o["dir"]] = os.stat(o["dir"]).st_dev
            except OSError:
                devs[o["dir"]] = None
        if mode == "copy" or devs[o["dir"]] != dev:
            need += o["size"]
    if need and need > free - config.FREE_SPACE_MARGIN_BYTES:
        raise ApiError(400, f"Not enough free space on {platform_utils.drive_of(root)}: this needs {_gb(need)}, and {_gb(max(0, free))} is free.")


def _gb(n):
    """Why: plain sizes in error messages ("14.5 GB")."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024
    return f"{n:.1f} TB"


@route(R, "POST", "integrity/start")
def r_integrity_start(h, qs, b):
    """Why: Integrity Check (quick: structure; deep: reads every byte) on all files or the selected ones, read-only."""
    ids = schema.id_list(b) or None
    h.send(200, {"job": checks.start_integrity(b.get("mode", "quick"), ids).id})


@route(R, "GET", "integrity/results")
def r_integrity_results(h, qs, b):
    """Why: the Corrupted page: problem files with what is wrong, the likely cause and what to do."""
    _, page, per = page_args(qs)
    out = checks.integrity_results(qs_get(qs, "sev"), page, per)
    out["rows"] = with_links(out["rows"])
    h.send(200, out)


@route(R, "GET", "integrity/csv")
def r_integrity_csv(h, qs, b):
    """Why: 'Export CSV' (a file the user asked for; it contains paths)."""
    h.send(200, checks.integrity_csv(), "text/csv; charset=utf-8", {"Content-Disposition": f'attachment; filename="{config.APP_SLUG}-problem-files.csv"'})


@route(R, "POST", "duplicates/start")
def r_duplicates_start(h, qs, b):
    """Why: find identical files (size, then first/last 64 KB, then a full hash), read-only."""
    h.send(200, {"job": checks.start_duplicates().id})


@route(R, "GET", "duplicates/results")
def r_duplicates_results(h, qs, b):
    """Why: groups of identical files, biggest waste first."""
    out = checks.duplicate_results(max(1, int(qs_get(qs, "page", "1"))))
    for g in out["groups"]:
        g["rows"] = with_links(g["rows"])
    h.send(200, out)


@route(R, "GET", "duplicates/extras")
def r_duplicates_extras(h, qs, b):
    """Why: 'Select all but the newest copy' in every group."""
    ids, sizes = checks.duplicate_extras()
    h.send(200, dict(ids=ids, sizes=sizes))


@route(R, "GET", "cleanup")
def r_cleanup(h, qs, b):
    """Why: the 'Clean junk files' review list (rules only; nothing is selected or removed automatically)."""
    reason = qs_get(qs, "reason")
    if not reason:
        return h.send(200, dict(groups=checks.cleanup_summary()))
    _, page, per = page_args(qs)
    out = checks.cleanup_rows(reason, page, per)
    out["rows"] = with_links(out["rows"])
    h.send(200, out)


@route(R, "GET", "cleanup/ids")
def r_cleanup_ids(h, qs, b):
    ids, sizes = checks.cleanup_ids(qs_get(qs, "reason"))
    h.send(200, dict(ids=ids, sizes=sizes))


def _quarantine_dest(create=True):
    base_dest = settings.load()["dest"] or platform_utils.default_destination()
    if create:
        os.makedirs(base_dest, exist_ok=True)
    return check_destination(os.path.join(base_dest, "Quarantine"))


@route(R, "POST", "quarantine")
def r_quarantine(h, qs, b):
    """Why: move problem files into one Quarantine folder (a normal, undoable move, labelled in History)."""
    dest = _quarantine_dest()
    ops, blocked = _ops_for(_ids(b), b, "here")
    _check_space(dest, "move", ops)
    job = _start_transfer(dest, "move", ops, b.get("verify") or config.VERIFY_DEFAULT, blocked=blocked, label="quarantine",
                          conflicts=conflicts.clean_choice(b.get("conflicts")))
    h.send(200, {"job": job.id, "count": len(ops), "blocked": blocked, "by_cat": _by_cat(ops), "dest": dest})


@route(R, "POST", "data/delete")
def r_data_delete(h, qs, b):
    """Why: Settings > Legal > 'Delete my AuraSort data' (AuraSort's own data only; your files are never touched)."""
    if b.get("confirm") != "DELETE":
        raise ApiError(400, "Confirm first.")
    h.send(200, {"removed": purge.delete_all()})


@route(R, "GET", "interrupted")
def r_interrupted(h, qs, b):
    """Why: jobs that stopped mid-way last time (crash, power loss), with what is left and any partial copies found."""
    out = history.interrupted()
    for x in out:
        x["parts"] = len(copier.leftovers([x["dest"]])) if x.get("dest") else 0
    h.send(200, out)


@route(R, "POST", "interrupted/resume")
def r_interrupted_resume(h, qs, b):
    """Why: 'Resume' continues an interrupted job with the files not done yet (each re-checked as usual)."""
    m = history.load(b.get("id", ""))
    if m.get("state") != "interrupted":
        raise ApiError(400, "That job is not waiting to be resumed.")
    done = {o.get("fid") for o in m.get("ops", [])}
    left = [p for p in m.get("plan", []) if p["fid"] not in done and os.path.exists(p["src"])]
    for f in copier.leftovers([m["dest"]]):
        trash.send_to_trash([f])   # our own partial copies from last time go to the Recycle Bin, never deleted
    m["state"] = "resumed"
    history.save(m)
    _check_space(m["dest"], m["mode"], left)
    job = _start_transfer(m["dest"], m["mode"], left, m.get("verify", config.VERIFY_DEFAULT), resumed_from=m["id"])
    h.send(200, {"job": job.id, "count": len(left), "by_cat": _by_cat(left)})


@route(R, "POST", "interrupted/clean")
def r_interrupted_clean(h, qs, b):
    """Why: 'Clean up' sends partial copies left by the interrupted job to the Recycle Bin and closes it (the originals are untouched)."""
    m = history.load(b.get("id", ""))
    parts = copier.leftovers([m["dest"]]) if m.get("dest") else []
    res = trash.send_to_trash(parts) if parts else None
    m["state"] = "closed"
    history.save(m)
    h.send(200, {"parts": len(parts), "removed": len(res.trashed) if res else 0})


@route(R, "POST", "selection")
def r_selection(h, qs, b):
    """Why: the confirmation dialog says exactly what a selection holds before anything happens."""
    stats = index_db.selection_stats(schema.id_list(b))
    no_bin = {d for d in {g[2] for g in stats["groups"]} if d and not trash.bin_available(d)}
    stats["no_bin"] = sum(g[3] for g in stats["groups"] if g[2] in no_bin)
    stats["optin"] = settings.load()["optin"]
    h.send(200, stats)


@route(R, "POST", "trash")
def r_trash(h, qs, b):
    """Why: the only delete path: selected files go to the Recycle Bin/Trash after confirmation, never permanently deleted."""
    ids = _ids(b)
    if len(ids) >= config.TRASH_TYPED_CONFIRM_MIN and str(b.get("confirm_count", "")).strip() != str(len(ids)):
        raise ApiError(400, f"To send {len(ids)} files to the Recycle Bin, type {len(ids)} to confirm.")
    ops, blocked = _ops_for(ids, b)
    job = jobs.Job("trash", total=len(ops), total_bytes=sum(o["size"] for o in ops), blocked=blocked)
    jobs.start(job, lambda j: mover.run_trash(j, ops, index_db.record_removed))
    h.send(200, {"job": job.id, "count": len(ops), "blocked": blocked, "by_cat": _by_cat(ops)})


@route(R, "POST", "open-trash")
def r_open_trash(h, qs, b):
    """Why: after sending files to the Recycle Bin, one click shows where to restore them."""
    try:
        platform_utils.open_trash()
    except platform_utils.NoFileManager:
        return h.send(200, {"ok": False, "fallback": "apptrash"})   # Android: the UI opens Settings > AuraSort trash
    h.send(200, {"ok": True})


@route(R, "POST", "mkdir")
def r_mkdir(h, qs, b):
    """Why: 'New folder' in the destination picker: legal names only, never inside a protected place, never over an existing folder."""
    parent = canonical(str(b.get("parent") or "")) if b.get("parent") else ""
    name = safe_folder_name(b.get("name"))
    if not name:
        raise ApiError(400, 'That folder name is not allowed. Avoid \\ / : * ? " < > | and names like CON or NUL.')
    if not parent or not os.path.isdir(parent):
        raise ApiError(400, "Open a folder first, then create the new folder inside it.")
    path = os.path.join(parent, name)
    if protection_reason(path):
        raise ApiError(400, "Folders can't be created in a protected location.")
    try:
        os.mkdir(path)
    except FileExistsError:
        raise ApiError(409, "A folder with that name already exists here.") from None
    except OSError:
        raise ApiError(400, "That folder could not be created (no permission, or the drive is read-only).") from None
    h.send(200, {"path": path})


def _rows_in_chunks(ids):
    """Why: very large selections are resolved in chunks (SQLite parameter limits)."""
    out = []
    for i in range(0, len(ids), 900):
        out += index_db.rows_by_ids(ids[i:i + 900])
    return out


@route(R, "GET", "job")
def r_job(h, qs, b):
    """Why: live progress of a background job (recently moved images carry signed thumbnail links)."""
    snap = jobs.get(qs_get(qs, "id")).snapshot()
    if isinstance(snap.get("current"), list):
        snap["current"] = [dict(c, thumb=signing.url("thumb", c["id"])) if c.get("cat") == "Images" else c for c in snap["current"]]
    h.send(200, snap)


@route(R, "POST", "job/control")
def r_job_control(h, qs, b):
    """Why: pause, resume or cancel a background job (Document Insights, model downloads; scans have their own route)."""
    action = b.get("action")
    if action not in ("pause", "resume", "cancel"):
        raise ApiError(400, "Unknown action.")
    job = jobs.get(b.get("id"))
    getattr(job, action)()
    h.send(200, job.snapshot())


@route(R, "GET", "history")
def r_history(h, qs, b):
    """Why: every move, copy, scan and check, newest first."""
    h.send(200, history.entries(min(int(qs_get(qs, "limit", str(config.HISTORY_LIST_MAX))), config.HISTORY_LIST_MAX)))


@route(R, "GET", "history/item")
def r_history_item(h, qs, b):
    """Why: 'Details' lists exactly which files an action touched (and where they went)."""
    m = history.load(qs_get(qs, "id"))
    ops = m.get("ops") or []
    shown = [dict(src=o.get("src", ""), dst=o.get("dst", ""), size=o.get("size", 0)) for o in ops[:config.HISTORY_DETAIL_MAX]]
    h.send(200, dict(history.summary(m), ops=shown, more=max(0, len(ops) - len(shown))))


@route(R, "POST", "undo")
def r_undo(h, qs, b):
    """Why: puts moved files back and updates the index so lists stay correct."""
    def restored(op, target):
        if op.get("fid") is not None:
            index_db.record_move(op["fid"], target, kind="ok")
    h.send(200, mover.undo(b.get("id", ""), restored))


# ---------------- Document Insights (optional, off by default) ----------------
MODEL_RX = re.compile(r"^[A-Za-z0-9._:/-]{1,80}$")
KEY_MAX = 400


def _ai_public(s):
    """Why: settings for the UI; the API key itself is never sent back, only whether one is present."""
    return dict(s, key_in_session=bool(keystore.get_session()), key_saved=keystore.has_saved())


@route(R, "GET", "ai/status")
def r_ai_status(h, qs, b):
    """Why: one call for the Document Insights screens (consent, engine, hardware, current results and job)."""
    s = docai.ai_settings()
    job = next((j for j in jobs.JOBS.values() if j.kind == "docai" and j.state in ("running", "paused", "waiting")), None)
    h.send(200, dict(settings=_ai_public(s), engine=docai.engine_status(s) if s["consent_local"] else None, hardware=hardware.facts(),
                     downloads=config.AI_DOWNLOADS, presets=config.AI_CLOUD_PRESETS, ttl_choices=config.AI_TTL_CHOICES_MIN,
                     results=docai.summary(), job=job.id if job else None, pypdf=bool(extract.PdfReader),
                     docs=len(index_db.ids_for({"exts": list(extract.DOC_EXTS), "scope": "all"})[0])))


@route(R, "POST", "ai/settings")
def r_ai_settings(h, qs, b):
    """Why: consent, engine, model and limits (never the API key, which has its own route)."""
    cur = dict(docai.ai_settings())
    cur.update({k: v for k, v in schema.obj(b, "settings").items() if k in settings.AI_DEFAULTS and not k.startswith("consent")})
    if b.get("accept_local"):
        cur["consent_local"] = time.time()
    if b.get("accept_cloud"):
        cur["consent_cloud"] = time.time()
    h.send(200, _ai_public(settings.update(ai=cur)["ai"]))


@route(R, "POST", "ai/key")
def r_ai_key(h, qs, b):
    """Why: the cloud API key goes to session memory (or the OS keychain if asked); it is never echoed or logged."""
    key = str(b.get("key") or "").strip()
    if not key or len(key) > KEY_MAX or any(c.isspace() for c in key):
        raise ApiError(400, "Paste the API key exactly as the provider shows it.")
    remembered = keystore.remember(key) if b.get("remember") else (keystore.set_session(key) or False)
    h.send(200, {"ok": True, "remembered": bool(remembered)})


@route(R, "POST", "ai/test")
def r_ai_test(h, qs, b):
    """Why: 'Test connection' lists the models the engine or provider offers."""
    mode = b.get("mode", "local")
    try:
        models = docai.make_engine(mode).models(timeout=config.AI_PROBE_TIMEOUT_S * 5)
    except llm.LLMError as e:
        raise ApiError(400, str(e)) from None
    h.send(200, {"ok": True, "models": [m["name"] for m in models][:50]})


@route(R, "POST", "ai/engine/start")
def r_ai_engine_start(h, qs, b):
    """Why: start `ollama serve` after the user clicked (stopped again on exit only if we started it)."""
    try:
        docai.start_engine()
    except llm.LLMError as e:
        raise ApiError(400, str(e)) from None
    h.send(200, {"ok": True})


@route(R, "POST", "ai/pull")
def r_ai_pull(h, qs, b):
    """Why: download a model through Ollama, with progress, after the user confirmed the size."""
    name = str(b.get("model") or "")
    if not MODEL_RX.match(name):
        raise ApiError(400, "Unknown model name.")
    h.send(200, {"job": docai.pull_model(name).id})


@route(R, "POST", "ai/start")
def r_ai_start(h, qs, b):
    """Why: read the selected documents (or every document) in the background."""
    ids = schema.id_list(b) or None
    h.send(200, {"job": docai.start(ids, b.get("mode", "local")).id})


@route(R, "POST", "ai/confirm")
def r_ai_confirm(h, qs, b):
    """Why: the per-batch cloud confirmation (with an explicit override for Confidential files)."""
    docai.confirm_cloud(jobs.get(b.get("job")), b.get("allow_confidential"))
    h.send(200, {"ok": True})


@route(R, "POST", "ai/clear")
def r_ai_clear(h, qs, b):
    """Why: 'Clear now' removes every result from memory."""
    docai.clear()
    h.send(200, {"ok": True})


@route(R, "POST", "ai/reset")
def r_ai_reset(h, qs, b):
    """Why: withdraw consent: AI settings to defaults, key removed (session and keychain), results cleared."""
    docai.reset()
    h.send(200, {"ok": True})


def _ai_filter(qs):
    """Why: the results screen's filters, validated like every other list."""
    sens = qs_get(qs, "sens")
    if sens and sens not in sensitive.LEVELS:
        raise ApiError(400, "Unknown sensitivity.")
    f = filters_from(qs)
    return dict(sens=sens, doctype=qs_get(qs, "doctype")[:40].lower(), junk=qs_get(qs, "junk") == "1", q=f.get("q", "").lower(),
                exts=set(f.get("exts") or []), dfrom=f.get("dfrom"), dto=f.get("dto"))


@route(R, "GET", "ai/results")
def r_ai_results(h, qs, b):
    """Why: Document Insights results, 100 per page, with the files' current folders from the index."""
    _, page, per = page_args(qs)
    out = docai.query(_ai_filter(qs), page, per)
    rows = docai.file_rows_for(r["fid"] for r in out["rows"])
    out["rows"] = [dict(with_links([rows[r["fid"]]])[0], ai=r) for r in out["rows"] if r["fid"] in rows]
    h.send(200, out)


@route(R, "GET", "ai/ids")
def r_ai_ids(h, qs, b):
    """Why: 'Select all N matching' on the results screen."""
    ids = docai.query(_ai_filter(qs), 1, 10 ** 9)["ids"]
    rows = docai.file_rows_for(ids)
    h.send(200, dict(ids=[i for i in ids if i in rows], sizes=[rows[i]["size"] for i in ids if i in rows]))


# ---------------- startup ----------------
class LocalServer(ThreadingHTTPServer):
    """Why: exclusive bind, so no other program can grab the same port (SO_REUSEADDR allows that on Windows)."""
    allow_reuse_address = not config.WIN
    daemon_threads = True
    request_queue_size = config.LISTEN_BACKLOG   # the default (5) refuses connections when a page loads ~30 files at once

    def server_bind(self):
        # Why: HTTPServer.server_bind also calls socket.getfqdn(), a reverse DNS lookup that can stall a start for many
        # seconds (macOS CI: 37 s to start vs 1-2 s elsewhere). Nothing uses server_name, so only bind and keep the address.
        if config.WIN and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


def make_server(port):
    """Why: try a few ports so a busy default port is not fatal; always loopback."""
    for p in range(port, port + config.PORT_SEARCH_RANGE):
        try:
            Handler.port = p
            return LocalServer((config.BIND_HOST, p), Handler), p
        except OSError:
            continue
    sys.exit("No free port found. Try --port 9000.")


def prepare():
    """Why: private data folders, legacy history import and the index must exist before serving."""
    setup_log()
    history.ensure_dirs()
    history.migrate_legacy()
    history.mark_interrupted()
    index_db.init()


def start_folder():
    """Why: a terminal opened 'as administrator' starts in C:\\Windows\\System32. Nothing may depend on the start folder,
    so the server works from the user's home folder."""
    return str(config.HOME) if os.path.isdir(config.HOME) else os.getcwd()


def console_utf8():
    """Why: a Windows console in cp1252/cp437 crashes print() on a non-English name; replace what it cannot show instead."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


def main():
    if sys.version_info < (3, 10):
        sys.exit(f"{config.APP_NAME} needs Python 3.10 or newer (this is {sys.version.split()[0]}). Get it from python.org.")
    """Why: parse arguments, prepare data, start the local-only server."""
    console_utf8()
    ap = argparse.ArgumentParser(description=f"{config.APP_NAME} - {config.TAGLINE} (local server)")
    ap.add_argument("--port", type=int, default=config.DEFAULT_PORT)
    ap.add_argument("--host", default=config.BIND_HOST, help="must be 127.0.0.1 (local only)")
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--doctor", action="store_true", help="check this computer (Python, data folder, SQLite, folders, a 3-second test scan) and exit")
    ap.add_argument("--folder", default="", help="with --doctor: the folder to test-scan (default: the first Quick Scan folder)")
    ap.add_argument("--json", action="store_true", help="with --doctor: print JSON instead of text")
    ap.add_argument("--wait-for-lock", action="store_true", help=argparse.SUPPRESS)   # set by "Restart with administrator permission"
    ap.add_argument("--self-test", action="store_true", help="scan a temporary folder of known files and say whether all were found")
    a = ap.parse_args()
    if a.host not in config.LOCAL_HOSTNAMES:
        sys.exit(f"{config.APP_NAME} only listens on 127.0.0.1 (refusing {a.host!r}).")
    if a.doctor:
        from core import doctor
        sys.exit(doctor.main(a.folder or None, a.json))
    if a.self_test:
        from core import doctor
        sys.exit(doctor.self_test())
    setup_log()
    try:
        os.chdir(start_folder())
    except OSError:
        pass
    if a.wait_for_lock:   # the copy that asked for elevation is handing over: give it a moment to stop
        for _ in range(80):
            if instance.acquire():
                break
            time.sleep(0.25)
    if not instance.held() and not instance.acquire():
        port = instance.running_port()
        url = f"http://localhost:{port}/" if port else ""
        print(f"\n  {config.APP_NAME} is already running{' at ' + url if url else ''}.\n"
              "  Only one copy can use your data folder at a time (two would fight over the file index).\n", flush=True)
        if url and not a.no_browser:
            platform_utils.open_url(url)
        sys.exit(0)
    prepare()
    Handler.token = secrets.token_urlsafe(config.TOKEN_BYTES)
    add_secret(Handler.token)
    srv, port = make_server(a.port)
    instance.remember_port(port)
    url = f"http://localhost:{port}/"
    print(f"\n  {config.APP_NAME} - {config.TAGLINE}\n  running at {url}\n  (local only - press Ctrl+C to stop)\n"
          f"  Log file: {config.LOG_FILE}\n", flush=True)
    if platform_utils.is_admin():
        if config.WIN:   # the Windows installer sets AuraSort up this way on purpose
            print("  Running with administrator permission. Windows system folders are still never touched.\n", flush=True)
            log.info("running with administrator permission")
        else:
            print("  Warning: running as root. AuraSort does not need it; start it as your normal user.\n", flush=True)
            log.warning("running with root rights")
    if trash.fake_bin_dir():
        print(f"  Test mode: 'Recycle Bin' moves files into {trash.fake_bin_dir()} ({trash.TEST_TRASH_ENV} is set).\n", flush=True)
        log.warning("test bin folder in use instead of the Recycle Bin")
    atexit.register(docai.stop_engine)   # only stops the AI engine if AuraSort started it
    if not a.no_browser:
        threading.Timer(0.6, lambda: platform_utils.open_url(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("bye")


if __name__ == "__main__":
    main()
