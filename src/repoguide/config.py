from functools import lru_cache

from typing import Literal
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str

    llm_provider: Literal["gemini", "opencode"] = "opencode"

    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.8-flash"

    opencode_api_key: str = ""
    opencode_base_url: str = "https://opencode.ai/zen/v1"
    opencode_model: str = "muse-spark-1.3-contributor-free"

    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_dim: int = 384

    rerank_model: str = "cross-encoder/ms-marco-MiniLM-L6-v2"
    context_char_budget: int = 16000

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
