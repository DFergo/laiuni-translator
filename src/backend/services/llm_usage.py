"""Token and prompt-cache usage per translation job and per slot (Sprint 21).

Every LLM call reports prompt, cached, completion and reasoning tokens when the
provider returns them (see the adapters in llm_provider.py). Two views:

  - per job:  documents/{job_id}/llm_usage.json  → {slot: counters}  (deleted
              with the job by the normal retention)
  - global:   DATA_DIR/llm_usage.json             → {"slot|connection|model": counters}

The running job is carried in a ContextVar set by job_queue.process_job, so the
translation loop does not need to pass it through every call. The admin shows
the global table with the cache hit rate (cached / prompt).
"""

import contextvars
import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any

from src.core.paths import DATA_DIR, DOCUMENTS_DIR

logger = logging.getLogger("backend.llm_usage")

current_job: contextvars.ContextVar[str | None] = contextvars.ContextVar("current_job", default=None)

_GLOBAL_FILE = DATA_DIR / "llm_usage.json"
_FIELDS = ("prompt_tokens", "cached_tokens", "completion_tokens", "reasoning_tokens")

_global: dict[str, dict[str, Any]] | None = None


def cache_key() -> str | None:
    """Provider prompt-cache key for the running job (a hash, never the job id)."""
    job = current_job.get()
    if not job:
        return None
    return hashlib.sha256(f"laiuni-cache:{job}".encode()).hexdigest()[:32]


def _empty() -> dict[str, Any]:
    return {"calls": 0, "calls_with_usage": 0, **{f: 0 for f in _FIELDS}}


def _add(counters: dict[str, Any], usage: dict[str, int]):
    counters["calls"] = counters.get("calls", 0) + 1
    if usage:
        counters["calls_with_usage"] = counters.get("calls_with_usage", 0) + 1
    for f in _FIELDS:
        counters[f] = counters.get(f, 0) + int(usage.get(f, 0) or 0)
    counters["updated_at"] = time.time()


def _write(path: Path, data: Any):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1))
    tmp.rename(path)


def _load_global() -> dict[str, dict[str, Any]]:
    global _global
    if _global is None:
        try:
            _global = json.loads(_GLOBAL_FILE.read_text()) if _GLOBAL_FILE.exists() else {}
        except (OSError, json.JSONDecodeError) as e:
            logger.warning(f"Unreadable {_GLOBAL_FILE.name}, starting fresh: {e}")
            _global = {}
    return _global


def record(slot: str, connection_id: str, model: str, usage: dict[str, int]):
    """Add one call's usage. Never raises (usage must not break a translation)."""
    try:
        g = _load_global()
        _add(g.setdefault(f"{slot}|{connection_id}|{model}", _empty()), usage)
        _write(_GLOBAL_FILE, g)
        job = current_job.get()
        if job:
            path = DOCUMENTS_DIR / job / "llm_usage.json"
            data = json.loads(path.read_text()) if path.exists() else {}
            _add(data.setdefault(slot, _empty()), usage)
            _write(path, data)
    except Exception as e:
        logger.warning(f"Could not record LLM usage: {e}")


def hit_rate(c: dict[str, Any]) -> float | None:
    return round(c["cached_tokens"] / c["prompt_tokens"], 4) if c.get("prompt_tokens") else None


def global_summary() -> list[dict[str, Any]]:
    rows = []
    for key, c in sorted(_load_global().items()):
        slot, connection_id, model = (key.split("|", 2) + ["", ""])[:3]
        rows.append({"slot": slot, "connection": connection_id, "model": model,
                     **{k: c.get(k, 0) for k in ("calls", "calls_with_usage", *_FIELDS)},
                     "hit_rate": hit_rate(c), "updated_at": c.get("updated_at")})
    return rows


def job_summary(job_id: str) -> dict[str, Any]:
    path = DOCUMENTS_DIR / job_id / "llm_usage.json"
    try:
        data = json.loads(path.read_text()) if path.exists() else {}
    except (OSError, json.JSONDecodeError):
        data = {}
    return {slot: {**c, "hit_rate": hit_rate(c)} for slot, c in data.items()}


def reset_global():
    global _global
    _global = {}
    _write(_GLOBAL_FILE, _global)
