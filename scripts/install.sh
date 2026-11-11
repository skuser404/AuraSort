#!/bin/sh
# Installs (or updates) AuraSort for the current user on macOS (Apple Silicon and Intel) or Linux. No sudo needed.
#   curl -fsSL https://github.com/skuser404/AuraSort/releases/latest/download/install.sh | sh
#   curl -fsSL .../install.sh | sh -s -- --yes        answer yes to every question
#   sh install.sh --dry-run                           show what would happen, change nothing
#   sh install.sh --source ./release                  offline: a folder holding aurasort.zip and SHA256SUMS
# Steps: Python 3.10+ (offers Homebrew/brew install python on macOS, only if you say yes) -> download the release ZIP ->
# check SHA-256 -> install to ~/.local/share/aurasort -> optional packages in a private virtual environment -> launcher
# -> self-test (server.py --doctor) -> offer to start. Safe to run again (that is how you update); your data in
# ~/.aurasort is kept.
set -eu
VERSION="${AURASORT_VERSION:-latest}"
REPO="${AURASORT_REPO:-skuser404/AuraSort}"
DEST="${AURASORT_DIR:-$HOME/.local/share/aurasort}"
SOURCE=""; DRY=0; YES=0; START=1; PACKAGES=1
ZIP="aurasort.zip"
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1 ;;
    --yes|-y) YES=1 ;;
    --no-start) START=0 ;;
    --no-packages) PACKAGES=0 ;;
    --source) SOURCE="$2"; shift ;;
    --version) VERSION="$2"; shift ;;
    --dir) DEST="$2"; shift ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done
say() { printf '%s\n' "$*"; }
step() { printf '\n== %s\n' "$*"; }
manual() { say "  $1"; [ -z "${2:-}" ] || say "  Run this yourself:  $2"; }
run() { if [ "$DRY" = 1 ]; then say "  would run: $*"; else "$@"; fi; }
ask() {   # ask "question" default(y|n); reads the terminal even under "curl | sh"
  [ "$YES" = 1 ] && return 0
  if [ -r /dev/tty ] && [ -w /dev/tty ]; then
    if [ "$2" = y ]; then printf '%s [Y/n] ' "$1" >/dev/tty; else printf '%s [y/N] ' "$1" >/dev/tty; fi
    read -r a </dev/tty || a=""
  else a=""; fi
  case "${a:-$2}" in [Yy]*) return 0 ;; *) return 1 ;; esac
}
OS="$(uname -s)"
if [ "$(id -u)" = 0 ]; then
  say "Warning: this runs as root. AuraSort does not need it, and it would be installed for root only."
  ask "Continue anyway?" n || exit 1
fi
case "$DEST" in /|/bin*|/sbin*|/usr*|/etc*|/System*|/Library*) say "Refusing to install into $DEST (a system folder)."; exit 1 ;; esac

# ---- 1. Python 3.10+ ----
py_ok() { "$1" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; }
find_python() {
  # Why: on macOS /usr/bin/python3 is a stub until the Xcode tools are installed (it pops up a dialog) and is often 3.9,
  # so Homebrew (Apple Silicon /opt/homebrew, Intel /usr/local) and python.org installs are tried first.
  for c in "${AURASORT_PYTHON:-}" /opt/homebrew/bin/python3 /usr/local/bin/python3 /Library/Frameworks/Python.framework/Versions/3.1[0-9]/bin/python3 \
           "$(command -v python3.13 2>/dev/null || true)" "$(command -v python3.12 2>/dev/null || true)" "$(command -v python3 2>/dev/null || true)" "$(command -v python 2>/dev/null || true)"; do
    [ -n "$c" ] && [ -x "$c" ] || continue
    if [ "$OS" = Darwin ] && [ "$c" = /usr/bin/python3 ] && ! xcode-select -p >/dev/null 2>&1; then continue; fi
    if py_ok "$c"; then printf '%s' "$c"; return 0; fi
  done
  return 1
}
step "Checking for Python 3.10 or newer"
PY="$(find_python || true)"
if [ -z "$PY" ]; then
  if [ "$OS" = Darwin ]; then
    BREW="$(command -v brew || ls /opt/homebrew/bin/brew /usr/local/bin/brew 2>/dev/null | head -n 1 || true)"
    if [ -z "$BREW" ] && ask "  Python 3.10+ is missing. Install Homebrew first (from brew.sh, it asks for your password)?" n; then
      run /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
      BREW="$(ls /opt/homebrew/bin/brew /usr/local/bin/brew 2>/dev/null | head -n 1 || true)"
    fi
    if [ -n "$BREW" ] && ask "  Install Python 3.12 with Homebrew (brew install python@3.12)?" y; then
      run "$BREW" install python@3.12
    fi
    PY="$(find_python || true)"
    [ -n "$PY" ] || manual "Python 3.10 or newer is needed." "brew install python@3.12   (or the installer from https://www.python.org/downloads/macos/)"
  else
    manual "Python 3.10 or newer is needed. Install it with your package manager, then run this again:" ""
    say "    Debian/Ubuntu/Mint:  sudo apt install python3 python3-venv"
    say "    Fedora:              sudo dnf install python3"
    say "    Arch/Manjaro:        sudo pacman -S python"
    say "    openSUSE:            sudo zypper install python3"
  fi
  [ -n "$PY" ] || { [ "$DRY" = 1 ] || exit 1; PY=python3; }
