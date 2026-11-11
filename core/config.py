"""AuraSort configuration. Every tunable constant lives here so no other module needs magic numbers."""
import os
import sys
from pathlib import Path

# ---------------- product ----------------
APP_NAME = "AuraSort"
APP_SLUG = "aurasort"
APP_VERSION = "1.1.1"
TAGLINE = "Make your files easier."
SUBLINE = "Scan your whole PC, find anything fast, and sort files safely."

# ---------------- platform ----------------
WIN = os.name == "nt"
MAC = sys.platform == "darwin"
# Termux on Android reports "linux"; CPython's own Android build reports "android". Both have no Recycle Bin.
ANDROID = sys.platform == "android" or (sys.platform.startswith("linux") and ("ANDROID_ROOT" in os.environ or "com.termux" in os.environ.get("PREFIX", "")))
FAKE_PLATFORM_ENV = "AURASORT_FAKE_PLATFORM"   # tests only: "android" simulates Termux on a desktop (paths and trash; no check is loosened)
ANDROID = ANDROID or os.environ.get(FAKE_PLATFORM_ENV) == "android"
LINUX = sys.platform.startswith("linux") or ANDROID
PLATFORM = "windows" if WIN else "mac" if MAC else "android" if ANDROID else "linux"

# ---------------- network (local only) ----------------
BIND_HOST = "127.0.0.1"            # loopback only: the server refuses any other address
LOCAL_HOSTNAMES = ("127.0.0.1", "localhost")
ALLOWED_HOST_NAMES = LOCAL_HOSTNAMES + ("[::1]",)   # Host/Origin values accepted ([::1] is what a browser opened at the IPv6 loopback address sends)
DEFAULT_PORT = 8765
PORT_SEARCH_RANGE = 20             # try this many ports if the default is busy
LISTEN_BACKLOG = 128               # pending connections the server accepts (a page load opens many at once)
TOKEN_HEADER = "X-AuraSort-Token"  # nosec B105  # not a password (header name / empty default / local test token)
TOKEN_BYTES = 24
MAX_BODY_BYTES = 4 * 1024 * 1024   # largest accepted JSON body (200k ids fit comfortably)
GZIP_MIN_BYTES = 1024              # smaller responses are not worth compressing
SIGNED_URL_TTL_S = 15 * 60         # preview/thumbnail links expire after 15 minutes
SIG_HEX_CHARS = 32                 # truncated HMAC length in signed URLs
RATE_LIMITS = {                    # endpoint -> (max calls, per seconds)
    "scan": (4, 10), "estimate": (4, 10), "execute": (6, 10), "trash": (6, 10), "open": (20, 10),
    "integrity": (4, 10), "duplicates": (4, 10), "mkdir": (20, 10), "undo": (6, 10), "ai": (10, 10),
    "pin": (12, 10), "diagnostics": (3, 10),
}

# ---------------- local data (user-only permissions) ----------------
HOME = Path.home()
DATA_DIR = HOME / f".{APP_SLUG}"
HISTORY_DIR = DATA_DIR / "history"
INDEX_DB = DATA_DIR / "index.sqlite3"
THUMB_DIR = DATA_DIR / "thumbs"
SETTINGS_FILE = DATA_DIR / "settings.json"
LOG_DIR = DATA_DIR / "logs"
LOG_FILE = LOG_DIR / "server.log"
LOG_MAX_BYTES = 1024 * 1024
LOG_BACKUPS = 3
LOG_FILE_SHOWN = f"~/.{APP_SLUG}/logs/server.log"   # how the log location is shown to people (no user name in it)
LOCK_FILE_NAME = "server.lock"     # one running AuraSort per data folder (two servers would fight over the index)
# Earlier versions of this app kept their history here; it is copied (read-only) into HISTORY_DIR once.
LEGACY_DATA_DIRS = (HOME / ".neon-tidy", HOME / ".aurelia")
DEST_FOLDER_NAME = "AuraSortFiles"
WEB_DIR = Path(__file__).resolve().parent.parent / "docs"

