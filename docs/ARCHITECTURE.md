# How AuraSort is built

A small Python server (standard library only) on `127.0.0.1` plus a plain HTML/CSS/JS front end (no build step).

```
browser (docs/)  --fetch + X-AuraSort-Token-->  server.py (routes)  -->  core/* (logic)  -->  your files (read; act only on confirm)
                 <--JSON / signed file links--                         core/index_db (SQLite in ~/.aurasort)
                                                                       core/llm --127.0.0.1 only--> Ollama / LM Studio (optional)
                                                                       core/llm --HTTPS, opt-in----> cloud AI API (optional)
```

## Server (`server.py`, `core/`)

| Module | Job |
|---|---|
| `web.py` | HTTP plumbing: Host/Origin/Sec-Fetch-Site checks, token, rate limits, body limit, security headers, gzip, static files, streaming with HTTP ranges. |
| `server.py` | Routes only: validates input (through `schema.py`) and calls the modules below. |
| `schema.py` | The request contract: the fields every POST route reads, typed helpers with defaults, and 400 errors with a code and a hint. |
| `instance.py` | One server per data folder (an OS file lock); a second start opens the running one instead of fighting over the index. |
| `config.py` | Every constant (limits, timings, names, model suggestions). |
| `scanner.py` | Background scan: one small thread pool per drive (sized by drive media: SSD/HDD/USB/network), `os.scandir` reusing `DirEntry.stat()`, a single SQLite writer thread, project detection, cloud-placeholder flags, live counts and an ETA. |
| `index_db.py` | SQLite index (WAL): files, folders, projects, snapshots, integrity results, hashes. Server-side filter, sort and pagination, facets, cached summaries, the search index for the browser worker, and updates after moves (lists stay correct without a rescan). |
| `classify.py` | 14 categories, view-only rules, preview and "open" allow-lists. |
| `safety.py` | Protected locations (canonical paths), project/asset detection, legal names, no-overwrite naming. |
| `dates.py` | Date filters in local time. |
| `mover.py` | Move/copy/Recycle Bin jobs: journal first, re-check every file, same-drive rename or verified copy, Undo. |
| `copier.py` | The verified copy engine: `CopyFileExW` / `shutil` fast paths / APFS clone / buffered fallback into `.aurasort-part`, fsync for moves, BLAKE2b or sampled verification, no-overwrite rename, retries, disk-full stop, leftovers after a crash. |
| `trash.py` | Recycle Bin (`SHFileOperationW`), Finder (`osascript`), `gio` / freedesktop Trash. Never a permanent delete. |
| `history.py` | JSON manifests for every action, legacy import, interrupted-job detection. |
| `jobs.py` | Background jobs with pause/resume/cancel, smoothed ETA and JSON snapshots. |
| `integrity.py`, `checks.py` | Read-only integrity checks (quick/deep), duplicates (size, partial hash, full hash), cleanup rules. |
| `signing.py` | Short-lived HMAC links for thumbnails and previews (the token never goes into a URL). |
| `extract.py`, `sensitive.py`, `llm.py`, `docai.py`, `hardware.py`, `keystore.py` | Document Insights: text extraction (size-capped), deterministic confidential rules with checksums and masking, local/cloud model clients with strict JSON validation, the in-memory results store with its timer, hardware facts, API-key storage. |
| `platform_utils.py`, `log.py`, `settings.py` | OS specifics (drives, Windows Known Folders / XDG user dirs / Android storage, reparse-point rules, long paths, opening files, permissions), redacting log, validated settings. |
| `pin.py` | The PIN lock: scrypt hash + persisted lockout in `pin.json`, the unlocked session with its idle timeout, and single-use action tokens bound to one request. Enforced for every route in `web.py`. |
| `conflicts.py` | Name clashes in a destination: the preview (both sides, identical content), the validated choice (skip / keep / replace, per file or for all). |
| `apptrash.py` | AuraSort's own trash (`.AuraSortTrash` on the same drive, index in `apptrash.json`): Android deletes and files set aside by Replace; Restore; the opt-in purge timer. |
| `doctor.py` | `server.py --doctor` and Settings > Diagnostics: independent checks with masked paths and a 3-second test scan using the scanner's own rules. |

