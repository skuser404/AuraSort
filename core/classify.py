"""File classification: extension -> category / sub-category, view-only rules and preview/open allow-lists."""
import re

from . import config

# (category, extensions, view_only). Order = display order. "Other" catches every unknown extension.
CATEGORIES = (
    ("Images", "jpg jpeg png gif webp heic heif bmp tif tiff avif svg dng cr2 cr3 nef arw raw orf rw2 ico jfif", False),
    ("Videos", "mp4 mov mkv avi webm m4v 3gp 3g2 wmv flv mts m2ts mpg mpeg vob", False),
    ("Audio", "mp3 wav flac m4a aac ogg opus wma amr aiff aif mid midi", False),
    ("Documents", "doc docx odt rtf txt md epub pages mobi docm dotx dot tex", False),
    ("PDFs", "pdf", False),
    ("Sheets & Slides", "xls xlsx csv ods ppt pptx key numbers odp xlsm pptm tsv", False),
    ("Archives", "zip rar 7z tar gz tgz bz2 xz zst lz cab", False),
    ("Installers & Apps", "exe msi apk ipa dmg pkg deb rpm appimage msix appx app xapk", True),
    ("Disk images", "iso img vhd vhdx vmdk", True),
    ("Code & Scripts", "py pyw js mjs cjs ts tsx jsx java c h cpp hpp cc cs go rs php sh bash zsh bat cmd ps1 psm1 sql "
                       "rb swift kt kts lua pl r html htm css scss sass vue ipynb dart scala", True),
    ("Text & Logs", "log json xml yml yaml ini cfg conf toml env properties", True),
    ("Fonts", "ttf otf woff woff2 fon fnt", True),
    ("Databases", "db sqlite sqlite3 mdb accdb dbf frm ibd kdbx", True),
    ("Other", "", True),
)
CATEGORY_NAMES = tuple(c for c, _, _ in CATEGORIES)
VIEW_ONLY = frozenset(c for c, _, v in CATEGORIES if v)
MOVABLE = frozenset(CATEGORY_NAMES) - VIEW_ONLY
EXT2CAT = {e: c for c, exts, _ in CATEGORIES for e in exts.split()}

# Never "Open file" these: opening would run code, install something or mount a disk. Only "Open location" is offered.
BLOCKED_OPEN = frozenset("""exe msi bat cmd ps1 psm1 psd1 ps1xml psc1 vbs vbe vb js jse ws wsf wsh wsc scr com pif jar jnlp apk xapk ipa
dmg pkg mpkg app appimage run deb rpm snap flatpakref sh bash zsh csh ksh fish command tool terminal desktop lnk url website
webloc inetloc fileloc reg hta chm dll ocx sys drv cpl msc inf ins isp scf application appref-ms gadget msix msixbundle appx
appxbundle msp mst xbap xll xpi crx py pyw pyc pyo pyz rb pl php workflow action settingcontent-ms library-ms search-ms
mobileconfig scpt scptd applescript iso img vhd vhdx""".split())
# Office files that can contain macros: warn once before opening.
MACRO_OFFICE = frozenset("xlsm docm pptm xltm dotm potm ppsm xlam ppam sldm".split())

# Content types served for in-browser preview (everything else: details + Open buttons only).
PREVIEW_MIME = {
    "jpg": "image/jpeg", "jpeg": "image/jpeg", "jfif": "image/jpeg", "png": "image/png", "gif": "image/gif",
    "webp": "image/webp", "bmp": "image/bmp", "avif": "image/avif", "svg": "image/svg+xml", "ico": "image/x-icon",
    "mp4": "video/mp4", "m4v": "video/mp4", "webm": "video/webm", "mov": "video/quicktime", "ogv": "video/ogg",
    "mp3": "audio/mpeg", "wav": "audio/wav", "ogg": "audio/ogg", "opus": "audio/ogg", "m4a": "audio/mp4",
    "aac": "audio/aac", "flac": "audio/flac", "pdf": "application/pdf",
}
TEXT_PREVIEW_EXTS = frozenset("""txt md log json xml yml yaml ini cfg conf toml csv tsv env properties py js ts tsx jsx java c h cpp
hpp cs go rs php sh bat cmd ps1 sql rb swift kt lua pl r html htm css scss vue dart tex""".split())
WEB_THUMB_EXTS = frozenset("jpg jpeg jfif png gif webp bmp avif svg ico".split())

