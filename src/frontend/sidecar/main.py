# Copyright (c) 2026 UNI Global Union. All rights reserved. See LICENSE.

import asyncio
import json
import logging
import os
import secrets
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Header, Request
from fastapi.responses import StreamingResponse, FileResponse, Response
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("sidecar")

app = FastAPI(title="UNI Translator Frontend Sidecar", version="2.0.0")

# Load deployment config (generic — behaviour now comes from the pushed
# frontend config, not this file; kept only for the `role` marker).
_config_path = os.environ.get("DEPLOYMENT_JSON_PATH", "/app/config/deployment_frontend.json")
_config: dict[str, Any] = {}
if os.path.exists(_config_path):
    with open(_config_path) as f:
        _config = json.load(f)

# --- Message Queue (in-memory, TTL 300s) ---
MESSAGE_TTL = 300
_queue: list[dict[str, Any]] = []
_queue_lock = asyncio.Lock()

# --- Recovery Requests (in-memory) ---
# token -> {"status": "pending"|"found"|"not_found"|"expired", "data": {...}}
_recovery: dict[str, dict[str, Any]] = {}
_recovery_lock = asyncio.Lock()

# --- SSE Stream Channels ---
# token -> asyncio.Queue of SSE events
_streams: dict[str, asyncio.Queue[dict[str, str]]] = {}
_streams_lock = asyncio.Lock()


class SubmitMessageRequest(BaseModel):
    session_token: str
    content: str
    message_id: str
    timestamp: str
    language: str = "en"
    survey: dict[str, Any] | None = None
    finalize: bool = False
    # Sprint 16: filenames the user is "shipping" with this turn (chips).
    # Backend uses this to log + synthesise file-only user messages.
    attachments: list[str] | None = None


class ChunkRequest(BaseModel):
    event: str  # "token", "done", "error", "queue_position"
    data: str


class RecoveryDataRequest(BaseModel):
    token: str
    status: str  # "found", "not_found", "expired"
    data: dict[str, Any] | None = None


# --- Health & Config ---

@app.get("/internal/health")
async def health():
    return {"status": "ok"}


# --- Branding (app title + logo, pushed by backend, persisted to disk) ---
_branding: dict[str, Any] = {}
_BRANDING_DIR = Path("/app/data/branding")

if (_BRANDING_DIR / "config.json").exists():
    try:
        _branding = json.loads((_BRANDING_DIR / "config.json").read_text())
        logger.info("Loaded branding config from disk")
    except (json.JSONDecodeError, OSError):
        pass


# --- Frontend config (pushed by backend, persisted to disk) — Sprint 21 ---
# A generic frontend starts unconfigured; the backend pushes its config
# (profiles, auth, languages, ...) the same way it pushes branding.
_frontend_config: dict[str, Any] = {}
_FRONTEND_CONFIG_FILE = Path("/app/data/frontend_config.json")
if _FRONTEND_CONFIG_FILE.exists():
    try:
        _frontend_config = json.loads(_FRONTEND_CONFIG_FILE.read_text())
        logger.info("Loaded frontend config from disk")
    except (json.JSONDecodeError, OSError):
        pass


@app.post("/internal/frontend-config")
async def update_frontend_config(data: dict[str, Any]):
    """Backend pushes this frontend's config object."""
    global _frontend_config
    _frontend_config = data
    _FRONTEND_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = _FRONTEND_CONFIG_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    tmp.rename(_FRONTEND_CONFIG_FILE)
    logger.info(f"Frontend config updated: configured={data.get('configured')}")
    return {"status": "ok"}


@app.post("/internal/branding")
async def update_branding(data: dict[str, Any]):
    """Backend pushes branding config (app title + logo) for this frontend."""
    global _branding

    is_custom = data.get("custom", False)
    _branding = data
    _BRANDING_DIR.mkdir(parents=True, exist_ok=True)

    if is_custom:
        cfg_tmp = (_BRANDING_DIR / "config.json").with_suffix(".tmp")
        cfg_tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2))
        cfg_tmp.rename(_BRANDING_DIR / "config.json")
    else:
        # Reset to default — delete the persisted branding
        p = _BRANDING_DIR / "config.json"
        if p.exists():
            p.unlink()
        logger.info("Branding reset to default, file deleted")

    logger.info(f"Branding updated: custom={is_custom}")
    return {"status": "ok"}


