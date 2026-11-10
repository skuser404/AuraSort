"""Trash module: only ever moves to the Recycle Bin/Trash; skips (never deletes) when that is impossible."""
import os
import subprocess
import unittest
import uuid
from unittest import mock

from tests.base import TempHomeCase
from core import config, trash


class TrashLogicTest(TempHomeCase):
    def test_missing_files_are_reported(self):
        res = trash.send_to_trash([str(self.home / "nope.txt")])
        self.assertEqual(res.trashed, [])
        self.assertEqual(res.failed[0][1], "file no longer exists")

    def test_drive_without_bin_is_skipped_not_deleted(self):
        f = self.make("keep.txt", b"important")
        with mock.patch.object(trash, "bin_available", return_value=False):
            res = trash.send_to_trash([f])
        self.assertTrue(os.path.exists(f), "file must still exist")
        self.assertIn("no Recycle Bin", res.failed[0][1])

    def test_windows_flags_ask_before_permanent_delete(self):
        self.assertTrue(trash.WIN_FLAGS & trash.FOF_ALLOWUNDO)
        self.assertTrue(trash.WIN_FLAGS & trash.FOF_WANTNUKEWARNING)

    def test_freedesktop_spec_layout(self):
        f = self.make("docs/report final.pdf", b"%PDF-1.4")
        tdir = str(self.home / "Trash")
        name = trash.freedesktop_trash(f, tdir)
        self.assertFalse(os.path.exists(f))
        self.assertTrue(os.path.exists(os.path.join(tdir, "files", name)))
        with open(os.path.join(tdir, "info", name + ".trashinfo"), encoding="utf-8") as fh:
            info = fh.read()
        self.assertIn("[Trash Info]", info)
        self.assertIn("report%20final.pdf", info)
        self.assertRegex(info, r"DeletionDate=\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d")
        f2 = self.make("docs/report final.pdf", b"again")
        self.assertNotEqual(trash.freedesktop_trash(f2, tdir), name)   # name clash -> new name, nothing overwritten


@unittest.skipUnless(config.WIN and os.environ.get("AURASORT_TEST_RECYCLE_BIN") == "1",
                     "set AURASORT_TEST_RECYCLE_BIN=1 on Windows to test the real Recycle Bin")
class RealRecycleBinTest(TempHomeCase):
    def test_send_and_restore(self):
        name = f"aurasort-trash-test-{uuid.uuid4().hex[:8]}.txt"
        f = self.make(name, b"restore me")
        res = trash.send_to_trash([f])
        self.assertEqual(res.trashed, [os.path.abspath(f)], res.failed)
        self.assertFalse(os.path.exists(f))
        ps = ("$rb=(New-Object -ComObject Shell.Application).Namespace(10);"
              f"$i=$rb.Items()|Where-Object {{ $_.Name -like '{name[:-4]}*' }};"
              "if($i){$i.InvokeVerb('undelete');'restored'}else{'missing'}")
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, timeout=60).stdout
        self.assertIn("restored", out)
        self.assertTrue(os.path.exists(f), "restoring from the Recycle Bin brings the file back")


if __name__ == "__main__":
    unittest.main()
