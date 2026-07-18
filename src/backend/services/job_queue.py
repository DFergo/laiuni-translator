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
import json
import logging
import secrets
import shutil
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

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
                priority     INTEGER NOT NULL DEFAULT 0   -- §12.7 privilege: 1 = jump the queue
            )
            """
        )
        # Additive migrations for older DBs.
        cols = {r[1] for r in conn.execute("PRAGMA table_info(jobs)")}
        if "client_ref" not in cols:  # Sprint 5
            conn.execute("ALTER TABLE jobs ADD COLUMN client_ref TEXT NOT NULL DEFAULT ''")
        if "priority" not in cols:    # Sprint 13
            conn.execute("ALTER TABLE jobs ADD COLUMN priority INTEGER NOT NULL DEFAULT 0")


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
    return job


# ---------------------------------------------------------------------------
# Estimate + scheduling helpers (pure — unit-testable)
# ---------------------------------------------------------------------------


def estimate_seconds(chars: int, n_langs: int, throughput: float | None = None) -> int:
    """Duration estimate = chars ÷ throughput × n_langs (SPEC §3.2)."""
    rate = throughput or config.translation_throughput_chars_per_s or 10.0
    return int(chars / rate * max(1, n_langs))


def compute_run_at(mode: str, now: datetime, hour: int, scheduling_enabled: bool) -> datetime:
    """When a job should run.

    ``immediate`` → now. ``scheduled`` → the next local time at ``hour``:00 that
    is ≥ now (today if now is before it, else tomorrow). Scheduling disabled →
    now (SPEC §3.2, configurable/disableable per deploy).
    """
    if mode == "immediate" or not scheduling_enabled:
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
    chars: int | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Insert a new job. Computes ``run_at`` (scheduled → the next window start,
    §12.6), the duration estimate, and the initial status (``queued`` if due now,
    else ``scheduled``). ``priority`` (§12.7) lets the job jump the queue."""
    now = now or datetime.now()
    from src.api.v1.admin.settings import scheduling
    start_hour = scheduling()["start_hour"]
    run_at_dt = compute_run_at(mode, now, start_hour, config.scheduling_enabled)
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
                   estimate_s, error, created_at, expires_at, priority)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (job_id, owner_email.lower().strip(), frontend_id, client_ref, source_lang,
             json.dumps(target_langs), fmt, path, glossary, mode,
             run_at_dt.timestamp(), status, json.dumps(progress), estimate,
             "", now.timestamp(), None, 1 if priority else 0),
        )
    logger.info(f"Enqueued job {job_id} status={status} run_at={run_at_dt.isoformat()} "
                f"priority={int(priority)} langs={len(target_langs)} estimate={estimate}s")
    return get(job_id)


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


def next_job(now: float | None = None) -> dict[str, Any] | None:
    """The single next job to run (§12.6 sequential single-flight), or None.

    Eligibility: a waiting job whose ``run_at`` has passed. **Immediate** jobs are
    eligible anytime; **scheduled** jobs only while ``now`` is inside the nightly
    window (unless scheduling is disabled deploy-wide, which makes everything
    immediate). Ordered **priority first** (§12.7), then by request time (FIFO).
    Jobs left when the window closes stay waiting → picked up next window
    (carry-over)."""
    now = now if now is not None else time.time()
    now_dt = datetime.fromtimestamp(now)
    from src.api.v1.admin.settings import scheduling
    sched = scheduling()
    in_window = (not config.scheduling_enabled) or _in_window(
        now_dt, sched["start_hour"], sched["duration_hours"])
    modes = ("immediate", "scheduled") if in_window else ("immediate",)
    with _connect() as conn:
        row = conn.execute(
            f"SELECT * FROM jobs WHERE status IN ({','.join('?' * len(_WAITING))}) "
            f"AND run_at <= ? AND mode IN ({','.join('?' * len(modes))}) "
            f"ORDER BY priority DESC, created_at ASC LIMIT 1",
            (*_WAITING, now, *modes),
        ).fetchone()
    return _row_to_job(row) if row else None


