"""Safety rules: protected system locations, project/asset folder detection, safe names and path containment."""
import os
import re
import stat

from . import config
from .platform_utils import is_reparse_or_link, long_path, within

WIN, MAC = config.WIN, config.MAC
_nc = os.path.normcase

# Folder names that are never scanned into or touched, wherever they appear.
PROTECTED_NAMES = frozenset((
    "node_modules", ".git", ".svn", ".hg", "__pycache__", "venv", ".venv", "site-packages", "appdata", ".cache", ".npm",
    ".gradle", ".m2", ".idea", ".vscode", ".trash", ".trashes", ".spotlight-v100", ".fseventsd", ".documentrevisions-v100",
    ".temporaryitems", ".tox", ".mypy_cache", ".pytest_cache", "windowsapps", ".aurasorttrash",
))
# System folders that only count when they sit directly in a drive root (C:\Recovery, E:\$Recycle.Bin ...).
ROOT_SYSTEM_NAMES = frozenset((
    "$recycle.bin", "system volume information", "recovery", "$winreagent", "config.msi", "perflogs", "$sysreset",
    "$windows.~bt", "$windows.~ws", "program files", "program files (x86)", "windows", "programdata", "msocache",
))


def _env_paths(*keys):
    """Why: Windows system folders move around (other drive letters), so read them from the environment."""
    return [os.path.normpath(os.environ[k]) for k in keys if os.environ.get(k)]


def protected_prefixes():
    """Why: whole system trees (Windows, Program Files, /System, /usr...) are off-limits on every platform."""
    home = str(config.HOME)
    if config.ANDROID:   # Termux: Android's own system, Termux's programs, and other apps' private data
        return ["/system", "/vendor", "/apex", "/product", "/proc", "/sys", "/dev", os.environ.get("PREFIX") or "/data/data/com.termux/files/usr",
                "/storage/emulated/0/Android", os.path.join(home, ".local", "share", "Trash")]
    if WIN:
        return _env_paths("WINDIR", "ProgramFiles", "ProgramFiles(x86)", "ProgramW6432", "ProgramData", "APPDATA",
                          "LOCALAPPDATA") + [os.path.join(home, "AppData")]
    if MAC:
        return ["/System", "/Library", "/usr", "/bin", "/sbin", "/private", "/cores", "/dev", "/etc", "/var", "/opt",
                "/Applications", os.path.join(home, "Library"), os.path.join(home, ".Trash")]
    return ["/bin", "/sbin", "/usr", "/etc", "/var", "/lib", "/lib32", "/lib64", "/opt", "/proc", "/sys", "/dev", "/boot",
            "/run", "/snap", "/srv", "/root", "/tmp", os.path.join(home, ".local", "share", "Trash")]  # nosec B108  # /tmp is listed to PROTECT it, not used as a temp file


_PREFIXES = None


def canonical(path):
    """Why: user-supplied paths are resolved first: realpath expands Windows 8.3 short names (like PROGRA~1) and links,
    so no spelling of a path can slip past the protection rules."""
    return os.path.realpath(os.path.abspath(os.path.expanduser(str(path))))


def _prefixes():
    """Why: computed once (canonical form); the environment does not change while the server runs."""
    global _PREFIXES
    if _PREFIXES is None:
        homes = {_nc(canonical(config.HOME)), _nc(os.path.abspath(str(config.HOME)))}   # both spellings (8.3 and long)
        found = {_nc(canonical(p)) for p in protected_prefixes()} | {_nc(os.path.abspath(p)) for p in protected_prefixes()}
        # A home folder inside a "system" tree (root's /root on Linux) must stay scannable, or every scan finds 0 files.
        _PREFIXES = sorted(p for p in found if not any(within(h, p) for h in homes))
    return _PREFIXES


def _home_or_above(p):
    """Why: a user called 'venv' or 'AppData' must not have the home folder itself treated as a tool folder."""
    home = _nc(os.path.abspath(str(config.HOME)))
    return p == home or within(home, p)