fi
say "  Using $PY ($("$PY" -c 'import sys; print(sys.version.split()[0])' 2>/dev/null || echo '?'))"

# ---- 2. download and verify ----
WORK="$(mktemp -d "${TMPDIR:-/tmp}/aurasort-install.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT INT TERM
step "Downloading AuraSort"
if [ -n "$SOURCE" ]; then
  cp "$SOURCE/$ZIP" "$SOURCE/SHA256SUMS" "$WORK/"
else
  if [ "$VERSION" = latest ]; then BASE="https://github.com/$REPO/releases/latest/download"; else BASE="https://github.com/$REPO/releases/download/$VERSION"; fi
  say "  $BASE/$ZIP"
  fetch() { if command -v curl >/dev/null 2>&1; then curl -fsSL -o "$2" "$1"; else wget -q -O "$2" "$1"; fi; }
  if ! fetch "$BASE/$ZIP" "$WORK/$ZIP" || ! fetch "$BASE/SHA256SUMS" "$WORK/SHA256SUMS"; then
    manual "The download failed. Check your connection, or that a release exists at https://github.com/$REPO/releases" ""
    say "  Manual alternative:  cd ~ && git clone https://github.com/skuser404/AuraSort.git && cd AuraSort && $PY server.py"
    exit 1
  fi
