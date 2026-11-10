"""The verified copy engine and crash safety: pin-to-pin copies, verification failures, full disks, locked files, cancel,
name clashes, long paths, the job journal with Resume / Clean up, the free-space check, duplicates and cloud placeholders."""
import errno
import json
import os
import time
import unittest
from unittest import mock

from tests import fixtures as fx
from tests.base import TempHomeCase
from tests.test_web_security import ServerCase
from core import config, copier, history, index_db, jobs, platform_utils, scanner, trash, web


class CopierTest(TempHomeCase):
    def src(self, name="a.bin", data=None):
        p = self.make("src/" + name, data if data is not None else os.urandom(300_000))
        os.utime(p, (1_600_000_000, 1_600_000_000))
        return p

    def dest(self):
        d = self.home / "dst"
        d.mkdir(exist_ok=True)
        return str(d)

    def parts(self, d):
        return [f for f in os.listdir(d) if f.endswith(copier.PART_SUFFIX)]

    def test_full_verified_copy_and_move(self):
        s, d = self.src(), self.dest()
        out = copier.copy_verified(s, d, "a.bin", "full")
        self.assertEqual(open(out, "rb").read(), open(s, "rb").read())
        self.assertEqual(int(os.path.getmtime(out)), 1_600_000_000, "timestamps preserved")
        self.assertEqual(self.parts(d), [])
        out2 = copier.copy_verified(s, d, "a.bin", "fast", move=True)
        self.assertTrue(out2.endswith("a (1).bin"), "never over an existing file")
        self.assertFalse(os.path.exists(s), "a move removes the source only after verification")

    def test_mismatch_keeps_the_source(self):
        s, d = self.src(), self.dest()
        with mock.patch.object(copier, "verify", return_value=False):
            with self.assertRaises(copier.CopyError):
                copier.copy_verified(s, d, "a.bin", "full", move=True)
        self.assertTrue(os.path.exists(s))
        self.assertEqual(os.listdir(d), [], "no final file, no partial file")

    def test_disk_full_and_locked_files(self):
        s, d = self.src(), self.dest()
        full = OSError(errno.ENOSPC, "No space left on device")
        with mock.patch.object(copier, "_raw_copy", side_effect=full):
            with self.assertRaises(copier.DiskFull):
                copier.copy_verified(s, d, "a.bin", move=True)
        self.assertTrue(os.path.exists(s))
        locked = OSError(None, "in use", s, 32)
        locked.winerror = 32
        real, calls = copier._raw_copy, []

        def flaky(*a):
            calls.append(1)
            if len(calls) < 3:
                raise locked
            return real(*a)
        with mock.patch.object(copier, "_raw_copy", side_effect=flaky):
            out = copier.copy_verified(s, d, "a.bin", sleep=lambda _s: None)
        self.assertTrue(os.path.exists(out) and len(calls) == 3, "locked files are retried with backoff")
        with mock.patch.object(copier, "_raw_copy", side_effect=locked):
            with self.assertRaisesRegex(copier.CopyError, "in use"):
                copier.copy_verified(s, d, "b.bin", sleep=lambda _s: None)
        self.assertEqual(self.parts(d), [])

    def test_cancel_and_fast_verify(self):
        s, d = self.src(data=os.urandom(5 * 1024 * 1024)), self.dest()
        with self.assertRaises(copier.CopyError):
            copier._buffered_copy(s, os.path.join(d, "x" + copier.PART_SUFFIX), None, lambda: True)
        a, b = self.src("p.bin", b"A" * 2_000_000), self.src("q.bin", b"B" + b"A" * 1_999_999)
        self.assertNotEqual(copier.sampled_hash(a, 2_000_000), copier.sampled_hash(b, 2_000_000))

    @unittest.skipUnless(config.WIN, "Windows long paths")
    def test_long_paths(self):
        p = "C:\\" + "x" * 250 + "\\file.txt"
        self.assertTrue(copier.long_path(p).startswith("\\\\?\\C:\\"))
        self.assertEqual(copier.long_path("C:\\short.txt"), "C:\\short.txt")

    def test_drive_media_is_known(self):
        self.assertIn(platform_utils.drive_media(platform_utils.drive_of(str(self.home))), config.SCAN_WORKERS)


