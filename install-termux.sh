#!/usr/bin/env bash
# AuraSort on Android, inside Termux (EXPERIMENTAL). Run from the AuraSort folder:
#   pkg update -y && pkg install -y python git && git clone https://github.com/skuser404/AuraSort.git && cd AuraSort && bash install-termux.sh
# What it does: installs the optional packages, asks Android for access to your files (termux-setup-storage), runs a
# self-test and starts AuraSort. Later, start it again with:  bash start-termux.sh
# Phone-optimized layout: coming later. The desktop layout works in the phone's browser.
set -eu
cd "$(dirname "$0")"
say() { printf '%s\n' "$*"; }
if [ -z "${PREFIX:-}" ] || [ "${PREFIX#*com.termux}" = "$PREFIX" ]; then
  say "This script is for Termux on Android. On a computer use scripts/install.sh (macOS/Linux) or install.ps1 (Windows)."
  exit 1
fi
say "== Packages"
command -v python >/dev/null 2>&1 || pkg install -y python
# Pillow builds slowly with pip on a phone; Termux ships it ready-made. pypdf is pure Python.
pkg install -y python-pillow >/dev/null 2>&1 || say "  (python-pillow not available: thumbnails use the built-in fallback)"
python -m pip install --disable-pip-version-check --quiet "$(grep -E '^pypdf==' requirements.txt | cut -d' ' -f1)" || say "  pypdf could not be installed; AuraSort works without it."

say "== Access to your files"
if [ ! -d "$HOME/storage/shared" ]; then
  say "  Android will now ask whether Termux may access your files. Tap 'Allow' (on Android 11+ it is 'Allow management of all files')."
  say "  Without it AuraSort cannot see your Downloads, Pictures (DCIM) or Documents."
  termux-setup-storage || true
  sleep 3
fi
[ -d /storage/emulated/0 ] && [ -r /storage/emulated/0 ] && say "  OK: your shared storage is readable." || say "  Shared storage is not readable yet: run termux-setup-storage again and allow access."

say "== Self-test"
python server.py --doctor | head -n 30 || true
chmod +x start-termux.sh
say ""
say "Installed. Start AuraSort now and later with:  bash start-termux.sh"
say "Deleting on Android: there is no Recycle Bin, so AuraSort moves files into a folder named .AuraSortTrash on the same"
say "storage instead. You can restore them in Settings > AuraSort trash. Nothing is erased unless you turn on the purge timer."
exec bash start-termux.sh
