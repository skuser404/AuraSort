"""Builders for healthy and broken sample files (pure Python, no Pillow), used by unit tests and tools/make_fixtures.py."""
import gzip
import io
import os
import struct
import tarfile
import wave
import zipfile
import zlib


def _crc(b):
    return zlib.crc32(b) & 0xFFFFFFFF


def jpeg(entropy=b"\x12\x34\x56\x78" * 64):
    """A structurally valid baseline JPEG (SOI, APP0, DQT, SOF0, DHT, SOS, data, EOI)."""
    seg = lambda m, payload: b"\xff" + bytes([m]) + struct.pack(">H", len(payload) + 2) + payload
    out = b"\xff\xd8"
    out += seg(0xE0, b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00")
    out += seg(0xDB, b"\x00" + bytes(range(1, 65)))
    out += seg(0xC0, b"\x08\x00\x10\x00\x10\x01\x01\x11\x00")
    out += seg(0xC4, b"\x00" + b"\x00" * 16)
    out += seg(0xDA, b"\x01\x01\x00\x00\x3f\x00")
    return out + entropy + b"\xff\xd9"


def png(width=4, height=4):
    """A real PNG (RGB, zlib-compressed rows, correct CRCs)."""
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", _crc(t + d))
    raw = b"".join(b"\x00" + b"".join(bytes([(x * 40) % 256, (y * 60) % 256, 128]) for x in range(width)) for y in range(height))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) + \
        chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def png_bad_crc():
    """PNG whose IDAT data was altered after the CRC was written."""
    data = bytearray(png())
    idat = data.find(b"IDAT")
    data[idat + 6] ^= 0xFF
    return bytes(data)


def gif():
    """Smallest valid GIF89a (1x1)."""
    return (b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00"
            b",\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;")


def wav(frames=800):
    """A real WAV written by the standard library."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\x00\x01" * frames)
    return buf.getvalue()


def webp():
    """RIFF/WEBP container with a dummy VP8 chunk and a correct RIFF size."""
    body = b"WEBP" + b"VP8 " + struct.pack("<I", 10) + b"\x00" * 10
    return b"RIFF" + struct.pack("<I", len(body)) + body


def bmp(w=2, h=2):
    """24-bit BMP with correct file size and pixel offset."""
    row = (b"\x00\x00\xff" * w).ljust((w * 3 + 3) & ~3, b"\x00")
    pixels = row * h
    dib = struct.pack("<IiiHHIIiiII", 40, w, h, 1, 24, 0, len(pixels), 2835, 2835, 0, 0)
    size = 14 + len(dib) + len(pixels)
    return b"BM" + struct.pack("<IHHI", size, 0, 0, 54) + dib + pixels


def pdf(pages=2):
    """Multi-page PDF with a correct classic xref table."""
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [" + b" ".join(f"{3 + i} 0 R".encode() for i in range(pages)) + b"] /Count " + str(pages).encode() + b" >>"]
    for i in range(pages):
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] /Contents {3 + pages + i} 0 R >>".encode())
    for i in range(pages):
        stream = f"BT /F1 24 Tf 50 100 Td (Page {i + 1}) Tj ET".encode()
        objs.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")
    out, offsets = b"%PDF-1.4\n", []
    for n, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{n} 0 obj\n".encode() + o + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


def zip_file(members=None, stored=True):
    """ZIP archive; stored members make byte-level corruption deterministic."""
    members = members or {"readme.txt": b"hello " * 50, "data/numbers.csv": b"1,2,3\n" * 40}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED) as z:
        for name, data in members.items():
            z.writestr(name, data)
    return buf.getvalue()


def docx():
    """Minimal Office Open XML container (the parts integrity checks look for)."""
    return zip_file({"[Content_Types].xml": b"<Types/>", "word/document.xml": b"<w:document/>" * 20, "_rels/.rels": b"<Relationships/>"})


def xlsx():
    return zip_file({"[Content_Types].xml": b"<Types/>", "xl/workbook.xml": b"<workbook/>" * 20})


def zip_bad_crc(builder=zip_file):
    """Flip one byte of a stored member's data so its CRC no longer matches."""
    data = bytearray(builder())
    pos = data.find(b"PK\x03\x04")
    name_len, extra_len = struct.unpack_from("<HH", data, pos + 26)
    data[pos + 30 + name_len + extra_len + 3] ^= 0xFF
    return bytes(data)


def apk():
    return zip_file({"AndroidManifest.xml": b"\x03\x00\x08\x00" * 10, "classes.dex": b"dex\n035\x00" * 10})


def ole(sectors=3):
    """OLE compound-file header (legacy .doc/.xls/.msi) with a directory sector inside the file."""
    hdr = bytearray(512)
    hdr[0:8] = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
    struct.pack_into("<HHH", hdr, 24, 0x3E, 3, 0xFFFE)
    struct.pack_into("<H", hdr, 30, 9)                 # 512-byte sectors
    struct.pack_into("<I", hdr, 44, 1)                 # one FAT sector
    struct.pack_into("<I", hdr, 48, 1)                 # directory starts at sector 1
    struct.pack_into("<I", hdr, 76, 0)                 # FAT sector 0
    for i in range(1, 109):
        struct.pack_into("<I", hdr, 76 + 4 * i, 0xFFFFFFFF)
    return bytes(hdr) + b"\x00" * 512 * sectors


def mp4(with_moov=True, cut=0):
    """ISO-BMFF: ftyp + (moov) + mdat. cut>0 removes bytes from the end (truncated download)."""
    box = lambda t, d: struct.pack(">I", 8 + len(d)) + t + d
    out = box(b"ftyp", b"isom\x00\x00\x02\x00isomiso2mp41")
    if with_moov:
        out += box(b"moov", box(b"mvhd", b"\x00" * 100))
    out += box(b"mdat", b"\x55" * 4000)
    return out[:-cut] if cut else out


