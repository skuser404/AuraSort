# AuraSort: a free, local file organizer and storage analyzer for Windows, macOS and Linux

**AuraSort** is a free, open-source **file organizer** and **storage analyzer** that runs only on your own computer. It
scans your folders or whole drives, shows where your space goes, helps you **find duplicate files**, works as a
**corrupted file checker**, lets you **sort your Downloads folder** and other folders into tidy sub-folders, and finds
anything fast by name or date. Nothing is uploaded, nothing is permanently deleted, and every move can be undone.

- **Local and private.** A small Python server on `127.0.0.1` with a per-run token. No accounts, no telemetry, no ads,
  no network calls (the optional cloud AI, off by default, is the only exception, and only after you connect it).
- **PIN lock.** AuraSort opens behind your PIN and asks for it again before every move, copy, delete, undo or replace.
- **Never permanently deletes.** "Delete" means the Recycle Bin / Trash, after a confirmation. If a file with the same
  name is already in the destination, you choose: skip, keep both, or replace (the old file is kept and Undo restores it).
- **Protects what matters.** Project folders (`package.json`, `.git`, `.sln`, Premiere/Blender/Ableton projects, websites…)
  and system folders are left alone. Installers, code, disk images, fonts, databases and logs are listed but view-only.

Website: <https://skuser404.github.io/AuraSort/> · Demo with made-up files, in your browser: <https://skuser404.github.io/AuraSort/demo/?demo>

## Contents

