"""Acting on selections: move/copy layouts, Recycle Bin jobs (test bin), typed confirmation, guarded files, New folder, preflight, History details."""
import json
import os
import time
import unittest
from unittest import mock

from tests import fixtures as fx
from tests.test_web_security import ServerCase
from core import config, history, index_db, jobs, scanner, trash, web


class ActionCase(ServerCase):
    def setUp(self):
        super().setUp()
        self.bin = self.tmp / "test-bin"
        self._env = mock.patch.dict(os.environ, {trash.TEST_TRASH_ENV: str(self.bin)})
        self._env.start()
        web._RATE.clear()   # each test starts with fresh rate-limit windows

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
        job = jobs.get(jid)
        while job.state in ("running", "paused"):
            time.sleep(0.02)
        return job.snapshot()


class TrashTest(ActionCase):
    def test_view_only_and_projects_need_opt_in(self):
        rows = self.scan([("Lib/doc.pdf", fx.pdf()), ("Lib/run.exe", fx.exe()), ("Lib/site/package.json", b"{}"), ("Lib/site/logo.png", fx.png())])
        ids = [rows[n]["id"] for n in ("doc.pdf", "run.exe", "logo.png")]
        st, r = self.post("/api/trash", {"ids": ids})
        self.assertEqual((r["count"], r["blocked"]), (1, 2), "the program and the project file are left alone")
        snap = self.wait(r["job"])
        self.assertEqual(snap["moved"], 1)
        self.assertFalse((self.home / "Lib" / "doc.pdf").exists())
        self.assertTrue((self.bin / "doc.pdf").exists(), "moved into the bin, never deleted")
        self.assertTrue((self.home / "Lib" / "run.exe").exists() and (self.home / "Lib" / "site" / "logo.png").exists())
        self.assertIsNone(index_db.file_by_id(rows["doc.pdf"]["id"]), "gone from every list without a rescan")
        entry = [e for e in history.entries() if e["kind"] == "trash"][0]
        self.assertEqual((entry["count"], entry["undoable"]), (1, False))
        st, r = self.post("/api/trash", {"ids": ids[1:], "allow_project": True, "allow_viewonly": ["Installers & Apps"]})
        self.assertEqual(r["count"], 2)
        self.wait(r["job"])
        self.assertFalse((self.home / "Lib" / "run.exe").exists())

    def test_typed_count_for_large_selections(self):
        rows = self.scan([(f"Lib/p{i}.pdf", fx.pdf(1) + bytes([i])) for i in range(4)])
        ids = [r["id"] for r in rows.values()]
        with mock.patch.object(config, "TRASH_TYPED_CONFIRM_MIN", 3):
            self.assertEqual(self.req("/api/trash", {"ids": ids})[0], 400)
            self.assertEqual(self.req("/api/trash", {"ids": ids, "confirm_count": "3"})[0], 400, "wrong number")
            st, r = self.post("/api/trash", {"ids": ids, "confirm_count": "4"})
        self.assertEqual((st, r["count"]), (200, 4))
        self.assertEqual(self.wait(r["job"])["moved"], 4)

    def test_changed_file_is_skipped(self):
        rows = self.scan([("Lib/c.pdf", fx.pdf())])
        (self.home / "Lib" / "c.pdf").write_bytes(fx.pdf(3))   # edited after the scan
        st, r = self.post("/api/trash", {"ids": [rows["c.pdf"]["id"]]})
        snap = self.wait(r["job"])
        self.assertEqual((snap["moved"], snap["skipped"]), (0, 1))
        self.assertTrue((self.home / "Lib" / "c.pdf").exists())

    def test_nothing_selected(self):
        self.assertEqual(self.req("/api/trash", {"ids": []})[0], 400)


class MoveSelectionTest(ActionCase):
    def test_layout_here_with_name_clash_and_undo(self):
        rows = self.scan([("Lib/x/photo.png", fx.png()), ("Lib/y/photo.png", fx.png(5, 5))])
        dest = self.home / "Picked"
        dest.mkdir()
        ids = [i["id"] for i in index_db.files_page({"scope": "all"})["rows"] if i["name"] == "photo.png"]
        st, r = self.post("/api/execute", {"ids": ids, "dest": str(dest), "mode": "move", "layout": "here"})
        self.assertEqual(st, 200)
        self.assertEqual(r["by_cat"]["Images"]["n"], r["count"])
        self.wait(r["job"])
        self.assertEqual(sorted(os.listdir(dest)), ["photo (1).png", "photo.png"], "straight into the folder, clash gets (1)")
        self.assertEqual(self.post("/api/undo", {"id": r["job"]})[1]["restored"], 2)
        self.assertTrue((self.home / "Lib" / "x" / "photo.png").exists() and (self.home / "Lib" / "y" / "photo.png").exists())

    def test_unknown_layout(self):
        rows = self.scan([("Lib/a.png", fx.png())])
        self.assertEqual(self.req("/api/execute", {"ids": [rows["a.png"]["id"]], "dest": str(self.home / "D"), "layout": "nope"})[0], 400)


class PreflightAndFolderTest(ActionCase):
    def test_selection_preflight(self):
        rows = self.scan([("Lib/a.png", fx.png()), ("Lib/b.exe", fx.exe()), ("Lib/site/package.json", b"{}"), ("Lib/site/c.png", fx.png())])
        st, r = self.post("/api/selection", {"ids": [rows[n]["id"] for n in ("a.png", "b.exe", "c.png")] + [999999]})
        self.assertEqual((r["n"], r["missing"]), (3, 1))
        kinds = {(g[0], g[1]): g[3] for g in r["groups"]}
        self.assertEqual(kinds[("Images", "ok")], 1)
        self.assertEqual(kinds[("Images", "project")], 1)
        self.assertEqual(kinds[("Installers & Apps", "ok")], 1)

    def test_mkdir_rules(self):
        parent = self.home / "Dest"
        parent.mkdir()
        st, r = self.post("/api/mkdir", {"parent": str(parent), "name": "New stuff"})
        self.assertEqual(st, 200)
        self.assertTrue(os.path.isdir(r["path"]))
        self.assertEqual(self.req("/api/mkdir", {"parent": str(parent), "name": "New stuff"})[0], 409)
        for bad in ("a/b", "CON", "..", "x:y", "", "trailing."):
            self.assertEqual(self.req("/api/mkdir", {"parent": str(parent), "name": bad})[0], 400, bad)
        self.assertEqual(self.req("/api/mkdir", {"parent": "", "name": "x"})[0], 400)
        self.assertEqual(self.req("/api/mkdir", {"parent": str(parent), "name": "node_modules"})[0], 400, "protected names are refused")

    def test_history_details(self):
        rows = self.scan([("Lib/a.pdf", fx.pdf())])
        st, r = self.post("/api/trash", {"ids": [rows["a.pdf"]["id"]]})
        self.wait(r["job"])
        st, _, raw = self.req(f"/api/history/item?id={r['job']}")
        d = json.loads(raw)
        self.assertEqual((st, d["kind"], len(d["ops"])), (200, "trash", 1))
        self.assertTrue(d["ops"][0]["src"].endswith("a.pdf"))


if __name__ == "__main__":
    unittest.main()