class JobsTest(ServerCase):
    def setUp(self):
        super().setUp()
        web._RATE.clear()
        self._env = mock.patch.dict(os.environ, {trash.TEST_TRASH_ENV: str(self.tmp / "bin")})
        self._env.start()

    def tearDown(self):
        self._env.stop()
        super().tearDown()

    def scan(self, files):
        for rel, data in files:
            self.make(rel, data)
        job = scanner.start("deep", [str(self.home / "Lib")], [])
        while job.state in ("running", "paused"):
            time.sleep(0.02)
        return {r["name"]: r for r in index_db.files_page({"scope": "all"}, per=500)["rows"]}

    def post(self, path, body):
        st, _, raw = self.req(path, body)
        return st, json.loads(raw or b"{}")

    def wait(self, jid):
        j = jobs.get(jid)
        while j.state in ("running", "paused"):
            time.sleep(0.02)
        return j.snapshot()

    def test_copy_is_verified_and_duplicates_count_once(self):
        rows = self.scan([("Lib/a.png", fx.png()), ("Lib/b.pdf", fx.pdf())])
        ids = [rows["a.png"]["id"], rows["b.pdf"]["id"], rows["a.png"]["id"]]
        st, r = self.post("/api/execute", {"ids": ids, "dest": str(self.home / "Out"), "mode": "copy", "layout": "here"})
        self.assertEqual(st, 200)
        snap = self.wait(r["job"])
        self.assertEqual((snap["moved"], snap["verified"]), (2, 2), "same file selected twice is copied once; every copy verified")
        m = history.load(r["job"])
        self.assertEqual((m["state"], len(m["plan"])), ("done", 2), "the journal lists the plan and ends 'done'")

    def test_free_space_check(self):
        rows = self.scan([("Lib/a.png", fx.png())])
        fake = mock.Mock(free=10, total=100, used=90)
        with mock.patch("server.shutil.disk_usage", return_value=fake):
            st, r = self.post("/api/execute", {"ids": [rows["a.png"]["id"]], "dest": str(self.home / "Out"), "mode": "copy"})
        self.assertEqual(st, 400)
        self.assertIn("Not enough free space", r["error"])

    def test_interrupted_job_resume_and_cleanup(self):
        rows = self.scan([("Lib/a.png", fx.png()), ("Lib/b.png", fx.png(6, 6))])
        out = self.home / "Out"
        out.mkdir()
        (out / ("a.png" + copier.PART_SUFFIX)).write_bytes(b"half")   # a partial copy left by a crash
        plan = [dict(fid=r["id"], src=os.path.join(r["path"], r["name"]), dir=r["path"], name=r["name"], size=r["size"], mtime=r["mtime"], cat=r["cat"], sub="")
                for r in rows.values()]
        history.save(dict(id="20250101-000000-crash", kind="move", mode="move", dest=str(out), time=1, ops=[], plan=plan, state="running", verify="full"))
        self.assertEqual(history.mark_interrupted(), 1)
        st, _, raw = self.req("/api/interrupted")
        info = json.loads(raw)[0]
        self.assertEqual((info["left"], info["parts"]), (2, 1))
        st, r = self.post("/api/interrupted/resume", {"id": "20250101-000000-crash"})
        self.assertEqual((st, r["count"]), (200, 2))
        self.wait(r["job"])
        self.assertEqual(sorted(os.listdir(out)), ["a.png", "b.png"], "resumed; the old partial file went to the bin")
        self.assertTrue((self.tmp / "bin").exists())
        self.assertEqual(history.load("20250101-000000-crash")["state"], "resumed")

    def test_cloud_placeholders_are_never_read(self):
        rows = self.scan([("Lib/cloud.png", fx.png())])
        fid = rows["cloud.png"]["id"]
        with index_db.write_lock():
            index_db.writer().execute("UPDATE files SET flags = flags | ? WHERE id=?", (index_db.FLAG_CLOUD, fid))
            index_db.writer().commit()
        index_db.bump()
        st, _, raw = self.req(f"/api/preview?id={fid}")
        d = json.loads(raw)
        self.assertEqual(d["kind"], "cloud")
        self.assertNotIn("thumb", d["file"], "no thumbnail would download it")
        st, r = self.post("/api/execute", {"ids": [fid], "dest": str(self.home / "Out"), "mode": "copy"})
        snap = self.wait(r["job"])
        self.assertEqual((snap["moved"], snap["skipped"]), (0, 1))
        self.assertIn("online-only", snap["errors"][0])


class ScanMediaTest(TempHomeCase):
    def test_scan_reports_drive_media(self):
        self.make("Lib/a.txt", b"x")
        job = scanner.start("deep", [str(self.home / "Lib")], [])
        while job.state in ("running", "paused"):
            time.sleep(0.02)
        self.assertTrue(set(job.extra.get("media", {}).values()) <= set(config.SCAN_WORKERS))



if __name__ == "__main__":
    unittest.main()
