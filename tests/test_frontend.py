"""Static checks on the front end (plain scripts, no build step): names must not collide, scripts must all be loaded."""
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JS = os.path.join(ROOT, "docs", "js")
TOP_LEVEL = re.compile(r"^(?:async\s+)?function\s+([A-Za-z0-9_$]+)|^(?:const|let|var)\s+([A-Za-z0-9_$]+)", re.M)
WORKER_ONLY = {"search-worker.js"}


def page_scripts():
    """Why: every classic script shares one global scope, so they are checked together."""
    out = []
    for base, _, files in os.walk(JS):
        out += [os.path.join(base, f) for f in files if f.endswith(".js") and f not in WORKER_ONLY]
    return out


class FrontendTest(unittest.TestCase):
    def test_no_duplicate_global_names(self):
        seen, dupes = {}, []
        for path in page_scripts():
            with open(path, encoding="utf-8") as fh:
                for m in TOP_LEVEL.finditer(fh.read()):
                    name = m.group(1) or m.group(2)
                    if name in seen:
                        dupes.append(f"{name}: {seen[name]} and {os.path.basename(path)}")
                    seen[name] = os.path.basename(path)
        self.assertEqual(dupes, [], "a later script would silently replace an earlier function")

    def test_every_script_is_loaded_by_the_page(self):
        with open(os.path.join(ROOT, "docs", "index.html"), encoding="utf-8") as fh:
            html = fh.read()
        loaded = set(re.findall(r'<script src="([^"]+)"', html))
        missing = [os.path.relpath(p, os.path.join(ROOT, "docs")).replace(os.sep, "/") for p in page_scripts()]
        self.assertEqual([m for m in missing if m not in loaded], [])

    def test_no_inline_handlers_or_styles_in_markup(self):
        bad = re.compile(r"""\son[a-z]+\s*=\s*["']|\sstyle\s*=\s*["']""", re.I)
        for path in page_scripts() + [os.path.join(ROOT, "docs", "index.html")]:
            with open(path, encoding="utf-8") as fh:
                for n, line in enumerate(fh, 1):
                    self.assertIsNone(bad.search(line), f"{os.path.basename(path)}:{n} uses an inline handler/style (blocked by the CSP)")


if __name__ == "__main__":
    unittest.main()
