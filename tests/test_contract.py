"""Front-end <-> server contract: the real request builders (docs/js/api.js, the Scan page's scanRequest) are run in Node
with a stub fetch; every request they make must hit a real route with fields the server schema knows, and every
response field the UI reads must exist in what the server sends. Catches renamed fields (camelCase vs snake_case,
`folders` vs `roots`) and missing keys before a person sees "Unexpected error (KeyError)"."""
import json
import os
import pathlib
import re
import shutil
import subprocess
import time
import unittest

from tests.base import TempHomeCase
from core import config, jobs, platform_utils, schema, scanner

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JS = os.path.join(ROOT, "docs", "js")
NODE = shutil.which("node")

# Runs api.js for real: each RealApi method is called with sample arguments; fetch records the request instead of sending it.
HARNESS = r"""
const fs = require('fs'), vm = require('vm');
const calls = [];
const box = { console, URLSearchParams, JSON, Promise, Object, Array, String, Number, Math, Date, Set, Map, encodeURIComponent,
  document: { querySelector: () => ({ content: 'token' }) }, location: { search: '' }, APP: { name: 'AuraSort' },
  fetch: async (url, opt) => { calls.push({ url, method: opt.method, body: opt.body ? JSON.parse(opt.body) : null }); return { ok: true, json: async () => ({}) } } };
box.window = box; box.self = box;
vm.createContext(box);
const src = fs.readFileSync(process.argv[1] + '/api.js', 'utf8');
vm.runInContext(src + '\n;this.__RealApi = RealApi; this.__qs = typeof qs === "function" ? qs : null;', box);
// the real guarded() wrapper from pin.js (move, copy, delete... get a PIN token); the PIN prompt itself answers "tok" here
const pinSrc = fs.readFileSync(process.argv[1] + '/pin.js', 'utf8');
vm.runInContext('var Pin = { confirm: async () => "tok", onLocked() {} };\n' + pinSrc.match(/async function guarded\([\s\S]*?\n\}/)[0] + '\n;this.guarded = guarded;', box);
const BODY = { __page_body__: 1 };   // marker: this method forwards a body that the page builds
(async () => {
  const api = box.__RealApi, out = {};
  for (const name of Object.keys(api)) {
    const fn = api[name]; if (typeof fn !== 'function') continue;
    calls.length = 0;
    try { await fn(...(fn.length === 0 ? [] : [BODY, 1])) } catch (e) { }
    out[name] = calls.slice(0, 1);
  }
  // the Scan page's request builder, taken from scan.js as written
  const scan = fs.readFileSync(process.argv[1] + '/views/scan.js', 'utf8');
  const grab = re => { const m = scan.match(re); if (!m) throw new Error('not found: ' + re); return m[0] };
  vm.runInContext(grab(/const deepRoots = [^\n]+/) + '\n' + grab(/function scanRequest\(st\) \{[\s\S]*?\n\}/) + '\n;this.__scanRequest = scanRequest;', box);
  const st = (mode, drives, folders, skip, est) => box.__scanRequest({ mode, drives: new Set(drives), folders, skip, est });
  const combos = {
    quick: st('quick', [], [], [], null), deep_folders_only: st('deep', [], ['C:\\Users\\anush\\Music', 'C:\\Users\\anush\\Downloads'], [], null),
    deep_drives: st('deep', ['C:\\', 'D:\\'], [], [], { est_files: 1200 }), deep_both_skip: st('deep', ['C:\\'], ['E:\\Photos'], ['C:\\Temp'], { est_files: 5 }),
    deep_nothing: st('deep', [], [], [], null) };
  process.stdout.write(JSON.stringify({ api: out, scan: combos }));
})();
"""


def read_js(*names):
    return "\n".join(pathlib.Path(JS, n).read_text(encoding="utf-8") for n in names)


def fields_read(src, var):
    """Every `var.field` the UI reads (e.g. s.found, d.root)."""
    return set(re.findall(rf"\b{var}\.([a-z_][a-z0-9_]*)\b", src))


