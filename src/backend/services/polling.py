"""Backend pull-inverse channel — the security boundary (SPEC §2, §8; ADR-009).

The browser talks only to the frontend **sidecar**; the sidecar never calls the
backend. Instead the backend polls each enabled frontend's sidecar
(`GET /internal/queue`) and pushes results back. The backend therefore accepts
no inbound connections from the public internet — it initiates every connection
outbound.

Sprint 1 scope: frontend status polling + auth-request handling (magic-code
against the whitelist) + branding push. The HRDD chat/evidence/RAG/guardrail
message processing has been stripped. Translation-job handling is added on this
same channel in Sprints 4–5.
"""

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

import httpx

from src.services.frontend_registry import registry
from src.services.smtp_service import (
    is_email_authorized, generate_auth_code, verify_auth_code,
    send_auth_code, is_configured as smtp_configured,
)

logger = logging.getLogger("backend.polling")


_branding_pushed: set[str] = set()  # Track which frontends have branding pushed


def invalidate_branding_cache(frontend_id: str = ""):
    """Clear branding push cache so it gets re-pushed on next poll."""
    if frontend_id:
        _branding_pushed.discard(frontend_id)
    else:
        _branding_pushed.clear()


async def _push_branding_if_needed(client: httpx.AsyncClient, url: str, fid: str):
    """Push branding config + translations to sidecar (once per session, or on change)."""
    if fid in _branding_pushed:
        return
    branding_path = Path(f"/app/data/campaigns/{fid}/branding.json")
    if not branding_path.exists():
        _branding_pushed.add(fid)
        return
    try:
        data = json.loads(branding_path.read_text())
        has_custom_text = bool(data.get("disclaimer_text") or data.get("instructions_text"))
        # Include translations if available
        from src.services.branding_translator import load_translations
        translations = load_translations(fid)
        payload = {**data, "custom": has_custom_text, "translations": translations}
        await client.post(f"{url}/internal/branding", json=payload)
        logger.info(f"Branding pushed to {fid}")
    except Exception as e:
        logger.debug(f"Branding push to {fid} failed: {e}")
        return  # Don't mark as pushed — retry next poll
    _branding_pushed.add(fid)


async def poll_frontends():
    """Poll all enabled frontends for pending auth requests; push branding."""
    client = httpx.AsyncClient(timeout=10.0)
    try:
        enabled = registry.list_enabled()

        for frontend in enabled:
            url = frontend["url"]
            fid = frontend["id"]
            try:
                resp = await client.get(f"{url}/internal/queue")
                resp.raise_for_status()
                data = resp.json()
                registry.set_status(fid, "online")

                # Push branding config if exists (survives sidecar restarts)
                await _push_branding_if_needed(client, url, fid)

                # Handle auth requests (pull-inverse: sidecar queues, backend resolves)
                auth_requests = data.get("auth_requests", [])
                for auth_req in auth_requests:
                    await _handle_auth_request(client, url, auth_req, fid)

            except Exception as e:
                registry.set_status(fid, "offline")
                logger.warning(f"Failed to poll {fid} ({url}): {e}")
    finally:
        await client.aclose()


async def _handle_auth_request(client: httpx.AsyncClient, frontend_url: str, auth_req: dict[str, Any], frontend_id: str = ""):
    """Handle an auth request from the sidecar (pull-inverse).

    Code request: check the whitelist, generate a code, email it. Verification:
    validate the submitted code. No user enumeration — the sidecar reports the
    same generic outcome regardless of whitelist membership (SPEC §8).
    """
    session_token = auth_req.get("session_token", "")
    email = auth_req.get("email", "").lower().strip()
    code_attempt = auth_req.get("code", "")
    language = auth_req.get("language", "en")

    if not session_token:
        return

    try:
        if code_attempt:
            # Verification attempt
            valid = verify_auth_code(session_token, code_attempt)
            result = {
                "session_token": session_token,
                "status": "verified" if valid else "invalid_code",
                "email": email,
            }
        else:
            # Code request — check whitelist, generate code, send email
            if not is_email_authorized(email, frontend_id):
                result = {
                    "session_token": session_token,
                    "status": "not_authorized",
                    "email": email,
                }
                logger.info(f"Auth rejected: {email} not in whitelist")
            elif not smtp_configured():
                result = {
                    "session_token": session_token,
                    "status": "smtp_not_configured",
                    "email": email,
                }
                logger.warning("Auth request but SMTP not configured")
            else:
                code = generate_auth_code(session_token, email)
                sent = await send_auth_code(email, code, language)
                if sent:
                    result = {
                        "session_token": session_token,
                        "status": "code_sent",
                        "email": email,
                    }
                    logger.info(f"Auth code sent to {email} for {session_token}")
                else:
                    result = {
                        "session_token": session_token,
                        "status": "smtp_error",
                        "email": email,
                    }
                    logger.error(f"Failed to send auth code to {email}")

        await client.post(
            f"{frontend_url}/internal/auth/{session_token}/result",
            json=result,
        )
    except Exception as e:
        logger.error(f"Auth request handling failed: {e}")


async def polling_loop(interval: int = 2):
    """Main polling loop — runs as background task."""
    logger.info(f"Polling loop started (interval: {interval}s)")
    while True:
        try:
            await poll_frontends()
        except Exception as e:
            logger.error(f"Polling loop error: {e}")
        await asyncio.sleep(interval)
