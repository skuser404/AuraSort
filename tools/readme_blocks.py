#!/usr/bin/env python3
"""CI only: run the README's copy-paste install commands, so they are verified on real Windows, macOS and Linux runners.

Only code blocks right after a `<!-- ci: run sh -->` or `<!-- ci: run pwsh -->` line are run. Two changes keep CI
honest and finite: the clone URL points at the checkout being tested (not whatever is on GitHub today), and a final
`server.py` line gets `--doctor` (the real server would wait forever for a browser).

    python tools/readme_blocks.py sh|pwsh [README.md]"""
import os
import re
import subprocess  # nosec B404  # runs the README's own commands in CI, nothing else
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLONE_URL = "https://github.com/skuser404/AuraSort.git"
MARK = re.compile(r"<!-- ci: run (sh|pwsh) -->\s*\n```[a-z]*\n(.*?)\n```", re.S)


def blocks(text, shell):
    return [b for s, b in MARK.findall(text) if s == shell]


def prepare(block):
    lines = []
    for ln in block.splitlines():
        ln = ln.replace(CLONE_URL, str(ROOT))
        if re.search(r"server\.py\s*$", ln):
            ln = ln.rstrip() + " --doctor"
        lines.append(ln)
    return "\n".join(lines)


def main(shell, readme):
    found = blocks(Path(readme).read_text(encoding="utf-8"), shell)
    if not found:
        print(f"no '<!-- ci: run {shell} -->' blocks in {readme}")
        return 1
    home = tempfile.mkdtemp(prefix="aurasort-readme-")
    env = dict(os.environ, HOME=home, USERPROFILE=home)
    for i, b in enumerate(found, 1):
        script = prepare(b)
        print(f"---- block {i} ({shell}) ----\n{script}\n----", flush=True)
        cmd = ["bash", "-euxo", "pipefail", "-c", script] if shell == "sh" else ["pwsh", "-NoProfile", "-Command", "$ErrorActionPreference='Stop'; " + script]
        r = subprocess.run(cmd, cwd=home, env=env, check=False)  # nosec B603
        if r.returncode:
            print(f"block {i} failed with exit code {r.returncode}")
            return r.returncode
    print(f"all {len(found)} {shell} blocks ran")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else str(ROOT / "README.md")))
