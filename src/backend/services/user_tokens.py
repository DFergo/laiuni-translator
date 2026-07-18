"""User bearer tokens (Sprint 5, SPEC §3.1).

Reuses the admin JWT machinery (HS256 + the shared `.jwt_secret`) rather than
reinventing crypto — `mint_user_token` / `verify_user_token` just wrap the
existing helpers with a user payload (`type:"user"`, `sub` = email, `fid`).

The result email carries a **signed download token** (`type:"download"`,
Sprint 12, SPEC §12): same HS256 secret, scoped to one job (`ref`), expiring
with retention (`exp`), single-use via `jti` (redemption tracked in
`job_channel`). It lets the emailed link authenticate without the browser
bearer token, staying token-gated (never a bare URL secret).
"""

import secrets
import time

from src.api.v1.admin.auth import _create_jwt, _decode_jwt, _get_jwt_secret

USER_TOKEN_EXPIRY = 24 * 3600  # 24h


def mint_user_token(email: str, frontend_id: str = "") -> str:
    """Mint a bearer token for an authenticated (whitelisted) user email."""
    now = int(time.time())
    payload = {
        "sub": email.lower().strip(),
        "fid": frontend_id,
        "type": "user",
        "iat": now,
        "exp": now + USER_TOKEN_EXPIRY,
    }
    return _create_jwt(payload, _get_jwt_secret())


def verify_user_token(token: str) -> dict | None:
    """Return the payload of a valid user token, else None."""
    payload = _decode_jwt(token or "", _get_jwt_secret())
    if not payload or payload.get("type") != "user":
        return None
    return payload


def mint_download_token(email: str, frontend_id: str, ref: str, expires_at: float) -> str:
    """Mint a signed, single-use, retention-bounded token for the result-email link.

    ``exp`` = the job's retention deadline, so the link dies exactly when the
    files are swept. ``jti`` is the single-use nonce (redemption is enforced by
    the backend when the link is clicked)."""
    now = int(time.time())
    payload = {
        "sub": email.lower().strip(),
        "fid": frontend_id,
        "ref": ref,
        "type": "download",
        "jti": secrets.token_urlsafe(9),
        "iat": now,
        "exp": int(expires_at),
    }
    return _create_jwt(payload, _get_jwt_secret())


def verify_download_token(token: str) -> dict | None:
    """Return the payload of a valid (unexpired) download token, else None.
    Single-use enforcement is the caller's job (the `jti`)."""
    payload = _decode_jwt(token or "", _get_jwt_secret())
    if not payload or payload.get("type") != "download":
        return None
    return payload