@unittest.skipUnless(NODE, "Node.js is needed to run the real front-end request builders")
class RequestContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        r = subprocess.run([NODE, "-e", HARNESS, JS], capture_output=True, text=True, encoding="utf-8", timeout=60)
        if r.returncode:
            raise AssertionError("contract harness failed:\n" + r.stderr)
        cls.out = json.loads(r.stdout)
        import server
        cls.routes = server.Handler.routes

    def test_every_api_call_hits_a_real_route_with_known_fields(self):
        checked = 0
        for name, calls in self.out["api"].items():
            for c in calls:
                path = c["url"].split("?")[0][len("/api/"):]
                self.assertIn(f"{c['method']} {path}", self.routes, f"API.{name} calls {c['method']} /api/{path}, which the server does not have")
                body = c["body"]
                if c["method"] == "POST" and body and "__page_body__" not in body:
                    unknown = set(body) - set(schema.POST_FIELDS.get(path, ()))
                    self.assertFalse(unknown, f"API.{name} sends {sorted(unknown)} to {path}; the server schema does not read them")
                checked += 1
        self.assertGreater(checked, 40)

    def test_scan_requests_match_the_server_schema(self):
        for label, body in self.out["scan"].items():
            self.assertEqual(set(body), set(schema.POST_FIELDS["scan/start"]), label)
            if label == "deep_nothing":
                with self.assertRaises(schema.BadRequest) as cm:     # the page disables Start for this case; the server agrees
                    schema.scan_request(body)
                self.assertEqual(cm.exception.code, "nothing_selected")
                continue
            if not config.WIN:   # the samples are Windows paths; on macOS/Linux the same folders look like /C/Users/anush/Music
                posix = lambda ps: ["/" + p.replace(":", "").replace("\\", "/").strip("/") for p in ps]
                body = dict(body, roots=posix(body["roots"]), skip=posix(body["skip"]))
            req = schema.scan_request(body)
            self.assertEqual(req["mode"], body["mode"], label)
        self.assertEqual(self.out["scan"]["deep_folders_only"]["roots"], ["C:\\Users\\anush\\Music", "C:\\Users\\anush\\Downloads"])

    def test_page_built_bodies_use_known_fields(self):
        """Object literals passed straight to API.x({...}) in the views use only fields the route reads."""
        method_route = {n: c[0]["url"].split("?")[0][5:] for n, c in self.out["api"].items() if c and c[0]["method"] == "POST"}
        src = "\n".join(open(os.path.join(dp, f), encoding="utf-8").read() for dp, _, fs in os.walk(JS) for f in fs if f.endswith(".js"))
        found = 0
        for m in re.finditer(r"API\.(\w+)\(\{([^{}()]*)\}", src):
            name, inner = m.groups()
            if name not in method_route:
                continue
            keys = {k for k in re.findall(r"(?:^|,)\s*([a-zA-Z_]\w*)\s*(?=[:,]|$)", inner.strip())}
            unknown = keys - set(schema.POST_FIELDS.get(method_route[name], ()))
            self.assertFalse(unknown, f"API.{name}({{...}}) sends {sorted(unknown)}; /api/{method_route[name]} does not read them")
            found += 1
        self.assertGreater(found, 5)


class ServerSchemaTest(unittest.TestCase):
    def test_every_post_route_has_a_schema_and_reads_only_its_fields(self):
        """Why: POST_FIELDS is the documented contract; it must match what server.py actually reads."""
        import server
        src = pathlib.Path(ROOT, "server.py").read_text(encoding="utf-8")
        starts = {m.group(1): m.start() for m in re.finditer(r"^def (\w+)\(", src, re.M)}
        order = sorted(starts, key=starts.get)
        body = {n: src[starts[n]:starts[order[i + 1]] if i + 1 < len(order) else len(src)] for i, n in enumerate(order)}
        reads = lambda t: set(re.findall(r'\bb\.get\("(\w+)"', t) + re.findall(r'\bb\["(\w+)"\]', t) + re.findall(r'schema\.\w+\(b, "(\w+)"', t))
        for key, fn in server.Handler.routes.items():
            method, name = key.split(" ", 1)
            if method != "POST":
                continue
            self.assertIn(name, schema.POST_FIELDS, f"POST /api/{name} has no entry in core/schema.py POST_FIELDS")
            text = body[fn.__name__]
            for helper in re.findall(r"\b(_\w+)\(", text):
                if helper in body and re.search(r"\bb\b", body[helper].split("\n")[0]):
                    text += body[helper]
            extra = reads(text) - set(schema.POST_FIELDS[name])
            if name == "scan/start" or name == "scan/estimate":
                extra -= {"roots", "skip", "est_files", "mode"}
            self.assertFalse(extra, f"POST /api/{name} reads {sorted(extra)}, which are missing from POST_FIELDS")


