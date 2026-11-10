# Contributing to AuraSort

Thanks for helping. A few rules keep AuraSort safe and simple. By taking part you agree to the
[Code of Conduct](CODE_OF_CONDUCT.md).

## Ground rules
1. **No new runtime dependencies.** Python 3.10+ standard library only (Pillow and pypdf stay optional). The front end is
   plain HTML/CSS/JS with no build step, no CDNs and no network calls. The only network code is `core/llm.py` (optional
   Document Insights), and a test enforces that.
2. **Never permanently delete.** Deletes go through `core/trash.py` (Recycle Bin / Trash) only. Moves never overwrite.
   Copies across drives go through `core/copier.py` (verified before a source is removed).
3. **Changes that touch move, copy, delete, open or reveal need tests** in `tests/`, covering the safety checks they rely
   on (protected folders, projects, view-only categories, links, files changed since the scan).
4. **AI stays a suggestion.** Model output is never executed, confidential rules run first, and nothing about documents
   is written to disk or logs.
5. **Small functions, one job each**, with a one-line `Why:` comment. Constants go in `core/config.py` / `docs/js/config.js`.
6. **Friendly errors, plain copy.** Never send stack traces or full paths to the browser. No emoji or hype words (a test checks).

## Run the checks
```bash
python -m unittest discover -s tests -t .                  # unit tests (all platforms)
python -m pip install bandit==1.9.4 && python -m bandit -q -r core server.py tools
python tools/make_fixtures.py ../fixture                    # fake home folder for the browser tests
node tests/e2e/app.e2e.mjs --home ../fixture/home --out out # end-to-end (Node 22+, Edge/Chrome; server running on that home)
node tests/e2e/screens.mjs --out out                        # screenshots of every page, both themes, two sizes
```
Optional: `AURASORT_TEST_RECYCLE_BIN=1` on Windows also tests the real Recycle Bin (send + restore).

## Pull requests
- Describe what changed and why, and how you tested it (OS + Python version).
- Screenshots for UI changes, in both the dark and the light theme, without private file names.
- Never paste personal files, full paths with your user name, API keys or screenshots of private documents.
- Report security problems privately (see [SECURITY.md](SECURITY.md)), not in a PR.
- Changing a legal document? Bump its version and effective date, and `TERMS_VERSION` in `docs/js/legal.js` for the Terms.