### Data
Everything lives in `~/.aurasort` (user-only permissions): `index.sqlite3`, `history/*.json`, `thumbs/`, `settings.json`,
`logs/server.log`, `pin.json` (salt, scrypt hash, wrong-try counter; never the PIN), `apptrash.json`. Files kept by Replace
(and Android deletes) live in `.AuraSortTrash` at the top of their own drive, so setting them aside is a rename.
The index carries a schema version (`PRAGMA user_version`, now 2; 1.0.0 had none): an older index is migrated, a newer or
unreadable one is set aside and rebuilt by the next scan. After each scan file rows without a folder are removed, and
`index_db.consistency()` compares totals, categories and lists (a difference is logged and shown as "refresh data"). Document Insights results are **never** written there: they stay in the server's memory.
`index_db.init()` updates an index written by an earlier version (outdated index tables are recreated and refilled by the
next scan; the scan list and storage snapshots get missing columns added) and sets aside a damaged index file as
`index.sqlite3.broken-<time>`. Settings and History entries from earlier versions are read with defaults for every field.

### Request contract (front end <-> server)
Every POST body is a JSON object. `core/schema.py` lists the fields each route reads (`POST_FIELDS`); unknown fields are
logged, and refused with a 400 when `AURASORT_STRICT_SCHEMA=1` (all test suites run that way). Ids are numbers, paths
are absolute strings, lists default to `[]`. `tests/test_contract.py` runs the real request builders from `docs/js` in
Node and checks every request against this table, and every response field the UI reads against what the server sends.

The scan request (`POST /api/scan/start`, built only by `scanRequest()` in `docs/js/views/scan.js`):

