import json
import os
from pydantic import BaseModel


class BackendConfig(BaseModel):
    role: str = "backend"
    lm_studio_endpoint: str = "http://host.docker.internal:1234/v1"
    lm_studio_model: str = "qwen3-235b-a22b"
    ollama_endpoint: str = "http://host.docker.internal:11434"
    ollama_summariser_model: str = "qwen2.5:7b"
    ollama_num_ctx: int = 8192
    streaming_enabled: bool = True
    stream_chunk_size: int = 1
    poll_interval_seconds: int = 2
    prompts_path: str = "./data/prompts"
    file_max_size_mb: int = 25


def load_config() -> BackendConfig:
    config_path = os.environ.get("DEPLOYMENT_JSON_PATH", "config/deployment_backend.json")
    if os.path.exists(config_path):
        with open(config_path) as f:
            data = json.load(f)
        return BackendConfig(**data)
    return BackendConfig()


config = load_config()