@app.get("/internal/config")
async def get_config():
    # Sprint 12: LAIUNI portal config — app language + auth mode + branding.
    cfg = {
        "role": "frontend",
        "configured": bool(_frontend_config.get("configured")),
        "app_language": _frontend_config.get("app_language") or "en",
        "auth_mode": _frontend_config.get("auth_mode", "token"),
    }
    if _branding:
        cfg["branding"] = {
            "app_title": _branding.get("app_title", ""),
            "logo_url": _branding.get("logo_url", ""),
            "custom": _branding.get("custom", False),
            "colors": _branding.get("colors"),
        }
    return cfg


# --- Message Queue ---

@app.post("/internal/queue")
async def enqueue_message(msg: SubmitMessageRequest):
    """React app submits a user message to the queue."""
    async with _queue_lock:
        _queue.append({
            **msg.model_dump(),
            "created_at": time.time(),
        })
    logger.info(f"Enqueued message {msg.message_id} for session {msg.session_token}")
    return {"status": "queued", "message_id": msg.message_id}


@app.get("/internal/queue")
async def dequeue_messages():
    """Backend polls this endpoint to collect pending messages."""
    now = time.time()
    async with _queue_lock:
        # Remove expired messages
        valid = [m for m in _queue if now - m["created_at"] < MESSAGE_TTL]
        _queue.clear()

    # Collect pending recovery requests
    recovery_requests = []
    async with _recovery_lock:
        for token, state in _recovery.items():
            if state["status"] == "pending":
                recovery_requests.append(token)

    # Collect pending auth requests
    auth_requests = []
    async with _auth_lock:
        auth_requests = list(_auth_queue)
        _auth_queue.clear()

    # Collect pending evidence-delete requests (Sprint 16)
    async with _evidence_delete_lock:
        evidence_delete_requests = list(_evidence_delete_queue)
        _evidence_delete_queue.clear()

    # Collect pending translation-job requests (Sprint 5, pull-inverse)
    async with _jobs_lock:
        job_submits = list(_job_submits); _job_submits.clear()
        job_downloads = list(_job_downloads); _job_downloads.clear()
        job_status_requests = list(_job_status_requests); _job_status_requests.clear()

    result: dict[str, Any] = {"messages": valid}
    if recovery_requests:
        result["recovery_requests"] = recovery_requests
        logger.info(f"Recovery requests: {recovery_requests}")
    if auth_requests:
        result["auth_requests"] = auth_requests
        logger.info(f"Auth requests: {len(auth_requests)}")
    if evidence_delete_requests:
        result["evidence_delete_requests"] = evidence_delete_requests
        logger.info(f"Evidence delete requests: {len(evidence_delete_requests)}")
    if job_submits:
        result["job_submits"] = job_submits
    if job_downloads:
        result["job_downloads"] = job_downloads
    if job_status_requests:
        result["job_status_requests"] = job_status_requests

    logger.info(f"Dequeued {len(valid)} messages")
    return result


# --- Session Recovery ---

@app.post("/internal/session/recover")
async def request_recovery(data: dict[str, Any]):
    """React app requests session recovery by token."""
    token = data.get("token", "").strip().upper()
    if not token or "-" not in token:
        raise HTTPException(status_code=400, detail="Invalid token format")

    async with _recovery_lock:
        _recovery[token] = {"status": "pending", "data": None, "created_at": time.time()}

    logger.info(f"Recovery requested for {token}")
    return {"status": "pending", "token": token}


@app.get("/internal/session/{token}/recover")
async def get_recovery_status(token: str):
    """React app polls this to check if recovery data is ready."""
    async with _recovery_lock:
        state = _recovery.get(token)

    if not state:
        raise HTTPException(status_code=404, detail="No recovery request for this token")

    if state["status"] == "pending":
        return {"status": "pending"}

    # Recovery resolved — clean up and return
    async with _recovery_lock:
        _recovery.pop(token, None)

    return {"status": state["status"], "data": state.get("data")}


