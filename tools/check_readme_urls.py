#!/usr/bin/env python3
"""CI only: every https:// link in the README (and the install docs) must answer 200. A 404 like the old
.../v1.0.0/scripts/install.ps1 link then fails the build instead of a user's install.

    python tools/check_readme_urls.py [README.md ...]

The app itself never makes network requests; this tool is not part of it."""
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
URL_RX = re.compile(r"https://[^\s)<>\"'`\]]+")
SKIP = ("localhost", "127.0.0.1", "example.com")
UA = "AuraSort-readme-link-check (+https://github.com/skuser404/AuraSort)"


def status(url):
    """HEAD first (cheap); some servers refuse HEAD, so GET on 403/405."""
    for method in ("HEAD", "GET"):
        req = urllib.request.Request(url, method=method, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:  # nosec B310  # https only (URL_RX), CI tool
                return r.status
        except urllib.error.HTTPError as e:
            if method == "HEAD" and e.code in (403, 405, 429):
                continue
            return e.code
        except (urllib.error.URLError, TimeoutError) as e:
            return f"error {e}"
    return "error"


def main(files):
    urls = {}
    for f in files:
        for n, line in enumerate(Path(f).read_text(encoding="utf-8").splitlines(), 1):
            for u in URL_RX.findall(line):
                u = u.rstrip(".,;:")
                if not any(s in u for s in SKIP):
                    urls.setdefault(u, f"{Path(f).name}:{n}")
    bad = []
    for u, where in sorted(urls.items()):
        code = status(u)
        print(f"{code}  {u}  ({where})")
        if code != 200:
            bad.append(f"{where}: {u} -> {code}")
        time.sleep(0.2)
    if bad:
        print("\nBroken links:\n  " + "\n  ".join(bad))
        return 1
    print(f"\nAll {len(urls)} links answer 200.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or [str(ROOT / "README.md")]))
