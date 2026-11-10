"""Document Insights: read document text locally, run the rule-based confidential check, ask a model (local by default,
an optional cloud API only after per-batch confirmation) for a short description, and keep the results in memory only.
Results are cleared a user-set time after the batch finishes, on exit, and per file when it is moved or deleted.
No document text is written to disk, the log, History or snapshots. The model can only suggest; it never acts."""
import os
import shutil
import subprocess  # nosec B404  # fixed argument lists only
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from . import config, extract, index_db, jobs, keystore, llm, sensitive, settings
from .log import log

_STORE = dict(results={}, finished=None, ttl_min=config.AI_TTL_DEFAULT_MIN, batch=None)
_LOCK = threading.RLock()
_PROC = dict(p=None)
CREATE_NO_WINDOW = 0x08000000


def ai_settings():
    return settings.load()["ai"]


# ---------------- results store (memory only) ----------------
def expires_at():
    """Why: the clock starts when the batch finishes; None while it is still running (or empty)."""
    f = _STORE["finished"]
    return f + _STORE["ttl_min"] * 60 if f and _STORE["results"] else None


def purge_if_expired(now=None):
    """Why: results disappear automatically after the chosen time."""
    exp = expires_at()
    if exp and (now or time.time()) >= exp:
        clear()
        return True
    return False


def clear():
    """Why: 'Clear now', the timer, and 'reset AI settings' all end here."""
    with _LOCK:
        _STORE["results"].clear()
        _STORE["finished"] = _STORE["batch"] = None


def forget(fids):
    """Why: a file that was moved or sent to the Recycle Bin loses its result immediately."""
    with _LOCK:
        for fid in fids:
            _STORE["results"].pop(int(fid), None)


index_db.LISTENERS.append(forget)


def results():
    purge_if_expired()
    with _LOCK:
        return dict(_STORE["results"])


def _matches(r, f):
    if f["sens"] and r["level"] != f["sens"]:
        return False
    if f["doctype"] and f["doctype"] not in r["doc_type"].lower():
        return False
    if f["junk"] and not (r["junk"] == "high" or r["action"] == "delete-candidate"):
        return False
    if f["exts"] and r["ext"] not in f["exts"]:
        return False
    if f["q"] and f["q"] not in f"{r['name']} {r['description']} {r['doc_type']}".lower():
        return False
    if f["dfrom"] is not None and not (f["dfrom"] <= r["mtime"] < f["dto"]):
        return False
    return True


