#!/usr/bin/env python3
"""Copy benchmark: AuraSort's verified copy engine vs plain shutil.copy2, on test files it creates (and removes) itself.
    python tools/bench_copy.py [work folder] [--small N] [--large-mb M]
Prints files/s and MB/s. Source files are read once beforehand so every method starts with the same (warm) cache.
Run it with the work folder on the drive you care about; across two drives, put the folder on the destination drive."""
import argparse
import os
import shutil
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import config, copier  # noqa: E402

SMALL_BYTES = 16 * 1024
MB = 1024 * 1024


def make_sets(root, n_small, large_mb, n_large=3):
    """Why: realistic mixes: many small files (photos/documents) and a few large ones (videos)."""
    small, large = root / "src-small", root / "src-large"
    small.mkdir(parents=True)
    large.mkdir(parents=True)
    for i in range(n_small):
        (small / f"f{i:05d}.bin").write_bytes(os.urandom(SMALL_BYTES))
    block = os.urandom(MB)
    for i in range(n_large):
        with open(large / f"big{i}.bin", "wb") as fh:
            for _ in range(large_mb):
                fh.write(block)
    return sorted(small.iterdir()), sorted(large.iterdir())


def warm(files):
    for f in files:
        with open(f, "rb") as fh:
            while fh.read(8 * MB):
                pass


def run(label, files, dest, fn, parallel=1):
    """Why: one timed pass; the destination is emptied afterwards."""
    dest.mkdir(parents=True)
    t0 = time.perf_counter()
    if parallel > 1:
        with ThreadPoolExecutor(parallel) as pool:
            list(pool.map(lambda f: fn(f, dest), files))
    else:
        for f in files:
            fn(f, dest)
    dt = time.perf_counter() - t0
    total = sum(f.stat().st_size for f in files)
    shutil.rmtree(dest)
    print(f"  {label:<44} {len(files) / dt:10.0f} files/s {total / MB / dt:10.1f} MB/s   ({dt:.2f} s)")
    return dt


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("folder", nargs="?", default="")
    ap.add_argument("--small", type=int, default=2000)
    ap.add_argument("--large-mb", type=int, default=128)
    a = ap.parse_args()
    root = Path(tempfile.mkdtemp(prefix="aurasort-bench-", dir=a.folder or None))
    try:
        print(f"Creating {a.small} x 16 KB and 3 x {a.large_mb} MB in {root} ...")
        small, large = make_sets(root, a.small, a.large_mb)
        warm(small + large)
        plain = lambda f, d: shutil.copy2(f, d / f.name)
        for name, files in (("many small files", small), ("few large files", large)):
            print(f"\n{name}:")
            run("shutil.copy2 (no verification)", files, root / "o1", plain)
            run("engine copy, full BLAKE2b verification", files, root / "o2", lambda f, d: copier.copy_verified(str(f), str(d), f.name, "full"))
            run("engine copy, size check only", files, root / "o3", lambda f, d: copier.copy_verified(str(f), str(d), f.name, "size"))
            run("engine move-grade (fsync + full verification)", files, root / "o6", lambda f, d: copier.copy_verified(str(f), str(d), f.name, "full", durable=True))
            if files is small:
                n = config.COPY_SMALL_THREADS["ssd"]
                run(f"engine copy, full verification, {n} threads (SSD)", files, root / "o4",
                    lambda f, d: copier.copy_verified(str(f), str(d), f.name, "full"), parallel=n)
                run(f"engine move-grade, {n} threads (SSD)", files, root / "o7",
                    lambda f, d: copier.copy_verified(str(f), str(d), f.name, "full", durable=True), parallel=n)
                run(f"shutil.copy2, {n} threads", files, root / "o5", plain, parallel=n)
        print("\nNotes: same-drive numbers. shutil.copy2 returns while data may still be in the RAM cache; 'move-grade' waits until the\n"
              "copy is on the disk (fsync) and re-reads both files to verify, because only then may a move delete the original.")
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    main()
