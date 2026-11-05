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


class JobStatus(BaseModel):
    job_id: str
    status: str = Field(description="queued | scheduled | running | done | failed")
    total_langs: int
    langs_done: list[str]
    error: str | None = None
    expires_at: float | None = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


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

    staging = DOCUMENTS_DIR / "_staging" / ("api-" + secrets.token_hex(6))
    staging.mkdir(parents=True, exist_ok=True)
    try:
        staged = staging / filename
        staged.write_bytes(await file.read())
        job = jq.enqueue(
            f"api:{token['name']}", source, targets, tier, str(staged), frontend_id=fid, glossary=glossary,
            mode="immediate", options={"connection_id": connection_id} if connection_id else {}, origin="api")
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
    return JobCreated(job_id=job["id"], status=job["status"], estimate_s=job["estimate_s"])


def _own_job(job_id: str, token: dict[str, Any]) -> dict[str, Any]:
    job = jq.get(job_id)
    if not job or job.get("origin") != "api" or job["owner_email"] != f"api:{token['name']}".lower():
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.get("/jobs/{job_id}", response_model=JobStatus, summary="Job status and progress")
async def job_status(job_id: str, token: dict = Depends(require_api_token)):
    job = _own_job(job_id, token)
    return JobStatus(job_id=job["id"], status=job["status"], total_langs=job["progress"].get("total", 0),
                     langs_done=job["progress"].get("langs_done", []), error=job["error"] or None,
                     expires_at=job["expires_at"])


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
