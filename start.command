#!/bin/sh
# macOS: double-click to start AuraSort (first time: right-click > Open, because the script is not notarised).
cd "$(dirname "$0")" || exit 1
if command -v python3 >/dev/null 2>&1; then exec python3 server.py "$@"; fi
echo "Python 3.10 or newer is needed: https://www.python.org/downloads/ (or 'brew install python')."
read -r _
