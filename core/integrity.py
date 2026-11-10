"""Deterministic integrity checks. Strictly read-only: files are opened 'rb', never modified, repaired or deleted.

Quick mode reads headers/trailers (cheap seeks). Deep mode parses structures, verifies CRCs and reads every byte
so disk read errors surface too. Each finding = severity, reason code, plain-English detail with location,
most likely cause, suggested fix and confidence."""
import gzip
import os
import re
import struct
import tarfile
import zipfile
import zlib

from . import config

CORRUPTED, DAMAGED, WARNING = "corrupted", "damaged", "warning"
SEVERITY_RANK = {CORRUPTED: 3, DAMAGED: 2, WARNING: 1}
HIGH, MEDIUM, LOW = "high", "medium", "low"

if config.WIN:
    _DISK_TOOL = "run 'chkdsk X: /scan' in an Administrator terminal (X = the drive letter)"
elif config.MAC:
    _DISK_TOOL = "open Disk Utility and run First Aid on the drive"
else:
    _DISK_TOOL = "run a file-system check (fsck) on the drive while it is unmounted"

REDOWNLOAD = "Download or copy it again from the original source, or restore it from a backup."
BACKUP = "Restore it from a backup or get a fresh copy from where it came from."
DISK = f"If several files on this drive show problems, back the drive up now and check it: {_DISK_TOOL}."
VIDEO = "Try VLC; to rescue the video, remux it with ffmpeg (ffmpeg -i in.mp4 -c copy out.mp4) or use a video repair tool. Keep the original."
CUT_OFF = "The download or copy stopped early, or the drive failed while writing."
BITROT = "Bits changed on disk or during a transfer (failing drive, bad cable, interrupted sync)."
UNKNOWN = "unknown"

