"""Admin settings — runtime, admin-editable global config (Sprint 12, SPEC §12.4).

Distinct from `deployment_backend.json` (deploy-time) and `llm_settings.json`
(the engine). This is what the admin edits in the **Settings** tab: retention,
the default app language, and (Sprint 13) the scheduling-window defaults.
Persisted at `config/settings.json` with atomic writes (lesson #5).
"""

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from src.api.v1.admin.auth import require_admin
from src.core.config import config
from src.core.paths import CONFIG_DIR

logger = logging.getLogger("backend.admin.settings")

router = APIRouter(prefix="/admin/settings", tags=["admin-settings"])

_SETTINGS_PATH = CONFIG_DIR / "settings.json"


def _defaults() -> dict[str, Any]:
    return {
        "retention_hours": config.retention_hours,   # hard-delete window (was hardcoded 48h)
        "app_language": "en",                         # default portal UI language (§12.2)
        # Sprint 13 adds: scheduling window (start hour, duration), immediate/scheduled default.
    }


def load_settings() -> dict[str, Any]:
    data = _defaults()
    if _SETTINGS_PATH.exists():
        try:
            data.update({k: v for k, v in json.loads(_SETTINGS_PATH.read_text()).items() if v is not None})
        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"Malformed settings.json rejected, using defaults: {e}")
    return data


def save_settings(settings: dict[str, Any]) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _SETTINGS_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(settings, indent=2))
    tmp.rename(_SETTINGS_PATH)


def get_setting(key: str, default: Any = None) -> Any:
    return load_settings().get(key, default)


def retention_hours() -> int:
    return int(get_setting("retention_hours", config.retention_hours))


class SettingsRequest(BaseModel):
    retention_hours: int | None = None
    app_language: str | None = None


@router.get("")
async def get_settings(_: dict = Depends(require_admin)):
    return load_settings()


@router.put("")
async def update_settings(req: SettingsRequest, _: dict = Depends(require_admin)):
    current = load_settings()
    current.update(req.model_dump(exclude_unset=True, exclude_none=True))
    save_settings(current)
    logger.info(f"Admin settings updated: {list(req.model_dump(exclude_unset=True).keys())}")
    return current
