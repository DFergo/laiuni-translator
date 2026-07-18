"""Admin SMTP endpoints — config, test, authorized emails, notification toggles.

Sprint 9: Real SMTP with aiosmtplib, auth code flow, notification toggles.
"""

import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from src.api.v1.admin.auth import require_admin

logger = logging.getLogger("backend.admin.smtp")

router = APIRouter(prefix="/admin/smtp", tags=["admin-smtp"])

from src.core.paths import SMTP_CONFIG
_SETTINGS_PATH = SMTP_CONFIG

_DEFAULTS = {
    "host": "",
    "port": 587,
    "username": "",
    "password": "",
    "use_tls": True,
    "from_address": "",
    "data_protection_email": "",
    "notification_emails": [],
    "notify_on_report": False,
    "send_summary_to_user": False,
    "send_report_to_user": False,
}


def _load_config() -> dict[str, Any]:
    if _SETTINGS_PATH.exists():
        try:
            data = json.loads(_SETTINGS_PATH.read_text())
            # Migrate: old single admin_notify_address → notification_emails list
            if "admin_notify_address" in data and "notification_emails" not in data:
                old = data.pop("admin_notify_address", "")
                data["notification_emails"] = [old] if old else []
            elif "admin_notify_address" in data:
                data.pop("admin_notify_address", None)
            for key, val in _DEFAULTS.items():
                data.setdefault(key, val)
            return data
        except (json.JSONDecodeError, OSError):
            pass
    return dict(_DEFAULTS)


def _save_config(config: dict[str, Any]):
    _SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _SETTINGS_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(config, indent=2))
    tmp.rename(_SETTINGS_PATH)


class SMTPConfigRequest(BaseModel):
    host: str | None = None
    port: int | None = None
    username: str | None = None
    password: str | None = None
    use_tls: bool | None = None
    from_address: str | None = None
    data_protection_email: str | None = None
    notification_emails: list[str] | None = None
    notify_on_report: bool | None = None
    send_summary_to_user: bool | None = None
    send_report_to_user: bool | None = None


@router.get("")
async def get_smtp_config(_: dict = Depends(require_admin)):
    """Get current SMTP configuration."""
    cfg = _load_config()
    if cfg.get("password"):
        cfg["password"] = "••••••••"
    return cfg


@router.put("")
async def update_smtp_config(req: SMTPConfigRequest, _: dict = Depends(require_admin)):
    """Update SMTP configuration."""
    current = _load_config()
    updates = req.model_dump(exclude_none=True)
    if updates.get("password") == "••••••••":
        del updates["password"]
    current.update(updates)
    _save_config(current)
    logger.info(f"SMTP config updated: {list(updates.keys())}")
    if current.get("password"):
        current["password"] = "••••••••"
    return current


@router.post("/test")
async def test_smtp(_: dict = Depends(require_admin)):
    """Test SMTP connection — sends real test email if admin address configured."""
    from src.services.smtp_service import test_connection
    result = await test_connection()
    logger.info(f"SMTP test: {result}")
    return result


# --- Authorized Emails ---

@router.get("/authorized-emails")
async def get_authorized_emails(_: dict = Depends(require_admin)):
    """Get list of authorized email addresses."""
    from src.services.smtp_service import load_authorized_emails
    return {"emails": load_authorized_emails()}


class AuthorizedEmailsRequest(BaseModel):
    emails: list[str]


@router.put("/authorized-emails")
async def update_authorized_emails(req: AuthorizedEmailsRequest, _: dict = Depends(require_admin)):
    """Update list of authorized email addresses."""
    from src.services.smtp_service import save_authorized_emails, load_authorized_emails
    save_authorized_emails(req.emails)
    return {"emails": load_authorized_emails()}


# --- Per-frontend notification emails ---

@router.get("/frontend-notifications/{frontend_id}")
async def get_frontend_notification_emails(frontend_id: str, _: dict = Depends(require_admin)):
    """Get notification emails for a specific frontend."""
    from src.services.smtp_service import load_frontend_notification_emails
    return {"emails": load_frontend_notification_emails(frontend_id)}


@router.put("/frontend-notifications/{frontend_id}")
async def update_frontend_notification_emails(frontend_id: str, req: AuthorizedEmailsRequest, _: dict = Depends(require_admin)):
    """Update notification emails for a specific frontend."""
    from src.services.smtp_service import save_frontend_notification_emails, load_frontend_notification_emails
    save_frontend_notification_emails(frontend_id, req.emails)
    return {"emails": load_frontend_notification_emails(frontend_id)}
