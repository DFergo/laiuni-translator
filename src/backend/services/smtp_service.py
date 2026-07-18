"""SMTP service — email sending for auth codes, notifications, and reports.

Sprint 9: Best-effort email sending. Failures are logged but never block the system.
"""

import json
import logging
import secrets
import time
from email.message import EmailMessage
from pathlib import Path
from typing import Any

import aiosmtplib

logger = logging.getLogger("backend.smtp")

from src.core.paths import SMTP_CONFIG, AUTHORIZED_CONTACTS, CONFIG_DIR, CAMPAIGNS_DIR
_SETTINGS_PATH = SMTP_CONFIG
_AUTHORIZED_EMAILS_PATH = CONFIG_DIR / "authorized_emails.json"  # legacy — migrated on first load
_AUTHORIZED_CONTACTS_PATH = AUTHORIZED_CONTACTS

# Contact schema — keys on every contact record
_CONTACT_FIELDS = ("email", "first_name", "last_name", "organization", "country", "sector", "registered_by")
_OVERRIDE_MODES = ("replace", "append")

# In-memory auth code store: {session_token: {email, code, expires_at}}
_pending_codes: dict[str, dict[str, Any]] = {}
CODE_EXPIRY_SECONDS = 600  # 10 minutes


# --- Config ---

def _load_config() -> dict[str, Any]:
    defaults = {
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
    if _SETTINGS_PATH.exists():
        try:
            data = json.loads(_SETTINGS_PATH.read_text())
            # Migrate: old single admin_notify_address → notification_emails list
            if "admin_notify_address" in data and "notification_emails" not in data:
                old = data.pop("admin_notify_address", "")
                data["notification_emails"] = [old] if old else []
            elif "admin_notify_address" in data:
                data.pop("admin_notify_address", None)
            for key, val in defaults.items():
                data.setdefault(key, val)
            return data
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Failed to load SMTP config: {e}, using defaults")
    return defaults


def is_configured() -> bool:
    """Check if SMTP has minimum config to send."""
    cfg = _load_config()
    return bool(cfg.get("host") and cfg.get("from_address"))


# --- Authorized Contacts (Sprint 18) ---

def _empty_contact(email: str) -> dict[str, str]:
    return {k: "" for k in _CONTACT_FIELDS} | {"email": email.lower().strip()}


def _normalise_contact(raw: dict[str, Any]) -> dict[str, str] | None:
    """Coerce a raw contact dict into the canonical schema. Returns None if invalid."""
    email = str(raw.get("email", "")).lower().strip()
    if not email or "@" not in email:
        return None
    contact = {k: "" for k in _CONTACT_FIELDS}
    for field in _CONTACT_FIELDS:
        val = raw.get(field, "")
        contact[field] = str(val).strip() if val is not None else ""
    contact["email"] = email
    return contact


def _migrate_authorized_emails_if_needed() -> bool:
    """One-shot migration: authorized_emails.json → authorized_contacts.json.

    Runs once. Renames the legacy file to .bak after successful write.
    Returns True if migration ran, False if not needed.
    """
    if _AUTHORIZED_CONTACTS_PATH.exists():
        return False
    if not _AUTHORIZED_EMAILS_PATH.exists():
        return False
    try:
        data = json.loads(_AUTHORIZED_EMAILS_PATH.read_text())
        legacy_emails = data.get("emails", []) if isinstance(data, dict) else []
        contacts = []
        seen: set[str] = set()
        for e in legacy_emails:
            if not isinstance(e, str):
                continue
            norm = e.lower().strip()
            if not norm or norm in seen:
                continue
            seen.add(norm)
            contacts.append(_empty_contact(norm))
        payload = {"global": contacts, "per_frontend": {}}
        _AUTHORIZED_CONTACTS_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _AUTHORIZED_CONTACTS_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2))
        tmp.rename(_AUTHORIZED_CONTACTS_PATH)
        # Rename legacy file so we don't re-migrate
        bak = _AUTHORIZED_EMAILS_PATH.with_suffix(".json.bak")
        _AUTHORIZED_EMAILS_PATH.rename(bak)
        logger.info(f"Migrated {len(contacts)} authorized emails → authorized_contacts.json (legacy saved as {bak.name})")
        return True
    except Exception as e:
        logger.error(f"Failed to migrate authorized_emails.json: {e}")
        return False


def _empty_contacts_store() -> dict[str, Any]:
    return {"global": [], "per_frontend": {}}


