import json
import logging
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from src.api.v1.admin.auth import require_admin
from src.services.frontend_registry import registry
from src.services.prompt_assembler import get_prompt_mode, copy_global_to_frontend

logger = logging.getLogger("backend.admin.frontends")
_CAMPAIGNS_DIR = Path("/app/data/campaigns")

router = APIRouter(prefix="/admin/frontends", tags=["admin-frontends"])


class RegisterRequest(BaseModel):
    url: str
    name: str = ""


class UpdateRequest(BaseModel):
    enabled: bool | None = None
    name: str | None = None


@router.get("")
async def list_frontends(_: dict = Depends(require_admin)):
    return {"frontends": registry.list_all()}


@router.post("")
async def register_frontend(req: RegisterRequest, _: dict = Depends(require_admin)):
    """Register a frontend by URL. Discovery stays URL-based (verify reachability
    via GET /internal/config); the frontend starts unconfigured (Sprint 21)."""
    url = req.url.rstrip("/")

    # Verify the frontend is reachable (URL-based detection, unchanged)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{url}/internal/config")
            resp.raise_for_status()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Cannot reach frontend at {url}: {str(e)}")

    frontend = registry.register(url, req.name)
    registry.set_status(frontend["id"], "online")

    # Auto-copy global prompts if in per_frontend mode (Sprint 8h loose end)
    if get_prompt_mode() == "per_frontend":
        copied = copy_global_to_frontend(frontend["id"])
        if copied:
            frontend["prompts_copied"] = copied

    return {"frontend": frontend}


# --- Deleted / restore (Sprint 21 soft-delete) ---

@router.get("/deleted")
async def list_deleted_frontends(_: dict = Depends(require_admin)):
    return {"frontends": registry.list_deleted()}


@router.post("/{frontend_id}/restore")
async def restore_frontend(frontend_id: str, _: dict = Depends(require_admin)):
    frontend = registry.restore(frontend_id)
    if not frontend:
        raise HTTPException(status_code=404, detail="Deleted frontend not found")
    return {"frontend": frontend}


# --- Per-frontend config (Sprint 21 schema; panel is Sprint 22) ---

@router.get("/{frontend_id}/config")
async def get_frontend_config(frontend_id: str, _: dict = Depends(require_admin)):
    if not registry.get(frontend_id):
        raise HTTPException(status_code=404, detail="Frontend not found")
    from src.services.frontend_registry import load_config
    return {"frontend_id": frontend_id, "config": load_config(frontend_id)}


@router.put("/{frontend_id}/config")
async def update_frontend_config(frontend_id: str, config: dict, _: dict = Depends(require_admin)):
    if not registry.get(frontend_id):
        raise HTTPException(status_code=404, detail="Frontend not found")
    from src.services.frontend_registry import save_config
    save_config(frontend_id, config)
    await _push_config_to_sidecar(frontend_id)
    return {"frontend_id": frontend_id, "config": config}


async def _push_config_to_sidecar(frontend_id: str):
    """Push the per-frontend config to the sidecar (mirror of branding push).

    Resolves the effective **app language** (Sprint 12): per-frontend override →
    the global default from admin Settings → 'en'. The portal renders its
    hardcoded i18n in this language.
    """
    from src.services.frontend_registry import load_config
    fe = registry.get(frontend_id)
    if not fe or not fe.get("enabled"):
        return
    config = load_config(frontend_id)
    if not config.get("app_language"):
        try:
            from src.api.v1.admin.settings import get_setting
            config = {**config, "app_language": get_setting("app_language", "en")}
        except Exception:
            pass
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            await client.post(f"{fe['url']}/internal/frontend-config", json=config)
            logger.info(f"Config pushed to {fe['url']}")
    except Exception as e:
        logger.warning(f"Failed to push config to {fe['url']}: {e}")


@router.put("/{frontend_id}")
async def update_frontend(frontend_id: str, req: UpdateRequest, _: dict = Depends(require_admin)):
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    frontend = registry.update(frontend_id, **updates)
    if not frontend:
        raise HTTPException(status_code=404, detail="Frontend not found")
    return {"frontend": frontend}


@router.delete("/{frontend_id}")
async def remove_frontend(frontend_id: str, _: dict = Depends(require_admin)):
    if not registry.remove(frontend_id):
        raise HTTPException(status_code=404, detail="Frontend not found")
    return {"status": "removed"}


# --- Branding ---

class BrandingRequest(BaseModel):
    app_title: str = ""
    logo_url: str = ""


def _branding_path(frontend_id: str) -> Path:
    return _CAMPAIGNS_DIR / frontend_id / "branding.json"


@router.get("/{frontend_id}/branding")
async def get_branding(frontend_id: str, _: dict = Depends(require_admin)):
    path = _branding_path(frontend_id)
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {"app_title": "", "logo_url": ""}


@router.put("/{frontend_id}/branding")
async def update_branding(frontend_id: str, req: BrandingRequest, _: dict = Depends(require_admin)):
    """Save per-frontend branding (app title + logo) and push it to the sidecar.

    Sprint 12: branding is now app_title/logo_url only — the disclaimer/instructions
    text and its LLM auto-translation (branding_translator) were retired with the
    hardcoded portal i18n (ADR-015). The portal UI is not customised text.
    """
    from src.services.polling import invalidate_branding_cache

    data = req.model_dump()
    path = _branding_path(frontend_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.rename(path)
    logger.info(f"Branding saved for frontend {frontend_id}")

    invalidate_branding_cache(frontend_id)
    await _push_branding_to_sidecar(frontend_id)

    return data


async def _push_branding_to_sidecar(frontend_id: str):
    """Push branding config (app title + logo) to the sidecar."""
    path = _branding_path(frontend_id)
    if not path.exists():
        return

    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return

    payload = {**data, "custom": bool(data.get("app_title") or data.get("logo_url"))}

    fe = registry.get(frontend_id)
    if fe and fe.get("enabled"):
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(f"{fe['url']}/internal/branding", json=payload)
                logger.info(f"Branding pushed to {fe['url']}")
        except Exception as e:
            logger.warning(f"Failed to push branding to {fe['url']}: {e}")
