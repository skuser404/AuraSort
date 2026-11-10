"""Classification: every extension lands in exactly one category; view-only rules; open/preview allow-lists."""
import unittest

from tests.base import TempHomeCase  # noqa: F401  (sets sys.path)
from core import classify


class ClassifyTest(unittest.TestCase):
    def test_all_categories_exist_in_order(self):
        self.assertEqual(classify.CATEGORY_NAMES, (
            "Images", "Videos", "Audio", "Documents", "PDFs", "Sheets & Slides", "Archives", "Installers & Apps",
            "Disk images", "Code & Scripts", "Text & Logs", "Fonts", "Databases", "Other"))

    def test_spec_extensions(self):
        cases = {
            "photo.JPG": "Images", "clip.mp4": "Videos", "song.mp3": "Audio", "notes.txt": "Documents", "letter.docx": "Documents",
            "book.epub": "Documents", "paper.pdf": "PDFs", "budget.xlsx": "Sheets & Slides", "deck.key": "Sheets & Slides",
            "data.csv": "Sheets & Slides", "backup.zip": "Archives", "setup.exe": "Installers & Apps", "app.apk": "Installers & Apps",
            "app.ipa": "Installers & Apps", "tool.dmg": "Installers & Apps", "pkg.deb": "Installers & Apps", "ubuntu.iso": "Disk images",
            "disk.vhd": "Disk images", "card.img": "Disk images", "main.py": "Code & Scripts", "run.ps1": "Code & Scripts",
            "query.sql": "Code & Scripts", "build.bat": "Code & Scripts", "server.log": "Text & Logs", "conf.yml": "Text & Logs",
            "a.json": "Text & Logs", "font.ttf": "Fonts", "font.woff2": "Fonts", "store.sqlite": "Databases", "x.unknownext": "Other",
            "Makefile": "Other", ".bashrc": "Other",
        }
        for name, cat in cases.items():
            with self.subTest(name=name):
                self.assertEqual(classify.classify(name)[1], cat)

    def test_extension_parsing(self):
        self.assertEqual(classify.ext_of("archive.tar.gz"), "gz")
        self.assertEqual(classify.ext_of(".bashrc"), "")
        self.assertEqual(classify.ext_of("file."), "")
        self.assertEqual(classify.ext_of("IMG_1.JPeG"), "jpeg")

    def test_view_only(self):
        for cat in ("Code & Scripts", "Installers & Apps", "Disk images", "Fonts", "Databases", "Text & Logs", "Other"):
            self.assertTrue(classify.is_view_only(cat), cat)
        for cat in ("Images", "Videos", "Audio", "Documents", "PDFs", "Sheets & Slides", "Archives"):
            self.assertFalse(classify.is_view_only(cat), cat)

    def test_subcategories(self):
        self.assertEqual(classify.classify("IMG_2031.jpg")[2], "Camera")
        self.assertEqual(classify.classify("Screenshot 2024-01-01.png")[2], "Screenshots")
        self.assertEqual(classify.classify("invoice_march.pdf")[2], "Invoices & receipts")

    def test_open_blocklist(self):
        for ext in ("exe", "msi", "bat", "cmd", "ps1", "vbs", "js", "jse", "wsf", "scr", "com", "jar", "apk", "dmg", "pkg",
                    "app", "sh", "lnk", "reg", "hta", "dll", "py"):
            self.assertFalse(classify.can_open(ext), ext)
        for ext in ("xlsx", "docx", "pdf", "jpg", "mp4"):
            self.assertTrue(classify.can_open(ext), ext)
        self.assertIn("xlsm", classify.MACRO_OFFICE)

    def test_preview_never_serves_html(self):
        self.assertEqual(classify.preview_mime("html"), "text/plain; charset=utf-8")
        self.assertEqual(classify.preview_mime("svg"), "image/svg+xml")
        self.assertIsNone(classify.preview_mime("exe"))
        self.assertEqual(classify.preview_kind("mp4"), "video")
        self.assertEqual(classify.preview_kind("xlsx"), "none")


if __name__ == "__main__":
    unittest.main()