def list_expired(now: float | None = None) -> list[dict[str, Any]]:
    """Done jobs whose retention window has passed."""
    now = now if now is not None else time.time()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM jobs WHERE status = 'done' AND expires_at IS NOT NULL "
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


def mark_progress(job_id: str, langs_done: list[str], total: int) -> None:
    _set(job_id, progress=json.dumps(
        {"total": total, "done": len(langs_done), "langs_done": langs_done}))


def mark_done(job_id: str, expires_at: float) -> None:
    _set(job_id, status="done", expires_at=expires_at)


def mark_failed(job_id: str, error: str) -> None:
    _set(job_id, status="failed", error=error[:500])


def assign_path(job_id: str, path: str) -> None:
    """Point a job at its stored source file (after the upload is moved in)."""
    _set(job_id, path=path)


def delete(job_id: str) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))


# ---------------------------------------------------------------------------
# Processing + retention + scheduler loop
# ---------------------------------------------------------------------------


def _job_dir(job_id: str) -> Path:
    return DOCUMENTS_DIR / job_id


async def process_job(job: dict[str, Any]) -> None:
    """Run one job end to end: translate every target language, email the
    result, set the retention deadline. Marks ``failed`` on any error."""
    from src.services.document_translator import extract, translate, recompose

    job_id = job["id"]
    mark_running(job_id)
    try:
        out_dir = _job_dir(job_id)
        ir = extract(job["path"])
        src = Path(job["path"])
        langs_done: list[str] = []
        outputs: list[Path] = []
        for lang in job["target_langs"]:
            await translate(ir, job["source_lang"], [lang], job["glossary"],
                            frontend_id=job.get("frontend_id", ""))
            out_path = out_dir / f"{src.stem}.{lang}{src.suffix}"
            recompose(ir, lang, str(out_path))
            outputs.append(out_path)
            langs_done.append(lang)
            mark_progress(job_id, langs_done, len(job["target_langs"]))

        from src.api.v1.admin.settings import retention_hours
        expires_at = time.time() + retention_hours() * 3600
        mark_done(job_id, expires_at)

        # Result email carries a signed, single-use, retention-bounded download
        # link on the public frontend domain — not attachments (SPEC §12).
        from src.services.smtp_service import send_translation_ready
        from src.services.user_tokens import mint_download_token
        from src.services.frontend_registry import registry
        fid = job.get("frontend_id", "")
        fe = registry.get(fid) or {}
        token = mint_download_token(job["owner_email"], fid, job["client_ref"], expires_at)
        download_url = f"{fe.get('url', '').rstrip('/')}/d/{token}"
        await send_translation_ready(job["owner_email"], download_url)
        logger.info(f"Job {job_id} done — {len(outputs)} translation(s), emailed download link, "
                    f"expires in {retention_hours()}h")
    except Exception as e:
        logger.error(f"Job {job_id} failed: {e}")
        mark_failed(job_id, str(e))


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


async def run_window(max_jobs: int = 1000) -> int:
    """Process eligible jobs **one at a time** (§12.6 sequential single-flight):
    pick the next job (priority-ordered, window-bounded), run it to completion,
    repeat until none is eligible. Re-evaluated each iteration, so when the window
    closes the remaining scheduled jobs simply stop being picked and carry over to
    the next window. ``max_jobs`` is a safety bound per tick. Returns count run."""
    count = 0
    while count < max_jobs:
        job = next_job()
        if not job:
            break
        await process_job(job)
        count += 1
    return count


async def scheduler_loop(interval: int | None = None) -> None:
    """Background loop: run the window queue, then sweep expired ones, every interval."""
    interval = interval or config.job_scheduler_interval_seconds
    logger.info(f"Job scheduler loop started (interval={interval}s)")
    while True:
        try:
            await run_window()
            sweep_expired()
        except Exception as e:  # never let the loop die
            logger.error(f"Scheduler loop iteration failed: {e}")
        await asyncio.sleep(interval)
