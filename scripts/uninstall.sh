#!/bin/sh
# Removes AuraSort (app folder and launchers). Your own files are never touched.
#   sh uninstall.sh            remove the app
#   sh uninstall.sh --purge    also delete ~/.aurasort (index, History/Undo logs, settings, thumbnails) and a saved API key
#   sh uninstall.sh --dry-run  show what would happen
set -eu
DEST="${AURASORT_DIR:-$HOME/.local/share/aurasort}"
PURGE=0
DRY=0
for a in "$@"; do
  case "$a" in --purge) PURGE=1 ;; --dry-run) DRY=1 ;; *) echo "Unknown option: $a" >&2; exit 2 ;; esac
done
rm_() { if [ "$DRY" = 1 ]; then echo "would remove: $*"; else rm -rf "$@"; fi; }
if [ -f "$DEST/server.py" ]; then rm_ "$DEST"; elif [ -e "$DEST" ]; then echo "$DEST does not look like AuraSort (no server.py). Left as it is."; fi
rm_ "$HOME/.local/bin/aurasort" "$HOME/.local/share/applications/aurasort.desktop" "$HOME/Applications/AuraSort.command"
if [ "$PURGE" = 1 ]; then
  rm_ "$HOME/.aurasort"
  if [ "$DRY" = 0 ]; then
    if command -v security >/dev/null 2>&1; then security delete-generic-password -a aurasort -s "AuraSort cloud AI key" >/dev/null 2>&1 || true; fi
    if command -v secret-tool >/dev/null 2>&1; then secret-tool clear service "AuraSort cloud AI key" account aurasort >/dev/null 2>&1 || true; fi
  fi
fi
echo "AuraSort was removed. Files it moved for you stay where they are."
echo "Files kept by 'Replace' (and, on Android, deleted files) are still in folders named .AuraSortTrash; delete them yourself when no longer needed."
