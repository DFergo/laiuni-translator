"""Admin knowledge base endpoints — glossary and organizations directory.

These are structured JSON files read directly by the LLM (not indexed via RAG).
They provide deterministic, curated data for term consistency and organization referrals.
"""

import json
import logging
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.api.v1.admin.auth import require_admin

logger = logging.getLogger("backend.admin.knowledge")

router = APIRouter(prefix="/admin/knowledge", tags=["admin-knowledge"])

from src.core.paths import KNOWLEDGE_DIR as _KNOWLEDGE_DIR
_DEFAULTS_DIR = Path(__file__).parent.parent.parent.parent / "knowledge"


def _ensure_dir():
    _KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)


def _atomic_write(path: Path, data: Any):
    """Write JSON atomically using tmp+rename (lesson #5)."""
    _ensure_dir()
    fd, tmp = tempfile.mkstemp(dir=_KNOWLEDGE_DIR, suffix=".tmp")
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