class ResponseContractTest(TempHomeCase):
    """Why: every field the UI reads from a response must exist in what the server sends (no `undefined` on screen)."""

    def test_scan_status_has_what_the_scan_page_reads(self):
        self.make("Lib/a.txt")
        job = scanner.start("deep", [str(self.home / "Lib")], [])
        while job.state in ("running", "paused"):
            time.sleep(0.02)
        snap = scanner.status()
        src = read_js("views/scan.js")
        body = src[src.index("function scanDone"):src.index("ACT.scanmode")]
        need = fields_read(body, "s") | fields_read(src[src.index("function skippedText"):src.index("async function pollScan")], "s")
        need -= {"pending"}                       # S.pending is page state, not part of the response
        self.assertFalse(need - set(snap), f"scan status lacks {sorted(need - set(snap))}")
        failure_keys = fields_read(src[src.index("function scanFailHtml"):src.index("function skippedText")], "f")
        failed = jobs.Job("scan", step="x")
        failed.fail(scanner.ScanFailed("m", "index_busy", "h", "writing the index"))
        self.assertFalse(failure_keys - set(failed.failure) - {"paths"}, failure_keys)

    def test_drive_records_have_what_the_scan_page_reads(self):
        src = read_js("views/scan.js")
        need = fields_read(src[src.index("S.drives.map(d =>"):src.index("<h3>Folders</h3>")], "d")
        for d in platform_utils.list_drives():
            self.assertFalse(need - set(d), f"drive record {d.get('root')} lacks {sorted(need - set(d))}")
        self.assertFalse(need - set(platform_utils.DRIVE_BLANK))

    def test_info_has_what_the_error_report_reads(self):
        import server
        captured = {}

        class H:
            def send(self, code, body):
                captured.update(body)
        server.r_info(H(), {}, {})
        src = read_js("ui.js")
        need = fields_read(src[src.index("function errorReport"):src.index("function showErrorDetails")], "info")
        self.assertFalse(need - set(captured), f"/api/info lacks {sorted(need - set(captured))}")
        self.assertEqual(captured["log_file"], config.LOG_FILE_SHOWN)
        self.assertNotIn(str(config.HOME), captured["log_file"])


@unittest.skipUnless(NODE, "Node.js is needed to run the front-end helper")
class DriveLabelTest(unittest.TestCase):
    """Regression: driveName() assumed a drive letter; network shares and Linux mounts were all shown as '/'."""

    def test_any_mount_gets_a_label(self):
        js = r"""
const src = require('fs').readFileSync(process.argv[1], 'utf8');
const fn = new Function(src.match(/function driveName\(p\) \{[\s\S]*?\n\}/)[0] + '; return driveName;')();
process.stdout.write(JSON.stringify(JSON.parse(process.argv[2]).map(fn)));
"""
        cases = {"C:\\": "C:", "d:\\Photos": "D:", "/": "/", "/Volumes/My Disk": "My Disk", "\\\\server\\share\\sub": "\\\\server\\share",
                 "/media/usb": "usb", "/run/media/me/STICK": "STICK", "": "/", "/storage/emulated/0": "phone", "/storage/1A2B-3C4D": "SD card"}
        r = subprocess.run([NODE, "-e", js, os.path.join(JS, "util.js"), json.dumps(list(cases))], capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), list(cases.values()))


if __name__ == "__main__":
    unittest.main()
