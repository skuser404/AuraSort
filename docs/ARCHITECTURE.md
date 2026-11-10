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
| `server.py` | Routes only: validates input and calls the modules below. |
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
| `platform_utils.py`, `log.py`, `settings.py` | OS specifics (drives, known folders, opening files, permissions), redacting log, validated settings. |

### Data
Everything lives in `~/.aurasort` (user-only permissions): `index.sqlite3`, `history/*.json`, `thumbs/`, `settings.json`,
`aurasort.log`. Document Insights results are **never** written there: they stay in the server's memory.

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
- `tools/benchmark.py`, `tools/bench_copy.py`: measured performance, printed as numbers.
