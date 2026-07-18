"""Connection registry — provider connections for the LLM slots (Sprint 19).

Replaces the hardcoded Ollama/LM Studio wiring with a registry of provider
connections. A connection record:

    {id, type: "openai"|"anthropic"|"ollama", base_url, api_key,
     prefix_id, model_ids[] (allowlist), enable}

Persisted at DATA_DIR/config/connections.json (REFACTOR §0.6 layout starts
here). Atomic writes (lesson #5). On first load the registry seeds itself
from deployment_backend.json so the existing Ollama/LM Studio production keeps
working unchanged.
"""

import json
import logging
import os
from pathlib import Path
from typing import Any

from src.core.config import config

logger = logging.getLogger("backend.connections")

from src.core.paths import CONFIG_DIR, CONNECTIONS as CONNECTIONS_FILE

VALID_TYPES = {"openai", "anthropic", "ollama"}


def _seed_connections() -> list[dict[str, Any]]:
    """Build the default connections from the deployment config.

    lmstudio-default is an OpenAI-compatible connection (LM Studio exposes the
    OpenAI API); ollama-default is a native Ollama connection. Both enabled so
    a fresh install keeps the current production wiring.
    """
    return [
        {
            "id": "ollama-default",
            "type": "ollama",
            "base_url": config.ollama_endpoint,
            "api_key": "",
            "prefix_id": "",
            "model_ids": [],
            "enable": True,
        },
        {
            "id": "lmstudio-default",
            "type": "openai",
            "base_url": config.lm_studio_endpoint,
            "api_key": "",
            "prefix_id": "",
            "model_ids": [],
            "enable": True,
        },
    ]


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
        for key in ("type", "base_url", "api_key", "prefix_id", "model_ids", "enable"):
            if key in patch and patch[key] is not None:
                existing[key] = patch[key]
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
        }


# Singleton
connections = ConnectionRegistry()
