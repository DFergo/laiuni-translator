"""Admin prompts endpoints — list, read, update prompt files.

Sprint 8h: Per-frontend prompt sets with ?frontend_id= query param.
"""

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from src.api.v1.admin.auth import require_admin
from src.services.prompt_assembler import (
    _global_prompts_dir,
    get_prompt_mode,
    set_prompt_mode,
    copy_global_to_frontend,
    delete_frontend_prompts,
    frontend_has_custom_prompts,
    reset_prompt_to_default,
    reset_global_to_defaults,
)

logger = logging.getLogger("backend.admin.prompts")

router = APIRouter(prefix="/admin/prompts", tags=["admin-prompts"])

# Category mapping for UI grouping.
# Sprint 9 (ADR-011): the document-translation *procedure* (translate_document.md)
# is hardcoded and NOT admin-editable; only the *flavour* (persona) is editable
# and per-frontend. translate.md remains the short UI-string prompt.
CATEGORIES: dict[str, list[str]] = {
    "UI strings": ["translate.md"],
    "Translation flavour (persona)": ["translate_flavour.md"],
}


def _resolve_prompts_dir(frontend_id: str | None = None) -> Path:
    """Resolve prompts directory: global or per-frontend."""
    if frontend_id:
        path = Path(f"/app/data/campaigns/{frontend_id}/prompts")
        path.mkdir(parents=True, exist_ok=True)
        return path
    return _global_prompts_dir()


def _file_meta(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "name": path.name,
        "size": stat.st_size,
        "modified": stat.st_mtime,
    }


# --- Prompt Mode endpoints (Sprint 8h) ---

@router.get("/mode")
async def get_mode(_: dict = Depends(require_admin)):
    """Get current prompt mode."""
    return {"mode": get_prompt_mode()}


class PromptModeRequest(BaseModel):
    mode: str


@router.put("/mode")
async def update_mode(req: PromptModeRequest, _: dict = Depends(require_admin)):
    """Set prompt mode (global / per_frontend). Auto-copies prompts when switching to per_frontend."""
    if req.mode not in ("global", "per_frontend"):
        raise HTTPException(status_code=400, detail="Mode must be 'global' or 'per_frontend'")

    old_mode = get_prompt_mode()
    new_mode = set_prompt_mode(req.mode)

    # Auto-copy global prompts to all frontends that don't have custom sets
    if old_mode == "global" and new_mode == "per_frontend":
        from src.services.frontend_registry import registry
        frontends = registry.list_all()
        for fe in frontends:
            if not frontend_has_custom_prompts(fe["id"]):
                copy_global_to_frontend(fe["id"])
                logger.info(f"Auto-copied global prompts to frontend {fe['id']}")

    return {"mode": new_mode}


@router.get("/custom-frontends")
async def list_custom_prompt_frontends(_: dict = Depends(require_admin)):
    """Frontends that currently have a custom prompt set (Sprint 23 guard)."""
    from src.services.frontend_registry import registry
    out = [
        {"id": fe["id"], "name": fe.get("name", fe["id"])}
        for fe in registry.list_all()
        if frontend_has_custom_prompts(fe["id"])
    ]
    return {"frontends": out}


@router.post("/copy-to-frontend/{frontend_id}")
async def copy_to_frontend(frontend_id: str, _: dict = Depends(require_admin)):
    """Copy global prompts to a frontend's campaign directory."""
    count = copy_global_to_frontend(frontend_id)
    return {"frontend_id": frontend_id, "copied": count}


@router.delete("/frontend/{frontend_id}")
async def delete_custom_prompts(frontend_id: str, _: dict = Depends(require_admin)):
    """Delete custom prompts for a frontend (reverts to global)."""
    count = delete_frontend_prompts(frontend_id)
    return {"frontend_id": frontend_id, "deleted": count}


@router.post("/reset-global")
async def reset_global_prompts(_: dict = Depends(require_admin)):
    """Reset ALL global prompts to factory defaults (per-frontend sets untouched)."""
    count = reset_global_to_defaults()
    return {"reset": count}


@router.post("/{name}/reset")
async def reset_single_prompt(name: str, frontend_id: str | None = Query(None), _: dict = Depends(require_admin)):
    """Reset one prompt to its default: per-frontend → global; global → factory."""
    try:
        content = reset_prompt_to_default(name, frontend_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"name": name, "content": content, "frontend_id": frontend_id}


# --- Standard prompt CRUD with optional frontend_id ---

@router.get("")
async def list_prompts(frontend_id: str | None = Query(None), _: dict = Depends(require_admin)):
    """List all prompt files grouped by category."""
    prompts_dir = _resolve_prompts_dir(frontend_id)
    result: dict[str, list[dict[str, Any]]] = {}

    for category, files in CATEGORIES.items():
        items = []
        for fname in files:
            path = prompts_dir / fname
            if path.exists():
                items.append(_file_meta(path))
            else:
                items.append({"name": fname, "size": 0, "modified": None})
        result[category] = items

    return {"categories": result}


@router.get("/{name}")
async def read_prompt(name: str, frontend_id: str | None = Query(None), _: dict = Depends(require_admin)):
    """Read a prompt file's content."""
    path = _resolve_prompts_dir(frontend_id) / name
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Prompt not found: {name}")
    return {"name": name, "content": path.read_text()}


class SavePromptRequest(BaseModel):
    content: str


@router.put("/{name}")
async def save_prompt(name: str, req: SavePromptRequest, frontend_id: str | None = Query(None), _: dict = Depends(require_admin)):
    """Save prompt file content (atomic write)."""
    prompts_dir = _resolve_prompts_dir(frontend_id)
    path = prompts_dir / name
    # Atomic write
    tmp = path.with_suffix(".tmp")
    tmp.write_text(req.content)
    tmp.rename(path)
    logger.info(f"Prompt saved: {name} (frontend={frontend_id or 'global'})")
    return {"name": name, "size": path.stat().st_size, "modified": path.stat().st_mtime}