# ---------------- scanning ----------------
SCAN_WORKERS_PER_DRIVE = 3         # fallback when the drive type is unknown
SCAN_WORKERS = {"ssd": 6, "hdd": 2, "usb": 2, "network": 2, "unknown": 3}   # threads per drive: SSDs like parallel reads, HDDs hate seeks
CLOUD_ATTRS = 0x1000 | 0x40000 | 0x400000   # Windows OFFLINE | RECALL_ON_OPEN | RECALL_ON_DATA_ACCESS (OneDrive "online-only")
MAC_DATALESS = 0x40000000          # macOS SF_DATALESS (iCloud placeholder)
SCAN_BATCH_ROWS = 2000             # rows written to SQLite per transaction
MAX_PATH_CHARS = 32767             # longest path Windows accepts (long-path prefix included)
SCAN_MAX_ROOTS = 200               # drives + folders in one scan request
SCAN_SKIP_REASONS = {              # why an item was left out of a scan (counted, shown, never fatal)
    "no_access": "no permission", "vanished": "removed during the scan", "unreadable": "could not be read",
    "bad_name": "name the index cannot store", "missing_root": "folder not found", "error": "unexpected problem (see the log)",
    "link": "links or junctions to other places (skipped to avoid loops)", "hidden": "hidden folders",
    "protected": "system or tool folders (protected)", "system_file": "system files such as Thumbs.db and desktop.ini",
    "skip_list": "folders you chose to skip",
}
SCAN_NOTES = {                     # files that WERE counted but are special (shown so numbers are never a mystery)
    "online_only": "online-only (OneDrive/iCloud): listed, never downloaded", "partial": "unfinished downloads",
    "project": "inside project folders (left alone when sorting)", "other_ext": "unknown extensions (listed under Other)",
}
# ---------------- PIN lock ----------------
PIN_FILE_NAME = "pin.json"         # salt + slow hash + failed-attempt counter; never the PIN itself
PIN_SCRYPT_N = 2 ** 15             # scrypt cost (32 MB, roughly 0.1 s per check on a normal PC)
PIN_PBKDF2_ITERATIONS = 600_000    # fallback where Python has no scrypt (OWASP 2023 minimum for PBKDF2-HMAC-SHA256)
PIN_FREE_TRIES = 5                 # wrong PINs before the first wait
PIN_LOCKOUT_S = (30, 60, 300, 900) # then 30 s, 1 min, 5 min, 15 min (and 15 min for every further miss); kept across restarts
PIN_ACTION_TOKEN_S = 60            # a PIN confirmation is valid this long, for one request only
PIN_IDLE_MIN_DEFAULT = 10          # lock after this many minutes without activity
PIN_IDLE_CHOICES_MIN = (1, 5, 10, 15, 30, 60)
PIN_REMEMBER_CHOICES_MIN = (0, 1, 5, 15)   # "do not ask again for N minutes" (0 = ask every time, the default)
# Guarded routes -> the action a PIN confirmation is issued for (server.py checks the token before the route runs).
PIN_GUARDED = {"execute": "transfer", "trash": "trash", "undo": "undo", "quarantine": "transfer", "data/delete": "delete_data",
               "interrupted/resume": "transfer", "interrupted/clean": "trash", "ai/key": "ai_key", "ai/reset": "ai_key",
               "apptrash/restore": "undo", "pin/settings": "settings"}
PIN_ACTIONS = frozenset(PIN_GUARDED.values())
# Routes that work while locked (or before a PIN exists): start-up facts, the PIN screens themselves.
PIN_OPEN_ROUTES = ("info", "pin/status", "pin/set", "pin/unlock", "pin/reset", "pin/lock")

