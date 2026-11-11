#!/usr/bin/env python3
"""CI only: run the unit tests and turn every failure into a GitHub annotation (test name + the end of its traceback),
so a red build says *which* test failed and why on the run's summary page, readable without downloading logs.

    python tools/ci_unittest.py        (same tests as: python -m unittest discover -s tests -t .)"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def esc(text):
    """GitHub workflow-command escaping (newlines become %0A)."""
    return str(text).replace("%", "%25").replace("\r", "").replace("\n", "%0A")


def main():
    sys.path.insert(0, str(ROOT))
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), top_level_dir=str(ROOT))
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    for kind, items in (("FAIL", result.failures), ("ERROR", result.errors)):
        for test, tb in items[:30]:
            tail = "\n".join(tb.strip().splitlines()[-8:])
            print(f"::error title={esc(kind + ': ' + test.id())}::{esc(tail)}", flush=True)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
