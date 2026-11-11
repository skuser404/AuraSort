# Decisions

Short records of choices that are not obvious from the code. Newest first.

## 2026-11-12: Windows installs run with administrator permission

**Decision (owner).** The Windows installer asks for administrator permission once. Windows shows its own prompt;
when the installer is started from a normal PowerShell, it restarts itself elevated. AuraSort is installed for the
signed-in user in `%LOCALAPPDATA%\AuraSort`, and its shortcuts start it the same way.

**Why.** Many PCs refuse AuraSort access to some folders otherwise, and installing Python is simpler with it.

**Limits and safeguards.**
- Administrator permission does not lift Controlled Folder Access or antivirus blocks; the app says so.
- Elevated programs do not see mapped network drives (`Z:`); scan them by their `\\server\share` path, or install in
  standard mode.
- The server still listens on 127.0.0.1 only and needs its per-run token and the PIN. Windows system folders are never
  scanned or touched.
- The browser is opened through Explorer, so the browser itself does not run elevated.
- When a different administrator account approves the prompt, the installer passes the signed-in user's profile, app
  data and Desktop folders through, so the app, its data and its shortcuts belong to that user. Python is then
  installed for all users.
- If you decline the prompt, nothing fails: the install continues in standard mode. The `-NoElevate` switch chooses
  that up front.

## 2026-11-12: The stack stays the same

The app remains a Python standard-library server with vanilla JavaScript and CSS: no Electron, Flutter, React or build
step. The UI problems reported were visual and were fixed in CSS and copy (see `docs/DESIGN.md`). A framework would
not have removed any failure.

## 2026-11-12: Inter is self-hosted (the only new asset)

The system fonts differ between Windows 10 (Segoe UI), Windows 11 (Segoe UI Variable), macOS and Android, so
spacing and line breaks differed too. Inter, variable weight, Latin and Latin Extended only (133 KB in total, SIL Open
Font License, `docs/fonts/OFL.txt`), gives one look everywhere. It is served from `docs/fonts`, so there is no network
request and the CSP stays `font-src 'self'`.

No Python or JavaScript dependency was added. Playwright is used for tests only and is never shipped.

## 2026-11-12: Python from python.org is pinned by SHA-256

Without winget (older Windows 10, LTSC, Windows Server), the installer downloads the official Python 3.12.10 installer
and refuses to run it unless its SHA-256 matches the value pinned in `scripts/install.ps1`. python.org publishes
Sigstore signatures, not hashes; the pinned values come from downloads that passed `sigstore verify identity
--cert-identity thomas@python.org --cert-oidc-issuer https://accounts.google.com`.

## 2026-11-12: The first start scans by itself

With no index yet, the page runs a Quick Scan of the usual folders without a click and then shows "Suggested
organization: N files into M folders". **Apply** opens the Sort preview and its own confirmation (with the PIN). Nothing
is moved without that preview, and Undo is available. Browser test servers set `AURASORT_NO_AUTO_SCAN=1` because they
run their own scans; `tests/e2e/firstrun.pw.mjs` covers the automatic one.
