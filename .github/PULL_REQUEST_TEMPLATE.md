## What and why

## How I tested it
- [ ] `python -m unittest discover -s tests -t .` passes (OS + Python version: )
- [ ] `bandit -q -r core server.py tools` is clean
- [ ] UI changes: screenshots in dark **and** light theme

## Safety checklist
- [ ] Touches move / copy / delete / open / reveal? Tests added for the safety checks involved
- [ ] No new runtime dependency, no network call, no inline script/style
- [ ] Nothing can be permanently deleted or overwritten
