# Changelog

All notable changes to AuraSort. Dates are YYYY-MM-DD.

## [1.1.1] - 2026-11-11

### Fixed
- Android/Termux without storage access said "Pick at least one drive or folder."; it now says to run
  `termux-setup-storage` and allow access, as a card on the Scan page. Unreadable phone storage is explained the same way.
- "Phone storage (0)" looked like zero files: the "0" was the end of `/storage/emulated/0`. The label now says "phone",
  and the greeting no longer shows the Termux account id.
- A browser opened at the IPv6 loopback address (`[::1]`) was refused (403).
- A failed refresh of the numbers was silent: old or zero numbers stayed on screen. A banner now shows the message and
  the HTTP status, with Reload.
- The installers' self-test reported a false failure on an empty Downloads folder (only `desktop.ini`), and its exit code
  leaked out of `install.ps1`, so CI installs "failed". The installers now end with "Self-test passed: found N files"
  (`server.py --self-test`) and an explicit exit code.
- Saving settings could fail with WinError 5 when another request was reading them; PIN setup on phones could be covered
  by the tab bar or reloaded mid-way; PDFs without font resources gave no text when pypdf was installed. See FIX_LOG.md.
- "Open location" / "Open destination" on Android (and Linux without a desktop) failed; they now show the path with Copy.

### Added
- Phones and small windows: a slide-in menu (menu button, Esc, focus kept inside), a bottom tab bar (Dashboard, Scan,
  Media, Sort, More), a search button, cards instead of tables, bottom-sheet dialogs, 44 px touch targets, safe areas.
  Checked automatically at 360, 412, 768 and 1366 px in both themes (no sideways scrolling); screenshots in docs/screenshots.
- `tests/acceptance/run_acceptance.py` (the 0-files bug, 14 variants), `tests/e2e/responsive.pw.mjs`,
  `tests/e2e/demo_live.pw.mjs` (the public demo, also run after each Pages deploy), `tools/ci_unittest.py` (each failed
  test becomes an annotation on the CI page), a "Demo mode, sample data only" strip.

## [1.1.0] - 2026-11-11

### Fixed
- **Scans that "complete in a second with 0 files" on some PCs.** Every Windows reparse point was skipped as if it were a
  link, without being counted. OneDrive Files On-Demand marks every placeholder file and folder that way, so on a PC
  with Desktop/Documents/Pictures in OneDrive those folders scanned as (nearly) empty. Only symlinks and junctions are
  skipped now (and counted); OneDrive placeholders are listed, online-only ones from metadata only (never downloaded).
  This is the most likely cause of the reported case; it could not be reproduced on the test PC, whose OneDrive files
  are local. `py server.py --doctor` checks for it (and for everything below) on any PC.
