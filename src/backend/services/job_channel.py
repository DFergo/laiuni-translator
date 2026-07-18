"""Job transport over the pull-inverse channel (Sprint 5, SPEC §3.2/§4.1; ADR-009).

The browser talks only to the frontend **sidecar**; the backend never accepts
inbound connections. So job submit / status / download are queued on the sidecar
and fulfilled here, on the same poll the backend already runs for auth+branding
(`polling.poll_frontends`). This module is the backend half:

  - `handle_job_requests(...)` drains the sidecar's `job_submits` / `job_downloads`
    from the `/internal/queue` response and fulfils each;
  - `push_statuses(...)` pushes live status for the jobs the browser is polling.

Everything is owner-scoped by the user bearer token (`user_tokens`). Downloads
are served by the backend **pushing** the result zip to the sidecar (the backend
holds the files; the sidecar has none) — the deliberate consequence of "backend
never inbound".
"""

import io
import json
import logging
import time
import zipfile
from pathlib import Path
from typing import Any

import httpx

from src.core.paths import DATA_DIR, DOCUMENTS_DIR
from src.services import job_queue as jq
from src.services.user_tokens import verify_user_token, verify_download_token

logger = logging.getLogger("backend.jobchannel")

# Statuses whose status the browser still cares about (pushed each poll).
_LIVE_STATUSES = ("queued", "scheduled", "running", "done", "failed")

# Single-use ledger for emailed download links (Sprint 12): {jti: exp}. Persisted
# so a redeemed link stays dead across a backend restart; pruned by expiry.
_REDEEMED_FILE = DATA_DIR / "redeemed_downloads.json"


def _load_redeemed() -> dict[str, float]:
    try:
        return json.loads(_REDEEMED_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _is_redeemed(jti: str) -> bool:
    return jti in _load_redeemed()


def _mark_redeemed(jti: str, exp: float) -> None:
    now = time.time()
    ledger = {j: e for j, e in _load_redeemed().items() if e > now}  # prune expired
    ledger[jti] = exp
    _REDEEMED_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = _REDEEMED_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(ledger))
    tmp.rename(_REDEEMED_FILE)


def _authorize(token: str, fid: str) -> dict[str, Any] | None:
    """Valid user token whose frontend matches the one being served. Enforcing
    ``fid`` stops a token minted on frontend A being replayed on frontend B
    (which may have a different whitelist)."""
    payload = verify_user_token(token)
    if not payload or payload.get("fid", "") != fid:
        return None
    return payload


def _status_payload(job: dict[str, Any]) -> dict[str, Any]:
    """The GET /jobs/{ref} contract (SPEC §4.1)."""
    return {
        "ref": job["client_ref"],
        "job_id": job["id"],
        "status": job["status"],
        "progress": job["progress"],
        "estimate_s": job["estimate_s"],
        "run_at": job["run_at"],
        "langs_done": job["progress"].get("langs_done", []),
        "error": job["error"],
    }


async def _push_status(client: httpx.AsyncClient, url: str, ref: str, payload: dict[str, Any]):
    try:
        await client.post(f"{url}/internal/jobs/{ref}/status", json=payload)
    except Exception as e:
        logger.debug(f"status push failed for {ref}: {e}")


async def _handle_submit(client: httpx.AsyncClient, url: str, fid: str, req: dict[str, Any]):
    """Validate the token, fetch the uploaded file, tier-detect, estimate, enqueue."""
    ref = req.get("ref", "")
    if not ref:
        return
    payload = _authorize(req.get("token", ""), fid)
    if not payload:
        await _push_status(client, url, ref, {"ref": ref, "status": "error", "error": "unauthorized"})
        return

    filename = Path(req.get("filename", "")).name
    tier = jq.detect_tier(filename)
    if tier is None:
        await _push_status(client, url, ref, {"ref": ref, "status": "rejected",
                                              "error": f"unsupported format: {Path(filename).suffix}"})
        return

    # Fetch the uploaded bytes from the sidecar (existing upload channel).
    try:
        resp = await client.get(f"{url}/internal/upload/{ref}/{filename}")
        resp.raise_for_status()
        data = resp.content
    except Exception as e:
        await _push_status(client, url, ref, {"ref": ref, "status": "error", "error": f"upload fetch failed: {e}"})
        return

    # Stage the original, enqueue (needs a path for the char count), then move it
    # into the job dir and repoint the job so retention cleans everything. Any
    # failure here (e.g. a corrupt/unreadable docx/pptx — extract runs during the
    # char count) is reported as `rejected`, never left hanging as `pending`.
    target_langs = req.get("target_langs") or []
    try:
        staging = DOCUMENTS_DIR / "_staging" / ref
        staging.mkdir(parents=True, exist_ok=True)
        staged_file = staging / filename
        staged_file.write_bytes(data)
        job = jq.enqueue(
            payload["sub"], req.get("source_lang", "en"), target_langs, tier, str(staged_file),
            frontend_id=fid, client_ref=ref, glossary=req.get("glossary", ""),
            mode=req.get("mode", "scheduled"),
        )
        job_dir = DOCUMENTS_DIR / job["id"]
        job_dir.mkdir(parents=True, exist_ok=True)
        final_path = job_dir / filename
        staged_file.replace(final_path)
        jq.assign_path(job["id"], str(final_path))
        try:
            staging.rmdir()
        except OSError:
            pass
    except Exception as e:
        logger.warning(f"Job submit failed ref={ref}: {e}")
        await _push_status(client, url, ref, {"ref": ref, "status": "rejected",
                                              "error": f"could not read the file (corrupt or unsupported): {e}"})
        return

    result = _status_payload(jq.get(job["id"]))
    if tier == "tier3":
        result["warning"] = "experimental: .pptx recomposition may fail (post-MVP)"
    await _push_status(client, url, ref, result)
    # Tell the sidecar to drop the temp upload.
    try:
        await client.delete(f"{url}/internal/upload/{ref}/{filename}")
    except Exception:
        pass
    logger.info(f"Job accepted ref={ref} job_id={job['id']} tier={tier} langs={len(target_langs)}")


