"""API tokens for the machine API (Sprint 22, SPEC §16.1).

Separate from the admin JWT and the user tokens. The plaintext (``lt_…``) is
returned once at creation; only its SHA-256 is stored in ``config/api_tokens.json``
(atomic writes, lesson #10). Revoking deletes the entry.
"""

import hashlib
import hmac
import json
import logging
import secrets
import time
from typing import Any

from src.core.paths import CONFIG_DIR

logger = logging.getLogger("backend.api_tokens")

_PATH = CONFIG_DIR / "api_tokens.json"
_PREFIX = "lt_"


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _load() -> list[dict[str, Any]]:
    if not _PATH.exists():
        return []
    try:
        return json.loads(_PATH.read_text())
    except (json.JSONDecodeError, OSError) as e:
        logger.error(f"Malformed api_tokens.json rejected, treating as empty: {e}")
        return []


def _save(tokens: list[dict[str, Any]]) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(tokens, indent=2))
    tmp.rename(_PATH)


SCOPES = ("translate", "admin")


def create(name: str, scope: str = "translate") -> tuple[str, dict[str, Any]]:
    """Mint a token. Returns ``(plaintext, public_entry)``; the plaintext is not recoverable."""
    name = name.strip()
    if scope not in SCOPES:
        raise ValueError(f"scope must be one of {SCOPES}")
    existing = _load()
    if any(e["name"].lower() == name.lower() for e in existing):  # name = job owner identity (api:<name>)
        raise ValueError(f"A token named '{name}' already exists")
    plaintext = _PREFIX + secrets.token_urlsafe(32)
    entry = {"id": secrets.token_hex(4), "name": name, "hash": _hash(plaintext), "scope": scope,
             "created_at": time.time(), "last_used": None}
    _save(existing + [entry])
    return plaintext, _public(entry)


def _public(entry: dict[str, Any]) -> dict[str, Any]:
    return {**{k: entry[k] for k in ("id", "name", "created_at", "last_used")},
            "scope": entry.get("scope", "translate")}  # tokens from before Sprint 24 have no scope


def list_tokens() -> list[dict[str, Any]]:
    return [_public(e) for e in _load()]


def revoke(token_id: str) -> bool:
    tokens = _load()
    kept = [e for e in tokens if e["id"] != token_id]
    if len(kept) == len(tokens):
        return False
    _save(kept)
    return True


def verify(plaintext: str) -> dict[str, Any] | None:
    """The public entry for a valid token, else None. Constant-time hash compare."""
    if not plaintext.startswith(_PREFIX):
        return None
    digest = _hash(plaintext)
    tokens = _load()
    for e in tokens:
        if hmac.compare_digest(e["hash"], digest):
            if time.time() - (e.get("last_used") or 0) > 60:  # avoid a write per request
                e["last_used"] = time.time()
                _save(tokens)
            return _public(e)
    return None
