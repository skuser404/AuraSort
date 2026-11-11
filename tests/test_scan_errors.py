"""Regression tests for "The scan stopped: Unexpected error (KeyError)." and every scan/request combination around it.

Root cause: the scan's database-writer thread died (an index written by an earlier version had no 'lpath' column; a file
name with broken Unicode can't be stored in SQLite), the real error was lost, and the scan then read result["w"], which
the dead thread never set -> KeyError: 'w'."""
import json
import os
import pathlib
import re
import sqlite3
import subprocess
import sys
import threading
import time
import unittest
from unittest import mock

from tests.test_web_security import ROOT, ServerCase
from tests.base import TempHomeCase
from core import config, history, index_db, instance, jobs, schema, scanner, settings, web


def wait(job, timeout=30):
    t0 = time.time()
    while job.state in ("running", "paused") and time.time() - t0 < timeout:
        time.sleep(0.02)
    return job


class ScanApiCase(ServerCase):
    """Why: the exact request the Scan page sends, through the real HTTP server."""

    def setUp(self):
        super().setUp()
        web._RATE.clear()   # each test starts with fresh rate-limit windows
        self._env = mock.patch.dict(os.environ, {config.SCHEMA_STRICT_ENV: "1"})
        self._env.start()

    def tearDown(self):
        self._env.stop()
        super().tearDown()

    def post(self, path, body):
        st, _, raw = self.req(path, body)
        return st, json.loads(raw or b"{}")

    def get(self, path):
        st, _, raw = self.req(path)
        return st, json.loads(raw or b"{}")

    def scan(self, body):
        """POST scan/start, then poll scan/status like the page does; returns (http status, final status)."""
        st, r = self.post("/api/scan/start", body)
        self.assertEqual(st, 200, r)
        t0 = time.time()
        while time.time() - t0 < 30:
            _, s = self.get("/api/scan/status")
            if s.get("state") not in ("running", "paused"):
                return st, s
            time.sleep(0.05)
        self.fail("scan did not finish")

    def two_folders(self):
        self.make("Music/song one.mp3")
        self.make("Music/Album/track.flac")
        self.make("Downloads/setup.exe")
        self.make("Downloads/report.pdf")
        return {"mode": "deep", "roots": [str(self.home / "Music"), str(self.home / "Downloads")], "skip": [], "est_files": 0}


