"""Integrity checks: healthy files are never flagged; every broken sample gets the right reason; files are never modified."""
import hashlib
import os
import unittest
from pathlib import Path

from tests import fixtures as fx
from tests.base import TempHomeCase
from core import integrity

HEALTHY = {
    "photo.jpg": fx.jpeg(), "image.png": fx.png(), "anim.gif": fx.gif(), "sound.wav": fx.wav(), "pic.webp": fx.webp(),
    "paint.bmp": fx.bmp(), "doc.pdf": fx.pdf(3), "archive.zip": fx.zip_file(), "letter.docx": fx.docx(), "sheet.xlsx": fx.xlsx(),
    "app.apk": fx.apk(), "old.doc": fx.ole(), "clip.mp4": fx.mp4(), "clip.mkv": fx.mkv(), "song.mp3": fx.mp3(),
    "song.flac": fx.flac(), "voice.ogg": fx.ogg(), "setup.exe": fx.exe(), "pack.7z": fx.sevenz(), "pack.rar": fx.rar5(),
    "data.gz": fx.gz(), "bundle.tar": fx.tar_file(), "disc.iso": fx.iso(), "notes.txt": b"just some text\n" * 20,
}


class IntegrityTest(TempHomeCase):
    def check(self, name, data, deep=True):
        path = self.make("samples/" + name, data)
        return integrity.check(path, deep=deep)

    def codes(self, name, data, deep=True):
        return [f["code"] for f in self.check(name, data, deep)["findings"]]

    def test_healthy_files_are_not_flagged(self):
        for name, data in HEALTHY.items():
            for deep in (False, True):
                with self.subTest(name=name, deep=deep):
                    res = self.check(name, data, deep)
                    self.assertEqual(res["status"], "ok", res["findings"])

    def test_generic_problems(self):
        self.assertEqual(self.codes("empty.jpg", b""), ["EMPTY"])
        self.assertEqual(self.codes("zeros.mp4", b"\x00" * 300000), ["NULL_FILLED"])
        self.assertEqual(self.codes("zeros.mp4", b"\x00" * 300000, deep=False), ["NULL_FILLED"])
        self.assertEqual(self.codes("movie.mp4.part", b"partial"), ["PARTIAL_DOWNLOAD"])
        self.assertEqual(self.codes("setup.exe.crdownload", b"MZ" + b"\x00" * 100), ["PARTIAL_DOWNLOAD"])

    def test_png_renamed_jpg_is_only_a_warning(self):
        res = self.check("really_png.jpg", fx.png())
        self.assertEqual([f["code"] for f in res["findings"]], ["EXT_MISMATCH"])
        self.assertEqual(res["findings"][0]["sev"], integrity.WARNING)
        self.assertIn("PNG", res["findings"][0]["detail"])

    def test_truncated_jpeg(self):
        data = fx.jpeg()[:-40]
        for deep in (False, True):
            self.assertEqual(self.codes("cut.jpg", data, deep), ["JPEG_NO_EOI"])
        f = self.check("cut.jpg", data)["findings"][0]
        self.assertEqual(f["sev"], integrity.DAMAGED)
        self.assertIn(f"{len(data):,}", f["detail"])

    def test_jpeg_with_appended_data_is_fine(self):
        self.assertEqual(self.codes("motion.jpg", fx.jpeg() + b"\x00\x00\x00\x18ftypmp42" + b"\x11" * 70000, deep=False), [])

    def test_png_bad_crc_needs_deep_mode(self):
        self.assertEqual(self.codes("crc.png", fx.png_bad_crc(), deep=False), [])
        self.assertEqual(self.codes("crc.png", fx.png_bad_crc(), deep=True), ["PNG_BAD_CRC"])

    def test_truncated_png(self):
        self.assertEqual(self.codes("cut.png", fx.png()[:-20]), ["PNG_TRUNCATED"])

    def test_pdf_cut_before_eof(self):
        data = fx.pdf(3)
        self.assertEqual(self.codes("cut.pdf", data[: data.rfind(b"startxref")], deep=False), ["PDF_NO_EOF"])
        self.assertEqual(self.codes("nohead.pdf", b"garbage" + data[8:], deep=False), ["PDF_NO_HEADER"])

    def test_pdf_bad_xref(self):
        data = fx.pdf(2)
        xref = data.rfind(b"xref\n0 ")
        broken = data[:xref] + b"junk" + data[xref + 4:]
        self.assertEqual(self.codes("xref.pdf", broken), ["PDF_BAD_XREF"])

    def test_zip_family_crc(self):
        self.assertEqual(self.codes("bad.zip", fx.zip_bad_crc(), deep=False), [])
        self.assertEqual(self.codes("bad.zip", fx.zip_bad_crc()), ["ZIP_BAD_CRC"])
        self.assertEqual(self.codes("bad.docx", fx.zip_bad_crc(fx.docx)), ["ZIP_BAD_CRC"])

    def test_zip_truncated_and_missing_parts(self):
        self.assertEqual(self.codes("cut.zip", fx.zip_file()[:-30], deep=False), ["ZIP_NO_CDIR"])
        self.assertEqual(self.codes("plain.docx", fx.zip_file(), deep=False), ["ZIP_MISSING_PART"])
        self.assertEqual(self.codes("noman.apk", fx.zip_file(), deep=False), ["ZIP_MISSING_PART"])

    def test_mp4_without_moov_and_truncated(self):
        self.assertEqual(self.codes("nomoov.mp4", fx.mp4(with_moov=False), deep=False), ["MP4_NO_MOOV"])
        self.assertEqual(self.codes("cut.mp4", fx.mp4(cut=500), deep=False), ["MP4_TRUNCATED"])

    def test_media_containers(self):
        self.assertEqual(self.codes("cut.wav", fx.wav()[:-100], deep=False), ["RIFF_TRUNCATED"])
        self.assertEqual(self.codes("cut.mkv", fx.mkv(cut=50), deep=False), ["MKV_TRUNCATED"])
        self.assertEqual(self.codes("bad.ogg", b"OggX" + fx.ogg()[4:], deep=False), ["OGG_BAD_SIG"])
        ogg = bytearray(fx.ogg())
        ogg[40] ^= 0xFF
        self.assertEqual(self.codes("crc.ogg", bytes(ogg)), ["OGG_BAD_CRC"])
        self.assertEqual(self.codes("cut.flac", fx.flac()[:20], deep=False), ["FLAC_TRUNCATED"])
        self.assertEqual(self.codes("cut.gif", fx.gif()[:-1], deep=False), ["GIF_NO_TRAILER"])
        self.assertEqual(self.codes("cut.bmp", fx.bmp()[:-5], deep=False), ["BMP_TRUNCATED"])

    def test_programs_and_archives(self):
        self.assertEqual(self.codes("cut.exe", fx.exe(cut=100), deep=False), ["PE_TRUNCATED"])
        self.assertEqual(self.codes("nope.exe", b"MZ" + b"\x00" * 200, deep=False), ["PE_BAD_SIG"])
        self.assertEqual(self.codes("cut.7z", fx.sevenz(cut=5), deep=False), ["SEVENZ_TRUNCATED"])
        self.assertEqual(self.codes("cut.gz", fx.gz(cut=10), deep=False), [])
        self.assertEqual(self.codes("cut.gz", fx.gz(cut=10)), ["GZ_TRUNCATED"])
        self.assertEqual(self.codes("cut.rar", fx.rar5()[:-8], deep=False), ["RAR_NO_END"])
        self.assertEqual(self.codes("cut.doc", fx.ole()[:900], deep=False), ["OLE_TRUNCATED"])
        self.assertEqual(self.codes("cut.iso", fx.iso()[:-4096], deep=False), ["ISO_TRUNCATED"])
        tar = bytearray(fx.tar_file())
        tar[0] ^= 0xFF
        self.assertEqual(self.codes("bad.tar", bytes(tar), deep=False), ["TAR_BAD_HEADER"])

    def test_findings_are_complete(self):
        for f in self.check("cut.jpg", fx.jpeg()[:-40])["findings"]:
            for key in ("sev", "code", "detail", "cause", "fix", "conf"):
                self.assertTrue(f[key], key)

    def test_never_modifies_files(self):
        path = self.make("samples/cut.mp4", fx.mp4(cut=300))
        digest = lambda: (hashlib.sha256(Path(path).read_bytes()).hexdigest(), os.path.getmtime(path))  # noqa: E731
        before = digest()
        integrity.check(path, deep=True)
        self.assertEqual(before, digest())

    def test_missing_file_is_skipped_not_flagged(self):
        self.assertEqual(integrity.check(str(self.home / "nope.jpg"))["status"], "skipped")

    def test_every_reason_has_text(self):
        for code, (sev, detail, cause, fix, conf) in integrity.REASONS.items():
            self.assertIn(sev, integrity.SEVERITY_RANK, code)
            self.assertIn(conf, ("high", "medium", "low"), code)
            self.assertTrue(detail and cause and fix, code)


if __name__ == "__main__":
    unittest.main()
