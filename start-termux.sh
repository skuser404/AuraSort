#!/usr/bin/env bash
# Starts AuraSort in Termux and opens it in the phone's browser. Keep Termux open while you use it; Ctrl+C stops it.
# If the browser does not open by itself: open Chrome (or any browser) and type the address printed below.
cd "$(dirname "$0")" || exit 1
PORT="${AURASORT_PORT:-8765}"
command -v termux-wake-lock >/dev/null 2>&1 && termux-wake-lock   # keeps Android from pausing Termux while a scan runs
( sleep 2; termux-open-url "http://localhost:$PORT/" >/dev/null 2>&1 || true ) &
echo "AuraSort: open http://localhost:$PORT/ in your browser if it did not open (if that port is busy, use the address printed below)."
exec python server.py --no-browser --port "$PORT"