# code -> (severity, detail template, most likely cause, suggested fix, confidence)
REASONS = {
    "EMPTY": (CORRUPTED, "The file is empty (0 bytes).", "The app that created it crashed, or the copy never wrote any data.", REDOWNLOAD, HIGH),
    "NULL_FILLED": (CORRUPTED, "The file contains only zero bytes{where} - there is no real content.", "An interrupted copy, a crash while saving, or a failing drive.", REDOWNLOAD + " " + DISK, HIGH),
    "PARTIAL_DOWNLOAD": (DAMAGED, "This is an unfinished download (.{ext}).", "The browser or download manager stopped before the download completed.", "Resume or restart the download in the app that started it.", HIGH),
    "TEMP_FILE": (WARNING, "This is a temporary file (.{ext}).", "Apps create temporary files while working and sometimes leave them behind.", "If the app that made it is closed, it is usually safe to remove.", MEDIUM),
    "READ_ERROR": (CORRUPTED, "Unreadable - disk read error at byte {pos:,}.", "Bad sectors on the drive, a loose cable/port, or a cloud file that is not downloaded.", DISK, HIGH),
    "EXT_MISMATCH": (WARNING, "This is really a {real}, but its name ends in .{ext}.", "It was renamed, or an app saved it with the wrong extension.", "Rename it to .{good} so the right app opens it.", HIGH),
    "JPEG_NO_SOI": (CORRUPTED, "The JPEG start-of-image marker is missing at byte 0, so this is not a readable JPEG.", BITROT, BACKUP, HIGH),
    "JPEG_NO_EOI": (DAMAGED, "The JPEG end-of-image marker is missing at byte {pos:,} - the picture was cut off, so its lower part is probably grey or missing.", CUT_OFF, REDOWNLOAD, HIGH),
    "JPEG_BAD_MARKER": (DAMAGED, "Unexpected data instead of a JPEG marker at byte {pos:,}.", BITROT, BACKUP + " " + DISK, HIGH),
    "JPEG_TRUNCATED": (DAMAGED, "A JPEG section starting at byte {pos:,} runs past the end of the file ({size:,} bytes).", CUT_OFF, REDOWNLOAD, HIGH),
    "PNG_BAD_SIG": (CORRUPTED, "The PNG signature is missing at byte 0, so this is not a readable PNG.", BITROT, BACKUP, HIGH),
    "PNG_NO_IHDR": (CORRUPTED, "The PNG header chunk (IHDR) is missing at byte 8.", BITROT, BACKUP, HIGH),
    "PNG_TRUNCATED": (DAMAGED, "The image data stops at byte {pos:,}; the PNG end marker (IEND) is missing.", CUT_OFF, REDOWNLOAD, HIGH),
    "PNG_BAD_CRC": (DAMAGED, "Chunk '{chunk}' at byte {pos:,} fails its checksum (CRC).", BITROT, BACKUP + " " + DISK, HIGH),
    "GIF_BAD_SIG": (CORRUPTED, "The GIF signature is missing at byte 0.", BITROT, BACKUP, HIGH),
    "GIF_NO_TRAILER": (DAMAGED, "The GIF end marker is missing at byte {pos:,} - the image or animation is incomplete.", CUT_OFF, REDOWNLOAD, HIGH),
    "RIFF_BAD_SIG": (CORRUPTED, "The RIFF signature is missing at byte 0.", BITROT, BACKUP, HIGH),
    "RIFF_TRUNCATED": (DAMAGED, "The header says the file should be {expected:,} bytes, but it is only {size:,} bytes.", CUT_OFF, REDOWNLOAD, HIGH),
    "BMP_BAD_SIG": (CORRUPTED, "The BMP signature is missing at byte 0.", BITROT, BACKUP, HIGH),
    "BMP_TRUNCATED": (DAMAGED, "The header says the image needs {expected:,} bytes, but the file is only {size:,} bytes.", CUT_OFF, REDOWNLOAD, HIGH),
    "PDF_NO_HEADER": (CORRUPTED, "The '%PDF-' header is missing at the start of the file.", BITROT, BACKUP, HIGH),
    "PDF_NO_EOF": (DAMAGED, "The PDF end-of-file marker (%%EOF) is missing at byte {pos:,} - the document was cut off; early pages may still open.", CUT_OFF, REDOWNLOAD, HIGH),
    "PDF_NO_STARTXREF": (DAMAGED, "The pointer to the cross-reference table (startxref) is missing near the end of the file.", CUT_OFF, REDOWNLOAD, HIGH),
    "PDF_BAD_XREF": (DAMAGED, "The cross-reference table should start at byte {off:,}, but no valid table is there.", BITROT, BACKUP + " Some PDF viewers can rebuild the table when opening.", HIGH),
    "PDF_BAD_OBJ": (DAMAGED, "Object {num} should start at byte {off:,}, but something else is there.", BITROT, BACKUP, MEDIUM),
    "ZIP_BAD_SIG": (CORRUPTED, "The ZIP signature is missing at byte 0.", BITROT, BACKUP, HIGH),
    "ZIP_NO_CDIR": (CORRUPTED, "The ZIP central directory (the table of contents at the end) is missing or unreadable.", CUT_OFF, REDOWNLOAD, HIGH),
    "ZIP_MISSING_PART": (CORRUPTED, "The required part '{part}' is missing inside this {kind} file.", "The file was assembled incorrectly or damaged.", BACKUP, HIGH),
    "ZIP_BAD_CRC": (DAMAGED, "'{member}' inside the archive fails its CRC check.", BITROT, BACKUP + " " + DISK, HIGH),
    "ZIP_BAD_DATA": (DAMAGED, "Compressed data inside the archive is unreadable ({err}).", BITROT, BACKUP, HIGH),
    "ZIP_ENCRYPTED": (WARNING, "The archive is password-protected, so its contents could not be verified.", UNKNOWN, "Nothing to do unless it fails to open with the password.", LOW),
    "ZIP_UNSUPPORTED": (WARNING, "The archive uses a compression method that could not be verified ({err}).", UNKNOWN, "Open it with 7-Zip or your archive app to test it.", LOW),
    "OLE_BAD_SIG": (CORRUPTED, "The Office/MSI header signature is missing at byte 0.", BITROT, BACKUP, HIGH),
    "OLE_BAD_HEADER": (CORRUPTED, "The Office/MSI header has an impossible sector size.", BITROT, BACKUP, HIGH),
    "OLE_TRUNCATED": (DAMAGED, "The file references data at byte {pos:,}, beyond its end ({size:,} bytes).", CUT_OFF, REDOWNLOAD, HIGH),
    "MP4_BAD_ATOM": (CORRUPTED, "The video structure is unreadable at byte {pos:,} (box '{atom}' has an impossible size).", BITROT, VIDEO, HIGH),
    "MP4_TRUNCATED": (DAMAGED, "Box '{atom}' at byte {pos:,} needs data up to byte {need:,}, but the file ends at {size:,} - it was cut off.", CUT_OFF, VIDEO, HIGH),
    "MP4_NO_MOOV": (CORRUPTED, "The 'moov' box (the index that players need) is missing, so normal players cannot open it.",
                    "Recording stopped unexpectedly (battery, crash, card removed) or the copy was incomplete.",
                    "A video repair tool (for example 'untrunc' with a healthy clip from the same camera) can often rebuild it. Keep the original.", HIGH),
    "MP4_NO_FTYP": (WARNING, "The 'ftyp' box is missing at byte 0; some players may refuse the file.", UNKNOWN, VIDEO, MEDIUM),
    "MKV_BAD_SIG": (CORRUPTED, "The Matroska/WebM signature is missing at byte 0.", BITROT, BACKUP, HIGH),
    "MKV_TRUNCATED": (DAMAGED, "The video segment needs data up to byte {need:,}, but the file ends at {size:,} - it was cut off.", CUT_OFF, VIDEO, HIGH),
    "MP3_NO_FRAME": (DAMAGED, "No MPEG audio frame was found after byte {pos:,}.", BITROT, REDOWNLOAD, MEDIUM),
    "MP3_TRUNCATED": (DAMAGED, "The ID3 tag claims {need:,} bytes, but the file is only {size:,} bytes.", CUT_OFF, REDOWNLOAD, HIGH),
    "FLAC_BAD_SIG": (CORRUPTED, "The FLAC signature ('fLaC') is missing.", BITROT, BACKUP, HIGH),
    "FLAC_TRUNCATED": (DAMAGED, "FLAC metadata needs data up to byte {need:,}, but the file ends at {size:,}.", CUT_OFF, REDOWNLOAD, HIGH),
    "OGG_BAD_SIG": (CORRUPTED, "The Ogg signature ('OggS') is missing at byte 0.", BITROT, BACKUP, HIGH),
    "OGG_TRUNCATED": (DAMAGED, "The Ogg page at byte {pos:,} runs past the end of the file ({size:,} bytes).", CUT_OFF, REDOWNLOAD, HIGH),
    "OGG_BAD_CRC": (DAMAGED, "The Ogg page at byte {pos:,} fails its checksum (CRC).", BITROT, BACKUP, HIGH),
    "PE_BAD_SIG": (CORRUPTED, "The Windows program header ({what}) is missing.", BITROT, "Download the installer or program again from the official site.", HIGH),
    "PE_TRUNCATED": (DAMAGED, "Section '{sect}' needs data up to byte {need:,}, but the file ends at {size:,} - the program is incomplete.", CUT_OFF, "Download it again from the official site.", HIGH),
    "SEVENZ_BAD_SIG": (CORRUPTED, "The 7-Zip signature is missing at byte 0.", BITROT, BACKUP, HIGH),
    "SEVENZ_BAD_HEADER": (CORRUPTED, "The 7-Zip start header fails its checksum (CRC).", BITROT, BACKUP, HIGH),
    "SEVENZ_TRUNCATED": (DAMAGED, "The 7-Zip index should end at byte {need:,}, but the file ends at {size:,}.", CUT_OFF, REDOWNLOAD, HIGH),
    "SEVENZ_BAD_CRC": (DAMAGED, "The 7-Zip index at byte {pos:,} fails its checksum (CRC).", BITROT, BACKUP, HIGH),
    "RAR_BAD_SIG": (CORRUPTED, "The RAR signature is missing at byte 0.", BITROT, BACKUP, HIGH),
    "RAR_NO_END": (DAMAGED, "The RAR end-of-archive marker is missing at byte {pos:,} - the archive may be incomplete.", CUT_OFF, REDOWNLOAD, MEDIUM),
    "GZ_BAD_SIG": (CORRUPTED, "The gzip signature is missing at byte 0.", BITROT, BACKUP, HIGH),
    "GZ_TRUNCATED": (DAMAGED, "The compressed stream ends before its end marker (file is {size:,} bytes).", CUT_OFF, REDOWNLOAD, HIGH),
    "GZ_BAD_CRC": (DAMAGED, "The decompressed data fails the gzip checksum ({err}).", BITROT, BACKUP, HIGH),
    "TAR_BAD_HEADER": (CORRUPTED, "The first TAR header fails its checksum.", BITROT, BACKUP, HIGH),
    "TAR_TRUNCATED": (DAMAGED, "Member '{member}' needs data up to byte {need:,}, but the archive ends at {size:,}.", CUT_OFF, REDOWNLOAD, HIGH),
    "ISO_BAD_SIG": (CORRUPTED, "No ISO 9660/UDF volume descriptor at byte 32,769.", BITROT, REDOWNLOAD, MEDIUM),
    "ISO_TRUNCATED": (DAMAGED, "The disc image should be {need:,} bytes, but it is only {size:,} bytes.", CUT_OFF, REDOWNLOAD, HIGH),
}

