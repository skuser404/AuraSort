"""User settings (scan folders, skip list, destination, view-only opt-ins), stored as private JSON."""
import json
import os
import threading

from . import classify, config
from .platform_utils import make_private

AI_DEFAULTS = dict(consent_local=0, consent_cloud=0, engine="ollama", local_url="", model="", ttl_min=config.AI_TTL_DEFAULT_MIN, parallel=1,
                   ctx=config.AI_CONTEXT_DEFAULT, pages=config.AI_MAX_PAGES, cpu_friendly=False, provider="deepseek",
                   cloud_url=config.AI_CLOUD_PRESETS["deepseek"]["base_url"], cloud_model=config.AI_CLOUD_PRESETS["deepseek"]["model"])
DEFAULTS = dict(roots=[], skip=[], dest="", dest_roots=[], optin=[], mode="quick", drives=[], ai=AI_DEFAULTS)
_LOCK = threading.Lock()
MAX_LIST = 200


def _clean_ai(value):
    """Why: AI settings come from the browser too; each field is checked (never an API key: those live in keystore.py)."""
    if not isinstance(value, dict):
        raise ValueError("Invalid settings.")
    out = dict(AI_DEFAULTS)
    num = lambda k, lo, hi: max(lo, min(hi, int(value.get(k, out[k]))))
    out.update(consent_local=float(value.get("consent_local") or 0), consent_cloud=float(value.get("consent_cloud") or 0),
               engine=value.get("engine") if value.get("engine") in config.AI_LOCAL_ENGINES else "ollama",
               local_url=str(value.get("local_url") or "")[:200], model=str(value.get("model") or "")[:120],
               ttl_min=int(value.get("ttl_min")) if value.get("ttl_min") in config.AI_TTL_CHOICES_MIN else config.AI_TTL_DEFAULT_MIN,
               parallel=num("parallel", 1, config.AI_PARALLEL_MAX), ctx=num("ctx", 1024, 32768), pages=num("pages", 1, 50),
               cpu_friendly=bool(value.get("cpu_friendly")), provider=value.get("provider") if value.get("provider") in config.AI_CLOUD_PRESETS else "deepseek",
               cloud_url=str(value.get("cloud_url") or "")[:300], cloud_model=str(value.get("cloud_model") or "")[:120])
    return out


def load():
    """Why: missing or broken settings fall back to defaults instead of breaking start-up."""
    try:
        data = json.loads(config.SETTINGS_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError
    except (OSError, ValueError):
        data = {}
    out = dict(DEFAULTS)
    for k, v in data.items():
        if k not in DEFAULTS:
            continue
        try:
            out[k] = {**AI_DEFAULTS, **v} if k == "ai" and isinstance(v, dict) else _clean(k, v)
        except (TypeError, ValueError):
            out[k] = DEFAULTS[k]       # an old or hand-edited file with a wrong type must not break scans later
    return out


def _clean(key, value):
    """Why: settings come from the browser, so every value is type- and size-checked."""
    if key in ("roots", "skip", "dest_roots", "drives"):
        if not isinstance(value, list):
            raise ValueError("Invalid settings.")
        # long paths are kept whole or dropped: a cut-off path would silently point at a different folder
        return [v for v in value if isinstance(v, str) and v.strip() and len(v) <= config.MAX_PATH_CHARS][:MAX_LIST]
    if key == "optin":
        return [c for c in value if c in classify.VIEW_ONLY] if isinstance(value, list) else []
    if key == "mode":
        return value if value in ("quick", "deep") else "quick"
    if key == "dest":
        return str(value) if len(str(value)) <= config.MAX_PATH_CHARS else ""
    if key == "ai":
        return _clean_ai(value)
    raise ValueError("Unknown setting.")


def update(**changes):
    """Why: atomic, private write of the merged settings."""
    with _LOCK:
        data = load()
        for k, v in changes.items():
            data[k] = _clean(k, v)
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        tmp = config.SETTINGS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
        os.replace(tmp, config.SETTINGS_FILE)
        if not config.WIN:
            make_private(config.SETTINGS_FILE, is_dir=False)
        return data


def remember_destination(dest):
    """Why: folders inside earlier destinations are labelled 'already sorted' and start unticked."""
    data = load()
    roots = [d for d in data["dest_roots"] if os.path.normcase(d) != os.path.normcase(dest)]
    update(dest_roots=[dest] + roots)
