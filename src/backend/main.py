# Copyright (c) 2026 UNI Global Union. All rights reserved. See LICENSE.

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

# Sprint 24: migrate the on-disk layout into config/ BEFORE any registry/service
# loads its files (the registries read at import time, just below).
from src.core.paths import migrate_layout
migrate_layout()

from src.api.v1.admin.auth import router as auth_router
from src.api.v1.admin.frontends import router as frontends_router
from src.api.v1.admin.llm import router as llm_router, fe_router as llm_fe_router
from src.api.v1.admin.prompts import router as prompts_router
from src.api.v1.admin.smtp import router as smtp_router
from src.api.v1.admin.contacts import router as contacts_router
from src.api.v1.admin.knowledge import router as knowledge_router
from src.api.v1.admin.knowledge import ensure_defaults as ensure_knowledge_defaults
from src.api.v1.admin.portability import router as portability_router
from src.api.v1.admin.settings import router as settings_router
from src.api.v1.admin.queue import router as queue_router, usage_router
from src.core.config import config
from src.services.job_queue import init_db, scheduler_loop
from src.services.polling import polling_loop
from src.services.prompt_assembler import ensure_defaults

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("backend")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Install default prompt files and knowledge base if missing
    ensure_defaults()
    ensure_knowledge_defaults()
    # Initialise the SQLite job queue (Sprint 4)
    init_db()
    # Non-blocking SMTP health check (logs warning if unreachable)
    from src.services.smtp_service import check_smtp_health
    asyncio.create_task(check_smtp_health())
    # Start the pull-inverse polling loop (SPEC §2, §8 — the security boundary)
    poll_task = asyncio.create_task(polling_loop(config.poll_interval_seconds))
    # Start the job scheduler loop (Sprint 4 — runs due jobs + retention sweep)
    sched_task = asyncio.create_task(scheduler_loop())
    logger.info("Backend started, pull-inverse polling + job scheduler loops running")
    yield
    for task in (poll_task, sched_task):
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="LAIUNI Translator Backend", version="1.0.0", lifespan=lifespan)

# Register API routes
app.include_router(auth_router)
app.include_router(frontends_router)
app.include_router(llm_router)
app.include_router(llm_fe_router)
app.include_router(prompts_router)
app.include_router(smtp_router)
app.include_router(contacts_router)
app.include_router(knowledge_router)
app.include_router(portability_router)
app.include_router(settings_router)
app.include_router(queue_router)
app.include_router(usage_router)

# Admin SPA static files
ADMIN_DIST = Path("/app/admin/dist")


@app.get("/health")
async def health():
    return JSONResponse({"status": "ok"})


# Serve admin SPA — must be after API routes
if ADMIN_DIST.exists():
    app.mount("/assets", StaticFiles(directory=ADMIN_DIST / "assets"), name="admin-assets")

    @app.get("/{full_path:path}")
    async def serve_admin_spa(full_path: str):
        """Serve admin SPA for all non-API routes."""
        file_path = ADMIN_DIST / full_path
        if file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(ADMIN_DIST / "index.html")