# ---------------- app-managed trash (where the OS has none: Android; and for "Replace") ----------------
APPTRASH_DIR_NAME = ".AuraSortTrash"   # on the same drive as the file, so a "delete" is an instant rename, never a copy
APPTRASH_INDEX = "apptrash.json"       # in the data folder: what is where, for Restore
APPTRASH_PURGE_CHOICES_DAYS = (0, 30, 60, 90)   # 0 = never erase (the default). The only thing that ever deletes for good.

# ---------------- name clashes in the destination ----------------
CONFLICT_PREVIEW_MAX = 500         # clashes listed side by side in the dialog (the rest are counted)
CONFLICT_COMPARE_MAX_BYTES = 1024 ** 3   # the preview compares up to 1 GB of same-size files byte by byte
CONFLICT_PER_FILE_MAX = 200000     # per-file choices accepted in one request

DOCTOR_TEST_SCAN_S = 3.0           # the --doctor test scan stops after this long
DOCTOR_TEST_SCAN_MAX_FILES = 20000
SCHEMA_STRICT_ENV = "AURASORT_STRICT_SCHEMA"   # tests set this: unknown request fields are refused instead of logged
SCAN_STATUS_RECENT_DIRS = 6        # folder paths shown in the live ticker
ESTIMATE_BENCH_SECONDS = 2.5       # files/second benchmark before a scan
ESTIMATE_LOW_FACTOR = 0.7          # ETA range shown as an honest estimate
ESTIMATE_HIGH_FACTOR = 1.6
DEFAULT_AVG_FILE_BYTES = 2 * 1024 * 1024
ETA_SMOOTHING = 0.25               # exponential moving average weight for rates
MAC_BUNDLE_EXTS = (".app", ".photoslibrary", ".xcodeproj", ".pkg", ".bundle", ".framework", ".plugin", ".kext")
IGNORED_FILE_NAMES = {".ds_store", "thumbs.db", "desktop.ini", ".localized", "icon\r"}
IGNORED_FILE_PREFIXES = ("._",)
PARTIAL_DOWNLOAD_EXTS = {"crdownload", "part", "partial", "download", "opdownload"}
TEMP_EXTS = {"tmp", "temp"}

# ---------------- moving ----------------
NAME_PART_MAX = 80                 # longest folder name created by auto-organize
MANIFEST_SAVE_EVERY = 100          # flush the undo manifest every N files
JOB_CURRENT_KEEP = 12              # recently moved files reported to the UI
COPY_SMALL_FILE_BYTES = 8 * 1024 * 1024   # smaller cross-drive copies run a few at a time
COPY_SMALL_THREADS = {"ssd": 8, "hdd": 2, "usb": 4, "network": 4, "unknown": 4}   # by destination drive: parallel copies hide fsync latency
FREE_SPACE_MARGIN_BYTES = 256 * 1024 * 1024   # a job never fills the destination drive to the last byte
VERIFY_DEFAULT = "full"            # full BLAKE2b check of every cross-drive copy ("fast" = size + sampled blocks)
EST_RENAME_FILES_PER_S = 800       # same-drive move estimate (renames are cheap)
EST_COPY_BYTES_PER_S = 80 * 1024 * 1024
FREE_SPACE_NOISE_BYTES = 1024 * 1024

# ---------------- trash ----------------
TRASH_BATCH = 100                  # files per Recycle Bin call
TRASH_TYPED_CONFIRM_MIN = 100      # 100+ files need the count typed to confirm

# ---------------- previews ----------------
THUMB_PX = 320
THUMB_QUALITY = 78
THUMB_RAW_MAX_BYTES = 25 * 1024 * 1024   # without Pillow, originals up to this size are served as thumbnails
TEXT_PREVIEW_BYTES = 200 * 1024
TEXT_SNIFF_BYTES = 4096            # a NUL byte in the first 4 KB means "binary, not text"
STREAM_CHUNK = 256 * 1024
YEAR_MIN, YEAR_MAX = 1970, 2100    # calendar years the UI can ask for

