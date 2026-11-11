"""Phase A: "the scan completes in 1 second and every number is 0 on my friend's PC" and the 197% storage panel.

Each likely cause is tested on its own. The friend's machine could not be reproduced here, so the diagnostics
(`py server.py --doctor`, Settings > Diagnostics) are tested too: they must name the cause without file names."""
import json
import os
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest import mock

from tests.base import TempHomeCase
from tests.test_contract import JS, NODE
from tests.test_scan_errors import ScanApiCase
from core import classify, config, doctor, index_db, platform_utils, safety, scanner

ROOT = Path(__file__).resolve().parent.parent
SYMLINK, JUNCTION, CLOUD, CLOUD_7, DEDUP, APPEXEC = 0xA000000C, 0xA0000003, 0x9000001A, 0x9000701A, 0x80000013, 0x8000001B


def fake_stat(kind="file", attrs=0, tag=0, size=10):
    """A DirEntry.stat() result with the Windows attributes a real OneDrive placeholder has."""
    mode = (stat.S_IFDIR if kind == "dir" else stat.S_IFREG) | 0o644
    if kind == "dir":
        attrs |= 0x10
    return types.SimpleNamespace(st_mode=mode, st_size=size, st_mtime=1.7e9, st_atime=1.7e9, st_ctime=1.7e9, st_birthtime=1.7e9,
                                 st_file_attributes=attrs, st_reparse_tag=tag, st_flags=0, st_dev=1)


class Entry:
    def __init__(self, name, st):
        self.name, self._st = name, st

    def stat(self, follow_symlinks=True):
        return self._st


class FakeDir(list):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class ReparseRulesTest(unittest.TestCase):
    """Root cause candidate 1: every Windows reparse point was skipped as a 'link', silently."""

    def test_only_name_surrogates_are_links(self):
        link = platform_utils.is_reparse_or_link
        self.assertTrue(link(fake_stat(attrs=0x400, tag=SYMLINK)))
        self.assertTrue(link(fake_stat("dir", attrs=0x400, tag=JUNCTION)))
        self.assertTrue(link(fake_stat(attrs=0x400, tag=0)), "an unknown reparse point stays on the safe side")
        for tag in (CLOUD, CLOUD_7, DEDUP, APPEXEC):
            self.assertFalse(link(fake_stat(attrs=0x400, tag=tag)), hex(tag))
        self.assertFalse(link(fake_stat()))

    def test_cloud_tags_and_online_only(self):
        self.assertTrue(platform_utils.is_cloud_reparse(fake_stat(attrs=0x400, tag=CLOUD_7)))
        self.assertFalse(platform_utils.is_cloud_reparse(fake_stat(attrs=0x400, tag=JUNCTION)))
        self.assertTrue(platform_utils.is_online_only(fake_stat(attrs=0x400 | 0x400000, tag=CLOUD)))   # RECALL_ON_DATA_ACCESS
        self.assertFalse(platform_utils.is_online_only(fake_stat(attrs=0x400, tag=CLOUD)), "synced placeholder: on disk")


class WalkCase(TempHomeCase):
    def walk(self, roots):
        job = doctor._FakeJob()
        w = scanner._Walk(job, [], [], roots)
        return job, w