@app.post("/internal/session/{token}/recovery-data")
async def push_recovery_data(token: str, req: RecoveryDataRequest):
    """Backend pushes recovery result (found/not_found/expired + session data)."""
    async with _recovery_lock:
        if token in _recovery:
            _recovery[token] = {
                "status": req.status,
                "data": req.data,
                "created_at": _recovery[token].get("created_at", time.time()),
            }
            logger.info(f"Recovery data pushed for {token}: {req.status}")
        else:
            logger.warning(f"Recovery data for {token} but no pending request")

    # Auto-clean after 60s
    async def _cleanup():
        await asyncio.sleep(60)
        async with _recovery_lock:
            _recovery.pop(token, None)
    asyncio.create_task(_cleanup())

    return {"status": "ok"}


# --- SSE Streaming ---

async def _get_or_create_stream(token: str) -> asyncio.Queue[dict[str, str]]:
    async with _streams_lock:
        if token not in _streams:
            _streams[token] = asyncio.Queue()
        return _streams[token]


@app.post("/internal/stream/{session_token}/chunk")
async def push_chunk(session_token: str, chunk: ChunkRequest):
    """Backend pushes response chunks (tokens) to the stream."""
    q = await _get_or_create_stream(session_token)
    await q.put({"event": chunk.event, "data": chunk.data})

    # Clean up stream on terminal events
    if chunk.event in ("done", "error"):
        # Give SSE consumer time to read, then clean up
        async def _cleanup():
            await asyncio.sleep(5)
            async with _streams_lock:
                _streams.pop(session_token, None)
        asyncio.create_task(_cleanup())

    return {"status": "ok"}


@app.get("/internal/stream/{session_token}")
async def stream_sse(session_token: str):
    """React app opens EventSource here to receive response tokens via SSE."""
    q = await _get_or_create_stream(session_token)

    async def event_generator():
        while True:
            try:
                event = await asyncio.wait_for(q.get(), timeout=30.0)
                # SSE multi-line: each line needs its own "data:" prefix
                lines = event['data'].split('\n')
                data_block = '\n'.join(f"data: {line}" for line in lines)
                yield f"event: {event['event']}\n{data_block}\n\n"
                if event["event"] in ("done", "error"):
                    break
            except asyncio.TimeoutError:
                # Send keepalive comment to prevent connection timeout
                yield ": keepalive\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# --- Auth Requests (pull-inverse: sidecar queues, backend resolves) ---
# session_token -> {"status": "pending"|"code_sent"|..., "email": str, ...}
_auth_requests: dict[str, dict[str, Any]] = {}
_auth_queue: list[dict[str, Any]] = []
_auth_lock = asyncio.Lock()


class AuthCodeRequest(BaseModel):
    session_token: str
    email: str
    language: str = "en"


class AuthVerifyRequest(BaseModel):
    session_token: str
    code: str
    language: str = "en"


class AuthResultRequest(BaseModel):
    session_token: str
    status: str  # "code_sent", "verified", "invalid_code", "not_authorized", "smtp_error", "smtp_not_configured"
    email: str = ""
    token: str = ""  # Sprint 5: user bearer token, present when status == "verified"
    scheduling: dict[str, Any] | None = None  # Sprint 13: {mode: scheduled|immediate|both}, on "verified"


@app.post("/internal/auth/request-code")
async def request_auth_code(req: AuthCodeRequest):
    """React app requests an auth code — queued for backend to process."""
    async with _auth_lock:
        _auth_requests[req.session_token] = {
            "status": "pending",
            "email": req.email,
            "created_at": time.time(),
        }
        _auth_queue.append({
            "session_token": req.session_token,
            "email": req.email,
            "language": req.language,
        })
    logger.info(f"Auth code requested for {req.email} (session {req.session_token})")
    return {"status": "pending"}


@app.post("/internal/auth/verify-code")
async def verify_auth_code(req: AuthVerifyRequest):
    """React app submits a code for verification — queued for backend."""
    async with _auth_lock:
        _auth_requests[req.session_token] = {
            "status": "verifying",
            "email": _auth_requests.get(req.session_token, {}).get("email", ""),
            "created_at": time.time(),
        }
        _auth_queue.append({
            "session_token": req.session_token,
            "code": req.code,
            "email": _auth_requests.get(req.session_token, {}).get("email", ""),
            "language": req.language,
        })
    logger.info(f"Auth code verification for session {req.session_token}")
    return {"status": "verifying"}