_RX = dict(
    shot=re.compile(r"screen ?shot|screenshot|screen_shot|capture", re.I),
    cam=re.compile(r"^(IMG|DSC|DSCN|PXL|DJI|MVIMG|VID|MOV|GOPR|GX)[-_ ]?\d|^\d{8}[_-]\d{6}", re.I),
    wa=re.compile(r"WA\d{4}|whatsapp|^(IMG|VID|AUD|PTT)-\d{8}-WA", re.I),
    rec=re.compile(r"screen ?record|screenrecord|recording", re.I),
    voice=re.compile(r"voice|recording|^rec[-_ ]?\d|^AUD-|^PTT-|memo", re.I),
    inv=re.compile(r"invoice|receipt|bill|statement|payslip", re.I),
    cv=re.compile(r"resume|\bcv\b|certificate|offer|marksheet|transcript", re.I),
)


def ext_of(name):
    """Why: one place decides what counts as an extension (lowercase, no dot, '' for none)."""
    base = name.rsplit("/", 1)[-1]
    return base.rsplit(".", 1)[-1].lower() if "." in base.strip(".") else ""


def category(ext):
    """Why: every file must land in exactly one category; unknown extensions go to Other."""
    return EXT2CAT.get(ext, "Other")


def is_view_only(cat):
    """Why: view-only categories are listed and searchable but never moved/deleted without opt-in."""
    return cat in VIEW_ONLY


def subcategory(cat, name, ext):
    """Why: auto-organize sorts into helpful sub-folders such as Images/Camera."""
    rx = _RX
    if cat == "Images":
        if rx["shot"].search(name): return "Screenshots"
        if rx["cam"].search(name): return "Camera"
        if rx["wa"].search(name): return "WhatsApp"
        if ext in ("dng", "cr2", "cr3", "nef", "arw", "raw", "orf", "rw2"): return "RAW"
        if ext in ("png", "svg", "gif", "webp", "ico"): return "Graphics"
        return "Photos"
    if cat == "Videos":
        if rx["rec"].search(name): return "Screen recordings"
        if rx["cam"].search(name): return "Camera"
        if rx["wa"].search(name): return "WhatsApp"
        return "Clips & movies"
    if cat == "Audio":
        if rx["wa"].search(name): return "WhatsApp audio"
        if rx["voice"].search(name): return "Recordings"
        return "Music"
    if cat == "PDFs":
        if rx["inv"].search(name): return "Invoices & receipts"
        if rx["cv"].search(name): return "Resumes & certificates"
        return "Other PDFs"
    if cat == "Documents":
        if ext in ("epub", "mobi"): return "eBooks"
        if ext in ("txt", "md", "tex"): return "Notes & text"
        return "Word docs"
    if cat == "Sheets & Slides":
        return "Presentations" if ext in ("ppt", "pptx", "odp", "key", "pptm") else "Spreadsheets"
    if cat == "Archives":
        return "Compressed"
    if cat == "Installers & Apps":
        return "Windows" if ext in ("exe", "msi", "msix", "appx") else "Android" if ext in ("apk", "xapk") else "Mac & Linux"
    return ext.upper() if ext else "No extension"


def classify(name):
    """Why: the scanner needs (ext, category, sub-category) for each file in one call."""
    ext = ext_of(name)
    cat = category(ext)
    return ext, cat, subcategory(cat, name, ext)


def open_block_reason(ext):
    """Why: 'Open file' must never run code; refused types get a friendly reason instead of a silent failure."""
    if not ext:
        return (f"Files without an extension are not opened by {config.APP_NAME}, because the system might run them as a program. "
                "Use Open location instead.")
    if ext in BLOCKED_OPEN:
        return f"For your safety, {config.APP_NAME} never opens programs, scripts, shortcuts or disk images. Use Open location instead."
    return ""


def can_open(ext):
    """Why: one yes/no answer for the UI and the server."""
    return not open_block_reason(ext)


STREAM_KINDS = ("image", "video", "audio", "pdf")   # previews served as the real file through /api/file


def preview_kind(ext):
    """Why: the preview panel needs to know how (or whether) the browser can show a file."""
    mime = PREVIEW_MIME.get(ext, "")
    if mime.startswith("image/"): return "image"
    if mime.startswith("video/"): return "video"
    if mime.startswith("audio/"): return "audio"
    if mime == "application/pdf": return "pdf"
    if ext in TEXT_PREVIEW_EXTS: return "text"
    return "none"


def preview_mime(ext):
    """Why: /api/file only serves content types from a fixed allow-list (text is always text/plain)."""
    if ext in PREVIEW_MIME:
        return PREVIEW_MIME[ext]
    if ext in TEXT_PREVIEW_EXTS:
        return "text/plain; charset=utf-8"
    return None
