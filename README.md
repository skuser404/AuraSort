# AuraSort

**Make your files easier.** Scan your whole PC, find anything fast, and sort files safely.

AuraSort is a file organiser that runs **only on your own computer**. It lists every file with its size and folder, finds
large, duplicate, damaged and junk files, and moves, copies or sends files to the Recycle Bin only after you have seen
exactly what will happen.

- **Local and private.** The app is a small Python server on `127.0.0.1` with a per-run token. No accounts, no telemetry,
  no ads, no network calls (the optional cloud AI, off by default, is the only exception, and only after you connect it).
- **Never permanently deletes.** "Delete" means the Recycle Bin / Trash, after a confirmation. Moves never overwrite
  (a clash becomes `name (1).ext`), are logged in History, and can be undone.
- **Protects what matters.** Project folders (`package.json`, `.git`, `.sln`, Premiere/Blender/Ableton projects, websites…)
  and system folders are left alone. Installers, code, disk images, fonts, databases and logs are listed but view-only.

> Screenshots: `docs/screenshots/` (placeholder: add `dashboard-dark.png`, `media-light.png`, `move.png`, `insights.png` here).

## Contents

- [Requirements](#requirements)
- [Install on Windows](#install-on-windows)
- [Install on macOS or Linux](#install-on-macos-or-linux)
- [First run](#first-run)
- [Everyday use](#everyday-use)
- [Optional: Document Insights (AI)](#optional-document-insights-ai)
- [Troubleshooting](#troubleshooting)
- [For developers](#for-developers)
- [Android (Termux): planned](#android-termux-planned)
- [Legal](#legal)

## Requirements

| | |
|---|---|
| Operating system | Windows 10 or 11, macOS 12 or newer (Intel and Apple Silicon), or a recent Linux desktop |
| Python | **3.10 or newer** from [python.org](https://www.python.org/downloads/) (Windows: tick *Add python.exe to PATH*) |
| Browser | Any current Edge, Chrome, Firefox or Safari |
| Optional | `Pillow` (faster thumbnails), `pypdf` (reads more PDFs for Document Insights). Install with `py -m pip install -r requirements-optional.txt` |

No other software is needed. The app itself has no third-party dependencies.

## Install on Windows

### One line (recommended)

Open **PowerShell** (not as Administrator) and run:

```powershell
irm https://raw.githubusercontent.com/skuser404/aurasort/v1.0.0/scripts/install.ps1 | iex
```

It downloads the **tagged release** `v1.0.0`, checks the ZIP's **SHA-256** against the release's `SHA256SUMS` (and refuses
to install on a mismatch), unpacks it to `%LOCALAPPDATA%\Programs\AuraSort` and adds a Start Menu shortcut. No admin rights.

Want to look first? Download `install.ps1` from the release page and run `.\install.ps1 -WhatIf` to see every step
without changing anything. Add `-DesktopShortcut` for a Desktop shortcut too.

### Manual (git)

```powershell
git clone https://github.com/skuser404/aurasort.git
cd aurasort
py server.py
```

### ZIP download

1. On the [Releases page](https://github.com/skuser404/aurasort/releases), download `aurasort-v1.0.0.zip` and `SHA256SUMS`.
2. Check it: `Get-FileHash .\aurasort-v1.0.0.zip -Algorithm SHA256` must match the line in `SHA256SUMS`.
3. Right-click the ZIP > **Extract All**. Note the **nested folder**: open the inner `aurasort` folder (the one that
   contains `server.py`).
4. Double-click `start.bat`, or run `py server.py` in that folder.

### Update, uninstall

- **Update:** run the one-line install again with the new version number. Your data (`%USERPROFILE%\.aurasort`) is kept.
- **Uninstall:** `powershell -ExecutionPolicy Bypass -File "$env:LOCALAPPDATA\Programs\AuraSort\scripts\uninstall.ps1"`.
  Add `-Purge` to also delete AuraSort's own data (index, History/Undo logs, settings, thumbnails, a saved API key).
  Files AuraSort moved for you stay where they are. Use `-WhatIf` to preview, `-Yes` to skip the confirmation.

## Install on macOS or Linux

### One line

```sh
curl -fsSL https://raw.githubusercontent.com/skuser404/aurasort/v1.0.0/scripts/install.sh | sh
```

Same checks as on Windows (tagged release, SHA-256 verified with `shasum`/`sha256sum`), installed to
`~/.local/share/aurasort`. On Linux it adds an `aurasort` command and an applications-menu entry. Use `--dry-run` to
preview.

### Manual

```sh
git clone https://github.com/skuser404/aurasort.git
cd aurasort
python3 server.py
```

### macOS notes

- **Start it** by double-clicking `start.command`. The first time, macOS Gatekeeper may say it cannot be opened because
  it is from an unidentified developer: **right-click > Open > Open** once. (The script is not notarised.)
- **Privacy permissions.** macOS asks before any app reads Desktop, Documents, Downloads or external drives. Allow
  *Terminal* (or your Python) in **System Settings > Privacy & Security > Files and Folders** (or *Full Disk Access* for
  Deep Scans of whole drives). If a folder shows "no access", that permission is missing.
- Moving to the Trash uses Finder, which keeps **Put Back**. The first time, macOS asks to allow controlling Finder.

**Uninstall:** `sh ~/.local/share/aurasort/scripts/uninstall.sh` (add `--purge` to delete `~/.aurasort`).

## First run

1. **Start AuraSort.** Your browser opens `http://localhost:8765/`. The terminal window must stay open while you use it;
   press `Ctrl+C` there to stop.
2. **Before you start.** Read the short summary and the Terms, tick *I have read and agree*.
3. **Scan.** Choose **Quick Scan** (your usual folders, usually seconds) or **Deep Scan** (whole drives you tick, plus
   folders you add). The *Ready to start* checklist shows what will be read (names, sizes and dates only), the
   estimated time (always an estimate), and that nothing is changed during a scan. Only scan files you own or are
   authorised to manage.
4. **Explore.** The dashboard shows your drive, space by type, the biggest folders and files, and rule-based insights.

> Screenshot placeholder: `docs/screenshots/first-run.png`

## Everyday use

### Find files

- **Media Explorer** lists every file, 100 per page, with its size (hover for exact bytes), date and full folder. Filter
  by type, format (`.jpg`, `.pdf`…), folder and date. Every filter is in the URL, so you can bookmark a view.
- **Search** (`Ctrl+K`) matches names partially, ignores case and forgives small typos. Type `.png` to match an extension.
- **Date filter:** today, yesterday, last 7/30 days, a day, a range, a month or a year, on the *Modified*, *Created* or
  *Last opened* date. **Timeline** shows a calendar of your files; select a day to list it.
- **Preview** any file (pictures with zoom, video and audio, PDF, text). *Open file* never runs programs or scripts.

### Select, move, copy, delete

1. Tick files (Shift-click for a range, or *Select all N matching*). A bar at the bottom shows the count and size.
2. **Move to…** or **Copy to…**: choose a folder (or create one with *New folder*), then review the confirmation: how
   many files, where they go, and anything that will be left alone (project files, view-only types).
3. **Recycle Bin**: files go to the Recycle Bin/Trash after a confirmation; 100 or more need the number typed.
4. **Undo** any move from **History**.

Copies between drives are written to a temporary `.aurasort-part` file, checked byte for byte (BLAKE2b; *Fast check* is
offered for huge jobs), and only then renamed. A move across drives deletes the original **only after** that check. If
AuraSort is closed mid-job, History offers **Resume** or **Clean up**.

### Corrupted files, duplicates, cleanup

- **Corrupted:** a read-only check (*Quick*: structure, *Deep*: every byte). Each result says what is wrong, the likely
  cause and what to do. Export the list as CSV, or move problem files to a Quarantine folder (undoable).
- **Duplicates:** identical files found by size, then the first and last 64 KB, then every byte. *Select all but the newest*.
- **Cleanup:** unfinished downloads, temporary files, empty files and old installers, as a list for you to review.
  Nothing is selected or removed automatically.

## Optional: Document Insights (AI)

Document Insights reads the text of documents you choose (PDF, Word, PowerPoint, Excel, text), says what each one is,
and flags ones that look confidential. It is **off by default** and asks for your consent first.

### Set up a local engine (recommended: nothing leaves your computer)

1. Install **[Ollama](https://ollama.com/download)** or **[LM Studio](https://lmstudio.ai)** (free). AuraSort never
   installs anything by itself.
2. Start it (Ollama runs in the background; in LM Studio, start the *local server*). AuraSort only ever talks to it on
   `127.0.0.1`.
3. Pick a model by memory. AuraSort shows your RAM and a suggestion:

   | Memory | Model size | Examples |
   |---|---|---|
   | about 4 GB | tiny (1B class) | `llama3.2:1b`, `qwen2.5:1.5b` |
   | about 8 GB | small (3B class) | `llama3.2:3b`, `qwen2.5:3b` |
   | 16 GB or more | medium (7-8B class) | `qwen2.5:7b`, `llama3.1:8b` |

   With Ollama, select a model name in AuraSort to download it (you confirm first; progress is shown).
4. In **Insights > Documents**, choose all documents or your selection and press **Start**. It is slow on a CPU; the
   progress shows an estimate ("about 38 min left").

### What is private

- **Confidential flags come from fixed rules first** (card numbers with a Luhn check, IBAN, Aadhaar with its check digit,
  PAN, GSTIN, bank statements, salary slips, private keys, passwords…). The model can raise a flag, never remove one.
  Only the kind of match and a masked form (`••••1111`) are shown, never the value.
- **The model only suggests.** It cannot open, move, delete or run anything. Text inside a document is treated as data,
  so instructions hidden in a document are ignored.
- **Results stay in memory** and clear themselves after 60 minutes (choose 30, 60 or 90; the countdown is visible), when
  you quit, or when a file is moved or deleted. No document text is written to disk, logs or History.

### Optional cloud API

You can connect **DeepSeek** or any OpenAI-compatible API with an **API key** (not your account password). The key stays
in memory for the session, or in your system keychain if you choose. Before every batch you see what will be sent;
numbers and IDs are masked, and files flagged Confidential are held back unless you say otherwise. **Data you send is
handled under that provider's privacy policy** (DeepSeek's policy states data may be stored on servers in China; check
the current policy), and AuraSort cannot delete it from their servers. Use the local engine for banking, job, legal and
medical documents. See [AI_DATA_NOTICE.md](AI_DATA_NOTICE.md).

## Troubleshooting

| Problem | Fix |
|---|---|
| `'py' is not recognized` / `python` opens the Microsoft Store | Install Python from python.org and tick *Add python.exe to PATH*, then open a new terminal. |
| `Address already in use` / page does not open | Another program uses port 8765. Run `py server.py --port 9000` and open `http://localhost:9000/`. |
| SmartScreen or antivirus warns about `start.bat` | It only runs `py server.py`. Choose *More info > Run anyway*, or start it from a terminal. |
| `running scripts is disabled on this system` | Run the installer with `powershell -ExecutionPolicy Bypass -File install.ps1` (this affects only that run). |
| macOS: folders show "no access" | Allow Terminal in *System Settings > Privacy & Security > Files and Folders* (or *Full Disk Access*). |
| "This page belongs to an older server session" | You restarted AuraSort. Reload the page. |
| Ollama is not detected | Make sure it is running (`ollama list` in a terminal works), then press *Test connection*. LM Studio: start its local server. |
| A copy says "in use by another program" | Close the program using the file and try again; the original was not touched. |
| A scan or action stopped with an error | Press *Copy details* on the message and paste it into a GitHub issue. It contains the app version, OS, step and error code, and no file names unless you tick the box. The full log is `~/.aurasort/logs/server.log` (on Windows `%USERPROFILE%\.aurasort\logs\server.log`). |
| "AuraSort is already running" | Only one copy can use your data folder at a time; the running one opens instead. Close its terminal window to stop it. |
| "N skipped" after a scan | Folders you have no permission for, files removed during the scan, or names the index cannot store are counted, not fatal. The scan page lists the reasons. |

When asking for help on GitHub, **do not paste personal file names, full paths with your user name, API keys or
screenshots of private documents.**

## For developers

```sh
python -m unittest discover -s tests -t .          # unit tests (standard library only)
python -m bandit -q -r core server.py tools        # security linter (pip install bandit)
python tools/make_fixtures.py ../fixture           # a fake home folder for manual and end-to-end tests
node tests/e2e/app.e2e.mjs --home ../fixture/home --out out    # browser tests (Node 22+, Edge or Chrome)
npm install playwright && node tests/e2e/full.pw.mjs --home ../fixture/home   # whole app via Playwright (test-only dependency)
python tools/benchmark.py                          # scan/search benchmark on generated files
python tools/bench_copy.py <folder>                # copy engine vs shutil.copy2 (prints measured numbers)
```

- Start the server with `AURASORT_STRICT_SCHEMA=1` for browser tests: a request field the server does not know is then
  refused (400), so a renamed field fails a test instead of being ignored. The request contract is in
  [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#request-contract-front-end---server). Logs: `~/.aurasort/logs/server.log`.
- Architecture: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Security: [SECURITY.md](SECURITY.md) and
  [docs/THREAT_MODEL.md](docs/THREAT_MODEL.md). Contributing: [CONTRIBUTING.md](CONTRIBUTING.md).
- Front end: plain HTML/CSS/JS in `docs/` (no build step), served by the app and as a demo on GitHub Pages
  (`?demo` uses fake data only).
- Measured performance on the author's test PC (SSD, 8 GB RAM): scanning about 200,000 files in under a minute; search
  under 100 ms. Verified copies are slower than a plain copy by design (each copy is read back and checked):
  `tools/bench_copy.py` prints the real numbers for your machine.

## Android (Termux): planned

Running AuraSort inside Termux on Android is being considered. It is not available yet and there is no date.

## Legal

- [Terms of Use](TERMS_OF_USE.md) · [Rules of use](ACCEPTABLE_USE.md) · [Privacy Policy](PRIVACY_POLICY.md) ·
  [AI Data Notice](AI_DATA_NOTICE.md) · [Third-party notices](THIRD_PARTY_NOTICES.md) · [Code of Conduct](CODE_OF_CONDUCT.md)
- Code licence: [MIT](LICENSE). The name "AuraSort" and its logo are not covered by the MIT licence.
- Contact: [GitHub Issues](https://github.com/skuser404/aurasort/issues). Security problems: please report them privately
  through [GitHub Security Advisories](https://github.com/skuser404/aurasort/security/advisories/new).
