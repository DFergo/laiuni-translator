"""Prompt-file management — global / per-frontend prompt sets (KEEP, gutted).

Sprint 1 (ADR-009): the HRDD system-prompt *assembly* (core+role+case+context+
knowledge) was removed with the chat machinery. What remains is the generic
prompt-file registry the admin **Prompts** tab and the **Frontends** route
depend on: mode (global / per_frontend), copy/reset, and per-frontend sets.
For LAIUNI the managed prompts are the UI/translation prompts (`translate.md`,
and later `translate_document.md`).
"""

import json
import logging
from pathlib import Path

from src.core.paths import PROMPTS_DIR, PROMPT_MODE, CAMPAIGNS_DIR

logger = logging.getLogger("backend.prompts")

# Default prompts shipped with the app — copied to data dir on first run
_DEFAULTS_DIR = Path(__file__).parent.parent / "prompts"

# Prompt mode config file (Sprint 24: config/ layout)
_PROMPT_MODE_PATH = PROMPT_MODE


def _global_prompts_dir() -> Path:
    """Always return the global prompts directory (for admin, defaults, etc.)."""
    return PROMPTS_DIR


def get_prompt_mode() -> str:
    """Get current prompt mode: 'global' or 'per_frontend'."""
    if _PROMPT_MODE_PATH.exists():
        try:
            data = json.loads(_PROMPT_MODE_PATH.read_text())
            return data.get("mode", "global")
        except Exception:
            pass
    return "global"


def set_prompt_mode(mode: str) -> str:
    """Set prompt mode. Returns the new mode."""
    if mode not in ("global", "per_frontend"):
        raise ValueError(f"Invalid prompt mode: {mode}")
    _PROMPT_MODE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _PROMPT_MODE_PATH.write_text(json.dumps({"mode": mode}))
    logger.info(f"Prompt mode set to: {mode}")
    return mode


def copy_global_to_frontend(frontend_id: str) -> int:
    """Copy all global prompts to a frontend's campaign directory. Returns count."""
    global_dir = _global_prompts_dir()
    campaign_dir = CAMPAIGNS_DIR / frontend_id / "prompts"
    campaign_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for src_file in global_dir.glob("*.md"):
        dst_file = campaign_dir / src_file.name
        if not dst_file.exists():
            dst_file.write_text(src_file.read_text())
            count += 1
    logger.info(f"Copied {count} global prompts to frontend {frontend_id}")
    return count


def delete_frontend_prompts(frontend_id: str) -> int:
    """Delete all custom prompts for a frontend. Returns count deleted."""
    campaign_dir = CAMPAIGNS_DIR / frontend_id / "prompts"
    if not campaign_dir.exists():
        return 0
    count = 0
    for f in campaign_dir.glob("*.md"):
        f.unlink()
        count += 1
    logger.info(f"Deleted {count} custom prompts for frontend {frontend_id}")
    return count


def frontend_has_custom_prompts(frontend_id: str) -> bool:
    """Check if a frontend has any custom prompt files."""
    campaign_dir = CAMPAIGNS_DIR / frontend_id / "prompts"
    return campaign_dir.exists() and any(campaign_dir.glob("*.md"))


def reset_prompt_to_default(name: str, frontend_id: str | None = None) -> str:
    """Reset a single prompt to its default; return the new content.

    Per-frontend: restore that frontend's copy from the current GLOBAL prompt.
    Global: restore the global prompt from the bundled FACTORY default.
    """
    if not name.endswith(".md") or "/" in name or "\\" in name:
        raise ValueError("Invalid prompt name")
    if frontend_id:
        src = _global_prompts_dir() / name
        dst_dir = CAMPAIGNS_DIR / frontend_id / "prompts"
    else:
        src = _DEFAULTS_DIR / name
        dst_dir = _global_prompts_dir()
    if not src.exists():
        raise FileNotFoundError(f"No default available for prompt: {name}")
    dst_dir.mkdir(parents=True, exist_ok=True)
    content = src.read_text()
    (dst_dir / name).write_text(content)
    logger.info(f"Reset prompt {name} to default (frontend={frontend_id or 'global'})")
    return content


def reset_global_to_defaults() -> int:
    """Overwrite ALL global prompts from the bundled factory defaults.

    Per-frontend custom sets live in separate directories and are NOT affected.
    """
    dest = _global_prompts_dir()
    dest.mkdir(parents=True, exist_ok=True)
    count = 0
    for src_file in _DEFAULTS_DIR.glob("*.md"):
        (dest / src_file.name).write_text(src_file.read_text())
        count += 1
    logger.info(f"Reset {count} global prompts to factory defaults")
    return count


def ensure_defaults():
    """Copy default prompt files to data dir if they don't exist yet."""
    dest = _global_prompts_dir()
    dest.mkdir(parents=True, exist_ok=True)
    for src_file in _DEFAULTS_DIR.glob("*.md"):
        dst_file = dest / src_file.name
        if not dst_file.exists():
            dst_file.write_text(src_file.read_text())
            logger.info(f"Installed default prompt: {src_file.name}")