def load_authorized_contacts() -> dict[str, Any]:
    """Load the full contacts store {global, per_frontend}. Runs migration on first call."""
    _migrate_authorized_emails_if_needed()
    if not _AUTHORIZED_CONTACTS_PATH.exists():
        return _empty_contacts_store()
    try:
        data = json.loads(_AUTHORIZED_CONTACTS_PATH.read_text())
        if not isinstance(data, dict):
            return _empty_contacts_store()
        data.setdefault("global", [])
        data.setdefault("per_frontend", {})
        # Normalise global list
        data["global"] = [c for c in (_normalise_contact(r) for r in data["global"] if isinstance(r, dict)) if c]
        # Normalise per_frontend overrides
        clean_pf: dict[str, Any] = {}
        for fid, override in (data.get("per_frontend") or {}).items():
            if not isinstance(override, dict):
                continue
            mode = override.get("mode", "replace")
            if mode not in _OVERRIDE_MODES:
                mode = "replace"
            raw_contacts = override.get("contacts", [])
            contacts = [c for c in (_normalise_contact(r) for r in raw_contacts if isinstance(r, dict)) if c]
            clean_pf[str(fid)] = {"mode": mode, "contacts": contacts}
        data["per_frontend"] = clean_pf
        return data
    except Exception as e:
        logger.warning(f"Failed to load authorized_contacts.json: {e}")
        return _empty_contacts_store()


def save_authorized_contacts(store: dict[str, Any]) -> dict[str, Any]:
    """Validate, normalise and persist the contacts store. Returns the normalised store."""
    clean: dict[str, Any] = _empty_contacts_store()

    seen_global: set[str] = set()
    for raw in store.get("global", []) or []:
        if not isinstance(raw, dict):
            continue
        c = _normalise_contact(raw)
        if not c or c["email"] in seen_global:
            continue
        seen_global.add(c["email"])
        clean["global"].append(c)
    clean["global"].sort(key=lambda c: c["email"])

    for fid, override in (store.get("per_frontend") or {}).items():
        if not isinstance(override, dict):
            continue
        mode = override.get("mode", "replace")
        if mode not in _OVERRIDE_MODES:
            mode = "replace"
        seen: set[str] = set()
        contacts: list[dict[str, str]] = []
        for raw in override.get("contacts", []) or []:
            if not isinstance(raw, dict):
                continue
            c = _normalise_contact(raw)
            if not c or c["email"] in seen:
                continue
            seen.add(c["email"])
            contacts.append(c)
        contacts.sort(key=lambda c: c["email"])
        clean["per_frontend"][str(fid)] = {"mode": mode, "contacts": contacts}

    _AUTHORIZED_CONTACTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _AUTHORIZED_CONTACTS_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(clean, indent=2))
    tmp.rename(_AUTHORIZED_CONTACTS_PATH)
    pf_count = sum(len(v.get("contacts", [])) for v in clean["per_frontend"].values())
    logger.info(
        f"Authorized contacts saved: {len(clean['global'])} global, "
        f"{len(clean['per_frontend'])} frontend override(s), {pf_count} per-frontend entries"
    )
    return clean


def _resolve_authorized_emails(frontend_id: str | None) -> set[str]:
    """Return the effective set of authorised emails for a given frontend (or global if None)."""
    store = load_authorized_contacts()
    global_emails = {c["email"] for c in store.get("global", [])}
    if not frontend_id:
        return global_emails
    override = (store.get("per_frontend") or {}).get(frontend_id)
    if not override:
        return global_emails
    fe_emails = {c["email"] for c in override.get("contacts", [])}
    mode = override.get("mode", "replace")
    if mode == "append":
        return global_emails | fe_emails
    return fe_emails  # replace


def is_email_authorized(email: str, frontend_id: str | None = None) -> bool:
    """Check if an email is authorised. Resolves per-frontend override if frontend_id given."""
    return email.lower().strip() in _resolve_authorized_emails(frontend_id)


# --- Backward-compat wrappers (to be removed once all callers pass frontend_id) ---

def load_authorized_emails() -> list[str]:
    """Legacy: return global email list only."""
    return sorted(c["email"] for c in load_authorized_contacts().get("global", []))


