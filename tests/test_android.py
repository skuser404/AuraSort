"""Phase F: AuraSort on Android (Termux), simulated on a desktop: no real phone is used in these tests.
What is checked: the phone's folders for Quick Scan, deleting into AuraSort's own trash (Android has no Recycle Bin)
with Restore, Android's protected folders, and the server running without any Windows-only call."""
import os
import time
from unittest import mock

from tests.test_web_security import ServerCase
from tests.base import TempHomeCase
from core import apptrash, config, index_db, jobs, platform_utils, safety, scanner, trash


class AndroidCase(TempHomeCase):
    def setUp(self):
        super().setUp()
        self.storage = self.tmp / "storage" / "emulated" / "0"
        for d in ("Download", "DCIM", "Pictures", "Documents", "Movies", "Music"):
            (self.storage / d).mkdir(parents=True)
        p = [mock.patch.object(config, "ANDROID", True), mock.patch.object(platform_utils, "ANDROID", True),
             mock.patch.object(platform_utils, "ANDROID_STORAGE", str(self.storage))]
        for x in p:
            x.start()
            self.addCleanup(x.stop)


class AndroidFoldersTest(AndroidCase):
    def test_quick_scan_uses_the_phone_storage(self):
        q = {x["name"]: x for x in platform_utils.quick_folders()}
        self.assertEqual(q["Downloads"]["path"], str(self.storage / "Download"))
        self.assertEqual(q["Camera"]["path"], str(self.storage / "DCIM"))
        self.assertTrue(all(x["exists"] for x in q.values()))

    def test_protected_android_folders(self):
        saved = safety._PREFIXES
        try:
            safety._PREFIXES = None
            with mock.patch.dict(os.environ, {"PREFIX": "/data/data/com.termux/files/usr"}):
                prefixes = safety.protected_prefixes()
            for p in ("/system", "/data/data/com.termux/files/usr", "/storage/emulated/0/Android"):
                self.assertIn(p, prefixes)
        finally:
            safety._PREFIXES = saved


class AndroidTrashTest(AndroidCase):
    def test_delete_goes_to_the_aurasort_trash_and_can_be_restored(self):
        f = self.storage / "Download" / "song.mp3"
        f.write_bytes(b"ID3 song")
        with mock.patch.dict(os.environ, {trash.TEST_TRASH_ENV: ""}):
            self.assertTrue(trash.bin_available(str(f)))
            res = trash.send_to_trash([str(f)])
        self.assertEqual(res.trashed, [str(f)])
        self.assertFalse(f.exists())
        items = apptrash.items()
        self.assertEqual(len(items), 1)
        self.assertIn(config.APPTRASH_DIR_NAME, items[0]["stored"])
        self.assertTrue(os.path.exists(items[0]["stored"]), "moved, not deleted")
        self.assertEqual(apptrash.restore(items[0]["id"]), str(f))
        self.assertEqual(f.read_bytes(), b"ID3 song")
        self.assertIn("AuraSort trash", trash.where_name())


class AndroidServerTest(ServerCase):
    def test_server_runs_and_scans_with_android_flags(self):
        storage = self.home / "storage"
        (storage / "Download").mkdir(parents=True)
        (storage / "Download" / "a.jpg").write_bytes(b"\xff\xd8\xff")
        with mock.patch.object(config, "ANDROID", True), mock.patch.object(platform_utils, "ANDROID", True), \
                mock.patch.object(platform_utils, "ANDROID_STORAGE", str(storage)):
            import json
            st, _, raw = self.req("/api/info")
            info = json.loads(raw)
            self.assertEqual(st, 200)
            self.assertTrue(info["apptrash"])
            st, _, raw = self.req("/api/drives")
            self.assertEqual(st, 200)
            self.assertEqual(json.loads(raw)[0]["name"], "Phone storage")
            job = scanner.start("quick", [], [])
            while job.state in ("running", "paused"):
                time.sleep(0.02)
            self.assertEqual(job.state, "done")
            self.assertEqual(index_db.summary()["total"], 1)
