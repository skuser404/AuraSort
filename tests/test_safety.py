"""Project detection, protected locations, safe names and path containment."""
import os
import unittest

from tests.base import TempHomeCase
from core import config, safety
from core.platform_utils import within


class ProjectDetectionTest(unittest.TestCase):
    def test_project_markers(self):
        for names in ({"package.json", "a.png"}, {".git"}, {"pom.xml"}, {"requirements.txt"}, {"Cargo.toml"}, {"App.sln"},
                      {"Web.csproj"}, {"pubspec.yaml"}, {"edit.prproj"}, {"comp.aep"}, {"scene.blend"}, {"song.als"}):
            self.assertTrue(safety.is_project(names), names)

    def test_website_folder(self):
        self.assertTrue(safety.is_project({"index.html", "css", "js"}))
        self.assertTrue(safety.is_project({"INDEX.HTML", "assets"}))
        self.assertFalse(safety.is_project({"index.html", "photos"}))

    def test_plain_folder_is_not_a_project(self):
        self.assertFalse(safety.is_project({"IMG_1.jpg", "notes.txt", "song.mp3"}))

    def test_asset_like_folders(self):
        for name in ("assets", "icons", "public", "static", "res", "drawable-hdpi", "mipmap-xxhdpi", "thumbnails"):
            self.assertTrue(safety.is_asset_dir(os.path.join("x", name)), name)
        self.assertFalse(safety.is_asset_dir(os.path.join("x", "Holiday 2025")))
        self.assertEqual(safety.folder_kind("/x/assets", -1), "assets")
        self.assertEqual(safety.folder_kind("/x/photos", 2), "project")
        self.assertEqual(safety.folder_kind("/x/photos", -1), "ok")


class ProtectedPathTest(TempHomeCase):
    def test_tool_folders_anywhere(self):
        for name in ("node_modules", ".git", "venv", ".venv", "__pycache__", "AppData", "site-packages"):
            self.assertTrue(safety.is_protected(str(self.home / "proj" / name)), name)

    def test_ordinary_folders_are_free(self):
        for name in ("Downloads", "information", "Recovery notes", "volume", "system"):
            self.assertFalse(safety.is_protected(str(self.home / name)), name)

    def test_drive_root_system_folders(self):
        root = os.path.abspath(os.sep)
        self.assertTrue(safety.is_protected(os.path.join(root, "$Recycle.Bin")))
        self.assertTrue(safety.is_protected(os.path.join(root, "System Volume Information")))
        self.assertFalse(safety.is_protected(str(self.home / "Recovery")))   # only at a drive root

    def test_os_system_trees(self):
        if config.WIN and os.environ.get("WINDIR"):
            self.assertTrue(safety.is_protected(os.path.join(os.environ["WINDIR"], "System32")))
            self.assertTrue(safety.is_protected(os.environ.get("ProgramFiles", r"C:\Program Files")))
        elif config.MAC:
            self.assertTrue(safety.is_protected("/System/Library"))
        else:
            self.assertTrue(safety.is_protected("/usr/bin"))

    @unittest.skipUnless(config.WIN and os.environ.get("ProgramFiles"), "8.3 short names are a Windows feature")
    def test_short_names_cannot_bypass_protection(self):
        import ctypes
        long_path = os.environ["ProgramFiles"]
        buf = ctypes.create_unicode_buffer(260)
        ctypes.windll.kernel32.GetShortPathNameW(long_path, buf, 260)
        if not buf.value or buf.value.lower() == long_path.lower():
            self.skipTest("8.3 names are disabled on this volume")
        self.assertTrue(safety.is_protected(safety.canonical(buf.value)))
        with self.assertRaises(ValueError):
            safety.check_destination(os.path.join(buf.value, "Sorted"))

    def test_own_data_folder_is_protected(self):
        self.assertTrue(safety.is_protected(str(config.DATA_DIR / "history")))

    def test_app_bundles(self):
        bundle = self.home / "Tools.app"
        bundle.mkdir()
        self.assertIn("bundle", safety.protection_reason(str(bundle)))


class NamesAndPathsTest(TempHomeCase):
    def test_safe_folder_names(self):
        self.assertEqual(safety.safe_folder_name("  Holiday 2025 "), "Holiday 2025")
        for bad in ("", ".", "..", "a/b", "a\\b", "con", "NUL.txt", "lpt1", "what?", "trailing.", "x" * 300, "a:b"):
            self.assertIsNone(safety.safe_folder_name(bad), bad)

    def test_clean_part(self):
        self.assertEqual(safety.clean_part('bad:name*'), "bad-name-")
        self.assertEqual(safety.clean_part(".."), "_")
        self.assertEqual(safety.clean_part("con"), "_con")

    def test_unique_name_never_overwrites(self):
        d = self.home / "d"
        d.mkdir()
        (d / "a.jpg").write_bytes(b"1")
        (d / "a (1).jpg").write_bytes(b"2")
        self.assertEqual(safety.unique_name(str(d), "a.jpg"), "a (2).jpg")
        self.assertEqual(safety.unique_name(str(d), "b.jpg"), "b.jpg")

    def test_unique_name_is_case_insensitive_where_the_disk_is(self):
        d = self.home / "c"
        d.mkdir()
        (d / "Photo.JPG").write_bytes(b"1")
        if os.path.exists(str(d / "photo.jpg")):   # case-insensitive file system (Windows/macOS default)
            self.assertEqual(safety.unique_name(str(d), "photo.jpg"), "photo (1).jpg")

    def test_containment_blocks_traversal(self):
        root = self.home / "dest"
        root.mkdir()
        self.assertTrue(safety.real_inside(str(root / "a" / "b"), str(root)))
        self.assertFalse(safety.real_inside(str(root / ".." / "elsewhere"), str(root)))
        self.assertFalse(within(str(self.home / "destination2"), str(root)))

    def test_symlink_escape_is_detected(self):
        root, outside = self.home / "root", self.home / "outside"
        root.mkdir()
        outside.mkdir()
        try:
            os.symlink(str(outside), str(root / "link"), target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("creating symlinks needs extra privileges here")
        self.assertFalse(safety.real_inside(str(root / "link" / "x.txt"), str(root)))

    def test_plain_file_check(self):
        f = self.make("f.txt")
        self.assertTrue(safety.is_plain_file(f))
        self.assertFalse(safety.is_plain_file(str(self.home)))
        self.assertFalse(safety.is_plain_file(str(self.home / "missing.txt")))

    def test_check_destination(self):
        self.assertTrue(safety.check_destination(str(self.home / config.DEST_FOLDER_NAME)).endswith(config.DEST_FOLDER_NAME))
        for bad in ("", "relative/path", str(self.home), os.path.abspath(os.sep), str(config.DATA_DIR)):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                safety.check_destination(bad)
        f = self.make("file.txt")
        with self.assertRaises(ValueError):
            safety.check_destination(f)


if __name__ == "__main__":
    unittest.main()
