"""Android (Termux): scanning worked but Move/Copy did nothing. Android's shared storage (/storage/emulated/0, a FUSE
file system) refuses hard links and changing file dates/permissions. The copy engine used a hard link to place every
verified copy without overwriting, and copied the dates with shutil.copystat: both raised PermissionError, so every
copy (and every move between storages) failed. Simulated here: the same refusals on a fake /storage/emulated/0 tree,
driven through the same API calls the Sort & move screen makes."""
import errno
import json
import os
import shutil
import time
from unittest import mock

from tests.test_web_security import ServerCase
from core import config, copier, history, index_db, jobs, platform_utils, scanner

_link, _copystat = os.link, shutil.copystat


class AndroidMoveCase(ServerCase):
    def setUp(self):
        super().setUp()
        from core import web
        web._RATE.clear()
        self.storage = self.home / "fake" / "storage" / "emulated" / "0"
        self.src = self.storage / "DCIM" / "Camera"
        self.src.mkdir(parents=True)
        for i in range(5):
            (self.src / f"IMG_{i:04d}.jpg").write_bytes(b"\xff\xd8\xff" + bytes([i]) * (100 + i))
        storage = str(self.storage)
        marker = os.path.normcase(os.path.join("fake", "storage", "emulated"))
        on_storage = lambda p: marker in os.path.normcase(str(p))   # any spelling of the path (8.3 short name, long path, real path)

        def no_link(a, b, *k, **kw):   # FUSE shared storage: hard links are not allowed
            if on_storage(a) or on_storage(b):
                raise PermissionError(errno.EPERM, "Operation not permitted")
            return _link(a, b, *k, **kw)

        def no_copystat(a, b, *k, **kw):   # FUSE shared storage: dates and permissions cannot be set
            if on_storage(b):
                raise PermissionError(errno.EPERM, "Operation not permitted")
            return _copystat(a, b, *k, **kw)
        patches = [mock.patch.object(config, "ANDROID", True), mock.patch.object(platform_utils, "ANDROID", True),
                   mock.patch.object(platform_utils, "ANDROID_STORAGE", storage), mock.patch.object(config, "WIN", False),
                   mock.patch("os.link", no_link), mock.patch("shutil.copystat", no_copystat)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        job = scanner.start("quick", [], [])
        while job.state in ("running", "paused"):
            time.sleep(0.02)
        self.ids = [r["id"] for r in index_db.files_page({"scope": "all"})["rows"]]
        self.assertEqual(len(self.ids), 5)
        self.dest = self.storage / "Sorted" / "Images"

    def run_job(self, mode, **extra):
        """What the Sort & move screen sends after you pick the destination (the PIN token is added like the UI does)."""
        body = dict(ids=self.ids, dest=str(self.dest), mode=mode, layout="here", **extra)
        st, _, raw = self.req("/api/execute", body)
        r = json.loads(raw)
        self.assertEqual(st, 200, r)
        j = jobs.get(r["job"])
        while j.state in ("running", "paused"):
            time.sleep(0.02)
        return j


class AndroidMoveCopyTest(AndroidMoveCase):
    def test_copy_into_shared_storage(self):
        j = self.run_job("copy")
        self.assertEqual(j.extra["skipped"], 0, j.errors)
        self.assertEqual(sorted(os.listdir(self.dest)), [f"IMG_{i:04d}.jpg" for i in range(5)])
        self.assertEqual(len(os.listdir(self.src)), 5, "a copy leaves the originals")
        self.assertEqual((self.dest / "IMG_0003.jpg").read_bytes(), (self.src / "IMG_0003.jpg").read_bytes())

    def test_move_and_undo(self):
        j = self.run_job("move")
        self.assertEqual(j.extra["skipped"], 0, j.errors)
        self.assertEqual(len(os.listdir(self.dest)), 5)
        self.assertEqual(os.listdir(self.src), [], "moved, not copied")
        self.assertTrue(any(h.get("id") == j.id for h in history.entries(10)), "History has the move")
        st, _, raw = self.req("/api/undo", {"id": j.id})
        self.assertEqual(st, 200, raw)
        self.assertEqual(len(os.listdir(self.src)), 5, "Undo puts every file back")

    def test_move_across_storages_is_a_verified_copy(self):
        """Termux home -> shared storage is two file systems: copy, verify, then remove the original."""
        from core import mover
        other = lambda p: 1 if "DCIM" in str(p) else 2   # the photos and the destination on two different file systems
        with mock.patch.object(copier, "same_volume", return_value=False), mock.patch.object(mover, "device", side_effect=other):
            j = self.run_job("move")
        self.assertEqual(j.extra["skipped"], 0, j.errors)
        self.assertEqual(len(os.listdir(self.dest)), 5)
        self.assertEqual(os.listdir(self.src), [])

    def test_name_clash_in_shared_storage(self):
        self.dest.mkdir(parents=True)
        (self.dest / "IMG_0001.jpg").write_bytes(b"an older photo")
        st, _, raw = self.req("/api/conflicts", dict(ids=self.ids, dest=str(self.dest), mode="copy", layout="here"))
        self.assertEqual(json.loads(raw)["total"], 1)
        j = self.run_job("copy", conflicts={"action": "keep"})
        self.assertEqual(j.extra["skipped"], 0, j.errors)
        self.assertTrue((self.dest / "IMG_0001 (1).jpg").exists())
        self.assertEqual((self.dest / "IMG_0001.jpg").read_bytes(), b"an older photo", "never overwritten")

    def test_default_destination_is_in_shared_storage(self):
        """The Termux home is private to Termux: files sorted there vanish from the Gallery and with the app."""
        self.assertTrue(platform_utils.default_destination().startswith(str(self.storage)), platform_utils.default_destination())