_DATA_CANON = {}


def _data_dir():
    """Why: resolved once (realpath is a system call; protection checks run for every folder during a scan)."""
    key = str(config.DATA_DIR)
    if key not in _DATA_CANON:
        _DATA_CANON.clear()
        _DATA_CANON[key] = {_nc(canonical(config.DATA_DIR)), _nc(os.path.abspath(key))}   # both spellings (8.3 and long)
    return _DATA_CANON[key]


def protection_reason(path):
    """Why: the UI explains *why* a folder is locked; None means the path is not protected."""
    p = _nc(os.path.abspath(path))
    base = os.path.basename(p).lower()
    if base in PROTECTED_NAMES and not _home_or_above(p):
        return f"'{os.path.basename(path)}' is a system or tool folder"
    parent = os.path.dirname(p)
    if base in ROOT_SYSTEM_NAMES and os.path.dirname(parent) == parent:
        return "system folder at the top of a drive"
    if base.endswith(config.MAC_BUNDLE_EXTS) and not os.path.isfile(path):
        return "app bundle (treated as a single item)"
    if any(p == d or within(p, d) for d in _data_dir()):
        return f"{config.APP_NAME}'s own data folder"
    for pre in _prefixes():
        if p == pre or p.startswith(pre.rstrip(os.sep) + os.sep):
            return "protected system location"
    return None


def is_protected(path):
    """Why: a single yes/no check used by the scanner, browser and every action."""
    return protection_reason(path) is not None


# ---------------- project & asset folders ----------------
PROJECT_FILES = frozenset("""package.json pyproject.toml requirements.txt setup.py setup.cfg Pipfile poetry.lock pom.xml build.gradle
build.gradle.kts settings.gradle Cargo.toml go.mod composer.json Gemfile pubspec.yaml CMakeLists.txt Makefile manage.py Dockerfile
docker-compose.yml tsconfig.json vite.config.js vite.config.ts next.config.js angular.json Package.swift mix.exs deno.json
project.godot .git .gitignore .vscode .idea .project .classpath ProjectSettings Assets.meta""".split())
PROJECT_EXTS = (".sln", ".csproj", ".vbproj", ".fsproj", ".vcxproj", ".xcodeproj", ".xcworkspace", ".uproject", ".prproj",
                ".aep", ".aepx", ".blend", ".kdenlive", ".drp", ".fcpxml", ".flp", ".als", ".logicx", ".cpr", ".ptx",
                ".sketch", ".fig", ".xd", ".indd", ".psd_project", ".unity", ".uasset", ".pbxproj", ".band")
WEB_DIRS = frozenset("css js assets static images img styles scripts fonts".split())
ASSET_DIR_RX = re.compile(r"^(assets?|static|public|res|resources|drawable.*|mipmap.*|icons?|sprites?|textures?|thumbnails?|thumbs|"
                          r"cache|wp-content|_next|dist|build|out|www|themes?|plugins?|vendor|media|uploads)$", re.I)


# One of these alone is weak evidence (a stray requirements.txt, a .gitignore or a downloaded .blend file in Downloads
# says little). A scan root or a folder above it needs a strong marker or two different weak ones to count as a project.
WEAK_PROJECT_FILES = frozenset("requirements.txt Makefile Dockerfile docker-compose.yml .gitignore .vscode .idea .project .classpath setup.cfg".split())
WEAK_PROJECT_EXTS = (".blend", ".psd_project", ".sketch", ".fig", ".xd", ".indd", ".kdenlive", ".fcpxml", ".flp", ".als", ".band",
                     ".aep", ".aepx", ".prproj", ".drp", ".cpr", ".ptx", ".logicx", ".unity", ".uasset")


