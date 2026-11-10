"""Web security: local-only checks, token, signed links, headers, limits, traversal, rate limits, generic errors, redaction."""
import json
import logging
import os
import subprocess
import sys
import threading
import time
import unittest
import urllib.error
import urllib.request

from tests import fixtures as fx
from tests.base import TempHomeCase
from core import config, index_db, log as alog, scanner, signing
from core.web import Handler

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOKEN = "test-token-123"


class ServerCase(TempHomeCase):
    """Why: a real HTTP server on a free loopback port, with the test's private HOME."""

    def setUp(self):
        super().setUp()
        import server
        self.server_mod = server
        server.prepare()
        Handler.token = TOKEN
        self.srv, self.port = server.make_server(8900)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        super().tearDown()

    def req(self, path, body=None, headers=None, method=None, raw=None, host=None):
        h = {"Host": host or f"127.0.0.1:{self.port}", config.TOKEN_HEADER: TOKEN, "Content-Type": "application/json"}
        h.update(headers or {})
        h = {k: v for k, v in h.items() if v is not None}
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        r = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=data, headers=h, method=method)
        try:
            with urllib.request.urlopen(r) as resp:
                return resp.status, dict(resp.headers), resp.read()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read()

    def scan_fixture(self):
        self.make("Pics/a.png", fx.png())
        self.make("Pics/b.jpg", fx.jpeg())
        job = scanner.start("deep", [str(self.home / "Pics")], [])
        while job.state in ("running", "paused"):
            time.sleep(0.02)
        return index_db.files_page({"scope": "all"})["rows"]


class RequestRulesTest(ServerCase):
    def test_host_origin_token_and_fetch_site(self):
        self.assertEqual(self.req("/api/info")[0], 200)
        self.assertEqual(self.req("/api/info", host="evil.example:80")[0], 403, "DNS-rebinding style Host is refused")
        self.assertEqual(self.req("/api/info", headers={"Origin": "http://evil.example"})[0], 403)
        self.assertEqual(self.req("/api/info", headers={config.TOKEN_HEADER: None})[0], 401)
        self.assertEqual(self.req("/api/info", headers={config.TOKEN_HEADER: "wrong"})[0], 401)
        self.assertEqual(self.req("/api/info", headers={"Sec-Fetch-Site": "cross-site"})[0], 403)

    def test_bodies_and_inputs(self):
        before = self.req("/api/settings")[2]
        big = b'{"skip": ["' + b"x" * (config.MAX_BODY_BYTES + 10) + b'"]}'
        try:
            code = self.req("/api/settings", raw=big, method="POST")[0]
        except (ConnectionError, urllib.error.URLError):
            code = 413   # the server refused and closed the connection before the upload finished
        self.assertEqual(code, 413)
        self.assertEqual(self.req("/api/settings")[2], before, "an oversized request changes nothing")
        code, _, body = self.req("/api/settings", raw=b"{not json", method="POST")
        self.assertEqual((code, json.loads(body)["error"]), (400, "Malformed request."))
        code, _, body = self.req("/api/files?page=abc")
        self.assertEqual((code, json.loads(body)["error"]), (400, "Invalid request."), "parser errors are generic")
        self.assertEqual(self.req("/api/nope")[0], 404)
        code, _, body = self.req("/api/files?type=<script>")
        self.assertEqual(code, 400)
        self.assertNotIn(b"<script>", body)

    def test_sql_injection_payloads_are_inert(self):
        self.scan_fixture()
        before = index_db.summary()["total"]
        for qs in ("q=x%27%20OR%201%3D1--", "folder=%27%29%20OR%201%3D1--", "q=%25", "q=_", "sort=size%3BDROP%20TABLE%20files",
                   "datefield=mtime;DROP", "format=png%27--", "type=Images%27%20OR%20%271%27%3D%271"):
            code, _, body = self.req("/api/files?" + qs)
            self.assertIn(code, (200, 400), qs)
            if code == 200:
                self.assertEqual(json.loads(body)["total"], 0, qs)
        index_db.bump()
        self.assertEqual(index_db.summary()["total"], before, "tables are intact")

    def test_static_traversal_is_blocked(self):
        for p in ("/../server.py", "/%2e%2e/server.py", "/css/../../server.py", "/..%5cserver.py", "/js/%2e%2e/%2e%2e/core/config.py"):
            self.assertEqual(self.req(p)[0], 404, p)

    def test_security_headers_everywhere(self):
        for path in ("/", "/js/app.js", "/api/info"):
            _, h, _ = self.req(path)
            self.assertIn("default-src 'self'", h["Content-Security-Policy"], path)
            self.assertNotIn("unsafe-inline", h["Content-Security-Policy"], path)
            for k, v in (("X-Content-Type-Options", "nosniff"), ("Referrer-Policy", "no-referrer"), ("X-Frame-Options", "DENY"),
                         ("Cross-Origin-Resource-Policy", "same-origin")):
                self.assertEqual(h.get(k), v, f"{path} {k}")
            self.assertIn("camera=()", h["Permissions-Policy"])

    def test_token_only_in_the_page_never_in_links(self):
        rows = self.scan_fixture()
        _, _, body = self.req("/api/files?type=Images")
        self.assertNotIn(TOKEN.encode(), body)
        self.assertTrue(all("sig=" in r["thumb"] and "exp=" in r["thumb"] for r in json.loads(body)["rows"]))
        self.assertTrue(rows)

    def test_rate_limit(self):
        codes = [self.req("/api/execute", {"dest": "", "mode": "move"}, method="POST")[0] for _ in range(config.RATE_LIMITS["execute"][0] + 2)]
        self.assertIn(429, codes)
        self.assertEqual(codes[0], 400)

    def test_errors_never_leak_internals(self):
        def boom(h, qs, b):
            raise RuntimeError(r"secret C:\Users\x\stack")
        Handler.routes["GET boom"] = boom
        try:
            code, _, body = self.req("/api/boom")
        finally:
            del Handler.routes["GET boom"]
        self.assertEqual(code, 500)
        self.assertNotIn(b"secret", body)
        self.assertNotIn(b"Users", body)


