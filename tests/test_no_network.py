"""Fails if AuraSort's runtime code makes (or could make) outgoing network calls: a static scan and a live check."""
import json
import os
import re
import socket
import threading
import time
import unittest
import urllib.request

from tests import fixtures as fx
from tests.base import TempHomeCase
from core import config
from core.web import Handler

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNTIME = [os.path.join(ROOT, "server.py")] + [os.path.join(ROOT, "core", f) for f in os.listdir(os.path.join(ROOT, "core")) if f.endswith(".py")]
for base, _, files in os.walk(os.path.join(ROOT, "docs")):
    RUNTIME += [os.path.join(base, f) for f in files if f.endswith((".js", ".html", ".css"))]
URL_RX = re.compile(r"https?://[^\s'\"<>)`]+")
ALLOWED_URL_PREFIXES = ("http://www.w3.org/", "http://localhost", "http://127.0.0.1", "http://${", "http://{h}:")  # SVG namespace + local origins
NETWORK_APIS = re.compile(r"\b(urllib\.request|http\.client|requests\.(get|post|put|delete|Session)|socket\.create_connection|smtplib|ftplib|"
                          r"XMLHttpRequest|navigator\.sendBeacon|WebSocket\(|EventSource\()")
LOOPBACK = ("127.0.0.1", "::1", "localhost")
# The one exception: optional Document Insights. Only core/llm.py may open connections (to 127.0.0.1 in local mode, or to the
# cloud API the user connected and confirmed), and these links are only shown to the user (download / API-key pages, preset).
NETWORK_MODULES = {os.path.join("core", "llm.py")}
SHOWN_LINKS = {os.path.join("core", "config.py"): {"https://ollama.com/download", "https://lmstudio.ai", "https://api.deepseek.com",
                                                   "https://platform.deepseek.com/api_keys"}}


class StaticNoNetworkTest(unittest.TestCase):
    def test_no_external_urls_or_network_apis_in_runtime_code(self):
        problems = []
        for path in RUNTIME:
            rel = os.path.relpath(path, ROOT)
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            for u in URL_RX.findall(text):
                if not u.startswith(ALLOWED_URL_PREFIXES) and u not in SHOWN_LINKS.get(rel, ()):
                    problems.append(f"{rel}: {u}")
            if rel not in NETWORK_MODULES:
                for m in NETWORK_APIS.finditer(text):
                    problems.append(f"{rel}: uses {m.group(0)}")
        self.assertEqual(problems, [], "runtime code must not reference external hosts or network APIs")

    def test_only_the_ai_client_imports_network_code(self):
        users = []
        for p in RUNTIME:
            if p.endswith(".py"):
                with open(p, encoding="utf-8") as fh:
                    if re.search(r"^import urllib\.request|^from urllib import request", fh.read(), re.M):
                        users.append(os.path.relpath(p, ROOT))
        self.assertEqual(sorted(users), sorted(NETWORK_MODULES))

    def test_no_cdn_fonts_or_scripts(self):
        with open(os.path.join(ROOT, "docs", "index.html"), encoding="utf-8") as fh:
            html = fh.read()
        self.assertNotRegex(html, r"<(script|link)[^>]+(src|href)=\"https?:")
        self.assertNotIn("fonts.googleapis", html)


class LiveNoNetworkTest(TempHomeCase):
    def test_server_never_connects_outside_loopback(self):
        attempts = []
        real_connect = socket.socket.connect

        def guarded(sock, addr):
            host = addr[0] if isinstance(addr, tuple) else addr
            if host not in LOOPBACK:
                attempts.append(addr)
                raise OSError("outgoing network blocked by test")
            return real_connect(sock, addr)
        socket.socket.connect = guarded
        try:
            import server
            from core import scanner
            server.prepare()
            Handler.token = "t"
            srv, port = server.make_server(8950)
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            self.make("Downloads/pic.png", fx.png())
            self.make("Downloads/doc.pdf", fx.pdf())

            def call(path, body=None):
                r = urllib.request.Request(f"http://127.0.0.1:{port}/api/{path}", data=json.dumps(body).encode() if body is not None else None,
                                           headers={config.TOKEN_HEADER: "t", "Host": f"127.0.0.1:{port}", "Content-Type": "application/json"})
                with urllib.request.urlopen(r) as resp:
                    return json.loads(resp.read())
            from core import pin
            pin.lock()
            call("pin/set", {"pin": "4826"})   # the first-run PIN setup, through the API like the UI does it
            for path in ("info", "drives", "settings", "summary", "history?limit=5", "pin/status"):
                call(path)
            call("scan/start", {"mode": "deep", "roots": [str(self.home / "Downloads")]})
            for _ in range(200):
                if call("scan/status")["state"] not in ("running", "paused"):
                    break
                time.sleep(0.05)
            call("files?type=Images")
            call("extensions")
            call("search-index")
            srv.shutdown()
            srv.server_close()
        finally:
            socket.socket.connect = real_connect
            from core import pin
            pin.lock()
        self.assertEqual(attempts, [], "no outgoing connections")


if __name__ == "__main__":
    unittest.main()
