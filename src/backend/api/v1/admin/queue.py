"""Admin queue management (Sprint 14, SPEC §12.8) + privacy-safe usage log (§12.9).

The admin sees the pending-process list (status + queue position) and can
reorder / delete / prioritise a job; the usage log reports per-user counts only —
never filenames or content — and survives retention.
"""

import logging

from fastapi import APIRouter, Depends, Query

from src.api.v1.admin.auth import require_admin
from src.services import job_queue as jq

logger = logging.getLogger("backend.admin.queue")

router = APIRouter(prefix="/admin/queue", tags=["admin-queue"])
usage_router = APIRouter(prefix="/admin/usage", tags=["admin-usage"])


@router.get("")
async def get_queue(_: dict = Depends(require_admin)):
    """Running + waiting jobs in run order, each with its 1-based position."""
    jobs = jq.list_queue()
    return {"jobs": [
        {
            "id": j["id"], "owner": j["owner_email"], "frontend_id": j["frontend_id"],
            "status": j["status"], "mode": j["mode"], "priority": bool(j["priority"]),
            "format": j["format"], "n_langs": len(j["target_langs"]),
            "created_at": j["created_at"], "run_at": j["run_at"], "position": i + 1,
        }
        for i, j in enumerate(jobs)
    ]}


@router.post("/{job_id}/prioritise")
async def prioritise(job_id: str, on: bool = Query(True), _: dict = Depends(require_admin)):
    jq.set_priority(job_id, on)
    logger.info(f"Admin set priority={on} for job {job_id}")
    return {"ok": True}


@router.post("/{job_id}/move")
async def move(job_id: str, direction: str = Query(...), _: dict = Depends(require_admin)):
    if direction not in ("up", "down"):
        return {"ok": False, "error": "direction must be up|down"}
    jq.move_in_queue(job_id, direction)
    return {"ok": True}


@router.delete("/{job_id}")
async def remove(job_id: str, _: dict = Depends(require_admin)):
    jq.purge(job_id)
    logger.info(f"Admin deleted job {job_id}")
    return {"ok": True}


@usage_router.get("")
async def get_usage(_: dict = Depends(require_admin)):
    """Per-user usage — documents / languages / dates. Counts only (§12.9)."""
    return {"usage": jq.usage_summary()}