@app.get("/internal/auth/status/{session_token}")
async def get_auth_status(session_token: str):
    """React app polls this to check auth result."""
    async with _auth_lock:
        state = _auth_requests.get(session_token)
    if not state:
        return {"status": "none"}
    return {"status": state["status"], "email": state.get("email", ""), "token": state.get("token", "")}


@app.post("/internal/auth/{session_token}/result")
async def push_auth_result(session_token: str, req: AuthResultRequest):
    """Backend pushes auth result (code_sent, verified, rejected, etc.)."""
    async with _auth_lock:
        if session_token in _auth_requests:
            _auth_requests[session_token]["status"] = req.status
            if req.email:
                _auth_requests[session_token]["email"] = req.email
            if req.token:
                _auth_requests[session_token]["token"] = req.token
            if req.scheduling is not None:
                _auth_requests[session_token]["scheduling"] = req.scheduling
            logger.info(f"Auth result for {session_token}: {req.status}")
        else:
            logger.warning(f"Auth result for {session_token} but no pending request")

    # Auto-clean after 5 minutes
    async def _cleanup():
        await asyncio.sleep(300)
        async with _auth_lock:
            _auth_requests.pop(session_token, None)
    asyncio.create_task(_cleanup())

    return {"status": "ok"}


# --- File Upload ---
# Temp storage for uploads until backend fetches them
UPLOAD_MAX_SIZE = 25 * 1024 * 1024  # 25MB
ALLOWED_EXTENSIONS = {".pdf", ".txt", ".md", ".doc", ".docx", ".jpg", ".jpeg", ".png"}
_upload_dir = Path(tempfile.mkdtemp(prefix="laiuni_uploads_"))
_upload_queue: list[dict[str, str]] = []
_upload_queue_lock = asyncio.Lock()


@app.post("/internal/upload/{session_token}")
async def upload_file(session_token: str, file: UploadFile = File(...)):
    """React app uploads a file for the session."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"File type {ext} not allowed. Accepted: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    # Read and check size
    content = await file.read()
    if len(content) > UPLOAD_MAX_SIZE:
        raise HTTPException(status_code=400, detail=f"File too large. Maximum: {UPLOAD_MAX_SIZE // (1024*1024)}MB")

    # Save to temp directory
    session_dir = _upload_dir / session_token
    session_dir.mkdir(parents=True, exist_ok=True)
    file_path = session_dir / file.filename
    file_path.write_bytes(content)

    # Queue upload notification for backend
    async with _upload_queue_lock:
        _upload_queue.append({
            "session_token": session_token,
            "filename": file.filename,
            "size": len(content),
            "created_at": time.time(),
        })

    logger.info(f"Upload received: {file.filename} ({len(content)} bytes) for {session_token}")
    return {"status": "uploaded", "filename": file.filename, "size": len(content)}


@app.get("/internal/upload/{session_token}/{filename}")
async def get_upload(session_token: str, filename: str):
    """Backend fetches the uploaded file."""
    file_path = _upload_dir / session_token / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(file_path)


@app.delete("/internal/upload/{session_token}/{filename}")
async def delete_upload(session_token: str, filename: str):
    """Backend confirms receipt — sidecar deletes temp file."""
    file_path = _upload_dir / session_token / filename
    if file_path.exists():
        file_path.unlink()
        logger.info(f"Upload cleaned: {filename} for {session_token}")

    # Clean empty session dir
    session_dir = _upload_dir / session_token
    if session_dir.exists() and not list(session_dir.iterdir()):
        session_dir.rmdir()

    return {"status": "deleted"}


@app.get("/internal/uploads")
async def list_pending_uploads():
    """Backend polls for pending uploads (alongside message queue)."""
    async with _upload_queue_lock:
        uploads = list(_upload_queue)
        _upload_queue.clear()
    return {"uploads": uploads}


# --- Evidence Deletion (Sprint 16 — Claude-Style retraction) ---
# Queue of pending evidence-delete requests {token, filename}.
# Drained by the backend on its next /internal/queue poll.
_evidence_delete_queue: list[dict[str, str]] = []
_evidence_delete_lock = asyncio.Lock()


@app.delete("/internal/evidence/{session_token}/{filename}")
async def request_evidence_delete(session_token: str, filename: str):
    """React app retracts a previously uploaded file.

    Enqueues the deletion for the backend to handle on its next poll.
    Returns 202 immediately. The frontend optimistically removes the chip
    and waits for an `evidence_deleted` SSE event for confirmation (or
    `evidence_delete_error` for failure).
    """
    if not filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    async with _evidence_delete_lock:
        _evidence_delete_queue.append({
            "token": session_token,
            "filename": filename,
        })
    logger.info(f"Evidence delete queued: {filename} for {session_token}")
    return {"status": "queued"}


# ===========================================================================
# LAIUNI Translator — user-facing API (Sprint 5, SPEC §4.1; pull-inverse)
# The browser hits these; the backend fulfils them over /internal/queue.
# ===========================================================================

# ref -> latest status pushed by backend; ref -> result zip; drained request lists.
_jobs: dict[str, dict[str, Any]] = {}
_artifacts: dict[str, bytes] = {}
_job_submits: list[dict[str, Any]] = []
_job_downloads: list[dict[str, Any]] = []
_job_status_requests: list[dict[str, Any]] = []
_jobs_lock = asyncio.Lock()

# Languages/format catalogue — persisted to disk so it survives a sidecar restart
# (it's fixed config, pushed by the backend only when the glossary changes; the
# sidecar must not depend on a re-push at every startup).
_LANGUAGES_FILE = Path("/app/data/languages.json")
_languages: dict[str, Any] = {}
if _LANGUAGES_FILE.exists():
    try:
        _languages = json.loads(_LANGUAGES_FILE.read_text())
        logger.info(f"Loaded languages catalogue from disk ({len(_languages.get('languages', []))} langs)")
    except (json.JSONDecodeError, OSError):
        pass

_AUTH_TERMINAL = ("verified", "invalid_code", "not_authorized", "smtp_error", "smtp_not_configured")


def _bearer(authorization: str) -> str:
    return authorization[7:] if authorization[:7].lower() == "bearer " else authorization


async def _wait_for(getter, timeout: float = 15.0, interval: float = 0.3):
    """Poll a getter until it returns something truthy or the timeout elapses."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        v = getter()
        if v:
            return v
        await asyncio.sleep(interval)
    return getter()