# ---------------- integrity / duplicates ----------------
INTEGRITY_HEAD_BYTES = 64 * 1024
INTEGRITY_TAIL_BYTES = 64 * 1024
INTEGRITY_READ_CHUNK = 1024 * 1024
DUP_MIN_BYTES = 1                  # zero-byte files are never "duplicates"
DUP_PARTIAL_BYTES = 64 * 1024      # first/last bytes hashed in stage 2
DRIVE_PROBLEM_SHARE_HINT = 0.6     # one drive holding most problem files triggers a backup hint
DRIVE_PROBLEM_MIN_FILES = 5

# ---------------- Document Insights (optional, off by default) ----------------
AI_LOCAL_ENGINES = {"ollama": "http://127.0.0.1:11434", "lmstudio": "http://127.0.0.1:1234", "llamacpp": "http://127.0.0.1:8080"}
AI_LOCAL_HOSTS = ("127.0.0.1", "localhost")      # local mode never talks to anything else
AI_DOWNLOADS = {"ollama": "https://ollama.com/download", "lmstudio": "https://lmstudio.ai"}
AI_CLOUD_PRESETS = {
    "deepseek": {"label": "DeepSeek", "base_url": "https://api.deepseek.com", "model": "deepseek-chat", "key_page": "https://platform.deepseek.com/api_keys"},
    "openai-compatible": {"label": "OpenAI-compatible API", "base_url": "", "model": "", "key_page": ""},
}
# (minimum RAM in GB as Windows reports it - an "8 GB" PC shows about 7.7 -, size class, example Ollama model names). Suggestions only: the installed list is always read first.
AI_MODEL_TIERS = ((3.5, "Tiny (1B class)", ("llama3.2:1b", "qwen2.5:1.5b")),
                  (7, "Small (3B class)", ("llama3.2:3b", "qwen2.5:3b")),
                  (14, "Medium (7-8B class)", ("qwen2.5:7b", "llama3.1:8b")))
AI_VISION_MIN_RAM_GB = 14                      # image descriptions (Phase 12b) need a vision model and more memory
AI_MAX_FILE_BYTES = 50 * 1024 * 1024           # bigger documents are skipped with a reason
AI_MAX_PART_BYTES = 20 * 1024 * 1024           # largest XML part read from an Office file (zip-bomb guard)
AI_MAX_PAGES = 10                              # pages (or slides) read per document
AI_MAX_CHARS = 12000                           # characters kept per document
AI_CHUNK_CHARS = 6000                          # long excerpts are summarised in chunks of this size
AI_CLOUD_MAX_CHARS = 4000                      # data minimisation: at most this much text per file goes to a cloud API
AI_CONTEXT_DEFAULT = 4096
AI_PARALLEL_MAX = 4
AI_TTL_CHOICES_MIN = (30, 60, 90)              # results are cleared this long after a batch finishes
AI_TTL_DEFAULT_MIN = 60
AI_REQUEST_TIMEOUT_S = 180                     # local models on a CPU can be slow
AI_PROBE_TIMEOUT_S = 2
AI_REPLY_MAX_BYTES = 256 * 1024
AI_DESCRIPTION_WORDS = 25
AI_KEYCHAIN_TARGET = "AuraSort cloud AI key"
AI_RESULTS_PAGE = 100

# ---------------- cleanup ----------------
OLD_INSTALLER_DAYS = 30
TEMP_MIN_AGE_DAYS = 7
PARTIAL_MIN_AGE_DAYS = 1

# ---------------- lists ----------------
PAGE_SIZE = 100
BIGGEST_N = 8
LARGE_FILES_N = 500
ACTIVITY_N = 8
HISTORY_LIST_MAX = 200
HISTORY_DETAIL_MAX = 500           # files listed in a History entry's details