# ---------------- formats ----------------
FAMILY_EXTS = {
    "jpeg": "jpg jpeg jfif", "png": "png", "gif": "gif", "riff": "webp wav avi", "bmp": "bmp", "pdf": "pdf",
    "zip": "zip docx xlsx pptx docm xlsm pptm dotx odt ods odp epub apk jar ipa xapk aar",
    "ole": "doc xls ppt msi msg vsd pub", "mp4": "mp4 m4v mov m4a 3gp 3g2", "mkv": "mkv webm", "mp3": "mp3",
    "flac": "flac", "ogg": "ogg opus oga", "pe": "exe dll sys scr ocx cpl", "sevenz": "7z", "rar": "rar",
    "gz": "gz tgz", "tar": "tar", "iso": "iso",
}
EXT_FAMILY = {e: fam for fam, exts in FAMILY_EXTS.items() for e in exts.split()}
FAMILY_LABEL = {
    "jpeg": ("JPEG image", "jpg"), "png": ("PNG image", "png"), "gif": ("GIF image", "gif"), "pdf": ("PDF document", "pdf"),
    "zip": ("ZIP archive (or Office document)", "zip"), "ole": ("legacy Office/MSI file", "doc"), "riff": ("RIFF media file", "wav"),
    "mp4": ("MP4/QuickTime video", "mp4"), "mkv": ("Matroska/WebM video", "mkv"), "ogg": ("Ogg audio", "ogg"),
    "flac": ("FLAC audio", "flac"), "mp3": ("MP3 audio", "mp3"), "sevenz": ("7-Zip archive", "7z"), "rar": ("RAR archive", "rar"),
    "gz": ("gzip archive", "gz"), "pe": ("Windows program (EXE/DLL)", "exe"), "tar": ("TAR archive", "tar"),
}
RIFF_FORMS = {b"WEBP": ("webp", "WebP image"), b"WAVE": ("wav", "WAV audio"), b"AVI ": ("avi", "AVI video")}
OOXML = frozenset("docx xlsx pptx docm xlsm pptm dotx".split())
ODF = frozenset("odt ods odp".split())
PNG_SIG = b"\x89PNG\r\n\x1a\n"
OLE_SIG = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
SEVENZ_SIG = b"7z\xbc\xaf\x27\x1c"
RAR4_END, RAR5_END = b"\xc4\x3d\x7b\x00\x40\x07\x00", b"\x1d\x77\x56\x51\x03\x05\x04\x00"
MAX_ATOMS = 100000
MAX_PE_SECTIONS = 96
MAX_PDF_OBJ_CHECKS = 200
MAX_OGG_CRC_PAGES = 400
MAX_7Z_HEADER_BYTES = 64 * 1024 * 1024
ISO_PVD_OFFSET = 0x8001
ISO_SECTOR = 2048


def finding(code, **kw):
    """Why: every result has the same shape (severity, code, detail, cause, fix, confidence)."""
    sev, tpl, cause, fix, conf = REASONS[code]
    return dict(sev=sev, code=code, detail=tpl.format(**kw), cause=cause, fix=fix.format(**kw), conf=conf)


