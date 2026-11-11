"""Move/copy/undo: never overwrite, re-check before acting, undo restores, history manifests are written."""
import os
import time
import unittest

from tests.base import TempHomeCase
from core import history, jobs, mover


def op_for(path, fid, cat="Images", sub="Images/Photos"):
    st = os.stat(path)
    return dict(fid=fid, src=path, dir=os.path.dirname(path), name=os.path.basename(path), size=st.st_size, mtime=st.st_mtime,
                cat=cat, sub=sub)


class MoverTest(TempHomeCase):
    def run_job(self, ops, mode="move", label=""):
        job = jobs.Job("move", total=len(ops))
        mover.run(job, str(self.home / "Sorted"), mode, ops, label=label)
        return job

    def test_move_and_undo(self):
        a = self.make("Downloads/a.jpg", b"A" * 10)
        b = self.make("Downloads/b.jpg", b"B" * 20)
        job = self.run_job([op_for(a, 1), op_for(b, 2)])
        self.assertEqual(job.extra["moved"], 2)
        self.assertFalse(os.path.exists(a))
        self.assertTrue((self.home / "Sorted/Images/Photos/a.jpg").exists())
        self.assertEqual(job.extra["by_cat"]["Images"], dict(moved=2, bytes=30))
        self.assertEqual([c["name"] for c in job.extra["current"]], ["a.jpg", "b.jpg"])
        res = mover.undo(job.id)
        self.assertEqual(res, dict(restored=2, missing=0, replaced_restored=0))
        self.assertTrue(os.path.exists(a) and os.path.exists(b))
        self.assertFalse((self.home / "Sorted/Images").exists(), "empty folders created by the move are removed")
        with self.assertRaises(ValueError):
            mover.undo(job.id)

    def test_never_overwrites(self):
        self.make("Sorted/Images/Photos/a.jpg", b"existing")
        a = self.make("Downloads/a.jpg", b"new")
        self.run_job([op_for(a, 1)])
        self.assertEqual((self.home / "Sorted/Images/Photos/a.jpg").read_bytes(), b"existing")
        self.assertEqual((self.home / "Sorted/Images/Photos/a (1).jpg").read_bytes(), b"new")

    def test_changed_since_scan_is_skipped(self):
        a = self.make("Downloads/a.jpg", b"v1")
        op = op_for(a, 1)
        time.sleep(0.01)
        with open(a, "ab") as f:
            f.write(b"edited")
        job = self.run_job([op])
        self.assertEqual(job.extra["skipped"], 1)
        self.assertTrue(os.path.exists(a))
        self.assertIn("changed since the scan", job.errors[0])

    def test_copy_keeps_original_and_cannot_be_undone(self):
        a = self.make("Downloads/a.pdf", b"%PDF")
        job = self.run_job([op_for(a, 1, "PDFs", "PDFs")], mode="copy")
        self.assertTrue(os.path.exists(a))
        self.assertTrue((self.home / "Sorted/PDFs/a.pdf").exists())
        with self.assertRaises(ValueError):
            mover.undo(job.id)

    def test_subfolder_cannot_escape_destination(self):
        a = self.make("Downloads/a.jpg", b"A")
        self.run_job([op_for(a, 1, sub="../../evil")])
        self.assertTrue((self.home / "Sorted/evil/a.jpg").exists())
        self.assertFalse((self.home / "evil").exists())

    def test_manifest_and_history(self):
        a = self.make("Downloads/a.jpg", b"A")
        job = self.run_job([op_for(a, 1)])
        entry = history.entries()[0]
        self.assertEqual((entry["id"], entry["kind"], entry["count"], entry["undoable"]), (job.id, "move", 1, True))

    def test_quarantine_is_undoable(self):
        a = self.make("Downloads/broken.jpg", b"\xff\xd8 cut")
        job = self.run_job([op_for(a, 1, sub="Corrupted/JPEG_NO_EOI")], label="quarantine")
        self.assertEqual(history.load(job.id)["kind"], "quarantine")
        self.assertEqual(mover.undo(job.id)["restored"], 1)
        self.assertTrue(os.path.exists(a))

    def test_symlinked_source_is_refused(self):
        real = self.make("real/a.jpg", b"A")
        link_dir = self.home / "Downloads"
        link_dir.mkdir(exist_ok=True)
        try:
            os.symlink(real, str(link_dir / "a.jpg"))
        except (OSError, NotImplementedError):
            self.skipTest("creating symlinks needs extra privileges here")
        job = self.run_job([op_for(str(link_dir / "a.jpg"), 1)])
        self.assertEqual(job.extra["moved"], 0)
        self.assertTrue(os.path.exists(real))


class HistoryTest(TempHomeCase):
    def test_legacy_history_is_imported_once(self):
        legacy = self.home / ".old-app" / "history"
        legacy.mkdir(parents=True)
        (legacy / "20240101-120000-abcd.json").write_text(
            '{"id": "20240101-120000-abcd", "time": 1, "dest": "x", "mode": "copy", "undone": false, "ops": [{"src": "a", "dst": "b", "size": 5}]}')
        self.assertEqual(history.migrate_legacy(), 1)
        self.assertEqual(history.migrate_legacy(), 0)
        e = history.entries()[0]
        self.assertEqual((e["kind"], e["imported"], e["size"]), ("copy", True, 5))
        self.assertTrue((legacy / "20240101-120000-abcd.json").exists(), "originals are left untouched")

    def test_ids_are_sanitised(self):
        with self.assertRaises(ValueError):
            history.load("../../etc/passwd")


if __name__ == "__main__":
    unittest.main()