# --- Auth (magic-code; session_token = email — one active code per email) ---

class RequestTokenRequest(BaseModel):
    email: str
    language: str = "en"


class VerifyRequest(BaseModel):
    email: str
    code: str
    language: str = "en"


@app.post("/request-token")
async def request_token(req: RequestTokenRequest):
    """Ask for a magic code. Generic response — no user enumeration (SPEC §8).

    In **email-only** mode (§12.5) a whitelisted email is enough: the backend
    resolves the request straight to a token, so this waits for the result and
    returns `{token}` (or 401). Weaker by design — a per-frontend choice."""
    st = req.email.lower().strip()
    async with _auth_lock:
        _auth_requests[st] = {"status": "pending", "email": st, "created_at": time.time()}
        _auth_queue.append({"session_token": st, "email": st, "language": req.language})
    logger.info(f"request-token for {st}")

    if _frontend_config.get("auth_mode") != "email-only":
        return {"ok": True}

    def _resolved():
        s = _auth_requests.get(st, {})
        return s if s.get("status") in _AUTH_TERMINAL else None

    state = await _wait_for(_resolved)
    if state and state.get("status") == "verified" and state.get("token"):
        return {"token": state["token"], "scheduling": state.get("scheduling")}
    raise HTTPException(status_code=401, detail="not_authorized")


@app.post("/verify")
async def verify(req: VerifyRequest):
    """Submit the code; on success return the bearer token (SPEC §3.1)."""
    st = req.email.lower().strip()
    async with _auth_lock:
        _auth_requests.setdefault(st, {"email": st, "created_at": time.time()})
        _auth_requests[st]["status"] = "verifying"
        _auth_queue.append({"session_token": st, "code": req.code, "email": st, "language": req.language})

    def _resolved():
        s = _auth_requests.get(st, {})
        return s if s.get("status") in _AUTH_TERMINAL else None

    state = await _wait_for(_resolved)
    if state and state.get("status") == "verified" and state.get("token"):
        return {"token": state["token"], "scheduling": state.get("scheduling")}
    raise HTTPException(status_code=401, detail="invalid_code")


# --- Jobs ---

