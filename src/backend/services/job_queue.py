"""Job queue — SQLite-backed translation jobs (Sprint 4, SPEC §3.2/§3.3/§4.3/§8).

SQLite is used **only** for the job queue (state transitions + `run_at`/expiry
queries); config stays JSON (lesson #14). One row per job:

    jobs(id, owner_email, frontend_id, source_lang, target_langs, format, path,
         glossary, mode, run_at, status, progress, estimate_s, error,
         created_at, expires_at)

State machine (SPEC §3.3):

    queued ─┐                          ┌─(success)→ done ─(retention)→ (deleted)
            ├─(run_at reached)→ running┤
  scheduled ┘                          └─(failure)→ failed

A background scheduler loop picks jobs whose ``run_at <= now`` and status is
``queued``/``scheduled``, runs the document translator, emails the result, and
sets ``expires_at = now + retention``. A retention sweep hard-deletes the files
and the row once ``expires_at`` passes (lesson #15 — actually delete the files;
documents may be sensitive). Never logs document content (lesson #16).
"""

import asyncio
import hashlib
import json
import logging
import secrets
import shutil
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterator

from src.core.config import config
from src.core.paths import JOBS_DB, DOCUMENTS_DIR

logger = logging.getLogger("backend.jobs")

_WAITING = ("queued", "scheduled")


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def _connect() -> sqlite3.Connection:
    JOBS_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(JOBS_DB)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create the jobs table if it does not exist. Idempotent."""
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id           TEXT PRIMARY KEY,
                owner_email  TEXT NOT NULL,
                frontend_id  TEXT NOT NULL DEFAULT '',
                client_ref   TEXT NOT NULL DEFAULT '',   -- sidecar-side handle (pull-inverse)
                source_lang  TEXT NOT NULL,
                target_langs TEXT NOT NULL,   -- JSON list
                format       TEXT NOT NULL,
                path         TEXT NOT NULL,
                glossary     TEXT NOT NULL DEFAULT '',
                mode         TEXT NOT NULL,   -- immediate | scheduled
                run_at       REAL NOT NULL,   -- epoch seconds
                status       TEXT NOT NULL,
                progress     TEXT NOT NULL,   -- JSON {total, done, langs_done}
                estimate_s   INTEGER NOT NULL DEFAULT 0,
                error        TEXT NOT NULL DEFAULT '',
                created_at   REAL NOT NULL,
                expires_at   REAL,            -- set on done
                priority     INTEGER NOT NULL DEFAULT 0,  -- §12.7 privilege: 1 = jump the queue
                options      TEXT NOT NULL DEFAULT '{}',  -- §13.2 per-job document options (JSON)
                origin       TEXT NOT NULL DEFAULT 'portal',  -- §16.4 portal | api
                fingerprint  TEXT NOT NULL DEFAULT ''         -- §17.4 duplicate detection
            )
            """
        )
        # Additive migrations for older DBs.
        cols = {r[1] for r in conn.execute("PRAGMA table_info(jobs)")}
        if "client_ref" not in cols:  # Sprint 5
            conn.execute("ALTER TABLE jobs ADD COLUMN client_ref TEXT NOT NULL DEFAULT ''")
        if "priority" not in cols:    # Sprint 13
            conn.execute("ALTER TABLE jobs ADD COLUMN priority INTEGER NOT NULL DEFAULT 0")
        if "options" not in cols:     # Sprint 15
            conn.execute("ALTER TABLE jobs ADD COLUMN options TEXT NOT NULL DEFAULT '{}'")
        if "origin" not in cols:      # Sprint 22
            conn.execute("ALTER TABLE jobs ADD COLUMN origin TEXT NOT NULL DEFAULT 'portal'")
        if "fingerprint" not in cols:  # Sprint 23
            conn.execute("ALTER TABLE jobs ADD COLUMN fingerprint TEXT NOT NULL DEFAULT ''")
        # Privacy-safe usage log (§12.9) — survives retention; counts only, never
        # filenames or content. One row per completed job.
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS usage_log (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                email        TEXT NOT NULL,
                frontend_id  TEXT NOT NULL DEFAULT '',
                langs        TEXT NOT NULL DEFAULT '[]',  -- JSON list of target codes
                day          TEXT NOT NULL,               -- YYYY-MM-DD (local)
                created_at   REAL NOT NULL,
                origin       TEXT NOT NULL DEFAULT 'portal'
            )
            """
        )
        if "origin" not in {r[1] for r in conn.execute("PRAGMA table_info(usage_log)")}:  # Sprint 22
            conn.execute("ALTER TABLE usage_log ADD COLUMN origin TEXT NOT NULL DEFAULT 'portal'")


def detect_tier(filename: str) -> str | None:
    """Map a filename to its supported tier (tier1|tier2|tier3), or None if
    unsupported (SPEC §4.2 / §7 `supported_formats`)."""
    ext = Path(filename).suffix.lower()
    for tier, exts in config.supported_formats.items():
        if ext in exts:
            return tier
    return None


def _row_to_job(row: sqlite3.Row) -> dict[str, Any]:
    job = dict(row)
    job["target_langs"] = json.loads(job["target_langs"])
    job["progress"] = json.loads(job["progress"])
    try:
        job["options"] = json.loads(job.get("options") or "{}")
    except (json.JSONDecodeError, TypeError):
        job["options"] = {}
    return job


# ---------------------------------------------------------------------------
# Estimate + scheduling helpers (pure — unit-testable)
# ---------------------------------------------------------------------------


def estimate_seconds(chars: int, n_langs: int, throughput: float | None = None) -> int:
    """Duration estimate = chars ÷ throughput × n_langs (SPEC §3.2)."""
    rate = throughput or config.translation_throughput_chars_per_s or 10.0
    return int(chars / rate * max(1, n_langs))


def compute_run_at(mode: str, now: datetime, hour: int, duration_hours: int, scheduling_enabled: bool) -> datetime:
    """When a scheduled job may first run (§12.6) — the start of the **nearest**
    window.

    ``immediate`` (or scheduling disabled) → now. ``scheduled``: if a window is
    **open right now**, that is the nearest window → return now, so the job is
    eligible immediately (it still queues behind everything already waiting).
    Otherwise → the next local ``hour``:00 that is ≥ now (today, else tomorrow).
    """
    if mode == "immediate" or not scheduling_enabled:
        return now
    if _in_window(now, hour, duration_hours):
        return now
    candidate = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if candidate < now:
        candidate += timedelta(days=1)
    return candidate


def _in_window(now: datetime, start_hour: int, duration_hours: int) -> bool:
    """Is ``now`` inside the nightly scheduling window (§12.6)? The window opens
    at ``start_hour``:00 local and lasts ``duration_hours`` — it may wrap past
    midnight (e.g. 23:00 + 3h → open until 02:00)."""
    if duration_hours >= 24:
        return True
    mins = now.hour * 60 + now.minute
    start = start_hour * 60
    end = start + duration_hours * 60
    if end <= 24 * 60:
        return start <= mins < end
    return mins >= start or mins < (end - 24 * 60)  # wraps past midnight


# ---------------------------------------------------------------------------
# CRUD + state transitions
# ---------------------------------------------------------------------------


def enqueue(
    owner_email: str,
    source_lang: str,
    target_langs: list[str],
    fmt: str,
    path: str,
    *,
    frontend_id: str = "",
    client_ref: str = "",
    glossary: str = "",
    mode: str = "scheduled",
    priority: bool = False,
    options: dict[str, Any] | None = None,
    chars: int | None = None,
    now: datetime | None = None,
    origin: str = "portal",
    fingerprint: str = "",
) -> dict[str, Any]:
    """Insert a new job. Computes ``run_at`` (scheduled → the next window start,
    §12.6), the duration estimate, and the initial status (``queued`` if due now,
    else ``scheduled``). ``priority`` (§12.7) lets the job jump the queue."""
    now = now or datetime.now()
    from src.api.v1.admin.settings import scheduling
    sched = scheduling(frontend_id)
    run_at_dt = compute_run_at(mode, now, sched["start_hour"], sched["duration_hours"], config.scheduling_enabled)
    if chars is None:
        from src.services.document_translator import count_translatable_chars
        chars = count_translatable_chars(path)
    estimate = estimate_seconds(chars, len(target_langs))
    status = "queued" if run_at_dt <= now else "scheduled"
    job_id = secrets.token_urlsafe(12)
    progress = {"total": len(target_langs), "done": 0, "langs_done": []}

    with _connect() as conn:
        conn.execute(
            """INSERT INTO jobs (id, owner_email, frontend_id, client_ref, source_lang,
                   target_langs, format, path, glossary, mode, run_at, status, progress,
                   estimate_s, error, created_at, expires_at, priority, options, origin, fingerprint)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (job_id, owner_email.lower().strip(), frontend_id, client_ref, source_lang,
             json.dumps(target_langs), fmt, path, glossary, mode,
             run_at_dt.timestamp(), status, json.dumps(progress), estimate,
             "", now.timestamp(), None, 1 if priority else 0, json.dumps(options or {}), origin, fingerprint),
        )
    logger.info(f"Enqueued job {job_id} status={status} run_at={run_at_dt.isoformat()} "
                f"priority={int(priority)} langs={len(target_langs)} estimate={estimate}s")
    return get(job_id)


