import json
import logging
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

from src.api.v1.admin.auth import require_admin
from src.services import frontend_client
from src.services.frontend_registry import registry
from src.services.prompt_assembler import get_prompt_mode, copy_global_to_frontend

logger = logging.getLogger("backend.admin.frontends")
_CAMPAIGNS_DIR = Path("/app/data/campaigns")

router = APIRouter(prefix="/admin/frontends", tags=["admin-frontends"])


class RegisterRequest(BaseModel):
    url: str  # the frontend's BACKEND port URL (legacy mode: its single port)
    name: str = ""
    # "signed" (default: own secret, else the installation secret TRANSLATOR_FRONTEND_SECRET),
    # "unsigned" (trusted network) or "legacy" (old frontend image).
    auth_mode: str = frontend_client.MODE_SIGNED
    signing_secret: str = ""   # optional per-frontend secret; blank = installation secret
    extra_headers: dict[str, str] = {}
    # Public address of the portal, used for the emailed download link (SPEC §14.3).
    # Blank = `url` (right only when `url` is also what users reach, i.e. legacy).
    public_url: str = ""


class UpdateRequest(BaseModel):
    enabled: bool | None = None
    name: str | None = None
    url: str | None = None
    auth_mode: str | None = None
    # None = unchanged; "" = remove the per-frontend secret (falls back to the installation secret)
    signing_secret: str | None = None
    # None = unchanged; {} = remove. Values are write-only (never returned).
    extra_headers: dict[str, str] | None = None
    public_url: str | None = None  # None = unchanged; "" = remove


MIN_SECRET_LENGTH = frontend_client.MIN_SECRET_LENGTH
_CRED_FIELDS = {"auth_mode", "signing_secret", "extra_headers"}


def _public_view(fe: dict | None) -> dict | None:
    """Registry entry without secrets: the admin only sees whether they are set."""
    if fe is None:
        return None
    out = {k: v for k, v in fe.items() if k not in ("signing_secret", "extra_headers")}
    mode = frontend_client.auth_mode(fe)
    _, source = frontend_client.effective_secret(fe)
    out["auth_mode"] = mode
    out["signing_source"] = source if mode == frontend_client.MODE_SIGNED else ""
    out["signing_enabled"] = mode == frontend_client.MODE_SIGNED and bool(source)
    out["extra_header_names"] = sorted((fe.get("extra_headers") or {}).keys())
    return out


def _check_mode(mode: str):
    if mode not in frontend_client.AUTH_MODES:
        raise HTTPException(status_code=400, detail=f"auth_mode must be one of {', '.join(frontend_client.AUTH_MODES)}")


def _check_secret(secret: str):
    if secret and len(secret) < MIN_SECRET_LENGTH:
        raise HTTPException(status_code=400, detail=f"Signing secret must be at least {MIN_SECRET_LENGTH} characters")


def _check_signable(entry: dict):
    if frontend_client.auth_mode(entry) == frontend_client.MODE_SIGNED and not frontend_client.effective_secret(entry)[0]:
        raise HTTPException(
            status_code=400,
            detail="Signed mode needs a secret: set TRANSLATOR_FRONTEND_SECRET on the backend (installation secret) "
                   "or enter a secret for this frontend.",
        )


async def _probe(url: str, entry: dict):
    """Reachability + auth check against the frontend (GET config), with the entry's final mode."""
    mode = frontend_client.auth_mode(entry)
    try:
        async with frontend_client.ProbeClient(entry) as client:
            resp = await client.get(f"{url}/internal/config")
            resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        code = e.response.status_code
        if code == 401 and mode == frontend_client.MODE_SIGNED:
            detail = (f"Frontend at {url} rejected the signature — check that its TRANSLATOR_BACKEND_SECRET matches "
                      f"this frontend's secret (or TRANSLATOR_FRONTEND_SECRET here) and that both clocks are in sync")
        elif code == 401:
            detail = (f"Frontend at {url} requires signed requests — choose 'Signed', or start the frontend "
                      f"with BACKEND_SURFACE_AUTH=trusted-network")
        elif code == 404 and mode != frontend_client.MODE_LEGACY:
            detail = (f"No backend surface at {url} — use the frontend's backend port (container port 8080), "
                      f"not the public one; a frontend on the old image needs mode 'Legacy'")
        else:
            detail = f"Cannot reach frontend at {url}: {str(e)}"
        raise HTTPException(status_code=400, detail=detail)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Cannot reach frontend at {url}: {str(e)}")


@router.get("")
async def list_frontends(_: dict = Depends(require_admin)):
    return {
        "frontends": [_public_view(f) for f in registry.list_all()],
        "global_secret_configured": bool(frontend_client.global_secret()),
    }