@app.post("/jobs")
async def submit_job(
    file: UploadFile = File(...),
    source_lang: str = Form("en"),
    target_langs: str = Form(...),   # JSON list or comma-separated codes
    glossary: str = Form(""),
    mode: str = Form("scheduled"),
    options: str = Form("{}"),       # JSON: per-job document options (§13.2)
    authorization: str = Header(default=""),
):
    """Upload one file + params. The backend detects tier, estimates, enqueues."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")
    content = await file.read()
    if len(content) > UPLOAD_MAX_SIZE:
        raise HTTPException(status_code=400, detail=f"File too large. Max {UPLOAD_MAX_SIZE // (1024*1024)}MB")

    ref = secrets.token_urlsafe(12)
    session_dir = _upload_dir / ref
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / file.filename).write_bytes(content)

    raw = target_langs.strip()
    langs = json.loads(raw) if raw.startswith("[") else [x.strip() for x in raw.split(",") if x.strip()]
    try:
        opts = json.loads(options) if options else {}
    except json.JSONDecodeError:
        opts = {}

    async with _jobs_lock:
        _job_submits.append({
            "ref": ref, "token": _bearer(authorization), "filename": file.filename,
            "source_lang": source_lang, "target_langs": langs,
            "glossary": glossary, "mode": mode, "options": opts,
        })
    logger.info(f"Job submit queued ref={ref} file={file.filename} langs={langs}")
    state = await _wait_for(lambda: _jobs.get(ref))
    return state or {"ref": ref, "status": "pending"}


@app.get("/jobs/{ref}")
async def job_status(ref: str, authorization: str = Header(default="")):
    """Latest status for a job (owner-scoped by the backend)."""
    async with _jobs_lock:
        _job_status_requests.append({"ref": ref, "token": _bearer(authorization)})
    return _jobs.get(ref, {"ref": ref, "status": "pending"})


@app.get("/jobs/{ref}/download")
async def job_download(ref: str, authorization: str = Header(default="")):
    """Download the result zip — backend pushes it; served only while valid."""
    async with _jobs_lock:
        _job_downloads.append({"ref": ref, "token": _bearer(authorization)})
    data = await _wait_for(lambda: _artifacts.get(ref), timeout=30.0)
    if not data:
        raise HTTPException(status_code=404, detail="Not available (not done, expired, or not owner)")
    async with _jobs_lock:
        _artifacts.pop(ref, None)  # one-shot
    return Response(
        content=data, media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="translations-{ref}.zip"'},
    )


@app.get("/d/{token}")
async def signed_download(token: str):
    """Emailed result link: the signed token authenticates (no browser bearer).
    The backend verifies it, enforces single use, and pushes the zip keyed by the
    token; an invalid/expired/already-used link yields nothing → 404."""
    async with _jobs_lock:
        _job_downloads.append({"token": token, "signed": True})
    data = await _wait_for(lambda: _artifacts.get(token), timeout=30.0)
    if not data:
        raise HTTPException(status_code=404, detail="This link is invalid, expired, or already used.")
    async with _jobs_lock:
        _artifacts.pop(token, None)  # one-shot
    return Response(
        content=data, media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="translations.zip"'},
    )


@app.get("/languages")
async def languages():
    """The 17 target languages + format tiers (pushed by the backend)."""
    return _languages or {"languages": [], "formats": []}


# --- Internal: backend pushes results here (pull-inverse) ---

@app.post("/internal/jobs/{ref}/status")
async def push_job_status(ref: str, body: dict[str, Any]):
    async with _jobs_lock:
        _jobs[ref] = body
    return {"status": "ok"}


@app.post("/internal/jobs/{ref}/artifact")
async def push_job_artifact(ref: str, request: Request):
    data = await request.body()
    async with _jobs_lock:
        _artifacts[ref] = data
    logger.info(f"Artifact received for {ref} ({len(data)} bytes)")
    return {"status": "ok"}


@app.post("/internal/languages")
async def push_languages(body: dict[str, Any]):
    """Backend pushes the languages/format catalogue (on first contact and when
    the glossary changes). Persisted so it survives sidecar restarts."""
    global _languages
    _languages = body
    _LANGUAGES_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = _LANGUAGES_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(body, ensure_ascii=False, indent=2))
    tmp.rename(_LANGUAGES_FILE)
    logger.info(f"Languages catalogue received ({len(body.get('languages', []))} langs), persisted")
    return {"status": "ok"}
