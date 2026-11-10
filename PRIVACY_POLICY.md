# Privacy Policy

Version: 1.0.0
Effective date: 10 November 2026
Owner: Sunil Kumar (GitHub: skuser404)

> **Note:** Template provided for convenience, not legal advice. Have a qualified lawyer review before relying on it.

> **The short version**
> - AuraSort runs on your computer. The project collects nothing.
> - No accounts, no analytics, no telemetry, no ads, no cookies.
> - What AuraSort stores stays in a private folder on your computer, and you can delete it at any time.
> - Data leaves your computer only if you turn on an optional cloud AI provider, and then only what you confirm.

## What AuraSort stores on your computer
Everything is in a folder called `.aurasort` in your user folder (`%USERPROFILE%\.aurasort` on Windows, `~/.aurasort`
on macOS and Linux). On Windows it is readable by your account only; on macOS and Linux it has user-only permissions.

| What | File | Kept until |
|---|---|---|
| Settings (folders to scan or skip, destination, AI settings, never an API key) | `settings.json` | you change or delete them |
| File index (names, sizes, dates, folders, check results) | `index.sqlite3` | the next scan replaces it, or you delete it |
| Scan snapshots (used space per drive, for the trend chart) | in the index | you delete the data |
| History and Undo logs (which files were moved, copied or sent to the Recycle Bin, and where) | `history/*.json` | you delete the data |
| Thumbnails of pictures | `thumbs/` | you delete the data |
| A log of errors (your token, keys and home folder path are masked) | `aurasort.log` | it rotates at 1 MB, keeping 3 files |
| Document Insights results and extracted text | **memory only**, never on disk | 30, 60 or 90 minutes after a batch finishes (default 60), when AuraSort closes, or when a file is moved or deleted |
| A cloud API key, if you choose to remember it | your system keychain (Windows Credential Manager, macOS Keychain, Linux Secret Service) | you remove it or reset the AI settings |

## What may leave your computer
Only if you turn it on:
- **(a) Cloud AI requests** to the provider you chose. What is sent, what is masked and what is never sent is described
  in the [AI Data Notice](AI_DATA_NOTICE.md). Every batch asks for your confirmation first.
- **(b) An update check against GitHub.** AuraSort does not include an automatic update check in version 1.0.0. If one is
  added, it will be off by default and will show exactly what it requests. [OWNER TO CONFIRM]

Nothing else is sent. The local AI engines (Ollama, LM Studio, llama.cpp) run on your computer and are only contacted on
`127.0.0.1`.

## Browser storage
AuraSort uses your browser's local storage only for your theme, the version of these terms you accepted, a few view
preferences (such as grid or list) and its notification list. No cookies, no tracking.

## How to delete your data
- In AuraSort: **Settings > Legal > Delete my AuraSort data**. This removes the index, History/Undo logs, snapshots,
  thumbnails, settings, the log, Document Insights results and any saved API key. Your own files are not touched, and
  files AuraSort moved for you stay where they are. (Without History, those moves can no longer be undone.)
- Or with the uninstall scripts: `uninstall.ps1 -Purge` (Windows) or `uninstall.sh --purge` (macOS/Linux).

## Children
AuraSort is not directed at children. It collects no information from anyone, including children.

## Security
See [SECURITY.md](SECURITY.md) for how AuraSort protects your data and how to report a problem.

## Roles
The project does not receive your files or personal data, so it does not act as a controller or processor of them. If
you enable a cloud AI provider, you are the one sending data to that provider, and the provider's own privacy policy
applies to it.

## Changes to this policy
New versions get a new version number and effective date, and AuraSort asks you to look at them again.

## Contact
[GitHub Issues](https://github.com/skuser404/aurasort/issues) for questions; security problems privately through
[GitHub Security Advisories](https://github.com/skuser404/aurasort/security/advisories/new).