class OneDriveScanTest(WalkCase):
    def test_placeholder_files_and_folders_are_counted(self):
        """The friend's symptom: a OneDrive folder scanned in a second with 0 files. Placeholders must be listed."""
        root = str(self.home / "OneDrive" / "Documents")
        os.makedirs(root)
        listing = {
            root: [Entry("report.pdf", fake_stat(attrs=0x400 | 0x400000, tag=CLOUD_7, size=5000)),   # online-only
                   Entry("photo.jpg", fake_stat(attrs=0x400, tag=CLOUD_7, size=3000)),                # synced placeholder
                   Entry("Taxes", fake_stat("dir", attrs=0x400, tag=CLOUD_7)),                         # placeholder folder
                   Entry("Shortcut", fake_stat("dir", attrs=0x400, tag=JUNCTION))],                    # a real junction
            os.path.join(root, "Taxes"): [Entry("2025.xlsx", fake_stat(attrs=0x400 | 0x400000, tag=CLOUD_7, size=700))],
        }
        job, w = self.walk([root])
        import queue
        q = queue.Queue()
        q.put((root, None))
        with mock.patch.object(scanner.os, "scandir", side_effect=lambda p: FakeDir(listing[p.replace("\\\\?\\", "")])):
            while not q.empty():
                w.scan_dir(q.get(), q, "C:\\", 1)
        self.assertEqual(job.extra["found"], 3, "all three placeholder files are listed")
        self.assertEqual(job.extra["skipped"].get("link"), 1, "only the junction is skipped, and it is counted")
        self.assertEqual(job.extra["notes"].get("online_only"), 2)
        rows = [w.sink.get() for _ in range(w.sink.qsize())]
        flags = {f[0]: f[8] for r in rows for f in r[6]}
        self.assertTrue(flags["report.pdf"] & index_db.FLAG_CLOUD)
        self.assertFalse(flags["photo.jpg"] & index_db.FLAG_CLOUD)

    def test_nothing_is_dropped_without_a_reason(self):
        """Every exclusion is counted: hidden, protected, system files, links, the user's skip list."""
        self.make("Stuff/.hidden/a.txt")
        self.make("Stuff/node_modules/b.js")
        self.make("Stuff/Thumbs.db")
        self.make("Stuff/keep.txt")
        self.make("Stuff/skipme/c.txt")
        job = doctor._FakeJob()
        w = scanner._Walk(job, [str(self.home / "Stuff" / "skipme")], [], [str(self.home / "Stuff")])
        import queue
        q = queue.Queue()
        q.put((str(self.home / "Stuff"), None))
        while not q.empty():
            w.scan_dir(q.get(), q, "C:\\", 1)
        self.assertEqual(job.extra["found"], 1)
        self.assertEqual(job.extra["skipped"], {"hidden": 1, "protected": 1, "system_file": 1, "skip_list": 1})


class QuickFoldersTest(TempHomeCase):
    @unittest.skipUnless(config.WIN, "Windows Known Folders")
    def test_moved_folder_outside_home_is_used_for_the_real_user(self):
        """Regression: a Downloads folder moved to D:\\ (or OneDrive) was ignored and an empty ~/Downloads scanned."""
        moved = str(Path(tempfile.mkdtemp(prefix="aurasort-moved-")))
        try:
            def kf(guid):
                return str(self.home) if guid == platform_utils._FOLDERID_PROFILE else moved if guid == platform_utils._KNOWN_FOLDERS["Downloads"] else None
            with mock.patch.object(platform_utils, "_win_known_folder", side_effect=kf):
                q = {x["name"]: x for x in platform_utils.quick_folders()}
            self.assertEqual(q["Downloads"]["path"], moved)
            self.assertEqual(q["Downloads"]["source"], "windows")
            self.assertTrue(q["Downloads"]["exists"])
        finally:
            shutil.rmtree(moved, ignore_errors=True)

    @unittest.skipUnless(config.WIN, "Windows Known Folders")
    def test_custom_home_never_scans_the_real_profile(self):
        """Tests and fixtures set their own HOME: the signed-in user's real folders must not leak in."""
        def kf(guid):
            return r"C:\Users\Someone" if guid == platform_utils._FOLDERID_PROFILE else r"C:\Users\Someone\Downloads"
        with mock.patch.object(platform_utils, "_win_known_folder", side_effect=kf):
            q = {x["name"]: x for x in platform_utils.quick_folders()}
        self.assertEqual(q["Downloads"]["path"], str(self.home / "Downloads"))

    def test_onedrive_is_reported(self):
        od = self.home / "OneDrive"
        (od / "Documents").mkdir(parents=True)
        with mock.patch.dict(os.environ, {"OneDrive": str(od)}), \
                mock.patch.object(platform_utils, "_win_known_folder", side_effect=lambda g: str(self.home) if g == platform_utils._FOLDERID_PROFILE else str(od / "Documents") if g == platform_utils._KNOWN_FOLDERS["Documents"] else None):
            q = {x["name"]: x for x in platform_utils.quick_folders()}
        if config.WIN:
            self.assertTrue(q["Documents"]["onedrive"])
            self.assertEqual(q["Documents"]["path"], str(od / "Documents"))

    def test_xdg_user_dirs(self):
        cfg = self.home / ".config"
        cfg.mkdir()
        (cfg / "user-dirs.dirs").write_text('XDG_DOWNLOAD_DIR="$HOME/Téléchargements"\nXDG_MUSIC_DIR="$HOME"\n# comment\n', encoding="utf-8")
        got = platform_utils._xdg_user_dirs(self.home)
        self.assertEqual(got["XDG_DOWNLOAD_DIR"], str(self.home) + "/Téléchargements")
        self.assertNotIn("XDG_MUSIC_DIR", got, "XDG uses $HOME itself for 'not set'")


