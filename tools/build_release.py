#!/usr/bin/env python3
"""Builds the release assets the installers download, so CI and local install tests use exactly the same files.

    python tools/build_release.py <out folder>

Writes aurasort.zip (every file git tracks, plus new files not ignored, under one top folder "aurasort/"),
copies of install.ps1 / install.sh / install-termux.sh, and SHA256SUMS for all of them. The names never change
between versions, so https://github.com/skuser404/AuraSort/releases/latest/download/<name> always works."""
import hashlib
import os
import subprocess  # nosec B404  # fixed argument list (git ls-files)
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INSTALLERS = ("scripts/install.ps1", "scripts/install.sh", "install-termux.sh")
TOP = "aurasort"
EXEC_SUFFIXES = (".sh", ".command")
# Never shipped, even if someone forgets to ignore them.
NEVER = (".git/", ".claude/", "dist/", "__pycache__/", "node_modules/", "tests/e2e/out", "site/")   # site/ is the public website, not the app


def tracked_files():
    """Why: git decides what belongs to the product (ignored files and local data never get into a release)."""
    out = subprocess.run(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd=ROOT,  # nosec B603 B607
                         capture_output=True, check=True).stdout.decode("utf-8")
    files = sorted({f for f in out.split("\0") if f and (ROOT / f).is_file()})
    return [f for f in files if not any(f.startswith(n) or f"/{n}" in f"/{f}" for n in NEVER)]


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build(out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    zpath = out / "aurasort.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for f in tracked_files():
            data = (ROOT / f).read_bytes()
            if f.endswith((".bat", ".cmd")):
                data = data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")   # cmd.exe wants CRLF
            elif not f.endswith((".png", ".jpg", ".ico", ".zip")) and b"\r\n" in data:
                data = data.replace(b"\r\n", b"\n")   # Windows checkouts may have CRLF; scripts must ship with LF
            info = zipfile.ZipInfo(f"{TOP}/{f}", date_time=(2020, 1, 1, 0, 0, 0))   # fixed time: reproducible checksums
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o755 if f.endswith(EXEC_SUFFIXES) else 0o644) << 16
            z.writestr(info, data)
    names = [zpath.name]
    for rel in INSTALLERS:
        src = ROOT / rel
        if src.is_file():
            (out / src.name).write_bytes(src.read_bytes().replace(b"\r\n", b"\n"))
            names.append(src.name)
    lines = [f"{sha256(out / n)}  {n}" for n in names]
    (out / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return out


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    build(sys.argv[1])
