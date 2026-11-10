#!/usr/bin/env python3
"""AuraSort benchmark: N fake files (default 200,000) -> Deep Scan via the HTTP API -> responsiveness, list and search timings.

Usage:  python tools/benchmark.py --dir D:\\some\\empty\\folder [--files 200000]
The folder must be outside protected locations (not inside AppData / system folders). Your real data is never touched:
the benchmark's own index and history live inside --dir."""
import argparse
import json
import os
import random
import shutil
import statistics
import subprocess  # nosec B404  # dev tool: runs node with a fixed argument list
import sys
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

WORDS = ["IMG", "photo", "light", "sunset", "report", "invoice", "track", "clip", "design", "screenshot", "holiday", "beach",
         "night", "family", "notes", "Spotlight", "flight", "delight", "budget", "backup"]
EXTS = ["jpg", "jpg", "png", "heic", "mp4", "mov", "mp3", "pdf", "docx", "xlsx", "zip", "txt", "exe", "py", "log", "iso"]
FILES_PER_DIR = 100
TARGET_SEARCH_MS = 100
TARGET_STATUS_P95_MS = 250


def build_tree(base, n):
    """Why: realistic names/extensions in folders of 100; reused if it already exists with the same size."""
    marker = base / f".bench-{n}"
    if marker.exists():
        print(f"reusing {n:,} files in {base}")
        return
    if base.exists():
        shutil.rmtree(base)
    rnd = random.Random(42)  # nosec B311  # fake file names for a benchmark, not security
    t0 = time.time()
    for i in range(n):
        d = base / f"folder_{i // FILES_PER_DIR:05d}"
        if i % FILES_PER_DIR == 0:
            d.mkdir(parents=True, exist_ok=True)
        name = f"{rnd.choice(WORDS)}_{rnd.choice(WORDS)}_{i}.{rnd.choice(EXTS)}"
        with open(d / name, "wb") as f:
            f.write(b"x" * (i % 97))
        if i and i % 50000 == 0:
            print(f"  created {i:,} files ({time.time() - t0:.0f} s)")
    marker.write_text("ok")
    print(f"created {n:,} files in {time.time() - t0:.0f} s")


def start_server(home):
    """Why: run the real server in-process (own HOME, so the benchmark never touches the user's data)."""
    from core import config
    config.HOME = home
    config.DATA_DIR = home / f".{config.APP_SLUG}"
    config.HISTORY_DIR = config.DATA_DIR / "history"
    config.INDEX_DB = config.DATA_DIR / "index.sqlite3"
    config.THUMB_DIR = config.DATA_DIR / "thumbs"
    config.SETTINGS_FILE = config.DATA_DIR / "settings.json"
    config.LOG_FILE = config.DATA_DIR / "bench.log"
    config.LEGACY_DATA_DIRS = ()
    import server
    from core.web import Handler
    server.prepare()
    Handler.token = "bench-token"  # nosec B105  # not a password (header name / empty default / local test token)
    srv, port = server.make_server(8890)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return port


def api(port, path, body=None):
    """Why: measure what the browser experiences (HTTP round trip included)."""
    req = urllib.request.Request(f"http://127.0.0.1:{port}/api/{path}", data=json.dumps(body).encode() if body is not None else None,
                                 headers={"X-AuraSort-Token": "bench-token", "Content-Type": "application/json", "Host": f"127.0.0.1:{port}",
                                          "Accept-Encoding": "gzip"})
    t0 = time.perf_counter()
    with urllib.request.urlopen(req) as r:  # nosec B310  # fixed http://127.0.0.1 URL (local benchmark)
        raw = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            import gzip
            raw = gzip.decompress(raw)
    return json.loads(raw), (time.perf_counter() - t0) * 1000, len(raw)