@router.post("")
async def register_frontend(req: RegisterRequest, _: dict = Depends(require_admin)):
    """Register a frontend by URL. Discovery stays URL-based (verify reachability
    via GET /internal/config); the frontend starts unconfigured (Sprint 21)."""
    url = req.url.rstrip("/")
    secret = req.signing_secret.strip()
    _check_mode(req.auth_mode)
    _check_secret(secret)
    entry = {"auth_mode": req.auth_mode, "signing_secret": secret, "extra_headers": req.extra_headers}
    _check_signable(entry)

    # Verify the frontend is reachable and accepts this mode before saving anything
    await _probe(url, entry)

    frontend = registry.register(url, req.name)
    frontend = registry.update(frontend["id"], **entry, public_url=req.public_url.strip().rstrip("/"))
    registry.set_status(frontend["id"], "online")

    # Auto-copy global prompts if in per_frontend mode (Sprint 8h loose end)
    if get_prompt_mode() == "per_frontend":
        copied = copy_global_to_frontend(frontend["id"])
        if copied:
            frontend = {**_public_view(frontend), "prompts_copied": copied}
            return {"frontend": frontend}

    return {"frontend": _public_view(frontend)}


# --- Deleted / restore (Sprint 21 soft-delete) ---

@router.get("/deleted")
async def list_deleted_frontends(_: dict = Depends(require_admin)):
    return {"frontends": [_public_view(f) for f in registry.list_deleted()]}


@router.post("/{frontend_id}/restore")
async def restore_frontend(frontend_id: str, _: dict = Depends(require_admin)):
    frontend = registry.restore(frontend_id)
    if not frontend:
        raise HTTPException(status_code=404, detail="Deleted frontend not found")
    return {"frontend": _public_view(frontend)}


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
    from src.services.polling import invalidate_config_cache
    save_config(frontend_id, config)
    invalidate_config_cache(frontend_id)  # ensure the poll re-pushes even if the direct push below fails
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
        async with frontend_client.AsyncClient(timeout=10.0) as client:
            await client.post(f"{fe['url']}/internal/frontend-config", json=config)
            logger.info(f"Config pushed to {fe['url']}")
    except Exception as e:
        logger.warning(f"Failed to push config to {fe['url']}: {e}")


@router.put("/{frontend_id}")
async def update_frontend(frontend_id: str, req: UpdateRequest, verify: bool = True, _: dict = Depends(require_admin)):
    """Update name/enabled/url. `url` preserves the id — and therefore all
    campaign config (profiles/auth/branding/glossary/...) tied to it — instead
    of forcing a delete+re-register that would mint a new id (office DHCP
    without a reservation is the recurring case: the frontend's LAN IP rotates
    and the registry is left pointing at the old one).

    `verify=false` skips only the reachability probe (for a launchd
    reconciler that resolves the new IP on the host); the URL-collision check
    always runs.
    """
    current = registry.get(frontend_id)
    if not current:
        raise HTTPException(status_code=404, detail="Frontend not found")

    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    if "public_url" in updates:
        updates["public_url"] = updates["public_url"].strip().rstrip("/")
    if "auth_mode" in updates:
        _check_mode(updates["auth_mode"])
    if "signing_secret" in updates:
        updates["signing_secret"] = updates["signing_secret"].strip()
        _check_secret(updates["signing_secret"])
    if _CRED_FIELDS & updates.keys():
        # Pin the mode explicitly: entries from before modes existed derive it from
        # their secret, and removing that secret must not silently switch to legacy.
        updates.setdefault("auth_mode", frontend_client.auth_mode(current))
        _check_signable({**current, **updates})

    if "url" in updates:
        new_url = updates["url"].rstrip("/")
        if registry.find_by_url(new_url, exclude=frontend_id):
            raise HTTPException(status_code=409, detail=f"URL {new_url} is already registered to another frontend")
        updates["url"] = new_url

    # Verify reachability and auth with the URL + mode + credentials that will be
    # in effect after the update. Any http(s) host is accepted — IP, hostname,
    # .local, Tailscale MagicDNS; the check decides, not the format.
    if verify and (({"url"} | _CRED_FIELDS) & updates.keys()):
        final = {**current, **updates}
        await _probe(final["url"], final)

    frontend = registry.update(frontend_id, **updates)
    return {"frontend": _public_view(frontend)}


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
            async with frontend_client.AsyncClient(timeout=10.0) as client:
                await client.post(f"{fe['url']}/internal/branding", json=payload)
                logger.info(f"Branding pushed to {fe['url']}")
        except Exception as e:
            logger.warning(f"Failed to push branding to {fe['url']}: {e}")