class Reader:
    """Why: checkers need random access (head, tail, arbitrary offsets) on one read-only handle."""

    def __init__(self, f, size):
        self.f, self.size = f, size
        self.head = self.at(0, config.INTEGRITY_HEAD_BYTES)
        tail_len = min(size, config.INTEGRITY_TAIL_BYTES)
        self.tail = self.at(size - tail_len, tail_len) if tail_len else b""

    def at(self, pos, n):
        if pos < 0 or pos >= self.size or n <= 0:
            return b""
        self.f.seek(pos)
        return self.f.read(n)


def _u16le(b, o=0): return struct.unpack_from("<H", b, o)[0]
def _u32le(b, o=0): return struct.unpack_from("<I", b, o)[0]
def _u64le(b, o=0): return struct.unpack_from("<Q", b, o)[0]
def _u32be(b, o=0): return struct.unpack_from(">I", b, o)[0]
def _u64be(b, o=0): return struct.unpack_from(">Q", b, o)[0]


# ---------------- sniffing ----------------
def sniff(head):
    """Why: the real type comes from the first bytes, so a PNG named .jpg is checked as a PNG."""
    if head[:3] == b"\xff\xd8\xff": return "jpeg"
    if head[:8] == PNG_SIG: return "png"
    if head[:4] == b"GIF8": return "gif"
    if b"%PDF-" in head[:1024]: return "pdf"
    if head[:4] in (b"PK\x03\x04", b"PK\x05\x06"): return "zip"
    if head[:8] == OLE_SIG: return "ole"
    if head[:4] == b"RIFF": return "riff"
    if head[4:8] == b"ftyp": return "mp4"
    if head[:4] == b"\x1a\x45\xdf\xa3": return "mkv"
    if head[:4] == b"OggS": return "ogg"
    if head[:4] == b"fLaC": return "flac"
    if head[:6] == SEVENZ_SIG: return "sevenz"
    if head[:6] == b"Rar!\x1a\x07": return "rar"
    if head[:3] == b"\x1f\x8b\x08": return "gz"
    if head[:2] == b"MZ" and len(head) > 0x40: return "pe"
    if head[257:262] == b"ustar": return "tar"
    return None


# ---------------- per-format checkers: (reader, deep, ext) -> list of findings ----------------
def _jpeg_find_eoi(r):
    """Why: walking JPEG segments locates the real end marker even with data appended (motion photos)."""
    pos = 2
    while pos < r.size:
        b = r.at(pos, 4)
        if len(b) < 2:
            return finding("JPEG_NO_EOI", pos=r.size)
        if b[0] != 0xFF:
            return finding("JPEG_BAD_MARKER", pos=pos)
        m = b[1]
        if m == 0xFF:
            pos += 1
            continue
        if m in (0xD8, 0x01) or 0xD0 <= m <= 0xD7:
            pos += 2
            continue
        if m == 0xD9:
            return None
        if len(b) < 4:
            return finding("JPEG_TRUNCATED", pos=pos, size=r.size)
        seg = struct.unpack(">H", b[2:4])[0]
        if seg < 2:
            return finding("JPEG_BAD_MARKER", pos=pos)
        if pos + 2 + seg > r.size:
            return finding("JPEG_TRUNCATED", pos=pos, size=r.size)
        pos += 2 + seg
        if m == 0xDA:  # start of scan: skip entropy-coded data up to the next real marker
            pos = _jpeg_skip_entropy(r, pos)
            if pos is None:
                return finding("JPEG_NO_EOI", pos=r.size)
    return finding("JPEG_NO_EOI", pos=r.size)


def _jpeg_skip_entropy(r, pos):
    """Why: inside image data 0xFF is followed by 0x00 or a restart marker; anything else is the next marker."""
    while pos < r.size:
        chunk = r.at(pos, config.INTEGRITY_READ_CHUNK + 1)
        i = chunk.find(b"\xff")
        while 0 <= i < len(chunk) - 1:
            nxt = chunk[i + 1]
            if nxt != 0x00 and not 0xD0 <= nxt <= 0xD7 and nxt != 0xFF:
                return pos + i
            i = chunk.find(b"\xff", i + 1)
        pos += max(1, len(chunk) - 1)
    return None


def chk_jpeg(r, deep, ext):
    """Why: JPEG = SOI marker, segments, image data, EOI marker; a missing EOI means the picture was cut off."""
    if r.head[:3] != b"\xff\xd8\xff":
        return [finding("JPEG_NO_SOI")]
    if not deep and r.tail.rstrip(b"\x00").endswith(b"\xff\xd9"):
        return []
    f = _jpeg_find_eoi(r)
    return [f] if f else []


def chk_png(r, deep, ext):
    """Why: PNG = signature + length/type/data/CRC chunks ending with IEND; deep mode verifies every CRC."""
    if r.head[:8] != PNG_SIG:
        return [finding("PNG_BAD_SIG")]
    if not deep and r.tail.rstrip(b"\x00").endswith(b"IEND\xaeB`\x82"):
        return []
    pos, first = 8, True
    while True:
        hdr = r.at(pos, 8)
        if len(hdr) < 8:
            return [finding("PNG_TRUNCATED", pos=pos)]
        ln, typ = struct.unpack(">I4s", hdr)
        if first and typ != b"IHDR":
            return [finding("PNG_NO_IHDR")]
        end = pos + 12 + ln
        if end > r.size:
            return [finding("PNG_TRUNCATED", pos=r.size)]
        if deep:
            data = r.at(pos + 4, 4 + ln)
            if (zlib.crc32(data) & 0xFFFFFFFF) != _u32be(r.at(pos + 8 + ln, 4)):
                return [finding("PNG_BAD_CRC", chunk=typ.decode("latin-1"), pos=pos)]
        if typ == b"IEND":
            return []
        pos, first = end, False