class OriginalBugTest(ScanApiCase):
    def test_deep_scan_two_folders_no_drives(self):
        """The reported case: Deep Scan, 0 drives, 2 folders."""
        st, s = self.scan(self.two_folders())
        self.assertEqual(st, 200)
        self.assertEqual(s["state"], "done", s)
        self.assertEqual(s["found"], 4)

    def test_index_from_an_earlier_version(self):
        """Regression: an old index without the 'lpath' column made the writer thread die -> KeyError: 'w'."""
        index_db.close_all()
        config.INDEX_DB.unlink()
        c = sqlite3.connect(str(config.INDEX_DB))
        c.executescript("CREATE TABLE dirs(id INTEGER PRIMARY KEY, path TEXT NOT NULL UNIQUE, drive TEXT, seen INTEGER);"
                        "CREATE TABLE files(id INTEGER PRIMARY KEY, dir INTEGER, name TEXT, lname TEXT, ext TEXT, cat TEXT, sub TEXT, "
                        "size INTEGER, mtime REAL, ctime REAL, atime REAL, seen INTEGER, UNIQUE(dir, name));"
                        "CREATE TABLE scans(id INTEGER PRIMARY KEY, started REAL, mode TEXT, roots TEXT);")
        c.commit()
        c.close()
        index_db.init()
        st, s = self.scan(self.two_folders())
        self.assertEqual(s["state"], "done", s)
        self.assertEqual(s["found"], 4)
        self.assertNotIn("KeyError", json.dumps(s))

    def test_file_name_sqlite_cannot_store(self):
        """Regression: a name with a lone surrogate (allowed by Windows, made by old phones/unzips) killed the writer."""
        body = self.two_folders()
        bad = os.path.join(str(self.home / "Music"), "bad" + chr(0xD800) + "name.mp3") if config.WIN \
            else os.fsencode(str(self.home / "Music")) + b"/bad\xffname.mp3"
        try:
            with open(bad, "wb") as fh:
                fh.write(b"x")
        except (OSError, UnicodeError):
            self.skipTest("this file system refuses such names")
        st, s = self.scan(body)
        self.assertEqual(s["state"], "done", s)
        self.assertEqual(s["found"], 4)
        self.assertEqual(s["skipped"].get("bad_name"), 1)
        self.assertEqual(s["skipped_total"], 1)
        os.remove(bad)

    def test_writer_failure_is_explained_not_keyerror(self):
        """A real database failure (here: locked) stops the scan with words a person can act on."""
        with mock.patch.object(index_db.ScanWriter, "add", side_effect=sqlite3.OperationalError("database is locked")):
            st, s = self.scan(self.two_folders())
        self.assertEqual(s["state"], "error")
        self.assertEqual(s["failure"]["code"], "index_busy")
        self.assertEqual(s["failure"]["step"], "writing the index")
        self.assertIn("another AuraSort window", s["errors"][0])
        self.assertNotIn("KeyError", json.dumps(s))

    def test_unexpected_bug_message_is_human(self):
        """Any other bug: a plain message plus a safe report (type, step); the traceback goes to the log file."""
        with mock.patch.object(scanner, "_scan", side_effect=KeyError("w")), self.assertLogs(config.APP_SLUG, "ERROR") as logs:
            st, s = self.scan(self.two_folders())
        self.assertEqual(s["state"], "error")
        self.assertEqual(s["errors"][0], "The scan stopped because of an unexpected problem.")
        self.assertEqual(s["failure"]["type"], "KeyError")
        self.assertIn("server.log", s["failure"]["hint"])
        self.assertTrue(any(r.exc_info and r.exc_info[0] is KeyError for r in logs.records), "full traceback is logged")


