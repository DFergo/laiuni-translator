"""Export / import (Sprint 24, REFACTOR §0.6).

ZIP portability for per-frontend campaigns and the global config. Bundles carry
source docs + config; RAG indexes are NOT shipped (rebuilt on import). Import
also supports a folder path (shortcut when DATA_DIR is bind-mounted).
"""

import io
import logging
import shutil
import zipfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from src.api.v1.admin.auth import require_admin
from src.core.paths import CONFIG_DIR, campaign_dir
from src.services.frontend_registry import registry

logger = logging.getLogger("backend.admin.portability")

router = APIRouter(prefix="/admin", tags=["admin-portability"])

# Directories never shipped in a bundle (binary/large; rebuilt on import).
_EXCLUDE_TOP = {"rag_index"}


def _zip_dir(src: Path) -> io.BytesIO:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in src.rglob("*"):
            if p.is_dir():
                continue
            rel = p.relative_to(src)
            if rel.parts and rel.parts[0] in _EXCLUDE_TOP:
                continue
            zf.write(p, str(rel))
    buf.seek(0)
    return buf


def _safe_extract(data: bytes, dest: Path):
    dest.mkdir(parents=True, exist_ok=True)
    dest_root = dest.resolve()
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for member in zf.namelist():
            target = (dest / member).resolve()
            if not str(target).startswith(str(dest_root)):
                raise HTTPException(status_code=400, detail=f"Unsafe path in archive: {member}")
        zf.extractall(dest)


def _copy_folder(src: Path, dest: Path):
    for p in src.rglob("*"):
        if p.is_dir():
            continue
        rel = p.relative_to(src)
        if rel.parts and rel.parts[0] in _EXCLUDE_TOP:
            continue
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, target)


def _stream_zip(buf: io.BytesIO, filename: str) -> StreamingResponse:
    return StreamingResponse(
        buf, media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


async def _post_frontend_import(frontend_id: str):
    """Push imported config to the sidecar."""
    try:
        from src.api.v1.admin.frontends import _push_config_to_sidecar
        await _push_config_to_sidecar(frontend_id)
    except Exception as e:
        logger.warning(f"Post-import config push failed for {frontend_id}: {e}")


class FolderImportRequest(BaseModel):
    path: str


# --- Export ---

@router.get("/export/frontend/{frontend_id}")
async def export_frontend(frontend_id: str, _: dict = Depends(require_admin)):
    src = campaign_dir(frontend_id)
    if not src.exists():
        raise HTTPException(status_code=404, detail="Frontend has no campaign data to export")
    fe = registry.get(frontend_id) or {}
    safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in (fe.get("name") or frontend_id))
    return _stream_zip(_zip_dir(src), f"frontend-{safe}.zip")


@router.get("/export/global")
async def export_global(_: dict = Depends(require_admin)):
    if not CONFIG_DIR.exists():
        raise HTTPException(status_code=404, detail="No global config to export")
    return _stream_zip(_zip_dir(CONFIG_DIR), "global-config.zip")


# --- Import (frontend) ---

@router.post("/import/frontend/{frontend_id}")
async def import_frontend(frontend_id: str, file: UploadFile = File(...), _: dict = Depends(require_admin)):
    if not registry.get(frontend_id):
        raise HTTPException(status_code=404, detail="Unknown frontend")
    _safe_extract(await file.read(), campaign_dir(frontend_id))
    await _post_frontend_import(frontend_id)
    return {"frontend_id": frontend_id, "imported": True}


@router.post("/import/frontend/{frontend_id}/from-folder")
async def import_frontend_folder(frontend_id: str, req: FolderImportRequest, _: dict = Depends(require_admin)):
    if not registry.get(frontend_id):
        raise HTTPException(status_code=404, detail="Unknown frontend")
    src = Path(req.path)
    if not src.is_dir():
        raise HTTPException(status_code=400, detail=f"Not a folder: {req.path}")
    _copy_folder(src, campaign_dir(frontend_id))
    await _post_frontend_import(frontend_id)
    return {"frontend_id": frontend_id, "imported": True}


# --- Import (global config) ---

@router.post("/import/global")
async def import_global(file: UploadFile = File(...), _: dict = Depends(require_admin)):
    _safe_extract(await file.read(), CONFIG_DIR)
    logger.info("Global config imported — restart the backend to reload registry-backed config")
    return {"imported": True, "note": "Restart the backend to fully apply registry-backed config (frontends, connections)."}