fi
WANT="$(grep " \*\{0,1\}$ZIP\$" "$WORK/SHA256SUMS" | awk '{print $1}' | head -n 1)"
[ -n "$WANT" ] || { say "SHA256SUMS has no line for $ZIP. Not installing."; exit 1; }
if command -v sha256sum >/dev/null 2>&1; then GOT="$(sha256sum "$WORK/$ZIP" | awk '{print $1}')"
elif command -v shasum >/dev/null 2>&1; then GOT="$(shasum -a 256 "$WORK/$ZIP" | awk '{print $1}')"
else GOT="$("$PY" -c 'import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest())' "$WORK/$ZIP")"; fi
if [ "$GOT" != "$WANT" ]; then rm -f "$WORK/$ZIP"; say "Checksum mismatch for $ZIP (expected $WANT, got $GOT). Not installing."; exit 1; fi
say "  Checksum OK ($GOT)"
"$PY" -m zipfile -e "$WORK/$ZIP" "$WORK/unpacked"     # no 'unzip' needed
ROOT="$WORK/unpacked"
set -- "$ROOT"/*
if [ $# -eq 1 ] && [ -d "$1" ]; then ROOT="$1"; fi   # one top folder in the ZIP: use what is inside it
[ -f "$ROOT/server.py" ] || { say "The download does not look like AuraSort (no server.py). Not installing."; exit 1; }
VER="$(sed -n 's/^APP_VERSION = "\(.*\)"/\1/p' "$ROOT/core/config.py" | head -n 1)"

# ---- 3. install (staged: a failure never leaves half an app) ----
step "Installing AuraSort $VER to $DEST"
if [ -d "$DEST" ] && [ ! -f "$DEST/server.py" ] && [ -n "$(ls -A "$DEST" 2>/dev/null)" ]; then
  say "$DEST exists and is not an AuraSort install. Not touching it. Use --dir to choose another folder."; exit 1
fi
run mkdir -p "$(dirname "$DEST")"
run rm -rf "$DEST.new" "$DEST.old"          # leftovers of an interrupted earlier run (program files only)
run cp -R "$ROOT" "$DEST.new"
if [ -d "$DEST/.venv" ]; then run mv "$DEST/.venv" "$DEST.new/.venv"; fi   # keep the installed packages
if [ -d "$DEST" ]; then run mv "$DEST" "$DEST.old"; fi
run mv "$DEST.new" "$DEST"
run rm -rf "$DEST.old"                       # the previous version's program files; your data is in ~/.aurasort
RUNPY="$PY"

venv_py() {   # the virtual environment's Python, only if it really runs (bin/ on macOS/Linux, Scripts/ under Git Bash)
  for c in "$DEST/.venv/bin/python" "$DEST/.venv/Scripts/python.exe"; do
    if [ -x "$c" ] && "$c" -c 'import sys' >/dev/null 2>&1; then printf '%s' "$c"; return 0; fi
  done
  return 1
}

# ---- 4. optional packages, in a private virtual environment (no system changes, no "externally managed" errors) ----
if [ "$PACKAGES" = 1 ]; then
  step "Installing optional packages (Pillow, pypdf)"
  if [ "$DRY" = 1 ]; then say "  would create $DEST/.venv and pip install -r requirements.txt"
  elif venv_py >/dev/null || { "$PY" -m venv "$DEST/.venv" >/dev/null 2>&1 && venv_py >/dev/null; }; then
    VPY="$(venv_py)"
    if "$VPY" -m pip install --disable-pip-version-check --quiet -r "$DEST/requirements.txt"; then RUNPY="$VPY"; say "  Done."
    else manual "The optional packages could not be installed. AuraSort works without them." "$VPY -m pip install -r $DEST/requirements.txt"; fi
  else
    manual "Python's venv module is missing, so the optional packages were skipped (AuraSort works without them)." "sudo apt install python3-venv   (then run this installer again)"
  fi
fi

# ---- 5. launcher ----
step "Adding a launcher"
if [ "$DRY" = 1 ]; then say "  would write the launcher"
elif [ "$OS" = Darwin ]; then
  printf '#!/bin/sh\n# AuraSort (double-click to start)\ncd "%s" || exit 1\nexec "%s" server.py "$@"\n' "$DEST" "$RUNPY" > "$DEST/start.command"
  chmod +x "$DEST/start.command"
  mkdir -p "$HOME/Applications" && ln -sf "$DEST/start.command" "$HOME/Applications/AuraSort.command"
  say "  Start it by double-clicking ~/Applications/AuraSort.command (made on this Mac, so Gatekeeper does not block it)."
else
  mkdir -p "$HOME/.local/bin" "$HOME/.local/share/applications"
  printf '#!/bin/sh\ncd "%s" && exec "%s" server.py "$@"\n' "$DEST" "$RUNPY" > "$HOME/.local/bin/aurasort"
  chmod +x "$HOME/.local/bin/aurasort"
  printf '[Desktop Entry]\nType=Application\nName=AuraSort\nComment=A local file organizer\nExec=%s/.local/bin/aurasort\nTerminal=true\nCategories=Utility;FileTools;\n' "$HOME" > "$HOME/.local/share/applications/aurasort.desktop"
  say "  Start it with: aurasort   (or from your applications menu). If 'aurasort' is not found, open a new terminal."
fi
[ "$DRY" = 1 ] && { say ""; say "Dry run: nothing was installed or changed."; exit 0; }

# ---- 6. self-test ----
step "Self-test (server.py --doctor)"
( cd "$DEST" && "$RUNPY" server.py --doctor | head -n 30 | sed 's/^/  /' ) || say "  The self-test found a problem (see FAIL above). The README troubleshooting table explains each line."
say ""
say "AuraSort $VER is installed in $DEST. It opens in your browser at http://localhost:8765/"
say "  Update: run the same install command again.   Remove: sh \"$DEST/scripts/uninstall.sh\" (add --purge to also delete ~/.aurasort)"
if [ "$OS" = Darwin ]; then say "  macOS: the first scan of Desktop/Documents/Downloads asks for permission. Allow it, or see 'Full Disk Access' in the README."; fi
if [ "$START" = 1 ] && ask "Start AuraSort now?" y; then cd "$DEST" && exec "$RUNPY" server.py; fi
