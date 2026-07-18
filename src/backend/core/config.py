import json
import os
from pydantic import BaseModel


class BackendConfig(BaseModel):
    role: str = "backend"
    poll_interval_seconds: int = 2  # pull-inverse polling loop (main.py)


def load_config() -> BackendConfig:
    config_path = os.environ.get("DEPLOYMENT_JSON_PATH", "config/deployment_backend.json")
    if os.path.exists(config_path):
        with open(config_path) as f:
            data = json.load(f)
        return BackendConfig(**data)
    return BackendConfig()


config = load_config()
