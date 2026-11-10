#!/bin/sh
# Installs AuraSort for the current user on macOS or Linux (no sudo needed).
# Downloads a tagged release, checks its SHA-256 against the release's SHA256SUMS, unpacks it and adds a launcher.
#   curl -fsSL https://raw.githubusercontent.com/skuser404/aurasort/v1.0.0/scripts/install.sh | sh
#   sh install.sh --dry-run            show what would happen, change nothing
#   sh install.sh --source ./release   install from a folder holding the ZIP and SHA256SUMS (offline)
set -eu
VERSION="${AURASORT_VERSION:-v1.0.0}"
REPO="${AURASORT_REPO:-skuser404/aurasort}"
DEST="${AURASORT_DIR:-$HOME/.local/share/aurasort}"
SOURCE=""
DRY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1 ;;
    --source) SOURCE="$2"; shift ;;
    --version) VERSION="$2"; shift ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done
ZIP="aurasort-$VERSION.zip"
say() { printf '%s\n' "$*"; }
run() { if [ "$DRY" = 1 ]; then say "would run: $*"; else "$@"; fi; }

# Python 3.10+ (from python.org, Homebrew or your distribution)
PY=""
for c in python3 python; do
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then PY="$c"; break; fi
done
if [ -z "$PY" ]; then
  say "Python 3.10 or newer was not found. macOS: install it from https://www.python.org/downloads/ (or 'brew install python'). Linux: 'sudo apt install python3' or your distribution's package."
  [ "$DRY" = 1 ] || exit 1
fi
command -v unzip >/dev/null 2>&1 || { say "Please install 'unzip' first."; exit 1; }

WORK="$(mktemp -d "${TMPDIR:-/tmp}/aurasort-install.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM
if [ -n "$SOURCE" ]; then
  cp "$SOURCE/$ZIP" "$SOURCE/SHA256SUMS" "$WORK/"
else
  BASE="https://github.com/$REPO/releases/download/$VERSION"
  say "Downloading $ZIP from github.com/$REPO ..."
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL -o "$WORK/$ZIP" "$BASE/$ZIP"; curl -fsSL -o "$WORK/SHA256SUMS" "$BASE/SHA256SUMS"
  else
    wget -q -O "$WORK/$ZIP" "$BASE/$ZIP"; wget -q -O "$WORK/SHA256SUMS" "$BASE/SHA256SUMS"
  fi
fi
WANT="$(grep " \*\{0,1\}$ZIP\$" "$WORK/SHA256SUMS" | awk '{print $1}' | head -n 1)"
[ -n "$WANT" ] || { say "SHA256SUMS has no line for $ZIP. Not installing."; exit 1; }
if command -v sha256sum >/dev/null 2>&1; then GOT="$(sha256sum "$WORK/$ZIP" | awk '{print $1}')"; else GOT="$(shasum -a 256 "$WORK/$ZIP" | awk '{print $1}')"; fi
if [ "$GOT" != "$WANT" ]; then rm -f "$WORK/$ZIP"; say "Checksum mismatch for $ZIP (expected $WANT, got $GOT). Not installing."; exit 1; fi
say "Checksum OK ($GOT)."

unzip -q "$WORK/$ZIP" -d "$WORK/unpacked"
ROOT="$WORK/unpacked"
set -- "$ROOT"/*
if [ $# -eq 1 ] && [ -d "$1" ]; then ROOT="$1"; fi   # GitHub ZIPs have one top folder: use what is inside it
[ -f "$ROOT/server.py" ] || { say "The release does not look like AuraSort (no server.py). Not installing."; exit 1; }

run mkdir -p "$DEST"
run cp -R "$ROOT/." "$DEST/"
if [ "$(uname)" = "Darwin" ]; then
  run chmod +x "$DEST/start.command"
  say "Start it by double-clicking $DEST/start.command (first time: right-click > Open, because it is not notarised)."
else
  run mkdir -p "$HOME/.local/bin" "$HOME/.local/share/applications"
  if [ "$DRY" = 1 ]; then say "would write $HOME/.local/bin/aurasort and aurasort.desktop"; else
    printf '#!/bin/sh\ncd "%s" && exec %s server.py "$@"\n' "$DEST" "$PY" > "$HOME/.local/bin/aurasort"
    chmod +x "$HOME/.local/bin/aurasort"
    printf '[Desktop Entry]\nType=Application\nName=AuraSort\nComment=Make your files easier.\nExec=%s/.local/bin/aurasort\nTerminal=true\nCategories=Utility;FileTools;\n' "$HOME" > "$HOME/.local/share/applications/aurasort.desktop"
  fi
  say "Start it with: aurasort   (or from your applications menu)."
fi
say "AuraSort $VERSION is installed in $DEST. It opens in your browser at http://localhost:8765/"
say "To remove it: sh \"$DEST/scripts/uninstall.sh\"   (add --purge to also delete its data folder ~/.aurasort)"
