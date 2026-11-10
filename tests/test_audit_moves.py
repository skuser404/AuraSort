"""End-to-end audit of the move flow through the real API: same drive, another drive (simulated), copy, name clashes,
a locked file, a project file, a view-only type, a full destination and a cancelled job. In every case: no file is lost,
nothing is overwritten, no partial file is left behind, and History matches what happened."""
import errno
import json
import os
import time
import unittest
from unittest import mock

from tests import fixtures as fx
from tests.test_web_security import ServerCase
from core import copier, history, index_db, jobs, mover, scanner, web


def all_files(root):
    return sorted(os.path.relpath(os.path.join(b, f), root) for b, _, fs in os.walk(root) for f in fs)


class AuditCase(ServerCase):
    def setUp(self):
        super().setUp()
        web._RATE.clear()
        self.out = self.home / "Sorted"

    def scan(self, files):
        for rel, data in files:
            self.make(rel, data)
        job = scanner.start("deep", [str(self.home / "Lib")], [])
        while job.state in ("running", "paused"):
            time.sleep(0.02)
        return index_db.files_page({"scope": "all"}, per=500)["rows"]

    def move(self, rows, **extra):
        body = dict(ids=[r["id"] for r in rows], dest=str(self.out), mode="move", layout="here", **extra)
        st, _, raw = self.req("/api/execute", body)
        r = json.loads(raw)
        self.assertEqual(st, 200, r)
        return r

    def wait(self, jid):
        j = jobs.get(jid)
        while j.state in ("running", "paused"):
            time.sleep(0.02)
        return j.snapshot()

    def no_parts(self):
        return [f for f in all_files(self.home) if f.endswith(copier.PART_SUFFIX)]

    def other_drive(self):
        """Simulate the destination being on another drive."""
        real, out = mover.device, os.path.normcase(os.path.realpath(str(self.out)))
        return mock.patch.object(mover, "device", lambda p: ("other",) if os.path.normcase(os.path.realpath(str(p))).startswith(out) else real(p))


class MoveAuditTest(AuditCase):
    def test_same_drive_is_a_rename(self):
        rows = self.scan([("Lib/a.png", fx.png()), ("Lib/b.pdf", fx.pdf())])
        snap = self.wait(self.move(rows)["job"])
        self.assertEqual((snap["moved"], snap["verified"]), (2, 0), "renames need no copy and no verification")
        self.assertEqual(all_files(self.out), ["a.png", "b.pdf"])

    def test_other_drive_is_copied_verified_then_removed_and_undoable(self):
        rows = self.scan([("Lib/a.png", fx.png()), ("Lib/b.pdf", fx.pdf())])
        with self.other_drive():
            r = self.move(rows)
            snap = self.wait(r["job"])
        self.assertEqual((snap["moved"], snap["verified"]), (2, 2))
        self.assertFalse((self.home / "Lib" / "a.png").exists())
        self.assertEqual(self.no_parts(), [])
        st, _, raw = self.req("/api/undo", {"id": r["job"]})
        self.assertEqual(json.loads(raw)["restored"], 2)
        self.assertTrue((self.home / "Lib" / "a.png").exists())

    def test_copy_keeps_originals_and_clash_gets_a_number(self):
        rows = self.scan([("Lib/a.png", fx.png())])
        self.out.mkdir()
        (self.out / "a.png").write_bytes(b"someone else's file")
        st, _, raw = self.req("/api/execute", dict(ids=[rows[0]["id"]], dest=str(self.out), mode="copy", layout="here"))
        self.wait(json.loads(raw)["job"])
        self.assertEqual(all_files(self.out), ["a (1).png", "a.png"])
        self.assertEqual((self.out / "a.png").read_bytes(), b"someone else's file", "never overwritten")
        self.assertTrue((self.home / "Lib" / "a.png").exists())

    def test_locked_file_is_skipped_others_continue(self):
        rows = self.scan([("Lib/a.png", fx.png()), ("Lib/locked.pdf", fx.pdf())])
        real = copier._raw_copy

        def raw(src, *a):
            if src.endswith("locked.pdf"):
                e = OSError(None, "in use", src, 32)
                e.winerror = 32
                raise e
            return real(src, *a)
        with self.other_drive(), mock.patch.object(copier, "_raw_copy", raw), mock.patch.object(copier, "LOCK_RETRY_S", (0.01,)):
            snap = self.wait(self.move(rows)["job"])
        self.assertEqual((snap["moved"], snap["skipped"]), (1, 1))
        self.assertIn("in use", " ".join(snap["errors"]))
        self.assertTrue((self.home / "Lib" / "locked.pdf").exists(), "the locked file stays where it was")
        self.assertEqual(self.no_parts(), [])

    def test_project_and_view_only_files_need_opt_in(self):
        rows = self.scan([("Lib/site/package.json", b"{}"), ("Lib/site/logo.png", fx.png()), ("Lib/tool.exe", fx.exe()), ("Lib/ok.png", fx.png())])
        r = self.move([x for x in rows if x["name"] in ("logo.png", "tool.exe", "ok.png")])
        self.wait(r["job"])
        self.assertEqual((r["count"], r["blocked"]), (1, 2))
        self.assertTrue((self.home / "Lib" / "site" / "logo.png").exists() and (self.home / "Lib" / "tool.exe").exists())

    def test_full_destination_stops_cleanly(self):
        rows = self.scan([(f"Lib/f{i}.pdf", fx.pdf(1) + bytes([i])) for i in range(4)])
        with self.other_drive(), mock.patch.object(copier, "_raw_copy", side_effect=OSError(errno.ENOSPC, "No space left on device")):
            r = self.move(rows)
            snap = self.wait(r["job"])
        self.assertEqual(snap["state"], "error")
        self.assertIn("full", " ".join(snap["errors"]))
        self.assertEqual(len(all_files(self.home / "Lib")), 4, "every source file is intact")
        self.assertEqual(self.no_parts(), [])
        self.assertEqual(history.load(r["job"])["state"], "stopped")

    def test_cancel_mid_job_loses_nothing(self):
        rows = self.scan([(f"Lib/f{i:02d}.pdf", fx.pdf(1) + bytes([i])) for i in range(60)])   # 60 x 0.15 s on 8 threads: well over a second
        real = copier._raw_copy

        def slow(*a):
            time.sleep(0.15)
            return real(*a)
        with self.other_drive(), mock.patch.object(copier, "_raw_copy", slow):
            r = self.move(rows)
            time.sleep(0.3)
            jobs.get(r["job"]).cancel()
            snap = self.wait(r["job"])
        self.assertEqual(snap["state"], "cancelled")
        moved, left = all_files(self.out), all_files(self.home / "Lib")
        self.assertEqual(len(moved) + len(left), 60, "every file is either moved or still at its source")
        self.assertTrue(0 < len(moved) < 60)
        m = history.load(r["job"])
        self.assertEqual((m["state"], len(m["ops"])), ("cancelled", len(moved)), "History lists exactly the files that moved")
        self.assertEqual(self.no_parts(), [])


if __name__ == "__main__":
    unittest.main()