def save_authorized_emails(emails: list[str]):
    """Legacy: replace the global list, preserving existing extended fields where email still present."""
    store = load_authorized_contacts()
    existing_by_email = {c["email"]: c for c in store.get("global", [])}
    new_global: list[dict[str, str]] = []
    for e in emails:
        if not isinstance(e, str):
            continue
        norm = e.lower().strip()
        if not norm:
            continue
        new_global.append(existing_by_email.get(norm) or _empty_contact(norm))
    store["global"] = new_global
    save_authorized_contacts(store)


# --- Email Sending ---

async def send_email(to: str, subject: str, body: str) -> bool:
    """Send an email. Returns True on success, False on failure. Never raises."""
    cfg = _load_config()
    if not cfg.get("host") or not cfg.get("from_address"):
        logger.debug("SMTP not configured, skipping email")
        return False

    msg = EmailMessage()
    msg["From"] = cfg["from_address"]
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)

    try:
        await aiosmtplib.send(
            msg,
            hostname=cfg["host"],
            port=cfg["port"],
            username=cfg.get("username") or None,
            password=cfg.get("password") or None,
            start_tls=cfg.get("use_tls", True),
        )
        logger.info(f"Email sent to {to}: {subject}")
        return True
    except Exception as e:
        logger.error(f"Failed to send email to {to}: {e}")
        return False


async def send_email_with_attachments(
    to: str, subject: str, body: str, attachments: list[Path]
) -> bool:
    """Send an email with file attachments. Returns True on success. Never raises.

    Used for the translation-result email (Sprint 4): the original + all
    translated files (SPEC §3.3). Falls back to a plain send if there are no
    attachments.
    """
    cfg = _load_config()
    if not cfg.get("host") or not cfg.get("from_address"):
        logger.debug("SMTP not configured, skipping email")
        return False

    msg = EmailMessage()
    msg["From"] = cfg["from_address"]
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)

    for path in attachments:
        try:
            data = Path(path).read_bytes()
        except OSError as e:
            logger.error(f"Attachment unreadable, skipping {path}: {e}")
            continue
        msg.add_attachment(
            data, maintype="application", subtype="octet-stream", filename=Path(path).name
        )

    try:
        await aiosmtplib.send(
            msg,
            hostname=cfg["host"],
            port=cfg["port"],
            username=cfg.get("username") or None,
            password=cfg.get("password") or None,
            start_tls=cfg.get("use_tls", True),
        )
        logger.info(f"Result email sent to {to}: {subject} ({len(attachments)} attachment(s))")
        return True
    except Exception as e:
        logger.error(f"Failed to send result email to {to}: {e}")
        return False


async def send_translation_ready(
    to: str, download_url: str, language: str = "en"
) -> bool:
    """Email the user a **download link** to their finished translation (Sprint 12,
    SPEC §12). The link is signed, single-use, and expires with retention — no
    attachments (better deliverability, no SMTP size limits). Never raises."""
    subjects = {
        "en": "Your translation is ready",
        "es": "Tu traducción está lista",
        "fr": "Votre traduction est prête",
    }
    bodies = {
        "en": ("Your document has been translated.\n\n"
               f"Download the original and all translations (one-time link):\n{download_url}\n\n"
               "The link expires once the files are removed from the server."),
        "es": ("Tu documento ha sido traducido.\n\n"
               f"Descarga el original y todas las traducciones (enlace de un solo uso):\n{download_url}\n\n"
               "El enlace caduca cuando los archivos se eliminan del servidor."),
        "fr": ("Votre document a été traduit.\n\n"
               f"Téléchargez l'original et toutes les traductions (lien à usage unique) :\n{download_url}\n\n"
               "Le lien expire dès que les fichiers sont supprimés du serveur."),
    }
    subject = subjects.get(language, subjects["en"])
    body = bodies.get(language, bodies["en"])
    return await send_email(to, subject, body)


