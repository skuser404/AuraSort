"""Text extraction for Document Insights (standard library; pypdf is optional for PDFs).
Office files are ZIP + XML: text is pulled out with size-capped regexes (no XML parser, so no entity-expansion attacks).
Every limit (bytes, pages, characters) comes from config; failures return a reason, never an exception."""
import html
import re
import zipfile
import zlib

from . import config

try:
    from pypdf import PdfReader  # optional, pure Python (see requirements.txt)
except ImportError:  # pragma: no cover
    PdfReader = None

DOC_EXTS = ("pdf", "docx", "pptx", "xlsx", "txt", "md", "csv")
_WT = re.compile(r"<w:t(?:\s[^>]*)?>([^<]*)</w:t>")
_AT = re.compile(r"<a:t>([^<]*)</a:t>")
_XT = re.compile(r"<t(?:\s[^>]*)?>([^<]*)</t>")
_PARA = re.compile(r"</w:p>|</a:p>|<w:br\s*/>|<w:tab\s*/>")


class Extracted:
    """Why: callers need the text plus honest facts about it (pages read, truncated, scanned, why it failed)."""

    def __init__(self, text="", pages=0, truncated=False, status="ok", note=""):
        self.text, self.pages, self.truncated, self.status, self.note = text, pages, truncated, status, note


def _cap(text, pages=0):
    text = re.sub(r"[ \t]+", " ", text).strip()
    cut = len(text) > config.AI_MAX_CHARS
    return Extracted(text[:config.AI_MAX_CHARS], pages, cut)


def _zip_part(z, name):
    """Why: refuse oversized parts (zip bombs) before reading them."""
    info = z.getinfo(name)
    if info.file_size > config.AI_MAX_PART_BYTES:
        raise ValueError("part too large")
    return z.read(name).decode("utf-8", errors="replace")


def _office(path, ext, max_pages):
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        if ext == "docx":
            parts, rx = [n for n in names if n == "word/document.xml" or re.match(r"word/(header|footer)\d*\.xml$", n)], _WT
        elif ext == "pptx":
            parts = sorted((n for n in names if re.match(r"ppt/slides/slide\d+\.xml$", n)), key=lambda n: int(re.findall(r"\d+", n)[-1]))
            parts, rx = parts[:max_pages], _AT
        else:
            parts, rx = [n for n in names if n == "xl/sharedStrings.xml"], _XT
        chunks, joiner = [], "" if ext == "docx" else " "
        for p in parts:
            xml = _PARA.sub(lambda m: "<w:t>\n</w:t>" if ext == "docx" else "<a:t>\n</a:t>", _zip_part(z, p))
            chunks.append(joiner.join(html.unescape(t) for t in rx.findall(xml)))
            if sum(len(c) for c in chunks) > config.AI_MAX_CHARS:
                break
        return _cap("\n".join(chunks), len(parts))


def _plain(path):
    with open(path, "rb") as fh:
        raw = fh.read(config.AI_MAX_CHARS * 4)
    return _cap(raw.decode("utf-8", errors="replace"))


# ---------------- PDF ----------------
_STREAM = re.compile(rb"<<(.*?)>>\s*stream\r?\n(.*?)\r?\nendstream", re.S)
_TJ = re.compile(rb"\((?:\\.|[^\\)])*\)\s*Tj|\[(?:[^\]]*)\]\s*TJ")
_STR = re.compile(rb"\((?:\\.|[^\\)])*\)")
_ESC = {b"n": "\n", b"r": "", b"t": " ", b"(": "(", b")": ")", b"\\": "\\"}


def _pdf_string(raw):
    """Why: PDF literal strings use backslash escapes; only plain text survives."""
    out, i, s = [], 0, raw[1:-1]
    while i < len(s):
        c = s[i:i + 1]
        if c == b"\\" and i + 1 < len(s):
            nxt = s[i + 1:i + 2]
            if nxt in _ESC:
                out.append(_ESC[nxt])
            elif nxt.isdigit():
                oct_ = re.match(rb"[0-7]{1,3}", s[i + 1:i + 4]).group(0)
                out.append(chr(int(oct_, 8)))
                i += len(oct_) - 1
            i += 2
            continue
        out.append(c.decode("latin-1"))
        i += 1
    return "".join(out)


def _pdf_builtin(path):
    """Why: without pypdf, simple PDFs (plain or Flate-compressed text streams) can still be read."""
    with open(path, "rb") as fh:
        data = fh.read(config.AI_MAX_FILE_BYTES)
    if not data.lstrip()[:5] == b"%PDF-":
        raise ValueError("not a PDF")
    pages = len(re.findall(rb"/Type\s*/Page(?!s)", data))
    texts = []
    for head, body in _STREAM.findall(data):
        if b"/Image" in head or b"/XObject" in head:
            continue
        if b"FlateDecode" in head:
            try:
                body = zlib.decompressobj().decompress(body, config.AI_MAX_PART_BYTES)
            except zlib.error:
                continue
        for op in _TJ.findall(body):
            texts.append("".join(_pdf_string(s) for s in _STR.findall(op)) + " ")   # separate text runs stay separate words
        texts.append("\n")
        if sum(len(t) for t in texts) > config.AI_MAX_CHARS:
            break
    return pages, "".join(texts)


def _pdf(path, max_pages):
    if PdfReader:
        reader = PdfReader(path)
        n, out = len(reader.pages), []
        for page in reader.pages[:max_pages]:
            out.append(page.extract_text() or "")
            if sum(len(t) for t in out) > config.AI_MAX_CHARS:
                break
        pages, text = n, "\n".join(out)
    else:
        pages, text = _pdf_builtin(path)
    ex = _cap(text, pages)
    if not ex.text.strip():
        ex.status, ex.note = "scanned", "No text layer: this looks like a scanned PDF (needs OCR)."
    elif not PdfReader:
        ex.note = "Read with the basic built-in PDF reader. Install pypdf for better results."
    return ex


def extract(path, ext, size, pages=None):
    """Why: one entry point; every failure becomes a status + friendly note, so one bad file never stops a batch."""
    if size > config.AI_MAX_FILE_BYTES:
        return Extracted(status="skipped", note=f"Skipped: larger than {config.AI_MAX_FILE_BYTES // (1024 * 1024)} MB.")
    try:
        if ext in ("docx", "pptx", "xlsx"):
            ex = _office(path, ext, pages or config.AI_MAX_PAGES)
        elif ext == "pdf":
            ex = _pdf(path, pages or config.AI_MAX_PAGES)
        elif ext in ("txt", "md", "csv"):
            ex = _plain(path)
        else:
            return Extracted(status="skipped", note="This type is not read yet.")
    except (OSError, ValueError, zipfile.BadZipFile, KeyError, RuntimeError, zlib.error) as e:  # noqa: BLE001 - reported per file
        return Extracted(status="error", note=f"Could not read this file ({type(e).__name__}).")
    except Exception as e:  # noqa: BLE001 - pypdf raises many types on damaged files
        return Extracted(status="error", note=f"Could not read this file ({type(e).__name__}).")
    if ex.status == "ok" and not ex.text.strip():
        ex.status, ex.note = "empty", "No readable text."
    return ex
