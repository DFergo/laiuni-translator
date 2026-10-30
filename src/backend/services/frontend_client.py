"""HTTP client for backend → frontend calls (backend surface).

Every frontend in the registry has an `auth_mode`:
  - "signed"   → `{url}/backend/v1/<op>`, HMAC-signed with the frontend's own
                 `signing_secret`, or else the installation-wide secret from the
                 backend env var TRANSLATOR_FRONTEND_SECRET (same value as
                 TRANSLATOR_BACKEND_SECRET on the frontends).
  - "unsigned" → `{url}/backend/v1/<op>` without a signature ("trusted network";
                 the frontend must run with BACKEND_SURFACE_AUTH=trusted-network).
  - "legacy"   → `{url}/internal/<op>` unchanged, unsigned — frontends still on the
                 image from before the two-port split.
Optional `extra_headers` (e.g. Cloudflare Access service token) go on every request.
Call sites keep writing `{url}/internal/<op>`; this client rewrites per mode.

Canonical string (must match src/frontend/sidecar/backend_auth.py):
    v1\\n{ts}\\n{nonce}\\n{METHOD}\\n{path?query}\\n{sha256hex(body)}
"""

import hashlib
import hmac
import logging
import os
import secrets
import time
from typing import Any

import httpx

logger = logging.getLogger("backend.frontend_client")

LEGACY_PREFIX = "/internal/"
SIGNED_PREFIX = "/backend/v1/"

MODE_SIGNED = "signed"
MODE_UNSIGNED = "unsigned"
MODE_LEGACY = "legacy"
AUTH_MODES = (MODE_SIGNED, MODE_UNSIGNED, MODE_LEGACY)
MIN_SECRET_LENGTH = 32

_warned: set[str] = set()


class MissingSigningSecret(httpx.RequestError):
    """Signed mode but neither a per-frontend nor an installation secret is set."""


def global_secret() -> str:
    """Installation-wide signing secret (TRANSLATOR_FRONTEND_SECRET), '' if unset/too short."""
    value = os.environ.get("TRANSLATOR_FRONTEND_SECRET", "").strip()
    if value and len(value) < MIN_SECRET_LENGTH:
        if "global-short" not in _warned:
            _warned.add("global-short")
            logger.error(f"TRANSLATOR_FRONTEND_SECRET is shorter than {MIN_SECRET_LENGTH} characters — ignored")
        return ""
    return value


def auth_mode(fe: dict[str, Any]) -> str:
    """Mode of a registry entry. Entries from before modes existed: secret → signed, else legacy."""
    mode = fe.get("auth_mode")
    if mode in AUTH_MODES:
        return mode
    return MODE_SIGNED if fe.get("signing_secret") else MODE_LEGACY


def effective_secret(fe: dict[str, Any]) -> tuple[str, str]:
    """(secret, source) for a signed entry; source is "own", "global" or ""."""
    if fe.get("signing_secret"):
        return fe["signing_secret"], "own"
    g = global_secret()
    return (g, "global") if g else ("", "")


def _warn_once(key: str, msg: str):
    if key not in _warned:
        _warned.add(key)
        logger.warning(msg)


def sign(secret: str, ts: str, nonce: str, method: str, path_qs: str, body: bytes) -> str:
    canon = "\n".join(["v1", ts, nonce, method.upper(), path_qs, hashlib.sha256(body).hexdigest()])
    return "v1=" + hmac.new(secret.encode(), canon.encode(), hashlib.sha256).hexdigest()


def _to_backend_surface(request: httpx.Request, extra_headers: dict[str, str] | None):
    path = request.url.path
    if path.startswith(LEGACY_PREFIX):
        request.url = request.url.copy_with(path=SIGNED_PREFIX + path[len(LEGACY_PREFIX):])
    for k, v in (extra_headers or {}).items():
        request.headers[k] = v


def _sign_request(request: httpx.Request, secret: str, extra_headers: dict[str, str] | None):
    _to_backend_surface(request, extra_headers)
    ts = str(int(time.time()))
    nonce = secrets.token_urlsafe(18)
    path_qs = request.url.raw_path.decode("ascii")  # path + "?query" as sent on the wire
    request.headers["X-HRDD-Timestamp"] = ts
    request.headers["X-HRDD-Nonce"] = nonce
    request.headers["X-HRDD-Signature"] = sign(secret, ts, nonce, request.method, path_qs, request.content)


def _match_frontend(url: str) -> dict[str, Any] | None:
    from src.services.frontend_registry import registry
    best = None
    for fe in registry.list_all():
        base = fe.get("url", "").rstrip("/")
        if base and (url == base or url.startswith(base + "/")):
            if best is None or len(base) > len(best["url"].rstrip("/")):
                best = fe
    return best


def _apply(request: httpx.Request, fe: dict[str, Any]):
    """Rewrite / sign one request according to the entry's mode."""
    mode = auth_mode(fe)
    label = f"Frontend {fe.get('id', '?')} ({fe.get('name', '')})"
    if mode == MODE_SIGNED:
        secret, _ = effective_secret(fe)
        if not secret:
            raise MissingSigningSecret(
                f"{label}: signed mode but no signing secret (set one in Admin → Frontends → "
                f"Security, or TRANSLATOR_FRONTEND_SECRET on the backend)", request=request)
        _sign_request(request, secret, fe.get("extra_headers"))
    elif mode == MODE_UNSIGNED:
        _warn_once(f"unsigned-{fe.get('id')}", f"{label} is registered as TRUSTED NETWORK — requests are not signed.")
        _to_backend_surface(request, fe.get("extra_headers"))
    else:
        _warn_once(f"legacy-{fe.get('id')}", f"{label} uses the LEGACY protocol (old frontend image, unsigned).")
        for k, v in (fe.get("extra_headers") or {}).items():
            request.headers[k] = v


class _RegistryAuth(httpx.Auth):
    """Applies the registry entry's mode to every request aimed at a registered frontend."""

    requires_request_body = True

    def auth_flow(self, request: httpx.Request):
        fe = _match_frontend(str(request.url))
        if fe:
            _apply(request, fe)
        yield request


class _ExplicitAuth(httpx.Auth):
    """Applies an explicit (not yet saved) entry — used to probe on register/edit."""

    requires_request_body = True

    def __init__(self, fe: dict[str, Any]):
        self.fe = fe

    def auth_flow(self, request: httpx.Request):
        _apply(request, self.fe)
        yield request


def AsyncClient(timeout: float | httpx.Timeout = 10.0, **kwargs: Any) -> httpx.AsyncClient:
    """Drop-in for httpx.AsyncClient for all backend → frontend traffic."""
    return httpx.AsyncClient(timeout=timeout, auth=_RegistryAuth(), **kwargs)


def ProbeClient(fe: dict[str, Any], timeout: float = 10.0) -> httpx.AsyncClient:
    """Client for an entry that is not (yet) saved: `fe` = {auth_mode, signing_secret, extra_headers}."""
    return httpx.AsyncClient(timeout=timeout, auth=_ExplicitAuth(fe))
