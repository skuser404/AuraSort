"""Phase D: 'a file with this name already exists' (like the Windows copy dialog), through the real HTTP API."""
import json
import os
import stat
import time
import unittest

from tests.test_web_security import ServerCase
from core import apptrash, config, index_db, jobs, scanner


class ClashCase(ServerCase):
    def setUp(self):
        super().setUp()
        from core import web
        web._RATE.clear()
        self.dest = self.home / "Sorted"
        self.dest.mkdir()

    def call(self, path, body=None):
        st, _, raw = self.req(path, body)
        return st, json.loads(raw or b"{}")

    def index(self, folder):
        job = scanner.start("deep", [str(self.home / folder)], [])
        while job.state in ("running", "paused"):
            time.sleep(0.02)
        return {r["name"]: r["id"] for r in index_db.files_page({"scope": "all"}, per=500)["rows"]}

    def run_job(self, body):
        st, r = self.call("/api/execute", body)
        self.assertEqual(st, 200, r)
        job = jobs.get(r["job"])
        while job.state in ("running", "paused"):
            time.sleep(0.02)
        return job, r

    def body(self, ids, **kw):
        return dict(dict(ids=ids, dest=str(self.dest), mode="move", layout="here"), **kw)


class PreviewTest(ClashCase):
    def test_clashes_listed_with_identical_flag_and_within_selection(self):
        self.make("In/same.txt", b"hello")
        self.make("In/diff.txt", b"new version")
        self.make("In/fresh.txt", b"x")
        self.make("In/sub/same.txt", b"hello")        # a second same.txt in the selection (same content: order-independent)
        (self.dest / "same.txt").write_bytes(b"hello")
        (self.dest / "diff.txt").write_bytes(b"old")
        self.index("In")
        ids = [r["id"] for r in index_db.files_page({"scope": "all"}, per=500)["rows"]]   # both same.txt (a name map would merge them)
        st, c = self.call("/api/conflicts", self.body(ids))
        self.assertEqual(st, 200, c)
        names = {(r["name"], r["identical"], r["within_selection"]) for r in c["rows"]}
        self.assertIn(("same.txt", True, False), names)
        self.assertIn(("diff.txt", False, False), names)
        self.assertIn(("same.txt", None, True), names)
        self.assertEqual(c["total"], 3)
        self.assertEqual(c["identical"], 1)
        diff = next(r for r in c["rows"] if r["name"] == "diff.txt")
        self.assertEqual((diff["src"]["size"], diff["dst"]["size"]), (11, 3), "both sides, side by side")

    def test_no_destination_yet_means_no_clash(self):
        self.make("In/a.txt")
        ids = list(self.index("In").values())
        st, c = self.call("/api/conflicts", self.body(ids, dest=str(self.home / "NotYet")))
        self.assertEqual((st, c["total"]), (200, 0))


