"""Machine translation API (Sprint 22, SPEC §16, ADR-024).

Scripts and skills on the tailnet call this with an API token (not the admin
login). Synchronous text translation (`/translate`) and asynchronous file jobs
(`/jobs`) reuse the normal translation loop, connection registry and job queue.
Never logs document content (lesson #16).
"""

import io
import logging
import re
import secrets
import shutil
import time
import zipfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from src.core.languages import LANGUAGES
from src.core.paths import DOCUMENTS_DIR
from src.services import api_tokens, job_queue as jq, llm_usage

logger = logging.getLogger("backend.machine_api")

router = APIRouter(prefix="/api/v1", tags=["machine-api"])
_bearer = HTTPBearer(auto_error=False, description="API token created in Admin → API tokens (`lt_…`)")


async def require_api_token(creds: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> dict[str, Any]:
    entry = api_tokens.verify(creds.credentials) if creds else None
    if not entry:
        raise HTTPException(status_code=401, detail="Invalid or missing API token",
                            headers={"WWW-Authenticate": "Bearer"})
    return entry


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _check_lang(code: str, field: str) -> str:
    code = (code or "").lower().strip()
    if code not in LANGUAGES:
        raise HTTPException(status_code=422, detail=f"{field}: '{code}' is not one of {sorted(LANGUAGES)}")
    return code


def _check_frontend(frontend_id: str) -> str:
    if frontend_id:
        from src.services.frontend_registry import registry
        if not registry.get(frontend_id):
            raise HTTPException(status_code=404, detail=f"Unknown frontend_id '{frontend_id}'")
    return frontend_id


def _check_connection(connection_id: str | None) -> dict[str, Any] | None:
    if not connection_id:
        return None
    from src.services.connection_registry import connections
    conn = connections.get(connection_id)
    if not conn or not conn.get("enable", True):
        raise HTTPException(status_code=404, detail=f"Unknown or disabled connection_id '{connection_id}'")
    return conn


def _model_for(conn: dict[str, Any] | None, model: str | None) -> str | None:
    """An explicit ``model`` wins. With a per-request connection and no model, the
    slot's model belongs to a different provider, so use the connection's first
    allow-listed model (falling back to the slot model if it lists none)."""
    if model or not conn:
        return model
    ids = conn.get("model_ids") or []
    return ids[0] if ids else None


# ---------------------------------------------------------------------------
# Markdown guarantees (SPEC §16.3)
# ---------------------------------------------------------------------------

_FRONTMATTER = re.compile(r"\A(---[ \t]*\r?\n.*?\r?\n---[ \t]*(?:\r?\n|\Z))", re.DOTALL)
_WIKILINK = re.compile(r"\[\[[^\]\n]+\]\]")
_URL = re.compile(r"https?://[^\s)>\]\"']+")
_FENCE = re.compile(r"^(```|~~~).*?^\1[ \t]*$", re.DOTALL | re.MULTILINE)


def split_frontmatter(text: str) -> tuple[str, str]:
    """``(frontmatter, body)``; frontmatter is '' when the text has none."""
    m = _FRONTMATTER.match(text)
    return (m.group(1), text[m.end():]) if m else ("", text)


def preservation_warnings(source: str, output: str) -> list[str]:
    """Differences in wikilinks, URLs and fenced code blocks between source and
    output. Reported, never repaired — the API does not silently edit model output."""
    warnings = []
    for label, rx in (("wikilink", _WIKILINK), ("URL", _URL), ("code block", _FENCE)):
        src, out = sorted(m.group(0) for m in rx.finditer(source)), sorted(m.group(0) for m in rx.finditer(output))
        if src != out:
            missing = [x for x in src if x not in out]
            warnings.append(f"{label}s differ from the source ({len(missing)} missing or altered of {len(src)})")
    return warnings


async def _detect_language(text: str, chain: list[dict[str, Any]]) -> str:
    from src.services.llm_provider import llm
    reply = await llm.chat_with_fallback(
        [{"role": "system", "content": "Identify the language of the user's text. Reply with only its "
                                       "ISO 639-1 code (two lowercase letters). Nothing else."},
         {"role": "user", "content": text[:1500]}], chain)
    from src.services.document_translator import _strip_think
    code = _strip_think(reply).strip().lower()[:2]
    return code if code.isalpha() and len(code) == 2 else "en"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class TranslateRequest(BaseModel):
    text: str = Field(description="Markdown or plain text. YAML frontmatter is returned untouched.")
    target_lang: str = Field(description="One of the codes from `GET /api/v1/languages`.")
    source_lang: str | None = Field(None, description="Omit to auto-detect.")
    frontend_id: str = Field("", description="Apply this frontend's glossary, prompts and LLM slot. Empty = global.")
    connection_id: str | None = Field(None, description="Use this connection for this request only. "
                                      "Without `model`, its first allow-listed model is used.")
    model: str | None = None
    glossary: str = Field("", description="Extra terms for this request, one `source = target` per line "
                          "(wins over the frontend/base glossary).")


class TranslateResponse(BaseModel):
    translated_text: str
    source_lang: str
    target_lang: str
    model: str
    glossary_applied: int = Field(description="Glossary terms (base, frontend and request) found in the source text.")
    usage: dict[str, int]
    warnings: list[str]


class JobCreated(BaseModel):
    job_id: str
    status: str
    estimate_s: int
    duplicate: bool = Field(False, description="True when an identical job (same file, languages, frontend, "
                            "glossary) was still active; its id is returned and nothing new was queued. "
                            "Send `force=true` to queue it anyway.")


class JobFile(BaseModel):
    name: str
    kind: str = Field(description="source | translation")
    lang: str | None = Field(None, description="Target language of a translation file.")
    size: int


class JobSummary(BaseModel):
    job_id: str
    filename: str
    status: str
    progress: float
    source_lang: str
    target_langs: list[str]
    frontend_id: str
    created_at: float
    expires_at: float | None = Field(None, description="Files and record are deleted after this time.")
    files: list[JobFile] = Field(default_factory=list, description="Only when status is done.")


class JobStatus(BaseModel):
    job_id: str
    status: str = Field(description="queued | scheduled | running | done | failed | cancelled")
    progress: float = Field(description="Overall progress 0–1 (translated units across all target languages).")
    total_langs: int
    langs_done: list[str]
    error: str | None = None
    expires_at: float | None = None
    files: list[JobFile] = Field(default_factory=list, description="Only when status is done.")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/frontends", summary="Frontends you can pass as `frontend_id`")
async def frontends(_: dict = Depends(require_api_token)):
    from src.services.frontend_registry import registry
    return {"frontends": [{"id": f["id"], "name": f.get("name", ""), "enabled": f.get("enabled", True)}
                          for f in registry.list_all()]}


@router.get("/connections", summary="Connections you can pass as `connection_id` (no keys or URLs)")
async def list_connections(_: dict = Depends(require_api_token)):
    from src.services.connection_registry import connections, capacity
    return {"connections": [{"id": c["id"], "type": c["type"], "models": c.get("model_ids") or [],
                             "enabled": c.get("enable", True), "parallel": bool(c.get("parallel")),
                             "max_concurrent": capacity(c)} for c in connections.all()]}


@router.get("/languages", summary="Accepted language codes")
async def languages(_: dict = Depends(require_api_token)):
    return {"languages": [{"code": c, "name": n} for c, n in LANGUAGES.items()]}


@router.post("/translate", response_model=TranslateResponse, summary="Translate text (synchronous)")
async def translate_text(req: TranslateRequest, _: dict = Depends(require_api_token)):
    from src.api.v1.admin.knowledge import resolve_glossary
    from src.api.v1.admin.llm import get_llm_settings
    from src.services.document_translator import _resolve_chain, translate
    from src.services.glossary_slice import slice_glossary

    target = _check_lang(req.target_lang, "target_lang")
    source = _check_lang(req.source_lang, "source_lang") if req.source_lang else None
    fid = _check_frontend(req.frontend_id)
    conn = _check_connection(req.connection_id)
    model = _model_for(conn, req.model)

    frontmatter, body = split_frontmatter(req.text)
    if not body.strip():
        return TranslateResponse(translated_text=req.text, source_lang=source or "en", target_lang=target,
                                 model="", glossary_applied=0, usage={}, warnings=[])

    job_key = "api-" + secrets.token_hex(6)  # attributes LLM usage; its scratch dir is removed below
    token = llm_usage.current_job.set(job_key)
    try:
        chain = _resolve_chain(req.connection_id, model, fid)
        if not chain or not chain[0].get("connection_id"):
            raise HTTPException(status_code=503, detail="No translation connection is configured")
        if not source:
            source = await _detect_language(body, chain)
        ir = {"format": "md", "source_path": "", "text": body}
        await translate(ir, source, [target], req.glossary, req.connection_id, model, fid)
        out_body = ir["doc_out"][target]
        usage = llm_usage.job_summary(job_key)
    except HTTPException:
        raise
    except Exception as e:  # LLM/provider failure — message only, never the text
        logger.error(f"API translate failed: {e}")
        raise HTTPException(status_code=502, detail=f"Translation failed: {e}")
    finally:
        llm_usage.current_job.reset(token)
        shutil.rmtree(DOCUMENTS_DIR / job_key, ignore_errors=True)

    glossary_on = get_llm_settings(fid).get("translation_glossary_enabled", True)
    applied = len(slice_glossary(body, source, target, req.glossary,
                                 base_terms=resolve_glossary(fid))) if glossary_on else 0
    totals = {k: sum(int(c.get(k, 0)) for c in usage.values())
              for k in ("calls", "prompt_tokens", "cached_tokens", "completion_tokens", "reasoning_tokens")}
    logger.info(f"API translate {source}→{target} frontend={fid or '-'} chars={len(body)} calls={totals['calls']}")
    return TranslateResponse(
        translated_text=frontmatter + out_body, source_lang=source, target_lang=target,
        model=chain[0].get("model") or (conn or {}).get("id", ""), glossary_applied=applied,
        usage=totals, warnings=preservation_warnings(body, out_body))


@router.post("/jobs", response_model=JobCreated, summary="Translate a file (asynchronous)")
async def create_job(
    file: UploadFile = File(..., description="Any format the portal accepts (.txt .md .docx .rtf .pptx)."),
    target_langs: str = Form(..., description="Comma-separated language codes."),
    source_lang: str = Form("en"),
    frontend_id: str = Form(""),
    connection_id: str = Form(""),
    glossary: str = Form(""),
    force: bool = Form(False, description="Queue even if an identical job is still active."),
    token: dict = Depends(require_api_token),
):
    targets = list(dict.fromkeys(_check_lang(c, "target_langs") for c in target_langs.split(",") if c.strip()))
    if not targets:
        raise HTTPException(status_code=422, detail="target_langs is empty")
    source = _check_lang(source_lang, "source_lang")
    fid = _check_frontend(frontend_id)
    _check_connection(connection_id or None)
    filename = Path(file.filename or "").name
    tier = jq.detect_tier(filename)
    if not tier:
        raise HTTPException(status_code=415, detail=f"Unsupported file type: '{Path(filename).suffix}'")

    data = await file.read()
    # No await between this check and the insert below, so concurrent identical
    # submissions cannot both pass it (single event loop).
    owner = f"api:{token['name']}"
    fingerprint = jq.compute_fingerprint(data, source, targets, fid, glossary, connection_id)
    dup = None if force else jq.find_active_duplicate(owner, fingerprint)
    if dup:
        logger.info(f"API job duplicate of {dup['id']} (token {token['id']}) — not queued")
        return JobCreated(job_id=dup["id"], status=dup["status"], estimate_s=dup["estimate_s"], duplicate=True)

    staging = DOCUMENTS_DIR / "_staging" / ("api-" + secrets.token_hex(6))
    staging.mkdir(parents=True, exist_ok=True)
    try:
        staged = staging / filename
        staged.write_bytes(data)
        job = jq.enqueue(
            owner, source, targets, tier, str(staged), frontend_id=fid, glossary=glossary,
            mode="immediate", options={"connection_id": connection_id} if connection_id else {}, origin="api",
            fingerprint=fingerprint)
        job_dir = DOCUMENTS_DIR / job["id"]
        job_dir.mkdir(parents=True, exist_ok=True)
        staged.replace(job_dir / filename)
        jq.assign_path(job["id"], str(job_dir / filename))
    except Exception as e:
        logger.warning(f"API job submit failed: {e}")
        raise HTTPException(status_code=400, detail=f"Could not read the file (corrupt or unsupported): {e}")
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    logger.info(f"API job {job['id']} accepted tier={tier} langs={len(targets)} token={token['id']}")
    jq.dispatch()  # start now if its connection has a free slot (otherwise it waits its turn)
    return JobCreated(job_id=job["id"], status=jq.get(job["id"])["status"], estimate_s=job["estimate_s"])


def _own_job(job_id: str, token: dict[str, Any]) -> dict[str, Any]:
    job = jq.get(job_id)
    if not job or job.get("origin") != "api" or job["owner_email"] != f"api:{token['name']}".lower():
        raise HTTPException(status_code=404, detail="Job not found")
    return job


def _job_files(job: dict[str, Any]) -> list[JobFile]:
    """Files of a finished, unexpired job: the original plus one translation per language."""
    if job["status"] != "done" or (job["expires_at"] and job["expires_at"] < time.time()):
        return []
    job_dir, src = DOCUMENTS_DIR / job["id"], Path(job["path"])
    if not job_dir.is_dir():
        return []
    out = []
    for p in sorted(job_dir.iterdir()):
        if not p.is_file():
            continue
        lang = next((c for c in job["target_langs"] if p.name == f"{src.stem}.{c}{src.suffix}"), None)
        out.append(JobFile(name=p.name, kind="translation" if lang else "source", lang=lang, size=p.stat().st_size))
    return out


@router.get("/jobs", response_model=list[JobSummary], summary="List your jobs (document library)")
async def list_jobs(status: str | None = None, limit: int = 50, token: dict = Depends(require_api_token)):
    limit = max(1, min(200, limit))
    return [JobSummary(
        job_id=j["id"], filename=Path(j["path"]).name, status=j["status"], progress=j["progress"].get("fraction", 0.0),
        source_lang=j["source_lang"], target_langs=j["target_langs"], frontend_id=j["frontend_id"],
        created_at=j["created_at"], expires_at=j["expires_at"], files=_job_files(j))
        for j in jq.list_by_owner(f"api:{token['name']}", status, limit)]


@router.get("/jobs/{job_id}", response_model=JobStatus, summary="Job status and progress")
async def job_status(job_id: str, token: dict = Depends(require_api_token)):
    job = _own_job(job_id, token)
    return JobStatus(job_id=job["id"], status=job["status"], progress=job["progress"].get("fraction", 0.0),
                     total_langs=job["progress"].get("total", 0),
                     langs_done=job["progress"].get("langs_done", []), error=job["error"] or None,
                     expires_at=job["expires_at"], files=_job_files(job))


@router.delete("/jobs/{job_id}", summary="Cancel a waiting or running job")
async def cancel_job(job_id: str, token: dict = Depends(require_api_token)):
    _own_job(job_id, token)
    if not jq.cancel(job_id):
        raise HTTPException(status_code=409, detail="Job already finished; nothing to cancel")
    return {"job_id": job_id, "status": jq.get(job_id)["status"]}


@router.get("/jobs/{job_id}/files/{filename}", summary="Download one file (original or one translation)")
async def job_file(job_id: str, filename: str, token: dict = Depends(require_api_token)):
    job = _own_job(job_id, token)
    if job["status"] != "done":
        raise HTTPException(status_code=409, detail=f"Files not available (status: {job['status']})")
    match = next((f for f in _job_files(job) if f.name == filename), None)  # names come from disk, never from the URL
    if not match:
        raise HTTPException(status_code=404, detail="File not found (or expired)")
    return FileResponse(DOCUMENTS_DIR / job_id / match.name, filename=match.name)


@router.get("/jobs/{job_id}/result", summary="Download the result (file, or ZIP for several languages)")
async def job_result(job_id: str, token: dict = Depends(require_api_token)):
    job = _own_job(job_id, token)
    if job["status"] != "done" or (job["expires_at"] and job["expires_at"] < time.time()):
        raise HTTPException(status_code=409, detail=f"Result not available (status: {job['status']})")
    src = Path(job["path"])
    files = sorted(p for p in (DOCUMENTS_DIR / job["id"]).iterdir() if p.is_file() and p != src)
    if not files:
        raise HTTPException(status_code=410, detail="Result files are gone")
    if len(files) == 1:
        return FileResponse(files[0], filename=files[0].name)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in files:
            zf.write(p, arcname=p.name)
    return Response(buf.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{src.stem}.zip"'})