async def _push_artifact(client: httpx.AsyncClient, url: str, key: str, job: dict[str, Any]) -> bool:
    """Zip the job's files and push them to the sidecar keyed by ``key`` (the
    browser ref for a live download, or the signed token for an email link).
    Returns True if an artifact was pushed."""
    job_dir = DOCUMENTS_DIR / job["id"]
    files = [p for p in job_dir.iterdir() if p.is_file()] if job_dir.exists() else []
    if not files:
        return False
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in files:
            zf.write(p, arcname=p.name)
    try:
        await client.post(f"{url}/internal/jobs/{key}/artifact",
                          content=buf.getvalue(),
                          headers={"Content-Type": "application/zip"})
        logger.info(f"Pushed download artifact ({len(files)} files)")
        return True
    except Exception as e:
        logger.error(f"artifact push failed: {e}")
        return False


async def _handle_signed_download(client: httpx.AsyncClient, url: str, fid: str, req: dict[str, Any]):
    """Fulfil an emailed download link: verify the signed token, enforce single
    use, then push the zip keyed by the token (the sidecar waits on it). On any
    failure nothing is pushed — the sidecar's /d/{token} 404s after its timeout."""
    token = req.get("token", "")
    payload = verify_download_token(token)  # checks signature + exp
    if not payload or payload.get("fid", "") != fid:
        return
    jti = payload.get("jti", "")
    if not jti or _is_redeemed(jti):
        return
    job = jq.get_by_ref(fid, payload.get("ref", ""))
    if not job or job["owner_email"] != payload["sub"] or job["status"] != "done":
        return
    if await _push_artifact(client, url, token, job):
        _mark_redeemed(jti, payload.get("exp", time.time()))


async def _handle_download(client: httpx.AsyncClient, url: str, fid: str, req: dict[str, Any]):
    """Zip the job's files and push them to the sidecar — only for the owner,
    only while ``done`` and not expired (SPEC §4.1/§8). Signed email-link
    downloads take the token-authenticated path instead."""
    if req.get("signed"):
        await _handle_signed_download(client, url, fid, req)
        return

    ref = req.get("ref", "")
    payload = _authorize(req.get("token", ""), fid)
    job = jq.get_by_ref(fid, ref) if ref else None
    if not payload or not job or job["owner_email"] != payload["sub"]:
        await _push_status(client, url, ref, {"ref": ref, "status": "error", "error": "unauthorized"})
        return
    if job["status"] != "done":
        await _push_status(client, url, ref, {"ref": ref, "status": job["status"], "error": "not ready"})
        return

    if not await _push_artifact(client, url, ref, job):
        await _push_status(client, url, ref, {"ref": ref, "status": "expired", "error": "no files"})


async def push_statuses(client: httpx.AsyncClient, url: str, fid: str, requests: list[dict[str, Any]]):
    """Push current status for the refs the browser is polling — owner-scoped."""
    for req in requests:
        ref = req.get("ref", "")
        payload = _authorize(req.get("token", ""), fid)
        job = jq.get_by_ref(fid, ref) if ref else None
        if not job:
            continue
        if not payload or job["owner_email"] != payload["sub"]:
            await _push_status(client, url, ref, {"ref": ref, "status": "error", "error": "unauthorized"})
            continue
        await _push_status(client, url, ref, _status_payload(job))


async def handle_job_requests(client: httpx.AsyncClient, url: str, data: dict[str, Any], fid: str):
    """Fulfil job submit/download/status requests drained from the sidecar."""
    for req in data.get("job_submits", []):
        await _handle_submit(client, url, fid, req)
    for req in data.get("job_downloads", []):
        await _handle_download(client, url, fid, req)
    status_requests = data.get("job_status_requests", [])
    if status_requests:
        await push_statuses(client, url, fid, status_requests)


def build_languages_payload(frontend_id: str = "") -> dict[str, Any]:
    """The GET /languages contract (SPEC §4.1): offered languages + format tiers.

    The offered languages are **read from the glossary** (§12.3 / ADR-015): the
    union of languages present across the base glossary's terms, named via
    ``core/languages``; the full 17 are the fallback when the glossary is empty
    or unreadable. Not per-frontend, never hardcoded to a count. (``frontend_id``
    is accepted for call-site stability but does not narrow the set.)"""
    from src.core.config import config
    from src.core.languages import LANGUAGES
    present: set[str] = set()
    try:
        from src.api.v1.admin.knowledge import load_glossary
        for term in load_glossary().get("terms", []):
            present |= set((term.get("translations") or {}).keys())
    except Exception as e:
        logger.debug(f"glossary language read failed: {e}")
    codes = [c for c in LANGUAGES if c in present] or list(LANGUAGES)  # fallback: full 17
    ext_tier = {ext: tier for tier, exts in config.supported_formats.items() for ext in exts}
    return {
        "languages": [{"code": c, "name": LANGUAGES[c]} for c in codes],
        "formats": [{"ext": ext, "tier": tier} for ext, tier in sorted(ext_tier.items())],
    }