class ResolveTest(ClashCase):
    def test_skip_identical_keeps_both_otherwise_never_overwrites(self):
        self.make("In/same.txt", b"hello")
        self.make("In/diff.txt", b"new")
        (self.dest / "same.txt").write_bytes(b"hello")
        (self.dest / "diff.txt").write_bytes(b"old")
        ids = self.index("In")
        job, _ = self.run_job(self.body(list(ids.values()), conflicts={"action": "keep", "skip_identical": True}))
        self.assertEqual((job.extra["clash_skipped"], job.extra["clash_kept"]), (1, 1))
        self.assertTrue((self.home / "In" / "same.txt").exists(), "an identical file is skipped: it stays where it was")
        self.assertEqual((self.dest / "diff.txt").read_bytes(), b"old", "never overwritten")
        self.assertEqual((self.dest / "diff (1).txt").read_bytes(), b"new")

    def test_default_without_a_choice_is_keep_both(self):
        self.make("In/a.txt", b"new")
        (self.dest / "a.txt").write_bytes(b"old")
        job, _ = self.run_job(self.body(list(self.index("In").values())))
        self.assertEqual((self.dest / "a.txt").read_bytes(), b"old")
        self.assertEqual((self.dest / "a (1).txt").read_bytes(), b"new")

    def test_replace_then_undo_restores_both_files(self):
        self.make("In/report.pdf", b"NEW")
        (self.dest / "report.pdf").write_bytes(b"OLD")
        job, _ = self.run_job(self.body(list(self.index("In").values()), conflicts={"action": "replace"}))
        self.assertEqual(job.extra["replaced"], 1)
        self.assertEqual((self.dest / "report.pdf").read_bytes(), b"NEW")
        kept = apptrash.items()
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["reason"], "replaced")
        self.assertEqual(open(kept[0]["stored"], "rb").read(), b"OLD", "the replaced file is kept, not deleted")
        st, r = self.call("/api/undo", {"id": job.id})
        self.assertEqual(st, 200, r)
        self.assertEqual(r["replaced_restored"], 1)
        self.assertEqual((self.home / "In" / "report.pdf").read_bytes(), b"NEW", "the moved file is back")
        self.assertEqual((self.dest / "report.pdf").read_bytes(), b"OLD", "and the replaced one is back in its place")
        self.assertEqual(apptrash.items(), [])

    def test_apply_to_all_with_per_file_override(self):
        for n in ("a", "b", "c"):
            self.make(f"In/{n}.txt", b"new-" + n.encode())
            (self.dest / f"{n}.txt").write_bytes(b"old-" + n.encode())
        ids = self.index("In")
        job, _ = self.run_job(self.body(list(ids.values()), conflicts={"action": "skip", "per": {str(ids["b.txt"]): "replace", str(ids["c.txt"]): "keep"}}))
        self.assertEqual((self.dest / "a.txt").read_bytes(), b"old-a")
        self.assertTrue((self.home / "In" / "a.txt").exists())
        self.assertEqual((self.dest / "b.txt").read_bytes(), b"new-b")
        self.assertEqual((self.dest / "c.txt").read_bytes(), b"old-c")
        self.assertEqual((self.dest / "c (1).txt").read_bytes(), b"new-c")

    def test_read_only_destination_file(self):
        """Replace of a read-only file: either it is set aside (and restorable) or refused; never lost or overwritten."""
        self.make("In/ro.txt", b"NEW")
        ro = self.dest / "ro.txt"
        ro.write_bytes(b"OLD")
        os.chmod(ro, stat.S_IREAD)
        try:
            job, _ = self.run_job(self.body(list(self.index("In").values()), conflicts={"action": "replace"}))
            kept = [i for i in apptrash.items() if i["reason"] == "replaced"]
            if job.extra["replaced"]:
                self.assertEqual(open(kept[0]["stored"], "rb").read(), b"OLD")
                self.assertEqual(ro.read_bytes(), b"NEW")
            else:
                self.assertEqual(ro.read_bytes(), b"OLD")
                self.assertTrue((self.home / "In" / "ro.txt").exists(), "refused: the source stays")
                self.assertEqual(job.extra["skipped"], 1)
        finally:
            for p in [ro] + [__import__("pathlib").Path(i["stored"]) for i in apptrash.items()]:
                if p.exists():
                    os.chmod(p, stat.S_IWRITE | stat.S_IREAD)

    def test_a_file_written_by_this_batch_is_never_replaced(self):
        self.make("In/x/photo.jpg", b"first")
        self.make("In/y/photo.jpg", b"second")
        self.index("In")
        all_ids = [r["id"] for r in index_db.files_page({"scope": "all"}, per=500)["rows"]]
        job, _ = self.run_job(self.body(all_ids, conflicts={"action": "replace"}))
        got = sorted(p.read_bytes() for p in self.dest.iterdir() if p.is_file())
        self.assertEqual(got, [b"first", b"second"], "both arrive; the second keeps both instead of replacing the first")
        self.assertEqual(job.extra["replaced"], 0)

    def test_copy_replace(self):
        self.make("In/c.txt", b"NEW")
        (self.dest / "c.txt").write_bytes(b"OLD")
        job, _ = self.run_job(self.body(list(self.index("In").values()), mode="copy", conflicts={"action": "replace"}))
        self.assertEqual((self.dest / "c.txt").read_bytes(), b"NEW")
        self.assertTrue((self.home / "In" / "c.txt").exists(), "a copy leaves the original")
        self.assertEqual(open(apptrash.items()[0]["stored"], "rb").read(), b"OLD")

    def test_quarantine_uses_the_same_rules(self):
        from core import settings
        settings.update(dest=str(self.home / "Sorted"))
        q = self.dest / "Quarantine"
        q.mkdir()
        (q / "broken.zip").write_bytes(b"older broken")
        self.make("In/broken.zip", b"PK broken")
        ids = list(self.index("In").values())
        st, c = self.call("/api/conflicts", {"ids": ids, "kind": "quarantine"})
        self.assertEqual(c["total"], 1)
        st, r = self.call("/api/quarantine", {"ids": ids, "conflicts": {"action": "skip"}})
        self.assertEqual(st, 200, r)
        job = jobs.get(r["job"])
        while job.state in ("running", "paused"):
            time.sleep(0.02)
        self.assertEqual((q / "broken.zip").read_bytes(), b"older broken")
        self.assertEqual(job.extra["clash_skipped"], 1)

    def test_bad_choices_are_refused(self):
        self.make("In/a.txt")
        ids = list(self.index("In").values())
        for bad in ({"action": "overwrite"}, {"action": "keep", "per": {"x": "keep"}}, {"action": "keep", "per": {"1": "delete"}}, "replace"):
            st, r = self.call("/api/execute", self.body(ids, conflicts=bad))
            self.assertEqual(st, 400, bad)


class AppTrashTest(ClashCase):
    def test_restore_never_overwrites_and_purge_is_opt_in(self):
        f = self.make("Docs/a.txt", b"one")
        rec = apptrash.put(f, "deleted")
        self.assertFalse(os.path.exists(f))
        self.assertIn(config.APPTRASH_DIR_NAME, rec["stored"])
        self.make("Docs/a.txt", b"someone made a new one")
        st, r = self.call("/api/apptrash/restore", {"id": rec["id"]})
        self.assertEqual(st, 200, r)
        self.assertTrue(r["path"].endswith("a (1).txt"))
        self.assertEqual((self.home / "Docs" / "a.txt").read_bytes(), b"someone made a new one")
        g = self.make("Docs/b.txt", b"two")
        rec = apptrash.put(g, "deleted")
        self.assertEqual(apptrash.purge_old(), 0, "the purge timer is off by default")
        items = json.loads((config.DATA_DIR / config.APPTRASH_INDEX).read_text(encoding="utf-8"))
        items[0]["time"] = 0
        (config.DATA_DIR / config.APPTRASH_INDEX).write_text(json.dumps(items), encoding="utf-8")
        self.assertEqual(apptrash.purge_old(days=30), 1)
        self.assertFalse(os.path.exists(rec["stored"]))

    def test_trash_folder_is_never_scanned_or_moved(self):
        from core import safety
        f = self.make("Docs/c.txt", b"x")
        rec = apptrash.put(f, "deleted")
        self.assertTrue(safety.is_protected(os.path.dirname(os.path.dirname(rec["stored"]))))
        self.make("Docs/visible.txt")
        names = self.index("Docs")
        self.assertNotIn("c.txt", names)


if __name__ == "__main__":
    unittest.main()