class ProtectionTest(TempHomeCase):
    def test_user_name_that_is_a_protected_word(self):
        """A user called 'venv' (or 'AppData'): the home folder itself must not be a 'tool folder'."""
        home = self.tmp / "venv"
        (home / "Downloads").mkdir(parents=True)
        with mock.patch.object(config, "HOME", home):
            self.assertIsNone(safety.protection_reason(str(home)))
            self.assertIsNone(safety.protection_reason(str(home / "Downloads")))
            self.assertIsNotNone(safety.protection_reason(str(home / "Downloads" / "venv")), "a real venv inside stays protected")

    def test_home_inside_a_system_prefix_stays_scannable(self):
        """Linux root has HOME=/root, which is a protected prefix: every scan found 0 files."""
        saved = safety._PREFIXES
        try:
            safety._PREFIXES = None
            with mock.patch.object(safety, "protected_prefixes", return_value=[str(self.tmp)]):
                self.assertFalse(safety.is_protected(str(self.home / "Documents")))
        finally:
            safety._PREFIXES = saved

    def test_space_and_non_english_user_folder(self):
        home = self.tmp / "Test User Ünïcødé" / "OneDrive" / "Documents"
        (home / "Tax 2025").mkdir(parents=True)
        (home / "Tax 2025" / "résumé.pdf").write_bytes(b"%PDF-1.4")
        self.assertFalse(safety.is_protected(str(home)))
        res = doctor.test_scan(str(home))
        self.assertEqual(res["files"], 1)

    def test_scan_root_needs_strong_project_evidence(self):
        """One stray requirements.txt in Downloads made every file in it 'part of a project'."""
        self.assertFalse(safety.is_project({"requirements.txt", "a.jpg"}, strict=True))
        self.assertTrue(safety.is_project({"requirements.txt", "a.jpg"}))               # a sub-folder: still a project
        self.assertTrue(safety.is_project({"requirements.txt", "Makefile"}, strict=True))
        self.assertTrue(safety.is_project({"package.json"}, strict=True))
        self.assertTrue(safety.is_project({"App.sln"}, strict=True))
        self.assertFalse(safety.is_project({"scene.blend", "notes.txt"}, strict=True))
        self.make("Downloads/requirements.txt")
        self.make("Downloads/photo.jpg")
        res = doctor.test_scan(str(self.home / "Downloads"))
        self.assertEqual(res["notes"].get("project", 0), 0)


