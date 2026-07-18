import hashlib
import hmac
import json
import os
import secrets
import time
from pathlib import Path

import bcrypt
from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, field_validator

router = APIRouter(prefix="/admin", tags=["admin"])
security = HTTPBearer(auto_error=False)

DATA_DIR = Path(os.environ.get("HRDD_DATA_DIR", "/app/data"))
ADMIN_HASH_FILE = DATA_DIR / ".admin_hash"
JWT_SECRET_FILE = DATA_DIR / ".jwt_secret"

DEFAULT_EXPIRY = 24 * 3600  # 24 hours
REMEMBER_EXPIRY = 30 * 24 * 3600  # 30 days


def _get_jwt_secret() -> str:
    if JWT_SECRET_FILE.exists():
        return JWT_SECRET_FILE.read_text().strip()
    secret = secrets.token_hex(32)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    JWT_SECRET_FILE.write_text(secret)
    return secret


def _create_jwt(payload: dict, secret: str) -> str:
    """Minimal JWT implementation (HS256) — no external dependency."""
    import base64

    header = base64.urlsafe_b64encode(
        json.dumps({"alg": "HS256", "typ": "JWT"}).encode()
    ).rstrip(b"=").decode()

    body = base64.urlsafe_b64encode(
        json.dumps(payload).encode()
    ).rstrip(b"=").decode()

    signature_input = f"{header}.{body}".encode()
    sig = hmac.new(secret.encode(), signature_input, hashlib.sha256).digest()
    signature = base64.urlsafe_b64encode(sig).rstrip(b"=").decode()

    return f"{header}.{body}.{signature}"


def _decode_jwt(token: str, secret: str) -> dict | None:
    """Decode and verify JWT. Returns payload or None."""
    import base64

    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None

        signature_input = f"{parts[0]}.{parts[1]}".encode()
        expected_sig = hmac.new(secret.encode(), signature_input, hashlib.sha256).digest()
        expected = base64.urlsafe_b64encode(expected_sig).rstrip(b"=").decode()

        if not hmac.compare_digest(expected, parts[2]):
            return None

        # Decode payload (add padding)
        padded = parts[1] + "=" * (4 - len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))

        if payload.get("exp", 0) < time.time():
            return None

        return payload
    except Exception:
        return None


async def require_admin(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")
    secret = _get_jwt_secret()
    payload = _decode_jwt(credentials.credentials, secret)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return payload


class SetupRequest(BaseModel):
    password: str
    confirm_password: str

    @field_validator("password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


class LoginRequest(BaseModel):
    password: str
    remember_me: bool = False


@router.get("/status")
async def admin_status():
    """Check if admin account exists."""
    return {"setup_complete": ADMIN_HASH_FILE.exists()}


@router.post("/setup")
async def admin_setup(req: SetupRequest):
    """Create admin account (first run only)."""
    if ADMIN_HASH_FILE.exists():
        raise HTTPException(status_code=400, detail="Admin account already exists")

    if req.password != req.confirm_password:
        raise HTTPException(status_code=400, detail="Passwords do not match")

    hashed = bcrypt.hashpw(req.password.encode(), bcrypt.gensalt())
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ADMIN_HASH_FILE.write_bytes(hashed)

    return {"message": "Admin account created"}


@router.post("/login")
async def admin_login(req: LoginRequest):
    """Login with password, returns JWT."""
    if not ADMIN_HASH_FILE.exists():
        raise HTTPException(status_code=400, detail="Admin account not set up")

    stored_hash = ADMIN_HASH_FILE.read_bytes().strip()
    if not bcrypt.checkpw(req.password.encode(), stored_hash):
        raise HTTPException(status_code=401, detail="Invalid password")

    secret = _get_jwt_secret()
    expiry = REMEMBER_EXPIRY if req.remember_me else DEFAULT_EXPIRY
    payload = {
        "sub": "admin",
        "iat": int(time.time()),
        "exp": int(time.time()) + expiry,
    }
    token = _create_jwt(payload, secret)

    return {"token": token, "expires_in": expiry}


@router.get("/verify")
async def admin_verify(admin: dict = Depends(require_admin)):
    """Verify JWT is still valid."""
    return {"valid": True, "sub": admin["sub"]}
