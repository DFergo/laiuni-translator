"""Central filesystem layout (Sprint 24, REFACTOR §0.6).

Single source of truth for every path under DATA_DIR. Global config lives in
`config/`; sessions/campaigns/deleted stay at the root; secrets + runtime state
stay at the root too.

    DATA_DIR/
    ├── config/            # global: prompts/, knowledge/,
    │                      #   llm_settings.json, connections.json, smtp.json,
    │                      #   authorized_contacts.json, prompt_mode.json, frontends.json
    ├── campaigns/{fid}/   # per-frontend: config, branding, prompts, llm overrides
    ├── deleted/{fid}/     # soft-deleted, recoverable
    ├── .admin_hash        # secret (root)
    └── .jwt_secret        # secret (root)
"""

import os
from pathlib import Path

DATA_DIR = Path(os.environ.get("HRDD_DATA_DIR", "/app/data"))

# Top-level dirs
CONFIG_DIR = DATA_DIR / "config"
CAMPAIGNS_DIR = DATA_DIR / "campaigns"
DELETED_DIR = DATA_DIR / "deleted"

# Global config files (in config/)
LLM_SETTINGS = CONFIG_DIR / "llm_settings.json"
CONNECTIONS = CONFIG_DIR / "connections.json"
SMTP_CONFIG = CONFIG_DIR / "smtp.json"
AUTHORIZED_CONTACTS = CONFIG_DIR / "authorized_contacts.json"
PROMPT_MODE = CONFIG_DIR / "prompt_mode.json"
FRONTENDS = CONFIG_DIR / "frontends.json"
KNOWLEDGE_DIR = CONFIG_DIR / "knowledge"
PROMPTS_DIR = CONFIG_DIR / "prompts"

# Runtime state (root — not config; Sprint 4 job queue)
JOBS_DB = DATA_DIR / "jobs.db"            # SQLite job queue (queue only — lesson #14)
DOCUMENTS_DIR = DATA_DIR / "documents"    # per-job uploads + translations (48h retention)

# Secrets (root — not admin-editable "navigable config")
ADMIN_HASH = DATA_DIR / ".admin_hash"
JWT_SECRET = DATA_DIR / ".jwt_secret"


def campaign_dir(frontend_id: str) -> Path:
    return CAMPAIGNS_DIR / frontend_id


# ---------------------------------------------------------------------------
# One-time layout migration (Sprint 24, transitional)
# ---------------------------------------------------------------------------

# Old root location → new config/ location. Applied on startup; non-destructive.
_MIGRATIONS: list[tuple[Path, Path]] = [
    (DATA_DIR / "llm_settings.json", LLM_SETTINGS),
    (DATA_DIR / "connections.json", CONNECTIONS),  # Sprint 19 already wrote to config/, but migrate any stray root copy
    (DATA_DIR / "smtp_config.json", SMTP_CONFIG),
    (DATA_DIR / "authorized_contacts.json", AUTHORIZED_CONTACTS),
    (DATA_DIR / "authorized_emails.json", CONFIG_DIR / "authorized_emails.json"),  # legacy
    (DATA_DIR / "prompt_mode.json", PROMPT_MODE),
    (DATA_DIR / "frontends.json", FRONTENDS),
    (DATA_DIR / "knowledge", KNOWLEDGE_DIR),
    (DATA_DIR / "prompts", PROMPTS_DIR),
]


def migrate_layout() -> int:
    """Move legacy root files/dirs into the config/ layout. Idempotent + safe.

    Moves only when the source exists and the target does not; never deletes.
    Transitional: fresh installs write straight to the new paths, so this is a
    no-op there and can be removed once all deployments are on the new layout.
    Returns the number of items moved.
    """
    import logging
    import shutil

    logger = logging.getLogger("backend.paths")
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    moved = 0
    for old, new in _MIGRATIONS:
        try:
            if old.exists() and not new.exists():
                new.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(old), str(new))
                logger.info(f"Migrated {old} → {new}")
                moved += 1
        except Exception as e:
            logger.error(f"Layout migration failed for {old} → {new}: {e}")
    if moved:
        logger.info(f"Layout migration moved {moved} item(s) into config/")
    return moved
