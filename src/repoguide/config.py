from functools import lru_cache

from typing import Literal
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str

    llm_provider: Literal["gemini", "opencode", "ollama"] = "gemini"

    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.8-flash"

    opencode_api_key: str = ""
    opencode_base_url: str = "https://opencode.ai/zen/v1"
    opencode_model: str = "muse-spark-1.3-contributor-free"

    ollama_base_url: str = "http://localhost:11434/v1"
    ollama_model: str = "qwen3.5:4b"

    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_dim: int = 384

    rerank_model: str = "cross-encoder/ms-marco-MiniLM-L6-v2"
    context_char_budget: int = 24000

    redis_url: str = ""
    context7_api_key: str = ""
    github_personal_access_token: str = ""

    mlflow_enabled: bool = False  # enable with an accessible remote MLflow tracking server
    mlflow_tracking_uri: str = "http://127.0.0.1:5000"
    mlflow_experiment: str = "RepoGuide"
    mlflow_capture_content: bool = False
    mlflow_autolog: bool = False
    router_provider: Literal["llm", "jev"] = "llm"
    jev_api_key: str = ""
    jev_endpoint: str = "https://api.typesafe.ai/v1/systemone"
    jev_model: str = "jev-latest"
    router_sufficiency_threshold: float = 0.75

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
