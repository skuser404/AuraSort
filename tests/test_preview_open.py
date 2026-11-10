"""Preview panel data, streaming with HTTP ranges, safe 'Open file', calendar/timeline counts and 'select all' ids."""
import json
import os
import time
import unittest
from unittest import mock

from tests import fixtures as fx
from tests.test_web_security import ServerCase, TOKEN
from core import config, index_db, platform_utils, scanner, signing


def local_ts(y, m, d, hh=12):
    return time.mktime((y, m, d, hh, 0, 0, 0, 0, -1))


class PreviewCase(ServerCase):
    def scan(self, files):
        """Write (relative path, bytes, mtime or None) under Lib/ and index it; returns rows by name."""
        for rel, data, when in files:
            p = self.make("Lib/" + rel, data)
            if when:
                os.utime(p, (when, when))
        job = scanner.start("deep", [str(self.home / "Lib")], [])
        while job.state in ("running", "paused"):
            time.sleep(0.02)
        return {r["name"]: r for r in index_db.files_page({"scope": "all"}, per=500)["rows"]}

    def get_json(self, path):
        st, _, body = self.req(path)
        self.assertEqual(st, 200, body)
        return json.loads(body)


class StreamTest(PreviewCase):
    def test_range_requests_and_headers(self):
        rows = self.scan([("tone.wav", fx.wav(4000), None), ("doc.pdf", fx.pdf(), None), ("app.exe", fx.exe(), None)])
        raw = (self.home / "Lib" / "tone.wav").read_bytes()
        url = signing.url("file", rows["tone.wav"]["id"])
        st, h, body = self.req(url, headers={config.TOKEN_HEADER: None})   # signed links need no token header
        self.assertEqual((st, h["Content-Type"], body), (200, "audio/wav", raw))
        self.assertEqual(h["Accept-Ranges"], "bytes")
        self.assertIn("sandbox", h["Content-Security-Policy"])
        st, h, body = self.req(url, headers={"Range": "bytes=10-19"})
        self.assertEqual((st, h["Content-Range"], body), (206, f"bytes 10-19/{len(raw)}", raw[10:20]))
        self.assertEqual(self.req(url, headers={"Range": "bytes=-5"})[2], raw[-5:])
        self.assertEqual(self.req(url, headers={"Range": f"bytes={len(raw) - 3}-"})[2], raw[-3:])
        st, h, _ = self.req(url, headers={"Range": f"bytes={len(raw)}-"})
        self.assertEqual((st, h["Content-Range"]), (416, f"bytes */{len(raw)}"))
        st, h, body = self.req(url, method="HEAD")
        self.assertEqual((st, body, h["Content-Length"]), (200, b"", str(len(raw))))

    def test_pdf_framing_programs_and_signatures(self):
        rows = self.scan([("doc.pdf", fx.pdf(), None), ("app.exe", fx.exe(), None), ("pic.png", fx.png(), None)])
        st, h, _ = self.req(signing.url("file", rows["doc.pdf"]["id"]))
        self.assertEqual((st, h["X-Frame-Options"]), (200, "SAMEORIGIN"))
        self.assertIn("frame-ancestors 'self'", h["Content-Security-Policy"])
        self.assertEqual(self.req(signing.url("file", rows["app.exe"]["id"]))[0], 404, "programs are never streamed")
        good = signing.url("file", rows["pic.png"]["id"])
        self.assertEqual(self.req(good)[0], 200)
        self.assertEqual(self.req(good[:-4] + "0000")[0], 403, "tampered signature")
        self.assertEqual(self.req(signing.url("thumb", rows["pic.png"]["id"]).replace("/api/thumb", "/api/file"))[0], 403, "a thumbnail link can't fetch the file")
        expired = signing.url("file", rows["pic.png"]["id"], ttl=-5)
        self.assertEqual(self.req(expired)[0], 403, "expired link")


