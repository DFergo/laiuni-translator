# Copyright (c) 2026 UNI Global Union. All rights reserved. See LICENSE.
"""Request signing for the backend surface of the sidecar.

Every request on the backend surface must carry an HMAC-SHA256 signature made
with this frontend's secret. The canonical string covers method, raw path with
query, timestamp, nonce and the SHA-256 of the body:

    v1\\n{timestamp}\\n{nonce}\\n{METHOD}\\n{path?query}\\n{sha256hex(body)}

Headers (same names as HRDD Helper — one protocol across the apps): X-HRDD-Timestamp (epoch seconds), X-HRDD-Nonce, X-HRDD-Signature
("v1=<hex>"). The backend's `services/frontend_client.py` implements the
signing side with the same canonical string.

Replay protection: timestamps outside ±120 s are rejected, nonces are cached
until they fall out of the window, and requests signed before this process
started are rejected — so a request captured before a restart cannot be
replayed after it, even though the in-memory nonce cache is lost.

Modes (BACKEND_SURFACE_AUTH):
  signed           (default) every request must be signed; no secret → reject all.
  trusted-network  no signature check. Supported for deployments where only the
                   backend can reach port 8080 (same host internal network, closed
                   LAN segment). Anyone who can reach that port gets full access to
                   the backend surface. Logged at startup and hourly while in use.
ALLOW_UNSIGNED_BACKEND_SURFACE=true is the older name for trusted-network.
"""

import hashlib
import hmac
import json
import logging
import os
import time

logger = logging.getLogger("sidecar.backend_auth")

SIGNATURE_VERSION = "v1"
WINDOW_SECONDS = 120
MIN_SECRET_LENGTH = 32
# Result ZIPs (original + one file per target language) reach ~414 MB for a
# 25 MB document into 16 languages; 512 MB leaves margin (SPEC §14.4).
MAX_BODY_BYTES = 512 * 1024 * 1024
MAX_NONCES = 100_000

HEADER_TS = "x-hrdd-timestamp"
HEADER_NONCE = "x-hrdd-nonce"
HEADER_SIG = "x-hrdd-signature"


def canonical_string(ts: str, nonce: str, method: str, path_qs: str, body: bytes) -> str:
    return "\n".join([
        SIGNATURE_VERSION, ts, nonce, method.upper(), path_qs,
        hashlib.sha256(body).hexdigest(),
    ])


def sign(secret: str, ts: str, nonce: str, method: str, path_qs: str, body: bytes) -> str:
    mac = hmac.new(secret.encode(), canonical_string(ts, nonce, method, path_qs, body).encode(), hashlib.sha256)
    return f"{SIGNATURE_VERSION}={mac.hexdigest()}"


MODE_SIGNED = "signed"
MODE_TRUSTED = "trusted-network"
TRUSTED_WARN_INTERVAL = 3600


def surface_mode() -> str:
    """Effective backend-surface auth mode from the environment."""
    mode = os.environ.get("BACKEND_SURFACE_AUTH", "").strip().lower()
    if mode in (MODE_SIGNED, MODE_TRUSTED):
        return mode
    if mode:
        logger.error(f"Unknown BACKEND_SURFACE_AUTH={mode!r} — using '{MODE_SIGNED}'")
        return MODE_SIGNED
    if os.environ.get("ALLOW_UNSIGNED_BACKEND_SURFACE", "false").lower() == "true":
        return MODE_TRUSTED
    return MODE_SIGNED


def _load_secrets() -> list[str]:
    out = []
    for var in ("TRANSLATOR_BACKEND_SECRET", "TRANSLATOR_BACKEND_SECRET_PREVIOUS"):
        value = os.environ.get(var, "").strip()
        if not value:
            continue
        if len(value) < MIN_SECRET_LENGTH:
            logger.error(f"{var} is shorter than {MIN_SECRET_LENGTH} characters — ignored")
            continue
        out.append(value)
    return out