class SignedLinkTest(ServerCase):
    def test_signed_thumbnail_links(self):
        rows = self.scan_fixture()
        png = [r for r in rows if r["name"] == "a.png"][0]
        good = signing.url("thumb", png["id"])
        self.assertEqual(self.req(good, headers={config.TOKEN_HEADER: None})[0], 200, "a signed link works without the token")
        expired = signing.url("thumb", png["id"], ttl=-10)
        self.assertEqual(self.req(expired, headers={config.TOKEN_HEADER: None})[0], 403)
        tampered = good[:-1] + ("0" if good[-1] != "0" else "1")
        self.assertEqual(self.req(tampered, headers={config.TOKEN_HEADER: None})[0], 403)
        other = [r for r in rows if r["name"] == "b.jpg"][0]
        swapped = good.replace(f"id={png['id']}", f"id={other['id']}")
        self.assertEqual(self.req(swapped, headers={config.TOKEN_HEADER: None})[0], 403, "a link is bound to one file")
        _, h, _ = self.req(good, headers={config.TOKEN_HEADER: None})
        self.assertEqual(h["Content-Security-Policy"], "sandbox")

    def test_verify_unit(self):
        u = signing.url("file", 7, now=1000)
        q = dict(p.split("=") for p in u.split("?")[1].split("&"))
        self.assertTrue(signing.verify("file", 7, q["exp"], q["sig"], now=1000))
        self.assertFalse(signing.verify("thumb", 7, q["exp"], q["sig"], now=1000))
        self.assertFalse(signing.verify("file", 7, q["exp"], q["sig"], now=1000 + config.SIGNED_URL_TTL_S + 1))


class ProcessTest(TempHomeCase):
    def test_refuses_non_loopback_bind(self):
        r = subprocess.run([sys.executable, os.path.join(ROOT, "server.py"), "--host", "0.0.0.0", "--no-browser"], capture_output=True, text=True, timeout=30)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("127.0.0.1", r.stderr + r.stdout)

    def test_log_redaction(self):
        alog.add_secret("SUPERSECRETTOKEN")
        rec = logging.LogRecord("x", logging.INFO, "", 0, "token %s at %s", ("SUPERSECRETTOKEN", str(config.HOME / "Documents")), None)
        alog._redactor.filter(rec)
        self.assertNotIn("SUPERSECRETTOKEN", rec.msg)
        self.assertNotIn(str(config.HOME), rec.msg)
        self.assertIn("~", rec.msg)

    def test_private_data_folder(self):
        from core.platform_utils import make_private
        d = self.home / "private"
        d.mkdir()
        make_private(d, is_dir=True)
        if config.WIN:
            out = subprocess.run(["icacls", str(d)], capture_output=True, text=True).stdout
            self.assertNotIn("(I)", out, "inherited permissions were removed")
            self.assertNotIn("BUILTIN\\Users", out)
            self.assertNotIn("Everyone", out)
        else:
            self.assertEqual(os.stat(d).st_mode & 0o777, 0o700)


if __name__ == "__main__":
    unittest.main()
