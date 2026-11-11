"""No emoji or decorative symbols anywhere in the product (UI, Python strings, docs, scripts), and no sparkle icon."""
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Emoji / pictographs, Misc symbols + Dingbats (incl. sparkles U+2726-2728), Misc symbols and arrows, emoji variation selector.
RANGES = ((0x1F000, 0x1FAFF), (0x2600, 0x27BF), (0x2B00, 0x2BFF), (0xFE0F, 0xFE0F))   # built from numbers so this file stays plain ASCII
BANNED = re.compile("[" + "".join(f"{chr(a)}-{chr(b)}" for a, b in RANGES) + "]")
TEXT_EXT = (".py", ".js", ".mjs", ".css", ".html", ".svg", ".md", ".yml", ".yaml", ".ps1", ".sh", ".bat", ".cmd", ".command", ".txt", ".json", ".toml")
SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv"}


def repo_text_files():
    """Why: every shipped text file is checked, not just the UI."""
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            if f.endswith(TEXT_EXT) or f in ("LICENSE",):
                yield os.path.join(base, f)


class NoEmojiTest(unittest.TestCase):
    def test_no_emoji_or_symbol_codepoints(self):
        bad = []
        for path in repo_text_files():
            with open(path, encoding="utf-8", errors="replace") as fh:
                for n, line in enumerate(fh, 1):
                    m = BANNED.search(line)
                    if m:
                        bad.append(f"{os.path.relpath(path, ROOT)}:{n} U+{ord(m.group(0)):04X}")
        self.assertEqual(bad, [])

    def test_no_sparkle_icon(self):
        hits = []
        for path in repo_text_files():
            if path.endswith((".js", ".html", ".svg", ".css")):
                with open(path, encoding="utf-8") as fh:
                    if re.search(r"sparkle|magic|wand", fh.read(), re.I):
                        hits.append(os.path.relpath(path, ROOT))
        self.assertEqual(hits, [], "no sparkle, star or magic-wand icon anywhere")

    def test_no_hype_words_in_the_ui_or_readme(self):
        hype = re.compile(r"\b(unlock|supercharge|seamless(ly)?|revolutionary|magical|effortless(ly)?|blazing|game-changing)\b", re.I)
        hits = []
        for path in repo_text_files():
            rel = os.path.relpath(path, ROOT)
            if rel.startswith("docs") and path.endswith((".js", ".html")) or rel == "README.md":
                with open(path, encoding="utf-8") as fh:
                    text = fh.read()
                for m in hype.finditer(text):
                    near = (text[max(0, m.start() - 60):m.start()] + text[m.end():m.end() + 60]).lower()
                    if m.group(0).lower() == "unlock" and re.search(r"pin|locked|lock screen|pinunlock|unlockscreen|aurasort", near):
                        continue   # the PIN lock's own word ("Unlock AuraSort"), not marketing ("unlock your potential")
                    hits.append(f"{rel}: {m.group(0)}")
        self.assertEqual(hits, [])

    def test_every_used_icon_exists_in_the_sprite(self):
        with open(os.path.join(ROOT, "docs", "icons.svg"), encoding="utf-8") as fh:
            sprite = set(re.findall(r'<symbol id="([a-z]+)"', fh.read()))
        used = set()
        for path in repo_text_files():
            if path.endswith(".js"):
                with open(path, encoding="utf-8") as fh:
                    used |= set(re.findall(r"\bic\('([a-z]+)'", fh.read()))
        self.assertEqual(sorted(used - sprite), [])
        with open(os.path.join(ROOT, "docs", "icons.svg"), encoding="utf-8") as fh:
            svg = fh.read()
        self.assertNotIn("Gradient", svg)
        self.assertNotRegex(svg, r'fill="(?!none)')


if __name__ == "__main__":
    unittest.main()
