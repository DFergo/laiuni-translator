"""User bearer tokens (Sprint 5, SPEC §3.1).

Reuses the admin JWT machinery (HS256 + the shared `.jwt_secret`) rather than
reinventing crypto — `mint_user_token` / `verify_user_token` just wrap the
existing helpers with a user payload (`type:"user"`, `sub` = email, `fid`).
"""

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