async def test_connection() -> dict[str, str]:
    """Test SMTP connection. Returns status dict."""
    cfg = _load_config()
    if not cfg.get("host"):
        return {"status": "error", "message": "SMTP host not configured"}

    try:
        smtp = aiosmtplib.SMTP(
            hostname=cfg["host"],
            port=cfg["port"],
            start_tls=cfg.get("use_tls", True),
        )
        await smtp.connect()
        if cfg.get("username") and cfg.get("password"):
            await smtp.login(cfg["username"], cfg["password"])
        await smtp.quit()

        # Send test email if notification emails configured
        notify_emails = cfg.get("notification_emails", [])
        if notify_emails:
            first = notify_emails[0]
            sent = await send_email(
                first,
                "UNI Translator — SMTP Test",
                "This is a test email from UNI Translator. SMTP is working correctly."
            )
            if sent:
                return {"status": "ok", "message": f"Connected and test email sent to {first}"}
            return {"status": "warning", "message": "Connected but failed to send test email"}

        return {"status": "ok", "message": "Connection successful"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


async def check_smtp_health():
    """Non-blocking health check on startup. Logs warning if unreachable."""
    cfg = _load_config()
    if not cfg.get("host"):
        return
    try:
        smtp = aiosmtplib.SMTP(
            hostname=cfg["host"],
            port=cfg["port"],
            start_tls=cfg.get("use_tls", True),
        )
        await smtp.connect()
        await smtp.quit()
        logger.info("SMTP health check: OK")
    except Exception as e:
        logger.warning(f"SMTP health check failed: {e} — email features may not work")


# --- Auth Codes ---

def generate_auth_code(session_token: str, email: str) -> str:
    """Generate a 6-digit auth code for a session."""
    code = f"{secrets.randbelow(1000000):06d}"
    _pending_codes[session_token] = {
        "email": email.lower().strip(),
        "code": code,
        "expires_at": time.time() + CODE_EXPIRY_SECONDS,
    }
    # Clean expired codes
    now = time.time()
    expired = [k for k, v in _pending_codes.items() if v["expires_at"] < now]
    for k in expired:
        del _pending_codes[k]

    return code


def verify_auth_code(session_token: str, code: str) -> bool:
    """Verify an auth code. Returns True if valid."""
    pending = _pending_codes.get(session_token)
    if not pending:
        return False
    if time.time() > pending["expires_at"]:
        del _pending_codes[session_token]
        return False
    if pending["code"] == code:
        del _pending_codes[session_token]
        return True
    return False


def get_pending_email(session_token: str) -> str | None:
    """Get the email associated with a pending auth code."""
    pending = _pending_codes.get(session_token)
    if pending and time.time() <= pending["expires_at"]:
        return pending["email"]
    return None


async def send_auth_code(email: str, code: str, language: str = "en") -> bool:
    """Send an auth code email. Returns True on success."""
    subjects = {
        "en": "UNI Translator — Your verification code",
        "es": "UNI Translator — Tu código de verificación",
        "fr": "UNI Translator — Votre code de vérification",
    }
    bodies = {
        "en": f"Your verification code is: {code}\n\nThis code expires in 10 minutes.\nIf you did not request this code, please ignore this email.",
        "es": f"Tu código de verificación es: {code}\n\nEste código caduca en 10 minutos.\nSi no has solicitado este código, ignora este email.",
        "fr": f"Votre code de vérification est : {code}\n\nCe code expire dans 10 minutes.\nSi vous n'avez pas demandé ce code, veuillez ignorer cet email.",
    }
    subject = subjects.get(language, subjects["en"])
    body = bodies.get(language, bodies["en"])
    return await send_email(email, subject, body)


# --- Notification recipients ---

_CAMPAIGNS_DIR = CAMPAIGNS_DIR

def _resolve_notification_recipients(frontend_id: str = "") -> list[str]:
    """Resolve notification recipients: per-frontend list + global fallback."""
    recipients: list[str] = []

    # Per-frontend notification emails
    if frontend_id:
        fe_config_path = _CAMPAIGNS_DIR / frontend_id / "notification_config.json"
        if fe_config_path.exists():
            try:
                data = json.loads(fe_config_path.read_text())
                fe_emails = data.get("notification_emails", [])
                recipients.extend(e.lower().strip() for e in fe_emails if e.strip())
            except (json.JSONDecodeError, OSError):
                pass

    # Global notification emails (always added)
    cfg = _load_config()
    global_emails = cfg.get("notification_emails", [])
    recipients.extend(e.lower().strip() for e in global_emails if e.strip())

    # Deduplicate preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for e in recipients:
        if e not in seen:
            seen.add(e)
            unique.append(e)
    return unique


def save_frontend_notification_emails(frontend_id: str, emails: list[str]):
    """Save per-frontend notification emails."""
    dir_path = _CAMPAIGNS_DIR / frontend_id
    dir_path.mkdir(parents=True, exist_ok=True)
    config_path = dir_path / "notification_config.json"
    clean = sorted(set(e.lower().strip() for e in emails if e.strip()))
    tmp = config_path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"notification_emails": clean}, indent=2))
    tmp.rename(config_path)
    logger.info(f"Frontend {frontend_id} notification emails updated: {len(clean)} entries")


