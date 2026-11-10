"""Scanner + SQLite index: what gets indexed, project/asset defaults, pagination, filters, incremental re-scan, cancel."""
import os
import time
import unittest

from tests import fixtures as fx
from tests.base import TempHomeCase
from core import classify, dates, index_db, jobs, scanner, settings


def wait(job, timeout=30):
    t0 = time.time()
    while job.state in ("running", "paused") and time.time() - t0 < timeout:
        time.sleep(0.02)
    return job


class ScannerTest(TempHomeCase):
    def build(self):
        h = self.home
        self.make("Downloads/IMG_2031.jpg", fx.jpeg())
        self.make("Downloads/Spotlight.png", fx.png())
        self.make("Downloads/report.pdf", fx.pdf())
        self.make("Downloads/setup.exe", fx.exe())
        self.make("Downloads/script.py", b"print(1)")
        self.make("Downloads/movie.mp4.part", b"partial")
        self.make("Downloads/mystery.qqq", b"?")
        self.make("Downloads/.DS_Store", b"x")
        self.make("Downloads/._IMG_2031.jpg", b"x")
        self.make("Web/package.json", b"{}")
        self.make("Web/img/logo.png", fx.png())
        self.make("Photos/assets/icon.png", fx.png())
        self.make("Photos/node_modules/pkg/a.png", fx.png())
        self.make("Photos/.hidden/a.png", fx.png())
        self.make("Skipme/a.jpg", fx.jpeg())
        self.make("Tools.app/Contents/MacOS/bin", b"\x00" * 1000)
        for i in range(250):
            self.make(f"Many/pic_{i:03d}.jpg", b"j" * (i + 1))
        old = time.mktime((2024, 3, 15, 12, 0, 0, 0, 0, -1))
        os.utime(h / "Downloads/report.pdf", (old, old))

    def scan(self, skip=()):
        job = wait(scanner.start("deep", [str(self.home)], [str(self.home / s) for s in skip]))
        self.assertEqual(job.state, "done", job.errors)
        return job

    def test_index_contents_and_defaults(self):
        self.build()
        self.scan(skip=["Skipme"])
        s = index_db.summary()
        self.assertEqual(list(s["by_cat"]), list(classify.CATEGORY_NAMES), "all categories present, in order")
        self.assertEqual(s["by_cat"]["Fonts"]["n"], 0, "empty categories are still listed (as 0)")
        names = {r["name"] for r in index_db.files_page({"scope": "all"}, per=500)["rows"]}
        for expected in ("IMG_2031.jpg", "setup.exe", "script.py", "movie.mp4.part", "mystery.qqq", "logo.png", "icon.png", "Tools.app"):
            self.assertIn(expected, names)
        for excluded in (".DS_Store", "._IMG_2031.jpg", "a.png", "a.jpg", "bin"):
            self.assertNotIn(excluded, names, excluded)
        rows = {r["name"]: r for r in index_db.files_page({"scope": "all"}, per=500)["rows"]}
        self.assertEqual(rows["logo.png"]["kind"], "project")
        self.assertFalse(rows["logo.png"]["included"])
        self.assertEqual(rows["icon.png"]["kind"], "assets")
        self.assertFalse(rows["icon.png"]["included"])
        self.assertTrue(rows["IMG_2031.jpg"]["included"])
        self.assertEqual(rows["Tools.app"]["flags"] & index_db.FLAG_BUNDLE, index_db.FLAG_BUNDLE)
        self.assertEqual(rows["Tools.app"]["size"], 1000)
        self.assertTrue(rows["setup.exe"]["viewonly"] and rows["mystery.qqq"]["cat"] == "Other")
        self.assertEqual(rows["movie.mp4.part"]["flags"] & index_db.FLAG_PARTIAL, index_db.FLAG_PARTIAL)
        self.assertEqual(s["total"], len(names))
        self.assertEqual(s["ready"], sum(1 for r in rows.values() if r["included"] and not r["viewonly"]))

    def test_pagination_filters_and_facets(self):
        self.build()
        self.scan(skip=["Skipme"])
        page1 = index_db.files_page({"cat": "Images", "scope": "all"}, "size", 1, 100)
        self.assertEqual((page1["per"], len(page1["rows"]), page1["pages"]), (100, 100, 3))
        self.assertGreaterEqual(page1["rows"][0]["size"], page1["rows"][-1]["size"])
        page3 = index_db.files_page({"cat": "Images", "scope": "all"}, "size", 3, 100)
        self.assertEqual(len(page3["rows"]), page1["total"] - 200)
        self.assertEqual(index_db.files_page({"exts": ["png"], "scope": "all"})["total"], 3)
        self.assertEqual(index_db.files_page({"q": "spot", "scope": "all"})["rows"][0]["name"], "Spotlight.png")
        self.assertEqual(index_db.files_page({"q": "%", "scope": "all"})["total"], 0, "LIKE wildcards are escaped")
        self.assertEqual(index_db.files_page({"folder": "many", "scope": "all"})["total"], 250)
        fac = index_db.facets({"cat": "Images", "exts": ["png"], "scope": "all"})
        self.assertEqual(dict(fac["ext"])["jpg"], 251, "format facets ignore the format filter itself")
        lo, hi = dates.range_for("on", "2024-03-15")
        hit = index_db.files_page({"dfrom": lo, "dto": hi, "scope": "all"})
        self.assertEqual([r["name"] for r in hit["rows"]], ["report.pdf"])
        ids, sizes = index_db.ids_for({"folder": "many", "scope": "all"})
        self.assertEqual((len(ids), sum(sizes)), (250, sum(range(1, 251))))
        ext = {e["ext"]: e for e in index_db.extensions()}
        self.assertEqual((ext["jpg"]["n"], ext["jpg"]["cat"]), (251, "Images"))

    def test_incremental_rescan_keeps_ids_and_prunes(self):
        self.build()
        self.scan()
        before = {r["name"]: r["id"] for r in index_db.files_page({"scope": "all"}, per=500)["rows"]}
        os.remove(self.home / "Downloads/Spotlight.png")
        self.make("Downloads/new.gif", fx.gif())
        self.scan()
        after = {r["name"]: r["id"] for r in index_db.files_page({"scope": "all"}, per=500)["rows"]}
        self.assertNotIn("Spotlight.png", after)
        self.assertIn("new.gif", after)
        self.assertEqual(before["IMG_2031.jpg"], after["IMG_2031.jpg"], "unchanged files keep their id")

    def test_folder_include_toggles(self):
        self.build()
        self.scan()
        web = [d for d in index_db.folders() if d["kind"] == "project"][0]
        index_db.set_included(ids=[web["id"]], value=True)
        self.assertTrue([d for d in index_db.folders() if d["id"] == web["id"]][0]["included"])
        index_db.set_included(preset="safe")
        self.assertFalse([d for d in index_db.folders() if d["id"] == web["id"]][0]["included"])

    def test_record_move_updates_lists(self):
        self.build()
        self.scan()
        row = index_db.files_page({"q": "spotlight", "scope": "all"})["rows"][0]
        new = str(self.home / "Sorted" / "Images" / "Spotlight.png")
        os.makedirs(os.path.dirname(new))
        os.replace(os.path.join(row["path"], row["name"]), new)
        index_db.record_move(row["id"], new)
        moved = index_db.file_by_id(row["id"])
        self.assertEqual((moved["path"], moved["kind"], moved["included"]), (os.path.dirname(new), "sorted", False))

    def test_cancel_keeps_previous_index(self):
        for i in range(400):
            self.make(f"Big/d{i:03d}/f.jpg", b"x")
        job = scanner.start("deep", [str(self.home)], [])
        job.cancel()
        wait(job)
        self.assertEqual(job.state, "cancelled")
        self.assertIsNone(index_db.last_scan(), "a cancelled scan is not recorded as a completed scan")

    def test_pause_and_resume(self):
        for i in range(300):
            self.make(f"Big/d{i:03d}/f.jpg", b"x")
        job = scanner.start("deep", [str(self.home)], [])
        job.pause()
        self.assertEqual(scanner.status()["state"], "paused")
        time.sleep(0.2)
        job.resume()
        self.assertEqual(wait(job).state, "done")
        self.assertEqual(index_db.summary()["total"], 300)

    def test_home_with_vscode_folder_is_not_a_project(self):
        self.make(".vscode/settings.json", b"{}")
        self.make(".gitignore", b"*")
        self.make("Downloads/IMG_1.jpg", fx.jpeg())
        self.scan()
        row = index_db.files_page({"q": "img_1", "scope": "all"})["rows"][0]
        self.assertEqual((row["kind"], row["included"]), ("ok", True))

    def test_protected_and_missing_roots_are_refused(self):
        with self.assertRaises(ValueError):
            scanner.start("deep", [str(self.home / "nope")], [])
        node = self.home / "node_modules"
        node.mkdir()
        with self.assertRaises(ValueError):
            scanner.start("deep", [str(node)], [])

    def test_estimate(self):
        self.build()
        est = scanner.estimate([str(self.home)])
        self.assertTrue(est["complete"])
        self.assertGreater(est["est_files"], 250)
        self.assertLessEqual(est["low_s"], est["high_s"])

    def test_snapshot_and_history_after_scan(self):
        self.build()
        self.scan()
        self.assertGreaterEqual(len(index_db.snapshots()), 1)
        from core import history
        self.assertEqual(history.entries()[0]["kind"], "scan")

    def test_settings_roundtrip(self):
        settings.update(skip=["a", 3, ""], optin=["Code & Scripts", "Images"], mode="deep")
        s = settings.load()
        self.assertEqual((s["skip"], s["optin"], s["mode"]), (["a"], ["Code & Scripts"], "deep"))


if __name__ == "__main__":
    unittest.main()
