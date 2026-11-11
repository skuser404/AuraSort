"""The Windows installer must survive "irm <url> | iex" on Windows PowerShell 5.1."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class InstallerTextTest(unittest.TestCase):
    def test_ps1_files_are_plain_ascii_without_bom(self):
        # Why: served without a charset (release assets are application/octet-stream), PowerShell 5.1 decodes the text as
        # ISO-8859-1; a UTF-8 BOM then becomes three junk characters before "<#" and the whole script fails to parse.
        for f in (ROOT / "scripts").glob("*.ps1"):
            raw = f.read_bytes()
            self.assertFalse(raw.startswith(b"\xef\xbb\xbf"), f.name)
            raw.decode("ascii")

    def test_iex_runs_the_installer_as_a_real_script(self):
        # Why: under iex $PSCmdlet is null (ShouldProcess fails) and "exit" closes the window.
        t = (ROOT / "scripts" / "install.ps1").read_text(encoding="ascii")
        self.assertLess(t.index("if ($null -eq $PSCmdlet)"), t.index("$PSCmdlet.ShouldProcess"))
        self.assertIn("-ExecutionPolicy Bypass -File $self", t)

    def test_no_release_falls_back_to_the_source_zip(self):
        for name in ("install.ps1", "install.sh"):
            self.assertIn("/archive/", (ROOT / "scripts" / name).read_text(encoding="ascii"), name)


if __name__ == "__main__":
    unittest.main()
