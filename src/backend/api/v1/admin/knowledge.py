"""Admin knowledge base endpoints — glossary and organizations directory.

These are structured JSON files read directly by the LLM (not indexed via RAG).
They provide deterministic, curated data for term consistency and organization referrals.
"""

import json
import logging
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from pydantic import BaseModel

from src.api.v1.admin.auth import require_admin

logger = logging.getLogger("backend.admin.knowledge")

router = APIRouter(prefix="/admin/knowledge", tags=["admin-knowledge"])

from src.core.paths import KNOWLEDGE_DIR as _KNOWLEDGE_DIR, CAMPAIGNS_DIR
_DEFAULTS_DIR = Path(__file__).parent.parent.parent.parent / "knowledge"

_GLOSSARY_MODES = ("append", "replace")


def _ensure_dir():
    _KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)


def _atomic_write(path: Path, data: Any):
    """Write JSON atomically (tmp+rename, lesson #5). Stages the temp file in the
    target's own directory (creating it) so it works for both the global
    knowledge dir and per-frontend campaign dirs."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with open(fd, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        Path(tmp).replace(path)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise


def ensure_defaults():
    """Install default knowledge base files if they don't exist."""
    _ensure_dir()
    for name in ("glossary.json", "organizations.json"):
        dest = _KNOWLEDGE_DIR / name
        src = _DEFAULTS_DIR / name
        if not dest.exists() and src.exists():
            dest.write_text(src.read_text())
            logger.info(f"Installed default knowledge file: {name}")


def load_glossary() -> dict[str, Any]:
    """Load glossary for prompt injection."""
    path = _KNOWLEDGE_DIR / "glossary.json"
    if path.exists():
        return json.loads(path.read_text())
    return {"terms": []}


def load_organizations() -> dict[str, Any]:
    """Load organizations directory for prompt injection."""
    path = _KNOWLEDGE_DIR / "organizations.json"
    if path.exists():
        return json.loads(path.read_text())
    return {"organizations": []}


# --- Glossary: structural validation + per-server storage (Sprint 10, ADR-012/013) ---


def validate_glossary(data: Any) -> dict[str, Any]:
    """Structural validation ONLY (§11.4): shape must be
    ``{"terms":[{"term": str, "translations": {lang: str}, "note"?: str}]}``.
    NEVER require a specific language count — a term covering some languages is
    valid. Raises ValueError on a bad shape; returns the normalised payload."""
    if not isinstance(data, dict) or not isinstance(data.get("terms"), list):
        raise ValueError('Glossary must be an object with a "terms" array.')
    terms: list[dict[str, Any]] = []
    for i, t in enumerate(data["terms"]):
        if not isinstance(t, dict):
            raise ValueError(f"terms[{i}] must be an object.")
        term = t.get("term")
        tr = t.get("translations")
        if not isinstance(term, str) or not term.strip():
            raise ValueError(f'terms[{i}] needs a non-empty "term" string.')
        if not isinstance(tr, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in tr.items()):
            raise ValueError(f'terms[{i}].translations must be an object of language→string.')
        entry: dict[str, Any] = {"term": term, "translations": tr}
        if isinstance(t.get("note"), str) and t["note"]:
            entry["note"] = t["note"]
        terms.append(entry)
    return {"terms": terms}


def _frontend_glossary_path(frontend_id: str) -> Path:
    return CAMPAIGNS_DIR / frontend_id / "glossary.json"


def _frontend_glossary_config_path(frontend_id: str) -> Path:
    return CAMPAIGNS_DIR / frontend_id / "glossary_config.json"