def js_search_bench(index_json, out_dir):
    """Why: the real browser search code (match.js + query.js) timed under Node on the real search index."""
    node = shutil.which("node")
    if not node:
        return None
    script = out_dir / "bench_search.cjs"
    idx = out_dir / "search-index.json"
    idx.write_bytes(index_json)
    js = ROOT / "docs" / "js"
    engine = "\n".join((js / f).read_text(encoding="utf-8") for f in ("match.js", "query.js"))
    script.write_text(engine + f"""
const fs = require('fs');
const j = JSON.parse(fs.readFileSync({json.dumps(str(idx))}, 'utf8')), n = j.id.length;
const src = {{ id: j.id, name: j.name, cat: j.cat.map(c => j.cats[c]), ext: j.ext.map(e => j.exts[e]), dir: j.dir, size: j.size, mtime: j.mtime, ctime: j.ctime, atime: j.atime,
  dirs: j.dirs.map((p, i) => ({{ id: i, path: p, kind: j.dir_kind[i], included: j.dir_inc[i] }})) }};
let t = performance.now(); const T = qTable(src); const build = performance.now() - t;
const res = {{ files: n, build_ms: Math.round(build) }};
for (const q of ['light', 'ligth', 'spotlight', 'img 123', '.png', 'zzqx']) {{
  t = performance.now(); const toks = tokens(q); let c = 0;
  for (let i = 0; i < T.id.length; i++) if (scoreName(T.ln[i], T.lb[i], T.mask[i], toks, false)) c++;
  res[q] = {{ ms: Math.round(performance.now() - t), hits: c }};
}}
console.log(JSON.stringify(res));
""", encoding="utf-8")
    out = subprocess.run([node, str(script)], capture_output=True, text=True, timeout=600)  # nosec B603  # fixed args
    return json.loads(out.stdout) if out.returncode == 0 else {"error": out.stderr[-400:]}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--dir", required=True, help="an empty folder outside protected locations")
    ap.add_argument("--files", type=int, default=200_000)
    a = ap.parse_args()
    base = Path(a.dir).resolve()
    home, tree = base / "home", base / "home" / "bench"
    home.mkdir(parents=True, exist_ok=True)
    build_tree(tree, a.files)
    port = start_server(home)
    lat = []
    _, ms, _ = api(port, "scan/start", {"mode": "deep", "roots": [str(tree)], "skip": []})
    t0 = time.time()
    while True:
        st, ms, _ = api(port, "scan/status")
        lat.append(ms)
        _, ms2, _ = api(port, "summary")
        lat.append(ms2)
        if st["state"] not in ("running", "paused"):
            break
        time.sleep(0.1)
    scan_s = time.time() - t0
    report = {"files_indexed": st["found"], "scan_seconds": round(scan_s, 1), "files_per_second": round(st["found"] / max(scan_s, .01)),
              "ui_latency_during_scan_ms": {"p50": round(statistics.median(lat), 1), "p95": round(sorted(lat)[int(len(lat) * .95) - 1], 1), "max": round(max(lat), 1)}}
    timings = {}
    for label, path in [("first page (images)", "files?type=Images&page=1&per=100"), ("last page (all, by size)", "files?page=2000&per=100"),
                        ("sort by name", "files?sort=name&page=10&per=100"), ("format filter png,jpg", "files?format=png,jpg&per=100"),
                        ("folder filter", "files?folder=folder_00123&per=100"), ("substring q=light", "files?q=light&per=100"), ("extensions table", "extensions"),
                        ("summary", "summary")]:
        _, ms, size = api(port, path)
        timings[label] = f"{ms:.0f} ms ({size / 1024:.0f} KB)"
    raw = None
    t = time.perf_counter()
    req = urllib.request.Request(f"http://127.0.0.1:{port}/api/search-index", headers={"X-AuraSort-Token": "bench-token", "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req) as r:  # nosec B310  # fixed http://127.0.0.1 URL (local benchmark)
        wire = r.read()
        import gzip
        raw = gzip.decompress(wire) if r.headers.get("Content-Encoding") == "gzip" else wire
    timings["search index (first build)"] = f"{(time.perf_counter() - t) * 1000:.0f} ms ({len(wire) / 1048576:.1f} MB gzipped, {len(raw) / 1048576:.1f} MB raw)"
    report["server_timings"] = timings
    js = js_search_bench(raw, base)
    report["browser_search_engine"] = js
    print(json.dumps(report, indent=2))
    ok = report["ui_latency_during_scan_ms"]["p95"] <= TARGET_STATUS_P95_MS
    if js and "error" not in js:
        ok = ok and all(v["ms"] <= TARGET_SEARCH_MS for k, v in js.items() if isinstance(v, dict))
    print("\nRESULT:", "PASS" if ok else "CHECK", f"(targets: search <= {TARGET_SEARCH_MS} ms per query, UI p95 <= {TARGET_STATUS_P95_MS} ms during scan)")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