- [Install](#install) ([Windows](#windows) · [macOS](#macos) · [Linux](#linux) · [Android (Termux)](#android-termux-experimental))
- [First run](#first-run)
- [Everyday use](#everyday-use)
- [PIN lock](#pin-lock)
- [If a scan finds 0 files](#if-a-scan-finds-0-files)
- [Optional: Document Insights (AI)](#optional-document-insights-ai)
- [Troubleshooting](#troubleshooting)
- [For developers](#for-developers)
- [Legal](#legal)

## Install

**No administrator rights are needed. Do not use "Run as administrator".** Open a normal terminal (not "Run as
administrator"). If your prompt shows `C:\WINDOWS\System32`, close it and open a new one. On every system the order is
the same: install the prerequisites, get AuraSort, install its optional packages, run it. The one-line installers do the
last three steps for you.

**Step 0: open a terminal in your user folder.**
Windows: press Start, type *PowerShell*, press Enter (not "Run as administrator"), then type `cd $HOME`.
macOS: open *Terminal* (Applications > Utilities), then type `cd ~`. Linux: open a terminal, then type `cd ~`.

You need **Python 3.10 or newer** and, for the manual method only, **Git**. Optional packages (Pillow for faster
thumbnails, pypdf for more PDFs) are installed by the installers; AuraSort also runs without them.

### Windows

**Step 1: prerequisites** (Windows 10 or 11; `winget` is built in):

```powershell
winget install --id Python.Python.3.12 --exact --scope user
winget install --id Git.Git --exact
```

Close the terminal and open a new one afterwards, so it sees the new programs. (No winget? Get Python from
[python.org](https://www.python.org/downloads/) and tick *Add python.exe to PATH*.)

**Step 2: the one-line installer** (recommended):

```powershell
irm https://raw.githubusercontent.com/skuser404/AuraSort/main/scripts/install.ps1 | iex
```

If PowerShell refuses scripts, or you are in the old *Command Prompt* (`cmd.exe`), use this form instead (it changes the
policy for this one run only):

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://raw.githubusercontent.com/skuser404/AuraSort/main/scripts/install.ps1 | iex"
```

(Second option, once a release is published: `irm https://github.com/skuser404/AuraSort/releases/latest/download/install.ps1 | iex`.)

It checks for Python (and offers to install it with winget if missing), downloads the latest release, checks its SHA-256
against the release's `SHA256SUMS` (and refuses to install on a mismatch; if no release is published yet it downloads
GitHub's source ZIP of the `main` branch instead and says so, without a checksum, and Git is not needed), installs it to `%LOCALAPPDATA%\AuraSort`,
installs the optional packages for your user, adds **Start Menu and Desktop shortcuts**, runs a self-test (a real scan
of a temporary folder: it must print `Self-test passed: found 6 files`) and offers to start AuraSort. On an old Windows 10 that says *Could not create SSL/TLS secure channel*, run this line first:
`[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor 3072`.
To see every step without changing anything:
`cd $HOME; irm https://raw.githubusercontent.com/skuser404/AuraSort/main/scripts/install.ps1 -OutFile install.ps1; powershell -ExecutionPolicy Bypass -File install.ps1 -WhatIf`

**Step 3: or install manually with Git:**

<!-- ci: run pwsh -->
```powershell
cd $HOME
git clone https://github.com/skuser404/AuraSort.git
cd AuraSort
py -m pip install --user -r requirements.txt
py server.py
```

**Update:** run the one-line installer again (or `git pull` in the AuraSort folder). Your data in
`%USERPROFILE%\.aurasort` is kept. **Uninstall:**
`powershell -ExecutionPolicy Bypass -File "$env:LOCALAPPDATA\AuraSort\scripts\uninstall.ps1"` (add `-Purge` to also
delete AuraSort's own data; files AuraSort moved for you stay where they are). **Start it** from the Start Menu or Desktop
shortcut (*AuraSort*), or with `py server.py` in its folder.

### macOS

**Step 1: prerequisites.** Install [Homebrew](https://brew.sh) if you do not have it, then:

```sh
brew install python git
```

(Without Homebrew, get Python from [python.org](https://www.python.org/downloads/macos/). The `python3` that comes with
macOS is often too old, 3.9, and first asks to install the Command Line Tools.)

**Step 2: the one-line installer** (Apple Silicon and Intel):

```sh
curl -fsSL https://raw.githubusercontent.com/skuser404/AuraSort/main/scripts/install.sh | sh
```

It does the same as on Windows, installs to `~/.local/share/aurasort` with its packages in a private virtual
environment (no system changes), and adds `~/Applications/AuraSort.command`. Add `-s -- --dry-run` after `sh` to preview.

**Step 3: or manually:**

<!-- ci: run sh -->
```sh
cd ~
git clone https://github.com/skuser404/AuraSort.git
cd AuraSort
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python server.py
```

**Gatekeeper.** A `.command` file the installer made on your Mac opens normally. One downloaded from the internet may be
blocked the first time: right-click it > *Open* > *Open*. **Privacy permissions.** macOS asks before any app reads
Desktop, Documents, Downloads or external drives: allow it. For Deep Scans of whole drives, allow *Terminal* (or your
Python) in **System Settings > Privacy & Security > Full Disk Access**, then quit and reopen Terminal. Moving to the
Trash uses Finder (so **Put Back** works); the first time, macOS asks to allow controlling Finder.
**Uninstall:** `sh ~/.local/share/aurasort/scripts/uninstall.sh` (add `--purge` to delete `~/.aurasort`).

### Linux

**Step 1: prerequisites** for your distribution:

| Distribution | Command |
|---|---|
| Ubuntu, Debian, Mint, Pop!_OS | `sudo apt install python3 python3-venv git` |
| Fedora | `sudo dnf install python3 git` |
| Arch, Manjaro | `sudo pacman -S python git` |
| openSUSE | `sudo zypper install python3 git` |

**Step 2: the one-line installer:**

```sh
curl -fsSL https://raw.githubusercontent.com/skuser404/AuraSort/main/scripts/install.sh | sh
```

It adds an `aurasort` command and an applications-menu entry. **Step 3: manual:** the same commands as
[on macOS](#macos). Uninstall: `sh ~/.local/share/aurasort/scripts/uninstall.sh`.

### Android (Termux): experimental

AuraSort can run inside [Termux](https://termux.dev) on an Android phone and open in the phone's browser, with a phone
layout (menu button, bottom tabs). A native Android app is not planned yet.

1. Install **Termux from [F-Droid](https://f-droid.org/packages/com.termux/) or the
   [Termux GitHub releases](https://github.com/termux/termux-app/releases)**. The Google Play version is outdated.
2. Open Termux and run this one command:

   ```sh
   pkg update -y && pkg install -y python git && git clone https://github.com/skuser404/AuraSort.git && cd AuraSort && bash install-termux.sh
   ```

3. Android asks whether Termux may access your files (`termux-setup-storage`). Tap **Allow** (on Android 11 and newer:
   *Allow management of all files*). Without it AuraSort cannot see Downloads, DCIM or Documents.
4. The browser opens `http://localhost:8765/`. If it does not, open Chrome and type that address (or the one Termux
   printed). Later, start it again with `cd ~/AuraSort && bash start-termux.sh`.

Android has no Recycle Bin, so **deleting moves files into a folder named `.AuraSortTrash`** on the same storage;
**Settings > AuraSort trash** lists them and puts them back. Nothing there is erased unless you turn on the purge timer.

## First run

1. **Start AuraSort.** Your browser opens `http://localhost:8765/`. Keep the terminal window open while you use it;
   press `Ctrl+C` there to stop.
2. **Before you start.** Read the short summary and the Terms, tick *I have read and agree*.
3. **This computer.** AuraSort shows the device name and your user name, and says it will ask for your PIN here.
4. **Set your PIN.** Choose 4 or 6 digits and type it twice. Easy PINs (1234, 0000, 1111…) get a warning.
5. **Scan.** **Quick Scan** reads your usual folders (Downloads, Documents, Desktop, Pictures, Videos, Music: the real
   ones, also when Windows keeps them in OneDrive or on another drive; *Exactly which folders* lists them). **Deep Scan**
   reads the drives you tick plus folders you add. Only names, sizes and dates are read; nothing is changed.

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
3. **If files with the same names are already there**, AuraSort says so ("12 files already exist in this folder") and
   shows both sides: name, size, date, and *identical content* when every byte matches. For each file or for all of them
   choose **Skip**, **Keep both** (`name (1).ext`) or **Replace**. *Skip identical files* is ticked by default. Replace
   never overwrites: the existing file is moved into AuraSort's trash on the same drive first, and **Undo** puts it back.
4. **Recycle Bin**: files go to the Recycle Bin/Trash after a confirmation; 100 or more need the number typed.
5. Each of these asks for your **PIN**. **Undo** any move from **History** (also with your PIN).

Copies between drives are written to a temporary `.aurasort-part` file, checked byte for byte (BLAKE2b; *Fast check* is
offered for huge jobs), and only then renamed. A move across drives deletes the original **only after** that check. If
AuraSort is closed mid-job, History offers **Resume** or **Clean up**. OneDrive/iCloud files that are online-only are
listed (with their full size, marked as taking no space on this PC) but never downloaded, so they cannot be copied
between drives until you make them available offline.

### Corrupted files, duplicates, cleanup

- **Corrupted:** a read-only check (*Quick*: structure, *Deep*: every byte). Each result says what is wrong, the likely
  cause and what to do. Export the list as CSV, or move problem files to a Quarantine folder (undoable).
- **Duplicates:** identical files found by size, then the first and last 64 KB, then every byte. *Select all but the newest*.
- **Cleanup:** unfinished downloads, temporary files, empty files and old installers, as a list for you to review.
  Nothing is selected or removed automatically.

## PIN lock

- AuraSort asks for your PIN **when it opens** and **before every move, copy, delete, undo, replace, "Delete my
  AuraSort data" and API-key change**. It locks itself after **10 minutes** without activity (Settings > PIN lock:
  1 minute to 1 hour). *Do not ask again for N minutes* exists, and is **off** by default.
- The server enforces this, not only the page. The PIN is stored only as a salted, slow hash (scrypt) in your data
  folder, never as the PIN itself, never in a URL or browser storage. After 5 wrong tries AuraSort waits 30 seconds,
  then 1, 5 and 15 minutes, also across restarts.
- **Forgot your PIN?** On the unlock screen choose *Forgot PIN?* and type RESET. That wipes AuraSort's own settings,
  History (including Undo) and file index, **never your files**, and setup starts again.
- **Be aware:** the PIN protects against casual misuse of AuraSort on a computer left unlocked. It does not stop someone
  who is already signed in to your Windows/macOS account from using Explorer, Finder or other tools. Lock your screen
  when you leave, use your OS password, and turn on BitLocker (Windows) or FileVault (macOS).

## If a scan finds 0 files

AuraSort never ends a scan with silent zeros. When a scan finds nothing, or some folders refused access, the Scan page
shows a card with the exact counts (files found, folders scanned, and folders skipped for each reason) and three
choices:

- **Choose folders to scan**: pick your own folders (Downloads, Documents, Desktop, Pictures, Videos, Music). These
  never need administrator rights.
- **Why was access denied?**: the usual causes for your system (Windows Controlled Folder Access, antivirus, OneDrive
  online-only files; macOS Full Disk Access; Android `termux-setup-storage`) and how to fix each one.
- **Restart with administrator permission** (Windows only, optional): only for other users' folders or whole system
  drives. Windows asks you first. If you decline, nothing changes. Windows system folders are still skipped. To check a computer completely, run the **doctor** in the
AuraSort folder (or use **Settings > Diagnostics** and *Copy diagnostics*):

```sh
py server.py --doctor
```

(`python3 server.py --doctor` on macOS/Linux.) It checks Python, the text encoding, administrator rights, the data
folder, SQLite, the file index, the drives, exactly which folders Quick Scan uses (and whether they are in OneDrive and
readable), and makes a 3-second test scan that counts files and every reason something was skipped. It prints no file
names; your home folder is shown as `~` and your user name as `<user>`. Add `--folder "C:\path\to\folder"` to test one
folder. **Send that output** when you ask for help.

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
| `irm ... install.ps1` says **404 Not Found** | Use exactly `https://raw.githubusercontent.com/skuser404/AuraSort/main/scripts/install.ps1` (the repository name is case-sensitive: `AuraSort`). The `releases/latest/download/...` link only works once a release is published, and older links with a version in the path (`.../v1.0.0/scripts/install.ps1`) pointed at a tag that was never published. |
| The installer window **closes by itself**, or says *You cannot call a method on a null-valued expression* / *Unexpected token* | Fixed in 1.1.2: older installers did not work through `irm ... \| iex` on Windows PowerShell 5.1. Run the command above again (it downloads the current installer). |
| `git clone` says **Permission denied** / `Could not create work tree` | The terminal is in `C:\WINDOWS\System32` (it was opened with *Run as administrator*). Close it, open PowerShell normally, run `cd $HOME`, then clone again. |
| `cd aurasort` says **Cannot find path**, or `py server.py` says **can't open file 'server.py'** | You are in a different folder. Run `cd $HOME\AuraSort` (Windows) or `cd ~/AuraSort`, then `py server.py`. Check with `dir server.py` (or `ls server.py`). |
| `'py' is not recognized` | Python is not installed, or the terminal was open while it was installed: run `winget install --id Python.Python.3.12 --exact --scope user`, then open a **new** terminal. |
| `python` opens the **Microsoft Store** / says *Python was not found* | That is Windows' Store shortcut, not Python. Install Python as above, or turn the shortcut off in *Settings > Apps > Advanced app settings > App execution aliases*. |
| `running scripts is disabled on this system` | Use `powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://raw.githubusercontent.com/skuser404/AuraSort/main/scripts/install.ps1 \| iex"`, or for a downloaded file `powershell -ExecutionPolicy Bypass -File install.ps1` (both affect only that run). |
| SmartScreen or antivirus warns about `start.bat` or the installer | They only run `py server.py`. Choose *More info > Run anyway*, or start AuraSort from a terminal. |
| `Address already in use` / page does not open | Another program uses port 8765. AuraSort tries the next ports and prints the address it uses; or run `py server.py --port 9000` and open `http://localhost:9000/`. |
| **A scan finds 0 files**, or numbers look wrong | Read the card on the Scan page, then run `py server.py --doctor` in `%LOCALAPPDATA%\AuraSort` (or *Settings > Diagnostics > Copy report*) and send its output (see [If a scan finds 0 files](#if-a-scan-finds-0-files)). |
| Windows, Python 3.12 or newer: Deep Scan estimates thousands of files, then says **0 files, 1 folders skipped** | Fixed in 1.1.2: some drives' 64-bit volume numbers did not fit in the index, so every folder was skipped. Update with the installer command above. |
| Windows: folders show "no permission" | Windows Security > Virus & threat protection > *Manage ransomware protection* (Controlled Folder Access), or your antivirus, blocks Python: allow `python.exe` / `py.exe`. Administrator rights are **not** the fix. |
| macOS: folders show "no permission" | Allow Terminal (or your Python) in *System Settings > Privacy & Security > Files and Folders* or *Full Disk Access*, then quit and reopen Terminal. |
| macOS: `python3` asks to install *command line developer tools*, or says it is 3.9 | Install a current Python: `brew install python` (or python.org), then use the installer above. |
| Linux/macOS: `pip` says **externally-managed-environment** | Use a virtual environment as in the manual steps (`python3 -m venv .venv`), or the installer, which does that for you. |
| Python 3.14: `pip install` tries to build Pillow and fails | Fixed in 1.1.0: `requirements.txt` now pins Pillow 12.3.0, which has ready-made wheels for Python 3.10 to 3.14. Pull or reinstall. |
| Android: "Your phone's folders cannot be seen yet" / 0 files | Termux has no storage access. Run `termux-setup-storage`, tap **Allow** (Android 11+: *Allow management of all files*), then press Scan again. |
| Android: Move or Copy fails with **Operation not permitted** | Fixed in 1.1.2: phone storage refuses hard links and copying file dates, so every copy failed. Update: `cd ~/AuraSort && git pull`. |
| The installer says "Self-test did not pass" | It saved a report (no file names) and printed its location: send that file, or the output of `py server.py --doctor`. |
| Forgot the PIN | *Forgot PIN?* on the unlock screen, type RESET. AuraSort's own data is wiped (never your files) and you set a new PIN. |
| "Too many wrong PINs" | Wait for the countdown (30 s, then 1, 5, 15 minutes). Restarting AuraSort does not reset it. |
| "This page belongs to an older server session" | You restarted AuraSort. Reload the page. |
| "AuraSort is already running" | Only one copy can use your data folder at a time; the running one opens instead. Close its terminal window to stop it. |
| Ollama is not detected | Make sure it is running (`ollama list` in a terminal works), then press *Test connection*. LM Studio: start its local server. |
| A copy says "in use by another program" | Close the program using the file and try again; the original was not touched. |
| A scan or action stopped with an error | Press *Copy details* on the message and paste it into a GitHub issue. The full log is `~/.aurasort/logs/server.log` (on Windows `%USERPROFILE%\.aurasort\logs\server.log`). |

When asking for help on GitHub, **do not paste personal file names, full paths with your user name, API keys or
screenshots of private documents.** The `--doctor` output is made to be safe to paste.

## For developers

```sh
python -m unittest discover -s tests -t .          # unit + contract tests (standard library only; Node.js for the contract tests)
python -m bandit -q -r core server.py tools        # security linter (pip install bandit)
python server.py --doctor --json                   # the same checks as Settings > Diagnostics, as JSON
python tools/make_fixtures.py ../fixture           # a fake home folder for manual and end-to-end tests
node tests/e2e/app.e2e.mjs --home ../fixture/home --out out    # browser tests (Node 22+, Edge or Chrome)
npm install playwright && node tests/e2e/full.pw.mjs --home ../fixture/home   # whole app via Playwright (test-only dependency)
python tools/build_release.py dist                 # the release assets: aurasort.zip, installers, SHA256SUMS
python tools/ci_smoke.py --app <installed folder>  # start an install in a clean home, scan, require > 0 files
python tools/check_readme_urls.py                  # every README link must answer 200
```

- Start the server with `AURASORT_STRICT_SCHEMA=1` and `AURASORT_TEST_TRASH_DIR=<folder>` for browser tests: unknown
  request fields are refused, and "Recycle Bin" means that folder. The request contract is in
  [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#request-contract-front-end---server). Logs: `~/.aurasort/logs/server.log`.
- Manual test plan for clean machines: [docs/MANUAL_TESTS.md](docs/MANUAL_TESTS.md). Security: [SECURITY.md](SECURITY.md)
  and [docs/THREAT_MODEL.md](docs/THREAT_MODEL.md). Contributing: [CONTRIBUTING.md](CONTRIBUTING.md).
- Front end: plain HTML/CSS/JS in `docs/` (no build step), served by the app and as the demo on GitHub Pages
  (`?demo` uses made-up files only).
- Releases: push a tag `vX.Y.Z` matching `APP_VERSION`; the Release workflow tests, builds and publishes the assets that
  the one-line installers download.

## Legal

- [Terms of Use](TERMS_OF_USE.md) · [Rules of use](ACCEPTABLE_USE.md) · [Privacy Policy](PRIVACY_POLICY.md) ·
  [AI Data Notice](AI_DATA_NOTICE.md) · [Third-party notices](THIRD_PARTY_NOTICES.md) · [Code of Conduct](CODE_OF_CONDUCT.md)
- Code licence: [MIT](LICENSE). The name "AuraSort" and its logo are not covered by the MIT licence.
- Contact: [GitHub Issues](https://github.com/skuser404/AuraSort/issues). Security problems: please report them privately
  through [GitHub Security Advisories](https://github.com/skuser404/AuraSort/security/advisories/new).