class ExplainTest(TempHomeCase):
    def test_zero_files_always_explained(self):
        self.assertEqual(scanner.explain(dict(found=0, skipped={}, notes={}))[0]["code"], "empty")
        codes = [e["code"] for e in scanner.explain(dict(found=0, skipped={"no_access": 4}, notes={}))]
        self.assertIn({"win32": "windows_blocked", "darwin": "mac_privacy"}.get(sys.platform, "no_permission" if not config.ANDROID else "android_storage"), codes)
        self.assertIn("links_only", [e["code"] for e in scanner.explain(dict(found=0, skipped={"link": 2}, notes={}))])
        self.assertIn("protected_only", [e["code"] for e in scanner.explain(dict(found=0, skipped={"protected": 2}, notes={}))])

    def test_everything_in_projects_or_online_only(self):
        self.assertEqual(scanner.explain(dict(found=10, skipped={}, notes={"project": 10}))[0]["code"], "all_project")
        self.assertEqual(scanner.explain(dict(found=10, skipped={}, notes={"online_only": 9}))[0]["code"], "online_only")
        self.assertEqual(scanner.explain(dict(found=10, skipped={}, notes={"project": 2})), [])


class IndexTest(ScanApiCase):
    def test_schema_version_is_stamped_and_old_index_upgraded(self):
        c = sqlite3.connect(str(config.INDEX_DB))
        self.assertEqual(c.execute("PRAGMA user_version").fetchone()[0], index_db.SCHEMA_VERSION)
        c.close()
        index_db.close_all()
        config.INDEX_DB.unlink()
        c = sqlite3.connect(str(config.INDEX_DB))   # an index from 1.0.0: version 0, no lpath
        c.executescript("CREATE TABLE dirs(id INTEGER PRIMARY KEY, path TEXT NOT NULL UNIQUE, seen INTEGER);"
                        "CREATE TABLE files(id INTEGER PRIMARY KEY, dir INTEGER, name TEXT, seen INTEGER);")
        c.close()
        index_db.init()
        st, s = self.scan(self.two_folders())
        self.assertEqual((s["state"], s["found"]), ("done", 4))

    def test_index_from_a_newer_version_is_rebuilt(self):
        index_db.close_all()
        c = sqlite3.connect(str(config.INDEX_DB))
        c.execute(f"PRAGMA user_version={index_db.SCHEMA_VERSION + 5}")
        c.close()
        index_db.init()
        st, s = self.scan(self.two_folders())
        self.assertEqual(s["found"], 4)

    def test_numbers_agree_everywhere(self):
        """Dashboard total = sum of categories = list totals; the Images badge = the Images list."""
        self.make("Pics/a.jpg", b"x" * 100)
        self.make("Pics/b.png", b"x" * 50)
        self.make("Pics/c.txt", b"x" * 7)
        self.scan({"mode": "deep", "roots": [str(self.home / "Pics")], "skip": []})
        _, summ = self.get("/api/summary")
        self.assertTrue(summ["consistent"])
        self.assertEqual(summ["total"], sum(c["n"] for c in summ["by_cat"].values()))
        _, imgs = self.get("/api/files?type=Images")
        self.assertEqual(imgs["total"], summ["by_cat"]["Images"]["n"])
        _, allf = self.get("/api/files")
        self.assertEqual(allf["total"], summ["total"])
        self.assertEqual(sum(v["size"] for v in summ["by_cat"].values()), summ["total_size"])

    def test_orphan_rows_are_removed_and_reported(self):
        self.scan(self.two_folders())
        with index_db.write_lock():
            w = index_db.writer()
            w.execute("INSERT INTO files(dir, name, lname, ext, cat, sub, size, mtime) VALUES(99999, 'ghost.jpg', 'ghost.jpg', 'jpg', 'Images', '', 5, 0)")
            w.commit()
        index_db.bump()
        with self.assertLogs("aurasort", "ERROR"):
            self.assertFalse(index_db.consistency()["ok"])
        _, summ = self.get("/api/summary")
        self.assertFalse(summ["consistent"])
        st, s = self.scan(self.two_folders())
        index_db.bump()
        self.assertTrue(index_db.consistency()["ok"])

    def test_percent_of_disk_ignores_online_only_files(self):
        """The 197% panel: online-only OneDrive files have a full size but use no disk space."""
        self.scan(self.two_folders())
        with index_db.write_lock():
            w = index_db.writer()
            w.execute("UPDATE files SET size = ?, flags = flags | ? WHERE ext = 'pdf'", (10 ** 12, index_db.FLAG_CLOUD))
            w.commit()
        index_db.bump()
        _, ext = self.get("/api/extensions")
        pdf = next(r for r in ext["rows"] if r["ext"] == "pdf")
        self.assertEqual(pdf["disk_size"], 0)
        self.assertEqual(pdf["size"], 10 ** 12)
        _, summ = self.get("/api/summary")
        self.assertEqual(summ["cloud_n"], 1)
        self.assertLess(summ["disk_size"], summ["total_size"])