def load_frontend_notification_emails(frontend_id: str) -> list[str]:
    """Load per-frontend notification emails."""
    config_path = _CAMPAIGNS_DIR / frontend_id / "notification_config.json"
    if config_path.exists():
        try:
            data = json.loads(config_path.read_text())
            return [e.lower().strip() for e in data.get("notification_emails", []) if e.strip()]
        except (json.JSONDecodeError, OSError):
            pass
    return []


# --- Notifications ---

async def notify_admin_report(session_token: str, report_content: str, frontend_id: str = ""):
    """Notify all configured recipients that a report was generated."""
    cfg = _load_config()
    if not cfg.get("notify_on_report"):
        return
    recipients = _resolve_notification_recipients(frontend_id)
    if not recipients:
        return
    subject = f"UNI Translator — Report generated for session {session_token}"
    body = f"A report has been generated for session {session_token}.\n\n---\n\n{report_content}"
    for addr in recipients:
        await send_email(addr, subject, body)


async def send_user_summary(email: str, session_token: str, summary: str, language: str = "en"):
    """Send session summary to user."""
    cfg = _load_config()
    if not cfg.get("send_summary_to_user"):
        return
    subjects = {
        "en": f"UNI Translator — Session summary ({session_token})",
        "es": f"UNI Translator — Resumen de sesión ({session_token})",
        "fr": f"UNI Translator — Résumé de session ({session_token})",
    }
    subject = subjects.get(language, subjects["en"])
    await send_email(email, subject, summary)


async def send_user_report(email: str, session_token: str, report: str, language: str = "en"):
    """Send report to user."""
    cfg = _load_config()
    if not cfg.get("send_report_to_user"):
        return
    subjects = {
        "en": f"UNI Translator — Session report ({session_token})",
        "es": f"UNI Translator — Informe de sesión ({session_token})",
        "fr": f"UNI Translator — Rapport de session ({session_token})",
    }
    subject = subjects.get(language, subjects["en"])
    await send_email(email, subject, report)


# --- Sprint 17: LLM slot failure notifications ---

_last_slot_email: dict[str, float] = {}
_SLOT_EMAIL_COOLDOWN = 3600.0  # 1 hour per slot


async def notify_slot_failure(
    slot_name: str,
    failed_provider: str,
    failed_model: str,
    error: str,
    fallback_provider: str | None = None,
    fallback_model: str | None = None,
):
    """Notify admin recipients that an LLM slot has degraded.

    Rate-limited to 1 email per slot per hour.
    Silently skips if SMTP is not configured or no recipients.
    """
    import time

    now = time.time()
    last = _last_slot_email.get(slot_name, 0)
    if now - last < _SLOT_EMAIL_COOLDOWN:
        logger.debug(f"Slot failure email for '{slot_name}' suppressed (rate limit)")
        return

    recipients = _resolve_notification_recipients()
    if not recipients:
        logger.warning(
            f"LLM slot '{slot_name}' degraded ({failed_provider}/{failed_model}: {error}) "
            f"but no notification recipients configured"
        )
        return

    if fallback_provider:
        subject = f"[UNI Translator] LLM slot \"{slot_name}\" degraded — falling back to {fallback_model}"
        body = (
            f"The LLM slot \"{slot_name}\" has failed and the system is using a fallback.\n\n"
            f"Failed: {failed_provider} / {failed_model}\n"
            f"Error: {error}\n"
            f"Fallback active: {fallback_provider} / {fallback_model}\n\n"
            f"The system is still operational but running in degraded mode. "
            f"Check that the primary model is loaded and responsive.\n\n"
            f"This email is rate-limited to 1 per hour per slot."
        )
    else:
        subject = f"[UNI Translator] LLM slot \"{slot_name}\" OFFLINE — no fallback available"
        body = (
            f"The LLM slot \"{slot_name}\" has failed and NO fallback is available.\n\n"
            f"Failed: {failed_provider} / {failed_model}\n"
            f"Error: {error}\n\n"
            f"Users will see errors until the model is restored.\n\n"
            f"This email is rate-limited to 1 per hour per slot."
        )

    for addr in recipients:
        try:
            await send_email(addr, subject, body)
        except Exception as e:
            logger.error(f"Failed to send slot failure notification to {addr}: {e}")

    _last_slot_email[slot_name] = now
    logger.info(f"Slot failure notification sent for '{slot_name}' to {len(recipients)} recipients")
