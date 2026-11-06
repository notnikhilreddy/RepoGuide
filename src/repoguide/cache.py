"""M5 Redis final-result caching. Only validated answers are cached.

Local-dev key namespace. Before multi-user production, use authenticated tenant
identity in the key, restrict Redis access, and define data retention rules.
"""

from __future__ import annotations

import hashlib
import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from repoguide.config import settings


class CacheBackend(Protocol):
    def get(self, key: str) -> str | None: ...
    def setex(self, key: str, ttl: int, value: str) -> None: ...


@lru_cache(maxsize=1)
def cache_client():
    from repoguide.cloud_cache import rest_cache

    if client := rest_cache():
        return client
    if os.getenv("REPOGUIDE_CLOUD_MODE") == "true":
        return None
    import redis

    url = getattr(settings, "redis_url", "")
    if not url:
        return None
    return redis.Redis.from_url(
        url, decode_responses=True, socket_timeout=1, socket_connect_timeout=1
    )


@lru_cache(maxsize=1)
def quality_fingerprint():
    digest = hashlib.sha256()
    for name in (
        "llm.py",
        "answers.py",
        "workflow.py",
        "router.py",
        "pipeline.py",
        "hybrid.py",
        "context.py",
    ):
        digest.update(Path(__file__).with_name(name).read_bytes())
    return digest.hexdigest()


def result_key(state: dict, provider: str, model: str) -> str:
    material = {
        "schema": "cloud-v2",
        "release": os.getenv("REPOGUIDE_RELEASE", "local"),
        "prompt_retrieval": quality_fingerprint(),
        "question": state["question"],
        "repo_id": state["repo_id"],
        "commit": state.get("commit_sha"),
        "policy": state.get("docs_policy"),
        "sources": state.get("sources", []),
        "docs": state.get("external_evidence", []),
        "provider": provider,
        "model": model,
        "generation_config": {
            "context_chars": settings.context_char_budget,
            "openai_reasoning": settings.openai_reasoning_effort,
            "openai_max_output": settings.openai_max_output_tokens,
        },
        "history": state.get("history", []),
        "focus": state.get("focus", {}),
    }
    fingerprint = hashlib.sha256(
        json.dumps(material, sort_keys=True, default=str).encode()
    ).hexdigest()
    return (
        "repoguide:"
        + os.getenv("REPOGUIDE_CACHE_NAMESPACE", "local")
        + ":answer:"
        + fingerprint
    )


def load_result(key: str) -> dict | None:
    if os.getenv("REPOGUIDE_EVALUATION") == "true":
        return None
    try:
        c = cache_client()
        return json.loads(value) if c and (value := c.get(key)) else None
    except Exception:
        return None  # optional cache should not make the API unavailable


def save_result(key: str, result: dict, ttl: int = 300) -> None:
    if os.getenv("REPOGUIDE_EVALUATION") == "true":
        return
    try:
        c = cache_client()
        if c:
            c.setex(key, ttl, json.dumps(result, default=str))
    except Exception:
        pass


def tool_cache_key(provider: str, query: dict) -> str:
    material = json.dumps(
        {"provider": provider, "query": query, "version": quality_fingerprint()},
        sort_keys=True,
        default=str,
    )
    return (
        "repoguide:"
        + os.getenv("REPOGUIDE_CACHE_NAMESPACE", "local")
        + ":tool:"
        + hashlib.sha256(material.encode()).hexdigest()
    )


def load_tool(key: str) -> dict | None:
    return load_result(key)


def save_tool(key: str, value: dict, ttl: int = 3600) -> None:
    save_result(key, value, ttl=ttl)