@unittest.skipUnless(config.WIN, "Windows path length limit")
class LongPathTest(TempHomeCase):
    def test_folder_deeper_than_260_characters_is_scanned(self):
        deep = str(self.home / "Deep")
        while len(deep) < 300:
            deep = os.path.join(deep, "a-rather-long-folder-name")
        os.makedirs(platform_utils.long_path(deep))
        with open(platform_utils.long_path(os.path.join(deep, "deep file.txt")), "wb") as fh:
            fh.write(b"hello")
        res = doctor.test_scan(str(self.home / "Deep"))
        self.assertEqual(res["files"], 1, res)
        self.assertNotIn("unreadable", res["skipped"])
        self.assertTrue(safety.is_plain_file(os.path.join(deep, "deep file.txt")))


class DoctorTest(TempHomeCase):
    def test_report_names_causes_without_file_names(self):
        secret = "my-private-medical-report.pdf"
        self.make(f"Documents/{secret}")
        self.make("Documents/holiday.jpg")
        d = doctor.collect(folder=str(self.home / "Documents"))
        text = doctor.as_text(d)
        self.assertNotIn(secret, text)
        self.assertNotIn("holiday", text)
        self.assertNotIn(str(self.home), text, "the home folder is shown as ~")
        names = {c["name"]: c for c in d["checks"]}
        for must in ("Python", "Text encoding", "Administrator / root", "Data folder", "SQLite", "File index", "Drives", "Test scan"):
            self.assertIn(must, names)
        self.assertEqual(names["Test scan"]["status"], doctor.OK)
        self.assertEqual(d["facts"]["test_scan"]["files"], 2)
        self.assertNotEqual(d["status"], doctor.FAIL, text)

    def test_a_failing_check_is_reported_not_raised(self):
        with mock.patch.object(platform_utils, "list_drives", side_effect=KeyError("boom")):
            d = doctor.collect(scan=False)
        drives = [c for c in d["checks"] if c["name"] == "Drives"][0]
        self.assertEqual(drives["status"], doctor.FAIL)
        self.assertIn("KeyError", drives["value"])
        self.assertIn("Traceback", drives["detail"])

    def test_user_name_is_masked(self):
        with mock.patch.object(doctor, "_user", return_value="anushka"):
            self.assertEqual(doctor.mask(r"C:\Data\anushka\x and Anushka"), r"C:\Data\<user>\x and <user>")

    def test_command_line_on_a_brand_new_home(self):
        """`py server.py --doctor` on a PC that never ran AuraSort (no ~/.aurasort), as a normal user."""
        home = self.tmp / "fresh user"
        (home / "Downloads").mkdir(parents=True)
        (home / "Downloads" / "a.txt").write_bytes(b"1")
        env = dict(os.environ, USERPROFILE=str(home), HOME=str(home), PYTHONIOENCODING="")
        r = subprocess.run([sys.executable, str(ROOT / "server.py"), "--doctor", "--json", "--folder", str(home / "Downloads")],
                           capture_output=True, timeout=120, env=env)
        out = json.loads(r.stdout.decode("utf-8"))
        self.assertEqual(r.returncode, 0, out)
        self.assertEqual(out["facts"]["test_scan"]["files"], 1)
        self.assertFalse((home / ".aurasort" / "index.sqlite3").exists(), "the doctor does not create an index")


