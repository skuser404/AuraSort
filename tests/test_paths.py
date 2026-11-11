"""Scan roots: every spelling of a drive root becomes X:\\ (never "the current folder on X"), nothing depends on the
folder the server was started from, and the estimate and the real scan agree on the same folder."""
import os
import subprocess
import sys
import time
import unittest
from unittest import mock

from tests.base import TempHomeCase
from tests.test_volume_serial import big_dev_stat
from core import config, index_db, safety, scanner, schema

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class NormalisePathTest(unittest.TestCase):
    @unittest.skipUnless(config.WIN, "Windows drive letters")
    def test_drive_roots(self):
        for raw, want in (("C:", "C:\\"), ("C:\\", "C:\\"), ("c:/", "c:\\"), ("D:", "D:\\"), ("\\\\?\\C:\\", "C:\\")):
            got = os.path.normcase(safety.canonical(schema.norm_path(raw, "roots")))
            self.assertEqual(got, os.path.normcase(want), raw)

    @unittest.skipUnless(config.WIN, "Windows long-path prefix")
    def test_long_prefix_cannot_dodge_the_protection_rules(self):
        """Before: "\\\\?\\C:\\Windows" kept its prefix, so "is this C:\\Windows?" compared different spellings."""
        windir = os.environ.get("WINDIR", "C:\\Windows")
        self.assertTrue(safety.is_protected(safety.canonical("\\\\?\\" + windir)))
        with self.assertRaises(schema.BadRequest) as cm:
            scanner.clean_roots([schema.norm_path("\\\\?\\" + windir, "roots")])
        self.assertEqual(cm.exception.code, "protected")

    def test_spaces_non_ascii_and_dot_dot(self):
        base = "C:\\Users\\Test User" if config.WIN else "/home/Test User"
        sep = "\\" if config.WIN else "/"
        p = schema.norm_path(base + sep + "Ünïcødé Docs" + sep + ".." + sep + "Music", "roots")
        self.assertTrue(p.endswith(sep + "Music") and "Test User" in p and ".." not in p, p)

    def test_posix_roots(self):
        if config.WIN:
            self.skipTest("POSIX paths")
        self.assertEqual(schema.norm_path("/", "roots"), "/")
        self.assertEqual(schema.norm_path("/storage/emulated/0", "roots"), "/storage/emulated/0")

    def test_relative_paths_are_refused(self):
        for raw in ("Music", ".", "..\\x" if config.WIN else "../x"):
            with self.assertRaises(schema.BadRequest):
                schema.norm_path(raw, "roots")


class EstimateMatchesScanTest(TempHomeCase):
    def _fixture(self):
        for i in range(40):
            self.make(f"Docs/{'A' if i % 2 else 'B'} folder/file {i:02d}.txt", b"x" * (i + 1))
        return str(self.home / "Docs")

    def _compare(self):
        root = self._fixture()
        est = scanner.estimate([root])
        job = scanner.start("deep", [root], [])
        while job.state in ("running", "paused"):
            time.sleep(0.02)
        found = index_db.summary()["total"]
        self.assertGreaterEqual(found, 0.9 * est["est_files"], f"estimate {est['est_files']}, scan {found}, skipped {job.extra['skipped']}")
        self.assertEqual(found, 40)

    def test_same_files_as_the_estimate(self):
        self._compare()

    def test_same_files_on_a_drive_with_a_64_bit_serial(self):
        """The friend's screen: estimate "about 7,629 files", scan "0 files". This is that case."""
        with mock.patch("os.stat", big_dev_stat):
            self._compare()


@unittest.skipUnless(config.WIN, "Windows: a terminal opened 'as administrator' starts in C:\\Windows\\System32")
class StartedFromSystem32Test(TempHomeCase):
    def test_scans_do_not_depend_on_the_start_folder(self):
        for i in range(3):
            self.make(f"Downloads/f{i}.txt")
        env = dict(os.environ, USERPROFILE=str(self.home), HOME=str(self.home), PYTHONIOENCODING="utf-8")
        code = ("import sys, time; sys.path.insert(0, sys.argv[1]); import os, server; server.prepare(); os.chdir(server.start_folder());"
                "from core import scanner, index_db; j = scanner.start('deep', ['C:'], [], est_files=0) if False else scanner.start('quick', [], []);\n"
                "while j.state in ('running', 'paused'): time.sleep(0.05)\nprint('CWD', os.getcwd()); print('FOUND', index_db.summary()['total'])")
        r = subprocess.run([sys.executable, "-c", code, ROOT], cwd=os.environ.get("SystemRoot", "C:\\Windows") + "\\System32", env=env,
                           capture_output=True, text=True, encoding="utf-8", timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])
        self.assertIn("FOUND 3", r.stdout, r.stdout + r.stderr[-1000:])
        self.assertNotIn("System32", r.stdout.split("CWD", 1)[1].splitlines()[0])


if __name__ == "__main__":
    unittest.main()