def project_markers(names):
    """Why: (strong, weak) marker counts, so 'is this a project' can be strict where a wrong yes would lock everything."""
    names = set(names)
    low = {n.lower() for n in names}
    strong = len((names & PROJECT_FILES) - WEAK_PROJECT_FILES) + sum(1 for n in low if n.endswith(PROJECT_EXTS) and not n.endswith(WEAK_PROJECT_EXTS))
    weak = len(names & WEAK_PROJECT_FILES) + sum(1 for n in low if n.endswith(WEAK_PROJECT_EXTS))
    if ("index.html" in low or "index.htm" in low) and (low & WEB_DIRS):
        weak += 1
    return strong, weak


def is_project(names, strict=False):
    """Why: files inside a project (website, app, video edit...) belong to it; moving them breaks the project.
    strict=True (scan roots and the folders above them): one weak marker is not enough."""
    strong, weak = project_markers(names)
    return strong > 0 or (weak >= 2 if strict else weak > 0)


def is_asset_dir(path):
    """Why: folders named like app/site assets start unticked even outside a detected project."""
    return bool(ASSET_DIR_RX.match(os.path.basename(os.path.normpath(path))))


def folder_kind(path, project_id):
    """Why: every folder gets one label (project / assets / ok) that decides its default tick state."""
    if project_id is not None and project_id >= 0:
        return "project"
    return "assets" if is_asset_dir(path) else "ok"


# ---------------- names & paths ----------------
_BAD_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = re.compile(r"^(con|prn|aux|nul|com[1-9]|lpt[1-9])(\..*)?$", re.I)
MAX_NAME = 255


def safe_folder_name(name):
    """Why: 'New folder' and auto-organize must create names that are legal on Windows, macOS and Linux."""
    name = (name or "").strip()
    if not name or name in (".", "..") or len(name) > MAX_NAME:
        return None
    if _BAD_CHARS.search(name) or _RESERVED.match(name) or name.endswith((".", " ")):
        return None
    return name


def clean_part(part):
    """Why: sub-folder names derived from data are sanitised rather than rejected."""
    part = _BAD_CHARS.sub("-", part).strip(" .")[: config.NAME_PART_MAX]
    if _RESERVED.match(part):
        part = "_" + part
    return part or "_"


def unique_name(dirpath, name):
    """Why: moves never overwrite; a clash becomes 'name (1).ext' (case-insensitive file systems included)."""
    base, ext = os.path.splitext(name)
    cand, i = name, 1
    while os.path.lexists(os.path.join(dirpath, cand)):
        cand = f"{base} ({i}){ext}"
        i += 1
    return cand


def real_inside(child, root):
    """Why: after resolving symlinks/junctions a path must still be inside the folder we meant."""
    try:
        return within(os.path.realpath(child), os.path.realpath(root))
    except (OSError, ValueError):
        return False


def is_plain_file(path):
    """Why: right before acting we refuse links/junctions and anything that is not a regular file."""
    try:
        st = os.lstat(long_path(path))
    except OSError:
        return False
    if is_reparse_or_link(st):     # links and junctions only; a OneDrive placeholder is a real file
        return False
    return stat.S_ISREG(st.st_mode)


def check_destination(dest):
    """Why: destinations must be real, dedicated, unprotected folders (never a drive root or the home folder itself)."""
    if not dest or not os.path.isabs(os.path.expanduser(dest)):
        raise ValueError("Choose a full folder path for the destination.")
    if os.path.islink(os.path.abspath(os.path.expanduser(dest))):
        raise ValueError("The destination is a link; choose the real folder instead.")
    dest = canonical(dest)
    if is_protected(dest):
        raise ValueError("That destination is inside a protected or system folder.")
    if _nc(dest) == _nc(canonical(config.HOME)) or os.path.dirname(dest) == dest:
        raise ValueError("Choose a dedicated folder, not your home folder or a drive root.")
    if os.path.lexists(dest) and not os.path.isdir(dest):
        raise ValueError("The destination is a file, not a folder.")
    return dest