class DiagnosticsApiTest(ScanApiCase):
    def test_settings_diagnostics_page_data(self):
        self.make("Downloads/a.txt")
        st, d = self.get("/api/diagnostics?scan=1")
        self.assertEqual(st, 200)
        self.assertIn("text", d)
        self.assertIn("Quick Scan folder: Downloads", d["text"])
        self.assertNotIn("a.txt", d["text"])


class ConcurrentSaveTest(TempHomeCase):
    def test_saving_settings_while_other_requests_read_them(self):
        """Regression (found by the Playwright run): POST /api/settings failed with WinError 5 when another request was
        reading settings.json at that moment (Windows refuses to replace an open file). Reads and writes now share a lock."""
        import threading
        from core import settings
        settings.update(mode="quick")
        stop, errors = threading.Event(), []

        def reader():   # like many requests at once: each reads the settings (cache emptied to force a real read)
            while not stop.is_set():
                settings._CACHE.clear()
                try:
                    settings.load()
                except OSError as ex:
                    errors.append(ex)
        threads = [threading.Thread(target=reader, daemon=True) for _ in range(4)]
        for th in threads:
            th.start()
        try:
            for i in range(80):
                try:
                    settings.update(mode="deep" if i % 2 else "quick")
                except OSError as ex:
                    errors.append(ex)
        finally:
            stop.set()
            for th in threads:
                th.join()
        self.assertEqual(errors, [])
        self.assertEqual(settings.load()["mode"], "deep")

    @unittest.skipUnless(config.WIN, "Windows only refuses to replace an open file")
    def test_a_brief_outside_hold_is_waited_out(self):
        """Another program (antivirus, backup) holding the file for a moment: the save waits instead of failing."""
        import threading
        from core import settings
        settings.update(mode="quick")
        fh = open(config.SETTINGS_FILE, encoding="utf-8")
        threading.Timer(0.3, fh.close).start()
        settings.update(mode="deep")      # retried until the file is free
        self.assertEqual(settings.load()["mode"], "deep")


@unittest.skipUnless(NODE, "Node.js runs the front-end helper")
class PercentTest(unittest.TestCase):
    def test_percentages_are_clamped_and_na_without_a_denominator(self):
        js = r"""
const src = require('fs').readFileSync(process.argv[1], 'utf8');
const pick = n => src.match(new RegExp('const ' + n + ' = [^\n]*'))[0];
const f = new Function([pick('share'), pick('pct'), pick('pctTxt'), 'return {share, pct, pctTxt};'].join('\n'))();
const out = [f.pctTxt(f.share(197, 100)), f.pctTxt(f.share(5, 0)), f.pctTxt(f.share(-3, 10)), f.pctTxt(f.share(0.4, 100)), f.pct(172, 100), f.pct(1, 0), f.pctTxt(f.share(79, 100))];
process.stdout.write(JSON.stringify(out));
"""
        r = subprocess.run([NODE, "-e", js, os.path.join(JS, "util.js")], capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), ["100%", "n/a", "0%", "<1%", 100, 0, "79%"])

    def test_no_view_divides_by_a_fake_denominator(self):
        """`total_size || 1` turned 'no data' into huge percentages; every share goes through share()/pct()."""
        for f in ("views/dashboard.js", "views/storage.js", "ui.js"):
            src = (Path(JS) / f).read_text(encoding="utf-8")
            self.assertNotIn("total_size || 1", src, f)
            self.assertNotIn("pctTxt(pct(", src, f)


if __name__ == "__main__":
    unittest.main()