def query(f, page=1, per=config.AI_RESULTS_PAGE):
    """Why: filter + sort (confidential first) + page over the in-memory results, with counts for the filter chips."""
    allr = list(results().values())
    hits = [r for r in allr if _matches(r, f)]
    hits.sort(key=lambda r: (-sensitive.RANK[r["level"]], r["name"].lower()))
    pages = max(1, -(-len(hits) // per))
    page = min(max(1, page), pages)
    levels = {lvl: sum(1 for r in allr if r["level"] == lvl) for lvl in sensitive.LEVELS}
    types = {}
    for r in allr:
        if r["doc_type"]:
            types[r["doc_type"]] = types.get(r["doc_type"], 0) + 1
    return dict(total=len(hits), page=page, pages=pages, per=per, size=sum(r["size"] for r in hits), rows=hits[(page - 1) * per: page * per],
                ids=[r["fid"] for r in hits], levels=levels, types=sorted(types.items(), key=lambda t: -t[1])[:20], summary=summary())


def summary():
    r = results()
    lv = [x["level"] for x in r.values()]
    return dict(count=len(r), confidential=lv.count("confidential"), sensitive=lv.count("sensitive"), expires_at=expires_at(),
                ttl_min=_STORE["ttl_min"], batch=_STORE["batch"])


# ---------------- engines ----------------
def make_engine(mode, s=None):
    """Why: local engines only on 127.0.0.1; the cloud only with a key from the keystore."""
    s = s or ai_settings()
    if mode == "local":
        kind = "ollama" if s["engine"] == "ollama" else "openai"
        return llm.Engine(kind, llm.local_base(s["engine"], s["local_url"]), s["model"], ctx=s["ctx"])
    if mode == "cloud":
        key = keystore.get()
        if not key:
            raise llm.LLMError("Connect the cloud provider first (paste an API key).")
        return llm.Engine("cloud", llm.cloud_base(s["cloud_url"]), s["cloud_model"], key=key, ctx=s["ctx"])
    return None


def engine_status(s=None):
    """Why: the setup screen shows what is installed, what is running and which models exist."""
    s = s or ai_settings()
    out = dict(engine=s["engine"], installed=bool(shutil.which("ollama")) if s["engine"] == "ollama" else None, running=False, models=[],
               started_by_us=bool(_PROC["p"] and _PROC["p"].poll() is None), url="")
    try:
        eng = make_engine("local", s)
        out["url"] = eng.base
        out["models"] = eng.models()
        out["running"] = True
    except llm.LLMError as e:
        out["error"] = str(e)
    return out


def start_engine():
    """Why: 'Start engine' runs `ollama serve` (argument list, no shell) only when the user clicks it."""
    exe = shutil.which("ollama")
    if not exe:
        raise llm.LLMError("Ollama is not installed. Download it from " + config.AI_DOWNLOADS["ollama"])
    if _PROC["p"] and _PROC["p"].poll() is None:
        return True
    flags = CREATE_NO_WINDOW if config.WIN else 0
    _PROC["p"] = subprocess.Popen([exe, "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)  # nosec B603
    log.info("started the local AI engine (ollama serve)")
    return True


def stop_engine():
    """Why: on exit, stop the engine only if AuraSort started it."""
    p = _PROC["p"]
    if p and p.poll() is None:
        p.terminate()
    _PROC["p"] = None


# ---------------- documents in scope ----------------
def doc_rows(ids=None):
    """Why: Document Insights reads PDFs, Office files and plain text only; ids come from the index, never paths."""
    if ids is None:
        ids, _ = index_db.ids_for({"exts": list(extract.DOC_EXTS), "scope": "all"})
    rows = []
    for i in range(0, len(ids), index_db.SQL_VARS):
        rows += [r for r in index_db.rows_by_ids(ids[i:i + index_db.SQL_VARS]) if r["ext"] in extract.DOC_EXTS and not r["flags"] & index_db.FLAG_CLOUD]
    return rows


def _model_label(eng, name, text, cloud):
    """Why: long documents are summarised in chunks and then combined; the excerpt is always quoted data."""
    excerpt = sensitive.redact(text)[:config.AI_CLOUD_MAX_CHARS] if cloud else text
    chunks = [excerpt[i:i + config.AI_CHUNK_CHARS] for i in range(0, max(1, len(excerpt)), config.AI_CHUNK_CHARS)] or [""]
    parts = [llm.parse_reply(eng.chat(llm.user_message(name, c))) for c in chunks]
    if len(parts) == 1:
        return parts[0]
    joined = "\n".join(f"Part {i + 1}: {p['doc_type']}: {p['description']}" for i, p in enumerate(parts))
    final = llm.parse_reply(eng.chat(llm.user_message(name, joined)))
    worst = max((p["sensitivity"] for p in parts + [final]), key=sensitive.RANK.get)
    final["sensitivity"], final["key_fields"] = worst, list(dict.fromkeys(k for p in parts for k in p["key_fields"]))[:llm.KEY_FIELDS_MAX]
    return final


def _clean_label(lab):
    """Why: a model might copy an ID or number into its description; those are masked before anything is shown."""
    return dict(lab, description=sensitive.redact(lab["description"]), key_fields=[sensitive.redact(k) for k in lab["key_fields"]])


def _read(r, pages):
    """Why: extraction + rules for one file (local, no model)."""
    path = os.path.join(r["path"], r["name"])
    ex = extract.extract(path, r["ext"], r["size"], pages)
    rule = sensitive.scan(ex.text, r["name"]) if ex.text else dict(level="normal", reasons=[])
    res = dict(fid=r["id"], name=r["name"], ext=r["ext"], size=r["size"], mtime=r["mtime"], cat=r["cat"], status=ex.status, note=ex.note,
               pages=ex.pages, truncated=ex.truncated, rule=rule, level=rule["level"], reasons=rule["reasons"], doc_type="", description="",
               key_fields=[], junk="", action="", by="")
    return res, ex.text


def run(job, rows, mode, opts):
    """Why: phase 1 reads every file locally; for the cloud the job then waits for an explicit confirmation of exactly
    what will be sent; phase 2 asks the model. One bad file or reply never stops the batch."""
    s = ai_settings()
    _STORE["ttl_min"] = s["ttl_min"]
    clear()
    _STORE["batch"] = dict(job=job.id, mode=mode, total=len(rows), started=time.time())
    texts = {}
    job.extra.update(phase="reading", read=0, labelled=0, confidential=0, failed=0, cloud_plan=None)
    for r in rows:
        job.checkpoint()
        job.current_file = r["name"]
        res, text = _read(r, s["pages"])
        texts[r["id"]] = text
        with _LOCK:
            _STORE["results"][r["id"]] = res
        job.extra["read"] += 1
        job.extra["confidential"] += res["level"] == "confidential"
        job.done += 1 if mode == "rules" else 0
    if mode != "rules":
        todo = [r for r in rows if texts.get(r["id"])]
        if mode == "cloud":
            todo = _await_cloud_ok(job, todo, texts)
        _label_all(job, todo, texts, mode, s)
    with _LOCK:
        _STORE["finished"] = time.time()


def _await_cloud_ok(job, todo, texts):
    """Why: nothing goes to a cloud provider until the user saw exactly what will be sent and confirmed this batch."""
    conf = [r for r in todo if _STORE["results"][r["id"]]["level"] == "confidential"]
    job.extra["cloud_plan"] = dict(files=len(todo), confidential=len(conf), chars=sum(min(len(texts[r["id"]]), config.AI_CLOUD_MAX_CHARS) for r in todo),
                                   pages=sum(_STORE["results"][r["id"]]["pages"] for r in todo), masked=True)
    job.extra["phase"] = "confirm"
    job.cloud_ok = threading.Event()
    job.state = "waiting"
    while not job.cloud_ok.wait(0.25):
        if job._cancel:
            raise jobs.Cancelled()
    job.state = "running"
    if not job.extra.get("allow_confidential"):
        for r in conf:
            _STORE["results"][r["id"]]["note"] = "Not sent to the cloud: flagged Confidential."
        todo = [r for r in todo if r not in conf]
    return todo


def confirm_cloud(job, allow_confidential):
    """Why: the per-batch 'Send' button in the cloud notice."""
    if job.extra.get("phase") != "confirm":
        raise ValueError("This batch is not waiting for a confirmation.")
    job.extra["allow_confidential"] = bool(allow_confidential)
    job.cloud_ok.set()


def _label_all(job, todo, texts, mode, s):
    job.extra["phase"] = "thinking"
    job.total, job.done = len(todo), 0
    try:
        eng = make_engine(mode, s)
    except llm.LLMError as e:
        for r in todo:
            _STORE["results"][r["id"]]["note"] = f"Not summarised: {e}"
        job.error(str(e))
        return

    def one(r):
        job.checkpoint()
        job.current_file = r["name"]
        res = _STORE["results"][r["id"]]
        try:
            lab = _clean_label(_model_label(eng, r["name"], texts[r["id"]], mode == "cloud"))
            combined = sensitive.combine(res["rule"], dict(level=lab["sensitivity"], reason=lab["sensitivity_reason"]))
            res.update(doc_type=lab["doc_type"], description=lab["description"], key_fields=lab["key_fields"], junk=lab["junk_likelihood"],
                       action=lab["suggested_action"], level=combined["level"], reasons=combined["reasons"], by=mode)
            job.extra["labelled"] += 1
        except (ValueError, KeyError, TypeError):
            res["note"] = "Could not summarise this one (the model's reply was not valid)."
            job.extra["failed"] += 1
        except llm.LLMError as e:
            res["note"] = f"Could not summarise this one: {e}"
            job.extra["failed"] += 1
        job.done += 1

    workers = 1 if s["cpu_friendly"] else s["parallel"]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(one, todo))
    job.extra["confidential"] = sum(1 for x in _STORE["results"].values() if x["level"] == "confidential")


def start(ids, mode):
    """Why: one Document Insights batch at a time."""
    if mode not in ("local", "cloud", "rules"):
        raise ValueError("Unknown mode.")
    if jobs.running("docai"):
        raise ValueError("Document Insights is already running.")
    s = ai_settings()
    if mode == "local" and not s["consent_local"]:
        raise ValueError("Turn on Document Insights first.")
    if mode == "cloud" and not s["consent_cloud"]:
        raise ValueError("Connect and allow the cloud provider first.")
    rows = doc_rows(ids)
    if not rows:
        raise ValueError("No documents (PDF, Word, PowerPoint, Excel, text) in that selection.")
    job = jobs.Job("docai", total=len(rows), mode=mode)
    return jobs.start(job, run, rows, mode, {})


def pull_model(name):
    """Why: download a model through Ollama's API, with progress, after the user confirmed."""
    eng = make_engine("local")
    if not eng.ollama:
        raise ValueError("Model downloads are done inside LM Studio or llama.cpp for those engines.")
    job = jobs.Job("pull", total=0, model=name, status="starting")

    def run_pull(j):
        def prog(status, done, total):
            j.extra["status"] = status
            j.total_bytes, j.bytes = total, done
        eng.timeout = None
        eng.pull(name, prog, lambda: j._cancel)
    return jobs.start(job, run_pull)


def reset():
    """Why: 'Withdraw consent / reset AI settings': settings back to defaults, key removed, results cleared, engine stopped."""
    clear()
    keystore.clear()
    stop_engine()
    settings.update(ai=dict(settings.AI_DEFAULTS))


def file_rows_for(fids):
    """Why: results are shown with the file's current folder and flags from the index."""
    return {r["id"]: r for r in index_db.rows_by_ids(list(fids))}