class BackendSignatureMiddleware:
    """ASGI middleware: buffers the body, verifies the signature, replays the body.

    Done at the ASGI level (not as a FastAPI dependency) because multipart
    routes consume the request stream before dependencies could read it.
    """

    def __init__(self, app):
        self.app = app
        self.secrets = _load_secrets()
        self.allow_unsigned = surface_mode() == MODE_TRUSTED
        self.started_at = int(time.time())
        self._nonces: dict[str, float] = {}
        self._last_trusted_warn = 0.0
        if self.allow_unsigned:
            self._warn_trusted()
        elif not self.secrets:
            logger.error(
                "TRANSLATOR_BACKEND_SECRET is not set — every request to the backend surface "
                "will be rejected until it is configured."
            )

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        body = bytearray()  # linear growth for large artifact bodies
        more = True
        while more:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body += message.get("body", b"")
            more = message.get("more_body", False)
            if len(body) > MAX_BODY_BYTES:
                await _send_status(send, 413, "Payload too large")
                return

        body = bytes(body)

        if self.allow_unsigned:
            if time.time() - self._last_trusted_warn > TRUSTED_WARN_INTERVAL:
                self._warn_trusted()
        else:
            reason = self._verify(scope, body)
            if reason:
                logger.warning(f"Rejected backend-surface request {scope['method']} {scope['path']} from {_client_ip(scope)}: {reason}")
                await _send_status(send, 401, "Unauthorized")
                return

        replayed = False

        async def replay():
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self.app(scope, replay, send)

    def _warn_trusted(self):
        self._last_trusted_warn = time.time()
        logger.warning(
            "BACKEND_SURFACE_AUTH=trusted-network — the backend surface (port 8080) accepts "
            "UNSIGNED requests. Only safe if nothing but the Translator backend can reach that port."
        )

    def _verify(self, scope, body: bytes) -> str | None:
        """Return None if valid, else a short reason for the log (never sent to the client)."""
        if not self.secrets:
            return "no secret configured"
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        ts, nonce, sig = headers.get(HEADER_TS, ""), headers.get(HEADER_NONCE, ""), headers.get(HEADER_SIG, "")
        if not (ts and nonce and sig):
            return "missing signature headers"
        if not ts.isdigit() or not (8 <= len(nonce) <= 128):
            return "malformed signature headers"
        now = time.time()
        ts_int = int(ts)
        if abs(now - ts_int) > WINDOW_SECONDS:
            return "timestamp outside window (check clock sync)"
        if ts_int < self.started_at:
            return "signed before this process started"

        raw_path = scope.get("raw_path") or scope["path"].encode()
        path_qs = raw_path.decode("latin-1")
        if scope.get("query_string"):
            path_qs += "?" + scope["query_string"].decode("latin-1")

        matched = False
        for secret in self.secrets:
            expected = sign(secret, ts, nonce, scope["method"], path_qs, body)
            if hmac.compare_digest(expected.encode(), sig.encode()):
                matched = True
        if not matched:
            return "bad signature"

        # Nonce check only after the signature is valid, so unauthenticated
        # traffic can't fill the cache.
        self._prune(now)
        if nonce in self._nonces:
            return "replayed nonce"
        if len(self._nonces) >= MAX_NONCES:
            return "nonce cache full"
        self._nonces[nonce] = now + 2 * WINDOW_SECONDS
        return None

    def _prune(self, now: float):
        expired = [n for n, exp in self._nonces.items() if exp < now]
        for n in expired:
            del self._nonces[n]


def _client_ip(scope) -> str:
    """Real client IP for the log: Nginx sets X-Real-IP; fall back to the socket peer."""
    for k, v in scope.get("headers", []):
        if k == b"x-real-ip":
            return v.decode("latin-1")
    return (scope.get("client") or ("?", 0))[0]


async def _send_status(send, status: int, detail: str):
    payload = json.dumps({"detail": detail}).encode()
    await send({
        "type": "http.response.start",
        "status": status,
        "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(payload)).encode())],
    })
    await send({"type": "http.response.body", "body": payload})
