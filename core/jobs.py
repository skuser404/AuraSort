"""Background jobs (scan, move, trash, integrity, duplicates): progress, pause/resume/cancel and smoothed ETA."""
import secrets
import threading
import time

from . import config


class Cancelled(Exception):
    """Why: raised inside a worker loop when the user cancels, so cleanup code runs once."""


class Job:
    """Why: every long task reports the same fields so the UI can show %, elapsed, ETA and speed uniformly."""

    def __init__(self, kind, total=0, total_bytes=0, **extra):
        self.id = time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3)
        self.kind, self.state = kind, "running"
        self.total, self.done, self.total_bytes, self.bytes = total, 0, total_bytes, 0
        self.started, self.finished = time.time(), None
        self.current_file, self.errors, self.extra = "", [], dict(extra)
        self._run = threading.Event()
        self._run.set()
        self._cancel = False
        self._rate = self._brate = None
        self._mark = (self.started, 0, 0)
        self._paused_s, self._paused_at = 0.0, None
        self.lock = threading.Lock()

    # ---- control ----
    def pause(self):
        if self.state == "running":
            self.state, self._paused_at = "paused", time.time()
            self._run.clear()

    def resume(self):
        if self.state == "paused":
            self._paused_s += time.time() - (self._paused_at or time.time())
            self.state, self._paused_at = "running", None
            self._run.set()

    def cancel(self):
        self._cancel = True
        self._run.set()

    def checkpoint(self):
        """Why: workers call this between items; it blocks while paused and stops on cancel."""
        self._run.wait()
        if self._cancel:
            raise Cancelled()

    def finish(self, state="done"):
        self.state, self.finished = state, time.time()
        self._run.set()

    def error(self, msg):
        if len(self.errors) < 50:
            self.errors.append(msg)

    # ---- progress ----
    def elapsed(self):
        end = self.finished or time.time()
        paused = self._paused_s + ((time.time() - self._paused_at) if self._paused_at else 0)
        return max(0.0, end - self.started - paused)

    def _update_rates(self):
        """Why: an exponential moving average keeps the ETA from jumping around."""
        t0, d0, b0 = self._mark
        now = time.time()
        if now - t0 < 0.5 or self.state != "running":
            return
        r, br = (self.done - d0) / (now - t0), (self.bytes - b0) / (now - t0)
        a = config.ETA_SMOOTHING
        self._rate = r if self._rate is None else a * r + (1 - a) * self._rate
        self._brate = br if self._brate is None else a * br + (1 - a) * self._brate
        self._mark = (now, self.done, self.bytes)

    def remaining_s(self):
        """Why: prefer bytes (copies) when known, else items; None while there is not enough data."""
        self._update_rates()
        if self.total_bytes and self._brate and self._brate > 0:
            return max(0.0, (self.total_bytes - self.bytes) / self._brate)
        if self.total and self._rate and self._rate > 0:
            return max(0.0, (self.total - self.done) / self._rate)
        return None

    def snapshot(self):
        """Why: JSON-safe view for /api/job; lists are copied so concurrent updates can't break serialisation."""
        rem = self.remaining_s() if self.state in ("running", "paused") else 0
        el = self.elapsed()
        snap = dict(id=self.id, kind=self.kind, state=self.state, total=self.total, done=self.done, bytes=self.bytes,
                    total_bytes=self.total_bytes, elapsed=round(el, 1), remaining=None if rem is None else round(rem, 1),
                    rate=round(self.done / el, 1) if el > 0 else 0, bytes_rate=round(self.bytes / el) if el > 0 else 0,
                    pct=round(100 * self.done / self.total, 1) if self.total else (100.0 if self.state == "done" else 0.0),
                    current_file=self.current_file, errors=list(self.errors))
        for k, v in list(self.extra.items()):
            snap[k] = list(v) if isinstance(v, list) else dict(v) if isinstance(v, dict) else v
        return snap


JOBS = {}
_LOCK = threading.Lock()


def start(job, target, *args):
    """Why: register the job, run it on a daemon thread, and always end in a final state."""
    with _LOCK:
        JOBS[job.id] = job

    def runner():
        try:
            target(job, *args)
            if job.state in ("running", "paused"):
                job.finish("done")
        except Cancelled:
            job.finish("cancelled")
        except Exception as ex:  # noqa: BLE001 - reported to the UI, details go to the log
            from .log import log
            log.exception("job %s failed", job.kind)
            job.error(f"Unexpected error ({type(ex).__name__}).")
            job.finish("error")
    threading.Thread(target=runner, daemon=True, name=f"job-{job.kind}").start()
    return job


def get(job_id):
    """Why: unknown ids are a normal 404-style error, not a crash."""
    job = JOBS.get(str(job_id))
    if not job:
        raise ValueError("Unknown job.")
    return job


def running(kind):
    """Why: only one scan (or integrity check, ...) may run at a time."""
    return any(j.kind == kind and j.state in ("running", "paused") for j in JOBS.values())
