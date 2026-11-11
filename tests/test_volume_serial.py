"""Regression: "Deep Scan finds 0 files" on Windows with Python 3.12+ (the friend's PC, and every windows-latest CI job on
3.12/3.13/3.14). Python 3.12+ reports the full 64-bit volume serial in st_dev; for about half of all drives it is 2**63
or more, which SQLite cannot store. Every folder of the scan was then skipped as "could not be stored" and the scan
ended with 0 files, while the estimate (which stores nothing) still saw the files."""
import os
import time
from unittest import mock

from tests.test_web_security import ServerCase
from tests.base import TempHomeCase
from core import index_db, jobs, scanner

BIG_DEV = 0xA3B2C1D0E5F60718      # a real-looking NTFS serial with the top bit set (> 2**63 - 1)
_real_stat = os.stat


class _Stat:
    """os.stat result with a 64-bit st_dev, everything else from the real file."""

    def __init__(self, st):
        self._st = st

    def __getattr__(self, k):
        return BIG_DEV if k == "st_dev" else getattr(self._st, k)


def big_dev_stat(*a, **k):
    return _Stat(_real_stat(*a, **k))


class VolumeSerialScanTest(TempHomeCase):
    def test_scan_on_a_drive_with_a_64_bit_serial_finds_the_files(self):
        for i in range(5):
            self.make(f"Docs/file {i}.txt", b"x" * (i + 1))
        with mock.patch("os.stat", big_dev_stat):
            job = scanner.start("deep", [str(self.home / "Docs")], [])
            while job.state in ("running", "paused"):
                time.sleep(0.02)
        snap = job.snapshot()
        self.assertEqual(snap["state"], "done")
        self.assertEqual(index_db.summary()["total"], 5, f"skipped: {snap.get('skipped')}")
        self.assertEqual(snap.get("skipped"), {})


class VolumeSerialMoveTest(ServerCase):
    def test_preview_and_move_on_such_a_drive(self):
        for i in range(3):
            self.make(f"In/p{i}.jpg", b"\xff\xd8" + bytes([i]))
        with mock.patch("os.stat", big_dev_stat):
            job = scanner.start("deep", [str(self.home / "In")], [])
            while job.state in ("running", "paused"):
                time.sleep(0.02)
            ids = [r["id"] for r in index_db.files_page({"scope": "all"})["rows"]]
            self.assertEqual(len(ids), 3)
            import json
            st, _, raw = self.req("/api/plan", {"dest": str(self.home / "Out")})
            self.assertEqual(st, 200, raw)
            st, _, raw = self.req("/api/execute", {"ids": ids, "dest": str(self.home / "Out"), "mode": "move", "layout": "here"})
            self.assertEqual(st, 200, raw)
            j = jobs.get(json.loads(raw)["job"])
            while j.state in ("running", "paused"):
                time.sleep(0.02)
        self.assertEqual(sorted(os.listdir(self.home / "Out")), ["p0.jpg", "p1.jpg", "p2.jpg"])
