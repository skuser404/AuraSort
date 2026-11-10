# Security policy

AuraSort reads, moves, copies and (through the Recycle Bin / Trash) removes files on your computer, and can optionally
send document text to an AI service you connect. Security reports are taken seriously.

## Reporting a vulnerability

Please report vulnerabilities **privately** through GitHub Security Advisories: on
<https://github.com/skuser404/aurasort/security/advisories/new> choose *Report a vulnerability*.
Please do not open a public issue for security problems, and do not include personal files, full paths with your user
name, API keys or screenshots of private documents. Include:

- what an attacker can do (for example "a web page can move files", "a crafted file name runs script in the UI",
  "a document makes the AI feature act on files");
- steps to reproduce, with the AuraSort version, operating system and Python version;
- whether it needs another program already running as your user.

You will get a reply within 7 days. Fixes are released as a new tagged version with a `SHA256SUMS` file, and credited in
the release notes unless you prefer otherwise.

## Supported versions

Only the latest release receives security fixes.

## In scope

- Anything reachable from a web page or another device (the server must only answer `127.0.0.1` with a valid token).
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
