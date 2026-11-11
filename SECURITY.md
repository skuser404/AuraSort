# Security policy

AuraSort reads, moves, copies and (through the Recycle Bin / Trash) removes files on your computer, and can optionally
send document text to an AI service you connect. Security reports are taken seriously.

## Reporting a vulnerability

Please report vulnerabilities **privately** through GitHub Security Advisories: on
<https://github.com/skuser404/AuraSort/security/advisories/new> choose *Report a vulnerability*.
Please do not open a public issue for security problems, and do not include personal files, full paths with your user
name, API keys or screenshots of private documents. Include:

- what an attacker can do (for example "a web page can move files", "a crafted file name runs script in the UI",
  "a document makes the AI feature act on files");
- steps to reproduce, with the AuraSort version, operating system and Python version;
- whether it needs another program already running as your user.

You will get a reply within 7 days. Fixes are released as a new tagged version with a `SHA256SUMS` file, and credited in
the release notes unless you prefer otherwise.

## PIN lock: what it does and what it does not

- **What it does.** AuraSort opens behind a 4- or 6-digit PIN, and asks for it again before every move, copy, delete
  (Recycle Bin), undo, replace, "Delete my AuraSort data" and API-key change. The server enforces this, not only the
  page: every API route answers `423 Locked` while locked, and each of those actions needs a single-use *action token*
  from `POST /api/pin/verify`, valid for 60 seconds and bound to that exact request (a token for "move these 3 files"
  cannot delete them, or move a fourth). The app also locks after 10 minutes without activity (configurable).
- **How the PIN is stored.** Never the PIN itself: a random 16-byte salt and `scrypt` (N=2^15, r=8, p=1; PBKDF2-HMAC-SHA256
  with 600,000 iterations where scrypt is unavailable) in `~/.aurasort/pin.json`, readable by your user only, compared in
  constant time. The PIN is never logged, never put in a URL and never kept in browser storage.
- **Wrong PINs.** After 5 wrong tries AuraSort waits 30 seconds, then 1, 5 and 15 minutes after each further miss. The
  counter is stored with the hash, so restarting AuraSort does not reset it.
- **Forgot PIN.** It cannot be recovered. *Forgot PIN* (type RESET) wipes AuraSort's own settings, History and index
  (never your files) and runs setup again.
- **What it does not do.** It protects AuraSort against casual misuse on a computer left unlocked. It does **not** stop
  someone who is already signed in to your Windows/macOS/Linux account from using Explorer, Finder, a terminal or other
  programs on the same files, and a 4-digit PIN is not a password. Lock your screen when you leave, use a strong OS
  password, and turn on BitLocker (Windows) or FileVault (macOS) for disk encryption.

## Supported versions

Only the latest release receives security fixes.

## In scope

- Anything reachable from a web page or another device (the server must only answer `127.0.0.1` with a valid token).
- A way around the PIN: any move, copy, delete, undo, replace, data wipe or API-key change that works without a valid
  action token, a token that can be reused or used for a different request, or the PIN appearing in a file, log or URL.
- Anything that could permanently delete, overwrite or corrupt a file, or touch protected, system or project folders
  without the documented confirmations. This includes the copy engine (partial files, verification, crash recovery).
- Script injection through file names, paths or file contents shown in the UI.
- Path traversal, symlink/junction escapes and time-of-check/time-of-use races around move, copy, open and Recycle Bin.
- **Document Insights:** prompt injection that leads to any action, document text or detected values reaching disk,
  logs or a cloud service without the documented consent and masking, API keys leaking into files, URLs or logs, and
  local mode contacting anything other than `127.0.0.1`.

## Out of scope

- Programs already running as your user (they can read your files directly).
- What a cloud AI provider does with data you chose to send it (see [AI_DATA_NOTICE.md](AI_DATA_NOTICE.md)).

See [docs/THREAT_MODEL.md](docs/THREAT_MODEL.md) for the design assumptions and known limits.