class CombinationsTest(ScanApiCase):
    def test_quick_scan_default_folders(self):
        self.make("Downloads/a.pdf")
        with mock.patch.object(scanner, "quick_roots", return_value=[str(self.home / "Downloads")]):
            st, s = self.scan({"mode": "quick", "roots": [], "skip": [], "est_files": 0})
        self.assertEqual(s["state"], "done", s)
        self.assertEqual(s["found"], 1)

    def test_deep_with_nothing_selected_is_refused(self):
        st, r = self.post("/api/scan/start", {"mode": "deep", "roots": [], "skip": [], "est_files": 0})
        self.assertEqual(st, 400)
        self.assertEqual(r["error"], "Pick at least one drive or folder.")
        self.assertEqual(r["code"], "nothing_selected")
        self.assertTrue(r["hint"])

    def test_missing_fields_get_defaults(self):
        self.two_folders()
        st, s = self.scan({"mode": "deep", "roots": [str(self.home / "Music")]})   # no skip, no est_files
        self.assertEqual(s["state"], "done", s)

    def test_many_folders_skip_and_nesting(self):
        body = self.two_folders()
        body["roots"].append(str(self.home / "Music" / "Album"))          # nested in Music: scanned once
        body["skip"] = [str(self.home / "Music" / "Album")]
        st, s = self.scan(body)
        self.assertEqual(s["state"], "done", s)
        self.assertEqual(s["found"], 3)                                     # track.flac is in the skipped folder

    def test_spaces_and_non_english_names(self):
        self.make("Música ñ/日本 photos/写真 1.jpg")
        self.make("Música ñ/Résumé final (v2).pdf")
        st, s = self.scan({"mode": "deep", "roots": [str(self.home / "Música ñ")], "skip": [], "est_files": 0})
        self.assertEqual(s["state"], "done", s)
        self.assertEqual(s["found"], 2)

    def test_trailing_separator_and_case(self):
        body = self.two_folders()
        body["roots"] = [str(self.home / "Music") + os.sep, str(self.home / "Downloads")]
        if config.WIN:
            body["roots"].append(str(self.home / "Downloads").upper())    # same folder on Windows: counted once
        st, s = self.scan(body)
        self.assertEqual(s["state"], "done", s)
        self.assertEqual(s["found"], 4)

    def test_empty_folder(self):
        (self.home / "Empty").mkdir()
        st, s = self.scan({"mode": "deep", "roots": [str(self.home / "Empty")], "skip": [], "est_files": 0})
        self.assertEqual(s["state"], "done", s)
        self.assertEqual(s["found"], 0)

    def test_one_folder_missing_others_scanned(self):
        body = self.two_folders()
        body["roots"].append(str(self.home / "Gone"))
        st, s = self.scan(body)
        self.assertEqual(s["state"], "done", s)
        self.assertEqual(s["skipped"].get("missing_root"), 1)

    def test_all_folders_missing_or_drive_unplugged(self):
        missing = [str(self.home / "Gone")] + (["Q:\\"] if config.WIN and not os.path.exists("Q:\\") else [])
        st, r = self.post("/api/scan/start", {"mode": "deep", "roots": missing, "skip": [], "est_files": 0})
        self.assertEqual(st, 400)
        self.assertEqual(r["code"], "not_found")

    def test_folder_disappears_mid_scan_and_no_permission(self):
        body = self.two_folders()
        real = os.scandir
        album, downloads = (os.path.normcase(scanner.canonical(self.home / n)) for n in ("Music/Album", "Downloads"))

        def flaky(path):
            p = os.path.normcase(str(path))
            if p == album:
                raise FileNotFoundError(2, "gone", path)
            if p == downloads:
                raise PermissionError(13, "denied", path)
            return real(path)
        with mock.patch.object(scanner.os, "scandir", side_effect=flaky):
            st, s = self.scan(body)
        self.assertEqual(s["state"], "done", s)
        self.assertEqual(s["skipped"].get("vanished"), 1)
        self.assertEqual(s["skipped"].get("no_access"), 1)
        self.assertEqual(s["noaccess"], 1)
        labels = {r["code"]: r["label"] for r in s["skipped_reasons"]}
        self.assertEqual(labels["no_access"], "no permission")

    def test_one_broken_folder_does_not_stop_the_scan(self):
        body = self.two_folders()
        real = scanner.classify.classify

        def boom(name):
            if name == "report.pdf":
                raise RuntimeError("bug in one folder")
            return real(name)
        with mock.patch.object(scanner.classify, "classify", side_effect=boom):
            st, s = self.scan(body)
        self.assertEqual(s["state"], "done", s)
        self.assertEqual(s["skipped"].get("error"), 1)

    @unittest.skipUnless(config.WIN, "Windows drive letters")
    def test_drive_root_without_backslash(self):
        """'C:' alone means 'the current folder on C:' to Windows; it must mean the drive."""
        self.assertEqual(schema.norm_path("C:", "roots"), "C:\\")
        self.assertEqual(schema.norm_path("d:\\", "roots"), "d:\\")
        self.assertEqual(schema.path_list({"roots": ["C:", "c:\\"]}, "roots"), ["C:\\"])


