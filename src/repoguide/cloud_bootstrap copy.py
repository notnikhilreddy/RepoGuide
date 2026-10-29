"""Load whitelisted application settings from SSM before importing FastAPI or settings."""
from __future__ import annotations

import json
import os

ALLOWED = frozenset({
    "DATABASE_URL", "LLM_PROVIDER", "GEMINI_API_KEY", "GEMINI_MODEL",
    "OPENCODE_API_KEY", "OPENCODE_BASE_URL", "OPENCODE_MODEL",
    "OLLAMA_BASE_URL", "OLLAMA_MODEL",
    "CONTEXT7_API_KEY", "GITHUB_PERSONAL_ACCESS_TOKEN", "REDIS_URL",
    "MLFLOW_ENABLED", "MLFLOW_TRACKING_URI", "MLFLOW_EXPERIMENT",
    "MLFLOW_CAPTURE_CONTENT", "MLFLOW_AUTOLOG", "ROUTER_PROVIDER",
    "JEV_API_KEY", "JEV_ENDPOINT", "JEV_MODEL",
    "ROUTER_SUFFICIENCY_THRESHOLD",
})


def hydrate_runtime_env() -> None:
    name = os.getenv("REPOGUIDE_SSM_PARAMETER")
    if not name:
        return
    import boto3
    result = boto3.client("ssm").get_parameter(Name=name, WithDecryption=True)
    config = json.loads(result["Parameter"]["Value"])
    if not isinstance(config, dict):
        raise ValueError("SSM runtime configuration must be a JSON object")
    for key, value in config.items():
        if key not in ALLOWED or not isinstance(value, str):
            raise ValueError(f"Invalid or unsupported SSM setting: {key}")
        os.environ[key] = value
