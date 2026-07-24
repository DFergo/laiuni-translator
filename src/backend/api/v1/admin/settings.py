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
        # Scheduling window (Sprint 13, §12.6): a nightly window with a start hour
        # and a duration; scheduled jobs run inside it, one at a time, and carry
        # over to the next night if the window closes first.
        "schedule_window_start_hour": config.schedule_default_hour,  # local hour the window opens
        "schedule_window_duration_hours": 3,          # how long the window stays open
        # One exclusive choice that drives exactly the buttons the user sees —
        # no silent policy. "scheduled" = every job runs in the window;
        # "immediate" = every job runs now; "both" = the user picks.
        "schedule_mode": "both",
        # Max documents per multiple-translation submission (§13.4), cap 10.
        "batch_max": 5,
        # Extraction/recomposition engine for Office formats (ADR-021):
        #   python      — in-process python-docx/pptx/pandoc (default, unchanged)
        #   okapi       — Okapi/Tikal, allowWordStyleOptimisation ON  (Okapi default)
        #   okapi_noopt — Okapi/Tikal, allowWordStyleOptimisation OFF (keeps styles)
        # .txt/.md always use the python path regardless of this setting.
        "format_engine": "python",
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


_FORMAT_ENGINES = ("python", "okapi", "okapi_noopt")


def format_engine() -> str:
    """Effective Office extract/recompose engine (ADR-021), validated."""
    v = get_setting("format_engine", "python")
    return v if v in _FORMAT_ENGINES else "python"


_SCHEDULE_MODES = ("scheduled", "immediate", "both")


def scheduling(frontend_id: str = "") -> dict[str, Any]:
    """The effective scheduling settings (Sprint 13, §12.6), resolved per-frontend:
    a frontend's config may override any key; anything it leaves unset falls back
    to the global admin Settings. ``mode`` is one of scheduled | immediate | both
    and drives exactly the buttons the portal shows."""
    s = load_settings()
    fe: dict[str, Any] = {}
    if frontend_id:
        try:
            from src.services.frontend_registry import load_config
            fe = load_config(frontend_id) or {}
        except Exception:
            fe = {}

    def pick(key: str, default: Any) -> Any:
        v = fe.get(key)
        return v if v is not None else s.get(key, default)

    mode = pick("schedule_mode", "both")
    if mode not in _SCHEDULE_MODES:
        mode = "both"
    return {
        "start_hour": int(pick("schedule_window_start_hour", config.schedule_default_hour)),
        "duration_hours": int(pick("schedule_window_duration_hours", 3)),
        "mode": mode,
        "batch_max": max(1, min(10, int(pick("batch_max", 5)))),
    }


class SettingsRequest(BaseModel):
    retention_hours: int | None = None
    app_language: str | None = None
    schedule_window_start_hour: int | None = None
    schedule_window_duration_hours: int | None = None
    schedule_mode: str | None = None
    batch_max: int | None = None
    format_engine: str | None = None


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