class PreviewDataTest(PreviewCase):
    def test_kinds_text_and_flags(self):
        rows = self.scan([("notes.txt", b"hello\nworld\n", None), ("big.log", b"a" * (config.TEXT_PREVIEW_BYTES + 50), None),
                          ("blob.txt", b"\x00\x01binary", None), ("u16.txt", "héllo".encode("utf-16"), None),
                          ("pic.png", fx.png(), None), ("x.exe", fx.exe(), None), ("m.xlsm", fx.xlsx(), None)])
        get = lambda n: self.get_json(f"/api/preview?id={rows[n]['id']}")
        d = get("notes.txt")
        self.assertEqual((d["kind"], d["text"], d["truncated"]), ("text", "hello\nworld\n", False))
        d = get("big.log")
        self.assertTrue(d["truncated"])
        self.assertEqual(len(d["text"]), config.TEXT_PREVIEW_BYTES)
        self.assertEqual(get("blob.txt")["kind"], "none", "binary data is never shown as text")
        self.assertEqual(get("u16.txt")["text"], "héllo")
        d = get("pic.png")
        self.assertEqual(d["kind"], "image")
        self.assertIn("sig=", d["src"])
        self.assertNotIn(TOKEN, json.dumps(d))
        d = get("x.exe")
        self.assertTrue(d["open_block"])
        self.assertNotIn("src", d)
        self.assertTrue(get("m.xlsm")["macro"])
        os.remove(self.home / "Lib" / "notes.txt")
        self.assertEqual(get("notes.txt")["kind"], "missing")
        self.assertEqual(self.req("/api/preview?id=999999")[0], 404)


class OpenFileTest(PreviewCase):
    def test_never_opens_programs_and_asks_for_macros(self):
        rows = self.scan([("a.pdf", fx.pdf(), None), ("run.exe", fx.exe(), None), ("s.ps1", b"Write-Host hi", None), ("noext", b"x", None),
                          ("m.xlsm", fx.xlsx(), None), ("disk.iso", fx.iso(), None), ("link.lnk", b"L\x00\x00\x00", None)])
        opened = []
        with mock.patch.object(platform_utils, "open_file", opened.append):
            for n in ("run.exe", "s.ps1", "noext", "disk.iso", "link.lnk"):
                st, _, body = self.req("/api/open", {"id": rows[n]["id"]})
                self.assertEqual(st, 400, n)
                self.assertIn("Open location", json.loads(body)["error"])
            self.assertEqual(self.req("/api/open", {"id": rows["m.xlsm"]["id"]})[0], 409, "macro files need a confirmation")
            self.assertEqual(self.req("/api/open", {"id": rows["m.xlsm"]["id"], "macro_ok": True})[0], 200)
            self.assertEqual(self.req("/api/open", {"id": rows["a.pdf"]["id"]})[0], 200)
            self.assertEqual(self.req("/api/open", {"id": rows["a.pdf"]["id"]}, headers={config.TOKEN_HEADER: None})[0], 401)
        self.assertEqual([os.path.basename(p) for p in opened], ["m.xlsm", "a.pdf"])

    @unittest.skipIf(config.WIN, "the executable bit only exists on macOS/Linux")
    def test_executable_bit_blocks_open(self):
        rows = self.scan([("tool.txt", b"#!/bin/sh\necho hi\n", None)])
        os.chmod(self.home / "Lib" / "tool.txt", 0o755)
        with mock.patch.object(platform_utils, "open_file") as op:
            self.assertEqual(self.req("/api/open", {"id": rows["tool.txt"]["id"]})[0], 400)
            op.assert_not_called()


class DatesTest(PreviewCase):
    def test_calendar_timeline_ids_and_nearest_days(self):
        self.scan([("a.txt", b"a", local_ts(2025, 3, 14, 0)), ("b.txt", b"bb", local_ts(2025, 3, 14, 23)),
                   ("c.txt", b"ccc", local_ts(2025, 3, 20)), ("d.png", fx.png(), local_ts(2024, 12, 31, 23))])
        self.assertEqual(self.get_json("/api/calendar?year=2025")["days"], [["2025-03-14", 2, 3], ["2025-03-20", 1, 3]])
        self.assertEqual(self.get_json("/api/calendar?year=2025&type=Images")["days"], [])
        self.assertEqual([m[:2] for m in self.get_json("/api/timeline")["months"]], [["2024-12", 1], ["2025-03", 3]])
        self.assertEqual(self.req("/api/calendar?year=1800")[0], 400)
        ids = self.get_json("/api/files/ids?date=on&from=2025-03-14")
        self.assertEqual((sorted(ids["sizes"]), ids["size"], len(ids["ids"])), ([1, 2], 3, 2))
        self.assertEqual(self.get_json("/api/files?date=on&from=2025-03-17")["nearest"], {"before": "2025-03-14", "after": "2025-03-20"})
        self.assertEqual(self.req("/api/files?date=on&from=2025-13-45")[0], 400, "impossible dates are a friendly 400")


if __name__ == "__main__":
    unittest.main()