def chk_gif(r, deep, ext):
    """Why: a GIF starts with GIF87a/GIF89a and ends with the ';' trailer byte."""
    if r.head[:6] not in (b"GIF87a", b"GIF89a"):
        return [finding("GIF_BAD_SIG")]
    return [] if r.tail.rstrip(b"\x00").endswith(b";") else [finding("GIF_NO_TRAILER", pos=r.size)]


def chk_riff(r, deep, ext):
    """Why: RIFF files (WAV/AVI/WebP) store their own size; a shorter file was cut off."""
    if r.head[:4] != b"RIFF" or len(r.head) < 12:
        return [finding("RIFF_BAD_SIG")]
    out = []
    expected = _u32le(r.head, 4) + 8
    if r.size < expected:
        out.append(finding("RIFF_TRUNCATED", expected=expected, size=r.size))
    form = RIFF_FORMS.get(r.head[8:12])
    if form and ext in FAMILY_EXTS["riff"].split() and form[0] != ext:
        out.append(finding("EXT_MISMATCH", real=form[1], ext=ext, good=form[0]))
    return out


def chk_bmp(r, deep, ext):
    """Why: BMP headers declare the file size and pixel offset; both must fit in the file."""
    if r.head[:2] != b"BM" or len(r.head) < 14:
        return [finding("BMP_BAD_SIG")]
    declared, offbits = _u32le(r.head, 2), _u32le(r.head, 10)
    if (declared and r.size < declared) or offbits >= r.size:
        return [finding("BMP_TRUNCATED", expected=max(declared, offbits + 1), size=r.size)]
    return []


_STARTXREF = re.compile(rb"startxref\s+(\d+)")
_OBJ = re.compile(rb"\s*\d+\s+\d+\s+obj")


def _pdf_check_xref_table(r, off):
    """Why: deep mode verifies that classic xref entries really point at 'N G obj'."""
    data = r.at(off, 20 * (MAX_PDF_OBJ_CHECKS + 50) + 200)
    lines = data.split(b"\n")[1:]
    checked, num = 0, 0
    for line in lines:
        parts = line.strip().split()
        if len(parts) == 2 and all(p.isdigit() for p in parts):
            num = int(parts[0])
            continue
        if len(parts) != 3 or parts[2] not in (b"n", b"f"):
            break
        if parts[2] == b"n" and int(parts[0]) > 0:
            o = int(parts[0])
            if not _OBJ.match(r.at(o, 40)):
                return finding("PDF_BAD_OBJ", num=num, off=o)
            checked += 1
            if checked >= MAX_PDF_OBJ_CHECKS:
                break
        num += 1
    return None


def chk_pdf(r, deep, ext):
    """Why: a PDF needs its %PDF- header, a startxref pointer to a valid xref and a final %%EOF."""
    if b"%PDF-" not in r.head[:1024]:
        return [finding("PDF_NO_HEADER")]
    tail = r.tail.rstrip(b"\x00\r\n\t ")
    if b"%%EOF" not in tail[-2048:]:
        return [finding("PDF_NO_EOF", pos=r.size)]
    m = None
    for m in _STARTXREF.finditer(r.tail):
        pass
    if not m:
        return [finding("PDF_NO_STARTXREF")]
    off = int(m.group(1))
    chunk = r.at(off, 64).lstrip()
    if chunk.startswith(b"xref"):
        if deep:
            bad = _pdf_check_xref_table(r, off)
            return [bad] if bad else []
        return []
    if _OBJ.match(chunk):
        return []  # cross-reference stream (PDF 1.5+)
    return [finding("PDF_BAD_XREF", off=off)]