- Quick Scan ignored Downloads/Documents/... moved outside the user folder (for example to `D:\`) and scanned an empty
  `~\Downloads` instead. The Windows Known Folder locations are used for the signed-in user; Linux reads XDG user dirs.
- "% of disk" reached 197% or 172%: online-only files counted with their full size against the disk. They are left out of
  disk shares now, and every percentage is clamped to 0-100 ("n/a" when there is nothing to divide by).
- Category badges and lists could disagree (rows without a folder). Such rows are removed after every scan, and a
  consistency check logs an error and shows "refresh data" instead of wrong numbers.
- A home folder inside a protected tree (`/root` on Linux) or named like a tool folder (a user called "venv") was never
  scanned. One stray `requirements.txt`, `.gitignore` or `.blend` file no longer turns a whole scan root into a project.
- Folders deeper than 260 characters on Windows are read with the `\\?\` prefix instead of being skipped.
- Installing on Python 3.14 failed: `Pillow==11.0.0` has no wheels for it (pip tried to compile it). `requirements.txt`
  now pins Pillow 12.3.0 and pypdf 6.9.2, with wheels for Python 3.10 to 3.14 on Windows, macOS and Linux.
- The one-line install commands returned 404: they pointed at `.../v1.0.0/scripts/install.ps1`, a tag that was never
  pushed. The installers are now release assets with stable names under `releases/latest/download/`.
- macOS installs failed with the system `python3` (often 3.9, or a stub that asks for the Command Line Tools) and with
  Homebrew's "externally-managed-environment" pip error. The installer finds Homebrew/python.org Pythons first and
  installs packages into a private virtual environment.
- Saving settings could fail with "Something went wrong" (WinError 5) when another request was reading them at the same
  moment: Windows cannot replace an open file. Reads and writes of settings, the PIN file, AuraSort's trash list and
  History manifests are serialised, a brief outside hold (antivirus) is waited out, and settings are cached in memory.
- The console could crash on non-English names in cp1252/cp437 terminals (it now replaces what it cannot show), and
  subprocess output is decoded as UTF-8.
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
- `py server.py --doctor` and **Settings > Diagnostics** ("Copy diagnostics"): Python and bitness, encoding, admin rights,
  data folder, SQLite (WAL), the index schema, drives, exactly which folders Quick Scan uses (OneDrive, readable), and a
  3-second test scan with every reason something was skipped. No file names; home shown as `~`, user name as `<user>`.
- Every skipped item is counted with its reason (links, hidden, protected, system files, your skip list, no permission
  with the OS error code...), and a scan that finds nothing, or nothing to sort, shows a plain explanation and what to do
  (Controlled Folder Access/antivirus on Windows, Full Disk Access on macOS, OneDrive online-only files, project folders).
- **PIN lock**, enforced by the server: "This computer" + "Set your PIN" on first run, the unlock screen, the PIN before
  every move, copy, delete, undo, replace, data wipe and API-key change (single-use 60-second tokens bound to the exact
  request), idle lock (10 minutes), scrypt-hashed storage, a lockout that survives restarts, Forgot PIN (type RESET).
  An original animated bear covers its eyes while you type, peeks when the PIN is shown, and shakes its head on a mistake.
- **"A file with this name already exists"**: before any move or copy, the clashes are shown side by side (size, date,
  identical content) with Skip / Keep both / Replace per file or for all; "Skip identical files" is the default. Replace
  sets the existing file aside in AuraSort's own trash on the same drive, and Undo restores it.
- AuraSort's own trash (`.AuraSortTrash`) with Restore in Settings, and an optional purge timer (off by default).
- New installers (`install.ps1` for PowerShell 5.1 and 7, `install.sh` for macOS Apple Silicon/Intel and Linux): Python
  check (and winget/Homebrew with your consent), SHA-256 check, `%LOCALAPPDATA%\AuraSort`, Start Menu and Desktop
  shortcuts, optional packages, self-test, safe re-run for updates, `-WhatIf` / `--dry-run`, elevation warning.
- Android (Termux, experimental): `install-termux.sh`, `start-termux.sh`, the phone's storage as Quick Scan folders and
  drives, deletes into AuraSort's trash. The phone-optimized layout comes later.
- Index schema versioning (`PRAGMA user_version`): an older index is migrated, a newer or broken one rebuilt.
- A public website (`site/`, GitHub Pages) with a description, Open Graph and JSON-LD tags, a social preview image,
  `sitemap.xml` and `robots.txt`; the demo moved to `/demo/`.
- CI on Windows, macOS and Linux with Python 3.10, 3.12, 3.13 and 3.14: unit tests, an install + smoke test in a clean
  home (more than 0 files required), the README's install commands, a check that every README link answers 200,
  browser tests (PIN, conflicts, undo), bandit. `docs/MANUAL_TESTS.md` for clean machines.
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
- The README says plainly that no administrator rights are needed (and why "Run as administrator" causes the System32
  errors), lists the install steps in order for every OS, and has a troubleshooting table built from the real errors.
- Windows installs go to `%LOCALAPPDATA%\AuraSort` (was `%LOCALAPPDATA%\Programs\AuraSort`).
- Terms of Use and Privacy Policy 1.1.0 (the PIN and AuraSort's trash); the app asks to accept them again.
- `requirements-optional.txt` is now `requirements.txt` (and `requirements-ai.txt`).
- The log moved from `~/.aurasort/aurasort.log` to `~/.aurasort/logs/server.log`. "Delete my AuraSort data" removes both.

## [1.0.0]
- First public release.