| Field | Type | Default | Rules |
|---|---|---|---|
| `mode` | `"quick"` or `"deep"` | `"quick"` | anything else: 400 `bad_mode` |
| `roots` | list of absolute paths (ticked drives + added folders) | `[]` | Quick Scan with `[]` = the usual folders; Deep Scan with `[]` = 400 `nothing_selected` ("Pick at least one drive or folder."). On Windows `C:` means `C:\`. Duplicates (case, trailing separator) and folders nested in another root are scanned once. A missing folder is skipped (counted as `missing_root`) while another root exists; with none left: 400 `not_found`. A protected system folder: 400 `protected`. |
| `skip` | list of absolute paths | `[]` | folders (and everything below) that are not scanned |
| `est_files` | number >= 0 | `0` | the estimate shown before the scan; only used for the progress bar |

`/api/scan/estimate` takes `mode` and `roots` with the same rules. `/api/scan/status` returns the job snapshot plus
`found, bytes, dirs, by_cat, recent, drives[], noaccess, skipped{reason: n}, skipped_total, skipped_reasons[], step,
failure`. Skip reasons: `no_access`, `vanished`, `unreadable`, `bad_name` (a name SQLite cannot store), `missing_root`,
`error` (an unexpected problem in one folder; its traceback is in the log), `link` (symlinks and junctions only: OneDrive
placeholders and other non-"name surrogate" reparse points are listed), `hidden`, `protected`, `system_file`, `skip_list`.
`notes{}` counts files that were listed but are special: `online_only`, `partial`, `project`, `other_ext`. A finished scan
has `explain[]` ({code, title, body}) whenever it found nothing, or nothing that can be sorted.

Moves and copies (`POST /api/execute`, `/api/quarantine`) take `conflicts: {action: "skip"|"keep"|"replace",
skip_identical: bool, per: {"<file id>": action}}` (default: keep both). `POST /api/conflicts` takes the same request (plus
`kind: "quarantine"`) and returns `{total, identical, rows[{fid, name, target, src{size, mtime}, dst{size, mtime, readonly},
identical, within_selection}], more}` without changing anything.

### PIN lock
- No PIN yet: every route except `info` and `pin/*` answers 423 `pin_not_set`. Locked (or idle for longer than
  `pin_idle_min`): 423 `locked`. `/api/info` then returns no paths or folders.
- `POST /api/pin/verify {pin, action, request}` returns an `action_token` for one request: valid 60 s, used once, bound to
  the action and a SHA-256 of the canonical request body. `config.PIN_GUARDED` lists the routes that need one (execute,
  quarantine, trash, undo, data/delete, interrupted/resume|clean, ai/key, ai/reset, apptrash/restore, pin/settings);
  `web.py` consumes it before the route runs. Wrong PINs count towards a lockout stored in `pin.json`.

### Errors
- API errors are always `{"error": "<plain sentence>", "code": "<stable code>", "hint": "<what to do>"}`. Invalid input is
  a 400; bugs (`KeyError`, `TypeError`...) are a 500 with code `internal`, and the full traceback goes to the terminal
  and to `~/.aurasort/logs/server.log` (rotating, 1 MB x 3; the token and home path are masked, file contents are never logged).
- A failed job has `state: "error"`, a plain `errors[0]`, and `failure: {code, message, hint, type, step}`. The UI never
  shows an exception name: it shows the message, "Try again", and "Copy details" (version, OS, step, code, log location;
  the folders you chose only if you tick the box).
- The scan never dies silently: folder and file problems are counted as skipped with a reason; only a failure to write
  the index (locked, disk full, read-only, damaged) stops it, with a message that says which.

### Safety pipeline for any file action
1. The browser sends **ids**, never paths. 2. The server resolves them in the index and applies the same rules for
every action (project/asset files and view-only types only with explicit opt-in). 3. A preflight tells the dialog what
will happen. 4. The job re-checks each file right before acting (still a regular file, same folder, same size and date,
not protected). 5. The result goes to History (Undo for moves), and the index is updated.

## Front end (`docs/`)
Plain scripts sharing one global scope (no bundler): `config.js` (constants, icon helper), `util.js`, `state.js` (state
and URL parameters), `api.js` (real API or the demo backend in `demo.js`), `ui.js` (shared components), `select.js`,
`preview.js`, `datefilter.js`, `actions.js`, `scene.js`, `animations.js`, one file per page in `views/`, and
`search-worker.js` (fuzzy search in a Web Worker using `match.js` and `query.js`). Icons come from one sprite,
`icons.svg`. A strict CSP forbids inline scripts and styles, so styles are applied through `data-css` and CSSOM.

## Tests
- `tests/test_*.py`: unit and API tests (temporary home folders; the real data folder is never touched; a test bin
  folder replaces the Recycle Bin; a mock model server replaces Ollama).
- `tests/e2e/*.mjs`: browser tests driving Edge/Chrome through the DevTools protocol on a fixture home built by
  `tools/make_fixtures.py`, plus a screenshot sweep of every page in both themes.
- `tests/e2e/full.pw.mjs`: the whole app through Playwright (test-only dependency, uses the installed Edge): every page,
  every scan combination, the PIN screens and prompts (wrong PIN, cancel, lock/unlock), move + undo, a name clash with
  Replace + Undo, Recycle Bin, preview, integrity check, Diagnostics, Settings and Legal. It fails on any console error,
  any failed request (4xx/5xx) and any error toast outside the blocks that cause one on purpose.
- `tools/ci_smoke.py` (an installed copy in a clean home: PIN, scan, more than 0 files), `tools/readme_blocks.py` (the
  README's install commands), `tools/check_readme_urls.py` (every README link answers 200): run by CI on Windows, macOS
  and Linux with Python 3.10 to 3.14. Manual checks for clean machines: [MANUAL_TESTS.md](MANUAL_TESTS.md).
- `tools/benchmark.py`, `tools/bench_copy.py`: measured performance, printed as numbers.
