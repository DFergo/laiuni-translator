"""Connection registry — provider connections for the LLM slots (Sprint 19).

Replaces the hardcoded Ollama/LM Studio wiring with a registry of provider
connections. A connection record:

    {id, type: "openai"|"anthropic"|"ollama", base_url, api_key,
     prefix_id, model_ids[] (allowlist), enable}

Persisted at DATA_DIR/config/connections.json (REFACTOR §0.6 layout starts
here). Atomic writes (lesson #5). LAIUNI ships with an **empty** registry — no
providers are preregistered; the operator registers what they need at boot via
the admin API (lesson #8).
"""

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger("backend.connections")

from src.core.paths import CONFIG_DIR, CONNECTIONS as CONNECTIONS_FILE

VALID_TYPES = {"openai", "anthropic", "ollama"}


def _clamp_concurrency(value: Any) -> int:
    try:
        return max(1, min(32, int(value)))
    except (TypeError, ValueError):
        return 4


def capacity(conn: dict[str, Any] | None) -> int:
    """How many jobs may run at once on a connection (§17.1)."""
    return _clamp_concurrency((conn or {}).get("max_concurrent")) if (conn or {}).get("parallel") else 1


def _seed_connections() -> list[dict[str, Any]]:
    """No preregistered connections — LAIUNI starts with an empty registry.

    The operator registers the connection(s) they need at boot via the admin
    API (``POST /admin/llm/connections``). Nothing provider-specific is baked
    in (lesson #8).
    """
    return []


class ConnectionRegistry:
    """Persistent registry of provider connections. Atomic JSON writes (lesson #5)."""

    def __init__(self):
        self._connections: list[dict[str, Any]] = []
        self._load()

    def _load(self):
        if CONNECTIONS_FILE.exists():
            try:
                data = json.loads(CONNECTIONS_FILE.read_text())
                self._connections = data.get("connections", [])
                logger.info(f"Loaded {len(self._connections)} connections")
                return
            except Exception as e:
                logger.error(f"Failed to load connections, reseeding: {e}")
        # First run (or unreadable) → seed from deployment config
        self._connections = _seed_connections()
        self._save()
        logger.info(f"Seeded {len(self._connections)} default connections")

    def _save(self):
        """Atomic write: write to temp file, then rename (lesson #5)."""
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        tmp = CONNECTIONS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps({"connections": self._connections}, indent=2))
        tmp.rename(CONNECTIONS_FILE)

    # --- Queries ---

    def all(self) -> list[dict[str, Any]]:
        return list(self._connections)

    def enabled(self) -> list[dict[str, Any]]:
        return [c for c in self._connections if c.get("enable", True)]

    def get(self, connection_id: str) -> dict[str, Any] | None:
        for c in self._connections:
            if c["id"] == connection_id:
                return c
        return None

    # --- Mutations ---

    def add(self, conn: dict[str, Any]) -> dict[str, Any]:
        record = self._normalise(conn)
        if self.get(record["id"]):
            raise ValueError(f"Connection id already exists: {record['id']}")
        self._connections.append(record)
        self._save()
        logger.info(f"Added connection {record['id']} ({record['type']})")
        return record

    def update(self, connection_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        existing = self.get(connection_id)
        if not existing:
            raise ValueError(f"Connection not found: {connection_id}")
        for key in ("type", "base_url", "api_key", "prefix_id", "model_ids", "enable",
                    "provider", "prompt_cache_key", "routing", "parallel", "max_concurrent"):
            if key in patch and patch[key] is not None:
                existing[key] = patch[key]
        existing["max_concurrent"] = _clamp_concurrency(existing.get("max_concurrent"))
        if existing["type"] not in VALID_TYPES:
            raise ValueError(f"Invalid connection type: {existing['type']}")
        self._save()
        logger.info(f"Updated connection {connection_id}")
        return existing

    def delete(self, connection_id: str):
        before = len(self._connections)
        self._connections = [c for c in self._connections if c["id"] != connection_id]
        if len(self._connections) != before:
            self._save()
            logger.info(f"Deleted connection {connection_id}")

    def _normalise(self, conn: dict[str, Any]) -> dict[str, Any]:
        conn_type = conn.get("type")
        if conn_type not in VALID_TYPES:
            raise ValueError(f"Invalid connection type: {conn_type}")
        conn_id = (conn.get("id") or "").strip()
        if not conn_id:
            raise ValueError("Connection id is required")
        return {
            "id": conn_id,
            "type": conn_type,
            "base_url": (conn.get("base_url") or "").rstrip("/"),
            "api_key": conn.get("api_key") or "",
            "prefix_id": conn.get("prefix_id") or "",
            "model_ids": conn.get("model_ids") or [],
            "enable": conn.get("enable", True),
            # Sprint 21 — optional provider hints (see llm_capabilities.py):
            # provider: force the provider profile ("" = infer from base_url);
            # prompt_cache_key: send a per-job cache key (a hash) to providers that use it;
            # routing: OpenRouter `provider` object (e.g. {"order": [...]}).
            "provider": conn.get("provider") or "",
            "prompt_cache_key": bool(conn.get("prompt_cache_key", False)),
            "routing": conn.get("routing") or {},
            # Sprint 23 (§17.1): several jobs at once on this connection (commercial
            # inference); off = one job at a time, the historical behaviour.
            "parallel": bool(conn.get("parallel", False)),
            "max_concurrent": _clamp_concurrency(conn.get("max_concurrent")),
        }


# Singleton
connections = ConnectionRegistry()
