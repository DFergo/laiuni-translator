import json
import logging
import os
import secrets
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("backend.registry")

from src.core.paths import DATA_DIR, FRONTENDS, CAMPAIGNS_DIR, DELETED_DIR, CONFIG_DIR
REGISTRY_FILE = FRONTENDS  # Sprint 24: config/ layout


# ---------------------------------------------------------------------------
# Per-frontend config (Sprint 21) — schema served via /internal/config.
# Sprint 21 consumes `configured`, `profiles`, `auth_required`; the rest is
# schema the Sprint 22 panel will drive.
# ---------------------------------------------------------------------------


def default_config() -> dict[str, Any]:
    return {
        "configured": False,
        "profiles": [],
        "auth_required": False,
        "auth": {},                                    # Sprint 22: per-profile auth
        "languages": [],                               # empty = all languages
        "modes": {},                                   # Sprint 22: active modes per profile
        "display_names": {"profiles": {}, "modes": {}},  # Sprint 22
        "session_resume_window_hours": 48,
        "disclaimer_enabled": True,
        "data_protection_email": "",
    }


def _config_from_type(frontend_type: str) -> dict[str, Any]:
    """Derive a config object from a legacy frontend_type (migration, D4)."""
    cfg = default_config()
    cfg["configured"] = True
    if frontend_type == "organizer":
        cfg["profiles"] = ["organizer", "officer"]
        cfg["auth_required"] = True
        cfg["session_resume_window_hours"] = 120
    else:  # worker (default)
        cfg["profiles"] = ["worker", "representative"]
        cfg["auth_required"] = False
        cfg["session_resume_window_hours"] = 48
    # Sprint 22: seed per-profile auth from the frontend-level flag
    cfg["auth"] = {p: cfg["auth_required"] for p in cfg["profiles"]}
    return cfg


def _config_path(fid: str) -> Path:
    return CAMPAIGNS_DIR / fid / "frontend_config.json"


def load_config(fid: str) -> dict[str, Any]:
    path = _config_path(fid)
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception as e:
            logger.warning(f"Failed to load frontend_config for {fid}: {e}")
    return default_config()


def save_config(fid: str, config: dict[str, Any]):
    """Atomic write of a frontend's config (lesson #5)."""
    campaign_dir = CAMPAIGNS_DIR / fid
    campaign_dir.mkdir(parents=True, exist_ok=True)
    path = campaign_dir / "frontend_config.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(config, indent=2))
    tmp.rename(path)


class FrontendRegistry:
    """Persistent registry of frontend instances. Atomic JSON writes (lesson #5)."""

    def __init__(self):
        self._frontends: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self):
        if REGISTRY_FILE.exists():
            try:
                self._frontends = json.loads(REGISTRY_FILE.read_text())
                logger.info(f"Loaded {len(self._frontends)} frontends from registry")
            except Exception as e:
                logger.error(f"Failed to load registry: {e}")
                self._frontends = {}
        self._migrate_frontend_type()

    def _migrate_frontend_type(self):
        """Sprint 21: convert legacy `frontend_type` entries to the config model.

        Idempotent: only migrates entries that still carry `frontend_type`.
        Derives a config (if none exists yet) and drops the key.
        """
        changed = False
        for fid, f in self._frontends.items():
            if "frontend_type" in f:
                ftype = f.pop("frontend_type")
                if not _config_path(fid).exists():
                    save_config(fid, _config_from_type(ftype))
                    logger.info(f"Migrated frontend {fid} ({ftype}) to config schema")
                changed = True
        if changed:
            self._save()

    def _save(self):
        """Atomic write: write to temp file, then rename (lesson #5)."""
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        tmp = REGISTRY_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._frontends, indent=2))
        tmp.rename(REGISTRY_FILE)

    def register(self, url: str, name: str = "") -> dict[str, Any]:
        url = url.rstrip("/")
        # Check if URL already registered
        for fid, f in self._frontends.items():
            if f["url"] == url:
                return f

        fid = secrets.token_hex(4)
        now = datetime.now(timezone.utc).isoformat()
        frontend = {
            "id": fid,
            "url": url,
            "name": name or f"frontend-{fid[:4]}",
            "enabled": True,
            "status": "unknown",
            "last_seen": None,
            "created_at": now,
        }
        self._frontends[fid] = frontend
        self._save()
        # A freshly registered frontend starts unconfigured (Sprint 21)
        save_config(fid, default_config())
        logger.info(f"Registered frontend {fid}: {url}")
        return frontend

    def remove(self, fid: str) -> bool:
        """Soft-delete: archive the frontend's config to deleted/{fid}/ (recoverable)."""
        if fid not in self._frontends:
            return False
        dst = DELETED_DIR / fid
        if dst.exists():
            shutil.rmtree(dst)
        src = CAMPAIGNS_DIR / fid
        if src.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
        else:
            dst.mkdir(parents=True, exist_ok=True)
        entry = self._frontends.pop(fid)
        (dst / "registry_entry.json").write_text(json.dumps(entry, indent=2))
        self._save()
        logger.info(f"Soft-deleted frontend {fid} → deleted/{fid}/")
        return True

    def restore(self, fid: str) -> dict[str, Any] | None:
        """Restore a soft-deleted frontend from deleted/{fid}/."""
        ddir = DELETED_DIR / fid
        entry_file = ddir / "registry_entry.json"
        if not entry_file.exists():
            return None
        entry = json.loads(entry_file.read_text())
        dst = CAMPAIGNS_DIR / fid
        dst.mkdir(parents=True, exist_ok=True)
        for item in ddir.iterdir():
            if item.name == "registry_entry.json":
                continue
            shutil.move(str(item), str(dst / item.name))
        self._frontends[fid] = entry
        self._save()
        shutil.rmtree(ddir, ignore_errors=True)
        logger.info(f"Restored frontend {fid} from deleted/")
        return entry

    def list_deleted(self) -> list[dict[str, Any]]:
        """List soft-deleted frontends (from their archived registry entries)."""
        if not DELETED_DIR.exists():
            return []
        out: list[dict[str, Any]] = []
        for d in DELETED_DIR.iterdir():
            entry_file = d / "registry_entry.json"
            if entry_file.exists():
                try:
                    out.append(json.loads(entry_file.read_text()))
                except Exception:
                    pass
        return out

    def update(self, fid: str, **kwargs: Any) -> dict[str, Any] | None:
        if fid not in self._frontends:
            return None
        self._frontends[fid].update(kwargs)
        self._save()
        return self._frontends[fid]

    def set_status(self, fid: str, status: str):
        if fid in self._frontends:
            self._frontends[fid]["status"] = status
            if status == "online":
                self._frontends[fid]["last_seen"] = datetime.now(timezone.utc).isoformat()
            # Don't save on every status update — it's runtime state

    def get(self, fid: str) -> dict[str, Any] | None:
        return self._frontends.get(fid)

    def list_all(self) -> list[dict[str, Any]]:
        return list(self._frontends.values())

    def list_enabled(self) -> list[dict[str, Any]]:
        return [f for f in self._frontends.values() if f["enabled"]]


registry = FrontendRegistry()
