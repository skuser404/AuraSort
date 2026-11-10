"""Corrupted files (Integrity Check job, results, CSV, drive hint, quarantine), duplicates (staged hashing) and cleanup rules."""
import json
import os
import time
import unittest
from unittest import mock

from tests import fixtures as fx
from tests.test_web_security import ServerCase
from core import checks, config, history, index_db, jobs, scanner, web


class ChecksCase(ServerCase):
    def setUp(self):
        super().setUp()
        web._RATE.clear()

    def scan(self, files, old=()):
        for rel, data in files:
            p = self.make(rel, data)
            if rel in old:
                os.utime(p, (time.time() - 90 * 86400,) * 2)
        job = scanner.start("deep", [str(self.home / "Lib")], [])
        while job.state in ("running", "paused"):
            time.sleep(0.02)
        return {r["name"]: r for r in index_db.files_page({"scope": "all"}, per=500)["rows"]}

    def post(self, path, body):
        st, _, raw = self.req(path, body)
        return st, json.loads(raw or b"{}")

    def get(self, path):
        st, _, raw = self.req(path)
        self.assertEqual(st, 200, raw)
        return json.loads(raw)

    def wait(self, jid):
        j = jobs.get(jid)
        while j.state in ("running", "paused"):
            time.sleep(0.02)
        return j.snapshot()


class IntegrityTest(ChecksCase):
    def test_finds_broken_files_with_cause_and_fix(self):
        good = fx.jpeg()
        self.scan([("Lib/ok.png", fx.png()), ("Lib/bad.png", fx.png_bad_crc()), ("Lib/cut.jpg", good[:len(good) // 2]), ("Lib/empty.docx", b""),
                   ("Lib/zip.zip", fx.zip_bad_crc()), ("Lib/fake.png", fx.pdf()), ("Lib/note.txt", b"hello")])
        st, r = self.post("/api/integrity/start", {"mode": "deep"})
        self.assertEqual(self.wait(r["job"])["state"], "done")
        res = self.get("/api/integrity/results")
        by = {x["name"]: x["findings"][0] for x in res["rows"]}
        for n in ("bad.png", "cut.jpg", "empty.docx", "zip.zip"):
            self.assertIn(n, by)
            self.assertTrue(by[n]["cause"] and by[n]["fix"])
        self.assertEqual(by["fake.png"]["sev"], "warning", "extension mismatch is a warning, not corruption")
        self.assertNotIn("ok.png", by)
        self.assertEqual(res["rows"][0]["findings"][0]["sev"], "corrupted", "worst first")
        self.assertEqual(self.get("/api/integrity/results?sev=warning")["total"], 1)
        st, h, raw = self.req("/api/integrity/csv")
        self.assertIn("text/csv", h["Content-Type"])
        self.assertIn("attachment", h["Content-Disposition"])
        self.assertIn("bad.png", raw.decode())
        # a second (quick) run reuses the deep results instead of re-reading
        with mock.patch("core.integrity.check", side_effect=AssertionError("should be cached")):
            st, r = self.post("/api/integrity/start", {"mode": "quick"})
            self.assertEqual(self.wait(r["job"])["state"], "done")

    def test_drive_hint_only_when_one_drive_stands_out(self):
        self.scan([(f"Lib/bad/bad{i}.png", fx.png_bad_crc()) for i in range(6)] + [(f"Lib/good/ok{i}.png", fx.png()) for i in range(10)])
        self.wait(self.post("/api/integrity/start", {"mode": "deep"})[1]["job"])   # CRC damage is a deep-check finding
        self.assertEqual(self.get("/api/integrity/results")["summary"]["hint"], "", "one drive only: no misleading drive warning")
        with index_db.write_lock():   # pretend the healthy files live on a second drive
            index_db.writer().execute("UPDATE dirs SET drive='Z:\\' WHERE path LIKE ?", ("%good",))
            index_db.writer().commit()
        index_db.bump()
        self.assertIn("back it up", self.get("/api/integrity/results")["summary"]["hint"])

    def test_quarantine_is_an_undoable_move(self):
        rows = self.scan([("Lib/bad.png", fx.png_bad_crc())])
        st, r = self.post("/api/quarantine", {"ids": [rows["bad.png"]["id"]]})
        self.assertEqual(st, 200)
        self.wait(r["job"])
        self.assertTrue(os.path.exists(os.path.join(r["dest"], "bad.png")))
        entry = [e for e in history.entries() if e["id"] == r["job"]][0]
        self.assertEqual((entry["kind"], entry["undoable"]), ("quarantine", True))
        self.assertEqual(self.post("/api/undo", {"id": r["job"]})[1]["restored"], 1)


class DuplicatesTest(ChecksCase):
    def test_staged_hashing(self):
        same = os.urandom(200_000)
        head = os.urandom(100_000)
        a, b = head + b"A" * 100_000, head + b"B" * 100_000   # same size, same first 64 KB, different content
        self.scan([("Lib/one/photo.jpg", same), ("Lib/two/photo copy.jpg", same), ("Lib/three/photo (1).jpg", same),
                   ("Lib/x.bin", a), ("Lib/y.bin", b), ("Lib/unique.bin", os.urandom(1234)), ("Lib/e1.txt", b""), ("Lib/e2.txt", b"")])
        snap = self.wait(self.post("/api/duplicates/start", {})[1]["job"])
        self.assertEqual(snap["state"], "done")
        res = self.get("/api/duplicates/results")
        self.assertEqual(res["summary"]["groups"], 1, "same size and same start but different content is not a duplicate; empty files are never duplicates")
        g = res["groups"][0]
        self.assertEqual((g["n"], g["wasted"]), (3, 2 * len(same)))
        extras = self.get("/api/duplicates/extras")
        self.assertEqual(len(extras["ids"]), 2)
        self.assertNotIn(g["keep"], extras["ids"], "the newest copy is kept")


class CleanupTest(ChecksCase):
    def test_rules_and_projects(self):
        self.scan([("Lib/Downloads/old_setup.exe", fx.exe()), ("Lib/Downloads/new_setup.exe", fx.exe()), ("Lib/Downloads/movie.crdownload", b"x" * 100),
                   ("Lib/scratch.tmp", b"t"), ("Lib/blank.txt", b""), ("Lib/site/package.json", b"{}"), ("Lib/site/empty.txt", b"")],
                  old=("Lib/Downloads/old_setup.exe", "Lib/Downloads/movie.crdownload", "Lib/scratch.tmp"))
        groups = {g["key"]: g for g in self.get("/api/cleanup")["groups"]}
        self.assertEqual(groups["installers"]["n"], 1, "only installers older than the limit")
        self.assertEqual(groups["partial"]["n"], 1)
        self.assertEqual(groups["temp"]["n"], 1)
        self.assertEqual(groups["empty"]["n"], 1, "the empty file inside a project folder is left out")
        names = [r["name"] for r in self.get("/api/cleanup?reason=installers")["rows"]]
        self.assertEqual(names, ["old_setup.exe"])
        self.assertEqual(self.req("/api/cleanup?reason=everything")[0], 400)


if __name__ == "__main__":
    unittest.main()