def chk_zip(r, deep, ext):
    """Why: ZIP-based files need a central directory; Office/ODF/EPUB/APK need their key parts; deep mode tests CRCs."""
    if r.head[:4] not in (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"):
        return [finding("ZIP_BAD_SIG")]
    try:
        zf = zipfile.ZipFile(r.f)
    except (zipfile.BadZipFile, OSError, ValueError, EOFError):
        return [finding("ZIP_NO_CDIR")]
    with zf:
        names = set(zf.namelist())
        need = {"apk": ("AndroidManifest.xml", "Android app")}.get(ext)
        if ext in OOXML:
            need = ("[Content_Types].xml", "Office")
        elif ext in ODF or ext == "epub":
            need = ("mimetype", "OpenDocument" if ext in ODF else "EPUB")
        if need and need[0] not in names:
            return [finding("ZIP_MISSING_PART", part=need[0], kind=need[1])]
        if not deep:
            return []
        try:
            bad = zf.testzip()
        except RuntimeError as ex:
            return [finding("ZIP_ENCRYPTED")] if "encrypt" in str(ex).lower() else [finding("ZIP_BAD_DATA", err=type(ex).__name__)]
        except NotImplementedError as ex:
            return [finding("ZIP_UNSUPPORTED", err=str(ex)[:60])]
        except (zipfile.BadZipFile, zlib.error, EOFError, OSError, ValueError) as ex:
            return [finding("ZIP_BAD_DATA", err=type(ex).__name__)]
        return [finding("ZIP_BAD_CRC", member=bad)] if bad else []


def chk_ole(r, deep, ext):
    """Why: legacy Office and MSI files are OLE compound files; their sectors must fit inside the file."""
    if r.head[:8] != OLE_SIG or len(r.head) < 512:
        return [finding("OLE_BAD_SIG")]
    shift = _u16le(r.head, 30)
    if shift not in (9, 12):
        return [finding("OLE_BAD_HEADER")]
    ssz = 1 << shift
    sectors = [_u32le(r.head, 48)] + ([_u32le(r.head, 76 + 4 * i) for i in range(109)] if deep else [])
    for s in sectors:
        if s >= 0xFFFFFFFA:  # free / end-of-chain markers
            continue
        need = (s + 1) * ssz + ssz
        if need > r.size:
            return [finding("OLE_TRUNCATED", pos=need, size=r.size)]
    return []


def chk_mp4(r, deep, ext):
    """Why: MP4/MOV are a chain of boxes; each size must fit, and 'moov' (the index) must exist."""
    pos, types, out = 0, [], []
    while pos < r.size and len(types) < MAX_ATOMS:
        h = r.at(pos, 16)
        if len(h) < 8:
            out.append(finding("MP4_TRUNCATED", atom="?", pos=pos, need=pos + 8, size=r.size))
            break
        sz, typ, hl = _u32be(h), h[4:8], 8
        if sz == 1:
            if len(h) < 16:
                out.append(finding("MP4_TRUNCATED", atom=typ.decode("latin-1"), pos=pos, need=pos + 16, size=r.size))
                break
            sz, hl = _u64be(h, 8), 16
        elif sz == 0:
            sz = r.size - pos
        name = typ.decode("latin-1")
        if not all(32 <= c < 127 for c in typ) or sz < hl:
            out.append(finding("MP4_BAD_ATOM", pos=pos, atom=name.encode("unicode_escape").decode()))
            break
        types.append(typ)
        if pos + sz > r.size:
            out.append(finding("MP4_TRUNCATED", atom=name, pos=pos, need=pos + sz, size=r.size))
            break
        pos += sz
    if b"moov" not in types:
        out.insert(0, finding("MP4_NO_MOOV"))
    elif types and types[0] != b"ftyp" and ext not in ("mov", "qt") and not out:
        out.append(finding("MP4_NO_FTYP"))
    return out


def _vint(buf, pos, keep_marker=False):
    """Why: Matroska (EBML) lengths are variable-width integers; returns (value, width) or (None, 0)."""
    if pos >= len(buf):
        return None, 0
    first = buf[pos]
    width = 1
    mask = 0x80
    while width <= 8 and not first & mask:
        mask >>= 1
        width += 1
    if width > 8 or pos + width > len(buf):
        return None, 0
    val = first if keep_marker else first & (mask - 1)
    for b in buf[pos + 1:pos + width]:
        val = (val << 8) | b
    return val, width


def chk_mkv(r, deep, ext):
    """Why: Matroska/WebM = EBML header + one Segment whose declared size must fit in the file."""
    if r.head[:4] != b"\x1a\x45\xdf\xa3":
        return [finding("MKV_BAD_SIG")]
    size, w = _vint(r.head, 4)
    if size is None:
        return [finding("MKV_BAD_SIG")]
    pos = 4 + w + size
    seg_id, w1 = _vint(r.head, pos, keep_marker=True)
    if seg_id != 0x18538067:
        return []
    seg_size, w2 = _vint(r.head, pos + w1)
    if seg_size is None or seg_size == (1 << (7 * w2)) - 1:  # unknown size (live recording): cannot check
        return []
    need = pos + w1 + w2 + seg_size
    return [finding("MKV_TRUNCATED", need=need, size=r.size)] if need > r.size else []


_MP3_BITRATE_BAD, _MP3_RATE_BAD = 0xF, 0x3


def _mp3_frame_at(b):
    """Why: a valid MPEG audio frame header has an 11-bit sync and legal bitrate/sample-rate fields."""
    return (len(b) >= 4 and b[0] == 0xFF and (b[1] & 0xE0) == 0xE0 and (b[1] >> 3) & 3 != 1 and (b[1] >> 1) & 3 != 0
            and (b[2] >> 4) != _MP3_BITRATE_BAD and (b[2] >> 2) & 3 != _MP3_RATE_BAD)


def chk_mp3(r, deep, ext):
    """Why: an MP3 is an optional ID3 tag followed by MPEG audio frames."""
    pos = 0
    if r.head[:3] == b"ID3" and len(r.head) >= 10:
        sz = 0
        for b in r.head[6:10]:
            sz = (sz << 7) | (b & 0x7F)
        pos = sz + 10 + (10 if r.head[5] & 0x10 else 0)
        if pos >= r.size:
            return [finding("MP3_TRUNCATED", need=pos, size=r.size)]
    window = r.at(pos, 8192)
    for i in range(max(0, len(window) - 3)):
        if _mp3_frame_at(window[i:i + 4]):
            return []
    return [finding("MP3_NO_FRAME", pos=pos)]


def chk_flac(r, deep, ext):
    """Why: FLAC = 'fLaC' + metadata blocks (STREAMINFO first) + audio frames."""
    pos = 0
    if r.head[:3] == b"ID3" and len(r.head) >= 10:
        sz = 0
        for b in r.head[6:10]:
            sz = (sz << 7) | (b & 0x7F)
        pos = sz + 10
    if r.at(pos, 4) != b"fLaC":
        return [finding("FLAC_BAD_SIG")]
    pos += 4
    while True:
        h = r.at(pos, 4)
        if len(h) < 4:
            return [finding("FLAC_TRUNCATED", need=pos + 4, size=r.size)]
        last, length = h[0] & 0x80, int.from_bytes(h[1:4], "big")
        pos += 4 + length
        if pos > r.size:
            return [finding("FLAC_TRUNCATED", need=pos, size=r.size)]
        if last:
            return []


def _ogg_crc_table():
    """Why: Ogg uses a non-reflected CRC-32 (poly 0x04C11DB7), not zlib's."""
    table = []
    for i in range(256):
        c = i << 24
        for _ in range(8):
            c = ((c << 1) ^ 0x04C11DB7) if c & 0x80000000 else (c << 1)
        table.append(c & 0xFFFFFFFF)
    return table


_OGG_TABLE = _ogg_crc_table()


def _ogg_crc(data):
    """Why: verifying a page needs its CRC computed with the CRC field set to zero."""
    crc = 0
    t = _OGG_TABLE
    for b in data:
        crc = ((crc << 8) & 0xFFFFFFFF) ^ t[((crc >> 24) & 0xFF) ^ b]
    return crc


def chk_ogg(r, deep, ext):
    """Why: Ogg = a chain of pages ('OggS' + segment table); each page must fit and (deep) match its CRC."""
    if r.head[:4] != b"OggS":
        return [finding("OGG_BAD_SIG")]
    if not deep:
        last = r.tail.rfind(b"OggS")
        if last < 0:
            return [finding("OGG_TRUNCATED", pos=r.size, size=r.size)]
        page_pos = r.size - len(r.tail) + last
        return _ogg_page(r, page_pos, False)[1]
    pos, pages = 0, 0
    while pos < r.size:
        pos, out = _ogg_page(r, pos, pages < MAX_OGG_CRC_PAGES)
        if out:
            return out
        pages += 1
    return []


def _ogg_page(r, pos, verify_crc):
    """Why: one page = 27-byte header + segment table + data; returns (next_pos, findings)."""
    hdr = r.at(pos, 27)
    if len(hdr) < 27 or hdr[:4] != b"OggS":
        return r.size, [finding("OGG_TRUNCATED", pos=pos, size=r.size)]
    nseg = hdr[26]
    segs = r.at(pos + 27, nseg)
    if len(segs) < nseg:
        return r.size, [finding("OGG_TRUNCATED", pos=pos, size=r.size)]
    total = 27 + nseg + sum(segs)
    if pos + total > r.size:
        return r.size, [finding("OGG_TRUNCATED", pos=pos, size=r.size)]
    if verify_crc:
        page = bytearray(r.at(pos, total))
        want = _u32le(page, 22)
        page[22:26] = b"\0\0\0\0"
        if _ogg_crc(page) != want:
            return r.size, [finding("OGG_BAD_CRC", pos=pos)]
    return pos + total, []


def chk_pe(r, deep, ext):
    """Why: Windows programs = 'MZ' + 'PE' header + sections; a section past the end means a cut-off download."""
    if r.head[:2] != b"MZ" or len(r.head) < 0x40:
        return [finding("PE_BAD_SIG", what="MZ signature")]
    lfanew = _u32le(r.head, 0x3C)
    if r.at(lfanew, 4) != b"PE\0\0":
        return [finding("PE_BAD_SIG", what="PE signature")]
    coff = r.at(lfanew + 4, 20)
    if len(coff) < 20:
        return [finding("PE_TRUNCATED", sect="header", need=lfanew + 24, size=r.size)]
    nsec, opt = _u16le(coff, 2), _u16le(coff, 16)
    table = lfanew + 24 + opt
    for i in range(min(nsec, MAX_PE_SECTIONS)):
        s = r.at(table + 40 * i, 40)
        if len(s) < 40:
            return [finding("PE_TRUNCATED", sect="section table", need=table + 40 * (i + 1), size=r.size)]
        raw_size, raw_ptr = _u32le(s, 16), _u32le(s, 20)
        if raw_size and raw_ptr + raw_size > r.size:
            name = s[:8].rstrip(b"\0").decode("latin-1") or f"#{i}"
            return [finding("PE_TRUNCATED", sect=name, need=raw_ptr + raw_size, size=r.size)]
    return []


def chk_7z(r, deep, ext):
    """Why: 7-Zip has a CRC-protected start header pointing at the archive index at the end."""
    if r.head[:6] != SEVENZ_SIG or len(r.head) < 32:
        return [finding("SEVENZ_BAD_SIG")]
    if (zlib.crc32(r.head[12:32]) & 0xFFFFFFFF) != _u32le(r.head, 8):
        return [finding("SEVENZ_BAD_HEADER")]
    off, size, crc = _u64le(r.head, 12), _u64le(r.head, 20), _u32le(r.head, 28)
    if 32 + off + size > r.size:
        return [finding("SEVENZ_TRUNCATED", need=32 + off + size, size=r.size)]
    if deep and size <= MAX_7Z_HEADER_BYTES:
        if (zlib.crc32(r.at(32 + off, size)) & 0xFFFFFFFF) != crc:
            return [finding("SEVENZ_BAD_CRC", pos=32 + off)]
    return []


def chk_rar(r, deep, ext):
    """Why: RAR 4/5 archives start with 'Rar!' and normally end with an end-of-archive block."""
    if r.head[:6] != b"Rar!\x1a\x07":
        return [finding("RAR_BAD_SIG")]
    end = r.tail[-64:]   # the end markers themselves end in 0x00, so search instead of stripping padding
    return [] if RAR4_END in end or RAR5_END in end else [finding("RAR_NO_END", pos=r.size)]


def chk_gz(r, deep, ext):
    """Why: gzip needs its signature and a complete deflate stream with a matching CRC (deep mode)."""
    if r.head[:2] != b"\x1f\x8b":
        return [finding("GZ_BAD_SIG")]
    if r.size < 18:
        return [finding("GZ_TRUNCATED", size=r.size)]
    if not deep:
        return []
    r.f.seek(0)
    try:
        with gzip.GzipFile(fileobj=r.f) as g:
            while g.read(config.INTEGRITY_READ_CHUNK):
                pass
    except EOFError:
        return [finding("GZ_TRUNCATED", size=r.size)]
    except (gzip.BadGzipFile, zlib.error) as ex:
        return [finding("GZ_BAD_CRC", err=str(ex)[:60])]
    return []


def chk_tar(r, deep, ext):
    """Why: TAR headers carry a checksum, and every member's data must fit inside the archive."""
    block = r.head[:512]
    if len(block) < 512:
        return [finding("TAR_TRUNCATED", member="header", need=512, size=r.size)]
    try:
        stored = int(block[148:156].strip(b"\0 ").decode("ascii") or "0", 8)
    except ValueError:
        return [finding("TAR_BAD_HEADER")]
    if stored != sum(block[:148]) + 8 * 32 + sum(block[156:512]):
        return [finding("TAR_BAD_HEADER")]
    if not deep:
        return []
    r.f.seek(0)
    try:
        with tarfile.open(fileobj=r.f, mode="r:") as tf:
            for m in tf:
                if m.isfile() and m.offset_data + m.size > r.size:
                    return [finding("TAR_TRUNCATED", member=m.name, need=m.offset_data + m.size, size=r.size)]
    except tarfile.TarError:
        return [finding("TAR_TRUNCATED", member="?", need=r.size + 1, size=r.size)]
    return []


def chk_iso(r, deep, ext):
    """Why: ISO 9660/UDF images have a volume descriptor at sector 16 and a declared size."""
    ident = r.at(ISO_PVD_OFFSET, 5)
    if ident not in (b"CD001", b"BEA01", b"NSR02", b"NSR03"):
        return [finding("ISO_BAD_SIG")]
    if ident == b"CD001":
        blocks = r.at(ISO_PVD_OFFSET - 1 + 80, 4)
        if len(blocks) == 4 and _u32le(blocks) * ISO_SECTOR > r.size:
            return [finding("ISO_TRUNCATED", need=_u32le(blocks) * ISO_SECTOR, size=r.size)]
    return []


CHECKERS = {"jpeg": chk_jpeg, "png": chk_png, "gif": chk_gif, "riff": chk_riff, "bmp": chk_bmp, "pdf": chk_pdf, "zip": chk_zip,
            "ole": chk_ole, "mp4": chk_mp4, "mkv": chk_mkv, "mp3": chk_mp3, "flac": chk_flac, "ogg": chk_ogg, "pe": chk_pe,
            "sevenz": chk_7z, "rar": chk_rar, "gz": chk_gz, "tar": chk_tar, "iso": chk_iso}


# ---------------- generic checks ----------------
def _read_through(r):
    """Why: deep mode reads every byte so bad sectors show up; also reports whether the file is all zeros."""
    r.f.seek(0)
    pos, all_zero = 0, True
    try:
        while True:
            chunk = r.f.read(config.INTEGRITY_READ_CHUNK)
            if not chunk:
                return None, all_zero
            if all_zero and chunk.count(0) != len(chunk):
                all_zero = False
            pos += len(chunk)
    except OSError:
        return finding("READ_ERROR", pos=pos), all_zero


def _is_zero(b):
    """Why: a cheap 'only NUL bytes' test for the null-filled check."""
    return bool(b) and b.count(0) == len(b)


def worst(findings):
    """Why: lists show the most serious finding first."""
    return max(findings, key=lambda f: SEVERITY_RANK[f["sev"]]) if findings else None


def check(path, ext=None, deep=False):
    """Why: the one entry point: returns {'status': 'ok'|'problem'|'skipped', 'findings': [...]} and never writes."""
    ext = (ext if ext is not None else os.path.splitext(path)[1][1:]).lower()
    try:
        size = os.path.getsize(path)
    except PermissionError:
        return dict(status="skipped", reason="no access", findings=[])
    except OSError:
        return dict(status="skipped", reason="missing", findings=[])
    if size == 0:
        return dict(status="problem", findings=[finding("EMPTY")])
    if ext in config.PARTIAL_DOWNLOAD_EXTS:
        return dict(status="problem", findings=[finding("PARTIAL_DOWNLOAD", ext=ext)])
    findings = []
    if ext in config.TEMP_EXTS:
        findings.append(finding("TEMP_FILE", ext=ext))
    try:
        with open(path, "rb") as f:
            r = Reader(f, size)
            if _is_zero(r.head) and _is_zero(r.tail):
                if not deep:
                    return dict(status="problem", findings=[finding("NULL_FILLED", where="")])
                err, all_zero = _read_through(r)
                if err:
                    return dict(status="problem", findings=[err])
                if all_zero:
                    return dict(status="problem", findings=[finding("NULL_FILLED", where=f" (all {size:,} bytes)")])
            fam = EXT_FAMILY.get(ext)
            real = sniff(r.head)
            if real and fam and real != fam:
                label, good = FAMILY_LABEL.get(real, (real, real))
                findings.append(finding("EXT_MISMATCH", real=label, ext=ext, good=good))
                fam = real   # check it as what it really is
            elif real and not fam and real in ("pe",) and ext in _MEDIA_AND_DOC_EXTS:
                findings.append(finding("EXT_MISMATCH", real=FAMILY_LABEL["pe"][0], ext=ext, good="exe"))
            if fam in CHECKERS:
                findings += CHECKERS[fam](r, deep, ext)
            if deep:
                err, _ = _read_through(r)
                if err:
                    findings.append(err)
    except PermissionError:
        return dict(status="skipped", reason="no access", findings=[])
    except OSError:
        return dict(status="problem", findings=[finding("READ_ERROR", pos=0)])
    findings.sort(key=lambda f: -SEVERITY_RANK[f["sev"]])
    return dict(status="problem" if findings else "ok", findings=findings)


_MEDIA_AND_DOC_EXTS = frozenset("txt md csv rtf heic heif tif tiff avif svg".split())