def mkv(cut=0):
    """EBML header + Segment of known size."""
    ebml_body = b"\x42\x86\x81\x01\x42\xf7\x81\x01\x42\x82\x84webm"
    seg_body = b"\x00" * 300
    out = b"\x1a\x45\xdf\xa3" + bytes([0x80 | len(ebml_body)]) + ebml_body
    out += b"\x18\x53\x80\x67" + b"\x41" + struct.pack(">B", len(seg_body) - 256) + seg_body  # 2-byte vint (0x4000|300)
    return out[:-cut] if cut else out


def mp3():
    """ID3v2 tag + MPEG-1 Layer III frames (128 kbps, 44.1 kHz)."""
    tag = b"ID3\x03\x00\x00" + bytes([0, 0, 0, 10]) + b"\x00" * 10
    frame = b"\xff\xfb\x90\x00" + b"\x00" * 413
    return tag + frame * 5


def flac():
    """'fLaC' + last STREAMINFO block (34 bytes) + a frame sync."""
    return b"fLaC" + b"\x80" + (34).to_bytes(3, "big") + b"\x00" * 34 + b"\xff\xf8" + b"\x00" * 40


def ogg(pages=2):
    """Ogg pages with correct CRCs (uses the checker's own CRC for symmetry with the spec algorithm)."""
    from core.integrity import _ogg_crc
    out = b""
    for seq in range(pages):
        data = b"\x01vorbis" + b"\x00" * 40
        hdr = bytearray(b"OggS\x00" + bytes([2 if seq == 0 else 0]) + b"\x00" * 8 + struct.pack("<IIi", 1, seq, 0) + bytes([1, len(data)]))
        page = hdr + data
        struct.pack_into("<I", page, 22, _ogg_crc(bytes(page)))
        out += bytes(page)
    return out


def exe(cut=0):
    """MZ + PE header with one section whose raw data lies inside the file."""
    mz = bytearray(64)
    mz[0:2] = b"MZ"
    struct.pack_into("<I", mz, 0x3C, 64)
    coff = struct.pack("<HHIIIHH", 0x14C, 1, 0, 0, 0, 0, 0x0102)
    sect = b".text\x00\x00\x00" + struct.pack("<IIIIIIHHI", 0x100, 0x1000, 0x200, 0x200, 0, 0, 0, 0, 0x60000020)
    head = bytes(mz) + b"PE\x00\x00" + coff + sect
    out = head.ljust(0x200, b"\x00") + b"\xc3" * 0x200
    return out[:-cut] if cut else out


def sevenz(cut=0):
    """7-Zip signature header with correct start-header CRC and a next header at the end."""
    nh = b"\x01\x04\x06\x00" + b"\x00" * 12
    body = b"\x00" * 64
    start = struct.pack("<QQI", len(body), len(nh), _crc(nh))
    out = b"7z\xbc\xaf\x27\x1c\x00\x04" + struct.pack("<I", _crc(start)) + start + body + nh
    return out[:-cut] if cut else out


def rar5():
    """RAR5 signature + dummy header + end-of-archive block."""
    return b"Rar!\x1a\x07\x01\x00" + b"\x00" * 32 + b"\x1d\x77\x56\x51\x03\x05\x04\x00"


def gz(cut=0):
    out = gzip.compress(os.urandom(2000) * 3)
    return out[:-cut] if cut else out


def tar_file():
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as t:
        data = b"x" * 3000
        info = tarfile.TarInfo("notes/a.txt")
        info.size = len(data)
        t.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def iso(blocks=20):
    """ISO 9660 image: primary volume descriptor at sector 16 declaring `blocks` sectors."""
    img = bytearray(2048 * blocks)
    pvd = 0x8000
    img[pvd] = 1
    img[pvd + 1:pvd + 6] = b"CD001"
    struct.pack_into("<I", img, pvd + 80, blocks)
    struct.pack_into(">I", img, pvd + 84, blocks)
    return bytes(img)


def docx_text(text):
    """A .docx whose paragraphs are the given lines (for Document Insights)."""
    paras = "".join(f"<w:p><w:r><w:t>{t}</w:t></w:r></w:p>" for t in text.split("\n"))
    return zip_file({"[Content_Types].xml": b"<Types/>", "word/document.xml": f'<w:document xmlns:w="x"><w:body>{paras}</w:body></w:document>'.encode()})


def pdf_text(lines):
    """An uncompressed one-page PDF showing the given lines (readable without pypdf)."""
    ops = " ".join(f"({ln}) Tj" for ln in lines).encode()
    stream = b"BT /F1 12 Tf 50 700 Td " + ops + b" ET"
    return (b"%PDF-1.4\n1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n"
            b"3 0 obj << /Type /Page /Parent 2 0 R /Contents 4 0 R >> endobj\n4 0 obj << /Length " + str(len(stream)).encode() + b" >>\nstream\n"
            + stream + b"\nendstream\nendobj\ntrailer << /Root 1 0 R >>\n%%EOF\n")


def fake_aadhaar(first11="23412341234"):
    """A syntactically valid but fake Aadhaar number (Verhoeff check digit), for tests only."""
    from core.sensitive import _VERHOEFF_D as d, _VERHOEFF_P as p
    inv, c = [0, 4, 3, 2, 1, 5, 6, 7, 8, 9], 0
    for i, ch in enumerate(reversed(first11)):
        c = d[c][p[(i + 1) % 8][int(ch)]]
    return first11 + str(inv[c])


def write(path, data):
    """Write bytes, creating parent folders."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    return path