class BadInputTest(ScanApiCase):
    def check_400(self, body, code):
        web._RATE.clear()
        st, r = self.post("/api/scan/start", body)
        self.assertEqual(st, 400, r)
        self.assertEqual(r["code"], code, r)
        self.assertTrue(r["error"])
        self.assertNotRegex(r["error"], r"[A-Z][a-z]+Error")

    def test_invalid_bodies_are_400_never_500(self):
        home = str(self.home)
        self.check_400({"mode": "fast", "roots": [home]}, "bad_mode")
        self.check_400({"mode": "deep", "roots": home}, "bad_type")
        self.check_400({"mode": "deep", "roots": [5]}, "bad_path")
        self.check_400({"mode": "deep", "roots": ["relative/folder"]}, "bad_path")
        self.check_400({"mode": "deep", "roots": [home], "est_files": -1}, "bad_type")
        self.check_400({"mode": "deep", "roots": [home], "est_files": "many"}, "bad_type")
        self.check_400({"mode": "deep", "roots": [home], "skip": "x"}, "bad_type")
        self.check_400({"mode": "deep", "folders": [home]}, "unknown_field")     # a renamed field fails loudly in tests

    def test_other_routes_with_wrong_types(self):
        for path, body in (("/api/rows", {"ids": "1,2"}), ("/api/rows", {"ids": ["a"]}), ("/api/open", {"id": None}),
                           ("/api/open", {}), ("/api/selection", {"ids": {"a": 1}}), ("/api/trash", {"ids": []}),
                           ("/api/ai/settings", {"settings": [1, 2]}), ("/api/reveal", {"job": ["x"]}), ("/api/plan", {"dest": 5})):
            st, r = self.post(path, body)
            self.assertIn(st, (400, 404), (path, body, r))
            self.assertIn("code", r)

    def test_internal_errors_are_500_with_code_and_logged(self):
        with mock.patch.object(scanner, "status", side_effect=KeyError("drive_stats")), self.assertLogs(config.APP_SLUG, "ERROR") as logs:
            st, r = self.get("/api/scan/status")
        self.assertEqual(st, 500)
        self.assertEqual(r["code"], "internal")
        self.assertIn("server.log", r["hint"])
        self.assertNotIn("KeyError", r["error"])
        self.assertTrue(any(r.exc_info and r.exc_info[0] is KeyError for r in logs.records), "full traceback is logged")


class PickerTest(ScanApiCase):
    def test_destination_that_does_not_exist_yet(self):
        """Regression: "Move to…" before the first move: the default AuraSortFiles does not exist; the picker got a 400,
        fell back to "This PC" and New folder was disabled. Now it opens the nearest existing folder and names the missing one."""
        from urllib.parse import quote
        st, r = self.get("/api/browse?path=" + quote(str(self.home / "AuraSortFiles" / "Later")))
        self.assertEqual(st, 200, r)
        self.assertEqual(os.path.normcase(r["path"]), os.path.normcase(scanner.canonical(self.home)))
        self.assertEqual(r["missing"], "Later")
        st, r = self.get("/api/browse?path=" + quote(str(self.home)))
        self.assertEqual((st, r["missing"]), (200, ""))


class StoredDataTest(TempHomeCase):
    def test_damaged_index_file_is_set_aside(self):
        index_db.close_all()
        for suffix in ("", "-wal", "-shm"):
            p = str(config.INDEX_DB) + suffix
            if os.path.exists(p):
                os.remove(p)
        config.INDEX_DB.write_bytes(b"this is not a database" * 100)
        index_db.init()
        self.assertIsNone(index_db.last_scan())
        self.assertTrue(any(p.name.startswith("index.sqlite3.broken-") for p in config.DATA_DIR.iterdir()))

    def test_settings_with_wrong_types(self):
        config.SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        config.SETTINGS_FILE.write_text(json.dumps({"dest_roots": 5, "skip": "C:\\x", "roots": [1, "C:\\ok"], "mode": "turbo", "ai": []}), encoding="utf-8")
        s = settings.load()
        self.assertEqual(s["dest_roots"], [])
        self.assertEqual(s["skip"], [])
        self.assertEqual(s["roots"], ["C:\\ok"])
        self.assertEqual(s["mode"], "quick")
        self.assertIsInstance(s["ai"], dict)
        self.make("Lib/a.txt")
        job = wait(scanner.start("deep", [str(self.home / "Lib")], []))
        self.assertEqual(job.state, "done", job.errors)

    def test_long_paths_are_not_cut(self):
        long = "C:\\" + "\\".join(["folder"] * 200)
        self.assertEqual(settings.update(roots=[long])["roots"], [long])

    def test_history_entries_from_older_versions(self):
        config.HISTORY_DIR.mkdir(parents=True, exist_ok=True)
        (config.HISTORY_DIR / "20200101-000000-aaaa.json").write_text(json.dumps({"kind": "move", "ops": [{"size": 5}, "junk"]}), encoding="utf-8")
        (config.HISTORY_DIR / "20200101-000001-bbbb.json").write_text("[1, 2]", encoding="utf-8")
        (config.HISTORY_DIR / "20200101-000002-cccc.json").write_text("{broken", encoding="utf-8")
        out = history.entries()
        self.assertEqual([e["id"] for e in out], ["20200101-000000-aaaa"])
        self.assertEqual(out[0]["size"], 5)

    def test_job_failure_report_is_safe(self):
        j = jobs.Job("scan", step="reading folders")
        j.fail(OSError(f"cannot read {self.home / 'Private' / 'diary.txt'}"))
        self.assertEqual(j.failure["type"], "OSError")
        self.assertEqual(j.failure["step"], "reading folders")
        self.assertNotIn("diary", json.dumps(j.snapshot()))


