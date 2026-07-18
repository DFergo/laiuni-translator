import json
import os
from pydantic import BaseModel


class BackendConfig(BaseModel):
    role: str = "backend"
    poll_interval_seconds: int = 2  # pull-inverse polling loop (main.py)

    # --- Sprint 4: job queue, scheduling, retention (SPEC §7) ---
    # Duration estimate = chars ÷ throughput × n_target_languages (calibrated;
    # ~two-pass on a large local model). Order-of-magnitude, not exact.
    translation_throughput_chars_per_s: float = 10.0
    schedule_default_hour: int = 23        # scheduled jobs default to next ≥ this hour, local
    scheduling_enabled: bool = True        # disable → "scheduled" mode runs immediately
    retention_hours: int = 48              # delete files + row this long after done
    job_scheduler_interval_seconds: int = 30
    supported_formats: dict[str, list[str]] = {
        "tier1": [".txt", ".md", ".markdown"],
        "tier2": [".docx", ".rtf"],
        "tier3": [".pptx"],
    }


def load_config() -> BackendConfig:
    config_path = os.environ.get("DEPLOYMENT_JSON_PATH", "config/deployment_backend.json")
    if os.path.exists(config_path):
        with open(config_path) as f:
            data = json.load(f)
        return BackendConfig(**data)
    return BackendConfig()


config = load_config()
