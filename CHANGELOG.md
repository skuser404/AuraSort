# Changelog

All notable changes to AuraSort. Dates are YYYY-MM-DD.

## [Unreleased]

### Fixed
- **"The scan stopped: Unexpected error (KeyError)."** The scan's database-writer thread could die without telling
  anyone, and the scan then read a result the thread never set (`result["w"]` in `core/scanner.py`), so all you saw
  was `KeyError`. Two real causes made the writer die:
  - an index written by an earlier version had no `lpath` column (`table dirs has no column named lpath`);
  - a file name with broken Unicode (allowed by Windows, common after old phones or bad unzips) cannot be stored in
    SQLite (`UnicodeEncodeError: surrogates not allowed`).

  Now an older index is upgraded at start-up, such names are skipped and counted, the writer never dies silently, and
  a real database failure stops the scan with a plain message (for example "The file index is being used by another
  AuraSort window or program").
- A damaged index file no longer blocks every scan: it is renamed to `index.sqlite3.broken-<time>` and rebuilt.
- A second copy of AuraSort no longer runs against the same data folder (two servers fought over the index and made
  scans fail with "database is locked"); it opens the running one instead.
- The server could crash outright (access violation in `_wmi.pyd`) when the OS name was read while other requests
  were running; the OS name is now read without WMI. (This came from the error-report work below and never shipped.)
- `C:` without a backslash was read by Windows as "the current folder on C:", not the drive; it now means `C:\`.
- Deep Scan with one missing folder (moved, renamed, drive unplugged) refused the whole scan; now that folder is
  skipped and counted, and only "nothing left to scan" is refused.
- Folders removed during a scan, folders without permission and files that vanish between listing and reading are
  counted as skipped with a reason instead of disappearing silently; one failing folder never stops the scan.
- A failure in the optional steps after a scan (storage snapshot, History entry) no longer marks a finished scan as failed.
- Settings files with wrong value types (hand-edited, or from an older version) no longer crash scans later; long
  paths in settings are kept whole instead of being cut at 1024 characters (a cut path pointed at a different folder).
- History entries from older versions without an id, or with an unknown format, no longer break the History page.
- Requests with wrong types (`ids: "1,2"`, `id: null`, `settings: [...]`, `dest: 5`...) were answered by accident
  (TypeError -> 400) or worked on a relative path; they are now validated with a clear 400.
- Bugs in request handling (`KeyError`, `TypeError`) were reported as "Invalid request." (400) with no traceback; they
  are now a 500 with a log entry and full traceback.
- Requests refused before their body was read (403/401/405/429) could reach the browser as "connection reset"
  instead of the JSON error.
- The scan time estimate showed "Estimating…" forever when it failed, and was requested again on every redraw.
- "Move to…" before the first move: the default `AuraSortFiles` folder did not exist yet, the folder picker fell back
  to "This PC" and *New folder* was disabled. It now opens the nearest existing folder and says the folder will need
  creating.
- After a move, the "Undo move?" and "Cancel the move?" confirmations opened *underneath* the move screen and could not
  be clicked (dialogs are now stacked above it).
- Leaving the Search page within a moment of typing raised a page error (a delayed search wrote into a page that was
  gone).
- Network shares (`\\server\share`) and Linux mounts (`/media/usb`) were all labelled `/` on the Scan page.
- Drive probing errors other than a timeout are now logged with their traceback instead of being swallowed.

### Added
- One request contract (`core/schema.py`, documented in `docs/ARCHITECTURE.md`): every POST route's fields, defaults,
  types, and readable 400 errors. API errors are always `{error, code, hint}`.
- Failed jobs carry `failure: {code, message, hint, type, step}`; the UI shows a short message, "Try again", and
  "Copy details" (app version, OS, step, error code, log file location; your folders only if you tick the box).
- The Scan page disables Start with "Pick at least one drive or folder." when Deep Scan has nothing picked, shows a
  failed scan with Try again / Copy details, and lists skipped items with their reasons.
- Full tracebacks of every failed request, job and thread go to the terminal and to `~/.aurasort/logs/server.log`
  (rotating, 1 MB x 3; the token and your home folder path are masked, file contents are never logged).
- Tests: `tests/test_scan_errors.py` (the original KeyError and every scan/request combination), `tests/test_contract.py`
  (runs the real front-end request builders in Node and checks them against the server schema, and checks responses
  against what the UI reads), and `tests/e2e/full.pw.mjs` (the whole app through Playwright; fails on any console
  error, failed request or error toast).

### Changed
- The log moved from `~/.aurasort/aurasort.log` to `~/.aurasort/logs/server.log`. "Delete my AuraSort data" removes both.

## [1.0.0]
- First public release.