class NoWmiCrashTest(ScanApiCase):
    """Regression: platform.system()/release() go through _wmi.pyd on Windows (Python 3.12), which crashed the whole server
    (access violation 0xc0000005) when /api/info ran in parallel with other requests."""

    def test_no_wmi_backed_platform_calls(self):
        rx = re.compile(r"\bplatform\.(system|release|version|uname|machine|processor|win32_ver|win32_edition|node|platform)\(")
        for f in [pathlib.Path(ROOT, "server.py"), *pathlib.Path(ROOT, "core").glob("*.py"), *pathlib.Path(ROOT, "tools").glob("*.py")]:
            self.assertIsNone(rx.search(f.read_text(encoding="utf-8")), f"{f.name} calls a WMI-backed platform function")

    def test_info_in_parallel(self):
        results = []
        threads = [threading.Thread(target=lambda: results.append(self.get("/api/info")[0])) for _ in range(40)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(30)
        self.assertEqual(results, [200] * 40)
        self.assertTrue(self.get("/api/info")[1]["os_name"])


class StartupTest(unittest.TestCase):
    def test_server_start_does_not_wait_for_a_dns_lookup(self):
        # Why: HTTPServer.server_bind calls socket.getfqdn(); on macOS that made every start take about 37 s.
        import socket
        import server
        with mock.patch.object(socket, "getfqdn", side_effect=AssertionError("getfqdn called")):
            srv, port = server.make_server(8970)
        try:
            self.assertEqual(srv.server_port, port)
        finally:
            srv.server_close()


class SingleInstanceTest(TempHomeCase):
    def test_second_server_opens_the_first(self):
        env = dict(os.environ, USERPROFILE=str(self.home), HOME=str(self.home), PYTHONIOENCODING="utf-8")
        a = subprocess.Popen([sys.executable, os.path.join(ROOT, "server.py"), "--no-browser", "--port", "8950"], env=env,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8")
        try:
            lock_dir = self.home / f".{config.APP_SLUG}"
            t0 = time.time()
            while not (lock_dir / instance.PORT_FILE_NAME).exists() and time.time() - t0 < 20:
                time.sleep(0.1)
            if not (lock_dir / instance.PORT_FILE_NAME).exists():   # say why, with the first server's own output
                a.terminate()
                self.fail(f"the first server did not start within 20 s: {a.communicate(timeout=10)[0][-1500:]}")
            b = subprocess.run([sys.executable, os.path.join(ROOT, "server.py"), "--no-browser", "--port", "8951"], env=env,
                               capture_output=True, text=True, encoding="utf-8", timeout=30)
            self.assertEqual(b.returncode, 0, b.stderr)
            self.assertIn("already running", b.stdout)
            self.assertIn("localhost:895", b.stdout)
        finally:
            a.terminate()
            a.wait(10)
            if a.stdout:
                a.stdout.close()


if __name__ == "__main__":
    unittest.main()