def load_frontend_glossary(frontend_id: str) -> dict[str, Any] | None:
    p = _frontend_glossary_path(frontend_id)
    if p.exists():
        try:
            return json.loads(p.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return None


def get_frontend_glossary_config(frontend_id: str) -> dict[str, Any]:
    """Per-frontend glossary mode (mirrors the original RAG ``include_global``):
    ``append`` = base + server (server wins on conflict); ``replace`` = server only."""
    p = _frontend_glossary_config_path(frontend_id)
    mode = "append"
    if p.exists():
        try:
            mode = json.loads(p.read_text()).get("mode", "append")
        except (json.JSONDecodeError, OSError):
            pass
    if mode not in _GLOSSARY_MODES:
        mode = "append"
    return {"mode": mode, "has_glossary": _frontend_glossary_path(frontend_id).exists()}


def set_frontend_glossary_config(frontend_id: str, mode: str) -> dict[str, Any]:
    if mode not in _GLOSSARY_MODES:
        raise ValueError(f"mode must be one of {_GLOSSARY_MODES}")
    _atomic_write(_frontend_glossary_config_path(frontend_id), {"mode": mode})
    return get_frontend_glossary_config(frontend_id)


def resolve_glossary(frontend_id: str = "") -> list[dict[str, Any]]:
    """The effective base+server term list for a job's frontend (§11.3).

    Precedence within the base layer: per-server **append** overrides base on a
    same term (case-insensitive); **replace** uses the server list alone. The
    per-job user glossary still wins over all of this (applied in slice_glossary).
    """
    base = load_glossary().get("terms", [])
    if not frontend_id:
        return base
    server = load_frontend_glossary(frontend_id)
    if not server:
        return base
    server_terms = server.get("terms", [])
    if get_frontend_glossary_config(frontend_id)["mode"] == "replace":
        return server_terms
    merged: dict[str, dict[str, Any]] = {t["term"].lower(): t for t in base}
    for t in server_terms:  # server wins on conflict
        merged[t["term"].lower()] = t
    return list(merged.values())


def glossary_coverage(terms: list[dict[str, Any]]) -> dict[str, Any]:
    """Counts for the admin tab: total terms + per-language coverage."""
    per_lang: dict[str, int] = {}
    for t in terms:
        for lang in (t.get("translations") or {}):
            per_lang[lang] = per_lang.get(lang, 0) + 1
    return {"term_count": len(terms), "languages": sorted(per_lang), "per_language": per_lang}


# --- API Endpoints ---


@router.get("/glossary")
async def get_glossary(_: dict = Depends(require_admin)):
    """Get the full glossary."""
    return load_glossary()


class GlossaryUpdate(BaseModel):
    terms: list[dict[str, Any]]


@router.put("/glossary")
async def update_glossary(data: GlossaryUpdate, _: dict = Depends(require_admin)):
    """Save the full glossary."""
    payload = {"terms": data.terms}
    path = _KNOWLEDGE_DIR / "glossary.json"
    _atomic_write(path, payload)
    logger.info(f"Glossary saved ({len(data.terms)} terms)")
    return payload


# --- Glossary upload (whole-JSON replace) + per-server (Sprint 10) ---


async def _read_glossary_upload(file: UploadFile) -> dict[str, Any]:
    try:
        data = json.loads((await file.read()).decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise HTTPException(status_code=400, detail=f"Not valid JSON: {e}")
    try:
        return validate_glossary(data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/glossary/upload")
async def upload_glossary(
    file: UploadFile = File(...),
    frontend_id: str | None = Query(None),
    _: dict = Depends(require_admin),
):
    """Replace the whole glossary from a JSON upload — global, or per-frontend
    when ``frontend_id`` is given (no per-term editor; §11.3). Structural
    validation only."""
    payload = await _read_glossary_upload(file)
    if frontend_id:
        _atomic_write(_frontend_glossary_path(frontend_id), payload)
        logger.info(f"Per-server glossary uploaded for {frontend_id} ({len(payload['terms'])} terms)")
    else:
        _atomic_write(_KNOWLEDGE_DIR / "glossary.json", payload)
        logger.info(f"Base glossary replaced via upload ({len(payload['terms'])} terms)")
    return {"terms": len(payload["terms"]), "frontend_id": frontend_id}


@router.get("/glossary/coverage")
async def glossary_coverage_endpoint(
    frontend_id: str | None = Query(None), _: dict = Depends(require_admin)
):
    """Coverage counts for the admin tab: base, per-server (if any), and the
    effective resolved list for a frontend."""
    out: dict[str, Any] = {"base": glossary_coverage(load_glossary().get("terms", []))}
    if frontend_id:
        server = load_frontend_glossary(frontend_id)
        out["config"] = get_frontend_glossary_config(frontend_id)
        out["server"] = glossary_coverage(server.get("terms", [])) if server else None
        out["effective"] = glossary_coverage(resolve_glossary(frontend_id))
    return out


class GlossaryModeRequest(BaseModel):
    mode: str


@router.put("/glossary/frontend/{frontend_id}/config")
async def set_frontend_glossary_mode(
    frontend_id: str, req: GlossaryModeRequest, _: dict = Depends(require_admin)
):
    """Set a frontend's glossary mode: ``append`` (base + server) or ``replace``."""
    try:
        return set_frontend_glossary_config(frontend_id, req.mode)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/glossary/frontend/{frontend_id}")
async def delete_frontend_glossary(frontend_id: str, _: dict = Depends(require_admin)):
    """Remove a frontend's per-server glossary (revert to the base)."""
    for p in (_frontend_glossary_path(frontend_id), _frontend_glossary_config_path(frontend_id)):
        p.unlink(missing_ok=True)
    logger.info(f"Per-server glossary removed for {frontend_id}")
    return {"status": "deleted", "frontend_id": frontend_id}


@router.get("/organizations")
async def get_organizations(_: dict = Depends(require_admin)):
    """Get the organizations directory."""
    return load_organizations()


class OrganizationsUpdate(BaseModel):
    organizations: list[dict[str, Any]]


@router.put("/organizations")
async def update_organizations(data: OrganizationsUpdate, _: dict = Depends(require_admin)):
    """Save the organizations directory."""
    payload = {"organizations": data.organizations}
    path = _KNOWLEDGE_DIR / "organizations.json"
    _atomic_write(path, payload)
    logger.info(f"Organizations saved ({len(data.organizations)} entries)")
    return payload
