"""Legal documents and data deletion: every document exists with a version, an effective date, the note and the short
version, and all required sections; the app's Terms version matches; bundled assets are listed; issue templates warn
about private data; the documents are served offline; 'Delete my AuraSort data' removes only AuraSort's own data."""
import json
import os
import re
import time
import unittest

from tests import fixtures as fx
from tests.test_web_security import ServerCase
from core import config, docai, history, index_db, keystore, scanner

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NOTE = "Template provided for convenience, not legal advice. Have a qualified lawyer review before relying on it."
DOCS = {
    "TERMS_OF_USE.md": ["Acceptance and who may use", "What AuraSort is", "Licence", "Your responsibilities", "Safety features and their limits",
                        "Automated checks are aids", "AI features", "Third-party software and services", "No warranty", "Limitation of liability",
                        "Acceptable use", "Changes to these Terms", "Ending use", "Governing law and jurisdiction", "Contact"],
    "ACCEPTABLE_USE.md": ["Your files only", "Other people's information", "Protections and the network", "Harmful use", "Copyright and licences",
                          "AI features", "Asking for help", "Laws"],
    "PRIVACY_POLICY.md": ["What AuraSort stores on your computer", "What may leave your computer", "Browser storage", "How to delete your data",
                          "Children", "Security", "Roles", "Changes to this policy", "Contact"],
    "AI_DATA_NOTICE.md": ["Local mode", "Cloud mode", "Accuracy and limits"],
    "THIRD_PARTY_NOTICES.md": ["Bundled assets", "Optional packages"],
    "CODE_OF_CONDUCT.md": ["Our pledge", "Expected behaviour", "Unacceptable behaviour", "Enforcement", "Scope"],
}
ASSET_EXTS = (".svg", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".woff", ".woff2", ".ttf", ".otf", ".ico")


def read(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as fh:
        return fh.read()


class DocumentsTest(unittest.TestCase):
    def test_every_document_is_complete(self):
        for name, headings in DOCS.items():
            text = read(name)
            self.assertRegex(text, r"(?m)^Version: \d+\.\d+\.\d+$", name)
            self.assertRegex(text, r"(?m)^Effective date: \d{1,2} \w+ \d{4}$", name)
            self.assertIn(NOTE, text, name)
            self.assertIn("The short version", text, name)
            self.assertIn("Sunil Kumar (GitHub: skuser404)", text, name)
            found = re.findall(r"(?m)^##\s+(?:\d+\.\s+)?(.+)$", text)
            for h in headings:
                self.assertTrue(any(f.startswith(h) for f in found), f"{name}: missing section '{h}'")
        self.assertIn("[OWNER TO CONFIRM", read("TERMS_OF_USE.md"), "governing law is marked for the owner")
        self.assertIn("China", read("AI_DATA_NOTICE.md"))

    def test_app_terms_version_matches_the_document(self):
        doc = re.search(r"(?m)^Version: (\S+)$", read("TERMS_OF_USE.md")).group(1)
        app = re.search(r"TERMS_VERSION = '([^']+)'", read(os.path.join("docs", "js", "legal.js"))).group(1)
        self.assertEqual(doc, app, "bump TERMS_VERSION in docs/js/legal.js together with the Terms")

    def test_license_and_readme(self):
        self.assertIn("Copyright (c) 2026 Sunil Kumar (GitHub: skuser404)", read("LICENSE"))
        readme = read("README.md")
        for name in list(DOCS) + ["LICENSE"]:
            self.assertIn(name, readme, f"README links {name}")

    def test_every_bundled_asset_has_a_notice(self):
        notices = read("THIRD_PARTY_NOTICES.md")
        for base, _, files in os.walk(os.path.join(ROOT, "docs")):
            for f in files:
                if f.lower().endswith(ASSET_EXTS):
                    self.assertIn(f, notices, f"{f} is bundled but not listed in THIRD_PARTY_NOTICES.md")

    def test_issue_templates_warn_about_private_data(self):
        for t in ("bug_report.yml", "feature_request.yml"):
            self.assertIn("full paths with your user name, API keys or screenshots of private documents", read(os.path.join(".github", "ISSUE_TEMPLATE", t)))


class ServedOfflineTest(ServerCase):
    def test_legal_documents_are_served_from_the_repo_and_nothing_else(self):
        for name in list(DOCS) + ["LICENSE"]:
            st, _, body = self.req(f"/legal/{name}", headers={config.TOKEN_HEADER: None})
            self.assertEqual(st, 200, name)
            self.assertEqual(body.decode("utf-8"), read(name), "the app shows exactly the repo's file")
        for bad in ("/legal/server.py", "/legal/../server.py", "/legal/README.md", "/legal/%2e%2e/LICENSE"):
            self.assertEqual(self.req(bad, headers={config.TOKEN_HEADER: None})[0], 404, bad)


class DeleteDataTest(ServerCase):
    def test_delete_my_data_removes_only_aurasort_data(self):
        p = self.make("Lib/keep.png", fx.png())
        job = scanner.start("deep", [str(self.home / "Lib")], [])
        while job.state in ("running", "paused"):
            time.sleep(0.02)
        history.record("scan", count=1)
        (config.THUMB_DIR / "x.jpg").write_bytes(b"t")
        self.req("/api/settings", {"dest": str(self.home / "Out")})
        keystore.set_session("sk-delete-me-123")
        docai._STORE["results"][1] = dict(level="normal")
        self.assertEqual(self.req("/api/data/delete", {})[0], 400, "needs an explicit confirmation")
        st, _, raw = self.req("/api/data/delete", {"confirm": "DELETE"})
        self.assertEqual(st, 200)
        self.assertIn("History and Undo logs", json.loads(raw)["removed"])
        self.assertTrue(os.path.exists(p), "your own files are never touched")
        self.assertEqual(list(config.HISTORY_DIR.glob("*.json")), [])
        self.assertEqual(list(config.THUMB_DIR.iterdir()), [])
        self.assertFalse(config.SETTINGS_FILE.exists())
        self.assertEqual(keystore.get_session(), "")
        self.assertEqual(docai.results(), {})
        self.assertEqual(index_db.files_page({"scope": "all"})["total"], 0, "the index is empty again")
        self.assertEqual(self.req("/api/info")[0], 200, "the app keeps working afterwards")


if __name__ == "__main__":
    unittest.main()