def compute_fingerprint(data: bytes, source_lang: str, target_langs: list[str], frontend_id: str = "",
                        glossary: str = "", connection_id: str = "") -> str:
    """Identity of a submission (§17.4): same file + same parameters = same job."""
    h = hashlib.sha256(data)
    h.update(json.dumps([source_lang, sorted(target_langs), frontend_id, glossary, connection_id]).encode())
    return h.hexdigest()


def list_by_owner(owner_email: str, status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    """An owner's jobs, newest first (machine-API library, SPEC §16.2)."""
    q, params = "SELECT * FROM jobs WHERE owner_email = ?", [owner_email.lower().strip()]
    if status:
        q += " AND status = ?"
        params.append(status)
    with _connect() as conn:
        rows = conn.execute(q + " ORDER BY created_at DESC LIMIT ?", (*params, limit)).fetchall()
    return [_row_to_job(r) for r in rows]


def find_active_duplicate(owner_email: str, fingerprint: str) -> dict[str, Any] | None:
    """A queued/scheduled/running job of the same owner with the same fingerprint."""
    if not fingerprint:
        return None
    with _connect() as conn:
        row = conn.execute(
            f"SELECT * FROM jobs WHERE owner_email = ? AND fingerprint = ? "
            f"AND status IN ({','.join('?' * len(_ACTIVE))}) ORDER BY created_at LIMIT 1",
            (owner_email.lower().strip(), fingerprint, *_ACTIVE),
        ).fetchone()
    return _row_to_job(row) if row else None


def get(job_id: str, owner_email: str | None = None) -> dict[str, Any] | None:
    """Fetch a job, optionally scoped to its owner (Sprint 5 auth)."""
    with _connect() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if not row:
        return None
    job = _row_to_job(row)
    if owner_email is not None and job["owner_email"] != owner_email.lower().strip():
        return None
    return job


def get_by_ref(frontend_id: str, client_ref: str) -> dict[str, Any] | None:
    """Fetch a job by its sidecar-side client_ref within a frontend."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM jobs WHERE frontend_id = ? AND client_ref = ?",
            (frontend_id, client_ref),
        ).fetchone()
    return _row_to_job(row) if row else None


def jobs_for_frontend(frontend_id: str, statuses: tuple[str, ...] | None = None) -> list[dict[str, Any]]:
    """Jobs belonging to a frontend, optionally filtered by status (for the
    pull-inverse status push)."""
    q = "SELECT * FROM jobs WHERE frontend_id = ?"
    params: list[Any] = [frontend_id]
    if statuses:
        q += f" AND status IN ({','.join('?' * len(statuses))})"
        params.extend(statuses)
    with _connect() as conn:
        rows = conn.execute(q, params).fetchall()
    return [_row_to_job(r) for r in rows]


def eligible_jobs(now: float | None = None) -> Iterator[dict[str, Any]]:
    """Waiting jobs that may start now, in run order (§12.6; capacity is §17.1's job).

    Eligibility: a waiting job whose ``run_at`` has passed. **Immediate** jobs are
    eligible anytime; **scheduled** jobs only while ``now`` is inside the nightly
    window (unless scheduling is disabled deploy-wide, which makes everything
    immediate). Ordered **priority first** (§12.7), then by request time (FIFO).
    Jobs left when the window closes stay waiting → picked up next window
    (carry-over)."""
    now = now if now is not None else time.time()
    now_dt = datetime.fromtimestamp(now)
    with _connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM jobs WHERE status IN ({','.join('?' * len(_WAITING))}) "
            f"AND run_at <= ? ORDER BY priority DESC, created_at ASC",
            (*_WAITING, now),
        ).fetchall()
    # Walk candidates in priority-then-FIFO order; return the first eligible one.
    # Immediate jobs are eligible anytime; scheduled jobs only inside *their own
    # frontend's* window (per-frontend, §12.6) — or always when scheduling is
    # disabled deploy-wide.
    from src.api.v1.admin.settings import scheduling
    for row in rows:
        job = _row_to_job(row)
        if job["mode"] == "immediate" or not config.scheduling_enabled:
            yield job
            continue
        sched = scheduling(job.get("frontend_id", ""))
        if _in_window(now_dt, sched["start_hour"], sched["duration_hours"]):
            yield job


def list_expired(now: float | None = None) -> list[dict[str, Any]]:
    """Done or cancelled jobs whose retention window has passed."""
    now = now if now is not None else time.time()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM jobs WHERE status IN ('done', 'cancelled') AND expires_at IS NOT NULL "
            "AND expires_at < ?",
            (now,),
        ).fetchall()
    return [_row_to_job(r) for r in rows]


def _set(job_id: str, **fields: Any) -> None:
    cols = ", ".join(f"{k} = ?" for k in fields)
    with _connect() as conn:
        conn.execute(f"UPDATE jobs SET {cols} WHERE id = ?", (*fields.values(), job_id))


def mark_running(job_id: str) -> None:
    _set(job_id, status="running")


def mark_progress(job_id: str, langs_done: list[str], total: int, fraction: float | None = None) -> None:
    """``fraction`` (§17.3) is overall progress 0–1; defaults to finished languages ÷ total."""
    if fraction is None:
        fraction = len(langs_done) / total if total else 1.0
    _set(job_id, progress=json.dumps(
        {"total": total, "done": len(langs_done), "langs_done": langs_done,
         "fraction": round(min(1.0, fraction), 4)}))


def mark_done(job_id: str, expires_at: float) -> None:
    _set(job_id, status="done", expires_at=expires_at)


def mark_failed(job_id: str, error: str) -> None:
    # Keep the TAIL: both Python tracebacks and the tikal subprocess dump put the
    # fatal line (exception type / "Error merging") at the end — the head is noise.
    _set(job_id, status="failed", error=error[-4000:])


def assign_path(job_id: str, path: str) -> None:
    """Point a job at its stored source file (after the upload is moved in)."""
    _set(job_id, path=path)


def delete(job_id: str) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))


# ---------------------------------------------------------------------------
# Admin queue management (Sprint 14, §12.8) + usage log (§12.9)
# ---------------------------------------------------------------------------

_ACTIVE = ("running", "queued", "scheduled")


def list_queue() -> list[dict[str, Any]]:
    """Running + waiting jobs in run order: running first, then priority DESC,
    then request time (the order the scheduler would pick them)."""
    with _connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM jobs WHERE status IN ({','.join('?' * len(_ACTIVE))}) "
            "ORDER BY CASE status WHEN 'running' THEN 0 ELSE 1 END, priority DESC, created_at ASC",
            _ACTIVE,
        ).fetchall()
    return [_row_to_job(r) for r in rows]


def list_failed() -> list[dict[str, Any]]:
    """Failed jobs (most recent first). Never swept (retention only clears `done`),
    so they persist with their error until the admin retries or deletes them."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM jobs WHERE status = 'failed' ORDER BY created_at DESC"
        ).fetchall()
    return [_row_to_job(r) for r in rows]


def retry(job_id: str) -> bool:
    """Re-queue a failed job to run again now. Returns False if the job isn't
    failed or its source file is gone (failed jobs aren't swept, so it normally
    persists). Reuses the same row → the result email/download path is unchanged."""
    job = get(job_id)
    if not job or job["status"] != "failed":
        return False
    if not job.get("path") or not Path(job["path"]).exists():
        return False
    progress = {"total": len(job["target_langs"]), "done": 0, "langs_done": []}
    _set(job_id, status="queued", run_at=time.time(), error="", progress=json.dumps(progress))
    logger.info(f"Admin re-queued failed job {job_id}")
    return True


def set_priority(job_id: str, on: bool) -> None:
    _set(job_id, priority=1 if on else 0)


def purge(job_id: str) -> None:
    """Delete a job's files + row (admin removes a pending/failed job)."""
    shutil.rmtree(_job_dir(job_id), ignore_errors=True)
    delete(job_id)


def move_in_queue(job_id: str, direction: str) -> None:
    """Reorder within the waiting list by swapping request time with the adjacent
    waiting job **in the same priority tier** (cross-tier moves are what
    prioritise/de-prioritise are for)."""
    waiting = [j for j in list_queue() if j["status"] in ("queued", "scheduled")]
    idx = next((i for i, j in enumerate(waiting) if j["id"] == job_id), None)
    if idx is None:
        return
    swap = idx - 1 if direction == "up" else idx + 1
    if swap < 0 or swap >= len(waiting):
        return
    a, b = waiting[idx], waiting[swap]
    if a["priority"] != b["priority"]:
        return
    _set(a["id"], created_at=b["created_at"])
    _set(b["id"], created_at=a["created_at"])


def record_usage(email: str, frontend_id: str, target_langs: list[str], now: float | None = None,
                 origin: str = "portal") -> None:
    """Log one completed job — counts only, never filenames/content (§8/§12.9)."""
    now = now if now is not None else time.time()
    day = datetime.fromtimestamp(now).strftime("%Y-%m-%d")
    with _connect() as conn:
        conn.execute(
            "INSERT INTO usage_log (email, frontend_id, langs, day, created_at, origin) VALUES (?,?,?,?,?,?)",
            (email.lower().strip(), frontend_id, json.dumps(target_langs), day, now, origin),
        )


def usage_summary() -> list[dict[str, Any]]:
    """Per-user usage: #documents, distinct languages, first/last day."""
    with _connect() as conn:
        rows = conn.execute("SELECT email, langs, day, origin FROM usage_log").fetchall()
    agg: dict[str, dict[str, Any]] = {}
    for r in rows:
        a = agg.setdefault(r["email"], {"email": r["email"], "origin": r["origin"], "documents": 0,
                                        "languages": set(), "first_day": r["day"], "last_day": r["day"]})
        a["documents"] += 1
        a["languages"].update(json.loads(r["langs"]))
        a["first_day"] = min(a["first_day"], r["day"])
        a["last_day"] = max(a["last_day"], r["day"])
    return [{"email": a["email"], "origin": a["origin"], "documents": a["documents"],
             "languages": sorted(a["languages"]), "first_day": a["first_day"], "last_day": a["last_day"]}
            for a in sorted(agg.values(), key=lambda x: x["email"])]


# ---------------------------------------------------------------------------
# Processing + retention + scheduler loop
# ---------------------------------------------------------------------------


def _job_dir(job_id: str) -> Path:
    return DOCUMENTS_DIR / job_id


async def process_job(job: dict[str, Any]) -> None:
    """Run one job end to end: translate every target language, email the
    result, set the retention deadline. Marks ``failed`` on any error."""
    from src.services.document_translator import extract, translate, recompose, progress_hook

    job_id = job["id"]
    mark_running(job_id)
    from src.services import llm_usage
    usage_token = llm_usage.current_job.set(job_id)  # attributes LLM usage to this job
    try:
        out_dir = _job_dir(job_id)
        ir = extract(job["path"], job.get("options") or {})
        src = Path(job["path"])
        langs_done: list[str] = []
        outputs: list[Path] = []
        n_langs = len(job["target_langs"])
        for lang in job["target_langs"]:
            base = len(langs_done)

            def hook(done: int, total: int, base: int = base) -> None:
                mark_progress(job_id, langs_done, n_langs, (base + (done / total if total else 1.0)) / n_langs)
            hook_token = progress_hook.set(hook)
            try:
                await translate(ir, job["source_lang"], [lang], job["glossary"],
                                connection_id=(job.get("options") or {}).get("connection_id") or None,
                                frontend_id=job.get("frontend_id", ""), options=job.get("options") or {})
            finally:
                progress_hook.reset(hook_token)
            out_path = out_dir / f"{src.stem}.{lang}{src.suffix}"
            recompose(ir, lang, str(out_path))
            outputs.append(out_path)
            langs_done.append(lang)
            mark_progress(job_id, langs_done, len(job["target_langs"]))

        from src.api.v1.admin.settings import retention_hours
        expires_at = time.time() + retention_hours() * 3600
        mark_done(job_id, expires_at)
        record_usage(job["owner_email"], job.get("frontend_id", ""), job["target_langs"],
                     origin=job.get("origin", "portal"))  # §12.9 counts only
        logger.info(f"Job {job_id} translated — {len(outputs)} language(s), expires in {retention_hours()}h")
        for slot, c in llm_usage.job_summary(job_id).items():
            logger.info(f"Job {job_id} LLM usage ({slot}): calls={c['calls']} prompt={c['prompt_tokens']} "
                        f"cached={c['cached_tokens']} completion={c['completion_tokens']} "
                        f"reasoning={c['reasoning_tokens']} hit_rate={c['hit_rate']}")
    except Exception as e:
        logger.error(f"Job {job_id} failed: {e}")
        mark_failed(job_id, str(e))
        return
    finally:
        llm_usage.current_job.reset(usage_token)

    if job.get("origin") == "api":  # §16.4: machine jobs are fetched via /api/v1, never emailed
        return

    # Notify separately: the translation already succeeded and is downloadable —
    # a mail/link failure must NOT flip the job to `failed`, but must be loud.
    try:
        from src.services.smtp_service import send_translation_ready
        from src.services.user_tokens import mint_download_token
        from src.services.frontend_registry import registry
        fid = job.get("frontend_id", "")
        fe = registry.get(fid) or {}
        # The public portal address (SPEC §14.3); `url` is the backend-surface address
        # once a frontend is on the two-port image, so it is only the fallback.
        base = (fe.get("public_url") or fe.get("url") or "").rstrip("/")
        from src.services.frontend_client import auth_mode, MODE_LEGACY
        if fe and not fe.get("public_url") and auth_mode(fe) != MODE_LEGACY:
            logger.warning(f"Job {job_id}: frontend {fid} has no public address — the emailed link points "
                           f"to its backend address. Set it in Admin → Frontends → Security.")
        token = mint_download_token(job["owner_email"], fid, job["client_ref"], expires_at)
        download_url = f"{base}/d/{token}"
        sent = await send_translation_ready(job["owner_email"], download_url)
        if sent:
            logger.info(f"Job {job_id}: result email sent to {job['owner_email']} (link {base}/d/…)")
        else:
            logger.error(f"Job {job_id}: result email NOT sent (SMTP unconfigured or send failed) — "
                         f"result is still downloadable in-app")
    except Exception as e:
        logger.error(f"Job {job_id}: notify step failed (translation OK, result downloadable): {e}")


def sweep_expired(now: float | None = None) -> int:
    """Hard-delete files + row for every expired job. Returns count swept."""
    swept = 0
    for job in list_expired(now):
        shutil.rmtree(_job_dir(job["id"]), ignore_errors=True)  # actually delete files (lesson #15)
        delete(job["id"])
        swept += 1
    if swept:
        logger.info(f"Retention sweep deleted {swept} expired job(s)")
    return swept


_running: dict[str, tuple[asyncio.Task, str]] = {}   # job id → (task, connection id)


def job_connection_id(job: dict[str, Any]) -> str:
    """The connection a job will call: its per-request override, else the frontend's slot."""
    cid = (job.get("options") or {}).get("connection_id")
    if cid:
        return cid
    from src.api.v1.admin.llm import get_llm_settings
    return get_llm_settings(job.get("frontend_id", "")).get("translation_connection") or ""


async def _run(job: dict[str, Any]) -> None:
    try:
        await process_job(job)
    except asyncio.CancelledError:
        pass  # cancel() already recorded the outcome
    except Exception:
        logger.exception(f"Job {job['id']} crashed")
    finally:
        _running.pop(job["id"], None)
        dispatch()  # a slot freed up


def dispatch(now: float | None = None) -> int:
    """Start every eligible waiting job that fits its connection's capacity (§17.1):
    1 unless the connection has ``parallel`` on, then ``max_concurrent``. Returns how
    many were started. Must run inside the event loop."""
    from src.services.connection_registry import connections, capacity
    load: dict[str, int] = {}
    for _, cid in _running.values():
        load[cid] = load.get(cid, 0) + 1
    started = 0
    for job in eligible_jobs(now):
        if job["id"] in _running:
            continue
        cid = job_connection_id(job)
        if load.get(cid, 0) >= capacity(connections.get(cid)):
            continue  # that connection is full; jobs on others may still start
        load[cid] = load.get(cid, 0) + 1
        mark_running(job["id"])
        _running[job["id"]] = (asyncio.get_running_loop().create_task(_run(job)), cid)
        started += 1
    return started


def cancel(job_id: str) -> bool:
    """Cancel a waiting or running job (§17.2). False if it is already finished/unknown.
    API jobs become ``cancelled`` and lose their files; portal jobs are recorded as
    ``failed`` (the sidecar contract has no cancelled state) and keep their source so
    the admin can relaunch them."""
    job = get(job_id)
    if not job or job["status"] not in _ACTIVE:
        return False
    entry = _running.pop(job_id, None)
    if entry:
        entry[0].cancel()
    if job["origin"] == "api":
        shutil.rmtree(_job_dir(job_id), ignore_errors=True)
        from src.api.v1.admin.settings import retention_hours
        _set(job_id, status="cancelled", error="", expires_at=time.time() + retention_hours() * 3600)
    else:
        mark_failed(job_id, "Cancelled by the admin")
    logger.info(f"Job {job_id} cancelled ({'was running' if entry else 'was waiting'})")
    try:
        dispatch()
    except RuntimeError:  # no event loop (sync caller) — the scheduler tick will pick it up
        pass
    return True


async def scheduler_loop(interval: int | None = None) -> None:
    """Background loop: dispatch eligible jobs, then sweep expired ones, every interval
    (job completion also dispatches immediately — this tick is the safety net)."""
    interval = interval or config.job_scheduler_interval_seconds
    logger.info(f"Job scheduler loop started (interval={interval}s)")
    while True:
        try:
            dispatch()
            sweep_expired()
        except Exception as e:  # never let the loop die
            logger.error(f"Scheduler loop iteration failed: {e}")
        await asyncio.sleep(interval)
