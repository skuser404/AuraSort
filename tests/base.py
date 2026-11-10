"""Shared test base: every test gets a private temporary HOME and data folder (the real ones are never touched)."""
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import config  # noqa: E402


class TempHomeCase(unittest.TestCase):
    """Why: tests create files, histories and indexes; isolate them from the user's real data."""

    _PATCHED = ("HOME", "DATA_DIR", "HISTORY_DIR", "INDEX_DB", "THUMB_DIR", "SETTINGS_FILE", "LOG_DIR", "LOG_FILE", "LEGACY_DATA_DIRS")

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="aurasort-test-"))
        self.home = self.tmp / "home"
        self.home.mkdir()
        self._saved = {k: getattr(config, k) for k in self._PATCHED}
        config.HOME = self.home
        config.DATA_DIR = self.home / f".{config.APP_SLUG}"
        config.HISTORY_DIR = config.DATA_DIR / "history"
        config.INDEX_DB = config.DATA_DIR / "index.sqlite3"
        config.THUMB_DIR = config.DATA_DIR / "thumbs"
        config.SETTINGS_FILE = config.DATA_DIR / "settings.json"
        config.LOG_DIR = config.DATA_DIR / "logs"
        config.LOG_FILE = config.LOG_DIR / "test.log"
        config.LEGACY_DATA_DIRS = (self.home / ".old-app",)
        config.HISTORY_DIR.mkdir(parents=True)
        config.THUMB_DIR.mkdir(parents=True)
        # The system temp folder sits inside protected AppData on Windows; let tests use their own temp tree.
        from core import safety
        from core.platform_utils import within
        self._saved_prefixes = safety._PREFIXES
        tmp_real = os.path.normcase(safety.canonical(self.tmp))
        safety._PREFIXES = [p for p in safety._prefixes() if not within(tmp_real, p)]
        safety._DATA_CANON.clear()
        from core import index_db
        index_db.close_all()
        index_db.init()

    def tearDown(self):
        from core import index_db, safety
        index_db.close_all()
        safety._PREFIXES = self._saved_prefixes
        safety._DATA_CANON.clear()
        for k, v in self._saved.items():
            setattr(config, k, v)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def make(self, rel, data=b"x"):
        """Create a file under the temp home and return its path as a string."""
        p = self.home / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return str(p)
