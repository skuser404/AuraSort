# Fix log: "the scan finds 0 files", Android, install, demo (1.1.1)

Each suspect from the bug report was checked against a test that can fail. "Confirmed" means a test failed before the
fix and passes after it; the evidence column names the test. Reproduction suite: `python tests/acceptance/run_acceptance.py`
(real `server.py`, brand-new home, the UI's own API calls, 14 variants; all pass on Python 3.10, 3.12, 3.13 and 3.14).

| # | Suspect | Verdict | Evidence |
|---|---|---|---|
| 1 | Scan worker swallows an exception, state never final ("done" with zeros or standing forever) | Not the cause now (fixed in 1.1.0: the `KeyError: 'w'` writer-thread death) | Every acceptance variant ends in `done` or `error` within 90 s; `tests/test_scan_errors.py` OriginalBugTest |
| 2a | Host header `[::1]:PORT` refused | **Confirmed, fixed** | acceptance "host [::1]": `403 forbidden` before, `found 189/189` after (`core/web.py` ok_host/ok_origin, `core/config.py` ALLOWED_HOST_NAMES) |
| 2b | A failed API call is swallowed and old/zero numbers stay on screen | **Confirmed, fixed** | `docs/js/app.js` refreshIndex caught every error and only set `S.offline`; now a banner shows the message and the HTTP status. `tests/e2e/responsive.pw.mjs` forces a 500 on `/api/summary` and requires "HTTP 500" in the banner |
| 2c | localhost vs 127.0.0.1, Origin present/absent | Not the cause | acceptance variants "host localhost", "host 127.0.0.1", "origin present", "origin absent": all pass unchanged |
| 3a | Android: no storage access gives "Pick at least one drive or folder." | **Confirmed, fixed** | acceptance "Android: storage folder does not exist": `400 nothing_selected` before, `400 no_storage_access` with the `termux-setup-storage` instructions after (`core/scanner.py` start) |
| 3b | Android: unreadable storage explained as a Windows problem | **Confirmed (order bug), fixed** | acceptance "Android: storage not readable": explain was `windows_blocked`, now `android_storage` with the exact command (`core/scanner.py` _blocked_hint). On a real phone the Windows branch could not run, but the order was wrong |
| 3c | Android: "Phone storage (0)" read as "0 files" | **Confirmed, fixed** | the "0" was the last part of `/storage/emulated/0`, not a count; `driveName` now says "phone" (`tests/test_contract.py` DriveLabelTest). The greeting no longer shows the Termux account id `u0_a1282` |
| 3d | Windows Known Folders, OneDrive-like path with a space | Not the cause now (fixed in 1.1.0) | acceptance "OneDrive-like path with a space": 189/189 |
| 4 | Protection rules exclude everything (project marker in the root, a repo inside Downloads, Android `/data`) | Not the cause now | acceptance: root that is itself a project still lists all 190 files (they are only not offered for sorting); a repo inside Downloads marks only its own subtree (5 files) |
| 5 | Demo data mixed with real data, percentages above 100% | Not the cause now (1.1.0 clamps every share and drops online-only sizes from "% of disk"); the demo is chosen only by the page token, never as a fallback | acceptance checks no category or extension share above 100% and that badges equal list totals in every variant; `tests/e2e/demo_live.pw.mjs` requires that the demo never calls `/api` |
| 6 | Encoding, non-UTF-8 names, long paths, placeholders, PermissionError | Not the cause now (1.1.0) | acceptance fixture has non-ASCII and space names (found); `tests/test_diagnostics.py` OneDrive placeholders, long paths, surrogate names |
| 7 | SQLite threading, WAL on unsupported storage, old schemas | Not the cause | acceptance "corrupt data folder" and "data folder from 1.0.0" pass; the index lives in the data folder (Termux home, not shared storage), and a folder without WAL falls back to SQLite's normal journal with a log warning. An in-memory fallback index was not added: no failing case was found for it |
| 8 | Skip reasons missing when 0 files are found | Not the cause now (1.1.0) | every 0-file acceptance variant carries `explain[]` with a reason and what to do |
| 9 | `--doctor` reports a false FAIL, so the Windows installer "fails" in CI | **Confirmed, fixed** | an empty Downloads that holds only `desktop.ini` gave `overall FAIL`, exit code 1, which leaked out of `install.ps1` as its exit code. Now WARN (exit 0), and the installers run `server.py --self-test` ("Self-test passed: found 6 files") and end with an explicit exit code. Re-ran the CI step verbatim: exit 0 |
| 10 | (found while testing) `POST /api/settings` returned 500 (WinError 5) | **Confirmed, fixed** | the Playwright run caught it; settings/PIN/trash/History files are read and written under one lock and saves retry briefly. `tests/test_diagnostics.py` ConcurrentSaveTest fails without the fix |
| 11 | (found while testing) PDF text missing when pypdf is installed | **Confirmed, fixed** | with pypdf 6.9.2 present (the installers add it), a PDF without font resources gave no text; the basic reader is now tried too. `tests/test_docai.py` passes with and without pypdf |
| 12 | (found while testing) first-run PIN setup reloaded or was covered on phones | **Confirmed, fixed** | a 423 from an early request reloaded the page mid-setup, and the new bottom tab bar covered the Start button. `tests/e2e/responsive.pw.mjs` sets the PIN through the phone UI |

## Not reproduced here
- The GitHub CI unit-test failures on Linux and macOS: their logs need a signed-in GitHub account, and no Linux or macOS
  machine is available on this PC. The CI now turns every failed test into an annotation (`tools/ci_unittest.py`), so
  the next run's page names each failing test and its error.
- A real Android phone and a real Mac: Android is simulated (`AURASORT_FAKE_PLATFORM=android`), see `docs/MANUAL_TESTS.md`.
